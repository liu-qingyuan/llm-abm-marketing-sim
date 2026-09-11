"""Study-owned task progression over the existing single-model recovery driver."""
from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import concurrent_robustness_formal_execution as _formal
from . import concurrent_robustness_recovery_execution as _execution
from . import concurrent_robustness_recovery_task as _task
from . import concurrent_robustness_v2 as _v2
from ._concurrent_recovery_bundle import publish_recovery_bundle
from ._concurrent_recovery_campaign import CampaignJournal, RecoveryCampaignError, _require_scope
from .decision import LLMDecisionAdapter, ProviderDecisionError

if TYPE_CHECKING:
    from .concurrent_robustness_study import ConcurrentRobustnessStudy

ModelResources = Callable[[str], AbstractContextManager[Callable[[], Mapping[str, LLMDecisionAdapter]]]]
_TERMINAL = {"stopped", "reconciliation_required", "revoked", "authorization_not_current", "execution_complete", "model_complete"}


def _append(context: _execution._ExecutionContext, kind: str, payload: dict[str, Any]) -> None:
    _task._validate_task_event(context.origins, context.state, kind, payload, _formal._utc_now())
    context.state.append(context.journal, kind, payload)


def _observe_revocation(context: _execution._ExecutionContext) -> None:
    if _task._read_revocation(context.plan) is not None and not context.state.task_revoked:
        path = Path(context.plan["revocation_path"])
        _append(context, "task_revoked", {"revocation": {
            "path": str(path), "sha256": _formal._sha256_file(path),
        }})


def _check_model(context: _execution._ExecutionContext, adapters: Mapping[str, LLMDecisionAdapter]) -> None:
    model = context.state.current_model
    assert model is not None
    cells = tuple(cell for cell in context.origins.source.manifest.prompt_model_cells if cell.requested_model == model)
    from ._concurrent_recovery_parallel_runtime import ParallelAdapterPool, preflight_pools
    amended = context.state.output_amendment is not None and context.state.output_amendment["requested_model"] == model
    ceiling = 1024 if amended else 256
    if any(isinstance(a, ParallelAdapterPool) for a in adapters.values()):
        preflight_pools(context.origins.source.manifest, cells, adapters, kimi_output_token_ceiling=ceiling)
        adapters = {key: value.lanes[0] if isinstance(value, ParallelAdapterPool) else value for key, value in adapters.items()}
    _v2._preflight_cell_adapters(context.origins.source.manifest, cells, adapters, kimi_output_token_ceiling=ceiling)
    from ._concurrent_recovery_output_amendment import preflight
    preflight(context.state, adapters)
    adapter = adapters[cells[0].cell_id]
    before = _v2._v2_adapter_snapshot(adapter)
    data = _task._self_check_input()
    if _task._task_status(context)["status"] in _TERMINAL:
        raise RecoveryCampaignError("Task ended before the self-check dispatch")
    prefix = "amended_" if amended else ""
    _append(context, prefix + "self_check_intent", {
        "requested_model": model, "contract_sha256": _v2._json_sha256(_task._health_contract(context.origins, model, context.state)),
    })
    failure = None
    decision = None
    try:
        decision = adapter.decide(post=data.post, profile=data.profile, peer_context=data.peer_context,
                                  platform_context=data.platform_context, time_step=data.time_step)
    except ProviderDecisionError as error:
        failure = error
    # Unknown provenance or an interruption leaves the durable intent unsettled.
    attempt = _v2._v2_attempt_evidence(adapter=adapter, before=before, attempt_number=1,
        outcome="succeeded" if failure is None else "nonretryable_failure", error=failure,
        wait_seconds=None, wait_source=None)
    _append(context, prefix + "self_check_settled", {"requested_model": model,
        "attempt": attempt.model_dump(mode="json"),
        "decision": None if decision is None else decision.model_dump(mode="json", exclude={"provider_metadata"})})


def _run_task_study(study: ConcurrentRobustnessStudy, plan_path: str | Path,
                    model_resources: ModelResources) -> dict[str, Any]:
    context = _task._context(plan_path)
    _require_scope(context.origins.campaign)
    status = _task._task_status(context)
    if status["status"] in _TERMINAL:
        if context.journal.records:
            publish_recovery_bundle(context)
        return _task._task_status(context)
    if os.environ.get("LLM_ABM_RUN_LIVE_LLM") != "1":
        raise RecoveryCampaignError("Recovery task requires the explicit live gate")
    journal = CampaignJournal.open(context.origins.campaign)
    if journal.head != context.journal.head:
        raise RecoveryCampaignError("Recovery task head changed before admission")
    context = _execution._ExecutionContext(context.plan, context.origins, journal, context.state)
    if context.state.task_plan is None:
        _append(context, "task_admitted", {"task_plan": context.origins.handoff.model_dump(mode="json")})
    try:
        while _task._task_status(context)["status"] not in _TERMINAL:
            model = context.state.current_model
            assert model is not None
            if context.state.effective_parallel_approval is not None and model != context.state.effective_parallel_approval["requested_model"]:
                break
            with model_resources(model) as fresh_adapters:
                if context.state.effective_self_check(model) is None:
                    _check_model(context, fresh_adapters())
                _observe_revocation(context)
                if _task._task_status(context)["status"] in _TERMINAL:
                    break
                if context.state.status in {"running", "paused"} and context.state.epochs:
                    path = Path(context.state.epochs[-1]["plan_path"])
                else:
                    path = _task._derive_epoch(context)
                manifest = _execution.RecoveryExecutionManifest(execution_plan=_formal.FormalArtifactReference(
                    path=path, sha256=_formal._sha256_file(path),
                ))
                result = study.run(manifest, fresh_adapters(), context.journal.root)
                if not isinstance(result, _execution.RecoveryExecutionResult):
                    raise RecoveryCampaignError("Task Study returned an incompatible checkpoint")
            context = _task._context(plan_path)
            _observe_revocation(context)
            if result.recovery_status != "checkpoint":
                break
    except (Exception, KeyboardInterrupt):
        # Append/HEAD may be durable even if the in-memory transition threw.
        # Never infer an unused self-check or Formal slot from the caught error.
        context = _task._context(plan_path)
        _observe_revocation(context)
        publish_recovery_bundle(context)
        status = _task._task_status(context)
        if status["status"] not in _TERMINAL:
            status.update(status="paused", pause_reason="task_setup_execution_or_cleanup_failed")
        return status
    publish_recovery_bundle(context)
    return _task._task_status(context)
