from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .decision import EngageDecision
from .provider_config import redact_secrets
from .provider_evidence import allowlisted_provider_evidence
from .schemas import PeerContext, PlatformContext, PostContent, UserProfile


class DecisionInputSummary(BaseModel):
    """Safe, structured subset of one Agent decision input for report inspection."""

    time_step: int = Field(ge=0)
    prompt_version: str
    post: dict[str, Any]
    profile: dict[str, Any]
    peer_context: dict[str, Any]
    platform_context: dict[str, Any]


class DecisionTraceSummary(BaseModel):
    """Safe Agent input/output packet attached to decision events and graph traces."""

    schema_version: str = "decision-trace-summary-v1"
    user_id: str
    input: DecisionInputSummary
    output: EngageDecision


def build_decision_trace_summary(
    *,
    user_id: str,
    post: PostContent,
    profile: UserProfile,
    peer_context: PeerContext,
    platform_context: PlatformContext,
    time_step: int,
    decision: EngageDecision,
    prompt_version: str,
) -> DecisionTraceSummary:
    return DecisionTraceSummary(
        user_id=user_id,
        input=DecisionInputSummary(
            time_step=time_step,
            prompt_version=prompt_version,
            post=redact_secrets(
                {
                    "post_id": post.post_id,
                    "text": post.text,
                    "topic_tags": post.topic_tags,
                    "media_summary": post.media_summary,
                }
            ),
            profile=redact_secrets(profile.model_dump(mode="json")),
            peer_context=redact_secrets(
                {
                    **peer_context.model_dump(mode="json"),
                    "engagement_ratio": round(peer_context.engagement_ratio, 4),
                }
            ),
            platform_context=redact_secrets(platform_context.model_dump(mode="json")),
        ),
        output=decision.model_copy(
            update={"provider_metadata": allowlisted_provider_evidence(decision.provider_metadata)}
        ),
    )
