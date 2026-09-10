"""One hash-bound restoration of suspended Gemini, never a quota retry policy."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import datetime
from typing import TYPE_CHECKING, Any

from . import concurrent_robustness_formal_execution as formal
from . import concurrent_robustness_v2 as v2
from ._concurrent_recovery_campaign import RecoveryCampaignError
from ._concurrent_recovery_recheck import _checked

if TYPE_CHECKING:
    from ._concurrent_recovery_progress import CampaignProgress
    from .concurrent_robustness_recovery_execution import _Origins

EVENT = "gemini_restoration_accepted"
MODEL = "gemini-3.1-pro"
KIMI = "kimi-coding/k3-256k"
PROBE_REFS = ("probe_authorization", "probe_intent", "probe_result", "probe_receipt")
FIELDS = {"requested_model", "maximum_inflight", "stop_after_model", "failed_attempts"}


def _require(value: bool) -> None:
    if not value:
        raise RecoveryCampaignError("Gemini restoration differs from its one approved drained stop")


def terms(state: CampaignProgress) -> list[dict[str, Any]]:
    suspended = state.suspended_models.get(MODEL)
    _require(
        state.gemini_restoration_approval is None
        and state.status == "stopped"
        and state.current_model == KIMI
        and state.model_lane_approval is not None
        and state.task_plan is not None
        and not state.task_revoked
        and not state.has_inflight
        and not state.parallel_unknown
        and state.self_check_inflight is None
        and state.reservation is None
        and state.pending_judgment is None
        and state.pending_realized is None
        and state.quota_retry_pending is None
        and suspended is not None
    )
    assert suspended is not None
    _require(
        suspended["status"] == "stopped"
        and suspended["parallel_active_batch"] is not None
        and suspended["parallel_approval"] == state.parallel_approval
        and suspended["quota_retry_approval"] == state.quota_retry_approval
    )
    check = state.effective_self_check(MODEL)
    _require(check is not None and check["attempt"]["outcome"] == "succeeded")
    kimi_check = state.effective_self_check(KIMI)
    _require(kimi_check is not None and kimi_check["attempt"]["outcome"] == "succeeded")
    cap = next(
        row["maximum_new_physical_attempts"]
        for row in state.proposal["model_budgets"]
        if row["requested_model"] == MODEL
    )
    _require(
        state.physical_attempts < state.proposal["maximum_new_physical_attempts"]
        and state.physical_by_model[MODEL] < cap
    )
    failures = []
    kimi_failures = 0
    for key, attempts in sorted(state.new_attempts.items()):
        last = attempts[-1]
        if last.outcome in {"succeeded", "retryable_failure"}:
            continue
        model = state.cells[key[0]].requested_model
        if model == KIMI:
            _require(
                last.outcome == "nonretryable_failure"
                and last.failure_category == "entitlement"
                and last.status_code == 403
            )
            kimi_failures += 1
            continue
        _require(
            model == MODEL
            and last.outcome == "nonretryable_failure"
            and last.failure_category == "quota_exhausted"
            and len(state.attempts(key)) < 3
            and key not in state.old_successes
            and key not in state.success_decisions
            and key not in state.judgments
            and (key[0], key[1] // (state.per_cell // 30)) == suspended["parallel_active_batch"]
        )
        failures.append(
            {
                "cell_index": key[0],
                "pair_schedule_position": key[1],
                "attempt_sha256": v2._json_sha256(last.model_dump(mode="json")),
            }
        )
    _require(kimi_failures > 0 and 1 <= len(failures) <= 4)
    return failures


def transition(state: CampaignProgress, payload: dict[str, Any]) -> Callable[[], None]:
    state._exact(payload, {"approval", *FIELDS})
    state._exact(payload["approval"], {"path", "sha256"})
    v2._require_sha256(payload["approval"]["sha256"], "Gemini restoration approval")
    _require(
        isinstance(payload["approval"]["path"], str)
        and payload["approval"]["path"].startswith("/")
        and payload["requested_model"] == MODEL
        and payload["stop_after_model"] is True
        and type(payload["maximum_inflight"]) is int
        and payload["maximum_inflight"] == 4
        and payload["failed_attempts"] == terms(state)
    )

    def accept() -> None:
        state.suspended_models[KIMI] = {
            "status": state.status,
            "parallel_active_batch": state.parallel_active_batch,
            "model_lane_approval": deepcopy(state.model_lane_approval),
            "output_amendment": deepcopy(state.output_amendment),
        }
        state.gemini_restoration_approval = deepcopy(payload)
        state.parallel_active_batch = state.suspended_models[MODEL]["parallel_active_batch"]
        first = payload["failed_attempts"][0]
        state.quota_retry_pending = (first["cell_index"], first["pair_schedule_position"])
        # A fresh Gemini epoch is derived; the most recent epoch belongs to Kimi.
        state.status = "ready"

    return accept


def validate_receipt(
    origins: _Origins, state: CampaignProgress, payload: dict[str, Any], when: datetime, head: str
) -> None:
    from . import concurrent_robustness_recovery_task as task

    state._exact(payload, {"approval", *FIELDS})
    approval = _checked(payload["approval"])
    state._exact(
        approval,
        {
            "schema_version",
            "status",
            "authorization_reference",
            "approved_at_utc",
            "task_plan",
            "stopped_head_sha256",
            "initial_formal_attempts",
            "additional_probes",
            *FIELDS,
            *PROBE_REFS,
        },
    )
    _require(
        origins.task_plan is not None
        and approval["schema_version"] == "concurrent-recovery-gemini-restoration-approval-v1"
        and approval["status"] == "approved"
        and approval["task_plan"] == origins.handoff.model_dump(mode="json")
        and approval["stopped_head_sha256"] == head
        and all(approval[k] == payload[k] for k in FIELDS)
        and type(approval["initial_formal_attempts"]) is int
        and approval["initial_formal_attempts"] == 1
        and type(approval["additional_probes"]) is int
        and approval["additional_probes"] == 0
    )
    assert origins.task_plan is not None
    _require(task._current(origins.task_plan, when))
    reference = approval["authorization_reference"]
    formal._safe_reference(reference, "Gemini restoration authorization")
    _require(bool(reference) and not reference.startswith("REPLACE-"))
    approved = formal._parse_utc(approval["approved_at_utc"], "restoration approval time")
    start = formal._parse_utc(origins.task_plan["authorization"]["approved_at_utc"], "task approval time")
    auth, intent, result, receipt = [_checked(approval[k]) for k in PROBE_REFS]
    _require(
        auth["task_plan"] == approval["task_plan"]
        and auth["requested_model"] == MODEL
        and auth["required_observed_model"] == task._health_contract(origins, MODEL)["route"]["required_observed_model"]
        and type(auth["maximum_new_attempts"]) is int
        and auth["maximum_new_attempts"] == 1
        and type(auth["automatic_retries"]) is int
        and auth["automatic_retries"] == 0
        and auth["new_formal_attempts_authorized"] == 0
        and auth["other_models_authorized"] == []
    )
    _require(
        intent["authorization_sha256"] == approval["probe_authorization"]["sha256"]
        and type(intent["attempt_number"]) is int
        and intent["attempt_number"] == 1
        and type(intent["maximum_attempts"]) is int
        and intent["maximum_attempts"] == 1
    )
    from .providers.robustness import robustness_provider_disclosures

    cell = next(c for c in origins.source.manifest.prompt_model_cells if c.requested_model == MODEL)
    disclosure = next(r for r in robustness_provider_disclosures() if r["requested_model"] == MODEL)
    keys = {
        "provider_route",
        "requested_model",
        "required_observed_model",
        "wire_api",
        "reasoning_effort",
        "thinking_mode",
        "thinking_budget",
        "output_token_ceiling",
        "wire_output_token_ceiling",
        "output_token_ceiling_scope",
        "billing_semantics",
        "billing_currency",
        "fee_ceiling",
    }
    expected_request = {k: disclosure[k] for k in keys}
    contract = origins.source.manifest.request_contract
    expected_request.update(
        schema_version="robustness-provider-request-evidence-v2",
        prompt_version=cell.prompt_version,
        prompt_canonical_hash=cell.prompt_canonical_hash,
        structured_output_schema_version=contract.structured_output_schema_version,
        structured_output_schema_hash=contract.structured_output_schema_hash,
        maximum_physical_attempts_per_logical_pair=3,
    )
    _require(formal._canonical_json_bytes(intent["request_evidence"]) == formal._canonical_json_bytes(expected_request))
    _require(
        result["status"] == "succeeded"
        and result["decision_valid"] is True
        and result["automatic_retries"] == 0
        and result["new_formal_attempts"] == 0
        and result["campaign_not_resumed"] is True
        and receipt["campaign_head_unchanged"] is True
        and receipt["head_before"] == receipt["head_after"] == head
        and receipt["campaign_writes_by_probe"] == 0
        and receipt["new_formal_attempts"] == 0
    )
    attempt = v2._V2AttemptEvidence.model_validate(result["attempt"])
    _require(
        attempt.outcome == "succeeded"
        and attempt.attempt_number == 1
        and attempt.request_invocations == attempt.provider_response_count == attempt.successful_decision_count == 1
        and attempt.usage_complete_response_count == 1
        and attempt.usage_missing_response_count == attempt.usage_malformed_response_count == 0
        and attempt.provider_route == disclosure["provider_route"]
        and attempt.observed_model_counts == {auth["required_observed_model"]: 1}
        and attempt.observed_model_missing_response_count == attempt.observed_model_malformed_response_count == 0
    )
    times = [
        formal._parse_utc(s, "probe time")
        for s in (auth["approved_at_utc"], intent["at_utc"], result["settled_at_utc"])
    ]
    _require(start <= times[0] <= times[1] <= times[2] <= approved <= when)
    transition(state, payload)


def receipt_references(payload: dict[str, Any]) -> list[dict[str, Any]]:
    approval = _checked(payload["approval"])
    return [payload["approval"], *(approval[k] for k in PROBE_REFS)]


def replays_prior_barrier(state: CampaignProgress, index: int, step: int, commit: dict[str, Any]) -> bool:
    """A new Gemini epoch may re-record only an identical already closed barrier."""
    if state.gemini_restoration_approval is None or state.current_model != MODEL:
        return False
    prior = [
        row
        for (epoch, cell, batch), row in state.batch_commits.items()
        if epoch < len(state.epochs) and cell == index and batch == step
    ]
    return bool(prior) and all(
        formal._canonical_json_bytes(row) == formal._canonical_json_bytes(commit) for row in prior
    )
