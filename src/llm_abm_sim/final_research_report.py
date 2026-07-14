from __future__ import annotations

import csv
import json
import os
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .prompt_field_summary import JINJIANG_PROMPT_V2_PROFILE_FIELDS
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
FieldProvenance = Literal[
    "Direct Observed Profile Field",
    "Historical Behavioral Evidence",
    "Derived Proxy Metric",
    "Synthetic Experiment Label",
    "Runtime Simulation Result",
]
FieldUsageStage = Literal["Sampling", "Seed Selection", "Ranking", "LLM Prompt", "Report Only"]


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


class RankingReportDownloads(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report: str
    payload: str
    csv: str
    users_json: str
    manifest: str
    ranking_diagnostics: str
    ranking_ablation_csv: str
    ranking_sensitivity_csv: str


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
    sample_role: Literal["seed", "network_cohort", "ordinary"]
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


class FinalResearchRankingReportPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["final-research-ranking-report-payload-v3"] = "final-research-ranking-report-payload-v3"
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
    downloads: RankingReportDownloads
    limitations: list[str]
    users: list[RankingUserReportRow]

    @model_validator(mode="after")
    def _validate_field_lineage(self) -> FinalResearchRankingReportPayload:
        declared = [entry.field_name for entry in self.field_lineage]
        if len(declared) != len(set(declared)):
            raise ValueError("field lineage must declare each field exactly once")
        expected = _ranking_lineage_field_names()
        if set(declared) != expected:
            missing = sorted(expected - set(declared))
            extra = sorted(set(declared) - expected)
            raise ValueError(f"field lineage does not match ranking user fields; missing={missing}, extra={extra}")
        return self


@dataclass(frozen=True)
class FinalResearchReportSource:
    target_video: Mapping[str, object]
    users: Sequence[Mapping[str, object]]
    historical_tags_by_user: Mapping[str, Sequence[str]]
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
        payload = self._build_payload()
        user_records = [row.model_dump(mode="json") for row in payload.users]
        user_document = {
            "schema_version": (
                "final-research-ranking-users-v3"
                if isinstance(payload, FinalResearchRankingReportPayload)
                else "final-research-users-v1"
            ),
            "links": payload.downloads.model_dump(mode="json"),
            "users": user_records,
        }

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

    def _build_payload(self) -> FinalResearchReportPayload | FinalResearchRankingReportPayload:
        if self.source.ranking_runtime_summary is not None:
            return _build_ranking_report_payload(self.source)
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
                }
            ),
            diagnostics=FinalResearchDiagnostics(
                holdout=HoldoutDiagnostic.model_validate(diagnostic),
                seed_method="global top10 and holdout-safe local top10 union within the sample",
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
    def render_payload(payload: FinalResearchReportPayload | FinalResearchRankingReportPayload) -> str:
        if isinstance(payload, FinalResearchRankingReportPayload):
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
      <div><span class="eyebrow">FINAL RESEARCH · JINJIANG</span><h1>{escape(payload.title)}</h1></div>
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


def _build_ranking_report_payload(source: FinalResearchReportSource) -> FinalResearchRankingReportPayload:
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
    base_sample = _required_mapping(audit, "base_sample", "network sample audit")
    network_cohort = _required_mapping(audit, "network_cohort", "network sample audit")
    replacement = _required_mapping(audit, "ordinary_replacement", "network sample audit")
    final_sample = _required_mapping(audit, "final_sample", "network sample audit")
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
        sample_role: Literal["seed", "network_cohort", "ordinary"] = (
            "seed" if is_seed else "network_cohort" if is_network_cohort else "ordinary"
        )
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
        ),
        run_funnel=[
            _funnel_stage(
                "processed_users",
                "Processed users scored",
                _as_int(source.offline_score_summary.get("user_count")),
                "权威 processed variant 中完成 holdout-safe 离线评分的用户。",
            ),
            _funnel_stage(
                "base_sample",
                "Base Sample",
                _as_int(base_sample.get("count")),
                "按 source scope 配额、去重与固定随机种子形成。",
            ),
            _funnel_stage("seeds", "Seeds", _as_int(audit.get("seed_count")), "从 Base Sample 选出的 seed union。"),
            _funnel_stage(
                "network_cohort",
                "Network Cohort",
                _as_int(network_cohort.get("count")),
                "Historical Set 评论网络中的 seed 直接邻居。",
            ),
            _funnel_stage(
                "final_sample",
                "Network-Augmented Research Sample",
                len(rows),
                "保持总量不变并替换等量普通用户后的最终样本。",
            ),
            _funnel_stage(
                "target_exposures",
                "Target exposures",
                _as_int(runtime_counts.get("target_exposures")),
                "实际进入 Delivery Capacity 并调用 Decision Adapter 的用户。",
            ),
            _funnel_stage(
                "provider_decisions",
                "Provider decisions",
                _as_int(runtime_counts.get("decisions")),
                "成功返回结构化 Decision 的 provider 调用。",
            ),
            _funnel_stage(
                "provider_failed",
                "Provider failed",
                _as_int(runtime_counts.get("provider_failed")),
                "重试耗尽后保留的独立失败状态。",
            ),
            _funnel_stage(
                "below_delivery_capacity",
                "Below delivery capacity",
                _as_int(runtime_counts.get("below_delivery_capacity")),
                "最终批次结束仍未获得目标曝光，不等于 ignore。",
            ),
        ],
        sample_comparison=RankingSampleComparison(
            base_sample_count=_as_int(base_sample.get("count")),
            final_sample_count=_as_int(final_sample.get("count")),
            seed_count=_as_int(audit.get("seed_count")),
            network_cohort_count=_as_int(network_cohort.get("count")),
            network_cohort_added_count=len(_required_list(network_cohort, "added_user_ids", "network cohort")),
            replacement_count=_as_int(replacement.get("count")),
            base_source_scope_counts=_int_mapping(base_sample.get("source_scope_counts")),
            final_source_scope_counts=_int_mapping(final_sample.get("source_scope_counts")),
        ),
        field_lineage=lineage,
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
        "interest_tags",
        "follower_count",
        "following_count",
        "video_count",
        *(f"target_video.{field}" for field in FinalResearchTargetVideo.model_fields),
        "ranking_rounds.candidates.user_id",
    }
    historical = {
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


def _render_ranking_report(payload: FinalResearchRankingReportPayload) -> str:
    target = payload.target_video
    target_url = escape(target.video_url, quote=True)
    download_csv = escape(payload.downloads.csv, quote=True)
    download_users_json = escape(payload.downloads.users_json, quote=True)
    download_payload = escape(payload.downloads.payload, quote=True)
    download_manifest = escape(payload.downloads.manifest, quote=True)
    download_diagnostics = escape(payload.downloads.ranking_diagnostics, quote=True)
    download_ablation = escape(payload.downloads.ranking_ablation_csv, quote=True)
    download_sensitivity = escape(payload.downloads.ranking_sensitivity_csv, quote=True)
    funnel_html = "".join(
        f"<article><strong>{stage.count:,}</strong><span>{escape(stage.label)}</span><p>{escape(stage.description)}</p></article>"
        for stage in payload.run_funnel
    )
    lineage_html = "".join(
        "<tr>"
        f"<td><code>{escape(entry.field_name)}</code></td>"
        f"<td>{escape(entry.provenance)}</td>"
        f"<td>{escape(', '.join(entry.usage_stages))}</td>"
        "</tr>"
        for entry in payload.field_lineage
    )
    users_html = "".join(
        "<tr>"
        f"<td><strong>{escape(row.nickname or row.user_id)}</strong><small>{escape(row.user_id)}</small></td>"
        f"<td>{escape(row.sample_role)}<small>{escape(row.sample_source_scope)}</small></td>"
        f"<td>{row.latest_ranking_time_step} / {row.latest_ranking_position}</td>"
        f"<td>{row.recommendation_score:.6f}</td>"
        f'<td><span class="status">{escape(row.result_status)}</span><small>{escape(row.provider_status)}</small></td>'
        f"<td>{escape(row.reason)}</td>"
        "</tr>"
        for row in payload.users
    )
    scope_rows = "".join(
        f"<tr><td>{escape(scope)}</td><td>{payload.sample_comparison.base_source_scope_counts.get(scope, 0)}</td>"
        f"<td>{payload.sample_comparison.final_source_scope_counts.get(scope, 0)}</td></tr>"
        for scope in sorted(
            set(payload.sample_comparison.base_source_scope_counts)
            | set(payload.sample_comparison.final_source_scope_counts)
        )
    )
    payload_json = safe_user_json(payload, indent=None).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(payload.title)}</title>
  <style>
    :root {{ color-scheme:light; --ink:#18201c; --muted:#5b6861; --line:#d7dfda; --paper:#f7f9f7; --accent:#075f4c; --warm:#9c5b16; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; color:var(--ink); background:white; font:15px/1.5 system-ui,sans-serif; }}
    main {{ width:min(1180px,100%); margin:auto; }} header,section,footer {{ padding:28px clamp(18px,4vw,46px); border-bottom:1px solid var(--line); }}
    header {{ display:flex; justify-content:space-between; gap:24px; align-items:end; background:#eaf1ed; }} h1,h2,p {{ margin-top:0; }} h1 {{ font-size:clamp(1.8rem,4vw,3.2rem); margin-bottom:8px; }}
    a {{ color:var(--accent); }} .downloads {{ display:flex; flex-wrap:wrap; gap:12px; }} .eyebrow,small {{ display:block; color:var(--muted); font-size:.78rem; }}
    .target {{ display:grid; grid-template-columns:2fr 1fr; gap:28px; }} .funnel {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:12px; }}
    .funnel article {{ padding:16px; border:1px solid var(--line); border-radius:6px; background:var(--paper); }} .funnel strong {{ display:block; font-size:1.6rem; }}
    .funnel span {{ font-weight:700; }} .funnel p {{ color:var(--muted); font-size:.82rem; margin:8px 0 0; }}
    .table-wrap {{ width:100%; overflow:auto; border:1px solid var(--line); }} table {{ width:100%; min-width:820px; border-collapse:collapse; }}
    th,td {{ padding:10px 12px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; overflow-wrap:anywhere; }} th {{ background:var(--paper); position:sticky; top:0; }}
    code {{ color:var(--accent); }} .status {{ color:var(--warm); font-weight:700; }} footer {{ display:flex; flex-wrap:wrap; gap:16px; }}
    @media (max-width:720px) {{ header,.target {{ display:block; }} .downloads {{ margin-top:18px; }} }}
  </style>
</head>
<body>
<main data-testid="final-research-ranking-report">
  <header><div><span class="eyebrow">TARGET DELIVERY RANKING · PAYLOAD V3</span><h1>{escape(payload.title)}</h1><p>{escape(payload.run.ranking_formula)}</p></div><nav class="downloads"><a href="{download_csv}">CSV</a><a href="{download_users_json}">JSON</a><a href="{download_payload}">Payload</a><a href="{download_manifest}">Manifest</a></nav></header>
  <section class="target"><div><span class="eyebrow">TargetVideo · {escape(target.video_id)}</span><h2>{escape(target.caption)}</h2><p>{escape(" ".join("#" + tag.lstrip("#") for tag in target.hashtags))}</p><a href="{target_url}">查看真实视频入口</a></div><dl><dt>研究用户</dt><dd>{payload.run.sample_size:,}</dd><dt>批次</dt><dd>{payload.run.horizon}</dd><dt>每轮容量</dt><dd>{payload.run.delivery_capacity}</dd></dl></section>
  <section data-testid="ranking-funnel-section"><h2>运行漏斗</h2><div class="funnel">{funnel_html}</div></section>
  <section><h2>Base Sample 与最终样本</h2><p>Seeds {payload.sample_comparison.seed_count}，Network Cohort {payload.sample_comparison.network_cohort_count}，替换普通用户 {payload.sample_comparison.replacement_count}。</p><div class="table-wrap"><table><thead><tr><th>Source scope</th><th>Base Sample</th><th>Final Sample</th></tr></thead><tbody>{scope_rows}</tbody></table></div></section>
  <section data-testid="field-lineage-section"><h2>Field Lineage Matrix</h2><div class="table-wrap"><table><thead><tr><th>Field</th><th>Field Provenance</th><th>Field Usage Stage</th></tr></thead><tbody>{lineage_html}</tbody></table></div></section>
  <section data-testid="ranking-users-section"><h2>完整用户表</h2><p>{len(payload.users):,} 条唯一用户记录；未曝光、ignore 与 provider failure 保持独立状态。</p><div class="table-wrap"><table><thead><tr><th>User</th><th>Sample role</th><th>Latest batch / rank</th><th>Score</th><th>Result</th><th>Reason</th></tr></thead><tbody>{users_html}</tbody></table></div></section>
  <footer><a href="{download_diagnostics}">Ranking diagnostics</a><a href="{download_ablation}">Ablation CSV</a><a href="{download_sensitivity}">Sensitivity CSV</a></footer>
</main>
<script id="final-research-ranking-payload" type="application/json">{payload_json}</script>
</body>
</html>
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
        payload = FinalResearchRankingReportPayload.model_validate(payload_document)
        _validate_ranking_rebuild_evidence(run_path, manifest, payload)
        return _publish_report_files(run_path, payload)

    summary_path = run_path / "runtime_summary.json"
    if not summary_path.is_file():
        raise FileNotFoundError(f"Final Research rebuild requires {summary_path.name}")
    runtime_summary = _read_json_object(summary_path)
    base_payload = _parse_report_payload(payload_document)
    _validate_rebuild_evidence(run_path, manifest, base_payload, runtime_summary)

    payload = _build_explainable_payload(base_payload, runtime_summary)
    return _publish_report_files(run_path, payload)


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
                    "按 source scope 配额、去重与稳定补齐形成研究样本。",
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
                _method_stage("sampling", "用户筛选", "按 source scope 配额抽样，去重后使用稳定顺序补齐。"),
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
                "quota_method": "按 source_challenge_name 分配 Research Sample 配额。",
                "deduplication_and_refill": "用户按 user_id 去重；配额不足时使用稳定候选顺序补齐到固定样本数。",
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
    payload: FinalResearchRankingReportPayload,
) -> None:
    if manifest.get("manifest_version") != FINAL_RESEARCH_RANKING_RUNTIME_VERSION:
        raise ValueError("unsupported Target Delivery Ranking artifact manifest schema")
    artifacts = _required_mapping(manifest, "artifacts", "artifact manifest")
    required_artifacts = {
        "final_research_report": "report.html",
        "final_research_report_payload": "final_research_report_payload.json",
        "final_research_users_csv": "final_research_users.csv",
        "final_research_users_json": "final_research_users.json",
        "network_augmented_sample_audit": "network_augmented_sample_audit.json",
        "ranking_runtime_candidates": "ranking_runtime_candidates.csv",
        "ranking_runtime_outcomes": "ranking_runtime_outcomes.csv",
        "ranking_runtime_steps": "ranking_runtime_steps.csv",
        "ranking_runtime_summary": "ranking_runtime_summary.json",
        "ranking_diagnostics": "ranking_diagnostics.json",
        "ranking_diagnostics_summary": "ranking_diagnostics_summary.json",
    }
    for name, expected_path in required_artifacts.items():
        if artifacts.get(name) != expected_path:
            raise ValueError(f"artifact manifest has invalid {name} path")
    artifact_paths: dict[str, Path] = {}
    for name, relative_path in artifacts.items():
        if not isinstance(name, str) or not isinstance(relative_path, str):
            raise ValueError("artifact manifest names and paths must be strings")
        artifact_paths[name] = _artifact_path(run_path, relative_path, name)

    user_ids = [row.user_id for row in payload.users]
    if len(user_ids) != len(set(user_ids)):
        raise ValueError("ranking report payload contains duplicate user_id")
    if payload.run.sample_size != len(user_ids):
        raise ValueError("ranking report payload user count does not match run.sample_size")
    actual_scope_counts = dict(sorted(Counter(row.sample_source_scope for row in payload.users).items()))
    if dict(sorted(payload.sample_comparison.final_source_scope_counts.items())) != actual_scope_counts:
        raise ValueError("ranking report final source scope distribution does not match users")

    audit = _read_json_object(artifact_paths["network_augmented_sample_audit"])
    if audit.get("schema_version") != "network-augmented-sample-audit-v1":
        raise ValueError("unsupported network augmented sample audit schema")
    base_sample = _required_mapping(audit, "base_sample", "network sample audit")
    final_sample = _required_mapping(audit, "final_sample", "network sample audit")
    network_cohort = _required_mapping(audit, "network_cohort", "network sample audit")
    replacement = _required_mapping(audit, "ordinary_replacement", "network sample audit")
    base_ids = [str(value) for value in _required_list(base_sample, "user_ids", "base sample")]
    final_ids = [str(value) for value in _required_list(final_sample, "user_ids", "final sample")]
    cohort_ids = [str(value) for value in _required_list(network_cohort, "user_ids", "network cohort")]
    seed_ids = [str(value) for value in _required_list(audit, "seed_user_ids", "network sample audit")]
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
        "seed_count": _as_int(audit.get("seed_count")),
        "network_cohort_count": _as_int(network_cohort.get("count")),
        "network_cohort_added_count": len(_required_list(network_cohort, "added_user_ids", "network cohort")),
        "replacement_count": _as_int(replacement.get("count")),
    }
    comparison_document = payload.sample_comparison.model_dump(mode="json")
    for key, expected in comparison_expectations.items():
        if comparison_document[key] != expected:
            raise ValueError(f"ranking report sample comparison {key} does not match audit")
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
    if user_document.get("schema_version") != "final-research-ranking-users-v3":
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
    payload: FinalResearchReportPayload | FinalResearchRankingReportPayload,
) -> Path:
    payload_path = run_path / FINAL_RESEARCH_REPORT_ARTIFACTS["final_research_report_payload"]
    report_path = run_path / FINAL_RESEARCH_REPORT_ARTIFACTS["final_research_report"]
    payload_text = safe_user_json(payload) + "\n"
    html_text = FinalResearchReportWriter.render_payload(payload)
    payload_model = (
        FinalResearchRankingReportPayload
        if isinstance(payload, FinalResearchRankingReportPayload)
        else FinalResearchReportPayload
    )
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
