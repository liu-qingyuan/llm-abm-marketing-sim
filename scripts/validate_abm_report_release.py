#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Literal, TypedDict
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from llm_abm_sim.concurrent_campaign_diagnostics import (
    ConcurrentCampaignDiagnostics,
    validate_concurrent_validation_summary,
)
from llm_abm_sim.concurrent_message_report import (
    ConcurrentMessageArtifactClosure,
    close_concurrent_message_artifacts,
)
from llm_abm_sim.concurrent_robustness_release import (
    ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V13,
    ConcurrentRobustnessReleaseError,
    validate_concurrent_robustness_production_release,
)
from llm_abm_sim.final_research_reason_context import ReasonContextDiagnostics
from llm_abm_sim.final_research_report import (
    FinalResearchRankingReportPayloadV5,
    FinalResearchRankingReportPayloadV6,
    RankingV5FormalEvidence,
    RankingV6FormalEvidence,
    _validate_persisted_ranking_report,
)
from llm_abm_sim.provider_accounting import ProviderAccounting


class ReleaseValidationError(ValueError):
    pass


class _TerminalCounts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    sample_users: int = Field(ge=0)
    exposed_users: int = Field(ge=0)
    decided_users: int = Field(ge=0)
    provider_failed: int = Field(ge=0)
    below_delivery_capacity: int = Field(ge=0)


class _DegeneracyFlags(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    all_decisions_ignore: bool
    single_action_only: bool
    no_engagement_feedback: bool


class _TargetAggregateRecordKey(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    video_id: str = Field(min_length=1)


class _TargetAggregateEngagementReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    source_artifact: Literal["videos.csv"]
    record_key: _TargetAggregateRecordKey
    like_count: int = Field(ge=0)
    comment_count: int = Field(ge=0)
    share_count: int = Field(ge=0)
    collect_count: int = Field(ge=0)
    real_exposure_denominator_available: Literal[False]
    user_level_attribution_available: Literal[False]
    action_mutual_exclusivity_known: Literal[False]
    diagnostic_only: Literal[True]


class _ReleaseContractV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["abm-report-release-contract-v2"]
    release_purpose: Literal["formal_research"]
    source_directory: str = Field(min_length=1)
    payload_schema_version: Literal["final-research-ranking-report-payload-v5"]
    users_schema_version: Literal["final-research-ranking-users-v5"]
    manifest_version: Literal["final-research-ranking-runtime-v3"]
    diagnostics_schema_version: Literal["ranking-diagnostics-v2"]
    diagnostics_summary_schema_version: Literal["ranking-diagnostics-summary-v2"]
    prompt_version: Literal["jinjiang-green-marketing-prompt-v3"]
    evidence_schema_version: Literal["ranking-v5-formal-evidence-v1"]
    decision_execution_evidence_schema_version: Literal["final-research-decision-execution-evidence-v1"]
    sampling_method: Literal["seed_first_research_sample_v1"]
    sampling_status: Literal["persisted_seed_first_formal_run"]
    decision_execution_mode: Literal["live_provider"]
    live_api_triggered: Literal[True]
    formal_research_evidence: Literal[True]
    production_deploy_eligible: Literal[True]
    sample_role_counts: dict[str, int]
    decision_source_counts: dict[str, int]
    action_counts: dict[str, int]
    terminal_counts: _TerminalCounts
    degeneracy_flags: _DegeneracyFlags
    target_aggregate_engagement_reference: _TargetAggregateEngagementReference
    artifact_sha256: dict[str, str]

    @model_validator(mode="after")
    def _validate_count_contract(self) -> _ReleaseContractV2:
        allowed_roles = {"seed", "network_cohort", "ordinary"}
        if not self.sample_role_counts or set(self.sample_role_counts) - allowed_roles:
            raise ValueError("sample_role_counts must contain only seed/network_cohort/ordinary roles")
        if set(self.action_counts) != {"like", "comment", "share", "ignore"}:
            raise ValueError("action_counts must contain like/comment/share/ignore exactly once")
        all_counts = [
            *self.sample_role_counts.values(),
            *self.decision_source_counts.values(),
            *self.action_counts.values(),
        ]
        if any(value < 0 for value in all_counts):
            raise ValueError("release evidence counts must be non-negative")
        counts = self.terminal_counts
        if counts.sample_users != counts.exposed_users + counts.below_delivery_capacity:
            raise ValueError("sample_users must equal exposed_users + below_delivery_capacity")
        if counts.exposed_users != counts.decided_users + counts.provider_failed:
            raise ValueError("exposed_users must equal decided_users + provider_failed")
        if counts.decided_users != sum(self.action_counts.values()):
            raise ValueError("decided_users must equal sum(action_counts)")
        if counts.decided_users != sum(self.decision_source_counts.values()):
            raise ValueError("decided_users must equal sum(decision_source_counts)")
        return self


class _ReleaseContractV3(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["abm-report-release-contract-v3"]
    release_purpose: Literal["formal_research"]
    source_directory: str = Field(min_length=1)
    payload_schema_version: Literal["final-research-ranking-report-payload-v6"]
    users_schema_version: Literal["final-research-ranking-users-v5"]
    manifest_version: Literal["final-research-ranking-runtime-v4"]
    diagnostics_schema_version: Literal["ranking-diagnostics-v2"]
    diagnostics_summary_schema_version: Literal["ranking-diagnostics-summary-v2"]
    prompt_version: Literal["jinjiang-green-marketing-prompt-v3"]
    evidence_schema_version: Literal["ranking-v6-formal-evidence-v1"]
    decision_execution_evidence_schema_version: Literal["final-research-decision-execution-evidence-v2"]
    sampling_method: Literal["seed_first_research_sample_v1"]
    sampling_status: Literal["persisted_seed_first_formal_run"]
    decision_execution_mode: Literal["live_provider"]
    adapter_chain: list[Literal["openai_compatible"]]
    requested_model: Literal["gpt-5.4-mini"]
    observed_model: Literal["gpt-5.4-mini-2026-03-17"]
    live_api_triggered: Literal[True]
    formal_research_evidence: Literal[True]
    production_deploy_eligible: Literal[True]
    sample_role_counts: dict[str, int]
    decision_source_counts: dict[str, int]
    action_counts: dict[str, int]
    terminal_counts: _TerminalCounts
    degeneracy_flags: _DegeneracyFlags
    provider_accounting: ProviderAccounting
    reason_context_diagnostics: ReasonContextDiagnostics
    target_aggregate_engagement_reference: _TargetAggregateEngagementReference
    artifact_sha256: dict[str, str]

    @model_validator(mode="after")
    def _validate_formal_contract(self) -> _ReleaseContractV3:
        if self.adapter_chain != ["openai_compatible"]:
            raise ValueError("adapter_chain must be exactly ['openai_compatible']")
        allowed_roles = {"seed", "network_cohort", "ordinary"}
        if not self.sample_role_counts or set(self.sample_role_counts) - allowed_roles:
            raise ValueError("sample_role_counts must contain only seed/network_cohort/ordinary roles")
        if set(self.decision_source_counts) - {"provider"}:
            raise ValueError("decision_source_counts must contain only provider Decisions")
        if set(self.action_counts) != {"like", "comment", "share", "ignore"}:
            raise ValueError("action_counts must contain like/comment/share/ignore exactly once")
        all_counts = [
            *self.sample_role_counts.values(),
            *self.decision_source_counts.values(),
            *self.action_counts.values(),
        ]
        if any(value < 0 for value in all_counts):
            raise ValueError("release evidence counts must be non-negative")
        counts = self.terminal_counts
        if counts.sample_users != counts.exposed_users + counts.below_delivery_capacity:
            raise ValueError("sample_users must equal exposed_users + below_delivery_capacity")
        if counts.exposed_users != counts.decided_users + counts.provider_failed:
            raise ValueError("exposed_users must equal decided_users + provider_failed")
        if counts.decided_users != sum(self.action_counts.values()):
            raise ValueError("decided_users must equal sum(action_counts)")
        if counts.decided_users != sum(self.decision_source_counts.values()):
            raise ValueError("decided_users must equal sum(decision_source_counts)")

        accounting = self.provider_accounting
        if accounting.external_request_invocations <= 0:
            raise ValueError("v3 Formal accounting requires at least one external request invocation")
        if not (
            accounting.external_request_invocations
            >= accounting.provider_response_count
            >= accounting.successful_decision_count
            == counts.decided_users
        ):
            raise ValueError("v3 accounting requires invocations >= responses >= successful Decisions == decided_users")
        if accounting.observed_model_counts != {self.observed_model: accounting.provider_response_count}:
            raise ValueError(
                "observed_model_counts must report only the exact contract observed_model for every response"
            )
        if accounting.observed_model_missing_response_count or accounting.observed_model_malformed_response_count:
            raise ValueError("v3 Formal accounting cannot contain missing or malformed observed models")
        if accounting.usage_complete_response_count != accounting.provider_response_count:
            raise ValueError("complete usage must cover every returned Provider response")
        if accounting.usage_missing_response_count or accounting.usage_malformed_response_count:
            raise ValueError("v3 Formal accounting cannot contain missing or malformed usage")

        diagnostics = self.reason_context_diagnostics
        if diagnostics.exact_reason_facts.decision_row_count != counts.decided_users:
            raise ValueError("exact reason denominator must equal decided_users")
        peer_context = diagnostics.decision_visible_peer_context
        if (
            peer_context.context_count != counts.exposed_users
            or peer_context.neutral_context_count != peer_context.context_count
            or peer_context.non_neutral_context_count != 0
            or any(peer_context.counter_totals.values())
        ):
            raise ValueError("Decision-visible PeerContext must be neutral for every exposed user")
        if diagnostics.selected_ranking_context.selected_candidate_count != counts.exposed_users:
            raise ValueError("selected Ranking context denominator must equal exposed_users")
        return self


class _ConcurrentVariantProviderAccounting(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    invocations: int = Field(ge=0)
    responses: int = Field(ge=0)
    successful_decisions: int = Field(ge=0)
    observed_model_counts: dict[str, int]
    observed_model_missing_response_count: int = Field(ge=0)
    observed_model_malformed_response_count: int = Field(ge=0)
    usage_complete_attempts: int = Field(ge=0)
    usage_incomplete_attempts: int = Field(ge=0)
    usage_complete_response_count: int = Field(ge=0)
    usage_missing_response_count: int = Field(ge=0)
    usage_malformed_response_count: int = Field(ge=0)
    input_usage: int | None = Field(default=None, ge=0)
    output_usage: int | None = Field(default=None, ge=0)
    total_usage: int | None = Field(default=None, ge=0)
    cached_input_usage: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _validate_accounting(self) -> _ConcurrentVariantProviderAccounting:
        if self.invocations < self.responses or self.responses < self.successful_decisions:
            raise ValueError("variant accounting requires invocations >= responses >= successful_decisions")
        if any(type(count) is not int or count < 0 for count in self.observed_model_counts.values()):
            raise ValueError("observed_model_counts must contain non-negative strict integers")
        if any(not isinstance(model, str) or not model.strip() for model in self.observed_model_counts):
            raise ValueError("observed_model_counts keys must be non-empty strings")
        observed_total = (
            sum(self.observed_model_counts.values())
            + self.observed_model_missing_response_count
            + self.observed_model_malformed_response_count
        )
        if observed_total != self.responses:
            raise ValueError("observed model accounting must cover every Provider response")
        usage_total = (
            self.usage_complete_response_count + self.usage_missing_response_count + self.usage_malformed_response_count
        )
        if usage_total != self.responses:
            raise ValueError("usage accounting must cover every Provider response")
        if self.usage_complete_attempts + self.usage_incomplete_attempts < self.successful_decisions:
            raise ValueError("usage attempt accounting cannot undercount successful Decisions")
        if self.usage_complete_response_count == 0:
            if any(
                value is not None
                for value in (self.input_usage, self.output_usage, self.total_usage, self.cached_input_usage)
            ):
                raise ValueError("token aggregates must be null when no response has complete usage")
            return self
        if self.input_usage is None or self.output_usage is None or self.total_usage is None:
            raise ValueError("complete usage requires input_usage, output_usage, and total_usage")
        if self.total_usage != self.input_usage + self.output_usage:
            raise ValueError("total_usage must equal input_usage + output_usage")
        if self.cached_input_usage is not None and self.cached_input_usage > self.input_usage:
            raise ValueError("cached_input_usage cannot exceed input_usage")
        return self


class _ConcurrentFormalCounts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    sample_users: Literal[1000]
    messages: Literal[3]
    eligible_user_message_pairs: Literal[3000]
    actual_exposures: Literal[1800]
    distinct_exposed_users: int = Field(ge=0, le=1000)
    primary_attempted: Literal[1800]
    primary_successes: Literal[1800]
    primary_failures: Literal[0]
    shadow_attempted: Literal[1800]
    shadow_successes: Literal[1800]
    shadow_failures: Literal[0]
    terminal_rows: Literal[3600]
    pair_terminal_coverage: float
    paired_decision_coverage: float

    @model_validator(mode="after")
    def _validate_counts(self) -> _ConcurrentFormalCounts:
        if self.actual_exposures != self.primary_attempted or self.actual_exposures != self.shadow_attempted:
            raise ValueError("actual_exposures must equal both primary_attempted and shadow_attempted")
        if self.primary_successes != self.primary_attempted or self.shadow_successes != self.shadow_attempted:
            raise ValueError("Formal counts require every attempted Decision to succeed")
        if self.terminal_rows != self.actual_exposures * 2:
            raise ValueError("terminal_rows must equal two terminal rows per actual exposure")
        if self.pair_terminal_coverage != 1.0 or self.paired_decision_coverage != 1.0:
            raise ValueError("Formal counts require 100% pair terminal and paired Decision coverage")
        return self


class _ConcurrentPerMessageContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    message_title: str = Field(min_length=1)
    intended_audience_segment: Literal["class_1", "class_2", "class_3"]
    exposures: Literal[600]
    primary_successes: Literal[600]
    primary_failures: Literal[0]
    shadow_successes: Literal[600]
    shadow_failures: Literal[0]
    below_delivery_capacity: Literal[400]

    @model_validator(mode="after")
    def _validate_message_counts(self) -> _ConcurrentPerMessageContract:
        if self.exposures != self.primary_successes + self.primary_failures:
            raise ValueError("Primary per-message counts must close to exposures")
        if self.exposures != self.shadow_successes + self.shadow_failures:
            raise ValueError("Shadow per-message counts must close to exposures")
        return self


class _ReleaseContractV4(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["abm-report-release-contract-v4"]
    release_purpose: Literal["formal_research"]
    source_directory: str = Field(min_length=1)
    artifact_manifest_schema_version: Literal["concurrent-message-artifact-manifest-v1"]
    payload_schema_version: Literal["concurrent-message-report-payload-v1"]
    users_schema_version: Literal["concurrent-message-users-v1"]
    runtime_schema_version: Literal["concurrent-message-runtime-v1"]
    diagnostics_schema_version: Literal["concurrent-message-diagnostics-v1"]
    decision_trace_schema_version: Literal["concurrent-message-decision-trace-v1"]
    field_lineage_schema_version: Literal["concurrent-message-field-lineage-v1"]
    validation_schema_version: Literal["concurrent-message-validation-v1"]
    campaign_diagnostics_schema_version: Literal["concurrent-campaign-diagnostics-v1"]
    sampling_method: Literal["seed_first_research_sample_v1"]
    sampling_status: Literal["persisted_seed_first_formal_run"]
    configuration_profile: Literal["production"]
    primary_prompt_token: Literal["jinjiang-concurrent-message-primary-prompt-v1"]
    shadow_prompt_token: Literal["jinjiang-concurrent-message-demographic-shadow-prompt-v1"]
    production_deploy_eligible: Literal[True]
    provider: Literal["openai_compatible"]
    requested_model: Literal["gpt-5.4-mini"]
    observed_model: Literal["gpt-5.4-mini-2026-03-17"]
    wire_api: Literal["responses"]
    timeout_seconds: float
    max_retries: Literal[2]
    fail_closed_action: Literal["raise"]
    logical_primary_decision_opportunities: Literal[1800]
    logical_shadow_decision_opportunities: Literal[1800]
    logical_decision_opportunities: Literal[3600]
    below_delivery_capacity_pairs: Literal[1200]
    counts: _ConcurrentFormalCounts
    per_message: dict[str, _ConcurrentPerMessageContract]
    variant_provider_accounting: dict[str, _ConcurrentVariantProviderAccounting]
    artifact_sha256: dict[str, str]

    @model_validator(mode="after")
    def _validate_formal_contract(self) -> _ReleaseContractV4:
        if set(self.per_message) != {"message_1", "message_2", "message_3"}:
            raise ValueError("per_message must cover exactly the approved three message ids")
        if any(not message_id.strip() for message_id in self.per_message):
            raise ValueError("per_message message ids must be non-empty")
        if self.timeout_seconds != 30.0:
            raise ValueError("timeout_seconds must remain the approved 30.0 seconds contract")
        if set(self.variant_provider_accounting) != {"primary", "shadow", "total"}:
            raise ValueError("variant_provider_accounting must contain primary/shadow/total exactly once")
        if self.logical_primary_decision_opportunities != self.counts.primary_attempted:
            raise ValueError("logical_primary_decision_opportunities must equal counts.primary_attempted")
        if self.logical_shadow_decision_opportunities != self.counts.shadow_attempted:
            raise ValueError("logical_shadow_decision_opportunities must equal counts.shadow_attempted")
        if self.logical_decision_opportunities != (
            self.logical_primary_decision_opportunities + self.logical_shadow_decision_opportunities
        ):
            raise ValueError("logical_decision_opportunities must equal primary + shadow logical opportunities")

        per_message_exposures = 0
        per_message_below_capacity = 0
        for contract_payload in self.per_message.values():
            per_message_exposures += contract_payload.exposures
            per_message_below_capacity += contract_payload.below_delivery_capacity
        if per_message_exposures != self.counts.actual_exposures:
            raise ValueError("per_message exposures must sum to counts.actual_exposures")
        if per_message_below_capacity != self.below_delivery_capacity_pairs:
            raise ValueError("per_message below_delivery_capacity must sum to below_delivery_capacity_pairs")
        if self.counts.eligible_user_message_pairs != self.counts.actual_exposures + self.below_delivery_capacity_pairs:
            raise ValueError("eligible_user_message_pairs must equal actual_exposures + below_delivery_capacity_pairs")

        primary = self.variant_provider_accounting["primary"]
        shadow = self.variant_provider_accounting["shadow"]
        total = self.variant_provider_accounting["total"]
        for variant_name, accounting, expected_successes in (
            ("primary", primary, self.counts.primary_successes),
            ("shadow", shadow, self.counts.shadow_successes),
        ):
            if accounting.successful_decisions != expected_successes:
                raise ValueError(f"{variant_name} successful_decisions must equal Formal successes")
            if accounting.responses != expected_successes:
                raise ValueError(f"{variant_name} responses must equal Formal successes")
            if accounting.invocations < accounting.responses:
                raise ValueError(f"{variant_name} invocations cannot be lower than responses")
            if accounting.observed_model_counts != {self.observed_model: accounting.responses}:
                raise ValueError(f"{variant_name} observed_model_counts must report only the exact observed_model")
            if accounting.observed_model_missing_response_count or accounting.observed_model_malformed_response_count:
                raise ValueError(f"{variant_name} observed_model accounting must be complete")
            if accounting.usage_complete_attempts != expected_successes or accounting.usage_incomplete_attempts != 0:
                raise ValueError(
                    f"{variant_name} usage attempt accounting must cover only complete successful attempts"
                )
            if (
                accounting.usage_complete_response_count != accounting.responses
                or accounting.usage_missing_response_count
                or accounting.usage_malformed_response_count
            ):
                raise ValueError(f"{variant_name} usage accounting must be complete for every response")
            if accounting.input_usage is None or accounting.output_usage is None or accounting.total_usage is None:
                raise ValueError(f"{variant_name} Formal accounting requires complete usage aggregates")

        if total.successful_decisions != self.logical_decision_opportunities:
            raise ValueError("total successful_decisions must equal logical_decision_opportunities")
        if total.responses != primary.responses + shadow.responses:
            raise ValueError("total responses must equal primary + shadow responses")
        if total.invocations != primary.invocations + shadow.invocations:
            raise ValueError("total invocations must equal primary + shadow invocations")
        if total.observed_model_counts != {self.observed_model: total.responses}:
            raise ValueError("total observed_model_counts must report only the exact observed_model")
        if total.observed_model_missing_response_count or total.observed_model_malformed_response_count:
            raise ValueError("total observed model accounting must be complete")
        if total.usage_complete_attempts != self.logical_decision_opportunities or total.usage_incomplete_attempts != 0:
            raise ValueError("total usage attempt accounting must equal logical_decision_opportunities")
        if (
            total.usage_complete_response_count != total.responses
            or total.usage_missing_response_count
            or total.usage_malformed_response_count
        ):
            raise ValueError("total usage accounting must be complete for every response")
        if total.input_usage is None or total.output_usage is None or total.total_usage is None:
            raise ValueError("total Formal accounting requires complete usage aggregates")
        if total.input_usage != (primary.input_usage or 0) + (shadow.input_usage or 0):
            raise ValueError("total input_usage must equal primary + shadow input_usage")
        if total.output_usage != (primary.output_usage or 0) + (shadow.output_usage or 0):
            raise ValueError("total output_usage must equal primary + shadow output_usage")
        if total.total_usage != (primary.total_usage or 0) + (shadow.total_usage or 0):
            raise ValueError("total total_usage must equal primary + shadow total_usage")
        return self


class _ConcurrentTerminalAccountingBucket(TypedDict):
    invocations: int
    responses: int
    successful_decisions: int
    observed_model_counts: dict[str, int]
    observed_model_missing_response_count: int
    observed_model_malformed_response_count: int
    usage_complete_attempts: int
    usage_incomplete_attempts: int
    usage_complete_response_count: int
    usage_missing_response_count: int
    usage_malformed_response_count: int
    input_usage_total: int
    output_usage_total: int
    total_usage_total: int
    cached_input_usage_total: int
    has_cached_input_usage: bool


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseValidationError(f"cannot read valid JSON from {path}: {exc}") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_artifact(source_dir: Path, raw_path: object, label: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path:
        raise ReleaseValidationError(f"{label} must be a non-empty relative path")
    relative = Path(raw_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ReleaseValidationError(f"{label} is not a safe relative path: {raw_path}")
    artifact = source_dir / relative
    if artifact.is_symlink() or not artifact.is_file():
        raise ReleaseValidationError(f"{label} is missing, not a file, or a symlink: {raw_path}")
    return artifact


def _reject_symlinks(source_dir: Path) -> None:
    if source_dir.is_symlink():
        raise ReleaseValidationError("source directory must not be a symlink")
    for directory, directory_names, file_names in os.walk(source_dir, followlinks=False):
        root = Path(directory)
        for name in [*directory_names, *file_names]:
            entry = root / name
            relative = entry.relative_to(source_dir)
            mode = entry.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise ReleaseValidationError(f"source directory contains symlink: {relative}")
            if not stat.S_ISDIR(mode) and not stat.S_ISREG(mode):
                raise ReleaseValidationError(f"release directory contains non-regular entry: {relative}")


def _expect_equal(actual: object, expected: object, label: str) -> None:
    if actual != expected:
        raise ReleaseValidationError(f"{label} mismatch: expected {expected!r}, got {actual!r}")


def _regular_contract_file(repo_root: Path, contract_path: Path) -> Path:
    candidate = contract_path if contract_path.is_absolute() else repo_root / contract_path
    candidate = candidate.absolute()
    if candidate.is_symlink():
        raise ReleaseValidationError("release contract must not contain symlink components")
    if not candidate.is_file():
        raise ReleaseValidationError("release contract must be a regular file")
    return candidate


def _safe_contract_file(repo_root: Path, contract_path: Path) -> Path:
    candidate = _regular_contract_file(repo_root, contract_path)
    if ".." in contract_path.parts:
        raise ReleaseValidationError("release contract path must not contain '..'")
    try:
        relative = candidate.relative_to(repo_root)
    except ValueError as exc:
        raise ReleaseValidationError("release contract must stay inside repo root") from exc
    current = repo_root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ReleaseValidationError("release contract must not contain symlink components")
    if not current.is_file():  # pragma: no cover - checked before component traversal.
        raise ReleaseValidationError("release contract must be a regular file")
    return current


def _reject_source_symlink_components(repo_root: Path, path: Path) -> None:
    candidate = path if path.is_absolute() else path.absolute()
    try:
        relative = candidate.relative_to(repo_root)
    except ValueError as exc:
        raise ReleaseValidationError("source directory must stay inside repo root") from exc
    current = repo_root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ReleaseValidationError("source directory must not contain symlink components")


def _validated_source_directory(
    *,
    repo_root: Path,
    raw_expected_source: object,
    source_dir: Path,
) -> tuple[str, Path]:
    if not isinstance(raw_expected_source, str):
        raise ReleaseValidationError("contract source_directory must be a relative path")
    expected_relative = Path(raw_expected_source)
    if expected_relative.is_absolute() or ".." in expected_relative.parts:
        raise ReleaseValidationError("contract source_directory must be a safe relative path")
    expected_path = repo_root / expected_relative
    provided_path = source_dir if source_dir.is_absolute() else source_dir.absolute()
    _reject_source_symlink_components(repo_root, expected_path)
    _reject_source_symlink_components(repo_root, provided_path)
    expected_source = expected_path.resolve()
    resolved_source = provided_path.resolve()
    _expect_equal(resolved_source, expected_source, "source directory")
    try:
        resolved_source.relative_to(repo_root)
    except ValueError as exc:
        raise ReleaseValidationError("source directory must stay inside repo root") from exc
    if not source_dir.is_dir():
        raise ReleaseValidationError(f"source directory does not exist: {source_dir}")
    _reject_symlinks(source_dir)
    return raw_expected_source, resolved_source


def _validate_v1(*, repo_root: Path, contract: dict[str, object], source_dir: Path) -> dict[str, object]:
    _expect_equal(contract.get("schema_version"), "abm-report-release-contract-v1", "contract schema_version")
    _expect_equal(
        contract.get("payload_schema_version"),
        "final-research-ranking-report-payload-v4",
        "v1 payload_schema_version",
    )
    _expect_equal(
        contract.get("manifest_version"),
        "final-research-ranking-runtime-v2",
        "v1 manifest_version",
    )
    _expect_equal(
        contract.get("sampling_method"),
        "seed_first_research_sample_v1",
        "v1 sampling_method",
    )
    _expect_equal(contract.get("sampling_status"), "validation_run", "v1 sampling_status")

    raw_expected_source, source_dir = _validated_source_directory(
        repo_root=repo_root,
        raw_expected_source=contract.get("source_directory"),
        source_dir=source_dir,
    )

    manifest = _load_json(_safe_artifact(source_dir, "artifact_manifest.json", "artifact manifest"))
    payload = _load_json(_safe_artifact(source_dir, "final_research_report_payload.json", "ranking report payload"))
    sample_audit = _load_json(_safe_artifact(source_dir, "seed_first_sample_audit.json", "sample audit"))
    sample_manifest = _load_json(_safe_artifact(source_dir, "sample_manifest.json", "sample manifest"))
    if not all(isinstance(value, dict) for value in (manifest, payload, sample_audit)):
        raise ReleaseValidationError("manifest, payload, and sample audit must be JSON objects")
    if not isinstance(sample_manifest, list):
        raise ReleaseValidationError("sample manifest must be a JSON array")

    sampling_method = contract.get("sampling_method")
    sampling_status = contract.get("sampling_status")
    role_counts = contract.get("sample_role_counts")
    if not isinstance(role_counts, dict) or not all(
        isinstance(role, str) and isinstance(count, int) and count >= 0 for role, count in role_counts.items()
    ):
        raise ReleaseValidationError("contract sample_role_counts must map roles to non-negative integers")

    _expect_equal(manifest.get("manifest_version"), contract.get("manifest_version"), "manifest version")
    _expect_equal(payload.get("schema_version"), contract.get("payload_schema_version"), "payload schema_version")
    _expect_equal(manifest.get("sampling_method"), sampling_method, "manifest sampling_method")
    _expect_equal(manifest.get("sampling_status"), sampling_status, "manifest sampling_status")
    _expect_equal(manifest.get("live_api_triggered"), False, "manifest live_api_triggered")
    _expect_equal(manifest.get("sample_role_counts"), role_counts, "manifest sample role counts")
    _expect_equal(sample_audit.get("sampling_method"), sampling_method, "sample audit sampling_method")
    _expect_equal(sample_audit.get("sampling_status"), sampling_status, "sample audit sampling_status")
    _expect_equal(sample_audit.get("roles", {}).get("counts"), role_counts, "sample audit role counts")
    _expect_equal(payload.get("run", {}).get("sampling_method"), sampling_method, "payload sampling_method")
    _expect_equal(payload.get("run", {}).get("sampling_status"), sampling_status, "payload sampling_status")
    _expect_equal(payload.get("sample_role_counts"), role_counts, "payload sample role counts")

    actual_role_counts = dict(Counter(record.get("sample_role") for record in sample_manifest))
    _expect_equal(actual_role_counts, role_counts, "sample manifest role counts")
    sample_size = sum(role_counts.values())
    _expect_equal(len(sample_manifest), sample_size, "sample manifest size")
    _expect_equal(manifest.get("counts", {}).get("sample_users"), sample_size, "manifest sample_users")
    _expect_equal(payload.get("run", {}).get("sample_size"), sample_size, "payload sample_size")

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise ReleaseValidationError("manifest artifacts must be a non-empty object")
    manifest_paths: set[str] = set()
    for key, raw_path in artifacts.items():
        _safe_artifact(source_dir, raw_path, f"manifest artifact {key}")
        manifest_paths.add(str(raw_path))

    downloads = payload.get("downloads")
    if not isinstance(downloads, dict) or not downloads:
        raise ReleaseValidationError("payload downloads must be a non-empty object")
    for key, raw_path in downloads.items():
        _safe_artifact(source_dir, raw_path, f"payload download {key}")

    expected_hashes = contract.get("artifact_sha256")
    if not isinstance(expected_hashes, dict) or not expected_hashes:
        raise ReleaseValidationError("contract artifact_sha256 must be a non-empty object")
    for raw_path, expected_hash in expected_hashes.items():
        artifact = _safe_artifact(source_dir, raw_path, f"hashed artifact {raw_path}")
        if raw_path != "artifact_manifest.json" and raw_path not in manifest_paths:
            raise ReleaseValidationError(f"hashed artifact is absent from manifest: {raw_path}")
        _expect_equal(_sha256(artifact), expected_hash, f"SHA-256 for {raw_path}")

    return {
        "schema_version": "abm-report-release-contract-v1",
        "release_purpose": "validation",
        "source_directory": raw_expected_source,
        "sampling_method": sampling_method,
        "sampling_status": sampling_status,
        "sample_role_counts": role_counts,
        "artifact_count": len(artifacts),
        "report_sha256": expected_hashes.get("report.html"),
        "production_deploy_eligible": False,
    }


def _validate_v2(
    *,
    repo_root: Path,
    contract_document: dict[str, object],
    source_dir: Path,
    snapshot_dir: Path | None = None,
) -> dict[str, object]:
    try:
        contract = _ReleaseContractV2.model_validate(contract_document)
    except ValidationError as exc:
        raise ReleaseValidationError(f"invalid v2 release contract: {exc}") from exc
    raw_expected_source, source_dir = _validated_source_directory(
        repo_root=repo_root,
        raw_expected_source=contract.source_directory,
        source_dir=source_dir,
    )
    evidence_dir = source_dir
    if snapshot_dir is not None:
        if snapshot_dir.is_symlink() or not snapshot_dir.is_dir():
            raise ReleaseValidationError("release snapshot must be a non-symlink directory")
        _reject_symlinks(snapshot_dir)
        evidence_dir = snapshot_dir.resolve()
    try:
        validated = _validate_persisted_ranking_report(evidence_dir)
    except (OSError, ValueError) as exc:
        raise ReleaseValidationError(f"persisted v5 evidence is invalid: {exc}") from exc
    if not isinstance(validated.payload, FinalResearchRankingReportPayloadV5):
        raise ReleaseValidationError("v2 release contract requires a v5 ranking report payload")
    payload = validated.payload
    if not isinstance(payload.evidence_state, RankingV5FormalEvidence):
        raise ReleaseValidationError("v2 release contract requires formal v5 evidence")
    decision = payload.evidence_state.decision_execution_evidence
    if decision.adapter_chain[-1:] != ["openai_compatible"]:
        raise ReleaseValidationError("formal Decision evidence requires the OpenAI-compatible adapter path")
    if decision.provider_metadata.get("adapter") != "openai_compatible":
        raise ReleaseValidationError("formal Decision evidence provider metadata does not match its adapter path")
    if set(decision.decision_source_counts) - {"provider"}:
        raise ReleaseValidationError("formal Decision evidence contains a non-provider Decision source")

    diagnostics = payload.ranking_diagnostics
    historical = diagnostics.get("historical_top20_diagnostic")
    if not isinstance(historical, dict):  # pragma: no cover - validated by the payload model.
        raise ReleaseValidationError("v2 release requires historical Top20 diagnostics")
    aggregate_reference = historical.get("target_aggregate_engagement_reference")
    evidence_expectations = {
        "sample_role_counts": payload.sample_role_counts,
        "decision_source_counts": decision.decision_source_counts,
        "action_counts": decision.action_counts,
        "terminal_counts": decision.terminal_counts.model_dump(mode="json"),
        "degeneracy_flags": decision.degeneracy_flags.model_dump(mode="json"),
        "target_aggregate_engagement_reference": aggregate_reference,
    }
    contract_evidence = {
        "sample_role_counts": contract.sample_role_counts,
        "decision_source_counts": contract.decision_source_counts,
        "action_counts": contract.action_counts,
        "terminal_counts": contract.terminal_counts.model_dump(mode="json"),
        "degeneracy_flags": contract.degeneracy_flags.model_dump(mode="json"),
        "target_aggregate_engagement_reference": contract.target_aggregate_engagement_reference.model_dump(mode="json"),
    }
    for field_name, expected in evidence_expectations.items():
        _expect_equal(contract_evidence[field_name], expected, f"v2 {field_name}")

    _expect_equal(payload.run.sampling_method, contract.sampling_method, "v2 sampling_method")
    _expect_equal(payload.run.sampling_status, contract.sampling_status, "v2 sampling_status")
    _expect_equal(decision.schema_version, contract.decision_execution_evidence_schema_version, "v2 Decision schema")
    _expect_equal(decision.decision_execution_mode, contract.decision_execution_mode, "v2 execution mode")
    _expect_equal(decision.live_api_triggered, contract.live_api_triggered, "v2 live_api_triggered")
    _expect_equal(
        decision.formal_research_evidence,
        contract.formal_research_evidence,
        "v2 formal_research_evidence",
    )
    _expect_equal(
        payload.evidence_state.schema_version,
        contract.evidence_schema_version,
        "v2 evidence schema",
    )
    _expect_equal(
        payload.evidence_state.production_deploy_eligible,
        contract.production_deploy_eligible,
        "v2 production_deploy_eligible",
    )

    artifacts = validated.manifest.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise ReleaseValidationError("v2 artifact manifest must contain artifacts")
    manifest_paths = list(artifacts.values())
    if not all(isinstance(path, str) for path in manifest_paths):  # pragma: no cover - reader validates this.
        raise ReleaseValidationError("v2 artifact manifest paths must be strings")
    if len(manifest_paths) != len(set(manifest_paths)):
        raise ReleaseValidationError("v2 artifact manifest paths must be unique")
    required_hash_paths = {*manifest_paths, "artifact_manifest.json"}
    source_files = {path.relative_to(evidence_dir).as_posix() for path in evidence_dir.rglob("*") if path.is_file()}
    if source_files != required_hash_paths:
        raise ReleaseValidationError(
            "source directory contains files outside the v2 artifact manifest or omits declared files; "
            f"missing={sorted(required_hash_paths - source_files)}, "
            f"extra={sorted(source_files - required_hash_paths)}"
        )
    actual_hash_paths = set(contract.artifact_sha256)
    if actual_hash_paths != required_hash_paths:
        raise ReleaseValidationError(
            "v2 artifact_sha256 must cover the exact manifest artifacts and artifact_manifest.json; "
            f"missing={sorted(required_hash_paths - actual_hash_paths)}, "
            f"extra={sorted(actual_hash_paths - required_hash_paths)}"
        )
    for raw_path, expected_hash in contract.artifact_sha256.items():
        if len(expected_hash) != 64 or any(character not in "0123456789abcdef" for character in expected_hash):
            raise ReleaseValidationError(f"v2 SHA-256 for {raw_path} must be 64 lowercase hexadecimal characters")
        artifact = _safe_artifact(evidence_dir, raw_path, f"v2 hashed artifact {raw_path}")
        _expect_equal(_sha256(artifact), expected_hash, f"SHA-256 for {raw_path}")

    return {
        "schema_version": contract.schema_version,
        "release_purpose": contract.release_purpose,
        "source_directory": raw_expected_source,
        "sampling_method": contract.sampling_method,
        "sampling_status": contract.sampling_status,
        "sample_role_counts": contract.sample_role_counts,
        "decision_execution_mode": contract.decision_execution_mode,
        "live_api_triggered": contract.live_api_triggered,
        "artifact_count": len(artifacts),
        "report_sha256": contract.artifact_sha256["report.html"],
        "production_deploy_eligible": contract.production_deploy_eligible,
    }


def _validate_v3(
    *,
    repo_root: Path,
    contract_document: dict[str, object],
    source_dir: Path,
    snapshot_dir: Path | None = None,
) -> dict[str, object]:
    try:
        contract = _ReleaseContractV3.model_validate(contract_document)
    except ValidationError as exc:
        raise ReleaseValidationError(f"invalid v3 release contract: {exc}") from exc
    raw_expected_source, source_dir = _validated_source_directory(
        repo_root=repo_root,
        raw_expected_source=contract.source_directory,
        source_dir=source_dir,
    )
    evidence_dir = source_dir
    if snapshot_dir is not None:
        if snapshot_dir.is_symlink() or not snapshot_dir.is_dir():
            raise ReleaseValidationError("release snapshot must be a non-symlink directory")
        _reject_symlinks(snapshot_dir)
        evidence_dir = snapshot_dir.resolve()
    try:
        validated = _validate_persisted_ranking_report(evidence_dir)
    except (OSError, ValueError) as exc:
        raise ReleaseValidationError(f"persisted v6 evidence is invalid: {exc}") from exc
    if not isinstance(validated.payload, FinalResearchRankingReportPayloadV6):
        raise ReleaseValidationError("v3 release contract requires a v6 ranking report payload")
    payload = validated.payload
    if not isinstance(payload.evidence_state, RankingV6FormalEvidence):
        raise ReleaseValidationError("v3 release contract requires Formal v6 evidence")
    if not payload.evidence_state.production_deploy_eligible:
        raise ReleaseValidationError("v3 release contract requires production-deploy-eligible v6 evidence")
    decision = payload.evidence_state.decision_execution_evidence
    accounting = decision.provider_accounting
    if decision.adapter_chain != ["openai_compatible"]:
        raise ReleaseValidationError("v3 Formal evidence requires bare ['openai_compatible'] adapter chain")
    if decision.provider_metadata.get("adapter") != "openai_compatible":
        raise ReleaseValidationError("v3 Formal provider metadata does not match the adapter chain")
    if (
        decision.provider_metadata.get("enabled") is not True
        or decision.provider_metadata.get("require_live_env") is not True
    ):
        raise ReleaseValidationError("v3 Formal provider metadata requires the explicit live environment gate")
    if decision.provider_metadata.get("model") != contract.requested_model:
        raise ReleaseValidationError("v3 requested model does not match persisted Provider metadata")
    if set(decision.decision_source_counts) - {"provider"}:
        raise ReleaseValidationError("v3 Formal evidence contains a non-provider Decision source")
    if not (
        accounting.external_request_invocations
        >= accounting.provider_response_count
        >= accounting.successful_decision_count
        == decision.terminal_counts.decided_users
    ):
        raise ReleaseValidationError(
            "v3 persisted accounting requires invocations >= responses >= successful Decisions == decided_users"
        )
    if accounting.observed_model_counts != {contract.observed_model: accounting.provider_response_count}:
        raise ReleaseValidationError("v3 observed models do not match the exact contract observed_model")
    if accounting.observed_model_missing_response_count or accounting.observed_model_malformed_response_count:
        raise ReleaseValidationError("v3 observed-model accounting is incomplete")
    if (
        accounting.usage_complete_response_count != accounting.provider_response_count
        or accounting.usage_missing_response_count
        or accounting.usage_malformed_response_count
    ):
        raise ReleaseValidationError("v3 usage accounting is incomplete")

    artifacts = validated.manifest.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise ReleaseValidationError("v3 artifact manifest must contain artifacts")
    diagnostics = payload.ranking_diagnostics
    historical = diagnostics.get("historical_top20_diagnostic")
    if not isinstance(historical, dict):  # pragma: no cover - validated by the payload model.
        raise ReleaseValidationError("v3 release requires historical Top20 diagnostics")
    aggregate_reference = historical.get("target_aggregate_engagement_reference")
    evidence_expectations = {
        "sample_role_counts": payload.sample_role_counts,
        "decision_source_counts": decision.decision_source_counts,
        "action_counts": decision.action_counts,
        "terminal_counts": decision.terminal_counts.model_dump(mode="json"),
        "degeneracy_flags": decision.degeneracy_flags.model_dump(mode="json"),
        "provider_accounting": accounting.model_dump(mode="json"),
        "reason_context_diagnostics": payload.reason_context_diagnostics.model_dump(mode="json"),
        "target_aggregate_engagement_reference": aggregate_reference,
    }
    contract_evidence = {
        "sample_role_counts": contract.sample_role_counts,
        "decision_source_counts": contract.decision_source_counts,
        "action_counts": contract.action_counts,
        "terminal_counts": contract.terminal_counts.model_dump(mode="json"),
        "degeneracy_flags": contract.degeneracy_flags.model_dump(mode="json"),
        "provider_accounting": contract.provider_accounting.model_dump(mode="json"),
        "reason_context_diagnostics": contract.reason_context_diagnostics.model_dump(mode="json"),
        "target_aggregate_engagement_reference": contract.target_aggregate_engagement_reference.model_dump(mode="json"),
    }
    for field_name, expected in evidence_expectations.items():
        _expect_equal(contract_evidence[field_name], expected, f"v3 {field_name}")

    _expect_equal(payload.run.sampling_method, contract.sampling_method, "v3 sampling_method")
    _expect_equal(payload.run.sampling_status, contract.sampling_status, "v3 sampling_status")
    _expect_equal(decision.schema_version, contract.decision_execution_evidence_schema_version, "v3 Decision schema")
    _expect_equal(decision.decision_execution_mode, contract.decision_execution_mode, "v3 execution mode")
    _expect_equal(decision.adapter_chain, contract.adapter_chain, "v3 adapter chain")
    _expect_equal(decision.live_api_triggered, contract.live_api_triggered, "v3 live_api_triggered")
    _expect_equal(decision.formal_research_evidence, contract.formal_research_evidence, "v3 Formal evidence")
    _expect_equal(payload.evidence_state.schema_version, contract.evidence_schema_version, "v3 evidence schema")
    _expect_equal(
        payload.evidence_state.production_deploy_eligible,
        contract.production_deploy_eligible,
        "v3 production_deploy_eligible",
    )

    manifest_paths = list(artifacts.values())
    if not all(isinstance(path, str) for path in manifest_paths):  # pragma: no cover - reader validates this.
        raise ReleaseValidationError("v3 artifact manifest paths must be strings")
    if len(manifest_paths) != len(set(manifest_paths)):
        raise ReleaseValidationError("v3 artifact manifest paths must be unique")
    required_hash_paths = {*manifest_paths, "artifact_manifest.json"}
    source_files = {path.relative_to(evidence_dir).as_posix() for path in evidence_dir.rglob("*") if path.is_file()}
    if source_files != required_hash_paths:
        raise ReleaseValidationError(
            "source directory contains files outside the v3 artifact manifest or omits declared files; "
            f"missing={sorted(required_hash_paths - source_files)}, "
            f"extra={sorted(source_files - required_hash_paths)}"
        )
    actual_hash_paths = set(contract.artifact_sha256)
    if actual_hash_paths != required_hash_paths:
        raise ReleaseValidationError(
            "v3 artifact_sha256 must cover the exact manifest artifacts and artifact_manifest.json; "
            f"missing={sorted(required_hash_paths - actual_hash_paths)}, "
            f"extra={sorted(actual_hash_paths - required_hash_paths)}"
        )
    for raw_path, expected_hash in contract.artifact_sha256.items():
        if len(expected_hash) != 64 or any(character not in "0123456789abcdef" for character in expected_hash):
            raise ReleaseValidationError(f"v3 SHA-256 for {raw_path} must be 64 lowercase hexadecimal characters")
        artifact = _safe_artifact(evidence_dir, raw_path, f"v3 hashed artifact {raw_path}")
        _expect_equal(_sha256(artifact), expected_hash, f"SHA-256 for {raw_path}")

    return {
        "schema_version": contract.schema_version,
        "release_purpose": contract.release_purpose,
        "source_directory": raw_expected_source,
        "sampling_method": contract.sampling_method,
        "sampling_status": contract.sampling_status,
        "sample_role_counts": contract.sample_role_counts,
        "decision_execution_mode": contract.decision_execution_mode,
        "requested_model": contract.requested_model,
        "observed_model": contract.observed_model,
        "live_api_triggered": contract.live_api_triggered,
        "artifact_count": len(artifacts),
        "report_sha256": contract.artifact_sha256["report.html"],
        "production_deploy_eligible": contract.production_deploy_eligible,
    }


def _validate_v4(
    *,
    repo_root: Path,
    contract_document: dict[str, object],
    source_dir: Path,
    snapshot_dir: Path | None = None,
) -> dict[str, object]:
    try:
        contract = _ReleaseContractV4.model_validate(contract_document)
    except ValidationError as exc:
        raise ReleaseValidationError(f"invalid v4 release contract: {exc}") from exc
    raw_expected_source, source_dir = _validated_source_directory(
        repo_root=repo_root,
        raw_expected_source=contract.source_directory,
        source_dir=source_dir,
    )
    evidence_dir = source_dir
    if snapshot_dir is not None:
        if snapshot_dir.is_symlink() or not snapshot_dir.is_dir():
            raise ReleaseValidationError("release snapshot must be a non-symlink directory")
        _reject_symlinks(snapshot_dir)
        evidence_dir = snapshot_dir.resolve()

    try:
        closure: ConcurrentMessageArtifactClosure = close_concurrent_message_artifacts(evidence_dir)
    except (OSError, ValueError, ValidationError) as exc:
        raise ReleaseValidationError(f"persisted concurrent message evidence is invalid: {exc}") from exc
    manifest = closure.manifest
    sample_audit = closure.source_evidence.sample_audit
    _expect_equal(manifest.schema_version, contract.artifact_manifest_schema_version, "v4 artifact manifest schema")
    _expect_equal(manifest.report_schema, contract.payload_schema_version, "v4 report payload schema")
    _expect_equal(manifest.users_schema, contract.users_schema_version, "v4 users schema")
    _expect_equal(manifest.runtime_schema, contract.runtime_schema_version, "v4 runtime schema")
    _expect_equal(manifest.diagnostics_schema, contract.diagnostics_schema_version, "v4 diagnostics schema")
    _expect_equal(manifest.decision_trace_schema, contract.decision_trace_schema_version, "v4 decision trace schema")
    _expect_equal(manifest.validation_schema, contract.validation_schema_version, "v4 validation schema")
    _expect_equal(manifest.primary_prompt_token, contract.primary_prompt_token, "v4 primary prompt token")
    _expect_equal(manifest.shadow_prompt_token, contract.shadow_prompt_token, "v4 shadow prompt token")
    if closure.source_evidence.sample_audit is None:
        raise ReleaseValidationError("v4 artifact manifest must include sample_audit")

    required_hash_paths = {*manifest.artifacts.values(), "artifact_manifest.json"}
    source_files = set(closure.source_files)
    if source_files != required_hash_paths:
        raise ReleaseValidationError(
            "source directory contains files outside the v4 artifact manifest or omits declared files; "
            f"missing={sorted(required_hash_paths - source_files)}, "
            f"extra={sorted(source_files - required_hash_paths)}"
        )
    actual_hash_paths = set(contract.artifact_sha256)
    if actual_hash_paths != required_hash_paths:
        raise ReleaseValidationError(
            "v4 artifact_sha256 must cover the exact manifest artifacts and artifact_manifest.json; "
            f"missing={sorted(required_hash_paths - actual_hash_paths)}, "
            f"extra={sorted(actual_hash_paths - required_hash_paths)}"
        )
    manifest_hashes_by_path = dict(closure.artifact_hashes)
    for name, relative_path in manifest.artifacts.items():
        manifest_hashes_by_path[relative_path] = manifest.sha256[name]
    for raw_path, expected_hash in contract.artifact_sha256.items():
        if len(expected_hash) != 64 or any(character not in "0123456789abcdef" for character in expected_hash):
            raise ReleaseValidationError(f"v4 SHA-256 for {raw_path} must be 64 lowercase hexadecimal characters")
        _safe_artifact(evidence_dir, raw_path, f"v4 hashed artifact {raw_path}")
        actual_hash = closure.artifact_hashes.get(raw_path)
        if actual_hash is None:
            raise ReleaseValidationError(f"v4 hashed artifact is absent from the persisted closure: {raw_path}")
        _expect_equal(actual_hash, expected_hash, f"SHA-256 for {raw_path}")
        _expect_equal(manifest_hashes_by_path[raw_path], expected_hash, f"v4 manifest SHA-256 for {raw_path}")

    source_evidence = closure.source_evidence
    config_snapshot = source_evidence.config_snapshot
    message_snapshot = source_evidence.message_snapshot
    candidate_rows = source_evidence.candidate_rows
    pair_rows = source_evidence.pair_rows
    terminal_rows = source_evidence.terminal_rows
    validation_summary = source_evidence.validation_summary
    campaign_diagnostics = source_evidence.campaign_diagnostics
    sample_audit = source_evidence.sample_audit
    users_document = closure.users_document
    decision_trace_document = closure.decision_trace_document
    runtime_document = closure.runtime_document
    diagnostics_document = closure.diagnostics_document
    field_lineage_document = closure.field_lineage_document
    payload = closure.report_payload
    primary_actions_rows = closure.primary_actions_rows
    provider_failure_rows = closure.provider_failure_rows
    if not isinstance(sample_audit, dict):
        raise ReleaseValidationError("v4 sample_audit must be a JSON object")

    contract_message_identity = {
        message_id: {
            "title": contract_payload.message_title,
            "intended_audience_segment": contract_payload.intended_audience_segment,
        }
        for message_id, contract_payload in contract.per_message.items()
    }
    message_snapshot_by_id: dict[str, dict[str, Any]] = {}
    for message in message_snapshot:
        message_id = message.get("message_id")
        if not isinstance(message_id, str) or not message_id.strip():
            raise ReleaseValidationError("v4 message snapshot rows require a non-empty message_id")
        if message_id in message_snapshot_by_id:
            raise ReleaseValidationError(f"duplicate v4 message snapshot identity: {message_id}")
        message_snapshot_by_id[message_id] = message
    if set(message_snapshot_by_id) != set(contract_message_identity):
        raise ReleaseValidationError(
            "v4 message snapshot identity domain must equal contract per_message keys; "
            f"missing={sorted(set(contract_message_identity) - set(message_snapshot_by_id))}, "
            f"extra={sorted(set(message_snapshot_by_id) - set(contract_message_identity))}"
        )
    for message_id, identity in contract_message_identity.items():
        persisted_message = message_snapshot_by_id[message_id]
        _expect_equal(
            persisted_message.get("title"),
            identity["title"],
            f"v4 message snapshot {message_id} title",
        )
        _expect_equal(
            persisted_message.get("intended_audience_segment"),
            identity["intended_audience_segment"],
            f"v4 message snapshot {message_id} intended audience segment",
        )
    _expect_equal(config_snapshot.get("messages"), message_snapshot, "v4 config message snapshot")
    _expect_equal(validation_summary.get("messages"), message_snapshot, "v4 validation message snapshot")
    _expect_equal(config_snapshot, runtime_document.configuration, "v4 config snapshot")

    try:
        rebuilt_diagnostics = ConcurrentCampaignDiagnostics(
            delivery_capacity=int(config_snapshot.get("delivery_capacity", 0))
        ).build(candidate_rows=candidate_rows, pair_rows=pair_rows)
        validate_concurrent_validation_summary(validation_summary, rebuilt_diagnostics)
    except ValueError as exc:
        raise ReleaseValidationError(f"v4 concurrent campaign diagnostics do not close to source rows: {exc}") from exc
    rebuilt_campaign_funnel = rebuilt_diagnostics.payload.get("campaign_funnel")
    if not isinstance(rebuilt_campaign_funnel, dict):
        raise ReleaseValidationError("v4 rebuilt campaign diagnostics must contain campaign_funnel")
    rebuilt_per_message = rebuilt_campaign_funnel.get("per_message")
    if not isinstance(rebuilt_per_message, dict):
        raise ReleaseValidationError("v4 rebuilt campaign diagnostics must contain per_message")
    if set(rebuilt_per_message) != set(contract.per_message):
        raise ReleaseValidationError(
            "v4 diagnostics per_message domain must equal contract per_message keys; "
            f"missing={sorted(set(contract.per_message) - set(rebuilt_per_message))}, "
            f"extra={sorted(set(rebuilt_per_message) - set(contract.per_message))}"
        )
    for message_id, contract_payload in contract.per_message.items():
        diagnostic_payload = rebuilt_per_message[message_id]
        if not isinstance(diagnostic_payload, dict):
            raise ReleaseValidationError(f"v4 diagnostics per_message[{message_id}] must be an object")
        _expect_equal(
            diagnostic_payload.get("message_title"),
            contract_payload.message_title,
            f"v4 diagnostics per_message[{message_id}] title",
        )
        for field_name in (
            "exposures",
            "primary_successes",
            "primary_failures",
            "shadow_successes",
            "shadow_failures",
            "below_delivery_capacity",
        ):
            _expect_equal(
                diagnostic_payload.get(field_name),
                getattr(contract_payload, field_name),
                f"v4 diagnostics per_message[{message_id}].{field_name}",
            )
    _expect_equal(campaign_diagnostics, rebuilt_diagnostics.payload, "v4 campaign diagnostics")
    _expect_equal(
        validation_summary.get("campaign_diagnostics_summary"),
        rebuilt_diagnostics.summary,
        "v4 campaign diagnostics summary",
    )
    _expect_equal(
        validation_summary.get("campaign_diagnostics_schema_version"),
        contract.campaign_diagnostics_schema_version,
        "v4 campaign diagnostics schema",
    )
    _expect_equal(
        campaign_diagnostics.get("schema_version"),
        contract.campaign_diagnostics_schema_version,
        "v4 campaign diagnostics artifact schema",
    )

    prompt_contract = validation_summary.get("prompt_contract")
    if not isinstance(prompt_contract, dict):
        raise ReleaseValidationError("v4 validation prompt_contract must be an object")
    primary_prompt = prompt_contract.get("primary")
    shadow_prompt = prompt_contract.get("shadow")
    if not isinstance(primary_prompt, dict) or not isinstance(shadow_prompt, dict):
        raise ReleaseValidationError("v4 prompt_contract must contain primary and shadow objects")
    _expect_equal(
        primary_prompt.get("prompt_version"), contract.primary_prompt_token, "v4 primary prompt contract token"
    )
    _expect_equal(shadow_prompt.get("prompt_version"), contract.shadow_prompt_token, "v4 shadow prompt contract token")

    _expect_equal(payload.schema_version, contract.payload_schema_version, "v4 payload schema")
    _expect_equal(users_document.schema_version, contract.users_schema_version, "v4 users schema")
    _expect_equal(runtime_document.schema_version, contract.runtime_schema_version, "v4 runtime schema")
    _expect_equal(diagnostics_document.schema_version, contract.diagnostics_schema_version, "v4 diagnostics schema")
    _expect_equal(
        decision_trace_document.schema_version, contract.decision_trace_schema_version, "v4 decision trace schema"
    )
    _expect_equal(
        field_lineage_document.schema_version, contract.field_lineage_schema_version, "v4 field lineage schema"
    )
    _expect_equal(validation_summary.get("schema_version"), contract.validation_schema_version, "v4 validation schema")

    _expect_equal(validation_summary.get("sampling_method"), contract.sampling_method, "v4 validation sampling_method")
    _expect_equal(validation_summary.get("sampling_status"), contract.sampling_status, "v4 validation sampling_status")
    _expect_equal(config_snapshot.get("sampling_method"), contract.sampling_method, "v4 config sampling_method")
    _expect_equal(config_snapshot.get("sampling_status"), contract.sampling_status, "v4 config sampling_status")
    _expect_equal(
        runtime_document.configuration.get("sampling_method"), contract.sampling_method, "v4 runtime sampling_method"
    )
    _expect_equal(
        runtime_document.configuration.get("sampling_status"), contract.sampling_status, "v4 runtime sampling_status"
    )
    _expect_equal(payload.run.get("sampling_method"), contract.sampling_method, "v4 payload sampling_method")
    _expect_equal(payload.run.get("sampling_status"), contract.sampling_status, "v4 payload sampling_status")
    _expect_equal(sample_audit.get("sampling_method"), contract.sampling_method, "v4 sample audit sampling_method")
    _expect_equal(sample_audit.get("sampling_status"), contract.sampling_status, "v4 sample audit sampling_status")

    _expect_equal(
        validation_summary.get("production_deploy_eligible"),
        contract.production_deploy_eligible,
        "v4 validation production_deploy_eligible",
    )
    _expect_equal(
        config_snapshot.get("production_deploy_eligible"),
        contract.production_deploy_eligible,
        "v4 config production_deploy_eligible",
    )
    _expect_equal(
        runtime_document.configuration.get("production_deploy_eligible"),
        contract.production_deploy_eligible,
        "v4 runtime production_deploy_eligible",
    )
    _expect_equal(
        payload.run.get("production_deploy_eligible"),
        contract.production_deploy_eligible,
        "v4 payload production_deploy_eligible",
    )

    _expect_equal(
        config_snapshot.get("configuration_profile"), contract.configuration_profile, "v4 config configuration_profile"
    )
    _expect_equal(
        validation_summary.get("configuration", {}).get("configuration_profile")
        if isinstance(validation_summary.get("configuration"), dict)
        else None,
        contract.configuration_profile,
        "v4 validation configuration_profile",
    )
    _expect_equal(config_snapshot.get("sample_size"), contract.counts.sample_users, "v4 config sample_size")
    _expect_equal(config_snapshot.get("horizon"), 30, "v4 config horizon")
    _expect_equal(config_snapshot.get("delivery_capacity"), 20, "v4 config delivery_capacity")

    _expect_equal(
        runtime_document.prompt_tokens.get("primary"), contract.primary_prompt_token, "v4 runtime primary prompt token"
    )
    _expect_equal(
        runtime_document.prompt_tokens.get("shadow"), contract.shadow_prompt_token, "v4 runtime shadow prompt token"
    )
    _expect_equal(
        payload.run.get("prompt_tokens"),
        {"primary": contract.primary_prompt_token, "shadow": contract.shadow_prompt_token},
        "v4 payload prompt tokens",
    )
    _expect_equal(
        decision_trace_document.primary_prompt_token,
        contract.primary_prompt_token,
        "v4 decision trace primary prompt token",
    )
    _expect_equal(
        decision_trace_document.shadow_prompt_token,
        contract.shadow_prompt_token,
        "v4 decision trace shadow prompt token",
    )

    expected_counts = contract.counts.model_dump(mode="json")
    expected_per_message = {
        message_id: payload.model_dump(mode="json") for message_id, payload in contract.per_message.items()
    }
    expected_provider_accounting = {
        name: accounting.model_dump(mode="json") for name, accounting in contract.variant_provider_accounting.items()
    }
    _expect_equal(validation_summary.get("counts"), expected_counts, "v4 counts")
    _expect_equal(runtime_document.counts, expected_counts, "v4 runtime counts")
    _expect_equal(validation_summary.get("per_message"), expected_per_message, "v4 per_message counts")
    _expect_equal(
        validation_summary.get("variant_provider_accounting"),
        expected_provider_accounting,
        "v4 variant provider accounting",
    )

    if len(users_document.rows) != contract.counts.sample_users:
        raise ReleaseValidationError("v4 users document must contain exactly 1,000 users")
    if len({row.user_id for row in users_document.rows}) != len(users_document.rows):
        raise ReleaseValidationError("v4 users document must keep stable unique user_id values")

    coverage = validation_summary.get("campaign_exposure_coverage")
    if not isinstance(coverage, dict):
        raise ReleaseValidationError("v4 campaign_exposure_coverage must be an object")
    try:
        normalized_coverage = {int(key): int(value) for key, value in coverage.items()}
    except (TypeError, ValueError) as exc:
        raise ReleaseValidationError(
            f"v4 campaign_exposure_coverage must contain integer keys and values: {exc}"
        ) from exc
    if set(normalized_coverage) != {0, 1, 2, 3}:
        raise ReleaseValidationError("v4 campaign_exposure_coverage must record 0/1/2/3-message coverage exactly")
    if sum(normalized_coverage.values()) != contract.counts.sample_users:
        raise ReleaseValidationError("v4 campaign_exposure_coverage must sum to sample_users")
    if (
        normalized_coverage[1] + normalized_coverage[2] + normalized_coverage[3]
        != contract.counts.distinct_exposed_users
    ):
        raise ReleaseValidationError("v4 distinct_exposed_users must equal 1/2/3-message coverage total")

    if len(pair_rows) != contract.counts.actual_exposures:
        raise ReleaseValidationError("v4 pair row count must equal actual_exposures")
    pair_ids: set[str] = set()
    pair_message_keys: set[tuple[str, str]] = set()
    pair_counts_by_message: Counter[str] = Counter()
    for row in pair_rows:
        pair_id = str(row.get("pair_id", "") or "")
        message_id = str(row.get("message_id", "") or "")
        user_id = str(row.get("user_id", "") or "")
        if not pair_id or not message_id or not user_id:
            raise ReleaseValidationError("v4 pair rows require non-empty pair_id, message_id, and user_id")
        if pair_id in pair_ids:
            raise ReleaseValidationError(f"duplicate pair_id in v4 pair rows: {pair_id}")
        pair_ids.add(pair_id)
        message_key = (message_id, user_id)
        if message_key in pair_message_keys:
            raise ReleaseValidationError(f"duplicate user/message identity in v4 pair rows: {message_id}/{user_id}")
        pair_message_keys.add(message_key)
        pair_counts_by_message[message_id] += 1
        if row.get("primary_status") != "succeeded" or row.get("shadow_status") != "succeeded":
            raise ReleaseValidationError("v4 Formal pair rows cannot contain provider_failed status")
        if row.get("primary_decision_source") != "provider" or row.get("shadow_decision_source") != "provider":
            raise ReleaseValidationError("v4 Formal pair rows require provider Decisions for both variants")
        if row.get("primary_prompt_version") != contract.primary_prompt_token:
            raise ReleaseValidationError("v4 pair rows crossed or changed the Primary prompt token")
        if row.get("shadow_prompt_version") != contract.shadow_prompt_token:
            raise ReleaseValidationError("v4 pair rows crossed or changed the Shadow prompt token")
        if str(row.get("pair_terminal_coverage", "")).lower() != "true":
            raise ReleaseValidationError("v4 pair rows require pair_terminal_coverage=true")
        if str(row.get("paired_decision_coverage", "")).lower() != "true":
            raise ReleaseValidationError("v4 pair rows require paired_decision_coverage=true")
    for message_id, expected in contract.per_message.items():
        if pair_counts_by_message[message_id] != expected.exposures:
            raise ReleaseValidationError(f"v4 pair rows for {message_id} must equal the contracted exposures")

    if len(decision_trace_document.rows) != contract.counts.actual_exposures:
        raise ReleaseValidationError("v4 decision trace row count must equal actual_exposures")
    trace_ids = {row.trace_id for row in decision_trace_document.rows}
    if len(trace_ids) != len(decision_trace_document.rows):
        raise ReleaseValidationError("v4 decision trace rows must keep stable unique trace_id values")
    if {row.pair_id for row in decision_trace_document.rows} != pair_ids:
        raise ReleaseValidationError("v4 decision trace rows must cover the exact pair_id set")

    if provider_failure_rows:
        raise ReleaseValidationError("v4 Formal artifacts cannot contain provider failure rows")
    if len(primary_actions_rows) != contract.counts.primary_successes:
        raise ReleaseValidationError("v4 primary_actions_csv must contain one row per Primary success")

    if len(terminal_rows) != contract.counts.terminal_rows:
        raise ReleaseValidationError("v4 terminal row count must equal counts.terminal_rows")
    terminal_by_pair_variant: set[tuple[str, str]] = set()
    terminal_accounting: dict[str, _ConcurrentTerminalAccountingBucket] = {
        name: {
            "invocations": 0,
            "responses": 0,
            "successful_decisions": 0,
            "observed_model_counts": {},
            "observed_model_missing_response_count": 0,
            "observed_model_malformed_response_count": 0,
            "usage_complete_attempts": 0,
            "usage_incomplete_attempts": 0,
            "usage_complete_response_count": 0,
            "usage_missing_response_count": 0,
            "usage_malformed_response_count": 0,
            "input_usage_total": 0,
            "output_usage_total": 0,
            "total_usage_total": 0,
            "cached_input_usage_total": 0,
            "has_cached_input_usage": False,
        }
        for name in ("primary", "shadow", "total")
    }
    for row in terminal_rows:
        pair_id = str(row.get("pair_id", "") or "")
        variant = str(row.get("decision_variant", "") or "")
        key = (pair_id, variant)
        if key in terminal_by_pair_variant:
            raise ReleaseValidationError(f"duplicate v4 terminal row identity: {pair_id}/{variant}")
        terminal_by_pair_variant.add(key)
        if variant not in {"primary", "shadow"}:
            raise ReleaseValidationError(f"unsupported v4 decision_variant: {variant!r}")
        expected_prompt = contract.primary_prompt_token if variant == "primary" else contract.shadow_prompt_token
        if row.get("prompt_version") != expected_prompt:
            raise ReleaseValidationError(f"v4 terminal rows crossed or changed the {variant} prompt token")
        if row.get("terminal_status") != "succeeded" or row.get("provider_status") != "succeeded":
            raise ReleaseValidationError("v4 Formal terminal rows cannot contain provider failures")
        if row.get("decision_source") != "provider":
            raise ReleaseValidationError("v4 Formal terminal rows require provider Decisions")
        try:
            request_invocations = int(str(row.get("request_invocations", "0") or "0"))
            provider_responses = int(str(row.get("provider_response_count", "0") or "0"))
            successful_decisions = int(str(row.get("successful_decision_count", "0") or "0"))
            observed_model_missing = int(str(row.get("observed_model_missing_response_count", "0") or "0"))
            observed_model_malformed = int(str(row.get("observed_model_malformed_response_count", "0") or "0"))
            usage_complete_response_count = int(str(row.get("usage_complete_response_count", "0") or "0"))
            usage_missing_response_count = int(str(row.get("usage_missing_response_count", "0") or "0"))
            usage_malformed_response_count = int(str(row.get("usage_malformed_response_count", "0") or "0"))
        except ValueError as exc:
            raise ReleaseValidationError(f"v4 terminal row counters must be integers: {exc}") from exc
        if request_invocations < provider_responses or provider_responses < successful_decisions:
            raise ReleaseValidationError("v4 terminal rows require invocations >= responses >= successful Decisions")
        if successful_decisions != 1:
            raise ReleaseValidationError("v4 Formal terminal rows must represent exactly one successful Decision")
        if observed_model_missing or observed_model_malformed:
            raise ReleaseValidationError("v4 Formal terminal rows cannot contain missing or malformed observed models")
        if (
            usage_complete_response_count != provider_responses
            or usage_missing_response_count
            or usage_malformed_response_count
        ):
            raise ReleaseValidationError("v4 Formal terminal rows require complete usage for every response")
        usage_complete = str(row.get("usage_complete", "")).lower() == "true"
        if not usage_complete:
            raise ReleaseValidationError("v4 Formal terminal rows require usage_complete=true")
        try:
            observed_model_counts = json.loads(str(row.get("observed_model_counts", "{}") or "{}"))
            provider_metadata = json.loads(str(row.get("provider_metadata", "{}") or "{}"))
        except json.JSONDecodeError as exc:
            raise ReleaseValidationError(f"v4 terminal row JSON payload is invalid: {exc}") from exc
        if observed_model_counts != {contract.observed_model: provider_responses}:
            raise ReleaseValidationError(
                "v4 terminal rows must report only the exact observed_model for every response"
            )
        if not isinstance(provider_metadata, dict):
            raise ReleaseValidationError("v4 terminal row provider_metadata must decode to an object")
        if (
            provider_metadata.get("adapter") != contract.provider
            or provider_metadata.get("provider") != contract.provider
        ):
            raise ReleaseValidationError(
                "v4 Formal provider metadata must stay on the bare registered live provider path"
            )
        if provider_metadata.get("enabled") is not True or provider_metadata.get("require_live_env") is not True:
            raise ReleaseValidationError("v4 Formal provider metadata requires enabled=true and require_live_env=true")
        if provider_metadata.get("model") != contract.requested_model:
            raise ReleaseValidationError("v4 requested model does not match persisted Provider metadata")
        if provider_metadata.get("wire_api") != contract.wire_api:
            raise ReleaseValidationError("v4 wire_api does not match persisted Provider metadata")
        if provider_metadata.get("timeout_seconds") != contract.timeout_seconds:
            raise ReleaseValidationError("v4 timeout_seconds does not match persisted Provider metadata")
        if provider_metadata.get("max_retries") != contract.max_retries:
            raise ReleaseValidationError("v4 max_retries does not match persisted Provider metadata")
        if provider_metadata.get("fail_closed_action") != contract.fail_closed_action:
            raise ReleaseValidationError("v4 fail_closed_action does not match persisted Provider metadata")
        if provider_metadata.get("prompt_version") != expected_prompt:
            raise ReleaseValidationError("v4 terminal row provider metadata crossed the prompt token contract")
        if (
            row.get("input_usage") in (None, "")
            or row.get("output_usage") in (None, "")
            or row.get("total_usage") in (None, "")
        ):
            raise ReleaseValidationError("v4 Formal terminal rows require complete token usage aggregates")
        try:
            input_usage = int(str(row.get("input_usage", "0") or "0"))
            output_usage = int(str(row.get("output_usage", "0") or "0"))
            total_usage = int(str(row.get("total_usage", "0") or "0"))
            cached_input_usage = (
                None
                if row.get("cached_input_usage") in (None, "")
                else int(str(row.get("cached_input_usage", "0") or "0"))
            )
        except ValueError as exc:
            raise ReleaseValidationError(f"v4 terminal row token counters must be integers: {exc}") from exc
        for bucket_name in (variant, "total"):
            bucket = terminal_accounting[bucket_name]
            bucket["invocations"] = int(bucket["invocations"]) + request_invocations
            bucket["responses"] = int(bucket["responses"]) + provider_responses
            bucket["successful_decisions"] = int(bucket["successful_decisions"]) + successful_decisions
            bucket["observed_model_missing_response_count"] = (
                int(bucket["observed_model_missing_response_count"]) + observed_model_missing
            )
            bucket["observed_model_malformed_response_count"] = (
                int(bucket["observed_model_malformed_response_count"]) + observed_model_malformed
            )
            bucket["usage_complete_attempts"] = int(bucket["usage_complete_attempts"]) + (1 if usage_complete else 0)
            bucket["usage_incomplete_attempts"] = int(bucket["usage_incomplete_attempts"]) + (
                0 if usage_complete or request_invocations == 0 else 1
            )
            bucket["usage_complete_response_count"] = (
                int(bucket["usage_complete_response_count"]) + usage_complete_response_count
            )
            bucket["usage_missing_response_count"] = (
                int(bucket["usage_missing_response_count"]) + usage_missing_response_count
            )
            bucket["usage_malformed_response_count"] = (
                int(bucket["usage_malformed_response_count"]) + usage_malformed_response_count
            )
            bucket["input_usage_total"] = int(bucket["input_usage_total"]) + input_usage
            bucket["output_usage_total"] = int(bucket["output_usage_total"]) + output_usage
            bucket["total_usage_total"] = int(bucket["total_usage_total"]) + total_usage
            if cached_input_usage is not None:
                bucket["cached_input_usage_total"] = int(bucket["cached_input_usage_total"]) + cached_input_usage
                bucket["has_cached_input_usage"] = True
            observed_counts = bucket["observed_model_counts"]
            if not isinstance(observed_counts, dict):
                raise ReleaseValidationError("v4 internal terminal accounting bucket is invalid")
            for model_name, count in observed_model_counts.items():
                observed_counts[model_name] = int(observed_counts.get(model_name, 0)) + int(count)
    for pair_id in pair_ids:
        if (pair_id, "primary") not in terminal_by_pair_variant or (pair_id, "shadow") not in terminal_by_pair_variant:
            raise ReleaseValidationError(
                f"v4 terminal rows must contain both primary and shadow entries for pair_id={pair_id}"
            )
    for variant_name in ("primary", "shadow", "total"):
        bucket = terminal_accounting[variant_name]
        observed_counts = bucket["observed_model_counts"]
        if not isinstance(observed_counts, dict):
            raise ReleaseValidationError("v4 internal terminal accounting bucket is invalid")
        terminal_provider_accounting = {
            "invocations": int(bucket["invocations"]),
            "responses": int(bucket["responses"]),
            "successful_decisions": int(bucket["successful_decisions"]),
            "observed_model_counts": dict(sorted((str(key), int(value)) for key, value in observed_counts.items())),
            "observed_model_missing_response_count": int(bucket["observed_model_missing_response_count"]),
            "observed_model_malformed_response_count": int(bucket["observed_model_malformed_response_count"]),
            "usage_complete_attempts": int(bucket["usage_complete_attempts"]),
            "usage_incomplete_attempts": int(bucket["usage_incomplete_attempts"]),
            "usage_complete_response_count": int(bucket["usage_complete_response_count"]),
            "usage_missing_response_count": int(bucket["usage_missing_response_count"]),
            "usage_malformed_response_count": int(bucket["usage_malformed_response_count"]),
            "input_usage": int(bucket["input_usage_total"]),
            "output_usage": int(bucket["output_usage_total"]),
            "total_usage": int(bucket["total_usage_total"]),
            "cached_input_usage": int(bucket["cached_input_usage_total"])
            if bool(bucket["has_cached_input_usage"])
            else None,
        }
        _expect_equal(
            terminal_provider_accounting,
            expected_provider_accounting[variant_name],
            f"v4 terminal provider accounting {variant_name}",
        )

    return {
        "schema_version": contract.schema_version,
        "release_purpose": contract.release_purpose,
        "source_directory": raw_expected_source,
        "sampling_method": contract.sampling_method,
        "sampling_status": contract.sampling_status,
        "decision_execution_mode": "live_provider",
        "requested_model": contract.requested_model,
        "observed_model": contract.observed_model,
        "live_api_triggered": True,
        "artifact_count": len(manifest.artifacts),
        "report_sha256": contract.artifact_sha256["report.html"],
        "production_deploy_eligible": contract.production_deploy_eligible,
    }


def _validate_v5(
    *,
    repo_root: Path,
    contract_document: dict[str, object],
    source_dir: Path,
    snapshot_dir: Path | None = None,
) -> dict[str, object]:
    try:
        return validate_concurrent_robustness_production_release(
            repo_root=repo_root,
            contract_document=contract_document,
            source_dir=source_dir,
            snapshot_dir=snapshot_dir,
        )
    except (ConcurrentRobustnessReleaseError, OSError, ValidationError) as exc:
        raise ReleaseValidationError(f"invalid v5 Concurrent Robustness release: {exc}") from exc


def _validate_v6(
    *,
    repo_root: Path,
    contract_document: dict[str, object],
    source_dir: Path,
    snapshot_dir: Path | None = None,
) -> dict[str, object]:
    try:
        return validate_concurrent_robustness_production_release(
            repo_root=repo_root,
            contract_document=contract_document,
            source_dir=source_dir,
            snapshot_dir=snapshot_dir,
        )
    except (ConcurrentRobustnessReleaseError, OSError, ValidationError) as exc:
        raise ReleaseValidationError(f"invalid v6 Concurrent Robustness release: {exc}") from exc


def _validate_v7(
    *,
    repo_root: Path,
    contract_document: dict[str, object],
    source_dir: Path,
    snapshot_dir: Path | None = None,
) -> dict[str, object]:
    try:
        return validate_concurrent_robustness_production_release(
            repo_root=repo_root,
            contract_document=contract_document,
            source_dir=source_dir,
            snapshot_dir=snapshot_dir,
        )
    except (ConcurrentRobustnessReleaseError, OSError, ValidationError) as exc:
        raise ReleaseValidationError(f"invalid v7 Concurrent Robustness release: {exc}") from exc


def _validate_v8(
    *,
    repo_root: Path,
    contract_document: dict[str, object],
    source_dir: Path,
    snapshot_dir: Path | None = None,
) -> dict[str, object]:
    try:
        return validate_concurrent_robustness_production_release(
            repo_root=repo_root,
            contract_document=contract_document,
            source_dir=source_dir,
            snapshot_dir=snapshot_dir,
        )
    except (ConcurrentRobustnessReleaseError, OSError, ValidationError) as exc:
        raise ReleaseValidationError(f"invalid v8 Full-Pool release: {exc}") from exc


def _validate_v9(
    *,
    repo_root: Path,
    contract_document: dict[str, object],
    source_dir: Path,
    snapshot_dir: Path | None = None,
) -> dict[str, object]:
    try:
        return validate_concurrent_robustness_production_release(
            repo_root=repo_root,
            contract_document=contract_document,
            source_dir=source_dir,
            snapshot_dir=snapshot_dir,
        )
    except (ConcurrentRobustnessReleaseError, OSError, ValidationError) as exc:
        raise ReleaseValidationError(f"invalid v9 segmented Full-Pool release: {exc}") from exc


def _validate_v10(
    *,
    repo_root: Path,
    contract_document: dict[str, object],
    source_dir: Path,
    snapshot_dir: Path | None = None,
) -> dict[str, object]:
    try:
        return validate_concurrent_robustness_production_release(
            repo_root=repo_root,
            contract_document=contract_document,
            source_dir=source_dir,
            snapshot_dir=snapshot_dir,
        )
    except (ConcurrentRobustnessReleaseError, OSError, ValidationError) as exc:
        raise ReleaseValidationError(
            f"invalid v10 automated nested Full-Pool release: {exc}"
        ) from exc


def _validate_v11(
    *,
    repo_root: Path,
    contract_document: dict[str, object],
    source_dir: Path,
    snapshot_dir: Path | None = None,
) -> dict[str, object]:
    try:
        return validate_concurrent_robustness_production_release(
            repo_root=repo_root,
            contract_document=contract_document,
            source_dir=source_dir,
            snapshot_dir=snapshot_dir,
        )
    except (ConcurrentRobustnessReleaseError, OSError, ValidationError) as exc:
        raise ReleaseValidationError(f"invalid v11 strict fresh Full-Pool release: {exc}") from exc


def _validate_v12(
    *,
    repo_root: Path,
    contract_document: dict[str, object],
    source_dir: Path,
    snapshot_dir: Path | None = None,
) -> dict[str, object]:
    try:
        return validate_concurrent_robustness_production_release(
            repo_root=repo_root,
            contract_document=contract_document,
            source_dir=source_dir,
            snapshot_dir=snapshot_dir,
        )
    except (ConcurrentRobustnessReleaseError, OSError, ValidationError) as exc:
        raise ReleaseValidationError(
            f"invalid v12 strict delivery-run Full-Pool release: {exc}"
        ) from exc


def _validate_v13(
    *,
    repo_root: Path,
    contract_document: dict[str, object],
    source_dir: Path,
    snapshot_dir: Path | None = None,
) -> dict[str, object]:
    try:
        return validate_concurrent_robustness_production_release(
            repo_root=repo_root,
            contract_document=contract_document,
            source_dir=source_dir,
            snapshot_dir=snapshot_dir,
        )
    except (ConcurrentRobustnessReleaseError, OSError, ValidationError) as exc:
        raise ReleaseValidationError(
            f"invalid v13 two-stage realized Full-Pool release: {exc}"
        ) from exc


def _load_and_validate_release(
    *,
    repo_root: Path,
    contract_path: Path,
    source_dir: Path,
    snapshot_dir: Path | None = None,
) -> tuple[dict[str, object], Path, dict[str, object]]:
    repo_root = repo_root.resolve()
    contract_file = _regular_contract_file(repo_root, contract_path)
    contract = _load_json(contract_file)
    if not isinstance(contract, dict):
        raise ReleaseValidationError("release contract must be a JSON object")
    schema_version = contract.get("schema_version")
    if schema_version == "abm-report-release-contract-v1":
        result = _validate_v1(repo_root=repo_root, contract=contract, source_dir=source_dir)
    elif schema_version == "abm-report-release-contract-v2":
        _safe_contract_file(repo_root, contract_path)
        result = _validate_v2(
            repo_root=repo_root,
            contract_document=contract,
            source_dir=source_dir,
            snapshot_dir=snapshot_dir,
        )
    elif schema_version == "abm-report-release-contract-v3":
        _safe_contract_file(repo_root, contract_path)
        result = _validate_v3(
            repo_root=repo_root,
            contract_document=contract,
            source_dir=source_dir,
            snapshot_dir=snapshot_dir,
        )
    elif schema_version == "abm-report-release-contract-v4":
        _safe_contract_file(repo_root, contract_path)
        result = _validate_v4(
            repo_root=repo_root,
            contract_document=contract,
            source_dir=source_dir,
            snapshot_dir=snapshot_dir,
        )
    elif schema_version == "abm-report-release-contract-v5":
        _safe_contract_file(repo_root, contract_path)
        result = _validate_v5(
            repo_root=repo_root,
            contract_document=contract,
            source_dir=source_dir,
            snapshot_dir=snapshot_dir,
        )
    elif schema_version == "abm-report-release-contract-v6":
        _safe_contract_file(repo_root, contract_path)
        result = _validate_v6(
            repo_root=repo_root,
            contract_document=contract,
            source_dir=source_dir,
            snapshot_dir=snapshot_dir,
        )
    elif schema_version == "abm-report-release-contract-v7":
        _safe_contract_file(repo_root, contract_path)
        result = _validate_v7(
            repo_root=repo_root,
            contract_document=contract,
            source_dir=source_dir,
            snapshot_dir=snapshot_dir,
        )
    elif schema_version == "abm-report-release-contract-v8":
        _safe_contract_file(repo_root, contract_path)
        result = _validate_v8(
            repo_root=repo_root,
            contract_document=contract,
            source_dir=source_dir,
            snapshot_dir=snapshot_dir,
        )
    elif schema_version == "abm-report-release-contract-v9":
        _safe_contract_file(repo_root, contract_path)
        result = _validate_v9(
            repo_root=repo_root,
            contract_document=contract,
            source_dir=source_dir,
            snapshot_dir=snapshot_dir,
        )
    elif schema_version == "abm-report-release-contract-v10":
        _safe_contract_file(repo_root, contract_path)
        result = _validate_v10(
            repo_root=repo_root,
            contract_document=contract,
            source_dir=source_dir,
            snapshot_dir=snapshot_dir,
        )
    elif schema_version == "abm-report-release-contract-v11":
        _safe_contract_file(repo_root, contract_path)
        result = _validate_v11(
            repo_root=repo_root,
            contract_document=contract,
            source_dir=source_dir,
            snapshot_dir=snapshot_dir,
        )
    elif schema_version == "abm-report-release-contract-v12":
        _safe_contract_file(repo_root, contract_path)
        result = _validate_v12(
            repo_root=repo_root,
            contract_document=contract,
            source_dir=source_dir,
            snapshot_dir=snapshot_dir,
        )
    elif schema_version == ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V13:
        _safe_contract_file(repo_root, contract_path)
        result = _validate_v13(
            repo_root=repo_root,
            contract_document=contract,
            source_dir=source_dir,
            snapshot_dir=snapshot_dir,
        )
    else:
        raise ReleaseValidationError(f"unsupported release contract schema_version: {schema_version!r}")
    return result, contract_file, contract


def validate_release(
    *,
    repo_root: Path,
    contract_path: Path,
    source_dir: Path,
    snapshot_dir: Path | None = None,
) -> dict[str, object]:
    result, _contract_file, _contract = _load_and_validate_release(
        repo_root=repo_root,
        contract_path=contract_path,
        source_dir=source_dir,
        snapshot_dir=snapshot_dir,
    )
    return result


_DEPLOYMENT_REPORT_KINDS = {
    "abm-report-release-contract-v2": "final-research",
    "abm-report-release-contract-v3": "final-research",
    "abm-report-release-contract-v4": "concurrent-message",
    "abm-report-release-contract-v5": "concurrent-robustness",
    "abm-report-release-contract-v6": "concurrent-robustness",
    "abm-report-release-contract-v7": "concurrent-robustness",
    "abm-report-release-contract-v8": "full-pool",
    "abm-report-release-contract-v9": "full-pool",
    "abm-report-release-contract-v10": "full-pool",
    "abm-report-release-contract-v11": "full-pool",
    "abm-report-release-contract-v12": "full-pool",
}
_DEPLOYMENT_RELEASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
_DEPLOYMENT_DOMAIN = re.compile(r"^[A-Za-z0-9.-]+$")
_DEPLOYMENT_ARTIFACT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_DEPLOYMENT_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _build_deployment_facts(
    *,
    contract_path: Path,
    contract: dict[str, object],
    result: dict[str, object],
    evidence_dir: Path,
    deployment_release_id: str,
    deployment_domain: str,
) -> dict[str, object]:
    """Project a validated release into the only facts the Deployment Module may consume."""
    schema_version = contract.get("schema_version")
    report_kind = _DEPLOYMENT_REPORT_KINDS.get(schema_version) if isinstance(schema_version, str) else None
    if report_kind is None or result.get("schema_version") != schema_version:
        raise ReleaseValidationError("deployment facts require a supported validated release schema")
    if not _DEPLOYMENT_RELEASE_ID.fullmatch(deployment_release_id):
        raise ReleaseValidationError("deployment release id is invalid")
    if not _DEPLOYMENT_DOMAIN.fullmatch(deployment_domain):
        raise ReleaseValidationError("deployment domain is invalid")
    frozen_release_id = contract.get("release_id")
    if frozen_release_id is not None and frozen_release_id != deployment_release_id:
        raise ReleaseValidationError("deployment release id differs from the frozen contract")
    if result.get("release_id") is not None and result.get("release_id") != deployment_release_id:
        raise ReleaseValidationError("deployment release id differs from validated release facts")

    endpoint = contract.get("canonical_endpoint")
    if endpoint is None:
        endpoint = f"https://{deployment_domain}/"
    parsed = urlparse(endpoint) if isinstance(endpoint, str) else None
    if (
        parsed is None
        or parsed.scheme != "https"
        or parsed.hostname != deployment_domain
        or parsed.port is not None
        or parsed.path != "/"
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ReleaseValidationError("deployment domain differs from the frozen canonical endpoint")

    raw_hashes = contract.get("artifact_sha256")
    if not isinstance(raw_hashes, dict) or not raw_hashes:
        raise ReleaseValidationError("deployment contract artifact_sha256 must be a non-empty object")
    artifact_hashes: dict[str, str] = {}
    for raw_path, raw_digest in raw_hashes.items():
        if not isinstance(raw_path, str) or not _DEPLOYMENT_ARTIFACT.fullmatch(raw_path):
            raise ReleaseValidationError("deployment artifact path is not canonical and shell-safe")
        path = PurePosixPath(raw_path)
        if path.is_absolute() or "." in path.parts or ".." in path.parts or path.as_posix() != raw_path:
            raise ReleaseValidationError("deployment artifact path escapes the release inventory")
        if not isinstance(raw_digest, str) or not _DEPLOYMENT_SHA256.fullmatch(raw_digest):
            raise ReleaseValidationError(f"deployment artifact SHA-256 is invalid: {raw_path}")
        artifact_hashes[raw_path] = raw_digest
    for required in ("report.html", "artifact_manifest.json"):
        if required not in artifact_hashes:
            raise ReleaseValidationError(f"deployment contract is missing {required}")
        target = evidence_dir / required
        if target.is_symlink() or not target.is_file() or _sha256(target) != artifact_hashes[required]:
            raise ReleaseValidationError(f"validated deployment snapshot changed at {required}")
    if result.get("report_sha256") != artifact_hashes["report.html"]:
        raise ReleaseValidationError("validated report hash differs from the deployment contract")

    manifest = _load_json(evidence_dir / "artifact_manifest.json")
    if not isinstance(manifest, dict):
        raise ReleaseValidationError("deployment artifact manifest must be a JSON object")
    approved_value = manifest.get("approved_downloads", {})
    if isinstance(approved_value, dict):
        approved_downloads = list(approved_value.values())
    elif isinstance(approved_value, list):
        approved_downloads = approved_value
    else:
        raise ReleaseValidationError("deployment approved downloads must be a mapping or list")
    if any(not isinstance(path, str) or path not in artifact_hashes for path in approved_downloads):
        raise ReleaseValidationError("deployment approved download is absent from the contract inventory")
    if len(set(approved_downloads)) != len(approved_downloads):
        raise ReleaseValidationError("deployment approved downloads are not one-to-one")

    release_identity = manifest.get("release_identity_sha256", "")
    if schema_version in {
        "abm-report-release-contract-v5",
        "abm-report-release-contract-v6",
        "abm-report-release-contract-v7",
        "abm-report-release-contract-v8",
        "abm-report-release-contract-v9",
        "abm-report-release-contract-v10",
        "abm-report-release-contract-v11",
        "abm-report-release-contract-v12",
    }:
        if manifest.get("release_id") != deployment_release_id:
            raise ReleaseValidationError("deployment manifest release id is crossed")
        if not isinstance(release_identity, str) or not _DEPLOYMENT_SHA256.fullmatch(release_identity):
            raise ReleaseValidationError("deployment manifest release identity is invalid")
    elif not isinstance(release_identity, str):
        release_identity = ""

    return {
        "schema_version": "abm-report-deployment-facts-v1",
        "release_contract_schema_version": schema_version,
        "report_kind": report_kind,
        "release_id": deployment_release_id,
        "canonical_endpoint": endpoint,
        "canonical_domain": deployment_domain,
        "contract_sha256": _sha256(contract_path),
        "release_identity_sha256": release_identity,
        "report_sha256": artifact_hashes["report.html"],
        "manifest_sha256": artifact_hashes["artifact_manifest.json"],
        "artifact_sha256": dict(sorted(artifact_hashes.items())),
        "approved_downloads": sorted(approved_downloads),
        "public_acceptance_artifacts": sorted(artifact_hashes),
    }


def _require_formal_production(result: dict[str, object]) -> None:
    schema_version = result.get("schema_version")
    if schema_version in {
        "abm-report-release-contract-v8",
        "abm-report-release-contract-v9",
        "abm-report-release-contract-v10",
        "abm-report-release-contract-v11",
        "abm-report-release-contract-v12",
    }:
        expected_purpose = {
            "abm-report-release-contract-v8": "full_pool_formal_research",
            "abm-report-release-contract-v9": "full_pool_segmented_formal_research",
            "abm-report-release-contract-v10": "full_pool_automated_nested_formal_research",
            "abm-report-release-contract-v11": "full_pool_strict_fresh_formal_research",
            "abm-report-release-contract-v12": "full_pool_strict_fresh_formal_research",
        }[str(schema_version)]
        expected_status = {
            "abm-report-release-contract-v8": "persisted_full_pool_formal_run",
            "abm-report-release-contract-v9": "persisted_full_pool_segmented_formal_run",
            "abm-report-release-contract-v10": (
                "persisted_full_pool_automated_nested_formal_run"
            ),
            "abm-report-release-contract-v11": (
                "persisted_strict_fresh_full_pool_formal_run"
            ),
            "abm-report-release-contract-v12": (
                "persisted_strict_fresh_full_pool_formal_run"
            ),
        }[str(schema_version)]
        schema_profile_valid = (
            result.get("release_purpose") == expected_purpose
            and result.get("sampling_status") == expected_status
            and result.get("live_api_triggered") is True
        )
    else:
        schema_profile_valid = (
            schema_version
            in {
                "abm-report-release-contract-v2",
                "abm-report-release-contract-v3",
                "abm-report-release-contract-v4",
                "abm-report-release-contract-v5",
                "abm-report-release-contract-v6",
                "abm-report-release-contract-v7",
            }
            and result.get("release_purpose")
            in {"formal_research", "concurrent_robustness_formal_research"}
            and result.get("sampling_status") == "persisted_seed_first_formal_run"
        )
    if (
        not schema_profile_valid
        or result.get("decision_execution_mode") != "live_provider"
        or result.get("production_deploy_eligible") is not True
    ):
        raise ReleaseValidationError(
            "formal production deployment requires abm-report-release-contract-v2 through v12 "
            "with matching deploy-eligible persisted live-provider Formal research evidence"
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate an approved persisted ABM report release")
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        help="Validate and deploy bytes from this local snapshot while preserving contract source identity",
    )
    parser.add_argument(
        "--require-formal-production",
        action="store_true",
        help="Reject validated evidence unless it is a deploy-eligible v2-v12 Formal research release",
    )
    parser.add_argument(
        "--deployment-facts-output",
        type=Path,
        help="Write validated, deployment-only facts for deploy_abm_report.sh",
    )
    parser.add_argument("--deployment-release-id")
    parser.add_argument("--deployment-domain")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        result, contract_file, contract = _load_and_validate_release(
            repo_root=args.repo_root,
            contract_path=args.contract,
            source_dir=args.source_dir,
            snapshot_dir=args.snapshot_dir,
        )
        if args.require_formal_production:
            _require_formal_production(result)
        if args.deployment_facts_output is not None:
            if (
                not args.require_formal_production
                or args.deployment_release_id is None
                or args.deployment_domain is None
            ):
                raise ReleaseValidationError(
                    "deployment facts require --require-formal-production, --deployment-release-id, and --deployment-domain"
                )
            facts = _build_deployment_facts(
                contract_path=contract_file,
                contract=contract,
                result=result,
                evidence_dir=args.snapshot_dir or args.source_dir,
                deployment_release_id=args.deployment_release_id,
                deployment_domain=args.deployment_domain,
            )
            output = args.deployment_facts_output
            if output.is_symlink() or (output.exists() and not output.is_file()):
                raise ReleaseValidationError("deployment facts output must be a regular non-symlink file")
            output.write_text(
                json.dumps(facts, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
    except ReleaseValidationError as exc:
        print(f"release validation error: {exc}", file=sys.stderr)
        return 1
    mode = result.get("decision_execution_mode", "historical_validation")
    print(
        "Release evidence validated: "
        f"{result['schema_version']} | {result['release_purpose']} | {result['source_directory']} | "
        f"{result['sampling_method']} | {result['sampling_status']} | {mode} | "
        f"report SHA-256 {result['report_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
