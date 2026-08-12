from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_abm_sim import concurrent_robustness_evidence as evidence


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
) -> None:
    path.mkdir()
    (path / "report.html").write_text(f"report {marker}\n", encoding="utf-8")
    (path / "concurrent_robustness_report_payload.json").write_text(
        json.dumps(
            {
                "schema_version": "concurrent-robustness-report-payload-v1",
                "downloads": {"sample": "sample.json"},
                "production_deploy_eligible": False,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    _write_json(
        path / "release_evidence.json",
        {
            "schema_version": "concurrent-robustness-report-release-evidence-v1",
            "candidate_content_identity_sha256": "e" * 64,
            "formal_source_manifest_sha256": formal_manifest_sha256,
            "study_manifest_sha256": study_manifest_sha256,
            "study_root_identity_sha256": "d" * 64,
            "provider_calls_during_composition": 0,
            "image_generation_triggered": False,
            "production_deploy_eligible": False,
        },
    )
    (path / "sample.json").write_text(f"sample {marker}\n", encoding="utf-8")
    artifacts = {
        "report_html": "report.html",
        "report_payload_json": "concurrent_robustness_report_payload.json",
        "release_evidence_json": "release_evidence.json",
        "sample_json": "sample.json",
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
            "artifacts": artifacts,
            "sha256": hashes,
            "approved_downloads": ["sample.json"],
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
    }
    assert document["schema_version"] == evidence.PRESENTATION_CLOSURE_SCHEMA
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
