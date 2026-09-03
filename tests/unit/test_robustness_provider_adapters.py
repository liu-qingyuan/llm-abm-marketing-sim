from __future__ import annotations

from typing import Any

import pytest

from llm_abm_sim import concurrent_robustness_v2 as v2_module
from llm_abm_sim.decision import ProviderDecisionError, ProviderResponseProvenanceUnknown
from llm_abm_sim.prompt_contracts import CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY
from llm_abm_sim.provider_accounting import ProviderResponseEnvelope
from llm_abm_sim.providers.robustness import (
    AntigravityGeminiDecisionAdapter,
    DeepSeekV4FlashDecisionAdapter,
    PiKimiDecisionAdapter,
    PiOpenAIDecisionAdapter,
)
from llm_abm_sim.schemas import PeerContext, PlatformContext, PostContent, UserProfile


class _HTTPFailure(RuntimeError):
    def __init__(self, status_code: int, *, retry_after: str | None = None, message: str = "failed") -> None:
        self.status_code = status_code
        self.headers = {} if retry_after is None else {"Retry-After": retry_after}
        super().__init__(message)


class APITimeoutError(RuntimeError):
    pass


class APIConnectionError(RuntimeError):
    pass


class AuthenticationError(RuntimeError):
    pass


class PermissionDeniedError(RuntimeError):
    pass


class _FailingTransport:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.api_key: str | None = None
        self.raw_payload: dict[str, object] | None = None

    def create_response(self, *_args: object, **_kwargs: object) -> ProviderResponseEnvelope:
        raise self.error


class _FakeTransport:
    def __init__(self, observed_model: str) -> None:
        self.observed_model = observed_model
        self.calls: list[tuple[list[dict[str, str]], str, dict[str, object]]] = []

    def create_response(
        self,
        messages: list[dict[str, str]],
        model: str,
        **settings: object,
    ) -> ProviderResponseEnvelope:
        self.calls.append((messages, model, settings))
        return ProviderResponseEnvelope(
            decision_text=(
                '{"engage":true,"probability":0.72,"reason":"fit",'
                '"confidence":0.81,"action":"like"}'
            ),
            observed_model=self.observed_model,
            observed_model_status="reported",
            usage_status="complete",
            input_tokens=20,
            output_tokens=10,
            total_tokens=30,
            cached_input_tokens=0,
        )


def _context() -> dict[str, Any]:
    return {
        "post": PostContent(post_id="message_1", text="绿色酒店营销内容"),
        "profile": UserProfile.model_validate(
            {
                "user_id": "u1",
                "activity_score": 0.5,
                "global_influence_score": 0.9,
                "local_influence_score": 0.4,
                "concurrent_environmental_consciousness_coef": 1.0,
                "concurrent_epistemic_value_weight": 0.1,
                "concurrent_environmental_value_weight": 0.8,
                "concurrent_functional_value_weight": 0.4,
                "concurrent_health_value_weight": 0.7,
                "concurrent_emotional_value_weight": 0.2,
                "concurrent_social_value_weight": 0.3,
                "concurrent_hotel_class": "midscale",
                "concurrent_travel_purpose": "leisure",
            }
        ),
        "peer_context": PeerContext(),
        "platform_context": PlatformContext(),
        "time_step": 0,
    }


@pytest.mark.parametrize("prompt_variant", ["P0", "P1", "P2", "P3"])
def test_five_provider_conditions_share_canonical_prompt_bytes_and_keep_request_settings_outside_prompt(
    prompt_variant: str,
) -> None:
    prompt = CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.resolve(prompt_variant)
    transports = {
        "deepseek-v4-flash": _FakeTransport("deepseek-v4-flash"),
        "gemini-3.1-pro": _FakeTransport("gemini-pro-agent"),
        "gemini-3.8-flash-high": _FakeTransport("gemini-3.8-flash-high"),
        "kimi-coding/k3-256k": _FakeTransport("k3-256k"),
        "openai-codex/gpt-5.6-sol": _FakeTransport("gpt-5.6-sol"),
    }
    adapters = [
        DeepSeekV4FlashDecisionAdapter(prompt_version=prompt.prompt_version, client=transports["deepseek-v4-flash"]),
        AntigravityGeminiDecisionAdapter(
            requested_model="gemini-3.1-pro",
            prompt_version=prompt.prompt_version,
            client=transports["gemini-3.1-pro"],
        ),
        AntigravityGeminiDecisionAdapter(
            requested_model="gemini-3.8-flash-high",
            prompt_version=prompt.prompt_version,
            client=transports["gemini-3.8-flash-high"],
        ),
        PiKimiDecisionAdapter(prompt_version=prompt.prompt_version, client=transports["kimi-coding/k3-256k"]),
        PiOpenAIDecisionAdapter(prompt_version=prompt.prompt_version, client=transports["openai-codex/gpt-5.6-sol"]),
    ]

    decisions = [adapter.decide(**_context()) for adapter in adapters]

    assert {decision.action for decision in decisions} == {"like"}
    submitted_messages = [transport.calls[0][0] for transport in transports.values()]
    assert all(messages == submitted_messages[0] for messages in submitted_messages)
    assert all(adapter.request_evidence["prompt_version"] == prompt.prompt_version for adapter in adapters)
    assert all(adapter.request_evidence["prompt_canonical_hash"] == prompt.canonical_hash for adapter in adapters)
    assert adapters[0].request_evidence | {} == {
        "schema_version": "robustness-provider-request-evidence-v2",
        "provider_route": "deepseek_official",
        "requested_model": "deepseek-v4-flash",
        "required_observed_model": "deepseek-v4-flash",
        "wire_api": "chat_completions",
        "reasoning_effort": None,
        "thinking_mode": "disabled",
        "output_token_ceiling": 256,
        "structured_output_schema_version": "engage-decision-output-v1",
        "structured_output_schema_hash": "sha256:baa4b5ac3950d8834bd296b184b8544c707633d5e668e1ee23cb8570e0e46654",
        "maximum_physical_attempts_per_logical_pair": 3,
        "prompt_version": prompt.prompt_version,
        "prompt_canonical_hash": prompt.canonical_hash,
        "billing_semantics": "provider_fee_cny",
        "billing_currency": "CNY",
        "fee_ceiling": 25.0,
    }
    assert adapters[1].request_evidence["provider_route"] == "antigravity_openai_compatible_gateway"
    assert adapters[1].request_evidence["required_observed_model"] == "gemini-pro-agent"
    assert adapters[2].request_evidence["required_observed_model"] == "gemini-3.8-flash-high"
    assert adapters[3].request_evidence["provider_route"] == "pi_kimi_oauth_subscription"
    assert adapters[3].request_evidence["reasoning_effort"] == "low"
    assert adapters[4].request_evidence["provider_route"] == "pi_openai_oauth_subscription"
    assert transports["deepseek-v4-flash"].calls[0][2] == {
        "reasoning_effort": None,
        "output_token_ceiling": 256,
        "thinking_mode": "disabled",
    }
    for requested_model in (
        "gemini-3.1-pro",
        "gemini-3.8-flash-high",
        "kimi-coding/k3-256k",
        "openai-codex/gpt-5.6-sol",
    ):
        assert transports[requested_model].calls[0][2] == {
            "reasoning_effort": "low",
            "output_token_ceiling": 256,
        }
    assert all(adapter.request_invocations == 1 for adapter in adapters)
    assert all(adapter.external_request_invocations == 0 for adapter in adapters)


@pytest.mark.parametrize(
    (
        "error",
        "category",
        "retryable",
        "status_code",
        "lane_cooldown",
        "wait_seconds",
        "wait_source",
    ),
    [
        (ConnectionError("connect failed"), "connection", True, None, False, None, None),
        (APIConnectionError("connect failed"), "connection", True, None, False, None, None),
        (TimeoutError("timeout"), "timeout", True, None, False, None, None),
        (APITimeoutError("timeout"), "timeout", True, None, False, None, None),
        (_HTTPFailure(408), "http_status", True, 408, False, None, None),
        (_HTTPFailure(409), "http_status", True, 409, False, None, None),
        (_HTTPFailure(429, retry_after="7"), "http_status", True, 429, True, 7.0, "retry_after"),
        (
            _HTTPFailure(503, message="busy; Wait 11s before retry"),
            "http_status",
            True,
            503,
            True,
            11.0,
            "provider_wait",
        ),
        (RuntimeError("HTTP status 429; Wait 4s"), "http_status", True, 429, True, 4.0, "provider_wait"),
        (_HTTPFailure(500), "http_status", True, 500, False, None, None),
        (_HTTPFailure(400), "http_status", False, 400, False, None, None),
        (_HTTPFailure(401), "authentication", False, 401, False, None, None),
        (_HTTPFailure(403), "permission", False, 403, False, None, None),
        (AuthenticationError("denied"), "authentication", False, None, False, None, None),
        (PermissionDeniedError("denied"), "permission", False, None, False, None, None),
    ],
)
def test_adapter_normalizes_only_the_frozen_retry_allowlist(
    error: Exception,
    category: str,
    retryable: bool,
    status_code: int | None,
    lane_cooldown: bool,
    wait_seconds: float | None,
    wait_source: str | None,
) -> None:
    adapter = DeepSeekV4FlashDecisionAdapter(
        prompt_version=CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.resolve("P0").prompt_version,
        client=_FailingTransport(error),
    )

    with pytest.raises(ProviderDecisionError) as captured:
        adapter.decide(**_context())

    assert captured.value.failure_category == category
    assert captured.value.retryable is retryable
    assert captured.value.status_code == status_code
    assert captured.value.lane_cooldown is lane_cooldown
    assert captured.value.wait_seconds == wait_seconds
    assert captured.value.wait_source == wait_source


def test_model_lane_exponential_backoff_is_bounded_and_never_exceeds_three_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = DeepSeekV4FlashDecisionAdapter(
        prompt_version=CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.resolve("P0").prompt_version,
        client=_FailingTransport(_HTTPFailure(500)),
    )
    lane = v2_module._V2ModelLane(requested_model="deepseek-v4-flash", backoff_seconds=40.0)
    waits: list[float] = []
    monkeypatch.setattr(v2_module, "_V2_SLEEP", waits.append)
    wrapped = v2_module._V2LaneDecisionAdapter(adapter, lane)

    with pytest.raises(ProviderDecisionError) as captured:
        wrapped.decide(**_context())

    assert adapter.request_invocations == 3
    assert waits == [40.0, 60.0]
    assert captured.value.retryable is True
    assert [row.outcome for row in wrapped.last_attempt_evidence] == [
        "retryable_failure",
        "retryable_failure",
        "attempts_exhausted",
    ]


def test_model_lane_cooldown_is_shared_by_another_prompt_for_the_same_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt = CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.resolve("P1")
    transport = _FakeTransport("deepseek-v4-flash")
    adapter = DeepSeekV4FlashDecisionAdapter(prompt_version=prompt.prompt_version, client=transport)
    lane = v2_module._V2ModelLane(requested_model="deepseek-v4-flash", backoff_seconds=0.5)
    lane.cooldown_until = 9.0
    now = [4.0]
    waits: list[float] = []

    def sleep(delay: float) -> None:
        waits.append(delay)
        now[0] += delay

    monkeypatch.setattr(v2_module, "_V2_MONOTONIC", lambda: now[0])
    monkeypatch.setattr(v2_module, "_V2_SLEEP", sleep)
    wrapped = v2_module._V2LaneDecisionAdapter(adapter, lane)

    decision = wrapped.decide(**_context())

    assert decision.action == "like"
    assert waits == [5.0]
    assert len(transport.calls) == 1
    assert wrapped.last_attempt_evidence[0].attempt_number == 1


def test_adapter_retries_only_malformed_decision_text_not_identity_or_usage_evidence() -> None:
    prompt_version = CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.resolve("P0").prompt_version
    malformed = _FakeTransport("deepseek-v4-flash")
    malformed.create_response = lambda *_args, **_kwargs: ProviderResponseEnvelope(  # type: ignore[method-assign]
        decision_text="not-json",
        observed_model="deepseek-v4-flash",
        observed_model_status="reported",
        usage_status="complete",
        input_tokens=1,
        output_tokens=1,
        total_tokens=2,
        cached_input_tokens=0,
    )
    drifted = _FakeTransport("different-model")
    missing_usage = _FakeTransport("deepseek-v4-flash")
    missing_usage.create_response = lambda *_args, **_kwargs: ProviderResponseEnvelope(  # type: ignore[method-assign]
        decision_text=(
            '{"engage":false,"probability":0.1,"reason":"low",'
            '"confidence":0.8,"action":"ignore"}'
        ),
        observed_model="deepseek-v4-flash",
        observed_model_status="reported",
        usage_status="missing",
    )

    expected = [
        (malformed, "malformed_structured_response", True),
        (drifted, "model_identity", False),
        (missing_usage, "usage_evidence", False),
    ]
    for transport, category, retryable in expected:
        adapter = DeepSeekV4FlashDecisionAdapter(prompt_version=prompt_version, client=transport)
        with pytest.raises(ProviderDecisionError) as captured:
            adapter.decide(**_context())
        assert captured.value.failure_category == category
        assert captured.value.retryable is retryable


def test_adapter_never_wraps_unknown_post_dispatch_provenance_as_retryable() -> None:
    adapter = DeepSeekV4FlashDecisionAdapter(
        prompt_version=CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.resolve("P0").prompt_version,
        client=_FailingTransport(ProviderResponseProvenanceUnknown("unknown")),
    )

    with pytest.raises(ProviderResponseProvenanceUnknown):
        adapter.decide(**_context())


def test_safe_metadata_and_typed_failures_redact_credentials_raw_prompt_and_payload() -> None:
    secret = "sk-never-persist-this-sentinel"
    error = _HTTPFailure(429, message=f"Bearer {secret}; HTTP status 429; Wait 2s; raw payload")
    transport = _FailingTransport(error)
    transport.api_key = secret
    transport.raw_payload = {"authorization": secret}
    adapter = DeepSeekV4FlashDecisionAdapter(
        prompt_version=CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.resolve("P0").prompt_version,
        client=transport,
    )

    with pytest.raises(ProviderDecisionError) as captured:
        adapter.decide(**_context())

    serialized = repr(
        {
            "error": str(captured.value),
            "category": captured.value.failure_category,
            "metadata": adapter.safe_metadata,
            "request_evidence": adapter.request_evidence,
        }
    )
    assert secret not in serialized
    assert "raw payload" not in serialized
    assert "authorization" not in serialized.lower()
    assert captured.value.status_code == 429
    assert captured.value.wait_seconds == 2.0


@pytest.mark.parametrize("model", ["gemini-2.5-pro", "gemini-3.1-pro-latest", ""])
def test_antigravity_adapter_rejects_models_outside_the_two_frozen_conditions(model: str) -> None:
    with pytest.raises(ValueError, match="frozen Gemini"):
        AntigravityGeminiDecisionAdapter(
            requested_model=model,
            prompt_version=CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.resolve("P0").prompt_version,
            client=_FakeTransport("gemini-pro-agent"),
        )
