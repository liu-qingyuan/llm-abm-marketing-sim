from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import tempfile
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from .concurrent_campaign_diagnostics import validate_concurrent_validation_summary
from .concurrent_message_renderer import render_report
from .prompt_field_summary import (
    AGE_LABELS,
    CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
    CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
    EDUCATION_LABELS,
    GENDER_LABELS,
    MONTHLY_INCOME_LABELS,
)
from .safe_serialization import safe_data

CONCURRENT_MESSAGE_REPORT_PAYLOAD_SCHEMA = "concurrent-message-report-payload-v1"
CONCURRENT_MESSAGE_USERS_SCHEMA = "concurrent-message-users-v1"
CONCURRENT_MESSAGE_RUNTIME_SCHEMA = "concurrent-message-runtime-v1"
CONCURRENT_MESSAGE_DIAGNOSTICS_SCHEMA = "concurrent-message-diagnostics-v1"
CONCURRENT_MESSAGE_DECISION_TRACE_SCHEMA = "concurrent-message-decision-trace-v1"
CONCURRENT_MESSAGE_FIELD_LINEAGE_SCHEMA = "concurrent-message-field-lineage-v1"
CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_SCHEMA = "concurrent-message-artifact-manifest-v1"

CONCURRENT_MESSAGE_CANDIDATE_CSV = "concurrent_runtime_candidates.csv"
CONCURRENT_MESSAGE_PAIR_CSV = "concurrent_runtime_pairs.csv"
CONCURRENT_MESSAGE_TERMINAL_CSV = "concurrent_runtime_terminal_rows.csv"
CONCURRENT_MESSAGE_STEP_JSON = "concurrent_runtime_steps.json"
CONCURRENT_MESSAGE_VALIDATION_JSON = "concurrent_validation.json"
CONCURRENT_MESSAGE_CAMPAIGN_DIAGNOSTICS_JSON = "concurrent_campaign_diagnostics.json"
CONCURRENT_MESSAGE_MESSAGE_JSON = "message_snapshot.json"
CONCURRENT_MESSAGE_SAMPLE_JSON = "sample_manifest.json"
CONCURRENT_MESSAGE_SAMPLE_CSV = "sample_manifest.csv"
CONCURRENT_MESSAGE_CONFIG_JSON = "config_snapshot.json"
CONCURRENT_MESSAGE_SEED_AUDIT_JSON = "seed_first_sample_audit.json"

CONCURRENT_MESSAGE_RUNTIME_JSON = "concurrent_message_runtime.json"
CONCURRENT_MESSAGE_PRIMARY_ACTIONS_CSV = "concurrent_message_primary_actions.csv"
CONCURRENT_MESSAGE_PROVIDER_FAILURES_CSV = "concurrent_message_provider_failures.csv"
CONCURRENT_MESSAGE_USERS_JSON = "concurrent_message_users.json"
CONCURRENT_MESSAGE_USERS_CSV = "concurrent_message_users.csv"
CONCURRENT_MESSAGE_DECISION_TRACE_JSON = "concurrent_message_decision_trace.json"
CONCURRENT_MESSAGE_DECISION_TRACE_CSV = "concurrent_message_decision_trace.csv"
CONCURRENT_MESSAGE_FIELD_LINEAGE_JSON = "concurrent_message_field_lineage.json"
CONCURRENT_MESSAGE_DIAGNOSTICS_JSON = "concurrent_message_diagnostics.json"
CONCURRENT_MESSAGE_REPORT_PAYLOAD_JSON = "concurrent_message_report_payload.json"
CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON = "artifact_manifest.json"
CONCURRENT_MESSAGE_REPORT_HTML = "report.html"

_POSITIVE_ACTIONS = frozenset({"like", "comment", "share"})


@dataclass(frozen=True)
class _ConcurrentMessageArtifactSpec:
    name: str
    relative_path: str
    manifest_key: str | None = None
    runtime_key: str | None = None
    download_key: str | None = None
    optional: bool = False


_CANONICAL_ARTIFACT_TABLE = (
    _ConcurrentMessageArtifactSpec("config_snapshot", CONCURRENT_MESSAGE_CONFIG_JSON, "config_snapshot", "config_snapshot"),
    _ConcurrentMessageArtifactSpec("message_snapshot", CONCURRENT_MESSAGE_MESSAGE_JSON, "message_snapshot", "message_snapshot"),
    _ConcurrentMessageArtifactSpec(
        "sample_manifest_json", CONCURRENT_MESSAGE_SAMPLE_JSON, "sample_manifest_json", "sample_manifest_json", "sample_manifest_json"
    ),
    _ConcurrentMessageArtifactSpec(
        "sample_manifest_csv", CONCURRENT_MESSAGE_SAMPLE_CSV, "sample_manifest_csv", "sample_manifest_csv", "sample_manifest_csv"
    ),
    _ConcurrentMessageArtifactSpec("rankings_csv", CONCURRENT_MESSAGE_CANDIDATE_CSV, "rankings_csv", "runtime_candidates_csv", "rankings_csv"),
    _ConcurrentMessageArtifactSpec("exposures_csv", CONCURRENT_MESSAGE_PAIR_CSV, "exposures_csv", "runtime_pairs_csv", "exposures_csv"),
    _ConcurrentMessageArtifactSpec(
        "terminals_csv", CONCURRENT_MESSAGE_TERMINAL_CSV, "terminals_csv", "runtime_terminal_rows_csv", "terminals_csv"
    ),
    _ConcurrentMessageArtifactSpec("runtime_steps_json", CONCURRENT_MESSAGE_STEP_JSON, "runtime_steps_json", "runtime_steps_json"),
    _ConcurrentMessageArtifactSpec("validation_evidence", CONCURRENT_MESSAGE_VALIDATION_JSON, "validation_evidence", "validation_evidence", "validation_evidence"),
    _ConcurrentMessageArtifactSpec(
        "campaign_diagnostics_json", CONCURRENT_MESSAGE_CAMPAIGN_DIAGNOSTICS_JSON, "campaign_diagnostics_json", "campaign_diagnostics_json"
    ),
    _ConcurrentMessageArtifactSpec("runtime_contract", CONCURRENT_MESSAGE_RUNTIME_JSON, "runtime_contract", None, "runtime_contract"),
    _ConcurrentMessageArtifactSpec("primary_actions_csv", CONCURRENT_MESSAGE_PRIMARY_ACTIONS_CSV, "primary_actions_csv", "primary_actions_csv", "primary_actions_csv"),
    _ConcurrentMessageArtifactSpec(
        "provider_failures_csv", CONCURRENT_MESSAGE_PROVIDER_FAILURES_CSV, "provider_failures_csv", "provider_failures_csv", "provider_failures_csv"
    ),
    _ConcurrentMessageArtifactSpec("users_json", CONCURRENT_MESSAGE_USERS_JSON, "users_json", None, "users_json"),
    _ConcurrentMessageArtifactSpec("users_csv", CONCURRENT_MESSAGE_USERS_CSV, "users_csv", None, "users_csv"),
    _ConcurrentMessageArtifactSpec("decision_trace_json", CONCURRENT_MESSAGE_DECISION_TRACE_JSON, "decision_trace_json", None, "decision_trace_json"),
    _ConcurrentMessageArtifactSpec("decision_trace_csv", CONCURRENT_MESSAGE_DECISION_TRACE_CSV, "decision_trace_csv", None, "decision_trace_csv"),
    _ConcurrentMessageArtifactSpec("field_lineage", CONCURRENT_MESSAGE_FIELD_LINEAGE_JSON, "field_lineage", None, "field_lineage"),
    _ConcurrentMessageArtifactSpec("diagnostics_contract", CONCURRENT_MESSAGE_DIAGNOSTICS_JSON, "diagnostics_contract", None, "diagnostics_contract"),
    _ConcurrentMessageArtifactSpec("report_payload", CONCURRENT_MESSAGE_REPORT_PAYLOAD_JSON, "report_payload", None, "report_payload"),
    _ConcurrentMessageArtifactSpec("report_html", CONCURRENT_MESSAGE_REPORT_HTML, "report_html"),
    _ConcurrentMessageArtifactSpec("sample_audit", CONCURRENT_MESSAGE_SEED_AUDIT_JSON, "sample_audit", optional=True),
    _ConcurrentMessageArtifactSpec("artifact_manifest", CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON, download_key="manifest"),
)


def _canonical_download_view() -> dict[str, str]:
    return {
        spec.download_key: spec.relative_path
        for spec in _CANONICAL_ARTIFACT_TABLE
        if spec.download_key is not None
    }


def _canonical_runtime_view() -> dict[str, str]:
    return {
        spec.runtime_key: spec.relative_path
        for spec in _CANONICAL_ARTIFACT_TABLE
        if spec.runtime_key is not None
    }


def _canonical_manifest_view(run_path: Path) -> dict[str, str]:
    return {
        spec.manifest_key: spec.relative_path
        for spec in _CANONICAL_ARTIFACT_TABLE
        if spec.manifest_key is not None and (not spec.optional or (run_path / spec.relative_path).is_file())
    }


_PRIMARY_CONTEXT_LABELS = {
    "activity_score": "Activity score",
    "global_influence_score": "Global influence score",
    "local_influence_score": "Local influence score",
    "environmental_consciousness_coef": "Environmental consciousness coef",
    "epistemic_value_weight": "Epistemic value weight",
    "environmental_value_weight": "Environmental value weight",
    "functional_value_weight": "Functional value weight",
    "health_value_weight": "Health value weight",
    "emotional_value_weight": "Emotional value weight",
    "social_value_weight": "Social value weight",
    "hotel_class": "Recent hotel class",
    "travel_purpose": "Recent travel purpose",
}
_SHADOW_ONLY_FIELDS = {
    "concurrent_gender": ("Synthetic gender label", GENDER_LABELS),
    "concurrent_age": ("Synthetic age label", AGE_LABELS),
    "concurrent_education": ("Synthetic education label", EDUCATION_LABELS),
    "concurrent_monthly_income": ("Synthetic monthly income label", MONTHLY_INCOME_LABELS),
}
_SAFE_SAMPLE_FIELDS = (
    "user_id",
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
    "latent_epistemic_value_weight",
    "latent_environmental_value_weight",
    "latent_functional_value_weight",
    "latent_health_value_weight",
    "latent_emotional_value_weight",
    "latent_social_value_weight",
    "latent_hotel_class",
    "latent_travel_purpose",
    "latent_gender",
    "latent_age",
    "latent_education",
    "latent_monthly_income",
)
_USER_CSV_FIELDS = (
    *_SAFE_SAMPLE_FIELDS,
    "exposure_count",
    "distinct_message_count",
    "exposed_message_ids",
    "primary_positive_action_count",
    "primary_provider_failure_count",
    "shadow_provider_failure_count",
)
_TRACE_CSV_FIELDS = (
    "trace_id",
    "pair_id",
    "time_step",
    "message_id",
    "message_title",
    "user_id",
    "latent_class",
    "is_seed",
    "selection_reason",
    "ranking_position",
    "personalized_delivery_score",
    "primary_status",
    "primary_action",
    "primary_probability",
    "primary_confidence",
    "primary_reason",
    "shadow_status",
    "shadow_action",
    "shadow_probability",
    "shadow_confidence",
    "shadow_reason",
    "provider_status",
    "primary_shadow_disagreement",
)
_PRIMARY_ACTION_FIELDS = (
    "pair_id",
    "time_step",
    "message_id",
    "user_id",
    "action",
    "engage",
    "probability",
    "confidence",
    "reason",
    "decision_source",
    "provider_status",
    "campaign_feedback_committed",
)
_PROVIDER_FAILURE_FIELDS = (
    "terminal_row_id",
    "pair_id",
    "time_step",
    "message_id",
    "user_id",
    "decision_variant",
    "failure_type",
    "provider_metadata",
)


class ConcurrentMessageDownloadLinks(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_payload: str = _canonical_download_view()["report_payload"]
    users_json: str = _canonical_download_view()["users_json"]
    users_csv: str = _canonical_download_view()["users_csv"]
    decision_trace_json: str = _canonical_download_view()["decision_trace_json"]
    decision_trace_csv: str = _canonical_download_view()["decision_trace_csv"]
    runtime_contract: str = _canonical_download_view()["runtime_contract"]
    diagnostics_contract: str = _canonical_download_view()["diagnostics_contract"]
    field_lineage: str = _canonical_download_view()["field_lineage"]
    validation_evidence: str = _canonical_download_view()["validation_evidence"]
    sample_manifest_json: str = _canonical_download_view()["sample_manifest_json"]
    sample_manifest_csv: str = _canonical_download_view()["sample_manifest_csv"]
    rankings_csv: str = _canonical_download_view()["rankings_csv"]
    exposures_csv: str = _canonical_download_view()["exposures_csv"]
    terminals_csv: str = _canonical_download_view()["terminals_csv"]
    primary_actions_csv: str = _canonical_download_view()["primary_actions_csv"]
    provider_failures_csv: str = _canonical_download_view()["provider_failures_csv"]
    manifest: str = _canonical_download_view()["manifest"]

    @model_validator(mode="after")
    def _validate_relative_paths(self) -> ConcurrentMessageDownloadLinks:
        for field_name, relative_path in self.model_dump(mode="json").items():
            if not isinstance(relative_path, str) or not relative_path:
                raise ValueError(f"download path {field_name} must be a non-empty string")
            path = Path(relative_path)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"download path {field_name} must remain within the run directory")
        return self


class ConcurrentMessageFieldLineageEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_name: str
    label: str
    source_artifact: str
    evidence_class: Literal["persisted_input", "reconstructed_context", "aggregate_evidence"]
    prompt_visibility: Literal["primary_allowed", "shadow_only", "platform_internal", "report_only"]
    usage_stages: list[str]
    description: str


class ConcurrentMessageUserRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    activity_score: float
    activity_video_score: float
    activity_comment_score: float
    activity_reply_score: float
    global_influence_score: float
    local_influence_score: float
    local_network_score: float
    local_recognition_score: float
    sample_source_scope: str
    is_seed: bool
    sample_role: str
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
    exposure_count: int
    distinct_message_count: int
    exposed_message_ids: list[str]
    primary_positive_action_count: int
    primary_provider_failure_count: int
    shadow_provider_failure_count: int


class ConcurrentMessageTraceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    pair_id: str
    time_step: int
    message_id: str
    message_title: str
    message_body: str
    user_id: str
    latent_class: str
    is_seed: bool
    selection_reason: str
    ranking_position: int
    personalized_delivery_score: float
    primary_status: str
    primary_action: str
    primary_probability: float | None = None
    primary_confidence: float | None = None
    primary_reason: str = ""
    primary_decision_source: str = ""
    primary_prompt_version: str
    primary_decision: dict[str, Any]
    shadow_status: str
    shadow_action: str
    shadow_probability: float | None = None
    shadow_confidence: float | None = None
    shadow_reason: str = ""
    shadow_decision_source: str = ""
    shadow_prompt_version: str
    shadow_decision: dict[str, Any]
    provider_status: str
    primary_shadow_disagreement: bool
    primary_context: dict[str, Any]
    primary_peer_context: dict[str, Any]
    shadow_context: dict[str, Any]
    shadow_peer_context: dict[str, Any]
    shadow_added_fields: dict[str, str]
    prompt_field_inclusion: dict[str, dict[str, str]]
    field_differences: list[dict[str, Any]]
    ranking_evidence: dict[str, Any]
    aggregate_evidence: dict[str, Any]


class ConcurrentMessageUsersDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal['concurrent-message-users-v1'] = CONCURRENT_MESSAGE_USERS_SCHEMA
    rows: list[ConcurrentMessageUserRecord]


class ConcurrentMessageDecisionTraceDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal['concurrent-message-decision-trace-v1'] = CONCURRENT_MESSAGE_DECISION_TRACE_SCHEMA
    primary_prompt_token: str
    shadow_prompt_token: str
    rows: list[ConcurrentMessageTraceRecord]

    @model_validator(mode="after")
    def _validate_prompt_tokens(self) -> ConcurrentMessageDecisionTraceDocument:
        _validate_prompt_tokens(self.primary_prompt_token, self.shadow_prompt_token)
        return self


class ConcurrentMessageRuntimeDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal['concurrent-message-runtime-v1'] = CONCURRENT_MESSAGE_RUNTIME_SCHEMA
    configuration: dict[str, Any]
    prompt_tokens: dict[str, str]
    counts: dict[str, Any]
    artifacts: dict[str, str]

    @model_validator(mode="after")
    def _validate_runtime(self) -> ConcurrentMessageRuntimeDocument:
        primary = self.prompt_tokens.get("primary")
        shadow = self.prompt_tokens.get("shadow")
        _validate_prompt_tokens(primary, shadow)
        for key, relative_path in self.artifacts.items():
            if not isinstance(relative_path, str) or not relative_path:
                raise ValueError(f"runtime artifact {key} must be a non-empty path")
            path = Path(relative_path)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"runtime artifact {key} must remain within the run directory")
        return self


class ConcurrentMessageDiagnosticsDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal['concurrent-message-diagnostics-v1'] = CONCURRENT_MESSAGE_DIAGNOSTICS_SCHEMA
    validation_summary: dict[str, Any]
    campaign_diagnostics: dict[str, Any]
    field_lineage_path: str


class ConcurrentMessageFieldLineageDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal['concurrent-message-field-lineage-v1'] = CONCURRENT_MESSAGE_FIELD_LINEAGE_SCHEMA
    entries: list[ConcurrentMessageFieldLineageEntry]


class ConcurrentMessageReportPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal['concurrent-message-report-payload-v1'] = CONCURRENT_MESSAGE_REPORT_PAYLOAD_SCHEMA
    title: str
    run: dict[str, Any]
    messages: list[dict[str, Any]]
    prompt_contract: dict[str, Any]
    variant_provider_accounting: dict[str, Any]
    campaign_funnel: dict[str, Any]
    message_allocation: dict[str, Any]
    primary_audience_response: dict[str, Any]
    campaign_feedback_effect: dict[str, Any]
    demographic_decision_sensitivity: dict[str, Any]
    validation_summary: dict[str, Any]
    downloads: ConcurrentMessageDownloadLinks
    notes: list[str]
    exposure_rows: list[ConcurrentMessageTraceRecord]
    user_rows: list[ConcurrentMessageUserRecord]
    field_lineage: list[ConcurrentMessageFieldLineageEntry]


class ConcurrentMessageArtifactManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal['concurrent-message-artifact-manifest-v1'] = CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_SCHEMA
    report_schema: str
    users_schema: str
    runtime_schema: str
    diagnostics_schema: str
    decision_trace_schema: str
    validation_schema: str
    primary_prompt_token: str
    shadow_prompt_token: str
    artifacts: dict[str, str]
    sha256: dict[str, str]

    @model_validator(mode="after")
    def _validate_manifest(self) -> ConcurrentMessageArtifactManifest:
        _validate_prompt_tokens(self.primary_prompt_token, self.shadow_prompt_token)
        expected_tokens = {
            "report_schema": CONCURRENT_MESSAGE_REPORT_PAYLOAD_SCHEMA,
            "users_schema": CONCURRENT_MESSAGE_USERS_SCHEMA,
            "runtime_schema": CONCURRENT_MESSAGE_RUNTIME_SCHEMA,
            "diagnostics_schema": CONCURRENT_MESSAGE_DIAGNOSTICS_SCHEMA,
            "decision_trace_schema": CONCURRENT_MESSAGE_DECISION_TRACE_SCHEMA,
        }
        for field_name, expected_value in expected_tokens.items():
            if getattr(self, field_name) != expected_value:
                raise ValueError(f"unsupported manifest token for {field_name}")
        if not self.validation_schema:
            raise ValueError("manifest must record the validation schema token")
        if set(self.artifacts) != set(self.sha256):
            raise ValueError("artifact manifest paths and hashes must share the same keys")
        if len(set(self.artifacts.values())) != len(self.artifacts):
            raise ValueError("artifact manifest paths must be unique")
        for key, relative_path in self.artifacts.items():
            path = Path(relative_path)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"artifact path {key} escapes the run directory")
        return self


class _BuildResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    report_payload: ConcurrentMessageReportPayload
    users_document: ConcurrentMessageUsersDocument
    decision_trace_document: ConcurrentMessageDecisionTraceDocument
    runtime_document: ConcurrentMessageRuntimeDocument
    diagnostics_document: ConcurrentMessageDiagnosticsDocument
    field_lineage_document: ConcurrentMessageFieldLineageDocument
    primary_actions_rows: list[dict[str, Any]]
    provider_failure_rows: list[dict[str, Any]]
    sample_manifest_rows: list[dict[str, Any]]
    report_html: str


class ConcurrentMessageSourceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    config_snapshot: dict[str, Any]
    message_snapshot: list[dict[str, Any]]
    sample_manifest_rows: list[dict[str, Any]]
    sample_audit: dict[str, Any] | None
    candidate_rows: list[dict[str, Any]]
    pair_rows: list[dict[str, Any]]
    terminal_rows: list[dict[str, Any]]
    step_rows: list[dict[str, Any]]
    validation_summary: dict[str, Any]
    campaign_diagnostics: dict[str, Any]


class ConcurrentMessageArtifactClosure(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid", frozen=True)

    run_dir: Path
    manifest: ConcurrentMessageArtifactManifest
    artifact_paths: dict[str, Path]
    source_evidence: ConcurrentMessageSourceEvidence
    report_payload: ConcurrentMessageReportPayload
    users_document: ConcurrentMessageUsersDocument
    decision_trace_document: ConcurrentMessageDecisionTraceDocument
    runtime_document: ConcurrentMessageRuntimeDocument
    diagnostics_document: ConcurrentMessageDiagnosticsDocument
    field_lineage_document: ConcurrentMessageFieldLineageDocument
    primary_actions_rows: list[dict[str, Any]]
    provider_failure_rows: list[dict[str, Any]]
    source_files: tuple[str, ...]
    artifact_hashes: dict[str, str]
    report_html: str


def write_concurrent_message_report_artifacts(
    output_dir: str | Path,
    *,
    title: str,
    config_snapshot: Mapping[str, Any],
    message_snapshot: Sequence[Mapping[str, Any]],
    sample_users: Sequence[Mapping[str, Any]],
    sample_audit: Mapping[str, Any] | None,
    candidate_rows: Sequence[Mapping[str, Any]],
    pair_rows: Sequence[Mapping[str, Any]],
    terminal_rows: Sequence[Mapping[str, Any]],
    step_rows: Sequence[Mapping[str, Any]],
    validation_summary: Mapping[str, Any],
    campaign_diagnostics: Mapping[str, Any],
) -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    build = _build_report_bundle(
        title=title,
        config_snapshot=config_snapshot,
        message_snapshot=message_snapshot,
        sample_users=sample_users,
        candidate_rows=candidate_rows,
        pair_rows=pair_rows,
        terminal_rows=terminal_rows,
        step_rows=step_rows,
        validation_summary=validation_summary,
        campaign_diagnostics=campaign_diagnostics,
    )

    _write_json(output_path / CONCURRENT_MESSAGE_CONFIG_JSON, config_snapshot)
    _write_json(output_path / CONCURRENT_MESSAGE_MESSAGE_JSON, list(message_snapshot))
    _write_json(output_path / CONCURRENT_MESSAGE_SAMPLE_JSON, build.sample_manifest_rows)
    _write_csv(output_path / CONCURRENT_MESSAGE_SAMPLE_CSV, _SAFE_SAMPLE_FIELDS, build.sample_manifest_rows)
    if sample_audit is not None:
        _write_json(output_path / CONCURRENT_MESSAGE_SEED_AUDIT_JSON, sample_audit)
    _write_csv(output_path / CONCURRENT_MESSAGE_CANDIDATE_CSV, _csv_fieldnames(candidate_rows), list(candidate_rows))
    _write_csv(output_path / CONCURRENT_MESSAGE_PAIR_CSV, _csv_fieldnames(pair_rows), list(pair_rows))
    _write_csv(output_path / CONCURRENT_MESSAGE_TERMINAL_CSV, _csv_fieldnames(terminal_rows), list(terminal_rows))
    _write_json(output_path / CONCURRENT_MESSAGE_STEP_JSON, list(step_rows))
    _write_json(output_path / CONCURRENT_MESSAGE_VALIDATION_JSON, validation_summary)
    _write_json(output_path / CONCURRENT_MESSAGE_CAMPAIGN_DIAGNOSTICS_JSON, campaign_diagnostics)
    _write_json(output_path / CONCURRENT_MESSAGE_RUNTIME_JSON, build.runtime_document.model_dump(mode="json"))
    _write_csv(output_path / CONCURRENT_MESSAGE_PRIMARY_ACTIONS_CSV, _PRIMARY_ACTION_FIELDS, build.primary_actions_rows)
    _write_csv(output_path / CONCURRENT_MESSAGE_PROVIDER_FAILURES_CSV, _PROVIDER_FAILURE_FIELDS, build.provider_failure_rows)
    _write_json(output_path / CONCURRENT_MESSAGE_USERS_JSON, build.users_document.model_dump(mode="json"))
    _write_csv(
        output_path / CONCURRENT_MESSAGE_USERS_CSV,
        _USER_CSV_FIELDS,
        [_csv_user_row(row.model_dump(mode="json")) for row in build.users_document.rows],
    )
    _write_json(output_path / CONCURRENT_MESSAGE_DECISION_TRACE_JSON, build.decision_trace_document.model_dump(mode="json"))
    _write_csv(
        output_path / CONCURRENT_MESSAGE_DECISION_TRACE_CSV,
        _TRACE_CSV_FIELDS,
        [_csv_trace_row(row.model_dump(mode="json")) for row in build.decision_trace_document.rows],
    )
    _write_json(output_path / CONCURRENT_MESSAGE_FIELD_LINEAGE_JSON, build.field_lineage_document.model_dump(mode="json"))
    _write_json(output_path / CONCURRENT_MESSAGE_DIAGNOSTICS_JSON, build.diagnostics_document.model_dump(mode="json"))
    _write_json(output_path / CONCURRENT_MESSAGE_REPORT_PAYLOAD_JSON, build.report_payload.model_dump(mode="json"))
    (output_path / CONCURRENT_MESSAGE_REPORT_HTML).write_text(build.report_html, encoding="utf-8")

    manifest = _build_manifest(output_path, validation_summary)
    _write_json(output_path / CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON, manifest.model_dump(mode="json"))
    return output_path / CONCURRENT_MESSAGE_REPORT_HTML


def close_concurrent_message_artifacts(run_dir: str | Path) -> ConcurrentMessageArtifactClosure:
    """Read, validate, and close one persisted Concurrent message artifact tuple.

    This interface is read-only. It returns the typed evidence closure and the
    exact renderer bytes that match the persisted report hash; callers decide
    whether those bytes should be written.
    """
    run_path = Path(run_dir)
    if run_path.is_symlink():
        raise ValueError("Concurrent message run directory must not be a symlink")
    if not run_path.is_dir():
        raise FileNotFoundError(f"Concurrent message run directory does not exist: {run_path}")
    manifest_path = run_path / CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Concurrent message rebuild requires {manifest_path.name}")
    manifest = ConcurrentMessageArtifactManifest.model_validate(_read_json_object(manifest_path))
    _ensure_no_unexpected_root_files(run_path, manifest)
    expected_artifacts = _canonical_manifest_view(run_path)
    if manifest.artifacts != expected_artifacts:
        raise ValueError("concurrent message manifest artifacts do not match the canonical artifact table")
    artifacts = {name: _artifact_path(run_path, relative_path, name) for name, relative_path in manifest.artifacts.items()}
    _validate_input_hashes(manifest, artifacts)

    config_snapshot = _read_json_object(artifacts["config_snapshot"])
    message_snapshot = _read_json_records(artifacts["message_snapshot"], "message snapshot")
    sample_manifest_rows = _read_json_records(artifacts["sample_manifest_json"], "sample manifest")
    sample_audit = _read_json_object(artifacts["sample_audit"]) if "sample_audit" in artifacts else None
    candidate_rows = _read_csv_rows(artifacts["rankings_csv"])
    pair_rows = _read_csv_rows(artifacts["exposures_csv"])
    terminal_rows = _read_csv_rows(artifacts["terminals_csv"])
    step_rows = _read_json_records(artifacts["runtime_steps_json"], "runtime steps")
    validation_summary = _read_json_object(artifacts["validation_evidence"])
    campaign_diagnostics = _read_json_object(artifacts["campaign_diagnostics_json"])
    users_document = ConcurrentMessageUsersDocument.model_validate(_read_json_object(artifacts["users_json"]))
    decision_trace_document = ConcurrentMessageDecisionTraceDocument.model_validate(
        _read_json_object(artifacts["decision_trace_json"])
    )
    runtime_document = ConcurrentMessageRuntimeDocument.model_validate(_read_json_object(artifacts["runtime_contract"]))
    diagnostics_document = ConcurrentMessageDiagnosticsDocument.model_validate(
        _read_json_object(artifacts["diagnostics_contract"])
    )
    field_lineage_document = ConcurrentMessageFieldLineageDocument.model_validate(_read_json_object(artifacts["field_lineage"]))
    payload = ConcurrentMessageReportPayload.model_validate(_read_json_object(artifacts["report_payload"]))
    primary_actions_rows = _read_csv_rows(artifacts["primary_actions_csv"])
    provider_failure_rows = _read_csv_rows(artifacts["provider_failures_csv"])
    if config_snapshot != runtime_document.configuration:
        raise ValueError("config snapshot does not close to the persisted concurrent message runtime contract")

    build = _build_report_bundle(
        title=payload.title,
        config_snapshot=runtime_document.configuration,
        message_snapshot=message_snapshot,
        sample_users=sample_manifest_rows,
        candidate_rows=candidate_rows,
        pair_rows=pair_rows,
        terminal_rows=terminal_rows,
        step_rows=step_rows,
        validation_summary=validation_summary,
        campaign_diagnostics=campaign_diagnostics,
        expected_report_sha256=manifest.sha256["report_html"],
    )
    _validate_documents_against_build(
        run_path=run_path,
        manifest=manifest,
        payload=payload,
        users_document=users_document,
        decision_trace_document=decision_trace_document,
        runtime_document=runtime_document,
        diagnostics_document=diagnostics_document,
        field_lineage_document=field_lineage_document,
        primary_actions_rows=primary_actions_rows,
        provider_failure_rows=provider_failure_rows,
        build=build,
    )
    artifact_paths = dict(artifacts)
    artifact_paths["artifact_manifest"] = manifest_path
    source_files = tuple(
        sorted(path.relative_to(run_path).as_posix() for path in run_path.rglob("*") if path.is_file())
    )
    artifact_hashes = {CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON: _sha256_file(manifest_path)}
    artifact_hashes.update(
        {
            manifest.artifacts[name]: _sha256_file(path)
            for name, path in artifacts.items()
            if path.is_file()
        }
    )
    return ConcurrentMessageArtifactClosure(
        run_dir=run_path,
        manifest=manifest,
        artifact_paths=artifact_paths,
        source_evidence=ConcurrentMessageSourceEvidence(
            config_snapshot=config_snapshot,
            message_snapshot=message_snapshot,
            sample_manifest_rows=sample_manifest_rows,
            sample_audit=sample_audit,
            candidate_rows=candidate_rows,
            pair_rows=pair_rows,
            terminal_rows=terminal_rows,
            step_rows=step_rows,
            validation_summary=validation_summary,
            campaign_diagnostics=campaign_diagnostics,
        ),
        report_payload=payload,
        users_document=users_document,
        decision_trace_document=decision_trace_document,
        runtime_document=runtime_document,
        diagnostics_document=diagnostics_document,
        field_lineage_document=field_lineage_document,
        primary_actions_rows=primary_actions_rows,
        provider_failure_rows=provider_failure_rows,
        source_files=source_files,
        artifact_hashes=artifact_hashes,
        report_html=build.report_html,
    )


def rebuild_concurrent_message_report(
    run_dir: str | Path,
    *,
    destination_dir: str | Path | None = None,
) -> Path:
    """Rebuild a report exactly in place or publish an immutable presentation candidate.

    With ``destination_dir=None`` this preserves the historical exact in-place
    rebuild contract and returns ``run_dir/report.html``. With an explicit
    destination, the validated persisted source tuple is copied into a unique
    sibling staging directory, rendered with the public Editorial default, and
    validated again before an atomic rename; the source is never modified and
    failures leave both the destination and staging directory absent. The
    returned path is the candidate's ``report.html``. Release contracts and
    deployment validation remain the responsibility of the release module.
    """
    if destination_dir is None:
        closure = close_concurrent_message_artifacts(run_dir)
        report_path = closure.artifact_paths["report_html"]
        _atomic_write_text(report_path, closure.report_html)
        return report_path

    source_path = Path(run_dir)
    destination_path = _validate_presentation_destination(source_path, Path(destination_dir))
    closure = close_concurrent_message_artifacts(source_path)
    source_hashes = dict(closure.artifact_hashes)
    staging_path: Path | None = None
    try:
        staging_path = _create_presentation_staging_directory(destination_path)
        _copy_presentation_artifacts(closure, staging_path)
        _atomic_write_text(
            staging_path / CONCURRENT_MESSAGE_REPORT_HTML,
            render_report(closure.report_payload),
        )
        manifest = _build_manifest(staging_path, closure.source_evidence.validation_summary)
        _write_json(staging_path / CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON, manifest.model_dump(mode="json"))

        _validate_presentation_candidate(
            source_closure=closure,
            candidate_dir=staging_path,
            source_hashes=source_hashes,
        )
        rebuild_concurrent_message_report(staging_path)
        _validate_presentation_candidate(
            source_closure=closure,
            candidate_dir=staging_path,
            source_hashes=source_hashes,
        )
        _assert_source_hashes_unchanged(source_path, source_hashes)
        if os.path.lexists(destination_path):
            raise FileExistsError(f"presentation destination appeared during rebuild: {destination_path}")
        if os.stat(staging_path).st_dev != os.stat(destination_path.parent).st_dev:
            raise OSError("presentation staging and destination are on different filesystems")
        staging_path.replace(destination_path)
        staging_path = None
        return destination_path / CONCURRENT_MESSAGE_REPORT_HTML
    finally:
        if staging_path is not None:
            _remove_presentation_staging(staging_path)


def _validate_presentation_destination(source_path: Path, destination_path: Path) -> Path:
    if source_path.is_symlink():
        raise ValueError("presentation source directory must not be a symlink")
    if not source_path.is_dir():
        raise FileNotFoundError(f"Concurrent message run directory does not exist: {source_path}")
    if ".." in destination_path.parts:
        raise ValueError("presentation destination path must not contain '..'")
    if os.path.lexists(destination_path):
        raise FileExistsError(f"presentation destination already exists: {destination_path}")

    source_absolute = source_path.absolute()
    source_resolved = source_path.resolve(strict=True)
    destination_absolute = destination_path.absolute()
    destination_resolved = destination_path.resolve(strict=False)
    if source_absolute != source_resolved:
        raise ValueError("presentation source path must not contain symlink components")
    if destination_absolute != destination_resolved:
        raise ValueError("presentation destination path must not contain symlink components")
    if (
        destination_resolved == source_resolved
        or destination_resolved.is_relative_to(source_resolved)
        or source_resolved.is_relative_to(destination_resolved)
    ):
        raise ValueError("presentation source and destination paths must not overlap")

    existing_parent = destination_path.parent
    while not os.path.lexists(existing_parent):
        parent = existing_parent.parent
        if parent == existing_parent:
            break
        existing_parent = parent
    if not existing_parent.is_dir() or existing_parent.is_symlink():
        raise ValueError("presentation destination parent must be a regular directory")
    if os.stat(source_resolved).st_dev != os.stat(existing_parent).st_dev:
        raise OSError("presentation source and destination are on different filesystems")
    return destination_path


def _create_presentation_staging_directory(destination_path: Path) -> Path:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if destination_path.parent.is_symlink():
        raise ValueError("presentation destination parent must not be a symlink")
    staging_path = Path(
        tempfile.mkdtemp(
            prefix=f".{destination_path.name}.",
            suffix=".staging",
            dir=destination_path.parent,
        )
    )
    if os.stat(staging_path).st_dev != os.stat(destination_path.parent).st_dev:
        _remove_presentation_staging(staging_path)
        raise OSError("presentation staging and destination are on different filesystems")
    return staging_path


def _copy_presentation_artifacts(closure: ConcurrentMessageArtifactClosure, candidate_dir: Path) -> None:
    for name, relative_path in closure.manifest.artifacts.items():
        if name == "report_html":
            continue
        source_artifact = closure.artifact_paths[name]
        destination_artifact = candidate_dir / relative_path
        shutil.copyfile(source_artifact, destination_artifact)


def _validate_presentation_candidate(
    *,
    source_closure: ConcurrentMessageArtifactClosure,
    candidate_dir: Path,
    source_hashes: Mapping[str, str],
) -> ConcurrentMessageArtifactClosure:
    candidate_closure = close_concurrent_message_artifacts(candidate_dir)
    for name, relative_path in source_closure.manifest.artifacts.items():
        if name == "report_html":
            continue
        expected_hash = source_hashes[relative_path]
        if candidate_closure.artifact_hashes.get(relative_path) != expected_hash:
            raise ValueError(f"presentation artifact was not copied byte-identically: {relative_path}")
    return candidate_closure


def _assert_source_hashes_unchanged(source_path: Path, expected_hashes: Mapping[str, str]) -> None:
    actual_files: set[str] = set()
    for path in source_path.rglob("*"):
        relative_path = path.relative_to(source_path).as_posix()
        if path.is_symlink():
            raise ValueError(f"presentation source artifacts changed during rebuild: {relative_path}")
        if path.is_file():
            actual_files.add(relative_path)
        elif not path.is_dir():
            raise ValueError(f"presentation source artifacts changed during rebuild: {relative_path}")
    if actual_files != set(expected_hashes):
        raise ValueError("presentation source artifact set changed during rebuild")
    actual_hashes = {
        relative_path: _sha256_file(source_path / relative_path)
        for relative_path in expected_hashes
    }
    if actual_hashes != dict(expected_hashes):
        raise ValueError("presentation source artifacts changed during rebuild")


def _remove_presentation_staging(staging_path: Path) -> None:
    if not os.path.lexists(staging_path):
        return
    if staging_path.is_symlink() or not staging_path.is_dir():
        staging_path.unlink()
        return
    shutil.rmtree(staging_path)


def _build_report_bundle(
    *,
    title: str,
    config_snapshot: Mapping[str, Any],
    message_snapshot: Sequence[Mapping[str, Any]],
    sample_users: Sequence[Mapping[str, Any]],
    candidate_rows: Sequence[Mapping[str, Any]],
    pair_rows: Sequence[Mapping[str, Any]],
    terminal_rows: Sequence[Mapping[str, Any]],
    step_rows: Sequence[Mapping[str, Any]],
    validation_summary: Mapping[str, Any],
    campaign_diagnostics: Mapping[str, Any],
    expected_report_sha256: str | None = None,
) -> _BuildResult:
    prompt_contract = _required_mapping(validation_summary, "prompt_contract", "validation summary")
    primary_prompt_token = _as_str(_required_mapping(prompt_contract, "primary", "prompt contract").get("prompt_version"))
    shadow_prompt_token = _as_str(_required_mapping(prompt_contract, "shadow", "prompt contract").get("prompt_version"))
    _validate_prompt_tokens(primary_prompt_token, shadow_prompt_token)
    validate_concurrent_validation_summary(validation_summary, campaign_diagnostics)

    message_by_id = {str(message["message_id"]): dict(message) for message in message_snapshot}
    trace_rows = _build_trace_rows(
        message_by_id=message_by_id,
        pair_rows=pair_rows,
        terminal_rows=terminal_rows,
        diagnostics=campaign_diagnostics,
        primary_prompt_token=primary_prompt_token,
        shadow_prompt_token=shadow_prompt_token,
    )
    sample_manifest_rows = [_safe_sample_manifest_row(user) for user in sample_users]
    users_document = ConcurrentMessageUsersDocument(rows=_build_user_rows(sample_manifest_rows, trace_rows))
    decision_trace_document = ConcurrentMessageDecisionTraceDocument(
        primary_prompt_token=primary_prompt_token,
        shadow_prompt_token=shadow_prompt_token,
        rows=trace_rows,
    )
    field_lineage_document = ConcurrentMessageFieldLineageDocument(entries=_field_lineage_entries())
    runtime_document = ConcurrentMessageRuntimeDocument(
        configuration=dict(safe_data(config_snapshot)),
        prompt_tokens={"primary": primary_prompt_token, "shadow": shadow_prompt_token},
        counts=dict(_required_mapping(validation_summary, "counts", "validation summary")),
        artifacts=_canonical_runtime_view(),
    )
    diagnostics_document = ConcurrentMessageDiagnosticsDocument(
        validation_summary=dict(safe_data(validation_summary)),
        campaign_diagnostics=dict(safe_data(campaign_diagnostics)),
        field_lineage_path=CONCURRENT_MESSAGE_FIELD_LINEAGE_JSON,
    )
    primary_actions_rows = _build_primary_actions_rows(trace_rows, pair_rows)
    provider_failure_rows = _build_provider_failure_rows(terminal_rows)
    payload = ConcurrentMessageReportPayload(
        title=title,
        run={
            "configuration_profile": config_snapshot.get("configuration_profile", "validation"),
            "sample_size": config_snapshot.get("sample_size"),
            "horizon": config_snapshot.get("horizon"),
            "delivery_capacity": config_snapshot.get("delivery_capacity"),
            "random_seed": config_snapshot.get("random_seed"),
            "sampling_method": config_snapshot.get("sampling_method"),
            "sampling_status": config_snapshot.get("sampling_status"),
            "production_deploy_eligible": config_snapshot.get("production_deploy_eligible"),
            "ranking_formula": config_snapshot.get("ranking_formula"),
            "engaged_neighbor_formula": config_snapshot.get("engaged_neighbor_formula"),
            "prompt_tokens": {"primary": primary_prompt_token, "shadow": shadow_prompt_token},
        },
        messages=[dict(safe_data(message)) for message in message_snapshot],
        prompt_contract=dict(safe_data(prompt_contract)),
        variant_provider_accounting=dict(
            safe_data(_required_mapping(validation_summary, "variant_provider_accounting", "validation summary"))
        ),
        campaign_funnel=dict(safe_data(_required_mapping(campaign_diagnostics, "campaign_funnel", "campaign diagnostics"))),
        message_allocation=dict(
            safe_data(_required_mapping(campaign_diagnostics, "message_allocation", "campaign diagnostics"))
        ),
        primary_audience_response=dict(
            safe_data(_required_mapping(campaign_diagnostics, "primary_audience_response", "campaign diagnostics"))
        ),
        campaign_feedback_effect=dict(
            safe_data(_required_mapping(campaign_diagnostics, "campaign_feedback_effect", "campaign diagnostics"))
        ),
        demographic_decision_sensitivity=dict(
            safe_data(_required_mapping(campaign_diagnostics, "demographic_decision_sensitivity", "campaign diagnostics"))
        ),
        validation_summary=dict(safe_data(validation_summary)),
        downloads=ConcurrentMessageDownloadLinks(),
        notes=[
            "Shadow is a report-only paired computation. It does not trigger a second user exposure, a second ranking trajectory, or any runtime state mutation.",
            "The page only shows allowlisted, recomputable evidence. Raw prompt text, raw provider payloads, raw responses, headers, and secrets remain excluded.",
            "Ranking evidence is platform-internal and not part of either prompt. The detail drawer separates persisted input, reconstructed context, and aggregate evidence.",
            "All five metric groups are descriptive and non-causal. They do not rank a winning message or infer demographic causality.",
        ],
        exposure_rows=trace_rows,
        user_rows=users_document.rows,
        field_lineage=field_lineage_document.entries,
    )
    report_html = render_report(payload, expected_sha256=expected_report_sha256)
    return _BuildResult(
        report_payload=payload,
        users_document=users_document,
        decision_trace_document=decision_trace_document,
        runtime_document=runtime_document,
        diagnostics_document=diagnostics_document,
        field_lineage_document=field_lineage_document,
        primary_actions_rows=primary_actions_rows,
        provider_failure_rows=provider_failure_rows,
        sample_manifest_rows=sample_manifest_rows,
        report_html=report_html,
    )


def _build_trace_rows(
    *,
    message_by_id: Mapping[str, Mapping[str, Any]],
    pair_rows: Sequence[Mapping[str, Any]],
    terminal_rows: Sequence[Mapping[str, Any]],
    diagnostics: Mapping[str, Any],
    primary_prompt_token: str,
    shadow_prompt_token: str,
) -> list[ConcurrentMessageTraceRecord]:
    terminal_by_key: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in terminal_rows:
        key = (_as_str(row.get("pair_id")), _as_str(row.get("decision_variant")))
        if key in terminal_by_key:
            raise ValueError(f"duplicate terminal row for {key}")
        terminal_by_key[key] = row
    message_response = _required_mapping(
        _required_mapping(diagnostics, "primary_audience_response", "campaign diagnostics"),
        "per_message",
        "primary audience response",
    )
    per_message_funnel = _required_mapping(
        _required_mapping(diagnostics, "campaign_funnel", "campaign diagnostics"),
        "per_message",
        "campaign funnel",
    )
    class_matrix = _required_mapping(
        _required_mapping(diagnostics, "message_allocation", "campaign diagnostics"),
        "class_message_matrix",
        "message allocation",
    )
    sensitivity = _required_mapping(diagnostics, "demographic_decision_sensitivity", "campaign diagnostics")
    summary_rates = {
        "pair_terminal_coverage": _required_mapping(sensitivity, "pair_terminal_coverage", "sensitivity"),
        "paired_decision_coverage": _required_mapping(sensitivity, "paired_decision_coverage", "sensitivity"),
        "engage_disagreement_rate": _required_mapping(sensitivity, "engage_disagreement_rate", "sensitivity"),
    }
    traces: list[ConcurrentMessageTraceRecord] = []
    seen_identity: set[tuple[str, str, int]] = set()
    for pair in sorted(pair_rows, key=lambda row: (_as_int(row.get("time_step")), _as_str(row.get("message_id")), _as_str(row.get("user_id")))):
        identity = (_as_str(pair.get("user_id")), _as_str(pair.get("message_id")), _as_int(pair.get("time_step")))
        if identity in seen_identity:
            raise ValueError(f"duplicate exposure identity for {identity}")
        seen_identity.add(identity)
        pair_id = _as_str(pair.get("pair_id"))
        primary_terminal = terminal_by_key.get((pair_id, "primary"))
        shadow_terminal = terminal_by_key.get((pair_id, "shadow"))
        if primary_terminal is None or shadow_terminal is None:
            raise ValueError(
                f"pair {pair_id} does not close to Primary/Shadow terminals; terminal row count or coverage is invalid"
            )
        message = message_by_id.get(_as_str(pair.get("message_id")))
        if message is None:
            raise ValueError(f"pair {pair_id} references an unknown message")
        primary_context = _json_object(primary_terminal.get("context_profile_payload"), "primary context payload")
        primary_peer_context = _json_object(primary_terminal.get("peer_context_payload"), "primary peer context")
        shadow_context = _json_object(shadow_terminal.get("context_profile_payload"), "shadow context payload")
        shadow_peer_context = _json_object(shadow_terminal.get("peer_context_payload"), "shadow peer context")
        primary_inclusion = _json_object(primary_terminal.get("prompt_field_inclusion"), "primary prompt field inclusion")
        shadow_inclusion = _json_object(shadow_terminal.get("prompt_field_inclusion"), "shadow prompt field inclusion")
        primary_status = _as_str(pair.get("primary_status"))
        shadow_status = _as_str(pair.get("shadow_status"))
        primary_probability = _as_optional_float(pair.get("primary_probability"))
        shadow_probability = _as_optional_float(pair.get("shadow_probability"))
        shadow_added_fields = {
            field_name: _shadow_value_label(field_name, _as_str(shadow_context.get(field_name, "")))
            for field_name in _SHADOW_ONLY_FIELDS
        }
        disagreement = (
            primary_status != shadow_status
            or _as_str(pair.get("primary_action")) != _as_str(pair.get("shadow_action"))
            or primary_probability != shadow_probability
            or _as_str(pair.get("primary_reason")) != _as_str(pair.get("shadow_reason"))
        )
        message_id = _as_str(pair.get("message_id"))
        latent_class = _as_str(pair.get("latent_class"))
        message_response_entry = _required_mapping(message_response, message_id, "message response")
        funnel_entry = _required_mapping(per_message_funnel, message_id, "per-message funnel")
        class_counts = _required_mapping(class_matrix, latent_class, "class x message matrix")
        trace = ConcurrentMessageTraceRecord(
            trace_id=pair_id,
            pair_id=pair_id,
            time_step=_as_int(pair.get("time_step")),
            message_id=message_id,
            message_title=_as_str(pair.get("message_title")),
            message_body=_as_str(message.get("body")),
            user_id=_as_str(pair.get("user_id")),
            latent_class=latent_class,
            is_seed=_as_bool(pair.get("is_seed")),
            selection_reason=_as_str(pair.get("selection_reason")),
            ranking_position=_as_int(pair.get("ranking_position")),
            personalized_delivery_score=_as_float(pair.get("personalized_delivery_score")),
            primary_status=primary_status,
            primary_action=_as_str(pair.get("primary_action")),
            primary_probability=primary_probability,
            primary_confidence=_as_optional_float(pair.get("primary_confidence")),
            primary_reason=_as_str(pair.get("primary_reason")),
            primary_decision_source=_as_str(pair.get("primary_decision_source")),
            primary_prompt_version=_as_str(pair.get("primary_prompt_version")),
            primary_decision={
                "status": primary_status,
                "action": _as_str(pair.get("primary_action")),
                "probability": primary_probability,
                "confidence": _as_optional_float(pair.get("primary_confidence")),
                "reason": _as_str(pair.get("primary_reason")),
                "decision_source": _as_str(pair.get("primary_decision_source")),
                "prompt_version": _as_str(pair.get("primary_prompt_version")),
                "provider_metadata": _json_object(primary_terminal.get("provider_metadata"), "primary provider metadata"),
            },
            shadow_status=shadow_status,
            shadow_action=_as_str(pair.get("shadow_action")),
            shadow_probability=shadow_probability,
            shadow_confidence=_as_optional_float(pair.get("shadow_confidence")),
            shadow_reason=_as_str(pair.get("shadow_reason")),
            shadow_decision_source=_as_str(pair.get("shadow_decision_source")),
            shadow_prompt_version=_as_str(pair.get("shadow_prompt_version")),
            shadow_decision={
                "status": shadow_status,
                "action": _as_str(pair.get("shadow_action")),
                "probability": shadow_probability,
                "confidence": _as_optional_float(pair.get("shadow_confidence")),
                "reason": _as_str(pair.get("shadow_reason")),
                "decision_source": _as_str(pair.get("shadow_decision_source")),
                "prompt_version": _as_str(pair.get("shadow_prompt_version")),
                "provider_metadata": _json_object(shadow_terminal.get("provider_metadata"), "shadow provider metadata"),
            },
            provider_status="provider_failed" if "provider_failed" in (primary_status, shadow_status) else "succeeded",
            primary_shadow_disagreement=disagreement,
            primary_context=primary_context,
            primary_peer_context=primary_peer_context,
            shadow_context=shadow_context,
            shadow_peer_context=shadow_peer_context,
            shadow_added_fields=shadow_added_fields,
            prompt_field_inclusion={"primary": _string_mapping(primary_inclusion), "shadow": _string_mapping(shadow_inclusion)},
            field_differences=_field_differences(primary_context, shadow_context),
            ranking_evidence={
                "ranking_position": _as_int(pair.get("ranking_position")),
                "selection_reason": _as_str(pair.get("selection_reason")),
                "base_network_relevance": _as_float(pair.get("base_network_relevance")),
                "campaign_engaged_neighbor_count": _as_int(pair.get("campaign_engaged_neighbor_count")),
                "campaign_engaged_neighbor_signal": _as_float(pair.get("campaign_engaged_neighbor_signal")),
                "historical_tag_affinity": _as_float(pair.get("historical_tag_affinity")),
                "raw_message_user_fit": _as_float(pair.get("raw_message_user_fit")),
                "normalized_message_user_fit": _as_float(pair.get("normalized_message_user_fit")),
                "personalized_delivery_score": _as_float(pair.get("personalized_delivery_score")),
                "not_in_prompt": True,
            },
            aggregate_evidence={
                "message_response": {
                    "message_id": message_id,
                    "exposures": _as_int(funnel_entry.get("exposures")),
                    "provider_failed": _as_int(_required_mapping(message_response_entry, "action_counts", "message response").get("provider_failed")),
                    "positive_actions": _positive_action_count(_required_mapping(message_response_entry, "action_counts", "message response")),
                    "exposure_engagement_rate": _required_mapping(message_response_entry, "exposure_engagement_rate", "message response"),
                    "decision_engagement_rate": _required_mapping(message_response_entry, "decision_engagement_rate", "message response"),
                },
                "message_allocation": {
                    "latent_class_message_exposures": _as_int(class_counts.get(message_id)),
                    "below_delivery_capacity": _as_int(funnel_entry.get("below_delivery_capacity")),
                },
                "sensitivity_summary": summary_rates,
            },
        )
        if trace.primary_prompt_version != primary_prompt_token:
            raise ValueError("decision trace crossed the approved Primary prompt token")
        if trace.shadow_prompt_version != shadow_prompt_token:
            raise ValueError("decision trace crossed the approved Shadow prompt token")
        traces.append(trace)
    return traces


def _build_user_rows(
    sample_manifest_rows: Sequence[Mapping[str, Any]],
    trace_rows: Sequence[ConcurrentMessageTraceRecord],
) -> list[ConcurrentMessageUserRecord]:
    traces_by_user: dict[str, list[ConcurrentMessageTraceRecord]] = defaultdict(list)
    for row in trace_rows:
        traces_by_user[row.user_id].append(row)
    users: list[ConcurrentMessageUserRecord] = []
    seen_user_ids: set[str] = set()
    for row in sample_manifest_rows:
        user_id = _as_str(row.get("user_id"))
        if user_id in seen_user_ids:
            raise ValueError(f"sample manifest contains duplicate user_id {user_id}")
        seen_user_ids.add(user_id)
        traces = traces_by_user.get(user_id, [])
        users.append(
            ConcurrentMessageUserRecord(
                user_id=user_id,
                activity_score=_as_float(row.get("activity_score")),
                activity_video_score=_as_float(row.get("activity_video_score")),
                activity_comment_score=_as_float(row.get("activity_comment_score")),
                activity_reply_score=_as_float(row.get("activity_reply_score")),
                global_influence_score=_as_float(row.get("global_influence_score")),
                local_influence_score=_as_float(row.get("local_influence_score")),
                local_network_score=_as_float(row.get("local_network_score")),
                local_recognition_score=_as_float(row.get("local_recognition_score")),
                sample_source_scope=_as_str(row.get("sample_source_scope")),
                is_seed=_as_bool(row.get("is_seed")),
                sample_role=_as_str(row.get("sample_role")),
                latent_attribute_spec_id=_as_str(row.get("latent_attribute_spec_id")),
                latent_attribute_method=_as_str(row.get("latent_attribute_method")),
                latent_attribute_seed=_as_int(row.get("latent_attribute_seed")),
                latent_class=_as_str(row.get("latent_class")),
                latent_environmental_consciousness_coef=_as_float(row.get("latent_environmental_consciousness_coef")),
                latent_epistemic_value_weight=_as_float(row.get("latent_epistemic_value_weight")),
                latent_environmental_value_weight=_as_float(row.get("latent_environmental_value_weight")),
                latent_functional_value_weight=_as_float(row.get("latent_functional_value_weight")),
                latent_health_value_weight=_as_float(row.get("latent_health_value_weight")),
                latent_emotional_value_weight=_as_float(row.get("latent_emotional_value_weight")),
                latent_social_value_weight=_as_float(row.get("latent_social_value_weight")),
                latent_hotel_class=_as_str(row.get("latent_hotel_class")),
                latent_travel_purpose=_as_str(row.get("latent_travel_purpose")),
                latent_gender=_as_str(row.get("latent_gender")),
                latent_age=_as_str(row.get("latent_age")),
                latent_education=_as_str(row.get("latent_education")),
                latent_monthly_income=_as_str(row.get("latent_monthly_income")),
                exposure_count=len(traces),
                distinct_message_count=len({trace.message_id for trace in traces}),
                exposed_message_ids=sorted({trace.message_id for trace in traces}),
                primary_positive_action_count=sum(
                    trace.primary_status == "succeeded" and trace.primary_action in _POSITIVE_ACTIONS for trace in traces
                ),
                primary_provider_failure_count=sum(trace.primary_status == "provider_failed" for trace in traces),
                shadow_provider_failure_count=sum(trace.shadow_status == "provider_failed" for trace in traces),
            )
        )
    return users


def _build_primary_actions_rows(
    trace_rows: Sequence[ConcurrentMessageTraceRecord],
    pair_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    committed_by_pair = {(_as_str(row.get("pair_id"))): _as_bool(row.get("campaign_feedback_committed")) for row in pair_rows}
    rows: list[dict[str, Any]] = []
    for trace in trace_rows:
        rows.append(
            {
                "pair_id": trace.pair_id,
                "time_step": trace.time_step,
                "message_id": trace.message_id,
                "user_id": trace.user_id,
                "action": trace.primary_action,
                "engage": trace.primary_action in _POSITIVE_ACTIONS,
                "probability": trace.primary_probability,
                "confidence": trace.primary_confidence,
                "reason": trace.primary_reason,
                "decision_source": trace.primary_decision_source,
                "provider_status": trace.primary_status,
                "campaign_feedback_committed": committed_by_pair.get(trace.pair_id, False),
            }
        )
    return rows


def _build_provider_failure_rows(terminal_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_terminal_ids: set[str] = set()
    for row in terminal_rows:
        if _as_str(row.get("provider_status")) != "provider_failed":
            continue
        terminal_row_id = _as_str(row.get("terminal_row_id"))
        if terminal_row_id in seen_terminal_ids:
            raise ValueError(f"duplicate provider failure for terminal_row_id {terminal_row_id}")
        seen_terminal_ids.add(terminal_row_id)
        rows.append(
            {
                "terminal_row_id": terminal_row_id,
                "pair_id": _as_str(row.get("pair_id")),
                "time_step": _as_int(row.get("time_step")),
                "message_id": _as_str(row.get("message_id")),
                "user_id": _as_str(row.get("user_id")),
                "decision_variant": _as_str(row.get("decision_variant")),
                "failure_type": _as_str(row.get("failure_type")),
                "provider_metadata": _json_object(row.get("provider_metadata"), "provider metadata"),
            }
        )
    return rows


def _safe_sample_manifest_row(user: Mapping[str, Any]) -> dict[str, Any]:
    latent = _required_mapping(user.get("latent_attributes", {}), "latent_attributes", "sample user") if user.get("latent_attributes") is not None else {}

    def sample_value(field_name: str) -> object:
        return user[field_name] if field_name in user else latent.get(field_name)

    row = {
        "user_id": _as_str(user.get("user_id")),
        "activity_score": _as_float(user.get("activity_score")),
        "activity_video_score": _as_float(user.get("activity_video_score")),
        "activity_comment_score": _as_float(user.get("activity_comment_score")),
        "activity_reply_score": _as_float(user.get("activity_reply_score")),
        "global_influence_score": _as_float(user.get("global_influence_score")),
        "local_influence_score": _as_float(user.get("local_influence_score")),
        "local_network_score": _as_float(user.get("local_network_score")),
        "local_recognition_score": _as_float(user.get("local_recognition_score")),
        "sample_source_scope": _as_str(user.get("sample_source_scope")),
        "is_seed": _as_bool(user.get("is_seed")),
        "sample_role": _as_str(user.get("sample_role")),
        "latent_attribute_spec_id": _as_str(sample_value("latent_attribute_spec_id")),
        "latent_attribute_method": _as_str(sample_value("latent_attribute_method")),
        "latent_attribute_seed": _as_int(sample_value("latent_attribute_seed")),
        "latent_class": _as_str(sample_value("latent_class")),
        "latent_environmental_consciousness_coef": _as_float(sample_value("latent_environmental_consciousness_coef")),
        "latent_epistemic_value_weight": _as_float(sample_value("latent_epistemic_value_weight")),
        "latent_environmental_value_weight": _as_float(sample_value("latent_environmental_value_weight")),
        "latent_functional_value_weight": _as_float(sample_value("latent_functional_value_weight")),
        "latent_health_value_weight": _as_float(sample_value("latent_health_value_weight")),
        "latent_emotional_value_weight": _as_float(sample_value("latent_emotional_value_weight")),
        "latent_social_value_weight": _as_float(sample_value("latent_social_value_weight")),
        "latent_hotel_class": _as_str(sample_value("latent_hotel_class")),
        "latent_travel_purpose": _as_str(sample_value("latent_travel_purpose")),
        "latent_gender": _as_str(sample_value("latent_gender")),
        "latent_age": _as_str(sample_value("latent_age")),
        "latent_education": _as_str(sample_value("latent_education")),
        "latent_monthly_income": _as_str(sample_value("latent_monthly_income")),
    }
    return dict(safe_data(row))


def _field_lineage_entries() -> list[ConcurrentMessageFieldLineageEntry]:
    return [
        ConcurrentMessageFieldLineageEntry(
            field_name="message_body",
            label="Message body",
            source_artifact=CONCURRENT_MESSAGE_MESSAGE_JSON,
            evidence_class="persisted_input",
            prompt_visibility="primary_allowed",
            usage_stages=["decision_trace", "detail_drawer"],
            description="The original message text shown to both Primary and Shadow decisions.",
        ),
        ConcurrentMessageFieldLineageEntry(
            field_name="primary_context",
            label="Primary allowed profile context",
            source_artifact=CONCURRENT_MESSAGE_TERMINAL_CSV,
            evidence_class="reconstructed_context",
            prompt_visibility="primary_allowed",
            usage_stages=["detail_drawer"],
            description="Allowlisted Primary context reconstructed from persisted safe profile payload and neutral PeerContext.",
        ),
        ConcurrentMessageFieldLineageEntry(
            field_name="shadow_added_fields",
            label="Shadow-only synthetic labels",
            source_artifact=CONCURRENT_MESSAGE_TERMINAL_CSV,
            evidence_class="reconstructed_context",
            prompt_visibility="shadow_only",
            usage_stages=["detail_drawer", "sensitivity"],
            description="The four coarse demographic labels are report-only synthetic additions visible only to the Shadow prompt.",
        ),
        ConcurrentMessageFieldLineageEntry(
            field_name="primary_decision",
            label="Primary structured decision",
            source_artifact=CONCURRENT_MESSAGE_TERMINAL_CSV,
            evidence_class="persisted_input",
            prompt_visibility="report_only",
            usage_stages=["decision_trace", "detail_drawer", "response_metrics"],
            description="Primary status, action, probability, confidence, reason, and safe provider metadata from the actual exposure.",
        ),
        ConcurrentMessageFieldLineageEntry(
            field_name="shadow_decision",
            label="Shadow structured decision",
            source_artifact=CONCURRENT_MESSAGE_TERMINAL_CSV,
            evidence_class="persisted_input",
            prompt_visibility="report_only",
            usage_stages=["decision_trace", "detail_drawer", "sensitivity"],
            description="Shadow status, action, probability, confidence, reason, and safe provider metadata from the paired report-only comparison.",
        ),
        ConcurrentMessageFieldLineageEntry(
            field_name="ranking_evidence",
            label="Ranking evidence",
            source_artifact=CONCURRENT_MESSAGE_PAIR_CSV,
            evidence_class="persisted_input",
            prompt_visibility="platform_internal",
            usage_stages=["detail_drawer", "allocation_metrics", "feedback_metrics"],
            description="Ranking position and score components are platform-internal evidence and never part of either prompt.",
        ),
        ConcurrentMessageFieldLineageEntry(
            field_name="aggregate_evidence",
            label="Aggregate evidence",
            source_artifact=CONCURRENT_MESSAGE_DIAGNOSTICS_JSON,
            evidence_class="aggregate_evidence",
            prompt_visibility="report_only",
            usage_stages=["detail_drawer", "topline_metrics"],
            description="Per-message rates and sensitivity summaries are aggregate evidence derived from the persisted tuple.",
        ),
    ]


def _build_manifest(output_path: Path, validation_summary: Mapping[str, Any]) -> ConcurrentMessageArtifactManifest:
    artifacts = _canonical_manifest_view(output_path)
    sha256 = {name: _sha256_file(output_path / relative_path) for name, relative_path in artifacts.items()}
    prompt_contract = _required_mapping(validation_summary, "prompt_contract", "validation summary")
    return ConcurrentMessageArtifactManifest(
        report_schema=CONCURRENT_MESSAGE_REPORT_PAYLOAD_SCHEMA,
        users_schema=CONCURRENT_MESSAGE_USERS_SCHEMA,
        runtime_schema=CONCURRENT_MESSAGE_RUNTIME_SCHEMA,
        diagnostics_schema=CONCURRENT_MESSAGE_DIAGNOSTICS_SCHEMA,
        decision_trace_schema=CONCURRENT_MESSAGE_DECISION_TRACE_SCHEMA,
        validation_schema=_as_str(validation_summary.get("schema_version")),
        primary_prompt_token=_as_str(_required_mapping(prompt_contract, "primary", "prompt contract").get("prompt_version")),
        shadow_prompt_token=_as_str(_required_mapping(prompt_contract, "shadow", "prompt contract").get("prompt_version")),
        artifacts=artifacts,
        sha256=sha256,
    )


def _validate_documents_against_build(
    *,
    run_path: Path,
    manifest: ConcurrentMessageArtifactManifest,
    payload: ConcurrentMessageReportPayload,
    users_document: ConcurrentMessageUsersDocument,
    decision_trace_document: ConcurrentMessageDecisionTraceDocument,
    runtime_document: ConcurrentMessageRuntimeDocument,
    diagnostics_document: ConcurrentMessageDiagnosticsDocument,
    field_lineage_document: ConcurrentMessageFieldLineageDocument,
    primary_actions_rows: Sequence[Mapping[str, Any]],
    provider_failure_rows: Sequence[Mapping[str, Any]],
    build: _BuildResult,
) -> None:
    if payload != build.report_payload:
        raise ValueError("report payload does not close to the persisted concurrent message tuple")
    if users_document != build.users_document:
        raise ValueError("users document does not match the persisted concurrent message payload")
    if decision_trace_document != build.decision_trace_document:
        raise ValueError("decision trace document does not match the persisted concurrent message payload")
    if runtime_document != build.runtime_document:
        raise ValueError("runtime contract does not match the persisted concurrent message tuple")
    if diagnostics_document != build.diagnostics_document:
        raise ValueError("diagnostics contract does not match the persisted concurrent message tuple")
    if field_lineage_document != build.field_lineage_document:
        raise ValueError("field lineage document does not match the persisted concurrent message payload")
    if [_csv_compare_row(row, _PRIMARY_ACTION_FIELDS) for row in primary_actions_rows] != [
        _csv_compare_row(row, _PRIMARY_ACTION_FIELDS) for row in build.primary_actions_rows
    ]:
        raise ValueError("primary actions artifact does not match the persisted concurrent message tuple")
    if [_csv_compare_row(row, _PROVIDER_FAILURE_FIELDS) for row in provider_failure_rows] != [
        _csv_compare_row(row, _PROVIDER_FAILURE_FIELDS) for row in build.provider_failure_rows
    ]:
        raise ValueError("provider failures artifact does not match the persisted concurrent message tuple")
    if runtime_document.artifacts != _canonical_runtime_view():
        raise ValueError("runtime artifact paths do not match the canonical artifact table")
    if manifest.artifacts != _canonical_manifest_view(run_path):
        raise ValueError("manifest artifact paths do not match the canonical artifact table")
    expected_downloads = ConcurrentMessageDownloadLinks().model_dump(mode="json")
    if payload.downloads.model_dump(mode="json") != expected_downloads:
        raise ValueError("report payload downloads do not match the approved concurrent message artifact layout")
    for download_name, relative_path in expected_downloads.items():
        target = _artifact_path(run_path, relative_path, f"download {download_name}")
        if download_name != "manifest" and relative_path not in manifest.artifacts.values():
            raise ValueError(f"download {download_name} is not closed by the artifact manifest")
        if not target.is_file():
            raise FileNotFoundError(f"download target for {download_name} does not exist: {relative_path}")
    if manifest.artifacts["report_payload"] != payload.downloads.report_payload:
        raise ValueError("artifact manifest report payload path does not match payload downloads")



def _positive_action_count(action_counts: Mapping[str, Any]) -> int:
    return sum(_as_int(action_counts.get(action)) for action in _POSITIVE_ACTIONS)


def _field_differences(primary_context: Mapping[str, Any], shadow_context: Mapping[str, Any]) -> list[dict[str, Any]]:
    differences: list[dict[str, Any]] = []
    for field_name, (label, labels) in _SHADOW_ONLY_FIELDS.items():
        shadow_value = _as_str(shadow_context.get(field_name, ""))
        differences.append(
            {
                "field_name": field_name,
                "label": label,
                "primary_display": "not provided",
                "shadow_display": labels.get(shadow_value, shadow_value),
                "note": "Shadow-only synthetic label added for paired sensitivity analysis.",
            }
        )
    return differences


def _shadow_value_label(field_name: str, value: str) -> str:
    label, labels = _SHADOW_ONLY_FIELDS[field_name]
    return f"{label}: {labels.get(value, value)}"


def _validate_prompt_tokens(primary_prompt_token: object, shadow_prompt_token: object) -> None:
    if primary_prompt_token != CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION:
        raise ValueError("crossed or unsupported Primary prompt token")
    if shadow_prompt_token != CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION:
        raise ValueError("crossed or unsupported Shadow prompt token")


def _validate_input_hashes(
    manifest: ConcurrentMessageArtifactManifest,
    artifacts: Mapping[str, Path],
) -> None:
    for name, path in artifacts.items():
        if name == "report_html":
            continue
        if not path.is_file():
            raise FileNotFoundError(f"Concurrent message rebuild requires {path.name}")
        actual = _sha256_file(path)
        if actual != manifest.sha256[name]:
            raise ValueError(f"artifact hash mismatch for {name}")


def _ensure_no_unexpected_root_files(run_path: Path, manifest: ConcurrentMessageArtifactManifest) -> None:
    expected = set(manifest.artifacts.values()) | {CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON}
    actual: set[str] = set()
    for path in run_path.rglob("*"):
        relative_path = path.relative_to(run_path).as_posix()
        if path.is_symlink():
            raise ValueError(f"run directory contains symlink: {relative_path}")
        if path.is_file():
            actual.add(relative_path)
        elif not path.is_dir():
            raise ValueError(f"run directory contains non-regular artifact: {relative_path}")
    unexpected = sorted(actual - expected)
    if unexpected:
        raise ValueError(f"run directory contains unlisted artifacts: {', '.join(unexpected)}")


def _artifact_path(run_path: Path, relative_path: str, artifact_name: str) -> Path:
    candidate = (run_path / relative_path).resolve()
    if not candidate.is_relative_to(run_path.resolve()):
        raise ValueError(f"artifact path escape rejected for {artifact_name}")
    return candidate


def _csv_compare_row(row: Mapping[str, Any], fieldnames: Sequence[str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for field in fieldnames:
        cell = _csv_cell(row.get(field))
        normalized[field] = "" if cell is None else str(cell)
    return normalized


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, fieldnames: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_cell(row.get(field)) for field in fieldnames})


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json_object(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"expected a JSON object in {path.name}")
    return dict(document)


def _read_json_records(path: Path, description: str) -> list[dict[str, Any]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, list) or not all(isinstance(row, dict) for row in document):
        raise ValueError(f"expected a JSON array of objects for {description}")
    return [dict(row) for row in document]


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _csv_fieldnames(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    if not rows:
        return []
    return list(rows[0].keys())


def _csv_user_row(row: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    payload["exposed_message_ids"] = json.dumps(payload.get("exposed_message_ids", []), ensure_ascii=False, separators=(",", ":"))
    payload["is_seed"] = "true" if payload.get("is_seed") else "false"
    return payload


def _csv_trace_row(row: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    payload["is_seed"] = "true" if payload.get("is_seed") else "false"
    payload["primary_shadow_disagreement"] = "true" if payload.get("primary_shadow_disagreement") else "false"
    return payload


def _csv_cell(value: object) -> object:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return value


def _required_mapping(value: object, description: str, parent: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{parent} must contain a mapping for {description}")
    if description in value:
        nested = value[description]
        if not isinstance(nested, Mapping):
            raise ValueError(f"{parent} must contain a mapping for {description}")
        return {str(key): item for key, item in nested.items()}
    return {str(key): item for key, item in value.items()}


def _required_list(value: object, description: str) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{description} must be a list")
    rows: list[dict[str, Any]] = []
    for row in value:
        if not isinstance(row, Mapping):
            raise ValueError(f"{description} must contain only objects")
        rows.append({str(key): item for key, item in row.items()})
    return rows


def _string_mapping(value: Mapping[str, Any]) -> dict[str, str]:
    return {str(key): _as_str(item) for key, item in value.items()}


def _json_object(value: object, description: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    if not isinstance(value, str) or not value:
        return {}
    document = json.loads(value)
    if not isinstance(document, dict):
        raise ValueError(f"{description} must decode to a JSON object")
    return {str(key): item for key, item in document.items()}


def _as_str(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        token = value.strip().lower()
        if token in {"true", "1", "yes"}:
            return True
        if token in {"false", "0", "no", ""}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    raise ValueError(f"cannot coerce {value!r} to bool")


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError(f"cannot coerce bool {value!r} to int")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        token = value.strip()
        if not token:
            return 0
        return int(token)
    raise ValueError(f"cannot coerce {value!r} to int")


def _as_float(value: object) -> float:
    if isinstance(value, bool):
        raise ValueError(f"cannot coerce bool {value!r} to float")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        token = value.strip()
        if not token:
            return 0.0
        return float(token)
    raise ValueError(f"cannot coerce {value!r} to float")


def _as_optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    return _as_float(value)
