from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from functools import cache
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .prompt_field_summary import JINJIANG_PROMPT_V2_PROFILE_FIELDS
from .research_explanations import FieldProvenance, FieldUsageStage, LineageEntry

ValueStatus = Literal["present", "empty", "unavailable"]
PromptInclusionStatus = Literal["included", "empty_omitted", "not_allowlisted", "not_exposed", "not_rendered"]
OmissionReason = Literal[
    "",
    "empty_value_omitted_from_prompt",
    "field_not_in_prompt_allowlist",
    "prompt_summary_not_built",
    "user_not_exposed_to_target_video",
    "source_value_unavailable",
]

_DIRECT_PROFILE_FIELDS: dict[str, tuple[str, str, str, list[str]]] = {
    "user_id": (
        "用户标识",
        "在 processed 数据与研究运行中关联同一用户的稳定标识。",
        "非空字符串。",
        ["标识符只用于记录关联，不表达用户属性。"],
    ),
    "nickname": (
        "昵称",
        "processed 用户记录中的公开昵称。",
        "清洗后的字符串，可为空。",
        ["昵称可能变化，也不保证唯一。"],
    ),
    "bio": (
        "简介",
        "processed 用户记录中的清洗后简介文本。",
        "清洗后的字符串，可为空。",
        ["空值表示本次 processed 记录未提供，不代表用户没有简介。"],
    ),
    "signature": (
        "个性签名",
        "processed 用户记录中的清洗后签名文本。",
        "清洗后的字符串，可为空。",
        ["空值表示本次 processed 记录未提供，不代表用户没有签名。"],
    ),
    "follower_count": (
        "粉丝数",
        "采集时点观测到的 follower 数量。",
        "大于或等于 0 的整数。",
        ["时点值可能变化，也不等同于真实触达或影响效果。"],
    ),
    "following_count": (
        "关注数",
        "采集时点观测到的 following 数量。",
        "大于或等于 0 的整数。",
        ["时点值可能变化。"],
    ),
    "video_count": (
        "作品数",
        "采集时点观测到的公开视频数量。",
        "大于或等于 0 的整数。",
        ["时点值可能变化，且不表示作品质量。"],
    ),
}


@dataclass(frozen=True)
class _DerivedProxySpec:
    display_name_zh: str
    meaning: str
    source_fields: tuple[str, ...]
    transformation_method: str
    transformation_description: str
    declared_usage_stages: tuple[FieldUsageStage, ...]
    source_artifact_id: str = "field_source_records"
    record_key_fields: tuple[str, ...] = ("user_id",)
    value_range: str = "0.0 到 1.0。"


_DERIVED_PROXY_FIELDS: dict[str, _DerivedProxySpec] = {
    "activity_score": _DerivedProxySpec(
        "活跃度代理",
        "综合历史作品、评论和回复活跃度的可观测代理。",
        ("activity_video_score", "activity_comment_score", "activity_reply_score"),
        "holdout_safe_activity_proxy_v1",
        "0.25 * activity_video_score + 0.45 * activity_comment_score + 0.30 * activity_reply_score。",
        ("LLM Prompt", "Report Only"),
        "sample_manifest_json",
    ),
    "activity_video_score": _DerivedProxySpec(
        "视频活跃分量",
        "活跃度代理中的历史作品分量。",
        ("video_count", "video_count_p95"),
        "holdout_safe_log_p95_video_activity_v1",
        "使用 Historical Set reference 对 video_count 执行 log1p/P95 归一化并截断到 0–1。",
        ("Report Only",),
    ),
    "activity_comment_score": _DerivedProxySpec(
        "评论活跃分量",
        "活跃度代理中的 Historical Set 一级评论分量。",
        ("comment_count", "comment_count_p95"),
        "holdout_safe_log_p95_comment_activity_v1",
        "使用 Historical Set reference 对 comment_count 执行 log1p/P95 归一化并截断到 0–1。",
        ("Report Only",),
    ),
    "activity_reply_score": _DerivedProxySpec(
        "回复活跃分量",
        "活跃度代理中的 Historical Set 回复分量。",
        ("reply_count", "reply_count_p95"),
        "holdout_safe_log_p95_reply_activity_v1",
        "使用 Historical Set reference 对 reply_count 执行 log1p/P95 归一化并截断到 0–1。",
        ("Report Only",),
    ),
    "global_influence_score": _DerivedProxySpec(
        "全平台影响力代理",
        "processed 数据中以 follower evidence 为主的全平台影响力代理。",
        ("follower_count",),
        "processed_global_influence_proxy_v1",
        "保留 processed variant 已计算的全平台影响力代理，并关联实际 follower_count。",
        ("Seed Selection", "LLM Prompt", "Report Only"),
        "sample_manifest_json",
    ),
    "local_influence_score": _DerivedProxySpec(
        "局部影响力代理",
        "Historical Set 评论网络位置与评论获赞认可的组合代理。",
        ("local_network_score", "local_recognition_score"),
        "holdout_safe_local_influence_proxy_v1",
        "0.60 * local_network_score + 0.40 * local_recognition_score。",
        ("Seed Selection", "LLM Prompt", "Report Only"),
        "sample_manifest_json",
    ),
    "local_network_score": _DerivedProxySpec(
        "局部网络分量",
        "局部影响力代理中的 Historical Set 评论网络位置分量。",
        ("edge_degree", "edge_degree_p95"),
        "holdout_safe_log_p95_local_network_v1",
        "使用 Historical Set reference 对 weighted edge degree 执行 log1p/P95 归一化并截断到 0–1。",
        ("Report Only",),
    ),
    "local_recognition_score": _DerivedProxySpec(
        "局部认可分量",
        "局部影响力代理中的 Historical Set 评论获赞认可分量。",
        ("comment_like_sum", "comment_like_sum_p95"),
        "holdout_safe_log_p95_local_recognition_v1",
        "使用 Historical Set reference 对 comment_like_sum 执行 log1p/P95 归一化并截断到 0–1。",
        ("Report Only",),
    ),
    "base_network_relevance": _DerivedProxySpec(
        "历史网络相关性",
        "由 Historical Set 评论网络 weighted degree 形成的 holdout-safe 排序代理。",
        ("target_scope_weighted_degree", "target_scope_p95_weighted_degree"),
        "holdout_safe_network_relevance_v1",
        "使用 Historical Set weighted degree 与 P95 reference 执行 log1p 归一化并截断到 0–1。",
        ("Ranking", "Report Only"),
    ),
    "engaged_neighbor_count": _DerivedProxySpec(
        "已互动直接邻居数",
        "当前 Batch 前已对目标视频互动的直接邻居聚合数量。",
        ("engaged_neighbor_count",),
        "engaged_direct_neighbor_count_v1",
        "runtime 从互动用户集合与 Historical Set 直接邻接关系计算，并在 candidate record 持久化聚合计数。",
        ("Ranking", "Report Only"),
        "ranking_runtime_candidates",
        ("user_id", "time_step"),
        "大于或等于 0 的整数。",
    ),
    "engaged_neighbor_signal": _DerivedProxySpec(
        "已互动邻居排序信号",
        "由已互动直接邻居数形成的动态排序代理。",
        ("engaged_neighbor_count", "engaged_neighbor_signal"),
        "engaged_neighbor_signal_v1",
        "min(1, engaged_neighbor_count / 3)。",
        ("Ranking", "Report Only"),
        "ranking_runtime_candidates",
        ("user_id", "time_step"),
    ),
    "historical_tag_affinity": _DerivedProxySpec(
        "历史标签亲和度",
        "Historical Set 互动标签与目标视频标签之间的亲和度代理。",
        ("historical_tag_affinity",),
        "historical_tag_affinity_v1",
        "根据历史标签与目标视频 hashtags 计算，并在 candidate record 持久化聚合亲和度。",
        ("Ranking", "Report Only"),
        "ranking_runtime_candidates",
        ("user_id", "time_step"),
    ),
    "recommendation_score": _DerivedProxySpec(
        "推荐排序分数",
        "平台用于当前 Batch 全局排序的预声明加权分数。",
        ("base_network_relevance", "engaged_neighbor_signal", "historical_tag_affinity"),
        "predeclared_target_delivery_score_v1",
        "0.50 * base_network_relevance + 0.30 * engaged_neighbor_signal + 0.20 * historical_tag_affinity。",
        ("Ranking", "Report Only"),
        "ranking_runtime_candidates",
        ("user_id", "time_step"),
    ),
}

_SYNTHETIC_FIELD_LABELS = {
    "latent_attribute_spec_id": "合成属性规格标识",
    "latent_attribute_method": "合成属性方法",
    "latent_attribute_seed": "合成属性随机种子",
    "latent_class": "合成实验类别",
    "latent_environmental_consciousness_coef": "合成环保意识系数",
    "latent_epistemic_value_weight": "合成认知价值权重",
    "latent_environmental_value_weight": "合成环境价值权重",
    "latent_functional_value_weight": "合成功能价值权重",
    "latent_health_value_weight": "合成健康价值权重",
    "latent_emotional_value_weight": "合成情绪价值权重",
    "latent_social_value_weight": "合成社会价值权重",
    "latent_hotel_class": "合成酒店偏好类别",
    "latent_travel_purpose": "合成出行目的",
    "latent_gender": "合成性别标签",
    "latent_age": "合成年龄段",
    "latent_education": "合成教育标签",
    "latent_monthly_income": "合成月收入标签",
}

_DECISION_FIELDS = {
    "action",
    "engage",
    "probability",
    "reason",
    "confidence",
    "decision_source",
}
_OUTCOME_FIELDS = {
    "exposure_time_step",
    "result_status",
    "provider_status",
    "selected_for_exposure",
}
_SAMPLE_RUNTIME_FIELDS = {"in_base_sample", "is_seed", "is_network_cohort", "sample_role"}
_REPORT_LINK_FIELDS = {"report_path", "payload_path", "json_path", "manifest_path"}
_USER_RANKING_FIELDS = {"latest_ranking_time_step", "latest_ranking_position"}
_DIAGNOSTIC_FIELDS = {
    "ranking_diagnostics.paired_ablation",
    "ranking_diagnostics.weight_sensitivity",
    "ranking_diagnostics.historical_top20_diagnostic",
    "ranking_diagnostics.summary",
}

_DISPLAY_NAMES_ZH = {
    "action": "互动动作",
    "engage": "是否互动",
    "probability": "互动倾向",
    "reason": "决策理由",
    "confidence": "决策置信度",
    "decision_source": "决策来源",
    "provider_status": "Provider 状态",
    "provider_failure_type": "Provider 失败类型",
    "result_status": "最终结果状态",
    "exposure_time_step": "曝光批次",
    "selected_for_exposure": "是否获得曝光",
    "latest_ranking_time_step": "对应排序批次",
    "latest_ranking_position": "对应排序名次",
    "sample_role": "样本角色",
    "is_seed": "是否 Seed",
    "is_network_cohort": "是否 Network Cohort",
    "in_base_sample": "是否在 Base Sample",
    "ranking_diagnostics.paired_ablation": "配对排序消融",
    "ranking_diagnostics.weight_sensitivity": "排序权重敏感性",
    "ranking_diagnostics.historical_top20_diagnostic": "Historical Top20 诊断",
    "ranking_diagnostics.summary": "排序诊断摘要",
}

_FIELD_TOKEN_DISPLAY_NAMES_ZH = {
    "user_id": "用户标识",
    "video_id": "视频标识",
    "source_challenge_name": "采集来源",
    "caption": "视频文案",
    "hashtags": "视频标签",
    "creator_user_id": "创作者标识",
    "video_url": "视频链接",
    "source_challenge_rank": "采集来源排名",
    "sample_size": "样本数量",
    "horizon": "批次数量",
    "random_seed": "随机种子",
    "delivery_capacity": "投放容量",
    "maximum_target_exposures": "最大目标曝光数",
    "ranking_formula": "排序公式",
    "engaged_neighbor_formula": "已互动邻居公式",
    "sampling_method": "抽样方法",
    "sampling_status": "运行状态",
    "base_sample_count": "Base Sample 数量",
    "final_sample_count": "最终样本数量",
    "seed_count": "Seed 数量",
    "network_cohort_count": "Network Cohort 数量",
    "network_cohort_added_count": "新增 Network Cohort 数量",
    "replacement_count": "替换用户数量",
    "base_source_scope_counts": "Base Sample 来源分布",
    "final_source_scope_counts": "最终样本来源分布",
    "ordinary_count": "普通用户数量",
    "time_step": "批次",
    "eligible_count": "合格候选数量",
    "selected_count": "入选数量",
    "selected_user_ids": "入选用户标识",
    "target_exposures": "目标曝光数量",
    "decisions": "成功决策数量",
    "engagements": "互动数量",
    "ignored": "忽略数量",
    "provider_failed": "Provider 失败数量",
    "below_delivery_capacity": "低于投放容量数量",
    "candidates_with_positive_engaged_neighbor_signal": "具有正向邻居信号的候选数量",
    "selected_with_positive_engaged_neighbor_signal": "具有正向邻居信号的入选数量",
    "maximum_engaged_neighbor_signal": "最大已互动邻居信号",
    "ranking_position": "排序名次",
    "is_seed": "是否 Seed",
    "selected": "是否入选",
    "base_network_relevance": "历史网络相关性",
    "engaged_neighbor_count": "已互动直接邻居数",
    "engaged_neighbor_signal": "已互动邻居排序信号",
    "historical_tag_affinity": "历史标签亲和度",
    "recommendation_score": "推荐排序分数",
    "report_path": "报告路径",
    "payload_path": "Payload 路径",
    "json_path": "用户 JSON 路径",
    "manifest_path": "Manifest 路径",
}


@dataclass(frozen=True)
class _ReportFieldSpec:
    artifact_id: str
    record_key_fields: tuple[str, ...]
    source_fields: tuple[str, ...]
    transformation_method: str
    transformation_description: str
    value_range: str
    interpretation: str
    limitations: tuple[str, ...]
    record_key_defaults: tuple[tuple[str, str | int], ...] = ()


class SourceRecordLocator(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    relative_path: str
    record_key: dict[str, str | int]


class FieldEvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_kind: str
    record_key: dict[str, str | int]
    source_fields: list[str]
    matched_values: list[str]


RuntimeFeedbackKind = Literal[
    "next_batch_direct_neighbor_signal",
    "no_eligible_direct_neighbor_signal",
    "no_next_batch_signal",
    "no_propagation_action",
    "provider_failure_no_action",
    "not_exposed_no_action",
]


class RuntimeFeedbackEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_kind: RuntimeFeedbackKind
    user_id: str
    time_step: int
    action: Literal["", "like", "comment", "share", "ignore"]
    next_time_step: int | None
    affected_direct_neighbor_user_ids: list[str]

    @model_validator(mode="after")
    def _validate_feedback_semantics(self) -> RuntimeFeedbackEvidence:
        engaging = self.action in {"like", "comment", "share"}
        if self.affected_direct_neighbor_user_ids != sorted(set(self.affected_direct_neighbor_user_ids)):
            raise ValueError("runtime feedback affected user ids must be unique and sorted")
        if self.evidence_kind == "next_batch_direct_neighbor_signal":
            if not engaging or self.next_time_step is None or not self.affected_direct_neighbor_user_ids:
                raise ValueError("next-batch feedback requires an engaging action, batch, and affected users")
        elif self.evidence_kind == "no_eligible_direct_neighbor_signal":
            if not engaging or self.next_time_step is None or self.affected_direct_neighbor_user_ids:
                raise ValueError("no-eligible feedback requires an engaging action and empty next-batch impact")
        elif self.evidence_kind == "no_next_batch_signal":
            if not engaging or self.next_time_step is not None or self.affected_direct_neighbor_user_ids:
                raise ValueError("no-next-batch feedback requires an engaging action without future impact")
        elif self.evidence_kind == "no_propagation_action":
            if self.action != "ignore" or self.affected_direct_neighbor_user_ids:
                raise ValueError("no-propagation feedback requires ignore and no affected users")
        elif self.action or self.affected_direct_neighbor_user_ids:
            raise ValueError("missing-action feedback cannot contain an action or affected users")
        return self

    def as_field_evidence(self) -> FieldEvidenceReference:
        matched_values = [
            f"action={self.action or 'unavailable'}",
            f"affected_direct_neighbor_count={len(self.affected_direct_neighbor_user_ids)}",
        ]
        if self.next_time_step is not None:
            matched_values.append(f"next_time_step={self.next_time_step}")
        if self.action in {"like", "comment", "share"}:
            matched_values.append(
                "affected_direct_neighbor_user_ids="
                + json.dumps(
                    self.affected_direct_neighbor_user_ids,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
        return FieldEvidenceReference(
            evidence_kind=self.evidence_kind,
            record_key={"user_id": self.user_id, "time_step": self.time_step},
            source_fields=["action", "next_time_step", "affected_direct_neighbor_user_ids"],
            matched_values=matched_values,
        )


class FieldLineageDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_name: str
    display_name_zh: str
    meaning: str
    provenance: FieldProvenance
    source_artifact_kind: str
    record_key_fields: list[str]
    source_fields: list[str]
    transformation_method: str
    transformation_description: str
    declared_usage_stages: list[FieldUsageStage]
    value_range: str
    interpretation: str
    limitations: list[str]


class UserFieldTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    field_name: str
    value_status: ValueStatus
    source_record_locator: SourceRecordLocator
    evidence: list[FieldEvidenceReference] = Field(default_factory=list)
    actual_usage_stages: list[FieldUsageStage]
    prompt_inclusion_status: PromptInclusionStatus
    omission_reason: OmissionReason = ""


class FieldSourceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    interest_tags: list[str]
    historical_tags: list[str]
    interest_tag_evidence: list[FieldEvidenceReference]
    historical_tag_evidence: list[FieldEvidenceReference]
    derived_proxy_inputs: dict[str, int | float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_evidence_coverage(self) -> FieldSourceRecord:
        _validate_evidence_coverage("interest_tags", self.interest_tags, self.interest_tag_evidence)
        _validate_evidence_coverage("historical_tags", self.historical_tags, self.historical_tag_evidence)
        return self


class FieldLineageTraceBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalog: list[FieldLineageDefinition]
    trace_index: dict[str, list[UserFieldTrace]]
    source_records: list[FieldSourceRecord]

    def catalog_document(self) -> dict[str, object]:
        return {
            "schema_version": "field-lineage-catalog-v1",
            "definitions": [definition.model_dump(mode="json") for definition in self.catalog],
            "coverage_audit": field_lineage_coverage_audit(self.catalog, self.trace_index),
        }

    def trace_document(self) -> dict[str, object]:
        return {
            "schema_version": "user-field-trace-v1",
            "users": {
                user_id: [trace.model_dump(mode="json") for trace in traces]
                for user_id, traces in self.trace_index.items()
            },
        }

    def source_document(self) -> dict[str, object]:
        return {
            "schema_version": "field-source-records-v1",
            "records": [record.model_dump(mode="json") for record in self.source_records],
        }


@dataclass(frozen=True)
class FieldLineageTraceSource:
    users: Sequence[Mapping[str, object]]
    historical_tags_by_user: Mapping[str, Sequence[str]]
    interest_tag_evidence_by_user: Mapping[str, Sequence[Mapping[str, object]]]
    historical_tag_evidence_by_user: Mapping[str, Sequence[Mapping[str, object]]]
    exposed_user_ids: set[str]
    prompt_inclusion_by_user: Mapping[str, Mapping[str, PromptInclusionStatus]]
    artifact_paths: Mapping[str, str]
    derived_proxy_inputs_by_user: Mapping[str, Mapping[str, int | float]] = dataclass_field(default_factory=dict)
    report_lineage: Sequence[LineageEntry] = ()


class FieldLineageTraceModule:
    """Build normalized field definitions and compact per-user trace evidence."""

    def build(self, source: FieldLineageTraceSource) -> FieldLineageTraceBundle:
        source_path = source.artifact_paths.get("field_source_records")
        if not source_path:
            raise ValueError("field trace requires the field_source_records artifact path")
        sample_path = source.artifact_paths.get("sample_manifest_json")
        if not sample_path:
            raise ValueError("field trace requires the sample_manifest_json artifact path")

        base_catalog = field_lineage_definitions()
        base_field_names = {definition.field_name for definition in base_catalog}
        catalog = field_lineage_definitions(source.report_lineage)
        definitions_by_name = {definition.field_name: definition for definition in catalog}
        trace_index: dict[str, list[UserFieldTrace]] = {}
        source_records: list[FieldSourceRecord] = []
        seen_user_ids: set[str] = set()
        for user in source.users:
            user_id = str(user.get("user_id", ""))
            if not user_id or user_id in seen_user_ids:
                raise ValueError("field trace users require unique non-empty user_id values")
            seen_user_ids.add(user_id)
            interest_tags = _string_list(user.get("interest_tags")) if "interest_tags" in user else None
            historical_tags = sorted({str(tag) for tag in source.historical_tags_by_user.get(user_id, ()) if str(tag)})
            interest_evidence = _evidence(source.interest_tag_evidence_by_user.get(user_id, ()))
            historical_evidence = _evidence(source.historical_tag_evidence_by_user.get(user_id, ()))
            source_records.append(
                FieldSourceRecord(
                    user_id=user_id,
                    interest_tags=interest_tags or [],
                    historical_tags=historical_tags,
                    interest_tag_evidence=interest_evidence,
                    historical_tag_evidence=historical_evidence,
                    derived_proxy_inputs=dict(source.derived_proxy_inputs_by_user.get(user_id, {})),
                )
            )
            locator = SourceRecordLocator(
                artifact_id="field_source_records",
                relative_path=source_path,
                record_key={"user_id": user_id},
            )
            sample_locator = SourceRecordLocator(
                artifact_id="sample_manifest_json",
                relative_path=sample_path,
                record_key={"user_id": user_id},
            )
            offline_locator = SourceRecordLocator(
                artifact_id="offline_scores",
                relative_path=source.artifact_paths.get("offline_scores", source_path),
                record_key={"user_id": user_id},
            )
            candidate_locator = SourceRecordLocator(
                artifact_id="ranking_runtime_candidates",
                relative_path=source.artifact_paths.get("ranking_runtime_candidates", source_path),
                record_key={
                    "user_id": user_id,
                    "time_step": _integer_value(user.get("latest_ranking_time_step")),
                },
            )
            proxy_locators = {
                "field_source_records": locator,
                "sample_manifest_json": sample_locator,
                "ranking_runtime_candidates": candidate_locator,
            }
            latent_source = user.get("latent_attributes")
            latent_attributes: Mapping[str, object] = latent_source if isinstance(latent_source, Mapping) else {}
            interest_prompt_status, interest_omission = _interest_prompt_status(
                user_id=user_id,
                value_status=_value_status(interest_tags),
                source=source,
            )
            trace_index[user_id] = [
                *(
                    UserFieldTrace(
                        user_id=user_id,
                        field_name=field_name,
                        value_status=field_value_status(user.get(field_name)) if field_name in user else "unavailable",
                        source_record_locator=sample_locator,
                        actual_usage_stages=(
                            ["Sampling", "Seed Selection", "Ranking", "Report Only"]
                            if field_name == "user_id"
                            else ["Report Only"]
                        ),
                        prompt_inclusion_status="not_allowlisted",
                        omission_reason="field_not_in_prompt_allowlist",
                    )
                    for field_name in _DIRECT_PROFILE_FIELDS
                ),
                UserFieldTrace(
                    user_id=user_id,
                    field_name="interest_tags",
                    value_status=_value_status(interest_tags),
                    source_record_locator=locator,
                    evidence=interest_evidence,
                    actual_usage_stages=(
                        ["LLM Prompt", "Report Only"] if interest_prompt_status == "included" else ["Report Only"]
                    ),
                    prompt_inclusion_status=interest_prompt_status,
                    omission_reason=interest_omission,
                ),
                UserFieldTrace(
                    user_id=user_id,
                    field_name="historical_tags",
                    value_status=_value_status(historical_tags),
                    source_record_locator=locator,
                    evidence=historical_evidence,
                    actual_usage_stages=["Ranking", "Report Only"],
                    prompt_inclusion_status="not_allowlisted",
                    omission_reason="field_not_in_prompt_allowlist",
                ),
                *(
                    _derived_proxy_trace(
                        user_id=user_id,
                        field_name=field_name,
                        spec=spec,
                        definition=definitions_by_name[field_name],
                        user=user,
                        source=source,
                        locator=proxy_locators[spec.source_artifact_id],
                    )
                    for field_name, spec in _DERIVED_PROXY_FIELDS.items()
                ),
                *(
                    _synthetic_trace(
                        user_id=user_id,
                        field_name=field_name,
                        definition=definitions_by_name[field_name],
                        latent_attributes=latent_attributes,
                        source=source,
                        locator=sample_locator,
                    )
                    for field_name in _SYNTHETIC_FIELD_LABELS
                ),
                _historical_scalar_trace(
                    user_id=user_id,
                    field_name="sample_source_scope",
                    definition=definitions_by_name["sample_source_scope"],
                    user=user,
                    locator=sample_locator,
                    actual_usage_stages=["Sampling", "Report Only"],
                ),
                _historical_scalar_trace(
                    user_id=user_id,
                    field_name="historical_comment_network_weighted_degree",
                    definition=definitions_by_name["historical_comment_network_weighted_degree"],
                    user=user,
                    locator=offline_locator,
                    actual_usage_stages=["Ranking", "Report Only"],
                    source_field_name="target_scope_weighted_degree",
                ),
                *(
                    _report_field_trace(
                        user_id=user_id,
                        definition=definition,
                        user=user,
                        source=source,
                    )
                    for definition in catalog
                    if definition.field_name not in base_field_names
                    and is_user_field_trace_definition(definition)
                ),
            ]

        return FieldLineageTraceBundle(
            catalog=catalog,
            trace_index=trace_index,
            source_records=source_records,
        )


def _historical_v4_field_lineage_definitions(
    report_lineage: Sequence[LineageEntry] = (),
) -> list[FieldLineageDefinition]:
    definitions = [
        *(
            FieldLineageDefinition(
                field_name=field_name,
                display_name_zh=display_name,
                meaning=meaning,
                provenance="Direct Observed Profile Field",
                source_artifact_kind="persisted processed research sample record",
                record_key_fields=["user_id"],
                source_fields=[field_name],
                transformation_method="processed_profile_direct_v1",
                transformation_description="从 allowlisted processed 用户记录原样保留；文本只使用既有清洗结果。",
                declared_usage_stages=(
                    ["Sampling", "Seed Selection", "Ranking", "Report Only"]
                    if field_name == "user_id"
                    else ["Report Only"]
                ),
                value_range=value_range,
                interpretation="直接观测字段只表达采集与清洗记录，不推断心理或行为倾向。",
                limitations=limitations,
            )
            for field_name, (display_name, meaning, value_range, limitations) in _DIRECT_PROFILE_FIELDS.items()
        ),
        FieldLineageDefinition(
            field_name="historical_tags",
            display_name_zh="历史互动标签",
            meaning="用户在 Historical Set 中实际互动视频的标签集合。",
            provenance="Historical Behavioral Evidence",
            source_artifact_kind="allowlisted historical interaction evidence snapshot",
            record_key_fields=["user_id"],
            source_fields=["commenter_user_id", "video_id", "hashtags"],
            transformation_method="historical_interaction_video_tags_v1",
            transformation_description="按用户关联 Historical Set 互动视频，合并 hashtags 后去重并稳定排序。",
            declared_usage_stages=["Ranking", "Report Only"],
            value_range="去重后的字符串列表，可为空。",
            interpretation="表示已观测历史互动内容的标签证据，不是用户自述兴趣。",
            limitations=["没有真实曝光日志。", "不得回填到 interest_tags。"],
        ),
        FieldLineageDefinition(
            field_name="interest_tags",
            display_name_zh="兴趣标签",
            meaning="processed variant 从历史 hashtags 与文本主题证据整理的用户兴趣主题。",
            provenance="Historical Behavioral Evidence",
            source_artifact_kind="allowlisted processed historical topic evidence snapshot",
            record_key_fields=["user_id"],
            source_fields=["historical_video_hashtags", "historical_text_topic_terms"],
            transformation_method="historical_topic_tags_stable_unique_v1",
            transformation_description="提取历史视频 hashtags 与相关文本主题词，清理空值、去重并稳定排序。",
            declared_usage_stages=["LLM Prompt", "Report Only"],
            value_range="去重后的字符串列表，可为空。",
            interpretation="表示可复算的历史主题代理，不是直接观测 profile 字段。",
            limitations=[
                "仅表示可复算的历史行为主题，不代表真实心理画像。",
                "空列表不代表用户没有兴趣。",
                "不得从 historical_tags 静默回填。",
            ],
        ),
        *(
            FieldLineageDefinition(
                field_name=field_name,
                display_name_zh=spec.display_name_zh,
                meaning=spec.meaning,
                provenance="Derived Proxy Metric",
                source_artifact_kind=_derived_source_artifact_kind(spec.source_artifact_id),
                record_key_fields=list(spec.record_key_fields),
                source_fields=list(spec.source_fields),
                transformation_method=spec.transformation_method,
                transformation_description=spec.transformation_description,
                declared_usage_stages=list(spec.declared_usage_stages),
                value_range=spec.value_range,
                interpretation="代理指标用于研究排序、抽样或 Prompt，不等同于真实影响力、活跃度或心理属性。",
                limitations=[
                    "依赖本项目声明的 Historical Set、reference 与归一化方法。",
                    "只能作为可复算代理，不等同第三方指数。",
                ],
            )
            for field_name, spec in _DERIVED_PROXY_FIELDS.items()
        ),
        *(
            FieldLineageDefinition(
                field_name=field_name,
                display_name_zh=display_name,
                meaning=f"由固定实验规格为研究用户生成的{display_name}。",
                provenance="Synthetic Experiment Label",
                source_artifact_kind="persisted synthetic experiment assignment record",
                record_key_fields=["user_id"],
                source_fields=_synthetic_source_fields(field_name),
                transformation_method="jinjiang_latent_attribute_assignment_v1",
                transformation_description="由 spec id、method、seed 与稳定 user_id 生成并持久化，不从真实画像推断。",
                declared_usage_stages=(
                    ["LLM Prompt", "Report Only"]
                    if field_name in JINJIANG_PROMPT_V2_PROFILE_FIELDS
                    else ["Report Only"]
                ),
                value_range=(
                    "实验规格定义的数值范围。"
                    if field_name.endswith(("_coef", "_weight"))
                    else "实验规格定义的标识、种子或类别值。"
                ),
                interpretation="仅用于可复现实验分组与决策输入，不表示真实用户身份、偏好或心理。",
                limitations=[
                    "始终属于 Synthetic Experiment Label。",
                    "不得描述为真实采集画像或第三方认证标签。",
                ],
            )
            for field_name, display_name in _SYNTHETIC_FIELD_LABELS.items()
        ),
        FieldLineageDefinition(
            field_name="sample_source_scope",
            display_name_zh="采集来源分组",
            meaning="用户在 Historical Set 中主要互动的 Video Source Scope。",
            provenance="Historical Behavioral Evidence",
            source_artifact_kind="persisted processed research sample record",
            record_key_fields=["user_id"],
            source_fields=["sample_source_scope"],
            transformation_method="primary_video_source_scope_v1",
            transformation_description="按 Historical Set 中用户互动次数选择主要 source scope，相同时稳定排序。",
            declared_usage_stages=["Sampling", "Report Only"],
            value_range="已知 source_challenge_name 或 remaining_users。",
            interpretation="表示采集来源分组，不是视频语义类别或用户偏好。",
            limitations=["只反映已采集 Historical Set。"],
        ),
        FieldLineageDefinition(
            field_name="historical_comment_network_weighted_degree",
            display_name_zh="历史评论网络加权度",
            meaning="用户在 holdout-safe Historical Set 评论互动网络中的 weighted degree。",
            provenance="Historical Behavioral Evidence",
            source_artifact_kind="persisted offline recommendation score record",
            record_key_fields=["user_id"],
            source_fields=["target_scope_weighted_degree"],
            transformation_method="historical_comment_graph_weighted_degree_v1",
            transformation_description="按评论者、回复与 mention 的历史互动边权聚合，不使用 Target Holdout。",
            declared_usage_stages=["Ranking", "Report Only"],
            value_range="大于或等于 0 的整数。",
            interpretation="表示采集评论图中的连接证据，不等同关注或好友关系。",
            limitations=["只覆盖已采集历史评论关系。", "Target Holdout 不进入该值。"],
        ),
    ]
    existing = {definition.field_name for definition in definitions}
    definitions.extend(
        _report_field_definition(entry)
        for entry in report_lineage
        if entry.field_name not in existing
    )
    return definitions


# Preserve the existing writer name while historical readers bind to the versioned function.
field_lineage_definitions = _historical_v4_field_lineage_definitions


def is_user_field_trace_definition(definition: FieldLineageDefinition) -> bool:
    return "user_id" in definition.record_key_fields or definition.field_name in _DIAGNOSTIC_FIELDS


def is_decision_trace_field(field_name: str) -> bool:
    return field_name in _DECISION_FIELDS or field_name == "provider_failure_type"


def _report_field_definition(entry: LineageEntry) -> FieldLineageDefinition:
    field_name = entry.field_name
    spec = _report_field_spec(field_name)
    field_token = field_name.split(".")[-1]
    display_name = (
        _DISPLAY_NAMES_ZH[field_name]
        if field_name in _DISPLAY_NAMES_ZH
        else _FIELD_TOKEN_DISPLAY_NAMES_ZH[field_token]
    )
    return FieldLineageDefinition(
        field_name=field_name,
        display_name_zh=display_name,
        meaning=f"报告中 {field_name} 的同源记录级证据。",
        provenance=entry.provenance,
        source_artifact_kind=f"persisted {spec.artifact_id} record",
        record_key_fields=list(spec.record_key_fields),
        source_fields=list(spec.source_fields),
        transformation_method=spec.transformation_method,
        transformation_description=spec.transformation_description,
        declared_usage_stages=list(entry.usage_stages),
        value_range=spec.value_range,
        interpretation=spec.interpretation,
        limitations=list(spec.limitations),
    )


@cache
def _report_field_spec(field_name: str) -> _ReportFieldSpec:
    token = field_name.rsplit(".", 1)[-1]
    value_range = (
        "true 或 false；未产生 Decision 时可 unavailable。"
        if field_name in {"engage", "selected_for_exposure", "in_base_sample", "is_seed", "is_network_cohort"}
        else "0.0 到 1.0；未产生成功 Decision 时 unavailable。"
        if field_name in {"probability", "confidence"}
        else "大于或等于 0 的整数；不适用时 unavailable。"
        if field_name.endswith(("position", "time_step", "count", "capacity"))
        else "由对应 persisted artifact schema 约束。"
    )
    common_interpretation = "该值按 catalog 声明的阶段解释，不自动成为 LLM Prompt 输入。"
    common_limitations = ("只引用本次 run 的 allowlisted persisted evidence。",)
    if field_name == "action":
        return _ReportFieldSpec(
            "runtime_decisions",
            ("user_id", "video_id", "time_step"),
            ("action", "engage", "probability", "reason", "confidence", "decision_source"),
            "structured_decision_and_direct_neighbor_feedback_v1",
            "保留同一次结构化 Decision 的 action；like/comment/share 只对下一轮仍 eligible 的直接邻居形成排序信号，ignore 不传播。",
            value_range,
            "该值只描述本次 Recommendation Opportunity 的结构化决策或 Provider 结果。",
            (
                "只引用本次 run 的 allowlisted persisted evidence。",
                "同批 action 不互相影响；只有下一批仍 eligible 的直接邻居可能获得动态信号。",
                "不保存原始 Prompt、Provider request/response 或异常消息。",
            ),
        )
    if field_name in _DECISION_FIELDS:
        return _ReportFieldSpec(
            "runtime_decisions",
            ("user_id", "video_id", "time_step"),
            ("action", "engage", "probability", "reason", "confidence", "decision_source"),
            "structured_decision_v1",
            "从同一次 Recommendation Opportunity 的安全结构化 Decision 原样投影。",
            value_range,
            "该值只描述本次 Recommendation Opportunity 的结构化决策或 Provider 结果。",
            (
                "只引用本次 run 的 allowlisted persisted evidence。",
                "不保存原始 Prompt、Provider request/response 或异常消息。",
            ),
        )
    if field_name == "provider_failure_type":
        return _ReportFieldSpec(
            "runtime_provider_failures",
            ("user_id", "video_id", "time_step"),
            ("failure_type",),
            "provider_failure_classification_v1",
            "仅保留稳定失败类型，不保存异常消息或 Provider Payload。",
            value_range,
            "该值只描述本次 Recommendation Opportunity 的结构化决策或 Provider 结果。",
            (
                "只引用本次 run 的 allowlisted persisted evidence。",
                "不保存原始 Prompt、Provider request/response 或异常消息。",
            ),
        )
    if field_name in _OUTCOME_FIELDS:
        interpretation = (
            "below_delivery_capacity 表示未曝光；ignore 表示曝光后不互动，两者不可互换。"
            if field_name == "result_status"
            else "该值只描述本次 Recommendation Opportunity 的结构化决策或 Provider 结果。"
            if field_name == "provider_status"
            else common_interpretation
        )
        return _ReportFieldSpec(
            "ranking_runtime_outcomes",
            ("user_id",),
            ("exposure_time_step", "ranking_position", "result_status", "provider_status"),
            "target_delivery_outcome_v1",
            "从每用户唯一的 persisted ranking outcome 记录投影。",
            value_range,
            str(interpretation),
            common_limitations,
        )
    if field_name in _USER_RANKING_FIELDS or field_name.startswith("ranking_rounds.candidates."):
        return _ReportFieldSpec(
            "ranking_runtime_candidates",
            ("user_id", "time_step"),
            (
                "ranking_position",
                "base_network_relevance",
                "engaged_neighbor_count",
                "engaged_neighbor_signal",
                "historical_tag_affinity",
                "recommendation_score",
                "selected",
            ),
            "global_reranking_candidate_evidence_v1",
            "使用同一 Batch 的冻结 candidate components 全局排序；相同 score 以 user_id 稳定打破并列。",
            value_range,
            common_interpretation,
            common_limitations,
        )
    if field_name in _SAMPLE_RUNTIME_FIELDS:
        return _ReportFieldSpec(
            "seed_first_sample_audit",
            ("user_id",),
            (token,),
            "seed_first_sample_membership_v1",
            "从本次 Seed-First sample audit 的互斥角色与成员记录投影。",
            value_range,
            common_interpretation,
            common_limitations,
        )
    if field_name in _REPORT_LINK_FIELDS:
        return _ReportFieldSpec(
            "final_research_users_json",
            ("user_id",),
            (token,),
            "report_artifact_link_v1",
            "由本次 manifest 登记的相对 artifact 路径生成。",
            value_range,
            common_interpretation,
            common_limitations,
        )
    diagnostic_specs = {
        "ranking_diagnostics.paired_ablation": (
            "ranking_ablation_diagnostics_csv",
            ("user_id", "time_step"),
            ("user_id", "time_step", "paired_ablation"),
            (),
        ),
        "ranking_diagnostics.weight_sensitivity": (
            "ranking_weight_sensitivity_csv",
            ("variant_id", "time_step"),
            ("variant_id", "time_step", "weight_sensitivity"),
            (("variant_id", "main_50_30_20"),),
        ),
        "ranking_diagnostics.historical_top20_diagnostic": (
            "ranking_diagnostics",
            ("schema_version", "section"),
            ("schema_version", "historical_top20_diagnostic"),
            (
                ("schema_version", "ranking-diagnostics-v1"),
                ("section", "historical_top20_diagnostic"),
            ),
        ),
        "ranking_diagnostics.summary": (
            "ranking_diagnostics_summary",
            ("schema_version",),
            ("schema_version", "summary"),
            (("schema_version", "ranking-diagnostics-summary-v1"),),
        ),
    }
    if field_name in diagnostic_specs:
        artifact_id, record_key_fields, source_fields, record_key_defaults = diagnostic_specs[field_name]
        return _ReportFieldSpec(
            artifact_id,
            record_key_fields,
            source_fields,
            "same_run_ranking_diagnostic_v1",
            "只引用本次 run 基于 persisted candidate evidence 生成的 diagnostics。",
            value_range,
            "诊断只解释本次 persisted run，不构成真实平台因果或准确率结论。",
            (
                "只引用本次 run 的 allowlisted persisted evidence。",
                "不得复用其他 run 的 rank delta、Top20 或 action 结果。",
            ),
            record_key_defaults,
        )
    if field_name.startswith("target_video."):
        artifact_id, record_key_fields = "target_video_snapshot", ("video_id",)
    elif field_name.startswith("run."):
        artifact_id, record_key_fields = "ranking_runtime_summary", ("sampling_method",)
    elif field_name.startswith("sample_comparison."):
        artifact_id, record_key_fields = "seed_first_sample_audit", ("sampling_method",)
    elif field_name.startswith("ranking_rounds."):
        artifact_id, record_key_fields = "ranking_runtime_steps", ("time_step",)
    else:
        raise ValueError(f"unsupported report field trace definition: {field_name}")
    return _ReportFieldSpec(
        artifact_id,
        record_key_fields,
        (token,),
        "persisted_report_projection_v1",
        "从本次 run 的 allowlisted persisted artifact 原样或确定性投影。",
        value_range,
        common_interpretation,
        common_limitations,
    )


def _report_field_trace(
    *,
    user_id: str,
    definition: FieldLineageDefinition,
    user: Mapping[str, object],
    source: FieldLineageTraceSource,
) -> UserFieldTrace:
    field_name = definition.field_name
    value = user.get(field_name)
    value_status = field_value_status(value) if field_name in user else "unavailable"
    artifact_id = _report_field_spec(field_name).artifact_id
    if field_name in _DECISION_FIELDS and value_status != "present":
        artifact_id = "ranking_runtime_outcomes"
    if field_name == "provider_failure_type" and value_status != "present":
        artifact_id = "ranking_runtime_outcomes"
    relative_path = source.artifact_paths.get(artifact_id)
    if not relative_path:
        raise ValueError(f"field trace requires the {artifact_id} artifact path")
    locator = SourceRecordLocator(
        artifact_id=artifact_id,
        relative_path=relative_path,
        record_key=_report_field_record_key(field_name, user_id, user, artifact_id=artifact_id),
    )
    evidence_values = {
        source_field: user[source_field]
        for source_field in definition.source_fields
        if source_field in user
    }
    if field_name in user:
        evidence_values.setdefault(field_name.split(".")[-1], value)
    if field_name == "provider_failure_type":
        evidence_values["failure_type"] = value
    evidence = field_trace_evidence(definition, evidence_values, locator)
    if artifact_id == "ranking_runtime_outcomes" and is_decision_trace_field(field_name):
        outcome_fields = [
            source_field
            for source_field in ("result_status", "provider_status")
            if source_field in user
        ]
        evidence = [
            FieldEvidenceReference(
                evidence_kind="runtime_value_unavailable",
                record_key=locator.record_key,
                source_fields=outcome_fields,
                matched_values=[f"{source_field}={user[source_field]}" for source_field in outcome_fields],
            )
        ]
    if field_name == "action":
        propagation = user.get("action_propagation_evidence")
        if isinstance(propagation, Mapping):
            evidence = [FieldEvidenceReference.model_validate(dict(propagation))]
    actual_usage_stages: list[FieldUsageStage] = list(definition.declared_usage_stages)
    if field_name == "action":
        if not evidence or evidence[0].evidence_kind != "next_batch_direct_neighbor_signal":
            actual_usage_stages = ["Report Only"]
    return UserFieldTrace(
        user_id=user_id,
        field_name=field_name,
        value_status=value_status,
        source_record_locator=locator,
        evidence=evidence,
        actual_usage_stages=actual_usage_stages,
        prompt_inclusion_status="not_allowlisted",
        omission_reason="field_not_in_prompt_allowlist",
    )


def _report_field_record_key(
    field_name: str,
    user_id: str,
    user: Mapping[str, object],
    artifact_id: str | None = None,
) -> dict[str, str | int]:
    spec = _report_field_spec(field_name)
    fields = ["user_id"] if artifact_id == "ranking_runtime_outcomes" else spec.record_key_fields
    defaults = dict(spec.record_key_defaults)
    key: dict[str, str | int] = {}
    for key_field in fields:
        if key_field in defaults:
            key[key_field] = defaults[key_field]
        elif key_field == "user_id":
            key[key_field] = user_id
        elif key_field == "time_step":
            key[key_field] = _integer_value(user.get("latest_ranking_time_step"))
        elif key_field == "video_id":
            key[key_field] = str(user.get("target_video_id", ""))
        else:
            key[key_field] = str(user.get(key_field, ""))
    return key


def _derived_proxy_trace(
    *,
    user_id: str,
    field_name: str,
    spec: _DerivedProxySpec,
    definition: FieldLineageDefinition,
    user: Mapping[str, object],
    source: FieldLineageTraceSource,
    locator: SourceRecordLocator,
) -> UserFieldTrace:
    value_status = field_value_status(user.get(field_name)) if field_name in user else "unavailable"
    prompt_status, omission_reason = _prompt_status(
        user_id=user_id,
        field_name=field_name,
        value_status=value_status,
        source=source,
    )
    inputs = {
        **source.derived_proxy_inputs_by_user.get(user_id, {}),
        **{key: value for key, value in user.items() if key in spec.source_fields},
    }
    evidence = field_trace_evidence(definition, inputs, locator)
    actual_stages: list[FieldUsageStage] = [
        stage for stage in spec.declared_usage_stages if stage != "LLM Prompt"
    ]
    if prompt_status == "included":
        actual_stages = list(spec.declared_usage_stages)
    return UserFieldTrace(
        user_id=user_id,
        field_name=field_name,
        value_status=value_status,
        source_record_locator=locator,
        evidence=evidence,
        actual_usage_stages=actual_stages,
        prompt_inclusion_status=prompt_status,
        omission_reason=omission_reason,
    )


def _synthetic_trace(
    *,
    user_id: str,
    field_name: str,
    definition: FieldLineageDefinition,
    latent_attributes: Mapping[str, object],
    source: FieldLineageTraceSource,
    locator: SourceRecordLocator,
) -> UserFieldTrace:
    value_status = (
        field_value_status(latent_attributes.get(field_name)) if field_name in latent_attributes else "unavailable"
    )
    prompt_status, omission_reason = _prompt_status(
        user_id=user_id,
        field_name=field_name,
        value_status=value_status,
        source=source,
    )
    evidence = field_trace_evidence(definition, latent_attributes, locator)
    declared_stages: list[FieldUsageStage] = (
        ["LLM Prompt", "Report Only"]
        if field_name in JINJIANG_PROMPT_V2_PROFILE_FIELDS
        else ["Report Only"]
    )
    actual_stages: list[FieldUsageStage] = [stage for stage in declared_stages if stage != "LLM Prompt"]
    if prompt_status == "included":
        actual_stages = declared_stages
    return UserFieldTrace(
        user_id=user_id,
        field_name=field_name,
        value_status=value_status,
        source_record_locator=locator,
        evidence=evidence,
        actual_usage_stages=actual_stages,
        prompt_inclusion_status=prompt_status,
        omission_reason=omission_reason,
    )


def _synthetic_source_fields(field_name: str) -> list[str]:
    contract_fields = ["latent_attribute_spec_id", "latent_attribute_method", "latent_attribute_seed"]
    return [*contract_fields, *([] if field_name in contract_fields else [field_name])]


def _historical_scalar_trace(
    *,
    user_id: str,
    field_name: str,
    definition: FieldLineageDefinition,
    user: Mapping[str, object],
    locator: SourceRecordLocator,
    actual_usage_stages: list[FieldUsageStage],
    source_field_name: str | None = None,
) -> UserFieldTrace:
    value_status = field_value_status(user.get(field_name)) if field_name in user else "unavailable"
    evidence_values = dict(user)
    if source_field_name is not None and field_name in user:
        evidence_values[source_field_name] = user[field_name]
    evidence = field_trace_evidence(definition, evidence_values, locator)
    return UserFieldTrace(
        user_id=user_id,
        field_name=field_name,
        value_status=value_status,
        source_record_locator=locator,
        evidence=evidence,
        actual_usage_stages=actual_usage_stages,
        prompt_inclusion_status="not_allowlisted",
        omission_reason="field_not_in_prompt_allowlist",
    )


def _interest_prompt_status(
    *,
    user_id: str,
    value_status: ValueStatus,
    source: FieldLineageTraceSource,
) -> tuple[PromptInclusionStatus, OmissionReason]:
    return _prompt_status(
        user_id=user_id,
        field_name="interest_tags",
        value_status=value_status,
        source=source,
    )


def _prompt_status(
    *,
    user_id: str,
    field_name: str,
    value_status: ValueStatus,
    source: FieldLineageTraceSource,
) -> tuple[PromptInclusionStatus, OmissionReason]:
    if field_name not in JINJIANG_PROMPT_V2_PROFILE_FIELDS:
        return "not_allowlisted", "field_not_in_prompt_allowlist"
    if user_id not in source.exposed_user_ids:
        return "not_exposed", "user_not_exposed_to_target_video"
    persisted_status = source.prompt_inclusion_by_user.get(user_id, {}).get(field_name)
    if persisted_status == "included":
        return "included", ""
    if persisted_status == "empty_omitted":
        if value_status == "unavailable":
            return "empty_omitted", "source_value_unavailable"
        return "empty_omitted", "empty_value_omitted_from_prompt"
    if value_status == "unavailable":
        return "empty_omitted", "source_value_unavailable"
    if value_status == "present":
        return "not_rendered", "prompt_summary_not_built"
    return "empty_omitted", "empty_value_omitted_from_prompt"


def _value_status(value: Sequence[str] | None) -> ValueStatus:
    return field_value_status(value)


def field_value_status(value: object) -> ValueStatus:
    if value is None:
        return "unavailable"
    if value == "" or (isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and not value):
        return "empty"
    return "present"


def field_trace_evidence(
    definition: FieldLineageDefinition,
    values: Mapping[str, object],
    locator: SourceRecordLocator,
) -> list[FieldEvidenceReference]:
    if definition.provenance == "Direct Observed Profile Field":
        return []
    if definition.provenance == "Historical Behavioral Evidence":
        source_field = definition.source_fields[0]
        if source_field not in values:
            return []
        return [
            FieldEvidenceReference(
                evidence_kind="historical_aggregate_evidence",
                record_key=locator.record_key,
                source_fields=[source_field],
                matched_values=[f"{source_field}={values[source_field]}"],
            )
        ]
    available_fields = [field for field in definition.source_fields if field in values]
    if not available_fields:
        return []
    return [
        FieldEvidenceReference(
            evidence_kind=(
                "synthetic_experiment_contract"
                if definition.provenance == "Synthetic Experiment Label"
                else "runtime_record_evidence"
                if definition.provenance == "Runtime Simulation Result"
                else "derived_proxy_inputs"
            ),
            record_key=locator.record_key,
            source_fields=available_fields,
            matched_values=[f"{field}={values[field]}" for field in available_fields],
        )
    ]


def field_lineage_coverage_audit(
    catalog: Sequence[FieldLineageDefinition],
    trace_index: Mapping[str, Sequence[UserFieldTrace]],
) -> dict[str, object]:
    field_coverage: list[dict[str, object]] = []
    value_status_counts: Counter[str] = Counter()
    for definition in catalog:
        counts = Counter(
            trace.value_status
            for traces in trace_index.values()
            for trace in traces
            if trace.field_name == definition.field_name
        )
        field_coverage.append(
            {
                "field_name": definition.field_name,
                "value_status_counts": {
                    status: counts.get(status, 0) for status in ("present", "empty", "unavailable")
                },
            }
        )
        value_status_counts.update(counts)
    provenance_field_counts = Counter(definition.provenance for definition in catalog)
    return {
        "user_count": len(trace_index),
        "catalog_field_count": len(catalog),
        "trace_count": sum(len(traces) for traces in trace_index.values()),
        "value_status_counts": {
            status: value_status_counts.get(status, 0) for status in ("present", "empty", "unavailable")
        },
        "provenance_field_counts": dict(sorted(provenance_field_counts.items())),
        "field_coverage": field_coverage,
    }


def _derived_source_artifact_kind(artifact_id: str) -> str:
    return {
        "field_source_records": "allowlisted derived proxy evidence snapshot",
        "sample_manifest_json": "persisted processed research sample record",
        "ranking_runtime_candidates": "persisted ranking candidate record",
    }[artifact_id]


def _integer_value(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip():
        return int(value)
    return 0


def _evidence(rows: Sequence[Mapping[str, object]]) -> list[FieldEvidenceReference]:
    return [FieldEvidenceReference.model_validate(dict(row)) for row in rows]


def _validate_evidence_coverage(
    field_name: str,
    values: Sequence[str],
    evidence: Sequence[FieldEvidenceReference],
) -> None:
    matched_values = {value for item in evidence for value in item.matched_values}
    if matched_values != set(values):
        raise ValueError(f"{field_name} values must exactly match their historical evidence")


def _string_list(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return sorted({str(item).strip() for item in value if str(item).strip()})
