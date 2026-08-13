from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_abm_sim import concurrent_robustness_evidence as evidence
from llm_abm_sim.concurrent_message_mechanism_presentation import _MECHANISM_PRESENTATION


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _candidate(
    path: Path,
    marker: str,
    *,
    formal_manifest_sha256: str,
    study_manifest_sha256: str,
    study_artifact_manifest_sha256: str,
    payload_version: int = 1,
) -> None:
    path.mkdir()
    (path / "report.html").write_text(f"report {marker}\n", encoding="utf-8")
    mechanism = _MECHANISM_PRESENTATION.build()
    downloads = {"sample": "sample.json"}
    payload: dict[str, object] = {
        "schema_version": f"concurrent-robustness-report-payload-v{payload_version}",
        "title": "fixture",
        "source_lineage": {},
        "ranking_weight": {},
        "prompt_model": {},
        "row_counts": {},
        "trace_row_count": 1,
        "downloads": downloads,
        "claim_boundary": {},
        "production_deploy_eligible": False,
    }
    if payload_version == 2:
        masters = {artifact.filename: artifact.sha256 for artifact in mechanism.mermaid_artifacts}
        downloads.update(
            {
                "mechanism_sample_first_mermaid": "mechanism-sample-first.mmd",
                "mechanism_pair_formation_mermaid": "mechanism-pair-formation.mmd",
                "mechanism_independent_delivery_mermaid": "mechanism-independent-delivery.mmd",
                "mechanism_exposure_decisions_mermaid": "mechanism-exposure-decisions.mmd",
                "mechanism_feedback_boundary_mermaid": "mechanism-feedback-boundary.mmd",
                "real_batch_mechanism_mermaid": "real-batch-mechanism.mmd",
                "prompt_model_factorial_mermaid": "prompt-model-factorial.mmd",
            }
        )
        (path / "prompt-model-factorial.mmd").write_text("flowchart TB\n", encoding="utf-8")
        payload["mechanism_presentation"] = {
            "schema_version": mechanism.schema_version,
            "semantic_set_identity_sha256": mechanism.semantic_set_identity_sha256,
            "masters": masters,
        }
        for artifact in mechanism.mermaid_artifacts:
            (path / artifact.filename).write_bytes(artifact.payload)
    _write_json(path / "concurrent_robustness_report_payload.json", payload)
    _write_json(
        path / "release_evidence.json",
        {
            "schema_version": "concurrent-robustness-report-release-evidence-v1",
            "candidate_type": "complete_fixture_report_candidate",
            "candidate_content_identity_sha256": "e" * 64,
            "formal_source_manifest_sha256": formal_manifest_sha256,
            "study_manifest_sha256": study_manifest_sha256,
            "study_root_identity_sha256": "d" * 64,
            "provider_calls_during_composition": 0,
            "image_generation_triggered": False,
            "canonical_deployment_triggered": False,
            "production_deploy_eligible": False,
        },
    )
    (path / "sample.json").write_text(f"sample {marker}\n", encoding="utf-8")
    artifacts = {
        "report_html": "report.html",
        "report_payload_json": "concurrent_robustness_report_payload.json",
        "release_evidence_json": "release_evidence.json",
        "sample_json": "sample.json",
        **{
            artifact.filename.removesuffix(".mmd").replace("-", "_"): artifact.filename
            for artifact in mechanism.mermaid_artifacts
            if payload_version == 2
        },
        **({"prompt_model_factorial": "prompt-model-factorial.mmd"} if payload_version == 2 else {}),
    }
    content_hashes = {
        relative: _sha256(path / relative)
        for relative in artifacts.values()
        if relative != "release_evidence.json"
    }
    release_path = path / "release_evidence.json"
    release_document = json.loads(release_path.read_text(encoding="utf-8"))
    release_document["candidate_content_identity_sha256"] = hashlib.sha256(
        (json.dumps(content_hashes, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ).hexdigest()
    _write_json(release_path, release_document)
    hashes = {name: _sha256(path / relative) for name, relative in artifacts.items()}
    identity_rows = {relative: hashes[name] for name, relative in sorted(artifacts.items())}
    identity = hashlib.sha256(
        (json.dumps(identity_rows, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ).hexdigest()
    _write_json(
        path / "artifact_manifest.json",
        {
            "schema_version": "concurrent-robustness-report-candidate-manifest-v1",
            "candidate_type": "immutable_combined_robustness_report",
            "candidate_identity_sha256": identity,
            "formal_source": {"manifest_sha256": formal_manifest_sha256},
            "study_source": {
                "manifest_sha256": study_manifest_sha256,
                "artifact_manifest_sha256": study_artifact_manifest_sha256,
                "root_identity_sha256": "d" * 64,
            },
            "report_schema": payload["schema_version"],
            "artifacts": artifacts,
            "sha256": hashes,
            "row_counts": {},
            "approved_downloads": list(downloads.values()),
            "production_deploy_eligible": False,
        },
    )


@pytest.fixture
def closure_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    root = tmp_path.resolve()
    formal = root / "formal"
    study = root / "study"
    workspace = root / "workspace"
    old_candidate = root / "old-candidate"
    new_candidate = root / "new-candidate"
    contracts = root / "contracts"
    for directory in (formal, study, workspace, contracts):
        directory.mkdir()
    _write_json(formal / "artifact_manifest.json", {"formal": True})
    _write_json(study / "study_manifest.json", {"study": True})
    _write_json(study / "artifact_manifest.json", {"root_identity_sha256": "d" * 64})
    formal_manifest_sha256 = _sha256(formal / "artifact_manifest.json")
    study_manifest_sha256 = _sha256(study / "study_manifest.json")
    study_artifact_manifest_sha256 = _sha256(study / "artifact_manifest.json")
    _candidate(
        old_candidate,
        "old",
        formal_manifest_sha256=formal_manifest_sha256,
        study_manifest_sha256=study_manifest_sha256,
        study_artifact_manifest_sha256=study_artifact_manifest_sha256,
    )
    _candidate(
        new_candidate,
        "new",
        formal_manifest_sha256=formal_manifest_sha256,
        study_manifest_sha256=study_manifest_sha256,
        study_artifact_manifest_sha256=study_artifact_manifest_sha256,
        payload_version=2,
    )
    replay = contracts / "replay.json"
    replay.write_text("replay\n", encoding="utf-8")
    execution = contracts / "execution.json"
    _write_json(
        execution,
        {
            "report_candidate": str(old_candidate),
            "closure_replay_artifact": str(replay),
            "closure_replay_sha256": _sha256(replay),
            "physical_provider_attempts": 28_800,
            "subscription_nominal_reference_cost_usd": 0.0,
            "implementation_commit": "1234567",
            "closure_implementation_commit": "7654321",
        },
    )

    class FakeManifest:
        @staticmethod
        def model_validate(_payload: object) -> SimpleNamespace:
            return SimpleNamespace(
                output_identity="test",
                source=SimpleNamespace(
                    manifest_sha256=_sha256(formal / "artifact_manifest.json")
                ),
            )

    monkeypatch.setattr(evidence, "ConcurrentRobustnessManifest", FakeManifest)
    monkeypatch.setattr(evidence, "_validate_execution_contract", lambda **_: None)
    monkeypatch.setattr(evidence, "_close_formal_cell_evidence", lambda **_: None)
    return {
        "root": root,
        "formal": formal,
        "study": study,
        "workspace": workspace,
        "old": old_candidate,
        "new": new_candidate,
        "execution": execution,
        "replay": replay,
        "closure": contracts / "presentation-closure.json",
    }


def _clone_candidate(source: Path, destination: Path, marker: str) -> None:
    shutil.copytree(source, destination)
    (destination / "report.html").write_text(f"report {marker}\n", encoding="utf-8")
    release_path = destination / "release_evidence.json"
    manifest_path = destination / "artifact_manifest.json"
    release = json.loads(release_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts = manifest["artifacts"]
    content_hashes = {
        relative: _sha256(destination / relative)
        for relative in artifacts.values()
        if relative != "release_evidence.json"
    }
    release["candidate_content_identity_sha256"] = hashlib.sha256(
        (json.dumps(content_hashes, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ).hexdigest()
    _write_json(release_path, release)
    hashes = {name: _sha256(destination / relative) for name, relative in artifacts.items()}
    manifest["sha256"] = hashes
    identity_rows = {relative: hashes[name] for name, relative in sorted(artifacts.items())}
    manifest["candidate_identity_sha256"] = hashlib.sha256(
        (json.dumps(identity_rows, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ).hexdigest()
    _write_json(manifest_path, manifest)


def _close(fixture: dict[str, Path]) -> evidence.PresentationClosureFacts:
    return evidence.close_presentation(
        repo_root=fixture["root"],
        formal_root=fixture["formal"],
        study_root=fixture["study"],
        workspace_root=fixture["workspace"],
        candidate_dir=fixture["new"],
        execution_contract_path=fixture["execution"],
        destination_path=fixture["closure"],
        implementation_commit="abcdef0",
    )


def test_close_writes_exact_contract_and_typed_facts(closure_fixture: dict[str, Path]) -> None:
    facts = _close(closure_fixture)
    document = json.loads(closure_fixture["closure"].read_text(encoding="utf-8"))
    assert set(document) == {
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
        "report_payload_schema_version",
        "semantic_set_identity_sha256",
    }
    assert document["schema_version"] == evidence.PRESENTATION_CLOSURE_V2_SCHEMA
    assert document["report_payload_schema_version"] == "concurrent-robustness-report-payload-v2"
    assert document["semantic_set_identity_sha256"] == (
        _MECHANISM_PRESENTATION.build().semantic_set_identity_sha256
    )
    assert document["provider_calls_during_closure"] == 0
    assert document["image_generation_triggered"] is False
    assert facts.new_candidate_path == closure_fixture["new"]
    assert facts.provider_calls_during_closure == 0


def test_validator_rejects_mutation_and_crossed_zero_provider_accounting(
    closure_fixture: dict[str, Path],
) -> None:
    _close(closure_fixture)
    document = json.loads(closure_fixture["closure"].read_text(encoding="utf-8"))
    document["provider_calls_during_closure"] = 1
    _write_json(closure_fixture["closure"], document)
    with pytest.raises(evidence.ConcurrentRobustnessEvidenceError, match="zero-provider"):
        evidence.validate_presentation_closure(
            repo_root=closure_fixture["root"],
            closure_path=closure_fixture["closure"],
            formal_root=closure_fixture["formal"],
            study_root=closure_fixture["study"],
            workspace_root=closure_fixture["workspace"],
            candidate_dir=closure_fixture["new"],
            execution_contract_path=closure_fixture["execution"],
        )


def test_validator_rejects_extra_fields_and_noncanonical_paths(
    closure_fixture: dict[str, Path],
) -> None:
    _close(closure_fixture)
    document = json.loads(closure_fixture["closure"].read_text(encoding="utf-8"))
    document["unexpected"] = True
    _write_json(closure_fixture["closure"], document)
    with pytest.raises(evidence.ConcurrentRobustnessEvidenceError, match="missing or unexpected"):
        evidence.validate_presentation_closure(
            repo_root=closure_fixture["root"],
            closure_path=closure_fixture["closure"],
            formal_root=closure_fixture["formal"],
            study_root=closure_fixture["study"],
            workspace_root=closure_fixture["workspace"],
            candidate_dir=closure_fixture["new"],
            execution_contract_path=closure_fixture["execution"],
        )

    document.pop("unexpected")
    document["new_candidate_directory"] = "../new-candidate"
    _write_json(closure_fixture["closure"], document)
    with pytest.raises(evidence.ConcurrentRobustnessEvidenceError, match="canonical"):
        evidence.validate_presentation_closure(
            repo_root=closure_fixture["root"],
            closure_path=closure_fixture["closure"],
            formal_root=closure_fixture["formal"],
            study_root=closure_fixture["study"],
            workspace_root=closure_fixture["workspace"],
            candidate_dir=closure_fixture["new"],
            execution_contract_path=closure_fixture["execution"],
        )


def test_payload_v1_validator_preserves_exact_pre_trace_legacy_shape(tmp_path: Path) -> None:
    payload = {
        "schema_version": "concurrent-robustness-report-payload-v1",
        "title": "legacy fixture",
        "source_lineage": {},
        "ranking_weight": {},
        "prompt_model": {},
        "row_counts": {},
        "downloads": {"sample": "sample.json"},
        "claim_boundary": {},
        "production_deploy_eligible": False,
    }

    schema, semantic_identity = evidence._validate_report_payload_contract(
        payload,
        candidate=tmp_path,
    )
    assert schema == "concurrent-robustness-report-payload-v1"
    assert semantic_identity is None

    payload.pop("row_counts")
    with pytest.raises(evidence.ConcurrentRobustnessEvidenceError, match="fields"):
        evidence._validate_report_payload_contract(payload, candidate=tmp_path)


def test_closure_dispatch_preserves_v1_and_rejects_crossed_schema_facts(
    closure_fixture: dict[str, Path],
) -> None:
    v1_candidate = closure_fixture["root"] / "second-v1-candidate"
    _clone_candidate(closure_fixture["old"], v1_candidate, "second-v1")
    v1_closure = closure_fixture["root"] / "contracts" / "presentation-closure-v1.json"
    v1_facts = evidence.close_presentation(
        repo_root=closure_fixture["root"],
        formal_root=closure_fixture["formal"],
        study_root=closure_fixture["study"],
        workspace_root=closure_fixture["workspace"],
        candidate_dir=v1_candidate,
        execution_contract_path=closure_fixture["execution"],
        destination_path=v1_closure,
        implementation_commit="abcdef0",
    )
    document = json.loads(v1_closure.read_text(encoding="utf-8"))
    assert document["schema_version"] == evidence.PRESENTATION_CLOSURE_SCHEMA
    assert "report_payload_schema_version" not in document
    assert "semantic_set_identity_sha256" not in document
    assert v1_facts.report_payload_schema_version == "concurrent-robustness-report-payload-v1"

    document["report_payload_schema_version"] = "concurrent-robustness-report-payload-v1"
    _write_json(v1_closure, document)
    with pytest.raises(evidence.ConcurrentRobustnessEvidenceError, match="missing or unexpected"):
        evidence.validate_presentation_closure(
            repo_root=closure_fixture["root"],
            closure_path=v1_closure,
            formal_root=closure_fixture["formal"],
            study_root=closure_fixture["study"],
            workspace_root=closure_fixture["workspace"],
            candidate_dir=v1_candidate,
            execution_contract_path=closure_fixture["execution"],
        )


def test_closure_v2_rereads_master_bytes_and_fails_atomically(
    closure_fixture: dict[str, Path],
) -> None:
    mechanism = _MECHANISM_PRESENTATION.build()
    target = closure_fixture["new"] / mechanism.mermaid_artifacts[0].filename
    target.write_bytes(target.read_bytes() + b"mutated")
    with pytest.raises(evidence.ConcurrentRobustnessEvidenceError, match="master|artifact hash"):
        _close(closure_fixture)
    assert not closure_fixture["closure"].exists()


@pytest.mark.parametrize("mutation", ["missing", "extra", "crossed-identity", "crossed-schema"])
def test_closure_v2_rejects_missing_extra_or_crossed_semantic_facts(
    closure_fixture: dict[str, Path],
    mutation: str,
) -> None:
    _close(closure_fixture)
    document = json.loads(closure_fixture["closure"].read_text(encoding="utf-8"))
    if mutation == "missing":
        document.pop("semantic_set_identity_sha256")
    elif mutation == "extra":
        document["unexpected"] = True
    elif mutation == "crossed-identity":
        document["semantic_set_identity_sha256"] = "0" * 64
    else:
        document["report_payload_schema_version"] = "concurrent-robustness-report-payload-v1"
    _write_json(closure_fixture["closure"], document)
    with pytest.raises(evidence.ConcurrentRobustnessEvidenceError):
        evidence.validate_presentation_closure(
            repo_root=closure_fixture["root"],
            closure_path=closure_fixture["closure"],
            formal_root=closure_fixture["formal"],
            study_root=closure_fixture["study"],
            workspace_root=closure_fixture["workspace"],
            candidate_dir=closure_fixture["new"],
            execution_contract_path=closure_fixture["execution"],
        )


def test_close_rejects_symlink_input(closure_fixture: dict[str, Path]) -> None:
    link = closure_fixture["root"] / "candidate-link"
    os.symlink(closure_fixture["new"], link, target_is_directory=True)
    with pytest.raises(evidence.ConcurrentRobustnessEvidenceError, match="non-symlink"):
        evidence.close_presentation(
            repo_root=closure_fixture["root"],
            formal_root=closure_fixture["formal"],
            study_root=closure_fixture["study"],
            workspace_root=closure_fixture["workspace"],
            candidate_dir=link,
            execution_contract_path=closure_fixture["execution"],
            destination_path=closure_fixture["closure"],
            implementation_commit="abcdef0",
        )


def test_close_is_atomic_and_does_not_overwrite(closure_fixture: dict[str, Path]) -> None:
    closure_fixture["closure"].write_bytes(b"operator-owned\n")
    with pytest.raises(evidence.ConcurrentRobustnessEvidenceError, match="already exists"):
        _close(closure_fixture)
    assert closure_fixture["closure"].read_bytes() == b"operator-owned\n"

    closure_fixture["closure"].unlink()
    closure_fixture["execution"].write_text("{}\n", encoding="utf-8")
    with pytest.raises(evidence.ConcurrentRobustnessEvidenceError):
        _close(closure_fixture)
    assert not closure_fixture["closure"].exists()


def test_production_validator_dispatches_v6_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "validate_abm_report_release.py"
    spec = importlib.util.spec_from_file_location("validate_abm_report_release_v6_test", script_path)
    assert spec is not None and spec.loader is not None
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    source = tmp_path / "release"
    source.mkdir()
    contract_path = tmp_path / "release-contract.json"
    _write_json(contract_path, {"schema_version": "abm-report-release-contract-v6"})
    expected = {
        "schema_version": "abm-report-release-contract-v6",
        "release_purpose": "concurrent_robustness_formal_research",
        "source_directory": "release",
        "sampling_method": "seed_first_research_sample_v1",
        "sampling_status": "persisted_seed_first_formal_run",
        "report_sha256": "a" * 64,
        "production_deploy_eligible": True,
    }
    calls: list[dict[str, object]] = []

    def validate_v6(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return expected

    monkeypatch.setattr(validator, "validate_concurrent_robustness_production_release", validate_v6)
    assert validator.validate_release(repo_root=tmp_path, contract_path=contract_path, source_dir=source) == expected
    assert len(calls) == 1
    assert calls[0]["source_dir"] == source
