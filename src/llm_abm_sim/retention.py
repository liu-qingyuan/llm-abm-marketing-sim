from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from collections.abc import Mapping as _Mapping
from pathlib import Path as _Path
from pathlib import PurePosixPath as _PurePosixPath
from pathlib import PureWindowsPath as _PureWindowsPath
from typing import Any as _Any
from typing import Literal as _Literal

from pydantic import BaseModel as _BaseModel
from pydantic import ConfigDict as _ConfigDict
from pydantic import Field as _Field
from pydantic import ValidationError as _ValidationError
from pydantic import field_validator as _field_validator

__all__ = ["RetentionAuditResult", "audit_retention", "render_retention_report"]

_MANIFEST_SCHEMA = "retention-manifest-v2"
_AUDIT_SCHEMA = "retention-audit-v2"
_RetentionClassification = _Literal[
    "contract-protected",
    "lineage-only",
    "reproducible-ephemeral",
    "unknown",
]


def _non_empty(value: str) -> str:
    if not value.strip():
        raise ValueError("value must not be empty")
    return value


def _is_secret_path(value: str) -> bool:
    return any(part == ".env" or part.startswith(".env.") for part in value.lower().replace("\\", "/").split("/"))


def _is_payload_path(value: str) -> bool:
    forbidden = {
        "raw",
        "raw_payload",
        "raw-payload",
        "raw_prompt",
        "raw-prompt",
        "provider_payload",
        "provider-payload",
    }
    return any(part in forbidden for part in _PurePosixPath(value.lower().replace("\\", "/")).parts)


class _RetentionEvidenceReference(_BaseModel):
    """A human or structured reference that establishes a root's ownership."""

    model_config = _ConfigDict(extra="forbid")

    path: str
    identity_field: str | None = None
    expected_identity: _Any | None = None

    _validate_path = _field_validator("path")(_non_empty)

    @_field_validator("identity_field")
    @classmethod
    def _validate_identity_field(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("identity_field must not be empty")
        return value


class _RetentionEntry(_BaseModel):
    model_config = _ConfigDict(extra="forbid")

    root: str
    root_type: _Literal["file", "directory"]
    ownership: str
    classification: _RetentionClassification
    basis: str
    evidence_reference: _RetentionEvidenceReference | None = None

    _validate_text = _field_validator("root", "ownership", "basis")(_non_empty)


class _RetentionManifest(_BaseModel):
    model_config = _ConfigDict(extra="forbid")

    schema_version: _Literal["retention-manifest-v2"]
    entries: list[_RetentionEntry]


class _RetentionViolation(_BaseModel):
    model_config = _ConfigDict(extra="forbid")

    code: str
    root: str
    message: str


class _RetentionEntryAudit(_BaseModel):
    model_config = _ConfigDict(extra="forbid")

    root: str
    root_type: _Literal["file", "directory"]
    classification: _RetentionClassification
    status: _Literal["valid", "rejected"]
    regular_file_count: int = _Field(ge=0)
    directory_count: int = _Field(ge=0)
    observed_bytes: int = _Field(ge=0)
    violations: list[str]


class _RetentionAggregateMetadata(_BaseModel):
    model_config = _ConfigDict(extra="forbid")

    regular_file_count: int = _Field(ge=0)
    directory_count: int = _Field(ge=0)
    observed_bytes: int = _Field(ge=0)


class RetentionAuditResult(_BaseModel):
    """Deterministic, read-only evidence for one tracked retention manifest.

    ``audit_valid`` only means that the explicit roots and their evidence satisfy
    the policy. It never grants deletion eligibility or authorizes a filesystem
    action. Root contents are represented by metadata counts and bytes only.
    """

    model_config = _ConfigDict(extra="forbid")

    schema_version: _Literal["retention-audit-v2"]
    manifest_sha256: str | None
    audit_valid: bool
    entry_results: list[_RetentionEntryAudit]
    protected_roots: list[str]
    lineage_roots: list[str]
    ephemeral_roots: list[str]
    unresolved_roots: list[str]
    metadata: _RetentionAggregateMetadata
    violations: list[_RetentionViolation]

    @property
    def aggregate_metadata(self) -> _RetentionAggregateMetadata:
        """Return the single serialized aggregate metadata record."""

        return self.metadata

    @property
    def regular_file_count(self) -> int:
        return self.metadata.regular_file_count

    @property
    def directory_count(self) -> int:
        return self.metadata.directory_count

    @property
    def observed_bytes(self) -> int:
        return self.metadata.observed_bytes


class _EntryState:
    def __init__(self, entry: _RetentionEntry) -> None:
        self.entry = entry
        self.root_path: _Path | None = None
        self.root_stat: os.stat_result | None = None
        self.canonical_root: str | None = None
        self.violations: list[_RetentionViolation] = []
        self.regular_file_count = 0
        self.directory_count = 0
        self.observed_bytes = 0

    def add_violation(self, code: str, message: str, *, root: str | None = None) -> None:
        self.violations.append(_RetentionViolation(code=code, root=root or self.entry.root, message=message))


class _PathValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _invalid_result(
    violations: list[_RetentionViolation],
    *,
    manifest_sha256: str | None = None,
) -> RetentionAuditResult:
    return RetentionAuditResult(
        schema_version=_AUDIT_SCHEMA,
        manifest_sha256=manifest_sha256,
        audit_valid=False,
        entry_results=[],
        protected_roots=[],
        lineage_roots=[],
        ephemeral_roots=[],
        unresolved_roots=[],
        metadata=_RetentionAggregateMetadata(regular_file_count=0, directory_count=0, observed_bytes=0),
        violations=sorted(violations, key=lambda item: (item.root, item.code, item.message)),
    )


def _violation(code: str, root: str, message: str) -> _RetentionViolation:
    return _RetentionViolation(code=code, root=root, message=message)


def _validate_relative(value: str, *, label: str) -> tuple[str, ...]:
    if not value:
        raise _PathValidationError("invalid-path", f"{label} must be a repository-relative path")
    if "\x00" in value:
        raise _PathValidationError("invalid-path", f"{label} must not contain NUL bytes")
    windows_path = _PureWindowsPath(value)
    if _PurePosixPath(value).is_absolute() or windows_path.is_absolute() or windows_path.drive:
        raise _PathValidationError("absolute-path", f"{label} must not be absolute")
    if "\\" in value:
        raise _PathValidationError("invalid-path", f"{label} must use POSIX separators")
    if ".." in value.split("/"):
        raise _PathValidationError("path-escape", f"{label} must not contain path escape components")
    if "//" in value or value.endswith("/"):
        raise _PathValidationError("invalid-path", f"{label} must use one separator between components")
    parts = tuple(value.split("/"))
    if any(part in {"", "."} for part in parts):
        raise _PathValidationError("invalid-path", f"{label} must use canonical components")
    if "/".join(parts) != value:
        raise _PathValidationError("invalid-path", f"{label} must be canonical")
    return parts


def _safe_path(repo_root: _Path, parts: tuple[str, ...]) -> tuple[_Path, str | None]:
    current = repo_root
    missing = False
    for part in parts:
        current = current / part
        if missing:
            continue
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            missing = True
            continue
        except OSError as error:
            return current, f"cannot inspect path metadata: {error}"
        if stat.S_ISLNK(mode):
            return current, "path contains a symlink component"
    return current, None


def _repo_root(value: str | _Path) -> _Path:
    root = _Path(value)
    if root.is_symlink():
        raise ValueError("repository root must not be a symlink")
    if not root.is_dir():
        raise FileNotFoundError(f"repository root does not exist: {root}")
    return root.resolve()


def _manifest_path(repo_root: _Path, value: str | _Path) -> tuple[str, _Path]:
    if not isinstance(value, (str, _Path)):
        raise _PathValidationError("invalid-path", "manifest path must be a string or Path")
    raw = str(value)
    parts = _validate_relative(raw, label="manifest path")
    path, error = _safe_path(repo_root, parts)
    if error == "path contains a symlink component":
        raise _PathValidationError("symlink-component", "manifest path must not contain symlink components")
    if error is not None:
        raise _PathValidationError("read-error", error)
    return "/".join(parts), path


def _tracked_manifest(repo_root: _Path, relative_path: str) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "--error-unmatch", "--", relative_path],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return False
    return completed.stdout.splitlines() == [relative_path]


def _read_tracked_manifest(
    repo_root: _Path,
    manifest_path: str | _Path,
) -> tuple[str, bytes, _RetentionManifest] | RetentionAuditResult:
    try:
        relative_path, path = _manifest_path(repo_root, manifest_path)
    except _PathValidationError as error:
        return _invalid_result([_violation(error.code, str(manifest_path), str(error))])
    try:
        manifest_stat = path.lstat()
    except FileNotFoundError:
        return _invalid_result([_violation("missing-manifest", relative_path, "manifest does not exist")])
    except OSError as error:
        return _invalid_result([_violation("read-error", relative_path, f"cannot inspect manifest metadata: {error}")])
    if stat.S_ISLNK(manifest_stat.st_mode):
        return _invalid_result([_violation("symlink-component", relative_path, "manifest must not be a symlink")])
    if not stat.S_ISREG(manifest_stat.st_mode):
        return _invalid_result([_violation("unexpected-file-type", relative_path, "manifest must be a regular file")])
    if not _tracked_manifest(repo_root, relative_path):
        return _invalid_result([_violation("manifest-not-tracked", relative_path, "manifest must be tracked by Git")])
    try:
        raw = path.read_bytes()
    except OSError as error:
        return _invalid_result([_violation("read-error", relative_path, f"cannot read manifest: {error}")])
    digest = hashlib.sha256(raw).hexdigest()
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return _invalid_result(
            [_violation("manifest-invalid", relative_path, f"manifest is not valid JSON: {error}")],
            manifest_sha256=digest,
        )
    if not isinstance(payload, _Mapping):
        return _invalid_result(
            [_violation("manifest-invalid", relative_path, "manifest root must be a JSON object")],
            manifest_sha256=digest,
        )
    schema_version = payload.get("schema_version")
    if schema_version != _MANIFEST_SCHEMA:
        code = "unsupported-schema" if schema_version == "retention-manifest-v1" else "manifest-schema"
        message = (
            "retention-manifest-v1 is historical evidence and is not supported by the current CLI"
            if code == "unsupported-schema"
            else "manifest schema must be retention-manifest-v2"
        )
        return _invalid_result([_violation(code, relative_path, message)], manifest_sha256=digest)
    try:
        manifest = _RetentionManifest.model_validate(payload)
    except _ValidationError as error:
        return _invalid_result(
            [_violation("manifest-invalid", relative_path, f"invalid retention-manifest-v2: {error}")],
            manifest_sha256=digest,
        )
    return relative_path, raw, manifest


def _verify_evidence(repo_root: _Path, state: _EntryState) -> None:
    reference = state.entry.evidence_reference
    if reference is None:
        if state.entry.classification != "unknown":
            state.add_violation(
                "missing-evidence",
                "non-unknown roots require an evidence reference",
            )
        return
    try:
        evidence_parts = _validate_relative(reference.path, label="evidence path")
    except _PathValidationError as error:
        state.add_violation(error.code, str(error), root=reference.path)
        return
    if _is_secret_path(reference.path) or _is_payload_path(reference.path):
        state.add_violation(
            "forbidden-evidence-path",
            "evidence references must not point to secret or raw payload paths",
            root=reference.path,
        )
        return
    evidence_path, error = _safe_path(repo_root, evidence_parts)
    if error == "path contains a symlink component":
        state.add_violation(
            "symlink-component",
            "evidence reference must not contain symlink components",
            root=reference.path,
        )
        return
    if error is not None:
        state.add_violation("read-error", error, root=reference.path)
        return
    try:
        evidence_stat = evidence_path.lstat()
    except FileNotFoundError:
        state.add_violation("missing-evidence", "evidence reference does not exist", root=reference.path)
        return
    except OSError as error:
        state.add_violation("read-error", f"cannot inspect evidence metadata: {error}", root=reference.path)
        return
    if stat.S_ISLNK(evidence_stat.st_mode) or not stat.S_ISREG(evidence_stat.st_mode):
        state.add_violation(
            "unexpected-file-type",
            "evidence reference must be a regular non-symlink file",
            root=reference.path,
        )
        return
    identity_field = reference.identity_field
    has_identity_field = identity_field is not None
    has_expected_identity = "expected_identity" in reference.model_fields_set
    if not has_identity_field and not has_expected_identity:
        return
    if not has_identity_field or not has_expected_identity:
        state.add_violation(
            "evidence-mismatch",
            "identity_field and expected_identity must be provided together",
            root=reference.path,
        )
        return
    if evidence_path.suffix.lower() != ".json":
        state.add_violation(
            "evidence-mismatch",
            "machine identity evidence must be a JSON file; Markdown is human reference only",
            root=reference.path,
        )
        return
    assert identity_field is not None
    fields = identity_field.split(".")
    if any(not field for field in fields):
        state.add_violation("evidence-mismatch", "identity_field must use non-empty components", root=reference.path)
        return
    try:
        evidence = json.loads(evidence_path.read_bytes())
        value: _Any = evidence
        for field in fields:
            if not isinstance(value, _Mapping) or field not in value:
                raise KeyError(field)
            value = value[field]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        state.add_violation("evidence-mismatch", f"cannot read identity evidence: {error}", root=reference.path)
        return
    if type(value) is not type(reference.expected_identity) or value != reference.expected_identity:
        state.add_violation(
            "evidence-mismatch",
            f"identity field {identity_field} does not match the expected value",
            root=reference.path,
        )


def _inventory(state: _EntryState) -> None:
    assert state.root_path is not None
    assert state.root_stat is not None
    if stat.S_ISREG(state.root_stat.st_mode):
        state.regular_file_count = 1
        state.observed_bytes = state.root_stat.st_size
        return
    if not stat.S_ISDIR(state.root_stat.st_mode):
        return

    state.directory_count = 1

    def visit(path: _Path, relative: str) -> None:
        try:
            with os.scandir(path) as iterator:
                children = sorted(iterator, key=lambda item: item.name)
        except OSError as error:
            state.add_violation("read-error", f"cannot inspect directory metadata: {error}", root=relative)
            return
        for child in children:
            child_path = _Path(child.path)
            child_relative = f"{relative}/{child.name}"
            try:
                child_stat = child.stat(follow_symlinks=False)
            except OSError as error:
                state.add_violation("read-error", f"cannot inspect filesystem metadata: {error}", root=child_relative)
                continue
            if stat.S_ISLNK(child_stat.st_mode):
                state.add_violation(
                    "symlink-component",
                    "retention roots must not contain symlink entries",
                    root=child_relative,
                )
            elif stat.S_ISDIR(child_stat.st_mode):
                state.directory_count += 1
                visit(child_path, child_relative)
            elif stat.S_ISREG(child_stat.st_mode):
                state.regular_file_count += 1
                state.observed_bytes += child_stat.st_size
            else:
                state.add_violation(
                    "unexpected-file-type",
                    "retention roots may contain regular files and directories only",
                    root=child_relative,
                )

    visit(state.root_path, state.entry.root)


def _prepare_states(repo_root: _Path, manifest: _RetentionManifest) -> list[_EntryState]:
    states = [_EntryState(entry) for entry in manifest.entries]
    canonical_groups: dict[str, list[_EntryState]] = {}
    inode_groups: dict[tuple[int, int], list[_EntryState]] = {}

    for state in states:
        try:
            parts = _validate_relative(state.entry.root, label="root")
        except _PathValidationError as error:
            state.add_violation(error.code, str(error))
            continue
        state.canonical_root = "/".join(parts)
        root_path, error = _safe_path(repo_root, parts)
        state.root_path = root_path
        if error == "path contains a symlink component":
            state.add_violation("symlink-component", "retention roots must not contain symlink components")
            continue
        if error is not None:
            state.add_violation("read-error", error)
            continue
        try:
            state.root_stat = root_path.lstat()
        except FileNotFoundError:
            state.add_violation("missing-root", "retention root does not exist")
            continue
        except OSError as error:
            state.add_violation("read-error", f"cannot inspect root metadata: {error}")
            continue
        if stat.S_ISLNK(state.root_stat.st_mode):
            state.add_violation("symlink-component", "retention root must not be a symlink")
            continue
        canonical_groups.setdefault(state.canonical_root, []).append(state)
        inode_groups.setdefault((state.root_stat.st_dev, state.root_stat.st_ino), []).append(state)

    for group in canonical_groups.values():
        if len(group) > 1:
            for state in group:
                state.add_violation(
                    "classification-conflict",
                    "the same canonical root appears more than once in the manifest",
                )
    for group in inode_groups.values():
        if len(group) > 1:
            for state in group:
                state.add_violation(
                    "classification-conflict",
                    "multiple manifest roots identify the same filesystem entity",
                )
    return states


def _audit_manifest(repo_root: _Path, manifest_sha256: str, manifest: _RetentionManifest) -> RetentionAuditResult:
    states = _prepare_states(repo_root, manifest)
    for state in states:
        if state.root_stat is not None:
            expected_directory = state.entry.root_type == "directory"
            actual_directory = stat.S_ISDIR(state.root_stat.st_mode)
            actual_file = stat.S_ISREG(state.root_stat.st_mode)
            if (expected_directory and not actual_directory) or (not expected_directory and not actual_file):
                state.add_violation(
                    "unexpected-file-type",
                    f"manifest expects a regular {state.entry.root_type}",
                )
        _verify_evidence(repo_root, state)
        if not state.violations and state.root_stat is not None:
            _inventory(state)

    states.sort(key=lambda state: state.entry.root)
    all_violations = sorted(
        [violation for state in states for violation in state.violations],
        key=lambda item: (item.root, item.code, item.message),
    )
    entry_results = [
        _RetentionEntryAudit(
            root=state.entry.root,
            root_type=state.entry.root_type,
            classification=state.entry.classification,
            status="valid" if not state.violations else "rejected",
            regular_file_count=state.regular_file_count,
            directory_count=state.directory_count,
            observed_bytes=state.observed_bytes,
            violations=sorted({violation.code for violation in state.violations}),
        )
        for state in states
    ]
    protected_roots = sorted(state.entry.root for state in states if state.entry.classification == "contract-protected")
    lineage_roots = sorted(state.entry.root for state in states if state.entry.classification == "lineage-only")
    ephemeral_roots = sorted(
        state.entry.root for state in states if state.entry.classification == "reproducible-ephemeral"
    )
    unresolved_roots = sorted(state.entry.root for state in states if state.entry.classification == "unknown")
    metadata = _RetentionAggregateMetadata(
        regular_file_count=sum(state.regular_file_count for state in states),
        directory_count=sum(state.directory_count for state in states),
        observed_bytes=sum(state.observed_bytes for state in states),
    )
    return RetentionAuditResult(
        schema_version=_AUDIT_SCHEMA,
        manifest_sha256=manifest_sha256,
        audit_valid=not all_violations,
        entry_results=entry_results,
        protected_roots=protected_roots,
        lineage_roots=lineage_roots,
        ephemeral_roots=ephemeral_roots,
        unresolved_roots=unresolved_roots,
        metadata=metadata,
        violations=all_violations,
    )


def audit_retention(
    manifest_path: str | _Path,
    *,
    repo_root: str | _Path = ".",
) -> RetentionAuditResult:
    """Audit one tracked, repo-relative manifest without reading root contents.

    The manifest itself and JSON fields explicitly named by evidence references may
    be read. Every configured root is inspected through filesystem metadata only.
    A valid result is policy evidence for explicit roots, never deletion authority.
    """

    try:
        root = _repo_root(repo_root)
    except (FileNotFoundError, OSError, TypeError, ValueError) as error:
        return _invalid_result([_violation("invalid-repo-root", str(repo_root), str(error))])
    loaded = _read_tracked_manifest(root, manifest_path)
    if isinstance(loaded, RetentionAuditResult):
        return loaded
    _relative_path, raw, manifest = loaded
    return _audit_manifest(root, hashlib.sha256(raw).hexdigest(), manifest)


def render_retention_report(result: RetentionAuditResult) -> str:
    """Render the same v2 audit semantics as a deterministic Markdown report."""

    lines = [
        "# Retention Audit",
        "",
        f"- schema: `{result.schema_version}`",
        f"- audit_valid: `{str(result.audit_valid).lower()}`",
        f"- manifest_sha256: `{result.manifest_sha256 or 'unavailable'}`",
        f"- regular_file_count: `{result.metadata.regular_file_count}`",
        f"- directory_count: `{result.metadata.directory_count}`",
        f"- observed_bytes: `{result.metadata.observed_bytes}`",
        "",
        "This read-only audit never authorizes deletion or any other filesystem action.",
        "",
        "## Protected Roots",
        "",
    ]
    lines.extend(f"- `{root}`" for root in result.protected_roots)
    if not result.protected_roots:
        lines.append("- none")
    lines.extend(["", "## Lineage Roots", ""])
    lines.extend(f"- `{root}`" for root in result.lineage_roots)
    if not result.lineage_roots:
        lines.append("- none")
    lines.extend(["", "## Reproducible-Ephemeral Roots", ""])
    lines.extend(f"- `{root}`" for root in result.ephemeral_roots)
    if not result.ephemeral_roots:
        lines.append("- none")
    lines.extend(["", "## Unresolved Roots", ""])
    lines.extend(f"- `{root}`" for root in result.unresolved_roots)
    if not result.unresolved_roots:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Aggregate Metadata",
            "",
            "| regular files | directories | observed bytes |",
            "|---:|---:|---:|",
            f"| {result.metadata.regular_file_count} | {result.metadata.directory_count} | {result.metadata.observed_bytes} |",
            "",
            "## Entry Results",
            "",
            "| root | type | classification | status | regular files | directories | observed bytes | violations |",
            "|---|---|---|---|---:|---:|---:|---|",
        ]
    )
    for entry in result.entry_results:
        violation_codes = ", ".join(entry.violations) if entry.violations else "none"
        lines.append(
            f"| `{entry.root}` | `{entry.root_type}` | `{entry.classification}` | `{entry.status}` | "
            f"{entry.regular_file_count} | {entry.directory_count} | {entry.observed_bytes} | `{violation_codes}` |"
        )
    if not result.entry_results:
        lines.append("| none | | | | 0 | 0 | 0 | none |")
    lines.extend(["", "## Violations", ""])
    for violation in result.violations:
        lines.append(f"- `{violation.code}` at `{violation.root}`: {violation.message}")
    if not result.violations:
        lines.append("- none")
    return "\n".join(lines) + "\n"
