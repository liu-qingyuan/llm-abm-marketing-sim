from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from pydantic import ValidationError

from llm_abm_sim.decision import DecisionInput, ProviderDecisionError
from llm_abm_sim.prompting import build_engagement_prompt
from llm_abm_sim.provider_config import RuntimeCredential, redact_secrets
from llm_abm_sim.providers import openai_compatible
from llm_abm_sim.providers.openai_compatible import (
    OpenAICompatibleDecisionAdapter,
    ProviderConfigurationError,
    ProviderResponseEnvelope,
    ProviderRunSkipped,
    _OpenAISDKClient,
)
from llm_abm_sim.schemas import (
    FailClosedAction,
    LatentAttributes,
    LatentProfileLabels,
    LatentValueWeights,
    PeerContext,
    PlatformContext,
    PostContent,
    ProviderLLMConfig,
    UserProfile,
)


class _UnusedSDKClient:
    def create_response(self, messages: list[dict[str, str]], model: str):
        del messages, model
        raise AssertionError("client construction must not invoke a request")


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
    context["profile"] = UserProfile.model_validate(
        {
            "user_id": "u1",
            "interest_tags": ["skincare"],
            "global_influence_score": 0.9,
            "brand_attitude": 1.0,
            "like_tendency": 1.0,
            "comment_tendency": 1.0,
            "share_tendency": 1.0,
            "latent_attributes": LatentAttributes(
                spec_id="jinjiang_user_latent_attributes_v1",
                method="latent_class_exact_quota_v1",
                seed=20260630,
                latent_class="class_1",
                environmental_consciousness_coef=0.8,
                value_weights=LatentValueWeights(
                    epistemic=0.1,
                    environmental=0.8,
                    functional=0.4,
                    health=0.7,
                    emotional=0.2,
                    social=0.3,
                ),
                profile_labels=LatentProfileLabels(
                    hotel_class="economy",
                    travel_purpose="business",
                    gender="female",
                    age="age_26_35",
                    education="bachelor",
                    monthly_income="income_8001_15000",
                ),
            ),
        }
    )
    decision_input = DecisionInput(time_step=2, prompt_version="engage-provider-v1", **context)

    messages = build_engagement_prompt(decision_input)
    system_content = messages[0]["content"]
    user_content = messages[1]["content"]

    assert messages[0]["role"] == "system"
    assert "模拟一名抖音用户无意间刷到锦江酒店集团使用秸秆制品、推进环保举措的绿色营销内容" in system_content
    assert "只返回一个 JSON 对象" in system_content
    assert "【营销内容】" in user_content
    assert "Eco skincare launch" in user_content
    assert "【内容主要强调的价值】" in user_content
    assert "未提供明确价值维度" in user_content
    assert "主题标签：eco、skincare" not in user_content
    assert "【用户可观测特征】" in user_content
    assert "【用户消费偏好】" in user_content
    assert (
        "说明：活跃度、全平台影响力、锦江酒店社群内的局部影响力为可观测代理指标；"
        "活跃度：中等（0.50）；全平台影响力：高（0.90）" in user_content
    )
    assert "历史 hashtags 与文本主题派生的兴趣代理" not in user_content
    assert "interest_tags" not in user_content
    assert (
        "环保意识倾向、消费价值、入住酒店类型和入住目的为虚拟实验标签，不代表真实身份或心理画像；"
        "环保意识倾向：正向（0.80）；前三个秸秆制品相关消费价值：环保消费价值（0.80）、健康价值（0.70）、功能价值（0.40）；"
        "最近一次入住锦江旗下酒店类型：经济型酒店；最近一次入住锦江旗下酒店目的：商务出行" in user_content
    )
    assert "brand_attitude" not in user_content
    assert "like_tendency" not in user_content
    assert "comment_tendency" not in user_content
    assert "share_tendency" not in user_content
    assert "latent_class" not in user_content
    assert "female" not in user_content
    assert "age_26_35" not in user_content
    assert "bachelor" not in user_content
    assert "income_8001_15000" not in user_content
    assert "【其他用户行为】" in user_content
    assert (
        "邻居曝光：4；邻居互动：2；互动比例：0.50；有影响力的已互动邻居：0；可见点赞：3；可见评论：0；可见分享：0"
        in user_content
    )
    assert "平台上下文：平台热门话题：eco；平台氛围：launch week；Feed 排序权重：1.00；痕迹可见度：1.00" in user_content
    assert "输出 schema" in user_content
    assert "engage" in user_content
    assert "action" in user_content
    assert "engage=false 时 action 必须为 ignore" in user_content
    assert "api_key" not in user_content


def test_prompt_keeps_full_marketing_copy_without_topic_tag_expansion():
    long_text = "锦江绿色营销 " + "秸秆制品环保行动" * 40
    decision_input = DecisionInput(
        post=PostContent(post_id="p2", text=long_text, topic_tags=["tag"] * 20),
        profile=UserProfile(user_id="u1"),
        peer_context=PeerContext(),
        platform_context=PlatformContext(),
        time_step=0,
        prompt_version="jinjiang-green-marketing-prompt-v3",
    )

    user_content = build_engagement_prompt(decision_input)[1]["content"]

    assert long_text in user_content
    assert "主题标签" not in user_content


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
    assert adapter.live_api_triggered is False


def test_falsey_injected_client_never_falls_through_to_live_client(monkeypatch):
    class FalseyClient(FakeProviderClient):
        def __bool__(self) -> bool:
            return False

    client = FalseyClient(
        '{"engage": false, "probability": 0.1, "reason": "low", "confidence": 0.8, "action": "ignore"}'
    )
    adapter = OpenAICompatibleDecisionAdapter(ProviderLLMConfig(enabled=True), client=client)

    def fail_live_client_build():
        raise AssertionError("injected client must be used explicitly")

    monkeypatch.setattr(adapter, "_build_live_client", fail_live_client_build)

    decision = adapter.decide(**sample_context())

    assert decision.action == "ignore"
    assert len(client.calls) == 1
    assert adapter.external_request_invocations == 0
    assert adapter.provider_accounting.provider_response_count == 1


def test_provider_envelope_accounts_returned_response_before_successful_decision():
    client = FakeProviderClient(
        ProviderResponseEnvelope(
            decision_text=(
                '{"engage": true, "probability": 0.8, "reason": "fit", '
                '"confidence": 0.9, "action": "like"}'
            ),
            observed_model="observed-model",
            observed_model_status="reported",
            usage_status="complete",
            input_tokens=12,
            output_tokens=8,
            total_tokens=20,
            cached_input_tokens=5,
        )
    )
    adapter = OpenAICompatibleDecisionAdapter(ProviderLLMConfig(enabled=True, model="requested-model"), client=client)

    decision = adapter.decide(**sample_context())

    assert decision.action == "like"
    assert adapter.provider_accounting.model_dump(mode="json") == {
        "schema_version": "provider-accounting-v1",
        "external_request_invocations": 0,
        "provider_response_count": 1,
        "successful_decision_count": 1,
        "observed_model_counts": {"observed-model": 1},
        "observed_model_missing_response_count": 0,
        "observed_model_malformed_response_count": 0,
        "usage_complete_response_count": 1,
        "usage_missing_response_count": 0,
        "usage_malformed_response_count": 0,
        "input_tokens": 12,
        "output_tokens": 8,
        "total_tokens": 20,
        "cached_input_tokens": 5,
        "cached_input_tokens_reported_response_count": 1,
    }


def test_live_sdk_client_uses_scoped_codex_auth_and_headers_without_serializing_values(monkeypatch, tmp_path):
    secret = "sub2api-header-secret"
    (tmp_path / "config.toml").write_text(
        f'''
model = "gpt-5.6-sol"
model_provider = "sub2api"

[model_providers.sub2api]
base_url = "https://api.example.test"
wire_api = "responses"
requires_openai_auth = false
http_headers = {{ "x-openai-actor-authorization" = "{secret}" }}
''',
        encoding="utf-8",
    )
    (tmp_path / "auth.json").write_text('{"OPENAI_API_KEY":"codex-secret"}', encoding="utf-8")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("LLM_ABM_RUN_LIVE_LLM", "1")
    monkeypatch.setattr(openai_compatible.importlib.util, "find_spec", lambda _name: object())
    captured: dict[str, object] = {}

    def build_client(**kwargs):
        captured.update(kwargs)
        return _UnusedSDKClient()

    monkeypatch.setattr(openai_compatible, "_OpenAISDKClient", build_client)
    adapter = OpenAICompatibleDecisionAdapter(
        ProviderLLMConfig(enabled=True, use_codex_provider_config=True, require_live_env=True),
        codex_home=tmp_path,
    )

    adapter._build_live_client()

    assert captured["api_key"] == "codex-secret"
    assert captured["default_headers"] == {"x-openai-actor-authorization": secret}
    assert secret not in json.dumps(adapter.safe_metadata)
    assert adapter.safe_metadata["codex_provider"]["http_header_names"] == ["x-openai-actor-authorization"]
    assert adapter.live_api_triggered is False


def test_scoped_codex_headers_reject_a_different_base_url(monkeypatch, tmp_path):
    (tmp_path / "config.toml").write_text(
        '''
model = "gpt-5.6-sol"
model_provider = "sub2api"

[model_providers.sub2api]
base_url = "https://selected.example.test"
wire_api = "responses"
requires_openai_auth = false
http_headers = { "x-openai-actor-authorization" = "selected-secret" }
''',
        encoding="utf-8",
    )
    (tmp_path / "auth.json").write_text('{"OPENAI_API_KEY":"codex-secret"}', encoding="utf-8")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("LLM_ABM_RUN_LIVE_LLM", "1")
    monkeypatch.setattr(openai_compatible.importlib.util, "find_spec", lambda _name: object())
    adapter = OpenAICompatibleDecisionAdapter(
        ProviderLLMConfig(
            enabled=True,
            base_url="https://unselected.example.test",
            use_codex_provider_config=True,
            require_live_env=True,
        ),
        codex_home=tmp_path,
    )

    with pytest.raises(ProviderConfigurationError, match="base_url"):
        adapter._build_live_client()


def test_responses_wire_normalizes_safe_model_and_usage_envelope():
    decision_text = '{"engage": false, "probability": 0.1, "reason": "low", "confidence": 0.8, "action": "ignore"}'
    sdk_response = SimpleNamespace(
        output_text=decision_text,
        model="observed-responses-model",
        usage=SimpleNamespace(
            input_tokens=21,
            output_tokens=9,
            total_tokens=30,
            input_tokens_details=SimpleNamespace(cached_tokens=7),
        ),
        id="must-not-persist",
        headers={"Authorization": "must-not-persist"},
    )
    sdk_client = object.__new__(_OpenAISDKClient)
    sdk_client._wire_api = "responses"
    sdk_client._extra_headers = None
    sdk_client._client = cast(
        Any,
        SimpleNamespace(responses=SimpleNamespace(create=lambda **_kwargs: sdk_response)),
    )

    envelope = sdk_client.create_response([{"role": "user", "content": "test"}], "requested-model")

    assert envelope == ProviderResponseEnvelope(
        decision_text=decision_text,
        observed_model="observed-responses-model",
        observed_model_status="reported",
        usage_status="complete",
        input_tokens=21,
        output_tokens=9,
        total_tokens=30,
        cached_input_tokens=7,
    )
    assert set(envelope.model_dump()) == {
        "decision_text",
        "observed_model",
        "observed_model_status",
        "usage_status",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cached_input_tokens",
    }
    assert "must-not-persist" not in envelope.model_dump_json()


def test_chat_wire_normalizes_usage_without_synthesizing_cached_tokens():
    decision_text = '{"engage": true, "probability": 0.7, "reason": "fit", "confidence": 0.8, "action": "share"}'
    sdk_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=decision_text))],
        model="observed-chat-model",
        usage=SimpleNamespace(prompt_tokens=14, completion_tokens=6, total_tokens=20),
    )
    sdk_client = object.__new__(_OpenAISDKClient)
    sdk_client._wire_api = "chat"
    sdk_client._extra_headers = None
    sdk_client._client = cast(
        Any,
        SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=lambda **_kwargs: sdk_response),
            )
        ),
    )

    envelope = sdk_client.create_response([{"role": "user", "content": "test"}], "requested-model")

    assert envelope == ProviderResponseEnvelope(
        decision_text=decision_text,
        observed_model="observed-chat-model",
        observed_model_status="reported",
        usage_status="complete",
        input_tokens=14,
        output_tokens=6,
        total_tokens=20,
        cached_input_tokens=None,
    )


@pytest.mark.parametrize(
    ("usage", "expected_status"),
    [
        (None, "missing"),
        (SimpleNamespace(input_tokens=4, output_tokens=2), "malformed"),
        (SimpleNamespace(input_tokens=True, output_tokens=2, total_tokens=3), "malformed"),
        (SimpleNamespace(input_tokens=-1, output_tokens=2, total_tokens=1), "malformed"),
        (SimpleNamespace(input_tokens=4, output_tokens=2, total_tokens=7), "malformed"),
        (
            SimpleNamespace(
                input_tokens=4,
                output_tokens=2,
                total_tokens=6,
                input_tokens_details="broken",
            ),
            "malformed",
        ),
        (
            SimpleNamespace(
                input_tokens=4,
                output_tokens=2,
                total_tokens=6,
                input_tokens_details=SimpleNamespace(cached_tokens=5),
            ),
            "malformed",
        ),
    ],
)
def test_responses_wire_downgrades_missing_or_malformed_usage_without_estimation(usage, expected_status):
    sdk_response = SimpleNamespace(
        output_text=(
            '{"engage": false, "probability": 0.1, "reason": "low", '
            '"confidence": 0.8, "action": "ignore"}'
        ),
        model="observed-model",
        usage=usage,
    )
    sdk_client = object.__new__(_OpenAISDKClient)
    sdk_client._wire_api = "responses"
    sdk_client._extra_headers = None
    sdk_client._client = cast(
        Any,
        SimpleNamespace(responses=SimpleNamespace(create=lambda **_kwargs: sdk_response)),
    )

    envelope = sdk_client.create_response([{"role": "user", "content": "test"}], "requested-model")

    assert envelope.usage_status == expected_status
    assert envelope.input_tokens is None
    assert envelope.output_tokens is None
    assert envelope.total_tokens is None
    assert envelope.cached_input_tokens is None
    assert envelope.decision_text.startswith('{"engage"')


@pytest.mark.parametrize(
    ("model", "expected_model", "expected_status"),
    [
        (None, None, "missing"),
        ("", None, "malformed"),
        (" ", None, "malformed"),
        ("Bearer hidden", None, "malformed"),
        ("sk-hidden", None, "malformed"),
        ("sub2api-header-secret", None, "malformed"),
        ("ghp_deadbeef", None, "malformed"),
        ("eyJhbGciOiJIUzI1NiJ9.payload.signature", None, "malformed"),
        (False, None, "malformed"),
        ("observed-model", "observed-model", "reported"),
    ],
)
def test_responses_wire_classifies_observed_model(model, expected_model, expected_status):
    sdk_response = SimpleNamespace(
        output_text=(
            '{"engage": false, "probability": 0.1, "reason": "low", '
            '"confidence": 0.8, "action": "ignore"}'
        ),
        model=model,
        usage=None,
    )
    sdk_client = object.__new__(_OpenAISDKClient)
    sdk_client._wire_api = "responses"
    sdk_client._extra_headers = None
    sdk_client._client = cast(
        Any,
        SimpleNamespace(responses=SimpleNamespace(create=lambda **_kwargs: sdk_response)),
    )

    envelope = sdk_client.create_response([{"role": "user", "content": "test"}], "requested-model")

    assert envelope.observed_model == expected_model
    assert envelope.observed_model_status == expected_status


def test_usage_metadata_getter_failure_is_malformed_without_retrying_a_valid_decision():
    class HostileDetails:
        def __getattribute__(self, name: str):
            if name in {"__dict__", "cached_tokens"}:
                raise RuntimeError("metadata access must not escape")
            return super().__getattribute__(name)

    class HostileUsage:
        input_tokens = 4
        output_tokens = 2
        total_tokens = 6

        @property
        def input_tokens_details(self):
            raise RuntimeError("metadata access must not escape")

    calls = 0

    def create_response(**_kwargs):
        nonlocal calls
        calls += 1
        return SimpleNamespace(
            output_text=(
                '{"engage": false, "probability": 0.1, "reason": "low", '
                '"confidence": 0.8, "action": "ignore"}'
            ),
            model="observed-model",
            usage=(
                SimpleNamespace(
                    input_tokens=4,
                    output_tokens=2,
                    total_tokens=6,
                    input_tokens_details=HostileDetails(),
                )
                if calls == 1
                else HostileUsage()
            ),
        )

    sdk_client = object.__new__(_OpenAISDKClient)
    sdk_client._wire_api = "responses"
    sdk_client._extra_headers = None
    sdk_client._client = cast(
        Any,
        SimpleNamespace(responses=SimpleNamespace(create=create_response)),
    )
    adapter = OpenAICompatibleDecisionAdapter(
        ProviderLLMConfig(enabled=True, max_retries=1),
        client=sdk_client,
    )

    decisions = [adapter.decide(**sample_context()) for _ in range(2)]

    assert {decision.action for decision in decisions} == {"ignore"}
    assert calls == 2
    assert adapter.provider_accounting.provider_response_count == 2
    assert adapter.provider_accounting.successful_decision_count == 2
    assert adapter.provider_accounting.usage_malformed_response_count == 2


def test_openai_sdk_client_sends_scoped_headers_without_synthetic_bearer(monkeypatch):
    for name in ("ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "http_proxy", "https_proxy"):
        monkeypatch.delenv(name, raising=False)
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "resp_test",
                "created_at": 0,
                "model": "test-model",
                "object": "response",
                "output": [],
                "parallel_tool_calls": False,
                "tool_choice": "auto",
                "tools": [],
            },
            request=request,
        )

    client = _OpenAISDKClient(
        api_key=None,
        base_url="https://api.example.test",
        timeout=1.0,
        default_headers={"x-openai-actor-authorization": "test-only-secret"},
        http_client=httpx.Client(transport=httpx.MockTransport(handle)),
    )

    envelope = client.create_response([{"role": "user", "content": "test"}], "test-model")

    assert envelope.decision_text == ""
    assert envelope.observed_model == "test-model"
    assert envelope.observed_model_status == "reported"
    assert envelope.usage_status == "missing"
    assert len(requests) == 1
    assert requests[0].headers["x-openai-actor-authorization"] == "test-only-secret"
    assert "authorization" not in requests[0].headers
    assert client._client.max_retries == 0


def test_openai_sdk_client_preserves_explicit_provider_authorization(monkeypatch):
    for name in ("ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "http_proxy", "https_proxy"):
        monkeypatch.delenv(name, raising=False)
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "resp_test",
                "created_at": 0,
                "model": "test-model",
                "object": "response",
                "output": [],
                "parallel_tool_calls": False,
                "tool_choice": "auto",
                "tools": [],
            },
            request=request,
        )

    client = _OpenAISDKClient(
        api_key=None,
        base_url="https://api.example.test",
        timeout=1.0,
        default_headers={"Authorization": "Bearer selected-provider-token"},
        http_client=httpx.Client(transport=httpx.MockTransport(handle)),
    )

    client.create_response([{"role": "user", "content": "test"}], "test-model")

    assert len(requests) == 1
    assert requests[0].headers["authorization"] == "Bearer selected-provider-token"


def test_openai_sdk_client_keeps_bearer_when_runtime_credential_exists(monkeypatch):
    for name in ("ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "http_proxy", "https_proxy"):
        monkeypatch.delenv(name, raising=False)

    client = _OpenAISDKClient(
        api_key="provider-api-key",
        base_url="https://api.example.test",
        timeout=1.0,
    )

    assert client._client.auth_headers == {"Authorization": "Bearer provider-api-key"}
    assert client._client.max_retries == 0


def test_building_live_sdk_client_does_not_mark_external_request_invocation(monkeypatch):
    monkeypatch.setattr(openai_compatible, "should_run_live_llm", lambda _codex_home: True)
    monkeypatch.setattr(openai_compatible.importlib.util, "find_spec", lambda _name: object())
    monkeypatch.setattr(
        openai_compatible,
        "resolve_runtime_credential",
        lambda **_kwargs: RuntimeCredential(value="test-only", source="test"),
    )
    monkeypatch.setattr(openai_compatible, "_OpenAISDKClient", lambda **_kwargs: _UnusedSDKClient())
    adapter = OpenAICompatibleDecisionAdapter(ProviderLLMConfig(enabled=True, require_live_env=True))

    adapter._build_live_client()

    assert adapter.live_api_triggered is False


@pytest.mark.parametrize(
    "response",
    [
        "not-json",
        '{"engage": true, "probability": 2.0, "confidence": 0.9}',
        '{"engage": false, "probability": 0.2, "confidence": 0.9, "action": "ignore"}',
        '{"engage": false, "probability": 0.2, "reason": "low fit", "confidence": 0.9, "action": "like"}',
        '{"engage": true, "probability": 0.8, "reason": "fit", "confidence": 0.9, "action": "ignore"}',
    ],
)
def test_provider_malformed_or_schema_invalid_raises_by_default(response):
    adapter = OpenAICompatibleDecisionAdapter(ProviderLLMConfig(enabled=True), client=FakeProviderClient(response))

    with pytest.raises(ProviderDecisionError) as caught:
        adapter.decide(**sample_context())

    assert isinstance(caught.value.__cause__, (ValueError, ValidationError))


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
        client=FakeProviderClient(
            {"engage": False, "probability": 0.1, "reason": "low fit", "confidence": 0.8, "action": "ignore"}
        ),
        codex_home=tmp_path,
    )

    metadata = adapter.safe_metadata
    serialized = json.dumps(redact_secrets(metadata), sort_keys=True)

    assert metadata["codex_provider"]["provider_name"] == "sub2api"
    assert metadata["codex_provider"]["auth_available"] is True
    assert "very-secret" not in serialized
    assert "sk-should-not-load" not in serialized


def test_malformed_decision_retry_keeps_every_returned_response_in_accounting():
    responses = [
        ProviderResponseEnvelope(
            decision_text="not-json",
            observed_model="first-model",
            observed_model_status="reported",
            usage_status="complete",
            input_tokens=10,
            output_tokens=2,
            total_tokens=12,
            cached_input_tokens=None,
        ),
        ProviderResponseEnvelope(
            decision_text=(
                '{"engage": true, "probability": 0.7, "reason": "retry ok", '
                '"confidence": 0.8, "action": "share"}'
            ),
            observed_model="second-model",
            observed_model_status="reported",
            usage_status="complete",
            input_tokens=11,
            output_tokens=3,
            total_tokens=14,
            cached_input_tokens=4,
        ),
    ]

    class SequenceClient:
        def __init__(self):
            self.calls = 0

        def create_response(self, messages: list[dict[str, str]], model: str):
            del messages, model
            response = responses[self.calls]
            self.calls += 1
            return response

    client = SequenceClient()
    adapter = OpenAICompatibleDecisionAdapter(
        ProviderLLMConfig(enabled=True, max_retries=1, retry_backoff_seconds=0),
        client=client,
        sleep=lambda _delay: None,
    )

    decision = adapter.decide(**sample_context())
    accounting = adapter.provider_accounting

    assert decision.action == "share"
    assert client.calls == 2
    assert accounting.provider_response_count == 2
    assert accounting.successful_decision_count == 1
    assert accounting.observed_model_counts == {"first-model": 1, "second-model": 1}
    assert accounting.usage_complete_response_count == 2
    assert accounting.input_tokens == 21
    assert accounting.output_tokens == 5
    assert accounting.total_tokens == 26
    assert accounting.cached_input_tokens == 4
    assert accounting.cached_input_tokens_reported_response_count == 1


def test_provider_accounting_aggregates_mixed_model_and_usage_statuses_without_changing_decisions():
    decision_text = (
        '{"engage": false, "probability": 0.1, "reason": "low", '
        '"confidence": 0.8, "action": "ignore"}'
    )
    responses = [
        ProviderResponseEnvelope(
            decision_text=decision_text,
            observed_model="requested-model",
            observed_model_status="reported",
            usage_status="complete",
            input_tokens=10,
            output_tokens=2,
            total_tokens=12,
            cached_input_tokens=2,
        ),
        ProviderResponseEnvelope(
            decision_text=decision_text,
            observed_model="wrong-model",
            observed_model_status="reported",
            usage_status="complete",
            input_tokens=10,
            output_tokens=2,
            total_tokens=12,
            cached_input_tokens=None,
        ),
        ProviderResponseEnvelope(
            decision_text=decision_text,
            observed_model=None,
            observed_model_status="missing",
            usage_status="missing",
        ),
        ProviderResponseEnvelope(
            decision_text=decision_text,
            observed_model=None,
            observed_model_status="malformed",
            usage_status="malformed",
        ),
    ]

    class SequenceClient:
        def create_response(self, messages: list[dict[str, str]], model: str) -> ProviderResponseEnvelope:
            del messages, model
            return responses.pop(0)

    adapter = OpenAICompatibleDecisionAdapter(
        ProviderLLMConfig(enabled=True, model="requested-model"),
        client=SequenceClient(),
    )

    decisions = [adapter.decide(**sample_context()) for _ in range(4)]
    accounting = adapter.provider_accounting

    assert {decision.action for decision in decisions} == {"ignore"}
    assert accounting.provider_response_count == accounting.successful_decision_count == 4
    assert accounting.observed_model_counts == {"requested-model": 1, "wrong-model": 1}
    assert accounting.observed_model_missing_response_count == 1
    assert accounting.observed_model_malformed_response_count == 1
    assert accounting.usage_complete_response_count == 2
    assert accounting.usage_missing_response_count == 1
    assert accounting.usage_malformed_response_count == 1
    assert accounting.input_tokens == 20
    assert accounting.output_tokens == 4
    assert accounting.total_tokens == 24
    assert accounting.cached_input_tokens == 2
    assert accounting.cached_input_tokens_reported_response_count == 1


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
    delays: list[float] = []
    adapter = OpenAICompatibleDecisionAdapter(
        ProviderLLMConfig(enabled=True, max_retries=1, retry_backoff_seconds=0.25),
        client=client,
        sleep=delays.append,
    )

    decision = adapter.decide(**sample_context())

    assert client.calls == 2
    assert delays == [0.25]
    assert decision.action == "share"
    assert decision.decision_source == "provider"
    assert adapter.provider_accounting.provider_response_count == 1
    assert adapter.provider_accounting.successful_decision_count == 1
    assert adapter.provider_accounting.usage_missing_response_count == 1


def test_live_client_transport_attempts_count_invocations_without_synthesizing_responses(monkeypatch):
    client = FakeProviderClient(None, exc=TimeoutError("temporary"))
    adapter = OpenAICompatibleDecisionAdapter(
        ProviderLLMConfig(enabled=True, require_live_env=False, max_retries=1, retry_backoff_seconds=0),
        sleep=lambda _delay: None,
    )
    monkeypatch.setattr(adapter, "_build_live_client", lambda: client)

    with pytest.raises(ProviderDecisionError, match="TimeoutError"):
        adapter.decide(**sample_context())

    assert adapter.external_request_invocations == 2
    assert adapter.provider_accounting.external_request_invocations == 2
    assert adapter.provider_accounting.provider_response_count == 0
    assert adapter.provider_accounting.successful_decision_count == 0
    assert adapter.provider_accounting.usage_complete_response_count == 0


def test_provider_retry_backoff_is_exponential_and_capped_at_five_retries():
    client = FakeProviderClient(None, exc=TimeoutError("temporary"))
    delays: list[float] = []
    config = ProviderLLMConfig(enabled=True, max_retries=5, retry_backoff_seconds=0.1)
    adapter = OpenAICompatibleDecisionAdapter(config, client=client, sleep=delays.append)

    with pytest.raises(ProviderDecisionError, match="TimeoutError") as caught:
        adapter.decide(**sample_context())

    assert caught.value.failure_type == "TimeoutError"
    assert isinstance(caught.value.__cause__, TimeoutError)
    assert len(client.calls) == 6
    assert delays == [0.1, 0.2, 0.4, 0.8, 1.6]
    assert config.safe_metadata()["retry_backoff_seconds"] == 0.1

    with pytest.raises(ValidationError, match="less than or equal to 5"):
        ProviderLLMConfig(enabled=True, max_retries=6)


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
    assert provider.provider_accounting.provider_response_count == 1
    assert provider.provider_accounting.successful_decision_count == 1
