"""Hash-bound evidence for one explicitly approved, already-settled recheck.

This Module reads evidence only. It grants neither new probes nor a new task.
The Task Module owns lock/admission; legal replay uses the same validator.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from . import concurrent_robustness_formal_execution as _formal
from . import concurrent_robustness_recovery_epoch as _initial
from . import concurrent_robustness_recovery_execution as _execution
from . import concurrent_robustness_v2 as _v2
from ._concurrent_recovery_campaign import RecoveryCampaignError, _read
from ._concurrent_recovery_progress import CampaignProgress
from .providers.robustness import robustness_provider_disclosures

EVENT = "self_check_recheck_accepted"
REFERENCES = ("task_plan", "failed_settlement", "probe_authorization", "probe_intent", "probe_result")


def _checked(value: Any) -> dict[str, Any]:
    reference = _formal.FormalArtifactReference.model_validate(value)
    _initial._checked_reference(reference)
    return _read(reference.path)


def _require(condition: bool) -> None:
    if not condition:
        raise RecoveryCampaignError("Explicit recheck evidence differs from its approved stopped task")


def validate_receipt(origins: _execution._Origins, state: CampaignProgress,
                     payload: dict[str, Any], when: datetime, head: str) -> None:
    from . import concurrent_robustness_recovery_task as task

    _require(set(payload) == {"approval", "requested_model", "attempt", "decision"})
    approval = _checked(payload["approval"])
    _require(set(approval) == {"schema_version", "status", "authorization_reference", "approved_at_utc",
                              "stopped_head_sha256", *REFERENCES})
    _require(approval["schema_version"] == "concurrent-recovery-recheck-approval-v1" and approval["status"] == "approved")
    _formal._safe_reference(approval["authorization_reference"], "recheck approval reference")
    _require(bool(approval["authorization_reference"]) and not approval["authorization_reference"].startswith("REPLACE-"))
    _require(approval["task_plan"] == origins.handoff.model_dump(mode="json") and approval["stopped_head_sha256"] == head)
    assert origins.task_plan is not None
    _require(task._current(origins.task_plan, when))
    model = state.current_model
    _require(isinstance(model, str) and payload["requested_model"] == model)
    assert model is not None
    health = task._health_contract(origins, model)
    failed = _checked(approval["failed_settlement"])
    _require(failed["kind"] == "self_check_settled" and failed["record_sha256"] == head
             and failed["campaign_identity_sha256"] == origins.campaign["campaign_identity_sha256"]
             and failed["payload"] == state.self_checks.get(model))
    expected_failure_path = Path(origins.campaign["control_root"]) / "events" / f'{failed["sequence"]:08d}.json'
    _require(approval["failed_settlement"]["path"] == str(expected_failure_path))
    auth = _checked(approval["probe_authorization"])
    intent = _checked(approval["probe_intent"])
    result = _checked(approval["probe_result"])
    expected_auth = {
        "schema_version": "recovery-explicit-single-probe-authorization-v1", "previous_task_plan": approval["task_plan"],
        "requested_model": model, "required_observed_model": health["route"]["required_observed_model"],
        "route": health["route"], "self_check_prompt_sha256": health["prompt_sha256"],
        "maximum_new_attempts": 1, "automatic_retries": 0, "effective_probe_retries": 0,
        "new_formal_attempts_authorized": 0, "previous_task_self_check_attempts": 1,
        "inherited_formal_request_contract": origins.source.manifest.request_contract.model_dump(mode="json"),
        "request_timeout_seconds": origins.source.request.run_parameters.request_timeout_seconds,
        "other_models_authorized": [], "old_failure_kept": True, "task_reset_or_reauthorization": False,
        "release_or_deployment": False, "production_deploy_eligible": False,
        "fee_policy": "optional_best_effort_no_cash_ceiling_v1",
    }
    _require(all(_formal._canonical_json_bytes({"v": auth.get(k)}) == _formal._canonical_json_bytes({"v": v})
                 for k, v in expected_auth.items()))
    _require(intent["schema_version"] == "recovery-explicit-single-probe-intent-v1"
             and intent["authorization_sha256"] == approval["probe_authorization"]["sha256"]
             and intent["requested_model"] == model and type(intent["attempt_number"]) is int
             and intent["attempt_number"] == 1 and type(intent["maximum_attempts"]) is int and intent["maximum_attempts"] == 1)
    cell = next(cell for cell in origins.source.manifest.prompt_model_cells if cell.requested_model == model)
    disclosure = next(row for row in robustness_provider_disclosures() if row["requested_model"] == model)
    keys = {"provider_route", "requested_model", "required_observed_model", "wire_api", "reasoning_effort",
            "thinking_mode", "thinking_budget", "output_token_ceiling", "wire_output_token_ceiling",
            "output_token_ceiling_scope", "billing_semantics", "billing_currency", "fee_ceiling"}
    expected_request = {k: disclosure[k] for k in keys}
    expected_request.update(schema_version="robustness-provider-request-evidence-v2",
        prompt_version=cell.prompt_version, prompt_canonical_hash=cell.prompt_canonical_hash,
        structured_output_schema_version=origins.source.manifest.request_contract.structured_output_schema_version,
        structured_output_schema_hash=origins.source.manifest.request_contract.structured_output_schema_hash,
        maximum_physical_attempts_per_logical_pair=3)
    _require(_formal._canonical_json_bytes(intent["request_evidence"]) == _formal._canonical_json_bytes(expected_request))
    _require(result["schema_version"] == "recovery-explicit-single-probe-result-v1" and result["status"] == "succeeded"
             and result["authorization_sha256"] == approval["probe_authorization"]["sha256"]
             and result["intent_sha256"] == approval["probe_intent"]["sha256"]
             and result["campaign_not_resumed"] is True and type(result["new_formal_attempts"]) is int
             and result["new_formal_attempts"] == 0 and result["release_or_deployment"] is False
             and result["attempt"] == payload["attempt"] and result["decision"] == payload["decision"])
    times = [_formal._parse_utc(value, "recheck evidence time") for value in
             (failed["recorded_at_utc"], auth["approved_at_utc"], intent["at_utc"], result["settled_at_utc"], approval["approved_at_utc"])]
    _require(times == sorted(times) and times[-1] <= when)
    attempt = _v2._V2AttemptEvidence.model_validate(result["attempt"])
    _require(attempt.outcome == "succeeded" and attempt.attempt_number == 1 and attempt.request_invocations == 1
             and attempt.successful_decision_count == 1 and attempt.failure_category is None
             and attempt.wait_seconds is None and attempt.wait_source is None and not attempt.lane_cooldown)
    task._validate_task_event(origins, state, "self_check_settled",
        {k: payload[k] for k in ("requested_model", "attempt", "decision")}, when)
    # Transition owns the narrow stop class and cumulative accounting checks.
    state.transition(EVENT, payload)


def receipt_references(payload: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """Return the transitive immutable inputs required by independent bundles."""
    approval = _checked(payload["approval"])
    return (payload["approval"], *(approval[name] for name in REFERENCES))
