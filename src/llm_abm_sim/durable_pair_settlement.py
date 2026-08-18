from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import cast

from .concurrent_message_experiment import (
    _adapter_external_request_invocations,
    _unwrap_adapter,
)
from .decision import (
    LLMDecisionAdapter,
    ProviderResponseProvenanceUnknown,
)
from .safe_serialization import safe_data

DURABLE_PAIR_SETTLEMENT_JOURNAL_FILE = "durable_pair_settlement_v2.jsonl"
DURABLE_PAIR_SETTLEMENT_SCHEMA = "full-pool-durable-pair-settlement-v2"

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_IMPLEMENTATION_ERROR_CATEGORIES = {
    AssertionError: "assertion_error",
    TypeError: "type_error",
    ValueError: "value_error",
    RuntimeError: "runtime_error",
}


class DurablePairOutcomeKind(str, Enum):
    TERMINAL = "terminal"
    PROVENANCE_UNKNOWN = "provenance_unknown"
    IMPLEMENTATION_FAILED = "implementation_failed"


@dataclass(frozen=True)
class DurablePairTerminal:
    pair_id: str
    terminal_row: Mapping[str, object]
    variant_evidence: Mapping[str, object]


@dataclass(frozen=True)
class DurablePairDispatch:
    """One frozen pair plan and the Adapter call derived from that plan."""

    pair_id: str
    plan_identity: Mapping[str, object]
    execute: Callable[[LLMDecisionAdapter], DurablePairTerminal]


@dataclass(frozen=True)
class DurablePairAccounting:
    request_invocations_delta: int
    external_request_invocations_delta: int
    terminal_evidence_request_invocations: int
    actual_physical_attempts: int
    uncertain_physical_attempts: int
    physical_attempt_charge: int
    recovered_without_settlement: bool = False

    def payload(self) -> dict[str, object]:
        return {
            "request_invocations_delta": self.request_invocations_delta,
            "external_request_invocations_delta": self.external_request_invocations_delta,
            "terminal_evidence_request_invocations": self.terminal_evidence_request_invocations,
            "actual_physical_attempts": self.actual_physical_attempts,
            "uncertain_physical_attempts": self.uncertain_physical_attempts,
            "physical_attempt_charge": self.physical_attempt_charge,
            "recovered_without_settlement": self.recovered_without_settlement,
        }


@dataclass(frozen=True)
class DurablePairOutcome:
    pair_id: str
    lane_id: int
    plan_identity_sha256: str
    kind: DurablePairOutcomeKind
    accounting: DurablePairAccounting
    terminal: DurablePairTerminal | None = None
    error_category: str | None = None
    audit_sha256: str | None = None

    def payload(self) -> dict[str, object]:
        if self.kind is DurablePairOutcomeKind.TERMINAL:
            if self.terminal is None:
                raise ValueError("terminal settlement outcome lacks terminal evidence")
            return {
                "kind": self.kind.value,
                "terminal_row": dict(safe_data(self.terminal.terminal_row)),
                "variant_evidence": dict(safe_data(self.terminal.variant_evidence)),
            }
        if self.error_category is None or self.audit_sha256 is None:
            raise ValueError("non-terminal settlement outcome lacks safe failure evidence")
        return {
            "kind": self.kind.value,
            "error_category": self.error_category,
            "audit_sha256": self.audit_sha256,
        }


@dataclass(frozen=True)
class DurableWaveSettlement:
    wave_index: int
    canonical_pair_ids: tuple[str, ...]
    dispatched_pair_ids: tuple[str, ...]
    completion_order: tuple[str, ...]
    outcomes: tuple[DurablePairOutcome, ...]
    canonical_terminal_frontier_pair_ids: tuple[str, ...]
    actual_physical_attempts: int
    uncertain_physical_attempts: int
    physical_attempt_charge: int
    closed: bool

    @property
    def outcomes_by_pair_id(self) -> dict[str, DurablePairOutcome]:
        return {outcome.pair_id: outcome for outcome in self.outcomes}

    @property
    def terminal_results(self) -> dict[str, DurablePairTerminal]:
        return {
            outcome.pair_id: cast(DurablePairTerminal, outcome.terminal)
            for outcome in self.outcomes
            if outcome.kind is DurablePairOutcomeKind.TERMINAL
        }

    @property
    def unknown_pair_ids(self) -> tuple[str, ...]:
        by_pair = self.outcomes_by_pair_id
        return tuple(
            pair_id
            for pair_id in self.canonical_pair_ids
            if pair_id in by_pair
            and by_pair[pair_id].kind is DurablePairOutcomeKind.PROVENANCE_UNKNOWN
        )

    @property
    def implementation_failed_pair_ids(self) -> tuple[str, ...]:
        by_pair = self.outcomes_by_pair_id
        return tuple(
            pair_id
            for pair_id in self.canonical_pair_ids
            if pair_id in by_pair
            and by_pair[pair_id].kind is DurablePairOutcomeKind.IMPLEMENTATION_FAILED
        )

    @property
    def all_pairs_terminal(self) -> bool:
        return len(self.terminal_results) == len(self.canonical_pair_ids)


@dataclass(frozen=True)
class DurableSettlementReplay:
    settlement_identity_hash: str
    sequence: int
    previous_checksum: str | None
    waves: tuple[DurableWaveSettlement, ...]

    @property
    def terminal_results(self) -> dict[str, DurablePairTerminal]:
        results: dict[str, DurablePairTerminal] = {}
        for wave in self.waves:
            for pair_id, terminal in wave.terminal_results.items():
                if pair_id in results:
                    raise ValueError("durable settlement replay contains a duplicate terminal pair")
                results[pair_id] = terminal
        return results

    @property
    def dispatched_pair_ids(self) -> tuple[str, ...]:
        return tuple(pair_id for wave in self.waves for pair_id in wave.dispatched_pair_ids)

    @property
    def unknown_pair_ids(self) -> tuple[str, ...]:
        return tuple(pair_id for wave in self.waves for pair_id in wave.unknown_pair_ids)

    @property
    def implementation_failed_pair_ids(self) -> tuple[str, ...]:
        return tuple(
            pair_id for wave in self.waves for pair_id in wave.implementation_failed_pair_ids
        )

    @property
    def actual_physical_attempts(self) -> int:
        return sum(wave.actual_physical_attempts for wave in self.waves)

    @property
    def uncertain_physical_attempts(self) -> int:
        return sum(wave.uncertain_physical_attempts for wave in self.waves)

    @property
    def physical_attempt_charge(self) -> int:
        return sum(wave.physical_attempt_charge for wave in self.waves)


@dataclass(frozen=True)
class _AdapterCounterBaseline:
    request_invocations: int
    external_request_invocations: int


@dataclass
class _ReplayWave:
    wave_index: int
    pairs: list[dict[str, object]]
    physical_reservation: int
    maximum_attempts_per_dispatch: int
    dispatched_pair_ids: list[str]
    completion_order: list[str]
    outcomes: dict[str, DurablePairOutcome]


LegacyEventSink = Callable[[str, Mapping[str, object]], None]


class DurablePairSettlement:
    """Drain a frozen wave into independently durable typed pair outcomes.

    Callers provide frozen pair identities, isolated Adapters, and one execution
    function per pair. This Module owns Future completion order, v2 journal event
    ordering, per-pair accounting, crash replay, and canonical frontier derivation.
    """

    def __init__(
        self,
        workspace: str | Path,
        *,
        settlement_identity_hash: str,
        maximum_attempts_per_dispatch: int,
        max_concurrency: int = 10,
        legacy_event_sink: LegacyEventSink | None = None,
    ) -> None:
        self.workspace = Path(workspace)
        if not self.workspace.is_dir() or self.workspace.is_symlink():
            raise ValueError("durable settlement workspace must be an existing real directory")
        if _SHA256_PATTERN.fullmatch(settlement_identity_hash) is None:
            raise ValueError("durable settlement identity must be a lowercase SHA-256 digest")
        if (
            isinstance(maximum_attempts_per_dispatch, bool)
            or not isinstance(maximum_attempts_per_dispatch, int)
            or maximum_attempts_per_dispatch < 1
        ):
            raise ValueError("durable settlement maximum attempts must be a positive int")
        if isinstance(max_concurrency, bool) or not isinstance(max_concurrency, int) or max_concurrency < 1:
            raise ValueError("durable settlement max concurrency must be a positive int")
        self.path = self.workspace / DURABLE_PAIR_SETTLEMENT_JOURNAL_FILE
        self.identity_hash = settlement_identity_hash
        self.maximum_attempts_per_dispatch = maximum_attempts_per_dispatch
        self.max_concurrency = max_concurrency
        self.legacy_event_sink = legacy_event_sink
        self._replay = self._read_replay(allow_inflight=True)
        self._sequence = self._replay.sequence
        self._previous_checksum = self._replay.previous_checksum

    def replay(self, *, seal_inflight: bool = False) -> DurableSettlementReplay:
        replay = self._read_replay(allow_inflight=True)
        self._sequence = replay.sequence
        self._previous_checksum = replay.previous_checksum
        self._replay = replay
        if seal_inflight and replay.waves and not replay.waves[-1].closed:
            self._seal_inflight_wave(replay.waves[-1])
            replay = self._read_replay(allow_inflight=False)
            self._sequence = replay.sequence
            self._previous_checksum = replay.previous_checksum
            self._replay = replay
        return replay

    def settle_wave(
        self,
        dispatches: Sequence[DurablePairDispatch],
        adapters: Sequence[LLMDecisionAdapter],
        *,
        physical_reservation: int,
    ) -> DurableWaveSettlement:
        if self._replay.waves and not self._replay.waves[-1].closed:
            raise ValueError("durable settlement has an inflight wave that must be replayed")
        if not dispatches:
            raise ValueError("durable settlement wave cannot be empty")
        if len(dispatches) > self.max_concurrency:
            raise ValueError("durable settlement wave exceeds configured concurrency")
        if len(adapters) < len(dispatches):
            raise ValueError("durable settlement requires one isolated Adapter per dispatch")
        expected_reservation = len(dispatches) * self.maximum_attempts_per_dispatch
        if physical_reservation != expected_reservation:
            raise ValueError("durable settlement reservation is crossed with the retry window")

        existing_pair_ids = set(self._replay.dispatched_pair_ids)
        pair_ids = [dispatch.pair_id for dispatch in dispatches]
        if any(not isinstance(pair_id, str) or not pair_id for pair_id in pair_ids):
            raise ValueError("durable settlement pair IDs must be non-empty strings")
        if len(set(pair_ids)) != len(pair_ids) or existing_pair_ids.intersection(pair_ids):
            raise ValueError("durable settlement pair dispatch is duplicated")

        reserved_pairs: list[dict[str, object]] = []
        for lane_id, dispatch in enumerate(dispatches):
            plan_identity = dict(safe_data(dispatch.plan_identity))
            if plan_identity.get("pair_id") != dispatch.pair_id:
                raise ValueError("durable settlement plan identity is crossed with its pair")
            reserved_pairs.append(
                {
                    "pair_id": dispatch.pair_id,
                    "lane_id": lane_id,
                    "plan_identity": plan_identity,
                    "plan_identity_sha256": _sha256_json(plan_identity),
                }
            )

        wave_index = len(self._replay.waves)
        reservation_payload = {
            "wave_index": wave_index,
            "pairs": reserved_pairs,
            "physical_reservation": physical_reservation,
            "maximum_attempts_per_dispatch": self.maximum_attempts_per_dispatch,
        }
        self._append("wave_reserved", reservation_payload)
        if self.legacy_event_sink is not None:
            self.legacy_event_sink(
                "suffix_wave_reserved",
                {
                    "pair_ids": pair_ids,
                    "physical_reservation": physical_reservation,
                    "maximum_attempts_per_dispatch": self.maximum_attempts_per_dispatch,
                },
            )

        baselines = tuple(_adapter_counter_baseline(adapters[index]) for index in range(len(dispatches)))
        completed: dict[str, DurablePairOutcome] = {}
        completion_order: list[str] = []
        with ThreadPoolExecutor(
            max_workers=self.max_concurrency,
            thread_name_prefix="durable-pair-settlement",
        ) as executor:
            futures: dict[Future[DurablePairTerminal], tuple[int, DurablePairDispatch, str]] = {}
            for lane_id, dispatch in enumerate(dispatches):
                plan_sha256 = cast(str, reserved_pairs[lane_id]["plan_identity_sha256"])
                dispatched_payload = {
                    "wave_index": wave_index,
                    "pair_id": dispatch.pair_id,
                    "lane_id": lane_id,
                    "plan_identity_sha256": plan_sha256,
                }
                self._append("pair_dispatched", dispatched_payload)
                if self.legacy_event_sink is not None:
                    self.legacy_event_sink(
                        "pair_dispatched",
                        {"pair_id": dispatch.pair_id, "lane_id": lane_id},
                    )
                future = executor.submit(dispatch.execute, adapters[lane_id])
                futures[future] = (lane_id, dispatch, plan_sha256)

            for future in as_completed(futures):
                lane_id, dispatch, plan_sha256 = futures[future]
                try:
                    terminal = future.result()
                    _validate_terminal(dispatch.pair_id, terminal)
                    kind = DurablePairOutcomeKind.TERMINAL
                    error_category = None
                    audit_sha256 = None
                except ProviderResponseProvenanceUnknown as exc:
                    terminal = None
                    kind = DurablePairOutcomeKind.PROVENANCE_UNKNOWN
                    error_category = "provider_response_provenance_unknown"
                    audit_sha256 = _failure_audit_sha256(error_category, exc)
                except BaseException as exc:
                    terminal = None
                    kind = DurablePairOutcomeKind.IMPLEMENTATION_FAILED
                    error_category = _implementation_error_category(exc)
                    audit_sha256 = _failure_audit_sha256(error_category, exc)

                accounting = _completed_accounting(
                    adapter=adapters[lane_id],
                    baseline=baselines[lane_id],
                    terminal=terminal,
                    maximum_attempts_per_dispatch=self.maximum_attempts_per_dispatch,
                )
                outcome = DurablePairOutcome(
                    pair_id=dispatch.pair_id,
                    lane_id=lane_id,
                    plan_identity_sha256=plan_sha256,
                    kind=kind,
                    accounting=accounting,
                    terminal=terminal,
                    error_category=error_category,
                    audit_sha256=audit_sha256,
                )
                self._append(
                    "pair_settled",
                    {
                        "wave_index": wave_index,
                        "pair_id": dispatch.pair_id,
                        "lane_id": lane_id,
                        "plan_identity_sha256": plan_sha256,
                        "outcome": outcome.payload(),
                        "accounting": accounting.payload(),
                    },
                )
                completed[dispatch.pair_id] = outcome
                completion_order.append(dispatch.pair_id)

        wave = _wave_settlement(
            wave_index=wave_index,
            canonical_pair_ids=pair_ids,
            dispatched_pair_ids=pair_ids,
            completion_order=completion_order,
            outcomes=completed,
            closed=True,
        )
        self._append_legacy_closure(wave)
        self._append("wave_closed", _wave_closed_payload(wave))
        self._replay = DurableSettlementReplay(
            settlement_identity_hash=self.identity_hash,
            sequence=self._sequence,
            previous_checksum=self._previous_checksum,
            waves=(*self._replay.waves, wave),
        )
        return wave

    def _append_legacy_closure(self, wave: DurableWaveSettlement) -> None:
        if self.legacy_event_sink is None:
            return
        by_pair = wave.outcomes_by_pair_id
        lanes = []
        for lane_id, pair_id in enumerate(wave.canonical_pair_ids):
            accounting = by_pair[pair_id].accounting
            lanes.append(
                {
                    "lane_id": lane_id,
                    "pair_id": pair_id,
                    "request_invocations_delta": accounting.request_invocations_delta,
                    "external_request_invocations_delta": accounting.external_request_invocations_delta,
                    "terminal_evidence_request_invocations": accounting.terminal_evidence_request_invocations,
                    "actual_physical_attempts": accounting.actual_physical_attempts,
                }
            )
        self.legacy_event_sink(
            "wave_accounting",
            {
                "pair_ids": list(wave.canonical_pair_ids),
                "lanes": lanes,
                "actual_physical_attempts": wave.actual_physical_attempts,
            },
        )
        for pair_id in wave.canonical_terminal_frontier_pair_ids:
            outcome = by_pair[pair_id]
            terminal = cast(DurablePairTerminal, outcome.terminal)
            self.legacy_event_sink(
                "pair_terminal",
                {
                    "pair_id": pair_id,
                    "terminal_row": terminal.terminal_row,
                    "variant_evidence": terminal.variant_evidence,
                },
            )

    def _seal_inflight_wave(self, wave: DurableWaveSettlement) -> None:
        by_pair = wave.outcomes_by_pair_id
        reserved_lane = {pair_id: lane_id for lane_id, pair_id in enumerate(wave.canonical_pair_ids)}
        plan_hashes = self._open_wave_plan_hashes()
        completion_order = list(wave.completion_order)
        outcomes = dict(by_pair)
        for pair_id in wave.dispatched_pair_ids:
            if pair_id in outcomes:
                continue
            lane_id = reserved_lane[pair_id]
            error_category = "dispatch_without_settlement"
            audit_sha256 = _sha256_json(
                {
                    "settlement_identity_hash": self.identity_hash,
                    "wave_index": wave.wave_index,
                    "pair_id": pair_id,
                    "plan_identity_sha256": plan_hashes[pair_id],
                    "error_category": error_category,
                }
            )
            accounting = DurablePairAccounting(
                request_invocations_delta=0,
                external_request_invocations_delta=0,
                terminal_evidence_request_invocations=0,
                actual_physical_attempts=0,
                uncertain_physical_attempts=self.maximum_attempts_per_dispatch,
                physical_attempt_charge=self.maximum_attempts_per_dispatch,
                recovered_without_settlement=True,
            )
            outcome = DurablePairOutcome(
                pair_id=pair_id,
                lane_id=lane_id,
                plan_identity_sha256=plan_hashes[pair_id],
                kind=DurablePairOutcomeKind.PROVENANCE_UNKNOWN,
                accounting=accounting,
                error_category=error_category,
                audit_sha256=audit_sha256,
            )
            self._append(
                "pair_settled",
                {
                    "wave_index": wave.wave_index,
                    "pair_id": pair_id,
                    "lane_id": lane_id,
                    "plan_identity_sha256": plan_hashes[pair_id],
                    "outcome": outcome.payload(),
                    "accounting": accounting.payload(),
                },
            )
            outcomes[pair_id] = outcome
            completion_order.append(pair_id)
        closed = _wave_settlement(
            wave_index=wave.wave_index,
            canonical_pair_ids=wave.canonical_pair_ids,
            dispatched_pair_ids=wave.dispatched_pair_ids,
            completion_order=completion_order,
            outcomes=outcomes,
            closed=True,
        )
        self._append("wave_closed", _wave_closed_payload(closed))

    def _open_wave_plan_hashes(self) -> dict[str, str]:
        replay_wave = _read_open_wave(
            self.path,
            expected_identity_hash=self.identity_hash,
            expected_maximum_attempts=self.maximum_attempts_per_dispatch,
        )
        if replay_wave is None:
            raise ValueError("durable settlement has no inflight wave to seal")
        return {
            cast(str, pair["pair_id"]): cast(str, pair["plan_identity_sha256"])
            for pair in replay_wave.pairs
        }

    def _append(self, event_type: str, payload: Mapping[str, object]) -> None:
        body = {
            "schema_version": DURABLE_PAIR_SETTLEMENT_SCHEMA,
            "sequence": self._sequence + 1,
            "previous_checksum": self._previous_checksum,
            "settlement_identity_hash": self.identity_hash,
            "event_type": event_type,
            "payload": dict(safe_data(payload)),
        }
        checksum = _sha256_json(body)
        _append_jsonl(self.path, {**body, "checksum": checksum})
        self._sequence += 1
        self._previous_checksum = checksum

    def _read_replay(self, *, allow_inflight: bool) -> DurableSettlementReplay:
        return _replay_journal(
            self.path,
            expected_identity_hash=self.identity_hash,
            expected_maximum_attempts=self.maximum_attempts_per_dispatch,
            allow_inflight=allow_inflight,
        )


def _adapter_counter_baseline(adapter: LLMDecisionAdapter) -> _AdapterCounterBaseline:
    leaf, _ = _unwrap_adapter(adapter)
    request_invocations = getattr(leaf, "request_invocations", 0)
    if (
        isinstance(request_invocations, bool)
        or not isinstance(request_invocations, int)
        or request_invocations < 0
    ):
        raise TypeError("adapter request_invocations must be a non-negative int")
    return _AdapterCounterBaseline(
        request_invocations=request_invocations,
        external_request_invocations=_adapter_external_request_invocations(adapter),
    )


def _completed_accounting(
    *,
    adapter: LLMDecisionAdapter,
    baseline: _AdapterCounterBaseline,
    terminal: DurablePairTerminal | None,
    maximum_attempts_per_dispatch: int,
) -> DurablePairAccounting:
    after = _adapter_counter_baseline(adapter)
    request_delta = after.request_invocations - baseline.request_invocations
    external_delta = after.external_request_invocations - baseline.external_request_invocations
    if request_delta < 0 or external_delta < 0:
        raise ValueError("adapter invocation counters moved backwards during pair settlement")
    evidence_delta = (
        0
        if terminal is None
        else _non_negative_int(
            terminal.variant_evidence.get("request_invocations"),
            "terminal evidence request invocations",
        )
    )
    actual = max(request_delta, external_delta, evidence_delta)
    if actual > maximum_attempts_per_dispatch:
        raise ValueError("pair settlement actual attempts exceed the reserved retry window")
    return DurablePairAccounting(
        request_invocations_delta=request_delta,
        external_request_invocations_delta=external_delta,
        terminal_evidence_request_invocations=evidence_delta,
        actual_physical_attempts=actual,
        uncertain_physical_attempts=0,
        physical_attempt_charge=actual,
    )


def _validate_terminal(pair_id: str, terminal: DurablePairTerminal) -> None:
    if not isinstance(terminal, DurablePairTerminal) or terminal.pair_id != pair_id:
        raise ValueError("durable terminal identity is crossed with its dispatch")
    terminal_row = dict(terminal.terminal_row)
    evidence = dict(terminal.variant_evidence)
    if terminal_row.get("pair_id") != pair_id or evidence.get("pair_id") != pair_id:
        raise ValueError("durable terminal evidence is crossed with its pair")
    if terminal_row.get("terminal_status") not in {"succeeded", "provider_failed"}:
        raise ValueError("durable terminal status is unsupported")
    if evidence.get("terminal_status") != terminal_row.get("terminal_status"):
        raise ValueError("durable terminal status is crossed with variant evidence")


def _implementation_error_category(exc: BaseException) -> str:
    for exception_type, category in _IMPLEMENTATION_ERROR_CATEGORIES.items():
        if isinstance(exc, exception_type):
            return category
    return "unexpected_implementation_error"


def _failure_audit_sha256(category: str, exc: BaseException) -> str:
    try:
        message = str(exc)
    except BaseException:
        message = "<unprintable>"
    return _sha256_json(
        {
            "error_category": category,
            "exception_type": f"{type(exc).__module__}.{type(exc).__qualname__}",
            "message_sha256": hashlib.sha256(message.encode("utf-8", errors="replace")).hexdigest(),
        }
    )


def _wave_settlement(
    *,
    wave_index: int,
    canonical_pair_ids: Sequence[str],
    dispatched_pair_ids: Sequence[str],
    completion_order: Sequence[str],
    outcomes: Mapping[str, DurablePairOutcome],
    closed: bool,
) -> DurableWaveSettlement:
    frontier: list[str] = []
    for pair_id in canonical_pair_ids:
        outcome = outcomes.get(pair_id)
        if outcome is None or outcome.kind is not DurablePairOutcomeKind.TERMINAL:
            break
        frontier.append(pair_id)
    ordered_outcomes = tuple(outcomes[pair_id] for pair_id in completion_order)
    actual = sum(outcome.accounting.actual_physical_attempts for outcome in ordered_outcomes)
    uncertain = sum(outcome.accounting.uncertain_physical_attempts for outcome in ordered_outcomes)
    charge = sum(outcome.accounting.physical_attempt_charge for outcome in ordered_outcomes)
    return DurableWaveSettlement(
        wave_index=wave_index,
        canonical_pair_ids=tuple(canonical_pair_ids),
        dispatched_pair_ids=tuple(dispatched_pair_ids),
        completion_order=tuple(completion_order),
        outcomes=ordered_outcomes,
        canonical_terminal_frontier_pair_ids=tuple(frontier),
        actual_physical_attempts=actual,
        uncertain_physical_attempts=uncertain,
        physical_attempt_charge=charge,
        closed=closed,
    )


def _wave_closed_payload(wave: DurableWaveSettlement) -> dict[str, object]:
    counts = Counter(outcome.kind.value for outcome in wave.outcomes)
    dispatched = set(wave.dispatched_pair_ids)
    return {
        "wave_index": wave.wave_index,
        "pair_ids": list(wave.canonical_pair_ids),
        "dispatched_pair_ids": list(wave.dispatched_pair_ids),
        "undispatched_pair_ids": [
            pair_id for pair_id in wave.canonical_pair_ids if pair_id not in dispatched
        ],
        "completion_order": list(wave.completion_order),
        "outcome_counts": dict(sorted(counts.items())),
        "actual_physical_attempts": wave.actual_physical_attempts,
        "uncertain_physical_attempts": wave.uncertain_physical_attempts,
        "physical_attempt_charge": wave.physical_attempt_charge,
        "canonical_terminal_frontier_pair_ids": list(
            wave.canonical_terminal_frontier_pair_ids
        ),
        "all_dispatched_pairs_terminal": wave.all_pairs_terminal,
    }


def _replay_journal(
    path: Path,
    *,
    expected_identity_hash: str,
    expected_maximum_attempts: int,
    allow_inflight: bool,
) -> DurableSettlementReplay:
    if not path.exists():
        return DurableSettlementReplay(expected_identity_hash, 0, None, ())
    if path.is_symlink() or not path.is_file():
        raise ValueError("durable settlement journal must be a regular file")
    sequence = 0
    previous_checksum: str | None = None
    waves: list[DurableWaveSettlement] = []
    open_wave: _ReplayWave | None = None
    seen_pair_ids: set[str] = set()
    exact_record_fields = {
        "schema_version",
        "sequence",
        "previous_checksum",
        "settlement_identity_hash",
        "event_type",
        "payload",
        "checksum",
    }
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            raw = line.strip()
            if not raw:
                continue
            record = _mapping(json.loads(raw), f"settlement journal line {line_number}")
            if set(record) != exact_record_fields:
                raise ValueError("durable settlement journal record fields are not exact")
            checksum = _non_empty(record.pop("checksum", None), "settlement checksum")
            if record.get("schema_version") != DURABLE_PAIR_SETTLEMENT_SCHEMA:
                raise ValueError("durable settlement journal schema is unsupported")
            if record.get("settlement_identity_hash") != expected_identity_hash:
                raise ValueError("durable settlement journal identity is crossed")
            if record.get("sequence") != sequence + 1 or record.get("previous_checksum") != previous_checksum:
                raise ValueError("durable settlement journal sequence or checksum chain is broken")
            if _sha256_json(record) != checksum:
                raise ValueError("durable settlement journal checksum mismatch")
            event_type = record.get("event_type")
            payload = _mapping(record.get("payload"), "settlement payload")
            if event_type == "wave_reserved":
                if open_wave is not None:
                    raise ValueError("durable settlement wave reservation overlaps an open wave")
                if set(payload) != {
                    "wave_index",
                    "pairs",
                    "physical_reservation",
                    "maximum_attempts_per_dispatch",
                }:
                    raise ValueError("durable settlement wave reservation fields are not exact")
                wave_index = _non_negative_int(payload.get("wave_index"), "settlement wave index")
                if wave_index != len(waves):
                    raise ValueError("durable settlement wave index is not canonical")
                maximum_attempts = _positive_int(
                    payload.get("maximum_attempts_per_dispatch"),
                    "settlement maximum attempts",
                )
                if maximum_attempts != expected_maximum_attempts:
                    raise ValueError("durable settlement retry window is crossed")
                pairs = _mapping_sequence(payload.get("pairs"), "settlement reserved pairs")
                if not pairs:
                    raise ValueError("durable settlement wave reservation is empty")
                pair_ids: list[str] = []
                for lane_id, pair in enumerate(pairs):
                    if set(pair) != {
                        "pair_id",
                        "lane_id",
                        "plan_identity",
                        "plan_identity_sha256",
                    }:
                        raise ValueError("durable settlement reserved pair fields are not exact")
                    pair_id = _non_empty(pair.get("pair_id"), "settlement reserved pair ID")
                    if pair.get("lane_id") != lane_id:
                        raise ValueError("durable settlement reserved lane order is crossed")
                    plan_identity = _mapping(pair.get("plan_identity"), "settlement plan identity")
                    if plan_identity.get("pair_id") != pair_id:
                        raise ValueError("durable settlement plan is crossed with its pair")
                    plan_sha256 = _non_empty(
                        pair.get("plan_identity_sha256"), "settlement plan hash"
                    )
                    if _SHA256_PATTERN.fullmatch(plan_sha256) is None or _sha256_json(
                        plan_identity
                    ) != plan_sha256:
                        raise ValueError("durable settlement plan identity hash mismatch")
                    if pair_id in pair_ids or pair_id in seen_pair_ids:
                        raise ValueError("durable settlement reservation duplicates a pair")
                    pair_ids.append(pair_id)
                reservation = _non_negative_int(
                    payload.get("physical_reservation"), "settlement physical reservation"
                )
                if reservation != len(pairs) * maximum_attempts:
                    raise ValueError("durable settlement reservation is crossed with retry windows")
                open_wave = _ReplayWave(
                    wave_index=wave_index,
                    pairs=pairs,
                    physical_reservation=reservation,
                    maximum_attempts_per_dispatch=maximum_attempts,
                    dispatched_pair_ids=[],
                    completion_order=[],
                    outcomes={},
                )
            elif event_type == "pair_dispatched":
                if open_wave is None:
                    raise ValueError("durable settlement dispatch has no wave reservation")
                if set(payload) != {
                    "wave_index",
                    "pair_id",
                    "lane_id",
                    "plan_identity_sha256",
                }:
                    raise ValueError("durable settlement dispatch fields are not exact")
                dispatch_index = len(open_wave.dispatched_pair_ids)
                if dispatch_index >= len(open_wave.pairs):
                    raise ValueError("durable settlement dispatch exceeds its reservation")
                expected_pair = open_wave.pairs[dispatch_index]
                pair_id = _non_empty(payload.get("pair_id"), "settlement dispatched pair ID")
                if (
                    payload.get("wave_index") != open_wave.wave_index
                    or payload.get("lane_id") != expected_pair["lane_id"]
                    or pair_id != expected_pair["pair_id"]
                    or payload.get("plan_identity_sha256")
                    != expected_pair["plan_identity_sha256"]
                ):
                    raise ValueError("durable settlement dispatch is crossed with its frozen plan")
                if pair_id in open_wave.dispatched_pair_ids:
                    raise ValueError("durable settlement dispatch is duplicated")
                open_wave.dispatched_pair_ids.append(pair_id)
                seen_pair_ids.add(pair_id)
            elif event_type == "pair_settled":
                if open_wave is None:
                    raise ValueError("durable pair settlement has no open wave")
                outcome = _parse_settled_outcome(
                    payload,
                    wave=open_wave,
                    expected_maximum_attempts=expected_maximum_attempts,
                )
                if outcome.pair_id in open_wave.outcomes:
                    raise ValueError("durable pair settlement is duplicated")
                open_wave.outcomes[outcome.pair_id] = outcome
                open_wave.completion_order.append(outcome.pair_id)
            elif event_type == "wave_closed":
                if open_wave is None:
                    raise ValueError("durable wave closure has no open wave")
                if set(open_wave.outcomes) != set(open_wave.dispatched_pair_ids):
                    raise ValueError("durable wave closure precedes reduction of every dispatch")
                pair_ids = [cast(str, pair["pair_id"]) for pair in open_wave.pairs]
                wave = _wave_settlement(
                    wave_index=open_wave.wave_index,
                    canonical_pair_ids=pair_ids,
                    dispatched_pair_ids=open_wave.dispatched_pair_ids,
                    completion_order=open_wave.completion_order,
                    outcomes=open_wave.outcomes,
                    closed=True,
                )
                if payload != _wave_closed_payload(wave):
                    raise ValueError("durable settlement wave closure drifted from pair outcomes")
                waves.append(wave)
                open_wave = None
            else:
                raise ValueError("durable settlement journal event type is unsupported")
            sequence += 1
            previous_checksum = checksum
    if open_wave is not None:
        if not allow_inflight:
            raise ValueError("durable settlement journal ends with an inflight wave")
        waves.append(
            _wave_settlement(
                wave_index=open_wave.wave_index,
                canonical_pair_ids=[cast(str, pair["pair_id"]) for pair in open_wave.pairs],
                dispatched_pair_ids=open_wave.dispatched_pair_ids,
                completion_order=open_wave.completion_order,
                outcomes=open_wave.outcomes,
                closed=False,
            )
        )
    return DurableSettlementReplay(
        settlement_identity_hash=expected_identity_hash,
        sequence=sequence,
        previous_checksum=previous_checksum,
        waves=tuple(waves),
    )


def _read_open_wave(
    path: Path,
    *,
    expected_identity_hash: str,
    expected_maximum_attempts: int,
) -> _ReplayWave | None:
    if not path.is_file():
        return None
    sequence = 0
    previous_checksum: str | None = None
    open_wave: _ReplayWave | None = None
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            record = _mapping(json.loads(line), f"settlement journal line {line_number}")
            checksum = _non_empty(record.pop("checksum", None), "settlement checksum")
            if (
                record.get("schema_version") != DURABLE_PAIR_SETTLEMENT_SCHEMA
                or record.get("settlement_identity_hash") != expected_identity_hash
                or record.get("sequence") != sequence + 1
                or record.get("previous_checksum") != previous_checksum
                or _sha256_json(record) != checksum
            ):
                raise ValueError("durable settlement journal cannot recover its inflight wave")
            event_type = record.get("event_type")
            payload = _mapping(record.get("payload"), "settlement payload")
            if event_type == "wave_reserved":
                pairs = _mapping_sequence(payload.get("pairs"), "settlement reserved pairs")
                open_wave = _ReplayWave(
                    wave_index=_non_negative_int(payload.get("wave_index"), "settlement wave index"),
                    pairs=pairs,
                    physical_reservation=_non_negative_int(
                        payload.get("physical_reservation"), "settlement reservation"
                    ),
                    maximum_attempts_per_dispatch=_positive_int(
                        payload.get("maximum_attempts_per_dispatch"),
                        "settlement maximum attempts",
                    ),
                    dispatched_pair_ids=[],
                    completion_order=[],
                    outcomes={},
                )
                if open_wave.maximum_attempts_per_dispatch != expected_maximum_attempts:
                    raise ValueError("durable settlement retry window is crossed")
            elif event_type == "pair_dispatched" and open_wave is not None:
                open_wave.dispatched_pair_ids.append(
                    _non_empty(payload.get("pair_id"), "settlement dispatched pair ID")
                )
            elif event_type == "pair_settled" and open_wave is not None:
                outcome = _parse_settled_outcome(
                    payload,
                    wave=open_wave,
                    expected_maximum_attempts=expected_maximum_attempts,
                )
                open_wave.outcomes[outcome.pair_id] = outcome
                open_wave.completion_order.append(outcome.pair_id)
            elif event_type == "wave_closed":
                open_wave = None
            sequence += 1
            previous_checksum = checksum
    return open_wave


def _parse_settled_outcome(
    payload: Mapping[str, object],
    *,
    wave: _ReplayWave,
    expected_maximum_attempts: int,
) -> DurablePairOutcome:
    if set(payload) != {
        "wave_index",
        "pair_id",
        "lane_id",
        "plan_identity_sha256",
        "outcome",
        "accounting",
    }:
        raise ValueError("durable pair settlement fields are not exact")
    pair_id = _non_empty(payload.get("pair_id"), "settled pair ID")
    if pair_id not in wave.dispatched_pair_ids:
        raise ValueError("durable pair settlement references an undispatched pair")
    pair = next(item for item in wave.pairs if item.get("pair_id") == pair_id)
    if (
        payload.get("wave_index") != wave.wave_index
        or payload.get("lane_id") != pair.get("lane_id")
        or payload.get("plan_identity_sha256") != pair.get("plan_identity_sha256")
    ):
        raise ValueError("durable pair settlement identity is crossed")
    accounting = _parse_accounting(
        _mapping(payload.get("accounting"), "settlement pair accounting"),
        expected_maximum_attempts=expected_maximum_attempts,
    )
    raw_outcome = _mapping(payload.get("outcome"), "settlement typed outcome")
    kind = DurablePairOutcomeKind(
        _non_empty(raw_outcome.get("kind"), "settlement outcome kind")
    )
    terminal: DurablePairTerminal | None = None
    error_category: str | None = None
    audit_sha256: str | None = None
    if kind is DurablePairOutcomeKind.TERMINAL:
        if set(raw_outcome) != {"kind", "terminal_row", "variant_evidence"}:
            raise ValueError("durable terminal settlement fields are not exact")
        terminal = DurablePairTerminal(
            pair_id=pair_id,
            terminal_row=_mapping(raw_outcome.get("terminal_row"), "settled terminal row"),
            variant_evidence=_mapping(
                raw_outcome.get("variant_evidence"), "settled terminal evidence"
            ),
        )
        _validate_terminal(pair_id, terminal)
        evidence_attempts = _non_negative_int(
            terminal.variant_evidence.get("request_invocations"),
            "settled terminal evidence attempts",
        )
        if evidence_attempts != accounting.terminal_evidence_request_invocations:
            raise ValueError("durable terminal accounting is crossed with its evidence")
    else:
        if set(raw_outcome) != {"kind", "error_category", "audit_sha256"}:
            raise ValueError("durable non-terminal settlement fields are not exact")
        error_category = _non_empty(
            raw_outcome.get("error_category"), "settlement error category"
        )
        audit_sha256 = _non_empty(raw_outcome.get("audit_sha256"), "settlement audit hash")
        if _SHA256_PATTERN.fullmatch(audit_sha256) is None:
            raise ValueError("durable settlement audit hash is invalid")
        if kind is DurablePairOutcomeKind.PROVENANCE_UNKNOWN:
            if error_category not in {
                "provider_response_provenance_unknown",
                "dispatch_without_settlement",
            }:
                raise ValueError("durable provenance-unknown category is not allowlisted")
        elif error_category not in set(_IMPLEMENTATION_ERROR_CATEGORIES.values()) | {
            "unexpected_implementation_error"
        }:
            raise ValueError("durable implementation-failure category is not allowlisted")
        if accounting.terminal_evidence_request_invocations != 0:
            raise ValueError("non-terminal settlement cannot claim terminal evidence attempts")
    if accounting.recovered_without_settlement and (
        kind is not DurablePairOutcomeKind.PROVENANCE_UNKNOWN
        or error_category != "dispatch_without_settlement"
    ):
        raise ValueError("recovered dispatch gap must remain a typed provenance unknown")
    return DurablePairOutcome(
        pair_id=pair_id,
        lane_id=cast(int, pair["lane_id"]),
        plan_identity_sha256=cast(str, pair["plan_identity_sha256"]),
        kind=kind,
        accounting=accounting,
        terminal=terminal,
        error_category=error_category,
        audit_sha256=audit_sha256,
    )


def _parse_accounting(
    payload: Mapping[str, object],
    *,
    expected_maximum_attempts: int,
) -> DurablePairAccounting:
    if set(payload) != {
        "request_invocations_delta",
        "external_request_invocations_delta",
        "terminal_evidence_request_invocations",
        "actual_physical_attempts",
        "uncertain_physical_attempts",
        "physical_attempt_charge",
        "recovered_without_settlement",
    }:
        raise ValueError("durable pair accounting fields are not exact")
    request_delta = _non_negative_int(
        payload.get("request_invocations_delta"), "settlement request delta"
    )
    external_delta = _non_negative_int(
        payload.get("external_request_invocations_delta"), "settlement external delta"
    )
    evidence_delta = _non_negative_int(
        payload.get("terminal_evidence_request_invocations"),
        "settlement terminal evidence delta",
    )
    actual = _non_negative_int(
        payload.get("actual_physical_attempts"), "settlement actual attempts"
    )
    uncertain = _non_negative_int(
        payload.get("uncertain_physical_attempts"), "settlement uncertain attempts"
    )
    charge = _non_negative_int(
        payload.get("physical_attempt_charge"), "settlement physical charge"
    )
    recovered = payload.get("recovered_without_settlement")
    if not isinstance(recovered, bool):
        raise ValueError("settlement recovered flag must be a bool")
    if recovered:
        if (
            request_delta != 0
            or external_delta != 0
            or evidence_delta != 0
            or actual != 0
            or uncertain != expected_maximum_attempts
            or charge != expected_maximum_attempts
        ):
            raise ValueError("recovered settlement accounting is crossed with its retry window")
    else:
        if (
            uncertain != 0
            or actual != max(request_delta, external_delta, evidence_delta)
            or actual > expected_maximum_attempts
            or charge != actual
        ):
            raise ValueError("durable pair attempt accounting invariant failed")
    return DurablePairAccounting(
        request_invocations_delta=request_delta,
        external_request_invocations_delta=external_delta,
        terminal_evidence_request_invocations=evidence_delta,
        actual_physical_attempts=actual,
        uncertain_physical_attempts=uncertain,
        physical_attempt_charge=charge,
        recovered_without_settlement=recovered,
    )


def _mapping(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be a mapping")
    return {str(key): item for key, item in value.items()}


def _mapping_sequence(value: object, context: str) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be a list")
    return [_mapping(item, context) for item in value]


def _non_empty(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be a non-empty string")
    return value


def _non_negative_int(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{context} must be a non-negative int")
    return value


def _positive_int(value: object, context: str) -> int:
    result = _non_negative_int(value, context)
    if result < 1:
        raise ValueError(f"{context} must be positive")
    return result


def _sha256_json(value: object) -> str:
    encoded = json.dumps(
        safe_data(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _append_jsonl(path: Path, payload: Mapping[str, object]) -> None:
    line = json.dumps(
        safe_data(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        handle = os.fdopen(descriptor, "a", encoding="utf-8")
    except BaseException:
        os.close(descriptor)
        raise
    with handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())
