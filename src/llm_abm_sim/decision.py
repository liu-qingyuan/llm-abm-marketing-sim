from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .schemas import (
    LATENT_VALUE_DIMENSIONS,
    LEGACY_DEMO_PRESET_FIELDS,
    PeerContext,
    PlatformContext,
    PostContent,
    RuleBasedDecisionConfig,
    UserProfile,
)

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

    @model_validator(mode="after")
    def _validate_engage_action_consistency(self) -> EngageDecision:
        if not self.engage and self.action != "ignore":
            raise ValueError("engage=false requires action=ignore")
        if self.engage and self.action == "ignore":
            raise ValueError("engage=true requires action to be like, comment, or share")
        return self


class ProviderDecisionError(RuntimeError):
    """Raised when provider attempts are exhausted at the decision seam."""

    def __init__(self, cause: Exception) -> None:
        self.failure_type = cause.__class__.__name__
        super().__init__(f"provider decision retries exhausted: {self.failure_type}")


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
        payload["profile"] = decision_profile_payload(self.profile)
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


def decision_profile_payload(profile: UserProfile) -> dict[str, Any]:
    """Return profile fields that are allowed to affect decisions and provider prompts."""

    return {
        key: value for key, value in profile.model_dump(mode="json").items() if key not in LEGACY_DEMO_PRESET_FIELDS
    }


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

    def __init__(self, wrapped: LLMDecisionAdapter, cache: DecisionCache, prompt_version: str | None = None) -> None:
        self.wrapped = wrapped
        self.cache = cache
        self.prompt_version = prompt_version or str(getattr(wrapped, "prompt_version", "engage-v1"))

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

    def __init__(self, config: RuleBasedDecisionConfig | None = None) -> None:
        self.config = config or RuleBasedDecisionConfig()
        if self.config.latent_value_weight > 0.0:
            self.prompt_version = f"engage-v1-rule-latent-value-{self.config.latent_value_weight:g}"

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
            0.50 * preference_score
            + 0.20 * peer_context.engagement_ratio
            + 0.30 * profile.activity_score
            + platform_score
        )
        latent_value_score = _latent_value_score(post, profile)
        latent_applied = self.config.latent_value_weight > 0.0 and latent_value_score > 0.0
        if latent_applied:
            score += self.config.latent_value_weight * latent_value_score
        probability = round(min(score, 1.0), 4)
        action = _select_action(probability, peer_context)
        latent_reason = (
            f"latent value score applied ({latent_value_score:.4f})"
            if latent_applied
            else "latent value score not applied"
        )
        return EngageDecision(
            engage=action != "ignore",
            action=action,
            probability=probability,
            reason=(
                "weighted baseline over post content, preference, peer influence, and platform context; "
                f"{latent_reason}"
            ),
            confidence=1.0,
            provider_metadata={
                "latent_value_score_applied": latent_applied,
                "latent_value_score": round(latent_value_score, 4),
                "latent_value_weight": self.config.latent_value_weight,
            },
        )


def _latent_value_score(post: PostContent, profile: UserProfile) -> float:
    attributes = profile.latent_attributes
    if attributes is None:
        return 0.0
    raw_score = sum(
        getattr(attributes.value_weights, dimension) * getattr(post.value_dimensions, dimension)
        for dimension in LATENT_VALUE_DIMENSIONS
    )
    return min(max(raw_score, 0.0), 1.0)


def _select_action(probability: float, peer_context: PeerContext) -> EngagementAction:
    if probability < 0.5:
        return "ignore"
    if (
        peer_context.visible_shares > 0
        and peer_context.visible_shares >= peer_context.visible_comments
        and peer_context.visible_shares >= peer_context.visible_likes
    ):
        return "share"
    if (
        peer_context.visible_comments > 0
        and peer_context.visible_comments >= peer_context.visible_likes
        and peer_context.visible_comments >= peer_context.visible_shares
    ):
        return "comment"
    return "like"
