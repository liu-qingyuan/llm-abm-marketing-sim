"""Versioned recovery evidence contracts: no Provider, source run or secrets."""
from __future__ import annotations

import copy
from typing import Any

import pytest

from llm_abm_sim import concurrent_robustness_v2 as v2
from llm_abm_sim._concurrent_recovery_judgment import RecoveryJudgmentV1
from llm_abm_sim.decision import EngageDecision


def _cell() -> dict[str, Any]:
    prompt = v2.CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.all()[0]
    model = v2._V2_MODELS[0]
    return {"cell_id": f"{prompt.variant_id}::{model}", "prompt_variant": prompt.variant_id,
            "prompt_version": prompt.prompt_version, "prompt_canonical_hash": prompt.canonical_hash,
            "requested_model": model, "required_observed_model": v2._V2_REQUIRED_OBSERVED_MODELS[model]}


def _attempt(number: int, *, outcome: str = "succeeded", missing: bool = False, no_response: bool = False) -> dict[str, Any]:
    success = outcome == "succeeded"
    retry = outcome == "retryable_failure"
    responses = int(not no_response)
    complete = int(not missing and not no_response)
    return {
        "schema_version": "concurrent-robustness-provider-attempt-v2", "attempt_number": number,
        "outcome": outcome, "failure_category": None if success else "timeout" if retry else "usage_evidence",
        "status_code": None, "wait_source": "exponential_backoff" if retry else None,
        "wait_seconds": 40.0 if retry else None, "lane_cooldown": False,
        "request_invocations": 1, "provider_response_count": responses, "successful_decision_count": int(success),
        "observed_model_counts": {"deepseek-v4-flash": 1} if responses else {},
        "observed_model_missing_response_count": 0, "observed_model_malformed_response_count": 0,
        "usage_complete_response_count": complete, "usage_missing_response_count": int(missing and not no_response),
        "usage_malformed_response_count": 0, "input_usage": 10 if complete else None,
        "output_usage": 5 if complete else None, "total_usage": 15 if complete else None,
        "cached_input_usage": 0 if complete else None, "provider_route": "deepseek_official",
        "billing_semantics": "provider_fee_cny", "billing_currency": "CNY",
        "provider_fee_cny": None, "subscription_nominal_cost_usd": None, "fee_ceiling": None,
    }


def _payload(*, historical: bool = True) -> dict[str, Any]:
    body = {
        "schema_version": "concurrent-recovery-provider-judgment-v1", "epoch_identity_sha256": "e" * 64,
        "judgment_source_identity": "b" * 64, "cell_index": 0, "cell": _cell(),
        "pair": {"pair_id": "pair-0", "pair_schedule_position": 0, "time_step": 0, "message_id": "m0", "user_id": "u0"},
        "decision": EngageDecision(engage=True, probability=0.5, action="like", reason="fixture", confidence=0.8,
                                   decision_source="provider_llm").model_dump(mode="json"),
        "historical_attempts": [_attempt(1, outcome="nonretryable_failure", missing=True)] if historical else [],
        "new_attempts": [_attempt(2 if historical else 1)],
    }
    return {**body, "judgment_id": v2._json_sha256(body)}


def _rehash(payload: dict[str, Any]) -> None:
    payload["judgment_id"] = v2._json_sha256({k: value for k, value in payload.items() if k != "judgment_id"})


def test_recovery_preserves_missing_history_and_proves_only_new_success_usage() -> None:
    payload = _payload()
    before = copy.deepcopy(payload)
    judgment = RecoveryJudgmentV1.model_validate(payload)
    assert payload == before
    assert judgment.historical_attempts[0].attempt_number == 1
    assert judgment.new_attempts[0].attempt_number == 2
    assert judgment.historical_usage_accounting["total_usage"] is None
    assert judgment.successful_sequence_accounting.total_usage == 15
    projection = judgment.realized_projection(realization_source_identity="c" * 64)
    assert projection.judgment_id == judgment.judgment_id
    assert projection.request_invocations == 2
    assert projection == v2._V2RealizedTerminal.model_validate(projection.model_dump(mode="json"))
    with pytest.raises(ValueError):
        v2._V2Judgment.model_validate(judgment.model_dump(mode="json"))


@pytest.mark.parametrize("fault", ["ordinal", "missing", "model", "decision", "route"])
def test_recovery_judgment_rejects_corrupt_success_sequence(fault: str) -> None:
    payload = _payload()
    if fault == "ordinal":
        payload["new_attempts"][0]["attempt_number"] = 1
    elif fault == "missing":
        payload["new_attempts"][0] = _attempt(2, missing=True)
    elif fault == "model":
        payload["new_attempts"][0]["observed_model_counts"] = {"wrong-model": 1}
    elif fault == "route":
        payload["new_attempts"][0]["provider_route"] = "antigravity_openai_compatible_gateway"
        payload["new_attempts"][0]["billing_semantics"] = "gateway_quota"
        payload["new_attempts"][0]["billing_currency"] = None
    else:
        payload["decision"]["probability"] = 0.1
    if fault != "decision":
        _rehash(payload)
    with pytest.raises(ValueError):
        RecoveryJudgmentV1.model_validate(payload)


def test_recovery_new_pair_keeps_no_response_retry_and_global_ordinals() -> None:
    payload = _payload(historical=False)
    payload["new_attempts"] = [_attempt(1, outcome="retryable_failure", no_response=True), _attempt(2)]
    _rehash(payload)
    judgment = RecoveryJudgmentV1.model_validate(payload)
    assert judgment.successful_sequence_accounting.request_invocations == 2
    assert judgment.successful_sequence_accounting.total_usage == 15
