from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .research_explanations import FieldProvenance, FieldUsageStage

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


class FieldLineageTraceModule:
    """Build normalized field definitions and compact per-user trace evidence."""

    def build(self, source: FieldLineageTraceSource) -> FieldLineageTraceBundle:
        source_path = source.artifact_paths.get("field_source_records")
        if not source_path:
            raise ValueError("field trace requires the field_source_records artifact path")

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
                )
            )
            locator = SourceRecordLocator(
                artifact_id="field_source_records",
                relative_path=source_path,
                record_key={"user_id": user_id},
            )
            interest_prompt_status, interest_omission = _interest_prompt_status(
                user_id=user_id,
                value_status=_value_status(interest_tags),
                source=source,
            )
            trace_index[user_id] = [
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
            ]

        return FieldLineageTraceBundle(
            catalog=_catalog(),
            trace_index=trace_index,
            source_records=source_records,
        )


def _catalog() -> list[FieldLineageDefinition]:
    return [
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
    ]


def _interest_prompt_status(
    *,
    user_id: str,
    value_status: ValueStatus,
    source: FieldLineageTraceSource,
) -> tuple[PromptInclusionStatus, OmissionReason]:
    if user_id not in source.exposed_user_ids:
        return "not_exposed", "user_not_exposed_to_target_video"
    persisted_status = source.prompt_inclusion_by_user.get(user_id, {}).get("interest_tags")
    if persisted_status == "included":
        return "included", ""
    if value_status == "unavailable":
        return "empty_omitted", "source_value_unavailable"
    if value_status == "present":
        return "not_rendered", "prompt_summary_not_built"
    return "empty_omitted", "empty_value_omitted_from_prompt"


def _value_status(value: Sequence[str] | None) -> ValueStatus:
    if value is None:
        return "unavailable"
    return "present" if value else "empty"


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
