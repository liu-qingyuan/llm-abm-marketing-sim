from __future__ import annotations

from abc import ABC, abstractmethod
from pydantic import BaseModel, Field

from .schemas import PeerContext, PostContent, UserProfile


class EngageDecision(BaseModel):
    """Structured binary decision for one agent at one time step."""

    engage: bool
    probability: float = Field(ge=0.0, le=1.0)
    reason: str = ""
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class LLMDecisionAdapter(ABC):
    """Boundary for LLM-supported reasoning.

    The simulator should depend on this interface, not on LangChain, GenericAgent,
    or a provider-specific SDK. This keeps the ABM loop reproducible and lets us
    cache or replace LLM decisions independently.
    """

    @abstractmethod
    def decide(
        self,
        post: PostContent,
        profile: UserProfile,
        peer_context: PeerContext,
    ) -> EngageDecision:
        """Return engage / not engage using post, preference, and peer influence."""


class RuleBasedDecisionAdapter(LLMDecisionAdapter):
    """Deterministic baseline before adding real LLM calls."""

    def decide(
        self,
        post: PostContent,
        profile: UserProfile,
        peer_context: PeerContext,
    ) -> EngageDecision:
        topic_overlap = len(set(post.topic_tags) & set(profile.interest_tags))
        preference_score = min(topic_overlap / max(len(post.topic_tags), 1), 1.0)
        score = (
            0.45 * preference_score
            + 0.30 * max(profile.brand_attitude, 0.0)
            + 0.15 * peer_context.engagement_ratio
            + 0.10 * profile.activity_level
        )
        return EngageDecision(
            engage=score >= 0.5,
            probability=round(score, 4),
            reason="weighted baseline over post content, preference, and peer influence",
            confidence=1.0,
        )
