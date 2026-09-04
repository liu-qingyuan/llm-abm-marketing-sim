from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic import ValidationError

from llm_abm_sim.decision import DecisionInput
from llm_abm_sim.prompt_contracts import (
    CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY,
    CONCURRENT_ROBUSTNESS_PROMPT_TOKENS,
)
from llm_abm_sim.prompt_field_summary import CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION
from llm_abm_sim.prompting import build_engagement_prompt
from llm_abm_sim.provider_accounting import ProviderResponseEnvelope
from llm_abm_sim.provider_evidence import allowlisted_provider_evidence
from llm_abm_sim.provider_request_contract import engage_decision_json_schema, validate_robustness_request_contract
from llm_abm_sim.providers.openai_compatible import OpenAICompatibleDecisionAdapter, _OpenAISDKClient
from llm_abm_sim.schemas import (
    PeerContext,
    PlatformContext,
    PostContent,
    ProviderLLMConfig,
    ReasoningEffort,
    UserProfile,
    ValueDimensions,
)


def test_prompt_registry_exposes_four_frozen_information_equivalent_contracts() -> None:
    contracts = CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.all()

    assert tuple(contract.variant_id for contract in contracts) == ("P0", "P1", "P2", "P3")
    assert tuple(
        CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.controlled_change(contract.variant_id)
        for contract in contracts
    ) == ("baseline", "wording_only", "information_order_only", "structured_rubric_only")
    assert tuple(contract.prompt_version for contract in contracts) == CONCURRENT_ROBUSTNESS_PROMPT_TOKENS
    assert contracts[0].prompt_version == CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION
    assert len({contract.prompt_version for contract in contracts}) == 4
    assert len({contract.canonical_hash for contract in contracts}) == 4
    assert tuple(contract.canonical_hash for contract in contracts) == (
        "sha256:cc50affc4e658a9a1804f5e1824710cb073003aff3cc6af8f8c5cd8edf5cdc7c",
        "sha256:67b38d5edfc562bf43a115d9a7aaebc856d51049614dc4cc633c431dd57bf0e1",
        "sha256:6784ecc2163e6b2426631d81672994376c3781791fa265c3e0f67d1428b71cb4",
        "sha256:a3ac934d194437f6ee86011b92666cf1ea19fb086a383fb7b7407cf5f44bd7ea",
    )
    assert len({contract.visible_field_allowlist for contract in contracts}) == 1
    assert len({contract.excluded_fields for contract in contracts}) == 1
    assert len({contract.task_semantics for contract in contracts}) == 1
    assert len({contract.action_semantics for contract in contracts}) == 1
    assert len({contract.output_schema for contract in contracts}) == 1
    assert len({contract.equivalence_checklist for contract in contracts}) == 1


def test_prompt_catalog_exposes_complete_client_templates_without_rendered_user_values() -> None:
    records = CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.catalog_records()

    assert tuple(record["variant_id"] for record in records) == ("P0", "P1", "P2", "P3")
    assert tuple(record["controlled_change"] for record in records) == (
        "baseline",
        "wording_only",
        "information_order_only",
        "structured_rubric_only",
    )
    assert all(record["schema_version"] == "concurrent-robustness-prompt-catalog-record-v1" for record in records)
    assert all(record["prompt_version"] in CONCURRENT_ROBUSTNESS_PROMPT_TOKENS for record in records)
    assert all(str(record["canonical_hash"]).startswith("sha256:") for record in records)
    assert all(record["placeholder_fields"] == (
        "marketing_content_summary",
        "post_value_summary",
        "observed_profile_summary",
        "consumption_preference_summary",
        "peer_influence_summary",
    ) for record in records)
    messages_by_variant: dict[str, tuple[dict[str, str], ...]] = {}
    for record in records:
        messages = cast(
            tuple[dict[str, str], ...],
            record["client_submitted_message_templates"],
        )
        messages_by_variant[str(record["variant_id"])] = messages
        assert tuple(message["role"] for message in messages) == ("system", "user")
        assert all(isinstance(message["content"], str) and message["content"] for message in messages)
        user_template = messages[1]["content"]
        placeholder_fields = cast(tuple[str, ...], record["placeholder_fields"])
        assert all(f"{{{{{field}}}}}" in user_template for field in placeholder_fields)
        assert "【输出 schema】" in user_template
        decision_schema = cast(dict[str, object], record["decision_output_schema"])
        assert decision_schema["required_fields"] == (
            "engage",
            "probability",
            "reason",
            "confidence",
            "action",
        )
        serialized = json.dumps(record, ensure_ascii=False)
        assert "excluded-user-id" not in serialized
        assert "rendered_prompt" not in serialized
    assert "【结构化判断 rubric】" not in messages_by_variant["P0"][1]["content"]
    assert "【结构化判断 rubric】" in messages_by_variant["P3"][1]["content"]


def test_all_prompt_variants_render_the_same_allowlisted_decision_information() -> None:
    profile = UserProfile.model_validate(
        {
            "user_id": "excluded-user-id",
            "activity_score": 0.5,
            "interest_tags": ["excluded-interest-tag"],
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
            "nickname": "excluded-nickname",
            "ranking_score": "excluded-ranking",
            "campaign_feedback": "excluded-feedback",
        }
    )
    post = PostContent(
        post_id="excluded-post-id",
        text="allowlisted-current-message",
        topic_tags=["excluded-topic-tag"],
        media_summary="excluded-media-summary",
        value_dimensions=ValueDimensions(environmental=1.0),
    )

    prompts = []
    for token in CONCURRENT_ROBUSTNESS_PROMPT_TOKENS:
        prompts.append(
            build_engagement_prompt(
                DecisionInput(
                    post=post,
                    profile=profile,
                    peer_context=PeerContext(),
                    platform_context=PlatformContext(platform_mood="excluded-platform"),
                    time_step=9,
                    prompt_version=token,
                )
            )
        )

    for messages in prompts:
        assert [message["role"] for message in messages] == ["system", "user"]
        user_content = messages[1]["content"]
        assert user_content.count("allowlisted-current-message") == 1
        assert "全平台影响力：高（0.90）" in user_content
        assert "环保意识倾向：正向较强（1.00）" in user_content
        assert "环保消费价值（0.80）" in user_content
        assert "最近一次入住锦江旗下酒店类型：中端酒店" in user_content
        assert "邻居曝光：0；邻居互动：0；互动比例：0.00" in user_content
        assert all(field in user_content for field in ("engage", "probability", "reason", "confidence", "action"))
        assert not any(
            excluded in user_content
            for excluded in (
                "excluded-user-id",
                "excluded-interest-tag",
                "excluded-nickname",
                "excluded-ranking",
                "excluded-feedback",
                "excluded-post-id",
                "excluded-topic-tag",
                "excluded-media-summary",
                "excluded-platform",
            )
        )


def test_provider_request_options_are_typed_explicit_and_historically_omitted() -> None:
    historical_config = ProviderLLMConfig()
    historical_metadata = historical_config.safe_metadata()
    historical_dump = historical_config.model_dump(mode="json")
    explicit_config = ProviderLLMConfig(
        reasoning_effort=ReasoningEffort.LOW,
        max_output_tokens=256,
    )
    explicit_metadata = explicit_config.safe_metadata()
    explicit_dump = explicit_config.model_dump(mode="json")
    assert "reasoning_effort" not in historical_metadata
    assert "max_output_tokens" not in historical_metadata
    assert "reasoning_effort" not in historical_dump
    assert "max_output_tokens" not in historical_dump
    assert explicit_metadata["reasoning_effort"] == "low"
    assert explicit_metadata["max_output_tokens"] == 256
    assert explicit_dump["reasoning_effort"] == "low"
    assert explicit_dump["max_output_tokens"] == 256
    with pytest.raises(ValidationError):
        ProviderLLMConfig(reasoning_effort=cast(Any, "untyped"))
    with pytest.raises(ValidationError, match="Responses"):
        ProviderLLMConfig(wire_api="chat", reasoning_effort=ReasoningEffort.LOW)


def test_robustness_request_contract_fails_before_any_provider_call_when_incomplete() -> None:
    class NeverCalledClient:
        calls = 0

        def create_response(self, messages: list[dict[str, str]], model: str) -> str:
            del messages, model
            self.calls += 1
            raise AssertionError("invalid robustness contract must fail before a request")

    client = NeverCalledClient()
    token = CONCURRENT_ROBUSTNESS_PROMPT_TOKENS[1]

    with pytest.raises(ValueError, match="reasoning_effort=low"):
        OpenAICompatibleDecisionAdapter(
            ProviderLLMConfig(prompt_version=token, max_output_tokens=256),
            client=client,
        )
    with pytest.raises(ValueError, match="output-token ceiling"):
        OpenAICompatibleDecisionAdapter(
            ProviderLLMConfig(prompt_version=token, reasoning_effort=ReasoningEffort.LOW),
            client=client,
        )

    assert client.calls == 0


def test_explicit_low_responses_request_contract_freezes_prompt_schema_and_limits() -> None:
    token = CONCURRENT_ROBUSTNESS_PROMPT_TOKENS[1]
    adapter = OpenAICompatibleDecisionAdapter(
        ProviderLLMConfig(
            enabled=True,
            model="requested-model",
            wire_api="responses",
            prompt_version=token,
            reasoning_effort=ReasoningEffort.LOW,
            max_output_tokens=256,
            timeout_seconds=12.5,
            max_retries=2,
            retry_backoff_seconds=0.25,
        )
    )

    contract = adapter.request_contract
    validate_robustness_request_contract(contract)

    assert contract.schema_version == "provider-request-contract-v1"
    assert contract.requested_model == "requested-model"
    assert contract.prompt_version == token
    assert contract.prompt_canonical_hash == CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.resolve(token).canonical_hash
    assert contract.wire_api == "responses"
    assert contract.reasoning_effort == "low"
    assert contract.output_token_ceiling == 256
    assert contract.timeout_seconds == 12.5
    assert contract.max_retries == 2
    assert contract.retry_backoff_seconds == 0.25
    assert contract.structured_output_schema_version == "engage-decision-output-v1"
    assert (
        contract.structured_output_schema_hash
        == "sha256:baa4b5ac3950d8834bd296b184b8544c707633d5e668e1ee23cb8570e0e46654"
    )
    assert contract.omitted_parameters == ("temperature", "top_p", "seed")


def test_explicit_low_reaches_responses_wire_without_sampling_parameters() -> None:
    captured: dict[str, object] = {}

    def create_response(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(
            output_text=(
                '{"engage": true, "probability": 0.8, "reason": "fit", '
                '"confidence": 0.9, "action": "like"}'
            ),
            model="observed-model",
            usage=SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15),
        )

    client = object.__new__(_OpenAISDKClient)
    client._wire_api = "responses"
    client._extra_headers = None
    client._client = cast(Any, SimpleNamespace(responses=SimpleNamespace(create=create_response)))
    profile = UserProfile.model_validate(
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
    )
    adapter = OpenAICompatibleDecisionAdapter(
        ProviderLLMConfig(
            enabled=True,
            model="requested-model",
            prompt_version=CONCURRENT_ROBUSTNESS_PROMPT_TOKENS[2],
            reasoning_effort=ReasoningEffort.LOW,
            max_output_tokens=256,
        ),
        client=client,
    )

    decision = adapter.decide(
        post=PostContent(post_id="message-1", text="绿色酒店营销内容"),
        profile=profile,
        peer_context=PeerContext(),
    )

    assert decision.action == "like"
    assert captured["model"] == "requested-model"
    assert captured["reasoning"] == {"effort": "low"}
    assert captured["max_output_tokens"] == 256
    assert set(captured).isdisjoint({"temperature", "top_p", "seed"})
    assert captured["text"] == {"format": engage_decision_json_schema()}


def test_safe_request_accounting_separates_requested_and_observed_model_identity() -> None:
    class ContractAwareClient:
        def create_response(
            self,
            messages: list[dict[str, str]],
            model: str,
            **request_options: object,
        ) -> ProviderResponseEnvelope:
            del messages, model, request_options
            return ProviderResponseEnvelope(
                decision_text=(
                    '{"engage": false, "probability": 0.2, "reason": "low fit", '
                    '"confidence": 0.8, "action": "ignore"}'
                ),
                observed_model="observed-model-snapshot",
                observed_model_status="reported",
                usage_status="complete",
                input_tokens=11,
                output_tokens=5,
                total_tokens=16,
                cached_input_tokens=None,
            )

    token = CONCURRENT_ROBUSTNESS_PROMPT_TOKENS[3]
    adapter = OpenAICompatibleDecisionAdapter(
        ProviderLLMConfig(
            enabled=True,
            model="requested-model-alias",
            prompt_version=token,
            reasoning_effort=ReasoningEffort.LOW,
            max_output_tokens=256,
        ),
        client=ContractAwareClient(),
    )
    profile = UserProfile.model_validate(
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
    )

    decision = adapter.decide(
        post=PostContent(post_id="message-1", text="must-not-persist-as-request-evidence"),
        profile=profile,
        peer_context=PeerContext(),
    )
    metadata = decision.provider_metadata
    accounting = adapter.provider_request_accounting

    assert metadata is not None
    assert metadata["requested_model"] == "requested-model-alias"
    assert metadata["request_contract"] == adapter.request_contract.audit_record()
    assert accounting.requested_model == "requested-model-alias"
    assert accounting.request_contract == adapter.request_contract
    assert accounting.response_accounting.observed_model_counts == {"observed-model-snapshot": 1}
    assert accounting.response_accounting.successful_decision_count == 1
    allowlisted_metadata = allowlisted_provider_evidence(metadata)
    assert allowlisted_metadata["requested_model"] == "requested-model-alias"
    assert allowlisted_metadata["request_contract"] == adapter.request_contract.audit_record()
    serialized = json.dumps(
        {"metadata": metadata, "accounting": accounting.audit_record()},
        ensure_ascii=False,
        sort_keys=True,
    )
    assert "must-not-persist-as-request-evidence" not in serialized
    assert not any(
        unsafe in serialized
        for unsafe in ("credential", "raw_prompt", "raw_request", "raw_response", "request_payload")
    )

    historical_metadata = OpenAICompatibleDecisionAdapter(ProviderLLMConfig(enabled=True)).safe_metadata
    assert "requested_model" not in historical_metadata
    assert "request_contract" not in historical_metadata
