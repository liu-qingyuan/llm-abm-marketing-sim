from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from itertools import zip_longest
from pathlib import Path, PurePosixPath
from typing import cast

from ._concurrent_runtime_spool import _ConcurrentRuntimeBatchSpool
from .concurrent_execution_journal import (
    CONCURRENT_MESSAGE_EXECUTION_JOURNAL_JSONL,
    CONCURRENT_MESSAGE_EXECUTION_RUN_IDENTITY_JSON,
    CONCURRENT_MESSAGE_EXECUTION_SNAPSHOTS_DIR,
    CONCURRENT_MESSAGE_EXECUTION_STATUS_JSON,
    ConcurrentExecutionJournal,
)
from .concurrent_message_experiment import (
    CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_DELIVERY_CAPACITY,
    CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_HORIZON,
    CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_SAMPLE_SIZE,
    authoritative_message_definitions,
)
from .durable_pair_settlement import (
    DURABLE_PAIR_SETTLEMENT_JOURNAL_FILE,
    DurablePairOutcomeKind,
    DurablePairSettlement,
    DurablePairTerminal,
    DurableSettlementReplay,
)
from .full_pool_source_v3 import (
    FULL_POOL_RESULT_CSV,
    FULL_POOL_RESULT_LINEAGE_MARKDOWN,
    FULL_POOL_RESULT_PROJECTION_SCHEMA,
    FullPoolResultProjection,
    _csv_bytes,
    _html_projection,
)
from .full_pool_strict_operator import (
    OperatorAttemptLedger,
    validate_strict_fresh_execution_manifest,
)
from .full_pool_strict_replay import (
    FULL_POOL_SOURCE_V4_SCHEMA,
    STRICT_PAIR_POLICY_FILE,
    STRICT_PAIR_POLICY_LEDGER_FILE,
    StrictPairPolicy,
    _final_succeeded_terminals_from_outcomes,
    _load_resolved_terminal,
    _reconciliation_settlement_root,
    _validate_dispatch_accounting,
    strict_formal_provider_contract,
)

_MESSAGE_CODES = {"message_1": "M1", "message_2": "M2", "message_3": "M3"}
_SEGMENT_CODES = {"class_1": "S1", "class_2": "S2", "class_3": "S3"}
_PRODUCTION_SEGMENT_DENOMINATORS = {"class_1": 15_616, "class_2": 15_070, "class_3": 5_714}
_STRICT_RESULT_FIELDS = (
    "Run",
    "Message",
    "Segment",
    "Total Likes",
    "Total Comments",
    "Total Shares",
    "Exposure",
)
_SOURCE_FIELDS = frozenset(
    {
        "schema_version",
        "source_identity",
        "replay_id",
        "profile",
        "production_topology",
        "counts",
        "provider_accounting",
        "physical_accounting",
        "operator_execution",
        "fresh_lineage",
        "runtime_lineage",
        "strict_policy",
        "settlement_v2",
        "row_hashes",
        "provider_contract_sha256",
        "source_hash",
        "production_deploy_eligible",
        "artifacts",
    }
)
_ROW_FILES = (
    "candidate_rows.jsonl",
    "pair_rows.jsonl",
    "terminal_rows.jsonl",
    "variant_evidence_rows.jsonl",
    "steps.jsonl",
)


@dataclass(frozen=True)
class StrictFullPoolSourceFacts:
    """Typed source-v4 facts rebuilt without caller-supplied Formal claims."""

    source_root: Path
    source_manifest_sha256: str
    source_identity: str
    source_hash: str
    replay_id: str
    profile: str
    runtime_workspace: Path
    execution_manifest_path: Path | None
    execution_manifest_sha256: str | None
    execution_manifest_identity_sha256: str | None
    implementation_commit: str | None
    attempt_ledger_path: Path | None
    attempt_ledger_identity_sha256: str | None
    terminal_attempt_count: int
    distinct_users: int
    logical_pairs: int
    committed_batches: int
    candidate_rows: int
    provider_failed_final_count: int
    provider_responses: int
    successful_decisions: int
    external_request_invocations: int
    observed_model_counts: Mapping[str, int]
    usage_complete_response_count: int
    usage_missing_response_count: int
    usage_malformed_response_count: int
    settled_actual_attempts: int
    dispatched_without_settlement_uncertainty: int
    charged_physical_attempts: int
    physical_cap: int
    original_dispatch_count: int
    reconciliation_dispatch_count: int
    maximum_dispatches_for_one_pair: int
    maximum_request_invocations_for_one_dispatch: int
    segment_denominators: Mapping[str, int]
    rejected_history: Mapping[str, object]
    artifact_hashes: Mapping[str, str]
    production_topology: bool
    production_deploy_eligible: bool


@dataclass(frozen=True)
class _StrictPresentationExecutionView:
    requested_model: str


@dataclass(frozen=True)
class _StrictPresentationContractView:
    schema_version: str
    message_ids: tuple[str, ...]
    horizon: int
    per_message_capacity: int
    expected_primary_terminals: int
    expected_final_batch_pairs_per_message: int
    formal_execution: _StrictPresentationExecutionView


@dataclass(frozen=True)
class _ClosedStrictFullPoolSource:
    """Closed source-v4 plus the read-only presentation Interface it can satisfy."""

    root: Path
    source_identity: str
    manifest_sha256: str
    manifest: Mapping[str, object]
    facts: StrictFullPoolSourceFacts
    membership: Mapping[str, str]
    runtime_replay: Mapping[str, object]
    runtime_run_id: str
    runtime_identity_hash: str
    contract: _StrictPresentationContractView
    aggregates: Mapping[str, object]
    diagnostics: Mapping[str, object]

    def read_batch(self, time_step: int) -> Mapping[str, object]:
        if time_step < 0 or time_step >= self.facts.committed_batches:
            raise IndexError("source-v4 batch index is outside the closed source")
        spool = _ConcurrentRuntimeBatchSpool(
            self.facts.runtime_workspace,
            run_id=self.runtime_run_id,
            identity_hash=self.runtime_identity_hash,
            terminal_variants=("primary",),
        )
        for chunk in spool.iter_committed(self.runtime_replay):
            if chunk.time_step == time_step:
                return {
                    "time_step": time_step,
                    "commit": dict(chunk.commit),
                    "rows": {
                        "candidate_rows": list(chunk.candidate_rows),
                        "pair_rows": list(chunk.result_rows),
                        "terminal_rows": list(chunk.terminal_rows),
                        "variant_evidence_rows": list(chunk.variant_evidence_rows),
                    },
                }
        raise ValueError("source-v4 committed spool is missing the requested batch")


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
        raise ValueError(f"persisted source-v4 artifact is missing or unsafe: {path}")
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
    return [_mapping(row, context) for row in value]


def _non_empty(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be a non-empty string")
    return value


def _non_negative_int(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{context} must be a non-negative integer")
    return value


def _jsonl(path: Path) -> Iterator[dict[str, object]]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"persisted source-v4 JSONL is missing or unsafe: {path.name}")
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                yield _mapping(json.loads(line), f"source-v4 {path.name} line {line_number}")
            except json.JSONDecodeError as exc:
                raise ValueError(f"source-v4 {path.name} is malformed") from exc


def _artifact_inventory(
    source: Path,
    manifest: Mapping[str, object],
) -> dict[str, dict[str, object]]:
    rows = _rows(manifest.get("artifacts"), "source-v4 artifact inventory")
    by_path: dict[str, dict[str, object]] = {}
    for row in rows:
        if set(row) != {"relative_path", "sha256", "bytes"}:
            raise ValueError("source-v4 artifact reference fields are not exact")
        relative_text = _non_empty(row.get("relative_path"), "source-v4 artifact path")
        relative = PurePosixPath(relative_text)
        target = source / Path(*relative.parts)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or relative_text == "manifest.json"
            or relative_text in by_path
            or target.is_symlink()
            or not target.is_file()
            or not target.resolve(strict=True).is_relative_to(source)
            or _sha256_file(target) != row.get("sha256")
            or target.stat().st_size != _non_negative_int(row.get("bytes"), "artifact bytes")
        ):
            raise ValueError("source-v4 artifact inventory is unsafe or crossed")
        by_path[relative_text] = row
    entries = tuple(source.rglob("*"))
    if any(path.is_symlink() or not (path.is_file() or path.is_dir()) for path in entries):
        raise ValueError("source-v4 contains an unsafe inventory entry")
    actual_files = {
        path.relative_to(source).as_posix() for path in entries if path.is_file()
    }
    if actual_files != set(by_path) | {"manifest.json"}:
        raise ValueError("source-v4 artifact inventory is missing or extra")
    if manifest.get("source_hash") != _json_sha256(rows):
        raise ValueError("source-v4 artifact list identity is crossed")
    return by_path


def _assert_bound_source_copy(
    source: Path,
    artifacts: Mapping[str, Mapping[str, object]],
    relative: str,
    origin: Path,
) -> None:
    artifact = artifacts.get(relative)
    if (
        artifact is None
        or origin.is_symlink()
        or not origin.is_file()
        or artifact.get("sha256") != _sha256_file(origin)
        or (source / relative).read_bytes() != origin.read_bytes()
    ):
        raise ValueError(f"source-v4 copied lineage differs from persisted origin: {relative}")


def _settlement_identity(path: Path) -> str:
    try:
        first = next(_jsonl(path))
    except StopIteration as exc:
        raise ValueError("source-v4 settlement journal is empty") from exc
    identity = _non_empty(first.get("settlement_identity_hash"), "settlement identity")
    if len(identity) != 64 or any(character not in "0123456789abcdef" for character in identity):
        raise ValueError("source-v4 settlement identity is malformed")
    return identity


def _settlement_replay(root: Path, *, max_concurrency: int) -> DurableSettlementReplay:
    journal = root / DURABLE_PAIR_SETTLEMENT_JOURNAL_FILE
    settlement = DurablePairSettlement(
        root,
        settlement_identity_hash=_settlement_identity(journal),
        maximum_attempts_per_dispatch=3,
        max_concurrency=max_concurrency,
    )
    replay = settlement.replay()
    if any(not wave.closed for wave in replay.waves):
        raise ValueError("complete source-v4 retains an inflight settlement wave")
    return replay


def _read_membership(
    path: Path,
    expected_users: set[str],
) -> dict[str, str]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("source-v4 latent membership is missing or unsafe")
    membership: dict[str, str] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["user_id", "latent_class"]:
            raise ValueError("source-v4 latent membership fields are not exact")
        for row in reader:
            user_id = row.get("user_id", "")
            latent_class = row.get("latent_class", "")
            if (
                not user_id
                or user_id in membership
                or latent_class not in _SEGMENT_CODES
            ):
                raise ValueError("source-v4 latent membership row is invalid")
            membership[user_id] = latent_class
    if set(membership) != expected_users:
        raise ValueError("source-v4 latent membership differs from terminal users")
    return membership


def _validate_operator_execution(
    *,
    source: Path,
    source_manifest_sha256: str,
    source_identity: str,
    runtime_workspace: Path,
    operator_execution: Mapping[str, object] | None,
    artifacts: Mapping[str, Mapping[str, object]],
) -> tuple[Path | None, str | None, str | None, Path | None, str | None, str | None, int]:
    if operator_execution is None:
        if "operator/execution-manifest.json" in artifacts:
            raise ValueError("direct source-v4 cannot carry unbound operator bytes")
        return None, None, None, None, None, None, 0
    expected_fields = {
        "execution_manifest_path",
        "execution_manifest_sha256",
        "execution_manifest_identity_sha256",
        "attempt_ledger_path",
        "attempt_ledger_identity_sha256",
    }
    if set(operator_execution) != expected_fields:
        raise ValueError("source-v4 operator execution fields are not exact")
    manifest_path = Path(
        _non_empty(operator_execution.get("execution_manifest_path"), "execution manifest path")
    )
    manifest_sha256 = _non_empty(
        operator_execution.get("execution_manifest_sha256"), "execution manifest hash"
    )
    manifest_identity = _non_empty(
        operator_execution.get("execution_manifest_identity_sha256"),
        "execution manifest identity",
    )
    ledger_path = Path(
        _non_empty(operator_execution.get("attempt_ledger_path"), "attempt ledger path")
    )
    ledger_identity = _non_empty(
        operator_execution.get("attempt_ledger_identity_sha256"), "attempt ledger identity"
    )
    copied = source / "operator" / "execution-manifest.json"
    if (
        "operator/execution-manifest.json" not in artifacts
        or _sha256_file(manifest_path) != manifest_sha256
        or _sha256_file(copied) != manifest_sha256
        or copied.read_bytes() != manifest_path.read_bytes()
    ):
        raise ValueError("source-v4 execution manifest copy or origin is crossed")
    facts = validate_strict_fresh_execution_manifest(
        manifest_path,
        require_current_implementation=False,
    )
    if (
        facts.manifest_sha256 != manifest_sha256
        or facts.manifest_identity_sha256 != manifest_identity
        or facts.replay_request.workspace != runtime_workspace
        or facts.attempt_ledger_path != ledger_path
        or facts.attempt_ledger_identity_sha256 != ledger_identity
    ):
        raise ValueError("source-v4 operator manifest facts are crossed")
    ledger = OperatorAttemptLedger(
        ledger_path,
        ledger_identity_sha256=ledger_identity,
        manifest_identity_sha256=manifest_identity,
        manifest_sha256=manifest_sha256,
        runtime_workspace=runtime_workspace,
    ).replay()
    if ledger.records and ledger.records[-1].get("event_type") == "source_v4_consumer_rejected":
        rejected_payload = _mapping(
            ledger.records[-1].get("payload"), "source-v4 consumer rejection payload"
        )
        if rejected_payload.get("source_manifest_sha256") == source_manifest_sha256:
            raise ValueError("latest operator attempt rejected the persisted source-v4 consumer")
    terminal_attempts = 0
    for record in ledger.records:
        if record.get("event_type") != "attempt_terminal":
            continue
        payload = _mapping(record.get("payload"), "terminal attempt payload")
        if (
            payload.get("status") == "complete"
            and payload.get("replay_identity_hash") == source_identity
            and payload.get("source_manifest_sha256") == source_manifest_sha256
        ):
            terminal_attempts += 1
    if terminal_attempts < 1:
        raise ValueError("source-v4 lacks a terminal operator attempt for this source")
    return (
        manifest_path,
        manifest_sha256,
        manifest_identity,
        ledger_path,
        ledger_identity,
        facts.implementation_commit,
        terminal_attempts,
    )


def read_closed_strict_full_pool_source(
    source_root: str | Path,
    *,
    manifest_sha256: str,
) -> _ClosedStrictFullPoolSource:
    """Rebuild source-v4 facts from persisted source and hash-bound workspace evidence."""
    candidate = Path(source_root).expanduser()
    if candidate.is_symlink():
        raise ValueError("source-v4 must be one explicit real directory")
    source = candidate.resolve(strict=True)
    if source != candidate.absolute() or not source.is_dir():
        raise ValueError("source-v4 must be one explicit real directory")
    manifest_path = source / "manifest.json"
    if _sha256_file(manifest_path) != manifest_sha256:
        raise ValueError("source-v4 manifest differs from its explicit hash")
    manifest = _mapping(json.loads(manifest_path.read_text(encoding="utf-8")), "source-v4 manifest")
    if set(manifest) != _SOURCE_FIELDS or manifest.get("schema_version") != FULL_POOL_SOURCE_V4_SCHEMA:
        raise ValueError("source-v4 manifest schema or fields are not exact")
    artifacts = _artifact_inventory(source, manifest)
    if any(name not in artifacts for name in (*_ROW_FILES, "latent-membership.csv", "fresh-request.json", "schema.json")):
        raise ValueError("source-v4 lacks required persisted rows or schema")
    schema = _mapping(json.loads((source / "schema.json").read_text(encoding="utf-8")), "source-v4 schema")
    if (
        schema.get("source_schema_version") != FULL_POOL_SOURCE_V4_SCHEMA
        or schema.get("terminal_variants") != ["primary"]
        or schema.get("provisional_outcomes_are_attempt_evidence_only") is not True
    ):
        raise ValueError("source-v4 schema document is crossed")
    request = _mapping(
        json.loads((source / "fresh-request.json").read_text(encoding="utf-8")),
        "source-v4 frozen request",
    )
    runtime_workspace = Path(
        _non_empty(request.get("workspace"), "source-v4 runtime workspace")
    )
    if source != runtime_workspace / "source-v4":
        raise ValueError("source-v4 root is crossed with its frozen runtime workspace")
    provider_contract = _mapping(request.get("provider_contract"), "source-v4 Provider contract")
    if (
        _canonical_json(provider_contract) != _canonical_json(strict_formal_provider_contract())
        or manifest.get("provider_contract_sha256") != _json_sha256(provider_contract)
    ):
        raise ValueError("source-v4 Provider/request contract is crossed")
    source_identity = _non_empty(manifest.get("source_identity"), "source-v4 identity")
    operator_raw = manifest.get("operator_execution")
    if operator_raw is not None and not isinstance(operator_raw, Mapping):
        raise ValueError("source-v4 operator execution must be an object or null")
    request_operator = request.get("operator_execution")
    if _canonical_json(request_operator) != _canonical_json(operator_raw):
        raise ValueError("source-v4 request and manifest operator execution are crossed")

    required_artifacts = {
        *_ROW_FILES,
        "latent-membership.csv",
        "fresh-request.json",
        "schema.json",
        "runtime/fresh-run-identity.json",
        "runtime/execution-journal.jsonl",
        "runtime/execution-status.json",
        "strict/strict-pair-policy.json",
        "strict/strict-pair-policy-ledger.jsonl",
        "settlement/original/durable-pair-settlement-v2.jsonl",
        "rejected-history/source-v3-manifest.json",
    }
    if operator_raw is not None:
        required_artifacts.add("operator/execution-manifest.json")
    if not required_artifacts.issubset(artifacts):
        raise ValueError("source-v4 persisted lineage artifacts are incomplete")
    for relative, origin in {
        "runtime/fresh-run-identity.json": runtime_workspace
        / CONCURRENT_MESSAGE_EXECUTION_RUN_IDENTITY_JSON,
        "runtime/execution-journal.jsonl": runtime_workspace
        / CONCURRENT_MESSAGE_EXECUTION_JOURNAL_JSONL,
        "runtime/execution-status.json": runtime_workspace
        / CONCURRENT_MESSAGE_EXECUTION_STATUS_JSON,
        "strict/strict-pair-policy.json": runtime_workspace / STRICT_PAIR_POLICY_FILE,
        "strict/strict-pair-policy-ledger.jsonl": runtime_workspace
        / STRICT_PAIR_POLICY_LEDGER_FILE,
        "settlement/original/durable-pair-settlement-v2.jsonl": runtime_workspace
        / "original-settlements"
        / DURABLE_PAIR_SETTLEMENT_JOURNAL_FILE,
    }.items():
        _assert_bound_source_copy(source, artifacts, relative, origin)
    snapshot_root = runtime_workspace / CONCURRENT_MESSAGE_EXECUTION_SNAPSHOTS_DIR
    if snapshot_root.is_symlink() or not snapshot_root.is_dir():
        raise ValueError("source-v4 runtime snapshots are missing or unsafe")
    expected_snapshot_paths: set[str] = set()
    for snapshot in sorted(snapshot_root.iterdir(), key=lambda item: item.name):
        if snapshot.is_symlink() or not snapshot.is_file():
            raise ValueError("source-v4 runtime snapshot inventory is unsafe")
        relative = f"runtime/snapshots/{snapshot.name}"
        expected_snapshot_paths.add(relative)
        _assert_bound_source_copy(source, artifacts, relative, snapshot)
    actual_snapshot_paths = {
        relative for relative in artifacts if relative.startswith("runtime/snapshots/")
    }
    if actual_snapshot_paths != expected_snapshot_paths:
        raise ValueError("source-v4 copied runtime snapshot inventory is crossed")

    if runtime_workspace.is_symlink() or not runtime_workspace.is_dir():
        raise ValueError("source-v4 runtime workspace is missing or unsafe")
    journal = ConcurrentExecutionJournal.open_existing(runtime_workspace)
    runtime_replay = journal._replay_runtime()
    runtime_identity = journal.identity
    runtime_execution = _mapping(
        runtime_identity.get("execution_contract"), "source-v4 runtime execution contract"
    )
    runtime_configuration = _mapping(
        runtime_identity.get("configuration"), "source-v4 runtime configuration"
    )
    runtime_providers = _mapping(
        runtime_identity.get("provider_contract"), "source-v4 runtime Provider contracts"
    )
    authoritative_messages = [
        message.model_dump(mode="json") for message in authoritative_message_definitions()
    ]
    if (
        journal.identity_hash != source_identity
        or manifest.get("replay_id") != request.get("replay_id")
        or manifest.get("profile") != runtime_configuration.get("configuration_profile")
        or _canonical_json(runtime_identity.get("messages"))
        != _canonical_json(authoritative_messages)
        or _canonical_json(runtime_providers.get("primary"))
        != _canonical_json(provider_contract)
        or runtime_execution.get("replay_id") != request.get("replay_id")
        or runtime_execution.get("logical_cap") != request.get("logical_cap")
        or runtime_execution.get("physical_cap") != request.get("physical_cap")
        or runtime_execution.get("maximum_attempts_per_dispatch")
        != request.get("maximum_attempts_per_dispatch")
        or runtime_execution.get("max_concurrency") != request.get("max_concurrency")
        or runtime_execution.get("seed_top_k_per_proxy")
        != request.get("seed_top_k_per_proxy")
        or runtime_execution.get("fresh_no_cache") is not True
        or runtime_execution.get("maximum_reconciliations_per_pair") != 1
        or _canonical_json(runtime_execution.get("rejected_history"))
        != _canonical_json(request.get("rejected_history"))
        or _canonical_json(runtime_execution.get("operator_execution"))
        != _canonical_json(operator_raw)
        or runtime_execution.get("fresh_initial_positions")
        != {"batch": 0, "logical": 0, "physical": 0, "pair_schedule": 0}
    ):
        raise ValueError("source-v4 runtime identity, messages, or frozen request is crossed")
    spool = _ConcurrentRuntimeBatchSpool(
        runtime_workspace,
        run_id=journal.run_id,
        identity_hash=journal.identity_hash,
        terminal_variants=("primary",),
    )
    row_hashers = {name: hashlib.sha256() for name in _ROW_FILES}
    spool_counts: Counter[str] = Counter()
    for expected_step, chunk in enumerate(spool.iter_committed(runtime_replay)):
        if chunk.time_step != expected_step:
            raise ValueError("source-v4 committed spool batches are reordered")
        spool_counts["committed_batches"] += 1
        rows_by_file = {
            "candidate_rows.jsonl": chunk.candidate_rows,
            "pair_rows.jsonl": chunk.result_rows,
            "terminal_rows.jsonl": chunk.terminal_rows,
            "variant_evidence_rows.jsonl": chunk.variant_evidence_rows,
            "steps.jsonl": [chunk.commit],
        }
        for name, rows in rows_by_file.items():
            spool_counts[name] += len(rows)
            for row in rows:
                row_hashers[name].update((_canonical_json(row) + "\n").encode("utf-8"))
    runtime_lineage = _mapping(manifest.get("runtime_lineage"), "source-v4 runtime lineage")
    spool_root = runtime_workspace / "concurrent_runtime_batch_spool"
    if spool_root.is_symlink() or not spool_root.is_dir():
        raise ValueError("source-v4 runtime batch spool is missing or unsafe")
    spool_entries = tuple(sorted(spool_root.iterdir(), key=lambda item: item.name))
    actual_spool_refs = [
        {
            "workspace_relative_path": path.relative_to(runtime_workspace).as_posix(),
            "sha256": _sha256_file(path),
            "bytes": path.stat().st_size,
        }
        for path in spool_entries
        if path.is_file() and not path.is_symlink()
    ]
    if (
        len(actual_spool_refs) != len(spool_entries)
        or runtime_lineage
        != {
            "run_identity_sha256": artifacts["runtime/fresh-run-identity.json"]["sha256"],
            "execution_journal_sha256": artifacts["runtime/execution-journal.jsonl"]["sha256"],
            "execution_status_sha256": artifacts["runtime/execution-status.json"]["sha256"],
            "batch_snapshots": [
                {
                    "relative_path": relative,
                    "sha256": artifacts[relative]["sha256"],
                }
                for relative in sorted(expected_snapshot_paths)
            ],
            "batch_spool": actual_spool_refs,
        }
    ):
        raise ValueError("source-v4 runtime lineage or batch spool inventory is crossed")

    row_hashes = _mapping(manifest.get("row_hashes"), "source-v4 row hashes")
    if set(row_hashes) != set(_ROW_FILES):
        raise ValueError("source-v4 row hash fields are not exact")
    for name, hasher in row_hashers.items():
        if (
            row_hashes.get(name) != hasher.hexdigest()
            or artifacts[name].get("sha256") != hasher.hexdigest()
        ):
            raise ValueError("source-v4 rows differ from the committed runtime spool")

    pair_ids: set[str] = set()
    users: set[str] = set()
    user_message_pairs: set[tuple[str, str]] = set()
    observed_models: Counter[str] = Counter()
    request_invocations = 0
    provider_responses = 0
    successful_decisions = 0
    usage_complete = 0
    usage_missing = 0
    usage_malformed = 0
    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    cached_input_tokens = 0
    cached_reported = 0
    provider_failed_final = 0
    sentinel = object()
    for pair_row, terminal, evidence in zip_longest(
        _jsonl(source / "pair_rows.jsonl"),
        _jsonl(source / "terminal_rows.jsonl"),
        _jsonl(source / "variant_evidence_rows.jsonl"),
        fillvalue=sentinel,
    ):
        if pair_row is sentinel or terminal is sentinel or evidence is sentinel:
            raise ValueError("source-v4 pair, terminal, and evidence row counts differ")
        pair = cast(dict[str, object], pair_row)
        terminal_row = cast(dict[str, object], terminal)
        evidence_row = cast(dict[str, object], evidence)
        pair_id = _non_empty(terminal_row.get("pair_id"), "source-v4 terminal pair id")
        user_id = _non_empty(terminal_row.get("user_id"), "source-v4 terminal user id")
        message_id = _non_empty(terminal_row.get("message_id"), "source-v4 message id")
        if (
            pair_id in pair_ids
            or message_id not in _MESSAGE_CODES
            or (user_id, message_id) in user_message_pairs
            or pair.get("pair_id") != pair_id
            or evidence_row.get("pair_id") != pair_id
            or pair.get("primary_status") != "succeeded"
            or terminal_row.get("terminal_status") != "succeeded"
            or terminal_row.get("provider_status") != "succeeded"
            or terminal_row.get("action") not in {"ignore", "like", "comment", "share"}
        ):
            raise ValueError("source-v4 final terminal mapping is mixed or crossed")
        pair_ids.add(pair_id)
        users.add(user_id)
        user_message_pairs.add((user_id, message_id))
        invocations = _non_negative_int(
            evidence_row.get("request_invocations"), "source-v4 request invocations"
        )
        responses = _non_negative_int(
            evidence_row.get("provider_response_count"), "source-v4 response count"
        )
        successes = _non_negative_int(
            evidence_row.get("successful_decision_count"), "source-v4 success count"
        )
        models = _mapping(evidence_row.get("observed_model_counts"), "source-v4 models")
        complete = _non_negative_int(
            evidence_row.get("usage_complete_response_count"), "source-v4 complete usage"
        )
        missing = _non_negative_int(
            evidence_row.get("usage_missing_response_count"), "source-v4 missing usage"
        )
        malformed = _non_negative_int(
            evidence_row.get("usage_malformed_response_count"), "source-v4 malformed usage"
        )
        if (
            not 1 <= invocations <= 3
            or responses != 1
            or successes != 1
            or models != {"gpt-5.6-sol": 1}
            or evidence_row.get("observed_model_missing_response_count") != 0
            or evidence_row.get("observed_model_malformed_response_count") != 0
            or complete != 1
            or missing != 0
            or malformed != 0
        ):
            raise ValueError("source-v4 logical pair lacks one exact final response/model/usage")
        input_value = _non_negative_int(evidence_row.get("input_usage"), "source-v4 input usage")
        output_value = _non_negative_int(evidence_row.get("output_usage"), "source-v4 output usage")
        total_value = _non_negative_int(evidence_row.get("total_usage"), "source-v4 total usage")
        if total_value != input_value + output_value:
            raise ValueError("source-v4 final token usage is crossed")
        cached_value = evidence_row.get("cached_input_usage")
        if cached_value is not None:
            cached_input_tokens += _non_negative_int(cached_value, "source-v4 cached usage")
            cached_reported += responses
        request_invocations += invocations
        provider_responses += responses
        successful_decisions += successes
        observed_models.update({str(key): _non_negative_int(value, "source-v4 model count") for key, value in models.items()})
        usage_complete += complete
        usage_missing += missing
        usage_malformed += malformed
        input_tokens += input_value
        output_tokens += output_value
        total_tokens += total_value
        provider_failed_final += terminal_row.get("terminal_status") == "provider_failed"

    membership = _read_membership(source / "latent-membership.csv", users)
    denominators = dict(Counter(membership.values()))
    production_topology = (
        len(users) == CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_SAMPLE_SIZE
        and len(pair_ids) == 109_200
        and spool_counts["committed_batches"]
        == CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_HORIZON
        and runtime_configuration.get("sample_size")
        == CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_SAMPLE_SIZE
        and runtime_configuration.get("horizon")
        == CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_HORIZON
        and runtime_configuration.get("delivery_capacity")
        == CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_DELIVERY_CAPACITY
        and request.get("logical_cap") == 109_200
        and request.get("physical_cap") == 120_120
        and request.get("max_concurrency") == 10
    )
    if manifest.get("production_topology") is not production_topology:
        raise ValueError("source-v4 production topology flag is crossed")
    if production_topology and denominators != _PRODUCTION_SEGMENT_DENOMINATORS:
        raise ValueError("source-v4 production segment denominators are crossed")
    if len(user_message_pairs) != len(users) * len(_MESSAGE_CODES):
        raise ValueError("source-v4 user-message denominator is incomplete")

    original_root = runtime_workspace / "original-settlements"
    original = _settlement_replay(original_root, max_concurrency=10)
    original_outcomes = {
        outcome.pair_id: outcome for wave in original.waves for outcome in wave.outcomes
    }
    if set(original_outcomes) != pair_ids:
        raise ValueError("source-v4 original settlement denominator differs from final pairs")
    for outcome in original_outcomes.values():
        _validate_dispatch_accounting(outcome, 3)
    policy = StrictPairPolicy(
        runtime_workspace,
        identity_hash=source_identity,
        physical_cap=_non_negative_int(request.get("physical_cap"), "source-v4 physical cap"),
        maximum_attempts_per_dispatch=3,
    )
    policy_replay = policy.replay()
    strict_manifest = _mapping(manifest.get("strict_policy"), "source-v4 strict policy")
    if (
        policy_replay.terminal_event_type != "runtime_completed"
        or strict_manifest
        != {
            "policy_identity_hash": source_identity,
            "policy_sha256": artifacts["strict/strict-pair-policy.json"]["sha256"],
            "policy_ledger_sha256": artifacts[
                "strict/strict-pair-policy-ledger.jsonl"
            ]["sha256"],
            "reconciliation_dispatch_count": len(policy_replay.dispatches),
        }
    ):
        raise ValueError("source-v4 strict policy is stopped, incomplete, or crossed")
    reconciliation_external = 0
    reconciliation_actual = 0
    maximum_dispatch_invocations = max(
        (outcome.accounting.request_invocations_delta for outcome in original_outcomes.values()),
        default=0,
    )
    for pair_id, dispatch in policy_replay.dispatches.items():
        resolution = policy_replay.resolutions.get(pair_id)
        if resolution is None:
            raise ValueError("source-v4 has an unresolved reconciliation dispatch")
        copied_relative = (
            Path("settlement/reconciliations")
            / dispatch.reconciliation_identity_hash
            / "durable-pair-settlement-v2.jsonl"
        ).as_posix()
        copied_artifact = artifacts.get(copied_relative)
        if (
            copied_artifact is None
            or copied_artifact.get("sha256") != resolution.journal_sha256
        ):
            raise ValueError("source-v4 reconciliation copy is missing or crossed")
        root = _reconciliation_settlement_root(
            runtime_workspace,
            PurePosixPath(dispatch.journal_relative_path),
            create_parent=False,
        )
        _assert_bound_source_copy(
            source,
            artifacts,
            copied_relative,
            root / DURABLE_PAIR_SETTLEMENT_JOURNAL_FILE,
        )
        replay = _settlement_replay(root, max_concurrency=1)
        outcomes = [outcome for wave in replay.waves for outcome in wave.outcomes]
        if len(outcomes) != 1 or outcomes[0].pair_id != pair_id:
            raise ValueError("source-v4 reconciliation journal is crossed")
        outcome = outcomes[0]
        _validate_dispatch_accounting(outcome, 3)
        if outcome.kind is not DurablePairOutcomeKind.TERMINAL:
            raise ValueError("source-v4 reconciliation did not settle to a terminal")
        _load_resolved_terminal(policy, dispatch, resolution)
        reconciliation_external += outcome.accounting.external_request_invocations_delta
        reconciliation_actual += outcome.accounting.actual_physical_attempts
        maximum_dispatch_invocations = max(
            maximum_dispatch_invocations,
            outcome.accounting.request_invocations_delta,
        )
    final_terminals = _final_succeeded_terminals_from_outcomes(
        policy=policy,
        outcomes=original_outcomes,
    )
    if set(final_terminals) != pair_ids:
        raise ValueError("source-v4 final settlement terminals differ from source rows")
    original_external = sum(
        outcome.accounting.external_request_invocations_delta
        for outcome in original_outcomes.values()
    )
    external_invocations = original_external + reconciliation_external
    actual_attempts = original.actual_physical_attempts + reconciliation_actual
    uncertain_attempts = original.uncertain_physical_attempts
    charged_attempts = actual_attempts + uncertain_attempts
    physical = _mapping(manifest.get("physical_accounting"), "source-v4 physical accounting")
    if physical != {
        "settled_actual_attempts": actual_attempts,
        "dispatched_without_settlement_uncertainty": uncertain_attempts,
        "charged_physical_attempts": charged_attempts,
        "active_reservations": 0,
        "physical_cap": request.get("physical_cap"),
    }:
        raise ValueError("source-v4 physical accounting differs from settlement replay")
    provider = {
        "schema_version": "provider-accounting-v1",
        "external_request_invocations": external_invocations,
        "provider_response_count": provider_responses,
        "successful_decision_count": successful_decisions,
        "observed_model_counts": dict(sorted(observed_models.items())),
        "observed_model_missing_response_count": 0,
        "observed_model_malformed_response_count": 0,
        "usage_complete_response_count": usage_complete,
        "usage_missing_response_count": usage_missing,
        "usage_malformed_response_count": usage_malformed,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cached_input_tokens": cached_input_tokens if cached_reported else None,
        "cached_input_tokens_reported_response_count": cached_reported,
    }
    if manifest.get("provider_accounting") != provider:
        raise ValueError("source-v4 Provider accounting differs from final evidence")
    counts = _mapping(manifest.get("counts"), "source-v4 counts")
    expected_counts = {
        "candidate_rows": spool_counts["candidate_rows.jsonl"],
        "committed_batches": spool_counts["committed_batches"],
        "distinct_users": len(users),
        "pair_rows": len(pair_ids),
        "terminal_rows": len(pair_ids),
        "variant_evidence_rows": len(pair_ids),
    }
    if counts != expected_counts:
        raise ValueError("source-v4 manifest counts differ from persisted rows")
    settlement_manifest = _mapping(manifest.get("settlement_v2"), "source-v4 settlement")
    expected_reconciliations = []
    for pair_id, dispatch in sorted(policy_replay.dispatches.items()):
        resolution = policy_replay.resolutions[pair_id]
        expected_reconciliations.append(
            {
                "pair_id": pair_id,
                "source_kind": dispatch.source_kind,
                "reconciliation_identity_hash": dispatch.reconciliation_identity_hash,
                "relative_path": (
                    Path("settlement/reconciliations")
                    / dispatch.reconciliation_identity_hash
                    / "durable-pair-settlement-v2.jsonl"
                ).as_posix(),
                "journal_sha256": resolution.journal_sha256,
                "terminal_sha256": resolution.terminal_sha256,
                "actual_physical_attempts": resolution.actual_physical_attempts,
                "uncertain_physical_attempts": resolution.uncertain_physical_attempts,
                "physical_attempt_charge": resolution.physical_attempt_charge,
            }
        )
    expected_settlement = {
        "schema_version": "full-pool-durable-pair-settlement-v2",
        "original_journal_sha256": artifacts[
            "settlement/original/durable-pair-settlement-v2.jsonl"
        ]["sha256"],
        "wave_count": len(original.waves),
        "original_dispatched_pair_count": len(pair_ids),
        "original_terminal_pair_count": sum(
            outcome.kind is DurablePairOutcomeKind.TERMINAL
            for outcome in original_outcomes.values()
        ),
        "provisional_provider_failed_count": sum(
            outcome.kind is DurablePairOutcomeKind.TERMINAL
            and cast(DurablePairTerminal, outcome.terminal).terminal_row.get("terminal_status")
            == "provider_failed"
            for outcome in original_outcomes.values()
        ),
        "provisional_unknown_pair_count": len(original.unknown_pair_ids),
        "implementation_failed_pair_count": len(original.implementation_failed_pair_ids),
        "final_succeeded_terminal_count": len(pair_ids),
        "reconciliation_journals": expected_reconciliations,
    }
    if (
        settlement_manifest != expected_settlement
        or provider_failed_final != 0
        or request_invocations < len(pair_ids)
        or successful_decisions != len(pair_ids)
        or provider_responses != len(pair_ids)
        or observed_models != {"gpt-5.6-sol": len(pair_ids)}
        or usage_complete != len(pair_ids)
        or usage_missing != 0
        or usage_malformed != 0
        or charged_attempts > _non_negative_int(request.get("physical_cap"), "physical cap")
    ):
        raise ValueError("source-v4 final Formal denominator is incomplete or mixed")

    operator_mapping = cast(Mapping[str, object] | None, operator_raw)
    (
        execution_manifest_path,
        execution_manifest_sha256,
        execution_manifest_identity,
        attempt_ledger_path,
        attempt_ledger_identity,
        implementation_commit,
        terminal_attempt_count,
    ) = _validate_operator_execution(
        source=source,
        source_manifest_sha256=manifest_sha256,
        source_identity=source_identity,
        runtime_workspace=runtime_workspace,
        operator_execution=operator_mapping,
        artifacts=artifacts,
    )
    manifest_eligible = manifest.get("production_deploy_eligible") is True
    production_eligible = (
        manifest_eligible
        and production_topology
        and terminal_attempt_count >= 1
        and external_invocations >= len(pair_ids)
        and uncertain_attempts == 0
    )
    if manifest_eligible != production_eligible:
        raise ValueError("source-v4 production deploy eligibility is not independently closed")
    fresh_lineage = _mapping(manifest.get("fresh_lineage"), "source-v4 fresh lineage")
    rejected_history = _mapping(
        fresh_lineage.get("rejected_history"), "source-v4 rejected history"
    )
    request_rejected = _mapping(request.get("rejected_history"), "frozen rejected history")
    rejected_origin = Path(
        _non_empty(request_rejected.get("source_root"), "rejected source root")
    ) / "manifest.json"
    if (
        rejected_history != request_rejected
        or request_rejected.get("rejection_reason")
        != "validation_mixed_provider_evidence"
        or request_rejected.get("manifest_sha256") != _sha256_file(rejected_origin)
    ):
        raise ValueError("source-v4 rejected mixed lineage is crossed")
    _assert_bound_source_copy(
        source,
        artifacts,
        "rejected-history/source-v3-manifest.json",
        rejected_origin,
    )
    artifact_hashes = {
        relative: _non_empty(row.get("sha256"), "source-v4 artifact hash")
        for relative, row in artifacts.items()
    }
    facts = StrictFullPoolSourceFacts(
        source_root=source,
        source_manifest_sha256=manifest_sha256,
        source_identity=source_identity,
        source_hash=_non_empty(manifest.get("source_hash"), "source-v4 source hash"),
        replay_id=_non_empty(manifest.get("replay_id"), "source-v4 replay id"),
        profile=_non_empty(manifest.get("profile"), "source-v4 profile"),
        runtime_workspace=runtime_workspace,
        execution_manifest_path=execution_manifest_path,
        execution_manifest_sha256=execution_manifest_sha256,
        execution_manifest_identity_sha256=execution_manifest_identity,
        implementation_commit=implementation_commit,
        attempt_ledger_path=attempt_ledger_path,
        attempt_ledger_identity_sha256=attempt_ledger_identity,
        terminal_attempt_count=terminal_attempt_count,
        distinct_users=len(users),
        logical_pairs=len(pair_ids),
        committed_batches=spool_counts["committed_batches"],
        candidate_rows=spool_counts["candidate_rows.jsonl"],
        provider_failed_final_count=provider_failed_final,
        provider_responses=provider_responses,
        successful_decisions=successful_decisions,
        external_request_invocations=external_invocations,
        observed_model_counts=dict(sorted(observed_models.items())),
        usage_complete_response_count=usage_complete,
        usage_missing_response_count=usage_missing,
        usage_malformed_response_count=usage_malformed,
        settled_actual_attempts=actual_attempts,
        dispatched_without_settlement_uncertainty=uncertain_attempts,
        charged_physical_attempts=charged_attempts,
        physical_cap=_non_negative_int(request.get("physical_cap"), "physical cap"),
        original_dispatch_count=len(original_outcomes),
        reconciliation_dispatch_count=len(policy_replay.dispatches),
        maximum_dispatches_for_one_pair=2 if policy_replay.dispatches else 1,
        maximum_request_invocations_for_one_dispatch=maximum_dispatch_invocations,
        segment_denominators=denominators,
        rejected_history=rejected_history,
        artifact_hashes=artifact_hashes,
        production_topology=production_topology,
        production_deploy_eligible=production_eligible,
    )
    sample_size = _non_negative_int(
        runtime_configuration.get("sample_size"), "source-v4 sample size"
    )
    horizon = _non_negative_int(
        runtime_configuration.get("horizon"), "source-v4 horizon"
    )
    delivery_capacity = _non_negative_int(
        runtime_configuration.get("delivery_capacity"),
        "source-v4 delivery capacity",
    )
    final_capacity = sample_size - delivery_capacity * max(horizon - 1, 0)
    if horizon < 1 or delivery_capacity < 1 or final_capacity < 1:
        raise ValueError("source-v4 presentation schedule is invalid")
    presentation_counts = {
        "candidate_ranking_rows": facts.candidate_rows,
        "committed_batches": facts.committed_batches,
        "distinct_users": facts.distinct_users,
        "eligible_pairs": facts.logical_pairs,
        "exposures": facts.logical_pairs,
        "primary_terminals": facts.logical_pairs,
        "provider_failed_terminals": facts.provider_failed_final_count,
        "below_delivery_capacity_pairs": 0,
    }
    presentation_accounting = {
        "logical_judgments": facts.logical_pairs,
        "physical_attempts": facts.charged_physical_attempts,
        "provider_responses": facts.provider_responses,
        "successful_decisions": facts.successful_decisions,
        "external_request_invocations": facts.external_request_invocations,
        "observed_model_counts": dict(facts.observed_model_counts),
        "usage_complete_response_count": facts.usage_complete_response_count,
        "subscription_billed_cost_usd": 0.0,
    }
    return _ClosedStrictFullPoolSource(
        root=source,
        source_identity=source_identity,
        manifest_sha256=manifest_sha256,
        manifest=manifest,
        facts=facts,
        membership=membership,
        runtime_replay=runtime_replay,
        runtime_run_id=journal.run_id,
        runtime_identity_hash=journal.identity_hash,
        contract=_StrictPresentationContractView(
            schema_version="full-pool-strict-presentation-contract-v1",
            message_ids=tuple(_MESSAGE_CODES),
            horizon=horizon,
            per_message_capacity=delivery_capacity,
            expected_primary_terminals=facts.logical_pairs,
            expected_final_batch_pairs_per_message=final_capacity,
            formal_execution=_StrictPresentationExecutionView(
                requested_model="gpt-5.6-sol"
            ),
        ),
        aggregates={
            "counts": presentation_counts,
            "provider_accounting": presentation_accounting,
            "evidence_profile": (
                "formal_live" if facts.production_deploy_eligible else "validation"
            ),
            "production_deploy_eligible": facts.production_deploy_eligible,
        },
        diagnostics={
            "schedule": {
                "per_message_capacity": delivery_capacity,
                "final_batch_pairs_per_message": final_capacity,
            }
        },
    )


def _strict_projection_html(rows: Sequence[Mapping[str, int | str]]) -> str:
    fragment = _html_projection(rows)
    for index, field in enumerate(_STRICT_RESULT_FIELDS):
        fragment = fragment.replace(
            f"<th>{field}</th>",
            f'<th><button type="button" class="full-pool-segment-sort" '
            f'data-sort-column="{index}" aria-label="Sort by {field}">{field}</button></th>',
        )
    fragment = fragment.replace(
        "<p>Rows are ordered Segment → Message → Run. Exposure includes ignore; interaction columns count only succeeded terminal actions.</p>",
        "<p>Rows are ordered Segment → Message → Run. Exposure includes ignore; interaction columns count only succeeded terminal actions.</p>"
        '<aside data-testid="strict-trajectory-disclosure">The strict fresh trajectory is the only source of these results. '
        "The mixed source-v3 trajectory is not combined because it contains three historical Provider failures. "
        "Historical 1,000-user sensitivity evidence remains descriptive; population and model both change, so single-factor or causal attribution is prohibited.</aside>",
    )
    return fragment + """
<script>
(() => {
  const table = document.querySelector('[data-testid="full-pool-segment-table"]');
  if (!table) return;
  const body = table.querySelector('tbody');
  const buttons = [...table.querySelectorAll('[data-sort-column]')];
  let activeColumn = -1;
  let direction = 1;
  const value = (row, column) => {
    const text = row.cells[column]?.textContent?.trim() ?? '';
    const numeric = Number(text.replaceAll(',', ''));
    return Number.isFinite(numeric) && text !== '' ? numeric : text;
  };
  for (const button of buttons) {
    button.addEventListener('click', () => {
      const column = Number(button.dataset.sortColumn);
      direction = activeColumn === column ? -direction : 1;
      activeColumn = column;
      for (const candidate of buttons) candidate.removeAttribute('aria-sort');
      button.setAttribute('aria-sort', direction === 1 ? 'ascending' : 'descending');
      const rows = [...body.rows];
      rows.sort((left, right) => {
        const a = value(left, column);
        const b = value(right, column);
        return (typeof a === 'number' && typeof b === 'number'
          ? a - b
          : String(a).localeCompare(String(b))) * direction;
      });
      body.replaceChildren(...rows);
    });
  }
})();
</script>
"""


def compose_strict_full_pool_result_projection(
    source: _ClosedStrictFullPoolSource,
) -> FullPoolResultProjection:
    """Project one validated source-v4 into same-source HTML, UTF-8 CSV, and lineage."""
    counters: dict[tuple[str, str], Counter[str]] = {
        (latent_class, message_id): Counter()
        for latent_class in _SEGMENT_CODES
        for message_id in _MESSAGE_CODES
    }
    for terminal in _jsonl(source.root / "terminal_rows.jsonl"):
        user_id = _non_empty(terminal.get("user_id"), "projection user id")
        message_id = _non_empty(terminal.get("message_id"), "projection message id")
        if user_id not in source.membership or message_id not in _MESSAGE_CODES:
            raise ValueError("source-v4 projection membership or message is crossed")
        counter = counters[(source.membership[user_id], message_id)]
        counter["exposure"] += 1
        if terminal.get("terminal_status") == "succeeded":
            action = terminal.get("action")
            if action in {"like", "comment", "share"}:
                counter[str(action)] += 1
    rows: list[dict[str, int | str]] = []
    for latent_class, segment_code in _SEGMENT_CODES.items():
        for message_id, message_code in _MESSAGE_CODES.items():
            counter = counters[(latent_class, message_id)]
            rows.append(
                {
                    "Run": 1,
                    "Message": message_code,
                    "Segment": segment_code,
                    "Total Likes": counter["like"],
                    "Total Comments": counter["comment"],
                    "Total Shares": counter["share"],
                    "Exposure": counter["exposure"],
                }
            )
    for latent_class, segment_code in _SEGMENT_CODES.items():
        expected = source.facts.segment_denominators[latent_class]
        if any(
            row["Exposure"] != expected
            for row in rows
            if row["Segment"] == segment_code
        ):
            raise ValueError("source-v4 projection segment denominator is incomplete")
    total_exposure = sum(cast(int, row["Exposure"]) for row in rows)
    if total_exposure != source.facts.logical_pairs:
        raise ValueError("source-v4 projection total exposure is crossed")
    rows_document = [dict(row) for row in rows]
    rows_sha256 = _json_sha256(rows_document)
    csv_bytes = _csv_bytes(rows)
    csv_sha256 = hashlib.sha256(csv_bytes).hexdigest()
    rejected_hash = _non_empty(
        source.facts.rejected_history.get("manifest_sha256"), "rejected source hash"
    )
    lineage = "\n".join(
        (
            "# Full-Pool strict source-v4 segment result lineage and data dictionary",
            "",
            f"- schema: `{FULL_POOL_RESULT_PROJECTION_SCHEMA}`",
            f"- source-v4 manifest SHA-256: `{source.manifest_sha256}`",
            f"- source-v4 identity: `{source.source_identity}`",
            f"- rows SHA-256: `{rows_sha256}`",
            f"- CSV SHA-256: `{csv_sha256}`",
            f"- execution manifest SHA-256: `{source.facts.execution_manifest_sha256 or 'direct-validation'}`",
            f"- operator attempt ledger identity SHA-256: `{source.facts.attempt_ledger_identity_sha256 or 'direct-validation'}`",
            f"- rejected mixed source-v3 manifest SHA-256: `{rejected_hash}`",
            "- 旧 mixed trajectory 未参与结果；它只作为 hash-bound rejection lineage 保留。",
            "- 旧 source-v3 因三个 historical Provider failures 被拒绝；strict fresh trajectory 从 Batch 0 独立重建。",
            "- Historical 1,000-user sensitivity evidence is retained, but population and model both change; this does not support single-factor or causal attribution.",
            "",
            "## Data dictionary",
            "",
            "| Column | Meaning |",
            "|---|---|",
            "| Run | Frozen experiment run identifier; this delivery uses `1`. |",
            "| Message | `M1` / `M2` / `M3`, mapped from the three persisted messages. |",
            "| Segment | `S1` / `S2` / `S3`, joined by `user_id` from frozen latent membership. |",
            "| Total Likes | Count of final `succeeded` actions equal to `like`. |",
            "| Total Comments | Count of final `succeeded` actions equal to `comment`. |",
            "| Total Shares | Count of final `succeeded` actions equal to `share`. |",
            "| Exposure | Every final successful Decision, including `ignore`. |",
            "",
        )
    ).encode("utf-8")
    return FullPoolResultProjection(
        schema_version=FULL_POOL_RESULT_PROJECTION_SCHEMA,
        rows=tuple(rows_document),
        rows_sha256=rows_sha256,
        csv_filename=FULL_POOL_RESULT_CSV,
        csv_bytes=csv_bytes,
        csv_sha256=csv_sha256,
        lineage_filename=FULL_POOL_RESULT_LINEAGE_MARKDOWN,
        lineage_bytes=lineage,
        lineage_sha256=hashlib.sha256(lineage).hexdigest(),
        html_fragment=_strict_projection_html(rows),
        segment_denominators=dict(source.facts.segment_denominators),
        total_exposure=total_exposure,
    )
