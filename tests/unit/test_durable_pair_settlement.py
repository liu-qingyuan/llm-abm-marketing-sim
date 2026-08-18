from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

import llm_abm_sim.durable_pair_settlement as settlement_module
from llm_abm_sim.decision import (
    EngageDecision,
    LLMDecisionAdapter,
    ProviderResponseProvenanceUnknown,
)
from llm_abm_sim.durable_pair_settlement import (
    DURABLE_PAIR_SETTLEMENT_JOURNAL_FILE,
    DurablePairDispatch,
    DurablePairSettlement,
    DurablePairTerminal,
)
from llm_abm_sim.schemas import PeerContext, PlatformContext, PostContent, UserProfile


class _SettlementAdapter(LLMDecisionAdapter):
    prompt_version = "settlement-fixture-v1"
    external_request_invocations = 0

    def __init__(self) -> None:
        self.request_invocations = 0

    def decide(
        self,
        post: PostContent,
        profile: UserProfile,
        peer_context: PeerContext,
        platform_context: PlatformContext | None = None,
        time_step: int = 0,
    ) -> EngageDecision:
        del post, profile, peer_context, platform_context, time_step
        self.request_invocations += 1
        return EngageDecision(
            engage=False,
            probability=0.1,
            reason="offline settlement fixture",
            confidence=0.9,
            action="ignore",
            decision_source="offline_settlement_fixture",
        )


def _dispatch(
    pair_id: str,
    execute: Callable[[_SettlementAdapter], DurablePairTerminal],
) -> DurablePairDispatch:
    return DurablePairDispatch(
        pair_id=pair_id,
        plan_identity={"pair_id": pair_id, "pair_schedule_position": int(pair_id.removeprefix("p"))},
        execute=lambda adapter: execute(cast(_SettlementAdapter, adapter)),
    )


def _terminal(adapter: _SettlementAdapter, pair_id: str) -> DurablePairTerminal:
    adapter.request_invocations += 1
    return DurablePairTerminal(
        pair_id=pair_id,
        terminal_row={
            "pair_id": pair_id,
            "terminal_row_id": f"{pair_id}:primary",
            "terminal_status": "succeeded",
            "decision_variant": "primary",
        },
        variant_evidence={
            "pair_id": pair_id,
            "terminal_status": "succeeded",
            "request_invocations": 1,
        },
    )


def test_implementation_failure_is_safe_and_does_not_erase_sibling_terminal(tmp_path: Path) -> None:
    secret_detail = "raw-secret-provider-payload"
    adapters = (_SettlementAdapter(), _SettlementAdapter())

    def fail(adapter: _SettlementAdapter) -> DurablePairTerminal:
        adapter.request_invocations += 1
        raise RuntimeError(secret_detail)

    settlement = DurablePairSettlement(
        tmp_path,
        settlement_identity_hash="a" * 64,
        maximum_attempts_per_dispatch=3,
        max_concurrency=2,
    )
    wave = settlement.settle_wave(
        (
            _dispatch("p0", lambda adapter: _terminal(adapter, "p0")),
            _dispatch("p1", fail),
        ),
        adapters,
        physical_reservation=6,
    )

    assert set(wave.terminal_results) == {"p0"}
    assert wave.implementation_failed_pair_ids == ("p1",)
    assert wave.unknown_pair_ids == ()
    assert wave.canonical_terminal_frontier_pair_ids == ("p0",)
    assert wave.actual_physical_attempts == 2
    assert [adapter.request_invocations for adapter in adapters] == [1, 1]
    journal_bytes = (tmp_path / DURABLE_PAIR_SETTLEMENT_JOURNAL_FILE).read_bytes()
    assert secret_detail.encode() not in journal_bytes
    records = [json.loads(line) for line in journal_bytes.splitlines()]
    failed = next(
        record["payload"]["outcome"]
        for record in records
        if record["event_type"] == "pair_settled"
        and record["payload"]["pair_id"] == "p1"
    )
    assert failed["kind"] == "implementation_failed"
    assert failed["error_category"] == "runtime_error"
    assert len(failed["audit_sha256"]) == 64


def test_replay_accepts_completion_order_and_derives_canonical_frontier(tmp_path: Path) -> None:
    adapters = tuple(_SettlementAdapter() for _ in range(3))

    def terminal_after(pair_id: str, delay: float) -> Callable[[_SettlementAdapter], DurablePairTerminal]:
        def execute(adapter: _SettlementAdapter) -> DurablePairTerminal:
            time.sleep(delay)
            return _terminal(adapter, pair_id)

        return execute

    def unknown_after(adapter: _SettlementAdapter) -> DurablePairTerminal:
        adapter.request_invocations += 1
        time.sleep(0.01)
        raise ProviderResponseProvenanceUnknown("raw response provenance detail")

    settlement = DurablePairSettlement(
        tmp_path,
        settlement_identity_hash="b" * 64,
        maximum_attempts_per_dispatch=3,
        max_concurrency=3,
    )
    wave = settlement.settle_wave(
        (
            _dispatch("p0", terminal_after("p0", 0.03)),
            _dispatch("p1", unknown_after),
            _dispatch("p2", terminal_after("p2", 0.0)),
        ),
        adapters,
        physical_reservation=9,
    )

    assert wave.completion_order != wave.canonical_pair_ids
    assert set(wave.terminal_results) == {"p0", "p2"}
    assert wave.unknown_pair_ids == ("p1",)
    assert wave.canonical_terminal_frontier_pair_ids == ("p0",)
    assert wave.actual_physical_attempts == 3

    replay = DurablePairSettlement(
        tmp_path,
        settlement_identity_hash="b" * 64,
        maximum_attempts_per_dispatch=3,
        max_concurrency=3,
    ).replay()
    assert replay.waves == (wave,)
    assert set(replay.terminal_results) == {"p0", "p2"}
    records = [
        json.loads(line)
        for line in (tmp_path / DURABLE_PAIR_SETTLEMENT_JOURNAL_FILE)
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [
        record["payload"]["pair_id"]
        for record in records
        if record["event_type"] == "pair_settled"
    ] == list(wave.completion_order)
    assert "raw response provenance detail" not in json.dumps(records)


def test_dispatch_without_settlement_replays_as_unknown_without_new_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _SettlementAdapter()
    real_append = settlement_module._append_jsonl

    def crash_after_dispatch(path: Path, payload: dict[str, object]) -> None:
        real_append(path, payload)
        if payload.get("event_type") == "pair_dispatched":
            raise RuntimeError("offline crash after durable dispatch")

    monkeypatch.setattr(settlement_module, "_append_jsonl", crash_after_dispatch)
    settlement = DurablePairSettlement(
        tmp_path,
        settlement_identity_hash="c" * 64,
        maximum_attempts_per_dispatch=3,
        max_concurrency=1,
    )
    with pytest.raises(RuntimeError, match="offline crash"):
        settlement.settle_wave(
            (_dispatch("p0", lambda current: _terminal(current, "p0")),),
            (adapter,),
            physical_reservation=3,
        )
    assert adapter.request_invocations == 0

    monkeypatch.setattr(settlement_module, "_append_jsonl", real_append)
    replay = DurablePairSettlement(
        tmp_path,
        settlement_identity_hash="c" * 64,
        maximum_attempts_per_dispatch=3,
        max_concurrency=1,
    ).replay(seal_inflight=True)

    assert adapter.request_invocations == 0
    assert replay.unknown_pair_ids == ("p0",)
    assert replay.terminal_results == {}
    assert replay.actual_physical_attempts == 0
    assert replay.uncertain_physical_attempts == 3
    assert replay.physical_attempt_charge == 3
    assert replay.waves[0].closed is True
    assert replay.waves[0].canonical_terminal_frontier_pair_ids == ()


def test_crash_after_one_settlement_preserves_capture_and_never_replays_adapters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapters = tuple(_SettlementAdapter() for _ in range(3))
    real_append = settlement_module._append_jsonl
    settlement_writes = 0

    def crash_after_first_settlement(path: Path, payload: dict[str, object]) -> None:
        nonlocal settlement_writes
        real_append(path, payload)
        if payload.get("event_type") == "pair_settled":
            settlement_writes += 1
            if settlement_writes == 1:
                raise RuntimeError("offline crash after first durable settlement")

    monkeypatch.setattr(settlement_module, "_append_jsonl", crash_after_first_settlement)
    settlement = DurablePairSettlement(
        tmp_path,
        settlement_identity_hash="1" * 64,
        maximum_attempts_per_dispatch=3,
        max_concurrency=3,
    )
    with pytest.raises(RuntimeError, match="first durable settlement"):
        settlement.settle_wave(
            tuple(
                _dispatch(
                    f"p{index}",
                    lambda current, pair_id=f"p{index}": _terminal(current, pair_id),
                )
                for index in range(3)
            ),
            adapters,
            physical_reservation=9,
        )
    calls_after_crash = [adapter.request_invocations for adapter in adapters]
    assert calls_after_crash == [1, 1, 1]

    monkeypatch.setattr(settlement_module, "_append_jsonl", real_append)
    replay = DurablePairSettlement(
        tmp_path,
        settlement_identity_hash="1" * 64,
        maximum_attempts_per_dispatch=3,
        max_concurrency=3,
    ).replay(seal_inflight=True)

    assert [adapter.request_invocations for adapter in adapters] == calls_after_crash
    assert len(replay.terminal_results) == 1
    assert len(replay.unknown_pair_ids) == 2
    assert set(replay.terminal_results).isdisjoint(replay.unknown_pair_ids)
    assert set(replay.terminal_results) | set(replay.unknown_pair_ids) == {"p0", "p1", "p2"}
    assert replay.actual_physical_attempts == 1
    assert replay.uncertain_physical_attempts == 6
    assert replay.physical_attempt_charge == 7


def _journal_records(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _write_rechained(path: Path, records: list[dict[str, object]]) -> None:
    previous: str | None = None
    rechained: list[dict[str, object]] = []
    for sequence, source in enumerate(records, start=1):
        body = {key: value for key, value in source.items() if key != "checksum"}
        body["sequence"] = sequence
        body["previous_checksum"] = previous
        checksum = hashlib.sha256(
            json.dumps(
                body,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        rechained.append({**body, "checksum": checksum})
        previous = checksum
    path.write_text(
        "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
            for record in rechained
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("corruption", "message"),
    [
        ("checksum", "checksum mismatch"),
        ("duplicate_settlement", "duplicated"),
        ("undispatched_settlement", "undispatched"),
        ("crossed_identity", "identity is crossed"),
        ("crossed_plan", "dispatch is crossed"),
        ("attempt_accounting", "attempt accounting invariant"),
        ("closure_drift", "closure drifted"),
    ],
)
def test_replay_rejects_corrupt_or_crossed_journal(
    tmp_path: Path,
    corruption: str,
    message: str,
) -> None:
    adapter = _SettlementAdapter()
    DurablePairSettlement(
        tmp_path,
        settlement_identity_hash="d" * 64,
        maximum_attempts_per_dispatch=3,
        max_concurrency=1,
    ).settle_wave(
        (_dispatch("p0", lambda current: _terminal(current, "p0")),),
        (adapter,),
        physical_reservation=3,
    )
    path = tmp_path / DURABLE_PAIR_SETTLEMENT_JOURNAL_FILE
    records = _journal_records(path)
    if corruption == "checksum":
        records[0]["checksum"] = "0" * 64
        path.write_text(
            "".join(
                json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
                for record in records
            ),
            encoding="utf-8",
        )
    else:
        if corruption == "duplicate_settlement":
            settled = next(record for record in records if record["event_type"] == "pair_settled")
            records.insert(-1, json.loads(json.dumps(settled)))
        elif corruption == "undispatched_settlement":
            settled = next(record for record in records if record["event_type"] == "pair_settled")
            cast(dict[str, object], settled["payload"])["pair_id"] = "p9"
        elif corruption == "crossed_identity":
            for record in records:
                record["settlement_identity_hash"] = "e" * 64
        elif corruption == "crossed_plan":
            dispatched = next(record for record in records if record["event_type"] == "pair_dispatched")
            cast(dict[str, object], dispatched["payload"])["plan_identity_sha256"] = "f" * 64
        elif corruption == "attempt_accounting":
            settled = next(record for record in records if record["event_type"] == "pair_settled")
            accounting = cast(
                dict[str, object],
                cast(dict[str, object], settled["payload"])["accounting"],
            )
            accounting["actual_physical_attempts"] = 2
            accounting["physical_attempt_charge"] = 2
        elif corruption == "closure_drift":
            closed = next(record for record in records if record["event_type"] == "wave_closed")
            cast(dict[str, object], closed["payload"])["physical_attempt_charge"] = 99
        _write_rechained(path, records)

    with pytest.raises(ValueError, match=message):
        DurablePairSettlement(
            tmp_path,
            settlement_identity_hash="d" * 64,
            maximum_attempts_per_dispatch=3,
            max_concurrency=1,
        )
