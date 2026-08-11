from __future__ import annotations

import hashlib
import importlib.util
import json
from collections.abc import Callable
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
            "downloads": {
                "weight": "ranking_weight_sensitivity.json",
                "release_evidence": "release_evidence.json",
            },
            "production_deploy_eligible": False,
        },
    )
    (candidate / "ranking_weight_sensitivity.json").write_text("{}\n", encoding="utf-8")
    (candidate / "sample_manifest.json").write_text("{}\n", encoding="utf-8")
    (candidate / "sample_manifest.csv").write_text("user_id\nu1\n", encoding="utf-8")
    (candidate / "report.html").write_text(
        """<!doctype html><html><head><title>test</title></head><body>
<div data-testid="mechanism-overview-section"></div>
<div data-testid="run-evidence-mode-panel"></div>
<div data-testid="run-trace-lineage-data"></div>
<section data-testid="robustness-report-candidate">
<code data-testid="robustness-production-eligibility">production_deploy_eligible=false</code>
<div data-testid="robustness-source-lineage"></div>
<section data-testid="ranking-weight-sensitivity-section">
<select data-testid="ranking-weight-family-select" data-weight-family-select>
<option value="network-feedback">network-feedback</option>
<option value="network-fit">network-fit</option>
<option value="feedback-fit">feedback-fit</option>
</select>
<div data-weight-family="network-feedback"></div>
<div data-weight-family="network-fit" hidden></div>
<div data-weight-family="feedback-fit" hidden></div>
</section>
<section data-testid="prompt-model-robustness-section">
<select data-testid="prompt-model-message-select" data-prompt-message-select>
<option value="message_1">message_1</option><option value="message_2">message_2</option><option value="message_3">message_3</option>
</select>
<select data-testid="prompt-model-metric-select" data-prompt-metric-select>
<option value="engagement">engagement</option><option value="audience">audience</option>
</select>
<div data-prompt-view="message_1|engagement"></div>
<div data-prompt-view="message_1|audience" hidden></div>
<div data-prompt-view="message_2|engagement" hidden></div>
<div data-prompt-view="message_2|audience" hidden></div>
<div data-prompt-view="message_3|engagement" hidden></div>
<div data-prompt-view="message_3|audience" hidden></div>
<table data-testid="shared-seed-exact-table"><tbody>
<tr data-row-message-id="message_1"><td>message_1</td></tr>
<tr data-row-message-id="message_2" hidden><td>message_2</td></tr>
<tr data-row-message-id="message_3" hidden><td>message_3</td></tr>
</tbody></table>
</section>
<section data-testid="robustness-downloads-section">
<a data-testid="robustness-download-weight" href="ranking_weight_sensitivity.json">weight</a>
<a data-testid="robustness-download-release_evidence" href="release_evidence.json">release evidence</a>
</section>
<p>Demographic Shadow evidence remains bound to the historical Formal source</p>
<p>values in this candidate</p>
</section>
<script>
(() => {
  const report = document.querySelector('[data-testid="robustness-report-candidate"]');
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
</script></body></html>""",
        encoding="utf-8",
    )


def _promote_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    mutate_candidate: Callable[[Path], None] | None = None,
) -> SimpleNamespace:
    formal = tmp_path / "formal"
    study = tmp_path / "study"
    workspace = tmp_path / "workspace"
    candidate = tmp_path / "candidate"
    for path in (formal, study, workspace):
        path.mkdir()
    _candidate(candidate)
    if mutate_candidate is not None:
        mutate_candidate(candidate)
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
        "closure_implementation_commit": "7654321",
        "closure_replay_sha256": "e" * 64,
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
    return SimpleNamespace(
        promoted=promoted,
        candidate=candidate,
        formal=formal,
        study=study,
        workspace=workspace,
        execution_contract=execution_contract,
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reclose_tampered_release(source: Path, contract_path: Path) -> dict[str, object]:
    manifest_path = source / "artifact_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifact_paths = manifest["artifacts"]
    manifest["sha256"] = {
        name: _sha256(source / relative_path)
        for name, relative_path in artifact_paths.items()
    }
    identity_rows = {
        relative_path: manifest["sha256"][name]
        for name, relative_path in sorted(artifact_paths.items())
    }
    manifest["release_identity_sha256"] = hashlib.sha256(
        (json.dumps(identity_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ).hexdigest()
    _write_json(manifest_path, manifest)

    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["artifact_sha256"] = {
        path.relative_to(source).as_posix(): _sha256(path)
        for path in sorted(source.rglob("*"))
        if path.is_file()
    }
    _write_json(contract_path, contract)
    return contract


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
        "closure_implementation_commit": "7654321",
        "closure_replay_sha256": "e" * 64,
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

    candidate_before = {
        path.relative_to(candidate): path.read_bytes()
        for path in candidate.rglob("*")
        if path.is_file()
    }
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

    assert candidate_before == {
        path.relative_to(candidate): path.read_bytes()
        for path in candidate.rglob("*")
        if path.is_file()
    }
    assert promoted.source_dir.is_dir()
    assert promoted.contract_path.is_file()
    production_html = (promoted.source_dir / "report.html").read_text(encoding="utf-8")
    assert "production_deploy_eligible=true" in production_html
    assert "production_deploy_eligible=false" not in production_html
    assert production_html.count('data-testid="robustness-report-release"') == 2
    assert 'data-testid="robustness-report-candidate"' not in production_html
    assert production_html.count(
        'document.querySelector(\'[data-testid="robustness-report-release"]\')'
    ) == 1
    assert 'document.querySelector(\'[data-testid="robustness-report-candidate"]\')' not in production_html
    assert 'href="robustness_production_release_evidence.json"' in production_html
    assert 'href="release_evidence.json"' not in production_html
    production_payload = json.loads(
        (promoted.source_dir / "concurrent_robustness_report_payload.json").read_text(encoding="utf-8")
    )
    assert production_payload["downloads"]["release_evidence"] == (
        "robustness_production_release_evidence.json"
    )
    preserved_manifest = json.loads(
        (promoted.source_dir / "validation_candidate_artifact_manifest.json").read_text(encoding="utf-8")
    )
    preserved_evidence = json.loads(
        (promoted.source_dir / "validation_candidate_release_evidence.json").read_text(encoding="utf-8")
    )
    assert preserved_manifest["production_deploy_eligible"] is False
    assert preserved_evidence["production_deploy_eligible"] is False
    production_manifest = json.loads(
        (promoted.source_dir / "artifact_manifest.json").read_text(encoding="utf-8")
    )
    assert production_manifest["artifacts"]["sample_manifest_json"] == "sample_manifest.json"
    assert production_manifest["artifacts"]["sample_manifest_csv"] == "sample_manifest.csv"
    assert production_manifest["approved_downloads"] == production_payload["downloads"]
    assert production_manifest["approved_downloads"]["release_evidence"] == (
        "robustness_production_release_evidence.json"
    )
    assert "robustness_production_release_evidence.json" in production_manifest["artifacts"].values()
    assert "validation_candidate_release_evidence.json" in production_manifest["artifacts"].values()
    assert "validation_candidate_release_evidence.json" not in production_manifest["approved_downloads"].values()

    contract = json.loads(promoted.contract_path.read_text(encoding="utf-8"))
    validated = release.validate_concurrent_robustness_production_release(
        repo_root=tmp_path,
        contract_document=contract,
        source_dir=promoted.source_dir,
    )
    assert validated["production_deploy_eligible"] is True
    assert validated["logical_judgments"] == 28_800


@pytest.mark.parametrize(
    "mutation",
    ["missing-root", "ambiguous-root", "missing-selector", "ambiguous-selector", "preexisting-release-id"],
)
def test_promotion_rejects_missing_or_ambiguous_stage_markers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    def mutate(candidate: Path) -> None:
        html_path = candidate / "report.html"
        html = html_path.read_text(encoding="utf-8")
        candidate_root = 'data-testid="robustness-report-candidate"'
        candidate_selector = "document.querySelector('[data-testid=\"robustness-report-candidate\"]')"
        if mutation == "missing-root":
            html = html.replace(candidate_root, 'data-testid="missing-robustness-root"', 1)
        elif mutation == "ambiguous-root":
            html = html.replace("</body>", f"<div {candidate_root}></div></body>")
        elif mutation == "missing-selector":
            html = html.replace(candidate_selector, "document.querySelector('[data-testid=\"missing\"]')")
        elif mutation == "ambiguous-selector":
            html = html.replace("</script>", f"\n// {candidate_selector}\n</script>")
        else:
            html = html.replace("<section data-testid=", '<section data-release-id="legacy" data-testid=', 1)
        html_path.write_text(html, encoding="utf-8")

    with pytest.raises(release.ConcurrentRobustnessReleaseError, match="missing|ambiguous|transformed"):
        _promote_fixture(tmp_path, monkeypatch, mutate_candidate=mutate)


def test_production_validator_rejects_validation_candidate_evidence_as_approved_download(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _promote_fixture(tmp_path, monkeypatch)
    source = fixture.promoted.source_dir
    payload_path = source / "concurrent_robustness_report_payload.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    payload["downloads"]["release_evidence"] = "validation_candidate_release_evidence.json"
    _write_json(payload_path, payload)

    html_path = source / "report.html"
    html_path.write_text(
        html_path.read_text(encoding="utf-8").replace(
            'href="robustness_production_release_evidence.json"',
            'href="validation_candidate_release_evidence.json"',
        ),
        encoding="utf-8",
    )
    manifest_path = source / "artifact_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["approved_downloads"]["release_evidence"] = "validation_candidate_release_evidence.json"
    _write_json(manifest_path, manifest)
    contract = _reclose_tampered_release(source, fixture.promoted.contract_path)

    with pytest.raises(release.ConcurrentRobustnessReleaseError, match="release-evidence"):
        release.validate_concurrent_robustness_production_release(
            repo_root=tmp_path,
            contract_document=contract,
            source_dir=source,
        )


def test_production_validator_rejects_crossed_bootstrap_stage_selector(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _promote_fixture(tmp_path, monkeypatch)
    source = fixture.promoted.source_dir
    html_path = source / "report.html"
    html_path.write_text(
        html_path.read_text(encoding="utf-8").replace(
            "document.querySelector('[data-testid=\"robustness-report-release\"]')",
            "document.querySelector('[data-testid=\"robustness-report-candidate\"]')",
        ),
        encoding="utf-8",
    )
    contract = _reclose_tampered_release(source, fixture.promoted.contract_path)

    with pytest.raises(release.ConcurrentRobustnessReleaseError, match="bootstrap|stage"):
        release.validate_concurrent_robustness_production_release(
            repo_root=tmp_path,
            contract_document=contract,
            source_dir=source,
        )


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ("payload-crossed", "payload and manifest"),
        ("manifest-crossed", "payload and manifest"),
        ("html-crossed", "HTML and approved"),
        ("path-escape", "escapes|inventory"),
        ("missing-file", "missing|inventory"),
    ],
)
def test_production_validator_rejects_crossed_or_unsafe_download_closure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    error: str,
) -> None:
    fixture = _promote_fixture(tmp_path, monkeypatch)
    source = fixture.promoted.source_dir
    payload_path = source / "concurrent_robustness_report_payload.json"
    manifest_path = source / "artifact_manifest.json"
    html_path = source / "report.html"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    html = html_path.read_text(encoding="utf-8")

    if mutation == "payload-crossed":
        payload["downloads"]["weight"] = "sample_manifest.json"
    elif mutation == "manifest-crossed":
        manifest["approved_downloads"]["weight"] = "sample_manifest.json"
    elif mutation == "html-crossed":
        html = html.replace('href="ranking_weight_sensitivity.json"', 'href="sample_manifest.json"')
    elif mutation == "path-escape":
        payload["downloads"]["weight"] = "../outside.json"
        manifest["approved_downloads"]["weight"] = "../outside.json"
        html = html.replace('href="ranking_weight_sensitivity.json"', 'href="../outside.json"')
    else:
        (source / "ranking_weight_sensitivity.json").unlink()
        logical_name = next(
            name
            for name, relative_path in manifest["artifacts"].items()
            if relative_path == "ranking_weight_sensitivity.json"
        )
        manifest["artifacts"].pop(logical_name)
        manifest["sha256"].pop(logical_name)

    _write_json(payload_path, payload)
    _write_json(manifest_path, manifest)
    html_path.write_text(html, encoding="utf-8")
    contract = _reclose_tampered_release(source, fixture.promoted.contract_path)

    with pytest.raises(release.ConcurrentRobustnessReleaseError, match=error):
        release.validate_concurrent_robustness_production_release(
            repo_root=tmp_path,
            contract_document=contract,
            source_dir=source,
        )


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
            "closure_implementation_commit": "7654321",
            "closure_replay_sha256": "e" * 64,
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
