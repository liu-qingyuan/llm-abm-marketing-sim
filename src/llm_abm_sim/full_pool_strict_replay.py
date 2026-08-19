from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import cast

from .concurrent_execution_journal import (
    ConcurrentExecutionJournal,
    _build_primary_only_concurrent_execution_run_identity,
)
from .concurrent_message_experiment import (
    ConcurrentMessageExperimentConfig,
    _ConcurrentRuntimeKernel,
    _ConcurrentRuntimeKernelState,
    _PairExecutionPlan,
    _prepare_full_pool_concurrent_runtime_inputs,
    _PrimaryOnlyConcurrentRuntimeConsumer,
)
from .decision import LLMDecisionAdapter
from .durable_pair_settlement import (
    DURABLE_PAIR_SETTLEMENT_JOURNAL_FILE,
    DurablePairDispatch,
    DurablePairOutcome,
    DurablePairOutcomeKind,
    DurablePairSettlement,
    DurablePairTerminal,
    DurableWaveSettlement,
)
from .final_research import FORMAL_RUN_STATUS, VALIDATION_RUN_STATUS
from .full_pool_formal_experiment import (
    FULL_POOL_FORMAL_ADAPTER_IDENTITY,
    FULL_POOL_FORMAL_PHYSICAL_ATTEMPT_CAP,
    FULL_POOL_FORMAL_REQUESTED_MODEL,
    FULL_POOL_FORMAL_TRANSPORT,
    FullPoolFormalRequestContract,
)
from .full_pool_segmented_continuation import (
    _execute_typed_pair,
    _typed_settlement_plan_identity,
)
from .prompt_contracts import CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY
from .prompt_field_summary import CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION
from .provider_request_contract import OMITTED_SAMPLING_PARAMETERS, STRUCTURED_OUTPUT_SCHEMA_HASH
from .safe_serialization import safe_data

STRICT_PAIR_POLICY_FILE = "strict_pair_policy.json"
STRICT_PAIR_POLICY_LEDGER_FILE = "strict_pair_policy_ledger.jsonl"
STRICT_FRESH_REPLAY_STATUS_FILE = "strict_fresh_replay_status.json"

_STRICT_POLICY_SCHEMA = "full-pool-strict-pair-policy-v1"
_STRICT_POLICY_LEDGER_SCHEMA = "full-pool-strict-pair-policy-ledger-v1"
_STRICT_STATUS_SCHEMA = "full-pool-strict-fresh-replay-status-v1"
_STRICT_EXECUTION_SCHEMA = "full-pool-strict-fresh-replay-execution-v1"
_REPLAY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class StrictFreshReplayStatus(str, Enum):
    COMPLETE = "complete"
    STRICT_STOP_PROVIDER_FAILED = "strict_stop_provider_failed"
    STRICT_STOP_PROVENANCE_UNKNOWN = "strict_stop_provenance_unknown"
    STRICT_STOP_IMPLEMENTATION_FAILED = "strict_stop_implementation_failed"
    STRICT_STOP_CAP = "strict_stop_cap"


@dataclass(frozen=True)
class StrictFreshReplayRequest:
    """Frozen inputs for a fresh strict trajectory; no historical terminal can be imported."""

    config: ConcurrentMessageExperimentConfig
    workspace: Path
    replay_id: str
    provider_contract: Mapping[str, object]
    seed_top_k_per_proxy: int
    logical_cap: int
    physical_cap: int = FULL_POOL_FORMAL_PHYSICAL_ATTEMPT_CAP
    maximum_attempts_per_dispatch: int = 3
    max_concurrency: int = 10

    def __post_init__(self) -> None:
        workspace = self.workspace.expanduser().absolute()
        object.__setattr__(self, "workspace", workspace)
        if _REPLAY_ID.fullmatch(self.replay_id) is None:
            raise ValueError("strict replay_id contains unsupported characters")
        dataset = self.config.dataset_dir.expanduser().absolute()
        if (
            workspace == dataset
            or workspace.is_relative_to(dataset)
            or dataset.is_relative_to(workspace)
        ):
            raise ValueError("strict replay workspace must be independent from its dataset")
        expected_provider_contract = strict_formal_provider_contract()
        if _canonical_json(self.provider_contract) != _canonical_json(expected_provider_contract):
            raise ValueError("strict replay Provider/request contract is not the frozen P0 contract")
        object.__setattr__(self, "provider_contract", expected_provider_contract)
        expected_logical = self.config.sample_size * len(self.config.messages)
        if self.logical_cap != expected_logical:
            raise ValueError("strict replay logical cap must equal the fresh full-pool denominator")
        if (
            isinstance(self.seed_top_k_per_proxy, bool)
            or not isinstance(self.seed_top_k_per_proxy, int)
            or self.seed_top_k_per_proxy < 1
        ):
            raise ValueError("strict replay seed_top_k_per_proxy must be a positive int")
        if (
            isinstance(self.physical_cap, bool)
            or not isinstance(self.physical_cap, int)
            or self.physical_cap < 1
        ):
            raise ValueError("strict replay physical cap must be a positive int")
        if self.maximum_attempts_per_dispatch != 3:
            raise ValueError("strict replay requires the frozen three-attempt dispatch window")
        if self.max_concurrency != 10:
            raise ValueError("strict replay requires the frozen ten-lane topology")


@dataclass(frozen=True)
class StrictFreshReplayResult:
    status: StrictFreshReplayStatus
    workspace_root: Path
    replay_identity_hash: str
    committed_batch_count: int
    logical_count: int
    final_succeeded_terminal_count: int
    reconciliation_dispatch_count: int
    settled_actual_attempts: int
    dispatched_without_settlement_uncertainty: int
    charged_physical_attempts: int
    active_physical_reservations: int
    committed_feedback_user_ids: tuple[str, ...]
    strict_stop_pair_ids: tuple[str, ...]
    production_deploy_eligible: bool = False


@dataclass(frozen=True)
class _ReconciliationDispatch:
    pair_id: str
    source_kind: str
    source_wave_index: int
    source_evidence_sha256: str
    plan_identity_sha256: str
    reconciliation_identity_hash: str
    journal_relative_path: str
    physical_reservation: int
    charged_before_dispatch: int


@dataclass(frozen=True)
class _ReconciliationResolution:
    pair_id: str
    reconciliation_identity_hash: str
    journal_sha256: str
    terminal_sha256: str
    actual_physical_attempts: int
    uncertain_physical_attempts: int
    physical_attempt_charge: int


@dataclass(frozen=True)
class _PolicyReplay:
    records: tuple[dict[str, object], ...]
    dispatches: Mapping[str, _ReconciliationDispatch]
    resolutions: Mapping[str, _ReconciliationResolution]
    terminal_event_type: str | None
    terminal_payload: Mapping[str, object] | None


@dataclass(frozen=True)
class _PhysicalAccounting:
    actual: int
    uncertain: int

    @property
    def charged(self) -> int:
        return self.actual + self.uncertain


class StrictPairPolicy:
    """Own one reconciliation dispatch event per pair and every typed strict stop."""

    def __init__(
        self,
        workspace: Path,
        *,
        identity_hash: str,
        physical_cap: int,
        maximum_attempts_per_dispatch: int,
    ) -> None:
        self.workspace = workspace
        self.identity_hash = _digest(identity_hash, "strict policy identity")
        self.physical_cap = physical_cap
        self.maximum_attempts_per_dispatch = maximum_attempts_per_dispatch
        self.path = workspace / STRICT_PAIR_POLICY_FILE
        self.ledger_path = workspace / STRICT_PAIR_POLICY_LEDGER_FILE
        self.expected_policy = {
            "schema_version": _STRICT_POLICY_SCHEMA,
            "identity_hash": identity_hash,
            "physical_cap": physical_cap,
            "maximum_attempts_per_dispatch": maximum_attempts_per_dispatch,
            "maximum_reconciliations_per_pair": 1,
            "slot_and_dispatch_event_is_atomic": True,
            "provider_failed_is_provisional": True,
            "production_deploy_eligible": False,
        }
        self._create_or_validate()

    def _create_or_validate(self) -> None:
        if self.path.exists() or self.path.is_symlink():
            if self.path.is_symlink() or not self.path.is_file():
                raise ValueError("strict pair policy must be one regular file")
            if _read_json(self.path) != self.expected_policy:
                raise ValueError("strict pair policy drifted from its frozen contract")
        else:
            _exclusive_write_json(self.path, self.expected_policy)
            self.path.chmod(0o444)
        if not self.ledger_path.exists():
            _append_policy_event(
                self.ledger_path,
                identity_hash=self.identity_hash,
                sequence=1,
                previous_checksum=None,
                event_type="policy_created",
                payload={"policy_sha256": _sha256_file(self.path)},
            )
        self.replay()

    def replay(self) -> _PolicyReplay:
        if self.ledger_path.is_symlink() or not self.ledger_path.is_file():
            raise ValueError("strict pair policy ledger is missing or unsafe")
        records: list[dict[str, object]] = []
        previous: str | None = None
        dispatches: dict[str, _ReconciliationDispatch] = {}
        resolutions: dict[str, _ReconciliationResolution] = {}
        terminal_event_type: str | None = None
        terminal_payload: dict[str, object] | None = None
        for expected_sequence, line in enumerate(
            self.ledger_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line:
                continue
            record = _mapping(json.loads(line), "strict policy ledger record")
            if set(record) != {
                "schema_version",
                "sequence",
                "previous_checksum",
                "policy_identity_hash",
                "event_type",
                "payload",
                "checksum",
            }:
                raise ValueError("strict policy ledger fields are not exact")
            checksum = _digest(record.get("checksum"), "strict policy checksum")
            body = {key: value for key, value in record.items() if key != "checksum"}
            if (
                record.get("schema_version") != _STRICT_POLICY_LEDGER_SCHEMA
                or record.get("sequence") != expected_sequence
                or record.get("previous_checksum") != previous
                or record.get("policy_identity_hash") != self.identity_hash
                or _sha256_json(body) != checksum
            ):
                raise ValueError("strict policy ledger hash chain is invalid")
            event_type = _non_empty(record.get("event_type"), "strict policy event type")
            payload = _mapping(record.get("payload"), "strict policy event payload")
            if expected_sequence == 1:
                if event_type != "policy_created" or payload != {
                    "policy_sha256": _sha256_file(self.path)
                }:
                    raise ValueError("strict policy ledger lacks its create-once event")
            else:
                if terminal_event_type is not None:
                    raise ValueError("strict policy ledger has events after its terminal state")
                if event_type == "reconciliation_dispatched":
                    expected_fields = {
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
                    if set(payload) != expected_fields:
                        raise ValueError("strict reconciliation dispatch fields are not exact")
                    pair_id = _non_empty(payload.get("pair_id"), "reconciliation pair_id")
                    source_kind = _non_empty(payload.get("source_kind"), "reconciliation source kind")
                    relative = PurePosixPath(
                        _non_empty(payload.get("journal_relative_path"), "reconciliation journal path")
                    )
                    dispatch = _ReconciliationDispatch(
                        pair_id=pair_id,
                        source_kind=source_kind,
                        source_wave_index=_non_negative_int(
                            payload.get("source_wave_index"), "reconciliation source wave"
                        ),
                        source_evidence_sha256=_digest(
                            payload.get("source_evidence_sha256"), "source evidence hash"
                        ),
                        plan_identity_sha256=_digest(
                            payload.get("plan_identity_sha256"), "plan identity hash"
                        ),
                        reconciliation_identity_hash=_digest(
                            payload.get("reconciliation_identity_hash"),
                            "reconciliation identity hash",
                        ),
                        journal_relative_path=relative.as_posix(),
                        physical_reservation=_non_negative_int(
                            payload.get("physical_reservation"),
                            "reconciliation physical reservation",
                        ),
                        charged_before_dispatch=_non_negative_int(
                            payload.get("charged_before_dispatch"),
                            "charged attempts before reconciliation",
                        ),
                    )
                    if (
                        pair_id in dispatches
                        or source_kind not in {"provider_failed", "provenance_unknown"}
                        or relative.is_absolute()
                        or ".." in relative.parts
                        or relative.parts[:1] != ("reconciliation-settlements",)
                        or dispatch.physical_reservation
                        != self.maximum_attempts_per_dispatch
                        or dispatch.charged_before_dispatch
                        + dispatch.physical_reservation
                        > self.physical_cap
                    ):
                        raise ValueError("strict reconciliation dispatch is duplicated or crossed")
                    dispatches[pair_id] = dispatch
                elif event_type == "reconciliation_resolved":
                    if set(payload) != {
                        "pair_id",
                        "reconciliation_identity_hash",
                        "journal_sha256",
                        "terminal_sha256",
                        "actual_physical_attempts",
                        "uncertain_physical_attempts",
                        "physical_attempt_charge",
                    }:
                        raise ValueError("strict reconciliation resolution fields are not exact")
                    pair_id = _non_empty(payload.get("pair_id"), "resolved pair_id")
                    dispatch = dispatches.get(pair_id)
                    resolution = _ReconciliationResolution(
                        pair_id=pair_id,
                        reconciliation_identity_hash=_digest(
                            payload.get("reconciliation_identity_hash"),
                            "resolved reconciliation identity",
                        ),
                        journal_sha256=_digest(
                            payload.get("journal_sha256"), "reconciliation journal hash"
                        ),
                        terminal_sha256=_digest(
                            payload.get("terminal_sha256"), "reconciliation terminal hash"
                        ),
                        actual_physical_attempts=_non_negative_int(
                            payload.get("actual_physical_attempts"),
                            "reconciliation actual attempts",
                        ),
                        uncertain_physical_attempts=_non_negative_int(
                            payload.get("uncertain_physical_attempts"),
                            "reconciliation uncertain attempts",
                        ),
                        physical_attempt_charge=_non_negative_int(
                            payload.get("physical_attempt_charge"),
                            "reconciliation physical charge",
                        ),
                    )
                    if (
                        dispatch is None
                        or pair_id in resolutions
                        or resolution.reconciliation_identity_hash
                        != dispatch.reconciliation_identity_hash
                        or resolution.uncertain_physical_attempts != 0
                        or not 1
                        <= resolution.actual_physical_attempts
                        <= self.maximum_attempts_per_dispatch
                        or resolution.physical_attempt_charge
                        != resolution.actual_physical_attempts
                    ):
                        raise ValueError("strict reconciliation resolution is crossed")
                    resolutions[pair_id] = resolution
                elif event_type == "strict_stopped":
                    if set(payload) != {"status", "pair_id", "reason", "audit_sha256"}:
                        raise ValueError("strict stop fields are not exact")
                    StrictFreshReplayStatus(
                        _non_empty(payload.get("status"), "strict stop status")
                    )
                    _non_empty(payload.get("pair_id"), "strict stop pair_id")
                    _non_empty(payload.get("reason"), "strict stop reason")
                    _digest(payload.get("audit_sha256"), "strict stop audit hash")
                    terminal_event_type = event_type
                    terminal_payload = payload
                elif event_type == "runtime_completed":
                    if set(payload) != {
                        "logical_count",
                        "committed_batch_count",
                        "charged_physical_attempts",
                    }:
                        raise ValueError("strict completion fields are not exact")
                    _non_negative_int(payload.get("logical_count"), "completed logical count")
                    _non_negative_int(
                        payload.get("committed_batch_count"), "completed batch count"
                    )
                    _non_negative_int(
                        payload.get("charged_physical_attempts"),
                        "completed charged attempts",
                    )
                    terminal_event_type = event_type
                    terminal_payload = payload
                else:
                    raise ValueError("strict policy ledger event type is unsupported")
            records.append(record)
            previous = checksum
        if not records:
            raise ValueError("strict policy ledger is empty")
        return _PolicyReplay(
            records=tuple(records),
            dispatches=dispatches,
            resolutions=resolutions,
            terminal_event_type=terminal_event_type,
            terminal_payload=terminal_payload,
        )

    def begin_reconciliation(
        self,
        *,
        pair_id: str,
        source_kind: str,
        source_wave_index: int,
        source_evidence_sha256: str,
        plan_identity_sha256: str,
        reconciliation_identity_hash: str,
        journal_relative_path: str,
        charged_before_dispatch: int,
    ) -> tuple[_ReconciliationDispatch, bool]:
        replay = self.replay()
        existing = replay.dispatches.get(pair_id)
        expected = _ReconciliationDispatch(
            pair_id=pair_id,
            source_kind=source_kind,
            source_wave_index=source_wave_index,
            source_evidence_sha256=source_evidence_sha256,
            plan_identity_sha256=plan_identity_sha256,
            reconciliation_identity_hash=reconciliation_identity_hash,
            journal_relative_path=journal_relative_path,
            physical_reservation=self.maximum_attempts_per_dispatch,
            charged_before_dispatch=charged_before_dispatch,
        )
        if existing is not None:
            if existing != expected:
                raise ValueError("strict reconciliation slot is crossed with its original outcome")
            return existing, False
        if replay.terminal_event_type is not None:
            raise ValueError("strict reconciliation cannot begin after terminal state")
        self._append(
            "reconciliation_dispatched",
            {
                "pair_id": pair_id,
                "source_kind": source_kind,
                "source_wave_index": source_wave_index,
                "source_evidence_sha256": source_evidence_sha256,
                "plan_identity_sha256": plan_identity_sha256,
                "reconciliation_identity_hash": reconciliation_identity_hash,
                "journal_relative_path": journal_relative_path,
                "physical_reservation": self.maximum_attempts_per_dispatch,
                "charged_before_dispatch": charged_before_dispatch,
            },
        )
        return cast(_ReconciliationDispatch, self.replay().dispatches[pair_id]), True

    def resolve(
        self,
        *,
        pair_id: str,
        reconciliation_identity_hash: str,
        journal_sha256: str,
        terminal_sha256: str,
        accounting: _PhysicalAccounting,
    ) -> None:
        replay = self.replay()
        if pair_id in replay.resolutions:
            return
        self._append(
            "reconciliation_resolved",
            {
                "pair_id": pair_id,
                "reconciliation_identity_hash": reconciliation_identity_hash,
                "journal_sha256": journal_sha256,
                "terminal_sha256": terminal_sha256,
                "actual_physical_attempts": accounting.actual,
                "uncertain_physical_attempts": accounting.uncertain,
                "physical_attempt_charge": accounting.charged,
            },
        )

    def stop(
        self,
        *,
        status: StrictFreshReplayStatus,
        pair_id: str,
        reason: str,
        audit_sha256: str,
    ) -> None:
        replay = self.replay()
        if replay.terminal_event_type is not None:
            return
        if status is StrictFreshReplayStatus.COMPLETE:
            raise ValueError("strict stop cannot use the complete status")
        self._append(
            "strict_stopped",
            {
                "status": status.value,
                "pair_id": pair_id,
                "reason": reason,
                "audit_sha256": _digest(audit_sha256, "strict stop audit hash"),
            },
        )

    def complete(
        self,
        *,
        logical_count: int,
        committed_batch_count: int,
        charged_physical_attempts: int,
    ) -> None:
        replay = self.replay()
        if replay.terminal_event_type is not None:
            return
        self._append(
            "runtime_completed",
            {
                "logical_count": logical_count,
                "committed_batch_count": committed_batch_count,
                "charged_physical_attempts": charged_physical_attempts,
            },
        )

    def _append(self, event_type: str, payload: Mapping[str, object]) -> None:
        replay = self.replay()
        previous = _digest(replay.records[-1].get("checksum"), "strict policy checksum")
        _append_policy_event(
            self.ledger_path,
            identity_hash=self.identity_hash,
            sequence=len(replay.records) + 1,
            previous_checksum=previous,
            event_type=event_type,
            payload=payload,
        )


class StrictFullPoolFormalReplay:
    """Run or resume a fresh trajectory behind one strict pre-commit settlement Interface."""

    def run(
        self,
        request: StrictFreshReplayRequest,
        *,
        adapter_factory: Callable[[int], LLMDecisionAdapter],
    ) -> StrictFreshReplayResult:
        prepared = _prepare_full_pool_concurrent_runtime_inputs(
            request.config,
            seed_top_k_per_proxy=request.seed_top_k_per_proxy,
        )
        if len(prepared.cohort.sample_user_ids) != request.config.sample_size:
            raise ValueError("strict replay prepared membership does not match sample_size")
        identity = _strict_run_identity(request, prepared.cohort.sample_audit)
        workspace_exists = request.workspace.exists() or request.workspace.is_symlink()
        journal = (
            ConcurrentExecutionJournal.open_resume(request.workspace, identity=identity)
            if workspace_exists
            else ConcurrentExecutionJournal.open_new(request.workspace, identity=identity)
        )
        try:
            policy = StrictPairPolicy(
                request.workspace,
                identity_hash=cast(str, identity["identity_hash"]),
                physical_cap=request.physical_cap,
                maximum_attempts_per_dispatch=request.maximum_attempts_per_dispatch,
            )
            original_root = request.workspace / "original-settlements"
            if original_root.exists() or original_root.is_symlink():
                if original_root.is_symlink() or not original_root.is_dir():
                    raise ValueError("strict original settlement root is unsafe")
            else:
                original_root.mkdir()
                _fsync_directory(request.workspace)
            settlement = DurablePairSettlement(
                original_root,
                settlement_identity_hash=_sha256_json(
                    {"run_identity_hash": identity["identity_hash"], "role": "original"}
                ),
                maximum_attempts_per_dispatch=request.maximum_attempts_per_dispatch,
                max_concurrency=request.max_concurrency,
            )
            settlement.replay(seal_inflight=True)
            state = _ConcurrentRuntimeKernelState(
                cohort=prepared.cohort,
                exposed_by_message={message.message_id: set() for message in request.config.messages},
                campaign_engaged_user_ids=set(),
            )
            kernel = _ConcurrentRuntimeKernel.primary_only(
                config=request.config,
                state=state,
                base_network_by_user=prepared.base_network_by_user,
                neighbors_by_user=prepared.neighbors_by_user,
                journal=journal,
            )
            if workspace_exists:
                kernel.restore(
                    journal._replay_runtime(),
                    result_builder=_PrimaryOnlyConcurrentRuntimeConsumer._replayed_primary_result_row,
                )

            terminal = policy.replay()
            if terminal.terminal_event_type is not None:
                result = _build_result(
                    request=request,
                    identity_hash=cast(str, identity["identity_hash"]),
                    policy=policy,
                    settlement=settlement,
                    journal=journal,
                    state=state,
                )
                _write_status(request.workspace, result)
                return result

            adapters: list[LLMDecisionAdapter] | None = None

            def lanes() -> Sequence[LLMDecisionAdapter]:
                nonlocal adapters
                if adapters is None:
                    adapters = _create_adapters(request, adapter_factory)
                return adapters

            while state.next_time_step < request.config.horizon:
                if kernel.active_batch is None:
                    kernel.plan_batch()
                pending = kernel.pending_plans()
                final_results = _settle_strict_batch(
                    request=request,
                    plans=pending,
                    settlement=settlement,
                    policy=policy,
                    adapters=lanes,
                )
                if final_results is None:
                    result = _build_result(
                        request=request,
                        identity_hash=cast(str, identity["identity_hash"]),
                        policy=policy,
                        settlement=settlement,
                        journal=journal,
                        state=state,
                    )
                    _write_status(request.workspace, result)
                    return result
                _register_final_results(kernel, pending, final_results)
                kernel.commit_primary_batch()

            accounting = _physical_accounting(
                request=request,
                policy=policy,
                settlement=settlement,
                seal_inflight=True,
            )
            policy.complete(
                logical_count=len(settlement.replay().dispatched_pair_ids),
                committed_batch_count=state.next_time_step,
                charged_physical_attempts=accounting.charged,
            )
            result = _build_result(
                request=request,
                identity_hash=cast(str, identity["identity_hash"]),
                policy=policy,
                settlement=settlement,
                journal=journal,
                state=state,
            )
            _write_status(request.workspace, result)
            return result
        finally:
            journal.close()


def strict_formal_provider_contract() -> dict[str, object]:
    prompt = CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.resolve(
        CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION
    )
    request = FullPoolFormalRequestContract(
        schema_version="provider-request-contract-v1",
        requested_model=FULL_POOL_FORMAL_REQUESTED_MODEL,
        prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
        prompt_canonical_hash=prompt.canonical_hash,
        wire_api="responses",
        reasoning_effort="low",
        output_token_ceiling=256,
        timeout_seconds=30.0,
        max_retries=2,
        retry_backoff_seconds=1.0,
        structured_output_schema_version="engage-decision-output-v1",
        structured_output_schema_hash=STRUCTURED_OUTPUT_SCHEMA_HASH,
        omitted_parameters=OMITTED_SAMPLING_PARAMETERS,
    )
    contract = {
        "provider": "Pi",
        "provider_transport": FULL_POOL_FORMAL_TRANSPORT,
        "adapter_identity": FULL_POOL_FORMAL_ADAPTER_IDENTITY,
        "requested_model": FULL_POOL_FORMAL_REQUESTED_MODEL,
        "model": FULL_POOL_FORMAL_REQUESTED_MODEL,
        "prompt_version": CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
        "max_retries": 2,
        "maximum_attempts_per_dispatch": 3,
        "fresh_no_cache": True,
        "request_contract": request.model_dump(mode="python"),
        "external_transport": {
            "provider_transport": FULL_POOL_FORMAL_TRANSPORT,
            "adapter_identity": FULL_POOL_FORMAL_ADAPTER_IDENTITY,
        },
    }
    return _mapping(json.loads(_canonical_json(contract)), "strict Provider contract")


def _strict_run_identity(
    request: StrictFreshReplayRequest,
    sample_audit: Mapping[str, object],
) -> dict[str, object]:
    configuration = request.config.snapshot(
        sampling_status=(
            FORMAL_RUN_STATUS
            if request.config.configuration_profile == "production"
            else VALIDATION_RUN_STATUS
        ),
        production_deploy_eligible=False,
    )
    configuration.update(
        {
            "runtime_consumer": "strict_full_pool_formal_replay",
            "primary_prompt_version": CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
            "fresh_from_batch_zero": True,
        }
    )
    prompt = CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.resolve(
        CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION
    )
    identity = _build_primary_only_concurrent_execution_run_identity(
        output_target=request.workspace.with_name(f"{request.workspace.name}-source-v4"),
        operational_workspace=request.workspace,
        configuration_snapshot=configuration,
        message_snapshot=[message.model_dump(mode="json") for message in request.config.messages],
        sample_audit=sample_audit,
        dataset_dir=request.config.dataset_dir,
        primary_provider_metadata=request.provider_contract,
        prompt_contract={"primary": prompt.audit_record()},
        execution_contract={
            "schema_version": _STRICT_EXECUTION_SCHEMA,
            "replay_id": request.replay_id,
            "seed_top_k_per_proxy": request.seed_top_k_per_proxy,
            "logical_cap": request.logical_cap,
            "physical_cap": request.physical_cap,
            "maximum_attempts_per_dispatch": request.maximum_attempts_per_dispatch,
            "max_concurrency": request.max_concurrency,
            "fresh_no_cache": True,
            "maximum_reconciliations_per_pair": 1,
        },
    )
    return _mapping(json.loads(_canonical_json(identity)), "strict run identity")


def _create_adapters(
    request: StrictFreshReplayRequest,
    adapter_factory: Callable[[int], LLMDecisionAdapter],
) -> list[LLMDecisionAdapter]:
    adapters: list[LLMDecisionAdapter] = []
    for lane_id in range(request.max_concurrency):
        adapter = adapter_factory(lane_id)
        if not isinstance(adapter, LLMDecisionAdapter):
            raise TypeError("strict replay adapter_factory must return LLMDecisionAdapter instances")
        if any(adapter is existing for existing in adapters):
            raise ValueError("strict replay requires one isolated Adapter per lane")
        _validate_adapter(adapter, request.provider_contract)
        adapters.append(adapter)
    return adapters


def _validate_adapter(
    adapter: LLMDecisionAdapter,
    expected: Mapping[str, object],
) -> None:
    if getattr(adapter, "wrapped", None) is not None or getattr(adapter, "cache", None) is not None:
        raise ValueError("strict replay forbids cached or wrapped Adapters")
    metadata = getattr(adapter, "safe_metadata", None)
    if not isinstance(metadata, Mapping):
        raise ValueError("strict replay Adapter safe metadata is missing")
    transport = metadata.get("external_transport", {})
    if not isinstance(transport, Mapping):
        raise ValueError("strict replay Adapter transport metadata is malformed")
    actual_transport = (
        metadata.get("provider_transport")
        or transport.get("provider_transport")
        or metadata.get("provider")
    )
    actual_identity = metadata.get("adapter_identity") or transport.get("adapter_identity")
    actual_model = metadata.get("requested_model", metadata.get("model"))
    if (
        actual_transport != expected.get("provider_transport")
        or actual_identity != expected.get("adapter_identity")
        or actual_model != expected.get("requested_model")
        or metadata.get("prompt_version", getattr(adapter, "prompt_version", None))
        != expected.get("prompt_version")
        or metadata.get("max_retries") != 2
        or metadata.get("fresh_no_cache") is not True
        or _canonical_json(metadata.get("request_contract"))
        != _canonical_json(expected.get("request_contract"))
    ):
        raise ValueError("strict replay Adapter differs from the frozen Provider/request contract")
    leaf_request_count = getattr(adapter, "request_invocations", 0)
    external_count = getattr(adapter, "external_request_invocations", 0)
    if leaf_request_count != 0 or external_count != 0:
        raise ValueError("strict replay Adapter must be a fresh no-cache decision store")


def _settle_strict_batch(
    *,
    request: StrictFreshReplayRequest,
    plans: Sequence[_PairExecutionPlan],
    settlement: DurablePairSettlement,
    policy: StrictPairPolicy,
    adapters: Callable[[], Sequence[LLMDecisionAdapter]],
) -> dict[str, DurablePairTerminal] | None:
    plan_by_id = {plan.pair_id: plan for plan in plans}
    results: dict[str, DurablePairTerminal] = {}
    cursor = 0
    while cursor < len(plans):
        policy_replay = policy.replay()
        if policy_replay.terminal_event_type is not None:
            return None
        replay = settlement.replay(seal_inflight=True)
        outcomes = {
            outcome.pair_id: outcome
            for wave in replay.waves
            for outcome in wave.outcomes
        }
        plan = plans[cursor]
        outcome = outcomes.get(plan.pair_id)
        if outcome is not None:
            terminal = _finalize_original_outcome(
                request=request,
                plan=plan,
                outcome=outcome,
                source_wave_index=_wave_index_for_pair(replay.waves, plan.pair_id),
                policy=policy,
                settlement=settlement,
                adapter_supplier=adapters,
            )
            if terminal is None:
                return None
            results[plan.pair_id] = terminal
            cursor += 1
            continue

        missing: list[_PairExecutionPlan] = []
        for candidate in plans[cursor : cursor + request.max_concurrency]:
            if candidate.pair_id in outcomes:
                break
            missing.append(candidate)
        logical_count = len(replay.dispatched_pair_ids)
        accounting = _physical_accounting(
            request=request,
            policy=policy,
            settlement=settlement,
            seal_inflight=False,
        )
        wave_plans = missing[: request.max_concurrency]
        requested_reservation = (
            len(wave_plans) * request.maximum_attempts_per_dispatch
        )
        if (
            logical_count + len(wave_plans) > request.logical_cap
            or accounting.charged + requested_reservation > request.physical_cap
        ):
            _stop_for_cap(
                policy=policy,
                pair_id=plan.pair_id,
                accounting=accounting,
                requested=requested_reservation,
            )
            return None
        _guard_pre_call_cap(
            accounting=accounting,
            active_reservations=0,
            requested_reservation=requested_reservation,
            physical_cap=request.physical_cap,
        )
        dispatches = tuple(
            DurablePairDispatch(
                pair_id=item.pair_id,
                plan_identity=_typed_settlement_plan_identity(item),
                execute=lambda adapter, item=item: _execute_typed_pair(
                    plan=item,
                    adapter=adapter,
                    provider_metadata=request.provider_contract,
                ),
            )
            for item in wave_plans
        )
        wave = settlement.settle_wave(
            dispatches,
            adapters(),
            physical_reservation=requested_reservation,
        )
        for captured in wave.outcomes:
            _validate_dispatch_accounting(captured, request.maximum_attempts_per_dispatch)

    if set(results) != set(plan_by_id):
        raise ValueError("strict batch settlement did not close every pending plan")
    return {plan.pair_id: results[plan.pair_id] for plan in plans}


def _finalize_original_outcome(
    *,
    request: StrictFreshReplayRequest,
    plan: _PairExecutionPlan,
    outcome: DurablePairOutcome,
    source_wave_index: int,
    policy: StrictPairPolicy,
    settlement: DurablePairSettlement,
    adapter_supplier: Callable[[], Sequence[LLMDecisionAdapter]],
) -> DurablePairTerminal | None:
    _validate_dispatch_accounting(outcome, request.maximum_attempts_per_dispatch)
    if outcome.kind is DurablePairOutcomeKind.IMPLEMENTATION_FAILED:
        policy.stop(
            status=StrictFreshReplayStatus.STRICT_STOP_IMPLEMENTATION_FAILED,
            pair_id=plan.pair_id,
            reason=_non_empty(outcome.error_category, "implementation failure category"),
            audit_sha256=_digest(outcome.audit_sha256, "implementation failure audit hash"),
        )
        return None
    if outcome.kind is DurablePairOutcomeKind.TERMINAL:
        terminal = cast(DurablePairTerminal, outcome.terminal)
        if terminal.terminal_row.get("terminal_status") == "succeeded":
            return terminal
        if terminal.terminal_row.get("terminal_status") != "provider_failed":
            raise ValueError("strict original terminal status is unsupported")
        source_kind = "provider_failed"
        source_evidence_sha256 = _terminal_sha256(terminal)
    else:
        source_kind = "provenance_unknown"
        source_evidence_sha256 = _digest(outcome.audit_sha256, "unknown outcome audit hash")
    return _reconcile_provisional_outcome(
        request=request,
        plan=plan,
        source_kind=source_kind,
        source_wave_index=source_wave_index,
        source_evidence_sha256=source_evidence_sha256,
        source_lane_id=outcome.lane_id,
        policy=policy,
        settlement=settlement,
        adapter_supplier=adapter_supplier,
    )


def _reconcile_provisional_outcome(
    *,
    request: StrictFreshReplayRequest,
    plan: _PairExecutionPlan,
    source_kind: str,
    source_wave_index: int,
    source_evidence_sha256: str,
    source_lane_id: int,
    policy: StrictPairPolicy,
    settlement: DurablePairSettlement,
    adapter_supplier: Callable[[], Sequence[LLMDecisionAdapter]],
) -> DurablePairTerminal | None:
    replay = policy.replay()
    existing = replay.dispatches.get(plan.pair_id)
    if existing is not None:
        resolution = replay.resolutions.get(plan.pair_id)
        if resolution is not None:
            return _load_resolved_terminal(policy, existing, resolution)
        return _recover_unresolved_reconciliation(
            request=request,
            policy=policy,
            dispatch=existing,
        )

    accounting = _physical_accounting(
        request=request,
        policy=policy,
        settlement=settlement,
        seal_inflight=False,
    )
    if accounting.charged + request.maximum_attempts_per_dispatch > request.physical_cap:
        _stop_for_cap(
            policy=policy,
            pair_id=plan.pair_id,
            accounting=accounting,
            requested=request.maximum_attempts_per_dispatch,
        )
        return None
    _guard_pre_call_cap(
        accounting=accounting,
        active_reservations=0,
        requested_reservation=request.maximum_attempts_per_dispatch,
        physical_cap=request.physical_cap,
    )
    plan_identity = _typed_settlement_plan_identity(plan)
    plan_sha256 = _sha256_json(plan_identity)
    reconciliation_identity = _sha256_json(
        {
            "strict_policy_identity_hash": policy.identity_hash,
            "pair_id": plan.pair_id,
            "source_kind": source_kind,
            "source_wave_index": source_wave_index,
            "source_evidence_sha256": source_evidence_sha256,
            "plan_identity_sha256": plan_sha256,
            "reconciliation_ordinal": 1,
        }
    )
    relative = PurePosixPath("reconciliation-settlements") / reconciliation_identity[:24]
    root = _reconciliation_settlement_root(
        request.workspace,
        relative,
        create_parent=True,
    )
    if root.exists() or root.is_symlink():
        if root.is_symlink() or not root.is_dir() or any(root.iterdir()):
            raise ValueError("strict reconciliation settlement root is unsafe or non-empty")
    else:
        root.mkdir()
    _fsync_directory(root.parent)
    dispatch, created = policy.begin_reconciliation(
        pair_id=plan.pair_id,
        source_kind=source_kind,
        source_wave_index=source_wave_index,
        source_evidence_sha256=source_evidence_sha256,
        plan_identity_sha256=plan_sha256,
        reconciliation_identity_hash=reconciliation_identity,
        journal_relative_path=relative.as_posix(),
        charged_before_dispatch=accounting.charged,
    )
    if not created:
        return _recover_unresolved_reconciliation(
            request=request,
            policy=policy,
            dispatch=dispatch,
        )
    reconciliation = DurablePairSettlement(
        root,
        settlement_identity_hash=reconciliation_identity,
        maximum_attempts_per_dispatch=request.maximum_attempts_per_dispatch,
        max_concurrency=1,
    )
    wave = reconciliation.settle_wave(
        (
            DurablePairDispatch(
                pair_id=plan.pair_id,
                plan_identity=plan_identity,
                execute=lambda adapter: _execute_typed_pair(
                    plan=plan,
                    adapter=adapter,
                    provider_metadata=request.provider_contract,
                ),
            ),
        ),
        (adapter_supplier()[source_lane_id],),
        physical_reservation=request.maximum_attempts_per_dispatch,
    )
    outcome = wave.outcomes_by_pair_id[plan.pair_id]
    _validate_dispatch_accounting(outcome, request.maximum_attempts_per_dispatch)
    return _close_reconciliation_outcome(
        policy=policy,
        dispatch=dispatch,
        settlement=reconciliation,
        outcome=outcome,
    )


def _recover_unresolved_reconciliation(
    *,
    request: StrictFreshReplayRequest,
    policy: StrictPairPolicy,
    dispatch: _ReconciliationDispatch,
) -> DurablePairTerminal | None:
    root = _reconciliation_settlement_root(
        request.workspace,
        PurePosixPath(dispatch.journal_relative_path),
        create_parent=False,
    )
    if root.is_symlink() or not root.is_dir():
        policy.stop(
            status=StrictFreshReplayStatus.STRICT_STOP_PROVENANCE_UNKNOWN,
            pair_id=dispatch.pair_id,
            reason="reconciliation_dispatch_without_settlement",
            audit_sha256=_sha256_json(dispatch.__dict__),
        )
        return None
    reconciliation = DurablePairSettlement(
        root,
        settlement_identity_hash=dispatch.reconciliation_identity_hash,
        maximum_attempts_per_dispatch=request.maximum_attempts_per_dispatch,
        max_concurrency=1,
    )
    replay = reconciliation.replay(seal_inflight=True)
    if len(replay.waves) != 1 or dispatch.pair_id not in {
        outcome.pair_id for wave in replay.waves for outcome in wave.outcomes
    }:
        policy.stop(
            status=StrictFreshReplayStatus.STRICT_STOP_PROVENANCE_UNKNOWN,
            pair_id=dispatch.pair_id,
            reason="reconciliation_dispatch_without_settlement",
            audit_sha256=_sha256_json(dispatch.__dict__),
        )
        return None
    outcome = replay.waves[0].outcomes_by_pair_id[dispatch.pair_id]
    return _close_reconciliation_outcome(
        policy=policy,
        dispatch=dispatch,
        settlement=reconciliation,
        outcome=outcome,
    )


def _close_reconciliation_outcome(
    *,
    policy: StrictPairPolicy,
    dispatch: _ReconciliationDispatch,
    settlement: DurablePairSettlement,
    outcome: DurablePairOutcome,
) -> DurablePairTerminal | None:
    if outcome.kind is DurablePairOutcomeKind.IMPLEMENTATION_FAILED:
        policy.stop(
            status=StrictFreshReplayStatus.STRICT_STOP_IMPLEMENTATION_FAILED,
            pair_id=dispatch.pair_id,
            reason=_non_empty(outcome.error_category, "reconciliation implementation category"),
            audit_sha256=_digest(outcome.audit_sha256, "reconciliation implementation audit"),
        )
        return None
    if outcome.kind is DurablePairOutcomeKind.PROVENANCE_UNKNOWN:
        policy.stop(
            status=StrictFreshReplayStatus.STRICT_STOP_PROVENANCE_UNKNOWN,
            pair_id=dispatch.pair_id,
            reason="second_provenance_unknown",
            audit_sha256=_digest(outcome.audit_sha256, "second unknown audit"),
        )
        return None
    terminal = cast(DurablePairTerminal, outcome.terminal)
    if terminal.terminal_row.get("terminal_status") == "provider_failed":
        policy.stop(
            status=StrictFreshReplayStatus.STRICT_STOP_PROVIDER_FAILED,
            pair_id=dispatch.pair_id,
            reason="reconciliation_provider_failed",
            audit_sha256=_terminal_sha256(terminal),
        )
        return None
    if terminal.terminal_row.get("terminal_status") != "succeeded":
        raise ValueError("strict reconciliation terminal status is unsupported")
    replay = settlement.replay()
    accounting = _PhysicalAccounting(
        actual=replay.actual_physical_attempts,
        uncertain=replay.uncertain_physical_attempts,
    )
    policy.resolve(
        pair_id=dispatch.pair_id,
        reconciliation_identity_hash=dispatch.reconciliation_identity_hash,
        journal_sha256=_sha256_file(settlement.path),
        terminal_sha256=_terminal_sha256(terminal),
        accounting=accounting,
    )
    return terminal


def _load_resolved_terminal(
    policy: StrictPairPolicy,
    dispatch: _ReconciliationDispatch,
    resolution: _ReconciliationResolution,
) -> DurablePairTerminal:
    root = _reconciliation_settlement_root(
        policy.workspace,
        PurePosixPath(dispatch.journal_relative_path),
        create_parent=False,
    )
    journal_path = root / DURABLE_PAIR_SETTLEMENT_JOURNAL_FILE
    if (
        journal_path.is_symlink()
        or not journal_path.is_file()
        or _sha256_file(journal_path) != resolution.journal_sha256
    ):
        raise ValueError("resolved strict reconciliation journal bytes drifted")
    replay = DurablePairSettlement(
        root,
        settlement_identity_hash=dispatch.reconciliation_identity_hash,
        maximum_attempts_per_dispatch=policy.maximum_attempts_per_dispatch,
        max_concurrency=1,
    ).replay()
    if (
        len(replay.waves) != 1
        or replay.unknown_pair_ids
        or replay.implementation_failed_pair_ids
        or set(replay.terminal_results) != {dispatch.pair_id}
        or replay.actual_physical_attempts != resolution.actual_physical_attempts
        or replay.uncertain_physical_attempts != resolution.uncertain_physical_attempts
        or replay.physical_attempt_charge != resolution.physical_attempt_charge
    ):
        raise ValueError("resolved strict reconciliation outcome or accounting drifted")
    terminal = replay.terminal_results[dispatch.pair_id]
    if (
        terminal.terminal_row.get("terminal_status") != "succeeded"
        or _terminal_sha256(terminal) != resolution.terminal_sha256
    ):
        raise ValueError("resolved strict reconciliation terminal drifted")
    return terminal


def _register_final_results(
    kernel: _ConcurrentRuntimeKernel,
    plans: Sequence[_PairExecutionPlan],
    results: Mapping[str, DurablePairTerminal],
) -> None:
    for plan in plans:
        terminal = results[plan.pair_id]
        if terminal.terminal_row.get("terminal_status") != "succeeded":
            raise ValueError("strict barrier refuses a non-success final terminal")
        kernel.start_pair(plan)
        existing = kernel.terminal_evidence(plan, "primary")
        if existing is None:
            kernel.register_terminal(
                plan=plan,
                decision_variant="primary",
                terminal_row=terminal.terminal_row,
                variant_evidence=terminal.variant_evidence,
            )
        elif existing != (dict(terminal.terminal_row), dict(terminal.variant_evidence)):
            raise ValueError("strict replayed kernel terminal differs from durable final settlement")
        kernel.close_primary_pair(
            plan,
            _PrimaryOnlyConcurrentRuntimeConsumer._primary_result_row(
                plan, terminal.terminal_row
            ),
        )


def _physical_accounting(
    *,
    request: StrictFreshReplayRequest,
    policy: StrictPairPolicy,
    settlement: DurablePairSettlement,
    seal_inflight: bool,
) -> _PhysicalAccounting:
    main = settlement.replay(seal_inflight=seal_inflight)
    actual = main.actual_physical_attempts
    uncertain = main.uncertain_physical_attempts
    policy_replay = policy.replay()
    for pair_id, dispatch in policy_replay.dispatches.items():
        root = _reconciliation_settlement_root(
            request.workspace,
            PurePosixPath(dispatch.journal_relative_path),
            create_parent=False,
        )
        if root.is_symlink() or not root.is_dir():
            uncertain += request.maximum_attempts_per_dispatch
            continue
        reconciliation = DurablePairSettlement(
            root,
            settlement_identity_hash=dispatch.reconciliation_identity_hash,
            maximum_attempts_per_dispatch=request.maximum_attempts_per_dispatch,
            max_concurrency=1,
        ).replay(seal_inflight=seal_inflight)
        if not reconciliation.waves or not reconciliation.dispatched_pair_ids:
            uncertain += request.maximum_attempts_per_dispatch
            continue
        actual += reconciliation.actual_physical_attempts
        uncertain += reconciliation.uncertain_physical_attempts
        if (
            pair_id not in reconciliation.terminal_results
            and pair_id not in reconciliation.unknown_pair_ids
            and pair_id not in reconciliation.implementation_failed_pair_ids
        ):
            uncertain += request.maximum_attempts_per_dispatch
    return _PhysicalAccounting(actual=actual, uncertain=uncertain)


def _build_result(
    *,
    request: StrictFreshReplayRequest,
    identity_hash: str,
    policy: StrictPairPolicy,
    settlement: DurablePairSettlement,
    journal: ConcurrentExecutionJournal,
    state: _ConcurrentRuntimeKernelState,
) -> StrictFreshReplayResult:
    policy_replay = policy.replay()
    if policy_replay.terminal_event_type == "runtime_completed":
        status = StrictFreshReplayStatus.COMPLETE
        stop_pair_ids: tuple[str, ...] = ()
    elif policy_replay.terminal_event_type == "strict_stopped":
        payload = cast(Mapping[str, object], policy_replay.terminal_payload)
        status = StrictFreshReplayStatus(
            _non_empty(payload.get("status"), "strict result status")
        )
        stop_pair_ids = (_non_empty(payload.get("pair_id"), "strict stop pair_id"),)
    else:
        raise ValueError("strict result requires a persisted terminal policy event")
    main = settlement.replay(seal_inflight=True)
    accounting = _physical_accounting(
        request=request,
        policy=policy,
        settlement=settlement,
        seal_inflight=True,
    )
    final_terminals: dict[str, DurablePairTerminal] = {}
    for wave in main.waves:
        for outcome in wave.outcomes:
            if outcome.kind is not DurablePairOutcomeKind.TERMINAL:
                continue
            terminal = cast(DurablePairTerminal, outcome.terminal)
            if terminal.terminal_row.get("terminal_status") == "succeeded":
                final_terminals[outcome.pair_id] = terminal
            elif outcome.pair_id in policy_replay.resolutions:
                final_terminals[outcome.pair_id] = _load_resolved_terminal(
                    policy,
                    policy_replay.dispatches[outcome.pair_id],
                    policy_replay.resolutions[outcome.pair_id],
                )
        for pair_id in wave.unknown_pair_ids:
            resolution = policy_replay.resolutions.get(pair_id)
            if resolution is not None:
                final_terminals[pair_id] = _load_resolved_terminal(
                    policy,
                    policy_replay.dispatches[pair_id],
                    resolution,
                )
    replay_status = _mapping(journal._replay_runtime().get("status"), "runtime status")
    committed_batches = _non_negative_int(
        replay_status.get("committed_batch_count"), "committed batch count"
    )
    result = StrictFreshReplayResult(
        status=status,
        workspace_root=request.workspace,
        replay_identity_hash=identity_hash,
        committed_batch_count=committed_batches,
        logical_count=len(set(main.dispatched_pair_ids)),
        final_succeeded_terminal_count=len(final_terminals),
        reconciliation_dispatch_count=len(policy_replay.dispatches),
        settled_actual_attempts=accounting.actual,
        dispatched_without_settlement_uncertainty=accounting.uncertain,
        charged_physical_attempts=accounting.charged,
        active_physical_reservations=0,
        committed_feedback_user_ids=tuple(sorted(state.campaign_engaged_user_ids)),
        strict_stop_pair_ids=stop_pair_ids,
    )
    if result.charged_physical_attempts > request.physical_cap:
        raise ValueError("strict result exceeds the frozen physical cap")
    if status is StrictFreshReplayStatus.COMPLETE and (
        result.logical_count != request.logical_cap
        or result.final_succeeded_terminal_count != request.logical_cap
        or result.committed_batch_count != request.config.horizon
    ):
        raise ValueError("strict complete result does not close its logical or batch denominator")
    return result


def _validate_dispatch_accounting(
    outcome: DurablePairOutcome,
    maximum_attempts_per_dispatch: int,
) -> None:
    accounting = outcome.accounting
    if accounting.recovered_without_settlement:
        if (
            accounting.actual_physical_attempts != 0
            or accounting.uncertain_physical_attempts != maximum_attempts_per_dispatch
        ):
            raise ValueError("strict dispatch gap accounting is crossed")
        return
    if outcome.kind is not DurablePairOutcomeKind.IMPLEMENTATION_FAILED and not (
        1 <= accounting.actual_physical_attempts <= maximum_attempts_per_dispatch
    ):
        raise ValueError("strict Provider dispatch must account for one to three attempts")


def _guard_pre_call_cap(
    *,
    accounting: _PhysicalAccounting,
    active_reservations: int,
    requested_reservation: int,
    physical_cap: int,
) -> None:
    if (
        accounting.charged
        + active_reservations
        + requested_reservation
        > physical_cap
    ):
        raise ValueError("strict pre-call reservation exceeds the physical cap")


def _stop_for_cap(
    *,
    policy: StrictPairPolicy,
    pair_id: str,
    accounting: _PhysicalAccounting,
    requested: int,
) -> None:
    policy.stop(
        status=StrictFreshReplayStatus.STRICT_STOP_CAP,
        pair_id=pair_id,
        reason="physical_cap_insufficient",
        audit_sha256=_sha256_json(
            {
                "pair_id": pair_id,
                "charged_physical_attempts": accounting.charged,
                "active_reservations": 0,
                "requested_reservation": requested,
                "physical_cap": policy.physical_cap,
            }
        ),
    )


def _wave_index_for_pair(
    waves: Sequence[DurableWaveSettlement], pair_id: str
) -> int:
    for wave in waves:
        if pair_id in wave.canonical_pair_ids:
            return wave.wave_index
    raise ValueError("strict outcome is missing its source wave")


def _terminal_sha256(terminal: DurablePairTerminal) -> str:
    return _sha256_json(
        {
            "pair_id": terminal.pair_id,
            "terminal_row": terminal.terminal_row,
            "variant_evidence": terminal.variant_evidence,
        }
    )


def _reconciliation_settlement_root(
    workspace: Path,
    relative: PurePosixPath,
    *,
    create_parent: bool,
) -> Path:
    if (
        relative.is_absolute()
        or len(relative.parts) != 2
        or relative.parts[0] != "reconciliation-settlements"
        or re.fullmatch(r"[0-9a-f]{24}", relative.parts[1]) is None
    ):
        raise ValueError("strict reconciliation settlement path is unsafe")
    parent = workspace / "reconciliation-settlements"
    if parent.exists() or parent.is_symlink():
        if parent.is_symlink() or not parent.is_dir():
            raise ValueError("strict reconciliation settlement directory is unsafe")
    elif create_parent:
        parent.mkdir()
        _fsync_directory(workspace)
    return parent / relative.parts[1]


def _write_status(workspace: Path, result: StrictFreshReplayResult) -> None:
    payload = {
        "schema_version": _STRICT_STATUS_SCHEMA,
        "status": result.status.value,
        "workspace_root": str(result.workspace_root),
        "replay_identity_hash": result.replay_identity_hash,
        "committed_batch_count": result.committed_batch_count,
        "logical_count": result.logical_count,
        "final_succeeded_terminal_count": result.final_succeeded_terminal_count,
        "reconciliation_dispatch_count": result.reconciliation_dispatch_count,
        "settled_actual_attempts": result.settled_actual_attempts,
        "dispatched_without_settlement_uncertainty": (
            result.dispatched_without_settlement_uncertainty
        ),
        "charged_physical_attempts": result.charged_physical_attempts,
        "active_physical_reservations": result.active_physical_reservations,
        "committed_feedback_user_ids": list(result.committed_feedback_user_ids),
        "strict_stop_pair_ids": list(result.strict_stop_pair_ids),
        "production_deploy_eligible": False,
    }
    path = workspace / STRICT_FRESH_REPLAY_STATUS_FILE
    _replace_json(path, payload)


def _append_policy_event(
    path: Path,
    *,
    identity_hash: str,
    sequence: int,
    previous_checksum: str | None,
    event_type: str,
    payload: Mapping[str, object],
) -> None:
    body = {
        "schema_version": _STRICT_POLICY_LEDGER_SCHEMA,
        "sequence": sequence,
        "previous_checksum": previous_checksum,
        "policy_identity_hash": identity_hash,
        "event_type": event_type,
        "payload": dict(safe_data(payload)),
    }
    record = {**body, "checksum": _sha256_json(body)}
    encoded = _canonical_json(record) + "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        with os.fdopen(descriptor, "a", encoding="utf-8", closefd=False) as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)
    _fsync_directory(path.parent)


def _exclusive_write_json(path: Path, payload: Mapping[str, object]) -> None:
    encoded = (_canonical_json(payload) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)
    _fsync_directory(path.parent)


def _replace_json(path: Path, payload: Mapping[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    if temporary.exists() or temporary.is_symlink():
        temporary.unlink()
    _exclusive_write_json(temporary, payload)
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def _read_json(path: Path) -> dict[str, object]:
    return _mapping(json.loads(path.read_text(encoding="utf-8")), f"JSON artifact {path.name}")


def _mapping(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be a mapping")
    return {str(key): item for key, item in value.items()}


def _non_empty(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be a non-empty string")
    return value


def _digest(value: object, context: str) -> str:
    text = _non_empty(value, context)
    if _SHA256.fullmatch(text) is None:
        raise ValueError(f"{context} must be a lowercase SHA-256 digest")
    return text


def _non_negative_int(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{context} must be a non-negative int")
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(
        safe_data(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"strict replay artifact is missing or unsafe: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
