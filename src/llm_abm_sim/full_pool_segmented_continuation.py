from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from enum import Enum
from itertools import chain
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ._concurrent_runtime_spool import (
    _ConcurrentRuntimeBatchSpool,
    _ConcurrentRuntimeSpoolChunk,
)
from .concurrent_execution_journal import ConcurrentExecutionJournal
from .concurrent_message_experiment import (
    CONCURRENT_MESSAGE_POSITIVE_ACTIONS,
    ConcurrentMessageExperimentConfig,
    ExperimentalMessageDefinition,
    _adapter_external_request_invocations,
    _adapter_prompt_version,
    _build_runtime_terminal_row,
    _ConcurrentRuntimeKernel,
    _ConcurrentRuntimeKernelState,
    _execute_runtime_variant,
    _MessageScore,
    _PairExecutionPlan,
    _prepare_full_pool_concurrent_runtime_inputs,
    _PreparedConcurrentRuntimeInputs,
    _primary_variant_context,
    _primary_variant_profile,
    _PrimaryOnlyConcurrentRuntimeConsumer,
    _unwrap_adapter,
    _VariantDecisionContext,
)
from .decision import DecisionInput, LLMDecisionAdapter
from .final_research import _adapter_safe_metadata
from .full_pool_formal_experiment import (
    FULL_POOL_FORMAL_ADAPTER_IDENTITY,
    FULL_POOL_FORMAL_REQUESTED_MODEL,
    FULL_POOL_FORMAL_REQUIRED_OBSERVED_MODEL,
    FULL_POOL_MESSAGE_IDS,
    FULL_POOL_PRODUCTION_CANDIDATE_ROWS,
    FULL_POOL_PRODUCTION_CAPACITY,
    FULL_POOL_PRODUCTION_ELIGIBLE_PAIRS,
    FULL_POOL_PRODUCTION_FINAL_BATCH_PAIRS_PER_MESSAGE,
    FULL_POOL_PRODUCTION_HORIZON,
    FULL_POOL_PRODUCTION_USER_COUNT,
    FullPoolExperimentContract,
    _ClosedFullPoolSource,
    _read_closed_full_pool_source,
)
from .prompt_contracts import CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY
from .prompt_field_summary import CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION
from .safe_serialization import safe_data
from .schemas import PeerContext, PlatformContext, ProviderLLMConfig

FULL_POOL_SEGMENTED_LOGICAL_CAP = 109_200
FULL_POOL_SEGMENTED_PHYSICAL_CAP = 120_120
FULL_POOL_SEGMENTED_MAX_CONCURRENCY = 10

_SEGMENTED_IDENTITY_SCHEMA = "full-pool-segmented-continuation-identity-v1"
_SEGMENTED_MANIFEST_SCHEMA = "full-pool-segmented-cutoff-manifest-v1"
_SEGMENTED_MANIFEST_ENVELOPE_SCHEMA = "full-pool-segmented-cutoff-envelope-v1"
_SEGMENTED_LEDGER_SCHEMA = "full-pool-segmented-continuation-ledger-v1"
_SEGMENTED_STATUS_SCHEMA = "full-pool-segmented-continuation-status-v1"
_RECONCILIATION_SCHEMA = "full-pool-segmented-reconciliation-authorization-v1"

_IDENTITY_FILE = "segmented_continuation_identity.json"
_MANIFEST_FILE = "cutoff_manifest.json"
_LEDGER_FILE = "segmented_continuation_ledger.jsonl"
_STATUS_FILE = "segmented_continuation_status.json"
_TERMINAL_ROWS_FILE = "segmented_terminal_rows.jsonl"

_FULL_POOL_IDENTITY_FILE = "full_pool_execution_identity.json"
_FULL_POOL_STATUS_FILE = "full_pool_execution_status.json"
_FULL_POOL_LEDGER_FILE = "full_pool_attempt_ledger.jsonl"
_FULL_POOL_IDENTITY_SCHEMA = "full-pool-formal-operational-identity-v1"
_FULL_POOL_STATUS_SCHEMA = "full-pool-formal-operational-status-v1"
_FULL_POOL_LEDGER_SCHEMA = "full-pool-formal-attempt-ledger-v1"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class SegmentedContinuationStatus(str, Enum):
    COMPLETE = "complete"
    RESUMABLE = "resumable"
    RECONCILIATION_REQUIRED = "reconciliation_required"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FullPoolReconciliationAuthorization(_FrozenModel):
    """Explicit one-pair permission to retry a migration-time v1 unknown."""

    schema_version: Literal["full-pool-segmented-reconciliation-authorization-v1"] = _RECONCILIATION_SCHEMA
    prefix_run_identity_hash: str
    unknown_pair_id: str = Field(min_length=1)
    authorization_reference: str = Field(min_length=1, max_length=240)
    physical_attempt_charge: int = Field(ge=1, le=3)
    retry_authorized: Literal[True]

    @field_validator("prefix_run_identity_hash")
    @classmethod
    def _hash(cls, value: str) -> str:
        if _SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError("prefix_run_identity_hash must be a lowercase SHA-256 digest")
        return value

    @field_validator("authorization_reference")
    @classmethod
    def _safe_reference(cls, value: str) -> str:
        lowered = value.lower()
        if "\n" in value or "\r" in value or any(
            marker in lowered
            for marker in ("bearer ", "api_key", "access_token", "refresh_token", "password", "secret")
        ):
            raise ValueError("reconciliation authorization reference must not contain credential material")
        return value


class SegmentedContinuationResult(_FrozenModel):
    status: SegmentedContinuationStatus
    workspace_root: Path
    manifest_sha256: str
    terminal_rows_path: Path | None
    source_root: Path | None = None
    source_manifest_sha256: str | None = None
    durable_prefix_terminal_count: int = Field(ge=0)
    concurrent_suffix_terminal_count: int = Field(ge=0)
    committed_feedback_user_ids: tuple[str, ...]
    unknown_pair_ids: tuple[str, ...]
    logical_count: int = Field(ge=0)
    physical_attempt_count: int = Field(ge=0)
    production_deploy_eligible: Literal[False] = False

    @field_validator("manifest_sha256", "source_manifest_sha256")
    @classmethod
    def _manifest_hash(cls, value: str | None) -> str | None:
        if value is not None and _SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError("manifest hashes must be lowercase SHA-256 digests")
        return value

    @model_validator(mode="after")
    def _closed_source_contract(self) -> SegmentedContinuationResult:
        source_fields = (self.source_root, self.source_manifest_sha256, self.terminal_rows_path)
        if self.status is SegmentedContinuationStatus.COMPLETE and any(value is None for value in source_fields):
            raise ValueError("complete segmented continuation requires a closed source-v2")
        if self.status is not SegmentedContinuationStatus.COMPLETE and any(value is not None for value in source_fields):
            raise ValueError("partial segmented continuation cannot expose source-v2")
        return self


@dataclass(frozen=True)
class _CapReservation:
    suffix_logical_reservation: int
    suffix_physical_reservation: int
    logical_total: int
    physical_total: int


@dataclass(frozen=True)
class _DynamicWaveReservation:
    wave_size: int
    reserved_physical_attempts: int


@dataclass(frozen=True)
class _AttemptPrefix:
    terminal_pair_ids: tuple[str, ...]
    pending_pair_id: str | None
    pending_physical_count: int
    logical_count: int
    physical_attempt_count: int
    provider_response_count: int
    successful_decision_count: int
    observed_model_counts: dict[str, int]
    usage_complete_response_count: int
    usage_missing_response_count: int
    usage_malformed_response_count: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cached_input_tokens: int
    accepted_ref: dict[str, object]

    def accounting(self) -> dict[str, object]:
        return {
            "logical_count": self.logical_count,
            "pending_physical_count": self.pending_physical_count,
            "physical_attempt_count": self.physical_attempt_count,
            "provider_response_count": self.provider_response_count,
            "successful_decision_count": self.successful_decision_count,
            "observed_model_counts": dict(sorted(self.observed_model_counts.items())),
            "usage_complete_response_count": self.usage_complete_response_count,
            "usage_missing_response_count": self.usage_missing_response_count,
            "usage_malformed_response_count": self.usage_malformed_response_count,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cached_input_tokens": self.cached_input_tokens,
        }


@dataclass(frozen=True)
class _FrozenPrefix:
    workspace: Path
    run_identity: dict[str, object]
    formal_identity: dict[str, object]
    accepted_artifacts: tuple[dict[str, object], ...]
    journal_ref: dict[str, object]
    attempt_prefix: _AttemptPrefix
    committed_batches: tuple[dict[str, object], ...]
    runtime_replay: dict[str, object]
    active_batch: dict[str, object]
    active_snapshot_payload: dict[str, object]
    expected_batch_count: int
    ordered_pair_ids: tuple[str, ...]
    plan_by_pair_id: dict[str, dict[str, object]]
    terminal_by_pair_id: dict[str, dict[str, object]]
    evidence_by_pair_id: dict[str, dict[str, object]]
    ordered_terminal_ids: tuple[str, ...]
    committed_feedback_user_ids: tuple[str, ...]
    active_frozen_feedback_user_ids: tuple[str, ...]
    unknown_pair_ids: tuple[str, ...]
    prompt_version: str
    provider_contract: dict[str, object]
    prompt_contract: dict[str, object]
    maximum_attempts_per_dispatch: int


@dataclass(frozen=True)
class _WorkerResult:
    pair_id: str
    terminal_row: dict[str, object]
    variant_evidence: dict[str, object]


@dataclass(frozen=True)
class _AdapterCounterBaseline:
    request_invocations: int
    external_request_invocations: int


class _ContinuationLedger:
    """Coordinator-owned append-only evidence writer."""

    def __init__(self, workspace: Path, *, continuation_identity_hash: str) -> None:
        self.path = workspace / _LEDGER_FILE
        self.identity_hash = continuation_identity_hash
        self.sequence = 0
        self.previous_checksum: str | None = None
        self.terminal_pair_ids: set[str] = set()

    def append(self, event_type: str, payload: Mapping[str, object]) -> None:
        if event_type == "pair_terminal":
            pair_id = _non_empty(payload.get("pair_id"), "suffix terminal pair_id")
            if pair_id in self.terminal_pair_ids:
                raise ValueError(f"duplicate continuation terminal for pair {pair_id}")
            self.terminal_pair_ids.add(pair_id)
        body = {
            "schema_version": _SEGMENTED_LEDGER_SCHEMA,
            "sequence": self.sequence + 1,
            "previous_checksum": self.previous_checksum,
            "continuation_identity_hash": self.identity_hash,
            "event_type": event_type,
            "payload": dict(safe_data(payload)),
        }
        checksum = _sha256_json(body)
        _append_jsonl(self.path, {**body, "checksum": checksum})
        self.sequence += 1
        self.previous_checksum = checksum


class FullPoolSegmentedContinuation:
    """Freeze a v1 serial prefix and continue every remaining batch with ten lanes.

    The Interface never mutates the v1 workspace. It derives future DecisionInput
    values from frozen plans and the existing ranking kernel, closes a complete
    source-v2, and never automatically replays uncertain suffix dispatches.
    """

    def run(
        self,
        prefix_workspace: str | Path,
        continuation_workspace: str | Path,
        *,
        continuation_id: str,
        adapter_factory: Callable[[int], LLMDecisionAdapter],
        dataset_dir: str | Path | None = None,
        reconciliation_authorization: FullPoolReconciliationAuthorization | None = None,
        _fixture_decision_inputs: Mapping[str, DecisionInput] | None = None,
    ) -> SegmentedContinuationResult:
        if dataset_dir is None and _fixture_decision_inputs is not None:
            return self._run_final_fixture(
                prefix_workspace,
                continuation_workspace,
                continuation_id=continuation_id,
                decision_inputs=_fixture_decision_inputs,
                adapter_factory=adapter_factory,
                reconciliation_authorization=reconciliation_authorization,
            )
        if _fixture_decision_inputs is not None:
            raise ValueError("complete segmented continuation derives DecisionInput from frozen batch plans")
        resolved_dataset_dir = (
            Path(dataset_dir)
            if dataset_dir is not None
            else _dataset_path_from_v1_identity(Path(prefix_workspace))
        )
        return self._run_complete(
            prefix_workspace,
            continuation_workspace,
            continuation_id=continuation_id,
            dataset_dir=resolved_dataset_dir,
            adapter_factory=adapter_factory,
            reconciliation_authorization=reconciliation_authorization,
        )

    def _run_final_fixture(
        self,
        prefix_workspace: str | Path,
        continuation_workspace: str | Path,
        *,
        continuation_id: str,
        decision_inputs: Mapping[str, DecisionInput],
        adapter_factory: Callable[[int], LLMDecisionAdapter],
        reconciliation_authorization: FullPoolReconciliationAuthorization | None = None,
    ) -> SegmentedContinuationResult:
        prefix = _freeze_v1_prefix(Path(prefix_workspace))
        if cast(int, prefix.active_batch["time_step"]) + 1 != prefix.expected_batch_count:
            raise ValueError("non-final cutoff requires dataset-backed complete continuation")
        continuation = Path(continuation_workspace).expanduser().resolve(strict=False)
        if continuation == prefix.workspace or continuation.is_relative_to(prefix.workspace):
            raise ValueError("continuation workspace must be independent from the read-only v1 prefix")
        continuation_token = _non_empty(continuation_id, "continuation_id")
        unknown_authorization = _validate_reconciliation(prefix, reconciliation_authorization)
        pending_pair_ids = tuple(
            pair_id
            for pair_id in cast(Sequence[str], prefix.active_batch["ordered_pair_ids"])
            if pair_id not in prefix.terminal_by_pair_id
        )
        _validate_decision_inputs(prefix, pending_pair_ids, decision_inputs)
        cap = _reserve_total_caps(
            prefix_logical=prefix.attempt_prefix.logical_count,
            prefix_physical=prefix.attempt_prefix.physical_attempt_count,
            unknown_logical_charge=len(prefix.unknown_pair_ids),
            unknown_physical_charge=(
                reconciliation_authorization.physical_attempt_charge
                if reconciliation_authorization is not None and prefix.unknown_pair_ids
                else 0
            ),
            pending_pair_count=len(pending_pair_ids),
            authorized_unknown_retry_count=(1 if unknown_authorization else 0),
            maximum_attempts_per_dispatch=prefix.maximum_attempts_per_dispatch,
        )
        manifest = _cutoff_manifest(
            prefix=prefix,
            continuation_id=continuation_token,
            pending_pair_ids=pending_pair_ids,
            decision_inputs=decision_inputs,
            reconciliation_authorization=reconciliation_authorization,
            cap=cap,
        )
        manifest_sha256 = _sha256_json(manifest)
        identity = _continuation_identity(
            continuation=continuation,
            continuation_id=continuation_token,
            prefix=prefix,
            manifest_sha256=manifest_sha256,
        )

        if continuation.exists() or continuation.is_symlink():
            return _load_existing_result(
                prefix=prefix,
                continuation=continuation,
                expected_identity=identity,
                expected_manifest=manifest,
                expected_manifest_sha256=manifest_sha256,
            )
        adapters = (
            None
            if prefix.unknown_pair_ids and not unknown_authorization
            else _build_lanes(prefix, adapter_factory)
        )
        _create_workspace(continuation)
        _atomic_write_json(continuation / _IDENTITY_FILE, identity)
        _atomic_write_json(
            continuation / _MANIFEST_FILE,
            {
                "schema_version": _SEGMENTED_MANIFEST_ENVELOPE_SCHEMA,
                "manifest": manifest,
                "manifest_sha256": manifest_sha256,
            },
        )
        ledger = _ContinuationLedger(continuation, continuation_identity_hash=cast(str, identity["identity_hash"]))
        ledger.append(
            "continuation_started",
            {
                "continuation_id": continuation_token,
                "cutoff_manifest_sha256": manifest_sha256,
                "max_concurrency": FULL_POOL_SEGMENTED_MAX_CONCURRENCY,
            },
        )

        if prefix.unknown_pair_ids and not unknown_authorization:
            return _persist_reconciliation_result(
                continuation=continuation,
                manifest_sha256=manifest_sha256,
                prefix=prefix,
                suffix_terminal_count=0,
                unknown_pair_ids=prefix.unknown_pair_ids,
                logical_count=prefix.attempt_prefix.logical_count + 1,
                physical_attempt_count=prefix.attempt_prefix.physical_attempt_count,
            )

        assert adapters is not None
        suffix_results: dict[str, _WorkerResult] = {}
        suffix_physical_attempts = 0
        try:
            for wave_start in range(0, len(pending_pair_ids), FULL_POOL_SEGMENTED_MAX_CONCURRENCY):
                wave_pair_ids = pending_pair_ids[
                    wave_start : wave_start + FULL_POOL_SEGMENTED_MAX_CONCURRENCY
                ]
                ledger.append(
                    "suffix_wave_reserved",
                    {
                        "wave_index": wave_start // FULL_POOL_SEGMENTED_MAX_CONCURRENCY,
                        "pair_ids": list(wave_pair_ids),
                        "logical_reservation": sum(
                            pair_id not in prefix.unknown_pair_ids for pair_id in wave_pair_ids
                        ),
                        "physical_reservation": (
                            len(wave_pair_ids) * prefix.maximum_attempts_per_dispatch
                        ),
                        "maximum_attempts_per_dispatch": prefix.maximum_attempts_per_dispatch,
                    },
                )
                wave, wave_physical_attempts = self._run_wave(
                    prefix=prefix,
                    wave_pair_ids=wave_pair_ids,
                    decision_inputs=decision_inputs,
                    adapters=adapters,
                    ledger=ledger,
                )
                suffix_physical_attempts += wave_physical_attempts
                for pair_id in wave_pair_ids:
                    suffix_results[pair_id] = wave[pair_id]
        except Exception:
            dispatched, durable, accounted_suffix_attempts, _ = _replay_continuation_ledger(
                continuation / _LEDGER_FILE,
                expected_identity_hash=cast(str, identity["identity_hash"]),
            )
            unknown = tuple(pair_id for pair_id in dispatched if pair_id not in durable)
            if not unknown:
                unknown = tuple(pair_id for pair_id in pending_pair_ids if pair_id not in suffix_results)
            return _persist_reconciliation_result(
                continuation=continuation,
                manifest_sha256=manifest_sha256,
                prefix=prefix,
                suffix_terminal_count=len(durable),
                unknown_pair_ids=unknown,
                logical_count=prefix.attempt_prefix.logical_count + len(dispatched),
                physical_attempt_count=(
                    prefix.attempt_prefix.physical_attempt_count
                    + (
                        reconciliation_authorization.physical_attempt_charge
                        if reconciliation_authorization is not None and prefix.unknown_pair_ids
                        else 0
                    )
                    + accounted_suffix_attempts
                ),
            )

        canonical_rows = [
            _segmented_terminal_row(
                prefix.terminal_by_pair_id[pair_id],
                segment="serial_prefix",
                reconciliation_retry=False,
            )
            if pair_id in prefix.terminal_by_pair_id
            else _segmented_terminal_row(
                suffix_results[pair_id].terminal_row,
                segment="concurrent_suffix",
                reconciliation_retry=pair_id in prefix.unknown_pair_ids,
            )
            for pair_id in prefix.ordered_pair_ids
        ]
        active_rows = [
            row
            for row in canonical_rows
            if row["pair_id"] in set(cast(Sequence[str], prefix.active_batch["ordered_pair_ids"]))
        ]
        committed_feedback = tuple(
            sorted(
                {
                    cast(str, row["user_id"])
                    for row in active_rows
                    if row.get("terminal_status") == "succeeded"
                    and row.get("action") in CONCURRENT_MESSAGE_POSITIVE_ACTIONS
                }
            )
        )
        prepared_rows_path = continuation / f".{_TERMINAL_ROWS_FILE}.pending"
        _exclusive_write_lines(prepared_rows_path, canonical_rows)
        rows_sha256 = _sha256_file(prepared_rows_path)
        ledger.append(
            "batch_committed",
            {
                "time_step": prefix.active_batch["time_step"],
                "batch_pair_count": len(active_rows),
                "committed_feedback_user_ids": list(committed_feedback),
                "terminal_rows_sha256": rows_sha256,
                "terminal_rows_count": len(canonical_rows),
            },
        )
        terminal_rows_path = continuation / _TERMINAL_ROWS_FILE
        os.replace(prepared_rows_path, terminal_rows_path)
        _fsync_directory(continuation)
        physical_total = (
            prefix.attempt_prefix.physical_attempt_count
            + (
                reconciliation_authorization.physical_attempt_charge
                if reconciliation_authorization is not None and prefix.unknown_pair_ids
                else 0
            )
            + suffix_physical_attempts
        )
        source_root, source_manifest_sha256 = _close_final_fixture_source_v2(
            continuation=continuation,
            prefix=prefix,
            canonical_terminal_rows=canonical_rows,
            committed_feedback_user_ids=committed_feedback,
            logical_count=cap.logical_total,
            physical_attempt_count=physical_total,
        )
        status = {
            "schema_version": _SEGMENTED_STATUS_SCHEMA,
            "lifecycle": SegmentedContinuationStatus.COMPLETE.value,
            "manifest_sha256": manifest_sha256,
            "durable_prefix_terminal_count": len(prefix.terminal_by_pair_id),
            "concurrent_suffix_terminal_count": len(suffix_results),
            "committed_feedback_user_ids": list(committed_feedback),
            "unknown_pair_ids": [],
            "logical_count": cap.logical_total,
            "physical_attempt_count": physical_total,
            "terminal_rows_relative_path": _TERMINAL_ROWS_FILE,
            "terminal_rows_sha256": rows_sha256,
            "source_root_relative_path": source_root.relative_to(continuation).as_posix(),
            "source_manifest_sha256": source_manifest_sha256,
            "production_deploy_eligible": False,
        }
        _atomic_write_json(continuation / _STATUS_FILE, status)
        _assert_prefix_unchanged(prefix)
        return _result_from_status(continuation, status)

    def _run_complete(
        self,
        prefix_workspace: str | Path,
        continuation_workspace: str | Path,
        *,
        continuation_id: str,
        dataset_dir: str | Path,
        adapter_factory: Callable[[int], LLMDecisionAdapter],
        reconciliation_authorization: FullPoolReconciliationAuthorization | None,
    ) -> SegmentedContinuationResult:
        return _run_complete_segmented(
            prefix_workspace=Path(prefix_workspace),
            continuation_workspace=Path(continuation_workspace),
            continuation_id=continuation_id,
            dataset_dir=Path(dataset_dir),
            adapter_factory=adapter_factory,
            reconciliation_authorization=reconciliation_authorization,
        )

    @staticmethod
    def _run_wave(
        *,
        prefix: _FrozenPrefix,
        wave_pair_ids: Sequence[str],
        decision_inputs: Mapping[str, DecisionInput],
        adapters: Sequence[LLMDecisionAdapter],
        ledger: _ContinuationLedger,
    ) -> tuple[dict[str, _WorkerResult], int]:
        completed: dict[str, _WorkerResult | BaseException] = {}
        baselines = _capture_adapter_counter_baselines(adapters, len(wave_pair_ids))
        with ThreadPoolExecutor(
            max_workers=FULL_POOL_SEGMENTED_MAX_CONCURRENCY,
            thread_name_prefix="full-pool-segmented",
        ) as executor:
            futures: dict[Future[_WorkerResult], str] = {}
            for lane_id, pair_id in enumerate(wave_pair_ids):
                ledger.append("pair_dispatched", {"pair_id": pair_id, "lane_id": lane_id})
                future = executor.submit(
                    _execute_pair,
                    pair_id=pair_id,
                    plan=prefix.plan_by_pair_id[pair_id],
                    decision_input=decision_inputs[pair_id],
                    adapter=adapters[lane_id],
                    provider_metadata=prefix.provider_contract,
                )
                futures[future] = pair_id
            for future in as_completed(futures):
                pair_id = futures[future]
                try:
                    completed[pair_id] = future.result()
                except BaseException as exc:
                    completed[pair_id] = exc
        wave_physical_attempts = _append_wave_accounting(
            ledger=ledger,
            pair_ids=wave_pair_ids,
            adapters=adapters,
            baselines=baselines,
            completed=completed,
        )
        drained: dict[str, _WorkerResult] = {}
        for pair_id in wave_pair_ids:
            item = completed[pair_id]
            if isinstance(item, BaseException):
                raise item
            ledger.append(
                "pair_terminal",
                {
                    "pair_id": pair_id,
                    "terminal_row": item.terminal_row,
                    "variant_evidence": item.variant_evidence,
                },
            )
            drained[pair_id] = item
        return drained, wave_physical_attempts


def _capture_adapter_counter_baselines(
    adapters: Sequence[LLMDecisionAdapter],
    lane_count: int,
) -> tuple[_AdapterCounterBaseline, ...]:
    return tuple(_adapter_counter_baseline(adapters[lane_id]) for lane_id in range(lane_count))


def _adapter_counter_baseline(adapter: LLMDecisionAdapter) -> _AdapterCounterBaseline:
    leaf, _ = _unwrap_adapter(adapter)
    request_invocations = getattr(leaf, "request_invocations", 0)
    if isinstance(request_invocations, bool) or not isinstance(request_invocations, int):
        raise TypeError("adapter request_invocations must be a non-negative int")
    if request_invocations < 0:
        raise TypeError("adapter request_invocations must be a non-negative int")
    return _AdapterCounterBaseline(
        request_invocations=request_invocations,
        external_request_invocations=_adapter_external_request_invocations(adapter),
    )


def _append_wave_accounting(
    *,
    ledger: _ContinuationLedger,
    pair_ids: Sequence[str],
    adapters: Sequence[LLMDecisionAdapter],
    baselines: Sequence[_AdapterCounterBaseline],
    completed: Mapping[str, _WorkerResult | BaseException],
) -> int:
    lanes: list[dict[str, object]] = []
    total = 0
    for lane_id, pair_id in enumerate(pair_ids):
        after = _adapter_counter_baseline(adapters[lane_id])
        baseline = baselines[lane_id]
        request_delta = after.request_invocations - baseline.request_invocations
        external_delta = after.external_request_invocations - baseline.external_request_invocations
        if request_delta < 0 or external_delta < 0:
            raise ValueError("adapter invocation counters moved backwards during a suffix wave")
        item = completed[pair_id]
        evidence_delta = (
            0
            if isinstance(item, BaseException)
            else _strict_non_negative_int(
                item.variant_evidence.get("request_invocations"),
                "suffix terminal request invocations",
            )
        )
        actual = max(request_delta, external_delta, evidence_delta)
        total += actual
        lanes.append(
            {
                "lane_id": lane_id,
                "pair_id": pair_id,
                "request_invocations_delta": request_delta,
                "external_request_invocations_delta": external_delta,
                "terminal_evidence_request_invocations": evidence_delta,
                "actual_physical_attempts": actual,
            }
        )
    ledger.append(
        "wave_accounting",
        {
            "pair_ids": list(pair_ids),
            "lanes": lanes,
            "actual_physical_attempts": total,
        },
    )
    return total


def _iter_prefix_committed_chunks(prefix: _FrozenPrefix) -> Iterator[_ConcurrentRuntimeSpoolChunk]:
    journal = ConcurrentExecutionJournal.open_existing(prefix.workspace)
    spool = _ConcurrentRuntimeBatchSpool(
        prefix.workspace,
        run_id=journal.run_id,
        identity_hash=journal.identity_hash,
        terminal_variants=("primary",),
    )
    yield from spool.iter_committed(prefix.runtime_replay)


def _close_final_fixture_source_v2(
    *,
    continuation: Path,
    prefix: _FrozenPrefix,
    canonical_terminal_rows: Sequence[Mapping[str, object]],
    committed_feedback_user_ids: Sequence[str],
    logical_count: int,
    physical_attempt_count: int,
) -> tuple[Path, str]:
    source = continuation / "source-v2"
    staging = continuation / ".source-v2.staging"
    staging.mkdir()
    prefix_chunks = list(_iter_prefix_committed_chunks(prefix))
    candidate_rows = [
        row for chunk in prefix_chunks for row in chunk.candidate_rows
    ] + [
        dict(candidate)
        for message in _mapping_sequence(prefix.active_snapshot_payload.get("messages"), "active messages")
        for candidate in _mapping_sequence(message.get("ranked_candidates"), "active candidates")
    ]
    pair_rows = [row for chunk in prefix_chunks for row in chunk.result_rows]
    for pair_id in cast(Sequence[str], prefix.active_batch["ordered_pair_ids"]):
        plan = prefix.plan_by_pair_id[pair_id]
        terminal = next(row for row in canonical_terminal_rows if row.get("pair_id") == pair_id)
        pair_rows.append(
            {
                **plan,
                "primary_status": terminal.get("terminal_status"),
                "primary_action": terminal.get("action"),
                "campaign_feedback_committed": (
                    "true"
                    if terminal.get("terminal_status") == "succeeded"
                    and terminal.get("action") in CONCURRENT_MESSAGE_POSITIVE_ACTIONS
                    else "false"
                ),
            }
        )
    steps = [
        {
            "time_step": chunk.time_step,
            "frozen_campaign_engaged_user_ids": chunk.commit.get("frozen_campaign_engaged_user_ids", []),
            "committed_primary_positive_user_ids": chunk.commit.get(
                "committed_primary_positive_user_ids", []
            ),
        }
        for chunk in prefix_chunks
    ]
    steps.append(
        {
            "time_step": prefix.active_batch["time_step"],
            "frozen_campaign_engaged_user_ids": list(prefix.active_frozen_feedback_user_ids),
            "committed_primary_positive_user_ids": list(committed_feedback_user_ids),
        }
    )
    for name, rows in (
        ("candidate_rows.jsonl", candidate_rows),
        ("pair_rows.jsonl", pair_rows),
        ("terminal_rows.jsonl", canonical_terminal_rows),
        ("steps.jsonl", steps),
    ):
        _exclusive_write_lines(staging / name, rows)
    artifacts = [
        _file_ref(staging, staging / name)
        for name in ("candidate_rows.jsonl", "pair_rows.jsonl", "terminal_rows.jsonl", "steps.jsonl")
    ]
    manifest = {
        "schema_version": "full-pool-segmented-source-v2",
        "counts": {
            "candidate_rows": len(candidate_rows),
            "pair_rows": len(pair_rows),
            "terminal_rows": len(canonical_terminal_rows),
            "steps": len(steps),
        },
        "logical_count": logical_count,
        "physical_attempt_count": physical_attempt_count,
        "artifacts": artifacts,
        "prefix_identity_hash": prefix.run_identity.get("identity_hash"),
        "max_concurrency": FULL_POOL_SEGMENTED_MAX_CONCURRENCY,
        "production_deploy_eligible": False,
    }
    _atomic_write_json(staging / "manifest.json", manifest)
    manifest_sha256 = _sha256_file(staging / "manifest.json")
    os.replace(staging, source)
    _fsync_directory(continuation)
    return source, manifest_sha256


class _SegmentedKernelJournal:
    """Kernel journal Adapter whose durable writes are owned by the coordinator."""

    read_only = False

    def __init__(
        self,
        workspace: Path,
        *,
        run_id: str,
        identity_hash: str,
        ledger: _ContinuationLedger,
        base_time_step: int,
    ) -> None:
        self.workspace_dir = workspace
        self.run_id = run_id
        self.identity_hash = identity_hash
        self.ledger = ledger
        self.base_time_step = base_time_step
        self.records: list[dict[str, object]] = []
        self.snapshot_dir = workspace / "segmented_runtime_snapshots"
        self.snapshot_dir.mkdir(exist_ok=True)

    def persist_snapshot(
        self,
        *,
        snapshot_type: str,
        snapshot_identity: Mapping[str, object],
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        document = {
            "schema_version": "concurrent-message-execution-snapshot-v1",
            "snapshot_type": snapshot_type,
            "snapshot_identity": dict(snapshot_identity),
            "payload": dict(payload),
        }
        snapshot_hash = _sha256_json(document)
        time_step = _strict_non_negative_int(snapshot_identity.get("time_step"), "snapshot time_step")
        path = self.snapshot_dir / f"batch-plan-{time_step:06d}-{snapshot_hash[:12]}.json"
        _atomic_write_json(path, document)
        ref = {
            "sequence": len(self.records) + 1,
            "snapshot_type": snapshot_type,
            "snapshot_identity": dict(snapshot_identity),
            "snapshot_hash": snapshot_hash,
            "snapshot_path": path.relative_to(self.workspace_dir).as_posix(),
        }
        self.ledger.append("kernel_batch_snapshot", ref)
        self.records.append(
            {
                "record_type": "snapshot",
                "sequence": len(self.records) + 1,
                **ref,
                "snapshot_document": document,
            }
        )
        return ref

    def append(
        self,
        *,
        event_type: str,
        event_identity: Mapping[str, object],
        payload: Mapping[str, object],
        batch_snapshot_hash: str | None = None,
    ) -> dict[str, object]:
        record = {
            "record_type": "event",
            "sequence": len(self.records) + 1,
            "event_type": event_type,
            "event_identity": dict(event_identity),
            "batch_snapshot_hash": batch_snapshot_hash,
            "payload": dict(payload),
        }
        if event_type == "batch_committed":
            self.ledger.append(
                "kernel_batch_committed",
                {
                    "event_identity": dict(event_identity),
                    "batch_snapshot_hash": batch_snapshot_hash,
                    "payload": dict(payload),
                },
            )
            self.records.append(record)
        return record

    def replay(self) -> dict[str, object]:
        return {
            "status": {
                "committed_batch_count": sum(
                    record.get("event_type") == "batch_committed" for record in self.records
                )
            },
            "records": list(self.records),
        }

    def close(self) -> None:
        return


def _run_complete_segmented(
    *,
    prefix_workspace: Path,
    continuation_workspace: Path,
    continuation_id: str,
    dataset_dir: Path,
    adapter_factory: Callable[[int], LLMDecisionAdapter],
    reconciliation_authorization: FullPoolReconciliationAuthorization | None,
) -> SegmentedContinuationResult:
    prefix = _freeze_v1_prefix(prefix_workspace)
    continuation = continuation_workspace.expanduser().resolve(strict=False)
    if continuation == prefix.workspace or continuation.is_relative_to(prefix.workspace):
        raise ValueError("continuation workspace must be independent from the read-only v1 prefix")
    continuation_token = _non_empty(continuation_id, "continuation_id")
    unknown_authorized = _validate_reconciliation(prefix, reconciliation_authorization)
    config, prepared, dataset_ref = _prepare_segmented_runtime(prefix, dataset_dir)
    expected_logical = config.sample_size * len(config.messages)
    if expected_logical > FULL_POOL_SEGMENTED_LOGICAL_CAP:
        raise ValueError("segmented continuation logical cap would be exceeded")
    if prefix.attempt_prefix.logical_count > expected_logical:
        raise ValueError("v1 prefix logical count exceeds the complete schedule")
    remaining_logical = expected_logical - prefix.attempt_prefix.logical_count
    cutoff_manifest = _complete_cutoff_manifest(
        prefix=prefix,
        continuation_id=continuation_token,
        dataset_ref=dataset_ref,
        expected_logical=expected_logical,
        remaining_logical=remaining_logical,
        reconciliation_authorization=reconciliation_authorization,
    )
    manifest_sha256 = _sha256_json(cutoff_manifest)
    identity = _continuation_identity(
        continuation=continuation,
        continuation_id=continuation_token,
        prefix=prefix,
        manifest_sha256=manifest_sha256,
    )
    if continuation.exists() or continuation.is_symlink():
        return _load_complete_existing(
            prefix=prefix,
            continuation=continuation,
            expected_identity=identity,
            expected_manifest=cutoff_manifest,
            manifest_sha256=manifest_sha256,
        )
    adapters = None if prefix.unknown_pair_ids and not unknown_authorized else _build_lanes(prefix, adapter_factory)
    _create_workspace(continuation)
    _atomic_write_json(continuation / _IDENTITY_FILE, identity)
    _atomic_write_json(
        continuation / _MANIFEST_FILE,
        {
            "schema_version": _SEGMENTED_MANIFEST_ENVELOPE_SCHEMA,
            "manifest": cutoff_manifest,
            "manifest_sha256": manifest_sha256,
        },
    )
    ledger = _ContinuationLedger(continuation, continuation_identity_hash=cast(str, identity["identity_hash"]))
    ledger.append(
        "continuation_started",
        {
            "continuation_id": continuation_token,
            "cutoff_manifest_sha256": manifest_sha256,
            "max_concurrency": FULL_POOL_SEGMENTED_MAX_CONCURRENCY,
            "active_time_step": prefix.active_batch["time_step"],
            "expected_horizon": config.horizon,
        },
    )
    if prefix.unknown_pair_ids and not unknown_authorized:
        return _persist_reconciliation_result(
            continuation=continuation,
            manifest_sha256=manifest_sha256,
            prefix=prefix,
            suffix_terminal_count=0,
            unknown_pair_ids=prefix.unknown_pair_ids,
            logical_count=prefix.attempt_prefix.logical_count + 1,
            physical_attempt_count=prefix.attempt_prefix.physical_attempt_count,
        )
    assert adapters is not None

    active_time_step = cast(int, prefix.active_batch["time_step"])
    kernel_journal = _SegmentedKernelJournal(
        continuation,
        run_id=cast(str, identity["run_id"]),
        identity_hash=cast(str, identity["identity_hash"]),
        ledger=ledger,
        base_time_step=active_time_step,
    )
    continuation_spool = _ConcurrentRuntimeBatchSpool(
        continuation,
        run_id=kernel_journal.run_id,
        identity_hash=kernel_journal.identity_hash,
        terminal_variants=("primary",),
        base_time_step=active_time_step,
    )
    physical_attempts = prefix.attempt_prefix.physical_attempt_count + (
        reconciliation_authorization.physical_attempt_charge
        if reconciliation_authorization is not None and prefix.unknown_pair_ids
        else 0
    )
    suffix_terminal_count = 0
    try:
        active_plans = _typed_active_plans(prefix, config=config, prepared=prepared)
        active_results: dict[str, _WorkerResult] = {
            pair_id: _WorkerResult(
                pair_id=pair_id,
                terminal_row=prefix.terminal_by_pair_id[pair_id],
                variant_evidence=prefix.evidence_by_pair_id[pair_id],
            )
            for pair_id in cast(Sequence[str], prefix.active_batch["ordered_pair_ids"])
            if pair_id in prefix.terminal_by_pair_id
        }
        active_pending = [plan for plan in active_plans if plan.pair_id not in active_results]
        active_wave_results, active_attempts, cap_stopped = _execute_typed_plans(
            plans=active_pending,
            adapters=adapters,
            ledger=ledger,
            provider_metadata=prefix.provider_contract,
            physical_attempts=physical_attempts,
            maximum_attempts_per_dispatch=prefix.maximum_attempts_per_dispatch,
        )
        if cap_stopped:
            return _persist_cap_stop(
                continuation=continuation,
                manifest_sha256=manifest_sha256,
                prefix=prefix,
                suffix_terminal_count=len(active_wave_results),
                logical_count=prefix.attempt_prefix.logical_count + len(active_wave_results),
                physical_attempt_count=physical_attempts + active_attempts,
            )
        physical_attempts += active_attempts
        suffix_terminal_count += len(active_wave_results)
        active_results.update(active_wave_results)
        if set(active_results) != {plan.pair_id for plan in active_plans}:
            raise ValueError("active segmented batch did not close every terminal")
        active_commit = _commit_cutoff_active_batch(
            prefix=prefix,
            plans=active_plans,
            results=active_results,
            spool=continuation_spool,
            journal=kernel_journal,
        )

        exposed_by_message = {message.message_id: set[str]() for message in config.messages}
        for pair_id in prefix.ordered_pair_ids:
            plan = prefix.plan_by_pair_id[pair_id]
            exposed_by_message[_non_empty(plan.get("message_id"), "prefix message_id")].add(
                _non_empty(plan.get("user_id"), "prefix user_id")
            )
        campaign_feedback = set(prefix.committed_feedback_user_ids)
        campaign_feedback.update(
            _string_list(
                active_commit["committed_primary_positive_user_ids"],
                "active committed feedback users",
            )
        )
        state = _ConcurrentRuntimeKernelState(
            cohort=prepared.cohort,
            exposed_by_message=exposed_by_message,
            campaign_engaged_user_ids=campaign_feedback,
            pair_schedule_position=len(prefix.ordered_pair_ids),
            next_time_step=active_time_step + 1,
        )
        kernel = _ConcurrentRuntimeKernel.primary_only(
            config=config,
            state=state,
            base_network_by_user=prepared.base_network_by_user,
            neighbors_by_user=prepared.neighbors_by_user,
            journal=cast(ConcurrentExecutionJournal, kernel_journal),
            spool_base_time_step=active_time_step,
        )
        while state.next_time_step < config.horizon:
            kernel.plan_batch()
            plans = kernel.pending_plans()
            wave_results, batch_attempts, cap_stopped = _execute_typed_plans(
                plans=plans,
                adapters=adapters,
                ledger=ledger,
                provider_metadata=prefix.provider_contract,
                physical_attempts=physical_attempts,
                maximum_attempts_per_dispatch=prefix.maximum_attempts_per_dispatch,
            )
            if cap_stopped:
                return _persist_cap_stop(
                    continuation=continuation,
                    manifest_sha256=manifest_sha256,
                    prefix=prefix,
                    suffix_terminal_count=suffix_terminal_count + len(wave_results),
                    logical_count=prefix.attempt_prefix.logical_count + suffix_terminal_count + len(wave_results),
                    physical_attempt_count=physical_attempts + batch_attempts,
                )
            physical_attempts += batch_attempts
            suffix_terminal_count += len(wave_results)
            for plan in plans:
                result = wave_results[plan.pair_id]
                kernel.start_pair(plan)
                kernel.register_terminal(
                    plan=plan,
                    decision_variant="primary",
                    terminal_row=result.terminal_row,
                    variant_evidence=result.variant_evidence,
                )
                kernel.close_primary_pair(
                    plan,
                    _PrimaryOnlyConcurrentRuntimeConsumer._primary_result_row(plan, result.terminal_row),
                )
            kernel.commit_primary_batch()
    except Exception:
        dispatched, durable, accounted_attempts, _ = _replay_continuation_ledger(
            continuation / _LEDGER_FILE,
            expected_identity_hash=kernel_journal.identity_hash,
        )
        unknown = tuple(pair_id for pair_id in dispatched if pair_id not in durable)
        return _persist_reconciliation_result(
            continuation=continuation,
            manifest_sha256=manifest_sha256,
            prefix=prefix,
            suffix_terminal_count=len(durable),
            unknown_pair_ids=unknown,
            logical_count=prefix.attempt_prefix.logical_count + len(dispatched),
            physical_attempt_count=(
                prefix.attempt_prefix.physical_attempt_count
                + (
                    reconciliation_authorization.physical_attempt_charge
                    if reconciliation_authorization is not None and prefix.unknown_pair_ids
                    else 0
                )
                + accounted_attempts
            ),
        )

    logical_count = prefix.attempt_prefix.logical_count + suffix_terminal_count
    if logical_count != expected_logical:
        raise ValueError("complete segmented runtime does not close the logical denominator")
    source_root, source_manifest_sha256, source_status = _close_segmented_source_v2(
        continuation=continuation,
        prefix=prefix,
        continuation_spool=continuation_spool,
        continuation_replay=kernel_journal.replay(),
        config=config,
        logical_count=logical_count,
        physical_attempt_count=physical_attempts,
        cutoff_manifest_sha256=manifest_sha256,
        continuation_identity_hash=kernel_journal.identity_hash,
        ledger=ledger,
    )
    status = {
        "schema_version": _SEGMENTED_STATUS_SCHEMA,
        "lifecycle": SegmentedContinuationStatus.COMPLETE.value,
        "manifest_sha256": manifest_sha256,
        "durable_prefix_terminal_count": source_status["durable_prefix_terminal_count"],
        "concurrent_suffix_terminal_count": source_status["concurrent_suffix_terminal_count"],
        "committed_feedback_user_ids": source_status["committed_feedback_user_ids"],
        "unknown_pair_ids": source_status["unknown_pair_ids"],
        "logical_count": source_status["logical_count"],
        "physical_attempt_count": source_status["physical_attempt_count"],
        "terminal_rows_relative_path": source_status["terminal_rows_relative_path"],
        "terminal_rows_sha256": source_status["terminal_rows_sha256"],
        "source_root_relative_path": source_status["source_root_relative_path"],
        "source_manifest_sha256": source_manifest_sha256,
        "production_deploy_eligible": False,
    }
    _atomic_write_json(continuation / _STATUS_FILE, status)
    _assert_prefix_unchanged(prefix)
    return _result_from_status(continuation, status)


def _prepare_segmented_runtime(
    prefix: _FrozenPrefix,
    dataset_dir: Path,
) -> tuple[ConcurrentMessageExperimentConfig, _PreparedConcurrentRuntimeInputs, dict[str, object]]:
    dataset = dataset_dir.expanduser().resolve(strict=True)
    _require_real_directory(dataset, "segmented continuation dataset")
    fingerprints = _mapping(prefix.run_identity.get("sample_data_fingerprints"), "sample data fingerprints")
    dataset_files = _mapping(fingerprints.get("dataset_files"), "dataset file fingerprints")
    verified_files: list[dict[str, object]] = []
    for file_name, expected_hash in sorted(dataset_files.items()):
        path = dataset / file_name
        if not path.is_file() or _sha256_file(path) != expected_hash:
            raise ValueError(f"segmented continuation dataset hash mismatch for {file_name}")
        verified_files.append(_file_ref(dataset, path))
    configuration = _mapping(prefix.run_identity.get("configuration"), "v1 run configuration")
    messages = tuple(
        ExperimentalMessageDefinition.model_validate(value)
        for value in _mapping_sequence(prefix.run_identity.get("messages"), "v1 messages")
    )
    config = ConcurrentMessageExperimentConfig(
        dataset_dir=dataset,
        sample_size=_strict_non_negative_int(configuration.get("sample_size"), "sample_size"),
        horizon=_strict_non_negative_int(configuration.get("horizon"), "horizon"),
        delivery_capacity=_strict_non_negative_int(
            configuration.get("delivery_capacity"), "delivery_capacity"
        ),
        random_seed=_strict_non_negative_int(configuration.get("random_seed"), "random_seed"),
        configuration_profile=cast(Literal["production", "validation"], configuration.get("configuration_profile")),
        sample_holdout_video_id=_non_empty(
            configuration.get("sample_holdout_video_id"), "sample_holdout_video_id"
        ),
        messages=messages,
    )
    execution = _mapping(prefix.run_identity.get("execution_contract"), "v1 execution contract")
    seed_top_k = _strict_non_negative_int(execution.get("seed_top_k_per_proxy"), "seed_top_k_per_proxy")
    prepared = _prepare_full_pool_concurrent_runtime_inputs(config, seed_top_k_per_proxy=seed_top_k)
    prepared_user_ids = sorted(prepared.cohort.sample_user_ids)
    eligible_count = execution.get("eligible_user_count")
    if eligible_count is not None and eligible_count != len(prepared_user_ids):
        raise ValueError("segmented prepared membership count is crossed with the v1 contract")
    eligible_hash = execution.get("eligible_user_ids_sha256")
    if eligible_hash is not None and eligible_hash != _sha256_json(prepared_user_ids):
        raise ValueError("segmented prepared membership hash is crossed with the v1 contract")
    expected_terminals = execution.get("expected_primary_terminals")
    if expected_terminals is not None and expected_terminals != config.sample_size * len(config.messages):
        raise ValueError("segmented logical denominator is crossed with the v1 contract")
    return config, prepared, {
        "dataset_dir": str(dataset),
        "files": verified_files,
        "dataset_files_sha256": _sha256_json(verified_files),
    }


def _typed_active_plans(
    prefix: _FrozenPrefix,
    *,
    config: ConcurrentMessageExperimentConfig,
    prepared: _PreparedConcurrentRuntimeInputs,
) -> list[_PairExecutionPlan]:
    cohort = prepared.cohort
    messages = {message.message_id: message for message in config.messages}
    plans: list[_PairExecutionPlan] = []
    for pair_id in cast(Sequence[str], prefix.active_batch["ordered_pair_ids"]):
        raw = prefix.plan_by_pair_id[pair_id]
        user_id = _non_empty(raw.get("user_id"), "active plan user_id")
        message_id = _non_empty(raw.get("message_id"), "active plan message_id")
        user = cohort.users_by_id[user_id]
        score = _MessageScore(
            user_id=user_id,
            base_network_relevance=_float_value(raw.get("base_network_relevance"), "base network relevance"),
            engaged_neighbor_count=_strict_non_negative_int(
                raw.get("campaign_engaged_neighbor_count"), "engaged neighbor count"
            ),
            engaged_neighbor_signal=_float_value(
                raw.get("campaign_engaged_neighbor_signal"), "engaged neighbor signal"
            ),
            raw_message_user_fit=_float_value(raw.get("raw_message_user_fit"), "raw message-user fit"),
            normalized_message_user_fit=_float_value(
                raw.get("normalized_message_user_fit"), "normalized message-user fit"
            ),
            personalized_delivery_score=_float_value(
                raw.get("personalized_delivery_score"), "personalized delivery score"
            ),
            base_network_relevance_full_precision=cast(str | None, raw.get("base_network_relevance_full_precision")),
            engaged_neighbor_signal_full_precision=cast(
                str | None, raw.get("campaign_engaged_neighbor_signal_full_precision")
            ),
            raw_message_user_fit_full_precision=cast(str | None, raw.get("raw_message_user_fit_full_precision")),
            normalized_message_user_fit_full_precision=cast(
                str | None, raw.get("normalized_message_user_fit_full_precision")
            ),
            personalized_delivery_score_full_precision=cast(
                str | None, raw.get("personalized_delivery_score_full_precision")
            ),
        )
        plans.append(
            _PairExecutionPlan(
                pair_id=pair_id,
                pair_schedule_position=_strict_non_negative_int(
                    raw.get("pair_schedule_position"), "pair schedule position"
                ),
                time_step=_strict_non_negative_int(raw.get("time_step"), "pair time_step"),
                message=messages[message_id],
                user=user,
                profile=_primary_variant_profile(user),
                ranking_position=_strict_non_negative_int(raw.get("ranking_position"), "ranking position"),
                selection_reason=_non_empty(raw.get("selection_reason"), "selection reason"),
                score=score,
            )
        )
    return plans


def _execute_typed_plans(
    *,
    plans: Sequence[_PairExecutionPlan],
    adapters: Sequence[LLMDecisionAdapter],
    ledger: _ContinuationLedger,
    provider_metadata: Mapping[str, object],
    physical_attempts: int,
    maximum_attempts_per_dispatch: int,
) -> tuple[dict[str, _WorkerResult], int, bool]:
    results: dict[str, _WorkerResult] = {}
    consumed_attempts = 0
    cursor = 0
    while cursor < len(plans):
        reservation = _reserve_dynamic_wave(
            remaining_pair_count=len(plans) - cursor,
            physical_attempts=physical_attempts + consumed_attempts,
            maximum_attempts_per_dispatch=maximum_attempts_per_dispatch,
        )
        if reservation.wave_size == 0:
            return results, consumed_attempts, True
        wave_plans = plans[cursor : cursor + reservation.wave_size]
        ledger.append(
            "suffix_wave_reserved",
            {
                "pair_ids": [plan.pair_id for plan in wave_plans],
                "physical_reservation": reservation.reserved_physical_attempts,
                "maximum_attempts_per_dispatch": maximum_attempts_per_dispatch,
            },
        )
        wave, wave_physical_attempts = _run_typed_wave(
            plans=wave_plans,
            adapters=adapters,
            ledger=ledger,
            provider_metadata=provider_metadata,
        )
        consumed_attempts += wave_physical_attempts
        for plan in wave_plans:
            results[plan.pair_id] = wave[plan.pair_id]
        cursor += reservation.wave_size
    return results, consumed_attempts, False


def _run_typed_wave(
    *,
    plans: Sequence[_PairExecutionPlan],
    adapters: Sequence[LLMDecisionAdapter],
    ledger: _ContinuationLedger,
    provider_metadata: Mapping[str, object],
) -> tuple[dict[str, _WorkerResult], int]:
    completed: dict[str, _WorkerResult | BaseException] = {}
    baselines = _capture_adapter_counter_baselines(adapters, len(plans))
    with ThreadPoolExecutor(
        max_workers=FULL_POOL_SEGMENTED_MAX_CONCURRENCY,
        thread_name_prefix="full-pool-segmented",
    ) as executor:
        futures: dict[Future[_WorkerResult], str] = {}
        for lane_id, plan in enumerate(plans):
            ledger.append("pair_dispatched", {"pair_id": plan.pair_id, "lane_id": lane_id})
            futures[
                executor.submit(
                    _execute_typed_pair,
                    plan=plan,
                    adapter=adapters[lane_id],
                    provider_metadata=provider_metadata,
                )
            ] = plan.pair_id
        for future in as_completed(futures):
            pair_id = futures[future]
            try:
                completed[pair_id] = future.result()
            except BaseException as exc:
                completed[pair_id] = exc
    pair_ids = [plan.pair_id for plan in plans]
    wave_physical_attempts = _append_wave_accounting(
        ledger=ledger,
        pair_ids=pair_ids,
        adapters=adapters,
        baselines=baselines,
        completed=completed,
    )
    drained: dict[str, _WorkerResult] = {}
    for pair_id in pair_ids:
        item = completed[pair_id]
        if isinstance(item, BaseException):
            raise item
        ledger.append(
            "pair_terminal",
            {
                "pair_id": pair_id,
                "terminal_row": item.terminal_row,
                "variant_evidence": item.variant_evidence,
            },
        )
        drained[pair_id] = item
    return drained, wave_physical_attempts


def _execute_typed_pair(
    *,
    plan: _PairExecutionPlan,
    adapter: LLMDecisionAdapter,
    provider_metadata: Mapping[str, object],
) -> _WorkerResult:
    context = _primary_variant_context(plan)
    attempt, accounting = _execute_runtime_variant(
        adapter=adapter,
        context=context,
        pair_schedule_position=plan.pair_schedule_position,
        time_step=plan.time_step,
        message_id=plan.message.message_id,
        default_provider_metadata=provider_metadata,
    )
    terminal_row, _, evidence = _build_runtime_terminal_row(
        pair_id=plan.pair_id,
        pair_schedule_position=plan.pair_schedule_position,
        time_step=plan.time_step,
        message_id=plan.message.message_id,
        user_id=plan.user.user_id,
        context=context,
        attempt=attempt,
        accounting=accounting,
        default_provider_metadata=provider_metadata,
    )
    return _WorkerResult(plan.pair_id, terminal_row, evidence)


def _commit_cutoff_active_batch(
    *,
    prefix: _FrozenPrefix,
    plans: Sequence[_PairExecutionPlan],
    results: Mapping[str, _WorkerResult],
    spool: _ConcurrentRuntimeBatchSpool,
    journal: _SegmentedKernelJournal,
) -> dict[str, object]:
    active_pair_ids = [plan.pair_id for plan in plans]
    terminal_rows = [results[pair_id].terminal_row for pair_id in active_pair_ids]
    evidence_rows = [results[pair_id].variant_evidence for pair_id in active_pair_ids]
    positive_users = sorted(
        {
            str(row["user_id"])
            for row in terminal_rows
            if row.get("terminal_status") == "succeeded"
            and row.get("action") in CONCURRENT_MESSAGE_POSITIVE_ACTIONS
        }
    )
    result_rows = [
        _PrimaryOnlyConcurrentRuntimeConsumer._primary_result_row(plan, results[plan.pair_id].terminal_row)
        for plan in plans
    ]
    for row in result_rows:
        row["campaign_feedback_committed"] = (
            "true"
            if row.get("primary_status") == "succeeded"
            and row.get("primary_action") in CONCURRENT_MESSAGE_POSITIVE_ACTIONS
            else "false"
        )
    candidate_rows = [
        dict(candidate)
        for message in _mapping_sequence(prefix.active_snapshot_payload.get("messages"), "active messages")
        for candidate in _mapping_sequence(message.get("ranked_candidates"), "active ranked candidates")
    ]
    terminals_by_message: dict[str, list[dict[str, object]]] = {}
    for row in terminal_rows:
        terminals_by_message.setdefault(
            _non_empty(row.get("message_id"), "active terminal message_id"), []
        ).append(row)
    message_summaries = []
    for message in _mapping_sequence(prefix.active_snapshot_payload.get("messages"), "active messages"):
        message_id = _non_empty(message.get("message_id"), "active message_id")
        message_terminals = terminals_by_message.get(message_id, [])
        ranked_candidates = _mapping_sequence(
            message.get("ranked_candidates"), "active ranked candidates"
        )
        message_summaries.append(
            {
                "message_id": message_id,
                "message_title": message.get("message_title"),
                "eligible_users": message.get("eligible_users"),
                "ranked_candidates": len(ranked_candidates),
                "selected_user_ids": message.get("selected_user_ids"),
                "seed_user_ids": message.get("seed_user_ids"),
                "personalized_topup_user_ids": message.get("personalized_topup_user_ids"),
                "primary_positive_user_ids": sorted(
                    {
                        str(row["user_id"])
                        for row in message_terminals
                        if row.get("terminal_status") == "succeeded"
                        and row.get("action") in CONCURRENT_MESSAGE_POSITIVE_ACTIONS
                    }
                ),
                "primary_provider_failed_user_ids": [
                    str(row["user_id"])
                    for row in message_terminals
                    if row.get("terminal_status") == "provider_failed"
                ],
                "shadow_provider_failed_user_ids": [],
                "below_delivery_capacity": message.get("below_delivery_capacity"),
                "selection_reason_counts": message.get("selection_reason_counts"),
            }
        )
    commit = {
        "time_step": prefix.active_batch["time_step"],
        "frozen_campaign_engaged_user_ids": list(prefix.active_frozen_feedback_user_ids),
        "committed_primary_positive_user_ids": positive_users,
        "message_summaries": message_summaries,
    }
    ref = spool.prepare_batch(
        time_step=cast(int, prefix.active_batch["time_step"]),
        batch_snapshot_hash=cast(str, prefix.active_batch["batch_snapshot_hash"]),
        commit=commit,
        candidate_rows=candidate_rows,
        result_rows=result_rows,
        terminal_rows=terminal_rows,
        variant_evidence_rows=evidence_rows,
    )
    journal.append(
        event_type="batch_committed",
        event_identity={"time_step": prefix.active_batch["time_step"]},
        payload={
            "time_step": prefix.active_batch["time_step"],
            "committed_user_ids": positive_users,
            "committed_user_count": len(positive_users),
            "batch_pair_count": len(plans),
            "batch_spool_chunk": ref,
        },
        batch_snapshot_hash=cast(str, prefix.active_batch["batch_snapshot_hash"]),
    )
    spool.publish_prepared(ref)
    return commit


def _complete_cutoff_manifest(
    *,
    prefix: _FrozenPrefix,
    continuation_id: str,
    dataset_ref: Mapping[str, object],
    expected_logical: int,
    remaining_logical: int,
    reconciliation_authorization: FullPoolReconciliationAuthorization | None,
) -> dict[str, object]:
    authorization = (
        reconciliation_authorization.model_dump(mode="json")
        if reconciliation_authorization is not None
        else None
    )
    return {
        "schema_version": "full-pool-segmented-complete-cutoff-manifest-v2",
        "continuation_id": continuation_id,
        "v1_contract_identity": prefix.formal_identity,
        "v1_run_identity": prefix.run_identity,
        "accepted_journal_prefix": prefix.journal_ref,
        "accepted_attempt_ledger_prefix": prefix.attempt_prefix.accepted_ref,
        "accepted_artifacts": list(prefix.accepted_artifacts),
        "committed_batches": list(prefix.committed_batches),
        "active_batch": prefix.active_batch,
        "ordered_prefix_pair_ids": list(prefix.ordered_pair_ids),
        "ordered_prefix_terminal_ids": list(prefix.ordered_terminal_ids),
        "prefix_accounting": prefix.attempt_prefix.accounting(),
        "unknown_count": len(prefix.unknown_pair_ids),
        "unknown_pair_ids": list(prefix.unknown_pair_ids),
        "reconciliation_authorization": authorization,
        "reconciliation_authorization_sha256": _sha256_json(authorization) if authorization else None,
        "dataset": dict(dataset_ref),
        "expected_horizon": prefix.expected_batch_count,
        "expected_logical_count": expected_logical,
        "remaining_logical_count": remaining_logical,
        "max_concurrency": FULL_POOL_SEGMENTED_MAX_CONCURRENCY,
        "logical_cap": FULL_POOL_SEGMENTED_LOGICAL_CAP,
        "physical_cap": FULL_POOL_SEGMENTED_PHYSICAL_CAP,
        "physical_reservation_policy": "dynamic-next-wave-retry-window-v1",
        "production_deploy_eligible": False,
    }


def _close_segmented_source_v2(
    *,
    continuation: Path,
    prefix: _FrozenPrefix,
    continuation_spool: _ConcurrentRuntimeBatchSpool,
    continuation_replay: Mapping[str, object],
    config: ConcurrentMessageExperimentConfig,
    logical_count: int,
    physical_attempt_count: int,
    cutoff_manifest_sha256: str,
    continuation_identity_hash: str,
    ledger: _ContinuationLedger,
) -> tuple[Path, str, dict[str, object]]:
    source = continuation / "source-v2"
    staging = continuation / ".source-v2.staging"
    if source.exists() or staging.exists():
        raise FileExistsError("segmented source-v2 target already exists")
    staging.mkdir()
    candidate_path = staging / "candidate_rows.jsonl"
    pair_path = staging / "pair_rows.jsonl"
    terminal_path = staging / "terminal_rows.jsonl"
    step_path = staging / "steps.jsonl"
    prefix_terminal_ids = set(prefix.terminal_by_pair_id)
    pair_ids: set[str] = set()
    terminal_ids: set[str] = set()
    terminal_pair_ids: set[str] = set()
    cumulative_feedback: set[str] = set()
    candidate_count = 0
    pair_count = 0
    terminal_count = 0
    step_count = 0
    evidence_count = 0
    expected_position = 0
    invocations = 0
    responses = 0
    successes = 0
    observed_models: Counter[str] = Counter()
    observed_missing = 0
    observed_malformed = 0
    usage_complete_attempts = 0
    usage_incomplete_attempts = 0
    usage_complete_responses = 0
    usage_missing_responses = 0
    usage_malformed_responses = 0
    input_usage = 0
    output_usage = 0
    total_usage = 0
    cached_input_usage = 0
    cached_reported = False

    chunks = chain(
        _iter_prefix_committed_chunks(prefix),
        continuation_spool.iter_committed(continuation_replay),
    )
    with (
        candidate_path.open("x", encoding="utf-8", newline="\n") as candidate_handle,
        pair_path.open("x", encoding="utf-8", newline="\n") as pair_handle,
        terminal_path.open("x", encoding="utf-8", newline="\n") as terminal_handle,
        step_path.open("x", encoding="utf-8", newline="\n") as step_handle,
    ):
        for expected_time_step, chunk in enumerate(chunks):
            if chunk.time_step != expected_time_step:
                raise ValueError("segmented source-v2 batches are missing, extra, or out of order")
            for row in chunk.candidate_rows:
                candidate_handle.write(_canonical_json(row) + "\n")
                candidate_count += 1
            for row in chunk.result_rows:
                pair_id = _non_empty(row.get("pair_id"), "source-v2 pair_id")
                position = _strict_non_negative_int(
                    row.get("pair_schedule_position"), "source-v2 pair schedule position"
                )
                if pair_id in pair_ids or position != expected_position:
                    raise ValueError("source-v2 pair identity or order is not canonical")
                pair_ids.add(pair_id)
                expected_position += 1
                pair_handle.write(
                    _canonical_json(
                        {
                            **row,
                            "execution_segment": (
                                "serial_prefix" if pair_id in prefix_terminal_ids else "concurrent_suffix"
                            ),
                        }
                    )
                    + "\n"
                )
                pair_count += 1
            for evidence in chunk.variant_evidence_rows:
                evidence_count += 1
                requests = _strict_non_negative_int(
                    evidence.get("request_invocations"), "source-v2 request invocations"
                )
                response_count = _strict_non_negative_int(
                    evidence.get("provider_response_count"), "source-v2 provider responses"
                )
                success_count = _strict_non_negative_int(
                    evidence.get("successful_decision_count"), "source-v2 successful decisions"
                )
                invocations += requests
                responses += response_count
                successes += success_count
                for model, count in _mapping(
                    evidence.get("observed_model_counts"), "source-v2 observed model counts"
                ).items():
                    observed_models[model] += _strict_non_negative_int(count, "observed model count")
                observed_missing += _strict_non_negative_int(
                    evidence.get("observed_model_missing_response_count"), "missing observed models"
                )
                observed_malformed += _strict_non_negative_int(
                    evidence.get("observed_model_malformed_response_count"), "malformed observed models"
                )
                usage_complete_responses += _strict_non_negative_int(
                    evidence.get("usage_complete_response_count"), "complete usage responses"
                )
                usage_missing_responses += _strict_non_negative_int(
                    evidence.get("usage_missing_response_count"), "missing usage responses"
                )
                usage_malformed_responses += _strict_non_negative_int(
                    evidence.get("usage_malformed_response_count"), "malformed usage responses"
                )
                if evidence.get("usage_complete") is True:
                    usage_complete_attempts += 1
                    input_usage += _strict_non_negative_int(evidence.get("input_usage"), "input usage")
                    output_usage += _strict_non_negative_int(evidence.get("output_usage"), "output usage")
                    total_usage += _strict_non_negative_int(evidence.get("total_usage"), "total usage")
                elif requests > 0:
                    usage_incomplete_attempts += 1
                cached = evidence.get("cached_input_usage")
                if cached is not None:
                    cached_input_usage += _strict_non_negative_int(cached, "cached input usage")
                    cached_reported = True
            for row in chunk.terminal_rows:
                pair_id = _non_empty(row.get("pair_id"), "source-v2 terminal pair_id")
                terminal_id = _non_empty(row.get("terminal_row_id"), "source-v2 terminal_row_id")
                if pair_id in terminal_pair_ids or terminal_id in terminal_ids:
                    raise ValueError("duplicate source-v2 terminal identity")
                if row.get("decision_variant") != "primary":
                    raise ValueError("source-v2 accepts Primary terminals only")
                terminal_pair_ids.add(pair_id)
                terminal_ids.add(terminal_id)
                terminal_handle.write(
                    _canonical_json(
                        _segmented_terminal_row(
                            row,
                            segment=(
                                "serial_prefix" if pair_id in prefix_terminal_ids else "concurrent_suffix"
                            ),
                            reconciliation_retry=pair_id in prefix.unknown_pair_ids,
                        )
                    )
                    + "\n"
                )
                terminal_count += 1
            frozen = _string_list(
                chunk.commit.get("frozen_campaign_engaged_user_ids"), "source-v2 frozen feedback"
            )
            if frozen != sorted(cumulative_feedback):
                raise ValueError("source-v2 batch feedback snapshot is not barrier-complete")
            committed = _string_list(
                chunk.commit.get("committed_primary_positive_user_ids"), "source-v2 committed feedback"
            )
            cumulative_feedback.update(committed)
            step_handle.write(
                _canonical_json(
                    {
                        "time_step": chunk.time_step,
                        "frozen_campaign_engaged_user_ids": frozen,
                        "committed_primary_positive_user_ids": committed,
                        "message_summaries": chunk.commit.get("message_summaries", []),
                    }
                )
                + "\n"
            )
            step_count += 1
        for handle in (candidate_handle, pair_handle, terminal_handle, step_handle):
            handle.flush()
            os.fsync(handle.fileno())

    expected_pairs = config.sample_size * len(config.messages)
    expected_candidates = len(config.messages) * (
        config.horizon * config.sample_size
        - config.delivery_capacity * config.horizon * (config.horizon - 1) // 2
    )
    if pair_count != expected_pairs or terminal_count != expected_pairs or evidence_count != expected_pairs:
        raise ValueError("source-v2 pair, terminal, or evidence denominator is incomplete")
    if candidate_count != expected_candidates or step_count != config.horizon:
        raise ValueError("source-v2 candidate or step denominator is incomplete")
    if pair_ids != terminal_pair_ids:
        raise ValueError("source-v2 pair and terminal identities are crossed")
    if not invocations >= responses >= successes:
        raise ValueError("source-v2 Provider accounting invariant failed")
    migration_unknown_charge = physical_attempt_count - invocations
    if migration_unknown_charge not in {0, 1, 2, 3}:
        raise ValueError("source-v2 migration unknown accounting is crossed")
    accounting = {
        "invocations": invocations,
        "responses": responses,
        "successful_decisions": successes,
        "observed_model_counts": dict(sorted(observed_models.items())),
        "observed_model_missing_response_count": observed_missing,
        "observed_model_malformed_response_count": observed_malformed,
        "usage_complete_attempts": usage_complete_attempts,
        "usage_incomplete_attempts": usage_incomplete_attempts,
        "usage_complete_response_count": usage_complete_responses,
        "usage_missing_response_count": usage_missing_responses,
        "usage_malformed_response_count": usage_malformed_responses,
        "input_usage": input_usage if usage_complete_attempts else None,
        "output_usage": output_usage if usage_complete_attempts else None,
        "total_usage": total_usage if usage_complete_attempts else None,
        "cached_input_usage": cached_input_usage if cached_reported else None,
        "migration_unknown_physical_charge": migration_unknown_charge,
    }
    artifacts = [
        _file_ref(staging, staging / name)
        for name in ("candidate_rows.jsonl", "pair_rows.jsonl", "terminal_rows.jsonl", "steps.jsonl")
    ]
    terminal_rows_sha256 = _sha256_file(terminal_path)
    complete_status = {
        "durable_prefix_terminal_count": len(prefix.terminal_by_pair_id),
        "concurrent_suffix_terminal_count": logical_count - prefix.attempt_prefix.logical_count,
        "committed_feedback_user_ids": sorted(cumulative_feedback),
        "unknown_pair_ids": [],
        "logical_count": logical_count,
        "physical_attempt_count": physical_attempt_count,
        "terminal_rows_relative_path": "source-v2/terminal_rows.jsonl",
        "terminal_rows_sha256": terminal_rows_sha256,
        "source_root_relative_path": "source-v2",
        "production_deploy_eligible": False,
    }
    manifest = {
        "schema_version": "full-pool-segmented-source-v2",
        "counts": {
            "candidate_rows": candidate_count,
            "pair_rows": pair_count,
            "terminal_rows": terminal_count,
            "steps": step_count,
        },
        "logical_count": logical_count,
        "physical_attempt_count": physical_attempt_count,
        "accounting": accounting,
        "artifacts": artifacts,
        "complete_status": complete_status,
        "cutoff_manifest_sha256": cutoff_manifest_sha256,
        "continuation_identity_hash": continuation_identity_hash,
        "prefix_identity_hash": prefix.run_identity.get("identity_hash"),
        "max_concurrency": FULL_POOL_SEGMENTED_MAX_CONCURRENCY,
        "production_deploy_eligible": False,
    }
    _atomic_write_json(staging / "manifest.json", manifest)
    manifest_sha256 = _sha256_file(staging / "manifest.json")
    ledger.append(
        "source_v2_prepared",
        {
            "source_manifest_sha256": manifest_sha256,
            "complete_status": complete_status,
        },
    )
    os.replace(staging, source)
    _fsync_directory(continuation)
    return source, manifest_sha256, complete_status


def _persist_cap_stop(
    *,
    continuation: Path,
    manifest_sha256: str,
    prefix: _FrozenPrefix,
    suffix_terminal_count: int,
    logical_count: int,
    physical_attempt_count: int,
) -> SegmentedContinuationResult:
    status = {
        "schema_version": _SEGMENTED_STATUS_SCHEMA,
        "lifecycle": SegmentedContinuationStatus.RESUMABLE.value,
        "manifest_sha256": manifest_sha256,
        "durable_prefix_terminal_count": len(prefix.terminal_by_pair_id),
        "concurrent_suffix_terminal_count": suffix_terminal_count,
        "committed_feedback_user_ids": [],
        "unknown_pair_ids": [],
        "logical_count": logical_count,
        "physical_attempt_count": physical_attempt_count,
        "terminal_rows_relative_path": None,
        "terminal_rows_sha256": None,
        "source_root_relative_path": None,
        "source_manifest_sha256": None,
        "production_deploy_eligible": False,
    }
    _atomic_write_json(continuation / _STATUS_FILE, status)
    _assert_prefix_unchanged(prefix)
    return _result_from_status(continuation, status)


def _load_complete_existing(
    *,
    prefix: _FrozenPrefix,
    continuation: Path,
    expected_identity: Mapping[str, object],
    expected_manifest: Mapping[str, object],
    manifest_sha256: str,
) -> SegmentedContinuationResult:
    _require_real_directory(continuation, "continuation workspace")
    if _read_json_object(continuation / _IDENTITY_FILE) != expected_identity:
        raise ValueError("existing continuation identity is crossed")
    envelope = _read_json_object(continuation / _MANIFEST_FILE)
    if envelope.get("manifest") != expected_manifest or envelope.get("manifest_sha256") != manifest_sha256:
        raise ValueError("existing complete cutoff manifest is crossed")
    identity_hash = _non_empty(expected_identity.get("identity_hash"), "continuation identity hash")
    dispatched, durable, wave_physical_attempts, source_anchor = _replay_continuation_ledger(
        continuation / _LEDGER_FILE,
        expected_identity_hash=identity_hash,
    )
    status_path = continuation / _STATUS_FILE
    if status_path.exists() or status_path.is_symlink():
        status = _read_json_object(status_path)
    else:
        status = _validated_complete_status_from_source(
            continuation=continuation,
            prefix=prefix,
            expected_manifest=expected_manifest,
            cutoff_manifest_sha256=manifest_sha256,
            continuation_identity_hash=identity_hash,
            dispatched=dispatched,
            durable=durable,
            wave_physical_attempts=wave_physical_attempts,
            source_anchor=source_anchor,
        )
        _atomic_write_json(status_path, status)
    authorization_raw = expected_manifest.get("reconciliation_authorization")
    migration_charge = (
        0
        if authorization_raw is None
        else _strict_non_negative_int(
            _mapping(authorization_raw, "reconciliation authorization").get("physical_attempt_charge"),
            "reconciliation physical charge",
        )
    )
    unretried_migration_unknown = len(prefix.unknown_pair_ids) if authorization_raw is None else 0
    expected_logical_progress = (
        prefix.attempt_prefix.logical_count + unretried_migration_unknown + len(dispatched)
    )
    expected_physical_progress = (
        prefix.attempt_prefix.physical_attempt_count + migration_charge + wave_physical_attempts
    )
    if status.get("concurrent_suffix_terminal_count") != len(durable):
        raise ValueError("continuation status terminal count is crossed with its ledger")
    if status.get("logical_count") != expected_logical_progress:
        raise ValueError("continuation logical count is crossed with dispatched reservations")
    if status.get("physical_attempt_count") != expected_physical_progress:
        raise ValueError("continuation physical count is crossed with wave accounting")
    if status.get("lifecycle") == SegmentedContinuationStatus.COMPLETE.value:
        expected_status = _validated_complete_status_from_source(
            continuation=continuation,
            prefix=prefix,
            expected_manifest=expected_manifest,
            cutoff_manifest_sha256=manifest_sha256,
            continuation_identity_hash=identity_hash,
            dispatched=dispatched,
            durable=durable,
            wave_physical_attempts=wave_physical_attempts,
            source_anchor=source_anchor,
        )
        if status != expected_status:
            raise ValueError("complete continuation status is crossed with durable source-v2")
    elif status.get("lifecycle") == SegmentedContinuationStatus.RECONCILIATION_REQUIRED.value:
        unknown = _string_list(status.get("unknown_pair_ids"), "continuation unknown pairs")
        if unknown != [pair_id for pair_id in dispatched if pair_id not in durable]:
            raise ValueError("continuation unknown status is crossed with its ledger")
    elif status.get("lifecycle") != SegmentedContinuationStatus.RESUMABLE.value:
        raise ValueError("incomplete segmented workspace cannot be automatically replayed")
    _assert_prefix_unchanged(prefix)
    return _result_from_status(continuation, status)


def _validated_complete_status_from_source(
    *,
    continuation: Path,
    prefix: _FrozenPrefix,
    expected_manifest: Mapping[str, object],
    cutoff_manifest_sha256: str,
    continuation_identity_hash: str,
    dispatched: Sequence[str],
    durable: Sequence[str],
    wave_physical_attempts: int,
    source_anchor: Mapping[str, object] | None,
) -> dict[str, object]:
    if source_anchor is None:
        raise ValueError("complete source-v2 lacks a durable ledger anchor")
    if list(dispatched) != list(durable):
        raise ValueError("complete continuation retains an unknown suffix dispatch")
    source = continuation / "source-v2"
    _require_real_directory(source, "segmented source-v2")
    source_manifest_path = source / "manifest.json"
    source_manifest_sha256 = _sha256_file(source_manifest_path)
    if source_manifest_sha256 != source_anchor.get("source_manifest_sha256"):
        raise ValueError("segmented source-v2 manifest hash mismatch")
    source_manifest = _read_json_object(source_manifest_path)
    if source_manifest.get("schema_version") != "full-pool-segmented-source-v2":
        raise ValueError("segmented source-v2 schema is unsupported")
    if source_manifest.get("cutoff_manifest_sha256") != cutoff_manifest_sha256:
        raise ValueError("source-v2 is crossed with the cutoff manifest")
    if source_manifest.get("continuation_identity_hash") != continuation_identity_hash:
        raise ValueError("source-v2 is crossed with the continuation identity")
    if source_manifest.get("prefix_identity_hash") != prefix.run_identity.get("identity_hash"):
        raise ValueError("source-v2 is crossed with the frozen prefix")

    expected_artifact_names = {
        "candidate_rows.jsonl",
        "pair_rows.jsonl",
        "terminal_rows.jsonl",
        "steps.jsonl",
    }
    artifacts = _mapping_sequence(source_manifest.get("artifacts"), "source-v2 artifacts")
    artifact_by_path: dict[str, dict[str, object]] = {}
    for raw_ref in artifacts:
        ref = dict(raw_ref)
        relative = _non_empty(ref.get("relative_path"), "source-v2 artifact path")
        if relative not in expected_artifact_names or relative in artifact_by_path:
            raise ValueError("source-v2 artifact inventory is not exact")
        path = source / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError("source-v2 artifact must be a regular file")
        if _file_ref(source, path) != ref:
            raise ValueError("source-v2 artifact hash mismatch")
        artifact_by_path[relative] = ref
    if set(artifact_by_path) != expected_artifact_names:
        raise ValueError("source-v2 artifact inventory is not exact")
    source_inventory = _artifact_inventory(source)
    if set(source_inventory) != expected_artifact_names | {"manifest.json"}:
        raise ValueError("source-v2 contains unmanifested artifacts")

    counts = _mapping(source_manifest.get("counts"), "source-v2 counts")
    observed_counts: dict[str, int] = {}
    for key, relative in (
        ("candidate_rows", "candidate_rows.jsonl"),
        ("pair_rows", "pair_rows.jsonl"),
        ("terminal_rows", "terminal_rows.jsonl"),
    ):
        with (source / relative).open(encoding="utf-8") as handle:
            observed_counts[key] = sum(bool(line.strip()) for line in handle)
    cumulative_feedback: set[str] = set()
    step_count = 0
    with (source / "steps.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            step = _mapping(json.loads(line), "source-v2 step")
            frozen = _string_list(
                step.get("frozen_campaign_engaged_user_ids"), "source-v2 recovered frozen feedback"
            )
            if frozen != sorted(cumulative_feedback):
                raise ValueError("source-v2 recovered feedback barrier is crossed")
            cumulative_feedback.update(
                _string_list(
                    step.get("committed_primary_positive_user_ids"),
                    "source-v2 recovered committed feedback",
                )
            )
            step_count += 1
    observed_counts["steps"] = step_count
    for key, observed in observed_counts.items():
        if _strict_non_negative_int(counts.get(key), f"source-v2 {key} count") != observed:
            raise ValueError("source-v2 artifact count is crossed with its manifest")

    expected_logical = _strict_non_negative_int(
        expected_manifest.get("expected_logical_count"), "expected segmented logical count"
    )
    if expected_logical != prefix.attempt_prefix.logical_count + len(dispatched):
        raise ValueError("source-v2 logical denominator is crossed with the ledger")
    if observed_counts["pair_rows"] != expected_logical or observed_counts["terminal_rows"] != expected_logical:
        raise ValueError("source-v2 terminal denominator is incomplete")
    expected_horizon = _strict_non_negative_int(
        expected_manifest.get("expected_horizon"), "expected segmented horizon"
    )
    if observed_counts["steps"] != expected_horizon:
        raise ValueError("source-v2 step denominator is incomplete")
    authorization_raw = expected_manifest.get("reconciliation_authorization")
    migration_charge = (
        0
        if authorization_raw is None
        else _strict_non_negative_int(
            _mapping(authorization_raw, "reconciliation authorization").get("physical_attempt_charge"),
            "reconciliation physical charge",
        )
    )
    expected_physical = (
        prefix.attempt_prefix.physical_attempt_count + migration_charge + wave_physical_attempts
    )
    accounting = _mapping(source_manifest.get("accounting"), "source-v2 accounting")
    if accounting.get("migration_unknown_physical_charge") != migration_charge:
        raise ValueError("source-v2 migration unknown accounting is crossed")
    if source_manifest.get("logical_count") != expected_logical:
        raise ValueError("source-v2 logical count is crossed")
    if source_manifest.get("physical_attempt_count") != expected_physical:
        raise ValueError("source-v2 physical count is crossed with wave accounting")

    complete_status = dict(
        _mapping(source_manifest.get("complete_status"), "source-v2 complete status facts")
    )
    if complete_status != source_anchor.get("complete_status"):
        raise ValueError("source-v2 complete status facts are crossed with their ledger anchor")
    expected_complete_status = {
        "durable_prefix_terminal_count": len(prefix.terminal_by_pair_id),
        "concurrent_suffix_terminal_count": len(durable),
        "committed_feedback_user_ids": sorted(cumulative_feedback),
        "unknown_pair_ids": [],
        "logical_count": expected_logical,
        "physical_attempt_count": expected_physical,
        "terminal_rows_relative_path": "source-v2/terminal_rows.jsonl",
        "terminal_rows_sha256": artifact_by_path["terminal_rows.jsonl"]["sha256"],
        "source_root_relative_path": "source-v2",
        "production_deploy_eligible": False,
    }
    if complete_status != expected_complete_status:
        raise ValueError("source-v2 complete status facts fail durable reconstruction")
    return {
        "schema_version": _SEGMENTED_STATUS_SCHEMA,
        "lifecycle": SegmentedContinuationStatus.COMPLETE.value,
        "manifest_sha256": cutoff_manifest_sha256,
        **complete_status,
        "source_manifest_sha256": source_manifest_sha256,
    }


def _reserve_dynamic_wave(
    *,
    remaining_pair_count: int,
    physical_attempts: int,
    maximum_attempts_per_dispatch: int,
) -> _DynamicWaveReservation:
    for value, context in (
        (remaining_pair_count, "remaining pair count"),
        (physical_attempts, "physical attempt count"),
        (maximum_attempts_per_dispatch, "maximum attempts per dispatch"),
    ):
        _strict_non_negative_int(value, context)
    if remaining_pair_count and maximum_attempts_per_dispatch < 1:
        raise ValueError("pending suffix dispatch requires a positive retry window")
    available = max(0, FULL_POOL_SEGMENTED_PHYSICAL_CAP - physical_attempts)
    wave_size = min(
        remaining_pair_count,
        FULL_POOL_SEGMENTED_MAX_CONCURRENCY,
        available // maximum_attempts_per_dispatch,
    )
    return _DynamicWaveReservation(
        wave_size=wave_size,
        reserved_physical_attempts=wave_size * maximum_attempts_per_dispatch,
    )


def _reserve_total_caps(
    *,
    prefix_logical: int,
    prefix_physical: int,
    unknown_logical_charge: int,
    unknown_physical_charge: int,
    pending_pair_count: int,
    authorized_unknown_retry_count: int,
    maximum_attempts_per_dispatch: int,
) -> _CapReservation:
    values = {
        "prefix_logical": prefix_logical,
        "prefix_physical": prefix_physical,
        "unknown_logical_charge": unknown_logical_charge,
        "unknown_physical_charge": unknown_physical_charge,
        "pending_pair_count": pending_pair_count,
        "authorized_unknown_retry_count": authorized_unknown_retry_count,
        "maximum_attempts_per_dispatch": maximum_attempts_per_dispatch,
    }
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values.values()):
        raise ValueError("segmented cap inputs must be non-negative integers")
    if unknown_logical_charge not in {0, 1}:
        raise ValueError("migration unknown count must be zero or one")
    if authorized_unknown_retry_count > unknown_logical_charge or authorized_unknown_retry_count > pending_pair_count:
        raise ValueError("authorized unknown retries are crossed with pending migration unknowns")
    if pending_pair_count and maximum_attempts_per_dispatch < 1:
        raise ValueError("pending suffix dispatch requires a positive attempt window")

    suffix_logical = pending_pair_count - authorized_unknown_retry_count
    suffix_physical = pending_pair_count * maximum_attempts_per_dispatch
    logical_total = prefix_logical + unknown_logical_charge + suffix_logical
    physical_total = prefix_physical + unknown_physical_charge + suffix_physical
    if logical_total > FULL_POOL_SEGMENTED_LOGICAL_CAP:
        raise ValueError("segmented continuation logical cap would be exceeded")
    if physical_total > FULL_POOL_SEGMENTED_PHYSICAL_CAP:
        raise ValueError("segmented continuation physical cap would be exceeded")
    return _CapReservation(
        suffix_logical_reservation=suffix_logical,
        suffix_physical_reservation=suffix_physical,
        logical_total=logical_total,
        physical_total=physical_total,
    )


def _dataset_path_from_v1_identity(prefix_workspace: Path) -> Path:
    identity = _read_json_object(
        prefix_workspace.expanduser() / "concurrent_message_execution_run_identity.json"
    )
    fingerprints = _mapping(identity.get("sample_data_fingerprints"), "sample data fingerprints")
    return Path(_non_empty(fingerprints.get("dataset_dir"), "v1 dataset_dir"))


def _freeze_v1_prefix(workspace_raw: Path) -> _FrozenPrefix:
    workspace = workspace_raw.expanduser().resolve(strict=True)
    _require_real_directory(workspace, "v1 prefix workspace")
    inventory_before = _artifact_inventory(workspace)
    journal = ConcurrentExecutionJournal.open_existing(workspace)
    replay = journal._replay_runtime()
    run_identity = _mapping(replay.get("identity"), "v1 run identity")
    status = _mapping(replay.get("status"), "v1 journal status")
    if status.get("lifecycle") not in {"running", "inflight_unknown"}:
        raise ValueError("v1 prefix must contain one running active batch")
    records = _mapping_sequence(replay.get("records"), "v1 runtime records")
    active_snapshot = next(
        (record for record in reversed(records) if record.get("record_type") == "snapshot"),
        None,
    )
    if active_snapshot is None:
        raise ValueError("v1 prefix has no active batch snapshot")
    active_document = _mapping(active_snapshot.get("snapshot_document"), "active snapshot document")
    active_payload = _mapping(active_document.get("payload"), "active snapshot payload")
    active_time_step = _strict_non_negative_int(
        _mapping(active_document.get("snapshot_identity"), "active snapshot identity").get("time_step"),
        "active time_step",
    )
    committed_count = _strict_non_negative_int(status.get("committed_batch_count"), "committed batch count")
    expected_count = _strict_non_negative_int(status.get("expected_batch_count"), "expected batch count")
    if active_time_step != committed_count or not committed_count < expected_count:
        raise ValueError("segmented cutoff active batch is crossed with committed progress")

    spool = _ConcurrentRuntimeBatchSpool(
        workspace,
        run_id=journal.run_id,
        identity_hash=journal.identity_hash,
        terminal_variants=("primary",),
    )
    committed_chunks = spool.iter_committed(replay)
    committed_records = [
        record
        for record in records
        if record.get("record_type") == "event" and record.get("event_type") == "batch_committed"
    ]
    ordered_pair_ids: list[str] = []
    plan_by_pair_id: dict[str, dict[str, object]] = {}
    terminal_by_pair_id: dict[str, dict[str, object]] = {}
    evidence_by_pair_id: dict[str, dict[str, object]] = {}
    committed_batches: list[dict[str, object]] = []
    committed_feedback: set[str] = set()
    observed_committed_count = 0
    for chunk, record in zip(committed_chunks, committed_records, strict=True):
        observed_committed_count += 1
        chunk_pair_ids: list[str] = []
        for row in chunk.result_rows:
            pair_id = _non_empty(row.get("pair_id"), "committed pair_id")
            chunk_pair_ids.append(pair_id)
            ordered_pair_ids.append(pair_id)
            plan_by_pair_id[pair_id] = {
                field_name: row[field_name]
                for field_name in (
                    "pair_id",
                    "pair_schedule_position",
                    "time_step",
                    "message_id",
                    "user_id",
                )
            }
        chunk_terminal_ids: list[str] = []
        for row in chunk.terminal_rows:
            pair_id = _non_empty(row.get("pair_id"), "committed terminal pair_id")
            if pair_id in terminal_by_pair_id:
                raise ValueError(f"duplicate durable terminal pair {pair_id}")
            terminal_by_pair_id[pair_id] = dict(row)
            chunk_terminal_ids.append(_non_empty(row.get("terminal_row_id"), "terminal_row_id"))
        for row in chunk.variant_evidence_rows:
            pair_id = _non_empty(row.get("pair_id"), "committed evidence pair_id")
            if pair_id in evidence_by_pair_id:
                raise ValueError(f"duplicate durable variant evidence pair {pair_id}")
            evidence_by_pair_id[pair_id] = dict(row)
        payload = _mapping(record.get("payload"), "batch commit payload")
        committed_ids = _string_list(payload.get("committed_user_ids"), "committed feedback users")
        committed_feedback.update(committed_ids)
        committed_batches.append(
            {
                "time_step": chunk.time_step,
                "batch_snapshot_hash": record.get("batch_snapshot_hash"),
                "ordered_pair_ids": chunk_pair_ids,
                "ordered_terminal_ids": chunk_terminal_ids,
                "frozen_feedback_user_ids": _string_list(
                    chunk.commit.get("frozen_campaign_engaged_user_ids"),
                    "spooled frozen feedback users",
                ),
                "committed_feedback_user_ids": committed_ids,
                "spool_ref": dict(_mapping(payload.get("batch_spool_chunk"), "batch spool ref")),
            }
        )

    if observed_committed_count != committed_count:
        raise ValueError("v1 committed spool does not close the journal prefix")

    active_plans: list[dict[str, object]] = []
    messages = _mapping_sequence(active_payload.get("messages"), "active snapshot messages")
    for message in messages:
        active_plans.extend(
            _mapping_sequence(message.get("selected_pair_plans"), "active selected pair plans")
        )
    active_pair_ids: list[str] = []
    for plan in active_plans:
        pair_id = _non_empty(plan.get("pair_id"), "active pair_id")
        if pair_id in plan_by_pair_id:
            raise ValueError(f"duplicate planned pair {pair_id}")
        active_pair_ids.append(pair_id)
        ordered_pair_ids.append(pair_id)
        plan_by_pair_id[pair_id] = dict(plan)
    positions = [
        _strict_non_negative_int(plan_by_pair_id[pair_id].get("pair_schedule_position"), "pair schedule position")
        for pair_id in ordered_pair_ids
    ]
    if positions != list(range(len(positions))):
        raise ValueError("v1 serial prefix pair schedule is not canonical and contiguous")

    started_pairs: list[str] = []
    active_terminal_ids: list[str] = []
    for record in records:
        if record.get("record_type") != "event":
            continue
        event_type = record.get("event_type")
        event_identity = _mapping(record.get("event_identity"), "v1 event identity")
        pair_id_raw = event_identity.get("pair_id")
        if event_type == "variant_started" and isinstance(pair_id_raw, str):
            started_pairs.append(pair_id_raw)
        elif event_type == "variant_terminal" and isinstance(pair_id_raw, str):
            payload = _mapping(record.get("payload"), "active terminal payload")
            row = _mapping(payload.get("terminal_row"), "active terminal row")
            if pair_id_raw in terminal_by_pair_id:
                raise ValueError(f"duplicate durable terminal pair {pair_id_raw}")
            if row.get("pair_id") != pair_id_raw or row.get("decision_variant") != "primary":
                raise ValueError("active terminal identity is crossed")
            terminal_by_pair_id[pair_id_raw] = row
            evidence = _mapping(payload.get("variant_evidence"), "active variant evidence")
            if evidence.get("pair_id") != pair_id_raw:
                raise ValueError("active variant evidence identity is crossed")
            evidence_by_pair_id[pair_id_raw] = evidence
            active_terminal_ids.append(_non_empty(row.get("terminal_row_id"), "terminal_row_id"))
    _validate_unique_terminal_rows(tuple(terminal_by_pair_id.values()))
    unknown_pairs = tuple(
        pair_id
        for pair_id in started_pairs
        if pair_id in active_pair_ids and pair_id not in terminal_by_pair_id
    )
    if len(unknown_pairs) > 1 or len(set(unknown_pairs)) != len(unknown_pairs):
        raise ValueError("migration prefix may contain at most one started-without-terminal pair")
    if bool(unknown_pairs) != (status.get("inflight_unknown") is True):
        raise ValueError("v1 journal unknown status is crossed with active events")

    formal_identity = _read_json_object(workspace / _FULL_POOL_IDENTITY_FILE)
    if formal_identity.get("schema_version") != _FULL_POOL_IDENTITY_SCHEMA:
        raise ValueError("v1 Full-Pool operational identity schema is unsupported")
    attempt_prefix = _read_attempt_prefix(workspace, formal_identity=formal_identity)
    if set(attempt_prefix.terminal_pair_ids) != set(terminal_by_pair_id):
        raise ValueError("v1 journal terminals are crossed with the accepted attempt-ledger prefix")
    if attempt_prefix.pending_pair_id != (unknown_pairs[0] if unknown_pairs else None):
        raise ValueError("v1 attempt reservation is crossed with the migration unknown")

    active_frozen_feedback = tuple(
        _string_list(
            active_payload.get("frozen_campaign_engaged_user_ids"),
            "active frozen campaign feedback",
        )
    )
    if active_frozen_feedback != tuple(sorted(committed_feedback)):
        raise ValueError("active batch feedback snapshot is crossed with committed prefix feedback")
    provider_by_variant = _mapping(run_identity.get("provider_contract"), "v1 provider contract")
    provider_contract = _mapping(provider_by_variant.get("primary"), "v1 Primary provider contract")
    prompt_by_variant = _mapping(run_identity.get("prompt_contract"), "v1 prompt contract")
    prompt_contract = _mapping(prompt_by_variant.get("primary"), "v1 Primary prompt contract")
    configuration = _mapping(run_identity.get("configuration"), "v1 run configuration")
    prompt_version = _non_empty(configuration.get("primary_prompt_version"), "v1 Primary prompt version")
    if prompt_contract.get("prompt_version") != prompt_version or provider_contract.get("prompt_version") != prompt_version:
        raise ValueError("v1 Prompt identity is crossed across run contracts")
    execution_contract = _mapping(run_identity.get("execution_contract"), "v1 execution contract")
    formal_execution_raw = execution_contract.get("formal_execution")
    effective_execution = (
        _mapping(formal_execution_raw, "v1 Formal execution contract")
        if isinstance(formal_execution_raw, Mapping)
        else execution_contract
    )
    request_contract = _mapping(effective_execution.get("request_contract"), "v1 request contract")
    max_retries = _strict_non_negative_int(request_contract.get("max_retries"), "v1 max_retries")
    if effective_execution.get("logical_judgment_cap") != FULL_POOL_SEGMENTED_LOGICAL_CAP:
        raise ValueError("v1 logical cap is crossed")
    if effective_execution.get("physical_attempt_cap") != FULL_POOL_SEGMENTED_PHYSICAL_CAP:
        raise ValueError("v1 physical cap is crossed")
    if effective_execution.get("worker_count") != 1:
        raise ValueError("accepted v1 serial prefix must freeze worker_count=1")

    inventory_after = _artifact_inventory(workspace)
    if inventory_after != inventory_before:
        raise ValueError("v1 prefix changed while the cutoff was frozen")
    accepted_artifacts = tuple(inventory_before[path] for path in sorted(inventory_before))
    journal_ref = next(
        ref for ref in accepted_artifacts if ref["relative_path"] == "concurrent_message_execution_journal.jsonl"
    )
    ordered_terminal_ids = tuple(
        _non_empty(terminal_by_pair_id[pair_id].get("terminal_row_id"), "terminal_row_id")
        for pair_id in ordered_pair_ids
        if pair_id in terminal_by_pair_id
    )
    return _FrozenPrefix(
        workspace=workspace,
        run_identity=run_identity,
        formal_identity=formal_identity,
        accepted_artifacts=accepted_artifacts,
        journal_ref=journal_ref,
        attempt_prefix=attempt_prefix,
        committed_batches=tuple(committed_batches),
        runtime_replay=dict(replay),
        active_batch={
            "time_step": active_time_step,
            "batch_snapshot_hash": active_snapshot.get("snapshot_hash"),
            "snapshot_ref": {
                "relative_path": active_snapshot.get("snapshot_path"),
                "sha256": active_snapshot.get("snapshot_hash"),
            },
            "ordered_pair_ids": active_pair_ids,
            "ordered_terminal_ids": active_terminal_ids,
            "frozen_feedback_user_ids": list(active_frozen_feedback),
        },
        active_snapshot_payload=active_payload,
        expected_batch_count=expected_count,
        ordered_pair_ids=tuple(ordered_pair_ids),
        plan_by_pair_id=plan_by_pair_id,
        terminal_by_pair_id=terminal_by_pair_id,
        evidence_by_pair_id=evidence_by_pair_id,
        ordered_terminal_ids=ordered_terminal_ids,
        committed_feedback_user_ids=tuple(sorted(committed_feedback)),
        active_frozen_feedback_user_ids=active_frozen_feedback,
        unknown_pair_ids=unknown_pairs,
        prompt_version=prompt_version,
        provider_contract=provider_contract,
        prompt_contract=prompt_contract,
        maximum_attempts_per_dispatch=max_retries + 1,
    )


def _read_attempt_prefix(workspace: Path, *, formal_identity: Mapping[str, object]) -> _AttemptPrefix:
    ledger_path = workspace / _FULL_POOL_LEDGER_FILE
    identity_hash = _non_empty(
        formal_identity.get("execution_contract_sha256"),
        "v1 execution contract hash",
    )
    if _SHA256_PATTERN.fullmatch(identity_hash) is None:
        raise ValueError("v1 execution contract hash is invalid")
    sequence = 0
    previous_checksum: str | None = None
    pending: str | None = None
    pending_physical_count = 0
    terminal_pair_ids: list[str] = []
    physical_attempt_count = 0
    provider_response_count = 0
    successful_decision_count = 0
    observed_model_counts: Counter[str] = Counter()
    usage_complete_response_count = 0
    usage_missing_response_count = 0
    usage_malformed_response_count = 0
    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    cached_input_tokens = 0
    with ledger_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            raw = line.strip()
            if not raw:
                continue
            record = _mapping(json.loads(raw), f"v1 attempt ledger line {line_number}")
            checksum = _non_empty(record.pop("checksum", None), "v1 attempt ledger checksum")
            if record.get("schema_version") != _FULL_POOL_LEDGER_SCHEMA:
                raise ValueError("v1 attempt ledger schema is unsupported")
            if record.get("execution_contract_sha256") != identity_hash:
                raise ValueError("v1 attempt ledger execution identity is crossed")
            if record.get("sequence") != sequence + 1 or record.get("previous_checksum") != previous_checksum:
                raise ValueError("v1 attempt ledger sequence or checksum chain is broken")
            if _sha256_json(record) != checksum:
                raise ValueError("v1 attempt ledger checksum mismatch")
            event_type = record.get("event_type")
            payload = _mapping(record.get("payload"), "v1 attempt ledger payload")
            if event_type == "judgment_reserved":
                if pending is not None:
                    raise ValueError("v1 attempt ledger contains overlapping reservations")
                pending = _non_empty(payload.get("pair_id"), "reserved pair_id")
                pending_physical_count = 0
            elif event_type == "physical_attempt_accounted":
                if _non_empty(payload.get("pair_id"), "attempt pair_id") != pending:
                    raise ValueError("v1 physical attempt is crossed with its reservation")
                pending_physical_count += 1
            elif event_type == "judgment_terminal":
                pair_id = _non_empty(payload.get("pair_id"), "terminal pair_id")
                if pair_id != pending or pair_id in terminal_pair_ids:
                    raise ValueError("v1 attempt terminal is crossed or duplicated")
                accounting = _mapping(payload.get("accounting"), "v1 terminal accounting")
                requests = _strict_non_negative_int(accounting.get("request_invocations"), "v1 request invocations")
                responses = _strict_non_negative_int(accounting.get("provider_response_count"), "v1 responses")
                successes = _strict_non_negative_int(accounting.get("successful_decision_count"), "v1 successes")
                if not 1 <= requests <= 3 or requests != pending_physical_count:
                    raise ValueError("v1 terminal physical attempts violate the request contract")
                if not requests >= responses >= successes or successes not in {0, 1}:
                    raise ValueError("v1 terminal accounting invariant failed")
                observed = _mapping(accounting.get("observed_model_counts"), "v1 observed models")
                for model, count in observed.items():
                    observed_model_counts[model] += _strict_non_negative_int(count, "v1 observed-model count")
                physical_attempt_count += requests
                provider_response_count += responses
                successful_decision_count += successes
                usage_complete_response_count += _strict_non_negative_int(
                    accounting.get("usage_complete_response_count"), "v1 complete usage count"
                )
                usage_missing_response_count += _strict_non_negative_int(
                    accounting.get("usage_missing_response_count"), "v1 missing usage count"
                )
                usage_malformed_response_count += _strict_non_negative_int(
                    accounting.get("usage_malformed_response_count"), "v1 malformed usage count"
                )
                if accounting.get("usage_complete") is True:
                    input_tokens += _strict_non_negative_int(accounting.get("input_usage"), "v1 input usage")
                    output_tokens += _strict_non_negative_int(accounting.get("output_usage"), "v1 output usage")
                    total_tokens += _strict_non_negative_int(accounting.get("total_usage"), "v1 total usage")
                    cached_input_tokens += _strict_non_negative_int(
                        accounting.get("cached_input_usage"), "v1 cached input usage"
                    )
                terminal_pair_ids.append(pair_id)
                pending = None
                pending_physical_count = 0
            elif event_type == "reservation_released":
                if _non_empty(payload.get("pair_id"), "released pair_id") != pending:
                    raise ValueError("v1 released reservation is crossed")
                pending = None
                pending_physical_count = 0
            elif event_type != "cap_stop":
                raise ValueError("v1 attempt ledger event type is unsupported")
            sequence += 1
            previous_checksum = checksum

    status = _read_json_object(workspace / _FULL_POOL_STATUS_FILE)
    if status.get("schema_version") != _FULL_POOL_STATUS_SCHEMA:
        raise ValueError("v1 Full-Pool status schema is unsupported")
    if status.get("execution_contract_sha256") != identity_hash:
        raise ValueError("v1 Full-Pool status identity is crossed")
    if status.get("logical_judgments") != len(terminal_pair_ids):
        raise ValueError("v1 logical count is crossed with the attempt ledger")
    if status.get("physical_attempts") != physical_attempt_count:
        raise ValueError("v1 physical count is crossed with the attempt ledger")
    return _AttemptPrefix(
        terminal_pair_ids=tuple(terminal_pair_ids),
        pending_pair_id=pending,
        pending_physical_count=pending_physical_count,
        logical_count=len(terminal_pair_ids),
        physical_attempt_count=physical_attempt_count,
        provider_response_count=provider_response_count,
        successful_decision_count=successful_decision_count,
        observed_model_counts=dict(observed_model_counts),
        usage_complete_response_count=usage_complete_response_count,
        usage_missing_response_count=usage_missing_response_count,
        usage_malformed_response_count=usage_malformed_response_count,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cached_input_tokens=cached_input_tokens,
        accepted_ref=_file_ref(workspace, ledger_path),
    )


def _validate_reconciliation(
    prefix: _FrozenPrefix,
    authorization: FullPoolReconciliationAuthorization | None,
) -> bool:
    if not prefix.unknown_pair_ids:
        if authorization is not None:
            raise ValueError("reconciliation authorization was supplied without a migration unknown")
        return False
    if authorization is None:
        return False
    if authorization.prefix_run_identity_hash != prefix.run_identity.get("identity_hash"):
        raise ValueError("reconciliation authorization is crossed with the v1 run identity")
    if authorization.unknown_pair_id != prefix.unknown_pair_ids[0]:
        raise ValueError("reconciliation authorization is crossed with the migration unknown pair")
    if authorization.physical_attempt_charge != prefix.maximum_attempts_per_dispatch:
        raise ValueError("reconciliation physical charge must exactly reserve the v1 request window")
    if authorization.physical_attempt_charge < prefix.attempt_prefix.pending_physical_count:
        raise ValueError("reconciliation physical charge is below durable pending attempts")
    return True


def _validate_decision_inputs(
    prefix: _FrozenPrefix,
    pending_pair_ids: Sequence[str],
    decision_inputs: Mapping[str, DecisionInput],
) -> None:
    if set(decision_inputs) != set(pending_pair_ids):
        raise ValueError("DecisionInput identities must exactly close the pending suffix schedule")
    for pair_id in pending_pair_ids:
        decision_input = decision_inputs[pair_id]
        if not isinstance(decision_input, DecisionInput):
            raise TypeError("segmented continuation requires typed DecisionInput values")
        plan = prefix.plan_by_pair_id[pair_id]
        if decision_input.profile.user_id != plan.get("user_id"):
            raise ValueError("DecisionInput user identity is crossed with the frozen pair plan")
        if decision_input.post.post_id != plan.get("message_id"):
            raise ValueError("DecisionInput message identity is crossed with the frozen pair plan")
        if decision_input.time_step != plan.get("time_step"):
            raise ValueError("DecisionInput time_step is crossed with the frozen pair plan")
        if decision_input.prompt_version != prefix.prompt_version:
            raise ValueError("DecisionInput Prompt version is crossed with the v1 contract")
        if decision_input.peer_context != PeerContext() or decision_input.platform_context != PlatformContext():
            raise ValueError("segmented continuation must preserve the frozen zero-visible-context semantics")


def _build_lanes(
    prefix: _FrozenPrefix,
    adapter_factory: Callable[[int], LLMDecisionAdapter],
) -> tuple[LLMDecisionAdapter, ...]:
    adapters = tuple(adapter_factory(lane_id) for lane_id in range(FULL_POOL_SEGMENTED_MAX_CONCURRENCY))
    if len({id(adapter) for adapter in adapters}) != FULL_POOL_SEGMENTED_MAX_CONCURRENCY:
        raise ValueError("adapter_factory must return one isolated Adapter per lane")
    leaf_ids: set[int] = set()
    client_ids: set[int] = set()
    for adapter in adapters:
        if not isinstance(adapter, LLMDecisionAdapter):
            raise TypeError("adapter_factory must return LLMDecisionAdapter instances")
        leaf, caches = _unwrap_adapter(adapter)
        if caches:
            raise ValueError("Full-Pool segmented continuation forbids DecisionCache")
        if id(leaf) in leaf_ids:
            raise ValueError("adapter_factory lanes must not share an underlying Adapter")
        leaf_ids.add(id(leaf))
        client = getattr(leaf, "client", None)
        if client is not None:
            if id(client) in client_ids:
                raise ValueError("adapter_factory lanes must not share an underlying Provider client")
            client_ids.add(id(client))
        if _adapter_prompt_version(adapter) != prefix.prompt_version:
            raise ValueError("lane Adapter Prompt version is crossed with the v1 prefix")
        if _adapter_safe_metadata(adapter, ProviderLLMConfig()) != prefix.provider_contract:
            raise ValueError("lane Adapter provider/model/request metadata is crossed with the v1 prefix")
        if _adapter_external_request_invocations(adapter) != 0:
            raise ValueError("lane Adapter must have zero prior external request invocations")
    return adapters


def _execute_pair(
    *,
    pair_id: str,
    plan: Mapping[str, object],
    decision_input: DecisionInput,
    adapter: LLMDecisionAdapter,
    provider_metadata: Mapping[str, object],
) -> _WorkerResult:
    context = _VariantDecisionContext(
        decision_variant="primary",
        prompt_token=decision_input.prompt_version,
        post=decision_input.post,
        profile=decision_input.profile,
        peer_context=decision_input.peer_context,
        platform_context=decision_input.platform_context,
    )
    position = _strict_non_negative_int(plan.get("pair_schedule_position"), "pair schedule position")
    time_step = _strict_non_negative_int(plan.get("time_step"), "pair time_step")
    message_id = _non_empty(plan.get("message_id"), "pair message_id")
    user_id = _non_empty(plan.get("user_id"), "pair user_id")
    attempt, accounting = _execute_runtime_variant(
        adapter=adapter,
        context=context,
        pair_schedule_position=position,
        time_step=time_step,
        message_id=message_id,
        default_provider_metadata=provider_metadata,
    )
    terminal_row, _, variant_evidence = _build_runtime_terminal_row(
        pair_id=pair_id,
        pair_schedule_position=position,
        time_step=time_step,
        message_id=message_id,
        user_id=user_id,
        context=context,
        attempt=attempt,
        accounting=accounting,
        default_provider_metadata=provider_metadata,
    )
    return _WorkerResult(pair_id=pair_id, terminal_row=terminal_row, variant_evidence=variant_evidence)


def _cutoff_manifest(
    *,
    prefix: _FrozenPrefix,
    continuation_id: str,
    pending_pair_ids: Sequence[str],
    decision_inputs: Mapping[str, DecisionInput],
    reconciliation_authorization: FullPoolReconciliationAuthorization | None,
    cap: _CapReservation,
) -> dict[str, object]:
    authorization_payload = (
        reconciliation_authorization.model_dump(mode="json")
        if reconciliation_authorization is not None
        else None
    )
    return {
        "schema_version": _SEGMENTED_MANIFEST_SCHEMA,
        "continuation_id": continuation_id,
        "v1_contract_identity": prefix.formal_identity,
        "v1_run_identity": prefix.run_identity,
        "accepted_journal_prefix": prefix.journal_ref,
        "accepted_attempt_ledger_prefix": prefix.attempt_prefix.accepted_ref,
        "accepted_artifacts": list(prefix.accepted_artifacts),
        "committed_batches": list(prefix.committed_batches),
        "active_batch": prefix.active_batch,
        "ordered_pair_ids": list(prefix.ordered_pair_ids),
        "ordered_terminal_ids": list(prefix.ordered_terminal_ids),
        "durable_terminal_pair_ids": [
            pair_id for pair_id in prefix.ordered_pair_ids if pair_id in prefix.terminal_by_pair_id
        ],
        "committed_feedback_user_ids": list(prefix.committed_feedback_user_ids),
        "active_frozen_feedback_user_ids": list(prefix.active_frozen_feedback_user_ids),
        "prefix_accounting": prefix.attempt_prefix.accounting(),
        "unknown_count": len(prefix.unknown_pair_ids),
        "unknown_pair_ids": list(prefix.unknown_pair_ids),
        "reconciliation_authorization": authorization_payload,
        "reconciliation_authorization_sha256": (
            _sha256_json(authorization_payload) if authorization_payload is not None else None
        ),
        "suffix": {
            "max_concurrency": FULL_POOL_SEGMENTED_MAX_CONCURRENCY,
            "pending_pair_ids": list(pending_pair_ids),
            "decision_input_refs": [
                {"pair_id": pair_id, "cache_key": decision_inputs[pair_id].cache_key()}
                for pair_id in pending_pair_ids
            ],
            "logical_reservation": cap.suffix_logical_reservation,
            "physical_reservation": cap.suffix_physical_reservation,
            "maximum_attempts_per_dispatch": prefix.maximum_attempts_per_dispatch,
        },
        "caps": {
            "logical_cap": FULL_POOL_SEGMENTED_LOGICAL_CAP,
            "physical_cap": FULL_POOL_SEGMENTED_PHYSICAL_CAP,
            "reserved_logical_total": cap.logical_total,
            "reserved_physical_total": cap.physical_total,
        },
        "production_deploy_eligible": False,
    }


def _continuation_identity(
    *,
    continuation: Path,
    continuation_id: str,
    prefix: _FrozenPrefix,
    manifest_sha256: str,
) -> dict[str, object]:
    body = {
        "schema_version": _SEGMENTED_IDENTITY_SCHEMA,
        "continuation_id": continuation_id,
        "workspace": str(continuation),
        "prefix_run_id": prefix.run_identity.get("run_id"),
        "prefix_identity_hash": prefix.run_identity.get("identity_hash"),
        "cutoff_manifest_sha256": manifest_sha256,
        "max_concurrency": FULL_POOL_SEGMENTED_MAX_CONCURRENCY,
        "logical_cap": FULL_POOL_SEGMENTED_LOGICAL_CAP,
        "physical_cap": FULL_POOL_SEGMENTED_PHYSICAL_CAP,
        "provider_contract": prefix.provider_contract,
        "prompt_contract": prefix.prompt_contract,
        "production_deploy_eligible": False,
    }
    identity_hash = _sha256_json(body)
    return {**body, "run_id": f"full-pool-segmented-{identity_hash[:16]}", "identity_hash": identity_hash}


def _load_existing_result(
    *,
    prefix: _FrozenPrefix,
    continuation: Path,
    expected_identity: Mapping[str, object],
    expected_manifest: Mapping[str, object],
    expected_manifest_sha256: str,
) -> SegmentedContinuationResult:
    _require_real_directory(continuation, "continuation workspace")
    if _read_json_object(continuation / _IDENTITY_FILE) != expected_identity:
        raise ValueError("existing continuation identity is crossed")
    envelope = _read_json_object(continuation / _MANIFEST_FILE)
    if set(envelope) != {"schema_version", "manifest", "manifest_sha256"}:
        raise ValueError("cutoff manifest envelope fields are not exact")
    if envelope.get("schema_version") != _SEGMENTED_MANIFEST_ENVELOPE_SCHEMA:
        raise ValueError("cutoff manifest envelope schema is unsupported")
    if envelope.get("manifest") != expected_manifest or envelope.get("manifest_sha256") != expected_manifest_sha256:
        raise ValueError("cutoff manifest changed or is crossed with the v1 prefix")
    if _sha256_json(envelope.get("manifest")) != expected_manifest_sha256:
        raise ValueError("cutoff manifest hash mismatch")
    identity_hash = _non_empty(expected_identity.get("identity_hash"), "continuation identity hash")
    dispatched, durable, wave_physical_attempts, _ = _replay_continuation_ledger(
        continuation / _LEDGER_FILE,
        expected_identity_hash=identity_hash,
    )
    status = _read_json_object(continuation / _STATUS_FILE)
    if status.get("schema_version") != _SEGMENTED_STATUS_SCHEMA:
        raise ValueError("continuation status schema is unsupported")
    if status.get("manifest_sha256") != expected_manifest_sha256:
        raise ValueError("continuation status is crossed with the cutoff manifest")
    authorization_raw = expected_manifest.get("reconciliation_authorization")
    migration_charge = (
        0
        if authorization_raw is None
        else _strict_non_negative_int(
            _mapping(authorization_raw, "reconciliation authorization").get("physical_attempt_charge"),
            "reconciliation physical charge",
        )
    )
    unretried_migration_unknown = len(prefix.unknown_pair_ids) if authorization_raw is None else 0
    if status.get("concurrent_suffix_terminal_count") != len(durable):
        raise ValueError("continuation status terminal count is crossed with its ledger")
    if status.get("logical_count") != (
        prefix.attempt_prefix.logical_count + unretried_migration_unknown + len(dispatched)
    ):
        raise ValueError("continuation logical count is crossed with dispatched reservations")
    if status.get("physical_attempt_count") != (
        prefix.attempt_prefix.physical_attempt_count + migration_charge + wave_physical_attempts
    ):
        raise ValueError("continuation physical count is crossed with wave accounting")
    if status.get("lifecycle") == SegmentedContinuationStatus.COMPLETE.value:
        rows_path = continuation / _TERMINAL_ROWS_FILE
        if _sha256_file(rows_path) != status.get("terminal_rows_sha256"):
            raise ValueError("segmented canonical terminal rows hash mismatch")
        rows = [json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines() if line]
        _validate_unique_terminal_rows(tuple(_mapping(row, "segmented terminal row") for row in rows))
        expected_row_count = _strict_non_negative_int(
            status.get("durable_prefix_terminal_count"),
            "prefix terminal count",
        ) + _strict_non_negative_int(
            status.get("concurrent_suffix_terminal_count"),
            "suffix terminal count",
        )
        if len(rows) != expected_row_count:
            raise ValueError("segmented canonical terminal denominator is crossed")
    elif status.get("lifecycle") == SegmentedContinuationStatus.RECONCILIATION_REQUIRED.value:
        unknown = _string_list(status.get("unknown_pair_ids"), "continuation unknown pairs")
        if dispatched and not set(unknown).issubset(set(dispatched) - set(durable)):
            raise ValueError("continuation unknown status is crossed with durable suffix evidence")
    else:
        raise ValueError("incomplete continuation is reconciliation-required and cannot be resumed automatically")
    _assert_prefix_unchanged(prefix)
    return _result_from_status(continuation, status)


def _persist_reconciliation_result(
    *,
    continuation: Path,
    manifest_sha256: str,
    prefix: _FrozenPrefix,
    suffix_terminal_count: int,
    unknown_pair_ids: Sequence[str],
    logical_count: int,
    physical_attempt_count: int,
) -> SegmentedContinuationResult:
    status = {
        "schema_version": _SEGMENTED_STATUS_SCHEMA,
        "lifecycle": SegmentedContinuationStatus.RECONCILIATION_REQUIRED.value,
        "manifest_sha256": manifest_sha256,
        "durable_prefix_terminal_count": len(prefix.terminal_by_pair_id),
        "concurrent_suffix_terminal_count": suffix_terminal_count,
        "committed_feedback_user_ids": [],
        "unknown_pair_ids": list(unknown_pair_ids),
        "logical_count": logical_count,
        "physical_attempt_count": physical_attempt_count,
        "terminal_rows_relative_path": None,
        "terminal_rows_sha256": None,
        "production_deploy_eligible": False,
    }
    _atomic_write_json(continuation / _STATUS_FILE, status)
    _assert_prefix_unchanged(prefix)
    return _result_from_status(continuation, status)


def _result_from_status(continuation: Path, status: Mapping[str, object]) -> SegmentedContinuationResult:
    rows_relative = status.get("terminal_rows_relative_path")
    return SegmentedContinuationResult(
        status=SegmentedContinuationStatus(cast(str, status["lifecycle"])),
        workspace_root=continuation,
        manifest_sha256=cast(str, status["manifest_sha256"]),
        terminal_rows_path=(continuation / cast(str, rows_relative) if isinstance(rows_relative, str) else None),
        source_root=(
            continuation / cast(str, status["source_root_relative_path"])
            if isinstance(status.get("source_root_relative_path"), str)
            else None
        ),
        source_manifest_sha256=cast(str | None, status.get("source_manifest_sha256")),
        durable_prefix_terminal_count=_strict_non_negative_int(
            status.get("durable_prefix_terminal_count"), "prefix terminal count"
        ),
        concurrent_suffix_terminal_count=_strict_non_negative_int(
            status.get("concurrent_suffix_terminal_count"), "suffix terminal count"
        ),
        committed_feedback_user_ids=tuple(
            _string_list(status.get("committed_feedback_user_ids"), "committed feedback users")
        ),
        unknown_pair_ids=tuple(_string_list(status.get("unknown_pair_ids"), "unknown pair IDs")),
        logical_count=_strict_non_negative_int(status.get("logical_count"), "logical count"),
        physical_attempt_count=_strict_non_negative_int(
            status.get("physical_attempt_count"), "physical attempt count"
        ),
        production_deploy_eligible=False,
    )


def _replay_continuation_ledger(
    path: Path,
    *,
    expected_identity_hash: str,
) -> tuple[list[str], list[str], int, dict[str, object] | None]:
    sequence = 0
    previous_checksum: str | None = None
    dispatched: list[str] = []
    durable: list[str] = []
    accounted_pair_ids: set[str] = set()
    accounted_terminal_evidence: dict[str, int] = {}
    pending_wave_pair_ids: list[str] | None = None
    pending_wave_reservation = 0
    pending_wave_dispatch_count = 0
    physical_attempts = 0
    source_anchor: dict[str, object] | None = None
    if not path.is_file():
        raise FileNotFoundError(f"continuation ledger is missing: {path}")
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            raw = line.strip()
            if not raw:
                continue
            record = _mapping(json.loads(raw), f"continuation ledger line {line_number}")
            checksum = _non_empty(record.pop("checksum", None), "continuation ledger checksum")
            if record.get("schema_version") != _SEGMENTED_LEDGER_SCHEMA:
                raise ValueError("continuation ledger schema is unsupported")
            if record.get("continuation_identity_hash") != expected_identity_hash:
                raise ValueError("continuation ledger identity is crossed")
            if record.get("sequence") != sequence + 1 or record.get("previous_checksum") != previous_checksum:
                raise ValueError("continuation ledger sequence or checksum chain is broken")
            if _sha256_json(record) != checksum:
                raise ValueError("continuation ledger checksum mismatch")
            event_type = record.get("event_type")
            payload = _mapping(record.get("payload"), "continuation ledger payload")
            if event_type == "suffix_wave_reserved":
                if pending_wave_pair_ids is not None:
                    raise ValueError("continuation wave reservation lacks durable accounting")
                pending_wave_pair_ids = _string_list(payload.get("pair_ids"), "reserved wave pair IDs")
                if not pending_wave_pair_ids:
                    raise ValueError("continuation wave reservation is empty")
                pending_wave_reservation = _strict_non_negative_int(
                    payload.get("physical_reservation"), "wave physical reservation"
                )
                maximum_attempts = _strict_non_negative_int(
                    payload.get("maximum_attempts_per_dispatch"),
                    "wave maximum attempts per dispatch",
                )
                if pending_wave_reservation != len(pending_wave_pair_ids) * maximum_attempts:
                    raise ValueError("continuation wave reservation is crossed with its retry window")
                pending_wave_dispatch_count = 0
            elif event_type == "pair_dispatched":
                pair_id = _non_empty(payload.get("pair_id"), "dispatched pair_id")
                if pair_id in dispatched:
                    raise ValueError("duplicate continuation dispatch")
                if (
                    pending_wave_pair_ids is None
                    or pending_wave_dispatch_count >= len(pending_wave_pair_ids)
                    or pair_id != pending_wave_pair_ids[pending_wave_dispatch_count]
                ):
                    raise ValueError("continuation dispatch is crossed with its wave reservation")
                dispatched.append(pair_id)
                pending_wave_dispatch_count += 1
            elif event_type == "wave_accounting":
                pair_ids = _string_list(payload.get("pair_ids"), "accounted wave pair IDs")
                if pending_wave_pair_ids is None or pair_ids != pending_wave_pair_ids:
                    raise ValueError("continuation wave accounting is crossed with its reservation")
                lanes = _mapping_sequence(payload.get("lanes"), "wave lane accounting")
                if (
                    len(lanes) != len(pair_ids)
                    or pending_wave_dispatch_count != len(pair_ids)
                    or dispatched[-len(pair_ids) :] != pair_ids
                ):
                    raise ValueError("continuation wave accounting does not close every dispatch")
                lane_total = 0
                for lane_id, (pair_id, lane) in enumerate(zip(pair_ids, lanes, strict=True)):
                    if lane.get("lane_id") != lane_id or lane.get("pair_id") != pair_id:
                        raise ValueError("continuation wave lane accounting is not canonical")
                    request_delta = _strict_non_negative_int(
                        lane.get("request_invocations_delta"), "wave request delta"
                    )
                    external_delta = _strict_non_negative_int(
                        lane.get("external_request_invocations_delta"), "wave external request delta"
                    )
                    evidence_delta = _strict_non_negative_int(
                        lane.get("terminal_evidence_request_invocations"), "wave terminal evidence delta"
                    )
                    actual = _strict_non_negative_int(
                        lane.get("actual_physical_attempts"), "wave actual physical attempts"
                    )
                    if actual != max(request_delta, external_delta, evidence_delta):
                        raise ValueError("continuation wave lane accounting invariant failed")
                    accounted_terminal_evidence[pair_id] = evidence_delta
                    lane_total += actual
                declared_total = _strict_non_negative_int(
                    payload.get("actual_physical_attempts"), "wave actual physical total"
                )
                if lane_total != declared_total:
                    raise ValueError("continuation wave accounting total is crossed with its lanes")
                physical_attempts += declared_total
                accounted_pair_ids.update(pair_ids)
                pending_wave_pair_ids = None
                pending_wave_reservation = 0
                pending_wave_dispatch_count = 0
            elif event_type == "pair_terminal":
                pair_id = _non_empty(payload.get("pair_id"), "terminal pair_id")
                if pair_id not in dispatched or pair_id in durable:
                    raise ValueError("duplicate or undispatched continuation terminal")
                if pair_id not in accounted_pair_ids:
                    raise ValueError("continuation terminal precedes durable wave accounting")
                if dispatched[len(durable)] != pair_id:
                    raise ValueError("continuation terminal order is not canonical")
                evidence = _mapping(payload.get("variant_evidence"), "continuation variant evidence")
                if _strict_non_negative_int(
                    evidence.get("request_invocations"),
                    "continuation terminal request invocations",
                ) != accounted_terminal_evidence[pair_id]:
                    raise ValueError("continuation terminal evidence is crossed with wave accounting")
                durable.append(pair_id)
            elif event_type == "source_v2_prepared":
                if source_anchor is not None:
                    raise ValueError("continuation source-v2 anchor is duplicated")
                source_manifest_sha256 = _non_empty(
                    payload.get("source_manifest_sha256"), "source-v2 anchor manifest hash"
                )
                if _SHA256_PATTERN.fullmatch(source_manifest_sha256) is None:
                    raise ValueError("source-v2 anchor manifest hash is invalid")
                source_anchor = {
                    "source_manifest_sha256": source_manifest_sha256,
                    "complete_status": dict(
                        _mapping(payload.get("complete_status"), "source-v2 anchored complete status")
                    ),
                }
            elif event_type not in {
                "continuation_started",
                "batch_committed",
            } and not (isinstance(event_type, str) and event_type.startswith("kernel_")):
                raise ValueError("continuation ledger event type is unsupported")
            sequence += 1
            previous_checksum = checksum
    if pending_wave_pair_ids is not None:
        raise ValueError("continuation wave reservation lacks durable accounting")
    return dispatched, durable, physical_attempts, source_anchor


def _segmented_terminal_row(
    row: Mapping[str, object],
    *,
    segment: Literal["serial_prefix", "concurrent_suffix"],
    reconciliation_retry: bool,
) -> dict[str, object]:
    return {
        **dict(safe_data(row)),
        "execution_segment": segment,
        "reconciliation_retry": reconciliation_retry,
    }


def _validate_unique_terminal_rows(rows: Sequence[Mapping[str, object]]) -> None:
    pair_ids: set[str] = set()
    terminal_ids: set[str] = set()
    for row in rows:
        pair_id = _non_empty(row.get("pair_id"), "terminal pair_id")
        terminal_id = _non_empty(row.get("terminal_row_id"), "terminal_row_id")
        if pair_id in pair_ids or terminal_id in terminal_ids:
            raise ValueError("duplicate terminal identity")
        if row.get("decision_variant") != "primary":
            raise ValueError("segmented continuation accepts Primary terminals only")
        pair_ids.add(pair_id)
        terminal_ids.add(terminal_id)


def _assert_prefix_unchanged(prefix: _FrozenPrefix) -> None:
    current = _artifact_inventory(prefix.workspace)
    expected = {cast(str, ref["relative_path"]): ref for ref in prefix.accepted_artifacts}
    if current != expected:
        raise ValueError("read-only v1 prefix changed after cutoff freeze")


_SEGMENTED_SOURCE_SCHEMA = "full-pool-segmented-source-v2"
_SEGMENTED_COMPLETE_CUTOFF_SCHEMA = "full-pool-segmented-complete-cutoff-manifest-v2"
_SEGMENTED_SOURCE_ARTIFACTS = (
    "candidate_rows.jsonl",
    "pair_rows.jsonl",
    "terminal_rows.jsonl",
    "steps.jsonl",
)
_FORMAL_RUN_CONTRACT_FILE = "full_pool_run_contract.json"
_FORMAL_EXECUTION_CONTRACT_FILE = "formal_execution_contract.json"
_SEGMENTED_CANDIDATE_FIELDS = frozenset(
    {
        "base_network_relevance",
        "base_network_relevance_full_precision",
        "campaign_engaged_neighbor_count",
        "campaign_engaged_neighbor_signal",
        "campaign_engaged_neighbor_signal_full_precision",
        "historical_tag_affinity",
        "is_seed",
        "message_id",
        "normalized_message_user_fit",
        "normalized_message_user_fit_full_precision",
        "personalized_delivery_score",
        "personalized_delivery_score_full_precision",
        "ranking_position",
        "raw_message_user_fit",
        "raw_message_user_fit_full_precision",
        "selected",
        "selection_reason",
        "time_step",
        "user_id",
    }
)
_SEGMENTED_PAIR_FIELDS = frozenset(
    {
        "base_network_relevance",
        "base_network_relevance_full_precision",
        "campaign_engaged_neighbor_count",
        "campaign_engaged_neighbor_signal",
        "campaign_engaged_neighbor_signal_full_precision",
        "campaign_feedback_committed",
        "execution_segment",
        "historical_tag_affinity",
        "is_seed",
        "message_id",
        "message_title",
        "normalized_message_user_fit",
        "normalized_message_user_fit_full_precision",
        "pair_id",
        "pair_schedule_position",
        "personalized_delivery_score",
        "personalized_delivery_score_full_precision",
        "primary_action",
        "primary_confidence",
        "primary_decision_source",
        "primary_probability",
        "primary_prompt_version",
        "primary_provider_metadata",
        "primary_reason",
        "primary_status",
        "primary_terminal_coverage",
        "ranking_position",
        "raw_message_user_fit",
        "raw_message_user_fit_full_precision",
        "selection_reason",
        "time_step",
        "user_id",
    }
)
_SEGMENTED_TERMINAL_FIELDS = frozenset(
    {
        "action",
        "cache_key",
        "cached_input_usage",
        "confidence",
        "context_profile_payload",
        "context_source_key",
        "decision_source",
        "decision_variant",
        "engage",
        "execution_segment",
        "failure_type",
        "input_usage",
        "message_id",
        "observed_model_counts",
        "observed_model_malformed_response_count",
        "observed_model_missing_response_count",
        "output_usage",
        "pair_id",
        "pair_schedule_position",
        "peer_context_payload",
        "probability",
        "prompt_field_inclusion",
        "prompt_version",
        "provider_metadata",
        "provider_response_count",
        "provider_status",
        "reason",
        "reconciliation_retry",
        "request_invocations",
        "successful_decision_count",
        "terminal_row_id",
        "terminal_status",
        "time_step",
        "total_usage",
        "usage_complete",
        "usage_complete_response_count",
        "usage_malformed_response_count",
        "usage_missing_response_count",
        "user_id",
    }
)
_SEGMENTED_STEP_FIELDS = frozenset(
    {
        "committed_primary_positive_user_ids",
        "frozen_campaign_engaged_user_ids",
        "message_summaries",
        "time_step",
    }
)
_SEGMENTED_MESSAGE_SUMMARY_FIELDS = frozenset(
    {
        "below_delivery_capacity",
        "eligible_users",
        "message_id",
        "message_title",
        "personalized_topup_user_ids",
        "primary_positive_user_ids",
        "primary_provider_failed_user_ids",
        "ranked_candidates",
        "seed_user_ids",
        "selected_user_ids",
        "selection_reason_counts",
        "shadow_provider_failed_user_ids",
    }
)
_CANDIDATE_PAIR_SHARED_FIELDS = frozenset(
    _SEGMENTED_CANDIDATE_FIELDS
    - {"selected"}
)
_FORBIDDEN_SOURCE_KEY_FRAGMENTS = (
    "access_token",
    "api_key_value",
    "authorization_header",
    "cookie",
    "oauth_token",
    "raw_prompt",
    "raw_response",
    "raw_provider_payload",
)
_SEGMENTED_SOURCE_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "counts",
        "logical_count",
        "physical_attempt_count",
        "accounting",
        "artifacts",
        "complete_status",
        "cutoff_manifest_sha256",
        "continuation_identity_hash",
        "prefix_identity_hash",
        "max_concurrency",
        "production_deploy_eligible",
    }
)
_SEGMENTED_ACCOUNTING_FIELDS = frozenset(
    {
        "invocations",
        "responses",
        "successful_decisions",
        "observed_model_counts",
        "observed_model_missing_response_count",
        "observed_model_malformed_response_count",
        "usage_complete_attempts",
        "usage_incomplete_attempts",
        "usage_complete_response_count",
        "usage_missing_response_count",
        "usage_malformed_response_count",
        "input_usage",
        "output_usage",
        "total_usage",
        "cached_input_usage",
        "migration_unknown_physical_charge",
    }
)
_SEGMENTED_COUNT_FIELDS = frozenset(
    {"candidate_rows", "pair_rows", "terminal_rows", "steps"}
)
_SEGMENTED_COMPLETE_STATUS_FIELDS = frozenset(
    {
        "durable_prefix_terminal_count",
        "concurrent_suffix_terminal_count",
        "committed_feedback_user_ids",
        "unknown_pair_ids",
        "logical_count",
        "physical_attempt_count",
        "terminal_rows_relative_path",
        "terminal_rows_sha256",
        "source_root_relative_path",
        "production_deploy_eligible",
    }
)
_SEGMENTED_CUTOFF_FIELDS = frozenset(
    {
        "schema_version",
        "continuation_id",
        "v1_contract_identity",
        "v1_run_identity",
        "accepted_journal_prefix",
        "accepted_attempt_ledger_prefix",
        "accepted_artifacts",
        "committed_batches",
        "active_batch",
        "ordered_prefix_pair_ids",
        "ordered_prefix_terminal_ids",
        "prefix_accounting",
        "unknown_count",
        "unknown_pair_ids",
        "reconciliation_authorization",
        "reconciliation_authorization_sha256",
        "dataset",
        "expected_horizon",
        "expected_logical_count",
        "remaining_logical_count",
        "max_concurrency",
        "logical_cap",
        "physical_cap",
        "physical_reservation_policy",
        "production_deploy_eligible",
    }
)
_SEGMENTED_IDENTITY_FIELDS = frozenset(
    {
        "schema_version",
        "continuation_id",
        "workspace",
        "prefix_run_id",
        "prefix_identity_hash",
        "cutoff_manifest_sha256",
        "max_concurrency",
        "logical_cap",
        "physical_cap",
        "provider_contract",
        "prompt_contract",
        "production_deploy_eligible",
        "run_id",
        "identity_hash",
    }
)


@dataclass(frozen=True)
class SegmentedFullPoolSourceFacts:
    """Typed source-v2 facts consumed by Report, Evidence, and v9 Release."""

    source_root: Path
    workspace_root: Path
    source_schema_version: str
    source_identity: str
    source_manifest_sha256: str
    source_hash: str
    cutoff_manifest_sha256: str
    continuation_identity_hash: str
    prefix_identity_hash: str
    contract_sha256: str
    formal_execution_contract_sha256: str | None
    authorization_artifact_sha256: str | None
    qualification_artifact_sha256: str | None
    observed_model_evidence_sha256: str | None
    prompt_variant_id: str
    prompt_version: str
    prompt_canonical_hash: str
    configuration_profile: str
    evidence_profile: str
    provider_transport: str
    adapter_identity: str
    requested_model: str
    qualified_observed_model: str
    distinct_users: int
    eligible_pairs: int
    exposures: int
    primary_terminals: int
    committed_batches: int
    candidate_ranking_rows: int
    provider_failed_terminals: int
    serial_prefix_terminal_count: int
    concurrent_suffix_terminal_count: int
    max_concurrency: int
    logical_judgments: int
    physical_attempts: int
    physical_attempt_cap: int
    provider_responses: int
    successful_decisions: int
    external_request_invocations: int
    observed_model_counts: Mapping[str, int]
    usage_complete_response_count: int
    usage_missing_response_count: int
    usage_malformed_response_count: int
    migration_unknown_physical_charge: int
    unknown_pair_count: int
    reconciliation_retry_count: int
    artifact_hashes: Mapping[str, str]
    live_api_triggered: bool
    production_deploy_eligible: bool


@dataclass(frozen=True)
class _SegmentedFormalLineage:
    contract: FullPoolExperimentContract
    contract_sha256: str
    execution_contract_sha256: str
    authorization_artifact_sha256: str
    qualification_artifact_sha256: str
    observed_model_evidence_sha256: str
    prompt_variant_id: str
    prompt_version: str
    prompt_canonical_hash: str


@dataclass(frozen=True)
class _SegmentedExecutionView:
    requested_model: str
    required_observed_model: str
    transport: str
    adapter_identity: str
    physical_attempt_cap: int


@dataclass(frozen=True)
class _SegmentedContractView:
    schema_version: str
    message_ids: tuple[str, str, str]
    horizon: int
    eligible_user_count: int
    per_message_capacity: int
    expected_primary_terminals: int
    expected_final_batch_pairs_per_message: int
    formal_execution: _SegmentedExecutionView | None


@dataclass(frozen=True)
class _JsonlBatchRange:
    start: int
    end: int
    row_count: int


@dataclass(frozen=True)
class _SegmentedBatchSlice:
    time_step: int
    candidate: _JsonlBatchRange
    pair: _JsonlBatchRange
    terminal: _JsonlBatchRange
    step: Mapping[str, object]


@dataclass(frozen=True)
class _SegmentedCandidateScan:
    ranges: tuple[_JsonlBatchRange, ...]
    row_count: int
    selected_rows: Mapping[tuple[str, str, int], Mapping[str, object]]
    summary_by_batch_message: Mapping[tuple[int, str], Mapping[str, object]]


@dataclass(frozen=True)
class _SegmentedPairTerminalScan:
    pair_ranges: tuple[_JsonlBatchRange, ...]
    terminal_ranges: tuple[_JsonlBatchRange, ...]
    pair_count: int
    terminal_count: int
    distinct_users: frozenset[str]
    coverage: Mapping[str, int]
    provider_failed: int
    serial_count: int
    suffix_count: int
    retry_pair_ids: tuple[str, ...]
    accounting: Mapping[str, object]
    positive_users_by_batch: tuple[frozenset[str], ...]
    ordered_pair_ids: tuple[str, ...]
    ordered_terminal_ids: tuple[str, ...]
    pair_ids_by_batch: tuple[tuple[str, ...], ...]
    terminal_ids_by_batch: tuple[tuple[str, ...], ...]
    selected_users_by_batch_message: Mapping[tuple[int, str], tuple[str, ...]]
    failed_users_by_batch_message: Mapping[tuple[int, str], tuple[str, ...]]
    positive_users_by_batch_message: Mapping[tuple[int, str], tuple[str, ...]]


@dataclass(frozen=True)
class _ClosedSegmentedFullPoolSource:
    """Read-only source-v2 Adapter for the existing Report source Seam."""

    root: Path
    contract: _SegmentedContractView
    source_identity: str
    manifest_sha256: str
    manifest: Mapping[str, object]
    aggregates: Mapping[str, object]
    diagnostics: Mapping[str, object]
    batch_paths: tuple[_SegmentedBatchSlice, ...]
    facts: SegmentedFullPoolSourceFacts

    def read_batch(self, time_step: int) -> Mapping[str, object]:
        if time_step < 0 or time_step >= len(self.batch_paths):
            raise IndexError("segmented Full-Pool batch index is outside the closed source")
        batch = self.batch_paths[time_step]
        if batch.time_step != time_step:
            raise ValueError("segmented Full-Pool batch order is crossed")
        return {
            "time_step": time_step,
            "commit": dict(batch.step),
            "rows": {
                "candidate_rows": _read_jsonl_range(
                    self.root / "candidate_rows.jsonl", batch.candidate
                ),
                "pair_rows": _read_jsonl_range(self.root / "pair_rows.jsonl", batch.pair),
                "terminal_rows": _read_jsonl_range(
                    self.root / "terminal_rows.jsonl", batch.terminal
                ),
            },
        }


def _read_closed_full_pool_source_versioned(
    source_root: str | Path,
    *,
    manifest_sha256: str,
) -> _ClosedFullPoolSource | _ClosedSegmentedFullPoolSource:
    """Dispatch exact source-v1/v2 readers without widening either source contract."""
    source = Path(source_root).expanduser()
    try:
        schema_version = _read_json_object(source / "manifest.json").get("schema_version")
    except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError):
        schema_version = None
    if schema_version == _SEGMENTED_SOURCE_SCHEMA:
        return _read_closed_segmented_full_pool_source(
            source,
            manifest_sha256=manifest_sha256,
        )
    return _read_closed_full_pool_source(source, manifest_sha256=manifest_sha256)


def _read_segmented_formal_lineage(
    *,
    run_identity: Mapping[str, object],
    formal_identity: Mapping[str, object],
) -> _SegmentedFormalLineage | None:
    runtime_contract = _mapping(
        run_identity.get("execution_contract"), "segmented runtime execution contract"
    )
    formal_runtime_raw = runtime_contract.get("formal_execution")
    if not isinstance(formal_runtime_raw, Mapping):
        return None
    formal_runtime = _mapping(formal_runtime_raw, "segmented runtime Formal contract")
    qualification_safe = _mapping(
        formal_runtime.get("qualification"), "segmented runtime qualification"
    )
    qualification_path_raw = qualification_safe.get("artifact_path")
    if not isinstance(qualification_path_raw, str) or not qualification_path_raw:
        return None
    qualification_path = Path(qualification_path_raw).expanduser()
    contract_path = qualification_path.parent / _FORMAL_RUN_CONTRACT_FILE
    execution_path = qualification_path.parent / _FORMAL_EXECUTION_CONTRACT_FILE
    if not contract_path.is_file() or not execution_path.is_file():
        return None
    _require_real_file(contract_path, "segmented Full-Pool Formal contract")
    _require_real_file(execution_path, "segmented Formal execution contract")
    contract_document = _read_json_object(contract_path)
    try:
        contract = FullPoolExperimentContract.model_validate(contract_document, strict=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("segmented Full-Pool Formal contract is invalid") from exc
    if safe_data(contract.model_dump(mode="json")) != runtime_contract:
        raise ValueError("segmented runtime identity is crossed with the persisted Formal contract")
    contract_hash = _sha256_json(contract.model_dump(mode="json"))
    execution = contract.formal_execution
    if execution is None:
        raise ValueError("segmented persisted contract omits Formal execution evidence")
    execution_document = execution.model_dump(mode="json")
    execution_hash = _sha256_json(execution_document)
    if (
        contract_hash != formal_identity.get("contract_sha256")
        or execution_hash != formal_identity.get("execution_contract_sha256")
        or _read_json_object(execution_path) != execution_document
    ):
        raise ValueError("segmented Formal contract or execution identity is crossed")

    authorization = execution.authorization
    qualification = execution.qualification
    artifact_paths = (
        authorization.artifact_path,
        qualification.artifact_path,
        qualification.observed_response_artifact_path,
    )
    for path, label in zip(
        artifact_paths,
        (
            "segmented authorization artifact",
            "segmented qualification artifact",
            "segmented observed-model artifact",
        ),
        strict=True,
    ):
        _require_real_file(path, label)
    if (
        _sha256_file(authorization.artifact_path) != authorization.artifact_sha256
        or _sha256_file(qualification.artifact_path) != qualification.artifact_sha256
        or _sha256_file(qualification.observed_response_artifact_path)
        != qualification.observed_response_sha256
        or authorization.artifact_sha256
        != formal_identity.get("authorization_artifact_sha256")
        or qualification.artifact_sha256
        != formal_identity.get("qualification_artifact_sha256")
    ):
        raise ValueError("segmented Formal authorization artifact hashes are crossed")
    authorization_document = authorization.model_dump(mode="json")
    for field in ("artifact_path", "artifact_sha256"):
        authorization_document.pop(field)
    if _read_json_object(authorization.artifact_path) != authorization_document:
        raise ValueError("segmented Formal authorization artifact content is crossed")
    qualification_document = qualification.model_dump(mode="json")
    for field in ("artifact_path", "artifact_sha256", "observed_response_artifact_path"):
        qualification_document.pop(field)
    if _read_json_object(qualification.artifact_path) != qualification_document:
        raise ValueError("segmented Formal qualification artifact content is crossed")
    observed_document = _read_json_object(qualification.observed_response_artifact_path)
    expected_observed = {
        "schema_version": "full-pool-formal-observed-model-evidence-v1",
        "evidence_kind": qualification.qualification_kind,
        "output_identity": contract.output_identity,
        "provider": execution.provider,
        "transport": execution.transport,
        "adapter_identity": execution.adapter_identity,
        "requested_model": execution.requested_model,
        "observed_model": execution.required_observed_model,
        "account_binding": qualification.account_binding,
        "qualified_at_utc": qualification.qualified_at_utc,
        "usage_complete": True,
        "raw_provider_payload_persisted": False,
    }
    if observed_document != expected_observed:
        raise ValueError("segmented observed-model qualification evidence is crossed")

    prompt = CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.resolve(
        CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION
    )
    prompt_document = _mapping(
        json.loads(_canonical_json(prompt.audit_record())),
        "canonical P0 Prompt audit",
    )
    prompt_contract = _mapping(run_identity.get("prompt_contract"), "segmented prompt contract")
    if (
        prompt_contract != {"primary": prompt_document}
        or execution.prompt_version != prompt.prompt_version
        or execution.prompt_canonical_hash != prompt.canonical_hash
        or prompt_document.get("variant_id") != "P0"
    ):
        raise ValueError("segmented Formal source does not close canonical P0 Prompt evidence")
    provider_by_variant = _mapping(
        run_identity.get("provider_contract"), "segmented provider contract"
    )
    provider = _mapping(provider_by_variant.get("primary"), "segmented Primary provider contract")
    external_transport = _mapping(
        provider.get("external_transport"), "segmented external transport"
    )
    request_contract = execution.request_contract.model_dump(mode="json")
    if (
        provider.get("provider") != execution.provider
        or provider.get("model") != execution.requested_model
        or provider.get("requested_model") != execution.requested_model
        or provider.get("prompt_version") != execution.prompt_version
        or provider.get("wire_api") != execution.request_contract.wire_api
        or provider.get("reasoning_effort") != execution.request_contract.reasoning_effort
        or provider.get("max_output_tokens") != execution.request_contract.output_token_ceiling
        or provider.get("timeout_seconds") != execution.request_contract.timeout_seconds
        or provider.get("max_retries") != execution.request_contract.max_retries
        or provider.get("request_contract") != request_contract
        or external_transport.get("adapter_identity") != execution.adapter_identity
        or external_transport.get("provider_transport") != execution.transport
    ):
        raise ValueError("segmented Formal Provider/request contract is crossed")
    return _SegmentedFormalLineage(
        contract=contract,
        contract_sha256=contract_hash,
        execution_contract_sha256=execution_hash,
        authorization_artifact_sha256=authorization.artifact_sha256,
        qualification_artifact_sha256=qualification.artifact_sha256,
        observed_model_evidence_sha256=qualification.observed_response_sha256,
        prompt_variant_id="P0",
        prompt_version=prompt.prompt_version,
        prompt_canonical_hash=prompt.canonical_hash,
    )


def _read_closed_segmented_full_pool_source(
    source_root: str | Path,
    *,
    manifest_sha256: str,
) -> _ClosedSegmentedFullPoolSource:
    """Close one explicit source-v2 and its sibling cutoff/identity lineage."""
    source = Path(source_root).expanduser()
    if ".." in source.parts or _SHA256_PATTERN.fullmatch(manifest_sha256) is None:
        raise ValueError("segmented source-v2 path or explicit manifest hash is invalid")
    absolute = Path(os.path.abspath(source))
    resolved = source.resolve(strict=True)
    if absolute != resolved or source.is_symlink():
        raise ValueError("segmented source-v2 must be one explicit real directory")
    _require_real_directory(resolved, "segmented source-v2")
    workspace = resolved.parent
    _require_real_directory(workspace, "segmented continuation workspace")
    manifest_path = resolved / "manifest.json"
    if _sha256_file(manifest_path) != manifest_sha256:
        raise ValueError("segmented source-v2 manifest differs from the explicit hash")
    manifest = _read_json_object(manifest_path)
    if (
        set(manifest) != _SEGMENTED_SOURCE_MANIFEST_FIELDS
        or manifest.get("schema_version") != _SEGMENTED_SOURCE_SCHEMA
        or manifest.get("max_concurrency") != FULL_POOL_SEGMENTED_MAX_CONCURRENCY
        or manifest.get("production_deploy_eligible") is not False
    ):
        raise ValueError("segmented source-v2 manifest fields are missing, extra, or unsupported")

    artifact_hashes = _validate_segmented_artifacts(resolved, manifest)
    cutoff, cutoff_hash = _read_segmented_cutoff(workspace)
    identity = _read_segmented_identity(workspace, cutoff_hash=cutoff_hash)
    if (
        manifest.get("cutoff_manifest_sha256") != cutoff_hash
        or manifest.get("continuation_identity_hash") != identity.get("identity_hash")
        or manifest.get("prefix_identity_hash") != identity.get("prefix_identity_hash")
        or cutoff.get("continuation_id") != identity.get("continuation_id")
        or _mapping(cutoff.get("v1_run_identity"), "segmented v1 run identity").get(
            "identity_hash"
        )
        != identity.get("prefix_identity_hash")
    ):
        raise ValueError("segmented source-v2 cutoff or continuation identity is crossed")

    run_identity = _mapping(cutoff.get("v1_run_identity"), "segmented v1 run identity")
    formal_identity = _mapping(
        cutoff.get("v1_contract_identity"), "segmented v1 contract identity"
    )
    if formal_identity.get("schema_version") != _FULL_POOL_IDENTITY_SCHEMA:
        raise ValueError("segmented v1 Formal identity schema is unsupported")
    run_provider_by_variant = _mapping(
        run_identity.get("provider_contract"), "segmented run Provider contract"
    )
    run_prompt_by_variant = _mapping(
        run_identity.get("prompt_contract"), "segmented run Prompt contract"
    )
    if (
        identity.get("provider_contract") != run_provider_by_variant.get("primary")
        or identity.get("prompt_contract") != run_prompt_by_variant.get("primary")
    ):
        raise ValueError("segmented continuation Provider or Prompt identity is crossed")
    formal_lineage = _read_segmented_formal_lineage(
        run_identity=run_identity,
        formal_identity=formal_identity,
    )
    configuration = _mapping(run_identity.get("configuration"), "segmented v1 configuration")
    messages = _mapping_sequence(run_identity.get("messages"), "segmented v1 messages")
    message_ids = tuple(_non_empty(row.get("message_id"), "segmented message_id") for row in messages)
    message_titles = {
        _non_empty(row.get("message_id"), "segmented message_id"): _non_empty(
            row.get("title"), "segmented message title"
        )
        for row in messages
    }
    if message_ids != FULL_POOL_MESSAGE_IDS or len(message_titles) != len(FULL_POOL_MESSAGE_IDS):
        raise ValueError("segmented source-v2 authoritative message topology is crossed")
    sample_size = _strict_non_negative_int(configuration.get("sample_size"), "segmented sample size")
    horizon = _strict_non_negative_int(configuration.get("horizon"), "segmented horizon")
    capacity = _strict_non_negative_int(
        configuration.get("delivery_capacity"), "segmented delivery capacity"
    )
    runtime_execution = _mapping(
        run_identity.get("execution_contract"), "segmented runtime execution contract"
    )
    formal_runtime_raw = runtime_execution.get("formal_execution")
    effective_execution = (
        _mapping(formal_runtime_raw, "segmented runtime Formal execution")
        if isinstance(formal_runtime_raw, Mapping)
        else runtime_execution
    )
    request_contract = _mapping(
        effective_execution.get("request_contract"), "segmented request contract"
    )
    maximum_attempts = (
        _strict_non_negative_int(request_contract.get("max_retries"), "segmented max retries")
        + 1
    )
    prompt_primary = _mapping(
        _mapping(run_identity.get("prompt_contract"), "segmented prompt contract").get(
            "primary"
        ),
        "segmented Primary prompt contract",
    )
    prompt_variant_id = _non_empty(
        prompt_primary.get("variant_id"), "segmented Prompt variant"
    )
    prompt_version = _non_empty(
        prompt_primary.get("prompt_version"), "segmented Prompt version"
    )
    prompt_canonical_hash = _non_empty(
        prompt_primary.get("canonical_hash"), "segmented Prompt canonical hash"
    )
    if formal_lineage is not None:
        contract = formal_lineage.contract
        execution = contract.formal_execution
        if execution is None:
            raise ValueError("segmented Formal lineage omits execution evidence")
        expected_runtime = {
            "sample_size": contract.eligible_user_count,
            "horizon": contract.horizon,
            "delivery_capacity": contract.per_message_capacity,
            "primary_prompt_version": execution.prompt_version,
        }
        sample_fingerprints = _mapping(
            run_identity.get("sample_data_fingerprints"),
            "segmented sample data fingerprints",
        )
        if (
            any(configuration.get(key) != value for key, value in expected_runtime.items())
            or contract.message_ids != message_ids
            or contract.dataset_dir.as_posix() != configuration.get("dataset_dir")
            or sample_fingerprints.get("message_snapshot_hash")
            != contract.message_snapshot_sha256
        ):
            raise ValueError("segmented runtime schedule or dataset is crossed with Formal contract")
        profile = "production" if contract.profile == "production" else "validation"
        prompt_variant_id = formal_lineage.prompt_variant_id
        prompt_version = formal_lineage.prompt_version
        prompt_canonical_hash = formal_lineage.prompt_canonical_hash
    else:
        profile = "validation"
    if horizon < 2 or capacity < 1 or not capacity * (horizon - 1) < sample_size <= capacity * horizon:
        raise ValueError("segmented source-v2 schedule is invalid")
    expected_pairs = sample_size * len(message_ids)
    expected_candidates = len(message_ids) * (
        horizon * sample_size - capacity * horizon * (horizon - 1) // 2
    )
    final_capacity = sample_size - capacity * (horizon - 1)
    if cutoff.get("expected_horizon") != horizon or cutoff.get("expected_logical_count") != expected_pairs:
        raise ValueError("segmented source-v2 cutoff denominator is crossed")
    if (
        cutoff.get("logical_cap") != FULL_POOL_SEGMENTED_LOGICAL_CAP
        or cutoff.get("physical_cap") != FULL_POOL_SEGMENTED_PHYSICAL_CAP
        or cutoff.get("max_concurrency") != FULL_POOL_SEGMENTED_MAX_CONCURRENCY
        or cutoff.get("physical_reservation_policy") != "dynamic-next-wave-retry-window-v1"
        or cutoff.get("production_deploy_eligible") is not False
        or maximum_attempts != 3
    ):
        raise ValueError("segmented source-v2 cutoff caps, retry window, or policy are crossed")

    candidate_scan = _scan_segmented_candidates(
        resolved / "candidate_rows.jsonl",
        message_ids=message_ids,
        horizon=horizon,
        sample_size=sample_size,
        capacity=capacity,
    )
    pair_scan = _scan_segmented_pairs_and_terminals(
        resolved / "pair_rows.jsonl",
        resolved / "terminal_rows.jsonl",
        message_ids=message_ids,
        horizon=horizon,
        capacity=capacity,
        final_capacity=final_capacity,
        maximum_attempts=maximum_attempts,
        prompt_version=prompt_version,
        selected_rows=candidate_scan.selected_rows,
    )
    step_rows = _scan_segmented_steps(
        resolved / "steps.jsonl",
        horizon=horizon,
        message_ids=message_ids,
        message_titles=message_titles,
        candidate_summary=candidate_scan.summary_by_batch_message,
        pair_scan=pair_scan,
    )
    candidate_ranges = candidate_scan.ranges
    candidate_count = candidate_scan.row_count
    pair_ranges = pair_scan.pair_ranges
    terminal_ranges = pair_scan.terminal_ranges
    pair_count = pair_scan.pair_count
    terminal_count = pair_scan.terminal_count
    distinct_users = pair_scan.distinct_users
    coverage = pair_scan.coverage
    provider_failed = pair_scan.provider_failed
    serial_count = pair_scan.serial_count
    suffix_count = pair_scan.suffix_count
    reconciliation_retry_count = len(pair_scan.retry_pair_ids)
    terminal_accounting = pair_scan.accounting
    positive_users_by_batch = pair_scan.positive_users_by_batch
    _validate_segmented_cutoff_order(
        cutoff,
        pair_scan=pair_scan,
        step_rows=step_rows,
    )

    counts = _mapping(manifest.get("counts"), "segmented source-v2 counts")
    expected_counts = {
        "candidate_rows": expected_candidates,
        "pair_rows": expected_pairs,
        "terminal_rows": expected_pairs,
        "steps": horizon,
    }
    observed_counts = {
        "candidate_rows": candidate_count,
        "pair_rows": pair_count,
        "terminal_rows": terminal_count,
        "steps": len(step_rows),
    }
    if (
        set(counts) != _SEGMENTED_COUNT_FIELDS
        or counts != expected_counts
        or observed_counts != expected_counts
        or len(distinct_users) != sample_size
        or coverage != {user_id: len(message_ids) for user_id in distinct_users}
    ):
        raise ValueError("segmented source-v2 36,400/109,200/30/1,691,730 topology is incomplete")

    cutoff_prefix = _mapping(cutoff.get("prefix_accounting"), "segmented prefix accounting")
    prefix_logical = _strict_non_negative_int(
        cutoff_prefix.get("logical_count"), "segmented prefix logical count"
    )
    prefix_physical = _strict_non_negative_int(
        cutoff_prefix.get("physical_attempt_count"), "segmented prefix physical count"
    )
    pending_physical = _strict_non_negative_int(
        cutoff_prefix.get("pending_physical_count"), "segmented pending physical count"
    )
    serial_invocations = _strict_non_negative_int(
        terminal_accounting["serial_invocations"], "segmented serial invocations"
    )
    if (
        prefix_logical != serial_count
        or cutoff.get("remaining_logical_count") != expected_pairs - prefix_logical
        or prefix_physical != serial_invocations
    ):
        raise ValueError("segmented serial prefix accounting is crossed")
    migration_charge, unknown_count = _validate_segmented_reconciliation(
        cutoff,
        retry_pair_ids=pair_scan.retry_pair_ids,
        prefix_identity_hash=_non_empty(
            identity.get("prefix_identity_hash"), "segmented prefix identity hash"
        ),
        maximum_attempts=maximum_attempts,
    )
    if (unknown_count == 0 and pending_physical != 0) or (
        unknown_count == 1 and pending_physical > 3
    ):
        raise ValueError("segmented pending physical attempts are crossed with migration unknown")
    accounting = _mapping(manifest.get("accounting"), "segmented source-v2 accounting")
    if set(accounting) != _SEGMENTED_ACCOUNTING_FIELDS:
        raise ValueError("segmented source-v2 accounting fields are missing or extra")
    expected_accounting = {
        key: terminal_accounting[key]
        for key in _SEGMENTED_ACCOUNTING_FIELDS
        if key != "migration_unknown_physical_charge"
    }
    expected_accounting["migration_unknown_physical_charge"] = migration_charge
    if accounting != expected_accounting:
        raise ValueError("segmented source-v2 Provider/model/usage accounting is crossed")
    logical = _strict_non_negative_int(manifest.get("logical_count"), "segmented logical count")
    physical = _strict_non_negative_int(
        manifest.get("physical_attempt_count"), "segmented physical count"
    )
    accounted_invocations = _strict_non_negative_int(
        terminal_accounting["invocations"], "segmented accounted invocations"
    )
    if (
        logical != expected_pairs
        or physical != accounted_invocations + migration_charge
        or physical > FULL_POOL_SEGMENTED_PHYSICAL_CAP
    ):
        raise ValueError("segmented source-v2 logical or physical accounting is crossed")

    complete_status = _mapping(manifest.get("complete_status"), "segmented complete status")
    cumulative_feedback = sorted(
        {user_id for users in positive_users_by_batch for user_id in users}
    )
    expected_complete_status = {
        "durable_prefix_terminal_count": serial_count,
        "concurrent_suffix_terminal_count": suffix_count,
        "committed_feedback_user_ids": cumulative_feedback,
        "unknown_pair_ids": [],
        "logical_count": logical,
        "physical_attempt_count": physical,
        "terminal_rows_relative_path": "source-v2/terminal_rows.jsonl",
        "terminal_rows_sha256": artifact_hashes["terminal_rows.jsonl"],
        "source_root_relative_path": "source-v2",
        "production_deploy_eligible": False,
    }
    if set(complete_status) != _SEGMENTED_COMPLETE_STATUS_FIELDS or complete_status != expected_complete_status:
        raise ValueError("segmented source-v2 complete status is crossed")
    dispatched, durable, suffix_physical, source_anchor = _replay_continuation_ledger(
        workspace / _LEDGER_FILE,
        expected_identity_hash=_non_empty(
            identity.get("identity_hash"), "segmented continuation identity hash"
        ),
    )
    suffix_pair_ids = list(pair_scan.ordered_pair_ids[pair_scan.serial_count :])
    serial_physical = _strict_non_negative_int(
        terminal_accounting["serial_invocations"], "segmented serial physical attempts"
    )
    if (
        dispatched != suffix_pair_ids
        or durable != suffix_pair_ids
        or suffix_physical != accounted_invocations - serial_physical
        or source_anchor
        != {
            "source_manifest_sha256": manifest_sha256,
            "complete_status": complete_status,
        }
    ):
        raise ValueError("segmented continuation ledger is crossed with source-v2")
    continuation_status = _read_json_object(workspace / _STATUS_FILE)
    expected_status_fields = {
        "schema_version",
        "lifecycle",
        "manifest_sha256",
        "durable_prefix_terminal_count",
        "concurrent_suffix_terminal_count",
        "logical_count",
        "physical_attempt_count",
        "unknown_pair_ids",
        "committed_feedback_user_ids",
        "terminal_rows_relative_path",
        "terminal_rows_sha256",
        "source_root_relative_path",
        "source_manifest_sha256",
        "production_deploy_eligible",
    }
    if (
        set(continuation_status) != expected_status_fields
        or continuation_status.get("schema_version") != _SEGMENTED_STATUS_SCHEMA
        or continuation_status.get("lifecycle") != SegmentedContinuationStatus.COMPLETE.value
        or continuation_status.get("manifest_sha256") != cutoff_hash
        or continuation_status.get("source_manifest_sha256") != manifest_sha256
        or continuation_status.get("durable_prefix_terminal_count") != serial_count
        or continuation_status.get("concurrent_suffix_terminal_count") != suffix_count
        or continuation_status.get("logical_count") != logical
        or continuation_status.get("physical_attempt_count") != physical
        or continuation_status.get("unknown_pair_ids") != []
        or continuation_status.get("committed_feedback_user_ids") != cumulative_feedback
        or continuation_status.get("terminal_rows_sha256")
        != artifact_hashes["terminal_rows.jsonl"]
        or continuation_status.get("source_root_relative_path") != "source-v2"
        or continuation_status.get("terminal_rows_relative_path")
        != "source-v2/terminal_rows.jsonl"
        or continuation_status.get("production_deploy_eligible") is not False
    ):
        raise ValueError("segmented continuation status is crossed with source-v2")

    provider_by_variant = _mapping(run_identity.get("provider_contract"), "segmented provider contract")
    provider = _mapping(provider_by_variant.get("primary"), "segmented Primary provider contract")
    formal_execution = (
        formal_lineage.contract.formal_execution if formal_lineage is not None else None
    )
    live_api_triggered = bool(
        formal_lineage is not None
        and formal_lineage.contract.profile == "production"
        and formal_execution is not None
        and formal_execution.evidence_profile == "formal_live"
    )
    if formal_execution is not None:
        adapter_identity = formal_execution.adapter_identity
        requested_model = formal_execution.requested_model
        qualified_model = formal_execution.required_observed_model
        evidence_profile = formal_execution.evidence_profile
        transport = formal_execution.transport
    else:
        adapter_identity = _non_empty(provider.get("adapter"), "segmented adapter identity")
        requested_model = _non_empty(provider.get("model"), "segmented requested model")
        qualified_model = requested_model
        evidence_profile = "deterministic_validation_fixture"
        transport = "deterministic"
    if live_api_triggered:
        production_values = (
            sample_size == FULL_POOL_PRODUCTION_USER_COUNT,
            expected_pairs == FULL_POOL_PRODUCTION_ELIGIBLE_PAIRS,
            horizon == FULL_POOL_PRODUCTION_HORIZON,
            capacity == FULL_POOL_PRODUCTION_CAPACITY,
            final_capacity == FULL_POOL_PRODUCTION_FINAL_BATCH_PAIRS_PER_MESSAGE,
            expected_candidates == FULL_POOL_PRODUCTION_CANDIDATE_ROWS,
            adapter_identity == FULL_POOL_FORMAL_ADAPTER_IDENTITY,
            requested_model == FULL_POOL_FORMAL_REQUESTED_MODEL,
            qualified_model == FULL_POOL_FORMAL_REQUIRED_OBSERVED_MODEL,
            prompt_variant_id == "P0",
            terminal_accounting["observed_model_counts"]
            == {FULL_POOL_FORMAL_REQUIRED_OBSERVED_MODEL: expected_pairs},
            terminal_accounting["responses"] == expected_pairs,
            terminal_accounting["successful_decisions"] == expected_pairs,
            terminal_accounting["usage_complete_response_count"] == expected_pairs,
            terminal_accounting["usage_missing_response_count"] == 0,
            terminal_accounting["usage_malformed_response_count"] == 0,
            provider_failed == 0,
        )
        if not all(production_values):
            raise ValueError("segmented production source-v2 is incomplete, mock, or non-Formal")

    contract_sha256 = (
        formal_lineage.contract_sha256
        if formal_lineage is not None
        else _non_empty(
            formal_identity.get("contract_sha256"), "segmented v1 contract sha256"
        )
    )
    if _SHA256_PATTERN.fullmatch(contract_sha256) is None:
        raise ValueError("segmented v1 contract hash is invalid")
    source_hash = _sha256_json(dict(sorted(artifact_hashes.items())))
    external_requests = terminal_accounting["invocations"] if live_api_triggered else 0
    facts = SegmentedFullPoolSourceFacts(
        source_root=resolved,
        workspace_root=workspace,
        source_schema_version=_SEGMENTED_SOURCE_SCHEMA,
        source_identity=cast(str, identity["identity_hash"]),
        source_manifest_sha256=manifest_sha256,
        source_hash=source_hash,
        cutoff_manifest_sha256=cutoff_hash,
        continuation_identity_hash=cast(str, identity["identity_hash"]),
        prefix_identity_hash=cast(str, identity["prefix_identity_hash"]),
        contract_sha256=contract_sha256,
        formal_execution_contract_sha256=(
            formal_lineage.execution_contract_sha256 if formal_lineage is not None else None
        ),
        authorization_artifact_sha256=(
            formal_lineage.authorization_artifact_sha256 if formal_lineage is not None else None
        ),
        qualification_artifact_sha256=(
            formal_lineage.qualification_artifact_sha256 if formal_lineage is not None else None
        ),
        observed_model_evidence_sha256=(
            formal_lineage.observed_model_evidence_sha256 if formal_lineage is not None else None
        ),
        prompt_variant_id=prompt_variant_id,
        prompt_version=prompt_version,
        prompt_canonical_hash=prompt_canonical_hash,
        configuration_profile=profile,
        evidence_profile=evidence_profile,
        provider_transport=transport,
        adapter_identity=adapter_identity,
        requested_model=requested_model,
        qualified_observed_model=qualified_model,
        distinct_users=len(distinct_users),
        eligible_pairs=expected_pairs,
        exposures=expected_pairs,
        primary_terminals=expected_pairs,
        committed_batches=horizon,
        candidate_ranking_rows=expected_candidates,
        provider_failed_terminals=provider_failed,
        serial_prefix_terminal_count=serial_count,
        concurrent_suffix_terminal_count=suffix_count,
        max_concurrency=FULL_POOL_SEGMENTED_MAX_CONCURRENCY,
        logical_judgments=logical,
        physical_attempts=physical,
        physical_attempt_cap=FULL_POOL_SEGMENTED_PHYSICAL_CAP,
        provider_responses=cast(int, terminal_accounting["responses"]),
        successful_decisions=cast(int, terminal_accounting["successful_decisions"]),
        external_request_invocations=cast(int, external_requests),
        observed_model_counts=cast(Mapping[str, int], terminal_accounting["observed_model_counts"]),
        usage_complete_response_count=cast(
            int, terminal_accounting["usage_complete_response_count"]
        ),
        usage_missing_response_count=cast(
            int, terminal_accounting["usage_missing_response_count"]
        ),
        usage_malformed_response_count=cast(
            int, terminal_accounting["usage_malformed_response_count"]
        ),
        migration_unknown_physical_charge=migration_charge,
        unknown_pair_count=unknown_count,
        reconciliation_retry_count=reconciliation_retry_count,
        artifact_hashes=artifact_hashes,
        live_api_triggered=live_api_triggered,
        production_deploy_eligible=False,
    )
    facade_counts = {
        "candidate_ranking_rows": expected_candidates,
        "committed_batches": horizon,
        "distinct_users": len(distinct_users),
        "eligible_pairs": expected_pairs,
        "exposures": expected_pairs,
        "primary_terminals": expected_pairs,
        "provider_failed_terminals": provider_failed,
        "below_delivery_capacity_pairs": expected_candidates - expected_pairs,
    }
    facade_accounting = {
        "logical_judgments": logical,
        "physical_attempts": physical,
        "provider_responses": terminal_accounting["responses"],
        "successful_decisions": terminal_accounting["successful_decisions"],
        "external_request_invocations": external_requests,
        "observed_model_counts": terminal_accounting["observed_model_counts"],
        "observed_model_missing_response_count": terminal_accounting[
            "observed_model_missing_response_count"
        ],
        "observed_model_malformed_response_count": terminal_accounting[
            "observed_model_malformed_response_count"
        ],
        "usage_complete_attempts": terminal_accounting["usage_complete_attempts"],
        "usage_incomplete_attempts": terminal_accounting["usage_incomplete_attempts"],
        "usage_complete_response_count": terminal_accounting[
            "usage_complete_response_count"
        ],
        "usage_missing_response_count": terminal_accounting[
            "usage_missing_response_count"
        ],
        "usage_malformed_response_count": terminal_accounting[
            "usage_malformed_response_count"
        ],
        "input_usage": terminal_accounting["input_usage"],
        "output_usage": terminal_accounting["output_usage"],
        "total_usage": terminal_accounting["total_usage"],
        "cached_input_usage": terminal_accounting["cached_input_usage"],
        "subscription_billed_cost_usd": 0.0,
    }
    facade_manifest = {
        "schema_version": _SEGMENTED_SOURCE_SCHEMA,
        "source_schema_version": _SEGMENTED_SOURCE_SCHEMA,
        "source_identity": facts.source_identity,
        "contract_sha256": contract_sha256,
        "source_hash": source_hash,
        "profile": "production" if live_api_triggered else "deterministic_validation",
        "evidence_profile": evidence_profile,
        "counts": facade_counts,
        "provider_calls": external_requests,
        "physical_provider_attempts": physical,
        "live_api_triggered": live_api_triggered,
        "production_deploy_eligible": False,
        "segmented_execution": _segmented_execution_document(facts),
    }
    aggregates = {
        "schema_version": "full-pool-segmented-aggregates-view-v1",
        "source_identity": facts.source_identity,
        "evidence_profile": evidence_profile,
        "counts": facade_counts,
        "provider_accounting": facade_accounting,
        "production_deploy_eligible": False,
    }
    diagnostics = {
        "schema_version": "full-pool-segmented-diagnostics-view-v1",
        "source_identity": facts.source_identity,
        "schedule": {
            "per_message_capacity": capacity,
            "final_batch_pairs_per_message": final_capacity,
        },
        "segmented_execution": _segmented_execution_document(facts),
    }
    execution = _SegmentedExecutionView(
        requested_model=requested_model,
        required_observed_model=qualified_model,
        transport=transport,
        adapter_identity=adapter_identity,
        physical_attempt_cap=FULL_POOL_SEGMENTED_PHYSICAL_CAP,
    )
    contract = _SegmentedContractView(
        schema_version="full-pool-segmented-contract-view-v1",
        message_ids=cast(tuple[str, str, str], message_ids),
        horizon=horizon,
        eligible_user_count=sample_size,
        per_message_capacity=capacity,
        expected_primary_terminals=expected_pairs,
        expected_final_batch_pairs_per_message=final_capacity,
        formal_execution=execution,
    )
    batch_paths = tuple(
        _SegmentedBatchSlice(
            time_step=time_step,
            candidate=candidate_ranges[time_step],
            pair=pair_ranges[time_step],
            terminal=terminal_ranges[time_step],
            step=step_rows[time_step],
        )
        for time_step in range(horizon)
    )
    return _ClosedSegmentedFullPoolSource(
        root=resolved,
        contract=contract,
        source_identity=facts.source_identity,
        manifest_sha256=manifest_sha256,
        manifest=facade_manifest,
        aggregates=aggregates,
        diagnostics=diagnostics,
        batch_paths=batch_paths,
        facts=facts,
    )


def _validate_segmented_artifacts(
    source: Path,
    manifest: Mapping[str, object],
) -> dict[str, str]:
    refs = _mapping_sequence(manifest.get("artifacts"), "segmented source-v2 artifacts")
    by_path: dict[str, Mapping[str, object]] = {}
    for ref in refs:
        relative = _non_empty(ref.get("relative_path"), "segmented artifact path")
        if relative not in _SEGMENTED_SOURCE_ARTIFACTS or relative in by_path:
            raise ValueError("segmented source-v2 artifact inventory is not exact")
        path = source / relative
        if path.is_symlink() or not path.is_file() or _file_ref(source, path) != ref:
            raise ValueError("segmented source-v2 artifact hash or byte length is crossed")
        by_path[relative] = ref
    inventory = _artifact_inventory(source)
    if set(by_path) != set(_SEGMENTED_SOURCE_ARTIFACTS) or set(inventory) != {
        *_SEGMENTED_SOURCE_ARTIFACTS,
        "manifest.json",
    }:
        raise ValueError("segmented source-v2 contains missing, extra, or unsafe artifacts")
    return {name: cast(str, by_path[name]["sha256"]) for name in _SEGMENTED_SOURCE_ARTIFACTS}


def _read_segmented_cutoff(workspace: Path) -> tuple[dict[str, object], str]:
    envelope = _read_json_object(workspace / _MANIFEST_FILE)
    if set(envelope) != {"schema_version", "manifest", "manifest_sha256"}:
        raise ValueError("segmented cutoff envelope fields are not exact")
    if envelope.get("schema_version") != _SEGMENTED_MANIFEST_ENVELOPE_SCHEMA:
        raise ValueError("segmented cutoff envelope schema is unsupported")
    cutoff = _mapping(envelope.get("manifest"), "segmented cutoff manifest")
    cutoff_hash = _non_empty(envelope.get("manifest_sha256"), "segmented cutoff hash")
    if (
        _SHA256_PATTERN.fullmatch(cutoff_hash) is None
        or _sha256_json(cutoff) != cutoff_hash
        or set(cutoff) != _SEGMENTED_CUTOFF_FIELDS
        or cutoff.get("schema_version") != _SEGMENTED_COMPLETE_CUTOFF_SCHEMA
    ):
        raise ValueError("segmented cutoff manifest fields, schema, or hash are crossed")
    accepted = _mapping_sequence(cutoff.get("accepted_artifacts"), "segmented accepted artifacts")
    accepted_by_path: dict[str, Mapping[str, object]] = {}
    for ref in accepted:
        if set(ref) != {"relative_path", "byte_length", "sha256"}:
            raise ValueError("segmented accepted artifact fields are not exact")
        relative = _non_empty(ref.get("relative_path"), "segmented accepted artifact path")
        digest = _non_empty(ref.get("sha256"), "segmented accepted artifact sha256")
        _strict_non_negative_int(ref.get("byte_length"), "segmented accepted artifact bytes")
        if relative in accepted_by_path or _SHA256_PATTERN.fullmatch(digest) is None:
            raise ValueError("segmented accepted artifact inventory is crossed")
        accepted_by_path[relative] = ref
    for key in ("accepted_journal_prefix", "accepted_attempt_ledger_prefix"):
        ref = _mapping(cutoff.get(key), f"segmented {key}")
        relative = _non_empty(ref.get("relative_path"), f"segmented {key} path")
        if accepted_by_path.get(relative) != ref:
            raise ValueError("segmented cutoff accepted lineage refs are crossed")
    return cutoff, cutoff_hash


def _read_segmented_identity(
    workspace: Path,
    *,
    cutoff_hash: str,
) -> dict[str, object]:
    identity = _read_json_object(workspace / _IDENTITY_FILE)
    if (
        set(identity) != _SEGMENTED_IDENTITY_FIELDS
        or identity.get("schema_version") != _SEGMENTED_IDENTITY_SCHEMA
        or identity.get("cutoff_manifest_sha256") != cutoff_hash
        or identity.get("max_concurrency") != FULL_POOL_SEGMENTED_MAX_CONCURRENCY
        or identity.get("logical_cap") != FULL_POOL_SEGMENTED_LOGICAL_CAP
        or identity.get("physical_cap") != FULL_POOL_SEGMENTED_PHYSICAL_CAP
        or identity.get("production_deploy_eligible") is not False
    ):
        raise ValueError("segmented continuation identity fields or caps are crossed")
    body = {
        key: value
        for key, value in identity.items()
        if key not in {"run_id", "identity_hash"}
    }
    expected_hash = _sha256_json(body)
    if (
        identity.get("identity_hash") != expected_hash
        or identity.get("run_id") != f"full-pool-segmented-{expected_hash[:16]}"
        or identity.get("workspace") != str(workspace)
    ):
        raise ValueError("segmented continuation identity hash or workspace is crossed")
    return identity


def _record_batch_range(
    ranges: list[_JsonlBatchRange],
    *,
    time_step: int,
    start: int,
    end: int,
) -> None:
    if time_step == len(ranges):
        ranges.append(_JsonlBatchRange(start=start, end=end, row_count=1))
        return
    if time_step != len(ranges) - 1:
        raise ValueError("segmented source-v2 row batches are not contiguous or ordered")
    current = ranges[-1]
    ranges[-1] = _JsonlBatchRange(
        start=current.start,
        end=end,
        row_count=current.row_count + 1,
    )


def _json_line(payload: bytes, context: str) -> dict[str, object]:
    try:
        row = _mapping(json.loads(payload), context)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError(f"{context} is not one canonical JSON object") from exc
    if payload != (_canonical_json(row) + "\n").encode("utf-8"):
        raise ValueError(f"{context} is not canonical JSONL")
    _validate_source_value_safe(row, context=context)
    return row


def _validate_source_value_safe(value: object, *, context: str) -> None:
    if isinstance(value, Mapping):
        for raw_key, nested in value.items():
            key = str(raw_key).lower()
            if any(fragment in key for fragment in _FORBIDDEN_SOURCE_KEY_FRAGMENTS):
                raise ValueError(f"{context} contains a forbidden persisted field")
            _validate_source_value_safe(nested, context=context)
    elif isinstance(value, list):
        for nested in value:
            _validate_source_value_safe(nested, context=context)


def _canonical_json_mapping_field(
    row: Mapping[str, object],
    field: str,
    *,
    context: str,
) -> dict[str, object]:
    value = row.get(field)
    if not isinstance(value, str):
        raise ValueError(f"{context} {field} must be canonical JSON text")
    try:
        parsed = _mapping(json.loads(value), f"{context} {field}")
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError(f"{context} {field} must be canonical JSON text") from exc
    if value != _canonical_json(parsed):
        raise ValueError(f"{context} {field} is not canonical JSON text")
    _validate_source_value_safe(parsed, context=f"{context} {field}")
    return parsed


def _scan_segmented_candidates(
    path: Path,
    *,
    message_ids: Sequence[str],
    horizon: int,
    sample_size: int,
    capacity: int,
) -> _SegmentedCandidateScan:
    ranges: list[_JsonlBatchRange] = []
    counts: Counter[tuple[int, str]] = Counter()
    selected: dict[tuple[str, str, int], Mapping[str, object]] = {}
    seen_users: dict[tuple[int, str], set[str]] = defaultdict(set)
    summary: dict[tuple[int, str], dict[str, object]] = {}
    row_count = 0
    rows_in_batch = 0
    current_time_step = -1
    with path.open("rb") as handle:
        while payload := handle.readline():
            start = handle.tell() - len(payload)
            row = _json_line(payload, "segmented candidate row")
            if set(row) != _SEGMENTED_CANDIDATE_FIELDS:
                raise ValueError("segmented candidate row fields are missing or extra")
            time_step = _strict_non_negative_int(row.get("time_step"), "candidate time_step")
            message_id = _non_empty(row.get("message_id"), "candidate message_id")
            user_id = _non_empty(row.get("user_id"), "candidate user_id")
            if time_step >= horizon or message_id not in message_ids:
                raise ValueError("segmented candidate batch or message is crossed")
            eligible = sample_size - capacity * time_step
            if time_step != current_time_step:
                if time_step != current_time_step + 1 or (
                    current_time_step >= 0
                    and rows_in_batch
                    != (sample_size - capacity * current_time_step) * len(message_ids)
                ):
                    raise ValueError("segmented candidate batches are missing or out of order")
                current_time_step = time_step
                rows_in_batch = 0
            expected_message_index = rows_in_batch // eligible
            expected_ranking_position = rows_in_batch % eligible + 1
            if (
                expected_message_index >= len(message_ids)
                or message_id != message_ids[expected_message_index]
                or row.get("ranking_position") != expected_ranking_position
                or user_id in seen_users[(time_step, message_id)]
                or row.get("is_seed") not in {"true", "false"}
            ):
                raise ValueError("segmented candidate order, ranking, or user identity is crossed")
            _record_batch_range(
                ranges,
                time_step=time_step,
                start=start,
                end=handle.tell(),
            )
            seen_users[(time_step, message_id)].add(user_id)
            counts[(time_step, message_id)] += 1
            key = (user_id, message_id, time_step)
            selected_marker = row.get("selected")
            selection_reason = row.get("selection_reason")
            if selected_marker == "true":
                if key in selected or selection_reason not in {"seed_union", "personalized_top20"}:
                    raise ValueError("segmented candidate selection is duplicated or unsupported")
                selected[key] = row
            elif selected_marker != "false" or selection_reason != "":
                raise ValueError("segmented candidate selected marker or reason is invalid")
            evidence = summary.setdefault(
                (time_step, message_id),
                {
                    "eligible_users": eligible,
                    "ranked_candidates": eligible,
                    "below_delivery_capacity": max(0, eligible - capacity),
                    "selected_user_ids": [],
                    "seed_user_ids": [],
                    "personalized_topup_user_ids": [],
                    "selection_reason_counts": Counter(),
                },
            )
            if selected_marker == "true":
                cast(list[str], evidence["selected_user_ids"]).append(user_id)
                if selection_reason == "seed_union":
                    cast(list[str], evidence["seed_user_ids"]).append(user_id)
                elif time_step == 0:
                    cast(list[str], evidence["personalized_topup_user_ids"]).append(user_id)
                cast(Counter[str], evidence["selection_reason_counts"])[
                    cast(str, selection_reason)
                ] += 1
            rows_in_batch += 1
            row_count += 1
    if len(ranges) != horizon:
        raise ValueError("segmented candidate rows do not cover every batch")
    normalized_summary: dict[tuple[int, str], Mapping[str, object]] = {}
    for time_step in range(horizon):
        expected = sample_size - capacity * time_step
        expected_selected = min(capacity, expected)
        for message_id in message_ids:
            evidence = summary.get((time_step, message_id))
            if (
                counts[(time_step, message_id)] != expected
                or evidence is None
                or len(cast(list[str], evidence["selected_user_ids"])) != expected_selected
            ):
                raise ValueError("segmented candidate denominator is crossed by batch or message")
            normalized_summary[(time_step, message_id)] = {
                **evidence,
                "selection_reason_counts": dict(
                    sorted(cast(Counter[str], evidence["selection_reason_counts"]).items())
                ),
            }
    return _SegmentedCandidateScan(
        ranges=tuple(ranges),
        row_count=row_count,
        selected_rows=selected,
        summary_by_batch_message=normalized_summary,
    )


def _terminal_int(row: Mapping[str, object], field: str) -> int:
    return _strict_non_negative_int(row.get(field), f"segmented terminal {field}")


def _terminal_json_mapping(row: Mapping[str, object], field: str) -> dict[str, object]:
    return _canonical_json_mapping_field(
        row,
        field,
        context="segmented terminal",
    )


def _terminal_optional_usage(row: Mapping[str, object], field: str) -> int | None:
    value = row.get(field)
    if value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"segmented terminal {field} is invalid")
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"segmented terminal {field} is invalid") from exc
    if parsed < 0:
        raise ValueError(f"segmented terminal {field} is invalid")
    return parsed


def _scan_segmented_pairs_and_terminals(
    pair_path: Path,
    terminal_path: Path,
    *,
    message_ids: Sequence[str],
    horizon: int,
    capacity: int,
    final_capacity: int,
    maximum_attempts: int,
    prompt_version: str,
    selected_rows: Mapping[tuple[str, str, int], Mapping[str, object]],
) -> _SegmentedPairTerminalScan:
    pair_ranges: list[_JsonlBatchRange] = []
    terminal_ranges: list[_JsonlBatchRange] = []
    pair_ids: set[str] = set()
    terminal_ids: set[str] = set()
    observed_pair_keys: set[tuple[str, str, int]] = set()
    distinct_users: set[str] = set()
    coverage: Counter[str] = Counter()
    batch_message_counts: Counter[tuple[int, str]] = Counter()
    positive_users: list[set[str]] = [set() for _ in range(horizon)]
    selected_users_by_batch_message: dict[tuple[int, str], list[str]] = defaultdict(list)
    failed_users_by_batch_message: dict[tuple[int, str], list[str]] = defaultdict(list)
    positive_users_by_batch_message: dict[tuple[int, str], set[str]] = defaultdict(set)
    ordered_pair_ids: list[str] = []
    ordered_terminal_ids: list[str] = []
    pair_ids_by_batch: list[list[str]] = [[] for _ in range(horizon)]
    terminal_ids_by_batch: list[list[str]] = [[] for _ in range(horizon)]
    retry_pair_ids: list[str] = []
    expected_position = 0
    serial_count = 0
    suffix_count = 0
    suffix_seen = False
    provider_failed = 0
    invocations = 0
    serial_invocations = 0
    responses = 0
    successful = 0
    observed_models: Counter[str] = Counter()
    observed_missing = 0
    observed_malformed = 0
    usage_complete_attempts = 0
    usage_incomplete_attempts = 0
    usage_complete_responses = 0
    usage_missing_responses = 0
    usage_malformed_responses = 0
    input_usage = 0
    output_usage = 0
    total_usage = 0
    cached_input_usage = 0
    cached_reported = False
    pair_count = 0
    terminal_count = 0
    with pair_path.open("rb") as pairs, terminal_path.open("rb") as terminals:
        while True:
            pair_payload = pairs.readline()
            terminal_payload = terminals.readline()
            if not pair_payload and not terminal_payload:
                break
            if not pair_payload or not terminal_payload:
                raise ValueError("segmented pair and terminal denominators differ")
            pair_start = pairs.tell() - len(pair_payload)
            terminal_start = terminals.tell() - len(terminal_payload)
            pair = _json_line(pair_payload, "segmented pair row")
            terminal = _json_line(terminal_payload, "segmented terminal row")
            if set(pair) != _SEGMENTED_PAIR_FIELDS or set(terminal) != _SEGMENTED_TERMINAL_FIELDS:
                raise ValueError("segmented pair or terminal row fields are missing or extra")
            pair_id = _non_empty(pair.get("pair_id"), "segmented pair_id")
            terminal_pair_id = _non_empty(terminal.get("pair_id"), "segmented terminal pair_id")
            terminal_id = _non_empty(terminal.get("terminal_row_id"), "segmented terminal identity")
            position = _strict_non_negative_int(
                pair.get("pair_schedule_position"), "segmented pair schedule position"
            )
            time_step = _strict_non_negative_int(pair.get("time_step"), "segmented pair time_step")
            message_id = _non_empty(pair.get("message_id"), "segmented pair message_id")
            user_id = _non_empty(pair.get("user_id"), "segmented pair user_id")
            key = (user_id, message_id, time_step)
            if (
                pair_id in pair_ids
                or terminal_id in terminal_ids
                or position != expected_position
                or time_step >= horizon
                or message_id not in message_ids
                or key not in selected_rows
                or key in observed_pair_keys
                or pair_id != f"{user_id}:{message_id}:{time_step}"
                or terminal_id != f"{pair_id}:primary"
            ):
                raise ValueError("segmented pair identity, selection, or order is crossed")
            identity_fields = ("pair_schedule_position", "time_step", "message_id", "user_id")
            selected_row = selected_rows[key]
            expected_capacity = capacity if time_step < horizon - 1 else final_capacity
            prior_pairs = min(time_step, horizon - 1) * capacity * len(message_ids)
            expected_message_index = (position - prior_pairs) // expected_capacity
            if (
                terminal_pair_id != pair_id
                or terminal.get("decision_variant") != "primary"
                or any(terminal.get(field) != pair.get(field) for field in identity_fields)
                or any(
                    pair.get(field) != selected_row.get(field)
                    for field in _CANDIDATE_PAIR_SHARED_FIELDS
                )
                or expected_message_index >= len(message_ids)
                or message_id != message_ids[expected_message_index]
            ):
                raise ValueError("segmented pair, candidate, terminal, or message order is crossed")
            crossed_terminal_fields = {
                "primary_action": "action",
                "primary_confidence": "confidence",
                "primary_decision_source": "decision_source",
                "primary_probability": "probability",
                "primary_prompt_version": "prompt_version",
                "primary_provider_metadata": "provider_metadata",
                "primary_reason": "reason",
                "primary_status": "terminal_status",
            }
            if (
                pair.get("primary_terminal_coverage") != "true"
                or any(
                    pair.get(pair_field) != terminal.get(terminal_field)
                    for pair_field, terminal_field in crossed_terminal_fields.items()
                )
                or terminal.get("prompt_version") != prompt_version
                or terminal.get("context_source_key") != f"{pair_id}:primary"
                or _SHA256_PATTERN.fullmatch(
                    _non_empty(terminal.get("cache_key"), "segmented terminal cache key")
                )
                is None
            ):
                raise ValueError("segmented pair and terminal Decision evidence is crossed")
            for row, field, context in (
                (pair, "primary_provider_metadata", "segmented pair"),
                (terminal, "provider_metadata", "segmented terminal"),
                (terminal, "context_profile_payload", "segmented terminal"),
                (terminal, "peer_context_payload", "segmented terminal"),
                (terminal, "prompt_field_inclusion", "segmented terminal"),
            ):
                _canonical_json_mapping_field(row, field, context=context)
            pair_segment = pair.get("execution_segment")
            terminal_segment = terminal.get("execution_segment")
            if pair_segment != terminal_segment or pair_segment not in {
                "serial_prefix",
                "concurrent_suffix",
            }:
                raise ValueError("segmented pair and terminal execution segments are crossed")
            if pair_segment == "serial_prefix":
                if suffix_seen:
                    raise ValueError("segmented source-v2 mixes serial and concurrent topology")
                serial_count += 1
            else:
                suffix_seen = True
                suffix_count += 1
            retry = terminal.get("reconciliation_retry")
            if not isinstance(retry, bool) or (retry and pair_segment != "concurrent_suffix"):
                raise ValueError("segmented reconciliation retry marker is crossed")
            if retry:
                retry_pair_ids.append(pair_id)
            status = terminal.get("terminal_status")
            action = terminal.get("action")
            engage = terminal.get("engage")
            positive = status == "succeeded" and action in CONCURRENT_MESSAGE_POSITIVE_ACTIONS
            if (
                pair.get("campaign_feedback_committed") != ("true" if positive else "false")
                or engage not in {"true", "false"}
                or (engage == "false") != (action == "ignore")
            ):
                raise ValueError("segmented Decision action or feedback marker is crossed")
            if positive:
                positive_users[time_step].add(user_id)
                positive_users_by_batch_message[(time_step, message_id)].add(user_id)
            if status == "provider_failed":
                provider_failed += 1
                failed_users_by_batch_message[(time_step, message_id)].append(user_id)
            elif status != "succeeded":
                raise ValueError("segmented terminal status is unsupported")
            requests = _terminal_int(terminal, "request_invocations")
            response_count = _terminal_int(terminal, "provider_response_count")
            success_count = _terminal_int(terminal, "successful_decision_count")
            if (
                not 1 <= requests <= maximum_attempts
                or not requests >= response_count >= success_count
                or success_count not in {0, 1}
                or (status == "succeeded") != (success_count == 1)
            ):
                raise ValueError("segmented terminal Provider accounting invariant failed")
            observed_counts = {
                model: _strict_non_negative_int(count, "segmented observed-model count")
                for model, count in _terminal_json_mapping(
                    terminal, "observed_model_counts"
                ).items()
            }
            missing_count = _terminal_int(terminal, "observed_model_missing_response_count")
            malformed_count = _terminal_int(
                terminal, "observed_model_malformed_response_count"
            )
            if sum(observed_counts.values()) + missing_count + malformed_count != response_count:
                raise ValueError("segmented observed-model evidence does not cover each response")
            complete_count = _terminal_int(terminal, "usage_complete_response_count")
            missing_usage_count = _terminal_int(terminal, "usage_missing_response_count")
            malformed_usage_count = _terminal_int(
                terminal, "usage_malformed_response_count"
            )
            if complete_count + missing_usage_count + malformed_usage_count != response_count:
                raise ValueError("segmented usage evidence does not cover each response")
            usage_complete = terminal.get("usage_complete")
            if usage_complete not in {"true", "false"} or (
                usage_complete == "true"
            ) != (response_count > 0 and complete_count == response_count):
                raise ValueError("segmented terminal usage_complete marker is crossed")
            input_value = _terminal_optional_usage(terminal, "input_usage")
            output_value = _terminal_optional_usage(terminal, "output_usage")
            total_value = _terminal_optional_usage(terminal, "total_usage")
            cached = _terminal_optional_usage(terminal, "cached_input_usage")
            if usage_complete == "true":
                if None in {input_value, output_value, total_value, cached}:
                    raise ValueError("segmented complete usage omits token evidence")
                assert input_value is not None and output_value is not None
                assert total_value is not None and cached is not None
                if total_value != input_value + output_value or cached > input_value:
                    raise ValueError("segmented token usage totals are crossed")
                usage_complete_attempts += 1
                input_usage += input_value
                output_usage += output_value
                total_usage += total_value
                cached_input_usage += cached
                cached_reported = True
            else:
                if any(value is not None for value in (input_value, output_value, total_value, cached)):
                    raise ValueError("segmented incomplete usage exposes partial token totals")
                if requests:
                    usage_incomplete_attempts += 1
            invocations += requests
            if pair_segment == "serial_prefix":
                serial_invocations += requests
            responses += response_count
            successful += success_count
            observed_models.update(observed_counts)
            observed_missing += missing_count
            observed_malformed += malformed_count
            usage_complete_responses += complete_count
            usage_missing_responses += missing_usage_count
            usage_malformed_responses += malformed_usage_count
            _record_batch_range(
                pair_ranges,
                time_step=time_step,
                start=pair_start,
                end=pairs.tell(),
            )
            _record_batch_range(
                terminal_ranges,
                time_step=time_step,
                start=terminal_start,
                end=terminals.tell(),
            )
            pair_ids.add(pair_id)
            terminal_ids.add(terminal_id)
            ordered_pair_ids.append(pair_id)
            ordered_terminal_ids.append(terminal_id)
            pair_ids_by_batch[time_step].append(pair_id)
            terminal_ids_by_batch[time_step].append(terminal_id)
            selected_users_by_batch_message[(time_step, message_id)].append(user_id)
            observed_pair_keys.add(key)
            distinct_users.add(user_id)
            coverage[user_id] += 1
            batch_message_counts[(time_step, message_id)] += 1
            expected_position += 1
            pair_count += 1
            terminal_count += 1
    if (
        observed_pair_keys != set(selected_rows)
        or len(pair_ranges) != horizon
        or len(terminal_ranges) != horizon
    ):
        raise ValueError("segmented selected candidate and terminal topology is incomplete")
    for time_step in range(horizon):
        expected = capacity if time_step < horizon - 1 else final_capacity
        for message_id in message_ids:
            if batch_message_counts[(time_step, message_id)] != expected:
                raise ValueError("segmented pair delivery capacity is crossed")
    accounting: dict[str, object] = {
        "invocations": invocations,
        "serial_invocations": serial_invocations,
        "responses": responses,
        "successful_decisions": successful,
        "observed_model_counts": dict(sorted(observed_models.items())),
        "observed_model_missing_response_count": observed_missing,
        "observed_model_malformed_response_count": observed_malformed,
        "usage_complete_attempts": usage_complete_attempts,
        "usage_incomplete_attempts": usage_incomplete_attempts,
        "usage_complete_response_count": usage_complete_responses,
        "usage_missing_response_count": usage_missing_responses,
        "usage_malformed_response_count": usage_malformed_responses,
        "input_usage": input_usage if usage_complete_attempts else None,
        "output_usage": output_usage if usage_complete_attempts else None,
        "total_usage": total_usage if usage_complete_attempts else None,
        "cached_input_usage": cached_input_usage if cached_reported else None,
    }
    return _SegmentedPairTerminalScan(
        pair_ranges=tuple(pair_ranges),
        terminal_ranges=tuple(terminal_ranges),
        pair_count=pair_count,
        terminal_count=terminal_count,
        distinct_users=frozenset(distinct_users),
        coverage=dict(coverage),
        provider_failed=provider_failed,
        serial_count=serial_count,
        suffix_count=suffix_count,
        retry_pair_ids=tuple(retry_pair_ids),
        accounting=accounting,
        positive_users_by_batch=tuple(frozenset(users) for users in positive_users),
        ordered_pair_ids=tuple(ordered_pair_ids),
        ordered_terminal_ids=tuple(ordered_terminal_ids),
        pair_ids_by_batch=tuple(tuple(rows) for rows in pair_ids_by_batch),
        terminal_ids_by_batch=tuple(tuple(rows) for rows in terminal_ids_by_batch),
        selected_users_by_batch_message={
            key: tuple(value) for key, value in selected_users_by_batch_message.items()
        },
        failed_users_by_batch_message={
            key: tuple(sorted(value)) for key, value in failed_users_by_batch_message.items()
        },
        positive_users_by_batch_message={
            key: tuple(sorted(value)) for key, value in positive_users_by_batch_message.items()
        },
    )


def _scan_segmented_steps(
    path: Path,
    *,
    horizon: int,
    message_ids: Sequence[str],
    message_titles: Mapping[str, str],
    candidate_summary: Mapping[tuple[int, str], Mapping[str, object]],
    pair_scan: _SegmentedPairTerminalScan,
) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    cumulative: set[str] = set()
    with path.open("rb") as handle:
        while payload := handle.readline():
            row = _json_line(payload, "segmented step row")
            if set(row) != _SEGMENTED_STEP_FIELDS:
                raise ValueError("segmented step row fields are missing or extra")
            time_step = _strict_non_negative_int(row.get("time_step"), "segmented step time_step")
            if time_step != len(rows) or time_step >= horizon:
                raise ValueError("segmented step rows are missing, extra, or out of order")
            frozen = _string_list(
                row.get("frozen_campaign_engaged_user_ids"), "segmented frozen feedback"
            )
            committed = _string_list(
                row.get("committed_primary_positive_user_ids"), "segmented committed feedback"
            )
            if (
                frozen != sorted(cumulative)
                or committed != sorted(pair_scan.positive_users_by_batch[time_step])
            ):
                raise ValueError("segmented feedback barrier or committed users are crossed")
            summaries = _mapping_sequence(
                row.get("message_summaries"), "segmented message summaries"
            )
            if len(summaries) != len(message_ids):
                raise ValueError("segmented message summary denominator is crossed")
            for message_id, summary in zip(message_ids, summaries, strict=True):
                if set(summary) != _SEGMENTED_MESSAGE_SUMMARY_FIELDS:
                    raise ValueError("segmented message summary fields are missing or extra")
                candidate = candidate_summary[(time_step, message_id)]
                expected = {
                    **candidate,
                    "message_id": message_id,
                    "message_title": message_titles[message_id],
                    "selected_user_ids": list(
                        pair_scan.selected_users_by_batch_message[(time_step, message_id)]
                    ),
                    "primary_positive_user_ids": list(
                        pair_scan.positive_users_by_batch_message.get((time_step, message_id), ())
                    ),
                    "primary_provider_failed_user_ids": list(
                        pair_scan.failed_users_by_batch_message.get((time_step, message_id), ())
                    ),
                    "shadow_provider_failed_user_ids": [],
                }
                if summary != expected:
                    raise ValueError("segmented message summary is crossed with source rows")
            cumulative.update(committed)
            rows.append(row)
    if len(rows) != horizon:
        raise ValueError("segmented steps do not close the horizon")
    return tuple(rows)


def _validate_segmented_cutoff_order(
    cutoff: Mapping[str, object],
    *,
    pair_scan: _SegmentedPairTerminalScan,
    step_rows: Sequence[Mapping[str, object]],
) -> None:
    committed = _mapping_sequence(
        cutoff.get("committed_batches"), "segmented committed cutoff batches"
    )
    active = _mapping(cutoff.get("active_batch"), "segmented active cutoff batch")
    committed_pair_ids: list[str] = []
    committed_terminal_ids: list[str] = []
    for time_step, batch in enumerate(committed):
        if (
            set(batch)
            != {
                "time_step",
                "batch_snapshot_hash",
                "spool_ref",
                "ordered_pair_ids",
                "ordered_terminal_ids",
                "frozen_feedback_user_ids",
                "committed_feedback_user_ids",
            }
            or batch.get("time_step") != time_step
            or _string_list(batch.get("ordered_pair_ids"), "cutoff committed pair IDs")
            != list(pair_scan.pair_ids_by_batch[time_step])
            or _string_list(
                batch.get("ordered_terminal_ids"), "cutoff committed terminal IDs"
            )
            != list(pair_scan.terminal_ids_by_batch[time_step])
            or _string_list(
                batch.get("frozen_feedback_user_ids"), "cutoff committed frozen feedback"
            )
            != _string_list(
                step_rows[time_step].get("frozen_campaign_engaged_user_ids"),
                "source committed frozen feedback",
            )
            or _string_list(
                batch.get("committed_feedback_user_ids"),
                "cutoff committed positive feedback",
            )
            != _string_list(
                step_rows[time_step].get("committed_primary_positive_user_ids"),
                "source committed positive feedback",
            )
        ):
            raise ValueError("segmented committed cutoff batch is crossed with source rows")
        committed_pair_ids.extend(pair_scan.pair_ids_by_batch[time_step])
        committed_terminal_ids.extend(pair_scan.terminal_ids_by_batch[time_step])
    active_time_step = len(committed)
    if (
        set(active)
        != {
            "time_step",
            "batch_snapshot_hash",
            "snapshot_ref",
            "ordered_pair_ids",
            "ordered_terminal_ids",
            "frozen_feedback_user_ids",
        }
        or active.get("time_step") != active_time_step
        or active_time_step >= len(pair_scan.pair_ids_by_batch)
        or _string_list(active.get("ordered_pair_ids"), "cutoff active pair IDs")
        != list(pair_scan.pair_ids_by_batch[active_time_step])
        or _string_list(active.get("frozen_feedback_user_ids"), "cutoff active frozen feedback")
        != _string_list(
            step_rows[active_time_step].get("frozen_campaign_engaged_user_ids"),
            "source active frozen feedback",
        )
    ):
        raise ValueError("segmented active cutoff batch is crossed with source rows")
    active_terminal_ids = _string_list(
        active.get("ordered_terminal_ids"), "cutoff active terminal IDs"
    )
    serial_terminal_ids = list(pair_scan.ordered_terminal_ids[: pair_scan.serial_count])
    if (
        committed_terminal_ids + active_terminal_ids != serial_terminal_ids
        or _string_list(cutoff.get("ordered_prefix_terminal_ids"), "cutoff terminal IDs")
        != serial_terminal_ids
        or _string_list(cutoff.get("ordered_prefix_pair_ids"), "cutoff pair IDs")
        != committed_pair_ids + list(pair_scan.pair_ids_by_batch[active_time_step])
    ):
        raise ValueError("segmented cutoff pair or terminal order is crossed")


def _validate_segmented_reconciliation(
    cutoff: Mapping[str, object],
    *,
    retry_pair_ids: Sequence[str],
    prefix_identity_hash: str,
    maximum_attempts: int,
) -> tuple[int, int]:
    unknown_ids = _string_list(cutoff.get("unknown_pair_ids"), "segmented migration unknowns")
    unknown_count = _strict_non_negative_int(
        cutoff.get("unknown_count"), "segmented migration unknown count"
    )
    authorization = cutoff.get("reconciliation_authorization")
    authorization_hash = cutoff.get("reconciliation_authorization_sha256")
    if unknown_count != len(unknown_ids) or unknown_count not in {0, 1}:
        raise ValueError("segmented migration unknown denominator is crossed")
    if unknown_count == 0:
        if authorization is not None or authorization_hash is not None or retry_pair_ids:
            raise ValueError("segmented reconciliation appears without a migration unknown")
        return 0, 0
    document = _mapping(authorization, "segmented reconciliation authorization")
    try:
        parsed = FullPoolReconciliationAuthorization.model_validate(document)
    except (TypeError, ValueError) as exc:
        raise ValueError("segmented reconciliation authorization is invalid") from exc
    if (
        parsed.prefix_run_identity_hash != prefix_identity_hash
        or parsed.unknown_pair_id != unknown_ids[0]
        or parsed.retry_authorized is not True
        or authorization_hash != _sha256_json(parsed.model_dump(mode="json"))
        or list(retry_pair_ids) != unknown_ids
        or parsed.physical_attempt_charge != maximum_attempts
    ):
        raise ValueError("segmented reconciliation authorization or retry identity is crossed")
    return parsed.physical_attempt_charge, unknown_count


def _segmented_execution_document(facts: SegmentedFullPoolSourceFacts) -> dict[str, object]:
    return {
        "execution_topology": "serial_prefix_then_concurrent_suffix",
        "serial_prefix_terminal_count": facts.serial_prefix_terminal_count,
        "concurrent_suffix_terminal_count": facts.concurrent_suffix_terminal_count,
        "max_concurrency": facts.max_concurrency,
        "cutoff_manifest_sha256": facts.cutoff_manifest_sha256,
        "continuation_identity_hash": facts.continuation_identity_hash,
        "prefix_identity_hash": facts.prefix_identity_hash,
        "formal_execution_contract_sha256": facts.formal_execution_contract_sha256,
        "authorization_artifact_sha256": facts.authorization_artifact_sha256,
        "qualification_artifact_sha256": facts.qualification_artifact_sha256,
        "observed_model_evidence_sha256": facts.observed_model_evidence_sha256,
        "prompt_variant_id": facts.prompt_variant_id,
        "prompt_version": facts.prompt_version,
        "prompt_canonical_hash": facts.prompt_canonical_hash,
        "unknown_pair_count": facts.unknown_pair_count,
        "reconciliation_retry_count": facts.reconciliation_retry_count,
        "migration_unknown_physical_charge": facts.migration_unknown_physical_charge,
        "total_physical_attempts": facts.physical_attempts,
    }


def _read_jsonl_range(path: Path, row_range: _JsonlBatchRange) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open("rb") as handle:
        handle.seek(row_range.start)
        while handle.tell() < row_range.end:
            payload = handle.readline()
            if not payload:
                break
            rows.append(_json_line(payload, f"segmented batch row from {path.name}"))
        final_position = handle.tell()
    if len(rows) != row_range.row_count or final_position != row_range.end:
        raise ValueError("segmented batch byte range changed after source closure")
    return rows


def _artifact_inventory(workspace: Path) -> dict[str, dict[str, object]]:
    inventory: dict[str, dict[str, object]] = {}
    for path in sorted(workspace.rglob("*")):
        relative = path.relative_to(workspace).as_posix()
        if path.is_symlink():
            raise ValueError(f"v1 prefix artifact must not be a symlink: {relative}")
        mode = path.stat(follow_symlinks=False).st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise ValueError(f"v1 prefix artifact must be a regular file: {relative}")
        inventory[relative] = _file_ref(workspace, path)
    return inventory


def _file_ref(workspace: Path, path: Path) -> dict[str, object]:
    return {
        "relative_path": path.relative_to(workspace).as_posix(),
        "byte_length": path.stat(follow_symlinks=False).st_size,
        "sha256": _sha256_file(path),
    }


def _create_workspace(path: Path) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"continuation workspace already exists: {path}")
    path.mkdir(parents=True)
    _fsync_directory(path.parent)


def _exclusive_write_lines(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as handle:
            for row in rows:
                handle.write(_canonical_json(row) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)
    _fsync_directory(path.parent)


def _append_jsonl(path: Path, payload: Mapping[str, object]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(_canonical_json(payload) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    content = _canonical_json(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
        temp_path = Path(handle.name)
    os.replace(temp_path, path)
    _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_DIRECTORY)
    except (AttributeError, FileNotFoundError, NotADirectoryError, OSError):
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _require_real_directory(path: Path, context: str) -> None:
    if path.is_symlink():
        raise ValueError(f"{context} must not be a symlink")
    mode = path.stat(follow_symlinks=False).st_mode
    if not stat.S_ISDIR(mode):
        raise ValueError(f"{context} must be a real directory")


def _require_real_file(path_raw: Path, label: str) -> Path:
    absolute = Path(os.path.abspath(path_raw.expanduser()))
    resolved = path_raw.expanduser().resolve(strict=True)
    if absolute != resolved or path_raw.is_symlink() or not resolved.is_file():
        raise ValueError(f"{label} must be one explicit real file")
    return resolved


def _read_json_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _mapping(payload, path.name)


def _mapping(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{context} must be an object")
    return {str(key): item for key, item in value.items()}


def _mapping_sequence(value: object, context: str) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{context} must be a sequence")
    return [_mapping(item, context) for item in value]


def _string_list(value: object, context: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{context} must be a sequence")
    if not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{context} must contain non-empty strings")
    result = list(cast(Sequence[str], value))
    if len(result) != len(set(result)):
        raise ValueError(f"{context} must not contain duplicates")
    return result


def _non_empty(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be a non-empty string")
    return value


def _strict_non_negative_int(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{context} must be a non-negative integer")
    return value


def _float_value(value: object, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"{context} must be numeric")
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{context} must be numeric") from exc


def _canonical_json(value: object) -> str:
    return json.dumps(_json_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_value(value: object) -> object:
    if isinstance(value, BaseModel):
        return cast(BaseModel, value).model_dump(mode="json")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_json_value(item) for item in value]
    return value


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()
