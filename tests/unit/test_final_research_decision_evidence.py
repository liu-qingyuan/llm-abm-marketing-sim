from __future__ import annotations

import pytest
from pydantic import ValidationError

from llm_abm_sim.decision import (
    CachedDecisionAdapter,
    EngageDecision,
    InMemoryDecisionCache,
    LLMDecisionAdapter,
    RuleBasedDecisionAdapter,
)
from llm_abm_sim.final_research_decision_evidence import _FinalResearchDecisionEvidenceBuilder
from llm_abm_sim.providers.openai_compatible import OpenAICompatibleDecisionAdapter
from llm_abm_sim.schemas import PeerContext, PlatformContext, PostContent, ProviderLLMConfig, UserProfile


@pytest.mark.parametrize(
    ("adapter", "expected_chain"),
    [
        (RuleBasedDecisionAdapter(), ["rule_based"]),
        (
            CachedDecisionAdapter(RuleBasedDecisionAdapter(), InMemoryDecisionCache()),
            ["cached", "rule_based"],
        ),
    ],
)
def test_decision_evidence_classifies_registered_rule_based_chains(adapter, expected_chain):
    builder = _FinalResearchDecisionEvidenceBuilder(adapter)

    classification = builder.classification()

    assert classification.decision_execution_mode == "rule_based"
    assert classification.adapter_chain == expected_chain
    assert classification.live_api_triggered is False
    assert classification.provider_metadata == {
        "adapter": "rule_based",
        "prompt_version": "engage-v1",
    }


class _UnusedProviderClient:
    def create_response(self, messages: list[dict[str, str]], model: str) -> dict[str, object]:
        del messages, model
        raise AssertionError("classification must not call the provider")


@pytest.mark.parametrize("cached", [False, True])
def test_decision_evidence_classifies_injected_provider_as_mock(cached: bool):
    provider = OpenAICompatibleDecisionAdapter(
        ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False),
        client=_UnusedProviderClient(),
    )
    adapter = CachedDecisionAdapter(provider, InMemoryDecisionCache()) if cached else provider

    classification = _FinalResearchDecisionEvidenceBuilder(adapter).classification()

    assert classification.decision_execution_mode == "mock_provider"
    assert classification.adapter_chain == (["cached"] if cached else []) + ["openai_compatible"]
    assert classification.live_api_triggered is False
    assert classification.provider_metadata["adapter"] == "openai_compatible"
    assert classification.provider_metadata["model"] == "mock-model"


class _UnknownWrapper(LLMDecisionAdapter):
    def __init__(self, wrapped: LLMDecisionAdapter) -> None:
        self.wrapped = wrapped

    def decide(
        self,
        post: PostContent,
        profile: UserProfile,
        peer_context: PeerContext,
        platform_context: PlatformContext | None = None,
        time_step: int = 0,
    ) -> EngageDecision:
        return self.wrapped.decide(post, profile, peer_context, platform_context, time_step)


def test_decision_evidence_uses_run_local_request_delta_for_reused_cached_provider():
    provider = OpenAICompatibleDecisionAdapter(
        ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False),
        client=_UnusedProviderClient(),
    )
    provider.external_request_invocations = 3
    adapter = CachedDecisionAdapter(provider, InMemoryDecisionCache())

    classification = _FinalResearchDecisionEvidenceBuilder(adapter).classification()

    assert provider.live_api_triggered is True
    assert classification.decision_execution_mode == "mock_provider"
    assert classification.live_api_triggered is False


def test_decision_evidence_rejects_unregistered_wrapper():
    adapter = _UnknownWrapper(RuleBasedDecisionAdapter())

    with pytest.raises(ValueError, match="unsupported Final Research decision adapter"):
        _FinalResearchDecisionEvidenceBuilder(adapter).classification()


def test_decision_evidence_rejects_cached_wrapper_cycle():
    adapter = CachedDecisionAdapter(RuleBasedDecisionAdapter(), InMemoryDecisionCache())
    adapter.wrapped = adapter

    with pytest.raises(ValueError, match="wrapper chain contains a cycle"):
        _FinalResearchDecisionEvidenceBuilder(adapter).classification()


def _decision_row(user_id: str, action: str) -> dict[str, object]:
    return {
        "schedule_position": int(user_id[1:]) - 1,
        "user_id": user_id,
        "video_id": "target",
        "time_step": 0,
        "engage": "false" if action == "ignore" else "true",
        "action": action,
        "decision_source": "rule_based",
    }


def _action_row(user_id: str, action: str) -> dict[str, object]:
    return {
        "schedule_position": int(user_id[1:]) - 1,
        "user_id": user_id,
        "video_id": "target",
        "time_step": 0,
        "action": action,
    }


def test_decision_evidence_builds_counts_from_canonical_runtime_rows():
    decisions = [
        _decision_row("u1", "like"),
        _decision_row("u2", "comment"),
        _decision_row("u3", "share"),
        _decision_row("u4", "ignore"),
    ]
    actions = [
        _action_row("u1", "like"),
        _action_row("u2", "comment"),
        _action_row("u3", "share"),
        _action_row("u4", "ignore"),
    ]
    outcomes = [
        {"user_id": "u1", "result_status": "like", "provider_status": "succeeded"},
        {"user_id": "u2", "result_status": "comment", "provider_status": "succeeded"},
        {"user_id": "u3", "result_status": "share", "provider_status": "succeeded"},
        {"user_id": "u4", "result_status": "ignore", "provider_status": "succeeded"},
        {"user_id": "u5", "result_status": "provider_failed", "provider_status": "provider_failed"},
        {
            "user_id": "u6",
            "result_status": "below_delivery_capacity",
            "provider_status": "not_called",
        },
    ]
    failures = [{"user_id": "u5", "failure_type": "TimeoutError"}]

    evidence = _FinalResearchDecisionEvidenceBuilder(RuleBasedDecisionAdapter()).build(
        sample_users=6,
        decision_rows=decisions,
        action_rows=actions,
        outcome_rows=outcomes,
        provider_failure_rows=failures,
    )

    assert evidence.status == "persisted"
    assert evidence.formal_research_evidence is False
    assert evidence.decision_execution_mode == "rule_based"
    assert evidence.sampling_status == "validation_run"
    assert evidence.decision_source_counts == {"rule_based": 4}
    assert evidence.action_counts == {"like": 1, "comment": 1, "share": 1, "ignore": 1}
    assert evidence.terminal_counts.model_dump() == {
        "sample_users": 6,
        "exposed_users": 5,
        "decided_users": 4,
        "provider_failed": 1,
        "below_delivery_capacity": 1,
    }
    assert evidence.degeneracy_flags.model_dump() == {
        "all_decisions_ignore": False,
        "single_action_only": False,
        "no_engagement_feedback": False,
    }

    tampered = evidence.model_dump(mode="json")
    tampered["terminal_counts"]["decided_users"] -= 1
    with pytest.raises(ValidationError, match=r"exposed_users != decided_users \+ provider_failed"):
        type(evidence).model_validate(tampered)

    coerced = evidence.model_dump(mode="json")
    coerced["live_api_triggered"] = 0
    with pytest.raises(ValidationError, match="live_api_triggered"):
        type(evidence).model_validate(coerced)

    unsafe_metadata = evidence.model_dump(mode="json")
    unsafe_metadata["provider_metadata"]["raw_provider_response"] = "not allowed"
    with pytest.raises(ValidationError, match="allowlisted, redacted fields"):
        type(evidence).model_validate(unsafe_metadata)
