from __future__ import annotations

import csv
import hashlib
import html
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from .concurrent_campaign_diagnostics import validate_concurrent_validation_summary
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

    report_payload: str = CONCURRENT_MESSAGE_REPORT_PAYLOAD_JSON
    users_json: str = CONCURRENT_MESSAGE_USERS_JSON
    users_csv: str = CONCURRENT_MESSAGE_USERS_CSV
    decision_trace_json: str = CONCURRENT_MESSAGE_DECISION_TRACE_JSON
    decision_trace_csv: str = CONCURRENT_MESSAGE_DECISION_TRACE_CSV
    runtime_contract: str = CONCURRENT_MESSAGE_RUNTIME_JSON
    diagnostics_contract: str = CONCURRENT_MESSAGE_DIAGNOSTICS_JSON
    field_lineage: str = CONCURRENT_MESSAGE_FIELD_LINEAGE_JSON
    validation_evidence: str = CONCURRENT_MESSAGE_VALIDATION_JSON
    sample_manifest_json: str = CONCURRENT_MESSAGE_SAMPLE_JSON
    sample_manifest_csv: str = CONCURRENT_MESSAGE_SAMPLE_CSV
    rankings_csv: str = CONCURRENT_MESSAGE_CANDIDATE_CSV
    exposures_csv: str = CONCURRENT_MESSAGE_PAIR_CSV
    terminals_csv: str = CONCURRENT_MESSAGE_TERMINAL_CSV
    primary_actions_csv: str = CONCURRENT_MESSAGE_PRIMARY_ACTIONS_CSV
    provider_failures_csv: str = CONCURRENT_MESSAGE_PROVIDER_FAILURES_CSV
    manifest: str = CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON

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


def rebuild_concurrent_message_report(run_dir: str | Path) -> Path:
    run_path = Path(run_dir)
    if not run_path.is_dir():
        raise FileNotFoundError(f"Concurrent message run directory does not exist: {run_path}")
    manifest_path = run_path / CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Concurrent message rebuild requires {manifest_path.name}")
    manifest = ConcurrentMessageArtifactManifest.model_validate(_read_json_object(manifest_path))
    _ensure_no_unexpected_root_files(run_path, manifest)
    artifacts = {name: _artifact_path(run_path, relative_path, name) for name, relative_path in manifest.artifacts.items()}
    _validate_input_hashes(manifest, artifacts)

    message_snapshot = _read_json_records(artifacts["message_snapshot"], "message snapshot")
    sample_manifest_rows = _read_json_records(artifacts["sample_manifest_json"], "sample manifest")
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
    )
    _validate_documents_against_build(
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
    expected_hash = manifest.sha256["report_html"]
    rendered_hash = _sha256_text(build.report_html)
    if rendered_hash != expected_hash:
        raise ValueError("rebuilt concurrent message HTML does not match the persisted manifest hash")
    report_path = _artifact_path(run_path, manifest.artifacts["report_html"], "report_html")
    _atomic_write_text(report_path, build.report_html)
    return report_path


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
        artifacts={
            "config_snapshot": CONCURRENT_MESSAGE_CONFIG_JSON,
            "message_snapshot": CONCURRENT_MESSAGE_MESSAGE_JSON,
            "sample_manifest_json": CONCURRENT_MESSAGE_SAMPLE_JSON,
            "sample_manifest_csv": CONCURRENT_MESSAGE_SAMPLE_CSV,
            "runtime_candidates_csv": CONCURRENT_MESSAGE_CANDIDATE_CSV,
            "runtime_pairs_csv": CONCURRENT_MESSAGE_PAIR_CSV,
            "runtime_terminal_rows_csv": CONCURRENT_MESSAGE_TERMINAL_CSV,
            "runtime_steps_json": CONCURRENT_MESSAGE_STEP_JSON,
            "validation_evidence": CONCURRENT_MESSAGE_VALIDATION_JSON,
            "campaign_diagnostics_json": CONCURRENT_MESSAGE_CAMPAIGN_DIAGNOSTICS_JSON,
            "primary_actions_csv": CONCURRENT_MESSAGE_PRIMARY_ACTIONS_CSV,
            "provider_failures_csv": CONCURRENT_MESSAGE_PROVIDER_FAILURES_CSV,
        },
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
    report_html = _render_report_html(payload)
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
            raise ValueError(f"pair {pair_id} does not close to Primary/Shadow terminals")
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
    sample_audit_path = output_path / CONCURRENT_MESSAGE_SEED_AUDIT_JSON
    artifacts = {
        "config_snapshot": CONCURRENT_MESSAGE_CONFIG_JSON,
        "message_snapshot": CONCURRENT_MESSAGE_MESSAGE_JSON,
        "sample_manifest_json": CONCURRENT_MESSAGE_SAMPLE_JSON,
        "sample_manifest_csv": CONCURRENT_MESSAGE_SAMPLE_CSV,
        "rankings_csv": CONCURRENT_MESSAGE_CANDIDATE_CSV,
        "exposures_csv": CONCURRENT_MESSAGE_PAIR_CSV,
        "terminals_csv": CONCURRENT_MESSAGE_TERMINAL_CSV,
        "runtime_steps_json": CONCURRENT_MESSAGE_STEP_JSON,
        "validation_evidence": CONCURRENT_MESSAGE_VALIDATION_JSON,
        "campaign_diagnostics_json": CONCURRENT_MESSAGE_CAMPAIGN_DIAGNOSTICS_JSON,
        "runtime_contract": CONCURRENT_MESSAGE_RUNTIME_JSON,
        "primary_actions_csv": CONCURRENT_MESSAGE_PRIMARY_ACTIONS_CSV,
        "provider_failures_csv": CONCURRENT_MESSAGE_PROVIDER_FAILURES_CSV,
        "users_json": CONCURRENT_MESSAGE_USERS_JSON,
        "users_csv": CONCURRENT_MESSAGE_USERS_CSV,
        "decision_trace_json": CONCURRENT_MESSAGE_DECISION_TRACE_JSON,
        "decision_trace_csv": CONCURRENT_MESSAGE_DECISION_TRACE_CSV,
        "field_lineage": CONCURRENT_MESSAGE_FIELD_LINEAGE_JSON,
        "diagnostics_contract": CONCURRENT_MESSAGE_DIAGNOSTICS_JSON,
        "report_payload": CONCURRENT_MESSAGE_REPORT_PAYLOAD_JSON,
        "report_html": CONCURRENT_MESSAGE_REPORT_HTML,
    }
    if sample_audit_path.is_file():
        artifacts["sample_audit"] = CONCURRENT_MESSAGE_SEED_AUDIT_JSON
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
    if payload.downloads.model_dump(mode="json") != ConcurrentMessageDownloadLinks().model_dump(mode="json"):
        raise ValueError("report payload downloads do not match the approved concurrent message artifact layout")
    if manifest.artifacts["report_payload"] != payload.downloads.report_payload:
        raise ValueError("artifact manifest report payload path does not match payload downloads")


def _render_report_html(payload: ConcurrentMessageReportPayload) -> str:
    counts = _required_mapping(payload.validation_summary, "counts", "validation summary")
    funnel = payload.campaign_funnel
    allocation = payload.message_allocation
    response = payload.primary_audience_response
    feedback = payload.campaign_feedback_effect
    sensitivity = payload.demographic_decision_sensitivity
    formal_seed_first_run = payload.run.get("sampling_status") == "persisted_seed_first_formal_run"
    deploy_eligible = _as_bool(payload.run.get("production_deploy_eligible"))
    if formal_seed_first_run and deploy_eligible:
        hero_copy = (
            "This additive Multi-Message v1 report is a persisted Seed-First Formal artifact. "
            "It is rebuilt from the approved tuple, remains descriptive and non-causal, and "
            "does not call a provider during report regeneration."
        )
        status_label = "Persisted Seed-First Formal Run · deploy eligible"
    elif formal_seed_first_run:
        hero_copy = (
            "This additive Multi-Message v1 report is a persisted Seed-First Formal artifact with a blocked deploy gate. "
            "It is rebuilt from the approved tuple, remains descriptive and non-causal, and does not call a provider "
            "during report regeneration."
        )
        status_label = "Persisted Seed-First Formal Run · deploy blocked"
    else:
        hero_copy = (
            "This additive Multi-Message v1 report is validation-only, descriptive, and non-causal. "
            "It is rebuilt from the persisted tuple and does not call a provider during report regeneration."
        )
        status_label = "Validation only · no deploy"
    summary_cards = [
        ("Research sample", f"{_as_int(counts.get('sample_users')):,}"),
        ("Actual exposures", f"{_as_int(counts.get('actual_exposures')):,}"),
        ("Primary success / fail", f"{_as_int(counts.get('primary_successes'))} / {_as_int(counts.get('primary_failures'))}"),
        ("Shadow success / fail", f"{_as_int(counts.get('shadow_successes'))} / {_as_int(counts.get('shadow_failures'))}"),
        ("Distinct exposed users", f"{_as_int(funnel.get('distinct_exposed_users')):,}"),
        (
            "Paired decision coverage",
            str(_required_mapping(sensitivity, "paired_decision_coverage", "sensitivity").get("value")),
        ),
        (
            "Changed message-batches",
            str(_required_mapping(feedback, "overall", "feedback overall").get("changed_message_batch_count")),
        ),
        (
            "Flagged shadow reasons",
            str(_as_int(_required_mapping(sensitivity, "reason_screening", "reason screening").get("flagged_pair_count"))),
        ),
    ]
    summary_html = "".join(
        f'<article class="summary-card"><span>{html.escape(label)}</span><strong>{html.escape(value)}</strong></article>'
        for label, value in summary_cards
    )
    downloads = payload.downloads.model_dump(mode="json")
    download_links = "".join(
        f'<a data-testid="download-{html.escape(key.replace("_", "-"), quote=True)}" href="{html.escape(relative_path)}">{html.escape(key.replace("_", " ").title())}</a>'
        for key, relative_path in downloads.items()
    )
    message_rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(row['message_id']))}</td>"
        f"<td>{html.escape(str(row['title']))}</td>"
        f"<td>{html.escape(str(row['intended_audience_segment']))}</td>"
        f"<td>{html.escape(str(row['body'])[:96])}...</td>"
        "</tr>"
        for row in payload.messages
    )
    funnel_rows = "".join(
        "<tr>"
        f"<td>{html.escape(label)}</td>"
        f"<td>{html.escape(value)}</td>"
        "</tr>"
        for label, value in (
            ("Sample users", f"{_as_int(funnel.get('sample_users')):,}"),
            ("Eligible user-message pairs", f"{_as_int(funnel.get('eligible_user_message_pairs')):,}"),
            ("Actual exposures", f"{_as_int(funnel.get('actual_exposures')):,}"),
            ("Distinct exposed users", f"{_as_int(funnel.get('distinct_exposed_users')):,}"),
            ("Below delivery capacity pairs", f"{_as_int(funnel.get('below_delivery_capacity_pairs')):,}"),
            ("Primary attempted / succeeded / failed", _three_part(funnel.get('primary'))),
            ("Shadow attempted / succeeded / failed", _three_part(funnel.get('shadow'))),
        )
    )
    coverage_rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(coverage))} message(s)</td>"
        f"<td>{html.escape(str(count))}</td>"
        "</tr>"
        for coverage, count in sorted(_required_mapping(funnel, "campaign_exposure_coverage", "campaign funnel").items())
    )
    allocation_batches = _required_list(allocation.get("batch_capacity"), "message allocation.batch_capacity")
    allocation_rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(row['message_id']))}</td>"
        f"<td>{html.escape(str(row['time_step']))}</td>"
        f"<td>{html.escape(str(row['configured_capacity']))}</td>"
        f"<td>{html.escape(str(row['eligible_users']))}</td>"
        f"<td>{html.escape(str(row['selected_pairs']))}</td>"
        f"<td>{html.escape(str(row['below_delivery_capacity']))}</td>"
        "</tr>"
        for row in allocation_batches
    )
    class_matrix = _required_mapping(allocation, "class_message_matrix", "message allocation")
    class_headers = "".join(f"<th>{html.escape(message['message_id'])}</th>" for message in payload.messages)
    class_rows = "".join(
        "<tr>"
        f"<td>{html.escape(latent_class)}</td>"
        + "".join(
            f"<td>{html.escape(str(values.get(latent_message['message_id'], 0)))}</td>"
            for latent_message in payload.messages
        )
        + "</tr>"
        for latent_class, values in class_matrix.items()
    )
    response_rows = "".join(
        "<tr>"
        f"<td>{html.escape(message_id)}</td>"
        f"<td>{html.escape(str(message_payload['message_title']))}</td>"
        f"<td>{html.escape(str(_required_mapping(message_payload, 'action_counts', 'message response')['like']))}</td>"
        f"<td>{html.escape(str(_required_mapping(message_payload, 'action_counts', 'message response')['comment']))}</td>"
        f"<td>{html.escape(str(_required_mapping(message_payload, 'action_counts', 'message response')['share']))}</td>"
        f"<td>{html.escape(str(_required_mapping(message_payload, 'action_counts', 'message response')['ignore']))}</td>"
        f"<td>{html.escape(str(_required_mapping(message_payload, 'action_counts', 'message response')['provider_failed']))}</td>"
        f"<td>{html.escape(_rate_label(message_payload['exposure_engagement_rate']))}</td>"
        f"<td>{html.escape(_rate_label(message_payload['decision_engagement_rate']))}</td>"
        "</tr>"
        for message_id, message_payload in _required_mapping(response, "per_message", "primary audience response").items()
    )
    feedback_rows = "".join(
        "<tr>"
        f"<td>{html.escape(message_id)}</td>"
        f"<td>{html.escape(str(batch['time_step']))}</td>"
        f"<td>{html.escape(str(batch['top_overlap_count']))}</td>"
        f"<td>{html.escape(str(batch['top_selection_changed']).lower())}</td>"
        f"<td>{html.escape(', '.join(batch['feedback_added_user_ids']))}</td>"
        f"<td>{html.escape(', '.join(batch['feedback_removed_user_ids']))}</td>"
        "</tr>"
        for message_id, message_payload in _required_mapping(feedback, "per_message", "feedback per_message").items()
        for batch in _required_list(message_payload.get("batches"), "feedback batches")
    )
    transition_rows = "".join(
        "<tr>"
        f"<td>{html.escape(transition)}</td>"
        f"<td>{html.escape(str(count))}</td>"
        "</tr>"
        for transition, count in _required_mapping(sensitivity, "action_transition_counts", "sensitivity").items()
    )
    sensitivity_rows = "".join(
        "<tr>"
        f"<td>{html.escape(label)}</td>"
        f"<td>{html.escape(value)}</td>"
        "</tr>"
        for label, value in (
            ("Pair terminal coverage", _rate_label(_required_mapping(sensitivity, "pair_terminal_coverage", "sensitivity"))),
            ("Paired decision coverage", _rate_label(_required_mapping(sensitivity, "paired_decision_coverage", "sensitivity"))),
            ("Dual-success pairs", str(_as_int(sensitivity.get("dual_success_pair_count")))),
            ("Engage disagreement rate", _rate_label(_required_mapping(sensitivity, "engage_disagreement_rate", "sensitivity"))),
            (
                "Mean absolute probability delta",
                _delta_label(_required_mapping(sensitivity, "mean_absolute_probability_delta", "sensitivity")),
            ),
        )
    )
    payload_json = json.dumps(payload.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")).replace("</", "<\\/")
    template = '''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(payload.title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #0f1b2d;
      --muted: #5e6e82;
      --line: #d8e1ee;
      --panel: #ffffff;
      --page: #f4f7fb;
      --green: #206b56;
      --amber: #9a5b12;
      --blue: #1f5fa6;
      --red: #9c2f37;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font: 14px/1.5 -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; color: var(--ink); background: var(--page); }}
    a {{ color: var(--blue); }}
    main {{ width: min(1480px, 100%); margin: 0 auto; background: #fff; }}
    .hero, .content-band, .downloads-band {{ padding: 30px clamp(18px, 4vw, 52px); border-bottom: 1px solid var(--line); }}
    .hero {{ background: linear-gradient(180deg, #f7fbff 0%, #ffffff 100%); }}
    .eyebrow {{ display: inline-block; margin-bottom: 8px; font-size: 11px; font-weight: 800; letter-spacing: 0.08em; text-transform: uppercase; color: var(--green); }}
    .hero-head {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; }}
    .hero h1, .content-band h2 {{ margin: 0 0 10px; line-height: 1.15; }}
    .hero h1 {{ font-size: clamp(2rem, 2.8vw, 3rem); }}
    .status-badge {{ display: inline-flex; align-items: center; gap: 8px; min-height: 34px; padding: 6px 10px; border: 1px solid #cfe2d7; border-radius: 6px; background: #edf7f2; color: var(--green); font-weight: 700; }}
    .summary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-top: 22px; }}
    .summary-card {{ min-height: 90px; padding: 14px 16px; border: 1px solid var(--line); border-radius: 6px; background: var(--panel); }}
    .summary-card span {{ display: block; color: var(--muted); font-size: 12px; }}
    .summary-card strong {{ display: block; margin-top: 6px; font-size: 24px; }}
    .hero-copy, .section-copy, .muted {{ color: var(--muted); }}
    .split-grid {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 20px; }}
    .stack {{ display: grid; gap: 18px; }}
    .panel, .split-grid > *, .stack > * {{ min-width: 0; }}
    .panel {{ border: 1px solid var(--line); border-radius: 6px; background: #fff; }}
    .panel h3 {{ margin: 0; padding: 14px 16px 0; font-size: 15px; }}
    .panel .section-copy, .panel .muted {{ padding: 0 16px; }}
    .table-wrap {{ overflow-x: auto; min-width: 0; max-width: 100%; }}
    table {{ width: 100%; border-collapse: collapse; min-width: 640px; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid #e5ebf4; text-align: left; vertical-align: top; }}
    th {{ font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }}
    .filters {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin: 16px 0 18px; }}
    .filters label {{ display: grid; gap: 6px; font-size: 12px; color: var(--muted); }}
    input, select {{ width: 100%; min-height: 38px; padding: 8px 10px; border: 1px solid var(--line); border-radius: 6px; font: inherit; color: var(--ink); background: #fff; }}
    .downloads {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; }}
    .downloads a {{ min-height: 42px; display: flex; align-items: center; padding: 8px 10px; border: 1px solid var(--line); border-radius: 6px; text-decoration: none; font-weight: 700; }}
    .downloads a:hover, .downloads a:focus-visible {{ border-color: var(--green); outline: 2px solid rgba(32, 107, 86, 0.22); outline-offset: 2px; }}
    .trace-count {{ font-weight: 700; color: var(--blue); }}
    [data-testid="decision-trace-table"] tbody tr {{ cursor: pointer; }}
    [data-testid="decision-trace-table"] tbody tr:hover, [data-testid="decision-trace-table"] tbody tr:focus {{ background: #f2f7fd; outline: 2px solid rgba(31, 95, 166, 0.18); outline-offset: -2px; }}
    .note-list {{ display: grid; gap: 10px; margin: 18px 0 0; padding: 0; list-style: none; }}
    .note-list li {{ padding: 12px 14px; border-left: 4px solid var(--amber); background: #fff9f2; color: #6f4a18; }}
    .drawer {{ position: fixed; top: 0; right: 0; bottom: 0; z-index: 30; width: min(520px, 100vw); border-left: 1px solid var(--line); background: #fff; box-shadow: -22px 0 48px rgba(15, 27, 45, 0.12); overflow: auto; }}
    .drawer[hidden] {{ display: none; }}
    .drawer-header {{ position: sticky; top: 0; z-index: 2; display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; min-height: 72px; padding: 14px 16px; border-bottom: 1px solid var(--line); background: rgba(255, 255, 255, 0.98); }}
    .drawer-header span {{ display: block; font-size: 11px; font-weight: 800; letter-spacing: 0.08em; text-transform: uppercase; color: var(--green); }}
    .drawer-header h2 {{ margin: 4px 0 0; font-size: 1.15rem; }}
    .drawer-close {{ width: 38px; min-height: 38px; padding: 0; border: 1px solid var(--line); border-radius: 6px; background: #fff; font-size: 1.35rem; line-height: 1; color: var(--ink); cursor: pointer; }}
    .drawer-body {{ padding: 18px; display: grid; gap: 18px; }}
    .drawer-grid {{ display: grid; gap: 14px; }}
    .drawer-card {{ padding: 14px; border: 1px solid var(--line); border-radius: 6px; background: #fff; }}
    .drawer-card h3 {{ margin: 0 0 10px; font-size: 15px; }}
    .drawer-card dl {{ display: grid; grid-template-columns: minmax(0, 140px) minmax(0, 1fr); gap: 8px 10px; margin: 0; }}
    .drawer-card dt {{ color: var(--muted); font-size: 12px; }}
    .drawer-card dd {{ margin: 0; word-break: break-word; }}
    .field-diff-list, .shadow-field-list {{ display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }}
    .field-diff-list li, .shadow-field-list li {{ padding: 10px 12px; border: 1px solid var(--line); border-radius: 6px; background: #f8fafc; }}
    .drawer-empty {{ color: var(--muted); }}
    .footer-note {{ color: var(--muted); font-size: 12px; }}
    @media (max-width: 900px) {{
      .hero-head, .split-grid {{ grid-template-columns: 1fr; display: grid; }}
      .hero-head {{ gap: 14px; }}
    }}
    @media (max-width: 680px) {{
      .hero, .content-band, .downloads-band {{ padding-top: 24px; padding-bottom: 24px; }}
      .summary-grid, .filters, .downloads {{ grid-template-columns: 1fr; }}
      .drawer {{ width: 100vw; }}
    }}
  </style>
</head>
<body>
  <main data-testid="concurrent-message-report">
    <header class="hero">
      <span class="eyebrow">Concurrent Message Experiment</span>
      <div class="hero-head">
        <div>
          <h1>{html.escape(payload.title)}</h1>
          <p class="hero-copy">{html.escape(hero_copy)}</p>
        </div>
        <span class="status-badge" data-testid="validation-status">{html.escape(status_label)}</span>
      </div>
      <div class="summary-grid">{summary_html}</div>
      <ul class="note-list" data-testid="shadow-boundary-notes">{''.join(f'<li>{html.escape(note)}</li>' for note in payload.notes)}</ul>
    </header>

    <section class="content-band" data-testid="messages-section">
      <span class="eyebrow">Contract</span>
      <h2>Approved message snapshot</h2>
      <p class="section-copy">The report freezes the three authoritative message bodies, the paired prompt tokens, and the safe tuple artifacts. Changing any crossed token, aggregate, or artifact hash fails the rebuild.</p>
      <div class="table-wrap"><table><thead><tr><th>Message</th><th>Title</th><th>Audience segment</th><th>Body preview</th></tr></thead><tbody>{message_rows}</tbody></table></div>
    </section>

    <section class="content-band" data-testid="campaign-funnel-section">
      <div class="split-grid">
        <div class="panel">
          <h3>Campaign Funnel</h3>
          <p class="section-copy">Counts and denominators come from the persisted payload and validation evidence.</p>
          <div class="table-wrap"><table><tbody>{funnel_rows}</tbody></table></div>
        </div>
        <div class="panel">
          <h3>Campaign Exposure Coverage</h3>
          <p class="section-copy">Coverage counts are user-level descriptive evidence and do not imply causal message effects.</p>
          <div class="table-wrap"><table><thead><tr><th>Coverage</th><th>User count</th></tr></thead><tbody>{coverage_rows}</tbody></table></div>
        </div>
      </div>
    </section>

    <section class="content-band" data-testid="message-allocation-section">
      <span class="eyebrow">Allocation</span>
      <h2>Message Allocation</h2>
      <p class="section-copy">Ranking evidence stays platform-internal. The page shows it only as explainable allocation evidence, not as prompt input.</p>
      <div class="stack">
        <div class="panel">
          <h3>Batch capacity</h3>
          <div class="table-wrap"><table><thead><tr><th>Message</th><th>Batch</th><th>Configured capacity</th><th>Eligible users</th><th>Selected pairs</th><th>Below capacity</th></tr></thead><tbody>{allocation_rows}</tbody></table></div>
        </div>
        <div class="panel">
          <h3>Class × Message Exposure Matrix</h3>
          <div class="table-wrap"><table><thead><tr><th>Latent class</th>{class_headers}</tr></thead><tbody>{class_rows}</tbody></table></div>
        </div>
      </div>
    </section>

    <section class="content-band" data-testid="primary-audience-response-section">
      <span class="eyebrow">Response</span>
      <h2>Primary Audience Response</h2>
      <p class="section-copy">Both rates keep their persisted denominators visible. Provider failures are shown directly and are never patched by the page.</p>
      <div class="table-wrap"><table><thead><tr><th>Message</th><th>Title</th><th>Like</th><th>Comment</th><th>Share</th><th>Ignore</th><th>Provider failed</th><th>Positive / exposures</th><th>Positive / successful Primary decisions</th></tr></thead><tbody>{response_rows}</tbody></table></div>
    </section>

    <section class="content-band" data-testid="campaign-feedback-effect-section">
      <span class="eyebrow">Feedback</span>
      <h2>Campaign Feedback Effect</h2>
      <p class="section-copy">No-feedback comparisons reuse the same frozen candidates and full-precision score components while setting only the campaign-feedback term to 0.</p>
      <div class="table-wrap"><table><thead><tr><th>Message</th><th>Batch</th><th>Top overlap</th><th>Changed</th><th>Feedback-added users</th><th>Feedback-removed users</th></tr></thead><tbody>{feedback_rows}</tbody></table></div>
    </section>

    <section class="content-band" data-testid="demographic-decision-sensitivity-section">
      <span class="eyebrow">Sensitivity</span>
      <h2>Demographic Decision Sensitivity</h2>
      <p class="section-copy">Shadow is report-only. Paired comparisons stay descriptive and do not become a second exposure or a second runtime path.</p>
      <div class="split-grid">
        <div class="panel">
          <h3>Summary</h3>
          <div class="table-wrap"><table><tbody>{sensitivity_rows}</tbody></table></div>
        </div>
        <div class="panel">
          <h3>Action transitions</h3>
          <div class="table-wrap"><table><thead><tr><th>Transition</th><th>Count</th></tr></thead><tbody>{transition_rows}</tbody></table></div>
        </div>
      </div>
    </section>

    <section class="content-band" data-testid="decision-trace-section">
      <span class="eyebrow">Decision Trace</span>
      <h2>Exposure trace table</h2>
      <p class="section-copy">Each row is one unique <code>user × message × exposure</code>. Filters only hide or show persisted rows; they never rewrite reasons or add synthetic actions.</p>
      <div class="filters">
        <label><span>Search</span><input data-testid="trace-search" id="trace-search" type="search" placeholder="user_id / message / reason"></label>
        <label><span>Message</span><select data-testid="message-filter" id="message-filter"><option value="">All</option></select></label>
        <label><span>Class</span><select data-testid="class-filter" id="class-filter"><option value="">All</option></select></label>
        <label><span>Batch</span><select data-testid="batch-filter" id="batch-filter"><option value="">All</option></select></label>
        <label><span>Primary action</span><select data-testid="primary-action-filter" id="primary-action-filter"><option value="">All</option></select></label>
        <label><span>Provider status</span><select data-testid="provider-status-filter" id="provider-status-filter"><option value="">All</option><option value="succeeded">Succeeded</option><option value="provider_failed">Provider failed</option></select></label>
        <label><span>Primary / Shadow disagreement</span><select data-testid="disagreement-filter" id="disagreement-filter"><option value="">All</option><option value="true">Disagree</option><option value="false">Agree</option></select></label>
      </div>
      <p class="trace-count" data-testid="visible-trace-count" id="visible-trace-count"></p>
      <div class="table-wrap"><table data-testid="decision-trace-table"><thead><tr><th>Batch</th><th>Message</th><th>User</th><th>Class</th><th>Rank</th><th>Selection</th><th>Fit</th><th>Primary</th><th>Shadow</th><th>Provider</th><th>Disagree</th></tr></thead><tbody id="decision-trace-body"></tbody></table></div>
    </section>

    <section class="downloads-band" data-testid="downloads-section">
      <span class="eyebrow">Artifacts</span>
      <h2>Safe downloads</h2>
      <p class="section-copy">Downloads expose only approved processed/runtime fields. Raw prompt text, raw provider responses, headers, secrets, nickname, bio, and signature remain excluded.</p>
      <div class="downloads">{download_links}</div>
      <p class="footer-note">The manifest records SHA-256 for release-relevant artifacts and the rebuild validates path safety, hashes, schema tokens, and aggregate closure before publishing HTML.</p>
    </section>
  </main>

  <aside id="trace-drawer" class="drawer" data-testid="trace-drawer" role="dialog" aria-labelledby="trace-drawer-title" hidden>
    <header class="drawer-header">
      <div><span>Trace detail</span><h2 id="trace-drawer-title">Evidence detail</h2></div>
      <button id="trace-drawer-close" class="drawer-close" type="button" aria-label="Close trace detail" title="Close trace detail">×</button>
    </header>
    <div id="trace-drawer-body" class="drawer-body"></div>
  </aside>

  <script id="concurrent-message-payload" type="application/json">{payload_json}</script>
  <script>
const payload = JSON.parse(document.getElementById('concurrent-message-payload').textContent || '{}');
const traces = payload.exposure_rows || [];
const lineages = payload.field_lineage || [];
const drawer = document.getElementById('trace-drawer');
const drawerBody = document.getElementById('trace-drawer-body');
const drawerTitle = document.getElementById('trace-drawer-title');
const closeButton = document.getElementById('trace-drawer-close');
const traceBody = document.getElementById('decision-trace-body');
const visibleTraceCount = document.getElementById('visible-trace-count');
const searchInput = document.getElementById('trace-search');
const filterIds = ['message-filter','class-filter','batch-filter','primary-action-filter','provider-status-filter','disagreement-filter'];

function optionize(selectId, values) {{
  const select = document.getElementById(selectId);
  const distinct = [...new Set(values)].filter((value) => value !== undefined && value !== null && String(value) !== '').sort();
  distinct.forEach((value) => {{
    const option = document.createElement('option');
    option.value = String(value);
    option.textContent = String(value);
    select.appendChild(option);
  }});
}}

optionize('message-filter', traces.map((row) => row.message_id));
optionize('class-filter', traces.map((row) => row.latent_class));
optionize('batch-filter', traces.map((row) => row.time_step));
optionize('primary-action-filter', traces.map((row) => row.primary_action));

function element(tag, className, text) {{
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}}

function asSearchText(row) {{
  return [
    row.user_id,
    row.message_id,
    row.message_title,
    row.primary_action,
    row.shadow_action,
    row.primary_reason,
    row.shadow_reason,
    row.latent_class,
  ].join(' ').toLowerCase();
}}

function passesFilters(row) {{
  const search = (searchInput.value || '').trim().toLowerCase();
  if (search && !asSearchText(row).includes(search)) return false;
  const messageValue = document.getElementById('message-filter').value;
  if (messageValue && row.message_id !== messageValue) return false;
  const classValue = document.getElementById('class-filter').value;
  if (classValue && row.latent_class !== classValue) return false;
  const batchValue = document.getElementById('batch-filter').value;
  if (batchValue && String(row.time_step) !== batchValue) return false;
  const primaryActionValue = document.getElementById('primary-action-filter').value;
  if (primaryActionValue && row.primary_action !== primaryActionValue) return false;
  const providerStatusValue = document.getElementById('provider-status-filter').value;
  if (providerStatusValue && row.provider_status !== providerStatusValue) return false;
  const disagreementValue = document.getElementById('disagreement-filter').value;
  if (disagreementValue && String(row.primary_shadow_disagreement) !== disagreementValue) return false;
  return true;
}}

function jsonBlock(value) {{
  const pre = element('pre', 'drawer-empty');
  pre.textContent = JSON.stringify(value, null, 2);
  return pre;
}}

function definitionList(items) {{
  const dl = element('dl');
  items.forEach(([label, value]) => {{
    dl.append(element('dt','',label), element('dd','', value === undefined || value === null ? '' : value));
  }});
  return dl;
}}

function renderLineage() {{
  const groups = {{ persisted_input: [], reconstructed_context: [], aggregate_evidence: [] }};
  lineages.forEach((entry) => groups[entry.evidence_class]?.push(entry));
  const wrapper = element('div', 'drawer-grid');
  [['persisted_input','Persisted input'],['reconstructed_context','Reconstructed context'],['aggregate_evidence','Aggregate evidence']].forEach(([key, label]) => {{
    const card = element('section', 'drawer-card');
    card.appendChild(element('h3', '', label));
    const list = element('ul', 'field-diff-list');
    (groups[key] || []).forEach((entry) => {{
      const item = element('li');
      item.appendChild(element('strong','',`${{entry.label}}`));
      item.appendChild(element('div','muted',`${{entry.description}} · source: ${{entry.source_artifact}} · visibility: ${{entry.prompt_visibility}}`));
      list.appendChild(item);
    }});
    card.appendChild(list);
    wrapper.appendChild(card);
  }});
  return wrapper;
}}

function openDrawer(row) {{
  drawerTitle.textContent = `${{row.user_id}} · ${{row.message_id}} · batch ${{row.time_step}}`;
  drawerBody.replaceChildren();

  const messageCard = element('section', 'drawer-card');
  messageCard.appendChild(element('h3', '', 'Message and ranking evidence'));
  messageCard.appendChild(element('p', 'muted', 'Ranking evidence is platform-internal and did not enter either prompt.'));
  messageCard.appendChild(element('p', '', row.message_body));
  messageCard.appendChild(definitionList([
    ['Ranking position', row.ranking_position],
    ['Selection reason', row.selection_reason],
    ['Personalized delivery score', row.personalized_delivery_score],
    ['Base network relevance', row.ranking_evidence.base_network_relevance],
    ['Campaign engaged neighbor count', row.ranking_evidence.campaign_engaged_neighbor_count],
    ['Campaign engaged neighbor signal', row.ranking_evidence.campaign_engaged_neighbor_signal],
    ['Raw message-user fit', row.ranking_evidence.raw_message_user_fit],
    ['Normalized message-user fit', row.ranking_evidence.normalized_message_user_fit],
  ]));

  const primaryCard = element('section', 'drawer-card');
  primaryCard.appendChild(element('h3', '', 'Primary decision'));
  primaryCard.appendChild(definitionList([
    ['Status', row.primary_status],
    ['Action', row.primary_action],
    ['Probability', row.primary_probability],
    ['Confidence', row.primary_confidence],
    ['Reason', row.primary_reason],
    ['Decision source', row.primary_decision_source],
    ['Prompt token', row.primary_prompt_version],
  ]));
  primaryCard.appendChild(jsonBlock({{ profile_context: row.primary_context, peer_context: row.primary_peer_context }}));

  const shadowCard = element('section', 'drawer-card');
  shadowCard.appendChild(element('h3', '', 'Shadow decision'));
  shadowCard.appendChild(element('p', 'muted', 'Shadow is report-only and adds four synthetic demographic labels without mutating runtime state.'));
  shadowCard.appendChild(definitionList([
    ['Status', row.shadow_status],
    ['Action', row.shadow_action],
    ['Probability', row.shadow_probability],
    ['Confidence', row.shadow_confidence],
    ['Reason', row.shadow_reason],
    ['Decision source', row.shadow_decision_source],
    ['Prompt token', row.shadow_prompt_version],
  ]));
  const shadowFields = element('ul', 'shadow-field-list');
  Object.entries(row.shadow_added_fields || {{}}).forEach(([fieldName, value]) => {{
    const item = element('li');
    item.append(element('strong','',fieldName), element('div','muted',value));
    shadowFields.appendChild(item);
  }});
  shadowCard.appendChild(shadowFields);
  shadowCard.appendChild(jsonBlock({{ profile_context: row.shadow_context, peer_context: row.shadow_peer_context }}));

  const diffCard = element('section', 'drawer-card');
  diffCard.appendChild(element('h3', '', 'Field differences'));
  const diffList = element('ul', 'field-diff-list');
  (row.field_differences || []).forEach((difference) => {{
    const item = element('li');
    item.append(
      element('strong','',difference.label),
      element('div','muted',`Primary: ${{difference.primary_display}}`),
      element('div','muted',`Shadow: ${{difference.shadow_display}}`),
      element('div','muted',difference.note),
    );
    diffList.appendChild(item);
  }});
  diffCard.appendChild(diffList);

  const aggregateCard = element('section', 'drawer-card');
  aggregateCard.appendChild(element('h3', '', 'Aggregate evidence'));
  aggregateCard.appendChild(jsonBlock(row.aggregate_evidence));

  drawerBody.append(messageCard, primaryCard, shadowCard, diffCard, aggregateCard, renderLineage());
  drawer.hidden = false;
  closeButton.focus({{ preventScroll: true }});
}}

function closeDrawer() {{
  drawer.hidden = true;
}}

function renderTable() {{
  const rows = traces.filter(passesFilters);
  visibleTraceCount.textContent = `${{rows.length.toLocaleString()}} visible trace row(s)`;
  traceBody.replaceChildren();
  rows.forEach((row) => {{
    const tr = document.createElement('tr');
    tr.tabIndex = 0;
    const cells = [
      row.time_step,
      row.message_id,
      row.user_id,
      row.latent_class,
      row.ranking_position,
      row.selection_reason,
      row.personalized_delivery_score,
      `${{row.primary_status}} / ${{row.primary_action}}`,
      `${{row.shadow_status}} / ${{row.shadow_action}}`,
      row.provider_status,
      row.primary_shadow_disagreement ? 'true' : 'false',
    ];
    cells.forEach((value) => tr.appendChild(element('td', '', value)));
    tr.addEventListener('click', () => openDrawer(row));
    tr.addEventListener('keydown', (event) => {{ if (event.key === 'Enter' || event.key === ' ') {{ event.preventDefault(); openDrawer(row); }} }});
    traceBody.appendChild(tr);
  }});
}}

searchInput.addEventListener('input', renderTable);
filterIds.forEach((id) => document.getElementById(id).addEventListener('change', renderTable));
closeButton.addEventListener('click', closeDrawer);
document.addEventListener('keydown', (event) => {{ if (event.key === 'Escape' && !drawer.hidden) closeDrawer(); }});
renderTable();
  </script>
</body>
</html>
'''


    return (
        template.replace("{{", "{")
        .replace("}}", "}")
        .replace("{html.escape(payload.title)}", html.escape(payload.title))
        .replace("{html.escape(hero_copy)}", html.escape(hero_copy))
        .replace("{html.escape(status_label)}", html.escape(status_label))
        .replace("{summary_html}", summary_html)
        .replace("{''.join(f'<li>{html.escape(note)}</li>' for note in payload.notes)}", "".join(f"<li>{html.escape(note)}</li>" for note in payload.notes))
        .replace("{message_rows}", message_rows)
        .replace("{funnel_rows}", funnel_rows)
        .replace("{coverage_rows}", coverage_rows)
        .replace("{allocation_rows}", allocation_rows)
        .replace("{class_headers}", class_headers)
        .replace("{class_rows}", class_rows)
        .replace("{response_rows}", response_rows)
        .replace("{feedback_rows}", feedback_rows)
        .replace("{sensitivity_rows}", sensitivity_rows)
        .replace("{transition_rows}", transition_rows)
        .replace("{download_links}", download_links)
        .replace("{payload_json}", payload_json)
    )

def _three_part(payload: object) -> str:
    mapping = _required_mapping(payload, "attempt/succeed/fail payload", "summary")
    return f"{_as_int(mapping.get('attempted'))} / {_as_int(mapping.get('succeeded'))} / {_as_int(mapping.get('provider_failed'))}"


def _rate_label(rate_payload: Mapping[str, Any]) -> str:
    numerator = rate_payload.get("numerator")
    denominator = rate_payload.get("denominator")
    value = rate_payload.get("value")
    return f"{numerator} / {denominator} = {value}"


def _delta_label(delta_payload: Mapping[str, Any]) -> str:
    absolute_delta_sum = delta_payload.get("absolute_delta_sum")
    denominator = delta_payload.get("denominator")
    value = delta_payload.get("value")
    return f"{absolute_delta_sum} / {denominator} = {value}"


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
    actual = {path.name for path in run_path.iterdir() if path.is_file()}
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


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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
