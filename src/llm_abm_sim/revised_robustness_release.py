"""Immutable v15 release for the explicitly revised four-model recovery study."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .concurrent_robustness_report import _REPORT_PRESENTATION
from .concurrent_robustness_revised import analyze_revised_evidence, close_revised_evidence, inventory, json_bytes, sha
from .concurrent_robustness_revised_report import revised_downloads

SCHEMA = "abm-report-release-contract-v15"
PURPOSE = "full_pool_and_revised_four_model_recovery_research"
ENDPOINT = "https://abm.q1ngyuan.top/"
_CONTRACT_FIELDS = {"schema_version", "release_purpose", "release_id", "source_directory", "implementation_commit", "canonical_endpoint", "source_evidence", "protected_v13_contract", "evidence_identity_sha256", "analysis_sha256", "candidate_report_sha256", "release_identity_sha256", "artifact_sha256", "production_deploy_eligible", "provider_calls"}


def _digest(value: Any) -> str:
    return hashlib.sha256(json_bytes(value)).hexdigest()


def _inside(root: Path, path: str | Path) -> Path:
    p = Path(path)
    p = p if p.is_absolute() else root / p
    if p.is_symlink() or p.absolute() != p.resolve() or not p.is_relative_to(root):
        raise ValueError("Release input must be a nonsymlink path inside repository")
    return p


def _baseline(root: Path, contract_path: Path) -> tuple[Path, dict[str, Any], dict[str, str]]:
    # Reuse the Release-owned protected canonical identity, not caller-selected
    # same-schema declarations. Its hash binds the complete previous inventory.
    from .concurrent_robustness_release import (
        FULL_POOL_V14_PROTECTED_V13_CONTRACT_SHA256,
        FULL_POOL_V14_PROTECTED_V13_MANIFEST_SHA256,
        FULL_POOL_V14_PROTECTED_V13_REPORT_SHA256,
    )
    if sha(contract_path) != FULL_POOL_V14_PROTECTED_V13_CONTRACT_SHA256:
        raise ValueError("v15 requires the exact protected canonical v13 contract")
    contract = json.loads(contract_path.read_text())
    source = _inside(root, contract["source_directory"])
    hashes = {k: v["sha256"] for k, v in inventory(source).items()}
    if hashes != contract["artifact_sha256"] or hashes.get("report.html") != FULL_POOL_V14_PROTECTED_V13_REPORT_SHA256 or hashes.get("artifact_manifest.json") != FULL_POOL_V14_PROTECTED_V13_MANIFEST_SHA256:
        raise ValueError("Protected v13 physical inventory drifted")
    return source, contract, hashes


def _materialize(root: Path, source: dict[str, str], baseline_path: Path, release_id: str):
    baseline, old, hashes = _baseline(root, baseline_path)
    evidence = close_revised_evidence(_inside(root, source["directory"]), evidence_sha256=source["sha256"])
    historical_payload = json.loads((baseline / "historical-1000/concurrent_robustness_report_payload.json").read_text())
    if evidence.document["formal_source_manifest_sha256"] != historical_payload["source_lineage"]["formal"]["manifest_sha256"]:
        raise ValueError("Revised study does not share the protected historical sample source")
    analysis = analyze_revised_evidence(evidence)
    downloads = revised_downloads(evidence, analysis)
    base_html = (baseline / "report.html").read_bytes()
    candidate = _REPORT_PRESENTATION.render_revised_research(base_html, evidence, analysis)
    report = _REPORT_PRESENTATION.render_revised_research(base_html, evidence, analysis, release_id=release_id)
    return baseline, old, hashes, evidence, analysis, downloads, candidate, report


def _release_documents(*, release_id: str, commit: str, old: dict[str, Any], old_hashes: dict[str, str], evidence, analysis, downloads: dict[str, bytes], report: bytes) -> tuple[dict[str, Any], dict[str, str]]:
    content = dict(old_hashes)
    content.pop("artifact_manifest.json")
    content.update({name: hashlib.sha256(payload).hexdigest() for name, payload in downloads.items()})
    content["report.html"] = hashlib.sha256(report).hexdigest()
    identity = _digest({"schema": SCHEMA, "release_id": release_id, "implementation_commit": commit, "protected_v13": old["release_identity_sha256"], "evidence_identity": evidence.document["identity_sha256"], "analysis_sha256": _digest(analysis), "content_sha256": content})
    old_manifest = json.loads((Path(old["_absolute_root"]) / "artifact_manifest.json").read_text())
    approved = old_manifest.get("approved_downloads", {})
    old_downloads = list(approved.values()) if isinstance(approved, dict) else list(approved)
    manifest = {"schema_version": "abm-report-release-manifest-v15", "release_contract_schema": SCHEMA,
        "release_id": release_id, "release_identity_sha256": identity, "implementation_commit": commit,
        "production_deploy_eligible": True, "provider_calls": 0,
        "protected_v13_release_identity": old["release_identity_sha256"],
        "revised_evidence_identity": evidence.document["identity_sha256"], "analysis_sha256": _digest(analysis),
        "approved_downloads": sorted(set(old_downloads) | set(downloads)), "content_sha256": content}
    hashes = {**content, "artifact_manifest.json": _digest(manifest)}
    return manifest, hashes


def promote_revised_research_release(*, repo_root: str | Path, verified_source: str | Path, evidence_sha256: str,
                                    protected_v13_contract: str | Path, destination_dir: str | Path,
                                    release_id: str, implementation_commit: str) -> Path:
    """Create a new immutable release and sibling contract; never deploy.

    Explicit source, canonical baseline and output identity only. Existing
    outputs or overlaps are rejected; original inputs retain bytes and modes.
    """
    root = Path(repo_root).resolve()
    destination = _inside(root, destination_dir)
    source_dir = _inside(root, verified_source)
    baseline_path = _inside(root, protected_v13_contract)
    contract_path = destination.with_name(destination.name + "-release-contract.json")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}", release_id) or not re.fullmatch(r"[0-9a-f]{40}", implementation_commit):
        raise ValueError("Release id or implementation commit is invalid")
    if destination.exists() or contract_path.exists() or destination.is_relative_to(source_dir) or source_dir.is_relative_to(destination):
        raise ValueError("Release destination exists or overlaps source")
    source = {"directory": str(source_dir), "sha256": evidence_sha256}
    baseline, old, old_hashes, evidence, analysis, downloads, candidate, report = _materialize(root, source, baseline_path, release_id)
    if destination.is_relative_to(baseline) or baseline.is_relative_to(destination):
        raise ValueError("Release output overlaps baseline")
    old = {**old, "_absolute_root": str(baseline)}
    manifest, hashes = _release_documents(release_id=release_id, commit=implementation_commit, old=old, old_hashes=old_hashes, evidence=evidence, analysis=analysis, downloads=downloads, report=report)
    contract = {"schema_version": SCHEMA, "release_purpose": PURPOSE, "release_id": release_id,
        "source_directory": str(destination), "implementation_commit": implementation_commit, "canonical_endpoint": ENDPOINT,
        "source_evidence": source, "protected_v13_contract": {"path": str(baseline_path), "sha256": sha(baseline_path)},
        "evidence_identity_sha256": evidence.document["identity_sha256"], "analysis_sha256": _digest(analysis),
        "candidate_report_sha256": hashlib.sha256(candidate).hexdigest(), "release_identity_sha256": manifest["release_identity_sha256"],
        "artifact_sha256": hashes, "production_deploy_eligible": True, "provider_calls": 0}
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".v15-", dir=destination.parent))
    installed_contract = False
    installed_candidate = False
    candidate_path = destination.with_name(destination.name + "-candidate.html")
    try:
        shutil.copytree(baseline, staging, dirs_exist_ok=True)
        for directory in [staging, *(p for p in staging.rglob("*") if p.is_dir())]:
            directory.chmod(directory.stat().st_mode | 0o700)
        # Copy operations preserve baseline modes; only private staging is writable.
        for name, payload in {**downloads, "report.html": report, "artifact_manifest.json": json_bytes(manifest)}.items():
            p = staging / name
            p.parent.mkdir(parents=True, exist_ok=True)
            if p.exists():
                p.chmod(0o644)
            p.write_bytes(payload)
        if {k: v["sha256"] for k, v in inventory(staging).items()} != hashes:
            raise ValueError("v15 staging inventory differs from reconstructed materialization")
        if inventory(source_dir) != evidence.source_inventory:
            raise ValueError("Source changed before release installation")
        _baseline(root, baseline_path)
        with candidate_path.open("xb") as f:
            installed_candidate = True
            f.write(candidate)
        for p in staging.rglob("*"):
            if p.is_file():
                p.chmod(0o444)
        with contract_path.open("xb") as f:
            installed_contract = True
            f.write(json_bytes(contract))
        contract_path.chmod(0o444)
        os.rename(staging, destination)
    except BaseException:
        if installed_contract:
            contract_path.unlink()
        if installed_candidate:
            candidate_path.unlink()
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return contract_path


def validate_revised_research_release(*, repo_root: str | Path, contract_document: dict[str, Any], source_dir: str | Path, snapshot_dir: str | Path | None = None) -> dict[str, Any]:
    """Standalone deterministic reconstruction; hashes alone cannot promote a fixture."""
    c = dict(contract_document)
    if set(c) != _CONTRACT_FIELDS or c["schema_version"] != SCHEMA or c["release_purpose"] != PURPOSE or c["production_deploy_eligible"] is not True or c["provider_calls"] != 0 or c["canonical_endpoint"] != ENDPOINT:
        raise ValueError("v15 contract fields or eligibility are crossed")
    if (not isinstance(c["release_id"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}", c["release_id"])
            or not isinstance(c["implementation_commit"], str) or not re.fullmatch(r"[0-9a-f]{40}", c["implementation_commit"])
            or not isinstance(c["source_evidence"], dict) or set(c["source_evidence"]) != {"directory", "sha256"}
            or not isinstance(c["protected_v13_contract"], dict) or set(c["protected_v13_contract"]) != {"path", "sha256"}):
        raise ValueError("v15 contract identity or source binding is invalid")
    root = Path(repo_root).resolve()
    source = _inside(root, source_dir)
    if str(source) != c["source_directory"]:
        raise ValueError("v15 source directory differs from frozen contract")
    baseline_path = _inside(root, c["protected_v13_contract"]["path"])
    if sha(baseline_path) != c["protected_v13_contract"]["sha256"]:
        raise ValueError("v15 protected contract hash drift")
    baseline, old, old_hashes, evidence, analysis, downloads, candidate, report = _materialize(root, c["source_evidence"], baseline_path, c["release_id"])
    old = {**old, "_absolute_root": str(baseline)}
    manifest, hashes = _release_documents(release_id=c["release_id"], commit=c["implementation_commit"], old=old, old_hashes=old_hashes, evidence=evidence, analysis=analysis, downloads=downloads, report=report)
    if (c["evidence_identity_sha256"] != evidence.document["identity_sha256"] or c["analysis_sha256"] != _digest(analysis)
            or c["candidate_report_sha256"] != hashlib.sha256(candidate).hexdigest()
            or c["release_identity_sha256"] != manifest["release_identity_sha256"] or c["artifact_sha256"] != hashes):
        raise ValueError("v15 release declarations differ from source-rebuilt facts")
    for directory in (source, *( [Path(snapshot_dir)] if snapshot_dir else [])):
        if {k: v["sha256"] for k, v in inventory(directory).items()} != hashes:
            raise ValueError("v15 physical inventory differs from source-rebuilt files")
    return {**c, "report_sha256": hashes["report.html"], "manifest_sha256": hashes["artifact_manifest.json"],
            "realized_source_identity": evidence.document["identity_sha256"],
            "revised_counts": evidence.document["counts"], "formal_research_evidence": True}


def require_revised_deployment_profile(result: dict[str, Any]) -> dict[str, Any]:
    """Release-owned minimal deployment projection, never recalculated by Deployment."""
    if (result.get("schema_version") != SCHEMA or result.get("production_deploy_eligible") is not True
            or result.get("formal_research_evidence") is not True or result.get("provider_calls") != 0
            or result.get("revised_counts", {}).get("judgments") != 28800
            or result.get("revised_counts", {}).get("cells") != 16
            or result.get("revised_counts", {}).get("barriers") != 480):
        raise ValueError("v15 deployment requires independently validated revised Formal release")
    return {"realized_source_identity": result["realized_source_identity"],
        "release_readiness": {"schema_version": "revised-four-model-v15-release-readiness-v1", "release_contract_schema": SCHEMA,
            "release_id": result["release_id"], "realized_source_identity": result["realized_source_identity"],
            "canonical_endpoint": ENDPOINT, "provider_calls": 0, "operational_authorization_required": True,
            "deployment_authorized": False, "public_acceptance_recorded": False}}
