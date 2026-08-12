from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import math
import os
import re
import shutil
import tempfile
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from .concurrent_message_renderer import render_report
from .concurrent_message_report import (
    CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON,
    CONCURRENT_MESSAGE_REPORT_HTML,
    ConcurrentMessageArtifactClosure,
    close_concurrent_message_artifacts,
)

if TYPE_CHECKING:
    from .concurrent_robustness_study import ConcurrentRobustnessManifest

_REPORT_PAYLOAD_SCHEMA = "concurrent-robustness-report-payload-v1"
_REPORT_MANIFEST_SCHEMA = "concurrent-robustness-report-candidate-manifest-v1"
_RELEASE_EVIDENCE_SCHEMA = "concurrent-robustness-report-release-evidence-v1"
_STUDY_MANIFEST_SCHEMA = "concurrent-robustness-study-artifact-manifest-v1"
_STUDY_VALIDATION_SCHEMA = "concurrent-robustness-complete-validation-v1"
_CLOSED_STUDY_ROOT_SUFFIX = ".study-root"
_WEIGHT_SCHEMA = "concurrent-ranking-weight-sensitivity-v1"
_PROMPT_MODEL_SCHEMA = "concurrent-prompt-model-robustness-analysis-v1"
_CLAIM_AUDIT_SCHEMA = "concurrent-robustness-claim-audit-v1"

_STUDY_FILES = {
    "artifact_manifest.json",
    "claim_audit.json",
    "prompt_model_analysis.json",
    "prompt_model_cell_evidence.json",
    "ranking_weight_sensitivity.json",
    "study_manifest.json",
    "validation_report.json",
}
_STUDY_HASHED_FILES = _STUDY_FILES - {"artifact_manifest.json"}

_REPORT_PAYLOAD = "concurrent_robustness_report_payload.json"
_WEIGHT_JSON = "ranking_weight_sensitivity.json"
_PROMPT_MODEL_JSON = "prompt_model_analysis.json"
_CLAIM_AUDIT_JSON = "robustness_claim_audit.json"
_STUDY_VALIDATION_JSON = "robustness_study_validation.json"
_WEIGHT_MESSAGE_CSV = "ranking_weight_message_summary.csv"
_WEIGHT_BATCH_CSV = "ranking_weight_batch_diagnostics.csv"
_SHARED_SEED_CSV = "prompt_model_shared_seed_summary.csv"
_PROMPT_MESSAGE_CSV = "prompt_model_message_summary.csv"
_PROMPT_TRAJECTORY_CSV = "prompt_model_trajectory_summary.csv"
_PROMPT_GROWTH_CSV = "prompt_model_campaign_growth.csv"
_THRESHOLD_CSV = "prompt_model_practical_thresholds.csv"
_RELEASE_EVIDENCE_JSON = "release_evidence.json"

_WEIGHT_MESSAGE_FIELDS = (
    "scenario_id",
    "message_id",
    "transfer_from",
    "transfer_to",
    "transfer_mass",
    "base_network_relevance_weight",
    "campaign_engaged_neighbor_signal_weight",
    "normalized_message_user_fit_weight",
    "mean_jaccard_distance",
    "auc_jaccard_distance",
    "first_divergent_batch",
)
_WEIGHT_BATCH_FIELDS = (
    "scenario_id",
    "message_id",
    "time_step",
    "jaccard_distance",
    "entered_user_count",
    "exited_user_count",
    "first_divergent_rank",
    "mean_absolute_rank_delta",
    "max_absolute_rank_delta",
)
_SHARED_SEED_FIELDS = (
    "cell_id",
    "prompt_variant",
    "requested_model",
    "message_id",
    "observation_count",
    "engage_rate",
    "mean_probability",
    "mean_confidence",
)
_PROMPT_MESSAGE_FIELDS = (
    "cell_id",
    "prompt_variant",
    "requested_model",
    "message_id",
    "actual_exposures",
    "successful_primary_decisions",
    "provider_failures",
    "positive_actions",
    "exposure_engagement_rate",
    "decision_engagement_rate",
    "mean_probability_successful_decisions",
    "first_divergent_batch_from_baseline_cell",
    "terminal_audience_overlap_count_with_baseline_cell",
    "terminal_audience_jaccard_similarity_with_baseline_cell",
    "terminal_audience_jaccard_distance_from_baseline_cell",
    "terminal_unique_positive_users",
)
_PROMPT_TRAJECTORY_FIELDS = (
    "cell_id",
    "prompt_variant",
    "requested_model",
    "message_id",
    "time_step",
    "batch_actual_exposures",
    "batch_successful_primary_decisions",
    "batch_provider_failures",
    "batch_positive_actions",
    "batch_exposure_engagement_rate",
    "batch_decision_engagement_rate",
    "cumulative_actual_exposures",
    "cumulative_successful_primary_decisions",
    "cumulative_provider_failures",
    "cumulative_positive_actions",
    "cumulative_exposure_engagement_rate",
    "cumulative_decision_engagement_rate",
    "batch_audience_jaccard_distance_from_baseline_cell",
    "cumulative_audience_jaccard_distance_from_baseline_cell",
)
_PROMPT_GROWTH_FIELDS = (
    "cell_id",
    "prompt_variant",
    "requested_model",
    "time_step",
    "cumulative_campaign_deduplicated_positive_user_count",
)
_THRESHOLD_FIELDS = (
    "comparison_id",
    "domain",
    "metric",
    "observed_difference",
    "absolute_difference",
    "threshold",
    "classification",
)

_COMPONENT_LABELS = {
    "base_network_relevance": "Network relevance",
    "campaign_engaged_neighbor_signal": "Campaign feedback",
    "normalized_message_user_fit": "Message–user fit",
}
_SERIES_STYLES = (
    {"color": "#155e75", "dash": "", "marker": "circle"},
    {"color": "#b45309", "dash": "12 6", "marker": "square"},
    {"color": "#4d7c0f", "dash": "3 5", "marker": "triangle"},
    {"color": "#7c3aed", "dash": "16 5 3 5", "marker": "diamond"},
    {"color": "#be123c", "dash": "8 4", "marker": "cross"},
    {"color": "#334155", "dash": "2 4", "marker": "plus"},
)
_PROMPT_STYLES = {
    "P0": _SERIES_STYLES[0],
    "P1": _SERIES_STYLES[1],
    "P2": _SERIES_STYLES[2],
    "P3": _SERIES_STYLES[3],
}


class _RobustnessReportPathError(ValueError):
    pass


class _RobustnessReportConflictError(ValueError):
    pass


class _RobustnessReportClosureError(ValueError):
    pass


@dataclass(frozen=True)
class _ClosedStudy:
    root: Path
    root_manifest: dict[str, Any]
    ranking: dict[str, Any]
    prompt_model: dict[str, Any]
    claims: dict[str, Any]
    validation: dict[str, Any]
    file_hashes: dict[str, str]


@dataclass(frozen=True)
class _ReportRows:
    weight_messages: list[dict[str, Any]]
    weight_batches: list[dict[str, Any]]
    shared_seed: list[dict[str, Any]]
    prompt_messages: list[dict[str, Any]]
    prompt_trajectories: list[dict[str, Any]]
    prompt_growth: list[dict[str, Any]]
    thresholds: list[dict[str, Any]]

    def counts(self) -> dict[str, int]:
        return {
            "ranking_weight_message_summary": len(self.weight_messages),
            "ranking_weight_batch_diagnostics": len(self.weight_batches),
            "prompt_model_shared_seed_summary": len(self.shared_seed),
            "prompt_model_message_summary": len(self.prompt_messages),
            "prompt_model_trajectory_summary": len(self.prompt_trajectories),
            "prompt_model_campaign_growth": len(self.prompt_growth),
            "prompt_model_practical_thresholds": len(self.thresholds),
        }


@dataclass(frozen=True)
class _ProductionPresentationFacts:
    """Release-approved facts that the Report Module may present but must not decide."""

    release_id: str
    release_contract_schema: str
    canonical_endpoint: str
    production_evidence_schema: str
    formal_logical_judgments: int
    formal_physical_attempts: int
    provider_transport: str
    subscription_billed_cost_usd: float
    approved_downloads: Mapping[str, str]


@dataclass(frozen=True)
class _PresentationBundle:
    report_payload: bytes
    report_html: bytes


@dataclass(frozen=True)
class _CandidateProjection:
    formal: ConcurrentMessageArtifactClosure
    study: _ClosedStudy
    manifest: ConcurrentRobustnessManifest
    manifest_sha256: str
    rows: _ReportRows
    report_payload: dict[str, Any]
    payloads: dict[str, bytes]


class _ReportPresentationInterface:
    """Package-internal seam for deterministic report composition and presentation stages."""

    def compose_candidate(
        self,
        *,
        formal_root: str | Path,
        study_root: str | Path,
        destination_dir: str | Path,
        reuse_existing: bool = False,
    ) -> Path:
        """Close two immutable lineages and create or reproduce one candidate atomically."""
        formal_path = Path(formal_root)
        study_path = Path(study_root)
        workspace_path = _workspace_root_for_study(study_path)
        manifest, manifest_payload, manifest_sha256 = _load_study_manifest(study_path)
        if reuse_existing and os.path.lexists(destination_dir):
            candidate, _ = self._validate_candidate_from_inputs(
                formal_root=formal_path,
                study_root=study_path,
                workspace_root=workspace_path,
                manifest=manifest,
                manifest_payload=manifest_payload,
                manifest_sha256=manifest_sha256,
                candidate_dir=destination_dir,
            )
            return candidate
        return self._compose_candidate_from_inputs(
            formal_root=formal_path,
            study_root=study_path,
            workspace_root=workspace_path,
            manifest=manifest,
            manifest_payload=manifest_payload,
            manifest_sha256=manifest_sha256,
            destination_dir=destination_dir,
        )

    def materialize_production(
        self,
        *,
        formal_root: str | Path,
        study_root: str | Path,
        candidate_dir: str | Path,
        stage_facts: _ProductionPresentationFacts,
    ) -> _PresentationBundle:
        """Render production presentation bytes from an immutable candidate and approved facts."""
        formal_path = Path(formal_root)
        study_path = Path(study_root)
        workspace_path = _workspace_root_for_study(study_path)
        manifest, manifest_payload, manifest_sha256 = _load_study_manifest(study_path)
        candidate, projection = self._validate_candidate_from_inputs(
            formal_root=formal_path,
            study_root=study_path,
            workspace_root=workspace_path,
            manifest=manifest,
            manifest_payload=manifest_payload,
            manifest_sha256=manifest_sha256,
            candidate_dir=candidate_dir,
        )
        candidate_before = {path.name: _sha256_file(path) for path in candidate.iterdir()}
        approved_downloads = _validate_production_facts(stage_facts)
        report_payload = _read_json(candidate / _REPORT_PAYLOAD)
        if report_payload.get("production_deploy_eligible") is not False:
            raise _RobustnessReportClosureError("candidate report payload is not validation-only")
        candidate_downloads = _string_mapping(report_payload.get("downloads"), "candidate downloads")
        if set(candidate_downloads) != set(approved_downloads):
            raise _RobustnessReportClosureError("production presentation changed the approved download keys")
        report_payload["downloads"] = approved_downloads
        report_payload["production_deploy_eligible"] = True
        report_payload["production_release"] = _production_release_payload(stage_facts)
        bundle = _PresentationBundle(
            report_payload=_json_bytes(report_payload),
            report_html=_render_additive_report(
                render_report(projection.formal.report_payload),
                payload=report_payload,
                stage_facts=stage_facts,
            ).encode("utf-8"),
        )
        self.validate_bundle(bundle, stage_facts=stage_facts)
        if candidate_before != {path.name: _sha256_file(path) for path in candidate.iterdir()}:
            raise _RobustnessReportClosureError("production presentation mutated the validation candidate")
        _assert_formal_unchanged(projection.formal, dict(projection.formal.artifact_hashes))
        _assert_study_unchanged(projection.study, dict(projection.study.file_hashes))
        return bundle

    def validate_bundle(
        self,
        bundle: _PresentationBundle,
        *,
        stage_facts: _ProductionPresentationFacts | None = None,
    ) -> None:
        """Validate payload, DOM stage, selectors, links, copy, and offline presentation safety."""
        try:
            _validate_presentation_bundle(bundle, stage_facts=stage_facts)
        except _RobustnessReportClosureError:
            raise
        except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _RobustnessReportClosureError("report presentation bundle failed validation") from exc

    def _compose_candidate_from_inputs(
        self,
        *,
        formal_root: Path,
        study_root: Path,
        workspace_root: Path,
        manifest: ConcurrentRobustnessManifest,
        manifest_payload: bytes,
        manifest_sha256: str,
        destination_dir: str | Path,
    ) -> Path:
        destination = _validate_destination(
            Path(destination_dir),
            protected_roots=(formal_root, study_root, workspace_root),
        )
        projection = _build_candidate_projection(
            formal_root=formal_root,
            study_root=study_root,
            manifest=manifest,
            manifest_payload=manifest_payload,
            manifest_sha256=manifest_sha256,
        )
        formal_before = dict(projection.formal.artifact_hashes)
        study_before = dict(projection.study.file_hashes)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.parent.is_symlink():
            raise _RobustnessReportPathError("robustness report destination parent must not be a symlink")
        staging = Path(
            tempfile.mkdtemp(
                prefix=f".{destination.name}.{manifest.output_identity}.",
                suffix=".staging",
                dir=destination.parent,
            )
        )
        try:
            if os.stat(staging).st_dev != os.stat(destination.parent).st_dev:
                raise _RobustnessReportPathError("robustness report staging must share the destination filesystem")
            for relative_path, payload in projection.payloads.items():
                target = staging / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
            _validate_candidate(
                staging,
                expected_payloads=projection.payloads,
                expected_row_counts=projection.rows.counts(),
            )
            _assert_formal_unchanged(projection.formal, formal_before)
            _assert_study_unchanged(projection.study, study_before)
            if os.path.lexists(destination):
                raise _RobustnessReportConflictError("robustness report destination appeared during publication")
            os.replace(staging, destination)
        except Exception:
            if os.path.lexists(staging):
                shutil.rmtree(staging, ignore_errors=True)
            raise
        _validate_candidate(
            destination,
            expected_payloads=projection.payloads,
            expected_row_counts=projection.rows.counts(),
        )
        _assert_formal_unchanged(projection.formal, formal_before)
        _assert_study_unchanged(projection.study, study_before)
        return destination

    def _validate_candidate_from_inputs(
        self,
        *,
        formal_root: Path,
        study_root: Path,
        workspace_root: Path,
        manifest: ConcurrentRobustnessManifest,
        manifest_payload: bytes,
        manifest_sha256: str,
        candidate_dir: str | Path,
    ) -> tuple[Path, _CandidateProjection]:
        candidate = Path(candidate_dir)
        try:
            if ".." in candidate.parts:
                raise ValueError("candidate contains an unsafe parent traversal")
            absolute = Path(os.path.abspath(candidate))
            resolved = candidate.resolve(strict=True)
            if absolute != resolved or candidate.is_symlink() or not resolved.is_dir():
                raise ValueError("candidate is not a real directory")
            protected = tuple(root.resolve(strict=True) for root in (formal_root, study_root, workspace_root))
            if any(
                resolved == root or resolved.is_relative_to(root) or root.is_relative_to(resolved)
                for root in protected
            ):
                raise ValueError("candidate overlaps a protected source root")
            projection = _build_candidate_projection(
                formal_root=formal_root,
                study_root=study_root,
                manifest=manifest,
                manifest_payload=manifest_payload,
                manifest_sha256=manifest_sha256,
            )
            formal_before = dict(projection.formal.artifact_hashes)
            study_before = dict(projection.study.file_hashes)
            _validate_candidate(
                resolved,
                expected_payloads=projection.payloads,
                expected_row_counts=projection.rows.counts(),
            )
            _assert_formal_unchanged(projection.formal, formal_before)
            _assert_study_unchanged(projection.study, study_before)
            return resolved, projection
        except (_RobustnessReportPathError, _RobustnessReportConflictError, _RobustnessReportClosureError):
            raise
        except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise _RobustnessReportClosureError("existing robustness report candidate failed closure") from exc


_REPORT_PRESENTATION = _ReportPresentationInterface()


def _workspace_root_for_study(study_root: Path) -> Path:
    if not study_root.name.endswith(_CLOSED_STUDY_ROOT_SUFFIX):
        raise _RobustnessReportPathError("immutable study root does not identify its protected workspace")
    workspace_name = study_root.name[: -len(_CLOSED_STUDY_ROOT_SUFFIX)]
    if not workspace_name:
        raise _RobustnessReportPathError("immutable study root has an invalid workspace identity")
    return study_root.with_name(workspace_name)


def _load_study_manifest(
    study_root: Path,
) -> tuple[ConcurrentRobustnessManifest, bytes, str]:
    try:
        from .concurrent_robustness_study import ConcurrentRobustnessManifest as ManifestModel

        manifest_path = study_root / "study_manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise ValueError("study manifest is not a regular file")
        payload = manifest_path.read_bytes()
        manifest = ManifestModel.model_validate_json(payload)
        return manifest, payload, _sha256_bytes(payload)
    except _RobustnessReportClosureError:
        raise
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise _RobustnessReportClosureError("immutable study lineage has an invalid manifest") from exc


def _validate_destination(destination: Path, *, protected_roots: Sequence[Path]) -> Path:
    if ".." in destination.parts:
        raise _RobustnessReportPathError("robustness report destination must not contain '..'")
    if os.path.lexists(destination):
        raise _RobustnessReportConflictError("robustness report destination already exists")
    absolute = Path(os.path.abspath(destination))
    try:
        resolved = destination.resolve(strict=False)
    except OSError as exc:
        raise _RobustnessReportPathError("robustness report destination cannot be resolved safely") from exc
    if absolute != resolved:
        raise _RobustnessReportPathError("robustness report destination must not contain symlink components")

    roots: list[Path] = []
    for root in protected_roots:
        try:
            root_absolute = Path(os.path.abspath(root))
            root_resolved = root.resolve(strict=True)
        except OSError as exc:
            raise _RobustnessReportPathError("robustness report source root cannot be resolved safely") from exc
        if root_absolute != root_resolved or root.is_symlink() or not root_resolved.is_dir():
            raise _RobustnessReportPathError("robustness report source roots must be real directories")
        roots.append(root_resolved)
        if (
            resolved == root_resolved
            or resolved.is_relative_to(root_resolved)
            or root_resolved.is_relative_to(resolved)
        ):
            raise _RobustnessReportPathError("robustness report destination must not overlap a source root")

    existing_parent = destination.parent
    while not os.path.lexists(existing_parent):
        parent = existing_parent.parent
        if parent == existing_parent:
            break
        existing_parent = parent
    if not existing_parent.is_dir() or existing_parent.is_symlink():
        raise _RobustnessReportPathError("robustness report destination parent must be a regular directory")
    if any(os.stat(root).st_dev != os.stat(existing_parent).st_dev for root in roots):
        raise _RobustnessReportPathError("robustness report sources and destination must share a filesystem")
    return resolved


def _build_candidate_projection(
    *,
    formal_root: Path,
    study_root: Path,
    manifest: ConcurrentRobustnessManifest,
    manifest_payload: bytes,
    manifest_sha256: str,
) -> _CandidateProjection:
    try:
        formal = close_concurrent_message_artifacts(formal_root)
    except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise _RobustnessReportClosureError("historical Concurrent Formal closure failed") from exc
    formal_manifest_hash = formal.artifact_hashes.get(CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON)
    if formal_manifest_hash is None or formal_manifest_hash != manifest.source.manifest_sha256:
        raise _RobustnessReportClosureError("historical Formal source is crossed with the robustness manifest")
    closed_study = _close_study_root(
        study_root,
        manifest=manifest,
        manifest_payload=manifest_payload,
        manifest_sha256=manifest_sha256,
        formal_manifest_sha256=formal_manifest_hash,
    )
    rows = _build_report_rows(closed_study, manifest)
    report_payload = _build_report_payload(
        formal=formal,
        study=closed_study,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        rows=rows,
    )
    payloads = _candidate_payloads(
        formal=formal,
        study=closed_study,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        rows=rows,
        report_payload=report_payload,
    )
    return _CandidateProjection(
        formal=formal,
        study=closed_study,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        rows=rows,
        report_payload=report_payload,
        payloads=payloads,
    )


def _close_study_root(
    root: Path,
    *,
    manifest: ConcurrentRobustnessManifest,
    manifest_payload: bytes,
    manifest_sha256: str,
    formal_manifest_sha256: str,
) -> _ClosedStudy:
    try:
        absolute = Path(os.path.abspath(root))
        resolved = root.resolve(strict=True)
        if absolute != resolved or root.is_symlink() or not resolved.is_dir():
            raise ValueError("study root is not a real directory")
        entries = list(resolved.iterdir())
        if any(path.is_symlink() or not path.is_file() for path in entries):
            raise ValueError("study root contains a non-regular artifact")
        if {path.name for path in entries} != _STUDY_FILES:
            raise ValueError("study root has missing or extra artifacts")
        if (resolved / "study_manifest.json").read_bytes() != manifest_payload:
            raise ValueError("study manifest bytes are crossed")

        file_hashes = {path.name: _sha256_file(path) for path in entries}
        root_manifest = _read_json(resolved / "artifact_manifest.json")
        if root_manifest.get("schema_version") != _STUDY_MANIFEST_SCHEMA:
            raise ValueError("study artifact manifest schema is unsupported")
        if root_manifest.get("root_type") != "immutable_closed_study" or root_manifest.get("status") != "complete":
            raise ValueError("study root is not an immutable complete root")
        artifacts = _string_sequence(root_manifest.get("artifacts"), "study artifact inventory")
        hashes = _string_mapping(root_manifest.get("sha256"), "study artifact hashes")
        if set(artifacts) != _STUDY_HASHED_FILES or set(hashes) != _STUDY_HASHED_FILES:
            raise ValueError("study artifact manifest inventory is incomplete")
        for relative_path, expected_hash in hashes.items():
            if not _is_sha256(expected_hash) or file_hashes[relative_path] != expected_hash:
                raise ValueError("study artifact hash mismatch")
        identity_payload = _json_bytes(dict(sorted(hashes.items())))
        if root_manifest.get("root_identity_sha256") != _sha256_bytes(identity_payload):
            raise ValueError("study root identity hash is crossed")
        if root_manifest.get("manifest_sha256") != manifest_sha256:
            raise ValueError("study manifest hash is crossed")
        if root_manifest.get("source_manifest_sha256") != formal_manifest_sha256:
            raise ValueError("study Formal source link is crossed")
        if root_manifest.get("production_deploy_eligible") is not False:
            raise ValueError("study root must remain non-deployable")
        if root_manifest.get("report_candidate") is not None:
            raise ValueError("study analysis closure cannot already expose a report candidate")

        ranking = _read_json(resolved / "ranking_weight_sensitivity.json")
        prompt_model = _read_json(resolved / "prompt_model_analysis.json")
        claims = _read_json(resolved / "claim_audit.json")
        validation = _read_json(resolved / "validation_report.json")
        _validate_study_documents(
            ranking=ranking,
            prompt_model=prompt_model,
            claims=claims,
            validation=validation,
            manifest=manifest,
            manifest_sha256=manifest_sha256,
            formal_manifest_sha256=formal_manifest_sha256,
        )
        return _ClosedStudy(
            root=resolved,
            root_manifest=root_manifest,
            ranking=ranking,
            prompt_model=prompt_model,
            claims=claims,
            validation=validation,
            file_hashes=file_hashes,
        )
    except _RobustnessReportClosureError:
        raise
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise _RobustnessReportClosureError(
            "immutable complete study root failed independent schema, row-count, and hash closure"
        ) from exc


def _validate_study_documents(
    *,
    ranking: Mapping[str, Any],
    prompt_model: Mapping[str, Any],
    claims: Mapping[str, Any],
    validation: Mapping[str, Any],
    manifest: ConcurrentRobustnessManifest,
    manifest_sha256: str,
    formal_manifest_sha256: str,
) -> None:
    if ranking.get("schema_version") != _WEIGHT_SCHEMA or ranking.get("manifest_sha256") != manifest_sha256:
        raise ValueError("ranking-weight evidence is crossed or unsupported")
    source = _mapping(ranking.get("source"), "ranking-weight source")
    if source.get("manifest_sha256") != formal_manifest_sha256:
        raise ValueError("ranking-weight source link is crossed")
    scenarios = _object_sequence(ranking.get("scenarios"), "ranking-weight scenarios")
    if len(scenarios) != 19:
        raise ValueError("ranking-weight evidence requires 19 scenarios")
    expected_scenarios = [point.scenario_id for point in manifest.weight_points]
    if [str(row.get("scenario_id")) for row in scenarios] != expected_scenarios:
        raise ValueError("ranking-weight scenario order is crossed")
    horizon = manifest.ranking_contract.horizon
    for scenario in scenarios:
        messages = _object_sequence(scenario.get("messages"), "ranking-weight messages")
        if [str(row.get("message_id")) for row in messages] != list(manifest.message_ids):
            raise ValueError("ranking-weight message order is crossed")
        for message in messages:
            batches = _object_sequence(message.get("batches"), "ranking-weight batches")
            if len(batches) != horizon or [int(row.get("time_step", -1)) for row in batches] != list(range(horizon)):
                raise ValueError("ranking-weight batch rows are incomplete")
    counts = _mapping(ranking.get("counts"), "ranking-weight counts")
    if counts != {
        "scenario_count": 19,
        "message_count": len(manifest.message_ids),
        "batch_count_per_message": horizon,
        "scenario_message_batch_count": 19 * len(manifest.message_ids) * horizon,
    }:
        raise ValueError("ranking-weight row counts do not close")

    if prompt_model.get("schema_version") != _PROMPT_MODEL_SCHEMA:
        raise ValueError("Prompt–Model analysis schema is unsupported")
    if prompt_model.get("manifest_sha256") != manifest_sha256 or int(prompt_model.get("cell_count", -1)) != 16:
        raise ValueError("Prompt–Model analysis identity is crossed")
    realized = _mapping(prompt_model.get("realized_paths"), "Prompt–Model realized paths")
    message_summaries = _object_sequence(realized.get("message_summaries"), "message summaries")
    trajectories = _object_sequence(realized.get("message_batch_trajectories"), "message trajectories")
    growth = _object_sequence(realized.get("campaign_deduplicated_positive_user_growth"), "campaign growth")
    if len(message_summaries) != 16 * len(manifest.message_ids):
        raise ValueError("Prompt–Model message summary count does not close")
    if len(trajectories) != 16 * len(manifest.message_ids) * horizon:
        raise ValueError("Prompt–Model trajectory row count does not close")
    if len(growth) != 16 * horizon:
        raise ValueError("Prompt–Model growth row count does not close")
    direct = _mapping(prompt_model.get("shared_seed_direct_decisions"), "shared-seed Decisions")
    exact_rows = _object_sequence(direct.get("exact_value_rows"), "shared-seed exact rows")
    if int(direct.get("exact_value_row_count", -1)) != len(exact_rows):
        raise ValueError("shared-seed exact row count does not close")
    if str(prompt_model.get("conditional_scope")) != "fixed_sample_fixed_graph_one_realized_path_per_cell":
        raise ValueError("Prompt–Model conditional scope is unsupported")

    if claims.get("schema_version") != _CLAIM_AUDIT_SCHEMA or claims.get("status") != "passed":
        raise ValueError("claim audit did not pass")
    if claims.get("ground_truth_used") is not False or claims.get("causal_claims_allowed") is not False:
        raise ValueError("claim audit boundary is crossed")
    if claims.get("statistical_equivalence_claims_allowed") is not False:
        raise ValueError("claim audit equivalence boundary is crossed")
    if validation.get("schema_version") != _STUDY_VALIDATION_SCHEMA or validation.get("status") != "complete":
        raise ValueError("study validation is not complete")
    if validation.get("manifest_sha256") != manifest_sha256:
        raise ValueError("study validation manifest hash is crossed")
    if validation.get("source_manifest_sha256") != formal_manifest_sha256:
        raise ValueError("study validation Formal source is crossed")
    if validation.get("production_deploy_eligible") is not False or validation.get("report_candidate") is not None:
        raise ValueError("study validation cannot authorize a report release")
    validation_counts = _mapping(validation.get("counts"), "study validation counts")
    if int(validation_counts.get("cell_count", -1)) != 16:
        raise ValueError("study validation cell count does not close")
    if int(validation_counts.get("message_count", -1)) != len(manifest.message_ids):
        raise ValueError("study validation message count does not close")
    if int(validation_counts.get("realized_logical_judgments", -1)) != manifest.request_caps.logical_judgment_cap:
        raise ValueError("study validation logical judgments do not close")


def _build_report_rows(study: _ClosedStudy, manifest: ConcurrentRobustnessManifest) -> _ReportRows:
    weight_messages: list[dict[str, Any]] = []
    weight_batches: list[dict[str, Any]] = []
    for scenario in _object_sequence(study.ranking["scenarios"], "ranking scenarios"):
        weights = _mapping(scenario.get("weights"), "ranking scenario weights")
        for message in _object_sequence(scenario.get("messages"), "ranking scenario messages"):
            weight_messages.append(
                {
                    "scenario_id": scenario["scenario_id"],
                    "message_id": message["message_id"],
                    "transfer_from": scenario.get("transfer_from"),
                    "transfer_to": scenario.get("transfer_to"),
                    "transfer_mass": scenario["transfer_mass"],
                    "base_network_relevance_weight": weights["base_network_relevance"],
                    "campaign_engaged_neighbor_signal_weight": weights["campaign_engaged_neighbor_signal"],
                    "normalized_message_user_fit_weight": weights["normalized_message_user_fit"],
                    "mean_jaccard_distance": message["curve_mean_jaccard_distance"],
                    "auc_jaccard_distance": message["curve_auc_jaccard_distance"],
                    "first_divergent_batch": message.get("first_divergent_batch"),
                }
            )
            for batch in _object_sequence(message.get("batches"), "ranking scenario batches"):
                rank_deltas = _object_sequence(batch.get("rank_deltas"), "rank deltas")
                absolute_deltas = [abs(int(row["rank_delta"])) for row in rank_deltas]
                weight_batches.append(
                    {
                        "scenario_id": scenario["scenario_id"],
                        "message_id": message["message_id"],
                        "time_step": batch["time_step"],
                        "jaccard_distance": batch["jaccard_distance"],
                        "entered_user_count": len(_sequence(batch.get("entered_user_ids"), "entered users")),
                        "exited_user_count": len(_sequence(batch.get("exited_user_ids"), "exited users")),
                        "first_divergent_rank": batch.get("first_divergent_rank"),
                        "mean_absolute_rank_delta": _round(sum(absolute_deltas) / len(absolute_deltas)) if absolute_deltas else 0.0,
                        "max_absolute_rank_delta": max(absolute_deltas, default=0),
                    }
                )

    cell_identity = {
        cell.cell_id: {"prompt_variant": cell.prompt_variant, "requested_model": cell.requested_model}
        for cell in manifest.prompt_model_cells
    }
    direct = _mapping(study.prompt_model["shared_seed_direct_decisions"], "shared-seed direct analysis")
    grouped_direct: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in _object_sequence(direct.get("exact_value_rows"), "shared-seed exact rows"):
        grouped_direct[(str(row["cell_id"]), str(row["message_id"]))].append(row)
    shared_seed: list[dict[str, Any]] = []
    for cell in manifest.prompt_model_cells:
        for message_id in manifest.message_ids:
            rows = grouped_direct[(cell.cell_id, message_id)]
            if not rows:
                raise _RobustnessReportClosureError("shared-seed report rows are incomplete")
            shared_seed.append(
                {
                    "cell_id": cell.cell_id,
                    "prompt_variant": cell.prompt_variant,
                    "requested_model": cell.requested_model,
                    "message_id": message_id,
                    "observation_count": len(rows),
                    "engage_rate": _round(sum(int(bool(row["engage"])) for row in rows) / len(rows)),
                    "mean_probability": _round(sum(float(row["probability"]) for row in rows) / len(rows)),
                    "mean_confidence": _round(sum(float(row["confidence"]) for row in rows) / len(rows)),
                }
            )

    realized = _mapping(study.prompt_model["realized_paths"], "Prompt–Model realized paths")
    prompt_messages = [
        {**cell_identity[str(row["cell_id"])], **dict(row)}
        for row in _object_sequence(realized.get("message_summaries"), "message summaries")
    ]
    prompt_trajectories = [
        {
            **cell_identity[str(row["cell_id"])],
            **{field: row.get(field) for field in _PROMPT_TRAJECTORY_FIELDS if field not in {"prompt_variant", "requested_model"}},
        }
        for row in _object_sequence(realized.get("message_batch_trajectories"), "message trajectories")
    ]
    prompt_growth = [
        {
            **cell_identity[str(row["cell_id"])],
            "cell_id": row["cell_id"],
            "time_step": row["time_step"],
            "cumulative_campaign_deduplicated_positive_user_count": row[
                "cumulative_campaign_deduplicated_positive_user_count"
            ],
        }
        for row in _object_sequence(
            realized.get("campaign_deduplicated_positive_user_growth"),
            "campaign growth",
        )
    ]
    thresholds = [
        {field: row.get(field) for field in _THRESHOLD_FIELDS}
        for row in _object_sequence(
            study.prompt_model.get("practical_threshold_classifications"),
            "practical threshold rows",
        )
    ]
    report_rows = _ReportRows(
        weight_messages=weight_messages,
        weight_batches=weight_batches,
        shared_seed=shared_seed,
        prompt_messages=prompt_messages,
        prompt_trajectories=prompt_trajectories,
        prompt_growth=prompt_growth,
        thresholds=thresholds,
    )
    expected_counts = {
        "ranking_weight_message_summary": 19 * len(manifest.message_ids),
        "ranking_weight_batch_diagnostics": 19 * len(manifest.message_ids) * manifest.ranking_contract.horizon,
        "prompt_model_shared_seed_summary": 16 * len(manifest.message_ids),
        "prompt_model_message_summary": 16 * len(manifest.message_ids),
        "prompt_model_trajectory_summary": 16 * len(manifest.message_ids) * manifest.ranking_contract.horizon,
        "prompt_model_campaign_growth": 16 * manifest.ranking_contract.horizon,
        "prompt_model_practical_thresholds": len(thresholds),
    }
    if report_rows.counts() != expected_counts:
        raise _RobustnessReportClosureError("report companion table row counts do not close")
    return report_rows


def _build_report_payload(
    *,
    formal: ConcurrentMessageArtifactClosure,
    study: _ClosedStudy,
    manifest: ConcurrentRobustnessManifest,
    manifest_sha256: str,
    rows: _ReportRows,
) -> dict[str, Any]:
    downloads = {
        "candidate_manifest": CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON,
        "report_payload": _REPORT_PAYLOAD,
        "ranking_weight_source": _WEIGHT_JSON,
        "prompt_model_source": _PROMPT_MODEL_JSON,
        "claim_audit": _CLAIM_AUDIT_JSON,
        "study_validation": _STUDY_VALIDATION_JSON,
        "ranking_weight_message_summary": _WEIGHT_MESSAGE_CSV,
        "ranking_weight_batch_diagnostics": _WEIGHT_BATCH_CSV,
        "prompt_model_shared_seed_summary": _SHARED_SEED_CSV,
        "prompt_model_message_summary": _PROMPT_MESSAGE_CSV,
        "prompt_model_trajectory_summary": _PROMPT_TRAJECTORY_CSV,
        "prompt_model_campaign_growth": _PROMPT_GROWTH_CSV,
        "prompt_model_practical_thresholds": _THRESHOLD_CSV,
        "release_evidence": _RELEASE_EVIDENCE_JSON,
    }
    return {
        "schema_version": _REPORT_PAYLOAD_SCHEMA,
        "title": "Concurrent Message · Incremental Robustness Evidence",
        "source_lineage": {
            "formal": {
                "source_id": manifest.source.source_id,
                "manifest_schema": manifest.source.manifest_schema,
                "manifest_sha256": manifest.source.manifest_sha256,
                "report_payload_schema": formal.report_payload.schema_version,
                "evidence_scope": [
                    "mechanism",
                    "run_evidence",
                    "field_lineage",
                    "demographic_shadow",
                    "primary_shadow_barrier",
                ],
            },
            "study": {
                "output_identity": manifest.output_identity,
                "manifest_sha256": manifest_sha256,
                "root_manifest_schema": study.root_manifest["schema_version"],
                "root_identity_sha256": study.root_manifest["root_identity_sha256"],
                "evidence_scope": ["ranking_weight_sensitivity", "prompt_model_primary_only"],
                "demographic_shadow_rerun": False,
            },
        },
        "ranking_weight": {
            "schema_version": study.ranking["schema_version"],
            "message_summary_rows": rows.weight_messages,
            "batch_diagnostic_rows": rows.weight_batches,
        },
        "prompt_model": {
            "schema_version": study.prompt_model["schema_version"],
            "shared_seed_rows": rows.shared_seed,
            "message_summary_rows": rows.prompt_messages,
            "trajectory_rows": rows.prompt_trajectories,
            "campaign_growth_rows": rows.prompt_growth,
            "practical_threshold_rows": rows.thresholds,
        },
        "row_counts": rows.counts(),
        "downloads": downloads,
        "claim_boundary": {
            "scope": "fixed_sample_fixed_graph_one_realized_path_per_cell",
            "ground_truth_used": False,
            "causal_claim": False,
            "calibration_claim": False,
            "statistical_equivalence_claim": False,
            "below_threshold_label": "small_observed_difference",
        },
        "production_deploy_eligible": False,
    }


def _candidate_payloads(
    *,
    formal: ConcurrentMessageArtifactClosure,
    study: _ClosedStudy,
    manifest: ConcurrentRobustnessManifest,
    manifest_sha256: str,
    rows: _ReportRows,
    report_payload: Mapping[str, Any],
) -> dict[str, bytes]:
    payloads: dict[str, bytes] = {}
    for name, relative_path in formal.manifest.artifacts.items():
        if name == "report_html":
            continue
        payloads[relative_path] = formal.artifact_paths[name].read_bytes()
    payloads[_REPORT_PAYLOAD] = _json_bytes(report_payload)
    payloads[_WEIGHT_JSON] = (study.root / "ranking_weight_sensitivity.json").read_bytes()
    payloads[_PROMPT_MODEL_JSON] = (study.root / "prompt_model_analysis.json").read_bytes()
    payloads[_CLAIM_AUDIT_JSON] = (study.root / "claim_audit.json").read_bytes()
    payloads[_STUDY_VALIDATION_JSON] = (study.root / "validation_report.json").read_bytes()
    payloads[_WEIGHT_MESSAGE_CSV] = _csv_bytes(_WEIGHT_MESSAGE_FIELDS, rows.weight_messages)
    payloads[_WEIGHT_BATCH_CSV] = _csv_bytes(_WEIGHT_BATCH_FIELDS, rows.weight_batches)
    payloads[_SHARED_SEED_CSV] = _csv_bytes(_SHARED_SEED_FIELDS, rows.shared_seed)
    payloads[_PROMPT_MESSAGE_CSV] = _csv_bytes(_PROMPT_MESSAGE_FIELDS, rows.prompt_messages)
    payloads[_PROMPT_TRAJECTORY_CSV] = _csv_bytes(_PROMPT_TRAJECTORY_FIELDS, rows.prompt_trajectories)
    payloads[_PROMPT_GROWTH_CSV] = _csv_bytes(_PROMPT_GROWTH_FIELDS, rows.prompt_growth)
    payloads[_THRESHOLD_CSV] = _csv_bytes(_THRESHOLD_FIELDS, rows.thresholds)

    formal_html = render_report(formal.report_payload)
    payloads[CONCURRENT_MESSAGE_REPORT_HTML] = _render_additive_report(
        formal_html,
        payload=report_payload,
    ).encode("utf-8")
    content_hashes = {path: _sha256_bytes(payload) for path, payload in payloads.items()}
    content_identity = _sha256_bytes(_json_bytes(dict(sorted(content_hashes.items()))))
    release_evidence = {
        "schema_version": _RELEASE_EVIDENCE_SCHEMA,
        "candidate_type": "complete_fixture_report_candidate",
        "candidate_content_identity_sha256": content_identity,
        "formal_source_manifest_sha256": manifest.source.manifest_sha256,
        "study_manifest_sha256": manifest_sha256,
        "study_root_identity_sha256": study.root_manifest["root_identity_sha256"],
        "provider_calls_during_composition": 0,
        "image_generation_triggered": False,
        "canonical_deployment_triggered": False,
        "production_deploy_eligible": False,
    }
    payloads[_RELEASE_EVIDENCE_JSON] = _json_bytes(release_evidence)
    artifact_hashes = {path: _sha256_bytes(payload) for path, payload in payloads.items()}
    artifact_mapping = _artifact_mapping(formal, payloads)
    manifest_document = {
        "schema_version": _REPORT_MANIFEST_SCHEMA,
        "candidate_type": "immutable_combined_robustness_report",
        "formal_source": {
            "source_id": manifest.source.source_id,
            "manifest_schema": manifest.source.manifest_schema,
            "manifest_sha256": manifest.source.manifest_sha256,
            "copied_artifact_count": len(formal.manifest.artifacts) - 1,
        },
        "study_source": {
            "output_identity": manifest.output_identity,
            "manifest_sha256": manifest_sha256,
            "artifact_manifest_sha256": study.file_hashes["artifact_manifest.json"],
            "root_identity_sha256": study.root_manifest["root_identity_sha256"],
        },
        "report_schema": _REPORT_PAYLOAD_SCHEMA,
        "artifacts": artifact_mapping,
        "sha256": {name: artifact_hashes[path] for name, path in artifact_mapping.items()},
        "candidate_identity_sha256": _sha256_bytes(
            _json_bytes(dict(sorted((path, artifact_hashes[path]) for path in artifact_mapping.values())))
        ),
        "row_counts": rows.counts(),
        "approved_downloads": list(_mapping(report_payload["downloads"], "report downloads").values()),
        "production_deploy_eligible": False,
    }
    payloads[CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON] = _json_bytes(manifest_document)
    return payloads


def _artifact_mapping(
    formal: ConcurrentMessageArtifactClosure,
    payloads: Mapping[str, bytes],
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    formal_paths = {
        relative_path: name
        for name, relative_path in formal.manifest.artifacts.items()
        if name != "report_html"
    }
    for relative_path in sorted(payloads):
        if relative_path == CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON:
            continue
        if relative_path in formal_paths:
            logical_name = f"formal_{formal_paths[relative_path]}"
        else:
            logical_name = Path(relative_path).stem.replace("-", "_")
        if logical_name in mapping:
            raise _RobustnessReportClosureError("candidate artifact logical names are not unique")
        mapping[logical_name] = relative_path
    return dict(sorted(mapping.items()))


def _validate_production_facts(facts: _ProductionPresentationFacts) -> dict[str, str]:
    strings = (
        facts.release_id,
        facts.release_contract_schema,
        facts.canonical_endpoint,
        facts.production_evidence_schema,
        facts.provider_transport,
    )
    if any(not isinstance(value, str) or not value for value in strings):
        raise _RobustnessReportClosureError("production presentation facts contain an empty string")
    if (
        type(facts.formal_logical_judgments) is not int
        or facts.formal_logical_judgments < 0
        or type(facts.formal_physical_attempts) is not int
        or facts.formal_physical_attempts < 0
    ):
        raise _RobustnessReportClosureError("production presentation judgment counts are invalid")
    billed_cost = facts.subscription_billed_cost_usd
    if isinstance(billed_cost, bool) or not isinstance(billed_cost, (int, float)) or not math.isfinite(billed_cost):
        raise _RobustnessReportClosureError("production presentation billed cost is invalid")
    downloads = _string_mapping(facts.approved_downloads, "production approved downloads")
    for key, relative_path in downloads.items():
        path = PurePosixPath(relative_path)
        if (
            _safe_id(key) != key
            or "\\" in relative_path
            or path.is_absolute()
            or path.as_posix() != relative_path
            or ".." in path.parts
        ):
            raise _RobustnessReportClosureError("production presentation download mapping is unsafe")
    return downloads


def _production_release_payload(facts: _ProductionPresentationFacts) -> dict[str, Any]:
    return {
        "schema_version": facts.production_evidence_schema,
        "release_id": facts.release_id,
        "canonical_endpoint": facts.canonical_endpoint,
        "formal_logical_judgments": facts.formal_logical_judgments,
        "formal_physical_attempts": facts.formal_physical_attempts,
        "provider_transport": facts.provider_transport,
        "subscription_billed_cost_usd": facts.subscription_billed_cost_usd,
    }


def _validate_presentation_bundle(
    bundle: _PresentationBundle,
    *,
    stage_facts: _ProductionPresentationFacts | None,
) -> None:
    payload_value = json.loads(bundle.report_payload)
    payload = _mapping(payload_value, "report presentation payload")
    html_document = bundle.report_html.decode("utf-8")
    if payload.get("schema_version") != _REPORT_PAYLOAD_SCHEMA:
        raise ValueError("report presentation payload schema is unsupported")
    downloads = _string_mapping(payload.get("downloads"), "report presentation downloads")

    if stage_facts is None:
        stage_test_id = "robustness-report-candidate"
        other_test_id = "robustness-report-release"
        eligibility = False
        release_attribute = ' aria-labelledby="robustness-title"'
        expected_copy = "values in this candidate"
        if "production_release" in payload:
            raise ValueError("candidate presentation contains production release metadata")
    else:
        approved_downloads = _validate_production_facts(stage_facts)
        if downloads != approved_downloads:
            raise ValueError("production payload downloads differ from approved presentation facts")
        if _mapping(payload.get("production_release"), "production release metadata") != (
            _production_release_payload(stage_facts)
        ):
            raise ValueError("production release metadata is crossed")
        stage_test_id = "robustness-report-release"
        other_test_id = "robustness-report-candidate"
        eligibility = True
        release_attribute = f' data-release-id="{_escape(stage_facts.release_id, quote=True)}"'
        expected_copy = "values in this production release"

    if payload.get("production_deploy_eligible") is not eligibility:
        raise ValueError("report payload eligibility is crossed with its presentation stage")
    root_signature = f'data-testid="{stage_test_id}"{release_attribute}'
    selector = f"document.querySelector('[data-testid=\"{stage_test_id}\"]')"
    stage_marker = f'data-testid="{stage_test_id}"'
    other_marker = f'data-testid="{other_test_id}"'
    eligibility_text = str(eligibility).lower()
    eligibility_marker = (
        'data-testid="robustness-production-eligibility">'
        f"production_deploy_eligible={eligibility_text}"
    )
    if (
        html_document.count(root_signature) != 1
        or html_document.count(stage_marker) != 2
        or html_document.count(selector) != 1
        or other_marker in html_document
        or html_document.count(eligibility_marker) != 1
        or f"production_deploy_eligible={str(not eligibility).lower()}" in html_document
        or expected_copy not in html_document
    ):
        raise ValueError("report DOM stage, selector, eligibility, or copy is crossed")

    if stage_facts is None:
        if (
            "data-release-id=" in html_document
            or 'name="abm-release-id"' in html_document
            or 'name="abm-release-contract"' in html_document
        ):
            raise ValueError("candidate presentation contains production stage metadata")
    else:
        release_id = _escape(stage_facts.release_id, quote=True)
        release_schema = _escape(stage_facts.release_contract_schema, quote=True)
        release_meta = f'<meta name="abm-release-id" content="{release_id}">'
        contract_meta = f'<meta name="abm-release-contract" content="{release_schema}">'
        if (
            html_document.count(release_meta) != 1
            or html_document.count(contract_meta) != 1
            or len(re.findall(r'\bdata-release-id="[^"]*"', html_document)) != 1
            or len(re.findall(r'<meta\s+name="abm-release-id"\s+content="[^"]*">', html_document)) != 1
        ):
            raise ValueError("production presentation release metadata is crossed")

    required = (
        'data-testid="mechanism-overview-section"',
        'data-testid="run-evidence-mode-panel"',
        'data-testid="run-trace-lineage-data"',
        'data-testid="robustness-source-lineage"',
        'data-testid="ranking-weight-sensitivity-section"',
        'data-testid="prompt-model-robustness-section"',
        "Demographic Shadow evidence remains bound to the historical Formal source",
    )
    if any(marker not in html_document for marker in required):
        raise ValueError("report presentation is missing required historical or robustness evidence")
    if re.search(
        r"<(?:script|link|img)\b[^>]*(?:src|href)=[\"']https?://",
        html_document,
        re.IGNORECASE,
    ):
        raise ValueError("report presentation requests an external resource")
    if _presentation_downloads_from_html(html_document) != downloads:
        raise ValueError("report presentation hrefs differ from its payload downloads")


def _presentation_downloads_from_html(html_document: str) -> dict[str, str]:
    section_starts = list(
        re.finditer(
            r'<section\b(?=[^>]*\bdata-testid="robustness-downloads-section")[^>]*>',
            html_document,
            re.IGNORECASE,
        )
    )
    if len(section_starts) != 1:
        raise ValueError("report download section is missing or ambiguous")
    section_end = html_document.find("</section>", section_starts[0].end())
    if section_end < 0:
        raise ValueError("report download section is not closed")
    section = html_document[section_starts[0].end():section_end]
    downloads: dict[str, str] = {}
    for anchor in re.findall(r"<a\b[^>]*>", section, re.IGNORECASE):
        pairs = re.findall(r'([A-Za-z_:][A-Za-z0-9_.:-]*)="([^"]*)"', anchor)
        attributes = {key: html.unescape(value) for key, value in pairs}
        if len(attributes) != len(pairs):
            raise ValueError("report download link attributes are ambiguous")
        test_id = attributes.get("data-testid", "")
        prefix = "robustness-download-"
        key = test_id.removeprefix(prefix)
        href = attributes.get("href")
        if (
            not test_id.startswith(prefix)
            or not re.fullmatch(r"[A-Za-z0-9_-]+", key)
            or href is None
            or key in downloads
        ):
            raise ValueError("report download link mapping is invalid")
        downloads[key] = href
    return downloads


def _validate_candidate(
    candidate: Path,
    *,
    expected_payloads: Mapping[str, bytes],
    expected_row_counts: Mapping[str, int],
) -> None:
    try:
        if candidate.is_symlink() or not candidate.is_dir():
            raise ValueError("candidate is not a real directory")
        entries = list(candidate.iterdir())
        if any(path.is_symlink() or not path.is_file() for path in entries):
            raise ValueError("candidate contains a non-regular artifact")
        if {path.name for path in entries} != set(expected_payloads):
            raise ValueError("candidate has missing or extra artifacts")
        for relative_path, expected in expected_payloads.items():
            if (candidate / relative_path).read_bytes() != expected:
                raise ValueError(f"candidate artifact is not reproducible: {relative_path}")
        manifest = _read_json(candidate / CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON)
        if manifest.get("schema_version") != _REPORT_MANIFEST_SCHEMA:
            raise ValueError("candidate manifest schema is unsupported")
        if manifest.get("candidate_type") != "immutable_combined_robustness_report":
            raise ValueError("candidate type is unsupported")
        if manifest.get("production_deploy_eligible") is not False:
            raise ValueError("candidate cannot be production deploy eligible")
        artifacts = _string_mapping(manifest.get("artifacts"), "candidate artifacts")
        hashes = _string_mapping(manifest.get("sha256"), "candidate hashes")
        if set(artifacts) != set(hashes) or len(set(artifacts.values())) != len(artifacts):
            raise ValueError("candidate artifact and hash inventories are crossed")
        if set(artifacts.values()) != set(expected_payloads) - {CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON}:
            raise ValueError("candidate artifact inventory is incomplete")
        for name, relative_path in artifacts.items():
            if hashes[name] != _sha256_file(candidate / relative_path):
                raise ValueError("candidate artifact hash mismatch")
        identity_rows = dict(sorted((path, hashes[name]) for name, path in artifacts.items()))
        if manifest.get("candidate_identity_sha256") != _sha256_bytes(_json_bytes(identity_rows)):
            raise ValueError("candidate identity hash is crossed")
        if _mapping(manifest.get("row_counts"), "candidate row counts") != dict(expected_row_counts):
            raise ValueError("candidate row counts do not close")
        payload = _read_json(candidate / _REPORT_PAYLOAD)
        if payload.get("schema_version") != _REPORT_PAYLOAD_SCHEMA:
            raise ValueError("candidate report payload schema is unsupported")
        if _mapping(payload.get("row_counts"), "report payload row counts") != dict(expected_row_counts):
            raise ValueError("report payload row counts do not close")
        payload_downloads = _string_mapping(payload.get("downloads"), "report payload downloads")
        approved_downloads = _string_sequence(manifest.get("approved_downloads"), "approved downloads")
        if set(approved_downloads) != set(payload_downloads.values()):
            raise ValueError("candidate approved downloads are crossed with the report payload")
        if any(
            Path(relative_path).is_absolute()
            or ".." in Path(relative_path).parts
            or not (candidate / relative_path).is_file()
            for relative_path in approved_downloads
        ):
            raise ValueError("candidate approved downloads escape or are missing")
        payload_lineage = _mapping(payload.get("source_lineage"), "report payload source lineage")
        payload_formal = _mapping(payload_lineage.get("formal"), "report payload Formal lineage")
        payload_study = _mapping(payload_lineage.get("study"), "report payload study lineage")
        manifest_formal = _mapping(manifest.get("formal_source"), "candidate Formal lineage")
        manifest_study = _mapping(manifest.get("study_source"), "candidate study lineage")
        if payload_formal.get("manifest_sha256") != manifest_formal.get("manifest_sha256"):
            raise ValueError("candidate Formal lineage is crossed")
        if payload_study.get("manifest_sha256") != manifest_study.get("manifest_sha256"):
            raise ValueError("candidate study lineage is crossed")
        if payload_study.get("root_identity_sha256") != manifest_study.get("root_identity_sha256"):
            raise ValueError("candidate study root identity is crossed")
        release = _read_json(candidate / _RELEASE_EVIDENCE_JSON)
        if release.get("schema_version") != _RELEASE_EVIDENCE_SCHEMA:
            raise ValueError("release evidence schema is unsupported")
        if release.get("production_deploy_eligible") is not False:
            raise ValueError("release evidence cannot authorize production deployment")
        if release.get("provider_calls_during_composition") != 0:
            raise ValueError("report composition cannot call a Provider")
        if release.get("image_generation_triggered") is not False:
            raise ValueError("report composition cannot generate images")
        content_hashes = {
            path: _sha256_file(candidate / path)
            for path in expected_payloads
            if path not in {CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON, _RELEASE_EVIDENCE_JSON}
        }
        if release.get("candidate_content_identity_sha256") != _sha256_bytes(
            _json_bytes(dict(sorted(content_hashes.items())))
        ):
            raise ValueError("release evidence content identity is crossed")
        if release.get("formal_source_manifest_sha256") != manifest_formal.get("manifest_sha256"):
            raise ValueError("release evidence Formal source is crossed")
        if release.get("study_manifest_sha256") != manifest_study.get("manifest_sha256"):
            raise ValueError("release evidence study source is crossed")
        _validate_presentation_bundle(
            _PresentationBundle(
                report_payload=(candidate / _REPORT_PAYLOAD).read_bytes(),
                report_html=(candidate / CONCURRENT_MESSAGE_REPORT_HTML).read_bytes(),
            ),
            stage_facts=None,
        )
        _validate_csv(candidate / _WEIGHT_MESSAGE_CSV, _WEIGHT_MESSAGE_FIELDS, expected_row_counts["ranking_weight_message_summary"])
        _validate_csv(candidate / _WEIGHT_BATCH_CSV, _WEIGHT_BATCH_FIELDS, expected_row_counts["ranking_weight_batch_diagnostics"])
        _validate_csv(candidate / _SHARED_SEED_CSV, _SHARED_SEED_FIELDS, expected_row_counts["prompt_model_shared_seed_summary"])
        _validate_csv(candidate / _PROMPT_MESSAGE_CSV, _PROMPT_MESSAGE_FIELDS, expected_row_counts["prompt_model_message_summary"])
        _validate_csv(candidate / _PROMPT_TRAJECTORY_CSV, _PROMPT_TRAJECTORY_FIELDS, expected_row_counts["prompt_model_trajectory_summary"])
        _validate_csv(candidate / _PROMPT_GROWTH_CSV, _PROMPT_GROWTH_FIELDS, expected_row_counts["prompt_model_campaign_growth"])
        _validate_csv(candidate / _THRESHOLD_CSV, _THRESHOLD_FIELDS, expected_row_counts["prompt_model_practical_thresholds"])
    except _RobustnessReportClosureError:
        raise
    except (OSError, TypeError, ValueError, json.JSONDecodeError, csv.Error) as exc:
        raise _RobustnessReportClosureError("staged robustness report candidate failed closure validation") from exc


def _validate_csv(path: Path, fields: Sequence[str], expected_rows: int) -> None:
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != tuple(fields):
            raise ValueError(f"{path.name} schema is crossed")
        rows = list(reader)
    if len(rows) != expected_rows:
        raise ValueError(f"{path.name} row count does not close")


def _render_additive_report(
    formal_html: str,
    *,
    payload: Mapping[str, Any],
    stage_facts: _ProductionPresentationFacts | None = None,
) -> str:
    if formal_html.count("</head>") != 1 or formal_html.count("</body>") != 1:
        raise _RobustnessReportClosureError("historical report renderer did not return one closed HTML document")
    insertion_marker = '<aside id="trace-drawer"'
    if formal_html.count(insertion_marker) != 1:
        raise _RobustnessReportClosureError("historical Editorial shell does not expose the private composition marker")
    section_html = _robustness_sections(payload, stage_facts=stage_facts)
    head_addition = f"<style>{_ROBUSTNESS_CSS}</style>\n"
    if stage_facts is not None:
        head_addition += (
            f'<meta name="abm-release-contract" content="{_escape(stage_facts.release_contract_schema, quote=True)}">'
            f'<meta name="abm-release-id" content="{_escape(stage_facts.release_id, quote=True)}">'
        )
    stage_test_id = (
        "robustness-report-release" if stage_facts is not None else "robustness-report-candidate"
    )
    script = _ROBUSTNESS_SCRIPT.replace("__REPORT_STAGE_TEST_ID__", stage_test_id)
    rendered = formal_html.replace("</head>", f"{head_addition}</head>", 1)
    rendered = rendered.replace(insertion_marker, f"{section_html}\n        {insertion_marker}", 1)
    rendered = rendered.replace("</body>", f"<script>{script}</script>\n</body>", 1)
    return rendered


def _robustness_sections(
    payload: Mapping[str, Any],
    *,
    stage_facts: _ProductionPresentationFacts | None = None,
) -> str:
    if stage_facts is None:
        stage_test_id = "robustness-report-candidate"
        stage_attribute = ""
        eligibility = "false"
        download_scope = "candidate"
    else:
        stage_test_id = "robustness-report-release"
        stage_attribute = f' data-release-id="{_escape(stage_facts.release_id, quote=True)}"'
        eligibility = "true"
        download_scope = "production release"
    lineage = _mapping(payload["source_lineage"], "source lineage")
    formal = _mapping(lineage["formal"], "Formal source")
    study = _mapping(lineage["study"], "study source")
    ranking = _mapping(payload["ranking_weight"], "ranking report")
    prompt_model = _mapping(payload["prompt_model"], "Prompt–Model report")
    downloads = _string_mapping(payload["downloads"], "report downloads")
    weight_messages = _object_sequence(ranking["message_summary_rows"], "weight message rows")
    weight_batches = _object_sequence(ranking["batch_diagnostic_rows"], "weight batch rows")
    shared_seed = _object_sequence(prompt_model["shared_seed_rows"], "shared-seed rows")
    prompt_messages = _object_sequence(prompt_model["message_summary_rows"], "Prompt message rows")
    trajectories = _object_sequence(prompt_model["trajectory_rows"], "Prompt trajectory rows")
    growth = _object_sequence(prompt_model["campaign_growth_rows"], "Prompt growth rows")
    thresholds = _object_sequence(prompt_model["practical_threshold_rows"], "threshold rows")
    message_ids = list(dict.fromkeys(str(row["message_id"]) for row in weight_messages))
    models = list(dict.fromkeys(str(row["requested_model"]) for row in prompt_messages))

    family_pairs = [
        ("network-feedback", "base_network_relevance", "campaign_engaged_neighbor_signal"),
        ("network-fit", "base_network_relevance", "normalized_message_user_fit"),
        ("feedback-fit", "campaign_engaged_neighbor_signal", "normalized_message_user_fit"),
    ]
    family_options = "".join(
        f'<option value="{_escape(family_id, quote=True)}">{_escape(_COMPONENT_LABELS[left])} ↔ {_escape(_COMPONENT_LABELS[right])}</option>'
        for family_id, left, right in family_pairs
    )
    weight_cards: list[str] = []
    for message_id in message_ids:
        family_views: list[str] = []
        for family_index, (family_id, left, right) in enumerate(family_pairs):
            family_scenarios = [
                row
                for row in weight_messages
                if row["message_id"] == message_id
                and {row.get("transfer_from"), row.get("transfer_to")} == {left, right}
            ]
            series: list[dict[str, Any]] = []
            for scenario_index, summary in enumerate(family_scenarios):
                scenario_id = str(summary["scenario_id"])
                batches = sorted(
                    (
                        row
                        for row in weight_batches
                        if row["scenario_id"] == scenario_id and row["message_id"] == message_id
                    ),
                    key=lambda row: int(row["time_step"]),
                )
                direction = f"{_COMPONENT_LABELS[str(summary['transfer_from'])]} → {_COMPONENT_LABELS[str(summary['transfer_to'])]}"
                series.append(
                    {
                        "series_id": scenario_id,
                        "label": f"{direction} · {_display(summary['transfer_mass'])}",
                        "values": [float(row["jaccard_distance"]) for row in batches],
                        "style": _SERIES_STYLES[scenario_index],
                    }
                )
            chart_id = f"weight-{message_id}-{family_id}"
            family_views.append(
                f'<div class="robustness-weight-family" data-weight-family="{family_id}"{"" if family_index == 0 else " hidden"}>'
                f'{_line_chart(chart_id=chart_id, title=f"{message_id} · Top K Jaccard distance", series=series, y_max=1.0)}'
                "</div>"
            )
        weight_cards.append(
            f'<article class="robustness-message-panel" data-testid="ranking-weight-panel-{_escape(message_id, quote=True)}">'
            f'<header><h3>{_escape(message_id)}</h3><p>Top K Jaccard distance by frozen batch. Rank movement remains available in the exact-value table.</p></header>'
            f'{"".join(family_views)}</article>'
        )

    message_options = "".join(f'<option value="{_escape(message, quote=True)}">{_escape(message)}</option>' for message in message_ids)
    prompt_views: list[str] = []
    metric_specs = (
        ("engagement", "cumulative_exposure_engagement_rate", "Cumulative exposure engagement rate", 1.0),
        ("audience", "cumulative_audience_jaccard_distance_from_baseline_cell", "Cumulative audience Jaccard distance", 1.0),
    )
    for message_index, message_id in enumerate(message_ids):
        for metric_index, (metric_id, field, label, y_max) in enumerate(metric_specs):
            model_cards: list[str] = []
            for model in models:
                model_series: list[dict[str, Any]] = []
                for prompt in ("P0", "P1", "P2", "P3"):
                    rows = sorted(
                        (
                            row
                            for row in trajectories
                            if row["message_id"] == message_id
                            and row["requested_model"] == model
                            and row["prompt_variant"] == prompt
                        ),
                        key=lambda row: int(row["time_step"]),
                    )
                    model_series.append(
                        {
                            "series_id": f"{message_id}-{metric_id}-{model}-{prompt}",
                            "label": prompt,
                            "values": [float(row[field]) for row in rows],
                            "style": _PROMPT_STYLES[prompt],
                        }
                    )
                chart_id = f"prompt-{message_id}-{metric_id}-{_safe_id(model)}"
                model_cards.append(
                    f'<article class="robustness-model-panel" data-testid="prompt-model-panel-{_safe_id(message_id)}-{_safe_id(model)}-{metric_id}">'
                    f'<header><h4>{_escape(model)}</h4><p>Four information-equivalent Prompt series.</p></header>'
                    f'{_line_chart(chart_id=chart_id, title=f"{model} · {label}", series=model_series, y_max=y_max)}'
                    "</article>"
                )
            hidden = "" if message_index == 0 and metric_index == 0 else " hidden"
            prompt_views.append(
                f'<div class="robustness-model-grid" data-prompt-view="{_escape(message_id, quote=True)}|{metric_id}"{hidden}>'
                f'{"".join(model_cards)}</div>'
            )

    growth_cards: list[str] = []
    growth_max = max((int(row["cumulative_campaign_deduplicated_positive_user_count"]) for row in growth), default=1)
    for model in models:
        series = []
        for prompt in ("P0", "P1", "P2", "P3"):
            rows = sorted(
                (
                    row
                    for row in growth
                    if row["requested_model"] == model and row["prompt_variant"] == prompt
                ),
                key=lambda row: int(row["time_step"]),
            )
            series.append(
                {
                    "series_id": f"growth-{model}-{prompt}",
                    "label": prompt,
                    "values": [float(row["cumulative_campaign_deduplicated_positive_user_count"]) for row in rows],
                    "style": _PROMPT_STYLES[prompt],
                }
            )
        growth_cards.append(
            f'<article class="robustness-model-panel" data-testid="prompt-model-growth-panel-{_safe_id(model)}">'
            f'<header><h4>{_escape(model)}</h4><p>Campaign-deduplicated successful Primary-positive users.</p></header>'
            f'{_line_chart(chart_id=f"growth-{_safe_id(model)}", title=f"{model} · campaign growth", series=series, y_max=float(max(1, growth_max)))}'
            "</article>"
        )

    threshold_counts: dict[str, int] = defaultdict(int)
    for row in thresholds:
        threshold_counts[str(row["classification"])] += 1
    meaningful = threshold_counts["practically_meaningful"]
    small = threshold_counts["small_observed_difference"]
    download_links = "".join(
        f'<a class="robustness-download" data-testid="robustness-download-{_safe_id(key)}" href="{_escape(path, quote=True)}"><span>{_escape(key.replace("_", " ").title())}</span><code>{_escape(path)}</code></a>'
        for key, path in downloads.items()
    )

    return f"""
        <section id="robustness-evidence" class="robustness-report" data-testid="{stage_test_id}"{stage_attribute} aria-labelledby="robustness-title">
          <div class="robustness-hero">
            <p class="robustness-kicker">Additive evidence · 增量证据</p>
            <h2 id="robustness-title">Ranking policy and Prompt–Model robustness, without relabelling the historical run</h2>
            <p>One fixed sample, one fixed graph, and one realized path per cell. These descriptive comparisons use no ground truth and make no causal, Calibration, or statistical-equivalence claim.</p>
            <code data-testid="robustness-production-eligibility">production_deploy_eligible={eligibility}</code>
          </div>
          <div class="robustness-lineage" data-testid="robustness-source-lineage">
            <article data-source-kind="formal">
              <span>Historical Concurrent Formal source</span>
              <strong>{_escape(formal['source_id'])}</strong>
              <code>{_escape(formal['manifest_sha256'])}</code>
              <p>Mechanism, Run Evidence, field lineage, Demographic Shadow comparison, and the Primary + Shadow barrier remain sourced here.</p>
            </article>
            <div class="robustness-lineage-arrow" aria-hidden="true">＋</div>
            <article data-source-kind="study">
              <span>Immutable complete study root</span>
              <strong>{_escape(study['output_identity'])}</strong>
              <code>{_escape(study['root_identity_sha256'])}</code>
              <p>Ranking Weight and Primary-only 4 Prompt × 4 model evidence. No Shadow condition was rerun.</p>
            </article>
          </div>
          <p class="robustness-source-warning" data-testid="robustness-shadow-source-label">Demographic Shadow evidence remains bound to the historical Formal source; it is not a factorial Prompt–Model result.</p>

          <section class="robustness-section" data-testid="ranking-weight-sensitivity-section" aria-labelledby="ranking-weight-title">
            <div class="robustness-section-heading">
              <div><h2 id="ranking-weight-title">Ranking Weight Sensitivity</h2><p>19 predeclared simplex points, shown as six-series transfer families rather than one 19-line panel. Candidate sets and feedback stay frozen.</p></div>
              <label>Visible transfer family<select data-testid="ranking-weight-family-select" data-weight-family-select>{family_options}</select></label>
            </div>
            <div class="robustness-message-grid">{"".join(weight_cards)}</div>
            <details class="robustness-table-disclosure" data-testid="ranking-weight-exact-table">
              <summary>Exact message-level Jaccard summaries · {len(weight_messages)} rows</summary>
              {_table(_WEIGHT_MESSAGE_FIELDS, weight_messages, test_id="ranking-weight-message-table")}
            </details>
            <details class="robustness-table-disclosure" data-testid="ranking-weight-rank-exact-table">
              <summary>Exact per-batch entered/exited and rank movement diagnostics · {len(weight_batches)} rows</summary>
              {_table(_WEIGHT_BATCH_FIELDS, weight_batches, test_id="ranking-weight-batch-table")}
            </details>
          </section>

          <section class="robustness-section" data-testid="prompt-model-robustness-section" aria-labelledby="prompt-model-title">
            <div class="robustness-section-heading">
              <div><h2 id="prompt-model-title">Prompt–Model Robustness</h2><p>Each model panel carries at most the four P0–P3 series. Later paths are descriptive; only shared-seed Batch 0 Decisions form the predeclared direct paired panel.</p></div>
              <div class="robustness-controls">
                <label>Message<select data-testid="prompt-model-message-select" data-prompt-message-select>{message_options}</select></label>
                <label>Dynamic metric<select data-testid="prompt-model-metric-select" data-prompt-metric-select><option value="engagement">Engagement rate</option><option value="audience">Audience distance</option></select></label>
              </div>
            </div>
            <div data-testid="prompt-model-dynamic-panels">{"".join(prompt_views)}</div>
            <div class="robustness-subsection-heading"><h3>Shared-seed direct Decisions</h3><p>Binary engage is primary; probability and confidence are secondary. Rows follow the selected message.</p></div>
            <div data-testid="prompt-model-shared-seed-table">{_table(_SHARED_SEED_FIELDS, shared_seed, test_id="shared-seed-exact-table", row_attribute="message_id")}</div>
            <div class="robustness-subsection-heading"><h3>Campaign-level positive-user growth</h3><p>Growth is campaign-deduplicated across messages, so it is kept outside message panels rather than mislabelled as a message-specific outcome.</p></div>
            <div class="robustness-model-grid" data-testid="prompt-model-growth-panels">{"".join(growth_cards)}</div>
            <div class="robustness-threshold-summary" data-testid="practical-threshold-summary">
              <article><strong>{meaningful}</strong><span>practically meaningful</span></article>
              <article><strong>{small}</strong><span>small_observed_difference</span></article>
              <p>Below-threshold values are small observed differences only; they do not establish equivalence.</p>
            </div>
            <details class="robustness-table-disclosure" data-testid="prompt-model-message-exact-table">
              <summary>Exact per-message dynamic summaries · {len(prompt_messages)} rows</summary>
              {_table(_PROMPT_MESSAGE_FIELDS, prompt_messages, test_id="prompt-model-message-table")}
            </details>
            <details class="robustness-table-disclosure" data-testid="practical-threshold-exact-table">
              <summary>Exact practical-threshold classifications · {len(thresholds)} rows</summary>
              {_table(_THRESHOLD_FIELDS, thresholds, test_id="threshold-table")}
            </details>
          </section>

          <section class="robustness-section robustness-downloads" data-testid="robustness-downloads-section" aria-labelledby="robustness-downloads-title">
            <div class="robustness-section-heading"><div><h2 id="robustness-downloads-title">Approved robustness downloads</h2><p>Companion JSON and CSV files close to the schemas, row counts, hashes, and exact values in this {download_scope}. No raw Prompt, Provider payload, response, or credential is included.</p></div></div>
            <div class="robustness-download-grid">{download_links}</div>
          </section>
        </section>
    """


def _line_chart(
    *,
    chart_id: str,
    title: str,
    series: Sequence[Mapping[str, Any]],
    y_max: float,
) -> str:
    width, height = 760.0, 238.0
    left, right, top, bottom = 54.0, 18.0, 22.0, 38.0
    plot_width = width - left - right
    plot_height = height - top - bottom
    max_points = max((len(_sequence(row["values"], "chart values")) for row in series), default=1)
    denominator = max(1, max_points - 1)
    safe_y_max = max(float(y_max), 1e-12)
    grid: list[str] = []
    for index in range(5):
        fraction = index / 4
        y = top + plot_height * (1.0 - fraction)
        label = _display(safe_y_max * fraction)
        grid.append(
            f'<line x1="{left:.2f}" y1="{y:.2f}" x2="{width - right:.2f}" y2="{y:.2f}" />'
            f'<text x="{left - 9:.2f}" y="{y + 4:.2f}" text-anchor="end">{_escape(label)}</text>'
        )
    marks: list[str] = []
    legends: list[str] = []
    for row in series:
        values = [float(value) for value in _sequence(row["values"], "chart values")]
        style = _mapping(row["style"], "chart series style")
        points = [
            (
                left + plot_width * index / denominator,
                top + plot_height * (1.0 - min(max(value / safe_y_max, 0.0), 1.0)),
            )
            for index, value in enumerate(values)
        ]
        point_text = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
        series_id = str(row["series_id"])
        dash = str(style.get("dash", ""))
        dash_attr = f' stroke-dasharray="{_escape(dash, quote=True)}"' if dash else ""
        marker_markup = "".join(
            _marker(str(style["marker"]), x, y, str(style["color"])) for x, y in points
        )
        marks.append(
            f'<g data-series-id="{_escape(series_id, quote=True)}"><polyline points="{point_text}" fill="none" stroke="{_escape(style["color"], quote=True)}" stroke-width="2.6" vector-effect="non-scaling-stroke"{dash_attr}/>{marker_markup}</g>'
        )
        legends.append(
            f'<li class="robustness-legend-item" data-legend-series-id="{_escape(series_id, quote=True)}">'
            f'{_legend_sample(style)}<span>{_escape(row["label"])}</span></li>'
        )
    return (
        f'<div class="robustness-chart-shell" data-chart-id="{_escape(chart_id, quote=True)}">'
        f'<div class="robustness-chart"><svg viewBox="0 0 {int(width)} {int(height)}" role="img" aria-labelledby="{_escape(chart_id, quote=True)}-title">'
        f'<title id="{_escape(chart_id, quote=True)}-title">{_escape(title)}</title>'
        f'<g class="robustness-grid">{"".join(grid)}</g><g class="robustness-series">{"".join(marks)}</g>'
        f'<text class="robustness-axis-label" x="{width / 2:.2f}" y="{height - 7:.2f}" text-anchor="middle">Batch index</text>'
        "</svg></div>"
        f'<ul class="robustness-legend" aria-label="Visible series for {_escape(title, quote=True)}">{"".join(legends)}</ul>'
        "</div>"
    )


def _marker(marker: str, x: float, y: float, color: str) -> str:
    escaped_color = _escape(color, quote=True)
    if marker == "circle":
        return f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3.6" fill="{escaped_color}"/>'
    if marker == "square":
        return f'<rect x="{x - 3.5:.2f}" y="{y - 3.5:.2f}" width="7" height="7" fill="{escaped_color}"/>'
    if marker == "triangle":
        return f'<polygon points="{x:.2f},{y - 4.4:.2f} {x - 4.2:.2f},{y + 3.5:.2f} {x + 4.2:.2f},{y + 3.5:.2f}" fill="{escaped_color}"/>'
    if marker == "diamond":
        return f'<polygon points="{x:.2f},{y - 4.4:.2f} {x - 4.4:.2f},{y:.2f} {x:.2f},{y + 4.4:.2f} {x + 4.4:.2f},{y:.2f}" fill="{escaped_color}"/>'
    if marker == "cross":
        return f'<path d="M{x - 3.5:.2f},{y - 3.5:.2f} L{x + 3.5:.2f},{y + 3.5:.2f} M{x + 3.5:.2f},{y - 3.5:.2f} L{x - 3.5:.2f},{y + 3.5:.2f}" stroke="{escaped_color}" stroke-width="2"/>'
    return f'<path d="M{x - 4:.2f},{y:.2f} H{x + 4:.2f} M{x:.2f},{y - 4:.2f} V{y + 4:.2f}" stroke="{escaped_color}" stroke-width="2"/>'


def _legend_sample(style: Mapping[str, Any]) -> str:
    dash = str(style.get("dash", ""))
    dash_attr = f' stroke-dasharray="{_escape(dash, quote=True)}"' if dash else ""
    color = str(style["color"])
    return (
        '<svg class="robustness-legend-sample" viewBox="0 0 52 16" aria-hidden="true">'
        f'<line x1="2" y1="8" x2="50" y2="8" stroke="{_escape(color, quote=True)}" stroke-width="2.4"{dash_attr}/>'
        f'{_marker(str(style["marker"]), 26, 8, color)}</svg>'
    )


def _table(
    fields: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
    *,
    test_id: str,
    row_attribute: str | None = None,
) -> str:
    headings = "".join(f"<th scope=\"col\">{_escape(field.replace('_', ' '))}</th>" for field in fields)
    body: list[str] = []
    for row in rows:
        attribute = ""
        if row_attribute is not None:
            attribute = f' data-row-{row_attribute.replace("_", "-")}="{_escape(row.get(row_attribute), quote=True)}"'
        cells = "".join(f"<td>{_escape(_display(row.get(field)))}</td>" for field in fields)
        body.append(f"<tr{attribute}>{cells}</tr>")
    return (
        '<div class="robustness-table-wrap">'
        f'<table data-testid="{_escape(test_id, quote=True)}"><thead><tr>{headings}</tr></thead><tbody>{"".join(body)}</tbody></table>'
        "</div>"
    )


def _assert_formal_unchanged(
    closure: ConcurrentMessageArtifactClosure,
    expected_hashes: Mapping[str, str],
) -> None:
    actual_files: set[str] = set()
    for path in closure.run_dir.rglob("*"):
        relative = path.relative_to(closure.run_dir).as_posix()
        if path.is_symlink():
            raise _RobustnessReportClosureError("historical Formal source changed during report composition")
        if path.is_file():
            actual_files.add(relative)
        elif not path.is_dir():
            raise _RobustnessReportClosureError("historical Formal source changed during report composition")
    if actual_files != set(expected_hashes):
        raise _RobustnessReportClosureError("historical Formal source artifact set changed")
    if {path: _sha256_file(closure.run_dir / path) for path in expected_hashes} != dict(expected_hashes):
        raise _RobustnessReportClosureError("historical Formal source artifact hashes changed")


def _assert_study_unchanged(study: _ClosedStudy, expected_hashes: Mapping[str, str]) -> None:
    entries = list(study.root.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in entries):
        raise _RobustnessReportClosureError("immutable study root changed during report composition")
    if {path.name for path in entries} != set(expected_hashes):
        raise _RobustnessReportClosureError("immutable study root artifact set changed")
    if {path.name: _sha256_file(path) for path in entries} != dict(expected_hashes):
        raise _RobustnessReportClosureError("immutable study root artifact hashes changed")


def _csv_bytes(fields: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(fields), lineterminator="\n", extrasaction="raise")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: _csv_value(row.get(field)) for field in fields})
    return stream.getvalue().encode("utf-8")


def _csv_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return _display(value)
    return value


def _display(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _RobustnessReportClosureError("report values must be finite")
        return format(value, ".12g")
    return str(value)


def _round(value: float) -> float:
    rounded = round(value, 12)
    return 0.0 if rounded == 0.0 else rounded


def _safe_id(value: object) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", str(value)).strip("-")


def _escape(value: object, *, quote: bool = False) -> str:
    return html.escape(str(value), quote=quote)


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return {str(key): item for key, item in value.items()}


def _sequence(value: object, label: str) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{label} must be a list")
    return list(value)


def _object_sequence(value: object, label: str) -> list[dict[str, Any]]:
    rows = _sequence(value, label)
    if any(not isinstance(row, Mapping) for row in rows):
        raise ValueError(f"{label} must contain objects")
    return [{str(key): item for key, item in row.items()} for row in rows]


def _string_sequence(value: object, label: str) -> list[str]:
    rows = [str(item) for item in _sequence(value, label)]
    if any(not item for item in rows) or len(rows) != len(set(rows)):
        raise ValueError(f"{label} must contain unique strings")
    return rows


def _string_mapping(value: object, label: str) -> dict[str, str]:
    mapping = _mapping(value, label)
    result = {key: str(item) for key, item in mapping.items()}
    if any(not key or not item for key, item in result.items()):
        raise ValueError(f"{label} must contain non-empty strings")
    return result


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain one JSON object")
    return payload


def _json_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


_ROBUSTNESS_CSS = r"""
.robustness-report{--rob-ink:#172033;--rob-muted:#5b6473;--rob-line:#d9dee7;--rob-surface:#f6f8fb;--rob-accent:#155e75;color:var(--rob-ink);background:#fbfcfe;border-top:1px solid var(--rob-line);padding:clamp(4rem,8vw,8rem) max(1rem,calc((100vw - 1320px)/2));font-family:inherit}
.robustness-report *{box-sizing:border-box}.robustness-report [hidden]{display:none!important}.robustness-hero{max-width:980px}.robustness-kicker{font-size:.78rem;font-weight:700;letter-spacing:.13em;text-transform:uppercase;color:var(--rob-accent);margin:0 0 1rem}.robustness-hero h2{font-size:clamp(2rem,4.4vw,4.6rem);line-height:1.02;letter-spacing:-.045em;max-width:16ch;margin:0}.robustness-hero>p:not(.robustness-kicker){max-width:72ch;color:var(--rob-muted);font-size:1.05rem;line-height:1.65;margin:1.5rem 0}.robustness-hero>code{display:inline-block;border:1px solid var(--rob-line);background:white;padding:.55rem .75rem;border-radius:.35rem;color:#8a341f}
.robustness-lineage{display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);gap:1rem;align-items:stretch;margin:3rem 0 1rem}.robustness-lineage article{border-top:3px solid var(--rob-accent);background:white;padding:1.35rem;min-width:0}.robustness-lineage article span{display:block;color:var(--rob-muted);font-size:.8rem;text-transform:uppercase;letter-spacing:.08em}.robustness-lineage article strong{display:block;font-size:1.15rem;margin:.55rem 0}.robustness-lineage article code{display:block;overflow-wrap:anywhere;font-size:.74rem;color:var(--rob-muted)}.robustness-lineage article p{line-height:1.55;margin:1rem 0 0}.robustness-lineage-arrow{align-self:center;font-size:2rem;color:var(--rob-muted)}.robustness-source-warning{border-left:4px solid #b45309;background:#fff8eb;padding:1rem 1.2rem;line-height:1.55;margin:0 0 6rem}
.robustness-section{padding:5rem 0;border-top:1px solid var(--rob-line)}.robustness-section-heading{display:flex;align-items:end;justify-content:space-between;gap:2rem;margin-bottom:2rem}.robustness-section-heading>div:first-child{max-width:820px}.robustness-section h2{font-size:clamp(1.8rem,3vw,3.2rem);letter-spacing:-.035em;margin:0 0 .8rem}.robustness-section-heading p,.robustness-subsection-heading p{color:var(--rob-muted);line-height:1.6;margin:0;max-width:72ch}.robustness-section label{display:grid;gap:.45rem;color:var(--rob-muted);font-size:.78rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase}.robustness-section select{min-width:14rem;background:white;border:1px solid #aeb7c5;border-radius:.35rem;padding:.72rem 2.2rem .72rem .75rem;color:var(--rob-ink);font:inherit;text-transform:none;letter-spacing:0}.robustness-section select:focus-visible,.robustness-download:focus-visible,.robustness-table-disclosure summary:focus-visible{outline:3px solid rgba(21,94,117,.32);outline-offset:3px}
.robustness-message-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1rem}.robustness-message-panel,.robustness-model-panel{min-width:0;background:white;border-top:2px solid #aeb7c5;padding:1.1rem}.robustness-message-panel header,.robustness-model-panel header{min-height:4.7rem}.robustness-message-panel h3,.robustness-model-panel h4{margin:0 0 .35rem;font-size:1rem}.robustness-message-panel p,.robustness-model-panel p{margin:0;color:var(--rob-muted);font-size:.82rem;line-height:1.45}.robustness-chart-shell{display:grid;grid-template-columns:minmax(0,1fr) minmax(8.5rem,.38fr);gap:.8rem;align-items:start;margin-top:1rem}.robustness-chart{min-width:0}.robustness-chart svg{display:block;width:100%;height:auto;aspect-ratio:3.2/1;background:var(--rob-surface);overflow:visible}.robustness-grid line{stroke:#dce2ea;stroke-width:1}.robustness-grid text,.robustness-axis-label{fill:#697386;font-size:11px}.robustness-legend{list-style:none;margin:0;padding:0;display:grid;gap:.35rem}.robustness-legend-item{width:100%;display:grid;grid-template-columns:52px minmax(0,1fr);align-items:center;gap:.45rem;padding:.28rem;color:var(--rob-ink);font-size:.7rem;line-height:1.25}.robustness-legend-sample{display:block;width:52px;height:16px}.robustness-model-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem}.robustness-controls{display:flex;gap:1rem;flex-wrap:wrap}.robustness-subsection-heading{margin:4rem 0 1.2rem}.robustness-subsection-heading h3{font-size:1.45rem;margin:0 0 .45rem}
.robustness-table-disclosure{margin-top:2rem;border-top:1px solid var(--rob-line);background:white}.robustness-table-disclosure summary{cursor:pointer;padding:1rem;font-weight:700}.robustness-table-wrap{max-width:100%;overflow:auto;border-top:1px solid var(--rob-line)}.robustness-table-wrap table{width:max-content;min-width:100%;border-collapse:collapse;font-size:.75rem}.robustness-table-wrap th,.robustness-table-wrap td{padding:.62rem .7rem;border-bottom:1px solid #e6eaf0;text-align:left;white-space:nowrap}.robustness-table-wrap th{position:sticky;top:0;background:#eef2f7;color:#465164}.robustness-threshold-summary{display:grid;grid-template-columns:auto auto minmax(0,1fr);gap:1rem;align-items:center;margin:3rem 0;background:#eef3f6;padding:1.25rem}.robustness-threshold-summary article{display:grid;gap:.2rem}.robustness-threshold-summary strong{font-size:1.65rem}.robustness-threshold-summary span,.robustness-threshold-summary p{font-size:.78rem;color:var(--rob-muted);margin:0}.robustness-download-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.65rem}.robustness-download{display:grid;gap:.35rem;padding:1rem;border:1px solid var(--rob-line);background:white;color:var(--rob-ink);text-decoration:none}.robustness-download:hover{border-color:var(--rob-accent)}.robustness-download span{font-weight:700}.robustness-download code{font-size:.72rem;color:var(--rob-muted);overflow-wrap:anywhere}
@media(max-width:980px){.robustness-message-grid,.robustness-model-grid{grid-template-columns:1fr}.robustness-chart-shell{grid-template-columns:1fr}.robustness-legend{grid-template-columns:repeat(2,minmax(0,1fr))}.robustness-message-panel header,.robustness-model-panel header{min-height:0}.robustness-section-heading{align-items:start;flex-direction:column}.robustness-lineage{grid-template-columns:1fr}.robustness-lineage-arrow{justify-self:center}.robustness-download-grid{grid-template-columns:1fr}}
@media(max-width:640px){.robustness-report{padding-inline:1rem}.robustness-section{padding:3.5rem 0}.robustness-source-warning{margin-bottom:4rem}.robustness-legend{grid-template-columns:1fr}.robustness-controls{display:grid;width:100%}.robustness-section label,.robustness-section select{width:100%;min-width:0}.robustness-threshold-summary{grid-template-columns:1fr}.robustness-hero h2{font-size:2.35rem}.robustness-chart svg{min-width:0}}
"""


_ROBUSTNESS_SCRIPT = r"""
(() => {
  const report = document.querySelector('[data-testid="__REPORT_STAGE_TEST_ID__"]');
  if (!report) return;
  const familySelect = report.querySelector('[data-weight-family-select]');
  const messageSelect = report.querySelector('[data-prompt-message-select]');
  const metricSelect = report.querySelector('[data-prompt-metric-select]');

  const applyWeightFamily = () => {
    const value = familySelect?.value || 'network-feedback';
    report.querySelectorAll('[data-weight-family]').forEach((panel) => {
      panel.hidden = panel.dataset.weightFamily !== value;
    });
  };
  const applyPromptView = () => {
    const message = messageSelect?.value || 'message_1';
    const metric = metricSelect?.value || 'engagement';
    report.querySelectorAll('[data-prompt-view]').forEach((panel) => {
      panel.hidden = panel.dataset.promptView !== `${message}|${metric}`;
    });
    report.querySelectorAll('[data-row-message-id]').forEach((row) => {
      row.hidden = row.dataset.rowMessageId !== message;
    });
  };

  familySelect?.addEventListener('change', applyWeightFamily);
  messageSelect?.addEventListener('change', applyPromptView);
  metricSelect?.addEventListener('change', applyPromptView);
  applyWeightFamily();
  applyPromptView();
})();
"""
