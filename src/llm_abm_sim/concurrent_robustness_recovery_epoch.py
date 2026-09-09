"""Zero-call preparation of the first recovery epoch, not a recovery runner.

This initial-epoch approval handoff cannot admit an epoch, claim a campaign,
reserve attempts, dispatch Providers or close Formal Evidence. The legacy run
remains terminal. Campaign ledger/replay/execution belong to the remaining #253
implementation, rather than an implicit fallback through the old v2 runner.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import model_validator

from . import concurrent_robustness_formal_execution as _formal
from . import concurrent_robustness_recovery as _proposals
from . import concurrent_robustness_v2 as _v2

INITIAL_EPOCH_REQUEST_SCHEMA = "concurrent-robustness-recovery-initial-epoch-request-v1"
INITIAL_EPOCH_PLAN_SCHEMA = "concurrent-robustness-recovery-initial-epoch-plan-v1"
INITIAL_EPOCH_AUTHORIZATION_SCHEMA = "concurrent-robustness-recovery-initial-epoch-authorization-v1"


class RecoveryInitialEpochError(ValueError):
    """Initial-epoch preparation failed without echoing supplied values."""


class RecoveryInitialEpochRequest(_formal._FrozenModel):
    schema_version: Literal["concurrent-robustness-recovery-initial-epoch-request-v1"] = INITIAL_EPOCH_REQUEST_SCHEMA
    proposal: _formal.FormalArtifactReference
    qualification_artifacts: tuple[_formal.FormalQualificationArtifactReference, ...]

    @model_validator(mode="after")
    def _models(self) -> RecoveryInitialEpochRequest:
        if tuple(item.requested_model for item in self.qualification_artifacts) != tuple(
            row["requested_model"] for row in _formal._expected_routes()
        ):
            raise ValueError("Recovery requires five ordered independent qualifications")
        return self


def _checked_reference(reference: _formal.FormalArtifactReference) -> dict[str, Any]:
    fact = _proposals._file_fact(reference.path)
    if fact["sha256"] != reference.sha256:
        raise RecoveryInitialEpochError("Recovery artifact differs from its bound hash")
    document, _ = _formal._load_canonical_object(reference.path, "initial recovery epoch artifact")
    return document


def _inherited_context(
    reference: _formal.FormalArtifactReference,
) -> tuple[dict[str, Any], _formal.FormalPlanInspection]:
    _checked_reference(reference)
    proposal, inherited = _proposals._read_recovery_proposal(reference.path)
    _checked_reference(reference)
    return proposal, inherited


def _campaign_identity(proposal: dict[str, Any]) -> dict[str, Any]:
    output = Path(proposal["output_root"])
    control = _proposals._safe_path(output.with_name(f".{output.name}.recovery-control"))
    source_output = Path(proposal["source_output_root"])
    source_key = _v2._json_sha256({
        "source_output_root": str(source_output), "source_plan_sha256": proposal["source_plan"]["sha256"],
    })
    # Derive from the original output, not the proposal/plan's location. Copying
    # a plan or creating another proposal must not select another source anchor.
    anchor = _proposals._safe_path(source_output.parent.parent / f".recovery-campaign-{source_key}.json")
    protected = [Path(row["path"]).parent for row in proposal["source_artifacts"]]
    protected.append(output)
    if not anchor.parent.is_dir() or any(
        candidate == root or candidate.is_relative_to(root) or root.is_relative_to(candidate)
        for candidate in (control, anchor) for root in protected
    ):
        raise RecoveryInitialEpochError("Recovery campaign scope overlaps protected evidence")
    body = {
        "schema_version": "concurrent-robustness-recovery-campaign-identity-v1",
        "control_root": str(control), "output_root": str(output), "source_anchor_path": str(anchor),
        "proposal_identity_sha256": proposal["proposal_identity_sha256"],
        "frozen_context": proposal["frozen_context"], "model_budgets": proposal["model_budgets"],
        "logical_judgment_cap": proposal["logical_judgment_cap"],
        "physical_attempt_cap": proposal["physical_attempt_cap"],
        "maximum_new_physical_attempts": proposal["maximum_new_physical_attempts"],
        "maximum_cumulative_physical_attempts": proposal["maximum_cumulative_physical_attempts"],
        "historical_failed_pair": proposal["failed_pair"],
    }
    return {**body, "campaign_identity_sha256": _v2._json_sha256(body)}


def _initial_readiness(
    request: RecoveryInitialEpochRequest, *, now: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    proposal, inherited = _inherited_context(request.proposal)
    campaign = _campaign_identity(proposal)
    qualifications = []
    for reference, route in zip(request.qualification_artifacts, inherited.request.provider_routes, strict=True):
        _checked_reference(reference)
        checked = _formal._validate_qualification(reference=reference, route=route, now=now)
        evidence = cast(dict[str, object], checked["evidence"])
        if any(type(evidence[key]) is not bool for key in (
            "structured_decision_valid", "usage_complete", "raw_prompt_persisted",
            "raw_response_persisted", "credential_material_persisted",
        )):
            raise RecoveryInitialEpochError("Recovery qualification flags must be booleans")
        qualifications.append({**reference.model_dump(mode="json"), "evidence": evidence})
    remaining = next(row for row in proposal["model_budgets"] if row["remaining_valid_judgments"] > 0)
    identity = {
        "schema_version": "concurrent-robustness-recovery-initial-epoch-identity-v1",
        "campaign": campaign, "proposal": request.proposal.model_dump(mode="json"),
        "proposal_identity_sha256": proposal["proposal_identity_sha256"],
        "expected_head_sha256": campaign["campaign_identity_sha256"],
        "epoch_ordinal": 1, "requested_model": remaining["requested_model"],
        "remaining_valid_judgments": proposal["remaining_valid_judgments"],
        "maximum_new_physical_attempts": proposal["maximum_new_physical_attempts"],
        "model_budgets": proposal["model_budgets"], "qualification_artifacts": qualifications,
        "provider_routes": [row.model_dump(mode="json") for row in inherited.request.provider_routes],
        "provider_caps": [row.model_dump(mode="json") for row in inherited.request.provider_caps],
        "run_parameters": inherited.request.run_parameters.model_dump(mode="json"),
        "historical_all_attempts_total_tokens": None,
    }
    digest = _v2._json_sha256(identity)
    template = {
        "schema_version": INITIAL_EPOCH_AUTHORIZATION_SCHEMA, "status": "approved",
        "authorization_reference": "REPLACE-WITH-INDEPENDENT-OPERATIONAL-ISSUE",
        "approved_at_utc": "REPLACE-WITH-UTC-SECOND",
        "expires_at_utc": "REPLACE-WITH-UTC-SECOND-WITHIN-24-HOURS",
        "request_identity_sha256": digest, "request_identity": identity,
    }
    return {
        "schema_version": "concurrent-robustness-recovery-initial-epoch-readiness-v1",
        "status": "ready_for_human", "request_identity": identity,
        "request_identity_sha256": digest, "authorization_template": template,
        "execution_authority": False, "recovery_slots_consumed": 0,
        "provider_calls": 0, "credential_reads": 0, "production_deploy_eligible": False,
    }, proposal


def _require_unused_initial_scope(readiness: dict[str, Any]) -> None:
    campaign = readiness["request_identity"]["campaign"]
    if any(Path(campaign[key]).exists() for key in ("control_root", "source_anchor_path")):
        raise RecoveryInitialEpochError("Initial epoch preparation requires an unused source anchor and control scope")


def prepare_recovery_initial_epoch(request: RecoveryInitialEpochRequest) -> dict[str, Any]:
    """Recompute the initial approval packet without locks, writes or authority."""
    readiness, _ = _initial_readiness(request, now=_formal._utc_now())
    _require_unused_initial_scope(readiness)
    return readiness


def _validate_approval(
    reference: _formal.FormalArtifactReference, readiness: dict[str, Any], *, now: datetime,
) -> dict[str, Any]:
    document = _checked_reference(reference)
    expected = dict(readiness["authorization_template"])
    editable = ("authorization_reference", "approved_at_utc", "expires_at_utc")
    if set(document) != set(expected):
        raise RecoveryInitialEpochError("Recovery approval fields are not exact")
    reference_token = document["authorization_reference"]
    if not isinstance(reference_token, str) or reference_token.startswith("REPLACE-"):
        raise RecoveryInitialEpochError("Recovery requires explicit independent approval")
    _formal._safe_reference(reference_token, "recovery authorization reference")
    _formal._validate_current_window(
        starts_at=document["approved_at_utc"], expires_at=document["expires_at_utc"],
        label="Recovery authorization", maximum_window=_formal._MAX_AUTHORIZATION_WINDOW, now=now,
    )
    expected.update({key: document[key] for key in editable})
    if _formal._canonical_json_bytes(document) != _formal._canonical_json_bytes(expected):
        raise RecoveryInitialEpochError("Recovery approval differs from verified scope and head")
    return document


def _validate_plan_location(path: Path, proposal: dict[str, Any], campaign: dict[str, Any]) -> Path:
    target = _proposals._safe_path(path)
    protected = [Path(proposal["output_root"]), Path(campaign["control_root"]), Path(campaign["source_anchor_path"])]
    protected.extend(Path(row["path"]).parent for row in proposal["source_artifacts"])
    if any(target == root or target.is_relative_to(root) or root.is_relative_to(target) for root in protected):
        raise RecoveryInitialEpochError("Recovery plan overlaps protected evidence or campaign scope")
    if not target.parent.is_dir():
        raise RecoveryInitialEpochError("Recovery plan requires an existing parent")
    return target


def _publish_immutable(path: Path, document: dict[str, Any]) -> None:
    pending = path.with_name(f".{path.name}.pending")
    with pending.open("xb") as handle:
        handle.write(_formal._canonical_json_bytes(document))
        handle.flush()
        os.fsync(handle.fileno())
    pending.chmod(0o444)
    os.link(pending, path, follow_symlinks=False)
    pending.unlink()
    _v2._fsync_directory(path.parent)


def _plan_body(
    request: RecoveryInitialEpochRequest, authorization_reference: _formal.FormalArtifactReference,
    authorization: dict[str, Any], target: Path,
) -> dict[str, Any]:
    return {
        "schema_version": INITIAL_EPOCH_PLAN_SCHEMA, "plan_path": str(target),
        "request": request.model_dump(mode="json"),
        "authorization_artifact": authorization_reference.model_dump(mode="json"),
        "authorization": authorization, "initial_epoch_only": True,
        "execution_authority": False, "recovery_slots_consumed": 0,
    }


def authorize_recovery_initial_epoch(
    *, request: RecoveryInitialEpochRequest, authorization_path: Path,
    authorization_sha256: str, plan_output: Path,
) -> dict[str, Any]:
    """Persist exact first-epoch approval, without claiming an anchor or a slot."""
    now = _formal._utc_now()
    readiness, proposal = _initial_readiness(request, now=now)
    _require_unused_initial_scope(readiness)
    reference = _formal.FormalArtifactReference(path=authorization_path, sha256=authorization_sha256)
    authorization = _validate_approval(reference, readiness, now=now)
    # Independent qualification evidence must already exist at approval time;
    # an approval cannot retroactively cover qualifications obtained afterwards.
    _initial_readiness(request, now=_formal._parse_utc(authorization["approved_at_utc"], "recovery approval time"))
    target = _validate_plan_location(plan_output, proposal, readiness["request_identity"]["campaign"])
    if target.exists():
        raise RecoveryInitialEpochError("Recovery plan requires a new path")
    body = _plan_body(request, reference, authorization, target)
    plan = {**body, "plan_identity_sha256": _v2._json_sha256(body)}
    _publish_immutable(target, plan)
    # Failed inspection leaves an explicit invalid/incomplete artifact, never
    # removes a create-once file or another writer's install collision.
    _read_initial_epoch_plan(target)
    return plan


def _read_initial_epoch_plan(plan_path: str | Path) -> dict[str, Any]:
    path = _proposals._safe_path(plan_path)
    fact = _proposals._file_fact(path)
    if cast(int, fact["mode"]) & 0o222:
        raise RecoveryInitialEpochError("Initial recovery epoch plan must be immutable")
    plan = _checked_reference(_formal.FormalArtifactReference(path=path, sha256=cast(str, fact["sha256"])))
    request = RecoveryInitialEpochRequest.model_validate(plan.get("request"))
    reference = _formal.FormalArtifactReference.model_validate(plan.get("authorization_artifact"))
    authorization = _checked_reference(reference)
    approved_at = _formal._parse_utc(authorization.get("approved_at_utc"), "recovery approval time")
    readiness, proposal = _initial_readiness(request, now=approved_at)
    _validate_plan_location(path, proposal, readiness["request_identity"]["campaign"])
    approval = _validate_approval(reference, readiness, now=approved_at)
    body = _plan_body(request, reference, approval, path)
    expected = {**body, "plan_identity_sha256": _v2._json_sha256(body)}
    if _formal._canonical_json_bytes(expected) != _formal._canonical_json_bytes(plan):
        raise RecoveryInitialEpochError("Initial recovery epoch plan differs from its persisted origins")
    return expected


def inspect_recovery_initial_epoch_plan(plan_path: str | Path) -> dict[str, Any]:
    """Verify the persisted initial handoff; current expiry is not historical fraud.

    This is not campaign status or epoch admission, even when all windows are
    current. The source anchor and private runtime are neither opened nor repaired.
    """
    plan = _read_initial_epoch_plan(plan_path)
    now = _formal._utc_now()
    authorization = plan["authorization"]
    identity = authorization["request_identity"]

    def current(start: str, end: str) -> bool:
        return _formal._parse_utc(start, "window start") <= now < _formal._parse_utc(end, "window expiry")

    qualifications = [{
        "requested_model": row["requested_model"],
        "currently_valid": current(row["evidence"]["qualified_at_utc"], row["evidence"]["expires_at_utc"]),
    } for row in identity["qualification_artifacts"]]
    authorization_current = current(authorization["approved_at_utc"], authorization["expires_at_utc"])
    return {
        "schema_version": "concurrent-robustness-recovery-initial-epoch-inspection-v1",
        "status": "verified_initial_handoff", "plan_identity_sha256": plan["plan_identity_sha256"],
        "current_gate": {"checked_at_utc": now.isoformat(), "authorization_current": authorization_current,
                         "qualifications": qualifications,
                         "currently_valid": authorization_current and all(row["currently_valid"] for row in qualifications)},
        "remaining_valid_judgments_at_preparation": identity["remaining_valid_judgments"],
        "maximum_new_physical_attempts_at_preparation": identity["maximum_new_physical_attempts"],
        "inspection_only": True, "execution_authority": False, "recovery_slots_consumed": 0,
        "provider_calls": 0, "credential_reads": 0, "production_deploy_eligible": False,
    }
