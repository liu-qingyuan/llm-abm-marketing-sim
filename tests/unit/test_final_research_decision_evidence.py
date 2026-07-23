from __future__ import annotations

from typing import cast

import pytest
from pydantic import ValidationError

from llm_abm_sim.decision import (
    CachedDecisionAdapter,
    EngageDecision,
    InMemoryDecisionCache,
    LLMDecisionAdapter,
    RuleBasedDecisionAdapter,
)
from llm_abm_sim.final_research_decision_evidence import (
    DecisionExecutionEvidence,
    DecisionExecutionEvidenceV2,
    _FinalResearchDecisionEvidenceBuilder,
)
from llm_abm_sim.final_research_report import RankingV5ExpandEvidence, ranking_v5_release_evidence
from llm_abm_sim.providers.openai_compatible import OpenAICompatibleDecisionAdapter, ProviderResponseEnvelope
from llm_abm_sim.safe_serialization import safe_data
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


def test_ranking_v5_release_evidence_promotes_only_actual_live_execution():
    validation_evidence = _FinalResearchDecisionEvidenceBuilder(RuleBasedDecisionAdapter()).build(
        sample_users=0,
        decision_rows=[],
        action_rows=[],
        outcome_rows=[],
        provider_failure_rows=[],
    )
    validation_state = ranking_v5_release_evidence(validation_evidence)

    assert validation_state["schema_version"] == "ranking-v5-expand-evidence-v1"
    assert validation_state["contract_stage"] == "validation_expand"
    assert validation_state["production_deploy_eligible"] is False

    formal_evidence = DecisionExecutionEvidence.model_validate(
        {
            **validation_evidence.model_dump(mode="json"),
            "formal_research_evidence": True,
            "decision_execution_mode": "live_provider",
            "adapter_chain": ["openai_compatible"],
            "provider_metadata": {
                "adapter": "openai_compatible",
                "model": "authorized-model",
                "prompt_version": "jinjiang-green-marketing-prompt-v3",
            },
            "live_api_triggered": True,
            "sampling_status": "persisted_seed_first_formal_run",
        }
    )

    historical_expand_state = {
        **validation_state,
        "decision_execution_evidence": formal_evidence.model_dump(mode="json"),
    }
    assert RankingV5ExpandEvidence.model_validate(historical_expand_state).production_deploy_eligible is False

    formal_state = ranking_v5_release_evidence(formal_evidence)

    assert formal_state["schema_version"] == "ranking-v5-formal-evidence-v1"
    assert formal_state["contract_stage"] == "formal_release"
    formal_target_evidence = cast(dict[str, object], formal_state["target_aggregate_engagement_reference"])
    assert formal_target_evidence["status"] == "persisted"
    assert formal_state["decision_execution_evidence"] == formal_evidence.model_dump(mode="json")
    assert formal_state["production_deploy_eligible"] is True


def test_v2_bare_provider_rejects_runtime_decisions_without_leaf_success_accounting():
    provider = OpenAICompatibleDecisionAdapter(
        ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False),
        client=_UnusedProviderClient(),
    )
    decision = {**_decision_row("u1", "like"), "decision_source": "provider"}

    with pytest.raises(ValidationError, match="bare Provider accounting must cover every persisted runtime Decision"):
        _FinalResearchDecisionEvidenceBuilder(provider).build_v2(
            sample_users=1,
            decision_rows=[decision],
            action_rows=[_action_row("u1", "like")],
            outcome_rows=[{"user_id": "u1", "result_status": "like", "provider_status": "succeeded"}],
            provider_failure_rows=[],
        )


def test_v2_decision_evidence_uses_run_local_provider_accounting_delta():
    response = ProviderResponseEnvelope(
        decision_text=(
            '{"engage": true, "probability": 0.7, "reason": "fit", '
            '"confidence": 0.8, "action": "like"}'
        ),
        observed_model="observed-model",
        observed_model_status="reported",
        usage_status="complete",
        input_tokens=9,
        output_tokens=3,
        total_tokens=12,
        cached_input_tokens=None,
    )

    class ReusableClient:
        def create_response(self, messages: list[dict[str, str]], model: str) -> ProviderResponseEnvelope:
            del messages, model
            return response

    provider = OpenAICompatibleDecisionAdapter(
        ProviderLLMConfig(enabled=True, model="requested-model", require_live_env=False),
        client=ReusableClient(),
    )
    context = {
        "post": PostContent(post_id="p1", text="target"),
        "profile": UserProfile(user_id="u1"),
        "peer_context": PeerContext(),
    }
    provider.decide(**context)
    builder = _FinalResearchDecisionEvidenceBuilder(provider)
    provider.decide(**context)
    decision = {**_decision_row("u1", "like"), "decision_source": "provider"}

    evidence = builder.build_v2(
        sample_users=1,
        decision_rows=[decision],
        action_rows=[_action_row("u1", "like")],
        outcome_rows=[{"user_id": "u1", "result_status": "like", "provider_status": "succeeded"}],
        provider_failure_rows=[],
    )

    assert isinstance(evidence, DecisionExecutionEvidenceV2)
    assert evidence.schema_version == "final-research-decision-execution-evidence-v2"
    assert evidence.provider_accounting.provider_response_count == 1
    assert evidence.provider_accounting.successful_decision_count == 1
    assert evidence.provider_accounting.observed_model_counts == {"observed-model": 1}
    assert evidence.provider_accounting.usage_complete_response_count == 1
    assert evidence.provider_accounting.input_tokens == 9
    assert evidence.provider_accounting.output_tokens == 3
    assert evidence.provider_accounting.total_tokens == 12
    assert evidence.provider_accounting.external_request_invocations == 0


def test_v2_provider_accounting_is_a_strict_safe_serialization_sibling():
    evidence = DecisionExecutionEvidenceV2.model_validate(
        {
            "schema_version": "final-research-decision-execution-evidence-v2",
            "status": "persisted",
            "formal_research_evidence": False,
            "decision_execution_mode": "mock_provider",
            "adapter_chain": ["openai_compatible"],
            "decision_source_counts": {"provider": 1},
            "action_counts": {"like": 1, "comment": 0, "share": 0, "ignore": 0},
            "terminal_counts": {
                "sample_users": 1,
                "exposed_users": 1,
                "decided_users": 1,
                "provider_failed": 0,
                "below_delivery_capacity": 0,
            },
            "provider_metadata": {"adapter": "openai_compatible", "model": "requested-model"},
            "provider_accounting": {
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
                "input_tokens": 9,
                "output_tokens": 3,
                "total_tokens": 12,
                "cached_input_tokens": None,
                "cached_input_tokens_reported_response_count": 0,
            },
            "live_api_triggered": False,
            "sampling_status": "validation_run",
            "degeneracy_flags": {
                "all_decisions_ignore": False,
                "single_action_only": True,
                "no_engagement_feedback": False,
            },
        }
    )

    serialized = safe_data(evidence)

    assert serialized["provider_accounting"]["input_tokens"] == 9
    assert serialized["provider_accounting"]["total_tokens"] == 12
    assert "provider_accounting" not in serialized["provider_metadata"]

    unsafe = evidence.model_dump(mode="json")
    unsafe["provider_accounting"]["raw_provider_response"] = "forbidden"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DecisionExecutionEvidenceV2.model_validate(unsafe)


def test_v2_rule_based_evidence_rejects_forged_provider_accounting():
    evidence = _FinalResearchDecisionEvidenceBuilder(RuleBasedDecisionAdapter()).build_v2(
        sample_users=0,
        decision_rows=[],
        action_rows=[],
        outcome_rows=[],
        provider_failure_rows=[],
    )
    forged = evidence.model_dump(mode="json")
    forged["provider_accounting"].update(
        {
            "provider_response_count": 1,
            "observed_model_missing_response_count": 1,
            "usage_missing_response_count": 1,
        }
    )

    with pytest.raises(ValidationError, match="rule-based Decision evidence cannot contain Provider accounting"):
        DecisionExecutionEvidenceV2.model_validate(forged)


def test_v2_cached_provider_hit_remains_a_runtime_decision_without_response_evidence():
    response = ProviderResponseEnvelope(
        decision_text=(
            '{"engage": true, "probability": 0.7, "reason": "cached", '
            '"confidence": 0.8, "action": "like"}'
        ),
        observed_model="observed-model",
        observed_model_status="reported",
        usage_status="complete",
        input_tokens=9,
        output_tokens=3,
        total_tokens=12,
        cached_input_tokens=None,
    )

    class OneResponseClient:
        def create_response(self, messages: list[dict[str, str]], model: str) -> ProviderResponseEnvelope:
            del messages, model
            return response

    provider = OpenAICompatibleDecisionAdapter(
        ProviderLLMConfig(enabled=True, model="requested-model", require_live_env=False),
        client=OneResponseClient(),
    )
    adapter = CachedDecisionAdapter(provider, InMemoryDecisionCache())
    context = {
        "post": PostContent(post_id="p1", text="target"),
        "profile": UserProfile(user_id="u1"),
        "peer_context": PeerContext(),
    }
    adapter.decide(**context)
    builder = _FinalResearchDecisionEvidenceBuilder(adapter)
    cached_decision = adapter.decide(**context)
    decision = {**_decision_row("u1", "like"), "decision_source": cached_decision.decision_source}

    evidence = builder.build_v2(
        sample_users=1,
        decision_rows=[decision],
        action_rows=[_action_row("u1", "like")],
        outcome_rows=[{"user_id": "u1", "result_status": "like", "provider_status": "succeeded"}],
        provider_failure_rows=[],
    )

    assert evidence.adapter_chain == ["cached", "openai_compatible"]
    assert evidence.decision_source_counts == {"provider": 1}
    assert evidence.provider_accounting.provider_response_count == 0
    assert evidence.provider_accounting.successful_decision_count == 0
    assert evidence.provider_accounting.observed_model_counts == {}
    assert evidence.provider_accounting.usage_complete_response_count == 0
    assert evidence.terminal_counts.decided_users - evidence.provider_accounting.successful_decision_count == 1


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
