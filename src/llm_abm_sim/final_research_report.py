from __future__ import annotations

import csv
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .safe_serialization import safe_json, safe_user_data, safe_user_json

FINAL_RESEARCH_REPORT_ARTIFACTS = {
    "final_research_report": "report.html",
    "final_research_report_payload": "final_research_report_payload.json",
    "final_research_users_csv": "final_research_users.csv",
    "final_research_users_json": "final_research_users.json",
}

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


class FinalResearchReportPayload(BaseModel):
    """Independent payload for the Final Research static report."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "final-research-report-payload-v1"
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
    runtime_enabled: bool = False


class FinalResearchReportWriter:
    """Build and write all Final Research human and machine-readable artifacts."""

    def __init__(self, source: FinalResearchReportSource) -> None:
        self.source = source

    def write(self, output_dir: str | Path) -> Path:
        output_path = Path(output_dir)
        payload = self._build_payload()
        user_records = [row.model_dump(mode="json") for row in payload.users]
        user_document = {
            "schema_version": "final-research-users-v1",
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
        (output_path / FINAL_RESEARCH_REPORT_ARTIFACTS["final_research_report_payload"]).write_text(
            safe_user_json(payload) + "\n",
            encoding="utf-8",
        )
        report_path = output_path / FINAL_RESEARCH_REPORT_ARTIFACTS["final_research_report"]
        report_path.write_text(self._render_html(payload), encoding="utf-8")
        (output_path / "artifact_manifest.json").write_text(
            safe_json(dict(self.source.artifact_manifest)) + "\n",
            encoding="utf-8",
        )
        return report_path

    def _build_payload(self) -> FinalResearchReportPayload:
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
        return FinalResearchReportPayload(
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
        action_counts = Counter(row.result_status for row in rows)
        scope_counts = Counter(row.sample_source_scope or "unspecified" for row in rows)
        provider_by_step = Counter(
            row.assigned_step
            for row in rows
            if row.result_status == "provider_failed" and row.assigned_step is not None
        )
        neighbor_by_step: dict[int, list[int]] = {}
        for row in rows:
            if row.assigned_step is None or row.engaged_neighbor_count is None:
                continue
            neighbor_by_step.setdefault(row.assigned_step, []).append(row.engaged_neighbor_count)
        return FinalResearchAggregates(
            action_distribution=[
                AggregateRow(label=label, value=count) for label, count in sorted(action_counts.items())
            ],
            scope_distribution=[
                AggregateRow(label=label, value=count) for label, count in sorted(scope_counts.items())
            ],
            provider_failures=[
                AggregateRow(label=f"Step {step}", value=provider_by_step.get(step, 0))
                for step in range(_as_int(self.source.config.get("horizon")))
            ],
            dynamic_neighbor_signal=[
                AggregateRow(
                    label=f"Step {step}",
                    value=round(sum(values) / len(values), 4) if values else 0.0,
                )
                for step, values in sorted(neighbor_by_step.items())
            ],
        )

    def _write_csv(self, path: Path, rows: Sequence[UserReportRow]) -> None:
        safe_rows = safe_user_data([row.csv_row() for row in rows])
        if not isinstance(safe_rows, list):  # pragma: no cover
            raise TypeError("safe user rows must remain a list")
        fieldnames = list(UserReportRow.model_fields)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(safe_rows)

    def _render_html(self, payload: FinalResearchReportPayload) -> str:
        payload_json = safe_user_json(payload, indent=None).replace("</", "<\\/")
        target = payload.target_video
        target_url = escape(target.video_url, quote=True)
        hashtags = " ".join(f"#{tag.lstrip('#')}" for tag in target.hashtags)
        static_formula = (
            f"{payload.recommendation_model.network_weight:.2f} network + "
            f"{payload.recommendation_model.tag_affinity_weight:.2f} historical tag affinity"
        )
        dynamic_formula = f"min(1, base + {payload.recommendation_model.neighbor_boost:.2f} × engaged direct neighbors)"
        return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
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

    <section class="target-band" data-testid="target-video-section">
      <div class="target-copy">
        <span class="eyebrow">TargetVideo · {escape(target.video_id)}</span>
        <h2>{escape(target.caption)}</h2>
        <p class="tags">{escape(hashtags)}</p>
        <div class="inline-actions"><a class="primary-link" href="{target_url}" target="_blank" rel="noreferrer">查看真实视频入口</a><span>当前无可嵌入媒体文件</span></div>
      </div>
      <dl class="target-facts"><div><dt>来源 scope</dt><dd>{escape(target.source_challenge_name)}</dd></div><div><dt>样本用户</dt><dd>{len(payload.users):,}</dd></div><div><dt>推荐批次</dt><dd>{payload.run.horizon}</dd></div><div><dt>随机种子</dt><dd>{payload.run.random_seed}</dd></div></dl>
    </section>

    <section class="object-flow" data-testid="core-objects-section">
      <article><span>01</span><h3>TargetVideo</h3><p>真实 caption、hashtags 与查看入口</p></article>
      <i aria-hidden="true">→</i>
      <article><span>02</span><h3>ResearchUser</h3><p>真实观测画像与合成实验标签</p></article>
      <i aria-hidden="true">→</i>
      <article><span>03</span><h3>PlatformRecommendationModel</h3><p>网络信号、历史标签与动态邻居反馈</p></article>
    </section>

    <section class="metrics-band" data-testid="summary-metrics">
      <article><span>Target exposures</span><strong id="metric-exposures">0</strong></article>
      <article><span>Engagements</span><strong id="metric-engagements">0</strong></article>
      <article><span>Background</span><strong id="metric-background">0</strong></article>
      <article><span>Provider failed</span><strong id="metric-failed">0</strong></article>
      <article><span>Seed users</span><strong>{payload.sample_summary.seed_count}</strong></article>
    </section>

    <section class="content-band" data-testid="model-boundary-section">
      <div class="split-heading"><div><span class="eyebrow">RESEARCH CONTRACT</span><h2>推荐模型与字段边界</h2></div><code>{escape(static_formula)}</code></div>
      <div class="boundary-grid">
        <article><h3>Observed</h3><p>来源事实与可复算代理指标</p><ul id="observed-list"></ul></article>
        <article><h3>Latent</h3><p>只用于受控仿真实验</p><ul id="latent-list"></ul></article>
        <article><h3>Dynamic signal</h3><p><code>{escape(dynamic_formula)}</code></p><p class="muted">只影响尚未进入固定批次的直接邻居。</p></article>
      </div>
      <p class="boundary-statement">{escape(payload.observed_latent_boundary.statement)}</p>
    </section>

    <section class="content-band" data-testid="diagnostics-section">
      <div class="split-heading"><div><span class="eyebrow">DIAGNOSTICS</span><h2>样本、seed 与 Top20 holdout</h2></div><span class="quiet-badge">diagnostic only</span></div>
      <div class="diagnostic-grid" id="diagnostic-grid"></div>
    </section>

    <section class="content-band" data-testid="charts-section">
      <div class="split-heading"><div><span class="eyebrow">AGGREGATES</span><h2>运行趋势与信号覆盖</h2></div><span class="muted">{payload.run.horizon} 个固定推荐批次，不代表自然日</span></div>
      <div class="chart-grid">
        <article class="wide"><h3>各批次曝光与参与趋势</h3><div class="timeline-chart" data-testid="trend-chart" id="trend-chart"></div></article>
        <article><h3>Action / result 分布</h3><div class="bar-chart" data-testid="action-chart" id="action-chart"></div></article>
        <article><h3>Source scope 分布</h3><div class="bar-chart" data-testid="scope-chart" id="scope-chart"></div></article>
        <article><h3>Provider failure</h3><div class="bar-chart" data-testid="provider-chart" id="provider-chart"></div></article>
        <article><h3>动态邻居信号</h3><div class="bar-chart" data-testid="neighbor-chart" id="neighbor-chart"></div></article>
      </div>
    </section>

    <section class="users-band" data-testid="users-section">
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
.boundary-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); border:1px solid var(--line); background:var(--line); gap:1px; }.boundary-grid article { min-height:180px; padding:18px; background:#fff; }.boundary-grid ul { margin:12px 0 0; padding-left:18px; }.boundary-grid li { margin:7px 0; }
.boundary-statement { margin:14px 0 0; padding-left:12px; border-left:3px solid var(--violet); color:var(--muted); }
.muted { color:var(--muted); }.quiet-badge { padding:5px 8px; border:1px solid var(--amber); color:#7c460a; background:#fff5e8; border-radius:999px; font-size:.76rem; font-weight:800; }
.diagnostic-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; }.diagnostic-grid article { min-height:120px; padding:16px; background:#fff; border:1px solid var(--line); border-radius:6px; }.diagnostic-grid strong { display:block; margin:8px 0; font-size:1.6rem; }.diagnostic-grid p { margin:0; color:var(--muted); font-size:.82rem; }
.chart-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }.chart-grid article { min-width:0; min-height:260px; padding:16px; background:#fff; border:1px solid var(--line); border-radius:6px; }.chart-grid .wide { grid-column:1 / -1; min-height:310px; }
.bar-chart { min-height:210px; display:flex; flex-direction:column; gap:8px; justify-content:center; }.bar-row { display:grid; grid-template-columns:minmax(92px,150px) 1fr 52px; align-items:center; gap:9px; font-size:.78rem; }.bar-track { height:12px; background:#e7ece9; }.bar-fill { height:100%; background:var(--blue); }.bar-row:nth-child(3n+2) .bar-fill { background:var(--teal); }.bar-row:nth-child(3n) .bar-fill { background:var(--amber); }
.timeline-chart { min-height:250px; display:grid; grid-template-columns:repeat(30,minmax(10px,1fr)); align-items:end; gap:4px; padding-top:20px; border-bottom:1px solid var(--line); overflow-x:auto; }.step-column { min-width:10px; height:220px; display:flex; flex-direction:column; justify-content:flex-end; gap:2px; position:relative; }.step-column i { display:block; min-height:1px; }.step-column .exposure { background:var(--blue); }.step-column .engagement { background:var(--teal); }.step-column span { position:absolute; bottom:-20px; width:100%; text-align:center; color:var(--muted); font-size:.58rem; }
.users-band { background:#fff; }.filters { display:grid; grid-template-columns:2fr repeat(3,minmax(140px,1fr)); gap:10px; margin-bottom:14px; }.filters label span { display:block; margin-bottom:5px; color:var(--muted); font-size:.75rem; font-weight:700; }.filters input,.filters select { width:100%; min-height:40px; padding:8px 10px; border:1px solid #bfcac4; border-radius:5px; background:#fff; color:var(--ink); }
.table-wrap { width:100%; overflow:auto; border:1px solid var(--line); }.table-wrap table { width:100%; min-width:1120px; border-collapse:collapse; table-layout:fixed; }.table-wrap th,.table-wrap td { padding:11px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; overflow-wrap:anywhere; }.table-wrap th { position:sticky; top:0; z-index:1; background:#edf2ef; color:#4d5b54; font-size:.74rem; }.table-wrap td { font-size:.78rem; }.table-wrap tbody tr { cursor:pointer; }.table-wrap tbody tr:hover { background:#f1f7f4; }.profile-name { display:block; font-weight:800; }.profile-id,.mini { color:var(--muted); font-size:.72rem; }.status { display:inline-flex; margin-bottom:4px; padding:3px 6px; border-radius:999px; background:#e9effc; color:#244f9e; font-weight:800; }.status.provider_failed { background:#fdeaea; color:#9d2d2d; }.status.background_content { background:#fff0dd; color:#8b4f08; }.status.like,.status.comment,.status.share { background:#e6f5ef; color:#08644f; }.status.ignore { background:#ecefed; color:#4e5b54; }
.user-detail { min-height:120px; margin-top:12px; padding:16px; border:1px solid var(--line); border-left:4px solid var(--violet); background:#fafbfa; overflow-wrap:anywhere; }.detail-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; }.detail-grid div { padding:9px; background:#fff; border:1px solid var(--line); }.detail-grid span { display:block; color:var(--muted); font-size:.7rem; }.detail-grid strong { display:block; margin-top:4px; font-size:.82rem; }
.limitations-band { padding:28px clamp(18px,4vw,56px); display:grid; grid-template-columns:240px 1fr; gap:24px; background:#fff8ed; border-bottom:1px solid #ead7bd; }.limitations-band ul { margin:0; padding-left:20px; }.limitations-band li { margin:7px 0; }
footer { padding:24px clamp(18px,4vw,56px); display:flex; gap:18px; flex-wrap:wrap; background:#fff; }
@media (max-width:900px) { .target-band { grid-template-columns:1fr; }.object-flow { grid-template-columns:1fr; }.object-flow i { transform:rotate(90deg); justify-self:center; }.metrics-band { grid-template-columns:repeat(2,1fr); }.metrics-band article { border-bottom:1px solid #425048; }.boundary-grid,.diagnostic-grid { grid-template-columns:1fr 1fr; }.filters { grid-template-columns:1fr 1fr; }.detail-grid { grid-template-columns:1fr 1fr; } }
@media (max-width:600px) { .topbar,.split-heading { align-items:flex-start; flex-direction:column; }.target-band,.content-band,.users-band { padding-top:24px; padding-bottom:24px; }.target-facts,.metrics-band,.boundary-grid,.diagnostic-grid,.chart-grid,.filters,.detail-grid { grid-template-columns:1fr; }.chart-grid .wide { grid-column:auto; }.metrics-band article { min-height:86px; }.limitations-band { grid-template-columns:1fr; }.downloads { width:100%; }.downloads a { flex:1; justify-content:center; }.inline-actions { align-items:flex-start; flex-direction:column; } }
"""


_REPORT_JS = r"""
const payload = JSON.parse(document.getElementById('final-research-payload').textContent);
const users = payload.users;
const byId = (id) => document.getElementById(id);
const text = (value) => value === null || value === undefined || value === '' ? '—' : String(value);
const pct = (value) => value === null || value === undefined ? '—' : Number(value).toFixed(3);

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
  root.append(title,grid,latent);
}

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
