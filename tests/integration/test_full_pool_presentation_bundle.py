from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from llm_abm_sim import ConcurrentRobustnessStudy
from llm_abm_sim import concurrent_robustness_report as report_module
from llm_abm_sim.concurrent_message_mechanism_presentation import _MECHANISM_PRESENTATION
from llm_abm_sim.full_pool_formal_experiment import FullPoolFormalExperiment, FullPoolRunStatus
from llm_abm_sim.full_pool_two_stage_replay import (
    FullPoolTwoStageReplay,
    FullPoolTwoStageReplayRequest,
)
from tests.integration.test_concurrent_message_experiment_runner import (
    _install_deterministic_robustness_cell_fixture,
    _make_validation_report_source,
    _robustness_manifest_for_source,
)
from tests.integration.test_full_pool_formal_experiment import (
    _contract,
    _DeterministicPrimaryAdapter,
    _fixture_dataset,
    _formal_execution_contract,
    _formal_validation_adapter,
    _FormalValidationProviderClient,
)
from tests.integration.test_full_pool_two_stage_replay import _source_v4

_HISTORICAL_MERMAID = {
    "mechanism-sample-first.mmd",
    "mechanism-pair-formation.mmd",
    "mechanism-independent-delivery.mmd",
    "mechanism-exposure-decisions.mmd",
    "mechanism-feedback-boundary.mmd",
    "real-batch-mechanism.mmd",
    "prompt-model-factorial.mmd",
}


def _snapshot(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def _historical_candidate(root: Path) -> tuple[Path, Path, Path]:
    formal = _make_validation_report_source(root, "historical-formal")
    manifest = _robustness_manifest_for_source(formal, output_identity="full-pool-presentation-history")
    workspace = root / "historical-workspace"
    v1_candidate = root / "historical-v1-candidate"
    v2_candidate = root / "historical-v2-candidate"
    study = ConcurrentRobustnessStudy()
    study.run(manifest, None, workspace)
    _install_deterministic_robustness_cell_fixture(workspace, manifest)
    completed = study.run(manifest, None, workspace, report_destination=v1_candidate)
    assert completed.study_root is not None
    report_module._REPORT_PRESENTATION.compose_presentation_candidate(
        formal_root=formal,
        study_root=completed.study_root,
        candidate_dir=v1_candidate,
        destination_dir=v2_candidate,
    )
    return formal, completed.study_root, v2_candidate


def _full_pool_source(root: Path) -> tuple[Path, str]:
    dataset = _fixture_dataset(root)
    identity = "full-pool-validation-v1-presentation"
    source = root / "sources" / identity
    result = FullPoolFormalExperiment().run(
        _contract(dataset, output_identity=identity),
        _DeterministicPrimaryAdapter(),
        source,
    )
    assert result.status is FullPoolRunStatus.COMPLETE
    assert result.manifest_sha256 is not None
    return source, result.manifest_sha256


def _realized_full_pool_source(root: Path) -> tuple[Path, str]:
    upstream, manifest_sha256, source_identity = _source_v4(root / "upstream")
    output = root / "realized-source"
    result = FullPoolTwoStageReplay().run_and_close(
        FullPoolTwoStageReplayRequest(
            source_root=upstream,
            source_manifest_sha256=manifest_sha256,
            source_identity=source_identity,
            output_dir=output,
        )
    )
    return output, result.manifest_sha256


def _formal_shaped_full_pool_source(root: Path) -> tuple[Path, str, Path, Path]:
    dataset = _fixture_dataset(root)
    identity = "full-pool-validation-v1-formal-presentation"
    source = root / "sources" / identity
    base_contract = _contract(dataset, output_identity=identity)
    execution = _formal_execution_contract(base_contract, source)
    contract = base_contract.model_copy(update={"formal_execution": execution})
    result = FullPoolFormalExperiment().run(
        contract,
        _formal_validation_adapter(_FormalValidationProviderClient()),
        source,
    )
    assert result.status is FullPoolRunStatus.COMPLETE
    assert result.manifest_sha256 is not None
    return (
        source,
        result.manifest_sha256,
        execution.operational_root,
        execution.authorization.artifact_path.parent,
    )


def test_report_interface_composes_a_closed_non_promotable_full_pool_bundle(tmp_path: Path) -> None:
    full_pool_source, full_pool_manifest_sha256 = _full_pool_source(tmp_path / "full-pool")
    historical_formal, historical_study, historical_candidate = _historical_candidate(tmp_path / "historical")
    destination = tmp_path / "presentation-bundle"
    protected = (full_pool_source, historical_formal, historical_study, historical_candidate)
    before = {root: _snapshot(root) for root in protected}

    created = report_module._REPORT_PRESENTATION.compose_full_pool_presentation_bundle(
        full_pool_source_root=full_pool_source,
        full_pool_manifest_sha256=full_pool_manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        historical_candidate_dir=historical_candidate,
        destination_dir=destination,
    )

    assert created == destination.resolve()
    assert all(before[root] == _snapshot(root) for root in protected)
    assert not (destination / "artifact_manifest.json").exists()
    assert not (destination / "concurrent_robustness_report_payload.json").exists()
    assert not list(destination.glob("*closure*"))
    assert not list(destination.glob("*release-contract*"))

    mermaid_paths = {path.relative_to(destination).as_posix(): path.read_bytes() for path in destination.rglob("*.mmd")}
    assert {Path(path).name for path in mermaid_paths} == _HISTORICAL_MERMAID | {"full-pool-mechanism.mmd"}
    assert len(mermaid_paths) == 8
    for filename in _HISTORICAL_MERMAID:
        assert mermaid_paths[f"historical-1000/{filename}"] == (historical_candidate / filename).read_bytes()
    full_pool_master = _MECHANISM_PRESENTATION.build_full_pool_master().mermaid_artifacts[0]
    assert mermaid_paths["full-pool-mechanism.mmd"] == full_pool_master.payload

    report_html = (destination / "report.html").read_text(encoding="utf-8")
    assert (destination / "report.html").stat().st_size < 3 * 1024 * 1024
    assert 'data-testid="full-pool-presentation"' in report_html
    assert 'data-production-deploy-eligible="false"' in report_html
    assert 'data-provider-calls-during-composition="0"' in report_html
    assert 'data-image-generation-triggered="false"' in report_html
    assert 'data-canonical-deployment-triggered="false"' in report_html
    assert 'data-testid="full-pool-main-experiment"' in report_html
    assert 'data-testid="historical-sensitivity-1000"' in report_html
    assert "36,400" in report_html
    assert "109,200" in report_html
    assert "1,214" in report_html and "1,194" in report_html
    assert "actual-users=7" in report_html
    assert "actual-primary-terminals=21" in report_html
    assert "3-batch Validation 投放轨迹" in report_html
    assert "3-batch Validation delivery trajectory" in report_html
    assert "ranking changes exposure timing and order only" in report_html
    assert "population and requested model both change" in report_html
    assert "production_deploy_eligible=false" in report_html
    assert "full-pool-validation-source-v1" in report_html
    assert "full-pool-trace-index-v1" in report_html
    assert 'data-testid="full-pool-trace-pagination"' in report_html
    assert 'data-testid="full-pool-trace-page-status"' in report_html
    assert 'data-full-pool-trace-page="previous"' in report_html
    assert 'data-full-pool-trace-page="next"' in report_html
    assert "full-pool-trace-inline-data" not in report_html
    first_terminal = json.loads((full_pool_source / "terminal_rows.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert first_terminal["terminal_row_id"] not in report_html
    assert "https://cdn" not in report_html
    assert "mermaid.min.js" not in report_html

    index_path = destination / "trace" / "full-pool-trace-index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert index["schema_version"] == "full-pool-trace-index-v1"
    assert index["source_manifest_sha256"] == full_pool_manifest_sha256
    assert index["terminal_count"] == 21
    assert len(index["partitions"]) == 9
    assert [row["message_id"] for row in index["partitions"]] == [
        message_id for message_id in ("message_1", "message_2", "message_3") for _ in range(3)
    ]
    terminal_ids: list[str] = []
    for entry in index["partitions"]:
        partition_path = destination / entry["relative_path"]
        payload = partition_path.read_bytes()
        assert hashlib.sha256(payload).hexdigest() == entry["sha256"]
        partition = json.loads(payload)
        assert len(partition["rows"]) == entry["row_count"]
        terminal_ids.extend(row["terminal_row_id"] for row in partition["rows"])
    source_terminal_ids = {
        json.loads(line)["terminal_row_id"]
        for line in (full_pool_source / "terminal_rows.jsonl").read_text(encoding="utf-8").splitlines()
    }
    assert len(terminal_ids) == len(set(terminal_ids)) == 21
    assert set(terminal_ids) == source_terminal_ids

    assert _snapshot(destination / "full-pool-source") == before[full_pool_source]
    assert _snapshot(destination / "historical-1000") == before[historical_candidate]
    report_module._REPORT_PRESENTATION.validate_full_pool_presentation_bundle(
        destination,
        full_pool_source_root=full_pool_source,
        full_pool_manifest_sha256=full_pool_manifest_sha256,
        historical_candidate_dir=historical_candidate,
    )


def test_report_interface_composes_realized_facts_and_two_stage_mechanism(
    tmp_path: Path,
) -> None:
    realized_source, realized_manifest_sha256 = _realized_full_pool_source(
        tmp_path / "full-pool-realized"
    )
    historical_formal, historical_study, historical_candidate = _historical_candidate(
        tmp_path / "historical-realized"
    )
    destination = tmp_path / "realized-presentation-bundle"
    protected = (realized_source, historical_formal, historical_study, historical_candidate)
    before = {root: _snapshot(root) for root in protected}

    created = report_module._REPORT_PRESENTATION.compose_full_pool_presentation_bundle(
        full_pool_source_root=realized_source,
        full_pool_manifest_sha256=realized_manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        historical_candidate_dir=historical_candidate,
        destination_dir=destination,
    )

    assert created == destination.resolve()
    assert all(before[root] == _snapshot(root) for root in protected)
    assert _snapshot(destination / "full-pool-source") == before[realized_source]
    assert _snapshot(destination / "historical-1000") == before[historical_candidate]

    two_stage_master = _MECHANISM_PRESENTATION.build_full_pool_two_stage_master().mermaid_artifacts[0]
    legacy_master = _MECHANISM_PRESENTATION.build_full_pool_master().mermaid_artifacts[0]
    assert (destination / "full-pool-mechanism.mmd").read_bytes() == two_stage_master.payload
    assert two_stage_master.payload != legacy_master.payload

    terminals = [
        json.loads(line)
        for line in (realized_source / "realized-terminal-rows.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    pairs = [
        json.loads(line)
        for line in (realized_source / "pair-rows.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    commits = [
        json.loads(line)
        for line in (realized_source / "batch-commits.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    realized_engagements = sum(row["realized_engage"] is True for row in terminals)
    exposures = len(terminals)
    report_html = (destination / "report.html").read_text(encoding="utf-8")
    assert 'data-presentation-semantics="two_stage_realized"' in report_html
    assert 'data-source-classification="nonproduction_two_stage_validation"' in report_html
    assert 'data-production-deploy-eligible="false"' in report_html
    assert 'data-testid="full-pool-realized-headline"' in report_html
    assert f"{realized_engagements} / {exposures}" in report_html
    assert 'data-testid="full-pool-overall-result"' in report_html
    assert 'data-testid="full-pool-message-result-table"' in report_html
    assert 'data-testid="full-pool-segment-result-table"' in report_html
    assert 'data-testid="full-pool-segment-table"' in report_html
    assert report_html.count('data-result-scope="segment-message"') == 9
    assert 'data-testid="full-pool-probability-contract"' in report_html
    assert "raw provider_probability mean" in report_html
    assert "sum(provider_engage × provider_probability) / exposures" in report_html
    s1_m1 = [
        terminal
        for pair, terminal in zip(pairs, terminals, strict=True)
        if pair["latent_class"] == "class_1" and pair["message_id"] == "message_1"
    ]
    raw_probability = sum(float(row["provider_probability"]) for row in s1_m1) / len(s1_m1)
    effective_expectation = sum(
        float(row["provider_probability"]) if row["provider_engage"] else 0.0
        for row in s1_m1
    ) / len(s1_m1)
    assert (
        f'data-probability-group="segment-message" data-segment="S1" data-message="M1">'
        f'<th scope="row">S1 × M1</th><td>{raw_probability * 100:.2f}%</td>'
        f'<td>{effective_expectation * 100:.2f}%</td>'
    ) in report_html
    assert 'data-testid="full-pool-feedback-trajectory"' in report_html
    first_commit = commits[0]
    first_batch_engagements = sum(
        row["realized_engage"] is True and row["replay_time_step"] == 0
        for row in terminals
    )
    assert (
        f'data-frozen-users="{len(first_commit["frozen_realized_positive_user_ids"])}" '
        f'data-committed-users="{len(first_commit["committed_realized_positive_user_ids"])}" '
        f'data-realized-engagements="{first_batch_engagements}"'
    ) in report_html
    assert "S1 does not evidence a preference for M1" in report_html
    assert "not a calibrated Douyin absolute engagement rate" in report_html
    assert "not a causal market effect" in report_html
    assert 'data-testid="full-pool-mechanism-svg"' in report_html
    assert '<svg' in report_html and 'role="img"' in report_html
    assert report_html.count('data-mechanism-node-id="') == 24
    assert report_html.count('data-mechanism-edge-id="') == 26
    assert 'data-testid="full-pool-mechanism-fallback"' in report_html
    assert 'data-trace-semantics="two_stage_realized"' in report_html
    assert "realized_reason" not in report_html
    for download in (
        "full-pool-source/manifest.json",
        "full-pool-source/realization-evidence.json",
        "full-pool-source/realized-projection.json",
        "full-pool-source/full-pool-realized-projection.csv",
        "full-pool-mechanism.mmd",
    ):
        assert f'href="{download}"' in report_html

    index = json.loads(
        (destination / "trace" / "full-pool-trace-index.json").read_text(encoding="utf-8")
    )
    assert index["source_manifest_sha256"] == realized_manifest_sha256
    assert index["trace_semantics"] == "two_stage_realized"
    assert index["terminal_count"] == exposures
    first_partition = json.loads(
        (destination / index["partitions"][0]["relative_path"]).read_text(encoding="utf-8")
    )
    first_trace = first_partition["rows"][0]
    assert set(first_trace["provider_judgment"]) == {
        "engage",
        "probability",
        "action",
        "reason",
        "confidence",
        "decision_source",
        "reason_role",
    }
    assert set(first_trace["abm_realization"]) == {
        "rule_version",
        "seed",
        "status",
        "uniform_draw",
        "engage",
        "action",
    }
    assert "realized_reason" not in first_trace

    report_module._REPORT_PRESENTATION.validate_full_pool_presentation_bundle(
        destination,
        full_pool_source_root=realized_source,
        full_pool_manifest_sha256=realized_manifest_sha256,
        historical_candidate_dir=historical_candidate,
    )


@pytest.mark.parametrize(
    "mutation",
    ("caller-metric", "direct-action-mechanism", "crossed-realized-projection"),
)
def test_realized_bundle_validator_rejects_crossed_report_mechanism_and_source(
    tmp_path: Path,
    mutation: str,
) -> None:
    realized_source, manifest_sha256 = _realized_full_pool_source(tmp_path / "realized-input")
    historical_formal, historical_study, historical_candidate = _historical_candidate(
        tmp_path / "realized-history"
    )
    destination = tmp_path / "realized-bundle"
    report_module._REPORT_PRESENTATION.compose_full_pool_presentation_bundle(
        full_pool_source_root=realized_source,
        full_pool_manifest_sha256=manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        historical_candidate_dir=historical_candidate,
        destination_dir=destination,
    )

    if mutation == "caller-metric":
        report_path = destination / "report.html"
        document = report_path.read_text(encoding="utf-8")
        report_path.write_text(
            document.replace("S1 does not evidence a preference for M1", "S1 prefers M1", 1),
            encoding="utf-8",
        )
    elif mutation == "direct-action-mechanism":
        legacy = _MECHANISM_PRESENTATION.build_full_pool_master().mermaid_artifacts[0]
        (destination / "full-pool-mechanism.mmd").write_bytes(legacy.payload)
    else:
        projection_path = realized_source / "realized-projection.json"
        projection = json.loads(projection_path.read_text(encoding="utf-8"))
        projection["rows"][0]["Total Likes"] += 1
        projection_path.write_text(json.dumps(projection, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(
        report_module._RobustnessReportClosureError,
        match="failed validation",
    ):
        report_module._REPORT_PRESENTATION.validate_full_pool_presentation_bundle(
            destination,
            full_pool_source_root=realized_source,
            full_pool_manifest_sha256=manifest_sha256,
            historical_candidate_dir=historical_candidate,
        )


def test_formal_shaped_validation_source_composes_without_operational_or_external_artifacts(
    tmp_path: Path,
) -> None:
    source, manifest_sha256, operational_root, external_artifact_root = _formal_shaped_full_pool_source(
        tmp_path / "full-pool"
    )
    historical_formal, historical_study, historical_candidate = _historical_candidate(tmp_path / "historical")
    source_before = _snapshot(source)
    shutil.rmtree(operational_root)
    shutil.rmtree(external_artifact_root)

    destination = tmp_path / "presentation-bundle"
    report_module._REPORT_PRESENTATION.compose_full_pool_presentation_bundle(
        full_pool_source_root=source,
        full_pool_manifest_sha256=manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        historical_candidate_dir=historical_candidate,
        destination_dir=destination,
    )

    assert _snapshot(source) == source_before
    report_html = (destination / "report.html").read_text(encoding="utf-8")
    assert "full-pool-formal-source-v1" in report_html
    assert "requested-model=gpt-5.6-sol" in report_html
    assert "evidence-profile=deterministic_validation_fixture" in report_html
    assert "actual-users=7" in report_html
    assert "production_deploy_eligible=false" in report_html


@pytest.mark.parametrize("gate", ("wrong-manifest-hash", "operational-workspace"))
def test_composition_rejects_non_explicit_or_non_closed_full_pool_sources(
    tmp_path: Path,
    gate: str,
) -> None:
    full_pool_source, full_pool_manifest_sha256 = _full_pool_source(tmp_path / "full-pool")
    historical_formal, historical_study, historical_candidate = _historical_candidate(tmp_path / "historical")
    selected_source = full_pool_source
    selected_hash = full_pool_manifest_sha256
    if gate == "wrong-manifest-hash":
        selected_hash = "0" * 64
    else:
        selected_source = full_pool_source.parent / f".{full_pool_source.name}.operational"

    destination = tmp_path / "presentation-bundle"
    with pytest.raises(
        report_module._RobustnessReportClosureError,
        match="failed closed",
    ):
        report_module._REPORT_PRESENTATION.compose_full_pool_presentation_bundle(
            full_pool_source_root=selected_source,
            full_pool_manifest_sha256=selected_hash,
            historical_formal_root=historical_formal,
            historical_study_root=historical_study,
            historical_candidate_dir=historical_candidate,
            destination_dir=destination,
        )
    assert not destination.exists()


def test_composition_keeps_an_existing_destination_untouched(tmp_path: Path) -> None:
    full_pool_source, full_pool_manifest_sha256 = _full_pool_source(tmp_path / "full-pool")
    historical_formal, historical_study, historical_candidate = _historical_candidate(tmp_path / "historical")
    destination = tmp_path / "presentation-bundle"
    destination.mkdir()
    sentinel = destination / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")

    with pytest.raises(report_module._RobustnessReportConflictError):
        report_module._REPORT_PRESENTATION.compose_full_pool_presentation_bundle(
            full_pool_source_root=full_pool_source,
            full_pool_manifest_sha256=full_pool_manifest_sha256,
            historical_formal_root=historical_formal,
            historical_study_root=historical_study,
            historical_candidate_dir=historical_candidate,
            destination_dir=destination,
        )
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert list(destination.iterdir()) == [sentinel]


@pytest.mark.parametrize(
    "mutation",
    (
        "missing-partition",
        "duplicate-terminal",
        "crossed-hash",
        "symlink-partition",
        "path-escape",
        "malformed-partition",
        "extra-partition",
    ),
)
def test_bundle_validator_rejects_trace_partition_identity_and_path_mutations(
    tmp_path: Path,
    mutation: str,
) -> None:
    full_pool_source, full_pool_manifest_sha256 = _full_pool_source(tmp_path / "full-pool")
    historical_formal, historical_study, historical_candidate = _historical_candidate(tmp_path / "historical")
    destination = tmp_path / "presentation-bundle"
    report_module._REPORT_PRESENTATION.compose_full_pool_presentation_bundle(
        full_pool_source_root=full_pool_source,
        full_pool_manifest_sha256=full_pool_manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        historical_candidate_dir=historical_candidate,
        destination_dir=destination,
    )
    index_path = destination / "trace" / "full-pool-trace-index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    first_path = destination / index["partitions"][0]["relative_path"]

    if mutation == "missing-partition":
        first_path.unlink()
    elif mutation == "duplicate-terminal":
        partition = json.loads(first_path.read_text(encoding="utf-8"))
        partition["rows"].append(partition["rows"][0])
        partition["row_count"] += 1
        first_path.write_text(
            json.dumps(partition, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
    elif mutation == "crossed-hash":
        index["partitions"][0]["sha256"] = "0" * 64
        index_path.write_text(
            json.dumps(index, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
    elif mutation == "symlink-partition":
        target = destination / index["partitions"][1]["relative_path"]
        first_path.unlink()
        first_path.symlink_to(target)
    elif mutation == "path-escape":
        index["partitions"][0]["relative_path"] = "../outside.json"
        index_path.write_text(
            json.dumps(index, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
    elif mutation == "malformed-partition":
        first_path.write_text('{"schema_version":', encoding="utf-8")
    else:
        extra = destination / "trace" / "message_1" / "batch-999999.json"
        extra.write_text("{}\n", encoding="utf-8")

    with pytest.raises(
        report_module._RobustnessReportClosureError,
        match="failed validation",
    ):
        report_module._REPORT_PRESENTATION.validate_full_pool_presentation_bundle(
            destination,
            full_pool_source_root=full_pool_source,
            full_pool_manifest_sha256=full_pool_manifest_sha256,
            historical_candidate_dir=historical_candidate,
        )
