import pytest

from llm_abm_sim.provider_config import load_codex_provider_config, should_run_live_llm
from llm_abm_sim.providers.openai_compatible import OpenAICompatibleDecisionAdapter
from llm_abm_sim.schemas import PeerContext, PlatformContext, PostContent, ProviderLLMConfig, UserProfile


@pytest.mark.live_llm
def test_manual_live_llm_gate_makes_one_decision_only_when_explicitly_ready():
    if not should_run_live_llm():
        pytest.skip(
            "live LLM gate requires LLM_ABM_RUN_LIVE_LLM=1 plus OPENAI_API_KEY or ready Codex auth/provider config"
        )

    config = load_codex_provider_config()
    adapter = OpenAICompatibleDecisionAdapter(
        ProviderLLMConfig(enabled=True, use_codex_provider_config=config is not None, fail_closed_action="raise")
    )
    decision = adapter.decide(
        post=PostContent(post_id="live-smoke", text="Tiny eco skincare launch", topic_tags=["eco", "skincare"]),
        profile=UserProfile(user_id="live-user", interest_tags=["skincare"], brand_attitude=0.4),
        peer_context=PeerContext(engaged_neighbors=1, exposed_neighbors=2),
        platform_context=PlatformContext(hot_topics=["eco"], platform_mood="manual smoke"),
        time_step=0,
    )
    assert decision.decision_source == "provider"
    assert decision.provider_metadata is not None
    assert 0.0 <= decision.probability <= 1.0
    assert 0.0 <= decision.confidence <= 1.0
    assert decision.action in {"ignore", "like", "comment", "share"}
