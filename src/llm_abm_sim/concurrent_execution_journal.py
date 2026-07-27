from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from .safe_serialization import safe_data

CONCURRENT_MESSAGE_EXECUTION_RUN_IDENTITY_SCHEMA = "concurrent-message-execution-run-identity-v1"
CONCURRENT_MESSAGE_EXECUTION_JOURNAL_SCHEMA = "concurrent-message-execution-journal-v1"
CONCURRENT_MESSAGE_EXECUTION_STATUS_SCHEMA = "concurrent-message-execution-status-v1"
CONCURRENT_MESSAGE_EXECUTION_SNAPSHOT_SCHEMA = "concurrent-message-execution-snapshot-v1"

CONCURRENT_MESSAGE_EXECUTION_RUN_IDENTITY_JSON = "concurrent_message_execution_run_identity.json"
CONCURRENT_MESSAGE_EXECUTION_JOURNAL_JSONL = "concurrent_message_execution_journal.jsonl"
CONCURRENT_MESSAGE_EXECUTION_STATUS_JSON = "concurrent_message_execution_status.json"
CONCURRENT_MESSAGE_EXECUTION_SNAPSHOTS_DIR = "concurrent_message_execution_snapshots"

_CONCURRENT_MESSAGE_REQUIRED_DATASET_FILES = ("videos.csv", "users.csv")
_CONCURRENT_MESSAGE_OPTIONAL_COMMENT_FILES = ("all_comments.csv", "comments.csv")


def derive_concurrent_execution_workspace(output_dir: str | Path) -> Path:
    output_path = Path(output_dir)
    return output_path.parent / f".{output_path.name}.operational"


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
        "provider_contract": {
            "primary": dict(safe_data(primary_provider_metadata)),
            "shadow": dict(safe_data(shadow_provider_metadata)),
        },
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
    finalized: bool = False
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
        return _summarize_workspace(self.workspace_dir)

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
                self.finalized = True
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
        lifecycle = _lifecycle_state(
            expected_batch_count=expected_batch_count,
            snapshot_count=self.snapshot_count,
            committed_batch_count=self.committed_batch_count,
            record_count=self.record_count,
            finalized=self.finalized,
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
            "last_durable_identity": self.last_durable_identity,
        }


def _summarize_workspace(workspace_dir: Path) -> dict[str, Any]:
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
    finalized = False
    last_durable_identity: dict[str, Any] | None = None
    known_snapshot_hashes: set[str] = set()
    seen_event_identities: set[str] = set()
    seen_snapshot_identities: set[str] = set()

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

                identity_value = record.get("event_identity") if record_type == "event" else record.get("snapshot_identity")
                identity_signature = _canonical_json(identity_value)
                if record_type == "event":
                    event_type = _as_str(record.get("event_type"))
                    if identity_signature in seen_event_identities:
                        raise ValueError(f"duplicate journal event identity at line {line_number}")
                    seen_event_identities.add(identity_signature)
                    payload = _require_mapping(record.get("payload"), "event payload")
                    if event_type == "variant_started":
                        started_variant_count += 1
                    elif event_type == "variant_terminal":
                        terminal_variant_count += 1
                    elif event_type == "pair_closed":
                        closed_pair_count += 1
                    elif event_type == "batch_committed":
                        committed_batch_count += 1
                    elif event_type == "run_finalized":
                        finalized = True
                    if event_type in {"variant_started", "variant_terminal", "pair_closed", "batch_committed"}:
                        batch_snapshot_hash = record.get("batch_snapshot_hash")
                        if not isinstance(batch_snapshot_hash, str) or batch_snapshot_hash not in known_snapshot_hashes:
                            raise ValueError(f"event {event_type} references an unknown snapshot hash at line {line_number}")
                    if event_type in {"variant_started", "variant_terminal"}:
                        if not _as_str(payload.get("pair_id")):
                            raise ValueError(f"event {event_type} payload must include pair_id")
                    last_durable_identity = {
                        "record_type": record_type,
                        "sequence": record_sequence,
                        "event_type": event_type,
                        "event_identity": dict(safe_data(identity_value)) if isinstance(identity_value, Mapping) else identity_value,
                        "batch_snapshot_hash": record.get("batch_snapshot_hash"),
                    }
                else:
                    if identity_signature in seen_snapshot_identities:
                        raise ValueError(f"duplicate journal snapshot identity at line {line_number}")
                    seen_snapshot_identities.add(identity_signature)
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
                    if _canonical_json(snapshot_document.get("snapshot_identity")) != _canonical_json(identity_value):
                        raise ValueError(f"snapshot file identity mismatch at line {line_number}")
                    payload = _require_mapping(snapshot_document.get("payload"), "snapshot payload")
                    if _as_int(record.get("planned_pair_count")) != _as_int(payload.get("planned_pair_count")):
                        raise ValueError(f"snapshot pair count mismatch at line {line_number}")
                    if _as_int(record.get("planned_variant_count")) != _as_int(payload.get("planned_variant_count")):
                        raise ValueError(f"snapshot variant count mismatch at line {line_number}")
                    planned_batch_count += 1
                    planned_pair_count += _as_int(record.get("planned_pair_count"))
                    planned_variant_count += _as_int(record.get("planned_variant_count"))
                    known_snapshot_hashes.add(snapshot_hash)
                    last_durable_identity = {
                        "record_type": record_type,
                        "sequence": record_sequence,
                        "snapshot_type": snapshot_type,
                        "snapshot_identity": dict(safe_data(identity_value)) if isinstance(identity_value, Mapping) else identity_value,
                        "snapshot_hash": snapshot_hash,
                        "snapshot_path": _as_str(record.get("snapshot_path")),
                    }

                previous_checksum = checksum
                sequence = record_sequence
                record_count += 1
                if record_type == "event":
                    event_count += 1
                else:
                    snapshot_count += 1

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

    lifecycle = _lifecycle_state(
        expected_batch_count=expected_batch_count,
        snapshot_count=snapshot_count,
        committed_batch_count=committed_batch_count,
        record_count=record_count,
        finalized=finalized,
    )
    return {
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
        "last_durable_identity": last_durable_identity,
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


def _lifecycle_state(*, expected_batch_count: int, snapshot_count: int, committed_batch_count: int, record_count: int, finalized: bool) -> str:
    if finalized:
        return "complete"
    if expected_batch_count > 0 and snapshot_count >= expected_batch_count and committed_batch_count >= expected_batch_count:
        return "ready_for_finalization"
    if record_count > 0:
        return "running"
    return "initialized"


def _write_status_file(path: Path, payload: Mapping[str, Any]) -> None:
    _atomic_write_json(path, payload)


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
