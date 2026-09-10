"""Recovery resolver for the existing Study-owned primary runtime driver."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from . import concurrent_robustness_v2 as _v2
from ._concurrent_recovery_campaign import CampaignJournal, RecoveryCampaignError, _require_scope
from ._concurrent_recovery_judgment import RecoveryJudgmentV1, build_recovery_judgment
from ._concurrent_recovery_progress import CampaignProgress
from .concurrent_message_experiment import _PairExecutionPlan
from .decision import LLMDecisionAdapter


class RecoverySafePause(RuntimeError):
    """No new intent was written; the current reservation remains usable."""


def inherited_terminals(proposal: Mapping[str, Any], manifest: _v2.ConcurrentRobustnessManifestV2) -> dict[tuple[int, int], _v2._V2RealizedTerminal]:
    result: dict[tuple[int, int], _v2._V2RealizedTerminal] = {}
    for row in proposal["inherited_cells"]:
        index = row["cell_index"]
        cell = manifest.prompt_model_cells[index]
        scope = Path(row["ledger_path"]).parent
        identity = _v2._cell_ledger_identity(manifest=manifest, manifest_sha256=proposal["frozen_context"]["manifest_sha256"],
                                           cell_index=index, cell=cell, cell_scope=scope)
        ledger = _v2._V2PairLedger.read(scope, identity=identity)
        for terminal in ledger.terminals():
            result[index, terminal.pair_schedule_position] = terminal
    return result


def _coordinates(index: int, plan: _PairExecutionPlan) -> dict[str, Any]:
    return {"cell_index": index, "pair_schedule_position": plan.pair_schedule_position, "pair_id": plan.pair_id,
            "time_step": plan.time_step, "message_id": plan.message.message_id, "user_id": plan.user.user_id}


def _kernel(
    *, config: Any, prepared: Any, manifest: _v2.ConcurrentRobustnessManifestV2, cell_index: int,
    target: Path, epoch_identity: str, invocation_identity: str,
) -> tuple[_v2._ConcurrentRuntimeKernel, _v2.ConcurrentExecutionJournal]:
    cell = manifest.prompt_model_cells[cell_index]
    workspace = _v2.derive_concurrent_execution_workspace(target)
    if target.exists() or workspace.exists():
        raise RecoveryCampaignError("Recovery runtime requires an independent new invocation identity")
    snapshot = config.snapshot(sampling_status=_v2.VALIDATION_RUN_STATUS, production_deploy_eligible=False)
    snapshot["runtime_consumer"] = "concurrent-recovery-realization-v1"
    identity = _v2._json_object(_v2._build_primary_only_concurrent_execution_run_identity(
        output_target=target, operational_workspace=workspace, configuration_snapshot=snapshot,
        message_snapshot=[message.model_dump(mode="json") for message in config.messages],
        sample_audit=prepared.cohort.sample_audit, dataset_dir=config.dataset_dir,
        primary_provider_metadata={"adapter": "persisted-recovery-realization-v1", "requested_model": cell.requested_model, "provider_calls": 0},
        prompt_contract={"primary": _v2.CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.resolve(cell.prompt_version).audit_record()},
        execution_contract={"schema_version": "concurrent-recovery-runtime-cell-v1", "epoch_identity_sha256": epoch_identity,
                            "invocation_identity_sha256": invocation_identity, "cell_index": cell_index,
                            "cell": cell.model_dump(mode="json"), "manifest_sha256": _v2._json_sha256(manifest.model_dump(mode="json")),
                            "realization_source_identity": manifest.realization_source.source_identity,
                            "production_deploy_eligible": False},
    ))
    journal = _v2.ConcurrentExecutionJournal.open_new(workspace, identity=identity)
    state = _v2._ConcurrentRuntimeKernelState(cohort=prepared.cohort,
            exposed_by_message={message.message_id: set() for message in config.messages}, campaign_engaged_user_ids=set())
    kernel = _v2._ConcurrentRuntimeKernel.primary_only(config=config, state=state,
             base_network_by_user=prepared.base_network_by_user, neighbors_by_user=prepared.neighbors_by_user, journal=journal)
    return kernel, journal


def run_recovery_model(
    *, config: Any, prepared: Any, manifest: _v2.ConcurrentRobustnessManifestV2,
    state: CampaignProgress, journal: CampaignJournal, adapters_by_cell: Mapping[str, LLMDecisionAdapter],
    inherited: Mapping[tuple[int, int], _v2._V2RealizedTerminal], check_dispatch_window: Callable[[], None],
) -> None:
    """Rebuild only through normal kernel interfaces; dispatch at most one model."""
    _require_scope(journal.identity)
    if not state.epochs or state.status not in {"running", "paused"} or state.has_inflight:
        raise RecoveryCampaignError("Recovery runtime lacks a safe admitted epoch")
    epoch = state.epochs[-1]
    invocation = state.append(journal, "invocation_started", {
        "epoch_identity_sha256": epoch["epoch_identity_sha256"], "ordinal": len(state.invocations) + 1,
    })
    invocation_id = invocation["record_sha256"]
    root = journal.root / "invocations" / invocation_id
    root.mkdir()
    lane = _v2._V2ModelLane(requested_model=epoch["requested_model"], backoff_seconds=manifest.request_contract.retry_backoff_seconds)
    for index, cell in enumerate(manifest.prompt_model_cells):
        if cell.requested_model != epoch["requested_model"]:
            continue
        from ._concurrent_recovery_parallel_runtime import ParallelAdapterPool, freeze_work, run_frozen_batch
        resource = adapters_by_cell[cell.cell_id]
        if state.parallel_approval is not None and not isinstance(resource, ParallelAdapterPool):
            raise RecoveryCampaignError("Approved parallel execution requires independent lane resources")
        adapter = _v2._V2LaneDecisionAdapter(resource.lanes[0] if isinstance(resource, ParallelAdapterPool) else resource, lane)
        request_baseline = _v2._adapter_request_invocations(adapter)
        external_baseline = _v2._adapter_external_request_invocations(adapter)
        cell_root = root / f"cell-{index:02d}"
        cell_root.mkdir()
        kernel, runtime_journal = _kernel(config=config, prepared=prepared, manifest=manifest, cell_index=index,
                                         target=cell_root / "runtime", epoch_identity=epoch["epoch_identity_sha256"],
                                         invocation_identity=invocation_id)
        source_id = _v2._judgment_source_identity(manifest=manifest,
                    manifest_sha256=state.proposal["frozen_context"]["manifest_sha256"], cell_index=index, cell=cell)

        def resolve(
            plan: _PairExecutionPlan, *, index: int = index, cell: _v2._PromptModelCell = cell,
            kernel: _v2._ConcurrentRuntimeKernel = kernel, adapter: _v2._V2LaneDecisionAdapter = adapter,
            request_baseline: int = request_baseline, external_baseline: int = external_baseline,
            source_id: str = source_id,
        ) -> _v2._V2RealizedTerminal:
            key = index, plan.pair_schedule_position
            terminal = inherited.get(key)
            if terminal is None and key in state.judgments:
                terminal = RecoveryJudgmentV1.model_validate(state.judgments[key]).realized_projection(
                    realization_source_identity=manifest.realization_source.source_identity)
            if terminal is None:
                coordinates = _coordinates(index, plan)
                if state.reservation is None:
                    state.append(journal, "pair_reserved", coordinates)
                elif state.reservation != coordinates:
                    raise RecoveryCampaignError("Recovery reservation differs from the rebuilt runtime cursor")
                kernel.start_pair(plan)
                if key not in state.success_decisions:
                    def observe(phase: str, next_number: int, evidence: tuple[_v2._V2AttemptEvidence, ...], delay: float | None) -> None:
                        if phase == "retry_wait":
                            row = evidence[-1]
                            state.append(journal, "attempt_settled", {"attempt": row.model_dump(mode="json"), "decision": None})
                        elif phase == "dispatching":
                            check_dispatch_window()
                            state.append(journal, "attempt_intent", {"attempt_number": next_number})
                        else:
                            raise RecoveryCampaignError("Recovery lane emitted an unknown phase")
                    prior = state.attempts(key)
                    if prior and prior[-1].outcome == "retryable_failure" and prior[-1].wait_seconds:
                        check_dispatch_window()
                        _v2._V2_SLEEP(prior[-1].wait_seconds)
                    adapter.prepare_attempt(prior_evidence=prior, observer=observe)
                    context = _v2._primary_variant_context(plan, prompt_token=cell.prompt_version)
                    attempt, _ = _v2._execute_runtime_variant(adapter=adapter, context=context,
                        pair_schedule_position=plan.pair_schedule_position, time_step=plan.time_step,
                        message_id=plan.message.message_id,
                        default_provider_metadata={"adapter": "formal-frozen-provider-recovery-v1", "requested_model": cell.requested_model})
                    _v2._assert_adapter_transport_progress(manifest=manifest, adapter=adapter,
                        request_baseline=request_baseline, external_baseline=external_baseline)
                    if not adapter.last_attempt_evidence or state.inflight is None:
                        raise RecoveryCampaignError("Recovery response lacks its durable attempt intent")
                    evidence = adapter.last_attempt_evidence[-1]
                    state.append(journal, "attempt_settled", {"attempt": evidence.model_dump(mode="json"),
                        "decision": attempt.decision.model_dump(mode="json") if attempt.decision is not None else None})
                    if state.status == "stopped":
                        raise _v2._V2CellStopped("Recovery stopped on a new hard Provider failure")
                if state.pending_judgment is None:
                    judgment = build_recovery_judgment(cell_index=index, cell=cell, plan=plan,
                        decision=state.success_decisions[key], historical_attempts=state.historical_failure if key == state.failed_key else (),
                        new_attempts=tuple(state.new_attempts[key]),
                        epoch_identity_sha256=state.attempt_epochs[key, state.new_attempts[key][-1].attempt_number],
                        judgment_source_identity=source_id)
                    state.append(journal, "judgment_persisted", {"judgment": judgment.model_dump(mode="json")})
                judgment = RecoveryJudgmentV1.model_validate(state.pending_judgment)
                terminal = judgment.realized_projection(realization_source_identity=manifest.realization_source.source_identity)
                if state.pending_realized is None:
                    state.append(journal, "realized_persisted", {"terminal": terminal.model_dump(mode="json")})
            runtime_terminal = _v2._runtime_terminal(plan, terminal)
            kernel.start_pair(plan)
            kernel.register_terminal(plan=plan, decision_variant="primary", terminal_row=runtime_terminal,
                                     variant_evidence=_v2._runtime_evidence(plan, runtime_terminal))
            return terminal

        def settled(plan: _PairExecutionPlan, terminal: _v2._V2RealizedTerminal, *, index: int = index) -> None:
            key = index, plan.pair_schedule_position
            if key not in inherited and key not in state.judgments:
                state.append(journal, "pair_settled", {"judgment_id": terminal.judgment_id,
                                                     "realized_terminal_id": terminal.realized_terminal_id})

        def committed(commit: _v2._ConcurrentRuntimeBatchCommit, *, index: int = index, cell: _v2._PromptModelCell = cell) -> None:
            row = _v2._commit_row(cell_index=index, cell_id=cell.cell_id, commit=commit)
            key = len(state.epochs), index, commit.time_step
            if key in state.batch_commits:
                if _v2._canonical_json_bytes(state.batch_commits[key]) != _v2._canonical_json_bytes(row):
                    raise RecoveryCampaignError("Recovery rebuilt batch differs from the committed history")
            else:
                state.append(journal, "batch_committed", {"cell_index": index, "time_step": commit.time_step, "commit": row})
        def batch_ready(plans: tuple[_PairExecutionPlan, ...], *, index: int = index,
                        cell: _v2._PromptModelCell = cell, resource: LLMDecisionAdapter = resource) -> None:
            if isinstance(resource, ParallelAdapterPool):
                run_frozen_batch(state=state, journal=journal, pool=resource,
                    work=freeze_work(index, cell, plans), check_dispatch_window=check_dispatch_window,
                    backoff_seconds=manifest.request_contract.retry_backoff_seconds)
        try:
            _v2._drive_primary_runtime(kernel, resolve_pair=resolve, pair_settled=settled, batch_committed=committed,
                                      batch_ready=batch_ready if state.parallel_approval is not None else None)
            replay = runtime_journal._replay_runtime()
            if kernel.validate_spool(replay) != manifest.ranking_contract.horizon or kernel.runtime_resident_row_count:
                raise RecoveryCampaignError("Recovery runtime did not close every batch")
        finally:
            runtime_journal.close()
    state.append(journal, "epoch_finished", {"status": "checkpoint"})
