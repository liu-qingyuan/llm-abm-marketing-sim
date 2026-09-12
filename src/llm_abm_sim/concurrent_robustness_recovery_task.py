"""One bounded task approval; old epoch approvals retain their original policy.

Preparation and inspection never claim a source or access Provider credentials.
A task starts a previously unused recovery campaign. Its immutable approval covers
only the proposal's remaining work and one self-check per unfinished model. It
ends on completion, revocation, an optional deadline, or a new terminal failure;
the legacy qualification TTL does not renew or expire this separate authority.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import field_validator

from . import concurrent_robustness_formal_execution as _formal
from . import concurrent_robustness_recovery_epoch as _initial
from . import concurrent_robustness_recovery_execution as _execution
from . import concurrent_robustness_v2 as _v2
from ._concurrent_recovery_campaign import RecoveryCampaignError, _read
from ._concurrent_recovery_progress import CampaignProgress
from .decision import DecisionInput, EngageDecision
from .prompt_contracts import CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY
from .prompting import build_engagement_prompt
from .schemas import PeerContext, PlatformContext, PostContent, UserProfile

TASK_POLICY = "single-task-bounded-recovery-v1"
TASK_PLAN_SCHEMA = "concurrent-recovery-task-plan-v1"
TASK_CAMPAIGN_SCHEMA = "concurrent-recovery-task-campaign-v1"
TASK_EPOCH_SCHEMA = "concurrent-recovery-task-epoch-v1"


class RecoveryTaskRequest(_formal._FrozenModel):
    """Frozen proposal and independent report destination; deadline is optional.

    No model, route, concurrency or budget overrides are accepted. Publication
    is create-once. A claimed legacy campaign cannot be reauthorized as a task.
    """
    schema_version: Literal["concurrent-recovery-task-request-v1"] = "concurrent-recovery-task-request-v1"
    proposal: _formal.FormalArtifactReference
    report_destination: Path
    deadline_utc: str | None = None

    @field_validator("report_destination")
    @classmethod
    def _destination(cls, value: Path) -> Path:
        return _initial._proposals._safe_path(value)

    @field_validator("deadline_utc")
    @classmethod
    def _deadline(cls, value: str | None) -> str | None:
        if value is not None:
            _formal._parse_utc(value, "task deadline")
        return value


def _campaign(proposal: dict[str, Any]) -> dict[str, Any]:
    legacy = _initial._campaign_identity(proposal)
    body = {key: value for key, value in legacy.items() if key != "campaign_identity_sha256"}
    body.update(schema_version=TASK_CAMPAIGN_SCHEMA, authorization_policy=TASK_POLICY)
    return {**body, "campaign_identity_sha256": _v2._json_sha256(body)}


def _scope(request: RecoveryTaskRequest, proposal: dict[str, Any], source: _formal.FormalPlanInspection) -> dict[str, Any]:
    campaign = _campaign(proposal)
    destination = _initial._validate_plan_location(request.report_destination, proposal, campaign)
    revocation = Path(campaign["source_anchor_path"]).with_suffix(".revoked.json")
    if destination == revocation or destination.is_relative_to(revocation) or revocation.is_relative_to(destination):
        raise RecoveryCampaignError("Task report overlaps its source-bound revocation signal")
    models = [row["requested_model"] for row in proposal["model_budgets"] if row["remaining_valid_judgments"]]
    return {"schema_version": "concurrent-recovery-task-scope-v1", "policy": TASK_POLICY,
            "proposal": request.proposal.model_dump(mode="json"), "campaign": campaign,
            "report_destination": str(destination), "deadline_utc": request.deadline_utc,
            "revocation_path": str(revocation),
            "remaining_valid_judgments": proposal["remaining_valid_judgments"],
            "maximum_new_physical_attempts": proposal["maximum_new_physical_attempts"],
            "maximum_cumulative_physical_attempts": proposal["maximum_cumulative_physical_attempts"],
            "self_check_models": models, "self_check_cap": len(models), "self_check_retries": 0,
            "self_check_policy": "same-task-frozen-config-once-per-unfinished-model-v1",
            "self_check_prompt_sha256": _v2._json_sha256(build_engagement_prompt(_self_check_input())),
            "provider_routes": [row.model_dump(mode="json") for row in source.request.provider_routes],
            "provider_caps": [row.model_dump(mode="json") for row in source.request.provider_caps],
            "run_parameters": source.request.run_parameters.model_dump(mode="json"),
            "historical_all_attempts_total_tokens": None, "production_deploy_eligible": False}


def _template(identity: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": "concurrent-recovery-task-authorization-v1", "status": "approved",
            "authorization_reference": "REPLACE-EXPLICIT-TASK-APPROVAL", "approved_at_utc": "REPLACE-UTC",
            "request_identity": identity, "request_identity_sha256": _v2._json_sha256(identity)}


def _approval(reference: _formal.FormalArtifactReference, identity: dict[str, Any]) -> dict[str, Any]:
    document = _initial._checked_reference(reference)
    if cast(int, _initial._proposals._file_fact(reference.path)["mode"]) & 0o222:
        raise RecoveryCampaignError("Task approval must be immutable")
    expected = _template(identity)
    if set(document) != set(expected):
        raise RecoveryCampaignError("Task approval fields are not exact")
    token = document["authorization_reference"]
    if not isinstance(token, str) or token.startswith("REPLACE-"):
        raise RecoveryCampaignError("Task requires explicit independent approval")
    _formal._safe_reference(token, "task approval reference")
    start = _formal._parse_utc(document["approved_at_utc"], "task approval time")
    deadline = identity["deadline_utc"]
    if deadline is not None and _formal._parse_utc(deadline, "task deadline") <= start:
        raise RecoveryCampaignError("Task deadline must follow approval")
    expected.update(authorization_reference=token, approved_at_utc=document["approved_at_utc"])
    if _formal._canonical_json_bytes(expected) != _formal._canonical_json_bytes(document):
        raise RecoveryCampaignError("Task approval differs from its frozen scope")
    return document


def _current(plan: dict[str, Any], now: datetime) -> bool:
    start = _formal._parse_utc(plan["authorization"]["approved_at_utc"], "task approval time")
    end = plan["request"]["deadline_utc"]
    return start <= now and (end is None or now < _formal._parse_utc(end, "task deadline"))


def _location(path: Path, request: RecoveryTaskRequest, proposal: dict[str, Any]) -> Path:
    target = _initial._validate_plan_location(path, proposal, _campaign(proposal))
    report = request.report_destination
    if target == report or target.is_relative_to(report) or report.is_relative_to(target):
        raise RecoveryCampaignError("Task plan and report scopes overlap")
    return target


def _body(request: RecoveryTaskRequest, reference: _formal.FormalArtifactReference,
          approval: dict[str, Any], path: Path) -> dict[str, Any]:
    return {"schema_version": TASK_PLAN_SCHEMA, "plan_path": str(path),
            "request": request.model_dump(mode="json"), "authorization_artifact": reference.model_dump(mode="json"),
            "authorization": approval, "revocation_path": approval["request_identity"]["revocation_path"],
            "execution_authority": "requires-source-lock-task-admission-and-model-self-check"}


def _task_origins(reference: _formal.FormalArtifactReference) -> _execution._Origins:
    document = _initial._checked_reference(reference)
    if cast(int, _initial._proposals._file_fact(reference.path)["mode"]) & 0o222:
        raise RecoveryCampaignError("Task plan must be immutable")
    request = RecoveryTaskRequest.model_validate(document.get("request"))
    proposal, source = _initial._inherited_context(request.proposal)
    identity = _scope(request, proposal, source)
    approval_ref = _formal.FormalArtifactReference.model_validate(document.get("authorization_artifact"))
    approval = _approval(approval_ref, identity)
    path = _location(reference.path, request, proposal)
    if approval_ref.path == path or approval_ref.path.is_relative_to(request.report_destination):
        raise RecoveryCampaignError("Task approval overlaps a writable task output")
    body = _body(request, approval_ref, approval, path)
    expected = {**body, "plan_identity_sha256": _v2._json_sha256(body)}
    if _formal._canonical_json_bytes(document) != _formal._canonical_json_bytes(expected):
        raise RecoveryCampaignError("Task plan differs from independently verified origins")
    _initial._checked_reference(reference)
    return _execution._Origins(reference, request.proposal, proposal, source, identity["campaign"], document)


def _context(path: str | Path) -> _execution._ExecutionContext:
    target = _initial._proposals._safe_path(path)
    fact = _initial._proposals._file_fact(target)
    origins = _task_origins(_formal.FormalArtifactReference(path=target, sha256=str(fact["sha256"])))
    journal = _execution._journal(origins)
    state = _execution._legal_history(origins, journal.records)
    _plan_inventory(origins, journal, state)
    assert origins.task_plan is not None
    return _execution._ExecutionContext(origins.task_plan, origins, journal, state)


def prepare_recovery_task(request: RecoveryTaskRequest) -> dict[str, Any]:
    """Return the single exact approval packet; no locks, writes or live checks."""
    proposal, source = _initial._inherited_context(request.proposal)
    identity = _scope(request, proposal, source)
    _initial._require_unused_initial_scope({"request_identity": identity})
    if request.report_destination.exists():
        raise RecoveryCampaignError("Task requires a new report destination")
    return {"schema_version": "concurrent-recovery-task-readiness-v1", "request_identity": identity,
            "authorization_template": _template(identity), "execution_authority": False,
            "provider_calls": 0, "credential_reads": 0, "production_deploy_eligible": False}


def authorize_recovery_task(*, request: RecoveryTaskRequest, authorization_path: Path,
                            authorization_sha256: str, plan_output: Path) -> dict[str, Any]:
    """Bind one explicit approval, create-once; no campaign or call is started."""
    ready = prepare_recovery_task(request)
    reference = _formal.FormalArtifactReference(path=authorization_path, sha256=authorization_sha256)
    approval = _approval(reference, ready["request_identity"])
    proposal, _ = _initial._inherited_context(request.proposal)
    path = _location(plan_output, request, proposal)
    body = _body(request, reference, approval, path)
    if not _current(body, _formal._utc_now()):
        raise RecoveryCampaignError("Task approval is not currently valid")
    if path.exists() or reference.path.is_relative_to(request.report_destination):
        raise RecoveryCampaignError("Task requires a new protected plan path")
    plan = {**body, "plan_identity_sha256": _v2._json_sha256(body)}
    _initial._publish_immutable(path, plan)
    return _context(path).plan


def inspect_recovery_task(plan_path: str | Path) -> dict[str, Any]:
    """Read legality/authority and optional report closure; original artifacts stay read-only.

    A closed report's independent reader may use its declared disposable kernel
    workspace. It never opens credentials or runs a Provider.
    """
    context = _context(plan_path)
    status = _task_status(context)
    if status["status"] == "execution_complete":
        report_path = Path(context.plan["request"]["report_destination"]) / "report.html"
        if report_path.is_file():
            try:
                from .concurrent_robustness_recovery_report import inspect_concurrent_robustness_recovery_report

                facts = inspect_concurrent_robustness_recovery_report(report_path)
                bundle = Path(status["execution_bundle"])
                if (facts.get("source_bundle") != {"path": str(bundle), "sha256": _formal._sha256_file(bundle)}
                        or facts.get("formal_evidence_closed") is not True or facts.get("report_status") != "complete"):
                    raise RecoveryCampaignError("Report closure differs from this task checkpoint")
                status.update(status="complete", report_status="complete", report_path=str(report_path), formal_evidence_closed=True)
            except Exception:
                status.update(report_failure="evidence_or_report_unavailable_or_failed")
    return {"schema_version": "concurrent-recovery-task-inspection-v1", **status,
            "inspection_only": True, "provider_calls": 0, "credential_reads": 0}


def _self_check_input() -> DecisionInput:
    return DecisionInput(
        post=PostContent(post_id="recovery-self-check-v1", text="绿色酒店营销内容"),
        profile=UserProfile.model_validate({"user_id": "recovery-self-check-v1", "activity_score": 0.5,
            "global_influence_score": 0.5, "local_influence_score": 0.5,
            "concurrent_environmental_consciousness_coef": 1.0,
            "concurrent_epistemic_value_weight": 0.5, "concurrent_environmental_value_weight": 0.5,
            "concurrent_functional_value_weight": 0.5, "concurrent_health_value_weight": 0.5,
            "concurrent_emotional_value_weight": 0.5, "concurrent_social_value_weight": 0.5,
            "concurrent_hotel_class": "midscale", "concurrent_travel_purpose": "leisure"}),
        peer_context=PeerContext(), platform_context=PlatformContext(), time_step=0,
        prompt_version=CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.resolve("P0").prompt_version,
    )


def _health_contract(origins: _execution._Origins, model: str, state: CampaignProgress | None = None) -> dict[str, Any]:
    assert origins.task_plan is not None
    scope = origins.task_plan["authorization"]["request_identity"]
    contract = {"task_plan_sha256": origins.handoff.sha256, "requested_model": model,
            "route": next(row for row in scope["provider_routes"] if row["requested_model"] == model),
            "prompt_sha256": scope["self_check_prompt_sha256"], "policy": scope["self_check_policy"]}
    if state is not None and state.output_amendment is not None and model == state.output_amendment["requested_model"]:
        contract["output_amendment"] = state.output_amendment
    return contract


def _validate_task_event(origins: _execution._Origins, state: CampaignProgress,
                         kind: str, payload: dict[str, Any], when: datetime) -> None:
    plan = origins.task_plan
    if plan is None:
        raise RecoveryCampaignError("Legacy campaign cannot admit task-policy events")
    if kind == "task_admitted":
        if payload != {"task_plan": origins.handoff.model_dump(mode="json")} or not _current(plan, when):
            raise RecoveryCampaignError("Task admission differs from its one approved origin")
        return
    if state.task_plan != origins.handoff.model_dump(mode="json"):
        raise RecoveryCampaignError("Task event lacks its unique admitted authority")
    if kind == "task_revoked":
        reference = _formal.FormalArtifactReference.model_validate(payload.get("revocation"))
        checked = _read_revocation(plan)
        if checked is None or reference.path != Path(plan["revocation_path"]):
            raise RecoveryCampaignError("Task revocation is crossed")
        _initial._checked_reference(reference)
        if _formal._parse_utc(checked["requested_at_utc"], "revocation time") > when:
            raise RecoveryCampaignError("Task revocation was observed before it was requested")
    elif kind in {"self_check_intent", "amended_self_check_intent"}:
        if not _current(plan, when) or payload.get("contract_sha256") != _v2._json_sha256(_health_contract(origins, state.current_model or "", state if kind == "amended_self_check_intent" else None)):
            raise RecoveryCampaignError("Self-check is outside the approved task or frozen configuration")
    elif kind in {"self_check_settled", "amended_self_check_settled", "official_attempt_settled"}:
        attempt = _v2._V2AttemptEvidence.model_validate(payload.get("attempt"))
        model = payload.get("requested_model")
        cell = next((cell for cell in state.cells if cell.requested_model == model), None)
        route = next((row.provider_route for row in origins.source.request.provider_routes if row.requested_model == model), None)
        official = kind == "official_attempt_settled"
        if official:
            if not state.kimi_migration_active or model != "kimi-coding/k3-256k":
                raise RecoveryCampaignError("Official attempt requires its activated migration")
            route = "moonshot_official"
        if cell is None or attempt.provider_route != route:
            raise RecoveryCampaignError("Self-check response is crossed with its frozen route")
        if attempt.outcome == "succeeded":
            EngageDecision.model_validate(payload["decision"])
            if kind == "amended_self_check_settled" and (attempt.output_usage is None or attempt.output_usage > 1024):
                raise RecoveryCampaignError("Amended self-check exceeds its total output ceiling")
            if (attempt.provider_response_count != 1 or attempt.usage_complete_response_count != 1
                or attempt.observed_model_counts != {"kimi-k3" if official else cell.required_observed_model: 1}
                or attempt.usage_missing_response_count or attempt.usage_malformed_response_count):
                raise RecoveryCampaignError("Self-check success lacks complete strict identity and usage")


def _epoch_body(origins: _execution._Origins, state: CampaignProgress, head: str) -> dict[str, Any]:
    plan = origins.task_plan
    model = state.current_model
    health = None if model is None else state.effective_self_check(model)
    if (plan is None or state.task_plan != origins.handoff.model_dump(mode="json") or state.task_revoked
        or state.has_inflight or state.self_check_inflight is not None
        or state.status in {"stopped", "reconciliation_required", "complete", "model_complete"}
        or model is None or health is None or health["attempt"]["outcome"] != "succeeded"):
        raise RecoveryCampaignError("Task epoch requires its admitted authority and successful model self-check")
    path = Path(origins.campaign["control_root"]) / "plans" / f"{head}.json"
    derivation = {"policy": TASK_POLICY, "epoch_ordinal": len(state.epochs) + 1, "requested_model": model,
                  "remaining_valid_judgments": origins.proposal["remaining_valid_judgments"] - state.new_valid_judgments,
                  "maximum_remaining_physical_attempts": origins.proposal["maximum_new_physical_attempts"] - state.physical_attempts,
                  "self_check_sha256": _v2._json_sha256(state.effective_self_check(model))}
    return {"schema_version": TASK_EPOCH_SCHEMA, "plan_path": str(path),
            "task_plan": origins.handoff.model_dump(mode="json"), "request": {"expected_head_sha256": head},
            "derivation": derivation,
            "task_authority": {"approved_at_utc": plan["authorization"]["approved_at_utc"],
                               "deadline_utc": plan["request"]["deadline_utc"]},
            "execution_authority": "derived-from-single-task-not-another-human-approval"}


def _verify_epoch(document: dict[str, Any], origins: _execution._Origins,
                  state: CampaignProgress, head: str) -> dict[str, Any]:
    body = _epoch_body(origins, state, head)
    expected = {**body, "plan_identity_sha256": _v2._json_sha256(body)}
    if _formal._canonical_json_bytes(document) != _formal._canonical_json_bytes(expected):
        raise RecoveryCampaignError("Task epoch differs from its task, health facts or committed head")
    return expected


def _plan_inventory(origins: _execution._Origins, journal: _execution.CampaignJournal,
                    state: CampaignProgress) -> None:
    if not journal.root.exists():
        return
    expected = {Path(row["plan_path"]).name for row in state.epochs}
    candidate = journal.root / "plans" / f"{journal.head}.json"
    if candidate.exists():
        _verify_epoch(_read(candidate), origins, state, journal.head)
        expected.add(candidate.name)
    if {path.name for path in (journal.root / "plans").iterdir()} != expected:
        raise RecoveryCampaignError("Task internal plan inventory contains an orphan or foreign entry")


def _derive_epoch(context: _execution._ExecutionContext) -> Path:
    body = _epoch_body(context.origins, context.state, context.journal.head)
    document = {**body, "plan_identity_sha256": _v2._json_sha256(body)}
    path = Path(document["plan_path"])
    if path.exists():
        if _read(path) != document:
            raise RecoveryCampaignError("Task epoch create-once destination is occupied")
    else:
        _initial._publish_immutable(path, document)
    return path


def _read_revocation(plan: dict[str, Any]) -> dict[str, Any] | None:
    path = _initial._proposals._safe_path(plan["revocation_path"])
    if not path.exists():
        return None
    document = _read(path)
    if (set(document) != {"schema_version", "request_identity_sha256", "requested_at_utc"}
        or document["schema_version"] != "concurrent-recovery-task-revocation-v1"
        or document["request_identity_sha256"] != plan["authorization"]["request_identity_sha256"]):
        raise RecoveryCampaignError("Task revocation differs from its bound task")
    _formal._parse_utc(document["requested_at_utc"], "revocation request time")
    return document


def revoke_recovery_task(plan_path: str | Path) -> dict[str, Any]:
    """Request cancellation at the next dispatch gate, without waiting for its lock.

    A dispatch already admitted may finish. The running Study records observation
    in its existing journal. This immutable signal neither refunds slots nor
    invalidates previously published historical checkpoints.
    """
    target = _initial._proposals._safe_path(plan_path)
    fact = _initial._proposals._file_fact(target)
    origins = _task_origins(_formal.FormalArtifactReference(path=target, sha256=str(fact["sha256"])))
    assert origins.task_plan is not None
    plan = origins.task_plan
    if _read_revocation(plan) is None:
        _initial._publish_immutable(Path(plan["revocation_path"]), {
            "schema_version": "concurrent-recovery-task-revocation-v1",
            "request_identity_sha256": plan["authorization"]["request_identity_sha256"],
            "requested_at_utc": _formal._utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
    return {"status": "revocation_requested", "provider_calls": 0, "credential_reads": 0}


def _task_status(context: _execution._ExecutionContext) -> dict[str, Any]:
    state = context.state
    progress = _execution._progress(context.origins, state)
    current = _current(context.plan, _formal._utc_now())
    revoked = state.task_revoked or _read_revocation(context.plan) is not None
    status = progress["status"]
    if state.self_check_inflight is not None:
        status = "reconciliation_required"
    elif status == "complete":
        status = "execution_complete"
    elif status not in {"stopped", "reconciliation_required"}:
        if revoked:
            status = "revoked"
        elif not current:
            status = "authorization_not_current"
    bundle = context.journal.root / "bundles" / context.journal.head / "bundle.json"
    return {**progress, "status": status, "authorization_current": current and not revoked,
            "kimi_output_amendment": state.output_amendment,
            "kimi_official_migration": state.kimi_migration_approval,
            "kimi_official_execution_active": state.kimi_migration_active,
            "amended_self_check": state.amended_self_check,
            "self_check_attempts": len(state.self_check_intents) + len(state.accepted_rechecks) + int(state.amended_self_check_intent is not None),
            "self_check_failures": {model: row["attempt"]["failure_category"] for model, row in state.self_checks.items()
                                    if row["attempt"]["outcome"] != "succeeded"},
            "campaign_head_sha256": context.journal.head,
            "execution_bundle": str(bundle) if bundle.is_file() else None,
            "report_status": "report_pending" if status == "execution_complete" else "not_ready",
            "report_path": None}


def accept_recovery_task_recheck(plan_path: str | Path, *, approval_path: Path,
                                  approval_sha256: str) -> dict[str, Any]:
    """Accept one explicit bound recheck without Provider calls or a new task.

    Only a settled connection/zero-response self-check before any task epoch is
    eligible. Original failures and budgets remain intact. The immutable receipt
    is a new journal event; same-approval repetition returns that receipt. Source
    drift, unknowns, other hard stops, revocation and crossed evidence fail closed.
    """
    from . import _concurrent_recovery_recheck as recheck
    from ._concurrent_recovery_campaign import recovery_scope

    context = _context(plan_path)
    reference = _formal.FormalArtifactReference(path=approval_path, sha256=approval_sha256).model_dump(mode="json")
    with recovery_scope(context.origins.campaign):
        context = _context(plan_path)
        approval = recheck._checked(reference)
        existing = next((row for row in context.journal.records if row["kind"] == recheck.EVENT), None)
        if existing is not None:
            if existing["payload"]["approval"] != reference:
                raise RecoveryCampaignError("Task already consumed a different recheck approval")
            row = existing
        else:
            if _read_revocation(context.plan) is not None:
                raise RecoveryCampaignError("Revoked task cannot accept recheck")
            result = recheck._checked(approval["probe_result"])
            payload = {"approval": reference, "requested_model": context.state.current_model,
                       "attempt": result["attempt"], "decision": result["decision"]}
            recheck.validate_receipt(context.origins, context.state, payload, _formal._utc_now(), context.journal.head)
            row = context.state.append(context.journal, recheck.EVENT, payload)
        # Independent persistent reread also validates an append completed before
        # interruption; no second event or probe is needed for receipt delivery.
        _context(plan_path)
        path = context.journal.root / "events" / f'{row["sequence"]:08d}.json'
        return {"schema_version": "concurrent-recovery-recheck-acceptance-v1",
                "receipt": {"path": str(path), "sha256": _formal._sha256_file(path)},
                "accepted_head_sha256": row["record_sha256"], "provider_calls": 0, "credential_reads": 0}


def accept_recovery_task_parallelism(plan_path: str | Path, *, approval_path: Path,
                                     approval_sha256: str) -> dict[str, Any]:
    """Bind explicit four-way Gemini dispatch to the same safely paused task.

    Zero Provider calls; immutable approval and original cumulative budgets are
    preserved. Repeating the same approval is idempotent even after publication
    succeeded before an interruption. Other hard stops and unknowns stay terminal.
    """
    from . import _concurrent_recovery_parallel as parallel
    from ._concurrent_recovery_campaign import recovery_scope

    context = _context(plan_path)
    reference = _formal.FormalArtifactReference(path=approval_path, sha256=approval_sha256).model_dump(mode='json')
    with recovery_scope(context.origins.campaign):
        context = _context(plan_path)
        approval = parallel._checked(reference)
        existing = next((row for row in context.journal.records if row['kind'] == parallel.EVENT), None)
        if existing is not None:
            if existing['payload']['approval'] != reference:
                raise RecoveryCampaignError('Task already accepted a different parallel approval')
            row = existing
        else:
            if _read_revocation(context.plan) is not None:
                raise RecoveryCampaignError('Revoked task cannot accept parallel execution')
            payload = {'approval': reference, **{key: approval[key] for key in parallel.FIELDS}}
            parallel.validate_receipt(context.origins, context.state, payload, _formal._utc_now(), context.journal.head)
            row = context.state.append(context.journal, parallel.EVENT, payload)
        _context(plan_path)
        path = context.journal.root / 'events' / f'{row["sequence"]:08d}.json'
        return {'schema_version':'concurrent-recovery-parallel-acceptance-v1',
                'receipt':{'path':str(path),'sha256':_formal._sha256_file(path)},
                'accepted_head_sha256':row['record_sha256'],'provider_calls':0,'credential_reads':0}


def accept_recovery_task_quota_retry(plan_path: str | Path, *, approval_path: Path,
                                    approval_sha256: str) -> dict[str, Any]:
    """Accept one explicit retry of this drained quota stop, without new probes.

    The first original failed pair gets one Formal attempt. Only its success
    permits the existing four lanes; any failure stops without automatic retry.
    Repeating this immutable approval returns the original receipt, never a new
    grant. Task, history, budgets, frozen inputs and other hard stops are retained.
    """
    from . import _concurrent_recovery_quota_retry as quota
    from ._concurrent_recovery_campaign import recovery_scope
    context = _context(plan_path)
    reference = _formal.FormalArtifactReference(path=approval_path, sha256=approval_sha256).model_dump(mode='json')
    with recovery_scope(context.origins.campaign):
        context = _context(plan_path)
        approval = quota._checked(reference)
        existing = next((row for row in context.journal.records if row['kind'] == quota.EVENT), None)
        if existing is not None:
            if existing['payload']['approval'] != reference:
                raise RecoveryCampaignError('Task already accepted a different quota retry')
            row = existing
        else:
            if _read_revocation(context.plan) is not None:
                raise RecoveryCampaignError('Revoked task cannot accept quota retry')
            payload = {'approval': reference, 'failed_attempts': approval['failed_attempts']}
            quota.validate_receipt(context.origins, context.state, payload, _formal._utc_now(), context.journal.head)
            row = context.state.append(context.journal, quota.EVENT, payload)
        _context(plan_path)
        path = context.journal.root / 'events' / f'{row["sequence"]:08d}.json'
        return {'schema_version': 'concurrent-recovery-quota-retry-acceptance-v1',
                'receipt': {'path': str(path), 'sha256': _formal._sha256_file(path)},
                'accepted_head_sha256': row['record_sha256'], 'provider_calls': 0, 'credential_reads': 0}


def accept_recovery_task_model_lane(plan_path: str | Path, *, approval_path: Path,
                                    approval_sha256: str) -> dict[str, Any]:
    """Admit Kimi only on the same drained quota-stopped task and cumulative ledger.

    Requires a hash-bound explicit confirmation referencing the exact stopped
    HEAD. Gemini's stop, receipts and unfinished batch are retained; this grants
    no Gemini retry. Kimi receives one original self-check and at most ten
    in-flight requests under Study's exclusive source lock. Other models never
    dispatch. A new hard stop is terminal; Kimi completion is not Study closure.
    Repeating this same approval returns its original receipt without calls.
    """
    from . import _concurrent_recovery_model_lane as lane
    from ._concurrent_recovery_campaign import recovery_scope
    context = _context(plan_path)
    reference = _formal.FormalArtifactReference(path=approval_path, sha256=approval_sha256).model_dump(mode='json')
    with recovery_scope(context.origins.campaign):
        context = _context(plan_path)
        approval = lane._checked(reference)
        existing = next((row for row in context.journal.records if row['kind'] == lane.EVENT), None)
        if existing is not None:
            if existing['payload']['approval'] != reference:
                raise RecoveryCampaignError('Task already accepted a different model lane')
            row = existing
        else:
            if _read_revocation(context.plan) is not None:
                raise RecoveryCampaignError('Revoked task cannot admit a model lane')
            payload = {'approval': reference, **{key: approval[key] for key in lane.FIELDS}}
            lane.validate_receipt(context.origins, context.state, payload, _formal._utc_now(), context.journal.head)
            row = context.state.append(context.journal, lane.EVENT, payload)
        _context(plan_path)
        path = context.journal.root / 'events' / f'{row["sequence"]:08d}.json'
        return {'schema_version': 'concurrent-recovery-model-lane-acceptance-v1',
                'receipt': {'path': str(path), 'sha256': _formal._sha256_file(path)},
                'accepted_head_sha256': row['record_sha256'], 'provider_calls': 0, 'credential_reads': 0}


def accept_recovery_task_kimi_output_amendment(plan_path: str | Path, *, approval_path: Path,
                                                approval_sha256: str) -> dict[str, Any]:
    """Accept Kimi 1024 and exactly one extra self-check on its original stopped task.

    The immutable approval binds the exact HEAD and original failed 256 check.
    Old failures, source, model, Prompt, budgets and suspended Gemini remain.
    A repeated identical receipt dispatches nothing; any new failure stops.
    """
    from . import _concurrent_recovery_output_amendment as amendment
    from ._concurrent_recovery_campaign import recovery_scope
    context = _context(plan_path)
    reference = _formal.FormalArtifactReference(path=approval_path, sha256=approval_sha256).model_dump(mode='json')
    with recovery_scope(context.origins.campaign):
        context = _context(plan_path)
        approval = amendment._checked(reference)
        existing = next((row for row in context.journal.records if row['kind'] == amendment.EVENT), None)
        if existing is not None:
            if existing['payload']['approval'] != reference:
                raise RecoveryCampaignError('Task already accepted a different output amendment')
            row = existing
        else:
            if _read_revocation(context.plan) is not None:
                raise RecoveryCampaignError('Revoked task cannot amend output conditions')
            payload = {'approval': reference, **{key: approval[key] for key in amendment.FIELDS}}
            amendment.validate_receipt(context.origins, context.state, payload, _formal._utc_now(), context.journal.head)
            row = context.state.append(context.journal, amendment.EVENT, payload)
        _context(plan_path)
        path = context.journal.root / 'events' / f'{row["sequence"]:08d}.json'
        return {'schema_version': 'concurrent-recovery-kimi-output-acceptance-v1',
                'receipt': {'path': str(path), 'sha256': _formal._sha256_file(path)},
                'accepted_head_sha256': row['record_sha256'], 'provider_calls': 0, 'credential_reads': 0}


def accept_recovery_task_gemini_restoration(plan_path: str | Path, *, approval_path: Path,
                                           approval_sha256: str) -> dict[str, Any]:
    """Restore Gemini once from its suspended quota stop using an existing probe.

    Preserves the stopped Kimi lane and every cumulative budget and failure.
    One failed-pair Formal trial must succeed before the original four lanes
    continue; any failure stops. Same approval is idempotent, not a renewal.
    This admission performs no Provider calls and authorizes no extra probes.
    """
    from . import _concurrent_recovery_gemini_restoration as restoration
    from ._concurrent_recovery_campaign import recovery_scope

    context = _context(plan_path)
    reference = _formal.FormalArtifactReference(path=approval_path, sha256=approval_sha256).model_dump(mode='json')
    with recovery_scope(context.origins.campaign):
        context = _context(plan_path)
        approval = restoration._checked(reference)
        existing = next((row for row in context.journal.records if row['kind'] == restoration.EVENT), None)
        if existing is not None:
            if existing['payload']['approval'] != reference:
                raise RecoveryCampaignError('Task already accepted a different Gemini restoration')
            row = existing
        else:
            if _read_revocation(context.plan) is not None:
                raise RecoveryCampaignError('Revoked task cannot restore Gemini')
            if not restoration.FIELDS <= set(approval):
                raise RecoveryCampaignError('Gemini restoration approval lacks its bounded scope')
            payload = {'approval': reference, **{key: approval[key] for key in restoration.FIELDS}}
            restoration.validate_receipt(context.origins, context.state, payload, _formal._utc_now(), context.journal.head)
            row = context.state.append(context.journal, restoration.EVENT, payload)
        _context(plan_path)
        path = context.journal.root / 'events' / f'{row["sequence"]:08d}.json'
        return {'schema_version': 'concurrent-recovery-gemini-restoration-acceptance-v1',
                'receipt': {'path': str(path), 'sha256': _formal._sha256_file(path)},
                'accepted_head_sha256': row['record_sha256'], 'provider_calls': 0, 'credential_reads': 0}


def accept_recovery_task_kimi_official_migration(plan_path: str | Path, *, approval_path: Path,
                                           approval_sha256: str) -> dict[str, Any]:
    """Record a bound official Kimi migration authorization without dispatch.

    Keeps the current completed model stage and every original budget/history.
    Repeating the same receipt is idempotent. Activation requires the subsequent
    execution preflight; admission itself does not restore or run a Provider.
    """
    from . import _concurrent_recovery_kimi_migration as restoration
    from ._concurrent_recovery_campaign import recovery_scope
    from ._concurrent_recovery_recheck import _checked

    context = _context(plan_path)
    reference = _formal.FormalArtifactReference(path=approval_path, sha256=approval_sha256).model_dump(mode='json')
    with recovery_scope(context.origins.campaign):
        context = _context(plan_path)
        approval = _checked(reference)
        existing = next((row for row in context.journal.records if row['kind'] == restoration.EVENT), None)
        if existing is not None:
            if existing['payload']['approval'] != reference:
                raise RecoveryCampaignError('Task already accepted a different Kimi official migration')
            row = existing
        else:
            if _read_revocation(context.plan) is not None:
                raise RecoveryCampaignError('Revoked task cannot admit Kimi migration')
            if not restoration.FIELDS <= set(approval):
                raise RecoveryCampaignError('Kimi official migration approval lacks its bounded scope')
            payload = {'approval': reference, **{key: approval[key] for key in restoration.FIELDS}}
            restoration.validate_receipt(context.origins, context.state, payload, _formal._utc_now(), context.journal.head)
            row = context.state.append(context.journal, restoration.EVENT, payload)
        _context(plan_path)
        path = context.journal.root / 'events' / f'{row["sequence"]:08d}.json'
        return {'schema_version': 'concurrent-recovery-kimi-official-migration-acceptance-v1',
                'receipt': {'path': str(path), 'sha256': _formal._sha256_file(path)},
                'accepted_head_sha256': row['record_sha256'], 'provider_calls': 0, 'credential_reads': 0}


def accept_recovery_task_kimi_manual_retry(plan_path: str | Path, *, approval_path: Path,
                                          approval_sha256: str) -> dict[str, Any]:
    """Archive four approved unknown intents and permit one manual retry each.

    Reuses the original Study lock, history and budgets. Does not dispatch or
    increase the cash cap. Repeating the same immutable receipt is read-only.
    """
    from . import _concurrent_recovery_manual_retry as manual
    from ._concurrent_recovery_campaign import recovery_scope
    from ._concurrent_recovery_kimi_migration import _evidence

    context = _context(plan_path)
    reference = _formal.FormalArtifactReference(path=approval_path, sha256=approval_sha256).model_dump(mode='json')
    with recovery_scope(context.origins.campaign):
        context = _context(plan_path)
        approval = _evidence(reference)
        existing = next((row for row in context.journal.records if row['kind'] == manual.EVENT), None)
        if existing is not None:
            if existing['payload']['approval'] != reference:
                raise RecoveryCampaignError('Task already accepted a different manual retry receipt')
            row = existing
        else:
            if _read_revocation(context.plan) is not None:
                raise RecoveryCampaignError('Revoked task cannot admit manual retries')
            payload = {'approval': reference, 'unknown_intents': [
                {key: item[key] for key in ('cell_index', 'pair_schedule_position', 'attempt_number', 'intent_sha256')}
                for item in approval['unknown_intents']]}
            manual.validate_receipt(context.origins, context.state, payload, _formal._utc_now(), context.journal.head)
            row = context.state.append(context.journal, manual.EVENT, payload)
        _context(plan_path)
        path = context.journal.root / 'events' / f'{row["sequence"]:08d}.json'
        return {'schema_version': 'concurrent-recovery-kimi-manual-retry-acceptance-v1',
                'receipt': {'path': str(path), 'sha256': _formal._sha256_file(path)},
                'accepted_head_sha256': row['record_sha256'], 'provider_calls': 0, 'credential_reads': 0}


def accept_recovery_task_kimi_retry_policy(plan_path: str | Path, *, approval_path: Path,
                                          approval_sha256: str) -> dict[str, Any]:
    """Admit the user's bounded retry amendment without dispatch or budget reset."""
    from . import _concurrent_recovery_kimi_retry as retry
    from ._concurrent_recovery_campaign import recovery_scope
    from ._concurrent_recovery_kimi_migration import _evidence

    context = _context(plan_path)
    reference = _formal.FormalArtifactReference(path=approval_path, sha256=approval_sha256).model_dump(mode='json')
    with recovery_scope(context.origins.campaign):
        context = _context(plan_path)
        approval = _evidence(reference)
        existing = next((row for row in context.journal.records if row['kind'] == retry.EVENT), None)
        if existing is not None:
            if existing['payload']['approval'] != reference:
                raise RecoveryCampaignError('Task already accepted a different retry policy')
            row = existing
        else:
            if _read_revocation(context.plan) is not None:
                raise RecoveryCampaignError('Revoked task cannot admit retries')
            payload = {'approval': reference, 'legacy_exception': approval['legacy_exception'],
                       **{k: approval[k] for k in retry.POLICY}}
            retry.validate_receipt(context.origins, context.state, payload, _formal._utc_now(), context.journal.head)
            row = context.state.append(context.journal, retry.EVENT, payload)
        _context(plan_path)
        path = context.journal.root / 'events' / f'{row["sequence"]:08d}.json'
        return {'schema_version': 'kimi-bounded-retry-acceptance-v1',
                'receipt': {'path': str(path), 'sha256': _formal._sha256_file(path)},
                'accepted_head_sha256': row['record_sha256'], 'provider_calls': 0, 'credential_reads': 0}


def accept_recovery_task_kimi_cash_cap(plan_path: str | Path, *, approval_path: Path,
                                          approval_sha256: str) -> dict[str, Any]:
    """Admit the approved cumulative cash cap without resetting prior spend."""
    from ._concurrent_recovery_campaign import recovery_scope
    from ._concurrent_recovery_kimi_migration import _evidence, validate_cash_cap_receipt

    context = _context(plan_path)
    reference = _formal.FormalArtifactReference(path=approval_path, sha256=approval_sha256).model_dump(mode='json')
    with recovery_scope(context.origins.campaign):
        context = _context(plan_path)
        approval = _evidence(reference)
        existing = next((row for row in context.journal.records if row['kind'] == 'kimi_cash_cap_amendment_accepted'), None)
        if existing is not None:
            if existing['payload']['approval'] != reference:
                raise RecoveryCampaignError('Task already accepted a different cash cap amendment')
            row = existing
        else:
            if _read_revocation(context.plan) is not None:
                raise RecoveryCampaignError('Revoked task cannot amend the cash cap')
            payload = {'approval': reference, **{k: approval[k] for k in ('previous_maximum_spend_cny', 'maximum_spend_cny')}}
            validate_cash_cap_receipt(context.origins, context.state, payload, _formal._utc_now(), context.journal.records[-1])
            row = context.state.append(context.journal, 'kimi_cash_cap_amendment_accepted', payload)
        _context(plan_path)
        path = context.journal.root / 'events' / f'{row["sequence"]:08d}.json'
        return {'schema_version': 'kimi-cash-cap-acceptance-v1',
                'receipt': {'path': str(path), 'sha256': _formal._sha256_file(path)},
                'accepted_head_sha256': row['record_sha256'], 'provider_calls': 0, 'credential_reads': 0}


def accept_recovery_task_final_model(plan_path: str | Path, *, approval_path: Path,
                                    approval_sha256: str) -> dict[str, Any]:
    """Continue only GPT-5.6 after all three prior models complete.

    The immutable receipt excludes untouched Flash and binds the exact completed
    HEAD. This preserves original scope evidence and cumulative physical budgets.
    Uses the original serial adapter, self-check and retry policy. Repeating the
    same receipt performs no dispatch or append; any conflicting receipt fails.
    """
    from . import _concurrent_recovery_final_model as lane
    from ._concurrent_recovery_campaign import recovery_scope
    context = _context(plan_path)
    reference = _formal.FormalArtifactReference(path=approval_path, sha256=approval_sha256).model_dump(mode='json')
    with recovery_scope(context.origins.campaign):
        context = _context(plan_path)
        approval = lane._checked(reference)
        existing = next((row for row in context.journal.records if row['kind'] == lane.EVENT), None)
        if existing is not None:
            if existing['payload']['approval'] != reference:
                raise RecoveryCampaignError('Task already accepted a different model lane')
            row = existing
        else:
            if _read_revocation(context.plan) is not None:
                raise RecoveryCampaignError('Revoked task cannot admit a model lane')
            payload = {'approval': reference, **{key: approval[key] for key in lane.FIELDS}}
            lane.validate_receipt(context.origins, context.state, payload, _formal._utc_now(), context.journal.head)
            row = context.state.append(context.journal, lane.EVENT, payload)
        _context(plan_path)
        path = context.journal.root / 'events' / f'{row["sequence"]:08d}.json'
        return {'schema_version': 'concurrent-recovery-final-model-acceptance-v1',
                'receipt': {'path': str(path), 'sha256': _formal._sha256_file(path)},
                'accepted_head_sha256': row['record_sha256'], 'provider_calls': 0, 'credential_reads': 0}


def accept_recovery_task_final_model_parallel(plan_path: str | Path, *, approval_path: Path,
                                    approval_sha256: str) -> dict[str, Any]:
    """Admit five GPT lanes on the same drained paused task; repeat is read-only."""
    from . import _concurrent_recovery_final_model as lane
    from ._concurrent_recovery_campaign import recovery_scope
    context = _context(plan_path)
    reference = _formal.FormalArtifactReference(path=approval_path, sha256=approval_sha256).model_dump(mode='json')
    with recovery_scope(context.origins.campaign):
        context = _context(plan_path)
        approval = lane._checked(reference)
        existing = next((row for row in context.journal.records if row['kind'] == lane.PARALLEL_EVENT), None)
        if existing is not None:
            if existing['payload']['approval'] != reference:
                raise RecoveryCampaignError('Task already accepted a different model lane')
            row = existing
        else:
            if _read_revocation(context.plan) is not None:
                raise RecoveryCampaignError('Revoked task cannot admit a model lane')
            payload = {'approval': reference, **{key: approval[key] for key in lane.PARALLEL_FIELDS}}
            lane.validate_parallel_receipt(context.origins, context.state, payload, _formal._utc_now(), context.journal.head)
            row = context.state.append(context.journal, lane.PARALLEL_EVENT, payload)
        _context(plan_path)
        path = context.journal.root / 'events' / f'{row["sequence"]:08d}.json'
        return {'schema_version': 'concurrent-recovery-final-model-parallel-acceptance-v1',
                'receipt': {'path': str(path), 'sha256': _formal._sha256_file(path)},
                'accepted_head_sha256': row['record_sha256'], 'provider_calls': 0, 'credential_reads': 0}

