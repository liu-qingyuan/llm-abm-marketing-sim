"""Kimi migration invariants over the original, fully replayed Study state.

This Module never opens credentials, dispatches requests, mutates state, or admits
an approval. Its exact terms are the input to the pending hash-bound admission.
"""
from __future__ import annotations

from typing import Any

from . import concurrent_robustness_v2 as v2
from ._concurrent_recovery_campaign import RecoveryCampaignError
from ._concurrent_recovery_progress import CampaignProgress

MODEL = "kimi-coding/k3-256k"
OFFICIAL_MODEL = "kimi-k3"


def _require(condition: bool) -> None:
    if not condition:
        raise RecoveryCampaignError("Kimi migration requires the drained original lane after Gemini completion")


def terms(state: CampaignProgress) -> dict[str, Any]:
    """Return exact preserved attempts and remaining budget, without changing them.

    Only a completed restored Gemini stage and its original suspended Kimi first
    batch qualify. No later Kimi stop, unknown attempt, or exhausted budget can be
    transformed into fresh capacity by preparing these terms.
    """
    suspended = state.suspended_models.get(MODEL)
    _require(
        state.status == "model_complete" and state.model_stage_complete
        and state.current_model == "gemini-3.1-pro"
        and state.gemini_restoration_approval is not None
        and state.task_plan is not None and not state.task_revoked
        and not state.has_inflight and not state.parallel_unknown
        and state.self_check_inflight is None and state.reservation is None
        and state.pending_judgment is None and state.pending_realized is None
        and state.quota_retry_pending is None and state.parallel_active_batch is None
        and suspended is not None
    )
    assert suspended is not None
    indexes = [i for i, cell in enumerate(state.cells) if cell.requested_model == MODEL]
    gemini = [i for i, cell in enumerate(state.cells) if cell.requested_model == "gemini-3.1-pro"]
    _require(
        len(indexes) == 4 and len(gemini) == 4
        and all(state.prefix[i] == state.per_cell for i in gemini)
        and all(state.prefix[i] == 0 for i in indexes)
        and suspended["status"] == "stopped"
        and suspended["model_lane_approval"] == state.model_lane_approval
        and suspended["output_amendment"] == state.output_amendment
        and suspended["parallel_active_batch"] == (indexes[0], 0)
        and (indexes[0], 0) in state.parallel_batches
    )
    check = state.effective_self_check(MODEL)
    _require(check is not None and check["attempt"]["outcome"] == "succeeded")
    preserved_successes = []
    failed_attempts = []
    for key, attempts in sorted(state.new_attempts.items()):
        if key[0] not in indexes:
            continue
        _require(
            len(attempts) == 1 and attempts[0].attempt_number == 1
            and key[0] == indexes[0] and 0 <= key[1] < state.per_cell // 30
            and key not in state.old_successes and key not in state.judgments
        )
        row = attempts[0]
        fact = {"cell_index": key[0], "pair_schedule_position": key[1],
                "attempt_sha256": v2._json_sha256(row.model_dump(mode="json"))}
        _require(row.provider_route == "pi_kimi_oauth_subscription")
        if row.outcome == "succeeded":
            _require(key in state.success_decisions and row.observed_model_counts == {"k3-256k": 1}
                     and row.provider_response_count == 1 and row.successful_decision_count == 1
                     and row.usage_complete_response_count == 1
                     and row.output_usage is not None and row.output_usage <= 1024)
            fact["decision_sha256"] = v2._json_sha256(state.success_decisions[key].model_dump(mode="json"))
            preserved_successes.append(fact)
        else:
            _require(key not in state.success_decisions and row.outcome == "nonretryable_failure"
                     and row.failure_category == "entitlement" and row.status_code == 403)
            failed_attempts.append(fact)
    _require(bool(failed_attempts))
    _require(len(preserved_successes) == sum(1 for k in state.success_decisions if k[0] in indexes))
    budget = next(row for row in state.proposal["model_budgets"] if row["requested_model"] == MODEL)
    global_remaining = state.proposal["maximum_new_physical_attempts"] - state.physical_attempts
    model_remaining = budget["maximum_new_physical_attempts"] - state.physical_by_model[MODEL]
    remaining = len(indexes) * state.per_cell - len(preserved_successes)
    _require(global_remaining >= remaining and model_remaining >= remaining)
    return {"preserved_successes": preserved_successes, "failed_attempts": failed_attempts,
            "frozen_batch": [indexes[0], 0], "remaining_logical_judgments": remaining,
            "remaining_global_physical_budget": global_remaining,
            "remaining_model_physical_budget": model_remaining}
