from __future__ import annotations

import json

import httpx
import pytest

from llm_abm_sim.prompt_contracts import CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY
from llm_abm_sim.providers.antigravity import AntigravityGeminiProviderClient
from llm_abm_sim.providers.openai_compatible import (
    ProviderConfigurationError,
    _OpenAISDKClient,
    _safe_chat_usage_diagnostics,
)
from llm_abm_sim.providers.robustness import AntigravityGeminiDecisionAdapter

_DECISION = (
    '{"engage":true,"probability":0.72,"reason":"fit",'
    '"confidence":0.81,"action":"like"}'
)


@pytest.mark.parametrize(("requested_model", "wire_model"), [
    ("gemini-3.1-pro", "gemini-pro-agent"),
    ("gemini-3.8-flash-high", "gemini-3.8-flash-high"),
])
def test_antigravity_gemini_client_uses_chat_completions_contract(
    monkeypatch: pytest.MonkeyPatch, requested_model: str, wire_model: str,
) -> None:
    monkeypatch.setenv("LLM_ABM_RUN_LIVE_LLM", "1")
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl_test",
                "object": "chat.completion",
                "created": 0,
                "model": wire_model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": _DECISION},
                        "finish_reason": "stop",
                        "logprobs": None,
                    }
                ],
                "usage": {
                    "prompt_tokens": 20,
                    "completion_tokens": 10,
                    "total_tokens": 30,
                    "prompt_tokens_details": {"cached_tokens": 0},
                },
            },
            request=request,
        )

    client = AntigravityGeminiProviderClient(
        api_key="test-only-api-key",
        base_url="https://gateway.example.test/v1",
        timeout=1.0,
        http_client=httpx.Client(transport=httpx.MockTransport(handle)),
    )

    envelope = client.create_response(
        [{"role": "user", "content": "test"}],
        requested_model,
        reasoning_effort=None,
        output_token_ceiling=256,
    )
    client.close()

    assert client.external_provider_client is True
    assert client.wire_api == "chat_completions"
    assert client.safe_metadata == {
        "provider": "antigravity_openai_compatible_gateway",
        "wire_api": "chat_completions",
        "thinking_budget": 128,
        "reasoning_usage_mapping": "reasoning_included_in_completion_tokens",
        "decision_output_token_ceiling": 256,
        "wire_output_token_ceiling": 1024,
    }
    assert len(requests) == 1
    assert requests[0].url.path == "/v1/chat/completions"
    body = json.loads(requests[0].content)
    assert body["model"] == wire_model
    assert body["messages"] == [{"role": "user", "content": "test"}]
    assert body["max_tokens"] == 1024
    assert "max_completion_tokens" not in body
    assert body["thinking"] == {"type": "enabled", "budget_tokens": 128}
    assert "reasoning" not in body
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["response_format"]["json_schema"]["schema"]["additionalProperties"] is False
    assert envelope.decision_text == _DECISION
    assert envelope.observed_model == wire_model
    assert envelope.observed_model_status == "reported"
    assert envelope.usage_status == "complete"
    assert envelope.input_tokens == 20
    assert envelope.output_tokens == 10
    assert envelope.total_tokens == 30
    assert envelope.cached_input_tokens == 0
    assert client.last_safe_usage_diagnostics == {
        "schema_version": "chat-usage-diagnostics-v1",
        "normalized_usage_status": "complete",
        "usage_status": "complete",
        "input_tokens": 20,
        "output_tokens": 10,
        "total_tokens": 30,
        "cached_input_tokens": 0,
        "reasoning_tokens": None,
        "failure_invariant": None,
        "total_delta": 0,
        "reasoning_reconciliation": "not_applied",
        "normalized_output_tokens": 10,
    }


def test_antigravity_gemini_client_reconciles_additive_reasoning_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_ABM_RUN_LIVE_LLM", "1")

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl_test",
                "object": "chat.completion",
                "created": 0,
                "model": "gemini-3.8-flash-high",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": _DECISION},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 487,
                    "completion_tokens": 50,
                    "total_tokens": 665,
                    "prompt_tokens_details": {"cached_tokens": 0},
                    "completion_tokens_details": {"reasoning_tokens": 128},
                },
            },
            request=request,
        )

    with AntigravityGeminiProviderClient(
        api_key="test-only-api-key",
        base_url="https://gateway.example.test/v1",
        timeout=1.0,
        http_client=httpx.Client(transport=httpx.MockTransport(handle)),
    ) as client:
        envelope = client.create_response(
            [{"role": "user", "content": "test"}],
            "gemini-3.8-flash-high",
            output_token_ceiling=256,
        )

        assert envelope.usage_status == "complete"
        assert envelope.input_tokens == 487
        assert envelope.output_tokens == 178
        assert envelope.total_tokens == 665
        assert envelope.cached_input_tokens == 0
        assert client.last_safe_usage_diagnostics == {
            "usage_status": "malformed",
            "input_tokens": 487,
            "output_tokens": 50,
            "total_tokens": 665,
            "schema_version": "chat-usage-diagnostics-v1",
            "normalized_usage_status": "complete",
            "cached_input_tokens": 0,
            "reasoning_tokens": 128,
            "failure_invariant": "total_mismatch",
            "total_delta": 128,
            "reasoning_reconciliation": "added_to_completion_tokens",
            "normalized_output_tokens": 178,
        }


def test_antigravity_gemini_client_does_not_guess_at_unexplained_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_ABM_RUN_LIVE_LLM", "1")

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl_test",
                "object": "chat.completion",
                "created": 0,
                "model": "gemini-3.8-flash-high",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": _DECISION},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 487,
                    "completion_tokens": 50,
                    "total_tokens": 664,
                    "completion_tokens_details": {"reasoning_tokens": 128},
                },
            },
            request=request,
        )

    with AntigravityGeminiProviderClient(
        api_key="test-only-api-key",
        base_url="https://gateway.example.test/v1",
        timeout=1.0,
        http_client=httpx.Client(transport=httpx.MockTransport(handle)),
    ) as client:
        envelope = client.create_response(
            [{"role": "user", "content": "test"}],
            "gemini-3.8-flash-high",
            output_token_ceiling=256,
        )

        assert envelope.usage_status == "malformed"
        assert envelope.input_tokens is None
        assert envelope.output_tokens is None
        assert envelope.total_tokens is None
        assert client.last_safe_usage_diagnostics == {
            "usage_status": "malformed",
            "input_tokens": 487,
            "output_tokens": 50,
            "total_tokens": 664,
            "schema_version": "chat-usage-diagnostics-v1",
            "normalized_usage_status": "malformed",
            "cached_input_tokens": None,
            "reasoning_tokens": 128,
            "failure_invariant": "total_mismatch",
            "total_delta": 127,
            "reasoning_reconciliation": "not_applied",
            "normalized_output_tokens": None,
        }


def test_safe_chat_usage_diagnostics_retains_only_counters_and_invariant() -> None:
    assert _safe_chat_usage_diagnostics(
        {
            "prompt_tokens": 20,
            "completion_tokens": 11,
            "total_tokens": 27,
            "prompt_tokens_details": {"cached_tokens": 0},
            "completion_tokens_details": {"reasoning_tokens": 7},
            "ignored_raw_field": "must-not-survive",
        }
    ) == {
        "usage_status": "malformed",
        "input_tokens": 20,
        "output_tokens": 11,
        "total_tokens": 27,
        "cached_input_tokens": 0,
        "reasoning_tokens": 7,
        "failure_invariant": "total_mismatch",
        "total_delta": -4,
    }


@pytest.mark.parametrize(
    ("model", "reasoning_effort", "output_token_ceiling"),
    [
        ("not-a-frozen-gemini", None, 256),
        ("gemini-3.1-pro", "low", 256),
        ("gemini-3.8-flash-high", None, None),
    ],
)
def test_antigravity_gemini_client_rejects_invalid_contract_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    model: str,
    reasoning_effort: str | None,
    output_token_ceiling: int | None,
) -> None:
    monkeypatch.setenv("LLM_ABM_RUN_LIVE_LLM", "1")
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError(f"unexpected request to {request.url.path}")

    client = AntigravityGeminiProviderClient(
        api_key="test-only-api-key",
        base_url="https://gateway.example.test/v1",
        timeout=1.0,
        http_client=httpx.Client(transport=httpx.MockTransport(handle)),
    )

    with pytest.raises(ProviderConfigurationError):
        client.create_response(
            [{"role": "user", "content": "test"}],
            model,
            reasoning_effort=reasoning_effort,  # type: ignore[arg-type]
            output_token_ceiling=output_token_ceiling,
        )
    client.close()

    assert calls == 0


def test_antigravity_gemini_client_requires_the_explicit_live_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LLM_ABM_RUN_LIVE_LLM", raising=False)

    with httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(200))) as http_client:
        with pytest.raises(ProviderConfigurationError, match="explicit"):
            AntigravityGeminiProviderClient(
                api_key="test-only-api-key",
                http_client=http_client,
            )


def test_antigravity_adapter_rejects_a_direct_generic_responses_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_ABM_RUN_LIVE_LLM", "1")
    with httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(200))) as http_client:
        client = _OpenAISDKClient(
            api_key="test-only-api-key",
            base_url="https://gateway.example.test/v1",
            timeout=1.0,
            wire_api="responses",
            http_client=http_client,
        )
        try:
            with pytest.raises(ValueError, match="Chat Completions"):
                AntigravityGeminiDecisionAdapter(
                    requested_model="gemini-3.1-pro",
                    prompt_version=CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.resolve(
                        "P0"
                    ).prompt_version,
                    client=client,
                )
        finally:
            client.close()
