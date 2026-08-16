from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

import llm_abm_sim.full_pool_segmented_recovery as recovery_module
from llm_abm_sim.decision import EngageDecision, ProviderResponseProvenanceUnknown
from llm_abm_sim.full_pool_segmented_continuation import (
    SEGMENTED_CONCURRENCY_QUALIFICATION_SCHEMA,
    SEGMENTED_OPERATOR_ARTIFACT_ENVELOPE_SCHEMA,
    FullPoolSegmentedContinuation,
    SegmentedQualificationArtifactRef,
    SegmentedQualificationWave,
    _replay_continuation_ledger,
)
from llm_abm_sim.full_pool_segmented_operator import (
    SEGMENTED_AUTHORIZATION_REFERENCE,
    SEGMENTED_IMPLEMENTATION_COMMIT,
    CutoverPlanRequest,
    FullPoolSegmentedCutoverOperator,
    LocalOperatorFilesystem,
)
from llm_abm_sim.full_pool_segmented_recovery import (
    FullPoolSegmentedRecoveryPreflight,
    SegmentedRecoveryPlanRequest,
)
from llm_abm_sim.schemas import PeerContext, PlatformContext, PostContent, UserProfile
from tests.integration.test_full_pool_segmented_multibatch import _LaneAdapter, _mid_batch_prefix
from tests.unit.test_full_pool_segmented_operator import FakeProcessController


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rewrite_ledger(path: Path, mutate: Any) -> None:
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    mutate(records)
    previous: str | None = None
    for sequence, record in enumerate(records, start=1):
        record["sequence"] = sequence
        record["previous_checksum"] = previous
        body = {key: value for key, value in record.items() if key != "checksum"}
        record["checksum"] = hashlib.sha256(_canonical(body).encode()).hexdigest()
        previous = record["checksum"]
    path.write_text("".join(_canonical(record) + "\n" for record in records), encoding="utf-8")


class _FailingLaneAdapter(_LaneAdapter):
    external_request_invocations = 0

    def __init__(
        self,
        lane_id: int,
        calls: list[str],
        *,
        fail_lane_id: int = 7,
        fail_time_step: int = 1,
    ) -> None:
        super().__init__(calls)
        self.lane_id = lane_id
        self.fail_lane_id = fail_lane_id
        self.fail_time_step = fail_time_step
        self.external_request_invocations = 0

    def decide(
        self,
        post: PostContent,
        profile: UserProfile,
        peer_context: PeerContext,
        platform_context: PlatformContext | None = None,
        time_step: int = 0,
    ) -> EngageDecision:
        self.external_request_invocations += 1
        decision = super().decide(post, profile, peer_context, platform_context, time_step)
        if time_step == self.fail_time_step and self.lane_id == self.fail_lane_id:
            raise ProviderResponseProvenanceUnknown("offline injected recovery fixture gap")
        return decision


def _write_qualification(
    path: Path,
    *,
    authorization_sha256: str,
    wave: SegmentedQualificationWave,
) -> SegmentedQualificationArtifactRef:
    payload = {
        "schema_version": SEGMENTED_CONCURRENCY_QUALIFICATION_SCHEMA,
        "continuation_authorization_sha256": authorization_sha256,
        "mode": "first-wave-formal-remaining-pairs",
        "status": "qualified",
        "pair_ids": list(wave.pair_ids),
        "lane_count": 10,
        "elapsed_seconds": 2.0,
        "actual_request_rate_per_second": 5.0,
        "physical_attempt_count": 10,
        "provider_response_count": 10,
        "successful_decision_count": 10,
        "error_count": 0,
        "terminal_status_counts": {"succeeded": 10},
        "observed_model_counts": {"gpt-5.6-sol": 10},
        "usage_complete_response_count": 10,
        "usage_missing_response_count": 0,
        "usage_malformed_response_count": 0,
        "input_tokens": 100,
        "output_tokens": 20,
        "total_tokens": 120,
        "cached_input_tokens": 0,
        "formal_remaining_pairs_consumed": 10,
        "provider_concurrency_reduction": False,
        "production_deploy_eligible": False,
    }
    envelope = {
        "schema_version": SEGMENTED_OPERATOR_ARTIFACT_ENVELOPE_SCHEMA,
        "payload": payload,
        "payload_sha256": hashlib.sha256(_canonical(payload).encode()).hexdigest(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_canonical(envelope) + "\n", encoding="utf-8")
    return SegmentedQualificationArtifactRef(path=path, sha256=_sha(path))


def _failed_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch | None = None,
    *,
    delivery_capacity: int = 4,
    sample_size: int = 7,
    fail_lane_id: int = 7,
    fail_time_step: int = 1,
    prefix_terminal_limit: int = 1,
) -> tuple[SegmentedRecoveryPlanRequest, dict[str, Any]]:
    prefix, dataset, _ = _mid_batch_prefix(
        tmp_path / "fixture",
        horizon=3,
        delivery_capacity=delivery_capacity,
        terminal_limit=prefix_terminal_limit,
        sample_size=sample_size,
    )
    runtime = json.loads((prefix / "concurrent_message_execution_run_identity.json").read_text())
    formal = json.loads((prefix / "full_pool_execution_identity.json").read_text())
    fingerprints = runtime["sample_data_fingerprints"]
    dataset_hashes = {str(name): str(digest) for name, digest in fingerprints["dataset_files"].items()}
    pid = 424242
    pidfile = tmp_path / "formal.pid"
    pidfile.write_text(f"{pid}\n", encoding="utf-8")
    controller = FakeProcessController(
        pid=pid,
        command="python frozen-full-pool.py run",
        cwd=tmp_path,
        lock_path=prefix / "concurrent_message_execution.lock",
    )
    operator = FullPoolSegmentedCutoverOperator(
        process_controller=controller,
        filesystem=LocalOperatorFilesystem(),
    )
    artifact_root = tmp_path / "failed-run-artifacts"
    plan_path = artifact_root / "plan.json"
    request = CutoverPlanRequest(
        prefix_workspace=prefix,
        frozen_prefix_workspace=tmp_path / "frozen-prefix",
        frozen_prefix_staging=tmp_path / ".frozen-prefix.staging",
        continuation_workspace=tmp_path / "failed-continuation",
        dataset_dir=dataset,
        pidfile=pidfile,
        expected_pid=pid,
        expected_command=controller.command,
        expected_cwd=tmp_path,
        expected_v1_output_identity=str(formal["output_identity"]),
        expected_v1_operational_root=str(formal["operational_root"]),
        expected_v1_source_root=str(formal["source_root"]),
        expected_v1_candidate_root=str(formal["candidate_root"]),
        expected_v1_recorded_runtime_workspace=str(runtime["operational_workspace"]),
        expected_v1_recorded_output_target=str(runtime["output_target"]),
        expected_v1_dataset_dir=str(fingerprints["dataset_dir"]),
        expected_v1_run_identity_hash=str(runtime["identity_hash"]),
        expected_execution_contract_sha256=str(formal["execution_contract_sha256"]),
        implementation_commit=SEGMENTED_IMPLEMENTATION_COMMIT,
        dataset_hashes=dataset_hashes,
        continuation_id="offline-dual-unresolved-v1",
        authorization_reference=SEGMENTED_AUTHORIZATION_REFERENCE,
        preflight_artifact=artifact_root / "preflight.json",
        cutover_artifact=artifact_root / "cutover.json",
        reconciliation_artifact=artifact_root / "reconciliation.json",
        continuation_authorization_artifact=artifact_root / "continuation-authorization.json",
        qualification_artifact=artifact_root / "qualification.json",
        stability_interval_seconds=0.01,
        stop_wait_timeout_seconds=1.0,
    )
    operator.prepare(plan_path, request)
    preflight = operator.dry_run(plan_path)
    controller.alive = False
    controller.locked = False
    operator.cutover(plan_path, confirmation_token=str(preflight["exact_confirmation_token"]))
    authorization_sha256 = _sha(request.continuation_authorization_artifact)

    calls: list[str] = []

    def qualify(wave: SegmentedQualificationWave) -> SegmentedQualificationArtifactRef:
        return _write_qualification(
            request.qualification_artifact,
            authorization_sha256=authorization_sha256,
            wave=wave,
        )

    result = FullPoolSegmentedContinuation().run(
        request.frozen_prefix_workspace,
        request.continuation_workspace,
        continuation_id=request.continuation_id,
        dataset_dir=request.dataset_dir,
        adapter_factory=lambda lane_id: _FailingLaneAdapter(
            lane_id,
            calls,
            fail_lane_id=fail_lane_id,
            fail_time_step=fail_time_step,
        ),
        first_wave_observer=qualify,
    )
    assert result.status.value == "reconciliation_required"
    assert len(result.unknown_pair_ids) == 2
    result_path = artifact_root / "continuation-result.json"
    result_path.write_text(_canonical(result.model_dump(mode="json")) + "\n", encoding="utf-8")

    identity = json.loads(
        (request.continuation_workspace / "segmented_continuation_identity.json").read_text()
    )
    ledger_path = request.continuation_workspace / "segmented_continuation_ledger.jsonl"
    dispatched, durable, suffix_physical, _ = _replay_continuation_ledger(
        ledger_path,
        expected_identity_hash=str(identity["identity_hash"]),
    )
    status_path = request.continuation_workspace / "segmented_continuation_status.json"
    accounted_wave_count = sum(
        json.loads(line).get("event_type") == "wave_accounting"
        for line in ledger_path.read_text(encoding="utf-8").splitlines()
        if line
    )
    audit = {
        "schema_version": "full-pool-segmented-reconciliation-required-audit-v1",
        "recorded_at": "2026-08-15T12:19:34+00:00",
        "plan_path": str(plan_path.resolve()),
        "plan_sha256": _sha(plan_path),
        "continuation_workspace": str(request.continuation_workspace),
        "worker_pid": pid,
        "worker_running": False,
        "lifecycle": "reconciliation_required",
        "configured_max_concurrency": 10,
        "prefix_logical_count": result.durable_prefix_terminal_count,
        "logical_count": result.logical_count,
        "physical_attempt_count": result.physical_attempt_count,
        "suffix_dispatched_count": len(dispatched),
        "suffix_terminal_count": len(durable),
        "unknown_pair_count": 2,
        "unknown_pair_ids": list(result.unknown_pair_ids),
        "zero_terminal_evidence_count": 1,
        "canonical_drain_blocked_following_pair_count": 1,
        "accounted_wave_count": accounted_wave_count,
        "accounted_suffix_physical_attempts": suffix_physical,
        "continuation_ledger_bytes": ledger_path.stat().st_size,
        "continuation_ledger_sha256": _sha(ledger_path),
        "continuation_status_sha256": _sha(status_path),
        "qualification_artifact_sha256": _sha(request.qualification_artifact),
        "qualification_lane_count": 10,
        "result_artifact_sha256": _sha(result_path),
        "automatic_retry_performed": False,
        "recovery_authorized": False,
        "production_deploy_eligible": False,
        "raw_prompt_request_response_persisted": False,
    }
    audit_path = artifact_root / "reconciliation-required-audit.json"
    audit_path.write_text(_canonical(audit) + "\n", encoding="utf-8")
    recovery_request = SegmentedRecoveryPlanRequest(
        cutover_plan_path=plan_path,
        result_artifact_path=result_path,
        failure_audit_path=audit_path,
        failure_audit_sha256=_sha(audit_path),
        recovery_id="offline-recovery-plan-v1",
        recovery_root=tmp_path / "recovery-plan",
    )
    expected_contract = recovery_module._FailedRunContract(
        plan_sha256=_sha(plan_path),
        continuation_identity_hash=str(identity["identity_hash"]),
        cutoff_manifest_sha256=result.manifest_sha256,
        continuation_ledger_sha256=_sha(ledger_path),
        continuation_status_sha256=_sha(status_path),
        qualification_artifact_sha256=_sha(request.qualification_artifact),
        result_artifact_sha256=_sha(result_path),
        failure_audit_sha256=_sha(audit_path),
        prefix_logical_count=int(audit["prefix_logical_count"]),
        durable_prefix_terminal_count=result.durable_prefix_terminal_count,
        suffix_dispatched_count=len(dispatched),
        suffix_terminal_count=len(durable),
        logical_count=result.logical_count,
        physical_attempt_count=result.physical_attempt_count,
        accounted_wave_count=int(audit["accounted_wave_count"]),
        accounted_suffix_physical_attempts=suffix_physical,
        unknown_pair_ids=result.unknown_pair_ids,
    )
    if monkeypatch is not None:
        monkeypatch.setattr(recovery_module, "_EXPECTED_FAILED_RUN", expected_contract)
    return recovery_request, {
        "request": request,
        "result": result,
        "audit": audit,
        "ledger_path": ledger_path,
        "expected_contract": expected_contract,
    }


def test_prepare_replays_dual_unresolved_failure_without_provider_or_source_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, failed = _failed_run(tmp_path, monkeypatch)
    failed_request = failed["request"]
    protected = {
        path: path.read_bytes()
        for root in (
            failed_request.frozen_prefix_workspace,
            failed_request.continuation_workspace,
        )
        for path in root.rglob("*")
        if path.is_file()
    }
    protected[failed_request.qualification_artifact] = failed_request.qualification_artifact.read_bytes()
    protected[request.failure_audit_path] = request.failure_audit_path.read_bytes()

    result = FullPoolSegmentedRecoveryPreflight().prepare(request)

    assert result.status == "recovery_prepared"
    assert result.configured_max_concurrency == 10
    assert result.worker_state == "recorded_stopped"
    assert result.unresolved_count == 2
    assert result.provider_calls == 0
    assert result.production_deploy_eligible is False
    payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))["payload"]
    assert payload["accounting"] == {
        "logical_cap": 109_200,
        "historical_logical_count": failed["result"].logical_count,
        "logical_retry_charge": 0,
        "remaining_logical_cap": 109_200 - failed["result"].logical_count,
        "physical_cap": 120_120,
        "historical_physical_attempts": failed["result"].physical_attempt_count,
        "unresolved_uncertainty_physical_charge": 6,
        "future_retry_physical_attempts": 0,
        "physical_accounting_total": failed["result"].physical_attempt_count + 6,
        "remaining_physical_cap": 120_120 - failed["result"].physical_attempt_count - 6,
    }
    snapshot = payload["recovery_snapshot"]
    assert len(snapshot["durable_prefix_terminals"]) == failed["result"].durable_prefix_terminal_count
    assert len(snapshot["durable_suffix_terminals"]) == failed["result"].concurrent_suffix_terminal_count
    batches = snapshot["batch_snapshots"]
    assert [batch["state"] for batch in batches] == ["committed", "active_incomplete"]
    assert sum(len(batch["candidate_schedule_pair_ids"]) for batch in batches) == 21
    assert batches[1]["frozen_feedback_user_ids"] == sorted(
        batches[0]["committed_feedback_user_ids"]
    )
    assert payload["execution_contract"]["qualification_lane_count"] == 10
    implementation = payload["recovery_identity"]["recovery_implementation"]
    assert set(implementation["failed_run_implementation_artifacts"]) == {
        "operator_module",
        "continuation_module",
        "operator_cli",
    }
    assert recovery_module.__file__ is not None
    assert implementation["recovery_module_sha256"] == _sha(Path(recovery_module.__file__))
    unresolved = snapshot["unresolved_pairs"]
    assert [row["classification"] for row in unresolved] == [
        "missing_terminal_evidence",
        "blocked_by_prior_canonical_gap",
    ]
    assert all(
        set(row)
        == {
            "pair_id",
            "canonical_schedule_position",
            "classification",
            "historical_physical_attempts",
            "uncertainty_physical_charge",
            "logical_retry_charge",
        }
        for row in unresolved
    )
    assert len(payload["recovery_snapshot"]["durable_suffix_terminals"]) == len(
        failed["ledger_path"].read_text(encoding="utf-8").split('"event_type":"pair_terminal"')
    ) - 1
    assert {path: path.read_bytes() for path in protected} == protected


def test_status_rejects_recomputed_payload_with_wrong_uncertainty_charge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _ = _failed_run(tmp_path, monkeypatch)
    preflight = FullPoolSegmentedRecoveryPreflight()
    result = preflight.prepare(request)
    envelope = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    payload = envelope["payload"]
    payload["accounting"]["unresolved_uncertainty_physical_charge"] = 5
    envelope["payload_sha256"] = hashlib.sha256(_canonical(payload).encode()).hexdigest()
    result.artifact_path.chmod(0o644)
    result.artifact_path.write_text(_canonical(envelope) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="accounting"):
        preflight.status(result.artifact_path)


def test_prepare_rejects_valid_but_non_issue_205_failed_run(tmp_path: Path) -> None:
    request, _ = _failed_run(tmp_path)

    with pytest.raises(ValueError, match="exact Issue #205"):
        FullPoolSegmentedRecoveryPreflight().prepare(request)


def test_prepare_rejects_semantically_equal_snapshot_byte_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, failed = _failed_run(tmp_path, monkeypatch)
    continuation = failed["request"].continuation_workspace
    snapshot = next((continuation / "segmented_runtime_snapshots").glob("*.json"))
    snapshot.write_bytes(snapshot.read_bytes() + b" ")

    with pytest.raises(ValueError, match="snapshot bytes"):
        FullPoolSegmentedRecoveryPreflight().prepare(request)


def test_prepare_rejects_semantically_equal_ledger_byte_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, failed = _failed_run(tmp_path, monkeypatch)
    ledger = failed["ledger_path"]
    lines = ledger.read_bytes().splitlines(keepends=True)
    lines[0] = lines[0][:-1] + b" \n"
    ledger.write_bytes(b"".join(lines))
    audit = json.loads(request.failure_audit_path.read_text(encoding="utf-8"))
    audit["continuation_ledger_bytes"] = ledger.stat().st_size
    audit["continuation_ledger_sha256"] = _sha(ledger)
    request.failure_audit_path.write_text(_canonical(audit) + "\n", encoding="utf-8")
    crossed = request.model_copy(update={"failure_audit_sha256": _sha(request.failure_audit_path)})

    with pytest.raises(ValueError, match="ledger bytes"):
        FullPoolSegmentedRecoveryPreflight().prepare(crossed)


@pytest.mark.parametrize("mutation", ["reorder", "duplicate"])
def test_prepare_rejects_terminal_reorder_and_duplicate_durable_pair(
    tmp_path: Path,
    mutation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, failed = _failed_run(tmp_path, monkeypatch)

    def mutate(records: list[dict[str, Any]]) -> None:
        terminals = [record for record in records if record["event_type"] == "pair_terminal"]
        if mutation == "reorder":
            terminals[0]["payload"], terminals[1]["payload"] = (
                terminals[1]["payload"],
                terminals[0]["payload"],
            )
        else:
            terminals[1]["payload"] = json.loads(json.dumps(terminals[0]["payload"]))

    _rewrite_ledger(failed["ledger_path"], mutate)

    with pytest.raises(ValueError, match="duplicate|order"):
        FullPoolSegmentedRecoveryPreflight().prepare(request)


@pytest.mark.parametrize("mode", ["missing", "extra"])
def test_prepare_rejects_missing_or_extra_unresolved_pair(
    tmp_path: Path,
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, failed = _failed_run(tmp_path, monkeypatch)
    status_path = failed["request"].continuation_workspace / "segmented_continuation_status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    if mode == "missing":
        status["unknown_pair_ids"] = status["unknown_pair_ids"][:1]
    else:
        status["unknown_pair_ids"].append("crossed:message_1:1")
    status_path.write_text(_canonical(status), encoding="utf-8")

    with pytest.raises(ValueError, match="dual-unresolved|unknown"):
        FullPoolSegmentedRecoveryPreflight().prepare(request)


def test_prepare_rejects_result_crossed_from_another_failed_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, first_failed = _failed_run(tmp_path / "first")
    second, _ = _failed_run(tmp_path / "second")
    monkeypatch.setattr(recovery_module, "_EXPECTED_FAILED_RUN", first_failed["expected_contract"])
    crossed = first.model_copy(update={"result_artifact_path": second.result_artifact_path})

    with pytest.raises(ValueError, match="result"):
        FullPoolSegmentedRecoveryPreflight().prepare(crossed)


@pytest.mark.parametrize("mode", ["truncated", "tampered"])
def test_prepare_rejects_ledger_truncation_or_checksum_tamper(
    tmp_path: Path,
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, failed = _failed_run(tmp_path, monkeypatch)
    ledger = failed["ledger_path"]
    if mode == "truncated":
        ledger.write_bytes(ledger.read_bytes()[:-1])
    else:
        records = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
        dispatched = next(record for record in records if record["event_type"] == "pair_dispatched")
        dispatched["payload"]["lane_id"] = 99
        ledger.write_text("".join(_canonical(record) + "\n" for record in records), encoding="utf-8")

    with pytest.raises(ValueError, match="truncated|checksum"):
        FullPoolSegmentedRecoveryPreflight().prepare(request)


def test_prepare_is_create_once_and_rejects_duplicate_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _ = _failed_run(tmp_path, monkeypatch)
    preflight = FullPoolSegmentedRecoveryPreflight()
    first = preflight.prepare(request)
    first_bytes = first.artifact_path.read_bytes()

    with pytest.raises(FileExistsError, match="new independent path"):
        preflight.prepare(request)

    assert first.artifact_path.read_bytes() == first_bytes


def test_prepare_removes_candidate_if_failed_workspace_changes_during_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, failed = _failed_run(tmp_path, monkeypatch)
    status_path = failed["request"].continuation_workspace / "segmented_continuation_status.json"
    original_write = recovery_module._exclusive_write_json

    def write_then_mutate(path: Path, payload: dict[str, object]) -> None:
        original_write(path, payload)
        status_path.write_bytes(status_path.read_bytes() + b" ")

    monkeypatch.setattr(recovery_module, "_exclusive_write_json", write_then_mutate)

    with pytest.raises(ValueError, match="failed continuation changed"):
        FullPoolSegmentedRecoveryPreflight().prepare(request)

    assert not request.recovery_root.exists()


def test_status_rejects_recomputed_payload_with_wrong_cap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _ = _failed_run(tmp_path, monkeypatch)
    preflight = FullPoolSegmentedRecoveryPreflight()
    result = preflight.prepare(request)
    envelope = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    envelope["payload"]["accounting"]["logical_cap"] = 109_199
    envelope["payload_sha256"] = hashlib.sha256(
        _canonical(envelope["payload"]).encode()
    ).hexdigest()
    result.artifact_path.chmod(0o644)
    result.artifact_path.write_text(_canonical(envelope) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="accounting"):
        preflight.status(result.artifact_path)
