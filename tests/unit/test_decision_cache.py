from llm_abm_sim.decision import CachedDecisionAdapter, EngageDecision, InMemoryDecisionCache, LLMDecisionAdapter
from llm_abm_sim.schemas import PeerContext, PlatformContext, PostContent, UserProfile


class CountingAdapter(LLMDecisionAdapter):
    def __init__(self):
        self.calls = 0

    def decide(self, post, profile, peer_context, platform_context=None, time_step=0):
        self.calls += 1
        return EngageDecision(engage=True, action="like", probability=0.8, reason="test")


def test_cached_decision_adapter_reuses_identical_decision_input():
    wrapped = CountingAdapter()
    adapter = CachedDecisionAdapter(wrapped, InMemoryDecisionCache())
    post = PostContent(post_id="p1", text="eco skincare", topic_tags=["eco"])
    profile = UserProfile(user_id="u1", interest_tags=["eco"])
    peer = PeerContext(exposed_neighbors=1, engaged_neighbors=1)
    platform = PlatformContext(hot_topics=["eco"])

    first = adapter.decide(post, profile, peer, platform, time_step=1)
    second = adapter.decide(post, profile, peer, platform, time_step=1)

    assert first == second
    assert wrapped.calls == 1


def test_cache_key_changes_with_time_step():
    wrapped = CountingAdapter()
    adapter = CachedDecisionAdapter(wrapped, InMemoryDecisionCache())
    post = PostContent(post_id="p1", text="eco skincare")
    profile = UserProfile(user_id="u1")
    peer = PeerContext()

    adapter.decide(post, profile, peer, time_step=1)
    adapter.decide(post, profile, peer, time_step=2)

    assert wrapped.calls == 2


def test_cache_key_ignores_legacy_demo_presets():
    wrapped = CountingAdapter()
    adapter = CachedDecisionAdapter(wrapped, InMemoryDecisionCache())
    post = PostContent(post_id="p1", text="eco skincare", topic_tags=["eco"])
    peer = PeerContext()

    adapter.decide(
        post,
        UserProfile(user_id="u1", interest_tags=["eco"], brand_attitude=1.0, like_tendency=1.0),
        peer,
        time_step=1,
    )
    adapter.decide(
        post,
        UserProfile(user_id="u1", interest_tags=["eco"], brand_attitude=-1.0, share_tendency=0.0),
        peer,
        time_step=1,
    )

    assert wrapped.calls == 1
