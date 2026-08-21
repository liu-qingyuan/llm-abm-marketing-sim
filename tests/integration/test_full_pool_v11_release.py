from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from llm_abm_sim import concurrent_robustness_evidence as evidence_module
from llm_abm_sim import concurrent_robustness_release as release_module
from llm_abm_sim import concurrent_robustness_report as report_module
from llm_abm_sim.full_pool_source_v3 import (
    FULL_POOL_RESULT_CSV,
    FULL_POOL_RESULT_LINEAGE_MARKDOWN,
)
from llm_abm_sim.full_pool_source_v4 import read_closed_strict_full_pool_source
from llm_abm_sim.full_pool_strict_operator import (
    StrictFreshAutomationOperator,
    StrictFreshLiveGates,
    create_strict_fresh_execution_manifest,
    validate_strict_fresh_execution_manifest,
)
from tests.integration.test_full_pool_presentation_bundle import _historical_candidate
from tests.integration.test_full_pool_strict_operator import _manifest_request
from tests.integration.test_full_pool_strict_replay import _CompleteEvidenceStrictAdapter


def _validation_source_v4(tmp_path: Path) -> tuple[Path, str]:
    request = _manifest_request(tmp_path / "strict")
    manifest_path = create_strict_fresh_execution_manifest(request)
    result = StrictFreshAutomationOperator().run(
        manifest_path,
        gates=StrictFreshLiveGates(
            explicit_live_authorization=True,
            external_requests_allowed=True,
            credentials_available=True,
            provider_transport="openai-codex",
            requested_model="gpt-5.6-sol",
            subscription_billed_cost_usd=0.0,
        ),
        adapter_factory=lambda lane_id: _CompleteEvidenceStrictAdapter(lane_id),
    )
    assert result.source_root is not None
    assert result.source_manifest_sha256 is not None
    return result.source_root, result.source_manifest_sha256


def test_report_composes_source_v4_projection_without_provider_calls(tmp_path: Path) -> None:
    source_root, source_manifest_sha256 = _validation_source_v4(tmp_path)
    historical_formal, historical_study, historical_candidate = _historical_candidate(tmp_path / "historical")
    destination = tmp_path / "source-v4-presentation"

    created = report_module._REPORT_PRESENTATION.compose_full_pool_presentation_bundle(
        full_pool_source_root=source_root,
        full_pool_manifest_sha256=source_manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        historical_candidate_dir=historical_candidate,
        destination_dir=destination,
    )

    assert created == destination.resolve()
    report = (created / "report.html").read_text(encoding="utf-8")
    lineage = (created / FULL_POOL_RESULT_LINEAGE_MARKDOWN).read_text(encoding="utf-8")
    assert (created / FULL_POOL_RESULT_CSV).is_file()
    assert 'data-testid="full-pool-segment-table"' in report
    assert ".full-pool-download-list li { min-width: 0;" in report
    assert ".full-pool-download-link { overflow-wrap: anywhere; word-break: break-word; }" in report
    assert "strict fresh trajectory" in report
    assert "three historical Provider failures" in report
    assert "旧 mixed trajectory 未参与结果" in lineage
    assert "三个 historical Provider failures" in lineage
    report_module._REPORT_PRESENTATION.validate_full_pool_presentation_bundle(
        created,
        full_pool_source_root=source_root,
        full_pool_manifest_sha256=source_manifest_sha256,
        historical_candidate_dir=historical_candidate,
    )


def test_report_candidate_binds_strict_source_v4_and_projection(tmp_path: Path) -> None:
    source_root, source_manifest_sha256 = _validation_source_v4(tmp_path)
    historical_formal, historical_study, historical_candidate = _historical_candidate(tmp_path / "historical")
    bundle = report_module._REPORT_PRESENTATION.compose_full_pool_presentation_bundle(
        full_pool_source_root=source_root,
        full_pool_manifest_sha256=source_manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        historical_candidate_dir=historical_candidate,
        destination_dir=tmp_path / "source-v4-presentation",
    )
    candidate = tmp_path / "source-v4-candidate"

    report_module._REPORT_PRESENTATION.compose_full_pool_candidate(
        full_pool_source_root=source_root,
        full_pool_manifest_sha256=source_manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        presentation_bundle_dir=bundle,
        implementation_commit="abcdef0",
        destination_dir=candidate,
    )

    payload = json.loads((candidate / "concurrent_robustness_report_payload.json").read_text(encoding="utf-8"))
    lineage = payload["source_lineage"]["full_pool"]
    assert lineage["source_schema_version"] == "full-pool-segmented-source-v4"
    assert lineage["strict_fresh_execution"]["fresh_from_batch_zero"] is True
    assert lineage["strict_fresh_execution"]["rejected_history"]["rejection_reason"] == (
        "validation_mixed_provider_evidence"
    )
    assert lineage["provider_accounting"]["successful_decisions"] == 24
    downloads = payload["presentation"]["approved_downloads"]
    assert downloads["full_pool_segment_results_csv"] == FULL_POOL_RESULT_CSV
    assert downloads["full_pool_segment_lineage_markdown"] == (FULL_POOL_RESULT_LINEAGE_MARKDOWN)


def test_evidence_v11_rejects_validation_source_v4_from_persisted_bytes(
    tmp_path: Path,
) -> None:
    source_root, source_manifest_sha256 = _validation_source_v4(tmp_path)
    source = read_closed_strict_full_pool_source(
        source_root,
        manifest_sha256=source_manifest_sha256,
    )
    assert source.facts.implementation_commit is not None
    implementation_commit = source.facts.implementation_commit
    historical_formal, historical_study, historical_candidate = _historical_candidate(tmp_path / "historical")
    bundle = report_module._REPORT_PRESENTATION.compose_full_pool_presentation_bundle(
        full_pool_source_root=source_root,
        full_pool_manifest_sha256=source_manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        historical_candidate_dir=historical_candidate,
        destination_dir=tmp_path / "source-v4-presentation",
    )
    candidate = report_module._REPORT_PRESENTATION.compose_full_pool_candidate(
        full_pool_source_root=source_root,
        full_pool_manifest_sha256=source_manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        presentation_bundle_dir=bundle,
        implementation_commit=implementation_commit,
        destination_dir=tmp_path / "source-v4-candidate",
    )
    closure_path = tmp_path / "source-v4-presentation-closure.json"
    evidence_module.close_full_pool_presentation(
        repo_root=tmp_path,
        full_pool_source_root=source_root,
        full_pool_manifest_sha256=source_manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        presentation_bundle_dir=bundle,
        candidate_dir=candidate,
        destination_path=closure_path,
        implementation_commit=implementation_commit,
    )

    with pytest.raises(
        evidence_module.ConcurrentRobustnessEvidenceError,
        match="source-v4|Validation|production|Formal",
    ):
        evidence_module.validate_strict_full_pool_production_evidence(
            repo_root=tmp_path,
            closure_path=closure_path,
            full_pool_source_root=source_root,
            full_pool_manifest_sha256=source_manifest_sha256,
            historical_formal_root=historical_formal,
            historical_study_root=historical_study,
            candidate_dir=candidate,
            fresh_execution_manifest_path=source.facts.execution_manifest_path,
            implementation_commit=implementation_commit,
        )


def test_release_v11_rejects_validation_source_before_publication(tmp_path: Path) -> None:
    source_root, source_manifest_sha256 = _validation_source_v4(tmp_path)
    source = read_closed_strict_full_pool_source(
        source_root,
        manifest_sha256=source_manifest_sha256,
    )
    assert source.facts.implementation_commit is not None
    assert source.facts.execution_manifest_path is not None
    implementation_commit = source.facts.implementation_commit
    historical_formal, historical_study, historical_candidate = _historical_candidate(tmp_path / "historical")
    bundle = report_module._REPORT_PRESENTATION.compose_full_pool_presentation_bundle(
        full_pool_source_root=source_root,
        full_pool_manifest_sha256=source_manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        historical_candidate_dir=historical_candidate,
        destination_dir=tmp_path / "source-v4-presentation",
    )
    candidate = report_module._REPORT_PRESENTATION.compose_full_pool_candidate(
        full_pool_source_root=source_root,
        full_pool_manifest_sha256=source_manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        presentation_bundle_dir=bundle,
        implementation_commit=implementation_commit,
        destination_dir=tmp_path / "source-v4-candidate",
    )
    closure_path = tmp_path / "source-v4-presentation-closure.json"
    evidence_module.close_full_pool_presentation(
        repo_root=tmp_path,
        full_pool_source_root=source_root,
        full_pool_manifest_sha256=source_manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        presentation_bundle_dir=bundle,
        candidate_dir=candidate,
        destination_path=closure_path,
        implementation_commit=implementation_commit,
    )
    destination = tmp_path / "forbidden-v11-release"
    contract_path = tmp_path / "forbidden-v11-contract.json"

    assert release_module.ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V11 == ("abm-report-release-contract-v11")
    with pytest.raises(
        release_module.ConcurrentRobustnessReleaseError,
        match="source-v4|Validation|production|Formal",
    ):
        release_module.promote_concurrent_robustness_release(
            repo_root=tmp_path,
            formal_root=historical_formal,
            study_root=historical_study,
            candidate_dir=candidate,
            destination_dir=destination,
            release_contract_path=contract_path,
            release_id="forbidden-validation-v11",
            presentation_closure_path=closure_path,
            full_pool_source_root=source_root,
            full_pool_manifest_sha256=source_manifest_sha256,
            fresh_execution_manifest_path=source.facts.execution_manifest_path,
            implementation_commit=implementation_commit,
        )
    assert not destination.exists()
    assert not contract_path.exists()


def test_release_v11_materializes_and_round_trips_typed_formal_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    origin_source_root, source_manifest_sha256 = _validation_source_v4(tmp_path)
    source_root = tmp_path / "published-source-v4"
    shutil.copytree(origin_source_root, source_root)
    closed = read_closed_strict_full_pool_source(
        source_root,
        manifest_sha256=source_manifest_sha256,
    )
    assert closed.facts.implementation_commit is not None
    assert closed.facts.execution_manifest_path is not None
    implementation_commit = closed.facts.implementation_commit
    execution = validate_strict_fresh_execution_manifest(closed.facts.execution_manifest_path)
    historical_formal, historical_study, historical_candidate = _historical_candidate(tmp_path / "historical")
    bundle = report_module._REPORT_PRESENTATION.compose_full_pool_presentation_bundle(
        full_pool_source_root=source_root,
        full_pool_manifest_sha256=source_manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        historical_candidate_dir=historical_candidate,
        destination_dir=tmp_path / "source-v4-presentation",
    )
    candidate = report_module._REPORT_PRESENTATION.compose_full_pool_candidate(
        full_pool_source_root=source_root,
        full_pool_manifest_sha256=source_manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        presentation_bundle_dir=bundle,
        implementation_commit=implementation_commit,
        destination_dir=tmp_path / "source-v4-candidate",
    )
    closure_path = tmp_path / "source-v4-presentation-closure.json"
    closure = evidence_module.close_full_pool_presentation(
        repo_root=tmp_path,
        full_pool_source_root=source_root,
        full_pool_manifest_sha256=source_manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        presentation_bundle_dir=bundle,
        candidate_dir=candidate,
        destination_path=closure_path,
        implementation_commit=implementation_commit,
    )
    strict = replace(
        closed.facts,
        profile="production",
        distinct_users=36_400,
        logical_pairs=109_200,
        committed_batches=30,
        candidate_rows=1_691_730,
        provider_failed_final_count=0,
        provider_responses=109_200,
        successful_decisions=109_200,
        external_request_invocations=109_200,
        observed_model_counts={"gpt-5.6-sol": 109_200},
        usage_complete_response_count=109_200,
        usage_missing_response_count=0,
        usage_malformed_response_count=0,
        settled_actual_attempts=109_200,
        dispatched_without_settlement_uncertainty=0,
        charged_physical_attempts=109_200,
        physical_cap=120_120,
        original_dispatch_count=109_200,
        reconciliation_dispatch_count=0,
        maximum_dispatches_for_one_pair=1,
        maximum_request_invocations_for_one_dispatch=1,
        segment_denominators={"class_1": 15_616, "class_2": 15_070, "class_3": 5_714},
        rejected_history={
            "source_root": str(closed.facts.rejected_history["source_root"]),
            "manifest_sha256": "11416c6ba56c6b0ea70daeb8ed27fbf74a1937ee5eb3e17f10a657fe6a7c08dc",
            "rejection_reason": "validation_mixed_provider_evidence",
        },
        production_topology=True,
        production_deploy_eligible=True,
    )
    provider_contract_sha256 = str(closed.manifest["provider_contract_sha256"])
    formal = replace(
        evidence_module._strict_formal_release_facts(
            closure,
            strict,
            provider_contract_sha256=provider_contract_sha256,
        ),
        historical_formal_source_kind="formal",
        historical_formal_users=1_000,
        historical_formal_exposures=1_800,
        historical_primary_terminals=1_800,
        historical_shadow_terminals=1_800,
        historical_trace_rows=1_800,
        historical_study_profile="formal_live",
        historical_study_evidence_profile="formal_live",
        historical_study_cell_count=16,
        historical_study_logical_judgments=28_800,
    )
    projection = {
        "schema_version": "full-pool-segment-result-projection-v1",
        "row_count": 9,
        "rows_sha256": "1" * 64,
        "csv_sha256": "2" * 64,
        "lineage_sha256": "3" * 64,
        "segment_denominators": {"S1": 15_616, "S2": 15_070, "S3": 5_714},
        "total_exposure": 109_200,
    }
    injected = evidence_module.StrictFullPoolProductionEvidenceFacts(
        closure=closure,
        formal=formal,
        strict_source=strict,
        execution_manifest=execution,
        result_projection=projection,
    )
    monkeypatch.setattr(
        release_module._evidence,
        "validate_strict_full_pool_production_evidence",
        lambda **_kwargs: injected,
    )
    destination = tmp_path / "typed-formal-v11-release"
    contract_path = tmp_path / "typed-formal-v11-contract.json"

    promoted = release_module.promote_concurrent_robustness_release(
        repo_root=tmp_path,
        formal_root=historical_formal,
        study_root=historical_study,
        candidate_dir=candidate,
        destination_dir=destination,
        release_contract_path=contract_path,
        release_id="typed-formal-v11",
        presentation_closure_path=closure_path,
        full_pool_source_root=source_root,
        full_pool_manifest_sha256=source_manifest_sha256,
        fresh_execution_manifest_path=closed.facts.execution_manifest_path,
        implementation_commit=implementation_commit,
    )

    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    assert promoted.source_dir == destination.resolve()
    assert contract["schema_version"] == "abm-report-release-contract-v11"
    assert set(contract) == release_module._RELEASE_CONTRACT_V11_FIELDS
    assert contract["strict_source_facts"]["logical_judgments"] == 109_200
    assert contract["result_projection_facts"]["total_exposure"] == 109_200
    assert contract["execution_handoff"]["provider_calls_during_composition"] == 0
    assert contract["execution_handoff"]["operational_authorization_required"] is True
    assert contract["execution_handoff"]["source_v4_directory"] == str(source_root.resolve())
    assert contract["execution_handoff"]["runtime_workspace"] == str(
        execution.replay_request.workspace
    )
    assert contract["production_deploy_eligible"] is True
    assert (destination / FULL_POOL_RESULT_CSV).is_file()
    assert (destination / FULL_POOL_RESULT_LINEAGE_MARKDOWN).is_file()
    assert '<meta name="abm-release-contract" content="abm-report-release-contract-v11">' in (
        destination / "report.html"
    ).read_text(encoding="utf-8")
    validated = release_module.validate_concurrent_robustness_production_release(
        repo_root=tmp_path,
        contract_document=contract,
        source_dir=destination,
    )
    assert validated["schema_version"] == "abm-report-release-contract-v11"
    assert validated["sampling_status"] == "persisted_strict_fresh_full_pool_formal_run"

    masquerade = json.loads(json.dumps(contract))
    masquerade["schema_version"] = "abm-report-release-contract-v10"
    with pytest.raises(
        release_module.ConcurrentRobustnessReleaseError,
        match="v10|schema-confused|fields",
    ):
        release_module.validate_concurrent_robustness_production_release(
            repo_root=tmp_path,
            contract_document=masquerade,
            source_dir=destination,
        )
    for field, value in (
        ("usage_missing_response_count", 1),
        ("physical_cap", 120_119),
    ):
        tampered = json.loads(json.dumps(contract))
        tampered["strict_source_facts"][field] = value
        with pytest.raises(
            release_module.ConcurrentRobustnessReleaseError,
            match="crossed|source|usage|physical",
        ):
            release_module.validate_concurrent_robustness_production_release(
                repo_root=tmp_path,
                contract_document=tampered,
                source_dir=destination,
            )
    projection_tamper = json.loads(json.dumps(contract))
    projection_tamper["result_projection_facts"]["total_exposure"] = 109_199
    with pytest.raises(
        release_module.ConcurrentRobustnessReleaseError,
        match="projection|crossed",
    ):
        release_module.validate_concurrent_robustness_production_release(
            repo_root=tmp_path,
            contract_document=projection_tamper,
            source_dir=destination,
        )
    handoff_tamper = json.loads(json.dumps(contract))
    handoff_tamper["execution_handoff"]["requested_model"] = "gpt-5.6-codex"
    with pytest.raises(
        release_module.ConcurrentRobustnessReleaseError,
        match="handoff|crossed",
    ):
        release_module.validate_concurrent_robustness_production_release(
            repo_root=tmp_path,
            contract_document=handoff_tamper,
            source_dir=destination,
        )


def test_zero_call_execution_handoff_binds_manifest_budget_and_workspace(
    tmp_path: Path,
) -> None:
    base = _manifest_request(tmp_path)
    request = replace(
        base,
        manifest_path=base.repo_root / "handoff" / "strict-fresh-execution.json",
    )
    manifest = create_strict_fresh_execution_manifest(request)

    handoff = release_module.compose_strict_full_pool_v11_execution_handoff(
        repo_root=request.repo_root,
        fresh_execution_manifest_path=manifest,
        implementation_commit=request.implementation_commit,
        release_id="strict-formal-v11",
    )

    assert handoff["implementation_commit"] == request.implementation_commit
    assert handoff["fresh_execution_manifest_sha256"] == (
        validate_strict_fresh_execution_manifest(manifest).manifest_sha256
    )
    assert handoff["provider_transport"] == "openai-codex"
    assert handoff["requested_model"] == "gpt-5.6-sol"
    assert handoff["logical_call_budget"] == 24
    assert handoff["physical_call_budget"] == 120_120
    assert handoff["fee_budget_usd"] == 0.0
    assert handoff["operator_workspace"] == str(request.operator_workspace)
    assert handoff["operational_authorization_issue"] == 205
    assert handoff["operational_authorization_required"] is True
    assert handoff["artifact_does_not_confer_authorization"] is True
    assert handoff["provider_calls_during_composition"] == 0
    assert handoff["deployment_triggered"] is False
    assert not request.operator_workspace.exists()
