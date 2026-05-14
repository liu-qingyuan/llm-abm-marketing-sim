from llm_abm_sim.agent import SocialUserAgent
from llm_abm_sim.decision import EngageDecision, LLMDecisionAdapter
from llm_abm_sim.schemas import PeerContext, PostContent, UserProfile


class SequenceAdapter(LLMDecisionAdapter):
    def __init__(self):
        self.decisions = [True, False]

    def decide(
        self,
        post: PostContent,
        profile: UserProfile,
        peer_context: PeerContext,
        platform_context=None,
        time_step: int = 0,
    ) -> EngageDecision:
        return EngageDecision(engage=self.decisions.pop(0), probability=1.0 if self.decisions else 0.0)


def test_agent_engagement_is_absorbing():
    agent = SocialUserAgent(UserProfile(user_id="u1"), exposed=True)
    adapter = SequenceAdapter()
    post = PostContent(post_id="p1", text="hello")
    peer = PeerContext()

    first = agent.step(post, peer, adapter)
    second = agent.step(post, peer, adapter)

    assert first is not None
    assert first.engage is True
    assert second is None
    assert agent.engaged is True
    assert len(agent.decisions) == 1
