from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import llm_abm_sim.full_pool_segmented_automated_recovery as automated_module
import llm_abm_sim.full_pool_segmented_nested_recovery as nested_module
from llm_abm_sim.decision import EngageDecision, ProviderResponseProvenanceUnknown
from llm_abm_sim.full_pool_segmented_automated_recovery import (
    AutomatedNestedRecoveryRequest,
    FullPoolSegmentedAutomatedRecovery,
)
from llm_abm_sim.full_pool_segmented_nested_recovery import (
    FullPoolSegmentedNestedRecoveryPreflight,
)
from llm_abm_sim.schemas import PeerContext, PlatformContext, PostContent, UserProfile
from tests.integration.test_full_pool_segmented_multibatch import _LaneAdapter
from tests.integration.test_full_pool_segmented_nested_recovery import _nested_stopped_run


def _automated_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    logical_cap: int | None = None,
    physical_headroom: int | None = None,
) -> AutomatedNestedRecoveryRequest:
    plan_request, stopped = _nested_stopped_run(tmp_path, monkeypatch)
    if logical_cap is not None:
        monkeypatch.setattr(nested_module, "FULL_POOL_SEGMENTED_LOGICAL_CAP", logical_cap)
    if physical_headroom is not None:
        monkeypatch.setattr(
            nested_module,
            "FULL_POOL_SEGMENTED_PHYSICAL_CAP",
            stopped["result"].physical_attempt_count + 21 + physical_headroom,
        )
    plan = FullPoolSegmentedNestedRecoveryPreflight().prepare(plan_request)
    return AutomatedNestedRecoveryRequest(
        nested_recovery_plan_path=plan.artifact_path,
        nested_recovery_plan_sha256=plan.artifact_sha256,
        recovery_id="offline-automated-nested-recovery-v3",
        recovery_workspace=tmp_path / "automated-nested-recovery",
    )


class _ImplementationFailureAdapter(_LaneAdapter):
    def __init__(self, calls: list[str], *, failed_pair_id: str) -> None:
        super().__init__(calls)
        self.failed_pair_id = failed_pair_id

    def decide(
        self,
        post: PostContent,
        profile: UserProfile,
        peer_context: PeerContext,
        platform_context: PlatformContext | None = None,
        time_step: int = 0,
    ) -> EngageDecision:
        decision = super().decide(post, profile, peer_context, platform_context, time_step)
        pair_id = f"{profile.user_id}:{post.post_id}:{time_step}"
        if pair_id == self.failed_pair_id:
            raise ValueError("offline implementation failure detail")
        return decision


class _AlwaysUnknownAdapter(_LaneAdapter):
    def __init__(self, calls: list[str], *, unknown_pair_id: str) -> None:
        super().__init__(calls)
        self.unknown_pair_id = unknown_pair_id

    def decide(
        self,
        post: PostContent,
        profile: UserProfile,
        peer_context: PeerContext,
        platform_context: PlatformContext | None = None,
        time_step: int = 0,
    ) -> EngageDecision:
        decision = super().decide(post, profile, peer_context, platform_context, time_step)
        pair_id = f"{profile.user_id}:{post.post_id}:{time_step}"
        if pair_id == self.unknown_pair_id:
            raise ProviderResponseProvenanceUnknown("offline repeated unknown")
        return decision


class _UnknownOnceAdapter(_LaneAdapter):
    def __init__(
        self,
        calls: list[str],
        *,
        unknown_pair_id: str,
        unknown_counts: dict[str, int],
    ) -> None:
        super().__init__(calls)
        self.unknown_pair_id = unknown_pair_id
        self.unknown_counts = unknown_counts

    def decide(
        self,
        post: PostContent,
        profile: UserProfile,
        peer_context: PeerContext,
        platform_context: PlatformContext | None = None,
        time_step: int = 0,
    ) -> EngageDecision:
        decision = super().decide(post, profile, peer_context, platform_context, time_step)
        pair_id = f"{profile.user_id}:{post.post_id}:{time_step}"
        if pair_id == self.unknown_pair_id and self.unknown_counts.get(pair_id, 0) == 0:
            self.unknown_counts[pair_id] = 1
            raise ProviderResponseProvenanceUnknown("offline first unknown")
        return decision


def _active_plan_ids(plan_payload: dict[str, object]) -> list[str]:
    lineage = plan_payload["parent_recovery_lineage"]  # type: ignore[index]
    stopped_identity = Path(lineage["stopped_recovery_identity"]["path"])  # type: ignore[index]
    active = plan_payload["recovery_snapshot"]["batch_snapshots"][-1]  # type: ignore[index]
    snapshot_path = stopped_identity.parent / active["snapshot_ref"]["relative_path"]
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    plans = [
        plan
        for message in snapshot["payload"]["messages"]
        for plan in message["selected_pair_plans"]
    ]
    plans.sort(key=lambda plan: plan["pair_schedule_position"])
    return [plan["pair_id"] for plan in plans]


def test_nested_plan_byte_drift_fails_before_adapter_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _automated_request(tmp_path, monkeypatch)
    request.nested_recovery_plan_path.chmod(0o644)
    request.nested_recovery_plan_path.write_bytes(
        request.nested_recovery_plan_path.read_bytes() + b"\n"
    )
    factory_calls: list[int] = []

    with pytest.raises(ValueError, match="nested recovery plan bytes"):
        FullPoolSegmentedAutomatedRecovery().run(
            request,
            adapter_factory=lambda lane_id: factory_calls.append(lane_id),  # type: ignore[arg-type,return-value]
        )

    assert factory_calls == []
    assert not request.recovery_workspace.exists()


def test_stopped_workspace_inventory_drift_fails_before_adapter_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _automated_request(tmp_path, monkeypatch)
    envelope = json.loads(request.nested_recovery_plan_path.read_text(encoding="utf-8"))
    stopped_identity = Path(
        envelope["payload"]["parent_recovery_lineage"]["stopped_recovery_identity"]["path"]
    )
    (stopped_identity.parent / "unexpected-after-plan.txt").write_text(
        "drift\n", encoding="utf-8"
    )
    factory_calls: list[int] = []

    with pytest.raises(ValueError, match="stopped recovery workspace.*changed"):
        FullPoolSegmentedAutomatedRecovery().run(
            request,
            adapter_factory=lambda lane_id: factory_calls.append(lane_id),  # type: ignore[arg-type,return-value]
        )

    assert factory_calls == []
    assert not request.recovery_workspace.exists()


def test_insufficient_retry_window_stops_before_adapter_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _automated_request(
        tmp_path,
        monkeypatch,
        logical_cap=90,
        physical_headroom=20,
    )
    factory_calls: list[int] = []

    result = FullPoolSegmentedAutomatedRecovery().run(
        request,
        adapter_factory=lambda lane_id: factory_calls.append(lane_id),  # type: ignore[arg-type,return-value]
    )

    assert result.status == "automation_exhausted"
    assert result.retry_physical_attempts == 0
    assert result.reconciliation_physical_attempts == 0
    assert result.source_root is None
    assert result.automation_exhausted_pair_ids
    assert factory_calls == []
    policy_records = [
        json.loads(line)
        for line in (
            request.recovery_workspace / "automated_recovery_policy_ledger.jsonl"
        ).read_text(encoding="utf-8").splitlines()
    ]
    assert [record["event_type"] for record in policy_records] == [
        "policy_created",
        "automation_exhausted",
    ]
    assert policy_records[-1]["payload"]["reason"] == "physical_cap_insufficient"


def test_policy_is_create_once_before_adapter_factory_and_failure_is_replayable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _automated_request(tmp_path, monkeypatch, logical_cap=90)
    plan_payload = json.loads(
        request.nested_recovery_plan_path.read_text(encoding="utf-8")
    )["payload"]
    factory_calls: list[int] = []

    def failed_factory(lane_id: int) -> object:
        factory_calls.append(lane_id)
        raise RuntimeError("offline factory failure")

    with pytest.raises(RuntimeError, match="offline factory failure"):
        FullPoolSegmentedAutomatedRecovery().run(
            request,
            adapter_factory=failed_factory,  # type: ignore[arg-type]
        )

    assert factory_calls == [0]
    policy_path = request.recovery_workspace / "automated_recovery_policy.json"
    policy_bytes = policy_path.read_bytes()
    policy = json.loads(policy_bytes)["payload"]
    assert policy["lifecycle"] == "active"
    assert policy["nested_recovery_plan_sha256"] == request.nested_recovery_plan_sha256
    assert policy["ordered_retry_pair_ids"] == [
        row["pair_id"]
        for row in plan_payload["recovery_snapshot"]["unresolved_pairs"]
    ]
    assert policy["maximum_reconciliations_per_pair"] == 1
    assert policy["maximum_attempts_per_dispatch"] == 3
    assert policy["logical_cap"] == 90
    assert policy["physical_cap"] == 120_120

    replay_factory_calls: list[int] = []

    def replay_failed_factory(lane_id: int) -> object:
        replay_factory_calls.append(lane_id)
        raise RuntimeError("replayed factory failure")

    with pytest.raises(RuntimeError, match="replayed factory failure"):
        FullPoolSegmentedAutomatedRecovery().run(
            request,
            adapter_factory=replay_failed_factory,  # type: ignore[arg-type]
        )
    assert replay_factory_calls == [0]
    assert policy_path.read_bytes() == policy_bytes
    assert not (request.recovery_workspace / "automated_recovery_status.json").exists()


def test_policy_drift_fails_closed_before_adapter_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _automated_request(tmp_path, monkeypatch, logical_cap=90)

    def failed_factory(_lane_id: int) -> object:
        raise RuntimeError("create policy only")

    with pytest.raises(RuntimeError, match="create policy only"):
        FullPoolSegmentedAutomatedRecovery().run(
            request,
            adapter_factory=failed_factory,  # type: ignore[arg-type]
        )
    policy_path = request.recovery_workspace / "automated_recovery_policy.json"
    policy_path.chmod(0o644)
    envelope = json.loads(policy_path.read_text(encoding="utf-8"))
    envelope["payload"]["maximum_reconciliations_per_pair"] = 2
    envelope["payload_sha256"] = hashlib.sha256(
        json.dumps(
            envelope["payload"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    policy_path.write_text(
        json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    replay_factory_calls: list[int] = []

    with pytest.raises(ValueError, match="policy drifted"):
        FullPoolSegmentedAutomatedRecovery().run(
            request,
            adapter_factory=lambda lane_id: replay_factory_calls.append(lane_id),  # type: ignore[arg-type,return-value]
        )

    assert replay_factory_calls == []
    assert not (request.recovery_workspace / "source-v3").exists()


def test_seven_retries_and_fresh_continuation_close_additive_source_v3(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _automated_request(tmp_path, monkeypatch, logical_cap=90)
    plan_payload = json.loads(
        request.nested_recovery_plan_path.read_text(encoding="utf-8")
    )["payload"]
    retry_ids = [
        row["pair_id"]
        for row in plan_payload["recovery_snapshot"]["unresolved_pairs"]
    ]
    calls: list[str] = []

    result = FullPoolSegmentedAutomatedRecovery().run(
        request,
        adapter_factory=lambda _lane_id: _LaneAdapter(calls),
    )

    assert result.status == "complete"
    assert result.logical_count == 90
    assert result.imported_durable_terminal_count == plan_payload[
        "recovery_snapshot"
    ]["durable_terminal_summary"]["count"]
    assert result.recovered_pair_ids == tuple(retry_ids)
    assert result.unknown_pair_ids == ()
    assert result.implementation_failed_pair_ids == ()
    assert result.automation_exhausted_pair_ids == ()
    assert result.fresh_logical_count == plan_payload["accounting"]["fresh_logical_remaining"]
    assert result.retry_physical_attempts == 7
    assert result.reconciliation_physical_attempts == 0
    assert result.continuation_physical_attempts == result.fresh_logical_count
    assert len(calls) == result.retry_physical_attempts + result.continuation_physical_attempts
    source_root = result.source_root
    assert source_root is not None
    assert source_root == request.recovery_workspace / "source-v3"
    assert source_root.is_dir()
    assert not (request.recovery_workspace / "source-v2").exists()
    manifest = json.loads((source_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "full-pool-segmented-source-v3"
    assert manifest["logical_count"] == 90
    assert manifest["counts"]["pair_rows"] == 90
    assert manifest["counts"]["terminal_rows"] == 90
    assert manifest["nested_recovery_lineage"]["nested_recovery_plan_sha256"] == (
        request.nested_recovery_plan_sha256
    )
    assert manifest["recovery_accounting"]["logical_retry_charge"] == 0
    assert manifest["recovery_accounting"]["retry_physical_attempts"] == 7
    assert manifest["recovery_accounting"]["reconciliation_physical_attempts"] == 0
    assert (source_root / "automated-recovery-policy.json").is_file()
    assert (source_root / "durable-pair-settlement-v2.jsonl").is_file()

    replay_calls: list[str] = []
    replay = FullPoolSegmentedAutomatedRecovery().run(
        request,
        adapter_factory=lambda _lane_id: _LaneAdapter(replay_calls),
    )
    assert replay == result
    assert replay_calls == []


def test_final_batch_replay_completes_policy_without_adapter_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _automated_request(tmp_path, monkeypatch, logical_cap=90)
    real_complete = automated_module.AutomatedRecoveryPolicy.complete
    complete_calls = 0

    def crash_before_policy_complete(self: object, **kwargs: object) -> None:
        nonlocal complete_calls
        complete_calls += 1
        if complete_calls == 1:
            raise RuntimeError("offline crash before policy completion")
        real_complete(self, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        automated_module.AutomatedRecoveryPolicy,
        "complete",
        crash_before_policy_complete,
    )
    with pytest.raises(RuntimeError, match="crash before policy completion"):
        FullPoolSegmentedAutomatedRecovery().run(
            request,
            adapter_factory=lambda _lane_id: _LaneAdapter([]),
        )
    policy_text = (
        request.recovery_workspace / "automated_recovery_policy_ledger.jsonl"
    ).read_text(encoding="utf-8")
    assert "policy_completed" not in policy_text

    factory_calls: list[int] = []
    result = FullPoolSegmentedAutomatedRecovery().run(
        request,
        adapter_factory=lambda lane_id: factory_calls.append(lane_id),  # type: ignore[arg-type,return-value]
    )
    assert result.status == "complete"
    assert factory_calls == []


def test_policy_completed_replay_closes_source_without_adapter_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _automated_request(tmp_path, monkeypatch, logical_cap=90)
    calls: list[str] = []
    real_close = automated_module._SourceV3Closure.close
    close_calls = 0

    def crash_before_source(self: object, **kwargs: object) -> object:
        nonlocal close_calls
        close_calls += 1
        if close_calls == 1:
            raise RuntimeError("offline crash before source-v3 closure")
        return real_close(self, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(automated_module._SourceV3Closure, "close", crash_before_source)
    with pytest.raises(RuntimeError, match="crash before source-v3 closure"):
        FullPoolSegmentedAutomatedRecovery().run(
            request,
            adapter_factory=lambda _lane_id: _LaneAdapter(calls),
        )
    assert not (request.recovery_workspace / "source-v3").exists()
    assert not (request.recovery_workspace / "automated_recovery_status.json").exists()

    factory_calls: list[int] = []
    result = FullPoolSegmentedAutomatedRecovery().run(
        request,
        adapter_factory=lambda lane_id: factory_calls.append(lane_id),  # type: ignore[arg-type,return-value]
    )
    assert result.status == "complete"
    assert result.source_root == request.recovery_workspace / "source-v3"
    assert factory_calls == []


def test_incomplete_source_staging_rebuilds_from_completed_policy_without_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _automated_request(tmp_path, monkeypatch, logical_cap=90)
    real_replace = automated_module._replace_json
    replace_calls = 0

    def crash_in_staging(path: Path, payload: object) -> None:
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls == 1:
            raise RuntimeError("offline crash in source-v3 staging")
        real_replace(path, payload)  # type: ignore[arg-type]

    monkeypatch.setattr(automated_module, "_replace_json", crash_in_staging)
    with pytest.raises(RuntimeError, match="crash in source-v3 staging"):
        FullPoolSegmentedAutomatedRecovery().run(
            request,
            adapter_factory=lambda _lane_id: _LaneAdapter([]),
        )
    assert (request.recovery_workspace / ".source-v3.staging").is_dir()
    assert not (request.recovery_workspace / "source-v3").exists()

    factory_calls: list[int] = []
    result = FullPoolSegmentedAutomatedRecovery().run(
        request,
        adapter_factory=lambda lane_id: factory_calls.append(lane_id),  # type: ignore[arg-type,return-value]
    )
    assert result.status == "complete"
    assert factory_calls == []
    assert not (request.recovery_workspace / ".source-v3.staging").exists()


def test_published_source_replay_recovers_status_without_adapter_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _automated_request(tmp_path, monkeypatch, logical_cap=90)
    real_write_status = automated_module._write_status
    write_calls = 0

    def crash_before_status(*args: object, **kwargs: object) -> None:
        nonlocal write_calls
        write_calls += 1
        if write_calls == 1:
            raise RuntimeError("offline crash before complete status")
        real_write_status(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(automated_module, "_write_status", crash_before_status)
    with pytest.raises(RuntimeError, match="crash before complete status"):
        FullPoolSegmentedAutomatedRecovery().run(
            request,
            adapter_factory=lambda _lane_id: _LaneAdapter([]),
        )
    source = request.recovery_workspace / "source-v3"
    manifest_bytes = (source / "manifest.json").read_bytes()
    assert source.is_dir()
    assert not (request.recovery_workspace / "automated_recovery_status.json").exists()

    factory_calls: list[int] = []
    result = FullPoolSegmentedAutomatedRecovery().run(
        request,
        adapter_factory=lambda lane_id: factory_calls.append(lane_id),  # type: ignore[arg-type,return-value]
    )
    assert result.status == "complete"
    assert factory_calls == []
    assert (source / "manifest.json").read_bytes() == manifest_bytes


def test_complete_source_v3_tamper_fails_before_adapter_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _automated_request(tmp_path, monkeypatch, logical_cap=90)
    result = FullPoolSegmentedAutomatedRecovery().run(
        request,
        adapter_factory=lambda _lane_id: _LaneAdapter([]),
    )
    assert result.source_root is not None
    terminal_path = result.source_root / "terminal_rows.jsonl"
    terminal_path.write_bytes(terminal_path.read_bytes() + b"\n")
    factory_calls: list[int] = []

    with pytest.raises(ValueError, match="artifact bytes"):
        FullPoolSegmentedAutomatedRecovery().run(
            request,
            adapter_factory=lambda lane_id: factory_calls.append(lane_id),  # type: ignore[arg-type,return-value]
        )

    assert factory_calls == []


@pytest.mark.parametrize("target_index", [0, 3, 6])
def test_retry_wave_unknown_reconciles_only_that_pair_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_index: int,
) -> None:
    request = _automated_request(tmp_path, monkeypatch, logical_cap=90)
    plan_payload = json.loads(
        request.nested_recovery_plan_path.read_text(encoding="utf-8")
    )["payload"]
    retry_ids = [
        row["pair_id"]
        for row in plan_payload["recovery_snapshot"]["unresolved_pairs"]
    ]
    target_pair_id = retry_ids[target_index]
    calls: list[str] = []
    unknown_counts: dict[str, int] = {}

    result = FullPoolSegmentedAutomatedRecovery().run(
        request,
        adapter_factory=lambda _lane_id: _UnknownOnceAdapter(
            calls,
            unknown_pair_id=target_pair_id,
            unknown_counts=unknown_counts,
        ),
    )

    assert result.status == "complete"
    assert result.recovered_pair_ids == tuple(retry_ids)
    assert result.retry_physical_attempts == 7
    assert result.reconciliation_physical_attempts == 1
    assert calls.count(target_pair_id) == 2
    assert all(calls.count(pair_id) == 1 for pair_id in retry_ids if pair_id != target_pair_id)
    policy_records = [
        json.loads(line)
        for line in (
            request.recovery_workspace / "automated_recovery_policy_ledger.jsonl"
        ).read_text(encoding="utf-8").splitlines()
    ]
    assert [record["event_type"] for record in policy_records] == [
        "policy_created",
        "reconciliation_slot_consumed",
        "reconciliation_resolved",
        "policy_completed",
    ]
    assert policy_records[1]["payload"]["pair_id"] == target_pair_id
    assert policy_records[1]["payload"]["physical_reservation"] == 3
    assert result.source_root is not None
    manifest = json.loads((result.source_root / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["settlement_v2"]["reconciliation_journals"]) == 1
    assert manifest["settlement_v2"]["reconciliation_journals"][0]["pair_id"] == target_pair_id


def test_resolved_reconciliation_crash_replays_without_consuming_second_slot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _automated_request(tmp_path, monkeypatch, logical_cap=90)
    plan_payload = json.loads(
        request.nested_recovery_plan_path.read_text(encoding="utf-8")
    )["payload"]
    retry_ids = [
        row["pair_id"]
        for row in plan_payload["recovery_snapshot"]["unresolved_pairs"]
    ]
    target_pair_id = retry_ids[0]
    calls: list[str] = []
    unknown_counts: dict[str, int] = {}
    real_append = automated_module._ContinuationLedger.append
    crashed = False

    def crash_after_resolved(
        self: object,
        event_type: str,
        payload: object,
    ) -> None:
        nonlocal crashed
        policy_path = request.recovery_workspace / "automated_recovery_policy_ledger.jsonl"
        resolved = policy_path.is_file() and "reconciliation_resolved" in policy_path.read_text(
            encoding="utf-8"
        )
        if (
            not crashed
            and resolved
            and event_type == "pair_terminal"
            and payload["pair_id"] == target_pair_id  # type: ignore[index]
        ):
            crashed = True
            raise RuntimeError("offline crash after reconciliation resolution")
        real_append(self, event_type, payload)  # type: ignore[arg-type]

    monkeypatch.setattr(automated_module._ContinuationLedger, "append", crash_after_resolved)
    with pytest.raises(RuntimeError, match="crash after reconciliation resolution"):
        FullPoolSegmentedAutomatedRecovery().run(
            request,
            adapter_factory=lambda _lane_id: _UnknownOnceAdapter(
                calls,
                unknown_pair_id=target_pair_id,
                unknown_counts=unknown_counts,
            ),
        )
    assert calls.count(target_pair_id) == 2

    replay_calls: list[str] = []
    result = FullPoolSegmentedAutomatedRecovery().run(
        request,
        adapter_factory=lambda _lane_id: _LaneAdapter(replay_calls),
    )
    assert result.status == "complete"
    assert target_pair_id not in replay_calls
    assert result.reconciliation_physical_attempts == 1
    policy_records = [
        json.loads(line)
        for line in (
            request.recovery_workspace / "automated_recovery_policy_ledger.jsonl"
        ).read_text(encoding="utf-8").splitlines()
    ]
    assert [record["event_type"] for record in policy_records].count(
        "reconciliation_slot_consumed"
    ) == 1
    assert "automation_exhausted" not in {
        record["event_type"] for record in policy_records
    }


def test_inflight_retry_wave_reconciles_only_uncaptured_pairs_on_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _automated_request(tmp_path, monkeypatch, logical_cap=90)
    plan_payload = json.loads(
        request.nested_recovery_plan_path.read_text(encoding="utf-8")
    )["payload"]
    retry_ids = [
        row["pair_id"]
        for row in plan_payload["recovery_snapshot"]["unresolved_pairs"]
    ]
    first_calls: list[str] = []
    real_append = automated_module.settlement_module._append_jsonl
    crashed = False

    def crash_after_first_capture(path: Path, payload: object) -> None:
        nonlocal crashed
        real_append(path, payload)  # type: ignore[arg-type]
        if not crashed and payload["event_type"] == "pair_settled":  # type: ignore[index]
            crashed = True
            raise RuntimeError("offline crash after one pair capture")

    monkeypatch.setattr(
        automated_module.settlement_module,
        "_append_jsonl",
        crash_after_first_capture,
    )
    with pytest.raises(RuntimeError, match="crash after one pair capture"):
        FullPoolSegmentedAutomatedRecovery().run(
            request,
            adapter_factory=lambda _lane_id: _LaneAdapter(first_calls),
        )
    assert sorted(first_calls) == sorted(retry_ids)
    records = [
        json.loads(line)
        for line in (
            request.recovery_workspace / "durable_pair_settlement_v2.jsonl"
        ).read_text(encoding="utf-8").splitlines()
    ]
    captured_pair_ids = [
        record["payload"]["pair_id"]
        for record in records
        if record["event_type"] == "pair_settled"
    ]
    assert len(captured_pair_ids) == 1

    replay_calls: list[str] = []
    result = FullPoolSegmentedAutomatedRecovery().run(
        request,
        adapter_factory=lambda _lane_id: _LaneAdapter(replay_calls),
    )
    assert result.status == "complete"
    assert captured_pair_ids[0] not in replay_calls
    assert all(replay_calls.count(pair_id) == 1 for pair_id in retry_ids if pair_id not in captured_pair_ids)
    assert result.retry_physical_attempts == 1
    assert result.new_uncertainty_physical_charge == 18
    assert result.reconciliation_physical_attempts == 6


def test_closed_retry_settlement_replays_without_recalling_captured_pairs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _automated_request(tmp_path, monkeypatch, logical_cap=90)
    plan_payload = json.loads(
        request.nested_recovery_plan_path.read_text(encoding="utf-8")
    )["payload"]
    retry_ids = [
        row["pair_id"]
        for row in plan_payload["recovery_snapshot"]["unresolved_pairs"]
    ]
    first_calls: list[str] = []
    real_register = automated_module._register_results
    register_calls = 0

    def crash_before_register(*args: object, **kwargs: object) -> object:
        nonlocal register_calls
        register_calls += 1
        if register_calls == 1:
            raise RuntimeError("offline crash after retry settlement")
        return real_register(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(automated_module, "_register_results", crash_before_register)
    with pytest.raises(RuntimeError, match="crash after retry settlement"):
        FullPoolSegmentedAutomatedRecovery().run(
            request,
            adapter_factory=lambda _lane_id: _LaneAdapter(first_calls),
        )
    assert first_calls == retry_ids

    replay_calls: list[str] = []
    result = FullPoolSegmentedAutomatedRecovery().run(
        request,
        adapter_factory=lambda _lane_id: _LaneAdapter(replay_calls),
    )
    assert result.status == "complete"
    assert all(pair_id not in replay_calls for pair_id in retry_ids)
    assert len(replay_calls) == result.fresh_logical_count
    assert result.retry_physical_attempts == 7


def test_reconciliation_slot_crash_replays_as_automation_exhausted_without_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _automated_request(tmp_path, monkeypatch, logical_cap=90)
    plan_payload = json.loads(
        request.nested_recovery_plan_path.read_text(encoding="utf-8")
    )["payload"]
    retry_ids = [
        row["pair_id"]
        for row in plan_payload["recovery_snapshot"]["unresolved_pairs"]
    ]
    target_pair_id = retry_ids[2]
    calls: list[str] = []
    unknown_counts: dict[str, int] = {}
    real_settle = automated_module.DurablePairSettlement.settle_wave

    def crash_after_slot(self: object, *args: object, **kwargs: object) -> object:
        workspace = self.workspace  # type: ignore[attr-defined]
        if workspace.parent.name == "reconciliation-settlements":
            raise RuntimeError("offline crash after reconciliation slot")
        return real_settle(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        automated_module.DurablePairSettlement,
        "settle_wave",
        crash_after_slot,
    )
    with pytest.raises(RuntimeError, match="crash after reconciliation slot"):
        FullPoolSegmentedAutomatedRecovery().run(
            request,
            adapter_factory=lambda _lane_id: _UnknownOnceAdapter(
                calls,
                unknown_pair_id=target_pair_id,
                unknown_counts=unknown_counts,
            ),
        )
    assert calls.count(target_pair_id) == 1

    replay_factory_calls: list[int] = []
    replay = FullPoolSegmentedAutomatedRecovery().run(
        request,
        adapter_factory=lambda lane_id: replay_factory_calls.append(lane_id),  # type: ignore[arg-type,return-value]
    )
    assert replay.status == "automation_exhausted"
    assert replay.automation_exhausted_pair_ids == (target_pair_id,)
    assert replay.reconciliation_physical_attempts == 0
    assert replay.new_uncertainty_physical_charge == 3
    assert replay_factory_calls == []
    assert calls.count(target_pair_id) == 1
    assert not (request.recovery_workspace / "source-v3").exists()
    policy_records = [
        json.loads(line)
        for line in (
            request.recovery_workspace / "automated_recovery_policy_ledger.jsonl"
        ).read_text(encoding="utf-8").splitlines()
    ]
    assert [record["event_type"] for record in policy_records] == [
        "policy_created",
        "reconciliation_slot_consumed",
        "automation_exhausted",
    ]


def test_implementation_failure_preserves_siblings_without_reconciliation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _automated_request(tmp_path, monkeypatch, logical_cap=90)
    plan_payload = json.loads(
        request.nested_recovery_plan_path.read_text(encoding="utf-8")
    )["payload"]
    retry_ids = [
        row["pair_id"]
        for row in plan_payload["recovery_snapshot"]["unresolved_pairs"]
    ]
    target_pair_id = retry_ids[-1]
    calls: list[str] = []

    result = FullPoolSegmentedAutomatedRecovery().run(
        request,
        adapter_factory=lambda _lane_id: _ImplementationFailureAdapter(
            calls, failed_pair_id=target_pair_id
        ),
    )

    assert result.status == "implementation_failed"
    assert result.source_root is None
    assert result.implementation_failed_pair_ids == (target_pair_id,)
    assert result.unknown_pair_ids == ()
    assert result.reconciliation_physical_attempts == 0
    assert all(calls.count(pair_id) == 1 for pair_id in retry_ids)
    policy_records = [
        json.loads(line)
        for line in (
            request.recovery_workspace / "automated_recovery_policy_ledger.jsonl"
        ).read_text(encoding="utf-8").splitlines()
    ]
    assert [record["event_type"] for record in policy_records] == ["policy_created"]
    main_settlements = [
        json.loads(line)
        for line in (
            request.recovery_workspace / "durable_pair_settlement_v2.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if json.loads(line)["event_type"] == "pair_settled"
    ]
    assert sum(
        row["payload"]["outcome"]["kind"] == "terminal"
        for row in main_settlements
    ) == 6
    assert not (request.recovery_workspace / "source-v3").exists()


def test_second_unknown_stops_automation_and_preserves_retry_siblings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _automated_request(tmp_path, monkeypatch, logical_cap=90)
    plan_payload = json.loads(
        request.nested_recovery_plan_path.read_text(encoding="utf-8")
    )["payload"]
    retry_ids = [
        row["pair_id"]
        for row in plan_payload["recovery_snapshot"]["unresolved_pairs"]
    ]
    target_pair_id = retry_ids[0]
    calls: list[str] = []

    result = FullPoolSegmentedAutomatedRecovery().run(
        request,
        adapter_factory=lambda _lane_id: _AlwaysUnknownAdapter(
            calls, unknown_pair_id=target_pair_id
        ),
    )

    assert result.status == "automation_exhausted"
    assert result.source_root is None
    assert result.source_manifest_sha256 is None
    assert result.unknown_pair_ids == (target_pair_id,)
    assert result.automation_exhausted_pair_ids == (target_pair_id,)
    assert result.retry_physical_attempts == 7
    assert result.reconciliation_physical_attempts == 1
    assert calls.count(target_pair_id) == 2
    assert all(calls.count(pair_id) == 1 for pair_id in retry_ids[1:])
    main_settlements = [
        json.loads(line)
        for line in (
            request.recovery_workspace / "durable_pair_settlement_v2.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if json.loads(line)["event_type"] == "pair_settled"
    ]
    assert len(main_settlements) == 7
    assert sum(
        row["payload"]["outcome"]["kind"] == "terminal"
        for row in main_settlements
    ) == 6
    assert not (request.recovery_workspace / "source-v3").exists()

    replay_factory_calls: list[int] = []
    replay = FullPoolSegmentedAutomatedRecovery().run(
        request,
        adapter_factory=lambda lane_id: replay_factory_calls.append(lane_id),  # type: ignore[arg-type,return-value]
    )
    assert replay == result
    assert replay_factory_calls == []


def test_fresh_wave_unknown_uses_the_same_single_pair_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _automated_request(tmp_path, monkeypatch, logical_cap=90)
    plan_payload = json.loads(
        request.nested_recovery_plan_path.read_text(encoding="utf-8")
    )["payload"]
    active_ids = _active_plan_ids(plan_payload)
    durable_count = plan_payload["recovery_snapshot"]["active_durable_terminal_count"]
    target_pair_id = active_ids[durable_count + 7]
    calls: list[str] = []
    unknown_counts: dict[str, int] = {}

    result = FullPoolSegmentedAutomatedRecovery().run(
        request,
        adapter_factory=lambda _lane_id: _UnknownOnceAdapter(
            calls,
            unknown_pair_id=target_pair_id,
            unknown_counts=unknown_counts,
        ),
    )

    assert result.status == "complete"
    assert result.reconciliation_physical_attempts == 1
    assert calls.count(target_pair_id) == 2
    assert result.continuation_physical_attempts == result.fresh_logical_count
    policy_records = [
        json.loads(line)
        for line in (
            request.recovery_workspace / "automated_recovery_policy_ledger.jsonl"
        ).read_text(encoding="utf-8").splitlines()
    ]
    consumed = [
        record
        for record in policy_records
        if record["event_type"] == "reconciliation_slot_consumed"
    ]
    assert [record["payload"]["pair_id"] for record in consumed] == [target_pair_id]
