from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .concurrent_message_report import (
    CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON,
    CONCURRENT_MESSAGE_REPORT_HTML,
)
from .concurrent_robustness_report import _validate_concurrent_robustness_report_candidate
from .concurrent_robustness_study import (
    CONCURRENT_ROBUSTNESS_SUBSCRIPTION_ADAPTER_IDENTITY,
    ConcurrentRobustnessManifest,
    _CellEvidenceDocument,
    _validate_cell_evidence_contract,
    _validate_completed_dynamic_root,
)
from .providers.pi_subscription import PI_SUBSCRIPTION_MODEL_ALIASES

ROBUSTNESS_PRODUCTION_MANIFEST_SCHEMA = "concurrent-robustness-production-release-manifest-v1"
ROBUSTNESS_PRODUCTION_EVIDENCE_SCHEMA = "concurrent-robustness-production-release-evidence-v1"
ROBUSTNESS_RELEASE_CONTRACT_SCHEMA = "abm-report-release-contract-v5"
ROBUSTNESS_CANONICAL_ENDPOINT = "https://abm.q1ngyuan.top/"
ROBUSTNESS_REPORT_PAYLOAD = "concurrent_robustness_report_payload.json"
ROBUSTNESS_CANDIDATE_RELEASE_EVIDENCE = "release_evidence.json"
ROBUSTNESS_VALIDATION_CANDIDATE_MANIFEST = "validation_candidate_artifact_manifest.json"
ROBUSTNESS_VALIDATION_CANDIDATE_EVIDENCE = "validation_candidate_release_evidence.json"
ROBUSTNESS_PRODUCTION_EVIDENCE = "robustness_production_release_evidence.json"
ROBUSTNESS_FORMAL_LOGICAL_JUDGMENTS = 28_800
ROBUSTNESS_FORMAL_PHYSICAL_ATTEMPT_CAP = 86_400

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RELEASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
_COMMIT = re.compile(r"^[0-9a-f]{7,40}$")


class ConcurrentRobustnessReleaseError(ValueError):
    """Raised when Formal evidence cannot be promoted to a production release."""


@dataclass(frozen=True)
class ConcurrentRobustnessProductionRelease:
    source_dir: Path
    contract_path: Path
    release_id: str
    report_sha256: str
    manifest_sha256: str
    release_identity_sha256: str


def promote_concurrent_robustness_release(
    *,
    repo_root: str | Path,
    formal_root: str | Path,
    study_root: str | Path,
    workspace_root: str | Path,
    candidate_dir: str | Path,
    execution_contract_path: str | Path,
    destination_dir: str | Path,
    release_contract_path: str | Path,
    release_id: str,
) -> ConcurrentRobustnessProductionRelease:
    """Validate both immutable lineages, then atomically create a production-only release root."""
    root = _real_directory(Path(repo_root), "repository root")
    formal = _repo_directory(root, Path(formal_root), "historical Formal root")
    study = _repo_directory(root, Path(study_root), "robustness study root")
    workspace = _repo_directory(root, Path(workspace_root), "robustness workspace")
    candidate = _repo_directory(root, Path(candidate_dir), "robustness validation candidate")
    execution_contract_file = _repo_file(root, Path(execution_contract_path), "Formal execution contract")
    destination = _new_repo_path(root, Path(destination_dir), "production release destination")
    contract_path = _new_repo_path(root, Path(release_contract_path), "production release contract")
    if not _RELEASE_ID.fullmatch(release_id):
        raise ConcurrentRobustnessReleaseError("release id is not a bounded stable token")
    protected = (formal, study, workspace, candidate, execution_contract_file.parent)
    if any(_paths_overlap(destination, path) for path in protected):
        raise ConcurrentRobustnessReleaseError("production release destination overlaps immutable input evidence")
    if contract_path == destination or contract_path.is_relative_to(destination):
        raise ConcurrentRobustnessReleaseError("release contract must be outside the production source directory")

    manifest_path = study / "study_manifest.json"
    manifest_payload = manifest_path.read_bytes()
    manifest_sha256 = _sha256_bytes(manifest_payload)
    try:
        manifest_document = json.loads(manifest_payload)
        manifest = ConcurrentRobustnessManifest.model_validate(manifest_document)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ConcurrentRobustnessReleaseError("Formal study manifest is invalid") from exc
    if manifest.dynamic_execution is None:
        raise ConcurrentRobustnessReleaseError("production release requires dynamic Formal execution evidence")
    execution = manifest.dynamic_execution
    if (
        execution.profile != "formal_live"
        or execution.adapter_identity != CONCURRENT_ROBUSTNESS_SUBSCRIPTION_ADAPTER_IDENTITY
        or execution.authorization.production_deploy_eligible is not False
        or execution.authorization.external_requests_allowed is not True
        or manifest.request_caps.logical_judgment_cap != ROBUSTNESS_FORMAL_LOGICAL_JUDGMENTS
        or manifest.request_caps.physical_attempt_cap != ROBUSTNESS_FORMAL_PHYSICAL_ATTEMPT_CAP
        or manifest.request_caps.fee_ceiling_usd != 0.0
    ):
        raise ConcurrentRobustnessReleaseError("study manifest is not the approved subscription-backed Formal profile")
    observed = {
        cell.requested_model: cell.required_observed_model
        for cell in manifest.prompt_model_cells
    }
    if observed != PI_SUBSCRIPTION_MODEL_ALIASES:
        raise ConcurrentRobustnessReleaseError("Formal study model aliases are crossed with qualification")
    if Path(manifest.source.source_dir).resolve(strict=True) != formal:
        raise ConcurrentRobustnessReleaseError("Formal study source path is crossed")

    _validate_concurrent_robustness_report_candidate(
        formal_root=formal,
        study_root=study,
        workspace_root=workspace,
        manifest=manifest,
        manifest_payload=manifest_payload,
        manifest_sha256=manifest_sha256,
        candidate_dir=candidate,
    )
    candidate_manifest = _json_object(candidate / CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON)
    candidate_evidence = _json_object(candidate / ROBUSTNESS_CANDIDATE_RELEASE_EVIDENCE)
    if (
        candidate_manifest.get("schema_version") != "concurrent-robustness-report-candidate-manifest-v1"
        or candidate_manifest.get("production_deploy_eligible") is not False
        or candidate_evidence.get("schema_version") != "concurrent-robustness-report-release-evidence-v1"
        or candidate_evidence.get("production_deploy_eligible") is not False
    ):
        raise ConcurrentRobustnessReleaseError("validation candidate did not preserve its non-production contract")

    execution_contract = _validate_execution_contract(
        root=root,
        path=execution_contract_file,
        formal=formal,
        study=study,
        workspace=workspace,
        candidate=candidate,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
    )
    cell_evidence = _close_formal_cell_evidence(
        study=study,
        workspace=workspace,
        formal=formal,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
    )
    physical_attempts = cell_evidence.physical_attempt_count
    if (
        cell_evidence.evidence_profile != "formal_live"
        or cell_evidence.cell_count != 16
        or cell_evidence.logical_judgment_count != ROBUSTNESS_FORMAL_LOGICAL_JUDGMENTS
        or cell_evidence.external_request_invocations != physical_attempts
        or cell_evidence.live_api_triggered is not True
        or cell_evidence.production_deploy_eligible is not False
        or not ROBUSTNESS_FORMAL_LOGICAL_JUDGMENTS <= physical_attempts <= ROBUSTNESS_FORMAL_PHYSICAL_ATTEMPT_CAP
    ):
        raise ConcurrentRobustnessReleaseError("Formal cell evidence does not close the approved 16-cell matrix")
    if execution_contract.get("physical_provider_attempts") != physical_attempts:
        raise ConcurrentRobustnessReleaseError("Formal execution contract is crossed with cell attempt accounting")

    candidate_hashes = _flat_file_hashes(candidate)
    candidate_manifest_sha256 = candidate_hashes[CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON]
    candidate_evidence_sha256 = candidate_hashes[ROBUSTNESS_CANDIDATE_RELEASE_EVIDENCE]
    execution_contract_sha256 = _sha256_file(execution_contract_file)
    payloads = _production_payloads(
        candidate=candidate,
        candidate_hashes=candidate_hashes,
        candidate_manifest=candidate_manifest,
        candidate_evidence=candidate_evidence,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        study=study,
        execution_contract=execution_contract,
        execution_contract_sha256=execution_contract_sha256,
        release_id=release_id,
        physical_attempts=physical_attempts,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", suffix=".staging", dir=destination.parent))
    contract_staging = contract_path.with_name(f".{contract_path.name}.{os.getpid()}.staging")
    try:
        for relative_path, payload in payloads.items():
            target = staging / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        _validate_production_release_dir(staging, release_id=release_id)
        release_hashes = _flat_file_hashes(staging)
        contract_document = {
            "schema_version": ROBUSTNESS_RELEASE_CONTRACT_SCHEMA,
            "release_purpose": "concurrent_robustness_formal_research",
            "release_id": release_id,
            "canonical_endpoint": ROBUSTNESS_CANONICAL_ENDPOINT,
            "source_directory": destination.relative_to(root).as_posix(),
            "artifact_manifest_schema_version": ROBUSTNESS_PRODUCTION_MANIFEST_SCHEMA,
            "report_payload_schema_version": "concurrent-robustness-report-payload-v1",
            "production_evidence_schema_version": ROBUSTNESS_PRODUCTION_EVIDENCE_SCHEMA,
            "historical_formal_directory": formal.relative_to(root).as_posix(),
            "historical_formal_manifest_sha256": manifest.source.manifest_sha256,
            "study_root_directory": study.relative_to(root).as_posix(),
            "study_manifest_sha256": manifest_sha256,
            "study_artifact_manifest_sha256": _sha256_file(study / "artifact_manifest.json"),
            "workspace_directory": workspace.relative_to(root).as_posix(),
            "validation_candidate_directory": candidate.relative_to(root).as_posix(),
            "validation_candidate_manifest_sha256": candidate_manifest_sha256,
            "validation_candidate_evidence_sha256": candidate_evidence_sha256,
            "formal_execution_contract": execution_contract_file.relative_to(root).as_posix(),
            "formal_execution_contract_sha256": execution_contract_sha256,
            "adapter_identity": CONCURRENT_ROBUSTNESS_SUBSCRIPTION_ADAPTER_IDENTITY,
            "provider_transport": "openai-codex",
            "requested_observed_model_aliases": PI_SUBSCRIPTION_MODEL_ALIASES,
            "logical_judgments": ROBUSTNESS_FORMAL_LOGICAL_JUDGMENTS,
            "physical_attempts": physical_attempts,
            "physical_attempt_cap": ROBUSTNESS_FORMAL_PHYSICAL_ATTEMPT_CAP,
            "subscription_billed_cost_usd": 0.0,
            "production_deploy_eligible": True,
            "artifact_sha256": dict(sorted(release_hashes.items())),
        }
        contract_staging.write_bytes(_json_bytes(contract_document))
        if destination.exists() or contract_path.exists():
            raise ConcurrentRobustnessReleaseError("production release destination or contract appeared during staging")
        os.replace(staging, destination)
        os.replace(contract_staging, contract_path)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if contract_staging.exists():
            contract_staging.unlink(missing_ok=True)
        raise

    _validate_production_release_dir(destination, release_id=release_id)
    final_hashes = _flat_file_hashes(destination)
    if final_hashes != contract_document["artifact_sha256"]:
        raise ConcurrentRobustnessReleaseError("published production release drifted after atomic close")
    release_manifest = _json_object(destination / CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON)
    return ConcurrentRobustnessProductionRelease(
        source_dir=destination,
        contract_path=contract_path,
        release_id=release_id,
        report_sha256=final_hashes[CONCURRENT_MESSAGE_REPORT_HTML],
        manifest_sha256=final_hashes[CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON],
        release_identity_sha256=str(release_manifest["release_identity_sha256"]),
    )


def validate_concurrent_robustness_production_release(
    *,
    repo_root: str | Path,
    contract_document: Mapping[str, object],
    source_dir: str | Path,
    snapshot_dir: str | Path | None = None,
) -> dict[str, object]:
    """Fail-closed validator used by the production deployment gate."""
    root = _real_directory(Path(repo_root), "repository root")
    if contract_document.get("schema_version") != ROBUSTNESS_RELEASE_CONTRACT_SCHEMA:
        raise ConcurrentRobustnessReleaseError("unsupported Concurrent Robustness release contract")
    if set(contract_document) != {
        "schema_version",
        "release_purpose",
        "release_id",
        "canonical_endpoint",
        "source_directory",
        "artifact_manifest_schema_version",
        "report_payload_schema_version",
        "production_evidence_schema_version",
        "historical_formal_directory",
        "historical_formal_manifest_sha256",
        "study_root_directory",
        "study_manifest_sha256",
        "study_artifact_manifest_sha256",
        "workspace_directory",
        "validation_candidate_directory",
        "validation_candidate_manifest_sha256",
        "validation_candidate_evidence_sha256",
        "formal_execution_contract",
        "formal_execution_contract_sha256",
        "adapter_identity",
        "provider_transport",
        "requested_observed_model_aliases",
        "logical_judgments",
        "physical_attempts",
        "physical_attempt_cap",
        "subscription_billed_cost_usd",
        "production_deploy_eligible",
        "artifact_sha256",
    }:
        raise ConcurrentRobustnessReleaseError("v5 release contract fields are missing or unexpected")
    release_id = _string(contract_document.get("release_id"), "release id")
    if not _RELEASE_ID.fullmatch(release_id):
        raise ConcurrentRobustnessReleaseError("v5 release id is invalid")
    expected_source = _repo_directory(
        root,
        Path(_string(contract_document.get("source_directory"), "source directory")),
        "contract source directory",
    )
    supplied_source = _real_directory(Path(source_dir), "supplied source directory")
    if supplied_source != expected_source:
        raise ConcurrentRobustnessReleaseError("v5 supplied source directory differs from the frozen contract")
    evidence_dir = expected_source
    if snapshot_dir is not None:
        evidence_dir = _real_directory(Path(snapshot_dir), "release snapshot")
    if (
        contract_document.get("release_purpose") != "concurrent_robustness_formal_research"
        or contract_document.get("canonical_endpoint") != ROBUSTNESS_CANONICAL_ENDPOINT
        or contract_document.get("artifact_manifest_schema_version") != ROBUSTNESS_PRODUCTION_MANIFEST_SCHEMA
        or contract_document.get("report_payload_schema_version") != "concurrent-robustness-report-payload-v1"
        or contract_document.get("production_evidence_schema_version") != ROBUSTNESS_PRODUCTION_EVIDENCE_SCHEMA
        or contract_document.get("adapter_identity") != CONCURRENT_ROBUSTNESS_SUBSCRIPTION_ADAPTER_IDENTITY
        or contract_document.get("provider_transport") != "openai-codex"
        or contract_document.get("requested_observed_model_aliases") != PI_SUBSCRIPTION_MODEL_ALIASES
        or contract_document.get("logical_judgments") != ROBUSTNESS_FORMAL_LOGICAL_JUDGMENTS
        or contract_document.get("physical_attempt_cap") != ROBUSTNESS_FORMAL_PHYSICAL_ATTEMPT_CAP
        or contract_document.get("subscription_billed_cost_usd") != 0.0
        or contract_document.get("production_deploy_eligible") is not True
    ):
        raise ConcurrentRobustnessReleaseError("v5 release contract is not the approved production profile")
    physical_attempts = _strict_int(contract_document.get("physical_attempts"), "physical attempts")
    if not ROBUSTNESS_FORMAL_LOGICAL_JUDGMENTS <= physical_attempts <= ROBUSTNESS_FORMAL_PHYSICAL_ATTEMPT_CAP:
        raise ConcurrentRobustnessReleaseError("v5 physical attempt count is outside the approved cap")
    expected_hashes = _string_mapping(contract_document.get("artifact_sha256"), "artifact SHA-256")
    actual_hashes = _flat_file_hashes(evidence_dir)
    if actual_hashes != expected_hashes:
        raise ConcurrentRobustnessReleaseError("v5 source inventory or artifact hashes differ from the contract")
    _validate_production_release_dir(evidence_dir, release_id=release_id)

    formal = _repo_directory(
        root,
        Path(_string(contract_document.get("historical_formal_directory"), "historical Formal directory")),
        "historical Formal directory",
    )
    study = _repo_directory(
        root,
        Path(_string(contract_document.get("study_root_directory"), "study root directory")),
        "study root directory",
    )
    workspace = _repo_directory(
        root,
        Path(_string(contract_document.get("workspace_directory"), "workspace directory")),
        "workspace directory",
    )
    candidate = _repo_directory(
        root,
        Path(_string(contract_document.get("validation_candidate_directory"), "validation candidate directory")),
        "validation candidate directory",
    )
    execution_contract_file = _repo_file(
        root,
        Path(_string(contract_document.get("formal_execution_contract"), "Formal execution contract")),
        "Formal execution contract",
    )
    for path, key in (
        (study / "study_manifest.json", "study_manifest_sha256"),
        (study / "artifact_manifest.json", "study_artifact_manifest_sha256"),
        (candidate / CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON, "validation_candidate_manifest_sha256"),
        (candidate / ROBUSTNESS_CANDIDATE_RELEASE_EVIDENCE, "validation_candidate_evidence_sha256"),
        (execution_contract_file, "formal_execution_contract_sha256"),
    ):
        if _sha256_file(path) != contract_document.get(key):
            raise ConcurrentRobustnessReleaseError(f"v5 external lineage hash is crossed: {key}")
    manifest_payload = (study / "study_manifest.json").read_bytes()
    manifest = ConcurrentRobustnessManifest.model_validate_json(manifest_payload)
    if manifest.source.manifest_sha256 != contract_document.get("historical_formal_manifest_sha256"):
        raise ConcurrentRobustnessReleaseError("v5 historical Formal manifest lineage is crossed")
    _validate_concurrent_robustness_report_candidate(
        formal_root=formal,
        study_root=study,
        workspace_root=workspace,
        manifest=manifest,
        manifest_payload=manifest_payload,
        manifest_sha256=_sha256_bytes(manifest_payload),
        candidate_dir=candidate,
    )
    execution_contract = _validate_execution_contract(
        root=root,
        path=execution_contract_file,
        formal=formal,
        study=study,
        workspace=workspace,
        candidate=candidate,
        manifest=manifest,
        manifest_sha256=_sha256_bytes(manifest_payload),
    )
    cell_evidence = _close_formal_cell_evidence(
        study=study,
        workspace=workspace,
        formal=formal,
        manifest=manifest,
        manifest_sha256=_sha256_bytes(manifest_payload),
    )
    if (
        cell_evidence.logical_judgment_count != ROBUSTNESS_FORMAL_LOGICAL_JUDGMENTS
        or cell_evidence.physical_attempt_count != physical_attempts
        or execution_contract.get("physical_provider_attempts") != physical_attempts
        or execution_contract.get("subscription_billed_cost_usd") != 0.0
    ):
        raise ConcurrentRobustnessReleaseError("v5 execution evidence is crossed with the release contract")
    return {
        "schema_version": ROBUSTNESS_RELEASE_CONTRACT_SCHEMA,
        "release_purpose": "concurrent_robustness_formal_research",
        "release_id": release_id,
        "source_directory": contract_document["source_directory"],
        "sampling_method": "seed_first_research_sample_v1",
        "sampling_status": "persisted_seed_first_formal_run",
        "decision_execution_mode": "live_provider",
        "logical_judgments": ROBUSTNESS_FORMAL_LOGICAL_JUDGMENTS,
        "physical_attempts": physical_attempts,
        "report_sha256": actual_hashes[CONCURRENT_MESSAGE_REPORT_HTML],
        "artifact_count": len(actual_hashes),
        "production_deploy_eligible": True,
    }


def _close_formal_cell_evidence(
    *,
    study: Path,
    workspace: Path,
    formal: Path,
    manifest: ConcurrentRobustnessManifest,
    manifest_sha256: str,
) -> _CellEvidenceDocument:
    try:
        evidence = _CellEvidenceDocument.model_validate(
            _json_object(study / "prompt_model_cell_evidence.json")
        )
        _validate_cell_evidence_contract(
            evidence,
            manifest=manifest,
            manifest_sha256=manifest_sha256,
        )
        _validate_completed_dynamic_root(
            manifest=manifest,
            manifest_sha256=manifest_sha256,
            output_path=workspace,
            source_path=formal,
            evidence=evidence,
        )
        return evidence
    except (OSError, TypeError, ValueError) as exc:
        raise ConcurrentRobustnessReleaseError(
            "Formal cell rows or durable journals failed independent closure"
        ) from exc


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
        "formal_runner_sha256",
        "subscription_worker_sha256",
        "subscription_client_sha256",
        "completion_status",
        "logical_provider_attempts",
        "physical_provider_attempts",
        "subscription_nominal_reference_cost_usd",
        "subscription_billed_cost_usd",
        "subscription_billing_evidence",
    }
    if not required.issubset(document):
        raise ConcurrentRobustnessReleaseError("Formal execution contract is incomplete")
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
        or document.get("logical_provider_attempts") != ROBUSTNESS_FORMAL_LOGICAL_JUDGMENTS
        or document.get("subscription_billed_cost_usd") != 0.0
        or document.get("subscription_billing_evidence") != "openai-codex OAuth subscription transport"
        or not isinstance(document.get("subscription_nominal_reference_cost_usd"), (int, float))
        or float(document["subscription_nominal_reference_cost_usd"]) < 0.0
        or not _COMMIT.fullmatch(_string(document.get("implementation_commit"), "implementation commit"))
    ):
        raise ConcurrentRobustnessReleaseError("Formal execution contract is crossed or incomplete")
    physical_attempts = _strict_int(document.get("physical_provider_attempts"), "physical provider attempts")
    if not ROBUSTNESS_FORMAL_LOGICAL_JUDGMENTS <= physical_attempts <= ROBUSTNESS_FORMAL_PHYSICAL_ATTEMPT_CAP:
        raise ConcurrentRobustnessReleaseError("Formal execution physical attempts exceed the approved contract")
    for key in ("formal_runner_sha256", "subscription_worker_sha256", "subscription_client_sha256"):
        if not _SHA256.fullmatch(_string(document.get(key), key)):
            raise ConcurrentRobustnessReleaseError(f"Formal execution {key} is invalid")

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
        raise ConcurrentRobustnessReleaseError("model qualification artifact header is invalid")
    row_by_model: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            raise ConcurrentRobustnessReleaseError("model qualification row is invalid")
        row = dict(raw)
        recorded = row.pop("evidence_sha256", None)
        if recorded != _sha256_bytes(_json_bytes(row)):
            raise ConcurrentRobustnessReleaseError("model qualification row hash is crossed")
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
            raise ConcurrentRobustnessReleaseError("model qualification row contract is crossed")
        row_by_model[requested] = raw
    if row_by_model.keys() != PI_SUBSCRIPTION_MODEL_ALIASES.keys():
        raise ConcurrentRobustnessReleaseError("qualification does not cover the exact four requested models")
    execution = manifest.dynamic_execution
    assert execution is not None
    for record in execution.qualifications:
        row = row_by_model.get(record.requested_model)
        if (
            row is None
            or record.artifact_sha256 != row.get("evidence_sha256")
            or record.required_observed_model != row.get("observed_model")
            or record.artifact_reference != f"{qualification.resolve()}#{record.requested_model}"
        ):
            raise ConcurrentRobustnessReleaseError("manifest qualification reference is crossed")

    authorization_document = _json_object(authorization)
    authorization_evidence = dict(authorization_document)
    authorization_sha256 = authorization_evidence.pop("evidence_sha256", None)
    if (
        authorization_sha256 != _sha256_bytes(_json_bytes(authorization_evidence))
        or authorization_sha256 != execution.authorization.artifact_sha256
        or authorization_document.get("provider_transport") != "openai-codex"
        or authorization_document.get("subscription_billing") is not True
        or authorization_document.get("logical_judgment_cap") != ROBUSTNESS_FORMAL_LOGICAL_JUDGMENTS
        or authorization_document.get("physical_attempt_cap") != ROBUSTNESS_FORMAL_PHYSICAL_ATTEMPT_CAP
        or authorization_document.get("fee_ceiling_usd") != 0.0
        or authorization_document.get("external_requests_allowed") is not True
    ):
        raise ConcurrentRobustnessReleaseError("execution authorization artifact is crossed")
    pricing_document = _json_object(pricing)
    pricing_evidence = dict(pricing_document)
    pricing_sha256 = pricing_evidence.pop("evidence_sha256", None)
    if (
        pricing_sha256 != _sha256_bytes(_json_bytes(pricing_evidence))
        or pricing_sha256 != execution.pricing_snapshot.snapshot_sha256
        or pricing_document.get("provider_transport") != "openai-codex"
        or pricing_document.get("billing_mode") != "subscription"
        or any(
            not isinstance(row, dict)
            or row.get("input_usd_per_million_tokens") != 0.0
            or row.get("output_usd_per_million_tokens") != 0.0
            for row in pricing_document.get("model_pricing", [])
        )
    ):
        raise ConcurrentRobustnessReleaseError("subscription pricing artifact is crossed")
    return document


def _production_payloads(
    *,
    candidate: Path,
    candidate_hashes: Mapping[str, str],
    candidate_manifest: Mapping[str, Any],
    candidate_evidence: Mapping[str, Any],
    manifest: ConcurrentRobustnessManifest,
    manifest_sha256: str,
    study: Path,
    execution_contract: Mapping[str, Any],
    execution_contract_sha256: str,
    release_id: str,
    physical_attempts: int,
) -> dict[str, bytes]:
    payloads: dict[str, bytes] = {}
    for relative_path in sorted(candidate_hashes):
        if relative_path in {
            CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON,
            ROBUSTNESS_CANDIDATE_RELEASE_EVIDENCE,
            CONCURRENT_MESSAGE_REPORT_HTML,
            ROBUSTNESS_REPORT_PAYLOAD,
        }:
            continue
        payloads[relative_path] = (candidate / relative_path).read_bytes()
    payloads[ROBUSTNESS_VALIDATION_CANDIDATE_MANIFEST] = (candidate / CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON).read_bytes()
    payloads[ROBUSTNESS_VALIDATION_CANDIDATE_EVIDENCE] = (
        candidate / ROBUSTNESS_CANDIDATE_RELEASE_EVIDENCE
    ).read_bytes()

    report_payload = _json_object(candidate / ROBUSTNESS_REPORT_PAYLOAD)
    if report_payload.get("production_deploy_eligible") is not False:
        raise ConcurrentRobustnessReleaseError("candidate report payload is not a validation-only artifact")
    report_payload["production_deploy_eligible"] = True
    report_payload["production_release"] = {
        "schema_version": ROBUSTNESS_PRODUCTION_EVIDENCE_SCHEMA,
        "release_id": release_id,
        "canonical_endpoint": ROBUSTNESS_CANONICAL_ENDPOINT,
        "formal_logical_judgments": ROBUSTNESS_FORMAL_LOGICAL_JUDGMENTS,
        "formal_physical_attempts": physical_attempts,
        "provider_transport": "openai-codex",
        "subscription_billed_cost_usd": 0.0,
    }
    payloads[ROBUSTNESS_REPORT_PAYLOAD] = _json_bytes(report_payload)

    report_html = (candidate / CONCURRENT_MESSAGE_REPORT_HTML).read_text(encoding="utf-8")
    if report_html.count("production_deploy_eligible=false") != 1:
        raise ConcurrentRobustnessReleaseError("candidate report has an ambiguous production marker")
    report_html = report_html.replace("production_deploy_eligible=false", "production_deploy_eligible=true")
    report_html = report_html.replace(
        'data-testid="robustness-report-candidate"',
        'data-testid="robustness-report-release" data-release-id="' + release_id + '"',
        1,
    ).replace("values in this candidate", "values in this production release")
    meta = (
        f'<meta name="abm-release-contract" content="{ROBUSTNESS_RELEASE_CONTRACT_SCHEMA}">'
        f'<meta name="abm-release-id" content="{release_id}">'
    )
    if report_html.count("</head>") != 1:
        raise ConcurrentRobustnessReleaseError("candidate report has an invalid head boundary")
    report_html = report_html.replace("</head>", meta + "</head>", 1)
    payloads[CONCURRENT_MESSAGE_REPORT_HTML] = report_html.encode("utf-8")

    production_evidence = {
        "schema_version": ROBUSTNESS_PRODUCTION_EVIDENCE_SCHEMA,
        "release_id": release_id,
        "canonical_endpoint": ROBUSTNESS_CANONICAL_ENDPOINT,
        "formal_source_manifest_sha256": manifest.source.manifest_sha256,
        "study_manifest_sha256": manifest_sha256,
        "study_artifact_manifest_sha256": _sha256_file(study / "artifact_manifest.json"),
        "study_root_identity_sha256": _string(
            _json_object(study / "artifact_manifest.json").get("root_identity_sha256"),
            "study root identity",
        ),
        "validation_candidate_manifest_sha256": candidate_hashes[CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON],
        "validation_candidate_evidence_sha256": candidate_hashes[ROBUSTNESS_CANDIDATE_RELEASE_EVIDENCE],
        "validation_candidate_content_identity_sha256": candidate_evidence["candidate_content_identity_sha256"],
        "formal_execution_contract_sha256": execution_contract_sha256,
        "formal_implementation_commit": execution_contract["implementation_commit"],
        "adapter_identity": CONCURRENT_ROBUSTNESS_SUBSCRIPTION_ADAPTER_IDENTITY,
        "provider_transport": "openai-codex",
        "requested_observed_model_aliases": PI_SUBSCRIPTION_MODEL_ALIASES,
        "logical_judgments": ROBUSTNESS_FORMAL_LOGICAL_JUDGMENTS,
        "physical_attempts": physical_attempts,
        "physical_attempt_cap": ROBUSTNESS_FORMAL_PHYSICAL_ATTEMPT_CAP,
        "subscription_nominal_reference_cost_usd": execution_contract[
            "subscription_nominal_reference_cost_usd"
        ],
        "subscription_billed_cost_usd": 0.0,
        "provider_calls_during_promotion": 0,
        "validation_candidate_preserved": True,
        "production_deploy_eligible": True,
    }
    payloads[ROBUSTNESS_PRODUCTION_EVIDENCE] = _json_bytes(production_evidence)
    content_hashes = {path: _sha256_bytes(payload) for path, payload in payloads.items()}
    artifact_mapping = {
        _logical_name(path): path
        for path in sorted(content_hashes)
    }
    if len(artifact_mapping) != len(content_hashes):
        raise ConcurrentRobustnessReleaseError("production release artifact logical names collide")
    release_identity = _sha256_bytes(_json_bytes(dict(sorted(content_hashes.items()))))
    production_manifest = {
        "schema_version": ROBUSTNESS_PRODUCTION_MANIFEST_SCHEMA,
        "release_type": "concurrent_robustness_formal_research",
        "release_id": release_id,
        "canonical_endpoint": ROBUSTNESS_CANONICAL_ENDPOINT,
        "report_schema": "concurrent-robustness-report-payload-v1",
        "production_evidence_schema": ROBUSTNESS_PRODUCTION_EVIDENCE_SCHEMA,
        "formal_source": candidate_manifest["formal_source"],
        "study_source": candidate_manifest["study_source"],
        "validation_candidate": {
            "manifest_sha256": candidate_hashes[CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON],
            "release_evidence_sha256": candidate_hashes[ROBUSTNESS_CANDIDATE_RELEASE_EVIDENCE],
            "candidate_identity_sha256": candidate_manifest["candidate_identity_sha256"],
            "production_deploy_eligible": False,
        },
        "formal_execution": {
            "contract_sha256": execution_contract_sha256,
            "logical_judgments": ROBUSTNESS_FORMAL_LOGICAL_JUDGMENTS,
            "physical_attempts": physical_attempts,
            "subscription_billed_cost_usd": 0.0,
        },
        "artifacts": dict(sorted(artifact_mapping.items())),
        "sha256": {
            name: content_hashes[path]
            for name, path in sorted(artifact_mapping.items())
        },
        "release_identity_sha256": release_identity,
        "approved_downloads": report_payload["downloads"],
        "production_deploy_eligible": True,
    }
    payloads[CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON] = _json_bytes(production_manifest)
    return payloads


def _validate_production_release_dir(source: Path, *, release_id: str) -> None:
    if source.is_symlink() or not source.is_dir():
        raise ConcurrentRobustnessReleaseError("production release source is not a real directory")
    hashes = _flat_file_hashes(source)
    manifest = _json_object(source / CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON)
    evidence = _json_object(source / ROBUSTNESS_PRODUCTION_EVIDENCE)
    payload = _json_object(source / ROBUSTNESS_REPORT_PAYLOAD)
    if (
        manifest.get("schema_version") != ROBUSTNESS_PRODUCTION_MANIFEST_SCHEMA
        or manifest.get("release_type") != "concurrent_robustness_formal_research"
        or manifest.get("release_id") != release_id
        or manifest.get("canonical_endpoint") != ROBUSTNESS_CANONICAL_ENDPOINT
        or manifest.get("production_deploy_eligible") is not True
        or evidence.get("schema_version") != ROBUSTNESS_PRODUCTION_EVIDENCE_SCHEMA
        or evidence.get("release_id") != release_id
        or evidence.get("production_deploy_eligible") is not True
        or evidence.get("provider_calls_during_promotion") != 0
        or evidence.get("subscription_billed_cost_usd") != 0.0
        or payload.get("schema_version") != "concurrent-robustness-report-payload-v1"
        or payload.get("production_deploy_eligible") is not True
    ):
        raise ConcurrentRobustnessReleaseError("production release schema or eligibility contract is invalid")
    artifacts = _string_mapping(manifest.get("artifacts"), "production artifacts")
    declared_hashes = _string_mapping(manifest.get("sha256"), "production artifact hashes")
    if set(artifacts) != set(declared_hashes) or len(set(artifacts.values())) != len(artifacts):
        raise ConcurrentRobustnessReleaseError("production artifact inventory is crossed")
    if set(artifacts.values()) != set(hashes) - {CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON}:
        raise ConcurrentRobustnessReleaseError("production artifact inventory is incomplete")
    for name, relative_path in artifacts.items():
        if declared_hashes[name] != hashes[relative_path]:
            raise ConcurrentRobustnessReleaseError("production artifact hash mismatch")
    identity_rows = dict(sorted((path, hashes[path]) for path in artifacts.values()))
    if manifest.get("release_identity_sha256") != _sha256_bytes(_json_bytes(identity_rows)):
        raise ConcurrentRobustnessReleaseError("production release identity is crossed")
    if hashes[ROBUSTNESS_VALIDATION_CANDIDATE_MANIFEST] != evidence.get(
        "validation_candidate_manifest_sha256"
    ) or hashes[ROBUSTNESS_VALIDATION_CANDIDATE_EVIDENCE] != evidence.get(
        "validation_candidate_evidence_sha256"
    ):
        raise ConcurrentRobustnessReleaseError("preserved validation candidate evidence is crossed")
    candidate_manifest = _json_object(source / ROBUSTNESS_VALIDATION_CANDIDATE_MANIFEST)
    candidate_evidence = _json_object(source / ROBUSTNESS_VALIDATION_CANDIDATE_EVIDENCE)
    if (
        candidate_manifest.get("production_deploy_eligible") is not False
        or candidate_evidence.get("production_deploy_eligible") is not False
    ):
        raise ConcurrentRobustnessReleaseError("validation candidate eligibility was mutated during promotion")
    html = (source / CONCURRENT_MESSAGE_REPORT_HTML).read_text(encoding="utf-8")
    required = (
        'data-testid="mechanism-overview-section"',
        'data-testid="run-evidence-mode-panel"',
        'data-testid="run-trace-lineage-data"',
        'data-testid="robustness-report-release"',
        'data-testid="robustness-source-lineage"',
        'data-testid="ranking-weight-sensitivity-section"',
        'data-testid="prompt-model-robustness-section"',
        'data-testid="robustness-production-eligibility">production_deploy_eligible=true',
        "Demographic Shadow evidence remains bound to the historical Formal source",
        f'<meta name="abm-release-id" content="{release_id}">',
    )
    if any(marker not in html for marker in required) or "production_deploy_eligible=false" in html:
        raise ConcurrentRobustnessReleaseError("production report is missing a required release or lineage marker")
    if re.search(r"<(?:script|link|img)\b[^>]*(?:src|href)=[\"']https?://", html, re.IGNORECASE):
        raise ConcurrentRobustnessReleaseError("production report requests an external resource")


def _logical_name(relative_path: str) -> str:
    return Path(relative_path).stem.replace("-", "_")


def _json_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")


def _json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConcurrentRobustnessReleaseError(f"cannot read valid JSON evidence: {path.name}") from exc
    if not isinstance(value, dict):
        raise ConcurrentRobustnessReleaseError(f"JSON evidence must be an object: {path.name}")
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
            raise ConcurrentRobustnessReleaseError("release evidence contains a symlink or non-regular entry")
        relative = path.relative_to(root).as_posix()
        hashes[relative] = _sha256_file(path)
    return hashes


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ConcurrentRobustnessReleaseError(f"{label} must be a non-empty string")
    return value


def _strict_int(value: object, label: str) -> int:
    if type(value) is not int:
        raise ConcurrentRobustnessReleaseError(f"{label} must be a strict integer")
    return value


def _string_mapping(value: object, label: str) -> dict[str, str]:
    if not isinstance(value, dict) or any(
        not isinstance(key, str) or not key or not isinstance(item, str) or not item
        for key, item in value.items()
    ):
        raise ConcurrentRobustnessReleaseError(f"{label} must be a non-empty string mapping")
    return dict(value)


def _real_directory(path: Path, label: str) -> Path:
    try:
        absolute = Path(os.path.abspath(path))
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ConcurrentRobustnessReleaseError(f"{label} does not resolve") from exc
    if absolute != resolved or path.is_symlink() or not resolved.is_dir():
        raise ConcurrentRobustnessReleaseError(f"{label} must be a real non-symlink directory")
    return resolved


def _repo_directory(root: Path, path: Path, label: str) -> Path:
    candidate = path if path.is_absolute() else root / path
    resolved = _real_directory(candidate, label)
    if not resolved.is_relative_to(root):
        raise ConcurrentRobustnessReleaseError(f"{label} escapes the repository")
    return resolved


def _repo_file(root: Path, path: Path, label: str) -> Path:
    candidate = path if path.is_absolute() else root / path
    try:
        absolute = Path(os.path.abspath(candidate))
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ConcurrentRobustnessReleaseError(f"{label} does not resolve") from exc
    if absolute != resolved or candidate.is_symlink() or not resolved.is_file() or not resolved.is_relative_to(root):
        raise ConcurrentRobustnessReleaseError(f"{label} must be a real repository file")
    return resolved


def _new_repo_path(root: Path, path: Path, label: str) -> Path:
    candidate = path if path.is_absolute() else root / path
    absolute = Path(os.path.abspath(candidate))
    resolved = candidate.resolve(strict=False)
    if absolute != resolved or not resolved.is_relative_to(root) or ".." in path.parts:
        raise ConcurrentRobustnessReleaseError(f"{label} must be a safe repository path")
    if os.path.lexists(resolved):
        raise ConcurrentRobustnessReleaseError(f"{label} already exists")
    parent = resolved.parent
    while not parent.exists():
        parent = parent.parent
    if parent.is_symlink() or not parent.resolve(strict=True).is_relative_to(root):
        raise ConcurrentRobustnessReleaseError(f"{label} parent is not safe")
    return resolved


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)
