from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

from .schemas import PeerContext, PlatformContext, PostContent, UserProfile

EngagementAction = Literal["ignore", "like", "comment", "share"]


class EngageDecision(BaseModel):
    """Structured decision for one agent at one time step."""

    engage: bool
    probability: float = Field(ge=0.0, le=1.0)
    reason: str = ""
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    action: EngagementAction = "ignore"
    decision_source: str = "rule_based"
    provider_metadata: dict[str, Any] | None = None


class DecisionInput(BaseModel):
    """Stable decision boundary for cache keys and future LLM prompts."""

    post: PostContent
    profile: UserProfile
    peer_context: PeerContext
    platform_context: PlatformContext = Field(default_factory=PlatformContext)
    time_step: int = Field(ge=0)
    prompt_version: str = "engage-v1"

    def cache_key(self) -> str:
        payload = self.model_dump(mode="json")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class DecisionCache(ABC):
    """Cache boundary for deterministic replay and lower provider cost."""

    @abstractmethod
    def get(self, decision_input: DecisionInput) -> EngageDecision | None:
        """Return a cached decision when available."""

    @abstractmethod
    def set(self, decision_input: DecisionInput, decision: EngageDecision) -> None:
        """Store a decision for an input."""


@dataclass
class InMemoryDecisionCache(DecisionCache):
    """Simple process-local cache for tests and offline runs."""

    decisions: dict[str, EngageDecision] = field(default_factory=dict)

    def get(self, decision_input: DecisionInput) -> EngageDecision | None:
        return self.decisions.get(decision_input.cache_key())

    def set(self, decision_input: DecisionInput, decision: EngageDecision) -> None:
        self.decisions[decision_input.cache_key()] = decision


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
        platform_context: PlatformContext | None = None,
        time_step: int = 0,
    ) -> EngageDecision:
        """Return an action decision using content, preference, peer influence, and context."""


class CachedDecisionAdapter(LLMDecisionAdapter):
    """LLMDecisionAdapter wrapper with stable DecisionInput cache keys."""

    def __init__(self, wrapped: LLMDecisionAdapter, cache: DecisionCache, prompt_version: str = "engage-v1") -> None:
        self.wrapped = wrapped
        self.cache = cache
        self.prompt_version = prompt_version

    def decide(
        self,
        post: PostContent,
        profile: UserProfile,
        peer_context: PeerContext,
        platform_context: PlatformContext | None = None,
        time_step: int = 0,
    ) -> EngageDecision:
        decision_input = DecisionInput(
            post=post,
            profile=profile,
            peer_context=peer_context,
            platform_context=platform_context or PlatformContext(),
            time_step=time_step,
            prompt_version=self.prompt_version,
        )
        cached = self.cache.get(decision_input)
        if cached is not None:
            return cached
        decision = self.wrapped.decide(post, profile, peer_context, platform_context, time_step)
        self.cache.set(decision_input, decision)
        return decision


class RuleBasedDecisionAdapter(LLMDecisionAdapter):
    """Deterministic baseline before adding real LLM calls."""

    prompt_version = "engage-v1"

    def decide(
        self,
        post: PostContent,
        profile: UserProfile,
        peer_context: PeerContext,
        platform_context: PlatformContext | None = None,
        time_step: int = 0,
    ) -> EngageDecision:
        context = platform_context or PlatformContext()
        topic_overlap = len(set(post.topic_tags) & set(profile.interest_tags))
        hot_topic_overlap = len(set(post.topic_tags) & set(context.hot_topics))
        preference_score = min(topic_overlap / max(len(post.topic_tags), 1), 1.0)
        platform_score = min(0.15 * hot_topic_overlap * context.feed_ranking_weight, 0.2)
        score = (
            0.40 * preference_score
            + 0.25 * max(profile.brand_attitude, 0.0)
            + 0.15 * peer_context.engagement_ratio
            + 0.10 * profile.activity_level
            + platform_score
        )
        probability = round(min(score, 1.0), 4)
        action = _select_action(probability, profile, peer_context)
        return EngageDecision(
            engage=action != "ignore",
            action=action,
            probability=probability,
            reason="weighted baseline over post content, preference, peer influence, and platform context",
            confidence=1.0,
        )


def _select_action(probability: float, profile: UserProfile, peer_context: PeerContext) -> EngagementAction:
    if probability < 0.5:
        return "ignore"
    share_score = probability * profile.share_tendency + 0.05 * peer_context.visible_shares
    comment_score = probability * profile.comment_tendency + 0.03 * peer_context.visible_comments
    like_score = probability * profile.like_tendency + 0.01 * peer_context.visible_likes
    scored: list[tuple[float, EngagementAction]] = [
        (share_score, "share"),
        (comment_score, "comment"),
        (like_score, "like"),
    ]
    return max(scored, key=lambda item: (item[0], {"like": 0, "comment": 1, "share": 2}[item[1]]))[1]
