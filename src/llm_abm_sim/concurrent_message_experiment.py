from __future__ import annotations

import csv
import html
import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .concurrent_campaign_diagnostics import ConcurrentCampaignDiagnosticArtifacts, ConcurrentCampaignDiagnostics
from .concurrent_message_report import write_concurrent_message_report_artifacts
from .decision import DecisionInput, EngageDecision, LLMDecisionAdapter, decision_profile_payload
from .final_research import (
    _TARGET_DELIVERY_RANKING_POLICY,
    REQUIRED_DATASET_FILES,
    SEED_FIRST_SAMPLING_METHOD,
    TARGET_VIDEO_ID,
    VALIDATION_RUN_STATUS,
    ResearchUser,
    _adapter_safe_metadata,
    _attempt_runtime_decision,
    _csv_bool,
    _json_cell,
    _log_p95_score,
    _PreparedResearchCohort,
    _ResearchCohortPreparer,
    _RuntimeDecisionAttempt,
    _safe_runtime_rows,
)
from .prompt_field_summary import (
    CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
    CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
    CONCURRENT_PRIMARY_PROFILE_FIELDS,
    CONCURRENT_SHADOW_PROFILE_FIELDS,
)
from .provider_accounting import ProviderAccounting, empty_provider_accounting, provider_accounting_delta
from .provider_evidence import allowlisted_provider_evidence
from .schemas import (
    LATENT_VALUE_DIMENSIONS,
    PeerContext,
    PlatformContext,
    PostContent,
    ProviderLLMConfig,
    ReportConfig,
    UserProfile,
    ValueDimensions,
)

CONCURRENT_MESSAGE_RUNTIME_VERSION = "concurrent-message-validation-runtime-v1"
CONCURRENT_MESSAGE_VALIDATION_VERSION = "concurrent-message-validation-v1"
CONCURRENT_MESSAGE_STEP_JSON = "concurrent_runtime_steps.json"
CONCURRENT_MESSAGE_CANDIDATE_CSV = "concurrent_runtime_candidates.csv"
CONCURRENT_MESSAGE_PAIR_CSV = "concurrent_runtime_pairs.csv"
CONCURRENT_MESSAGE_TERMINAL_CSV = "concurrent_runtime_terminal_rows.csv"
CONCURRENT_MESSAGE_VALIDATION_JSON = "concurrent_validation.json"
CONCURRENT_MESSAGE_CAMPAIGN_DIAGNOSTICS_JSON = "concurrent_campaign_diagnostics.json"
CONCURRENT_MESSAGE_REPORT_HTML = "report.html"
CONCURRENT_MESSAGE_MESSAGE_JSON = "message_snapshot.json"
CONCURRENT_MESSAGE_SAMPLE_JSON = "sample_manifest.json"
CONCURRENT_MESSAGE_SAMPLE_CSV = "sample_manifest.csv"
CONCURRENT_MESSAGE_CONFIG_JSON = "config_snapshot.json"
CONCURRENT_MESSAGE_SEED_AUDIT_JSON = "seed_first_sample_audit.json"
CONCURRENT_MESSAGE_HOLDOUT_VIDEO_ID = TARGET_VIDEO_ID
CONCURRENT_MESSAGE_PRODUCTION_SAMPLE_SIZE = 1000
CONCURRENT_MESSAGE_PRODUCTION_HORIZON = 30
CONCURRENT_MESSAGE_PRODUCTION_DELIVERY_CAPACITY = 20
CONCURRENT_MESSAGE_ENGAGED_NEIGHBOR_FORMULA = "min(1, engaged_neighbor_count / 3)"
CONCURRENT_MESSAGE_RANKING_FORMULA = (
    "0.50 * base_network_relevance + 0.30 * campaign_engaged_neighbor_signal + 0.20 * normalized_message_user_fit"
)
CONCURRENT_MESSAGE_HISTORY_AFFINITY = 0.0
CONCURRENT_MESSAGE_POSITIVE_ACTIONS = {"like", "comment", "share"}
CONCURRENT_MESSAGE_SHADOW_ADDITIONAL_PROFILE_FIELDS = (
    "concurrent_gender",
    "concurrent_age",
    "concurrent_education",
    "concurrent_monthly_income",
)
CONCURRENT_MESSAGE_PRIMARY_EXCLUDED_CONTEXT_FIELDS = (
    "nickname",
    "bio",
    "signature",
    "follower_count",
    "following_count",
    "video_count",
    "latent_class",
    "interest_tags",
    "historical_tags",
    "intended_audience_segment",
    "message_vector",
    "raw_message_user_fit",
    "normalized_message_user_fit",
    "personalized_delivery_score",
    "ranking_position",
    "base_network_relevance",
    "campaign_engaged_neighbor_count",
    "campaign_engaged_neighbor_signal",
    "historical_tag_affinity",
    "sample_holdout_video_id",
    "platform_context",
    "other_message_history",
)
CONCURRENT_MESSAGE_CANDIDATE_FIELDS = (
    "time_step",
    "message_id",
    "user_id",
    "is_seed",
    "selected",
    "selection_reason",
    "ranking_position",
    "base_network_relevance",
    "base_network_relevance_full_precision",
    "campaign_engaged_neighbor_count",
    "campaign_engaged_neighbor_signal",
    "campaign_engaged_neighbor_signal_full_precision",
    "historical_tag_affinity",
    "raw_message_user_fit",
    "raw_message_user_fit_full_precision",
    "normalized_message_user_fit",
    "normalized_message_user_fit_full_precision",
    "personalized_delivery_score",
    "personalized_delivery_score_full_precision",
)
CONCURRENT_MESSAGE_PAIR_FIELDS = (
    "pair_id",
    "pair_schedule_position",
    "time_step",
    "message_id",
    "message_title",
    "user_id",
    "latent_class",
    "shadow_gender",
    "shadow_age",
    "shadow_education",
    "shadow_monthly_income",
    "is_seed",
    "selection_reason",
    "ranking_position",
    "base_network_relevance",
    "base_network_relevance_full_precision",
    "campaign_engaged_neighbor_count",
    "campaign_engaged_neighbor_signal",
    "campaign_engaged_neighbor_signal_full_precision",
    "historical_tag_affinity",
    "raw_message_user_fit",
    "raw_message_user_fit_full_precision",
    "normalized_message_user_fit",
    "normalized_message_user_fit_full_precision",
    "personalized_delivery_score",
    "personalized_delivery_score_full_precision",
    "primary_status",
    "primary_action",
    "primary_probability",
    "primary_confidence",
    "primary_reason",
    "primary_decision_source",
    "primary_prompt_version",
    "primary_provider_metadata",
    "shadow_status",
    "shadow_action",
    "shadow_probability",
    "shadow_confidence",
    "shadow_reason",
    "shadow_decision_source",
    "shadow_prompt_version",
    "shadow_provider_metadata",
    "campaign_feedback_committed",
    "pair_terminal_coverage",
    "paired_decision_coverage",
)
CONCURRENT_MESSAGE_TERMINAL_FIELDS = (
    "terminal_row_id",
    "pair_id",
    "pair_schedule_position",
    "time_step",
    "message_id",
    "user_id",
    "decision_variant",
    "prompt_version",
    "context_source_key",
    "cache_key",
    "context_profile_payload",
    "peer_context_payload",
    "prompt_field_inclusion",
    "terminal_status",
    "provider_status",
    "request_invocations",
    "provider_response_count",
    "successful_decision_count",
    "observed_model_counts",
    "observed_model_missing_response_count",
    "observed_model_malformed_response_count",
    "usage_complete",
    "usage_complete_response_count",
    "usage_missing_response_count",
    "usage_malformed_response_count",
    "input_usage",
    "output_usage",
    "total_usage",
    "cached_input_usage",
    "engage",
    "probability",
    "confidence",
    "action",
    "reason",
    "decision_source",
    "failure_type",
    "provider_metadata",
)

_MESSAGE_1_BODY = """每次在旅途中下榻酒店，面对洗手台上那些用完即弃的全塑料洗漱用品，注重环保的你，或许也曾有过些许无奈。在锦江酒店，这件微小的日常有了不一样的答案。我们把田野里的麦浪，变成了你手心里的绿色体验。

你可能好奇，秸秆是怎么变成客房洗漱用品的？其实，那些废弃的小麦秸秆，在经过严格的无菌化处理与天然提取后，于高温下淬炼成型。繁复的工艺并非目的，而是为了消除新兴材料的安全隐患，确保最终到达你手中的牙刷和梳子零甲醛、无有害残留。在保障安全与卫生的同时，这也是一份我们共同为地球减负的证明。用天然秸秆替代传统全塑料材质，不仅让农作物废弃物实现了高效的资源循环利用，更从源头上大幅减少了石化资源消耗与碳排放。

作为积极落实 ESG 理念的头部酒店集团，锦江酒店深知，真正的“商业向善”与社会责任，就藏在这些关乎环境的微小细节里。截至目前，锦江旗下已有近万家门店通过锦江全球采购平台（GPP）全面推广秸秆材质的洗漱耗品，超700家门店已完成酒店可持续发展基准（HSB）认证。从理念到行动，我们致力于让“去塑化”和“循环经济”融入你的每一次旅居体验。

万物流转，皆是馈赠。下一次，当你入住锦江旗下酒店，拿起那把带有自然纹理的牙刷时，请记得，你不是在消费，而是在和锦江一起，用微小却坚定的力量，照亮这个蔚蓝星球的绿色未来。"""

_MESSAGE_2_BODY = """一次好的入住体验，往往藏在细节里。房间是否整洁，用品是否安心，设计是否舒适，都会影响一段旅程的质感。而真正打动人的，常常是那些看不见的用心。入住锦江酒店时，你也许会在洗漱台前发现一点小变化：手中的牙刷和梳子，已悄悄换成了秸秆材质。

很多人会关心，秸秆材质好用吗？卫生吗？会不会发软、不耐用？答案是不会。锦江酒店所使用的秸秆材质洗漱用品，在安全性与实用性上都经过严格把控。我们以严苛标准筛选并处理天然秸秆成分，确保产品零甲醛、无有害残留。同时，材质的改变并不意味着对品质的妥协。在实际使用中，牙刷握感轻盈扎实，刷毛柔韧舒适；梳子触感平滑，梳齿顺畅不易变形。无论是硬度、耐用性，还是整体使用感受，都与传统塑料制品保持着接近的体验标准。细闻之下，还有淡淡麦香。

如今，锦江酒店旗下近万家门店已完成秸秆材质洗漱耗品替换，另有700多家门店通过全球酒店可持续发展基准（HSB）认证。这看似只是一次洗漱用品的升级，背后却是对资源价值的重塑。曾被视作农业剩余物的秸秆，如今被重新利用，成为酒店日常用品的一部分。对自然的珍视，不一定宏大，也可以是触手可及的改变。

下一次来到锦江，欢迎感受这把来自麦田的牙刷。它承载的，不只是一次使用，也是一种更可持续的生活方式。锦江酒店，陪你轻松出行，也陪地球好好呼吸。"""

_MESSAGE_3_BODY = """当田野中的秸秆，经过匠心工艺走进酒店客房，一场关于自然、环保与品质的旅居革新，正在悄然发生。

在许多人的印象中，秸秆只是农作物收获后的剩余物，常常被视作不起眼的“边角料”；而在锦江酒店看来，它是值得被重新定义的自然资源。通过精细研磨，并与改性淀粉、生物降解聚酯科学复配，再经过高温热压、挤出成型等多道工艺，原本朴素的秸秆被创新应用于牙刷、梳子、地板等酒店日常用品之中。繁复的工序并非博人眼球，而是一份对健康的极致坚守。出门在外，贴肤与入口的物件，安心始终是第一位的。这套工艺减少了多余化学添加，确保到达你手中的洗漱用品，零甲醛、无重金属与塑化剂残留，以更贴近自然的材料选择，满足旅途中对洁净与安心的需要。

这份对个人健康的关注，同样也是锦江对绿色生活方式的积极践行。每一次使用天然秸秆替代传统塑料，都在无声地减少着石化资源的消耗。作为可持续生活方式的倡导者，锦江将宏大的环保理念，妥帖地藏在了这些不增加您负担的微小细节里。

从“秸秆是垃圾”到“秸秆也能成为品质好物”，材料的每一次创新，都是对未来生活方式的一次重新想象。下次入住锦江酒店，当你拿起一把带着自然温度的秸秆牙刷，不妨感受一下这份来自“麦田里的黑科技”。在享受假期的同时，你也正以一种优雅的方式，与我们一起守护这颗蔚蓝星球。"""


class ExperimentalMessageDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    message_id: str
    title: str
    intended_audience_segment: Literal["class_1", "class_2", "class_3"]
    body: str
    value_dimensions: ValueDimensions

    @field_validator("message_id", "title")
    @classmethod
    def _non_empty_token(cls, value: str) -> str:
        token = value.strip()
        if not token:
            raise ValueError("must not be empty")
        return token

    @field_validator("body")
    @classmethod
    def _non_empty_body(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("body must not be empty")
        return value

    def as_post(self) -> PostContent:
        return PostContent(post_id=self.message_id, text=self.body, value_dimensions=self.value_dimensions)

    def vector(self) -> tuple[float, ...]:
        return tuple(float(getattr(self.value_dimensions, dimension)) for dimension in LATENT_VALUE_DIMENSIONS)


def authoritative_message_definitions() -> tuple[ExperimentalMessageDefinition, ...]:
    return (
        ExperimentalMessageDefinition(
            message_id="message_1",
            title="Message for Class 1",
            intended_audience_segment="class_1",
            body=_MESSAGE_1_BODY,
            value_dimensions=ValueDimensions(environmental=1.0, health=1.0, social=1.0),
        ),
        ExperimentalMessageDefinition(
            message_id="message_2",
            title="Message for Class 2",
            intended_audience_segment="class_2",
            body=_MESSAGE_2_BODY,
            value_dimensions=ValueDimensions(environmental=1.0, functional=1.0, health=1.0),
        ),
        ExperimentalMessageDefinition(
            message_id="message_3",
            title="Message for Class 3",
            intended_audience_segment="class_3",
            body=_MESSAGE_3_BODY,
            value_dimensions=ValueDimensions(epistemic=1.0, environmental=1.0, health=1.0),
        ),
    )


class ConcurrentMessageExperimentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_dir: Path
    sample_size: int = Field(default=CONCURRENT_MESSAGE_PRODUCTION_SAMPLE_SIZE, ge=1)
    horizon: int = Field(default=CONCURRENT_MESSAGE_PRODUCTION_HORIZON, ge=1)
    delivery_capacity: int = Field(default=CONCURRENT_MESSAGE_PRODUCTION_DELIVERY_CAPACITY, ge=1)
    random_seed: int = 20260713
    configuration_profile: Literal["production", "validation"] = "production"
    sample_holdout_video_id: str = CONCURRENT_MESSAGE_HOLDOUT_VIDEO_ID
    messages: tuple[ExperimentalMessageDefinition, ...] = Field(default_factory=authoritative_message_definitions)
    report: ReportConfig = Field(default_factory=lambda: ReportConfig(title="Concurrent Message Experiment Validation"))

    @field_validator("sample_holdout_video_id")
    @classmethod
    def _fixed_holdout_video(cls, value: str) -> str:
        if value != CONCURRENT_MESSAGE_HOLDOUT_VIDEO_ID:
            raise ValueError(
                f"sample_holdout_video_id must remain the approved shared holdout video {CONCURRENT_MESSAGE_HOLDOUT_VIDEO_ID}"
            )
        return value

    @model_validator(mode="after")
    def _validate_contract(self) -> ConcurrentMessageExperimentConfig:
        dataset_dir = self.dataset_dir.expanduser()
        if not dataset_dir.is_dir():
            raise ValueError(f"dataset_dir does not exist: {dataset_dir}")
        missing = [filename for filename in REQUIRED_DATASET_FILES if not (dataset_dir / filename).is_file()]
        if not (dataset_dir / "all_comments.csv").is_file() and not (dataset_dir / "comments.csv").is_file():
            missing.append("all_comments.csv or comments.csv")
        if missing:
            raise ValueError(f"dataset_dir is missing required file(s): {', '.join(missing)}")

        target_exists = False
        with (dataset_dir / "videos.csv").open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if str(row.get("video_id", "") or "").strip() == self.sample_holdout_video_id:
                    target_exists = True
                    break
        if not target_exists:
            raise ValueError(f"target video {self.sample_holdout_video_id} is absent from videos.csv")

        user_ids: set[str] = set()
        with (dataset_dir / "users.csv").open(encoding="utf-8", newline="") as handle:
            for row_number, row in enumerate(csv.DictReader(handle), start=2):
                user_id = str(row.get("user_id", "") or "").strip()
                if not user_id:
                    raise ValueError(f"users.csv row {row_number} has an empty user_id")
                if user_id in user_ids:
                    raise ValueError(f"users.csv contains duplicate user_id: {user_id}")
                user_ids.add(user_id)
        if self.sample_size > len(user_ids):
            raise ValueError(f"sample_size {self.sample_size} exceeds available user count {len(user_ids)}")

        if len(self.messages) != 3:
            raise ValueError("concurrent message experiment requires exactly 3 messages")
        message_ids = [message.message_id for message in self.messages]
        if len(set(message_ids)) != len(message_ids):
            raise ValueError("message_id values must be unique")

        authoritative_messages = [message.model_dump(mode="json") for message in authoritative_message_definitions()]
        if [message.model_dump(mode="json") for message in self.messages] != authoritative_messages:
            raise ValueError("messages must exactly match the authoritative three-message contract")

        if self.configuration_profile == "production":
            if self.sample_size != CONCURRENT_MESSAGE_PRODUCTION_SAMPLE_SIZE:
                raise ValueError(f"production sample_size must be {CONCURRENT_MESSAGE_PRODUCTION_SAMPLE_SIZE}")
            if self.horizon != CONCURRENT_MESSAGE_PRODUCTION_HORIZON:
                raise ValueError(f"production horizon must be {CONCURRENT_MESSAGE_PRODUCTION_HORIZON}")
            if self.delivery_capacity != CONCURRENT_MESSAGE_PRODUCTION_DELIVERY_CAPACITY:
                raise ValueError(
                    f"production delivery_capacity must be {CONCURRENT_MESSAGE_PRODUCTION_DELIVERY_CAPACITY}"
                )
            if [message.model_dump(mode="json") for message in self.messages] != [
                message.model_dump(mode="json") for message in authoritative_message_definitions()
            ]:
                raise ValueError("production messages must exactly match the authoritative three-message contract")

        self.dataset_dir = dataset_dir
        return self

    def snapshot(self) -> dict[str, object]:
        return {
            "dataset_dir": str(self.dataset_dir),
            "sample_size": self.sample_size,
            "horizon": self.horizon,
            "delivery_capacity": self.delivery_capacity,
            "random_seed": self.random_seed,
            "configuration_profile": self.configuration_profile,
            "sample_holdout_video_id": self.sample_holdout_video_id,
            "ranking_formula": CONCURRENT_MESSAGE_RANKING_FORMULA,
            "engaged_neighbor_formula": CONCURRENT_MESSAGE_ENGAGED_NEIGHBOR_FORMULA,
            "historical_tag_affinity": CONCURRENT_MESSAGE_HISTORY_AFFINITY,
            "sampling_method": SEED_FIRST_SAMPLING_METHOD,
            "sampling_status": VALIDATION_RUN_STATUS,
            "production_deploy_eligible": False,
            "messages": [message.model_dump(mode="json") for message in self.messages],
            "report": self.report.model_dump(mode="json"),
        }


@dataclass(frozen=True)
class _MessageScore:
    user_id: str
    base_network_relevance: float
    engaged_neighbor_count: int
    engaged_neighbor_signal: float
    raw_message_user_fit: float
    normalized_message_user_fit: float
    personalized_delivery_score: float


@dataclass(frozen=True)
class _PairExecutionPlan:
    pair_id: str
    pair_schedule_position: int
    time_step: int
    message: ExperimentalMessageDefinition
    user: ResearchUser
    profile: UserProfile
    ranking_position: int
    selection_reason: str
    score: _MessageScore


class _BatchMessageSummary(TypedDict):
    message_id: str
    message_title: str
    eligible_users: int
    ranked_candidates: int
    selected_user_ids: list[str]
    seed_user_ids: list[str]
    personalized_topup_user_ids: list[str]
    primary_positive_user_ids: list[str]
    primary_provider_failed_user_ids: list[str]
    shadow_provider_failed_user_ids: list[str]
    below_delivery_capacity: int
    selection_reason_counts: dict[str, int]


class _BatchStepSummary(TypedDict):
    time_step: int
    frozen_campaign_engaged_user_ids: list[str]
    deduplicated_committed_primary_positive_user_ids: list[str]
    messages: list[_BatchMessageSummary]


def _cosine_similarity(left: Sequence[float], right: Sequence[float], *, zero_label: str) -> float:
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        raise ValueError(f"{zero_label} has zero norm and cannot produce a cosine score")
    return sum(left_value * right_value for left_value, right_value in zip(left, right, strict=True)) / (
        left_norm * right_norm
    )


def _message_user_fit_components(message: ExperimentalMessageDefinition, user: ResearchUser) -> tuple[float, float]:
    message_vector = message.vector()
    user_vector = tuple(float(user.latent_attributes[f"latent_{dimension}_value_weight"]) for dimension in LATENT_VALUE_DIMENSIONS)
    raw_fit = _cosine_similarity(message_vector, user_vector, zero_label=f"message/user pair {message.message_id}/{user.user_id}")
    normalized_fit = (raw_fit + 1.0) / 2.0
    return raw_fit, normalized_fit


def _rank_message_candidates(
    *,
    message: ExperimentalMessageDefinition,
    users_by_id: Mapping[str, ResearchUser],
    eligible_user_ids: Sequence[str],
    base_network_by_user: Mapping[str, float],
    neighbors_by_user: Mapping[str, set[str]],
    campaign_engaged_user_ids: set[str],
) -> list[_MessageScore]:
    scores: list[_MessageScore] = []
    for user_id in eligible_user_ids:
        user = users_by_id[user_id]
        raw_fit, normalized_fit = _message_user_fit_components(message, user)
        engaged_neighbor_count = len(neighbors_by_user.get(user_id, set()) & campaign_engaged_user_ids)
        engaged_neighbor_signal = min(1.0, engaged_neighbor_count / 3.0)
        base_network_relevance = base_network_by_user.get(user_id, 0.0)
        personalized_delivery_score = (
            0.50 * base_network_relevance + 0.30 * engaged_neighbor_signal + 0.20 * normalized_fit
        )
        scores.append(
            _MessageScore(
                user_id=user_id,
                base_network_relevance=base_network_relevance,
                engaged_neighbor_count=engaged_neighbor_count,
                engaged_neighbor_signal=engaged_neighbor_signal,
                raw_message_user_fit=raw_fit,
                normalized_message_user_fit=normalized_fit,
                personalized_delivery_score=personalized_delivery_score,
            )
        )
    return sorted(scores, key=lambda score: (-score.personalized_delivery_score, score.user_id))


def _select_batch_candidates(
    *,
    time_step: int,
    ranked_scores: Sequence[_MessageScore],
    seed_user_ids: Sequence[str],
    delivery_capacity: int,
) -> tuple[list[_MessageScore], dict[str, str]]:
    seed_set = set(seed_user_ids)
    if time_step != 0:
        selected = list(ranked_scores[:delivery_capacity])
        return selected, {score.user_id: "personalized_top20" for score in selected}

    selected = [score for score in ranked_scores if score.user_id in seed_set]
    if len(selected) > delivery_capacity:
        raise ValueError(
            f"delivery_capacity {delivery_capacity} is smaller than the seed union size {len(selected)}"
        )
    selection_reason_by_user = {score.user_id: "seed_union" for score in selected}
    if len(selected) == delivery_capacity:
        return selected, selection_reason_by_user

    for score in ranked_scores:
        if score.user_id in selection_reason_by_user:
            continue
        selected.append(score)
        selection_reason_by_user[score.user_id] = "personalized_topup"
        if len(selected) == delivery_capacity:
            break
    return selected, selection_reason_by_user


@dataclass(frozen=True)
class _VariantDecisionContext:
    decision_variant: Literal["primary", "shadow"]
    prompt_token: str
    post: PostContent
    profile: UserProfile
    peer_context: PeerContext
    platform_context: PlatformContext

    def decision_input(self, *, time_step: int) -> DecisionInput:
        return DecisionInput(
            post=self.post,
            profile=self.profile,
            peer_context=self.peer_context,
            platform_context=self.platform_context,
            time_step=time_step,
            prompt_version=self.prompt_token,
        )


@dataclass(frozen=True)
class _AdapterRuntimeBaseline:
    request_invocations: int
    provider_accounting: ProviderAccounting
    has_provider_accounting: bool


@dataclass(frozen=True)
class _VariantAttemptAccounting:
    request_invocations: int
    provider_response_count: int
    successful_decision_count: int
    observed_model_counts: dict[str, int]
    observed_model_missing_response_count: int
    observed_model_malformed_response_count: int
    usage_complete: bool
    usage_complete_response_count: int
    usage_missing_response_count: int
    usage_malformed_response_count: int
    input_usage: int | None
    output_usage: int | None
    total_usage: int | None
    cached_input_usage: int | None


def _shared_variant_profile_payload(user: ResearchUser) -> dict[str, object]:
    latent = user.latent_attributes
    return {
        "user_id": user.user_id,
        "activity_score": user.activity_score,
        "global_influence_score": user.global_influence_score,
        "local_influence_score": user.local_influence_score,
        "concurrent_environmental_consciousness_coef": latent["latent_environmental_consciousness_coef"],
        **{
            f"concurrent_{dimension}_value_weight": latent[f"latent_{dimension}_value_weight"]
            for dimension in LATENT_VALUE_DIMENSIONS
        },
        "concurrent_hotel_class": latent["latent_hotel_class"],
        "concurrent_travel_purpose": latent["latent_travel_purpose"],
    }


def _primary_variant_profile(user: ResearchUser) -> UserProfile:
    return UserProfile.model_validate(_shared_variant_profile_payload(user))


def _shadow_variant_profile(user: ResearchUser) -> UserProfile:
    latent = user.latent_attributes
    return UserProfile.model_validate(
        {
            **_shared_variant_profile_payload(user),
            "concurrent_gender": latent["latent_gender"],
            "concurrent_age": latent["latent_age"],
            "concurrent_education": latent["latent_education"],
            "concurrent_monthly_income": latent["latent_monthly_income"],
        }
    )


def _primary_variant_context(plan: _PairExecutionPlan) -> _VariantDecisionContext:
    return _VariantDecisionContext(
        decision_variant="primary",
        prompt_token=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
        post=plan.message.as_post(),
        profile=_primary_variant_profile(plan.user),
        peer_context=PeerContext(),
        platform_context=PlatformContext(),
    )


def _shadow_variant_context(plan: _PairExecutionPlan) -> _VariantDecisionContext:
    return _VariantDecisionContext(
        decision_variant="shadow",
        prompt_token=CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
        post=plan.message.as_post(),
        profile=_shadow_variant_profile(plan.user),
        peer_context=PeerContext(),
        platform_context=PlatformContext(),
    )


def _unwrap_adapter(adapter: LLMDecisionAdapter) -> tuple[LLMDecisionAdapter, list[object]]:
    current = adapter
    caches: list[object] = []
    seen: set[int] = set()
    while True:
        if id(current) in seen:
            raise ValueError("decision adapter wrapper chain contains a cycle")
        seen.add(id(current))
        cache = getattr(current, "cache", None)
        if cache is not None:
            caches.append(cache)
        wrapped = getattr(current, "wrapped", None)
        if not isinstance(wrapped, LLMDecisionAdapter):
            return current, caches
        current = wrapped


def _adapter_prompt_version(adapter: LLMDecisionAdapter) -> str:
    prompt_version = getattr(adapter, "prompt_version", None)
    if isinstance(prompt_version, str) and prompt_version:
        return prompt_version
    leaf, _ = _unwrap_adapter(adapter)
    prompt_version = getattr(leaf, "prompt_version", None)
    if isinstance(prompt_version, str) and prompt_version:
        return prompt_version
    raise ValueError(f"adapter {type(adapter).__qualname__} must expose a prompt_version")


def _adapter_runtime_baseline(adapter: LLMDecisionAdapter) -> _AdapterRuntimeBaseline:
    leaf, _ = _unwrap_adapter(adapter)
    request_invocations = getattr(leaf, "request_invocations", 0)
    if not isinstance(request_invocations, int) or request_invocations < 0:
        raise TypeError("adapter request_invocations must be a non-negative int")
    accounting = getattr(leaf, "provider_accounting", None)
    if isinstance(accounting, ProviderAccounting):
        return _AdapterRuntimeBaseline(
            request_invocations=request_invocations,
            provider_accounting=accounting,
            has_provider_accounting=True,
        )
    return _AdapterRuntimeBaseline(
        request_invocations=request_invocations,
        provider_accounting=empty_provider_accounting(),
        has_provider_accounting=False,
    )


def _attempt_observed_model(
    attempt: _RuntimeDecisionAttempt,
    default_provider_metadata: Mapping[str, object],
) -> str | None:
    decision = attempt.decision
    if isinstance(decision, EngageDecision) and isinstance(decision.provider_metadata, Mapping):
        model = decision.provider_metadata.get("model")
        if isinstance(model, str) and model.strip():
            return model
    model = default_provider_metadata.get("model")
    if isinstance(model, str) and model.strip():
        return model
    return None


def _variant_attempt_accounting(
    *,
    adapter: LLMDecisionAdapter,
    baseline: _AdapterRuntimeBaseline,
    attempt: _RuntimeDecisionAttempt,
    default_provider_metadata: Mapping[str, object],
) -> _VariantAttemptAccounting:
    after = _adapter_runtime_baseline(adapter)
    request_delta = after.request_invocations - baseline.request_invocations
    if request_delta < 0:
        raise ValueError("adapter request_invocations moved backwards")
    logical_attempted = attempt.decision is not None or attempt.provider_failure is not None
    minimum_requests = 1 if logical_attempted else 0

    if baseline.has_provider_accounting and after.has_provider_accounting:
        delta = provider_accounting_delta(after.provider_accounting, baseline.provider_accounting)
        usage_complete = (
            delta.provider_response_count > 0
            and delta.usage_complete_response_count == delta.provider_response_count
        )
        return _VariantAttemptAccounting(
            request_invocations=max(request_delta, delta.provider_response_count, 1 if attempt.provider_failure is not None else 0),
            provider_response_count=delta.provider_response_count,
            successful_decision_count=delta.successful_decision_count,
            observed_model_counts=dict(delta.observed_model_counts),
            observed_model_missing_response_count=delta.observed_model_missing_response_count,
            observed_model_malformed_response_count=delta.observed_model_malformed_response_count,
            usage_complete=usage_complete,
            usage_complete_response_count=delta.usage_complete_response_count,
            usage_missing_response_count=delta.usage_missing_response_count,
            usage_malformed_response_count=delta.usage_malformed_response_count,
            input_usage=delta.input_tokens if usage_complete else None,
            output_usage=delta.output_tokens if usage_complete else None,
            total_usage=delta.total_tokens if usage_complete else None,
            cached_input_usage=delta.cached_input_tokens if usage_complete else None,
        )

    response_count = 0 if attempt.provider_failure is not None else 1
    observed_model = _attempt_observed_model(attempt, default_provider_metadata)
    observed_model_counts = {observed_model: response_count} if observed_model and response_count > 0 else {}
    return _VariantAttemptAccounting(
        request_invocations=max(request_delta, minimum_requests),
        provider_response_count=response_count,
        successful_decision_count=1 if attempt.decision is not None else 0,
        observed_model_counts=observed_model_counts,
        observed_model_missing_response_count=0,
        observed_model_malformed_response_count=0,
        usage_complete=False,
        usage_complete_response_count=0,
        usage_missing_response_count=response_count,
        usage_malformed_response_count=0,
        input_usage=None,
        output_usage=None,
        total_usage=None,
        cached_input_usage=None,
    )


def _validate_observed_model_match(
    accounting: _VariantAttemptAccounting,
    default_provider_metadata: Mapping[str, object],
) -> None:
    requested_model = default_provider_metadata.get("model")
    if not isinstance(requested_model, str) or not requested_model.strip():
        return
    mismatched = sorted(model for model in accounting.observed_model_counts if model != requested_model)
    if mismatched:
        raise ValueError(
            f"observed model mismatch: requested {requested_model}, observed {', '.join(mismatched)}"
        )


def _aggregate_variant_evidence(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    observed_model_counts: Counter[str] = Counter()
    request_invocations = 0
    provider_responses = 0
    successful_decisions = 0
    observed_model_missing_response_count = 0
    observed_model_malformed_response_count = 0
    usage_complete_response_count = 0
    usage_missing_response_count = 0
    usage_malformed_response_count = 0
    usage_complete_attempts = 0
    usage_incomplete_attempts = 0
    input_usage = 0
    output_usage = 0
    total_usage = 0
    cached_input_usage = 0
    cached_reported = False
    for row in rows:
        request_invocations += int(cast(int | str, row["request_invocations"]))
        provider_responses += int(cast(int | str, row["provider_response_count"]))
        successful_decisions += int(cast(int | str, row["successful_decision_count"]))
        observed_model_missing_response_count += int(cast(int | str, row["observed_model_missing_response_count"]))
        observed_model_malformed_response_count += int(cast(int | str, row["observed_model_malformed_response_count"]))
        usage_complete_response_count += int(cast(int | str, row["usage_complete_response_count"]))
        usage_missing_response_count += int(cast(int | str, row["usage_missing_response_count"]))
        usage_malformed_response_count += int(cast(int | str, row["usage_malformed_response_count"]))
        if cast(bool, row["usage_complete"]):
            usage_complete_attempts += 1
        elif int(cast(int | str, row["request_invocations"])) > 0:
            usage_incomplete_attempts += 1
        for model, count in cast(dict[str, int], row["observed_model_counts"]).items():
            observed_model_counts[model] += count
        if row["input_usage"] is not None:
            input_usage += int(cast(int, row["input_usage"]))
            output_usage += int(cast(int, row["output_usage"]))
            total_usage += int(cast(int, row["total_usage"]))
        if row["cached_input_usage"] is not None:
            cached_input_usage += int(cast(int, row["cached_input_usage"]))
            cached_reported = True
    if not (request_invocations >= provider_responses >= successful_decisions):
        raise ValueError("variant accounting invariant failed: invocations >= responses >= successful decisions")
    return {
        "invocations": request_invocations,
        "responses": provider_responses,
        "successful_decisions": successful_decisions,
        "observed_model_counts": dict(sorted(observed_model_counts.items())),
        "observed_model_missing_response_count": observed_model_missing_response_count,
        "observed_model_malformed_response_count": observed_model_malformed_response_count,
        "usage_complete_attempts": usage_complete_attempts,
        "usage_incomplete_attempts": usage_incomplete_attempts,
        "usage_complete_response_count": usage_complete_response_count,
        "usage_missing_response_count": usage_missing_response_count,
        "usage_malformed_response_count": usage_malformed_response_count,
        "input_usage": input_usage if usage_complete_attempts > 0 else None,
        "output_usage": output_usage if usage_complete_attempts > 0 else None,
        "total_usage": total_usage if usage_complete_attempts > 0 else None,
        "cached_input_usage": cached_input_usage if cached_reported else None,
    }


def _variant_prompt_contract_summary() -> dict[str, object]:
    return {
        "primary": {
            "prompt_version": CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
            "allowed_profile_fields": list(CONCURRENT_PRIMARY_PROFILE_FIELDS),
            "excluded_context_fields": list(CONCURRENT_MESSAGE_PRIMARY_EXCLUDED_CONTEXT_FIELDS),
            "peer_context": PeerContext().model_dump(mode="json"),
        },
        "shadow": {
            "prompt_version": CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
            "allowed_profile_fields": list(CONCURRENT_SHADOW_PROFILE_FIELDS),
            "additional_shadow_fields": list(CONCURRENT_MESSAGE_SHADOW_ADDITIONAL_PROFILE_FIELDS),
            "excluded_context_fields": list(CONCURRENT_MESSAGE_PRIMARY_EXCLUDED_CONTEXT_FIELDS),
            "peer_context": PeerContext().model_dump(mode="json"),
            "anti_stereotyping_constraint": (
                "Synthetic Experiment Labels 只用于受控对照，不代表真实身份，不得据此推断人格、价值高低、消费能力优劣或行为必然性。"
            ),
        },
    }


class ConcurrentMessageExperimentRunner:
    """Run the runtime-only concurrent-message tracer and write validation artifacts."""

    def __init__(
        self,
        config: ConcurrentMessageExperimentConfig,
        primary_adapter: LLMDecisionAdapter,
        shadow_adapter: LLMDecisionAdapter,
    ) -> None:
        self.config = config
        self.primary_adapter = primary_adapter
        self.shadow_adapter = shadow_adapter
        self._validate_adapter_contracts()

    def _validate_adapter_contracts(self) -> None:
        primary_leaf, primary_caches = _unwrap_adapter(self.primary_adapter)
        shadow_leaf, shadow_caches = _unwrap_adapter(self.shadow_adapter)
        if self.primary_adapter is self.shadow_adapter or primary_leaf is shadow_leaf:
            raise ValueError("primary and shadow adapters must be distinct instances")
        if type(primary_leaf) is not type(shadow_leaf):
            raise ValueError("primary and shadow adapter leaf types must match")
        if {id(cache) for cache in primary_caches} & {id(cache) for cache in shadow_caches}:
            raise ValueError("primary and shadow adapters must not share a cache instance")
        primary_prompt = _adapter_prompt_version(self.primary_adapter)
        shadow_prompt = _adapter_prompt_version(self.shadow_adapter)
        if primary_prompt != CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION:
            raise ValueError(
                f"primary adapter prompt_version must be {CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION}, got {primary_prompt}"
            )
        if shadow_prompt != CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION:
            raise ValueError(
                f"shadow adapter prompt_version must be {CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION}, got {shadow_prompt}"
            )
        primary_metadata = dict(_adapter_safe_metadata(self.primary_adapter, ProviderLLMConfig()))
        shadow_metadata = dict(_adapter_safe_metadata(self.shadow_adapter, ProviderLLMConfig()))
        primary_metadata.pop("prompt_version", None)
        shadow_metadata.pop("prompt_version", None)
        if primary_metadata != shadow_metadata:
            raise ValueError(
                "primary and shadow adapters must match on provider/model/timeout/retry/sampling metadata"
            )

    def run_and_write(self, output_dir: str | Path) -> Path:
        output_path = Path(output_dir)
        dataset_path = self.config.dataset_dir.resolve()
        if output_path.resolve().is_relative_to(dataset_path):
            raise ValueError("output_dir must be outside dataset_dir")
        if output_path.exists() and any(output_path.iterdir()):
            raise FileExistsError(f"output_dir already exists and is not empty: {output_path}")
        output_path.mkdir(parents=True, exist_ok=True)

        cohort = _ResearchCohortPreparer(
            dataset_dir=self.config.dataset_dir,
            sample_size=self.config.sample_size,
            random_seed=self.config.random_seed,
            model_policy=_TARGET_DELIVERY_RANKING_POLICY,
            holdout_video_ids=(self.config.sample_holdout_video_id,),
        ).prepare()

        if len(cohort.seed_user_ids) > self.config.delivery_capacity:
            raise ValueError(
                f"delivery_capacity {self.config.delivery_capacity} is smaller than the prepared seed union {len(cohort.seed_user_ids)}"
            )

        sample_users = [cohort.users_by_id[user_id] for user_id in cohort.sample_user_ids]
        base_network_by_user = {
            user_id: _log_p95_score(
                cohort.comment_graph.weighted_degree_by_user.get(user_id, 0),
                cohort.comment_graph.p95_weighted_degree,
            )
            for user_id in cohort.users_by_id
        }
        neighbors_by_user = cohort.comment_graph.neighbors_by_user
        exposed_by_message = {message.message_id: set() for message in self.config.messages}
        campaign_engaged_user_ids: set[str] = set()

        candidate_rows: list[dict[str, object]] = []
        pair_rows: list[dict[str, object]] = []
        terminal_rows: list[dict[str, object]] = []
        variant_evidence_rows: list[dict[str, object]] = []
        step_rows: list[_BatchStepSummary] = []
        pair_schedule_position = 0
        primary_provider_metadata = _adapter_safe_metadata(self.primary_adapter, ProviderLLMConfig())
        shadow_provider_metadata = _adapter_safe_metadata(self.shadow_adapter, ProviderLLMConfig())

        for time_step in range(self.config.horizon):
            frozen_campaign_engaged_user_ids = sorted(campaign_engaged_user_ids)
            batch_pair_start = len(pair_rows)
            batch_primary_positive_events: list[dict[str, str]] = []
            batch_plans: list[_PairExecutionPlan] = []
            batch_message_summaries: dict[str, _BatchMessageSummary] = {}

            for message in self.config.messages:
                eligible_user_ids = [
                    user_id for user_id in cohort.sample_user_ids if user_id not in exposed_by_message[message.message_id]
                ]
                ranked_scores = _rank_message_candidates(
                    message=message,
                    users_by_id=cohort.users_by_id,
                    eligible_user_ids=eligible_user_ids,
                    base_network_by_user=base_network_by_user,
                    neighbors_by_user=neighbors_by_user,
                    campaign_engaged_user_ids=campaign_engaged_user_ids,
                )
                selected_scores, selection_reason_by_user = _select_batch_candidates(
                    time_step=time_step,
                    ranked_scores=ranked_scores,
                    seed_user_ids=cohort.seed_user_ids,
                    delivery_capacity=self.config.delivery_capacity,
                )
                ranking_position_by_user = {
                    score.user_id: ranking_position for ranking_position, score in enumerate(ranked_scores, start=1)
                }
                selected_user_ids = [score.user_id for score in selected_scores]
                exposed_by_message[message.message_id].update(selected_user_ids)
                for ranking_position, score in enumerate(ranked_scores, start=1):
                    candidate_rows.append(
                        {
                            "time_step": time_step,
                            "message_id": message.message_id,
                            "user_id": score.user_id,
                            "is_seed": _csv_bool(score.user_id in cohort.seed_user_ids),
                            "selected": _csv_bool(score.user_id in selection_reason_by_user),
                            "selection_reason": selection_reason_by_user.get(score.user_id, ""),
                            "ranking_position": ranking_position,
                            "base_network_relevance": round(score.base_network_relevance, 12),
                            "base_network_relevance_full_precision": _full_precision_cell(score.base_network_relevance),
                            "campaign_engaged_neighbor_count": score.engaged_neighbor_count,
                            "campaign_engaged_neighbor_signal": round(score.engaged_neighbor_signal, 12),
                            "campaign_engaged_neighbor_signal_full_precision": _full_precision_cell(
                                score.engaged_neighbor_signal
                            ),
                            "historical_tag_affinity": CONCURRENT_MESSAGE_HISTORY_AFFINITY,
                            "raw_message_user_fit": round(score.raw_message_user_fit, 12),
                            "raw_message_user_fit_full_precision": _full_precision_cell(score.raw_message_user_fit),
                            "normalized_message_user_fit": round(score.normalized_message_user_fit, 12),
                            "normalized_message_user_fit_full_precision": _full_precision_cell(
                                score.normalized_message_user_fit
                            ),
                            "personalized_delivery_score": round(score.personalized_delivery_score, 12),
                            "personalized_delivery_score_full_precision": _full_precision_cell(
                                score.personalized_delivery_score
                            ),
                        }
                    )
                batch_message_summaries[message.message_id] = {
                    "message_id": message.message_id,
                    "message_title": message.title,
                    "eligible_users": len(eligible_user_ids),
                    "ranked_candidates": len(ranked_scores),
                    "selected_user_ids": list(selected_user_ids),
                    "seed_user_ids": [user_id for user_id in selected_user_ids if user_id in cohort.seed_user_ids],
                    "personalized_topup_user_ids": [
                        user_id for user_id, reason in selection_reason_by_user.items() if reason == "personalized_topup"
                    ],
                    "primary_positive_user_ids": [],
                    "primary_provider_failed_user_ids": [],
                    "shadow_provider_failed_user_ids": [],
                    "below_delivery_capacity": len(ranked_scores) - len(selected_scores),
                    "selection_reason_counts": dict(sorted(Counter(selection_reason_by_user.values()).items())),
                }
                for score in selected_scores:
                    user = cohort.users_by_id[score.user_id]
                    batch_plans.append(
                        _PairExecutionPlan(
                            pair_id=f"{user.user_id}:{message.message_id}:{time_step}",
                            pair_schedule_position=pair_schedule_position,
                            time_step=time_step,
                            message=message,
                            user=user,
                            profile=_primary_variant_profile(user),
                            ranking_position=ranking_position_by_user[user.user_id],
                            selection_reason=selection_reason_by_user[user.user_id],
                            score=score,
                        )
                    )
                    pair_schedule_position += 1

            for plan in batch_plans:
                pair_row, primary_positive_event = self._execute_pair(
                    plan=plan,
                    primary_provider_metadata=primary_provider_metadata,
                    shadow_provider_metadata=shadow_provider_metadata,
                )
                terminal_rows.extend(cast(list[dict[str, object]], pair_row.pop("_terminal_rows")))
                variant_evidence_rows.extend(cast(list[dict[str, object]], pair_row.pop("_variant_evidence")))
                pair_rows.append(pair_row)
                if primary_positive_event is not None:
                    batch_primary_positive_events.append(primary_positive_event)
                    batch_message_summaries[plan.message.message_id]["primary_positive_user_ids"].append(plan.user.user_id)
                if pair_row["primary_status"] == "provider_failed":
                    batch_message_summaries[plan.message.message_id]["primary_provider_failed_user_ids"].append(
                        plan.user.user_id
                    )
                if pair_row["shadow_status"] == "provider_failed":
                    batch_message_summaries[plan.message.message_id]["shadow_provider_failed_user_ids"].append(
                        plan.user.user_id
                    )

            committed_user_ids = sorted({event["user_id"] for event in batch_primary_positive_events})
            campaign_engaged_user_ids.update(committed_user_ids)
            for pair_row in pair_rows[batch_pair_start:]:
                pair_row["campaign_feedback_committed"] = _csv_bool(
                    pair_row["primary_action"] in CONCURRENT_MESSAGE_POSITIVE_ACTIONS
                    and str(pair_row["user_id"]) in committed_user_ids
                )

            step_rows.append(
                {
                    "time_step": time_step,
                    "frozen_campaign_engaged_user_ids": frozen_campaign_engaged_user_ids,
                    "deduplicated_committed_primary_positive_user_ids": committed_user_ids,
                    "messages": [batch_message_summaries[message.message_id] for message in self.config.messages],
                }
            )

        safe_candidate_rows = _safe_runtime_rows(candidate_rows)
        safe_pair_rows = _safe_runtime_rows(pair_rows)
        safe_terminal_rows = _safe_runtime_rows(terminal_rows)
        campaign_diagnostics = ConcurrentCampaignDiagnostics(
            delivery_capacity=self.config.delivery_capacity
        ).build(candidate_rows=safe_candidate_rows, pair_rows=safe_pair_rows)
        validation_summary = self._validation_summary(
            cohort=cohort,
            pair_rows=pair_rows,
            terminal_rows=terminal_rows,
            variant_evidence_rows=variant_evidence_rows,
            step_rows=step_rows,
            diagnostics=campaign_diagnostics,
        )
        write_concurrent_message_report_artifacts(
            output_path,
            title=self.config.report.title,
            config_snapshot=self.config.snapshot(),
            message_snapshot=[message.model_dump(mode="json") for message in self.config.messages],
            sample_users=[user.model_dump(mode="json") for user in sample_users],
            sample_audit=cohort.sample_audit,
            candidate_rows=safe_candidate_rows,
            pair_rows=safe_pair_rows,
            terminal_rows=safe_terminal_rows,
            step_rows=list(step_rows),
            validation_summary=validation_summary,
            campaign_diagnostics=campaign_diagnostics.payload,
        )
        return output_path

    def _execute_variant(
        self,
        *,
        adapter: LLMDecisionAdapter,
        context: _VariantDecisionContext,
        pair_schedule_position: int,
        time_step: int,
        message_id: str,
        default_provider_metadata: Mapping[str, object],
    ) -> tuple[_RuntimeDecisionAttempt, _VariantAttemptAccounting]:
        baseline = _adapter_runtime_baseline(adapter)
        attempt = _attempt_runtime_decision(
            adapter=adapter,
            post=context.post,
            profile=context.profile,
            peer_context=context.peer_context,
            platform_context=context.platform_context,
            time_step=time_step,
            schedule_position=pair_schedule_position,
            video_id=message_id,
            provider_metadata=default_provider_metadata,
        )
        accounting = _variant_attempt_accounting(
            adapter=adapter,
            baseline=baseline,
            attempt=attempt,
            default_provider_metadata=default_provider_metadata,
        )
        _validate_observed_model_match(accounting, default_provider_metadata)
        return attempt, accounting

    def _execute_pair(
        self,
        *,
        plan: _PairExecutionPlan,
        primary_provider_metadata: Mapping[str, object],
        shadow_provider_metadata: Mapping[str, object],
    ) -> tuple[dict[str, object], dict[str, str] | None]:
        primary_context = _primary_variant_context(plan)
        shadow_context = _shadow_variant_context(plan)
        primary_attempt, primary_accounting = self._execute_variant(
            adapter=self.primary_adapter,
            context=primary_context,
            pair_schedule_position=plan.pair_schedule_position,
            time_step=plan.time_step,
            message_id=plan.message.message_id,
            default_provider_metadata=primary_provider_metadata,
        )
        shadow_attempt, shadow_accounting = self._execute_variant(
            adapter=self.shadow_adapter,
            context=shadow_context,
            pair_schedule_position=plan.pair_schedule_position,
            time_step=plan.time_step,
            message_id=plan.message.message_id,
            default_provider_metadata=shadow_provider_metadata,
        )
        primary_terminal_row, primary_positive_event, primary_variant_evidence = self._terminal_row(
            pair_id=plan.pair_id,
            pair_schedule_position=plan.pair_schedule_position,
            time_step=plan.time_step,
            message_id=plan.message.message_id,
            user_id=plan.user.user_id,
            context=primary_context,
            attempt=primary_attempt,
            accounting=primary_accounting,
            default_provider_metadata=primary_provider_metadata,
        )
        shadow_terminal_row, _, shadow_variant_evidence = self._terminal_row(
            pair_id=plan.pair_id,
            pair_schedule_position=plan.pair_schedule_position,
            time_step=plan.time_step,
            message_id=plan.message.message_id,
            user_id=plan.user.user_id,
            context=shadow_context,
            attempt=shadow_attempt,
            accounting=shadow_accounting,
            default_provider_metadata=shadow_provider_metadata,
        )
        pair_row = {
            "pair_id": plan.pair_id,
            "pair_schedule_position": plan.pair_schedule_position,
            "time_step": plan.time_step,
            "message_id": plan.message.message_id,
            "message_title": plan.message.title,
            "user_id": plan.user.user_id,
            "latent_class": str(plan.user.latent_attributes["latent_class"]),
            "shadow_gender": str(plan.user.latent_attributes["latent_gender"]),
            "shadow_age": str(plan.user.latent_attributes["latent_age"]),
            "shadow_education": str(plan.user.latent_attributes["latent_education"]),
            "shadow_monthly_income": str(plan.user.latent_attributes["latent_monthly_income"]),
            "is_seed": _csv_bool(plan.user.is_seed),
            "selection_reason": plan.selection_reason,
            "ranking_position": plan.ranking_position,
            "base_network_relevance": round(plan.score.base_network_relevance, 12),
            "base_network_relevance_full_precision": _full_precision_cell(plan.score.base_network_relevance),
            "campaign_engaged_neighbor_count": plan.score.engaged_neighbor_count,
            "campaign_engaged_neighbor_signal": round(plan.score.engaged_neighbor_signal, 12),
            "campaign_engaged_neighbor_signal_full_precision": _full_precision_cell(
                plan.score.engaged_neighbor_signal
            ),
            "historical_tag_affinity": CONCURRENT_MESSAGE_HISTORY_AFFINITY,
            "raw_message_user_fit": round(plan.score.raw_message_user_fit, 12),
            "raw_message_user_fit_full_precision": _full_precision_cell(plan.score.raw_message_user_fit),
            "normalized_message_user_fit": round(plan.score.normalized_message_user_fit, 12),
            "normalized_message_user_fit_full_precision": _full_precision_cell(
                plan.score.normalized_message_user_fit
            ),
            "personalized_delivery_score": round(plan.score.personalized_delivery_score, 12),
            "personalized_delivery_score_full_precision": _full_precision_cell(
                plan.score.personalized_delivery_score
            ),
            "primary_status": primary_terminal_row["terminal_status"],
            "primary_action": primary_terminal_row["action"],
            "primary_probability": primary_terminal_row["probability"],
            "primary_confidence": primary_terminal_row["confidence"],
            "primary_reason": primary_terminal_row["reason"],
            "primary_decision_source": primary_terminal_row["decision_source"],
            "primary_prompt_version": primary_terminal_row["prompt_version"],
            "primary_provider_metadata": primary_terminal_row["provider_metadata"],
            "shadow_status": shadow_terminal_row["terminal_status"],
            "shadow_action": shadow_terminal_row["action"],
            "shadow_probability": shadow_terminal_row["probability"],
            "shadow_confidence": shadow_terminal_row["confidence"],
            "shadow_reason": shadow_terminal_row["reason"],
            "shadow_decision_source": shadow_terminal_row["decision_source"],
            "shadow_prompt_version": shadow_terminal_row["prompt_version"],
            "shadow_provider_metadata": shadow_terminal_row["provider_metadata"],
            "campaign_feedback_committed": "false",
            "pair_terminal_coverage": _csv_bool(True),
            "paired_decision_coverage": _csv_bool(
                primary_terminal_row["terminal_status"] == "succeeded"
                and shadow_terminal_row["terminal_status"] == "succeeded"
            ),
            "_terminal_rows": [primary_terminal_row, shadow_terminal_row],
            "_variant_evidence": [primary_variant_evidence, shadow_variant_evidence],
        }
        return pair_row, primary_positive_event

    def _terminal_row(
        self,
        *,
        pair_id: str,
        pair_schedule_position: int,
        time_step: int,
        message_id: str,
        user_id: str,
        context: _VariantDecisionContext,
        attempt: _RuntimeDecisionAttempt,
        accounting: _VariantAttemptAccounting,
        default_provider_metadata: Mapping[str, object],
    ) -> tuple[dict[str, object], dict[str, str] | None, dict[str, object]]:
        decision_variant = context.decision_variant
        decision_input = context.decision_input(time_step=time_step)
        context_source_key = f"{pair_id}:{decision_variant}"
        prompt_field_inclusion = attempt.prompt_field_inclusion or {}
        profile_payload = decision_profile_payload(context.profile)
        peer_context_payload = context.peer_context.model_dump(mode="json")
        variant_evidence = {
            "terminal_row_id": f"{pair_id}:{decision_variant}",
            "pair_id": pair_id,
            "message_id": message_id,
            "user_id": user_id,
            "decision_variant": decision_variant,
            "prompt_version": context.prompt_token,
            "context_source_key": context_source_key,
            "cache_key": decision_input.cache_key(),
            "profile_payload": profile_payload,
            "peer_context_payload": peer_context_payload,
            "prompt_field_inclusion": prompt_field_inclusion,
            "request_invocations": accounting.request_invocations,
            "provider_response_count": accounting.provider_response_count,
            "successful_decision_count": accounting.successful_decision_count,
            "observed_model_counts": accounting.observed_model_counts,
            "observed_model_missing_response_count": accounting.observed_model_missing_response_count,
            "observed_model_malformed_response_count": accounting.observed_model_malformed_response_count,
            "usage_complete": accounting.usage_complete,
            "usage_complete_response_count": accounting.usage_complete_response_count,
            "usage_missing_response_count": accounting.usage_missing_response_count,
            "usage_malformed_response_count": accounting.usage_malformed_response_count,
            "input_usage": accounting.input_usage,
            "output_usage": accounting.output_usage,
            "total_usage": accounting.total_usage,
            "cached_input_usage": accounting.cached_input_usage,
        }
        shared_row_fields = {
            "prompt_version": context.prompt_token,
            "context_source_key": context_source_key,
            "cache_key": decision_input.cache_key(),
            "context_profile_payload": _json_cell(profile_payload),
            "peer_context_payload": _json_cell(peer_context_payload),
            "prompt_field_inclusion": _json_cell(prompt_field_inclusion),
            "request_invocations": accounting.request_invocations,
            "provider_response_count": accounting.provider_response_count,
            "successful_decision_count": accounting.successful_decision_count,
            "observed_model_counts": _json_cell(accounting.observed_model_counts),
            "observed_model_missing_response_count": accounting.observed_model_missing_response_count,
            "observed_model_malformed_response_count": accounting.observed_model_malformed_response_count,
            "usage_complete": _csv_bool(accounting.usage_complete),
            "usage_complete_response_count": accounting.usage_complete_response_count,
            "usage_missing_response_count": accounting.usage_missing_response_count,
            "usage_malformed_response_count": accounting.usage_malformed_response_count,
            "input_usage": "" if accounting.input_usage is None else accounting.input_usage,
            "output_usage": "" if accounting.output_usage is None else accounting.output_usage,
            "total_usage": "" if accounting.total_usage is None else accounting.total_usage,
            "cached_input_usage": "" if accounting.cached_input_usage is None else accounting.cached_input_usage,
        }
        provider_failure = attempt.provider_failure
        decision = attempt.decision
        if provider_failure is not None:
            terminal_row = {
                "terminal_row_id": f"{pair_id}:{decision_variant}",
                "pair_id": pair_id,
                "pair_schedule_position": pair_schedule_position,
                "time_step": time_step,
                "message_id": message_id,
                "user_id": user_id,
                "decision_variant": decision_variant,
                **shared_row_fields,
                "terminal_status": "provider_failed",
                "provider_status": "provider_failed",
                "engage": "",
                "probability": "",
                "confidence": "",
                "action": "",
                "reason": "",
                "decision_source": "",
                "failure_type": provider_failure["failure_type"],
                "provider_metadata": _json_cell(
                    allowlisted_provider_evidence(json.loads(cast(str, provider_failure["provider_metadata"])))
                ),
            }
            variant_evidence["terminal_status"] = "provider_failed"
            variant_evidence["provider_status"] = "provider_failed"
            return terminal_row, None, variant_evidence

        assert isinstance(decision, EngageDecision)
        terminal_row = {
            "terminal_row_id": f"{pair_id}:{decision_variant}",
            "pair_id": pair_id,
            "pair_schedule_position": pair_schedule_position,
            "time_step": time_step,
            "message_id": message_id,
            "user_id": user_id,
            "decision_variant": decision_variant,
            **shared_row_fields,
            "terminal_status": "succeeded",
            "provider_status": "succeeded",
            "engage": _csv_bool(decision.engage),
            "probability": decision.probability,
            "confidence": decision.confidence,
            "action": decision.action,
            "reason": decision.reason,
            "decision_source": decision.decision_source,
            "failure_type": "",
            "provider_metadata": _json_cell(
                allowlisted_provider_evidence(
                    decision.provider_metadata if decision.provider_metadata is not None else default_provider_metadata
                )
            ),
        }
        variant_evidence.update(
            {
                "terminal_status": "succeeded",
                "provider_status": "succeeded",
                "action": decision.action,
                "decision_source": decision.decision_source,
            }
        )
        positive_event = (
            {"message_id": message_id, "user_id": user_id, "action": decision.action}
            if decision_variant == "primary" and decision.action in CONCURRENT_MESSAGE_POSITIVE_ACTIONS
            else None
        )
        return terminal_row, positive_event, variant_evidence

    def _validation_summary(
        self,
        *,
        cohort: _PreparedResearchCohort,
        pair_rows: Sequence[Mapping[str, object]],
        terminal_rows: Sequence[Mapping[str, object]],
        variant_evidence_rows: Sequence[Mapping[str, object]],
        step_rows: Sequence[_BatchStepSummary],
        diagnostics: ConcurrentCampaignDiagnosticArtifacts,
    ) -> dict[str, object]:
        del cohort, pair_rows
        funnel = diagnostics.payload["campaign_funnel"]
        sensitivity = diagnostics.payload["demographic_decision_sensitivity"]
        assert isinstance(funnel, Mapping)
        assert isinstance(sensitivity, Mapping)
        funnel_primary = funnel["primary"]
        funnel_shadow = funnel["shadow"]
        funnel_per_message = funnel["per_message"]
        assert isinstance(funnel_primary, Mapping)
        assert isinstance(funnel_shadow, Mapping)
        assert isinstance(funnel_per_message, Mapping)
        per_message_segments = {
            message.message_id: message.intended_audience_segment for message in self.config.messages
        }
        primary_variant_rows = [row for row in variant_evidence_rows if row["decision_variant"] == "primary"]
        shadow_variant_rows = [row for row in variant_evidence_rows if row["decision_variant"] == "shadow"]
        provider_accounting = {
            "primary": _aggregate_variant_evidence(primary_variant_rows),
            "shadow": _aggregate_variant_evidence(shadow_variant_rows),
            "total": _aggregate_variant_evidence(variant_evidence_rows),
        }
        return {
            "schema_version": CONCURRENT_MESSAGE_VALIDATION_VERSION,
            "runtime_version": CONCURRENT_MESSAGE_RUNTIME_VERSION,
            "sampling_method": SEED_FIRST_SAMPLING_METHOD,
            "sampling_status": VALIDATION_RUN_STATUS,
            "descriptive_only": True,
            "non_causal": True,
            "production_deploy_eligible": False,
            "configuration": self.config.snapshot(),
            "messages": [message.model_dump(mode="json") for message in self.config.messages],
            "prompt_contract": _variant_prompt_contract_summary(),
            "variant_provider_accounting": provider_accounting,
            "campaign_diagnostics_schema_version": diagnostics.payload["schema_version"],
            "campaign_diagnostics_summary": diagnostics.summary,
            "counts": {
                "sample_users": funnel["sample_users"],
                "messages": funnel["message_count"],
                "eligible_user_message_pairs": funnel["eligible_user_message_pairs"],
                "actual_exposures": funnel["actual_exposures"],
                "distinct_exposed_users": funnel["distinct_exposed_users"],
                "primary_attempted": funnel_primary["attempted"],
                "primary_successes": funnel_primary["succeeded"],
                "primary_failures": funnel_primary["provider_failed"],
                "shadow_attempted": funnel_shadow["attempted"],
                "shadow_successes": funnel_shadow["succeeded"],
                "shadow_failures": funnel_shadow["provider_failed"],
                "terminal_rows": len(terminal_rows),
                "pair_terminal_coverage": sensitivity["pair_terminal_coverage"]["value"],
                "paired_decision_coverage": sensitivity["paired_decision_coverage"]["value"],
            },
            "campaign_exposure_coverage": funnel["campaign_exposure_coverage"],
            "per_message": {
                message_id: {
                    "message_title": message_payload["message_title"],
                    "intended_audience_segment": per_message_segments[message_id],
                    "exposures": message_payload["exposures"],
                    "primary_successes": message_payload["primary_successes"],
                    "primary_failures": message_payload["primary_failures"],
                    "shadow_successes": message_payload["shadow_successes"],
                    "shadow_failures": message_payload["shadow_failures"],
                    "below_delivery_capacity": message_payload["below_delivery_capacity"],
                }
                for message_id, message_payload in funnel_per_message.items()
            },
            "steps": list(step_rows),
        }

    def _render_report(
        self,
        *,
        validation_summary: Mapping[str, object],
        pair_rows: Sequence[Mapping[str, object]],
        step_rows: Sequence[_BatchStepSummary],
        diagnostics: Mapping[str, object],
    ) -> str:
        counts = validation_summary["counts"]
        assert isinstance(counts, Mapping)
        per_message = validation_summary["per_message"]
        assert isinstance(per_message, Mapping)
        prompt_contract = validation_summary["prompt_contract"]
        assert isinstance(prompt_contract, Mapping)
        provider_accounting = validation_summary["variant_provider_accounting"]
        assert isinstance(provider_accounting, Mapping)
        funnel = diagnostics["campaign_funnel"]
        allocation = diagnostics["message_allocation"]
        response = diagnostics["primary_audience_response"]
        feedback = diagnostics["campaign_feedback_effect"]
        sensitivity = diagnostics["demographic_decision_sensitivity"]
        assert isinstance(funnel, Mapping)
        assert isinstance(allocation, Mapping)
        assert isinstance(response, Mapping)
        assert isinstance(feedback, Mapping)
        assert isinstance(sensitivity, Mapping)
        feedback_overall = feedback["overall"]
        assert isinstance(feedback_overall, Mapping)
        reason_screening = sensitivity["reason_screening"]
        assert isinstance(reason_screening, Mapping)
        summary_items = [
            ("Research sample", str(counts["sample_users"])),
            ("Eligible user-message pairs", str(counts["eligible_user_message_pairs"])),
            ("Actual exposures", str(counts["actual_exposures"])),
            ("Primary success / fail", f"{counts['primary_successes']} / {counts['primary_failures']}"),
            ("Shadow success / fail", f"{counts['shadow_successes']} / {counts['shadow_failures']}"),
            ("Changed message-batches", str(feedback_overall["changed_message_batch_count"])),
            ("Pair terminal coverage", f"{float(counts['pair_terminal_coverage']):.2f}"),
            ("Paired decision coverage", f"{float(counts['paired_decision_coverage']):.2f}"),
        ]
        message_rows_html = "".join(
            "<tr>"
            f"<td>{html.escape(message_id)}</td>"
            f"<td>{html.escape(str(message_payload['message_title']))}</td>"
            f"<td>{html.escape(str(message_payload['intended_audience_segment']))}</td>"
            f"<td>{message_payload['exposures']}</td>"
            f"<td>{message_payload['primary_successes']}</td>"
            f"<td>{message_payload['primary_failures']}</td>"
            f"<td>{message_payload['shadow_successes']}</td>"
            f"<td>{message_payload['shadow_failures']}</td>"
            f"<td>{message_payload['below_delivery_capacity']}</td>"
            "</tr>"
            for message_id, message_payload in per_message.items()
        )
        prompt_contract_rows_html = "".join(
            "<tr>"
            f"<td>{html.escape(str(variant))}</td>"
            f"<td>{html.escape(str(payload['prompt_version']))}</td>"
            f"<td>{html.escape(', '.join(cast(list[str], payload['allowed_profile_fields'])))}</td>"
            f"<td>{html.escape(', '.join(cast(list[str], payload['excluded_context_fields'])))}</td>"
            f"<td>{html.escape(_json_cell(payload['peer_context']))}</td>"
            "</tr>"
            for variant, payload in prompt_contract.items()
        )
        accounting_rows_html = "".join(
            "<tr>"
            f"<td>{html.escape(str(variant))}</td>"
            f"<td>{payload['invocations']}</td>"
            f"<td>{payload['responses']}</td>"
            f"<td>{payload['successful_decisions']}</td>"
            f"<td>{payload['usage_complete_attempts']}</td>"
            f"<td>{payload['usage_incomplete_attempts']}</td>"
            f"<td>{html.escape(_json_cell(payload['observed_model_counts']))}</td>"
            f"<td>{payload['input_usage'] if payload['input_usage'] is not None else ''}</td>"
            f"<td>{payload['output_usage'] if payload['output_usage'] is not None else ''}</td>"
            f"<td>{payload['total_usage'] if payload['total_usage'] is not None else ''}</td>"
            "</tr>"
            for variant, payload in provider_accounting.items()
        )
        pair_rows_html = "".join(
            "<tr>"
            f"<td>{row['time_step']}</td>"
            f"<td>{html.escape(str(row['message_id']))}</td>"
            f"<td>{html.escape(str(row['user_id']))}</td>"
            f"<td>{html.escape(str(row['latent_class']))}</td>"
            f"<td>{row['ranking_position']}</td>"
            f"<td>{html.escape(str(row['selection_reason']))}</td>"
            f"<td>{html.escape(str(row['personalized_delivery_score_full_precision']))}</td>"
            f"<td>{row['primary_status']}</td>"
            f"<td>{html.escape(str(row['primary_action']))}</td>"
            f"<td>{html.escape(str(row['primary_prompt_version']))}</td>"
            f"<td>{row['shadow_status']}</td>"
            f"<td>{html.escape(str(row['shadow_action']))}</td>"
            f"<td>{html.escape(str(row['shadow_prompt_version']))}</td>"
            f"<td>{row['campaign_feedback_committed']}</td>"
            "</tr>"
            for row in pair_rows
        )
        step_rows_html = "".join(
            "<tr>"
            f"<td>{step['time_step']}</td>"
            f"<td>{html.escape(', '.join(step['frozen_campaign_engaged_user_ids']))}</td>"
            f"<td>{html.escape(', '.join(step['deduplicated_committed_primary_positive_user_ids']))}</td>"
            f"<td>{html.escape(' | '.join(_step_message_summary(message) for message in step['messages']))}</td>"
            "</tr>"
            for step in step_rows
        )
        funnel_per_message_capacity = funnel["per_message_capacity"]
        assert isinstance(funnel_per_message_capacity, Mapping)
        funnel_rows_html = "".join(
            "<tr>"
            f"<td>{html.escape(label)}</td>"
            f"<td>{html.escape(value)}</td>"
            "</tr>"
            for label, value in (
                ("Research sample users", f"{funnel['sample_users']:,}"),
                ("Eligible user-message pairs", f"{funnel['eligible_user_message_pairs']:,}"),
                ("Actual exposures", f"{funnel['actual_exposures']:,}"),
                (
                    "Per-message capacity",
                    f"{funnel_per_message_capacity['per_batch']} per batch x {funnel_per_message_capacity['batches']} batches = {funnel_per_message_capacity['per_message_total']}",
                ),
                ("Distinct exposed users", f"{funnel['distinct_exposed_users']:,}"),
                (
                    "Primary attempted / succeeded / failed",
                    f"{funnel['primary']['attempted']} / {funnel['primary']['succeeded']} / {funnel['primary']['provider_failed']}",
                ),
                (
                    "Shadow attempted / succeeded / failed",
                    f"{funnel['shadow']['attempted']} / {funnel['shadow']['succeeded']} / {funnel['shadow']['provider_failed']}",
                ),
                ("Below-delivery-capacity pairs", f"{funnel['below_delivery_capacity_pairs']:,}"),
            )
        )
        coverage_rows_html = "".join(
            "<tr>"
            f"<td>{html.escape(message_count)} message(s)</td>"
            f"<td>{count}</td>"
            "</tr>"
            for message_count, count in cast(Mapping[str, object], funnel["campaign_exposure_coverage"]).items()
        )
        allocation_batches = cast(list[dict[str, object]], allocation["batch_capacity"])
        allocation_rows_html = "".join(
            "<tr>"
            f"<td>{html.escape(str(row['message_id']))}</td>"
            f"<td>{row['time_step']}</td>"
            f"<td>{row['configured_capacity']}</td>"
            f"<td>{row['eligible_users']}</td>"
            f"<td>{row['selected_pairs']}</td>"
            f"<td>{row['cumulative_pairs']}</td>"
            f"<td>{row['below_delivery_capacity']}</td>"
            f"<td>{html.escape(', '.join(cast(list[str], row['actual_selected_user_ids'])))}</td>"
            "</tr>"
            for row in allocation_batches
        )
        overlap = cast(Mapping[str, object], allocation["overlap"])
        overlap_rows_html = "".join(
            "<tr>"
            f"<td>{html.escape(str(row['left_message_id']))}</td>"
            f"<td>{html.escape(str(row['right_message_id']))}</td>"
            f"<td>{row['overlap_count']}</td>"
            f"<td>{html.escape(', '.join(cast(list[str], row['overlap_user_ids'])))}</td>"
            "</tr>"
            for row in cast(list[dict[str, object]], overlap["pairwise"])
        )
        class_matrix = cast(Mapping[str, object], allocation["class_message_matrix"])
        class_matrix_headers = "".join(f"<th>{html.escape(message_id)}</th>" for message_id in per_message.keys())
        class_matrix_rows_html = "".join(
            "<tr>"
            f"<td>{html.escape(latent_class)}</td>"
            + "".join(f"<td>{cast(Mapping[str, object], counts_by_message)[message_id]}</td>" for message_id in per_message.keys())
            + "</tr>"
            for latent_class, counts_by_message in class_matrix.items()
        )
        fit_distribution = cast(Mapping[str, Mapping[str, object]], allocation["fit_distribution_by_message"])
        fit_rows_html = "".join(
            "<tr>"
            f"<td>{html.escape(message_id)}</td>"
            f"<td>{html.escape(str(payload['message_title']))}</td>"
            f"<td>{payload['selected_pairs']}</td>"
            f"<td>{cast(Mapping[str, object], payload['raw_message_user_fit'])['min']}</td>"
            f"<td>{cast(Mapping[str, object], payload['raw_message_user_fit'])['mean']}</td>"
            f"<td>{cast(Mapping[str, object], payload['raw_message_user_fit'])['max']}</td>"
            f"<td>{cast(Mapping[str, object], payload['normalized_message_user_fit'])['min']}</td>"
            f"<td>{cast(Mapping[str, object], payload['normalized_message_user_fit'])['mean']}</td>"
            f"<td>{cast(Mapping[str, object], payload['normalized_message_user_fit'])['max']}</td>"
            "</tr>"
            for message_id, payload in fit_distribution.items()
        )
        selected_pair_rows_html = "".join(
            "<tr>"
            f"<td>{row['time_step']}</td>"
            f"<td>{html.escape(str(row['message_id']))}</td>"
            f"<td>{html.escape(str(row['user_id']))}</td>"
            f"<td>{html.escape(str(row['latent_class']))}</td>"
            f"<td>{html.escape(str(row['selection_reason']))}</td>"
            f"<td>{row['ranking_position']}</td>"
            f"<td>{html.escape(str(row['base_network_component_full_precision']))}</td>"
            f"<td>{html.escape(str(row['campaign_feedback_component_full_precision']))}</td>"
            f"<td>{html.escape(str(row['message_user_fit_component_full_precision']))}</td>"
            f"<td>{html.escape(str(row['personalized_delivery_score_full_precision']))}</td>"
            "</tr>"
            for row in cast(list[dict[str, object]], allocation["selected_pair_details"])
        )
        response_rows_html = "".join(
            "<tr>"
            f"<td>{html.escape(message_id)}</td>"
            f"<td>{html.escape(str(payload['message_title']))}</td>"
            f"<td>{cast(Mapping[str, object], payload['action_counts'])['like']}</td>"
            f"<td>{cast(Mapping[str, object], payload['action_counts'])['comment']}</td>"
            f"<td>{cast(Mapping[str, object], payload['action_counts'])['share']}</td>"
            f"<td>{cast(Mapping[str, object], payload['action_counts'])['ignore']}</td>"
            f"<td>{cast(Mapping[str, object], payload['action_counts'])['provider_failed']}</td>"
            f"<td>{cast(Mapping[str, object], payload['exposure_engagement_rate'])['numerator']} / {cast(Mapping[str, object], payload['exposure_engagement_rate'])['denominator']} = {cast(Mapping[str, object], payload['exposure_engagement_rate'])['value']}</td>"
            f"<td>{cast(Mapping[str, object], payload['decision_engagement_rate'])['numerator']} / {cast(Mapping[str, object], payload['decision_engagement_rate'])['denominator']} = {cast(Mapping[str, object], payload['decision_engagement_rate'])['value']}</td>"
            "</tr>"
            for message_id, payload in cast(Mapping[str, Mapping[str, object]], response["per_message"]).items()
        )
        feedback_rows_html = "".join(
            "<tr>"
            f"<td>{html.escape(message_id)}</td>"
            f"<td>{batch['time_step']}</td>"
            f"<td>{batch['eligible_users']}</td>"
            f"<td>{batch['top_count']}</td>"
            f"<td>{batch['top_overlap_count']}</td>"
            f"<td>{html.escape(', '.join(cast(list[str], batch['feedback_added_user_ids'])))}</td>"
            f"<td>{html.escape(', '.join(cast(list[str], batch['feedback_removed_user_ids'])))}</td>"
            f"<td>{'true' if batch['top_selection_changed'] else 'false'}</td>"
            "</tr>"
            for message_id, payload in cast(Mapping[str, object], feedback["per_message"]).items()
            for batch in cast(list[dict[str, object]], cast(Mapping[str, object], payload)["batches"])
        )
        sensitivity_summary_rows_html = "".join(
            "<tr>"
            f"<td>{html.escape(label)}</td>"
            f"<td>{html.escape(value)}</td>"
            "</tr>"
            for label, value in (
                (
                    "Pair terminal coverage",
                    f"{sensitivity['pair_terminal_coverage']['numerator']} / {sensitivity['pair_terminal_coverage']['denominator']} = {sensitivity['pair_terminal_coverage']['value']}",
                ),
                (
                    "Paired decision coverage",
                    f"{sensitivity['paired_decision_coverage']['numerator']} / {sensitivity['paired_decision_coverage']['denominator']} = {sensitivity['paired_decision_coverage']['value']}",
                ),
                ("Dual-success pairs", str(sensitivity['dual_success_pair_count'])),
                (
                    "Engage disagreement rate",
                    f"{sensitivity['engage_disagreement_rate']['numerator']} / {sensitivity['engage_disagreement_rate']['denominator']} = {sensitivity['engage_disagreement_rate']['value']}",
                ),
                (
                    "Mean absolute probability delta",
                    f"{sensitivity['mean_absolute_probability_delta']['absolute_delta_sum']} / {sensitivity['mean_absolute_probability_delta']['denominator']} = {sensitivity['mean_absolute_probability_delta']['value']}",
                ),
                (
                    "Flagged shadow reasons",
                    f"{reason_screening['flagged_pair_count']} / {reason_screening['screened_non_empty_shadow_reasons']}",
                ),
            )
        )
        transition_rows_html = "".join(
            "<tr>"
            f"<td>{html.escape(transition)}</td>"
            f"<td>{count}</td>"
            "</tr>"
            for transition, count in cast(Mapping[str, object], sensitivity["action_transition_counts"]).items()
        )
        flagged_pairs_rows_html = "".join(
            "<tr>"
            f"<td>{html.escape(str(row['pair_id']))}</td>"
            f"<td>{html.escape(str(row['message_id']))}</td>"
            f"<td>{html.escape(str(row['user_id']))}</td>"
            f"<td>{html.escape(str(row['shadow_reason']))}</td>"
            f"<td>{html.escape(_json_cell(row['matched_spans']))}</td>"
            "</tr>"
            for row in cast(list[dict[str, object]], reason_screening["flagged_pairs"])
        )
        summary_html = "".join(
            f"<div class=\"metric\"><span>{html.escape(label)}</span><strong>{html.escape(value)}</strong></div>"
            for label, value in summary_items
        )
        return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(self.config.report.title)}</title>
  <style>
    :root {{ color-scheme: light; }}
    body {{ margin: 0; font: 14px/1.5 -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; color: #102033; background: #f6f8fb; }}
    main {{ max-width: 1360px; margin: 0 auto; padding: 32px 20px 48px; }}
    h1, h2 {{ margin: 0 0 12px; }}
    h3 {{ margin: 18px 0 8px; font-size: 15px; }}
    p {{ margin: 0 0 12px; }}
    .banner {{ padding: 18px 20px; border: 1px solid #d8e1ee; background: #fff; border-radius: 8px; }}
    .metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 20px 0 28px; }}
    .metric {{ padding: 14px 16px; border: 1px solid #d8e1ee; background: #fff; border-radius: 8px; }}
    .metric span {{ display: block; color: #526173; font-size: 12px; }}
    .metric strong {{ display: block; margin-top: 6px; font-size: 22px; font-weight: 600; }}
    section {{ margin-top: 28px; padding: 20px; border: 1px solid #d8e1ee; background: #fff; border-radius: 8px; }}
    table {{ width: 100%; border-collapse: collapse; min-width: 760px; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid #e4eaf3; text-align: left; vertical-align: top; }}
    th {{ font-size: 12px; color: #526173; text-transform: uppercase; letter-spacing: .04em; }}
    .table-wrap {{ overflow-x: auto; }}
    .muted {{ color: #526173; }}
  </style>
</head>
<body>
  <main>
    <div class="banner">
      <h1>{html.escape(self.config.report.title)}</h1>
      <p>This tracer is validation-only, descriptive, and non-causal. It is not a formal release artifact and cannot be deployed.</p>
      <p class="muted">The diagnostics below are rebuilt from persisted candidate and pair rows. They do not call the adapter, do not advance runtime state, and do not claim a causal winner.</p>
    </div>
    <div class="metrics">{summary_html}</div>
    <section>
      <h2>Campaign Funnel</h2>
      <p class="muted">Counts are rebuilt from runtime candidate/pair rows rather than handwritten aggregates.</p>
      <div class="table-wrap">
        <table>
          <tbody>{funnel_rows_html}</tbody>
        </table>
      </div>
      <h3>Exposure Coverage</h3>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>Coverage</th><th>User count</th></tr>
          </thead>
          <tbody>{coverage_rows_html}</tbody>
        </table>
      </div>
    </section>
    <section>
      <h2>Message Allocation</h2>
      <p class="muted">Allocation comparisons are descriptive only. Overlaps and fit summaries reflect deterministic queue assignment, not causal content effectiveness.</p>
      <h3>Batch Capacity</h3>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>Message</th><th>Batch</th><th>Configured capacity</th><th>Eligible users</th><th>Selected pairs</th><th>Cumulative pairs</th><th>Below capacity</th><th>Actual selected users</th></tr>
          </thead>
          <tbody>{allocation_rows_html}</tbody>
        </table>
      </div>
      <h3>Audience Overlap</h3>
      <p class="muted">Distinct union: {overlap['distinct_union_count']}; three-way intersection: {overlap['three_way_intersection_count']}.</p>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>Left message</th><th>Right message</th><th>Overlap count</th><th>User IDs</th></tr>
          </thead>
          <tbody>{overlap_rows_html}</tbody>
        </table>
      </div>
      <h3>Class x Message Exposure Matrix</h3>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>Latent class</th>{class_matrix_headers}</tr>
          </thead>
          <tbody>{class_matrix_rows_html}</tbody>
        </table>
      </div>
      <h3>Fit Distribution</h3>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>Message</th><th>Title</th><th>Selected pairs</th><th>Raw fit min</th><th>Raw fit mean</th><th>Raw fit max</th><th>Normalized fit min</th><th>Normalized fit mean</th><th>Normalized fit max</th></tr>
          </thead>
          <tbody>{fit_rows_html}</tbody>
        </table>
      </div>
      <h3>Selected Pair Score Components</h3>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>Batch</th><th>Message</th><th>User</th><th>Class</th><th>Selection</th><th>Rank</th><th>Base component</th><th>Feedback component</th><th>Fit component</th><th>Full score</th></tr>
          </thead>
          <tbody>{selected_pair_rows_html}</tbody>
        </table>
      </div>
    </section>
    <section>
      <h2>Primary Audience Response</h2>
      <p class="muted">Per-message action counts and rates are descriptive only. They do not rank messages as winners.</p>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>Message</th><th>Title</th><th>Like</th><th>Comment</th><th>Share</th><th>Ignore</th><th>Provider failed</th><th>Positive actions / exposures</th><th>Positive actions / successful Primary decisions</th></tr>
          </thead>
          <tbody>{response_rows_html}</tbody>
        </table>
      </div>
    </section>
    <section>
      <h2>Campaign Feedback Effect</h2>
      <p class="muted">No-feedback diagnostics reuse the same frozen candidate evidence, full-precision ranking, and user_id tie-break, while setting only the campaign feedback component to 0.</p>
      <p class="muted">Changed message-batches: {feedback_overall['changed_message_batch_count']}; distinct changed users: {len(cast(list[str], feedback_overall['distinct_changed_user_ids']))}.</p>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>Message</th><th>Batch</th><th>Eligible users</th><th>Top count</th><th>Top overlap</th><th>Feedback-added users</th><th>Feedback-removed users</th><th>Changed</th></tr>
          </thead>
          <tbody>{feedback_rows_html}</tbody>
        </table>
      </div>
    </section>
    <section>
      <h2>Demographic Decision Sensitivity</h2>
      <p class="muted">Paired decision comparisons use only Primary/Shadow dual-success rows. Reason screening is lexical evidence only and not a full semantic bias classifier.</p>
      <div class="table-wrap">
        <table>
          <tbody>{sensitivity_summary_rows_html}</tbody>
        </table>
      </div>
      <h3>Action Transitions</h3>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>Transition</th><th>Count</th></tr>
          </thead>
          <tbody>{transition_rows_html}</tbody>
        </table>
      </div>
      <h3>Flagged Shadow Reasons</h3>
      <p class="muted">{html.escape(str(reason_screening['limitations']))}</p>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>Pair</th><th>Message</th><th>User</th><th>Shadow reason</th><th>Matched spans</th></tr>
          </thead>
          <tbody>{flagged_pairs_rows_html}</tbody>
        </table>
      </div>
    </section>
    <section>
      <h2>Prompt Contract</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>Variant</th><th>Prompt token</th><th>Allowed profile fields</th><th>Excluded context fields</th><th>Neutral PeerContext</th></tr>
          </thead>
          <tbody>{prompt_contract_rows_html}</tbody>
        </table>
      </div>
    </section>
    <section>
      <h2>Provider Accounting</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>Variant</th><th>Invocations</th><th>Responses</th><th>Successful decisions</th><th>Usage-complete attempts</th><th>Usage-incomplete attempts</th><th>Observed models</th><th>Input tokens</th><th>Output tokens</th><th>Total tokens</th></tr>
          </thead>
          <tbody>{accounting_rows_html}</tbody>
        </table>
      </div>
    </section>
    <section>
      <h2>Message Summary</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>Message ID</th><th>Title</th><th>Segment</th><th>Exposures</th><th>Primary success</th><th>Primary fail</th><th>Shadow success</th><th>Shadow fail</th><th>Below capacity</th></tr>
          </thead>
          <tbody>{message_rows_html}</tbody>
        </table>
      </div>
    </section>
    <section>
      <h2>Batch Freeze</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>Batch</th><th>Frozen engaged users</th><th>Committed Primary positive users</th><th>Selected pairs per message</th></tr>
          </thead>
          <tbody>{step_rows_html}</tbody>
        </table>
      </div>
    </section>
    <section>
      <h2>Exposure Pairs</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>Batch</th><th>Message</th><th>User</th><th>Class</th><th>Rank</th><th>Selection</th><th>Full score</th><th>Primary status</th><th>Primary action</th><th>Primary prompt</th><th>Shadow status</th><th>Shadow action</th><th>Shadow prompt</th><th>Feedback committed</th></tr>
          </thead>
          <tbody>{pair_rows_html}</tbody>
        </table>
      </div>
    </section>
  </main>
</body>
</html>
'''


def _full_precision_cell(value: float) -> str:
    return format(value, ".17g")


def _step_message_summary(message_summary: _BatchMessageSummary) -> str:
    return f"{message_summary['message_id']}: {len(message_summary['selected_user_ids'])}"
