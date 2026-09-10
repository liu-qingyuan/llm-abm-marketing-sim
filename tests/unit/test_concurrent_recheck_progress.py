"""Narrow stop-class regression; synthetic state only, no live calls."""
from __future__ import annotations

from typing import Any

import pytest

from llm_abm_sim._concurrent_recovery_campaign import RecoveryCampaignError
from llm_abm_sim._concurrent_recovery_progress import CampaignProgress
from llm_abm_sim.decision import EngageDecision
from tests.unit.test_concurrent_recovery_judgment import _attempt
from tests.unit.test_concurrent_recovery_progress import _proposal


def _state() -> tuple[CampaignProgress, dict[str, Any]]:
    state = CampaignProgress(_proposal())
    state.transition("task_admitted", {"task_plan": {"path": "/fixture/plan", "sha256": "a" * 64}})()
    state.transition("self_check_intent", {"requested_model": "deepseek-v4-flash", "contract_sha256": "b" * 64})()
    failed = _attempt(1, outcome="nonretryable_failure", no_response=True)
    failed["failure_category"] = "connection"
    state.transition("self_check_settled", {"requested_model": "deepseek-v4-flash", "attempt": failed, "decision": None})()
    return state, {"approval": {"path": "/fixture/approval", "sha256": "c" * 64},
        "requested_model": "deepseek-v4-flash", "attempt": _attempt(1),
        "decision": EngageDecision(engage=True, probability=0.5, reason="fixture", confidence=0.8,
                                    action="like", decision_source="provider").model_dump(mode="json")}


@pytest.mark.parametrize("field,value", [
    ("task_revoked", True), ("status", "reconciliation_required"),
    ("inflight", ((0, 1), 2)), ("self_check_inflight", "deepseek-v4-flash"),
    ("reservation", {}), ("pending_judgment", {}), ("pending_realized", {}),
    ("epochs", [{}]), ("invocations", [{}]), ("physical_attempts", 1),
    ("accepted_rechecks", {"deepseek-v4-flash": {}}),
])
def test_recheck_rejects_noninitial_or_unknown_state(field: str, value: Any) -> None:
    state, payload = _state()
    setattr(state, field, value)
    with pytest.raises(RecoveryCampaignError):
        state.transition("self_check_recheck_accepted", payload)


@pytest.mark.parametrize("category", ["usage_evidence", "quota_exhausted", "identity_evidence", "invalid_decision", "timeout", "provider_error"])
def test_recheck_rejects_other_self_check_failure_classes(category: str) -> None:
    state, payload = _state()
    state.self_checks["deepseek-v4-flash"]["attempt"]["failure_category"] = category
    with pytest.raises((RecoveryCampaignError, ValueError)):
        state.transition("self_check_recheck_accepted", payload)


def test_recheck_retains_failure_and_cumulative_slots_and_is_once_only() -> None:
    state, payload = _state()
    old = dict(state.self_checks)
    original_slots = state.attempts(state.failed_key)
    state.transition("self_check_recheck_accepted", payload)()
    assert state.status == "ready" and state.self_checks == old
    assert state.effective_self_check("deepseek-v4-flash") == payload
    assert state.attempts(state.failed_key) == original_slots
    assert state.physical_attempts == 0
    with pytest.raises(RecoveryCampaignError):
        state.transition("self_check_recheck_accepted", payload)
    with pytest.raises(RecoveryCampaignError):
        state.transition("self_check_intent", {"requested_model": "deepseek-v4-flash", "contract_sha256": "b" * 64})
