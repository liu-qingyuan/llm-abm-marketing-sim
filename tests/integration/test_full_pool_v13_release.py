from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from llm_abm_sim import concurrent_robustness_release as release_module
from llm_abm_sim import concurrent_robustness_report as report_module
from tests.integration.test_full_pool_presentation_bundle import (
    _formal_realized_full_pool_source,
    _historical_candidate,
    _realized_full_pool_source,
)
from tests.unit.test_robustness_deploy_contract import _load_validator


def _protected_v12_fixture(
    root: Path,
    *,
    historical_formal: Path,
    historical_study: Path,
    upstream_source: Mapping[str, object],
) -> tuple[Path, Path]:
    release = root / "protected-v12-release"
    release.mkdir(parents=True)
    (release / "report.html").write_text("protected v12\n", encoding="utf-8")
    contract = root / "protected-v12-contract.json"
    contract.write_text(
        json.dumps(
            {
                "schema_version": "abm-report-release-contract-v12",
                "release_id": "protected-v12",
                "source_directory": release.relative_to(root).as_posix(),
                "full_pool_source_directory": Path(
                    cast(str, upstream_source["source_root"])
                ).relative_to(root).as_posix(),
                "full_pool_source_identity": upstream_source["source_identity"],
                "full_pool_source_manifest_sha256": upstream_source["manifest_sha256"],
                "full_pool_source_hash": upstream_source["source_hash"],
                "historical_formal_directory": historical_formal.relative_to(root).as_posix(),
                "historical_study_directory": historical_study.relative_to(root).as_posix(),
                "production_deploy_eligible": True,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return release, contract


def _snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _install_formal_upstream_reader(
    realized_source: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from llm_abm_sim.full_pool_source_v4 import read_closed_strict_full_pool_source

    manifest = json.loads((realized_source / "manifest.json").read_text(encoding="utf-8"))
    upstream_ref = manifest["upstream_source"]
    upstream = Path(upstream_ref["source_root"])
    closed = read_closed_strict_full_pool_source(
        upstream,
        manifest_sha256=upstream_ref["manifest_sha256"],
    )
    provider_accounting = dict(
        cast(Mapping[str, object], closed.manifest["provider_accounting"])
    )
    provider_accounting["external_request_invocations"] = closed.facts.logical_pairs
    formal_closed = replace(
        closed,
        manifest={**closed.manifest, "provider_accounting": provider_accounting},
        facts=replace(
            closed.facts,
            profile="production",
            external_request_invocations=closed.facts.logical_pairs,
            production_topology=True,
            production_deploy_eligible=True,
        ),
        aggregates={
            **closed.aggregates,
            "evidence_profile": "formal_live",
            "production_deploy_eligible": True,
        },
    )
    monkeypatch.setattr(
        release_module,
        "read_closed_strict_full_pool_source",
        lambda *_args, **_kwargs: formal_closed,
    )


def _promoted_v13_fixture(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    source, manifest_sha256 = _formal_realized_full_pool_source(
        root / "formal-realized",
        monkeypatch,
    )
    _install_formal_upstream_reader(source, monkeypatch)
    source_manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    historical_formal, historical_study, historical_candidate = _historical_candidate(
        root / "formal-history"
    )
    candidate = report_module._REPORT_PRESENTATION.compose_full_pool_presentation_bundle(
        full_pool_source_root=source,
        full_pool_manifest_sha256=manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        historical_candidate_dir=historical_candidate,
        destination_dir=root / "formal-candidate",
    )
    protected_v12, protected_v12_contract = _protected_v12_fixture(
        root,
        historical_formal=historical_formal,
        historical_study=historical_study,
        upstream_source=cast(
            Mapping[str, object],
            source_manifest["upstream_source"],
        ),
    )
    protected_v12_report_sha256 = hashlib.sha256(
        (protected_v12 / "report.html").read_bytes()
    ).hexdigest()
    monkeypatch.setattr(
        release_module,
        "_validate_full_pool_v12_production_release",
        lambda **_kwargs: {
            "schema_version": "abm-report-release-contract-v12",
            "release_id": "protected-v12",
            "report_sha256": protected_v12_report_sha256,
            "production_deploy_eligible": True,
        },
    )
    destination = root / "production-v13"
    contract_path = root / "production-v13-contract.json"
    promoted = release_module.promote_concurrent_robustness_release(
        repo_root=root,
        formal_root=historical_formal,
        study_root=historical_study,
        candidate_dir=candidate,
        destination_dir=destination,
        release_contract_path=contract_path,
        release_id="formal-two-stage-v13",
        full_pool_source_root=source,
        full_pool_manifest_sha256=manifest_sha256,
        full_pool_source_identity=source_manifest["source_identity"],
        protected_v12_release_root=protected_v12,
        protected_v12_contract_path=protected_v12_contract,
        implementation_commit="a" * 40,
    )
    return {
        "source": source,
        "source_manifest": source_manifest,
        "manifest_sha256": manifest_sha256,
        "historical_formal": historical_formal,
        "historical_study": historical_study,
        "candidate": candidate,
        "protected_v12": protected_v12,
        "protected_v12_contract": protected_v12_contract,
        "destination": destination,
        "contract_path": contract_path,
        "promoted": promoted,
    }


def test_v13_promotion_rejects_the_nonproduction_validation_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, manifest_sha256 = _realized_full_pool_source(tmp_path / "validation-realized")
    source_manifest = json.loads(
        (source / "manifest.json").read_text(encoding="utf-8")
    )
    source_identity = source_manifest["source_identity"]
    historical_formal, historical_study, historical_candidate = _historical_candidate(
        tmp_path / "history"
    )
    candidate = report_module._REPORT_PRESENTATION.compose_full_pool_presentation_bundle(
        full_pool_source_root=source,
        full_pool_manifest_sha256=manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        historical_candidate_dir=historical_candidate,
        destination_dir=tmp_path / "validation-candidate",
    )
    protected_v12, protected_v12_contract = _protected_v12_fixture(
        tmp_path,
        historical_formal=historical_formal,
        historical_study=historical_study,
        upstream_source=cast(
            Mapping[str, object],
            source_manifest["upstream_source"],
        ),
    )
    monkeypatch.setattr(
        release_module,
        "_validate_full_pool_v12_production_release",
        lambda **_kwargs: {
            "schema_version": "abm-report-release-contract-v12",
            "release_id": "protected-v12",
            "report_sha256": "0" * 64,
            "production_deploy_eligible": True,
        },
    )

    with pytest.raises(
        release_module.ConcurrentRobustnessReleaseError,
        match="v13|formal|production|validation",
    ):
        release_module.promote_concurrent_robustness_release(
            repo_root=tmp_path,
            formal_root=historical_formal,
            study_root=historical_study,
            candidate_dir=candidate,
            destination_dir=tmp_path / "forbidden-v13-release",
            release_contract_path=tmp_path / "forbidden-v13-contract.json",
            release_id="forbidden-validation-v13",
            full_pool_source_root=source,
            full_pool_manifest_sha256=manifest_sha256,
            full_pool_source_identity=source_identity,
            protected_v12_release_root=protected_v12,
            protected_v12_contract_path=protected_v12_contract,
            implementation_commit="a" * 40,
        )

    assert not (tmp_path / "forbidden-v13-release").exists()
    assert not (tmp_path / "forbidden-v13-contract.json").exists()


def test_v13_materializes_and_round_trips_only_persisted_formal_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, manifest_sha256 = _formal_realized_full_pool_source(
        tmp_path / "formal-realized",
        monkeypatch,
    )
    _install_formal_upstream_reader(source, monkeypatch)
    source_manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    source_identity = source_manifest["source_identity"]
    historical_formal, historical_study, historical_candidate = _historical_candidate(
        tmp_path / "formal-history"
    )
    candidate = report_module._REPORT_PRESENTATION.compose_full_pool_presentation_bundle(
        full_pool_source_root=source,
        full_pool_manifest_sha256=manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        historical_candidate_dir=historical_candidate,
        destination_dir=tmp_path / "formal-candidate",
    )
    protected_v12, protected_v12_contract = _protected_v12_fixture(
        tmp_path,
        historical_formal=historical_formal,
        historical_study=historical_study,
        upstream_source=cast(
            Mapping[str, object],
            source_manifest["upstream_source"],
        ),
    )
    protected_v12_report_sha256 = hashlib.sha256(
        (protected_v12 / "report.html").read_bytes()
    ).hexdigest()
    monkeypatch.setattr(
        release_module,
        "_validate_full_pool_v12_production_release",
        lambda **_kwargs: {
            "schema_version": "abm-report-release-contract-v12",
            "release_id": "protected-v12",
            "report_sha256": protected_v12_report_sha256,
            "production_deploy_eligible": True,
        },
    )
    protected = (
        source,
        Path(source_manifest["upstream_source"]["source_root"]),
        historical_formal,
        historical_study,
        candidate,
        protected_v12,
    )
    before = {root: _snapshot(root) for root in protected}
    destination = tmp_path / "production-v13"
    contract_path = tmp_path / "production-v13-contract.json"

    promoted = release_module.promote_concurrent_robustness_release(
        repo_root=tmp_path,
        formal_root=historical_formal,
        study_root=historical_study,
        candidate_dir=candidate,
        destination_dir=destination,
        release_contract_path=contract_path,
        release_id="formal-two-stage-v13",
        full_pool_source_root=source,
        full_pool_manifest_sha256=manifest_sha256,
        full_pool_source_identity=source_identity,
        protected_v12_release_root=protected_v12,
        protected_v12_contract_path=protected_v12_contract,
        implementation_commit="a" * 40,
    )

    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    assert promoted.source_dir == destination.resolve()
    assert contract["schema_version"] == "abm-report-release-contract-v13"
    assert contract["release_purpose"] == "full_pool_two_stage_realization_formal_research"
    assert contract["sampling_status"] == "persisted_two_stage_realized_full_pool_formal_run"
    assert contract["live_api_triggered"] is True
    assert contract["formal_research_evidence"] is True
    assert contract["realization_provider_calls"] == 0
    assert contract["realization_live_api_triggered"] is False
    assert contract["realized_source"]["source_identity"] == source_identity
    accounting = contract["composite_provider_accounting"]
    assert accounting["upstream_live_api_triggered"] is True
    assert accounting["upstream_external_request_invocations"] == 24
    assert accounting["realization_provider_calls"] == 0
    assert accounting["realization_live_api_triggered"] is False
    assert accounting["composite_live_api_triggered"] is True
    assert contract["release_readiness"]["public_acceptance_recorded"] is False
    assert contract["release_readiness"]["canonical_deployment_triggered"] is False
    report = (destination / "report.html").read_text(encoding="utf-8")
    assert 'data-production-deploy-eligible="true"' in report
    assert '<meta name="abm-release-contract" content="abm-report-release-contract-v13">' in report
    assert (destination / "full_pool_two_stage_production_release_evidence.json").is_file()
    assert (destination / "artifact_manifest.json").is_file()
    assert all(_snapshot(root) == before[root] for root in protected)

    validated = release_module.validate_concurrent_robustness_production_release(
        repo_root=tmp_path,
        contract_document=contract,
        source_dir=destination,
    )
    assert validated["schema_version"] == "abm-report-release-contract-v13"
    assert validated["sampling_status"] == "persisted_two_stage_realized_full_pool_formal_run"
    assert validated["live_api_triggered"] is True
    assert validated["realization_provider_calls"] == 0
    assert validated["report_sha256"] == promoted.report_sha256

    cli_validated = _load_validator().validate_release(
        repo_root=tmp_path,
        contract_path=contract_path,
        source_dir=destination,
    )
    assert cli_validated == validated


def test_v13_publication_removes_both_outputs_when_round_trip_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _promoted_v13_fixture(tmp_path, monkeypatch)
    source = fixture["source"]
    historical_formal = fixture["historical_formal"]
    historical_study = fixture["historical_study"]
    candidate = fixture["candidate"]
    protected_v12 = fixture["protected_v12"]
    protected_v12_contract = fixture["protected_v12_contract"]
    manifest_sha256 = fixture["manifest_sha256"]
    assert isinstance(source, Path)
    assert isinstance(historical_formal, Path)
    assert isinstance(historical_study, Path)
    assert isinstance(candidate, Path)
    assert isinstance(protected_v12, Path)
    assert isinstance(protected_v12_contract, Path)
    assert isinstance(manifest_sha256, str)
    source_identity = json.loads(
        (source / "manifest.json").read_text(encoding="utf-8")
    )["source_identity"]
    destination = tmp_path / "failed-v13-release"
    contract_path = tmp_path / "failed-v13-contract.json"

    def fail_round_trip(**_kwargs: object) -> dict[str, object]:
        raise release_module.ConcurrentRobustnessReleaseError("simulated v13 round-trip failure")

    monkeypatch.setattr(
        release_module,
        "_validate_full_pool_v13_production_release",
        fail_round_trip,
    )

    with pytest.raises(
        release_module.ConcurrentRobustnessReleaseError,
        match="simulated v13 round-trip failure",
    ):
        release_module.promote_concurrent_robustness_release(
            repo_root=tmp_path,
            formal_root=historical_formal,
            study_root=historical_study,
            candidate_dir=candidate,
            destination_dir=destination,
            release_contract_path=contract_path,
            release_id="failed-round-trip-v13",
            full_pool_source_root=source,
            full_pool_manifest_sha256=manifest_sha256,
            full_pool_source_identity=source_identity,
            protected_v12_release_root=protected_v12,
            protected_v12_contract_path=protected_v12_contract,
            implementation_commit="a" * 40,
        )

    assert not destination.exists()
    assert not contract_path.exists()
    assert not list(tmp_path.glob(".failed-v13-release.v13.*.staging"))
    assert not list(tmp_path.glob(".failed-v13-contract.json.*.staging"))


def test_v13_round_trip_rejects_crossed_accounting_and_physical_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _promoted_v13_fixture(tmp_path, monkeypatch)
    destination = fixture["destination"]
    contract_path = fixture["contract_path"]
    source = fixture["source"]
    protected_v12 = fixture["protected_v12"]
    historical_formal = fixture["historical_formal"]
    historical_study = fixture["historical_study"]
    candidate = fixture["candidate"]
    manifest_sha256 = fixture["manifest_sha256"]
    protected_v12_contract = fixture["protected_v12_contract"]
    assert isinstance(destination, Path)
    assert isinstance(contract_path, Path)
    assert isinstance(source, Path)
    assert isinstance(protected_v12, Path)
    assert isinstance(historical_formal, Path)
    assert isinstance(historical_study, Path)
    assert isinstance(candidate, Path)
    assert isinstance(manifest_sha256, str)
    assert isinstance(protected_v12_contract, Path)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))

    crossed = deepcopy(contract)
    crossed["composite_provider_accounting"]["realization_provider_calls"] = 1
    with pytest.raises(
        release_module.ConcurrentRobustnessReleaseError,
        match="accounting|crossed",
    ):
        release_module.validate_concurrent_robustness_production_release(
            repo_root=tmp_path,
            contract_document=crossed,
            source_dir=destination,
        )

    extra = destination / "extra.txt"
    extra.write_text("not in the immutable inventory\n", encoding="utf-8")
    with pytest.raises(
        release_module.ConcurrentRobustnessReleaseError,
        match="inventory|hashes|differ",
    ):
        release_module.validate_concurrent_robustness_production_release(
            repo_root=tmp_path,
            contract_document=contract,
            source_dir=destination,
        )
    extra.unlink()

    symlink = destination / "forbidden-link"
    symlink.symlink_to(destination / "report.html")
    with pytest.raises(
        release_module.ConcurrentRobustnessReleaseError,
        match="symlink|inventory",
    ):
        release_module.validate_concurrent_robustness_production_release(
            repo_root=tmp_path,
            contract_document=contract,
            source_dir=destination,
        )
    symlink.unlink()

    source_evidence = source / "realization-evidence.json"
    source_evidence_before = source_evidence.read_bytes()
    source_evidence.write_bytes(source_evidence_before + b" ")
    with pytest.raises(
        release_module.ConcurrentRobustnessReleaseError,
        match="source|manifest|closure|hash",
    ):
        release_module.validate_concurrent_robustness_production_release(
            repo_root=tmp_path,
            contract_document=contract,
            source_dir=destination,
        )
    source_evidence.write_bytes(source_evidence_before)

    v12_report = protected_v12 / "report.html"
    v12_report_before = v12_report.read_bytes()
    v12_report.write_bytes(v12_report_before + b"drift")
    with pytest.raises(
        release_module.ConcurrentRobustnessReleaseError,
        match="v12|protected|crossed",
    ):
        release_module.validate_concurrent_robustness_production_release(
            repo_root=tmp_path,
            contract_document=contract,
            source_dir=destination,
        )
    v12_report.write_bytes(v12_report_before)

    with pytest.raises(
        release_module.ConcurrentRobustnessReleaseError,
        match="already exists",
    ):
        release_module.promote_concurrent_robustness_release(
            repo_root=tmp_path,
            formal_root=historical_formal,
            study_root=historical_study,
            candidate_dir=candidate,
            destination_dir=destination,
            release_contract_path=tmp_path / "other-v13-contract.json",
            release_id="duplicate-v13",
            full_pool_source_root=source,
            full_pool_manifest_sha256=manifest_sha256,
            full_pool_source_identity=contract["realized_source"]["source_identity"],
            protected_v12_release_root=protected_v12,
            protected_v12_contract_path=protected_v12_contract,
            implementation_commit="a" * 40,
        )
