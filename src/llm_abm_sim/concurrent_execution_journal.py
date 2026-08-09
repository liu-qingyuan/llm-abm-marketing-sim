from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from .concurrent_message_report import CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON
from .safe_serialization import safe_data

CONCURRENT_MESSAGE_EXECUTION_RUN_IDENTITY_SCHEMA = "concurrent-message-execution-run-identity-v1"
CONCURRENT_MESSAGE_EXECUTION_JOURNAL_SCHEMA = "concurrent-message-execution-journal-v1"
CONCURRENT_MESSAGE_EXECUTION_STATUS_SCHEMA = "concurrent-message-execution-status-v1"
CONCURRENT_MESSAGE_EXECUTION_SNAPSHOT_SCHEMA = "concurrent-message-execution-snapshot-v1"

CONCURRENT_MESSAGE_EXECUTION_RUN_IDENTITY_JSON = "concurrent_message_execution_run_identity.json"
CONCURRENT_MESSAGE_EXECUTION_JOURNAL_JSONL = "concurrent_message_execution_journal.jsonl"
CONCURRENT_MESSAGE_EXECUTION_STATUS_JSON = "concurrent_message_execution_status.json"
CONCURRENT_MESSAGE_EXECUTION_SNAPSHOTS_DIR = "concurrent_message_execution_snapshots"
CONCURRENT_MESSAGE_EXECUTION_LOCK_FILE = "concurrent_message_execution.lock"

_CONCURRENT_MESSAGE_REQUIRED_DATASET_FILES = ("videos.csv", "users.csv")
_CONCURRENT_MESSAGE_OPTIONAL_COMMENT_FILES = ("all_comments.csv", "comments.csv")


def derive_concurrent_execution_workspace(output_dir: str | Path) -> Path:
    output_path = Path(output_dir)
    return output_path.parent / f".{output_path.name}.operational"


def derive_concurrent_execution_publish_staging_dir(output_dir: str | Path, *, run_id: str) -> Path:
    output_path = Path(output_dir)
    return output_path.parent / f".{output_path.name}.{run_id}.staging"


def build_concurrent_execution_run_identity(
    *,
    output_target: str | Path,
    operational_workspace: str | Path,
    configuration_snapshot: Mapping[str, Any],
    message_snapshot: Sequence[Mapping[str, Any]],
    sample_audit: Mapping[str, Any],
    dataset_dir: str | Path,
    primary_provider_metadata: Mapping[str, Any],
    shadow_provider_metadata: Mapping[str, Any],
    prompt_contract: Mapping[str, Any],
) -> dict[str, Any]:
    return _build_concurrent_execution_run_identity(
        output_target=output_target,
        operational_workspace=operational_workspace,
        configuration_snapshot=configuration_snapshot,
        message_snapshot=message_snapshot,
        sample_audit=sample_audit,
        dataset_dir=dataset_dir,
        provider_contract={
            "primary": dict(safe_data(primary_provider_metadata)),
            "shadow": dict(safe_data(shadow_provider_metadata)),
        },
        prompt_contract=prompt_contract,
    )


def _build_primary_only_concurrent_execution_run_identity(
    *,
    output_target: str | Path,
    operational_workspace: str | Path,
    configuration_snapshot: Mapping[str, Any],
    message_snapshot: Sequence[Mapping[str, Any]],
    sample_audit: Mapping[str, Any],
    dataset_dir: str | Path,
    primary_provider_metadata: Mapping[str, Any],
    prompt_contract: Mapping[str, Any],
    execution_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    identity = _build_concurrent_execution_run_identity(
        output_target=output_target,
        operational_workspace=operational_workspace,
        configuration_snapshot=configuration_snapshot,
        message_snapshot=message_snapshot,
        sample_audit=sample_audit,
        dataset_dir=dataset_dir,
        provider_contract={"primary": dict(safe_data(primary_provider_metadata))},
        prompt_contract=prompt_contract,
    )
    if execution_contract is None:
        return identity
    identity_body = {key: value for key, value in identity.items() if key not in {"run_id", "identity_hash"}}
    identity_body["execution_contract"] = dict(safe_data(execution_contract))
    identity_hash = _sha256_text(_canonical_json(identity_body))
    return {
        **identity_body,
        "run_id": f"concurrent-execution-{identity_hash[:16]}",
        "identity_hash": identity_hash,
    }


def _build_concurrent_execution_run_identity(
    *,
    output_target: str | Path,
    operational_workspace: str | Path,
    configuration_snapshot: Mapping[str, Any],
    message_snapshot: Sequence[Mapping[str, Any]],
    sample_audit: Mapping[str, Any],
    dataset_dir: str | Path,
    provider_contract: Mapping[str, Any],
    prompt_contract: Mapping[str, Any],
) -> dict[str, Any]:
    dataset_path = Path(dataset_dir).resolve()
    dataset_files: dict[str, str] = {}
    for file_name in _CONCURRENT_MESSAGE_REQUIRED_DATASET_FILES:
        dataset_files[file_name] = _sha256_file(dataset_path / file_name)
    for file_name in _CONCURRENT_MESSAGE_OPTIONAL_COMMENT_FILES:
        candidate = dataset_path / file_name
        if candidate.is_file():
            dataset_files[file_name] = _sha256_file(candidate)
            break

    identity_body = {
        "schema_version": CONCURRENT_MESSAGE_EXECUTION_RUN_IDENTITY_SCHEMA,
        "output_target": str(Path(output_target).resolve()),
        "operational_workspace": str(Path(operational_workspace).resolve()),
        "configuration": dict(safe_data(configuration_snapshot)),
        "messages": list(safe_data(list(message_snapshot))),
        "sample_data_fingerprints": {
            "dataset_dir": str(dataset_path),
            "dataset_files": dataset_files,
            "configuration_hash": _sha256_text(_canonical_json(configuration_snapshot)),
            "message_snapshot_hash": _sha256_text(_canonical_json(list(message_snapshot))),
            "sample_audit_hash": _sha256_text(_canonical_json(sample_audit)),
        },
        "provider_contract": dict(safe_data(provider_contract)),
        "prompt_contract": dict(safe_data(prompt_contract)),
        "deploy_eligibility": False,
    }
    identity_hash = _sha256_text(_canonical_json(identity_body))
    run_id = f"concurrent-execution-{identity_hash[:16]}"
    return {**identity_body, "run_id": run_id, "identity_hash": identity_hash}


@dataclass
class ConcurrentExecutionJournal:
    workspace_dir: Path
    identity: dict[str, Any]
    read_only: bool = False
    journal_path: Path = field(init=False)
    status_path: Path = field(init=False)
    identity_path: Path = field(init=False)
    snapshots_dir: Path = field(init=False)
    _lock_handle: Any = field(default=None, init=False, repr=False)
    sequence: int = 0
    previous_checksum: str | None = None
    record_count: int = 0
    snapshot_count: int = 0
    event_count: int = 0
    planned_batch_count: int = 0
    planned_pair_count: int = 0
    planned_variant_count: int = 0
    started_variant_count: int = 0
    terminal_variant_count: int = 0
    closed_pair_count: int = 0
    committed_batch_count: int = 0
    finalization_started: bool = False
    finalized: bool = False
    final_source_hash: str | None = None
    last_durable_identity: dict[str, Any] | None = None
    _known_snapshot_hashes: set[str] = field(default_factory=set, init=False)
    _known_event_identities: set[str] = field(default_factory=set, init=False)
    _known_snapshot_identities: set[str] = field(default_factory=set, init=False)

    def __post_init__(self) -> None:
        self.workspace_dir = Path(self.workspace_dir)
        self.journal_path = self.workspace_dir / CONCURRENT_MESSAGE_EXECUTION_JOURNAL_JSONL
        self.status_path = self.workspace_dir / CONCURRENT_MESSAGE_EXECUTION_STATUS_JSON
        self.identity_path = self.workspace_dir / CONCURRENT_MESSAGE_EXECUTION_RUN_IDENTITY_JSON
        self.snapshots_dir = self.workspace_dir / CONCURRENT_MESSAGE_EXECUTION_SNAPSHOTS_DIR

    @property
    def run_id(self) -> str:
        return _as_str(self.identity.get("run_id"))

    @property
    def identity_hash(self) -> str:
        return _as_str(self.identity.get("identity_hash"))

    @classmethod
    def open_new(cls, workspace_dir: str | Path, *, identity: Mapping[str, Any]) -> ConcurrentExecutionJournal:
        workspace = Path(workspace_dir)
        _ensure_workspace_is_available(workspace)
        workspace.mkdir(parents=True, exist_ok=True)
        journal = cls(workspace, dict(safe_data(identity)))
        _validate_run_identity(journal.identity)
        journal._lock_handle = _acquire_workspace_lock(workspace)
        try:
            _atomic_write_json(journal.identity_path, journal.identity)
            journal.snapshots_dir.mkdir(parents=True, exist_ok=True)
            journal.append(
                event_type="run_started",
                event_identity={"run_id": journal.run_id},
                payload={
                    "identity_hash": journal.identity_hash,
                    "output_target": journal.identity["output_target"],
                    "operational_workspace": journal.identity["operational_workspace"],
                    "deploy_eligibility": journal.identity["deploy_eligibility"],
                },
            )
        except Exception:
            journal.close()
            raise
        return journal

    @classmethod
    def open_existing(cls, workspace_dir: str | Path) -> ConcurrentExecutionJournal:
        workspace = Path(workspace_dir)
        if not workspace.is_dir():
            raise FileNotFoundError(f"Concurrent execution workspace does not exist: {workspace}")
        identity_path = workspace / CONCURRENT_MESSAGE_EXECUTION_RUN_IDENTITY_JSON
        if not identity_path.is_file():
            raise FileNotFoundError(f"Concurrent execution workspace is missing {identity_path.name}")
        identity = _read_json_object(identity_path)
        _validate_run_identity(identity)
        return cls(workspace, dict(identity), read_only=True)

    @classmethod
    def open_resume(cls, workspace_dir: str | Path, *, identity: Mapping[str, Any]) -> ConcurrentExecutionJournal:
        workspace = Path(workspace_dir)
        if not workspace.is_dir():
            raise FileNotFoundError(f"Concurrent execution workspace does not exist: {workspace}")
        journal = cls(workspace, dict(safe_data(identity)))
        _validate_run_identity(journal.identity)
        journal._lock_handle = _acquire_workspace_lock(workspace)
        try:
            identity_path = workspace / CONCURRENT_MESSAGE_EXECUTION_RUN_IDENTITY_JSON
            if not identity_path.is_file():
                raise FileNotFoundError(f"Concurrent execution workspace is missing {identity_path.name}")
            persisted_identity = _read_json_object(identity_path)
            _validate_run_identity(persisted_identity)
            if persisted_identity != journal.identity:
                raise ValueError("Concurrent execution workspace identity mismatch for resume")
            if not (workspace / CONCURRENT_MESSAGE_EXECUTION_JOURNAL_JSONL).is_file():
                raise FileNotFoundError(
                    f"Concurrent execution workspace is missing {CONCURRENT_MESSAGE_EXECUTION_JOURNAL_JSONL}"
                )
            replay = _replay_workspace(workspace)
            journal._hydrate_from_replay(replay)
        except Exception:
            journal.close()
            raise
        return journal

    def close(self) -> None:
        lock_handle = self._lock_handle
        if lock_handle is not None:
            lock_handle.close()
            self._lock_handle = None

    def replay(self) -> dict[str, Any]:
        return _replay_workspace(self.workspace_dir)

    def _hydrate_from_replay(self, replay: Mapping[str, Any]) -> None:
        status = _require_mapping(replay.get("status"), "replay status")
        self.sequence = _as_int(status.get("record_count"))
        self.record_count = _as_int(status.get("record_count"))
        self.snapshot_count = _as_int(status.get("snapshot_count"))
        self.event_count = _as_int(status.get("event_count"))
        self.planned_batch_count = _as_int(status.get("planned_batch_count"))
        self.planned_pair_count = _as_int(status.get("planned_pair_count"))
        self.planned_variant_count = _as_int(status.get("planned_variant_count"))
        self.started_variant_count = _as_int(status.get("started_variant_count"))
        self.terminal_variant_count = _as_int(status.get("terminal_variant_count"))
        self.closed_pair_count = _as_int(status.get("closed_pair_count"))
        self.committed_batch_count = _as_int(status.get("committed_batch_count"))
        self.finalization_started = bool(status.get("finalization_started")) or _as_str(status.get("lifecycle")) in {"durable_partial", "published"}
        self.finalized = _as_str(status.get("lifecycle")) in {"published", "complete"}
        self.final_source_hash = _as_str(status.get("final_source_hash")) or None
        last_identity = status.get("last_durable_identity")
        self.last_durable_identity = dict(safe_data(last_identity)) if isinstance(last_identity, Mapping) else None
        self.previous_checksum = _read_last_journal_checksum(self.journal_path)
        self._known_snapshot_hashes = set()
        self._known_event_identities = set()
        self._known_snapshot_identities = set()
        records = replay.get("records", [])
        if isinstance(records, Sequence):
            for record in records:
                if not isinstance(record, Mapping):
                    continue
                record_type = _as_str(record.get("record_type"))
                if record_type == "snapshot":
                    snapshot_hash = _as_str(record.get("snapshot_hash"))
                    if snapshot_hash:
                        self._known_snapshot_hashes.add(snapshot_hash)
                    snapshot_identity = record.get("snapshot_identity")
                    if isinstance(snapshot_identity, Mapping):
                        self._known_snapshot_identities.add(_canonical_json(snapshot_identity))
                elif record_type == "event":
                    event_identity = record.get("event_identity")
                    if isinstance(event_identity, Mapping):
                        self._known_event_identities.add(_canonical_json(event_identity))

    def persist_snapshot(
        self,
        *,
        snapshot_type: str,
        snapshot_identity: Mapping[str, Any],
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        self._ensure_writable()
        snapshot_type = _non_empty_token(snapshot_type, "snapshot_type")
        snapshot_identity_dict = dict(safe_data(snapshot_identity))
        snapshot_payload = dict(safe_data(payload))
        if "planned_pair_count" not in snapshot_payload or "planned_variant_count" not in snapshot_payload:
            raise ValueError("snapshot payload must include planned_pair_count and planned_variant_count")
        snapshot_document = {
            "schema_version": CONCURRENT_MESSAGE_EXECUTION_SNAPSHOT_SCHEMA,
            "snapshot_type": snapshot_type,
            "snapshot_identity": snapshot_identity_dict,
            "payload": snapshot_payload,
        }
        sequence = self.sequence + 1
        snapshot_hash = _sha256_text(_canonical_json(snapshot_document))
        snapshot_path = self.snapshots_dir / f"{snapshot_type}-{sequence:04d}-{snapshot_hash[:12]}.json"
        _atomic_write_json(snapshot_path, snapshot_document)
        record = {
            "schema_version": CONCURRENT_MESSAGE_EXECUTION_JOURNAL_SCHEMA,
            "record_type": "snapshot",
            "sequence": sequence,
            "run_id": self.run_id,
            "identity_hash": self.identity_hash,
            "previous_checksum": self.previous_checksum,
            "snapshot_type": snapshot_type,
            "snapshot_identity": snapshot_identity_dict,
            "snapshot_hash": snapshot_hash,
            "snapshot_path": str(snapshot_path.relative_to(self.workspace_dir)),
            "planned_batch_count": 1,
            "planned_pair_count": _as_int(snapshot_payload.get("planned_pair_count")),
            "planned_variant_count": _as_int(snapshot_payload.get("planned_variant_count")),
        }
        self._write_record(record)
        return {
            "sequence": sequence,
            "snapshot_type": snapshot_type,
            "snapshot_identity": snapshot_identity_dict,
            "snapshot_hash": snapshot_hash,
            "snapshot_path": str(snapshot_path.relative_to(self.workspace_dir)),
        }

    def append(
        self,
        *,
        event_type: str,
        event_identity: Mapping[str, Any],
        payload: Mapping[str, Any],
        batch_snapshot_hash: str | None = None,
    ) -> dict[str, Any]:
        self._ensure_writable()
        event_type = _non_empty_token(event_type, "event_type")
        event_identity_dict = dict(safe_data(event_identity))
        payload_dict = dict(safe_data(payload))
        sequence = self.sequence + 1
        record = {
            "schema_version": CONCURRENT_MESSAGE_EXECUTION_JOURNAL_SCHEMA,
            "record_type": "event",
            "event_type": event_type,
            "sequence": sequence,
            "run_id": self.run_id,
            "identity_hash": self.identity_hash,
            "previous_checksum": self.previous_checksum,
            "event_identity": event_identity_dict,
            "batch_snapshot_hash": batch_snapshot_hash,
            "payload": payload_dict,
        }
        self._write_record(record)
        return {
            "sequence": sequence,
            "event_type": event_type,
            "event_identity": event_identity_dict,
            "batch_snapshot_hash": batch_snapshot_hash,
        }

    def status(self) -> dict[str, Any]:
        return _replay_workspace(self.workspace_dir)["status"]

    def _ensure_writable(self) -> None:
        if self.read_only:
            raise RuntimeError("read-only journal cannot append records")

    def _write_record(self, record: dict[str, Any]) -> None:
        serialized_record = dict(safe_data(record))
        serialized_record["checksum"] = _record_checksum(serialized_record)
        _append_jsonl_record(self.journal_path, serialized_record)
        self._apply_record(serialized_record)
        _atomic_write_json(self.status_path, self._current_status())

    def _apply_record(self, record: Mapping[str, Any]) -> None:
        record_type = _as_str(record.get("record_type"))
        sequence = _as_int(record.get("sequence"))
        checksum = _as_str(record.get("checksum"))
        self.sequence = sequence
        self.previous_checksum = checksum
        self.record_count += 1
        identity_value = record.get("event_identity") if record_type == "event" else record.get("snapshot_identity")
        identity_signature = _canonical_json(identity_value)
        if record_type == "event":
            self.event_count += 1
            self._known_event_identities.add(identity_signature)
            event_type = _as_str(record.get("event_type"))
            payload = _require_mapping(record.get("payload"), "event payload")
            if event_type == "variant_started":
                self.started_variant_count += 1
            elif event_type == "variant_terminal":
                self.terminal_variant_count += 1
            elif event_type == "pair_closed":
                self.closed_pair_count += 1
            elif event_type == "batch_committed":
                self.committed_batch_count += 1
            elif event_type == "run_finalized":
                self.finalization_started = True
                self.final_source_hash = _as_str(payload.get("final_source_hash")) or self.final_source_hash
            elif event_type == "run_published":
                self.finalization_started = True
                self.finalized = True
                self.final_source_hash = _as_str(payload.get("final_source_hash")) or self.final_source_hash
            self.last_durable_identity = {
                "record_type": record_type,
                "sequence": sequence,
                "event_type": event_type,
                "event_identity": dict(safe_data(identity_value)) if isinstance(identity_value, Mapping) else identity_value,
                "batch_snapshot_hash": record.get("batch_snapshot_hash"),
            }
            if event_type in {"variant_started", "variant_terminal", "pair_closed", "batch_committed"}:
                batch_snapshot_hash = record.get("batch_snapshot_hash")
                if not isinstance(batch_snapshot_hash, str) or not batch_snapshot_hash:
                    raise ValueError(f"{event_type} records must include a batch_snapshot_hash")
                if batch_snapshot_hash not in self._known_snapshot_hashes:
                    raise ValueError(f"{event_type} references an unknown batch snapshot hash")
            if event_type == "variant_started" or event_type == "variant_terminal":
                if not isinstance(payload.get("pair_id"), str) or not payload.get("pair_id"):
                    raise ValueError(f"{event_type} payload must include pair_id")
        elif record_type == "snapshot":
            self.snapshot_count += 1
            self.planned_batch_count += 1
            self._known_snapshot_identities.add(identity_signature)
            snapshot_hash = _as_str(record.get("snapshot_hash"))
            self._known_snapshot_hashes.add(snapshot_hash)
            self.planned_pair_count += _as_int(record.get("planned_pair_count"))
            self.planned_variant_count += _as_int(record.get("planned_variant_count"))
            self.last_durable_identity = {
                "record_type": record_type,
                "sequence": sequence,
                "snapshot_type": _as_str(record.get("snapshot_type")),
                "snapshot_identity": dict(safe_data(identity_value)) if isinstance(identity_value, Mapping) else identity_value,
                "snapshot_hash": snapshot_hash,
                "snapshot_path": record.get("snapshot_path"),
            }
        else:
            raise ValueError(f"unsupported journal record type: {record_type}")

    def _current_status(self) -> dict[str, Any]:
        expected_batch_count = _expected_batch_count(self.identity)
        output_target = Path(_as_str(self.identity.get("output_target")))
        staging_path = derive_concurrent_execution_publish_staging_dir(output_target, run_id=self.run_id)
        output_exists = output_target.is_dir()
        staging_exists = staging_path.is_dir()
        final_source_hash: str | None = None
        if output_exists:
            manifest_path = output_target / CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON
            if manifest_path.is_file():
                final_source_hash = _sha256_file(manifest_path)
            elif self.finalized:
                raise FileNotFoundError(f"published concurrent message output is missing {manifest_path.name}")
        elif staging_exists:
            manifest_path = staging_path / CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON
            if manifest_path.is_file():
                final_source_hash = _sha256_file(manifest_path)
        lifecycle = "published" if self.finalized else (
            "durable_partial"
            if self.finalization_started or output_exists or staging_exists
            else (
                "ready_to_finalize"
                if expected_batch_count > 0 and self.snapshot_count >= expected_batch_count and self.committed_batch_count >= expected_batch_count
                else ("running" if self.record_count > 0 else "initialized")
            )
        )
        return {
            "schema_version": CONCURRENT_MESSAGE_EXECUTION_STATUS_SCHEMA,
            "run_id": self.run_id,
            "identity_hash": self.identity_hash,
            "lifecycle": lifecycle,
            "deploy_eligibility": False,
            "expected_batch_count": expected_batch_count,
            "planned_batch_count": self.planned_batch_count,
            "planned_pair_count": self.planned_pair_count,
            "planned_variant_count": self.planned_variant_count,
            "started_variant_count": self.started_variant_count,
            "terminal_variant_count": self.terminal_variant_count,
            "closed_pair_count": self.closed_pair_count,
            "committed_batch_count": self.committed_batch_count,
            "snapshot_count": self.snapshot_count,
            "event_count": self.event_count,
            "record_count": self.record_count,
            "finalization_started": self.finalization_started,
            "final_source_path": str(output_target),
            "final_source_hash": final_source_hash,
            "staging_path": str(staging_path) if staging_exists or self.finalization_started else None,
            "last_durable_identity": self.last_durable_identity,
            "inflight_unknown": False,
        }


def _replay_workspace(workspace_dir: Path) -> dict[str, Any]:
    workspace = Path(workspace_dir)
    identity_path = workspace / CONCURRENT_MESSAGE_EXECUTION_RUN_IDENTITY_JSON
    journal_path = workspace / CONCURRENT_MESSAGE_EXECUTION_JOURNAL_JSONL
    if not identity_path.is_file():
        raise FileNotFoundError(f"Concurrent execution workspace is missing {identity_path.name}")
    identity = _read_json_object(identity_path)
    _validate_run_identity(identity)

    expected_batch_count = _expected_batch_count(identity)
    sequence = 0
    previous_checksum: str | None = None
    record_count = 0
    snapshot_count = 0
    event_count = 0
    planned_batch_count = 0
    planned_pair_count = 0
    planned_variant_count = 0
    started_variant_count = 0
    terminal_variant_count = 0
    closed_pair_count = 0
    committed_batch_count = 0
    finalization_started = False
    finalized = False
    final_source_hash: str | None = None
    inflight_unknown = False
    last_durable_identity: dict[str, Any] | None = None
    known_snapshot_hashes: set[str] = set()
    records: list[dict[str, Any]] = []
    seen_event_identities: set[str] = set()
    seen_snapshot_identities: set[str] = set()

    output_target = Path(_as_str(identity.get("output_target")))
    staging_path = derive_concurrent_execution_publish_staging_dir(output_target, run_id=_as_str(identity.get("run_id")))

    active_batch_hash: str | None = None
    active_batch_pair_order: list[str] = []
    active_batch_pair_index = 0
    active_batch_terminal_variants: tuple[str, ...] = ()
    active_batch_pair_event_index = 0

    if journal_path.is_file():
        with journal_path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                raw = line.strip()
                if not raw:
                    continue
                try:
                    record = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"journal line {line_number} is not valid JSON") from exc
                if not isinstance(record, dict):
                    raise ValueError(f"journal line {line_number} must decode to an object")
                if _as_str(record.get("schema_version")) != CONCURRENT_MESSAGE_EXECUTION_JOURNAL_SCHEMA:
                    raise ValueError(f"journal line {line_number} has an unsupported schema version")
                if _as_str(record.get("run_id")) != _as_str(identity.get("run_id")):
                    raise ValueError(f"journal line {line_number} has a mismatched run_id")
                if _as_str(record.get("identity_hash")) != _as_str(identity.get("identity_hash")):
                    raise ValueError(f"journal line {line_number} has a mismatched identity_hash")
                record_type = _as_str(record.get("record_type"))
                if record_type not in {"event", "snapshot"}:
                    raise ValueError(f"journal line {line_number} has unsupported record_type {record_type}")
                record_sequence = _as_int(record.get("sequence"))
                if record_sequence != sequence + 1:
                    raise ValueError(f"journal sequence breaks at line {line_number}")
                if record.get("previous_checksum") != previous_checksum:
                    raise ValueError(f"journal checksum chain breaks at line {line_number}")
                checksum = _as_str(record.get("checksum"))
                if checksum != _record_checksum({k: v for k, v in record.items() if k != "checksum"}):
                    raise ValueError(f"journal checksum mismatch at line {line_number}")

                if finalized:
                    raise ValueError(f"journal records appear after run_published at line {line_number}")

                if record_type == "snapshot":
                    if active_batch_hash is not None:
                        raise ValueError(f"journal batch snapshot breaks at line {line_number}")
                    snapshot_identity_record = record.get("snapshot_identity")
                    snapshot_identity_signature = _canonical_json(snapshot_identity_record)
                    if snapshot_identity_signature in seen_snapshot_identities:
                        raise ValueError(f"duplicate journal snapshot identity at line {line_number}")
                    seen_snapshot_identities.add(snapshot_identity_signature)
                    snapshot_type = _as_str(record.get("snapshot_type"))
                    snapshot_hash = _as_str(record.get("snapshot_hash"))
                    snapshot_path = workspace / _as_str(record.get("snapshot_path"))
                    if not snapshot_path.is_file():
                        raise FileNotFoundError(f"snapshot file missing for journal line {line_number}: {snapshot_path}")
                    if _sha256_file(snapshot_path) != snapshot_hash:
                        raise ValueError(f"snapshot hash mismatch for journal line {line_number}")
                    snapshot_document = _read_json_object(snapshot_path)
                    if _as_str(snapshot_document.get("schema_version")) != CONCURRENT_MESSAGE_EXECUTION_SNAPSHOT_SCHEMA:
                        raise ValueError(f"snapshot file has an unsupported schema version: {snapshot_path}")
                    if _as_str(snapshot_document.get("snapshot_type")) != snapshot_type:
                        raise ValueError(f"snapshot file type mismatch at line {line_number}")
                    snapshot_identity = _require_mapping(snapshot_document.get("snapshot_identity"), "snapshot identity")
                    if _canonical_json(snapshot_identity) != _canonical_json(record.get("snapshot_identity")):
                        raise ValueError(f"snapshot file identity mismatch at line {line_number}")
                    payload = _require_mapping(snapshot_document.get("payload"), "snapshot payload")
                    if _as_int(record.get("planned_pair_count")) != _as_int(payload.get("planned_pair_count")):
                        raise ValueError(f"snapshot pair count mismatch at line {line_number}")
                    if _as_int(record.get("planned_variant_count")) != _as_int(payload.get("planned_variant_count")):
                        raise ValueError(f"snapshot variant count mismatch at line {line_number}")
                    messages = payload.get("messages")
                    if not isinstance(messages, Sequence):
                        raise ValueError(f"snapshot payload messages must be a sequence at line {line_number}")
                    pair_order: list[str] = []
                    for message in messages:
                        message_payload = _require_mapping(message, "snapshot message")
                        selected_pair_plans = message_payload.get("selected_pair_plans", [])
                        if not isinstance(selected_pair_plans, Sequence):
                            raise ValueError(f"snapshot selected_pair_plans must be a sequence at line {line_number}")
                        for pair_plan in selected_pair_plans:
                            pair_plan_payload = _require_mapping(pair_plan, "selected pair plan")
                            pair_id = _as_str(pair_plan_payload.get("pair_id"))
                            if not pair_id:
                                raise ValueError(f"snapshot pair plan is missing pair_id at line {line_number}")
                            pair_order.append(pair_id)
                    planned_batch_count += 1
                    planned_pair_count += _as_int(record.get("planned_pair_count"))
                    planned_variant_count += _as_int(record.get("planned_variant_count"))
                    if len(pair_order) != _as_int(record.get("planned_pair_count")):
                        raise ValueError(f"snapshot pair count does not match selected pair plans at line {line_number}")
                    terminal_variants_raw = payload.get("terminal_variants")
                    if terminal_variants_raw is None:
                        terminal_variants = ("primary", "shadow")
                    elif isinstance(terminal_variants_raw, Sequence) and not isinstance(
                        terminal_variants_raw, (str, bytes)
                    ):
                        terminal_variants = tuple(_as_str(variant) for variant in terminal_variants_raw)
                    else:
                        raise ValueError(f"snapshot terminal_variants must be a sequence at line {line_number}")
                    if terminal_variants not in {("primary", "shadow"), ("primary",)}:
                        raise ValueError(f"snapshot terminal contract is unsupported at line {line_number}")
                    if len(pair_order) * len(terminal_variants) != _as_int(record.get("planned_variant_count")):
                        raise ValueError(f"snapshot variant count does not match selected pair plans at line {line_number}")
                    active_batch_hash = snapshot_hash
                    active_batch_pair_order = pair_order
                    active_batch_pair_index = 0
                    active_batch_terminal_variants = terminal_variants
                    active_batch_pair_event_index = 0
                    known_snapshot_hashes.add(snapshot_hash)
                    last_durable_identity = {
                        "record_type": record_type,
                        "sequence": record_sequence,
                        "snapshot_type": snapshot_type,
                        "snapshot_identity": dict(safe_data(snapshot_identity)),
                        "snapshot_hash": snapshot_hash,
                        "snapshot_path": _as_str(record.get("snapshot_path")),
                    }
                    records.append(
                        {
                            "record_type": "snapshot",
                            "sequence": record_sequence,
                            "snapshot_type": snapshot_type,
                            "snapshot_identity": dict(safe_data(snapshot_identity)),
                            "snapshot_hash": snapshot_hash,
                            "snapshot_path": _as_str(record.get("snapshot_path")),
                            "snapshot_document": dict(safe_data(snapshot_document)),
                        }
                    )
                    previous_checksum = checksum
                    sequence = record_sequence
                    record_count += 1
                    snapshot_count += 1
                    continue

                event_type = _as_str(record.get("event_type"))
                event_identity = _require_mapping(record.get("event_identity"), "event identity")
                event_identity_signature = _canonical_json(event_identity)
                if event_identity_signature in seen_event_identities:
                    raise ValueError(f"duplicate journal event identity at line {line_number}")
                seen_event_identities.add(event_identity_signature)
                payload = _require_mapping(record.get("payload"), "event payload")
                batch_snapshot_hash = _as_str(record.get("batch_snapshot_hash"))
                current_pair_id = active_batch_pair_order[active_batch_pair_index] if active_batch_pair_index < len(active_batch_pair_order) else None
                if event_type == "run_started":
                    if record_sequence != 1 or active_batch_hash is not None:
                        raise ValueError(f"run_started occurs out of order at line {line_number}")
                    records.append(
                        {
                            "record_type": "event",
                            "sequence": record_sequence,
                            "event_type": event_type,
                            "event_identity": dict(safe_data(event_identity)),
                            "batch_snapshot_hash": None,
                            "payload": dict(safe_data(payload)),
                        }
                    )
                    last_durable_identity = {
                        "record_type": record_type,
                        "sequence": record_sequence,
                        "event_type": event_type,
                        "event_identity": dict(safe_data(event_identity)),
                        "batch_snapshot_hash": None,
                    }
                    previous_checksum = checksum
                    sequence = record_sequence
                    record_count += 1
                    event_count += 1
                    continue
                if event_type not in {"run_finalized", "run_published"}:
                    if not batch_snapshot_hash:
                        raise ValueError(f"{event_type} records must include a batch_snapshot_hash")
                    if batch_snapshot_hash not in known_snapshot_hashes:
                        raise ValueError(f"event {event_type} references an unknown snapshot hash at line {line_number}")
                    if active_batch_hash != batch_snapshot_hash:
                        raise ValueError(f"event {event_type} references an out-of-order batch snapshot hash at line {line_number}")

                if event_type == "variant_started":
                    pair_id = _as_str(event_identity.get("pair_id"))
                    decision_variant = _as_str(event_identity.get("decision_variant"))
                    if not pair_id:
                        raise ValueError(f"event {event_type} payload must include pair_id at line {line_number}")
                    if current_pair_id is None or pair_id != current_pair_id:
                        raise ValueError(f"variant_started pair order breaks at line {line_number}")
                    if decision_variant not in active_batch_terminal_variants:
                        raise ValueError(f"event {event_type} has unsupported decision_variant {decision_variant}")
                    if _as_str(payload.get("pair_id")) != pair_id:
                        raise ValueError(f"event {event_type} payload pair_id mismatch at line {line_number}")
                    if active_batch_pair_event_index >= len(active_batch_terminal_variants):
                        raise ValueError(f"variant_started occurs out of order at line {line_number}")
                    expected_variant = active_batch_terminal_variants[active_batch_pair_event_index]
                    if decision_variant != expected_variant:
                        raise ValueError(
                            f"event {event_type} must start {expected_variant} next at line {line_number}"
                        )
                    active_batch_pair_event_index += 1
                    started_variant_count += 1
                    last_durable_identity = {
                        "record_type": record_type,
                        "sequence": record_sequence,
                        "event_type": event_type,
                        "event_identity": dict(safe_data(event_identity)),
                        "batch_snapshot_hash": batch_snapshot_hash,
                    }
                    records.append(
                        {
                            "record_type": "event",
                            "sequence": record_sequence,
                            "event_type": event_type,
                            "event_identity": dict(safe_data(event_identity)),
                            "batch_snapshot_hash": batch_snapshot_hash,
                            "payload": dict(safe_data(payload)),
                        }
                    )
                elif event_type == "variant_terminal":
                    pair_id = _as_str(event_identity.get("pair_id"))
                    decision_variant = _as_str(event_identity.get("decision_variant"))
                    if not pair_id:
                        raise ValueError(f"event {event_type} payload must include pair_id at line {line_number}")
                    if current_pair_id is None or pair_id != current_pair_id:
                        raise ValueError(f"variant_terminal pair order breaks at line {line_number}")
                    if decision_variant not in active_batch_terminal_variants:
                        raise ValueError(f"event {event_type} has unsupported decision_variant {decision_variant}")
                    if _as_str(payload.get("pair_id")) != pair_id:
                        raise ValueError(f"event {event_type} payload pair_id mismatch at line {line_number}")
                    terminal_index = active_batch_pair_event_index - len(active_batch_terminal_variants)
                    if terminal_index < 0 or terminal_index >= len(active_batch_terminal_variants):
                        raise ValueError(f"variant_terminal occurs out of order at line {line_number}")
                    expected_variant = active_batch_terminal_variants[terminal_index]
                    if decision_variant != expected_variant:
                        raise ValueError(
                            f"event {event_type} must close {expected_variant} next at line {line_number}"
                        )
                    active_batch_pair_event_index += 1
                    terminal_variant_count += 1
                    last_durable_identity = {
                        "record_type": record_type,
                        "sequence": record_sequence,
                        "event_type": event_type,
                        "event_identity": dict(safe_data(event_identity)),
                        "batch_snapshot_hash": batch_snapshot_hash,
                    }
                    records.append(
                        {
                            "record_type": "event",
                            "sequence": record_sequence,
                            "event_type": event_type,
                            "event_identity": dict(safe_data(event_identity)),
                            "batch_snapshot_hash": batch_snapshot_hash,
                            "payload": dict(safe_data(payload)),
                        }
                    )
                elif event_type == "pair_closed":
                    pair_id = _as_str(event_identity.get("pair_id"))
                    if not pair_id:
                        raise ValueError(f"event {event_type} payload must include pair_id at line {line_number}")
                    if current_pair_id is None or pair_id != current_pair_id:
                        raise ValueError(f"pair_closed pair order breaks at line {line_number}")
                    if active_batch_pair_event_index != 2 * len(active_batch_terminal_variants):
                        raise ValueError(f"pair_closed occurs before required terminals at line {line_number}")
                    if _as_str(payload.get("pair_id")) != pair_id:
                        raise ValueError(f"event {event_type} payload pair_id mismatch at line {line_number}")
                    active_batch_pair_event_index = 0
                    active_batch_pair_index += 1
                    closed_pair_count += 1
                    last_durable_identity = {
                        "record_type": record_type,
                        "sequence": record_sequence,
                        "event_type": event_type,
                        "event_identity": dict(safe_data(event_identity)),
                        "batch_snapshot_hash": batch_snapshot_hash,
                    }
                    records.append(
                        {
                            "record_type": "event",
                            "sequence": record_sequence,
                            "event_type": event_type,
                            "event_identity": dict(safe_data(event_identity)),
                            "batch_snapshot_hash": batch_snapshot_hash,
                            "payload": dict(safe_data(payload)),
                        }
                    )
                elif event_type == "batch_committed":
                    if active_batch_pair_index != len(active_batch_pair_order) or active_batch_pair_event_index != 0:
                        raise ValueError(f"batch_committed occurs before all pairs close at line {line_number}")
                    committed_user_ids = payload.get("committed_user_ids", [])
                    if not isinstance(committed_user_ids, Sequence):
                        raise ValueError(f"batch_committed committed_user_ids must be a sequence at line {line_number}")
                    committed_user_count = _as_int(payload.get("committed_user_count"))
                    if committed_user_count != len(committed_user_ids):
                        raise ValueError(f"batch_committed committed_user_count mismatch at line {line_number}")
                    batch_pair_count = _as_int(payload.get("batch_pair_count"))
                    if batch_pair_count != len(active_batch_pair_order):
                        raise ValueError(f"batch_committed batch_pair_count mismatch at line {line_number}")
                    committed_batch_count += 1
                    active_batch_hash = None
                    active_batch_pair_order = []
                    active_batch_pair_index = 0
                    active_batch_terminal_variants = ()
                    active_batch_pair_event_index = 0
                    last_durable_identity = {
                        "record_type": record_type,
                        "sequence": record_sequence,
                        "event_type": event_type,
                        "event_identity": dict(safe_data(event_identity)),
                        "batch_snapshot_hash": batch_snapshot_hash,
                    }
                    records.append(
                        {
                            "record_type": "event",
                            "sequence": record_sequence,
                            "event_type": event_type,
                            "event_identity": dict(safe_data(event_identity)),
                            "batch_snapshot_hash": batch_snapshot_hash,
                            "payload": dict(safe_data(payload)),
                        }
                    )
                elif event_type == "run_finalized":
                    if committed_batch_count != expected_batch_count:
                        raise ValueError(f"run_finalized occurs before the last batch is committed at line {line_number}")
                    finalization_started = True
                    final_source_hash = _as_str(payload.get("final_source_hash")) or final_source_hash
                    last_durable_identity = {
                        "record_type": record_type,
                        "sequence": record_sequence,
                        "event_type": event_type,
                        "event_identity": dict(safe_data(event_identity)),
                        "batch_snapshot_hash": record.get("batch_snapshot_hash"),
                    }
                    records.append(
                        {
                            "record_type": "event",
                            "sequence": record_sequence,
                            "event_type": event_type,
                            "event_identity": dict(safe_data(event_identity)),
                            "batch_snapshot_hash": batch_snapshot_hash or None,
                            "payload": dict(safe_data(payload)),
                        }
                    )
                elif event_type == "run_published":
                    if committed_batch_count != expected_batch_count:
                        raise ValueError(f"run_published occurs before the last batch is committed at line {line_number}")
                    finalized = True
                    finalization_started = True
                    final_source_hash = _as_str(payload.get("final_source_hash")) or final_source_hash
                    last_durable_identity = {
                        "record_type": record_type,
                        "sequence": record_sequence,
                        "event_type": event_type,
                        "event_identity": dict(safe_data(event_identity)),
                        "batch_snapshot_hash": record.get("batch_snapshot_hash"),
                    }
                    records.append(
                        {
                            "record_type": "event",
                            "sequence": record_sequence,
                            "event_type": event_type,
                            "event_identity": dict(safe_data(event_identity)),
                            "batch_snapshot_hash": batch_snapshot_hash or None,
                            "payload": dict(safe_data(payload)),
                        }
                    )
                else:
                    raise ValueError(f"unsupported journal event type: {event_type}")

                previous_checksum = checksum
                sequence = record_sequence
                record_count += 1
                event_count += 1

    if active_batch_hash is not None and not finalized:
        if 0 < active_batch_pair_event_index <= len(active_batch_terminal_variants):
            inflight_unknown = True
        if active_batch_pair_index < len(active_batch_pair_order) and active_batch_pair_event_index == 0:
            inflight_unknown = False

    output_exists = output_target.is_dir()
    if finalized:
        if snapshot_count != expected_batch_count:
            raise ValueError("finalized journal does not contain the expected batch snapshots")
        if committed_batch_count != expected_batch_count:
            raise ValueError("finalized journal does not contain the expected batch commits")
        if closed_pair_count != planned_pair_count:
            raise ValueError("finalized journal does not close the planned pair count")
        if started_variant_count != planned_variant_count:
            raise ValueError("finalized journal does not close the planned variant count")
        if terminal_variant_count != planned_variant_count:
            raise ValueError("finalized journal does not close the terminal variant count")
        if not output_exists:
            raise FileNotFoundError(f"published concurrent message output is missing: {output_target}")
        manifest_path = output_target / CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON
        if not manifest_path.is_file():
            raise FileNotFoundError(f"published concurrent message output is missing {manifest_path.name}")
        manifest_hash = _sha256_file(manifest_path)
        if final_source_hash is None:
            final_source_hash = manifest_hash
        elif final_source_hash != manifest_hash:
            raise ValueError("published concurrent message final source hash mismatch")
    elif output_exists:
        manifest_path = output_target / CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON
        if manifest_path.is_file() and final_source_hash is None:
            final_source_hash = _sha256_file(manifest_path)
    elif staging_path.is_dir():
        manifest_path = staging_path / CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON
        if manifest_path.is_file() and final_source_hash is None:
            final_source_hash = _sha256_file(manifest_path)

    lifecycle = "published" if finalized else (
        "inflight_unknown"
        if inflight_unknown
        else (
            "durable_partial"
            if finalization_started or output_exists or staging_path.is_dir()
            else (
                "ready_to_finalize"
                if expected_batch_count > 0 and snapshot_count >= expected_batch_count and committed_batch_count >= expected_batch_count
                else ("running" if record_count > 0 else "initialized")
            )
        )
    )
    status = {
        "schema_version": CONCURRENT_MESSAGE_EXECUTION_STATUS_SCHEMA,
        "run_id": _as_str(identity.get("run_id")),
        "identity_hash": _as_str(identity.get("identity_hash")),
        "lifecycle": lifecycle,
        "deploy_eligibility": False,
        "expected_batch_count": expected_batch_count,
        "planned_batch_count": planned_batch_count,
        "planned_pair_count": planned_pair_count,
        "planned_variant_count": planned_variant_count,
        "started_variant_count": started_variant_count,
        "terminal_variant_count": terminal_variant_count,
        "closed_pair_count": closed_pair_count,
        "committed_batch_count": committed_batch_count,
        "snapshot_count": snapshot_count,
        "event_count": event_count,
        "record_count": record_count,
        "finalization_started": finalization_started,
        "final_source_path": str(output_target),
        "final_source_hash": final_source_hash,
        "staging_path": str(staging_path) if finalization_started or staging_path.is_dir() else None,
        "last_durable_identity": last_durable_identity,
        "inflight_unknown": inflight_unknown,
    }
    return {
        "identity": dict(safe_data(identity)),
        "status": status,
        "records": records,
    }
def _validate_run_identity(identity: Mapping[str, Any]) -> None:
    if _as_str(identity.get("schema_version")) != CONCURRENT_MESSAGE_EXECUTION_RUN_IDENTITY_SCHEMA:
        raise ValueError("run identity has an unsupported schema version")
    if not _as_str(identity.get("run_id")):
        raise ValueError("run identity must include run_id")
    if not _as_str(identity.get("identity_hash")):
        raise ValueError("run identity must include identity_hash")
    identity_body = {k: v for k, v in identity.items() if k not in {"run_id", "identity_hash"}}
    expected_hash = _sha256_text(_canonical_json(identity_body))
    if expected_hash != _as_str(identity.get("identity_hash")):
        raise ValueError("run identity hash mismatch")
    if not isinstance(identity.get("configuration"), Mapping):
        raise ValueError("run identity must include configuration")
    if not isinstance(identity.get("messages"), Sequence):
        raise ValueError("run identity must include messages")
    if not isinstance(identity.get("sample_data_fingerprints"), Mapping):
        raise ValueError("run identity must include sample_data_fingerprints")
    if not isinstance(identity.get("provider_contract"), Mapping):
        raise ValueError("run identity must include provider_contract")
    if not isinstance(identity.get("prompt_contract"), Mapping):
        raise ValueError("run identity must include prompt_contract")


def _ensure_workspace_is_available(workspace: Path) -> None:
    if workspace.exists():
        if workspace.is_file():
            raise FileExistsError(f"Concurrent execution workspace already exists as a file: {workspace}")
        if any(workspace.iterdir()):
            raise FileExistsError(f"Concurrent execution workspace already exists and is not empty: {workspace}")


def _expected_batch_count(identity: Mapping[str, Any]) -> int:
    configuration = _require_mapping(identity.get("configuration"), "run identity configuration")
    return _as_int(configuration.get("horizon"))


def _append_jsonl_record(path: Path, record: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(safe_data(record), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(safe_data(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
        temp_path = Path(handle.name)
    os.replace(temp_path, path)
    _fsync_parent_directory(path.parent)


def _fsync_parent_directory(path: Path) -> None:
    try:
        dir_fd = os.open(path, os.O_DIRECTORY)
    except (AttributeError, NotADirectoryError, FileNotFoundError, OSError):
        return
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _acquire_workspace_lock(workspace: Path) -> Any:
    lock_path = workspace / CONCURRENT_MESSAGE_EXECUTION_LOCK_FILE
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except Exception:
        handle.close()
        raise
    return handle


def _read_last_journal_checksum(path: Path) -> str | None:
    if not path.is_file():
        return None
    last_record: str | None = None
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if raw:
                last_record = raw
    if last_record is None:
        return None
    record = json.loads(last_record)
    if not isinstance(record, dict):
        raise ValueError(f"expected {path.name} to contain JSON object records")
    return _as_str(record.get("checksum")) or None


def _read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected {path.name} to contain a JSON object")
    return payload


def _require_mapping(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{context} must be a mapping")
    return dict(value)


def _non_empty_token(value: str, field_name: str) -> str:
    token = value.strip()
    if not token:
        raise ValueError(f"{field_name} must not be empty")
    return token


def _canonical_json(value: Any) -> str:
    return json.dumps(safe_data(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _record_checksum(record: Mapping[str, Any]) -> str:
    return _sha256_text(_canonical_json(record))


def _sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _as_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


def _as_int(value: Any) -> int:
    if isinstance(value, bool):
        raise TypeError("boolean values are not valid integers")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        return int(value)
    raise TypeError(f"expected integer-compatible value, got {value!r}")
