from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .safe_serialization import safe_data

_CONCURRENT_RUNTIME_BATCH_SPOOL_SCHEMA = "concurrent-runtime-batch-spool-v1"
_CONCURRENT_RUNTIME_BATCH_SPOOL_REF_SCHEMA = "concurrent-runtime-batch-spool-ref-v1"
_CONCURRENT_RUNTIME_BATCH_SPOOL_DIR = "concurrent_runtime_batch_spool"
_BATCH_CHUNK_NAME = re.compile(r"batch-(?P<time_step>[0-9]{6})\.json")
_BATCH_PENDING_NAME = re.compile(r"\.batch-(?P<time_step>[0-9]{6})-(?P<sha256>[0-9a-f]{64})\.pending")
_ROW_KINDS = ("candidate_rows", "result_rows", "terminal_rows", "variant_evidence_rows")


@dataclass(frozen=True)
class _ConcurrentRuntimeSpoolChunk:
    time_step: int
    batch_snapshot_hash: str
    terminal_variants: tuple[str, ...]
    commit: dict[str, object]
    candidate_rows: list[dict[str, object]]
    result_rows: list[dict[str, object]]
    terminal_rows: list[dict[str, object]]
    variant_evidence_rows: list[dict[str, object]]

    @property
    def resident_row_count(self) -> int:
        return sum(
            len(rows)
            for rows in (
                self.candidate_rows,
                self.result_rows,
                self.terminal_rows,
                self.variant_evidence_rows,
            )
        )


@dataclass(frozen=True)
class _ConcurrentRuntimeJournalCommit:
    ref: dict[str, object]
    committed_user_ids: list[str]
    batch_pair_count: int


@dataclass(frozen=True)
class _ConcurrentRuntimeMaterializedRows:
    candidate_rows: list[dict[str, object]]
    result_rows: list[dict[str, object]]
    terminal_rows: list[dict[str, object]]
    variant_evidence_rows: list[dict[str, object]]
    commits: list[dict[str, object]]


class _ConcurrentRuntimeBatchSpool:
    """Own append-only batch chunks and canonical replay behind a private runtime Interface."""

    def __init__(
        self,
        workspace_dir: str | Path,
        *,
        run_id: str,
        identity_hash: str,
        terminal_variants: tuple[str, ...],
        recover_prepared: bool = False,
    ) -> None:
        self.workspace_dir = Path(workspace_dir)
        self.spool_dir = self.workspace_dir / _CONCURRENT_RUNTIME_BATCH_SPOOL_DIR
        self.run_id = _non_empty(run_id, "run_id")
        self.identity_hash = _sha256(identity_hash, "identity_hash")
        if terminal_variants not in {("primary",), ("primary", "shadow")}:
            raise ValueError("runtime spool terminal contract is unsupported")
        self.terminal_variants = terminal_variants
        self.recover_prepared = recover_prepared
        _require_real_directory(self.workspace_dir, "runtime workspace")
        if self.spool_dir.exists() or self.spool_dir.is_symlink():
            _require_real_directory(self.spool_dir, "runtime batch spool")

    def prepare_batch(
        self,
        *,
        time_step: int,
        batch_snapshot_hash: str,
        commit: Mapping[str, object],
        candidate_rows: Sequence[Mapping[str, object]],
        result_rows: Sequence[Mapping[str, object]],
        terminal_rows: Sequence[Mapping[str, object]],
        variant_evidence_rows: Sequence[Mapping[str, object]],
    ) -> dict[str, object]:
        if time_step < 0:
            raise ValueError("runtime spool time_step must be non-negative")
        snapshot_hash = _sha256(batch_snapshot_hash, "batch_snapshot_hash")
        self._ensure_spool_dir()
        serialized_rows = {
            "candidate_rows": list(safe_data(list(candidate_rows))),
            "result_rows": list(safe_data(list(result_rows))),
            "terminal_rows": list(safe_data(list(terminal_rows))),
            "variant_evidence_rows": list(safe_data(list(variant_evidence_rows))),
        }
        document = {
            "schema_version": _CONCURRENT_RUNTIME_BATCH_SPOOL_SCHEMA,
            "chunk_identity": {
                "run_id": self.run_id,
                "identity_hash": self.identity_hash,
                "time_step": time_step,
                "batch_snapshot_hash": snapshot_hash,
                "terminal_variants": list(self.terminal_variants),
            },
            "commit": dict(safe_data(commit)),
            "row_field_order": {
                row_kind: _row_field_order(rows, row_kind)
                for row_kind, rows in serialized_rows.items()
            },
            "rows": serialized_rows,
        }
        content = _canonical_json_bytes(document)
        chunk = self._decode_chunk(content, expected_time_step=time_step, expected_snapshot_hash=snapshot_hash)
        digest = hashlib.sha256(content).hexdigest()
        final_paths, pending_paths = _chunk_inventory(self.spool_dir)
        if set(final_paths) != set(range(time_step)):
            raise ValueError("runtime batch spool chunks are missing, extra, or non-contiguous before prepare")
        if set(pending_paths) - {time_step}:
            raise ValueError("runtime batch spool contains an extra prepared chunk")
        target = self.spool_dir / _chunk_name(time_step)
        pending = self.spool_dir / _pending_name(time_step, digest)
        existing_pending = pending_paths.get(time_step)
        if existing_pending is None:
            _exclusive_write(pending, content)
        elif existing_pending != pending or existing_pending.read_bytes() != content:
            raise ValueError("runtime batch spool prepared chunk does not match the replayed active batch")
        return {
            "schema_version": _CONCURRENT_RUNTIME_BATCH_SPOOL_REF_SCHEMA,
            "relative_path": f"{_CONCURRENT_RUNTIME_BATCH_SPOOL_DIR}/{target.name}",
            "sha256": digest,
            "run_id": self.run_id,
            "identity_hash": self.identity_hash,
            "time_step": time_step,
            "batch_snapshot_hash": snapshot_hash,
            "terminal_variants": list(self.terminal_variants),
            "row_counts": {
                "candidate_rows": len(chunk.candidate_rows),
                "result_rows": len(chunk.result_rows),
                "terminal_rows": len(chunk.terminal_rows),
                "variant_evidence_rows": len(chunk.variant_evidence_rows),
            },
        }

    def publish_prepared(self, ref: Mapping[str, object]) -> None:
        time_step = _integer(ref.get("time_step"), "spool reference time_step")
        target, pending = self._ref_paths(ref, expected_time_step=time_step)
        expected_hash = _sha256(ref.get("sha256"), "spool chunk sha256")
        if target.exists() or target.is_symlink():
            _require_regular_file(target, f"runtime batch spool chunk {time_step}")
            if hashlib.sha256(target.read_bytes()).hexdigest() != expected_hash:
                raise ValueError(f"runtime batch spool checksum mismatch at time_step {time_step}")
            if pending.exists() or pending.is_symlink():
                raise ValueError("runtime batch spool retains a prepared file after publication")
            return
        _require_regular_file(pending, f"runtime batch spool prepared chunk {time_step}")
        raw = pending.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected_hash:
            raise ValueError(f"runtime batch spool prepared checksum mismatch at time_step {time_step}")
        expected_snapshot_hash = _sha256(ref.get("batch_snapshot_hash"), "batch_snapshot_hash")
        self._decode_chunk(raw, expected_time_step=time_step, expected_snapshot_hash=expected_snapshot_hash)
        os.replace(pending, target)
        _fsync_directory(self.spool_dir)

    def validate_prepared_state(self, *, active_time_step: int | None, active_batch_complete: bool) -> None:
        if not (self.spool_dir.exists() or self.spool_dir.is_symlink()):
            return
        _require_real_directory(self.spool_dir, "runtime batch spool")
        _, pending_paths = _chunk_inventory(self.spool_dir)
        if not pending_paths:
            return
        if active_time_step is None or set(pending_paths) != {active_time_step} or not active_batch_complete:
            raise ValueError("runtime batch spool prepared chunk is not owned by one complete active batch")

    def iter_committed(self, replay: Mapping[str, object]) -> Iterator[_ConcurrentRuntimeSpoolChunk]:
        journal_commits = self._commit_refs(replay)
        status = _mapping(replay.get("status"), "runtime replay status")
        committed_batch_count = _integer(status.get("committed_batch_count"), "committed batch count")
        if len(journal_commits) != committed_batch_count:
            raise ValueError("runtime batch spool references do not close the journal committed batch count")
        if not (self.spool_dir.exists() or self.spool_dir.is_symlink()):
            if journal_commits:
                raise FileNotFoundError("runtime batch spool is missing for committed journal batches")
            return

        _require_real_directory(self.spool_dir, "runtime batch spool")
        if self.recover_prepared:
            for journal_commit in journal_commits:
                ref = journal_commit.ref
                time_step = _integer(ref.get("time_step"), "spool reference time_step")
                target, pending = self._ref_paths(ref, expected_time_step=time_step)
                if not (target.exists() or target.is_symlink()) and (pending.exists() or pending.is_symlink()):
                    self.publish_prepared(ref)

        final_paths, pending_paths = _chunk_inventory(self.spool_dir)
        expected_time_steps = set(range(len(journal_commits)))
        if set(final_paths) != expected_time_steps:
            missing = sorted(expected_time_steps - set(final_paths))
            extra = sorted(set(final_paths) - expected_time_steps)
            raise ValueError(f"runtime batch spool chunk inventory mismatch: missing={missing}, extra={extra}")
        active_time_step = _active_snapshot_time_step(replay)
        allowed_pending = {active_time_step} if active_time_step == len(journal_commits) else set()
        if set(pending_paths) - allowed_pending:
            raise ValueError("runtime batch spool contains an extra prepared chunk")

        for expected_time_step, journal_commit in enumerate(journal_commits):
            ref = journal_commit.ref
            path, _ = self._ref_paths(ref, expected_time_step=expected_time_step)
            _require_regular_file(path, f"runtime batch spool chunk {expected_time_step}")
            raw = path.read_bytes()
            expected_hash = _sha256(ref.get("sha256"), "spool chunk sha256")
            if hashlib.sha256(raw).hexdigest() != expected_hash:
                raise ValueError(f"runtime batch spool checksum mismatch at time_step {expected_time_step}")
            expected_snapshot_hash = _sha256(ref.get("batch_snapshot_hash"), "batch_snapshot_hash")
            chunk = self._decode_chunk(
                raw,
                expected_time_step=expected_time_step,
                expected_snapshot_hash=expected_snapshot_hash,
            )
            expected_counts = _mapping(ref.get("row_counts"), "spool row_counts")
            actual_counts = {
                "candidate_rows": len(chunk.candidate_rows),
                "result_rows": len(chunk.result_rows),
                "terminal_rows": len(chunk.terminal_rows),
                "variant_evidence_rows": len(chunk.variant_evidence_rows),
            }
            if expected_counts != actual_counts:
                raise ValueError(f"runtime batch spool row counts mismatch at time_step {expected_time_step}")
            chunk_committed_user_ids = _string_list(
                chunk.commit.get("committed_primary_positive_user_ids"),
                "spooled committed Primary-positive users",
            )
            if chunk_committed_user_ids != journal_commit.committed_user_ids:
                raise ValueError("runtime batch spool committed users are crossed with the journal")
            if len(chunk.result_rows) != journal_commit.batch_pair_count:
                raise ValueError("runtime batch spool result count is crossed with the journal")
            yield chunk

    def materialize(self, replay: Mapping[str, object]) -> _ConcurrentRuntimeMaterializedRows:
        candidate_rows: list[dict[str, object]] = []
        result_rows: list[dict[str, object]] = []
        terminal_rows: list[dict[str, object]] = []
        variant_evidence_rows: list[dict[str, object]] = []
        commits: list[dict[str, object]] = []
        for chunk in self.iter_committed(replay):
            candidate_rows.extend(chunk.candidate_rows)
            result_rows.extend(chunk.result_rows)
            terminal_rows.extend(chunk.terminal_rows)
            variant_evidence_rows.extend(chunk.variant_evidence_rows)
            commits.append(chunk.commit)
        return _ConcurrentRuntimeMaterializedRows(
            candidate_rows=candidate_rows,
            result_rows=result_rows,
            terminal_rows=terminal_rows,
            variant_evidence_rows=variant_evidence_rows,
            commits=commits,
        )

    def _ensure_spool_dir(self) -> None:
        if self.spool_dir.exists() or self.spool_dir.is_symlink():
            _require_real_directory(self.spool_dir, "runtime batch spool")
            return
        self.spool_dir.mkdir()
        _fsync_directory(self.workspace_dir)
        _require_real_directory(self.spool_dir, "runtime batch spool")

    def _commit_refs(self, replay: Mapping[str, object]) -> list[_ConcurrentRuntimeJournalCommit]:
        records = replay.get("records", [])
        if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
            raise TypeError("runtime replay records must be a sequence")
        commits: list[_ConcurrentRuntimeJournalCommit] = []
        for record_raw in records:
            record = _mapping(record_raw, "runtime replay record")
            if record.get("record_type") != "event" or record.get("event_type") != "batch_committed":
                continue
            expected_time_step = len(commits)
            event_identity = _mapping(record.get("event_identity"), "batch_committed event identity")
            payload = _mapping(record.get("payload"), "batch_committed payload")
            ref = _mapping(payload.get("batch_spool_chunk"), "batch_committed spool reference")
            if ref.get("schema_version") != _CONCURRENT_RUNTIME_BATCH_SPOOL_REF_SCHEMA:
                raise ValueError("runtime batch spool reference has an unsupported schema version")
            if any(
                _integer(value, "batch_committed time_step") != expected_time_step
                for value in (event_identity.get("time_step"), payload.get("time_step"), ref.get("time_step"))
            ):
                raise ValueError("runtime batch spool reference time_step is crossed with the journal")
            if ref.get("batch_snapshot_hash") != record.get("batch_snapshot_hash"):
                raise ValueError("runtime batch spool snapshot identity is crossed with the journal")
            commits.append(
                _ConcurrentRuntimeJournalCommit(
                    ref=ref,
                    committed_user_ids=_string_list(payload.get("committed_user_ids"), "journal committed users"),
                    batch_pair_count=_integer(payload.get("batch_pair_count"), "journal batch pair count"),
                )
            )
        return commits

    def _ref_paths(self, ref: Mapping[str, object], *, expected_time_step: int) -> tuple[Path, Path]:
        if ref.get("run_id") != self.run_id or ref.get("identity_hash") != self.identity_hash:
            raise ValueError(f"runtime batch spool reference identity mismatch at time_step {expected_time_step}")
        if _integer(ref.get("time_step"), "spool reference time_step") != expected_time_step:
            raise ValueError("runtime batch spool references are missing, extra, or out of order")
        variants_raw = ref.get("terminal_variants")
        if not isinstance(variants_raw, Sequence) or isinstance(variants_raw, (str, bytes)):
            raise ValueError("runtime batch spool reference terminal_variants must be a sequence")
        if tuple(str(item) for item in variants_raw) != self.terminal_variants:
            raise ValueError("runtime batch spool reference terminal contract mismatch")

        relative_raw = ref.get("relative_path")
        if not isinstance(relative_raw, str):
            raise ValueError("runtime batch spool reference path must be a string")
        relative = PurePosixPath(relative_raw)
        expected_name = _chunk_name(expected_time_step)
        if relative.is_absolute() or relative.parts != (_CONCURRENT_RUNTIME_BATCH_SPOOL_DIR, expected_name):
            raise ValueError("runtime batch spool reference path escapes its private spool directory")
        target = self.workspace_dir / Path(*relative.parts)
        if target.parent.resolve(strict=True) != self.spool_dir.resolve(strict=True):
            raise ValueError("runtime batch spool reference path escapes its private spool directory")
        expected_hash = _sha256(ref.get("sha256"), "spool chunk sha256")
        pending = self.spool_dir / _pending_name(expected_time_step, expected_hash)
        return target, pending

    def _decode_chunk(
        self,
        raw: bytes,
        *,
        expected_time_step: int,
        expected_snapshot_hash: str,
    ) -> _ConcurrentRuntimeSpoolChunk:
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"runtime batch spool chunk is partial or invalid at time_step {expected_time_step}") from exc
        document = _mapping(decoded, "runtime batch spool chunk")
        if _canonical_json_bytes(document) != raw:
            raise ValueError(f"runtime batch spool chunk is not canonical at time_step {expected_time_step}")
        if document.get("schema_version") != _CONCURRENT_RUNTIME_BATCH_SPOOL_SCHEMA:
            raise ValueError("runtime batch spool chunk has an unsupported schema version")
        identity = _mapping(document.get("chunk_identity"), "runtime batch spool chunk identity")
        if identity.get("run_id") != self.run_id or identity.get("identity_hash") != self.identity_hash:
            raise ValueError(f"runtime batch spool chunk identity mismatch at time_step {expected_time_step}")
        if _integer(identity.get("time_step"), "spool chunk time_step") != expected_time_step:
            raise ValueError("runtime batch spool chunk time_step is crossed")
        if identity.get("batch_snapshot_hash") != expected_snapshot_hash:
            raise ValueError("runtime batch spool chunk snapshot identity is crossed")
        variants_raw = identity.get("terminal_variants")
        if not isinstance(variants_raw, Sequence) or isinstance(variants_raw, (str, bytes)):
            raise ValueError("runtime batch spool chunk terminal_variants must be a sequence")
        terminal_variants = tuple(str(item) for item in variants_raw)
        if terminal_variants != self.terminal_variants:
            raise ValueError("runtime batch spool chunk terminal contract mismatch")

        commit = _mapping(document.get("commit"), "runtime batch spool commit")
        if _integer(commit.get("time_step"), "spool commit time_step") != expected_time_step:
            raise ValueError("runtime batch spool commit time_step is crossed")
        rows = _mapping(document.get("rows"), "runtime batch spool rows")
        field_orders = _mapping(document.get("row_field_order"), "runtime batch spool row field order")
        if set(rows) != set(_ROW_KINDS) or set(field_orders) != set(_ROW_KINDS):
            raise ValueError("runtime batch spool row kinds are incomplete or extra")
        candidate_rows = _row_list(rows.get("candidate_rows"), "candidate rows", field_orders["candidate_rows"])
        result_rows = _row_list(rows.get("result_rows"), "result rows", field_orders["result_rows"])
        terminal_rows = _row_list(rows.get("terminal_rows"), "terminal rows", field_orders["terminal_rows"])
        variant_evidence_rows = _row_list(
            rows.get("variant_evidence_rows"),
            "variant evidence rows",
            field_orders["variant_evidence_rows"],
        )
        self._validate_row_order(
            time_step=expected_time_step,
            candidate_rows=candidate_rows,
            result_rows=result_rows,
            terminal_rows=terminal_rows,
            variant_evidence_rows=variant_evidence_rows,
        )
        return _ConcurrentRuntimeSpoolChunk(
            time_step=expected_time_step,
            batch_snapshot_hash=expected_snapshot_hash,
            terminal_variants=terminal_variants,
            commit=commit,
            candidate_rows=candidate_rows,
            result_rows=result_rows,
            terminal_rows=terminal_rows,
            variant_evidence_rows=variant_evidence_rows,
        )

    def _validate_row_order(
        self,
        *,
        time_step: int,
        candidate_rows: Sequence[Mapping[str, object]],
        result_rows: Sequence[Mapping[str, object]],
        terminal_rows: Sequence[Mapping[str, object]],
        variant_evidence_rows: Sequence[Mapping[str, object]],
    ) -> None:
        for row in (*candidate_rows, *result_rows, *terminal_rows):
            if _integer(row.get("time_step"), "spool row time_step") != time_step:
                raise ValueError(f"runtime batch spool contains a crossed row at time_step {time_step}")

        pair_ids = [str(row.get("pair_id", "")) for row in result_rows]
        if not all(pair_ids) or len(pair_ids) != len(set(pair_ids)):
            raise ValueError(f"runtime batch spool result identities are missing or duplicated at time_step {time_step}")
        positions = [_integer(row.get("pair_schedule_position"), "pair schedule position") for row in result_rows]
        if positions and positions != list(range(positions[0], positions[0] + len(positions))):
            raise ValueError(f"runtime batch spool result order is not canonical at time_step {time_step}")

        expected_terminal_keys = [
            (pair_id, variant)
            for pair_id in pair_ids
            for variant in self.terminal_variants
        ]
        terminal_keys = [
            (str(row.get("pair_id", "")), str(row.get("decision_variant", ""))) for row in terminal_rows
        ]
        evidence_keys = [
            (str(row.get("pair_id", "")), str(row.get("decision_variant", "")))
            for row in variant_evidence_rows
        ]
        if terminal_keys != expected_terminal_keys or evidence_keys != expected_terminal_keys:
            raise ValueError(f"runtime batch spool terminal order is not canonical at time_step {time_step}")

        candidate_keys = [
            (str(row.get("message_id", "")), str(row.get("user_id", ""))) for row in candidate_rows
        ]
        if not all(message_id and user_id for message_id, user_id in candidate_keys):
            raise ValueError(f"runtime batch spool candidate identity is missing at time_step {time_step}")
        if len(candidate_keys) != len(set(candidate_keys)):
            raise ValueError(f"runtime batch spool candidate identities are duplicated at time_step {time_step}")


def _chunk_name(time_step: int) -> str:
    if not 0 <= time_step <= 999_999:
        raise ValueError("runtime spool time_step exceeds the chunk naming contract")
    return f"batch-{time_step:06d}.json"


def _pending_name(time_step: int, digest: str) -> str:
    return f".batch-{time_step:06d}-{_sha256(digest, 'prepared chunk sha256')}.pending"


def _chunk_inventory(directory: Path) -> tuple[dict[int, Path], dict[int, Path]]:
    final_paths: dict[int, Path] = {}
    pending_paths: dict[int, Path] = {}
    for entry in directory.iterdir():
        final_match = _BATCH_CHUNK_NAME.fullmatch(entry.name)
        pending_match = _BATCH_PENDING_NAME.fullmatch(entry.name)
        if final_match is None and pending_match is None:
            raise ValueError(f"runtime batch spool contains an extra entry: {entry.name}")
        _require_regular_file(entry, f"runtime batch spool entry {entry.name}")
        match = final_match or pending_match
        assert match is not None
        time_step = int(match.group("time_step"))
        target = final_paths if final_match is not None else pending_paths
        if time_step in target:
            raise ValueError("runtime batch spool contains duplicate chunk identities")
        target[time_step] = entry
    return final_paths, pending_paths


def _exclusive_write(path: Path, content: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"runtime batch spool prepared chunk already exists: {path}")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)
    _fsync_directory(path.parent)


def _active_snapshot_time_step(replay: Mapping[str, object]) -> int | None:
    records = replay.get("records", [])
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise TypeError("runtime replay records must be a sequence")
    active_time_step: int | None = None
    for record_raw in records:
        record = _mapping(record_raw, "runtime replay record")
        if record.get("record_type") == "snapshot":
            identity = _mapping(record.get("snapshot_identity"), "runtime snapshot identity")
            active_time_step = _integer(identity.get("time_step"), "runtime snapshot time_step")
        elif record.get("record_type") == "event" and record.get("event_type") == "batch_committed":
            active_time_step = None
    return active_time_step


def _require_real_directory(path: Path, context: str) -> None:
    if path.is_symlink():
        raise ValueError(f"{context} must not be a symlink")
    try:
        mode = path.stat(follow_symlinks=False).st_mode
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"{context} does not exist: {path}") from exc
    if not stat.S_ISDIR(mode):
        raise ValueError(f"{context} must be a regular directory")


def _require_regular_file(path: Path, context: str) -> None:
    if path.is_symlink():
        raise ValueError(f"{context} must be a regular file, not a symlink")
    try:
        mode = path.stat(follow_symlinks=False).st_mode
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"{context} is missing: {path}") from exc
    if not stat.S_ISREG(mode):
        raise ValueError(f"{context} must be a regular file")


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_DIRECTORY)
    except (AttributeError, FileNotFoundError, NotADirectoryError, OSError):
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(safe_data(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _mapping(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{context} must be an object")
    return {str(key): item for key, item in value.items()}


def _row_field_order(rows: object, row_kind: str) -> list[str]:
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise TypeError(f"runtime batch spool {row_kind} must be a sequence")
    if not rows:
        return []
    field_order: list[str] = []
    seen_fields: set[str] = set()
    for row in rows:
        for field_name in _mapping(row, f"runtime batch spool {row_kind} row"):
            if field_name not in seen_fields:
                seen_fields.add(field_name)
                field_order.append(field_name)
    return field_order


def _row_list(value: object, context: str, field_order_raw: object) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"runtime batch spool {context} must be a sequence")
    if not isinstance(field_order_raw, Sequence) or isinstance(field_order_raw, (str, bytes)):
        raise TypeError(f"runtime batch spool {context} field order must be a sequence")
    field_order = [str(field_name) for field_name in field_order_raw]
    if len(field_order) != len(set(field_order)):
        raise ValueError(f"runtime batch spool {context} field order contains duplicates")
    rows = [_mapping(row, f"runtime batch spool {context} row") for row in value]
    if not rows and field_order:
        raise ValueError(f"runtime batch spool empty {context} must not declare fields")
    declared_fields = set(field_order)
    for row in rows:
        if not set(row).issubset(declared_fields):
            raise ValueError(f"runtime batch spool {context} row fields do not match their canonical order")
    return [
        {field_name: row[field_name] for field_name in field_order if field_name in row}
        for row in rows
    ]


def _string_list(value: object, context: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{context} must be a sequence")
    if not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{context} must contain non-empty strings")
    return list(value)


def _integer(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{context} must be an integer")
    return value


def _non_empty(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be a non-empty string")
    return value


def _sha256(value: object, context: str) -> str:
    token = _non_empty(value, context)
    if len(token) != 64 or any(character not in "0123456789abcdef" for character in token):
        raise ValueError(f"{context} must be a lowercase SHA-256 digest")
    return token
