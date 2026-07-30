from __future__ import annotations

import csv
import json
import math
import shutil
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypedDict, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .concurrent_campaign_diagnostics import ConcurrentCampaignDiagnosticArtifacts, ConcurrentCampaignDiagnostics
from .concurrent_execution_journal import (
    CONCURRENT_MESSAGE_EXECUTION_SNAPSHOT_SCHEMA,
    ConcurrentExecutionJournal,
    _as_int,
    _as_str,
    _require_mapping,
    _sha256_file,
    build_concurrent_execution_run_identity,
    derive_concurrent_execution_publish_staging_dir,
    derive_concurrent_execution_workspace,
)
from .concurrent_message_report import (
    close_concurrent_message_artifacts,
    rebuild_concurrent_message_report,
    write_concurrent_message_report_artifacts,
)
from .decision import DecisionInput, EngageDecision, LLMDecisionAdapter, decision_profile_payload
from .final_research import (
    _TARGET_DELIVERY_RANKING_POLICY,
    FORMAL_RUN_STATUS,
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
from .safe_serialization import safe_data
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
CONCURRENT_MESSAGE_HOLDOUT_VIDEO_ID = TARGET_VIDEO_ID
CONCURRENT_MESSAGE_PRODUCTION_SAMPLE_SIZE = 1000
CONCURRENT_MESSAGE_PRODUCTION_HORIZON = 30
CONCURRENT_MESSAGE_PRODUCTION_DELIVERY_CAPACITY = 20
CONCURRENT_MESSAGE_FORMAL_PROVIDER = "openai_compatible"
CONCURRENT_MESSAGE_FORMAL_WIRE_API = "responses"
CONCURRENT_MESSAGE_FORMAL_REQUESTED_MODEL = "gpt-5.4-mini"
CONCURRENT_MESSAGE_FORMAL_OBSERVED_MODEL = "gpt-5.4-mini-2026-03-17"
CONCURRENT_MESSAGE_FORMAL_TIMEOUT_SECONDS = 30.0
CONCURRENT_MESSAGE_FORMAL_MAX_RETRIES = 2
CONCURRENT_MESSAGE_FORMAL_EXPOSURES_PER_MESSAGE = 600
CONCURRENT_MESSAGE_FORMAL_BELOW_CAPACITY_PER_MESSAGE = 400
CONCURRENT_MESSAGE_FORMAL_PRIMARY_DECISIONS = 1800
CONCURRENT_MESSAGE_FORMAL_SHADOW_DECISIONS = 1800
CONCURRENT_MESSAGE_FORMAL_TOTAL_LOGICAL_DECISIONS = 3600
CONCURRENT_MESSAGE_FORMAL_EXPOSURES = 1800
CONCURRENT_MESSAGE_FORMAL_BELOW_CAPACITY_PAIRS = 1200
CONCURRENT_MESSAGE_FORMAL_ELIGIBLE_PAIRS = 3000
CONCURRENT_MESSAGE_FORMAL_TERMINAL_ROWS = 3600
CONCURRENT_MESSAGE_FORMAL_INVOCATION_CEILING = 10800
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

    def snapshot(
        self,
        *,
        sampling_status: str = VALIDATION_RUN_STATUS,
        production_deploy_eligible: bool = False,
    ) -> dict[str, object]:
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
            "sampling_status": sampling_status,
            "production_deploy_eligible": production_deploy_eligible,
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
    base_network_relevance_full_precision: str | None = None
    engaged_neighbor_signal_full_precision: str | None = None
    raw_message_user_fit_full_precision: str | None = None
    normalized_message_user_fit_full_precision: str | None = None
    personalized_delivery_score_full_precision: str | None = None


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


@dataclass
class _ConcurrentBatchState:
    """Runner-owned state for one concurrent runtime, split by mutability."""

    # Immutable run identity, cohort/config contract, and provider baselines.
    output_path: Path
    run_identity: Mapping[str, object]
    cohort: _PreparedResearchCohort
    sample_users: list[ResearchUser]
    base_network_by_user: Mapping[str, float]
    neighbors_by_user: Mapping[str, set[str]]
    primary_provider_metadata: Mapping[str, object]
    shadow_provider_metadata: Mapping[str, object]
    primary_live_baseline: int
    shadow_live_baseline: int
    preflight_config_snapshot: Mapping[str, object]
    message_snapshot: Sequence[Mapping[str, object]]
    prompt_contract: Mapping[str, object]
    journal: ConcurrentExecutionJournal

    # Mutable committed evidence and lifecycle cursors.
    exposed_by_message: dict[str, set[str]]
    campaign_engaged_user_ids: set[str]
    candidate_rows: list[dict[str, object]] = field(default_factory=list)
    pair_rows: list[dict[str, object]] = field(default_factory=list)
    terminal_rows: list[dict[str, object]] = field(default_factory=list)
    variant_evidence_rows: list[dict[str, object]] = field(default_factory=list)
    step_rows: list[_BatchStepSummary] = field(default_factory=list)
    pair_schedule_position: int = 0
    next_time_step: int = 0

    # Active batch evidence is populated before ranking and cleared after commit.
    active_batch: dict[str, Any] | None = None


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
    user_vector = tuple(
        float(user.latent_attributes[f"latent_{dimension}_value_weight"]) for dimension in LATENT_VALUE_DIMENSIONS
    )
    raw_fit = _cosine_similarity(
        message_vector, user_vector, zero_label=f"message/user pair {message.message_id}/{user.user_id}"
    )
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
        raise ValueError(f"delivery_capacity {delivery_capacity} is smaller than the seed union size {len(selected)}")
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


def _adapter_external_request_invocations(adapter: LLMDecisionAdapter) -> int:
    leaf, _ = _unwrap_adapter(adapter)
    external_request_invocations = getattr(leaf, "external_request_invocations", 0)
    if not isinstance(external_request_invocations, int) or external_request_invocations < 0:
        raise TypeError("adapter external_request_invocations must be a non-negative int")
    return external_request_invocations


def _adapter_live_api_triggered(adapter: LLMDecisionAdapter, *, baseline: int = 0) -> bool:
    current = _adapter_external_request_invocations(adapter)
    if current < baseline:
        raise ValueError("adapter external_request_invocations moved backwards")
    return current > baseline


def _concurrent_sampling_status(
    primary_adapter: LLMDecisionAdapter,
    shadow_adapter: LLMDecisionAdapter,
    *,
    primary_live_baseline: int,
    shadow_live_baseline: int,
) -> str:
    if not (
        _adapter_live_api_triggered(primary_adapter, baseline=primary_live_baseline)
        and _adapter_live_api_triggered(shadow_adapter, baseline=shadow_live_baseline)
    ):
        return VALIDATION_RUN_STATUS
    return FORMAL_RUN_STATUS


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
            delta.provider_response_count > 0 and delta.usage_complete_response_count == delta.provider_response_count
        )
        return _VariantAttemptAccounting(
            request_invocations=max(
                request_delta, delta.provider_response_count, 1 if attempt.provider_failure is not None else 0
            ),
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


def _validate_observed_model_accounting(accounting: _VariantAttemptAccounting) -> None:
    observed_total = (
        sum(accounting.observed_model_counts.values())
        + accounting.observed_model_missing_response_count
        + accounting.observed_model_malformed_response_count
    )
    if observed_total != accounting.provider_response_count:
        raise ValueError("observed model accounting must cover every provider response")


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


def _provider_metadata_matches_formal_contract(metadata: Mapping[str, object]) -> bool:
    return (
        metadata.get("adapter") == CONCURRENT_MESSAGE_FORMAL_PROVIDER
        and metadata.get("enabled") is True
        and metadata.get("provider") == CONCURRENT_MESSAGE_FORMAL_PROVIDER
        and metadata.get("model") == CONCURRENT_MESSAGE_FORMAL_REQUESTED_MODEL
        and metadata.get("wire_api") == CONCURRENT_MESSAGE_FORMAL_WIRE_API
        and metadata.get("require_live_env") is True
        and metadata.get("timeout_seconds") == CONCURRENT_MESSAGE_FORMAL_TIMEOUT_SECONDS
        and metadata.get("max_retries") == CONCURRENT_MESSAGE_FORMAL_MAX_RETRIES
        and metadata.get("fail_closed_action") == "raise"
    )


def _variant_accounting_is_formal_eligible(accounting: Mapping[str, object], *, expected_successes: int) -> bool:
    invocations = accounting.get("invocations")
    responses = accounting.get("responses")
    if not isinstance(invocations, int) or not isinstance(responses, int):
        return False
    if accounting.get("successful_decisions") != expected_successes or responses != expected_successes:
        return False
    if invocations < responses:
        return False
    if invocations > expected_successes * (CONCURRENT_MESSAGE_FORMAL_MAX_RETRIES + 1):
        return False
    if accounting.get("observed_model_counts") != {CONCURRENT_MESSAGE_FORMAL_OBSERVED_MODEL: responses}:
        return False
    if accounting.get("observed_model_missing_response_count") != 0:
        return False
    if accounting.get("observed_model_malformed_response_count") != 0:
        return False
    if accounting.get("usage_complete_attempts") != expected_successes:
        return False
    if accounting.get("usage_incomplete_attempts") != 0:
        return False
    if accounting.get("usage_complete_response_count") != responses:
        return False
    if accounting.get("usage_missing_response_count") != 0:
        return False
    if accounting.get("usage_malformed_response_count") != 0:
        return False
    return (
        accounting.get("input_usage") is not None
        and accounting.get("output_usage") is not None
        and accounting.get("total_usage") is not None
    )


def _concurrent_production_deploy_eligible(
    validation_summary: Mapping[str, object],
    *,
    sampling_status: str,
    primary_provider_metadata: Mapping[str, object],
    shadow_provider_metadata: Mapping[str, object],
) -> bool:
    if sampling_status != FORMAL_RUN_STATUS:
        return False
    normalized_primary_metadata = dict(primary_provider_metadata)
    normalized_shadow_metadata = dict(shadow_provider_metadata)
    normalized_primary_metadata.pop("prompt_version", None)
    normalized_shadow_metadata.pop("prompt_version", None)
    if normalized_primary_metadata != normalized_shadow_metadata:
        return False
    if not _provider_metadata_matches_formal_contract(normalized_primary_metadata):
        return False

    counts = validation_summary.get("counts")
    per_message = validation_summary.get("per_message")
    provider_accounting = validation_summary.get("variant_provider_accounting")
    if (
        not isinstance(counts, Mapping)
        or not isinstance(per_message, Mapping)
        or not isinstance(provider_accounting, Mapping)
    ):
        return False

    expected_counts = {
        "sample_users": CONCURRENT_MESSAGE_PRODUCTION_SAMPLE_SIZE,
        "messages": len(authoritative_message_definitions()),
        "eligible_user_message_pairs": CONCURRENT_MESSAGE_FORMAL_ELIGIBLE_PAIRS,
        "actual_exposures": CONCURRENT_MESSAGE_FORMAL_EXPOSURES,
        "primary_attempted": CONCURRENT_MESSAGE_FORMAL_PRIMARY_DECISIONS,
        "primary_successes": CONCURRENT_MESSAGE_FORMAL_PRIMARY_DECISIONS,
        "primary_failures": 0,
        "shadow_attempted": CONCURRENT_MESSAGE_FORMAL_SHADOW_DECISIONS,
        "shadow_successes": CONCURRENT_MESSAGE_FORMAL_SHADOW_DECISIONS,
        "shadow_failures": 0,
        "terminal_rows": CONCURRENT_MESSAGE_FORMAL_TERMINAL_ROWS,
        "pair_terminal_coverage": 1.0,
        "paired_decision_coverage": 1.0,
    }
    for field_name, expected_value in expected_counts.items():
        if counts.get(field_name) != expected_value:
            return False

    for message in authoritative_message_definitions():
        message_counts = per_message.get(message.message_id)
        if not isinstance(message_counts, Mapping):
            return False
        if message_counts.get("message_title") != message.title:
            return False
        if message_counts.get("intended_audience_segment") != message.intended_audience_segment:
            return False
        if message_counts.get("exposures") != CONCURRENT_MESSAGE_FORMAL_EXPOSURES_PER_MESSAGE:
            return False
        if message_counts.get("primary_successes") != CONCURRENT_MESSAGE_FORMAL_EXPOSURES_PER_MESSAGE:
            return False
        if message_counts.get("primary_failures") != 0:
            return False
        if message_counts.get("shadow_successes") != CONCURRENT_MESSAGE_FORMAL_EXPOSURES_PER_MESSAGE:
            return False
        if message_counts.get("shadow_failures") != 0:
            return False
        if message_counts.get("below_delivery_capacity") != CONCURRENT_MESSAGE_FORMAL_BELOW_CAPACITY_PER_MESSAGE:
            return False

    primary = provider_accounting.get("primary")
    shadow = provider_accounting.get("shadow")
    total = provider_accounting.get("total")
    if not isinstance(primary, Mapping) or not isinstance(shadow, Mapping) or not isinstance(total, Mapping):
        return False
    if not _variant_accounting_is_formal_eligible(
        primary, expected_successes=CONCURRENT_MESSAGE_FORMAL_PRIMARY_DECISIONS
    ):
        return False
    if not _variant_accounting_is_formal_eligible(
        shadow, expected_successes=CONCURRENT_MESSAGE_FORMAL_SHADOW_DECISIONS
    ):
        return False

    primary_input_usage = primary.get("input_usage")
    shadow_input_usage = shadow.get("input_usage")
    primary_output_usage = primary.get("output_usage")
    shadow_output_usage = shadow.get("output_usage")
    primary_total_usage = primary.get("total_usage")
    shadow_total_usage = shadow.get("total_usage")
    total_input_usage = total.get("input_usage")
    total_output_usage = total.get("output_usage")
    total_total_usage = total.get("total_usage")
    total_invocations = total.get("invocations")
    total_responses = total.get("responses")
    primary_responses = primary.get("responses")
    shadow_responses = shadow.get("responses")
    primary_invocations = primary.get("invocations")
    shadow_invocations = shadow.get("invocations")
    numeric_values = (
        primary_input_usage,
        shadow_input_usage,
        primary_output_usage,
        shadow_output_usage,
        primary_total_usage,
        shadow_total_usage,
        total_input_usage,
        total_output_usage,
        total_total_usage,
        total_invocations,
        total_responses,
        primary_responses,
        shadow_responses,
        primary_invocations,
        shadow_invocations,
    )
    if not all(isinstance(value, int) for value in numeric_values):
        return False
    primary_input_usage = cast(int, primary_input_usage)
    shadow_input_usage = cast(int, shadow_input_usage)
    primary_output_usage = cast(int, primary_output_usage)
    shadow_output_usage = cast(int, shadow_output_usage)
    primary_total_usage = cast(int, primary_total_usage)
    shadow_total_usage = cast(int, shadow_total_usage)
    total_input_usage = cast(int, total_input_usage)
    total_output_usage = cast(int, total_output_usage)
    total_total_usage = cast(int, total_total_usage)
    total_invocations = cast(int, total_invocations)
    total_responses = cast(int, total_responses)
    primary_responses = cast(int, primary_responses)
    shadow_responses = cast(int, shadow_responses)
    primary_invocations = cast(int, primary_invocations)
    shadow_invocations = cast(int, shadow_invocations)
    if total.get("successful_decisions") != CONCURRENT_MESSAGE_FORMAL_TOTAL_LOGICAL_DECISIONS:
        return False
    if total_responses != primary_responses + shadow_responses:
        return False
    if total_invocations != primary_invocations + shadow_invocations:
        return False
    if total_invocations > CONCURRENT_MESSAGE_FORMAL_INVOCATION_CEILING:
        return False
    if total.get("observed_model_counts") != {CONCURRENT_MESSAGE_FORMAL_OBSERVED_MODEL: total_responses}:
        return False
    if total.get("observed_model_missing_response_count") != 0:
        return False
    if total.get("observed_model_malformed_response_count") != 0:
        return False
    if total.get("usage_complete_attempts") != CONCURRENT_MESSAGE_FORMAL_TOTAL_LOGICAL_DECISIONS:
        return False
    if total.get("usage_incomplete_attempts") != 0:
        return False
    if total.get("usage_complete_response_count") != total_responses:
        return False
    if total.get("usage_missing_response_count") != 0:
        return False
    if total.get("usage_malformed_response_count") != 0:
        return False
    if total_input_usage != primary_input_usage + shadow_input_usage:
        return False
    if total_output_usage != primary_output_usage + shadow_output_usage:
        return False
    if total_total_usage != primary_total_usage + shadow_total_usage:
        return False
    return True


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
    """Run the runtime-only concurrent-message tracer and write persisted artifacts."""

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
            raise ValueError("primary and shadow adapters must match on provider/model/timeout/retry/sampling metadata")

    def run_and_write(self, output_dir: str | Path, mode: Literal["new", "resume"] = "new") -> Path:
        if mode == "resume":
            return self._run_and_write_resume(output_dir)

        output_path = Path(output_dir)
        dataset_path = self.config.dataset_dir.resolve()
        if output_path.resolve().is_relative_to(dataset_path):
            raise ValueError("output_dir must be outside dataset_dir")
        operational_workspace = derive_concurrent_execution_workspace(output_path)
        if output_path.exists():
            raise FileExistsError(f"output_dir already exists before finalization: {output_path}")
        if operational_workspace.exists():
            if operational_workspace.is_file() or any(operational_workspace.iterdir()):
                raise FileExistsError(f"operational workspace already exists and is not empty: {operational_workspace}")

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
        primary_live_baseline = _adapter_external_request_invocations(self.primary_adapter)
        shadow_live_baseline = _adapter_external_request_invocations(self.shadow_adapter)
        sampling_status = _concurrent_sampling_status(
            self.primary_adapter,
            self.shadow_adapter,
            primary_live_baseline=primary_live_baseline,
            shadow_live_baseline=shadow_live_baseline,
        )
        preflight_config_snapshot = self.config.snapshot(
            sampling_status=sampling_status,
            production_deploy_eligible=False,
        )
        message_snapshot = [message.model_dump(mode="json") for message in self.config.messages]
        prompt_contract = _variant_prompt_contract_summary()
        run_identity = build_concurrent_execution_run_identity(
            output_target=output_path,
            operational_workspace=operational_workspace,
            configuration_snapshot=preflight_config_snapshot,
            message_snapshot=message_snapshot,
            sample_audit=cohort.sample_audit,
            dataset_dir=self.config.dataset_dir,
            primary_provider_metadata=primary_provider_metadata,
            shadow_provider_metadata=shadow_provider_metadata,
            prompt_contract=prompt_contract,
        )
        journal = ConcurrentExecutionJournal.open_new(operational_workspace, identity=run_identity)

        state = _ConcurrentBatchState(
            output_path=output_path,
            run_identity=run_identity,
            cohort=cohort,
            sample_users=sample_users,
            base_network_by_user=base_network_by_user,
            neighbors_by_user=neighbors_by_user,
            primary_provider_metadata=primary_provider_metadata,
            shadow_provider_metadata=shadow_provider_metadata,
            primary_live_baseline=primary_live_baseline,
            shadow_live_baseline=shadow_live_baseline,
            preflight_config_snapshot=preflight_config_snapshot,
            message_snapshot=message_snapshot,
            prompt_contract=prompt_contract,
            journal=journal,
            exposed_by_message=exposed_by_message,
            campaign_engaged_user_ids=campaign_engaged_user_ids,
            candidate_rows=candidate_rows,
            pair_rows=pair_rows,
            terminal_rows=terminal_rows,
            variant_evidence_rows=variant_evidence_rows,
            step_rows=step_rows,
            pair_schedule_position=pair_schedule_position,
        )
        try:
            return self._run_batches_from(state)
        finally:
            journal.close()

    def _run_and_write_resume(self, output_dir: str | Path) -> Path:
        output_path = Path(output_dir)
        dataset_path = self.config.dataset_dir.resolve()
        if output_path.resolve().is_relative_to(dataset_path):
            raise ValueError("output_dir must be outside dataset_dir")

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
        primary_live_baseline = _adapter_external_request_invocations(self.primary_adapter)
        shadow_live_baseline = _adapter_external_request_invocations(self.shadow_adapter)
        sampling_status = _concurrent_sampling_status(
            self.primary_adapter,
            self.shadow_adapter,
            primary_live_baseline=primary_live_baseline,
            shadow_live_baseline=shadow_live_baseline,
        )
        preflight_config_snapshot = self.config.snapshot(
            sampling_status=sampling_status,
            production_deploy_eligible=False,
        )
        message_snapshot = [message.model_dump(mode="json") for message in self.config.messages]
        prompt_contract = _variant_prompt_contract_summary()
        run_identity = build_concurrent_execution_run_identity(
            output_target=output_path,
            operational_workspace=derive_concurrent_execution_workspace(output_path),
            configuration_snapshot=preflight_config_snapshot,
            message_snapshot=message_snapshot,
            sample_audit=cohort.sample_audit,
            dataset_dir=self.config.dataset_dir,
            primary_provider_metadata=primary_provider_metadata,
            shadow_provider_metadata=shadow_provider_metadata,
            prompt_contract=prompt_contract,
        )
        journal = ConcurrentExecutionJournal.open_resume(
            derive_concurrent_execution_workspace(output_path), identity=run_identity
        )
        try:
            replay = journal.replay()
            status = replay["status"]
            if status["lifecycle"] == "published":
                if not output_path.exists():
                    raise FileNotFoundError(f"finalized concurrent message output is missing: {output_path}")
                rebuild_concurrent_message_report(output_path)
                return output_path
            if output_path.exists() and status["lifecycle"] not in {"ready_to_finalize", "durable_partial"}:
                raise FileExistsError(f"output_dir already exists before finalization: {output_path}")

            messages_by_id = {message.message_id: message for message in self.config.messages}
            resume_state = self._restore_runtime_state(
                replay=replay,
                cohort=cohort,
                messages_by_id=messages_by_id,
            )
            candidate_rows = resume_state["candidate_rows"]
            pair_rows = resume_state["pair_rows"]
            terminal_rows = resume_state["terminal_rows"]
            variant_evidence_rows = resume_state["variant_evidence_rows"]
            step_rows = resume_state["step_rows"]
            campaign_engaged_user_ids = resume_state["campaign_engaged_user_ids"]
            exposed_by_message = resume_state["exposed_by_message"]
            pair_schedule_position = resume_state["pair_schedule_position"]
            active_batch = resume_state["active_batch"]
            state = _ConcurrentBatchState(
                output_path=output_path,
                run_identity=run_identity,
                cohort=cohort,
                sample_users=sample_users,
                base_network_by_user=base_network_by_user,
                neighbors_by_user=neighbors_by_user,
                primary_provider_metadata=primary_provider_metadata,
                shadow_provider_metadata=shadow_provider_metadata,
                primary_live_baseline=primary_live_baseline,
                shadow_live_baseline=shadow_live_baseline,
                preflight_config_snapshot=preflight_config_snapshot,
                message_snapshot=message_snapshot,
                prompt_contract=prompt_contract,
                journal=journal,
                exposed_by_message=exposed_by_message,
                campaign_engaged_user_ids=campaign_engaged_user_ids,
                candidate_rows=candidate_rows,
                pair_rows=pair_rows,
                terminal_rows=terminal_rows,
                variant_evidence_rows=variant_evidence_rows,
                step_rows=step_rows,
                pair_schedule_position=pair_schedule_position,
                next_time_step=resume_state["next_time_step"],
                active_batch=active_batch,
            )
            return self._run_batches_from(state)
        finally:
            journal.close()

    @staticmethod
    def _validate_active_batch_state(
        state: _ConcurrentBatchState,
        *,
        require_all_pairs: bool,
    ) -> None:
        active_batch = state.active_batch
        if active_batch is None:
            raise RuntimeError("batch transition requires an active batch state")
        batch_plans = cast(list[_PairExecutionPlan], active_batch["batch_plans"])
        pair_positions = [plan.pair_schedule_position for plan in batch_plans]
        if len({plan.pair_id for plan in batch_plans}) != len(batch_plans):
            raise ValueError("active batch pair identities must be unique")
        if pair_positions != sorted(pair_positions) or len(set(pair_positions)) != len(pair_positions):
            raise ValueError("active batch pair order must be stable")
        if pair_positions and pair_positions != list(range(pair_positions[0], pair_positions[0] + len(pair_positions))):
            raise ValueError("active batch pair schedule positions must be contiguous")
        snapshot_hash = active_batch.get("batch_snapshot_hash")
        if not isinstance(snapshot_hash, str) or not snapshot_hash:
            raise ValueError("active batch requires a persisted snapshot hash")
        next_pair_index = active_batch.get("next_pair_index")
        if not isinstance(next_pair_index, int) or not 0 <= next_pair_index <= len(batch_plans):
            raise ValueError("active batch next pair index is out of range")
        terminal_start = active_batch.get("terminal_row_start")
        if not isinstance(terminal_start, int) or not 0 <= terminal_start <= len(state.terminal_rows):
            raise ValueError("active batch terminal row start is out of range")
        pair_state_by_id = active_batch.get("pair_state_by_id")
        if not isinstance(pair_state_by_id, Mapping):
            raise ValueError("active batch pair state is missing")
        if set(pair_state_by_id) != {plan.pair_id for plan in batch_plans}:
            raise ValueError("active batch pair state identities do not match the plan")
        expected_terminal_keys: set[tuple[str, str]] = set()
        for pair_index, plan in enumerate(batch_plans):
            pair_state = pair_state_by_id[plan.pair_id]
            if not isinstance(pair_state, Mapping):
                raise ValueError(f"active batch pair state is invalid for {plan.pair_id}")
            pair_closed = bool(pair_state.get("pair_closed"))
            if pair_closed != (pair_index < next_pair_index):
                raise ValueError("active batch pair closure does not match next pair index")
            for variant in ("primary", "shadow"):
                terminal = pair_state.get(f"{variant}_terminal_row")
                evidence = pair_state.get(f"{variant}_variant_evidence")
                if (terminal is None) != (evidence is None):
                    raise ValueError("active batch terminal and variant evidence must arrive together")
                if isinstance(terminal, Mapping) and isinstance(evidence, Mapping):
                    expected_terminal_keys.add((plan.pair_id, variant))
        terminal_rows = state.terminal_rows[terminal_start:]
        terminal_keys = [(str(row["pair_id"]), str(row["decision_variant"])) for row in terminal_rows]
        if len(terminal_keys) != len(set(terminal_keys)):
            raise ValueError("active batch terminal identities must be unique")
        if set(terminal_keys) != expected_terminal_keys:
            raise ValueError("active batch terminal evidence does not match pair state")
        if require_all_pairs:
            expected_terminal_keys = {
                (plan.pair_id, variant) for plan in batch_plans for variant in ("primary", "shadow")
            }
            if set(terminal_keys) != expected_terminal_keys:
                raise ValueError("campaign feedback requires terminal evidence for every pair variant")
            if next_pair_index != len(batch_plans):
                raise ValueError("campaign feedback requires all pairs to be terminal")

    def _run_batches_from(self, state: _ConcurrentBatchState) -> Path:
        output_path = state.output_path
        cohort = state.cohort
        sample_users = state.sample_users
        base_network_by_user = state.base_network_by_user
        neighbors_by_user = state.neighbors_by_user
        exposed_by_message = state.exposed_by_message
        campaign_engaged_user_ids = state.campaign_engaged_user_ids
        candidate_rows = state.candidate_rows
        pair_rows = state.pair_rows
        terminal_rows = state.terminal_rows
        variant_evidence_rows = state.variant_evidence_rows
        step_rows = state.step_rows
        primary_provider_metadata = state.primary_provider_metadata
        shadow_provider_metadata = state.shadow_provider_metadata
        primary_live_baseline = state.primary_live_baseline
        shadow_live_baseline = state.shadow_live_baseline
        message_snapshot = state.message_snapshot
        journal = state.journal

        def _complete_active_batch(active_batch: dict[str, Any]) -> None:
            self._validate_active_batch_state(state, require_all_pairs=False)
            time_step = _as_int(active_batch["time_step"])
            batch_pair_start = _as_int(active_batch["batch_pair_start"])
            batch_snapshot_hash = _as_str(active_batch["batch_snapshot_hash"])
            batch_plans = cast(list[_PairExecutionPlan], active_batch["batch_plans"])
            pair_state_by_id = cast(dict[str, dict[str, Any]], active_batch["pair_state_by_id"])
            batch_message_summaries = cast(dict[str, _BatchMessageSummary], active_batch["batch_message_summaries"])
            primary_positive_user_ids = cast(set[str], active_batch["primary_positive_user_ids"])
            next_pair_index = _as_int(active_batch["next_pair_index"])

            for pair_index in range(next_pair_index, len(batch_plans)):
                plan = batch_plans[pair_index]
                pair_row, primary_positive_event = self._execute_pair(
                    plan=plan,
                    pair_state=pair_state_by_id[plan.pair_id],
                    primary_provider_metadata=primary_provider_metadata,
                    shadow_provider_metadata=shadow_provider_metadata,
                    journal=journal,
                    batch_snapshot_hash=batch_snapshot_hash,
                )
                terminal_rows.extend(cast(list[dict[str, object]], pair_row.pop("_terminal_rows", [])))
                variant_evidence_rows.extend(cast(list[dict[str, object]], pair_row.pop("_variant_evidence", [])))
                pair_rows.append(pair_row)
                if primary_positive_event is not None:
                    primary_positive_user_ids.add(plan.user.user_id)
                    batch_message_summaries[plan.message.message_id]["primary_positive_user_ids"].append(
                        plan.user.user_id
                    )
                if pair_row["primary_status"] == "provider_failed":
                    batch_message_summaries[plan.message.message_id]["primary_provider_failed_user_ids"].append(
                        plan.user.user_id
                    )
                if pair_row["shadow_status"] == "provider_failed":
                    batch_message_summaries[plan.message.message_id]["shadow_provider_failed_user_ids"].append(
                        plan.user.user_id
                    )
                active_batch["next_pair_index"] = pair_index + 1

            self._validate_active_batch_state(state, require_all_pairs=True)
            committed_user_ids = sorted(primary_positive_user_ids)
            campaign_engaged_user_ids.update(committed_user_ids)
            journal.append(
                event_type="batch_committed",
                event_identity={"time_step": time_step},
                payload={
                    "time_step": time_step,
                    "committed_user_ids": committed_user_ids,
                    "committed_user_count": len(committed_user_ids),
                    "batch_pair_count": len(batch_plans),
                },
                batch_snapshot_hash=batch_snapshot_hash,
            )
            state.next_time_step = time_step + 1
            for pair_row in pair_rows[batch_pair_start:]:
                pair_row["campaign_feedback_committed"] = _csv_bool(
                    pair_row["primary_action"] in CONCURRENT_MESSAGE_POSITIVE_ACTIONS
                    and str(pair_row["user_id"]) in committed_user_ids
                )

            step_rows.append(
                {
                    "time_step": time_step,
                    "frozen_campaign_engaged_user_ids": list(active_batch["frozen_campaign_engaged_user_ids"]),
                    "deduplicated_committed_primary_positive_user_ids": committed_user_ids,
                    "messages": [batch_message_summaries[message.message_id] for message in self.config.messages],
                }
            )
            state.active_batch = None

        def _advance_batch() -> None:
            active_batch = state.active_batch
            if active_batch is not None:
                _complete_active_batch(active_batch)
                return

            time_step = state.next_time_step
            pair_schedule_position = state.pair_schedule_position
            frozen_campaign_engaged_user_ids = sorted(campaign_engaged_user_ids)
            batch_pair_start = len(pair_rows)
            batch_plans: list[_PairExecutionPlan] = []
            batch_message_summaries: dict[str, _BatchMessageSummary] = {}
            batch_candidate_rows_by_message: dict[str, list[dict[str, object]]] = {}
            batch_selected_pair_plans_by_message: dict[str, list[dict[str, object]]] = {}
            pair_state_by_id: dict[str, dict[str, Any]] = {}
            state.active_batch = {
                "time_step": time_step,
                "batch_pair_start": batch_pair_start,
                "frozen_campaign_engaged_user_ids": frozen_campaign_engaged_user_ids,
                "batch_plans": batch_plans,
                "batch_message_summaries": batch_message_summaries,
                "batch_candidate_rows_by_message": batch_candidate_rows_by_message,
                "batch_selected_pair_plans_by_message": batch_selected_pair_plans_by_message,
                "pair_state_by_id": pair_state_by_id,
                "primary_positive_user_ids": set[str](),
                "terminal_row_start": len(terminal_rows),
                "batch_snapshot_hash": None,
                "next_pair_index": 0,
            }
            active_batch = state.active_batch
            if active_batch is None:
                raise RuntimeError("batch transition failed to initialize active state")

            for message in self.config.messages:
                eligible_user_ids = [
                    user_id
                    for user_id in cohort.sample_user_ids
                    if user_id not in exposed_by_message[message.message_id]
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
                message_candidate_rows: list[dict[str, object]] = []
                for ranking_position, score in enumerate(ranked_scores, start=1):
                    candidate_row = {
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
                    candidate_rows.append(candidate_row)
                    message_candidate_rows.append(candidate_row)
                batch_candidate_rows_by_message[message.message_id] = message_candidate_rows
                batch_message_summaries[message.message_id] = {
                    "message_id": message.message_id,
                    "message_title": message.title,
                    "eligible_users": len(eligible_user_ids),
                    "ranked_candidates": len(ranked_scores),
                    "selected_user_ids": list(selected_user_ids),
                    "seed_user_ids": [user_id for user_id in selected_user_ids if user_id in cohort.seed_user_ids],
                    "personalized_topup_user_ids": [
                        user_id
                        for user_id, reason in selection_reason_by_user.items()
                        if reason == "personalized_topup"
                    ],
                    "primary_positive_user_ids": [],
                    "primary_provider_failed_user_ids": [],
                    "shadow_provider_failed_user_ids": [],
                    "below_delivery_capacity": len(ranked_scores) - len(selected_scores),
                    "selection_reason_counts": dict(sorted(Counter(selection_reason_by_user.values()).items())),
                }
                message_selected_pair_plans: list[dict[str, object]] = []
                for score in selected_scores:
                    user = cohort.users_by_id[score.user_id]
                    pair_plan = _PairExecutionPlan(
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
                    batch_plans.append(pair_plan)
                    pair_state_by_id[pair_plan.pair_id] = {
                        "plan": pair_plan,
                        "primary_started": False,
                        "shadow_started": False,
                        "primary_terminal_row": None,
                        "shadow_terminal_row": None,
                        "primary_variant_evidence": None,
                        "shadow_variant_evidence": None,
                        "pair_closed": False,
                        "pair_row": None,
                    }
                    message_selected_pair_plans.append(
                        {
                            "pair_id": pair_plan.pair_id,
                            "pair_schedule_position": pair_plan.pair_schedule_position,
                            "time_step": pair_plan.time_step,
                            "message_id": pair_plan.message.message_id,
                            "message_title": pair_plan.message.title,
                            "user_id": pair_plan.user.user_id,
                            "ranking_position": pair_plan.ranking_position,
                            "selection_reason": pair_plan.selection_reason,
                            "base_network_relevance": round(pair_plan.score.base_network_relevance, 12),
                            "base_network_relevance_full_precision": _full_precision_cell(
                                pair_plan.score.base_network_relevance
                            ),
                            "campaign_engaged_neighbor_count": pair_plan.score.engaged_neighbor_count,
                            "campaign_engaged_neighbor_signal": round(pair_plan.score.engaged_neighbor_signal, 12),
                            "campaign_engaged_neighbor_signal_full_precision": _full_precision_cell(
                                pair_plan.score.engaged_neighbor_signal
                            ),
                            "historical_tag_affinity": CONCURRENT_MESSAGE_HISTORY_AFFINITY,
                            "raw_message_user_fit": round(pair_plan.score.raw_message_user_fit, 12),
                            "raw_message_user_fit_full_precision": _full_precision_cell(
                                pair_plan.score.raw_message_user_fit
                            ),
                            "normalized_message_user_fit": round(pair_plan.score.normalized_message_user_fit, 12),
                            "normalized_message_user_fit_full_precision": _full_precision_cell(
                                pair_plan.score.normalized_message_user_fit
                            ),
                            "personalized_delivery_score": round(pair_plan.score.personalized_delivery_score, 12),
                            "personalized_delivery_score_full_precision": _full_precision_cell(
                                pair_plan.score.personalized_delivery_score
                            ),
                        }
                    )
                    pair_schedule_position += 1
                    state.pair_schedule_position = pair_schedule_position
                batch_selected_pair_plans_by_message[message.message_id] = message_selected_pair_plans

            batch_snapshot_payload = {
                "schema_version": CONCURRENT_MESSAGE_EXECUTION_SNAPSHOT_SCHEMA,
                "snapshot_type": "batch_plan",
                "snapshot_identity": {"time_step": time_step},
                "time_step": time_step,
                "frozen_campaign_engaged_user_ids": list(frozen_campaign_engaged_user_ids),
                "planned_pair_count": len(batch_plans),
                "planned_variant_count": len(batch_plans) * 2,
                "messages": [
                    {
                        "message_id": message_id,
                        "message_title": batch_message_summaries[message_id]["message_title"],
                        "eligible_users": batch_message_summaries[message_id]["eligible_users"],
                        "ranked_candidates": batch_candidate_rows_by_message[message_id],
                        "selected_pair_plans": batch_selected_pair_plans_by_message[message_id],
                        "selected_user_ids": batch_message_summaries[message_id]["selected_user_ids"],
                        "seed_user_ids": batch_message_summaries[message_id]["seed_user_ids"],
                        "personalized_topup_user_ids": batch_message_summaries[message_id][
                            "personalized_topup_user_ids"
                        ],
                        "below_delivery_capacity": batch_message_summaries[message_id]["below_delivery_capacity"],
                        "selection_reason_counts": batch_message_summaries[message_id]["selection_reason_counts"],
                    }
                    for message_id in [message.message_id for message in self.config.messages]
                ],
            }
            batch_snapshot_ref = journal.persist_snapshot(
                snapshot_type="batch_plan",
                snapshot_identity={"time_step": time_step},
                payload=batch_snapshot_payload,
            )
            batch_snapshot_hash = batch_snapshot_ref["snapshot_hash"]
            active_batch["batch_snapshot_hash"] = batch_snapshot_hash
            self._validate_active_batch_state(state, require_all_pairs=False)

            _complete_active_batch(active_batch)

        while state.next_time_step < self.config.horizon:
            _advance_batch()

        safe_candidate_rows = _safe_runtime_rows(candidate_rows)
        safe_pair_rows = _safe_runtime_rows(pair_rows)
        safe_terminal_rows = _safe_runtime_rows(terminal_rows)
        campaign_diagnostics = ConcurrentCampaignDiagnostics(delivery_capacity=self.config.delivery_capacity).build(
            candidate_rows=safe_candidate_rows, pair_rows=safe_pair_rows
        )
        sampling_status = _concurrent_sampling_status(
            self.primary_adapter,
            self.shadow_adapter,
            primary_live_baseline=primary_live_baseline,
            shadow_live_baseline=shadow_live_baseline,
        )
        validation_summary = self._validation_summary(
            cohort=cohort,
            pair_rows=pair_rows,
            terminal_rows=terminal_rows,
            variant_evidence_rows=variant_evidence_rows,
            step_rows=step_rows,
            diagnostics=campaign_diagnostics,
            sampling_status=sampling_status,
            production_deploy_eligible=False,
        )
        production_deploy_eligible = _concurrent_production_deploy_eligible(
            validation_summary,
            sampling_status=sampling_status,
            primary_provider_metadata=primary_provider_metadata,
            shadow_provider_metadata=shadow_provider_metadata,
        )
        if production_deploy_eligible:
            validation_summary = self._validation_summary(
                cohort=cohort,
                pair_rows=pair_rows,
                terminal_rows=terminal_rows,
                variant_evidence_rows=variant_evidence_rows,
                step_rows=step_rows,
                diagnostics=campaign_diagnostics,
                sampling_status=sampling_status,
                production_deploy_eligible=production_deploy_eligible,
            )
        config_snapshot = self.config.snapshot(
            sampling_status=sampling_status,
            production_deploy_eligible=production_deploy_eligible,
        )
        sample_audit = dict(cohort.sample_audit)
        sample_audit["sampling_status"] = sampling_status
        return self._finalize_concurrent_message_output(
            output_path=output_path,
            journal=journal,
            sample_users=sample_users,
            config_snapshot=config_snapshot,
            message_snapshot=message_snapshot,
            sample_audit=sample_audit,
            candidate_rows=safe_candidate_rows,
            pair_rows=safe_pair_rows,
            terminal_rows=safe_terminal_rows,
            step_rows=list(step_rows),
            validation_summary=validation_summary,
            campaign_diagnostics=campaign_diagnostics,
            sampling_status=sampling_status,
        )

    def _finalize_concurrent_message_output(
        self,
        *,
        output_path: Path,
        journal: ConcurrentExecutionJournal,
        sample_users: list[ResearchUser],
        config_snapshot: Mapping[str, object],
        message_snapshot: Sequence[Mapping[str, object]],
        sample_audit: Mapping[str, object],
        candidate_rows: Sequence[Mapping[str, object]],
        pair_rows: Sequence[Mapping[str, object]],
        terminal_rows: Sequence[Mapping[str, object]],
        step_rows: Sequence[Mapping[str, object]],
        validation_summary: Mapping[str, object],
        campaign_diagnostics: ConcurrentCampaignDiagnosticArtifacts,
        sampling_status: str,
    ) -> Path:
        staging_path = derive_concurrent_execution_publish_staging_dir(output_path, run_id=journal.run_id)

        def _publish_payload(final_source_hash: str, report_path: Path) -> dict[str, object]:
            return {
                "output_target": str(output_path),
                "staging_path": str(staging_path),
                "final_source_path": str(output_path),
                "final_source_hash": final_source_hash,
                "report_path": str(report_path),
                "deploy_eligibility": False,
                "sampling_status": sampling_status,
            }

        if output_path.exists():
            if not output_path.is_dir():
                raise FileExistsError(f"final concurrent message output already exists as a file: {output_path}")
            report_path = rebuild_concurrent_message_report(output_path)
            closure = close_concurrent_message_artifacts(output_path)
            manifest_hash = _sha256_file(closure.artifact_paths["artifact_manifest"])
            if not journal.finalized:
                journal.append(
                    event_type="run_published",
                    event_identity={
                        "run_id": journal.run_id,
                        "output_target": str(output_path),
                        "finalization_stage": "published",
                    },
                    payload=_publish_payload(manifest_hash, report_path),
                )
            return output_path

        if staging_path.exists():
            if staging_path.is_file():
                raise FileExistsError(f"concurrent message staging path already exists as a file: {staging_path}")
            shutil.rmtree(staging_path)

        write_concurrent_message_report_artifacts(
            staging_path,
            title=self.config.report.title,
            config_snapshot=config_snapshot,
            message_snapshot=message_snapshot,
            sample_users=[user.model_dump(mode="json") for user in sample_users],
            sample_audit=sample_audit,
            candidate_rows=candidate_rows,
            pair_rows=pair_rows,
            terminal_rows=terminal_rows,
            step_rows=step_rows,
            validation_summary=validation_summary,
            campaign_diagnostics=campaign_diagnostics.payload,
        )
        report_path = rebuild_concurrent_message_report(staging_path)
        closure = close_concurrent_message_artifacts(staging_path)
        manifest_hash = _sha256_file(closure.artifact_paths["artifact_manifest"])
        if not journal.finalization_started:
            journal.append(
                event_type="run_finalized",
                event_identity={
                    "run_id": journal.run_id,
                    "output_target": str(output_path),
                    "finalization_stage": "finalized",
                },
                payload=_publish_payload(manifest_hash, report_path),
            )
        staging_path.replace(output_path)
        journal.append(
            event_type="run_published",
            event_identity={
                "run_id": journal.run_id,
                "output_target": str(output_path),
                "finalization_stage": "published",
            },
            payload=_publish_payload(manifest_hash, report_path),
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
        _validate_observed_model_accounting(accounting)
        return attempt, accounting

    def _execute_pair(
        self,
        *,
        plan: _PairExecutionPlan,
        pair_state: dict[str, Any],
        primary_provider_metadata: Mapping[str, object],
        shadow_provider_metadata: Mapping[str, object],
        journal: ConcurrentExecutionJournal,
        batch_snapshot_hash: str,
    ) -> tuple[dict[str, object], dict[str, str] | None]:
        primary_context = _primary_variant_context(plan)
        shadow_context = _shadow_variant_context(plan)
        new_terminal_rows: list[dict[str, object]] = []
        new_variant_evidence: list[dict[str, object]] = []

        def _ensure_started(decision_variant: str) -> None:
            started_key = f"{decision_variant}_started"
            if not bool(pair_state[started_key]):
                journal.append(
                    event_type="variant_started",
                    event_identity={
                        "pair_id": plan.pair_id,
                        "decision_variant": decision_variant,
                        "event_type": "variant_started",
                        "time_step": plan.time_step,
                    },
                    payload={
                        "pair_id": plan.pair_id,
                        "pair_schedule_position": plan.pair_schedule_position,
                        "message_id": plan.message.message_id,
                        "message_title": plan.message.title,
                        "user_id": plan.user.user_id,
                        "ranking_position": plan.ranking_position,
                        "selection_reason": plan.selection_reason,
                    },
                    batch_snapshot_hash=batch_snapshot_hash,
                )
                pair_state[started_key] = True

        def _ensure_terminal(
            *,
            decision_variant: str,
            context: _VariantDecisionContext,
            provider_metadata: Mapping[str, object],
        ) -> tuple[dict[str, object], dict[str, object], bool]:
            terminal_key = f"{decision_variant}_terminal_row"
            evidence_key = f"{decision_variant}_variant_evidence"
            terminal_row = pair_state[terminal_key]
            variant_evidence = pair_state[evidence_key]
            terminal_missing = not isinstance(terminal_row, Mapping) or not isinstance(variant_evidence, Mapping)
            if terminal_missing:
                attempt, accounting = self._execute_variant(
                    adapter=self.primary_adapter if decision_variant == "primary" else self.shadow_adapter,
                    context=context,
                    pair_schedule_position=plan.pair_schedule_position,
                    time_step=plan.time_step,
                    message_id=plan.message.message_id,
                    default_provider_metadata=provider_metadata,
                )
                terminal_row, _, variant_evidence = self._terminal_row(
                    pair_id=plan.pair_id,
                    pair_schedule_position=plan.pair_schedule_position,
                    time_step=plan.time_step,
                    message_id=plan.message.message_id,
                    user_id=plan.user.user_id,
                    context=context,
                    attempt=attempt,
                    accounting=accounting,
                    default_provider_metadata=provider_metadata,
                )
                pair_state[terminal_key] = terminal_row
                pair_state[evidence_key] = variant_evidence
                return terminal_row, variant_evidence, True
            return dict(terminal_row), dict(variant_evidence), False

        def _append_terminal_event(
            *,
            decision_variant: str,
            terminal_row: Mapping[str, object],
            variant_evidence: Mapping[str, object],
        ) -> None:
            journal.append(
                event_type="variant_terminal",
                event_identity={
                    "pair_id": plan.pair_id,
                    "decision_variant": decision_variant,
                    "event_type": "variant_terminal",
                    "time_step": plan.time_step,
                },
                payload={
                    "pair_id": plan.pair_id,
                    "pair_schedule_position": plan.pair_schedule_position,
                    "message_id": plan.message.message_id,
                    "message_title": plan.message.title,
                    "user_id": plan.user.user_id,
                    "terminal_row_id": terminal_row["terminal_row_id"],
                    "terminal_status": terminal_row["terminal_status"],
                    "provider_status": terminal_row["provider_status"],
                    "action": terminal_row["action"],
                    "reason": terminal_row["reason"],
                    "decision_source": terminal_row["decision_source"],
                    "terminal_row": terminal_row,
                    "variant_evidence": variant_evidence,
                },
                batch_snapshot_hash=batch_snapshot_hash,
            )

        if bool(pair_state["pair_closed"]):
            pair_row = dict(cast(dict[str, object], pair_state["pair_row"]))
            primary_terminal_row = cast(Mapping[str, object], pair_state["primary_terminal_row"])
            primary_action = str(primary_terminal_row["action"])
            pair_row["_terminal_rows"] = []
            pair_row["_variant_evidence"] = []
            primary_positive_event = (
                {"message_id": plan.message.message_id, "user_id": plan.user.user_id, "action": primary_action}
                if primary_terminal_row["terminal_status"] == "succeeded"
                and primary_action in CONCURRENT_MESSAGE_POSITIVE_ACTIONS
                else None
            )
            return pair_row, primary_positive_event

        _ensure_started("primary")
        _ensure_started("shadow")

        primary_terminal_row, primary_variant_evidence, primary_needs_event = _ensure_terminal(
            decision_variant="primary",
            context=primary_context,
            provider_metadata=primary_provider_metadata,
        )
        primary_action = str(primary_terminal_row["action"])
        primary_positive_event = (
            {"message_id": plan.message.message_id, "user_id": plan.user.user_id, "action": primary_action}
            if primary_terminal_row["terminal_status"] == "succeeded"
            and primary_action in CONCURRENT_MESSAGE_POSITIVE_ACTIONS
            else None
        )
        shadow_terminal_row, shadow_variant_evidence, shadow_needs_event = _ensure_terminal(
            decision_variant="shadow",
            context=shadow_context,
            provider_metadata=shadow_provider_metadata,
        )

        if primary_needs_event:
            _append_terminal_event(
                decision_variant="primary",
                terminal_row=primary_terminal_row,
                variant_evidence=primary_variant_evidence,
            )
            new_terminal_rows.append(dict(safe_data(primary_terminal_row)))
            new_variant_evidence.append(dict(safe_data(primary_variant_evidence)))
        if shadow_needs_event:
            _append_terminal_event(
                decision_variant="shadow",
                terminal_row=shadow_terminal_row,
                variant_evidence=shadow_variant_evidence,
            )
            new_terminal_rows.append(dict(safe_data(shadow_terminal_row)))
            new_variant_evidence.append(dict(safe_data(shadow_variant_evidence)))

        pair_row = self._build_pair_row(
            plan=plan,
            primary_terminal_row=primary_terminal_row,
            shadow_terminal_row=shadow_terminal_row,
            primary_variant_evidence=primary_variant_evidence,
            shadow_variant_evidence=shadow_variant_evidence,
        )
        pair_row["_terminal_rows"] = new_terminal_rows
        pair_row["_variant_evidence"] = new_variant_evidence
        journal.append(
            event_type="pair_closed",
            event_identity={
                "pair_id": plan.pair_id,
                "time_step": plan.time_step,
            },
            payload={
                "pair_id": plan.pair_id,
                "pair_schedule_position": plan.pair_schedule_position,
                "message_id": plan.message.message_id,
                "message_title": plan.message.title,
                "user_id": plan.user.user_id,
                "primary_terminal_row_id": primary_terminal_row["terminal_row_id"],
                "shadow_terminal_row_id": shadow_terminal_row["terminal_row_id"],
                "primary_status": primary_terminal_row["terminal_status"],
                "shadow_status": shadow_terminal_row["terminal_status"],
            },
            batch_snapshot_hash=batch_snapshot_hash,
        )
        pair_state["pair_closed"] = True
        pair_state["pair_row"] = pair_row
        return pair_row, primary_positive_event

    def _build_pair_row(
        self,
        *,
        plan: _PairExecutionPlan,
        primary_terminal_row: Mapping[str, object],
        shadow_terminal_row: Mapping[str, object],
        primary_variant_evidence: Mapping[str, object],
        shadow_variant_evidence: Mapping[str, object],
        committed_user_ids: Sequence[str] | None = None,
    ) -> dict[str, object]:
        committed_user_set = set(committed_user_ids or [])

        def _precision(value: float, override: str | None) -> str:
            return override if override is not None else _full_precision_cell(value)

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
            "base_network_relevance_full_precision": _precision(
                plan.score.base_network_relevance,
                plan.score.base_network_relevance_full_precision,
            ),
            "campaign_engaged_neighbor_count": plan.score.engaged_neighbor_count,
            "campaign_engaged_neighbor_signal": round(plan.score.engaged_neighbor_signal, 12),
            "campaign_engaged_neighbor_signal_full_precision": _precision(
                plan.score.engaged_neighbor_signal,
                plan.score.engaged_neighbor_signal_full_precision,
            ),
            "historical_tag_affinity": CONCURRENT_MESSAGE_HISTORY_AFFINITY,
            "raw_message_user_fit": round(plan.score.raw_message_user_fit, 12),
            "raw_message_user_fit_full_precision": _precision(
                plan.score.raw_message_user_fit,
                plan.score.raw_message_user_fit_full_precision,
            ),
            "normalized_message_user_fit": round(plan.score.normalized_message_user_fit, 12),
            "normalized_message_user_fit_full_precision": _precision(
                plan.score.normalized_message_user_fit,
                plan.score.normalized_message_user_fit_full_precision,
            ),
            "personalized_delivery_score": round(plan.score.personalized_delivery_score, 12),
            "personalized_delivery_score_full_precision": _precision(
                plan.score.personalized_delivery_score,
                plan.score.personalized_delivery_score_full_precision,
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
            "campaign_feedback_committed": _csv_bool(
                primary_terminal_row["action"] in CONCURRENT_MESSAGE_POSITIVE_ACTIONS
                and plan.user.user_id in committed_user_set
            ),
            "pair_terminal_coverage": _csv_bool(True),
            "paired_decision_coverage": _csv_bool(
                primary_terminal_row["terminal_status"] == "succeeded"
                and shadow_terminal_row["terminal_status"] == "succeeded"
            ),
            "_terminal_rows": [dict(safe_data(primary_terminal_row)), dict(safe_data(shadow_terminal_row))],
            "_variant_evidence": [
                dict(safe_data(primary_variant_evidence)),
                dict(safe_data(shadow_variant_evidence)),
            ],
        }
        return pair_row

    def _restore_runtime_state(
        self,
        *,
        replay: Mapping[str, object],
        cohort: _PreparedResearchCohort,
        messages_by_id: Mapping[str, ExperimentalMessageDefinition],
    ) -> dict[str, Any]:
        status = _require_mapping(replay.get("status"), "replay status")
        records = replay.get("records", [])
        if not isinstance(records, Sequence):
            raise TypeError("replay records must be a sequence")

        candidate_rows: list[dict[str, object]] = []
        pair_rows: list[dict[str, object]] = []
        terminal_rows: list[dict[str, object]] = []
        variant_evidence_rows: list[dict[str, object]] = []
        step_rows: list[_BatchStepSummary] = []
        campaign_engaged_user_ids: set[str] = set()
        exposed_by_message = {message.message_id: set[str]() for message in self.config.messages}
        pair_schedule_position = 0
        batches_by_time_step: dict[int, dict[str, Any]] = {}
        batches_by_snapshot_hash: dict[str, dict[str, Any]] = {}

        def _canonical_candidate_row(row: Mapping[str, object]) -> dict[str, object]:
            fieldnames = [
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
            ]
            return {field: row[field] for field in fieldnames if field in row}

        def _canonical_terminal_row(row: Mapping[str, object]) -> dict[str, object]:
            fieldnames = [
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
                "terminal_status",
                "provider_status",
                "engage",
                "probability",
                "confidence",
                "action",
                "reason",
                "decision_source",
                "failure_type",
                "provider_metadata",
            ]
            return {field: row[field] for field in fieldnames if field in row}

        for record in records:
            record_type = _as_str(record.get("record_type"))
            if record_type == "snapshot":
                snapshot_document = _require_mapping(record.get("snapshot_document"), "snapshot document")
                snapshot_identity = _require_mapping(snapshot_document.get("snapshot_identity"), "snapshot identity")
                payload = _require_mapping(snapshot_document.get("payload"), "snapshot payload")
                snapshot_hash = _as_str(record.get("snapshot_hash"))
                time_step = _as_int(snapshot_identity.get("time_step"))
                frozen_campaign_engaged_user_ids = [
                    _as_str(user_id)
                    for user_id in payload.get("frozen_campaign_engaged_user_ids", [])
                    if _as_str(user_id)
                ]
                batch_pair_start = len(pair_rows)
                batch_message_summaries: dict[str, _BatchMessageSummary] = {}
                batch_plans: list[_PairExecutionPlan] = []
                pair_state_by_id: dict[str, dict[str, Any]] = {}

                messages = payload.get("messages", [])
                if not isinstance(messages, Sequence):
                    raise ValueError(f"snapshot payload messages must be a sequence at time_step {time_step}")
                for message_payload_raw in messages:
                    message_payload = _require_mapping(message_payload_raw, "snapshot message")
                    message_id = _as_str(message_payload.get("message_id"))
                    message = messages_by_id[message_id]
                    ranked_candidates = message_payload.get("ranked_candidates", [])
                    if not isinstance(ranked_candidates, Sequence):
                        raise ValueError(f"snapshot ranked_candidates must be a sequence for message {message_id}")
                    candidate_rows.extend(
                        _canonical_candidate_row(cast(Mapping[str, object], safe_data(row)))
                        for row in ranked_candidates
                        if isinstance(row, Mapping)
                    )
                    selected_user_ids = [
                        _as_str(user_id) for user_id in message_payload.get("selected_user_ids", []) if _as_str(user_id)
                    ]
                    exposed_by_message[message_id].update(selected_user_ids)
                    seed_user_ids = [
                        _as_str(user_id) for user_id in message_payload.get("seed_user_ids", []) if _as_str(user_id)
                    ]
                    personalized_topup_user_ids = [
                        _as_str(user_id)
                        for user_id in message_payload.get("personalized_topup_user_ids", [])
                        if _as_str(user_id)
                    ]
                    selection_reason_counts_raw = message_payload.get("selection_reason_counts", {})
                    if not isinstance(selection_reason_counts_raw, Mapping):
                        raise ValueError(f"selection_reason_counts must be a mapping for message {message_id}")
                    selection_reason_counts = {
                        str(reason): _as_int(count) for reason, count in selection_reason_counts_raw.items()
                    }
                    batch_message_summaries[message_id] = {
                        "message_id": message_id,
                        "message_title": _as_str(message_payload.get("message_title")),
                        "eligible_users": _as_int(message_payload.get("eligible_users")),
                        "ranked_candidates": len(ranked_candidates),
                        "selected_user_ids": selected_user_ids,
                        "seed_user_ids": seed_user_ids,
                        "personalized_topup_user_ids": personalized_topup_user_ids,
                        "primary_positive_user_ids": [],
                        "primary_provider_failed_user_ids": [],
                        "shadow_provider_failed_user_ids": [],
                        "below_delivery_capacity": _as_int(message_payload.get("below_delivery_capacity")),
                        "selection_reason_counts": dict(sorted(selection_reason_counts.items())),
                    }
                    selected_pair_plans = message_payload.get("selected_pair_plans", [])
                    if not isinstance(selected_pair_plans, Sequence):
                        raise ValueError(f"selected_pair_plans must be a sequence for message {message_id}")
                    for plan_payload_raw in selected_pair_plans:
                        plan_payload = _require_mapping(plan_payload_raw, "selected pair plan")
                        pair_id = _as_str(plan_payload.get("pair_id"))
                        user_id = _as_str(plan_payload.get("user_id"))
                        user = cohort.users_by_id[user_id]
                        score = _MessageScore(
                            user_id=user_id,
                            base_network_relevance=float(plan_payload.get("base_network_relevance", 0.0)),
                            engaged_neighbor_count=_as_int(plan_payload.get("campaign_engaged_neighbor_count")),
                            engaged_neighbor_signal=float(plan_payload.get("campaign_engaged_neighbor_signal", 0.0)),
                            raw_message_user_fit=float(plan_payload.get("raw_message_user_fit", 0.0)),
                            normalized_message_user_fit=float(plan_payload.get("normalized_message_user_fit", 0.0)),
                            personalized_delivery_score=float(plan_payload.get("personalized_delivery_score", 0.0)),
                            base_network_relevance_full_precision=_as_str(
                                plan_payload.get("base_network_relevance_full_precision")
                            )
                            or None,
                            engaged_neighbor_signal_full_precision=_as_str(
                                plan_payload.get("campaign_engaged_neighbor_signal_full_precision")
                            )
                            or None,
                            raw_message_user_fit_full_precision=_as_str(
                                plan_payload.get("raw_message_user_fit_full_precision")
                            )
                            or None,
                            normalized_message_user_fit_full_precision=_as_str(
                                plan_payload.get("normalized_message_user_fit_full_precision")
                            )
                            or None,
                            personalized_delivery_score_full_precision=_as_str(
                                plan_payload.get("personalized_delivery_score_full_precision")
                            )
                            or None,
                        )
                        pair_plan = _PairExecutionPlan(
                            pair_id=pair_id,
                            pair_schedule_position=_as_int(plan_payload.get("pair_schedule_position")),
                            time_step=_as_int(plan_payload.get("time_step", time_step)),
                            message=message,
                            user=user,
                            profile=_primary_variant_profile(user),
                            ranking_position=_as_int(plan_payload.get("ranking_position")),
                            selection_reason=_as_str(plan_payload.get("selection_reason")),
                            score=score,
                        )
                        batch_plans.append(pair_plan)
                        pair_state_by_id[pair_id] = {
                            "plan": pair_plan,
                            "primary_started": False,
                            "shadow_started": False,
                            "primary_terminal_row": None,
                            "shadow_terminal_row": None,
                            "primary_variant_evidence": None,
                            "shadow_variant_evidence": None,
                            "pair_closed": False,
                            "pair_row": None,
                        }
                        pair_schedule_position = max(
                            pair_schedule_position,
                            _as_int(plan_payload.get("pair_schedule_position")) + 1,
                        )

                batches_by_time_step[time_step] = {
                    "time_step": time_step,
                    "batch_snapshot_hash": snapshot_hash,
                    "batch_pair_start": batch_pair_start,
                    "batch_message_summaries": batch_message_summaries,
                    "batch_plans": batch_plans,
                    "pair_state_by_id": pair_state_by_id,
                    "frozen_campaign_engaged_user_ids": frozen_campaign_engaged_user_ids,
                    "primary_positive_user_ids": set[str](),
                    "terminal_row_start": len(terminal_rows),
                    "next_pair_index": 0,
                    "committed_user_ids": [],
                    "committed": False,
                }
                batches_by_snapshot_hash[snapshot_hash] = batches_by_time_step[time_step]
                continue

            if record_type == "event":
                event_type = _as_str(record.get("event_type"))
                if event_type == "run_started":
                    continue
                if event_type in {"run_finalized", "run_published"}:
                    continue
                batch_snapshot_hash = _as_str(record.get("batch_snapshot_hash"))
                if batch_snapshot_hash not in batches_by_snapshot_hash:
                    raise ValueError(f"event {event_type} references an unknown snapshot hash")
                batch_state = batches_by_snapshot_hash[batch_snapshot_hash]
                if event_type == "batch_committed":
                    payload = _require_mapping(record.get("payload"), "event payload")
                    committed_user_ids = [
                        _as_str(user_id) for user_id in payload.get("committed_user_ids", []) if _as_str(user_id)
                    ]
                    expected_committed_user_ids = sorted(batch_state["primary_positive_user_ids"])
                    if committed_user_ids != expected_committed_user_ids:
                        raise ValueError("batch_committed committed_user_ids do not match replayed primary positives")
                    batch_state["committed_user_ids"] = committed_user_ids
                    batch_state["committed"] = True
                    campaign_engaged_user_ids.update(committed_user_ids)
                    batch_pair_start = _as_int(batch_state["batch_pair_start"])
                    for pair_row in pair_rows[batch_pair_start:]:
                        pair_row["campaign_feedback_committed"] = _csv_bool(
                            pair_row["primary_action"] in CONCURRENT_MESSAGE_POSITIVE_ACTIONS
                            and str(pair_row["user_id"]) in committed_user_ids
                        )
                    step_rows.append(
                        {
                            "time_step": batch_state["time_step"],
                            "frozen_campaign_engaged_user_ids": list(batch_state["frozen_campaign_engaged_user_ids"]),
                            "deduplicated_committed_primary_positive_user_ids": committed_user_ids,
                            "messages": [
                                batch_state["batch_message_summaries"][message.message_id]
                                for message in self.config.messages
                            ],
                        }
                    )
                    continue
                event_identity = _require_mapping(record.get("event_identity"), "event identity")
                pair_id = _as_str(event_identity.get("pair_id"))
                pair_state = batch_state["pair_state_by_id"].get(pair_id)
                if not isinstance(pair_state, dict):
                    raise ValueError(f"event {event_type} references an unknown pair_id {pair_id}")

                if event_type == "variant_started":
                    decision_variant = _as_str(event_identity.get("decision_variant"))
                    pair_state[f"{decision_variant}_started"] = True
                    continue

                if event_type == "variant_terminal":
                    decision_variant = _as_str(event_identity.get("decision_variant"))
                    payload = _require_mapping(record.get("payload"), "event payload")
                    terminal_row = _require_mapping(payload.get("terminal_row"), "terminal row")
                    variant_evidence = _require_mapping(payload.get("variant_evidence"), "variant evidence")
                    pair_state[f"{decision_variant}_terminal_row"] = dict(safe_data(terminal_row))
                    pair_state[f"{decision_variant}_variant_evidence"] = dict(safe_data(variant_evidence))
                    terminal_rows.append(_canonical_terminal_row(cast(Mapping[str, object], safe_data(terminal_row))))
                    variant_evidence_rows.append(dict(safe_data(variant_evidence)))
                    continue

                if event_type == "pair_closed":
                    plan = cast(_PairExecutionPlan, pair_state["plan"])
                    primary_terminal_row = pair_state["primary_terminal_row"]
                    shadow_terminal_row = pair_state["shadow_terminal_row"]
                    primary_variant_evidence = pair_state["primary_variant_evidence"]
                    shadow_variant_evidence = pair_state["shadow_variant_evidence"]
                    if not isinstance(primary_terminal_row, Mapping) or not isinstance(shadow_terminal_row, Mapping):
                        raise ValueError(f"pair_closed encountered before both terminals for pair {pair_id}")
                    if not isinstance(primary_variant_evidence, Mapping) or not isinstance(
                        shadow_variant_evidence, Mapping
                    ):
                        raise ValueError(
                            f"pair_closed encountered before both variant evidence rows for pair {pair_id}"
                        )
                    pair_row = self._build_pair_row(
                        plan=plan,
                        primary_terminal_row=primary_terminal_row,
                        shadow_terminal_row=shadow_terminal_row,
                        primary_variant_evidence=primary_variant_evidence,
                        shadow_variant_evidence=shadow_variant_evidence,
                    )
                    pair_row.pop("_terminal_rows", None)
                    pair_row.pop("_variant_evidence", None)
                    pair_rows.append(pair_row)
                    pair_state["pair_closed"] = True
                    pair_state["pair_row"] = pair_row
                    batch_state["next_pair_index"] = _as_int(batch_state["next_pair_index"]) + 1
                    if pair_row["primary_action"] in CONCURRENT_MESSAGE_POSITIVE_ACTIONS:
                        batch_state["primary_positive_user_ids"].add(str(pair_row["user_id"]))
                    message_summary = batch_state["batch_message_summaries"][plan.message.message_id]
                    if pair_row["primary_status"] == "provider_failed":
                        message_summary["primary_provider_failed_user_ids"].append(str(pair_row["user_id"]))
                    if pair_row["shadow_status"] == "provider_failed":
                        message_summary["shadow_provider_failed_user_ids"].append(str(pair_row["user_id"]))
                    if (
                        pair_row["primary_status"] == "succeeded"
                        and pair_row["primary_action"] in CONCURRENT_MESSAGE_POSITIVE_ACTIONS
                    ):
                        message_summary["primary_positive_user_ids"].append(str(pair_row["user_id"]))
                    continue

                raise ValueError(f"unsupported replay event type: {event_type}")

        next_time_step = _as_int(status.get("committed_batch_count"))
        active_batch = batches_by_time_step.get(next_time_step)
        if isinstance(active_batch, dict) and bool(active_batch.get("committed")):
            active_batch = None
        return {
            "candidate_rows": candidate_rows,
            "pair_rows": pair_rows,
            "terminal_rows": terminal_rows,
            "variant_evidence_rows": variant_evidence_rows,
            "step_rows": step_rows,
            "campaign_engaged_user_ids": campaign_engaged_user_ids,
            "exposed_by_message": exposed_by_message,
            "pair_schedule_position": pair_schedule_position,
            "active_batch": active_batch,
            "next_time_step": next_time_step,
        }

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
        sampling_status: str,
        production_deploy_eligible: bool,
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
        config_snapshot = self.config.snapshot(
            sampling_status=sampling_status,
            production_deploy_eligible=production_deploy_eligible,
        )
        return {
            "schema_version": CONCURRENT_MESSAGE_VALIDATION_VERSION,
            "runtime_version": CONCURRENT_MESSAGE_RUNTIME_VERSION,
            "sampling_method": SEED_FIRST_SAMPLING_METHOD,
            "sampling_status": sampling_status,
            "descriptive_only": True,
            "non_causal": True,
            "production_deploy_eligible": production_deploy_eligible,
            "configuration": config_snapshot,
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


def _full_precision_cell(value: float) -> str:
    return format(value, ".17g")
