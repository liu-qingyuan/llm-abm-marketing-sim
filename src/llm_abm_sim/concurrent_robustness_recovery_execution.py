"""Explicit recovery epochs, legal lineage and Study execution.

Plans name one source-bound campaign and committed head. Neither preparation nor
inspection grants execution permission. Legacy epochs retain all five current
qualification windows; explicitly versioned task epochs derive their authority
from one task approval and persisted model self-checks, under the same live lock.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import field_validator

from . import concurrent_robustness_formal_execution as _formal
from . import concurrent_robustness_recovery_epoch as _initial
from . import concurrent_robustness_v2 as _v2
from ._concurrent_recovery_campaign import CampaignJournal, RecoveryCampaignError, _require_scope
from ._concurrent_recovery_progress import CampaignProgress
from .concurrent_robustness_study import ConcurrentRobustnessStudyResult, ConcurrentRobustnessStudyStatus
from .decision import LLMDecisionAdapter

RECOVERY_EXECUTION_REQUEST_SCHEMA = "concurrent-robustness-recovery-execution-request-v1"
RECOVERY_EXECUTION_PLAN_SCHEMA = "concurrent-robustness-recovery-execution-plan-v1"
RECOVERY_EXECUTION_MANIFEST_SCHEMA = "concurrent-robustness-recovery-manifest-v1"


class RecoveryExecutionRequest(_formal._FrozenModel):
    schema_version: Literal["concurrent-robustness-recovery-execution-request-v1"] = RECOVERY_EXECUTION_REQUEST_SCHEMA
    initial_handoff: _formal.FormalArtifactReference
    qualification_artifacts: tuple[_formal.FormalQualificationArtifactReference, ...]
    expected_head_sha256: str

    @field_validator("expected_head_sha256")
    @classmethod
    def _head(cls, value: str) -> str:
        return _v2._require_sha256(value, "recovery expected head")


class RecoveryExecutionManifest(_formal._FrozenModel):
    schema_version: Literal["concurrent-robustness-recovery-manifest-v1"] = RECOVERY_EXECUTION_MANIFEST_SCHEMA
    execution_plan: _formal.FormalArtifactReference


class RecoveryExecutionResult(ConcurrentRobustnessStudyResult):
    """cells_complete means execution only, never final Formal Evidence closure."""
    recovery_status: str
    successful_judgments: int
    campaign_head_sha256: str
    execution_bundle: Path | None = None
    formal_evidence_closed: Literal[False] = False
    production_deploy_eligible: Literal[False] = False


@dataclass(frozen=True)
class _Origins:
    handoff: _formal.FormalArtifactReference
    proposal_reference: _formal.FormalArtifactReference
    proposal: dict[str, Any]
    source: _formal.FormalPlanInspection
    campaign: dict[str, Any]
    task_plan: dict[str, Any] | None = None


@dataclass(frozen=True)
class _ExecutionContext:
    plan: dict[str, Any]
    origins: _Origins
    journal: CampaignJournal
    state: CampaignProgress


def _origins(reference: _formal.FormalArtifactReference) -> _Origins:
    document = _initial._checked_reference(reference)
    if document.get("schema_version") == "concurrent-recovery-task-plan-v1":
        from .concurrent_robustness_recovery_task import _task_origins
        return _task_origins(reference)
    handoff = _initial._read_initial_epoch_plan(reference.path)
    _initial._checked_reference(reference)
    request = _initial.RecoveryInitialEpochRequest.model_validate(handoff["request"])
    proposal, source = _initial._inherited_context(request.proposal)
    campaign = _initial._campaign_identity(proposal)
    if campaign != handoff["authorization"]["request_identity"]["campaign"]:
        raise RecoveryCampaignError("Recovery source differs from its initial handoff")
    return _Origins(reference, request.proposal, proposal, source, campaign)


def _journal(origins: _Origins) -> CampaignJournal:
    if any(Path(origins.campaign[k]).exists() for k in ("source_anchor_path", "control_root")):
        return CampaignJournal.read(origins.campaign)
    return CampaignJournal(origins.campaign, ())


def _readiness(request: RecoveryExecutionRequest, origins: _Origins, state: CampaignProgress, head: str, *, now: datetime) -> dict[str, Any]:
    if origins.task_plan is not None:
        raise RecoveryCampaignError("Legacy execution approval cannot use task-policy origins")
    if request.initial_handoff != origins.handoff or request.expected_head_sha256 != head:
        raise RecoveryCampaignError("Recovery execution uses crossed origins or a stale head")
    if state.has_inflight or state.status in {"stopped", "reconciliation_required", "complete"} or state.current_model is None:
        raise RecoveryCampaignError("Recovery cannot authorize unknown or terminal history")
    initial_request = _initial.RecoveryInitialEpochRequest(proposal=origins.proposal_reference, qualification_artifacts=request.qualification_artifacts)
    qualifications = _initial._qualified_artifacts(initial_request, origins.source, now=now)
    proposal = origins.proposal
    identity = {
        "schema_version": "concurrent-recovery-execution-scope-v1",
        "initial_handoff": request.initial_handoff.model_dump(mode="json"),
        "proposal": origins.proposal_reference.model_dump(mode="json"),
        "campaign": origins.campaign, "expected_head_sha256": head,
        "epoch_ordinal": len(state.epochs) + 1, "requested_model": state.current_model,
        "remaining_valid_judgments": proposal["remaining_valid_judgments"] - state.new_valid_judgments,
        "maximum_remaining_physical_attempts": proposal["maximum_new_physical_attempts"] - state.physical_attempts,
        "new_physical_attempts_already_consumed": state.physical_attempts,
        "model_remaining_physical_attempts": [
            {"requested_model": row["requested_model"], "remaining": row["maximum_new_physical_attempts"] - state.physical_by_model[row["requested_model"]]}
            for row in proposal["model_budgets"]
        ],
        "qualification_artifacts": qualifications,
        "provider_routes": [row.model_dump(mode="json") for row in origins.source.request.provider_routes],
        "provider_caps": [row.model_dump(mode="json") for row in origins.source.request.provider_caps],
        "run_parameters": origins.source.request.run_parameters.model_dump(mode="json"),
        "execution_policy": "model-major-serial-one-model-per-invocation-v1",
        "historical_all_attempts_total_tokens": None,
    }
    template = {"schema_version": "concurrent-recovery-execution-authorization-v1", "status": "approved",
                "authorization_reference": "REPLACE-EXPLICIT-RECOVERY-EXECUTION-APPROVAL",
                "approved_at_utc": "REPLACE-UTC", "expires_at_utc": "REPLACE-UTC",
                "request_identity": identity, "request_identity_sha256": _v2._json_sha256(identity)}
    return {"request_identity": identity, "authorization_template": template}


def _plan_body(request: RecoveryExecutionRequest, reference: _formal.FormalArtifactReference, approval: dict[str, Any], path: Path) -> dict[str, Any]:
    return {"schema_version": RECOVERY_EXECUTION_PLAN_SCHEMA, "plan_path": str(path),
            "request": request.model_dump(mode="json"), "authorization_artifact": reference.model_dump(mode="json"),
            "authorization": approval, "execution_authority": "requires-current-source-lock-and-epoch-admission"}


def _plan_document(path: str | Path) -> dict[str, Any]:
    target = _initial._proposals._safe_path(path)
    fact = _initial._proposals._file_fact(target)
    if cast(int, fact["mode"]) & 0o222:
        raise RecoveryCampaignError("Recovery execution plan must be immutable")
    document = _initial._checked_reference(_formal.FormalArtifactReference(path=target, sha256=str(fact["sha256"])))
    if document.get("schema_version") not in {RECOVERY_EXECUTION_PLAN_SCHEMA, "concurrent-recovery-task-epoch-v1"} or document.get("plan_path") != str(target):
        raise RecoveryCampaignError("Recovery execution requires its exact path-bound plan schema")
    return document


def _verify_plan(document: dict[str, Any], origins: _Origins, state: CampaignProgress, head: str) -> dict[str, Any]:
    if document["schema_version"] == "concurrent-recovery-task-epoch-v1":
        from .concurrent_robustness_recovery_task import _verify_epoch
        return _verify_epoch(document, origins, state, head)
    request = RecoveryExecutionRequest.model_validate(document.get("request"))
    reference = _formal.FormalArtifactReference.model_validate(document.get("authorization_artifact"))
    approval = _initial._checked_reference(reference)
    when = _formal._parse_utc(approval.get("approved_at_utc"), "recovery approval")
    readiness = _readiness(request, origins, state, head, now=when)
    path = _initial._validate_plan_location(Path(document["plan_path"]), origins.proposal, origins.campaign)
    checked = _initial._validate_approval(reference, readiness, now=when)
    body = _plan_body(request, reference, checked, path)
    expected = {**body, "plan_identity_sha256": _v2._json_sha256(body)}
    if _formal._canonical_json_bytes(document) != _formal._canonical_json_bytes(expected):
        raise RecoveryCampaignError("Recovery execution plan differs from independent origins")
    return expected


def _window_current(plan: dict[str, Any], now: datetime) -> bool:
    if plan["schema_version"] == "concurrent-recovery-task-epoch-v1":
        authority = plan["task_authority"]
        end = authority["deadline_utc"]
        return (_formal._parse_utc(authority["approved_at_utc"], "task approval") <= now
                and (end is None or now < _formal._parse_utc(end, "task deadline")))
    approval = plan["authorization"]
    windows = [(approval["approved_at_utc"], approval["expires_at_utc"])]
    windows.extend((row["evidence"]["qualified_at_utc"], row["evidence"]["expires_at_utc"]) for row in approval["request_identity"]["qualification_artifacts"])
    return all(_formal._parse_utc(start, "recovery window start") <= now < _formal._parse_utc(end, "recovery window expiry") for start, end in windows)


def _legal_history(origins: _Origins, records: tuple[dict[str, Any], ...], target: dict[str, Any] | None = None) -> CampaignProgress:
    """One forward replay: each epoch is checked against its actual predecessor."""
    state = CampaignProgress(origins.proposal)
    head = origins.campaign["campaign_identity_sha256"]
    active: dict[str, Any] | None = None
    target_head = target["request"]["expected_head_sha256"] if target is not None else None
    target_checked = False
    previous_time: datetime | None = None
    for number, row in enumerate((*records, None), 1):
        if target is not None and head == target_head:
            _verify_plan(target, origins, state, head)
            target_checked = True
        if row is None:
            break
        body = {k: v for k, v in row.items() if k != "record_sha256"}
        if (set(row) != {"schema_version", "campaign_identity_sha256", "sequence", "previous_sha256", "kind", "payload", "recorded_at_utc", "record_sha256"}
            or row["schema_version"] != "concurrent-recovery-campaign-event-v1" or row["campaign_identity_sha256"] != origins.campaign["campaign_identity_sha256"]
            or type(row["sequence"]) is not int or row["sequence"] != number or row["previous_sha256"] != head
            or row["record_sha256"] != _v2._json_sha256(body)):
            raise RecoveryCampaignError("Recovery legal history has a crossed chain")
        when = _formal._parse_utc(row["recorded_at_utc"], "recovery event time")
        if previous_time is not None and when < previous_time:
            raise RecoveryCampaignError("Recovery event clock moved backwards")
        payload = row["payload"]
        if row["kind"] == "kimi_retry_policy_accepted":
            from ._concurrent_recovery_kimi_retry import validate_receipt as validate_kimi_retry
            validate_kimi_retry(origins, state, payload, when, head)
        if row["kind"] == "kimi_manual_retry_accepted":
            from ._concurrent_recovery_manual_retry import validate_receipt as validate_manual
            validate_manual(origins, state, payload, when, head)
        if row["kind"] == "kimi_official_execution_activated":
            from .concurrent_robustness_recovery_task import _current
            if origins.task_plan is None or not _current(origins.task_plan, when):
                raise RecoveryCampaignError("Official activation is outside the current task window")
        if row["kind"] == "kimi_official_migration_accepted":
            from ._concurrent_recovery_kimi_migration import validate_receipt as validate_kimi_migration
            validate_kimi_migration(origins, state, payload, when, head)
        if row["kind"] == "gemini_restoration_accepted":
            from ._concurrent_recovery_gemini_restoration import validate_receipt as validate_restoration
            validate_restoration(origins, state, payload, when, head)
        if row["kind"] == "kimi_output_amendment_accepted":
            from ._concurrent_recovery_output_amendment import validate_receipt as validate_output
            validate_output(origins, state, payload, when, head)
        if row["kind"] == "model_lane_accepted":
            from ._concurrent_recovery_model_lane import validate_receipt as validate_model_lane
            validate_model_lane(origins, state, payload, when, head)
        if row["kind"] == "quota_retry_accepted":
            from ._concurrent_recovery_quota_retry import validate_receipt as validate_quota
            validate_quota(origins, state, payload, when, head)
        if row["kind"] == "parallel_execution_accepted":
            from ._concurrent_recovery_parallel import validate_receipt as validate_parallel
            validate_parallel(origins, state, payload, when, head)
        if row["kind"] == "parallel_attempt_settled":
            from .concurrent_robustness_recovery_task import _validate_task_event
            _validate_task_event(origins, state, "official_attempt_settled" if state.kimi_migration_active else "self_check_settled", {
                "requested_model": state.cells[payload["cell_index"]].requested_model,
                "attempt": payload["attempt"], "decision": payload["decision"],
            }, when)
        if row["kind"] == "self_check_recheck_accepted":
            from ._concurrent_recovery_recheck import validate_receipt
            validate_receipt(origins, state, payload, when, head)
        if row["kind"] in {"task_admitted", "task_revoked", "self_check_intent", "self_check_settled", "amended_self_check_intent", "amended_self_check_settled"}:
            from .concurrent_robustness_recovery_task import _validate_task_event
            _validate_task_event(origins, state, row["kind"], payload, when)
        elif origins.task_plan is not None and state.task_plan != origins.handoff.model_dump(mode="json"):
            raise RecoveryCampaignError("Task history lacks its unique admitted authority")
        if row["kind"] == "epoch_admitted":
            reference = _formal.FormalArtifactReference(path=payload["plan_path"], sha256=payload["plan_sha256"])
            _initial._checked_reference(reference)
            active = _verify_plan(_plan_document(reference.path), origins, state, head)
            if payload["epoch_identity_sha256"] != active["plan_identity_sha256"]:
                raise RecoveryCampaignError("Recovery epoch is crossed with its approved plan")
        if row["kind"] in {"epoch_admitted", "invocation_started", "attempt_intent", "parallel_attempt_intent"}:
            if active is None or not _window_current(active, when):
                raise RecoveryCampaignError("Recovery dispatch or admission is outside its legal window")
        state.transition(row["kind"], payload)()
        previous_time, head = when, row["record_sha256"]
    if target is not None and not target_checked:
        raise RecoveryCampaignError("Recovery plan references an unknown committed head")
    return state


def _load_context(plan_path: str | Path) -> _ExecutionContext:
    document = _plan_document(plan_path)
    if document["schema_version"] == "concurrent-recovery-task-epoch-v1":
        reference = _formal.FormalArtifactReference.model_validate(document["task_plan"])
    else:
        reference = RecoveryExecutionRequest.model_validate(document.get("request")).initial_handoff
    origins = _origins(reference)
    journal = _journal(origins)
    state = _legal_history(origins, journal.records, document)
    if origins.task_plan is not None:
        from .concurrent_robustness_recovery_task import _plan_inventory
        _plan_inventory(origins, journal, state)
    return _ExecutionContext(document, origins, journal, state)


def prepare_recovery_execution(request: RecoveryExecutionRequest) -> dict[str, Any]:
    """Return a current exact approval template without claiming or dispatching."""
    origins = _origins(request.initial_handoff)
    journal = _journal(origins)
    state = _legal_history(origins, journal.records)
    readiness = _readiness(request, origins, state, journal.head, now=_formal._utc_now())
    return {"schema_version": "concurrent-recovery-execution-readiness-v1", **readiness,
            "execution_authority": False, "provider_calls": 0, "credential_reads": 0}


def authorize_recovery_execution(*, request: RecoveryExecutionRequest, authorization_path: Path, authorization_sha256: str, plan_output: Path) -> dict[str, Any]:
    """Publish a new immutable execution plan; this does not claim a source."""
    origins = _origins(request.initial_handoff)
    journal = _journal(origins)
    state = _legal_history(origins, journal.records)
    readiness = _readiness(request, origins, state, journal.head, now=_formal._utc_now())
    reference = _formal.FormalArtifactReference(path=authorization_path, sha256=authorization_sha256)
    approval = _initial._validate_approval(reference, readiness, now=_formal._utc_now())
    path = _initial._validate_plan_location(plan_output, origins.proposal, origins.campaign)
    if path.exists():
        raise RecoveryCampaignError("Recovery execution plan requires a new path")
    body = _plan_body(request, reference, approval, path)
    plan = {**body, "plan_identity_sha256": _v2._json_sha256(body)}
    _verify_plan(plan, origins, state, journal.head)
    _initial._publish_immutable(path, plan)
    return read_recovery_execution_plan(path)


def read_recovery_execution_plan(plan_path: str | Path) -> dict[str, Any]:
    """Verify all persisted legal origins, including every prior admitted epoch."""
    return _load_context(plan_path).plan


def _action(context: _ExecutionContext) -> str:
    plan, state, journal = context.plan, context.state, context.journal
    if state.has_inflight or state.status in {"complete", "stopped", "reconciliation_required", "model_complete"}:
        return "return"
    used = [row for row in state.epochs if row["epoch_identity_sha256"] == plan["plan_identity_sha256"]]
    if used:
        if used[-1] != state.epochs[-1]:
            raise RecoveryCampaignError("Recovery execution grant belongs to a completed older epoch")
        return "return" if state.status == "checkpoint" else "continue"
    if plan["request"]["expected_head_sha256"] != journal.head:
        raise RecoveryCampaignError("Recovery execution plan has a stale admission head")
    return "admit"


def _progress(origins: _Origins, state: CampaignProgress) -> dict[str, Any]:
    old = origins.proposal["progress"]
    attempted = set(state.new_attempts)
    if state.inflight is not None:
        attempted.add(state.inflight[0])
    attempted.update(state.parallel_inflight)
    return {"status": "reconciliation_required" if state.has_inflight or state.self_check_inflight is not None else state.status,
            "successful_judgments": old["successful_judgments"] + state.new_valid_judgments,
            "attempted_logical_judgments": old["attempted_logical_judgments"] + len(attempted - {state.failed_key}),
            "physical_attempts": old["physical_attempts"] + state.physical_attempts,
            "new_physical_attempts": state.physical_attempts, "cell_prefixes": list(state.prefix),
            "current_model": state.current_model, "historical_all_attempts_total_tokens": None,
            "formal_evidence_closed": False, "production_deploy_eligible": False}


def inspect_recovery_execution(plan_path: str | Path) -> dict[str, Any]:
    context = _load_context(plan_path)
    return {"schema_version": "concurrent-recovery-execution-inspection-v1", **_progress(context.origins, context.state),
            "campaign_head_sha256": context.journal.head, "current_window_valid": _window_current(context.plan, _formal._utc_now()),
            "execution_action": _action(context), "inspection_only": True, "provider_calls": 0, "credential_reads": 0}


def _result(context: _ExecutionContext, bundle: Path | None = None) -> RecoveryExecutionResult:
    progress = _progress(context.origins, context.state)
    status = {"complete": ConcurrentRobustnessStudyStatus.CELLS_COMPLETE, "stopped": ConcurrentRobustnessStudyStatus.STOPPED,
              "reconciliation_required": ConcurrentRobustnessStudyStatus.RECONCILIATION_REQUIRED,
              "ready": ConcurrentRobustnessStudyStatus.READY_FOR_HUMAN}.get(progress["status"], ConcurrentRobustnessStudyStatus.RESUMABLE)
    return RecoveryExecutionResult(status=status, workspace_root=context.journal.root,
        validation_report=bundle or Path(context.plan["plan_path"]), manifest_sha256=context.origins.proposal["frozen_context"]["manifest_sha256"],
        logical_provider_attempts=progress["attempted_logical_judgments"], physical_provider_attempts=progress["physical_attempts"],
        recovery_status=progress["status"], successful_judgments=progress["successful_judgments"],
        campaign_head_sha256=context.journal.head, execution_bundle=bundle)


def _run_recovery_study(*, manifest: RecoveryExecutionManifest, adapters_by_cell: Mapping[str, LLMDecisionAdapter] | None,
                        output_dir: str | Path, report_destination: str | Path | None, formal_execution_plan: str | Path | None) -> RecoveryExecutionResult:
    from ._concurrent_recovery_bundle import publish_recovery_bundle
    from ._concurrent_recovery_runtime import RecoverySafePause, inherited_terminals, run_recovery_model

    if report_destination is not None or formal_execution_plan is not None:
        raise RecoveryCampaignError("Recovery manifest cannot accept legacy plan or report overrides")
    _initial._checked_reference(manifest.execution_plan)
    context = _load_context(manifest.execution_plan.path)
    _initial._checked_reference(manifest.execution_plan)
    if _initial._proposals._safe_path(output_dir) != context.journal.root:
        raise RecoveryCampaignError("Recovery output differs from its approved campaign")
    _require_scope(context.origins.campaign)
    if adapters_by_cell is None or _action(context) == "return":
        return _result(context)
    if os.environ.get("LLM_ABM_RUN_LIVE_LLM") != "1" or not _window_current(context.plan, _formal._utc_now()):
        raise RecoveryCampaignError("Recovery execution requires its current explicit live window")
    if context.origins.task_plan is None:
        _v2._preflight_adapters(context.origins.source.manifest, adapters_by_cell)
    else:
        from .concurrent_robustness_recovery_task import _read_revocation
        if _read_revocation(context.origins.task_plan) is not None or context.state.task_revoked:
            raise RecoveryCampaignError("Recovery task has been revoked")
        cells = tuple(cell for cell in context.origins.source.manifest.prompt_model_cells
                      if cell.requested_model == context.state.current_model)
        if context.state.kimi_migration_active:
            from ._concurrent_recovery_kimi_migration import preflight as preflight_migration
            preflight_migration(context.state, context.origins.source.manifest, adapters_by_cell)
        elif context.state.effective_parallel_approval is not None:
            from ._concurrent_recovery_parallel_runtime import preflight_pools
            preflight_pools(context.origins.source.manifest, cells, adapters_by_cell,
                            kimi_output_token_ceiling=1024 if context.state.output_amendment is not None else 256)
        else:
            _v2._preflight_cell_adapters(context.origins.source.manifest, cells, adapters_by_cell,
                                         kimi_output_token_ceiling=1024 if context.state.output_amendment is not None else 256)
    from ._concurrent_recovery_output_amendment import preflight as preflight_output
    if not context.state.kimi_migration_active:
        preflight_output(context.state, adapters_by_cell)
    journal = CampaignJournal.open(context.origins.campaign)
    if journal.head != context.journal.head:
        raise RecoveryCampaignError("Recovery head changed before epoch admission")
    state = context.state
    if _action(context) == "admit":
        identity = (context.plan["derivation"] if context.origins.task_plan is not None
                    else context.plan["authorization"]["request_identity"])
        state.append(journal, "epoch_admitted", {"ordinal": identity["epoch_ordinal"], "requested_model": identity["requested_model"],
            "epoch_identity_sha256": context.plan["plan_identity_sha256"], "plan_path": str(manifest.execution_plan.path), "plan_sha256": manifest.execution_plan.sha256})
    context = _ExecutionContext(context.plan, context.origins, journal, state)
    source_manifest = context.origins.source.manifest
    closure = _v2._close_source(source_manifest.source.source_dir)
    config = _v2._dynamic_runtime_config(closure)
    prepared = _v2._prepare_concurrent_runtime_inputs(config)
    inherited = inherited_terminals(context.origins.proposal, source_manifest)

    guard = None
    if state.model_lane_approval is not None:
        from ._concurrent_recovery_model_lane import source_guard
        guard = source_guard(context.origins.proposal["source_artifacts"])

    def check_window() -> None:
        if guard is not None:
            try:
                guard()
            except RecoveryCampaignError:
                state.append(journal, "model_lane_source_drift", {"failure_category": "source_drift"})
                raise
        _require_scope(context.origins.campaign)
        if not _window_current(context.plan, _formal._utc_now()):
            raise RecoverySafePause("Recovery window ended before the next dispatch")
        if context.origins.task_plan is not None:
            from .concurrent_robustness_recovery_task import _read_revocation
            if _read_revocation(context.origins.task_plan) is not None:
                raise RecoverySafePause("Recovery task was revoked before the next dispatch")

    try:
        run_recovery_model(config=config, prepared=prepared, manifest=source_manifest, state=state, journal=journal,
                           adapters_by_cell=adapters_by_cell, inherited=inherited, check_dispatch_window=check_window)
    except _v2._V2CellStopped:
        if state.status != "stopped":
            raise
    except (Exception, KeyboardInterrupt):
        # HEAD may have become durable before an in-memory effect ran. Only the
        # independently replayed durable stage can distinguish pause from unknown.
        journal = CampaignJournal.read(context.origins.campaign)
        state = _legal_history(context.origins, journal.records)
        if state.status == "running":
            state.append(journal, "epoch_finished", {"status": "reconciliation_required" if state.has_inflight else "paused"})
        context = _ExecutionContext(context.plan, context.origins, journal, state)
    _v2._assert_source_unchanged(closure)
    bundle = publish_recovery_bundle(context)
    return _result(context, bundle)


def inspect_recovery_execution_bundle(path: str | Path) -> dict[str, Any]:
    """Independently replay a frozen prefix; temporary kernel workspace is cleaned."""
    from ._concurrent_recovery_bundle import read_recovery_bundle
    return read_recovery_bundle(path)["progress"]
