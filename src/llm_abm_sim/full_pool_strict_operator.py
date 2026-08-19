from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from .concurrent_message_experiment import (
    CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_DELIVERY_CAPACITY,
    CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_HORIZON,
    CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_SAMPLE_SIZE,
    ConcurrentMessageExperimentConfig,
)
from .decision import LLMDecisionAdapter
from .full_pool_strict_replay import (
    StrictFreshOperatorExecutionReference,
    StrictFreshReplayRequest,
    StrictFreshReplayResult,
    StrictFreshReplayStatus,
    StrictFullPoolFormalReplay,
    StrictRejectedHistoryReference,
    strict_formal_provider_contract,
)

if TYPE_CHECKING:
    from .full_pool_source_v3 import FullPoolResultProjection
    from .full_pool_source_v4 import _ClosedStrictFullPoolSource

STRICT_FRESH_EXECUTION_MANIFEST_SCHEMA = "full-pool-strict-fresh-execution-manifest-v1"
STRICT_FRESH_EXECUTION_MANIFEST_ENVELOPE_SCHEMA = (
    "full-pool-strict-fresh-execution-manifest-envelope-v1"
)
STRICT_FRESH_OPERATOR_ATTEMPT_LEDGER_FILE = "strict_fresh_operator_attempt_ledger.jsonl"
STRICT_FRESH_OPERATOR_LOCK_FILE = ".strict_fresh_operator.lock"

STRICT_FRESH_IMPLEMENTATION_MODULE_PATHS = (
    "src/llm_abm_sim/_concurrent_runtime_spool.py",
    "src/llm_abm_sim/concurrent_execution_journal.py",
    "src/llm_abm_sim/concurrent_message_experiment.py",
    "src/llm_abm_sim/durable_pair_settlement.py",
    "src/llm_abm_sim/decision.py",
    "src/llm_abm_sim/full_pool_formal_experiment.py",
    "src/llm_abm_sim/full_pool_segmented_continuation.py",
    "src/llm_abm_sim/full_pool_segmented_operator.py",
    "src/llm_abm_sim/full_pool_source_v3.py",
    "src/llm_abm_sim/full_pool_strict_replay.py",
    "src/llm_abm_sim/full_pool_strict_operator.py",
    "src/llm_abm_sim/full_pool_source_v4.py",
    "src/llm_abm_sim/prompt_contracts.py",
    "src/llm_abm_sim/prompt_field_summary.py",
    "src/llm_abm_sim/provider_accounting.py",
    "src/llm_abm_sim/provider_request_contract.py",
    "src/llm_abm_sim/providers/openai_compatible.py",
    "src/llm_abm_sim/providers/pi_subscription.py",
    "src/llm_abm_sim/schemas.py",
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "lifecycle",
        "manifest_identity",
        "implementation",
        "frozen_request",
        "dataset",
        "messages",
        "provider_contract",
        "execution_topology",
        "accounting_caps",
        "billing_contract",
        "output_paths",
        "rejected_history",
        "stop_conditions",
        "live_gates",
        "provider_calls_during_composition",
        "production_deploy_eligible",
    }
)
_STOP_CONDITIONS = (
    "strict_stop_provider_failed",
    "strict_stop_provenance_unknown",
    "strict_stop_implementation_failed",
    "strict_stop_cap",
    "source_v4_consumer_rejected",
)


@dataclass(frozen=True)
class StrictFreshExecutionManifestRequest:
    repo_root: Path
    manifest_path: Path
    operator_workspace: Path
    replay_request: StrictFreshReplayRequest
    implementation_commit: str


@dataclass(frozen=True)
class StrictFreshExecutionManifestFacts:
    manifest_path: Path
    manifest_sha256: str
    manifest_identity_sha256: str
    repo_root: Path
    implementation_commit: str
    operator_workspace: Path
    replay_request: StrictFreshReplayRequest
    attempt_ledger_path: Path
    attempt_ledger_identity_sha256: str
    provider_calls_during_composition: int
    production_deploy_eligible: bool
    payload: Mapping[str, object]


@dataclass(frozen=True)
class StrictFreshLiveGates:
    explicit_live_authorization: bool
    external_requests_allowed: bool
    credentials_available: bool
    provider_transport: str
    requested_model: str
    subscription_billed_cost_usd: float


@dataclass(frozen=True)
class StrictFreshOperatorResult:
    attempt_id: str
    runtime: StrictFreshReplayResult
    source: _ClosedStrictFullPoolSource | None
    projection: FullPoolResultProjection | None

    @property
    def status(self) -> StrictFreshReplayStatus:
        return self.runtime.status

    @property
    def source_root(self) -> Path | None:
        return self.runtime.source_root

    @property
    def source_manifest_sha256(self) -> str | None:
        return self.runtime.source_manifest_sha256

    @property
    def production_deploy_eligible(self) -> bool:
        return self.runtime.production_deploy_eligible


@dataclass(frozen=True)
class _AttemptLedgerReplay:
    records: tuple[Mapping[str, object], ...]
    open_attempt_id: str | None
    last_attempt_id: str | None
    last_outcome: str | None
    next_ordinal: int


class StrictFreshOperatorActiveError(RuntimeError):
    """Raised when another process owns the exact operator workspace."""


class _WorkspaceAdvisoryLock:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.path = workspace / STRICT_FRESH_OPERATOR_LOCK_FILE
        self._descriptor: int | None = None

    def __enter__(self) -> _WorkspaceAdvisoryLock:
        if self.workspace.exists() or self.workspace.is_symlink():
            if self.workspace.is_symlink() or not self.workspace.is_dir():
                raise ValueError("strict fresh operator workspace is unsafe")
        else:
            if self.workspace.parent.is_symlink() or not self.workspace.parent.is_dir():
                raise ValueError("strict fresh operator workspace parent is unsafe")
            self.workspace.mkdir(mode=0o700)
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(self.path, flags, 0o600)
        except OSError as exc:
            raise ValueError("strict fresh operator lock path is unsafe") from exc
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise ValueError("strict fresh operator lock must be one regular file")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(descriptor)
            raise StrictFreshOperatorActiveError(
                "strict fresh operator workspace already has an active owner"
            ) from exc
        self._descriptor = descriptor
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._descriptor is not None:
            try:
                fcntl.flock(self._descriptor, fcntl.LOCK_UN)
            finally:
                os.close(self._descriptor)
                self._descriptor = None


class OperatorAttemptLedger:
    """Append-only, identity-bound audit of starts, resumes, and outcomes."""

    _SCHEMA = "full-pool-strict-fresh-operator-attempt-ledger-v1"
    _FIELDS = {
        "schema_version",
        "sequence",
        "previous_checksum",
        "ledger_identity_sha256",
        "manifest_identity_sha256",
        "event_type",
        "payload",
        "checksum",
    }

    def __init__(
        self,
        path: Path,
        *,
        ledger_identity_sha256: str,
        manifest_identity_sha256: str,
        manifest_sha256: str,
        runtime_workspace: Path,
    ) -> None:
        self.path = path
        self.ledger_identity_sha256 = _digest(
            ledger_identity_sha256, "attempt ledger identity"
        )
        self.manifest_identity_sha256 = _digest(
            manifest_identity_sha256, "attempt manifest identity"
        )
        self.manifest_sha256 = _digest(manifest_sha256, "attempt manifest hash")
        self.runtime_workspace = runtime_workspace
        if path.parent.is_symlink() or not path.parent.is_dir():
            raise ValueError("strict fresh attempt ledger parent is unsafe")
        if path.exists() or path.is_symlink():
            if path.is_symlink() or not path.is_file():
                raise ValueError("strict fresh attempt ledger is unsafe")
        self.replay()

    def replay(self) -> _AttemptLedgerReplay:
        if not self.path.exists():
            return _AttemptLedgerReplay((), None, None, None, 1)
        records: list[dict[str, object]] = []
        previous: str | None = None
        open_attempt_id: str | None = None
        last_attempt_id: str | None = None
        last_outcome: str | None = None
        next_ordinal = 1
        for expected_sequence, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line:
                continue
            record = _mapping(json.loads(line), "strict fresh attempt record")
            if set(record) != self._FIELDS:
                raise ValueError("strict fresh attempt ledger fields are not exact")
            checksum = _digest(record.get("checksum"), "attempt checksum")
            body = {key: value for key, value in record.items() if key != "checksum"}
            if (
                record.get("schema_version") != self._SCHEMA
                or record.get("sequence") != expected_sequence
                or record.get("previous_checksum") != previous
                or record.get("ledger_identity_sha256") != self.ledger_identity_sha256
                or record.get("manifest_identity_sha256")
                != self.manifest_identity_sha256
                or _json_sha256(body) != checksum
            ):
                raise ValueError("strict fresh attempt ledger sequence or checksum is invalid")
            event_type = _non_empty(record.get("event_type"), "attempt event type")
            payload = _mapping(record.get("payload"), "attempt payload")
            attempt_id = _non_empty(payload.get("attempt_id"), "attempt id")
            if payload.get("manifest_sha256") != self.manifest_sha256:
                raise ValueError("strict fresh attempt is crossed with its manifest")
            if event_type in {"attempt_started", "attempt_resumed"}:
                if open_attempt_id is not None:
                    raise ValueError("strict fresh attempt ledger overlaps active attempts")
                ordinal = _non_negative_int(payload.get("attempt_ordinal"), "attempt ordinal")
                if ordinal != next_ordinal or attempt_id != f"attempt-{ordinal:06d}":
                    raise ValueError("strict fresh attempt ordinal is not canonical")
                if set(payload) != {
                    "attempt_id",
                    "attempt_ordinal",
                    "manifest_sha256",
                    "runtime_workspace",
                    "prior_attempt_id",
                    "prior_outcome",
                }:
                    raise ValueError("strict fresh attempt entry fields are not exact")
                if payload.get("runtime_workspace") != str(self.runtime_workspace):
                    raise ValueError("strict fresh attempt runtime workspace is crossed")
                expected_event = "attempt_started" if ordinal == 1 else "attempt_resumed"
                if event_type != expected_event:
                    raise ValueError("strict fresh attempt start/resume event is crossed")
                if payload.get("prior_attempt_id") != last_attempt_id or payload.get(
                    "prior_outcome"
                ) != last_outcome:
                    raise ValueError("strict fresh attempt prior outcome is crossed")
                open_attempt_id = attempt_id
                last_attempt_id = attempt_id
                last_outcome = "open"
                next_ordinal += 1
            elif event_type in {"attempt_terminal", "attempt_resumable"}:
                if open_attempt_id != attempt_id:
                    raise ValueError("strict fresh attempt outcome has no matching entry")
                if event_type == "attempt_terminal":
                    if set(payload) != {
                        "attempt_id",
                        "manifest_sha256",
                        "status",
                        "replay_identity_hash",
                        "committed_batch_count",
                        "logical_count",
                        "charged_physical_attempts",
                        "source_manifest_sha256",
                        "production_deploy_eligible",
                    }:
                        raise ValueError("strict fresh terminal attempt fields are not exact")
                    _non_empty(payload.get("status"), "attempt terminal status")
                    _digest(payload.get("replay_identity_hash"), "attempt replay identity")
                    _non_negative_int(
                        payload.get("committed_batch_count"), "attempt committed batches"
                    )
                    _non_negative_int(payload.get("logical_count"), "attempt logical count")
                    _non_negative_int(
                        payload.get("charged_physical_attempts"), "attempt physical count"
                    )
                    source_hash = payload.get("source_manifest_sha256")
                    if source_hash is not None:
                        _digest(source_hash, "attempt source manifest hash")
                    if not isinstance(payload.get("production_deploy_eligible"), bool):
                        raise ValueError("attempt deploy eligibility must be boolean")
                    last_outcome = "terminal"
                else:
                    if set(payload) != {
                        "attempt_id",
                        "manifest_sha256",
                        "reason_class",
                        "audit_sha256",
                        "runtime_workspace_exists",
                    }:
                        raise ValueError("strict fresh resumable attempt fields are not exact")
                    _non_empty(payload.get("reason_class"), "attempt resumable reason")
                    _digest(payload.get("audit_sha256"), "attempt resumable audit")
                    if not isinstance(payload.get("runtime_workspace_exists"), bool):
                        raise ValueError("attempt runtime workspace fact must be boolean")
                    last_outcome = "resumable"
                open_attempt_id = None
            elif event_type == "source_v4_consumer_rejected":
                if (
                    open_attempt_id is not None
                    or last_attempt_id != attempt_id
                    or last_outcome != "terminal"
                    or set(payload)
                    != {
                        "attempt_id",
                        "manifest_sha256",
                        "reason_class",
                        "audit_sha256",
                        "source_manifest_sha256",
                    }
                ):
                    raise ValueError("source-v4 consumer rejection has no terminal attempt")
                _non_empty(payload.get("reason_class"), "consumer rejection reason")
                _digest(payload.get("audit_sha256"), "consumer rejection audit")
                _digest(
                    payload.get("source_manifest_sha256"),
                    "consumer rejection source hash",
                )
                last_outcome = "consumer_rejected"
            else:
                raise ValueError("strict fresh attempt ledger event type is unsupported")
            records.append(record)
            previous = checksum
        return _AttemptLedgerReplay(
            tuple(records),
            open_attempt_id,
            last_attempt_id,
            last_outcome,
            next_ordinal,
        )

    def start_or_resume(self) -> str:
        replay = self.replay()
        if replay.open_attempt_id is not None:
            self._append(
                "attempt_resumable",
                {
                    "attempt_id": replay.open_attempt_id,
                    "manifest_sha256": self.manifest_sha256,
                    "reason_class": "released_lock_without_terminal_event",
                    "audit_sha256": _json_sha256(
                        {
                            "attempt_id": replay.open_attempt_id,
                            "reason": "released_lock_without_terminal_event",
                        }
                    ),
                    "runtime_workspace_exists": self.runtime_workspace.exists(),
                },
            )
            replay = self.replay()
        ordinal = replay.next_ordinal
        attempt_id = f"attempt-{ordinal:06d}"
        self._append(
            "attempt_started" if ordinal == 1 else "attempt_resumed",
            {
                "attempt_id": attempt_id,
                "attempt_ordinal": ordinal,
                "manifest_sha256": self.manifest_sha256,
                "runtime_workspace": str(self.runtime_workspace),
                "prior_attempt_id": replay.last_attempt_id,
                "prior_outcome": replay.last_outcome,
            },
        )
        return attempt_id

    def record_terminal(self, attempt_id: str, result: StrictFreshReplayResult) -> None:
        self._append(
            "attempt_terminal",
            {
                "attempt_id": attempt_id,
                "manifest_sha256": self.manifest_sha256,
                "status": result.status.value,
                "replay_identity_hash": result.replay_identity_hash,
                "committed_batch_count": result.committed_batch_count,
                "logical_count": result.logical_count,
                "charged_physical_attempts": result.charged_physical_attempts,
                "source_manifest_sha256": result.source_manifest_sha256,
                "production_deploy_eligible": result.production_deploy_eligible,
            },
        )

    def record_consumer_rejected(
        self,
        attempt_id: str,
        result: StrictFreshReplayResult,
        exc: Exception,
    ) -> None:
        if result.source_manifest_sha256 is None:
            raise ValueError("consumer rejection requires a persisted source-v4 manifest")
        reason_class = f"{type(exc).__module__}.{type(exc).__qualname__}"
        self._append(
            "source_v4_consumer_rejected",
            {
                "attempt_id": attempt_id,
                "manifest_sha256": self.manifest_sha256,
                "reason_class": reason_class,
                "audit_sha256": _json_sha256(
                    {
                        "attempt_id": attempt_id,
                        "reason_class": reason_class,
                        "source_manifest_sha256": result.source_manifest_sha256,
                    }
                ),
                "source_manifest_sha256": result.source_manifest_sha256,
            },
        )

    def record_resumable(self, attempt_id: str, exc: Exception) -> None:
        reason_class = f"{type(exc).__module__}.{type(exc).__qualname__}"
        self._append(
            "attempt_resumable",
            {
                "attempt_id": attempt_id,
                "manifest_sha256": self.manifest_sha256,
                "reason_class": reason_class,
                "audit_sha256": _json_sha256(
                    {
                        "attempt_id": attempt_id,
                        "reason_class": reason_class,
                        "manifest_sha256": self.manifest_sha256,
                    }
                ),
                "runtime_workspace_exists": self.runtime_workspace.exists(),
            },
        )

    def _append(self, event_type: str, payload: Mapping[str, object]) -> None:
        replay = self.replay()
        previous = (
            _digest(replay.records[-1].get("checksum"), "attempt checksum")
            if replay.records
            else None
        )
        body = {
            "schema_version": self._SCHEMA,
            "sequence": len(replay.records) + 1,
            "previous_checksum": previous,
            "ledger_identity_sha256": self.ledger_identity_sha256,
            "manifest_identity_sha256": self.manifest_identity_sha256,
            "event_type": event_type,
            "payload": dict(payload),
        }
        record = {**body, "checksum": _json_sha256(body)}
        flags = "a" if self.path.exists() else "x"
        with self.path.open(flags, encoding="utf-8", newline="\n") as handle:
            handle.write(_canonical_json(record) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self.replay()


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _json_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"strict fresh artifact is missing or unsafe: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mapping(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be an object")
    return {str(key): item for key, item in value.items()}


def _rows(value: object, context: str) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{context} must be an array")
    return [_mapping(item, context) for item in value]


def _non_empty(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be a non-empty string")
    return value


def _digest(value: object, context: str) -> str:
    digest = _non_empty(value, context)
    if _SHA256.fullmatch(digest) is None:
        raise ValueError(f"{context} must be a lowercase SHA-256 digest")
    return digest


def _non_negative_int(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{context} must be a non-negative integer")
    return value


def _real_directory(path: Path, context: str) -> Path:
    expanded = path.expanduser()
    absolute = Path(os.path.abspath(expanded))
    if expanded.is_symlink():
        raise ValueError(f"{context} is unsafe")
    try:
        resolved = expanded.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"{context} is missing") from exc
    if resolved != absolute or not resolved.is_dir():
        raise ValueError(f"{context} must be one explicit real directory")
    return resolved


def _git(repo_root: Path, *args: str, text: bool = True) -> str | bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            check=True,
            capture_output=True,
            text=text,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("strict fresh manifest cannot verify its Git implementation") from exc
    return completed.stdout


def _head(repo_root: Path) -> str:
    return str(_git(repo_root, "rev-parse", "HEAD")).strip()


def _module_refs_from_files(repo_root: Path) -> list[dict[str, object]]:
    refs: list[dict[str, object]] = []
    for relative in STRICT_FRESH_IMPLEMENTATION_MODULE_PATHS:
        path = repo_root / relative
        refs.append(
            {
                "relative_path": relative,
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    return refs


def _module_refs_from_commit(repo_root: Path, commit: str) -> list[dict[str, object]]:
    refs: list[dict[str, object]] = []
    for relative in STRICT_FRESH_IMPLEMENTATION_MODULE_PATHS:
        payload = _git(repo_root, "show", f"{commit}:{relative}", text=False)
        assert isinstance(payload, bytes)
        refs.append(
            {
                "relative_path": relative,
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    return refs


def _implementation_payload(repo_root: Path, commit: str) -> dict[str, object]:
    if _COMMIT.fullmatch(commit) is None or _head(repo_root) != commit:
        raise ValueError("strict fresh implementation commit differs from HEAD")
    refs = _module_refs_from_files(repo_root)
    if refs != _module_refs_from_commit(repo_root, commit):
        raise ValueError("strict fresh implementation Module bytes are dirty")
    status = str(
        _git(
            repo_root,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--",
            *STRICT_FRESH_IMPLEMENTATION_MODULE_PATHS,
        )
    )
    if status.strip():
        raise ValueError("strict fresh implementation Module set is dirty")
    return {
        "repository_commit": commit,
        "modules": refs,
        "module_set_identity_sha256": _json_sha256(refs),
    }


def _validate_implementation(
    repo_root: Path,
    implementation: Mapping[str, object],
    *,
    require_current: bool,
) -> dict[str, object]:
    if set(implementation) != {
        "repository_commit",
        "modules",
        "module_set_identity_sha256",
    }:
        raise ValueError("strict fresh implementation fields are not exact")
    commit = _non_empty(implementation.get("repository_commit"), "implementation commit")
    if _COMMIT.fullmatch(commit) is None:
        raise ValueError("strict fresh implementation commit is invalid")
    rows = _rows(implementation.get("modules"), "implementation Module refs")
    if any(set(row) != {"relative_path", "bytes", "sha256"} for row in rows):
        raise ValueError("strict fresh implementation Module refs are not exact")
    if rows != _module_refs_from_commit(repo_root, commit):
        raise ValueError("strict fresh implementation commit lacks exact Module blobs")
    if implementation.get("module_set_identity_sha256") != _json_sha256(rows):
        raise ValueError("strict fresh implementation Module identity is crossed")
    if require_current:
        expected = _implementation_payload(repo_root, commit)
        if dict(implementation) != expected:
            raise ValueError("strict fresh current implementation drifted")
    return dict(implementation)


def _dataset_inventory(dataset_dir: Path) -> list[dict[str, object]]:
    root = _real_directory(dataset_dir, "strict fresh dataset")
    entries = tuple(sorted(root.rglob("*"), key=lambda item: item.as_posix()))
    if any(path.is_symlink() or not (path.is_file() or path.is_dir()) for path in entries):
        raise ValueError("strict fresh dataset inventory contains an unsafe entry")
    refs = [
        {
            "relative_path": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        }
        for path in entries
        if path.is_file()
    ]
    if not refs:
        raise ValueError("strict fresh dataset inventory is empty")
    return refs


def _request_payload(request: StrictFreshReplayRequest) -> dict[str, object]:
    if getattr(request, "operator_execution", None) is not None:
        raise ValueError("strict fresh manifest must bind a request before operator execution")
    return {
        "configuration": request.config.model_dump(mode="json"),
        "runtime_workspace": str(request.workspace),
        "replay_id": request.replay_id,
        "seed_top_k_per_proxy": request.seed_top_k_per_proxy,
        "logical_cap": request.logical_cap,
        "physical_cap": request.physical_cap,
        "maximum_attempts_per_dispatch": request.maximum_attempts_per_dispatch,
        "max_concurrency": request.max_concurrency,
    }


def _request_paths(
    request: StrictFreshExecutionManifestRequest,
    *,
    require_new_workspace: bool,
) -> tuple[Path, Path, Path, Path]:
    repo_root = _real_directory(Path(request.repo_root), "strict fresh repository root")
    manifest_path = Path(os.path.abspath(Path(request.manifest_path).expanduser()))
    operator_workspace = Path(os.path.abspath(Path(request.operator_workspace).expanduser()))
    runtime_workspace = request.replay_request.workspace
    if runtime_workspace != operator_workspace / "runtime":
        raise ValueError("strict fresh runtime workspace must be operator_workspace/runtime")
    dataset = request.replay_request.config.dataset_dir.resolve(strict=True)
    rejected = request.replay_request.rejected_history.source_root
    protected = (repo_root, dataset, rejected)
    if any(
        operator_workspace == root
        or operator_workspace.is_relative_to(root)
        or root.is_relative_to(operator_workspace)
        for root in protected
    ):
        raise ValueError("strict fresh operator workspace overlaps a protected input")
    if (
        manifest_path == operator_workspace
        or manifest_path.is_relative_to(operator_workspace)
        or operator_workspace.is_relative_to(manifest_path)
        or manifest_path.is_relative_to(dataset)
        or manifest_path.is_relative_to(rejected)
        or any(manifest_path == root for root in protected)
    ):
        raise ValueError("strict fresh manifest and execution paths overlap")
    if manifest_path.is_symlink() or operator_workspace.is_symlink():
        raise ValueError("strict fresh manifest or workspace path is unsafe")
    if require_new_workspace and operator_workspace.exists():
        raise ValueError("strict fresh operator workspace must not exist at manifest creation")
    if not require_new_workspace and operator_workspace.exists() and not operator_workspace.is_dir():
        raise ValueError("strict fresh operator workspace is unsafe")
    return repo_root, manifest_path, operator_workspace, runtime_workspace


def _compose_payload(
    request: StrictFreshExecutionManifestRequest,
    *,
    require_new_workspace: bool,
    persisted_implementation: Mapping[str, object] | None = None,
) -> dict[str, object]:
    repo_root, manifest_path, operator_workspace, runtime_workspace = _request_paths(
        request,
        require_new_workspace=require_new_workspace,
    )
    if _COMMIT.fullmatch(request.implementation_commit) is None:
        raise ValueError("strict fresh implementation commit is invalid")
    replay_request = request.replay_request
    if replay_request.physical_cap != 120_120 or (
        replay_request.config.configuration_profile == "production"
        and replay_request.logical_cap != 109_200
    ):
        raise ValueError("strict fresh Formal manifest requires exact 109,200/120,120 caps")
    implementation = (
        _implementation_payload(repo_root, request.implementation_commit)
        if persisted_implementation is None
        else _validate_implementation(
            repo_root,
            persisted_implementation,
            require_current=False,
        )
    )
    if implementation["repository_commit"] != request.implementation_commit:
        raise ValueError("strict fresh persisted implementation is crossed")
    dataset_refs = _dataset_inventory(request.replay_request.config.dataset_dir)
    messages = [
        message.model_dump(mode="json") for message in request.replay_request.config.messages
    ]
    provider = strict_formal_provider_contract()
    if _canonical_json(request.replay_request.provider_contract) != _canonical_json(provider):
        raise ValueError("strict fresh manifest Provider contract is crossed")
    ledger_identity = _json_sha256(
        {
            "schema_version": "full-pool-strict-fresh-attempt-ledger-identity-v1",
            "operator_workspace": str(operator_workspace),
            "runtime_workspace": str(runtime_workspace),
            "replay_id": request.replay_request.replay_id,
            "implementation_commit": request.implementation_commit,
        }
    )
    body: dict[str, object] = {
        "schema_version": STRICT_FRESH_EXECUTION_MANIFEST_SCHEMA,
        "lifecycle": "ready_for_reentrant_operator",
        "implementation": implementation,
        "frozen_request": _request_payload(request.replay_request),
        "dataset": {
            "root": str(request.replay_request.config.dataset_dir.resolve(strict=True)),
            "artifacts": dataset_refs,
            "inventory_sha256": _json_sha256(dataset_refs),
        },
        "messages": {
            "rows": messages,
            "sha256": _json_sha256(messages),
            "prompt_variant_id": "P0",
        },
        "provider_contract": provider,
        "execution_topology": {
            "configured_max_concurrency": 10,
            "isolated_adapter_per_lane": True,
            "fresh_no_cache": True,
            "latest_directory_scan_allowed": False,
            "reentrant_same_manifest": True,
            "active_owner_mechanism": "local_os_advisory_lock",
        },
        "accounting_caps": {
            "logical_cap": request.replay_request.logical_cap,
            "physical_cap": request.replay_request.physical_cap,
            "maximum_attempts_per_dispatch": 3,
            "maximum_dispatches_per_pair": 2,
        },
        "billing_contract": {
            "subscription_billed_cost_usd": 0.0,
            "fee_ceiling_usd": 0.0,
            "billing_mode": "Pi subscription",
        },
        "output_paths": {
            "repo_root": str(repo_root),
            "manifest_path": str(manifest_path),
            "operator_workspace": str(operator_workspace),
            "runtime_workspace": str(runtime_workspace),
            "source_v4": str(runtime_workspace / "source-v4"),
            "attempt_ledger": str(
                operator_workspace / STRICT_FRESH_OPERATOR_ATTEMPT_LEDGER_FILE
            ),
            "attempt_ledger_identity_sha256": ledger_identity,
            "active_owner_lock": str(operator_workspace / STRICT_FRESH_OPERATOR_LOCK_FILE),
        },
        "rejected_history": {
            "source_root": str(request.replay_request.rejected_history.source_root),
            "manifest_sha256": request.replay_request.rejected_history.manifest_sha256,
            "rejection_reason": request.replay_request.rejected_history.rejection_reason,
        },
        "stop_conditions": list(_STOP_CONDITIONS),
        "live_gates": {
            "explicit_live_authorization_required": True,
            "external_requests_allowed_required": True,
            "credentials_available_required": True,
            "provider_contract_exact_required": True,
            "clean_implementation_required": True,
        },
        "provider_calls_during_composition": 0,
        "production_deploy_eligible": False,
    }
    identity = _json_sha256(body)
    return {
        **body,
        "manifest_identity": {
            "schema_version": "full-pool-strict-fresh-execution-identity-v1",
            "sha256": identity,
        },
    }


def _exclusive_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.parent.resolve(strict=True) != path.parent.absolute():
        raise ValueError("strict fresh manifest parent must be one explicit real directory")
    try:
        with path.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise FileExistsError("strict fresh execution manifest is create once") from exc


def create_strict_fresh_execution_manifest(
    request: StrictFreshExecutionManifestRequest,
) -> Path:
    """Create one zero-call manifest bound to exact fresh Formal execution inputs."""
    payload = _compose_payload(request, require_new_workspace=True)
    envelope = {
        "schema_version": STRICT_FRESH_EXECUTION_MANIFEST_ENVELOPE_SCHEMA,
        "payload": payload,
        "payload_sha256": _json_sha256(payload),
    }
    target = Path(os.path.abspath(Path(request.manifest_path).expanduser()))
    _exclusive_write(target, (_canonical_json(envelope) + "\n").encode("utf-8"))
    validate_strict_fresh_execution_manifest(target, require_current_implementation=True)
    return target


def _request_from_payload(
    manifest_path: Path,
    payload: Mapping[str, object],
) -> StrictFreshExecutionManifestRequest:
    implementation = _mapping(payload.get("implementation"), "manifest implementation")
    frozen = _mapping(payload.get("frozen_request"), "manifest frozen request")
    outputs = _mapping(payload.get("output_paths"), "manifest outputs")
    rejected = _mapping(payload.get("rejected_history"), "manifest rejected history")
    if outputs.get("manifest_path") != str(manifest_path):
        raise ValueError("strict fresh manifest path is crossed")
    config = ConcurrentMessageExperimentConfig.model_validate(
        _mapping(frozen.get("configuration"), "manifest configuration")
    )
    replay = StrictFreshReplayRequest(
        config=config,
        workspace=Path(_non_empty(frozen.get("runtime_workspace"), "runtime workspace")),
        replay_id=_non_empty(frozen.get("replay_id"), "replay id"),
        provider_contract=_mapping(payload.get("provider_contract"), "Provider contract"),
        rejected_history=StrictRejectedHistoryReference(
            source_root=Path(_non_empty(rejected.get("source_root"), "rejected source root")),
            manifest_sha256=_digest(
                rejected.get("manifest_sha256"), "rejected manifest SHA-256"
            ),
            rejection_reason=_non_empty(
                rejected.get("rejection_reason"), "rejected history reason"
            ),
        ),
        seed_top_k_per_proxy=_non_negative_int(
            frozen.get("seed_top_k_per_proxy"), "seed top k"
        ),
        logical_cap=_non_negative_int(frozen.get("logical_cap"), "logical cap"),
        physical_cap=_non_negative_int(frozen.get("physical_cap"), "physical cap"),
        maximum_attempts_per_dispatch=_non_negative_int(
            frozen.get("maximum_attempts_per_dispatch"), "maximum attempts"
        ),
        max_concurrency=_non_negative_int(
            frozen.get("max_concurrency"), "maximum concurrency"
        ),
    )
    return StrictFreshExecutionManifestRequest(
        repo_root=Path(_non_empty(outputs.get("repo_root"), "repository root")),
        manifest_path=manifest_path,
        operator_workspace=Path(
            _non_empty(outputs.get("operator_workspace"), "operator workspace")
        ),
        replay_request=replay,
        implementation_commit=_non_empty(
            implementation.get("repository_commit"), "implementation commit"
        ),
    )


def validate_strict_fresh_execution_manifest(
    manifest_path: str | Path,
    *,
    require_current_implementation: bool = False,
) -> StrictFreshExecutionManifestFacts:
    path = Path(os.path.abspath(Path(manifest_path).expanduser()))
    if path.is_symlink() or not path.is_file():
        raise ValueError("strict fresh execution manifest must be one regular file")
    try:
        envelope = _mapping(
            json.loads(path.read_text(encoding="utf-8")), "strict fresh manifest envelope"
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("strict fresh execution manifest is malformed") from exc
    if set(envelope) != {"schema_version", "payload", "payload_sha256"} or envelope.get(
        "schema_version"
    ) != STRICT_FRESH_EXECUTION_MANIFEST_ENVELOPE_SCHEMA:
        raise ValueError("strict fresh execution manifest envelope is not exact")
    payload = _mapping(envelope.get("payload"), "strict fresh manifest payload")
    if (
        set(payload) != _MANIFEST_FIELDS
        or payload.get("schema_version") != STRICT_FRESH_EXECUTION_MANIFEST_SCHEMA
        or payload.get("lifecycle") != "ready_for_reentrant_operator"
        or payload.get("provider_calls_during_composition") != 0
        or payload.get("production_deploy_eligible") is not False
        or envelope.get("payload_sha256") != _json_sha256(payload)
    ):
        raise ValueError("strict fresh execution manifest fields or hash are crossed")
    request = _request_from_payload(path, payload)
    implementation = _mapping(payload.get("implementation"), "manifest implementation")
    _validate_implementation(
        _real_directory(request.repo_root, "strict fresh repository root"),
        implementation,
        require_current=require_current_implementation,
    )
    expected = _compose_payload(
        request,
        require_new_workspace=False,
        persisted_implementation=implementation,
    )
    if payload != expected:
        raise ValueError("strict fresh execution manifest drifted from persisted inputs")
    identity = _mapping(payload.get("manifest_identity"), "manifest identity")
    body = {key: value for key, value in payload.items() if key != "manifest_identity"}
    if identity != {
        "schema_version": "full-pool-strict-fresh-execution-identity-v1",
        "sha256": _json_sha256(body),
    }:
        raise ValueError("strict fresh execution manifest identity is crossed")
    outputs = _mapping(payload.get("output_paths"), "manifest outputs")
    return StrictFreshExecutionManifestFacts(
        manifest_path=path,
        manifest_sha256=_sha256_file(path),
        manifest_identity_sha256=_digest(identity.get("sha256"), "manifest identity"),
        repo_root=request.repo_root.resolve(strict=True),
        implementation_commit=request.implementation_commit,
        operator_workspace=request.operator_workspace,
        replay_request=request.replay_request,
        attempt_ledger_path=Path(
            _non_empty(outputs.get("attempt_ledger"), "attempt ledger path")
        ),
        attempt_ledger_identity_sha256=_digest(
            outputs.get("attempt_ledger_identity_sha256"), "attempt ledger identity"
        ),
        provider_calls_during_composition=0,
        production_deploy_eligible=False,
        payload=payload,
    )


class StrictFreshAutomationOperator:
    """Consume one explicit fresh manifest without recency discovery."""

    def preflight(
        self,
        manifest_path: str | Path,
        *,
        gates: StrictFreshLiveGates,
    ) -> StrictFreshExecutionManifestFacts:
        facts = validate_strict_fresh_execution_manifest(
            manifest_path,
            require_current_implementation=True,
        )
        config = facts.replay_request.config
        if facts.replay_request.logical_cap == 109_200 and (
            config.configuration_profile != "production"
            or config.sample_size != CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_SAMPLE_SIZE
            or config.horizon != CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_HORIZON
            or config.delivery_capacity
            != CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_DELIVERY_CAPACITY
        ):
            raise ValueError(
                "strict fresh full-scale live execution requires the exact production profile and topology"
            )
        provider = _mapping(facts.payload.get("provider_contract"), "manifest Provider")
        billing = _mapping(facts.payload.get("billing_contract"), "manifest billing")
        if (
            gates.explicit_live_authorization is not True
            or gates.external_requests_allowed is not True
            or gates.credentials_available is not True
            or gates.provider_transport != provider.get("provider_transport")
            or gates.requested_model != provider.get("requested_model")
            or gates.subscription_billed_cost_usd
            != billing.get("subscription_billed_cost_usd")
        ):
            raise ValueError("strict fresh operator live gates differ from the manifest")
        return facts

    def run(
        self,
        manifest_path: str | Path,
        *,
        gates: StrictFreshLiveGates,
        adapter_factory: Callable[[int], LLMDecisionAdapter],
    ) -> StrictFreshOperatorResult:
        facts = self.preflight(manifest_path, gates=gates)
        with _WorkspaceAdvisoryLock(facts.operator_workspace):
            # Revalidate every mutable preflight fact after acquiring sole ownership.
            facts = self.preflight(manifest_path, gates=gates)
            ledger = OperatorAttemptLedger(
                facts.attempt_ledger_path,
                ledger_identity_sha256=facts.attempt_ledger_identity_sha256,
                manifest_identity_sha256=facts.manifest_identity_sha256,
                manifest_sha256=facts.manifest_sha256,
                runtime_workspace=facts.replay_request.workspace,
            )
            attempt_id = ledger.start_or_resume()
            operator_execution = StrictFreshOperatorExecutionReference(
                execution_manifest_path=facts.manifest_path,
                execution_manifest_sha256=facts.manifest_sha256,
                execution_manifest_identity_sha256=facts.manifest_identity_sha256,
                attempt_ledger_path=facts.attempt_ledger_path,
                attempt_ledger_identity_sha256=facts.attempt_ledger_identity_sha256,
            )
            replay_request = replace(
                facts.replay_request,
                operator_execution=operator_execution,
            )
            try:
                result = StrictFullPoolFormalReplay().run(
                    replay_request,
                    adapter_factory=adapter_factory,
                )
            except Exception as exc:
                ledger.record_resumable(attempt_id, exc)
                raise
            ledger.record_terminal(attempt_id, result)
            closed_source = None
            projection = None
            if result.source_root is not None and result.source_manifest_sha256 is not None:
                from .full_pool_source_v4 import (
                    compose_strict_full_pool_result_projection,
                    read_closed_strict_full_pool_source,
                )

                try:
                    closed_source = read_closed_strict_full_pool_source(
                        result.source_root,
                        manifest_sha256=result.source_manifest_sha256,
                    )
                    projection = compose_strict_full_pool_result_projection(closed_source)
                except Exception as exc:
                    ledger.record_consumer_rejected(attempt_id, result, exc)
                    raise
            return StrictFreshOperatorResult(
                attempt_id=attempt_id,
                runtime=result,
                source=closed_source,
                projection=projection,
            )
