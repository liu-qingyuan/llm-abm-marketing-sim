from __future__ import annotations

import hashlib
import json
import math
import os
import random
import shutil
import stat
import tempfile
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from .concurrent_message_experiment import _prepare_concurrent_runtime_inputs
from .concurrent_message_report import close_concurrent_message_artifacts
from .concurrent_robustness_study import (
    _assert_source_unchanged,
    _dynamic_runtime_config,
    _ordered_user_ids_sha256,
    _resolve_source_path,
    _validate_source_against_manifest,
)
from .concurrent_robustness_v2 import (
    _V2_ALLOWED_TRANSITIONS,
    _V2_ATTEMPT_BILLING_PROFILES,
    _V2_CELL_COUNT,
    _V2_EXECUTION_ANCHOR_SCHEMA,
    _V2_EXECUTION_FILES,
    _V2_EXECUTION_PAYLOAD_FILES,
    _V2_EXECUTION_SCHEMA,
    _V2_FORMAL_LOGICAL_CAP,
    _V2_FORMAL_LOGICAL_PER_CELL,
    _V2_FORMAL_PHYSICAL_CAP,
    _V2_JUDGMENT_SCHEMA,
    _V2_MAXIMUM_ATTEMPTS,
    _V2_MODELS,
    _V2_PAIR_LEDGER_SCHEMA,
    _V2_REALIZED_TERMINAL_SCHEMA,
    _V2_WORKSPACE_MANIFEST,
    ConcurrentRobustnessManifestV2,
    _effective_graph_identity,
    _realization_source_payload,
    _V2AttemptEvidence,
    _V2Judgment,
    _V2RealizedTerminal,
)

CONCURRENT_ROBUSTNESS_STUDY_MANIFEST_V2_SCHEMA = "concurrent-robustness-study-artifact-manifest-v2"
CONCURRENT_ROBUSTNESS_STUDY_VALIDATION_V2_SCHEMA = "concurrent-robustness-complete-validation-v2"
CONCURRENT_ROBUSTNESS_REALIZED_ANALYSIS_V2_SCHEMA = "concurrent-prompt-model-realized-analysis-v2"
CONCURRENT_ROBUSTNESS_JUDGMENT_AUDIT_V2_SCHEMA = "concurrent-prompt-model-judgment-audit-v2"
CONCURRENT_ROBUSTNESS_CLAIM_AUDIT_V2_SCHEMA = "concurrent-robustness-claim-audit-v2"
CONCURRENT_ROBUSTNESS_SAMPLE_MEMBERSHIP_V2_SCHEMA = "concurrent-robustness-sample-membership-v2"

_STUDY_ROOT_SUFFIX = ".study-root"
_ROOT_MANIFEST = "artifact_manifest.json"
_STUDY_MANIFEST = "study_manifest.json"
_EXECUTION_MANIFEST = "execution_manifest.json"
_EXECUTION_ANCHOR = "execution_anchor.json"
_CELL_REGISTRY = "cell_registry.json"
_TERMINALS = "terminal_rows.jsonl"
_BATCH_COMMITS = "batch_commits.jsonl"
_PAIR_LIFECYCLE = "pair_lifecycle.jsonl"
_SAMPLE_MEMBERSHIP = "sample_membership.json"
_REALIZED_ANALYSIS = "realized_analysis.json"
_JUDGMENT_AUDIT = "judgment_audit.json"
_CLAIM_AUDIT = "claim_audit.json"
_VALIDATION = "validation_report.json"
_EXECUTION_NAMES = {
    _EXECUTION_MANIFEST,
    _EXECUTION_ANCHOR,
    _CELL_REGISTRY,
    _TERMINALS,
    _BATCH_COMMITS,
    _PAIR_LIFECYCLE,
}
_ROOT_FILES = {
    _ROOT_MANIFEST,
    _STUDY_MANIFEST,
    *_EXECUTION_NAMES,
    _SAMPLE_MEMBERSHIP,
    _REALIZED_ANALYSIS,
    _JUDGMENT_AUDIT,
    _CLAIM_AUDIT,
    _VALIDATION,
}
_HASH_PATTERN = __import__("re").compile(r"^[0-9a-f]{64}$")
_SEGMENTS = ("S1", "S2", "S3")
_SEGMENT_BY_CLASS = {"class_1": "S1", "class_2": "S2", "class_3": "S3"}
_MESSAGE_LABELS = {"message_1": "M1", "message_2": "M2", "message_3": "M3"}
_RATE_THRESHOLD = 0.02
_BOOTSTRAP_SEED = 20_260_823
_BOOTSTRAP_ITERATIONS = 500
_POSITIVE_ACTIONS = {"like", "comment", "share"}


class ConcurrentRobustnessV2EvidenceError(ValueError):
    """Persisted v2 evidence cannot be independently closed."""


class ConcurrentRobustnessV2EvidenceConflictError(ConcurrentRobustnessV2EvidenceError):
    """A final root conflicts with the deterministic no-overwrite closure."""


@dataclass(frozen=True)
class ConcurrentRobustnessV2StudyFacts:
    root_path: Path
    manifest_sha256: str
    root_identity_sha256: str
    logical_judgments: int
    physical_attempts: int
    provider_calls: int
    live_api_triggered: bool


@dataclass(frozen=True)
class _PersistedEvidence:
    manifest: ConcurrentRobustnessManifestV2
    manifest_bytes: bytes
    manifest_sha256: str
    execution_manifest: dict[str, Any]
    execution_manifest_sha256: str
    cell_registry: dict[str, Any]
    judgments: tuple[_V2Judgment, ...]
    terminals: tuple[_V2RealizedTerminal, ...]
    commits: tuple[dict[str, Any], ...]
    lifecycle: tuple[dict[str, Any], ...]
    physical_attempts: int
    provider_calls: int
    live_api_triggered: bool


@dataclass(frozen=True)
class _RootDocuments:
    evidence: _PersistedEvidence
    membership: dict[str, Any]
    realized_analysis: dict[str, Any]
    judgment_audit: dict[str, Any]
    claim_audit: dict[str, Any]


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_identity(value: object) -> str:
    return _sha256_bytes(_canonical_json_bytes(value))


def _read_canonical_object(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink() or not path.is_file():
        raise ConcurrentRobustnessV2EvidenceError(f"{label} must be a regular file")
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConcurrentRobustnessV2EvidenceError(f"{label} contains malformed JSON") from exc
    if not isinstance(value, dict) or raw != _canonical_json_bytes(value):
        raise ConcurrentRobustnessV2EvidenceError(f"{label} is not canonical JSON")
    return cast(dict[str, Any], value), raw


def _read_canonical_jsonl(path: Path, label: str) -> tuple[dict[str, Any], ...]:
    if path.is_symlink() or not path.is_file():
        raise ConcurrentRobustnessV2EvidenceError(f"{label} must be a regular file")
    rows: list[dict[str, Any]] = []
    with path.open("rb") as handle:
        for raw in handle:
            if not raw.endswith(b"\n"):
                raise ConcurrentRobustnessV2EvidenceError(f"{label} contains a partial row")
            try:
                value = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ConcurrentRobustnessV2EvidenceError(f"{label} contains malformed JSON") from exc
            if not isinstance(value, dict) or raw != _canonical_json_bytes(value):
                raise ConcurrentRobustnessV2EvidenceError(f"{label} is not canonical JSONL")
            rows.append(cast(dict[str, Any], value))
    return tuple(rows)


def _real_directory(path: Path, label: str) -> Path:
    if ".." in path.parts:
        raise ConcurrentRobustnessV2EvidenceError(f"{label} must not contain '..'")
    absolute = Path(os.path.abspath(path))
    try:
        resolved = absolute.resolve(strict=True)
    except OSError as exc:
        raise ConcurrentRobustnessV2EvidenceError(f"{label} does not exist") from exc
    if absolute != resolved or absolute.is_symlink() or not resolved.is_dir():
        raise ConcurrentRobustnessV2EvidenceError(f"{label} must be a real directory")
    return resolved


def _snapshot_tree(root: Path) -> dict[str, tuple[int, str]]:
    snapshot: dict[str, tuple[int, str]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ConcurrentRobustnessV2EvidenceError("evidence source contains a symlink")
        if path.is_dir():
            snapshot[f"{relative}/"] = (0, "directory")
        elif path.is_file():
            snapshot[relative] = (path.stat().st_size, _sha256_file(path))
        else:
            raise ConcurrentRobustnessV2EvidenceError("evidence source contains a non-regular entry")
    return snapshot


def _strict_int(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ConcurrentRobustnessV2EvidenceError(f"{label} must be an integer >= {minimum}")
    return value


def _string_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ConcurrentRobustnessV2EvidenceError(f"{label} must be a string list")
    return cast(list[str], value)


def _expected_judgment_source(
    manifest: ConcurrentRobustnessManifestV2,
    manifest_sha256: str,
    cell_index: int,
) -> str:
    cell = manifest.prompt_model_cells[cell_index]
    return _json_identity(
        {
            "schema_version": "concurrent-robustness-judgment-source-identity-v2",
            "manifest_sha256": manifest_sha256,
            "source_manifest_sha256": manifest.source.manifest_sha256,
            "sample_identity": manifest.sample.sample_identity,
            "message_snapshot_sha256": manifest.message_snapshot_sha256,
            "cell_index": cell_index,
            "cell": cell.model_dump(mode="json"),
        }
    )


def _validate_row_identity(
    row: _V2Judgment | _V2RealizedTerminal,
    record: Mapping[str, object],
    manifest: ConcurrentRobustnessManifestV2,
    manifest_sha256: str,
) -> None:
    cell_index = _strict_int(record.get("cell_index"), "lifecycle cell index")
    if cell_index >= _V2_CELL_COUNT:
        raise ConcurrentRobustnessV2EvidenceError("lifecycle cell index is outside the panel")
    cell = manifest.prompt_model_cells[cell_index]
    record_fields = (
        "cell_index",
        "cell_id",
        "pair_id",
        "pair_schedule_position",
        "time_step",
        "message_id",
        "user_id",
    )
    if any(getattr(row, field) != record.get(field) for field in record_fields):
        raise ConcurrentRobustnessV2EvidenceError("lifecycle payload identity is crossed")
    if (
        row.cell_id != cell.cell_id
        or row.prompt_variant != cell.prompt_variant
        or row.prompt_version != cell.prompt_version
        or row.prompt_canonical_hash != cell.prompt_canonical_hash
        or row.requested_model != cell.requested_model
        or row.observed_model != cell.required_observed_model
        or row.judgment_source_identity
        != _expected_judgment_source(manifest, manifest_sha256, cell_index)
    ):
        raise ConcurrentRobustnessV2EvidenceError("Judgment is crossed with its Prompt-Model cell")
    if isinstance(row, _V2RealizedTerminal) and (
        row.realization_source_identity != manifest.realization_source.source_identity
    ):
        raise ConcurrentRobustnessV2EvidenceError("terminal realization source is crossed")


def _validate_attempting_payload(payload: Mapping[str, object]) -> None:
    if not payload:
        return
    expected = {"phase", "next_attempt_number", "attempt_evidence", "retry_delay_seconds"}
    if set(payload) != expected or payload.get("phase") not in {"pre_dispatch", "dispatching", "retry_wait"}:
        raise ConcurrentRobustnessV2EvidenceError("attempting lifecycle payload schema is invalid")
    raw_attempts = payload.get("attempt_evidence")
    if not isinstance(raw_attempts, list):
        raise ConcurrentRobustnessV2EvidenceError("attempting lifecycle evidence must be a list")
    attempts = tuple(_V2AttemptEvidence.model_validate(row) for row in raw_attempts)
    next_attempt = _strict_int(payload.get("next_attempt_number"), "next attempt number", minimum=1)
    if (
        next_attempt > _V2_MAXIMUM_ATTEMPTS
        or tuple(row.attempt_number for row in attempts) != tuple(range(1, len(attempts) + 1))
        or next_attempt != len(attempts) + 1
        or any(row.outcome == "succeeded" for row in attempts)
    ):
        raise ConcurrentRobustnessV2EvidenceError("attempting lifecycle cursor is crossed")
    retry_delay = payload.get("retry_delay_seconds")
    if payload.get("phase") == "retry_wait":
        if (
            not attempts
            or attempts[-1].outcome != "retryable_failure"
            or isinstance(retry_delay, bool)
            or not isinstance(retry_delay, (int, float))
            or not math.isfinite(float(retry_delay))
            or float(retry_delay) < 0.0
        ):
            raise ConcurrentRobustnessV2EvidenceError("retry-wait lifecycle evidence is invalid")
    elif retry_delay is not None:
        raise ConcurrentRobustnessV2EvidenceError("non-waiting lifecycle cannot carry a retry delay")


def _terminal_matches_judgment(terminal: _V2RealizedTerminal, judgment: _V2Judgment) -> bool:
    fields = (
        "judgment_source_identity",
        "cell_index",
        "cell_id",
        "pair_id",
        "pair_schedule_position",
        "time_step",
        "message_id",
        "user_id",
        "prompt_variant",
        "prompt_version",
        "prompt_canonical_hash",
        "requested_model",
        "observed_model",
        "provider_engage",
        "provider_probability",
        "provider_action",
        "provider_reason",
        "provider_confidence",
        "provider_decision_source",
        "environmental_consciousness_prompt_inclusion",
        "request_invocations",
    )
    return terminal.judgment_id == judgment.judgment_id and all(
        getattr(terminal, field) == getattr(judgment, field) for field in fields
    )


def _replay_lifecycle(
    rows: Sequence[Mapping[str, object]],
    manifest: ConcurrentRobustnessManifestV2,
    manifest_sha256: str,
) -> tuple[tuple[_V2Judgment, ...], tuple[_V2RealizedTerminal, ...], dict[int, int]]:
    required_keys = {
        "schema_version",
        "sequence",
        "previous_checksum",
        "cell_index",
        "cell_id",
        "pair_id",
        "pair_schedule_position",
        "time_step",
        "message_id",
        "user_id",
        "state",
        "payload",
        "checksum",
    }
    sequences = {index: 0 for index in range(_V2_CELL_COUNT)}
    checksums: dict[int, str | None] = {index: None for index in range(_V2_CELL_COUNT)}
    states: dict[tuple[int, str], str] = {}
    identities: dict[tuple[int, str], tuple[object, ...]] = {}
    judgment_by_pair: dict[tuple[int, str], _V2Judgment] = {}
    terminal_by_pair: dict[tuple[int, str], _V2RealizedTerminal] = {}
    judgments: list[_V2Judgment] = []
    terminals: list[_V2RealizedTerminal] = []
    records_per_cell: Counter[int] = Counter()
    prior_cell_index = 0

    for record in rows:
        if set(record) != required_keys or record.get("schema_version") != _V2_PAIR_LEDGER_SCHEMA:
            raise ConcurrentRobustnessV2EvidenceError("lifecycle record schema is invalid")
        cell_index = _strict_int(record.get("cell_index"), "lifecycle cell index")
        if cell_index >= _V2_CELL_COUNT or cell_index < prior_cell_index:
            raise ConcurrentRobustnessV2EvidenceError("lifecycle cell order is crossed")
        prior_cell_index = cell_index
        cell = manifest.prompt_model_cells[cell_index]
        if record.get("cell_id") != cell.cell_id:
            raise ConcurrentRobustnessV2EvidenceError("lifecycle cell identity is crossed")
        sequence = _strict_int(record.get("sequence"), "lifecycle sequence", minimum=1)
        if sequence != sequences[cell_index] + 1 or record.get("previous_checksum") != checksums[cell_index]:
            raise ConcurrentRobustnessV2EvidenceError("lifecycle sequence or checksum chain is broken")
        body = {key: value for key, value in record.items() if key != "checksum"}
        checksum = record.get("checksum")
        if not isinstance(checksum, str) or checksum != _json_identity(body):
            raise ConcurrentRobustnessV2EvidenceError("lifecycle checksum is invalid")
        sequences[cell_index] = sequence
        checksums[cell_index] = checksum
        records_per_cell[cell_index] += 1

        pair_id = record.get("pair_id")
        state = record.get("state")
        if not isinstance(pair_id, str) or not pair_id or not isinstance(state, str):
            raise ConcurrentRobustnessV2EvidenceError("lifecycle pair or state is invalid")
        pair_key = (cell_index, pair_id)
        prior = states.get(pair_key)
        if state not in _V2_ALLOWED_TRANSITIONS.get(prior, set()):
            raise ConcurrentRobustnessV2EvidenceError("lifecycle state transition is invalid")
        identity = tuple(
            record.get(key)
            for key in (
                "cell_index",
                "cell_id",
                "pair_id",
                "pair_schedule_position",
                "time_step",
                "message_id",
                "user_id",
            )
        )
        if pair_key in identities and identities[pair_key] != identity:
            raise ConcurrentRobustnessV2EvidenceError("pair identity changed between lifecycle stages")
        identities[pair_key] = identity
        payload = record.get("payload")
        if not isinstance(payload, Mapping):
            raise ConcurrentRobustnessV2EvidenceError("lifecycle payload must be an object")

        if state == "pending":
            if payload:
                raise ConcurrentRobustnessV2EvidenceError("pending lifecycle cannot carry a payload")
        elif state == "reserved":
            if payload != {"maximum_physical_attempts": _V2_MAXIMUM_ATTEMPTS}:
                raise ConcurrentRobustnessV2EvidenceError("reserved lifecycle attempt cap is crossed")
        elif state == "attempting":
            _validate_attempting_payload(payload)
        elif state == "judgment_persisted":
            if set(payload) != {"judgment"}:
                raise ConcurrentRobustnessV2EvidenceError("Judgment lifecycle payload schema is invalid")
            judgment = _V2Judgment.model_validate(payload.get("judgment"))
            if judgment.schema_version != _V2_JUDGMENT_SCHEMA:
                raise ConcurrentRobustnessV2EvidenceError("Judgment schema is unsupported")
            _validate_row_identity(judgment, record, manifest, manifest_sha256)
            if pair_key in judgment_by_pair:
                raise ConcurrentRobustnessV2EvidenceError("duplicate persisted Judgment")
            judgment_by_pair[pair_key] = judgment
            judgments.append(judgment)
        elif state == "realized_persisted":
            if set(payload) != {"terminal"}:
                raise ConcurrentRobustnessV2EvidenceError("Realized lifecycle payload schema is invalid")
            terminal = _V2RealizedTerminal.model_validate(payload.get("terminal"))
            if terminal.schema_version != _V2_REALIZED_TERMINAL_SCHEMA:
                raise ConcurrentRobustnessV2EvidenceError("Realized terminal schema is unsupported")
            _validate_row_identity(terminal, record, manifest, manifest_sha256)
            judgment = judgment_by_pair.get(pair_key)
            if judgment is None or not _terminal_matches_judgment(terminal, judgment):
                raise ConcurrentRobustnessV2EvidenceError("Realized terminal is crossed with its Judgment")
            if pair_key in terminal_by_pair:
                raise ConcurrentRobustnessV2EvidenceError("duplicate persisted Realized terminal")
            terminal_by_pair[pair_key] = terminal
            terminals.append(terminal)
        elif state == "settled":
            terminal = terminal_by_pair.get(pair_key)
            if terminal is None or payload != {"realized_terminal_id": terminal.realized_terminal_id}:
                raise ConcurrentRobustnessV2EvidenceError("settled lifecycle is crossed with its terminal")
        else:
            raise ConcurrentRobustnessV2EvidenceError("closed evidence contains a stopped pair")
        states[pair_key] = state

    expected_pairs = manifest.request_caps.logical_judgment_cap
    if (
        len(states) != expected_pairs
        or any(state != "settled" for state in states.values())
        or len(judgments) != expected_pairs
        or len(terminals) != expected_pairs
        or set(records_per_cell) != set(range(_V2_CELL_COUNT))
    ):
        raise ConcurrentRobustnessV2EvidenceError("lifecycle does not close every selected pair")
    return tuple(judgments), tuple(terminals), dict(records_per_cell)


def _validate_terminal_inventory(
    terminals: Sequence[_V2RealizedTerminal],
    manifest: ConcurrentRobustnessManifestV2,
    manifest_sha256: str,
    membership_by_user: Mapping[str, str],
) -> None:
    expected_per_cell = manifest.request_caps.logical_judgments_per_cell
    if len(terminals) != manifest.request_caps.logical_judgment_cap:
        raise ConcurrentRobustnessV2EvidenceError("Realized terminal denominator is incomplete")
    if len({row.realized_terminal_id for row in terminals}) != len(terminals):
        raise ConcurrentRobustnessV2EvidenceError("duplicate Realized terminal identity")
    expected_order = sorted(terminals, key=lambda row: (row.cell_index, row.pair_schedule_position))
    if list(terminals) != expected_order:
        raise ConcurrentRobustnessV2EvidenceError("Realized terminals are not in canonical cell schedule order")

    pair_keys_by_cell: dict[int, set[tuple[str, str]]] = defaultdict(set)
    counts_by_batch_message: Counter[tuple[int, int, str]] = Counter()
    vector_keys: dict[tuple[str, str], set[str]] = defaultdict(set)
    vector_draws: dict[tuple[str, str], set[float]] = defaultdict(set)
    positions: dict[int, list[int]] = defaultdict(list)
    counts_by_cell: Counter[int] = Counter()
    for terminal in terminals:
        _validate_row_identity(
            terminal,
            {
                "cell_index": terminal.cell_index,
                "cell_id": terminal.cell_id,
                "pair_id": terminal.pair_id,
                "pair_schedule_position": terminal.pair_schedule_position,
                "time_step": terminal.time_step,
                "message_id": terminal.message_id,
                "user_id": terminal.user_id,
            },
            manifest,
            manifest_sha256,
        )
        if terminal.user_id not in membership_by_user:
            raise ConcurrentRobustnessV2EvidenceError("terminal user is outside the frozen sample")
        if terminal.message_id not in manifest.message_ids or terminal.time_step >= manifest.ranking_contract.horizon:
            raise ConcurrentRobustnessV2EvidenceError("terminal message or batch is outside the manifest")
        pair_key = (terminal.user_id, terminal.message_id)
        if pair_key in pair_keys_by_cell[terminal.cell_index]:
            raise ConcurrentRobustnessV2EvidenceError("cell repeats a message-level exposure")
        pair_keys_by_cell[terminal.cell_index].add(pair_key)
        counts_by_batch_message[(terminal.cell_index, terminal.time_step, terminal.message_id)] += 1
        counts_by_cell[terminal.cell_index] += 1
        positions[terminal.cell_index].append(terminal.pair_schedule_position)
        vector_keys[pair_key].add(terminal.realization_key)
        if terminal.uniform_draw is not None:
            vector_draws[pair_key].add(terminal.uniform_draw)
        if terminal.realized_engage != (terminal.realized_action in _POSITIVE_ACTIONS):
            raise ConcurrentRobustnessV2EvidenceError("Realized engage and action are crossed")

    expected_positions = list(range(expected_per_cell))
    for cell_index in range(_V2_CELL_COUNT):
        if counts_by_cell[cell_index] != expected_per_cell or positions[cell_index] != expected_positions:
            raise ConcurrentRobustnessV2EvidenceError("cell schedule positions are incomplete")
        for time_step in range(manifest.ranking_contract.horizon):
            for message_id in manifest.message_ids:
                if (
                    counts_by_batch_message[(cell_index, time_step, message_id)]
                    != manifest.ranking_contract.delivery_capacity
                ):
                    raise ConcurrentRobustnessV2EvidenceError("batch-message Realized denominator is incomplete")
    if any(len(keys) != 1 for keys in vector_keys.values()) or any(
        len(draws) > 1 for draws in vector_draws.values()
    ):
        raise ConcurrentRobustnessV2EvidenceError("shared deterministic realization vector is crossed")


def _validate_batch_commits(
    commits: Sequence[Mapping[str, object]],
    terminals: Sequence[_V2RealizedTerminal],
    manifest: ConcurrentRobustnessManifestV2,
) -> None:
    expected_keys = [
        (cell_index, time_step)
        for cell_index in range(_V2_CELL_COUNT)
        for time_step in range(manifest.ranking_contract.horizon)
    ]
    actual_keys = [
        (
            _strict_int(row.get("cell_index"), "commit cell index"),
            _strict_int(row.get("time_step"), "commit time step"),
        )
        for row in commits
    ]
    if actual_keys != expected_keys:
        raise ConcurrentRobustnessV2EvidenceError("batch commits are missing, duplicated, or reordered")
    terminals_by_batch: dict[tuple[int, int], list[_V2RealizedTerminal]] = defaultdict(list)
    for terminal in terminals:
        terminals_by_batch[(terminal.cell_index, terminal.time_step)].append(terminal)
    campaign_feedback: dict[int, set[str]] = {index: set() for index in range(_V2_CELL_COUNT)}
    expected_record_keys = {
        "schema_version",
        "cell_index",
        "cell_id",
        "time_step",
        "frozen_campaign_engaged_user_ids",
        "committed_realized_positive_user_ids",
        "messages",
    }
    for commit in commits:
        if (
            set(commit) != expected_record_keys
            or commit.get("schema_version") != "concurrent-robustness-two-stage-batch-commit-v2"
        ):
            raise ConcurrentRobustnessV2EvidenceError("batch commit schema is invalid")
        cell_index = cast(int, commit["cell_index"])
        time_step = cast(int, commit["time_step"])
        if commit.get("cell_id") != manifest.prompt_model_cells[cell_index].cell_id:
            raise ConcurrentRobustnessV2EvidenceError("batch commit cell identity is crossed")
        frozen = _string_list(commit.get("frozen_campaign_engaged_user_ids"), "frozen feedback")
        if frozen != sorted(campaign_feedback[cell_index]):
            raise ConcurrentRobustnessV2EvidenceError("batch frozen feedback is crossed")
        messages = commit.get("messages")
        if not isinstance(messages, list) or len(messages) != len(manifest.message_ids):
            raise ConcurrentRobustnessV2EvidenceError("batch message evidence is incomplete")
        batch_terminals = terminals_by_batch[(cell_index, time_step)]
        committed_from_messages: set[str] = set()
        for message_id, raw_message in zip(manifest.message_ids, messages, strict=True):
            if not isinstance(raw_message, Mapping) or set(raw_message) != {
                "message_id",
                "selected_user_ids",
                "realized_positive_user_ids",
                "provider_failed_user_ids",
            }:
                raise ConcurrentRobustnessV2EvidenceError("batch message evidence schema is invalid")
            if raw_message.get("message_id") != message_id:
                raise ConcurrentRobustnessV2EvidenceError("batch message order is crossed")
            message_terminals = [row for row in batch_terminals if row.message_id == message_id]
            selected = [row.user_id for row in message_terminals]
            positives = [row.user_id for row in message_terminals if row.realized_engage]
            if _string_list(raw_message.get("selected_user_ids"), "selected users") != selected:
                raise ConcurrentRobustnessV2EvidenceError("batch selected users are crossed")
            if _string_list(raw_message.get("realized_positive_user_ids"), "Realized positives") != positives:
                raise ConcurrentRobustnessV2EvidenceError("batch Realized feedback is crossed")
            if _string_list(raw_message.get("provider_failed_user_ids"), "Provider failures"):
                raise ConcurrentRobustnessV2EvidenceError("closed batch contains a Provider failure")
            committed_from_messages.update(positives)
        committed = _string_list(commit.get("committed_realized_positive_user_ids"), "committed feedback")
        if committed != sorted(committed_from_messages):
            raise ConcurrentRobustnessV2EvidenceError("campaign feedback is not deduplicated")
        campaign_feedback[cell_index].update(committed)


def _validate_execution_documents(
    paths: Mapping[str, Path],
    manifest: ConcurrentRobustnessManifestV2,
    manifest_bytes: bytes,
    membership_by_user: Mapping[str, str],
) -> _PersistedEvidence:
    if set(paths) != _EXECUTION_NAMES:
        raise ConcurrentRobustnessV2EvidenceError("execution artifact inventory is incomplete")
    if any(path.is_symlink() or not path.is_file() for path in paths.values()):
        raise ConcurrentRobustnessV2EvidenceError("execution inventory contains a non-regular artifact")
    manifest_sha256 = _sha256_bytes(manifest_bytes)
    anchor, _ = _read_canonical_object(paths[_EXECUTION_ANCHOR], "execution anchor")
    if (
        set(anchor)
        != {"schema_version", "manifest_sha256", "execution_manifest_sha256", "anchor_identity"}
        or anchor.get("schema_version") != _V2_EXECUTION_ANCHOR_SCHEMA
        or anchor.get("manifest_sha256") != manifest_sha256
        or paths[_EXECUTION_ANCHOR].stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
    ):
        raise ConcurrentRobustnessV2EvidenceError("execution immutable anchor is invalid")
    anchor_facts = {key: value for key, value in anchor.items() if key != "anchor_identity"}
    if anchor.get("anchor_identity") != _json_identity(anchor_facts):
        raise ConcurrentRobustnessV2EvidenceError("execution anchor identity is crossed")

    execution_manifest, execution_manifest_bytes = _read_canonical_object(
        paths[_EXECUTION_MANIFEST], "execution manifest"
    )
    execution_manifest_sha256 = _sha256_bytes(execution_manifest_bytes)
    if (
        anchor.get("execution_manifest_sha256") != execution_manifest_sha256
        or execution_manifest.get("schema_version") != _V2_EXECUTION_SCHEMA
        or execution_manifest.get("manifest_sha256") != manifest_sha256
        or execution_manifest.get("realization_source_identity")
        != manifest.realization_source.source_identity
        or execution_manifest.get("production_deploy_eligible") is not False
    ):
        raise ConcurrentRobustnessV2EvidenceError("execution manifest identity is crossed")
    classification = execution_manifest.get("classification")
    provider_calls = _strict_int(execution_manifest.get("provider_calls"), "execution Provider calls")
    live_api_triggered = execution_manifest.get("live_api_triggered")
    if not isinstance(live_api_triggered, bool):
        raise ConcurrentRobustnessV2EvidenceError("execution live-call evidence is malformed")
    if manifest.execution_profile == "deterministic_validation":
        if classification != "deterministic_two_stage_validation" or provider_calls != 0 or live_api_triggered:
            raise ConcurrentRobustnessV2EvidenceError("validation execution is crossed with live Provider evidence")
    elif classification != "formal_two_stage_live" or not live_api_triggered:
        raise ConcurrentRobustnessV2EvidenceError("Formal execution classification is incomplete")

    artifacts = execution_manifest.get("artifacts")
    if not isinstance(artifacts, Mapping) or set(artifacts) != _V2_EXECUTION_PAYLOAD_FILES:
        raise ConcurrentRobustnessV2EvidenceError("execution artifact registry is incomplete")
    for name, reference in artifacts.items():
        path = paths[str(name)]
        if (
            not isinstance(reference, Mapping)
            or reference.get("sha256") != _sha256_file(path)
            or reference.get("bytes") != path.stat().st_size
        ):
            raise ConcurrentRobustnessV2EvidenceError("execution artifact hash or byte count is crossed")

    lifecycle = _read_canonical_jsonl(paths[_PAIR_LIFECYCLE], "pair lifecycle")
    judgments, lifecycle_terminals, records_per_cell = _replay_lifecycle(
        lifecycle,
        manifest,
        manifest_sha256,
    )
    if any(not judgment.usage_complete for judgment in judgments):
        raise ConcurrentRobustnessV2EvidenceError(
            "complete v2 study closure requires complete usage for every Judgment"
        )
    terminal_rows = _read_canonical_jsonl(paths[_TERMINALS], "Realized terminals")
    terminals = tuple(_V2RealizedTerminal.model_validate(row) for row in terminal_rows)
    if [row.model_dump(mode="json") for row in terminals] != [
        row.model_dump(mode="json") for row in lifecycle_terminals
    ]:
        raise ConcurrentRobustnessV2EvidenceError("terminal artifact is crossed with lifecycle evidence")
    _validate_terminal_inventory(terminals, manifest, manifest_sha256, membership_by_user)

    commits = _read_canonical_jsonl(paths[_BATCH_COMMITS], "batch commits")
    _validate_batch_commits(commits, terminals, manifest)
    physical_attempts = sum(row.request_invocations for row in judgments)
    counts = execution_manifest.get("counts")
    expected_counts = {
        "cells": _V2_CELL_COUNT,
        "logical_judgments": len(judgments),
        "physical_attempts": physical_attempts,
        "realized_terminals": len(terminals),
        "batch_commits": len(commits),
    }
    if counts != expected_counts or physical_attempts > manifest.request_caps.physical_attempt_cap:
        raise ConcurrentRobustnessV2EvidenceError("execution denominator or physical-attempt cap is crossed")
    if manifest.execution_profile == "formal" and provider_calls != physical_attempts:
        raise ConcurrentRobustnessV2EvidenceError("Formal Provider call accounting is incomplete")

    registry, _ = _read_canonical_object(paths[_CELL_REGISTRY], "cell registry")
    if set(registry) != {
        "schema_version",
        "manifest_sha256",
        "realization_source_identity",
        "cells",
        "provider_calls",
        "live_api_triggered",
        "production_deploy_eligible",
    }:
        raise ConcurrentRobustnessV2EvidenceError("cell registry schema is invalid")
    if (
        registry.get("schema_version") != "concurrent-robustness-two-stage-cell-registry-v2"
        or registry.get("manifest_sha256") != manifest_sha256
        or registry.get("realization_source_identity") != manifest.realization_source.source_identity
        or registry.get("provider_calls") != provider_calls
        or registry.get("live_api_triggered") is not live_api_triggered
        or registry.get("production_deploy_eligible") is not False
    ):
        raise ConcurrentRobustnessV2EvidenceError("cell registry identity is crossed")
    registry_cells = registry.get("cells")
    if not isinstance(registry_cells, list) or len(registry_cells) != _V2_CELL_COUNT:
        raise ConcurrentRobustnessV2EvidenceError("cell registry denominator is incomplete")
    judgments_by_cell: Counter[int] = Counter(row.cell_index for row in judgments)
    attempts_by_cell: Counter[int] = Counter()
    for judgment in judgments:
        attempts_by_cell[judgment.cell_index] += judgment.request_invocations
    commits_by_cell: Counter[int] = Counter(_strict_int(row.get("cell_index"), "commit cell index") for row in commits)
    for cell_index, row in enumerate(registry_cells):
        if not isinstance(row, Mapping) or set(row) != {
            "cell_index",
            "cell_id",
            "judgment_source_identity",
            "runtime_identity_hash",
            "logical_judgments",
            "physical_attempts",
            "realized_terminals",
            "batch_commits",
            "lifecycle_records",
        }:
            raise ConcurrentRobustnessV2EvidenceError("cell registry row schema is invalid")
        runtime_identity = row.get("runtime_identity_hash")
        if (
            row.get("cell_index") != cell_index
            or row.get("cell_id") != manifest.prompt_model_cells[cell_index].cell_id
            or row.get("judgment_source_identity")
            != _expected_judgment_source(manifest, manifest_sha256, cell_index)
            or not isinstance(runtime_identity, str)
            or not _HASH_PATTERN.fullmatch(runtime_identity)
            or row.get("logical_judgments") != judgments_by_cell[cell_index]
            or row.get("physical_attempts") != attempts_by_cell[cell_index]
            or row.get("realized_terminals") != judgments_by_cell[cell_index]
            or row.get("batch_commits") != commits_by_cell[cell_index]
            or row.get("lifecycle_records") != records_per_cell[cell_index]
        ):
            raise ConcurrentRobustnessV2EvidenceError("cell registry row is crossed with persisted evidence")

    return _PersistedEvidence(
        manifest=manifest,
        manifest_bytes=manifest_bytes,
        manifest_sha256=manifest_sha256,
        execution_manifest=execution_manifest,
        execution_manifest_sha256=execution_manifest_sha256,
        cell_registry=registry,
        judgments=judgments,
        terminals=terminals,
        commits=tuple(cast(dict[str, Any], row) for row in commits),
        lifecycle=tuple(cast(dict[str, Any], row) for row in lifecycle),
        physical_attempts=physical_attempts,
        provider_calls=provider_calls,
        live_api_triggered=live_api_triggered,
    )


def _membership_document(
    manifest: ConcurrentRobustnessManifestV2,
    sample_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if len(sample_rows) != manifest.sample.sample_size:
        raise ConcurrentRobustnessV2EvidenceError("sample membership denominator is incomplete")
    if _ordered_user_ids_sha256(sample_rows) != manifest.sample.sample_identity:
        raise ConcurrentRobustnessV2EvidenceError("sample membership identity is crossed")
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    counts: Counter[str] = Counter()
    for source_row in sample_rows:
        user_id = source_row.get("user_id")
        latent_class = source_row.get("latent_class")
        if (
            not isinstance(user_id, str)
            or not user_id
            or user_id in seen
            or not isinstance(latent_class, str)
            or latent_class not in _SEGMENT_BY_CLASS
        ):
            raise ConcurrentRobustnessV2EvidenceError("sample membership contains a malformed user or segment")
        seen.add(user_id)
        segment = _SEGMENT_BY_CLASS[latent_class]
        counts[segment] += 1
        rows.append({"user_id": user_id, "latent_class": latent_class, "segment": segment})
    return {
        "schema_version": CONCURRENT_ROBUSTNESS_SAMPLE_MEMBERSHIP_V2_SCHEMA,
        "source_manifest_sha256": manifest.source.manifest_sha256,
        "sample_manifest_sha256": manifest.sample.sample_manifest_sha256,
        "sample_identity": manifest.sample.sample_identity,
        "counts": {"users": len(rows), **{segment: counts[segment] for segment in _SEGMENTS}},
        "rows": rows,
    }


def _validate_membership_document(
    document: Mapping[str, Any], manifest: ConcurrentRobustnessManifestV2
) -> dict[str, str]:
    if set(document) != {
        "schema_version",
        "source_manifest_sha256",
        "sample_manifest_sha256",
        "sample_identity",
        "counts",
        "rows",
    }:
        raise ConcurrentRobustnessV2EvidenceError("sample membership schema is invalid")
    if (
        document.get("schema_version") != CONCURRENT_ROBUSTNESS_SAMPLE_MEMBERSHIP_V2_SCHEMA
        or document.get("source_manifest_sha256") != manifest.source.manifest_sha256
        or document.get("sample_manifest_sha256") != manifest.sample.sample_manifest_sha256
        or document.get("sample_identity") != manifest.sample.sample_identity
    ):
        raise ConcurrentRobustnessV2EvidenceError("sample membership lineage is crossed")
    raw_rows = document.get("rows")
    if not isinstance(raw_rows, list):
        raise ConcurrentRobustnessV2EvidenceError("sample membership rows are malformed")
    reconstructed = _membership_document(manifest, cast(list[Mapping[str, Any]], raw_rows))
    if reconstructed != document:
        raise ConcurrentRobustnessV2EvidenceError("sample membership counts or ordering are crossed")
    return {str(row["user_id"]): str(row["segment"]) for row in raw_rows}


def _group_specs(manifest: ConcurrentRobustnessManifestV2) -> tuple[tuple[str, tuple[str, ...]], ...]:
    del manifest
    return (
        ("total", ()),
        ("model", ("requested_model",)),
        ("prompt", ("prompt_variant",)),
        ("segment", ("segment",)),
        ("message", ("message_id",)),
        ("model_prompt", ("requested_model", "prompt_variant")),
        ("segment_message", ("segment", "message_id")),
        (
            "model_prompt_segment_message",
            ("requested_model", "prompt_variant", "segment", "message_id"),
        ),
    )


def _dimension_values(manifest: ConcurrentRobustnessManifestV2) -> dict[str, tuple[str, ...]]:
    return {
        "requested_model": _V2_MODELS,
        "prompt_variant": tuple(prompt for prompt in manifest.formal_contract.prompt_variants),
        "segment": _SEGMENTS,
        "message_id": manifest.message_ids,
    }


def _cartesian_rows(
    dimensions: tuple[str, ...], values: Mapping[str, tuple[str, ...]]
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = [{}]
    for dimension in dimensions:
        rows = [
            {**row, dimension: value}
            for row in rows
            for value in values[dimension]
        ]
    return rows


def _matches(row: Mapping[str, object], selection: Mapping[str, str]) -> bool:
    return all(row.get(key) == value for key, value in selection.items())


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 12) if denominator else 0.0


def _realized_group_rows(
    evidence: _PersistedEvidence,
    membership_by_user: Mapping[str, str],
) -> list[dict[str, Any]]:
    source_rows = [
        {
            "requested_model": row.requested_model,
            "prompt_variant": row.prompt_variant,
            "segment": membership_by_user[row.user_id],
            "message_id": row.message_id,
            "realized_action": row.realized_action,
        }
        for row in evidence.terminals
    ]
    values = _dimension_values(evidence.manifest)
    result: list[dict[str, Any]] = []
    for scope, dimensions in _group_specs(evidence.manifest):
        for selection in _cartesian_rows(dimensions, values):
            rows = [row for row in source_rows if _matches(row, selection)]
            actions = Counter(str(row["realized_action"]) for row in rows)
            engagement = sum(actions[action] for action in sorted(_POSITIVE_ACTIONS))
            result.append(
                {
                    "scope": scope,
                    "requested_model": selection.get("requested_model"),
                    "prompt_variant": selection.get("prompt_variant"),
                    "segment": selection.get("segment"),
                    "message_id": selection.get("message_id"),
                    "message_label": _MESSAGE_LABELS.get(selection.get("message_id", "")),
                    "like_count": actions["like"],
                    "comment_count": actions["comment"],
                    "share_count": actions["share"],
                    "engagement_count": engagement,
                    "exposure_count": len(rows),
                    "engagement_rate": _rate(engagement, len(rows)),
                }
            )
    return result


def _cell_rate(terminals: Sequence[_V2RealizedTerminal], cell_id: str) -> float:
    rows = [row for row in terminals if row.cell_id == cell_id]
    return _rate(sum(row.realized_engage for row in rows), len(rows))


def _difference_label(value: float) -> str:
    return "small_observed_difference" if abs(value) < _RATE_THRESHOLD else "observed_difference"


def _planned_contrasts(evidence: _PersistedEvidence) -> list[dict[str, Any]]:
    baseline_model = "openai-codex/gpt-5.6-sol"
    prompt_variants = evidence.manifest.formal_contract.prompt_variants
    rows: list[dict[str, Any]] = []

    def rate_for(*, model: str | None = None, prompt: str | None = None) -> float:
        selected = [
            row
            for row in evidence.terminals
            if (model is None or row.requested_model == model)
            and (prompt is None or row.prompt_variant == prompt)
        ]
        return _rate(sum(row.realized_engage for row in selected), len(selected))

    for model in _V2_MODELS:
        if model == baseline_model:
            continue
        estimate = round(rate_for(model=model) - rate_for(model=baseline_model), 12)
        rows.append(
            {
                "contrast_id": f"model:{model}-vs-{baseline_model}",
                "factor": "model",
                "left": model,
                "right": baseline_model,
                "realized_engagement_rate_difference": estimate,
                "classification": _difference_label(estimate),
            }
        )
    for prompt in prompt_variants[1:]:
        estimate = round(rate_for(prompt=prompt) - rate_for(prompt="P0"), 12)
        rows.append(
            {
                "contrast_id": f"prompt:{prompt}-vs-P0",
                "factor": "prompt",
                "left": prompt,
                "right": "P0",
                "realized_engagement_rate_difference": estimate,
                "classification": _difference_label(estimate),
            }
        )
    return rows


def _prompt_model_interactions(evidence: _PersistedEvidence) -> list[dict[str, Any]]:
    baseline_model = "openai-codex/gpt-5.6-sol"
    rows: list[dict[str, Any]] = []
    for model in _V2_MODELS:
        if model == baseline_model:
            continue
        for prompt in evidence.manifest.formal_contract.prompt_variants[1:]:
            estimate = round(
                (_cell_rate(evidence.terminals, f"{prompt}::{model}") - _cell_rate(evidence.terminals, f"P0::{model}"))
                - (
                    _cell_rate(evidence.terminals, f"{prompt}::{baseline_model}")
                    - _cell_rate(evidence.terminals, f"P0::{baseline_model}")
                ),
                12,
            )
            rows.append(
                {
                    "model": model,
                    "reference_model": baseline_model,
                    "prompt_variant": prompt,
                    "reference_prompt": "P0",
                    "difference_in_realized_engagement_rate_differences": estimate,
                    "classification": _difference_label(estimate),
                }
            )
    return rows


def _paired_overlap(evidence: _PersistedEvidence) -> list[dict[str, Any]]:
    pairs = {
        cell.cell_id: {
            (row.user_id, row.message_id)
            for row in evidence.terminals
            if row.cell_id == cell.cell_id
        }
        for cell in evidence.manifest.prompt_model_cells
    }
    baseline_model = "openai-codex/gpt-5.6-sol"
    rows: list[dict[str, Any]] = []
    for model in _V2_MODELS:
        for prompt in evidence.manifest.formal_contract.prompt_variants:
            if model == baseline_model:
                continue
            left_id = f"{prompt}::{model}"
            right_id = f"{prompt}::{baseline_model}"
            intersection = len(pairs[left_id] & pairs[right_id])
            union = len(pairs[left_id] | pairs[right_id])
            rows.append(
                {
                    "comparison": "model_within_prompt",
                    "left_cell": left_id,
                    "right_cell": right_id,
                    "intersection_pair_count": intersection,
                    "union_pair_count": union,
                    "jaccard_overlap": _rate(intersection, union),
                }
            )
    for model in _V2_MODELS:
        for prompt in evidence.manifest.formal_contract.prompt_variants[1:]:
            left_id = f"{prompt}::{model}"
            right_id = f"P0::{model}"
            intersection = len(pairs[left_id] & pairs[right_id])
            union = len(pairs[left_id] | pairs[right_id])
            rows.append(
                {
                    "comparison": "prompt_within_model",
                    "left_cell": left_id,
                    "right_cell": right_id,
                    "intersection_pair_count": intersection,
                    "union_pair_count": union,
                    "jaccard_overlap": _rate(intersection, union),
                }
            )
    return rows


def _percentile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _bootstrap(evidence: _PersistedEvidence, membership_by_user: Mapping[str, str]) -> dict[str, Any]:
    users = sorted(membership_by_user)
    contrast_specs: list[tuple[str, str, str, str]] = []
    baseline_model = "openai-codex/gpt-5.6-sol"
    for model in _V2_MODELS:
        if model != baseline_model:
            contrast_specs.append((f"model:{model}-vs-{baseline_model}", "model", model, baseline_model))
    for prompt in evidence.manifest.formal_contract.prompt_variants[1:]:
        contrast_specs.append((f"prompt:{prompt}-vs-P0", "prompt", prompt, "P0"))

    by_user: dict[str, list[_V2RealizedTerminal]] = defaultdict(list)
    for terminal in evidence.terminals:
        by_user[terminal.user_id].append(terminal)
    rng = random.Random(_BOOTSTRAP_SEED)
    estimates: dict[str, list[float]] = {spec[0]: [] for spec in contrast_specs}
    for _ in range(_BOOTSTRAP_ITERATIONS):
        sampled = [users[rng.randrange(len(users))] for _ in users]
        for contrast_id, factor, left, right in contrast_specs:
            left_positive = left_exposure = right_positive = right_exposure = 0
            for user_id in sampled:
                for terminal in by_user[user_id]:
                    value = terminal.requested_model if factor == "model" else terminal.prompt_variant
                    if value == left:
                        left_exposure += 1
                        left_positive += int(terminal.realized_engage)
                    elif value == right:
                        right_exposure += 1
                        right_positive += int(terminal.realized_engage)
            estimate = _rate(left_positive, left_exposure) - _rate(right_positive, right_exposure)
            estimates[contrast_id].append(estimate)
    observed = {row["contrast_id"]: row for row in _planned_contrasts(evidence)}
    return {
        "schema_version": "concurrent-robustness-realized-user-blocked-bootstrap-v2",
        "seed": _BOOTSTRAP_SEED,
        "iterations": _BOOTSTRAP_ITERATIONS,
        "block": "sample_user_id",
        "outcome": "realized_engagement_rate",
        "rows": [
            {
                "contrast_id": contrast_id,
                "observed_difference": observed[contrast_id]["realized_engagement_rate_difference"],
                "lower_95": round(_percentile(estimates[contrast_id], 0.025), 12),
                "upper_95": round(_percentile(estimates[contrast_id], 0.975), 12),
            }
            for contrast_id, *_ in contrast_specs
        ],
    }


def _realized_analysis_document(
    evidence: _PersistedEvidence,
    membership_by_user: Mapping[str, str],
) -> dict[str, Any]:
    group_rows = _realized_group_rows(evidence, membership_by_user)
    total = group_rows[0]
    if total["engagement_count"] != total["like_count"] + total["comment_count"] + total["share_count"]:
        raise ConcurrentRobustnessV2EvidenceError("Realized total action identity is crossed")
    return {
        "schema_version": CONCURRENT_ROBUSTNESS_REALIZED_ANALYSIS_V2_SCHEMA,
        "manifest_sha256": evidence.manifest_sha256,
        "execution_manifest_sha256": evidence.execution_manifest_sha256,
        "realization_source_identity": evidence.manifest.realization_source.source_identity,
        "primary_outcome": "abm_realized_engagement",
        "metric_contract": {
            "actions": ["like", "comment", "share", "ignore"],
            "engagement_identity": "like_count + comment_count + share_count = engagement_count",
            "denominator": "all validated Realized terminals including realized ignore",
            "rate": "engagement_count / exposure_count",
        },
        "formal_topology": {
            "cells": _V2_CELL_COUNT,
            "logical_judgments_per_cell": _V2_FORMAL_LOGICAL_PER_CELL,
            "logical_judgments": _V2_FORMAL_LOGICAL_CAP,
            "maximum_physical_attempts": _V2_FORMAL_PHYSICAL_CAP,
        },
        "realized_denominator": {
            "cells": _V2_CELL_COUNT,
            "logical_judgments_per_cell": evidence.manifest.request_caps.logical_judgments_per_cell,
            "logical_judgments": len(evidence.terminals),
            "exposures": len(evidence.terminals),
        },
        "group_rows": group_rows,
        "planned_contrasts": _planned_contrasts(evidence),
        "prompt_model_interactions": _prompt_model_interactions(evidence),
        "paired_overlap": _paired_overlap(evidence),
        "bootstrap": _bootstrap(evidence, membership_by_user),
        "practical_rate_threshold": _RATE_THRESHOLD,
        "conditional_scope": {
            "fixed_sample": True,
            "fixed_graph": True,
            "shared_deterministic_draw": True,
            "one_path_per_cell": True,
        },
    }


def _judgment_group_rows(
    evidence: _PersistedEvidence,
    membership_by_user: Mapping[str, str],
) -> list[dict[str, Any]]:
    source_rows: list[dict[str, Any]] = []
    for judgment in evidence.judgments:
        source_rows.append(
            {
                "requested_model": judgment.requested_model,
                "observed_model": judgment.observed_model,
                "prompt_variant": judgment.prompt_variant,
                "segment": membership_by_user[judgment.user_id],
                "message_id": judgment.message_id,
                "provider_action": judgment.provider_action,
                "provider_probability": judgment.provider_probability,
                "provider_confidence": judgment.provider_confidence,
                "request_invocations": judgment.request_invocations,
                "provider_response_count": judgment.provider_response_count,
                "usage_complete": judgment.usage_complete,
                "input_usage": judgment.input_usage,
                "output_usage": judgment.output_usage,
                "total_usage": judgment.total_usage,
                "cached_input_usage": judgment.cached_input_usage,
                "attempts": judgment.attempt_evidence,
            }
        )
    values = _dimension_values(evidence.manifest)
    result: list[dict[str, Any]] = []
    for scope, dimensions in _group_specs(evidence.manifest):
        for selection in _cartesian_rows(dimensions, values):
            rows = [row for row in source_rows if _matches(row, selection)]
            actions = Counter(str(row["provider_action"]) for row in rows)
            positive = sum(actions[action] for action in sorted(_POSITIVE_ACTIONS))
            attempts = [attempt for row in rows for attempt in cast(tuple[_V2AttemptEvidence, ...], row["attempts"])]
            observed_models = Counter(str(row["observed_model"]) for row in rows)
            requested_models = Counter(str(row["requested_model"]) for row in rows)
            routes = Counter(attempt.provider_route for attempt in attempts)
            billing = Counter(attempt.billing_semantics for attempt in attempts)
            cny_fee = sum(attempt.provider_fee_cny or 0.0 for attempt in attempts)
            nominal_usd = sum(attempt.subscription_nominal_cost_usd or 0.0 for attempt in attempts)
            input_tokens = sum(cast(int, row["input_usage"]) for row in rows if row["input_usage"] is not None)
            output_tokens = sum(cast(int, row["output_usage"]) for row in rows if row["output_usage"] is not None)
            total_tokens = sum(cast(int, row["total_usage"]) for row in rows if row["total_usage"] is not None)
            cached_tokens = sum(
                cast(int, row["cached_input_usage"])
                for row in rows
                if row["cached_input_usage"] is not None
            )
            result.append(
                {
                    "scope": scope,
                    "requested_model": selection.get("requested_model"),
                    "prompt_variant": selection.get("prompt_variant"),
                    "segment": selection.get("segment"),
                    "message_id": selection.get("message_id"),
                    "message_label": _MESSAGE_LABELS.get(selection.get("message_id", "")),
                    "provider_like_count": actions["like"],
                    "provider_comment_count": actions["comment"],
                    "provider_share_count": actions["share"],
                    "provider_ignore_count": actions["ignore"],
                    "positive_judgment_count": positive,
                    "logical_judgment_count": len(rows),
                    "positive_judgment_rate": _rate(positive, len(rows)),
                    "mean_probability": round(
                        sum(float(row["provider_probability"]) for row in rows) / len(rows), 12
                    )
                    if rows
                    else 0.0,
                    "mean_confidence": round(
                        sum(float(row["provider_confidence"]) for row in rows) / len(rows), 12
                    )
                    if rows
                    else 0.0,
                    "terminal_failure_count": 0,
                    "physical_attempt_count": sum(int(row["request_invocations"]) for row in rows),
                    "retry_attempt_count": sum(
                        1 for attempt in attempts if attempt.outcome == "retryable_failure"
                    ),
                    "provider_response_count": sum(int(row["provider_response_count"]) for row in rows),
                    "usage_complete_judgment_count": sum(bool(row["usage_complete"]) for row in rows),
                    "usage_missing_judgment_count": sum(not bool(row["usage_complete"]) for row in rows),
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": total_tokens,
                    "cached_input_tokens": cached_tokens,
                    "requested_model_counts": dict(sorted(requested_models.items())),
                    "observed_model_counts": dict(sorted(observed_models.items())),
                    "provider_route_counts": dict(sorted(routes.items())),
                    "billing_semantics_counts": dict(sorted(billing.items())),
                    "provider_fee_cny": round(cny_fee, 12),
                    "subscription_nominal_cost_usd_reference": round(nominal_usd, 12),
                }
            )
    return result


def _judgment_audit_document(
    evidence: _PersistedEvidence,
    membership_by_user: Mapping[str, str],
) -> dict[str, Any]:
    attempts = [attempt for judgment in evidence.judgments for attempt in judgment.attempt_evidence]
    cny_fee = sum(attempt.provider_fee_cny or 0.0 for attempt in attempts)
    if cny_fee > 25.0:
        raise ConcurrentRobustnessV2EvidenceError("DeepSeek CNY fee exceeds the independent ceiling")
    return {
        "schema_version": CONCURRENT_ROBUSTNESS_JUDGMENT_AUDIT_V2_SCHEMA,
        "manifest_sha256": evidence.manifest_sha256,
        "execution_manifest_sha256": evidence.execution_manifest_sha256,
        "scope": "provider_judgment_only",
        "counts": {
            "logical_judgments": len(evidence.judgments),
            "physical_attempts": evidence.physical_attempts,
            "provider_calls": evidence.provider_calls,
            "terminal_failures": 0,
        },
        "group_rows": _judgment_group_rows(evidence, membership_by_user),
        "accounting_contract": {
            "provider_routes": sorted(_V2_ATTEMPT_BILLING_PROFILES),
            "currency_rule": "CNY Provider fee and subscription nominal USD reference are not summed",
            "requested_and_observed_model_separate": True,
            "reason_and_confidence_belong_to_judgment": True,
        },
    }


def _claim_audit_document(evidence: _PersistedEvidence) -> dict[str, Any]:
    statements = [
        "Results are descriptive and conditional on the fixed sample, fixed graph, shared deterministic draw, and one path per cell.",
        "Differences below the declared practical threshold are labelled small observed difference only.",
        "Provider Judgment and ABM Realized outcomes remain separate evidence scopes.",
    ]
    forbidden = ("winner", "accuracy", "calibration", "causal", "external validity", "真实抖音")
    if any(token in statement.lower() for statement in statements for token in forbidden):
        raise ConcurrentRobustnessV2EvidenceError("claim audit contains a prohibited research claim")
    return {
        "schema_version": CONCURRENT_ROBUSTNESS_CLAIM_AUDIT_V2_SCHEMA,
        "status": "passed",
        "manifest_sha256": evidence.manifest_sha256,
        "statements": statements,
        "checked_statement_count": len(statements),
        "below_threshold_label": "small_observed_difference",
        "fixed_sample": True,
        "fixed_graph": True,
        "shared_deterministic_draw": True,
        "one_realized_path_per_cell": True,
        "ground_truth_used": False,
        "causal_claims_allowed": False,
        "external_platform_claims_allowed": False,
        "model_randomness_resolved": False,
    }


def _root_documents(
    evidence: _PersistedEvidence,
    membership: dict[str, Any],
) -> _RootDocuments:
    membership_by_user = _validate_membership_document(membership, evidence.manifest)
    return _RootDocuments(
        evidence=evidence,
        membership=membership,
        realized_analysis=_realized_analysis_document(evidence, membership_by_user),
        judgment_audit=_judgment_audit_document(evidence, membership_by_user),
        claim_audit=_claim_audit_document(evidence),
    )


def _validation_document(
    documents: _RootDocuments,
    artifact_payloads: Mapping[str, bytes],
) -> dict[str, Any]:
    evidence = documents.evidence
    return {
        "schema_version": CONCURRENT_ROBUSTNESS_STUDY_VALIDATION_V2_SCHEMA,
        "status": "complete",
        "manifest_sha256": evidence.manifest_sha256,
        "execution_manifest_sha256": evidence.execution_manifest_sha256,
        "source_manifest_sha256": evidence.manifest.source.manifest_sha256,
        "realization_source_identity": evidence.manifest.realization_source.source_identity,
        "counts": {
            "cells": _V2_CELL_COUNT,
            "logical_judgments_per_cell": evidence.manifest.request_caps.logical_judgments_per_cell,
            "logical_judgments": len(evidence.judgments),
            "realized_terminals": len(evidence.terminals),
            "physical_attempts": evidence.physical_attempts,
            "batch_commits": len(evidence.commits),
            "sample_users": evidence.manifest.sample.sample_size,
            "formal_cells": _V2_CELL_COUNT,
            "formal_logical_judgments_per_cell": _V2_FORMAL_LOGICAL_PER_CELL,
            "formal_logical_judgments": _V2_FORMAL_LOGICAL_CAP,
            "formal_maximum_physical_attempts": _V2_FORMAL_PHYSICAL_CAP,
        },
        "checks": {
            "independent_persisted_reread": True,
            "exact_twenty_cell_topology": True,
            "all_judgments_present": True,
            "all_realized_terminals_present": True,
            "all_batch_barriers_present": True,
            "pair_lifecycle_settled": True,
            "judgment_source_identities_recomputed": True,
            "realization_source_identity_recomputed": True,
            "realization_keys_and_draws_recomputed": True,
            "prompt_hashes_recomputed": True,
            "requested_observed_models_closed": True,
            "attempt_and_usage_accounting_closed": True,
            "feedback_recomputed": True,
            "artifact_hashes_closed": True,
            "provider_failures_zero": True,
            "claim_audit_passed": True,
            "source_unchanged": True,
        },
        "input_artifact_hashes": {
            name: _sha256_bytes(payload)
            for name, payload in sorted(artifact_payloads.items())
        },
        "provider_calls": evidence.provider_calls,
        "live_api_triggered": evidence.live_api_triggered,
        "production_deploy_eligible": False,
        "report_candidate": None,
    }


def _root_manifest_document(
    root_path: Path,
    evidence: _PersistedEvidence,
    payloads: Mapping[str, bytes],
) -> dict[str, Any]:
    hashes = {name: _sha256_bytes(payload) for name, payload in sorted(payloads.items())}
    return {
        "schema_version": CONCURRENT_ROBUSTNESS_STUDY_MANIFEST_V2_SCHEMA,
        "root_type": "immutable_closed_two_stage_study",
        "status": "complete",
        "study_root": str(root_path),
        "root_identity_sha256": _json_identity(hashes),
        "manifest_sha256": evidence.manifest_sha256,
        "source_manifest_sha256": evidence.manifest.source.manifest_sha256,
        "execution_manifest_sha256": evidence.execution_manifest_sha256,
        "realization_source_identity": evidence.manifest.realization_source.source_identity,
        "artifacts": sorted(hashes),
        "sha256": hashes,
        "counts": {
            "cell_count": _V2_CELL_COUNT,
            "logical_judgment_count": len(evidence.judgments),
            "realized_terminal_count": len(evidence.terminals),
            "physical_attempt_count": evidence.physical_attempts,
            "batch_commit_count": len(evidence.commits),
        },
        "provider_calls": evidence.provider_calls,
        "live_api_triggered": evidence.live_api_triggered,
        "production_deploy_eligible": False,
        "report_candidate": None,
    }


def _execution_paths(root: Path) -> dict[str, Path]:
    return {name: root / name for name in _EXECUTION_NAMES}


def _read_manifest(path: Path) -> tuple[ConcurrentRobustnessManifestV2, bytes]:
    payload, raw = _read_canonical_object(path, "v2 study manifest")
    try:
        manifest = ConcurrentRobustnessManifestV2.model_validate(payload)
    except ValueError as exc:
        raise ConcurrentRobustnessV2EvidenceError("v2 study manifest schema is invalid") from exc
    return manifest, raw


def _validate_workspace_documents(
    workspace: Path,
    manifest: ConcurrentRobustnessManifestV2,
    manifest_bytes: bytes,
) -> None:
    manifest_sha256 = _sha256_bytes(manifest_bytes)
    validation, validation_bytes = _read_canonical_object(
        workspace / "validation_report.json", "v2 workspace validation"
    )
    expected_validation = {
        "schema_version": "concurrent-robustness-v2-validation-v1",
        "status": "ready_for_execution",
        "manifest_sha256": manifest_sha256,
        "execution_profile": manifest.execution_profile,
        "counts": {
            "cells": len(manifest.prompt_model_cells),
            "messages": len(manifest.message_ids),
            "batches_per_cell": manifest.ranking_contract.horizon,
            "delivery_capacity_per_message": manifest.ranking_contract.delivery_capacity,
            "logical_judgments_per_cell": manifest.request_caps.logical_judgments_per_cell,
            "logical_judgment_cap": manifest.request_caps.logical_judgment_cap,
            "physical_attempt_cap": manifest.request_caps.physical_attempt_cap,
            "formal_cells": _V2_CELL_COUNT,
            "formal_logical_judgments_per_cell": _V2_FORMAL_LOGICAL_PER_CELL,
            "formal_logical_judgment_cap": _V2_FORMAL_LOGICAL_CAP,
            "formal_physical_attempt_cap": _V2_FORMAL_PHYSICAL_CAP,
        },
        "checks": {
            "exact_twenty_cell_topology": True,
            "canonical_prompt_hashes": True,
            "frozen_ranking_and_barrier": True,
            "shared_realization_source_closed": True,
            "provider_attempts_zero": True,
        },
        "provider_calls": 0,
        "live_api_triggered": False,
        "production_deploy_eligible": False,
    }
    if validation != expected_validation:
        raise ConcurrentRobustnessV2EvidenceError("v2 workspace validation is crossed")
    registry, _ = _read_canonical_object(workspace / "workspace_registry.json", "v2 workspace registry")
    expected_registry = {
        "schema_version": "concurrent-robustness-v2-workspace-registry-v1",
        "workspace_type": "private_resumable",
        "status": "ready_for_execution",
        "output_identity": manifest.output_identity,
        "output_root": str(workspace),
        "manifest_sha256": manifest_sha256,
        "realization_source_identity": manifest.realization_source.source_identity,
        "artifacts": {
            "study_manifest": "study_manifest.json",
            "validation_report": "validation_report.json",
        },
        "sha256": {
            "study_manifest": manifest_sha256,
            "validation_report": _sha256_bytes(validation_bytes),
        },
        "execution_directory": "two_stage_execution",
        "execution_anchor": "two_stage_execution/execution_anchor.json",
        "provider_calls": 0,
        "live_api_triggered": False,
        "production_deploy_eligible": False,
    }
    if registry != expected_registry:
        raise ConcurrentRobustnessV2EvidenceError("v2 workspace registry is crossed")


def _source_membership(manifest: ConcurrentRobustnessManifestV2) -> tuple[dict[str, Any], Any]:
    source_path = _resolve_source_path(manifest.source.source_dir)
    closure = close_concurrent_message_artifacts(source_path)
    try:
        _validate_source_against_manifest(manifest, closure, source_path)  # type: ignore[arg-type]
    except (KeyError, TypeError, ValueError) as exc:
        raise ConcurrentRobustnessV2EvidenceError("v2 frozen source is crossed with its manifest") from exc
    membership = _membership_document(manifest, closure.source_evidence.sample_manifest_rows)
    config = _dynamic_runtime_config(closure)
    prepared = _prepare_concurrent_runtime_inputs(config)
    prepared_identity = hashlib.sha256(
        json.dumps(
            prepared.cohort.sample_user_ids,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    message_ids = tuple(str(row["message_id"]) for row in closure.source_evidence.message_snapshot)
    expected_realization_source = _realization_source_payload(
        sample_identity=prepared_identity,
        graph_identity_sha256=_effective_graph_identity(prepared),
        message_ids=message_ids,
        message_snapshot_sha256=closure.artifact_hashes["message_snapshot.json"],
    )
    if (
        prepared_identity != manifest.sample.sample_identity
        or expected_realization_source != manifest.realization_source.model_dump(mode="json")
    ):
        raise ConcurrentRobustnessV2EvidenceError(
            "realization source identity is crossed with the independently rebuilt sample or graph"
        )
    _assert_source_unchanged(closure)
    return membership, closure


def _input_payloads(workspace: Path) -> dict[str, bytes]:
    execution = workspace / "two_stage_execution"
    if execution.is_symlink() or not execution.is_dir():
        raise ConcurrentRobustnessV2EvidenceError("closed execution directory is missing or unsafe")
    if {path.name for path in execution.iterdir()} != _V2_EXECUTION_FILES:
        raise ConcurrentRobustnessV2EvidenceError("closed execution directory has missing or extra artifacts")
    payloads = {_STUDY_MANIFEST: (workspace / _V2_WORKSPACE_MANIFEST).read_bytes()}
    payloads.update({name: (execution / name).read_bytes() for name in _EXECUTION_NAMES})
    return payloads


def _build_root_payloads(
    root_path: Path,
    workspace: Path,
    documents: _RootDocuments,
) -> dict[str, bytes]:
    payloads = _input_payloads(workspace)
    payloads[_SAMPLE_MEMBERSHIP] = _canonical_json_bytes(documents.membership)
    payloads[_REALIZED_ANALYSIS] = _canonical_json_bytes(documents.realized_analysis)
    payloads[_JUDGMENT_AUDIT] = _canonical_json_bytes(documents.judgment_audit)
    payloads[_CLAIM_AUDIT] = _canonical_json_bytes(documents.claim_audit)
    validation = _validation_document(documents, payloads)
    payloads[_VALIDATION] = _canonical_json_bytes(validation)
    payloads[_ROOT_MANIFEST] = _canonical_json_bytes(
        _root_manifest_document(root_path, documents.evidence, payloads)
    )
    return payloads


def _read_root_documents(root: Path) -> _RootDocuments:
    manifest, manifest_bytes = _read_manifest(root / _STUDY_MANIFEST)
    membership, _ = _read_canonical_object(root / _SAMPLE_MEMBERSHIP, "sample membership")
    membership_by_user = _validate_membership_document(membership, manifest)
    evidence = _validate_execution_documents(
        _execution_paths(root),
        manifest,
        manifest_bytes,
        membership_by_user,
    )
    return _root_documents(evidence, membership)


def _validate_root(
    root: Path,
    *,
    declared_root_path: Path | None = None,
    expected_payloads: Mapping[str, bytes] | None = None,
) -> ConcurrentRobustnessV2StudyFacts:
    if root.is_symlink() or not root.is_dir():
        raise ConcurrentRobustnessV2EvidenceError("v2 study root must be a real directory")
    entries = {path.name: path for path in root.iterdir()}
    if set(entries) != _ROOT_FILES or any(path.is_symlink() or not path.is_file() for path in entries.values()):
        raise ConcurrentRobustnessV2EvidenceError("v2 study root has missing, extra, or non-regular artifacts")
    documents = _read_root_documents(root)
    evidence = documents.evidence
    rebuilt: dict[str, bytes] = {
        _STUDY_MANIFEST: entries[_STUDY_MANIFEST].read_bytes(),
        **{name: entries[name].read_bytes() for name in _EXECUTION_NAMES},
        _SAMPLE_MEMBERSHIP: _canonical_json_bytes(documents.membership),
        _REALIZED_ANALYSIS: _canonical_json_bytes(documents.realized_analysis),
        _JUDGMENT_AUDIT: _canonical_json_bytes(documents.judgment_audit),
        _CLAIM_AUDIT: _canonical_json_bytes(documents.claim_audit),
    }
    rebuilt[_VALIDATION] = _canonical_json_bytes(_validation_document(documents, rebuilt))
    final_root = declared_root_path or root
    rebuilt[_ROOT_MANIFEST] = _canonical_json_bytes(_root_manifest_document(final_root, evidence, rebuilt))
    for name, payload in rebuilt.items():
        if entries[name].read_bytes() != payload:
            raise ConcurrentRobustnessV2EvidenceError(f"v2 study artifact is not reproducible: {name}")
    if expected_payloads is not None and dict(expected_payloads) != rebuilt:
        raise ConcurrentRobustnessV2EvidenceConflictError("existing v2 study root is crossed with its workspace")
    root_manifest, _ = _read_canonical_object(entries[_ROOT_MANIFEST], "v2 root manifest")
    root_identity = root_manifest.get("root_identity_sha256")
    if not isinstance(root_identity, str) or not _HASH_PATTERN.fullmatch(root_identity):
        raise ConcurrentRobustnessV2EvidenceError("v2 root identity is invalid")
    return ConcurrentRobustnessV2StudyFacts(
        root_path=final_root,
        manifest_sha256=evidence.manifest_sha256,
        root_identity_sha256=root_identity,
        logical_judgments=len(evidence.judgments),
        physical_attempts=evidence.physical_attempts,
        provider_calls=evidence.provider_calls,
        live_api_triggered=evidence.live_api_triggered,
    )


def _read_closed_concurrent_robustness_v2_study(
    root_path: str | Path,
) -> ConcurrentRobustnessV2StudyFacts:
    root = _real_directory(Path(root_path), "v2 study root")
    return _validate_root(root)


def _close_concurrent_robustness_v2_study(
    workspace_path: str | Path,
) -> ConcurrentRobustnessV2StudyFacts:
    workspace = _real_directory(Path(workspace_path), "v2 study workspace")
    if {path.name for path in workspace.iterdir()} != {
        "study_manifest.json",
        "validation_report.json",
        "workspace_registry.json",
        "two_stage_execution",
    }:
        raise ConcurrentRobustnessV2EvidenceError("v2 workspace is partial or contains unexpected entries")
    source_snapshot = _snapshot_tree(workspace)
    manifest, manifest_bytes = _read_manifest(workspace / _STUDY_MANIFEST)
    _validate_workspace_documents(workspace, manifest, manifest_bytes)
    membership, source_closure = _source_membership(manifest)
    membership_by_user = _validate_membership_document(membership, manifest)
    evidence = _validate_execution_documents(
        _execution_paths(workspace / "two_stage_execution"),
        manifest,
        manifest_bytes,
        membership_by_user,
    )
    documents = _root_documents(evidence, membership)
    root_path = workspace.with_name(f"{workspace.name}{_STUDY_ROOT_SUFFIX}")
    payloads = _build_root_payloads(root_path, workspace, documents)
    if _snapshot_tree(workspace) != source_snapshot:
        raise ConcurrentRobustnessV2EvidenceError("v2 workspace mutated during Evidence closure")
    _assert_source_unchanged(source_closure)

    if root_path.exists() or root_path.is_symlink():
        facts = _validate_root(root_path, expected_payloads=payloads)
        if _snapshot_tree(workspace) != source_snapshot:
            raise ConcurrentRobustnessV2EvidenceError("v2 workspace mutated during repeated validation")
        _assert_source_unchanged(source_closure)
        return facts

    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{root_path.name}.{manifest.output_identity}.",
            suffix=".staging",
            dir=root_path.parent,
        )
    )
    try:
        for name, payload in payloads.items():
            (staging / name).write_bytes(payload)
        (staging / _EXECUTION_ANCHOR).chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        _validate_root(staging, declared_root_path=root_path, expected_payloads=payloads)
        if _snapshot_tree(workspace) != source_snapshot:
            raise ConcurrentRobustnessV2EvidenceError("v2 workspace mutated during root staging")
        _assert_source_unchanged(source_closure)
        if root_path.exists() or root_path.is_symlink():
            raise ConcurrentRobustnessV2EvidenceConflictError("v2 study root appeared during atomic install")
        os.replace(staging, root_path)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    facts = _validate_root(root_path, expected_payloads=payloads)
    if _snapshot_tree(workspace) != source_snapshot:
        raise ConcurrentRobustnessV2EvidenceError("v2 workspace mutated during atomic closure")
    _assert_source_unchanged(source_closure)
    return facts


def read_closed_concurrent_robustness_v2_study(
    root_path: str | Path,
) -> ConcurrentRobustnessV2StudyFacts:
    """Independently rebuild all v2 facts from one immutable persisted root."""

    try:
        return _read_closed_concurrent_robustness_v2_study(root_path)
    except ConcurrentRobustnessV2EvidenceError:
        raise
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ConcurrentRobustnessV2EvidenceError(
            "immutable v2 study root failed independent evidence validation"
        ) from exc


def close_concurrent_robustness_v2_study(
    workspace_path: str | Path,
) -> ConcurrentRobustnessV2StudyFacts:
    """Close one complete v2 execution without accepting caller-provided summaries."""

    try:
        return _close_concurrent_robustness_v2_study(workspace_path)
    except ConcurrentRobustnessV2EvidenceError:
        raise
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ConcurrentRobustnessV2EvidenceError(
            "persisted v2 execution failed independent evidence closure"
        ) from exc
