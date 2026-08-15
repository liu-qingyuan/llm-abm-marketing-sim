from __future__ import annotations

import hashlib
import json
import shutil
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from llm_abm_sim.decision import (
    DecisionInput,
    EngageDecision,
    LLMDecisionAdapter,
    ProviderResponseProvenanceUnknown,
)
from llm_abm_sim.full_pool_segmented_continuation import (
    FULL_POOL_SEGMENTED_LOGICAL_CAP,
    FULL_POOL_SEGMENTED_MAX_CONCURRENCY,
    FullPoolReconciliationAuthorization,
    FullPoolSegmentedContinuation,
    SegmentedContinuationStatus,
    _reserve_total_caps,
    _validate_unique_terminal_rows,
)
from llm_abm_sim.schemas import PeerContext, PlatformContext, PostContent, UserProfile

FIXTURES = Path(__file__).parents[1] / "fixtures"
PREFIX = FIXTURES / "full_pool_segmented_v1_prefix"
UNKNOWN_PREFIX = FIXTURES / "full_pool_segmented_v1_prefix_unknown"
PROMPT_VERSION = "concurrent-primary-observed-v2"
MODEL = "offline-segmented-fixture-v1"


def test_segmented_cap_reservation_includes_prefix_unknown_and_suffix_retry_windows() -> None:
    reservation = _reserve_total_caps(
        prefix_logical=109_190,
        prefix_physical=120_080,
        unknown_logical_charge=1,
        unknown_physical_charge=1,
        pending_pair_count=10,
        authorized_unknown_retry_count=1,
        maximum_attempts_per_dispatch=3,
    )

    assert reservation.logical_total == FULL_POOL_SEGMENTED_LOGICAL_CAP
    assert reservation.physical_total == 120_111
    assert reservation.suffix_logical_reservation == 9
    assert reservation.suffix_physical_reservation == 30

    with pytest.raises(ValueError, match="logical cap"):
        _reserve_total_caps(
            prefix_logical=109_191,
            prefix_physical=120_080,
            unknown_logical_charge=1,
            unknown_physical_charge=1,
            pending_pair_count=10,
            authorized_unknown_retry_count=1,
            maximum_attempts_per_dispatch=3,
        )

    with pytest.raises(ValueError, match="physical cap"):
        _reserve_total_caps(
            prefix_logical=109_190,
            prefix_physical=120_090,
            unknown_logical_charge=1,
            unknown_physical_charge=1,
            pending_pair_count=10,
            authorized_unknown_retry_count=1,
            maximum_attempts_per_dispatch=3,
        )


class _LaneState:
    def __init__(self, *, crash_pair_id: str | None = None) -> None:
        self.lock = threading.Lock()
        self.calls: list[tuple[int, str]] = []
        self.completion_order: list[str] = []
        self.lane_ids: list[int] = []
        self.active = 0
        self.max_active = 0
        self.crash_pair_id = crash_pair_id


class _OfflineLaneAdapter(LLMDecisionAdapter):
    prompt_version = PROMPT_VERSION
    external_request_invocations = 0
    safe_metadata = {
        "adapter": "offline_segmented_fixture",
        "provider": "deterministic",
        "model": MODEL,
        "prompt_version": PROMPT_VERSION,
        "timeout_seconds": 30.0,
        "max_retries": 2,
    }

    def __init__(self, lane_id: int, state: _LaneState) -> None:
        self.lane_id = lane_id
        self.state = state
        self.request_invocations = 0
        state.lane_ids.append(lane_id)

    def decide(
        self,
        post: PostContent,
        profile: UserProfile,
        peer_context: PeerContext,
        platform_context: PlatformContext | None = None,
        time_step: int = 0,
    ) -> EngageDecision:
        del post, peer_context, platform_context, time_step
        pair_id = f"{profile.user_id}:message_1:1"
        with self.state.lock:
            self.request_invocations += 1
            self.state.calls.append((self.lane_id, pair_id))
            self.state.active += 1
            self.state.max_active = max(self.state.max_active, self.state.active)
        try:
            number = int(profile.user_id.removeprefix("u"))
            time.sleep((12 - number) * 0.002)
            if pair_id == self.state.crash_pair_id:
                raise ProviderResponseProvenanceUnknown("offline injected unknown provenance")
            positive = number in {4, 6, 8}
            with self.state.lock:
                self.state.completion_order.append(pair_id)
            return EngageDecision(
                engage=positive,
                probability=0.8 if positive else 0.1,
                reason="offline segmented lane",
                confidence=0.9,
                action="share" if positive else "ignore",
                decision_source="offline_segmented_fixture",
                provider_metadata={"model": MODEL},
            )
        finally:
            with self.state.lock:
                self.state.active -= 1


def _inputs(*, first_user: int = 3) -> dict[str, DecisionInput]:
    return {
        f"u{number}:message_1:1": DecisionInput(
            post=PostContent(post_id="message_1", text="unchanged prompt semantics"),
            profile=UserProfile(user_id=f"u{number}"),
            peer_context=PeerContext(),
            platform_context=PlatformContext(),
            time_step=1,
            prompt_version=PROMPT_VERSION,
        )
        for number in range(first_user, 13)
    }


def _factory(state: _LaneState) -> Any:
    return lambda lane_id: _OfflineLaneAdapter(lane_id, state)


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _unknown_prefix_with_pending_attempts(tmp_path: Path, count: int) -> Path:
    prefix = tmp_path / "unknown-prefix-with-pending-attempts"
    shutil.copytree(UNKNOWN_PREFIX, prefix)
    ledger_path = prefix / "full_pool_attempt_ledger.jsonl"
    records = _jsonl(ledger_path)
    previous = records[-1]["checksum"]
    for attempt_index in range(1, count + 1):
        body = {
            "schema_version": "full-pool-formal-attempt-ledger-v1",
            "sequence": len(records) + 1,
            "previous_checksum": previous,
            "execution_contract_sha256": "a" * 64,
            "event_type": "physical_attempt_accounted",
            "payload": {
                "pair_id": "u3:message_1:1",
                "attempt_index": attempt_index,
                "attempt_outcome": "started_without_terminal",
            },
        }
        checksum = hashlib.sha256(
            json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        records.append({**body, "checksum": checksum})
        previous = checksum
    ledger_path.write_text(
        "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            for record in records
        ),
        encoding="utf-8",
    )
    return prefix


def test_segmented_continuation_freezes_committed_and_active_prefix_then_drains_ten_lanes_canonically(
    tmp_path: Path,
) -> None:
    prefix_before = _tree_bytes(PREFIX)
    state = _LaneState()
    workspace = tmp_path / "segmented-continuation"

    result = FullPoolSegmentedContinuation().run(
        PREFIX,
        workspace,
        continuation_id="offline-segmented-success-v1",
        _fixture_decision_inputs=_inputs(),
        adapter_factory=_factory(state),
    )

    assert result.status is SegmentedContinuationStatus.COMPLETE
    assert result.durable_prefix_terminal_count == 3
    assert result.concurrent_suffix_terminal_count == 10
    assert result.logical_count == 13
    assert result.physical_attempt_count == 13
    assert result.committed_feedback_user_ids == ("u2", "u4", "u6", "u8")
    assert result.unknown_pair_ids == ()
    assert _tree_bytes(PREFIX) == prefix_before
    assert state.lane_ids == list(range(FULL_POOL_SEGMENTED_MAX_CONCURRENCY))
    assert len({lane_id for lane_id, _ in state.calls}) == 10
    assert state.max_active == 10
    assert state.completion_order != [f"u{number}:message_1:1" for number in range(3, 13)]
    assert {pair_id for _, pair_id in state.calls}.isdisjoint(
        {"u0:message_1:0", "u1:message_1:1", "u2:message_1:1"}
    )

    rows = _jsonl(result.terminal_rows_path or Path("missing"))
    assert [row["pair_schedule_position"] for row in rows] == list(range(13))
    assert [row["execution_segment"] for row in rows[:3]] == ["serial_prefix"] * 3
    assert [row["execution_segment"] for row in rows[3:]] == ["concurrent_suffix"] * 10
    ledger = _jsonl(workspace / "segmented_continuation_ledger.jsonl")
    terminal_pair_ids = [
        row["payload"]["pair_id"] for row in ledger if row["event_type"] == "pair_terminal"
    ]
    assert terminal_pair_ids == [f"u{number}:message_1:1" for number in range(3, 13)]
    assert ledger[-1]["event_type"] == "batch_committed"
    assert sum(row["event_type"] == "pair_terminal" for row in ledger[:-1]) == 10

    envelope = json.loads((workspace / "cutoff_manifest.json").read_text(encoding="utf-8"))
    assert set(envelope) == {"schema_version", "manifest", "manifest_sha256"}
    manifest = envelope["manifest"]
    assert set(manifest) == {
        "schema_version",
        "continuation_id",
        "v1_contract_identity",
        "v1_run_identity",
        "accepted_journal_prefix",
        "accepted_attempt_ledger_prefix",
        "accepted_artifacts",
        "committed_batches",
        "active_batch",
        "ordered_pair_ids",
        "ordered_terminal_ids",
        "durable_terminal_pair_ids",
        "committed_feedback_user_ids",
        "active_frozen_feedback_user_ids",
        "prefix_accounting",
        "unknown_count",
        "unknown_pair_ids",
        "reconciliation_authorization",
        "reconciliation_authorization_sha256",
        "suffix",
        "caps",
        "production_deploy_eligible",
    }
    assert manifest["committed_batches"][0]["ordered_pair_ids"] == ["u0:message_1:0"]
    assert manifest["active_batch"]["ordered_pair_ids"] == [
        f"u{number}:message_1:1" for number in range(1, 13)
    ]
    assert manifest["ordered_terminal_ids"] == [
        "u0:message_1:0:primary",
        "u1:message_1:1:primary",
        "u2:message_1:1:primary",
    ]
    assert manifest["active_frozen_feedback_user_ids"] == ["u0"]
    assert manifest["suffix"]["max_concurrency"] == 10
    expected_hash = hashlib.sha256(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert envelope["manifest_sha256"] == expected_hash == result.manifest_sha256


def test_segmented_cutoff_rejects_snapshot_tamper_before_adapter_factory(tmp_path: Path) -> None:
    prefix = tmp_path / "tampered-prefix"
    shutil.copytree(PREFIX, prefix)
    snapshot = next((prefix / "concurrent_message_execution_snapshots").glob("*.json"))
    snapshot.write_bytes(snapshot.read_bytes() + b" ")
    factory_called = False

    def tripwire(_lane_id: int) -> LLMDecisionAdapter:
        nonlocal factory_called
        factory_called = True
        raise AssertionError("tampered cutoff must fail before Adapter creation")

    with pytest.raises(ValueError, match="snapshot hash mismatch"):
        FullPoolSegmentedContinuation().run(
            prefix,
            tmp_path / "continuation",
            continuation_id="tampered-prefix-v1",
            _fixture_decision_inputs=_inputs(),
            adapter_factory=tripwire,
        )

    assert factory_called is False


def test_segmented_cutoff_manifest_hash_rejects_post_freeze_tamper(tmp_path: Path) -> None:
    state = _LaneState()
    workspace = tmp_path / "manifest-tamper"
    FullPoolSegmentedContinuation().run(
        PREFIX,
        workspace,
        continuation_id="manifest-tamper-v1",
        _fixture_decision_inputs=_inputs(),
        adapter_factory=_factory(state),
    )
    manifest_path = workspace / "cutoff_manifest.json"
    envelope = json.loads(manifest_path.read_text(encoding="utf-8"))
    envelope["manifest"]["suffix"]["max_concurrency"] = 9
    manifest_path.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(ValueError, match="cutoff manifest changed|hash mismatch"):
        FullPoolSegmentedContinuation().run(
            PREFIX,
            workspace,
            continuation_id="manifest-tamper-v1",
            _fixture_decision_inputs=_inputs(),
            adapter_factory=lambda _lane_id: (_ for _ in ()).throw(
                AssertionError("tampered closed manifest must fail before Adapter creation")
            ),
        )


def test_segmented_migration_unknown_requires_exact_authorization_and_is_explicitly_charged(
    tmp_path: Path,
) -> None:
    unknown_prefix = _unknown_prefix_with_pending_attempts(tmp_path, 2)
    unauthorized_state = _LaneState()
    unauthorized = FullPoolSegmentedContinuation().run(
        unknown_prefix,
        tmp_path / "unauthorized",
        continuation_id="unknown-unauthorized-v1",
        _fixture_decision_inputs=_inputs(),
        adapter_factory=_factory(unauthorized_state),
    )
    assert unauthorized.status is SegmentedContinuationStatus.RECONCILIATION_REQUIRED
    assert unauthorized.unknown_pair_ids == ("u3:message_1:1",)
    assert unauthorized_state.calls == []

    run_identity = json.loads(
        (unknown_prefix / "concurrent_message_execution_run_identity.json").read_text(encoding="utf-8")
    )
    for undercharge in (1, 2):
        authorization = FullPoolReconciliationAuthorization(
            prefix_run_identity_hash=run_identity["identity_hash"],
            unknown_pair_id="u3:message_1:1",
            authorization_reference=f"fixture://rejected-undercharge-{undercharge}",
            physical_attempt_charge=undercharge,
            retry_authorized=True,
        )
        with pytest.raises(ValueError, match="exactly reserve the v1 request window"):
            FullPoolSegmentedContinuation().run(
                unknown_prefix,
                tmp_path / f"undercharge-{undercharge}",
                continuation_id=f"unknown-undercharge-{undercharge}-v1",
                _fixture_decision_inputs=_inputs(),
                adapter_factory=lambda _lane_id: (_ for _ in ()).throw(
                    AssertionError("undercharged authorization must fail before Adapter creation")
                ),
                reconciliation_authorization=authorization,
            )

    authorization = FullPoolReconciliationAuthorization(
        prefix_run_identity_hash=run_identity["identity_hash"],
        unknown_pair_id="u3:message_1:1",
        authorization_reference="fixture://maintainer-approved-one-unknown",
        physical_attempt_charge=3,
        retry_authorized=True,
    )
    authorized_state = _LaneState()
    authorized = FullPoolSegmentedContinuation().run(
        unknown_prefix,
        tmp_path / "authorized",
        continuation_id="unknown-authorized-v1",
        _fixture_decision_inputs=_inputs(),
        adapter_factory=_factory(authorized_state),
        reconciliation_authorization=authorization,
    )

    assert authorized.status is SegmentedContinuationStatus.COMPLETE
    assert authorized.logical_count == 13
    assert authorized.physical_attempt_count == 16
    assert {pair_id for _, pair_id in authorized_state.calls} == {
        f"u{number}:message_1:1" for number in range(3, 13)
    }
    rows = _jsonl(authorized.terminal_rows_path or Path("missing"))
    retried = next(row for row in rows if row["pair_id"] == "u3:message_1:1")
    assert retried["reconciliation_retry"] is True
    envelope = json.loads((authorized.workspace_root / "cutoff_manifest.json").read_text(encoding="utf-8"))
    assert envelope["manifest"]["unknown_count"] == 1
    assert envelope["manifest"]["reconciliation_authorization"] == authorization.model_dump(mode="json")
    assert envelope["manifest"]["caps"]["reserved_logical_total"] == 13
    assert envelope["manifest"]["prefix_accounting"]["pending_physical_count"] == 2
    assert envelope["manifest"]["caps"]["reserved_physical_total"] == 36


def test_segmented_suffix_unknown_fails_closed_and_existing_workspace_never_replays(
    tmp_path: Path,
) -> None:
    state = _LaneState(crash_pair_id="u3:message_1:1")
    workspace = tmp_path / "crashed"
    first = FullPoolSegmentedContinuation().run(
        PREFIX,
        workspace,
        continuation_id="suffix-crash-v1",
        _fixture_decision_inputs=_inputs(),
        adapter_factory=_factory(state),
    )

    assert first.status is SegmentedContinuationStatus.RECONCILIATION_REQUIRED
    assert first.concurrent_suffix_terminal_count == 0
    assert first.logical_count == 13
    assert first.physical_attempt_count == 13
    assert first.unknown_pair_ids == tuple(f"u{number}:message_1:1" for number in range(3, 13))
    assert first.unknown_pair_ids[1:] == tuple(
        f"u{number}:message_1:1" for number in range(4, 13)
    )
    assert len(state.calls) == 10
    ledger = _jsonl(workspace / "segmented_continuation_ledger.jsonl")
    wave_accounting = [row for row in ledger if row["event_type"] == "wave_accounting"]
    assert len(wave_accounting) == 1
    assert wave_accounting[0]["payload"]["actual_physical_attempts"] == 10
    assert [lane["actual_physical_attempts"] for lane in wave_accounting[0]["payload"]["lanes"]] == [
        1
    ] * 10
    ledger_before = (workspace / "segmented_continuation_ledger.jsonl").read_bytes()
    replay_factory_called = False

    def tripwire(_lane_id: int) -> LLMDecisionAdapter:
        nonlocal replay_factory_called
        replay_factory_called = True
        raise AssertionError("reconciliation-required suffix must not replay")

    replay = FullPoolSegmentedContinuation().run(
        PREFIX,
        workspace,
        continuation_id="suffix-crash-v1",
        _fixture_decision_inputs=_inputs(),
        adapter_factory=tripwire,
    )
    assert replay == first
    assert replay_factory_called is False
    assert (workspace / "segmented_continuation_ledger.jsonl").read_bytes() == ledger_before


def test_segmented_terminal_validator_rejects_duplicate_pair_or_terminal_identity() -> None:
    row = {
        "pair_id": "u1:message_1:1",
        "terminal_row_id": "u1:message_1:1:primary",
        "decision_variant": "primary",
    }
    with pytest.raises(ValueError, match="duplicate terminal identity"):
        _validate_unique_terminal_rows((row, dict(row)))
