from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

import llm_abm_sim.full_pool_segmented_nested_recovery as nested_module
from llm_abm_sim.decision import EngageDecision, ProviderResponseProvenanceUnknown
from llm_abm_sim.full_pool_segmented_continuation import _replay_continuation_ledger
from llm_abm_sim.full_pool_segmented_nested_recovery import (
    FullPoolSegmentedNestedRecoveryPreflight,
    SegmentedNestedRecoveryPlanRequest,
)
from llm_abm_sim.full_pool_segmented_recovery_execution import FullPoolSegmentedRecovery
from llm_abm_sim.schemas import PeerContext, PlatformContext, PostContent, UserProfile
from tests.integration.test_full_pool_segmented_multibatch import _LaneAdapter
from tests.integration.test_full_pool_segmented_recovery_execution import (
    _clock,
    _prepared_recovery,
)


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rewrite_ledger(path: Path, mutate: Any) -> None:
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    mutate(records)
    previous: str | None = None
    for sequence, record in enumerate(records, start=1):
        record["sequence"] = sequence
        record["previous_checksum"] = previous
        body = {key: value for key, value in record.items() if key != "checksum"}
        record["checksum"] = hashlib.sha256(_canonical(body).encode()).hexdigest()
        previous = record["checksum"]
    path.write_text(
        "".join(_canonical(record) + "\n" for record in records),
        encoding="utf-8",
    )


class _SecondWaveUnknownAdapter(_LaneAdapter):
    external_request_invocations = 0

    def __init__(self, lane_id: int, calls: list[str]) -> None:
        super().__init__(calls)
        self.lane_id = lane_id
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
        if time_step == 2 and self.lane_id == 3:
            raise ProviderResponseProvenanceUnknown("offline nested recovery fixture gap")
        return decision


def _snapshot_plans(workspace: Path) -> list[dict[str, Any]]:
    snapshots = sorted((workspace / "segmented_runtime_snapshots").glob("batch-plan-*.json"))
    document = json.loads(snapshots[-1].read_text(encoding="utf-8"))
    plans = [
        plan
        for message in document["payload"]["messages"]
        for plan in message["selected_pair_plans"]
    ]
    return sorted(plans, key=lambda row: row["pair_schedule_position"])


def _nested_stopped_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[SegmentedNestedRecoveryPlanRequest, dict[str, Any]]:
    parent_request, _failed = _prepared_recovery(
        tmp_path,
        monkeypatch,
        delivery_capacity=10,
        fail_time_step=1,
        prefix_terminal_limit=1,
        sample_size=30,
    )
    calls: list[str] = []
    result = FullPoolSegmentedRecovery(now=_clock).run(
        parent_request,
        adapter_factory=lambda lane_id: _SecondWaveUnknownAdapter(lane_id, calls),
    )
    assert result.status == "reconciliation_required"
    assert len(result.unknown_pair_ids) == 7

    operational_root = tmp_path / "nested-failure-operational"
    operational_root.mkdir()
    execution_result_path = operational_root / "recovery-run-result.json"
    execution_result = {
        "schema_version": "full-pool-ticket-205-live-recovery-result-v1",
        "recorded_at": "2026-08-17T15:29:22+00:00",
        "implementation_commit": "f" * 40,
        "recovery_plan_sha256": parent_request.recovery_plan_sha256,
        "human_authorization_sha256": parent_request.authorization_sha256,
        "configured_max_concurrency": 10,
        "observed_external_request_invocations": (
            result.retry_physical_attempts + result.continuation_physical_attempts
        ),
        "subscription_billed_cost_usd": 0,
        "subscription_nominal_cost_usd": 0.0,
        "raw_prompt_request_response_persisted": False,
        "result": result.model_dump(mode="json"),
    }
    execution_result_path.write_text(_canonical(execution_result) + "\n", encoding="utf-8")

    request = SegmentedNestedRecoveryPlanRequest(
        parent_recovery_plan_path=parent_request.recovery_plan_path,
        parent_authorization_path=parent_request.authorization_path,
        stopped_workspace=parent_request.recovery_workspace,
        execution_result_path=execution_result_path,
        execution_result_sha256=_sha(execution_result_path),
        recovery_id="offline-seven-unresolved-recovery-v2",
        recovery_root=tmp_path / "nested-recovery-plan",
        proposed_authorization_path=tmp_path / "nested-authorization" / "human-authorization.json",
        proposed_recovery_workspace=tmp_path / "nested-recovered-continuation",
    )

    identity_path = request.stopped_workspace / "segmented_continuation_identity.json"
    manifest_path = request.stopped_workspace / "cutoff_manifest.json"
    ledger_path = request.stopped_workspace / "segmented_continuation_ledger.jsonl"
    continuation_status_path = request.stopped_workspace / "segmented_continuation_status.json"
    recovery_status_path = request.stopped_workspace / "segmented_recovery_status.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dispatched, durable, new_physical, source_anchor = _replay_continuation_ledger(
        ledger_path,
        expected_identity_hash=identity["identity_hash"],
    )
    assert source_anchor is None
    plans = _snapshot_plans(request.stopped_workspace)
    positions = {row["pair_id"]: row["pair_schedule_position"] for row in plans}
    ledger_rows = [
        json.loads(line)
        for line in ledger_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    expected_contract = nested_module._StoppedRecoveryContract(
        parent_recovery_plan_sha256=parent_request.recovery_plan_sha256,
        parent_authorization_sha256=parent_request.authorization_sha256,
        stopped_identity_hash=identity["identity_hash"],
        stopped_identity_file_sha256=_sha(identity_path),
        stopped_manifest_sha256=manifest["manifest_sha256"],
        stopped_manifest_file_sha256=_sha(manifest_path),
        stopped_ledger_sha256=_sha(ledger_path),
        stopped_workspace_inventory_sha256=hashlib.sha256(
            _canonical(
                nested_module.LocalOperatorFilesystem().inventory(
                    request.stopped_workspace
                )
            ).encode()
        ).hexdigest(),
        stopped_continuation_status_sha256=_sha(continuation_status_path),
        stopped_recovery_status_sha256=_sha(recovery_status_path),
        execution_result_sha256=_sha(execution_result_path),
        implementation_commit=execution_result["implementation_commit"],
        historical_logical_count=result.logical_count,
        historical_physical_attempts=result.physical_attempt_count,
        imported_durable_terminal_count=result.imported_durable_terminal_count,
        durable_terminal_count=result.imported_durable_terminal_count + len(durable),
        explicit_dispatched_count=len(dispatched),
        explicit_durable_terminal_count=len(durable),
        explicit_physical_attempts=new_physical,
        committed_batch_count=len(
            list((request.stopped_workspace / "concurrent_runtime_batch_spool").glob("batch-*.json"))
        ),
        accounted_wave_count=sum(row["event_type"] == "wave_accounting" for row in ledger_rows),
        ledger_sequence=len(ledger_rows),
        recovered_pair_ids=result.recovered_pair_ids,
        unknown_pair_ids=result.unknown_pair_ids,
        unknown_schedule_positions=tuple(positions[pair_id] for pair_id in result.unknown_pair_ids),
    )
    monkeypatch.setattr(nested_module, "_EXPECTED_STOPPED_RECOVERY", expected_contract)
    return request, {
        "parent_request": parent_request,
        "result": result,
        "execution_result": execution_result,
        "expected_contract": expected_contract,
        "calls": calls,
    }


def test_prepare_replays_seven_unresolved_nested_failure_without_provider_or_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, stopped = _nested_stopped_run(tmp_path, monkeypatch)
    protected = {
        path: path.read_bytes()
        for root in (
            request.stopped_workspace,
            request.parent_recovery_plan_path.parent,
            request.parent_authorization_path.parent,
            request.execution_result_path.parent,
        )
        for path in root.rglob("*")
        if path.is_file()
    }

    result = FullPoolSegmentedNestedRecoveryPreflight().prepare(request)

    assert result.status == "recovery_prepared"
    assert result.configured_max_concurrency == 10
    assert result.worker_state == "recorded_stopped"
    assert result.durable_terminal_count == stopped["expected_contract"].durable_terminal_count
    assert result.unresolved_count == 7
    assert result.provider_calls == 0
    assert result.production_deploy_eligible is False
    payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))["payload"]
    assert payload["accounting"] == {
        "logical_cap": 109_200,
        "historical_logical_count": stopped["result"].logical_count,
        "logical_retry_charge": 0,
        "fresh_logical_remaining": 109_200 - stopped["result"].logical_count,
        "physical_cap": 120_120,
        "historical_physical_attempts": stopped["result"].physical_attempt_count,
        "unresolved_uncertainty_physical_charge": 21,
        "future_retry_physical_attempts": 0,
        "future_continuation_physical_attempts": 0,
        "physical_accounting_total": stopped["result"].physical_attempt_count + 21,
        "remaining_physical_cap": 120_120 - stopped["result"].physical_attempt_count - 21,
    }
    unresolved = payload["recovery_snapshot"]["unresolved_pairs"]
    assert [row["pair_id"] for row in unresolved] == list(stopped["result"].unknown_pair_ids)
    assert [row["classification"] for row in unresolved] == [
        "missing_terminal_evidence",
        *(["blocked_by_prior_canonical_gap"] * 6),
    ]
    assert [row["canonical_schedule_position"] for row in unresolved] == list(
        stopped["expected_contract"].unknown_schedule_positions
    )
    assert all(row["uncertainty_physical_charge"] == 3 for row in unresolved)
    assert all(row["logical_retry_charge"] == 0 for row in unresolved)
    handoff = payload["human_authorization_handoff"]
    assert handoff["authorization_required"] is True
    assert handoff["retry_authorized"] is False
    assert handoff["unresolved_pair_ids"] == list(stopped["result"].unknown_pair_ids)
    assert handoff["proposed_authorization_path"] == str(request.proposed_authorization_path)
    assert handoff["proposed_recovery_workspace"] == str(request.proposed_recovery_workspace)
    assert handoff["provider_transport"] == "openai-codex"
    assert handoff["wire_api"] == "responses"
    assert handoff["reasoning_effort"] == "low"
    assert handoff["max_output_tokens"] == 256
    assert handoff["timeout_seconds"] == 30.0
    assert handoff["max_retries"] == 2
    assert handoff["omitted_parameters"] == ["temperature", "top_p", "seed"]
    assert handoff["fresh_no_cache"] is True
    assert handoff["provider_calls"] == 0
    assert {path: path.read_bytes() for path in protected} == protected


def test_status_rejects_extra_handoff_field(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _stopped = _nested_stopped_run(tmp_path, monkeypatch)
    preflight = FullPoolSegmentedNestedRecoveryPreflight()
    result = preflight.prepare(request)
    envelope = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    envelope["payload"]["human_authorization_handoff"]["unexpected"] = True
    envelope["payload_sha256"] = hashlib.sha256(
        _canonical(envelope["payload"]).encode()
    ).hexdigest()
    result.artifact_path.chmod(0o644)
    result.artifact_path.write_text(_canonical(envelope) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="handoff"):
        preflight.status(result.artifact_path)


def test_status_rejects_crossed_parent_recovery_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _stopped = _nested_stopped_run(tmp_path, monkeypatch)
    preflight = FullPoolSegmentedNestedRecoveryPreflight()
    result = preflight.prepare(request)
    envelope = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    envelope["payload"]["parent_recovery_lineage"]["parent_recovery_identity_hash"] = (
        "0" * 64
    )
    envelope["payload_sha256"] = hashlib.sha256(
        _canonical(envelope["payload"]).encode()
    ).hexdigest()
    result.artifact_path.chmod(0o644)
    result.artifact_path.write_text(_canonical(envelope) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="parent recovery lineage"):
        preflight.status(result.artifact_path)


def test_status_rejects_execution_contract_crossed_from_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _stopped = _nested_stopped_run(tmp_path, monkeypatch)
    preflight = FullPoolSegmentedNestedRecoveryPreflight()
    result = preflight.prepare(request)
    envelope = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    envelope["payload"]["execution_contract"]["configured_max_concurrency"] = 5
    envelope["payload_sha256"] = hashlib.sha256(
        _canonical(envelope["payload"]).encode()
    ).hexdigest()
    result.artifact_path.chmod(0o644)
    result.artifact_path.write_text(_canonical(envelope) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="execution contract"):
        preflight.status(result.artifact_path)


def test_status_rejects_crossed_durable_terminal_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _stopped = _nested_stopped_run(tmp_path, monkeypatch)
    preflight = FullPoolSegmentedNestedRecoveryPreflight()
    result = preflight.prepare(request)
    envelope = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    payload = envelope["payload"]
    payload["recovery_snapshot"]["durable_terminal_summary"]["pair_ids_sha256"] = (
        "0" * 64
    )
    payload["recovery_identity"]["recovery_snapshot_sha256"] = hashlib.sha256(
        _canonical(payload["recovery_snapshot"]).encode()
    ).hexdigest()
    identity_body = {
        key: value for key, value in payload["recovery_identity"].items() if key != "identity_hash"
    }
    payload["recovery_identity"]["identity_hash"] = hashlib.sha256(
        _canonical(identity_body).encode()
    ).hexdigest()
    payload["human_authorization_handoff"]["recovery_plan_identity_hash"] = payload[
        "recovery_identity"
    ]["identity_hash"]
    envelope["payload_sha256"] = hashlib.sha256(_canonical(payload).encode()).hexdigest()
    result.artifact_path.chmod(0o644)
    result.artifact_path.write_text(_canonical(envelope) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="durable terminal summary"):
        preflight.status(result.artifact_path)


def test_status_rejects_extra_stopped_workspace_inventory_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _stopped = _nested_stopped_run(tmp_path, monkeypatch)
    preflight = FullPoolSegmentedNestedRecoveryPreflight()
    result = preflight.prepare(request)
    envelope = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    envelope["payload"]["source_inventories"]["stopped_recovery_workspace"][
        "extra.json"
    ] = {"relative_path": "extra.json", "bytes": 1, "sha256": "0" * 64}
    envelope["payload_sha256"] = hashlib.sha256(
        _canonical(envelope["payload"]).encode()
    ).hexdigest()
    result.artifact_path.chmod(0o644)
    result.artifact_path.write_text(_canonical(envelope) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="source inventory"):
        preflight.status(result.artifact_path)


def test_prepare_rejects_preexisting_snapshot_byte_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _stopped = _nested_stopped_run(tmp_path, monkeypatch)
    snapshot = sorted(
        (request.stopped_workspace / "segmented_runtime_snapshots").glob(
            "batch-plan-*.json"
        )
    )[0]
    snapshot.write_bytes(snapshot.read_bytes() + b" \n")

    with pytest.raises(ValueError, match="exact Issue #205"):
        FullPoolSegmentedNestedRecoveryPreflight().prepare(request)

    assert not request.recovery_root.exists()


def test_prepare_rejects_reordered_unresolved_wave(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _stopped = _nested_stopped_run(tmp_path, monkeypatch)
    ledger = request.stopped_workspace / "segmented_continuation_ledger.jsonl"

    def reorder(records: list[dict[str, Any]]) -> None:
        wave = next(
            row for row in reversed(records) if row["event_type"] == "wave_accounting"
        )
        wave["payload"]["pair_ids"] = list(reversed(wave["payload"]["pair_ids"]))

    _rewrite_ledger(ledger, reorder)

    with pytest.raises(ValueError, match="order|crossed|wave"):
        FullPoolSegmentedNestedRecoveryPreflight().prepare(request)

    assert not request.recovery_root.exists()


def test_prepare_rejects_duplicated_durable_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _stopped = _nested_stopped_run(tmp_path, monkeypatch)
    ledger = request.stopped_workspace / "segmented_continuation_ledger.jsonl"

    def duplicate(records: list[dict[str, Any]]) -> None:
        terminal = next(
            row for row in reversed(records) if row["event_type"] == "pair_terminal"
        )
        records.append(json.loads(json.dumps(terminal)))

    _rewrite_ledger(ledger, duplicate)

    with pytest.raises(ValueError, match="duplicat|terminal"):
        FullPoolSegmentedNestedRecoveryPreflight().prepare(request)

    assert not request.recovery_root.exists()


def test_prepare_rejects_truncated_stopped_ledger_without_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _stopped = _nested_stopped_run(tmp_path, monkeypatch)
    ledger = request.stopped_workspace / "segmented_continuation_ledger.jsonl"
    ledger.write_bytes(ledger.read_bytes().rstrip(b"\n"))

    with pytest.raises(ValueError, match="truncated"):
        FullPoolSegmentedNestedRecoveryPreflight().prepare(request)

    assert not request.recovery_root.exists()


def test_prepare_rejects_rehashed_execution_result_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _stopped = _nested_stopped_run(tmp_path, monkeypatch)
    wrapper = json.loads(request.execution_result_path.read_text(encoding="utf-8"))
    wrapper["observed_external_request_invocations"] += 1
    request.execution_result_path.write_text(_canonical(wrapper) + "\n", encoding="utf-8")
    crossed = request.model_copy(
        update={"execution_result_sha256": _sha(request.execution_result_path)}
    )

    with pytest.raises(ValueError, match="execution result"):
        FullPoolSegmentedNestedRecoveryPreflight().prepare(crossed)

    assert not request.recovery_root.exists()


def test_prepare_is_create_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _stopped = _nested_stopped_run(tmp_path, monkeypatch)
    preflight = FullPoolSegmentedNestedRecoveryPreflight()
    preflight.prepare(request)

    with pytest.raises(FileExistsError, match="must be new"):
        preflight.prepare(request)


def test_request_rejects_output_inside_stopped_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _stopped = _nested_stopped_run(tmp_path, monkeypatch)
    payload = request.model_dump()
    payload["recovery_root"] = request.stopped_workspace / "crossed-plan"

    with pytest.raises(ValueError, match="independent"):
        SegmentedNestedRecoveryPlanRequest.model_validate(payload)


def test_status_rejects_recomputed_wrong_uncertainty_charge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _stopped = _nested_stopped_run(tmp_path, monkeypatch)
    preflight = FullPoolSegmentedNestedRecoveryPreflight()
    result = preflight.prepare(request)
    envelope = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    payload = envelope["payload"]
    accounting = payload["accounting"]
    accounting["unresolved_uncertainty_physical_charge"] = 20
    accounting["physical_accounting_total"] = accounting["historical_physical_attempts"] + 20
    accounting["remaining_physical_cap"] = (
        accounting["physical_cap"] - accounting["physical_accounting_total"]
    )
    payload["recovery_identity"]["accounting_sha256"] = hashlib.sha256(
        _canonical(accounting).encode()
    ).hexdigest()
    identity_body = {
        key: value for key, value in payload["recovery_identity"].items() if key != "identity_hash"
    }
    payload["recovery_identity"]["identity_hash"] = hashlib.sha256(
        _canonical(identity_body).encode()
    ).hexdigest()
    payload["human_authorization_handoff"]["recovery_plan_identity_hash"] = payload[
        "recovery_identity"
    ]["identity_hash"]
    payload["human_authorization_handoff"]["uncertainty_physical_charge"] = 20
    envelope["payload_sha256"] = hashlib.sha256(_canonical(payload).encode()).hexdigest()
    result.artifact_path.chmod(0o644)
    result.artifact_path.write_text(_canonical(envelope) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="accounting"):
        preflight.status(result.artifact_path)


class _MutatingFilesystem(nested_module.LocalOperatorFilesystem):
    def __init__(self, target: Path) -> None:
        self.target = target
        self.target_inventory_calls = 0

    def inventory(self, root: Path) -> dict[str, dict[str, object]]:
        if root == self.target:
            self.target_inventory_calls += 1
            if self.target_inventory_calls == 2:
                status = root / "segmented_continuation_status.json"
                status.write_bytes(status.read_bytes() + b" ")
        return super().inventory(root)


def test_prepare_detects_workspace_mutation_before_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _stopped = _nested_stopped_run(tmp_path, monkeypatch)
    preflight = FullPoolSegmentedNestedRecoveryPreflight(
        filesystem=_MutatingFilesystem(request.stopped_workspace)
    )

    with pytest.raises(ValueError, match="changed during"):
        preflight.prepare(request)

    assert not request.recovery_root.exists()
