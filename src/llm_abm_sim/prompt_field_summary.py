from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Literal

from .decision import DecisionInput
from .prompt_contracts import (
    CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
    CONCURRENT_ROBUSTNESS_PROMPT_TOKENS,
)
from .schemas import LATENT_VALUE_DIMENSIONS, PeerContext, PlatformContext, PostContent, UserProfile

MAX_INTEREST_TAGS = 6
MAX_INTEREST_TAG_LENGTH = 24
MAX_TEXT_LENGTH = 240

JINJIANG_PROMPT_V3 = "jinjiang-green-marketing-prompt-v3"
LEGACY_PROVIDER_PROMPT_V1 = "engage-provider-v1"
LEGACY_DECISION_PROMPT_V1 = "engage-v1"
CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION = "jinjiang-concurrent-message-demographic-shadow-prompt-v1"
JINJIANG_PROMPT_V3_TOKENS = frozenset({JINJIANG_PROMPT_V3, LEGACY_PROVIDER_PROMPT_V1, LEGACY_DECISION_PROMPT_V1})
CONCURRENT_ROBUSTNESS_PRIMARY_PROMPT_TOKENS = frozenset(CONCURRENT_ROBUSTNESS_PROMPT_TOKENS)
CONCURRENT_MESSAGE_PROMPT_TOKENS = frozenset(
    {CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION, CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION}
)
CONCURRENT_PRIMARY_PROFILE_FIELDS: tuple[str, ...] = (
    "activity_score",
    "global_influence_score",
    "local_influence_score",
    "concurrent_environmental_consciousness_coef",
    *(f"concurrent_{dimension}_value_weight" for dimension in LATENT_VALUE_DIMENSIONS),
    "concurrent_hotel_class",
    "concurrent_travel_purpose",
)
CONCURRENT_SHADOW_PROFILE_FIELDS: tuple[str, ...] = (
    *CONCURRENT_PRIMARY_PROFILE_FIELDS,
    "concurrent_gender",
    "concurrent_age",
    "concurrent_education",
    "concurrent_monthly_income",
)

OBSERVED_SCORE_FIELDS: tuple[tuple[str, str], ...] = (
    ("activity_score", "活跃度"),
    ("global_influence_score", "全平台影响力"),
    ("local_influence_score", "锦江酒店社群内的局部影响力"),
)

JINJIANG_PROMPT_V2_PROFILE_FIELDS: tuple[str, ...] = (
    "interest_tags",
    "activity_score",
    "global_influence_score",
    "local_influence_score",
    "latent_environmental_consciousness_coef",
    *(f"latent_{dimension}_value_weight" for dimension in LATENT_VALUE_DIMENSIONS),
    "latent_hotel_class",
    "latent_travel_purpose",
)
JINJIANG_PROMPT_V3_PROFILE_FIELDS: tuple[str, ...] = tuple(
    field_name for field_name in JINJIANG_PROMPT_V2_PROFILE_FIELDS if field_name != "interest_tags"
)

VALUE_LABELS: dict[str, str] = {
    "epistemic": "认知探索价值",
    "environmental": "环保消费价值",
    "functional": "功能价值",
    "health": "健康价值",
    "emotional": "情感价值",
    "social": "社交价值",
}

HOTEL_CLASS_LABELS: dict[str, str] = {
    "economy": "经济型酒店",
    "midscale": "中端酒店",
    "upper_midscale": "中高端酒店",
}

TRAVEL_PURPOSE_LABELS: dict[str, str] = {
    "business": "商务出行",
    "leisure": "休闲旅游",
}

GENDER_LABELS: dict[str, str] = {
    "female": "女性",
    "male": "男性",
}

AGE_LABELS: dict[str, str] = {
    "age_18_25": "18-25 岁",
    "age_26_35": "26-35 岁",
    "age_36_45": "36-45 岁",
    "age_46_55": "46-55 岁",
    "age_56_plus": "56 岁以上",
}

EDUCATION_LABELS: dict[str, str] = {
    "high_school_or_below": "高中及以下",
    "community_college": "大专",
    "bachelor": "本科",
    "master_or_above": "硕士及以上",
}

MONTHLY_INCOME_LABELS: dict[str, str] = {
    "income_8000_or_less": "8000 元及以下",
    "income_8001_15000": "8001-15000 元",
    "income_15001_25000": "15001-25000 元",
    "income_25001_40000": "25001-40000 元",
    "income_40001_or_more": "40001 元及以上",
}

PromptFieldInclusion = Literal["included", "empty_omitted"]


@dataclass
class PromptFieldInclusionCapture:
    """Collect field inclusion facts emitted by actual Prompt summary builds."""

    by_user: dict[str, dict[str, PromptFieldInclusion]] = field(default_factory=dict)


_PROMPT_FIELD_INCLUSION_CAPTURE: ContextVar[PromptFieldInclusionCapture | None] = ContextVar(
    "prompt_field_inclusion_capture",
    default=None,
)


@contextmanager
def capture_prompt_field_inclusion() -> Iterator[PromptFieldInclusionCapture]:
    capture = PromptFieldInclusionCapture()
    token = _PROMPT_FIELD_INCLUSION_CAPTURE.set(capture)
    try:
        yield capture
    finally:
        _PROMPT_FIELD_INCLUSION_CAPTURE.reset(token)


def build_prompt_field_summary(decision_input: DecisionInput) -> dict[str, str]:
    """Convert provider-visible decision context into stable Chinese summaries."""

    prompt_version = decision_input.prompt_version
    if prompt_version in JINJIANG_PROMPT_V3_TOKENS:
        summaries = {
            "post_summary": summarize_post_fields(decision_input.post),
            "marketing_content_summary": summarize_marketing_content_fields(decision_input.post),
            "post_value_summary": summarize_post_value_fields(decision_input.post),
            "observed_profile_summary": summarize_observed_prompt_fields(decision_input.profile),
            "consumption_preference_summary": summarize_consumption_preference_fields(decision_input.profile),
            "individual_preference_summary": summarize_prompt_fields(decision_input.profile),
            "peer_influence_summary": summarize_peer_fields(decision_input.peer_context),
            "platform_context_summary": summarize_platform_fields(decision_input.platform_context),
        }
        inclusion = profile_prompt_field_inclusion(decision_input.profile)
    elif prompt_version in CONCURRENT_ROBUSTNESS_PRIMARY_PROMPT_TOKENS:
        summaries = {
            "post_summary": summarize_post_fields(decision_input.post),
            "marketing_content_summary": summarize_marketing_content_fields(decision_input.post),
            "post_value_summary": summarize_post_value_fields(decision_input.post),
            "observed_profile_summary": summarize_concurrent_observed_prompt_fields(decision_input.profile),
            "consumption_preference_summary": summarize_concurrent_primary_labels(decision_input.profile),
            "individual_preference_summary": summarize_concurrent_prompt_fields(decision_input.profile),
            "peer_influence_summary": summarize_peer_fields(decision_input.peer_context),
            "platform_context_summary": "",
            "synthetic_demographic_summary": "",
        }
        inclusion = concurrent_profile_prompt_field_inclusion(decision_input.profile, decision_input.prompt_version)
    elif prompt_version == CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION:
        summaries = {
            "post_summary": summarize_post_fields(decision_input.post),
            "marketing_content_summary": summarize_marketing_content_fields(decision_input.post),
            "post_value_summary": summarize_post_value_fields(decision_input.post),
            "observed_profile_summary": summarize_concurrent_observed_prompt_fields(decision_input.profile),
            "consumption_preference_summary": summarize_concurrent_primary_labels(decision_input.profile, allow_shadow_demographics=True),
            "individual_preference_summary": summarize_concurrent_prompt_fields(decision_input.profile, allow_shadow_demographics=True),
            "peer_influence_summary": summarize_peer_fields(decision_input.peer_context),
            "platform_context_summary": "",
            "synthetic_demographic_summary": summarize_concurrent_shadow_labels(decision_input.profile),
        }
        inclusion = concurrent_profile_prompt_field_inclusion(decision_input.profile, decision_input.prompt_version)
    else:
        raise ValueError(f"unsupported prompt_version: {prompt_version}")

    capture = _PROMPT_FIELD_INCLUSION_CAPTURE.get()
    if capture is not None:
        capture.by_user[decision_input.profile.user_id] = inclusion
    return summaries


def summarize_prompt_fields(profile: UserProfile) -> str:
    """Return a stable Chinese prompt summary for provider-visible user fields."""

    parts = [summarize_observed_prompt_fields(profile)]
    preference_summary = summarize_consumption_preference_fields(profile)
    if preference_summary:
        parts.append(preference_summary)
    return "；".join(parts)


def profile_prompt_field_inclusion(profile: UserProfile) -> dict[str, PromptFieldInclusion]:
    """Return field-level inclusion facts from the same path that builds Prompt v2 summaries."""

    extra = profile.model_extra or {}
    included = {
        "activity_score": True,
        "global_influence_score": _optional_float(extra.get("global_influence_score")) is not None,
        "local_influence_score": _optional_float(extra.get("local_influence_score")) is not None,
    }
    attributes = profile.latent_attributes
    included.update(
        {
            "latent_environmental_consciousness_coef": attributes is not None,
            **{f"latent_{dimension}_value_weight": attributes is not None for dimension in LATENT_VALUE_DIMENSIONS},
            "latent_hotel_class": attributes is not None,
            "latent_travel_purpose": attributes is not None,
        }
    )
    return {
        field_name: "included" if included[field_name] else "empty_omitted"
        for field_name in JINJIANG_PROMPT_V3_PROFILE_FIELDS
    }


def concurrent_profile_prompt_field_inclusion(
    profile: UserProfile,
    prompt_version: str,
) -> dict[str, PromptFieldInclusion]:
    if prompt_version in CONCURRENT_ROBUSTNESS_PRIMARY_PROMPT_TOKENS:
        fields = CONCURRENT_PRIMARY_PROFILE_FIELDS
    elif prompt_version == CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION:
        fields = CONCURRENT_SHADOW_PROFILE_FIELDS
    else:
        raise ValueError(f"unsupported prompt_version: {prompt_version}")
    return {
        field_name: "included" if _concurrent_profile_value(profile, field_name) is not None else "empty_omitted"
        for field_name in fields
    }


def summarize_observed_prompt_fields(profile: UserProfile) -> str:
    """Return observed profile fields that may be shown to provider prompts."""

    parts: list[str] = ["说明：活跃度、全平台影响力、锦江酒店社群内的局部影响力为可观测代理指标"]
    extra = profile.model_extra or {}
    for field_name, label in OBSERVED_SCORE_FIELDS:
        score = profile.activity_score if field_name == "activity_score" else _optional_float(extra.get(field_name))
        if score is not None:
            parts.append(_score_summary(label, score))

    return "；".join(parts)


def summarize_concurrent_observed_prompt_fields(profile: UserProfile) -> str:
    return summarize_observed_prompt_fields(profile)


def summarize_consumption_preference_fields(profile: UserProfile) -> str:
    """Return virtual experiment preference fields that may be shown to provider prompts."""

    attributes = profile.latent_attributes
    if attributes is None:
        return ""

    parts: list[str] = ["环保意识倾向、消费价值、入住酒店类型和入住目的为虚拟实验标签，不代表真实身份或心理画像"]
    parts.append(
        "环保意识倾向："
        f"{_environmental_consciousness_level(attributes.environmental_consciousness_coef)}"
        f"（{attributes.environmental_consciousness_coef:.2f}）"
    )
    parts.append(_top_value_weights_summary(attributes.value_weights))
    parts.append(f"最近一次入住锦江旗下酒店类型：{HOTEL_CLASS_LABELS[attributes.profile_labels.hotel_class]}")
    parts.append(f"最近一次入住锦江旗下酒店目的：{TRAVEL_PURPOSE_LABELS[attributes.profile_labels.travel_purpose]}")
    return "；".join(parts)


def summarize_concurrent_primary_labels(profile: UserProfile, *, allow_shadow_demographics: bool = False) -> str:
    _require_concurrent_profile_fields(profile, CONCURRENT_PRIMARY_PROFILE_FIELDS)
    if not allow_shadow_demographics:
        _reject_concurrent_profile_fields(
            profile,
            ("concurrent_gender", "concurrent_age", "concurrent_education", "concurrent_monthly_income"),
            prompt_label=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
        )
    environmental = _concurrent_required_float(profile, "concurrent_environmental_consciousness_coef")
    value_weights = {
        dimension: _concurrent_required_float(profile, f"concurrent_{dimension}_value_weight")
        for dimension in LATENT_VALUE_DIMENSIONS
    }
    hotel_class = _concurrent_required_label(profile, "concurrent_hotel_class", HOTEL_CLASS_LABELS)
    travel_purpose = _concurrent_required_label(profile, "concurrent_travel_purpose", TRAVEL_PURPOSE_LABELS)
    parts = ["以下 Synthetic Experiment Labels 仅用于受控实验，不代表真实身份、心理画像或价值判断"]
    parts.append(f"环保意识倾向：{_environmental_consciousness_level(environmental)}（{environmental:.2f}）")
    parts.append(_top_value_weights_summary(_DictValueWeights(value_weights)))
    parts.append(f"最近一次入住锦江旗下酒店类型：{hotel_class}")
    parts.append(f"最近一次入住锦江旗下酒店目的：{travel_purpose}")
    return "；".join(parts)


def summarize_concurrent_shadow_labels(profile: UserProfile) -> str:
    _require_concurrent_profile_fields(profile, CONCURRENT_SHADOW_PROFILE_FIELDS)
    return "；".join(
        [
            "以下 Synthetic Experiment Labels 仅用于受控对照，不代表真实身份，不得据此推断人格、能力、价值高低或行为必然性",
            f"性别标签：{_concurrent_required_label(profile, 'concurrent_gender', GENDER_LABELS)}",
            f"年龄段标签：{_concurrent_required_label(profile, 'concurrent_age', AGE_LABELS)}",
            f"教育程度标签：{_concurrent_required_label(profile, 'concurrent_education', EDUCATION_LABELS)}",
            f"月收入区间标签：{_concurrent_required_label(profile, 'concurrent_monthly_income', MONTHLY_INCOME_LABELS)}",
        ]
    )


def summarize_concurrent_prompt_fields(profile: UserProfile, *, allow_shadow_demographics: bool = False) -> str:
    return "；".join(
        [
            summarize_concurrent_observed_prompt_fields(profile),
            summarize_concurrent_primary_labels(profile, allow_shadow_demographics=allow_shadow_demographics),
        ]
    )


def summarize_post_fields(post: PostContent) -> str:
    parts = [f"帖子内容：{_clean_text(post.text, MAX_TEXT_LENGTH)}"]
    topic_tags = _clean_interest_tags(post.topic_tags)
    if topic_tags:
        parts.append(f"主题标签：{'、'.join(topic_tags)}")
    if post.media_summary:
        parts.append(f"媒体摘要：{_clean_text(post.media_summary, MAX_TEXT_LENGTH)}")

    value_parts = [
        f"{VALUE_LABELS[dimension]}（{float(getattr(post.value_dimensions, dimension)):.2f}）"
        for dimension in LATENT_VALUE_DIMENSIONS
        if float(getattr(post.value_dimensions, dimension)) > 0.0
    ]
    if value_parts:
        parts.append(f"帖子价值维度：{'、'.join(value_parts)}")
    return "；".join(parts)


def summarize_marketing_content_fields(post: PostContent) -> str:
    """Return the full normalized marketing copy for Prompt v2."""

    return _normalize_text(post.text)


def summarize_post_value_fields(post: PostContent) -> str:
    """Return the value dimensions emphasized by a post without topic tag expansion."""

    value_parts = [
        f"{VALUE_LABELS[dimension]}（{float(getattr(post.value_dimensions, dimension)):.2f}）"
        for dimension in LATENT_VALUE_DIMENSIONS
        if float(getattr(post.value_dimensions, dimension)) > 0.0
    ]
    if not value_parts:
        return "未提供明确价值维度"
    return "、".join(value_parts)


def summarize_peer_fields(peer_context: PeerContext) -> str:
    return "；".join(
        [
            f"邻居曝光：{peer_context.exposed_neighbors}",
            f"邻居互动：{peer_context.engaged_neighbors}",
            f"互动比例：{peer_context.engagement_ratio:.2f}",
            f"有影响力的已互动邻居：{peer_context.influential_engaged_neighbors}",
            f"可见点赞：{peer_context.visible_likes}",
            f"可见评论：{peer_context.visible_comments}",
            f"可见分享：{peer_context.visible_shares}",
        ]
    )


def summarize_platform_fields(platform_context: PlatformContext) -> str:
    parts: list[str] = []
    if platform_context.time_label:
        parts.append(f"时间标签：{_clean_text(platform_context.time_label, MAX_TEXT_LENGTH)}")
    hot_topics = _clean_interest_tags(platform_context.hot_topics)
    if hot_topics:
        parts.append(f"平台热门话题：{'、'.join(hot_topics)}")
    if platform_context.platform_mood:
        parts.append(f"平台氛围：{_clean_text(platform_context.platform_mood, MAX_TEXT_LENGTH)}")
    parts.append(f"Feed 排序权重：{platform_context.feed_ranking_weight:.2f}")
    parts.append(f"痕迹可见度：{platform_context.trace_visibility:.2f}")
    return "；".join(parts)


@dataclass(frozen=True)
class _DictValueWeights:
    values: dict[str, float]

    def __getattr__(self, name: str) -> float:
        try:
            return self.values[name]
        except KeyError as exc:  # pragma: no cover - defensive only.
            raise AttributeError(name) from exc


def _concurrent_profile_value(profile: UserProfile, field_name: str) -> Any:
    extra = profile.model_extra or {}
    if field_name == "activity_score":
        return profile.activity_score
    return extra.get(field_name)


def _require_concurrent_profile_fields(profile: UserProfile, fields: tuple[str, ...]) -> None:
    missing = [field_name for field_name in fields if _concurrent_profile_value(profile, field_name) is None]
    if missing:
        raise ValueError(f"prompt context mismatch for {fields[0].split('_')[0]} variant: missing {', '.join(missing)}")


def _reject_concurrent_profile_fields(
    profile: UserProfile,
    fields: tuple[str, ...],
    *,
    prompt_label: str,
) -> None:
    present = [field_name for field_name in fields if _concurrent_profile_value(profile, field_name) is not None]
    if present:
        raise ValueError(f"prompt context mismatch for {prompt_label}: unexpected {', '.join(present)}")


def _concurrent_required_float(profile: UserProfile, field_name: str) -> float:
    value = _optional_float(_concurrent_profile_value(profile, field_name))
    if value is None:
        raise ValueError(f"prompt context mismatch: missing {field_name}")
    return value


def _concurrent_required_label(profile: UserProfile, field_name: str, labels: dict[str, str]) -> str:
    raw = _concurrent_profile_value(profile, field_name)
    if not isinstance(raw, str) or raw not in labels:
        raise ValueError(f"prompt context mismatch: invalid {field_name}")
    return labels[raw]


def _clean_interest_tags(raw_tags: list[str]) -> list[str]:
    cleaned_tags: list[str] = []
    seen: set[str] = set()
    for raw_tag in raw_tags:
        tag = _clean_text(str(raw_tag), MAX_INTEREST_TAG_LENGTH)
        if not tag or tag in seen:
            continue
        seen.add(tag)
        cleaned_tags.append(tag)
        if len(cleaned_tags) >= MAX_INTEREST_TAGS:
            break
    return cleaned_tags


def _score_summary(label: str, score: float) -> str:
    bounded_score = min(max(score, 0.0), 1.0)
    return f"{label}：{_score_level(bounded_score)}（{score:.2f}）"


def _score_level(score: float) -> str:
    if score >= 0.8:
        return "高"
    if score >= 0.6:
        return "中等偏高"
    if score >= 0.4:
        return "中等"
    if score >= 0.2:
        return "中等偏低"
    return "低"


def _environmental_consciousness_level(coefficient: float) -> str:
    if coefficient >= 1.0:
        return "正向较强"
    if coefficient > 0.0:
        return "正向"
    if coefficient == 0.0:
        return "中性"
    if coefficient > -1.0:
        return "负向"
    return "负向较强"


def _top_value_weights_summary(value_weights: Any) -> str:
    weighted_dimensions = sorted(
        LATENT_VALUE_DIMENSIONS,
        key=lambda dimension: (-float(getattr(value_weights, dimension)), LATENT_VALUE_DIMENSIONS.index(dimension)),
    )[:3]
    values = [
        f"{VALUE_LABELS[dimension]}（{float(getattr(value_weights, dimension)):.2f}）"
        for dimension in weighted_dimensions
    ]
    return f"前三个秸秆制品相关消费价值：{'、'.join(values)}"


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_text(value: str, max_length: int) -> str:
    return _normalize_text(value)[:max_length]


def _normalize_text(value: str) -> str:
    return " ".join(value.split())
