from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Mapping
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

RETENTION_MANIFEST_SCHEMA = "retention-manifest-v1"
RETENTION_AUDIT_SCHEMA = "retention-audit-v1"

RetentionClassification = Literal[
    "contract-protected",
    "lineage-only",
    "reproducible-ephemeral",
    "unknown",
]
RetentionPlannedAction = Literal["retain", "human-review", "delete", "defer"]


def _non_empty(value: str) -> str:
    if not value.strip():
        raise ValueError("value must not be empty")
    return value


def _is_forbidden_secret_path(value: str) -> bool:
    return any(part == ".env" or part.startswith(".env.") for part in value.replace("\\", "/").split("/"))


def _is_forbidden_content_path(value: str) -> bool:
    forbidden = {"raw", "raw_payload", "raw_prompt", "raw_provider_payload", "provider_payload"}
    parts = PurePosixPath(value.replace("\\", "/")).parts
    return any(part.lower() in forbidden for part in parts)


class RetentionEvidenceReference(BaseModel):
    """A tracked reference that can prove a root identity without copying its facts."""

    model_config = ConfigDict(extra="forbid")

    path: str
    identity_field: str | None = None
    expected_identity: str | None = None

    _validate_path = field_validator("path")(_non_empty)

    @field_validator("identity_field", "expected_identity")
    @classmethod
    def _validate_optional_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("optional evidence identity values must not be empty")
        return value


class DuplicateEvidence(BaseModel):
    """Exact candidate/retained equality evidence for a dry-run delete allowlist."""

    model_config = ConfigDict(extra="forbid")

    candidate_root: str
    retained_root: str
    relative_files: list[str]
    sha256_map: dict[str, str]
    expected_bytes: int = Field(ge=0)
    approved_action: Literal["delete"]

    _validate_roots = field_validator("candidate_root", "retained_root")(_non_empty)

    @field_validator("relative_files")
    @classmethod
    def _validate_file_names(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("duplicate relative file names must not be empty")
        return value

    @field_validator("sha256_map")
    @classmethod
    def _validate_hash_values(cls, value: dict[str, str]) -> dict[str, str]:
        for relative_path, digest in value.items():
            if not relative_path.strip():
                raise ValueError("duplicate hash map paths must not be empty")
            if len(digest) != 64 or any(character not in "0123456789abcdefABCDEF" for character in digest):
                raise ValueError(f"invalid SHA-256 value for {relative_path}")
        return value


class CacheEvidence(BaseModel):
    """Evidence that an exact cache root can be rebuilt after review."""

    model_config = ConfigDict(extra="forbid")

    exact_root: str
    producer: str
    rebuild_validation: str

    _validate_text = field_validator("exact_root", "producer", "rebuild_validation")(_non_empty)


class RetentionEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: str
    root_type: Literal["file", "directory"]
    ownership: str
    classification: RetentionClassification
    basis: str
    planned_action: RetentionPlannedAction
    evidence_reference: RetentionEvidenceReference | None = None
    duplicate_evidence: DuplicateEvidence | None = None
    cache_evidence: CacheEvidence | None = None

    _validate_text = field_validator("root", "ownership", "basis")(_non_empty)


class RetentionManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["retention-manifest-v1"]
    entries: list[RetentionEntry]


class RetentionViolation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    root: str
    message: str


class RetentionEntryAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: str
    classification: RetentionClassification
    status: Literal["protected", "approved", "human-review", "deferred", "rejected"]
    observed_bytes: int = Field(ge=0)
    violations: list[str]


class ExactCleanupEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_root: str
    path: str
    action: Literal["delete"]
    bytes: int = Field(ge=0)
    sha256: str
    evidence_kind: Literal["duplicate", "cache"]

    @field_validator("source_root", "path", "sha256")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        return _non_empty(value)


class DirectoryCleanupEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    action: Literal["delete"]
    verified_empty_after_file_actions: bool
    files_processed: list[str]
    directories_processed: list[str]


class RetentionAuditResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["retention-audit-v1"]
    entry_results: list[RetentionEntryAudit]
    protected_roots: list[str]
    approved_candidates: list[str]
    human_review_roots: list[str]
    deferred_unknowns: list[str]
    approved_actions: list[ExactCleanupEvidence]
    approved_directories: list[DirectoryCleanupEvidence]
    aggregate_bytes: int = Field(ge=0)
    protected_bytes: int = Field(ge=0)
    lineage_bytes: int = Field(ge=0)
    unknown_bytes: int = Field(ge=0)
    violations: list[RetentionViolation]
    ready_for_cleanup: bool


class _FileObservation:
    def __init__(self, path: str, size: int, sha256: str | None) -> None:
        self.path = path
        self.size = size
        self.sha256 = sha256


class _DirectoryObservation:
    def __init__(self, path: str) -> None:
        self.path = path


class _EntryOutcome:
    def __init__(self, entry: RetentionEntry) -> None:
        self.entry = entry
        self.observed_bytes = 0
        self.status: Literal["protected", "approved", "human-review", "deferred", "rejected"] = "rejected"
        self.violations: list[RetentionViolation] = []
        self.actions: list[ExactCleanupEvidence] = []
        self.directories: list[DirectoryCleanupEvidence] = []

    def add_violation(self, code: str, message: str, *, root: str | None = None) -> None:
        self.violations.append(RetentionViolation(code=code, root=root or self.entry.root, message=message))


class _PathValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class RetentionAuditor:
    """Read-only retention manifest auditor.

    The Interface accepts a typed manifest and returns deterministic aggregate evidence.
    It reads path metadata, referenced JSON identities, and hashes for explicitly
    authorized duplicate/cache roots. It never mutates the filesystem or contacts a
    provider/data source.
    """

    def __init__(self, repo_root: str | Path) -> None:
        root = Path(repo_root)
        if root.is_symlink():
            raise ValueError("repository root must not be a symlink")
        if not root.is_dir():
            raise FileNotFoundError(f"repository root does not exist: {root}")
        self.repo_root = root.resolve()

    def audit(
        self,
        manifest: RetentionManifest | Mapping[str, Any] | str | Path,
    ) -> RetentionAuditResult:
        typed_manifest = self._coerce_manifest(manifest)
        entries = sorted(typed_manifest.entries, key=lambda entry: entry.root)
        duplicate_roots = self._duplicate_roots(entries)
        outcomes: list[_EntryOutcome] = []

        for entry in entries:
            outcome = _EntryOutcome(entry)
            if entry.root in duplicate_roots:
                outcome.add_violation(
                    "classification-conflict",
                    "the same root appears more than once in the retention manifest",
                )
            self._audit_entry(outcome)
            outcomes.append(outcome)

        violations = sorted(
            [violation for outcome in outcomes for violation in outcome.violations],
            key=lambda violation: (violation.root, violation.code, violation.message),
        )
        approved_actions = sorted(
            [action for outcome in outcomes for action in outcome.actions],
            key=lambda action: (action.path, action.sha256),
        )
        approved_directories = sorted(
            [directory for outcome in outcomes for directory in outcome.directories],
            key=lambda directory: (-directory.path.count("/"), directory.path),
        )
        entry_results = [
            RetentionEntryAudit(
                root=outcome.entry.root,
                classification=outcome.entry.classification,
                status=outcome.status,
                observed_bytes=outcome.observed_bytes,
                violations=sorted({violation.code for violation in outcome.violations}),
            )
            for outcome in outcomes
        ]
        protected_roots = sorted(
            outcome.entry.root for outcome in outcomes if outcome.entry.classification == "contract-protected"
        )
        approved_candidates = sorted(
            outcome.entry.root for outcome in outcomes if outcome.actions and outcome.status == "approved"
        )
        human_review_roots = sorted(
            outcome.entry.root
            for outcome in outcomes
            if outcome.entry.classification in {"lineage-only", "unknown"}
            or (outcome.entry.classification == "reproducible-ephemeral" and outcome.violations)
        )
        deferred_unknowns = sorted(
            outcome.entry.root for outcome in outcomes if outcome.entry.classification == "unknown"
        )
        protected_bytes = sum(
            outcome.observed_bytes for outcome in outcomes if outcome.entry.classification == "contract-protected"
        )
        lineage_bytes = sum(
            outcome.observed_bytes for outcome in outcomes if outcome.entry.classification == "lineage-only"
        )
        unknown_bytes = sum(outcome.observed_bytes for outcome in outcomes if outcome.entry.classification == "unknown")
        aggregate_bytes = sum(action.bytes for action in approved_actions)
        ready_for_cleanup = not violations and not human_review_roots and not deferred_unknowns

        return RetentionAuditResult(
            schema_version=RETENTION_AUDIT_SCHEMA,
            entry_results=entry_results,
            protected_roots=protected_roots,
            approved_candidates=approved_candidates,
            human_review_roots=human_review_roots,
            deferred_unknowns=deferred_unknowns,
            approved_actions=approved_actions,
            approved_directories=approved_directories,
            aggregate_bytes=aggregate_bytes,
            protected_bytes=protected_bytes,
            lineage_bytes=lineage_bytes,
            unknown_bytes=unknown_bytes,
            violations=violations,
            ready_for_cleanup=ready_for_cleanup,
        )

    def _coerce_manifest(
        self,
        manifest: RetentionManifest | Mapping[str, Any] | str | Path,
    ) -> RetentionManifest:
        if isinstance(manifest, RetentionManifest):
            return manifest
        if isinstance(manifest, (str, Path)):
            return load_retention_manifest(manifest)
        return RetentionManifest.model_validate(manifest)

    @staticmethod
    def _duplicate_roots(entries: list[RetentionEntry]) -> set[str]:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for entry in entries:
            if entry.root in seen:
                duplicates.add(entry.root)
            seen.add(entry.root)
        return duplicates

    def _audit_entry(self, outcome: _EntryOutcome) -> None:
        entry = outcome.entry
        try:
            root_path = self._safe_repo_path(entry.root)
        except _PathValidationError as error:
            outcome.add_violation(error.code, str(error))
            outcome.status = "deferred" if entry.classification == "unknown" else "rejected"
            return
        if _is_forbidden_secret_path(entry.root):
            outcome.add_violation("forbidden-secret-path", "retention manifest must not inspect environment files")
            outcome.status = "deferred" if entry.classification == "unknown" else "rejected"
            return
        if entry.classification == "reproducible-ephemeral" and _is_forbidden_content_path(entry.root):
            outcome.add_violation(
                "forbidden-payload-path", "rebuild evidence must not hash raw or provider payload roots"
            )
            outcome.status = "rejected"
            return

        root_stat = self._lstat(root_path, outcome, missing_code="missing-root")
        if root_stat is None:
            outcome.status = "deferred" if entry.classification == "unknown" else "rejected"
            return
        if stat.S_ISLNK(root_stat.st_mode):
            outcome.add_violation("symlink-component", "root must not be a symlink")
            outcome.status = "deferred" if entry.classification == "unknown" else "rejected"
            return
        if not self._matches_root_type(entry, root_stat.st_mode, outcome):
            outcome.status = "deferred" if entry.classification == "unknown" else "rejected"
            return

        observations, directories = self._inventory(root_path, entry.root, hash_files=False, outcome=outcome)
        outcome.observed_bytes = sum(observation.size for observation in observations)
        self._verify_evidence(entry, outcome)

        if entry.classification == "contract-protected":
            outcome.status = "protected"
            if entry.planned_action != "retain":
                outcome.add_violation("protected-action", "contract-protected roots may only be retained")
            if entry.duplicate_evidence or entry.cache_evidence:
                outcome.add_violation("classification-conflict", "protected roots cannot carry delete evidence")
            if outcome.violations:
                outcome.status = "rejected"
            return

        if entry.classification == "lineage-only":
            outcome.status = "human-review"
            if entry.planned_action not in {"retain", "human-review"}:
                outcome.add_violation("lineage-action", "lineage-only roots require retain or human-review")
            if entry.duplicate_evidence or entry.cache_evidence:
                outcome.add_violation("classification-conflict", "lineage-only roots cannot carry delete evidence")
            if outcome.violations:
                outcome.status = "rejected"
            return

        if entry.classification == "unknown":
            outcome.status = "deferred"
            if entry.planned_action != "defer":
                outcome.add_violation("unknown-action", "unknown roots must use the defer action")
            if entry.duplicate_evidence or entry.cache_evidence:
                outcome.add_violation("classification-conflict", "unknown roots cannot carry delete evidence")
            if outcome.violations:
                outcome.status = "rejected"
            return

        outcome.status = "rejected"
        if entry.planned_action != "delete":
            outcome.add_violation("ephemeral-action", "reproducible-ephemeral roots require the delete action")
        if outcome.violations:
            return
        if entry.duplicate_evidence and entry.cache_evidence:
            outcome.add_violation("classification-conflict", "a root cannot use duplicate and cache evidence together")
        elif entry.duplicate_evidence:
            self._authorize_duplicate(entry, root_path, observations, directories, outcome)
        elif entry.cache_evidence:
            self._authorize_cache(entry, observations, directories, outcome)
        else:
            outcome.add_violation(
                "missing-rebuild-evidence",
                "reproducible-ephemeral roots require duplicate or cache evidence",
            )
        if not outcome.violations and outcome.actions:
            outcome.status = "approved"
        elif not outcome.violations:
            outcome.add_violation("empty-allowlist", "no regular files were authorized for the planned action")

    def _matches_root_type(self, entry: RetentionEntry, mode: int, outcome: _EntryOutcome) -> bool:
        expected_directory = entry.root_type == "directory"
        actual_directory = stat.S_ISDIR(mode)
        actual_file = stat.S_ISREG(mode)
        if expected_directory and not actual_directory:
            outcome.add_violation("unexpected-file-type", "manifest expects a regular directory")
            return False
        if not expected_directory and not actual_file:
            outcome.add_violation("unexpected-file-type", "manifest expects a regular file")
            return False
        return True

    def _verify_evidence(self, entry: RetentionEntry, outcome: _EntryOutcome) -> None:
        reference = entry.evidence_reference
        if reference is None:
            if entry.classification in {"contract-protected", "lineage-only"}:
                outcome.add_violation("missing-evidence", "protected and lineage roots require an evidence reference")
            return
        try:
            reference_path = self._safe_repo_path(reference.path)
        except _PathValidationError as error:
            outcome.add_violation(error.code, str(error), root=reference.path)
            return
        if _is_forbidden_secret_path(reference.path):
            outcome.add_violation("forbidden-secret-path", "evidence reference must not be an environment file")
            return
        reference_stat = self._lstat(reference_path, outcome, missing_code="missing-evidence", root=reference.path)
        if reference_stat is None:
            return
        if stat.S_ISLNK(reference_stat.st_mode) or not stat.S_ISREG(reference_stat.st_mode):
            outcome.add_violation(
                "unexpected-file-type", "evidence reference must be a regular file", root=reference.path
            )
            return
        if reference.identity_field is None and reference.expected_identity is None:
            return
        if reference.identity_field is None or reference.expected_identity is None:
            outcome.add_violation("evidence-mismatch", "evidence identity field and expected value must be paired")
            return
        if reference_path.suffix.lower() != ".json":
            outcome.add_violation(
                "evidence-mismatch", "machine identity evidence must be a JSON file", root=reference.path
            )
            return
        try:
            evidence = json.loads(reference_path.read_text(encoding="utf-8"))
            value: Any = evidence
            for key in reference.identity_field.split("."):
                if not isinstance(value, Mapping) or key not in value:
                    raise KeyError(key)
                value = value[key]
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as error:
            outcome.add_violation("evidence-mismatch", f"cannot read identity evidence: {error}", root=reference.path)
            return
        if value != reference.expected_identity:
            outcome.add_violation(
                "evidence-mismatch",
                f"identity field {reference.identity_field} does not match the expected value",
                root=reference.path,
            )

    def _authorize_duplicate(
        self,
        entry: RetentionEntry,
        candidate_path: Path,
        candidate_observations: list[_FileObservation],
        candidate_directories: list[_DirectoryObservation],
        outcome: _EntryOutcome,
    ) -> None:
        evidence = entry.duplicate_evidence
        assert evidence is not None
        if evidence.candidate_root != entry.root:
            outcome.add_violation("duplicate-root-mismatch", "duplicate candidate_root must equal the manifest root")
            return
        if evidence.retained_root == entry.root:
            outcome.add_violation("duplicate-root-mismatch", "candidate and retained roots must be different")
            return
        if _is_forbidden_secret_path(evidence.retained_root):
            outcome.add_violation(
                "forbidden-secret-path",
                "retained duplicate roots must not inspect environment files",
                root=evidence.retained_root,
            )
            return
        if _is_forbidden_content_path(evidence.retained_root):
            outcome.add_violation(
                "forbidden-payload-path",
                "retained duplicate roots containing raw or provider payloads cannot be hashed",
                root=evidence.retained_root,
            )
            return
        try:
            retained_path = self._safe_repo_path(evidence.retained_root)
        except _PathValidationError as error:
            outcome.add_violation(error.code, str(error), root=evidence.retained_root)
            return
        retained_stat = self._lstat(
            retained_path, outcome, missing_code="duplicate-mismatch", root=evidence.retained_root
        )
        if retained_stat is None:
            return
        if stat.S_ISLNK(retained_stat.st_mode):
            outcome.add_violation(
                "symlink-component", "retained duplicate root must not be a symlink", root=evidence.retained_root
            )
            return
        if entry.root_type == "directory" and not stat.S_ISDIR(retained_stat.st_mode):
            outcome.add_violation("duplicate-mismatch", "candidate and retained roots have different file types")
            return
        if entry.root_type == "file" and not stat.S_ISREG(retained_stat.st_mode):
            outcome.add_violation("duplicate-mismatch", "candidate and retained roots have different file types")
            return
        if outcome.violations:
            return
        retained_observations, _ = self._inventory(
            retained_path,
            evidence.retained_root,
            hash_files=True,
            outcome=outcome,
        )
        if outcome.violations:
            return
        if any(_is_forbidden_content_path(observation.path) for observation in candidate_observations):
            outcome.add_violation(
                "forbidden-payload-path",
                "candidate roots containing raw or provider payloads cannot be hashed",
            )
            return
        self._rehash_observations(candidate_path, entry.root, candidate_observations, outcome)
        if outcome.violations:
            return
        expected_files = list(evidence.relative_files)
        expected_set = set(expected_files)
        expected_hashes = set(evidence.sha256_map)
        candidate_map = {
            observation.path.removeprefix(f"{entry.root}/"): observation for observation in candidate_observations
        }
        retained_map = {
            observation.path.removeprefix(f"{evidence.retained_root}/"): observation
            for observation in retained_observations
        }
        invalid_paths = self._validate_relative_file_names(expected_files, outcome)
        if invalid_paths or len(expected_set) != len(expected_files):
            outcome.add_violation(
                "duplicate-mismatch", "duplicate evidence contains duplicate or unsafe relative paths"
            )
        if expected_set != expected_hashes:
            outcome.add_violation("duplicate-mismatch", "duplicate evidence file and hash sets are not identical")
        if set(candidate_map) != expected_set or set(retained_map) != expected_set:
            outcome.add_violation(
                "duplicate-mismatch", "candidate or retained regular-file set differs from the expected set"
            )
        if sum(observation.size for observation in candidate_observations) != evidence.expected_bytes:
            outcome.add_violation("duplicate-mismatch", "candidate bytes do not match expected_bytes")
        if sum(observation.size for observation in retained_observations) != evidence.expected_bytes:
            outcome.add_violation("duplicate-mismatch", "retained bytes do not match expected_bytes")
        for relative_path in sorted(expected_set):
            expected_hash = evidence.sha256_map.get(relative_path, "").lower()
            candidate_hash = candidate_map.get(relative_path).sha256 if relative_path in candidate_map else None
            retained_hash = retained_map.get(relative_path).sha256 if relative_path in retained_map else None
            if candidate_hash != expected_hash or retained_hash != expected_hash:
                outcome.add_violation("duplicate-mismatch", f"SHA-256 mismatch for {relative_path}")
        if outcome.violations:
            return
        for observation in sorted(candidate_observations, key=lambda item: item.path):
            assert observation.sha256 is not None
            outcome.actions.append(
                ExactCleanupEvidence(
                    source_root=entry.root,
                    path=observation.path,
                    action="delete",
                    bytes=observation.size,
                    sha256=observation.sha256,
                    evidence_kind="duplicate",
                )
            )
        self._add_directory_action(candidate_directories, candidate_observations, outcome)

    def _authorize_cache(
        self,
        entry: RetentionEntry,
        observations: list[_FileObservation],
        directories: list[_DirectoryObservation],
        outcome: _EntryOutcome,
    ) -> None:
        evidence = entry.cache_evidence
        assert evidence is not None
        if evidence.exact_root != entry.root:
            outcome.add_violation("cache-root-mismatch", "cache exact_root must equal the manifest root")
            return
        if not observations:
            outcome.add_violation("empty-allowlist", "cache root contains no regular files")
            return
        for observation in sorted(observations, key=lambda item: item.path):
            self._rehash_observation(observation, outcome)
            if observation.sha256 is None:
                continue
            outcome.actions.append(
                ExactCleanupEvidence(
                    source_root=entry.root,
                    path=observation.path,
                    action="delete",
                    bytes=observation.size,
                    sha256=observation.sha256,
                    evidence_kind="cache",
                )
            )
        if outcome.violations:
            outcome.actions.clear()
            return
        self._add_directory_action(directories, observations, outcome)

    def _add_directory_action(
        self,
        directories: list[_DirectoryObservation],
        observations: list[_FileObservation],
        outcome: _EntryOutcome,
    ) -> None:
        if not directories:
            return
        file_paths = sorted(observation.path for observation in observations)
        directory_paths = sorted(
            (directory.path for directory in directories),
            key=lambda path: (-path.count("/"), path),
        )
        for directory_path in directory_paths:
            prefix = f"{directory_path}/"
            files = [path for path in file_paths if path.startswith(prefix)]
            children = [path for path in directory_paths if path != directory_path and path.startswith(prefix)]
            outcome.directories.append(
                DirectoryCleanupEvidence(
                    path=directory_path,
                    action="delete",
                    verified_empty_after_file_actions=True,
                    files_processed=files,
                    directories_processed=children,
                )
            )

    def _validate_relative_file_names(self, paths: list[str], outcome: _EntryOutcome) -> bool:
        invalid = False
        for path in paths:
            try:
                self._validate_relative(path)
            except _PathValidationError as error:
                outcome.add_violation(error.code, str(error))
                invalid = True
        return invalid

    def _inventory(
        self,
        root_path: Path,
        root_relative: str,
        *,
        hash_files: bool,
        outcome: _EntryOutcome,
    ) -> tuple[list[_FileObservation], list[_DirectoryObservation]]:
        observations: list[_FileObservation] = []
        directories: list[_DirectoryObservation] = []

        def visit(path: Path, relative: str) -> None:
            try:
                with os.scandir(path) as iterator:
                    entries = sorted(iterator, key=lambda entry: entry.name)
            except OSError as error:
                outcome.add_violation("read-error", f"cannot inspect directory metadata: {error}")
                return
            directories.append(_DirectoryObservation(relative))
            for item in entries:
                child = Path(item.path)
                try:
                    child_stat = item.stat(follow_symlinks=False)
                except OSError as error:
                    outcome.add_violation("read-error", f"cannot inspect filesystem metadata: {error}")
                    continue
                child_relative = f"{relative}/{item.name}"
                if stat.S_ISLNK(child_stat.st_mode):
                    outcome.add_violation(
                        "symlink-component", "retention roots must not contain symlink entries", root=child_relative
                    )
                elif stat.S_ISDIR(child_stat.st_mode):
                    visit(child, child_relative)
                elif stat.S_ISREG(child_stat.st_mode):
                    observation = _FileObservation(child_relative, child_stat.st_size, None)
                    observations.append(observation)
                    if hash_files:
                        if _is_forbidden_content_path(child_relative):
                            outcome.add_violation(
                                "forbidden-payload-path",
                                "raw or provider payload files must not be hashed",
                                root=child_relative,
                            )
                        else:
                            self._rehash_observation(observation, outcome, path=child)
                else:
                    outcome.add_violation(
                        "unexpected-file-type", "retention roots may contain regular files only", root=child_relative
                    )

        try:
            root_stat = root_path.stat()
        except OSError as error:
            outcome.add_violation("read-error", f"cannot inspect filesystem metadata: {error}")
            return observations, directories
        if stat.S_ISREG(root_stat.st_mode):
            observation = _FileObservation(root_relative, root_stat.st_size, None)
            observations.append(observation)
            if hash_files:
                self._rehash_observation(observation, outcome, path=root_path)
        elif stat.S_ISDIR(root_stat.st_mode):
            visit(root_path, root_relative)
        return observations, directories

    def _rehash_observations(
        self,
        root_path: Path,
        root_relative: str,
        observations: list[_FileObservation],
        outcome: _EntryOutcome,
    ) -> None:
        prefix = f"{root_relative}/"
        for observation in observations:
            if observation.path == root_relative:
                path = root_path
            else:
                relative_path = observation.path.removeprefix(prefix)
                path = root_path / relative_path
            self._rehash_observation(observation, outcome, path=path)

    def _rehash_observation(
        self,
        observation: _FileObservation,
        outcome: _EntryOutcome,
        *,
        path: Path | None = None,
    ) -> None:
        if observation.sha256 is not None:
            return
        if path is None:
            path = self.repo_root / observation.path
        digest = hashlib.sha256()
        try:
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(65536), b""):
                    digest.update(chunk)
        except OSError as error:
            outcome.add_violation("read-error", f"cannot hash regular file: {error}", root=observation.path)
            return
        observation.sha256 = digest.hexdigest()

    def _lstat(
        self,
        path: Path,
        outcome: _EntryOutcome,
        *,
        missing_code: str,
        root: str | None = None,
    ) -> os.stat_result | None:
        try:
            return path.lstat()
        except FileNotFoundError:
            outcome.add_violation(missing_code, "path does not exist", root=root)
        except OSError as error:
            outcome.add_violation("read-error", f"cannot inspect path metadata: {error}", root=root)
        return None

    def _safe_repo_path(self, value: str) -> Path:
        parts = self._validate_relative(value)
        current = self.repo_root
        for part in parts:
            current = current / part
            try:
                mode = current.lstat().st_mode
            except FileNotFoundError:
                break
            if stat.S_ISLNK(mode):
                raise _PathValidationError("symlink-component", "path contains a symlink component")
        return current

    @staticmethod
    def _validate_relative(value: str) -> tuple[str, ...]:
        if not value or value == ".":
            raise _PathValidationError("invalid-path", "path must name a repository-relative root")
        if "\x00" in value or "\\" in value:
            raise _PathValidationError("invalid-path", "path must use safe POSIX-relative components")
        if PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute() or PureWindowsPath(value).drive:
            raise _PathValidationError("absolute-path", "absolute paths are not allowed")
        parts = PurePosixPath(value).parts
        if any(part == ".." for part in parts):
            raise _PathValidationError("path-escape", "path escape components are not allowed")
        if any(part in {"", "."} for part in parts):
            raise _PathValidationError("invalid-path", "path contains an empty or current-directory component")
        return parts


def load_retention_manifest(path: str | Path) -> RetentionManifest:
    manifest_path = Path(path)
    if _is_forbidden_secret_path(manifest_path.name):
        raise ValueError("retention manifest must not be an environment file")
    if manifest_path.is_symlink():
        raise ValueError("retention manifest must not be a symlink")
    if not manifest_path.is_file():
        raise FileNotFoundError(f"retention manifest does not exist: {manifest_path}")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid retention manifest: {error}") from error
    return RetentionManifest.model_validate(payload)


def audit_retention(
    manifest: RetentionManifest | Mapping[str, Any] | str | Path,
    *,
    repo_root: str | Path = ".",
) -> RetentionAuditResult:
    return RetentionAuditor(repo_root).audit(manifest)


def render_retention_report(result: RetentionAuditResult) -> str:
    lines = [
        "# Retention Audit Dry Run",
        "",
        f"- schema: `{result.schema_version}`",
        f"- ready_for_cleanup: `{str(result.ready_for_cleanup).lower()}`",
        f"- aggregate_bytes: `{result.aggregate_bytes}`",
        f"- protected_bytes: `{result.protected_bytes}`",
        f"- lineage_bytes: `{result.lineage_bytes}`",
        f"- unknown_bytes: `{result.unknown_bytes}`",
        f"- protected_roots: `{len(result.protected_roots)}`",
        f"- approved_candidates: `{len(result.approved_candidates)}`",
        f"- human_review_roots: `{len(result.human_review_roots)}`",
        f"- deferred_unknowns: `{len(result.deferred_unknowns)}`",
        "",
        "## Protected Roots",
        "",
    ]
    lines.extend(f"- `{root}`" for root in result.protected_roots)
    if not result.protected_roots:
        lines.append("- none")
    action_totals: dict[str, tuple[int, int, str]] = {}
    for action in result.approved_actions:
        total_bytes, file_count, action_name = action_totals.get(action.source_root, (0, 0, action.action))
        action_totals[action.source_root] = (total_bytes + action.bytes, file_count + 1, action_name)
    lines.extend(
        [
            "",
            "## Approved Candidates",
            "",
            f"Structured exact file actions: `{len(result.approved_actions)}`.",
            "",
            "| candidate root | action | regular files | aggregate bytes |",
            "|---|---|---:|---:|",
        ]
    )
    for root in sorted(action_totals):
        total_bytes, file_count, action = action_totals[root]
        lines.append(f"| `{root}` | `{action}` | {file_count} | {total_bytes} |")
    if not action_totals:
        lines.append("| none | | 0 | 0 |")
    lines.extend(["", "## Approved Directory Postconditions", ""])
    lines.append("Structured directory postconditions are recorded per exact directory in the structured result.")
    for root in sorted(result.approved_candidates):
        directories = [
            directory
            for directory in result.approved_directories
            if directory.path == root or directory.path.startswith(f"{root}/")
        ]
        if directories:
            lines.append(
                f"- `{root}`: {len(directories)} directory postcondition(s); all recorded files and child directories must be processed before removal."
            )
    if not result.approved_directories:
        lines.append("- none")
    lines.extend(["", "## Human Review Roots", ""])
    lines.extend(f"- `{root}`" for root in result.human_review_roots)
    if not result.human_review_roots:
        lines.append("- none")
    lines.extend(["", "## Deferred Unknowns", ""])
    lines.extend(f"- `{root}`" for root in result.deferred_unknowns)
    if not result.deferred_unknowns:
        lines.append("- none")
    lines.extend(["", "## Violations", ""])
    for violation in result.violations:
        lines.append(f"- `{violation.code}` at `{violation.root}`: {violation.message}")
    if not result.violations:
        lines.append("- none")
    return "\n".join(lines) + "\n"
