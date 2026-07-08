from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from llm_abm_sim.decision import DecisionInput
from llm_abm_sim.prompting import build_engagement_prompt
from llm_abm_sim.provider_config import redact_secrets
from llm_abm_sim.providers.openai_compatible import OpenAICompatibleDecisionAdapter, ProviderRunSkipped
from llm_abm_sim.schemas import (
    FailClosedAction,
    PeerContext,
    PlatformContext,
    PostContent,
    ProviderLLMConfig,
    UserProfile,
)


class FakeProviderClient:
    def __init__(self, response, exc: Exception | None = None):
        self.response = response
        self.exc = exc
        self.calls: list[tuple[list[dict[str, str]], str]] = []

    def create_response(self, messages: list[dict[str, str]], model: str):
        self.calls.append((messages, model))
        if self.exc is not None:
            raise self.exc
        return self.response


def sample_context():
    return {
        "post": PostContent(post_id="p1", text="Eco skincare launch", topic_tags=["eco", "skincare"]),
        "profile": UserProfile(user_id="u1", interest_tags=["skincare"]),
        "peer_context": PeerContext(engaged_neighbors=2, exposed_neighbors=4, visible_likes=3),
        "platform_context": PlatformContext(hot_topics=["eco"], platform_mood="launch week"),
    }


def test_prompt_includes_post_preference_peer_influence_and_schema():
    context = sample_context()
    context["profile"] = UserProfile(
        user_id="u1",
        interest_tags=["skincare"],
        brand_attitude=1.0,
        like_tendency=1.0,
        comment_tendency=1.0,
        share_tendency=1.0,
    )
    decision_input = DecisionInput(time_step=2, prompt_version="engage-provider-v1", **context)

    messages = build_engagement_prompt(decision_input)
    payload = json.loads(messages[1]["content"])

    assert messages[0]["role"] == "system"
    assert payload["post_content"]["text"] == "Eco skincare launch"
    assert payload["individual_preference"]["user_id"] == "u1"
    assert "brand_attitude" not in payload["individual_preference"]
    assert "like_tendency" not in payload["individual_preference"]
    assert "comment_tendency" not in payload["individual_preference"]
    assert "share_tendency" not in payload["individual_preference"]
    assert payload["peer_influence"]["engaged_neighbors"] == 2
    assert payload["required_output_schema"]["engage"] == "boolean"
    assert "api_key" not in messages[1]["content"]


def test_mocked_provider_success_validates_engage_decision():
    client = FakeProviderClient(
        '{"engage": true, "probability": 0.8, "reason": "fit", "confidence": 0.9, "action": "like"}'
    )
    adapter = OpenAICompatibleDecisionAdapter(ProviderLLMConfig(enabled=True, model="mock-model"), client=client)

    decision = adapter.decide(time_step=1, **sample_context())

    assert decision.engage is True
    assert decision.probability == 0.8
    assert decision.reason == "fit"
    assert decision.confidence == 0.9
    assert decision.action == "like"
    assert decision.decision_source == "provider"
    assert decision.provider_metadata is not None
    assert client.calls[0][1] == "mock-model"


@pytest.mark.parametrize("response", ["not-json", '{"engage": true, "probability": 2.0, "confidence": 0.9}'])
def test_provider_malformed_or_schema_invalid_raises_by_default(response):
    adapter = OpenAICompatibleDecisionAdapter(ProviderLLMConfig(enabled=True), client=FakeProviderClient(response))

    with pytest.raises((ValueError, ValidationError)):
        adapter.decide(**sample_context())


def test_fail_closed_no_engage_returns_safe_ignore_decision():
    adapter = OpenAICompatibleDecisionAdapter(
        ProviderLLMConfig(enabled=True, fail_closed_action=FailClosedAction.NO_ENGAGE),
        client=FakeProviderClient(None, exc=TimeoutError("boom secret sk-hidden")),
    )

    decision = adapter.decide(**sample_context())

    assert decision.engage is False
    assert decision.action == "ignore"
    assert decision.probability == 0.0
    assert decision.decision_source == "provider_fail_closed"
    assert "sk-hidden" not in decision.reason


def test_fail_closed_skip_run_raises_skip_signal():
    adapter = OpenAICompatibleDecisionAdapter(
        ProviderLLMConfig(enabled=True, fail_closed_action=FailClosedAction.SKIP_RUN),
        client=FakeProviderClient(None, exc=RuntimeError("unavailable")),
    )

    with pytest.raises(ProviderRunSkipped):
        adapter.decide(**sample_context())


def test_provider_metadata_and_redaction_are_secret_safe(tmp_path):
    (tmp_path / "config.toml").write_text(
        """
model = "gpt-5.5"
model_provider = "sub2api"

[model_providers.sub2api]
base_url = "https://api.example.test"
wire_api = "responses"
requires_openai_auth = true
api_key = "sk-should-not-load"
""",
        encoding="utf-8",
    )
    (tmp_path / "auth.json").write_text('{"tokens":{"access_token":"very-secret"}}', encoding="utf-8")
    adapter = OpenAICompatibleDecisionAdapter(
        ProviderLLMConfig(enabled=True, use_codex_provider_config=True),
        client=FakeProviderClient({"engage": False, "probability": 0.1, "reason": "low fit", "confidence": 0.8}),
        codex_home=tmp_path,
    )

    metadata = adapter.safe_metadata
    serialized = json.dumps(redact_secrets(metadata), sort_keys=True)

    assert metadata["codex_provider"]["provider_name"] == "sub2api"
    assert metadata["codex_provider"]["auth_available"] is True
    assert "very-secret" not in serialized
    assert "sk-should-not-load" not in serialized


def test_provider_retries_timeout_before_success():
    class FlakyClient:
        def __init__(self):
            self.calls = 0

        def create_response(self, messages: list[dict[str, str]], model: str):
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError("temporary")
            return {"engage": True, "probability": 0.7, "reason": "retry ok", "confidence": 0.8, "action": "share"}

    client = FlakyClient()
    adapter = OpenAICompatibleDecisionAdapter(ProviderLLMConfig(enabled=True, max_retries=1), client=client)

    decision = adapter.decide(**sample_context())

    assert client.calls == 2
    assert decision.action == "share"
    assert decision.decision_source == "provider"


def test_cached_provider_adapter_avoids_duplicate_provider_calls():
    from llm_abm_sim.decision import CachedDecisionAdapter, InMemoryDecisionCache

    client = FakeProviderClient(
        {"engage": True, "probability": 0.6, "reason": "cached", "confidence": 0.8, "action": "like"}
    )
    provider = OpenAICompatibleDecisionAdapter(ProviderLLMConfig(enabled=True), client=client)
    cached = CachedDecisionAdapter(provider, InMemoryDecisionCache(), prompt_version="engage-provider-v1")

    first = cached.decide(**sample_context())
    second = cached.decide(**sample_context())

    assert first == second
    assert first.decision_source == "provider"
    assert len(client.calls) == 1
