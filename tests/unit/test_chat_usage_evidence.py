from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from llm_abm_sim import concurrent_robustness_v2 as v2
from llm_abm_sim.decision import ProviderDecisionError
from llm_abm_sim.providers.antigravity import AntigravityGeminiProviderClient
from llm_abm_sim.providers.openai_compatible import ChatUsageDiagnostics
from llm_abm_sim.providers.robustness import AntigravityGeminiDecisionAdapter
from tests.unit.test_robustness_provider_adapters import _context

_DECISION = '{"engage":true,"probability":0.72,"reason":"fit","confidence":0.81,"action":"like"}'


def _client(monkeypatch: pytest.MonkeyPatch, usages: list[object]) -> AntigravityGeminiProviderClient:
    monkeypatch.setenv("LLM_ABM_RUN_LIVE_LLM", "1")

    def handle(request: httpx.Request) -> httpx.Response:
        usage = usages.pop(0)
        if isinstance(usage, Exception):
            raise usage
        return httpx.Response(200, json={
            "id": "offline", "object": "chat.completion", "created": 0,
            "model": "gemini-pro-agent",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": _DECISION}}],
            "usage": usage,
        }, request=request)

    return AntigravityGeminiProviderClient(
        api_key="test-only", base_url="https://gateway.example.test/v1", timeout=1.0,
        http_client=httpx.Client(transport=httpx.MockTransport(handle)),
    )


def test_chat_transport_and_adapter_reset_diagnostics_after_no_response(monkeypatch: pytest.MonkeyPatch) -> None:
    with _client(monkeypatch, [
        {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
        httpx.ReadTimeout("SYNTHETIC_RAW_ERROR_MUST_NOT_SURVIVE"),
    ]) as client:
        adapter = AntigravityGeminiDecisionAdapter(requested_model="gemini-3.1-pro", prompt_version="P0", client=client)
        adapter.decide(**_context())
        assert client.last_safe_usage_diagnostics is not None
        with pytest.raises(ProviderDecisionError):
            adapter.decide(**_context())
        assert client.last_safe_usage_diagnostics is None
        assert adapter.last_usage_diagnostics is None


@pytest.mark.parametrize(("usage", "expected_status", "invariant"), [
    (None, "missing", "usage_absent"),
    ({}, "malformed", "required_counter_invalid"),
    ({"prompt_tokens": False, "completion_tokens": 10, "total_tokens": 10}, "malformed", "required_counter_invalid"),
    ({"prompt_tokens": "20", "completion_tokens": 10, "total_tokens": 30}, "malformed", "required_counter_invalid"),
    ({"prompt_tokens": 20.0, "completion_tokens": 10, "total_tokens": 30}, "malformed", "required_counter_invalid"),
    ({"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 31,
      "completion_tokens_details": {"reasoning_tokens": 1},
      "prompt_tokens_details": {"cached_tokens": "invalid"}}, "malformed", "total_mismatch"),
    ({"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 31}, "malformed", "total_mismatch"),
    ({"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}, "complete", None),
    ({"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 271,
      "completion_tokens_details": {"reasoning_tokens": 241}}, "complete", "total_mismatch"),
])
def test_usage_diagnostics_follow_exact_attempt_without_relaxing_usage(
    monkeypatch: pytest.MonkeyPatch, usage: object, expected_status: str, invariant: str | None,
) -> None:
    if isinstance(usage, dict):
        usage["untrusted_field"] = "SYNTHETIC_RAW_PAYLOAD_MUST_NOT_SURVIVE"
    with _client(monkeypatch, [usage]) as client:
        adapter = AntigravityGeminiDecisionAdapter(requested_model="gemini-3.1-pro", prompt_version="P0", client=client)
        lane = v2._V2ModelLane(requested_model=adapter.model, backoff_seconds=0.0)
        if expected_status == "complete":
            _, evidence = lane.execute(adapter, lambda: adapter.decide(**_context()))
        else:
            with pytest.raises(ProviderDecisionError) as caught:
                lane.execute(adapter, lambda: adapter.decide(**_context()))
            assert caught.value.failure_category == "usage_evidence"
            assert caught.value.retryable is False
            evidence = caught.value.attempt_evidence
        assert len(evidence) == 1
        row: Any = evidence[0]
        diagnostic = row.usage_diagnostics
        assert diagnostic is not None
        assert diagnostic.normalized_usage_status == expected_status
        assert diagnostic.failure_invariant == invariant
        assert diagnostic.normalized_output_tokens == row.output_usage
        assert row.wait_seconds is None and row.lane_cooldown is False
        assert adapter.request_invocations == 1
        serialized = row.model_dump_json()
        assert "SYNTHETIC_RAW" not in serialized
        assert v2._V2AttemptEvidence.model_validate_json(serialized) == row
        # Historical attempt rows omitted this optional field; replay/serialization
        # must not add a null and change immutable judgment identities.
        legacy = json.loads(serialized)
        legacy.pop("usage_diagnostics")
        assert v2._V2AttemptEvidence.model_validate(legacy).model_dump(mode="json") == legacy


@pytest.mark.parametrize("patch", [
    {"raw_response": "SYNTHETIC_RAW_PAYLOAD_MUST_NOT_SURVIVE"},
    {"failure_invariant": "SYNTHETIC_RAW_ERROR_MUST_NOT_SURVIVE"},
    {"input_tokens": True}, {"input_tokens": 1.0}, {"input_tokens": -1},
    {"input_tokens": 2**53}, {"total_delta": -(2**53)},
])
def test_diagnostic_contract_rejects_raw_fields_and_unbounded_values(
    monkeypatch: pytest.MonkeyPatch, patch: dict[str, object],
) -> None:
    with _client(monkeypatch, [None]) as client:
        client.create_response([], "gemini-pro-agent", output_token_ceiling=256)
        diagnostic = client.last_safe_usage_diagnostics
        assert diagnostic is not None
        with pytest.raises(ValidationError):
            ChatUsageDiagnostics.model_validate({**diagnostic, **patch})


def test_bounded_diagnostics_do_not_change_usage_arithmetic(monkeypatch: pytest.MonkeyPatch) -> None:
    with _client(monkeypatch, [{
        "prompt_tokens": 2**60, "completion_tokens": 10, "total_tokens": 2**60 + 11,
        "completion_tokens_details": {"reasoning_tokens": 1},
    }]) as client:
        response = client.create_response([], "gemini-pro-agent", output_token_ceiling=256)
        assert response.usage_status == "complete" and response.output_tokens == 11
        assert response.input_tokens == 2**60
        diagnostic = client.last_safe_usage_diagnostics
        assert diagnostic is not None and diagnostic["input_tokens"] is None
