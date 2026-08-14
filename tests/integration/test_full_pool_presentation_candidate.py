from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from llm_abm_sim import concurrent_robustness_evidence as evidence_module
from llm_abm_sim import concurrent_robustness_report as report_module
from tests.integration.test_full_pool_presentation_bundle import (
    _formal_shaped_full_pool_source,
    _full_pool_source,
    _historical_candidate,
    _snapshot,
)


def _compose_inputs(root: Path) -> dict[str, Path | str]:
    full_pool_source, full_pool_manifest_sha256 = _full_pool_source(root / "full-pool")
    historical_formal, historical_study, historical_candidate = _historical_candidate(root / "historical")
    bundle = root / "presentation-bundle"
    report_module._REPORT_PRESENTATION.compose_full_pool_presentation_bundle(
        full_pool_source_root=full_pool_source,
        full_pool_manifest_sha256=full_pool_manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        historical_candidate_dir=historical_candidate,
        destination_dir=bundle,
    )
    return {
        "full_pool_source": full_pool_source,
        "full_pool_manifest_sha256": full_pool_manifest_sha256,
        "historical_formal": historical_formal,
        "historical_study": historical_study,
        "bundle": bundle,
    }


def test_report_interface_composes_exact_three_lineage_candidate(tmp_path: Path) -> None:
    inputs = _compose_inputs(tmp_path)
    protected = (
        inputs["full_pool_source"],
        inputs["historical_formal"],
        inputs["historical_study"],
        inputs["bundle"],
    )
    assert all(isinstance(path, Path) for path in protected)
    before = {path: _snapshot(path) for path in protected if isinstance(path, Path)}
    destination = tmp_path / "full-pool-candidate"

    created = report_module._REPORT_PRESENTATION.compose_full_pool_candidate(
        full_pool_source_root=inputs["full_pool_source"],
        full_pool_manifest_sha256=inputs["full_pool_manifest_sha256"],
        historical_formal_root=inputs["historical_formal"],
        historical_study_root=inputs["historical_study"],
        presentation_bundle_dir=inputs["bundle"],
        implementation_commit="abcdef0",
        destination_dir=destination,
    )

    assert created == destination.resolve()
    assert all(before[path] == _snapshot(path) for path in before)
    payload_path = destination / "concurrent_robustness_report_payload.json"
    manifest_path = destination / "artifact_manifest.json"
    evidence_path = destination / "release_evidence.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    release_evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "full-pool-three-lineage-report-payload-v1"
    assert set(payload["source_lineage"]) == {
        "full_pool",
        "historical_formal",
        "robustness_study",
    }
    assert payload["source_lineage"]["full_pool"]["counts"]["primary_terminals"] == 21
    assert payload["source_lineage"]["historical_formal"]["source_kind"] == "fixture"
    assert payload["source_lineage"]["historical_formal"]["counts"] == {
        "distinct_users": 30,
        "exposures": 60,
        "primary_terminals": 60,
        "shadow_terminals": 60,
        "trace_rows": 60,
    }
    assert payload["claim_boundary"]["historical_formal_scope"] == (
        "scaled_validation_primary_shadow_only"
    )
    assert payload["source_lineage"]["robustness_study"]["sample_size"] == 30
    assert payload["source_lineage"]["robustness_study"]["ranking_weight_point_count"] == 19
    assert payload["source_lineage"]["robustness_study"]["prompt_model_cell_count"] == 16
    presentation = payload["presentation"]
    assert len(presentation["mechanism_presentation"]["masters"]) == 8
    assert presentation["trace"]["partition_count"] == 9
    assert presentation["trace"]["terminal_count"] == 21
    assert payload["provider_calls_during_composition"] == 0
    assert payload["production_deploy_eligible"] is False

    assert manifest["schema_version"] == "full-pool-three-lineage-candidate-manifest-v1"
    assert manifest["candidate_type"] == "full_pool_three_lineage_presentation_candidate"
    assert manifest["production_deploy_eligible"] is False
    artifact_paths = [row["relative_path"] for row in manifest["artifacts"]]
    assert artifact_paths == sorted(artifact_paths)
    assert len(artifact_paths) == len(set(artifact_paths))
    assert set(artifact_paths) == {
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file()
    } - {"artifact_manifest.json"}
    assert all(
        hashlib.sha256((destination / row["relative_path"]).read_bytes()).hexdigest()
        == row["sha256"]
        for row in manifest["artifacts"]
    )
    assert release_evidence["schema_version"] == "full-pool-three-lineage-release-evidence-v1"
    assert release_evidence["candidate_content_identity_sha256"] == manifest[
        "candidate_content_identity_sha256"
    ]
    assert release_evidence["provider_calls_during_composition"] == 0
    assert release_evidence["production_deploy_eligible"] is False

    facts = report_module._REPORT_PRESENTATION.validate_full_pool_candidate(
        destination,
        full_pool_source_root=inputs["full_pool_source"],
        full_pool_manifest_sha256=inputs["full_pool_manifest_sha256"],
        historical_formal_root=inputs["historical_formal"],
        historical_study_root=inputs["historical_study"],
        presentation_bundle_dir=inputs["bundle"],
        implementation_commit="abcdef0",
    )
    assert facts.candidate_identity_sha256 == manifest["candidate_identity_sha256"]
    assert facts.trace_index_sha256 == presentation["trace"]["index"]["sha256"]


def _compose_candidate(root: Path) -> tuple[dict[str, Path | str], Path]:
    inputs = _compose_inputs(root)
    candidate = root / "full-pool-candidate"
    report_module._REPORT_PRESENTATION.compose_full_pool_candidate(
        full_pool_source_root=inputs["full_pool_source"],
        full_pool_manifest_sha256=inputs["full_pool_manifest_sha256"],
        historical_formal_root=inputs["historical_formal"],
        historical_study_root=inputs["historical_study"],
        presentation_bundle_dir=inputs["bundle"],
        implementation_commit="abcdef0",
        destination_dir=candidate,
    )
    return inputs, candidate


@pytest.mark.parametrize(
    "mutation",
    (
        "missing-field",
        "extra-field",
        "schema-confusion",
        "crossed-lineage-count",
        "trace-mutation",
        "extra-artifact",
        "symlink-artifact",
    ),
)
def test_candidate_validator_rejects_schema_inventory_and_trace_mutations(
    tmp_path: Path,
    mutation: str,
) -> None:
    inputs, candidate = _compose_candidate(tmp_path)
    payload_path = candidate / "concurrent_robustness_report_payload.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    if mutation == "missing-field":
        payload.pop("claim_boundary")
        payload_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    elif mutation == "extra-field":
        payload["unexpected"] = True
        payload_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    elif mutation == "schema-confusion":
        payload["schema_version"] = "concurrent-robustness-report-payload-v2"
        payload_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    elif mutation == "crossed-lineage-count":
        payload["source_lineage"]["full_pool"]["counts"]["primary_terminals"] += 1
        payload_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    elif mutation == "trace-mutation":
        index = payload["presentation"]["trace"]
        partition_path = candidate / index["partitions"][0]["relative_path"]
        partition_path.write_bytes(partition_path.read_bytes() + b" ")
    elif mutation == "extra-artifact":
        (candidate / "extra.json").write_text("{}\n", encoding="utf-8")
    else:
        target = candidate / payload["presentation"]["trace"]["partitions"][0]["relative_path"]
        link = candidate / "trace" / "linked-partition.json"
        link.symlink_to(target)

    with pytest.raises(
        report_module._RobustnessReportClosureError,
        match="candidate|closure|artifact",
    ):
        report_module._REPORT_PRESENTATION.validate_full_pool_candidate(
            candidate,
            full_pool_source_root=inputs["full_pool_source"],
            full_pool_manifest_sha256=inputs["full_pool_manifest_sha256"],
            historical_formal_root=inputs["historical_formal"],
            historical_study_root=inputs["historical_study"],
            presentation_bundle_dir=inputs["bundle"],
            implementation_commit="abcdef0",
        )


def test_report_interface_materializes_and_validates_full_pool_production_bytes(
    tmp_path: Path,
) -> None:
    inputs, candidate = _compose_candidate(tmp_path)
    candidate_facts = report_module._REPORT_PRESENTATION.validate_full_pool_candidate(
        candidate,
        full_pool_source_root=inputs["full_pool_source"],
        full_pool_manifest_sha256=inputs["full_pool_manifest_sha256"],
        historical_formal_root=inputs["historical_formal"],
        historical_study_root=inputs["historical_study"],
        presentation_bundle_dir=inputs["bundle"],
        implementation_commit="abcdef0",
    )
    before = _snapshot(candidate)
    stage_facts = report_module._FullPoolProductionPresentationFacts(
        release_id="full-pool-v8-test",
        release_contract_schema="abm-report-release-contract-v8",
        canonical_endpoint="https://abm.q1ngyuan.top/",
        production_evidence_schema="full-pool-production-release-evidence-v1",
        implementation_commit="abcdef0",
        full_pool_source_identity=str(
            candidate_facts.source_lineage["full_pool"]["source_identity"]
        ),
        full_pool_source_manifest_sha256=str(
            candidate_facts.source_lineage["full_pool"]["manifest_sha256"]
        ),
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
        provider_transport="openai-codex",
        requested_model="gpt-5.6-sol",
        qualified_observed_model="gpt-5.6-sol",
        usage_complete_response_count=109_200,
        subscription_billed_cost_usd=0.0,
        approved_downloads=candidate_facts.approved_downloads,
    )

    production = report_module._REPORT_PRESENTATION.materialize_full_pool_production(
        full_pool_source_root=inputs["full_pool_source"],
        full_pool_manifest_sha256=inputs["full_pool_manifest_sha256"],
        historical_formal_root=inputs["historical_formal"],
        historical_study_root=inputs["historical_study"],
        presentation_bundle_dir=inputs["bundle"],
        candidate_dir=candidate,
        implementation_commit="abcdef0",
        stage_facts=stage_facts,
    )

    payload = json.loads(production.report_payload)
    assert payload["schema_version"] == "full-pool-three-lineage-report-payload-v1"
    assert payload["production_deploy_eligible"] is True
    assert payload["production_release"]["schema_version"] == (
        "full-pool-production-presentation-v1"
    )
    assert payload["production_release"]["release_id"] == "full-pool-v8-test"
    assert (
        b'<main class="full-pool-presentation" data-testid="full-pool-presentation" '
        b'data-production-deploy-eligible="true"'
    ) in production.report_html
    assert (
        b'<main class="full-pool-presentation" data-testid="full-pool-presentation" '
        b'data-production-deploy-eligible="false"'
    ) not in production.report_html
    assert len(production.report_html) < 3 * 1024 * 1024
    report_module._REPORT_PRESENTATION.validate_full_pool_production_bundle(
        production,
        candidate_dir=candidate,
        stage_facts=stage_facts,
    )
    assert _snapshot(candidate) == before


def test_candidate_rejects_nested_output_and_allows_zero_call_retry(tmp_path: Path) -> None:
    inputs = _compose_inputs(tmp_path)
    bundle = inputs["bundle"]
    assert isinstance(bundle, Path)
    nested = bundle / "nested-candidate"
    with pytest.raises(report_module._RobustnessReportPathError, match="overlap"):
        report_module._REPORT_PRESENTATION.compose_full_pool_candidate(
            full_pool_source_root=inputs["full_pool_source"],
            full_pool_manifest_sha256=inputs["full_pool_manifest_sha256"],
            historical_formal_root=inputs["historical_formal"],
            historical_study_root=inputs["historical_study"],
            presentation_bundle_dir=bundle,
            implementation_commit="abcdef0",
            destination_dir=nested,
        )
    assert not nested.exists()

    destination = tmp_path / "retry-candidate"
    destination.mkdir()
    (destination / "sentinel").write_text("operator owned\n", encoding="utf-8")
    source = inputs["full_pool_source"]
    assert isinstance(source, Path)
    source_before = _snapshot(source)
    with pytest.raises(report_module._RobustnessReportConflictError):
        report_module._REPORT_PRESENTATION.compose_full_pool_candidate(
            full_pool_source_root=source,
            full_pool_manifest_sha256=inputs["full_pool_manifest_sha256"],
            historical_formal_root=inputs["historical_formal"],
            historical_study_root=inputs["historical_study"],
            presentation_bundle_dir=bundle,
            implementation_commit="abcdef0",
            destination_dir=destination,
        )
    assert (destination / "sentinel").read_text(encoding="utf-8") == "operator owned\n"
    shutil.rmtree(destination)
    report_module._REPORT_PRESENTATION.compose_full_pool_candidate(
        full_pool_source_root=source,
        full_pool_manifest_sha256=inputs["full_pool_manifest_sha256"],
        historical_formal_root=inputs["historical_formal"],
        historical_study_root=inputs["historical_study"],
        presentation_bundle_dir=bundle,
        implementation_commit="abcdef0",
        destination_dir=destination,
    )
    assert destination.is_dir()
    assert _snapshot(source) == source_before


def test_formal_shaped_source_classification_is_preserved_in_candidate(tmp_path: Path) -> None:
    source, source_hash, _, _ = _formal_shaped_full_pool_source(tmp_path / "full-pool")
    historical_formal, historical_study, historical_candidate = _historical_candidate(
        tmp_path / "historical"
    )
    bundle = tmp_path / "bundle"
    report_module._REPORT_PRESENTATION.compose_full_pool_presentation_bundle(
        full_pool_source_root=source,
        full_pool_manifest_sha256=source_hash,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        historical_candidate_dir=historical_candidate,
        destination_dir=bundle,
    )
    candidate = tmp_path / "candidate"
    report_module._REPORT_PRESENTATION.compose_full_pool_candidate(
        full_pool_source_root=source,
        full_pool_manifest_sha256=source_hash,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        presentation_bundle_dir=bundle,
        implementation_commit="abcdef0",
        destination_dir=candidate,
    )

    payload = json.loads(
        (candidate / "concurrent_robustness_report_payload.json").read_text(encoding="utf-8")
    )
    lineage = payload["source_lineage"]["full_pool"]
    source_manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    assert lineage["source_schema_version"] == "full-pool-formal-source-v1"
    assert lineage["evidence_profile"] == "deterministic_validation_fixture"
    assert lineage["provider_calls"] == source_manifest["provider_calls"] == 0
    assert lineage["source_production_deploy_eligible"] is False
    assert payload["production_deploy_eligible"] is False


def test_post_compose_input_mutation_removes_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _compose_inputs(tmp_path)
    bundle = inputs["bundle"]
    assert isinstance(bundle, Path)
    destination = tmp_path / "candidate"
    original = report_module._validate_full_pool_candidate_directory
    calls = 0

    def mutate_then_validate(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        result = original(*args, **kwargs)
        if calls == 1:
            report = bundle / "report.html"
            report.write_bytes(report.read_bytes() + b" ")
        return result

    monkeypatch.setattr(
        report_module,
        "_validate_full_pool_candidate_directory",
        mutate_then_validate,
    )
    with pytest.raises(report_module._RobustnessReportClosureError):
        report_module._REPORT_PRESENTATION.compose_full_pool_candidate(
            full_pool_source_root=inputs["full_pool_source"],
            full_pool_manifest_sha256=inputs["full_pool_manifest_sha256"],
            historical_formal_root=inputs["historical_formal"],
            historical_study_root=inputs["historical_study"],
            presentation_bundle_dir=bundle,
            implementation_commit="abcdef0",
            destination_dir=destination,
        )
    assert not destination.exists()


def _close_candidate(
    root: Path,
    inputs: dict[str, Path | str],
    candidate: Path,
    destination: Path,
) -> evidence_module.FullPoolPresentationClosureFacts:
    return evidence_module.close_full_pool_presentation(
        repo_root=root,
        full_pool_source_root=inputs["full_pool_source"],
        full_pool_manifest_sha256=inputs["full_pool_manifest_sha256"],
        historical_formal_root=inputs["historical_formal"],
        historical_study_root=inputs["historical_study"],
        presentation_bundle_dir=inputs["bundle"],
        candidate_dir=candidate,
        destination_path=destination,
        implementation_commit="abcdef0",
    )


def test_evidence_module_atomically_closes_and_revalidates_candidate(tmp_path: Path) -> None:
    inputs, candidate = _compose_candidate(tmp_path)
    closure = tmp_path / "contracts" / "full-pool-presentation-closure.json"
    protected = (
        inputs["full_pool_source"],
        inputs["historical_formal"],
        inputs["historical_study"],
        inputs["bundle"],
        candidate,
    )
    assert all(isinstance(path, Path) for path in protected)
    before = {path: _snapshot(path) for path in protected if isinstance(path, Path)}

    facts = _close_candidate(tmp_path, inputs, candidate, closure)

    document = json.loads(closure.read_text(encoding="utf-8"))
    assert document["schema_version"] == "full-pool-three-lineage-presentation-closure-v1"
    assert document["status"] == "complete"
    assert document["implementation_commit"] == "abcdef0"
    assert document["report_payload_schema_version"] == (
        "full-pool-three-lineage-report-payload-v1"
    )
    assert document["candidate_identity_sha256"] == facts.candidate_identity_sha256
    assert document["mechanism_set_identity_sha256"] == facts.mechanism_set_identity_sha256
    assert document["trace_index_sha256"] == facts.trace_index_sha256
    assert document["provider_calls_during_closure"] == 0
    assert document["image_generation_triggered"] is False
    assert document["production_deploy_eligible"] is False
    assert all(before[path] == _snapshot(path) for path in before)

    validated = evidence_module.validate_full_pool_presentation_closure(
        repo_root=tmp_path,
        closure_path=closure,
        full_pool_source_root=inputs["full_pool_source"],
        full_pool_manifest_sha256=inputs["full_pool_manifest_sha256"],
        historical_formal_root=inputs["historical_formal"],
        historical_study_root=inputs["historical_study"],
        presentation_bundle_dir=inputs["bundle"],
        candidate_dir=candidate,
    )
    assert validated.closure_sha256 == hashlib.sha256(closure.read_bytes()).hexdigest()
    assert validated.source_lineage_identity_sha256 == document[
        "source_lineage_identity_sha256"
    ]


@pytest.mark.parametrize("mutation", ("extra-field", "candidate-bytes", "crossed-trace"))
def test_closure_rejects_mutation_and_crossed_identity(
    tmp_path: Path,
    mutation: str,
) -> None:
    inputs, candidate = _compose_candidate(tmp_path)
    closure = tmp_path / "closure.json"
    _close_candidate(tmp_path, inputs, candidate, closure)
    if mutation == "candidate-bytes":
        (candidate / "report.html").write_bytes(
            (candidate / "report.html").read_bytes() + b" "
        )
    else:
        document = json.loads(closure.read_text(encoding="utf-8"))
        if mutation == "extra-field":
            document["unexpected"] = True
        else:
            document["trace_index_sha256"] = "0" * 64
        closure.write_text(json.dumps(document) + "\n", encoding="utf-8")

    with pytest.raises(evidence_module.ConcurrentRobustnessEvidenceError):
        evidence_module.validate_full_pool_presentation_closure(
            repo_root=tmp_path,
            closure_path=closure,
            full_pool_source_root=inputs["full_pool_source"],
            full_pool_manifest_sha256=inputs["full_pool_manifest_sha256"],
            historical_formal_root=inputs["historical_formal"],
            historical_study_root=inputs["historical_study"],
            presentation_bundle_dir=inputs["bundle"],
            candidate_dir=candidate,
        )


def test_closure_failure_is_atomic_and_destination_cannot_overlap_input(tmp_path: Path) -> None:
    inputs, candidate = _compose_candidate(tmp_path)
    payload = candidate / "concurrent_robustness_report_payload.json"
    payload.write_bytes(payload.read_bytes() + b" ")
    closure = tmp_path / "failed-closure.json"
    with pytest.raises(evidence_module.ConcurrentRobustnessEvidenceError):
        _close_candidate(tmp_path, inputs, candidate, closure)
    assert not closure.exists()

    shutil.rmtree(candidate)
    inputs, candidate = _compose_candidate(tmp_path / "second")
    nested = candidate / "presentation-closure.json"
    with pytest.raises(evidence_module.ConcurrentRobustnessEvidenceError, match="overlap"):
        _close_candidate(tmp_path, inputs, candidate, nested)
    assert not nested.exists()


def test_production_evidence_rejects_formal_shaped_validation_source(tmp_path: Path) -> None:
    source, source_hash, _, _ = _formal_shaped_full_pool_source(tmp_path / "full-pool")
    historical_formal, historical_study, historical_candidate = _historical_candidate(
        tmp_path / "historical"
    )
    bundle = tmp_path / "bundle"
    report_module._REPORT_PRESENTATION.compose_full_pool_presentation_bundle(
        full_pool_source_root=source,
        full_pool_manifest_sha256=source_hash,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        historical_candidate_dir=historical_candidate,
        destination_dir=bundle,
    )
    candidate = tmp_path / "candidate"
    report_module._REPORT_PRESENTATION.compose_full_pool_candidate(
        full_pool_source_root=source,
        full_pool_manifest_sha256=source_hash,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        presentation_bundle_dir=bundle,
        implementation_commit="abcdef0",
        destination_dir=candidate,
    )
    closure = tmp_path / "closure.json"
    closure_facts = evidence_module.close_full_pool_presentation(
        repo_root=tmp_path,
        full_pool_source_root=source,
        full_pool_manifest_sha256=source_hash,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        presentation_bundle_dir=bundle,
        candidate_dir=candidate,
        destination_path=closure,
        implementation_commit="abcdef0",
    )

    with pytest.raises(
        evidence_module.ConcurrentRobustnessEvidenceError,
        match="Formal production facts",
    ):
        evidence_module.validate_full_pool_production_evidence(
            repo_root=tmp_path,
            closure_path=closure,
            full_pool_source_root=source,
            full_pool_manifest_sha256=source_hash,
            historical_formal_root=historical_formal,
            historical_study_root=historical_study,
            candidate_dir=candidate,
            implementation_commit="abcdef0",
        )

    injected = evidence_module.FullPoolFormalReleaseFacts(
        full_pool_source_path=source.resolve(),
        full_pool_source_schema_version="full-pool-formal-source-v1",
        full_pool_source_identity=closure_facts.full_pool_source_identity,
        full_pool_source_manifest_sha256=source_hash,
        full_pool_source_hash=closure_facts.full_pool_source_hash,
        full_pool_contract_sha256=str(
            closure_facts.source_lineage["full_pool"]["contract_sha256"]
        ),
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
        historical_formal_source_id=closure_facts.historical_formal_source_id,
        historical_formal_manifest_sha256=(
            closure_facts.historical_formal_manifest_sha256
        ),
        historical_formal_source_kind="formal",
        historical_formal_users=1_000,
        historical_formal_exposures=1_800,
        historical_primary_terminals=1_800,
        historical_shadow_terminals=1_800,
        historical_trace_rows=1_800,
        historical_study_path=historical_study.resolve(),
        historical_study_manifest_sha256=(
            closure_facts.robustness_study_manifest_sha256
        ),
        historical_study_root_identity_sha256=(
            closure_facts.robustness_study_root_identity_sha256
        ),
        historical_study_profile="formal_live",
        historical_study_evidence_profile="formal_live",
        historical_study_cell_count=16,
        historical_study_logical_judgments=28_800,
    )
    validated = evidence_module.validate_full_pool_production_evidence(
        repo_root=tmp_path,
        closure_path=closure,
        full_pool_source_root=source,
        full_pool_manifest_sha256=source_hash,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        candidate_dir=candidate,
        implementation_commit="abcdef0",
        formal_facts=injected,
    )
    assert validated.formal is injected
    assert validated.closure.candidate_identity_sha256 == (
        closure_facts.candidate_identity_sha256
    )
