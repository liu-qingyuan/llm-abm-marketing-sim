from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .concurrent_message_mechanism_presentation import _MECHANISM_PRESENTATION
from .concurrent_message_report import CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON
from .concurrent_robustness_report import _REPORT_PRESENTATION, _FullPoolCandidateFacts
from .concurrent_robustness_study import (
    ConcurrentRobustnessManifest,
    _CellEvidenceDocument,
    _dynamic_root,
    _validate_cell_evidence_contract,
    _validate_completed_dynamic_root,
)
from .providers.pi_subscription import PI_SUBSCRIPTION_MODEL_ALIASES

FORMAL_LOGICAL_JUDGMENTS = 28_800
FORMAL_PHYSICAL_ATTEMPT_CAP = 86_400
PRESENTATION_CLOSURE_SCHEMA = "concurrent-robustness-presentation-closure-contract-v1"
PRESENTATION_CLOSURE_V2_SCHEMA = "concurrent-robustness-presentation-closure-contract-v2"
FULL_POOL_PRESENTATION_CLOSURE_SCHEMA = "full-pool-three-lineage-presentation-closure-v1"
_REPORT_PAYLOAD_V1_SCHEMA = "concurrent-robustness-report-payload-v1"
_REPORT_PAYLOAD_V2_SCHEMA = "concurrent-robustness-report-payload-v2"
_REPORT_PAYLOAD_V1_FIELDS = frozenset(
    {
        "schema_version",
        "title",
        "source_lineage",
        "ranking_weight",
        "prompt_model",
        "row_counts",
        "trace_row_count",
        "downloads",
        "claim_boundary",
        "production_deploy_eligible",
    }
)
_REPORT_PAYLOAD_V1_LEGACY_FIELDS = _REPORT_PAYLOAD_V1_FIELDS - {"trace_row_count"}
_REPORT_PAYLOAD_V2_FIELDS = _REPORT_PAYLOAD_V1_FIELDS | {"mechanism_presentation"}
_MECHANISM_PRESENTATION_FIELDS = frozenset(
    {"schema_version", "semantic_set_identity_sha256", "masters"}
)
_SEMANTIC_MERMAID_DOWNLOADS = {
    "mechanism_sample_first_mermaid": "mechanism-sample-first.mmd",
    "mechanism_pair_formation_mermaid": "mechanism-pair-formation.mmd",
    "mechanism_independent_delivery_mermaid": "mechanism-independent-delivery.mmd",
    "mechanism_exposure_decisions_mermaid": "mechanism-exposure-decisions.mmd",
    "mechanism_feedback_boundary_mermaid": "mechanism-feedback-boundary.mmd",
    "real_batch_mechanism_mermaid": "real-batch-mechanism.mmd",
    "prompt_model_factorial_mermaid": "prompt-model-factorial.mmd",
}
_CANDIDATE_EVIDENCE = "release_evidence.json"
_CANDIDATE_REPORT = "report.html"
_CANDIDATE_PAYLOAD = "concurrent_robustness_report_payload.json"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{7,40}$")


class ConcurrentRobustnessEvidenceError(ValueError):
    """Raised when persisted robustness evidence cannot be independently closed."""


@dataclass(frozen=True)
class FormalExecutionFacts:
    implementation_commit: str
    closure_implementation_commit: str
    closure_replay_path: Path
    closure_replay_sha256: str
    physical_provider_attempts: int
    subscription_nominal_reference_cost_usd: float
    subscription_billed_cost_usd: float


@dataclass(frozen=True)
class CandidateLineageFacts:
    path: Path
    manifest_sha256: str
    candidate_identity_sha256: str
    content_identity_sha256: str
    report_sha256: str
    payload_sha256: str
    evidence_sha256: str


@dataclass(frozen=True)
class FullPoolPresentationClosureFacts:
    closure_path: Path
    closure_sha256: str
    closure_schema_version: str
    implementation_commit: str
    full_pool_source_path: Path
    full_pool_source_schema_version: str
    full_pool_source_identity: str
    full_pool_source_manifest_sha256: str
    full_pool_source_hash: str
    historical_formal_path: Path
    historical_formal_source_id: str
    historical_formal_manifest_schema_version: str
    historical_formal_manifest_sha256: str
    robustness_study_path: Path
    robustness_study_manifest_schema_version: str
    robustness_study_manifest_sha256: str
    robustness_study_artifact_manifest_sha256: str
    robustness_study_root_identity_sha256: str
    presentation_bundle_path: Path
    presentation_bundle_identity_sha256: str
    candidate_path: Path
    candidate_manifest_sha256: str
    candidate_identity_sha256: str
    candidate_content_identity_sha256: str
    candidate_report_sha256: str
    candidate_payload_sha256: str
    candidate_evidence_sha256: str
    report_payload_schema_version: str
    source_lineage_identity_sha256: str
    presentation_inventory_identity_sha256: str
    mechanism_set_identity_sha256: str
    trace_index_sha256: str
    provider_calls_during_closure: int
    image_generation_triggered: bool
    production_deploy_eligible: bool


@dataclass(frozen=True)
class PresentationClosureFacts:
    closure_path: Path
    closure_sha256: str
    closure_schema_version: str
    implementation_commit: str
    formal_execution_contract_path: Path
    formal_execution_contract_sha256: str
    immutable_replay_path: Path
    immutable_replay_sha256: str
    old_candidate_path: Path
    old_candidate_manifest_sha256: str
    old_candidate_identity_sha256: str
    new_candidate_path: Path
    new_candidate_manifest_sha256: str
    new_candidate_identity_sha256: str
    new_candidate_report_sha256: str
    new_candidate_payload_sha256: str
    new_candidate_evidence_sha256: str
    new_candidate_content_identity_sha256: str
    formal_judgment_implementation_commit: str
    formal_closure_implementation_commit: str
    logical_judgments: int
    physical_attempts: int
    subscription_nominal_reference_cost_usd: float
    provider_calls_during_closure: int
    image_generation_triggered: bool
    report_payload_schema_version: str
    semantic_set_identity_sha256: str | None


def close_formal_cell_evidence(
    *,
    study: Path,
    workspace: Path,
    formal: Path,
    manifest: ConcurrentRobustnessManifest,
    manifest_sha256: str,
    evidence_model: Any = _CellEvidenceDocument,
    cell_validator: Any = _validate_cell_evidence_contract,
    dynamic_validator: Any = _validate_completed_dynamic_root,
) -> Any:
    """Close the Formal cell matrix; validators are injectable for Release seams."""
    try:
        evidence = evidence_model.model_validate(_json_object(study / "prompt_model_cell_evidence.json"))
        cell_validator(evidence, manifest=manifest, manifest_sha256=manifest_sha256)
        dynamic_validator(
            manifest=manifest,
            manifest_sha256=manifest_sha256,
            output_path=workspace,
            source_path=formal,
            evidence=evidence,
        )
        return evidence
    except (OSError, TypeError, ValueError) as exc:
        raise ConcurrentRobustnessEvidenceError(
            "Formal cell rows or durable journals failed independent closure"
        ) from exc


_close_formal_cell_evidence = close_formal_cell_evidence


def _validate_parallel_cell_execution(
    *,
    root: Path,
    document: Mapping[str, Any],
    manifest: ConcurrentRobustnessManifest,
    manifest_sha256: str,
    workspace: Path,
    physical_attempts: int,
) -> None:
    required = {
        "parallel_cell_worker_commit",
        "parallel_cell_worker_artifact",
        "parallel_cell_worker_sha256",
        "parallel_cell_indices",
        "parallel_cell_strategy",
        "main_process_subscription_nominal_reference_cost_usd",
        "parallel_worker_subscription_nominal_reference_cost_usd",
        "main_process_physical_attempts",
        "parallel_worker_physical_attempts",
        "parallel_worker_completion_sha256",
    }
    if not required.issubset(document):
        raise ConcurrentRobustnessEvidenceError("parallel Formal execution evidence is incomplete")
    if (
        not _COMMIT.fullmatch(_string(document.get("parallel_cell_worker_commit"), "parallel cell worker commit"))
        or document.get("parallel_cell_indices") != list(range(1, 16))
        or document.get("parallel_cell_strategy") != "disjoint-final-journals-main-study-replay-v1"
    ):
        raise ConcurrentRobustnessEvidenceError("parallel Formal execution identity is crossed")
    worker_sha256 = _string(document.get("parallel_cell_worker_sha256"), "parallel cell worker SHA-256")
    if not _SHA256.fullmatch(worker_sha256):
        raise ConcurrentRobustnessEvidenceError("parallel cell worker SHA-256 is invalid")
    worker_artifact = _repo_file(
        root,
        Path(_string(document.get("parallel_cell_worker_artifact"), "parallel cell worker artifact")),
        "parallel cell worker artifact",
    )
    if _sha256_file(worker_artifact) != worker_sha256:
        raise ConcurrentRobustnessEvidenceError("parallel cell worker artifact hash is crossed")
    main_nominal = document.get("main_process_subscription_nominal_reference_cost_usd")
    aggregate_nominal = document.get("subscription_nominal_reference_cost_usd")
    if (
        isinstance(main_nominal, bool)
        or not isinstance(main_nominal, (int, float))
        or float(main_nominal) < 0.0
        or isinstance(aggregate_nominal, bool)
        or not isinstance(aggregate_nominal, (int, float))
        or float(aggregate_nominal) < 0.0
    ):
        raise ConcurrentRobustnessEvidenceError("parallel subscription nominal reference cost is invalid")
    worker_nominal = 0.0
    worker_physical = 0
    completion_hashes = _string_mapping(
        document.get("parallel_worker_completion_sha256"),
        "parallel worker completion hashes",
    )
    if set(completion_hashes) != {f"cell-{index:02d}" for index in range(1, 16)}:
        raise ConcurrentRobustnessEvidenceError("parallel worker completion hash inventory is incomplete")
    dynamic_root = _dynamic_root(workspace)
    for cell_index in range(1, 16):
        cell = manifest.prompt_model_cells[cell_index]
        completion_path = dynamic_root / f"cell-{cell_index:02d}" / "cell_worker_completion.json"
        completion = _json_object(completion_path)
        if completion_hashes[f"cell-{cell_index:02d}"] != _sha256_file(completion_path):
            raise ConcurrentRobustnessEvidenceError(f"parallel cell {cell_index} completion hash is crossed")
        completion_physical = _strict_int(
            completion.get("physical_attempts"),
            f"parallel cell {cell_index} physical attempts",
        )
        nominal = completion.get("subscription_nominal_reference_cost_usd")
        expected_workspace = (dynamic_root / f"cell-{cell_index:02d}" / ".primary-only.operational").resolve(
            strict=True
        )
        if (
            completion.get("schema_version") != "concurrent-robustness-formal-cell-worker-completion-v1"
            or completion.get("manifest_sha256") != manifest_sha256
            or completion.get("cell_index") != cell_index
            or completion.get("cell_id") != cell.cell_id
            or completion.get("requested_model") != cell.requested_model
            or completion.get("observed_model") != cell.required_observed_model
            or completion.get("logical_judgments") != manifest.request_caps.logical_judgments_per_cell
            or not manifest.request_caps.logical_judgments_per_cell
            <= completion_physical
            <= manifest.request_caps.logical_judgments_per_cell * (manifest.request_contract.max_retries + 1)
            or isinstance(nominal, bool)
            or not isinstance(nominal, (int, float))
            or float(nominal) < 0.0
            or completion.get("subscription_billed_cost_usd") != 0.0
            or Path(_string(completion.get("journal_workspace"), "parallel journal workspace")).resolve(strict=True)
            != expected_workspace
            or completion.get("production_deploy_eligible") is not False
        ):
            raise ConcurrentRobustnessEvidenceError(f"parallel cell {cell_index} completion evidence is crossed")
        worker_physical += completion_physical
        worker_nominal += float(nominal)
    main_physical = physical_attempts - worker_physical
    per_cell_logical = manifest.request_caps.logical_judgments_per_cell
    if (
        not per_cell_logical <= main_physical <= per_cell_logical * (manifest.request_contract.max_retries + 1)
        or document.get("main_process_physical_attempts") != main_physical
        or document.get("parallel_worker_physical_attempts") != worker_physical
    ):
        raise ConcurrentRobustnessEvidenceError("main/worker physical accounting is crossed")
    recorded_worker_nominal = document.get("parallel_worker_subscription_nominal_reference_cost_usd")
    if (
        isinstance(recorded_worker_nominal, bool)
        or not isinstance(recorded_worker_nominal, (int, float))
        or not math.isclose(float(recorded_worker_nominal), worker_nominal, rel_tol=0.0, abs_tol=1e-12)
        or not math.isclose(
            float(aggregate_nominal),
            float(main_nominal) + worker_nominal,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    ):
        raise ConcurrentRobustnessEvidenceError("parallel nominal reference cost does not close")


def _validate_execution_contract(
    *,
    root: Path,
    path: Path,
    formal: Path,
    study: Path,
    workspace: Path,
    candidate: Path,
    manifest: ConcurrentRobustnessManifest,
    manifest_sha256: str,
) -> dict[str, Any]:
    document = _json_object(path)
    required = {
        "schema_version",
        "output_identity",
        "source_dir",
        "workspace",
        "study_root",
        "report_candidate",
        "study_manifest_sha256",
        "qualification_artifact",
        "authorization_artifact",
        "pricing_artifact",
        "provider_calls_authorized",
        "canonical_deployment_authorized_after_validation",
        "implementation_commit",
        "formal_runner_artifact",
        "formal_runner_sha256",
        "subscription_worker_artifact",
        "subscription_worker_sha256",
        "subscription_client_artifact",
        "subscription_client_sha256",
        "completion_status",
        "logical_provider_attempts",
        "physical_provider_attempts",
        "closure_implementation_commit",
        "closure_replay_artifact",
        "closure_replay_sha256",
        "closure_study_module_artifact",
        "closure_study_module_sha256",
        "closure_report_module_artifact",
        "closure_report_module_sha256",
        "closure_provider_requests",
        "closure_subscription_billed_cost_usd",
        "study_artifact_manifest_sha256",
        "report_candidate_manifest_sha256",
        "subscription_nominal_reference_cost_usd",
        "subscription_billed_cost_usd",
        "subscription_billing_evidence",
    }
    if not required.issubset(document):
        raise ConcurrentRobustnessEvidenceError("Formal execution contract is incomplete")
    if (
        document.get("schema_version") != "concurrent-robustness-formal-run-contract-v1"
        or document.get("output_identity") != manifest.output_identity
        or Path(_string(document.get("source_dir"), "Formal source path")).resolve(strict=True) != formal
        or Path(_string(document.get("workspace"), "workspace path")).resolve(strict=True) != workspace
        or Path(_string(document.get("study_root"), "study root path")).resolve(strict=True) != study
        or Path(_string(document.get("report_candidate"), "candidate path")).resolve(strict=True) != candidate
        or document.get("study_manifest_sha256") != manifest_sha256
        or document.get("provider_calls_authorized") is not True
        or document.get("canonical_deployment_authorized_after_validation") is not True
        or document.get("completion_status") != "complete"
        or document.get("logical_provider_attempts") != FORMAL_LOGICAL_JUDGMENTS
        or document.get("closure_provider_requests") != 0
        or document.get("closure_subscription_billed_cost_usd") != 0.0
        or document.get("subscription_billed_cost_usd") != 0.0
        or document.get("subscription_billing_evidence") != "openai-codex OAuth subscription transport"
        or isinstance(document.get("subscription_nominal_reference_cost_usd"), bool)
        or not isinstance(document.get("subscription_nominal_reference_cost_usd"), (int, float))
        or float(document["subscription_nominal_reference_cost_usd"]) < 0.0
        or not _COMMIT.fullmatch(_string(document.get("implementation_commit"), "implementation commit"))
    ):
        raise ConcurrentRobustnessEvidenceError("Formal execution contract is crossed or incomplete")
    physical_attempts = _strict_int(document.get("physical_provider_attempts"), "physical provider attempts")
    if not FORMAL_LOGICAL_JUDGMENTS <= physical_attempts <= FORMAL_PHYSICAL_ATTEMPT_CAP:
        raise ConcurrentRobustnessEvidenceError("Formal execution physical attempts exceed the approved contract")
    implementation_artifacts = {
        "formal_runner_sha256": "formal_runner_artifact",
        "subscription_worker_sha256": "subscription_worker_artifact",
        "subscription_client_sha256": "subscription_client_artifact",
        "closure_study_module_sha256": "closure_study_module_artifact",
        "closure_report_module_sha256": "closure_report_module_artifact",
    }
    for hash_key, path_key in implementation_artifacts.items():
        expected_hash = _string(document.get(hash_key), hash_key)
        if not _SHA256.fullmatch(expected_hash):
            raise ConcurrentRobustnessEvidenceError(f"Formal execution {hash_key} is invalid")
        artifact = _repo_file(
            root,
            Path(_string(document.get(path_key), path_key)),
            f"Formal implementation artifact {path_key}",
        )
        if _sha256_file(artifact) != expected_hash:
            raise ConcurrentRobustnessEvidenceError(f"Formal implementation artifact is crossed: {path_key}")

    closure_commit = _string(document.get("closure_implementation_commit"), "closure implementation commit")
    if not _COMMIT.fullmatch(closure_commit):
        raise ConcurrentRobustnessEvidenceError("closure implementation commit is invalid")
    closure_replay = _repo_file(
        root,
        Path(_string(document.get("closure_replay_artifact"), "closure replay artifact")),
        "closure replay artifact",
    )
    closure_replay_sha256 = _string(document.get("closure_replay_sha256"), "closure replay SHA-256")
    closure_document = _json_object(closure_replay)
    if (
        not _SHA256.fullmatch(closure_replay_sha256)
        or _sha256_file(closure_replay) != closure_replay_sha256
        or closure_document.get("schema_version") != "concurrent-robustness-formal-closure-replay-v1"
        or closure_document.get("closure_implementation_commit") != closure_commit
        or closure_document.get("status") != "complete"
        or closure_document.get("manifest_sha256") != manifest_sha256
        or closure_document.get("logical_provider_attempts") != FORMAL_LOGICAL_JUDGMENTS
        or closure_document.get("physical_provider_attempts") != physical_attempts
        or closure_document.get("provider_requests_during_closure_replay") != 0
        or closure_document.get("subscription_billed_cost_usd_during_closure") != 0.0
        or Path(_string(closure_document.get("workspace"), "closure workspace")).resolve(strict=True) != workspace
        or Path(_string(closure_document.get("study_root"), "closure study root")).resolve(strict=True) != study
        or Path(_string(closure_document.get("report_candidate"), "closure report candidate")).resolve(strict=True)
        != candidate
        or document.get("study_artifact_manifest_sha256") != _sha256_file(study / "artifact_manifest.json")
        or document.get("report_candidate_manifest_sha256")
        != _sha256_file(candidate / CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON)
    ):
        raise ConcurrentRobustnessEvidenceError("zero-call Formal closure replay evidence is crossed")

    if document.get("parallel_cell_execution_used") is True:
        _validate_parallel_cell_execution(
            root=root,
            document=document,
            manifest=manifest,
            manifest_sha256=manifest_sha256,
            workspace=workspace,
            physical_attempts=physical_attempts,
        )
    elif any(str(key).startswith("parallel_cell_") for key in document):
        raise ConcurrentRobustnessEvidenceError("parallel cell evidence is present without an explicit execution flag")

    qualification = _repo_file(
        root,
        Path(_string(document.get("qualification_artifact"), "qualification artifact")),
        "qualification artifact",
    )
    authorization = _repo_file(
        root,
        Path(_string(document.get("authorization_artifact"), "authorization artifact")),
        "authorization artifact",
    )
    pricing = _repo_file(
        root,
        Path(_string(document.get("pricing_artifact"), "pricing artifact")),
        "pricing artifact",
    )
    qualification_document = _json_object(qualification)
    rows = qualification_document.get("rows")
    if (
        qualification_document.get("schema_version") != "concurrent-robustness-subscription-qualification-v1"
        or qualification_document.get("provider_transport") != "openai-codex"
        or qualification_document.get("subscription_billing") is not True
        or qualification_document.get("model_count") != 4
        or not isinstance(rows, list)
        or len(rows) != 4
    ):
        raise ConcurrentRobustnessEvidenceError("model qualification artifact header is invalid")
    row_by_model: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            raise ConcurrentRobustnessEvidenceError("model qualification row is invalid")
        row = dict(raw)
        recorded = row.pop("evidence_sha256", None)
        if recorded != _sha256_bytes(_json_bytes(row)):
            raise ConcurrentRobustnessEvidenceError("model qualification row hash is crossed")
        requested = _string(raw.get("requested_model"), "qualified requested model")
        if (
            requested in row_by_model
            or raw.get("provider_transport") != "openai-codex"
            or raw.get("authentication") != "local_oauth_subscription"
            or raw.get("observed_model") != PI_SUBSCRIPTION_MODEL_ALIASES.get(requested)
            or raw.get("status") != "qualified"
            or raw.get("structured_decision_valid") is not True
            or raw.get("usage_status") != "complete"
        ):
            raise ConcurrentRobustnessEvidenceError("model qualification row contract is crossed")
        row_by_model[requested] = raw
    if row_by_model.keys() != PI_SUBSCRIPTION_MODEL_ALIASES.keys():
        raise ConcurrentRobustnessEvidenceError("qualification does not cover the exact four requested models")
    execution = manifest.dynamic_execution
    assert execution is not None
    for record in execution.qualifications:
        qualification_row = row_by_model.get(record.requested_model)
        if (
            qualification_row is None
            or record.artifact_sha256 != qualification_row.get("evidence_sha256")
            or record.required_observed_model != qualification_row.get("observed_model")
            or record.artifact_reference != f"{qualification.resolve()}#{record.requested_model}"
        ):
            raise ConcurrentRobustnessEvidenceError("manifest qualification reference is crossed")

    authorization_document = _json_object(authorization)
    authorization_evidence = dict(authorization_document)
    authorization_sha256 = authorization_evidence.pop("evidence_sha256", None)
    if (
        authorization_sha256 != _sha256_bytes(_json_bytes(authorization_evidence))
        or authorization_sha256 != execution.authorization.artifact_sha256
        or authorization_document.get("provider_transport") != "openai-codex"
        or authorization_document.get("subscription_billing") is not True
        or authorization_document.get("logical_judgment_cap") != FORMAL_LOGICAL_JUDGMENTS
        or authorization_document.get("physical_attempt_cap") != FORMAL_PHYSICAL_ATTEMPT_CAP
        or authorization_document.get("fee_ceiling_usd") != 0.0
        or authorization_document.get("external_requests_allowed") is not True
    ):
        raise ConcurrentRobustnessEvidenceError("execution authorization artifact is crossed")
    pricing_document = _json_object(pricing)
    pricing_evidence = dict(pricing_document)
    pricing_sha256 = pricing_evidence.pop("evidence_sha256", None)
    model_pricing = pricing_document.get("model_pricing")
    if (
        pricing_sha256 != _sha256_bytes(_json_bytes(pricing_evidence))
        or pricing_sha256 != execution.pricing_snapshot.snapshot_sha256
        or pricing_document.get("provider_transport") != "openai-codex"
        or pricing_document.get("billing_mode") != "subscription"
        or not isinstance(model_pricing, list)
        or len(model_pricing) != 4
        or {row.get("requested_model") for row in model_pricing if isinstance(row, dict)}
        != set(PI_SUBSCRIPTION_MODEL_ALIASES)
        or any(
            not isinstance(row, dict)
            or row.get("input_usd_per_million_tokens") != 0.0
            or row.get("output_usd_per_million_tokens") != 0.0
            for row in model_pricing
        )
    ):
        raise ConcurrentRobustnessEvidenceError("subscription pricing artifact is crossed")
    return document


def _validate_report_payload_contract(
    payload: Mapping[str, Any],
    *,
    candidate: Path,
    production: bool = False,
) -> tuple[str, str | None]:
    schema = payload.get("schema_version")
    production_fields = {"production_release"} if production else set()
    if schema == _REPORT_PAYLOAD_V1_SCHEMA:
        payload_fields = set(payload)
        if payload_fields not in {
            _REPORT_PAYLOAD_V1_FIELDS | production_fields,
            _REPORT_PAYLOAD_V1_LEGACY_FIELDS | production_fields,
        }:
            raise ConcurrentRobustnessEvidenceError("payload v1 fields are missing or unexpected")
        return _REPORT_PAYLOAD_V1_SCHEMA, None
    if (
        schema != _REPORT_PAYLOAD_V2_SCHEMA
        or set(payload) != _REPORT_PAYLOAD_V2_FIELDS | production_fields
    ):
        raise ConcurrentRobustnessEvidenceError("report payload schema or fields are unsupported")
    facts = payload.get("mechanism_presentation")
    if not isinstance(facts, Mapping) or set(facts) != _MECHANISM_PRESENTATION_FIELDS:
        raise ConcurrentRobustnessEvidenceError("mechanism presentation fields are missing or unexpected")
    mechanism = _MECHANISM_PRESENTATION.build()
    expected_masters = {
        artifact.filename: artifact.sha256
        for artifact in mechanism.mermaid_artifacts
    }
    masters = _string_mapping(facts.get("masters"), "mechanism presentation masters")
    semantic_identity = _string(
        facts.get("semantic_set_identity_sha256"),
        "mechanism semantic set identity",
    )
    if (
        facts.get("schema_version") != mechanism.schema_version
        or semantic_identity != mechanism.semantic_set_identity_sha256
        or masters != expected_masters
    ):
        raise ConcurrentRobustnessEvidenceError("mechanism presentation identity is crossed")
    downloads = _string_mapping(payload.get("downloads"), "candidate report downloads")
    if any(downloads.get(key) != value for key, value in _SEMANTIC_MERMAID_DOWNLOADS.items()):
        raise ConcurrentRobustnessEvidenceError("payload v2 Mermaid downloads are incomplete or crossed")
    if "project_evidence_chain_mermaid" in downloads or "batch_mechanism_mermaid" in downloads:
        raise ConcurrentRobustnessEvidenceError("payload v2 retained a compatibility Mermaid mapping")
    if any(
        value == "mechanism-image-generation-audit.json"
        or value.endswith("-v4.png")
        or value.endswith("-v4.webp")
        for value in downloads.values()
    ):
        raise ConcurrentRobustnessEvidenceError("payload v2 contains a rejected presentation download")
    for filename, expected_sha256 in expected_masters.items():
        target = candidate / filename
        if target.is_symlink() or not target.is_file() or _sha256_file(target) != expected_sha256:
            raise ConcurrentRobustnessEvidenceError("mechanism presentation master bytes are crossed")
    return _REPORT_PAYLOAD_V2_SCHEMA, semantic_identity


def _validate_candidate_release_contract(
    *,
    candidate: Path,
    candidate_manifest: Mapping[str, Any],
    candidate_evidence: Mapping[str, Any],
    candidate_report_payload: Mapping[str, Any],
    manifest: ConcurrentRobustnessManifest,
    manifest_sha256: str,
    formal: Path,
    study: Path,
) -> None:
    candidate_hashes = _flat_file_hashes(candidate)
    artifacts = _string_mapping(candidate_manifest.get("artifacts"), "candidate artifacts")
    declared_hashes = _string_mapping(candidate_manifest.get("sha256"), "candidate artifact hashes")
    report_schema, _ = _validate_report_payload_contract(
        candidate_report_payload,
        candidate=candidate,
    )
    if (
        candidate_manifest.get("schema_version") != "concurrent-robustness-report-candidate-manifest-v1"
        or candidate_manifest.get("candidate_type") != "immutable_combined_robustness_report"
        or candidate_manifest.get("production_deploy_eligible") is not False
        or candidate_evidence.get("schema_version") != "concurrent-robustness-report-release-evidence-v1"
        or candidate_evidence.get("production_deploy_eligible") is not False
        or (
            report_schema == _REPORT_PAYLOAD_V2_SCHEMA
            and candidate_manifest.get("report_schema") != report_schema
        )
        or (
            report_schema == _REPORT_PAYLOAD_V1_SCHEMA
            and candidate_manifest.get("report_schema") not in {None, report_schema}
        )
        or candidate_report_payload.get("production_deploy_eligible") is not False
    ):
        raise ConcurrentRobustnessEvidenceError("validation candidate did not preserve its non-production contract")
    if set(artifacts) != set(declared_hashes) or len(set(artifacts.values())) != len(artifacts):
        raise ConcurrentRobustnessEvidenceError("validation candidate artifact inventory is crossed")
    if set(artifacts.values()) != set(candidate_hashes) - {CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON}:
        raise ConcurrentRobustnessEvidenceError("validation candidate artifact inventory is incomplete")
    for name, relative_path in artifacts.items():
        if declared_hashes[name] != candidate_hashes[relative_path]:
            raise ConcurrentRobustnessEvidenceError("validation candidate artifact hash mismatch")
    content_hashes = {
        relative_path: declared_hashes[name]
        for name, relative_path in artifacts.items()
        if relative_path != _CANDIDATE_EVIDENCE
    }
    if candidate_evidence.get("candidate_content_identity_sha256") != _sha256_bytes(
        _json_bytes(dict(sorted(content_hashes.items())))
    ):
        raise ConcurrentRobustnessEvidenceError("validation candidate content identity is crossed")
    identity_rows = dict(sorted((path, declared_hashes[name]) for name, path in artifacts.items()))
    if candidate_manifest.get("candidate_identity_sha256") != _sha256_bytes(_json_bytes(identity_rows)):
        raise ConcurrentRobustnessEvidenceError("validation candidate identity hash is crossed")

    formal_source = candidate_manifest.get("formal_source")
    study_source = candidate_manifest.get("study_source")
    if not isinstance(formal_source, Mapping) or not isinstance(study_source, Mapping):
        raise ConcurrentRobustnessEvidenceError("validation candidate lineage is missing")
    formal_manifest_sha256 = _sha256_file(formal / CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON)
    study_artifact_sha256 = _sha256_file(study / "artifact_manifest.json")
    study_root_identity = _string(
        _json_object(study / "artifact_manifest.json").get("root_identity_sha256"),
        "study root identity",
    )
    if (
        formal_source.get("manifest_sha256") != manifest.source.manifest_sha256
        or manifest.source.manifest_sha256 != formal_manifest_sha256
        or study_source.get("manifest_sha256") != manifest_sha256
        or study_source.get("artifact_manifest_sha256") != study_artifact_sha256
        or study_source.get("root_identity_sha256") != study_root_identity
        or candidate_evidence.get("formal_source_manifest_sha256") != manifest.source.manifest_sha256
        or candidate_evidence.get("study_manifest_sha256") != manifest_sha256
        or candidate_evidence.get("study_root_identity_sha256") != study_root_identity
    ):
        raise ConcurrentRobustnessEvidenceError("validation candidate lineage is crossed")

    payload_downloads = _string_mapping(
        candidate_report_payload.get("downloads"),
        "candidate report downloads",
    )
    raw_manifest_downloads = candidate_manifest.get("approved_downloads")
    if not isinstance(raw_manifest_downloads, list) or any(
        not isinstance(value, str) or not value for value in raw_manifest_downloads
    ):
        raise ConcurrentRobustnessEvidenceError("validation candidate approved downloads are invalid")
    manifest_downloads = list(raw_manifest_downloads)
    if (
        len(set(manifest_downloads)) != len(manifest_downloads)
        or set(manifest_downloads) != set(payload_downloads.values())
        or type(candidate_evidence.get("provider_calls_during_composition")) is not int
        or candidate_evidence.get("provider_calls_during_composition") != 0
        or candidate_evidence.get("image_generation_triggered") is not False
    ):
        raise ConcurrentRobustnessEvidenceError(
            "validation candidate approved downloads or eligibility evidence is crossed"
        )
    inventory = set(artifacts.values()) | {CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON}
    for relative_path in manifest_downloads:
        path = PurePosixPath(relative_path)
        target = candidate / relative_path
        if (
            "\\" in relative_path
            or path.is_absolute()
            or path.as_posix() != relative_path
            or ".." in path.parts
            or relative_path not in inventory
            or target.is_symlink()
            or not target.is_file()
        ):
            raise ConcurrentRobustnessEvidenceError(
                "validation candidate approved download escapes or is absent from inventory"
            )


def close_presentation(
    *,
    repo_root: str | Path,
    formal_root: str | Path,
    study_root: str | Path,
    workspace_root: str | Path,
    candidate_dir: str | Path,
    execution_contract_path: str | Path,
    destination_path: str | Path,
    implementation_commit: str,
) -> PresentationClosureFacts:
    """Close an additive presentation candidate without touching its inputs."""
    root = _real_directory(Path(repo_root), "repository root")
    formal = _repo_directory(root, Path(formal_root), "historical Formal root")
    study = _repo_directory(root, Path(study_root), "robustness study root")
    workspace = _repo_directory(root, Path(workspace_root), "robustness workspace")
    candidate = _repo_directory(root, Path(candidate_dir), "new presentation candidate")
    execution_path = _repo_file(root, Path(execution_contract_path), "Formal execution contract")
    destination = _new_repo_path(root, Path(destination_path), "presentation closure destination")
    protected_inputs = (formal, study, workspace, candidate, execution_path)
    if any(_paths_overlap(destination, item) for item in protected_inputs):
        raise ConcurrentRobustnessEvidenceError("presentation closure destination overlaps immutable input evidence")
    if not _COMMIT.fullmatch(implementation_commit):
        raise ConcurrentRobustnessEvidenceError("presentation implementation commit is invalid")

    old_candidate, execution, old_facts, new_facts = _prepare_closure_lineage(
        root=root,
        formal=formal,
        study=study,
        workspace=workspace,
        candidate=candidate,
        execution_path=execution_path,
    )
    replay = _repo_file(
        root,
        Path(_string(execution.get("closure_replay_artifact"), "immutable replay")),
        "immutable replay",
    )
    if new_facts.report_payload_schema_version == _REPORT_PAYLOAD_V2_SCHEMA:
        if new_facts.semantic_set_identity_sha256 is None:
            raise ConcurrentRobustnessEvidenceError("payload v2 semantic identity is missing")
        closure_schema = PRESENTATION_CLOSURE_V2_SCHEMA
    else:
        closure_schema = PRESENTATION_CLOSURE_SCHEMA
    closure_document = {
        "schema_version": closure_schema,
        "status": "complete",
        "implementation_commit": implementation_commit,
        "formal_execution_contract": execution_path.relative_to(root).as_posix(),
        "formal_execution_contract_sha256": _sha256_file(execution_path),
        "immutable_replay": replay.relative_to(root).as_posix(),
        "immutable_replay_sha256": _string(execution.get("closure_replay_sha256"), "immutable replay SHA-256"),
        "old_candidate_directory": old_candidate.relative_to(root).as_posix(),
        "old_candidate_manifest_sha256": old_facts.manifest_sha256,
        "old_candidate_identity_sha256": old_facts.candidate_identity_sha256,
        "new_candidate_directory": candidate.relative_to(root).as_posix(),
        "new_candidate_manifest_sha256": new_facts.manifest_sha256,
        "new_candidate_identity_sha256": new_facts.candidate_identity_sha256,
        "new_candidate_report_sha256": new_facts.report_sha256,
        "new_candidate_payload_sha256": new_facts.payload_sha256,
        "new_candidate_evidence_sha256": new_facts.evidence_sha256,
        "new_candidate_content_identity_sha256": new_facts.content_identity_sha256,
        "provider_calls_during_closure": 0,
        "image_generation_triggered": False,
    }
    if closure_schema == PRESENTATION_CLOSURE_V2_SCHEMA:
        closure_document.update(
            {
                "report_payload_schema_version": new_facts.report_payload_schema_version,
                "semantic_set_identity_sha256": new_facts.semantic_set_identity_sha256,
            }
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging: Path | None = None
    installed = False
    try:
        fd, staging_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".staging", dir=destination.parent)
        staging = Path(staging_name)
        with os.fdopen(fd, "wb") as stream:
            stream.write(_json_bytes(closure_document))
            stream.flush()
            os.fsync(stream.fileno())
        # link(2) is intentionally used instead of replace(2): a close can never
        # overwrite an operator's existing contract, even under a race.
        os.link(staging, destination)
        staging.unlink()
        staging = None
        installed = True
        result = validate_presentation_closure(
            repo_root=root,
            closure_path=destination,
            formal_root=formal,
            study_root=study,
            workspace_root=workspace,
            candidate_dir=candidate,
            execution_contract_path=execution_path,
        )
        installed = False
        return result
    except ConcurrentRobustnessEvidenceError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise ConcurrentRobustnessEvidenceError("presentation closure failed atomic close") from exc
    finally:
        if staging is not None:
            staging.unlink(missing_ok=True)
        if installed and destination.exists():
            destination.unlink(missing_ok=True)


@dataclass(frozen=True)
class _CandidateFacts:
    manifest_sha256: str
    candidate_identity_sha256: str
    report_sha256: str
    payload_sha256: str
    evidence_sha256: str
    content_identity_sha256: str
    report_payload_schema_version: str
    semantic_set_identity_sha256: str | None


def _candidate_facts(candidate: Path) -> _CandidateFacts:
    hashes = _flat_file_hashes(candidate)
    manifest = _json_object(candidate / CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON)
    evidence = _json_object(candidate / _CANDIDATE_EVIDENCE)
    payload = _json_object(candidate / _CANDIDATE_PAYLOAD)
    report_schema, semantic_identity = _validate_report_payload_contract(
        payload,
        candidate=candidate,
    )
    identity = _string(manifest.get("candidate_identity_sha256"), "candidate identity")
    content = _string(evidence.get("candidate_content_identity_sha256"), "candidate content identity")
    if not _SHA256.fullmatch(identity) or not _SHA256.fullmatch(content):
        raise ConcurrentRobustnessEvidenceError("candidate identity hash is invalid")
    required_files = (_CANDIDATE_REPORT, _CANDIDATE_PAYLOAD, _CANDIDATE_EVIDENCE)
    if any(name not in hashes for name in required_files):
        raise ConcurrentRobustnessEvidenceError("candidate identity inventory is incomplete")
    return _CandidateFacts(
        manifest_sha256=hashes[CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON],
        candidate_identity_sha256=identity,
        report_sha256=hashes[_CANDIDATE_REPORT],
        payload_sha256=hashes[_CANDIDATE_PAYLOAD],
        evidence_sha256=hashes[_CANDIDATE_EVIDENCE],
        content_identity_sha256=content,
        report_payload_schema_version=report_schema,
        semantic_set_identity_sha256=semantic_identity,
    )


def _prepare_closure_lineage(
    *,
    root: Path,
    formal: Path,
    study: Path,
    workspace: Path,
    candidate: Path,
    execution_path: Path,
) -> tuple[Path, dict[str, Any], _CandidateFacts, _CandidateFacts]:
    manifest_payload = (study / "study_manifest.json").read_bytes()
    manifest_sha256 = _sha256_bytes(manifest_payload)
    try:
        manifest = ConcurrentRobustnessManifest.model_validate(json.loads(manifest_payload))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ConcurrentRobustnessEvidenceError("Formal study manifest is invalid") from exc

    execution = _json_object(execution_path)
    old_candidate = _repo_directory(
        root,
        Path(_string(execution.get("report_candidate"), "Formal report candidate")),
        "Formal report candidate",
    )
    if old_candidate == candidate:
        raise ConcurrentRobustnessEvidenceError("old and new presentation candidates must be distinct")
    _validate_execution_contract(
        root=root,
        path=execution_path,
        formal=formal,
        study=study,
        workspace=workspace,
        candidate=old_candidate,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
    )
    _close_formal_cell_evidence(
        study=study,
        workspace=workspace,
        formal=formal,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
    )
    for item in (old_candidate, candidate):
        _validate_candidate_release_contract(
            candidate=item,
            candidate_manifest=_json_object(item / CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON),
            candidate_evidence=_json_object(item / _CANDIDATE_EVIDENCE),
            candidate_report_payload=_json_object(item / _CANDIDATE_PAYLOAD),
            manifest=manifest,
            manifest_sha256=manifest_sha256,
            formal=formal,
            study=study,
        )
    old_facts = _candidate_facts(old_candidate)
    new_facts = _candidate_facts(candidate)
    if old_facts.candidate_identity_sha256 == new_facts.candidate_identity_sha256:
        raise ConcurrentRobustnessEvidenceError("old and new presentation candidates must be distinct")
    return old_candidate, execution, old_facts, new_facts


def _canonical_document_path(value: object, label: str) -> str:
    relative = _string(value, label)
    path = PurePosixPath(relative)
    if (
        "\\" in relative
        or path.is_absolute()
        or path.as_posix() != relative
        or not relative
        or "." in path.parts
        or ".." in path.parts
    ):
        raise ConcurrentRobustnessEvidenceError(f"{label} must be a canonical repository-relative path")
    return relative


def validate_presentation_closure(
    *,
    repo_root: str | Path,
    closure_path: str | Path,
    formal_root: str | Path,
    study_root: str | Path,
    workspace_root: str | Path,
    candidate_dir: str | Path,
    execution_contract_path: str | Path,
) -> PresentationClosureFacts:
    """Revalidate closure bytes and every referenced evidence lineage."""
    root = _real_directory(Path(repo_root), "repository root")
    closure = _repo_file(root, Path(closure_path), "presentation closure contract")
    formal = _repo_directory(root, Path(formal_root), "historical Formal root")
    study = _repo_directory(root, Path(study_root), "robustness study root")
    workspace = _repo_directory(root, Path(workspace_root), "robustness workspace")
    candidate = _repo_directory(root, Path(candidate_dir), "new presentation candidate")
    execution_path = _repo_file(root, Path(execution_contract_path), "Formal execution contract")
    document = _json_object(closure)
    common_required = {
        "schema_version",
        "status",
        "implementation_commit",
        "formal_execution_contract",
        "formal_execution_contract_sha256",
        "immutable_replay",
        "immutable_replay_sha256",
        "old_candidate_directory",
        "old_candidate_manifest_sha256",
        "old_candidate_identity_sha256",
        "new_candidate_directory",
        "new_candidate_manifest_sha256",
        "new_candidate_identity_sha256",
        "new_candidate_report_sha256",
        "new_candidate_payload_sha256",
        "new_candidate_evidence_sha256",
        "new_candidate_content_identity_sha256",
        "provider_calls_during_closure",
        "image_generation_triggered",
    }
    closure_schema = document.get("schema_version")
    if closure_schema == PRESENTATION_CLOSURE_SCHEMA:
        required = common_required
    elif closure_schema == PRESENTATION_CLOSURE_V2_SCHEMA:
        required = common_required | {
            "report_payload_schema_version",
            "semantic_set_identity_sha256",
        }
    else:
        raise ConcurrentRobustnessEvidenceError("presentation closure schema is unsupported")
    if set(document) != required:
        raise ConcurrentRobustnessEvidenceError("presentation closure fields are missing or unexpected")
    if (
        document.get("status") != "complete"
        or type(document.get("provider_calls_during_closure")) is not int
        or document.get("provider_calls_during_closure") != 0
        or document.get("image_generation_triggered") is not False
    ):
        raise ConcurrentRobustnessEvidenceError("presentation closure is incomplete or not zero-provider")

    implementation = _string(document.get("implementation_commit"), "presentation implementation commit")
    if not _COMMIT.fullmatch(implementation):
        raise ConcurrentRobustnessEvidenceError("presentation implementation commit is invalid")
    stored_execution_relative = _canonical_document_path(
        document.get("formal_execution_contract"), "Formal execution contract"
    )
    replay_relative = _canonical_document_path(document.get("immutable_replay"), "immutable replay")
    old_relative = _canonical_document_path(document.get("old_candidate_directory"), "old candidate directory")
    new_relative = _canonical_document_path(document.get("new_candidate_directory"), "new candidate directory")
    stored_execution = _repo_file(root, Path(stored_execution_relative), "presentation Formal execution contract")
    replay = _repo_file(root, Path(replay_relative), "presentation immutable replay")
    old_candidate = _repo_directory(root, Path(old_relative), "presentation old candidate")
    new_candidate = _repo_directory(root, Path(new_relative), "presentation new candidate")
    if stored_execution != execution_path or new_candidate != candidate or old_candidate == new_candidate:
        raise ConcurrentRobustnessEvidenceError("presentation closure explicit inputs are crossed")

    manifest_payload = (study / "study_manifest.json").read_bytes()
    manifest_sha256 = _sha256_bytes(manifest_payload)
    try:
        manifest = ConcurrentRobustnessManifest.model_validate(json.loads(manifest_payload))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ConcurrentRobustnessEvidenceError("Formal study manifest is invalid") from exc
    execution = _json_object(execution_path)
    execution_candidate = _repo_directory(
        root,
        Path(_string(execution.get("report_candidate"), "Formal report candidate")),
        "Formal report candidate",
    )
    if execution_candidate != old_candidate:
        raise ConcurrentRobustnessEvidenceError("presentation old candidate is crossed with Formal execution")
    execution_replay = _repo_file(
        root,
        Path(_string(execution.get("closure_replay_artifact"), "immutable replay")),
        "immutable replay",
    )
    if execution_replay != replay:
        raise ConcurrentRobustnessEvidenceError("presentation replay path is crossed")

    _validate_execution_contract(
        root=root,
        path=execution_path,
        formal=formal,
        study=study,
        workspace=workspace,
        candidate=old_candidate,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
    )
    _close_formal_cell_evidence(
        study=study,
        workspace=workspace,
        formal=formal,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
    )
    for item in (old_candidate, new_candidate):
        _validate_candidate_release_contract(
            candidate=item,
            candidate_manifest=_json_object(item / CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON),
            candidate_evidence=_json_object(item / _CANDIDATE_EVIDENCE),
            candidate_report_payload=_json_object(item / _CANDIDATE_PAYLOAD),
            manifest=manifest,
            manifest_sha256=manifest_sha256,
            formal=formal,
            study=study,
        )

    old_facts = _candidate_facts(old_candidate)
    new_facts = _candidate_facts(new_candidate)
    if closure_schema == PRESENTATION_CLOSURE_SCHEMA:
        if new_facts.report_payload_schema_version != _REPORT_PAYLOAD_V1_SCHEMA:
            raise ConcurrentRobustnessEvidenceError("closure v1 is crossed with the report payload schema")
    elif (
        new_facts.report_payload_schema_version != _REPORT_PAYLOAD_V2_SCHEMA
        or new_facts.semantic_set_identity_sha256 is None
        or document.get("report_payload_schema_version") != new_facts.report_payload_schema_version
        or document.get("semantic_set_identity_sha256") != new_facts.semantic_set_identity_sha256
    ):
        raise ConcurrentRobustnessEvidenceError("closure v2 semantic identity is crossed")
    expected_hashes = {
        "formal_execution_contract_sha256": _sha256_file(execution_path),
        "immutable_replay_sha256": _sha256_file(replay),
        "old_candidate_manifest_sha256": old_facts.manifest_sha256,
        "old_candidate_identity_sha256": old_facts.candidate_identity_sha256,
        "new_candidate_manifest_sha256": new_facts.manifest_sha256,
        "new_candidate_identity_sha256": new_facts.candidate_identity_sha256,
        "new_candidate_report_sha256": new_facts.report_sha256,
        "new_candidate_payload_sha256": new_facts.payload_sha256,
        "new_candidate_evidence_sha256": new_facts.evidence_sha256,
        "new_candidate_content_identity_sha256": new_facts.content_identity_sha256,
    }
    if any(document.get(key) != value for key, value in expected_hashes.items()):
        raise ConcurrentRobustnessEvidenceError("presentation closure hash or identity is crossed")

    physical_attempts = _strict_int(execution.get("physical_provider_attempts"), "physical provider attempts")
    nominal_cost = execution.get("subscription_nominal_reference_cost_usd")
    if isinstance(nominal_cost, bool) or not isinstance(nominal_cost, (int, float)) or nominal_cost < 0:
        raise ConcurrentRobustnessEvidenceError("subscription nominal reference cost is invalid")
    return PresentationClosureFacts(
        closure_path=closure,
        closure_sha256=_sha256_file(closure),
        closure_schema_version=str(closure_schema),
        implementation_commit=implementation,
        formal_execution_contract_path=execution_path,
        formal_execution_contract_sha256=expected_hashes["formal_execution_contract_sha256"],
        immutable_replay_path=replay,
        immutable_replay_sha256=expected_hashes["immutable_replay_sha256"],
        old_candidate_path=old_candidate,
        old_candidate_manifest_sha256=old_facts.manifest_sha256,
        old_candidate_identity_sha256=old_facts.candidate_identity_sha256,
        new_candidate_path=new_candidate,
        new_candidate_manifest_sha256=new_facts.manifest_sha256,
        new_candidate_identity_sha256=new_facts.candidate_identity_sha256,
        new_candidate_report_sha256=new_facts.report_sha256,
        new_candidate_payload_sha256=new_facts.payload_sha256,
        new_candidate_evidence_sha256=new_facts.evidence_sha256,
        new_candidate_content_identity_sha256=new_facts.content_identity_sha256,
        formal_judgment_implementation_commit=_string(execution.get("implementation_commit"), "implementation commit"),
        formal_closure_implementation_commit=_string(
            execution.get("closure_implementation_commit"), "closure implementation commit"
        ),
        logical_judgments=FORMAL_LOGICAL_JUDGMENTS,
        physical_attempts=physical_attempts,
        subscription_nominal_reference_cost_usd=float(nominal_cost),
        provider_calls_during_closure=0,
        image_generation_triggered=False,
        report_payload_schema_version=new_facts.report_payload_schema_version,
        semantic_set_identity_sha256=new_facts.semantic_set_identity_sha256,
    )


def _full_pool_closure_document(
    *,
    root: Path,
    full_pool: Path,
    historical_formal: Path,
    robustness_study: Path,
    presentation_bundle: Path,
    candidate: Path,
    facts: _FullPoolCandidateFacts,
    implementation_commit: str,
) -> dict[str, Any]:
    lineage = facts.source_lineage
    if set(lineage) != {"full_pool", "historical_formal", "robustness_study"}:
        raise ConcurrentRobustnessEvidenceError("Full-Pool candidate lineage fields are missing or unexpected")
    full_pool_lineage = _mapping(lineage.get("full_pool"), "Full-Pool source lineage")
    historical_lineage = _mapping(
        lineage.get("historical_formal"),
        "historical Formal source lineage",
    )
    study_lineage = _mapping(
        lineage.get("robustness_study"),
        "robustness study lineage",
    )
    if facts.implementation_commit != implementation_commit:
        raise ConcurrentRobustnessEvidenceError("Full-Pool candidate implementation commit is crossed")
    return {
        "schema_version": FULL_POOL_PRESENTATION_CLOSURE_SCHEMA,
        "status": "complete",
        "implementation_commit": implementation_commit,
        "full_pool_source_directory": full_pool.relative_to(root).as_posix(),
        "full_pool_source_schema_version": _string(
            full_pool_lineage.get("source_schema_version"),
            "Full-Pool source schema",
        ),
        "full_pool_source_identity": _string(
            full_pool_lineage.get("source_identity"),
            "Full-Pool source identity",
        ),
        "full_pool_source_manifest_sha256": _string(
            full_pool_lineage.get("manifest_sha256"),
            "Full-Pool source manifest SHA-256",
        ),
        "full_pool_source_hash": _string(
            full_pool_lineage.get("source_hash"),
            "Full-Pool source hash",
        ),
        "historical_formal_directory": historical_formal.relative_to(root).as_posix(),
        "historical_formal_source_id": _string(
            historical_lineage.get("source_id"),
            "historical Formal source identity",
        ),
        "historical_formal_manifest_schema_version": _string(
            historical_lineage.get("manifest_schema_version"),
            "historical Formal manifest schema",
        ),
        "historical_formal_manifest_sha256": _string(
            historical_lineage.get("manifest_sha256"),
            "historical Formal manifest SHA-256",
        ),
        "robustness_study_directory": robustness_study.relative_to(root).as_posix(),
        "robustness_study_manifest_schema_version": _string(
            study_lineage.get("manifest_schema_version"),
            "robustness study manifest schema",
        ),
        "robustness_study_manifest_sha256": _string(
            study_lineage.get("manifest_sha256"),
            "robustness study manifest SHA-256",
        ),
        "robustness_study_artifact_manifest_sha256": _string(
            study_lineage.get("artifact_manifest_sha256"),
            "robustness study artifact manifest SHA-256",
        ),
        "robustness_study_root_identity_sha256": _string(
            study_lineage.get("root_identity_sha256"),
            "robustness study root identity",
        ),
        "presentation_bundle_directory": presentation_bundle.relative_to(root).as_posix(),
        "presentation_bundle_identity_sha256": facts.presentation_bundle_identity_sha256,
        "candidate_directory": candidate.relative_to(root).as_posix(),
        "candidate_manifest_sha256": facts.manifest_sha256,
        "candidate_identity_sha256": facts.candidate_identity_sha256,
        "candidate_content_identity_sha256": facts.candidate_content_identity_sha256,
        "candidate_report_sha256": facts.report_sha256,
        "candidate_payload_sha256": facts.payload_sha256,
        "candidate_evidence_sha256": facts.evidence_sha256,
        "report_payload_schema_version": facts.report_payload_schema_version,
        "source_lineage_identity_sha256": facts.source_lineage_identity_sha256,
        "presentation_inventory_identity_sha256": facts.presentation_inventory_identity_sha256,
        "mechanism_set_identity_sha256": facts.mechanism_set_identity_sha256,
        "trace_index_sha256": facts.trace_index_sha256,
        "provider_calls_during_closure": 0,
        "image_generation_triggered": False,
        "production_deploy_eligible": False,
    }


def _full_pool_closure_inputs(
    *,
    root: Path,
    full_pool_source_root: str | Path,
    historical_formal_root: str | Path,
    historical_study_root: str | Path,
    presentation_bundle_dir: str | Path,
    candidate_dir: str | Path,
) -> tuple[Path, Path, Path, Path, Path]:
    return (
        _repo_directory(root, Path(full_pool_source_root), "Full-Pool source root"),
        _repo_directory(root, Path(historical_formal_root), "historical Formal root"),
        _repo_directory(root, Path(historical_study_root), "robustness study root"),
        _repo_directory(root, Path(presentation_bundle_dir), "Full-Pool presentation bundle"),
        _repo_directory(root, Path(candidate_dir), "Full-Pool presentation candidate"),
    )


def _validate_full_pool_candidate_for_closure(
    *,
    full_pool: Path,
    full_pool_manifest_sha256: str,
    historical_formal: Path,
    robustness_study: Path,
    presentation_bundle: Path,
    candidate: Path,
    implementation_commit: str,
) -> _FullPoolCandidateFacts:
    try:
        return _REPORT_PRESENTATION.validate_full_pool_candidate(
            candidate,
            full_pool_source_root=full_pool,
            full_pool_manifest_sha256=full_pool_manifest_sha256,
            historical_formal_root=historical_formal,
            historical_study_root=robustness_study,
            presentation_bundle_dir=presentation_bundle,
            implementation_commit=implementation_commit,
        )
    except (OSError, TypeError, ValueError) as exc:
        raise ConcurrentRobustnessEvidenceError(
            "Full-Pool candidate failed Report Presentation Interface closure"
        ) from exc


def _full_pool_snapshots(paths: tuple[Path, ...]) -> dict[Path, dict[str, str]]:
    return {path: _flat_file_hashes(path) for path in paths}


def _assert_full_pool_snapshots(snapshots: Mapping[Path, Mapping[str, str]]) -> None:
    if any(_flat_file_hashes(path) != dict(before) for path, before in snapshots.items()):
        raise ConcurrentRobustnessEvidenceError(
            "Full-Pool presentation closure mutated immutable input evidence"
        )


def close_full_pool_presentation(
    *,
    repo_root: str | Path,
    full_pool_source_root: str | Path,
    full_pool_manifest_sha256: str,
    historical_formal_root: str | Path,
    historical_study_root: str | Path,
    presentation_bundle_dir: str | Path,
    candidate_dir: str | Path,
    destination_path: str | Path,
    implementation_commit: str,
) -> FullPoolPresentationClosureFacts:
    """Atomically close a Full-Pool three-lineage presentation without reopening a Provider."""
    root = _real_directory(Path(repo_root), "repository root")
    full_pool, historical_formal, study, bundle, candidate = _full_pool_closure_inputs(
        root=root,
        full_pool_source_root=full_pool_source_root,
        historical_formal_root=historical_formal_root,
        historical_study_root=historical_study_root,
        presentation_bundle_dir=presentation_bundle_dir,
        candidate_dir=candidate_dir,
    )
    destination = _new_repo_path(
        root,
        Path(destination_path),
        "Full-Pool presentation closure destination",
    )
    protected = (full_pool, historical_formal, study, bundle, candidate)
    if any(_paths_overlap(destination, item) for item in protected):
        raise ConcurrentRobustnessEvidenceError(
            "Full-Pool presentation closure destination overlaps immutable input evidence"
        )
    if not _COMMIT.fullmatch(implementation_commit):
        raise ConcurrentRobustnessEvidenceError("Full-Pool presentation implementation commit is invalid")
    snapshots = _full_pool_snapshots(protected)
    facts = _validate_full_pool_candidate_for_closure(
        full_pool=full_pool,
        full_pool_manifest_sha256=full_pool_manifest_sha256,
        historical_formal=historical_formal,
        robustness_study=study,
        presentation_bundle=bundle,
        candidate=candidate,
        implementation_commit=implementation_commit,
    )
    document = _full_pool_closure_document(
        root=root,
        full_pool=full_pool,
        historical_formal=historical_formal,
        robustness_study=study,
        presentation_bundle=bundle,
        candidate=candidate,
        facts=facts,
        implementation_commit=implementation_commit,
    )
    _assert_full_pool_snapshots(snapshots)

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging: Path | None = None
    installed = False
    try:
        fd, staging_name = tempfile.mkstemp(
            prefix=f".{destination.name}.full-pool.",
            suffix=".staging",
            dir=destination.parent,
        )
        staging = Path(staging_name)
        with os.fdopen(fd, "wb") as stream:
            stream.write(_json_bytes(document))
            stream.flush()
            os.fsync(stream.fileno())
        os.link(staging, destination)
        staging.unlink()
        staging = None
        installed = True
        result = validate_full_pool_presentation_closure(
            repo_root=root,
            closure_path=destination,
            full_pool_source_root=full_pool,
            full_pool_manifest_sha256=full_pool_manifest_sha256,
            historical_formal_root=historical_formal,
            historical_study_root=study,
            presentation_bundle_dir=bundle,
            candidate_dir=candidate,
        )
        _assert_full_pool_snapshots(snapshots)
        installed = False
        return result
    except ConcurrentRobustnessEvidenceError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise ConcurrentRobustnessEvidenceError(
            "Full-Pool presentation closure failed atomic close"
        ) from exc
    finally:
        if staging is not None:
            staging.unlink(missing_ok=True)
        if installed and destination.exists():
            destination.unlink(missing_ok=True)


def validate_full_pool_presentation_closure(
    *,
    repo_root: str | Path,
    closure_path: str | Path,
    full_pool_source_root: str | Path,
    full_pool_manifest_sha256: str,
    historical_formal_root: str | Path,
    historical_study_root: str | Path,
    presentation_bundle_dir: str | Path,
    candidate_dir: str | Path,
) -> FullPoolPresentationClosureFacts:
    """Reread the three source lineages, bundle, candidate, and additive closure bytes."""
    root = _real_directory(Path(repo_root), "repository root")
    closure = _repo_file(root, Path(closure_path), "Full-Pool presentation closure")
    full_pool, historical_formal, study, bundle, candidate = _full_pool_closure_inputs(
        root=root,
        full_pool_source_root=full_pool_source_root,
        historical_formal_root=historical_formal_root,
        historical_study_root=historical_study_root,
        presentation_bundle_dir=presentation_bundle_dir,
        candidate_dir=candidate_dir,
    )
    protected = (full_pool, historical_formal, study, bundle, candidate)
    if any(_paths_overlap(closure, item) for item in protected):
        raise ConcurrentRobustnessEvidenceError(
            "Full-Pool presentation closure overlaps immutable input evidence"
        )
    document = _json_object(closure)
    required = {
        "schema_version",
        "status",
        "implementation_commit",
        "full_pool_source_directory",
        "full_pool_source_schema_version",
        "full_pool_source_identity",
        "full_pool_source_manifest_sha256",
        "full_pool_source_hash",
        "historical_formal_directory",
        "historical_formal_source_id",
        "historical_formal_manifest_schema_version",
        "historical_formal_manifest_sha256",
        "robustness_study_directory",
        "robustness_study_manifest_schema_version",
        "robustness_study_manifest_sha256",
        "robustness_study_artifact_manifest_sha256",
        "robustness_study_root_identity_sha256",
        "presentation_bundle_directory",
        "presentation_bundle_identity_sha256",
        "candidate_directory",
        "candidate_manifest_sha256",
        "candidate_identity_sha256",
        "candidate_content_identity_sha256",
        "candidate_report_sha256",
        "candidate_payload_sha256",
        "candidate_evidence_sha256",
        "report_payload_schema_version",
        "source_lineage_identity_sha256",
        "presentation_inventory_identity_sha256",
        "mechanism_set_identity_sha256",
        "trace_index_sha256",
        "provider_calls_during_closure",
        "image_generation_triggered",
        "production_deploy_eligible",
    }
    if set(document) != required:
        raise ConcurrentRobustnessEvidenceError(
            "Full-Pool presentation closure fields are missing or unexpected"
        )
    if (
        document.get("schema_version") != FULL_POOL_PRESENTATION_CLOSURE_SCHEMA
        or document.get("status") != "complete"
        or type(document.get("provider_calls_during_closure")) is not int
        or document.get("provider_calls_during_closure") != 0
        or document.get("image_generation_triggered") is not False
        or document.get("production_deploy_eligible") is not False
    ):
        raise ConcurrentRobustnessEvidenceError(
            "Full-Pool presentation closure schema, status, or zero-call contract is crossed"
        )
    implementation_commit = _string(
        document.get("implementation_commit"),
        "Full-Pool presentation implementation commit",
    )
    if not _COMMIT.fullmatch(implementation_commit):
        raise ConcurrentRobustnessEvidenceError("Full-Pool presentation implementation commit is invalid")

    explicit_paths = {
        "full_pool_source_directory": full_pool,
        "historical_formal_directory": historical_formal,
        "robustness_study_directory": study,
        "presentation_bundle_directory": bundle,
        "candidate_directory": candidate,
    }
    for field_name, expected_path in explicit_paths.items():
        relative = _canonical_document_path(document.get(field_name), field_name)
        if _repo_directory(root, Path(relative), field_name) != expected_path:
            raise ConcurrentRobustnessEvidenceError(
                "Full-Pool presentation closure explicit input paths are crossed"
            )
    snapshots = _full_pool_snapshots(protected)
    facts = _validate_full_pool_candidate_for_closure(
        full_pool=full_pool,
        full_pool_manifest_sha256=full_pool_manifest_sha256,
        historical_formal=historical_formal,
        robustness_study=study,
        presentation_bundle=bundle,
        candidate=candidate,
        implementation_commit=implementation_commit,
    )
    expected = _full_pool_closure_document(
        root=root,
        full_pool=full_pool,
        historical_formal=historical_formal,
        robustness_study=study,
        presentation_bundle=bundle,
        candidate=candidate,
        facts=facts,
        implementation_commit=implementation_commit,
    )
    if document != expected:
        raise ConcurrentRobustnessEvidenceError(
            "Full-Pool presentation closure hash, identity, or lineage is crossed"
        )
    _assert_full_pool_snapshots(snapshots)
    lineage = facts.source_lineage
    full_pool_lineage = _mapping(lineage.get("full_pool"), "Full-Pool source lineage")
    historical_lineage = _mapping(
        lineage.get("historical_formal"),
        "historical Formal lineage",
    )
    study_lineage = _mapping(lineage.get("robustness_study"), "robustness study lineage")
    return FullPoolPresentationClosureFacts(
        closure_path=closure,
        closure_sha256=_sha256_file(closure),
        closure_schema_version=FULL_POOL_PRESENTATION_CLOSURE_SCHEMA,
        implementation_commit=implementation_commit,
        full_pool_source_path=full_pool,
        full_pool_source_schema_version=_string(
            full_pool_lineage.get("source_schema_version"),
            "Full-Pool source schema",
        ),
        full_pool_source_identity=_string(
            full_pool_lineage.get("source_identity"),
            "Full-Pool source identity",
        ),
        full_pool_source_manifest_sha256=_string(
            full_pool_lineage.get("manifest_sha256"),
            "Full-Pool source manifest hash",
        ),
        full_pool_source_hash=_string(
            full_pool_lineage.get("source_hash"),
            "Full-Pool source hash",
        ),
        historical_formal_path=historical_formal,
        historical_formal_source_id=_string(
            historical_lineage.get("source_id"),
            "historical Formal source identity",
        ),
        historical_formal_manifest_schema_version=_string(
            historical_lineage.get("manifest_schema_version"),
            "historical Formal manifest schema",
        ),
        historical_formal_manifest_sha256=_string(
            historical_lineage.get("manifest_sha256"),
            "historical Formal manifest hash",
        ),
        robustness_study_path=study,
        robustness_study_manifest_schema_version=_string(
            study_lineage.get("manifest_schema_version"),
            "robustness study manifest schema",
        ),
        robustness_study_manifest_sha256=_string(
            study_lineage.get("manifest_sha256"),
            "robustness study manifest hash",
        ),
        robustness_study_artifact_manifest_sha256=_string(
            study_lineage.get("artifact_manifest_sha256"),
            "robustness study artifact manifest hash",
        ),
        robustness_study_root_identity_sha256=_string(
            study_lineage.get("root_identity_sha256"),
            "robustness study root identity",
        ),
        presentation_bundle_path=bundle,
        presentation_bundle_identity_sha256=facts.presentation_bundle_identity_sha256,
        candidate_path=candidate,
        candidate_manifest_sha256=facts.manifest_sha256,
        candidate_identity_sha256=facts.candidate_identity_sha256,
        candidate_content_identity_sha256=facts.candidate_content_identity_sha256,
        candidate_report_sha256=facts.report_sha256,
        candidate_payload_sha256=facts.payload_sha256,
        candidate_evidence_sha256=facts.evidence_sha256,
        report_payload_schema_version=facts.report_payload_schema_version,
        source_lineage_identity_sha256=facts.source_lineage_identity_sha256,
        presentation_inventory_identity_sha256=facts.presentation_inventory_identity_sha256,
        mechanism_set_identity_sha256=facts.mechanism_set_identity_sha256,
        trace_index_sha256=facts.trace_index_sha256,
        provider_calls_during_closure=0,
        image_generation_triggered=False,
        production_deploy_eligible=False,
    )


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ConcurrentRobustnessEvidenceError(f"{label} must be an object")
    return {str(key): item for key, item in value.items()}


def _json_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")


def _json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConcurrentRobustnessEvidenceError(f"cannot read valid JSON evidence: {path.name}") from exc
    if not isinstance(value, dict):
        raise ConcurrentRobustnessEvidenceError(f"JSON evidence must be an object: {path.name}")
    return value


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _flat_file_hashes(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            if path.is_dir() and not path.is_symlink():
                continue
            raise ConcurrentRobustnessEvidenceError("release evidence contains a symlink or non-regular entry")
        relative = path.relative_to(root).as_posix()
        hashes[relative] = _sha256_file(path)
    return hashes


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ConcurrentRobustnessEvidenceError(f"{label} must be a non-empty string")
    return value


def _strict_int(value: object, label: str) -> int:
    if type(value) is not int:
        raise ConcurrentRobustnessEvidenceError(f"{label} must be a strict integer")
    return value


def _string_mapping(value: object, label: str) -> dict[str, str]:
    if not isinstance(value, dict) or any(
        not isinstance(key, str) or not key or not isinstance(item, str) or not item for key, item in value.items()
    ):
        raise ConcurrentRobustnessEvidenceError(f"{label} must be a non-empty string mapping")
    return dict(value)


def _real_directory(path: Path, label: str) -> Path:
    try:
        absolute = Path(os.path.abspath(path))
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ConcurrentRobustnessEvidenceError(f"{label} does not resolve") from exc
    if absolute != resolved or path.is_symlink() or not resolved.is_dir():
        raise ConcurrentRobustnessEvidenceError(f"{label} must be a real non-symlink directory")
    return resolved


def _repo_directory(root: Path, path: Path, label: str) -> Path:
    candidate = path if path.is_absolute() else root / path
    resolved = _real_directory(candidate, label)
    if not resolved.is_relative_to(root):
        raise ConcurrentRobustnessEvidenceError(f"{label} escapes the repository")
    return resolved


def _repo_file(root: Path, path: Path, label: str) -> Path:
    candidate = path if path.is_absolute() else root / path
    try:
        absolute = Path(os.path.abspath(candidate))
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ConcurrentRobustnessEvidenceError(f"{label} does not resolve") from exc
    if absolute != resolved or candidate.is_symlink() or not resolved.is_file() or not resolved.is_relative_to(root):
        raise ConcurrentRobustnessEvidenceError(f"{label} must be a real repository file")
    return resolved


def _new_repo_path(root: Path, path: Path, label: str) -> Path:
    candidate = path if path.is_absolute() else root / path
    absolute = Path(os.path.abspath(candidate))
    resolved = candidate.resolve(strict=False)
    if absolute != resolved or not resolved.is_relative_to(root) or ".." in path.parts:
        raise ConcurrentRobustnessEvidenceError(f"{label} must be a safe repository path")
    if os.path.lexists(resolved):
        raise ConcurrentRobustnessEvidenceError(f"{label} already exists")
    parent = resolved.parent
    while not parent.exists():
        parent = parent.parent
    if parent.is_symlink() or not parent.resolve(strict=True).is_relative_to(root):
        raise ConcurrentRobustnessEvidenceError(f"{label} parent is not safe")
    return resolved


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)
