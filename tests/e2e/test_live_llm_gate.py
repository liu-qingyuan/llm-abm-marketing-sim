import pytest

from llm_abm_sim.final_research_decision_evidence import _FinalResearchDecisionEvidenceBuilder
from llm_abm_sim.provider_config import load_codex_provider_config, should_run_live_llm
from llm_abm_sim.providers.openai_compatible import OpenAICompatibleDecisionAdapter
from llm_abm_sim.schemas import (
    FailClosedAction,
    PeerContext,
    PlatformContext,
    PostContent,
    ProviderLLMConfig,
    UserProfile,
)


@pytest.mark.live_llm
def test_manual_live_llm_gate_makes_one_decision_only_when_explicitly_ready():
    if not should_run_live_llm():
        pytest.skip(
            "live LLM gate requires LLM_ABM_RUN_LIVE_LLM=1 plus API key, scoped Codex auth, or selected-provider headers"
        )

    config = load_codex_provider_config()
    adapter = OpenAICompatibleDecisionAdapter(
        ProviderLLMConfig(
            enabled=True,
            use_codex_provider_config=config is not None,
            fail_closed_action=FailClosedAction.RAISE,
        )
    )
    evidence_builder = _FinalResearchDecisionEvidenceBuilder(adapter)
    decision = adapter.decide(
        post=PostContent(post_id="live-smoke", text="Tiny eco skincare launch", topic_tags=["eco", "skincare"]),
        profile=UserProfile(user_id="live-user", interest_tags=["skincare"]),
        peer_context=PeerContext(engaged_neighbors=1, exposed_neighbors=2),
        platform_context=PlatformContext(hot_topics=["eco"], platform_mood="manual smoke"),
        time_step=0,
    )
    assert decision.decision_source == "provider"
    assert decision.provider_metadata is not None
    assert adapter.live_api_triggered is True
    assert 0.0 <= decision.probability <= 1.0
    assert 0.0 <= decision.confidence <= 1.0
    assert decision.action in {"ignore", "like", "comment", "share"}

    evidence = evidence_builder.build(
        sample_users=1,
        decision_rows=[
            {
                "schedule_position": 0,
                "user_id": "live-user",
                "video_id": "live-smoke",
                "time_step": 0,
                "engage": decision.engage,
                "action": decision.action,
                "decision_source": decision.decision_source,
            }
        ],
        action_rows=[
            {
                "schedule_position": 0,
                "user_id": "live-user",
                "video_id": "live-smoke",
                "time_step": 0,
                "action": decision.action,
            }
        ],
        outcome_rows=[
            {
                "user_id": "live-user",
                "result_status": decision.action,
                "provider_status": "succeeded",
            }
        ],
        provider_failure_rows=[],
    )
    assert evidence.decision_execution_mode == "live_provider"
    assert evidence.live_api_triggered is True
    assert evidence.formal_research_evidence is True
    assert evidence.sampling_status == "persisted_seed_first_formal_run"
