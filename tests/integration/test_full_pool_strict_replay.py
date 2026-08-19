from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from time import sleep
from typing import Literal, cast

import pytest

import llm_abm_sim.durable_pair_settlement as settlement_module
import llm_abm_sim.full_pool_strict_replay as strict_module
from llm_abm_sim.concurrent_execution_journal import ConcurrentExecutionJournal
from llm_abm_sim.concurrent_message_experiment import ConcurrentMessageExperimentConfig
from llm_abm_sim.decision import (
    EngageDecision,
    LLMDecisionAdapter,
    ProviderDecisionError,
    ProviderResponseProvenanceUnknown,
)
from llm_abm_sim.full_pool_strict_replay import (
    FULL_POOL_SOURCE_V4_SCHEMA,
    STRICT_PAIR_POLICY_LEDGER_FILE,
    StrictFreshReplayRequest,
    StrictFreshReplayResult,
    StrictFreshReplayStatus,
    StrictFullPoolFormalReplay,
    StrictRejectedHistoryReference,
    strict_formal_provider_contract,
)
from llm_abm_sim.provider_accounting import (
    ProviderAccounting,
    ProviderAccountingTracker,
    ProviderResponseEnvelope,
)
from llm_abm_sim.schemas import PeerContext, PlatformContext, PostContent, UserProfile
from tests.integration.test_full_pool_segmented_multibatch import _dataset

_Outcome = Literal[
    "succeeded", "provider_failed", "provenance_unknown", "implementation_failed"
]


class _StrictAdapter(LLMDecisionAdapter):
    def __init__(
        self,
        lane_id: int,
        calls: list[str],
        *,
        target_lane: int = 4,
        initial_outcome: _Outcome = "provider_failed",
        reconciliation_outcome: _Outcome = "succeeded",
        reconciliation_action: Literal["ignore", "like", "comment", "share"] = "like",
        success_attempts: int = 1,
    ) -> None:
        self.lane_id = lane_id
        self.calls = calls
        self.target_lane = target_lane
        self.initial_outcome: _Outcome = initial_outcome
        self.reconciliation_outcome: _Outcome = reconciliation_outcome
        self.reconciliation_action: Literal["ignore", "like", "comment", "share"] = (
            reconciliation_action
        )
        self.success_attempts = success_attempts
        self.request_invocations = 0
        self.external_request_invocations = 0
        self.prompt_version = str(strict_formal_provider_contract()["prompt_version"])
        self.safe_metadata = strict_formal_provider_contract()
        self.failed_pair_id: str | None = None
        self.pair_calls: dict[str, int] = {}

    def decide(
        self,
        post: PostContent,
        profile: UserProfile,
        peer_context: PeerContext,
        platform_context: PlatformContext | None = None,
        time_step: int = 0,
    ) -> EngageDecision:
        del peer_context, platform_context
        pair_id = f"{profile.user_id}:{post.post_id}:{time_step}"
        self.calls.append(pair_id)
        ordinal = self.pair_calls.get(pair_id, 0) + 1
        self.pair_calls[pair_id] = ordinal
        if self.lane_id == self.target_lane and time_step == 0 and self.failed_pair_id is None:
            self.failed_pair_id = pair_id
        outcome: _Outcome = "succeeded"
        if pair_id == self.failed_pair_id:
            outcome = self.initial_outcome if ordinal == 1 else self.reconciliation_outcome
        attempts = 3 if outcome == "provider_failed" else self.success_attempts
        self.request_invocations += attempts
        self.external_request_invocations += attempts
        if outcome == "provider_failed":
            raise ProviderDecisionError(TimeoutError("offline exhausted retries"))
        if outcome == "provenance_unknown":
            raise ProviderResponseProvenanceUnknown("offline unknown response provenance")
        if outcome == "implementation_failed":
            raise ValueError("offline allowlisted implementation failure")
        action = self.reconciliation_action if pair_id == self.failed_pair_id else "ignore"
        return EngageDecision(
            engage=action != "ignore",
            probability=0.9 if action != "ignore" else 0.1,
            confidence=0.9,
            action=action,
            reason="offline strict replay",
            decision_source="offline_strict_replay",
            provider_metadata={"model": "gpt-5.6-sol"},
        )


class _ContextStrictAdapter(_StrictAdapter):
    def __init__(
        self,
        lane_id: int,
        calls: list[str],
        contexts: dict[str, list[dict[str, object]]],
    ) -> None:
        super().__init__(lane_id, calls)
        self.contexts = contexts

    def decide(
        self,
        post: PostContent,
        profile: UserProfile,
        peer_context: PeerContext,
        platform_context: PlatformContext | None = None,
        time_step: int = 0,
    ) -> EngageDecision:
        pair_id = f"{profile.user_id}:{post.post_id}:{time_step}"
        self.contexts.setdefault(pair_id, []).append(
            {
                "post": post.model_dump(mode="json"),
                "profile": profile.model_dump(mode="json"),
                "peer_context": peer_context.model_dump(mode="json"),
                "platform_context": (
                    PlatformContext() if platform_context is None else platform_context
                ).model_dump(mode="json"),
                "time_step": time_step,
            }
        )
        return super().decide(post, profile, peer_context, platform_context, time_step)


class _DelayedStrictAdapter(_StrictAdapter):
    def __init__(self, *args: object, reverse: bool, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.reverse = reverse

    def decide(
        self,
        post: PostContent,
        profile: UserProfile,
        peer_context: PeerContext,
        platform_context: PlatformContext | None = None,
        time_step: int = 0,
    ) -> EngageDecision:
        delay_rank = 9 - self.lane_id if self.reverse else self.lane_id
        sleep(delay_rank * 0.003)
        return super().decide(post, profile, peer_context, platform_context, time_step)


def _rejected_history(tmp_path: Path) -> StrictRejectedHistoryReference:
    source = tmp_path / "rejected-source-v3"
    source.mkdir(parents=True, exist_ok=True)
    manifest = source / "manifest.json"
    manifest.write_text(
        '{"schema_version":"full-pool-segmented-source-v3","status":"mixed"}\n',
        encoding="utf-8",
    )
    return StrictRejectedHistoryReference(
        source_root=source,
        manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
        rejection_reason="validation_mixed_provider_evidence",
    )


def _request(tmp_path: Path, *, physical_cap: int = 120_120) -> StrictFreshReplayRequest:
    dataset = _dataset(tmp_path, user_count=8)
    config = ConcurrentMessageExperimentConfig(
        dataset_dir=dataset,
        sample_size=8,
        horizon=2,
        delivery_capacity=4,
        configuration_profile="validation",
    )
    return StrictFreshReplayRequest(
        config=config,
        workspace=tmp_path / "strict-fresh-replay",
        replay_id="offline-strict-fresh-v1",
        provider_contract=strict_formal_provider_contract(),
        rejected_history=_rejected_history(tmp_path),
        seed_top_k_per_proxy=2,
        logical_cap=24,
        physical_cap=physical_cap,
    )


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_provider_failed_is_provisional_until_same_context_reconciliation_and_batch_barrier(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    calls: list[str] = []
    adapters: dict[int, _StrictAdapter] = {}

    def factory(lane_id: int) -> _StrictAdapter:
        adapter = _StrictAdapter(lane_id, calls)
        adapters[lane_id] = adapter
        return adapter

    result = StrictFullPoolFormalReplay().run(request, adapter_factory=factory)

    assert result.status is StrictFreshReplayStatus.COMPLETE
    assert result.committed_batch_count == 2
    assert result.logical_count == 24
    assert result.final_succeeded_terminal_count == 24
    assert result.reconciliation_dispatch_count == 1
    assert result.settled_actual_attempts == 27
    assert result.dispatched_without_settlement_uncertainty == 0
    assert result.charged_physical_attempts == 27
    assert result.active_physical_reservations == 0

    failed_pair_id = adapters[4].failed_pair_id
    assert failed_pair_id is not None
    assert calls.count(failed_pair_id) == 2

    original_records = _jsonl(
        request.workspace / "original-settlements" / "durable_pair_settlement_v2.jsonl"
    )
    first_wave = [
        row for row in original_records if row["event_type"] == "pair_settled"
    ][:10]
    assert len(first_wave) == 10
    assert sum(
        row["payload"]["outcome"].get("terminal_row", {}).get("terminal_status")  # type: ignore[index,union-attr]
        == "provider_failed"
        for row in first_wave
    ) == 1
    assert sum(
        row["payload"]["outcome"].get("terminal_row", {}).get("terminal_status")  # type: ignore[index,union-attr]
        == "succeeded"
        for row in first_wave
    ) == 9

    policy_records = _jsonl(request.workspace / STRICT_PAIR_POLICY_LEDGER_FILE)
    assert [row["event_type"] for row in policy_records] == [
        "policy_created",
        "reconciliation_dispatched",
        "reconciliation_resolved",
        "runtime_completed",
    ]
    dispatch = policy_records[1]["payload"]  # type: ignore[assignment]
    assert dispatch["pair_id"] == failed_pair_id  # type: ignore[index]
    assert dispatch["source_kind"] == "provider_failed"  # type: ignore[index]
    assert dispatch["physical_reservation"] == 3  # type: ignore[index]
    assert "slot" not in dispatch  # type: ignore[operator]

    replay = ConcurrentExecutionJournal.open_existing(request.workspace).replay()
    batch_snapshots = [
        row for row in replay["records"] if row.get("record_type") == "snapshot"
    ]
    assert len(batch_snapshots) == 2
    failed_user_id = failed_pair_id.split(":", 1)[0]
    assert batch_snapshots[0]["snapshot_document"]["payload"][
        "frozen_campaign_engaged_user_ids"
    ] == []
    assert failed_user_id in batch_snapshots[1]["snapshot_document"]["payload"][
        "frozen_campaign_engaged_user_ids"
    ]

    committed_chunks = sorted(
        (request.workspace / "concurrent_runtime_batch_spool").glob("batch-*.json")
    )
    assert len(committed_chunks) == 2
    first_chunk = json.loads(committed_chunks[0].read_text(encoding="utf-8"))
    assert len(first_chunk["rows"]["terminal_rows"]) == 12
    assert {row["terminal_status"] for row in first_chunk["rows"]["terminal_rows"]} == {
        "succeeded"
    }
    assert not (request.workspace / "source-v4").exists()


@pytest.mark.parametrize("action", ["ignore", "like", "comment", "share"])
def test_reconciliation_action_becomes_one_final_success_and_feedback_waits_for_barrier(
    tmp_path: Path,
    action: Literal["ignore", "like", "comment", "share"],
) -> None:
    request = _request(tmp_path)
    adapters: dict[int, _StrictAdapter] = {}

    def factory(lane_id: int) -> _StrictAdapter:
        adapter = _StrictAdapter(lane_id, [], reconciliation_action=action)
        adapters[lane_id] = adapter
        return adapter

    result = StrictFullPoolFormalReplay().run(request, adapter_factory=factory)

    assert result.status is StrictFreshReplayStatus.COMPLETE
    target_pair_id = adapters[4].failed_pair_id
    assert target_pair_id is not None
    target_user_id = target_pair_id.split(":", 1)[0]
    first_chunk = json.loads(
        (request.workspace / "concurrent_runtime_batch_spool" / "batch-000000.json").read_text(
            encoding="utf-8"
        )
    )
    target_terminals = [
        row for row in first_chunk["rows"]["terminal_rows"] if row["pair_id"] == target_pair_id
    ]
    assert len(target_terminals) == 1
    assert target_terminals[0]["terminal_status"] == "succeeded"
    assert target_terminals[0]["action"] == action

    replay = ConcurrentExecutionJournal.open_existing(request.workspace).replay()
    second_snapshot = [
        row for row in replay["records"] if row.get("record_type") == "snapshot"
    ][1]
    frozen_feedback = second_snapshot["snapshot_document"]["payload"][
        "frozen_campaign_engaged_user_ids"
    ]
    assert (target_user_id in frozen_feedback) is (action != "ignore")


def test_reconciliation_reuses_the_exact_frozen_pair_context_and_plan_identity(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    calls: list[str] = []
    contexts: dict[str, list[dict[str, object]]] = {}
    adapters: dict[int, _ContextStrictAdapter] = {}

    def factory(lane_id: int) -> _ContextStrictAdapter:
        adapter = _ContextStrictAdapter(lane_id, calls, contexts)
        adapters[lane_id] = adapter
        return adapter

    result = StrictFullPoolFormalReplay().run(request, adapter_factory=factory)

    assert result.status is StrictFreshReplayStatus.COMPLETE
    target_pair_id = adapters[4].failed_pair_id
    assert target_pair_id is not None
    assert contexts[target_pair_id][0] == contexts[target_pair_id][1]
    original_records = _jsonl(
        request.workspace / "original-settlements" / "durable_pair_settlement_v2.jsonl"
    )
    original_plan = next(
        pair
        for row in original_records
        if row["event_type"] == "wave_reserved"
        for pair in row["payload"]["pairs"]  # type: ignore[index]
        if pair["pair_id"] == target_pair_id
    )
    policy_dispatch = next(
        row["payload"]
        for row in _jsonl(request.workspace / STRICT_PAIR_POLICY_LEDGER_FILE)
        if row["event_type"] == "reconciliation_dispatched"
    )
    assert policy_dispatch["plan_identity_sha256"] == original_plan[  # type: ignore[index]
        "plan_identity_sha256"
    ]


@pytest.mark.parametrize(
    ("reconciliation_outcome", "expected_status", "expected_actual"),
    [
        ("provider_failed", StrictFreshReplayStatus.STRICT_STOP_PROVIDER_FAILED, 15),
        (
            "provenance_unknown",
            StrictFreshReplayStatus.STRICT_STOP_PROVENANCE_UNKNOWN,
            13,
        ),
        (
            "implementation_failed",
            StrictFreshReplayStatus.STRICT_STOP_IMPLEMENTATION_FAILED,
            13,
        ),
    ],
)
def test_reconciliation_non_success_strict_stops_before_any_batch_commit_or_later_dispatch(
    tmp_path: Path,
    reconciliation_outcome: _Outcome,
    expected_status: StrictFreshReplayStatus,
    expected_actual: int,
) -> None:
    request = _request(tmp_path)
    calls: list[str] = []
    adapters: dict[int, _StrictAdapter] = {}

    def factory(lane_id: int) -> _StrictAdapter:
        adapter = _StrictAdapter(
            lane_id,
            calls,
            reconciliation_outcome=reconciliation_outcome,
        )
        adapters[lane_id] = adapter
        return adapter

    result = StrictFullPoolFormalReplay().run(request, adapter_factory=factory)

    assert result.status is expected_status
    assert result.committed_batch_count == 0
    assert result.logical_count == 10
    assert result.final_succeeded_terminal_count == 9
    assert result.reconciliation_dispatch_count == 1
    assert result.settled_actual_attempts == expected_actual
    assert result.dispatched_without_settlement_uncertainty == 0
    assert result.charged_physical_attempts == expected_actual
    target_pair_id = adapters[4].failed_pair_id
    assert target_pair_id is not None
    assert calls.count(target_pair_id) == 2
    assert len(calls) == 11
    assert not any(pair_id.endswith(":1") for pair_id in calls)

    policy_records = _jsonl(request.workspace / STRICT_PAIR_POLICY_LEDGER_FILE)
    assert [row["event_type"] for row in policy_records] == [
        "policy_created",
        "reconciliation_dispatched",
        "strict_stopped",
    ]
    runtime_records = ConcurrentExecutionJournal.open_existing(request.workspace).replay()[
        "records"
    ]
    assert not any(row.get("event_type") == "variant_terminal" for row in runtime_records)
    assert not (request.workspace / "concurrent_runtime_batch_spool").exists()
    assert not (request.workspace / "source-v4").exists()


def test_initial_unknown_consumes_the_only_dispatch_and_second_unknown_strict_stops(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    calls: list[str] = []
    adapters: dict[int, _StrictAdapter] = {}

    def factory(lane_id: int) -> _StrictAdapter:
        adapter = _StrictAdapter(
            lane_id,
            calls,
            initial_outcome="provenance_unknown",
            reconciliation_outcome="provenance_unknown",
        )
        adapters[lane_id] = adapter
        return adapter

    result = StrictFullPoolFormalReplay().run(request, adapter_factory=factory)

    assert result.status is StrictFreshReplayStatus.STRICT_STOP_PROVENANCE_UNKNOWN
    assert result.committed_batch_count == 0
    assert result.logical_count == 10
    assert result.final_succeeded_terminal_count == 9
    assert result.reconciliation_dispatch_count == 1
    assert result.settled_actual_attempts == 11
    target_pair_id = adapters[4].failed_pair_id
    assert target_pair_id is not None
    assert calls.count(target_pair_id) == 2
    policy_records = _jsonl(request.workspace / STRICT_PAIR_POLICY_LEDGER_FILE)
    dispatched = [
        row for row in policy_records if row["event_type"] == "reconciliation_dispatched"
    ]
    assert len(dispatched) == 1
    assert dispatched[0]["payload"]["source_kind"] == "provenance_unknown"  # type: ignore[index]
    assert "slot" not in dispatched[0]["payload"]  # type: ignore[operator]


def test_original_implementation_failure_keeps_only_allowlisted_audit_and_never_reconciles(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    calls: list[str] = []
    adapters: dict[int, _StrictAdapter] = {}

    def factory(lane_id: int) -> _StrictAdapter:
        adapter = _StrictAdapter(
            lane_id,
            calls,
            initial_outcome="implementation_failed",
        )
        adapters[lane_id] = adapter
        return adapter

    result = StrictFullPoolFormalReplay().run(request, adapter_factory=factory)

    assert result.status is StrictFreshReplayStatus.STRICT_STOP_IMPLEMENTATION_FAILED
    assert result.committed_batch_count == 0
    assert result.logical_count == 10
    assert result.final_succeeded_terminal_count == 9
    assert result.reconciliation_dispatch_count == 0
    assert result.settled_actual_attempts == 10
    assert len(calls) == 10

    records = _jsonl(
        request.workspace / "original-settlements" / "durable_pair_settlement_v2.jsonl"
    )
    failure_records = [
        row
        for row in records
        if row["event_type"] == "pair_settled"
        and row["payload"]["outcome"]["kind"] == "implementation_failed"  # type: ignore[index]
    ]
    assert len(failure_records) == 1
    failure = failure_records[0]["payload"]["outcome"]  # type: ignore[index]
    assert set(failure) == {"kind", "error_category", "audit_sha256"}  # type: ignore[arg-type]
    assert failure["error_category"] == "value_error"  # type: ignore[index]
    assert len(failure["audit_sha256"]) == 64  # type: ignore[arg-type,index]
    assert "offline allowlisted implementation failure" not in json.dumps(
        records, ensure_ascii=False
    )
    assert not (request.workspace / "concurrent_runtime_batch_spool").exists()
    assert not (request.workspace / "source-v4").exists()


def test_original_wave_cap_insufficiency_stops_before_adapter_factory_or_invocation(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path, physical_cap=29)
    factory_calls: list[int] = []

    def factory(lane_id: int) -> _StrictAdapter:
        factory_calls.append(lane_id)
        return _StrictAdapter(lane_id, [])

    result = StrictFullPoolFormalReplay().run(request, adapter_factory=factory)

    assert result.status is StrictFreshReplayStatus.STRICT_STOP_CAP
    assert result.committed_batch_count == 0
    assert result.logical_count == 0
    assert result.reconciliation_dispatch_count == 0
    assert result.charged_physical_attempts == 0
    assert factory_calls == []
    assert not (
        request.workspace / "original-settlements" / "durable_pair_settlement_v2.jsonl"
    ).exists()


def test_reconciliation_cap_insufficiency_never_invokes_the_adapter_again(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path, physical_cap=30)
    calls: list[str] = []
    adapters: dict[int, _StrictAdapter] = {}

    def factory(lane_id: int) -> _StrictAdapter:
        adapter = _StrictAdapter(lane_id, calls, success_attempts=3)
        adapters[lane_id] = adapter
        return adapter

    result = StrictFullPoolFormalReplay().run(request, adapter_factory=factory)

    assert result.status is StrictFreshReplayStatus.STRICT_STOP_CAP
    assert result.committed_batch_count == 0
    assert result.logical_count == 10
    assert result.final_succeeded_terminal_count == 9
    assert result.reconciliation_dispatch_count == 0
    assert result.settled_actual_attempts == 30
    assert result.charged_physical_attempts == 30
    target_pair_id = adapters[4].failed_pair_id
    assert target_pair_id is not None
    assert calls.count(target_pair_id) == 1
    assert len(calls) == 10
    assert not any(pair_id.endswith(":1") for pair_id in calls)


@pytest.mark.parametrize("target_lane", [0, 4, 9])
def test_unknown_at_wave_head_middle_or_tail_drains_siblings_and_reconciles_only_that_pair(
    tmp_path: Path,
    target_lane: int,
) -> None:
    request = _request(tmp_path)
    calls: list[str] = []
    adapters: dict[int, _StrictAdapter] = {}

    def factory(lane_id: int) -> _StrictAdapter:
        adapter = _StrictAdapter(
            lane_id,
            calls,
            target_lane=target_lane,
            initial_outcome="provenance_unknown",
            reconciliation_action="ignore",
        )
        adapters[lane_id] = adapter
        return adapter

    result = StrictFullPoolFormalReplay().run(request, adapter_factory=factory)

    assert result.status is StrictFreshReplayStatus.COMPLETE
    assert result.logical_count == 24
    assert result.final_succeeded_terminal_count == 24
    assert result.reconciliation_dispatch_count == 1
    assert result.settled_actual_attempts == 25
    assert result.dispatched_without_settlement_uncertainty == 0
    target_pair_id = adapters[target_lane].failed_pair_id
    assert target_pair_id is not None
    assert calls.count(target_pair_id) == 2
    original_records = _jsonl(
        request.workspace / "original-settlements" / "durable_pair_settlement_v2.jsonl"
    )
    first_wave_settlements = [
        row for row in original_records if row["event_type"] == "pair_settled"
    ][:10]
    assert len(first_wave_settlements) == 10
    assert {row["payload"]["pair_id"] for row in first_wave_settlements} == set(  # type: ignore[index]
        calls[:10]
    )


def test_completion_order_does_not_change_outcomes_accounting_or_canonical_frontier(
    tmp_path: Path,
) -> None:
    runs: list[tuple[StrictFreshReplayResult, dict[str, object], list[dict[str, object]]]] = []
    for name, reverse in (("forward", False), ("reverse", True)):
        request = _request(tmp_path / name)
        result = StrictFullPoolFormalReplay().run(
            request,
            adapter_factory=lambda lane_id, reverse=reverse: _DelayedStrictAdapter(
                lane_id,
                [],
                reverse=reverse,
                initial_outcome="provenance_unknown",
                reconciliation_action="share",
            ),
        )
        first_chunk = json.loads(
            (
                request.workspace
                / "concurrent_runtime_batch_spool"
                / "batch-000000.json"
            ).read_text(encoding="utf-8")
        )
        original_records = _jsonl(
            request.workspace
            / "original-settlements"
            / "durable_pair_settlement_v2.jsonl"
        )
        runs.append((result, first_chunk, original_records))

    forward, reverse = runs
    assert forward[0].status is reverse[0].status is StrictFreshReplayStatus.COMPLETE
    assert (
        forward[0].settled_actual_attempts,
        forward[0].dispatched_without_settlement_uncertainty,
        forward[0].charged_physical_attempts,
        forward[0].committed_feedback_user_ids,
    ) == (
        reverse[0].settled_actual_attempts,
        reverse[0].dispatched_without_settlement_uncertainty,
        reverse[0].charged_physical_attempts,
        reverse[0].committed_feedback_user_ids,
    )
    assert forward[1]["rows"]["result_rows"] == reverse[1]["rows"]["result_rows"]  # type: ignore[index]
    assert forward[1]["rows"]["terminal_rows"] == reverse[1]["rows"]["terminal_rows"]  # type: ignore[index]

    forward_closure = next(
        row for row in forward[2] if row["event_type"] == "wave_closed"
    )
    reverse_closure = next(
        row for row in reverse[2] if row["event_type"] == "wave_closed"
    )
    assert forward_closure["payload"]["completion_order"] != reverse_closure["payload"][  # type: ignore[index]
        "completion_order"
    ]
    assert forward_closure["payload"]["canonical_terminal_frontier_pair_ids"] == (  # type: ignore[index]
        reverse_closure["payload"]["canonical_terminal_frontier_pair_ids"]  # type: ignore[index]
    )


@pytest.mark.parametrize(
    (
        "crash_event",
        "expected_first_calls",
        "expected_replay_calls",
        "expected_uncertainty",
        "expected_reconciliations",
    ),
    [
        ("wave_reserved", 0, 24, 0, 0),
        ("pair_dispatched", 0, 24, 3, 1),
        ("pair_settled", 10, 23, 27, 9),
        ("wave_closed", 10, 14, 0, 0),
    ],
)
def test_original_settlement_crash_points_replay_without_recalling_captured_pairs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    crash_event: str,
    expected_first_calls: int,
    expected_replay_calls: int,
    expected_uncertainty: int,
    expected_reconciliations: int,
) -> None:
    request = _request(tmp_path)
    first_calls: list[str] = []
    real_append = settlement_module._append_jsonl
    crashed = False

    def crash_after_event(path: Path, payload: Mapping[str, object]) -> None:
        nonlocal crashed
        real_append(path, payload)
        if (
            not crashed
            and path.parent.name == "original-settlements"
            and payload.get("event_type") == crash_event
        ):
            crashed = True
            raise RuntimeError(f"offline crash after {crash_event}")

    monkeypatch.setattr(settlement_module, "_append_jsonl", crash_after_event)
    with pytest.raises(RuntimeError, match=f"crash after {crash_event}"):
        StrictFullPoolFormalReplay().run(
            request,
            adapter_factory=lambda lane_id: _StrictAdapter(
                lane_id, first_calls, target_lane=99
            ),
        )
    assert len(first_calls) == expected_first_calls

    monkeypatch.setattr(settlement_module, "_append_jsonl", real_append)
    replay_calls: list[str] = []
    result = StrictFullPoolFormalReplay().run(
        request,
        adapter_factory=lambda lane_id: _StrictAdapter(
            lane_id, replay_calls, target_lane=99
        ),
    )

    assert result.status is StrictFreshReplayStatus.COMPLETE
    assert result.logical_count == 24
    assert result.final_succeeded_terminal_count == 24
    assert result.reconciliation_dispatch_count == expected_reconciliations
    assert result.dispatched_without_settlement_uncertainty == expected_uncertainty
    assert len(replay_calls) == expected_replay_calls
    captured_records = [
        row
        for row in _jsonl(
            request.workspace
            / "original-settlements"
            / "durable_pair_settlement_v2.jsonl"
        )
        if row["event_type"] == "pair_settled"
        and row["payload"]["outcome"]["kind"] == "terminal"  # type: ignore[index]
        and row["payload"]["accounting"]["recovered_without_settlement"] is False  # type: ignore[index]
    ]
    captured_before_crash = {
        row["payload"]["pair_id"]  # type: ignore[index]
        for row in captured_records[:1]
    } if crash_event == "pair_settled" else set(first_calls)
    if crash_event in {"pair_settled", "wave_closed"}:
        assert captured_before_crash.isdisjoint(replay_calls)


def test_atomic_reconciliation_dispatch_crash_has_no_slot_only_state_and_never_calls_again(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path)
    calls: list[str] = []
    real_append = strict_module._append_policy_event
    crashed = False

    def crash_after_atomic_dispatch(
        path: Path,
        *,
        identity_hash: str,
        sequence: int,
        previous_checksum: str | None,
        event_type: str,
        payload: Mapping[str, object],
    ) -> None:
        nonlocal crashed
        real_append(
            path,
            identity_hash=identity_hash,
            sequence=sequence,
            previous_checksum=previous_checksum,
            event_type=event_type,
            payload=payload,
        )
        if not crashed and event_type == "reconciliation_dispatched":
            crashed = True
            raise RuntimeError("offline crash after atomic reconciliation dispatch")

    monkeypatch.setattr(strict_module, "_append_policy_event", crash_after_atomic_dispatch)
    with pytest.raises(RuntimeError, match="atomic reconciliation dispatch"):
        StrictFullPoolFormalReplay().run(
            request,
            adapter_factory=lambda lane_id: _StrictAdapter(lane_id, calls),
        )
    assert len(calls) == 10

    monkeypatch.setattr(strict_module, "_append_policy_event", real_append)
    replay_factory_calls: list[int] = []

    def tripwire(lane_id: int) -> LLMDecisionAdapter:
        replay_factory_calls.append(lane_id)
        raise AssertionError("reconciliation dispatch evidence must forbid a replayed call")

    result = StrictFullPoolFormalReplay().run(request, adapter_factory=tripwire)

    assert result.status is StrictFreshReplayStatus.STRICT_STOP_PROVENANCE_UNKNOWN
    assert result.committed_batch_count == 0
    assert result.logical_count == 10
    assert result.final_succeeded_terminal_count == 9
    assert result.reconciliation_dispatch_count == 1
    assert result.settled_actual_attempts == 12
    assert result.dispatched_without_settlement_uncertainty == 3
    assert result.charged_physical_attempts == 15
    assert replay_factory_calls == []
    policy_records = _jsonl(request.workspace / STRICT_PAIR_POLICY_LEDGER_FILE)
    assert [row["event_type"] for row in policy_records] == [
        "policy_created",
        "reconciliation_dispatched",
        "strict_stopped",
    ]
    dispatch_payload = policy_records[1]["payload"]
    assert set(dispatch_payload) == {  # type: ignore[arg-type]
        "pair_id",
        "source_kind",
        "source_wave_index",
        "source_evidence_sha256",
        "plan_identity_sha256",
        "reconciliation_identity_hash",
        "journal_relative_path",
        "physical_reservation",
        "charged_before_dispatch",
    }
    assert not any("slot" in key for key in dispatch_payload)  # type: ignore[union-attr]


@pytest.mark.parametrize("crash_event", ["pair_settled", "wave_closed"])
def test_captured_reconciliation_crash_replays_terminal_without_a_second_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    crash_event: str,
) -> None:
    request = _request(tmp_path)
    first_calls: list[str] = []
    first_adapters: dict[int, _StrictAdapter] = {}
    real_append = settlement_module._append_jsonl
    crashed = False

    def crash_after_reconciliation_capture(
        path: Path, payload: Mapping[str, object]
    ) -> None:
        nonlocal crashed
        real_append(path, payload)
        if (
            not crashed
            and path.parent.parent.name == "reconciliation-settlements"
            and payload.get("event_type") == crash_event
        ):
            crashed = True
            raise RuntimeError(f"offline reconciliation crash after {crash_event}")

    def first_factory(lane_id: int) -> _StrictAdapter:
        adapter = _StrictAdapter(lane_id, first_calls)
        first_adapters[lane_id] = adapter
        return adapter

    monkeypatch.setattr(
        settlement_module, "_append_jsonl", crash_after_reconciliation_capture
    )
    with pytest.raises(RuntimeError, match="reconciliation crash"):
        StrictFullPoolFormalReplay().run(request, adapter_factory=first_factory)
    target_pair_id = first_adapters[4].failed_pair_id
    assert target_pair_id is not None
    assert first_calls.count(target_pair_id) == 2
    assert len(first_calls) == 11

    monkeypatch.setattr(settlement_module, "_append_jsonl", real_append)
    replay_calls: list[str] = []
    result = StrictFullPoolFormalReplay().run(
        request,
        adapter_factory=lambda lane_id: _StrictAdapter(
            lane_id, replay_calls, target_lane=99
        ),
    )

    assert result.status is StrictFreshReplayStatus.COMPLETE
    assert result.reconciliation_dispatch_count == 1
    assert result.settled_actual_attempts == 27
    assert result.dispatched_without_settlement_uncertainty == 0
    assert target_pair_id not in replay_calls
    assert len(replay_calls) == 14
    policy_events = [
        row["event_type"]
        for row in _jsonl(request.workspace / STRICT_PAIR_POLICY_LEDGER_FILE)
    ]
    assert policy_events.count("reconciliation_dispatched") == 1
    assert policy_events.count("reconciliation_resolved") == 1


@pytest.mark.parametrize(
    "drift",
    ["max_retries", "fresh_no_cache", "request_contract", "prior_counter", "cache"],
)
def test_production_shaped_adapter_contract_drift_fails_before_first_decision(
    tmp_path: Path,
    drift: str,
) -> None:
    request = _request(tmp_path)
    decision_calls: list[str] = []

    def factory(lane_id: int) -> _StrictAdapter:
        adapter = _StrictAdapter(lane_id, decision_calls, target_lane=99)
        metadata = deepcopy(adapter.safe_metadata)
        if drift == "max_retries":
            metadata["max_retries"] = 1
        elif drift == "fresh_no_cache":
            metadata["fresh_no_cache"] = False
        elif drift == "request_contract":
            cast(dict[str, object], metadata["request_contract"])["max_retries"] = 1
        elif drift == "prior_counter":
            adapter.request_invocations = 1
        elif drift == "cache":
            adapter.cache = object()  # type: ignore[attr-defined]
        adapter.safe_metadata = metadata
        return adapter

    with pytest.raises(ValueError, match="strict replay"):
        StrictFullPoolFormalReplay().run(request, adapter_factory=factory)

    assert decision_calls == []
    assert not (
        request.workspace / "original-settlements" / "durable_pair_settlement_v2.jsonl"
    ).exists()


def test_complete_same_identity_replay_returns_without_adapter_factory(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    first = StrictFullPoolFormalReplay().run(
        request,
        adapter_factory=lambda lane_id: _StrictAdapter(lane_id, [], target_lane=99),
    )
    factory_calls: list[int] = []

    def tripwire(lane_id: int) -> LLMDecisionAdapter:
        factory_calls.append(lane_id)
        raise AssertionError("complete strict replay must not create an Adapter")

    replay = StrictFullPoolFormalReplay().run(request, adapter_factory=tripwire)

    assert replay == first
    assert factory_calls == []


def test_batch_commit_crash_replays_canonical_spool_without_recalling_committed_pairs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path)
    first_calls: list[str] = []
    real_finish = strict_module._ConcurrentRuntimeKernel._finish_commit
    crashed = False

    def crash_after_durable_commit(self: object, commit: object) -> None:
        nonlocal crashed
        if not crashed:
            crashed = True
            raise RuntimeError("offline crash after durable batch commit")
        real_finish(self, commit)  # type: ignore[arg-type]

    monkeypatch.setattr(
        strict_module._ConcurrentRuntimeKernel, "_finish_commit", crash_after_durable_commit
    )
    with pytest.raises(RuntimeError, match="durable batch commit"):
        StrictFullPoolFormalReplay().run(
            request,
            adapter_factory=lambda lane_id: _StrictAdapter(
                lane_id, first_calls, target_lane=99
            ),
        )
    assert len(first_calls) == 12
    assert all(pair_id.endswith(":0") for pair_id in first_calls)

    monkeypatch.setattr(strict_module._ConcurrentRuntimeKernel, "_finish_commit", real_finish)
    replay_calls: list[str] = []
    result = StrictFullPoolFormalReplay().run(
        request,
        adapter_factory=lambda lane_id: _StrictAdapter(
            lane_id, replay_calls, target_lane=99
        ),
    )

    assert result.status is StrictFreshReplayStatus.COMPLETE
    assert result.committed_batch_count == 2
    assert len(replay_calls) == 12
    assert all(pair_id.endswith(":1") for pair_id in replay_calls)
    assert set(first_calls).isdisjoint(replay_calls)
    assert result.logical_count == 24
    assert result.settled_actual_attempts == 24


def test_reconciliation_parent_symlink_fails_closed_without_writing_outside_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path)
    real_append = settlement_module._append_jsonl
    crashed = False

    def crash_after_original_wave(
        path: Path, payload: Mapping[str, object]
    ) -> None:
        nonlocal crashed
        real_append(path, payload)
        if (
            not crashed
            and path.parent.name == "original-settlements"
            and payload.get("event_type") == "wave_closed"
        ):
            crashed = True
            raise RuntimeError("offline stop before reconciliation")

    monkeypatch.setattr(settlement_module, "_append_jsonl", crash_after_original_wave)
    with pytest.raises(RuntimeError, match="before reconciliation"):
        StrictFullPoolFormalReplay().run(
            request,
            adapter_factory=lambda lane_id: _StrictAdapter(lane_id, []),
        )
    monkeypatch.setattr(settlement_module, "_append_jsonl", real_append)

    outside = tmp_path / "outside-reconciliation"
    outside.mkdir()
    (request.workspace / "reconciliation-settlements").symlink_to(
        outside, target_is_directory=True
    )
    factory_calls: list[int] = []

    with pytest.raises(ValueError, match="reconciliation settlement directory is unsafe"):
        StrictFullPoolFormalReplay().run(
            request,
            adapter_factory=lambda lane_id: factory_calls.append(lane_id),  # type: ignore[arg-type,return-value]
        )

    assert factory_calls == []
    assert list(outside.iterdir()) == []


class _CompleteEvidenceStrictAdapter(LLMDecisionAdapter):
    def __init__(self, lane_id: int, *, observed_model: str = "gpt-5.6-sol") -> None:
        self.lane_id = lane_id
        self.observed_model = observed_model
        self.request_invocations = 0
        self.external_request_invocations = 0
        self.prompt_version = str(strict_formal_provider_contract()["prompt_version"])
        self.safe_metadata = strict_formal_provider_contract()
        self._accounting = ProviderAccountingTracker()

    @property
    def provider_accounting(self) -> ProviderAccounting:
        return self._accounting.snapshot(external_request_invocations=0)

    def decide(
        self,
        post: PostContent,
        profile: UserProfile,
        peer_context: PeerContext,
        platform_context: PlatformContext | None = None,
        time_step: int = 0,
    ) -> EngageDecision:
        del peer_context, platform_context, time_step
        self.request_invocations += 1
        self._accounting.record_response(
            ProviderResponseEnvelope(
                decision_text='{"engage":false,"action":"ignore"}',
                observed_model=self.observed_model,
                observed_model_status="reported",
                usage_status="complete",
                input_tokens=10,
                output_tokens=2,
                total_tokens=12,
                cached_input_tokens=0,
            )
        )
        self._accounting.record_successful_decision()
        return EngageDecision(
            engage=False,
            probability=0.1,
            confidence=0.9,
            action="ignore",
            reason=f"offline complete evidence for {profile.user_id}:{post.post_id}",
            decision_source="offline_strict_rehearsal",
            provider_metadata={"model": "gpt-5.6-sol"},
        )


class _CompleteEvidenceReconciliationAdapter(_CompleteEvidenceStrictAdapter):
    def __init__(self, lane_id: int) -> None:
        super().__init__(lane_id)
        self.failed_pair_id: str | None = None

    def decide(
        self,
        post: PostContent,
        profile: UserProfile,
        peer_context: PeerContext,
        platform_context: PlatformContext | None = None,
        time_step: int = 0,
    ) -> EngageDecision:
        pair_id = f"{profile.user_id}:{post.post_id}:{time_step}"
        if self.lane_id == 4 and time_step == 0 and self.failed_pair_id is None:
            self.failed_pair_id = pair_id
            self.request_invocations += 3
            raise ProviderDecisionError(TimeoutError("offline provisional failure"))
        return super().decide(post, profile, peer_context, platform_context, time_step)


def test_complete_persisted_evidence_atomically_closes_additive_source_v4(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    rejected_before = {
        path.relative_to(request.rejected_history.source_root).as_posix(): (
            hashlib.sha256(path.read_bytes()).hexdigest(),
            path.stat().st_size,
        )
        for path in request.rejected_history.source_root.rglob("*")
        if path.is_file()
    }

    result = StrictFullPoolFormalReplay().run(
        request,
        adapter_factory=_CompleteEvidenceStrictAdapter,
    )

    assert result.status is StrictFreshReplayStatus.COMPLETE
    assert result.source_root == request.workspace / "source-v4"
    source_root = result.source_root
    assert source_root is not None
    assert result.source_manifest_sha256 is not None
    assert source_root.is_dir()
    manifest_path = source_root / "manifest.json"
    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == result.source_manifest_sha256
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == FULL_POOL_SOURCE_V4_SCHEMA
    assert manifest["counts"] == {
        "candidate_rows": 36,
        "committed_batches": 2,
        "distinct_users": 8,
        "pair_rows": 24,
        "terminal_rows": 24,
        "variant_evidence_rows": 24,
    }
    assert manifest["provider_accounting"]["provider_response_count"] == 24
    assert manifest["provider_accounting"]["successful_decision_count"] == 24
    assert manifest["provider_accounting"]["observed_model_counts"] == {
        "gpt-5.6-sol": 24
    }
    assert manifest["provider_accounting"]["usage_complete_response_count"] == 24
    assert manifest["provider_accounting"]["usage_missing_response_count"] == 0
    assert manifest["provider_accounting"]["usage_malformed_response_count"] == 0
    assert manifest["physical_accounting"] == {
        "active_reservations": 0,
        "charged_physical_attempts": 24,
        "dispatched_without_settlement_uncertainty": 0,
        "physical_cap": 120_120,
        "settled_actual_attempts": 24,
    }
    assert manifest["fresh_lineage"]["imported_batch_count"] == 0
    assert manifest["fresh_lineage"]["imported_terminal_count"] == 0
    assert manifest["fresh_lineage"]["rejected_history"] == {
        "manifest_sha256": request.rejected_history.manifest_sha256,
        "rejection_reason": "validation_mixed_provider_evidence",
        "source_root": str(request.rejected_history.source_root),
    }
    assert manifest["production_deploy_eligible"] is False
    assert not (request.workspace / ".source-v4.staging").exists()

    rejected_after = {
        path.relative_to(request.rejected_history.source_root).as_posix(): (
            hashlib.sha256(path.read_bytes()).hexdigest(),
            path.stat().st_size,
        )
        for path in request.rejected_history.source_root.rglob("*")
        if path.is_file()
    }
    assert rejected_after == rejected_before

    def tripwire(_: int) -> LLMDecisionAdapter:
        raise AssertionError("closed source-v4 replay must not create an Adapter")

    replay = StrictFullPoolFormalReplay().run(request, adapter_factory=tripwire)
    assert replay == result
    status = json.loads(
        (request.workspace / "strict_fresh_replay_status.json").read_text(encoding="utf-8")
    )
    assert status["source_root"] == str(result.source_root)
    assert status["source_manifest_sha256"] == result.source_manifest_sha256


def test_complete_runtime_with_wrong_observed_model_cannot_create_source_v4(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)

    result = StrictFullPoolFormalReplay().run(
        request,
        adapter_factory=lambda lane_id: _CompleteEvidenceStrictAdapter(
            lane_id,
            observed_model="crossed-model",
        ),
    )

    assert result.status is StrictFreshReplayStatus.COMPLETE
    assert result.source_root is None
    assert result.source_manifest_sha256 is None
    assert not (request.workspace / "source-v4").exists()


def test_source_v4_tamper_fails_closed_before_adapter_creation(tmp_path: Path) -> None:
    request = _request(tmp_path)
    result = StrictFullPoolFormalReplay().run(
        request,
        adapter_factory=_CompleteEvidenceStrictAdapter,
    )
    assert result.source_root is not None
    terminal_path = result.source_root / "terminal_rows.jsonl"
    terminal_path.write_bytes(terminal_path.read_bytes() + b"{}\n")
    factory_calls: list[int] = []

    with pytest.raises(ValueError, match="artifact inventory is unsafe or crossed"):
        StrictFullPoolFormalReplay().run(
            request,
            adapter_factory=lambda lane_id: factory_calls.append(lane_id),  # type: ignore[arg-type,return-value]
        )

    assert factory_calls == []


def test_source_v4_closure_rebuilds_after_crash_before_atomic_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path)
    real_write = strict_module._write_source_v4_rows

    def crash_after_rows(
        source: Path,
        journal: ConcurrentExecutionJournal,
        *,
        runtime_replay: Mapping[str, object],
    ) -> None:
        real_write(source, journal, runtime_replay=runtime_replay)
        raise RuntimeError("offline source-v4 staging crash")

    monkeypatch.setattr(strict_module, "_write_source_v4_rows", crash_after_rows)
    with pytest.raises(RuntimeError, match="staging crash"):
        StrictFullPoolFormalReplay().run(
            request,
            adapter_factory=_CompleteEvidenceStrictAdapter,
        )
    assert not (request.workspace / "source-v4").exists()
    assert not (request.workspace / ".source-v4.staging").exists()

    monkeypatch.setattr(strict_module, "_write_source_v4_rows", real_write)

    def tripwire(_: int) -> LLMDecisionAdapter:
        raise AssertionError("source-v4 closure replay must not create an Adapter")

    result = StrictFullPoolFormalReplay().run(request, adapter_factory=tripwire)
    assert result.status is StrictFreshReplayStatus.COMPLETE
    assert result.source_root == request.workspace / "source-v4"


def test_source_v4_replay_recovers_crash_after_atomic_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path)
    real_replace = strict_module.os.replace
    crashed = False

    def crash_after_source_rename(source: Path, target: Path) -> None:
        nonlocal crashed
        real_replace(source, target)
        if not crashed and source.name == ".source-v4.staging" and target.name == "source-v4":
            crashed = True
            raise RuntimeError("offline crash after source-v4 rename")

    monkeypatch.setattr(strict_module.os, "replace", crash_after_source_rename)
    with pytest.raises(RuntimeError, match="after source-v4 rename"):
        StrictFullPoolFormalReplay().run(
            request,
            adapter_factory=_CompleteEvidenceStrictAdapter,
        )
    assert (request.workspace / "source-v4").is_dir()
    assert not (request.workspace / ".source-v4.staging").exists()

    monkeypatch.setattr(strict_module.os, "replace", real_replace)

    def tripwire(_: int) -> LLMDecisionAdapter:
        raise AssertionError("renamed source-v4 replay must not create an Adapter")

    result = StrictFullPoolFormalReplay().run(request, adapter_factory=tripwire)
    assert result.status is StrictFreshReplayStatus.COMPLETE
    assert result.source_manifest_sha256 is not None


def test_source_v4_keeps_provisional_failure_only_in_attempt_accounting(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    adapters: dict[int, _CompleteEvidenceReconciliationAdapter] = {}

    def factory(lane_id: int) -> _CompleteEvidenceReconciliationAdapter:
        adapter = _CompleteEvidenceReconciliationAdapter(lane_id)
        adapters[lane_id] = adapter
        return adapter

    result = StrictFullPoolFormalReplay().run(request, adapter_factory=factory)

    assert result.status is StrictFreshReplayStatus.COMPLETE
    assert result.source_root is not None
    assert result.reconciliation_dispatch_count == 1
    assert result.settled_actual_attempts == 27
    failed_pair_id = adapters[4].failed_pair_id
    assert failed_pair_id is not None
    manifest = json.loads((result.source_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["settlement_v2"]["provisional_provider_failed_count"] == 1
    assert len(manifest["settlement_v2"]["reconciliation_journals"]) == 1
    assert manifest["physical_accounting"]["settled_actual_attempts"] == 27
    assert manifest["provider_accounting"]["provider_response_count"] == 24
    terminals = _jsonl(result.source_root / "terminal_rows.jsonl")
    assert len(terminals) == 24
    assert {row["terminal_status"] for row in terminals} == {"succeeded"}
    assert {row["provider_status"] for row in terminals} == {"succeeded"}
    assert sum(cast(int, row["provider_response_count"]) for row in terminals) == 24
    original_attempts = _jsonl(
        result.source_root
        / "settlement/original/durable-pair-settlement-v2.jsonl"
    )
    assert any(
        row["event_type"] == "pair_settled"
        and row["payload"]["pair_id"] == failed_pair_id  # type: ignore[index]
        and row["payload"]["outcome"]["terminal_row"]["terminal_status"]  # type: ignore[index]
        == "provider_failed"
        for row in original_attempts
    )


def test_deterministic_thirty_batch_smoke_closes_every_fresh_pair_without_provider_calls(
    tmp_path: Path,
) -> None:
    dataset = _dataset(tmp_path, user_count=30)
    request = StrictFreshReplayRequest(
        config=ConcurrentMessageExperimentConfig(
            dataset_dir=dataset,
            sample_size=30,
            horizon=30,
            delivery_capacity=1,
            configuration_profile="validation",
        ),
        workspace=tmp_path / "strict-thirty-batch-replay",
        replay_id="offline-strict-thirty-batch-v1",
        provider_contract=strict_formal_provider_contract(),
        rejected_history=_rejected_history(tmp_path),
        seed_top_k_per_proxy=1,
        logical_cap=90,
    )
    adapters: dict[int, _CompleteEvidenceStrictAdapter] = {}

    def factory(lane_id: int) -> _CompleteEvidenceStrictAdapter:
        adapter = _CompleteEvidenceStrictAdapter(lane_id)
        adapters[lane_id] = adapter
        return adapter

    result = StrictFullPoolFormalReplay().run(request, adapter_factory=factory)

    assert result.status is StrictFreshReplayStatus.COMPLETE
    assert result.committed_batch_count == 30
    assert result.logical_count == 90
    assert result.final_succeeded_terminal_count == 90
    assert result.reconciliation_dispatch_count == 0
    assert result.settled_actual_attempts == 90
    assert result.dispatched_without_settlement_uncertainty == 0
    assert result.charged_physical_attempts == 90
    assert sum(adapter.request_invocations for adapter in adapters.values()) == 90
    assert sum(adapter.external_request_invocations for adapter in adapters.values()) == 0
    assert result.source_root is not None
    manifest = json.loads((result.source_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"] == {
        "candidate_rows": 1_395,
        "committed_batches": 30,
        "distinct_users": 30,
        "pair_rows": 90,
        "terminal_rows": 90,
        "variant_evidence_rows": 90,
    }
    assert manifest["settlement_v2"]["provisional_provider_failed_count"] == 0
    assert manifest["settlement_v2"]["provisional_unknown_pair_count"] == 0
    assert manifest["settlement_v2"]["implementation_failed_pair_count"] == 0
    assert manifest["production_topology"] is False


@pytest.mark.full_scale_rehearsal
def test_full_scale_zero_provider_rehearsal_closes_production_topology(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import llm_abm_sim._concurrent_runtime_spool as spool_module
    import llm_abm_sim.concurrent_execution_journal as journal_module
    import llm_abm_sim.concurrent_message_experiment as experiment_module

    root = tmp_path / "full-scale-zero-provider"
    root.mkdir()
    try:
        monkeypatch.setattr(strict_module.os, "fsync", lambda _descriptor: None)
        for module in (
            settlement_module,
            spool_module,
            journal_module,
            experiment_module,
            strict_module,
        ):
            monkeypatch.setattr(module, "safe_data", lambda value: value)

        dataset = _dataset(root, user_count=36_400)
        request = StrictFreshReplayRequest(
            config=ConcurrentMessageExperimentConfig(
                dataset_dir=dataset,
                sample_size=36_400,
                horizon=30,
                delivery_capacity=1_214,
                configuration_profile="validation",
            ),
            workspace=root / "strict-full-scale-replay",
            replay_id="offline-strict-full-scale-v1",
            provider_contract=strict_formal_provider_contract(),
            rejected_history=_rejected_history(root),
            seed_top_k_per_proxy=10,
            logical_cap=109_200,
            physical_cap=120_120,
            max_concurrency=10,
        )
        adapters: dict[int, _CompleteEvidenceStrictAdapter] = {}

        def factory(lane_id: int) -> _CompleteEvidenceStrictAdapter:
            adapter = _CompleteEvidenceStrictAdapter(lane_id)
            adapters[lane_id] = adapter
            return adapter

        result = StrictFullPoolFormalReplay().run(request, adapter_factory=factory)

        assert result.status is StrictFreshReplayStatus.COMPLETE
        assert result.committed_batch_count == 30
        assert result.logical_count == 109_200
        assert result.final_succeeded_terminal_count == 109_200
        assert result.reconciliation_dispatch_count == 0
        assert result.settled_actual_attempts == 109_200
        assert result.dispatched_without_settlement_uncertainty == 0
        assert result.charged_physical_attempts == 109_200
        assert result.charged_physical_attempts <= 120_120
        assert set(adapters) == set(range(10))
        assert sum(adapter.request_invocations for adapter in adapters.values()) == 109_200
        assert sum(adapter.external_request_invocations for adapter in adapters.values()) == 0
        assert result.source_root is not None
        manifest = json.loads(
            (result.source_root / "manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["production_topology"] is True
        assert manifest["counts"] == {
            "candidate_rows": 1_691_730,
            "committed_batches": 30,
            "distinct_users": 36_400,
            "pair_rows": 109_200,
            "terminal_rows": 109_200,
            "variant_evidence_rows": 109_200,
        }
        assert manifest["provider_accounting"]["external_request_invocations"] == 0
        assert manifest["provider_accounting"]["provider_response_count"] == 109_200
        assert manifest["provider_accounting"]["successful_decision_count"] == 109_200
        assert manifest["provider_accounting"]["observed_model_counts"] == {
            "gpt-5.6-sol": 109_200
        }
        assert manifest["provider_accounting"]["usage_complete_response_count"] == 109_200
        assert manifest["settlement_v2"]["provisional_provider_failed_count"] == 0
        assert manifest["settlement_v2"]["provisional_unknown_pair_count"] == 0
        assert manifest["settlement_v2"]["implementation_failed_pair_count"] == 0
        assert manifest["production_deploy_eligible"] is False
    finally:
        shutil.rmtree(root, ignore_errors=True)
