from __future__ import annotations

import copy
import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path
from typing import TypedDict

import pytest

from llm_abm_sim import concurrent_robustness_evidence as evidence_module
from llm_abm_sim import concurrent_robustness_release as release_module
from llm_abm_sim import concurrent_robustness_report as report_module
from tests.integration.test_full_pool_presentation_bundle import (
    _formal_shaped_full_pool_source,
    _historical_candidate,
    _snapshot,
)


class _ClosedCandidateInputs(TypedDict):
    source: Path
    source_hash: str
    historical_formal: Path
    historical_study: Path
    bundle: Path
    candidate: Path
    closure_path: Path
    closure: evidence_module.FullPoolPresentationClosureFacts


def _closed_candidate(root: Path) -> _ClosedCandidateInputs:
    source, source_hash, _, _ = _formal_shaped_full_pool_source(root / "full-pool")
    historical_formal, historical_study, historical_candidate = _historical_candidate(
        root / "historical"
    )
    bundle = root / "bundle"
    report_module._REPORT_PRESENTATION.compose_full_pool_presentation_bundle(
        full_pool_source_root=source,
        full_pool_manifest_sha256=source_hash,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        historical_candidate_dir=historical_candidate,
        destination_dir=bundle,
    )
    candidate = root / "candidate"
    report_module._REPORT_PRESENTATION.compose_full_pool_candidate(
        full_pool_source_root=source,
        full_pool_manifest_sha256=source_hash,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        presentation_bundle_dir=bundle,
        implementation_commit="abcdef0",
        destination_dir=candidate,
    )
    closure_path = root / "closure.json"
    closure = evidence_module.close_full_pool_presentation(
        repo_root=root,
        full_pool_source_root=source,
        full_pool_manifest_sha256=source_hash,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        presentation_bundle_dir=bundle,
        candidate_dir=candidate,
        destination_path=closure_path,
        implementation_commit="abcdef0",
    )
    return {
        "source": source,
        "source_hash": source_hash,
        "historical_formal": historical_formal,
        "historical_study": historical_study,
        "bundle": bundle,
        "candidate": candidate,
        "closure_path": closure_path,
        "closure": closure,
    }


def _injected_formal_facts(inputs: _ClosedCandidateInputs) -> evidence_module.FullPoolFormalReleaseFacts:
    closure = inputs["closure"]
    assert isinstance(closure, evidence_module.FullPoolPresentationClosureFacts)
    source = inputs["source"]
    historical_formal = inputs["historical_formal"]
    historical_study = inputs["historical_study"]
    assert isinstance(source, Path)
    assert isinstance(historical_formal, Path)
    assert isinstance(historical_study, Path)
    return evidence_module.FullPoolFormalReleaseFacts(
        full_pool_source_path=source.resolve(),
        full_pool_source_schema_version="full-pool-formal-source-v1",
        full_pool_source_identity=closure.full_pool_source_identity,
        full_pool_source_manifest_sha256=closure.full_pool_source_manifest_sha256,
        full_pool_source_hash=closure.full_pool_source_hash,
        full_pool_contract_sha256=str(closure.source_lineage["full_pool"]["contract_sha256"]),
        evidence_profile="formal_live",
        provider_transport="openai-codex",
        adapter_identity=evidence_module.FULL_POOL_FORMAL_ADAPTER_IDENTITY,
        requested_model="gpt-5.6-sol",
        qualified_observed_model="gpt-5.6-sol",
        distinct_users=36_400,
        eligible_pairs=109_200,
        exposures=109_200,
        primary_terminals=109_200,
        committed_batches=30,
        candidate_ranking_rows=1_691_730,
        campaign_exposure_coverage=3,
        provider_failed_terminals=0,
        logical_judgments=109_200,
        physical_attempts=109_200,
        physical_attempt_cap=120_120,
        provider_responses=109_200,
        successful_decisions=109_200,
        external_request_invocations=109_200,
        observed_model_counts={"gpt-5.6-sol": 109_200},
        usage_complete_response_count=109_200,
        usage_missing_response_count=0,
        usage_malformed_response_count=0,
        subscription_billed_cost_usd=0.0,
        live_api_triggered=True,
        source_production_deploy_eligible=True,
        historical_formal_path=historical_formal.resolve(),
        historical_formal_source_id=closure.historical_formal_source_id,
        historical_formal_manifest_sha256=closure.historical_formal_manifest_sha256,
        historical_formal_source_kind="formal",
        historical_formal_users=1_000,
        historical_formal_exposures=1_800,
        historical_primary_terminals=1_800,
        historical_shadow_terminals=1_800,
        historical_trace_rows=1_800,
        historical_study_path=historical_study.resolve(),
        historical_study_manifest_sha256=closure.robustness_study_manifest_sha256,
        historical_study_root_identity_sha256=closure.robustness_study_root_identity_sha256,
        historical_study_profile="formal_live",
        historical_study_evidence_profile="formal_live",
        historical_study_cell_count=16,
        historical_study_logical_judgments=28_800,
    )


def test_v8_promotion_materializes_an_exact_non_overwriting_local_release(tmp_path: Path) -> None:
    inputs = _closed_candidate(tmp_path)
    protected = (
        inputs["source"],
        inputs["historical_formal"],
        inputs["historical_study"],
        inputs["bundle"],
        inputs["candidate"],
        inputs["closure_path"],
    )
    assert all(isinstance(path, Path) for path in protected)
    before = {path: _snapshot(path) if path.is_dir() else {path.name: path.read_bytes()} for path in protected}
    destination = tmp_path / "production-v8"
    contract_path = tmp_path / "release-contract-v8.json"

    promoted = release_module.promote_concurrent_robustness_release(
        repo_root=tmp_path,
        formal_root=inputs["historical_formal"],
        study_root=inputs["historical_study"],
        workspace_root=None,
        candidate_dir=inputs["candidate"],
        execution_contract_path=None,
        destination_dir=destination,
        release_contract_path=contract_path,
        release_id="full-pool-v8-test",
        presentation_closure_path=inputs["closure_path"],
        full_pool_source_root=inputs["source"],
        full_pool_manifest_sha256=inputs["source_hash"],
        implementation_commit="abcdef0",
        _closed_full_pool_formal_facts=_injected_formal_facts(inputs),
    )

    assert promoted.source_dir == destination.resolve()
    assert promoted.contract_path == contract_path.resolve()
    assert all(
        before[path] == (_snapshot(path) if path.is_dir() else {path.name: path.read_bytes()})
        for path in protected
    )
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    manifest = json.loads((destination / "artifact_manifest.json").read_text(encoding="utf-8"))
    production_evidence = json.loads(
        (destination / "full_pool_production_release_evidence.json").read_text(encoding="utf-8")
    )
    payload = json.loads(
        (destination / "concurrent_robustness_report_payload.json").read_text(encoding="utf-8")
    )
    candidate_manifest = json.loads(
        (destination / "full_pool_candidate_artifact_manifest.json").read_text(encoding="utf-8")
    )
    candidate_evidence = json.loads(
        (destination / "full_pool_candidate_release_evidence.json").read_text(encoding="utf-8")
    )

    assert contract["schema_version"] == "abm-report-release-contract-v8"
    assert contract["production_deploy_eligible"] is True
    assert contract["implementation_commit"] == "abcdef0"
    assert manifest["schema_version"] == "full-pool-production-release-manifest-v1"
    assert manifest["production_deploy_eligible"] is True
    assert production_evidence["schema_version"] == "full-pool-production-release-evidence-v1"
    assert production_evidence["provider_calls_during_promotion"] == 0
    assert production_evidence["production_deploy_eligible"] is True
    assert payload["production_deploy_eligible"] is True
    assert candidate_manifest["production_deploy_eligible"] is False
    assert candidate_evidence["production_deploy_eligible"] is False
    assert (destination / "full_pool_presentation_closure.json").read_bytes() == Path(
        inputs["closure_path"]
    ).read_bytes()
    assert (destination / "report.html").stat().st_size < 3 * 1024 * 1024
    assert len(list(destination.rglob("*.mmd"))) == 8
    assert not any(path.is_symlink() for path in destination.rglob("*"))
    actual_hashes = {
        path.relative_to(destination).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(destination.rglob("*"))
        if path.is_file()
    }
    assert contract["artifact_sha256"] == actual_hashes
    assert manifest["release_identity_sha256"] == contract["release_identity_sha256"]

    with pytest.raises(
        release_module.ConcurrentRobustnessReleaseError,
        match="Formal production facts",
    ):
        release_module.validate_concurrent_robustness_production_release(
            repo_root=tmp_path,
            contract_document=contract,
            source_dir=destination,
        )


def _promote_with_injected(
    root: Path,
    inputs: _ClosedCandidateInputs,
    *,
    destination_name: str,
    contract_name: str,
    formal_facts: evidence_module.FullPoolFormalReleaseFacts | None = None,
) -> release_module.ConcurrentRobustnessProductionRelease:
    return release_module.promote_concurrent_robustness_release(
        repo_root=root,
        formal_root=inputs["historical_formal"],
        study_root=inputs["historical_study"],
        workspace_root=None,
        candidate_dir=inputs["candidate"],
        execution_contract_path=None,
        destination_dir=root / destination_name,
        release_contract_path=root / contract_name,
        release_id=f"{destination_name}-release",
        presentation_closure_path=inputs["closure_path"],
        full_pool_source_root=inputs["source"],
        full_pool_manifest_sha256=inputs["source_hash"],
        implementation_commit="abcdef0",
        _closed_full_pool_formal_facts=formal_facts or _injected_formal_facts(inputs),
    )


def _injected_evidence(
    root: Path,
    inputs: _ClosedCandidateInputs,
) -> evidence_module.FullPoolProductionEvidenceFacts:
    return evidence_module.validate_full_pool_production_evidence(
        repo_root=root,
        closure_path=inputs["closure_path"],
        full_pool_source_root=inputs["source"],
        full_pool_manifest_sha256=str(inputs["source_hash"]),
        historical_formal_root=inputs["historical_formal"],
        historical_study_root=inputs["historical_study"],
        candidate_dir=inputs["candidate"],
        implementation_commit="abcdef0",
        formal_facts=_injected_formal_facts(inputs),
    )


def test_v8_promotion_rejects_count_model_usage_failure_and_live_drift(tmp_path: Path) -> None:
    inputs = _closed_candidate(tmp_path)
    valid = _injected_formal_facts(inputs)
    mutations = (
        replace(valid, distinct_users=36_399),
        replace(valid, qualified_observed_model="gpt-5.6-sol-crossed"),
        replace(valid, usage_complete_response_count=109_199),
        replace(valid, provider_failed_terminals=1),
        replace(valid, live_api_triggered=False),
    )

    for index, formal_facts in enumerate(mutations):
        destination = tmp_path / f"rejected-{index}"
        contract = tmp_path / f"rejected-{index}.json"
        with pytest.raises(
            release_module.ConcurrentRobustnessReleaseError,
            match="Formal production facts",
        ):
            _promote_with_injected(
                tmp_path,
                inputs,
                destination_name=destination.name,
                contract_name=contract.name,
                formal_facts=formal_facts,
            )
        assert not destination.exists()
        assert not contract.exists()


def test_v8_promotion_rejects_crossed_source_closure_and_candidate_identities(
    tmp_path: Path,
) -> None:
    inputs = _closed_candidate(tmp_path)
    valid = _injected_formal_facts(inputs)
    crossed = (
        replace(valid, full_pool_source_identity="crossed-source"),
        replace(valid, historical_formal_source_id="crossed-historical"),
        replace(valid, historical_study_root_identity_sha256="0" * 64),
    )
    for index, formal_facts in enumerate(crossed):
        with pytest.raises(release_module.ConcurrentRobustnessReleaseError):
            _promote_with_injected(
                tmp_path,
                inputs,
                destination_name=f"crossed-{index}",
                contract_name=f"crossed-{index}.json",
                formal_facts=formal_facts,
            )
        assert not (tmp_path / f"crossed-{index}").exists()

    closure_path = inputs["closure_path"]
    candidate = inputs["candidate"]
    assert isinstance(closure_path, Path)
    assert isinstance(candidate, Path)
    closure_bytes = closure_path.read_bytes()
    closure_document = json.loads(closure_bytes)
    closure_document["candidate_identity_sha256"] = "0" * 64
    closure_path.write_text(json.dumps(closure_document) + "\n", encoding="utf-8")
    with pytest.raises(release_module.ConcurrentRobustnessReleaseError):
        _promote_with_injected(
            tmp_path,
            inputs,
            destination_name="crossed-closure",
            contract_name="crossed-closure.json",
        )
    assert not (tmp_path / "crossed-closure").exists()
    closure_path.write_bytes(closure_bytes)

    report = candidate / "report.html"
    report.write_bytes(report.read_bytes() + b"crossed\n")
    with pytest.raises(release_module.ConcurrentRobustnessReleaseError):
        _promote_with_injected(
            tmp_path,
            inputs,
            destination_name="crossed-candidate",
            contract_name="crossed-candidate.json",
        )
    assert not (tmp_path / "crossed-candidate").exists()


def test_v8_rejects_existing_nested_escaping_and_symlink_paths(tmp_path: Path) -> None:
    inputs = _closed_candidate(tmp_path)
    candidate = inputs["candidate"]
    source = inputs["source"]
    assert isinstance(candidate, Path)
    assert isinstance(source, Path)

    existing = tmp_path / "existing-v8"
    existing.mkdir()
    (existing / "sentinel").write_text("operator-owned\n", encoding="utf-8")
    with pytest.raises(release_module.ConcurrentRobustnessReleaseError, match="already exists"):
        _promote_with_injected(
            tmp_path,
            inputs,
            destination_name=existing.name,
            contract_name="existing-v8.json",
        )
    assert (existing / "sentinel").read_text(encoding="utf-8") == "operator-owned\n"

    with pytest.raises(release_module.ConcurrentRobustnessReleaseError, match="overlap"):
        release_module.promote_concurrent_robustness_release(
            repo_root=tmp_path,
            formal_root=inputs["historical_formal"],
            study_root=inputs["historical_study"],
            workspace_root=None,
            candidate_dir=candidate,
            execution_contract_path=None,
            destination_dir=candidate / "nested-release",
            release_contract_path=tmp_path / "nested-release.json",
            release_id="nested-release",
            presentation_closure_path=inputs["closure_path"],
            full_pool_source_root=source,
            full_pool_manifest_sha256=inputs["source_hash"],
            implementation_commit="abcdef0",
            _closed_full_pool_formal_facts=_injected_formal_facts(inputs),
        )
    assert not (candidate / "nested-release").exists()

    escape = tmp_path.parent / f"{tmp_path.name}-escape-v8"
    with pytest.raises(release_module.ConcurrentRobustnessReleaseError, match="safe repository path"):
        release_module.promote_concurrent_robustness_release(
            repo_root=tmp_path,
            formal_root=inputs["historical_formal"],
            study_root=inputs["historical_study"],
            workspace_root=None,
            candidate_dir=candidate,
            execution_contract_path=None,
            destination_dir=escape,
            release_contract_path=tmp_path / "escape-v8.json",
            release_id="escape-v8",
            presentation_closure_path=inputs["closure_path"],
            full_pool_source_root=source,
            full_pool_manifest_sha256=inputs["source_hash"],
            implementation_commit="abcdef0",
            _closed_full_pool_formal_facts=_injected_formal_facts(inputs),
        )
    assert not escape.exists()

    source_link = tmp_path / "source-link"
    source_link.symlink_to(source, target_is_directory=True)
    linked_inputs: _ClosedCandidateInputs = inputs.copy()
    linked_inputs["source"] = source_link
    with pytest.raises(release_module.ConcurrentRobustnessReleaseError, match="non-symlink"):
        _promote_with_injected(
            tmp_path,
            linked_inputs,
            destination_name="linked-v8",
            contract_name="linked-v8.json",
        )
    assert not (tmp_path / "linked-v8").exists()


def test_v8_contract_dispatch_rejects_missing_extra_crossed_and_drifted_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _closed_candidate(tmp_path)
    promoted = _promote_with_injected(
        tmp_path,
        inputs,
        destination_name="production-v8-contract",
        contract_name="production-v8-contract.json",
    )
    contract = json.loads(promoted.contract_path.read_text(encoding="utf-8"))
    evidence = _injected_evidence(tmp_path, inputs)
    monkeypatch.setattr(
        release_module._evidence,
        "validate_full_pool_production_evidence",
        lambda **_kwargs: evidence,
    )
    assert set(contract) == release_module._RELEASE_CONTRACT_V8_FIELDS
    assert set(contract["full_pool_formal_facts"]) == release_module._FULL_POOL_FORMAL_FACT_FIELDS
    assert set(contract["historical_formal_facts"]) == release_module._HISTORICAL_FORMAL_FACT_FIELDS
    assert set(contract["historical_study_facts"]) == release_module._HISTORICAL_STUDY_FACT_FIELDS
    validated = release_module.validate_concurrent_robustness_production_release(
        repo_root=tmp_path,
        contract_document=contract,
        source_dir=promoted.source_dir,
    )
    assert validated["schema_version"] == "abm-report-release-contract-v8"
    assert validated["sampling_status"] == "persisted_full_pool_formal_run"
    assert validated["decision_execution_mode"] == "live_provider"
    assert validated["production_deploy_eligible"] is True

    mutations: list[dict[str, object]] = []
    missing = copy.deepcopy(contract)
    missing.pop("mechanism_set_identity_sha256")
    mutations.append(missing)
    extra = copy.deepcopy(contract)
    extra["unexpected"] = True
    mutations.append(extra)
    schema_confusion = copy.deepcopy(contract)
    schema_confusion["report_payload_schema_version"] = "concurrent-robustness-report-payload-v2"
    mutations.append(schema_confusion)
    count_drift = copy.deepcopy(contract)
    count_drift["full_pool_formal_facts"]["distinct_users"] = 36_399
    mutations.append(count_drift)
    model_drift = copy.deepcopy(contract)
    model_drift["full_pool_formal_facts"]["qualified_observed_model"] = "crossed"
    mutations.append(model_drift)
    usage_drift = copy.deepcopy(contract)
    usage_drift["full_pool_formal_facts"]["usage_complete_response_count"] = 0
    mutations.append(usage_drift)
    failure_drift = copy.deepcopy(contract)
    failure_drift["full_pool_formal_facts"]["provider_failed_terminals"] = 1
    mutations.append(failure_drift)
    candidate_cross = copy.deepcopy(contract)
    candidate_cross["candidate_identity_sha256"] = "0" * 64
    mutations.append(candidate_cross)
    closure_cross = copy.deepcopy(contract)
    closure_cross["presentation_closure_contract_sha256"] = "0" * 64
    mutations.append(closure_cross)

    for mutated in mutations:
        with pytest.raises(release_module.ConcurrentRobustnessReleaseError):
            release_module.validate_concurrent_robustness_production_release(
                repo_root=tmp_path,
                contract_document=mutated,
                source_dir=promoted.source_dir,
            )


def test_v8_local_validator_rejects_artifact_download_trace_symlink_and_extra_drift(
    tmp_path: Path,
) -> None:
    inputs = _closed_candidate(tmp_path)
    promoted = _promote_with_injected(
        tmp_path,
        inputs,
        destination_name="production-v8-artifacts",
        contract_name="production-v8-artifacts.json",
    )
    evidence = _injected_evidence(tmp_path, inputs)
    stage_facts = release_module._full_pool_production_stage_facts(
        release_id=promoted.release_id,
        evidence=evidence,
    )
    source = promoted.source_dir
    release_identity = promoted.release_identity_sha256
    backup = {
        path.relative_to(source).as_posix(): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }

    def restore() -> None:
        shutil.rmtree(source)
        source.mkdir()
        for relative_path, payload in backup.items():
            target = source / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)

    def expect_rejected() -> None:
        with pytest.raises(release_module.ConcurrentRobustnessReleaseError):
            release_module._validate_full_pool_v8_release_dir(
                source,
                repo_root=tmp_path.resolve(),
                evidence=evidence,
                stage_facts=stage_facts,
                release_identity=release_identity,
            )
        restore()

    (source / "report.html").write_bytes((source / "report.html").read_bytes() + b"mutated\n")
    expect_rejected()

    manifest_path = source / "artifact_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    first_download = next(iter(manifest["approved_downloads"]))
    manifest["approved_downloads"][first_download] = "missing-download.json"
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    expect_rejected()

    trace_path = source / "trace" / "full-pool-trace-index.json"
    trace_path.write_bytes(trace_path.read_bytes() + b"mutated\n")
    expect_rejected()

    mermaid = source / "full-pool-mechanism.mmd"
    mermaid.unlink()
    mermaid.symlink_to(source / "report.html")
    expect_rejected()

    (source / "unexpected.json").write_text("{}\n", encoding="utf-8")
    expect_rejected()


def test_v8_contract_publish_failure_removes_partial_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _closed_candidate(tmp_path)
    real_replace = release_module.os.replace
    replacements = 0

    def fail_contract_publish(source: Path, destination: Path) -> None:
        nonlocal replacements
        replacements += 1
        if replacements == 2:
            raise OSError("v8 contract publish failure")
        real_replace(source, destination)

    monkeypatch.setattr(release_module.os, "replace", fail_contract_publish)
    with pytest.raises(OSError, match="v8 contract publish failure"):
        _promote_with_injected(
            tmp_path,
            inputs,
            destination_name="production-v8-atomic",
            contract_name="production-v8-atomic.json",
        )
    assert not (tmp_path / "production-v8-atomic").exists()
    assert not (tmp_path / "production-v8-atomic.json").exists()
    assert not list(tmp_path.glob(".production-v8-atomic.v8.*.staging"))
    assert not list(tmp_path.glob(".production-v8-atomic.json.*.staging"))
