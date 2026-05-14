from llm_abm_sim.decision import RuleBasedDecisionAdapter
from llm_abm_sim.schemas import PeerContext, PostContent, UserProfile


def test_rule_based_decision_returns_binary_schema():
    adapter = RuleBasedDecisionAdapter()
    decision = adapter.decide(
        PostContent(post_id="p1", text="new skincare post", topic_tags=["skincare"]),
        UserProfile(user_id="u1", interest_tags=["skincare"], brand_attitude=0.5, activity_level=0.8),
        PeerContext(engaged_neighbors=3, exposed_neighbors=4),
    )
    assert isinstance(decision.engage, bool)
    assert 0.0 <= decision.probability <= 1.0
