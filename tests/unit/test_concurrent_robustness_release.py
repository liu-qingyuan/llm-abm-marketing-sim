from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_abm_sim import concurrent_robustness_release as release
from llm_abm_sim.providers.pi_subscription import PI_SUBSCRIPTION_MODEL_ALIASES


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _fake_manifest(formal: Path) -> SimpleNamespace:
    cells = [
        SimpleNamespace(requested_model=requested, required_observed_model=observed)
        for requested, observed in PI_SUBSCRIPTION_MODEL_ALIASES.items()
        for _prompt in range(4)
    ]
    return SimpleNamespace(
        output_identity="robustness-formal-test",
        source=SimpleNamespace(source_dir=str(formal), manifest_sha256="a" * 64),
        prompt_model_cells=cells,
        request_caps=SimpleNamespace(
            logical_judgment_cap=28_800,
            physical_attempt_cap=86_400,
            fee_ceiling_usd=0.0,
        ),
        dynamic_execution=SimpleNamespace(
            profile="formal_live",
            adapter_identity="openai-codex-subscription-client-v1",
            authorization=SimpleNamespace(
                production_deploy_eligible=False,
                external_requests_allowed=True,
            ),
        ),
    )


class _FakeCellEvidenceModel:
    @staticmethod
    def model_validate(_payload: object) -> SimpleNamespace:
        return SimpleNamespace(
            evidence_profile="formal_live",
            cell_count=16,
            logical_judgment_count=28_800,
            physical_attempt_count=28_800,
            external_request_invocations=28_800,
            live_api_triggered=True,
            production_deploy_eligible=False,
        )


def _candidate(candidate: Path) -> None:
    candidate.mkdir()
    _write_json(
        candidate / "artifact_manifest.json",
        {
            "schema_version": "concurrent-robustness-report-candidate-manifest-v1",
            "candidate_type": "immutable_combined_robustness_report",
            "candidate_identity_sha256": "b" * 64,
            "formal_source": {"manifest_sha256": "a" * 64},
            "study_source": {"root_identity_sha256": "c" * 64},
            "production_deploy_eligible": False,
        },
    )
    _write_json(
        candidate / "release_evidence.json",
        {
            "schema_version": "concurrent-robustness-report-release-evidence-v1",
            "candidate_content_identity_sha256": "d" * 64,
            "production_deploy_eligible": False,
        },
    )
    _write_json(
        candidate / "concurrent_robustness_report_payload.json",
        {
            "schema_version": "concurrent-robustness-report-payload-v1",
            "downloads": {"weight": "ranking_weight_sensitivity.json"},
            "production_deploy_eligible": False,
        },
    )
    (candidate / "ranking_weight_sensitivity.json").write_text("{}\n", encoding="utf-8")
    (candidate / "report.html").write_text(
        """<!doctype html><html><head><title>test</title></head><body>
<div data-testid="mechanism-overview-section"></div>
<div data-testid="run-evidence-mode-panel"></div>
<div data-testid="run-trace-lineage-data"></div>
<section data-testid="robustness-report-candidate">
<code data-testid="robustness-production-eligibility">production_deploy_eligible=false</code>
<div data-testid="robustness-source-lineage"></div>
<div data-testid="ranking-weight-sensitivity-section"></div>
<div data-testid="prompt-model-robustness-section"></div>
<p>Demographic Shadow evidence remains bound to the historical Formal source</p>
<p>values in this candidate</p>
</section></body></html>""",
        encoding="utf-8",
    )


def test_formal_candidate_promotes_without_mutating_validation_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    formal = tmp_path / "formal"
    study = tmp_path / "study"
    workspace = tmp_path / "workspace"
    candidate = tmp_path / "candidate"
    for path in (formal, study, workspace):
        path.mkdir()
    _candidate(candidate)
    _write_json(study / "study_manifest.json", {"fixture": True})
    _write_json(study / "artifact_manifest.json", {"root_identity_sha256": "c" * 64})
    _write_json(
        study / "prompt_model_cell_evidence.json",
        {
            "schema_version": "concurrent-robustness-cell-evidence-v1",
            "evidence_profile": "formal_live",
            "cell_count": 16,
            "logical_judgment_count": 28_800,
            "physical_attempt_count": 28_800,
            "external_request_invocations": 28_800,
            "live_api_triggered": True,
            "production_deploy_eligible": False,
        },
    )
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    execution_contract = contracts / "formal-run-contract.json"
    _write_json(execution_contract, {"fixture": True})
    fake_manifest = _fake_manifest(formal)

    class FakeManifestModel:
        @staticmethod
        def model_validate(_payload: object) -> SimpleNamespace:
            return fake_manifest

        @staticmethod
        def model_validate_json(_payload: bytes) -> SimpleNamespace:
            return fake_manifest

    execution_document = {
        "implementation_commit": "1234567",
        "physical_provider_attempts": 28_800,
        "subscription_nominal_reference_cost_usd": 1.25,
        "subscription_billed_cost_usd": 0.0,
    }
    monkeypatch.setattr(release, "ConcurrentRobustnessManifest", FakeManifestModel)
    monkeypatch.setattr(release, "_CellEvidenceDocument", _FakeCellEvidenceModel)
    monkeypatch.setattr(release, "_validate_cell_evidence_contract", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(release, "_validate_completed_dynamic_root", lambda **_kwargs: None)
    monkeypatch.setattr(release, "_validate_concurrent_robustness_report_candidate", lambda **_kwargs: candidate)
    monkeypatch.setattr(release, "_validate_execution_contract", lambda **_kwargs: execution_document)

    promoted = release.promote_concurrent_robustness_release(
        repo_root=tmp_path,
        formal_root=formal,
        study_root=study,
        workspace_root=workspace,
        candidate_dir=candidate,
        execution_contract_path=execution_contract,
        destination_dir=tmp_path / "production-release",
        release_contract_path=tmp_path / "release-contract.json",
        release_id="robustness-release-test",
    )

    assert promoted.source_dir.is_dir()
    assert promoted.contract_path.is_file()
    production_html = (promoted.source_dir / "report.html").read_text(encoding="utf-8")
    assert "production_deploy_eligible=true" in production_html
    assert "production_deploy_eligible=false" not in production_html
    preserved_manifest = json.loads(
        (promoted.source_dir / "validation_candidate_artifact_manifest.json").read_text(encoding="utf-8")
    )
    preserved_evidence = json.loads(
        (promoted.source_dir / "validation_candidate_release_evidence.json").read_text(encoding="utf-8")
    )
    assert preserved_manifest["production_deploy_eligible"] is False
    assert preserved_evidence["production_deploy_eligible"] is False

    contract = json.loads(promoted.contract_path.read_text(encoding="utf-8"))
    validated = release.validate_concurrent_robustness_production_release(
        repo_root=tmp_path,
        contract_document=contract,
        source_dir=promoted.source_dir,
    )
    assert validated["production_deploy_eligible"] is True
    assert validated["logical_judgments"] == 28_800


def test_release_validator_routes_v5_contract_through_strong_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validator_path = Path(__file__).resolve().parents[2] / "scripts" / "validate_abm_report_release.py"
    spec = importlib.util.spec_from_file_location("validate_abm_report_release_v5_test", validator_path)
    assert spec is not None and spec.loader is not None
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    source = tmp_path / "release"
    source.mkdir()
    contract = tmp_path / "release-contract.json"
    _write_json(contract, {"schema_version": "abm-report-release-contract-v5"})
    expected = {
        "schema_version": "abm-report-release-contract-v5",
        "release_purpose": "concurrent_robustness_formal_research",
        "source_directory": "release",
        "sampling_method": "seed_first_research_sample_v1",
        "sampling_status": "persisted_seed_first_formal_run",
        "decision_execution_mode": "live_provider",
        "report_sha256": "a" * 64,
        "production_deploy_eligible": True,
    }
    calls: list[dict[str, object]] = []

    def validate_v5(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return expected

    monkeypatch.setattr(validator, "validate_concurrent_robustness_production_release", validate_v5)

    assert validator.validate_release(
        repo_root=tmp_path,
        contract_path=contract,
        source_dir=source,
    ) == expected
    assert len(calls) == 1
    assert calls[0]["source_dir"] == source


def test_production_release_rejects_post_close_report_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    formal = tmp_path / "formal"
    study = tmp_path / "study"
    workspace = tmp_path / "workspace"
    candidate = tmp_path / "candidate"
    for path in (formal, study, workspace):
        path.mkdir()
    _candidate(candidate)
    _write_json(study / "study_manifest.json", {})
    _write_json(study / "artifact_manifest.json", {"root_identity_sha256": "c" * 64})
    _write_json(
        study / "prompt_model_cell_evidence.json",
        {
            "schema_version": "concurrent-robustness-cell-evidence-v1",
            "evidence_profile": "formal_live",
            "cell_count": 16,
            "logical_judgment_count": 28_800,
            "physical_attempt_count": 28_800,
            "external_request_invocations": 28_800,
            "live_api_triggered": True,
            "production_deploy_eligible": False,
        },
    )
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    execution_contract = contracts / "formal-run-contract.json"
    _write_json(execution_contract, {})
    fake_manifest = _fake_manifest(formal)

    class FakeManifestModel:
        @staticmethod
        def model_validate(_payload: object) -> SimpleNamespace:
            return fake_manifest

    monkeypatch.setattr(release, "ConcurrentRobustnessManifest", FakeManifestModel)
    monkeypatch.setattr(release, "_CellEvidenceDocument", _FakeCellEvidenceModel)
    monkeypatch.setattr(release, "_validate_cell_evidence_contract", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(release, "_validate_completed_dynamic_root", lambda **_kwargs: None)
    monkeypatch.setattr(release, "_validate_concurrent_robustness_report_candidate", lambda **_kwargs: candidate)
    monkeypatch.setattr(
        release,
        "_validate_execution_contract",
        lambda **_kwargs: {
            "implementation_commit": "1234567",
            "physical_provider_attempts": 28_800,
            "subscription_nominal_reference_cost_usd": 1.25,
        },
    )
    promoted = release.promote_concurrent_robustness_release(
        repo_root=tmp_path,
        formal_root=formal,
        study_root=study,
        workspace_root=workspace,
        candidate_dir=candidate,
        execution_contract_path=execution_contract,
        destination_dir=tmp_path / "production-release",
        release_contract_path=tmp_path / "release-contract.json",
        release_id="robustness-release-test",
    )
    with (promoted.source_dir / "report.html").open("a", encoding="utf-8") as stream:
        stream.write("mutated")

    with pytest.raises(release.ConcurrentRobustnessReleaseError, match="hash"):
        release.validate_concurrent_robustness_production_release(
            repo_root=tmp_path,
            contract_document=json.loads(promoted.contract_path.read_text(encoding="utf-8")),
            source_dir=promoted.source_dir,
        )
