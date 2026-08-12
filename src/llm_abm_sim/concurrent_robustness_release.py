from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from . import concurrent_robustness_evidence as _evidence
from .concurrent_message_report import (
    CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON,
    CONCURRENT_MESSAGE_REPORT_HTML,
)
from .concurrent_robustness_evidence import (
    ConcurrentRobustnessEvidenceError,
    PresentationClosureFacts,
)
from .concurrent_robustness_report import (
    _REPORT_PRESENTATION,
    _PresentationBundle,
    _ProductionPresentationFacts,
)
from .concurrent_robustness_study import (
    CONCURRENT_ROBUSTNESS_SUBSCRIPTION_ADAPTER_IDENTITY,
    ConcurrentRobustnessManifest,
)
from .providers.pi_subscription import PI_SUBSCRIPTION_MODEL_ALIASES

ROBUSTNESS_PRODUCTION_MANIFEST_SCHEMA = "concurrent-robustness-production-release-manifest-v1"
ROBUSTNESS_PRODUCTION_EVIDENCE_SCHEMA = "concurrent-robustness-production-release-evidence-v1"
ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V5 = "abm-report-release-contract-v5"
ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V6 = "abm-report-release-contract-v6"
ROBUSTNESS_RELEASE_CONTRACT_SCHEMA = ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V5
ROBUSTNESS_PRESENTATION_CLOSURE_CONTRACT = "presentation_closure_contract.json"
ROBUSTNESS_CANONICAL_ENDPOINT = "https://abm.q1ngyuan.top/"
ROBUSTNESS_REPORT_PAYLOAD = "concurrent_robustness_report_payload.json"
ROBUSTNESS_CANDIDATE_RELEASE_EVIDENCE = "release_evidence.json"
ROBUSTNESS_VALIDATION_CANDIDATE_MANIFEST = "validation_candidate_artifact_manifest.json"
ROBUSTNESS_VALIDATION_CANDIDATE_EVIDENCE = "validation_candidate_release_evidence.json"
ROBUSTNESS_PRODUCTION_EVIDENCE = "robustness_production_release_evidence.json"
ROBUSTNESS_FORMAL_LOGICAL_JUDGMENTS = _evidence.FORMAL_LOGICAL_JUDGMENTS
ROBUSTNESS_FORMAL_PHYSICAL_ATTEMPT_CAP = _evidence.FORMAL_PHYSICAL_ATTEMPT_CAP

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RELEASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
_COMMIT = re.compile(r"^[0-9a-f]{7,40}$")


class ConcurrentRobustnessReleaseError(ValueError):
    """Raised when Formal evidence cannot be promoted to a production release."""


# These package-internal compatibility seams preserve v5's test and caller
# injection points while the evidence implementation lives in Evidence Module.
_CellEvidenceDocument = _evidence._CellEvidenceDocument
_validate_cell_evidence_contract = _evidence._validate_cell_evidence_contract
_validate_completed_dynamic_root = _evidence._validate_completed_dynamic_root


def _validate_execution_contract(**kwargs: object) -> dict[str, Any]:
    try:
        return _evidence._validate_execution_contract(**kwargs)
    except ConcurrentRobustnessEvidenceError as exc:
        raise ConcurrentRobustnessReleaseError(str(exc)) from exc


def _close_formal_cell_evidence(**kwargs: object) -> Any:
    try:
        return _evidence.close_formal_cell_evidence(
            evidence_model=_CellEvidenceDocument,
            cell_validator=_validate_cell_evidence_contract,
            dynamic_validator=_validate_completed_dynamic_root,
            **kwargs,
        )
    except ConcurrentRobustnessEvidenceError as exc:
        raise ConcurrentRobustnessReleaseError(str(exc)) from exc


def _validate_candidate_release_contract(**kwargs: object) -> None:
    try:
        _evidence._validate_candidate_release_contract(**kwargs)
    except ConcurrentRobustnessEvidenceError as exc:
        raise ConcurrentRobustnessReleaseError(str(exc)) from exc


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
    presentation_closure_path: str | Path | None = None,
) -> ConcurrentRobustnessProductionRelease:
    """Validate both immutable lineages, then atomically create a production-only release root."""
    root = _real_directory(Path(repo_root), "repository root")
    formal = _repo_directory(root, Path(formal_root), "historical Formal root")
    study = _repo_directory(root, Path(study_root), "robustness study root")
    workspace = _repo_directory(root, Path(workspace_root), "robustness workspace")
    candidate = _repo_directory(root, Path(candidate_dir), "robustness validation candidate")
    execution_contract_file = _repo_file(root, Path(execution_contract_path), "Formal execution contract")
    presentation_closure_file = (
        _repo_file(root, Path(presentation_closure_path), "presentation closure contract")
        if presentation_closure_path is not None
        else None
    )
    destination = _new_repo_path(root, Path(destination_dir), "production release destination")
    contract_path = _new_repo_path(root, Path(release_contract_path), "production release contract")
    if not _RELEASE_ID.fullmatch(release_id):
        raise ConcurrentRobustnessReleaseError("release id is not a bounded stable token")
    protected = (formal, study, workspace, candidate, execution_contract_file.parent)
    if presentation_closure_file is not None:
        protected = (*protected, presentation_closure_file)
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
    observed = {cell.requested_model: cell.required_observed_model for cell in manifest.prompt_model_cells}
    if observed != PI_SUBSCRIPTION_MODEL_ALIASES:
        raise ConcurrentRobustnessReleaseError("Formal study model aliases are crossed with qualification")
    if Path(manifest.source.source_dir).resolve(strict=True) != formal:
        raise ConcurrentRobustnessReleaseError("Formal study source path is crossed")

    closure_facts: PresentationClosureFacts | None = None
    if presentation_closure_file is not None:
        try:
            closure_facts = _evidence.validate_presentation_closure(
                repo_root=root,
                closure_path=presentation_closure_file,
                formal_root=formal,
                study_root=study,
                workspace_root=workspace,
                candidate_dir=candidate,
                execution_contract_path=execution_contract_file,
            )
        except ConcurrentRobustnessEvidenceError as exc:
            raise ConcurrentRobustnessReleaseError(str(exc)) from exc

    candidate_manifest = _json_object(candidate / CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON)
    candidate_evidence = _json_object(candidate / ROBUSTNESS_CANDIDATE_RELEASE_EVIDENCE)
    candidate_report_payload = _json_object(candidate / ROBUSTNESS_REPORT_PAYLOAD)
    _validate_candidate_release_contract(
        candidate=candidate,
        candidate_manifest=candidate_manifest,
        candidate_evidence=candidate_evidence,
        candidate_report_payload=candidate_report_payload,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        formal=formal,
        study=study,
    )

    formal_candidate = closure_facts.old_candidate_path if closure_facts is not None else candidate
    execution_contract = _validate_execution_contract(
        root=root,
        path=execution_contract_file,
        formal=formal,
        study=study,
        workspace=workspace,
        candidate=formal_candidate,
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
    approved_downloads = _production_approved_downloads(candidate_report_payload)
    selected_release_schema = (
        ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V6 if closure_facts is not None else ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V5
    )
    presentation_closure_bytes = None
    if presentation_closure_file is not None and closure_facts is not None:
        presentation_closure_bytes = presentation_closure_file.read_bytes()
        if _sha256_bytes(presentation_closure_bytes) != closure_facts.closure_sha256:
            raise ConcurrentRobustnessReleaseError("presentation closure changed during promotion")
    stage_facts = _production_presentation_facts(
        release_id=release_id,
        physical_attempts=physical_attempts,
        approved_downloads=approved_downloads,
        release_contract_schema=selected_release_schema,
    )
    presentation = _materialize_production_presentation(
        formal=formal,
        study=study,
        candidate=candidate,
        stage_facts=stage_facts,
    )
    if _flat_file_hashes(candidate) != candidate_hashes:
        raise ConcurrentRobustnessReleaseError("validation candidate was mutated during presentation materialization")
    payloads = _build_production_release_payloads(
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
        presentation=presentation,
        approved_downloads=approved_downloads,
        presentation_closure=presentation_closure_bytes,
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
        _validate_production_release_dir(staging, stage_facts=stage_facts)
        release_hashes = _flat_file_hashes(staging)
        contract_document = {
            "schema_version": selected_release_schema,
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
            "formal_judgment_implementation_commit": execution_contract["implementation_commit"],
            "formal_closure_implementation_commit": execution_contract["closure_implementation_commit"],
            "formal_closure_replay_sha256": execution_contract["closure_replay_sha256"],
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
        if closure_facts is not None and presentation_closure_file is not None:
            contract_document["presentation_closure_contract"] = presentation_closure_file.relative_to(root).as_posix()
            contract_document["presentation_closure_contract_sha256"] = closure_facts.closure_sha256
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

    _validate_production_release_dir(destination, stage_facts=stage_facts)
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
    schema_version = contract_document.get("schema_version")
    if schema_version not in {
        ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V5,
        ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V6,
    }:
        raise ConcurrentRobustnessReleaseError("unsupported Concurrent Robustness release contract")
    if schema_version == ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V5 and set(contract_document) != {
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
        "formal_judgment_implementation_commit",
        "formal_closure_implementation_commit",
        "formal_closure_replay_sha256",
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
    if schema_version == ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V6:
        v6_fields = {
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
            "formal_judgment_implementation_commit",
            "formal_closure_implementation_commit",
            "formal_closure_replay_sha256",
            "adapter_identity",
            "provider_transport",
            "requested_observed_model_aliases",
            "logical_judgments",
            "physical_attempts",
            "physical_attempt_cap",
            "subscription_billed_cost_usd",
            "production_deploy_eligible",
            "artifact_sha256",
            "presentation_closure_contract",
            "presentation_closure_contract_sha256",
        }
        if set(contract_document) != v6_fields:
            raise ConcurrentRobustnessReleaseError("v6 release contract fields are missing or unexpected")
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
        or not _COMMIT.fullmatch(
            _string(
                contract_document.get("formal_judgment_implementation_commit"),
                "Formal judgment implementation commit",
            )
        )
        or not _COMMIT.fullmatch(
            _string(
                contract_document.get("formal_closure_implementation_commit"),
                "Formal closure implementation commit",
            )
        )
        or not _SHA256.fullmatch(
            _string(contract_document.get("formal_closure_replay_sha256"), "Formal closure replay SHA-256")
        )
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
    if schema_version == ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V6:
        if actual_hashes.get(ROBUSTNESS_PRESENTATION_CLOSURE_CONTRACT) != contract_document.get(
            "presentation_closure_contract_sha256"
        ):
            raise ConcurrentRobustnessReleaseError("v6 release closure artifact hash is crossed")
    production_manifest = _json_object(evidence_dir / CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON)
    stage_facts = _production_presentation_facts(
        release_id=release_id,
        physical_attempts=physical_attempts,
        approved_downloads=_string_mapping(
            production_manifest.get("approved_downloads"),
            "production approved downloads",
        ),
        release_contract_schema=str(schema_version),
    )
    _validate_production_release_dir(evidence_dir, stage_facts=stage_facts)

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
    closure_file: Path | None = None
    if schema_version == ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V6:
        closure_file = _repo_file(
            root,
            Path(
                _canonical_relative_path(
                    contract_document.get("presentation_closure_contract"),
                    "presentation closure contract",
                )
            ),
            "presentation closure contract",
        )
        if _sha256_file(closure_file) != contract_document.get("presentation_closure_contract_sha256"):
            raise ConcurrentRobustnessReleaseError("v6 presentation closure contract hash is crossed")
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
    candidate_manifest = _json_object(candidate / CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON)
    candidate_evidence = _json_object(candidate / ROBUSTNESS_CANDIDATE_RELEASE_EVIDENCE)
    candidate_report_payload = _json_object(candidate / ROBUSTNESS_REPORT_PAYLOAD)
    _validate_candidate_release_contract(
        candidate=candidate,
        candidate_manifest=candidate_manifest,
        candidate_evidence=candidate_evidence,
        candidate_report_payload=candidate_report_payload,
        manifest=manifest,
        manifest_sha256=_sha256_bytes(manifest_payload),
        formal=formal,
        study=study,
    )
    formal_candidate = candidate
    if closure_file is not None:
        try:
            closure_facts = _evidence.validate_presentation_closure(
                repo_root=root,
                closure_path=closure_file,
                formal_root=formal,
                study_root=study,
                workspace_root=workspace,
                candidate_dir=candidate,
                execution_contract_path=execution_contract_file,
            )
            formal_candidate = closure_facts.old_candidate_path
        except ConcurrentRobustnessEvidenceError as exc:
            raise ConcurrentRobustnessReleaseError(str(exc)) from exc
    expected_presentation = _materialize_production_presentation(
        formal=formal,
        study=study,
        candidate=candidate,
        stage_facts=stage_facts,
    )
    if (
        expected_presentation.report_payload != (evidence_dir / ROBUSTNESS_REPORT_PAYLOAD).read_bytes()
        or expected_presentation.report_html != (evidence_dir / CONCURRENT_MESSAGE_REPORT_HTML).read_bytes()
    ):
        raise ConcurrentRobustnessReleaseError(
            "production presentation differs from the Report materialization contract"
        )
    execution_contract = _validate_execution_contract(
        root=root,
        path=execution_contract_file,
        formal=formal,
        study=study,
        workspace=workspace,
        candidate=formal_candidate,
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
        or contract_document.get("formal_judgment_implementation_commit")
        != execution_contract.get("implementation_commit")
        or contract_document.get("formal_closure_implementation_commit")
        != execution_contract.get("closure_implementation_commit")
        or contract_document.get("formal_closure_replay_sha256") != execution_contract.get("closure_replay_sha256")
        or execution_contract.get("physical_provider_attempts") != physical_attempts
        or execution_contract.get("subscription_billed_cost_usd") != 0.0
    ):
        raise ConcurrentRobustnessReleaseError("v5 execution evidence is crossed with the release contract")
    return {
        "schema_version": schema_version,
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


def _production_approved_downloads(candidate_report_payload: Mapping[str, Any]) -> dict[str, str]:
    downloads = _string_mapping(candidate_report_payload.get("downloads"), "candidate report downloads")
    if downloads.get("release_evidence") != ROBUSTNESS_CANDIDATE_RELEASE_EVIDENCE:
        raise ConcurrentRobustnessReleaseError("candidate release-evidence download mapping is crossed")
    approved_downloads = dict(downloads)
    approved_downloads["release_evidence"] = ROBUSTNESS_PRODUCTION_EVIDENCE
    if len(set(approved_downloads.values())) != len(approved_downloads):
        raise ConcurrentRobustnessReleaseError("production approved downloads are not one-to-one")
    return approved_downloads


def _production_presentation_facts(
    *,
    release_id: str,
    physical_attempts: int,
    approved_downloads: Mapping[str, str],
    release_contract_schema: str = ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V5,
) -> _ProductionPresentationFacts:
    return _ProductionPresentationFacts(
        release_id=release_id,
        release_contract_schema=release_contract_schema,
        canonical_endpoint=ROBUSTNESS_CANONICAL_ENDPOINT,
        production_evidence_schema=ROBUSTNESS_PRODUCTION_EVIDENCE_SCHEMA,
        formal_logical_judgments=ROBUSTNESS_FORMAL_LOGICAL_JUDGMENTS,
        formal_physical_attempts=physical_attempts,
        provider_transport="openai-codex",
        subscription_billed_cost_usd=0.0,
        approved_downloads=dict(approved_downloads),
    )


def _materialize_production_presentation(
    *,
    formal: Path,
    study: Path,
    candidate: Path,
    stage_facts: _ProductionPresentationFacts,
) -> _PresentationBundle:
    try:
        bundle = _REPORT_PRESENTATION.materialize_production(
            formal_root=formal,
            study_root=study,
            candidate_dir=candidate,
            stage_facts=stage_facts,
        )
        if not isinstance(bundle, _PresentationBundle):
            raise TypeError("Report materialization returned an invalid bundle")
        return bundle
    except (OSError, TypeError, ValueError) as exc:
        raise ConcurrentRobustnessReleaseError("Report production presentation failed closure") from exc


def _validate_production_presentation(
    bundle: _PresentationBundle,
    *,
    stage_facts: _ProductionPresentationFacts,
) -> None:
    try:
        _REPORT_PRESENTATION.validate_bundle(bundle, stage_facts=stage_facts)
    except (OSError, TypeError, ValueError) as exc:
        raise ConcurrentRobustnessReleaseError("Report production presentation failed validation") from exc


def _build_production_release_payloads(
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
    presentation: _PresentationBundle,
    approved_downloads: Mapping[str, str],
    presentation_closure: bytes | None = None,
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
    payloads[ROBUSTNESS_VALIDATION_CANDIDATE_MANIFEST] = (
        candidate / CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON
    ).read_bytes()
    payloads[ROBUSTNESS_VALIDATION_CANDIDATE_EVIDENCE] = (
        candidate / ROBUSTNESS_CANDIDATE_RELEASE_EVIDENCE
    ).read_bytes()

    payloads[ROBUSTNESS_REPORT_PAYLOAD] = presentation.report_payload
    payloads[CONCURRENT_MESSAGE_REPORT_HTML] = presentation.report_html
    if presentation_closure is not None:
        payloads[ROBUSTNESS_PRESENTATION_CLOSURE_CONTRACT] = presentation_closure

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
        "formal_judgment_implementation_commit": execution_contract["implementation_commit"],
        "formal_closure_implementation_commit": execution_contract["closure_implementation_commit"],
        "formal_closure_replay_sha256": execution_contract["closure_replay_sha256"],
        "adapter_identity": CONCURRENT_ROBUSTNESS_SUBSCRIPTION_ADAPTER_IDENTITY,
        "provider_transport": "openai-codex",
        "requested_observed_model_aliases": PI_SUBSCRIPTION_MODEL_ALIASES,
        "logical_judgments": ROBUSTNESS_FORMAL_LOGICAL_JUDGMENTS,
        "physical_attempts": physical_attempts,
        "physical_attempt_cap": ROBUSTNESS_FORMAL_PHYSICAL_ATTEMPT_CAP,
        "subscription_nominal_reference_cost_usd": execution_contract["subscription_nominal_reference_cost_usd"],
        "subscription_billed_cost_usd": 0.0,
        "provider_calls_during_promotion": 0,
        "validation_candidate_preserved": True,
        "production_deploy_eligible": True,
    }
    payloads[ROBUSTNESS_PRODUCTION_EVIDENCE] = _json_bytes(production_evidence)
    content_hashes = {path: _sha256_bytes(payload) for path, payload in payloads.items()}
    artifact_mapping = {_logical_name(path): path for path in sorted(content_hashes)}
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
            "judgment_implementation_commit": execution_contract["implementation_commit"],
            "closure_implementation_commit": execution_contract["closure_implementation_commit"],
            "closure_replay_sha256": execution_contract["closure_replay_sha256"],
            "logical_judgments": ROBUSTNESS_FORMAL_LOGICAL_JUDGMENTS,
            "physical_attempts": physical_attempts,
            "subscription_billed_cost_usd": 0.0,
        },
        "artifacts": dict(sorted(artifact_mapping.items())),
        "sha256": {name: content_hashes[path] for name, path in sorted(artifact_mapping.items())},
        "release_identity_sha256": release_identity,
        "approved_downloads": dict(approved_downloads),
        "production_deploy_eligible": True,
    }
    payloads[CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON] = _json_bytes(production_manifest)
    return payloads


def _validate_production_release_dir(
    source: Path,
    *,
    stage_facts: _ProductionPresentationFacts,
) -> None:
    release_id = stage_facts.release_id
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
    ) or hashes[ROBUSTNESS_VALIDATION_CANDIDATE_EVIDENCE] != evidence.get("validation_candidate_evidence_sha256"):
        raise ConcurrentRobustnessReleaseError("preserved validation candidate evidence is crossed")
    candidate_manifest = _json_object(source / ROBUSTNESS_VALIDATION_CANDIDATE_MANIFEST)
    candidate_evidence = _json_object(source / ROBUSTNESS_VALIDATION_CANDIDATE_EVIDENCE)
    if (
        candidate_manifest.get("production_deploy_eligible") is not False
        or candidate_evidence.get("production_deploy_eligible") is not False
    ):
        raise ConcurrentRobustnessReleaseError("validation candidate eligibility was mutated during promotion")
    _validate_production_downloads(
        source,
        payload=payload,
        manifest=manifest,
        artifacts=artifacts,
    )
    _validate_production_presentation(
        _PresentationBundle(
            report_payload=(source / ROBUSTNESS_REPORT_PAYLOAD).read_bytes(),
            report_html=(source / CONCURRENT_MESSAGE_REPORT_HTML).read_bytes(),
        ),
        stage_facts=stage_facts,
    )


def _validate_production_downloads(
    source: Path,
    *,
    payload: Mapping[str, Any],
    manifest: Mapping[str, Any],
    artifacts: Mapping[str, str],
) -> None:
    payload_downloads = _string_mapping(payload.get("downloads"), "production payload downloads")
    approved_downloads = _string_mapping(
        manifest.get("approved_downloads"),
        "production approved downloads",
    )
    if payload_downloads != approved_downloads:
        raise ConcurrentRobustnessReleaseError("production payload and manifest approved downloads are crossed")
    if len(set(approved_downloads.values())) != len(approved_downloads):
        raise ConcurrentRobustnessReleaseError("production approved downloads are not one-to-one")
    if (
        approved_downloads.get("release_evidence") != ROBUSTNESS_PRODUCTION_EVIDENCE
        or ROBUSTNESS_VALIDATION_CANDIDATE_EVIDENCE in approved_downloads.values()
        or ROBUSTNESS_CANDIDATE_RELEASE_EVIDENCE in approved_downloads.values()
    ):
        raise ConcurrentRobustnessReleaseError(
            "production release-evidence download is crossed with validation candidate evidence"
        )

    inventory = set(artifacts.values()) | {CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON}
    for relative_path in approved_downloads.values():
        path = PurePosixPath(relative_path)
        if (
            "\\" in relative_path
            or path.is_absolute()
            or path.as_posix() != relative_path
            or ".." in path.parts
            or relative_path not in inventory
        ):
            raise ConcurrentRobustnessReleaseError(
                "production approved download escapes or is absent from the artifact inventory"
            )
        target = source / relative_path
        if target.is_symlink() or not target.is_file():
            raise ConcurrentRobustnessReleaseError("production approved download is missing or is not a regular file")


def _logical_name(relative_path: str) -> str:
    path = Path(relative_path)
    stem = path.stem.replace("-", "_")
    suffix = path.suffix.removeprefix(".").replace("-", "_")
    return f"{stem}_{suffix}" if suffix else stem


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


def _canonical_relative_path(value: object, label: str) -> str:
    relative = _string(value, label)
    path = PurePosixPath(relative)
    if "\\" in relative or path.is_absolute() or path.as_posix() != relative or "." in path.parts or ".." in path.parts:
        raise ConcurrentRobustnessReleaseError(f"{label} must be a canonical repository-relative path")
    return relative


def _string_mapping(value: object, label: str) -> dict[str, str]:
    if not isinstance(value, dict) or any(
        not isinstance(key, str) or not key or not isinstance(item, str) or not item for key, item in value.items()
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
