from __future__ import annotations

import hashlib
import html
import json
import math
import os
import re
import shutil
import stat
import tempfile
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

from .concurrent_message_experiment import CONCURRENT_MESSAGE_POSITIVE_ACTIONS
from .concurrent_message_mechanism_presentation import _MECHANISM_PRESENTATION
from .full_pool_formal_experiment import (
    FULL_POOL_PRODUCTION_CANDIDATE_ROWS,
    FULL_POOL_PRODUCTION_CAPACITY,
    FULL_POOL_PRODUCTION_ELIGIBLE_PAIRS,
    FULL_POOL_PRODUCTION_FINAL_BATCH_PAIRS_PER_MESSAGE,
    FULL_POOL_PRODUCTION_HORIZON,
    FULL_POOL_PRODUCTION_USER_COUNT,
    _ClosedFullPoolSource,
)
from .full_pool_source_v3 import (
    FULL_POOL_RESULT_CSV,
    FULL_POOL_RESULT_LINEAGE_MARKDOWN,
    FULL_POOL_SOURCE_V3_SCHEMA,
    AutomatedFullPoolSourceFacts,
    FullPoolResultProjection,
    compose_full_pool_result_projection,
)
from .full_pool_source_v4 import (
    FULL_POOL_SOURCE_V4_SCHEMA,
    STRICT_FULL_POOL_RESULT_PROJECTION_SCHEMA_V1,
    STRICT_FULL_POOL_RESULT_PROJECTION_SCHEMA_V2,
    StrictFullPoolSourceFacts,
    compose_strict_full_pool_result_projection,
)
from .full_pool_two_stage_replay import (
    FULL_POOL_TWO_STAGE_FORMAL_CLASSIFICATION,
    FULL_POOL_TWO_STAGE_SOURCE_SCHEMA,
    ClosedFullPoolTwoStageSource,
)

_TRACE_INDEX_SCHEMA = "full-pool-trace-index-v1"
_TRACE_PARTITION_SCHEMA = "full-pool-trace-partition-v1"
_TWO_STAGE_TRACE_SEMANTICS = "two_stage_realized"
_HISTORICAL_DIR = "historical-1000"
_FULL_POOL_SOURCE_DIR = "full-pool-source"
_TRACE_INDEX_PATH = "trace/full-pool-trace-index.json"
_FULL_POOL_MASTER = "full-pool-mechanism.mmd"
_MAX_REPORT_HTML_BYTES = 3 * 1024 * 1024
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_HISTORICAL_MERMAID_FILENAMES = (
    "mechanism-sample-first.mmd",
    "mechanism-pair-formation.mmd",
    "mechanism-independent-delivery.mmd",
    "mechanism-exposure-decisions.mmd",
    "mechanism-feedback-boundary.mmd",
    "real-batch-mechanism.mmd",
    "prompt-model-factorial.mmd",
)
_TRACE_ROW_FIELDS = (
    "terminal_row_id",
    "pair_id",
    "pair_schedule_position",
    "time_step",
    "message_id",
    "message_title",
    "user_id",
    "decision_variant",
    "prompt_version",
    "context_source_key",
    "context_profile_payload",
    "peer_context_payload",
    "prompt_field_inclusion",
    "terminal_status",
    "provider_status",
    "engage",
    "probability",
    "confidence",
    "action",
    "reason",
    "decision_source",
    "failure_type",
    "provider_metadata",
    "request_invocations",
    "provider_response_count",
    "successful_decision_count",
    "observed_model_counts",
    "usage_complete",
    "input_usage",
    "output_usage",
    "total_usage",
    "cached_input_usage",
    "selection_reason",
    "is_seed",
    "ranking_position",
    "base_network_relevance",
    "campaign_engaged_neighbor_count",
    "campaign_engaged_neighbor_signal",
    "raw_message_user_fit",
    "normalized_message_user_fit",
    "personalized_delivery_score",
    "campaign_feedback_committed",
)
_MESSAGE_IDS = ("message_1", "message_2", "message_3")
_MESSAGE_CODES = {"message_1": "M1", "message_2": "M2", "message_3": "M3"}
_SEGMENT_CODES = {"class_1": "S1", "class_2": "S2", "class_3": "S3"}
_RESULT_ACTIONS = ("like", "comment", "share", "ignore")

_PAIR_TRACE_FIELDS = (
    "message_title",
    "selection_reason",
    "is_seed",
    "ranking_position",
    "base_network_relevance",
    "campaign_engaged_neighbor_count",
    "campaign_engaged_neighbor_signal",
    "raw_message_user_fit",
    "normalized_message_user_fit",
    "personalized_delivery_score",
    "campaign_feedback_committed",
)


class _FullPoolPresentationError(ValueError):
    pass


@dataclass(frozen=True)
class _TraceProjection:
    index_payload: bytes
    index_sha256: str
    batch_summaries: tuple[Mapping[str, object], ...]
    message_summaries: tuple[Mapping[str, object], ...]


@dataclass(frozen=True)
class _RealizedPresentationProjection:
    trace: _TraceProjection
    overall: Mapping[str, object]
    message_summaries: tuple[Mapping[str, object], ...]
    segment_summaries: tuple[Mapping[str, object], ...]
    segment_message_summaries: tuple[Mapping[str, object], ...]
    batch_summaries: tuple[Mapping[str, object], ...]
    feedback_summaries: tuple[Mapping[str, object], ...]
    provider_action_counts: Mapping[str, int]
    realized_action_counts: Mapping[str, int]


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_bytes(value: object) -> bytes:
    return (_canonical_json(value) + "\n").encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    _require_regular_file(path, path.name)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_regular_file(path: Path, context: str) -> None:
    if path.is_symlink():
        raise _FullPoolPresentationError(f"{context} must not be a symlink")
    try:
        mode = path.stat(follow_symlinks=False).st_mode
    except FileNotFoundError as exc:
        raise _FullPoolPresentationError(f"{context} is missing") from exc
    if not stat.S_ISREG(mode):
        raise _FullPoolPresentationError(f"{context} must be a regular file")


def _require_real_directory(path: Path, context: str) -> Path:
    if ".." in path.parts or path.is_symlink():
        raise _FullPoolPresentationError(f"{context} is unsafe")
    try:
        absolute = Path(os.path.abspath(path))
        resolved = path.resolve(strict=True)
        mode = path.stat(follow_symlinks=False).st_mode
    except (FileNotFoundError, OSError) as exc:
        raise _FullPoolPresentationError(f"{context} is missing or cannot be resolved") from exc
    if absolute != resolved or not stat.S_ISDIR(mode):
        raise _FullPoolPresentationError(f"{context} must be one real directory")
    return resolved


def _file_hashes(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise _FullPoolPresentationError(f"artifact inventory contains a symlink: {relative}")
        mode = path.stat(follow_symlinks=False).st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise _FullPoolPresentationError(f"artifact inventory contains a non-regular file: {relative}")
        hashes[relative] = _sha256_file(path)
    return hashes


def _copy_tree_exact(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, copy_function=shutil.copyfile)
    if _file_hashes(destination) != _file_hashes(source):
        raise _FullPoolPresentationError("copied immutable source bytes changed")


def _strict_int(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _FullPoolPresentationError(f"{context} must be a non-negative integer")
    return value


def _strict_mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _FullPoolPresentationError(f"{context} must be an object")
    return cast(Mapping[str, object], value)


def _strict_rows(value: object, context: str) -> Sequence[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise _FullPoolPresentationError(f"{context} must be an array")
    rows: list[Mapping[str, object]] = []
    for row in value:
        if not isinstance(row, Mapping):
            raise _FullPoolPresentationError(f"{context} contains a non-object row")
        rows.append(cast(Mapping[str, object], row))
    return rows


def _non_empty_string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise _FullPoolPresentationError(f"{context} must be a non-empty string")
    return value


def _source_schema(source: Any) -> object:
    schema = source.manifest.get("source_schema_version")
    return source.manifest.get("schema_version") if schema is None else schema


def _source_contract_sha256(source: Any) -> object:
    contract_sha256 = source.manifest.get("contract_sha256")
    return source.manifest.get("provider_contract_sha256") if contract_sha256 is None else contract_sha256


def _identity_sha256(terminal_ids: Sequence[str]) -> str:
    return _sha256_bytes(_canonical_json(list(terminal_ids)).encode("utf-8"))


def _report_safe_trace_row(
    terminal: Mapping[str, object],
    pair: Mapping[str, object],
) -> dict[str, object]:
    row: dict[str, object] = {}
    for field_name in _TRACE_ROW_FIELDS:
        if field_name in _PAIR_TRACE_FIELDS:
            if field_name not in pair:
                raise _FullPoolPresentationError(f"persisted pair row is missing trace field {field_name}")
            row[field_name] = pair[field_name]
        else:
            if field_name not in terminal:
                raise _FullPoolPresentationError(f"persisted terminal row is missing trace field {field_name}")
            row[field_name] = terminal[field_name]
    if row["decision_variant"] != "primary":
        raise _FullPoolPresentationError("Full-Pool trace contains a non-Primary terminal")
    if (
        row["pair_id"] != pair.get("pair_id")
        or row["user_id"] != pair.get("user_id")
        or row["message_id"] != pair.get("message_id")
        or row["time_step"] != pair.get("time_step")
    ):
        raise _FullPoolPresentationError("terminal and pair identities are crossed")
    return row


def _trace_projection(
    source: _ClosedFullPoolSource,
    *,
    partition_sink: Callable[[str, bytes], None],
) -> _TraceProjection:
    contract = source.contract
    entries: dict[tuple[str, int], dict[str, object]] = {}
    identities: dict[tuple[str, int], tuple[str, ...]] = {}
    batch_summaries: list[dict[str, object]] = []
    message_totals: dict[str, dict[str, object]] = {
        message_id: {
            "message_id": message_id,
            "message_title": message_id,
            "exposures": 0,
            "successful_primary_decisions": 0,
            "provider_failures": 0,
            "positive_actions": 0,
            "action_counts": Counter[str](),
        }
        for message_id in contract.message_ids
    }
    all_terminal_ids: set[str] = set()
    cumulative_by_message: dict[str, Counter[str]] = {message_id: Counter() for message_id in contract.message_ids}

    for expected_time_step in range(contract.horizon):
        batch = source.read_batch(expected_time_step)
        if batch.get("time_step") != expected_time_step:
            raise _FullPoolPresentationError("Full-Pool batch order is crossed")
        rows = _strict_mapping(batch.get("rows"), "Full-Pool batch rows")
        pair_rows = _strict_rows(rows.get("pair_rows"), "Full-Pool pair rows")
        terminal_rows = _strict_rows(rows.get("terminal_rows"), "Full-Pool terminal rows")
        pairs_by_id: dict[str, Mapping[str, object]] = {}
        for pair in pair_rows:
            pair_id = _non_empty_string(pair.get("pair_id"), "pair_id")
            if pair_id in pairs_by_id:
                raise _FullPoolPresentationError("Full-Pool batch duplicates pair_id")
            pairs_by_id[pair_id] = pair
        terminals_by_message: dict[str, list[dict[str, object]]] = {
            message_id: [] for message_id in contract.message_ids
        }
        for terminal in terminal_rows:
            pair_id = _non_empty_string(terminal.get("pair_id"), "terminal pair_id")
            try:
                pair = pairs_by_id[pair_id]
            except KeyError as exc:
                raise _FullPoolPresentationError("Full-Pool terminal has no matching persisted pair") from exc
            trace_row = _report_safe_trace_row(terminal, pair)
            terminal_id = _non_empty_string(trace_row.get("terminal_row_id"), "terminal_row_id")
            if terminal_id in all_terminal_ids:
                raise _FullPoolPresentationError("Full-Pool trace duplicates terminal identity")
            all_terminal_ids.add(terminal_id)
            message_id = _non_empty_string(trace_row.get("message_id"), "message_id")
            if message_id not in terminals_by_message:
                raise _FullPoolPresentationError("Full-Pool trace contains an unknown message")
            terminals_by_message[message_id].append(trace_row)

        if set(pairs_by_id) != {_non_empty_string(row.get("pair_id"), "terminal pair_id") for row in terminal_rows}:
            raise _FullPoolPresentationError("Full-Pool pair and terminal denominators do not match")

        for message_id in contract.message_ids:
            partition_rows = terminals_by_message[message_id]
            expected_row_count = (
                contract.per_message_capacity
                if expected_time_step < contract.horizon - 1
                else contract.expected_final_batch_pairs_per_message
            )
            if len(partition_rows) != expected_row_count:
                raise _FullPoolPresentationError("Full-Pool trace partition does not close delivery capacity")
            terminal_ids = tuple(_non_empty_string(row["terminal_row_id"], "terminal_row_id") for row in partition_rows)
            terminal_identity = _identity_sha256(terminal_ids)
            relative_path = f"trace/{message_id}/batch-{expected_time_step:06d}.json"
            partition = {
                "schema_version": _TRACE_PARTITION_SCHEMA,
                "source_identity": source.source_identity,
                "source_manifest_sha256": source.manifest_sha256,
                "message_id": message_id,
                "time_step": expected_time_step,
                "row_count": len(partition_rows),
                "terminal_identity_sha256": terminal_identity,
                "rows": partition_rows,
            }
            payload = _json_bytes(partition)
            partition_sink(relative_path, payload)
            entry = {
                "message_id": message_id,
                "time_step": expected_time_step,
                "relative_path": relative_path,
                "sha256": _sha256_bytes(payload),
                "bytes": len(payload),
                "row_count": len(partition_rows),
                "terminal_identity_sha256": terminal_identity,
            }
            entries[(message_id, expected_time_step)] = entry
            identities[(message_id, expected_time_step)] = terminal_ids

            successful = sum(row["terminal_status"] == "succeeded" for row in partition_rows)
            provider_failures = sum(row["terminal_status"] == "provider_failed" for row in partition_rows)
            positives = sum(
                row["terminal_status"] == "succeeded" and row["action"] in CONCURRENT_MESSAGE_POSITIVE_ACTIONS
                for row in partition_rows
            )
            action_counts = Counter(
                str(row["action"]) for row in partition_rows if row["terminal_status"] == "succeeded"
            )
            cumulative = cumulative_by_message[message_id]
            cumulative.update(
                {
                    "exposures": len(partition_rows),
                    "successful_primary_decisions": successful,
                    "provider_failures": provider_failures,
                    "positive_actions": positives,
                }
            )
            total = message_totals[message_id]
            if partition_rows:
                total["message_title"] = str(partition_rows[0]["message_title"])
            total["exposures"] = cast(int, total["exposures"]) + len(partition_rows)
            total["successful_primary_decisions"] = cast(int, total["successful_primary_decisions"]) + successful
            total["provider_failures"] = cast(int, total["provider_failures"]) + provider_failures
            total["positive_actions"] = cast(int, total["positive_actions"]) + positives
            cast(Counter[str], total["action_counts"]).update(action_counts)
            batch_summaries.append(
                {
                    "message_id": message_id,
                    "time_step": expected_time_step,
                    "exposures": len(partition_rows),
                    "successful_primary_decisions": successful,
                    "provider_failures": provider_failures,
                    "positive_actions": positives,
                    "exposure_engagement_rate": (positives / len(partition_rows) if partition_rows else 0.0),
                    "decision_engagement_rate": (positives / successful if successful else 0.0),
                    "cumulative_exposures": cumulative["exposures"],
                    "cumulative_positive_actions": cumulative["positive_actions"],
                }
            )

    ordered_entries = [
        entries[(message_id, time_step)] for message_id in contract.message_ids for time_step in range(contract.horizon)
    ]
    ordered_terminal_ids = [
        terminal_id
        for message_id in contract.message_ids
        for time_step in range(contract.horizon)
        for terminal_id in identities[(message_id, time_step)]
    ]
    if len(all_terminal_ids) != contract.expected_primary_terminals:
        raise _FullPoolPresentationError("Full-Pool trace does not cover every persisted terminal identity")
    index = {
        "schema_version": _TRACE_INDEX_SCHEMA,
        "source_schema_version": _source_schema(source),
        "source_identity": source.source_identity,
        "source_manifest_sha256": source.manifest_sha256,
        "contract_sha256": _source_contract_sha256(source),
        "message_order": list(contract.message_ids),
        "batch_order": list(range(contract.horizon)),
        "terminal_count": len(ordered_terminal_ids),
        "terminal_identity_sha256": _identity_sha256(ordered_terminal_ids),
        "partition_count": len(ordered_entries),
        "partitions": ordered_entries,
    }
    index_payload = _json_bytes(index)

    summaries: list[dict[str, object]] = []
    for message_id in contract.message_ids:
        total = message_totals[message_id]
        exposures = cast(int, total["exposures"])
        successful = cast(int, total["successful_primary_decisions"])
        positives = cast(int, total["positive_actions"])
        summaries.append(
            {
                "message_id": message_id,
                "message_title": total["message_title"],
                "exposures": exposures,
                "successful_primary_decisions": successful,
                "provider_failures": total["provider_failures"],
                "positive_actions": positives,
                "action_counts": dict(sorted(cast(Counter[str], total["action_counts"]).items())),
                "exposure_engagement_rate": positives / exposures if exposures else 0.0,
                "decision_engagement_rate": positives / successful if successful else 0.0,
            }
        )
    return _TraceProjection(
        index_payload=index_payload,
        index_sha256=_sha256_bytes(index_payload),
        batch_summaries=tuple(batch_summaries),
        message_summaries=tuple(summaries),
    )


def _strict_float(value: object, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _FullPoolPresentationError(f"{context} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise _FullPoolPresentationError(f"{context} must be finite")
    return result


def _strict_string_sequence(value: object, context: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise _FullPoolPresentationError(f"{context} must be an array")
    result = tuple(_non_empty_string(item, context) for item in value)
    if len(result) != len(set(result)):
        raise _FullPoolPresentationError(f"{context} must not contain duplicates")
    return result


def _new_realized_counter() -> dict[str, int | float]:
    return {
        "exposures": 0,
        "provider_positive_judgments": 0,
        "provider_probability_sum": 0.0,
        "effective_gate_probability_sum": 0.0,
        "like": 0,
        "comment": 0,
        "share": 0,
        "ignore": 0,
    }


def _update_realized_counter(
    counter: dict[str, int | float],
    terminal: Mapping[str, object],
) -> None:
    provider_engage = terminal.get("provider_engage")
    realized_engage = terminal.get("realized_engage")
    if not isinstance(provider_engage, bool) or not isinstance(realized_engage, bool):
        raise _FullPoolPresentationError("realized trace engage fields must be booleans")
    probability = _strict_float(
        terminal.get("provider_probability"),
        "Provider Judgment probability",
    )
    if probability < 0.0 or probability > 1.0:
        raise _FullPoolPresentationError("Provider Judgment probability is outside [0, 1]")
    action = _non_empty_string(terminal.get("realized_action"), "realized action")
    if action not in _RESULT_ACTIONS or realized_engage is not (action != "ignore"):
        raise _FullPoolPresentationError("realized action and engage fields are crossed")
    counter["exposures"] = cast(int, counter["exposures"]) + 1
    counter["provider_probability_sum"] = (
        cast(float, counter["provider_probability_sum"]) + probability
    )
    if provider_engage:
        counter["provider_positive_judgments"] = (
            cast(int, counter["provider_positive_judgments"]) + 1
        )
        counter["effective_gate_probability_sum"] = (
            cast(float, counter["effective_gate_probability_sum"]) + probability
        )
    counter[action] = cast(int, counter[action]) + 1


def _finish_realized_counter(
    counter: Mapping[str, int | float],
    **dimensions: object,
) -> dict[str, object]:
    exposures = _strict_int(counter.get("exposures"), "realized summary exposures")
    action_counts = {
        action: _strict_int(counter.get(action), f"realized summary {action}")
        for action in _RESULT_ACTIONS
    }
    engagements = sum(action_counts[action] for action in ("like", "comment", "share"))
    if engagements + action_counts["ignore"] != exposures:
        raise _FullPoolPresentationError("realized summary actions do not close exposure")
    probability_sum = _strict_float(
        counter.get("provider_probability_sum"),
        "raw Provider probability sum",
    )
    effective_sum = _strict_float(
        counter.get("effective_gate_probability_sum"),
        "effective gate probability sum",
    )
    return {
        **dimensions,
        "exposures": exposures,
        "provider_positive_judgments": _strict_int(
            counter.get("provider_positive_judgments"),
            "provider positive judgments",
        ),
        "action_counts": action_counts,
        "realized_engagements": engagements,
        "realized_engagement_rate": engagements / exposures if exposures else 0.0,
        "raw_provider_probability_mean": probability_sum / exposures if exposures else 0.0,
        "effective_gate_expectation": effective_sum / exposures if exposures else 0.0,
    }


def _realized_trace_row(
    pair: Mapping[str, object],
    terminal: Mapping[str, object],
) -> dict[str, object]:
    time_step = _strict_int(terminal.get("replay_time_step"), "realized trace time_step")
    message_id = _non_empty_string(terminal.get("message_id"), "realized trace message_id")
    user_id = _non_empty_string(terminal.get("user_id"), "realized trace user_id")
    provider_reason = _non_empty_string(
        terminal.get("provider_reason"),
        "Provider Judgment reason",
    )
    provider_probability = _strict_float(
        terminal.get("provider_probability"),
        "Provider Judgment probability",
    )
    uniform_draw = terminal.get("uniform_draw")
    if uniform_draw is not None:
        uniform_draw = _strict_float(uniform_draw, "realization draw")
    provider_judgment = {
        "engage": terminal.get("provider_engage"),
        "probability": provider_probability,
        "action": terminal.get("provider_action"),
        "reason": provider_reason,
        "confidence": terminal.get("provider_confidence"),
        "decision_source": terminal.get("provider_decision_source"),
        "reason_role": "provider_judgment_engagement_intent",
    }
    realization = {
        "rule_version": terminal.get("realization_rule_version"),
        "seed": terminal.get("realization_seed"),
        "status": terminal.get("realization_status"),
        "uniform_draw": uniform_draw,
        "engage": terminal.get("realized_engage"),
        "action": terminal.get("realized_action"),
    }
    row = {
        "terminal_row_id": terminal.get("realized_terminal_id"),
        "pair_id": terminal.get("replay_pair_id"),
        "pair_schedule_position": terminal.get("replay_pair_schedule_position"),
        "time_step": time_step,
        "message_id": message_id,
        "message_title": pair.get("message_title"),
        "user_id": user_id,
        "decision_variant": "primary",
        "prompt_version": terminal.get("prompt_version"),
        "terminal_status": "succeeded",
        "provider_status": "succeeded",
        "engage": terminal.get("realized_engage"),
        "probability": provider_probability,
        "confidence": terminal.get("provider_confidence"),
        "action": terminal.get("realized_action"),
        "reason": provider_reason,
        "reason_role": "provider_judgment_engagement_intent",
        "decision_source": terminal.get("provider_decision_source"),
        "latent_class": pair.get("latent_class"),
        "selection_reason": pair.get("selection_reason"),
        "is_seed": pair.get("is_seed"),
        "ranking_position": pair.get("ranking_position"),
        "base_network_relevance": pair.get("base_network_relevance"),
        "campaign_engaged_neighbor_count": pair.get("campaign_engaged_neighbor_count"),
        "campaign_engaged_neighbor_signal": pair.get("campaign_engaged_neighbor_signal"),
        "raw_message_user_fit": pair.get("raw_message_user_fit"),
        "normalized_message_user_fit": pair.get("normalized_message_user_fit"),
        "personalized_delivery_score": pair.get("personalized_delivery_score"),
        "campaign_feedback_committed": pair.get("campaign_feedback_committed"),
        "upstream_source_identity": terminal.get("upstream_source_identity"),
        "upstream_terminal_row_id": terminal.get("upstream_terminal_row_id"),
        "provider_judgment": provider_judgment,
        "abm_realization": realization,
    }
    if "realized_reason" in row or "realized_reason" in realization:
        raise _FullPoolPresentationError("ABM realization must not create realized_reason")
    return row


def _realized_trace_projection(
    source: ClosedFullPoolTwoStageSource,
    *,
    partition_sink: Callable[[str, bytes], None],
) -> _RealizedPresentationProjection:
    horizon = source.horizon
    if source.message_ids != _MESSAGE_IDS or horizon <= 0:
        raise _FullPoolPresentationError("realized source message order or horizon is crossed")

    expected_partition_counts: Counter[tuple[str, int]] = Counter()
    expected_cells: dict[tuple[str, str], Counter[str]] = {
        (segment, message_id): Counter()
        for segment in _SEGMENT_CODES.values()
        for message_id in _MESSAGE_IDS
    }
    code_to_message = {code: message_id for message_id, code in _MESSAGE_CODES.items()}
    for row in source.projection_rows:
        run = _strict_int(row.get("Run"), "realized projection Run")
        if run < 1 or run > horizon:
            raise _FullPoolPresentationError("realized projection Run is outside the source horizon")
        message_code = _non_empty_string(row.get("Message"), "realized projection Message")
        segment = _non_empty_string(row.get("Segment"), "realized projection Segment")
        if message_code not in code_to_message or segment not in _SEGMENT_CODES.values():
            raise _FullPoolPresentationError("realized projection group is crossed")
        message_id = code_to_message[message_code]
        exposure = _strict_int(row.get("Exposure"), "realized projection Exposure")
        expected_partition_counts[(message_id, run - 1)] += exposure
        cell = expected_cells[(segment, message_id)]
        cell["exposures"] += exposure
        cell["like"] += _strict_int(row.get("Total Likes"), "realized projection likes")
        cell["comment"] += _strict_int(row.get("Total Comments"), "realized projection comments")
        cell["share"] += _strict_int(row.get("Total Shares"), "realized projection shares")
    if set(expected_partition_counts) != {
        (message_id, time_step)
        for message_id in _MESSAGE_IDS
        for time_step in range(horizon)
    }:
        raise _FullPoolPresentationError("realized projection partitions are incomplete")

    overall = _new_realized_counter()
    messages = {message_id: _new_realized_counter() for message_id in _MESSAGE_IDS}
    segments = {segment: _new_realized_counter() for segment in _SEGMENT_CODES.values()}
    cells = {
        (segment, message_id): _new_realized_counter()
        for segment in _SEGMENT_CODES.values()
        for message_id in _MESSAGE_IDS
    }
    batches = {
        (time_step, message_id): _new_realized_counter()
        for time_step in range(horizon)
        for message_id in _MESSAGE_IDS
    }
    message_titles = {message_id: message_id for message_id in _MESSAGE_IDS}
    provider_actions: Counter[str] = Counter()
    realized_actions: Counter[str] = Counter()
    entries: dict[tuple[str, int], dict[str, object]] = {}
    identities: dict[tuple[str, int], tuple[str, ...]] = {}
    all_terminal_ids: set[str] = set()
    batch_rows: dict[str, list[dict[str, object]]] = {
        message_id: [] for message_id in _MESSAGE_IDS
    }
    current_step = 0
    saw_row = False

    def flush(time_step: int) -> None:
        for message_id in _MESSAGE_IDS:
            rows = batch_rows[message_id]
            expected = expected_partition_counts[(message_id, time_step)]
            if len(rows) != expected:
                raise _FullPoolPresentationError(
                    "realized trace partition does not close source projection exposure"
                )
            terminal_ids = tuple(
                _non_empty_string(row.get("terminal_row_id"), "realized terminal identity")
                for row in rows
            )
            terminal_identity = _identity_sha256(terminal_ids)
            relative_path = f"trace/{message_id}/batch-{time_step:06d}.json"
            partition = {
                "schema_version": _TRACE_PARTITION_SCHEMA,
                "trace_semantics": _TWO_STAGE_TRACE_SEMANTICS,
                "source_identity": source.source_identity,
                "source_manifest_sha256": source.manifest_sha256,
                "message_id": message_id,
                "time_step": time_step,
                "row_count": len(rows),
                "terminal_identity_sha256": terminal_identity,
                "rows": rows,
            }
            payload = _json_bytes(partition)
            partition_sink(relative_path, payload)
            entries[(message_id, time_step)] = {
                "message_id": message_id,
                "time_step": time_step,
                "relative_path": relative_path,
                "sha256": _sha256_bytes(payload),
                "bytes": len(payload),
                "row_count": len(rows),
                "terminal_identity_sha256": terminal_identity,
            }
            identities[(message_id, time_step)] = terminal_ids
            batch_rows[message_id] = []

    for pair, terminal in source.iter_pair_terminal_rows():
        time_step = _strict_int(terminal.get("replay_time_step"), "realized time_step")
        if not saw_row:
            current_step = time_step
            saw_row = True
        elif time_step != current_step:
            if time_step != current_step + 1:
                raise _FullPoolPresentationError("realized terminal batches are not contiguous")
            flush(current_step)
            current_step = time_step
        message_id = _non_empty_string(terminal.get("message_id"), "realized message_id")
        latent_class = _non_empty_string(pair.get("latent_class"), "realized latent class")
        try:
            segment = _SEGMENT_CODES[latent_class]
        except KeyError as exc:
            raise _FullPoolPresentationError("realized latent membership is unsupported") from exc
        if message_id not in messages:
            raise _FullPoolPresentationError("realized trace contains an unknown message")
        trace_row = _realized_trace_row(pair, terminal)
        terminal_id = _non_empty_string(trace_row.get("terminal_row_id"), "realized terminal id")
        if terminal_id in all_terminal_ids:
            raise _FullPoolPresentationError("realized trace duplicates terminal identity")
        all_terminal_ids.add(terminal_id)
        batch_rows[message_id].append(trace_row)
        message_titles[message_id] = _non_empty_string(
            pair.get("message_title"),
            "realized message title",
        )
        for counter in (
            overall,
            messages[message_id],
            segments[segment],
            cells[(segment, message_id)],
            batches[(time_step, message_id)],
        ):
            _update_realized_counter(counter, terminal)
        provider_actions[
            _non_empty_string(terminal.get("provider_action"), "Provider Judgment action")
        ] += 1
        realized_actions[
            _non_empty_string(terminal.get("realized_action"), "realized action")
        ] += 1
    if not saw_row:
        raise _FullPoolPresentationError("realized source contains no terminals")
    flush(current_step)
    if current_step != horizon - 1:
        raise _FullPoolPresentationError("realized trace does not close the source horizon")

    ordered_entries = [
        entries[(message_id, time_step)]
        for message_id in _MESSAGE_IDS
        for time_step in range(horizon)
    ]
    ordered_terminal_ids = [
        terminal_id
        for message_id in _MESSAGE_IDS
        for time_step in range(horizon)
        for terminal_id in identities[(message_id, time_step)]
    ]
    expected_terminal_count = source.counts["realized_terminals"]
    if len(all_terminal_ids) != expected_terminal_count:
        raise _FullPoolPresentationError("realized trace terminal denominator is crossed")
    source_hash = _non_empty_string(source.manifest.get("source_hash"), "realized source hash")
    index = {
        "schema_version": _TRACE_INDEX_SCHEMA,
        "trace_semantics": _TWO_STAGE_TRACE_SEMANTICS,
        "source_schema_version": FULL_POOL_TWO_STAGE_SOURCE_SCHEMA,
        "source_identity": source.source_identity,
        "source_manifest_sha256": source.manifest_sha256,
        "contract_sha256": source_hash,
        "message_order": list(_MESSAGE_IDS),
        "batch_order": list(range(horizon)),
        "terminal_count": len(ordered_terminal_ids),
        "terminal_identity_sha256": _identity_sha256(ordered_terminal_ids),
        "partition_count": len(ordered_entries),
        "partitions": ordered_entries,
    }
    index_payload = _json_bytes(index)

    overall_summary = _finish_realized_counter(overall, scope="overall")
    message_summaries = tuple(
        _finish_realized_counter(
            messages[message_id],
            scope="message",
            message_id=message_id,
            message=_MESSAGE_CODES[message_id],
            message_title=message_titles[message_id],
        )
        for message_id in _MESSAGE_IDS
    )
    segment_summaries = tuple(
        _finish_realized_counter(
            segments[segment],
            scope="segment",
            segment=segment,
        )
        for segment in _SEGMENT_CODES.values()
    )
    segment_message_summaries = tuple(
        _finish_realized_counter(
            cells[(segment, message_id)],
            scope="segment-message",
            segment=segment,
            message_id=message_id,
            message=_MESSAGE_CODES[message_id],
        )
        for segment in _SEGMENT_CODES.values()
        for message_id in _MESSAGE_IDS
    )
    for summary in segment_message_summaries:
        key = (str(summary["segment"]), str(summary["message_id"]))
        expected = expected_cells[key]
        actions = cast(Mapping[str, int], summary["action_counts"])
        if (
            summary["exposures"] != expected["exposures"]
            or actions["like"] != expected["like"]
            or actions["comment"] != expected["comment"]
            or actions["share"] != expected["share"]
        ):
            raise _FullPoolPresentationError(
                "realized report summary differs from the source-bound projection"
            )
    batch_summaries = tuple(
        _finish_realized_counter(
            batches[(time_step, message_id)],
            scope="batch-message",
            time_step=time_step,
            run=time_step + 1,
            message_id=message_id,
            message=_MESSAGE_CODES[message_id],
        )
        for time_step in range(horizon)
        for message_id in _MESSAGE_IDS
    )
    engagements_by_step = Counter[int]()
    for summary in batch_summaries:
        engagements_by_step[_strict_int(summary.get("time_step"), "batch summary time_step")] += _strict_int(
            summary.get("realized_engagements"),
            "batch realized engagements",
        )
    feedback_summaries: list[dict[str, object]] = []
    for expected_step, commit in enumerate(source.iter_batch_commits()):
        time_step = _strict_int(commit.get("replay_time_step"), "feedback time_step")
        if time_step != expected_step:
            raise _FullPoolPresentationError("realized feedback commits are not contiguous")
        frozen = _strict_string_sequence(
            commit.get("frozen_realized_positive_user_ids"),
            "frozen realized-positive users",
        )
        committed = _strict_string_sequence(
            commit.get("committed_realized_positive_user_ids"),
            "committed realized-positive users",
        )
        feedback_summaries.append(
            {
                "time_step": time_step,
                "run": time_step + 1,
                "frozen_realized_positive_users": len(frozen),
                "committed_realized_positive_users": len(committed),
                "realized_engagements": engagements_by_step[time_step],
            }
        )
    if len(feedback_summaries) != horizon:
        raise _FullPoolPresentationError("realized feedback commit denominator is crossed")

    normalized_realized_actions = {
        action: realized_actions[action] for action in _RESULT_ACTIONS
    }
    manifest_actions = _strict_mapping(
        source.manifest.get("action_counts"),
        "realized manifest action counts",
    )
    if normalized_realized_actions != {
        action: _strict_int(manifest_actions.get(action), f"manifest {action}")
        for action in _RESULT_ACTIONS
    }:
        raise _FullPoolPresentationError("realized report action counts differ from the source")

    trace = _TraceProjection(
        index_payload=index_payload,
        index_sha256=_sha256_bytes(index_payload),
        batch_summaries=batch_summaries,
        message_summaries=message_summaries,
    )
    return _RealizedPresentationProjection(
        trace=trace,
        overall=overall_summary,
        message_summaries=message_summaries,
        segment_summaries=segment_summaries,
        segment_message_summaries=segment_message_summaries,
        batch_summaries=batch_summaries,
        feedback_summaries=tuple(feedback_summaries),
        provider_action_counts=dict(sorted(provider_actions.items())),
        realized_action_counts=normalized_realized_actions,
    )


def _write_partition(root: Path, relative_path: str, payload: bytes) -> None:
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != relative_path:
        raise _FullPoolPresentationError("trace partition path is unsafe")
    target = root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)


def _compare_partition(root: Path, relative_path: str, payload: bytes) -> None:
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != relative_path:
        raise _FullPoolPresentationError("trace partition path is unsafe")
    target = root / relative_path
    _require_regular_file(target, f"trace partition {relative_path}")
    if target.read_bytes() != payload:
        raise _FullPoolPresentationError(f"trace partition bytes are malformed or crossed: {relative_path}")


def _format_count(value: object) -> str:
    return f"{_strict_int(value, 'presentation count'):,}"


def _format_rate(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _FullPoolPresentationError("presentation rate must be numeric")
    return f"{float(value) * 100:.2f}%"


def _full_pool_catalog() -> dict[str, dict[str, str]]:
    catalog = {
        "zh-CN": {
            "shell.status": "Validation 展示包 · 不可晋升",
            "shell.title": "Full-Pool 主实验",
            "shell.lead": "完整用户池、三条消息、30 个批次与 Primary-only 决策的主证据路径。",
            "shell.language": "报告语言",
            "nav.scope": "运行口径",
            "nav.trajectory": "批次轨迹",
            "nav.response": "消息响应",
            "nav.provider": "Provider 核算",
            "nav.mechanism": "机制总图",
            "nav.trace": "决策轨迹",
            "nav.downloads": "下载",
            "scope.title": "生产合同与当前来源",
            "scope.copy": "左侧是固定生产目标，右侧是本次已关闭来源的真实计数。Validation 计数不会被放大为生产结果。",
            "scope.target": "固定生产合同",
            "scope.actual": "当前来源实际值",
            "scope.users": "合格用户",
            "scope.pairs": "user × message 配对",
            "scope.batches": "完整批次",
            "scope.capacity": "每条消息批容量",
            "scope.final_capacity": "最后一批每条消息",
            "scope.candidates": "候选排序行",
            "scope.terminals": "Primary terminals",
            "scope.coverage": "完整三消息覆盖",
            "claims.title": "解释边界",
            "claims.order": "排序只改变曝光批次与顺序；最终人群和配对覆盖保持完整。",
            "claims.change": "新旧证据同时改变 population 与 requested model，禁止单因素归因。",
            "claims.limit": "结果不是因果效果、总体代表性结论或文案胜负。",
            "trajectory.title": "30-batch 投放轨迹",
            "trajectory.copy": "每个条目同时显示 exposure、成功 Primary、Provider failure 与正向行为分母。",
            "trajectory.batch": "批次",
            "trajectory.exposures": "曝光",
            "trajectory.success": "成功决策",
            "trajectory.failures": "Provider failures",
            "trajectory.positive": "正向行为",
            "response.title": "三条消息的描述性响应",
            "response.copy": "消息之间只作描述性比较，不生成 winner 或综合得分。",
            "response.message": "消息",
            "response.actions": "动作计数",
            "response.exposure_rate": "曝光互动率",
            "response.decision_rate": "成功决策互动率",
            "provider.title": "Provider 与用量核算",
            "provider.copy": "Provider failure 与 ignore 分开；完整用量和 observed model 只来自持久化 terminal evidence。",
            "provider.logical": "Logical judgments",
            "provider.physical": "Physical attempts",
            "provider.responses": "Provider responses",
            "provider.success": "Successful decisions",
            "provider.calls": "External Provider calls",
            "provider.models": "Observed models",
            "provider.usage": "Usage complete responses",
            "provider.billing": "Subscription billed USD",
            "mechanism.title": "Full-Pool 机制总图",
            "mechanism.copy": "同一语义定义投影节点、边、双语 fallback 与 Mermaid 下载，不运行 Mermaid JavaScript。",
            "mechanism.nodes": "语义节点",
            "mechanism.edges": "关系与反馈",
            "mechanism.fallback": "完整文本说明",
            "trace.title": "按需加载的完整决策轨迹",
            "trace.copy": "浏览器先校验 index，再只加载当前 message 与 batch 分区。失败时不会回退为空数据。",
            "trace.message": "消息",
            "trace.batch": "批次",
            "trace.search": "搜索 user、action 或 reason",
            "trace.action": "动作",
            "trace.all_actions": "全部动作",
            "trace.loading_index": "正在加载并校验轨迹索引。",
            "trace.loading_partition": "正在加载并校验所选分区。",
            "trace.ready": "轨迹分区已就绪。",
            "trace.error": "轨迹分区不可用；筛选器、表格与详情保持禁用。",
            "trace.results": "当前匹配",
            "trace.pagination": "轨迹分页",
            "trace.previous": "上一页",
            "trace.next": "下一页",
            "trace.open": "查看详情",
            "trace.user": "用户",
            "trace.status": "终态",
            "trace.probability": "概率",
            "trace.reason": "理由",
            "trace.detail": "Primary Decision 详情",
            "trace.close": "关闭详情",
            "downloads.title": "来源、轨迹与机制下载",
            "downloads.copy": "完整来源与历史 candidate 以原字节复制；根目录不创建新的 payload、candidate manifest、presentation closure 或 release contract。",
            "history.title": "Historical Sensitivity · 1,000 users",
            "history.copy": "以下 Primary-Shadow、19-point Ranking Weight 与 4 × 4 Prompt-Model evidence 保持原始 source、model、分母、exact values 与 approved downloads。",
            "history.open": "进入历史机制与敏感性报告",
        },
        "en-US": {
            "shell.status": "Validation presentation bundle · not promotable",
            "shell.title": "Full-Pool Main Experiment",
            "shell.lead": "The main evidence path for the full user pool, three messages, 30 batches, and Primary-only decisions.",
            "shell.language": "Report language",
            "nav.scope": "Run scope",
            "nav.trajectory": "Batch trajectory",
            "nav.response": "Message response",
            "nav.provider": "Provider accounting",
            "nav.mechanism": "Mechanism master",
            "nav.trace": "Decision trace",
            "nav.downloads": "Downloads",
            "scope.title": "Production contract and current source",
            "scope.copy": "The fixed production target is shown beside the actual counts of this closed source. Validation counts are never scaled into production results.",
            "scope.target": "Fixed production contract",
            "scope.actual": "Actual current source",
            "scope.users": "Eligible users",
            "scope.pairs": "User × message pairs",
            "scope.batches": "Committed batches",
            "scope.capacity": "Per-message batch capacity",
            "scope.final_capacity": "Final batch per message",
            "scope.candidates": "Candidate ranking rows",
            "scope.terminals": "Primary terminals",
            "scope.coverage": "Complete three-message coverage",
            "claims.title": "Interpretation boundary",
            "claims.order": "ranking changes exposure timing and order only; final population and pair coverage remain complete.",
            "claims.change": "population and requested model both change across new and historical evidence, so single-factor attribution is prohibited.",
            "claims.limit": "The results do not establish causality, population representativeness, or a winning message.",
            "trajectory.title": "30-batch delivery trajectory",
            "trajectory.copy": "Each entry keeps exposure, successful Primary, Provider failure, and positive-action denominators together.",
            "trajectory.batch": "Batch",
            "trajectory.exposures": "Exposures",
            "trajectory.success": "Successful decisions",
            "trajectory.failures": "Provider failures",
            "trajectory.positive": "Positive actions",
            "response.title": "Descriptive response by message",
            "response.copy": "Messages are compared descriptively only; no winner or composite score is produced.",
            "response.message": "Message",
            "response.actions": "Action counts",
            "response.exposure_rate": "Exposure engagement rate",
            "response.decision_rate": "Successful-decision engagement rate",
            "provider.title": "Provider and usage accounting",
            "provider.copy": "Provider failure remains separate from ignore; complete usage and observed model facts come only from persisted terminal evidence.",
            "provider.logical": "Logical judgments",
            "provider.physical": "Physical attempts",
            "provider.responses": "Provider responses",
            "provider.success": "Successful decisions",
            "provider.calls": "External Provider calls",
            "provider.models": "Observed models",
            "provider.usage": "Usage complete responses",
            "provider.billing": "Subscription billed USD",
            "mechanism.title": "Full-Pool mechanism master",
            "mechanism.copy": "One semantic definition projects nodes, edges, bilingual fallback, and the Mermaid download without Mermaid JavaScript.",
            "mechanism.nodes": "Semantic nodes",
            "mechanism.edges": "Relations and feedback",
            "mechanism.fallback": "Complete text fallback",
            "trace.title": "Complete decision trace, loaded on demand",
            "trace.copy": "The browser validates the index, then loads only the selected message and batch partition. Failure never falls back to empty data.",
            "trace.message": "Message",
            "trace.batch": "Batch",
            "trace.search": "Search user, action, or reason",
            "trace.action": "Action",
            "trace.all_actions": "All actions",
            "trace.loading_index": "Loading and validating the trace index.",
            "trace.loading_partition": "Loading and validating the selected partition.",
            "trace.ready": "The trace partition is ready.",
            "trace.error": "The trace partition is unavailable; filters, table, and details remain disabled.",
            "trace.results": "Current matches",
            "trace.pagination": "Trace pagination",
            "trace.previous": "Previous page",
            "trace.next": "Next page",
            "trace.open": "Open details",
            "trace.user": "User",
            "trace.status": "Terminal",
            "trace.probability": "Probability",
            "trace.reason": "Reason",
            "trace.detail": "Primary Decision details",
            "trace.close": "Close details",
            "downloads.title": "Source, trace, and mechanism downloads",
            "downloads.copy": "The complete source and historical candidate are copied byte-for-byte; the bundle root creates no new payload, candidate manifest, presentation closure, or release contract.",
            "history.title": "Historical Sensitivity · 1,000 users",
            "history.copy": "The Primary-Shadow, 19-point Ranking Weight, and 4 × 4 Prompt-Model evidence below keeps its original source, model, denominator, exact values, and approved downloads.",
            "history.open": "Open the historical mechanism and sensitivity report",
        },
    }
    if set(catalog) != {"zh-CN", "en-US"} or set(catalog["zh-CN"]) != set(catalog["en-US"]):
        raise _FullPoolPresentationError("Full-Pool bilingual catalog parity is crossed")
    return catalog


def _i18n(catalog: Mapping[str, Mapping[str, str]], key: str, *, tag: str = "span") -> str:
    try:
        text = catalog["zh-CN"][key]
    except KeyError as exc:
        raise _FullPoolPresentationError(f"missing Full-Pool catalog key: {key}") from exc
    return f'<{tag} data-full-pool-i18n="{html.escape(key, quote=True)}">{html.escape(text)}</{tag}>'


def _mechanism_html(catalog: dict[str, dict[str, str]]) -> str:
    presentation = _MECHANISM_PRESENTATION.build_full_pool_master()
    if len(presentation.diagrams) != 1:
        raise _FullPoolPresentationError("Full-Pool mechanism projection is incomplete")
    diagram = presentation.diagrams[0]
    projections = {projection.language: projection for projection in diagram.projections}
    if set(projections) != {"zh-CN", "en-US"}:
        raise _FullPoolPresentationError("Full-Pool mechanism language parity is incomplete")
    for language, projection in projections.items():
        for key, value in zip(projection.keys, projection.values, strict=True):
            catalog[language][f"mechanism.{key}"] = value
    if set(catalog["zh-CN"]) != set(catalog["en-US"]):
        raise _FullPoolPresentationError("Full-Pool mechanism catalog parity is crossed")
    nodes = "".join(
        '<li class="full-pool-mechanism-node" '
        f'data-mechanism-node-id="{html.escape(node.semantic_id, quote=True)}" '
        f'data-lane="{html.escape(node.lane, quote=True)}">'
        f"<code>{html.escape(node.semantic_id)}</code>"
        f"{_i18n(catalog, f'mechanism.{node.label.key}', tag='strong')}</li>"
        for node in diagram.nodes
    )
    edges = "".join(
        '<li class="full-pool-mechanism-edge" '
        f'data-mechanism-edge-id="{html.escape(edge.semantic_id, quote=True)}" '
        f'data-from="{html.escape(edge.source, quote=True)}" '
        f'data-to="{html.escape(edge.target, quote=True)}" '
        f'data-edge-style="{html.escape(edge.style, quote=True)}">'
        f"<code>{html.escape(edge.source)} → {html.escape(edge.target)}</code>"
        + (_i18n(catalog, f"mechanism.{edge.label.key}") if edge.label is not None else "")
        + "</li>"
        for edge in diagram.edges
    )
    zh_projection = projections["zh-CN"]
    fallback = "".join(f"<li>{_i18n(catalog, f'mechanism.{key}')}</li>" for key in zh_projection.fallback_keys)
    return (
        '<section id="full-pool-mechanism" class="full-pool-section" '
        'data-testid="full-pool-mechanism-section">'
        f"{_i18n(catalog, 'mechanism.title', tag='h2')}"
        f"{_i18n(catalog, 'mechanism.copy', tag='p')}"
        '<div class="full-pool-mechanism-grid">'
        f"<div><h3>{_i18n(catalog, 'mechanism.nodes')}</h3><ol>{nodes}</ol></div>"
        f"<div><h3>{_i18n(catalog, 'mechanism.edges')}</h3><ol>{edges}</ol></div>"
        "</div>"
        '<details data-testid="full-pool-mechanism-fallback">'
        f"<summary>{_i18n(catalog, 'mechanism.fallback')}</summary><ol>{fallback}</ol>"
        "</details>"
        f'<a class="full-pool-download-link" href="{_FULL_POOL_MASTER}" download>'
        f"{html.escape(_FULL_POOL_MASTER)}</a>"
        "</section>"
    )


def _realized_catalog(*, production: bool = False) -> dict[str, dict[str, str]]:
    catalog = _full_pool_catalog()
    catalog["zh-CN"].update(
        {
            "shell.status": "Two-Stage Validation · 不可部署",
            "shell.title": "Full-Pool 两阶段互动实现",
            "shell.lead": "Provider Judgment 表达互动意向；ABM 以稳定概率抽样形成每次 exposure 的 realized action。",
            "headline.label": "Realized engagement · 单次 user × message exposure",
            "nav.results": "Realized 结果",
            "nav.probability": "概率口径",
            "scope.title": "同源 realized 运行口径",
            "scope.copy": "当前页面只消费 independently closed realized source、evidence 与 projection；分类与不可部署状态原样继承。",
            "claims.order": "单次 user × message exposure 是唯一 Primary engagement 单位；Exposure 包含 realized ignore。",
            "claims.change": "S1 尚未形成 M1 偏好证据；S2 与 S3 排序只按本 source 的九格结果展示。",
            "claims.limit": "Simulated engagement 不是校准后的抖音绝对互动率，也不是因果市场效果或文案胜负。",
            "results.title": "Realized engagement 结果",
            "results.copy": "总体、Message、Segment 与完整九格均由 realized terminal 和同源 projection 重算。Likes、Comments、Shares 之和等于 realized engagements。",
            "results.overall": "总体",
            "results.message": "按 Message",
            "results.segment": "按 Segment",
            "results.segment_message": "Segment × Message · 完整九格",
            "results.exposure": "Exposure",
            "results.likes": "Likes",
            "results.comments": "Comments",
            "results.shares": "Shares",
            "results.ignores": "Realized ignores",
            "results.engagements": "Realized engagements",
            "results.rate": "单次曝光 realized engagement",
            "results.ordering": "Artifact 排序与结论",
            "trajectory.title": "30-batch realized trajectory",
            "trajectory.copy": "每个批次按 Message 显示 Exposure、realized engagements 与 action counts；同批 outcomes 全部关闭后才提交 feedback。",
            "trajectory.positive": "Realized engagements",
            "feedback.title": "Realized feedback barrier",
            "feedback.copy": "frozen 表示本批排序开始时可见的既有 realized-positive users；committed 表示整批关闭后按 user_id 去重提交的集合。",
            "feedback.frozen": "Frozen feedback users",
            "feedback.committed": "Committed feedback users",
            "probability.title": "Provider probability 与 effective gate expectation",
            "probability.copy": "raw provider_probability mean 是分组内全部 Provider Judgments 的概率均值；effective gate expectation 固定为 sum(provider_engage × provider_probability) / exposures。后者是固定 Judgment 分组下两阶段 gate 的条件期望，不是 trajectory expectation 或多-seed 区间。",
            "probability.raw": "Raw provider probability mean",
            "probability.effective": "Effective gate expectation",
            "provider.title": "Upstream Provider 与 realization 分栏核算",
            "provider.copy": "Provider/model/usage 来自已闭合 upstream evidence；realization 阶段新增 Provider calls 为 0。复合研究不会被改写成 zero-Provider Formal。",
            "provider.requested_model": "Upstream requested model",
            "provider.upstream_live": "Upstream live API triggered",
            "provider.realization_calls": "Realization Provider calls",
            "provider.realization_live": "Realization live API triggered",
            "provider.formal": "Formal research evidence",
            "mechanism.title": "两阶段 Full-Pool 机制总图",
            "mechanism.copy": "下方是由 Mechanism Presentation Module 单一语义定义生成的 deterministic inline SVG；同一节点、边与双语文本同时投影到 DOM fallback 和 `.mmd`。",
            "mechanism.figure_title": "Provider Judgment 到 realized projection 的两阶段主链",
            "mechanism.figure_description": "图形展示 Provider ignore 无 draw、正向 Judgment 进入稳定抽样、realized outcome 通过完整批次屏障形成下一批 feedback。",
            "trace.title": "Provider Judgment 与 ABM Realization trace",
            "trace.copy": "每个分区按需加载；Provider reason 只标记为互动意向理由，draw、status 与 realized outcome 单独解释 ABM Realization。",
            "trace.provider_judgment": "Provider Judgment",
            "trace.intent_reason": "互动意向理由",
            "trace.realization": "ABM Realization",
            "trace.draw": "Draw",
            "trace.realized_action": "Realized action",
            "downloads.title": "Realized source、projection、lineage 与机制下载",
            "downloads.copy": "下载全部来自同一 closed realized source；upstream lineage 保留在 manifest 与 realization evidence 中。Historical 1,000-User artifacts 按原 bytes 复制。",
            "history.copy": "以下 Primary-Shadow、Ranking Weight 与 Prompt-Model evidence 继续绑定原始 1,000-user denominator 和历史 direct-action 机制；它们不是当前 realized result。",
        }
    )
    catalog["en-US"].update(
        {
            "shell.status": "Two-Stage Validation · not deployable",
            "shell.title": "Full-Pool Two-Stage Engagement Realization",
            "shell.lead": "Provider Judgment expresses engagement intent; the ABM uses a stable probability draw to form the realized action for each exposure.",
            "headline.label": "Realized engagement · single user × message exposure",
            "nav.results": "Realized results",
            "nav.probability": "Probability contract",
            "scope.title": "Same-source realized run scope",
            "scope.copy": "This page consumes only the independently closed realized source, evidence, and projection; it preserves their classification and nondeployable status.",
            "claims.order": "A single user × message exposure is the only Primary engagement unit; Exposure includes realized ignore.",
            "claims.change": "S1 does not evidence a preference for M1; S2 and S3 orderings are shown only as persisted in this source's nine cells.",
            "claims.limit": "Simulated engagement is not a calibrated Douyin absolute engagement rate and is not a causal market effect or a winning-message claim.",
            "results.title": "Realized engagement results",
            "results.copy": "Overall, Message, Segment, and all nine cells are recomputed from realized terminals and the same-source projection. Likes, Comments, and Shares sum to realized engagements.",
            "results.overall": "Overall",
            "results.message": "By Message",
            "results.segment": "By Segment",
            "results.segment_message": "Segment × Message · all nine cells",
            "results.exposure": "Exposure",
            "results.likes": "Likes",
            "results.comments": "Comments",
            "results.shares": "Shares",
            "results.ignores": "Realized ignores",
            "results.engagements": "Realized engagements",
            "results.rate": "Single-exposure realized engagement",
            "results.ordering": "Artifact ordering and conclusion",
            "trajectory.title": "30-batch realized trajectory",
            "trajectory.copy": "Each batch shows Exposure, realized engagements, and action counts by Message; feedback is committed only after every outcome in the batch closes.",
            "trajectory.positive": "Realized engagements",
            "feedback.title": "Realized feedback barrier",
            "feedback.copy": "Frozen is the prior realized-positive user set visible when ranking starts; committed is the user_id-deduplicated set submitted after the full batch closes.",
            "feedback.frozen": "Frozen feedback users",
            "feedback.committed": "Committed feedback users",
            "probability.title": "Provider probability and effective gate expectation",
            "probability.copy": "raw provider_probability mean averages every Provider Judgment probability in the group; effective gate expectation is fixed as sum(provider_engage × provider_probability) / exposures. The latter is a conditional expectation for a fixed Judgment group, not a trajectory expectation or a multi-seed interval.",
            "probability.raw": "Raw provider probability mean",
            "probability.effective": "Effective gate expectation",
            "provider.title": "Separated upstream Provider and realization accounting",
            "provider.copy": "Provider, model, and usage facts come from closed upstream evidence; the realization stage adds zero Provider calls. The composite research is never rewritten as zero-Provider Formal evidence.",
            "provider.requested_model": "Upstream requested model",
            "provider.upstream_live": "Upstream live API triggered",
            "provider.realization_calls": "Realization Provider calls",
            "provider.realization_live": "Realization live API triggered",
            "provider.formal": "Formal research evidence",
            "mechanism.title": "Two-stage Full-Pool mechanism master",
            "mechanism.copy": "The deterministic inline SVG below is generated from the sole semantic definition in the Mechanism Presentation Module. The same nodes, edges, and bilingual text project to the DOM fallback and `.mmd`.",
            "mechanism.figure_title": "Two-stage path from Provider Judgment to realized projection",
            "mechanism.figure_description": "The figure shows Provider ignore without a draw, positive Judgment entering the stable draw, and realized outcome crossing the full-batch barrier into next-batch feedback.",
            "trace.title": "Provider Judgment and ABM Realization trace",
            "trace.copy": "Each partition loads on demand. Provider reason is labeled only as an engagement-intent reason; draw, status, and realized outcome explain ABM Realization separately.",
            "trace.provider_judgment": "Provider Judgment",
            "trace.intent_reason": "Engagement-intent reason",
            "trace.realization": "ABM Realization",
            "trace.draw": "Draw",
            "trace.realized_action": "Realized action",
            "downloads.title": "Realized source, projection, lineage, and mechanism downloads",
            "downloads.copy": "Every download comes from the same closed realized source; upstream lineage remains in the manifest and realization evidence. Historical 1,000-User artifacts are copied byte-for-byte.",
            "history.copy": "The Primary-Shadow, Ranking Weight, and Prompt-Model evidence below remains bound to its original 1,000-user denominator and historical direct-action mechanism; it is not the current realized result.",
        }
    )
    if production:
        catalog["zh-CN"].update(
            {
                "shell.status": "Formal Research Release v13 · 待部署授权",
                "scope.copy": "当前production presentation只消费independently closed formal realized source、evidence与projection；页面仍不表示已完成canonical deployment或public acceptance。",
                "downloads.copy": "下载全部来自同一formal realized source；upstream live lineage保留在manifest与realization evidence中。Historical 1,000-User artifacts按原bytes复制。",
            }
        )
        catalog["en-US"].update(
            {
                "shell.status": "Formal Research Release v13 · awaiting deployment authorization",
                "scope.copy": "This production presentation consumes only the independently closed formal realized source, evidence, and projection. It does not claim canonical deployment or public acceptance.",
                "downloads.copy": "Every download comes from the same formal realized source; upstream live lineage remains in the manifest and realization evidence. Historical 1,000-User artifacts are copied byte-for-byte.",
            }
        )
    if set(catalog["zh-CN"]) != set(catalog["en-US"]):
        raise _FullPoolPresentationError("realized Full-Pool bilingual catalog parity is crossed")
    return catalog


def _two_stage_mechanism_svg(
    catalog: Mapping[str, Mapping[str, str]],
    diagram: Any,
) -> str:
    positions: dict[str, tuple[int, int]] = {}
    node_width = 280
    node_height = 112
    for node in diagram.nodes:
        index = node.stage - 1
        row = index // 4
        offset = index % 4
        column = offset if row % 2 == 0 else 3 - offset
        positions[node.semantic_id] = (55 + column * 335, 75 + row * 205)

    edge_markup: list[str] = []
    for ordinal, edge in enumerate(diagram.edges, start=1):
        source_x, source_y = positions[edge.source]
        target_x, target_y = positions[edge.target]
        x1, y1 = source_x + node_width / 2, source_y + node_height / 2
        x2, y2 = target_x + node_width / 2, target_y + node_height / 2
        if abs(y2 - y1) < 1:
            path = f"M {x1:.0f} {y1:.0f} L {x2:.0f} {y2:.0f}"
        else:
            midpoint = (y1 + y2) / 2
            path = f"M {x1:.0f} {y1:.0f} C {x1:.0f} {midpoint:.0f}, {x2:.0f} {midpoint:.0f}, {x2:.0f} {y2:.0f}"
        label_key = f"mechanism.{edge.label.key}" if edge.label is not None else ""
        label = catalog["zh-CN"].get(label_key, edge.semantic_id)
        dash = ' stroke-dasharray="8 6"' if edge.style == "dashed" else ""
        width = "3" if edge.style == "thick" else "2"
        edge_markup.append(
            '<g class="full-pool-svg-edge" '
            f'data-mechanism-edge-id="{html.escape(edge.semantic_id, quote=True)}" '
            f'data-from="{html.escape(edge.source, quote=True)}" '
            f'data-to="{html.escape(edge.target, quote=True)}" role="group" '
            f'aria-label="{html.escape(label, quote=True)}" '
            + (f'data-full-pool-i18n-aria-label="{html.escape(label_key, quote=True)}"' if label_key else "")
            + ">"
            + (f'<title data-full-pool-i18n="{html.escape(label_key, quote=True)}">{html.escape(label)}</title>' if label_key else f"<title>{html.escape(label)}</title>")
            + f'<path d="{path}" fill="none" stroke="currentColor" stroke-width="{width}"{dash} marker-end="url(#full-pool-arrow)"/>'
            + f'<circle cx="{(x1 + x2) / 2:.0f}" cy="{(y1 + y2) / 2:.0f}" r="11"/>'
            + f'<text x="{(x1 + x2) / 2:.0f}" y="{(y1 + y2) / 2 + 4:.0f}" text-anchor="middle">{ordinal}</text>'
            + "</g>"
        )

    node_markup: list[str] = []
    for node in diagram.nodes:
        x, y = positions[node.semantic_id]
        label_key = f"mechanism.{node.label.key}"
        label = catalog["zh-CN"][label_key]
        classes = f"full-pool-svg-node full-pool-svg-node-{node.lane}"
        if node.shape == "diamond":
            shape = (
                f'<polygon points="{x + node_width / 2},{y} {x + node_width},{y + node_height / 2} '
                f'{x + node_width / 2},{y + node_height} {x},{y + node_height / 2}"/>'
            )
        elif node.shape == "hexagon":
            shape = (
                f'<polygon points="{x + 28},{y} {x + node_width - 28},{y} {x + node_width},{y + node_height / 2} '
                f'{x + node_width - 28},{y + node_height} {x + 28},{y + node_height} {x},{y + node_height / 2}"/>'
            )
        else:
            radius = 52 if node.shape == "stadium" else (18 if node.shape == "rounded" else 8)
            shape = f'<rect x="{x}" y="{y}" width="{node_width}" height="{node_height}" rx="{radius}"/>'
        node_markup.append(
            f'<g class="{classes}" data-mechanism-node-id="{html.escape(node.semantic_id, quote=True)}" '
            f'data-lane="{html.escape(node.lane, quote=True)}" tabindex="0" role="group" '
            f'aria-label="{html.escape(label, quote=True)}" data-full-pool-i18n-aria-label="{html.escape(label_key, quote=True)}">'
            f'<title data-full-pool-i18n="{html.escape(label_key, quote=True)}">{html.escape(label)}</title>'
            f"{shape}"
            f'<text x="{x + node_width / 2}" y="{y + 31}" text-anchor="middle" class="full-pool-svg-stage">{node.stage:02d}</text>'
            f'<foreignObject x="{x + 18}" y="{y + 43}" width="{node_width - 36}" height="{node_height - 48}">'
            f'<div xmlns="http://www.w3.org/1999/xhtml" data-full-pool-i18n="{html.escape(label_key, quote=True)}">{html.escape(label)}</div>'
            "</foreignObject></g>"
        )

    return (
        '<div class="full-pool-mechanism-figure-wrap">'
        '<svg data-testid="full-pool-mechanism-svg" class="full-pool-mechanism-svg" '
        'viewBox="0 0 1400 720" role="img" '
        'aria-labelledby="full-pool-mechanism-svg-title full-pool-mechanism-svg-description">'
        '<title id="full-pool-mechanism-svg-title" data-full-pool-i18n="mechanism.figure_title">'
        f'{html.escape(catalog["zh-CN"]["mechanism.figure_title"])}</title>'
        '<desc id="full-pool-mechanism-svg-description" data-full-pool-i18n="mechanism.figure_description">'
        f'{html.escape(catalog["zh-CN"]["mechanism.figure_description"])}</desc>'
        '<defs><marker id="full-pool-arrow" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto"><path d="M0,0 L9,4.5 L0,9 z"/></marker></defs>'
        + "".join(edge_markup)
        + "".join(node_markup)
        + "</svg></div>"
    )


def _two_stage_mechanism_html(catalog: dict[str, dict[str, str]]) -> str:
    presentation = _MECHANISM_PRESENTATION.build_full_pool_two_stage_master()
    if len(presentation.diagrams) != 1:
        raise _FullPoolPresentationError("two-stage Full-Pool mechanism projection is incomplete")
    diagram = presentation.diagrams[0]
    projections = {projection.language: projection for projection in diagram.projections}
    if set(projections) != {"zh-CN", "en-US"}:
        raise _FullPoolPresentationError("two-stage mechanism language parity is incomplete")
    for language, projection in projections.items():
        for key, value in zip(projection.keys, projection.values, strict=True):
            catalog[language][f"mechanism.{key}"] = value
    if set(catalog["zh-CN"]) != set(catalog["en-US"]):
        raise _FullPoolPresentationError("two-stage mechanism catalog parity is crossed")
    svg = _two_stage_mechanism_svg(catalog, diagram)
    nodes = "".join(
        '<li class="full-pool-mechanism-node" '
        f'data-mechanism-node-id="{html.escape(node.semantic_id, quote=True)}" '
        f'data-lane="{html.escape(node.lane, quote=True)}">'
        f"<code>{html.escape(node.semantic_id)}</code>"
        f"{_i18n(catalog, f'mechanism.{node.label.key}', tag='strong')}</li>"
        for node in diagram.nodes
    )
    edges = "".join(
        '<li class="full-pool-mechanism-edge" '
        f'data-mechanism-edge-id="{html.escape(edge.semantic_id, quote=True)}" '
        f'data-from="{html.escape(edge.source, quote=True)}" '
        f'data-to="{html.escape(edge.target, quote=True)}" '
        f'data-edge-style="{html.escape(edge.style, quote=True)}">'
        f"<code>{html.escape(edge.source)} → {html.escape(edge.target)}</code>"
        + (_i18n(catalog, f"mechanism.{edge.label.key}") if edge.label is not None else "")
        + "</li>"
        for edge in diagram.edges
    )
    zh_projection = projections["zh-CN"]
    fallback = "".join(
        f"<li>{_i18n(catalog, f'mechanism.{key}')}</li>"
        for key in zh_projection.fallback_keys
    )
    return (
        '<section id="full-pool-mechanism" class="full-pool-section" data-testid="full-pool-mechanism-section">'
        f"{_i18n(catalog, 'mechanism.title', tag='h2')}"
        f"{_i18n(catalog, 'mechanism.copy', tag='p')}"
        f"{svg}"
        '<details data-testid="full-pool-mechanism-fallback">'
        f"<summary>{_i18n(catalog, 'mechanism.fallback')}</summary>"
        f'<div class="full-pool-mechanism-grid"><div><h3>{_i18n(catalog, "mechanism.nodes")}</h3><ol>{nodes}</ol></div>'
        f'<div><h3>{_i18n(catalog, "mechanism.edges")}</h3><ol>{edges}</ol></div></div>'
        f"<ol>{fallback}</ol></details>"
        f'<a class="full-pool-download-link" href="{_FULL_POOL_MASTER}" download>{html.escape(_FULL_POOL_MASTER)}</a>'
        "</section>"
    )


def _scope_fact(label: str, value: str, test_id: str) -> str:
    return (
        f'<div class="full-pool-fact" data-testid="{html.escape(test_id, quote=True)}">'
        f"<dt>{label}</dt><dd>{html.escape(value)}</dd></div>"
    )


def _result_action_cells(summary: Mapping[str, object]) -> tuple[int, int, int, int]:
    actions = _strict_mapping(summary.get("action_counts"), "realized summary action counts")
    return (
        _strict_int(actions.get("like"), "realized like"),
        _strict_int(actions.get("comment"), "realized comment"),
        _strict_int(actions.get("share"), "realized share"),
        _strict_int(actions.get("ignore"), "realized ignore"),
    )


def _result_table_row(
    catalog: Mapping[str, Mapping[str, str]],
    summary: Mapping[str, object],
    *,
    scope: str,
    label: str,
    attributes: Mapping[str, str],
) -> str:
    likes, comments, shares, ignores = _result_action_cells(summary)
    engagements = _strict_int(summary.get("realized_engagements"), "realized engagements")
    exposures = _strict_int(summary.get("exposures"), "realized exposures")
    attrs = " ".join(
        f'data-{html.escape(key, quote=True)}="{html.escape(value, quote=True)}"'
        for key, value in attributes.items()
    )
    return (
        f'<tr data-result-scope="{html.escape(scope, quote=True)}" {attrs} '
        f'data-exposure="{exposures}" data-realized-engagements="{engagements}">'
        f'<th scope="row">{html.escape(label)}</th>'
        f"<td>{exposures:,}</td><td>{likes:,}</td><td>{comments:,}</td><td>{shares:,}</td>"
        f"<td>{ignores:,}</td><td>{engagements:,}</td>"
        f"<td>{_format_rate(summary.get('realized_engagement_rate'))}</td></tr>"
    )


def _result_table(
    catalog: Mapping[str, Mapping[str, str]],
    *,
    test_id: str,
    rows: str,
) -> str:
    return (
        f'<div class="full-pool-table-wrap"><table data-testid="{html.escape(test_id, quote=True)}">'
        "<thead><tr><th>Group</th>"
        f"<th>{_i18n(catalog, 'results.exposure')}</th>"
        f"<th>{_i18n(catalog, 'results.likes')}</th>"
        f"<th>{_i18n(catalog, 'results.comments')}</th>"
        f"<th>{_i18n(catalog, 'results.shares')}</th>"
        f"<th>{_i18n(catalog, 'results.ignores')}</th>"
        f"<th>{_i18n(catalog, 'results.engagements')}</th>"
        f"<th>{_i18n(catalog, 'results.rate')}</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
    )


def _render_realized_full_pool_main(
    source: ClosedFullPoolTwoStageSource,
    projection: _RealizedPresentationProjection,
    *,
    index_sha256: str,
    production: bool = False,
) -> tuple[str, dict[str, dict[str, str]]]:
    catalog = _realized_catalog(production=production)
    counts = source.counts
    overall = projection.overall
    exposures = _strict_int(overall.get("exposures"), "overall realized exposures")
    engagements = _strict_int(
        overall.get("realized_engagements"),
        "overall realized engagements",
    )
    if exposures != counts["exposures"] or exposures != counts["realized_terminals"]:
        raise _FullPoolPresentationError("realized headline denominator differs from source")
    if engagements != sum(
        projection.realized_action_counts[action]
        for action in ("like", "comment", "share")
    ):
        raise _FullPoolPresentationError("realized headline numerator differs from source")

    message_rows = "".join(
        _result_table_row(
            catalog,
            summary,
            scope="message",
            label=str(summary["message"]),
            attributes={"message": str(summary["message"])},
        )
        for summary in projection.message_summaries
    )
    segment_rows = "".join(
        _result_table_row(
            catalog,
            summary,
            scope="segment",
            label=str(summary["segment"]),
            attributes={"segment": str(summary["segment"])},
        )
        for summary in projection.segment_summaries
    )
    segment_message_rows = "".join(
        _result_table_row(
            catalog,
            summary,
            scope="segment-message",
            label=f"{summary['segment']} × {summary['message']}",
            attributes={
                "segment": str(summary["segment"]),
                "message": str(summary["message"]),
            },
        )
        for summary in projection.segment_message_summaries
    )

    by_segment: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for summary in projection.segment_message_summaries:
        by_segment[str(summary["segment"])].append(summary)
    ordering_items: list[str] = []
    for segment in ("S2", "S3"):
        ordered = sorted(
            by_segment[segment],
            key=lambda row: (
                -_strict_float(row.get("realized_engagement_rate"), "segment-message rate"),
                str(row["message"]),
            ),
        )
        ordering = " > ".join(str(row["message"]) for row in ordered)
        key = f"results.ordering.{segment.lower()}"
        catalog["zh-CN"][key] = f"{segment} artifact 排序：{ordering}。这是本次 simulated exposure 的描述性结果。"
        catalog["en-US"][key] = (
            f"{segment} artifact ordering: {ordering}. This is a descriptive result for this simulated exposure path."
        )
        ordering_items.append(
            f'<li data-segment-order="{segment}" data-ordering="{html.escape(ordering, quote=True)}">'
            f"{_i18n(catalog, key)}</li>"
        )
    if set(catalog["zh-CN"]) != set(catalog["en-US"]):
        raise _FullPoolPresentationError("realized ordering catalog parity is crossed")

    batches_by_step: dict[int, list[Mapping[str, object]]] = defaultdict(list)
    for summary in projection.batch_summaries:
        batches_by_step[_strict_int(summary.get("time_step"), "batch time_step")].append(summary)
    feedback_by_step = {
        _strict_int(row.get("time_step"), "feedback time_step"): row
        for row in projection.feedback_summaries
    }
    batch_rows: list[str] = []
    for time_step in range(source.horizon):
        summaries = sorted(
            batches_by_step[time_step],
            key=lambda row: _MESSAGE_IDS.index(str(row["message_id"])),
        )
        message_cells = "".join(
            '<div class="full-pool-batch-message" '
            f'data-message-id="{html.escape(str(row["message_id"]), quote=True)}">'
            f"<strong>{html.escape(str(row['message']))}</strong>"
            f"<span>{_i18n(catalog, 'trajectory.exposures')}: {_format_count(row['exposures'])}</span>"
            f"<span>{_i18n(catalog, 'trajectory.positive')}: {_format_count(row['realized_engagements'])}</span>"
            f"<span>{_i18n(catalog, 'response.actions')}: {html.escape(_canonical_json(row['action_counts']))}</span>"
            "</div>"
            for row in summaries
        )
        feedback = feedback_by_step[time_step]
        batch_rows.append(
            '<li class="full-pool-batch-row" '
            f'data-time-step="{time_step}"><div class="full-pool-batch-label">'
            f"{_i18n(catalog, 'trajectory.batch')} {time_step + 1:02d}</div>"
            f'<div class="full-pool-batch-content"><div class="full-pool-batch-messages">{message_cells}</div>'
            '<div class="full-pool-feedback-row" data-testid="full-pool-feedback-row" '
            f'data-frozen-users="{feedback["frozen_realized_positive_users"]}" '
            f'data-committed-users="{feedback["committed_realized_positive_users"]}" '
            f'data-realized-engagements="{feedback["realized_engagements"]}">'
            f"<span>{_i18n(catalog, 'feedback.frozen')}: {_format_count(feedback['frozen_realized_positive_users'])}</span>"
            f"<span>{_i18n(catalog, 'feedback.committed')}: {_format_count(feedback['committed_realized_positive_users'])}</span>"
            "</div></div></li>"
        )

    probability_rows = "".join(
        '<tr data-probability-group="segment-message" '
        f'data-segment="{html.escape(str(row["segment"]), quote=True)}" '
        f'data-message="{html.escape(str(row["message"]), quote=True)}">'
        f"<th scope=" + '"row"' + f">{html.escape(str(row['segment']))} × {html.escape(str(row['message']))}</th>"
        f"<td>{_format_rate(row['raw_provider_probability_mean'])}</td>"
        f"<td>{_format_rate(row['effective_gate_expectation'])}</td>"
        f"<td>{_format_rate(row['realized_engagement_rate'])}</td></tr>"
        for row in projection.segment_message_summaries
    )

    accounting = _strict_mapping(source.manifest.get("accounting"), "realized accounting")
    upstream = _strict_mapping(accounting.get("upstream"), "upstream accounting")
    realization = _strict_mapping(accounting.get("realization"), "realization accounting")
    upstream_provider = _strict_mapping(
        upstream.get("provider_accounting"),
        "upstream Provider accounting",
    )
    provider_facts = "".join(
        (
            _scope_fact(
                _i18n(catalog, "provider.logical"),
                _format_count(upstream.get("logical_judgments")),
                "provider-logical",
            ),
            _scope_fact(
                _i18n(catalog, "provider.physical"),
                _format_count(upstream.get("charged_physical_attempts")),
                "provider-physical",
            ),
            _scope_fact(
                _i18n(catalog, "provider.responses"),
                _format_count(upstream_provider.get("provider_response_count")),
                "provider-responses",
            ),
            _scope_fact(
                _i18n(catalog, "provider.requested_model"),
                _non_empty_string(upstream.get("requested_model"), "upstream requested model"),
                "provider-requested-model",
            ),
            _scope_fact(
                _i18n(catalog, "provider.models"),
                _canonical_json(upstream.get("observed_model_counts")),
                "provider-models",
            ),
            _scope_fact(
                _i18n(catalog, "provider.usage"),
                _format_count(upstream.get("usage_complete_response_count")),
                "provider-usage",
            ),
            _scope_fact(
                _i18n(catalog, "provider.upstream_live"),
                str(upstream.get("live_api_triggered")).lower(),
                "provider-upstream-live",
            ),
            _scope_fact(
                _i18n(catalog, "provider.realization_calls"),
                _format_count(realization.get("provider_calls")),
                "realization-provider-calls",
            ),
            _scope_fact(
                _i18n(catalog, "provider.realization_live"),
                str(realization.get("live_api_triggered")).lower(),
                "realization-live",
            ),
            _scope_fact(
                _i18n(catalog, "provider.formal"),
                str(source.formal_research_evidence).lower(),
                "formal-research-evidence",
            ),
        )
    )

    batch_exposures = {
        (
            _strict_int(row.get("time_step"), "batch exposure time_step"),
            _non_empty_string(row.get("message_id"), "batch exposure message_id"),
        ): _strict_int(row.get("exposures"), "batch exposure count")
        for row in projection.batch_summaries
    }
    nonfinal = [
        batch_exposures[(time_step, message_id)]
        for time_step in range(max(0, source.horizon - 1))
        for message_id in _MESSAGE_IDS
    ]
    actual_capacity = max(nonfinal, default=max(batch_exposures.values()))
    final_capacities = {
        batch_exposures[(source.horizon - 1, message_id)] for message_id in _MESSAGE_IDS
    }
    actual_final_capacity = (
        final_capacities.pop() if len(final_capacities) == 1 else min(final_capacities)
    )
    actual_facts = "".join(
        (
            _scope_fact(_i18n(catalog, "scope.users"), f"{counts['users']:,}", "actual-users"),
            _scope_fact(_i18n(catalog, "scope.pairs"), f"{counts['pairs']:,}", "actual-pairs"),
            _scope_fact(_i18n(catalog, "scope.batches"), f"{counts['batch_commits']:,}", "actual-batches"),
            _scope_fact(_i18n(catalog, "scope.capacity"), f"{actual_capacity:,}", "actual-capacity"),
            _scope_fact(_i18n(catalog, "scope.final_capacity"), f"{actual_final_capacity:,}", "actual-final-capacity"),
            _scope_fact(_i18n(catalog, "scope.candidates"), f"{counts['candidate_rows']:,}", "actual-candidates"),
            _scope_fact(_i18n(catalog, "scope.terminals"), f"{counts['realized_terminals']:,}", "actual-terminals"),
            _scope_fact(_i18n(catalog, "scope.coverage"), "3 / user", "actual-coverage"),
        )
    )
    likes, comments, shares, ignores = _result_action_cells(overall)
    overall_facts = "".join(
        (
            _scope_fact(_i18n(catalog, "results.exposure"), f"{exposures:,}", "overall-exposure"),
            _scope_fact(_i18n(catalog, "results.engagements"), f"{engagements:,}", "overall-engagements"),
            _scope_fact(_i18n(catalog, "results.rate"), _format_rate(overall.get("realized_engagement_rate")), "overall-rate"),
            _scope_fact(_i18n(catalog, "results.likes"), f"{likes:,}", "overall-likes"),
            _scope_fact(_i18n(catalog, "results.comments"), f"{comments:,}", "overall-comments"),
            _scope_fact(_i18n(catalog, "results.shares"), f"{shares:,}", "overall-shares"),
            _scope_fact(_i18n(catalog, "results.ignores"), f"{ignores:,}", "overall-ignores"),
        )
    )

    message_options = "".join(
        f'<option value="{message_id}">{_MESSAGE_CODES[message_id]}</option>'
        for message_id in _MESSAGE_IDS
    )
    batch_options = "".join(
        f'<option value="{time_step}">{time_step + 1:02d}</option>'
        for time_step in range(source.horizon)
    )
    source_artifacts = ("manifest.json", *tuple(sorted(source.artifact_hashes)))
    source_downloads = "".join(
        f'<li><a class="full-pool-download-link" href="{_FULL_POOL_SOURCE_DIR}/{html.escape(relative_path, quote=True)}" download>{html.escape(relative_path)}</a></li>'
        for relative_path in source_artifacts
    )
    mechanism = _two_stage_mechanism_html(catalog)
    presentation_eligibility = (
        "presentation_release_production_deploy_eligible=true"
        if production
        else "presentation_candidate_production_deploy_eligible=false"
    )

    main = f"""
<section id="full-pool-main" class="full-pool-hero" data-testid="full-pool-main-experiment">
  <div class="full-pool-hero-copy">
    {_i18n(catalog, "shell.status", tag="p")}
    {_i18n(catalog, "shell.title", tag="h1")}
    {_i18n(catalog, "shell.lead", tag="p")}
  </div>
  <div class="full-pool-realized-headline" data-testid="full-pool-realized-headline">
    <span>{_i18n(catalog, "headline.label")}</span>
    <strong>{engagements:,} / {exposures:,}</strong>
    <b>{_format_rate(overall.get("realized_engagement_rate"))}</b>
  </div>
  <div class="full-pool-language" role="group" aria-label="{html.escape(catalog['zh-CN']['shell.language'], quote=True)}" data-full-pool-i18n-aria-label="shell.language">
    <button type="button" data-full-pool-language="zh-CN" aria-pressed="true">中文</button>
    <button type="button" data-full-pool-language="en-US" aria-pressed="false">English</button>
  </div>
  <nav class="full-pool-nav" aria-label="Full-Pool report">
    <a href="#full-pool-scope">{_i18n(catalog, "nav.scope")}</a>
    <a href="#full-pool-results">{_i18n(catalog, "nav.results")}</a>
    <a href="#full-pool-trajectory">{_i18n(catalog, "nav.trajectory")}</a>
    <a href="#full-pool-probability">{_i18n(catalog, "nav.probability")}</a>
    <a href="#full-pool-provider">{_i18n(catalog, "nav.provider")}</a>
    <a href="#full-pool-mechanism">{_i18n(catalog, "nav.mechanism")}</a>
    <a href="#full-pool-trace">{_i18n(catalog, "nav.trace")}</a>
    <a href="#full-pool-downloads">{_i18n(catalog, "nav.downloads")}</a>
  </nav>
</section>
<section id="full-pool-scope" class="full-pool-section" data-testid="full-pool-run-evidence">
  {_i18n(catalog, "scope.title", tag="h2")}
  {_i18n(catalog, "scope.copy", tag="p")}
  <dl class="full-pool-provider-grid">{actual_facts}</dl>
  <code class="full-pool-source-facts">source-schema={FULL_POOL_TWO_STAGE_SOURCE_SCHEMA} source-classification={html.escape(source.classification)} formal_research_evidence={str(source.formal_research_evidence).lower()} source_production_deploy_eligible={str(source.production_deploy_eligible).lower()} {presentation_eligibility} realization_provider_calls=0</code>
  <aside class="full-pool-claim-boundary" data-testid="full-pool-claim-boundary">
    {_i18n(catalog, "claims.title", tag="h3")}
    <ul><li>{_i18n(catalog, "claims.order")}</li><li>{_i18n(catalog, "claims.change")}</li><li>{_i18n(catalog, "claims.limit")}</li></ul>
  </aside>
</section>
<section id="full-pool-results" class="full-pool-section" data-testid="full-pool-segment-results">
  {_i18n(catalog, "results.title", tag="h2")}
  {_i18n(catalog, "results.copy", tag="p")}
  <article class="full-pool-overall" data-testid="full-pool-overall-result"><h3>{_i18n(catalog, "results.overall")}</h3><dl class="full-pool-provider-grid">{overall_facts}</dl></article>
  <article><h3>{_i18n(catalog, "results.message")}</h3>{_result_table(catalog, test_id="full-pool-message-result-table", rows=message_rows)}</article>
  <article><h3>{_i18n(catalog, "results.segment")}</h3>{_result_table(catalog, test_id="full-pool-segment-result-table", rows=segment_rows)}</article>
  <article><h3>{_i18n(catalog, "results.segment_message")}</h3>{_result_table(catalog, test_id="full-pool-segment-table", rows=segment_message_rows)}</article>
  <aside class="full-pool-result-conclusion" data-testid="full-pool-result-conclusion">
    <h3>{_i18n(catalog, "results.ordering")}</h3>
    <p>{_i18n(catalog, "claims.change")}</p><ul>{''.join(ordering_items)}</ul>
  </aside>
</section>
<section id="full-pool-trajectory" class="full-pool-section" data-testid="full-pool-batch-trajectory">
  {_i18n(catalog, "trajectory.title", tag="h2")}
  {_i18n(catalog, "trajectory.copy", tag="p")}
  <aside data-testid="full-pool-feedback-trajectory"><h3>{_i18n(catalog, "feedback.title")}</h3>{_i18n(catalog, "feedback.copy", tag="p")}</aside>
  <ol class="full-pool-batch-list">{''.join(batch_rows)}</ol>
</section>
<section id="full-pool-probability" class="full-pool-section" data-testid="full-pool-probability-contract">
  {_i18n(catalog, "probability.title", tag="h2")}
  {_i18n(catalog, "probability.copy", tag="p")}
  <div class="full-pool-table-wrap"><table><thead><tr><th>Segment × Message</th><th>{_i18n(catalog, "probability.raw")}</th><th>{_i18n(catalog, "probability.effective")}</th><th>{_i18n(catalog, "results.rate")}</th></tr></thead><tbody>{probability_rows}</tbody></table></div>
</section>
<section id="full-pool-provider" class="full-pool-section" data-testid="full-pool-provider-accounting">
  {_i18n(catalog, "provider.title", tag="h2")}
  {_i18n(catalog, "provider.copy", tag="p")}
  <dl class="full-pool-provider-grid">{provider_facts}</dl>
</section>
{mechanism}
<section id="full-pool-trace" class="full-pool-section" data-testid="full-pool-trace-reader" data-trace-semantics="{_TWO_STAGE_TRACE_SEMANTICS}" data-trace-state="loading" aria-busy="true" data-trace-index-schema="{_TRACE_INDEX_SCHEMA}" data-trace-index-sha256="{index_sha256}">
  {_i18n(catalog, "trace.title", tag="h2")}
  {_i18n(catalog, "trace.copy", tag="p")}
  <p class="full-pool-trace-status" data-testid="full-pool-trace-state" data-trace-state="loading" role="status" aria-live="polite" aria-atomic="true">{html.escape(catalog['zh-CN']['trace.loading_index'])}</p>
  <div class="full-pool-trace-controls">
    <label>{_i18n(catalog, "trace.message")}<select data-testid="full-pool-trace-message" disabled>{message_options}</select></label>
    <label>{_i18n(catalog, "trace.batch")}<select data-testid="full-pool-trace-batch" disabled>{batch_options}</select></label>
    <label>{_i18n(catalog, "trace.search")}<input data-testid="full-pool-trace-search" type="search" disabled></label>
    <label>{_i18n(catalog, "trace.action")}<select data-testid="full-pool-trace-action" disabled><option value="">{_i18n(catalog, "trace.all_actions")}</option><option value="like">like</option><option value="comment">comment</option><option value="share">share</option><option value="ignore">ignore</option></select></label>
  </div>
  <p data-testid="full-pool-trace-filtered-count">{_i18n(catalog, "trace.results")}: <strong>0</strong></p>
  <nav class="full-pool-trace-pagination" data-testid="full-pool-trace-pagination" aria-label="{html.escape(catalog['zh-CN']['trace.pagination'], quote=True)}" data-full-pool-i18n-aria-label="trace.pagination">
    <button type="button" data-full-pool-trace-page="previous" aria-label="{html.escape(catalog['zh-CN']['trace.previous'], quote=True)}" data-full-pool-i18n-aria-label="trace.previous" disabled>{_i18n(catalog, "trace.previous")}</button>
    <p data-testid="full-pool-trace-page-status" role="status" aria-live="polite" aria-atomic="true">第 1 / 1 页 · 0-0 / 0</p>
    <button type="button" data-full-pool-trace-page="next" aria-label="{html.escape(catalog['zh-CN']['trace.next'], quote=True)}" data-full-pool-i18n-aria-label="trace.next" disabled>{_i18n(catalog, "trace.next")}</button>
  </nav>
  <div class="full-pool-table-wrap"><table data-testid="full-pool-trace-table" hidden>
    <thead><tr><th>{_i18n(catalog, "trace.user")}</th><th>{_i18n(catalog, "trace.message")}</th><th>{_i18n(catalog, "trace.batch")}</th><th>{_i18n(catalog, "trace.provider_judgment")}</th><th>{_i18n(catalog, "trace.probability")}</th><th>{_i18n(catalog, "trace.intent_reason")}</th><th>{_i18n(catalog, "trace.realization")}</th><th>{_i18n(catalog, "trace.draw")}</th><th>{_i18n(catalog, "trace.realized_action")}</th><th></th></tr></thead>
    <tbody data-testid="full-pool-trace-table-body"></tbody>
  </table></div>
  <aside class="full-pool-trace-drawer" data-testid="full-pool-trace-drawer" role="dialog" aria-modal="true" aria-labelledby="full-pool-trace-drawer-title" hidden>
    <div class="full-pool-trace-drawer-backdrop" aria-hidden="true"></div><div class="full-pool-trace-drawer-surface"><header><h3 id="full-pool-trace-drawer-title">{_i18n(catalog, "trace.detail")}</h3><button type="button" data-testid="full-pool-trace-drawer-close" aria-label="{html.escape(catalog['zh-CN']['trace.close'], quote=True)}" data-full-pool-i18n-aria-label="trace.close">×</button></header><pre data-testid="full-pool-trace-detail"></pre></div>
  </aside>
</section>
<section id="full-pool-downloads" class="full-pool-section" data-testid="full-pool-downloads">
  {_i18n(catalog, "downloads.title", tag="h2")}
  {_i18n(catalog, "downloads.copy", tag="p")}
  <ul class="full-pool-download-list"><li><a class="full-pool-download-link" href="{_TRACE_INDEX_PATH}" download>{_TRACE_INDEX_PATH}</a></li><li><a class="full-pool-download-link" href="{_FULL_POOL_MASTER}" download>{_FULL_POOL_MASTER}</a></li>{source_downloads}</ul>
</section>
"""
    return main, catalog


def _render_full_pool_main(
    source: _ClosedFullPoolSource,
    trace: _TraceProjection,
    *,
    index_sha256: str,
    result_projection: FullPoolResultProjection | None = None,
) -> tuple[str, dict[str, dict[str, str]]]:
    catalog = _full_pool_catalog()
    counts = _strict_mapping(source.aggregates.get("counts"), "Full-Pool counts")
    diagnostics_schedule = _strict_mapping(
        _strict_mapping(source.diagnostics, "Full-Pool diagnostics").get("schedule"),
        "Full-Pool schedule",
    )
    accounting = _strict_mapping(source.aggregates.get("provider_accounting"), "Full-Pool Provider accounting")
    actual_users = _strict_int(counts.get("distinct_users"), "actual users")
    actual_pairs = _strict_int(counts.get("eligible_pairs"), "actual pairs")
    actual_terminals = _strict_int(counts.get("primary_terminals"), "actual terminals")
    actual_batches = _strict_int(counts.get("committed_batches"), "actual batches")
    actual_candidates = _strict_int(counts.get("candidate_ranking_rows"), "actual candidate rows")
    if actual_batches != FULL_POOL_PRODUCTION_HORIZON:
        catalog["zh-CN"]["trajectory.title"] = f"{actual_batches}-batch Validation 投放轨迹（生产目标 30 batches）"
        catalog["en-US"]["trajectory.title"] = (
            f"{actual_batches}-batch Validation delivery trajectory (30-batch production target)"
        )
    actual_capacity = _strict_int(diagnostics_schedule.get("per_message_capacity"), "actual capacity")
    actual_final_capacity = _strict_int(
        diagnostics_schedule.get("final_batch_pairs_per_message"),
        "actual final capacity",
    )
    requested_model = (
        source.contract.formal_execution.requested_model
        if source.contract.formal_execution is not None
        else "deterministic-validation"
    )
    evidence_profile = _non_empty_string(
        source.aggregates.get("evidence_profile"),
        "Full-Pool evidence profile",
    )
    segmented_lineage = ""
    raw_segmented = source.manifest.get("segmented_execution")
    if raw_segmented is not None:
        segmented = _strict_mapping(raw_segmented, "segmented execution lineage")
        prefix_terminals = _strict_int(
            segmented.get("serial_prefix_terminal_count"),
            "segmented serial prefix terminals",
        )
        suffix_terminals = _strict_int(
            segmented.get("concurrent_suffix_terminal_count"),
            "segmented concurrent suffix terminals",
        )
        max_concurrency = _strict_int(segmented.get("max_concurrency"), "segmented max concurrency")
        unknown_count = _strict_int(segmented.get("unknown_pair_count"), "segmented unknown count")
        reconciliation_count = _strict_int(
            segmented.get("reconciliation_retry_count"),
            "segmented reconciliation count",
        )
        total_physical = _strict_int(
            segmented.get("total_physical_attempts"),
            "segmented total physical attempts",
        )
        cutoff_hash = _non_empty_string(
            segmented.get("cutoff_manifest_sha256"),
            "segmented cutoff hash",
        )
        if max_concurrency != 10 or not _SHA256_PATTERN.fullmatch(cutoff_hash):
            raise _FullPoolPresentationError("segmented execution topology or cutoff hash is crossed")
        segmented_lineage = (
            '<aside class="full-pool-segmented-lineage" data-testid="full-pool-segmented-lineage">'
            '<strong>serial prefix → max_concurrency10 suffix</strong>'
            '<p>串行前缀在静态 cutoff 后切换为最多 10 路并发后缀；'
            'unknown 与 reconciliation 独立核算。</p>'
            '<p>After the static cutoff, the serial prefix continues as a '
            'max-concurrency-10 suffix; unknown and reconciliation charges remain explicit.</p>'
            f'<code>prefix-terminals={prefix_terminals} suffix-terminals={suffix_terminals} '
            f'unknown={unknown_count} reconciliation={reconciliation_count} '
            f'total-physical={total_physical} cutoff-sha256={cutoff_hash}</code>'
            '</aside>'
        )

    target_facts = "".join(
        (
            _scope_fact(_i18n(catalog, "scope.users"), f"{FULL_POOL_PRODUCTION_USER_COUNT:,}", "target-users"),
            _scope_fact(_i18n(catalog, "scope.pairs"), f"{FULL_POOL_PRODUCTION_ELIGIBLE_PAIRS:,}", "target-pairs"),
            _scope_fact(_i18n(catalog, "scope.batches"), f"{FULL_POOL_PRODUCTION_HORIZON:,}", "target-batches"),
            _scope_fact(_i18n(catalog, "scope.capacity"), f"{FULL_POOL_PRODUCTION_CAPACITY:,}", "target-capacity"),
            _scope_fact(
                _i18n(catalog, "scope.final_capacity"),
                f"{FULL_POOL_PRODUCTION_FINAL_BATCH_PAIRS_PER_MESSAGE:,}",
                "target-final-capacity",
            ),
            _scope_fact(
                _i18n(catalog, "scope.candidates"), f"{FULL_POOL_PRODUCTION_CANDIDATE_ROWS:,}", "target-candidates"
            ),
            _scope_fact(
                _i18n(catalog, "scope.terminals"), f"{FULL_POOL_PRODUCTION_ELIGIBLE_PAIRS:,}", "target-terminals"
            ),
            _scope_fact(_i18n(catalog, "scope.coverage"), "3 / user", "target-coverage"),
        )
    )
    actual_facts = "".join(
        (
            _scope_fact(_i18n(catalog, "scope.users"), f"{actual_users:,}", "actual-users"),
            _scope_fact(_i18n(catalog, "scope.pairs"), f"{actual_pairs:,}", "actual-pairs"),
            _scope_fact(_i18n(catalog, "scope.batches"), f"{actual_batches:,}", "actual-batches"),
            _scope_fact(_i18n(catalog, "scope.capacity"), f"{actual_capacity:,}", "actual-capacity"),
            _scope_fact(_i18n(catalog, "scope.final_capacity"), f"{actual_final_capacity:,}", "actual-final-capacity"),
            _scope_fact(_i18n(catalog, "scope.candidates"), f"{actual_candidates:,}", "actual-candidates"),
            _scope_fact(_i18n(catalog, "scope.terminals"), f"{actual_terminals:,}", "actual-terminals"),
            _scope_fact(_i18n(catalog, "scope.coverage"), "3 / user", "actual-coverage"),
        )
    )

    batches_by_step: dict[int, list[Mapping[str, object]]] = defaultdict(list)
    for row in trace.batch_summaries:
        batches_by_step[_strict_int(row.get("time_step"), "batch time_step")].append(row)
    batch_rows = []
    for time_step in range(source.contract.horizon):
        messages = sorted(
            batches_by_step[time_step],
            key=lambda row: source.contract.message_ids.index(str(row["message_id"])),
        )
        message_cells = "".join(
            '<div class="full-pool-batch-message" '
            f'data-message-id="{html.escape(str(row["message_id"]), quote=True)}">'
            f"<strong>{html.escape(str(row['message_id']))}</strong>"
            f"<span>{_i18n(catalog, 'trajectory.exposures')}: {_format_count(row['exposures'])}</span>"
            f"<span>{_i18n(catalog, 'trajectory.success')}: {_format_count(row['successful_primary_decisions'])}</span>"
            f"<span>{_i18n(catalog, 'trajectory.failures')}: {_format_count(row['provider_failures'])}</span>"
            f"<span>{_i18n(catalog, 'trajectory.positive')}: {_format_count(row['positive_actions'])}</span>"
            "</div>"
            for row in messages
        )
        batch_rows.append(
            '<li class="full-pool-batch-row" '
            f'data-time-step="{time_step}"><div class="full-pool-batch-label">'
            f"{_i18n(catalog, 'trajectory.batch')} {time_step + 1:02d}</div>"
            f'<div class="full-pool-batch-messages">{message_cells}</div></li>'
        )

    message_rows = "".join(
        '<tr data-message-id="{message_id}">'
        '<th scope="row"><span class="full-pool-message-mark" aria-hidden="true"></span>'
        "<span>{message_id}</span><small>{title}</small></th>"
        "<td>{exposures}</td><td>{success}</td><td>{failures}</td><td>{actions}</td>"
        "<td>{exposure_rate}</td><td>{decision_rate}</td></tr>".format(
            message_id=html.escape(str(row["message_id"]), quote=True),
            title=html.escape(str(row["message_title"])),
            exposures=_format_count(row["exposures"]),
            success=_format_count(row["successful_primary_decisions"]),
            failures=_format_count(row["provider_failures"]),
            actions=html.escape(_canonical_json(row["action_counts"])),
            exposure_rate=_format_rate(row["exposure_engagement_rate"]),
            decision_rate=_format_rate(row["decision_engagement_rate"]),
        )
        for row in trace.message_summaries
    )

    provider_facts = "".join(
        (
            _scope_fact(
                _i18n(catalog, "provider.logical"),
                _format_count(accounting.get("logical_judgments")),
                "provider-logical",
            ),
            _scope_fact(
                _i18n(catalog, "provider.physical"),
                _format_count(accounting.get("physical_attempts")),
                "provider-physical",
            ),
            _scope_fact(
                _i18n(catalog, "provider.responses"),
                _format_count(accounting.get("provider_responses")),
                "provider-responses",
            ),
            _scope_fact(
                _i18n(catalog, "provider.success"),
                _format_count(accounting.get("successful_decisions")),
                "provider-success",
            ),
            _scope_fact(
                _i18n(catalog, "provider.calls"),
                _format_count(accounting.get("external_request_invocations")),
                "provider-calls",
            ),
            _scope_fact(
                _i18n(catalog, "provider.models"),
                _canonical_json(accounting.get("observed_model_counts")),
                "provider-models",
            ),
            _scope_fact(
                _i18n(catalog, "provider.usage"),
                _format_count(accounting.get("usage_complete_response_count")),
                "provider-usage",
            ),
            _scope_fact(
                _i18n(catalog, "provider.billing"),
                str(accounting.get("subscription_billed_cost_usd")),
                "provider-billing",
            ),
        )
    )

    message_options = "".join(
        f'<option value="{html.escape(message_id, quote=True)}">{html.escape(message_id)}</option>'
        for message_id in source.contract.message_ids
    )
    batch_options = "".join(
        f'<option value="{time_step}">{time_step + 1:02d}</option>' for time_step in range(source.contract.horizon)
    )
    source_schema = _source_schema(source)
    if source_schema == FULL_POOL_SOURCE_V4_SCHEMA:
        facts = getattr(source, "facts", None)
        if not isinstance(facts, StrictFullPoolSourceFacts):
            raise _FullPoolPresentationError("source-v4 presentation lacks typed persisted facts")
        source_artifacts = ("manifest.json", *tuple(sorted(facts.artifact_hashes)))
    elif source_schema == FULL_POOL_SOURCE_V3_SCHEMA:
        facts = getattr(source, "facts", None)
        if not isinstance(facts, AutomatedFullPoolSourceFacts):
            raise _FullPoolPresentationError("source-v3 presentation lacks typed persisted facts")
        source_artifacts = ("manifest.json", *tuple(sorted(facts.artifact_hashes)))
    elif source_schema == "full-pool-segmented-source-v2":
        source_artifacts = (
            "manifest.json",
            "candidate_rows.jsonl",
            "pair_rows.jsonl",
            "terminal_rows.jsonl",
            "steps.jsonl",
        )
    else:
        source_artifacts = (
            "manifest.json",
            "contract.json",
            "schema.json",
            "aggregates.json",
            "diagnostics.json",
            "candidate_rows.jsonl",
            "pair_rows.jsonl",
            "terminal_rows.jsonl",
        )
    source_downloads = "".join(
        f'<li><a class="full-pool-download-link" href="{_FULL_POOL_SOURCE_DIR}/{html.escape(relative_path, quote=True)}" download>{html.escape(relative_path)}</a></li>'
        for relative_path in source_artifacts
    )
    result_projection_html = (
        result_projection.html_fragment if result_projection is not None else ""
    )
    mechanism = _mechanism_html(catalog)
    main = f"""
<section id="full-pool-main" class="full-pool-hero" data-testid="full-pool-main-experiment">
  <div class="full-pool-hero-copy">
    {_i18n(catalog, "shell.status", tag="p")}
    {_i18n(catalog, "shell.title", tag="h1")}
    {_i18n(catalog, "shell.lead", tag="p")}
  </div>
  <div class="full-pool-hero-contract" aria-label="Full-Pool production contract">
    <strong>36,400</strong><span>users</span>
    <strong>109,200</strong><span>Primary Decisions</span>
    <strong>30</strong><span>batches</span>
  </div>
  <div class="full-pool-language" role="group" aria-label="{html.escape(catalog["zh-CN"]["shell.language"], quote=True)}" data-full-pool-i18n-aria-label="shell.language">
    <button type="button" data-full-pool-language="zh-CN" aria-pressed="true">中文</button>
    <button type="button" data-full-pool-language="en-US" aria-pressed="false">English</button>
  </div>
  <nav class="full-pool-nav" aria-label="Full-Pool report">
    <a href="#full-pool-scope">{_i18n(catalog, "nav.scope")}</a>
    <a href="#full-pool-trajectory">{_i18n(catalog, "nav.trajectory")}</a>
    <a href="#full-pool-response">{_i18n(catalog, "nav.response")}</a>
    <a href="#full-pool-provider">{_i18n(catalog, "nav.provider")}</a>
    <a href="#full-pool-mechanism">{_i18n(catalog, "nav.mechanism")}</a>
    <a href="#full-pool-trace">{_i18n(catalog, "nav.trace")}</a>
    <a href="#full-pool-downloads">{_i18n(catalog, "nav.downloads")}</a>
  </nav>
</section>
<section id="full-pool-scope" class="full-pool-section" data-testid="full-pool-run-evidence">
  {_i18n(catalog, "scope.title", tag="h2")}
  {_i18n(catalog, "scope.copy", tag="p")}
  <div class="full-pool-scope-grid">
    <article><h3>{_i18n(catalog, "scope.target")}</h3><dl>{target_facts}</dl></article>
    <article><h3>{_i18n(catalog, "scope.actual")}</h3><dl>{actual_facts}</dl></article>
  </div>
  <code class="full-pool-source-facts">actual-users={actual_users} actual-primary-terminals={actual_terminals} source-schema={html.escape(str(_source_schema(source)))} requested-model={html.escape(requested_model)} evidence-profile={html.escape(evidence_profile)} production_deploy_eligible=false</code>
  {segmented_lineage}
  <aside class="full-pool-claim-boundary" data-testid="full-pool-claim-boundary">
    {_i18n(catalog, "claims.title", tag="h3")}
    <ul><li>{_i18n(catalog, "claims.order")}</li><li>{_i18n(catalog, "claims.change")}</li><li>{_i18n(catalog, "claims.limit")}</li></ul>
  </aside>
</section>
<section id="full-pool-trajectory" class="full-pool-section" data-testid="full-pool-batch-trajectory">
  {_i18n(catalog, "trajectory.title", tag="h2")}
  {_i18n(catalog, "trajectory.copy", tag="p")}
  <ol class="full-pool-batch-list">{"".join(batch_rows)}</ol>
</section>
<section id="full-pool-response" class="full-pool-section" data-testid="full-pool-message-response">
  {_i18n(catalog, "response.title", tag="h2")}
  {_i18n(catalog, "response.copy", tag="p")}
  <div class="full-pool-table-wrap"><table aria-label="{html.escape(catalog["zh-CN"]["response.title"], quote=True)}" data-full-pool-i18n-aria-label="response.title"><thead><tr>
    <th>{_i18n(catalog, "response.message")}</th><th>{_i18n(catalog, "trajectory.exposures")}</th>
    <th>{_i18n(catalog, "trajectory.success")}</th><th>{_i18n(catalog, "trajectory.failures")}</th>
    <th>{_i18n(catalog, "response.actions")}</th><th>{_i18n(catalog, "response.exposure_rate")}</th>
    <th>{_i18n(catalog, "response.decision_rate")}</th>
  </tr></thead><tbody>{message_rows}</tbody></table></div>
</section>
{result_projection_html}
<section id="full-pool-provider" class="full-pool-section" data-testid="full-pool-provider-accounting">
  {_i18n(catalog, "provider.title", tag="h2")}
  {_i18n(catalog, "provider.copy", tag="p")}
  <dl class="full-pool-provider-grid">{provider_facts}</dl>
</section>
{mechanism}
<section id="full-pool-trace" class="full-pool-section" data-testid="full-pool-trace-reader" data-trace-state="loading" aria-busy="true" data-trace-index-schema="{_TRACE_INDEX_SCHEMA}" data-trace-index-sha256="{index_sha256}">
  {_i18n(catalog, "trace.title", tag="h2")}
  {_i18n(catalog, "trace.copy", tag="p")}
  <p class="full-pool-trace-status" data-testid="full-pool-trace-state" data-trace-state="loading" role="status" aria-live="polite" aria-atomic="true">{html.escape(catalog["zh-CN"]["trace.loading_index"])}</p>
  <div class="full-pool-trace-controls">
    <label>{_i18n(catalog, "trace.message")}<select data-testid="full-pool-trace-message" disabled>{message_options}</select></label>
    <label>{_i18n(catalog, "trace.batch")}<select data-testid="full-pool-trace-batch" disabled>{batch_options}</select></label>
    <label>{_i18n(catalog, "trace.search")}<input data-testid="full-pool-trace-search" type="search" disabled></label>
    <label>{_i18n(catalog, "trace.action")}<select data-testid="full-pool-trace-action" disabled><option value="">{_i18n(catalog, "trace.all_actions")}</option><option value="like">like</option><option value="comment">comment</option><option value="share">share</option><option value="ignore">ignore</option><option value="provider_failed">provider_failed</option></select></label>
  </div>
  <p data-testid="full-pool-trace-filtered-count">{_i18n(catalog, "trace.results")}: <strong>0</strong></p>
  <nav class="full-pool-trace-pagination" data-testid="full-pool-trace-pagination" aria-label="{html.escape(catalog["zh-CN"]["trace.pagination"], quote=True)}" data-full-pool-i18n-aria-label="trace.pagination">
    <button type="button" data-full-pool-trace-page="previous" aria-label="{html.escape(catalog["zh-CN"]["trace.previous"], quote=True)}" data-full-pool-i18n-aria-label="trace.previous" disabled>{_i18n(catalog, "trace.previous")}</button>
    <p data-testid="full-pool-trace-page-status" role="status" aria-live="polite" aria-atomic="true">第 1 / 1 页 · 0-0 / 0</p>
    <button type="button" data-full-pool-trace-page="next" aria-label="{html.escape(catalog["zh-CN"]["trace.next"], quote=True)}" data-full-pool-i18n-aria-label="trace.next" disabled>{_i18n(catalog, "trace.next")}</button>
  </nav>
  <div class="full-pool-table-wrap"><table data-testid="full-pool-trace-table" aria-label="{html.escape(catalog["zh-CN"]["trace.title"], quote=True)}" data-full-pool-i18n-aria-label="trace.title" hidden>
    <thead><tr><th>{_i18n(catalog, "trace.user")}</th><th>{_i18n(catalog, "trace.message")}</th><th>{_i18n(catalog, "trace.batch")}</th><th>{_i18n(catalog, "trace.status")}</th><th>{_i18n(catalog, "trace.action")}</th><th>{_i18n(catalog, "trace.probability")}</th><th>{_i18n(catalog, "trace.reason")}</th><th></th></tr></thead>
    <tbody data-testid="full-pool-trace-table-body"></tbody>
  </table></div>
  <aside class="full-pool-trace-drawer" data-testid="full-pool-trace-drawer" role="dialog" aria-modal="true" aria-labelledby="full-pool-trace-drawer-title" hidden>
    <div class="full-pool-trace-drawer-backdrop" aria-hidden="true"></div>
    <div class="full-pool-trace-drawer-surface">
      <header><h3 id="full-pool-trace-drawer-title">{_i18n(catalog, "trace.detail")}</h3><button type="button" data-testid="full-pool-trace-drawer-close" aria-label="{html.escape(catalog["zh-CN"]["trace.close"], quote=True)}" data-full-pool-i18n-aria-label="trace.close">×</button></header>
      <pre data-testid="full-pool-trace-detail"></pre>
    </div>
  </aside>
</section>
<section id="full-pool-downloads" class="full-pool-section" data-testid="full-pool-downloads">
  {_i18n(catalog, "downloads.title", tag="h2")}
  {_i18n(catalog, "downloads.copy", tag="p")}
  <ul class="full-pool-download-list">
    <li><a class="full-pool-download-link" href="{_TRACE_INDEX_PATH}" download>{_TRACE_INDEX_PATH}</a></li>
    <li><a class="full-pool-download-link" href="{_FULL_POOL_MASTER}" download>{_FULL_POOL_MASTER}</a></li>
    {source_downloads}
  </ul>
</section>
"""
    return main, catalog


def _prefix_historical_links(
    document: str,
    historical_inventory: Mapping[str, str],
) -> str:
    rendered = document
    for relative_path in sorted(historical_inventory, key=len, reverse=True):
        escaped = html.escape(relative_path, quote=True)
        marker = f'href="{escaped}"'
        if marker in rendered:
            rendered = rendered.replace(
                marker,
                f'href="{_HISTORICAL_DIR}/{escaped}"',
            )
    return rendered


def _compose_html(
    historical_html: bytes,
    historical_inventory: Mapping[str, str],
    full_pool_main: str,
    catalog: Mapping[str, Mapping[str, str]],
    *,
    source: _ClosedFullPoolSource | ClosedFullPoolTwoStageSource,
    index_sha256: str,
    production_release: tuple[str, str] | None = None,
) -> bytes:
    try:
        document = historical_html.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _FullPoolPresentationError("historical report HTML is not UTF-8") from exc
    if (
        document.count("<body>") != 1
        or document.count("</body>") != 1
        or document.count('<main class="editorial-report"') != 1
        or document.count("</main>") != 1
        or document.count("</head>") != 1
    ):
        raise _FullPoolPresentationError("historical report does not expose one stable composition shell")
    document = _prefix_historical_links(document, historical_inventory)
    title_pattern = re.compile(
        r'<title data-i18n="shell\.brand">.*?</title>',
        re.DOTALL,
    )
    if len(title_pattern.findall(document)) != 1:
        raise _FullPoolPresentationError("historical report title marker is missing or duplicated")
    document = title_pattern.sub(
        f'<title data-full-pool-i18n="shell.title">{html.escape(catalog["zh-CN"]["shell.title"])}</title>',
        document,
        count=1,
    )
    body_open = document.index("<body>") + len("<body>")
    root_open = document.index('<main class="editorial-report"', body_open)
    root_close = document.index("</main>", root_open)
    root_fragment = document[root_open:root_close].replace(
        '<main class="editorial-report"',
        '<div class="editorial-report"',
        1,
    )
    before = document[:body_open]
    after_root = document[root_close + len("</main>") :]
    historical_heading = (
        '<section class="full-pool-history" data-testid="historical-sensitivity-1000">'
        '<header class="full-pool-history-heading">'
        f"{_i18n(catalog, 'history.title', tag='h2')}"
        f"{_i18n(catalog, 'history.copy', tag='p')}"
        "<p><code>historical-denominator=1,000 users</code></p>"
        "</header>"
    )
    realized_attributes = (
        f'data-presentation-semantics="{_TWO_STAGE_TRACE_SEMANTICS}" '
        f'data-source-classification="{html.escape(source.classification, quote=True)}" '
        f'data-formal-research-evidence="{str(source.formal_research_evidence).lower()}" '
        if isinstance(source, ClosedFullPoolTwoStageSource)
        else ""
    )
    presentation_eligibility = "true" if production_release is not None else "false"
    wrapper = (
        '<main class="full-pool-presentation" data-testid="full-pool-presentation" '
        f'{realized_attributes}'
        f'data-production-deploy-eligible="{presentation_eligibility}" '
        'data-provider-calls-during-composition="0" '
        'data-image-generation-triggered="false" '
        'data-canonical-deployment-triggered="false" '
        f'data-full-pool-source-identity="{html.escape(source.source_identity, quote=True)}" '
        f'data-full-pool-source-manifest-sha256="{source.manifest_sha256}" '
        f'data-full-pool-trace-index-sha256="{index_sha256}">'
        f"{full_pool_main}{historical_heading}{root_fragment}</div></section></main>"
    )
    rendered = before + wrapper + after_root
    catalog_json = json.dumps(catalog, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    script = (
        _FULL_POOL_RUNTIME.replace("__FULL_POOL_CATALOG__", catalog_json)
        .replace("__TRACE_INDEX_SHA256__", index_sha256)
        .replace("__TRACE_INDEX_PATH__", _TRACE_INDEX_PATH)
    )
    release_metadata = ""
    if production_release is not None:
        release_id, release_contract_schema = production_release
        release_metadata = (
            f'<meta name="abm-release-id" content="{html.escape(release_id, quote=True)}">'
            f'<meta name="abm-release-contract" content="{html.escape(release_contract_schema, quote=True)}">\n'
        )
    rendered = rendered.replace(
        "</head>",
        f'{release_metadata}<link rel="icon" href="data:,"><style>{_FULL_POOL_CSS}</style>\n</head>',
        1,
    )
    rendered = rendered.replace("</body>", f"<script>{script}</script>\n</body>", 1)
    payload = rendered.encode("utf-8")
    if len(payload) >= _MAX_REPORT_HTML_BYTES:
        raise _FullPoolPresentationError("report.html exceeds the 3 MiB presentation limit")
    return payload


def compose_full_pool_presentation_bundle(
    *,
    source: _ClosedFullPoolSource | ClosedFullPoolTwoStageSource,
    historical_candidate: Path,
    historical_inventory: Mapping[str, str],
    destination: Path,
) -> Path:
    destination_parent = destination.parent
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.full-pool-", dir=destination_parent))
    try:
        _copy_tree_exact(source.root, staging / _FULL_POOL_SOURCE_DIR)
        _copy_tree_exact(historical_candidate, staging / _HISTORICAL_DIR)
        result_projection: FullPoolResultProjection | None = None
        source_schema = _source_schema(source)
        if source_schema == FULL_POOL_SOURCE_V4_SCHEMA:
            result_projection = compose_strict_full_pool_result_projection(cast(Any, source))
        elif source_schema == FULL_POOL_SOURCE_V3_SCHEMA:
            result_projection = compose_full_pool_result_projection(
                cast(Any, source),
                historical_artifact_hashes=historical_inventory,
            )
        if result_projection is not None:
            (staging / result_projection.csv_filename).write_bytes(
                result_projection.csv_bytes
            )
            (staging / result_projection.lineage_filename).write_bytes(
                result_projection.lineage_bytes
            )
        realized_projection: _RealizedPresentationProjection | None = None
        if isinstance(source, ClosedFullPoolTwoStageSource):
            master = _MECHANISM_PRESENTATION.build_full_pool_two_stage_master().mermaid_artifacts[0]
            realized_projection = _realized_trace_projection(
                source,
                partition_sink=lambda relative_path, payload: _write_partition(
                    staging, relative_path, payload
                ),
            )
            trace = realized_projection.trace
        else:
            master = _MECHANISM_PRESENTATION.build_full_pool_master().mermaid_artifacts[0]
            trace = _trace_projection(
                source,
                partition_sink=lambda relative_path, payload: _write_partition(
                    staging, relative_path, payload
                ),
            )
        if master.filename != _FULL_POOL_MASTER:
            raise _FullPoolPresentationError("Full-Pool mechanism filename is crossed")
        (staging / _FULL_POOL_MASTER).write_bytes(master.payload)
        index_path = staging / _TRACE_INDEX_PATH
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_bytes(trace.index_payload)
        historical_html_path = historical_candidate / "report.html"
        _require_regular_file(historical_html_path, "historical report.html")
        if isinstance(source, ClosedFullPoolTwoStageSource):
            if realized_projection is None:
                raise _FullPoolPresentationError("realized presentation projection is missing")
            full_pool_main, catalog = _render_realized_full_pool_main(
                source,
                realized_projection,
                index_sha256=trace.index_sha256,
            )
        else:
            full_pool_main, catalog = _render_full_pool_main(
                source,
                trace,
                index_sha256=trace.index_sha256,
                result_projection=result_projection,
            )
        report_html = _compose_html(
            historical_html_path.read_bytes(),
            historical_inventory,
            full_pool_main,
            catalog,
            source=source,
            index_sha256=trace.index_sha256,
        )
        (staging / "report.html").write_bytes(report_html)
        validate_full_pool_presentation_bundle(
            staging,
            source=source,
            historical_candidate=historical_candidate,
        )
        os.replace(staging, destination)
        return destination
    except Exception:
        if staging.is_dir() and not staging.is_symlink():
            shutil.rmtree(staging)
        raise


def render_full_pool_two_stage_production_html(
    bundle_root: Path,
    *,
    source: ClosedFullPoolTwoStageSource,
    historical_candidate: Path,
    release_id: str,
    release_contract_schema: str,
) -> bytes:
    """Regenerate production HTML from persisted facts; never relabel candidate bytes."""
    if (
        source.classification != FULL_POOL_TWO_STAGE_FORMAL_CLASSIFICATION
        or source.formal_research_evidence is not True
        or source.production_deploy_eligible is not True
    ):
        raise _FullPoolPresentationError(
            "production rendering requires a formal realized source"
        )
    root = _require_real_directory(bundle_root, "formal Full-Pool presentation candidate")
    historical = _require_real_directory(
        historical_candidate,
        "historical presentation candidate",
    )
    validate_full_pool_presentation_bundle(
        root,
        source=source,
        historical_candidate=historical,
    )
    realized_projection = _realized_trace_projection(
        source,
        partition_sink=lambda relative_path, payload: _compare_partition(
            root,
            relative_path,
            payload,
        ),
    )
    full_pool_main, catalog = _render_realized_full_pool_main(
        source,
        realized_projection,
        index_sha256=realized_projection.trace.index_sha256,
        production=True,
    )
    historical_hashes = _file_hashes(historical)
    historical_report = historical / "report.html"
    _require_regular_file(historical_report, "historical report.html")
    return _compose_html(
        historical_report.read_bytes(),
        historical_hashes,
        full_pool_main,
        catalog,
        source=source,
        index_sha256=realized_projection.trace.index_sha256,
        production_release=(release_id, release_contract_schema),
    )


def _strict_projection_schema_from_bundle(bundle_root: Path) -> str:
    lineage_path = bundle_root / FULL_POOL_RESULT_LINEAGE_MARKDOWN
    _require_regular_file(lineage_path, FULL_POOL_RESULT_LINEAGE_MARKDOWN)
    try:
        lineage = lineage_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise _FullPoolPresentationError("Full-Pool result lineage is not UTF-8") from exc
    matched = [
        schema
        for schema in (
            STRICT_FULL_POOL_RESULT_PROJECTION_SCHEMA_V1,
            STRICT_FULL_POOL_RESULT_PROJECTION_SCHEMA_V2,
        )
        if f"- schema: `{schema}`" in lineage
    ]
    if len(matched) != 1:
        raise _FullPoolPresentationError("Full-Pool result projection schema is missing or crossed")
    return matched[0]


def validate_full_pool_presentation_bundle(
    bundle_root: Path,
    *,
    source: _ClosedFullPoolSource | ClosedFullPoolTwoStageSource,
    historical_candidate: Path,
) -> None:
    root = _require_real_directory(bundle_root, "Full-Pool presentation bundle")
    historical = _require_real_directory(historical_candidate, "historical presentation candidate")
    source_copy = root / _FULL_POOL_SOURCE_DIR
    historical_copy = root / _HISTORICAL_DIR
    if _file_hashes(source_copy) != _file_hashes(source.root):
        raise _FullPoolPresentationError("Full-Pool source copy differs from closed source")
    historical_hashes = _file_hashes(historical)
    if _file_hashes(historical_copy) != historical_hashes:
        raise _FullPoolPresentationError("historical presentation copy differs from its approved candidate")
    result_projection: FullPoolResultProjection | None = None
    source_schema = _source_schema(source)
    if source_schema == FULL_POOL_SOURCE_V4_SCHEMA:
        result_projection = compose_strict_full_pool_result_projection(
            cast(Any, source),
            schema_version=_strict_projection_schema_from_bundle(root),
        )
    elif source_schema == FULL_POOL_SOURCE_V3_SCHEMA:
        result_projection = compose_full_pool_result_projection(
            cast(Any, source),
            historical_artifact_hashes=historical_hashes,
        )
    if result_projection is not None:
        for relative_path, expected in (
            (result_projection.csv_filename, result_projection.csv_bytes),
            (result_projection.lineage_filename, result_projection.lineage_bytes),
        ):
            path = root / relative_path
            _require_regular_file(path, relative_path)
            if path.read_bytes() != expected:
                raise _FullPoolPresentationError(
                    "source-v3/v4 result delivery is malformed, non-canonical, or crossed"
                )
    elif any(
        (root / relative_path).exists() or (root / relative_path).is_symlink()
        for relative_path in (FULL_POOL_RESULT_CSV, FULL_POOL_RESULT_LINEAGE_MARKDOWN)
    ):
        raise _FullPoolPresentationError("historical Full-Pool bundle contains source-v3 delivery")
    realized_projection: _RealizedPresentationProjection | None = None
    if isinstance(source, ClosedFullPoolTwoStageSource):
        realized_projection = _realized_trace_projection(
            source,
            partition_sink=lambda relative_path, payload: _compare_partition(
                root, relative_path, payload
            ),
        )
        trace = realized_projection.trace
        message_ids = source.message_ids
        horizon = source.horizon
    else:
        trace = _trace_projection(
            source,
            partition_sink=lambda relative_path, payload: _compare_partition(
                root, relative_path, payload
            ),
        )
        message_ids = source.contract.message_ids
        horizon = source.contract.horizon
    index_path = root / _TRACE_INDEX_PATH
    _require_regular_file(index_path, "Full-Pool trace index")
    if index_path.read_bytes() != trace.index_payload:
        raise _FullPoolPresentationError("Full-Pool trace index is malformed, non-canonical, or crossed")
    expected_trace_files = {
        _TRACE_INDEX_PATH,
        *(
            f"trace/{message_id}/batch-{time_step:06d}.json"
            for message_id in message_ids
            for time_step in range(horizon)
        ),
    }
    actual_trace_files = {
        path.relative_to(root).as_posix()
        for path in (root / "trace").rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    if actual_trace_files != expected_trace_files:
        raise _FullPoolPresentationError("Full-Pool trace inventory has missing or extra partitions")
    for path in (root / "trace").rglob("*"):
        if path.is_symlink() or (not path.is_dir() and not stat.S_ISREG(path.stat(follow_symlinks=False).st_mode)):
            raise _FullPoolPresentationError("Full-Pool trace inventory contains a symlink or non-regular file")

    master = (
        _MECHANISM_PRESENTATION.build_full_pool_two_stage_master().mermaid_artifacts[0]
        if isinstance(source, ClosedFullPoolTwoStageSource)
        else _MECHANISM_PRESENTATION.build_full_pool_master().mermaid_artifacts[0]
    )
    master_path = root / _FULL_POOL_MASTER
    _require_regular_file(master_path, "Full-Pool mechanism master")
    if master_path.read_bytes() != master.payload:
        raise _FullPoolPresentationError("Full-Pool mechanism master bytes are crossed")
    mermaid_paths = sorted(root.rglob("*.mmd"))
    expected_mermaid_paths = {
        _FULL_POOL_MASTER,
        *(f"{_HISTORICAL_DIR}/{filename}" for filename in _HISTORICAL_MERMAID_FILENAMES),
    }
    actual_mermaid_paths = {path.relative_to(root).as_posix() for path in mermaid_paths}
    if actual_mermaid_paths != expected_mermaid_paths:
        raise _FullPoolPresentationError("presentation bundle Mermaid inventory is incomplete, duplicated, or extra")
    for filename in _HISTORICAL_MERMAID_FILENAMES:
        if (historical_copy / filename).read_bytes() != (historical / filename).read_bytes():
            raise _FullPoolPresentationError(f"historical Mermaid bytes changed: {filename}")

    report_path = root / "report.html"
    _require_regular_file(report_path, "Full-Pool report.html")
    report_payload = report_path.read_bytes()
    if len(report_payload) >= _MAX_REPORT_HTML_BYTES:
        raise _FullPoolPresentationError("report.html exceeds the 3 MiB presentation limit")
    try:
        report = report_payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _FullPoolPresentationError("report.html is not UTF-8") from exc
    if isinstance(source, ClosedFullPoolTwoStageSource):
        if realized_projection is None:
            raise _FullPoolPresentationError("realized presentation projection is missing")
        expected_main, expected_catalog = _render_realized_full_pool_main(
            source,
            realized_projection,
            index_sha256=trace.index_sha256,
        )
        historical_report_path = historical / "report.html"
        _require_regular_file(historical_report_path, "historical report.html")
        expected_report = _compose_html(
            historical_report_path.read_bytes(),
            historical_hashes,
            expected_main,
            expected_catalog,
            source=source,
            index_sha256=trace.index_sha256,
        )
        if report_payload != expected_report:
            raise _FullPoolPresentationError(
                "realized Full-Pool report bytes differ from persisted facts"
            )
    result_markers = (
        (
            'data-testid="full-pool-realized-headline"',
            'data-testid="full-pool-overall-result"',
            'data-testid="full-pool-message-result-table"',
            'data-testid="full-pool-segment-result-table"',
            'data-testid="full-pool-segment-results"',
            'data-testid="full-pool-segment-table"',
            'data-testid="full-pool-probability-contract"',
            'data-testid="full-pool-feedback-trajectory"',
            'data-testid="full-pool-mechanism-svg"',
            f'data-presentation-semantics="{_TWO_STAGE_TRACE_SEMANTICS}"',
            f'data-source-classification="{source.classification}"',
        )
        if isinstance(source, ClosedFullPoolTwoStageSource)
        else (
            (
                'data-testid="full-pool-segment-results"',
                'data-testid="full-pool-segment-table"',
                f'href="{FULL_POOL_RESULT_CSV}"',
                f'href="{FULL_POOL_RESULT_LINEAGE_MARKDOWN}"',
            )
            if result_projection is not None
            else ()
        )
    )
    required_markers = (
        'data-testid="full-pool-presentation"',
        'data-production-deploy-eligible="false"',
        'data-provider-calls-during-composition="0"',
        'data-image-generation-triggered="false"',
        'data-canonical-deployment-triggered="false"',
        'data-testid="full-pool-main-experiment"',
        'data-testid="full-pool-run-evidence"',
        *(() if isinstance(source, ClosedFullPoolTwoStageSource) else ('data-testid="full-pool-message-response"',)),
        'data-testid="full-pool-provider-accounting"',
        'data-testid="full-pool-mechanism-section"',
        'data-testid="full-pool-trace-reader"',
        'data-testid="full-pool-trace-pagination"',
        'data-testid="full-pool-trace-page-status"',
        'data-full-pool-trace-page="previous"',
        'data-full-pool-trace-page="next"',
        'data-testid="historical-sensitivity-1000"',
        f'data-full-pool-source-manifest-sha256="{source.manifest_sha256}"',
        f'data-full-pool-trace-index-sha256="{trace.index_sha256}"',
        "production_deploy_eligible=false",
        _TRACE_INDEX_SCHEMA,
        *result_markers,
    )
    missing_markers = [marker for marker in required_markers if marker not in report]
    if (
        missing_markers
        or report.count(
            '<main class="full-pool-presentation" data-testid="full-pool-presentation" '
        )
        != 1
    ):
        raise _FullPoolPresentationError(
            "Full-Pool report markers are missing, duplicated, or crossed: "
            + ", ".join(missing_markers)
        )
    if (
        'data-production-deploy-eligible="true"' in report
        or "presentation_candidate_production_deploy_eligible=true" in report
        or re.search(
            r"<(?:script|link|img)\b[^>]*(?:src|href)=[\"']https?://",
            report,
            re.IGNORECASE,
        )
        or "mermaid.min.js" in report
        or "full-pool-trace-inline-data" in report
    ):
        raise _FullPoolPresentationError("Full-Pool report crosses eligibility or offline resource boundaries")
    if isinstance(source, ClosedFullPoolTwoStageSource):
        try:
            _, first_terminal = next(source.iter_pair_terminal_rows())
        except StopIteration as exc:
            raise _FullPoolPresentationError("realized source contains no terminal") from exc
        first_terminal_id = _non_empty_string(
            first_terminal.get("realized_terminal_id"),
            "realized terminal id",
        )
        source_download_paths = {
            f"{_FULL_POOL_SOURCE_DIR}/manifest.json",
            *(
                f"{_FULL_POOL_SOURCE_DIR}/{relative_path}"
                for relative_path in source.artifact_hashes
            ),
        }
    else:
        source_first_batch = source.read_batch(0)
        source_rows = _strict_mapping(source_first_batch.get("rows"), "source rows")
        first_terminal = _strict_rows(source_rows.get("terminal_rows"), "terminal rows")[0]
        first_terminal_id = _non_empty_string(first_terminal.get("terminal_row_id"), "terminal_row_id")
        source_download_paths = {
            f"{_FULL_POOL_SOURCE_DIR}/manifest.json",
            f"{_FULL_POOL_SOURCE_DIR}/candidate_rows.jsonl",
            f"{_FULL_POOL_SOURCE_DIR}/pair_rows.jsonl",
            f"{_FULL_POOL_SOURCE_DIR}/terminal_rows.jsonl",
        }
        facts = getattr(source, "facts", None)
        if isinstance(facts, (AutomatedFullPoolSourceFacts, StrictFullPoolSourceFacts)):
            source_download_paths.update(
                f"{_FULL_POOL_SOURCE_DIR}/{relative_path}"
                for relative_path in facts.artifact_hashes
            )
    if first_terminal_id in report:
        raise _FullPoolPresentationError(
            "report.html embeds Full-Pool terminal rows instead of lazy-loading partitions"
        )
    result_download_paths = (
        {FULL_POOL_RESULT_CSV, FULL_POOL_RESULT_LINEAGE_MARKDOWN}
        if result_projection is not None
        else set()
    )
    for relative_path in (
        expected_mermaid_paths
        | {_TRACE_INDEX_PATH}
        | source_download_paths
        | result_download_paths
    ):
        if f'href="{relative_path}"' not in report and relative_path != f"{_HISTORICAL_DIR}/report.html":
            raise _FullPoolPresentationError(f"Full-Pool report is missing a required download href: {relative_path}")

    root_entries = {path.name for path in root.iterdir()}
    expected_root_entries = {
        "report.html",
        _FULL_POOL_MASTER,
        _FULL_POOL_SOURCE_DIR,
        _HISTORICAL_DIR,
        "trace",
    }
    if result_projection is not None:
        expected_root_entries.update(
            {FULL_POOL_RESULT_CSV, FULL_POOL_RESULT_LINEAGE_MARKDOWN}
        )
    if root_entries != expected_root_entries:
        raise _FullPoolPresentationError(
            "Full-Pool bundle root contains a payload, manifest, closure, release contract, or extra artifact"
        )


_FULL_POOL_CSS = r"""
:root {
  --fp-ink: #17212b;
  --fp-muted: #526170;
  --fp-paper: #f6f7f8;
  --fp-surface: #ffffff;
  --fp-line: #cfd7df;
  --fp-accent: #2459a9;
  --fp-accent-soft: #e9f0fa;
  --fp-warn: #8a4b12;
  --fp-radius: 12px;
}
html { scroll-behavior: smooth; }
.full-pool-presentation { color: var(--fp-ink); background: var(--fp-paper); }
.full-pool-hero, .full-pool-section, .full-pool-history-heading {
  width: min(1180px, calc(100% - 48px)); margin-inline: auto;
}
.full-pool-hero { min-height: min(720px, 100dvh); padding: 72px 0 56px; display: grid; grid-template-columns: 1.35fr .65fr; gap: 40px; align-content: center; }
.full-pool-hero-copy > p:first-child { margin: 0 0 18px; color: var(--fp-accent); font: 700 13px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .08em; }
.full-pool-hero h1 { margin: 0; max-width: 12ch; word-break: keep-all; font: 780 clamp(3rem, 8vw, 6.8rem)/.93 ui-sans-serif, system-ui, sans-serif; letter-spacing: -.065em; }
.full-pool-hero-copy > p:last-child { max-width: 56ch; margin: 28px 0 0; color: var(--fp-muted); font: 500 18px/1.7 ui-sans-serif, system-ui, sans-serif; }
.full-pool-hero-contract { align-self: end; display: grid; grid-template-columns: auto 1fr; gap: 10px 16px; padding: 28px; border: 1px solid var(--fp-line); border-radius: var(--fp-radius); background: var(--fp-surface); }
.full-pool-hero-contract strong { color: var(--fp-accent); font: 750 30px/1 ui-monospace, SFMono-Regular, Menlo, monospace; }
.full-pool-hero-contract span { align-self: center; color: var(--fp-muted); }
.full-pool-realized-headline { align-self: end; display: grid; gap: 10px; padding: 28px; border: 1px solid var(--fp-line); border-radius: var(--fp-radius); background: var(--fp-surface); }
.full-pool-realized-headline span { color: var(--fp-muted); font-size: 13px; }
.full-pool-realized-headline strong { color: var(--fp-accent); font: 760 clamp(1.8rem, 4vw, 3.4rem)/1 ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: -.04em; }
.full-pool-realized-headline b { font: 700 20px/1.2 ui-monospace, SFMono-Regular, Menlo, monospace; }
.full-pool-language { grid-column: 1 / -1; display: flex; gap: 8px; }
.full-pool-language button { min-height: 42px; padding: 0 16px; border: 1px solid var(--fp-line); border-radius: 8px; color: var(--fp-ink); background: var(--fp-surface); cursor: pointer; }
.full-pool-language button[aria-pressed="true"] { border-color: var(--fp-accent); color: var(--fp-accent); background: var(--fp-accent-soft); }
.full-pool-nav { grid-column: 1 / -1; display: flex; gap: 8px 20px; flex-wrap: wrap; padding-top: 18px; border-top: 1px solid var(--fp-line); }
.full-pool-nav a, .full-pool-download-link { color: var(--fp-accent); text-underline-offset: 4px; }
.full-pool-section { padding: 88px 0; border-top: 1px solid var(--fp-line); }
.full-pool-section > h2, .full-pool-history-heading h2 { max-width: 18ch; margin: 0 0 18px; font: 720 clamp(2rem, 5vw, 4.25rem)/1 ui-sans-serif, system-ui, sans-serif; letter-spacing: -.045em; }
.full-pool-section > p, .full-pool-history-heading > p { max-width: 72ch; color: var(--fp-muted); font: 500 16px/1.7 ui-sans-serif, system-ui, sans-serif; }
.full-pool-scope-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 34px; }
.full-pool-scope-grid article { padding: 24px; border: 1px solid var(--fp-line); border-radius: var(--fp-radius); background: var(--fp-surface); }
.full-pool-scope-grid h3 { margin-top: 0; }
.full-pool-scope-grid dl, .full-pool-provider-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.full-pool-fact { min-width: 0; }
.full-pool-fact dt { color: var(--fp-muted); font-size: 13px; }
.full-pool-fact dd { margin: 5px 0 0; overflow-wrap: anywhere; font: 720 21px/1.25 ui-monospace, SFMono-Regular, Menlo, monospace; }
.full-pool-source-facts { display: block; margin-top: 20px; padding: 14px; overflow-wrap: anywhere; border-radius: 8px; background: #e8ebee; }
.full-pool-claim-boundary { margin-top: 28px; padding: 24px; border-left: 5px solid var(--fp-warn); background: #fff8ef; }
.full-pool-claim-boundary h3 { margin-top: 0; }
.full-pool-claim-boundary li + li { margin-top: 10px; }
.full-pool-batch-list { display: grid; gap: 10px; padding: 0; margin: 32px 0 0; list-style: none; }
.full-pool-batch-row { display: grid; grid-template-columns: 90px 1fr; gap: 16px; padding: 14px 0; border-bottom: 1px solid var(--fp-line); }
.full-pool-batch-label { font: 700 13px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace; }
.full-pool-batch-content { min-width: 0; }
.full-pool-batch-messages { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.full-pool-feedback-row { display: flex; flex-wrap: wrap; gap: 8px 20px; margin-top: 8px; padding: 10px 12px; color: var(--fp-muted); background: var(--fp-accent-soft); font: 650 12px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; }
.full-pool-batch-message { display: grid; gap: 4px; padding: 12px; border-left: 4px solid var(--fp-accent); background: var(--fp-surface); }
.full-pool-batch-message[data-message-id="message_2"] { border-left-style: dashed; }
.full-pool-batch-message[data-message-id="message_3"] { border-left-style: double; border-left-width: 7px; }
.full-pool-batch-message span { color: var(--fp-muted); font-size: 12px; }
.full-pool-table-wrap { margin-top: 28px; overflow-x: auto; }
.full-pool-table-wrap table { width: 100%; min-width: 760px; border-collapse: collapse; background: var(--fp-surface); }
.full-pool-table-wrap th, .full-pool-table-wrap td { padding: 13px 12px; border-bottom: 1px solid var(--fp-line); text-align: left; vertical-align: top; }
.full-pool-table-wrap th { font-weight: 700; }
.full-pool-table-wrap th small { display: block; max-width: 28ch; margin-top: 4px; color: var(--fp-muted); font-weight: 400; }
.full-pool-message-mark { display: inline-block; width: 22px; margin-right: 8px; border-top: 3px solid var(--fp-accent); }
tr[data-message-id="message_2"] .full-pool-message-mark { border-top-style: dashed; }
tr[data-message-id="message_3"] .full-pool-message-mark { border-top-style: double; border-top-width: 6px; }
.full-pool-provider-grid { margin-top: 28px; padding: 28px; border: 1px solid var(--fp-line); border-radius: var(--fp-radius); background: var(--fp-surface); }
.full-pool-overall, .full-pool-result-conclusion { margin-top: 32px; padding: 24px; border: 1px solid var(--fp-line); border-radius: var(--fp-radius); background: var(--fp-surface); }
.full-pool-result-conclusion { border-left: 5px solid var(--fp-accent); }
.full-pool-result-conclusion h3, .full-pool-overall h3 { margin-top: 0; }
.full-pool-mechanism-figure-wrap { max-width: 100%; margin-top: 30px; overflow-x: auto; border: 1px solid var(--fp-line); border-radius: var(--fp-radius); background: var(--fp-surface); }
.full-pool-mechanism-svg { display: block; width: 100%; min-width: 980px; height: auto; color: #617285; }
.full-pool-svg-edge path { color: #718398; }
.full-pool-svg-edge circle { fill: var(--fp-surface); stroke: #718398; }
.full-pool-svg-edge text { fill: var(--fp-muted); font: 700 10px/1 ui-monospace, SFMono-Regular, Menlo, monospace; }
.full-pool-svg-node { outline: none; }
.full-pool-svg-node > rect, .full-pool-svg-node > polygon { fill: #fff; stroke: #2459a9; stroke-width: 2; }
.full-pool-svg-node-historical_data > rect, .full-pool-svg-node-historical_data > polygon { fill: #f4f1e8; stroke: #1f2933; }
.full-pool-svg-node-platform_recommendation > rect, .full-pool-svg-node-platform_recommendation > polygon { fill: #eef3fb; }
.full-pool-svg-node:focus > rect, .full-pool-svg-node:focus > polygon { stroke: #b44d12; stroke-width: 4; }
.full-pool-svg-node foreignObject div { display: grid; height: 100%; place-items: start center; overflow-wrap: anywhere; color: var(--fp-ink); font: 650 13px/1.35 ui-sans-serif, system-ui, sans-serif; text-align: center; }
.full-pool-svg-stage { fill: var(--fp-accent); font: 750 11px/1 ui-monospace, SFMono-Regular, Menlo, monospace; }
.full-pool-mechanism-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 30px; }
.full-pool-mechanism-grid > div { padding: 22px; border: 1px solid var(--fp-line); border-radius: var(--fp-radius); background: var(--fp-surface); }
.full-pool-mechanism-grid ol { display: grid; gap: 10px; padding-left: 22px; }
.full-pool-mechanism-node, .full-pool-mechanism-edge { padding: 9px; }
.full-pool-mechanism-node code, .full-pool-mechanism-edge code { display: block; margin-bottom: 4px; color: var(--fp-accent); overflow-wrap: anywhere; }
.full-pool-section details { margin: 24px 0; padding: 16px; border: 1px solid var(--fp-line); border-radius: var(--fp-radius); background: var(--fp-surface); }
.full-pool-section summary { cursor: pointer; font-weight: 700; }
.full-pool-trace-controls { display: grid; grid-template-columns: .8fr .7fr 1.5fr .9fr; gap: 12px; margin-top: 28px; }
.full-pool-trace-controls label { display: grid; gap: 7px; color: var(--fp-muted); font-size: 13px; }
.full-pool-trace-controls select, .full-pool-trace-controls input { min-height: 44px; width: 100%; padding: 8px 10px; border: 1px solid #98a6b4; border-radius: 8px; color: var(--fp-ink); background: var(--fp-surface); }
.full-pool-trace-status { min-height: 24px; margin-top: 20px; font-weight: 700; }
.full-pool-trace-status[data-trace-state="error"] { color: #9a261c; }
.full-pool-trace-pagination { display: flex; align-items: center; justify-content: flex-end; gap: 12px; margin-top: 18px; }
.full-pool-trace-pagination p { min-width: 190px; margin: 0; text-align: center; font-variant-numeric: tabular-nums; }
.full-pool-trace-pagination button, .full-pool-trace-table button { min-height: 40px; border: 1px solid var(--fp-accent); border-radius: 8px; color: var(--fp-accent); background: var(--fp-surface); cursor: pointer; }
.full-pool-trace-pagination button { padding: 8px 14px; }
.full-pool-trace-pagination button:disabled { cursor: not-allowed; opacity: .45; }
.full-pool-trace-table button { min-height: 36px; white-space: nowrap; }
.full-pool-trace-drawer { position: fixed; inset: 0; z-index: 80; }
.full-pool-trace-drawer-backdrop { position: absolute; inset: 0; background: rgb(12 20 28 / .55); }
.full-pool-trace-drawer-surface { position: absolute; top: 0; right: 0; width: min(680px, 92vw); height: 100%; padding: 24px; overflow: auto; color: var(--fp-ink); background: var(--fp-surface); box-shadow: -18px 0 50px rgb(32 48 64 / .2); }
.full-pool-trace-drawer-surface header { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.full-pool-trace-drawer-surface button { min-width: 44px; min-height: 44px; border: 1px solid var(--fp-line); border-radius: 8px; background: var(--fp-surface); }
.full-pool-trace-drawer-surface pre { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; }
.full-pool-download-list { columns: 2; padding-left: 20px; }
.full-pool-download-list li { min-width: 0; break-inside: avoid; margin: 8px 0; }
.full-pool-download-link { overflow-wrap: anywhere; word-break: break-word; }
.full-pool-history { padding: 110px 0 0; border-top: 8px solid var(--fp-ink); background: #fff; }
.full-pool-history-heading { padding-bottom: 54px; }
.full-pool-history > .editorial-report { width: 100%; }
.full-pool-history .editorial-header { top: 0; }
@media (max-width: 767px) {
  html { scroll-behavior: auto; }
  .full-pool-hero, .full-pool-section, .full-pool-history-heading { width: calc(100% - 32px); }
  .full-pool-hero { min-height: auto; grid-template-columns: 1fr; gap: 28px; padding: 48px 0; }
  .full-pool-hero h1 { max-width: none; font-size: clamp(3rem, 16vw, 5rem); }
  .full-pool-hero-contract, .full-pool-realized-headline, .full-pool-language, .full-pool-nav { grid-column: auto; }
  .full-pool-section { padding: 64px 0; }
  .full-pool-scope-grid, .full-pool-mechanism-grid, .full-pool-provider-grid { grid-template-columns: 1fr; }
  .full-pool-batch-row { grid-template-columns: 1fr; }
  .full-pool-batch-messages { grid-template-columns: 1fr; }
  .full-pool-trace-controls { grid-template-columns: 1fr; }
  .full-pool-trace-pagination { justify-content: space-between; }
  .full-pool-trace-pagination p { min-width: 0; }
  .full-pool-download-list { columns: 1; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { scroll-behavior: auto !important; transition-duration: .01ms !important; animation-duration: .01ms !important; }
}
"""


_FULL_POOL_RUNTIME = r"""
(() => {
  'use strict';
  const root = document.querySelector('[data-testid="full-pool-presentation"]');
  const reader = document.querySelector('[data-testid="full-pool-trace-reader"]');
  if (!root || !reader) return;
  const twoStage = reader.dataset.traceSemantics === 'two_stage_realized';
  const catalog = __FULL_POOL_CATALOG__;
  const indexPath = '__TRACE_INDEX_PATH__';
  const expectedIndexSha = '__TRACE_INDEX_SHA256__';
  const status = reader.querySelector('[data-testid="full-pool-trace-state"]');
  const messageSelect = reader.querySelector('[data-testid="full-pool-trace-message"]');
  const batchSelect = reader.querySelector('[data-testid="full-pool-trace-batch"]');
  const searchInput = reader.querySelector('[data-testid="full-pool-trace-search"]');
  const actionSelect = reader.querySelector('[data-testid="full-pool-trace-action"]');
  const count = reader.querySelector('[data-testid="full-pool-trace-filtered-count"] strong');
  const pageStatus = reader.querySelector('[data-testid="full-pool-trace-page-status"]');
  const previousPage = reader.querySelector('[data-full-pool-trace-page="previous"]');
  const nextPage = reader.querySelector('[data-full-pool-trace-page="next"]');
  const table = reader.querySelector('[data-testid="full-pool-trace-table"]');
  const body = reader.querySelector('[data-testid="full-pool-trace-table-body"]');
  const drawer = reader.querySelector('[data-testid="full-pool-trace-drawer"]');
  const drawerClose = reader.querySelector('[data-testid="full-pool-trace-drawer-close"]');
  const detail = reader.querySelector('[data-testid="full-pool-trace-detail"]');
  let index = null;
  let rows = null;
  let generation = 0;
  let controller = null;
  let restoreFocus = null;
  let state = 'loading-index';
  let page = 0;
  const pageSize = 25;

  const language = () => document.documentElement.lang === 'en-US' ? 'en-US' : 'zh-CN';
  const copy = (key) => (catalog[language()] || catalog['zh-CN'])[key] || key;
  const digest = async (bytes) => {
    const hash = await crypto.subtle.digest('SHA-256', bytes);
    return [...new Uint8Array(hash)].map((value) => value.toString(16).padStart(2, '0')).join('');
  };
  const identityDigest = async (ids) => digest(new TextEncoder().encode(JSON.stringify(ids)));
  const setState = (next, messageKey) => {
    state = next;
    const failed = next === 'error';
    const loading = next.startsWith('loading');
    const publicState = loading ? 'loading' : next;
    reader.dataset.traceState = publicState;
    reader.setAttribute('aria-busy', String(loading));
    status.dataset.traceState = publicState;
    status.textContent = copy(messageKey);
    messageSelect.disabled = failed || !index || loading;
    batchSelect.disabled = failed || !index || loading;
    searchInput.disabled = failed || loading || !rows;
    actionSelect.disabled = failed || loading || !rows;
    previousPage.disabled = true;
    nextPage.disabled = true;
    table.hidden = failed || loading || !rows;
  };
  const applyLanguage = (nextLanguage) => {
    const resolved = nextLanguage === 'en-US' ? 'en-US' : 'zh-CN';
    document.querySelectorAll('[data-full-pool-i18n]').forEach((element) => {
      const key = element.dataset.fullPoolI18n;
      if (key && catalog[resolved][key]) element.textContent = catalog[resolved][key];
    });
    document.querySelectorAll('[data-full-pool-i18n-aria-label]').forEach((element) => {
      const key = element.dataset.fullPoolI18nAriaLabel;
      if (key && catalog[resolved][key]) element.setAttribute('aria-label', catalog[resolved][key]);
    });
    document.querySelectorAll('[data-full-pool-language]').forEach((button) => {
      button.setAttribute('aria-pressed', String(button.dataset.fullPoolLanguage === resolved));
    });
    if (state === 'loading-index') setState(state, 'trace.loading_index');
    else if (state === 'loading-partition') setState(state, 'trace.loading_partition');
    else if (state === 'ready') setState(state, 'trace.ready');
    else if (state === 'error') setState(state, 'trace.error');
    render();
  };
  document.querySelectorAll('[data-full-pool-language]').forEach((button) => {
    button.addEventListener('click', () => {
      const next = button.dataset.fullPoolLanguage;
      const historical = document.querySelector(`.editorial-report [data-report-language="${next}"]`);
      if (historical) historical.click();
      document.documentElement.lang = next;
      applyLanguage(next);
    });
  });
  new MutationObserver(() => applyLanguage(language())).observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['lang'],
  });

  const validateRelativePath = (value) => {
    if (typeof value !== 'string' || !value || value.startsWith('/') || value.split('/').includes('..')) {
      throw new Error('unsafe trace partition path');
    }
    const url = new URL(value, document.baseURI);
    if (url.origin !== location.origin) throw new Error('cross-origin trace partition path');
    return value;
  };
  const fetchBytes = async (relativePath, signal) => {
    const response = await fetch(validateRelativePath(relativePath), { cache: 'no-store', signal });
    if (!response.ok) throw new Error(`trace fetch failed: ${response.status}`);
    return new Uint8Array(await response.arrayBuffer());
  };
  const decodeJson = (bytes) => JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
  const validateIndex = async (documentValue, bytes) => {
    if (await digest(bytes) !== expectedIndexSha) throw new Error('trace index hash mismatch');
    if (!documentValue || documentValue.schema_version !== 'full-pool-trace-index-v1'
        || (twoStage && documentValue.trace_semantics !== 'two_stage_realized')
        || (!twoStage && documentValue.trace_semantics != null)
        || documentValue.source_manifest_sha256 !== root.dataset.fullPoolSourceManifestSha256
        || !Array.isArray(documentValue.message_order) || !Array.isArray(documentValue.batch_order)
        || !Array.isArray(documentValue.partitions)
        || documentValue.partition_count !== documentValue.partitions.length
        || typeof documentValue.terminal_count !== 'number') {
      throw new Error('trace index contract mismatch');
    }
    const keys = new Set();
    let total = 0;
    for (const entry of documentValue.partitions) {
      const key = `${entry.message_id}|${entry.time_step}`;
      if (keys.has(key) || !documentValue.message_order.includes(entry.message_id)
          || !documentValue.batch_order.includes(entry.time_step)
          || !/^[0-9a-f]{64}$/.test(entry.sha256)
          || !/^[0-9a-f]{64}$/.test(entry.terminal_identity_sha256)) {
        throw new Error('trace index partition identity mismatch');
      }
      validateRelativePath(entry.relative_path);
      keys.add(key);
      total += entry.row_count;
    }
    if (total !== documentValue.terminal_count) throw new Error('trace index terminal count mismatch');
    return documentValue;
  };
  const selectedEntry = () => {
    if (!index) return null;
    return index.partitions.find((entry) => entry.message_id === messageSelect.value
      && entry.time_step === Number(batchSelect.value));
  };
  const validatePartition = async (documentValue, bytes, entry) => {
    if (await digest(bytes) !== entry.sha256 || bytes.byteLength !== entry.bytes) {
      throw new Error('trace partition hash or byte count mismatch');
    }
    if (!documentValue || documentValue.schema_version !== 'full-pool-trace-partition-v1'
        || (twoStage && documentValue.trace_semantics !== 'two_stage_realized')
        || (!twoStage && documentValue.trace_semantics != null)
        || documentValue.source_identity !== index.source_identity
        || documentValue.source_manifest_sha256 !== index.source_manifest_sha256
        || documentValue.message_id !== entry.message_id
        || documentValue.time_step !== entry.time_step
        || documentValue.row_count !== entry.row_count
        || documentValue.terminal_identity_sha256 !== entry.terminal_identity_sha256
        || !Array.isArray(documentValue.rows)
        || documentValue.rows.length !== entry.row_count) {
      throw new Error('trace partition contract mismatch');
    }
    const ids = [];
    const unique = new Set();
    for (const row of documentValue.rows) {
      if (!row || typeof row.terminal_row_id !== 'string' || unique.has(row.terminal_row_id)
          || row.message_id !== entry.message_id || row.time_step !== entry.time_step
          || row.decision_variant !== 'primary') {
        throw new Error('trace partition row identity mismatch');
      }
      if (twoStage && (!row.provider_judgment || !row.abm_realization
          || row['realized' + '_reason'] != null
          || row.provider_judgment.reason_role !== 'provider_judgment_engagement_intent'
          || row.probability !== row.provider_judgment.probability
          || row.action !== row.abm_realization.action
          || row.engage !== row.abm_realization.engage)) {
        throw new Error('two-stage trace row semantics mismatch');
      }
      unique.add(row.terminal_row_id);
      ids.push(row.terminal_row_id);
    }
    if (await identityDigest(ids) !== entry.terminal_identity_sha256) {
      throw new Error('trace partition terminal digest mismatch');
    }
    return documentValue.rows;
  };

  const closeDrawer = () => {
    drawer.hidden = true;
    document.body.style.overflow = '';
    if (restoreFocus && restoreFocus.isConnected) restoreFocus.focus();
    restoreFocus = null;
  };
  const openDrawer = (row, trigger) => {
    restoreFocus = trigger;
    detail.textContent = JSON.stringify(row, null, 2);
    drawer.hidden = false;
    document.body.style.overflow = 'hidden';
    drawerClose.focus();
  };
  drawerClose.addEventListener('click', closeDrawer);
  drawer.querySelector('.full-pool-trace-drawer-backdrop').addEventListener('click', closeDrawer);
  drawer.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      closeDrawer();
      return;
    }
    if (event.key !== 'Tab') return;
    const focusable = [...drawer.querySelectorAll('button, [href], input, select, [tabindex]:not([tabindex="-1"])')]
      .filter((element) => !element.disabled && !element.hidden);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });

  const render = () => {
    if (!rows || state !== 'ready') return;
    const query = searchInput.value.trim().toLocaleLowerCase(language());
    const action = actionSelect.value;
    const filtered = rows.filter((row) => {
      const provider = row.provider_judgment || {};
      const realization = row.abm_realization || {};
      const haystack = `${row.user_id} ${row.action} ${row.reason} ${row.terminal_status} ${provider.action || ''} ${provider.reason || ''} ${realization.status || ''}`.toLocaleLowerCase(language());
      const actionValue = twoStage ? realization.action : (row.terminal_status === 'provider_failed' ? 'provider_failed' : row.action);
      return (!query || haystack.includes(query)) && (!action || actionValue === action);
    });
    count.textContent = filtered.length.toLocaleString(language());
    const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
    page = Math.min(page, pageCount - 1);
    const start = page * pageSize;
    const visibleRows = filtered.slice(start, start + pageSize);
    const first = filtered.length ? start + 1 : 0;
    const last = filtered.length ? start + visibleRows.length : 0;
    pageStatus.textContent = language() === 'en-US'
      ? `Page ${page + 1} of ${pageCount} · ${first}-${last} of ${filtered.length}`
      : `第 ${page + 1} / ${pageCount} 页 · ${first}-${last} / ${filtered.length}`;
    previousPage.disabled = page === 0;
    nextPage.disabled = page >= pageCount - 1;
    body.replaceChildren();
    visibleRows.forEach((row) => {
      const tr = document.createElement('tr');
      tr.dataset.terminalRowId = row.terminal_row_id;
      const values = twoStage ? [
        row.user_id,
        row.message_id,
        String(Number(row.time_step) + 1),
        `${row.provider_judgment.engage ? 'engage' : 'ignore'} · ${row.provider_judgment.action}`,
        String(row.provider_judgment.probability),
        row.provider_judgment.reason || '',
        row.abm_realization.status,
        row.abm_realization.uniform_draw == null ? '-' : String(row.abm_realization.uniform_draw),
        row.abm_realization.action,
      ] : [
        row.user_id,
        row.message_id,
        String(Number(row.time_step) + 1),
        row.terminal_status,
        row.action,
        row.probability == null ? '' : String(row.probability),
        row.reason || '',
      ];
      values.forEach((value) => {
        const cell = document.createElement('td');
        cell.textContent = value;
        tr.append(cell);
      });
      const actionCell = document.createElement('td');
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.testid = 'full-pool-trace-row';
      button.textContent = copy('trace.open');
      button.addEventListener('click', () => openDrawer(row, button));
      actionCell.append(button);
      tr.append(actionCell);
      body.append(tr);
    });
  };
  const resetPageAndRender = () => {
    page = 0;
    render();
  };
  searchInput.addEventListener('input', resetPageAndRender);
  actionSelect.addEventListener('change', resetPageAndRender);
  previousPage.addEventListener('click', () => {
    page = Math.max(0, page - 1);
    render();
  });
  nextPage.addEventListener('click', () => {
    page += 1;
    render();
  });

  const loadSelected = async () => {
    const entry = selectedEntry();
    if (!entry) {
      rows = null;
      setState('error', 'trace.error');
      return { state: 'error', rowCount: 0 };
    }
    generation += 1;
    page = 0;
    const current = generation;
    if (controller) controller.abort();
    controller = new AbortController();
    rows = null;
    count.textContent = '0';
    body.replaceChildren();
    setState('loading-partition', 'trace.loading_partition');
    try {
      const bytes = await fetchBytes(entry.relative_path, controller.signal);
      const nextRows = await validatePartition(decodeJson(bytes), bytes, entry);
      if (current !== generation) return { state: 'stale', rowCount: 0 };
      rows = nextRows;
      setState('ready', 'trace.ready');
      render();
      return { state: 'ready', rowCount: rows.length };
    } catch (error) {
      if (error && error.name === 'AbortError') return { state: 'stale', rowCount: 0 };
      if (current === generation) {
        rows = null;
        body.replaceChildren();
        setState('error', 'trace.error');
      }
      return { state: 'error', rowCount: 0 };
    }
  };
  messageSelect.addEventListener('change', () => {
    globalThis.__fullPoolTraceReady = loadSelected();
  });
  batchSelect.addEventListener('change', () => {
    globalThis.__fullPoolTraceReady = loadSelected();
  });

  const initialize = async () => {
    setState('loading-index', 'trace.loading_index');
    try {
      const bytes = await fetchBytes(indexPath);
      index = await validateIndex(decodeJson(bytes), bytes);
      return await loadSelected();
    } catch (_error) {
      index = null;
      rows = null;
      setState('error', 'trace.error');
      return { state: 'error', rowCount: 0 };
    }
  };
  applyLanguage(language());
  globalThis.__fullPoolTraceReady = initialize();
})();
"""


__all__: list[str] = []
