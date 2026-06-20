from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TIKHUB_OPENAPI_VERSION = "V5.3.2"
TIKHUB_OPENAPI_UPDATED = "2026-06-07"

VIDEO_COLUMNS = [
    "video_id",
    "source_challenge_id",
    "source_challenge_name",
    "source_challenge_rank",
    "raw_detail_status",
    "metadata_source",
    "video_url",
    "publish_time",
    "caption",
    "hashtags",
    "creator_user_id",
    "like_count",
    "comment_count",
    "share_count",
    "collect_count",
]
COMMENT_COLUMNS = [
    "comment_id",
    "video_id",
    "parent_comment_id",
    "commenter_user_id",
    "content",
    "publish_time",
    "mentioned_user_ids",
    "like_count",
    "comment_level",
]
USER_COLUMNS = [
    "user_id",
    "sec_user_id",
    "nickname",
    "follower_count",
    "following_count",
    "video_count",
    "verified_type",
    "bio",
    "observed_activity_level",
    "observed_influence",
]
EDGE_COLUMNS = [
    "source",
    "target",
    "weight",
    "comment_count",
    "reply_count",
    "mention_count",
    "first_interaction_time",
    "last_interaction_time",
]

TEXT_ITEM_COLUMNS = [
    "item_id",
    "item_type",
    "video_id",
    "parent_comment_id",
    "user_id",
    "target_user_id",
    "text",
    "publish_time",
    "like_count",
    "source",
]

PROFILE_COLUMNS = [
    "user_id",
    "user_type",
    "follower_count",
    "observed_activity_level",
    "observed_influence",
    "value_proposition",
    "interest_tags",
    "brand_attitude",
    "activity_level",
    "like_tendency",
    "comment_tendency",
    "share_tendency",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class DouyinVideoRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    video_id: str
    source_challenge_id: str = ""
    source_challenge_name: str = ""
    source_challenge_rank: int = Field(default=0, ge=0)
    raw_detail_status: str = "unknown"
    metadata_source: str = ""
    video_url: str = ""
    publish_time: str = ""
    caption: str = ""
    hashtags: list[str] = Field(default_factory=list)
    creator_user_id: str = ""
    like_count: int = Field(default=0, ge=0)
    comment_count: int = Field(default=0, ge=0)
    share_count: int = Field(default=0, ge=0)
    collect_count: int = Field(default=0, ge=0)


class DouyinCommentRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    comment_id: str
    video_id: str
    parent_comment_id: str = ""
    commenter_user_id: str
    content: str = ""
    publish_time: str = ""
    mentioned_user_ids: list[str] = Field(default_factory=list)
    like_count: int = Field(default=0, ge=0)
    comment_level: Literal["comment", "reply"] = "comment"

    @model_validator(mode="after")
    def _reply_has_parent(self) -> DouyinCommentRecord:
        if self.comment_level == "reply" and not self.parent_comment_id:
            raise ValueError("reply comments require parent_comment_id")
        return self


class DouyinUserRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    user_id: str
    sec_user_id: str = ""
    nickname: str = ""
    follower_count: int = Field(default=0, ge=0)
    following_count: int = Field(default=0, ge=0)
    video_count: int = Field(default=0, ge=0)
    verified_type: str = ""
    bio: str = ""
    observed_activity_level: float = Field(default=0.5, ge=0.0, le=1.0)
    observed_influence: float = Field(default=0.0, ge=0.0, le=1.0)


class DouyinEdgeRecord(BaseModel):
    source: str
    target: str
    weight: int = Field(default=0, ge=0)
    comment_count: int = Field(default=0, ge=0)
    reply_count: int = Field(default=0, ge=0)
    mention_count: int = Field(default=0, ge=0)
    first_interaction_time: str = ""
    last_interaction_time: str = ""

    @model_validator(mode="after")
    def _weight_matches_counts(self) -> DouyinEdgeRecord:
        expected = self.comment_count + self.reply_count + self.mention_count
        if self.weight == 0 and expected:
            self.weight = expected
        if self.weight != expected:
            raise ValueError("weight must equal comment_count + reply_count + mention_count")
        return self


class DouyinProfileRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    user_id: str
    user_type: str = "observed"
    follower_count: int = Field(default=0, ge=0)
    observed_activity_level: float = Field(default=0.5, ge=0.0, le=1.0)
    observed_influence: float = Field(default=0.0, ge=0.0, le=1.0)
    value_proposition: str = ""
    interest_tags: list[str] = Field(default_factory=list)
    brand_attitude: float = Field(default=0.0, ge=-1.0, le=1.0)
    activity_level: float = Field(default=0.5, ge=0.0, le=1.0)
    like_tendency: float = Field(default=0.5, ge=0.0, le=1.0)
    comment_tendency: float = Field(default=0.2, ge=0.0, le=1.0)
    share_tendency: float = Field(default=0.2, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _activity_level_follows_observed(self) -> DouyinProfileRecord:
        self.activity_level = self.observed_activity_level
        return self


class FieldProvenance(BaseModel):
    observed: list[str] = Field(default_factory=list)
    derived: list[str] = Field(default_factory=list)
    defaulted: list[str] = Field(default_factory=list)


class DouyinCollectionReport(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str
    mode: Literal["mock", "live"] = "mock"
    created_at: str = Field(default_factory=_now_iso)
    counts: dict[str, int] = Field(default_factory=dict)
    limits: dict[str, int | None] = Field(default_factory=dict)
    limit_profile: Literal["capped", "unbounded"] = "capped"
    selection_metadata: dict[str, Any] = Field(default_factory=dict)
    endpoint_call_counts: dict[str, int] = Field(default_factory=dict)
    missing_fields: dict[str, list[str]] = Field(default_factory=dict)
    failed_pages: list[dict[str, Any]] = Field(default_factory=list)
    skipped_users: list[str] = Field(default_factory=list)
    dedupe_counts: dict[str, int] = Field(default_factory=dict)
    stage_counts: dict[str, int] = Field(default_factory=dict)
    stage_status: dict[str, str] = Field(default_factory=dict)
    comments_collected: bool = True
    profiles_collected: bool = True
    video_source_mode: str = "detail_only"
    live_fetch: bool = False
    redacted_config: dict[str, Any] = Field(default_factory=dict)
    tikhub_openapi_version: str = TIKHUB_OPENAPI_VERSION
    tikhub_openapi_updated: str = TIKHUB_OPENAPI_UPDATED
    field_provenance: dict[str, FieldProvenance] = Field(default_factory=dict)

    @field_validator("redacted_config")
    @classmethod
    def _no_secret_looking_values(cls, value: dict[str, Any]) -> dict[str, Any]:
        text = repr(value).lower()
        if "authorization" in text or "bearer " in text:
            raise ValueError("redacted_config must not contain authorization material")
        return value
