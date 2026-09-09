"""Publication Seam tests; replaced bundle facts are NOT a Formal proof.

Full-shape/source/usage proof belongs to the independent bundle/Evidence tests.
Here a deliberately empty derived DTO isolates immutable filesystem behavior.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from llm_abm_sim import concurrent_robustness_recovery_evidence as evidence
from llm_abm_sim import concurrent_robustness_recovery_report as report


@pytest.fixture
def publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    source = tmp_path / "source"
    campaign = tmp_path / "campaign"
    source.mkdir()
    campaign.mkdir()
    bundle = campaign / "bundle.json"
    bundle.write_text("synthetic publication seam, not a recovery bundle\n")
    bundle.chmod(0o444)
    manifest = SimpleNamespace(source=SimpleNamespace(source_dir=source),
                               model_dump=lambda **_: {"test_only": "publication seam"})
    origins = SimpleNamespace(source=SimpleNamespace(manifest=manifest),
                              campaign={"control_root": str(campaign), "source_anchor_path": str(tmp_path / "anchor.json")},
                              proposal={"source_artifacts": [], "inherited_cells": []})
    def verified(path: str | Path) -> Any:
        return SimpleNamespace(bundle_path=Path(path), origins=origins, batch_commits=(),
                               document={"artifact_facts": [{"path": str(bundle)}]})
    monkeypatch.setattr(evidence._bundle, "_read_verified_recovery_bundle", verified)
    document = {"schema_version": evidence.RECOVERY_EVIDENCE_SCHEMA, "evidence_path": "", "source_bundle": {},
                "counts": {"test_only": 0}, "formal_evidence_closed": True,
                "production_deploy_eligible": False, "provider_calls_during_composition": 0}
    monkeypatch.setattr(evidence, "_derive", lambda _: (dict(document), (), (), (), (), {}, ()))
    return bundle, tmp_path / "output"


def _replace(path: Path, body: bytes) -> None:
    path.chmod(0o644)
    path.write_bytes(body)
    path.chmod(0o444)


def _edit_document(root: Path, change: dict[str, Any]) -> None:
    path = root / "evidence.json"
    document = json.loads(path.read_bytes())
    document.update(change)
    body = evidence._json_bytes(document)
    _replace(path, body)
    manifest_path = root / "artifact_manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["inventory"]["evidence.json"] = {"sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
    _replace(manifest_path, evidence._json_bytes(manifest))


def test_evidence_publication_is_idempotent_only_for_exact_explicit_bundle(publication: tuple[Path, Path]) -> None:
    bundle, root = publication
    path = evidence.close_concurrent_robustness_recovery_evidence(bundle, output_dir=root)
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    assert evidence.close_concurrent_robustness_recovery_evidence(bundle, output_dir=root) == path
    other = bundle.parent / "other.json"
    other.write_text("different synthetic checkpoint\n")
    other.chmod(0o444)
    with pytest.raises(evidence.RecoveryEvidenceError, match="different explicit bundle"):
        evidence.close_concurrent_robustness_recovery_evidence(other, output_dir=root)
    assert {p.name: p.read_bytes() for p in root.iterdir()} == before


@pytest.mark.parametrize("change", [{"counts": {"test_only": 36000}}, {"schema_version": "legacy-v2"}])
def test_rehashed_local_claim_does_not_replace_reconstructed_origin(
    publication: tuple[Path, Path], change: dict[str, Any],
) -> None:
    bundle, root = publication
    path = evidence.close_concurrent_robustness_recovery_evidence(bundle, output_dir=root)
    _edit_document(root, change)
    with pytest.raises(evidence.RecoveryEvidenceError, match="independently reconstructed"):
        evidence.read_concurrent_robustness_recovery_evidence(path)


def test_evidence_manifest_rejects_extra_fields(publication: tuple[Path, Path]) -> None:
    bundle, root = publication
    path = evidence.close_concurrent_robustness_recovery_evidence(bundle, output_dir=root)
    manifest_path = root / "artifact_manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["foreign_claim"] = True
    _replace(manifest_path, evidence._json_bytes(manifest))
    with pytest.raises(evidence.RecoveryEvidenceError, match="independently reconstructed"):
        evidence.read_concurrent_robustness_recovery_evidence(path)


@pytest.mark.parametrize("filename", evidence._INVENTORY)
def test_every_new_evidence_file_requires_readonly_mode(publication: tuple[Path, Path], filename: str) -> None:
    bundle, root = publication
    path = evidence.close_concurrent_robustness_recovery_evidence(bundle, output_dir=root)
    (root / filename).chmod(0o644)
    with pytest.raises(evidence.RecoveryEvidenceError, match="immutable"):
        evidence.read_concurrent_robustness_recovery_evidence(path)


def test_protected_and_foreign_outputs_are_not_repaired(publication: tuple[Path, Path]) -> None:
    bundle, root = publication
    with pytest.raises(evidence.RecoveryEvidenceError, match="protected"):
        evidence.close_concurrent_robustness_recovery_evidence(bundle, output_dir=bundle.parent / "evidence")
    root.mkdir()
    foreign = root / "foreign.txt"
    foreign.write_text("keep")
    with pytest.raises(evidence.RecoveryEvidenceError, match="cannot be repaired"):
        evidence.close_concurrent_robustness_recovery_evidence(bundle, output_dir=root)
    assert foreign.read_text() == "keep"


def test_report_failure_preserves_evidence_and_retries_only_own_exact_files(
    publication: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, root = publication
    monkeypatch.setattr(report, "_payloads", lambda _: ({"data.csv": b"test-only\n", "report.html": b"test-only report\n"}, {"csv": "data.csv"}))
    publish = report._publish_file
    def fail_after_first(path: Path, body: bytes) -> None:
        if path.name == "report.html":
            raise OSError("synthetic report failure")
        publish(path, body)
    monkeypatch.setattr(report, "_publish_file", fail_after_first)
    with pytest.raises(OSError, match="synthetic report failure"):
        report.export_concurrent_robustness_recovery_report(bundle, output_dir=root)
    assert not (root / "artifact_manifest.json").exists()
    evidence_bytes = {p.name: p.read_bytes() for p in (root / "evidence").iterdir()}
    assert (root / "data.csv").read_bytes() == b"test-only\n"
    monkeypatch.setattr(report, "_publish_file", publish)
    path = report.export_concurrent_robustness_recovery_report(bundle, output_dir=root)
    assert report.inspect_concurrent_robustness_recovery_report(path)["report_status"] == "complete"
    assert {p.name: p.read_bytes() for p in (root / "evidence").iterdir()} == evidence_bytes
    _replace(root / "data.csv", b"foreign bytes\n")
    with pytest.raises(report.RecoveryReportError, match="immutable expected bytes"):
        report.inspect_concurrent_robustness_recovery_report(path)
