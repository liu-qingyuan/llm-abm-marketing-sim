from __future__ import annotations

from dataclasses import dataclass, field

from .decision import EngageDecision, LLMDecisionAdapter
from .schemas import PeerContext, PostContent, UserProfile


@dataclass
class SocialUserAgent:
    """One social-network user in the ABM simulation."""

    profile: UserProfile
    exposed: bool = False
    engaged: bool = False
    decisions: list[EngageDecision] = field(default_factory=list)

    @property
    def user_id(self) -> str:
        return self.profile.user_id

    def step(
        self,
        post: PostContent,
        peer_context: PeerContext,
        decision_adapter: LLMDecisionAdapter,
    ) -> EngageDecision | None:
        if not self.exposed:
            return None
        decision = decision_adapter.decide(post, self.profile, peer_context)
        self.engaged = decision.engage
        self.decisions.append(decision)
        return decision
