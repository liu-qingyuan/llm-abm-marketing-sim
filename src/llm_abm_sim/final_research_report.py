from __future__ import annotations

import csv
import json
import os
import tempfile
from base64 import b64encode
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from html import escape
from importlib.resources import files
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .field_lineage_trace import (
    FieldLineageDefinition,
    FieldLineageTraceBundle,
    FieldLineageTraceModule,
    FieldLineageTraceSource,
    PromptInclusionStatus,
    UserFieldTrace,
)
from .prompt_field_summary import JINJIANG_PROMPT_V2_PROFILE_FIELDS
from .research_explanations import (
    ExplanationContext,
    FieldProvenance,
    FieldUsageStage,
    RenderedConceptExplanation,
    ResearchExplanationCatalog,
)
from .safe_serialization import safe_json, safe_user_data, safe_user_json

FINAL_RESEARCH_REPORT_ARTIFACTS = {
    "final_research_report": "report.html",
    "final_research_report_payload": "final_research_report_payload.json",
    "final_research_users_csv": "final_research_users.csv",
    "final_research_users_json": "final_research_users.json",
}
FINAL_RESEARCH_RUNTIME_VERSION = "final-research-runtime-v1"
FINAL_RESEARCH_RANKING_RUNTIME_VERSION = "final-research-ranking-runtime-v2"
FINAL_RESEARCH_SCHEDULE_METHOD = "stable_shuffle_round_robin_batches"
FINAL_RESEARCH_SEED_STEP = 0
FINAL_RESEARCH_USER_OPPORTUNITY_LIMIT = 1
FINAL_RESEARCH_SCORE_USAGE = "single exposure probability, never user ordering"
FINAL_RESEARCH_DYNAMIC_NETWORK_FORMULA = "min(1.0, base_network_score + neighbor_boost * engaged_direct_neighbor_count)"

ResultStatus = Literal[
    "like",
    "comment",
    "share",
    "ignore",
    "background_content",
    "provider_failed",
    "missing_decision",
    "runtime_not_run",
]
ExposureStatus = Literal["target_exposed", "background_content", "missing_exposure", "runtime_not_run"]
ReportAction = Literal["", "like", "comment", "share", "ignore"]
ProviderStatus = Literal["not_called", "succeeded", "provider_failed", "missing_decision", "runtime_not_run"]
RankingResultStatus = Literal[
    "like",
    "comment",
    "share",
    "ignore",
    "provider_failed",
    "below_delivery_capacity",
]
SamplingMethod = Literal[
    "source_scope_stratified_sample_v1",
    "network_augmented_research_sample",
    "seed_first_research_sample_v1",
]
SamplingStatus = Literal[
    "historical_network_augmented_run",
    "validation_run",
    "persisted_seed_first_formal_run",
    "persisted_probability_formal_run",
]
SampleRole = Literal["seed", "network_cohort", "ordinary"]


def _sampling_method(value: object) -> SamplingMethod:
    if value not in {
        "source_scope_stratified_sample_v1",
        "network_augmented_research_sample",
        "seed_first_research_sample_v1",
    }:
        raise ValueError(f"unsupported sampling_method: {value!r}")
    return cast(SamplingMethod, value)


def _sampling_status(value: object) -> SamplingStatus:
    if value not in {
        "historical_network_augmented_run",
        "validation_run",
        "persisted_seed_first_formal_run",
        "persisted_probability_formal_run",
    }:
        raise ValueError(f"unsupported sampling_status: {value!r}")
    return cast(SamplingStatus, value)


def _sample_role(value: object) -> SampleRole:
    if value not in {"seed", "network_cohort", "ordinary"}:
        raise ValueError(f"unsupported sample_role: {value!r}")
    return cast(SampleRole, value)


def _render_section_explanation(explanation: RenderedConceptExplanation, test_id: str) -> str:
    entries = (
        ("是什么", explanation["what"]),
        ("为什么需要", explanation["why"]),
        ("怎么形成或计算", explanation["formation"]),
        ("本次结果怎么看", explanation["result"]),
    )
    articles = "".join(f"<article><h3>{escape(title)}</h3><p>{escape(copy)}</p></article>" for title, copy in entries)
    return f'<div class="section-explanation" data-testid="{escape(test_id, quote=True)}">{articles}</div>'


def _embedded_report_image(file_name: str) -> str:
    image_bytes = files("llm_abm_sim").joinpath("report_assets").joinpath(file_name).read_bytes()
    return f"data:image/webp;base64,{b64encode(image_bytes).decode('ascii')}"


class FinalResearchTargetVideo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    video_id: str
    source_challenge_name: str
    source_challenge_rank: int
    caption: str
    hashtags: list[str]
    creator_user_id: str
    video_url: str


class FinalResearchReportRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_size: int
    horizon: int
    random_seed: int
    runtime_enabled: bool
    sampling_method: SamplingMethod = "network_augmented_research_sample"
    sampling_status: SamplingStatus = "historical_network_augmented_run"


class FinalResearchScoreSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_count: int
    formula: str
    network_weight: float
    tag_affinity_weight: float
    minimum_score: float
    maximum_score: float
    mean_score: float
    users_with_non_target_history: int
    users_with_network_connection: int
    users_with_historical_tag_affinity: int
    top20_user_ids: list[str]


class FinalResearchRecommendationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    formula: str
    network_weight: float
    tag_affinity_weight: float
    neighbor_boost: float
    score_summary: FinalResearchScoreSummary


class ObservedLatentBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_fields: list[str]
    latent_fields: list[str]
    statement: str


class FinalResearchSampleSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_scope_counts: dict[str, int]
    seed_user_ids: list[str]
    seed_count: int
    historical_video_count: int
    historical_interaction_rows: int
    sample_role_counts: dict[SampleRole, int] = Field(default_factory=dict)


class HoldoutSignalRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    has_non_target_history: bool
    has_network_connection: bool
    has_historical_tag_affinity: bool


class HoldoutSignalCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    with_non_target_history: int
    with_network_connection: int
    with_historical_tag_affinity: int
    rows: list[HoldoutSignalRow]


class HoldoutDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_holdout_participant_count: int
    observed_holdout_participant_ids: list[str]
    model_recommended_user_count: int
    model_recommended_user_ids: list[str]
    intersection_count: int
    intersection_user_ids: list[str]
    observed_participant_signal_coverage: HoldoutSignalCoverage
    diagnostic_only: bool
    unobserved_pair_semantics: str
    production_accuracy_claim: bool


class FinalResearchDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    holdout: HoldoutDiagnostic
    seed_method: str
    proxy_method: str
    proxy_semantics: str


class FinalResearchTrendRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time_step: int
    assigned_users: int
    seed_users: int
    target_exposures: int
    background_impressions: int
    decisions: int
    engagements: int
    ignored: int
    provider_failed: int


class AggregateRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    value: int | float


class FinalResearchAggregates(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_distribution: list[AggregateRow]
    scope_distribution: list[AggregateRow]
    provider_failures: list[AggregateRow]
    dynamic_neighbor_signal: list[AggregateRow]


class FinalResearchDownloads(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report: str
    payload: str
    csv: str
    users_json: str
    manifest: str


class UserReportRow(BaseModel):
    """Explicit user-level allowlist for Final Research artifacts."""

    model_config = ConfigDict(extra="forbid")

    user_id: str
    nickname: str = ""
    bio: str = ""
    signature: str = ""
    interest_tags: list[str] = Field(default_factory=list)
    historical_tags: list[str] = Field(default_factory=list)
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
    latent_attributes: dict[str, str | int | float] = Field(default_factory=dict)
    sample_source_scope: str = ""
    is_seed: bool = False
    sample_role: SampleRole = "ordinary"
    assigned_step: int | None = None
    base_network_score: float | None = None
    dynamic_network_score: float | None = None
    engaged_neighbor_count: int | None = None
    historical_tag_affinity: float | None = None
    recommendation_score: float | None = None
    random_draw: float | None = None
    exposure_status: ExposureStatus
    result_status: ResultStatus
    action: ReportAction = ""
    engage: bool | None = None
    reason: str = ""
    confidence: float | None = None
    decision_source: str = ""
    provider_status: ProviderStatus
    provider_failure_type: str = ""
    report_path: str = FINAL_RESEARCH_REPORT_ARTIFACTS["final_research_report"]
    csv_path: str = FINAL_RESEARCH_REPORT_ARTIFACTS["final_research_users_csv"]
    json_path: str = FINAL_RESEARCH_REPORT_ARTIFACTS["final_research_users_json"]
    manifest_path: str = "artifact_manifest.json"

    def csv_row(self) -> dict[str, object]:
        row = self.model_dump(mode="json")
        row["interest_tags"] = json.dumps(row["interest_tags"], ensure_ascii=False, separators=(",", ":"))
        row["historical_tags"] = json.dumps(row["historical_tags"], ensure_ascii=False, separators=(",", ":"))
        row["latent_attributes"] = json.dumps(
            row["latent_attributes"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return row


class _FinalResearchReportPayloadBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    core_objects: tuple[Literal["TargetVideo"], Literal["ResearchUser"], Literal["PlatformRecommendationModel"]]
    target_video: FinalResearchTargetVideo
    run: FinalResearchReportRun
    recommendation_model: FinalResearchRecommendationModel
    observed_latent_boundary: ObservedLatentBoundary
    sample_summary: FinalResearchSampleSummary
    diagnostics: FinalResearchDiagnostics
    trends: list[FinalResearchTrendRow]
    aggregates: FinalResearchAggregates
    downloads: FinalResearchDownloads
    limitations: list[str]
    users: list[UserReportRow]


class FinalResearchReportPayloadV1(_FinalResearchReportPayloadBase):
    """Independent v1 payload accepted by the report rebuild boundary."""

    schema_version: Literal["final-research-report-payload-v1"] = "final-research-report-payload-v1"


class FinalResearchFunnelStage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    count: int
    description: str


class FinalResearchMethodStage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    title: str
    summary: str


class FinalResearchVideoUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime_target_video_count: int
    historical_video_count: int
    target_video_role: str
    background_video_role: str


class FinalResearchSamplingExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_scope_counts: dict[str, int]
    quota_method: str
    deduplication_and_refill: str
    holdout_safe_projection: str
    seed_union_method: str
    seed_forced_exposure: str


class FinalResearchRecommendationExample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    is_seed: bool
    recommendation_score: float | None
    random_draw: float | None
    outcome: str
    explanation: str


class FinalResearchRecommendationExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    static_formula: str
    dynamic_formula: str
    network_weight: float
    tag_affinity_weight: float
    neighbor_boost: float
    seed_example: FinalResearchRecommendationExample | None
    non_seed_example: FinalResearchRecommendationExample | None


class FinalResearchBatchExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_count: int
    seed_batch: int
    non_seed_batches: list[int]
    opportunity_limit: int
    assignment_method: str


class FinalResearchDecisionContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fields: list[str]
    action_values: list[str]
    single_most_likely_action: bool
    persisted_context_label: str
    prompt_recoverability: str


class FinalResearchOutcomeExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str
    count: int
    explanation: str


class FinalResearchDynamicNeighborSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    users_with_positive_engaged_neighbor_count: int
    maximum_engaged_neighbor_count: int
    configured_neighbor_boost: float
    maximum_actual_boost: float
    activated: bool
    explanation: str


class FinalResearchUserTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    context_label: str
    persisted_evidence: dict[str, str | int | float | bool | None]
    unrecoverable_peer_context_fields: list[str]
    prompt_recoverability: str


class FinalResearchReportPayload(_FinalResearchReportPayloadBase):
    """Explainable v2 payload shared by fresh runs and report rebuilding."""

    schema_version: Literal["final-research-report-payload-v2"] = "final-research-report-payload-v2"
    run_funnel: list[FinalResearchFunnelStage]
    methodology_flow: list[FinalResearchMethodStage]
    video_usage: FinalResearchVideoUsage
    sampling_explanation: FinalResearchSamplingExplanation
    comment_network_explanation: str
    recommendation_explanation: FinalResearchRecommendationExplanation
    batch_explanation: FinalResearchBatchExplanation
    decision_contract: FinalResearchDecisionContract
    outcome_explanations: list[FinalResearchOutcomeExplanation]
    dynamic_neighbor_summary: FinalResearchDynamicNeighborSummary
    user_traces: list[FinalResearchUserTrace]


class RankingReportRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_size: int
    horizon: int
    random_seed: int
    delivery_capacity: int
    maximum_target_exposures: int
    ranking_formula: str
    engaged_neighbor_formula: str
    sampling_method: SamplingMethod = "network_augmented_research_sample"
    sampling_status: SamplingStatus = "historical_network_augmented_run"


class RankingSampleComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_sample_count: int
    final_sample_count: int
    seed_count: int
    network_cohort_count: int
    network_cohort_added_count: int
    replacement_count: int
    base_source_scope_counts: dict[str, int]
    final_source_scope_counts: dict[str, int]
    ordinary_count: int = 0


class FieldLineageEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_name: str
    provenance: FieldProvenance
    usage_stages: list[FieldUsageStage]

    @model_validator(mode="after")
    def _validate_usage_stages(self) -> FieldLineageEntry:
        if not self.usage_stages:
            raise ValueError("field lineage requires at least one usage stage")
        if len(self.usage_stages) != len(set(self.usage_stages)):
            raise ValueError("field lineage usage stages must be unique")
        return self


class RankingCandidateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ranking_position: int
    user_id: str
    is_seed: bool
    selected: bool
    base_network_relevance: float
    engaged_neighbor_count: int
    engaged_neighbor_signal: float
    historical_tag_affinity: float
    recommendation_score: float


class RankingRoundSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time_step: int
    eligible_count: int
    delivery_capacity: int
    selected_count: int
    selected_user_ids: list[str]
    target_exposures: int
    decisions: int
    engagements: int
    ignored: int
    provider_failed: int
    below_delivery_capacity: int
    candidates_with_positive_engaged_neighbor_signal: int
    selected_with_positive_engaged_neighbor_signal: int
    maximum_engaged_neighbor_signal: float
    candidates: list[RankingCandidateEvidence]


class RankingPromptContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed_profile_fields: list[str]
    neutralized_fields: list[str]
    excluded_fields: list[str]
    statement: str


class RankingDiagnosticSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    network_signals_in_formula: bool
    main_weights: dict[str, float]
    top_selection_changed: bool
    batches_with_top_selection_change: int
    diagnostic_decision_adapter_calls: int


class RankingReportDownloadsV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report: str
    payload: str
    csv: str
    users_json: str
    manifest: str
    ranking_diagnostics: str
    ranking_ablation_csv: str
    ranking_sensitivity_csv: str


class RankingReportDownloads(RankingReportDownloadsV3):
    field_lineage_catalog: str
    user_field_trace: str
    field_source_records: str


class RankingUserReportRow(BaseModel):
    """Explicit user-level allowlist for Target Delivery Ranking reports."""

    model_config = ConfigDict(extra="forbid")

    user_id: str
    nickname: str = ""
    bio: str = ""
    signature: str = ""
    interest_tags: list[str] = Field(default_factory=list)
    historical_tags: list[str] = Field(default_factory=list)
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
    latent_attribute_spec_id: str
    latent_attribute_method: str
    latent_attribute_seed: int
    latent_class: str
    latent_environmental_consciousness_coef: float
    latent_epistemic_value_weight: float
    latent_environmental_value_weight: float
    latent_functional_value_weight: float
    latent_health_value_weight: float
    latent_emotional_value_weight: float
    latent_social_value_weight: float
    latent_hotel_class: str
    latent_travel_purpose: str
    latent_gender: str
    latent_age: str
    latent_education: str
    latent_monthly_income: str
    sample_source_scope: str
    in_base_sample: bool
    is_seed: bool
    is_network_cohort: bool
    sample_role: SampleRole
    historical_comment_network_weighted_degree: int
    latest_ranking_time_step: int
    latest_ranking_position: int
    selected_for_exposure: bool
    base_network_relevance: float
    engaged_neighbor_count: int
    engaged_neighbor_signal: float
    historical_tag_affinity: float
    recommendation_score: float
    exposure_time_step: int | None
    result_status: RankingResultStatus
    provider_status: Literal["not_called", "succeeded", "provider_failed"]
    action: ReportAction = ""
    engage: bool | None = None
    probability: float | None = None
    reason: str = ""
    confidence: float | None = None
    decision_source: str = ""
    provider_failure_type: str = ""
    report_path: str = FINAL_RESEARCH_REPORT_ARTIFACTS["final_research_report"]
    payload_path: str = FINAL_RESEARCH_REPORT_ARTIFACTS["final_research_report_payload"]
    json_path: str = FINAL_RESEARCH_REPORT_ARTIFACTS["final_research_users_json"]
    manifest_path: str = "artifact_manifest.json"

    def csv_row(self) -> dict[str, object]:
        row = self.model_dump(mode="json")
        row["interest_tags"] = json.dumps(row["interest_tags"], ensure_ascii=False, separators=(",", ":"))
        row["historical_tags"] = json.dumps(row["historical_tags"], ensure_ascii=False, separators=(",", ":"))
        return row


class _FinalResearchRankingReportPayloadBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    title: str
    core_objects: tuple[Literal["TargetVideo"], Literal["ResearchUser"], Literal["PlatformRecommendationModel"]]
    target_video: FinalResearchTargetVideo
    run: RankingReportRun
    run_funnel: list[FinalResearchFunnelStage]
    sample_comparison: RankingSampleComparison
    field_lineage: list[FieldLineageEntry]
    prompt_contract: RankingPromptContract
    ranking_rounds: list[RankingRoundSummary]
    ranking_diagnostics: dict[str, object]
    ranking_diagnostics_summary: RankingDiagnosticSummary
    downloads: RankingReportDownloadsV3
    limitations: list[str]
    users: list[RankingUserReportRow]

    @model_validator(mode="after")
    def _validate_field_lineage(self) -> _FinalResearchRankingReportPayloadBase:
        declared = [entry.field_name for entry in self.field_lineage]
        if len(declared) != len(set(declared)):
            raise ValueError("field lineage must declare each field exactly once")
        expected = _ranking_lineage_field_names()
        missing = expected - set(declared)
        legacy_compatibility_fields = {
            "run.sampling_method",
            "run.sampling_status",
            "sample_comparison.ordinary_count",
        }
        if (
            self.run.sampling_method == "network_augmented_research_sample"
            and missing
            and missing <= legacy_compatibility_fields
        ):
            compatibility_entries = {
                entry.field_name: entry for entry in _ranking_field_lineage() if entry.field_name in missing
            }
            self.field_lineage.extend(compatibility_entries[field_name] for field_name in sorted(missing))
            declared = [entry.field_name for entry in self.field_lineage]
        if set(declared) != expected:
            missing_fields = sorted(expected - set(declared))
            extra = sorted(set(declared) - expected)
            raise ValueError(
                f"field lineage does not match ranking user fields; missing={missing_fields}, extra={extra}"
            )
        return self


class FinalResearchRankingReportPayloadV3(_FinalResearchRankingReportPayloadBase):
    schema_version: Literal["final-research-ranking-report-payload-v3"] = "final-research-ranking-report-payload-v3"


class FinalResearchRankingReportPayload(_FinalResearchRankingReportPayloadBase):
    schema_version: Literal["final-research-ranking-report-payload-v4"] = (
        "final-research-ranking-report-payload-v4"
    )
    sample_role_counts: dict[SampleRole, int]
    field_lineage_catalog: list[FieldLineageDefinition]
    user_field_trace_index: dict[str, list[UserFieldTrace]]
    downloads: RankingReportDownloads

    @model_validator(mode="after")
    def _validate_field_trace(self) -> FinalResearchRankingReportPayload:
        catalog_names = [definition.field_name for definition in self.field_lineage_catalog]
        if len(catalog_names) != len(set(catalog_names)):
            raise ValueError("field lineage catalog must declare each field exactly once")
        user_ids = [user.user_id for user in self.users]
        if set(self.user_field_trace_index) != set(user_ids):
            raise ValueError("user field trace index must cover every report user exactly once")
        for user_id, traces in self.user_field_trace_index.items():
            trace_names = [trace.field_name for trace in traces]
            if len(trace_names) != len(set(trace_names)):
                raise ValueError(f"user field trace contains duplicate fields for {user_id}")
            if any(trace.user_id != user_id for trace in traces):
                raise ValueError(f"user field trace key does not match trace user_id for {user_id}")
            if not set(trace_names) <= set(catalog_names):
                raise ValueError(f"user field trace references an unknown catalog field for {user_id}")
        return self


@dataclass(frozen=True)
class FinalResearchReportSource:
    target_video: Mapping[str, object]
    users: Sequence[Mapping[str, object]]
    historical_tags_by_user: Mapping[str, Sequence[str]]
    interest_tag_evidence_by_user: Mapping[str, Sequence[Mapping[str, object]]]
    historical_tag_evidence_by_user: Mapping[str, Sequence[Mapping[str, object]]]
    prompt_field_inclusion_by_user: Mapping[str, Mapping[str, PromptInclusionStatus]]
    config: Mapping[str, object]
    offline_score_summary: Mapping[str, object]
    holdout_diagnostic: Mapping[str, object]
    holdout_safe_audit: Mapping[str, object]
    artifact_manifest: Mapping[str, object]
    runtime_steps: Sequence[Mapping[str, object]] = ()
    runtime_exposures: Sequence[Mapping[str, object]] = ()
    runtime_decisions: Sequence[Mapping[str, object]] = ()
    runtime_provider_failures: Sequence[Mapping[str, object]] = ()
    runtime_summary: Mapping[str, object] | None = None
    runtime_enabled: bool = False
    offline_scores: Sequence[Mapping[str, object]] = ()
    network_sample_audit: Mapping[str, object] | None = None
    ranking_steps: Sequence[Mapping[str, object]] = ()
    ranking_candidates: Sequence[Mapping[str, object]] = ()
    ranking_outcomes: Sequence[Mapping[str, object]] = ()
    ranking_diagnostics: Mapping[str, object] | None = None
    ranking_diagnostics_summary: Mapping[str, object] | None = None
    ranking_runtime_summary: Mapping[str, object] | None = None


class FinalResearchReportWriter:
    """Build and write all Final Research human and machine-readable artifacts."""

    def __init__(self, source: FinalResearchReportSource) -> None:
        self.source = source

    def write(self, output_dir: str | Path) -> Path:
        output_path = Path(output_dir)
        trace_bundle = self._build_field_trace_bundle() if self.source.ranking_runtime_summary is not None else None
        payload = self._build_payload(trace_bundle)
        user_records = [row.model_dump(mode="json") for row in payload.users]
        user_document = {
            "schema_version": (
                "final-research-ranking-users-v4"
                if isinstance(payload, FinalResearchRankingReportPayload)
                else "final-research-ranking-users-v3"
                if isinstance(payload, FinalResearchRankingReportPayloadV3)
                else "final-research-users-v1"
            ),
            "links": payload.downloads.model_dump(mode="json"),
            "users": user_records,
        }

        if trace_bundle is not None:
            artifacts = _required_mapping(self.source.artifact_manifest, "artifacts", "artifact manifest")
            (output_path / str(artifacts["field_lineage_catalog"])).write_text(
                safe_json(trace_bundle.catalog_document()) + "\n",
                encoding="utf-8",
            )
            (output_path / str(artifacts["user_field_trace"])).write_text(
                safe_user_json(trace_bundle.trace_document()) + "\n",
                encoding="utf-8",
            )
            (output_path / str(artifacts["field_source_records"])).write_text(
                safe_user_json(trace_bundle.source_document()) + "\n",
                encoding="utf-8",
            )
        self._write_csv(
            output_path / FINAL_RESEARCH_REPORT_ARTIFACTS["final_research_users_csv"],
            payload.users,
        )
        (output_path / FINAL_RESEARCH_REPORT_ARTIFACTS["final_research_users_json"]).write_text(
            safe_user_json(user_document) + "\n",
            encoding="utf-8",
        )
        report_path = _publish_report_files(output_path, payload)
        (output_path / "artifact_manifest.json").write_text(
            safe_json(dict(self.source.artifact_manifest)) + "\n",
            encoding="utf-8",
        )
        return report_path

    def _build_payload(
        self,
        trace_bundle: FieldLineageTraceBundle | None = None,
    ) -> FinalResearchReportPayload | FinalResearchRankingReportPayload:
        if self.source.ranking_runtime_summary is not None:
            if trace_bundle is None:  # pragma: no cover
                raise ValueError("ranking report requires field trace evidence")
            return _build_ranking_report_payload(self.source, trace_bundle)
        rows = self._build_user_rows()
        configured_title = str(self.source.config.get("report_title") or "")
        title = (
            "锦江酒店 Final Research Report"
            if not configured_title or configured_title == "LLM-ABM Simulation Report"
            else configured_title
        )
        score_summary = dict(self.source.offline_score_summary)
        audit = dict(self.source.holdout_safe_audit)
        diagnostic = dict(self.source.holdout_diagnostic)
        sampling_method = _sampling_method(
            self.source.artifact_manifest.get(
                "sampling_method",
                audit.get("sampling_method", "network_augmented_research_sample"),
            )
        )
        sampling_status = _sampling_status(
            self.source.artifact_manifest.get(
                "sampling_status",
                audit.get("sampling_status", "historical_network_augmented_run"),
            )
        )
        sample_role_counts = self.source.artifact_manifest.get("sample_role_counts", {})
        target_video = safe_user_data(dict(self.source.target_video))
        if not isinstance(target_video, dict):  # pragma: no cover
            raise TypeError("safe target video must remain an object")
        base_payload = FinalResearchReportPayloadV1(
            title=title,
            core_objects=("TargetVideo", "ResearchUser", "PlatformRecommendationModel"),
            target_video=FinalResearchTargetVideo.model_validate(target_video),
            run=FinalResearchReportRun(
                sample_size=len(rows),
                horizon=_as_int(self.source.config.get("horizon")),
                random_seed=_as_int(self.source.config.get("random_seed")),
                runtime_enabled=self.source.runtime_enabled,
                sampling_method=sampling_method,
                sampling_status=sampling_status,
            ),
            recommendation_model=FinalResearchRecommendationModel(
                formula=str(score_summary.get("formula", "")),
                network_weight=_as_float(self.source.config.get("network_weight")),
                tag_affinity_weight=_as_float(self.source.config.get("tag_affinity_weight")),
                neighbor_boost=_as_float(self.source.config.get("neighbor_boost")),
                score_summary=FinalResearchScoreSummary.model_validate(score_summary),
            ),
            observed_latent_boundary=ObservedLatentBoundary(
                observed_fields=[
                    "profile text",
                    "activity proxies",
                    "influence proxies",
                    "cleaned interest tags",
                    "historical tags",
                    "source scope",
                ],
                latent_fields=["virtual experiment labels", "value weights", "environmental coefficient"],
                statement=(
                    "Observed fields are source facts or reproducible proxies. Latent fields are synthetic experiment "
                    "labels and are not verified identity, demographics, psychology, or third-party classifications."
                ),
            ),
            sample_summary=FinalResearchSampleSummary.model_validate(
                {
                    "source_scope_counts": audit.get("source_scope_sample_counts", {}),
                    "seed_user_ids": audit.get("global_top10_local_top10_seed_union", []),
                    "seed_count": audit.get("seed_count", 0),
                    "historical_video_count": audit.get("historical_video_count", 0),
                    "historical_interaction_rows": audit.get("historical_interaction_rows", 0),
                    "sample_role_counts": sample_role_counts,
                }
            ),
            diagnostics=FinalResearchDiagnostics(
                holdout=HoldoutDiagnostic.model_validate(diagnostic),
                seed_method=(
                    "global top10 and holdout-safe local top10 union from the full eligible pool"
                    if sampling_method == "seed_first_research_sample_v1"
                    else "global top10 and holdout-safe local top10 union within the sample"
                ),
                proxy_method=str(audit.get("profile_index_method", "")),
                proxy_semantics=str(audit.get("proxy_semantics", "")),
            ),
            trends=[FinalResearchTrendRow.model_validate(row) for row in self.source.runtime_steps],
            aggregates=self._aggregates(rows),
            downloads=FinalResearchDownloads(
                report=FINAL_RESEARCH_REPORT_ARTIFACTS["final_research_report"],
                payload=FINAL_RESEARCH_REPORT_ARTIFACTS["final_research_report_payload"],
                csv=FINAL_RESEARCH_REPORT_ARTIFACTS["final_research_users_csv"],
                users_json=FINAL_RESEARCH_REPORT_ARTIFACTS["final_research_users_json"],
                manifest="artifact_manifest.json",
            ),
            limitations=[
                "The dataset contains no real exposure denominator; an unobserved pair is not a real ignore.",
                "Top20 holdout results are a sparse-data diagnostic, not a production recommendation accuracy claim.",
                "The target record contains a view link but no local media file for embedded playback.",
                "Sensitive request material and source responses are excluded from every report artifact.",
            ],
            users=rows,
        )
        return _build_explainable_payload(base_payload, self.source.runtime_summary)

    def _build_field_trace_bundle(self) -> FieldLineageTraceBundle:
        outcomes = _unique_user_rows(self.source.ranking_outcomes, "ranking outcomes")
        exposed_user_ids = {
            user_id for user_id, row in outcomes.items() if row.get("result_status") != "below_delivery_capacity"
        }
        artifacts = _required_mapping(self.source.artifact_manifest, "artifacts", "artifact manifest")
        return FieldLineageTraceModule().build(
            FieldLineageTraceSource(
                users=self.source.users,
                historical_tags_by_user=self.source.historical_tags_by_user,
                interest_tag_evidence_by_user=self.source.interest_tag_evidence_by_user,
                historical_tag_evidence_by_user=self.source.historical_tag_evidence_by_user,
                exposed_user_ids=exposed_user_ids,
                prompt_inclusion_by_user=self.source.prompt_field_inclusion_by_user,
                artifact_paths={str(key): str(value) for key, value in artifacts.items()},
            )
        )

    def _build_user_rows(self) -> list[UserReportRow]:
        exposures = {str(row.get("user_id", "")): row for row in self.source.runtime_exposures}
        decisions = {str(row.get("user_id", "")): row for row in self.source.runtime_decisions}
        failures = {str(row.get("user_id", "")): row for row in self.source.runtime_provider_failures}
        rows: list[UserReportRow] = []
        for user in self.source.users:
            user_id = str(user.get("user_id", ""))
            exposure = exposures.get(user_id)
            decision = decisions.get(user_id)
            failure = failures.get(user_id)
            latent_source = user.get("latent_attributes", {})
            latent_attributes = (
                {
                    str(key): value
                    for key, value in latent_source.items()
                    if isinstance(value, (str, int, float)) and not isinstance(value, bool)
                }
                if isinstance(latent_source, Mapping)
                else {}
            )
            exposure_status, result_status, provider_status = self._statuses(exposure, decision, failure)
            rows.append(
                UserReportRow(
                    user_id=user_id,
                    nickname=str(user.get("nickname", "")),
                    bio=str(user.get("bio", "")),
                    signature=str(user.get("signature", "")),
                    interest_tags=_string_list(user.get("interest_tags")),
                    historical_tags=sorted({str(tag) for tag in self.source.historical_tags_by_user.get(user_id, ())}),
                    follower_count=_as_int(user.get("follower_count")),
                    following_count=_as_int(user.get("following_count")),
                    video_count=_as_int(user.get("video_count")),
                    activity_score=_as_float(user.get("activity_score")),
                    activity_video_score=_as_float(user.get("activity_video_score")),
                    activity_comment_score=_as_float(user.get("activity_comment_score")),
                    activity_reply_score=_as_float(user.get("activity_reply_score")),
                    global_influence_score=_as_float(user.get("global_influence_score")),
                    local_influence_score=_as_float(user.get("local_influence_score")),
                    local_network_score=_as_float(user.get("local_network_score")),
                    local_recognition_score=_as_float(user.get("local_recognition_score")),
                    latent_attributes=latent_attributes,
                    sample_source_scope=str(user.get("sample_source_scope", "")),
                    is_seed=bool(user.get("is_seed", False)),
                    sample_role=_sample_role(user.get("sample_role", "ordinary")),
                    assigned_step=_optional_int(exposure, "assigned_step"),
                    base_network_score=_optional_float(exposure, "base_network_score"),
                    dynamic_network_score=_optional_float(exposure, "dynamic_network_score"),
                    engaged_neighbor_count=_optional_int(exposure, "engaged_neighbor_count"),
                    historical_tag_affinity=_optional_float(exposure, "historical_tag_affinity"),
                    recommendation_score=_optional_float(exposure, "recommendation_score"),
                    random_draw=_optional_float(exposure, "random_draw"),
                    exposure_status=exposure_status,
                    result_status=result_status,
                    action=_report_action(decision.get("action") if decision else ""),
                    engage=_optional_bool(decision, "engage"),
                    reason=str(decision.get("reason", "")) if decision else "",
                    confidence=_optional_float(decision, "confidence"),
                    decision_source=str(decision.get("decision_source", "")) if decision else "",
                    provider_status=provider_status,
                    provider_failure_type=str(failure.get("failure_type", "")) if failure else "",
                )
            )
        return rows

    def _statuses(
        self,
        exposure: Mapping[str, object] | None,
        decision: Mapping[str, object] | None,
        failure: Mapping[str, object] | None,
    ) -> tuple[ExposureStatus, ResultStatus, ProviderStatus]:
        if not self.source.runtime_enabled:
            return "runtime_not_run", "runtime_not_run", "runtime_not_run"
        if exposure is None:
            return "missing_exposure", "missing_decision", "missing_decision"
        exposure_status = _exposure_status(exposure.get("exposure_outcome"))
        if exposure_status == "background_content":
            return exposure_status, "background_content", "not_called"
        if failure is not None:
            return exposure_status, "provider_failed", "provider_failed"
        if decision is None:
            return exposure_status, "missing_decision", "missing_decision"
        action = str(decision.get("action", "ignore"))
        if action not in {"like", "comment", "share", "ignore"}:
            action = "ignore"
        return exposure_status, _result_action(action), "succeeded"

    def _aggregates(self, rows: Sequence[UserReportRow]) -> FinalResearchAggregates:
        return _build_report_aggregates(rows, _as_int(self.source.config.get("horizon")))

    def _write_csv(
        self,
        path: Path,
        rows: Sequence[UserReportRow] | Sequence[RankingUserReportRow],
    ) -> None:
        safe_rows = safe_user_data([row.csv_row() for row in rows])
        if not isinstance(safe_rows, list):  # pragma: no cover
            raise TypeError("safe user rows must remain a list")
        fieldnames = (
            list(RankingUserReportRow.model_fields)
            if rows and isinstance(rows[0], RankingUserReportRow)
            else list(UserReportRow.model_fields)
        )
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(safe_rows)

    @staticmethod
    def render_payload(
        payload: FinalResearchReportPayload | FinalResearchRankingReportPayloadV3 | FinalResearchRankingReportPayload,
    ) -> str:
        if isinstance(payload, (FinalResearchRankingReportPayloadV3, FinalResearchRankingReportPayload)):
            return _render_ranking_report(payload)
        payload_json = safe_user_json(payload, indent=None).replace("</", "<\\/")
        target = payload.target_video
        target_url = escape(target.video_url, quote=True)
        hashtags = " ".join(f"#{tag.lstrip('#')}" for tag in target.hashtags)
        static_formula = (
            f"{payload.recommendation_model.network_weight:.2f} network + "
            f"{payload.recommendation_model.tag_affinity_weight:.2f} historical tag affinity"
        )
        dynamic_formula = f"min(1, base + {payload.recommendation_model.neighbor_boost:.2f} × engaged direct neighbors)"
        batch_fact = str(payload.run.horizon) if payload.run.runtime_enabled else "未执行"
        batch_note = (
            f"{payload.run.horizon} 个固定推荐批次，不代表自然日"
            if payload.run.runtime_enabled
            else "Provider runtime 未执行"
        )
        opportunity_note = (
            "每个用户最多一次 TargetVideo 机会" if payload.run.runtime_enabled else "Provider runtime 未执行"
        )
        run_method_status = (
            "Persisted Seed-First Formal Run（已持久化的 Seed-First 正式运行）"
            if payload.run.sampling_status == "persisted_seed_first_formal_run"
            else "Persisted Probability Formal Run（已持久化的 Probability 正式运行）"
            if payload.run.sampling_status == "persisted_probability_formal_run"
            else "Validation Run（验证运行） · Seed-First Research Sample（先选种子研究样本）"
            if payload.run.sampling_method == "seed_first_research_sample_v1"
            else "Historical Network-Augmented Run（历史 Network-Augmented 运行）"
            if payload.run.sampling_status == "historical_network_augmented_run"
            else "Validation Run（验证运行）"
        )
        sample_role_counts = payload.sample_summary.sample_role_counts
        seed_exposures = sum(row.is_seed and row.exposure_status == "target_exposed" for row in payload.users)
        non_seed_exposures = sum(not row.is_seed and row.exposure_status == "target_exposed" for row in payload.users)
        exposure_breakdown = (
            f"{seed_exposures + non_seed_exposures} 次 Provider Decision 调用来自 "
            f"{seed_exposures} 个强制 seed 曝光和 {non_seed_exposures} 个普通用户抽签曝光。"
            if payload.run.runtime_enabled
            else "Provider runtime 未执行，因此没有 Target Exposure 或 Provider Decision 调用。"
        )
        return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>{escape(payload.title)}</title>
  <style>{_REPORT_CSS}</style>
</head>
<body>
  <main data-testid="final-research-report">
    <header class="topbar">
      <div><span class="eyebrow">FINAL RESEARCH · JINJIANG</span><h1>{escape(payload.title)}</h1><span class="quiet-badge" data-testid="run-method-status">{escape(run_method_status)}</span></div>
      <nav class="downloads" aria-label="Artifact downloads">
        <a href="{payload.downloads.csv}" download>下载 CSV</a>
        <a href="{payload.downloads.users_json}" download>下载 JSON</a>
        <a href="{payload.downloads.manifest}">Manifest</a>
      </nav>
    </header>

    <nav class="workflow-nav" data-testid="workflow-nav" aria-label="研究流程导航">
      <a href="#funnel">运行漏斗</a><a href="#methodology">数据与抽样</a><a href="#recommendation">推荐与抽签</a><a href="#decision">LLM 决策</a><a href="#users">用户追踪</a>
    </nav>

    <section class="target-band" data-testid="target-video-section">
      <div class="target-copy">
        <span class="eyebrow">TargetVideo · {escape(target.video_id)}</span>
        <h2>{escape(target.caption)}</h2>
        <p class="tags">{escape(hashtags)}</p>
        <div class="inline-actions"><a class="primary-link" href="{target_url}" target="_blank" rel="noreferrer">查看真实视频入口</a><span>当前无可嵌入媒体文件</span></div>
      </div>
      <dl class="target-facts"><div><dt>来源 scope</dt><dd>{escape(target.source_challenge_name)}</dd></div><div><dt>样本用户</dt><dd>{len(payload.users):,}</dd></div><div><dt>推荐批次</dt><dd>{batch_fact}</dd></div><div><dt>随机种子</dt><dd>{payload.run.random_seed}</dd></div></dl>
    </section>

    <section class="object-flow" data-testid="core-objects-section">
      <article><span>01</span><h3>TargetVideo</h3><p>真实 caption、hashtags 与查看入口</p></article>
      <i aria-hidden="true">→</i>
      <article><span>02</span><h3>ResearchUser</h3><p>真实观测画像与合成实验标签</p></article>
      <i aria-hidden="true">→</i>
      <article><span>03</span><h3>PlatformRecommendationModel</h3><p>网络信号、历史标签与动态邻居反馈</p></article>
    </section>

    <section class="content-band" id="funnel" data-testid="funnel-section">
      <div class="split-heading"><div><span class="eyebrow">RUN FUNNEL</span><h2>从离线评分到最终结果</h2></div><span class="muted">所有数字均来自本次持久化 artifacts</span></div>
      <div class="funnel-grid" id="run-funnel"></div>
    </section>

    <section class="content-band" id="methodology" data-testid="methodology-section">
      <div class="split-heading"><div><span class="eyebrow">METHOD</span><h2>数据、抽样、视频与评论网络</h2></div><span class="quiet-badge">holdout-safe</span></div>
      <div class="method-grid" id="methodology-flow"></div>
      <div class="evidence-grid">
        <article><h3>视频用途</h3><p id="target-video-role"></p><p class="muted" id="background-video-role"></p></article>
        <article><h3>Source-scope 配额与补齐</h3><p id="sampling-method"></p><p class="muted" id="sampling-counts"></p></article>
        <article><h3>评论派生网络</h3><p id="comment-network"></p><p class="muted" id="holdout-projection"></p></article>
      </div>
    </section>

    <section class="metrics-band" data-testid="summary-metrics">
      <article><span>Target exposures</span><strong id="metric-exposures">0</strong></article>
      <article><span>Engagements</span><strong id="metric-engagements">0</strong></article>
      <article><span>Background</span><strong id="metric-background">0</strong></article>
      <article><span>Provider failed</span><strong id="metric-failed">0</strong></article>
      <article><span>Seed users</span><strong>{payload.sample_summary.seed_count}</strong></article>
      <article><span>Seed Neighbor Cohort</span><strong>{sample_role_counts.get("network_cohort", 0)}</strong></article>
      <article><span>Ordinary users</span><strong>{sample_role_counts.get("ordinary", 0)}</strong></article>
    </section>

    <section class="content-band" id="recommendation" data-testid="recommendation-section">
      <div class="split-heading"><div><span class="eyebrow">RESEARCH CONTRACT</span><h2>推荐模型与字段边界</h2></div><code>{escape(static_formula)}</code></div>
      <div class="formula-stack">
        <article><span>静态公式</span><code id="static-formula"></code></article>
        <article><span>动态公式</span><code id="dynamic-formula"></code></article>
      </div>
      <div class="example-grid">
        <article data-testid="seed-example"><h3>Seed 强制曝光示例</h3><div id="seed-example"></div></article>
        <article data-testid="non-seed-example"><h3>Non-seed 抽签示例</h3><div id="non-seed-example"></div></article>
      </div>
      <div class="boundary-grid">
        <article><h3>Observed</h3><p>来源事实与可复算代理指标</p><ul id="observed-list"></ul></article>
        <article><h3>Latent</h3><p>只用于受控仿真实验</p><ul id="latent-list"></ul></article>
        <article><h3>Dynamic signal</h3><p><code>{escape(dynamic_formula)}</code></p><p class="muted">只影响尚未进入固定批次的直接邻居。</p></article>
      </div>
      <p class="boundary-statement">{escape(payload.observed_latent_boundary.statement)}</p>
    </section>

    <section class="content-band" id="decision" data-testid="decision-section">
      <div class="split-heading"><div><span class="eyebrow">BATCH & DECISION</span><h2>固定批次、曝光抽签与 LLM 合同</h2></div><span class="muted">{opportunity_note}</span></div>
      <div class="evidence-grid">
        <article><h3 id="batch-heading">固定批次</h3><p id="batch-method"></p><p class="muted" data-testid="exposure-breakdown">{escape(exposure_breakdown)}</p></article>
        <article><h3>结构化决策字段</h3><p id="decision-fields"></p><p class="muted" id="decision-recoverability"></p></article>
        <article><h3>动态邻居信号</h3><p id="neighbor-summary"></p></article>
      </div>
      <div class="outcome-list" id="outcome-explanations" data-testid="outcome-explanations"></div>
    </section>

    <section class="content-band" data-testid="diagnostics-section">
      <div class="split-heading"><div><span class="eyebrow">DIAGNOSTICS</span><h2>样本、seed 与 Top20 holdout</h2></div><span class="quiet-badge">diagnostic only</span></div>
      <div class="diagnostic-grid" id="diagnostic-grid"></div>
    </section>

    <section class="content-band" data-testid="charts-section">
      <div class="split-heading"><div><span class="eyebrow">AGGREGATES</span><h2>运行趋势与信号覆盖</h2></div><span class="muted">{batch_note}</span></div>
      <div class="chart-grid">
        <article class="wide"><h3>各批次曝光与参与趋势</h3><div class="timeline-chart" data-testid="trend-chart" id="trend-chart"></div></article>
        <article><h3>Action / result 分布</h3><div class="bar-chart" data-testid="action-chart" id="action-chart"></div></article>
        <article><h3>Source scope 分布</h3><div class="bar-chart" data-testid="scope-chart" id="scope-chart"></div></article>
        <article><h3>Provider failure</h3><div class="bar-chart" data-testid="provider-chart" id="provider-chart"></div></article>
        <article><h3>动态邻居信号</h3><div class="bar-chart" data-testid="neighbor-chart" id="neighbor-chart"></div></article>
      </div>
    </section>

    <section class="users-band" id="users" data-testid="users-section">
      <div class="split-heading"><div><span class="eyebrow">ALL RESEARCH USERS</span><h2>完整用户级结果</h2></div><strong id="visible-user-count"></strong></div>
      <div class="filters">
        <label><span>搜索</span><input data-testid="user-search" id="user-search" type="search" placeholder="user_id / 昵称 / 标签 / reason"></label>
        <label><span>Result</span><select data-testid="result-filter" id="result-filter"><option value="">全部</option></select></label>
        <label><span>Source scope</span><select data-testid="scope-filter" id="scope-filter"><option value="">全部</option></select></label>
        <label><span>Seed</span><select data-testid="seed-filter" id="seed-filter"><option value="">全部</option><option value="true">Seed</option><option value="false">Non-seed</option></select></label>
      </div>
      <div class="table-wrap"><table data-testid="user-table"><thead><tr><th>用户画像</th><th>Scope / seed</th><th>Step</th><th>曝光概率 / 抽签</th><th>Action / provider</th><th>Reason / confidence</th></tr></thead><tbody id="user-table-body"></tbody></table></div>
      <aside class="user-detail" data-testid="user-detail" id="user-detail"><span class="muted">选择一行查看完整用户时间线与 allowlisted 字段。</span></aside>
    </section>

    <section class="limitations-band" data-testid="limitations-section"><div><span class="eyebrow">LIMITATIONS</span><h2>解释边界</h2></div><ul id="limitations-list"></ul></section>
    <footer><a href="{payload.downloads.payload}">Report payload</a><a href="{payload.downloads.csv}">User CSV</a><a href="{payload.downloads.users_json}">User JSON</a><a href="{payload.downloads.manifest}">Artifact manifest</a></footer>
  </main>
  <script id="final-research-payload" type="application/json">{payload_json}</script>
  <script>{_REPORT_JS}</script>
</body>
</html>
"""


def _build_ranking_report_payload(
    source: FinalResearchReportSource,
    trace_bundle: FieldLineageTraceBundle,
) -> FinalResearchRankingReportPayload:
    if source.network_sample_audit is None:
        raise ValueError("ranking report requires network sample audit evidence")
    if source.ranking_runtime_summary is None:
        raise ValueError("ranking report requires ranking runtime summary evidence")
    if source.ranking_diagnostics is None:
        raise ValueError("ranking report requires ranking diagnostics evidence")
    if source.ranking_diagnostics_summary is None:
        raise ValueError("ranking report requires ranking diagnostics summary evidence")

    audit = source.network_sample_audit
    runtime_summary = source.ranking_runtime_summary
    diagnostic_summary = source.ranking_diagnostics_summary
    manifest_artifacts = _required_mapping(source.artifact_manifest, "artifacts", "artifact manifest")
    seed_first = audit.get("schema_version") == "seed-first-sample-audit-v1"
    final_sample = _required_mapping(audit, "final_sample", "sample audit")
    if seed_first:
        roles = _required_mapping(audit, "roles", "seed-first sample audit")
        role_counts = _mapping_counts(roles, "counts", "seed-first sample roles")
        role_user_ids = _required_mapping(roles, "user_ids", "seed-first sample roles")
        cohort_user_ids_list = [
            str(value) for value in _required_list(role_user_ids, "network_cohort", "seed-first roles")
        ]
        base_sample: Mapping[str, object] = {"count": 0, "user_ids": [], "source_scope_counts": {}}
        network_cohort: Mapping[str, object] = {
            "count": _as_int(role_counts.get("network_cohort")),
            "user_ids": cohort_user_ids_list,
            "added_user_ids": cohort_user_ids_list,
        }
        replacement: Mapping[str, object] = {"count": 0}
        seed_count = _as_int(role_counts.get("seed"))
        ordinary_count = _as_int(role_counts.get("ordinary"))
    else:
        base_sample = _required_mapping(audit, "base_sample", "network sample audit")
        network_cohort = _required_mapping(audit, "network_cohort", "network sample audit")
        replacement = _required_mapping(audit, "ordinary_replacement", "network sample audit")
        seed_count = _as_int(audit.get("seed_count"))
        ordinary_count = _as_int(final_sample.get("count")) - seed_count - _as_int(network_cohort.get("count"))
    runtime_counts = _mapping_counts(runtime_summary, "counts", "ranking runtime summary")

    outcomes = _unique_user_rows(source.ranking_outcomes, "ranking outcomes")
    decisions = _unique_user_rows(source.runtime_decisions, "runtime decisions")
    failures = _unique_user_rows(source.runtime_provider_failures, "runtime provider failures")
    offline_scores = _unique_user_rows(source.offline_scores, "offline scores")
    candidates_by_user: dict[str, list[Mapping[str, object]]] = {}
    candidate_keys: set[tuple[int, str]] = set()
    candidates_by_step: dict[int, list[Mapping[str, object]]] = {}
    for candidate in source.ranking_candidates:
        user_id = str(candidate.get("user_id", ""))
        time_step = _as_int(candidate.get("time_step"))
        key = (time_step, user_id)
        if not user_id or key in candidate_keys:
            raise ValueError("ranking candidates must contain unique non-empty user ids per batch")
        candidate_keys.add(key)
        candidates_by_user.setdefault(user_id, []).append(candidate)
        candidates_by_step.setdefault(time_step, []).append(candidate)

    base_user_ids = {str(value) for value in _required_list(base_sample, "user_ids", "base sample")}
    cohort_user_ids = {str(value) for value in _required_list(network_cohort, "user_ids", "network cohort")}
    rows: list[RankingUserReportRow] = []
    for raw_user in source.users:
        safe_user = safe_user_data(dict(raw_user))
        if not isinstance(safe_user, dict):  # pragma: no cover
            raise TypeError("safe ranking user must remain an object")
        user_id = str(safe_user.get("user_id", ""))
        outcome = outcomes.get(user_id)
        score = offline_scores.get(user_id)
        user_candidates = candidates_by_user.get(user_id, [])
        if outcome is None or score is None or not user_candidates:
            raise ValueError(f"ranking report evidence is incomplete for user {user_id!r}")
        exposure_time_step = _optional_int(outcome, "exposure_time_step")
        latest_candidate = max(user_candidates, key=lambda row: _as_int(row.get("time_step")))
        if exposure_time_step is not None:
            latest_candidate = next(
                (
                    candidate
                    for candidate in user_candidates
                    if _as_int(candidate.get("time_step")) == exposure_time_step
                ),
                latest_candidate,
            )
        latent = safe_user.get("latent_attributes")
        if not isinstance(latent, Mapping):
            raise ValueError(f"ranking report user {user_id!r} has no latent_attributes object")
        decision = decisions.get(user_id)
        failure = failures.get(user_id)
        result_status = _ranking_result_status(outcome.get("result_status"))
        is_seed = bool(safe_user.get("is_seed", False))
        is_network_cohort = user_id in cohort_user_ids
        sample_role: SampleRole = "seed" if is_seed else "network_cohort" if is_network_cohort else "ordinary"
        rows.append(
            RankingUserReportRow(
                user_id=user_id,
                nickname=str(safe_user.get("nickname", "")),
                bio=str(safe_user.get("bio", "")),
                signature=str(safe_user.get("signature", "")),
                interest_tags=_string_list(safe_user.get("interest_tags")),
                historical_tags=sorted({str(tag) for tag in source.historical_tags_by_user.get(user_id, ())}),
                follower_count=_as_int(safe_user.get("follower_count")),
                following_count=_as_int(safe_user.get("following_count")),
                video_count=_as_int(safe_user.get("video_count")),
                activity_score=_as_float(safe_user.get("activity_score")),
                activity_video_score=_as_float(safe_user.get("activity_video_score")),
                activity_comment_score=_as_float(safe_user.get("activity_comment_score")),
                activity_reply_score=_as_float(safe_user.get("activity_reply_score")),
                global_influence_score=_as_float(safe_user.get("global_influence_score")),
                local_influence_score=_as_float(safe_user.get("local_influence_score")),
                local_network_score=_as_float(safe_user.get("local_network_score")),
                local_recognition_score=_as_float(safe_user.get("local_recognition_score")),
                latent_attribute_spec_id=str(latent.get("latent_attribute_spec_id", "")),
                latent_attribute_method=str(latent.get("latent_attribute_method", "")),
                latent_attribute_seed=_as_int(latent.get("latent_attribute_seed")),
                latent_class=str(latent.get("latent_class", "")),
                latent_environmental_consciousness_coef=_as_float(
                    latent.get("latent_environmental_consciousness_coef")
                ),
                latent_epistemic_value_weight=_as_float(latent.get("latent_epistemic_value_weight")),
                latent_environmental_value_weight=_as_float(latent.get("latent_environmental_value_weight")),
                latent_functional_value_weight=_as_float(latent.get("latent_functional_value_weight")),
                latent_health_value_weight=_as_float(latent.get("latent_health_value_weight")),
                latent_emotional_value_weight=_as_float(latent.get("latent_emotional_value_weight")),
                latent_social_value_weight=_as_float(latent.get("latent_social_value_weight")),
                latent_hotel_class=str(latent.get("latent_hotel_class", "")),
                latent_travel_purpose=str(latent.get("latent_travel_purpose", "")),
                latent_gender=str(latent.get("latent_gender", "")),
                latent_age=str(latent.get("latent_age", "")),
                latent_education=str(latent.get("latent_education", "")),
                latent_monthly_income=str(latent.get("latent_monthly_income", "")),
                sample_source_scope=str(safe_user.get("sample_source_scope", "")),
                in_base_sample=user_id in base_user_ids,
                is_seed=is_seed,
                is_network_cohort=is_network_cohort,
                sample_role=sample_role,
                historical_comment_network_weighted_degree=_as_int(score.get("target_scope_weighted_degree")),
                latest_ranking_time_step=_as_int(latest_candidate.get("time_step")),
                latest_ranking_position=_as_int(latest_candidate.get("ranking_position")),
                selected_for_exposure=result_status != "below_delivery_capacity",
                base_network_relevance=_as_float(latest_candidate.get("base_network_relevance")),
                engaged_neighbor_count=_as_int(latest_candidate.get("engaged_neighbor_count")),
                engaged_neighbor_signal=_as_float(latest_candidate.get("engaged_neighbor_signal")),
                historical_tag_affinity=_as_float(latest_candidate.get("historical_tag_affinity")),
                recommendation_score=_as_float(latest_candidate.get("recommendation_score")),
                exposure_time_step=exposure_time_step,
                result_status=result_status,
                provider_status=_ranking_provider_status(outcome.get("provider_status")),
                action=_report_action(decision.get("action") if decision else ""),
                engage=_optional_bool(decision, "engage"),
                probability=_optional_float(decision, "probability"),
                reason=str(decision.get("reason", "")) if decision else "",
                confidence=_optional_float(decision, "confidence"),
                decision_source=str(decision.get("decision_source", "")) if decision else "",
                provider_failure_type=str(failure.get("failure_type", "")) if failure else "",
            )
        )

    target_video = safe_user_data(dict(source.target_video))
    if not isinstance(target_video, dict):  # pragma: no cover
        raise TypeError("safe target video must remain an object")
    configured_title = str(source.config.get("report_title") or "")
    title = (
        "锦江酒店 Target Delivery Ranking Research Report"
        if not configured_title or configured_title == "LLM-ABM Simulation Report"
        else configured_title
    )
    rounds = _ranking_round_summaries(
        source.ranking_steps,
        candidates_by_step,
        _as_int(runtime_summary.get("delivery_capacity")),
    )
    inclusion = _required_mapping(
        diagnostic_summary,
        "recommendation_signal_inclusion",
        "ranking diagnostics summary",
    )
    effect = _required_mapping(
        diagnostic_summary,
        "observed_recommendation_signal_effect",
        "ranking diagnostics summary",
    )
    lineage = _ranking_field_lineage()
    allowed_prompt_fields = list(JINJIANG_PROMPT_V2_PROFILE_FIELDS)
    return FinalResearchRankingReportPayload(
        title=title,
        core_objects=("TargetVideo", "ResearchUser", "PlatformRecommendationModel"),
        target_video=FinalResearchTargetVideo.model_validate(target_video),
        run=RankingReportRun(
            sample_size=len(rows),
            horizon=_as_int(runtime_summary.get("horizon")),
            random_seed=_as_int(source.config.get("random_seed")),
            delivery_capacity=_as_int(runtime_summary.get("delivery_capacity")),
            maximum_target_exposures=_as_int(runtime_summary.get("maximum_target_exposures")),
            ranking_formula=str(runtime_summary.get("ranking_formula", "")),
            engaged_neighbor_formula=str(runtime_summary.get("engaged_neighbor_formula", "")),
            sampling_method=_sampling_method(
                runtime_summary.get("sampling_method")
                or source.artifact_manifest.get("sampling_method")
                or "network_augmented_research_sample"
            ),
            sampling_status=_sampling_status(
                runtime_summary.get("sampling_status")
                or source.artifact_manifest.get("sampling_status")
                or "historical_network_augmented_run"
            ),
        ),
        run_funnel=[
            _typed_funnel_stage(
                "processed_users",
                "Processed users scored",
                _as_int(source.offline_score_summary.get("user_count")),
                "权威 processed variant 中完成 holdout-safe 离线评分的用户。",
            ),
            *(
                []
                if seed_first
                else [
                    _typed_funnel_stage(
                        "base_sample",
                        "Base Sample",
                        _as_int(base_sample.get("count")),
                        "按 source scope 配额、去重与固定随机种子形成。",
                    )
                ]
            ),
            _typed_funnel_stage(
                "seeds",
                "Seeds",
                seed_count,
                (
                    "从全部合格 processed users 形成的 Full-Pool Influence Seed Union。"
                    if seed_first
                    else "从 Base Sample 选出的 seed union。"
                ),
            ),
            _typed_funnel_stage(
                "network_cohort",
                "Network Cohort",
                _as_int(network_cohort.get("count")),
                "Historical Set 评论网络中的 seed 直接邻居。",
            ),
            _typed_funnel_stage(
                "final_sample",
                "Seed-First Research Sample" if seed_first else "Network-Augmented Research Sample",
                len(rows),
                (
                    "seeds 和直接邻居优先进入，再按 Primary Video Source Scope 配额补足普通用户。"
                    if seed_first
                    else "保持总量不变并替换等量普通用户后的最终样本。"
                ),
            ),
            _typed_funnel_stage(
                "target_exposures",
                "Target exposures",
                _as_int(runtime_counts.get("target_exposures")),
                "实际进入 Delivery Capacity 并调用 Decision Adapter 的用户。",
            ),
            _typed_funnel_stage(
                "provider_decisions",
                "Provider decisions",
                _as_int(runtime_counts.get("decisions")),
                "成功返回结构化 Decision 的 provider 调用。",
            ),
            _typed_funnel_stage(
                "provider_failed",
                "Provider failed",
                _as_int(runtime_counts.get("provider_failed")),
                "重试耗尽后保留的独立失败状态。",
            ),
            _typed_funnel_stage(
                "below_delivery_capacity",
                "Below delivery capacity",
                _as_int(runtime_counts.get("below_delivery_capacity")),
                "最终批次结束仍未获得目标曝光，不等于 ignore。",
            ),
        ],
        sample_comparison=RankingSampleComparison(
            base_sample_count=_as_int(base_sample.get("count")),
            final_sample_count=_as_int(final_sample.get("count")),
            seed_count=seed_count,
            network_cohort_count=_as_int(network_cohort.get("count")),
            network_cohort_added_count=len(_required_list(network_cohort, "added_user_ids", "network cohort")),
            replacement_count=_as_int(replacement.get("count")),
            base_source_scope_counts=_int_mapping(base_sample.get("source_scope_counts")),
            final_source_scope_counts=_int_mapping(final_sample.get("source_scope_counts")),
            ordinary_count=ordinary_count,
        ),
        sample_role_counts=dict(sorted(Counter(row.sample_role for row in rows).items())),
        field_lineage=lineage,
        field_lineage_catalog=trace_bundle.catalog,
        user_field_trace_index=trace_bundle.trace_index,
        prompt_contract=RankingPromptContract(
            allowed_profile_fields=allowed_prompt_fields,
            neutralized_fields=[
                "peer_context.exposed_neighbors",
                "peer_context.engaged_neighbors",
                "peer_context.engagement_ratio",
                "peer_context.influential_engaged_neighbors",
                "peer_context.visible_likes",
                "peer_context.visible_comments",
                "peer_context.visible_shares",
            ],
            excluded_fields=[
                "historical_comment_network_weighted_degree",
                "base_network_relevance",
                "engaged_neighbor_count",
                "engaged_neighbor_signal",
                "historical_tag_affinity",
                "recommendation_score",
                "latest_ranking_position",
                "Target Holdout answers",
            ],
            statement=(
                "Ranking, comment-network runtime state and Target Holdout evidence are excluded from the LLM "
                "Prompt; the compatibility PeerContext is neutral."
            ),
        ),
        ranking_rounds=rounds,
        ranking_diagnostics=dict(source.ranking_diagnostics),
        ranking_diagnostics_summary=RankingDiagnosticSummary(
            network_signals_in_formula=_strict_bool(inclusion.get("network_signals_in_formula")),
            main_weights={
                str(key): _as_float(value)
                for key, value in _required_mapping(inclusion, "main_weights", "ranking signal inclusion").items()
            },
            top_selection_changed=_strict_bool(effect.get("top_selection_changed")),
            batches_with_top_selection_change=_as_int(effect.get("batches_with_top_selection_change")),
            diagnostic_decision_adapter_calls=_as_int(diagnostic_summary.get("diagnostic_decision_adapter_calls")),
        ),
        downloads=RankingReportDownloads(
            report=FINAL_RESEARCH_REPORT_ARTIFACTS["final_research_report"],
            payload=FINAL_RESEARCH_REPORT_ARTIFACTS["final_research_report_payload"],
            csv=FINAL_RESEARCH_REPORT_ARTIFACTS["final_research_users_csv"],
            users_json=FINAL_RESEARCH_REPORT_ARTIFACTS["final_research_users_json"],
            manifest="artifact_manifest.json",
            ranking_diagnostics=str(manifest_artifacts["ranking_diagnostics"]),
            ranking_ablation_csv=str(manifest_artifacts["ranking_ablation_diagnostics_csv"]),
            ranking_sensitivity_csv=str(manifest_artifacts["ranking_weight_sensitivity_csv"]),
            field_lineage_catalog=str(manifest_artifacts["field_lineage_catalog"]),
            user_field_trace=str(manifest_artifacts["user_field_trace"]),
            field_source_records=str(manifest_artifacts["field_source_records"]),
        ),
        limitations=[
            "Network Cohort supports propagation identification and is not a representative random sample.",
            "Ranking weights are predeclared research assumptions, not learned Douyin platform parameters.",
            "Paired ablation is a frozen-evidence shadow ranking, not a second user-state trajectory.",
            "No real exposure denominator is available; below delivery capacity is not a user ignore decision.",
        ],
        users=rows,
    )


def _ranking_round_summaries(
    step_rows: Sequence[Mapping[str, object]],
    candidates_by_step: Mapping[int, Sequence[Mapping[str, object]]],
    delivery_capacity: int,
) -> list[RankingRoundSummary]:
    rounds: list[RankingRoundSummary] = []
    for step in step_rows:
        time_step = _as_int(step.get("time_step"))
        candidates = [
            RankingCandidateEvidence(
                ranking_position=_as_int(row.get("ranking_position")),
                user_id=str(row.get("user_id", "")),
                is_seed=_as_bool(row.get("is_seed")),
                selected=_as_bool(row.get("selected")),
                base_network_relevance=_as_float(row.get("base_network_relevance")),
                engaged_neighbor_count=_as_int(row.get("engaged_neighbor_count")),
                engaged_neighbor_signal=_as_float(row.get("engaged_neighbor_signal")),
                historical_tag_affinity=_as_float(row.get("historical_tag_affinity")),
                recommendation_score=_as_float(row.get("recommendation_score")),
            )
            for row in sorted(
                candidates_by_step.get(time_step, ()),
                key=lambda row: _as_int(row.get("ranking_position")),
            )
        ]
        selected = [row for row in candidates if row.selected]
        positive_signal = [row for row in candidates if row.engaged_neighbor_signal > 0.0]
        rounds.append(
            RankingRoundSummary(
                time_step=time_step,
                eligible_count=_as_int(step.get("eligible_users")),
                delivery_capacity=delivery_capacity,
                selected_count=_as_int(step.get("selected_users")),
                selected_user_ids=[row.user_id for row in selected],
                target_exposures=_as_int(step.get("target_exposures")),
                decisions=_as_int(step.get("decisions")),
                engagements=_as_int(step.get("engagements")),
                ignored=_as_int(step.get("ignored")),
                provider_failed=_as_int(step.get("provider_failed")),
                below_delivery_capacity=_as_int(step.get("below_delivery_capacity")),
                candidates_with_positive_engaged_neighbor_signal=len(positive_signal),
                selected_with_positive_engaged_neighbor_signal=sum(row.selected for row in positive_signal),
                maximum_engaged_neighbor_signal=max(
                    (row.engaged_neighbor_signal for row in candidates),
                    default=0.0,
                ),
                candidates=candidates,
            )
        )
    return rounds


def _ranking_lineage_field_names() -> set[str]:
    return {
        *RankingUserReportRow.model_fields,
        *(f"target_video.{field}" for field in FinalResearchTargetVideo.model_fields),
        *(f"run.{field}" for field in RankingReportRun.model_fields),
        *(f"sample_comparison.{field}" for field in RankingSampleComparison.model_fields),
        *(f"ranking_rounds.{field}" for field in RankingRoundSummary.model_fields if field != "candidates"),
        *(f"ranking_rounds.candidates.{field}" for field in RankingCandidateEvidence.model_fields),
        "ranking_diagnostics.paired_ablation",
        "ranking_diagnostics.weight_sensitivity",
        "ranking_diagnostics.historical_top20_diagnostic",
        "ranking_diagnostics.summary",
    }


def _ranking_field_lineage() -> list[FieldLineageEntry]:
    direct = {
        "user_id",
        "nickname",
        "bio",
        "signature",
        "follower_count",
        "following_count",
        "video_count",
        *(f"target_video.{field}" for field in FinalResearchTargetVideo.model_fields),
        "ranking_rounds.candidates.user_id",
    }
    historical = {
        "interest_tags",
        "historical_tags",
        "sample_source_scope",
        "historical_comment_network_weighted_degree",
    }
    derived = {
        "activity_score",
        "activity_video_score",
        "activity_comment_score",
        "activity_reply_score",
        "global_influence_score",
        "local_influence_score",
        "local_network_score",
        "local_recognition_score",
        "base_network_relevance",
        "engaged_neighbor_count",
        "engaged_neighbor_signal",
        "historical_tag_affinity",
        "recommendation_score",
        "run.ranking_formula",
        "run.engaged_neighbor_formula",
        "ranking_rounds.candidates.base_network_relevance",
        "ranking_rounds.candidates.engaged_neighbor_count",
        "ranking_rounds.candidates.engaged_neighbor_signal",
        "ranking_rounds.candidates.historical_tag_affinity",
        "ranking_rounds.candidates.recommendation_score",
    }
    synthetic = {field for field in RankingUserReportRow.model_fields if field.startswith("latent_")}
    synthetic.update({"run.random_seed", "run.delivery_capacity", "run.maximum_target_exposures"})
    all_fields = _ranking_lineage_field_names()
    stages: dict[str, list[FieldUsageStage]] = {field: ["Report Only"] for field in all_fields}
    stages["user_id"] = ["Sampling", "Seed Selection", "Ranking", "Report Only"]
    stages["sample_source_scope"] = ["Sampling", "Report Only"]
    stages["in_base_sample"] = ["Sampling", "Report Only"]
    stages["is_network_cohort"] = ["Sampling", "Ranking", "Report Only"]
    stages["sample_role"] = ["Sampling", "Report Only"]
    stages["is_seed"] = ["Seed Selection", "Ranking", "Report Only"]
    stages["global_influence_score"] = ["Seed Selection", "LLM Prompt", "Report Only"]
    stages["local_influence_score"] = ["Seed Selection", "LLM Prompt", "Report Only"]
    stages["activity_score"] = ["LLM Prompt", "Report Only"]
    stages["interest_tags"] = ["LLM Prompt", "Report Only"]
    for field in JINJIANG_PROMPT_V2_PROFILE_FIELDS:
        stages[field] = ["LLM Prompt", "Report Only"]
    for field in (
        "historical_tags",
        "historical_comment_network_weighted_degree",
        "base_network_relevance",
        "engaged_neighbor_count",
        "engaged_neighbor_signal",
        "historical_tag_affinity",
        "recommendation_score",
        "latest_ranking_time_step",
        "latest_ranking_position",
        "selected_for_exposure",
    ):
        stages[field] = ["Ranking", "Report Only"]
    stages["target_video.caption"] = ["LLM Prompt", "Report Only"]
    stages["target_video.hashtags"] = ["Ranking", "LLM Prompt", "Report Only"]
    stages["run.random_seed"] = ["Sampling", "Report Only"]
    for field in RankingSampleComparison.model_fields:
        stages[f"sample_comparison.{field}"] = ["Sampling", "Report Only"]
    for field in RankingReportRun.model_fields:
        if field != "random_seed":
            stages[f"run.{field}"] = ["Ranking", "Report Only"]
    for field in RankingRoundSummary.model_fields:
        if field != "candidates":
            stages[f"ranking_rounds.{field}"] = ["Ranking", "Report Only"]
    for field in RankingCandidateEvidence.model_fields:
        stages[f"ranking_rounds.candidates.{field}"] = ["Ranking", "Report Only"]
    for field in (
        "ranking_diagnostics.paired_ablation",
        "ranking_diagnostics.weight_sensitivity",
        "ranking_diagnostics.historical_top20_diagnostic",
        "ranking_diagnostics.summary",
    ):
        stages[field] = ["Ranking", "Report Only"]

    entries: list[FieldLineageEntry] = []
    for field_name in sorted(all_fields):
        provenance: FieldProvenance
        if field_name in direct:
            provenance = "Direct Observed Profile Field"
        elif field_name in historical:
            provenance = "Historical Behavioral Evidence"
        elif field_name in derived:
            provenance = "Derived Proxy Metric"
        elif field_name in synthetic:
            provenance = "Synthetic Experiment Label"
        else:
            provenance = "Runtime Simulation Result"
        entries.append(
            FieldLineageEntry(
                field_name=field_name,
                provenance=provenance,
                usage_stages=stages[field_name],
            )
        )
    return entries


def _render_ranking_report(
    payload: FinalResearchRankingReportPayloadV3 | FinalResearchRankingReportPayload,
) -> str:
    target = payload.target_video
    target_url = escape(target.video_url, quote=True)
    weights = payload.ranking_diagnostics_summary.main_weights
    base_network_weight = weights["base_network"] * 100
    engaged_neighbor_weight = weights["engaged_neighbor"] * 100
    tag_affinity_weight = weights["tag_affinity"] * 100
    final_reranking_batch = max(1, payload.run.horizon - 1)
    explanation_catalog = ResearchExplanationCatalog.from_lineage(payload.field_lineage)
    sample = payload.sample_comparison
    total_exposures = sum(round_evidence.target_exposures for round_evidence in payload.ranking_rounds)
    configured_delivery_slots = payload.run.horizon * payload.run.delivery_capacity
    batch_zero_exposures = next(
        (round_evidence.target_exposures for round_evidence in payload.ranking_rounds if round_evidence.time_step == 0),
        0,
    )
    runtime_delivery_slots = batch_zero_exposures + max(0, payload.run.horizon - 1) * payload.run.delivery_capacity
    effective_exposure_limit = min(payload.run.sample_size, runtime_delivery_slots)
    provider_decisions = next(stage.count for stage in payload.run_funnel if stage.key == "provider_decisions")
    sample_role_counts = Counter(user.sample_role for user in payload.users)
    result_status_counts = Counter(user.result_status for user in payload.users)
    positive_selected_user_ids = {
        candidate.user_id
        for round_evidence in payload.ranking_rounds
        for candidate in round_evidence.candidates
        if candidate.selected and candidate.engaged_neighbor_signal > 0
    }
    explanation_context = ExplanationContext(
        base_sample_count=f"{sample.base_sample_count:,}",
        final_sample_count=f"{sample.final_sample_count:,}",
        network_cohort_added_count=f"{sample.network_cohort_added_count:,}",
        replacement_count=f"{sample.replacement_count:,}",
        field_count=f"{len(payload.field_lineage):,}",
        top_label=f"Top{payload.run.delivery_capacity}（前 {payload.run.delivery_capacity} 名）",
        base_network_weight=f"{base_network_weight:.0f}",
        engaged_neighbor_weight=f"{engaged_neighbor_weight:.0f}",
        tag_affinity_weight=f"{tag_affinity_weight:.0f}",
        horizon=f"{payload.run.horizon:,}",
        delivery_capacity=f"{payload.run.delivery_capacity:,}",
        total_exposures=f"{total_exposures:,}",
        changed_batches=f"{payload.ranking_diagnostics_summary.batches_with_top_selection_change:,}",
        batch_count=f"{len(payload.ranking_rounds):,}",
        provider_decisions=f"{provider_decisions:,}",
        user_count=f"{len(payload.users):,}",
        seed_count=f"{sample_role_counts['seed']:,}",
        network_cohort_count=f"{sample_role_counts['network_cohort']:,}",
        ordinary_count=f"{sample_role_counts['ordinary']:,}",
        final_batch=f"{max(1, payload.run.horizon - 1):,}",
        below_capacity=f"{result_status_counts['below_delivery_capacity']:,}",
        ignored=f"{result_status_counts['ignore']:,}",
        engaged=f"{sum(result_status_counts[action] for action in ('like', 'comment', 'share')):,}",
        provider_failures=f"{result_status_counts['provider_failed']:,}",
        candidate_rows=f"{sum(len(round_evidence.candidates) for round_evidence in payload.ranking_rounds):,}",
        positive_candidate_rows=f"{sum(round_evidence.candidates_with_positive_engaged_neighbor_signal for round_evidence in payload.ranking_rounds):,}",
        positive_selected_users=f"{sum(round_evidence.selected_with_positive_engaged_neighbor_signal for round_evidence in payload.ranking_rounds):,}",
        positive_signal_actions=f"{sum(user.user_id in positive_selected_user_ids and bool(user.action) for user in payload.users):,}",
    )
    explanation_document = explanation_catalog.as_document(explanation_context)
    section_explanations = explanation_document["concept_explanations"]
    downloads = payload.downloads.model_dump(mode="json")
    download_links = "".join(
        f'<a data-testid="download-{escape(key.replace("_", "-"), quote=True)}" '
        f'href="{escape(str(relative_path), quote=True)}">{escape(_ranking_download_label(key))}</a>'
        for key, relative_path in downloads.items()
    )
    seed_first_run = payload.run.sampling_method == "seed_first_research_sample_v1"
    if seed_first_run and payload.run.sampling_status == "persisted_seed_first_formal_run":
        run_method_status = "Persisted Seed-First Formal Run（已持久化的 Seed-First 正式运行）"
        run_evidence_title = "Seed-First 正式运行证据"
    elif seed_first_run:
        run_method_status = "Validation Run（验证运行） · Seed-First Research Sample（先选种子研究样本）"
        run_evidence_title = "Seed-First 离线验证证据"
    else:
        run_method_status = (
            "Historical Network-Augmented Run（历史 Network-Augmented 运行） · Persisted runtime evidence"
        )
        run_evidence_title = "历史正式运行证据"
    run_evidence_boundary = (
        "以上计数均来自当前 Seed-First run 的 persisted artifacts；Validation Run 不代表已经执行 live provider 正式运行。"
        if seed_first_run
        else "以上均来自当前历史 payload 与 persisted artifacts，不使用 Proposed Seed-First 投影改写本次运行。"
    )
    sample_heading = (
        "Seed-First Research Sample（Seed-First 研究样本）"
        if seed_first_run
        else "Base Sample（基础样本）与 Final Sample（最终样本）"
    )
    processed_user_count = next(stage.count for stage in payload.run_funnel if stage.key == "processed_users")
    mechanism_seed_count = sample.seed_count if seed_first_run else 20
    mechanism_neighbor_count = sample.network_cohort_count if seed_first_run else 60
    mechanism_ordinary_count = sample.ordinary_count if seed_first_run else 920
    mechanism_sample_count = payload.run.sample_size if seed_first_run else 1000
    mechanism_exposure_limit = effective_exposure_limit if seed_first_run else 600
    mechanism_below_capacity = max(0, mechanism_sample_count - mechanism_exposure_limit)
    mechanism_status = (
        "ADR 0003 · Accepted · persisted Validation Run"
        if seed_first_run
        else "ADR 0003 · Proposed · offline projection"
    )
    mechanism_boundary = (
        "当前 Seed-First Validation Run 的 persisted sample；它不代表已经执行 live provider 正式运行。"
        if seed_first_run
        else "Proposed Seed-First Research Sample 的 offline projection，不是旧正式 run 的新结果。"
    )
    payload_json = safe_user_json(payload, indent=None).replace("</", "<\\/")
    explanation_json = safe_user_json(explanation_document, indent=None).replace("</", "<\\/")
    sample_construction_image = _embedded_report_image("sample-construction.webp")
    batch_zero_seeds_image = _embedded_report_image("batch-zero-seeds.webp")
    global_reranking_image = _embedded_report_image("global-reranking.webp")
    platform_llm_boundary_image = _embedded_report_image("platform-llm-boundary.webp")
    neighbor_feedback_image = _embedded_report_image("neighbor-feedback.webp")
    capacity_network_impact_image = _embedded_report_image("capacity-network-impact.webp")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(payload.title)}</title>
  <link rel="icon" href="data:,">
  <style>{_RANKING_REPORT_CSS}</style>
</head>
<body>
<main data-testid="final-research-ranking-report" data-report-mode="mechanism">
  <nav class="topbar" aria-label="研究报告导航">
    <a class="brand" href="#overview">推荐机制</a>
    <div class="workflow-nav"><a href="#overview">概览</a><a href="#sample">样本</a><a href="#exposure-ranking">曝光排序</a><a href="#llm-decision">LLM 决策</a><a href="#network-feedback">网络反馈</a></div>
    <div class="mode-switch" role="tablist" aria-label="报告阅读模式">
      <button id="mechanism-mode-tab" type="button" role="tab" aria-selected="true" aria-controls="mechanism-mode-panel" data-report-mode-target="mechanism" data-testid="mechanism-mode-button">机制说明</button>
      <button id="run-evidence-mode-tab" type="button" role="tab" aria-selected="false" aria-controls="run-evidence-mode-panel" data-report-mode-target="run-evidence" data-testid="run-evidence-mode-button">本次运行</button>
    </div>
  </nav>

  <div id="mechanism-mode-panel" role="tabpanel" aria-labelledby="mechanism-mode-tab" data-report-mode-panel="mechanism" data-testid="mechanism-mode-panel">
    <section id="overview" class="sample-opening" data-section-anchor="overview" data-testid="mechanism-sample-opening">
      <div class="sample-opening-copy">
        <h1>从 {processed_user_count:,} 到 {mechanism_sample_count:,}</h1>
        <p>先选影响力种子，再纳入历史直接邻居，最后按来源配额补足普通用户。</p>
        <span class="sample-method-status">{escape(mechanism_status)}</span>
      </div>
      <figure id="sample" class="sample-opening-visual" tabindex="-1" data-section-anchor="sample" data-testid="mechanism-sample-detail" aria-label="Seed-First Research Sample 方法与证据">
        <img data-testid="sample-construction-illustration" src="{sample_construction_image}" width="1672" height="941" alt="从完整合格用户池选择影响力种子、历史直接邻居并补足研究样本的无文字示意图">
        <div class="sample-projection-label sample-projection-seeds" data-testid="sample-count-seed" aria-label="{mechanism_seed_count} seeds"><strong>{mechanism_seed_count}</strong> <span>seeds</span></div>
        <div class="sample-projection-label sample-projection-neighbors" data-testid="sample-count-neighbor" aria-label="{mechanism_neighbor_count} Seed Neighbor Cohort"><strong>{mechanism_neighbor_count}</strong> <span>Seed Neighbor Cohort</span></div>
        <div class="sample-projection-label sample-projection-ordinary" data-testid="sample-count-ordinary" aria-label="{mechanism_ordinary_count} ordinary users"><strong>{mechanism_ordinary_count}</strong> <span>ordinary users</span></div>
        <button class="sample-hotspot sample-hotspot-seed" type="button" data-mechanism-key="seed" data-testid="sample-hotspot-seed" aria-label="查看影响力种子机制详情" aria-expanded="false" aria-controls="evidence-drawer" title="影响力种子"></button>
        <button class="sample-hotspot sample-hotspot-neighbor" type="button" data-mechanism-key="neighbor" data-testid="sample-hotspot-neighbor" aria-label="查看历史直接邻居机制详情" aria-expanded="false" aria-controls="evidence-drawer" title="历史直接邻居"></button>
        <button class="sample-hotspot sample-hotspot-ordinary" type="button" data-mechanism-key="ordinary" data-testid="sample-hotspot-ordinary" aria-label="查看普通补足用户机制详情" aria-expanded="false" aria-controls="evidence-drawer" title="普通补足用户"></button>
        <p class="sample-opening-boundary">{escape(mechanism_boundary)}</p>
      </figure>
    </section>

    <section id="exposure-ranking" class="mechanism-stage mechanism-scene batch-zero-mechanism" data-section-anchor="exposure-ranking" data-testid="mechanism-batch-zero-section">
      <div class="mechanism-scene-header">
        <div class="mechanism-copy">
          <span class="eyebrow">BATCH 0</span>
          <h2>种子直接曝光，不参加普通排名</h2>
        </div>
        <div class="mechanism-copy">
          <p>Full-Pool Influence Seed Union 是预先选择的研究起点。平台把 Target Marketing Video 直接曝光给这些 seeds，不等待 Global Reranking Top20。</p>
        </div>
      </div>
      <figure class="mechanism-scene-visual batch-zero-visual" data-testid="batch-zero-scene-visual">
        <img data-testid="batch-zero-seeds-illustration" src="{batch_zero_seeds_image}" width="1672" height="941" alt="预先选定的影响力种子沿直接路径获得目标营销视频曝光，普通候选等待后续排序的无文字示意图">
        <div class="scene-object-label batch-zero-label-video" data-testid="batch-zero-video-label"><strong>Target Marketing Video</strong><span>直接曝光对象</span></div>
        <button class="mechanism-hotspot batch-zero-hotspot-seeds" type="button" data-mechanism-key="batch-seeds" data-testid="batch-zero-hotspot-seeds" aria-label="查看 Batch 0 seeds 机制详情" aria-expanded="false" aria-controls="evidence-drawer"><strong>Full-Pool Influence Seed Union</strong><span>预先选择并直接曝光</span></button>
        <p class="scene-status batch-zero-status"><strong>不是普通 Top20 胜出者</strong><br>not Global Reranking Top20 winners。其余 eligible users 从 Batch 1 开始参与排序。</p>
      </figure>
    </section>

    <section class="mechanism-stage mechanism-scene global-reranking-mechanism" data-testid="mechanism-global-reranking-section">
      <div class="mechanism-scene-header">
        <div class="mechanism-copy">
          <span class="eyebrow">GLOBAL RERANKING</span>
          <h2>三路信号形成相对排序</h2>
        </div>
        <div class="mechanism-copy">
          <p>后续 Batch 对全部尚未处理的 eligible users 重新计算分数。{base_network_weight:.0f}%、{engaged_neighbor_weight:.0f}%、{tag_affinity_weight:.0f}% 是预声明研究假设，不是抖音平台学习参数或已观测效果。</p>
        </div>
      </div>
      <figure class="mechanism-scene-visual reranking-visual" data-testid="global-reranking-scene-visual">
        <img data-testid="global-reranking-illustration" src="{global_reranking_image}" width="1672" height="941" alt="三路平台信号汇入同一全局排序并在投放容量内选出目标视频曝光用户的无文字示意图">
        <button class="mechanism-hotspot reranking-hotspot-network" type="button" data-mechanism-key="ranking-network" data-testid="reranking-hotspot-network" aria-label="查看 {base_network_weight:.0f}% 历史评论网络位置信号详情" aria-expanded="false" aria-controls="evidence-drawer"><strong>{base_network_weight:.0f}% 历史评论网络位置</strong><span>base_network_relevance</span></button>
        <button class="mechanism-hotspot reranking-hotspot-neighbor" type="button" data-mechanism-key="ranking-neighbor" data-testid="reranking-hotspot-neighbor" aria-label="查看 {engaged_neighbor_weight:.0f}% 已互动直接邻居信号详情" aria-expanded="false" aria-controls="evidence-drawer"><strong>{engaged_neighbor_weight:.0f}% 已互动直接邻居</strong><span>engaged_neighbor_signal</span></button>
        <button class="mechanism-hotspot reranking-hotspot-affinity" type="button" data-mechanism-key="ranking-affinity" data-testid="reranking-hotspot-affinity" aria-label="查看 {tag_affinity_weight:.0f}% 历史标签亲和度信号详情" aria-expanded="false" aria-controls="evidence-drawer"><strong>{tag_affinity_weight:.0f}% 历史标签亲和度</strong><span>historical_tag_affinity</span></button>
        <button class="mechanism-hotspot reranking-hotspot-top20" type="button" data-mechanism-key="ranking-top20" data-testid="reranking-hotspot-top20" aria-label="查看 Global Reranking Top20 结果详情" aria-expanded="false" aria-controls="evidence-drawer"><strong>Global Reranking Top20</strong><span>相对排序结果</span></button>
        <p class="scene-status reranking-status"><strong>Recommendation Signal Inclusion</strong><br>不等于 Observed Recommendation Signal Effect。</p>
      </figure>
    </section>

    <section id="llm-decision" class="mechanism-stage mechanism-scene platform-llm-mechanism" tabindex="-1" data-section-anchor="llm-decision" data-testid="mechanism-platform-llm-section">
      <div class="mechanism-scene-header">
        <div class="mechanism-copy">
          <span class="eyebrow">PLATFORM ENVIRONMENT / DECISION ADAPTER</span>
          <h2>平台先决定谁获得 Recommendation Opportunity</h2>
        </div>
        <div class="mechanism-copy">
          <p>LLM 不负责曝光调度。Decision Adapter 只为已曝光用户输出结构化 Decision：<code>like / comment / share / ignore</code>。</p>
        </div>
      </div>
      <figure class="mechanism-scene-visual platform-llm-visual" data-testid="platform-llm-scene-visual">
        <img data-testid="platform-llm-boundary-illustration" src="{platform_llm_boundary_image}" width="1672" height="941" alt="平台先选择一位曝光用户，再由独立决策适配器输出点赞、评论、分享或忽略动作的无文字示意图">
        <div class="platform-llm-label platform-zone-label"><strong>Platform Environment</strong><span>选择 Recommendation Opportunity</span></div>
        <div class="platform-llm-label adapter-zone-label"><strong>Decision Adapter</strong><span>只处理已曝光用户</span></div>
        <button class="platform-llm-hotspot platform-gate-hotspot" type="button" data-mechanism-key="platform-gate" data-testid="platform-gate-hotspot" aria-label="查看 Platform Environment gate 职责详情" aria-expanded="false" aria-controls="evidence-drawer" title="Platform Environment gate"></button>
        <button class="platform-llm-hotspot decision-adapter-hotspot" type="button" data-mechanism-key="decision-adapter" data-testid="decision-adapter-hotspot" aria-label="查看 Decision Adapter 职责详情" aria-expanded="false" aria-controls="evidence-drawer" title="Decision Adapter"></button>
        <button class="platform-llm-hotspot platform-llm-action decision-like-hotspot" type="button" data-mechanism-key="decision-like" data-testid="decision-like-hotspot" aria-label="查看 like action 结构化 Decision 详情" aria-expanded="false" aria-controls="evidence-drawer" title="like"></button>
        <button class="platform-llm-hotspot platform-llm-action decision-comment-hotspot" type="button" data-mechanism-key="decision-comment" data-testid="decision-comment-hotspot" aria-label="查看 comment action 结构化 Decision 详情" aria-expanded="false" aria-controls="evidence-drawer" title="comment"></button>
        <button class="platform-llm-hotspot platform-llm-action decision-share-hotspot" type="button" data-mechanism-key="decision-share" data-testid="decision-share-hotspot" aria-label="查看 share action 结构化 Decision 详情" aria-expanded="false" aria-controls="evidence-drawer" title="share"></button>
        <button class="platform-llm-hotspot platform-llm-action decision-ignore-hotspot" type="button" data-mechanism-key="decision-ignore" data-testid="decision-ignore-hotspot" aria-label="查看 ignore action 结构化 Decision 详情" aria-expanded="false" aria-controls="evidence-drawer" title="ignore"></button>
        <p class="scene-status platform-llm-status"><strong>Prompt contract</strong><br>ranking、network evidence、Target Holdout 与 raw Provider Payload 不进入 Final Research LLM Prompt。</p>
      </figure>
    </section>

    <section id="network-feedback" class="mechanism-stage mechanism-scene network-feedback-mechanism" tabindex="-1" data-section-anchor="network-feedback" data-testid="mechanism-network-feedback-section">
      <div class="mechanism-scene-header">
        <div class="mechanism-copy">
          <span class="eyebrow">DYNAMIC NETWORK RANKING SIGNAL</span>
          <h2>成功互动只激活一跳直接邻居</h2>
        </div>
        <div class="mechanism-copy">
          <p><code>like / comment / share</code> 激活 Comment-Derived User Interaction Graph 中相连用户的排序信号，只进入下一轮 Global Reranking。<code>ignore</code> 在当前用户处停止。</p>
          <p class="feedback-reader-boundary">这是平台排序信号，不表示用户真实看见了邻居互动。</p>
        </div>
      </div>
      <figure class="mechanism-scene-visual neighbor-feedback-visual" data-testid="neighbor-feedback-scene-visual">
        <img data-testid="neighbor-feedback-illustration" src="{neighbor_feedback_image}" width="1672" height="941" alt="点赞评论分享分别激活一跳直接邻居并进入下一轮排序，忽略动作停止传播的无文字示意图">
        <button class="feedback-hotspot feedback-action feedback-like-hotspot" type="button" data-mechanism-key="feedback-like" data-testid="feedback-like-hotspot" aria-label="查看 like 激活直接邻居详情" aria-expanded="false" aria-controls="evidence-drawer"><strong>like</strong><span>激活</span></button>
        <button class="feedback-hotspot feedback-action feedback-comment-hotspot" type="button" data-mechanism-key="feedback-comment" data-testid="feedback-comment-hotspot" aria-label="查看 comment 激活直接邻居详情" aria-expanded="false" aria-controls="evidence-drawer"><strong>comment</strong><span>激活</span></button>
        <button class="feedback-hotspot feedback-action feedback-share-hotspot" type="button" data-mechanism-key="feedback-share" data-testid="feedback-share-hotspot" aria-label="查看 share 激活直接邻居详情" aria-expanded="false" aria-controls="evidence-drawer"><strong>share</strong><span>激活</span></button>
        <button class="feedback-hotspot feedback-ignore-hotspot" type="button" data-mechanism-key="feedback-ignore" data-testid="feedback-ignore-hotspot" aria-label="查看 ignore 停止传播详情" aria-expanded="false" aria-controls="evidence-drawer"><strong>ignore</strong><span>停止传播</span></button>
        <button class="feedback-hotspot feedback-neighbors-hotspot" type="button" data-mechanism-key="feedback-neighbors" data-testid="feedback-neighbors-hotspot" aria-label="查看一跳直接邻居详情" aria-expanded="false" aria-controls="evidence-drawer"><strong>一跳直接邻居</strong><span>只激活相连用户</span></button>
        <button class="feedback-hotspot feedback-next-round-hotspot" type="button" data-mechanism-key="feedback-next-round" data-testid="feedback-next-round-hotspot" aria-label="查看下一轮 Global Reranking 详情" aria-expanded="false" aria-controls="evidence-drawer"><strong>下一轮 Global Reranking</strong><span>重新计算相对排序</span></button>
        <p class="scene-status feedback-status"><strong>排序反馈边界</strong><br>单次 action 只传播一跳，后续成功互动才可能形成新的反馈。</p>
      </figure>
    </section>
    <details class="mechanism-network-impact" data-testid="mechanism-network-impact-details">
      <summary>展开容量与网络影响</summary>
      <section class="mechanism-stage mechanism-scene capacity-comparison-mechanism" data-testid="mechanism-capacity-comparison-section">
        <div class="mechanism-scene-header">
          <div class="mechanism-copy">
            <span class="eyebrow">DELIVERY CAPACITY / PAIRED RANKING</span>
            <h2>{mechanism_exposure_limit:,} 人容量内并列比较两种排序</h2>
          </div>
          <div class="mechanism-copy">
            <p>{mechanism_sample_count:,} 人 Research Sample 中，{payload.run.horizon} 个 Batch 与 Top{payload.run.delivery_capacity} 容量使 {mechanism_exposure_limit:,} 人最多获得 Recommendation Opportunity；{mechanism_below_capacity:,} 人保持 <code>below_delivery_capacity</code>：未曝光，不是 <code>ignore</code>。</p>
            <p class="capacity-reader-boundary">Paired Network Ranking Ablation 使用同批冻结 candidate evidence，零额外 Decision Adapter calls，不推进第二条 trajectory，也不预设网络一定改变 Top20。</p>
          </div>
        </div>
        <figure class="mechanism-scene-visual capacity-network-visual" data-testid="capacity-network-scene-visual">
          <img data-testid="capacity-network-impact-illustration" src="{capacity_network_impact_image}" width="1672" height="941" alt="一千人研究样本在六百人最大投放容量边界内，使用同批候选证据并列比较完整排序与无网络排序的无文字示意图">
          <button class="mechanism-hotspot capacity-hotspot capacity-limit-hotspot" type="button" data-mechanism-key="capacity-limit" data-testid="capacity-limit-hotspot" aria-label="查看 Delivery Capacity 上限详情" aria-expanded="false" aria-controls="evidence-drawer"><strong>{mechanism_exposure_limit:,} max Delivery Capacity</strong><span>{payload.run.horizon} Batch × Top{payload.run.delivery_capacity}</span></button>
          <button class="mechanism-hotspot capacity-hotspot below-capacity-hotspot" type="button" data-mechanism-key="below-capacity" data-testid="below-capacity-hotspot" aria-label="查看 below delivery capacity 详情" aria-expanded="false" aria-controls="evidence-drawer"><strong>{mechanism_below_capacity:,} below_delivery_capacity</strong><span>未曝光，不是 ignore</span></button>
          <button class="mechanism-hotspot capacity-hotspot frozen-evidence-hotspot" type="button" data-mechanism-key="frozen-evidence" data-testid="frozen-evidence-hotspot" aria-label="查看同批冻结 candidate evidence 详情" aria-expanded="false" aria-controls="evidence-drawer"><strong>同批冻结 evidence</strong><span>只做 paired ranking</span></button>
          <button class="mechanism-hotspot capacity-hotspot full-ranking-hotspot" type="button" data-mechanism-key="full-ranking" data-testid="full-ranking-hotspot" aria-label="查看 full ranking 详情" aria-expanded="false" aria-controls="evidence-drawer"><strong>full ranking</strong><span>保留网络信号</span></button>
          <button class="mechanism-hotspot capacity-hotspot no-network-ranking-hotspot" type="button" data-mechanism-key="no-network-ranking" data-testid="no-network-ranking-hotspot" aria-label="查看 no-network ranking 详情" aria-expanded="false" aria-controls="evidence-drawer"><strong>no-network ranking</strong><span>移除网络贡献</span></button>
          <p class="scene-status capacity-status"><strong>{mechanism_sample_count:,} 人 Seed-First Sample</strong><br>容量决定谁获得曝光，不决定已曝光用户的 action。</p>
        </figure>
      </section>
    </details>
  </div>

  <div id="run-evidence-mode-panel" role="tabpanel" aria-labelledby="run-evidence-mode-tab" data-report-mode-panel="run-evidence" data-testid="run-evidence-mode-panel" hidden>
  <header id="top" class="run-evidence-intro" data-testid="ranking-hero" data-section-anchor="overview">
    <div class="run-evidence-heading">
      <div>
        <span class="run-method-status" data-testid="run-evidence-method-status">{escape(run_method_status)}</span>
        <h1>{escape(run_evidence_title)}</h1>
        <p>{escape(target.caption)}</p>
      </div>
      <a class="target-link" data-testid="target-video-link" href="{target_url}">查看 Target Marketing Video（目标营销视频）</a>
    </div>
    <div class="run-evidence-facts" aria-label="本次运行口径">
      <article><strong>{payload.run.sample_size:,}</strong><span>Research Sample（研究样本）</span></article>
      <article><strong data-testid="run-evidence-seed-count">{sample_role_counts["seed"]:,}</strong><span>seed users（种子用户）</span></article>
      <article><strong data-testid="run-evidence-network-cohort-count">{sample_role_counts["network_cohort"]:,}</strong><span>Network Cohort（网络传播识别组）</span></article>
      <article><strong data-testid="run-evidence-ordinary-count">{sample_role_counts["ordinary"]:,}</strong><span>ordinary users（普通用户）</span></article>
      <article><strong>{payload.run.horizon}</strong><span>Batches（批次）</span></article>
      <article><strong>Top{payload.run.delivery_capacity}</strong><span>Delivery Capacity（投放容量）</span></article>
    </div>
    <p class="run-evidence-boundary">{escape(run_evidence_boundary)}</p>
  </header>

  <section class="batch-control" aria-label="共享 Batch 时间轴">
    <div class="batch-control-copy"><span>Run Evidence Batch</span><strong id="batch-mechanism-label" data-testid="batch-mechanism-label"></strong></div>
    <div id="shared-batch-timeline" class="batch-timeline" data-testid="shared-batch-timeline" role="group" aria-label="选择一个 Batch 同步更新排序与决策证据"></div>
  </section>

  <section class="object-band" data-testid="core-objects-section"><span class="eyebrow">CORE OBJECTS（核心对象）</span><div class="object-flow"><article><strong>TargetVideo（目标视频）</strong><span>唯一目标内容</span></article><i aria-hidden="true">→</i><article><strong>PlatformRecommendationModel（平台推荐模型）</strong><span>逐批全局重排</span></article><i aria-hidden="true">→</i><article><strong>ResearchUser（研究用户）</strong><span>曝光后结构化决策</span></article></div></section>

  <section id="run-sample" class="content-band" data-testid="sample-comparison-section" data-section-anchor="sample">
    <div class="section-heading"><div><span class="eyebrow">SAMPLE（样本）</span><h2>{escape(sample_heading)}</h2></div><p id="sample-summary"></p></div>
    {_render_section_explanation(section_explanations["sample"], "sample-section-explanation")}
    <div id="sample-metrics" class="sample-metrics"></div>
    <div class="table-wrap sample-role-table"><table data-testid="sample-role-table"><thead><tr><th>角色</th><th>人数</th><th>怎么形成</th><th>研究角色</th><th>是否进入最终样本</th></tr></thead><tbody id="sample-role-table-body"></tbody></table></div>
    <div class="scope-intro"><h3>Video Source Scope（视频来源分组）</h3><p>这里表示采集来源分组，不是视频语义类别。下表用本次实际前后差值说明网络补样如何改变构成。</p></div>
    <div class="split-grid"><div class="table-wrap"><table data-testid="sample-scope-table"><thead><tr><th>Source Scope（来源分组）</th><th>Base Sample（基础样本）</th><th>Final Sample（最终样本）</th><th>变化</th></tr></thead><tbody id="scope-table-body"></tbody></table></div><article class="chart-panel"><h3>最终样本角色构成</h3><div id="sample-composition-explanation" class="chart-explanation" data-testid="sample-composition-explanation"></div><div id="sample-composition-chart" class="bar-chart" data-testid="sample-composition-chart"></div></article></div>

  <div id="lineage" class="evidence-subsection" data-testid="field-lineage-section">
    <div class="section-heading"><div><span class="eyebrow">FIELD LINEAGE（字段血缘）</span><h2>Field Dictionary（字段词典）</h2><p class="muted">默认表格用于快速扫描；选择字段后查看含义、形成方式、范围、用途和研究限制。</p></div><div class="compact-filters"><label>字段搜索<input id="lineage-search" data-testid="lineage-search" type="search"></label><label>用途<select id="lineage-stage-filter" data-testid="lineage-stage-filter"><option value="">全部</option></select></label></div></div>
    {_render_section_explanation(section_explanations["lineage"], "lineage-section-explanation")}
    <div class="lineage-legends">
      <section><h3>Field Provenance（字段来源）</h3><dl id="lineage-provenance-legend"></dl></section>
      <section><h3>Field Usage Stage（字段使用阶段）</h3><dl id="lineage-usage-legend"></dl></section>
    </div>
    <div class="table-wrap lineage-table"><table data-testid="lineage-table"><thead><tr><th>Field（字段）</th><th>中文名</th><th>Meaning（简要含义）</th><th>Field Provenance（字段来源）</th><th>Field Usage Stage（字段使用阶段）</th></tr></thead><tbody id="lineage-table-body"></tbody></table></div>
  </div>
  </section>

  <section id="ranking-rounds" class="content-band" data-testid="ranking-rounds-section" data-section-anchor="exposure-ranking">
    <div class="section-heading"><div><span id="ranking-batch-eyebrow" class="eyebrow"></span><h2 id="ranking-batch-title" data-testid="ranking-batch-title"></h2><p id="ranking-batch-description"></p><p id="ranking-batch-formula" class="formula">{escape(payload.run.ranking_formula)}</p></div></div>
    <div id="reranking-evidence-contract" data-testid="reranking-evidence-contract">
    {_render_section_explanation(section_explanations["ranking"], "ranking-section-explanation")}
    <div class="ranking-term-grid" data-testid="ranking-formula-terms">
      <article><h3><code>base_network_relevance</code>（历史评论网络相关性）</h3><p>0..1；越高表示用户在 Historical Set（历史集合）评论网络中的相关性越强，按 {base_network_weight:.0f}% 权重进入排序。</p></article>
      <article><h3><code>engaged_neighbor_signal</code>（已互动直接邻居信号）</h3><p>0..1；<code>min(1, engaged_neighbor_count / 3)</code> 表示三位已互动直接邻居达到封顶。它只影响后续批次，按 {engaged_neighbor_weight:.0f}% 权重进入排序。</p></article>
      <article><h3><code>historical_tag_affinity</code>（历史标签亲和度）</h3><p>0..1；越高表示历史互动标签与目标视频标签越匹配，按 {tag_affinity_weight:.0f}% 权重进入排序。</p></article>
      <article><h3><code>recommendation_score</code>（推荐排序分数）</h3><p>0..1；三项加权贡献之和，越高越靠前，只用于同批候选排序，不是单个用户的曝光或互动概率。</p></article>
    </div>
    <div class="ranking-method-notes">
      <article><h3>Delivery Capacity（每批投放容量）{payload.run.delivery_capacity}</h3><p>Top{payload.run.delivery_capacity}（前 {payload.run.delivery_capacity} 名）表示每批最多投放 {payload.run.delivery_capacity} 人，不是用户互动概率或 action（动作）配额；曝光后的 action（动作）由 LLM Decision Adapter（大模型决策适配器）另行决定。</p></article>
      <article><h3>Batch 0（第 0 批）与 Batch 1-{final_reranking_batch}（第 1-{final_reranking_batch} 批）</h3><p>Batch 0（第 0 批）强制曝光预先选定的 seeds（种子用户）；Batch 1-{final_reranking_batch}（第 1-{final_reranking_batch} 批）每批对全部尚未处理的 eligible users（合格用户）重新计算分数并全局重排。</p></article>
    </div>
    <article id="ranking-worked-example" class="ranking-worked-example" data-testid="ranking-worked-example"></article>
    </div>
    <div class="section-heading round-heading"><div><h3 id="ranking-candidate-title"></h3><p id="ranking-candidate-description" class="muted"></p></div></div>
    <div id="round-summary" class="round-summary" data-testid="round-summary"></div><div class="table-wrap"><table data-testid="ranking-candidate-table"><thead><tr id="ranking-candidate-head-row"></tr></thead><tbody id="ranking-candidate-body"></tbody></table></div>
    <div class="evidence-subsection">
      {_render_section_explanation(section_explanations["aggregate"], "aggregate-section-explanation")}
      <div class="chart-grid distributed-chart-grid"><article class="wide"><h3>逐批投放</h3><div id="batch-delivery-explanation" class="chart-explanation" data-testid="batch-delivery-explanation"></div><div id="batch-delivery-chart" class="batch-chart" data-testid="batch-delivery-chart"></div></article></div>
    </div>
  </section>

  <section class="content-band" data-testid="prompt-contract-section" data-section-anchor="llm-decision">
    <span class="eyebrow">LLM PROMPT CONTRACT（大模型提示合同）</span><h2>Prompt Isolation（提示证据隔离）</h2>{_render_section_explanation(section_explanations["prompt"], "prompt-section-explanation")}<div class="prompt-reading-note"><p><strong>阶段一：</strong>平台排序决定谁看到视频；<strong>阶段二：</strong>LLM（大模型）决定曝光后的 action（动作）。</p><p>使用 neutral PeerContext（中性同伴上下文）是为了防止评论网络 evidence（证据）同时进入 ranking（排序）和 LLM（大模型）决策，不是数据丢失。页面只展示 allowlisted evidence（允许证据），raw Prompt（原始提示）与 provider payload（服务提供方载荷）保持不可见。</p></div><div id="batch-decision-evidence" class="batch-decision-evidence" data-testid="batch-decision-evidence"></div><div class="prompt-grid"><article><h3>Allowed（允许字段）</h3><ul id="prompt-allowed"></ul></article><article><h3>Neutral（空缺 / 中性字段）</h3><ul id="prompt-neutral"></ul></article><article><h3>Excluded（排除字段）</h3><ul id="prompt-excluded"></ul></article></div>
    <div class="chart-grid distributed-chart-grid evidence-subsection">
      <article><h3>Action（动作）与容量状态</h3><div id="action-status-explanation" class="chart-explanation" data-testid="action-status-explanation"></div><div id="action-chart" class="bar-chart" data-testid="action-chart"></div></article>
      <article><h3>Provider failure（Provider 失败）</h3><div id="provider-failure-explanation" class="chart-explanation" data-testid="provider-failure-explanation"></div><div id="provider-failure-chart" class="bar-chart" data-testid="provider-failure-chart"></div></article>
    </div>
    <div id="users" class="evidence-subsection" data-testid="ranking-users-section"><div class="section-heading"><div><span class="eyebrow">USER TRACE（用户追踪）</span><h2>完整 {payload.run.sample_size:,} 用户追踪</h2></div><strong id="visible-user-count" data-testid="visible-user-count"></strong></div>{_render_section_explanation(section_explanations["users"], "users-section-explanation")}<div class="filters"><label>搜索<input id="user-search" data-testid="user-search" type="search"></label><label>Sample role（样本角色）<select id="role-filter" data-testid="role-filter"><option value="">全部</option><option value="seed">seed（种子用户）</option><option value="network_cohort">network_cohort（网络传播识别组）</option><option value="ordinary">ordinary（普通用户）</option></select></label><label>Result（结果）<select id="result-filter" data-testid="result-filter"><option value="">全部</option></select></label><label>Source Scope（来源分组）<select id="scope-filter" data-testid="scope-filter"><option value="">全部</option></select></label><label>Seed User（种子用户）<select id="seed-filter" data-testid="seed-filter"><option value="">全部</option><option value="true">是</option><option value="false">否</option></select></label><label>Network Cohort（网络传播识别组）<select id="cohort-filter" data-testid="cohort-filter"><option value="">全部</option><option value="true">是</option><option value="false">否</option></select></label></div><div class="table-wrap users-table"><table data-testid="user-table"><thead><tr><th>User（用户）</th><th>Role / scope（角色 / 来源）</th><th>Batch / rank（批次 / 名次）</th><th>Score（分数）</th><th>Result（结果）</th><th>Reason（理由）</th></tr></thead><tbody id="user-table-body"></tbody></table></div></div>
  </section>

  <section id="run-network-feedback" class="content-band" data-testid="network-feedback-section" data-section-anchor="network-feedback">
    <span class="eyebrow">NETWORK FEEDBACK（网络反馈）</span><h2 id="network-feedback-title"></h2>
    <p class="network-feedback-boundary"><code>like / comment / share</code> 激活 Comment-Derived User Interaction Graph 中直接邻居的优先级，只影响下一轮 Global Reranking。<code>ignore</code> 不传播；每次反馈只作用于一跳直接邻居，后续互动可能跨批形成新的直接邻居反馈。这不表示用户真实看见了邻居互动。</p>
    <div id="network-feedback-summary" class="effect-grid" data-testid="network-feedback-summary"></div>
    <details class="network-impact-details" data-testid="network-impact-details">
      <summary>展开网络影响证据</summary>
      <div id="network-effect" class="network-effect-content" data-testid="network-effect-section">
    <span class="eyebrow">NETWORK EFFECT（网络影响）</span><h2>Recommendation Signal Inclusion（推荐信号已纳入）与 Observed Recommendation Signal Effect（推荐信号产生可观测影响）</h2>
    <div class="capacity-layout" data-testid="delivery-capacity-evidence">
      <article><h3>Delivery Capacity（投放容量）</h3><p>{payload.run.horizon} 批 × 每批 {payload.run.delivery_capacity} 人 = {configured_delivery_slots:,} 个配置投放槽位。Batch 0 持久化曝光 {batch_zero_exposures:,} 人，后续批次最多提供 {max(0, payload.run.horizon - 1) * payload.run.delivery_capacity:,} 个槽位，因此运行调度上限为 {runtime_delivery_slots:,} 人。样本 {payload.run.sample_size:,} 人，本次最多曝光 {effective_exposure_limit:,} 人；payload 配置上限为 {payload.run.maximum_target_exposures:,}。</p></article>
      <article><h3>未曝光与曝光后不互动</h3><p>{result_status_counts["below_delivery_capacity"]:,} 个 <code>below_delivery_capacity</code> 用户未曝光，{result_status_counts["ignore"]:,} 个 <code>ignore</code> 用户已曝光后选择不互动。这两个状态不能互换。</p></article>
    </div>
    {_render_section_explanation(section_explanations["network"], "network-section-explanation")}
    <div class="network-reading-note"><p><strong>Inclusion（纳入）</strong>只说明网络项进入公式并具有明确权重，不能单独证明投放结果改变。</p><p><strong>Observed Effect（可观测影响）</strong>要求移除网络项后，同批 Top{payload.run.delivery_capacity} membership（前 {payload.run.delivery_capacity} 名成员集合）实际发生变化。</p></div>
    <p id="network-effect-reading" class="observed-effect-reading"></p>
    <div id="network-effect-summary" class="effect-grid"></div>
    <div class="diagnostic-layout"><article id="paired-ablation" class="diagnostic-panel" data-testid="paired-ablation-section"><div class="section-heading"><div><h3>Paired ranking（配对排序） · shadow diagnostic（影子诊断）</h3><p class="muted">同批冻结 persisted candidate evidence（持久化候选证据）并运行 shadow no-network（无网络影子排序），零额外 Decision Adapter calls（决策适配器调用）；它不是第二条完整 trajectory（轨迹），也不是因果实验。</p></div></div><div id="ablation-summary" class="ablation-summary" data-testid="ablation-summary"></div><div class="table-wrap rank-delta-table"><table data-testid="ablation-rank-deltas"><thead><tr><th>User（用户）</th><th>Full rank（完整排序名次）</th><th>No-network rank（无网络排序名次）</th><th>Rank delta（名次变化）</th><th>Selection effect（入选影响）</th></tr></thead><tbody id="ablation-rank-delta-body"></tbody></table></div></article><article class="diagnostic-panel" data-testid="sensitivity-section"><h3>Ranking Weight Sensitivity（排序权重敏感性）</h3><p id="sensitivity-reading-note" class="muted"></p><div id="sensitivity-variants" class="sensitivity-variants"></div></article></div>
      </div>
    </details>
    <div class="chart-grid distributed-chart-grid evidence-subsection">
      <article><h3>动态网络激活</h3><div id="network-activation-explanation" class="chart-explanation" data-testid="network-activation-explanation"></div><div id="network-activation-chart" class="bar-chart" data-testid="network-activation-chart"></div></article>
      <article><h3>Ablation（消融）Top{payload.run.delivery_capacity} overlap（重合人数）</h3><div id="ablation-overlap-explanation" class="chart-explanation" data-testid="ablation-overlap-explanation"></div><div id="ablation-overlap-chart" class="batch-chart" data-testid="ablation-overlap-chart"></div></article>
    </div>
  </section>

  <section class="downloads-band"><span class="eyebrow">ARTIFACTS（交付物）</span><h2>同源下载</h2><div class="downloads">{download_links}</div></section>
  <section class="limitations-band"><span class="eyebrow">LIMITATIONS（研究限制）</span><ul id="limitations-list"></ul></section>
  </div>
  <aside id="evidence-drawer" class="evidence-drawer" data-testid="evidence-drawer" role="dialog" aria-labelledby="evidence-drawer-title" hidden>
    <header class="drawer-header"><div><span>Evidence detail</span><h2 id="evidence-drawer-title">证据详情</h2></div><button id="evidence-drawer-close" class="drawer-close" type="button" aria-label="关闭详情" title="关闭详情">×</button></header>
    <div id="mechanism-detail" class="drawer-detail mechanism-detail" data-testid="mechanism-detail" data-drawer-kind="mechanism" aria-live="polite" hidden></div>
    <div id="drawer-candidate-detail" class="drawer-detail" data-drawer-kind="candidate" aria-live="polite" hidden></div>
    <div id="user-detail" class="drawer-detail user-detail" data-testid="user-detail" data-drawer-kind="user" aria-live="polite" hidden></div>
    <div id="lineage-detail" class="drawer-detail lineage-detail" data-testid="lineage-detail" data-drawer-kind="field" aria-live="polite" hidden></div>
    <div id="network-detail" class="drawer-detail" data-drawer-kind="network" aria-live="polite" hidden></div>
  </aside>
</main>
<script id="final-research-ranking-payload" type="application/json">{payload_json}</script>
<script id="research-explanation-catalog" type="application/json">{explanation_json}</script>
<script>{_RANKING_REPORT_JS}</script>
</body>
</html>
"""


def _ranking_download_label(key: str) -> str:
    labels = {
        "report": "Report HTML（网页报告）",
        "payload": "Payload JSON（报告载荷）",
        "csv": "User CSV（用户表格）",
        "users_json": "User JSON（用户数据）",
        "manifest": "Manifest（交付物清单）",
        "ranking_diagnostics": "Ranking diagnostics（排序诊断）",
        "ranking_ablation_csv": "Ablation CSV（消融表格）",
        "ranking_sensitivity_csv": "Sensitivity CSV（敏感性表格）",
        "field_lineage_catalog": "Field Lineage Catalog（字段血缘目录）",
        "user_field_trace": "User Field Trace（用户字段追溯）",
        "field_source_records": "Field source records（字段来源记录）",
    }
    return labels[key]


_RANKING_REPORT_CSS = r"""
:root { color-scheme:light; --ink:#0b1f46; --muted:#58657a; --line:#d8e0eb; --paper:#f5f7fb; --green:#125ee8; --blue:#125ee8; --gold:#9b6508; --red:#a23636; --coral:#d85a48; --teal:#0f7f82; }
* { box-sizing:border-box; }
[hidden] { display:none !important; }
html { scroll-behavior:smooth; }
body { margin:0; color:var(--ink); background:#fbfcfe; font:15px/1.5 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
main { width:100%; margin:0; }
[data-section-anchor] { scroll-margin-top:76px; }
h1,h2,h3,p { margin-top:0; }
h1 { margin-bottom:10px; font-size:2.55rem; line-height:1.08; letter-spacing:0; }
h2 { margin-bottom:10px; font-size:1.55rem; letter-spacing:0; }
h3 { margin-bottom:8px; font-size:1rem; letter-spacing:0; }
a { color:var(--green); overflow-wrap:anywhere; }
button,input,select { min-height:38px; border:1px solid #bcc8d8; border-radius:4px; background:#fff; color:var(--ink); font:inherit; }
input,select { width:100%; padding:7px 9px; }
label { display:grid; gap:5px; color:var(--muted); font-size:.76rem; font-weight:700; }
.eyebrow { display:block; margin-bottom:8px; color:var(--green); font-size:.72rem; font-weight:800; text-transform:uppercase; }
.muted { color:var(--muted); }
.topbar { position:sticky; top:0; z-index:20; display:grid; grid-template-columns:112px minmax(500px,1fr) auto; gap:clamp(20px,3vw,42px); align-items:center; min-height:68px; padding:10px clamp(22px,3vw,46px); border-bottom:1px solid var(--line); background:#fbfcfe; }
.brand { min-width:0; color:var(--ink); font-size:1rem; font-weight:850; text-decoration:none; white-space:nowrap; }
.workflow-nav { height:48px; display:flex; justify-content:center; gap:clamp(18px,2.2vw,34px); min-width:0; overflow:hidden; white-space:nowrap; }
.workflow-nav a { position:relative; display:flex; align-items:center; color:var(--muted); font-size:.84rem; font-weight:760; text-decoration:none; }
.workflow-nav a::after { content:""; position:absolute; right:0; bottom:0; left:0; height:3px; background:transparent; }
.workflow-nav a:hover,.workflow-nav a:focus-visible,.workflow-nav a[aria-current="location"] { color:var(--blue); }
.workflow-nav a:focus-visible { outline:2px solid var(--blue); outline-offset:3px; }
.workflow-nav a[aria-current="location"]::after { background:var(--blue); }
.mode-switch { display:grid; grid-template-columns:repeat(2,1fr); padding:3px; border:1px solid #bcc8d8; border-radius:6px; background:var(--paper); }
.mode-switch button { min-height:30px; padding:4px 10px; border:0; border-radius:3px; background:transparent; color:var(--muted); font-size:.76rem; font-weight:800; white-space:nowrap; cursor:pointer; }
.mode-switch button[aria-selected="true"] { background:var(--blue); color:#fff; }
.mode-switch button:focus-visible { outline:2px solid var(--green); outline-offset:2px; }
.sample-opening { position:relative; min-height:calc(100dvh - 68px); overflow:hidden; border-bottom:1px solid var(--line); background:#fbfcfe; }
.sample-opening-copy { position:relative; z-index:3; width:min(640px,48%); padding:clamp(50px,6vh,68px) 0 0 clamp(32px,4.5vw,72px); }
.sample-opening-copy h1 { max-width:570px; margin-bottom:14px; font-size:3.5rem; line-height:1.06; }
.sample-opening-copy p { max-width:430px; margin-bottom:22px; color:var(--ink); font-size:1.05rem; }
.sample-method-status { color:var(--muted); font-size:.8rem; font-weight:650; }
.sample-opening-visual { position:absolute; right:0; bottom:0; left:0; height:66%; margin:0; overflow:visible; outline:none; }
.sample-opening-visual:focus-visible { outline:3px solid var(--blue); outline-offset:-5px; }
.sample-opening-visual > img { display:block; width:100%; height:100%; object-fit:cover; object-position:center bottom; }
.sample-projection-label { position:absolute; top:-48px; z-index:2; display:grid; min-width:120px; text-align:center; transform:translateX(-50%); }
.sample-projection-label::after { content:""; justify-self:center; width:1px; height:clamp(50px,10vh,88px); margin-top:8px; background:#9aabc3; }
.sample-projection-label strong { font-size:2.5rem; line-height:1; }
.sample-projection-label span { margin-top:4px; color:var(--ink); font-size:.78rem; font-weight:750; }
.sample-projection-seeds { left:31.5%; }
.sample-projection-neighbors { left:49%; }
.sample-projection-ordinary { left:68%; }
.sample-hotspot { position:absolute; z-index:4; min-height:0; padding:0; border:2px dashed transparent; border-radius:6px; background:transparent; cursor:pointer; }
.sample-hotspot::after { content:""; position:absolute; top:10px; left:50%; width:14px; height:14px; border:3px solid #fbfcfe; border-radius:50%; background:var(--blue); box-shadow:0 0 0 2px var(--blue); transform:translateX(-50%); }
.sample-hotspot:hover,.sample-hotspot:focus-visible,.sample-hotspot[aria-expanded="true"] { border-color:var(--blue); background:rgba(18,94,232,.06); outline:none; }
.sample-hotspot:active { transform:translateY(1px); }
.sample-hotspot-seed { top:35%; left:25.5%; width:12%; height:59%; }
.sample-hotspot-neighbor { top:37%; left:41.5%; width:15%; height:58%; }
.sample-hotspot-ordinary { top:24%; left:58%; width:20%; height:70%; }
.sample-opening-boundary { position:absolute; right:clamp(28px,4vw,62px); bottom:18px; z-index:2; max-width:520px; margin:0; padding:8px 0 0; border-top:1px solid var(--line); color:var(--muted); font-size:.72rem; }
.sample-opening-boundary strong { color:var(--ink); }
.mechanism-stage { min-height:640px; display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,430px),1fr)); gap:clamp(30px,5vw,72px); align-items:center; padding:clamp(48px,7vw,86px) clamp(22px,6vw,78px); border-bottom:1px solid var(--line); }
.sample-mechanism { background:#fff; }
.mechanism-scene { min-height:920px; display:grid; grid-template-columns:1fr; grid-template-rows:auto minmax(680px,1fr); gap:24px; align-items:stretch; padding:clamp(82px,6vw,96px) clamp(22px,5vw,70px) clamp(48px,5vw,70px); scroll-margin-top:64px; }
.mechanism-scene-header { display:grid; grid-template-columns:minmax(0,1.25fr) minmax(320px,.75fr); gap:clamp(28px,5vw,72px); align-items:end; }
.mechanism-scene-header .mechanism-copy h2 { margin-bottom:0; }
.mechanism-scene-header .mechanism-copy > p { margin:0; }
.mechanism-scene-visual { position:relative; min-height:680px; margin:0; overflow:hidden; border-radius:6px; background:#f2f5f9; }
.mechanism-scene-visual > img { display:block; width:100%; height:100%; min-height:680px; aspect-ratio:auto; border-radius:0; object-fit:cover; object-position:center; }
.scene-status { position:absolute; z-index:3; margin:0; padding:8px 12px; border-left:3px solid var(--blue); background:rgba(251,252,254,.94); color:var(--ink); font-size:.72rem; font-weight:750; }
.scene-object-label { position:absolute; z-index:3; min-height:52px; display:grid; align-content:center; gap:2px; padding:8px 11px; border:1px solid #9bb8e8; border-left:3px solid var(--blue); border-radius:6px; background:rgba(251,252,254,.92); color:var(--ink); }
.scene-object-label strong,.scene-object-label span { display:block; }
.scene-object-label strong { font-size:.78rem; line-height:1.2; }
.scene-object-label span { color:var(--muted); font-size:.66rem; line-height:1.2; }
.mechanism-hotspot { position:absolute; z-index:4; min-height:52px; display:grid; align-content:center; gap:2px; padding:8px 11px; border:2px solid rgba(18,94,232,.7); border-radius:6px; background:rgba(251,252,254,.92); color:var(--ink); text-align:left; cursor:pointer; box-shadow:0 8px 24px rgba(23,32,27,.1); }
.mechanism-hotspot strong,.mechanism-hotspot span { display:block; }
.mechanism-hotspot strong { font-size:.78rem; line-height:1.2; }
.mechanism-hotspot span { color:var(--muted); font-size:.66rem; line-height:1.2; }
.mechanism-hotspot:hover,.mechanism-hotspot:focus-visible,.mechanism-hotspot[aria-expanded="true"] { border-color:var(--blue); background:#fff; outline:3px solid rgba(18,94,232,.22); outline-offset:2px; transform:translateY(-2px); }
.mechanism-hotspot:active { transform:translateY(1px); }
.batch-zero-mechanism { background:#f7f8fa; }
.batch-zero-visual > img { object-position:center center; }
.batch-zero-label-video { top:5%; left:5%; width:22%; }
.batch-zero-hotspot-seeds { top:34%; left:39%; width:25%; }
.batch-zero-status { right:3%; bottom:6%; max-width:25%; }
.global-reranking-mechanism { background:#f3f7fd; }
.reranking-hotspot-network { top:4%; left:32%; width:20%; }
.reranking-hotspot-neighbor { top:37%; left:52%; width:20%; }
.reranking-hotspot-affinity { top:84%; left:31%; width:20%; }
.reranking-hotspot-top20 { top:28%; left:61%; width:18%; }
.reranking-status { right:2%; bottom:5%; max-width:22%; border-left-color:var(--gold); }
.platform-llm-mechanism { grid-template-rows:auto minmax(740px,1fr); background:#f7f8fa; }
.platform-llm-mechanism .mechanism-copy h2 { max-width:780px; font-size:2.65rem; }
.platform-llm-visual { min-height:740px; }
.platform-llm-visual > img { min-height:740px; object-position:center center; }
.platform-llm-label { position:absolute; z-index:3; min-height:52px; display:grid; align-content:center; gap:2px; padding:8px 11px; border-left:3px solid var(--blue); background:rgba(251,252,254,.94); color:var(--ink); }
.platform-llm-label strong,.platform-llm-label span { display:block; }
.platform-llm-label strong { font-size:.8rem; line-height:1.2; }
.platform-llm-label span { color:var(--muted); font-size:.68rem; line-height:1.2; }
.platform-zone-label { top:4%; left:3%; width:25%; }
.adapter-zone-label { top:4%; left:55%; width:23%; }
.platform-llm-hotspot { position:absolute; z-index:4; min-width:44px; min-height:44px; padding:0; border:2px dashed rgba(18,94,232,.72); border-radius:6px; background:rgba(18,94,232,.035); cursor:pointer; }
.platform-llm-hotspot:hover,.platform-llm-hotspot:focus-visible,.platform-llm-hotspot[aria-expanded="true"] { border-style:solid; border-color:var(--blue); background:rgba(18,94,232,.1); outline:3px solid rgba(18,94,232,.22); outline-offset:2px; transform:translateY(-2px); }
.platform-llm-hotspot:active { transform:translateY(1px); }
.platform-gate-hotspot { top:18%; left:27%; width:17%; height:48%; }
.decision-adapter-hotspot { top:31%; left:60%; width:17%; height:42%; }
.decision-like-hotspot { top:18%; left:88%; width:10%; height:18%; }
.decision-comment-hotspot { top:40%; left:88%; width:10%; height:19%; }
.decision-share-hotspot { top:60%; left:85%; width:10%; height:17%; }
.decision-ignore-hotspot { top:80%; left:84%; width:11%; height:17%; }
.platform-llm-status { top:16%; left:48%; max-width:28%; border-left-color:var(--gold); }
.mechanism-copy h2 { max-width:620px; margin-bottom:16px; font-size:clamp(2rem,3.5vw,3.3rem); line-height:1.08; }
.mechanism-copy > p { max-width:640px; color:var(--muted); font-size:1rem; }
.evidence-boundary { margin:22px 0; padding:15px 0 15px 18px; border-left:4px solid var(--gold); }
.evidence-boundary strong { color:var(--ink); }
.projection-counts { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); margin-top:26px; border-block:1px solid var(--line); }
.projection-counts div { min-width:0; padding:16px 12px 16px 0; }
.projection-counts div + div { padding-left:16px; border-left:1px solid var(--line); }
.projection-counts strong,.projection-counts span { display:block; }
.projection-counts strong { font-size:2rem; }
.projection-counts span { color:var(--muted); font-size:.76rem; overflow-wrap:anywhere; }
.network-feedback-mechanism { min-height:1100px; grid-template-rows:auto minmax(820px,1fr) auto; background:#fbfcfe; }
.neighbor-feedback-visual { min-height:820px; background:#f4f7fb; }
.neighbor-feedback-visual > img { min-height:820px; object-position:center center; }
.feedback-reader-boundary { padding-left:14px; border-left:3px solid var(--gold); color:var(--ink) !important; font-size:.84rem !important; font-weight:720; }
.feedback-hotspot { position:absolute; z-index:4; min-height:54px; display:grid; align-content:center; gap:2px; padding:7px 10px; border:2px solid rgba(18,94,232,.7); border-radius:6px; background:rgba(251,252,254,.94); color:var(--ink); text-align:left; cursor:pointer; box-shadow:0 8px 24px rgba(23,32,27,.1); }
.feedback-hotspot strong,.feedback-hotspot span { display:block; white-space:nowrap; }
.feedback-hotspot strong { font-size:.76rem; line-height:1.15; }
.feedback-hotspot span { color:var(--muted); font-size:.65rem; line-height:1.15; }
.feedback-hotspot:hover,.feedback-hotspot:focus-visible,.feedback-hotspot[aria-expanded="true"] { border-color:var(--blue); background:#fff; outline:3px solid rgba(18,94,232,.22); outline-offset:2px; transform:translateY(-2px); }
.feedback-hotspot:active { transform:translateY(1px); }
.feedback-action { width:9%; min-width:92px; }
.feedback-like-hotspot { top:18%; left:17%; }
.feedback-comment-hotspot { top:36%; left:16%; width:10%; }
.feedback-share-hotspot { top:54%; left:15%; }
.feedback-ignore-hotspot { top:67%; left:3%; width:11%; min-width:112px; }
.feedback-neighbors-hotspot { top:30%; right:3%; width:21%; }
.feedback-next-round-hotspot { top:62%; right:3%; width:22%; }
.feedback-status { top:13%; right:3%; max-width:24%; border-left-color:var(--gold); }
.mechanism-network-impact { border-bottom:1px solid var(--line); background:#fbfcfe; }
.mechanism-network-impact > summary { padding:18px clamp(22px,5vw,70px); color:var(--green); font-weight:800; cursor:pointer; }
.mechanism-network-impact > summary:focus-visible { outline:2px solid var(--green); outline-offset:3px; }
.capacity-comparison-mechanism { min-height:1100px; grid-template-rows:auto minmax(820px,1fr); border-top:1px solid var(--line); border-bottom:0; background:#f7f9fc; }
.capacity-network-visual { min-height:820px; background:#f2f5fa; }
.capacity-network-visual > img { min-height:820px; object-position:center center; }
.capacity-reader-boundary { padding-left:14px; border-left:3px solid var(--gold); color:var(--ink) !important; font-size:.84rem !important; font-weight:720; }
.capacity-hotspot { min-width:150px; }
.capacity-limit-hotspot { top:25%; left:3%; width:19%; }
.below-capacity-hotspot { top:33%; left:3%; width:20%; }
.frozen-evidence-hotspot { top:43%; left:40%; width:17%; }
.full-ranking-hotspot { top:12%; right:2%; width:20%; }
.no-network-ranking-hotspot { right:2%; bottom:3%; width:20%; }
.capacity-status { top:13%; left:3%; max-width:24%; border-left-color:var(--gold); }
.run-evidence-intro { padding:28px clamp(18px,4vw,54px) 22px; border-bottom:1px solid var(--line); background:#fbfcfe; }
.run-evidence-heading { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:24px; align-items:end; }
.run-evidence-heading h1 { margin:5px 0 6px; font-size:2rem; }
.run-evidence-heading p { max-width:900px; margin:0; color:var(--muted); }
.run-method-status { color:var(--blue); font-size:.72rem; font-weight:800; }
.target-link { width:max-content; font-weight:750; white-space:nowrap; }
.run-evidence-facts { display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); margin-top:22px; border-block:1px solid var(--line); }
.run-evidence-facts article { min-width:0; padding:12px 14px 12px 0; }
.run-evidence-facts article + article { padding-left:14px; border-left:1px solid var(--line); }
.run-evidence-facts article:nth-child(2) { border-top:3px solid var(--coral); }
.run-evidence-facts article:nth-child(3) { border-top:3px solid var(--teal); }
.run-evidence-facts article:not(:nth-child(2)):not(:nth-child(3)) { border-top:3px solid var(--blue); }
.run-evidence-facts strong,.run-evidence-facts span { display:block; }
.run-evidence-facts strong { font-size:1.45rem; line-height:1.15; }
.run-evidence-facts span { margin-top:3px; color:var(--muted); font-size:.72rem; font-weight:720; }
.run-evidence-boundary { margin:12px 0 0; color:var(--muted); font-size:.72rem; }
.batch-control { position:sticky; top:64px; z-index:18; display:grid; grid-template-columns:190px minmax(0,1fr); gap:18px; align-items:center; padding:10px clamp(18px,4vw,54px); border-bottom:1px solid var(--line); background:rgba(255,255,255,.98); }
.batch-control-copy span,.batch-control-copy strong { display:block; }
.batch-control-copy span { color:var(--muted); font-size:.68rem; font-weight:800; text-transform:uppercase; }
.batch-control-copy strong { font-size:.82rem; }
.batch-timeline { display:grid; grid-auto-flow:column; grid-auto-columns:36px; gap:5px; overflow-x:auto; padding:2px 0 5px; scrollbar-width:thin; }
.batch-timeline button { width:36px; min-height:34px; padding:0; border-color:var(--line); border-radius:3px; color:var(--muted); font-size:.72rem; font-weight:800; cursor:pointer; }
.batch-timeline button:hover,.batch-timeline button:focus-visible { border-color:var(--green); color:var(--green); outline:none; }
.batch-timeline button[aria-current="step"] { border-color:var(--ink); background:var(--ink); color:#fff; }
.object-band,.content-band,.users-band,.downloads-band,.limitations-band { padding:30px clamp(18px,4vw,54px); border-bottom:1px solid var(--line); }
.evidence-subsection { margin-top:30px; padding-top:24px; border-top:1px solid var(--line); }
.object-band { background:#fff; }
.object-flow { display:grid; grid-template-columns:1fr auto 1.25fr auto 1fr; gap:15px; align-items:center; }
.object-flow article { min-height:88px; padding:14px; border-top:3px solid var(--blue); background:var(--paper); }
.object-flow strong,.object-flow span { display:block; }
.object-flow span { margin-top:5px; color:var(--muted); font-size:.82rem; }
.object-flow i { color:var(--gold); font-size:1.4rem; font-style:normal; }
.section-heading { display:flex; align-items:end; justify-content:space-between; gap:20px; margin-bottom:18px; }
.section-heading > p { max-width:520px; margin-bottom:0; color:var(--muted); }
.sample-metrics,.effect-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin-bottom:18px; }
.sample-metrics article,.effect-grid article { min-height:92px; padding:13px; border-left:4px solid var(--blue); background:var(--paper); }
.sample-metrics strong,.effect-grid strong { display:block; font-size:1.55rem; }
.sample-metrics span,.effect-grid span { color:var(--muted); font-size:.78rem; }
.section-explanation { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:0 22px; margin:0 0 18px; border-block:1px solid var(--line); }
.section-explanation article { padding:14px 0; }
.section-explanation article:nth-child(odd) { padding-right:22px; border-right:1px solid var(--line); }
.section-explanation article:nth-child(n+3) { border-top:1px solid var(--line); }
.section-explanation h3 { color:var(--green); }
.section-explanation p { margin-bottom:0; color:var(--muted); }
.sample-role-table { margin-bottom:18px; }
.scope-intro { display:grid; grid-template-columns:minmax(220px,.6fr) minmax(0,1.4fr); gap:18px; align-items:start; margin:22px 0 10px; }
.scope-intro p { margin-bottom:0; color:var(--muted); }
.split-grid { display:grid; grid-template-columns:minmax(0,1.4fr) minmax(280px,.8fr); gap:18px; }
.table-wrap { width:100%; overflow:auto; border:1px solid var(--line); }
table { width:100%; min-width:780px; border-collapse:collapse; }
th,td { padding:9px 11px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; overflow-wrap:anywhere; }
th { position:sticky; top:0; z-index:1; background:#edf2fa; font-size:.76rem; }
td { font-size:.82rem; }
td small { display:block; margin-top:3px; color:var(--muted); }
code { color:var(--blue); }
.chart-panel,.chart-grid article,.diagnostic-panel { min-width:0; padding:16px; border:1px solid var(--line); border-radius:6px; background:#fff; }
.bar-chart { min-height:140px; display:grid; gap:8px; align-content:center; }
.bar-row { display:grid; grid-template-columns:minmax(90px,1fr) 2fr auto; gap:8px; align-items:center; min-height:22px; }
.bar-row span { overflow-wrap:anywhere; font-size:.74rem; }
.bar-track { height:9px; background:#e5ebf4; }
.bar-fill { height:100%; background:var(--blue); }
.compact-filters { display:grid; grid-template-columns:minmax(170px,1fr) minmax(150px,.8fr); gap:10px; width:min(480px,100%); }
.lineage-legends { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:22px; margin-bottom:18px; border-block:1px solid var(--line); }
.lineage-legends section { padding:14px 0; }
.lineage-legends section + section { padding-left:22px; border-left:1px solid var(--line); }
.lineage-legends dl,.lineage-detail dl { margin:0; }
.lineage-legends dl > div { margin-bottom:8px; }
.lineage-legends dt { font-size:.76rem; font-weight:800; }
.lineage-legends dd { margin:2px 0 0; color:var(--muted); font-size:.74rem; }
.lineage-table { max-height:620px; }
.lineage-field { min-height:0; padding:0; border:0; background:transparent; color:var(--blue); font:inherit; font-weight:750; text-align:left; overflow-wrap:anywhere; cursor:pointer; }
.lineage-field:hover,.lineage-field:focus-visible,.lineage-field[aria-pressed="true"] { color:var(--green); text-decoration:underline; outline-offset:3px; }
.lineage-detail { min-height:360px; padding:16px; border:1px solid var(--line); border-top:4px solid var(--green); background:var(--paper); }
.lineage-detail h3 { overflow-wrap:anywhere; }
.lineage-detail dl > div { padding:8px 0; border-top:1px solid var(--line); }
.lineage-detail dt { color:var(--muted); font-size:.72rem; font-weight:800; }
.lineage-detail dd { margin:2px 0 0; overflow-wrap:anywhere; font-size:.8rem; }
.formula { margin:0 0 4px; color:var(--blue); font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:.82rem; overflow-wrap:anywhere; }
.ranking-term-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); border-block:1px solid var(--line); }
.ranking-term-grid article { min-width:0; padding:14px 0; }
.ranking-term-grid article:nth-child(odd) { padding-right:20px; border-right:1px solid var(--line); }
.ranking-term-grid article:nth-child(even) { padding-left:20px; }
.ranking-term-grid article:nth-child(n+3) { border-top:1px solid var(--line); }
.ranking-term-grid p,.ranking-method-notes p,.ranking-worked-example p { margin-bottom:0; color:var(--muted); }
.ranking-method-notes { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:20px; margin:18px 0; }
.ranking-method-notes article { padding-left:13px; border-left:4px solid var(--gold); }
.ranking-worked-example { margin:18px 0 24px; padding:16px; border:1px solid var(--line); border-top:4px solid var(--blue); border-radius:6px; background:var(--paper); }
.ranking-worked-example-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:9px; margin:12px 0; }
.ranking-worked-example-grid div { min-width:0; padding:10px; background:#fff; }
.ranking-worked-example-grid strong,.ranking-worked-example-grid span { display:block; overflow-wrap:anywhere; }
.ranking-worked-example-grid span { color:var(--muted); font-size:.75rem; }
.worked-total { padding-top:10px; border-top:1px solid var(--line); color:var(--ink) !important; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-weight:750; overflow-wrap:anywhere; }
.round-heading { margin-top:4px; }
.round-summary,.ablation-summary { display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:8px; margin-bottom:12px; }
.round-summary article,.ablation-summary article { padding:10px; border-top:3px solid var(--gold); background:var(--paper); }
.round-summary strong,.round-summary span,.ablation-summary strong,.ablation-summary span { display:block; }
.round-summary span,.ablation-summary span { color:var(--muted); font-size:.7rem; }
.effect-grid article:nth-child(2) { border-left-color:var(--gold); }
.network-reading-note,.prompt-reading-note { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:20px; margin:0 0 18px; padding-block:12px; border-block:1px solid var(--line); }
.network-reading-note p,.prompt-reading-note p { margin:0; color:var(--muted); }
.network-feedback-boundary { max-width:900px; color:var(--muted); }
.network-impact-details { margin-top:22px; border-top:1px solid var(--line); }
.network-impact-details > summary { padding:14px 0; color:var(--green); font-weight:800; cursor:pointer; }
.network-impact-details > summary:focus-visible { outline:2px solid var(--green); outline-offset:3px; }
.network-effect-content { padding-top:18px; }
.capacity-layout { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:18px; margin-bottom:18px; }
.capacity-layout article { padding-left:14px; border-left:4px solid var(--gold); }
.capacity-layout p,.observed-effect-reading { margin-bottom:0; color:var(--muted); }
.observed-effect-reading { margin:0 0 18px; padding:12px 14px; background:var(--paper); font-weight:750; }
.diagnostic-layout { display:grid; grid-template-columns:minmax(0,1.4fr) minmax(300px,.6fr); gap:16px; }
.rank-delta-table { max-height:310px; }
.rank-delta-table tbody tr,.interactive-evidence { cursor:pointer; }
.rank-delta-table tbody tr:hover,.rank-delta-table tbody tr:focus,.interactive-evidence:hover,.interactive-evidence:focus { background:#f3f7fd; outline:2px solid var(--blue); outline-offset:-2px; }
.sensitivity-variants { display:grid; gap:9px; }
.sensitivity-variants article { padding:12px; border-left:4px solid var(--blue); background:var(--paper); }
.sensitivity-variants strong,.sensitivity-variants span { display:block; }
.sensitivity-variants span { color:var(--muted); font-size:.75rem; }
.prompt-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }
.batch-decision-evidence { margin-bottom:18px; padding:16px; border:1px solid var(--line); border-left:4px solid var(--green); background:var(--paper); }
.batch-decision-evidence > p { margin-bottom:12px; color:var(--muted); }
.batch-decision-list { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:8px; }
.batch-decision-list article { min-width:0; padding:10px; border-top:3px solid var(--blue); background:#fff; }
.batch-decision-list strong,.batch-decision-list span { display:block; overflow-wrap:anywhere; }
.batch-decision-list span { color:var(--muted); font-size:.74rem; }
.prompt-grid article { padding:15px; border-top:3px solid var(--green); background:var(--paper); }
.prompt-grid article:nth-child(2) { border-top-color:var(--gold); }
.prompt-grid article:nth-child(3) { border-top-color:var(--red); }
.prompt-grid ul,.limitations-band ul { margin:0; padding-left:19px; }
.prompt-grid li { margin:4px 0; overflow-wrap:anywhere; font-size:.78rem; }
.prompt-field-button { width:100%; min-width:0; max-width:100%; min-height:0; padding:2px 0; border:0; background:transparent; color:var(--blue); font:inherit; font-weight:700; text-align:left; white-space:normal; overflow-wrap:anywhere; word-break:break-all; cursor:pointer; }
.prompt-field-button:hover,.prompt-field-button:focus-visible { color:var(--green); text-decoration:underline; outline-offset:3px; }
.chart-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
.chart-grid .wide { grid-column:1 / -1; }
.distributed-chart-grid { margin-top:18px; }
.chart-explanation { display:grid; gap:5px; margin-bottom:12px; padding:10px 0 10px 12px; border-left:3px solid var(--gold); }
.chart-explanation p { margin:0; color:var(--muted); font-size:.76rem; overflow-wrap:anywhere; }
.chart-explanation strong { color:var(--ink); }
.batch-chart { min-height:150px; display:flex; align-items:end; gap:4px; padding-top:16px; overflow:hidden; }
.batch-column { flex:1; min-width:4px; display:grid; align-items:end; height:125px; }
.batch-column i { display:block; min-height:2px; background:var(--green); }
.batch-column:nth-child(5n) i { background:var(--gold); }
.filters { display:grid; grid-template-columns:2fr repeat(5,1fr); gap:9px; margin-bottom:12px; }
.users-table { max-height:620px; }
.users-table tbody tr { cursor:pointer; }
.users-table tbody tr:hover,.users-table tbody tr:focus { background:#f3f7fd; outline:none; }
[data-testid="ranking-candidate-table"] tbody tr,.batch-decision-list article { cursor:pointer; }
[data-testid="ranking-candidate-table"] tbody tr:hover,[data-testid="ranking-candidate-table"] tbody tr:focus,.batch-decision-list article:hover,.batch-decision-list article:focus { background:#f3f7fd; outline:2px solid var(--blue); outline-offset:-2px; }
.profile-name,.profile-id { display:block; }
.profile-name { font-weight:800; }
.profile-id { color:var(--muted); font-size:.72rem; }
.status { display:inline-block; padding:2px 6px; border-radius:4px; background:#e9eef6; color:var(--blue); font-weight:800; }
.status.provider_failed { background:#f9e7e7; color:var(--red); }
.status.below_delivery_capacity { background:#fff0d9; color:#855007; }
.status.like,.status.comment,.status.share { background:#e1f3f1; color:#0b6f72; }
.status.ignore { background:#edf0f5; color:#526078; }
.user-detail { min-height:220px; margin-top:14px; padding:16px; border-left:4px solid var(--blue); background:var(--paper); }
.trace-groups { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:9px; }
.trace-groups article { min-height:130px; padding:12px; border:1px solid var(--line); background:#fff; }
.trace-groups dl { margin:0; }
.trace-groups div { display:grid; grid-template-columns:minmax(88px,.8fr) minmax(0,1.2fr); gap:7px; padding:3px 0; }
.trace-groups dt { color:var(--muted); font-size:.7rem; }
.trace-groups dd { margin:0; overflow-wrap:anywhere; font-size:.75rem; font-weight:700; }
.proxy-explanation-guide { margin-top:12px; padding:12px 0; border-block:1px solid #cdd9ed; }
.proxy-explanation-guide summary { color:var(--blue); font-weight:800; cursor:pointer; }
.proxy-explanation-guide > p { margin:10px 0 0; color:var(--muted); font-size:.78rem; }
.proxy-explanation-list { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:0 18px; margin-top:10px; }
.proxy-explanation-list article { min-width:0; padding:10px 0; border-top:1px solid var(--line); }
.proxy-explanation-list h4 { margin:0 0 5px; font-size:.82rem; overflow-wrap:anywhere; }
.proxy-explanation-list p { margin:3px 0 0; color:var(--muted); font-size:.74rem; overflow-wrap:anywhere; }
.proxy-explanation-list strong { color:var(--ink); }
.ranking-history { margin-top:12px; }
.ranking-history .table-wrap { max-height:300px; background:#fff; }
.evidence-drawer { position:fixed; top:64px; right:0; bottom:0; z-index:40; width:min(460px,100vw); overflow:auto; border-left:1px solid #b9c5d8; background:#fff; box-shadow:-20px 0 48px rgba(11,31,70,.16); }
.drawer-header { position:sticky; top:0; z-index:2; display:flex; align-items:center; justify-content:space-between; gap:18px; min-height:72px; padding:12px 16px; border-bottom:1px solid var(--line); background:rgba(255,255,255,.98); }
.drawer-header span { color:var(--muted); font-size:.68rem; font-weight:800; text-transform:uppercase; }
.drawer-header h2 { margin:2px 0 0; font-size:1.15rem; }
.drawer-close { width:38px; min-height:38px; padding:0; border-color:var(--line); border-radius:3px; color:var(--ink); font-size:1.45rem; line-height:1; cursor:pointer; }
.drawer-close:hover,.drawer-close:focus-visible { border-color:var(--green); color:var(--green); outline:2px solid var(--green); outline-offset:2px; }
.drawer-detail { padding:18px; }
.mechanism-detail { border-top:4px solid var(--blue); }
.mechanism-detail h3 { margin-bottom:10px; font-size:1.25rem; }
.mechanism-detail > p { color:var(--muted); }
.mechanism-detail dl { margin:20px 0 0; }
.mechanism-detail dl div { padding:13px 0; border-top:1px solid var(--line); }
.mechanism-detail dt { color:var(--muted); font-size:.7rem; font-weight:800; text-transform:uppercase; }
.mechanism-detail dd { margin:4px 0 0; font-weight:720; }
.drawer-detail.user-detail,.drawer-detail.lineage-detail { min-height:0; margin:0; border:0; border-top:4px solid var(--green); background:#fff; }
.drawer-detail .trace-groups { grid-template-columns:1fr; }
.drawer-detail .trace-groups article { min-height:0; }
.drawer-detail .ranking-history table { min-width:720px; }
.user-field-trace { margin:18px 0; padding-top:16px; border-top:1px solid var(--line); }
.user-field-trace-list { display:grid; border:1px solid var(--line); }
.user-field-trace-button { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:3px 12px; min-width:0; min-height:62px; padding:10px 12px; border:0; border-bottom:1px solid var(--line); border-radius:0; text-align:left; cursor:pointer; }
.user-field-trace-button:last-child { border-bottom:0; }
.user-field-trace-button strong,.user-field-trace-button span,.user-field-trace-button small { min-width:0; overflow-wrap:anywhere; }
.user-field-trace-button span { color:var(--ink); text-align:right; }
.user-field-trace-button small { grid-column:1 / -1; color:var(--muted); }
.user-field-trace-button:hover,.user-field-trace-button:focus-visible,.user-field-trace-button[aria-expanded="true"] { background:#edf4ff; outline:2px solid var(--green); outline-offset:-2px; }
.user-field-trace-detail { padding:14px; border:1px solid var(--line); border-top:4px solid var(--green); background:var(--paper); }
.user-field-trace-detail dl { margin:0; }
.user-field-trace-detail dl > div { padding:8px 0; border-top:1px solid var(--line); }
.user-field-trace-detail dt { color:var(--muted); font-size:.72rem; font-weight:800; }
.user-field-trace-detail dd { margin:2px 0 0; overflow-wrap:anywhere; }
.field-trace-source-link { display:inline-block; margin-top:12px; font-weight:750; }
.candidate-contributions { display:grid; gap:8px; margin:14px 0; }
.candidate-contributions article { padding:10px; border-left:4px solid var(--blue); background:var(--paper); }
.candidate-contributions strong,.candidate-contributions span { display:block; overflow-wrap:anywhere; }
.candidate-contributions span { color:var(--muted); font-size:.75rem; }
.downloads { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; }
.downloads a { min-height:42px; display:flex; align-items:center; padding:8px 10px; border:1px solid var(--line); border-radius:4px; text-decoration:none; font-weight:750; }
.limitations-band { display:grid; grid-template-columns:180px 1fr; background:#fff8ec; }
.limitations-band li { margin:5px 0; }
@media (max-width:1000px) { .mechanism-scene-header { grid-template-columns:1fr; }.sample-metrics,.effect-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }.diagnostic-layout { grid-template-columns:1fr; }.lineage-detail { min-height:0; }.filters { grid-template-columns:repeat(3,minmax(0,1fr)); }.trace-groups { grid-template-columns:repeat(2,minmax(0,1fr)); }.drawer-detail .trace-groups { grid-template-columns:1fr; } }
"""


_RANKING_REPORT_JS = r"""
const payload = JSON.parse(document.getElementById('final-research-ranking-payload').textContent);
const explanationDocument = JSON.parse(document.getElementById('research-explanation-catalog').textContent);
const explanationCatalog = new Map(explanationDocument.entries.map((entry) => [entry.field_name,entry]));
const users = payload.users;
const fieldLineageCatalog = new Map((payload.field_lineage_catalog || []).map((entry) => [entry.field_name,entry]));
const topLabel = `Top${payload.run.delivery_capacity}`;
const isSeedFirstRun = payload.run.sampling_method === 'seed_first_research_sample_v1';
const methodExposureLimit = Math.min(payload.run.sample_size,payload.run.maximum_target_exposures);
const methodBelowCapacity = Math.max(0,payload.run.sample_size - methodExposureLimit);
const sampleRoleCounts = new Map(); users.forEach((row) => sampleRoleCounts.set(row.sample_role,(sampleRoleCounts.get(row.sample_role) || 0) + 1));
const resultStatusCounts = new Map(); users.forEach((row) => resultStatusCounts.set(row.result_status,(resultStatusCounts.get(row.result_status) || 0) + 1));
const proxyFields = [
  ['activity_score','Activity（活跃度代理）'],
  ['global_influence_score','Global influence（全平台影响力代理）'],
  ['local_influence_score','Local influence（局部影响力代理）'],
  ['local_network_score','Local network（局部网络分量）'],
  ['local_recognition_score','Local recognition（局部认可分量）'],
];
const rankingHistoryByUser = new Map();
payload.ranking_rounds.forEach((round) => round.candidates.forEach((candidate) => {
  if (!rankingHistoryByUser.has(candidate.user_id)) rankingHistoryByUser.set(candidate.user_id,[]);
  rankingHistoryByUser.get(candidate.user_id).push({time_step:round.time_step,...candidate});
}));
const byId = (id) => document.getElementById(id);
const reportRoot = document.querySelector('[data-testid="final-research-ranking-report"]');
const modeButtons = [...document.querySelectorAll('[data-report-mode-target]')];
const modePanels = [...document.querySelectorAll('[data-report-mode-panel]')];
const evidenceDrawer = byId('evidence-drawer');
const interactionState = {
  mode:'mechanism',
  batch:payload.ranking_rounds[0]?.time_step || 0,
  selection:null,
  drawerOpen:false,
  returnFocusTarget:null,
};
const display = (value) => value === null || value === undefined || value === '' ? '-' : String(value);
const fixed = (value) => value === null || value === undefined ? '-' : Number(value).toFixed(4);
const provenanceLabels = Object.fromEntries(explanationDocument.provenance_categories.map((category) => [category.key,category.label]));
const usageLabels = Object.fromEntries(explanationDocument.usage_stages.map((stage) => [stage.key,stage.label]));
const actionLabels = {like:'like（点赞）',comment:'comment（评论）',share:'share（分享）',ignore:'ignore（忽略）'};
const resultStatusLabels = {...actionLabels,provider_failed:'provider_failed（Provider 失败）',below_delivery_capacity:'below_delivery_capacity（未获得投放）'};
const providerStatusLabels = {not_called:'not_called（未调用）',succeeded:'succeeded（成功）',provider_failed:'provider_failed（Provider 失败）'};
const valueStatusLabels = {present:'present（有值）',empty:'empty（空值）',unavailable:'unavailable（不可用）'};
const promptInclusionLabels = {included:'included（已进入 Prompt）',empty_omitted:'empty_omitted（空值省略）',not_allowlisted:'not_allowlisted（未列入 Prompt allowlist）',not_exposed:'not_exposed（未曝光）'};
const sampleRoleLabels = {seed:'seed（种子用户）',network_cohort:'network_cohort（网络传播识别组）',ordinary:'ordinary（普通用户）'};
const limitationTranslations = {
  'Network Cohort supports propagation identification and is not a representative random sample.':'Network Cohort（网络传播识别组）用于传播识别，不是代表性随机样本。',
  'Ranking weights are predeclared research assumptions, not learned Douyin platform parameters.':'Ranking weights（排序权重）是预声明研究假设，不是从抖音平台学习得到的参数。',
  'Paired ablation is a frozen-evidence shadow ranking, not a second user-state trajectory.':'Paired ablation（配对消融）是冻结证据上的影子排序，不是第二条用户状态轨迹。',
  'No real exposure denominator is available; below delivery capacity is not a user ignore decision.':'没有真实曝光分母；below_delivery_capacity（未获得投放）不是用户的 ignore（忽略）决策。',
};
const mechanismPromptContract = {
  allowed:`允许进入 Final Research LLM Prompt：Target Marketing Video content；allowlisted profile fields（${payload.prompt_contract.allowed_profile_fields.join(' / ')}）；neutral PeerContext。`,
  excluded:'不进入 Final Research LLM Prompt：ranking、network evidence、Target Holdout 与 raw Provider Payload。',
};
const mechanismActionDetail = (action,meaning,limitation) => ({
  title:`${action} action`,
  definition:`${meaning}。它是已曝光用户的结构化 Decision。${mechanismPromptContract.allowed} 输出字段合同为 engage / probability / reason / confidence / action。`,
  provenance:'Runtime Simulation Result（仿真运行结果）',
  usage:'Report Only（仅报告展示）',
  limitation:`${limitation} ${mechanismPromptContract.excluded}`,
});
const mechanismFeedbackDetail = (action) => ({
  title:`${action} 激活直接邻居`,
  definition:`${action} 是已曝光用户的成功互动 action。Platform Environment 只把它转换为 Comment-Derived User Interaction Graph 中一跳直接邻居的动态排序信号，并在下一轮 Global Reranking 使用。`,
  provenance:'Runtime Simulation Result（仿真运行结果） / Historical Behavioral Evidence（历史行为证据）',
  usage:'Ranking（排序） / Report Only（仅报告展示）',
  limitation:'该传播只作用于一跳直接邻居，不是用户可见同伴行为，也不证明网络信号一定改变下一轮 Top20。',
});
const mechanismDetails = {
  seed:{
    title:'Full-Pool Influence Seed Union',
    definition:'从全部合格 processed users 中取 Global Influence Proxy Top10 与 Local Influence Proxy Top10 的去重并集，作为 Seed-First Research Sample 的研究起点。',
    provenance:'Derived Proxy Metric（派生代理指标）',
    usage:'Seed Selection（种子选择） / Sampling（抽样）',
    limitation:isSeedFirstRun ? `${payload.sample_comparison.seed_count} 位来自当前 persisted sample audit；它们不是普通 Global Reranking Top20 胜出者。` : '20 位是 ADR 0003 的 offline projection。它不是旧正式 run 的结果，也不是普通 Global Reranking Top20 胜出者。',
  },
  neighbor:{
    title:'Seed Neighbor Cohort',
    definition:'Full-Pool Influence Seed Union 在 holdout-safe Comment-Derived User Interaction Graph 中的历史一跳直接邻居。',
    provenance:'Historical Behavioral Evidence（历史行为证据）',
    usage:'Sampling（抽样） / Ranking（排序）',
    limitation:isSeedFirstRun ? `${payload.sample_comparison.network_cohort_count} 位来自当前 persisted sample audit。评论、回复与 mention 派生的连接不是好友或关注关系，也不代表总体随机样本。` : '60 位是 offline projection。评论、回复与 mention 派生的连接不是好友或关注关系，也不代表总体随机样本。',
  },
  ordinary:{
    title:'普通补足用户',
    definition:`种子和直接邻居计入配额后，按 Primary Video Source Scope 使用固定随机规则补足到 ${payload.run.sample_size} 位真实合格用户。`,
    provenance:'Historical Behavioral Evidence（历史行为证据）',
    usage:'Sampling（抽样） / Report Only（仅报告展示）',
    limitation:isSeedFirstRun ? `${payload.sample_comparison.ordinary_count} 位来自当前 persisted sample audit，不是合成用户，也不表示总体代表性。` : '920 位是 offline projection，不是合成用户，也不表示总体代表性或某次 runtime 的实际用户结果。',
  },
  'batch-seeds':{
    title:'Batch 0 seeds 直接曝光',
    definition:'Full-Pool Influence Seed Union 在 runtime 开始前由 Global Influence Proxy Top10 与 Local Influence Proxy Top10 的去重并集形成，并在 Batch 0 直接获得 Target Marketing Video 曝光。',
    provenance:'Derived Proxy Metric（派生代理指标）',
    usage:'Seed Selection（种子选择） / Ranking（排序） / Report Only（仅报告展示）',
    limitation:'Batch 0 seeds 是预先选择并直接曝光的研究起点，不属于 Recommendation Signal Inclusion，也不是普通 Global Reranking Top20 胜出者或真实平台关键意见领袖。',
  },
  'ranking-network':{
    title:`${Math.round(payload.ranking_diagnostics_summary.main_weights.base_network * 100)}% 历史评论网络位置`,
    definition:'base_network_relevance 使用 Historical Set 的 Comment-Derived User Interaction Graph weighted degree 与 holdout-safe P95 reference 形成 0..1 相对信号。',
    provenance:'Derived Proxy Metric（派生代理指标）',
    usage:'Ranking（排序） / Report Only（仅报告展示）',
    limitation:`${Math.round(payload.ranking_diagnostics_summary.main_weights.base_network * 100)}% 是预声明研究假设。Recommendation Signal Inclusion 只说明信号进入公式，不等于 Observed Recommendation Signal Effect，也不是抖音平台学习参数。`,
  },
  'ranking-neighbor':{
    title:`${Math.round(payload.ranking_diagnostics_summary.main_weights.engaged_neighbor * 100)}% 已互动直接邻居`,
    definition:'engaged_neighbor_signal = min(1, engaged_neighbor_count / 3)。它把已对 Target Marketing Video 产生 like、comment 或 share 的历史一跳直接邻居计数归一化，并在下一轮排序中使用。',
    provenance:'Derived Proxy Metric（派生代理指标）',
    usage:'Ranking（排序） / Report Only（仅报告展示）',
    limitation:`${Math.round(payload.ranking_diagnostics_summary.main_weights.engaged_neighbor * 100)}% 是预声明研究假设。该信号不是用户可见同伴行为；Recommendation Signal Inclusion 不等于 Observed Recommendation Signal Effect。`,
  },
  'ranking-affinity':{
    title:`${Math.round(payload.ranking_diagnostics_summary.main_weights.tag_affinity * 100)}% 历史标签亲和度`,
    definition:'historical_tag_affinity 比较用户 Historical Set 互动标签与 Target Marketing Video 标签，形成 0..1 的内容亲和排序信号。',
    provenance:'Derived Proxy Metric（派生代理指标）',
    usage:'Ranking（排序） / Report Only（仅报告展示）',
    limitation:`${Math.round(payload.ranking_diagnostics_summary.main_weights.tag_affinity * 100)}% 是预声明研究假设，不是已观测效果或真实平台参数。Recommendation Signal Inclusion 不等于 Observed Recommendation Signal Effect，也不证明它改变了本次 Top20。`,
  },
  'ranking-top20':{
    title:'Global Reranking Top20',
    definition:'后续每个 Batch 对全部尚未处理的 eligible users 重新计算相对分数，并在 Delivery Capacity 内选择当前 Top20 获得 Recommendation Opportunity。',
    provenance:'Runtime Simulation Result（仿真运行结果）',
    usage:'Ranking（排序） / Report Only（仅报告展示）',
    limitation:'Top20 是 Recommendation Signal Inclusion 后的相对排序与容量结果，不是曝光概率或互动倾向，也不能证明某一信号产生 Observed Recommendation Signal Effect。只有成对消融的 persisted diagnostics 能判断该 effect。',
  },
  'platform-gate':{
    title:'Platform Environment gate',
    definition:`Platform Environment 先执行 Global Reranking，并在 Delivery Capacity 内选择获得 Recommendation Opportunity 的用户。LLM 不参与曝光调度。${mechanismPromptContract.allowed}`,
    provenance:'Runtime Simulation Result（仿真运行结果）',
    usage:'Ranking（排序） / Report Only（仅报告展示）',
    limitation:`平台证据只负责选择曝光用户，不能被解释为用户互动倾向。${mechanismPromptContract.excluded}`,
  },
  'decision-adapter':{
    title:'Decision Adapter',
    definition:`Decision Adapter 只处理已曝光用户。${mechanismPromptContract.allowed} 输出字段合同为 engage / probability / reason / confidence / action。`,
    provenance:'Derived Proxy Metric（派生代理指标） / Synthetic Experiment Label（合成实验标签）',
    usage:'LLM Prompt（大模型提示） / Report Only（仅报告展示）',
    limitation:`Decision 只表示已获得 Recommendation Opportunity 后的模拟互动倾向。${mechanismPromptContract.excluded}`,
  },
  'decision-like':mechanismActionDetail('like','正向轻量互动','like 不表示平台曝光调度，也不代表真实平台已观测结果；机制模式不展示某次 run 的行为计数。'),
  'decision-comment':mechanismActionDetail('comment','生成文字互动','comment 不恢复或展示 raw Provider Payload；机制模式只解释结构化 Decision 的稳定含义。'),
  'decision-share':mechanismActionDetail('share','进一步传播内容','share 是仿真 action，不等同真实平台因果传播效果；机制模式不展示某次 run 的用户级结果。'),
  'decision-ignore':mechanismActionDetail('ignore','已曝光但不互动','ignore 与 below_delivery_capacity 不同。前者已经曝光后选择不互动，后者没有进入 Delivery Capacity。'),
  'feedback-like':mechanismFeedbackDetail('like'),
  'feedback-comment':mechanismFeedbackDetail('comment'),
  'feedback-share':mechanismFeedbackDetail('share'),
  'feedback-ignore':{
    title:'ignore 停止传播',
    definition:'ignore 表示用户已经获得 Target Marketing Video 曝光，但选择不互动。它不会激活任何直接邻居，也不会形成下一轮 engaged_neighbor_signal。',
    provenance:'Runtime Simulation Result（仿真运行结果）',
    usage:'Report Only（仅报告展示）',
    limitation:'ignore 不是 below_delivery_capacity。前者已曝光后不互动，后者没有进入 Delivery Capacity。',
  },
  'feedback-neighbors':{
    title:'一跳直接邻居',
    definition:'一跳直接邻居来自 Historical Set 的 Comment-Derived User Interaction Graph。成功互动只激活与当前用户直接相连的候选。',
    provenance:'Historical Behavioral Evidence（历史行为证据）',
    usage:'Ranking（排序） / Report Only（仅报告展示）',
    limitation:'评论、回复和 mention 派生的边不是好友或关注关系，也不是用户可见同伴行为。',
  },
  'feedback-next-round':{
    title:'下一轮 Global Reranking',
    definition:'下一轮对全部尚未处理的 eligible users 重新计算相对分数，其中 engaged_neighbor_signal = min(1, engaged_neighbor_count / 3)。',
    provenance:'Derived Proxy Metric（派生代理指标） / Runtime Simulation Result（仿真运行结果）',
    usage:'Ranking（排序） / Report Only（仅报告展示）',
    limitation:'信号进入下一轮排序只表示 Recommendation Signal Inclusion，不预设或证明 Observed Recommendation Signal Effect。',
  },
  'capacity-limit':{
    title:'Delivery Capacity 上限',
    definition:`当前方法使用 ${payload.run.horizon} 个 Batch，每批 Top${payload.run.delivery_capacity}。最多 ${methodExposureLimit} 位用户获得 Target Marketing Video 的 Recommendation Opportunity。`,
    provenance:'Synthetic Experiment Label（合成实验标签）',
    usage:'Ranking（排序） / Report Only（仅报告展示）',
    limitation:`最多 ${methodExposureLimit} 是配置与样本共同约束的投放容量，不是互动人数或曝光概率。`,
  },
  'below-capacity':{
    title:'below_delivery_capacity',
    definition:`${payload.run.sample_size} 人 Research Sample 中最多 ${methodExposureLimit} 人获得 Recommendation Opportunity，其余 ${methodBelowCapacity} 人没有获得目标视频曝光。`,
    provenance:'Runtime Simulation Result（仿真运行结果）',
    usage:'Ranking（排序） / Report Only（仅报告展示）',
    limitation:'below_delivery_capacity 不是 ignore。前者未进入容量且未曝光，后者已经曝光后选择不互动。',
  },
  'frozen-evidence':{
    title:'同批冻结 candidate evidence',
    definition:'Paired Network Ranking Ablation 对同一批 eligible users 和同一份 persisted candidate evidence 计算 full 与 no-network 两种排序，不调用 Decision Adapter。',
    provenance:'Runtime Simulation Result（仿真运行结果）',
    usage:'Ranking（排序） / Report Only（仅报告展示）',
    limitation:'它不是第二条完整 trajectory，也不是因果实验；只在同批冻结证据上检查网络信号的排序差异。',
  },
  'full-ranking':{
    title:'full ranking',
    definition:'full ranking 在同批候选上保留 base_network_relevance、engaged_neighbor_signal 与 historical_tag_affinity 的预声明贡献。',
    provenance:'Derived Proxy Metric（派生代理指标） / Runtime Simulation Result（仿真运行结果）',
    usage:'Ranking（排序） / Report Only（仅报告展示）',
    limitation:'保留网络信号不预设改变 Top20。具体 effect 只能由 Run Evidence Mode 的 persisted diagnostics 判断。',
  },
  'no-network-ranking':{
    title:'no-network ranking',
    definition:'no-network ranking 对同一批候选和同一份冻结证据移除评论网络贡献，再计算相对排序。',
    provenance:'Derived Proxy Metric（派生代理指标） / Runtime Simulation Result（仿真运行结果）',
    usage:'Ranking（排序） / Report Only（仅报告展示）',
    limitation:'它与 full ranking 共用同一批候选，不额外执行 Decision Adapter，不推进第二条 trajectory，也不能解释为因果实验。',
  },
};
let selectedLineageField = payload.field_lineage[0]?.field_name || '';
const count = (value) => {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric.toLocaleString() : display(value);
};

function contextualValueLabel(value, chineseName) {
  const text = display(value);
  if (text === '-' || /[\u3400-\u9fff]/.test(text) || /（[^）]+）/.test(text)) return text;
  return `${text}（${chineseName}）`;
}

const sourceScopeLabel = (value) => contextualValueLabel(value, value === 'remaining_users' ? '其余用户' : '来源分组');

function element(tag, className, textValue) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (textValue !== undefined) node.textContent = textValue;
  return node;
}

function appendBreakableFieldLabel(node, label) {
  label.split(/([._])/).forEach((part) => {
    node.appendChild(document.createTextNode(part));
    if (part === '.' || part === '_') node.appendChild(document.createElement('wbr'));
  });
}

function setReportMode(mode) {
  if (interactionState.mode !== mode) closeDrawer({restoreFocus:false});
  interactionState.mode = mode;
  reportRoot.dataset.reportMode = mode;
  modePanels.forEach((panel) => { panel.hidden = panel.dataset.reportModePanel !== mode; });
  modeButtons.forEach((button) => button.setAttribute('aria-selected',String(button.dataset.reportModeTarget === mode)));
}

function openDrawer(kind, selection, trigger=null) {
  interactionState.selection = {kind,...selection};
  interactionState.drawerOpen = true;
  interactionState.returnFocusTarget = trigger || (document.activeElement instanceof HTMLElement && document.activeElement !== document.body ? document.activeElement : null);
  evidenceDrawer.dataset.selectionKind = kind;
  evidenceDrawer.hidden = false;
  evidenceDrawer.querySelectorAll('[data-drawer-kind]').forEach((panel) => {
    panel.hidden = panel.dataset.drawerKind !== kind;
  });
  const titles = {mechanism:'机制详情',candidate:'Ranking candidate（排序候选）',user:'Research user（研究用户）',field:'Prompt / Field Lineage（提示 / 字段血缘）',network:'Network evidence（网络证据）'};
  byId('evidence-drawer-title').textContent = titles[kind] || '证据详情';
  byId('evidence-drawer-close').focus({preventScroll:true});
}

function closeDrawer({restoreFocus=true}={}) {
  const returnFocusTarget = interactionState.returnFocusTarget;
  interactionState.selection = null;
  interactionState.drawerOpen = false;
  interactionState.returnFocusTarget = null;
  evidenceDrawer.removeAttribute('data-selection-kind');
  evidenceDrawer.hidden = true;
  document.querySelectorAll('[data-mechanism-key]').forEach((hotspot) => hotspot.setAttribute('aria-expanded','false'));
  if (restoreFocus && returnFocusTarget?.isConnected) returnFocusTarget.focus({preventScroll:true});
}

byId('evidence-drawer-close').addEventListener('click',closeDrawer);
document.addEventListener('keydown',(event) => { if (event.key === 'Escape' && interactionState.drawerOpen) closeDrawer(); });

function renderMechanismDetail(key) {
  const detail = mechanismDetails[key];
  if (!detail) return;
  const root = byId('mechanism-detail');
  root.replaceChildren();
  root.append(element('h3','',detail.title),element('p','',detail.definition));
  const facts = document.createElement('dl');
  [
    ['Field Provenance（字段来源）',detail.provenance],
    ['Field Usage Stage（字段使用阶段）',detail.usage],
    ['研究限制',detail.limitation],
  ].forEach(([term,value]) => {
    const row = document.createElement('div');
    row.append(element('dt','',term),element('dd','',value));
    facts.appendChild(row);
  });
  root.appendChild(facts);
}

document.querySelectorAll('[data-mechanism-key]').forEach((hotspot) => hotspot.addEventListener('click',() => {
  const key = hotspot.dataset.mechanismKey;
  renderMechanismDetail(key);
  document.querySelectorAll('[data-mechanism-key]').forEach((candidate) => candidate.setAttribute('aria-expanded','false'));
  hotspot.setAttribute('aria-expanded','true');
  openDrawer('mechanism',{mechanismKey:key},hotspot);
}));

function activeSectionTarget(anchor) {
  const panel = modePanels.find((candidate) => candidate.dataset.reportModePanel === reportRoot.dataset.reportMode);
  return panel?.querySelector(`[data-section-anchor="${anchor}"]`) || null;
}

function setActiveNavigation(anchor) {
  document.querySelectorAll('.workflow-nav a').forEach((link) => {
    if (link.getAttribute('href') === `#${anchor}`) link.setAttribute('aria-current','location');
    else link.removeAttribute('aria-current');
  });
}

modeButtons.forEach((button,index) => {
  button.addEventListener('click',() => setReportMode(button.dataset.reportModeTarget));
  button.addEventListener('keydown',(event) => {
    if (!['ArrowLeft','ArrowRight'].includes(event.key)) return;
    event.preventDefault();
    const offset = event.key === 'ArrowRight' ? 1 : -1;
    const next = modeButtons[(index + offset + modeButtons.length) % modeButtons.length];
    next.focus();
    setReportMode(next.dataset.reportModeTarget);
  });
});
document.querySelectorAll('.workflow-nav a').forEach((link) => link.addEventListener('click',(event) => {
  const anchor = link.getAttribute('href')?.slice(1);
  const target = anchor ? activeSectionTarget(anchor) : null;
  if (!target) return;
  event.preventDefault();
  history.replaceState(null,'',`#${anchor}`);
  target.scrollIntoView({block:'start'});
  target.setAttribute('tabindex','-1');
  target.focus({preventScroll:true});
  setActiveNavigation(anchor);
}));
function locationNavigationAnchor() {
  const anchor = window.location.hash.slice(1);
  return anchor && activeSectionTarget(anchor) ? anchor : 'overview';
}
setActiveNavigation(locationNavigationAnchor());
window.addEventListener('hashchange',() => {
  const anchor = locationNavigationAnchor();
  const target = activeSectionTarget(anchor);
  setActiveNavigation(anchor);
  if (target) {
    target.setAttribute('tabindex','-1');
    target.focus({preventScroll:true});
  }
});
const visibleNavigationSections = new Set();
const sectionObserver = new IntersectionObserver((entries) => {
  entries.forEach((entry) => {
    if (entry.isIntersecting && !entry.target.closest('[hidden]')) visibleNavigationSections.add(entry.target);
    else visibleNavigationSections.delete(entry.target);
  });
  const visibleSections = [...visibleNavigationSections];
  const locationAnchor = window.location.hash.slice(1);
  const hashSection = visibleSections.find((section) => section.dataset.sectionAnchor === locationAnchor);
  const nearestSection = visibleSections.sort((left,right) =>
    Math.abs(left.getBoundingClientRect().top - 68) - Math.abs(right.getBoundingClientRect().top - 68)
  )[0];
  const activeSection = hashSection && nearestSection &&
    Math.abs(hashSection.getBoundingClientRect().top - 68) <= Math.abs(nearestSection.getBoundingClientRect().top - 68) + 8
    ? hashSection
    : nearestSection;
  if (activeSection) setActiveNavigation(activeSection.dataset.sectionAnchor);
},{rootMargin:'-68px 0px -60% 0px',threshold:0});
document.querySelectorAll('[data-report-mode-panel] [data-section-anchor]').forEach((section) => sectionObserver.observe(section));

function fillList(id, values) {
  const root = byId(id);
  values.forEach((value) => root.appendChild(element('li', '', value)));
}

function promptFieldLabel(fieldName) {
  const explanation = explanationCatalog.get(fieldName);
  if (explanation) return `${fieldName}（${explanation.chinese_name}）`;
  const labels = {
    'peer_context.exposed_neighbors':'已曝光邻居数',
    'peer_context.engaged_neighbors':'已互动邻居数',
    'peer_context.engagement_ratio':'邻居互动比例',
    'peer_context.influential_engaged_neighbors':'高影响已互动邻居数',
    'peer_context.visible_likes':'可见点赞数',
    'peer_context.visible_comments':'可见评论数',
    'peer_context.visible_shares':'可见分享数',
    'Target Holdout answers':'目标留出答案',
  };
  return `${fieldName}（${labels[fieldName] || '报告字段'}）`;
}

function metric(label, value, note) {
  const article = element('article');
  article.append(element('strong', '', count(value)), element('span', '', label), element('p', 'muted', note));
  return article;
}

function renderSample() {
  const sample = payload.sample_comparison;
  const ordinaryCount = sampleRoleCounts.get('ordinary') || 0;
  const seedFirst = payload.run.sampling_method === 'seed_first_research_sample_v1';
  byId('sample-summary').textContent = seedFirst
    ? `Seed Users（种子用户） ${sample.seed_count} · Seed Neighbor Cohort（直接邻居） ${sample.network_cohort_count} · Ordinary Users（普通用户） ${ordinaryCount}`
    : `Seed Users（种子用户） ${sample.seed_count} · Network Cohort（网络传播识别组） ${sample.network_cohort_count} · 普通用户替换 ${sample.replacement_count}`;
  const metrics = seedFirst ? [
    ['Full-Pool Seeds（全量池种子）',sample.seed_count,'在形成 Research Sample 前选择'],
    ['Seed Neighbor Cohort（种子邻居）',sample.network_cohort_count,'Historical Set 一跳直接邻居'],
    ['Ordinary Users（普通用户）',ordinaryCount,'按 Primary Video Source Scope 配额补足'],
    ['Final Sample（最终样本）',sample.final_sample_count,'本次 Validation Run 样本'],
  ] : [
    ['Base Sample（基础样本）',sample.base_sample_count,'network augmentation（网络补样）前'],
    ['Final Sample（最终样本）',sample.final_sample_count,'正式 runtime（仿真运行）样本'],
    ['Network Cohort（网络传播识别组）',sample.network_cohort_count,`${sample.network_cohort_added_count} 位新增网络用户`],
    ['普通用户替换',sample.replacement_count,'保持最终样本总量不变'],
  ];
  metrics.forEach(([label,value,note]) => byId('sample-metrics').appendChild(metric(label,value,note)));
  const roles = [
    ['Seed Users（种子用户）',sampleRoleCounts.get('seed') || 0,seedFirst ? '从全部合格 processed users 形成 Full-Pool Influence Seed Union' : '从 Base Sample（基础样本）按预声明 seed union（种子并集）固定','Batch 0（第 0 批）固定曝光；后续互动可激活邻居信号','是'],
    ['Network Cohort（网络传播识别组）',sampleRoleCounts.get('network_cohort') || 0,'Seed Users（种子用户）在 Historical Set（历史集合）评论网络中的直接邻居','传播识别组；参与后续全局 ranking（排序）','是'],
    ['Ordinary Users（普通用户）',ordinaryCount,'Final Sample（最终样本）中非种子、非网络传播识别组用户','保持来源样本与对照覆盖；参与后续全局 ranking（排序）','是'],
  ];
  roles.forEach((values) => { const row = element('tr'); values.forEach((value) => row.appendChild(element('td','',display(value)))); byId('sample-role-table-body').appendChild(row); });
  const scopes = [...new Set([...Object.keys(sample.base_source_scope_counts),...Object.keys(sample.final_source_scope_counts)])].sort();
  scopes.forEach((scope) => {
    const row = element('tr');
    const baseCount = sample.base_source_scope_counts[scope] || 0;
    const finalCount = sample.final_source_scope_counts[scope] || 0;
    const delta = finalCount - baseCount;
    [sourceScopeLabel(scope),baseCount,finalCount,`${delta > 0 ? '+' : ''}${delta}`].forEach((value) => row.appendChild(element('td','',display(value))));
    byId('scope-table-body').appendChild(row);
  });
  renderBars('sample-composition-chart', [
    {label:'Seed Users（种子用户）',value:sample.seed_count},
    {label:'Network Cohort（网络传播识别组）',value:sample.network_cohort_count},
    {label:'Ordinary Users（普通用户）',value:ordinaryCount},
  ]);
}

function renderLineageDetail(fieldName, shouldOpen = true) {
  const explanation = explanationCatalog.get(fieldName);
  if (!explanation) return;
  selectedLineageField = fieldName;
  document.querySelectorAll('.lineage-field').forEach((button) => button.setAttribute('aria-pressed',String(button.dataset.fieldName === fieldName)));
  const root = byId('lineage-detail'); root.replaceChildren();
  root.appendChild(element('h3','',`${explanation.field_name}（${explanation.chinese_name}）`));
  const list = element('dl');
  const lineage = payload.field_lineage.find((entry) => entry.field_name === fieldName);
  [
    ['含义',explanation.meaning],
    ['Field Provenance（字段来源）',lineage ? provenanceLabels[lineage.provenance] : explanation.source],
    ['Field Usage Stage（字段使用阶段）',lineage ? lineage.usage_stages.map((value) => usageLabels[value]).join(' · ') : explanation.usage],
    ['来源',explanation.source],
    ['计算 / 形成方式',explanation.calculation],
    ['范围',explanation.value_range],
    ['用途',explanation.usage],
    ['高低值解读',explanation.interpretation],
    ['限制',explanation.limitation],
  ].forEach(([label,value]) => { const line = element('div'); line.append(element('dt','',label),element('dd','',value)); list.appendChild(line); });
  root.appendChild(list);
  if (shouldOpen) openDrawer('field',{fieldName});
}

function renderPromptFieldDetail(fieldName, category) {
  if (explanationCatalog.has(fieldName)) {
    renderLineageDetail(fieldName);
    return;
  }
  const root = byId('lineage-detail'); root.replaceChildren();
  root.appendChild(element('h3','',promptFieldLabel(fieldName)));
  const list = element('dl');
  const usage = category === 'allowed' ? 'LLM Prompt' : category === 'neutral' ? 'LLM Prompt neutralized' : 'Excluded from LLM Prompt';
  [
    ['Field Provenance（字段来源）','Prompt contract declaration（提示合同声明）'],
    ['Field Usage Stage（字段使用阶段）',usage],
    ['证据边界',category === 'excluded' ? '该字段不进入 Final Research LLM Prompt。' : '该字段按 persisted prompt contract 展示。'],
  ].forEach(([label,value]) => { const line = element('div'); line.append(element('dt','',label),element('dd','',value)); list.appendChild(line); });
  root.appendChild(list);
  openDrawer('field',{fieldName});
}

function renderPromptFieldList(id, values, category) {
  const root = byId(id);
  values.forEach((fieldName) => {
    const item = element('li');
    const button = element('button','prompt-field-button');
    appendBreakableFieldLabel(button,promptFieldLabel(fieldName));
    button.type = 'button';
    button.addEventListener('click',() => renderPromptFieldDetail(fieldName,category));
    item.appendChild(button); root.appendChild(item);
  });
}

function renderLineageMetadata() {
  const fillDefinitions = (id, categories) => categories.forEach((category) => {
    const line = element('div'); line.append(element('dt','',category.label),element('dd','',category.definition)); byId(id).appendChild(line);
  });
  fillDefinitions('lineage-provenance-legend',explanationDocument.provenance_categories);
  fillDefinitions('lineage-usage-legend',explanationDocument.usage_stages);
  explanationDocument.usage_stages.forEach((stage) => { const option = element('option','',stage.label); option.value = stage.key; byId('lineage-stage-filter').appendChild(option); });
}

function renderLineage() {
  const query = byId('lineage-search').value.trim().toLowerCase();
  const stage = byId('lineage-stage-filter').value;
  const body = byId('lineage-table-body'); body.replaceChildren();
  const filtered = payload.field_lineage.filter((entry) => {
    const explanation = explanationCatalog.get(entry.field_name);
    const searchText = `${entry.field_name} ${entry.provenance} ${entry.usage_stages.join(' ')} ${Object.values(explanation || {}).join(' ')}`.toLowerCase();
    return (!query || searchText.includes(query)) && (!stage || entry.usage_stages.includes(stage));
  });
  filtered.forEach((entry) => {
    const explanation = explanationCatalog.get(entry.field_name);
    const row = element('tr');
    const field = element('td'); const button = element('button','lineage-field',entry.field_name); button.type = 'button'; button.dataset.fieldName = entry.field_name; button.setAttribute('aria-controls','lineage-detail'); button.addEventListener('click',() => renderLineageDetail(entry.field_name)); field.appendChild(button);
    row.append(field,element('td','',explanation.chinese_name),element('td','',explanation.meaning),element('td','',provenanceLabels[entry.provenance]),element('td','',entry.usage_stages.map((value) => usageLabels[value]).join(' · '))); body.appendChild(row);
  });
  if (filtered.length) renderLineageDetail(filtered.some((entry) => entry.field_name === selectedLineageField) ? selectedLineageField : filtered[0].field_name,false);
  else { selectedLineageField = ''; byId('lineage-detail').replaceChildren(element('p','muted','没有符合当前条件的字段。')); }
}

function renderBatchTimeline() {
  const root = byId('shared-batch-timeline');
  Array.from({length:payload.run.horizon},(_,timeStep) => timeStep).forEach((timeStep) => {
    const button = element('button','',String(timeStep));
    button.type = 'button';
    button.dataset.batch = String(timeStep);
    button.setAttribute('aria-label',`Batch ${timeStep}`);
    button.addEventListener('click',() => selectBatch(timeStep));
    root.appendChild(button);
  });
}

function selectBatch(timeStep) {
  const round = payload.ranking_rounds.find((row) => row.time_step === timeStep);
  if (!round) return;
  if (interactionState.batch !== timeStep) closeDrawer({restoreFocus:false});
  interactionState.batch = timeStep;
  reportRoot.dataset.currentBatch = String(timeStep);
  document.querySelectorAll('[data-batch]').forEach((button) => {
    if (Number(button.dataset.batch) === timeStep) button.setAttribute('aria-current','step');
    else button.removeAttribute('aria-current');
  });
  byId('batch-mechanism-label').textContent = timeStep === 0
    ? 'Seed direct exposure（种子直接曝光）'
    : 'Global Reranking（全局重排）';
  const isSeedBatch = timeStep === 0;
  byId('ranking-batch-eyebrow').textContent = isSeedBatch ? 'BATCH 0（第 0 批） · SEED DIRECT EXPOSURE（种子直接曝光）' : 'GLOBAL RERANKING（全局重排）';
  byId('ranking-batch-title').textContent = isSeedBatch
    ? 'Seed direct exposure（种子直接曝光）'
    : `Batch ${timeStep} Global Reranking（全局重排）`;
  const weights = payload.ranking_diagnostics_summary.main_weights;
  byId('ranking-batch-description').textContent = isSeedBatch
    ? '本批直接曝光预先声明的 seed union（种子并集），不使用三路 ranking score（排序分数）决定入选。'
    : `平台对全部尚未处理的 eligible users（合格用户）重新计算排序：历史评论网络相关性 ${(weights.base_network * 100).toFixed(0)}%、已互动直接邻居信号 ${(weights.engaged_neighbor * 100).toFixed(0)}%、目标标签亲和度 ${(weights.tag_affinity * 100).toFixed(0)}%。`;
  byId('ranking-batch-formula').hidden = isSeedBatch;
  byId('reranking-evidence-contract').hidden = isSeedBatch;
  renderRankingRound();
  renderAblation();
  renderBatchDecisionEvidence();
  renderNetworkFeedback();
}

function summaryItem(label, value) {
  const article = element('article'); article.append(element('span','',label),element('strong','',display(value))); return article;
}

function renderRankingWorkedExample() {
  const evidence = payload.ranking_rounds.flatMap((round) => round.candidates.map((candidate) => ({time_step:round.time_step,...candidate})));
  const preferredCandidate = evidence.find((row) => !row.is_seed && row.selected && row.engaged_neighbor_signal > 0);
  const candidate = preferredCandidate || evidence.find((row) => !row.is_seed && row.selected)
    || evidence[0];
  if (!candidate) return;
  const weights = payload.ranking_diagnostics_summary.main_weights;
  const contributions = [
    ['base_network_relevance（历史评论网络相关性）',candidate.base_network_relevance,weights.base_network],
    ['engaged_neighbor_signal（已互动直接邻居信号）',candidate.engaged_neighbor_signal,weights.engaged_neighbor],
    ['historical_tag_affinity（历史标签亲和度）',candidate.historical_tag_affinity,weights.tag_affinity],
  ];
  const root = byId('ranking-worked-example');
  root.append(
    element('h3','',`Persisted Candidate Evidence（持久化候选证据）复算示例`),
    element('p','',`User（用户）${candidate.user_id} · Batch（批次）${candidate.time_step} · Rank（名次）${candidate.ranking_position} · ${candidate.selected ? '已曝光' : '未曝光'}`),
    element('p','',preferredCandidate ? '确定选择规则：按批次与名次顺序，取首位非 seed（种子用户）、已曝光且邻居信号为正的候选。' : '确定选择规则：当前证据无正向邻居信号候选，按批次与名次顺序取首位非 seed（种子用户）已曝光候选。'),
  );
  const grid = element('div','ranking-worked-example-grid');
  contributions.forEach(([field,value,weight]) => {
    const contribution = Number(value) * Number(weight);
    const item = element('div');
    item.append(element('strong','',String(field)),element('span','',`${fixed(value)} × ${(Number(weight) * 100).toFixed(0)}% = ${fixed(contribution)}`));
    grid.appendChild(item);
  });
  root.appendChild(grid);
  const total = contributions.reduce((sum,[,value,weight]) => sum + Number(value) * Number(weight),0);
  root.appendChild(element('p','worked-total',`${contributions.map(([,value,weight]) => fixed(Number(value) * Number(weight))).join(' + ')} = ${fixed(total)} recommendation_score（推荐排序分数；持久化值 ${fixed(candidate.recommendation_score)}）`));
}

function renderRankingRound() {
  const timeStep = interactionState.batch;
  const round = payload.ranking_rounds.find((row) => row.time_step === timeStep);
  if (!round) return;
  const isSeedBatch = timeStep === 0;
  const values = isSeedBatch
    ? [
      ['Predeclared seeds（预声明种子）',round.selected_count],['Delivery Capacity（投放容量）',round.delivery_capacity],['Direct exposures（直接曝光）',round.target_exposures],
      ['Provider succeeded（Provider 成功）',round.target_exposures - round.provider_failed],['Provider failed（Provider 失败）',round.provider_failed],
    ]
    : [
      ['Eligible（合格候选）',count(round.eligible_count)],['Delivery Capacity（投放容量）',round.delivery_capacity],['Selected（已选择）',round.selected_count],
      ['Target exposures（目标视频曝光）',round.target_exposures],['Provider failed（Provider 失败）',round.provider_failed],['Network-active selected（网络信号入选）',round.selected_with_positive_engaged_neighbor_signal],
    ];
  const summary = byId('round-summary'); summary.replaceChildren(); values.forEach(([label,value]) => summary.appendChild(summaryItem(label,value)));
  byId('ranking-candidate-title').textContent = isSeedBatch ? 'Batch 0 seed direct exposures（种子直接曝光）' : '逐批候选结果';
  byId('ranking-candidate-description').textContent = isSeedBatch
    ? '顺序仅用于追踪预声明 seeds（种子用户），不表示 Global Reranking（全局重排）名次。'
    : '当前表格展示进入当批 Delivery Capacity（投放容量）的候选。';
  const headers = isSeedBatch
    ? ['Seed order（种子顺序）','User（用户）']
    : ['Rank（名次）','User（用户）','Base network（历史网络）','Engaged neighbor（已互动邻居）','Tag affinity（标签亲和度）','Score（分数）'];
  const head = byId('ranking-candidate-head-row'); head.replaceChildren(); headers.forEach((label) => head.appendChild(element('th','',label)));
  const body = byId('ranking-candidate-body'); body.replaceChildren();
  round.candidates.filter((candidate) => candidate.selected).forEach((candidate) => {
    const row = element('tr'); row.tabIndex = 0;
    const cells = isSeedBatch
      ? [candidate.ranking_position,candidate.user_id]
      : [candidate.ranking_position,candidate.user_id,fixed(candidate.base_network_relevance),`${candidate.engaged_neighbor_count} / ${fixed(candidate.engaged_neighbor_signal)}`,fixed(candidate.historical_tag_affinity),fixed(candidate.recommendation_score)];
    cells.forEach((value) => row.appendChild(element('td','',display(value))));
    row.addEventListener('click',() => renderCandidateDetail(candidate,timeStep));
    row.addEventListener('keydown',(event) => { if (event.key === 'Enter') renderCandidateDetail(candidate,timeStep); });
    body.appendChild(row);
  });
}

function renderCandidateDetail(candidate, timeStep) {
  const root = byId('drawer-candidate-detail'); root.replaceChildren();
  const user = users.find((row) => row.user_id === candidate.user_id);
  const weights = payload.ranking_diagnostics_summary.main_weights;
  root.append(
    element('h3','',`${user?.nickname || candidate.user_id} · ${candidate.user_id}`),
    traceGroup('Persisted selection（持久化选择）',[
      ['sample role（样本角色）',sampleRoleLabels[user?.sample_role] || user?.sample_role],
      ['Batch（批次）',timeStep],
      ['ranking position（排序名次）',candidate.ranking_position],
      ['selected（已曝光）',candidate.selected],
      ['action（动作）',actionLabels[user?.action] || user?.action],
      ['confidence（置信度）',fixed(user?.confidence)],
      ['reason（理由）',user?.reason],
    ]),
  );
  const contributions = element('section','candidate-contributions');
  if (timeStep === 0) {
    contributions.append(
      element('h3','','Seed selection evidence（种子选择证据）'),
      element('p','muted','Batch 0 由预声明 seed union 直接曝光；持久化 ranking score 不决定本批选择。'),
    );
    root.appendChild(contributions);
    openDrawer('candidate',{userId:candidate.user_id,batch:timeStep});
    return;
  }
  contributions.appendChild(element('h3','',`Score contribution（分数贡献） · ${fixed(candidate.recommendation_score)}`));
  [
    ['base_network_relevance',candidate.base_network_relevance,weights.base_network],
    ['engaged_neighbor_signal',candidate.engaged_neighbor_signal,weights.engaged_neighbor],
    ['historical_tag_affinity',candidate.historical_tag_affinity,weights.tag_affinity],
  ].forEach(([field,value,weight]) => {
    const lineage = payload.field_lineage.find((entry) => entry.field_name === field);
    const item = element('article');
    item.append(
      element('strong','',String(field)),
      element('span','',`${fixed(value)} × ${(Number(weight) * 100).toFixed(0)}% = ${fixed(Number(value) * Number(weight))}`),
      element('span','',`Field Provenance（字段来源）${lineage ? provenanceLabels[lineage.provenance] : 'persisted candidate evidence（持久化候选证据）'}`),
      element('span','',`Field Usage Stage（字段使用阶段）${lineage ? lineage.usage_stages.map((stage) => usageLabels[stage]).join(' · ') : 'Ranking（排序）'}`),
    );
    contributions.appendChild(item);
  });
  root.appendChild(contributions);
  openDrawer('candidate',{userId:candidate.user_id,batch:timeStep});
}

function renderBatchDecisionEvidence() {
  const timeStep = interactionState.batch;
  const root = byId('batch-decision-evidence'); root.replaceChildren();
  const exposedUsers = users.filter((user) => user.exposure_time_step === timeStep);
  root.append(
    element('h3','',`Batch ${timeStep}（第 ${timeStep} 批）persisted decision evidence（持久化决策证据）`),
    element('p','',timeStep === 0
      ? '平台直接曝光预声明 seeds；Decision Adapter 只为这些已曝光用户输出结构化 action。'
      : '平台先用 Global Reranking 选择 Recommendation Opportunity；Decision Adapter 只为当批已曝光用户输出结构化 action。'),
  );
  const list = element('div','batch-decision-list');
  exposedUsers.forEach((user) => {
    const item = element('article'); item.tabIndex = 0;
    item.append(
      element('strong','',`${user.nickname || user.user_id} · ${user.user_id}`),
      element('span','',`${providerStatusLabels[user.provider_status] || user.provider_status} · ${resultStatusLabels[user.result_status] || user.result_status}`),
      element('span','',`action（动作）${actionLabels[user.action] || display(user.action)} · confidence（置信度）${fixed(user.confidence)}`),
    );
    item.addEventListener('click',() => renderUserDetail(user));
    item.addEventListener('keydown',(event) => { if (event.key === 'Enter') renderUserDetail(user); });
    list.appendChild(item);
  });
  if (!exposedUsers.length) list.appendChild(element('p','muted','本批没有 persisted exposure decision（持久化曝光决策）。'));
  root.appendChild(list);
}

function renderNetworkFeedback() {
  const timeStep = interactionState.batch;
  const actions = users.filter((user) => user.exposure_time_step === timeStep);
  const propagating = actions.filter((user) => ['like','comment','share'].includes(user.action));
  const ignored = actions.filter((user) => user.action === 'ignore');
  const currentRound = payload.ranking_rounds.find((round) => round.time_step === timeStep);
  const nextRound = payload.ranking_rounds.find((round) => round.time_step === timeStep + 1);
  const currentNeighborCounts = new Map(
    (currentRound?.candidates || []).map((candidate) => [candidate.user_id,candidate.engaged_neighbor_count]),
  );
  const activatedCandidates = nextRound
    ? nextRound.candidates.filter(
        (candidate) => candidate.engaged_neighbor_count > (currentNeighborCounts.get(candidate.user_id) ?? 0),
      )
    : [];
  byId('network-feedback-title').textContent = nextRound
    ? `Batch ${timeStep} 互动如何进入下一轮排序`
    : `Batch ${timeStep} 是最后一批，不再形成下一轮排序`;
  const summary = byId('network-feedback-summary'); summary.replaceChildren();
  [
    ['当批已曝光',actions.length,`Batch ${timeStep}（第 ${timeStep} 批）的 persisted exposure decisions（持久化曝光决策）`,'exposure_time_step'],
    ['可传播 action（动作）',`${count(propagating.length)} 个`,'like（点赞）/ comment（评论）/ share（分享）','action'],
    ['ignore（忽略）',`${count(ignored.length)} 个`,'不激活直接邻居排序信号','action'],
    ['新增直接邻居信号',`${count(activatedCandidates.length)} 位候选`,nextRound ? `Batch ${nextRound.time_step}（第 ${nextRound.time_step} 批）相对上一批的 engaged_neighbor_count（已互动邻居数）增加` : '本次运行已到最后一批','ranking_rounds.candidates.engaged_neighbor_count'],
  ].forEach(([label,value,note,lineageField]) => {
    const card = metric(label,value,note); card.tabIndex = 0; card.classList.add('interactive-evidence');
    card.addEventListener('click',() => renderNetworkFeedbackDetail(label,value,note,lineageField,timeStep));
    card.addEventListener('keydown',(event) => { if (event.key === 'Enter') renderNetworkFeedbackDetail(label,value,note,lineageField,timeStep); });
    summary.appendChild(card);
  });
}

function lineageContractGroup(fieldName, limitation) {
  const lineage = payload.field_lineage.find((entry) => entry.field_name === fieldName);
  return traceGroup('Evidence contract（证据合同）',[
    ['Field（字段）',fieldName],
    ['Field Provenance（字段来源）',provenanceLabels[lineage?.provenance] || lineage?.provenance],
    ['Field Usage Stage（字段使用阶段）',(lineage?.usage_stages || []).map((stage) => usageLabels[stage] || stage).join(' · ')],
    ['研究限制',limitation],
  ]);
}

function renderNetworkFeedbackDetail(label, value, note, lineageField, timeStep) {
  const root = byId('network-detail'); root.replaceChildren();
  root.append(
    element('h3','',`${label} · Batch ${timeStep}`),
    traceGroup('Persisted evidence（持久化证据）',[[label,value],['口径',note]]),
    lineageContractGroup(lineageField,'每次反馈只作用于一跳直接邻居；后续互动可能跨批形成新的直接邻居反馈。'),
  );
  openDrawer('network',{fieldName:lineageField,batch:timeStep});
}

function renderNetworkSummary() {
  const summary = payload.ranking_diagnostics_summary;
  const weights = summary.main_weights;
  const weightLabel = `${(weights.base_network * 100).toFixed(0)}/${(weights.engaged_neighbor * 100).toFixed(0)}/${(weights.tag_affinity * 100).toFixed(0)}`;
  const inclusion = metric('Recommendation Signal Inclusion（推荐信号已纳入）',summary.network_signals_in_formula ? '已纳入' : '未纳入',`${weightLabel} 权重 · diagnostic adapter calls（诊断适配器调用）${summary.diagnostic_decision_adapter_calls}`);
  const effect = metric('Observed Recommendation Signal Effect（推荐信号产生可观测影响）',summary.top_selection_changed ? `${topLabel}（前列集合）已改变` : `${topLabel}（前列集合）未改变`,`${summary.batches_with_top_selection_change} / ${payload.ranking_rounds.length} 个批次的同批 ${topLabel} membership（成员集合）发生变化`);
  byId('network-effect-summary').append(inclusion,effect);
  byId('network-effect-reading').textContent = summary.top_selection_changed
    ? 'Observed Recommendation Signal Effect：本次运行存在可观测变化'
    : 'Observed Recommendation Signal Effect：本次运行未观察到变化';
}

function renderAblation() {
  const batches = payload.ranking_diagnostics.paired_ablation.batches;
  const timeStep = interactionState.batch;
  const batch = batches.find((row) => row.time_step === timeStep);
  if (!batch) return;
  const summary = byId('ablation-summary'); summary.replaceChildren();
  [
    ['Eligible（合格候选）',batch.eligible_count],[`${topLabel} overlap（重合人数）`,batch.top_overlap_count],['network-added（网络新增）',batch.network_added_user_ids.length],
    ['network-removed（网络移除）',batch.network_removed_user_ids.length],[`Full ${topLabel}（完整排序）`,batch.full_top_user_ids.length],[`No-network ${topLabel}（无网络排序）`,batch.no_network_top_user_ids.length],
  ].forEach(([label,value]) => summary.appendChild(summaryItem(label,value)));
  const deltas = byId('ablation-rank-delta-body'); deltas.replaceChildren();
  batch.rank_deltas.forEach((row) => {
    const effect = batch.network_added_user_ids.includes(row.user_id) ? 'network-added（网络新增）' : batch.network_removed_user_ids.includes(row.user_id) ? 'network-removed（网络移除）' : batch.full_top_user_ids.includes(row.user_id) ? 'retained（保留）' : 'not-selected（未入选）';
    const line = element('tr'); line.tabIndex = 0;
    [row.user_id,row.full_rank,row.no_network_rank,`${row.network_rank_delta > 0 ? '+' : ''}${row.network_rank_delta}`].forEach((value) => line.appendChild(element('td','',display(value))));
    line.appendChild(element('td','effect-label',effect));
    line.addEventListener('click',() => renderPairedRankingDetail(row,batch,effect));
    line.addEventListener('keydown',(event) => { if (event.key === 'Enter') renderPairedRankingDetail(row,batch,effect); });
    deltas.appendChild(line);
  });
}

function renderPairedRankingDetail(row, batch, selectionEffect) {
  const root = byId('network-detail'); root.replaceChildren();
  const user = users.find((candidate) => candidate.user_id === row.user_id);
  root.append(
    element('h3','',`${user?.nickname || row.user_id} · ${row.user_id}`),
    traceGroup('Frozen paired evidence（冻结配对证据）',[
      ['Batch（批次）',batch.time_step],
      ['full rank（完整排序名次）',row.full_rank],
      ['no-network rank（无网络排序名次）',row.no_network_rank],
      ['rank delta（名次变化）',row.network_rank_delta],
      ['selection effect（入选影响）',selectionEffect],
      ['action（动作）',actionLabels[user?.action] || user?.action],
      ['reason（理由）',user?.reason],
    ]),
    lineageContractGroup('ranking_diagnostics.paired_ablation','同批冻结 candidate evidence 只重算 full / no-network ranking，不调用 Decision Adapter，不推进第二条 trajectory，也不是因果实验。'),
  );
  openDrawer('network',{userId:row.user_id,batch:batch.time_step});
}

function renderSensitivity() {
  const descriptions = {
    main_50_30_20:['主方案','预声明研究假设，作为正式排序与比较基准。','与自身基准比较，用于确认计算口径。'],
    weaker_network_40_20_40:['网络较弱','降低两项网络权重，检查投放选择对主权重假设的稳健性。','重合越接近每批投放容量，表示主方案对权重调整越稳健。'],
    no_network_0_0_100:['无网络','移除评论网络贡献，只保留目标标签亲和度作为对照。','不同选择越多，表示网络项对本次投放集合的影响越明显。'],
  };
  let readingExample = null;
  payload.ranking_diagnostics.weight_sensitivity.variants.forEach((variant) => {
    const averageOverlap = variant.batches.reduce((total,batch) => total + batch.overlap_with_main_user_ids.length,0) / Math.max(1,variant.batches.length);
    const averageChanged = variant.batches.reduce((total,batch) => total + batch.added_vs_main_user_ids.length,0) / Math.max(1,variant.batches.length);
    const ratio = `${(variant.weights.base_network * 100).toFixed(0)}/${(variant.weights.engaged_neighbor * 100).toFixed(0)}/${(variant.weights.tag_affinity * 100).toFixed(0)}`;
    const [name,purpose,interpretation] = descriptions[variant.variant_id] || [variant.variant_id,'预声明权重对照。','结合重合人数与不同选择数阅读。'];
    const article = element('article'); article.dataset.variantId = variant.variant_id;
    article.append(element('strong','',`${name}（${ratio}）`),element('span','',purpose),element('span','',`平均 ${topLabel} overlap（重合人数）${averageOverlap.toFixed(1)} · 平均 changed selections（不同选择数）${averageChanged.toFixed(1)}`),element('span','',`结果解读：${interpretation}`));
    byId('sensitivity-variants').appendChild(article);
    if (variant.variant_id === 'weaker_network_40_20_40') readingExample = {name,averageOverlap,averageChanged};
  });
  if (!readingExample) {
    const fallback = payload.ranking_diagnostics.weight_sensitivity.variants[0];
    const batches = fallback?.batches || [];
    readingExample = {name:'所选方案',averageOverlap:batches.reduce((total,batch) => total + batch.overlap_with_main_user_ids.length,0) / Math.max(1,batches.length),averageChanged:batches.reduce((total,batch) => total + batch.added_vs_main_user_ids.length,0) / Math.max(1,batches.length)};
  }
  byId('sensitivity-reading-note').textContent = `同时阅读平均 ${topLabel} overlap（重合人数）与平均 changed selections（不同选择数）；本次${readingExample.name}方案的 ${readingExample.averageOverlap.toFixed(1)} overlap（重合人数）约等于 ${readingExample.averageChanged.toFixed(1)} 个不同选择。`;
}

function renderBars(id, rows) {
  const root = byId(id);
  const maximum = Math.max(1,...rows.map((row) => Number(row.value) || 0));
  rows.forEach((row) => {
    const line = element('div','bar-row'); const track = element('div','bar-track'); const fill = element('div','bar-fill');
    fill.style.width = `${(Number(row.value || 0) / maximum) * 100}%`; track.appendChild(fill);
    line.append(element('span','',row.label),track,element('strong','',display(row.value))); root.appendChild(line);
  });
}

function renderBatchChart(id, rows, valueKey) {
  const root = byId(id); const maximum = Math.max(1,...rows.map((row) => Number(row[valueKey]) || 0));
  rows.forEach((row) => { const column = element('div','batch-column'); column.title = `Batch（批次）${row.time_step}: ${row[valueKey]}`; const bar = element('i'); bar.style.height = `${Math.max(2,(Number(row[valueKey] || 0) / maximum) * 115)}px`; column.appendChild(bar); root.appendChild(column); });
}

function renderChartExplanation(id, explanation) {
  const root = byId(id);
  [
    ['统计什么',explanation.measurement],
    ['单位 / 分母',explanation.denominator],
    ['为什么需要',explanation.purpose],
    ['本次结果',explanation.result],
  ].forEach(([label,value]) => {
    const line = element('p');
    line.append(element('strong','',`${label}：`),document.createTextNode(value));
    root.appendChild(line);
  });
}

function renderChartExplanations() {
  Object.entries(explanationDocument.chart_explanations).forEach(([id,explanation]) => {
    renderChartExplanation(id,explanation);
  });
}

function renderCharts() {
  renderBatchChart('batch-delivery-chart',payload.ranking_rounds,'target_exposures');
  renderBars('action-chart',[...resultStatusCounts.entries()].sort().map(([label,value]) => ({label:resultStatusLabels[label] || label,value})));
  renderBars('provider-failure-chart',payload.ranking_rounds.map((row) => ({label:`Batch ${row.time_step}（第 ${row.time_step} 批）`,value:row.provider_failed})).filter((row) => row.value > 0).concat(payload.ranking_rounds.every((row) => row.provider_failed === 0) ? [{label:'No failures（无失败）',value:0}] : []));
  renderBars('network-activation-chart',payload.ranking_rounds.map((row) => ({label:`Batch ${row.time_step}（第 ${row.time_step} 批）`,value:row.candidates_with_positive_engaged_neighbor_signal})).filter((row) => row.value > 0).slice(0,12).concat(payload.ranking_rounds.every((row) => row.candidates_with_positive_engaged_neighbor_signal === 0) ? [{label:'No activation（未激活）',value:0}] : []));
  renderBatchChart('ablation-overlap-chart',payload.ranking_diagnostics.paired_ablation.batches,'top_overlap_count');
}

function populateUserFilters() {
  const addOptions = (id, values, labels = {}) => values.forEach((value) => { const option = element('option','',labels[value] || value); option.value = value; byId(id).appendChild(option); });
  addOptions('result-filter',[...new Set(users.map((row) => row.result_status))].sort(),resultStatusLabels);
  addOptions('scope-filter',[...new Set(users.map((row) => row.sample_source_scope))].sort(),Object.fromEntries(users.map((row) => [row.sample_source_scope,sourceScopeLabel(row.sample_source_scope)])));
}

function userSearchText(row) {
  return [row.user_id,row.nickname,row.bio,row.signature,row.reason,row.sample_source_scope,row.sample_role,...row.interest_tags,...row.historical_tags,row.latent_class,row.latent_hotel_class,row.latent_travel_purpose].join(' ').toLowerCase();
}

function renderUsers() {
  const query = byId('user-search').value.trim().toLowerCase();
  const result = byId('result-filter').value; const role = byId('role-filter').value; const scope = byId('scope-filter').value;
  const seed = byId('seed-filter').value; const cohort = byId('cohort-filter').value;
  const filtered = users.filter((row) => (!query || userSearchText(row).includes(query)) && (!result || row.result_status === result) && (!role || row.sample_role === role) && (!scope || row.sample_source_scope === scope) && (!seed || String(row.is_seed) === seed) && (!cohort || String(row.is_network_cohort) === cohort));
  byId('visible-user-count').textContent = `${count(filtered.length)} / ${count(users.length)}`;
  const body = byId('user-table-body'); body.replaceChildren();
  filtered.forEach((row) => {
    const tr = element('tr'); tr.tabIndex = 0;
    const profile = element('td'); profile.append(element('span','profile-name',row.nickname || row.user_id),element('span','profile-id',row.user_id));
    const status = element('span',`status ${row.result_status}`,resultStatusLabels[row.result_status] || row.result_status); const resultCell = element('td'); resultCell.append(status,element('small','provider-status',providerStatusLabels[row.provider_status] || row.provider_status));
    [profile,element('td','',`${sampleRoleLabels[row.sample_role] || row.sample_role} · ${sourceScopeLabel(row.sample_source_scope)}`),element('td','',`${row.latest_ranking_time_step} / ${row.latest_ranking_position}`),element('td','',fixed(row.recommendation_score)),resultCell,element('td','',row.reason || '-')].forEach((cell) => tr.appendChild(cell));
    tr.addEventListener('click',() => renderUserDetail(row)); tr.addEventListener('keydown',(event) => { if (event.key === 'Enter') renderUserDetail(row); }); body.appendChild(tr);
  });
}

function traceGroup(title, fields) {
  const article = element('article'); article.appendChild(element('h3','',title)); const list = element('dl');
  fields.forEach(([label,value]) => { const line = element('div'); line.append(element('dt','',label),element('dd','',display(value))); list.appendChild(line); }); article.appendChild(list); return article;
}

function renderProxyExplanationGuide() {
  const details = element('details','proxy-explanation-guide'); details.dataset.testid = 'proxy-explanation-guide';
  details.appendChild(element('summary','','查看派生代理计算说明'));
  details.appendChild(element('p','', '五项均为 0..1 的归一化数值；越高只表示对应可观测证据在本项目口径下越强。Local network（局部网络分量）与 Local recognition（局部认可分量）是 local influence（局部影响力代理）的两个组成部分，不是独立心理特征。'));
  const list = element('div','proxy-explanation-list');
  proxyFields.forEach(([fieldName,label]) => {
    const explanation = explanationCatalog.get(fieldName);
    if (!explanation) return;
    const article = element('article'); article.appendChild(element('h4','',label));
    [
      ['含义',explanation.meaning],
      ['计算',explanation.calculation],
      ['范围与高低值',`${explanation.value_range} ${explanation.interpretation}`],
      ['限制',explanation.limitation],
    ].forEach(([term,value]) => {
      const line = element('p'); line.append(element('strong','',`${term}：`),document.createTextNode(value)); article.appendChild(line);
    });
    list.appendChild(article);
  });
  details.appendChild(list);
  return details;
}

function fieldTraceValue(row, fieldName) {
  const value = row[fieldName];
  if (Array.isArray(value)) return value.length ? value.join(', ') : '-';
  return display(value);
}

function renderUserFieldTraceDetail(row, trace, definition) {
  const root = byId('user-field-trace-detail'); root.replaceChildren(); root.hidden = false;
  root.appendChild(element('h4','',`${definition.field_name}（${definition.display_name_zh}）`));
  const facts = element('dl');
  const locator = trace.source_record_locator;
  const evidence = trace.evidence.map((item) => `${item.evidence_kind}: ${item.matched_values.join(', ')} · ${JSON.stringify(item.record_key)}`).join(' | ') || '-';
  [
    ['Value（字段值）',fieldTraceValue(row,definition.field_name)],
    ['Value status（值状态）',valueStatusLabels[trace.value_status] || trace.value_status],
    ['Field Provenance（字段来源）',provenanceLabels[definition.provenance] || definition.provenance],
    ['Source artifact kind（来源 artifact 类型）',definition.source_artifact_kind],
    ['Artifact id',locator.artifact_id],
    ['Relative path（仓库内相对路径）',locator.relative_path],
    ['Record key（记录键）',JSON.stringify(locator.record_key)],
    ['Source fields（来源字段）',definition.source_fields.join(' · ')],
    ['Evidence（实际证据）',evidence],
    ['Transformation method（变换方法）',definition.transformation_method],
    ['Transformation（形成方式）',definition.transformation_description],
    ['Declared Usage Stage（声明用途）',definition.declared_usage_stages.map((stage) => usageLabels[stage] || stage).join(' · ')],
    ['Actual Usage Stage（本次实际用途）',trace.actual_usage_stages.map((stage) => usageLabels[stage] || stage).join(' · ')],
    ['Prompt inclusion（Prompt 纳入状态）',promptInclusionLabels[trace.prompt_inclusion_status] || trace.prompt_inclusion_status],
    ['Omission reason（省略原因）',trace.omission_reason || '-'],
    ['范围与解读',`${definition.value_range} ${definition.interpretation}`],
    ['限制',definition.limitations.join(' · ')],
  ].forEach(([label,value]) => { const line = element('div'); line.append(element('dt','',label),element('dd','',value)); facts.appendChild(line); });
  const sourceLink = element('a','field-trace-source-link','打开来源 artifact'); sourceLink.href = locator.relative_path; sourceLink.setAttribute('download','');
  root.append(facts,sourceLink);
}

function renderUserFieldTrace(row) {
  const traces = payload.user_field_trace_index?.[row.user_id] || [];
  if (!traces.length) return null;
  const section = element('section','user-field-trace'); section.dataset.testid = 'user-field-trace';
  section.appendChild(element('h3','','User Field Trace（用户字段追溯）'));
  const list = element('div','user-field-trace-list');
  traces.forEach((trace) => {
    const definition = fieldLineageCatalog.get(trace.field_name);
    if (!definition) return;
    const button = element('button','user-field-trace-button'); button.type = 'button';
    button.dataset.fieldName = trace.field_name; button.dataset.testid = `user-field-trace-${trace.field_name}`;
    button.setAttribute('aria-expanded','false'); button.setAttribute('aria-controls','user-field-trace-detail');
    button.append(
      element('strong','',`${definition.field_name}（${definition.display_name_zh}）`),
      element('span','',fieldTraceValue(row,trace.field_name)),
      element('small','',`${valueStatusLabels[trace.value_status] || trace.value_status} · ${provenanceLabels[definition.provenance] || definition.provenance}`),
    );
    button.addEventListener('click',() => {
      list.querySelectorAll('button').forEach((candidate) => candidate.setAttribute('aria-expanded',String(candidate === button)));
      renderUserFieldTraceDetail(row,trace,definition);
    });
    list.appendChild(button);
  });
  const detail = element('div','user-field-trace-detail'); detail.id = 'user-field-trace-detail'; detail.dataset.testid = 'user-field-trace-detail'; detail.hidden = true;
  section.append(list,detail);
  return section;
}

function renderUserDetail(row) {
  const root = byId('user-detail'); root.replaceChildren(); root.appendChild(element('h3','',`${row.nickname || row.user_id} · ${row.user_id}`));
  const groups = element('div','trace-groups');
  const proxyValues = traceGroup('派生代理',proxyFields.map(([fieldName,label]) => [label,fixed(row[fieldName])]));
  proxyValues.dataset.testid = 'proxy-values';
  groups.append(
    traceGroup('直接观测',[['nickname（昵称）',row.nickname],['bio（简介）',row.bio],['signature（个性签名）',row.signature],['followers（粉丝数）',row.follower_count],['following（关注数）',row.following_count],['video_count（作品数）',row.video_count]]),
    traceGroup('历史行为',[['interest_tags（兴趣标签）',row.interest_tags.join(', ')],['historical_tags（历史互动标签）',row.historical_tags.join(', ')],['weighted_degree（历史网络加权度）',row.historical_comment_network_weighted_degree]]),
    proxyValues,
    traceGroup('合成标签',[['class（实验类别）',row.latent_class],['hotel class（酒店类别）',row.latent_hotel_class],['travel purpose（出行目的）',row.latent_travel_purpose],['age（年龄段）',row.latent_age],['income（月收入区间）',row.latent_monthly_income]]),
    traceGroup('样本与 ranking（排序）',[['role（角色）',sampleRoleLabels[row.sample_role] || row.sample_role],['scope（来源分组）',sourceScopeLabel(row.sample_source_scope)],['seed（种子用户）',row.is_seed],['network cohort（网络传播识别组）',row.is_network_cohort],['batch / rank（批次 / 名次）',`${row.latest_ranking_time_step} / ${row.latest_ranking_position}`],['score（分数）',fixed(row.recommendation_score)]]),
    traceGroup('曝光与 provider（服务提供方）',[['selected（已选择）',row.selected_for_exposure],['exposure batch（曝光批次）',row.exposure_time_step],['provider（服务提供方）',providerStatusLabels[row.provider_status] || row.provider_status],['failure type（失败类型）',contextualValueLabel(row.provider_failure_type,'Provider 失败类型')]]),
    traceGroup('最终 action（动作）',[['result（结果）',resultStatusLabels[row.result_status] || row.result_status],['action（动作）',actionLabels[row.action] || row.action],['engage（是否互动）',row.engage],['probability（互动倾向）',fixed(row.probability)],['confidence（置信度）',fixed(row.confidence)],['reason（理由）',row.reason],['source（来源）',contextualValueLabel(row.decision_source,'决策来源')]])
  );
  const historyPanel = element('section','ranking-history'); historyPanel.appendChild(element('h3','','逐轮 ranking evidence（排序证据）'));
  const historyWrap = element('div','table-wrap'); const historyTable = element('table'); historyTable.dataset.testid = 'ranking-history-table';
  const head = element('thead'); const headRow = element('tr'); ['Batch（批次）','Rank（名次）','Selected（已选择）','Base network（历史网络）','Engaged neighbor（已互动邻居）','Tag affinity（标签亲和度）','Score（分数）'].forEach((label) => headRow.appendChild(element('th','',label))); head.appendChild(headRow);
  const body = element('tbody'); (rankingHistoryByUser.get(row.user_id) || []).forEach((evidence) => {
    const line = element('tr'); [evidence.time_step,evidence.ranking_position,evidence.selected,fixed(evidence.base_network_relevance),`${evidence.engaged_neighbor_count} / ${fixed(evidence.engaged_neighbor_signal)}`,fixed(evidence.historical_tag_affinity),fixed(evidence.recommendation_score)].forEach((value) => line.appendChild(element('td','',display(value)))); body.appendChild(line);
  });
  historyTable.append(head,body); historyWrap.appendChild(historyTable); historyPanel.appendChild(historyWrap);
  const fieldTrace = renderUserFieldTrace(row);
  root.append(groups,traceGroup('Field contract（字段合同）',[["Field Provenance（字段来源）","Direct Observed / Historical Behavioral Evidence / Derived Proxy / Runtime Simulation Result"],["Field Usage Stage（字段使用阶段）","Sampling / Ranking / LLM Prompt / Report Only"]]));
  if (fieldTrace) root.appendChild(fieldTrace);
  root.append(renderProxyExplanationGuide(),historyPanel);
  openDrawer('user',{userId:row.user_id,batch:row.exposure_time_step});
}

renderSample(); renderLineageMetadata(); renderLineage(); renderRankingWorkedExample();
renderBatchTimeline(); selectBatch(interactionState.batch);
renderNetworkSummary(); renderSensitivity();
renderPromptFieldList('prompt-allowed',payload.prompt_contract.allowed_profile_fields,'allowed'); renderPromptFieldList('prompt-neutral',payload.prompt_contract.neutralized_fields,'neutral'); renderPromptFieldList('prompt-excluded',payload.prompt_contract.excluded_fields,'excluded'); fillList('limitations-list',payload.limitations.map((value) => limitationTranslations[value] || value));
renderChartExplanations(); renderCharts(); populateUserFilters(); renderUsers();
byId('lineage-search').addEventListener('input',renderLineage); byId('lineage-stage-filter').addEventListener('input',renderLineage);
['user-search','role-filter','result-filter','scope-filter','seed-filter','cohort-filter'].forEach((id) => byId(id).addEventListener('input',renderUsers));
"""


def _build_report_aggregates(rows: Sequence[UserReportRow], horizon: int) -> FinalResearchAggregates:
    action_counts = Counter(row.result_status for row in rows)
    scope_counts = Counter(row.sample_source_scope or "unspecified" for row in rows)
    provider_by_step = Counter(
        row.assigned_step for row in rows if row.result_status == "provider_failed" and row.assigned_step is not None
    )
    neighbor_by_step: dict[int, list[int]] = {}
    for row in rows:
        if row.assigned_step is None or row.engaged_neighbor_count is None:
            continue
        neighbor_by_step.setdefault(row.assigned_step, []).append(row.engaged_neighbor_count)
    return FinalResearchAggregates(
        action_distribution=[AggregateRow(label=label, value=count) for label, count in sorted(action_counts.items())],
        scope_distribution=[AggregateRow(label=label, value=count) for label, count in sorted(scope_counts.items())],
        provider_failures=[
            AggregateRow(label=f"Step {step}", value=provider_by_step.get(step, 0)) for step in range(horizon)
        ],
        dynamic_neighbor_signal=[
            AggregateRow(
                label=f"Step {step}",
                value=round(sum(values) / len(values), 4) if values else 0.0,
            )
            for step, values in sorted(neighbor_by_step.items())
        ],
    )


def _build_trends_from_users(rows: Sequence[UserReportRow], horizon: int) -> list[FinalResearchTrendRow]:
    trends = [
        FinalResearchTrendRow(
            time_step=time_step,
            assigned_users=0,
            seed_users=0,
            target_exposures=0,
            background_impressions=0,
            decisions=0,
            engagements=0,
            ignored=0,
            provider_failed=0,
        )
        for time_step in range(horizon)
    ]
    for row in rows:
        if row.assigned_step is None or not 0 <= row.assigned_step < horizon:
            raise ValueError(f"report payload user {row.user_id} has an invalid assigned_step")
        trend = trends[row.assigned_step]
        trend.assigned_users += 1
        trend.seed_users += int(row.is_seed)
        trend.target_exposures += int(row.exposure_status == "target_exposed")
        trend.background_impressions += int(row.result_status == "background_content")
        trend.decisions += int(row.provider_status == "succeeded")
        trend.engagements += int(row.result_status in {"like", "comment", "share"})
        trend.ignored += int(row.result_status == "ignore")
        trend.provider_failed += int(row.result_status == "provider_failed")
    return trends


def rebuild_final_research_report(run_dir: str | Path) -> Path:
    """Validate an existing safe run and atomically rebuild its explainable report."""

    run_path = Path(run_dir)
    if not run_path.is_dir():
        raise FileNotFoundError(f"Final Research run directory does not exist: {run_path}")
    manifest_path = run_path / "artifact_manifest.json"
    payload_path = run_path / FINAL_RESEARCH_REPORT_ARTIFACTS["final_research_report_payload"]
    for required_path in (manifest_path, payload_path):
        if not required_path.is_file():
            raise FileNotFoundError(f"Final Research rebuild requires {required_path.name}")

    manifest = _read_json_object(manifest_path)
    payload_document = _read_json_object(payload_path)
    if manifest.get("manifest_version") == FINAL_RESEARCH_RANKING_RUNTIME_VERSION:
        ranking_payload = (
            FinalResearchRankingReportPayload.model_validate(payload_document)
            if payload_document.get("schema_version") == "final-research-ranking-report-payload-v4"
            else FinalResearchRankingReportPayloadV3.model_validate(payload_document)
        )
        _validate_ranking_rebuild_evidence(run_path, manifest, ranking_payload)
        return _publish_report_files(run_path, ranking_payload)

    summary_path = run_path / "runtime_summary.json"
    if not summary_path.is_file():
        raise FileNotFoundError(f"Final Research rebuild requires {summary_path.name}")
    runtime_summary = _read_json_object(summary_path)
    base_payload = _parse_report_payload(payload_document)
    _validate_rebuild_evidence(run_path, manifest, base_payload, runtime_summary)

    explainable_payload = _build_explainable_payload(base_payload, runtime_summary)
    return _publish_report_files(run_path, explainable_payload)


def _build_explainable_payload(
    base_payload: FinalResearchReportPayloadV1,
    runtime_summary: Mapping[str, object] | None,
) -> FinalResearchReportPayload:
    users = base_payload.users
    action_counts = Counter(row.result_status for row in users)
    target_exposures = sum(row.exposure_status == "target_exposed" for row in users)
    background_count = action_counts["background_content"]
    provider_decisions = target_exposures
    engagements = sum(action_counts[action] for action in ("like", "comment", "share"))
    opportunities = len(users) if base_payload.run.runtime_enabled else 0
    if runtime_summary is not None:
        provider_decisions = _as_int(runtime_summary.get("decision_adapter_calls")) or target_exposures

    seed_example_row = next(
        (row for row in users if row.is_seed and row.exposure_status == "target_exposed"),
        None,
    )
    non_seed_example_row = next((row for row in users if not row.is_seed and row.random_draw is not None), None)
    positive_neighbor_rows = [row for row in users if (row.engaged_neighbor_count or 0) > 0]
    maximum_neighbors = max((row.engaged_neighbor_count or 0 for row in users), default=0)
    maximum_actual_boost = max(
        (
            max(0.0, row.dynamic_network_score - row.base_network_score)
            for row in users
            if row.dynamic_network_score is not None and row.base_network_score is not None
        ),
        default=0.0,
    )
    neighbor_activated = maximum_actual_boost > 0.0
    sample_size = len(users)
    runtime_enabled = base_payload.run.runtime_enabled
    seed_first_run = base_payload.run.sampling_method == "seed_first_research_sample_v1"
    video_method = (
        "仅一条真实 TargetVideo 进入 runtime，历史视频只提供信号。"
        if runtime_enabled
        else "Provider runtime 未启用；TargetVideo 只用于离线评分与诊断说明。"
    )
    batch_method = (
        "Batch 0 分配 seeds，Batch 1–29 分配其他用户；每人只抽签一次。"
        if runtime_enabled
        else "Provider runtime 未启用，因此没有执行固定批次分配或曝光抽签。"
    )
    decision_method = (
        "仅 Target Exposure 调用结构化 Decision Adapter。"
        if runtime_enabled
        else "Provider runtime 未启用，Decision Adapter 未被调用。"
    )

    payload_data = base_payload.model_dump(mode="json")
    payload_data.update(
        {
            "schema_version": "final-research-report-payload-v2",
            "run_funnel": [
                _funnel_stage(
                    "offline_scoring",
                    "Offline scoring",
                    base_payload.recommendation_model.score_summary.user_count,
                    "使用 holdout-safe 历史信号计算静态推荐分数。",
                ),
                _funnel_stage(
                    "research_sample",
                    "Research Sample",
                    sample_size,
                    (
                        "从 full eligible pool 先选 seeds、再纳入一跳直接邻居，并按 Primary Video Source Scope 稳定补足。"
                        if seed_first_run
                        else "按 source scope 配额、去重与稳定补齐形成研究样本。"
                    ),
                ),
                _funnel_stage(
                    "recommendation_opportunity",
                    "Recommendation Opportunity",
                    opportunities,
                    "每个样本用户只属于一个固定批次，最多获得一次目标视频机会。",
                ),
                _funnel_stage(
                    "target_exposure",
                    "Target Exposure",
                    target_exposures,
                    "Seed 强制曝光；non-seed 仅在 random_draw < recommendation_score 时曝光。",
                ),
                _funnel_stage(
                    "provider_decision",
                    "Provider Decision",
                    provider_decisions,
                    "目标曝光后才调用 Decision Adapter；背景内容不会调用。",
                ),
                _funnel_stage("engagement", "Engagement", engagements, "like、comment 或 share 计为参与。"),
                _funnel_stage(
                    "background_content",
                    "Background Content",
                    background_count,
                    "抽签失败时记录背景内容占用机会，不对历史视频执行 runtime 排序。",
                ),
            ],
            "methodology_flow": [
                _method_stage("data", "数据来源", "读取 processed Video Catalog、用户画像和评论派生互动证据。"),
                _method_stage(
                    "sampling",
                    "用户筛选",
                    (
                        "从全量合格用户形成 seed union，纳入 Historical Set 一跳邻居，再按来源配额稳定补足。"
                        if seed_first_run
                        else "按 source scope 配额抽样，去重后使用稳定顺序补齐。"
                    ),
                ),
                _method_stage("video", "视频用途", video_method),
                _method_stage("network", "评论网络", "一级评论、回复和 @ mention 构成历史互动图，不等同关注关系。"),
                _method_stage(
                    "recommendation", "推荐评分", "静态分数结合网络与标签，动态分数可加入已参与直接邻居 boost。"
                ),
                _method_stage("batches", "固定批次与抽签", batch_method),
                _method_stage("decision", "LLM 决策", decision_method),
                _method_stage("outcome", "结果解释", "只根据持久化动作计数、结构化合同和样本规模解释结果。"),
            ],
            "video_usage": {
                "runtime_target_video_count": 1 if runtime_enabled else 0,
                "historical_video_count": base_payload.sample_summary.historical_video_count,
                "target_video_role": (
                    "唯一进入固定批次、曝光抽签和 Provider Decision 的真实 TargetVideo。"
                    if runtime_enabled
                    else "Provider runtime 未启用；本次没有 TargetVideo 曝光或 Provider Decision。"
                ),
                "background_video_role": "仅提供评论网络、历史标签和抽样信号；本次报告不声称对背景视频完成了 runtime 排序。",
            },
            "sampling_explanation": {
                "source_scope_counts": base_payload.sample_summary.source_scope_counts,
                "quota_method": (
                    "Seeds 与 Seed Neighbor Cohort 先占用 Primary Video Source Scope 配额，普通真实用户补足剩余配额。"
                    if seed_first_run
                    else "按 source_challenge_name 分配 Research Sample 配额。"
                ),
                "deduplication_and_refill": (
                    "角色按 user_id 互斥去重；scope 不足时使用 audit 记录的 deterministic fallback 补足。"
                    if seed_first_run
                    else "用户按 user_id 去重；配额不足时使用稳定候选顺序补齐到固定样本数。"
                ),
                "holdout_safe_projection": "TargetVideo 互动在画像投影、抽样、seed 选择和推荐评分完成前保持 holdout。",
                "seed_union_method": base_payload.diagnostics.seed_method,
                "seed_forced_exposure": (
                    "global top10 与 local top10 的去重 union 在 Batch 0 强制曝光，不参与 random draw。"
                    if runtime_enabled
                    else "已计算 global/local top10 seed union，但 runtime 未启用，因此没有执行强制曝光。"
                ),
            },
            "comment_network_explanation": (
                "Comment-Derived User Interaction Graph 来自一级评论者到视频作者、回复者到被回复评论者以及 "
                "@ mention 关系；它是历史互动代理，不是好友或关注网络。"
            ),
            "recommendation_explanation": {
                "static_formula": base_payload.recommendation_model.formula,
                "dynamic_formula": "dynamic_network_score = min(1.0, base_network_score + neighbor_boost * engaged_neighbor_count); recommendation_score = network_weight * dynamic_network_score + tag_affinity_weight * historical_tag_affinity",
                "network_weight": base_payload.recommendation_model.network_weight,
                "tag_affinity_weight": base_payload.recommendation_model.tag_affinity_weight,
                "neighbor_boost": base_payload.recommendation_model.neighbor_boost,
                "seed_example": _recommendation_example(seed_example_row),
                "non_seed_example": _recommendation_example(non_seed_example_row),
            },
            "batch_explanation": {
                "batch_count": base_payload.run.horizon if runtime_enabled else 0,
                "seed_batch": 0,
                "non_seed_batches": [1, max(1, base_payload.run.horizon - 1)] if runtime_enabled else [],
                "opportunity_limit": 1,
                "assignment_method": (
                    "Seeds 固定属于 Batch 0；其他用户经稳定 shuffle 后 round-robin 分配到 Batch 1–29。"
                    if runtime_enabled
                    else "Provider runtime 未启用，未执行 batch assignment 或 TargetVideo opportunity。"
                ),
            },
            "decision_contract": {
                "fields": ["engage", "probability", "reason", "confidence", "action"],
                "action_values": ["like", "comment", "share", "ignore"],
                "single_most_likely_action": True,
                "persisted_context_label": "重建的决策上下文",
                "prompt_recoverability": "当前安全 artifacts 只保留 allowlisted evidence；完整原始 PeerContext 与 Provider Prompt 不可恢复。",
            },
            "outcome_explanations": [
                _outcome_explanation(action, action_counts[action], sample_size)
                for action in ("like", "comment", "share", "ignore", "provider_failed")
            ],
            "dynamic_neighbor_summary": {
                "users_with_positive_engaged_neighbor_count": len(positive_neighbor_rows),
                "maximum_engaged_neighbor_count": maximum_neighbors,
                "configured_neighbor_boost": base_payload.recommendation_model.neighbor_boost,
                "maximum_actual_boost": round(maximum_actual_boost, 6),
                "activated": neighbor_activated,
                "explanation": (
                    "本次运行中已有用户在批次冻结时观测到参与邻居，动态 boost 实际生效。"
                    if neighbor_activated
                    else (
                        "本次存在正向 engaged_neighbor_count，但 configured neighbor_boost 为 0，因此未实际生效。"
                        if positive_neighbor_rows and base_payload.recommendation_model.neighbor_boost == 0
                        else (
                            "本次存在正向 engaged_neighbor_count，但 network score 饱和后实际最大 boost 为 0，因此未实际生效。"
                            if positive_neighbor_rows
                            else "配置包含动态邻居 boost，但本次所有 persisted engaged_neighbor_count 均为 0，因此未实际生效。"
                        )
                    )
                ),
            },
            "user_traces": [_user_trace(row) for row in users],
        }
    )
    return FinalResearchReportPayload.model_validate(payload_data)


def _validate_ranking_rebuild_evidence(
    run_path: Path,
    manifest: Mapping[str, object],
    payload: FinalResearchRankingReportPayloadV3 | FinalResearchRankingReportPayload,
) -> None:
    if manifest.get("manifest_version") != FINAL_RESEARCH_RANKING_RUNTIME_VERSION:
        raise ValueError("unsupported Target Delivery Ranking artifact manifest schema")
    artifacts = _required_mapping(manifest, "artifacts", "artifact manifest")
    seed_first = payload.run.sampling_method == "seed_first_research_sample_v1"
    sample_audit_name = "seed_first_sample_audit" if seed_first else "network_augmented_sample_audit"
    sample_audit_path = "seed_first_sample_audit.json" if seed_first else "network_augmented_sample_audit.json"
    required_artifacts = {
        "final_research_report": "report.html",
        "final_research_report_payload": "final_research_report_payload.json",
        "final_research_users_csv": "final_research_users.csv",
        "final_research_users_json": "final_research_users.json",
        sample_audit_name: sample_audit_path,
        "ranking_runtime_candidates": "ranking_runtime_candidates.csv",
        "ranking_runtime_outcomes": "ranking_runtime_outcomes.csv",
        "ranking_runtime_steps": "ranking_runtime_steps.csv",
        "ranking_runtime_summary": "ranking_runtime_summary.json",
        "ranking_diagnostics": "ranking_diagnostics.json",
        "ranking_diagnostics_summary": "ranking_diagnostics_summary.json",
    }
    v4_payload = payload if isinstance(payload, FinalResearchRankingReportPayload) else None
    is_v4 = v4_payload is not None
    if v4_payload is not None:
        required_artifacts.update(
            {
                "field_lineage_catalog": "field_lineage_catalog.json",
                "field_source_records": "field_source_records.json",
                "user_field_trace": "user_field_trace.json",
            }
        )
    for name, expected_path in required_artifacts.items():
        if artifacts.get(name) != expected_path:
            raise ValueError(f"artifact manifest has invalid {name} path")
    artifact_paths: dict[str, Path] = {}
    for name, relative_path in artifacts.items():
        if not isinstance(name, str) or not isinstance(relative_path, str):
            raise ValueError("artifact manifest names and paths must be strings")
        artifact_paths[name] = _artifact_path(run_path, relative_path, name)

    if v4_payload is not None:
        catalog_document = _read_json_object(artifact_paths["field_lineage_catalog"])
        trace_document = _read_json_object(artifact_paths["user_field_trace"])
        source_document = _read_json_object(artifact_paths["field_source_records"])
        if catalog_document.get("schema_version") != "field-lineage-catalog-v1":
            raise ValueError("unsupported field lineage catalog schema")
        if trace_document.get("schema_version") != "user-field-trace-v1":
            raise ValueError("unsupported user field trace schema")
        if source_document.get("schema_version") != "field-source-records-v1":
            raise ValueError("unsupported field source records schema")
        if catalog_document.get("definitions") != [
            definition.model_dump(mode="json") for definition in v4_payload.field_lineage_catalog
        ]:
            raise ValueError("field lineage catalog artifact does not match ranking report payload")
        if trace_document.get("users") != {
            user_id: [trace.model_dump(mode="json") for trace in traces]
            for user_id, traces in v4_payload.user_field_trace_index.items()
        }:
            raise ValueError("user field trace artifact does not match ranking report payload")
        source_records = _required_list(source_document, "records", "field source records")
        source_record_ids = {
            str(record.get("user_id", "")) for record in source_records if isinstance(record, Mapping)
        }
        if source_record_ids != set(v4_payload.user_field_trace_index):
            raise ValueError("field source records do not match ranking report users")
        for user_id, traces in v4_payload.user_field_trace_index.items():
            for trace in traces:
                locator = trace.source_record_locator
                if artifacts.get(locator.artifact_id) != locator.relative_path:
                    raise ValueError(f"field trace locator does not match artifact manifest for {user_id}")
                if locator.record_key != {"user_id": user_id}:
                    raise ValueError(f"field trace locator has an invalid record key for {user_id}")

    user_ids = [row.user_id for row in payload.users]
    if len(user_ids) != len(set(user_ids)):
        raise ValueError("ranking report payload contains duplicate user_id")
    if payload.run.sample_size != len(user_ids):
        raise ValueError("ranking report payload user count does not match run.sample_size")
    actual_scope_counts = dict(sorted(Counter(row.sample_source_scope for row in payload.users).items()))
    if dict(sorted(payload.sample_comparison.final_source_scope_counts.items())) != actual_scope_counts:
        raise ValueError("ranking report final source scope distribution does not match users")
    if v4_payload is not None and v4_payload.sample_role_counts != dict(
        sorted(Counter(row.sample_role for row in payload.users).items())
    ):
        raise ValueError("ranking report sample role counts do not match users")

    audit = _read_json_object(artifact_paths[sample_audit_name])
    if seed_first:
        if audit.get("schema_version") != "seed-first-sample-audit-v1":
            raise ValueError("unsupported seed-first sample audit schema")
        roles = _required_mapping(audit, "roles", "seed-first sample audit")
        role_counts = _mapping_counts(roles, "counts", "seed-first sample roles")
        role_user_ids = _required_mapping(roles, "user_ids", "seed-first sample roles")
        base_sample: Mapping[str, object] = {"count": 0, "user_ids": [], "source_scope_counts": {}}
        network_cohort: Mapping[str, object] = {
            "count": _as_int(role_counts.get("network_cohort")),
            "user_ids": _required_list(role_user_ids, "network_cohort", "seed-first roles"),
            "added_user_ids": _required_list(role_user_ids, "network_cohort", "seed-first roles"),
        }
        replacement: Mapping[str, object] = {"count": 0}
        seed_ids = [str(value) for value in _required_list(role_user_ids, "seed", "seed-first roles")]
        ordinary_ids = [str(value) for value in _required_list(role_user_ids, "ordinary", "seed-first roles")]
    else:
        if audit.get("schema_version") != "network-augmented-sample-audit-v1":
            raise ValueError("unsupported network augmented sample audit schema")
        base_sample = _required_mapping(audit, "base_sample", "network sample audit")
        network_cohort = _required_mapping(audit, "network_cohort", "network sample audit")
        replacement = _required_mapping(audit, "ordinary_replacement", "network sample audit")
        seed_ids = [str(value) for value in _required_list(audit, "seed_user_ids", "network sample audit")]
        ordinary_ids = []
    final_sample = _required_mapping(audit, "final_sample", "sample audit")
    base_ids = [str(value) for value in _required_list(base_sample, "user_ids", "base sample")]
    final_ids = [str(value) for value in _required_list(final_sample, "user_ids", "final sample")]
    cohort_ids = [str(value) for value in _required_list(network_cohort, "user_ids", "network cohort")]
    for label, values in (
        ("base sample", base_ids),
        ("final sample", final_ids),
        ("network cohort", cohort_ids),
        ("seed", seed_ids),
    ):
        if len(values) != len(set(values)):
            raise ValueError(f"{label} contains duplicate user ids")
    if set(final_ids) != set(user_ids):
        raise ValueError("network sample audit final users do not match ranking report users")
    comparison_expectations = {
        "base_sample_count": _as_int(base_sample.get("count")),
        "final_sample_count": _as_int(final_sample.get("count")),
        "seed_count": len(seed_ids),
        "network_cohort_count": _as_int(network_cohort.get("count")),
        "network_cohort_added_count": len(_required_list(network_cohort, "added_user_ids", "network cohort")),
        "replacement_count": _as_int(replacement.get("count")),
    }
    comparison_document = payload.sample_comparison.model_dump(mode="json")
    for key, expected in comparison_expectations.items():
        if comparison_document[key] != expected:
            raise ValueError(f"ranking report sample comparison {key} does not match audit")
    if seed_first and payload.sample_comparison.ordinary_count != len(ordinary_ids):
        raise ValueError("ranking report ordinary_count does not match seed-first sample audit")
    if payload.sample_comparison.base_source_scope_counts != _int_mapping(base_sample.get("source_scope_counts")):
        raise ValueError("ranking report Base Sample source scope counts do not match audit")
    if payload.sample_comparison.final_source_scope_counts != _int_mapping(final_sample.get("source_scope_counts")):
        raise ValueError("ranking report final sample source scope counts do not match audit")
    if {row.user_id for row in payload.users if row.in_base_sample} != set(base_ids) & set(final_ids):
        raise ValueError("ranking report Base Sample membership does not match audit")
    if {row.user_id for row in payload.users if row.is_seed} != set(seed_ids):
        raise ValueError("ranking report seed membership does not match audit")
    if {row.user_id for row in payload.users if row.is_network_cohort} != set(cohort_ids):
        raise ValueError("ranking report Network Cohort membership does not match audit")

    summary = _read_json_object(artifact_paths["ranking_runtime_summary"])
    if summary.get("runtime_version") != FINAL_RESEARCH_RANKING_RUNTIME_VERSION:
        raise ValueError("unsupported Target Delivery Ranking runtime summary schema")
    expected_sampling_method = payload.run.sampling_method
    expected_sampling_status = payload.run.sampling_status
    for evidence_name, evidence in (
        ("artifact manifest", manifest),
        ("ranking runtime summary", summary),
    ):
        evidence_method = evidence.get("sampling_method") or "network_augmented_research_sample"
        evidence_status = evidence.get("sampling_status") or "historical_network_augmented_run"
        if evidence_method != expected_sampling_method:
            raise ValueError(f"{evidence_name} sampling_method does not match report payload")
        if evidence_status != expected_sampling_status:
            raise ValueError(f"{evidence_name} sampling_status does not match report payload")
    if seed_first:
        if audit.get("sampling_method") != expected_sampling_method:
            raise ValueError("seed-first sample audit sampling_method does not match report payload")
        if audit.get("sampling_status") != expected_sampling_status:
            raise ValueError("seed-first sample audit sampling_status does not match report payload")
    summary_counts = _mapping_counts(summary, "counts", "ranking runtime summary")
    derived_counts = {
        "sample_users": len(payload.users),
        "seed_users": sum(row.is_seed for row in payload.users),
        "target_exposures": sum(row.selected_for_exposure for row in payload.users),
        "decisions": sum(row.provider_status == "succeeded" for row in payload.users),
        "engagements": sum(row.result_status in {"like", "comment", "share"} for row in payload.users),
        "ignored": sum(row.result_status == "ignore" for row in payload.users),
        "provider_failed": sum(row.result_status == "provider_failed" for row in payload.users),
        "below_delivery_capacity": sum(row.result_status == "below_delivery_capacity" for row in payload.users),
    }
    for key, expected in derived_counts.items():
        if _as_int(summary_counts.get(key)) != expected:
            raise ValueError(f"ranking runtime summary count {key} does not match report payload")
    if _as_int(summary.get("horizon")) != payload.run.horizon:
        raise ValueError("ranking runtime summary horizon does not match report payload")
    if _as_int(summary.get("delivery_capacity")) != payload.run.delivery_capacity:
        raise ValueError("ranking runtime summary delivery capacity does not match report payload")
    if summary.get("ranking_formula") != payload.run.ranking_formula:
        raise ValueError("ranking runtime summary formula does not match report payload")
    if summary.get("engaged_neighbor_formula") != payload.run.engaged_neighbor_formula:
        raise ValueError("ranking runtime engaged-neighbor formula does not match report payload")

    manifest_counts = _mapping_counts(manifest, "counts", "artifact manifest")
    manifest_expectations = {
        "sample_users": derived_counts["sample_users"],
        "seed_users": derived_counts["seed_users"],
        "runtime_exposures": derived_counts["target_exposures"],
        "runtime_decisions": derived_counts["decisions"],
        "runtime_provider_failures": derived_counts["provider_failed"],
    }
    for key, expected in manifest_expectations.items():
        if _as_int(manifest_counts.get(key)) != expected:
            raise ValueError(f"artifact manifest count {key} does not match ranking report payload")
    if _as_int(manifest.get("decision_adapter_calls")) != derived_counts["target_exposures"]:
        raise ValueError("artifact manifest decision_adapter_calls does not match ranking report payload")

    outcome_rows = _unique_user_rows(
        _read_csv_rows(artifact_paths["ranking_runtime_outcomes"]),
        "ranking runtime outcomes",
    )
    if set(outcome_rows) != set(user_ids):
        raise ValueError("ranking runtime outcomes do not match ranking report users")
    for user_row in payload.users:
        outcome = outcome_rows[user_row.user_id]
        if outcome.get("result_status") != user_row.result_status:
            raise ValueError(f"ranking outcome status does not match report user {user_row.user_id}")
        if outcome.get("provider_status") != user_row.provider_status:
            raise ValueError(f"ranking provider status does not match report user {user_row.user_id}")
        if _optional_int(outcome, "exposure_time_step") != user_row.exposure_time_step:
            raise ValueError(f"ranking exposure batch does not match report user {user_row.user_id}")

    candidate_rows = _read_csv_rows(artifact_paths["ranking_runtime_candidates"])
    candidates_by_step: dict[int, list[Mapping[str, object]]] = {}
    candidate_keys: set[tuple[int, str]] = set()
    for candidate_row in candidate_rows:
        candidate_key = (
            _as_int(candidate_row.get("time_step")),
            str(candidate_row.get("user_id", "")),
        )
        if not candidate_key[1] or candidate_key in candidate_keys:
            raise ValueError("ranking runtime candidates contain duplicate batch user evidence")
        candidate_keys.add(candidate_key)
        candidates_by_step.setdefault(candidate_key[0], []).append(candidate_row)
    expected_rounds = _ranking_round_summaries(
        _read_csv_rows(artifact_paths["ranking_runtime_steps"]),
        candidates_by_step,
        payload.run.delivery_capacity,
    )
    if [row.model_dump(mode="json") for row in expected_rounds] != [
        row.model_dump(mode="json") for row in payload.ranking_rounds
    ]:
        raise ValueError("ranking report round summaries do not match runtime artifacts")

    full_diagnostics = _read_json_object(artifact_paths["ranking_diagnostics"])
    if full_diagnostics.get("schema_version") != "ranking-diagnostics-v1":
        raise ValueError("unsupported ranking diagnostics schema")
    if full_diagnostics != payload.ranking_diagnostics:
        raise ValueError("ranking diagnostics artifact does not match report payload")
    diagnostics = _read_json_object(artifact_paths["ranking_diagnostics_summary"])
    if full_diagnostics.get("summary") != diagnostics:
        raise ValueError("ranking diagnostics artifacts do not share the same summary")
    inclusion = _required_mapping(diagnostics, "recommendation_signal_inclusion", "ranking diagnostics summary")
    effect = _required_mapping(
        diagnostics,
        "observed_recommendation_signal_effect",
        "ranking diagnostics summary",
    )
    expected_diagnostics = RankingDiagnosticSummary(
        network_signals_in_formula=_strict_bool(inclusion.get("network_signals_in_formula")),
        main_weights={
            str(key): _as_float(value)
            for key, value in _required_mapping(inclusion, "main_weights", "ranking signal inclusion").items()
        },
        top_selection_changed=_strict_bool(effect.get("top_selection_changed")),
        batches_with_top_selection_change=_as_int(effect.get("batches_with_top_selection_change")),
        diagnostic_decision_adapter_calls=_as_int(diagnostics.get("diagnostic_decision_adapter_calls")),
    )
    if expected_diagnostics != payload.ranking_diagnostics_summary:
        raise ValueError("ranking diagnostics summary does not match report payload")

    expected_prompt_fields = {
        entry.field_name
        for entry in payload.field_lineage
        if entry.field_name in RankingUserReportRow.model_fields and "LLM Prompt" in entry.usage_stages
    }
    if expected_prompt_fields != set(JINJIANG_PROMPT_V2_PROFILE_FIELDS):
        raise ValueError("ranking report Prompt usage declarations do not match Prompt Field Summary")
    if set(payload.prompt_contract.allowed_profile_fields) != set(JINJIANG_PROMPT_V2_PROFILE_FIELDS):
        raise ValueError("ranking report Prompt contract does not match Prompt Field Summary")

    user_document = _read_json_object(artifact_paths["final_research_users_json"])
    expected_user_schema = "final-research-ranking-users-v4" if is_v4 else "final-research-ranking-users-v3"
    if user_document.get("schema_version") != expected_user_schema:
        raise ValueError("unsupported ranking user JSON schema")
    if user_document.get("links") != payload.downloads.model_dump(mode="json"):
        raise ValueError("ranking user JSON links do not match report payload")
    if user_document.get("users") != [row.model_dump(mode="json") for row in payload.users]:
        raise ValueError("ranking user JSON does not match report payload users")
    csv_rows = _read_csv_rows(artifact_paths["final_research_users_csv"])
    if [row.get("user_id") for row in csv_rows] != user_ids:
        raise ValueError("ranking user CSV does not match report payload users")
    if [row.get("result_status") for row in csv_rows] != [row.result_status for row in payload.users]:
        raise ValueError("ranking user CSV result statuses do not match report payload")
    for csv_row, payload_row in zip(csv_rows, payload.users, strict=True):
        for field_name in ("report_path", "payload_path", "json_path", "manifest_path"):
            relative_path = csv_row.get(field_name)
            if relative_path != getattr(payload_row, field_name):
                raise ValueError(f"ranking user CSV {field_name} does not match report payload")
            if not isinstance(relative_path, str):  # pragma: no cover
                raise ValueError(f"ranking user CSV {field_name} must be a string")
            _artifact_path(run_path, relative_path, f"CSV {field_name}")

    expected_downloads = {
        "report": artifacts.get("final_research_report"),
        "payload": artifacts.get("final_research_report_payload"),
        "csv": artifacts.get("final_research_users_csv"),
        "users_json": artifacts.get("final_research_users_json"),
        "manifest": "artifact_manifest.json",
        "ranking_diagnostics": artifacts.get("ranking_diagnostics"),
        "ranking_ablation_csv": artifacts.get("ranking_ablation_diagnostics_csv"),
        "ranking_sensitivity_csv": artifacts.get("ranking_weight_sensitivity_csv"),
    }
    if is_v4:
        expected_downloads.update(
            {
                "field_lineage_catalog": artifacts.get("field_lineage_catalog"),
                "user_field_trace": artifacts.get("user_field_trace"),
                "field_source_records": artifacts.get("field_source_records"),
            }
        )
    for field_name, relative_path in expected_downloads.items():
        if getattr(payload.downloads, field_name) != relative_path:
            raise ValueError(f"ranking report download {field_name} does not match artifact manifest")


def _validate_rebuild_evidence(
    run_path: Path,
    manifest: Mapping[str, object],
    payload: FinalResearchReportPayloadV1,
    runtime_summary: Mapping[str, object],
) -> None:
    if manifest.get("manifest_version") != FINAL_RESEARCH_RUNTIME_VERSION:
        raise ValueError("unsupported Final Research artifact manifest schema")
    if runtime_summary.get("runtime_version") != FINAL_RESEARCH_RUNTIME_VERSION:
        raise ValueError("unsupported Final Research runtime summary schema")
    if not payload.run.runtime_enabled:
        raise ValueError("report rebuild requires a provider runtime payload")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise ValueError("artifact_manifest.json must contain an artifacts object")
    expected_artifacts = {
        "final_research_report": "report.html",
        "final_research_report_payload": "final_research_report_payload.json",
        "runtime_summary": "runtime_summary.json",
    }
    for name, expected_path in expected_artifacts.items():
        if artifacts.get(name) != expected_path:
            raise ValueError(f"artifact manifest has invalid {name} path")
    for name, relative_path in artifacts.items():
        if not isinstance(name, str) or not isinstance(relative_path, str):
            raise ValueError("artifact manifest names and paths must be strings")
        _artifact_path(run_path, relative_path, name)

    user_ids = [row.user_id for row in payload.users]
    if len(user_ids) != len(set(user_ids)):
        raise ValueError("report payload contains duplicate user_id")
    user_count = len(user_ids)
    seed_count = sum(row.is_seed for row in payload.users)
    if payload.run.sample_size != user_count:
        raise ValueError("report payload user count does not match run.sample_size")
    if sum(payload.sample_summary.source_scope_counts.values()) != user_count:
        raise ValueError("report payload source scope counts do not match users")
    actual_scope_counts = dict(sorted(Counter(row.sample_source_scope for row in payload.users).items()))
    if dict(sorted(payload.sample_summary.source_scope_counts.items())) != actual_scope_counts:
        raise ValueError("report payload source scope distribution does not match users")
    if payload.sample_summary.seed_count != seed_count:
        raise ValueError("report payload seed count does not match users")
    if len(set(payload.sample_summary.seed_user_ids)) != payload.sample_summary.seed_count:
        raise ValueError("report payload seed_user_ids are inconsistent")
    if set(payload.sample_summary.seed_user_ids) != {row.user_id for row in payload.users if row.is_seed}:
        raise ValueError("report payload seed_user_ids do not match users")
    actual_role_counts = dict(sorted(Counter(row.sample_role for row in payload.users).items()))
    declared_role_counts = dict(sorted(payload.sample_summary.sample_role_counts.items()))
    if declared_role_counts and declared_role_counts != actual_role_counts:
        raise ValueError("report payload sample role counts do not match users")
    if payload.run.sampling_method == "seed_first_research_sample_v1" and not declared_role_counts:
        raise ValueError("Seed-First report payload requires sample role counts")
    expected_aggregates = _build_report_aggregates(payload.users, payload.run.horizon)
    if payload.aggregates.model_dump(mode="json") != expected_aggregates.model_dump(mode="json"):
        raise ValueError("report payload aggregates do not match users")
    expected_trends = _build_trends_from_users(payload.users, payload.run.horizon)
    if [row.model_dump(mode="json") for row in payload.trends] != [
        row.model_dump(mode="json") for row in expected_trends
    ]:
        raise ValueError("report payload trends do not match users")

    manifest_counts = _mapping_counts(manifest, "counts", "artifact manifest")
    summary_counts = _mapping_counts(runtime_summary, "counts", "runtime summary")
    derived_counts = {
        "sample_users": user_count,
        "seed_users": seed_count,
        "target_exposures": sum(row.exposure_status == "target_exposed" for row in payload.users),
        "background_impressions": sum(row.result_status == "background_content" for row in payload.users),
        "decisions": sum(row.provider_status == "succeeded" for row in payload.users),
        "engagements": sum(row.result_status in {"like", "comment", "share"} for row in payload.users),
        "ignored": sum(row.result_status == "ignore" for row in payload.users),
        "provider_failed": sum(row.result_status == "provider_failed" for row in payload.users),
    }
    for key, expected in derived_counts.items():
        if _as_int(summary_counts.get(key)) != expected:
            raise ValueError(f"runtime summary count {key} does not match report payload")
    manifest_expectations = {
        "sample_users": user_count,
        "seed_users": seed_count,
        "users_scored": payload.recommendation_model.score_summary.user_count,
        "runtime_exposures": user_count,
        "runtime_decisions": derived_counts["decisions"],
        "runtime_provider_failures": derived_counts["provider_failed"],
    }
    for key, expected in manifest_expectations.items():
        if _as_int(manifest_counts.get(key)) != expected:
            raise ValueError(f"artifact manifest count {key} does not match report payload")
    if _as_int(runtime_summary.get("horizon")) != payload.run.horizon:
        raise ValueError("runtime summary horizon does not match report payload")
    expected_schedule_contract: dict[str, object] = {
        "schedule_method": FINAL_RESEARCH_SCHEDULE_METHOD,
        "seed_step": FINAL_RESEARCH_SEED_STEP,
        "non_seed_steps": [1, payload.run.horizon - 1],
        "user_opportunity_limit": FINAL_RESEARCH_USER_OPPORTUNITY_LIMIT,
        "recommendation_score_usage": FINAL_RESEARCH_SCORE_USAGE,
        "dynamic_network_formula": FINAL_RESEARCH_DYNAMIC_NETWORK_FORMULA,
    }
    for field_name, expected_contract_value in expected_schedule_contract.items():
        if runtime_summary.get(field_name) != expected_contract_value:
            raise ValueError(f"runtime summary {field_name} does not match the supported runtime contract")
    if not isinstance(runtime_summary.get("provider_metadata"), Mapping):
        raise ValueError("runtime summary provider_metadata must be an object")
    adapter_calls = _as_int(runtime_summary.get("decision_adapter_calls"))
    if adapter_calls != derived_counts["target_exposures"]:
        raise ValueError("runtime summary decision_adapter_calls does not match target exposures")
    if _as_int(manifest.get("decision_adapter_calls")) != adapter_calls:
        raise ValueError("artifact manifest decision_adapter_calls does not match runtime summary")

    expected_downloads = {
        "report": artifacts.get("final_research_report"),
        "payload": artifacts.get("final_research_report_payload"),
        "csv": artifacts.get("final_research_users_csv"),
        "users_json": artifacts.get("final_research_users_json"),
        "manifest": "artifact_manifest.json",
    }
    for field_name, relative_path in expected_downloads.items():
        if getattr(payload.downloads, field_name) != relative_path:
            raise ValueError(f"report payload download {field_name} does not match artifact manifest")
        if not isinstance(relative_path, str):
            raise ValueError(f"artifact manifest is missing download target {field_name}")
        _artifact_path(run_path, relative_path, field_name)


def _parse_report_payload(document: Mapping[str, object]) -> FinalResearchReportPayloadV1:
    schema_version = document.get("schema_version")
    if schema_version == "final-research-report-payload-v1":
        return FinalResearchReportPayloadV1.model_validate(document)
    if schema_version == "final-research-report-payload-v2":
        payload_v2 = FinalResearchReportPayload.model_validate(document)
        base_fields = set(FinalResearchReportPayloadV1.model_fields)
        base_document = payload_v2.model_dump(include=base_fields, mode="json")
        base_document["schema_version"] = "final-research-report-payload-v1"
        return FinalResearchReportPayloadV1.model_validate(base_document)
    raise ValueError(f"unsupported Final Research report payload schema: {schema_version!r}")


def _read_json_object(path: Path) -> dict[str, object]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read valid JSON from {path.name}") from exc
    if not isinstance(document, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return document


def _read_csv_rows(path: Path) -> list[dict[str, object]]:
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ValueError(f"cannot read valid CSV from {path.name}") from exc


def _artifact_path(run_path: Path, relative_path: str, artifact_name: str) -> Path:
    path = Path(relative_path)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"artifact {artifact_name} has an unsafe path")
    candidate = run_path / path
    if not candidate.is_file():
        raise FileNotFoundError(f"artifact {artifact_name} is missing: {relative_path}")
    resolved = candidate.resolve()
    if not resolved.is_relative_to(run_path.resolve()):
        raise ValueError(f"artifact {artifact_name} resolves outside the run directory")
    return resolved


def _mapping_counts(document: Mapping[str, object], key: str, label: str) -> Mapping[str, object]:
    counts = document.get(key)
    if not isinstance(counts, Mapping):
        raise ValueError(f"{label} must contain a {key} object")
    return counts


def _stage_text(run_path: Path, target_name: str, content: str) -> Path:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=run_path,
        prefix=f".{target_name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(content)
        return Path(handle.name)


def _publish_report_files(
    run_path: Path,
    payload: FinalResearchReportPayload | FinalResearchRankingReportPayloadV3 | FinalResearchRankingReportPayload,
) -> Path:
    payload_path = run_path / FINAL_RESEARCH_REPORT_ARTIFACTS["final_research_report_payload"]
    report_path = run_path / FINAL_RESEARCH_REPORT_ARTIFACTS["final_research_report"]
    payload_text = safe_user_json(payload) + "\n"
    html_text = FinalResearchReportWriter.render_payload(payload)
    payload_model = type(payload)
    payload_model.model_validate(json.loads(payload_text))
    staged_payload: Path | None = _stage_text(run_path, payload_path.name, payload_text)
    staged_report: Path | None = _stage_text(run_path, report_path.name, html_text)
    try:
        assert staged_payload is not None
        os.replace(staged_payload, payload_path)
        staged_payload = None
        assert staged_report is not None
        os.replace(staged_report, report_path)
        staged_report = None
    finally:
        for staged_path in (staged_payload, staged_report):
            if staged_path is not None:
                staged_path.unlink(missing_ok=True)
    return report_path


def _funnel_stage(key: str, label: str, count: int, description: str) -> dict[str, object]:
    return {"key": key, "label": label, "count": count, "description": description}


def _typed_funnel_stage(key: str, label: str, count: int, description: str) -> FinalResearchFunnelStage:
    return FinalResearchFunnelStage.model_validate(_funnel_stage(key, label, count, description))


def _method_stage(key: str, title: str, summary: str) -> dict[str, str]:
    return {"key": key, "title": title, "summary": summary}


def _recommendation_example(row: UserReportRow | None) -> dict[str, object] | None:
    if row is None:
        return None
    if row.is_seed:
        explanation = "Seed 属于 global/local top10 union，在 Batch 0 强制曝光，不生成 random draw。"
    else:
        operator = "<" if (row.random_draw or 0.0) < (row.recommendation_score or 0.0) else ">="
        explanation = f"non-seed 抽签：random_draw {operator} recommendation_score，因此结果为 {row.exposure_status}。"
    return {
        "user_id": row.user_id,
        "is_seed": row.is_seed,
        "recommendation_score": row.recommendation_score,
        "random_draw": row.random_draw,
        "outcome": row.exposure_status,
        "explanation": explanation,
    }


def _outcome_explanation(action: str, count: int, sample_size: int) -> dict[str, object]:
    if count == 0:
        explanation = (
            f"本次 {sample_size} 名 Research Sample 中没有记录到 {action}；Provider Prompt 合同要求每次决策只返回一个最可能 action，"
            "该结论仅来自动作计数，不分析 reason 文本，也未调用额外 LLM。"
        )
    else:
        explanation = (
            f"本次记录到 {count} 次 {action}；计数来自 persisted structured decisions，不对 reason 文本做关键词推断。"
        )
    return {"action": action, "count": count, "explanation": explanation}


def _user_trace(row: UserReportRow) -> dict[str, object]:
    return {
        "user_id": row.user_id,
        "context_label": "重建的决策上下文",
        "persisted_evidence": {
            "sample_source_scope": row.sample_source_scope,
            "is_seed": row.is_seed,
            "assigned_step": row.assigned_step,
            "base_network_score": row.base_network_score,
            "dynamic_network_score": row.dynamic_network_score,
            "engaged_neighbor_count": row.engaged_neighbor_count,
            "historical_tag_affinity": row.historical_tag_affinity,
            "recommendation_score": row.recommendation_score,
            "random_draw": row.random_draw,
            "exposure_status": row.exposure_status,
            "result_status": row.result_status,
            "action": row.action,
            "engage": row.engage,
            "reason": row.reason,
            "confidence": row.confidence,
            "decision_source": row.decision_source,
        },
        "unrecoverable_peer_context_fields": [
            "PeerContext.exposed_neighbors",
            "PeerContext.influential_engaged_neighbors",
            "PeerContext.visible_likes",
            "PeerContext.visible_comments",
            "PeerContext.visible_shares",
            "original Provider Prompt messages",
        ],
        "prompt_recoverability": "完整原始 Provider Prompt 无法从当前安全 artifacts 恢复。",
    }


def _required_mapping(source: Mapping[str, object], key: str, label: str) -> Mapping[str, object]:
    value = source.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must contain a {key} object")
    return value


def _required_list(source: Mapping[str, object], key: str, label: str) -> list[object]:
    value = source.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{label} must contain a {key} list")
    return value


def _unique_user_rows(
    rows: Sequence[Mapping[str, object]],
    label: str,
) -> dict[str, Mapping[str, object]]:
    indexed: dict[str, Mapping[str, object]] = {}
    for row in rows:
        user_id = str(row.get("user_id", ""))
        if not user_id:
            raise ValueError(f"{label} contains an empty user_id")
        if user_id in indexed:
            raise ValueError(f"{label} contains duplicate user_id: {user_id}")
        indexed[user_id] = row
    return indexed


def _int_mapping(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise ValueError("expected an object containing integer counts")
    return {str(key): _as_int(item) for key, item in value.items()}


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    raise ValueError(f"expected boolean value, got {value!r}")


def _strict_bool(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"expected JSON boolean value, got {value!r}")
    return value


def _ranking_result_status(value: object) -> RankingResultStatus:
    status = str(value)
    if status not in {"like", "comment", "share", "ignore", "provider_failed", "below_delivery_capacity"}:
        raise ValueError(f"unsupported ranking result status: {status!r}")
    return status  # type: ignore[return-value]


def _ranking_provider_status(value: object) -> Literal["not_called", "succeeded", "provider_failed"]:
    status = str(value)
    if status not in {"not_called", "succeeded", "provider_failed"}:
        raise ValueError(f"unsupported ranking provider status: {status!r}")
    return status  # type: ignore[return-value]


def _string_list(value: object) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return [str(item) for item in value if str(item)]


def _report_action(value: object) -> ReportAction:
    if value == "like":
        return "like"
    if value == "comment":
        return "comment"
    if value == "share":
        return "share"
    if value == "ignore":
        return "ignore"
    return ""


def _result_action(value: object) -> ResultStatus:
    action = _report_action(value)
    return action if action else "ignore"


def _exposure_status(value: object) -> ExposureStatus:
    if value == "target_exposed":
        return "target_exposed"
    if value == "background_content":
        return "background_content"
    if value == "runtime_not_run":
        return "runtime_not_run"
    return "missing_exposure"


def _as_int(value: object) -> int:
    if value in (None, ""):
        return 0
    if isinstance(value, (str, int, float)):
        return int(value)
    raise TypeError(f"expected integer-compatible value, got {type(value).__name__}")


def _as_float(value: object) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, (str, int, float)):
        return float(value)
    raise TypeError(f"expected numeric value, got {type(value).__name__}")


def _optional_int(row: Mapping[str, object] | None, key: str) -> int | None:
    if row is None or row.get(key) in (None, ""):
        return None
    return _as_int(row[key])


def _optional_float(row: Mapping[str, object] | None, key: str) -> float | None:
    if row is None or row.get(key) in (None, ""):
        return None
    return _as_float(row[key])


def _optional_bool(row: Mapping[str, object] | None, key: str) -> bool | None:
    if row is None or row.get(key) in (None, ""):
        return None
    value = row[key]
    return value is True or str(value).lower() == "true"


_REPORT_CSS = r"""
:root { color-scheme: light; --bg:#f3f6f4; --surface:#ffffff; --ink:#18211d; --muted:#617068; --line:#d7dfda; --teal:#087f6a; --blue:#3267d6; --amber:#b86b12; --red:#bd4545; --violet:#6959b8; }
* { box-sizing:border-box; }
html { scroll-behavior:smooth; }
body { margin:0; background:var(--bg); color:var(--ink); font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
a { color:var(--blue); text-decoration:none; }
a:hover { text-decoration:underline; }
main { min-height:100vh; }
.topbar { min-height:86px; padding:18px clamp(18px,4vw,56px); display:flex; align-items:center; justify-content:space-between; gap:24px; background:#fff; border-bottom:1px solid var(--line); }
h1,h2,h3,p { margin-top:0; }
h1 { margin-bottom:0; font-size:clamp(1.25rem,2vw,1.75rem); }
h2 { margin-bottom:8px; font-size:1.35rem; }
h3 { margin-bottom:6px; font-size:.98rem; }
.eyebrow { display:block; margin-bottom:5px; color:var(--teal); font-size:.72rem; font-weight:800; letter-spacing:.08em; }
.downloads { display:flex; gap:8px; flex-wrap:wrap; }
.downloads a,.primary-link { min-height:36px; display:inline-flex; align-items:center; padding:7px 11px; border:1px solid var(--line); border-radius:6px; background:#fff; font-weight:700; }
.downloads a:first-child,.primary-link { background:var(--teal); border-color:var(--teal); color:#fff; }
.workflow-nav { min-height:44px; padding:0 clamp(18px,4vw,56px); display:flex; align-items:center; gap:20px; overflow-x:auto; white-space:nowrap; background:#18211d; border-bottom:1px solid #425048; }.workflow-nav a { padding:12px 0; color:#dce6e1; font-size:.78rem; font-weight:800; }
.target-band { padding:34px clamp(18px,4vw,56px); display:grid; grid-template-columns:minmax(0,1.4fr) minmax(280px,.8fr); gap:40px; background:#eaf3ef; border-bottom:1px solid var(--line); }
.target-copy h2 { max-width:900px; margin-bottom:10px; font-size:clamp(1.55rem,3vw,2.6rem); line-height:1.2; }
.tags { color:var(--teal); font-weight:700; }
.inline-actions { display:flex; align-items:center; gap:12px; flex-wrap:wrap; color:var(--muted); font-size:.88rem; }
.target-facts { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:1px; margin:0; background:var(--line); border:1px solid var(--line); }
.target-facts div { min-height:84px; padding:14px; background:#fff; }
dt { color:var(--muted); font-size:.76rem; } dd { margin:6px 0 0; font-size:1.12rem; font-weight:800; overflow-wrap:anywhere; }
.object-flow { padding:22px clamp(18px,4vw,56px); display:grid; grid-template-columns:1fr auto 1fr auto 1fr; align-items:center; gap:14px; background:#fff; border-bottom:1px solid var(--line); }
.object-flow article { min-height:94px; padding:14px; border-left:4px solid var(--blue); background:#f7f9fb; }
.object-flow article:nth-of-type(2) { border-color:var(--amber); }.object-flow article:nth-of-type(3) { border-color:var(--teal); }
.object-flow article span { color:var(--muted); font-size:.72rem; font-weight:800; }.object-flow article p { margin:0; color:var(--muted); font-size:.86rem; }
.object-flow i { color:var(--muted); font-style:normal; font-size:1.4rem; }
.metrics-band { padding:0 clamp(18px,4vw,56px); display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); background:#202923; color:#fff; }
.metrics-band article { min-height:112px; padding:22px 16px; border-right:1px solid #425048; }.metrics-band article:last-child { border-right:0; }
.metrics-band span { display:block; color:#b9c6bf; font-size:.76rem; text-transform:uppercase; }.metrics-band strong { display:block; margin-top:9px; font-size:1.8rem; }
.content-band,.users-band { padding:34px clamp(18px,4vw,56px); border-bottom:1px solid var(--line); }
.content-band:nth-of-type(even) { background:#fff; }
.split-heading { display:flex; align-items:flex-end; justify-content:space-between; gap:20px; margin-bottom:20px; }.split-heading code { max-width:520px; padding:8px 10px; background:#edf2f8; border:1px solid var(--line); overflow-wrap:anywhere; }
.funnel-grid { display:grid; grid-template-columns:repeat(7,minmax(0,1fr)); gap:1px; border:1px solid var(--line); background:var(--line); }.funnel-grid article { min-width:0; min-height:154px; padding:15px; background:#fff; }.funnel-grid span,.formula-stack span { display:block; color:var(--muted); font-size:.7rem; font-weight:800; text-transform:uppercase; }.funnel-grid strong { display:block; margin:10px 0; font-size:1.65rem; }.funnel-grid p { margin:0; color:var(--muted); font-size:.76rem; overflow-wrap:anywhere; }
.method-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; margin-bottom:12px; }.method-grid article { min-height:126px; padding:14px; border-top:3px solid var(--teal); background:#fff; }.method-grid span { color:var(--muted); font-size:.7rem; font-weight:800; }.method-grid p { margin:8px 0 0; color:var(--muted); font-size:.8rem; }
.evidence-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; }.evidence-grid article { min-height:158px; padding:17px; border:1px solid var(--line); background:#fff; }.evidence-grid p { margin-bottom:9px; font-size:.86rem; }
.formula-stack { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:10px; }.formula-stack article { min-width:0; padding:14px; border:1px solid var(--line); background:#edf2f8; }.formula-stack code { display:block; margin-top:8px; white-space:normal; overflow-wrap:anywhere; }
.example-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:10px; }.example-grid article { min-height:130px; padding:16px; border:1px solid var(--line); border-left:4px solid var(--blue); background:#fff; }.example-grid article:last-child { border-left-color:var(--amber); }.example-grid p { margin:6px 0; font-size:.84rem; }.example-grid strong { overflow-wrap:anywhere; }
.outcome-list { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:8px; margin-top:12px; }.outcome-list article { min-height:150px; padding:14px; border:1px solid var(--line); background:#fff; }.outcome-list strong { display:block; margin:7px 0; font-size:1.45rem; }.outcome-list p { margin:0; color:var(--muted); font-size:.78rem; }
.boundary-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); border:1px solid var(--line); background:var(--line); gap:1px; }.boundary-grid article { min-height:180px; padding:18px; background:#fff; }.boundary-grid ul { margin:12px 0 0; padding-left:18px; }.boundary-grid li { margin:7px 0; }
.boundary-statement { margin:14px 0 0; padding-left:12px; border-left:3px solid var(--violet); color:var(--muted); }
.muted { color:var(--muted); }.quiet-badge { padding:5px 8px; border:1px solid var(--amber); color:#7c460a; background:#fff5e8; border-radius:999px; font-size:.76rem; font-weight:800; }
.diagnostic-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; }.diagnostic-grid article { min-height:120px; padding:16px; background:#fff; border:1px solid var(--line); border-radius:6px; }.diagnostic-grid strong { display:block; margin:8px 0; font-size:1.6rem; }.diagnostic-grid p { margin:0; color:var(--muted); font-size:.82rem; }
.chart-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }.chart-grid article { min-width:0; min-height:260px; padding:16px; background:#fff; border:1px solid var(--line); border-radius:6px; }.chart-grid .wide { grid-column:1 / -1; min-height:310px; }
.bar-chart { min-height:210px; display:flex; flex-direction:column; gap:8px; justify-content:center; }.bar-row { display:grid; grid-template-columns:minmax(92px,150px) 1fr 52px; align-items:center; gap:9px; font-size:.78rem; }.bar-track { height:12px; background:#e7ece9; }.bar-fill { height:100%; background:var(--blue); }.bar-row:nth-child(3n+2) .bar-fill { background:var(--teal); }.bar-row:nth-child(3n) .bar-fill { background:var(--amber); }
.timeline-chart { min-height:250px; display:grid; grid-template-columns:repeat(30,minmax(10px,1fr)); align-items:end; gap:4px; padding-top:20px; border-bottom:1px solid var(--line); overflow-x:auto; }.step-column { min-width:10px; height:220px; display:flex; flex-direction:column; justify-content:flex-end; gap:2px; position:relative; }.step-column i { display:block; min-height:1px; }.step-column .exposure { background:var(--blue); }.step-column .engagement { background:var(--teal); }.step-column span { position:absolute; bottom:-20px; width:100%; text-align:center; color:var(--muted); font-size:.58rem; }
.users-band { background:#fff; }.filters { display:grid; grid-template-columns:2fr repeat(3,minmax(140px,1fr)); gap:10px; margin-bottom:14px; }.filters label span { display:block; margin-bottom:5px; color:var(--muted); font-size:.75rem; font-weight:700; }.filters input,.filters select { width:100%; min-height:40px; padding:8px 10px; border:1px solid #bfcac4; border-radius:5px; background:#fff; color:var(--ink); }
.table-wrap { width:100%; overflow:auto; border:1px solid var(--line); }.table-wrap table { width:100%; min-width:1120px; border-collapse:collapse; table-layout:fixed; }.table-wrap th,.table-wrap td { padding:11px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; overflow-wrap:anywhere; }.table-wrap th { position:sticky; top:0; z-index:1; background:#edf2ef; color:#4d5b54; font-size:.74rem; }.table-wrap td { font-size:.78rem; }.table-wrap tbody tr { cursor:pointer; }.table-wrap tbody tr:hover { background:#f1f7f4; }.profile-name { display:block; font-weight:800; }.profile-id,.mini { color:var(--muted); font-size:.72rem; }.status { display:inline-flex; margin-bottom:4px; padding:3px 6px; border-radius:999px; background:#e9effc; color:#244f9e; font-weight:800; }.status.provider_failed { background:#fdeaea; color:#9d2d2d; }.status.background_content { background:#fff0dd; color:#8b4f08; }.status.like,.status.comment,.status.share { background:#e6f5ef; color:#08644f; }.status.ignore { background:#ecefed; color:#4e5b54; }
.user-detail { min-height:120px; margin-top:12px; padding:16px; border:1px solid var(--line); border-left:4px solid var(--violet); background:#fafbfa; overflow-wrap:anywhere; }.detail-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; }.detail-grid div { padding:9px; background:#fff; border:1px solid var(--line); }.detail-grid span { display:block; color:var(--muted); font-size:.7rem; }.detail-grid strong { display:block; margin-top:4px; font-size:.82rem; }.trace-note { margin-top:12px; padding:12px; border:1px solid #d9d1f1; background:#f4f1fc; }.trace-note > strong { display:block; margin-bottom:5px; }.trace-note ul { margin:8px 0 0; padding-left:18px; }.trace-evidence { margin:12px 0; }.trace-evidence div { background:#fff; }
.limitations-band { padding:28px clamp(18px,4vw,56px); display:grid; grid-template-columns:240px 1fr; gap:24px; background:#fff8ed; border-bottom:1px solid #ead7bd; }.limitations-band ul { margin:0; padding-left:20px; }.limitations-band li { margin:7px 0; }
footer { padding:24px clamp(18px,4vw,56px); display:flex; gap:18px; flex-wrap:wrap; background:#fff; }
@media (max-width:1100px) { .funnel-grid { grid-template-columns:repeat(4,minmax(0,1fr)); }.method-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }.outcome-list { grid-template-columns:repeat(3,minmax(0,1fr)); } }
@media (max-width:900px) { .target-band { grid-template-columns:1fr; }.object-flow { grid-template-columns:1fr; }.object-flow i { transform:rotate(90deg); justify-self:center; }.metrics-band { grid-template-columns:repeat(2,1fr); }.metrics-band article { border-bottom:1px solid #425048; }.boundary-grid,.diagnostic-grid,.evidence-grid { grid-template-columns:1fr 1fr; }.filters { grid-template-columns:1fr 1fr; }.detail-grid { grid-template-columns:1fr 1fr; } }
@media (max-width:600px) { .topbar,.split-heading { align-items:flex-start; flex-direction:column; }.target-band,.content-band,.users-band { padding-top:24px; padding-bottom:24px; }.target-facts,.metrics-band,.funnel-grid,.method-grid,.evidence-grid,.formula-stack,.example-grid,.outcome-list,.boundary-grid,.diagnostic-grid,.chart-grid,.filters,.detail-grid { grid-template-columns:1fr; }.chart-grid .wide { grid-column:auto; }.metrics-band article { min-height:86px; }.limitations-band { grid-template-columns:1fr; }.downloads { width:100%; }.downloads a { flex:1; justify-content:center; }.inline-actions { align-items:flex-start; flex-direction:column; } }
"""


_REPORT_JS = r"""
const payload = JSON.parse(document.getElementById('final-research-payload').textContent);
const users = payload.users;
const tracesById = new Map(payload.user_traces.map((trace) => [trace.user_id, trace]));
const byId = (id) => document.getElementById(id);
const text = (value) => value === null || value === undefined || value === '' ? '—' : String(value);
const pct = (value) => value === null || value === undefined ? '—' : Number(value).toFixed(3);

function renderFunnel() {
  const root = byId('run-funnel');
  payload.run_funnel.forEach((stage, index) => {
    const article = document.createElement('article');
    const key = document.createElement('span'); key.textContent = `${String(index + 1).padStart(2, '0')} · ${stage.label}`;
    const count = document.createElement('strong'); count.textContent = Number(stage.count).toLocaleString();
    const description = document.createElement('p'); description.textContent = stage.description;
    article.append(key, count, description); root.appendChild(article);
  });
}

function renderMethodology() {
  const root = byId('methodology-flow');
  payload.methodology_flow.forEach((stage, index) => {
    const article = document.createElement('article');
    const number = document.createElement('span'); number.textContent = String(index + 1).padStart(2, '0');
    const title = document.createElement('h3'); title.textContent = stage.title;
    const summary = document.createElement('p'); summary.textContent = stage.summary;
    article.append(number, title, summary); root.appendChild(article);
  });
  byId('target-video-role').textContent = payload.video_usage.target_video_role;
  byId('background-video-role').textContent = payload.video_usage.background_video_role;
  const sampling = payload.sampling_explanation;
  byId('sampling-method').textContent = `${sampling.quota_method} ${sampling.deduplication_and_refill}`;
  byId('sampling-counts').textContent = Object.entries(sampling.source_scope_counts).map(([scope, count]) => `${scope}: ${count}`).join(' · ');
  byId('comment-network').textContent = payload.comment_network_explanation;
  byId('holdout-projection').textContent = sampling.holdout_safe_projection;
}

function renderExample(id, example) {
  const root = byId(id);
  if (!example) { root.textContent = '当前运行没有可展示记录'; root.classList.add('muted'); return; }
  const user = document.createElement('strong'); user.textContent = example.user_id;
  const values = document.createElement('p'); values.textContent = `score ${pct(example.recommendation_score)} · draw ${pct(example.random_draw)} · ${example.outcome}`;
  const explanation = document.createElement('p'); explanation.className = 'muted'; explanation.textContent = example.explanation;
  root.append(user, values, explanation);
}

function renderRecommendation() {
  const recommendation = payload.recommendation_explanation;
  byId('static-formula').textContent = recommendation.static_formula;
  byId('dynamic-formula').textContent = recommendation.dynamic_formula;
  renderExample('seed-example', recommendation.seed_example);
  renderExample('non-seed-example', recommendation.non_seed_example);
}

function renderDecisionExplanation() {
  const batch = payload.batch_explanation;
  if (batch.batch_count > 0) {
    byId('batch-heading').textContent = `${batch.batch_count} 个固定批次`;
    byId('batch-method').textContent = `${batch.batch_count} 个批次；Batch ${batch.seed_batch} 为 seeds，Batch ${batch.non_seed_batches[0]}–${batch.non_seed_batches[1]} 为 non-seeds。${batch.assignment_method}`;
  } else {
    byId('batch-heading').textContent = 'Provider runtime 未执行';
    byId('batch-method').textContent = batch.assignment_method;
  }
  byId('decision-fields').textContent = `${payload.decision_contract.fields.join(' / ')}；action = ${payload.decision_contract.action_values.join(' / ')}`;
  byId('decision-recoverability').textContent = payload.decision_contract.prompt_recoverability;
  const neighbor = payload.dynamic_neighbor_summary;
  byId('neighbor-summary').textContent = `${neighbor.explanation} 正向邻居用户 ${neighbor.users_with_positive_engaged_neighbor_count}，最大邻居数 ${neighbor.maximum_engaged_neighbor_count}，实际最大 boost ${pct(neighbor.maximum_actual_boost)}。`;
  const root = byId('outcome-explanations');
  payload.outcome_explanations.forEach((outcome) => {
    const article = document.createElement('article');
    const action = document.createElement('h3'); action.textContent = outcome.action;
    const count = document.createElement('strong'); count.textContent = Number(outcome.count).toLocaleString();
    const explanation = document.createElement('p'); explanation.textContent = outcome.explanation;
    article.append(action, count, explanation); root.appendChild(article);
  });
}

function setMetrics() {
  byId('metric-exposures').textContent = users.filter((row) => row.exposure_status === 'target_exposed').length;
  byId('metric-engagements').textContent = users.filter((row) => ['like','comment','share'].includes(row.result_status)).length;
  byId('metric-background').textContent = users.filter((row) => row.result_status === 'background_content').length;
  byId('metric-failed').textContent = users.filter((row) => row.result_status === 'provider_failed').length;
}

function fillList(id, values) {
  const root = byId(id);
  values.forEach((value) => { const item = document.createElement('li'); item.textContent = value; root.appendChild(item); });
}

function renderDiagnostics() {
  const holdout = payload.diagnostics.holdout;
  const coverage = holdout.observed_participant_signal_coverage || {};
  const items = [
    ['真实参与用户', holdout.observed_holdout_participant_count, 'Holdout 中已观测到的 comment / reply 用户'],
    ['模型 Top20', holdout.model_recommended_user_count, '静态 holdout-safe 推荐分数最高用户'],
    ['交集命中', holdout.intersection_count, '仅用于稀疏信号诊断'],
    ['非目标历史信号', coverage.with_non_target_history || 0, '真实参与用户中的历史覆盖'],
    ['网络连接信号', coverage.with_network_connection || 0, '真实参与用户中的网络覆盖'],
    ['标签亲和信号', coverage.with_historical_tag_affinity || 0, '真实参与用户中的标签覆盖'],
    ['Seed users', payload.sample_summary.seed_count, payload.diagnostics.seed_method],
    ['Source scopes', Object.keys(payload.sample_summary.source_scope_counts || {}).length, '固定随机种子的配额样本分布'],
  ];
  const root = byId('diagnostic-grid');
  items.forEach(([label, value, note]) => {
    const article = document.createElement('article');
    const h3 = document.createElement('h3'); h3.textContent = label;
    const strong = document.createElement('strong'); strong.textContent = text(value);
    const p = document.createElement('p'); p.textContent = note;
    article.append(h3, strong, p); root.appendChild(article);
  });
}

function renderBars(id, rows) {
  const root = byId(id);
  if (!rows.length) { root.textContent = '当前运行无可展示记录'; root.classList.add('muted'); return; }
  const maximum = Math.max(1, ...rows.map((row) => Number(row.value) || 0));
  rows.forEach((row) => {
    const line = document.createElement('div'); line.className = 'bar-row';
    const label = document.createElement('span'); label.textContent = row.label;
    const track = document.createElement('div'); track.className = 'bar-track';
    const fill = document.createElement('div'); fill.className = 'bar-fill'; fill.style.width = `${(Number(row.value) / maximum) * 100}%`; track.appendChild(fill);
    const value = document.createElement('strong'); value.textContent = text(row.value);
    line.append(label, track, value); root.appendChild(line);
  });
}

function renderTimeline() {
  const root = byId('trend-chart');
  const rows = payload.trends;
  if (!rows.length) { root.textContent = 'Offline baseline 未执行 provider runtime'; root.classList.add('muted'); return; }
  const maximum = Math.max(1, ...rows.flatMap((row) => [Number(row.target_exposures) || 0, Number(row.engagements) || 0]));
  rows.forEach((row) => {
    const column = document.createElement('div'); column.className = 'step-column'; column.title = `Step ${row.time_step}: exposures ${row.target_exposures}, engagements ${row.engagements}`;
    const exposure = document.createElement('i'); exposure.className = 'exposure'; exposure.style.height = `${(Number(row.target_exposures) / maximum) * 190}px`;
    const engagement = document.createElement('i'); engagement.className = 'engagement'; engagement.style.height = `${(Number(row.engagements) / maximum) * 190}px`;
    const label = document.createElement('span'); label.textContent = row.time_step;
    column.append(exposure, engagement, label); root.appendChild(column);
  });
}

function populateFilters() {
  const results = [...new Set(users.map((row) => row.result_status))].sort();
  const scopes = [...new Set(users.map((row) => row.sample_source_scope))].sort();
  [[byId('result-filter'), results], [byId('scope-filter'), scopes]].forEach(([select, values]) => {
    values.forEach((value) => { const option = document.createElement('option'); option.value = value; option.textContent = value; select.appendChild(option); });
  });
}

function rowSearchText(row) {
  return [row.user_id,row.nickname,row.bio,row.signature,row.sample_source_scope,row.reason,JSON.stringify(row.historical_tags),JSON.stringify(row.latent_attributes)].join(' ').toLowerCase();
}

function renderUsers() {
  const query = byId('user-search').value.trim().toLowerCase();
  const result = byId('result-filter').value;
  const scope = byId('scope-filter').value;
  const seed = byId('seed-filter').value;
  const filtered = users.filter((row) => (!query || rowSearchText(row).includes(query)) && (!result || row.result_status === result) && (!scope || row.sample_source_scope === scope) && (!seed || String(row.is_seed) === seed));
  byId('visible-user-count').textContent = `${filtered.length.toLocaleString()} / ${users.length.toLocaleString()}`;
  const body = byId('user-table-body'); body.replaceChildren();
  filtered.forEach((row) => {
    const tr = document.createElement('tr'); tr.tabIndex = 0;
    const profile = document.createElement('td');
    const name = document.createElement('span'); name.className = 'profile-name'; name.textContent = row.nickname || row.user_id;
    const id = document.createElement('span'); id.className = 'profile-id'; id.textContent = row.user_id;
    const bio = document.createElement('div'); bio.className = 'mini'; bio.textContent = [row.bio,row.signature].filter(Boolean).join(' · ') || '无公开简介';
    profile.append(name,id,bio);
    const source = document.createElement('td'); source.textContent = `${row.sample_source_scope || 'unspecified'} · ${row.is_seed ? 'seed' : 'non-seed'}`;
    const step = document.createElement('td'); step.textContent = text(row.assigned_step);
    const exposure = document.createElement('td'); exposure.textContent = `${pct(row.recommendation_score)} / ${pct(row.random_draw)}`;
    const outcome = document.createElement('td'); const badge = document.createElement('span'); badge.className = `status ${row.result_status}`; badge.textContent = row.result_status; const provider = document.createElement('div'); provider.className = 'mini'; provider.textContent = row.provider_status; outcome.append(badge,provider);
    const reason = document.createElement('td'); reason.textContent = row.reason || '—'; const confidence = document.createElement('div'); confidence.className = 'mini'; confidence.textContent = `confidence ${pct(row.confidence)}`; reason.appendChild(confidence);
    tr.append(profile,source,step,exposure,outcome,reason);
    tr.addEventListener('click', () => renderDetail(row)); tr.addEventListener('keydown', (event) => { if (event.key === 'Enter') renderDetail(row); });
    body.appendChild(tr);
  });
}

function renderDetail(row) {
  const root = byId('user-detail'); root.replaceChildren();
  const title = document.createElement('h3'); title.textContent = `${row.nickname || row.user_id} · Step ${text(row.assigned_step)} timeline`;
  const grid = document.createElement('div'); grid.className = 'detail-grid';
  const values = [
    ['User ID',row.user_id],['Exposure',row.exposure_status],['Result',row.result_status],['Provider',row.provider_status],
    ['Base network',pct(row.base_network_score)],['Dynamic network',pct(row.dynamic_network_score)],['Engaged neighbors',text(row.engaged_neighbor_count)],['Tag affinity',pct(row.historical_tag_affinity)],
    ['Activity proxy',pct(row.activity_score)],['Global influence',pct(row.global_influence_score)],['Local influence',pct(row.local_influence_score)],['Historical tags',row.historical_tags.join(', ') || '—'],
  ];
  values.forEach(([label,value]) => { const box = document.createElement('div'); const span = document.createElement('span'); span.textContent = label; const strong = document.createElement('strong'); strong.textContent = value; box.append(span,strong); grid.appendChild(box); });
  const latent = document.createElement('p'); latent.className = 'muted'; latent.textContent = `Latent experiment labels: ${JSON.stringify(row.latent_attributes)}`;
  const trace = tracesById.get(row.user_id);
  const traceNote = document.createElement('div'); traceNote.className = 'trace-note'; traceNote.dataset.testid = 'trace-context';
  const traceTitle = document.createElement('strong'); traceTitle.textContent = trace?.context_label || '重建的决策上下文';
  const recoverability = document.createElement('p'); recoverability.textContent = trace?.prompt_recoverability || '完整原始 Provider Prompt 不可恢复。';
  const evidence = document.createElement('div'); evidence.className = 'detail-grid trace-evidence'; evidence.dataset.testid = 'trace-evidence';
  Object.entries(trace?.persisted_evidence || {}).forEach(([label, value]) => {
    const box = document.createElement('div');
    const name = document.createElement('span'); name.textContent = label;
    const persisted = document.createElement('strong'); persisted.textContent = text(value);
    box.append(name, persisted); evidence.appendChild(box);
  });
  const unavailable = document.createElement('ul');
  (trace?.unrecoverable_peer_context_fields || []).forEach((field) => { const item = document.createElement('li'); item.textContent = field; unavailable.appendChild(item); });
  traceNote.append(traceTitle, evidence, recoverability, unavailable);
  root.append(title,grid,latent,traceNote);
}

renderFunnel();
renderMethodology();
renderRecommendation();
renderDecisionExplanation();
setMetrics();
fillList('observed-list', payload.observed_latent_boundary.observed_fields);
fillList('latent-list', payload.observed_latent_boundary.latent_fields);
fillList('limitations-list', payload.limitations);
renderDiagnostics();
renderTimeline();
renderBars('action-chart', payload.aggregates.action_distribution);
renderBars('scope-chart', payload.aggregates.scope_distribution);
renderBars('provider-chart', payload.aggregates.provider_failures.filter((row) => Number(row.value) > 0));
renderBars('neighbor-chart', payload.aggregates.dynamic_neighbor_signal);
populateFilters();
['user-search','result-filter','scope-filter','seed-filter'].forEach((id) => byId(id).addEventListener('input', renderUsers));
renderUsers();
if (users.length) renderDetail(users[0]);
"""
