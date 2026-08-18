from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import replace
from pathlib import Path

import pytest

from llm_abm_sim import concurrent_robustness_evidence as evidence_module
from llm_abm_sim import concurrent_robustness_release as release_module
from llm_abm_sim import concurrent_robustness_report as report_module
from llm_abm_sim.full_pool_automation import (
    AutomationExecutionManifestRequest,
    AutomationLiveGates,
    FullPoolAutomationOperator,
    create_automation_execution_manifest,
    validate_automation_execution_manifest,
)
from llm_abm_sim.full_pool_segmented_automated_recovery import (
    FullPoolSegmentedAutomatedRecovery,
)
from llm_abm_sim.full_pool_segmented_continuation import (
    _read_closed_full_pool_source_versioned,
)
from llm_abm_sim.full_pool_source_v3 import (
    FULL_POOL_RESULT_CSV,
    FULL_POOL_RESULT_LINEAGE_MARKDOWN,
    _ClosedAutomatedFullPoolSource,
    _read_closed_automated_full_pool_source,
    compose_full_pool_result_projection,
)
from llm_abm_sim.prompt_field_summary import CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION
from tests.integration.test_full_pool_automation_manifest import (
    _ContractShapedValidationAdapter,
    _head,
)
from tests.integration.test_full_pool_presentation_bundle import _historical_candidate
from tests.integration.test_full_pool_segmented_automated_recovery import (
    _automated_request,
    _LaneAdapter,
)


def _source_v3(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, str]:
    request = _automated_request(tmp_path, monkeypatch, logical_cap=90)
    result = FullPoolSegmentedAutomatedRecovery().run(
        request,
        adapter_factory=lambda _lane_id: _LaneAdapter([]),
    )
    assert result.source_root is not None
    assert result.source_manifest_sha256 is not None
    return result.source_root, result.source_manifest_sha256


def test_source_v3_consumer_recloses_persisted_nested_lineage_and_terminal_accounting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root, manifest_sha256 = _source_v3(tmp_path, monkeypatch)

    closed = _read_closed_automated_full_pool_source(
        source_root,
        manifest_sha256=manifest_sha256,
    )

    assert closed.facts.source_schema_version == "full-pool-segmented-source-v3"
    assert closed.facts.logical_judgments == 90
    assert closed.facts.primary_terminals == 90
    assert closed.facts.committed_batches == 3
    assert closed.facts.imported_durable_terminal_count == 63
    assert closed.facts.ordered_retry_pair_ids == (
        "u11:message_1:2",
        "u14:message_1:2",
        "u17:message_1:2",
        "u20:message_1:2",
        "u23:message_1:2",
        "u26:message_1:2",
        "u29:message_1:2",
    )
    assert closed.facts.settlement_terminal_pair_count == 27
    assert closed.facts.settlement_unknown_pair_ids == ()
    assert closed.facts.provider_responses == 90
    assert closed.facts.observed_model_counts == {"offline-segmented-multibatch-v1": 90}
    assert closed.facts.live_api_triggered is False
    assert closed.facts.production_deploy_eligible is False
    assert closed.facts.membership_path == source_root / "latent-v1-membership.csv"
    assert "latent-v1-membership.csv" in closed.facts.artifact_hashes
    assert closed.read_batch(0)["time_step"] == 0
    assert closed.read_batch(2)["time_step"] == 2
    dispatched = _read_closed_full_pool_source_versioned(
        source_root,
        manifest_sha256=manifest_sha256,
    )
    assert isinstance(dispatched, _ClosedAutomatedFullPoolSource)
    assert dispatched.facts == closed.facts


def test_source_v3_consumer_rejects_terminal_tamper_even_with_reclosed_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root, _manifest_sha256 = _source_v3(tmp_path, monkeypatch)
    terminal_path = source_root / "terminal_rows.jsonl"
    rows = [json.loads(line) for line in terminal_path.read_text(encoding="utf-8").splitlines()]
    rows[0]["action"] = "share" if rows[0]["action"] != "share" else "like"
    terminal_path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    manifest_path = source_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    terminal_sha256 = hashlib.sha256(terminal_path.read_bytes()).hexdigest()
    for artifact in manifest["artifacts"]:
        if artifact["relative_path"] == "terminal_rows.jsonl":
            artifact["sha256"] = terminal_sha256
            artifact["byte_length"] = terminal_path.stat().st_size
    manifest["complete_status"]["terminal_rows_sha256"] = terminal_sha256
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    reclosed_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="terminal|settlement|source-v3"):
        _read_closed_automated_full_pool_source(
            source_root,
            manifest_sha256=reclosed_hash,
        )


def test_result_projection_uses_one_nine_row_aggregation_for_csv_html_and_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root, manifest_sha256 = _source_v3(tmp_path, monkeypatch)
    closed = _read_closed_automated_full_pool_source(
        source_root,
        manifest_sha256=manifest_sha256,
    )

    projection = compose_full_pool_result_projection(closed)
    external_users = closed.facts.dataset_dir / "users.csv"
    external_users.write_text(
        external_users.read_text(encoding="utf-8").replace("class_1", "class_2", 1),
        encoding="utf-8",
    )
    replayed_projection = compose_full_pool_result_projection(closed)
    assert replayed_projection.csv_bytes == projection.csv_bytes
    assert replayed_projection.rows_sha256 == projection.rows_sha256

    assert projection.csv_filename == FULL_POOL_RESULT_CSV
    assert projection.lineage_filename == FULL_POOL_RESULT_LINEAGE_MARKDOWN
    decoded = projection.csv_bytes.decode("utf-8")
    reader = csv.DictReader(io.StringIO(decoded))
    rows = list(reader)
    assert reader.fieldnames == [
        "Run",
        "Message",
        "Segment",
        "Total Likes",
        "Total Comments",
        "Total Shares",
        "Exposure",
    ]
    assert [(row["Segment"], row["Message"], row["Run"]) for row in rows] == [
        (segment, message, "1")
        for segment in ("S1", "S2", "S3")
        for message in ("M1", "M2", "M3")
    ]
    assert sum(int(row["Exposure"]) for row in rows) == 90
    assert {row["Exposure"] for row in rows} == {"10"}
    assert projection.rows_sha256 in projection.lineage_markdown
    assert "population and model both change" in projection.lineage_markdown
    assert "historical 1,000-user sensitivity" in projection.lineage_markdown
    assert projection.html_fragment.count("<tr") == 10
    assert "Total Likes" in projection.html_fragment
    assert f'href="{FULL_POOL_RESULT_CSV}"' in projection.html_fragment
    assert f'href="{FULL_POOL_RESULT_LINEAGE_MARKDOWN}"' in projection.html_fragment


def test_report_interface_composes_and_revalidates_source_v3_delivery_without_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root, manifest_sha256 = _source_v3(tmp_path, monkeypatch)
    historical_formal, historical_study, historical_candidate = _historical_candidate(
        tmp_path / "historical"
    )
    destination = tmp_path / "source-v3-presentation"

    created = report_module._REPORT_PRESENTATION.compose_full_pool_presentation_bundle(
        full_pool_source_root=source_root,
        full_pool_manifest_sha256=manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        historical_candidate_dir=historical_candidate,
        destination_dir=destination,
    )

    assert created == destination.resolve()
    assert (created / FULL_POOL_RESULT_CSV).is_file()
    assert (created / FULL_POOL_RESULT_LINEAGE_MARKDOWN).is_file()
    report = (created / "report.html").read_text(encoding="utf-8")
    assert 'data-testid="full-pool-segment-results"' in report
    assert "population and model both change" in (
        created / FULL_POOL_RESULT_LINEAGE_MARKDOWN
    ).read_text(encoding="utf-8")
    assert 'data-production-deploy-eligible="false"' in report
    report_module._REPORT_PRESENTATION.validate_full_pool_presentation_bundle(
        created,
        full_pool_source_root=source_root,
        full_pool_manifest_sha256=manifest_sha256,
        historical_candidate_dir=historical_candidate,
    )

    candidate = tmp_path / "source-v3-candidate"
    report_module._REPORT_PRESENTATION.compose_full_pool_candidate(
        full_pool_source_root=source_root,
        full_pool_manifest_sha256=manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        presentation_bundle_dir=created,
        implementation_commit="abcdef0",
        destination_dir=candidate,
    )
    payload = json.loads(
        (candidate / "concurrent_robustness_report_payload.json").read_text(
            encoding="utf-8"
        )
    )
    source_lineage = payload["source_lineage"]["full_pool"]
    assert source_lineage["source_schema_version"] == "full-pool-segmented-source-v3"
    assert source_lineage["nested_recovery"]["settlement_schema_version"] == (
        "full-pool-durable-pair-settlement-v2"
    )
    downloads = payload["presentation"]["approved_downloads"]
    assert downloads["full_pool_segment_results_csv"] == FULL_POOL_RESULT_CSV
    assert downloads["full_pool_segment_lineage_markdown"] == (
        FULL_POOL_RESULT_LINEAGE_MARKDOWN
    )


def test_evidence_v10_rejects_manifest_driven_validation_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nested = _automated_request(tmp_path, monkeypatch, logical_cap=90)
    manifest_request = AutomationExecutionManifestRequest(
        repo_root=Path.cwd(),
        nested_recovery_plan_path=nested.nested_recovery_plan_path,
        nested_recovery_plan_sha256=nested.nested_recovery_plan_sha256,
        recovery_id="evidence-validation-source-v3",
        recovery_workspace=tmp_path / "manifest-recovery",
        manifest_path=tmp_path / "automation" / "execution-manifest.json",
        implementation_commit=_head(),
    )
    execution_manifest = create_automation_execution_manifest(manifest_request)
    result = FullPoolAutomationOperator().run(
        execution_manifest,
        gates=AutomationLiveGates(
            explicit_live_authorization=True,
            external_requests_allowed=True,
            credentials_available=True,
            provider_transport="openai-codex",
            requested_model="gpt-5.6-sol",
            subscription_billed_cost_usd=0.0,
        ),
        adapter_factory=lambda _lane_id: _ContractShapedValidationAdapter([]),
    )
    assert result.source_root is not None
    assert result.source_manifest_sha256 is not None
    historical_formal, historical_study, historical_candidate = _historical_candidate(
        tmp_path / "historical-evidence"
    )
    bundle = tmp_path / "evidence-bundle"
    report_module._REPORT_PRESENTATION.compose_full_pool_presentation_bundle(
        full_pool_source_root=result.source_root,
        full_pool_manifest_sha256=result.source_manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        historical_candidate_dir=historical_candidate,
        destination_dir=bundle,
    )
    candidate = tmp_path / "evidence-candidate"
    report_module._REPORT_PRESENTATION.compose_full_pool_candidate(
        full_pool_source_root=result.source_root,
        full_pool_manifest_sha256=result.source_manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        presentation_bundle_dir=bundle,
        implementation_commit=_head(),
        destination_dir=candidate,
    )
    closure = tmp_path / "evidence-closure.json"
    closure_facts = evidence_module.close_full_pool_presentation(
        repo_root=tmp_path,
        full_pool_source_root=result.source_root,
        full_pool_manifest_sha256=result.source_manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        presentation_bundle_dir=bundle,
        candidate_dir=candidate,
        destination_path=closure,
        implementation_commit=_head(),
    )

    with pytest.raises(
        evidence_module.ConcurrentRobustnessEvidenceError,
        match="source-v3|non-live|Validation|Formal",
    ):
        evidence_module.validate_nested_full_pool_production_evidence(
            repo_root=tmp_path,
            closure_path=closure,
            full_pool_source_root=result.source_root,
            full_pool_manifest_sha256=result.source_manifest_sha256,
            historical_formal_root=historical_formal,
            historical_study_root=historical_study,
            candidate_dir=candidate,
            automation_execution_manifest_path=execution_manifest,
            implementation_commit=_head(),
        )

    assert release_module.ROBUSTNESS_RELEASE_CONTRACT_SCHEMA_V10 == (
        "abm-report-release-contract-v10"
    )
    with pytest.raises(
        release_module.ConcurrentRobustnessReleaseError,
        match="source-v3|non-live|Validation|Formal",
    ):
        release_module.promote_concurrent_robustness_release(
            repo_root=tmp_path,
            formal_root=historical_formal,
            study_root=historical_study,
            candidate_dir=candidate,
            destination_dir=tmp_path / "forbidden-v10-release",
            release_contract_path=tmp_path / "forbidden-v10-contract.json",
            release_id="forbidden-validation-v10",
            presentation_closure_path=closure,
            full_pool_source_root=result.source_root,
            full_pool_manifest_sha256=result.source_manifest_sha256,
            automation_execution_manifest_path=execution_manifest,
            implementation_commit=_head(),
        )

    closed = _read_closed_automated_full_pool_source(
        result.source_root,
        manifest_sha256=result.source_manifest_sha256,
    )
    automated = replace(
        closed.facts,
        configuration_profile="production",
        evidence_profile="formal_live",
        provider_transport=evidence_module.FULL_POOL_FORMAL_TRANSPORT,
        adapter_identity=evidence_module.FULL_POOL_FORMAL_ADAPTER_IDENTITY,
        requested_model=evidence_module.FULL_POOL_FORMAL_REQUESTED_MODEL,
        qualified_observed_model=(
            evidence_module.FULL_POOL_FORMAL_REQUIRED_OBSERVED_MODEL
        ),
        prompt_variant_id="P0",
        prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
        prompt_canonical_hash=(
            evidence_module.CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.resolve(
                CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION
            ).canonical_hash
        ),
        distinct_users=36_400,
        eligible_pairs=109_200,
        exposures=109_200,
        primary_terminals=109_200,
        committed_batches=30,
        candidate_ranking_rows=1_691_730,
        provider_failed_terminals=0,
        logical_judgments=109_200,
        physical_attempts=110_051,
        physical_attempt_cap=120_120,
        provider_responses=109_200,
        successful_decisions=109_200,
        external_request_invocations=110_030,
        observed_model_counts={"gpt-5.6-sol": 109_200},
        usage_complete_response_count=109_200,
        usage_missing_response_count=0,
        usage_malformed_response_count=0,
        imported_durable_terminal_count=90_061,
        historical_logical_count=90_068,
        fresh_logical_count=19_132,
        historical_physical_attempts=90_891,
        historical_uncertainty_physical_charge=21,
        new_uncertainty_physical_charge=0,
        retry_physical_attempts=7,
        reconciliation_physical_attempts=0,
        continuation_physical_attempts=19_132,
        settlement_dispatched_pair_count=19_139,
        settlement_terminal_pair_count=19_139,
        settlement_unknown_pair_ids=(),
        live_api_triggered=True,
        production_deploy_eligible=False,
    )
    formal = replace(
        evidence_module._segmented_formal_release_facts(
            closure_facts,
            automated,  # type: ignore[arg-type]
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
    projection = compose_full_pool_result_projection(closed)
    injected = evidence_module.NestedFullPoolProductionEvidenceFacts(
        closure=closure_facts,
        formal=formal,
        automated=automated,
        execution_manifest=validate_automation_execution_manifest(execution_manifest),
        result_projection={
            "schema_version": projection.schema_version,
            "row_count": 9,
            "rows_sha256": projection.rows_sha256,
            "csv_sha256": projection.csv_sha256,
            "lineage_sha256": projection.lineage_sha256,
            "segment_denominators": {"S1": 15_616, "S2": 15_070, "S3": 5_714},
            "total_exposure": 109_200,
        },
    )
    monkeypatch.setattr(
        release_module._evidence,
        "validate_nested_full_pool_production_evidence",
        lambda **_kwargs: injected,
    )
    destination = tmp_path / "typed-fixture-v10-release"
    contract_path = tmp_path / "typed-fixture-v10-contract.json"
    promoted = release_module.promote_concurrent_robustness_release(
        repo_root=tmp_path,
        formal_root=historical_formal,
        study_root=historical_study,
        candidate_dir=candidate,
        destination_dir=destination,
        release_contract_path=contract_path,
        release_id="typed-fixture-v10",
        presentation_closure_path=closure,
        full_pool_source_root=result.source_root,
        full_pool_manifest_sha256=result.source_manifest_sha256,
        automation_execution_manifest_path=execution_manifest,
        implementation_commit=_head(),
    )
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    assert promoted.source_dir == destination.resolve()
    assert contract["schema_version"] == "abm-report-release-contract-v10"
    assert set(contract) == release_module._RELEASE_CONTRACT_V10_FIELDS
    assert contract["nested_source_facts"]["source_schema_version"] == (
        "full-pool-segmented-source-v3"
    )
    assert contract["settlement_v2_facts"]["schema_version"] == (
        "full-pool-durable-pair-settlement-v2"
    )
    assert contract["result_projection_facts"]["total_exposure"] == 109_200
    assert contract["production_deploy_eligible"] is True
    assert (
        '<meta name="abm-release-contract" content="abm-report-release-contract-v10">'
        in (destination / "report.html").read_text(encoding="utf-8")
    )
    validated = release_module.validate_concurrent_robustness_production_release(
        repo_root=tmp_path,
        contract_document=contract,
        source_dir=destination,
    )
    assert validated["schema_version"] == "abm-report-release-contract-v10"
    assert validated["sampling_status"] == (
        "persisted_full_pool_automated_nested_formal_run"
    )
