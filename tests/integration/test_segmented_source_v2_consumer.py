from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import replace
from pathlib import Path

import pytest

from llm_abm_sim import concurrent_robustness_evidence as evidence_module
from llm_abm_sim import concurrent_robustness_release as release_module
from llm_abm_sim import concurrent_robustness_report as report_module
from llm_abm_sim.concurrent_execution_journal import ConcurrentExecutionJournal
from llm_abm_sim.full_pool_segmented_continuation import (
    FullPoolReconciliationAuthorization,
    FullPoolSegmentedContinuation,
    SegmentedContinuationStatus,
    SegmentedRecoveryUnresolvedPairFacts,
    _read_closed_segmented_full_pool_source,
    _read_segmented_formal_lineage,
    _scan_segmented_candidates,
    _scan_segmented_pairs_and_terminals,
    _validate_segmented_cutoff_order,
    _validate_segmented_reconciliation,
)
from llm_abm_sim.full_pool_segmented_recovery_execution import FullPoolSegmentedRecovery
from llm_abm_sim.safe_serialization import safe_data
from tests.integration.test_full_pool_formal_experiment import (
    _formal_execution_contract,
    _production_contract,
    _write_contract_artifact,
)
from tests.integration.test_full_pool_presentation_bundle import _historical_candidate
from tests.integration.test_full_pool_segmented_multibatch import (
    _LaneAdapter,
    _mid_batch_prefix,
)
from tests.integration.test_full_pool_segmented_recovery_execution import (
    _clock as _recovery_clock,
)
from tests.integration.test_full_pool_segmented_recovery_execution import (
    _prepared_recovery,
)


def _source(tmp_path: Path) -> tuple[Path, str]:
    prefix, _dataset, _calls = _mid_batch_prefix(tmp_path)
    result = FullPoolSegmentedContinuation().run(
        prefix,
        tmp_path / "continuation",
        continuation_id="segmented-consumer-v2",
        adapter_factory=lambda _lane_id: _LaneAdapter([]),
    )
    assert result.status is SegmentedContinuationStatus.COMPLETE
    assert result.source_root is not None
    assert result.source_manifest_sha256 is not None
    return result.source_root, result.source_manifest_sha256


def _recovered_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, str]:
    request, _failed = _prepared_recovery(tmp_path, monkeypatch)
    result = FullPoolSegmentedRecovery(now=_recovery_clock).run(
        request,
        adapter_factory=lambda _lane_id: _LaneAdapter([]),
    )
    assert result.source_root is not None
    assert result.source_manifest_sha256 is not None
    return result.source_root, result.source_manifest_sha256


def _rewrite_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _mid_batch_unknown_prefix(tmp_path: Path, *, pending_attempts: int) -> tuple[Path, str]:
    prefix, _dataset, _calls = _mid_batch_prefix(tmp_path)
    journal_identity = json.loads(
        (prefix / "concurrent_message_execution_run_identity.json").read_text(encoding="utf-8")
    )
    journal = ConcurrentExecutionJournal.open_resume(prefix, identity=journal_identity)
    try:
        replay = journal.replay()
        terminal = next(
            row
            for row in reversed(replay["records"])
            if row.get("event_type") == "variant_terminal"
        )
        terminal_payload = terminal["payload"]
        terminal_row = terminal_payload["terminal_row"]
        pair_id = terminal_payload["pair_id"]
        batch_hash = terminal["batch_snapshot_hash"]
        snapshot_path = next(
            path
            for path in (prefix / "concurrent_message_execution_snapshots").glob("*.json")
            if json.loads(path.read_text(encoding="utf-8"))["payload"]["time_step"] == 1
        )
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))["payload"]
        plans = [
            plan
            for message in snapshot["messages"]
            for plan in message["selected_pair_plans"]
        ]
        terminal_plan = next(plan for plan in plans if plan["pair_id"] == pair_id)
        journal.append(
            event_type="pair_closed",
            event_identity={"pair_id": pair_id, "time_step": terminal_row["time_step"]},
            payload={
                "pair_id": pair_id,
                "pair_schedule_position": terminal_row["pair_schedule_position"],
                "message_id": terminal_row["message_id"],
                "message_title": terminal_plan["message_title"],
                "user_id": terminal_row["user_id"],
                "primary_terminal_row_id": terminal_row["terminal_row_id"],
                "primary_status": terminal_row["terminal_status"],
            },
            batch_snapshot_hash=batch_hash,
        )
        unknown = next(
            plan for plan in plans if plan["pair_schedule_position"] == terminal_row["pair_schedule_position"] + 1
        )
        unknown_pair_id = unknown["pair_id"]
        journal.append(
            event_type="variant_started",
            event_identity={
                "pair_id": unknown_pair_id,
                "decision_variant": "primary",
                "event_type": "variant_started",
                "time_step": unknown["time_step"],
            },
            payload={
                "pair_id": unknown_pair_id,
                "pair_schedule_position": unknown["pair_schedule_position"],
                "message_id": unknown["message_id"],
                "message_title": unknown["message_title"],
                "user_id": unknown["user_id"],
                "ranking_position": unknown["ranking_position"],
                "selection_reason": unknown["selection_reason"],
            },
            batch_snapshot_hash=batch_hash,
        )
    finally:
        journal.close()

    identity = json.loads((prefix / "full_pool_execution_identity.json").read_text(encoding="utf-8"))
    ledger_path = prefix / "full_pool_attempt_ledger.jsonl"
    ledger = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]
    sequence = ledger[-1]["sequence"]
    previous = ledger[-1]["checksum"]

    def append(event_type: str, payload: dict[str, object]) -> None:
        nonlocal sequence, previous
        sequence += 1
        body = {
            "schema_version": "full-pool-formal-attempt-ledger-v1",
            "sequence": sequence,
            "previous_checksum": previous,
            "execution_contract_sha256": identity["execution_contract_sha256"],
            "event_type": event_type,
            "payload": payload,
        }
        checksum = hashlib.sha256(_canonical(body).encode()).hexdigest()
        ledger.append({**body, "checksum": checksum})
        previous = checksum

    old_status = json.loads((prefix / "full_pool_execution_status.json").read_text(encoding="utf-8"))
    append(
        "judgment_reserved",
        {
            "pair_id": unknown_pair_id,
            "reserved_logical_judgments": old_status["logical_judgments"] + 1,
            "reserved_physical_attempts": old_status["physical_attempts"] + 3,
            "maximum_physical_attempts": 3,
        },
    )
    for attempt in range(1, pending_attempts + 1):
        append(
            "physical_attempt_accounted",
            {
                "pair_id": unknown_pair_id,
                "attempt_index": attempt,
                "attempt_outcome": "migration_unknown",
            },
        )
    ledger_path.write_text("".join(_canonical(row) + "\n" for row in ledger), encoding="utf-8")
    old_status.update(
        {
            "lifecycle": "attempt_reserved",
            "reserved_logical_judgments": old_status["logical_judgments"] + 1,
            "reserved_physical_attempts": old_status["physical_attempts"] + 3,
            "last_pair_id": unknown_pair_id,
        }
    )
    (prefix / "full_pool_execution_status.json").write_text(
        _canonical(old_status), encoding="utf-8"
    )
    return prefix, unknown_pair_id


def test_v9_evidence_interface_has_no_caller_formal_fact_injection() -> None:
    parameters = inspect.signature(
        evidence_module.validate_segmented_full_pool_production_evidence
    ).parameters
    assert "formal_facts" not in parameters
    assert "segmented_facts" not in parameters


def test_segmented_formal_lineage_recloses_contract_authorization_qualification_and_p0(
    tmp_path: Path,
) -> None:
    base = _production_contract(tmp_path / "dataset")
    source_root = tmp_path / base.output_identity
    execution = _formal_execution_contract(
        base,
        source_root,
        evidence_profile="formal_live",
        active_logical_cap=109_200,
        active_physical_cap=120_120,
    )
    contract = type(base).model_validate(
        {**base.model_dump(mode="json"), "formal_execution": execution.model_dump(mode="json")},
        strict=False,
    )
    qualification_root = execution.qualification.artifact_path.parent
    _write_contract_artifact(
        qualification_root / "full_pool_run_contract.json",
        contract.model_dump(mode="json"),
    )
    _write_contract_artifact(
        qualification_root / "formal_execution_contract.json",
        execution.model_dump(mode="json"),
    )
    prompt = evidence_module.CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.resolve(
        "jinjiang-concurrent-message-primary-prompt-v1"
    )
    request = execution.request_contract.model_dump(mode="json")
    run_identity = {
        "execution_contract": safe_data(contract.model_dump(mode="json")),
        "prompt_contract": {"primary": json.loads(json.dumps(prompt.audit_record()))},
        "provider_contract": {
            "primary": {
                "provider": execution.provider,
                "model": execution.requested_model,
                "requested_model": execution.requested_model,
                "prompt_version": execution.prompt_version,
                "wire_api": execution.request_contract.wire_api,
                "reasoning_effort": execution.request_contract.reasoning_effort,
                "max_output_tokens": execution.request_contract.output_token_ceiling,
                "timeout_seconds": execution.request_contract.timeout_seconds,
                "max_retries": execution.request_contract.max_retries,
                "request_contract": request,
                "external_transport": {
                    "adapter_identity": execution.adapter_identity,
                    "provider_transport": execution.transport,
                },
            }
        },
    }
    formal_identity = {
        "contract_sha256": hashlib.sha256(
            _canonical(contract.model_dump(mode="json")).encode()
        ).hexdigest(),
        "execution_contract_sha256": hashlib.sha256(
            _canonical(execution.model_dump(mode="json")).encode()
        ).hexdigest(),
        "authorization_artifact_sha256": execution.authorization.artifact_sha256,
        "qualification_artifact_sha256": execution.qualification.artifact_sha256,
    }

    lineage = _read_segmented_formal_lineage(
        run_identity=run_identity,
        formal_identity=formal_identity,
    )

    assert lineage is not None
    assert lineage.contract.profile == "production"
    assert lineage.prompt_variant_id == "P0"
    assert lineage.prompt_canonical_hash == prompt.canonical_hash
    crossed = json.loads(json.dumps(run_identity))
    crossed["prompt_contract"]["primary"]["variant_id"] = "P1"
    with pytest.raises(ValueError, match="canonical P0"):
        _read_segmented_formal_lineage(
            run_identity=crossed,
            formal_identity=formal_identity,
        )


def test_segmented_source_v2_validator_closes_rows_cutoff_identity_and_accounting(
    tmp_path: Path,
) -> None:
    source, manifest_sha256 = _source(tmp_path)

    closed = _read_closed_segmented_full_pool_source(
        source,
        manifest_sha256=manifest_sha256,
    )

    assert closed.facts.source_schema_version == "full-pool-segmented-source-v2"
    assert closed.facts.candidate_ranking_rows == 36
    assert closed.facts.eligible_pairs == 21
    assert closed.facts.primary_terminals == 21
    assert closed.facts.committed_batches == 3
    assert closed.facts.serial_prefix_terminal_count == 11
    assert closed.facts.concurrent_suffix_terminal_count == 10
    assert closed.facts.max_concurrency == 10
    assert closed.facts.logical_judgments == 21
    assert closed.facts.physical_attempts == 21
    assert closed.facts.migration_unknown_physical_charge == 0
    assert closed.facts.concurrency_qualification_artifact_sha256 is None
    assert closed.facts.unknown_pair_count == 0
    assert closed.facts.reconciliation_retry_count == 0
    assert closed.facts.evidence_profile == "deterministic_validation_fixture"
    assert closed.facts.live_api_triggered is False
    assert closed.facts.production_deploy_eligible is False
    assert len(closed.batch_paths) == 3
    assert closed.read_batch(0)["time_step"] == 0


def test_segmented_source_v2_preserves_pending_unknown_invocations_and_separate_retry_charge(
    tmp_path: Path,
) -> None:
    prefix, unknown_pair_id = _mid_batch_unknown_prefix(tmp_path, pending_attempts=2)
    run_identity = json.loads(
        (prefix / "concurrent_message_execution_run_identity.json").read_text(encoding="utf-8")
    )
    result = FullPoolSegmentedContinuation().run(
        prefix,
        tmp_path / "continuation",
        continuation_id="segmented-unknown-source-v2",
        adapter_factory=lambda _lane_id: _LaneAdapter([]),
        reconciliation_authorization=FullPoolReconciliationAuthorization(
            prefix_run_identity_hash=run_identity["identity_hash"],
            unknown_pair_id=unknown_pair_id,
            authorization_reference="fixture://approved-one-migration-unknown",
            physical_attempt_charge=3,
            retry_authorized=True,
        ),
    )
    assert result.status is SegmentedContinuationStatus.COMPLETE
    assert result.source_root is not None
    assert result.source_manifest_sha256 is not None

    manifest = json.loads((result.source_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["physical_attempt_count"] == 24
    assert manifest["accounting"]["invocations"] == 21
    assert manifest["accounting"]["usage_incomplete_attempts"] == 21
    assert manifest["accounting"]["migration_unknown_physical_charge"] == 3
    closed = _read_closed_segmented_full_pool_source(
        result.source_root,
        manifest_sha256=result.source_manifest_sha256,
    )
    assert closed.facts.physical_attempts == 24
    assert closed.facts.migration_unknown_physical_charge == 3
    assert closed.facts.unknown_pair_count == 1
    assert closed.facts.reconciliation_retry_count == 1


def test_segmented_source_v2_deep_scanners_reject_extra_fields_response_drift_and_cutoff_reorder(
    tmp_path: Path,
) -> None:
    source, _manifest_sha256 = _source(tmp_path)
    candidate_scan = _scan_segmented_candidates(
        source / "candidate_rows.jsonl",
        message_ids=("message_1", "message_2", "message_3"),
        horizon=3,
        sample_size=7,
        capacity=3,
    )

    candidate_rows = [json.loads(line) for line in (source / "candidate_rows.jsonl").read_text().splitlines()]
    candidate_rows[0]["access_token"] = "forbidden"
    _rewrite_jsonl(source / "candidate_rows.jsonl", candidate_rows)
    with pytest.raises(ValueError, match="forbidden|missing or extra"):
        _scan_segmented_candidates(
            source / "candidate_rows.jsonl",
            message_ids=("message_1", "message_2", "message_3"),
            horizon=3,
            sample_size=7,
            capacity=3,
        )
    candidate_rows[0].pop("access_token")
    _rewrite_jsonl(source / "candidate_rows.jsonl", candidate_rows)

    terminal_path = source / "terminal_rows.jsonl"
    terminal_rows = [json.loads(line) for line in terminal_path.read_text().splitlines()]
    terminal_rows[0]["request_invocations"] = 4
    _rewrite_jsonl(terminal_path, terminal_rows)
    with pytest.raises(ValueError, match="Provider accounting"):
        _scan_segmented_pairs_and_terminals(
            source / "pair_rows.jsonl",
            terminal_path,
            message_ids=("message_1", "message_2", "message_3"),
            horizon=3,
            capacity=3,
            final_capacity=1,
            maximum_attempts=3,
            prompt_version="jinjiang-concurrent-message-primary-prompt-v1",
            selected_rows=candidate_scan.selected_rows,
        )
    terminal_rows[0]["request_invocations"] = 1
    terminal_rows[0]["observed_model_counts"] = json.dumps(
        {"offline-segmented-multibatch-v1": 2}, separators=(",", ":"), sort_keys=True
    )
    _rewrite_jsonl(terminal_path, terminal_rows)
    with pytest.raises(ValueError, match="observed-model evidence"):
        _scan_segmented_pairs_and_terminals(
            source / "pair_rows.jsonl",
            terminal_path,
            message_ids=("message_1", "message_2", "message_3"),
            horizon=3,
            capacity=3,
            final_capacity=1,
            maximum_attempts=3,
            prompt_version="jinjiang-concurrent-message-primary-prompt-v1",
            selected_rows=candidate_scan.selected_rows,
        )

    terminal_rows[0]["observed_model_counts"] = json.dumps(
        {"offline-segmented-multibatch-v1": 1}, separators=(",", ":"), sort_keys=True
    )
    _rewrite_jsonl(terminal_path, terminal_rows)
    pair_scan = _scan_segmented_pairs_and_terminals(
        source / "pair_rows.jsonl",
        terminal_path,
        message_ids=("message_1", "message_2", "message_3"),
        horizon=3,
        capacity=3,
        final_capacity=1,
        maximum_attempts=3,
        prompt_version="jinjiang-concurrent-message-primary-prompt-v1",
        selected_rows=candidate_scan.selected_rows,
    )
    steps = [json.loads(line) for line in (source / "steps.jsonl").read_text().splitlines()]
    cutoff_path = source.parent / "cutoff_manifest.json"
    cutoff = json.loads(cutoff_path.read_text())["manifest"]
    cutoff["ordered_prefix_pair_ids"][0] = "crossed:message_1:0"
    with pytest.raises(ValueError, match="cutoff pair or terminal order"):
        _validate_segmented_cutoff_order(cutoff, pair_scan=pair_scan, step_rows=steps)


def test_segmented_reconciliation_binds_exact_unknown_pair_and_full_retry_window() -> None:
    authorization = FullPoolReconciliationAuthorization(
        prefix_run_identity_hash="a" * 64,
        unknown_pair_id="u1:message_1:1",
        authorization_reference="fixture://one-unknown",
        physical_attempt_charge=3,
        retry_authorized=True,
    ).model_dump(mode="json")
    cutoff = {
        "unknown_pair_ids": ["u1:message_1:1"],
        "unknown_count": 1,
        "reconciliation_authorization": authorization,
        "reconciliation_authorization_sha256": hashlib.sha256(
            _canonical(authorization).encode()
        ).hexdigest(),
    }
    with pytest.raises(ValueError, match="retry identity"):
        _validate_segmented_reconciliation(
            cutoff,
            retry_pair_ids=("u2:message_1:1",),
            prefix_identity_hash="a" * 64,
            maximum_attempts=3,
        )
    with pytest.raises(ValueError, match="retry identity"):
        _validate_segmented_reconciliation(
            cutoff,
            retry_pair_ids=("u1:message_1:1",),
            prefix_identity_hash="b" * 64,
            maximum_attempts=3,
        )


@pytest.mark.parametrize(
    "artifact,mutation",
    (
        ("candidate_rows.jsonl", "drop"),
        ("pair_rows.jsonl", "segment"),
        ("terminal_rows.jsonl", "accounting"),
        ("steps.jsonl", "feedback"),
    ),
)
def test_segmented_source_v2_validator_rejects_count_topology_accounting_and_feedback_tamper(
    tmp_path: Path,
    artifact: str,
    mutation: str,
) -> None:
    source, manifest_sha256 = _source(tmp_path)
    path = source / artifact
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    if mutation == "drop":
        rows.pop()
    elif mutation == "segment":
        rows[0]["execution_segment"] = "concurrent_suffix"
    elif mutation == "accounting":
        rows[0]["request_invocations"] = 2
    else:
        rows[2]["frozen_campaign_engaged_user_ids"] = []
    _rewrite_jsonl(path, rows)

    with pytest.raises(ValueError):
        _read_closed_segmented_full_pool_source(
            source,
            manifest_sha256=manifest_sha256,
        )


def test_segmented_formal_source_remains_non_deployable_until_evidence_promotion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, manifest_sha256 = _source(tmp_path / "segmented")
    closed = _read_closed_segmented_full_pool_source(
        source,
        manifest_sha256=manifest_sha256,
    )
    formal = replace(
        closed,
        manifest={
            **closed.manifest,
            "profile": "production",
            "evidence_profile": "formal_live",
            "provider_calls": 21,
            "live_api_triggered": True,
            "production_deploy_eligible": False,
        },
        aggregates={
            **closed.aggregates,
            "evidence_profile": "formal_live",
            "production_deploy_eligible": False,
        },
    )
    monkeypatch.setattr(
        report_module,
        "_read_closed_full_pool_source",
        lambda *_args, **_kwargs: formal,
    )
    historical_formal, historical_study, historical_candidate = _historical_candidate(
        tmp_path / "historical"
    )

    bundle = report_module._REPORT_PRESENTATION.compose_full_pool_presentation_bundle(
        full_pool_source_root=source,
        full_pool_manifest_sha256=manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        historical_candidate_dir=historical_candidate,
        destination_dir=tmp_path / "bundle",
    )

    assert bundle.is_dir()
    assert 'data-testid="full-pool-segmented-lineage"' in (
        bundle / "report.html"
    ).read_text(encoding="utf-8")


def test_segmented_source_v2_composes_candidate_and_evidence_closure_without_calls(
    tmp_path: Path,
) -> None:
    source, manifest_sha256 = _source(tmp_path / "segmented")
    historical_formal, historical_study, historical_candidate = _historical_candidate(
        tmp_path / "historical"
    )
    bundle = tmp_path / "bundle"
    report_module._REPORT_PRESENTATION.compose_full_pool_presentation_bundle(
        full_pool_source_root=source,
        full_pool_manifest_sha256=manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        historical_candidate_dir=historical_candidate,
        destination_dir=bundle,
    )
    html = (bundle / "report.html").read_text(encoding="utf-8")
    assert 'data-testid="full-pool-segmented-lineage"' in html
    assert "serial prefix → max_concurrency10 suffix" in html
    assert "prefix-terminals=11 suffix-terminals=10" in html
    assert "unknown=0 reconciliation=0 total-physical=21" in html

    candidate = tmp_path / "candidate"
    report_module._REPORT_PRESENTATION.compose_full_pool_candidate(
        full_pool_source_root=source,
        full_pool_manifest_sha256=manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        presentation_bundle_dir=bundle,
        implementation_commit="abcdef0",
        destination_dir=candidate,
    )
    payload = json.loads(
        (candidate / "concurrent_robustness_report_payload.json").read_text(encoding="utf-8")
    )
    segmented = payload["source_lineage"]["full_pool"]["segmented_execution"]
    assert segmented["execution_topology"] == "serial_prefix_then_concurrent_suffix"
    assert segmented["max_concurrency"] == 10
    assert payload["production_deploy_eligible"] is False

    closure_path = tmp_path / "closure.json"
    closure = evidence_module.close_full_pool_presentation(
        repo_root=tmp_path,
        full_pool_source_root=source,
        full_pool_manifest_sha256=manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        presentation_bundle_dir=bundle,
        candidate_dir=candidate,
        destination_path=closure_path,
        implementation_commit="abcdef0",
    )
    assert closure.production_deploy_eligible is False
    assert closure.provider_calls_during_closure == 0

    rejected_destination = tmp_path / "rejected-validation-v9"
    rejected_contract = tmp_path / "rejected-validation-v9.json"
    with pytest.raises(
        release_module.ConcurrentRobustnessReleaseError,
        match="non-live|non-Formal|incomplete",
    ):
        release_module.promote_concurrent_robustness_release(
            repo_root=tmp_path,
            formal_root=historical_formal,
            study_root=historical_study,
            workspace_root=None,
            candidate_dir=candidate,
            execution_contract_path=None,
            destination_dir=rejected_destination,
            release_contract_path=rejected_contract,
            release_id="segmented-validation-rejected",
            presentation_closure_path=closure_path,
            full_pool_source_root=source,
            full_pool_manifest_sha256=manifest_sha256,
            implementation_commit="abcdef0",
        )
    assert not rejected_destination.exists()
    assert not rejected_contract.exists()


def test_recovered_source_composes_candidate_and_evidence_closure_but_cannot_promote(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, manifest_sha256 = _recovered_source(tmp_path / "recovered", monkeypatch)
    historical_formal, historical_study, historical_candidate = _historical_candidate(
        tmp_path / "historical-recovery"
    )
    bundle = tmp_path / "recovery-bundle"
    report_module._REPORT_PRESENTATION.compose_full_pool_presentation_bundle(
        full_pool_source_root=source,
        full_pool_manifest_sha256=manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        historical_candidate_dir=historical_candidate,
        destination_dir=bundle,
    )
    candidate = tmp_path / "recovery-candidate"
    report_module._REPORT_PRESENTATION.compose_full_pool_candidate(
        full_pool_source_root=source,
        full_pool_manifest_sha256=manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        presentation_bundle_dir=bundle,
        implementation_commit="abcdef0",
        destination_dir=candidate,
    )
    payload = json.loads(
        (candidate / "concurrent_robustness_report_payload.json").read_text(
            encoding="utf-8"
        )
    )
    segmented = payload["source_lineage"]["full_pool"]["segmented_execution"]
    closed = _read_closed_segmented_full_pool_source(
        source,
        manifest_sha256=manifest_sha256,
    )
    release_lineage, release_accounting = release_module._v9_recovery_fact_documents(
        closed.facts
    )
    assert segmented["recovery_lineage"] == release_lineage
    assert segmented["recovery_accounting"] == release_accounting
    assert [
        row["pair_id"] for row in segmented["recovery_lineage"]["unresolved_pairs"]
    ] == ["u7:message_2:1", "u8:message_2:1"]
    assert segmented["recovery_accounting"]["uncertainty_physical_charge"] == 6
    assert segmented["recovery_accounting"]["logical_retry_charge"] == 0
    assert payload["production_deploy_eligible"] is False

    closure_path = tmp_path / "recovery-closure.json"
    closure = evidence_module.close_full_pool_presentation(
        repo_root=tmp_path,
        full_pool_source_root=source,
        full_pool_manifest_sha256=manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        presentation_bundle_dir=bundle,
        candidate_dir=candidate,
        destination_path=closure_path,
        implementation_commit="abcdef0",
    )
    closed_segmented = closure.source_lineage["full_pool"]["segmented_execution"]
    assert closed_segmented["recovery_lineage"] == segmented["recovery_lineage"]
    assert closed_segmented["recovery_accounting"] == segmented["recovery_accounting"]
    assert closure.provider_calls_during_closure == 0
    assert closure.production_deploy_eligible is False

    destination = tmp_path / "forbidden-recovery-v9"
    contract_path = tmp_path / "forbidden-recovery-v9.json"
    with pytest.raises(
        release_module.ConcurrentRobustnessReleaseError,
        match="non-live|non-Formal|incomplete",
    ):
        release_module.promote_concurrent_robustness_release(
            repo_root=tmp_path,
            formal_root=historical_formal,
            study_root=historical_study,
            workspace_root=None,
            candidate_dir=candidate,
            execution_contract_path=None,
            destination_dir=destination,
            release_contract_path=contract_path,
            release_id="recovery-validation-rejected",
            presentation_closure_path=closure_path,
            full_pool_source_root=source,
            full_pool_manifest_sha256=manifest_sha256,
            implementation_commit="abcdef0",
        )
    assert not destination.exists()
    assert not contract_path.exists()


def test_recovery_typed_facts_close_the_exact_issue_205_production_accounting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, manifest_sha256 = _recovered_source(
        tmp_path / "recovery-formal-facts",
        monkeypatch,
    )
    historical_formal, historical_study, historical_candidate = _historical_candidate(
        tmp_path / "historical-formal-facts"
    )
    bundle = tmp_path / "recovery-formal-bundle"
    report_module._REPORT_PRESENTATION.compose_full_pool_presentation_bundle(
        full_pool_source_root=source,
        full_pool_manifest_sha256=manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        historical_candidate_dir=historical_candidate,
        destination_dir=bundle,
    )
    candidate = tmp_path / "recovery-formal-candidate"
    report_module._REPORT_PRESENTATION.compose_full_pool_candidate(
        full_pool_source_root=source,
        full_pool_manifest_sha256=manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        presentation_bundle_dir=bundle,
        implementation_commit="abcdef0",
        destination_dir=candidate,
    )
    closure = evidence_module.close_full_pool_presentation(
        repo_root=tmp_path,
        full_pool_source_root=source,
        full_pool_manifest_sha256=manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        presentation_bundle_dir=bundle,
        candidate_dir=candidate,
        destination_path=tmp_path / "recovery-formal-closure.json",
        implementation_commit="abcdef0",
    )
    closed = _read_closed_segmented_full_pool_source(
        source,
        manifest_sha256=manifest_sha256,
    )
    assert closed.facts.recovery_lineage is not None
    assert closed.facts.recovery_accounting is not None
    retry_ids = (
        "70400636033:message_1:5",
        "70401299326:message_1:5",
    )
    recovery_lineage = replace(
        closed.facts.recovery_lineage,
        failed_v1_run_identity_hash=closed.facts.prefix_identity_hash,
        recovery_identity_hash=closed.facts.continuation_identity_hash,
        unresolved_pairs=(
            SegmentedRecoveryUnresolvedPairFacts(
                pair_id=retry_ids[0],
                canonical_schedule_position=18_998,
                classification="missing_terminal_evidence",
                historical_physical_attempts=1,
                uncertainty_physical_charge=3,
                logical_retry_charge=0,
                terminal_row_id=f"{retry_ids[0]}:primary",
            ),
            SegmentedRecoveryUnresolvedPairFacts(
                pair_id=retry_ids[1],
                canonical_schedule_position=18_999,
                classification="blocked_by_prior_canonical_gap",
                historical_physical_attempts=1,
                uncertainty_physical_charge=3,
                logical_retry_charge=0,
                terminal_row_id=f"{retry_ids[1]}:primary",
            ),
        ),
    )
    recovery_accounting = replace(
        closed.facts.recovery_accounting,
        historical_logical_count=19_000,
        fresh_logical_count=90_200,
        logical_count=109_200,
        historical_physical_attempts=19_117,
        uncertainty_physical_charge=6,
        retry_actual_physical_attempts=2,
        continuation_actual_physical_attempts=90_200,
        aggregate_physical_attempts=109_325,
    )
    segmented = replace(
        closed.facts,
        configuration_profile="production",
        evidence_profile="formal_live",
        provider_transport=evidence_module.FULL_POOL_FORMAL_TRANSPORT,
        adapter_identity=evidence_module.FULL_POOL_FORMAL_ADAPTER_IDENTITY,
        requested_model=evidence_module.FULL_POOL_FORMAL_REQUESTED_MODEL,
        qualified_observed_model=evidence_module.FULL_POOL_FORMAL_REQUIRED_OBSERVED_MODEL,
        formal_execution_contract_sha256="1" * 64,
        authorization_artifact_sha256="2" * 64,
        qualification_artifact_sha256="3" * 64,
        observed_model_evidence_sha256="4" * 64,
        prompt_variant_id="P0",
        prompt_version="jinjiang-concurrent-message-primary-prompt-v1",
        prompt_canonical_hash=(
            evidence_module.CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.resolve(
                "jinjiang-concurrent-message-primary-prompt-v1"
            ).canonical_hash
        ),
        distinct_users=36_400,
        eligible_pairs=109_200,
        exposures=109_200,
        primary_terminals=109_200,
        committed_batches=30,
        candidate_ranking_rows=1_691_730,
        provider_failed_terminals=0,
        serial_prefix_terminal_count=8_782,
        concurrent_suffix_terminal_count=100_418,
        logical_judgments=109_200,
        physical_attempts=109_325,
        physical_attempt_cap=120_120,
        provider_responses=109_200,
        successful_decisions=109_200,
        external_request_invocations=109_319,
        observed_model_counts={"gpt-5.6-sol": 109_200},
        usage_complete_response_count=109_200,
        usage_missing_response_count=0,
        usage_malformed_response_count=0,
        migration_unknown_physical_charge=3,
        unknown_pair_count=1,
        reconciliation_retry_count=3,
        live_api_triggered=True,
        recovery_lineage=recovery_lineage,
        recovery_accounting=recovery_accounting,
    )
    formal = replace(
        evidence_module._segmented_formal_release_facts(closure, segmented),
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

    evidence_module._validate_segmented_formal_release_facts(
        segmented,
        formal,
        closure=closure,
    )
    release_lineage, release_accounting = release_module._v9_recovery_fact_documents(
        segmented
    )
    assert release_lineage is not None
    assert release_accounting is not None
    unresolved_documents = release_lineage["unresolved_pairs"]
    assert isinstance(unresolved_documents, list)
    first_unresolved = unresolved_documents[0]
    assert isinstance(first_unresolved, dict)
    assert first_unresolved["terminal_row_id"] == "70400636033:message_1:5:primary"
    assert release_accounting["aggregate_physical_attempts"] == 109_325


def test_v9_promotes_and_validates_an_exact_local_release_with_typed_fixture_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, manifest_sha256 = _source(tmp_path / "segmented")
    closed = _read_closed_segmented_full_pool_source(
        source,
        manifest_sha256=manifest_sha256,
    )
    historical_formal, historical_study, historical_candidate = _historical_candidate(
        tmp_path / "historical"
    )
    bundle = tmp_path / "bundle"
    report_module._REPORT_PRESENTATION.compose_full_pool_presentation_bundle(
        full_pool_source_root=source,
        full_pool_manifest_sha256=manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        historical_candidate_dir=historical_candidate,
        destination_dir=bundle,
    )
    candidate = tmp_path / "candidate"
    report_module._REPORT_PRESENTATION.compose_full_pool_candidate(
        full_pool_source_root=source,
        full_pool_manifest_sha256=manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        presentation_bundle_dir=bundle,
        implementation_commit="abcdef0",
        destination_dir=candidate,
    )
    closure_path = tmp_path / "closure.json"
    closure = evidence_module.close_full_pool_presentation(
        repo_root=tmp_path,
        full_pool_source_root=source,
        full_pool_manifest_sha256=manifest_sha256,
        historical_formal_root=historical_formal,
        historical_study_root=historical_study,
        presentation_bundle_dir=bundle,
        candidate_dir=candidate,
        destination_path=closure_path,
        implementation_commit="abcdef0",
    )
    segmented = replace(
        closed.facts,
        configuration_profile="production",
        evidence_profile="formal_live",
        provider_transport=evidence_module.FULL_POOL_FORMAL_TRANSPORT,
        adapter_identity=evidence_module.FULL_POOL_FORMAL_ADAPTER_IDENTITY,
        requested_model=evidence_module.FULL_POOL_FORMAL_REQUESTED_MODEL,
        qualified_observed_model=evidence_module.FULL_POOL_FORMAL_REQUIRED_OBSERVED_MODEL,
        formal_execution_contract_sha256="1" * 64,
        authorization_artifact_sha256="2" * 64,
        qualification_artifact_sha256="3" * 64,
        concurrency_qualification_artifact_sha256="5" * 64,
        observed_model_evidence_sha256="4" * 64,
        prompt_variant_id="P0",
        prompt_version="jinjiang-concurrent-message-primary-prompt-v1",
        prompt_canonical_hash=(
            evidence_module.CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.resolve(
                "jinjiang-concurrent-message-primary-prompt-v1"
            ).canonical_hash
        ),
        distinct_users=36_400,
        eligible_pairs=109_200,
        exposures=109_200,
        primary_terminals=109_200,
        committed_batches=30,
        candidate_ranking_rows=1_691_730,
        provider_failed_terminals=0,
        serial_prefix_terminal_count=11,
        concurrent_suffix_terminal_count=109_189,
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
        migration_unknown_physical_charge=0,
        unknown_pair_count=0,
        reconciliation_retry_count=0,
        live_api_triggered=True,
        production_deploy_eligible=False,
    )
    formal = replace(
        evidence_module._segmented_formal_release_facts(closure, segmented),
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
    injected = evidence_module.SegmentedFullPoolProductionEvidenceFacts(
        closure=closure,
        formal=formal,
        segmented=segmented,
    )
    monkeypatch.setattr(
        release_module._evidence,
        "validate_segmented_full_pool_production_evidence",
        lambda **_kwargs: injected,
    )
    destination = tmp_path / "production-v9"
    contract_path = tmp_path / "release-contract-v9.json"
    promoted = release_module.promote_concurrent_robustness_release(
        repo_root=tmp_path,
        formal_root=historical_formal,
        study_root=historical_study,
        workspace_root=None,
        candidate_dir=candidate,
        execution_contract_path=None,
        destination_dir=destination,
        release_contract_path=contract_path,
        release_id="segmented-v9-local",
        presentation_closure_path=closure_path,
        full_pool_source_root=source,
        full_pool_manifest_sha256=manifest_sha256,
        implementation_commit="abcdef0",
    )
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    assert promoted.source_dir == destination.resolve()
    assert contract["schema_version"] == "abm-report-release-contract-v9"
    assert set(contract) == release_module._RELEASE_CONTRACT_V9_FIELDS
    assert set(contract["segmented_source_facts"]) == release_module._SEGMENTED_SOURCE_FACT_FIELDS
    assert contract["segmented_source_facts"]["max_concurrency"] == 10
    assert contract["segmented_source_facts"]["physical_attempts"] == 109_200
    assert contract["production_deploy_eligible"] is True
    assert '<meta name="abm-release-contract" content="abm-report-release-contract-v9">' in (
        destination / "report.html"
    ).read_text(encoding="utf-8")

    validated = release_module.validate_concurrent_robustness_production_release(
        repo_root=tmp_path,
        contract_document=contract,
        source_dir=destination,
    )
    assert validated["schema_version"] == "abm-report-release-contract-v9"
    assert validated["sampling_status"] == "persisted_full_pool_segmented_formal_run"
    assert validated["physical_attempts"] == 109_200
