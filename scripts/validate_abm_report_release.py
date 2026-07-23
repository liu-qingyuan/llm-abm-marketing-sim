#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

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
        if accounting.observed_model_counts != {self.requested_model: accounting.provider_response_count}:
            raise ValueError("observed_model_counts must report only the exact requested model for every response")
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
    if accounting.observed_model_counts != {contract.requested_model: accounting.provider_response_count}:
        raise ReleaseValidationError("v3 observed models do not match the exact requested model")
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
        "live_api_triggered": contract.live_api_triggered,
        "artifact_count": len(artifacts),
        "report_sha256": contract.artifact_sha256["report.html"],
        "production_deploy_eligible": contract.production_deploy_eligible,
    }


def validate_release(
    *,
    repo_root: Path,
    contract_path: Path,
    source_dir: Path,
    snapshot_dir: Path | None = None,
) -> dict[str, object]:
    repo_root = repo_root.resolve()
    contract_file = _regular_contract_file(repo_root, contract_path)
    contract = _load_json(contract_file)
    if not isinstance(contract, dict):
        raise ReleaseValidationError("release contract must be a JSON object")
    schema_version = contract.get("schema_version")
    if schema_version == "abm-report-release-contract-v1":
        return _validate_v1(repo_root=repo_root, contract=contract, source_dir=source_dir)
    if schema_version == "abm-report-release-contract-v2":
        _safe_contract_file(repo_root, contract_path)
        return _validate_v2(
            repo_root=repo_root,
            contract_document=contract,
            source_dir=source_dir,
            snapshot_dir=snapshot_dir,
        )
    if schema_version == "abm-report-release-contract-v3":
        _safe_contract_file(repo_root, contract_path)
        return _validate_v3(
            repo_root=repo_root,
            contract_document=contract,
            source_dir=source_dir,
            snapshot_dir=snapshot_dir,
        )
    raise ReleaseValidationError(f"unsupported release contract schema_version: {schema_version!r}")


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
        help="Reject validated evidence unless it is a deploy-eligible v2 or v3 formal research release",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        result = validate_release(
            repo_root=args.repo_root,
            contract_path=args.contract,
            source_dir=args.source_dir,
            snapshot_dir=args.snapshot_dir,
        )
        if args.require_formal_production and (
            result.get("schema_version") not in {"abm-report-release-contract-v2", "abm-report-release-contract-v3"}
            or result.get("release_purpose") != "formal_research"
            or result.get("production_deploy_eligible") is not True
        ):
            raise ReleaseValidationError(
                "formal production deployment requires abm-report-release-contract-v2 or "
                "abm-report-release-contract-v3 formal_research evidence"
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
