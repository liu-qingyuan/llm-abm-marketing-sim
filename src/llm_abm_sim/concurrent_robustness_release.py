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
    FullPoolFormalReleaseFacts,
    FullPoolProductionEvidenceFacts,
    NestedFullPoolProductionEvidenceFacts,
    PresentationClosureFacts,
    SegmentedFullPoolProductionEvidenceFacts,
    StrictFullPoolProductionEvidenceFacts,
)
from .concurrent_robustness_report import (
    _REPORT_PRESENTATION,
    _FullPoolProductionPresentationFacts,
    _PresentationBundle,
    _ProductionPresentationFacts,
)
from .concurrent_robustness_study import (
    CONCURRENT_ROBUSTNESS_SUBSCRIPTION_ADAPTER_IDENTITY,
    ConcurrentRobustnessManifest,
)
from .final_research import FULL_POOL_MEMBERSHIP_METHOD
from .full_pool_presentation import (
    _FULL_POOL_MASTER,
    _HISTORICAL_DIR,
    _HISTORICAL_MERMAID_FILENAMES,
)
from .full_pool_segmented_continuation import (
    SegmentedFullPoolSourceFacts,
    _segmented_recovery_accounting_document,
    _segmented_recovery_lineage_document,
)
from .full_pool_strict_operator import (
    StrictFreshExecutionManifestFacts,
    validate_strict_fresh_execution_manifest,
)
from .providers.pi_subscription import PI_SUBSCRIPTION_MODEL_ALIASES

ROBUSTNESS_PRODUCTION_MANIFEST_SCHEMA = "concurrent-robustness-production-release-manifest-v1"
ROBUSTNESS_PRODUCTION_EVIDENCE_SCHEMA = "concurrent-robustness-production-release-evidence-v1"
ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V5 = "abm-report-release-contract-v5"
ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V6 = "abm-report-release-contract-v6"
ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V7 = "abm-report-release-contract-v7"
ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V8 = "abm-report-release-contract-v8"
ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V9 = "abm-report-release-contract-v9"
ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V10 = "abm-report-release-contract-v10"
ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V11 = "abm-report-release-contract-v11"
ROBUSTNESS_RELEASE_CONTRACT_SCHEMA = ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V5
ROBUSTNESS_PRESENTATION_CLOSURE_CONTRACT = "presentation_closure_contract.json"
FULL_POOL_PRODUCTION_MANIFEST_SCHEMA = "full-pool-production-release-manifest-v1"
FULL_POOL_PRODUCTION_EVIDENCE_SCHEMA = "full-pool-production-release-evidence-v1"
FULL_POOL_PRODUCTION_IDENTITY_SCHEMA = "full-pool-production-release-identity-v1"
FULL_POOL_PRESENTATION_CLOSURE_ARTIFACT = "full_pool_presentation_closure.json"
FULL_POOL_CANDIDATE_MANIFEST_ARTIFACT = "full_pool_candidate_artifact_manifest.json"
FULL_POOL_CANDIDATE_EVIDENCE_ARTIFACT = "full_pool_candidate_release_evidence.json"
FULL_POOL_PRODUCTION_EVIDENCE_ARTIFACT = "full_pool_production_release_evidence.json"
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
_REPORT_PAYLOAD_SCHEMA_V1 = "concurrent-robustness-report-payload-v1"
_REPORT_PAYLOAD_SCHEMA_V2 = "concurrent-robustness-report-payload-v2"
_RELEASE_CONTRACT_V5_FIELDS = frozenset(
    {
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
    }
)
_RELEASE_CONTRACT_V6_FIELDS = _RELEASE_CONTRACT_V5_FIELDS | {
    "presentation_closure_contract",
    "presentation_closure_contract_sha256",
}
_RELEASE_CONTRACT_V7_FIELDS = _RELEASE_CONTRACT_V6_FIELDS | {
    "presentation_closure_schema_version",
    "semantic_set_identity_sha256",
}
_RELEASE_CONTRACT_V8_FIELDS = frozenset(
    {
        "schema_version",
        "release_purpose",
        "release_id",
        "canonical_endpoint",
        "source_directory",
        "artifact_manifest_schema_version",
        "report_payload_schema_version",
        "production_evidence_schema_version",
        "implementation_commit",
        "full_pool_source_directory",
        "full_pool_source_identity",
        "full_pool_source_manifest_sha256",
        "full_pool_source_hash",
        "full_pool_contract_sha256",
        "historical_formal_directory",
        "historical_formal_source_id",
        "historical_formal_manifest_sha256",
        "historical_study_directory",
        "historical_study_manifest_sha256",
        "historical_study_artifact_manifest_sha256",
        "historical_study_root_identity_sha256",
        "candidate_directory",
        "candidate_manifest_sha256",
        "candidate_identity_sha256",
        "candidate_content_identity_sha256",
        "presentation_closure_contract",
        "presentation_closure_contract_sha256",
        "presentation_closure_schema_version",
        "source_lineage_identity_sha256",
        "presentation_inventory_identity_sha256",
        "mechanism_set_identity_sha256",
        "trace_index_sha256",
        "full_pool_formal_facts",
        "historical_formal_facts",
        "historical_study_facts",
        "release_identity_sha256",
        "production_deploy_eligible",
        "artifact_sha256",
    }
)
_RELEASE_CONTRACT_V9_FIELDS = _RELEASE_CONTRACT_V8_FIELDS | {
    "segmented_source_facts",
    "physical_snapshot_identity_sha256",
}
_RELEASE_CONTRACT_V9_RECOVERY_FIELDS = _RELEASE_CONTRACT_V9_FIELDS | {
    "recovery_lineage_facts",
    "recovery_accounting_facts",
}
_RELEASE_CONTRACT_V10_FIELDS = _RELEASE_CONTRACT_V8_FIELDS | {
    "automation_execution_manifest",
    "automation_execution_manifest_sha256",
    "automation_execution_manifest_identity_sha256",
    "automation_execution_manifest_facts",
    "nested_source_facts",
    "nested_recovery_lineage_facts",
    "automated_recovery_policy_facts",
    "settlement_v2_facts",
    "recovery_accounting_facts",
    "result_projection_facts",
    "physical_snapshot_identity_sha256",
}
_RELEASE_CONTRACT_V11_FIELDS = _RELEASE_CONTRACT_V8_FIELDS | {
    "fresh_execution_manifest",
    "fresh_execution_manifest_sha256",
    "fresh_execution_manifest_identity_sha256",
    "fresh_execution_manifest_facts",
    "strict_source_facts",
    "strict_fresh_lineage_facts",
    "strict_policy_facts",
    "strict_settlement_facts",
    "operator_attempt_facts",
    "physical_accounting_facts",
    "result_projection_facts",
    "rejected_mixed_history_facts",
    "execution_handoff",
    "physical_snapshot_identity_sha256",
}
_SEGMENTED_SOURCE_FACT_FIELDS = frozenset(
    {
        "source_schema_version",
        "cutoff_manifest_sha256",
        "continuation_identity_hash",
        "prefix_identity_hash",
        "formal_execution_contract_sha256",
        "authorization_artifact_sha256",
        "qualification_artifact_sha256",
        "concurrency_qualification_artifact_sha256",
        "observed_model_evidence_sha256",
        "prompt_variant_id",
        "prompt_version",
        "prompt_canonical_hash",
        "execution_topology",
        "serial_prefix_terminal_count",
        "concurrent_suffix_terminal_count",
        "max_concurrency",
        "logical_judgments",
        "physical_attempts",
        "migration_unknown_physical_charge",
        "unknown_pair_count",
        "reconciliation_retry_count",
        "source_artifact_sha256",
    }
)
_RECOVERY_LINEAGE_FACT_FIELDS = frozenset(
    {
        "failed_v1_run_identity_hash",
        "failed_continuation_identity_hash",
        "failed_continuation_ledger_sha256",
        "recovery_plan_sha256",
        "recovery_plan_identity_hash",
        "human_authorization_sha256",
        "qualification_artifact_sha256",
        "recovery_identity_hash",
        "unresolved_pairs",
        "configured_max_concurrency",
        "failed_artifact_sha256",
    }
)
_RECOVERY_ACCOUNTING_FACT_FIELDS = frozenset(
    {
        "logical_cap",
        "historical_logical_count",
        "logical_retry_charge",
        "fresh_logical_count",
        "logical_count",
        "physical_cap",
        "historical_physical_attempts",
        "uncertainty_physical_charge",
        "retry_actual_physical_attempts",
        "continuation_actual_physical_attempts",
        "aggregate_physical_attempts",
    }
)
_FULL_POOL_FORMAL_FACT_FIELDS = frozenset(
    {
        "source_schema_version",
        "evidence_profile",
        "provider_transport",
        "adapter_identity",
        "requested_model",
        "qualified_observed_model",
        "distinct_users",
        "eligible_pairs",
        "exposures",
        "primary_terminals",
        "committed_batches",
        "candidate_ranking_rows",
        "campaign_exposure_coverage",
        "provider_failed_terminals",
        "logical_judgments",
        "physical_attempts",
        "physical_attempt_cap",
        "provider_responses",
        "successful_decisions",
        "external_request_invocations",
        "observed_model_counts",
        "usage_complete_response_count",
        "usage_missing_response_count",
        "usage_malformed_response_count",
        "subscription_billed_cost_usd",
        "live_api_triggered",
        "source_production_deploy_eligible",
    }
)
_HISTORICAL_FORMAL_FACT_FIELDS = frozenset(
    {
        "source_kind",
        "distinct_users",
        "exposures",
        "primary_terminals",
        "shadow_terminals",
        "trace_rows",
    }
)
_HISTORICAL_STUDY_FACT_FIELDS = frozenset(
    {
        "profile",
        "evidence_profile",
        "cell_count",
        "logical_judgments",
    }
)
_FULL_POOL_PRODUCTION_EVIDENCE_FIELDS = frozenset(
    {
        "schema_version",
        "release_id",
        "canonical_endpoint",
        "implementation_commit",
        "full_pool_source",
        "historical_formal_source",
        "historical_study_source",
        "candidate",
        "presentation_closure",
        "source_lineage_identity_sha256",
        "presentation_inventory_identity_sha256",
        "mechanism_set_identity_sha256",
        "trace_index_sha256",
        "full_pool_formal_facts",
        "historical_formal_facts",
        "historical_study_facts",
        "provider_calls_during_promotion",
        "image_generation_triggered",
        "canonical_deployment_triggered",
        "production_deploy_eligible",
    }
)
_FULL_POOL_PRODUCTION_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "release_type",
        "release_id",
        "canonical_endpoint",
        "report_schema",
        "production_evidence_schema",
        "implementation_commit",
        "full_pool_source",
        "historical_formal_source",
        "historical_study_source",
        "candidate",
        "presentation_closure",
        "source_lineage_identity_sha256",
        "presentation_inventory_identity_sha256",
        "mechanism_set_identity_sha256",
        "trace_index_sha256",
        "full_pool_formal_facts",
        "historical_formal_facts",
        "historical_study_facts",
        "artifacts",
        "approved_downloads",
        "release_identity_sha256",
        "provider_calls_during_promotion",
        "production_deploy_eligible",
    }
)
_FULL_POOL_RELEASE_IDENTITY_FIELDS = frozenset(
    {
        "schema_version",
        "release_id",
        "implementation_commit",
        "full_pool_source",
        "historical_formal_source",
        "historical_study_source",
        "candidate",
        "presentation_closure",
        "report_payload_schema_version",
        "source_lineage_identity_sha256",
        "presentation_inventory_identity_sha256",
        "mechanism_set_identity_sha256",
        "trace_index_sha256",
        "artifact_sha256",
    }
)
_ARTIFACT_RECORD_FIELDS = frozenset({"relative_path", "sha256", "bytes"})
_RELEASE_CONTRACT_FIELDS = {
    ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V5: _RELEASE_CONTRACT_V5_FIELDS,
    ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V6: _RELEASE_CONTRACT_V6_FIELDS,
    ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V7: _RELEASE_CONTRACT_V7_FIELDS,
    ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V8: _RELEASE_CONTRACT_V8_FIELDS,
    ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V9: _RELEASE_CONTRACT_V9_FIELDS,
    ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V10: _RELEASE_CONTRACT_V10_FIELDS,
    ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V11: _RELEASE_CONTRACT_V11_FIELDS,
}
_V7_MERMAID_INVENTORY = frozenset(_evidence._SEMANTIC_MERMAID_DOWNLOADS.values())
_V8_MERMAID_INVENTORY = frozenset(
    {
        _FULL_POOL_MASTER,
        *(f"{_HISTORICAL_DIR}/{name}" for name in _HISTORICAL_MERMAID_FILENAMES),
    }
)
_V7_EXCLUDED_PRESENTATION_ARTIFACTS = frozenset(
    {
        "project-evidence-chain.mmd",
        "mechanism-image-generation-audit.json",
    }
)


class ConcurrentRobustnessReleaseError(ValueError):
    """Raised when Formal evidence cannot be promoted to a production release."""


# These package-internal compatibility seams preserve v5's test and caller
# injection points while the evidence implementation lives in Evidence Module.
_CellEvidenceDocument = _evidence._CellEvidenceDocument
_validate_cell_evidence_contract = _evidence._validate_cell_evidence_contract
_validate_completed_dynamic_root = _evidence._validate_completed_dynamic_root


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
    try:
        return _evidence._validate_execution_contract(
            root=root,
            path=path,
            formal=formal,
            study=study,
            workspace=workspace,
            candidate=candidate,
            manifest=manifest,
            manifest_sha256=manifest_sha256,
        )
    except ConcurrentRobustnessEvidenceError as exc:
        raise ConcurrentRobustnessReleaseError(str(exc)) from exc


def _close_formal_cell_evidence(
    *,
    study: Path,
    workspace: Path,
    formal: Path,
    manifest: ConcurrentRobustnessManifest,
    manifest_sha256: str,
) -> Any:
    try:
        return _evidence.close_formal_cell_evidence(
            study=study,
            workspace=workspace,
            formal=formal,
            manifest=manifest,
            manifest_sha256=manifest_sha256,
            evidence_model=_CellEvidenceDocument,
            cell_validator=_validate_cell_evidence_contract,
            dynamic_validator=_validate_completed_dynamic_root,
        )
    except ConcurrentRobustnessEvidenceError as exc:
        raise ConcurrentRobustnessReleaseError(str(exc)) from exc


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
    try:
        _evidence._validate_candidate_release_contract(
            candidate=candidate,
            candidate_manifest=candidate_manifest,
            candidate_evidence=candidate_evidence,
            candidate_report_payload=candidate_report_payload,
            manifest=manifest,
            manifest_sha256=manifest_sha256,
            formal=formal,
            study=study,
        )
    except ConcurrentRobustnessEvidenceError as exc:
        raise ConcurrentRobustnessReleaseError(str(exc)) from exc


def _validate_production_report_payload_contract(
    *,
    source: Path,
    payload: Mapping[str, Any],
) -> str:
    try:
        schema, _semantic_identity = _evidence._validate_report_payload_contract(
            payload,
            candidate=source,
            production=True,
        )
        return schema
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
    workspace_root: str | Path | None = None,
    candidate_dir: str | Path,
    execution_contract_path: str | Path | None = None,
    destination_dir: str | Path,
    release_contract_path: str | Path,
    release_id: str,
    presentation_closure_path: str | Path | None = None,
    full_pool_source_root: str | Path | None = None,
    full_pool_manifest_sha256: str | None = None,
    implementation_commit: str | None = None,
    automation_execution_manifest_path: str | Path | None = None,
    fresh_execution_manifest_path: str | Path | None = None,
    _closed_full_pool_formal_facts: FullPoolFormalReleaseFacts | None = None,
) -> ConcurrentRobustnessProductionRelease:
    """Dispatch one explicit legacy or Full-Pool promotion through the sole Release Seam."""
    full_pool_values = (
        full_pool_source_root,
        full_pool_manifest_sha256,
        implementation_commit,
        automation_execution_manifest_path,
        fresh_execution_manifest_path,
        _closed_full_pool_formal_facts,
    )
    if any(value is not None for value in full_pool_values):
        if (
            any(value is None for value in full_pool_values[:3])
            or presentation_closure_path is None
            or workspace_root is not None
            or execution_contract_path is not None
        ):
            raise ConcurrentRobustnessReleaseError(
                "versioned Full-Pool promotion requires only explicit source, historical, candidate, closure, and release inputs"
            )
        assert full_pool_source_root is not None
        assert full_pool_manifest_sha256 is not None
        assert implementation_commit is not None
        source_path = Path(full_pool_source_root)
        if not source_path.is_absolute():
            source_path = Path(repo_root) / source_path
        try:
            source_schema = _json_object(source_path / "manifest.json").get("schema_version")
        except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ConcurrentRobustnessReleaseError(
                "Full-Pool source manifest cannot be version-dispatched"
            ) from exc
        if source_schema == "full-pool-segmented-source-v4":
            if (
                _closed_full_pool_formal_facts is not None
                or automation_execution_manifest_path is not None
                or fresh_execution_manifest_path is None
            ):
                raise ConcurrentRobustnessReleaseError(
                    "v11 production promotion requires persisted source-v4 and fresh manifest facts and rejects injected Formal facts"
                )
            return _promote_full_pool_v11_release(
                repo_root=repo_root,
                full_pool_source_root=full_pool_source_root,
                full_pool_manifest_sha256=full_pool_manifest_sha256,
                historical_formal_root=formal_root,
                historical_study_root=study_root,
                candidate_dir=candidate_dir,
                presentation_closure_path=presentation_closure_path,
                fresh_execution_manifest_path=fresh_execution_manifest_path,
                destination_dir=destination_dir,
                release_contract_path=release_contract_path,
                release_id=release_id,
                implementation_commit=implementation_commit,
            )
        if source_schema == "full-pool-segmented-source-v3":
            if (
                _closed_full_pool_formal_facts is not None
                or automation_execution_manifest_path is None
                or fresh_execution_manifest_path is not None
            ):
                raise ConcurrentRobustnessReleaseError(
                    "v10 production promotion requires a persisted automation manifest and rejects injected Formal facts"
                )
            return _promote_full_pool_v10_release(
                repo_root=repo_root,
                full_pool_source_root=full_pool_source_root,
                full_pool_manifest_sha256=full_pool_manifest_sha256,
                historical_formal_root=formal_root,
                historical_study_root=study_root,
                candidate_dir=candidate_dir,
                presentation_closure_path=presentation_closure_path,
                automation_execution_manifest_path=automation_execution_manifest_path,
                destination_dir=destination_dir,
                release_contract_path=release_contract_path,
                release_id=release_id,
                implementation_commit=implementation_commit,
            )
        if source_schema == "full-pool-segmented-source-v2":
            if (
                _closed_full_pool_formal_facts is not None
                or automation_execution_manifest_path is not None
                or fresh_execution_manifest_path is not None
            ):
                raise ConcurrentRobustnessReleaseError(
                    "v9 production promotion cannot accept injected Formal facts or source-v3 automation manifests"
                )
            return _promote_full_pool_v9_release(
                repo_root=repo_root,
                full_pool_source_root=full_pool_source_root,
                full_pool_manifest_sha256=full_pool_manifest_sha256,
                historical_formal_root=formal_root,
                historical_study_root=study_root,
                candidate_dir=candidate_dir,
                presentation_closure_path=presentation_closure_path,
                destination_dir=destination_dir,
                release_contract_path=release_contract_path,
                release_id=release_id,
                implementation_commit=implementation_commit,
            )
        if (
            automation_execution_manifest_path is not None
            or fresh_execution_manifest_path is not None
        ):
            raise ConcurrentRobustnessReleaseError(
                "historical v8 promotion rejects source-v3/v4 execution manifests"
            )
        return _promote_full_pool_v8_release(
            repo_root=repo_root,
            full_pool_source_root=full_pool_source_root,
            full_pool_manifest_sha256=full_pool_manifest_sha256,
            historical_formal_root=formal_root,
            historical_study_root=study_root,
            candidate_dir=candidate_dir,
            presentation_closure_path=presentation_closure_path,
            destination_dir=destination_dir,
            release_contract_path=release_contract_path,
            release_id=release_id,
            implementation_commit=implementation_commit,
            closed_formal_facts=_closed_full_pool_formal_facts,
        )
    if workspace_root is None or execution_contract_path is None:
        raise ConcurrentRobustnessReleaseError(
            "legacy promotion requires explicit workspace and execution contract inputs"
        )
    return _promote_legacy_concurrent_robustness_release(
        repo_root=repo_root,
        formal_root=formal_root,
        study_root=study_root,
        workspace_root=workspace_root,
        candidate_dir=candidate_dir,
        execution_contract_path=execution_contract_path,
        destination_dir=destination_dir,
        release_contract_path=release_contract_path,
        release_id=release_id,
        presentation_closure_path=presentation_closure_path,
    )


def _promote_legacy_concurrent_robustness_release(
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
    """Validate both immutable legacy lineages, then atomically create a production release."""
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
    contract_protected = (formal, study, workspace, candidate, execution_contract_file)
    if presentation_closure_file is not None:
        protected = (*protected, presentation_closure_file)
        contract_protected = (*contract_protected, presentation_closure_file)
    if any(_paths_overlap(destination, path) for path in protected):
        raise ConcurrentRobustnessReleaseError("production release destination overlaps immutable input evidence")
    if any(_paths_overlap(contract_path, path) for path in contract_protected):
        raise ConcurrentRobustnessReleaseError("release contract overlaps immutable input evidence")
    if _paths_overlap(contract_path, destination):
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
    candidate_report_schema = _string(
        candidate_report_payload.get("schema_version"),
        "candidate report payload schema",
    )
    if closure_facts is None:
        if candidate_report_schema != _REPORT_PAYLOAD_SCHEMA_V1:
            raise ConcurrentRobustnessReleaseError("payload v2 requires an exact closure v2 contract")
        selected_release_schema = ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V5
    elif (
        closure_facts.closure_schema_version == _evidence.PRESENTATION_CLOSURE_SCHEMA
        and closure_facts.report_payload_schema_version == _REPORT_PAYLOAD_SCHEMA_V1
        and candidate_report_schema == _REPORT_PAYLOAD_SCHEMA_V1
        and closure_facts.semantic_set_identity_sha256 is None
    ):
        selected_release_schema = ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V6
    elif (
        closure_facts.closure_schema_version == _evidence.PRESENTATION_CLOSURE_V2_SCHEMA
        and closure_facts.report_payload_schema_version == _REPORT_PAYLOAD_SCHEMA_V2
        and candidate_report_schema == _REPORT_PAYLOAD_SCHEMA_V2
        and isinstance(candidate_report_payload.get("mechanism_presentation"), Mapping)
        and closure_facts.semantic_set_identity_sha256
        == candidate_report_payload["mechanism_presentation"].get("semantic_set_identity_sha256")
    ):
        selected_release_schema = ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V7
    else:
        raise ConcurrentRobustnessReleaseError("presentation closure facts are crossed with the report payload")
    if selected_release_schema == ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V7:
        _validate_v7_presentation_inventory(candidate_hashes)
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
        report_payload_schema_version=candidate_report_schema,
        presentation_closure=presentation_closure_bytes,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", suffix=".staging", dir=destination.parent))
    contract_staging = contract_path.with_name(f".{contract_path.name}.{os.getpid()}.staging")
    destination_installed = False
    contract_installed = False
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
            "report_payload_schema_version": candidate_report_schema,
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
        if selected_release_schema == ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V7 and closure_facts is not None:
            contract_document["presentation_closure_schema_version"] = closure_facts.closure_schema_version
            contract_document["semantic_set_identity_sha256"] = closure_facts.semantic_set_identity_sha256
        contract_staging.write_bytes(_json_bytes(contract_document))
        if destination.exists() or contract_path.exists():
            raise ConcurrentRobustnessReleaseError("production release destination or contract appeared during staging")
        os.replace(staging, destination)
        destination_installed = True
        os.replace(contract_staging, contract_path)
        contract_installed = True
        _validate_production_release_dir(destination, stage_facts=stage_facts)
        final_hashes = _flat_file_hashes(destination)
        if final_hashes != contract_document["artifact_sha256"]:
            raise ConcurrentRobustnessReleaseError("published production release drifted after atomic close")
        release_manifest = _json_object(destination / CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if contract_staging.exists():
            contract_staging.unlink(missing_ok=True)
        if contract_installed:
            contract_path.unlink(missing_ok=True)
        if destination_installed:
            shutil.rmtree(destination, ignore_errors=True)
        raise

    return ConcurrentRobustnessProductionRelease(
        source_dir=destination,
        contract_path=contract_path,
        release_id=release_id,
        report_sha256=final_hashes[CONCURRENT_MESSAGE_REPORT_HTML],
        manifest_sha256=final_hashes[CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON],
        release_identity_sha256=str(release_manifest["release_identity_sha256"]),
    )


def _v8_fact_documents(
    facts: FullPoolFormalReleaseFacts,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    full_pool = {
        "source_schema_version": facts.full_pool_source_schema_version,
        "evidence_profile": facts.evidence_profile,
        "provider_transport": facts.provider_transport,
        "adapter_identity": facts.adapter_identity,
        "requested_model": facts.requested_model,
        "qualified_observed_model": facts.qualified_observed_model,
        "distinct_users": facts.distinct_users,
        "eligible_pairs": facts.eligible_pairs,
        "exposures": facts.exposures,
        "primary_terminals": facts.primary_terminals,
        "committed_batches": facts.committed_batches,
        "candidate_ranking_rows": facts.candidate_ranking_rows,
        "campaign_exposure_coverage": facts.campaign_exposure_coverage,
        "provider_failed_terminals": facts.provider_failed_terminals,
        "logical_judgments": facts.logical_judgments,
        "physical_attempts": facts.physical_attempts,
        "physical_attempt_cap": facts.physical_attempt_cap,
        "provider_responses": facts.provider_responses,
        "successful_decisions": facts.successful_decisions,
        "external_request_invocations": facts.external_request_invocations,
        "observed_model_counts": dict(facts.observed_model_counts),
        "usage_complete_response_count": facts.usage_complete_response_count,
        "usage_missing_response_count": facts.usage_missing_response_count,
        "usage_malformed_response_count": facts.usage_malformed_response_count,
        "subscription_billed_cost_usd": facts.subscription_billed_cost_usd,
        "live_api_triggered": facts.live_api_triggered,
        "source_production_deploy_eligible": facts.source_production_deploy_eligible,
    }
    historical_formal = {
        "source_kind": facts.historical_formal_source_kind,
        "distinct_users": facts.historical_formal_users,
        "exposures": facts.historical_formal_exposures,
        "primary_terminals": facts.historical_primary_terminals,
        "shadow_terminals": facts.historical_shadow_terminals,
        "trace_rows": facts.historical_trace_rows,
    }
    historical_study = {
        "profile": facts.historical_study_profile,
        "evidence_profile": facts.historical_study_evidence_profile,
        "cell_count": facts.historical_study_cell_count,
        "logical_judgments": facts.historical_study_logical_judgments,
    }
    if (
        set(full_pool) != _FULL_POOL_FORMAL_FACT_FIELDS
        or set(historical_formal) != _HISTORICAL_FORMAL_FACT_FIELDS
        or set(historical_study) != _HISTORICAL_STUDY_FACT_FIELDS
    ):
        raise ConcurrentRobustnessReleaseError("v8 typed Formal fact fields are crossed")
    return full_pool, historical_formal, historical_study


def _v9_segmented_fact_document(
    facts: SegmentedFullPoolSourceFacts,
) -> dict[str, object]:
    document = {
        "source_schema_version": facts.source_schema_version,
        "cutoff_manifest_sha256": facts.cutoff_manifest_sha256,
        "continuation_identity_hash": facts.continuation_identity_hash,
        "prefix_identity_hash": facts.prefix_identity_hash,
        "formal_execution_contract_sha256": facts.formal_execution_contract_sha256,
        "authorization_artifact_sha256": facts.authorization_artifact_sha256,
        "qualification_artifact_sha256": facts.qualification_artifact_sha256,
        "concurrency_qualification_artifact_sha256": facts.concurrency_qualification_artifact_sha256,
        "observed_model_evidence_sha256": facts.observed_model_evidence_sha256,
        "prompt_variant_id": facts.prompt_variant_id,
        "prompt_version": facts.prompt_version,
        "prompt_canonical_hash": facts.prompt_canonical_hash,
        "execution_topology": "serial_prefix_then_concurrent_suffix",
        "serial_prefix_terminal_count": facts.serial_prefix_terminal_count,
        "concurrent_suffix_terminal_count": facts.concurrent_suffix_terminal_count,
        "max_concurrency": facts.max_concurrency,
        "logical_judgments": facts.logical_judgments,
        "physical_attempts": facts.physical_attempts,
        "migration_unknown_physical_charge": facts.migration_unknown_physical_charge,
        "unknown_pair_count": facts.unknown_pair_count,
        "reconciliation_retry_count": facts.reconciliation_retry_count,
        "source_artifact_sha256": dict(sorted(facts.artifact_hashes.items())),
    }
    if set(document) != _SEGMENTED_SOURCE_FACT_FIELDS:
        raise ConcurrentRobustnessReleaseError("v9 segmented source fact fields are crossed")
    return document


def _v9_recovery_fact_documents(
    facts: SegmentedFullPoolSourceFacts,
) -> tuple[dict[str, object] | None, dict[str, object] | None]:
    if facts.recovery_lineage is None or facts.recovery_accounting is None:
        if facts.recovery_lineage is not None or facts.recovery_accounting is not None:
            raise ConcurrentRobustnessReleaseError(
                "v9 recovery lineage and accounting must close together"
            )
        return None, None
    lineage = _segmented_recovery_lineage_document(facts.recovery_lineage)
    accounting = _segmented_recovery_accounting_document(facts.recovery_accounting)
    if (
        set(lineage) != _RECOVERY_LINEAGE_FACT_FIELDS
        or set(accounting) != _RECOVERY_ACCOUNTING_FACT_FIELDS
    ):
        raise ConcurrentRobustnessReleaseError("v9 recovery fact fields are crossed")
    return lineage, accounting


def _v9_base_evidence(
    evidence: SegmentedFullPoolProductionEvidenceFacts,
) -> FullPoolProductionEvidenceFacts:
    return FullPoolProductionEvidenceFacts(
        closure=evidence.closure,
        formal=evidence.formal,
    )


def _v10_base_evidence(
    evidence: NestedFullPoolProductionEvidenceFacts,
) -> FullPoolProductionEvidenceFacts:
    return FullPoolProductionEvidenceFacts(
        closure=evidence.closure,
        formal=evidence.formal,
    )


def _v10_fact_documents(
    *,
    root: Path,
    evidence: NestedFullPoolProductionEvidenceFacts,
) -> dict[str, object]:
    automated = evidence.automated
    execution = evidence.execution_manifest
    nested_source = {
        "source_schema_version": automated.source_schema_version,
        "source_identity": automated.source_identity,
        "manifest_sha256": automated.source_manifest_sha256,
        "source_hash": automated.source_hash,
        "implementation_commit": automated.implementation_commit,
        "logical_judgments": automated.logical_judgments,
        "physical_attempts": automated.physical_attempts,
        "provider_responses": automated.provider_responses,
        "successful_decisions": automated.successful_decisions,
        "observed_model_counts": dict(sorted(automated.observed_model_counts.items())),
        "usage_complete_response_count": automated.usage_complete_response_count,
        "live_api_triggered": automated.live_api_triggered,
        "production_deploy_eligible": automated.production_deploy_eligible,
    }
    lineage = dict(automated.nested_recovery_lineage)
    policy = {
        "policy_sha256": automated.policy_sha256,
        "policy_ledger_sha256": automated.policy_ledger_sha256,
        "policy_identity_hash": automated.source_identity,
        "ordered_retry_pair_ids": list(automated.ordered_retry_pair_ids),
        "maximum_reconciliations_per_pair": automated.policy_payload.get(
            "maximum_reconciliations_per_pair"
        ),
        "stop_conditions": automated.policy_payload.get("stop_conditions"),
    }
    settlement = dict(automated.settlement_v2)
    accounting = dict(automated.recovery_accounting)
    manifest = {
        "path": execution.manifest_path.relative_to(root).as_posix(),
        "sha256": execution.manifest_sha256,
        "identity_sha256": execution.manifest_identity_sha256,
        "implementation_commit": execution.implementation_commit,
        "nested_recovery_plan_sha256": execution.nested_recovery_plan_sha256,
        "recovery_workspace": execution.recovery_workspace.relative_to(root).as_posix(),
        "ordered_retry_pair_ids": list(execution.ordered_retry_pair_ids),
        "provider_transport": execution.provider_transport,
        "requested_model": execution.requested_model,
        "prompt_variant_id": execution.prompt_variant_id,
        "configured_max_concurrency": execution.configured_max_concurrency,
        "logical_cap": execution.logical_cap,
        "physical_cap": execution.physical_cap,
        "subscription_billed_cost_usd": execution.subscription_billed_cost_usd,
        "provider_calls_during_composition": execution.provider_calls_during_composition,
        "production_deploy_eligible": execution.production_deploy_eligible,
    }
    return {
        "nested_source_facts": nested_source,
        "nested_recovery_lineage_facts": lineage,
        "automated_recovery_policy_facts": policy,
        "settlement_v2_facts": settlement,
        "recovery_accounting_facts": accounting,
        "automation_execution_manifest_facts": manifest,
        "result_projection_facts": dict(evidence.result_projection),
    }


def _v11_execution_handoff(
    *,
    root: Path,
    release_id: str,
    execution: StrictFreshExecutionManifestFacts,
) -> dict[str, object]:
    if not _RELEASE_ID.fullmatch(release_id):
        raise ConcurrentRobustnessReleaseError("v11 execution handoff release id is invalid")
    return {
        "schema_version": "full-pool-v11-execution-handoff-v1",
        "implementation_commit": execution.implementation_commit,
        "fresh_execution_manifest": execution.manifest_path.relative_to(root).as_posix(),
        "fresh_execution_manifest_sha256": execution.manifest_sha256,
        "fresh_execution_manifest_identity_sha256": execution.manifest_identity_sha256,
        "provider_transport": "openai-codex",
        "requested_model": "gpt-5.6-sol",
        "logical_call_budget": execution.replay_request.logical_cap,
        "physical_call_budget": execution.replay_request.physical_cap,
        "fee_budget_usd": 0.0,
        "operator_workspace": str(execution.operator_workspace),
        "runtime_workspace": str(execution.replay_request.workspace),
        "source_v4_directory": str(execution.replay_request.workspace / "source-v4"),
        "release_id": release_id,
        "operational_authorization_issue": 205,
        "operational_authorization_required": True,
        "artifact_does_not_confer_authorization": True,
        "provider_calls_during_composition": 0,
        "deployment_triggered": False,
        "canonical_requests_during_composition": 0,
    }


def compose_strict_full_pool_v11_execution_handoff(
    *,
    repo_root: str | Path,
    fresh_execution_manifest_path: str | Path,
    implementation_commit: str,
    release_id: str,
) -> Mapping[str, object]:
    """Create zero-call handoff facts; this artifact never authorizes live execution."""
    root = _real_directory(Path(repo_root), "repository root")
    manifest = _repo_file(
        root,
        Path(fresh_execution_manifest_path),
        "fresh execution manifest",
    )
    try:
        execution = validate_strict_fresh_execution_manifest(
            manifest,
            require_current_implementation=True,
        )
    except (FileNotFoundError, OSError, TypeError, ValueError) as exc:
        raise ConcurrentRobustnessReleaseError("v11 execution handoff fresh manifest failed exact validation") from exc
    if (
        not _COMMIT.fullmatch(implementation_commit)
        or execution.repo_root != root
        or execution.implementation_commit != implementation_commit
        or execution.provider_calls_during_composition != 0
        or execution.production_deploy_eligible is not False
    ):
        raise ConcurrentRobustnessReleaseError("v11 execution handoff implementation or composition facts are crossed")
    return _v11_execution_handoff(
        root=root,
        release_id=release_id,
        execution=execution,
    )


def _v11_base_evidence(
    evidence: StrictFullPoolProductionEvidenceFacts,
) -> FullPoolProductionEvidenceFacts:
    return FullPoolProductionEvidenceFacts(
        closure=evidence.closure,
        formal=evidence.formal,
    )


def _v11_fact_documents(
    *,
    root: Path,
    release_id: str,
    evidence: StrictFullPoolProductionEvidenceFacts,
) -> dict[str, object]:
    strict = evidence.strict_source
    execution = evidence.execution_manifest
    source_manifest = _json_object(strict.source_root / "manifest.json")
    fresh_lineage = _object_mapping(source_manifest.get("fresh_lineage"), "v11 fresh lineage")
    strict_policy = _object_mapping(source_manifest.get("strict_policy"), "v11 strict policy")
    settlement = _object_mapping(source_manifest.get("settlement_v2"), "v11 settlement")
    physical = _object_mapping(source_manifest.get("physical_accounting"), "v11 physical accounting")
    rejected = _object_mapping(fresh_lineage.get("rejected_history"), "v11 rejected mixed history")
    strict_source = {
        "source_schema_version": "full-pool-segmented-source-v4",
        "source_identity": strict.source_identity,
        "manifest_sha256": strict.source_manifest_sha256,
        "source_hash": strict.source_hash,
        "implementation_commit": strict.implementation_commit,
        "profile": strict.profile,
        "distinct_users": strict.distinct_users,
        "logical_judgments": strict.logical_pairs,
        "committed_batches": strict.committed_batches,
        "candidate_ranking_rows": strict.candidate_rows,
        "provider_failed_final_count": strict.provider_failed_final_count,
        "provider_responses": strict.provider_responses,
        "successful_decisions": strict.successful_decisions,
        "external_request_invocations": strict.external_request_invocations,
        "observed_model_counts": dict(sorted(strict.observed_model_counts.items())),
        "usage_complete_response_count": strict.usage_complete_response_count,
        "usage_missing_response_count": strict.usage_missing_response_count,
        "usage_malformed_response_count": strict.usage_malformed_response_count,
        "charged_physical_attempts": strict.charged_physical_attempts,
        "physical_cap": strict.physical_cap,
        "production_topology": strict.production_topology,
        "production_deploy_eligible": strict.production_deploy_eligible,
    }
    manifest = {
        "path": execution.manifest_path.relative_to(root).as_posix(),
        "sha256": execution.manifest_sha256,
        "identity_sha256": execution.manifest_identity_sha256,
        "implementation_commit": execution.implementation_commit,
        "operator_workspace": str(execution.operator_workspace),
        "runtime_workspace": str(execution.replay_request.workspace),
        "attempt_ledger_path": str(execution.attempt_ledger_path),
        "attempt_ledger_identity_sha256": execution.attempt_ledger_identity_sha256,
        "provider_transport": "openai-codex",
        "requested_model": "gpt-5.6-sol",
        "prompt_variant_id": "P0",
        "configured_max_concurrency": execution.replay_request.max_concurrency,
        "logical_cap": execution.replay_request.logical_cap,
        "physical_cap": execution.replay_request.physical_cap,
        "subscription_billed_cost_usd": 0.0,
        "provider_calls_during_composition": execution.provider_calls_during_composition,
        "production_deploy_eligible": execution.production_deploy_eligible,
    }
    operator_attempt = {
        "attempt_ledger_path": str(execution.attempt_ledger_path),
        "attempt_ledger_identity_sha256": strict.attempt_ledger_identity_sha256,
        "terminal_attempt_count": strict.terminal_attempt_count,
        "execution_manifest_sha256": strict.execution_manifest_sha256,
        "execution_manifest_identity_sha256": strict.execution_manifest_identity_sha256,
    }
    rejected_facts = {
        **rejected,
        "rejected_provider_failure_count": 3,
        "rejected_pair_ids": [
            "106772146606:message_3:0",
            "1068317153703915:message_3:0",
            "58839888405:message_2:22",
        ],
        "mixed_trajectory_included_in_results": False,
    }
    handoff = _v11_execution_handoff(
        root=root,
        release_id=release_id,
        execution=execution,
    )
    if handoff["source_v4_directory"] != str(strict.source_root):
        raise ConcurrentRobustnessReleaseError("v11 execution handoff source directory is crossed")
    return {
        "strict_source_facts": strict_source,
        "strict_fresh_lineage_facts": fresh_lineage,
        "strict_policy_facts": strict_policy,
        "strict_settlement_facts": settlement,
        "operator_attempt_facts": operator_attempt,
        "physical_accounting_facts": physical,
        "fresh_execution_manifest_facts": manifest,
        "result_projection_facts": dict(evidence.result_projection),
        "rejected_mixed_history_facts": rejected_facts,
        "execution_handoff": handoff,
    }


def _physical_snapshot_identity(artifact_sha256: Mapping[str, str]) -> str:
    return _sha256_bytes(_json_bytes(dict(sorted(artifact_sha256.items()))))


def _v8_lineage_documents(
    *,
    root: Path,
    evidence: FullPoolProductionEvidenceFacts,
) -> dict[str, dict[str, object]]:
    closure = evidence.closure
    formal = evidence.formal
    return {
        "full_pool_source": {
            "directory": formal.full_pool_source_path.relative_to(root).as_posix(),
            "source_identity": formal.full_pool_source_identity,
            "manifest_sha256": formal.full_pool_source_manifest_sha256,
            "source_hash": formal.full_pool_source_hash,
            "contract_sha256": formal.full_pool_contract_sha256,
        },
        "historical_formal_source": {
            "directory": formal.historical_formal_path.relative_to(root).as_posix(),
            "source_id": formal.historical_formal_source_id,
            "manifest_sha256": formal.historical_formal_manifest_sha256,
        },
        "historical_study_source": {
            "directory": formal.historical_study_path.relative_to(root).as_posix(),
            "manifest_sha256": formal.historical_study_manifest_sha256,
            "artifact_manifest_sha256": closure.robustness_study_artifact_manifest_sha256,
            "root_identity_sha256": formal.historical_study_root_identity_sha256,
        },
        "candidate": {
            "directory": closure.candidate_path.relative_to(root).as_posix(),
            "manifest_sha256": closure.candidate_manifest_sha256,
            "candidate_identity_sha256": closure.candidate_identity_sha256,
            "candidate_content_identity_sha256": closure.candidate_content_identity_sha256,
            "production_deploy_eligible": False,
        },
        "presentation_closure": {
            "path": closure.closure_path.relative_to(root).as_posix(),
            "schema_version": closure.closure_schema_version,
            "sha256": closure.closure_sha256,
            "production_deploy_eligible": False,
        },
    }


def _full_pool_production_stage_facts(
    *,
    release_id: str,
    evidence: FullPoolProductionEvidenceFacts,
    release_contract_schema: str = ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V8,
) -> _FullPoolProductionPresentationFacts:
    facts = evidence.formal
    closure = evidence.closure
    return _FullPoolProductionPresentationFacts(
        release_id=release_id,
        release_contract_schema=release_contract_schema,
        canonical_endpoint=ROBUSTNESS_CANONICAL_ENDPOINT,
        production_evidence_schema=FULL_POOL_PRODUCTION_EVIDENCE_SCHEMA,
        implementation_commit=closure.implementation_commit,
        full_pool_source_identity=facts.full_pool_source_identity,
        full_pool_source_manifest_sha256=facts.full_pool_source_manifest_sha256,
        distinct_users=facts.distinct_users,
        eligible_pairs=facts.eligible_pairs,
        exposures=facts.exposures,
        primary_terminals=facts.primary_terminals,
        committed_batches=facts.committed_batches,
        candidate_ranking_rows=facts.candidate_ranking_rows,
        campaign_exposure_coverage=facts.campaign_exposure_coverage,
        provider_failed_terminals=facts.provider_failed_terminals,
        logical_judgments=facts.logical_judgments,
        physical_attempts=facts.physical_attempts,
        provider_transport=facts.provider_transport,
        requested_model=facts.requested_model,
        qualified_observed_model=facts.qualified_observed_model,
        usage_complete_response_count=facts.usage_complete_response_count,
        subscription_billed_cost_usd=facts.subscription_billed_cost_usd,
        approved_downloads=dict(closure.approved_downloads),
    )


def _materialize_full_pool_production_presentation(
    *,
    evidence: FullPoolProductionEvidenceFacts,
    stage_facts: _FullPoolProductionPresentationFacts,
) -> _PresentationBundle:
    closure = evidence.closure
    try:
        bundle = _REPORT_PRESENTATION.materialize_full_pool_production(
            full_pool_source_root=closure.full_pool_source_path,
            full_pool_manifest_sha256=closure.full_pool_source_manifest_sha256,
            historical_formal_root=closure.historical_formal_path,
            historical_study_root=closure.robustness_study_path,
            presentation_bundle_dir=closure.presentation_bundle_path,
            candidate_dir=closure.candidate_path,
            implementation_commit=closure.implementation_commit,
            stage_facts=stage_facts,
        )
        if not isinstance(bundle, _PresentationBundle):
            raise TypeError("Report returned an invalid Full-Pool production bundle")
        return bundle
    except (OSError, TypeError, ValueError) as exc:
        raise ConcurrentRobustnessReleaseError(
            "Report Full-Pool production presentation failed closure"
        ) from exc


def _validate_full_pool_production_presentation(
    bundle: _PresentationBundle,
    *,
    candidate: Path,
    stage_facts: _FullPoolProductionPresentationFacts,
) -> None:
    try:
        _REPORT_PRESENTATION.validate_full_pool_production_bundle(
            bundle,
            candidate_dir=candidate,
            stage_facts=stage_facts,
        )
    except (OSError, TypeError, ValueError) as exc:
        raise ConcurrentRobustnessReleaseError(
            "Report Full-Pool production presentation failed validation"
        ) from exc


def _v8_input_snapshots(paths: tuple[Path, ...]) -> dict[Path, dict[str, str]]:
    return {
        path: (_flat_file_hashes(path) if path.is_dir() else {path.name: _sha256_file(path)})
        for path in paths
    }


def _assert_v8_input_snapshots(snapshots: Mapping[Path, Mapping[str, str]]) -> None:
    for path, expected in snapshots.items():
        actual = _flat_file_hashes(path) if path.is_dir() else {path.name: _sha256_file(path)}
        if actual != dict(expected):
            raise ConcurrentRobustnessReleaseError(
                "v8 promotion mutated Full-Pool or historical immutable input evidence"
            )


def _v8_release_identity_document(
    *,
    release_id: str,
    implementation_commit: str,
    lineages: Mapping[str, Mapping[str, object]],
    closure: _evidence.FullPoolPresentationClosureFacts,
    artifact_sha256: Mapping[str, str],
) -> dict[str, object]:
    document = {
        "schema_version": FULL_POOL_PRODUCTION_IDENTITY_SCHEMA,
        "release_id": release_id,
        "implementation_commit": implementation_commit,
        "full_pool_source": dict(lineages["full_pool_source"]),
        "historical_formal_source": dict(lineages["historical_formal_source"]),
        "historical_study_source": dict(lineages["historical_study_source"]),
        "candidate": dict(lineages["candidate"]),
        "presentation_closure": dict(lineages["presentation_closure"]),
        "report_payload_schema_version": closure.report_payload_schema_version,
        "source_lineage_identity_sha256": closure.source_lineage_identity_sha256,
        "presentation_inventory_identity_sha256": (
            closure.presentation_inventory_identity_sha256
        ),
        "mechanism_set_identity_sha256": closure.mechanism_set_identity_sha256,
        "trace_index_sha256": closure.trace_index_sha256,
        "artifact_sha256": dict(sorted(artifact_sha256.items())),
    }
    if set(document) != _FULL_POOL_RELEASE_IDENTITY_FIELDS:
        raise ConcurrentRobustnessReleaseError("v8 release identity fields are crossed")
    return document


def _build_full_pool_v8_payloads(
    *,
    root: Path,
    evidence: FullPoolProductionEvidenceFacts,
    release_id: str,
    presentation: _PresentationBundle,
) -> tuple[dict[str, bytes], str]:
    closure = evidence.closure
    candidate = closure.candidate_path
    candidate_hashes = _flat_file_hashes(candidate)
    expected_candidate_hashes = {
        **dict(closure.candidate_artifact_hashes),
        CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON: closure.candidate_manifest_sha256,
    }
    if candidate_hashes != expected_candidate_hashes:
        raise ConcurrentRobustnessReleaseError(
            "v8 candidate inventory differs from the Evidence closure"
        )
    payloads: dict[str, bytes] = {}
    replaced = {
        CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON,
        ROBUSTNESS_CANDIDATE_RELEASE_EVIDENCE,
        CONCURRENT_MESSAGE_REPORT_HTML,
        ROBUSTNESS_REPORT_PAYLOAD,
    }
    for relative_path in sorted(candidate_hashes):
        if relative_path not in replaced:
            payloads[relative_path] = (candidate / relative_path).read_bytes()
    payloads[FULL_POOL_CANDIDATE_MANIFEST_ARTIFACT] = (
        candidate / CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON
    ).read_bytes()
    payloads[FULL_POOL_CANDIDATE_EVIDENCE_ARTIFACT] = (
        candidate / ROBUSTNESS_CANDIDATE_RELEASE_EVIDENCE
    ).read_bytes()
    payloads[FULL_POOL_PRESENTATION_CLOSURE_ARTIFACT] = closure.closure_path.read_bytes()
    payloads[ROBUSTNESS_REPORT_PAYLOAD] = presentation.report_payload
    payloads[CONCURRENT_MESSAGE_REPORT_HTML] = presentation.report_html

    full_pool_facts, historical_formal_facts, historical_study_facts = _v8_fact_documents(
        evidence.formal
    )
    lineages = _v8_lineage_documents(root=root, evidence=evidence)
    production_evidence = {
        "schema_version": FULL_POOL_PRODUCTION_EVIDENCE_SCHEMA,
        "release_id": release_id,
        "canonical_endpoint": ROBUSTNESS_CANONICAL_ENDPOINT,
        "implementation_commit": closure.implementation_commit,
        **lineages,
        "source_lineage_identity_sha256": closure.source_lineage_identity_sha256,
        "presentation_inventory_identity_sha256": (
            closure.presentation_inventory_identity_sha256
        ),
        "mechanism_set_identity_sha256": closure.mechanism_set_identity_sha256,
        "trace_index_sha256": closure.trace_index_sha256,
        "full_pool_formal_facts": full_pool_facts,
        "historical_formal_facts": historical_formal_facts,
        "historical_study_facts": historical_study_facts,
        "provider_calls_during_promotion": 0,
        "image_generation_triggered": False,
        "canonical_deployment_triggered": False,
        "production_deploy_eligible": True,
    }
    if set(production_evidence) != _FULL_POOL_PRODUCTION_EVIDENCE_FIELDS:
        raise ConcurrentRobustnessReleaseError("v8 production evidence fields are crossed")
    payloads[FULL_POOL_PRODUCTION_EVIDENCE_ARTIFACT] = _json_bytes(production_evidence)

    content_hashes = {
        relative_path: _sha256_bytes(payload)
        for relative_path, payload in payloads.items()
    }
    identity_document = _v8_release_identity_document(
        release_id=release_id,
        implementation_commit=closure.implementation_commit,
        lineages=lineages,
        closure=closure,
        artifact_sha256=content_hashes,
    )
    release_identity = _sha256_bytes(_json_bytes(identity_document))
    artifact_records = [
        {
            "relative_path": relative_path,
            "sha256": sha256,
            "bytes": len(payloads[relative_path]),
        }
        for relative_path, sha256 in sorted(content_hashes.items())
    ]
    manifest = {
        "schema_version": FULL_POOL_PRODUCTION_MANIFEST_SCHEMA,
        "release_type": "full_pool_formal_research",
        "release_id": release_id,
        "canonical_endpoint": ROBUSTNESS_CANONICAL_ENDPOINT,
        "report_schema": closure.report_payload_schema_version,
        "production_evidence_schema": FULL_POOL_PRODUCTION_EVIDENCE_SCHEMA,
        "implementation_commit": closure.implementation_commit,
        **lineages,
        "source_lineage_identity_sha256": closure.source_lineage_identity_sha256,
        "presentation_inventory_identity_sha256": (
            closure.presentation_inventory_identity_sha256
        ),
        "mechanism_set_identity_sha256": closure.mechanism_set_identity_sha256,
        "trace_index_sha256": closure.trace_index_sha256,
        "full_pool_formal_facts": full_pool_facts,
        "historical_formal_facts": historical_formal_facts,
        "historical_study_facts": historical_study_facts,
        "artifacts": artifact_records,
        "approved_downloads": dict(closure.approved_downloads),
        "release_identity_sha256": release_identity,
        "provider_calls_during_promotion": 0,
        "production_deploy_eligible": True,
    }
    if set(manifest) != _FULL_POOL_PRODUCTION_MANIFEST_FIELDS:
        raise ConcurrentRobustnessReleaseError("v8 production manifest fields are crossed")
    payloads[CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON] = _json_bytes(manifest)
    return payloads, release_identity


def _validate_v8_inventory_safety(hashes: Mapping[str, str]) -> None:
    paths = set(hashes)
    mermaid = {path for path in paths if path.endswith(".mmd")}
    if mermaid != _V8_MERMAID_INVENTORY:
        raise ConcurrentRobustnessReleaseError(
            "v8 production inventory must contain exactly eight Mermaid artifacts"
        )
    forbidden = (
        ".env",
        "credential",
        "cookie",
        "raw_prompt",
        "raw_response",
        "raw_provider_payload",
        "raw_profile_payload",
        "full_pool_attempt_ledger",
        "full_pool_execution_status",
        "full_pool_execution_identity",
        "release-contract",
    )
    if any(any(fragment in path.lower() for fragment in forbidden) for path in paths):
        raise ConcurrentRobustnessReleaseError(
            "v8 production inventory contains a forbidden operational or secret artifact"
        )


def _validate_full_pool_v8_release_dir(
    source: Path,
    *,
    repo_root: Path,
    evidence: FullPoolProductionEvidenceFacts,
    stage_facts: _FullPoolProductionPresentationFacts,
    release_identity: str,
) -> None:
    if source.is_symlink() or not source.is_dir():
        raise ConcurrentRobustnessReleaseError("v8 production release is not a real directory")
    hashes = _flat_file_hashes(source)
    _validate_v8_inventory_safety(hashes)
    manifest = _json_object(source / CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON)
    production_evidence = _json_object(source / FULL_POOL_PRODUCTION_EVIDENCE_ARTIFACT)
    payload = _json_object(source / ROBUSTNESS_REPORT_PAYLOAD)
    if (
        set(manifest) != _FULL_POOL_PRODUCTION_MANIFEST_FIELDS
        or set(production_evidence) != _FULL_POOL_PRODUCTION_EVIDENCE_FIELDS
        or manifest.get("schema_version") != FULL_POOL_PRODUCTION_MANIFEST_SCHEMA
        or manifest.get("release_type") != "full_pool_formal_research"
        or manifest.get("release_id") != stage_facts.release_id
        or manifest.get("canonical_endpoint") != ROBUSTNESS_CANONICAL_ENDPOINT
        or manifest.get("report_schema") != evidence.closure.report_payload_schema_version
        or manifest.get("production_evidence_schema") != FULL_POOL_PRODUCTION_EVIDENCE_SCHEMA
        or manifest.get("implementation_commit") != evidence.closure.implementation_commit
        or manifest.get("release_identity_sha256") != release_identity
        or manifest.get("provider_calls_during_promotion") != 0
        or manifest.get("production_deploy_eligible") is not True
        or production_evidence.get("schema_version") != FULL_POOL_PRODUCTION_EVIDENCE_SCHEMA
        or production_evidence.get("release_id") != stage_facts.release_id
        or production_evidence.get("canonical_endpoint") != ROBUSTNESS_CANONICAL_ENDPOINT
        or production_evidence.get("implementation_commit")
        != evidence.closure.implementation_commit
        or production_evidence.get("provider_calls_during_promotion") != 0
        or production_evidence.get("image_generation_triggered") is not False
        or production_evidence.get("canonical_deployment_triggered") is not False
        or production_evidence.get("production_deploy_eligible") is not True
        or payload.get("schema_version") != evidence.closure.report_payload_schema_version
        or payload.get("production_deploy_eligible") is not True
    ):
        raise ConcurrentRobustnessReleaseError(
            "v8 production manifest, evidence, or payload is crossed"
        )
    expected_lineages = _v8_lineage_documents(root=repo_root, evidence=evidence)
    expected_full_pool, expected_historical_formal, expected_historical_study = (
        _v8_fact_documents(evidence.formal)
    )
    expected_shared = {
        **expected_lineages,
        "source_lineage_identity_sha256": evidence.closure.source_lineage_identity_sha256,
        "presentation_inventory_identity_sha256": (
            evidence.closure.presentation_inventory_identity_sha256
        ),
        "mechanism_set_identity_sha256": evidence.closure.mechanism_set_identity_sha256,
        "trace_index_sha256": evidence.closure.trace_index_sha256,
        "full_pool_formal_facts": expected_full_pool,
        "historical_formal_facts": expected_historical_formal,
        "historical_study_facts": expected_historical_study,
    }
    if any(
        manifest.get(key) != value or production_evidence.get(key) != value
        for key, value in expected_shared.items()
    ):
        raise ConcurrentRobustnessReleaseError(
            "v8 production lineage, model, count, usage, or identity is crossed"
        )
    raw_records = manifest.get("artifacts")
    if not isinstance(raw_records, list) or any(
        not isinstance(record, dict) or set(record) != _ARTIFACT_RECORD_FIELDS
        for record in raw_records
    ):
        raise ConcurrentRobustnessReleaseError("v8 artifact records are invalid")
    records = [dict(record) for record in raw_records]
    paths: list[str] = []
    for record in records:
        raw_path = record.get("relative_path")
        if not isinstance(raw_path, str) or not raw_path:
            raise ConcurrentRobustnessReleaseError("v8 artifact path is invalid")
        paths.append(raw_path)
    if (
        paths != sorted(paths)
        or len(set(paths)) != len(paths)
        or set(paths) != set(hashes) - {CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON}
    ):
        raise ConcurrentRobustnessReleaseError("v8 artifact inventory is incomplete or non-canonical")
    artifact_hashes: dict[str, str] = {}
    for record in records:
        relative_path = str(record["relative_path"])
        target = source / relative_path
        if (
            record.get("sha256") != hashes[relative_path]
            or record.get("bytes") != target.stat().st_size
        ):
            raise ConcurrentRobustnessReleaseError("v8 artifact hash or byte count is crossed")
        artifact_hashes[relative_path] = str(record["sha256"])
    approved = _string_mapping(manifest.get("approved_downloads"), "v8 approved downloads")
    if approved != dict(evidence.closure.approved_downloads) or len(set(approved.values())) != len(approved):
        raise ConcurrentRobustnessReleaseError("v8 approved downloads are crossed or duplicated")
    for relative_path in approved.values():
        canonical = _canonical_relative_path(relative_path, "v8 approved download")
        if canonical not in artifact_hashes:
            raise ConcurrentRobustnessReleaseError("v8 approved download is absent from inventory")
    if (
        hashes.get(FULL_POOL_PRESENTATION_CLOSURE_ARTIFACT) != evidence.closure.closure_sha256
        or hashes.get(FULL_POOL_CANDIDATE_MANIFEST_ARTIFACT)
        != evidence.closure.candidate_manifest_sha256
        or hashes.get(FULL_POOL_CANDIDATE_EVIDENCE_ARTIFACT)
        != evidence.closure.candidate_evidence_sha256
    ):
        raise ConcurrentRobustnessReleaseError(
            "v8 preserved candidate or presentation closure identity is crossed"
        )
    preserved_manifest = _json_object(source / FULL_POOL_CANDIDATE_MANIFEST_ARTIFACT)
    preserved_evidence = _json_object(source / FULL_POOL_CANDIDATE_EVIDENCE_ARTIFACT)
    if (
        preserved_manifest.get("production_deploy_eligible") is not False
        or preserved_evidence.get("production_deploy_eligible") is not False
    ):
        raise ConcurrentRobustnessReleaseError("v8 candidate eligibility was mutated")
    _validate_full_pool_production_presentation(
        _PresentationBundle(
            report_payload=(source / ROBUSTNESS_REPORT_PAYLOAD).read_bytes(),
            report_html=(source / CONCURRENT_MESSAGE_REPORT_HTML).read_bytes(),
        ),
        candidate=evidence.closure.candidate_path,
        stage_facts=stage_facts,
    )
    lineages = {
        key: _object_mapping(manifest.get(key), f"v8 {key}")
        for key in (
            "full_pool_source",
            "historical_formal_source",
            "historical_study_source",
            "candidate",
            "presentation_closure",
        )
    }
    identity_document = _v8_release_identity_document(
        release_id=stage_facts.release_id,
        implementation_commit=evidence.closure.implementation_commit,
        lineages=lineages,
        closure=evidence.closure,
        artifact_sha256=artifact_hashes,
    )
    if _sha256_bytes(_json_bytes(identity_document)) != release_identity:
        raise ConcurrentRobustnessReleaseError("v8 release identity is crossed")


def _promote_full_pool_v8_release(
    *,
    repo_root: str | Path,
    full_pool_source_root: str | Path,
    full_pool_manifest_sha256: str,
    historical_formal_root: str | Path,
    historical_study_root: str | Path,
    candidate_dir: str | Path,
    presentation_closure_path: str | Path,
    destination_dir: str | Path,
    release_contract_path: str | Path,
    release_id: str,
    implementation_commit: str,
    closed_formal_facts: FullPoolFormalReleaseFacts | None,
) -> ConcurrentRobustnessProductionRelease:
    root = _real_directory(Path(repo_root), "repository root")
    full_pool = _repo_directory(root, Path(full_pool_source_root), "Full-Pool Formal source")
    historical_formal = _repo_directory(
        root,
        Path(historical_formal_root),
        "historical Formal source",
    )
    historical_study = _repo_directory(
        root,
        Path(historical_study_root),
        "historical robustness study",
    )
    candidate = _repo_directory(root, Path(candidate_dir), "Full-Pool candidate")
    closure_file = _repo_file(
        root,
        Path(presentation_closure_path),
        "Full-Pool presentation closure",
    )
    destination = _new_repo_path(root, Path(destination_dir), "v8 production destination")
    contract_path = _new_repo_path(root, Path(release_contract_path), "v8 release contract")
    if not _RELEASE_ID.fullmatch(release_id):
        raise ConcurrentRobustnessReleaseError("v8 release id is not a bounded stable token")
    if not _COMMIT.fullmatch(implementation_commit):
        raise ConcurrentRobustnessReleaseError("v8 implementation commit is invalid")
    if not _SHA256.fullmatch(full_pool_manifest_sha256):
        raise ConcurrentRobustnessReleaseError("v8 Full-Pool manifest SHA-256 is invalid")
    direct_inputs = (full_pool, historical_formal, historical_study, candidate, closure_file)
    for index, left in enumerate(direct_inputs):
        if any(_paths_overlap(left, right) for right in direct_inputs[index + 1 :]):
            raise ConcurrentRobustnessReleaseError("v8 immutable inputs overlap or are nested")
    if (
        any(_paths_overlap(destination, path) for path in direct_inputs)
        or any(_paths_overlap(contract_path, path) for path in direct_inputs)
        or _paths_overlap(destination, contract_path)
    ):
        raise ConcurrentRobustnessReleaseError("v8 output overlaps immutable input evidence")
    snapshots = _v8_input_snapshots(direct_inputs)
    try:
        evidence = _evidence.validate_full_pool_production_evidence(
            repo_root=root,
            closure_path=closure_file,
            full_pool_source_root=full_pool,
            full_pool_manifest_sha256=full_pool_manifest_sha256,
            historical_formal_root=historical_formal,
            historical_study_root=historical_study,
            candidate_dir=candidate,
            implementation_commit=implementation_commit,
            formal_facts=closed_formal_facts,
        )
    except ConcurrentRobustnessEvidenceError as exc:
        raise ConcurrentRobustnessReleaseError(str(exc)) from exc
    bundle = evidence.closure.presentation_bundle_path
    if any(_paths_overlap(bundle, path) for path in direct_inputs):
        raise ConcurrentRobustnessReleaseError("v8 presentation bundle overlaps another immutable input")
    if _paths_overlap(destination, bundle) or _paths_overlap(contract_path, bundle):
        raise ConcurrentRobustnessReleaseError("v8 output overlaps the presentation bundle")
    snapshots[bundle] = _flat_file_hashes(bundle)
    _assert_v8_input_snapshots(snapshots)

    stage_facts = _full_pool_production_stage_facts(
        release_id=release_id,
        evidence=evidence,
    )
    presentation = _materialize_full_pool_production_presentation(
        evidence=evidence,
        stage_facts=stage_facts,
    )
    _assert_v8_input_snapshots(snapshots)
    payloads, release_identity = _build_full_pool_v8_payloads(
        root=root,
        evidence=evidence,
        release_id=release_id,
        presentation=presentation,
    )
    lineages = _v8_lineage_documents(root=root, evidence=evidence)
    full_pool_facts, historical_formal_facts, historical_study_facts = _v8_fact_documents(
        evidence.formal
    )

    destination.parent.mkdir(parents=True, exist_ok=True)
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.v8.",
            suffix=".staging",
            dir=destination.parent,
        )
    )
    contract_staging = contract_path.with_name(
        f".{contract_path.name}.{os.getpid()}.staging"
    )
    destination_installed = False
    contract_installed = False
    try:
        for relative_path, payload in payloads.items():
            target = staging / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        _validate_full_pool_v8_release_dir(
            staging,
            repo_root=root,
            evidence=evidence,
            stage_facts=stage_facts,
            release_identity=release_identity,
        )
        release_hashes = _flat_file_hashes(staging)
        contract_document = {
            "schema_version": ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V8,
            "release_purpose": "full_pool_formal_research",
            "release_id": release_id,
            "canonical_endpoint": ROBUSTNESS_CANONICAL_ENDPOINT,
            "source_directory": destination.relative_to(root).as_posix(),
            "artifact_manifest_schema_version": FULL_POOL_PRODUCTION_MANIFEST_SCHEMA,
            "report_payload_schema_version": evidence.closure.report_payload_schema_version,
            "production_evidence_schema_version": FULL_POOL_PRODUCTION_EVIDENCE_SCHEMA,
            "implementation_commit": implementation_commit,
            "full_pool_source_directory": lineages["full_pool_source"]["directory"],
            "full_pool_source_identity": evidence.formal.full_pool_source_identity,
            "full_pool_source_manifest_sha256": evidence.formal.full_pool_source_manifest_sha256,
            "full_pool_source_hash": evidence.formal.full_pool_source_hash,
            "full_pool_contract_sha256": evidence.formal.full_pool_contract_sha256,
            "historical_formal_directory": lineages["historical_formal_source"]["directory"],
            "historical_formal_source_id": evidence.formal.historical_formal_source_id,
            "historical_formal_manifest_sha256": (
                evidence.formal.historical_formal_manifest_sha256
            ),
            "historical_study_directory": lineages["historical_study_source"]["directory"],
            "historical_study_manifest_sha256": evidence.formal.historical_study_manifest_sha256,
            "historical_study_artifact_manifest_sha256": (
                evidence.closure.robustness_study_artifact_manifest_sha256
            ),
            "historical_study_root_identity_sha256": (
                evidence.formal.historical_study_root_identity_sha256
            ),
            "candidate_directory": lineages["candidate"]["directory"],
            "candidate_manifest_sha256": evidence.closure.candidate_manifest_sha256,
            "candidate_identity_sha256": evidence.closure.candidate_identity_sha256,
            "candidate_content_identity_sha256": (
                evidence.closure.candidate_content_identity_sha256
            ),
            "presentation_closure_contract": lineages["presentation_closure"]["path"],
            "presentation_closure_contract_sha256": evidence.closure.closure_sha256,
            "presentation_closure_schema_version": evidence.closure.closure_schema_version,
            "source_lineage_identity_sha256": evidence.closure.source_lineage_identity_sha256,
            "presentation_inventory_identity_sha256": (
                evidence.closure.presentation_inventory_identity_sha256
            ),
            "mechanism_set_identity_sha256": evidence.closure.mechanism_set_identity_sha256,
            "trace_index_sha256": evidence.closure.trace_index_sha256,
            "full_pool_formal_facts": full_pool_facts,
            "historical_formal_facts": historical_formal_facts,
            "historical_study_facts": historical_study_facts,
            "release_identity_sha256": release_identity,
            "production_deploy_eligible": True,
            "artifact_sha256": dict(sorted(release_hashes.items())),
        }
        if set(contract_document) != _RELEASE_CONTRACT_V8_FIELDS:
            raise ConcurrentRobustnessReleaseError("v8 release contract fields are crossed")
        contract_staging.write_bytes(_json_bytes(contract_document))
        if destination.exists() or contract_path.exists():
            raise ConcurrentRobustnessReleaseError(
                "v8 production destination or contract appeared during staging"
            )
        os.replace(staging, destination)
        destination_installed = True
        os.replace(contract_staging, contract_path)
        contract_installed = True
        _validate_full_pool_v8_release_dir(
            destination,
            repo_root=root,
            evidence=evidence,
            stage_facts=stage_facts,
            release_identity=release_identity,
        )
        final_hashes = _flat_file_hashes(destination)
        if final_hashes != contract_document["artifact_sha256"]:
            raise ConcurrentRobustnessReleaseError("v8 release drifted after atomic publication")
        _assert_v8_input_snapshots(snapshots)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if contract_staging.exists():
            contract_staging.unlink(missing_ok=True)
        if contract_installed:
            contract_path.unlink(missing_ok=True)
        if destination_installed:
            shutil.rmtree(destination, ignore_errors=True)
        raise

    return ConcurrentRobustnessProductionRelease(
        source_dir=destination,
        contract_path=contract_path,
        release_id=release_id,
        report_sha256=final_hashes[CONCURRENT_MESSAGE_REPORT_HTML],
        manifest_sha256=final_hashes[CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON],
        release_identity_sha256=release_identity,
    )


def _promote_full_pool_v9_release(
    *,
    repo_root: str | Path,
    full_pool_source_root: str | Path,
    full_pool_manifest_sha256: str,
    historical_formal_root: str | Path,
    historical_study_root: str | Path,
    candidate_dir: str | Path,
    presentation_closure_path: str | Path,
    destination_dir: str | Path,
    release_contract_path: str | Path,
    release_id: str,
    implementation_commit: str,
) -> ConcurrentRobustnessProductionRelease:
    root = _real_directory(Path(repo_root), "repository root")
    full_pool = _repo_directory(root, Path(full_pool_source_root), "segmented Full-Pool source-v2")
    historical_formal = _repo_directory(
        root, Path(historical_formal_root), "historical Formal source"
    )
    historical_study = _repo_directory(
        root, Path(historical_study_root), "historical robustness study"
    )
    candidate = _repo_directory(root, Path(candidate_dir), "segmented Full-Pool candidate")
    closure_file = _repo_file(
        root, Path(presentation_closure_path), "segmented Full-Pool presentation closure"
    )
    destination = _new_repo_path(root, Path(destination_dir), "v9 production destination")
    contract_path = _new_repo_path(root, Path(release_contract_path), "v9 release contract")
    if not _RELEASE_ID.fullmatch(release_id):
        raise ConcurrentRobustnessReleaseError("v9 release id is not a bounded stable token")
    if not _COMMIT.fullmatch(implementation_commit):
        raise ConcurrentRobustnessReleaseError("v9 implementation commit is invalid")
    if not _SHA256.fullmatch(full_pool_manifest_sha256):
        raise ConcurrentRobustnessReleaseError("v9 source-v2 manifest SHA-256 is invalid")
    direct_inputs = (full_pool, historical_formal, historical_study, candidate, closure_file)
    for index, left in enumerate(direct_inputs):
        if any(_paths_overlap(left, right) for right in direct_inputs[index + 1 :]):
            raise ConcurrentRobustnessReleaseError("v9 immutable inputs overlap or are nested")
    if (
        any(_paths_overlap(destination, path) for path in direct_inputs)
        or any(_paths_overlap(contract_path, path) for path in direct_inputs)
        or _paths_overlap(destination, contract_path)
    ):
        raise ConcurrentRobustnessReleaseError("v9 output overlaps immutable input evidence")
    snapshots = _v8_input_snapshots(direct_inputs)
    try:
        evidence = _evidence.validate_segmented_full_pool_production_evidence(
            repo_root=root,
            closure_path=closure_file,
            full_pool_source_root=full_pool,
            full_pool_manifest_sha256=full_pool_manifest_sha256,
            historical_formal_root=historical_formal,
            historical_study_root=historical_study,
            candidate_dir=candidate,
            implementation_commit=implementation_commit,
        )
    except ConcurrentRobustnessEvidenceError as exc:
        raise ConcurrentRobustnessReleaseError(str(exc)) from exc
    base_evidence = _v9_base_evidence(evidence)
    bundle = evidence.closure.presentation_bundle_path
    if any(_paths_overlap(bundle, path) for path in direct_inputs):
        raise ConcurrentRobustnessReleaseError("v9 presentation bundle overlaps another immutable input")
    if _paths_overlap(destination, bundle) or _paths_overlap(contract_path, bundle):
        raise ConcurrentRobustnessReleaseError("v9 output overlaps the presentation bundle")
    snapshots[bundle] = _flat_file_hashes(bundle)
    _assert_v8_input_snapshots(snapshots)

    stage_facts = _full_pool_production_stage_facts(
        release_id=release_id,
        evidence=base_evidence,
        release_contract_schema=ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V9,
    )
    presentation = _materialize_full_pool_production_presentation(
        evidence=base_evidence,
        stage_facts=stage_facts,
    )
    _assert_v8_input_snapshots(snapshots)
    payloads, release_identity = _build_full_pool_v8_payloads(
        root=root,
        evidence=base_evidence,
        release_id=release_id,
        presentation=presentation,
    )
    lineages = _v8_lineage_documents(root=root, evidence=base_evidence)
    full_pool_facts, historical_formal_facts, historical_study_facts = _v8_fact_documents(
        evidence.formal
    )
    segmented_facts = _v9_segmented_fact_document(evidence.segmented)
    recovery_lineage_facts, recovery_accounting_facts = _v9_recovery_fact_documents(
        evidence.segmented
    )

    destination.parent.mkdir(parents=True, exist_ok=True)
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.v9.", suffix=".staging", dir=destination.parent
        )
    )
    contract_staging = contract_path.with_name(
        f".{contract_path.name}.{os.getpid()}.staging"
    )
    destination_installed = False
    contract_installed = False
    try:
        for relative_path, payload in payloads.items():
            target = staging / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        _validate_full_pool_v8_release_dir(
            staging,
            repo_root=root,
            evidence=base_evidence,
            stage_facts=stage_facts,
            release_identity=release_identity,
        )
        release_hashes = _flat_file_hashes(staging)
        snapshot_identity = _physical_snapshot_identity(release_hashes)
        contract_document: dict[str, object] = {
            "schema_version": ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V9,
            "release_purpose": "full_pool_segmented_formal_research",
            "release_id": release_id,
            "canonical_endpoint": ROBUSTNESS_CANONICAL_ENDPOINT,
            "source_directory": destination.relative_to(root).as_posix(),
            "artifact_manifest_schema_version": FULL_POOL_PRODUCTION_MANIFEST_SCHEMA,
            "report_payload_schema_version": evidence.closure.report_payload_schema_version,
            "production_evidence_schema_version": FULL_POOL_PRODUCTION_EVIDENCE_SCHEMA,
            "implementation_commit": implementation_commit,
            "full_pool_source_directory": lineages["full_pool_source"]["directory"],
            "full_pool_source_identity": evidence.formal.full_pool_source_identity,
            "full_pool_source_manifest_sha256": evidence.formal.full_pool_source_manifest_sha256,
            "full_pool_source_hash": evidence.formal.full_pool_source_hash,
            "full_pool_contract_sha256": evidence.formal.full_pool_contract_sha256,
            "historical_formal_directory": lineages["historical_formal_source"]["directory"],
            "historical_formal_source_id": evidence.formal.historical_formal_source_id,
            "historical_formal_manifest_sha256": evidence.formal.historical_formal_manifest_sha256,
            "historical_study_directory": lineages["historical_study_source"]["directory"],
            "historical_study_manifest_sha256": evidence.formal.historical_study_manifest_sha256,
            "historical_study_artifact_manifest_sha256": (
                evidence.closure.robustness_study_artifact_manifest_sha256
            ),
            "historical_study_root_identity_sha256": (
                evidence.formal.historical_study_root_identity_sha256
            ),
            "candidate_directory": lineages["candidate"]["directory"],
            "candidate_manifest_sha256": evidence.closure.candidate_manifest_sha256,
            "candidate_identity_sha256": evidence.closure.candidate_identity_sha256,
            "candidate_content_identity_sha256": evidence.closure.candidate_content_identity_sha256,
            "presentation_closure_contract": lineages["presentation_closure"]["path"],
            "presentation_closure_contract_sha256": evidence.closure.closure_sha256,
            "presentation_closure_schema_version": evidence.closure.closure_schema_version,
            "source_lineage_identity_sha256": evidence.closure.source_lineage_identity_sha256,
            "presentation_inventory_identity_sha256": (
                evidence.closure.presentation_inventory_identity_sha256
            ),
            "mechanism_set_identity_sha256": evidence.closure.mechanism_set_identity_sha256,
            "trace_index_sha256": evidence.closure.trace_index_sha256,
            "full_pool_formal_facts": full_pool_facts,
            "historical_formal_facts": historical_formal_facts,
            "historical_study_facts": historical_study_facts,
            "segmented_source_facts": segmented_facts,
            "physical_snapshot_identity_sha256": snapshot_identity,
            "release_identity_sha256": release_identity,
            "production_deploy_eligible": True,
            "artifact_sha256": dict(sorted(release_hashes.items())),
        }
        if recovery_lineage_facts is not None and recovery_accounting_facts is not None:
            contract_document.update(
                {
                    "recovery_lineage_facts": recovery_lineage_facts,
                    "recovery_accounting_facts": recovery_accounting_facts,
                }
            )
            expected_contract_fields = _RELEASE_CONTRACT_V9_RECOVERY_FIELDS
        else:
            expected_contract_fields = _RELEASE_CONTRACT_V9_FIELDS
        if set(contract_document) != expected_contract_fields:
            raise ConcurrentRobustnessReleaseError("v9 release contract fields are crossed")
        contract_staging.write_bytes(_json_bytes(contract_document))
        if destination.exists() or contract_path.exists():
            raise ConcurrentRobustnessReleaseError(
                "v9 production destination or contract appeared during staging"
            )
        os.replace(staging, destination)
        destination_installed = True
        os.replace(contract_staging, contract_path)
        contract_installed = True
        _validate_full_pool_v8_release_dir(
            destination,
            repo_root=root,
            evidence=base_evidence,
            stage_facts=stage_facts,
            release_identity=release_identity,
        )
        final_hashes = _flat_file_hashes(destination)
        if (
            final_hashes != contract_document["artifact_sha256"]
            or _physical_snapshot_identity(final_hashes) != snapshot_identity
        ):
            raise ConcurrentRobustnessReleaseError("v9 physical snapshot drifted after publication")
        round_trip = _validate_full_pool_v9_production_release(
            repo_root=root,
            contract_document=contract_document,
            source_dir=destination,
        )
        if (
            round_trip.get("production_deploy_eligible") is not True
            or round_trip.get("report_sha256")
            != final_hashes[CONCURRENT_MESSAGE_REPORT_HTML]
        ):
            raise ConcurrentRobustnessReleaseError("v9 standalone round-trip facts are crossed")
        _assert_v8_input_snapshots(snapshots)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if contract_staging.exists():
            contract_staging.unlink(missing_ok=True)
        if contract_installed:
            contract_path.unlink(missing_ok=True)
        if destination_installed:
            shutil.rmtree(destination, ignore_errors=True)
        raise
    return ConcurrentRobustnessProductionRelease(
        source_dir=destination,
        contract_path=contract_path,
        release_id=release_id,
        report_sha256=final_hashes[CONCURRENT_MESSAGE_REPORT_HTML],
        manifest_sha256=final_hashes[CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON],
        release_identity_sha256=release_identity,
    )


def _promote_full_pool_v10_release(
    *,
    repo_root: str | Path,
    full_pool_source_root: str | Path,
    full_pool_manifest_sha256: str,
    historical_formal_root: str | Path,
    historical_study_root: str | Path,
    candidate_dir: str | Path,
    presentation_closure_path: str | Path,
    automation_execution_manifest_path: str | Path,
    destination_dir: str | Path,
    release_contract_path: str | Path,
    release_id: str,
    implementation_commit: str,
) -> ConcurrentRobustnessProductionRelease:
    root = _real_directory(Path(repo_root), "repository root")
    full_pool = _repo_directory(root, Path(full_pool_source_root), "source-v3 Full-Pool source")
    historical_formal = _repo_directory(
        root, Path(historical_formal_root), "v10 historical Formal source"
    )
    historical_study = _repo_directory(
        root, Path(historical_study_root), "v10 historical robustness study"
    )
    candidate = _repo_directory(root, Path(candidate_dir), "source-v3 Full-Pool candidate")
    closure_file = _repo_file(
        root, Path(presentation_closure_path), "source-v3 presentation closure"
    )
    execution_manifest_file = _repo_file(
        root,
        Path(automation_execution_manifest_path),
        "automation execution manifest",
    )
    destination = _new_repo_path(root, Path(destination_dir), "v10 production destination")
    contract_path = _new_repo_path(root, Path(release_contract_path), "v10 release contract")
    if not _RELEASE_ID.fullmatch(release_id):
        raise ConcurrentRobustnessReleaseError("v10 release id is not a bounded stable token")
    if not _COMMIT.fullmatch(implementation_commit):
        raise ConcurrentRobustnessReleaseError("v10 implementation commit is invalid")
    if not _SHA256.fullmatch(full_pool_manifest_sha256):
        raise ConcurrentRobustnessReleaseError("v10 source-v3 manifest SHA-256 is invalid")
    direct_inputs = (
        full_pool,
        historical_formal,
        historical_study,
        candidate,
        closure_file,
        execution_manifest_file,
    )
    for index, left in enumerate(direct_inputs):
        if any(_paths_overlap(left, right) for right in direct_inputs[index + 1 :]):
            raise ConcurrentRobustnessReleaseError("v10 immutable inputs overlap or are nested")
    if (
        any(_paths_overlap(destination, path) for path in direct_inputs)
        or any(_paths_overlap(contract_path, path) for path in direct_inputs)
        or _paths_overlap(destination, contract_path)
    ):
        raise ConcurrentRobustnessReleaseError("v10 output overlaps immutable input evidence")
    snapshots = _v8_input_snapshots(direct_inputs)
    try:
        evidence = _evidence.validate_nested_full_pool_production_evidence(
            repo_root=root,
            closure_path=closure_file,
            full_pool_source_root=full_pool,
            full_pool_manifest_sha256=full_pool_manifest_sha256,
            historical_formal_root=historical_formal,
            historical_study_root=historical_study,
            candidate_dir=candidate,
            automation_execution_manifest_path=execution_manifest_file,
            implementation_commit=implementation_commit,
        )
    except ConcurrentRobustnessEvidenceError as exc:
        raise ConcurrentRobustnessReleaseError(str(exc)) from exc
    base_evidence = _v10_base_evidence(evidence)
    bundle = evidence.closure.presentation_bundle_path
    if any(_paths_overlap(bundle, path) for path in direct_inputs):
        raise ConcurrentRobustnessReleaseError("v10 presentation bundle overlaps immutable inputs")
    if _paths_overlap(destination, bundle) or _paths_overlap(contract_path, bundle):
        raise ConcurrentRobustnessReleaseError("v10 output overlaps the presentation bundle")
    snapshots[bundle] = _flat_file_hashes(bundle)
    _assert_v8_input_snapshots(snapshots)

    stage_facts = _full_pool_production_stage_facts(
        release_id=release_id,
        evidence=base_evidence,
        release_contract_schema=ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V10,
    )
    presentation = _materialize_full_pool_production_presentation(
        evidence=base_evidence,
        stage_facts=stage_facts,
    )
    _assert_v8_input_snapshots(snapshots)
    payloads, release_identity = _build_full_pool_v8_payloads(
        root=root,
        evidence=base_evidence,
        release_id=release_id,
        presentation=presentation,
    )
    lineages = _v8_lineage_documents(root=root, evidence=base_evidence)
    full_pool_facts, historical_formal_facts, historical_study_facts = _v8_fact_documents(
        evidence.formal
    )
    v10_facts = _v10_fact_documents(root=root, evidence=evidence)

    destination.parent.mkdir(parents=True, exist_ok=True)
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.v10.",
            suffix=".staging",
            dir=destination.parent,
        )
    )
    contract_staging = contract_path.with_name(
        f".{contract_path.name}.{os.getpid()}.staging"
    )
    destination_installed = False
    contract_installed = False
    try:
        for relative_path, payload in payloads.items():
            target = staging / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        _validate_full_pool_v8_release_dir(
            staging,
            repo_root=root,
            evidence=base_evidence,
            stage_facts=stage_facts,
            release_identity=release_identity,
        )
        release_hashes = _flat_file_hashes(staging)
        snapshot_identity = _physical_snapshot_identity(release_hashes)
        contract_document: dict[str, object] = {
            "schema_version": ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V10,
            "release_purpose": "full_pool_automated_nested_formal_research",
            "release_id": release_id,
            "canonical_endpoint": ROBUSTNESS_CANONICAL_ENDPOINT,
            "source_directory": destination.relative_to(root).as_posix(),
            "artifact_manifest_schema_version": FULL_POOL_PRODUCTION_MANIFEST_SCHEMA,
            "report_payload_schema_version": evidence.closure.report_payload_schema_version,
            "production_evidence_schema_version": FULL_POOL_PRODUCTION_EVIDENCE_SCHEMA,
            "implementation_commit": implementation_commit,
            "full_pool_source_directory": lineages["full_pool_source"]["directory"],
            "full_pool_source_identity": evidence.formal.full_pool_source_identity,
            "full_pool_source_manifest_sha256": evidence.formal.full_pool_source_manifest_sha256,
            "full_pool_source_hash": evidence.formal.full_pool_source_hash,
            "full_pool_contract_sha256": evidence.formal.full_pool_contract_sha256,
            "historical_formal_directory": lineages["historical_formal_source"]["directory"],
            "historical_formal_source_id": evidence.formal.historical_formal_source_id,
            "historical_formal_manifest_sha256": evidence.formal.historical_formal_manifest_sha256,
            "historical_study_directory": lineages["historical_study_source"]["directory"],
            "historical_study_manifest_sha256": evidence.formal.historical_study_manifest_sha256,
            "historical_study_artifact_manifest_sha256": (
                evidence.closure.robustness_study_artifact_manifest_sha256
            ),
            "historical_study_root_identity_sha256": (
                evidence.formal.historical_study_root_identity_sha256
            ),
            "candidate_directory": lineages["candidate"]["directory"],
            "candidate_manifest_sha256": evidence.closure.candidate_manifest_sha256,
            "candidate_identity_sha256": evidence.closure.candidate_identity_sha256,
            "candidate_content_identity_sha256": evidence.closure.candidate_content_identity_sha256,
            "presentation_closure_contract": lineages["presentation_closure"]["path"],
            "presentation_closure_contract_sha256": evidence.closure.closure_sha256,
            "presentation_closure_schema_version": evidence.closure.closure_schema_version,
            "source_lineage_identity_sha256": evidence.closure.source_lineage_identity_sha256,
            "presentation_inventory_identity_sha256": (
                evidence.closure.presentation_inventory_identity_sha256
            ),
            "mechanism_set_identity_sha256": evidence.closure.mechanism_set_identity_sha256,
            "trace_index_sha256": evidence.closure.trace_index_sha256,
            "full_pool_formal_facts": full_pool_facts,
            "historical_formal_facts": historical_formal_facts,
            "historical_study_facts": historical_study_facts,
            "automation_execution_manifest": execution_manifest_file.relative_to(root).as_posix(),
            "automation_execution_manifest_sha256": evidence.execution_manifest.manifest_sha256,
            "automation_execution_manifest_identity_sha256": (
                evidence.execution_manifest.manifest_identity_sha256
            ),
            "automation_execution_manifest_facts": v10_facts[
                "automation_execution_manifest_facts"
            ],
            "nested_source_facts": v10_facts["nested_source_facts"],
            "nested_recovery_lineage_facts": v10_facts[
                "nested_recovery_lineage_facts"
            ],
            "automated_recovery_policy_facts": v10_facts[
                "automated_recovery_policy_facts"
            ],
            "settlement_v2_facts": v10_facts["settlement_v2_facts"],
            "recovery_accounting_facts": v10_facts["recovery_accounting_facts"],
            "result_projection_facts": v10_facts["result_projection_facts"],
            "physical_snapshot_identity_sha256": snapshot_identity,
            "release_identity_sha256": release_identity,
            "production_deploy_eligible": True,
            "artifact_sha256": dict(sorted(release_hashes.items())),
        }
        if set(contract_document) != _RELEASE_CONTRACT_V10_FIELDS:
            raise ConcurrentRobustnessReleaseError("v10 release contract fields are crossed")
        contract_staging.write_bytes(_json_bytes(contract_document))
        if destination.exists() or contract_path.exists():
            raise ConcurrentRobustnessReleaseError(
                "v10 production destination or contract appeared during staging"
            )
        os.replace(staging, destination)
        destination_installed = True
        os.replace(contract_staging, contract_path)
        contract_installed = True
        final_hashes = _flat_file_hashes(destination)
        if (
            final_hashes != contract_document["artifact_sha256"]
            or _physical_snapshot_identity(final_hashes) != snapshot_identity
        ):
            raise ConcurrentRobustnessReleaseError("v10 physical snapshot drifted after publication")
        round_trip = _validate_full_pool_v10_production_release(
            repo_root=root,
            contract_document=contract_document,
            source_dir=destination,
        )
        if (
            round_trip.get("production_deploy_eligible") is not True
            or round_trip.get("report_sha256")
            != final_hashes[CONCURRENT_MESSAGE_REPORT_HTML]
        ):
            raise ConcurrentRobustnessReleaseError("v10 standalone round-trip facts are crossed")
        _assert_v8_input_snapshots(snapshots)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if contract_staging.exists():
            contract_staging.unlink(missing_ok=True)
        if contract_installed:
            contract_path.unlink(missing_ok=True)
        if destination_installed:
            shutil.rmtree(destination, ignore_errors=True)
        raise
    return ConcurrentRobustnessProductionRelease(
        source_dir=destination,
        contract_path=contract_path,
        release_id=release_id,
        report_sha256=final_hashes[CONCURRENT_MESSAGE_REPORT_HTML],
        manifest_sha256=final_hashes[CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON],
        release_identity_sha256=release_identity,
    )


def _promote_full_pool_v11_release(
    *,
    repo_root: str | Path,
    full_pool_source_root: str | Path,
    full_pool_manifest_sha256: str,
    historical_formal_root: str | Path,
    historical_study_root: str | Path,
    candidate_dir: str | Path,
    presentation_closure_path: str | Path,
    fresh_execution_manifest_path: str | Path,
    destination_dir: str | Path,
    release_contract_path: str | Path,
    release_id: str,
    implementation_commit: str,
) -> ConcurrentRobustnessProductionRelease:
    """Promote only independently closed strict source-v4 evidence."""
    root = _real_directory(Path(repo_root), "repository root")
    full_pool = _repo_directory(root, Path(full_pool_source_root), "source-v4 Full-Pool source")
    historical_formal = _repo_directory(root, Path(historical_formal_root), "v11 historical Formal source")
    historical_study = _repo_directory(root, Path(historical_study_root), "v11 historical robustness study")
    candidate = _repo_directory(root, Path(candidate_dir), "source-v4 Full-Pool candidate")
    closure_file = _repo_file(root, Path(presentation_closure_path), "source-v4 presentation closure")
    execution_manifest_file = _repo_file(root, Path(fresh_execution_manifest_path), "fresh execution manifest")
    destination = _new_repo_path(root, Path(destination_dir), "v11 production destination")
    contract_path = _new_repo_path(root, Path(release_contract_path), "v11 release contract")
    if not _RELEASE_ID.fullmatch(release_id):
        raise ConcurrentRobustnessReleaseError("v11 release id is not a bounded stable token")
    if not _COMMIT.fullmatch(implementation_commit):
        raise ConcurrentRobustnessReleaseError("v11 implementation commit is invalid")
    if not _SHA256.fullmatch(full_pool_manifest_sha256):
        raise ConcurrentRobustnessReleaseError("v11 source-v4 manifest SHA-256 is invalid")
    direct_inputs = (
        full_pool,
        historical_formal,
        historical_study,
        candidate,
        closure_file,
        execution_manifest_file,
    )
    for index, left in enumerate(direct_inputs):
        if any(_paths_overlap(left, right) for right in direct_inputs[index + 1 :]):
            raise ConcurrentRobustnessReleaseError("v11 immutable inputs overlap or are nested")
    if (
        any(_paths_overlap(destination, path) for path in direct_inputs)
        or any(_paths_overlap(contract_path, path) for path in direct_inputs)
        or _paths_overlap(destination, contract_path)
    ):
        raise ConcurrentRobustnessReleaseError("v11 output overlaps immutable input evidence")
    snapshots = _v8_input_snapshots(direct_inputs)
    try:
        evidence = _evidence.validate_strict_full_pool_production_evidence(
            repo_root=root,
            closure_path=closure_file,
            full_pool_source_root=full_pool,
            full_pool_manifest_sha256=full_pool_manifest_sha256,
            historical_formal_root=historical_formal,
            historical_study_root=historical_study,
            candidate_dir=candidate,
            fresh_execution_manifest_path=execution_manifest_file,
            implementation_commit=implementation_commit,
        )
    except ConcurrentRobustnessEvidenceError as exc:
        raise ConcurrentRobustnessReleaseError(str(exc)) from exc
    base_evidence = _v11_base_evidence(evidence)
    bundle = evidence.closure.presentation_bundle_path
    if any(_paths_overlap(bundle, path) for path in direct_inputs):
        raise ConcurrentRobustnessReleaseError("v11 presentation bundle overlaps immutable inputs")
    if _paths_overlap(destination, bundle) or _paths_overlap(contract_path, bundle):
        raise ConcurrentRobustnessReleaseError("v11 output overlaps the presentation bundle")
    snapshots[bundle] = _flat_file_hashes(bundle)
    _assert_v8_input_snapshots(snapshots)

    stage_facts = _full_pool_production_stage_facts(
        release_id=release_id,
        evidence=base_evidence,
        release_contract_schema=ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V11,
    )
    presentation = _materialize_full_pool_production_presentation(
        evidence=base_evidence,
        stage_facts=stage_facts,
    )
    _assert_v8_input_snapshots(snapshots)
    payloads, release_identity = _build_full_pool_v8_payloads(
        root=root,
        evidence=base_evidence,
        release_id=release_id,
        presentation=presentation,
    )
    lineages = _v8_lineage_documents(root=root, evidence=base_evidence)
    full_pool_facts, historical_formal_facts, historical_study_facts = _v8_fact_documents(evidence.formal)
    v11_facts = _v11_fact_documents(root=root, release_id=release_id, evidence=evidence)

    destination.parent.mkdir(parents=True, exist_ok=True)
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.v11.",
            suffix=".staging",
            dir=destination.parent,
        )
    )
    contract_staging = contract_path.with_name(f".{contract_path.name}.{os.getpid()}.staging")
    destination_installed = False
    contract_installed = False
    try:
        for relative_path, payload in payloads.items():
            target = staging / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        _validate_full_pool_v8_release_dir(
            staging,
            repo_root=root,
            evidence=base_evidence,
            stage_facts=stage_facts,
            release_identity=release_identity,
        )
        release_hashes = _flat_file_hashes(staging)
        snapshot_identity = _physical_snapshot_identity(release_hashes)
        contract_document: dict[str, object] = {
            "schema_version": ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V11,
            "release_purpose": "full_pool_strict_fresh_formal_research",
            "release_id": release_id,
            "canonical_endpoint": ROBUSTNESS_CANONICAL_ENDPOINT,
            "source_directory": destination.relative_to(root).as_posix(),
            "artifact_manifest_schema_version": FULL_POOL_PRODUCTION_MANIFEST_SCHEMA,
            "report_payload_schema_version": evidence.closure.report_payload_schema_version,
            "production_evidence_schema_version": FULL_POOL_PRODUCTION_EVIDENCE_SCHEMA,
            "implementation_commit": implementation_commit,
            "full_pool_source_directory": lineages["full_pool_source"]["directory"],
            "full_pool_source_identity": evidence.formal.full_pool_source_identity,
            "full_pool_source_manifest_sha256": (evidence.formal.full_pool_source_manifest_sha256),
            "full_pool_source_hash": evidence.formal.full_pool_source_hash,
            "full_pool_contract_sha256": evidence.formal.full_pool_contract_sha256,
            "historical_formal_directory": lineages["historical_formal_source"]["directory"],
            "historical_formal_source_id": evidence.formal.historical_formal_source_id,
            "historical_formal_manifest_sha256": (evidence.formal.historical_formal_manifest_sha256),
            "historical_study_directory": lineages["historical_study_source"]["directory"],
            "historical_study_manifest_sha256": (evidence.formal.historical_study_manifest_sha256),
            "historical_study_artifact_manifest_sha256": (evidence.closure.robustness_study_artifact_manifest_sha256),
            "historical_study_root_identity_sha256": (evidence.formal.historical_study_root_identity_sha256),
            "candidate_directory": lineages["candidate"]["directory"],
            "candidate_manifest_sha256": evidence.closure.candidate_manifest_sha256,
            "candidate_identity_sha256": evidence.closure.candidate_identity_sha256,
            "candidate_content_identity_sha256": (evidence.closure.candidate_content_identity_sha256),
            "presentation_closure_contract": lineages["presentation_closure"]["path"],
            "presentation_closure_contract_sha256": evidence.closure.closure_sha256,
            "presentation_closure_schema_version": evidence.closure.closure_schema_version,
            "source_lineage_identity_sha256": (evidence.closure.source_lineage_identity_sha256),
            "presentation_inventory_identity_sha256": (evidence.closure.presentation_inventory_identity_sha256),
            "mechanism_set_identity_sha256": evidence.closure.mechanism_set_identity_sha256,
            "trace_index_sha256": evidence.closure.trace_index_sha256,
            "full_pool_formal_facts": full_pool_facts,
            "historical_formal_facts": historical_formal_facts,
            "historical_study_facts": historical_study_facts,
            "fresh_execution_manifest": execution_manifest_file.relative_to(root).as_posix(),
            "fresh_execution_manifest_sha256": (evidence.execution_manifest.manifest_sha256),
            "fresh_execution_manifest_identity_sha256": (evidence.execution_manifest.manifest_identity_sha256),
            "fresh_execution_manifest_facts": v11_facts["fresh_execution_manifest_facts"],
            "strict_source_facts": v11_facts["strict_source_facts"],
            "strict_fresh_lineage_facts": v11_facts["strict_fresh_lineage_facts"],
            "strict_policy_facts": v11_facts["strict_policy_facts"],
            "strict_settlement_facts": v11_facts["strict_settlement_facts"],
            "operator_attempt_facts": v11_facts["operator_attempt_facts"],
            "physical_accounting_facts": v11_facts["physical_accounting_facts"],
            "result_projection_facts": v11_facts["result_projection_facts"],
            "rejected_mixed_history_facts": v11_facts["rejected_mixed_history_facts"],
            "execution_handoff": v11_facts["execution_handoff"],
            "physical_snapshot_identity_sha256": snapshot_identity,
            "release_identity_sha256": release_identity,
            "production_deploy_eligible": True,
            "artifact_sha256": dict(sorted(release_hashes.items())),
        }
        if set(contract_document) != _RELEASE_CONTRACT_V11_FIELDS:
            raise ConcurrentRobustnessReleaseError("v11 release contract fields are crossed")
        contract_staging.write_bytes(_json_bytes(contract_document))
        if destination.exists() or contract_path.exists():
            raise ConcurrentRobustnessReleaseError("v11 production destination or contract appeared during staging")
        os.replace(staging, destination)
        destination_installed = True
        os.replace(contract_staging, contract_path)
        contract_installed = True
        final_hashes = _flat_file_hashes(destination)
        if (
            final_hashes != contract_document["artifact_sha256"]
            or _physical_snapshot_identity(final_hashes) != snapshot_identity
        ):
            raise ConcurrentRobustnessReleaseError("v11 physical snapshot drifted after publication")
        round_trip = _validate_full_pool_v11_production_release(
            repo_root=root,
            contract_document=contract_document,
            source_dir=destination,
        )
        if (
            round_trip.get("production_deploy_eligible") is not True
            or round_trip.get("report_sha256") != final_hashes[CONCURRENT_MESSAGE_REPORT_HTML]
        ):
            raise ConcurrentRobustnessReleaseError("v11 standalone round-trip facts are crossed")
        _assert_v8_input_snapshots(snapshots)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if contract_staging.exists():
            contract_staging.unlink(missing_ok=True)
        if contract_installed:
            contract_path.unlink(missing_ok=True)
        if destination_installed:
            shutil.rmtree(destination, ignore_errors=True)
        raise
    return ConcurrentRobustnessProductionRelease(
        source_dir=destination,
        contract_path=contract_path,
        release_id=release_id,
        report_sha256=final_hashes[CONCURRENT_MESSAGE_REPORT_HTML],
        manifest_sha256=final_hashes[CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON],
        release_identity_sha256=release_identity,
    )


def _validate_full_pool_v8_production_release(
    *,
    repo_root: str | Path,
    contract_document: Mapping[str, object],
    source_dir: str | Path,
    snapshot_dir: str | Path | None = None,
) -> dict[str, object]:
    root = _real_directory(Path(repo_root), "repository root")
    if (
        contract_document.get("schema_version") != ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V8
        or set(contract_document) != _RELEASE_CONTRACT_V8_FIELDS
    ):
        raise ConcurrentRobustnessReleaseError(
            "v8 release contract fields are missing, unexpected, or schema-confused"
        )
    release_id = _string(contract_document.get("release_id"), "v8 release id")
    implementation_commit = _string(
        contract_document.get("implementation_commit"),
        "v8 implementation commit",
    )
    if not _RELEASE_ID.fullmatch(release_id) or not _COMMIT.fullmatch(implementation_commit):
        raise ConcurrentRobustnessReleaseError("v8 release or implementation identity is invalid")

    expected_source = _repo_directory(
        root,
        Path(
            _canonical_relative_path(
                contract_document.get("source_directory"),
                "v8 source directory",
            )
        ),
        "v8 contract source directory",
    )
    supplied_source = _real_directory(Path(source_dir), "v8 supplied source directory")
    if supplied_source != expected_source:
        raise ConcurrentRobustnessReleaseError(
            "v8 supplied source directory differs from the frozen contract"
        )
    evidence_dir = (
        _real_directory(Path(snapshot_dir), "v8 release snapshot")
        if snapshot_dir is not None
        else expected_source
    )

    full_pool = _repo_directory(
        root,
        Path(
            _canonical_relative_path(
                contract_document.get("full_pool_source_directory"),
                "v8 Full-Pool source directory",
            )
        ),
        "v8 Full-Pool source directory",
    )
    historical_formal = _repo_directory(
        root,
        Path(
            _canonical_relative_path(
                contract_document.get("historical_formal_directory"),
                "v8 historical Formal directory",
            )
        ),
        "v8 historical Formal directory",
    )
    historical_study = _repo_directory(
        root,
        Path(
            _canonical_relative_path(
                contract_document.get("historical_study_directory"),
                "v8 historical study directory",
            )
        ),
        "v8 historical study directory",
    )
    candidate = _repo_directory(
        root,
        Path(
            _canonical_relative_path(
                contract_document.get("candidate_directory"),
                "v8 candidate directory",
            )
        ),
        "v8 candidate directory",
    )
    closure_file = _repo_file(
        root,
        Path(
            _canonical_relative_path(
                contract_document.get("presentation_closure_contract"),
                "v8 presentation closure",
            )
        ),
        "v8 presentation closure",
    )
    try:
        evidence = _evidence.validate_full_pool_production_evidence(
            repo_root=root,
            closure_path=closure_file,
            full_pool_source_root=full_pool,
            full_pool_manifest_sha256=_string(
                contract_document.get("full_pool_source_manifest_sha256"),
                "v8 Full-Pool manifest hash",
            ),
            historical_formal_root=historical_formal,
            historical_study_root=historical_study,
            candidate_dir=candidate,
            implementation_commit=implementation_commit,
        )
    except ConcurrentRobustnessEvidenceError as exc:
        raise ConcurrentRobustnessReleaseError(str(exc)) from exc

    lineages = _v8_lineage_documents(root=root, evidence=evidence)
    full_pool_facts, historical_formal_facts, historical_study_facts = _v8_fact_documents(
        evidence.formal
    )
    supplied_full_pool_facts = _object_mapping(
        contract_document.get("full_pool_formal_facts"),
        "v8 Full-Pool Formal facts",
    )
    supplied_historical_formal = _object_mapping(
        contract_document.get("historical_formal_facts"),
        "v8 historical Formal facts",
    )
    supplied_historical_study = _object_mapping(
        contract_document.get("historical_study_facts"),
        "v8 historical study facts",
    )
    if (
        set(supplied_full_pool_facts) != _FULL_POOL_FORMAL_FACT_FIELDS
        or set(supplied_historical_formal) != _HISTORICAL_FORMAL_FACT_FIELDS
        or set(supplied_historical_study) != _HISTORICAL_STUDY_FACT_FIELDS
        or supplied_full_pool_facts != full_pool_facts
        or supplied_historical_formal != historical_formal_facts
        or supplied_historical_study != historical_study_facts
    ):
        raise ConcurrentRobustnessReleaseError("v8 Formal count, model, usage, or historical facts are crossed")
    expected_flat = {
        "release_purpose": "full_pool_formal_research",
        "canonical_endpoint": ROBUSTNESS_CANONICAL_ENDPOINT,
        "artifact_manifest_schema_version": FULL_POOL_PRODUCTION_MANIFEST_SCHEMA,
        "report_payload_schema_version": evidence.closure.report_payload_schema_version,
        "production_evidence_schema_version": FULL_POOL_PRODUCTION_EVIDENCE_SCHEMA,
        "full_pool_source_identity": evidence.formal.full_pool_source_identity,
        "full_pool_source_manifest_sha256": evidence.formal.full_pool_source_manifest_sha256,
        "full_pool_source_hash": evidence.formal.full_pool_source_hash,
        "full_pool_contract_sha256": evidence.formal.full_pool_contract_sha256,
        "historical_formal_source_id": evidence.formal.historical_formal_source_id,
        "historical_formal_manifest_sha256": evidence.formal.historical_formal_manifest_sha256,
        "historical_study_manifest_sha256": evidence.formal.historical_study_manifest_sha256,
        "historical_study_artifact_manifest_sha256": (
            evidence.closure.robustness_study_artifact_manifest_sha256
        ),
        "historical_study_root_identity_sha256": (
            evidence.formal.historical_study_root_identity_sha256
        ),
        "candidate_manifest_sha256": evidence.closure.candidate_manifest_sha256,
        "candidate_identity_sha256": evidence.closure.candidate_identity_sha256,
        "candidate_content_identity_sha256": evidence.closure.candidate_content_identity_sha256,
        "presentation_closure_contract_sha256": evidence.closure.closure_sha256,
        "presentation_closure_schema_version": evidence.closure.closure_schema_version,
        "source_lineage_identity_sha256": evidence.closure.source_lineage_identity_sha256,
        "presentation_inventory_identity_sha256": (
            evidence.closure.presentation_inventory_identity_sha256
        ),
        "mechanism_set_identity_sha256": evidence.closure.mechanism_set_identity_sha256,
        "trace_index_sha256": evidence.closure.trace_index_sha256,
        "production_deploy_eligible": True,
    }
    if any(contract_document.get(key) != value for key, value in expected_flat.items()):
        raise ConcurrentRobustnessReleaseError("v8 release contract identity or lineage is crossed")
    expected_paths = {
        "full_pool_source_directory": lineages["full_pool_source"]["directory"],
        "historical_formal_directory": lineages["historical_formal_source"]["directory"],
        "historical_study_directory": lineages["historical_study_source"]["directory"],
        "candidate_directory": lineages["candidate"]["directory"],
        "presentation_closure_contract": lineages["presentation_closure"]["path"],
    }
    if any(contract_document.get(key) != value for key, value in expected_paths.items()):
        raise ConcurrentRobustnessReleaseError("v8 explicit source paths are crossed")

    expected_hashes = _string_mapping(
        contract_document.get("artifact_sha256"),
        "v8 artifact SHA-256",
    )
    actual_hashes = _flat_file_hashes(evidence_dir)
    if actual_hashes != expected_hashes:
        raise ConcurrentRobustnessReleaseError(
            "v8 source inventory or artifact hashes differ from the contract"
        )
    release_identity = _string(
        contract_document.get("release_identity_sha256"),
        "v8 release identity",
    )
    if not _SHA256.fullmatch(release_identity):
        raise ConcurrentRobustnessReleaseError("v8 release identity is invalid")
    stage_facts = _full_pool_production_stage_facts(
        release_id=release_id,
        evidence=evidence,
    )
    _validate_full_pool_v8_release_dir(
        evidence_dir,
        repo_root=root,
        evidence=evidence,
        stage_facts=stage_facts,
        release_identity=release_identity,
    )
    return {
        "schema_version": ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V8,
        "release_purpose": "full_pool_formal_research",
        "release_id": release_id,
        "source_directory": contract_document["source_directory"],
        "sampling_method": FULL_POOL_MEMBERSHIP_METHOD,
        "sampling_status": "persisted_full_pool_formal_run",
        "decision_execution_mode": "live_provider",
        "live_api_triggered": evidence.formal.live_api_triggered,
        "logical_judgments": evidence.formal.logical_judgments,
        "physical_attempts": evidence.formal.physical_attempts,
        "report_sha256": actual_hashes[CONCURRENT_MESSAGE_REPORT_HTML],
        "artifact_count": len(actual_hashes),
        "production_deploy_eligible": True,
    }


def _validate_full_pool_v9_production_release(
    *,
    repo_root: str | Path,
    contract_document: Mapping[str, object],
    source_dir: str | Path,
    snapshot_dir: str | Path | None = None,
) -> dict[str, object]:
    root = _real_directory(Path(repo_root), "repository root")
    contract_fields = frozenset(contract_document)
    if (
        contract_document.get("schema_version") != ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V9
        or contract_fields
        not in {
            _RELEASE_CONTRACT_V9_FIELDS,
            _RELEASE_CONTRACT_V9_RECOVERY_FIELDS,
        }
    ):
        raise ConcurrentRobustnessReleaseError(
            "v9 release contract fields are missing, unexpected, or schema-confused"
        )
    release_id = _string(contract_document.get("release_id"), "v9 release id")
    implementation_commit = _string(
        contract_document.get("implementation_commit"), "v9 implementation commit"
    )
    if not _RELEASE_ID.fullmatch(release_id) or not _COMMIT.fullmatch(implementation_commit):
        raise ConcurrentRobustnessReleaseError("v9 release or implementation identity is invalid")
    expected_source = _repo_directory(
        root,
        Path(
            _canonical_relative_path(
                contract_document.get("source_directory"), "v9 source directory"
            )
        ),
        "v9 contract source directory",
    )
    supplied_source = _real_directory(Path(source_dir), "v9 supplied source directory")
    if supplied_source != expected_source:
        raise ConcurrentRobustnessReleaseError(
            "v9 supplied source directory differs from the frozen contract"
        )
    evidence_dir = (
        _real_directory(Path(snapshot_dir), "v9 release snapshot")
        if snapshot_dir is not None
        else expected_source
    )
    full_pool = _repo_directory(
        root,
        Path(
            _canonical_relative_path(
                contract_document.get("full_pool_source_directory"),
                "v9 segmented source directory",
            )
        ),
        "v9 segmented source directory",
    )
    historical_formal = _repo_directory(
        root,
        Path(
            _canonical_relative_path(
                contract_document.get("historical_formal_directory"),
                "v9 historical Formal directory",
            )
        ),
        "v9 historical Formal directory",
    )
    historical_study = _repo_directory(
        root,
        Path(
            _canonical_relative_path(
                contract_document.get("historical_study_directory"),
                "v9 historical study directory",
            )
        ),
        "v9 historical study directory",
    )
    candidate = _repo_directory(
        root,
        Path(
            _canonical_relative_path(
                contract_document.get("candidate_directory"), "v9 candidate directory"
            )
        ),
        "v9 candidate directory",
    )
    closure_file = _repo_file(
        root,
        Path(
            _canonical_relative_path(
                contract_document.get("presentation_closure_contract"),
                "v9 presentation closure",
            )
        ),
        "v9 presentation closure",
    )
    try:
        evidence = _evidence.validate_segmented_full_pool_production_evidence(
            repo_root=root,
            closure_path=closure_file,
            full_pool_source_root=full_pool,
            full_pool_manifest_sha256=_string(
                contract_document.get("full_pool_source_manifest_sha256"),
                "v9 source-v2 manifest hash",
            ),
            historical_formal_root=historical_formal,
            historical_study_root=historical_study,
            candidate_dir=candidate,
            implementation_commit=implementation_commit,
        )
    except ConcurrentRobustnessEvidenceError as exc:
        raise ConcurrentRobustnessReleaseError(str(exc)) from exc
    base_evidence = _v9_base_evidence(evidence)
    lineages = _v8_lineage_documents(root=root, evidence=base_evidence)
    full_pool_facts, historical_formal_facts, historical_study_facts = _v8_fact_documents(
        evidence.formal
    )
    segmented_facts = _v9_segmented_fact_document(evidence.segmented)
    recovery_lineage_facts, recovery_accounting_facts = _v9_recovery_fact_documents(
        evidence.segmented
    )
    if recovery_lineage_facts is None or recovery_accounting_facts is None:
        recovery_facts_exact = contract_fields == _RELEASE_CONTRACT_V9_FIELDS
    else:
        supplied_recovery_lineage = _object_mapping(
            contract_document.get("recovery_lineage_facts"),
            "v9 recovery lineage facts",
        )
        supplied_recovery_accounting = _object_mapping(
            contract_document.get("recovery_accounting_facts"),
            "v9 recovery accounting facts",
        )
        recovery_facts_exact = (
            contract_fields == _RELEASE_CONTRACT_V9_RECOVERY_FIELDS
            and set(supplied_recovery_lineage) == _RECOVERY_LINEAGE_FACT_FIELDS
            and set(supplied_recovery_accounting) == _RECOVERY_ACCOUNTING_FACT_FIELDS
            and supplied_recovery_lineage == recovery_lineage_facts
            and supplied_recovery_accounting == recovery_accounting_facts
        )
    supplied_full_pool = _object_mapping(
        contract_document.get("full_pool_formal_facts"), "v9 Full-Pool Formal facts"
    )
    supplied_historical = _object_mapping(
        contract_document.get("historical_formal_facts"), "v9 historical Formal facts"
    )
    supplied_study = _object_mapping(
        contract_document.get("historical_study_facts"), "v9 historical study facts"
    )
    supplied_segmented = _object_mapping(
        contract_document.get("segmented_source_facts"), "v9 segmented source facts"
    )
    if (
        set(supplied_full_pool) != _FULL_POOL_FORMAL_FACT_FIELDS
        or set(supplied_historical) != _HISTORICAL_FORMAL_FACT_FIELDS
        or set(supplied_study) != _HISTORICAL_STUDY_FACT_FIELDS
        or set(supplied_segmented) != _SEGMENTED_SOURCE_FACT_FIELDS
        or supplied_full_pool != full_pool_facts
        or supplied_historical != historical_formal_facts
        or supplied_study != historical_study_facts
        or supplied_segmented != segmented_facts
        or not recovery_facts_exact
    ):
        raise ConcurrentRobustnessReleaseError(
            "v9 segmented, model, usage, count, or historical facts are crossed"
        )
    expected_flat = {
        "release_purpose": "full_pool_segmented_formal_research",
        "canonical_endpoint": ROBUSTNESS_CANONICAL_ENDPOINT,
        "artifact_manifest_schema_version": FULL_POOL_PRODUCTION_MANIFEST_SCHEMA,
        "report_payload_schema_version": evidence.closure.report_payload_schema_version,
        "production_evidence_schema_version": FULL_POOL_PRODUCTION_EVIDENCE_SCHEMA,
        "full_pool_source_identity": evidence.formal.full_pool_source_identity,
        "full_pool_source_manifest_sha256": evidence.formal.full_pool_source_manifest_sha256,
        "full_pool_source_hash": evidence.formal.full_pool_source_hash,
        "full_pool_contract_sha256": evidence.formal.full_pool_contract_sha256,
        "historical_formal_source_id": evidence.formal.historical_formal_source_id,
        "historical_formal_manifest_sha256": evidence.formal.historical_formal_manifest_sha256,
        "historical_study_manifest_sha256": evidence.formal.historical_study_manifest_sha256,
        "historical_study_artifact_manifest_sha256": (
            evidence.closure.robustness_study_artifact_manifest_sha256
        ),
        "historical_study_root_identity_sha256": (
            evidence.formal.historical_study_root_identity_sha256
        ),
        "candidate_manifest_sha256": evidence.closure.candidate_manifest_sha256,
        "candidate_identity_sha256": evidence.closure.candidate_identity_sha256,
        "candidate_content_identity_sha256": evidence.closure.candidate_content_identity_sha256,
        "presentation_closure_contract_sha256": evidence.closure.closure_sha256,
        "presentation_closure_schema_version": evidence.closure.closure_schema_version,
        "source_lineage_identity_sha256": evidence.closure.source_lineage_identity_sha256,
        "presentation_inventory_identity_sha256": (
            evidence.closure.presentation_inventory_identity_sha256
        ),
        "mechanism_set_identity_sha256": evidence.closure.mechanism_set_identity_sha256,
        "trace_index_sha256": evidence.closure.trace_index_sha256,
        "production_deploy_eligible": True,
    }
    if any(contract_document.get(key) != value for key, value in expected_flat.items()):
        raise ConcurrentRobustnessReleaseError("v9 release contract identity or lineage is crossed")
    expected_paths = {
        "full_pool_source_directory": lineages["full_pool_source"]["directory"],
        "historical_formal_directory": lineages["historical_formal_source"]["directory"],
        "historical_study_directory": lineages["historical_study_source"]["directory"],
        "candidate_directory": lineages["candidate"]["directory"],
        "presentation_closure_contract": lineages["presentation_closure"]["path"],
    }
    if any(contract_document.get(key) != value for key, value in expected_paths.items()):
        raise ConcurrentRobustnessReleaseError("v9 explicit source paths are crossed")
    expected_hashes = _string_mapping(
        contract_document.get("artifact_sha256"), "v9 artifact SHA-256"
    )
    actual_hashes = _flat_file_hashes(evidence_dir)
    snapshot_identity = _string(
        contract_document.get("physical_snapshot_identity_sha256"),
        "v9 physical snapshot identity",
    )
    if (
        actual_hashes != expected_hashes
        or not _SHA256.fullmatch(snapshot_identity)
        or _physical_snapshot_identity(actual_hashes) != snapshot_identity
    ):
        raise ConcurrentRobustnessReleaseError(
            "v9 physical source inventory, snapshot identity, or artifact hashes differ"
        )
    release_identity = _string(
        contract_document.get("release_identity_sha256"), "v9 release identity"
    )
    if not _SHA256.fullmatch(release_identity):
        raise ConcurrentRobustnessReleaseError("v9 release identity is invalid")
    stage_facts = _full_pool_production_stage_facts(
        release_id=release_id,
        evidence=base_evidence,
        release_contract_schema=ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V9,
    )
    _validate_full_pool_v8_release_dir(
        evidence_dir,
        repo_root=root,
        evidence=base_evidence,
        stage_facts=stage_facts,
        release_identity=release_identity,
    )
    return {
        "schema_version": ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V9,
        "release_purpose": "full_pool_segmented_formal_research",
        "release_id": release_id,
        "source_directory": contract_document["source_directory"],
        "sampling_method": FULL_POOL_MEMBERSHIP_METHOD,
        "sampling_status": "persisted_full_pool_segmented_formal_run",
        "decision_execution_mode": "live_provider",
        "live_api_triggered": True,
        "logical_judgments": evidence.segmented.logical_judgments,
        "physical_attempts": evidence.segmented.physical_attempts,
        "report_sha256": actual_hashes[CONCURRENT_MESSAGE_REPORT_HTML],
        "artifact_count": len(actual_hashes),
        "production_deploy_eligible": True,
    }


def _validate_full_pool_v10_production_release(
    *,
    repo_root: str | Path,
    contract_document: Mapping[str, object],
    source_dir: str | Path,
    snapshot_dir: str | Path | None = None,
) -> dict[str, object]:
    root = _real_directory(Path(repo_root), "repository root")
    if (
        contract_document.get("schema_version")
        != ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V10
        or set(contract_document) != _RELEASE_CONTRACT_V10_FIELDS
    ):
        raise ConcurrentRobustnessReleaseError(
            "v10 release contract fields are missing, unexpected, or schema-confused"
        )
    release_id = _string(contract_document.get("release_id"), "v10 release id")
    implementation_commit = _string(
        contract_document.get("implementation_commit"), "v10 implementation commit"
    )
    if not _RELEASE_ID.fullmatch(release_id) or not _COMMIT.fullmatch(
        implementation_commit
    ):
        raise ConcurrentRobustnessReleaseError("v10 release or implementation identity is invalid")
    expected_source = _repo_directory(
        root,
        Path(
            _canonical_relative_path(
                contract_document.get("source_directory"), "v10 source directory"
            )
        ),
        "v10 contract source directory",
    )
    supplied_source = _real_directory(Path(source_dir), "v10 supplied source directory")
    if supplied_source != expected_source:
        raise ConcurrentRobustnessReleaseError(
            "v10 supplied source directory differs from the frozen contract"
        )
    evidence_dir = (
        _real_directory(Path(snapshot_dir), "v10 release snapshot")
        if snapshot_dir is not None
        else expected_source
    )
    full_pool = _repo_directory(
        root,
        Path(
            _canonical_relative_path(
                contract_document.get("full_pool_source_directory"),
                "v10 source-v3 directory",
            )
        ),
        "v10 source-v3 directory",
    )
    historical_formal = _repo_directory(
        root,
        Path(
            _canonical_relative_path(
                contract_document.get("historical_formal_directory"),
                "v10 historical Formal directory",
            )
        ),
        "v10 historical Formal directory",
    )
    historical_study = _repo_directory(
        root,
        Path(
            _canonical_relative_path(
                contract_document.get("historical_study_directory"),
                "v10 historical study directory",
            )
        ),
        "v10 historical study directory",
    )
    candidate = _repo_directory(
        root,
        Path(
            _canonical_relative_path(
                contract_document.get("candidate_directory"),
                "v10 candidate directory",
            )
        ),
        "v10 candidate directory",
    )
    closure_file = _repo_file(
        root,
        Path(
            _canonical_relative_path(
                contract_document.get("presentation_closure_contract"),
                "v10 presentation closure",
            )
        ),
        "v10 presentation closure",
    )
    execution_manifest = _repo_file(
        root,
        Path(
            _canonical_relative_path(
                contract_document.get("automation_execution_manifest"),
                "v10 automation execution manifest",
            )
        ),
        "v10 automation execution manifest",
    )
    try:
        evidence = _evidence.validate_nested_full_pool_production_evidence(
            repo_root=root,
            closure_path=closure_file,
            full_pool_source_root=full_pool,
            full_pool_manifest_sha256=_string(
                contract_document.get("full_pool_source_manifest_sha256"),
                "v10 source-v3 manifest hash",
            ),
            historical_formal_root=historical_formal,
            historical_study_root=historical_study,
            candidate_dir=candidate,
            automation_execution_manifest_path=execution_manifest,
            implementation_commit=implementation_commit,
        )
    except ConcurrentRobustnessEvidenceError as exc:
        raise ConcurrentRobustnessReleaseError(str(exc)) from exc
    base_evidence = _v10_base_evidence(evidence)
    lineages = _v8_lineage_documents(root=root, evidence=base_evidence)
    full_pool_facts, historical_formal_facts, historical_study_facts = _v8_fact_documents(
        evidence.formal
    )
    v10_facts = _v10_fact_documents(root=root, evidence=evidence)
    supplied_documents = {
        "nested_source_facts": _object_mapping(
            contract_document.get("nested_source_facts"), "v10 nested source facts"
        ),
        "nested_recovery_lineage_facts": _object_mapping(
            contract_document.get("nested_recovery_lineage_facts"),
            "v10 nested recovery lineage facts",
        ),
        "automated_recovery_policy_facts": _object_mapping(
            contract_document.get("automated_recovery_policy_facts"),
            "v10 automated policy facts",
        ),
        "settlement_v2_facts": _object_mapping(
            contract_document.get("settlement_v2_facts"), "v10 settlement facts"
        ),
        "recovery_accounting_facts": _object_mapping(
            contract_document.get("recovery_accounting_facts"),
            "v10 recovery accounting facts",
        ),
        "automation_execution_manifest_facts": _object_mapping(
            contract_document.get("automation_execution_manifest_facts"),
            "v10 execution manifest facts",
        ),
        "result_projection_facts": _object_mapping(
            contract_document.get("result_projection_facts"),
            "v10 result projection facts",
        ),
    }
    if supplied_documents != v10_facts:
        raise ConcurrentRobustnessReleaseError(
            "v10 nested lineage, settlement, policy, manifest, or result facts are crossed"
        )
    if (
        _object_mapping(
            contract_document.get("full_pool_formal_facts"),
            "v10 Full-Pool Formal facts",
        )
        != full_pool_facts
        or _object_mapping(
            contract_document.get("historical_formal_facts"),
            "v10 historical Formal facts",
        )
        != historical_formal_facts
        or _object_mapping(
            contract_document.get("historical_study_facts"),
            "v10 historical study facts",
        )
        != historical_study_facts
    ):
        raise ConcurrentRobustnessReleaseError(
            "v10 model, usage, count, or historical facts are crossed"
        )
    expected_flat = {
        "release_purpose": "full_pool_automated_nested_formal_research",
        "canonical_endpoint": ROBUSTNESS_CANONICAL_ENDPOINT,
        "artifact_manifest_schema_version": FULL_POOL_PRODUCTION_MANIFEST_SCHEMA,
        "report_payload_schema_version": evidence.closure.report_payload_schema_version,
        "production_evidence_schema_version": FULL_POOL_PRODUCTION_EVIDENCE_SCHEMA,
        "full_pool_source_identity": evidence.formal.full_pool_source_identity,
        "full_pool_source_manifest_sha256": evidence.formal.full_pool_source_manifest_sha256,
        "full_pool_source_hash": evidence.formal.full_pool_source_hash,
        "full_pool_contract_sha256": evidence.formal.full_pool_contract_sha256,
        "historical_formal_source_id": evidence.formal.historical_formal_source_id,
        "historical_formal_manifest_sha256": evidence.formal.historical_formal_manifest_sha256,
        "historical_study_manifest_sha256": evidence.formal.historical_study_manifest_sha256,
        "historical_study_artifact_manifest_sha256": (
            evidence.closure.robustness_study_artifact_manifest_sha256
        ),
        "historical_study_root_identity_sha256": (
            evidence.formal.historical_study_root_identity_sha256
        ),
        "candidate_manifest_sha256": evidence.closure.candidate_manifest_sha256,
        "candidate_identity_sha256": evidence.closure.candidate_identity_sha256,
        "candidate_content_identity_sha256": evidence.closure.candidate_content_identity_sha256,
        "presentation_closure_contract_sha256": evidence.closure.closure_sha256,
        "presentation_closure_schema_version": evidence.closure.closure_schema_version,
        "source_lineage_identity_sha256": evidence.closure.source_lineage_identity_sha256,
        "presentation_inventory_identity_sha256": (
            evidence.closure.presentation_inventory_identity_sha256
        ),
        "mechanism_set_identity_sha256": evidence.closure.mechanism_set_identity_sha256,
        "trace_index_sha256": evidence.closure.trace_index_sha256,
        "automation_execution_manifest_sha256": evidence.execution_manifest.manifest_sha256,
        "automation_execution_manifest_identity_sha256": (
            evidence.execution_manifest.manifest_identity_sha256
        ),
        "production_deploy_eligible": True,
    }
    if any(contract_document.get(key) != value for key, value in expected_flat.items()):
        raise ConcurrentRobustnessReleaseError("v10 release identity or lineage is crossed")
    expected_paths = {
        "full_pool_source_directory": lineages["full_pool_source"]["directory"],
        "historical_formal_directory": lineages["historical_formal_source"]["directory"],
        "historical_study_directory": lineages["historical_study_source"]["directory"],
        "candidate_directory": lineages["candidate"]["directory"],
        "presentation_closure_contract": lineages["presentation_closure"]["path"],
        "automation_execution_manifest": execution_manifest.relative_to(root).as_posix(),
    }
    if any(contract_document.get(key) != value for key, value in expected_paths.items()):
        raise ConcurrentRobustnessReleaseError("v10 explicit source paths are crossed")
    expected_hashes = _string_mapping(
        contract_document.get("artifact_sha256"), "v10 artifact SHA-256"
    )
    actual_hashes = _flat_file_hashes(evidence_dir)
    snapshot_identity = _string(
        contract_document.get("physical_snapshot_identity_sha256"),
        "v10 physical snapshot identity",
    )
    if (
        actual_hashes != expected_hashes
        or not _SHA256.fullmatch(snapshot_identity)
        or _physical_snapshot_identity(actual_hashes) != snapshot_identity
    ):
        raise ConcurrentRobustnessReleaseError(
            "v10 physical source inventory, snapshot identity, or hashes differ"
        )
    release_identity = _string(
        contract_document.get("release_identity_sha256"), "v10 release identity"
    )
    if not _SHA256.fullmatch(release_identity):
        raise ConcurrentRobustnessReleaseError("v10 release identity is invalid")
    stage_facts = _full_pool_production_stage_facts(
        release_id=release_id,
        evidence=base_evidence,
        release_contract_schema=ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V10,
    )
    _validate_full_pool_v8_release_dir(
        evidence_dir,
        repo_root=root,
        evidence=base_evidence,
        stage_facts=stage_facts,
        release_identity=release_identity,
    )
    return {
        "schema_version": ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V10,
        "release_purpose": "full_pool_automated_nested_formal_research",
        "release_id": release_id,
        "source_directory": contract_document["source_directory"],
        "sampling_method": FULL_POOL_MEMBERSHIP_METHOD,
        "sampling_status": "persisted_full_pool_automated_nested_formal_run",
        "decision_execution_mode": "live_provider",
        "live_api_triggered": True,
        "logical_judgments": evidence.automated.logical_judgments,
        "physical_attempts": evidence.automated.physical_attempts,
        "report_sha256": actual_hashes[CONCURRENT_MESSAGE_REPORT_HTML],
        "artifact_count": len(actual_hashes),
        "production_deploy_eligible": True,
    }


def _validate_full_pool_v11_production_release(
    *,
    repo_root: str | Path,
    contract_document: Mapping[str, object],
    source_dir: str | Path,
    snapshot_dir: str | Path | None = None,
) -> dict[str, object]:
    root = _real_directory(Path(repo_root), "repository root")
    if (
        contract_document.get("schema_version") != ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V11
        or set(contract_document) != _RELEASE_CONTRACT_V11_FIELDS
    ):
        raise ConcurrentRobustnessReleaseError(
            "v11 release contract fields are missing, unexpected, or schema-confused"
        )
    release_id = _string(contract_document.get("release_id"), "v11 release id")
    implementation_commit = _string(contract_document.get("implementation_commit"), "v11 implementation commit")
    if not _RELEASE_ID.fullmatch(release_id) or not _COMMIT.fullmatch(implementation_commit):
        raise ConcurrentRobustnessReleaseError("v11 release or implementation identity is invalid")
    expected_source = _repo_directory(
        root,
        Path(_canonical_relative_path(contract_document.get("source_directory"), "v11 source directory")),
        "v11 contract source directory",
    )
    supplied_source = _real_directory(Path(source_dir), "v11 supplied source directory")
    if supplied_source != expected_source:
        raise ConcurrentRobustnessReleaseError("v11 supplied source directory differs from the frozen contract")
    evidence_dir = (
        _real_directory(Path(snapshot_dir), "v11 release snapshot") if snapshot_dir is not None else expected_source
    )
    full_pool = _repo_directory(
        root,
        Path(
            _canonical_relative_path(
                contract_document.get("full_pool_source_directory"),
                "v11 source-v4 directory",
            )
        ),
        "v11 source-v4 directory",
    )
    historical_formal = _repo_directory(
        root,
        Path(
            _canonical_relative_path(
                contract_document.get("historical_formal_directory"),
                "v11 historical Formal directory",
            )
        ),
        "v11 historical Formal directory",
    )
    historical_study = _repo_directory(
        root,
        Path(
            _canonical_relative_path(
                contract_document.get("historical_study_directory"),
                "v11 historical study directory",
            )
        ),
        "v11 historical study directory",
    )
    candidate = _repo_directory(
        root,
        Path(
            _canonical_relative_path(
                contract_document.get("candidate_directory"),
                "v11 candidate directory",
            )
        ),
        "v11 candidate directory",
    )
    closure_file = _repo_file(
        root,
        Path(
            _canonical_relative_path(
                contract_document.get("presentation_closure_contract"),
                "v11 presentation closure",
            )
        ),
        "v11 presentation closure",
    )
    execution_manifest = _repo_file(
        root,
        Path(
            _canonical_relative_path(
                contract_document.get("fresh_execution_manifest"),
                "v11 fresh execution manifest",
            )
        ),
        "v11 fresh execution manifest",
    )
    try:
        evidence = _evidence.validate_strict_full_pool_production_evidence(
            repo_root=root,
            closure_path=closure_file,
            full_pool_source_root=full_pool,
            full_pool_manifest_sha256=_string(
                contract_document.get("full_pool_source_manifest_sha256"),
                "v11 source-v4 manifest hash",
            ),
            historical_formal_root=historical_formal,
            historical_study_root=historical_study,
            candidate_dir=candidate,
            fresh_execution_manifest_path=execution_manifest,
            implementation_commit=implementation_commit,
        )
    except ConcurrentRobustnessEvidenceError as exc:
        raise ConcurrentRobustnessReleaseError(str(exc)) from exc
    base_evidence = _v11_base_evidence(evidence)
    lineages = _v8_lineage_documents(root=root, evidence=base_evidence)
    full_pool_facts, historical_formal_facts, historical_study_facts = _v8_fact_documents(evidence.formal)
    v11_facts = _v11_fact_documents(root=root, release_id=release_id, evidence=evidence)
    supplied_documents = {
        key: _object_mapping(contract_document.get(key), f"v11 {key}")
        for key in (
            "fresh_execution_manifest_facts",
            "strict_source_facts",
            "strict_fresh_lineage_facts",
            "strict_policy_facts",
            "strict_settlement_facts",
            "operator_attempt_facts",
            "physical_accounting_facts",
            "result_projection_facts",
            "rejected_mixed_history_facts",
            "execution_handoff",
        )
    }
    if supplied_documents != v11_facts:
        raise ConcurrentRobustnessReleaseError(
            "v11 fresh manifest, source, settlement, policy, attempt, projection, or handoff facts are crossed"
        )
    if (
        _object_mapping(
            contract_document.get("full_pool_formal_facts"),
            "v11 Full-Pool Formal facts",
        )
        != full_pool_facts
        or _object_mapping(
            contract_document.get("historical_formal_facts"),
            "v11 historical Formal facts",
        )
        != historical_formal_facts
        or _object_mapping(
            contract_document.get("historical_study_facts"),
            "v11 historical study facts",
        )
        != historical_study_facts
    ):
        raise ConcurrentRobustnessReleaseError("v11 model, usage, count, or historical facts are crossed")
    expected_flat = {
        "release_purpose": "full_pool_strict_fresh_formal_research",
        "canonical_endpoint": ROBUSTNESS_CANONICAL_ENDPOINT,
        "artifact_manifest_schema_version": FULL_POOL_PRODUCTION_MANIFEST_SCHEMA,
        "report_payload_schema_version": evidence.closure.report_payload_schema_version,
        "production_evidence_schema_version": FULL_POOL_PRODUCTION_EVIDENCE_SCHEMA,
        "full_pool_source_identity": evidence.formal.full_pool_source_identity,
        "full_pool_source_manifest_sha256": (evidence.formal.full_pool_source_manifest_sha256),
        "full_pool_source_hash": evidence.formal.full_pool_source_hash,
        "full_pool_contract_sha256": evidence.formal.full_pool_contract_sha256,
        "historical_formal_source_id": evidence.formal.historical_formal_source_id,
        "historical_formal_manifest_sha256": (evidence.formal.historical_formal_manifest_sha256),
        "historical_study_manifest_sha256": (evidence.formal.historical_study_manifest_sha256),
        "historical_study_artifact_manifest_sha256": (evidence.closure.robustness_study_artifact_manifest_sha256),
        "historical_study_root_identity_sha256": (evidence.formal.historical_study_root_identity_sha256),
        "candidate_manifest_sha256": evidence.closure.candidate_manifest_sha256,
        "candidate_identity_sha256": evidence.closure.candidate_identity_sha256,
        "candidate_content_identity_sha256": (evidence.closure.candidate_content_identity_sha256),
        "presentation_closure_contract_sha256": evidence.closure.closure_sha256,
        "presentation_closure_schema_version": evidence.closure.closure_schema_version,
        "source_lineage_identity_sha256": (evidence.closure.source_lineage_identity_sha256),
        "presentation_inventory_identity_sha256": (evidence.closure.presentation_inventory_identity_sha256),
        "mechanism_set_identity_sha256": evidence.closure.mechanism_set_identity_sha256,
        "trace_index_sha256": evidence.closure.trace_index_sha256,
        "fresh_execution_manifest_sha256": evidence.execution_manifest.manifest_sha256,
        "fresh_execution_manifest_identity_sha256": (evidence.execution_manifest.manifest_identity_sha256),
        "production_deploy_eligible": True,
    }
    if any(contract_document.get(key) != value for key, value in expected_flat.items()):
        raise ConcurrentRobustnessReleaseError("v11 release identity or lineage is crossed")
    expected_paths = {
        "full_pool_source_directory": lineages["full_pool_source"]["directory"],
        "historical_formal_directory": lineages["historical_formal_source"]["directory"],
        "historical_study_directory": lineages["historical_study_source"]["directory"],
        "candidate_directory": lineages["candidate"]["directory"],
        "presentation_closure_contract": lineages["presentation_closure"]["path"],
        "fresh_execution_manifest": execution_manifest.relative_to(root).as_posix(),
    }
    if any(contract_document.get(key) != value for key, value in expected_paths.items()):
        raise ConcurrentRobustnessReleaseError("v11 explicit source paths are crossed")
    expected_hashes = _string_mapping(contract_document.get("artifact_sha256"), "v11 artifact SHA-256")
    actual_hashes = _flat_file_hashes(evidence_dir)
    snapshot_identity = _string(
        contract_document.get("physical_snapshot_identity_sha256"),
        "v11 physical snapshot identity",
    )
    if (
        actual_hashes != expected_hashes
        or not _SHA256.fullmatch(snapshot_identity)
        or _physical_snapshot_identity(actual_hashes) != snapshot_identity
    ):
        raise ConcurrentRobustnessReleaseError("v11 physical source inventory, snapshot identity, or hashes differ")
    release_identity = _string(contract_document.get("release_identity_sha256"), "v11 release identity")
    if not _SHA256.fullmatch(release_identity):
        raise ConcurrentRobustnessReleaseError("v11 release identity is invalid")
    stage_facts = _full_pool_production_stage_facts(
        release_id=release_id,
        evidence=base_evidence,
        release_contract_schema=ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V11,
    )
    _validate_full_pool_v8_release_dir(
        evidence_dir,
        repo_root=root,
        evidence=base_evidence,
        stage_facts=stage_facts,
        release_identity=release_identity,
    )
    return {
        "schema_version": ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V11,
        "release_purpose": "full_pool_strict_fresh_formal_research",
        "release_id": release_id,
        "source_directory": contract_document["source_directory"],
        "sampling_method": FULL_POOL_MEMBERSHIP_METHOD,
        "sampling_status": "persisted_strict_fresh_full_pool_formal_run",
        "decision_execution_mode": "live_provider",
        "live_api_triggered": True,
        "logical_judgments": evidence.strict_source.logical_pairs,
        "physical_attempts": evidence.strict_source.charged_physical_attempts,
        "report_sha256": actual_hashes[CONCURRENT_MESSAGE_REPORT_HTML],
        "artifact_count": len(actual_hashes),
        "production_deploy_eligible": True,
    }


def validate_concurrent_robustness_production_release(
    *,
    repo_root: str | Path,
    contract_document: Mapping[str, object],
    source_dir: str | Path,
    snapshot_dir: str | Path | None = None,
) -> dict[str, object]:
    """Fail-closed validator used by the production deployment gate."""
    schema_version = contract_document.get("schema_version")
    if schema_version == ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V11:
        return _validate_full_pool_v11_production_release(
            repo_root=repo_root,
            contract_document=contract_document,
            source_dir=source_dir,
            snapshot_dir=snapshot_dir,
        )
    if schema_version == ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V10:
        return _validate_full_pool_v10_production_release(
            repo_root=repo_root,
            contract_document=contract_document,
            source_dir=source_dir,
            snapshot_dir=snapshot_dir,
        )
    if schema_version == ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V9:
        return _validate_full_pool_v9_production_release(
            repo_root=repo_root,
            contract_document=contract_document,
            source_dir=source_dir,
            snapshot_dir=snapshot_dir,
        )
    if schema_version == ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V8:
        return _validate_full_pool_v8_production_release(
            repo_root=repo_root,
            contract_document=contract_document,
            source_dir=source_dir,
            snapshot_dir=snapshot_dir,
        )
    root = _real_directory(Path(repo_root), "repository root")
    if not isinstance(schema_version, str) or schema_version not in _RELEASE_CONTRACT_FIELDS:
        raise ConcurrentRobustnessReleaseError("unsupported Concurrent Robustness release contract")
    if set(contract_document) != _RELEASE_CONTRACT_FIELDS[schema_version]:
        version = schema_version.rsplit("-", 1)[-1]
        raise ConcurrentRobustnessReleaseError(
            f"{version} release contract fields are missing or unexpected"
        )
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
    expected_report_schema = (
        _REPORT_PAYLOAD_SCHEMA_V2
        if schema_version == ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V7
        else _REPORT_PAYLOAD_SCHEMA_V1
    )
    if (
        contract_document.get("release_purpose") != "concurrent_robustness_formal_research"
        or contract_document.get("canonical_endpoint") != ROBUSTNESS_CANONICAL_ENDPOINT
        or contract_document.get("artifact_manifest_schema_version") != ROBUSTNESS_PRODUCTION_MANIFEST_SCHEMA
        or contract_document.get("report_payload_schema_version") != expected_report_schema
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
    if schema_version in {
        ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V6,
        ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V7,
    }:
        if actual_hashes.get(ROBUSTNESS_PRESENTATION_CLOSURE_CONTRACT) != contract_document.get(
            "presentation_closure_contract_sha256"
        ):
            raise ConcurrentRobustnessReleaseError("release closure artifact hash is crossed")
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
    if schema_version in {
        ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V6,
        ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V7,
    }:
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
            raise ConcurrentRobustnessReleaseError("presentation closure contract hash is crossed")
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
            if schema_version == ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V6 and (
                closure_facts.closure_schema_version != _evidence.PRESENTATION_CLOSURE_SCHEMA
                or closure_facts.report_payload_schema_version != _REPORT_PAYLOAD_SCHEMA_V1
                or closure_facts.semantic_set_identity_sha256 is not None
            ):
                raise ConcurrentRobustnessReleaseError("v6 closure facts are crossed")
            if schema_version == ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V7 and (
                closure_facts.closure_schema_version != _evidence.PRESENTATION_CLOSURE_V2_SCHEMA
                or closure_facts.report_payload_schema_version != _REPORT_PAYLOAD_SCHEMA_V2
                or contract_document.get("presentation_closure_schema_version")
                != closure_facts.closure_schema_version
                or contract_document.get("semantic_set_identity_sha256")
                != closure_facts.semantic_set_identity_sha256
            ):
                raise ConcurrentRobustnessReleaseError("v7 closure semantic identity is crossed")
        except ConcurrentRobustnessEvidenceError as exc:
            raise ConcurrentRobustnessReleaseError(str(exc)) from exc
    if schema_version == ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V7:
        expected_presentation = _materialize_production_presentation(
            formal=formal,
            study=study,
            candidate=candidate,
            stage_facts=stage_facts,
        )
        if (
            expected_presentation.report_payload
            != (evidence_dir / ROBUSTNESS_REPORT_PAYLOAD).read_bytes()
            or expected_presentation.report_html
            != (evidence_dir / CONCURRENT_MESSAGE_REPORT_HTML).read_bytes()
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


def _validate_v7_presentation_inventory(inventory: Mapping[str, object]) -> None:
    paths = set(inventory)
    mermaid_paths = {path for path in paths if path.endswith(".mmd")}
    if mermaid_paths != _V7_MERMAID_INVENTORY:
        raise ConcurrentRobustnessReleaseError(
            "v7 production inventory must contain exactly seven Mermaid artifacts"
        )
    if any(
        path in _V7_EXCLUDED_PRESENTATION_ARTIFACTS
        or path.endswith("-v4.png")
        or path.endswith("-v4.webp")
        for path in paths
    ):
        raise ConcurrentRobustnessReleaseError(
            "v7 production inventory contains an excluded presentation artifact"
        )


def _production_approved_downloads(candidate_report_payload: Mapping[str, Any]) -> dict[str, str]:
    downloads = _string_mapping(candidate_report_payload.get("downloads"), "candidate report downloads")
    if ROBUSTNESS_PRESENTATION_CLOSURE_CONTRACT in downloads.values():
        raise ConcurrentRobustnessReleaseError("presentation closure cannot be a Report approved download")
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
    report_payload_schema_version: str,
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
        "report_schema": report_payload_schema_version,
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
    expected_report_schema = (
        _REPORT_PAYLOAD_SCHEMA_V2
        if stage_facts.release_contract_schema == ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V7
        else _REPORT_PAYLOAD_SCHEMA_V1
    )
    if (
        manifest.get("schema_version") != ROBUSTNESS_PRODUCTION_MANIFEST_SCHEMA
        or manifest.get("release_type") != "concurrent_robustness_formal_research"
        or manifest.get("release_id") != release_id
        or manifest.get("canonical_endpoint") != ROBUSTNESS_CANONICAL_ENDPOINT
        or manifest.get("report_schema") != expected_report_schema
        or manifest.get("production_deploy_eligible") is not True
        or evidence.get("schema_version") != ROBUSTNESS_PRODUCTION_EVIDENCE_SCHEMA
        or evidence.get("release_id") != release_id
        or evidence.get("production_deploy_eligible") is not True
        or type(evidence.get("provider_calls_during_promotion")) is not int
        or evidence.get("provider_calls_during_promotion") != 0
        or evidence.get("subscription_billed_cost_usd") != 0.0
        or payload.get("schema_version") != expected_report_schema
        or payload.get("production_deploy_eligible") is not True
    ):
        raise ConcurrentRobustnessReleaseError("production release schema or eligibility contract is invalid")
    if _validate_production_report_payload_contract(source=source, payload=payload) != expected_report_schema:
        raise ConcurrentRobustnessReleaseError("production report payload schema is crossed")
    if stage_facts.release_contract_schema == ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V7:
        _validate_v7_presentation_inventory(hashes)
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
        or ROBUSTNESS_PRESENTATION_CLOSURE_CONTRACT in approved_downloads.values()
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


def _object_mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ConcurrentRobustnessReleaseError(f"{label} must be an object")
    return {str(key): item for key, item in value.items()}


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
