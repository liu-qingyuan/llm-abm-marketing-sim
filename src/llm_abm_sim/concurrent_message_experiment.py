from __future__ import annotations

import csv
import html
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .decision import EngageDecision, LLMDecisionAdapter
from .final_research import (
    _TARGET_DELIVERY_RANKING_POLICY,
    REQUIRED_DATASET_FILES,
    SAMPLE_CSV_FIELDS,
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
    _runtime_user_profile,
    _RuntimeDecisionAttempt,
    _safe_runtime_rows,
    _write_csv,
    _write_json,
)
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
CONCURRENT_MESSAGE_CANDIDATE_FIELDS = (
    "time_step",
    "message_id",
    "user_id",
    "is_seed",
    "selected",
    "selection_reason",
    "ranking_position",
    "base_network_relevance",
    "campaign_engaged_neighbor_count",
    "campaign_engaged_neighbor_signal",
    "historical_tag_affinity",
    "raw_message_user_fit",
    "normalized_message_user_fit",
    "personalized_delivery_score",
)
CONCURRENT_MESSAGE_PAIR_FIELDS = (
    "pair_id",
    "pair_schedule_position",
    "time_step",
    "message_id",
    "message_title",
    "user_id",
    "latent_class",
    "is_seed",
    "selection_reason",
    "ranking_position",
    "base_network_relevance",
    "campaign_engaged_neighbor_count",
    "campaign_engaged_neighbor_signal",
    "historical_tag_affinity",
    "raw_message_user_fit",
    "normalized_message_user_fit",
    "personalized_delivery_score",
    "primary_status",
    "primary_action",
    "primary_probability",
    "primary_confidence",
    "primary_reason",
    "primary_decision_source",
    "primary_provider_metadata",
    "shadow_status",
    "shadow_action",
    "shadow_probability",
    "shadow_confidence",
    "shadow_reason",
    "shadow_decision_source",
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
        _write_json(output_path / CONCURRENT_MESSAGE_CONFIG_JSON, self.config.snapshot())
        _write_json(
            output_path / CONCURRENT_MESSAGE_MESSAGE_JSON,
            [message.model_dump(mode="json") for message in self.config.messages],
        )
        _write_json(
            output_path / CONCURRENT_MESSAGE_SAMPLE_JSON,
            [user.model_dump(mode="json") for user in sample_users],
            preserve_user_text=True,
        )
        _write_csv(
            output_path / CONCURRENT_MESSAGE_SAMPLE_CSV,
            list(SAMPLE_CSV_FIELDS),
            [user.sample_row() for user in sample_users],
            preserve_user_text=True,
        )
        if cohort.sample_audit:
            _write_json(output_path / CONCURRENT_MESSAGE_SEED_AUDIT_JSON, cohort.sample_audit)

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
                            "campaign_engaged_neighbor_count": score.engaged_neighbor_count,
                            "campaign_engaged_neighbor_signal": round(score.engaged_neighbor_signal, 12),
                            "historical_tag_affinity": CONCURRENT_MESSAGE_HISTORY_AFFINITY,
                            "raw_message_user_fit": round(score.raw_message_user_fit, 12),
                            "normalized_message_user_fit": round(score.normalized_message_user_fit, 12),
                            "personalized_delivery_score": round(score.personalized_delivery_score, 12),
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
                            profile=_runtime_user_profile(user),
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
        _write_csv(output_path / CONCURRENT_MESSAGE_CANDIDATE_CSV, list(CONCURRENT_MESSAGE_CANDIDATE_FIELDS), safe_candidate_rows)
        _write_csv(output_path / CONCURRENT_MESSAGE_PAIR_CSV, list(CONCURRENT_MESSAGE_PAIR_FIELDS), safe_pair_rows)
        _write_csv(
            output_path / CONCURRENT_MESSAGE_TERMINAL_CSV,
            list(CONCURRENT_MESSAGE_TERMINAL_FIELDS),
            safe_terminal_rows,
        )
        _write_json(output_path / CONCURRENT_MESSAGE_STEP_JSON, step_rows)

        validation_summary = self._validation_summary(
            cohort=cohort,
            pair_rows=safe_pair_rows,
            terminal_rows=safe_terminal_rows,
            step_rows=step_rows,
        )
        _write_json(output_path / CONCURRENT_MESSAGE_VALIDATION_JSON, validation_summary)
        (output_path / CONCURRENT_MESSAGE_REPORT_HTML).write_text(
            self._render_report(validation_summary=validation_summary, pair_rows=safe_pair_rows, step_rows=step_rows),
            encoding="utf-8",
        )
        return output_path

    def _execute_pair(
        self,
        *,
        plan: _PairExecutionPlan,
        primary_provider_metadata: Mapping[str, object],
        shadow_provider_metadata: Mapping[str, object],
    ) -> tuple[dict[str, object], dict[str, str] | None]:
        primary_attempt = _attempt_runtime_decision(
            adapter=self.primary_adapter,
            post=plan.message.as_post(),
            profile=plan.profile,
            peer_context=PeerContext(),
            platform_context=PlatformContext(),
            time_step=plan.time_step,
            schedule_position=plan.pair_schedule_position,
            video_id=plan.message.message_id,
            provider_metadata=primary_provider_metadata,
        )
        shadow_attempt = _attempt_runtime_decision(
            adapter=self.shadow_adapter,
            post=plan.message.as_post(),
            profile=plan.profile,
            peer_context=PeerContext(),
            platform_context=PlatformContext(),
            time_step=plan.time_step,
            schedule_position=plan.pair_schedule_position,
            video_id=plan.message.message_id,
            provider_metadata=shadow_provider_metadata,
        )
        primary_terminal_row, primary_positive_event = self._terminal_row(
            pair_id=plan.pair_id,
            pair_schedule_position=plan.pair_schedule_position,
            time_step=plan.time_step,
            message_id=plan.message.message_id,
            user_id=plan.user.user_id,
            decision_variant="primary",
            attempt=primary_attempt,
            default_provider_metadata=primary_provider_metadata,
        )
        shadow_terminal_row, _ = self._terminal_row(
            pair_id=plan.pair_id,
            pair_schedule_position=plan.pair_schedule_position,
            time_step=plan.time_step,
            message_id=plan.message.message_id,
            user_id=plan.user.user_id,
            decision_variant="shadow",
            attempt=shadow_attempt,
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
            "is_seed": _csv_bool(plan.user.is_seed),
            "selection_reason": plan.selection_reason,
            "ranking_position": plan.ranking_position,
            "base_network_relevance": round(plan.score.base_network_relevance, 12),
            "campaign_engaged_neighbor_count": plan.score.engaged_neighbor_count,
            "campaign_engaged_neighbor_signal": round(plan.score.engaged_neighbor_signal, 12),
            "historical_tag_affinity": CONCURRENT_MESSAGE_HISTORY_AFFINITY,
            "raw_message_user_fit": round(plan.score.raw_message_user_fit, 12),
            "normalized_message_user_fit": round(plan.score.normalized_message_user_fit, 12),
            "personalized_delivery_score": round(plan.score.personalized_delivery_score, 12),
            "primary_status": primary_terminal_row["terminal_status"],
            "primary_action": primary_terminal_row["action"],
            "primary_probability": primary_terminal_row["probability"],
            "primary_confidence": primary_terminal_row["confidence"],
            "primary_reason": primary_terminal_row["reason"],
            "primary_decision_source": primary_terminal_row["decision_source"],
            "primary_provider_metadata": primary_terminal_row["provider_metadata"],
            "shadow_status": shadow_terminal_row["terminal_status"],
            "shadow_action": shadow_terminal_row["action"],
            "shadow_probability": shadow_terminal_row["probability"],
            "shadow_confidence": shadow_terminal_row["confidence"],
            "shadow_reason": shadow_terminal_row["reason"],
            "shadow_decision_source": shadow_terminal_row["decision_source"],
            "shadow_provider_metadata": shadow_terminal_row["provider_metadata"],
            "campaign_feedback_committed": "false",
            "pair_terminal_coverage": _csv_bool(True),
            "paired_decision_coverage": _csv_bool(
                primary_terminal_row["terminal_status"] == "succeeded"
                and shadow_terminal_row["terminal_status"] == "succeeded"
            ),
            "_terminal_rows": [primary_terminal_row, shadow_terminal_row],
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
        decision_variant: Literal["primary", "shadow"],
        attempt: _RuntimeDecisionAttempt,
        default_provider_metadata: Mapping[str, object],
    ) -> tuple[dict[str, object], dict[str, str] | None]:
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
                "terminal_status": "provider_failed",
                "provider_status": "provider_failed",
                "engage": "",
                "probability": "",
                "confidence": "",
                "action": "",
                "reason": "",
                "decision_source": "",
                "failure_type": provider_failure["failure_type"],
                "provider_metadata": provider_failure["provider_metadata"],
            }
            return terminal_row, None

        assert isinstance(decision, EngageDecision)
        terminal_row = {
            "terminal_row_id": f"{pair_id}:{decision_variant}",
            "pair_id": pair_id,
            "pair_schedule_position": pair_schedule_position,
            "time_step": time_step,
            "message_id": message_id,
            "user_id": user_id,
            "decision_variant": decision_variant,
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
                decision.provider_metadata if decision.provider_metadata is not None else default_provider_metadata
            ),
        }
        positive_event = (
            {"message_id": message_id, "user_id": user_id, "action": decision.action}
            if decision_variant == "primary" and decision.action in CONCURRENT_MESSAGE_POSITIVE_ACTIONS
            else None
        )
        return terminal_row, positive_event

    def _validation_summary(
        self,
        *,
        cohort: _PreparedResearchCohort,
        pair_rows: Sequence[Mapping[str, object]],
        terminal_rows: Sequence[Mapping[str, object]],
        step_rows: Sequence[_BatchStepSummary],
    ) -> dict[str, object]:
        sample_user_ids = list(cohort.sample_user_ids)
        exposures = len(pair_rows)
        primary_successes = sum(row["primary_status"] == "succeeded" for row in pair_rows)
        primary_failures = sum(row["primary_status"] == "provider_failed" for row in pair_rows)
        shadow_successes = sum(row["shadow_status"] == "succeeded" for row in pair_rows)
        shadow_failures = sum(row["shadow_status"] == "provider_failed" for row in pair_rows)
        paired_successes = sum(row["paired_decision_coverage"] == "true" for row in pair_rows)
        per_message_counts: dict[str, dict[str, object]] = {}
        for message in self.config.messages:
            message_rows = [row for row in pair_rows if row["message_id"] == message.message_id]
            per_message_counts[message.message_id] = {
                "message_title": message.title,
                "intended_audience_segment": message.intended_audience_segment,
                "exposures": len(message_rows),
                "primary_successes": sum(row["primary_status"] == "succeeded" for row in message_rows),
                "primary_failures": sum(row["primary_status"] == "provider_failed" for row in message_rows),
                "shadow_successes": sum(row["shadow_status"] == "succeeded" for row in message_rows),
                "shadow_failures": sum(row["shadow_status"] == "provider_failed" for row in message_rows),
                "below_delivery_capacity": len(set(sample_user_ids) - {str(row["user_id"]) for row in message_rows}),
            }
        distinct_exposed_users = len({str(row["user_id"]) for row in pair_rows})
        coverage_counts = Counter(
            sum(str(row["user_id"]) == user_id for row in pair_rows)
            for user_id in sample_user_ids
        )
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
            "counts": {
                "sample_users": len(sample_user_ids),
                "messages": len(self.config.messages),
                "eligible_user_message_pairs": len(sample_user_ids) * len(self.config.messages),
                "actual_exposures": exposures,
                "distinct_exposed_users": distinct_exposed_users,
                "primary_attempted": exposures,
                "primary_successes": primary_successes,
                "primary_failures": primary_failures,
                "shadow_attempted": exposures,
                "shadow_successes": shadow_successes,
                "shadow_failures": shadow_failures,
                "terminal_rows": len(terminal_rows),
                "pair_terminal_coverage": 1.0 if exposures == 0 else len(terminal_rows) / (exposures * 2),
                "paired_decision_coverage": 0.0 if exposures == 0 else paired_successes / exposures,
            },
            "campaign_exposure_coverage": {
                str(message_count): coverage_counts.get(message_count, 0)
                for message_count in range(len(self.config.messages) + 1)
            },
            "per_message": per_message_counts,
            "steps": list(step_rows),
        }

    def _render_report(
        self,
        *,
        validation_summary: Mapping[str, object],
        pair_rows: Sequence[Mapping[str, object]],
        step_rows: Sequence[_BatchStepSummary],
    ) -> str:
        counts = validation_summary["counts"]
        assert isinstance(counts, Mapping)
        per_message = validation_summary["per_message"]
        assert isinstance(per_message, Mapping)
        summary_items = [
            ("Research sample", str(counts["sample_users"])),
            ("Eligible user-message pairs", str(counts["eligible_user_message_pairs"])),
            ("Actual exposures", str(counts["actual_exposures"])),
            ("Primary success / fail", f"{counts['primary_successes']} / {counts['primary_failures']}"),
            ("Shadow success / fail", f"{counts['shadow_successes']} / {counts['shadow_failures']}"),
            ("Pair terminal coverage", f"{float(counts['pair_terminal_coverage']):.2f}"),
            ("Paired decision coverage", f"{float(counts['paired_decision_coverage']):.2f}"),
            ("Production deploy eligible", "false"),
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
        pair_rows_html = "".join(
            "<tr>"
            f"<td>{row['time_step']}</td>"
            f"<td>{html.escape(str(row['message_id']))}</td>"
            f"<td>{html.escape(str(row['user_id']))}</td>"
            f"<td>{html.escape(str(row['latent_class']))}</td>"
            f"<td>{row['ranking_position']}</td>"
            f"<td>{row['selection_reason']}</td>"
            f"<td>{row['personalized_delivery_score']}</td>"
            f"<td>{row['primary_status']}</td>"
            f"<td>{html.escape(str(row['primary_action']))}</td>"
            f"<td>{row['shadow_status']}</td>"
            f"<td>{html.escape(str(row['shadow_action']))}</td>"
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
        summary_html = "".join(
            f"<div class=\"metric\"><span>{html.escape(label)}</span><strong>{html.escape(value)}</strong></div>"
            for label, value in summary_items
        )
        return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>{html.escape(self.config.report.title)}</title>
  <style>
    :root {{ color-scheme: light; }}
    body {{ margin: 0; font: 14px/1.5 -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; color: #102033; background: #f6f8fb; }}
    main {{ max-width: 1360px; margin: 0 auto; padding: 32px 20px 48px; }}
    h1, h2 {{ margin: 0 0 12px; }}
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
    <div class=\"banner\">
      <h1>{html.escape(self.config.report.title)}</h1>
      <p>This tracer is validation-only, descriptive, and non-causal. It is not a formal release artifact and cannot be deployed.</p>
      <p class=\"muted\">The runner freezes three message queues batch-by-batch, records paired Primary/Shadow terminal rows, and keeps production_deploy_eligible=false.</p>
    </div>
    <div class=\"metrics\">{summary_html}</div>
    <section>
      <h2>Message Summary</h2>
      <div class=\"table-wrap\">
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
      <div class=\"table-wrap\">
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
      <div class=\"table-wrap\">
        <table>
          <thead>
            <tr><th>Batch</th><th>Message</th><th>User</th><th>Class</th><th>Rank</th><th>Selection</th><th>Score</th><th>Primary status</th><th>Primary action</th><th>Shadow status</th><th>Shadow action</th><th>Feedback committed</th></tr>
          </thead>
          <tbody>{pair_rows_html}</tbody>
        </table>
      </div>
    </section>
  </main>
</body>
</html>
"""


def _step_message_summary(message_summary: _BatchMessageSummary) -> str:
    return f"{message_summary['message_id']}: {len(message_summary['selected_user_ids'])}"
