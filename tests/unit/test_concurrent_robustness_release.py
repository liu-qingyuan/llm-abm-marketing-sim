from __future__ import annotations

import hashlib
import importlib.util
import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_abm_sim import concurrent_robustness_release as release
from llm_abm_sim import concurrent_robustness_report as report
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


def _candidate(
    candidate: Path,
    *,
    formal_manifest_sha256: str,
    study_manifest_sha256: str,
    study_artifact_manifest_sha256: str,
) -> None:
    candidate.mkdir()
    _write_json(
        candidate / "release_evidence.json",
        {
            "schema_version": "concurrent-robustness-report-release-evidence-v1",
            "candidate_content_identity_sha256": "d" * 64,
            "formal_source_manifest_sha256": formal_manifest_sha256,
            "study_manifest_sha256": study_manifest_sha256,
            "study_root_identity_sha256": "c" * 64,
            "provider_calls_during_composition": 0,
            "image_generation_triggered": False,
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
        "opaque candidate presentation owned by the Report Module\n",
        encoding="utf-8",
    )
    artifact_paths = {
        "release_evidence_json": "release_evidence.json",
        "report_html": "report.html",
        "report_payload_json": "concurrent_robustness_report_payload.json",
        "sample_manifest_csv": "sample_manifest.csv",
        "sample_manifest_json": "sample_manifest.json",
        "weight_json": "ranking_weight_sensitivity.json",
    }
    artifact_hashes = {
        name: _sha256(candidate / relative_path)
        for name, relative_path in artifact_paths.items()
    }
    identity_rows = {
        relative_path: artifact_hashes[name]
        for name, relative_path in sorted(artifact_paths.items())
    }
    _write_json(
        candidate / "artifact_manifest.json",
        {
            "schema_version": "concurrent-robustness-report-candidate-manifest-v1",
            "candidate_type": "immutable_combined_robustness_report",
            "candidate_identity_sha256": hashlib.sha256(
                (
                    json.dumps(identity_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    + "\n"
                ).encode()
            ).hexdigest(),
            "formal_source": {"manifest_sha256": formal_manifest_sha256},
            "study_source": {
                "manifest_sha256": study_manifest_sha256,
                "artifact_manifest_sha256": study_artifact_manifest_sha256,
                "root_identity_sha256": "c" * 64,
            },
            "artifacts": artifact_paths,
            "sha256": artifact_hashes,
            "approved_downloads": [
                "ranking_weight_sensitivity.json",
                "release_evidence.json",
            ],
            "production_deploy_eligible": False,
        },
    )


class _FakeReportPresentation:
    def __init__(
        self,
        *,
        report_html: bytes = b"<!doctype html><html><body>report-owned production presentation</body></html>",
    ) -> None:
        self.report_html = report_html
        self.calls: list[tuple[str, object]] = []
        self.validation_error: ValueError | None = None

    def materialize_production(self, **kwargs: object) -> report._PresentationBundle:
        self.calls.append(("materialize", kwargs))
        candidate = Path(str(kwargs["candidate_dir"]))
        facts = kwargs["stage_facts"]
        assert isinstance(facts, report._ProductionPresentationFacts)
        payload = json.loads(
            (candidate / "concurrent_robustness_report_payload.json").read_text(encoding="utf-8")
        )
        payload["downloads"] = dict(facts.approved_downloads)
        payload["production_deploy_eligible"] = True
        payload["production_release"] = {
            "schema_version": facts.production_evidence_schema,
            "release_id": facts.release_id,
            "canonical_endpoint": facts.canonical_endpoint,
            "formal_logical_judgments": facts.formal_logical_judgments,
            "formal_physical_attempts": facts.formal_physical_attempts,
            "provider_transport": facts.provider_transport,
            "subscription_billed_cost_usd": facts.subscription_billed_cost_usd,
        }
        return report._PresentationBundle(
            report_payload=(
                json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            ).encode("utf-8"),
            report_html=self.report_html,
        )

    def validate_bundle(
        self,
        bundle: report._PresentationBundle,
        *,
        stage_facts: report._ProductionPresentationFacts | None = None,
    ) -> None:
        self.calls.append(("validate", (bundle, stage_facts)))
        if self.validation_error is not None:
            raise self.validation_error


def _promote_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    mutate_candidate: Callable[[Path], None] | None = None,
    presentation: _FakeReportPresentation | None = None,
) -> SimpleNamespace:
    formal = tmp_path / "formal"
    study = tmp_path / "study"
    workspace = tmp_path / "workspace"
    candidate = tmp_path / "candidate"
    for path in (formal, study, workspace):
        path.mkdir()
    _write_json(formal / "artifact_manifest.json", {"fixture": "formal"})
    _write_json(study / "study_manifest.json", {"fixture": True})
    _write_json(study / "artifact_manifest.json", {"root_identity_sha256": "c" * 64})
    _candidate(
        candidate,
        formal_manifest_sha256=_sha256(formal / "artifact_manifest.json"),
        study_manifest_sha256=_sha256(study / "study_manifest.json"),
        study_artifact_manifest_sha256=_sha256(study / "artifact_manifest.json"),
    )
    if mutate_candidate is not None:
        mutate_candidate(candidate)
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
    fake_manifest.source.manifest_sha256 = _sha256(formal / "artifact_manifest.json")

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
    monkeypatch.setattr(release, "_validate_execution_contract", lambda **_kwargs: execution_document)
    report_presentation = presentation or _FakeReportPresentation()
    monkeypatch.setattr(release, "_REPORT_PRESENTATION", report_presentation)
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
    return SimpleNamespace(
        promoted=promoted,
        candidate=candidate,
        formal=formal,
        study=study,
        workspace=workspace,
        execution_contract=execution_contract,
        report_presentation=report_presentation,
        candidate_before=candidate_before,
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


def test_promotion_delegates_opaque_presentation_to_report_module(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opaque_html = b"<!doctype html><html><body>opaque Report presentation</body></html>"
    presentation = _FakeReportPresentation(report_html=opaque_html)

    fixture = _promote_fixture(tmp_path, monkeypatch, presentation=presentation)

    assert (fixture.promoted.source_dir / "report.html").read_bytes() == opaque_html
    assert presentation.calls[0][0] == "materialize"
    assert any(kind == "validate" for kind, _payload in presentation.calls)


def test_formal_candidate_promotes_without_mutating_validation_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _promote_fixture(tmp_path, monkeypatch)
    candidate = fixture.candidate
    candidate_before = fixture.candidate_before
    promoted = fixture.promoted

    assert candidate_before == {
        path.relative_to(candidate): path.read_bytes()
        for path in candidate.rglob("*")
        if path.is_file()
    }
    assert promoted.source_dir.is_dir()
    assert promoted.contract_path.is_file()
    assert (promoted.source_dir / "report.html").read_bytes() == (
        fixture.report_presentation.report_html
    )
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
    ("mutation", "error"),
    [
        ("crossed-lineage", "lineage"),
        ("inventory-mismatch", "inventory"),
        ("hash-mutation", "hash"),
    ],
)
def test_release_rejects_candidate_closure_before_report_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    error: str,
) -> None:
    presentation = _FakeReportPresentation()

    def mutate(candidate: Path) -> None:
        manifest_path = candidate / "artifact_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if mutation == "crossed-lineage":
            manifest["formal_source"]["manifest_sha256"] = "b" * 64
            _write_json(manifest_path, manifest)
        elif mutation == "inventory-mismatch":
            manifest["artifacts"].pop("weight_json")
            manifest["sha256"].pop("weight_json")
            _write_json(manifest_path, manifest)
        else:
            with (candidate / "ranking_weight_sensitivity.json").open("a", encoding="utf-8") as stream:
                stream.write("mutated")

    with pytest.raises(release.ConcurrentRobustnessReleaseError, match=error):
        _promote_fixture(
            tmp_path,
            monkeypatch,
            mutate_candidate=mutate,
            presentation=presentation,
        )

    assert presentation.calls == []
    assert not (tmp_path / "production-release").exists()
    assert not (tmp_path / "release-contract.json").exists()


def test_promotion_fails_closed_when_report_rejects_candidate_presentation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RejectingReportPresentation(_FakeReportPresentation):
        def materialize_production(self, **kwargs: object) -> report._PresentationBundle:
            raise report._RobustnessReportClosureError("candidate presentation is invalid")

    with pytest.raises(
        release.ConcurrentRobustnessReleaseError,
        match="Report production presentation failed closure",
    ):
        _promote_fixture(
            tmp_path,
            monkeypatch,
            presentation=RejectingReportPresentation(),
        )

    assert not (tmp_path / "production-release").exists()
    assert not (tmp_path / "release-contract.json").exists()
    assert not list(tmp_path.glob(".production-release.*.staging"))


def test_promotion_cleans_staging_when_report_rejects_production_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    presentation = _FakeReportPresentation()
    presentation.validation_error = report._RobustnessReportClosureError(
        "production presentation is invalid"
    )

    with pytest.raises(
        release.ConcurrentRobustnessReleaseError,
        match="Report production presentation failed validation",
    ):
        _promote_fixture(tmp_path, monkeypatch, presentation=presentation)

    assert not (tmp_path / "production-release").exists()
    assert not (tmp_path / "release-contract.json").exists()
    assert not list(tmp_path.glob(".production-release.*.staging"))


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


def test_production_validator_delegates_presentation_bundle_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _promote_fixture(tmp_path, monkeypatch)
    fixture.report_presentation.validation_error = report._RobustnessReportClosureError(
        "production DOM contract is crossed"
    )
    contract = json.loads(fixture.promoted.contract_path.read_text(encoding="utf-8"))

    with pytest.raises(
        release.ConcurrentRobustnessReleaseError,
        match="Report production presentation failed validation",
    ):
        release.validate_concurrent_robustness_production_release(
            repo_root=tmp_path,
            contract_document=contract,
            source_dir=fixture.promoted.source_dir,
        )


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ("payload-crossed", "payload and manifest"),
        ("manifest-crossed", "payload and manifest"),
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
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    if mutation == "payload-crossed":
        payload["downloads"]["weight"] = "sample_manifest.json"
    elif mutation == "manifest-crossed":
        manifest["approved_downloads"]["weight"] = "sample_manifest.json"
    elif mutation == "path-escape":
        payload["downloads"]["weight"] = "../outside.json"
        manifest["approved_downloads"]["weight"] = "../outside.json"
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
    promoted = _promote_fixture(tmp_path, monkeypatch).promoted
    with (promoted.source_dir / "report.html").open("a", encoding="utf-8") as stream:
        stream.write("mutated")

    with pytest.raises(release.ConcurrentRobustnessReleaseError, match="hash"):
        release.validate_concurrent_robustness_production_release(
            repo_root=tmp_path,
            contract_document=json.loads(promoted.contract_path.read_text(encoding="utf-8")),
            source_dir=promoted.source_dir,
        )
