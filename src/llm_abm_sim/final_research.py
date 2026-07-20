from __future__ import annotations

import ast
import csv
import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .decision import EngageDecision, LLMDecisionAdapter, ProviderDecisionError
from .final_research_report import (
    FINAL_RESEARCH_DYNAMIC_NETWORK_FORMULA,
    FINAL_RESEARCH_RANKING_RUNTIME_VERSION,
    FINAL_RESEARCH_REPORT_ARTIFACTS,
    FINAL_RESEARCH_RUNTIME_VERSION,
    FINAL_RESEARCH_SCHEDULE_METHOD,
    FINAL_RESEARCH_SCORE_USAGE,
    FINAL_RESEARCH_SEED_STEP,
    FINAL_RESEARCH_USER_OPPORTUNITY_LIMIT,
    FinalResearchReportSource,
    FinalResearchReportWriter,
)
from .ranking_diagnostics import MAIN_RANKING_WEIGHTS, RankingDiagnosticArtifacts, RankingDiagnostics
from .safe_serialization import safe_data, safe_json, safe_user_data, safe_user_json
from .schemas import (
    LATENT_PROFILE_LABEL_FIELDS,
    LATENT_VALUE_DIMENSIONS,
    LEGACY_DEMO_PRESET_FIELDS,
    FailClosedAction,
    PeerContext,
    PlatformContext,
    PostContent,
    ProviderLLMConfig,
    ReportConfig,
    UserProfile,
)

TARGET_VIDEO_ID = "7328592728139353363"
TARGET_NETWORK_SCOPE = "锦江酒店"
PROFILE_INDEX_METHOD = "log1p_p95_reference_weighted_v2"
NETWORK_AUGMENTED_SAMPLE_AUDIT_VERSION = "network-augmented-sample-audit-v1"
SEED_FIRST_SAMPLE_AUDIT_VERSION = "seed-first-sample-audit-v1"
SEED_FIRST_SAMPLING_METHOD = "seed_first_research_sample_v1"
HISTORICAL_SAMPLING_METHOD = "network_augmented_research_sample"
VALIDATION_RUN_STATUS = "validation_run"
FORMAL_RUN_STATUS = "persisted_seed_first_formal_run"
PRIMARY_SOURCE_SCOPE_QUOTA = 100
OFFLINE_BASELINE_VERSION = "final-research-offline-v2"
TARGET_DELIVERY_BASE_NETWORK_WEIGHT = MAIN_RANKING_WEIGHTS.base_network
TARGET_DELIVERY_ENGAGED_NEIGHBOR_WEIGHT = MAIN_RANKING_WEIGHTS.engaged_neighbor
TARGET_DELIVERY_TAG_AFFINITY_WEIGHT = MAIN_RANKING_WEIGHTS.tag_affinity
TARGET_DELIVERY_CAPACITY = 20
TARGET_DELIVERY_RUNTIME_VERSION = FINAL_RESEARCH_RANKING_RUNTIME_VERSION
TARGET_DELIVERY_SCHEDULE_METHOD = "global_stable_reranking_top20"
TARGET_DELIVERY_RANKING_FORMULA = (
    "0.50 * base_network_relevance + 0.30 * engaged_neighbor_signal + 0.20 * historical_tag_affinity"
)
TARGET_DELIVERY_ENGAGED_NEIGHBOR_FORMULA = "min(1, engaged_neighbor_count / 3)"
UNOBSERVED_PAIR_SEMANTICS = "No observed interaction is not evidence that a user saw the target video and chose ignore."
REQUIRED_DATASET_FILES = ("videos.csv", "users.csv")
SAMPLE_CSV_FIELDS = (
    "user_id",
    "nickname",
    "bio",
    "signature",
    "interest_tags",
    "follower_count",
    "following_count",
    "video_count",
    "activity_score",
    "activity_video_score",
    "activity_comment_score",
    "activity_reply_score",
    "global_influence_score",
    "local_influence_score",
    "local_network_score",
    "local_recognition_score",
    "sample_source_scope",
    "is_seed",
    "sample_role",
    "latent_attribute_spec_id",
    "latent_attribute_method",
    "latent_attribute_seed",
    "latent_class",
    "latent_environmental_consciousness_coef",
    *(f"latent_{dimension}_value_weight" for dimension in LATENT_VALUE_DIMENSIONS),
    *(f"latent_{field_name}" for field_name in LATENT_PROFILE_LABEL_FIELDS),
)
SCORE_CSV_FIELDS = (
    "user_id",
    "target_scope_weighted_degree",
    "base_network_relevance",
    "base_network_score",
    "historical_tag_affinity",
    "recommendation_score",
    "has_non_target_history",
    "has_network_connection",
    "has_historical_tag_affinity",
)
RUNTIME_STEP_CSV_FIELDS = (
    "time_step",
    "assigned_users",
    "seed_users",
    "target_exposures",
    "background_impressions",
    "decisions",
    "engagements",
    "ignored",
    "provider_failed",
)
RUNTIME_EXPOSURE_CSV_FIELDS = (
    "schedule_position",
    "user_id",
    "video_id",
    "time_step",
    "assigned_step",
    "is_seed",
    "base_network_score",
    "dynamic_network_score",
    "engaged_neighbor_count",
    "historical_tag_affinity",
    "recommendation_score",
    "random_draw",
    "exposure_outcome",
)
RUNTIME_DECISION_CSV_FIELDS = (
    "schedule_position",
    "user_id",
    "video_id",
    "time_step",
    "engage",
    "probability",
    "reason",
    "confidence",
    "action",
    "decision_source",
    "provider_metadata",
)
RUNTIME_ACTION_CSV_FIELDS = (
    "schedule_position",
    "user_id",
    "video_id",
    "time_step",
    "action",
)
RUNTIME_BACKGROUND_CSV_FIELDS = (
    "schedule_position",
    "user_id",
    "video_id",
    "time_step",
    "recommendation_score",
    "random_draw",
)
RUNTIME_PROVIDER_FAILURE_CSV_FIELDS = (
    "schedule_position",
    "user_id",
    "video_id",
    "time_step",
    "failure_type",
    "provider_metadata",
)
RANKING_RUNTIME_STEP_CSV_FIELDS = (
    "time_step",
    "eligible_users",
    "ranked_candidates",
    "selected_users",
    "seed_users",
    "target_exposures",
    "decisions",
    "engagements",
    "ignored",
    "provider_failed",
    "below_delivery_capacity",
)
RANKING_RUNTIME_CANDIDATE_CSV_FIELDS = (
    "time_step",
    "ranking_position",
    "user_id",
    "is_seed",
    "selected",
    "base_network_relevance",
    "engaged_neighbor_count",
    "engaged_neighbor_signal",
    "historical_tag_affinity",
    "recommendation_score",
)
RANKING_RUNTIME_OUTCOME_CSV_FIELDS = (
    "user_id",
    "video_id",
    "is_seed",
    "exposure_time_step",
    "ranking_position",
    "result_status",
    "provider_status",
)
RANKING_ABLATION_DIAGNOSTIC_CSV_FIELDS = (
    "time_step",
    "user_id",
    "full_rank",
    "no_network_rank",
    "network_rank_delta",
    "full_selected",
    "no_network_selected",
    "selection_effect",
    "base_network_relevance",
    "engaged_neighbor_signal",
    "historical_tag_affinity",
)
RANKING_WEIGHT_SENSITIVITY_CSV_FIELDS = (
    "time_step",
    "variant_id",
    "base_network_weight",
    "engaged_neighbor_weight",
    "tag_affinity_weight",
    "eligible_count",
    "selected_count",
    "top_user_ids",
    "overlap_with_main_count",
    "overlap_with_main_user_ids",
    "added_vs_main_user_ids",
    "removed_vs_main_user_ids",
)


class FinalResearchModel(str, Enum):
    PROBABILITY_V1 = "probability_v1"
    TARGET_DELIVERY_RANKING_V2 = "target_delivery_ranking_v2"


@dataclass(frozen=True)
class _ResearchModelPolicy:
    model: FinalResearchModel
    augment_network_sample: bool
    sampling_method: str
    network_normalization: str
    network_weight: float
    tag_affinity_weight: float
    static_formula: str
    offline_manifest_version: str


_TARGET_DELIVERY_RANKING_POLICY = _ResearchModelPolicy(
    model=FinalResearchModel.TARGET_DELIVERY_RANKING_V2,
    augment_network_sample=True,
    sampling_method=SEED_FIRST_SAMPLING_METHOD,
    network_normalization="log_p95_weighted_degree",
    network_weight=TARGET_DELIVERY_BASE_NETWORK_WEIGHT,
    tag_affinity_weight=TARGET_DELIVERY_TAG_AFFINITY_WEIGHT,
    static_formula=(
        "0.50 * base_network_relevance + 0.20 * historical_tag_affinity "
        "(static portion of the predeclared 0.50/0.30/0.20 ranking model)"
    ),
    offline_manifest_version=OFFLINE_BASELINE_VERSION,
)


class FinalResearchConfig(BaseModel):
    """Validated inputs for the single-target final research workflow."""

    model_config = ConfigDict(extra="forbid")

    dataset_dir: Path
    target_video_id: str = TARGET_VIDEO_ID
    research_model: FinalResearchModel = FinalResearchModel.TARGET_DELIVERY_RANKING_V2
    sample_size: int = Field(default=1000, ge=1)
    horizon: int = Field(default=30, ge=1)
    random_seed: int = 20260713
    network_weight: float = Field(default=0.70, ge=0.0, le=1.0)
    tag_affinity_weight: float = Field(default=0.30, ge=0.0, le=1.0)
    neighbor_boost: float = Field(default=0.20, ge=0.0, le=1.0)
    provider: ProviderLLMConfig = Field(default_factory=ProviderLLMConfig)
    report: ReportConfig = Field(default_factory=ReportConfig)

    @field_validator("target_video_id")
    @classmethod
    def _target_video_is_fixed(cls, value: str) -> str:
        if value != TARGET_VIDEO_ID:
            raise ValueError(f"target_video_id must be the approved real target video {TARGET_VIDEO_ID}")
        return value

    @model_validator(mode="after")
    def _validate_dataset_and_weights(self) -> FinalResearchConfig:
        if not math.isclose(self.network_weight + self.tag_affinity_weight, 1.0, abs_tol=1e-9):
            raise ValueError("network_weight and tag_affinity_weight must sum to 1.0")
        if self.provider.enabled:
            if self.provider.fail_closed_action is not FailClosedAction.RAISE:
                raise ValueError("enabled final research provider must use fail_closed_action=raise")
            if self.horizon != 30:
                raise ValueError("enabled final research runtime requires horizon=30")
            if self.provider.prompt_version != "jinjiang-green-marketing-prompt-v2":
                raise ValueError("enabled final research runtime requires jinjiang-green-marketing-prompt-v2")

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
                if _cell(row, "video_id") == self.target_video_id:
                    target_exists = True
                    break
        if not target_exists:
            raise ValueError(f"target video {self.target_video_id} is absent from videos.csv")

        user_ids: set[str] = set()
        with (dataset_dir / "users.csv").open(encoding="utf-8", newline="") as handle:
            for row_number, row in enumerate(csv.DictReader(handle), start=2):
                user_id = _cell(row, "user_id")
                if not user_id:
                    raise ValueError(f"users.csv row {row_number} has an empty user_id")
                if user_id in user_ids:
                    raise ValueError(f"users.csv contains duplicate user_id: {user_id}")
                user_ids.add(user_id)
        if self.sample_size > len(user_ids):
            raise ValueError(f"sample_size {self.sample_size} exceeds available user count {len(user_ids)}")
        self.dataset_dir = dataset_dir
        return self

    def snapshot(self) -> dict[str, object]:
        return {
            "dataset_dir": str(self.dataset_dir),
            "target_video_id": self.target_video_id,
            "research_model": self.research_model.value,
            "sample_size": self.sample_size,
            "horizon": self.horizon,
            "horizon_semantics": "fixed recommendation batches, not natural days",
            "user_opportunity_limit": 1,
            "random_seed": self.random_seed,
            "network_weight": self.network_weight,
            "tag_affinity_weight": self.tag_affinity_weight,
            "neighbor_boost": self.neighbor_boost,
            "target_delivery_ranking_weights": {
                "base_network_relevance": TARGET_DELIVERY_BASE_NETWORK_WEIGHT,
                "engaged_neighbor_signal": TARGET_DELIVERY_ENGAGED_NEIGHBOR_WEIGHT,
                "historical_tag_affinity": TARGET_DELIVERY_TAG_AFFINITY_WEIGHT,
            },
            "provider": self.provider.safe_metadata(),
            "report": self.report.model_dump(mode="json"),
        }


def _research_model_policy(config: FinalResearchConfig) -> _ResearchModelPolicy:
    if config.research_model is FinalResearchModel.PROBABILITY_V1:
        return _ResearchModelPolicy(
            model=FinalResearchModel.PROBABILITY_V1,
            augment_network_sample=False,
            sampling_method="source_scope_stratified_sample_v1",
            network_normalization="max_weighted_degree",
            network_weight=config.network_weight,
            tag_affinity_weight=config.tag_affinity_weight,
            static_formula=("network_weight * base_network_score + tag_affinity_weight * historical_tag_affinity"),
            offline_manifest_version="final-research-offline-v1",
        )
    return _TARGET_DELIVERY_RANKING_POLICY


class TargetVideo(BaseModel):
    """Real target video fields allowed before holdout revelation."""

    model_config = ConfigDict(extra="forbid")

    video_id: str
    source_challenge_name: str
    source_challenge_rank: int
    caption: str
    hashtags: list[str]
    creator_user_id: str
    video_url: str


class ResearchUser(BaseModel):
    """Observed profile plus virtual labels and holdout-safe runtime proxies."""

    model_config = ConfigDict(extra="forbid")

    user_id: str
    nickname: str = ""
    bio: str = ""
    signature: str = ""
    interest_tags: list[str] = Field(default_factory=list)
    follower_count: int = 0
    following_count: int = 0
    video_count: int = 0
    activity_score: float = 0.0
    activity_video_score: float = 0.0
    activity_comment_score: float = 0.0
    activity_reply_score: float = 0.0
    global_influence_score: float = 0.0
    local_influence_score: float = 0.0
    local_network_score: float = 0.0
    local_recognition_score: float = 0.0
    latent_attributes: dict[str, str | int | float]
    sample_source_scope: str = ""
    is_seed: bool = False
    sample_role: Literal["seed", "network_cohort", "ordinary"] = "ordinary"

    def sample_row(self) -> dict[str, object]:
        row = self.model_dump(exclude={"latent_attributes"})
        row["is_seed"] = _csv_bool(self.is_seed)
        row["interest_tags"] = _json_cell(self.interest_tags)
        row.update(self.latent_attributes)
        return {field: row.get(field, "") for field in SAMPLE_CSV_FIELDS}


class OfflineRecommendationScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    target_scope_weighted_degree: int
    base_network_relevance: float | None = None
    base_network_score: float
    historical_tag_affinity: float
    recommendation_score: float
    has_non_target_history: bool
    has_network_connection: bool
    has_historical_tag_affinity: bool

    def csv_row(self) -> dict[str, object]:
        row = self.model_dump()
        for key in ("has_non_target_history", "has_network_connection", "has_historical_tag_affinity"):
            row[key] = _csv_bool(bool(row[key]))
        return row


class _DynamicRecommendationScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    base_network_score: float
    dynamic_network_score: float
    engaged_neighbor_count: int
    historical_tag_affinity: float
    recommendation_score: float


class RankingCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    base_network_relevance: float
    engaged_neighbor_count: int
    engaged_neighbor_signal: float
    historical_tag_affinity: float
    recommendation_score: float


@dataclass(frozen=True)
class _RuntimeArtifacts:
    steps: list[dict[str, object]]
    exposures: list[dict[str, object]]
    decisions: list[dict[str, object]]
    actions: list[dict[str, object]]
    background_events: list[dict[str, object]]
    provider_failures: list[dict[str, object]]
    summary: dict[str, object]
    decision_adapter_calls: int


@dataclass(frozen=True)
class _RankingRuntimeArtifacts:
    steps: list[dict[str, object]]
    candidates: list[dict[str, object]]
    outcomes: list[dict[str, object]]
    decisions: list[dict[str, object]]
    actions: list[dict[str, object]]
    provider_failures: list[dict[str, object]]
    summary: dict[str, object]
    decision_adapter_calls: int


@dataclass(frozen=True)
class _BatchRuntimeInput:
    user_id: str
    user: ResearchUser
    is_seed: bool
    dynamic_score: _DynamicRecommendationScore
    peer_context: PeerContext
    draw: float | None
    target_exposed: bool


@dataclass(frozen=True)
class _RuntimeDecisionAttempt:
    decision: EngageDecision | None
    provider_failure: dict[str, object] | None


@dataclass(frozen=True)
class _VideoRecord:
    video_id: str
    source_challenge_name: str
    source_challenge_rank: int
    caption: str
    hashtags: tuple[str, ...]
    creator_user_id: str
    video_url: str


@dataclass(frozen=True)
class _CommentRecord:
    comment_id: str
    video_id: str
    parent_comment_id: str
    commenter_user_id: str
    mentioned_user_ids: tuple[str, ...]
    like_count: int
    comment_level: str


@dataclass(frozen=True)
class _PreparedInputs:
    target_video: TargetVideo
    users_by_id: dict[str, ResearchUser]
    sample_user_ids: list[str]
    base_sample_user_ids: list[str]
    seed_user_ids: list[str]
    network_cohort_user_ids: list[str]
    network_cohort_added_user_ids: list[str]
    replaced_ordinary_user_ids: list[str]
    final_sample_user_ids: list[str]
    historical_video_count: int
    historical_interaction_rows: int
    thresholds: dict[str, float]
    historical_interaction_user_ids: set[str]
    historical_tags_by_user: dict[str, set[str]]
    target_scope_weighted_degree: dict[str, int]
    target_scope_neighbors: dict[str, set[str]]
    source_scope_sample_counts: dict[str, int]
    base_source_scope_sample_counts: dict[str, int]
    final_source_scope_sample_counts: dict[str, int]
    target_scope_p95_weighted_degree: float
    sampling_method: str
    sample_audit: dict[str, object]


@dataclass(frozen=True)
class _SampleSelection:
    sampling_method: str
    seed_user_ids: list[str]
    neighbor_user_ids: list[str]
    ordinary_user_ids: list[str]
    sample_user_ids: list[str]
    scope_by_user: dict[str, str]
    source_scope_counts: dict[str, int]
    audit: dict[str, object]


class _SeedFirstSampleModule:
    """Select a deterministic seed-first sample from holdout-safe inputs."""

    def __init__(
        self,
        *,
        users_by_id: Mapping[str, ResearchUser],
        videos: Mapping[str, _VideoRecord],
        comments: Sequence[_CommentRecord],
        target_scope_neighbors: Mapping[str, set[str]],
        target_scope_edge_weights: Mapping[tuple[str, str], int],
        sample_size: int,
        random_seed: int,
    ) -> None:
        self.users_by_id = users_by_id
        self.videos = videos
        self.comments = comments
        self.target_scope_neighbors = target_scope_neighbors
        self.target_scope_edge_weights = target_scope_edge_weights
        self.sample_size = sample_size
        self.random_seed = random_seed

    def build(self) -> _SampleSelection:
        eligible_user_ids = sorted(self.users_by_id)
        influence_top_k = min(10, max(1, self.sample_size // 2))
        global_top = sorted(
            eligible_user_ids,
            key=lambda user_id: (-self.users_by_id[user_id].global_influence_score, user_id),
        )[:influence_top_k]
        local_top = sorted(
            eligible_user_ids,
            key=lambda user_id: (-self.users_by_id[user_id].local_influence_score, user_id),
        )[:influence_top_k]
        seed_user_ids = sorted(set(global_top) | set(local_top))
        seed_set = set(seed_user_ids)

        neighbor_strengths: dict[str, int] = {}
        for seed_user_id in seed_user_ids:
            for neighbor_user_id in self.target_scope_neighbors.get(seed_user_id, set()):
                if neighbor_user_id not in self.users_by_id or neighbor_user_id in seed_set:
                    continue
                edge_key = _graph_edge_key(seed_user_id, neighbor_user_id)
                neighbor_strengths[neighbor_user_id] = neighbor_strengths.get(neighbor_user_id, 0) + int(
                    self.target_scope_edge_weights.get(edge_key, 0)
                )
        ranked_neighbors = sorted(neighbor_strengths, key=lambda user_id: (-neighbor_strengths[user_id], user_id))
        neighbor_capacity = self.sample_size - len(seed_user_ids)
        neighbor_user_ids = ranked_neighbors[:neighbor_capacity]
        neighbor_set = set(neighbor_user_ids)

        scope_order, primary_scope_by_user, tied_primary_scope_user_ids = _primary_source_scopes(
            videos=self.videos,
            comments=self.comments,
            available_user_ids=set(eligible_user_ids),
        )
        scope_quotas = _source_scope_quotas(scope_order, self.sample_size)
        selected_set = seed_set | neighbor_set
        selected_counts = Counter(primary_scope_by_user.get(user_id, "remaining_users") for user_id in selected_set)
        ordinary_user_ids: list[str] = []
        quota_audit: list[dict[str, object]] = []
        for scope_name in scope_order:
            quota = scope_quotas.get(scope_name, 0)
            preselected_count = selected_counts.get(scope_name, 0)
            remaining_quota = max(0, quota - preselected_count)
            candidates = sorted(
                user_id
                for user_id, primary_scope in primary_scope_by_user.items()
                if primary_scope == scope_name and user_id not in selected_set
            )
            rng = random.Random(_stable_seed(self.random_seed, f"seed-first-scope:{scope_name}"))
            rng.shuffle(candidates)
            remaining_sample_slots = self.sample_size - len(selected_set)
            selected_for_scope = candidates[: min(remaining_quota, remaining_sample_slots)]
            ordinary_user_ids.extend(selected_for_scope)
            selected_set.update(selected_for_scope)
            quota_audit.append(
                {
                    "scope": scope_name,
                    "quota": quota,
                    "preselected_seed_or_neighbor_count": preselected_count,
                    "available_ordinary_count": len(candidates),
                    "ordinary_selected_count": len(selected_for_scope),
                    "scope_shortfall": max(0, remaining_quota - len(selected_for_scope)),
                }
            )

        fallback_needed = self.sample_size - len(selected_set)
        fallback_candidates = sorted(set(eligible_user_ids) - selected_set)
        fallback_rng = random.Random(_stable_seed(self.random_seed, "seed-first-scope-fallback"))
        fallback_rng.shuffle(fallback_candidates)
        fallback_user_ids = fallback_candidates[:fallback_needed]
        ordinary_user_ids.extend(fallback_user_ids)
        selected_set.update(fallback_user_ids)
        if len(selected_set) != self.sample_size:
            raise ValueError(
                f"could not select {self.sample_size} unique seed-first users; selected {len(selected_set)}"
            )

        sample_user_ids = [*seed_user_ids, *neighbor_user_ids, *ordinary_user_ids]
        scope_by_user = {user_id: primary_scope_by_user.get(user_id, "remaining_users") for user_id in sample_user_ids}
        source_scope_counts = dict(sorted(Counter(scope_by_user.values()).items()))
        role_user_ids = {
            "seed": sorted(seed_user_ids),
            "network_cohort": sorted(neighbor_user_ids),
            "ordinary": sorted(ordinary_user_ids),
        }
        role_counts = {role: len(user_ids) for role, user_ids in role_user_ids.items()}
        audit: dict[str, object] = {
            "schema_version": SEED_FIRST_SAMPLE_AUDIT_VERSION,
            "sampling_method": SEED_FIRST_SAMPLING_METHOD,
            "sampling_status": VALIDATION_RUN_STATUS,
            "eligible_pool": {
                "count": len(eligible_user_ids),
                "user_ids": eligible_user_ids,
                "target_holdout_used": False,
            },
            "seed_selection": {
                "selection_stage": "eligible_full_pool_before_sampling",
                "requested_top_k_per_proxy": 10,
                "effective_top_k_per_proxy": influence_top_k,
                "global_top10_user_ids": global_top,
                "local_top10_user_ids": local_top,
                "seed_user_ids": seed_user_ids,
                "seed_count": len(seed_user_ids),
                "deduplicated_union": True,
                "tie_break": "descending proxy score, then user_id ascending",
            },
            "neighbor_selection": {
                "candidate_count": len(ranked_neighbors),
                "selected_count": len(neighbor_user_ids),
                "capacity": neighbor_capacity,
                "selected_user_ids": neighbor_user_ids,
                "candidates": [
                    {
                        "user_id": user_id,
                        "seed_edge_weight": neighbor_strengths[user_id],
                        "selected": user_id in neighbor_set,
                    }
                    for user_id in ranked_neighbors
                ],
                "historical_set_only": True,
                "direct_neighbors_only": True,
                "tie_break": "descending total historical edge weight to seeds, then user_id ascending",
            },
            "scope_selection": {
                "scope_order": scope_order,
                "per_scope_quota": PRIMARY_SOURCE_SCOPE_QUOTA,
                "primary_scope_tie_break": "source_challenge_rank ascending, then source name ascending",
                "tied_primary_scope_user_count": len(tied_primary_scope_user_ids),
                "tied_primary_scope_user_ids": tied_primary_scope_user_ids,
                "quota_rows": quota_audit,
                "fallback": {
                    "needed_count": fallback_needed,
                    "selected_user_ids": sorted(fallback_user_ids),
                    "random_seed": _stable_seed(self.random_seed, "seed-first-scope-fallback"),
                    "reason": "scope quota shortage or seed/neighbor scope overage",
                },
            },
            "roles": {"counts": role_counts, "user_ids": role_user_ids},
            "final_sample": {
                "count": len(sample_user_ids),
                "unique_user_count": len(set(sample_user_ids)),
                "user_ids": sorted(sample_user_ids),
                "source_scope_counts": source_scope_counts,
                "primary_scope_by_user": dict(sorted(scope_by_user.items())),
            },
            "source_dataset_modified": False,
        }
        return _SampleSelection(
            sampling_method=SEED_FIRST_SAMPLING_METHOD,
            seed_user_ids=seed_user_ids,
            neighbor_user_ids=neighbor_user_ids,
            ordinary_user_ids=ordinary_user_ids,
            sample_user_ids=sample_user_ids,
            scope_by_user=scope_by_user,
            source_scope_counts=source_scope_counts,
            audit=audit,
        )


class _ResearchInputBuilder:
    def __init__(self, config: FinalResearchConfig, model_policy: _ResearchModelPolicy) -> None:
        self.config = config
        self.model_policy = model_policy

    def prepare(self) -> _PreparedInputs:
        videos = self._load_videos()
        historical_comments = self._load_comments(holdout=False)
        profile_rows = _read_csv_rows(self.config.dataset_dir / "users.csv")
        target_record = videos[self.config.target_video_id]
        target_video = TargetVideo(
            video_id=target_record.video_id,
            source_challenge_name=target_record.source_challenge_name,
            source_challenge_rank=target_record.source_challenge_rank,
            caption=target_record.caption,
            hashtags=list(target_record.hashtags),
            creator_user_id=target_record.creator_user_id,
            video_url=target_record.video_url,
        )
        historical_videos = {video_id: video for video_id, video in videos.items() if video_id != target_video.video_id}

        all_history_degree = _weighted_degrees(historical_videos, historical_comments)
        target_scope_video_ids = {
            video_id
            for video_id, video in historical_videos.items()
            if video.source_challenge_name == TARGET_NETWORK_SCOPE
        }
        target_scope_comments = [
            comment for comment in historical_comments if comment.video_id in target_scope_video_ids
        ]
        target_scope_degree, target_scope_neighbors, target_scope_edge_weights = _weighted_graph_details(
            historical_videos,
            target_scope_comments,
        )
        history_counts, history_likes, historical_tags_by_user = _historical_user_signals(
            historical_videos,
            historical_comments,
        )
        thresholds = _holdout_safe_thresholds(profile_rows, history_counts, history_likes, all_history_degree)
        users_by_id = _build_research_users(
            profile_rows,
            history_counts=history_counts,
            history_likes=history_likes,
            all_history_degree=all_history_degree,
            thresholds=thresholds,
        )
        if self.model_policy.sampling_method == SEED_FIRST_SAMPLING_METHOD:
            selection = _SeedFirstSampleModule(
                users_by_id=users_by_id,
                videos=historical_videos,
                comments=historical_comments,
                target_scope_neighbors=target_scope_neighbors,
                target_scope_edge_weights=target_scope_edge_weights,
                sample_size=self.config.sample_size,
                random_seed=self.config.random_seed,
            ).build()
            sample_user_ids = selection.sample_user_ids
            base_sample_user_ids: list[str] = []
            seed_user_ids = selection.seed_user_ids
            network_cohort_user_ids = selection.neighbor_user_ids
            network_cohort_added_user_ids = list(network_cohort_user_ids)
            replaced_ordinary_user_ids: list[str] = []
            final_sample_user_ids = list(sample_user_ids)
            base_scope_by_user: dict[str, str] = {}
            final_scope_by_user = dict(selection.scope_by_user)
            sample_scope_by_user = dict(selection.scope_by_user)
            sample_audit = selection.audit
        else:
            base_sample_user_ids, base_scope_by_user = _sample_users(
                videos=historical_videos,
                comments=historical_comments,
                available_user_ids=set(users_by_id),
                sample_size=self.config.sample_size,
                random_seed=self.config.random_seed,
            )
            seed_user_ids = _select_seeds(base_sample_user_ids, users_by_id)
            network_cohort_user_ids = []
            network_cohort_added_user_ids = []
            replaced_ordinary_user_ids = []
            final_sample_user_ids = list(base_sample_user_ids)
            final_scope_by_user = dict(base_scope_by_user)
            sample_user_ids = list(base_sample_user_ids)
            sample_scope_by_user = dict(base_scope_by_user)
            sample_audit = {}
        seed_set = set(seed_user_ids)
        network_cohort_set = set(network_cohort_user_ids)
        for user_id in sample_user_ids:
            user = users_by_id[user_id]
            users_by_id[user_id] = user.model_copy(
                update={
                    "sample_source_scope": sample_scope_by_user.get(user_id, "remaining_users"),
                    "is_seed": user_id in seed_set,
                    "sample_role": (
                        "seed"
                        if user_id in seed_set
                        else "network_cohort"
                        if user_id in network_cohort_set
                        else "ordinary"
                    ),
                }
            )
        target_scope_p95_weighted_degree = round(
            _percentile(
                (target_scope_degree.get(user_id, 0) for user_id in users_by_id),
                0.95,
            ),
            6,
        )
        return _PreparedInputs(
            target_video=target_video,
            users_by_id=users_by_id,
            sample_user_ids=sample_user_ids,
            base_sample_user_ids=base_sample_user_ids,
            seed_user_ids=seed_user_ids,
            network_cohort_user_ids=network_cohort_user_ids,
            network_cohort_added_user_ids=network_cohort_added_user_ids,
            replaced_ordinary_user_ids=replaced_ordinary_user_ids,
            final_sample_user_ids=final_sample_user_ids,
            historical_video_count=len(historical_videos),
            historical_interaction_rows=len(historical_comments),
            thresholds=thresholds,
            historical_interaction_user_ids=set(history_counts),
            historical_tags_by_user=historical_tags_by_user,
            target_scope_weighted_degree=target_scope_degree,
            target_scope_neighbors=target_scope_neighbors,
            source_scope_sample_counts=dict(sorted(Counter(sample_scope_by_user.values()).items())),
            base_source_scope_sample_counts=dict(sorted(Counter(base_scope_by_user.values()).items())),
            final_source_scope_sample_counts=dict(sorted(Counter(final_scope_by_user.values()).items())),
            target_scope_p95_weighted_degree=target_scope_p95_weighted_degree,
            sampling_method=self.model_policy.sampling_method,
            sample_audit=sample_audit,
        )

    def reveal_holdout(self) -> list[_CommentRecord]:
        """Load target interaction answers only after static scoring is complete."""

        return self._load_comments(holdout=True)

    def _load_videos(self) -> dict[str, _VideoRecord]:
        videos: dict[str, _VideoRecord] = {}
        for row_number, row in enumerate(_read_csv_rows(self.config.dataset_dir / "videos.csv"), start=2):
            video_id = _cell(row, "video_id")
            if not video_id:
                raise ValueError(f"videos.csv row {row_number} has an empty video_id")
            if video_id in videos:
                raise ValueError(f"videos.csv contains duplicate video_id: {video_id}")
            videos[video_id] = _VideoRecord(
                video_id=video_id,
                source_challenge_name=_cell(row, "source_challenge_name"),
                source_challenge_rank=_int_cell(row, "source_challenge_rank"),
                caption=_cell(row, "caption"),
                hashtags=tuple(_parse_list(_cell(row, "hashtags"))),
                creator_user_id=_cell(row, "creator_user_id"),
                video_url=_cell(row, "video_url"),
            )
        return videos

    def _load_comments(self, *, holdout: bool) -> list[_CommentRecord]:
        path = self.config.dataset_dir / "all_comments.csv"
        if not path.is_file():
            path = self.config.dataset_dir / "comments.csv"
        comments: list[_CommentRecord] = []
        seen_ids: set[str] = set()
        for row_number, row in enumerate(_read_csv_rows(path), start=2):
            comment_id = _cell(row, "comment_id")
            if not comment_id:
                raise ValueError(f"{path.name} row {row_number} has an empty comment_id")
            if comment_id in seen_ids:
                raise ValueError(f"{path.name} contains duplicate comment_id: {comment_id}")
            seen_ids.add(comment_id)
            is_holdout = _cell(row, "video_id") == self.config.target_video_id
            if is_holdout != holdout:
                continue
            level = _cell(row, "comment_level").lower()
            if level not in {"comment", "reply"}:
                level = "reply" if _has_parent(_cell(row, "parent_comment_id")) else "comment"
            comments.append(
                _CommentRecord(
                    comment_id=comment_id,
                    video_id=_cell(row, "video_id"),
                    parent_comment_id=_cell(row, "parent_comment_id"),
                    commenter_user_id=_cell(row, "commenter_user_id"),
                    mentioned_user_ids=tuple(_parse_list(_cell(row, "mentioned_user_ids"))),
                    like_count=_int_cell(row, "like_count"),
                    comment_level=level,
                )
            )
        return comments


class PlatformRecommendationModel:
    """Recommendation scoring and direct-neighbor runtime feedback."""

    def __init__(
        self,
        config: FinalResearchConfig,
        prepared: _PreparedInputs,
        model_policy: _ResearchModelPolicy,
    ) -> None:
        self.config = config
        self.prepared = prepared
        self.model_policy = model_policy
        if model_policy.network_normalization == "log_p95_weighted_degree":
            self._base_network_scores = {
                user_id: _log_p95_score(degree, prepared.target_scope_p95_weighted_degree)
                for user_id, degree in prepared.target_scope_weighted_degree.items()
            }
        else:
            max_degree = max(prepared.target_scope_weighted_degree.values(), default=0)
            self._base_network_scores = {
                user_id: (degree / max_degree if max_degree > 0 else 0.0)
                for user_id, degree in prepared.target_scope_weighted_degree.items()
            }
        self._target_tags = set(prepared.target_video.hashtags)
        self._target_exposed_user_ids: set[str] = set()
        self._engaged_actions: dict[str, str] = {}

    def _historical_tag_affinity(self, user_id: str) -> float:
        history_tags = self.prepared.historical_tags_by_user.get(user_id, set())
        return len(self._target_tags & history_tags) / max(len(self._target_tags), 1)

    def score_static(self, user_id: str) -> OfflineRecommendationScore:
        affinity = self._historical_tag_affinity(user_id)
        base_network_score = self._base_network_scores.get(user_id, 0.0)
        score = self.model_policy.network_weight * base_network_score + self.model_policy.tag_affinity_weight * affinity
        base_network_relevance = (
            base_network_score if self.model_policy.model is FinalResearchModel.TARGET_DELIVERY_RANKING_V2 else None
        )
        return OfflineRecommendationScore(
            user_id=user_id,
            target_scope_weighted_degree=self.prepared.target_scope_weighted_degree.get(user_id, 0),
            base_network_relevance=round(base_network_relevance, 6) if base_network_relevance is not None else None,
            base_network_score=round(base_network_score, 6),
            historical_tag_affinity=round(affinity, 6),
            recommendation_score=round(score, 6),
            has_non_target_history=user_id in self.prepared.historical_interaction_user_ids,
            has_network_connection=base_network_score > 0.0,
            has_historical_tag_affinity=affinity > 0.0,
        )

    def score_all(self) -> list[OfflineRecommendationScore]:
        return [self.score_static(user_id) for user_id in sorted(self.prepared.users_by_id)]

    def score_dynamic(self, user_id: str) -> _DynamicRecommendationScore:
        neighbors = self.prepared.target_scope_neighbors.get(user_id, set())
        engaged_neighbor_count = len(neighbors & self._engaged_actions.keys())
        base_network_score = self._base_network_scores.get(user_id, 0.0)
        dynamic_network_score = min(
            1.0,
            base_network_score + self.config.neighbor_boost * engaged_neighbor_count,
        )
        affinity = self._historical_tag_affinity(user_id)
        recommendation_score = (
            self.config.network_weight * dynamic_network_score + self.config.tag_affinity_weight * affinity
        )
        return _DynamicRecommendationScore(
            user_id=user_id,
            base_network_score=round(base_network_score, 6),
            dynamic_network_score=round(dynamic_network_score, 6),
            engaged_neighbor_count=engaged_neighbor_count,
            historical_tag_affinity=round(affinity, 6),
            recommendation_score=round(recommendation_score, 6),
        )

    @staticmethod
    def rank_candidates(candidates: Iterable[RankingCandidate]) -> list[RankingCandidate]:
        return sorted(candidates, key=lambda candidate: (-candidate.recommendation_score, candidate.user_id))

    def rank_eligible_users(self, user_ids: Iterable[str]) -> list[RankingCandidate]:
        candidates: list[RankingCandidate] = []
        for user_id in user_ids:
            neighbors = self.prepared.target_scope_neighbors.get(user_id, set())
            engaged_neighbor_count = len(neighbors & self._engaged_actions.keys())
            engaged_neighbor_signal = min(1.0, engaged_neighbor_count / 3)
            base_network_relevance = self._base_network_scores.get(user_id, 0.0)
            historical_tag_affinity = self._historical_tag_affinity(user_id)
            recommendation_score = (
                TARGET_DELIVERY_BASE_NETWORK_WEIGHT * base_network_relevance
                + TARGET_DELIVERY_ENGAGED_NEIGHBOR_WEIGHT * engaged_neighbor_signal
                + TARGET_DELIVERY_TAG_AFFINITY_WEIGHT * historical_tag_affinity
            )
            candidates.append(
                RankingCandidate(
                    user_id=user_id,
                    base_network_relevance=base_network_relevance,
                    engaged_neighbor_count=engaged_neighbor_count,
                    engaged_neighbor_signal=engaged_neighbor_signal,
                    historical_tag_affinity=historical_tag_affinity,
                    recommendation_score=recommendation_score,
                )
            )
        return self.rank_candidates(candidates)

    def peer_context(self, user_id: str) -> PeerContext:
        neighbors = self.prepared.target_scope_neighbors.get(user_id, set())
        engaged_neighbor_ids = neighbors & self._engaged_actions.keys()
        exposed_neighbor_ids = neighbors & self._target_exposed_user_ids
        actions = [self._engaged_actions[neighbor_id] for neighbor_id in engaged_neighbor_ids]
        return PeerContext(
            engaged_neighbors=len(engaged_neighbor_ids),
            exposed_neighbors=len(exposed_neighbor_ids),
            visible_likes=actions.count("like"),
            visible_comments=actions.count("comment"),
            visible_shares=actions.count("share"),
        )

    def record_target_exposure(self, user_id: str) -> None:
        self._target_exposed_user_ids.add(user_id)

    def record_engagement(self, user_id: str, action: str) -> None:
        if action in {"like", "comment", "share"}:
            self._engaged_actions[user_id] = action


class FinalResearchRunner:
    """Write deterministic final-research diagnostics and optional provider runtime artifacts."""

    def __init__(self, config: FinalResearchConfig, decision_adapter: LLMDecisionAdapter) -> None:
        self.config = config
        self.decision_adapter = decision_adapter

    def run_and_write(self, output_dir: str | Path) -> Path:
        output_path = Path(output_dir)
        dataset_path = self.config.dataset_dir.resolve()
        if output_path.resolve().is_relative_to(dataset_path):
            raise ValueError("output_dir must be outside dataset_dir")
        if output_path.exists() and any(output_path.iterdir()):
            raise FileExistsError(f"output_dir already exists and is not empty: {output_path}")
        output_path.mkdir(parents=True, exist_ok=True)

        model_policy = _research_model_policy(self.config)
        builder = _ResearchInputBuilder(self.config, model_policy)
        prepared = builder.prepare()
        sampling_status = (
            FORMAL_RUN_STATUS if _adapter_live_api_triggered(self.decision_adapter) else VALIDATION_RUN_STATUS
        )
        sample_audit = dict(prepared.sample_audit)
        if sample_audit:
            sample_audit["sampling_status"] = sampling_status
        platform = PlatformRecommendationModel(self.config, prepared, model_policy)
        scores = platform.score_all()
        ranked_scores = sorted(scores, key=lambda item: (-item.recommendation_score, item.user_id))
        top_scores = ranked_scores[:20]
        scores_by_user = {score.user_id: score for score in scores}
        probability_runtime: _RuntimeArtifacts | None = None
        ranking_runtime: _RankingRuntimeArtifacts | None = None
        if self.config.provider.enabled:
            if model_policy.model is FinalResearchModel.TARGET_DELIVERY_RANKING_V2:
                ranking_runtime = self._run_target_delivery_runtime(prepared, platform)
            else:
                probability_runtime = self._run_runtime(prepared, platform)
        holdout_comments = builder.reveal_holdout()
        holdout_participant_ids = sorted({comment.commenter_user_id for comment in holdout_comments})
        diagnostic = _holdout_diagnostic(holdout_participant_ids, top_scores, scores_by_user)
        ranking_diagnostics: RankingDiagnosticArtifacts | None = None
        if ranking_runtime is not None:
            ranking_diagnostics = RankingDiagnostics(
                delivery_capacity=TARGET_DELIVERY_CAPACITY,
            ).build(
                candidate_rows=ranking_runtime.candidates,
                holdout_diagnostic=diagnostic,
                batch_time_steps=[int(str(step["time_step"])) for step in ranking_runtime.steps],
            )
        score_summary = _score_summary(
            scores,
            ranked_scores,
            model_policy,
        )
        holdout_safe_audit = {
            "profile_index_method": PROFILE_INDEX_METHOD,
            "historical_video_count": prepared.historical_video_count,
            "historical_interaction_rows": prepared.historical_interaction_rows,
            "holdout_interaction_rows": len(holdout_comments),
            "holdout_unique_participant_count": len(holdout_participant_ids),
            "holdout_safe_reference_thresholds": prepared.thresholds,
            "activity_formula": (
                "0.25 * Norm(video_count) + 0.45 * Norm(historical_comment_count) + 0.30 * Norm(historical_reply_count)"
            ),
            "local_influence_formula": (
                "0.60 * Norm(historical_edge_degree) + 0.40 * Norm(historical_comment_like_sum)"
            ),
            "reference_basis": (
                "Historical Set P95 references with Norm(x)=min(1, log1p(x)/log1p(P95)); "
                "global_influence_score remains the observed source value."
            ),
            "proxy_semantics": (
                "Activity and local influence are observable research proxies, not true psychological traits, "
                "third-party indices, or causal influence measurements."
            ),
            "limitations": (
                "The dataset has no real exposure denominator and incomplete user-level like/share/collect data; "
                "holdout-safe scores support simulation analysis only."
            ),
            "sample_size": len(prepared.sample_user_ids),
            "source_scope_sample_counts": prepared.source_scope_sample_counts,
            "global_top10_local_top10_seed_union": prepared.seed_user_ids,
            "seed_count": len(prepared.seed_user_ids),
            "sampling_method": prepared.sampling_method,
            "sampling_status": sampling_status,
            "source_dataset_modified": False,
            "holdout_boundary": (
                "Target interactions and aggregate engagement counts were excluded from profile projection, "
                "sampling, seed selection, and recommendation scoring."
            ),
        }
        if model_policy.augment_network_sample:
            holdout_safe_audit.update(
                {
                    "base_source_scope_sample_counts": prepared.base_source_scope_sample_counts,
                    "final_source_scope_sample_counts": prepared.final_source_scope_sample_counts,
                    "base_network_relevance": {
                        "formula": "min(1, log1p(weighted_degree) / log1p(P95_weighted_degree))",
                        "target_source_scope": TARGET_NETWORK_SCOPE,
                        "p95_weighted_degree": prepared.target_scope_p95_weighted_degree,
                        "reference_user_count": len(prepared.users_by_id),
                        "holdout_safe": True,
                        "zero_degree_relevance": 0.0,
                    },
                }
            )

        artifacts = {
            "config_snapshot": "config_snapshot.json",
            "holdout_diagnostic": "top20_holdout_diagnostic.json",
            "holdout_safe_audit": "holdout_safe_audit.json",
            "offline_score_summary": "offline_score_summary.json",
            "offline_scores": "offline_scores.csv",
            "sample_manifest_csv": "sample_manifest.csv",
            "sample_manifest_json": "sample_manifest.json",
            "target_video_snapshot": "target_video_snapshot.json",
        }
        artifacts.update(FINAL_RESEARCH_REPORT_ARTIFACTS)
        if probability_runtime is not None:
            artifacts.update(
                {
                    "runtime_actions": "runtime_actions.csv",
                    "runtime_background_events": "runtime_background_events.csv",
                    "runtime_decisions": "runtime_decisions.csv",
                    "runtime_exposures": "runtime_exposures.csv",
                    "runtime_provider_failures": "runtime_provider_failures.csv",
                    "runtime_steps": "runtime_steps.csv",
                    "runtime_summary": "runtime_summary.json",
                }
            )
        elif ranking_runtime is not None:
            artifacts.update(
                {
                    "seed_first_sample_audit": "seed_first_sample_audit.json",
                    "ranking_ablation_diagnostics_csv": "ranking_ablation_diagnostics.csv",
                    "ranking_diagnostics": "ranking_diagnostics.json",
                    "ranking_diagnostics_summary": "ranking_diagnostics_summary.json",
                    "ranking_runtime_candidates": "ranking_runtime_candidates.csv",
                    "ranking_runtime_outcomes": "ranking_runtime_outcomes.csv",
                    "ranking_runtime_steps": "ranking_runtime_steps.csv",
                    "ranking_runtime_summary": "ranking_runtime_summary.json",
                    "ranking_weight_sensitivity_csv": "ranking_weight_sensitivity.csv",
                    "runtime_actions": "runtime_actions.csv",
                    "runtime_decisions": "runtime_decisions.csv",
                    "runtime_provider_failures": "runtime_provider_failures.csv",
                }
            )
        elif prepared.sampling_method == SEED_FIRST_SAMPLING_METHOD:
            artifacts["seed_first_sample_audit"] = "seed_first_sample_audit.json"
        sample_users = [prepared.users_by_id[user_id] for user_id in prepared.sample_user_ids]
        config_snapshot = self.config.snapshot()
        config_snapshot["sampling_method"] = prepared.sampling_method
        config_snapshot["sampling_status"] = sampling_status
        _write_json(output_path / artifacts["config_snapshot"], config_snapshot)
        _write_json(output_path / artifacts["target_video_snapshot"], prepared.target_video.model_dump(mode="json"))
        _write_json(
            output_path / artifacts["sample_manifest_json"],
            [user.model_dump(mode="json") for user in sample_users],
            preserve_user_text=True,
        )
        _write_csv(
            output_path / artifacts["sample_manifest_csv"],
            list(SAMPLE_CSV_FIELDS),
            [user.sample_row() for user in sample_users],
            preserve_user_text=True,
        )
        _write_csv(
            output_path / artifacts["offline_scores"],
            list(SCORE_CSV_FIELDS),
            [score.csv_row() for score in scores],
        )
        _write_json(
            output_path / artifacts["offline_score_summary"],
            score_summary,
        )
        _write_json(output_path / artifacts["holdout_diagnostic"], diagnostic)
        if prepared.sampling_method == SEED_FIRST_SAMPLING_METHOD:
            _write_json(
                output_path / artifacts["seed_first_sample_audit"],
                sample_audit,
            )
        if probability_runtime is not None:
            _write_csv(
                output_path / artifacts["runtime_steps"],
                list(RUNTIME_STEP_CSV_FIELDS),
                probability_runtime.steps,
            )
            _write_csv(
                output_path / artifacts["runtime_exposures"],
                list(RUNTIME_EXPOSURE_CSV_FIELDS),
                probability_runtime.exposures,
            )
            _write_csv(
                output_path / artifacts["runtime_decisions"],
                list(RUNTIME_DECISION_CSV_FIELDS),
                probability_runtime.decisions,
            )
            _write_csv(
                output_path / artifacts["runtime_actions"],
                list(RUNTIME_ACTION_CSV_FIELDS),
                probability_runtime.actions,
            )
            _write_csv(
                output_path / artifacts["runtime_background_events"],
                list(RUNTIME_BACKGROUND_CSV_FIELDS),
                probability_runtime.background_events,
            )
            _write_csv(
                output_path / artifacts["runtime_provider_failures"],
                list(RUNTIME_PROVIDER_FAILURE_CSV_FIELDS),
                probability_runtime.provider_failures,
            )
            _write_json(output_path / artifacts["runtime_summary"], probability_runtime.summary)
        if ranking_runtime is not None:
            assert ranking_diagnostics is not None
            _write_csv(
                output_path / artifacts["ranking_runtime_steps"],
                list(RANKING_RUNTIME_STEP_CSV_FIELDS),
                ranking_runtime.steps,
            )
            _write_csv(
                output_path / artifacts["ranking_runtime_candidates"],
                list(RANKING_RUNTIME_CANDIDATE_CSV_FIELDS),
                ranking_runtime.candidates,
            )
            _write_csv(
                output_path / artifacts["ranking_runtime_outcomes"],
                list(RANKING_RUNTIME_OUTCOME_CSV_FIELDS),
                ranking_runtime.outcomes,
            )
            _write_csv(
                output_path / artifacts["runtime_decisions"],
                list(RUNTIME_DECISION_CSV_FIELDS),
                ranking_runtime.decisions,
            )
            _write_csv(
                output_path / artifacts["runtime_actions"],
                list(RUNTIME_ACTION_CSV_FIELDS),
                ranking_runtime.actions,
            )
            _write_csv(
                output_path / artifacts["runtime_provider_failures"],
                list(RUNTIME_PROVIDER_FAILURE_CSV_FIELDS),
                ranking_runtime.provider_failures,
            )
            _write_json(output_path / artifacts["ranking_runtime_summary"], ranking_runtime.summary)
            _write_csv(
                output_path / artifacts["ranking_ablation_diagnostics_csv"],
                list(RANKING_ABLATION_DIAGNOSTIC_CSV_FIELDS),
                ranking_diagnostics.ablation_rows,
            )
            _write_csv(
                output_path / artifacts["ranking_weight_sensitivity_csv"],
                list(RANKING_WEIGHT_SENSITIVITY_CSV_FIELDS),
                ranking_diagnostics.sensitivity_rows,
            )
            _write_json(output_path / artifacts["ranking_diagnostics"], ranking_diagnostics.payload)
            _write_json(output_path / artifacts["ranking_diagnostics_summary"], ranking_diagnostics.summary)
        _write_json(output_path / artifacts["holdout_safe_audit"], holdout_safe_audit)
        report_config = self.config.snapshot()
        report_config["report_title"] = self.config.report.title
        report_config["network_weight"] = model_policy.network_weight
        report_config["tag_affinity_weight"] = model_policy.tag_affinity_weight
        manifest_counts = {
            "historical_videos": prepared.historical_video_count,
            "users_scored": len(scores),
            "sample_users": len(prepared.sample_user_ids),
            "seed_users": len(prepared.seed_user_ids),
            "runtime_exposures": (
                len(probability_runtime.exposures)
                if probability_runtime is not None
                else sum(row["result_status"] != "below_delivery_capacity" for row in ranking_runtime.outcomes)
                if ranking_runtime is not None
                else 0
            ),
            "runtime_decisions": (
                len(probability_runtime.decisions)
                if probability_runtime is not None
                else len(ranking_runtime.decisions)
                if ranking_runtime is not None
                else 0
            ),
            "runtime_provider_failures": (
                len(probability_runtime.provider_failures)
                if probability_runtime is not None
                else len(ranking_runtime.provider_failures)
                if ranking_runtime is not None
                else 0
            ),
        }
        if prepared.sampling_method == SEED_FIRST_SAMPLING_METHOD:
            role_counts = Counter(user.sample_role for user in sample_users)
            manifest_counts.update(
                {
                    "seed_users": role_counts["seed"],
                    "network_cohort_users": len(prepared.network_cohort_user_ids),
                    "ordinary_users": role_counts["ordinary"],
                }
            )
        if ranking_diagnostics is not None:
            observed_effect = ranking_diagnostics.summary["observed_recommendation_signal_effect"]
            assert isinstance(observed_effect, Mapping)
            manifest_counts.update(
                {
                    "ranking_diagnostic_batches": ranking_diagnostics.summary["counts"]["batches"],
                    "ranking_ablation_rows": len(ranking_diagnostics.ablation_rows),
                    "ranking_sensitivity_rows": len(ranking_diagnostics.sensitivity_rows),
                    "ranking_batches_with_network_top20_effect": observed_effect["batches_with_top_selection_change"],
                }
            )
        runtime_manifest_version = (
            TARGET_DELIVERY_RUNTIME_VERSION
            if ranking_runtime is not None
            else FINAL_RESEARCH_RUNTIME_VERSION
            if probability_runtime is not None
            else model_policy.offline_manifest_version
        )
        decision_adapter_calls = (
            ranking_runtime.decision_adapter_calls
            if ranking_runtime is not None
            else probability_runtime.decision_adapter_calls
            if probability_runtime is not None
            else 0
        )
        artifact_manifest = {
            "manifest_version": runtime_manifest_version,
            "sampling_method": prepared.sampling_method,
            "sampling_status": sampling_status,
            "sample_role_counts": dict(sorted(Counter(user.sample_role for user in sample_users).items())),
            "artifacts": artifacts,
            "counts": manifest_counts,
            "live_api_triggered": _adapter_live_api_triggered(self.decision_adapter),
            "decision_adapter_calls": decision_adapter_calls,
        }
        if ranking_diagnostics is not None:
            artifact_manifest["diagnostic_decision_adapter_calls"] = ranking_diagnostics.summary[
                "diagnostic_decision_adapter_calls"
            ]
        FinalResearchReportWriter(
            FinalResearchReportSource(
                target_video=prepared.target_video.model_dump(mode="json"),
                users=[user.model_dump(mode="json") for user in sample_users],
                historical_tags_by_user={
                    user.user_id: sorted(prepared.historical_tags_by_user.get(user.user_id, set()))
                    for user in sample_users
                },
                config=report_config,
                offline_score_summary=score_summary,
                holdout_diagnostic=diagnostic,
                holdout_safe_audit=holdout_safe_audit,
                artifact_manifest=artifact_manifest,
                runtime_steps=probability_runtime.steps if probability_runtime is not None else (),
                runtime_exposures=probability_runtime.exposures if probability_runtime is not None else (),
                runtime_decisions=(
                    ranking_runtime.decisions
                    if ranking_runtime is not None
                    else probability_runtime.decisions
                    if probability_runtime is not None
                    else ()
                ),
                runtime_provider_failures=(
                    ranking_runtime.provider_failures
                    if ranking_runtime is not None
                    else probability_runtime.provider_failures
                    if probability_runtime is not None
                    else ()
                ),
                runtime_summary=probability_runtime.summary if probability_runtime is not None else None,
                runtime_enabled=probability_runtime is not None or ranking_runtime is not None,
                offline_scores=[score.model_dump(mode="json") for score in scores],
                network_sample_audit=sample_audit or None,
                ranking_steps=ranking_runtime.steps if ranking_runtime is not None else (),
                ranking_candidates=ranking_runtime.candidates if ranking_runtime is not None else (),
                ranking_outcomes=ranking_runtime.outcomes if ranking_runtime is not None else (),
                ranking_diagnostics=(ranking_diagnostics.payload if ranking_diagnostics is not None else None),
                ranking_diagnostics_summary=(ranking_diagnostics.summary if ranking_diagnostics is not None else None),
                ranking_runtime_summary=ranking_runtime.summary if ranking_runtime is not None else None,
            )
        ).write(output_path)
        return output_path

    def _run_target_delivery_runtime(
        self,
        prepared: _PreparedInputs,
        platform: PlatformRecommendationModel,
    ) -> _RankingRuntimeArtifacts:
        post = PostContent(
            post_id=prepared.target_video.video_id,
            text=prepared.target_video.caption,
            topic_tags=list(prepared.target_video.hashtags),
        )
        provider_metadata = _adapter_safe_metadata(self.decision_adapter, self.config.provider)
        eligible_user_ids = set(prepared.sample_user_ids) - set(prepared.seed_user_ids)
        candidate_rows: list[dict[str, object]] = []
        decision_rows: list[dict[str, object]] = []
        action_rows: list[dict[str, object]] = []
        provider_failure_rows: list[dict[str, object]] = []
        outcomes_by_user: dict[str, dict[str, object]] = {}
        step_rows: list[dict[str, object]] = []
        decision_adapter_calls = 0
        schedule_position = 0

        for time_step in range(self.config.horizon):
            if time_step == 0:
                ranked_candidates = platform.rank_eligible_users(prepared.seed_user_ids)
                selected_candidates = ranked_candidates
            else:
                ranked_candidates = platform.rank_eligible_users(eligible_user_ids)
                selected_candidates = ranked_candidates[:TARGET_DELIVERY_CAPACITY]
            selected_user_ids = {candidate.user_id for candidate in selected_candidates}
            ranking_positions = {
                candidate.user_id: ranking_position
                for ranking_position, candidate in enumerate(ranked_candidates, start=1)
            }
            for ranking_position, candidate in enumerate(ranked_candidates, start=1):
                candidate_rows.append(
                    {
                        "time_step": time_step,
                        "ranking_position": ranking_position,
                        "user_id": candidate.user_id,
                        "is_seed": _csv_bool(candidate.user_id in prepared.seed_user_ids),
                        "selected": _csv_bool(candidate.user_id in selected_user_ids),
                        "base_network_relevance": round(candidate.base_network_relevance, 12),
                        "engaged_neighbor_count": candidate.engaged_neighbor_count,
                        "engaged_neighbor_signal": round(candidate.engaged_neighbor_signal, 12),
                        "historical_tag_affinity": round(candidate.historical_tag_affinity, 12),
                        "recommendation_score": round(candidate.recommendation_score, 12),
                    }
                )

            pending_target_exposures: list[str] = []
            pending_engagements: list[tuple[str, str]] = []
            step_decisions = 0
            step_engagements = 0
            step_ignored = 0
            step_provider_failed = 0
            for candidate in selected_candidates:
                user_id = candidate.user_id
                user = prepared.users_by_id[user_id]
                decision_adapter_calls += 1
                pending_target_exposures.append(user_id)
                outcome_row = {
                    "user_id": user_id,
                    "video_id": prepared.target_video.video_id,
                    "is_seed": _csv_bool(user.is_seed),
                    "exposure_time_step": time_step,
                    "ranking_position": ranking_positions[user_id],
                    "result_status": "",
                    "provider_status": "",
                }
                attempt = _attempt_runtime_decision(
                    adapter=self.decision_adapter,
                    post=post,
                    profile=_runtime_user_profile(user),
                    peer_context=PeerContext(),
                    platform_context=PlatformContext(
                        time_label=f"batch-{time_step}",
                        hot_topics=list(prepared.target_video.hashtags),
                        platform_mood="target delivery ranking exposure",
                    ),
                    time_step=time_step,
                    schedule_position=schedule_position,
                    video_id=prepared.target_video.video_id,
                    provider_metadata=provider_metadata,
                )
                if attempt.provider_failure is not None:
                    step_provider_failed += 1
                    outcome_row["result_status"] = "provider_failed"
                    outcome_row["provider_status"] = "provider_failed"
                    provider_failure_rows.append(attempt.provider_failure)
                    outcomes_by_user[user_id] = outcome_row
                    schedule_position += 1
                    continue

                decision = attempt.decision
                assert decision is not None
                step_decisions += 1
                if decision.engage:
                    step_engagements += 1
                    pending_engagements.append((user_id, decision.action))
                else:
                    step_ignored += 1
                outcome_row["result_status"] = decision.action
                outcome_row["provider_status"] = "succeeded"
                outcomes_by_user[user_id] = outcome_row
                decision_row, action_row = _runtime_decision_rows(
                    decision,
                    schedule_position=schedule_position,
                    user_id=user_id,
                    video_id=prepared.target_video.video_id,
                    time_step=time_step,
                )
                decision_rows.append(decision_row)
                action_rows.append(action_row)
                schedule_position += 1

            eligible_user_ids.difference_update(selected_user_ids)
            for user_id in pending_target_exposures:
                platform.record_target_exposure(user_id)
            for user_id, action in pending_engagements:
                platform.record_engagement(user_id, action)
            step_rows.append(
                {
                    "time_step": time_step,
                    "eligible_users": len(ranked_candidates),
                    "ranked_candidates": len(ranked_candidates),
                    "selected_users": len(selected_candidates),
                    "seed_users": len(selected_candidates) if time_step == 0 else 0,
                    "target_exposures": len(selected_candidates),
                    "decisions": step_decisions,
                    "engagements": step_engagements,
                    "ignored": step_ignored,
                    "provider_failed": step_provider_failed,
                    "below_delivery_capacity": len(ranked_candidates) - len(selected_candidates),
                }
            )

        for user_id in sorted(eligible_user_ids):
            user = prepared.users_by_id[user_id]
            outcomes_by_user[user_id] = {
                "user_id": user_id,
                "video_id": prepared.target_video.video_id,
                "is_seed": _csv_bool(user.is_seed),
                "exposure_time_step": "",
                "ranking_position": "",
                "result_status": "below_delivery_capacity",
                "provider_status": "not_called",
            }
        outcomes = [outcomes_by_user[user_id] for user_id in prepared.sample_user_ids]
        summary = {
            "runtime_version": TARGET_DELIVERY_RUNTIME_VERSION,
            "sampling_method": prepared.sampling_method,
            "sampling_status": (
                FORMAL_RUN_STATUS if _adapter_live_api_triggered(self.decision_adapter) else VALIDATION_RUN_STATUS
            ),
            "sample_role_counts": dict(
                sorted(
                    Counter(prepared.users_by_id[user_id].sample_role for user_id in prepared.sample_user_ids).items()
                )
            ),
            "horizon": self.config.horizon,
            "schedule_method": TARGET_DELIVERY_SCHEDULE_METHOD,
            "seed_step": 0,
            "non_seed_steps": [1, self.config.horizon - 1],
            "user_opportunity_limit": 1,
            "delivery_capacity": TARGET_DELIVERY_CAPACITY,
            "maximum_target_exposures": (
                len(prepared.seed_user_ids) + TARGET_DELIVERY_CAPACITY * max(0, self.config.horizon - 1)
            ),
            "ranking_formula": TARGET_DELIVERY_RANKING_FORMULA,
            "engaged_neighbor_formula": TARGET_DELIVERY_ENGAGED_NEIGHBOR_FORMULA,
            "same_batch_feedback": False,
            "decision_adapter_calls": decision_adapter_calls,
            "provider_metadata": provider_metadata,
            "counts": {
                "sample_users": len(prepared.sample_user_ids),
                "seed_users": len(prepared.seed_user_ids),
                "target_exposures": decision_adapter_calls,
                "decisions": len(decision_rows),
                "engagements": sum(row["action"] != "ignore" for row in action_rows),
                "ignored": sum(row["action"] == "ignore" for row in action_rows),
                "provider_failed": len(provider_failure_rows),
                "below_delivery_capacity": len(eligible_user_ids),
                "decision_adapter_calls": decision_adapter_calls,
            },
        }
        return _RankingRuntimeArtifacts(
            steps=step_rows,
            candidates=candidate_rows,
            outcomes=outcomes,
            decisions=decision_rows,
            actions=action_rows,
            provider_failures=provider_failure_rows,
            summary=summary,
            decision_adapter_calls=decision_adapter_calls,
        )

    def _run_runtime(
        self,
        prepared: _PreparedInputs,
        platform: PlatformRecommendationModel,
    ) -> _RuntimeArtifacts:
        assignments = _fixed_batch_assignments(prepared, self.config)
        draw_rng = random.Random(_stable_seed(self.config.random_seed, "final-research-exposure-draws"))
        post = PostContent(
            post_id=prepared.target_video.video_id,
            text=prepared.target_video.caption,
            topic_tags=list(prepared.target_video.hashtags),
        )
        provider_metadata = _adapter_safe_metadata(self.decision_adapter, self.config.provider)
        step_rows: dict[int, dict[str, object]] = {
            time_step: {
                "time_step": time_step,
                "assigned_users": 0,
                "seed_users": 0,
                "target_exposures": 0,
                "background_impressions": 0,
                "decisions": 0,
                "engagements": 0,
                "ignored": 0,
                "provider_failed": 0,
            }
            for time_step in range(self.config.horizon)
        }
        exposures: list[dict[str, object]] = []
        decisions: list[dict[str, object]] = []
        actions: list[dict[str, object]] = []
        background_events: list[dict[str, object]] = []
        provider_failures: list[dict[str, object]] = []
        decision_adapter_calls = 0
        schedule_position = 0

        for time_step in range(self.config.horizon):
            batch_inputs: list[_BatchRuntimeInput] = []
            for user_id in assignments[time_step]:
                user = prepared.users_by_id[user_id]
                dynamic_score = platform.score_dynamic(user_id)
                draw = None if user.is_seed else draw_rng.random()
                batch_inputs.append(
                    _BatchRuntimeInput(
                        user_id=user_id,
                        user=user,
                        is_seed=user.is_seed,
                        dynamic_score=dynamic_score,
                        peer_context=platform.peer_context(user_id),
                        draw=draw,
                        target_exposed=user.is_seed
                        or bool(draw is not None and draw < dynamic_score.recommendation_score),
                    )
                )

            pending_target_exposures: list[str] = []
            pending_engagements: list[tuple[str, str]] = []
            for batch_input in batch_inputs:
                user_id = batch_input.user_id
                step_row = step_rows[time_step]
                _increment_counter(step_row, "assigned_users")
                if batch_input.is_seed:
                    _increment_counter(step_row, "seed_users")
                exposure_outcome = "target_exposed" if batch_input.target_exposed else "background_content"
                exposure_row = {
                    "schedule_position": schedule_position,
                    "user_id": user_id,
                    "video_id": prepared.target_video.video_id,
                    "time_step": time_step,
                    "assigned_step": time_step,
                    "is_seed": _csv_bool(batch_input.is_seed),
                    "base_network_score": batch_input.dynamic_score.base_network_score,
                    "dynamic_network_score": batch_input.dynamic_score.dynamic_network_score,
                    "engaged_neighbor_count": batch_input.dynamic_score.engaged_neighbor_count,
                    "historical_tag_affinity": batch_input.dynamic_score.historical_tag_affinity,
                    "recommendation_score": batch_input.dynamic_score.recommendation_score,
                    "random_draw": "" if batch_input.draw is None else round(batch_input.draw, 12),
                    "exposure_outcome": exposure_outcome,
                }
                exposures.append(exposure_row)

                if not batch_input.target_exposed:
                    _increment_counter(step_row, "background_impressions")
                    background_events.append(
                        {
                            "schedule_position": schedule_position,
                            "user_id": user_id,
                            "video_id": prepared.target_video.video_id,
                            "time_step": time_step,
                            "recommendation_score": batch_input.dynamic_score.recommendation_score,
                            "random_draw": round(batch_input.draw, 12) if batch_input.draw is not None else "",
                        }
                    )
                    schedule_position += 1
                    continue

                _increment_counter(step_row, "target_exposures")
                pending_target_exposures.append(user_id)
                decision_adapter_calls += 1
                attempt = _attempt_runtime_decision(
                    adapter=self.decision_adapter,
                    post=post,
                    profile=_runtime_user_profile(batch_input.user),
                    peer_context=batch_input.peer_context,
                    platform_context=PlatformContext(
                        time_label=f"batch-{time_step}",
                        hot_topics=list(prepared.target_video.hashtags),
                        platform_mood="fixed final research batch",
                    ),
                    time_step=time_step,
                    schedule_position=schedule_position,
                    video_id=prepared.target_video.video_id,
                    provider_metadata=provider_metadata,
                )
                if attempt.provider_failure is not None:
                    _increment_counter(step_row, "provider_failed")
                    provider_failures.append(attempt.provider_failure)
                    schedule_position += 1
                    continue

                decision = attempt.decision
                assert decision is not None
                _increment_counter(step_row, "decisions")
                if decision.engage:
                    _increment_counter(step_row, "engagements")
                    pending_engagements.append((user_id, decision.action))
                else:
                    _increment_counter(step_row, "ignored")
                decision_row, action_row = _runtime_decision_rows(
                    decision,
                    schedule_position=schedule_position,
                    user_id=user_id,
                    video_id=prepared.target_video.video_id,
                    time_step=time_step,
                )
                decisions.append(decision_row)
                actions.append(action_row)
                schedule_position += 1

            for user_id in pending_target_exposures:
                platform.record_target_exposure(user_id)
            for user_id, action in pending_engagements:
                platform.record_engagement(user_id, action)

        summary = {
            "runtime_version": FINAL_RESEARCH_RUNTIME_VERSION,
            "horizon": self.config.horizon,
            "schedule_method": FINAL_RESEARCH_SCHEDULE_METHOD,
            "seed_step": FINAL_RESEARCH_SEED_STEP,
            "non_seed_steps": [1, self.config.horizon - 1],
            "user_opportunity_limit": FINAL_RESEARCH_USER_OPPORTUNITY_LIMIT,
            "recommendation_score_usage": FINAL_RESEARCH_SCORE_USAGE,
            "dynamic_network_formula": FINAL_RESEARCH_DYNAMIC_NETWORK_FORMULA,
            "decision_adapter_calls": decision_adapter_calls,
            "provider_metadata": provider_metadata,
            "counts": {
                "sample_users": len(prepared.sample_user_ids),
                "seed_users": len(prepared.seed_user_ids),
                "target_exposures": sum(row["exposure_outcome"] == "target_exposed" for row in exposures),
                "background_impressions": len(background_events),
                "decisions": len(decisions),
                "engagements": sum(row["action"] != "ignore" for row in actions),
                "ignored": sum(row["action"] == "ignore" for row in actions),
                "provider_failed": len(provider_failures),
            },
        }
        return _RuntimeArtifacts(
            steps=[step_rows[time_step] for time_step in range(self.config.horizon)],
            exposures=exposures,
            decisions=decisions,
            actions=actions,
            background_events=background_events,
            provider_failures=provider_failures,
            summary=summary,
            decision_adapter_calls=decision_adapter_calls,
        )


def _attempt_runtime_decision(
    *,
    adapter: LLMDecisionAdapter,
    post: PostContent,
    profile: UserProfile,
    peer_context: PeerContext,
    platform_context: PlatformContext,
    time_step: int,
    schedule_position: int,
    video_id: str,
    provider_metadata: Mapping[str, object],
) -> _RuntimeDecisionAttempt:
    try:
        decision = adapter.decide(
            post,
            profile,
            peer_context,
            platform_context,
            time_step,
        )
    except ProviderDecisionError as exc:
        return _RuntimeDecisionAttempt(
            decision=None,
            provider_failure={
                "schedule_position": schedule_position,
                "user_id": profile.user_id,
                "video_id": video_id,
                "time_step": time_step,
                "failure_type": exc.failure_type,
                "provider_metadata": _json_cell(provider_metadata),
            },
        )
    return _RuntimeDecisionAttempt(decision=decision, provider_failure=None)


def _runtime_decision_rows(
    decision: EngageDecision,
    *,
    schedule_position: int,
    user_id: str,
    video_id: str,
    time_step: int,
) -> tuple[dict[str, object], dict[str, object]]:
    decision_row = {
        "schedule_position": schedule_position,
        "user_id": user_id,
        "video_id": video_id,
        "time_step": time_step,
        "engage": _csv_bool(decision.engage),
        "probability": decision.probability,
        "reason": decision.reason,
        "confidence": decision.confidence,
        "action": decision.action,
        "decision_source": decision.decision_source,
        "provider_metadata": _json_cell(decision.provider_metadata),
    }
    action_row = {
        "schedule_position": schedule_position,
        "user_id": user_id,
        "video_id": video_id,
        "time_step": time_step,
        "action": decision.action,
    }
    return decision_row, action_row


def _fixed_batch_assignments(
    prepared: _PreparedInputs,
    config: FinalResearchConfig,
) -> dict[int, list[str]]:
    assignments: dict[int, list[str]] = {time_step: [] for time_step in range(config.horizon)}
    seed_set = set(prepared.seed_user_ids)
    assignments[0] = sorted(prepared.seed_user_ids)
    remaining = [user_id for user_id in prepared.sample_user_ids if user_id not in seed_set]
    rng = random.Random(_stable_seed(config.random_seed, "final-research-fixed-batches"))
    rng.shuffle(remaining)
    for index, user_id in enumerate(remaining):
        time_step = 1 + index % (config.horizon - 1)
        assignments[time_step].append(user_id)
    return assignments


def _runtime_user_profile(user: ResearchUser) -> UserProfile:
    latent = user.latent_attributes
    return UserProfile.model_validate(
        {
            "user_id": user.user_id,
            "interest_tags": [],
            "activity_score": user.activity_score,
            "nickname": user.nickname,
            "bio": user.bio,
            "signature": user.signature,
            "follower_count": user.follower_count,
            "following_count": user.following_count,
            "video_count": user.video_count,
            "global_influence_score": user.global_influence_score,
            "local_influence_score": user.local_influence_score,
            "latent_attributes": {
                "spec_id": latent["latent_attribute_spec_id"],
                "method": latent["latent_attribute_method"],
                "seed": latent["latent_attribute_seed"],
                "latent_class": latent["latent_class"],
                "environmental_consciousness_coef": latent["latent_environmental_consciousness_coef"],
                "value_weights": {
                    dimension: latent[f"latent_{dimension}_value_weight"] for dimension in LATENT_VALUE_DIMENSIONS
                },
                "profile_labels": {
                    field_name: latent[f"latent_{field_name}"] for field_name in LATENT_PROFILE_LABEL_FIELDS
                },
            },
        }
    )


def _adapter_safe_metadata(
    adapter: LLMDecisionAdapter,
    provider_config: ProviderLLMConfig,
) -> dict[str, object]:
    current: object = adapter
    seen: set[int] = set()
    while id(current) not in seen:
        seen.add(id(current))
        metadata = getattr(current, "safe_metadata", None)
        if isinstance(metadata, Mapping):
            sanitized = safe_data(dict(metadata))
            return sanitized if isinstance(sanitized, dict) else provider_config.safe_metadata()
        wrapped = getattr(current, "wrapped", None)
        if wrapped is None:
            break
        current = wrapped
    return provider_config.safe_metadata()


def _adapter_live_api_triggered(adapter: LLMDecisionAdapter) -> bool:
    current: object = adapter
    seen: set[int] = set()
    while id(current) not in seen:
        seen.add(id(current))
        if bool(getattr(current, "live_api_triggered", False)):
            return True
        wrapped = getattr(current, "wrapped", None)
        if wrapped is None:
            return False
        current = wrapped
    return False


def _json_cell(payload: object) -> str:
    sanitized = safe_data(payload)
    return json.dumps(sanitized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _increment_counter(row: dict[str, object], field_name: str) -> None:
    value = row[field_name]
    if not isinstance(value, int):
        raise TypeError(f"runtime counter {field_name} must be an int")
    row[field_name] = value + 1


def _build_research_users(
    profile_rows: Sequence[Mapping[str, str]],
    *,
    history_counts: Mapping[str, Counter[str]],
    history_likes: Mapping[str, int],
    all_history_degree: Mapping[str, int],
    thresholds: Mapping[str, float],
) -> dict[str, ResearchUser]:
    users: dict[str, ResearchUser] = {}
    for row in profile_rows:
        user_id = _cell(row, "user_id")
        counts = history_counts.get(user_id, Counter())
        signals = {
            "video_count": _int_cell(row, "video_count"),
            "comment_count": counts["comment"],
            "reply_count": counts["reply"],
            "edge_degree": all_history_degree.get(user_id, 0),
            "comment_like_sum": history_likes.get(user_id, 0),
        }
        video_score = _log_p95_score(signals["video_count"], thresholds["video_count"])
        comment_score = _log_p95_score(signals["comment_count"], thresholds["comment_count"])
        reply_score = _log_p95_score(signals["reply_count"], thresholds["reply_count"])
        network_score = _log_p95_score(signals["edge_degree"], thresholds["edge_degree"])
        recognition_score = _log_p95_score(signals["comment_like_sum"], thresholds["comment_like_sum"])
        users[user_id] = ResearchUser(
            user_id=user_id,
            nickname=_cell(row, "nickname"),
            bio=_cell(row, "bio"),
            signature=_cell(row, "signature"),
            interest_tags=_parse_list(_cell(row, "interest_tags")),
            follower_count=_int_cell(row, "follower_count"),
            following_count=_int_cell(row, "following_count"),
            video_count=signals["video_count"],
            activity_score=round(0.25 * video_score + 0.45 * comment_score + 0.30 * reply_score, 6),
            activity_video_score=round(video_score, 6),
            activity_comment_score=round(comment_score, 6),
            activity_reply_score=round(reply_score, 6),
            global_influence_score=_float_cell(row, "global_influence_score"),
            local_influence_score=round(0.60 * network_score + 0.40 * recognition_score, 6),
            local_network_score=round(network_score, 6),
            local_recognition_score=round(recognition_score, 6),
            latent_attributes=_latent_attributes(row),
        )
    return users


def _historical_user_signals(
    videos: Mapping[str, _VideoRecord],
    comments: Sequence[_CommentRecord],
) -> tuple[dict[str, Counter[str]], dict[str, int], dict[str, set[str]]]:
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    likes: dict[str, int] = defaultdict(int)
    tags: dict[str, set[str]] = defaultdict(set)
    for comment in comments:
        if not comment.commenter_user_id:
            continue
        counts[comment.commenter_user_id][comment.comment_level] += 1
        likes[comment.commenter_user_id] += max(0, comment.like_count)
        video = videos.get(comment.video_id)
        if video is not None:
            tags[comment.commenter_user_id].update(video.hashtags)
    return dict(counts), dict(likes), dict(tags)


def _weighted_degrees(
    videos: Mapping[str, _VideoRecord],
    comments: Sequence[_CommentRecord],
) -> dict[str, int]:
    degree, _neighbors, _edge_weights = _weighted_graph_details(videos, comments)
    return degree


def _weighted_graph(
    videos: Mapping[str, _VideoRecord],
    comments: Sequence[_CommentRecord],
) -> tuple[dict[str, int], dict[str, set[str]]]:
    degree, neighbors, _edge_weights = _weighted_graph_details(videos, comments)
    return degree, neighbors


def _weighted_graph_details(
    videos: Mapping[str, _VideoRecord],
    comments: Sequence[_CommentRecord],
) -> tuple[dict[str, int], dict[str, set[str]], dict[tuple[str, str], int]]:
    comment_by_id = {comment.comment_id: comment for comment in comments}
    degree: dict[str, int] = defaultdict(int)
    neighbors: dict[str, set[str]] = defaultdict(set)
    edge_weights: dict[tuple[str, str], int] = defaultdict(int)

    def add(source: str, target: str) -> None:
        if not source or not target or source == target:
            return
        degree[source] += 1
        degree[target] += 1
        neighbors[source].add(target)
        neighbors[target].add(source)
        edge_weights[_graph_edge_key(source, target)] += 1

    for comment in comments:
        if comment.comment_level == "comment":
            video = videos.get(comment.video_id)
            add(comment.commenter_user_id, video.creator_user_id if video is not None else "")
        else:
            parent = comment_by_id.get(comment.parent_comment_id)
            add(comment.commenter_user_id, parent.commenter_user_id if parent is not None else "")
        for mentioned_user_id in comment.mentioned_user_ids:
            add(comment.commenter_user_id, mentioned_user_id)
    return dict(degree), dict(neighbors), dict(edge_weights)


def _primary_source_scopes(
    *,
    videos: Mapping[str, _VideoRecord],
    comments: Sequence[_CommentRecord],
    available_user_ids: set[str],
) -> tuple[list[str], dict[str, str], list[str]]:
    rank_by_scope: dict[str, int] = {}
    for video in videos.values():
        rank_by_scope[video.source_challenge_name] = min(
            video.source_challenge_rank,
            rank_by_scope.get(video.source_challenge_name, video.source_challenge_rank),
        )
    scope_order = sorted(rank_by_scope, key=lambda scope: (rank_by_scope[scope], scope))
    scope_position = {scope: position for position, scope in enumerate(scope_order)}
    counts_by_user: dict[str, Counter[str]] = defaultdict(Counter)
    for comment in comments:
        comment_video = videos.get(comment.video_id)
        if comment_video is not None and comment.commenter_user_id in available_user_ids:
            counts_by_user[comment.commenter_user_id][comment_video.source_challenge_name] += 1

    primary_scope_by_user: dict[str, str] = {}
    tied_user_ids: list[str] = []
    for user_id in sorted(available_user_ids):
        scope_counts = counts_by_user.get(user_id)
        if not scope_counts:
            primary_scope_by_user[user_id] = "remaining_users"
            continue
        maximum_count = max(scope_counts.values())
        tied_scopes = [scope for scope, count in scope_counts.items() if count == maximum_count]
        if len(tied_scopes) > 1:
            tied_user_ids.append(user_id)
        primary_scope_by_user[user_id] = min(
            tied_scopes,
            key=lambda scope: (scope_position.get(scope, len(scope_order)), scope),
        )
    return scope_order, primary_scope_by_user, tied_user_ids


def _source_scope_quotas(scope_order: Sequence[str], sample_size: int) -> dict[str, int]:
    remaining = sample_size
    quotas: dict[str, int] = {}
    for scope_name in scope_order:
        quota = min(PRIMARY_SOURCE_SCOPE_QUOTA, remaining)
        quotas[scope_name] = quota
        remaining -= quota
    if remaining > 0:
        quotas["remaining_users"] = remaining
    return quotas


def _graph_edge_key(source: str, target: str) -> tuple[str, str]:
    return (source, target) if source <= target else (target, source)


def _holdout_safe_thresholds(
    profile_rows: Sequence[Mapping[str, str]],
    history_counts: Mapping[str, Counter[str]],
    history_likes: Mapping[str, int],
    all_history_degree: Mapping[str, int],
) -> dict[str, float]:
    fields = ("video_count", "comment_count", "reply_count", "edge_degree", "comment_like_sum")
    values: dict[str, list[int]] = {field: [] for field in fields}
    for row in profile_rows:
        user_id = _cell(row, "user_id")
        counts = history_counts.get(user_id, Counter())
        signals = {
            "video_count": _int_cell(row, "video_count"),
            "comment_count": counts["comment"],
            "reply_count": counts["reply"],
            "edge_degree": all_history_degree.get(user_id, 0),
            "comment_like_sum": history_likes.get(user_id, 0),
        }
        for field in fields:
            values[field].append(signals[field])
    return {field: round(_percentile(field_values, 0.95), 6) for field, field_values in values.items()}


def _sample_users(
    *,
    videos: Mapping[str, _VideoRecord],
    comments: Sequence[_CommentRecord],
    available_user_ids: set[str],
    sample_size: int,
    random_seed: int,
) -> tuple[list[str], dict[str, str]]:
    scope_order = sorted(
        {(video.source_challenge_rank, video.source_challenge_name) for video in videos.values()},
        key=lambda item: (item[0], item[1]),
    )
    pools: dict[str, set[str]] = defaultdict(set)
    for comment in comments:
        video = videos.get(comment.video_id)
        if video is not None and comment.commenter_user_id in available_user_ids:
            pools[video.source_challenge_name].add(comment.commenter_user_id)

    selected: list[str] = []
    selected_set: set[str] = set()
    scope_by_user: dict[str, str] = {}
    for _rank, scope_name in scope_order:
        remaining_slots = sample_size - len(selected)
        if remaining_slots <= 0:
            break
        candidates = sorted(pools.get(scope_name, set()) - selected_set)
        rng = random.Random(_stable_seed(random_seed, scope_name))
        rng.shuffle(candidates)
        for user_id in candidates[: min(100, remaining_slots)]:
            selected.append(user_id)
            selected_set.add(user_id)
            scope_by_user[user_id] = scope_name

    if len(selected) < sample_size:
        remaining = sorted(available_user_ids - selected_set)
        rng = random.Random(_stable_seed(random_seed, "remaining-users"))
        rng.shuffle(remaining)
        for user_id in remaining[: sample_size - len(selected)]:
            selected.append(user_id)
            scope_by_user[user_id] = "remaining_users"
    if len(selected) != sample_size:
        raise ValueError(f"could not select {sample_size} unique users; selected {len(selected)}")
    return selected, scope_by_user


def _select_seeds(sample_user_ids: Sequence[str], users_by_id: Mapping[str, ResearchUser]) -> list[str]:
    global_top = sorted(
        sample_user_ids,
        key=lambda user_id: (-users_by_id[user_id].global_influence_score, user_id),
    )[:10]
    local_top = sorted(
        sample_user_ids,
        key=lambda user_id: (-users_by_id[user_id].local_influence_score, user_id),
    )[:10]
    return sorted(set(global_top) | set(local_top))


def _holdout_diagnostic(
    holdout_participant_ids: Sequence[str],
    top_scores: Sequence[OfflineRecommendationScore],
    scores_by_user: Mapping[str, OfflineRecommendationScore],
) -> dict[str, object]:
    observed = list(holdout_participant_ids[:20])
    recommended = [score.user_id for score in top_scores]
    observed_set = set(observed)
    participant_signals = [
        {
            "user_id": user_id,
            "has_non_target_history": scores_by_user[user_id].has_non_target_history,
            "has_network_connection": scores_by_user[user_id].has_network_connection,
            "has_historical_tag_affinity": scores_by_user[user_id].has_historical_tag_affinity,
        }
        for user_id in observed
    ]
    return {
        "observed_holdout_participant_count": len(observed),
        "observed_holdout_participant_ids": observed,
        "model_recommended_user_count": len(recommended),
        "model_recommended_user_ids": recommended,
        "intersection_count": len(observed_set & set(recommended)),
        "intersection_user_ids": sorted(observed_set & set(recommended)),
        "observed_participant_signal_coverage": {
            "with_non_target_history": sum(bool(row["has_non_target_history"]) for row in participant_signals),
            "with_network_connection": sum(bool(row["has_network_connection"]) for row in participant_signals),
            "with_historical_tag_affinity": sum(
                bool(row["has_historical_tag_affinity"]) for row in participant_signals
            ),
            "rows": participant_signals,
        },
        "diagnostic_only": True,
        "unobserved_pair_semantics": UNOBSERVED_PAIR_SEMANTICS,
        "production_accuracy_claim": False,
    }


def _network_augmented_sample_audit(
    prepared: _PreparedInputs,
    config: FinalResearchConfig,
) -> dict[str, object]:
    base_sample_set = set(prepared.base_sample_user_ids)
    cohort_set = set(prepared.network_cohort_user_ids)
    return {
        "schema_version": NETWORK_AUGMENTED_SAMPLE_AUDIT_VERSION,
        "sample_size": config.sample_size,
        "base_sample": {
            "user_ids": sorted(prepared.base_sample_user_ids),
            "count": len(prepared.base_sample_user_ids),
            "source_scope_counts": prepared.base_source_scope_sample_counts,
        },
        "seed_user_ids": prepared.seed_user_ids,
        "seed_count": len(prepared.seed_user_ids),
        "network_cohort": {
            "user_ids": prepared.network_cohort_user_ids,
            "count": len(prepared.network_cohort_user_ids),
            "already_in_base_user_ids": sorted(cohort_set & base_sample_set),
            "added_user_ids": prepared.network_cohort_added_user_ids,
            "target_source_scope": TARGET_NETWORK_SCOPE,
            "historical_set_only": True,
            "direct_neighbors_only": True,
        },
        "ordinary_replacement": {
            "removed_user_ids": prepared.replaced_ordinary_user_ids,
            "count": len(prepared.replaced_ordinary_user_ids),
            "random_seed": _stable_seed(config.random_seed, "network-cohort-replacement"),
            "eligible_role": "base sample ordinary non-seed outside network cohort",
        },
        "final_sample": {
            "user_ids": sorted(prepared.final_sample_user_ids),
            "count": len(prepared.final_sample_user_ids),
            "unique_user_count": len(set(prepared.final_sample_user_ids)),
            "source_scope_counts": prepared.final_source_scope_sample_counts,
        },
        "seed_selection_stage": "base_sample_before_network_augmentation",
        "source_dataset_modified": False,
    }


def _score_summary(
    scores: Sequence[OfflineRecommendationScore],
    ranked_scores: Sequence[OfflineRecommendationScore],
    model_policy: _ResearchModelPolicy,
) -> dict[str, object]:
    values = [score.recommendation_score for score in scores]
    return {
        "user_count": len(scores),
        "formula": model_policy.static_formula,
        "network_weight": model_policy.network_weight,
        "tag_affinity_weight": model_policy.tag_affinity_weight,
        "minimum_score": min(values, default=0.0),
        "maximum_score": max(values, default=0.0),
        "mean_score": round(sum(values) / len(values), 6) if values else 0.0,
        "users_with_non_target_history": sum(score.has_non_target_history for score in scores),
        "users_with_network_connection": sum(score.has_network_connection for score in scores),
        "users_with_historical_tag_affinity": sum(score.has_historical_tag_affinity for score in scores),
        "top20_user_ids": [score.user_id for score in ranked_scores[:20]],
    }


def _latent_attributes(row: Mapping[str, str]) -> dict[str, str | int | float]:
    result: dict[str, str | int | float] = {
        "latent_attribute_spec_id": _cell(row, "latent_attribute_spec_id"),
        "latent_attribute_method": _cell(row, "latent_attribute_method"),
        "latent_attribute_seed": _int_cell(row, "latent_attribute_seed"),
        "latent_class": _cell(row, "latent_class"),
        "latent_environmental_consciousness_coef": _float_cell(row, "latent_environmental_consciousness_coef"),
    }
    for dimension in LATENT_VALUE_DIMENSIONS:
        result[f"latent_{dimension}_value_weight"] = _float_cell(row, f"latent_{dimension}_value_weight")
    for field_name in LATENT_PROFILE_LABEL_FIELDS:
        result[f"latent_{field_name}"] = _cell(row, f"latent_{field_name}")
    missing = [key for key, value in result.items() if value == ""]
    if missing:
        raise ValueError(f"user {_cell(row, 'user_id')!r} has incomplete latent attributes: {', '.join(missing)}")
    return result


def _percentile(values: Iterable[int], quantile: float) -> float:
    clean = sorted(max(0, int(value)) for value in values)
    if not clean:
        return 0.0
    position = (len(clean) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(clean[lower])
    fraction = position - lower
    return float(clean[lower] * (1 - fraction) + clean[upper] * fraction)


def _log_p95_score(value: int, threshold: float) -> float:
    if value <= 0 or threshold <= 0:
        return 0.0
    return max(0.0, min(1.0, math.log1p(value) / math.log1p(threshold)))


def _stable_seed(random_seed: int, label: str) -> int:
    digest = hashlib.sha256(f"{random_seed}:{label}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_csv(
    path: Path,
    fieldnames: list[str],
    rows: Sequence[Mapping[str, object]],
    *,
    preserve_user_text: bool = False,
) -> None:
    safe_rows = safe_user_data(list(rows)) if preserve_user_text else safe_data(list(rows))
    if not isinstance(safe_rows, list):  # pragma: no cover - serializers preserve list inputs.
        raise TypeError("safe artifact rows must remain a list")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(safe_rows)


def _write_json(path: Path, payload: object, *, preserve_user_text: bool = False) -> None:
    serializer = safe_user_json if preserve_user_text else safe_json
    path.write_text(serializer(payload) + "\n", encoding="utf-8")


def _parse_list(value: str) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            parsed = None
    if isinstance(parsed, (list, tuple, set)):
        return [str(item).strip() for item in parsed if str(item).strip()]
    return [part.strip() for part in value.replace("|", ",").replace(";", ",").split(",") if part.strip()]


def _cell(row: Mapping[str, Any], field_name: str) -> str:
    value = row.get(field_name, "")
    return str(value or "").strip()


def _int_cell(row: Mapping[str, Any], field_name: str) -> int:
    value = _cell(row, field_name)
    if not value:
        return 0
    try:
        return max(0, int(float(value)))
    except ValueError as error:
        raise ValueError(f"invalid integer value for {field_name}: {value!r}") from error


def _float_cell(row: Mapping[str, Any], field_name: str) -> float:
    value = _cell(row, field_name)
    if not value:
        return 0.0
    try:
        return float(value)
    except ValueError as error:
        raise ValueError(f"invalid float value for {field_name}: {value!r}") from error


def _has_parent(parent_comment_id: str) -> bool:
    return parent_comment_id not in {"", "0", "none", "null"}


def _csv_bool(value: bool) -> str:
    return "true" if value else "false"


assert not LEGACY_DEMO_PRESET_FIELDS.intersection(SAMPLE_CSV_FIELDS)
