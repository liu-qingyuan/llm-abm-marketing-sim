from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ._concurrent_runtime_spool import (
    _ConcurrentRuntimeBatchSpool,
    _ConcurrentRuntimeSpoolChunk,
)
from .concurrent_execution_journal import ConcurrentExecutionJournal
from .concurrent_message_experiment import (
    ConcurrentMessageExperimentConfig,
    _ConcurrentRuntimeKernel,
    _ConcurrentRuntimeKernelState,
    _PairExecutionPlan,
    _PreparedConcurrentRuntimeInputs,
    _PrimaryOnlyConcurrentRuntimeConsumer,
)
from .decision import LLMDecisionAdapter
from .full_pool_formal_experiment import (
    FULL_POOL_FORMAL_REQUESTED_MODEL,
    FULL_POOL_FORMAL_REQUIRED_OBSERVED_MODEL,
)
from .full_pool_segmented_continuation import (
    FULL_POOL_SEGMENTED_LOGICAL_CAP,
    FULL_POOL_SEGMENTED_MAX_CONCURRENCY,
    FULL_POOL_SEGMENTED_PHYSICAL_CAP,
    SEGMENTED_CONCURRENCY_QUALIFICATION_FILE,
    SegmentedQualificationArtifactRef,
    _atomic_write_json,
    _build_lanes,
    _close_segmented_source_v2,
    _ContinuationLedger,
    _create_workspace,
    _execute_typed_plans,
    _freeze_v1_prefix,
    _FrozenPrefix,
    _iter_prefix_committed_chunks,
    _prepare_segmented_runtime,
    _replay_continuation_ledger,
    _reserve_dynamic_wave,
    _run_typed_wave,
    _SegmentedKernelJournal,
    _validated_concurrency_qualification_bytes,
    _WorkerResult,
)
from .full_pool_segmented_operator import (
    CutoverPlanRequest,
    FullPoolSegmentedCutoverOperator,
    LocalOperatorFilesystem,
    _request_fields,
)
from .full_pool_segmented_recovery import FullPoolSegmentedRecoveryPreflight

_RECOVERY_AUTHORIZATION_SCHEMA = "full-pool-segmented-recovery-human-authorization-v1"
_RECOVERY_AUTHORIZATION_ENVELOPE_SCHEMA = (
    "full-pool-segmented-recovery-human-authorization-envelope-v1"
)
_RECOVERY_SCOPE = "retry-two-unresolved-and-complete-source-v2"
_RECOVERY_IDENTITY_SCHEMA = "full-pool-segmented-recovery-execution-identity-v1"
_RECOVERY_MANIFEST_SCHEMA = "full-pool-segmented-recovery-cutoff-manifest-v1"
_RECOVERY_MANIFEST_ENVELOPE_SCHEMA = "full-pool-segmented-recovery-cutoff-envelope-v1"
_RECOVERY_STATUS_SCHEMA = "full-pool-segmented-recovery-status-v1"
_RECOVERY_STATUS_FILE = "segmented_recovery_status.json"
_CONTINUATION_STATUS_FILE = "segmented_continuation_status.json"
_IDENTITY_FILE = "segmented_continuation_identity.json"
_MANIFEST_FILE = "cutoff_manifest.json"
_LEDGER_FILE = "segmented_continuation_ledger.jsonl"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RECOVERY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_AUTHORIZATION_FIELDS = frozenset(
    {
        "schema_version",
        "authorization_id",
        "authorization_reference",
        "authorized_at",
        "expires_at",
        "scope",
        "recovery_plan_sha256",
        "recovery_plan_identity_hash",
        "failed_continuation_identity_hash",
        "unresolved_pair_ids",
        "configured_max_concurrency",
        "prompt_version",
        "provider_contract_sha256",
        "prompt_contract_sha256",
        "requested_model",
        "required_observed_model",
        "maximum_attempts_per_dispatch",
        "uncertainty_physical_charge",
        "logical_cap",
        "physical_cap",
        "historical_logical_count",
        "historical_physical_attempts",
        "recovery_id",
        "recovery_workspace",
        "retry_authorized",
        "production_deploy_eligible",
    }
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SegmentedRecoveryExecutionRequest(_FrozenModel):
    """Exact persisted authorization and create-once recovery destination."""

    recovery_plan_path: Path
    recovery_plan_sha256: str
    authorization_path: Path
    authorization_sha256: str
    recovery_id: str = Field(min_length=1, max_length=160)
    recovery_workspace: Path

    @field_validator(
        "recovery_plan_path",
        "authorization_path",
        "recovery_workspace",
        mode="before",
    )
    @classmethod
    def _absolute_path(cls, value: object) -> Path:
        return Path(cast(str | Path, value)).expanduser().absolute()

    @field_validator("recovery_plan_sha256", "authorization_sha256")
    @classmethod
    def _hash(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("persisted recovery references require lowercase SHA-256 digests")
        return value

    @field_validator("recovery_id")
    @classmethod
    def _identity(cls, value: str) -> str:
        if _RECOVERY_ID.fullmatch(value) is None:
            raise ValueError("recovery_id contains unsupported characters")
        return value

    @model_validator(mode="after")
    def _independent_paths(self) -> SegmentedRecoveryExecutionRequest:
        if self.recovery_plan_path == self.authorization_path:
            raise ValueError("recovery plan and human authorization must be distinct files")
        for source in (self.recovery_plan_path, self.authorization_path):
            if source == self.recovery_workspace or source.is_relative_to(self.recovery_workspace):
                raise ValueError("recovery workspace must not own its authorization inputs")
        return self


class SegmentedRecoveryExecutionResult(_FrozenModel):
    status: Literal["complete", "resumable", "reconciliation_required"]
    workspace_root: Path
    recovery_identity_hash: str
    source_root: Path | None = None
    source_manifest_sha256: str | None = None
    logical_count: int = Field(ge=0)
    historical_physical_attempts: int = Field(ge=0)
    uncertainty_physical_charge: int = Field(ge=0)
    retry_physical_attempts: int = Field(ge=0)
    continuation_physical_attempts: int = Field(ge=0)
    physical_attempt_count: int = Field(ge=0)
    imported_durable_terminal_count: int = Field(ge=0)
    recovered_pair_ids: tuple[str, ...]
    unknown_pair_ids: tuple[str, ...]
    provider_calls: Literal[0] = 0
    production_deploy_eligible: Literal[False] = False


@dataclass(frozen=True)
class _FailedLedgerReplay:
    kernel_replay: dict[str, object]
    terminal_payload_by_pair_id: dict[str, dict[str, object]]
    dispatched_pair_ids: tuple[str, ...]
    durable_pair_ids: tuple[str, ...]
    wave_physical_attempts: int


@dataclass(frozen=True)
class _RecoveryDocuments:
    identity: dict[str, object]
    manifest: dict[str, object]
    manifest_sha256: str


@dataclass(frozen=True)
class _RecoveryRuntime:
    ledger: _ContinuationLedger
    journal: _SegmentedKernelJournal
    spool: _ConcurrentRuntimeBatchSpool
    kernel: _ConcurrentRuntimeKernel
    state: _ConcurrentRuntimeKernelState


@dataclass(frozen=True)
class _ValidatedRecoveryInputs:
    plan: dict[str, object]
    authorization: dict[str, object]
    cutover_request: CutoverPlanRequest
    prefix: _FrozenPrefix
    config: ConcurrentMessageExperimentConfig
    prepared: _PreparedConcurrentRuntimeInputs
    failed_continuation_identity: dict[str, object]
    failed_ledger: _FailedLedgerReplay
    historical_chunks: tuple[_ConcurrentRuntimeSpoolChunk, ...]
    snapshot_document_by_time_step: dict[int, dict[str, object]]
    active_snapshot_document: dict[str, object]
    active_terminal_payloads: tuple[dict[str, object], ...]
    qualification_artifact: SegmentedQualificationArtifactRef
    unresolved_pair_ids: tuple[str, str]
    imported_durable_terminal_count: int
    protected_inventories: dict[str, object]


class FullPoolSegmentedRecovery:
    """Consume one persisted human authorization and recover one exact failed run.

    Validation of the plan, authorization, expiry, immutable source references, and
    destination identity completes before the Adapter factory can be called.
    """

    def __init__(self, *, now: Callable[[], datetime] | None = None) -> None:
        self._now = now or (lambda: datetime.now(timezone.utc))

    def run(
        self,
        request: SegmentedRecoveryExecutionRequest,
        *,
        adapter_factory: Callable[[int], LLMDecisionAdapter],
    ) -> SegmentedRecoveryExecutionResult:
        inputs = self._validated_inputs(request)
        documents = _recovery_documents(request, inputs)
        if request.recovery_workspace.exists() or request.recovery_workspace.is_symlink():
            return _load_existing_recovery(request, inputs, documents)

        runtime = _initialize_recovery_workspace(request, inputs, documents)
        _assert_protected_unchanged(request, inputs)
        pending = runtime.kernel.pending_plans()
        if [plan.pair_id for plan in pending[:2]] != list(inputs.unresolved_pair_ids):
            return _persist_partial_result(
                request,
                inputs,
                documents,
                runtime,
                status="reconciliation_required",
                retry_physical_attempts=0,
                continuation_physical_attempts=0,
                fresh_logical_count=0,
                unknown_pair_ids=inputs.unresolved_pair_ids,
            )

        accounting = _mapping(inputs.plan.get("accounting"), "recovery accounting")
        historical_physical = _non_negative_int(
            accounting.get("historical_physical_attempts"),
            "historical physical attempts",
        )
        uncertainty_charge = _non_negative_int(
            accounting.get("unresolved_uncertainty_physical_charge"),
            "uncertainty physical charge",
        )
        base_physical = historical_physical + uncertainty_charge
        retry_physical_attempts = 0
        continuation_physical_attempts = 0
        fresh_logical_count = 0
        phase = "adapter_creation"
        try:
            adapters = _build_lanes(inputs.prefix, adapter_factory)
            phase = "retry_wave"
            reservation = _reserve_dynamic_wave(
                remaining_pair_count=2,
                physical_attempts=base_physical,
                maximum_attempts_per_dispatch=inputs.prefix.maximum_attempts_per_dispatch,
            )
            if reservation.wave_size != 2:
                return _persist_partial_result(
                    request,
                    inputs,
                    documents,
                    runtime,
                    status="resumable",
                    retry_physical_attempts=0,
                    continuation_physical_attempts=0,
                    fresh_logical_count=0,
                    unknown_pair_ids=(),
                )
            retry_plans = pending[:2]
            runtime.ledger.append(
                "suffix_wave_reserved",
                {
                    "pair_ids": [plan.pair_id for plan in retry_plans],
                    "physical_reservation": reservation.reserved_physical_attempts,
                    "maximum_attempts_per_dispatch": inputs.prefix.maximum_attempts_per_dispatch,
                },
            )
            retry_results, retry_physical_attempts = _run_typed_wave(
                plans=retry_plans,
                adapters=adapters,
                ledger=runtime.ledger,
                provider_metadata=inputs.prefix.provider_contract,
            )
            _register_results(runtime.kernel, retry_plans, retry_results)

            phase = "continuation_waves"
            remaining_active = runtime.kernel.pending_plans()
            active_results, active_attempts, cap_stopped = _execute_typed_plans(
                plans=remaining_active,
                adapters=adapters,
                ledger=runtime.ledger,
                provider_metadata=inputs.prefix.provider_contract,
                physical_attempts=base_physical + retry_physical_attempts,
                maximum_attempts_per_dispatch=inputs.prefix.maximum_attempts_per_dispatch,
                first_wave_observer_state=[None],
                qualification_artifact_state=[None],
            )
            _register_results(runtime.kernel, remaining_active[: len(active_results)], active_results)
            continuation_physical_attempts += active_attempts
            fresh_logical_count += len(active_results)
            if cap_stopped:
                return _persist_partial_result(
                    request,
                    inputs,
                    documents,
                    runtime,
                    status="resumable",
                    retry_physical_attempts=retry_physical_attempts,
                    continuation_physical_attempts=continuation_physical_attempts,
                    fresh_logical_count=fresh_logical_count,
                    unknown_pair_ids=(),
                )
            runtime.kernel.commit_primary_batch()

            while runtime.state.next_time_step < inputs.config.horizon:
                if runtime.kernel.active_batch is None:
                    runtime.kernel.plan_batch()
                plans = runtime.kernel.pending_plans()
                results, attempts, cap_stopped = _execute_typed_plans(
                    plans=plans,
                    adapters=adapters,
                    ledger=runtime.ledger,
                    provider_metadata=inputs.prefix.provider_contract,
                    physical_attempts=(
                        base_physical
                        + retry_physical_attempts
                        + continuation_physical_attempts
                    ),
                    maximum_attempts_per_dispatch=inputs.prefix.maximum_attempts_per_dispatch,
                    first_wave_observer_state=[None],
                    qualification_artifact_state=[None],
                )
                _register_results(runtime.kernel, plans[: len(results)], results)
                continuation_physical_attempts += attempts
                fresh_logical_count += len(results)
                if cap_stopped:
                    return _persist_partial_result(
                        request,
                        inputs,
                        documents,
                        runtime,
                        status="resumable",
                        retry_physical_attempts=retry_physical_attempts,
                        continuation_physical_attempts=continuation_physical_attempts,
                        fresh_logical_count=fresh_logical_count,
                        unknown_pair_ids=(),
                    )
                runtime.kernel.commit_primary_batch()
        except BaseException:
            observed_new_physical = _new_wave_physical_attempts(
                request.recovery_workspace / _LEDGER_FILE,
                documents.identity["identity_hash"],
            )
            if phase == "retry_wave":
                retry_physical_attempts = observed_new_physical
            elif phase == "continuation_waves":
                continuation_physical_attempts = max(
                    continuation_physical_attempts,
                    observed_new_physical - retry_physical_attempts,
                )
            unknown_pair_ids = _new_unknown_pair_ids(
                request.recovery_workspace / _LEDGER_FILE,
                documents.identity["identity_hash"],
            )
            fresh_logical_count = max(
                fresh_logical_count,
                _new_fresh_dispatch_count(
                    request.recovery_workspace / _LEDGER_FILE,
                    documents.identity["identity_hash"],
                    inputs.unresolved_pair_ids,
                ),
            )
            return _persist_partial_result(
                request,
                inputs,
                documents,
                runtime,
                status="reconciliation_required",
                retry_physical_attempts=retry_physical_attempts,
                continuation_physical_attempts=continuation_physical_attempts,
                fresh_logical_count=fresh_logical_count,
                unknown_pair_ids=unknown_pair_ids,
            )

        expected_logical = inputs.config.sample_size * len(inputs.config.messages)
        historical_logical = _non_negative_int(
            accounting.get("historical_logical_count"), "historical logical count"
        )
        if historical_logical + fresh_logical_count != expected_logical:
            return _persist_partial_result(
                request,
                inputs,
                documents,
                runtime,
                status="reconciliation_required",
                retry_physical_attempts=retry_physical_attempts,
                continuation_physical_attempts=continuation_physical_attempts,
                fresh_logical_count=fresh_logical_count,
                unknown_pair_ids=(),
            )
        physical_total = (
            historical_physical
            + uncertainty_charge
            + retry_physical_attempts
            + continuation_physical_attempts
        )
        recovery_accounting = _recovery_accounting(
            inputs,
            logical_count=expected_logical,
            fresh_logical_count=fresh_logical_count,
            retry_physical_attempts=retry_physical_attempts,
            continuation_physical_attempts=continuation_physical_attempts,
        )
        recovery_lineage = _recovery_lineage(request, inputs, documents)
        source_root, source_manifest_sha256, complete_status = _close_segmented_source_v2(
            continuation=request.recovery_workspace,
            prefix=inputs.prefix,
            continuation_spool=runtime.spool,
            continuation_replay=runtime.journal.replay(),
            config=inputs.config,
            logical_count=expected_logical,
            physical_attempt_count=physical_total,
            cutoff_manifest_sha256=documents.manifest_sha256,
            continuation_identity_hash=cast(str, documents.identity["identity_hash"]),
            qualification_artifact=inputs.qualification_artifact,
            ledger=runtime.ledger,
            historical_chunks=(),
            recovery_retry_pair_ids=inputs.unresolved_pair_ids,
            recovery_lineage=recovery_lineage,
            recovery_accounting=recovery_accounting,
            recovery_artifacts={
                "recovery-plan.json": request.recovery_plan_path,
                "human-authorization.json": request.authorization_path,
            },
        )
        standard_status = {
            "schema_version": "full-pool-segmented-continuation-status-v1",
            "lifecycle": "complete",
            "manifest_sha256": documents.manifest_sha256,
            **complete_status,
            "source_manifest_sha256": source_manifest_sha256,
        }
        _atomic_write_json(request.recovery_workspace / _CONTINUATION_STATUS_FILE, standard_status)
        result = SegmentedRecoveryExecutionResult(
            status="complete",
            workspace_root=request.recovery_workspace,
            recovery_identity_hash=cast(str, documents.identity["identity_hash"]),
            source_root=source_root,
            source_manifest_sha256=source_manifest_sha256,
            logical_count=expected_logical,
            historical_physical_attempts=historical_physical,
            uncertainty_physical_charge=uncertainty_charge,
            retry_physical_attempts=retry_physical_attempts,
            continuation_physical_attempts=continuation_physical_attempts,
            physical_attempt_count=physical_total,
            imported_durable_terminal_count=inputs.imported_durable_terminal_count,
            recovered_pair_ids=inputs.unresolved_pair_ids,
            unknown_pair_ids=(),
            provider_calls=0,
            production_deploy_eligible=False,
        )
        _write_recovery_status(request, result)
        _assert_protected_unchanged(request, inputs)
        return result

    def status(
        self,
        request: SegmentedRecoveryExecutionRequest,
    ) -> SegmentedRecoveryExecutionResult:
        inputs = self._validated_inputs(request)
        documents = _recovery_documents(request, inputs)
        return _load_existing_recovery(request, inputs, documents)

    def _validated_inputs(
        self,
        request: SegmentedRecoveryExecutionRequest,
    ) -> _ValidatedRecoveryInputs:
        plan_path = _require_regular_file(request.recovery_plan_path, "recovery plan")
        if _sha256_file(plan_path) != request.recovery_plan_sha256:
            raise ValueError("recovery plan bytes differ from the explicit hash")
        FullPoolSegmentedRecoveryPreflight().status(plan_path)
        plan_envelope = _read_json(plan_path)
        plan = _mapping(plan_envelope.get("payload"), "recovery plan payload")

        authorization_path = _require_regular_file(
            request.authorization_path,
            "persisted human authorization",
        )
        if _sha256_file(authorization_path) != request.authorization_sha256:
            raise ValueError("human authorization bytes differ from the explicit hash")
        envelope = _read_json(authorization_path)
        if set(envelope) != {"schema_version", "payload", "payload_sha256"}:
            raise ValueError("human authorization envelope fields are not exact")
        if envelope.get("schema_version") != _RECOVERY_AUTHORIZATION_ENVELOPE_SCHEMA:
            raise ValueError("human authorization envelope schema is unsupported")
        authorization = _mapping(envelope.get("payload"), "human authorization payload")
        if envelope.get("payload_sha256") != _sha256_json(authorization):
            raise ValueError("human authorization payload hash mismatch")
        self._validate_authorization(request, plan, authorization)

        failed_lineage = _mapping(plan.get("failed_run_lineage"), "failed run lineage")
        artifact_refs = _mapping(failed_lineage.get("artifact_refs"), "failed artifact refs")
        for label, ref_raw in artifact_refs.items():
            _validate_file_ref(_mapping(ref_raw, f"failed {label} artifact ref"), label)
        cutover_plan_ref = _mapping(artifact_refs.get("cutover_plan"), "cutover plan ref")
        cutover_plan_path = Path(_non_empty(cutover_plan_ref.get("path"), "cutover plan path"))
        operator = FullPoolSegmentedCutoverOperator(filesystem=LocalOperatorFilesystem())
        cutover_plan, cutover_plan_sha256 = operator._read_plan(cutover_plan_path)
        if cutover_plan_sha256 != cutover_plan_ref.get("sha256"):
            raise ValueError("recovery plan cutover lineage is crossed")
        cutover_request = CutoverPlanRequest.model_validate(_request_fields(cutover_plan))

        source_inventories = _mapping(plan.get("source_inventories"), "recovery source inventories")
        filesystem = LocalOperatorFilesystem()
        frozen_inventory = _mapping(
            source_inventories.get("frozen_prefix"), "recovery frozen-prefix inventory"
        )
        failed_inventory = _mapping(
            source_inventories.get("failed_continuation"), "recovery failed-continuation inventory"
        )
        if filesystem.inventory(cutover_request.frozen_prefix_workspace) != frozen_inventory:
            raise ValueError("frozen prefix changed after recovery planning")
        if filesystem.inventory(cutover_request.continuation_workspace) != failed_inventory:
            raise ValueError("failed continuation changed after recovery planning")

        for source_root in (
            cutover_request.prefix_workspace,
            cutover_request.frozen_prefix_workspace,
            cutover_request.continuation_workspace,
            cutover_request.dataset_dir,
            Path(_non_empty(
                _mapping(plan.get("recovery_identity"), "recovery identity").get("recovery_root"),
                "recovery plan root",
            )),
        ):
            if (
                request.recovery_workspace == source_root
                or request.recovery_workspace.is_relative_to(source_root)
                or source_root.is_relative_to(request.recovery_workspace)
            ):
                raise ValueError("new recovery workspace is not independent from persisted inputs")

        prefix = _freeze_v1_prefix(cutover_request.frozen_prefix_workspace)
        config, prepared, _dataset_ref = _prepare_segmented_runtime(prefix, cutover_request.dataset_dir)
        failed_continuation = cutover_request.continuation_workspace
        failed_identity = _read_json(failed_continuation / "segmented_continuation_identity.json")
        expected_failed_identity_hash = _non_empty(
            _mapping(plan.get("recovery_identity"), "recovery identity").get(
                "failed_continuation_identity_hash"
            ),
            "failed continuation identity hash",
        )
        if failed_identity.get("identity_hash") != expected_failed_identity_hash:
            raise ValueError("failed continuation identity is crossed with the recovery plan")
        failed_ledger = _read_failed_ledger(
            failed_continuation / "segmented_continuation_ledger.jsonl",
            continuation=failed_continuation,
            expected_identity_hash=expected_failed_identity_hash,
        )

        historical_chunks = list(_iter_prefix_committed_chunks(prefix))
        active_base_time_step = _non_negative_int(
            prefix.active_batch["time_step"], "prefix active time_step"
        )
        failed_spool = _ConcurrentRuntimeBatchSpool(
            failed_continuation,
            run_id=_non_empty(failed_identity.get("run_id"), "failed continuation run_id"),
            identity_hash=expected_failed_identity_hash,
            terminal_variants=("primary",),
            base_time_step=active_base_time_step,
        )
        historical_chunks.extend(failed_spool.iter_committed(failed_ledger.kernel_replay))
        if [chunk.time_step for chunk in historical_chunks] != list(range(len(historical_chunks))):
            raise ValueError("recovery historical batch chunks are missing, extra, or out of order")

        prefix_full_replay = ConcurrentExecutionJournal.open_existing(prefix.workspace).replay()
        snapshot_document_by_time_step = _snapshot_documents(prefix_full_replay)
        for time_step, document in _snapshot_documents(failed_ledger.kernel_replay).items():
            prefix_document = snapshot_document_by_time_step.get(time_step)
            if prefix_document is not None and prefix_document != document:
                raise ValueError("prefix and failed continuation snapshots overlap with different bytes")
            snapshot_document_by_time_step[time_step] = document
        active_time_step = len(historical_chunks)
        active_snapshot_document = snapshot_document_by_time_step.get(active_time_step)
        if active_snapshot_document is None:
            raise ValueError("recovery active batch snapshot is missing")

        recovery_snapshot = _mapping(plan.get("recovery_snapshot"), "recovery snapshot")
        batches = _mapping_sequence(recovery_snapshot.get("batch_snapshots"), "recovery batch snapshots")
        if [batch.get("time_step") for batch in batches] != list(range(len(batches))):
            raise ValueError("recovery batch snapshot time steps are crossed")
        if len(batches) != active_time_step + 1 or batches[-1].get("state") != "active_incomplete":
            raise ValueError("recovery plan does not retain one final incomplete batch")
        if any(batch.get("state") != "committed" for batch in batches[:-1]):
            raise ValueError("recovery historical committed batches are crossed")

        active_pair_ids = _snapshot_pair_ids(active_snapshot_document)
        planned_active_ids = _string_list(
            batches[-1].get("candidate_schedule_pair_ids"), "recovery active pair IDs"
        )
        if active_pair_ids != planned_active_ids:
            raise ValueError("recovery active candidate schedule is crossed")
        durable_active_ids = _string_list(
            batches[-1].get("durable_terminal_pair_ids"), "recovery active durable IDs"
        )
        if durable_active_ids != active_pair_ids[: len(durable_active_ids)]:
            raise ValueError("recovery active durable terminals are not a canonical prefix")
        terminal_payloads: list[dict[str, object]] = []
        for pair_id in durable_active_ids:
            if pair_id in failed_ledger.terminal_payload_by_pair_id:
                terminal_payloads.append(failed_ledger.terminal_payload_by_pair_id[pair_id])
            elif pair_id in prefix.terminal_by_pair_id:
                terminal_payloads.append(
                    {
                        "pair_id": pair_id,
                        "terminal_row": prefix.terminal_by_pair_id[pair_id],
                        "variant_evidence": prefix.evidence_by_pair_id[pair_id],
                    }
                )
            else:
                raise ValueError("recovery active terminal evidence is missing")

        unresolved_rows = _mapping_sequence(
            recovery_snapshot.get("unresolved_pairs"), "recovery unresolved pairs"
        )
        unresolved_ids_raw = tuple(
            _non_empty(row.get("pair_id"), "recovery unresolved pair id")
            for row in unresolved_rows
        )
        if len(unresolved_ids_raw) != 2:
            raise ValueError("recovery requires exactly two unresolved pair IDs")
        unresolved_pair_ids = cast(tuple[str, str], unresolved_ids_raw)
        next_pair_ids = active_pair_ids[len(durable_active_ids) : len(durable_active_ids) + 2]
        if next_pair_ids != list(unresolved_pair_ids):
            raise ValueError("recovery unresolved pair IDs are not the next canonical plans")

        durable_prefix_ids = _string_list(
            recovery_snapshot.get("durable_prefix_terminals"), "durable prefix terminal IDs"
        )
        if durable_prefix_ids != list(prefix.ordered_terminal_ids):
            raise ValueError("recovery durable prefix terminal inventory is crossed")
        durable_suffix_refs = _mapping_sequence(
            recovery_snapshot.get("durable_suffix_terminals"), "durable suffix terminal refs"
        )
        if len(durable_suffix_refs) != len(failed_ledger.durable_pair_ids):
            raise ValueError("recovery durable suffix denominator is crossed")
        for ref, pair_id in zip(durable_suffix_refs, failed_ledger.durable_pair_ids, strict=True):
            terminal_payload = failed_ledger.terminal_payload_by_pair_id[pair_id]
            if (
                ref.get("pair_id") != pair_id
                or ref.get("terminal_evidence_sha256") != _sha256_json(terminal_payload)
            ):
                raise ValueError("recovery durable suffix terminal hash is crossed")

        qualification_ref_raw = _mapping(artifact_refs.get("qualification"), "qualification ref")
        qualification_artifact = SegmentedQualificationArtifactRef(
            path=Path(_non_empty(qualification_ref_raw.get("path"), "qualification path")),
            sha256=_non_empty(qualification_ref_raw.get("sha256"), "qualification hash"),
        )
        _validated_concurrency_qualification_bytes(qualification_artifact)
        protected = {
            "frozen_prefix_path": cutover_request.frozen_prefix_workspace,
            "frozen_prefix_inventory": frozen_inventory,
            "failed_continuation_path": failed_continuation,
            "failed_continuation_inventory": failed_inventory,
            "artifact_refs": artifact_refs,
            "recovery_plan_sha256": request.recovery_plan_sha256,
            "authorization_sha256": request.authorization_sha256,
        }
        return _ValidatedRecoveryInputs(
            plan=plan,
            authorization=authorization,
            cutover_request=cutover_request,
            prefix=prefix,
            config=config,
            prepared=prepared,
            failed_continuation_identity=failed_identity,
            failed_ledger=failed_ledger,
            historical_chunks=tuple(historical_chunks),
            snapshot_document_by_time_step=snapshot_document_by_time_step,
            active_snapshot_document=active_snapshot_document,
            active_terminal_payloads=tuple(terminal_payloads),
            qualification_artifact=qualification_artifact,
            unresolved_pair_ids=unresolved_pair_ids,
            imported_durable_terminal_count=len(durable_prefix_ids) + len(durable_suffix_refs),
            protected_inventories=protected,
        )

    def _validate_authorization(
        self,
        request: SegmentedRecoveryExecutionRequest,
        plan: Mapping[str, object],
        authorization: Mapping[str, object],
    ) -> None:
        if set(authorization) != _AUTHORIZATION_FIELDS:
            raise ValueError("human authorization fields are missing or extra")
        if (
            authorization.get("schema_version") != _RECOVERY_AUTHORIZATION_SCHEMA
            or authorization.get("scope") != _RECOVERY_SCOPE
            or authorization.get("retry_authorized") is not True
            or authorization.get("production_deploy_eligible") is not False
        ):
            raise ValueError("human authorization scope is not exact")
        authorization_id = _non_empty(
            authorization.get("authorization_id"), "human authorization id"
        )
        if _RECOVERY_ID.fullmatch(authorization_id) is None:
            raise ValueError("human authorization id contains unsupported characters")
        _safe_reference(
            _non_empty(
                authorization.get("authorization_reference"),
                "human authorization reference",
            )
        )
        authorized_at = _utc_datetime(
            authorization.get("authorized_at"), "human authorization timestamp"
        )
        expires_at = _utc_datetime(
            authorization.get("expires_at"), "human authorization expiry"
        )
        now = self._now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("recovery clock must be timezone-aware")
        now = now.astimezone(timezone.utc)
        if expires_at <= authorized_at or now > expires_at:
            raise ValueError("human authorization is expired")
        if authorized_at > now:
            raise ValueError("human authorization timestamp is in the future")

        identity = _mapping(plan.get("recovery_identity"), "recovery plan identity")
        execution = _mapping(plan.get("execution_contract"), "recovery execution contract")
        accounting = _mapping(plan.get("accounting"), "recovery accounting")
        snapshot = _mapping(plan.get("recovery_snapshot"), "recovery snapshot")
        unresolved = _mapping_sequence(snapshot.get("unresolved_pairs"), "recovery unresolved pairs")
        unresolved_ids = [
            _non_empty(row.get("pair_id"), "recovery unresolved pair id")
            for row in unresolved
        ]
        if authorization.get("recovery_plan_sha256") != request.recovery_plan_sha256:
            raise ValueError("human authorization recovery plan binding is crossed")
        if authorization.get("recovery_plan_identity_hash") != identity.get("identity_hash"):
            raise ValueError("human authorization recovery plan identity is crossed")
        if (
            authorization.get("failed_continuation_identity_hash")
            != identity.get("failed_continuation_identity_hash")
        ):
            raise ValueError("human authorization failed continuation binding is crossed")
        if authorization.get("unresolved_pair_ids") != unresolved_ids or len(unresolved_ids) != 2:
            raise ValueError("human authorization unresolved pair order is crossed")
        if (
            authorization.get("configured_max_concurrency")
            != FULL_POOL_SEGMENTED_MAX_CONCURRENCY
            or execution.get("configured_max_concurrency")
            != FULL_POOL_SEGMENTED_MAX_CONCURRENCY
        ):
            raise ValueError("human authorization concurrency contract is crossed")
        if (
            authorization.get("prompt_version") != execution.get("prompt_version")
            or authorization.get("provider_contract_sha256")
            != execution.get("provider_contract_sha256")
            or authorization.get("prompt_contract_sha256")
            != execution.get("prompt_contract_sha256")
            or authorization.get("requested_model") != FULL_POOL_FORMAL_REQUESTED_MODEL
            or authorization.get("required_observed_model")
            != FULL_POOL_FORMAL_REQUIRED_OBSERVED_MODEL
            or authorization.get("maximum_attempts_per_dispatch") != 3
        ):
            raise ValueError("human authorization Provider model or P0 request contract is crossed")
        if (
            authorization.get("uncertainty_physical_charge") != 6
            or authorization.get("uncertainty_physical_charge")
            != accounting.get("unresolved_uncertainty_physical_charge")
            or authorization.get("logical_cap") != FULL_POOL_SEGMENTED_LOGICAL_CAP
            or authorization.get("logical_cap") != accounting.get("logical_cap")
            or authorization.get("physical_cap") != FULL_POOL_SEGMENTED_PHYSICAL_CAP
            or authorization.get("physical_cap") != accounting.get("physical_cap")
            or authorization.get("historical_logical_count")
            != accounting.get("historical_logical_count")
            or authorization.get("historical_physical_attempts")
            != accounting.get("historical_physical_attempts")
        ):
            raise ValueError("human authorization uncertainty charge or cap contract is crossed")
        if (
            authorization.get("recovery_id") != request.recovery_id
            or authorization.get("recovery_workspace")
            != str(request.recovery_workspace)
        ):
            raise ValueError("human authorization recovery identity or workspace is crossed")


def _read_failed_ledger(
    path: Path,
    *,
    continuation: Path,
    expected_identity_hash: str,
) -> _FailedLedgerReplay:
    dispatched, durable, physical, source_anchor = _replay_continuation_ledger(
        path,
        expected_identity_hash=expected_identity_hash,
    )
    if source_anchor is not None:
        raise ValueError("failed continuation unexpectedly exposes source-v2")
    records: list[dict[str, object]] = []
    terminals: dict[str, dict[str, object]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        record = _mapping(json.loads(line), "failed continuation ledger record")
        event_type = record.get("event_type")
        payload = _mapping(record.get("payload"), "failed continuation ledger payload")
        if event_type == "kernel_batch_snapshot":
            relative = _safe_relative_path(
                payload.get("snapshot_path"), "failed kernel snapshot path"
            )
            document = _read_json(continuation / relative)
            if _sha256_json(document) != payload.get("snapshot_hash"):
                raise ValueError("failed kernel snapshot hash is crossed")
            records.append(
                {
                    "record_type": "snapshot",
                    **payload,
                    "snapshot_document": document,
                }
            )
        elif event_type == "kernel_batch_committed":
            records.append(
                {
                    "record_type": "event",
                    "sequence": len(records) + 1,
                    "event_type": "batch_committed",
                    "event_identity": payload.get("event_identity"),
                    "batch_snapshot_hash": payload.get("batch_snapshot_hash"),
                    "payload": payload.get("payload"),
                }
            )
        elif event_type == "pair_terminal":
            pair_id = _non_empty(payload.get("pair_id"), "failed durable pair id")
            if pair_id in terminals:
                raise ValueError("failed continuation durable terminal is duplicated")
            terminals[pair_id] = payload
    if list(terminals) != durable:
        raise ValueError("failed continuation terminal payload order is crossed")
    committed_count = sum(
        record.get("record_type") == "event"
        and record.get("event_type") == "batch_committed"
        for record in records
    )
    return _FailedLedgerReplay(
        kernel_replay={
            "status": {"committed_batch_count": committed_count},
            "records": records,
        },
        terminal_payload_by_pair_id=terminals,
        dispatched_pair_ids=tuple(dispatched),
        durable_pair_ids=tuple(durable),
        wave_physical_attempts=physical,
    )


def _validate_persisted_recovery_source_inputs(
    *,
    source_root: Path,
    recovery_workspace: Path,
    recovery_plan_sha256: str,
    authorization_sha256: str,
) -> _ValidatedRecoveryInputs:
    """Reclose source-copied recovery artifacts without re-evaluating live authorization time."""
    copied_plan = _require_regular_file(
        source_root / "recovery-plan.json", "source-v2 recovery plan copy"
    )
    if _sha256_file(copied_plan) != recovery_plan_sha256:
        raise ValueError("source-v2 recovery plan hash is crossed")
    plan_envelope = _read_json(copied_plan)
    plan = _mapping(plan_envelope.get("payload"), "source-v2 recovery plan payload")
    plan_identity = _mapping(plan.get("recovery_identity"), "source-v2 recovery plan identity")
    original_plan = _require_regular_file(
        Path(_non_empty(plan_identity.get("recovery_root"), "recovery plan root"))
        / "recovery-plan.json",
        "original persisted recovery plan",
    )
    if (
        original_plan.read_bytes() != copied_plan.read_bytes()
        or _sha256_file(original_plan) != recovery_plan_sha256
    ):
        raise ValueError("source-v2 recovery plan copy differs from its persisted origin")

    copied_authorization = _require_regular_file(
        source_root / "human-authorization.json", "source-v2 human authorization copy"
    )
    if _sha256_file(copied_authorization) != authorization_sha256:
        raise ValueError("source-v2 human authorization hash is crossed")
    authorization_envelope = _read_json(copied_authorization)
    authorization = _mapping(
        authorization_envelope.get("payload"), "source-v2 human authorization payload"
    )
    authorized_at = _utc_datetime(
        authorization.get("authorized_at"), "source-v2 authorization timestamp"
    )
    request = SegmentedRecoveryExecutionRequest.model_construct(
        recovery_plan_path=original_plan,
        recovery_plan_sha256=recovery_plan_sha256,
        authorization_path=copied_authorization,
        authorization_sha256=authorization_sha256,
        recovery_id=_non_empty(authorization.get("recovery_id"), "source-v2 recovery id"),
        recovery_workspace=recovery_workspace,
    )
    return FullPoolSegmentedRecovery(now=lambda: authorized_at)._validated_inputs(request)


def _snapshot_documents(replay: Mapping[str, object]) -> dict[int, dict[str, object]]:
    documents: dict[int, dict[str, object]] = {}
    records = replay.get("records", [])
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise TypeError("kernel replay records must be a sequence")
    for raw in records:
        record = _mapping(raw, "kernel replay record")
        if record.get("record_type") != "snapshot":
            continue
        document = _mapping(record.get("snapshot_document"), "kernel snapshot document")
        identity = _mapping(document.get("snapshot_identity"), "kernel snapshot identity")
        time_step = _non_negative_int(identity.get("time_step"), "kernel snapshot time_step")
        if time_step in documents:
            raise ValueError("kernel snapshot time_step is duplicated")
        documents[time_step] = document
    return documents


def _snapshot_pair_ids(document: Mapping[str, object]) -> list[str]:
    payload = _mapping(document.get("payload"), "active snapshot payload")
    plans = [
        plan
        for message in _mapping_sequence(payload.get("messages"), "active snapshot messages")
        for plan in _mapping_sequence(
            message.get("selected_pair_plans"), "active selected pair plans"
        )
    ]
    plans.sort(
        key=lambda row: _non_negative_int(
            row.get("pair_schedule_position"), "active pair schedule position"
        )
    )
    return [_non_empty(row.get("pair_id"), "active pair id") for row in plans]


def _recovery_documents(
    request: SegmentedRecoveryExecutionRequest,
    inputs: _ValidatedRecoveryInputs,
) -> _RecoveryDocuments:
    plan_identity = _mapping(inputs.plan.get("recovery_identity"), "recovery identity")
    accounting = _mapping(inputs.plan.get("accounting"), "recovery accounting")
    manifest = {
        "schema_version": _RECOVERY_MANIFEST_SCHEMA,
        "recovery_id": request.recovery_id,
        "recovery_workspace": str(request.recovery_workspace),
        "recovery_plan_sha256": request.recovery_plan_sha256,
        "recovery_plan_identity_hash": plan_identity["identity_hash"],
        "human_authorization_sha256": request.authorization_sha256,
        "failed_continuation_identity_hash": plan_identity[
            "failed_continuation_identity_hash"
        ],
        "prefix_identity_hash": inputs.prefix.run_identity.get("identity_hash"),
        "unresolved_pair_ids": list(inputs.unresolved_pair_ids),
        "imported_durable_terminal_count": inputs.imported_durable_terminal_count,
        "expected_horizon": inputs.config.horizon,
        "expected_logical_count": inputs.config.sample_size * len(inputs.config.messages),
        "historical_logical_count": accounting["historical_logical_count"],
        "historical_physical_attempts": accounting["historical_physical_attempts"],
        "unresolved_uncertainty_physical_charge": accounting[
            "unresolved_uncertainty_physical_charge"
        ],
        "logical_cap": FULL_POOL_SEGMENTED_LOGICAL_CAP,
        "physical_cap": FULL_POOL_SEGMENTED_PHYSICAL_CAP,
        "max_concurrency": FULL_POOL_SEGMENTED_MAX_CONCURRENCY,
        "production_deploy_eligible": False,
    }
    manifest_sha256 = _sha256_json(manifest)
    identity_body = {
        "schema_version": _RECOVERY_IDENTITY_SCHEMA,
        "recovery_id": request.recovery_id,
        "workspace": str(request.recovery_workspace),
        "run_id": f"recovery-{request.recovery_id}",
        "recovery_cutoff_manifest_sha256": manifest_sha256,
        "recovery_plan_sha256": request.recovery_plan_sha256,
        "human_authorization_sha256": request.authorization_sha256,
        "failed_continuation_identity_hash": plan_identity[
            "failed_continuation_identity_hash"
        ],
        "prefix_identity_hash": inputs.prefix.run_identity.get("identity_hash"),
        "provider_contract": inputs.prefix.provider_contract,
        "prompt_contract": inputs.prefix.prompt_contract,
        "max_concurrency": FULL_POOL_SEGMENTED_MAX_CONCURRENCY,
        "logical_cap": FULL_POOL_SEGMENTED_LOGICAL_CAP,
        "physical_cap": FULL_POOL_SEGMENTED_PHYSICAL_CAP,
        "production_deploy_eligible": False,
    }
    identity = {**identity_body, "identity_hash": _sha256_json(identity_body)}
    return _RecoveryDocuments(
        identity=identity,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
    )


def _initialize_recovery_workspace(
    request: SegmentedRecoveryExecutionRequest,
    inputs: _ValidatedRecoveryInputs,
    documents: _RecoveryDocuments,
) -> _RecoveryRuntime:
    _create_workspace(request.recovery_workspace)
    _atomic_write_json(request.recovery_workspace / _IDENTITY_FILE, documents.identity)
    _atomic_write_json(
        request.recovery_workspace / _MANIFEST_FILE,
        {
            "schema_version": _RECOVERY_MANIFEST_ENVELOPE_SCHEMA,
            "manifest": documents.manifest,
            "manifest_sha256": documents.manifest_sha256,
        },
    )
    identity_hash = cast(str, documents.identity["identity_hash"])
    ledger = _ContinuationLedger(
        request.recovery_workspace,
        continuation_identity_hash=identity_hash,
    )
    ledger.append(
        "kernel_recovery_started",
        {
            "recovery_id": request.recovery_id,
            "recovery_plan_sha256": request.recovery_plan_sha256,
            "human_authorization_sha256": request.authorization_sha256,
            "unresolved_pair_ids": list(inputs.unresolved_pair_ids),
            "max_concurrency": FULL_POOL_SEGMENTED_MAX_CONCURRENCY,
        },
    )
    journal = _SegmentedKernelJournal(
        request.recovery_workspace,
        run_id=cast(str, documents.identity["run_id"]),
        identity_hash=identity_hash,
        ledger=ledger,
        base_time_step=0,
        record_runtime_events=True,
    )
    spool = _ConcurrentRuntimeBatchSpool(
        request.recovery_workspace,
        run_id=journal.run_id,
        identity_hash=journal.identity_hash,
        terminal_variants=("primary",),
        base_time_step=0,
    )
    for chunk in inputs.historical_chunks:
        document = inputs.snapshot_document_by_time_step.get(chunk.time_step)
        if document is None:
            raise ValueError("historical recovery snapshot document is missing")
        snapshot_ref = journal.persist_snapshot(
            snapshot_type="batch_plan",
            snapshot_identity={"time_step": chunk.time_step},
            payload=_mapping(document.get("payload"), "historical snapshot payload"),
        )
        if snapshot_ref.get("snapshot_hash") != chunk.batch_snapshot_hash:
            raise ValueError("imported historical snapshot hash changed")
        spool_ref = spool.prepare_batch(
            time_step=chunk.time_step,
            batch_snapshot_hash=chunk.batch_snapshot_hash,
            commit=chunk.commit,
            candidate_rows=chunk.candidate_rows,
            result_rows=chunk.result_rows,
            terminal_rows=chunk.terminal_rows,
            variant_evidence_rows=chunk.variant_evidence_rows,
        )
        committed_ids = _string_list(
            chunk.commit.get("committed_primary_positive_user_ids"),
            "imported committed feedback",
        )
        journal.append(
            event_type="batch_committed",
            event_identity={"time_step": chunk.time_step},
            payload={
                "time_step": chunk.time_step,
                "committed_user_ids": committed_ids,
                "committed_user_count": len(committed_ids),
                "batch_pair_count": len(chunk.result_rows),
                "batch_spool_chunk": spool_ref,
            },
            batch_snapshot_hash=chunk.batch_snapshot_hash,
        )
        spool.publish_prepared(spool_ref)

    state = _ConcurrentRuntimeKernelState(
        cohort=inputs.prepared.cohort,
        exposed_by_message={message.message_id: set() for message in inputs.config.messages},
        campaign_engaged_user_ids=set(),
    )
    kernel = _ConcurrentRuntimeKernel.primary_only(
        config=inputs.config,
        state=state,
        base_network_by_user=inputs.prepared.base_network_by_user,
        neighbors_by_user=inputs.prepared.neighbors_by_user,
        journal=cast(ConcurrentExecutionJournal, journal),
        spool_base_time_step=0,
    )
    for chunk in inputs.historical_chunks:
        kernel._restore_spooled_chunk(chunk)

    active_document = inputs.active_snapshot_document
    active_identity = _mapping(
        active_document.get("snapshot_identity"), "active snapshot identity"
    )
    active_time_step = _non_negative_int(
        active_identity.get("time_step"), "active snapshot time_step"
    )
    kernel.plan_batch()
    generated_snapshot = next(
        (
            _mapping(record.get("snapshot_document"), "generated active snapshot")
            for record in reversed(journal.records)
            if record.get("record_type") == "snapshot"
        ),
        None,
    )
    if generated_snapshot != active_document:
        raise ValueError("recovered same-batch context differs from the persisted snapshot")
    plans = kernel.pending_plans()
    for terminal_payload, plan in zip(
        inputs.active_terminal_payloads,
        plans,
        strict=False,
    ):
        pair_id = _non_empty(terminal_payload.get("pair_id"), "imported active pair id")
        if pair_id != plan.pair_id:
            raise ValueError("imported active terminals are not canonical")
        terminal_row = _mapping(
            terminal_payload.get("terminal_row"), "imported active terminal row"
        )
        variant_evidence = _mapping(
            terminal_payload.get("variant_evidence"), "imported active variant evidence"
        )
        kernel.start_pair(plan)
        kernel.register_terminal(
            plan=plan,
            decision_variant="primary",
            terminal_row=terminal_row,
            variant_evidence=variant_evidence,
        )
        kernel.close_primary_pair(
            plan,
            _PrimaryOnlyConcurrentRuntimeConsumer._primary_result_row(
                plan, terminal_row
            ),
        )
    ledger.append(
        "kernel_recovery_imported",
        {
            "durable_terminal_count": inputs.imported_durable_terminal_count,
            "committed_batch_count": len(inputs.historical_chunks),
            "active_time_step": active_time_step,
        },
    )
    return _RecoveryRuntime(
        ledger=ledger,
        journal=journal,
        spool=spool,
        kernel=kernel,
        state=state,
    )


def _register_results(
    kernel: _ConcurrentRuntimeKernel,
    plans: Sequence[_PairExecutionPlan],
    results: Mapping[str, _WorkerResult],
) -> None:
    if [plan.pair_id for plan in plans] != list(results):
        raise ValueError("recovery result order is crossed with the canonical plans")
    for plan in plans:
        result = results[plan.pair_id]
        kernel.start_pair(plan)
        kernel.register_terminal(
            plan=plan,
            decision_variant="primary",
            terminal_row=result.terminal_row,
            variant_evidence=result.variant_evidence,
        )
        kernel.close_primary_pair(
            plan,
            _PrimaryOnlyConcurrentRuntimeConsumer._primary_result_row(
                plan, result.terminal_row
            ),
        )


def _recovery_accounting(
    inputs: _ValidatedRecoveryInputs,
    *,
    logical_count: int,
    fresh_logical_count: int,
    retry_physical_attempts: int,
    continuation_physical_attempts: int,
) -> dict[str, object]:
    accounting = _mapping(inputs.plan.get("accounting"), "recovery accounting")
    historical_physical = _non_negative_int(
        accounting.get("historical_physical_attempts"), "historical physical attempts"
    )
    uncertainty = _non_negative_int(
        accounting.get("unresolved_uncertainty_physical_charge"),
        "uncertainty physical charge",
    )
    return {
        "logical_cap": FULL_POOL_SEGMENTED_LOGICAL_CAP,
        "historical_logical_count": accounting["historical_logical_count"],
        "logical_retry_charge": 0,
        "fresh_logical_count": fresh_logical_count,
        "logical_count": logical_count,
        "physical_cap": FULL_POOL_SEGMENTED_PHYSICAL_CAP,
        "historical_physical_attempts": historical_physical,
        "unresolved_uncertainty_physical_charge": uncertainty,
        "retry_actual_physical_attempts": retry_physical_attempts,
        "continuation_actual_physical_attempts": continuation_physical_attempts,
        "physical_attempt_count": (
            historical_physical
            + uncertainty
            + retry_physical_attempts
            + continuation_physical_attempts
        ),
    }


def _recovery_lineage(
    request: SegmentedRecoveryExecutionRequest,
    inputs: _ValidatedRecoveryInputs,
    documents: _RecoveryDocuments,
) -> dict[str, object]:
    failed_lineage = _mapping(inputs.plan.get("failed_run_lineage"), "failed lineage")
    plan_identity = _mapping(inputs.plan.get("recovery_identity"), "recovery identity")
    return {
        "failed_v1_run_identity_hash": failed_lineage["v1_run_identity_hash"],
        "failed_continuation_identity_hash": plan_identity[
            "failed_continuation_identity_hash"
        ],
        "failed_continuation_ledger_sha256": failed_lineage[
            "continuation_ledger_sha256"
        ],
        "recovery_plan_sha256": request.recovery_plan_sha256,
        "recovery_plan_identity_hash": plan_identity["identity_hash"],
        "human_authorization_sha256": request.authorization_sha256,
        "qualification_artifact_sha256": failed_lineage[
            "qualification_artifact_sha256"
        ],
        "recovery_identity_hash": documents.identity["identity_hash"],
        "unresolved_pair_ids": list(inputs.unresolved_pair_ids),
        "configured_max_concurrency": FULL_POOL_SEGMENTED_MAX_CONCURRENCY,
        "provider_calls": 0,
        "production_deploy_eligible": False,
    }


def _persist_partial_result(
    request: SegmentedRecoveryExecutionRequest,
    inputs: _ValidatedRecoveryInputs,
    documents: _RecoveryDocuments,
    runtime: _RecoveryRuntime,
    *,
    status: Literal["resumable", "reconciliation_required"],
    retry_physical_attempts: int,
    continuation_physical_attempts: int,
    fresh_logical_count: int,
    unknown_pair_ids: Sequence[str],
) -> SegmentedRecoveryExecutionResult:
    del runtime
    accounting = _recovery_accounting(
        inputs,
        logical_count=(
            _non_negative_int(
                _mapping(inputs.plan.get("accounting"), "recovery accounting").get(
                    "historical_logical_count"
                ),
                "historical logical count",
            )
            + fresh_logical_count
        ),
        fresh_logical_count=fresh_logical_count,
        retry_physical_attempts=retry_physical_attempts,
        continuation_physical_attempts=continuation_physical_attempts,
    )
    result = SegmentedRecoveryExecutionResult(
        status=status,
        workspace_root=request.recovery_workspace,
        recovery_identity_hash=cast(str, documents.identity["identity_hash"]),
        logical_count=cast(int, accounting["logical_count"]),
        historical_physical_attempts=cast(
            int, accounting["historical_physical_attempts"]
        ),
        uncertainty_physical_charge=cast(
            int, accounting["unresolved_uncertainty_physical_charge"]
        ),
        retry_physical_attempts=retry_physical_attempts,
        continuation_physical_attempts=continuation_physical_attempts,
        physical_attempt_count=cast(int, accounting["physical_attempt_count"]),
        imported_durable_terminal_count=inputs.imported_durable_terminal_count,
        recovered_pair_ids=_new_recovered_pair_ids(
            request.recovery_workspace / _LEDGER_FILE,
            documents.identity["identity_hash"],
            inputs.unresolved_pair_ids,
        ),
        unknown_pair_ids=tuple(unknown_pair_ids),
        provider_calls=0,
        production_deploy_eligible=False,
    )
    _atomic_write_json(
        request.recovery_workspace / _CONTINUATION_STATUS_FILE,
        {
            "schema_version": "full-pool-segmented-continuation-status-v1",
            "lifecycle": status,
            "manifest_sha256": documents.manifest_sha256,
            "durable_prefix_terminal_count": len(inputs.prefix.terminal_by_pair_id),
            "concurrent_suffix_terminal_count": (
                inputs.imported_durable_terminal_count
                - len(inputs.prefix.terminal_by_pair_id)
                + fresh_logical_count
            ),
            "committed_feedback_user_ids": [],
            "unknown_pair_ids": list(unknown_pair_ids),
            "logical_count": result.logical_count,
            "physical_attempt_count": result.physical_attempt_count,
            "terminal_rows_relative_path": None,
            "terminal_rows_sha256": None,
            "source_root_relative_path": None,
            "source_manifest_sha256": None,
            "production_deploy_eligible": False,
        },
    )
    _write_recovery_status(request, result)
    return result


def _new_wave_physical_attempts(path: Path, identity_hash: object) -> int:
    try:
        _dispatched, _durable, physical, _anchor = _replay_continuation_ledger(
            path,
            expected_identity_hash=_non_empty(identity_hash, "recovery identity hash"),
            allow_inflight_wave=True,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return 0
    return physical


def _new_fresh_dispatch_count(
    path: Path,
    identity_hash: object,
    recovery_pair_ids: Sequence[str],
) -> int:
    try:
        dispatched, _durable, _physical, _anchor = _replay_continuation_ledger(
            path,
            expected_identity_hash=_non_empty(identity_hash, "recovery identity hash"),
            allow_inflight_wave=True,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return 0
    retry_ids = set(recovery_pair_ids)
    return sum(pair_id not in retry_ids for pair_id in dispatched)


def _new_recovered_pair_ids(
    path: Path,
    identity_hash: object,
    recovery_pair_ids: Sequence[str],
) -> tuple[str, ...]:
    try:
        _dispatched, durable, _physical, _anchor = _replay_continuation_ledger(
            path,
            expected_identity_hash=_non_empty(identity_hash, "recovery identity hash"),
            allow_inflight_wave=True,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return ()
    durable_set = set(durable)
    return tuple(pair_id for pair_id in recovery_pair_ids if pair_id in durable_set)


def _new_unknown_pair_ids(path: Path, identity_hash: object) -> tuple[str, ...]:
    try:
        dispatched, durable, _physical, _anchor = _replay_continuation_ledger(
            path,
            expected_identity_hash=_non_empty(identity_hash, "recovery identity hash"),
            allow_inflight_wave=True,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return ()
    durable_set = set(durable)
    return tuple(pair_id for pair_id in dispatched if pair_id not in durable_set)


def _write_recovery_status(
    request: SegmentedRecoveryExecutionRequest,
    result: SegmentedRecoveryExecutionResult,
) -> None:
    _atomic_write_json(
        request.recovery_workspace / _RECOVERY_STATUS_FILE,
        {
            "schema_version": _RECOVERY_STATUS_SCHEMA,
            "result": result.model_dump(mode="json"),
        },
    )


def _load_existing_recovery(
    request: SegmentedRecoveryExecutionRequest,
    inputs: _ValidatedRecoveryInputs,
    documents: _RecoveryDocuments,
) -> SegmentedRecoveryExecutionResult:
    if request.recovery_workspace.is_symlink() or not request.recovery_workspace.is_dir():
        raise ValueError("existing recovery workspace must be one real directory")
    if _read_json(request.recovery_workspace / _IDENTITY_FILE) != documents.identity:
        raise ValueError("existing recovery identity is crossed")
    manifest_envelope = _read_json(request.recovery_workspace / _MANIFEST_FILE)
    if manifest_envelope != {
        "schema_version": _RECOVERY_MANIFEST_ENVELOPE_SCHEMA,
        "manifest": documents.manifest,
        "manifest_sha256": documents.manifest_sha256,
    }:
        raise ValueError("existing recovery cutoff manifest is crossed")
    source = request.recovery_workspace / "source-v2"
    staging = request.recovery_workspace / ".source-v2.staging"
    if not source.exists() and staging.is_dir():
        _validate_recovered_source_directory(
            staging,
            request=request,
            inputs=inputs,
            documents=documents,
            require_ledger_anchor=True,
        )
        os.replace(staging, source)
    if source.is_dir():
        result = _validate_recovered_source_directory(
            source,
            request=request,
            inputs=inputs,
            documents=documents,
            require_ledger_anchor=True,
        )
        manifest = _read_json(source / "manifest.json")
        complete_status = _mapping(
            manifest.get("complete_status"), "recovered complete status"
        )
        standard_status = {
            "schema_version": "full-pool-segmented-continuation-status-v1",
            "lifecycle": "complete",
            "manifest_sha256": documents.manifest_sha256,
            **complete_status,
            "source_manifest_sha256": result.source_manifest_sha256,
        }
        _atomic_write_json(
            request.recovery_workspace / _CONTINUATION_STATUS_FILE,
            standard_status,
        )
        _write_recovery_status(request, result)
        _assert_protected_unchanged(request, inputs)
        return result
    status_path = request.recovery_workspace / _RECOVERY_STATUS_FILE
    if status_path.is_file():
        dispatched, durable, new_physical, anchor = _replay_continuation_ledger(
            request.recovery_workspace / _LEDGER_FILE,
            expected_identity_hash=cast(str, documents.identity["identity_hash"]),
        )
        if anchor is not None:
            raise ValueError("partial recovery status unexpectedly anchors source-v2")
        status = _read_json(status_path)
        if set(status) != {"schema_version", "result"} or status.get(
            "schema_version"
        ) != _RECOVERY_STATUS_SCHEMA:
            raise ValueError("recovery status fields or schema are crossed")
        result = SegmentedRecoveryExecutionResult.model_validate(status.get("result"))
        expected_unknown = tuple(
            pair_id for pair_id in dispatched if pair_id not in set(durable)
        )
        if (
            result.workspace_root != request.recovery_workspace
            or result.recovery_identity_hash != documents.identity["identity_hash"]
            or result.status == "complete"
            or result.unknown_pair_ids != expected_unknown
            or (
                result.physical_attempt_count
                - result.historical_physical_attempts
                - result.uncertainty_physical_charge
            )
            != new_physical
        ):
            raise ValueError("recovery status is crossed with its identity or ledger")
        _assert_protected_unchanged(request, inputs)
        return result
    raise ValueError("existing recovery workspace has no closed or fail-closed status")


def _validate_recovered_source_directory(
    source: Path,
    *,
    request: SegmentedRecoveryExecutionRequest,
    inputs: _ValidatedRecoveryInputs,
    documents: _RecoveryDocuments,
    require_ledger_anchor: bool,
) -> SegmentedRecoveryExecutionResult:
    if source.is_symlink() or not source.is_dir():
        raise ValueError("recovered source-v2 must be one real directory")
    manifest_path = source / "manifest.json"
    manifest = _read_json(manifest_path)
    expected_fields = {
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
        "concurrency_qualification_artifact_sha256",
        "max_concurrency",
        "production_deploy_eligible",
        "recovery_lineage",
        "recovery_accounting",
    }
    if (
        set(manifest) != expected_fields
        or manifest.get("schema_version") != "full-pool-segmented-source-v2"
        or manifest.get("cutoff_manifest_sha256") != documents.manifest_sha256
        or manifest.get("continuation_identity_hash")
        != documents.identity["identity_hash"]
        or manifest.get("max_concurrency") != FULL_POOL_SEGMENTED_MAX_CONCURRENCY
        or manifest.get("production_deploy_eligible") is not False
    ):
        raise ValueError("recovered source-v2 manifest fields or identity are crossed")
    lineage = _mapping(manifest.get("recovery_lineage"), "recovery source lineage")
    if lineage != _recovery_lineage(request, inputs, documents):
        raise ValueError("recovered source-v2 lineage is crossed")
    accounting = _mapping(
        manifest.get("recovery_accounting"), "recovery source accounting"
    )
    expected_logical = inputs.config.sample_size * len(inputs.config.messages)
    if accounting != _recovery_accounting(
        inputs,
        logical_count=expected_logical,
        fresh_logical_count=cast(int, accounting.get("fresh_logical_count")),
        retry_physical_attempts=cast(
            int, accounting.get("retry_actual_physical_attempts")
        ),
        continuation_physical_attempts=cast(
            int, accounting.get("continuation_actual_physical_attempts")
        ),
    ):
        raise ValueError("recovered source-v2 accounting is crossed")
    artifact_refs = _mapping_sequence(manifest.get("artifacts"), "source artifacts")
    expected_names = {
        "candidate_rows.jsonl",
        "pair_rows.jsonl",
        "terminal_rows.jsonl",
        "steps.jsonl",
        SEGMENTED_CONCURRENCY_QUALIFICATION_FILE,
        "recovery-plan.json",
        "human-authorization.json",
    }
    observed_names: set[str] = set()
    for ref in artifact_refs:
        relative = _non_empty(ref.get("relative_path"), "source artifact path")
        if relative in observed_names or relative not in expected_names:
            raise ValueError("recovered source-v2 artifact inventory is crossed")
        observed_names.add(relative)
        path = source / relative
        if (
            path.is_symlink()
            or not path.is_file()
            or ref.get("sha256") != _sha256_file(path)
            or ref.get("byte_length") != path.stat().st_size
        ):
            raise ValueError("recovered source-v2 artifact hash is crossed")
    if observed_names != expected_names or {
        path.name for path in source.iterdir() if path.is_file()
    } != expected_names | {"manifest.json"}:
        raise ValueError("recovered source-v2 artifact set is not exact")
    if (source / "recovery-plan.json").read_bytes() != request.recovery_plan_path.read_bytes():
        raise ValueError("recovered source-v2 recovery plan copy is crossed")
    if (source / "human-authorization.json").read_bytes() != request.authorization_path.read_bytes():
        raise ValueError("recovered source-v2 human authorization copy is crossed")
    if _sha256_file(source / SEGMENTED_CONCURRENCY_QUALIFICATION_FILE) != inputs.qualification_artifact.sha256:
        raise ValueError("recovered source-v2 qualification copy is crossed")
    counts = _mapping(manifest.get("counts"), "recovered source counts")
    observed_counts = {
        "candidate_rows": _line_count(source / "candidate_rows.jsonl"),
        "pair_rows": _line_count(source / "pair_rows.jsonl"),
        "terminal_rows": _line_count(source / "terminal_rows.jsonl"),
        "steps": _line_count(source / "steps.jsonl"),
    }
    if counts != observed_counts or observed_counts["pair_rows"] != expected_logical or observed_counts[
        "terminal_rows"
    ] != expected_logical:
        raise ValueError("recovered source-v2 denominators are incomplete")
    source_manifest_sha256 = _sha256_file(manifest_path)
    if require_ledger_anchor:
        _dispatched, _durable, _physical, anchor = _replay_continuation_ledger(
            request.recovery_workspace / _LEDGER_FILE,
            expected_identity_hash=cast(str, documents.identity["identity_hash"]),
        )
        if anchor != {
            "source_manifest_sha256": source_manifest_sha256,
            "complete_status": manifest.get("complete_status"),
        }:
            raise ValueError("recovered source-v2 ledger anchor is crossed")
    return SegmentedRecoveryExecutionResult(
        status="complete",
        workspace_root=request.recovery_workspace,
        recovery_identity_hash=cast(str, documents.identity["identity_hash"]),
        source_root=request.recovery_workspace / "source-v2",
        source_manifest_sha256=source_manifest_sha256,
        logical_count=cast(int, accounting["logical_count"]),
        historical_physical_attempts=cast(
            int, accounting["historical_physical_attempts"]
        ),
        uncertainty_physical_charge=cast(
            int, accounting["unresolved_uncertainty_physical_charge"]
        ),
        retry_physical_attempts=cast(
            int, accounting["retry_actual_physical_attempts"]
        ),
        continuation_physical_attempts=cast(
            int, accounting["continuation_actual_physical_attempts"]
        ),
        physical_attempt_count=cast(int, accounting["physical_attempt_count"]),
        imported_durable_terminal_count=inputs.imported_durable_terminal_count,
        recovered_pair_ids=inputs.unresolved_pair_ids,
        unknown_pair_ids=(),
        provider_calls=0,
        production_deploy_eligible=False,
    )


def _assert_protected_unchanged(
    request: SegmentedRecoveryExecutionRequest,
    inputs: _ValidatedRecoveryInputs,
) -> None:
    protected = inputs.protected_inventories
    filesystem = LocalOperatorFilesystem()
    if filesystem.inventory(cast(Path, protected["frozen_prefix_path"])) != protected[
        "frozen_prefix_inventory"
    ]:
        raise ValueError("frozen prefix changed during recovery")
    if filesystem.inventory(cast(Path, protected["failed_continuation_path"])) != protected[
        "failed_continuation_inventory"
    ]:
        raise ValueError("failed continuation changed during recovery")
    for label, raw in _mapping(protected["artifact_refs"], "protected refs").items():
        _validate_file_ref(_mapping(raw, f"protected {label} ref"), label)
    if _sha256_file(request.recovery_plan_path) != protected["recovery_plan_sha256"]:
        raise ValueError("recovery plan changed during execution")
    if _sha256_file(request.authorization_path) != protected["authorization_sha256"]:
        raise ValueError("human authorization changed during execution")


def _validate_file_ref(ref: Mapping[str, object], label: str) -> None:
    if set(ref) != {"path", "sha256", "bytes"}:
        raise ValueError(f"{label} artifact reference fields are not exact")
    path = _require_regular_file(
        Path(_non_empty(ref.get("path"), f"{label} artifact path")),
        f"{label} artifact",
    )
    if ref.get("sha256") != _sha256_file(path) or ref.get("bytes") != path.stat().st_size:
        raise ValueError(f"{label} artifact changed after recovery planning")


def _safe_relative_path(value: object, context: str) -> Path:
    token = _non_empty(value, context)
    path = Path(token)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{context} escapes its workspace")
    return path


def _line_count(path: Path) -> int:
    with path.open(encoding="utf-8") as handle:
        return sum(bool(line.strip()) for line in handle)


def _string_list(value: object, context: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{context} must be a sequence")
    if not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{context} must contain non-empty strings")
    return list(value)


def _non_negative_int(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{context} must be a non-negative integer")
    return value


def _safe_reference(value: str) -> str:
    lowered = value.lower()
    if "\n" in value or "\r" in value or any(
        marker in lowered
        for marker in (
            "bearer ",
            "api_key",
            "access_token",
            "refresh_token",
            "password",
            "secret",
        )
    ):
        raise ValueError("human authorization reference contains credential material")
    return value


def _utc_datetime(value: object, context: str) -> datetime:
    token = _non_empty(value, context)
    try:
        parsed = datetime.fromisoformat(token.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{context} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{context} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _require_regular_file(path: Path, context: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{context} must be one persisted regular file")
    return path


def _read_json(path: Path) -> dict[str, object]:
    return _mapping(json.loads(path.read_text(encoding="utf-8")), str(path))


def _mapping(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{context} must be an object")
    return {str(key): item for key, item in value.items()}


def _mapping_sequence(value: object, context: str) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{context} must be a sequence")
    return [_mapping(item, context) for item in value]


def _non_empty(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be a non-empty string")
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
