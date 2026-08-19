from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import cast

from ._concurrent_runtime_spool import _ConcurrentRuntimeBatchSpool
from .concurrent_execution_journal import (
    CONCURRENT_MESSAGE_EXECUTION_JOURNAL_JSONL,
    CONCURRENT_MESSAGE_EXECUTION_RUN_IDENTITY_JSON,
    CONCURRENT_MESSAGE_EXECUTION_SNAPSHOTS_DIR,
    CONCURRENT_MESSAGE_EXECUTION_STATUS_JSON,
    ConcurrentExecutionJournal,
    _build_primary_only_concurrent_execution_run_identity,
)
from .concurrent_message_experiment import (
    CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_DELIVERY_CAPACITY,
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
    DurableSettlementReplay,
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
STRICT_SOURCE_V4_DIR = "source-v4"
FULL_POOL_SOURCE_V4_SCHEMA = "full-pool-segmented-source-v4"

_STRICT_POLICY_SCHEMA = "full-pool-strict-pair-policy-v1"
_STRICT_POLICY_LEDGER_SCHEMA = "full-pool-strict-pair-policy-ledger-v1"
_STRICT_STATUS_SCHEMA = "full-pool-strict-fresh-replay-status-v2"
_STRICT_EXECUTION_SCHEMA = "full-pool-strict-fresh-replay-execution-v1"
_SOURCE_V4_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "source_identity",
        "replay_id",
        "profile",
        "production_topology",
        "counts",
        "provider_accounting",
        "physical_accounting",
        "operator_execution",
        "fresh_lineage",
        "runtime_lineage",
        "strict_policy",
        "settlement_v2",
        "row_hashes",
        "provider_contract_sha256",
        "source_hash",
        "production_deploy_eligible",
        "artifacts",
    }
)
_REPLAY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class StrictFreshReplayStatus(str, Enum):
    COMPLETE = "complete"
    STRICT_STOP_PROVIDER_FAILED = "strict_stop_provider_failed"
    STRICT_STOP_PROVENANCE_UNKNOWN = "strict_stop_provenance_unknown"
    STRICT_STOP_IMPLEMENTATION_FAILED = "strict_stop_implementation_failed"
    STRICT_STOP_CAP = "strict_stop_cap"


@dataclass(frozen=True)
class StrictRejectedHistoryReference:
    """Hash-bound rejected source-v3 lineage that can never supply runtime state."""

    source_root: Path
    manifest_sha256: str
    rejection_reason: str

    def __post_init__(self) -> None:
        root = self.source_root.expanduser().resolve(strict=True)
        if root.is_symlink() or not root.is_dir():
            raise ValueError("strict rejected history must be one real source directory")
        manifest = root / "manifest.json"
        if manifest.is_symlink() or not manifest.is_file():
            raise ValueError("strict rejected history manifest is missing or unsafe")
        digest = _digest(self.manifest_sha256, "rejected source-v3 manifest hash")
        if _sha256_file(manifest) != digest:
            raise ValueError("strict rejected history manifest differs from its frozen hash")
        if self.rejection_reason != "validation_mixed_provider_evidence":
            raise ValueError("strict rejected history reason is not the mixed-evidence rejection")
        object.__setattr__(self, "source_root", root)
        object.__setattr__(self, "manifest_sha256", digest)


@dataclass(frozen=True)
class StrictFreshOperatorExecutionReference:
    """Manifest and append-only attempt identity attached by the reentrant operator."""

    execution_manifest_path: Path
    execution_manifest_sha256: str
    execution_manifest_identity_sha256: str
    attempt_ledger_path: Path
    attempt_ledger_identity_sha256: str

    def __post_init__(self) -> None:
        manifest = self.execution_manifest_path.expanduser().absolute()
        ledger = self.attempt_ledger_path.expanduser().absolute()
        if manifest.is_symlink() or not manifest.is_file():
            raise ValueError("strict fresh execution manifest is missing or unsafe")
        if ledger.is_symlink() or not ledger.is_file():
            raise ValueError("strict fresh operator attempt ledger is missing or unsafe")
        manifest_sha256 = _digest(
            self.execution_manifest_sha256, "strict fresh execution manifest hash"
        )
        if _sha256_file(manifest) != manifest_sha256:
            raise ValueError("strict fresh execution manifest differs from its frozen hash")
        object.__setattr__(self, "execution_manifest_path", manifest)
        object.__setattr__(self, "execution_manifest_sha256", manifest_sha256)
        object.__setattr__(
            self,
            "execution_manifest_identity_sha256",
            _digest(
                self.execution_manifest_identity_sha256,
                "strict fresh execution manifest identity",
            ),
        )
        object.__setattr__(self, "attempt_ledger_path", ledger)
        object.__setattr__(
            self,
            "attempt_ledger_identity_sha256",
            _digest(self.attempt_ledger_identity_sha256, "strict fresh attempt ledger identity"),
        )


@dataclass(frozen=True)
class StrictFreshReplayRequest:
    """Frozen inputs for a fresh strict trajectory; no historical terminal can be imported."""

    config: ConcurrentMessageExperimentConfig
    workspace: Path
    replay_id: str
    provider_contract: Mapping[str, object]
    rejected_history: StrictRejectedHistoryReference
    seed_top_k_per_proxy: int
    logical_cap: int
    physical_cap: int = FULL_POOL_FORMAL_PHYSICAL_ATTEMPT_CAP
    maximum_attempts_per_dispatch: int = 3
    max_concurrency: int = 10
    operator_execution: StrictFreshOperatorExecutionReference | None = None

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
        rejected_root = self.rejected_history.source_root
        if (
            workspace == rejected_root
            or workspace.is_relative_to(rejected_root)
            or rejected_root.is_relative_to(workspace)
            or dataset == rejected_root
            or dataset.is_relative_to(rejected_root)
            or rejected_root.is_relative_to(dataset)
        ):
            raise ValueError("strict replay rejected history must remain read-only and independent")
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
        if self.operator_execution is not None:
            manifest = self.operator_execution.execution_manifest_path
            ledger = self.operator_execution.attempt_ledger_path
            if (
                manifest == workspace
                or manifest.is_relative_to(workspace)
                or workspace.is_relative_to(manifest)
                or ledger == workspace
                or ledger.is_relative_to(workspace)
                or ledger == dataset
                or ledger.is_relative_to(dataset)
                or ledger == rejected_root
                or ledger.is_relative_to(rejected_root)
            ):
                raise ValueError("strict operator evidence paths overlap protected runtime inputs")


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
    source_root: Path | None = None
    source_manifest_sha256: str | None = None
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


@dataclass
class _StrictSettlementProgress:
    waves: list[DurableWaveSettlement]
    outcomes: dict[str, DurablePairOutcome]
    wave_index_by_pair: dict[str, int]
    logical_count: int
    accounting: _PhysicalAccounting
    external_request_invocations: int


@dataclass(frozen=True)
class _StrictSourceV4Reference:
    root: Path
    manifest_sha256: str


@dataclass(frozen=True)
class _StrictSourceV4Evidence:
    counts: Mapping[str, int]
    provider_accounting: Mapping[str, object]
    row_hashes: Mapping[str, str]
    source_eligible: bool


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
        _validate_rejected_history_reference(request.rejected_history)
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
            main_replay = settlement.replay(seal_inflight=True)
            progress = _strict_settlement_progress(
                request=request,
                policy=policy,
                main=main_replay,
            )
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
                return _finalize_strict_result(
                    request=request,
                    identity_hash=cast(str, identity["identity_hash"]),
                    sample_user_ids=prepared.cohort.sample_user_ids,
                    policy=policy,
                    settlement=settlement,
                    progress=progress,
                    journal=journal,
                    state=state,
                )

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
                    progress=progress,
                    adapters=lanes,
                )
                if final_results is None:
                    return _finalize_strict_result(
                        request=request,
                        identity_hash=cast(str, identity["identity_hash"]),
                        sample_user_ids=prepared.cohort.sample_user_ids,
                        policy=policy,
                        settlement=settlement,
                        progress=progress,
                        journal=journal,
                        state=state,
                    )
                _register_final_results(kernel, pending, final_results)
                kernel.commit_primary_batch()

            accounting = progress.accounting
            policy.complete(
                logical_count=progress.logical_count,
                committed_batch_count=state.next_time_step,
                charged_physical_attempts=accounting.charged,
            )
            return _finalize_strict_result(
                request=request,
                identity_hash=cast(str, identity["identity_hash"]),
                sample_user_ids=prepared.cohort.sample_user_ids,
                policy=policy,
                settlement=settlement,
                progress=progress,
                journal=journal,
                state=state,
            )
        finally:
            journal.close()


def _finalize_strict_result(
    *,
    request: StrictFreshReplayRequest,
    identity_hash: str,
    sample_user_ids: Sequence[str],
    policy: StrictPairPolicy,
    settlement: DurablePairSettlement,
    progress: _StrictSettlementProgress,
    journal: ConcurrentExecutionJournal,
    state: _ConcurrentRuntimeKernelState,
) -> StrictFreshReplayResult:
    result = _build_result(
        request=request,
        identity_hash=identity_hash,
        policy=policy,
        progress=progress,
        journal=journal,
        state=state,
    )
    source = request.workspace / STRICT_SOURCE_V4_DIR
    staging = request.workspace / ".source-v4.staging"
    if result.status is StrictFreshReplayStatus.COMPLETE:
        source_ref = _close_or_validate_source_v4(
            request=request,
            identity_hash=identity_hash,
            sample_user_ids=sample_user_ids,
            result=result,
            policy=policy,
            settlement=settlement,
            progress=progress,
            journal=journal,
        )
        if source_ref is not None:
            source_manifest = _read_json(source_ref.root / "manifest.json")
            result = replace(
                result,
                source_root=source_ref.root,
                source_manifest_sha256=source_ref.manifest_sha256,
                production_deploy_eligible=(
                    source_manifest.get("production_deploy_eligible") is True
                ),
            )
    elif any(path.exists() or path.is_symlink() for path in (source, staging)):
        raise ValueError("strict-stopped replay cannot expose source-v4 bytes")
    _write_status(request.workspace, result)
    return result


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


def _operator_execution_payload(
    reference: StrictFreshOperatorExecutionReference | None,
) -> dict[str, object] | None:
    if reference is None:
        return None
    if (
        reference.execution_manifest_path.is_symlink()
        or not reference.execution_manifest_path.is_file()
        or _sha256_file(reference.execution_manifest_path)
        != reference.execution_manifest_sha256
        or reference.attempt_ledger_path.is_symlink()
        or not reference.attempt_ledger_path.is_file()
    ):
        raise ValueError("strict fresh operator execution evidence changed or is unsafe")
    return {
        "execution_manifest_path": str(reference.execution_manifest_path),
        "execution_manifest_sha256": reference.execution_manifest_sha256,
        "execution_manifest_identity_sha256": (
            reference.execution_manifest_identity_sha256
        ),
        "attempt_ledger_path": str(reference.attempt_ledger_path),
        "attempt_ledger_identity_sha256": reference.attempt_ledger_identity_sha256,
    }


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
        output_target=request.workspace / STRICT_SOURCE_V4_DIR,
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
            "operator_execution": _operator_execution_payload(request.operator_execution),
            "seed_top_k_per_proxy": request.seed_top_k_per_proxy,
            "logical_cap": request.logical_cap,
            "physical_cap": request.physical_cap,
            "maximum_attempts_per_dispatch": request.maximum_attempts_per_dispatch,
            "max_concurrency": request.max_concurrency,
            "fresh_no_cache": True,
            "maximum_reconciliations_per_pair": 1,
            "fresh_initial_positions": {
                "batch": 0,
                "logical": 0,
                "physical": 0,
                "pair_schedule": 0,
            },
            "rejected_history": {
                "source_root": str(request.rejected_history.source_root),
                "manifest_sha256": request.rejected_history.manifest_sha256,
                "rejection_reason": request.rejected_history.rejection_reason,
            },
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
    fresh_claim = metadata.get("fresh_no_cache")
    production_live_fresh = (
        fresh_claim is None
        and metadata.get("enabled") is True
        and metadata.get("require_live_env") is True
        and metadata.get("adapter") == "openai_compatible"
    )
    if (
        actual_transport != expected.get("provider_transport")
        or actual_identity != expected.get("adapter_identity")
        or actual_model != expected.get("requested_model")
        or metadata.get("prompt_version", getattr(adapter, "prompt_version", None))
        != expected.get("prompt_version")
        or metadata.get("max_retries") != 2
        or not (fresh_claim is True or production_live_fresh)
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
    progress: _StrictSettlementProgress,
    adapters: Callable[[], Sequence[LLMDecisionAdapter]],
) -> dict[str, DurablePairTerminal] | None:
    if policy.replay().terminal_event_type is not None:
        return None
    plan_by_id = {plan.pair_id: plan for plan in plans}
    results: dict[str, DurablePairTerminal] = {}
    outcomes = progress.outcomes
    wave_index_by_pair = progress.wave_index_by_pair
    logical_count = progress.logical_count
    accounting = progress.accounting
    cursor = 0
    while cursor < len(plans):
        plan = plans[cursor]
        outcome = outcomes.get(plan.pair_id)
        if outcome is not None:
            provisional = (
                outcome.kind is not DurablePairOutcomeKind.TERMINAL
                or cast(DurablePairTerminal, outcome.terminal).terminal_row.get(
                    "terminal_status"
                )
                != "succeeded"
            )
            terminal = _finalize_original_outcome(
                request=request,
                plan=plan,
                outcome=outcome,
                source_wave_index=wave_index_by_pair[plan.pair_id],
                policy=policy,
                settlement=settlement,
                adapter_supplier=adapters,
            )
            if provisional:
                accounting = _physical_accounting(
                    request=request,
                    policy=policy,
                    settlement=settlement,
                    seal_inflight=False,
                )
                progress.accounting = accounting
                progress.external_request_invocations = (
                    _external_request_invocations_from_outcomes(
                        request=request,
                        policy=policy,
                        outcomes=progress.outcomes,
                    )
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
        wave_plans = missing[: request.max_concurrency]
        if not wave_plans:
            raise ValueError("strict batch has an empty nonterminal wave")
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
        progress.waves.append(wave)
        logical_count += len(wave.dispatched_pair_ids)
        progress.logical_count = logical_count
        accounting = _PhysicalAccounting(
            actual=accounting.actual + wave.actual_physical_attempts,
            uncertain=accounting.uncertain + wave.uncertain_physical_attempts,
        )
        progress.accounting = accounting
        progress.external_request_invocations += sum(
            captured.accounting.external_request_invocations_delta
            for captured in wave.outcomes
        )
        for captured in wave.outcomes:
            _validate_dispatch_accounting(captured, request.maximum_attempts_per_dispatch)
            outcomes[captured.pair_id] = captured
            wave_index_by_pair[captured.pair_id] = wave.wave_index

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


def _strict_settlement_progress(
    *,
    request: StrictFreshReplayRequest,
    policy: StrictPairPolicy,
    main: DurableSettlementReplay,
) -> _StrictSettlementProgress:
    waves = list(main.waves)
    return _StrictSettlementProgress(
        waves=waves,
        outcomes={
            outcome.pair_id: outcome
            for wave in waves
            for outcome in wave.outcomes
        },
        wave_index_by_pair={
            pair_id: wave.wave_index
            for wave in waves
            for pair_id in wave.canonical_pair_ids
        },
        logical_count=len(main.dispatched_pair_ids),
        accounting=_physical_accounting_from_main(
            request=request,
            policy=policy,
            main=main,
            seal_inflight=True,
        ),
        external_request_invocations=_external_request_invocations_from_outcomes(
            request=request,
            policy=policy,
            outcomes={
                outcome.pair_id: outcome
                for wave in waves
                for outcome in wave.outcomes
            },
        ),
    )


def _external_request_invocations_from_outcomes(
    *,
    request: StrictFreshReplayRequest,
    policy: StrictPairPolicy,
    outcomes: Mapping[str, DurablePairOutcome],
) -> int:
    external = sum(
        outcome.accounting.external_request_invocations_delta
        for outcome in outcomes.values()
    )
    for dispatch in policy.replay().dispatches.values():
        root = _reconciliation_settlement_root(
            request.workspace,
            PurePosixPath(dispatch.journal_relative_path),
            create_parent=False,
        )
        if root.is_symlink() or not root.is_dir():
            continue
        replay = DurablePairSettlement(
            root,
            settlement_identity_hash=dispatch.reconciliation_identity_hash,
            maximum_attempts_per_dispatch=request.maximum_attempts_per_dispatch,
            max_concurrency=1,
        ).replay(seal_inflight=True)
        external += sum(
            outcome.accounting.external_request_invocations_delta
            for wave in replay.waves
            for outcome in wave.outcomes
        )
    return external


def _physical_accounting(
    *,
    request: StrictFreshReplayRequest,
    policy: StrictPairPolicy,
    settlement: DurablePairSettlement,
    seal_inflight: bool,
) -> _PhysicalAccounting:
    return _physical_accounting_from_main(
        request=request,
        policy=policy,
        main=settlement.replay(seal_inflight=seal_inflight),
        seal_inflight=seal_inflight,
    )


def _physical_accounting_from_main(
    *,
    request: StrictFreshReplayRequest,
    policy: StrictPairPolicy,
    main: DurableSettlementReplay,
    seal_inflight: bool,
) -> _PhysicalAccounting:
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


def _final_succeeded_terminals_from_outcomes(
    *,
    policy: StrictPairPolicy,
    outcomes: Mapping[str, DurablePairOutcome],
) -> dict[str, DurablePairTerminal]:
    policy_replay = policy.replay()
    final_terminals: dict[str, DurablePairTerminal] = {}
    for pair_id, outcome in outcomes.items():
        if outcome.kind is DurablePairOutcomeKind.TERMINAL:
            terminal = cast(DurablePairTerminal, outcome.terminal)
            if terminal.terminal_row.get("terminal_status") == "succeeded":
                final_terminals[pair_id] = terminal
                continue
        resolution = policy_replay.resolutions.get(pair_id)
        if resolution is not None:
            final_terminals[pair_id] = _load_resolved_terminal(
                policy,
                policy_replay.dispatches[pair_id],
                resolution,
            )
    return final_terminals


def _build_result(
    *,
    request: StrictFreshReplayRequest,
    identity_hash: str,
    policy: StrictPairPolicy,
    progress: _StrictSettlementProgress,
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
    accounting = progress.accounting
    final_terminals = _final_succeeded_terminals_from_outcomes(
        policy=policy,
        outcomes=progress.outcomes,
    )
    committed_batches = journal.committed_batch_count
    if committed_batches != state.next_time_step:
        raise ValueError("strict runtime state is crossed with durable batch commits")
    result = StrictFreshReplayResult(
        status=status,
        workspace_root=request.workspace,
        replay_identity_hash=identity_hash,
        committed_batch_count=committed_batches,
        logical_count=progress.logical_count,
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
    if status is StrictFreshReplayStatus.COMPLETE:
        completion = _mapping(policy_replay.terminal_payload, "strict completion payload")
        if completion != {
            "logical_count": result.logical_count,
            "committed_batch_count": result.committed_batch_count,
            "charged_physical_attempts": result.charged_physical_attempts,
        }:
            raise ValueError("strict completion event is crossed with persisted runtime facts")
    if status is StrictFreshReplayStatus.COMPLETE and (
        result.logical_count != request.logical_cap
        or result.final_succeeded_terminal_count != request.logical_cap
        or result.committed_batch_count != request.config.horizon
    ):
        raise ValueError("strict complete result does not close its logical or batch denominator")
    return result


def _validate_rejected_history_reference(
    reference: StrictRejectedHistoryReference,
) -> None:
    root = reference.source_root
    manifest = root / "manifest.json"
    if (
        root.is_symlink()
        or not root.is_dir()
        or manifest.is_symlink()
        or not manifest.is_file()
        or _sha256_file(manifest) != reference.manifest_sha256
    ):
        raise ValueError("strict rejected source-v3 lineage changed after it was frozen")


def _close_or_validate_source_v4(
    *,
    request: StrictFreshReplayRequest,
    identity_hash: str,
    sample_user_ids: Sequence[str],
    result: StrictFreshReplayResult,
    policy: StrictPairPolicy,
    settlement: DurablePairSettlement,
    progress: _StrictSettlementProgress,
    journal: ConcurrentExecutionJournal,
) -> _StrictSourceV4Reference | None:
    final_terminals = _final_succeeded_terminals_from_outcomes(
        policy=policy,
        outcomes=progress.outcomes,
    )
    runtime_replay = journal._replay_runtime()
    evidence = _scan_source_v4_evidence(
        request=request,
        journal=journal,
        runtime_replay=runtime_replay,
        sample_user_ids=sample_user_ids,
        final_terminals=final_terminals,
        external_request_invocations=progress.external_request_invocations,
    )
    source = request.workspace / STRICT_SOURCE_V4_DIR
    staging = request.workspace / ".source-v4.staging"
    if source.exists() or source.is_symlink():
        if staging.exists() or staging.is_symlink():
            raise ValueError("source-v4 and its staging directory cannot coexist")
        if not evidence.source_eligible:
            raise ValueError("persisted source-v4 exists without complete final response evidence")
        manifest_sha256 = _sha256_file(source / "manifest.json")
        _validate_source_v4(
            source=source,
            manifest_sha256=manifest_sha256,
            request=request,
            identity_hash=identity_hash,
            sample_user_ids=sample_user_ids,
            result=result,
            policy=policy,
            settlement=settlement,
            progress=progress,
            journal=journal,
            evidence=evidence,
        )
        return _StrictSourceV4Reference(source, manifest_sha256)

    _discard_source_v4_staging(staging, request.workspace)
    if not evidence.source_eligible:
        return None

    staging.mkdir()
    _fsync_directory(request.workspace)
    try:
        _write_source_v4_rows(staging, journal, runtime_replay=runtime_replay)
        for relative, expected_hash in evidence.row_hashes.items():
            if _sha256_file(staging / relative) != expected_hash:
                raise ValueError("source-v4 row projection differs from committed runtime spool")

        workspace_artifacts, reconciliation_entries = _source_v4_workspace_artifacts(
            request=request,
            policy=policy,
            settlement=settlement,
            journal=journal,
        )
        for relative, origin in workspace_artifacts.items():
            _copy_file_durable(origin, staging / relative)

        membership = _source_v4_membership_bytes(
            request.config.dataset_dir,
            sample_user_ids=sample_user_ids,
        )
        _write_bytes_durable(staging / "latent-membership.csv", membership)
        _exclusive_write_json(staging / "fresh-request.json", _source_v4_request_payload(request))
        _exclusive_write_json(staging / "schema.json", _source_v4_schema_payload())

        artifacts = _source_v4_artifact_refs(staging)
        manifest = _source_v4_expected_manifest(
            request=request,
            identity_hash=identity_hash,
            result=result,
            progress=progress,
            evidence=evidence,
            artifacts=artifacts,
            reconciliation_entries=reconciliation_entries,
        )
        _exclusive_write_json(staging / "manifest.json", manifest)
        manifest_sha256 = _sha256_file(staging / "manifest.json")
        _validate_source_v4(
            source=staging,
            manifest_sha256=manifest_sha256,
            request=request,
            identity_hash=identity_hash,
            sample_user_ids=sample_user_ids,
            result=result,
            policy=policy,
            settlement=settlement,
            progress=progress,
            journal=journal,
            evidence=evidence,
        )
        os.replace(staging, source)
        _fsync_directory(request.workspace)
        _validate_source_v4(
            source=source,
            manifest_sha256=manifest_sha256,
            request=request,
            identity_hash=identity_hash,
            sample_user_ids=sample_user_ids,
            result=result,
            policy=policy,
            settlement=settlement,
            progress=progress,
            journal=journal,
            evidence=evidence,
        )
        return _StrictSourceV4Reference(source, manifest_sha256)
    except Exception:
        if staging.exists() and not staging.is_symlink() and staging.is_dir():
            shutil.rmtree(staging)
            _fsync_directory(request.workspace)
        raise


def _scan_source_v4_evidence(
    *,
    request: StrictFreshReplayRequest,
    journal: ConcurrentExecutionJournal,
    runtime_replay: Mapping[str, object],
    sample_user_ids: Sequence[str],
    final_terminals: Mapping[str, DurablePairTerminal],
    external_request_invocations: int,
) -> _StrictSourceV4Evidence:
    spool = _ConcurrentRuntimeBatchSpool(
        request.workspace,
        run_id=journal.run_id,
        identity_hash=journal.identity_hash,
        terminal_variants=("primary",),
    )
    row_hashers = {
        name: hashlib.sha256()
        for name in (
            "candidate_rows.jsonl",
            "pair_rows.jsonl",
            "terminal_rows.jsonl",
            "variant_evidence_rows.jsonl",
            "steps.jsonl",
        )
    }
    counts = Counter[str]()
    pair_ids: set[str] = set()
    user_message_pairs: set[tuple[str, str]] = set()
    distinct_users: set[str] = set()
    message_ids = {message.message_id for message in request.config.messages}
    coverage: Counter[str] = Counter()
    observed_models: Counter[str] = Counter()
    request_invocations = 0
    provider_responses = 0
    successful_decisions = 0
    observed_missing = 0
    observed_malformed = 0
    usage_complete = 0
    usage_missing = 0
    usage_malformed = 0
    input_usage = 0
    output_usage = 0
    total_usage = 0
    cached_input_usage = 0
    cached_reported_response_count = 0

    for expected_time_step, chunk in enumerate(spool.iter_committed(runtime_replay)):
        if chunk.time_step != expected_time_step:
            raise ValueError("source-v4 committed batches are missing or reordered")
        counts["committed_batches"] += 1
        rows_by_file = {
            "candidate_rows.jsonl": chunk.candidate_rows,
            "pair_rows.jsonl": chunk.result_rows,
            "terminal_rows.jsonl": chunk.terminal_rows,
            "variant_evidence_rows.jsonl": chunk.variant_evidence_rows,
            "steps.jsonl": [chunk.commit],
        }
        for relative, rows in rows_by_file.items():
            for row in rows:
                row_hashers[relative].update((_canonical_json(row) + "\n").encode("utf-8"))

        counts["candidate_rows"] += len(chunk.candidate_rows)
        counts["pair_rows"] += len(chunk.result_rows)
        counts["terminal_rows"] += len(chunk.terminal_rows)
        counts["variant_evidence_rows"] += len(chunk.variant_evidence_rows)
        result_ids = tuple(
            _non_empty(row.get("pair_id"), "source-v4 result pair_id")
            for row in chunk.result_rows
        )
        terminal_ids = tuple(
            _non_empty(row.get("pair_id"), "source-v4 terminal pair_id")
            for row in chunk.terminal_rows
        )
        evidence_ids = tuple(
            _non_empty(row.get("pair_id"), "source-v4 evidence pair_id")
            for row in chunk.variant_evidence_rows
        )
        if result_ids != terminal_ids or result_ids != evidence_ids:
            raise ValueError("source-v4 pair, terminal, and evidence order is crossed")
        selected_rows = [
            row for row in chunk.candidate_rows if _true_cell(row.get("selected"))
        ]
        selected_ids = {
            f"{_non_empty(row.get('user_id'), 'selected user_id')}:"
            f"{_non_empty(row.get('message_id'), 'selected message_id')}:"
            f"{_non_negative_int(row.get('time_step'), 'selected time_step')}"
            for row in selected_rows
        }
        remaining_per_message = max(
            request.config.sample_size
            - expected_time_step * request.config.delivery_capacity,
            0,
        )
        expected_selected_per_message = min(
            request.config.delivery_capacity,
            remaining_per_message,
        )
        if (
            len(chunk.candidate_rows) != remaining_per_message * len(message_ids)
            or len(result_ids) != expected_selected_per_message * len(message_ids)
            or len(selected_rows) != len(result_ids)
            or selected_ids != set(result_ids)
        ):
            raise ValueError("source-v4 selected candidate frontier differs from committed pairs")

        for result_row, terminal_row, evidence_row in zip(
            chunk.result_rows,
            chunk.terminal_rows,
            chunk.variant_evidence_rows,
            strict=True,
        ):
            pair_id = _non_empty(terminal_row.get("pair_id"), "source-v4 pair_id")
            user_id = _non_empty(terminal_row.get("user_id"), "source-v4 user_id")
            message_id = _non_empty(terminal_row.get("message_id"), "source-v4 message_id")
            terminal = final_terminals.get(pair_id)
            if (
                pair_id in pair_ids
                or message_id not in message_ids
                or (user_id, message_id) in user_message_pairs
                or terminal is None
                or dict(terminal.terminal_row) != dict(terminal_row)
                or dict(terminal.variant_evidence) != dict(evidence_row)
                or result_row.get("primary_status") != "succeeded"
                or terminal_row.get("terminal_status") != "succeeded"
                or terminal_row.get("provider_status") != "succeeded"
            ):
                raise ValueError("source-v4 final succeeded terminal mapping is crossed")
            pair_ids.add(pair_id)
            user_message_pairs.add((user_id, message_id))
            distinct_users.add(user_id)
            coverage[user_id] += 1

            invocations = _non_negative_int(
                evidence_row.get("request_invocations"), "source-v4 request invocations"
            )
            responses = _non_negative_int(
                evidence_row.get("provider_response_count"), "source-v4 provider responses"
            )
            successes = _non_negative_int(
                evidence_row.get("successful_decision_count"), "source-v4 successful decisions"
            )
            if not invocations >= responses >= successes:
                raise ValueError("source-v4 final response accounting invariant failed")
            request_invocations += invocations
            provider_responses += responses
            successful_decisions += successes
            for model, count in _mapping(
                evidence_row.get("observed_model_counts"), "source-v4 observed models"
            ).items():
                observed_models[model] += _non_negative_int(count, "source-v4 model count")
            observed_missing += _non_negative_int(
                evidence_row.get("observed_model_missing_response_count"),
                "source-v4 missing model count",
            )
            observed_malformed += _non_negative_int(
                evidence_row.get("observed_model_malformed_response_count"),
                "source-v4 malformed model count",
            )
            usage_complete += _non_negative_int(
                evidence_row.get("usage_complete_response_count"),
                "source-v4 complete usage count",
            )
            usage_missing += _non_negative_int(
                evidence_row.get("usage_missing_response_count"),
                "source-v4 missing usage count",
            )
            usage_malformed += _non_negative_int(
                evidence_row.get("usage_malformed_response_count"),
                "source-v4 malformed usage count",
            )
            input_value = evidence_row.get("input_usage")
            output_value = evidence_row.get("output_usage")
            total_value = evidence_row.get("total_usage")
            if input_value is not None or output_value is not None or total_value is not None:
                input_tokens = _non_negative_int(input_value, "source-v4 input usage")
                output_tokens = _non_negative_int(output_value, "source-v4 output usage")
                total_tokens = _non_negative_int(total_value, "source-v4 total usage")
                if total_tokens != input_tokens + output_tokens:
                    raise ValueError("source-v4 token usage total is crossed")
                input_usage += input_tokens
                output_usage += output_tokens
                total_usage += total_tokens
            cached_value = evidence_row.get("cached_input_usage")
            if cached_value is not None:
                cached_input_usage += _non_negative_int(
                    cached_value, "source-v4 cached input usage"
                )
                cached_reported_response_count += responses

    expected_messages = len(message_ids)
    expected_candidates = expected_messages * sum(
        max(
            request.config.sample_size
            - time_step * request.config.delivery_capacity,
            0,
        )
        for time_step in range(request.config.horizon)
    )
    if (
        counts["committed_batches"] != request.config.horizon
        or counts["candidate_rows"] != expected_candidates
        or len(pair_ids) != request.logical_cap
        or set(pair_ids) != set(final_terminals)
        or distinct_users != set(sample_user_ids)
        or len(distinct_users) != request.config.sample_size
        or set(coverage.values()) != {expected_messages}
    ):
        raise ValueError("source-v4 fresh user, pair, or batch denominator is incomplete")
    counts["distinct_users"] = len(distinct_users)
    expected_model = _non_empty(
        request.provider_contract.get("requested_model"), "source-v4 requested model"
    )
    source_eligible = (
        request_invocations >= request.logical_cap
        and provider_responses == request.logical_cap
        and successful_decisions == request.logical_cap
        and dict(observed_models) == {expected_model: request.logical_cap}
        and observed_missing == 0
        and observed_malformed == 0
        and usage_complete == request.logical_cap
        and usage_missing == 0
        and usage_malformed == 0
    )
    provider_accounting = {
        "schema_version": "provider-accounting-v1",
        "external_request_invocations": external_request_invocations,
        "provider_response_count": provider_responses,
        "successful_decision_count": successful_decisions,
        "observed_model_counts": dict(sorted(observed_models.items())),
        "observed_model_missing_response_count": observed_missing,
        "observed_model_malformed_response_count": observed_malformed,
        "usage_complete_response_count": usage_complete,
        "usage_missing_response_count": usage_missing,
        "usage_malformed_response_count": usage_malformed,
        "input_tokens": input_usage if usage_complete else None,
        "output_tokens": output_usage if usage_complete else None,
        "total_tokens": total_usage if usage_complete else None,
        "cached_input_tokens": (
            cached_input_usage if cached_reported_response_count else None
        ),
        "cached_input_tokens_reported_response_count": cached_reported_response_count,
    }
    return _StrictSourceV4Evidence(
        counts={
            key: counts[key]
            for key in (
                "candidate_rows",
                "committed_batches",
                "distinct_users",
                "pair_rows",
                "terminal_rows",
                "variant_evidence_rows",
            )
        },
        provider_accounting=provider_accounting,
        row_hashes={name: digest.hexdigest() for name, digest in row_hashers.items()},
        source_eligible=source_eligible,
    )


def _write_source_v4_rows(
    source: Path,
    journal: ConcurrentExecutionJournal,
    *,
    runtime_replay: Mapping[str, object],
) -> None:
    spool = _ConcurrentRuntimeBatchSpool(
        journal.workspace_dir,
        run_id=journal.run_id,
        identity_hash=journal.identity_hash,
        terminal_variants=("primary",),
    )
    handles = {
        name: (source / name).open("x", encoding="utf-8", newline="\n")
        for name in (
            "candidate_rows.jsonl",
            "pair_rows.jsonl",
            "terminal_rows.jsonl",
            "variant_evidence_rows.jsonl",
            "steps.jsonl",
        )
    }
    try:
        for chunk in spool.iter_committed(runtime_replay):
            rows_by_file = {
                "candidate_rows.jsonl": chunk.candidate_rows,
                "pair_rows.jsonl": chunk.result_rows,
                "terminal_rows.jsonl": chunk.terminal_rows,
                "variant_evidence_rows.jsonl": chunk.variant_evidence_rows,
                "steps.jsonl": [chunk.commit],
            }
            for relative, rows in rows_by_file.items():
                for row in rows:
                    handles[relative].write(_canonical_json(row) + "\n")
        for handle in handles.values():
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        for handle in handles.values():
            handle.close()
    _fsync_directory(source)


def _source_v4_workspace_artifacts(
    *,
    request: StrictFreshReplayRequest,
    policy: StrictPairPolicy,
    settlement: DurablePairSettlement,
    journal: ConcurrentExecutionJournal,
) -> tuple[dict[str, Path], list[dict[str, object]]]:
    _validate_rejected_history_reference(request.rejected_history)
    artifacts = {
        "runtime/fresh-run-identity.json": request.workspace
        / CONCURRENT_MESSAGE_EXECUTION_RUN_IDENTITY_JSON,
        "runtime/execution-journal.jsonl": request.workspace
        / CONCURRENT_MESSAGE_EXECUTION_JOURNAL_JSONL,
        "runtime/execution-status.json": request.workspace
        / CONCURRENT_MESSAGE_EXECUTION_STATUS_JSON,
        "strict/strict-pair-policy.json": policy.path,
        "strict/strict-pair-policy-ledger.jsonl": policy.ledger_path,
        "settlement/original/durable-pair-settlement-v2.jsonl": settlement.path,
        "rejected-history/source-v3-manifest.json": request.rejected_history.source_root
        / "manifest.json",
    }
    if request.operator_execution is not None:
        artifacts["operator/execution-manifest.json"] = (
            request.operator_execution.execution_manifest_path
        )
    snapshot_root = request.workspace / CONCURRENT_MESSAGE_EXECUTION_SNAPSHOTS_DIR
    if snapshot_root.is_symlink() or not snapshot_root.is_dir():
        raise ValueError("source-v4 runtime snapshot directory is missing or unsafe")
    for snapshot in sorted(snapshot_root.iterdir(), key=lambda path: path.name):
        if snapshot.is_symlink() or not snapshot.is_file():
            raise ValueError("source-v4 runtime snapshot inventory is unsafe")
        artifacts[f"runtime/snapshots/{snapshot.name}"] = snapshot

    reconciliation_entries: list[dict[str, object]] = []
    policy_replay = policy.replay()
    for pair_id, dispatch in sorted(policy_replay.dispatches.items()):
        resolution = policy_replay.resolutions.get(pair_id)
        if resolution is None:
            raise ValueError("complete source-v4 has an unresolved reconciliation dispatch")
        root = _reconciliation_settlement_root(
            request.workspace,
            PurePosixPath(dispatch.journal_relative_path),
            create_parent=False,
        )
        journal_path = root / DURABLE_PAIR_SETTLEMENT_JOURNAL_FILE
        relative = (
            Path("settlement/reconciliations")
            / dispatch.reconciliation_identity_hash
            / "durable-pair-settlement-v2.jsonl"
        ).as_posix()
        if _sha256_file(journal_path) != resolution.journal_sha256:
            raise ValueError("source-v4 reconciliation journal differs from policy closure")
        artifacts[relative] = journal_path
        reconciliation_entries.append(
            {
                "pair_id": pair_id,
                "source_kind": dispatch.source_kind,
                "reconciliation_identity_hash": dispatch.reconciliation_identity_hash,
                "relative_path": relative,
                "journal_sha256": resolution.journal_sha256,
                "terminal_sha256": resolution.terminal_sha256,
                "actual_physical_attempts": resolution.actual_physical_attempts,
                "uncertain_physical_attempts": resolution.uncertain_physical_attempts,
                "physical_attempt_charge": resolution.physical_attempt_charge,
            }
        )
    for origin in artifacts.values():
        _sha256_file(origin)
    return artifacts, reconciliation_entries


def _source_v4_membership_bytes(
    dataset_dir: Path,
    *,
    sample_user_ids: Sequence[str],
) -> bytes:
    source = dataset_dir / "users.csv"
    if source.is_symlink() or not source.is_file():
        raise ValueError("source-v4 latent membership origin is missing or unsafe")
    expected = set(sample_user_ids)
    membership: dict[str, str] = {}
    with source.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or not {"user_id", "latent_class"}.issubset(
            reader.fieldnames
        ):
            raise ValueError("source-v4 latent membership columns are incomplete")
        for row in reader:
            user_id = row.get("user_id", "")
            if user_id not in expected:
                continue
            latent_class = row.get("latent_class", "")
            if user_id in membership or latent_class not in {
                "class_1",
                "class_2",
                "class_3",
            }:
                raise ValueError("source-v4 latent membership is invalid or duplicated")
            membership[user_id] = latent_class
    if set(membership) != expected:
        raise ValueError("source-v4 latent membership differs from the fresh user set")
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("user_id", "latent_class"))
    for user_id in sorted(expected):
        writer.writerow((user_id, membership[user_id]))
    return output.getvalue().encode("utf-8")


def _source_v4_request_payload(request: StrictFreshReplayRequest) -> dict[str, object]:
    return {
        "schema_version": "full-pool-strict-fresh-request-v1",
        "replay_id": request.replay_id,
        "workspace": str(request.workspace),
        "dataset_dir": str(request.config.dataset_dir.resolve()),
        "seed_top_k_per_proxy": request.seed_top_k_per_proxy,
        "logical_cap": request.logical_cap,
        "physical_cap": request.physical_cap,
        "maximum_attempts_per_dispatch": request.maximum_attempts_per_dispatch,
        "max_concurrency": request.max_concurrency,
        "provider_contract": dict(request.provider_contract),
        "operator_execution": _operator_execution_payload(request.operator_execution),
        "rejected_history": {
            "source_root": str(request.rejected_history.source_root),
            "manifest_sha256": request.rejected_history.manifest_sha256,
            "rejection_reason": request.rejected_history.rejection_reason,
        },
    }


def _source_v4_schema_payload() -> dict[str, object]:
    return {
        "schema_version": "full-pool-segmented-source-v4-schema-v1",
        "source_schema_version": FULL_POOL_SOURCE_V4_SCHEMA,
        "terminal_variants": ["primary"],
        "row_files": {
            "candidate": "candidate_rows.jsonl",
            "pair": "pair_rows.jsonl",
            "terminal": "terminal_rows.jsonl",
            "variant_evidence": "variant_evidence_rows.jsonl",
            "steps": "steps.jsonl",
        },
        "provisional_outcomes_are_attempt_evidence_only": True,
    }


def _source_v4_spool_refs(
    request: StrictFreshReplayRequest,
) -> list[dict[str, object]]:
    root = request.workspace / "concurrent_runtime_batch_spool"
    if root.is_symlink() or not root.is_dir():
        raise ValueError("source-v4 runtime batch spool is missing or unsafe")
    entries = tuple(sorted(root.iterdir(), key=lambda path: path.name))
    expected_names = {
        f"batch-{time_step:06d}.json" for time_step in range(request.config.horizon)
    }
    if (
        any(path.is_symlink() or not path.is_file() for path in entries)
        or {path.name for path in entries} != expected_names
    ):
        raise ValueError("source-v4 runtime batch spool inventory is incomplete or unsafe")
    return [
        {
            "workspace_relative_path": path.relative_to(request.workspace).as_posix(),
            "sha256": _sha256_file(path),
            "bytes": path.stat().st_size,
        }
        for path in entries
    ]


def _source_v4_expected_manifest(
    *,
    request: StrictFreshReplayRequest,
    identity_hash: str,
    result: StrictFreshReplayResult,
    progress: _StrictSettlementProgress,
    evidence: _StrictSourceV4Evidence,
    artifacts: Sequence[Mapping[str, object]],
    reconciliation_entries: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    artifact_by_path = {
        _non_empty(item.get("relative_path"), "source-v4 artifact path"): item
        for item in artifacts
    }
    outcomes = tuple(progress.outcomes.values())
    provisional_provider_failed = sum(
        1
        for outcome in outcomes
        if outcome.kind is DurablePairOutcomeKind.TERMINAL
        and cast(DurablePairTerminal, outcome.terminal).terminal_row.get("terminal_status")
        == "provider_failed"
    )
    snapshot_refs = [
        {
            "relative_path": relative,
            "sha256": artifact_by_path[relative]["sha256"],
        }
        for relative in sorted(artifact_by_path)
        if relative.startswith("runtime/snapshots/")
    ]
    production_topology = (
        request.config.sample_size == 36_400
        and request.config.horizon == 30
        and request.config.delivery_capacity
        == CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_DELIVERY_CAPACITY
        and request.logical_cap == 109_200
        and request.physical_cap == 120_120
        and request.max_concurrency == 10
    )
    external_invocations = _non_negative_int(
        evidence.provider_accounting.get("external_request_invocations"),
        "source-v4 external request invocations",
    )
    production_deploy_eligible = (
        production_topology
        and request.config.configuration_profile == "production"
        and request.operator_execution is not None
        and evidence.source_eligible
        and external_invocations >= request.logical_cap
        and result.dispatched_without_settlement_uncertainty == 0
    )
    return {
        "schema_version": FULL_POOL_SOURCE_V4_SCHEMA,
        "source_identity": identity_hash,
        "replay_id": request.replay_id,
        "profile": request.config.configuration_profile,
        "production_topology": production_topology,
        "counts": dict(evidence.counts),
        "provider_accounting": dict(evidence.provider_accounting),
        "physical_accounting": {
            "settled_actual_attempts": result.settled_actual_attempts,
            "dispatched_without_settlement_uncertainty": (
                result.dispatched_without_settlement_uncertainty
            ),
            "charged_physical_attempts": result.charged_physical_attempts,
            "active_reservations": result.active_physical_reservations,
            "physical_cap": request.physical_cap,
        },
        "operator_execution": _operator_execution_payload(request.operator_execution),
        "fresh_lineage": {
            "schema_version": "full-pool-strict-fresh-lineage-v1",
            "fresh_from_batch_zero": True,
            "initial_positions": {
                "batch": 0,
                "logical": 0,
                "physical": 0,
                "pair_schedule": 0,
            },
            "imported_terminal_count": 0,
            "imported_batch_count": 0,
            "rejected_history": {
                "source_root": str(request.rejected_history.source_root),
                "manifest_sha256": request.rejected_history.manifest_sha256,
                "rejection_reason": request.rejected_history.rejection_reason,
            },
        },
        "runtime_lineage": {
            "run_identity_sha256": artifact_by_path[
                "runtime/fresh-run-identity.json"
            ]["sha256"],
            "execution_journal_sha256": artifact_by_path[
                "runtime/execution-journal.jsonl"
            ]["sha256"],
            "execution_status_sha256": artifact_by_path[
                "runtime/execution-status.json"
            ]["sha256"],
            "batch_snapshots": snapshot_refs,
            "batch_spool": _source_v4_spool_refs(request),
        },
        "strict_policy": {
            "policy_identity_hash": identity_hash,
            "policy_sha256": artifact_by_path[
                "strict/strict-pair-policy.json"
            ]["sha256"],
            "policy_ledger_sha256": artifact_by_path[
                "strict/strict-pair-policy-ledger.jsonl"
            ]["sha256"],
            "reconciliation_dispatch_count": result.reconciliation_dispatch_count,
        },
        "settlement_v2": {
            "schema_version": "full-pool-durable-pair-settlement-v2",
            "original_journal_sha256": artifact_by_path[
                "settlement/original/durable-pair-settlement-v2.jsonl"
            ]["sha256"],
            "wave_count": len(progress.waves),
            "original_dispatched_pair_count": progress.logical_count,
            "original_terminal_pair_count": sum(
                outcome.kind is DurablePairOutcomeKind.TERMINAL
                for outcome in outcomes
            ),
            "provisional_provider_failed_count": provisional_provider_failed,
            "provisional_unknown_pair_count": sum(
                outcome.kind is DurablePairOutcomeKind.PROVENANCE_UNKNOWN
                for outcome in outcomes
            ),
            "implementation_failed_pair_count": sum(
                outcome.kind is DurablePairOutcomeKind.IMPLEMENTATION_FAILED
                for outcome in outcomes
            ),
            "final_succeeded_terminal_count": result.final_succeeded_terminal_count,
            "reconciliation_journals": [dict(item) for item in reconciliation_entries],
        },
        "row_hashes": dict(evidence.row_hashes),
        "provider_contract_sha256": _sha256_json(request.provider_contract),
        "source_hash": _sha256_json(list(artifacts)),
        "production_deploy_eligible": production_deploy_eligible,
        "artifacts": [dict(item) for item in artifacts],
    }


def _validate_source_v4(
    *,
    source: Path,
    manifest_sha256: str,
    request: StrictFreshReplayRequest,
    identity_hash: str,
    sample_user_ids: Sequence[str],
    result: StrictFreshReplayResult,
    policy: StrictPairPolicy,
    settlement: DurablePairSettlement,
    progress: _StrictSettlementProgress,
    journal: ConcurrentExecutionJournal,
    evidence: _StrictSourceV4Evidence,
) -> None:
    if source.is_symlink() or not source.is_dir():
        raise ValueError("source-v4 must be one real directory")
    manifest_path = source / "manifest.json"
    if _sha256_file(manifest_path) != _digest(manifest_sha256, "source-v4 manifest hash"):
        raise ValueError("source-v4 manifest differs from its explicit hash")
    manifest = _read_json(manifest_path)
    if set(manifest) != _SOURCE_V4_MANIFEST_FIELDS:
        raise ValueError("source-v4 manifest fields are not exact")
    artifact_rows = manifest.get("artifacts")
    if not isinstance(artifact_rows, Sequence) or isinstance(artifact_rows, (str, bytes)):
        raise ValueError("source-v4 artifacts must be a sequence")
    artifacts: list[dict[str, object]] = []
    artifact_by_path: dict[str, dict[str, object]] = {}
    for raw in artifact_rows:
        artifact = _mapping(raw, "source-v4 artifact reference")
        if set(artifact) != {"relative_path", "sha256", "bytes"}:
            raise ValueError("source-v4 artifact reference fields are not exact")
        relative_text = _non_empty(artifact.get("relative_path"), "source-v4 artifact path")
        relative = PurePosixPath(relative_text)
        target = source / Path(*relative.parts)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or relative_text == "manifest.json"
            or relative_text in artifact_by_path
            or target.is_symlink()
            or not target.is_file()
            or _sha256_file(target) != _digest(artifact.get("sha256"), "artifact hash")
            or target.stat().st_size != _non_negative_int(artifact.get("bytes"), "artifact bytes")
        ):
            raise ValueError("source-v4 artifact inventory is unsafe or crossed")
        artifacts.append(artifact)
        artifact_by_path[relative_text] = artifact

    workspace_artifacts, reconciliation_entries = _source_v4_workspace_artifacts(
        request=request,
        policy=policy,
        settlement=settlement,
        journal=journal,
    )
    expected_paths = {
        "candidate_rows.jsonl",
        "pair_rows.jsonl",
        "terminal_rows.jsonl",
        "variant_evidence_rows.jsonl",
        "steps.jsonl",
        "latent-membership.csv",
        "fresh-request.json",
        "schema.json",
        *workspace_artifacts,
    }
    inventory = tuple(source.rglob("*"))
    if any(path.is_symlink() or not (path.is_file() or path.is_dir()) for path in inventory):
        raise ValueError("source-v4 artifact inventory contains an unsafe entry")
    actual_files = {
        path.relative_to(source).as_posix()
        for path in inventory
        if path.is_file()
    }
    if set(artifact_by_path) != expected_paths or actual_files != expected_paths | {
        "manifest.json"
    }:
        raise ValueError("source-v4 artifact inventory is missing, extra, or unsafe")
    for relative, origin in workspace_artifacts.items():
        if artifact_by_path[relative]["sha256"] != _sha256_file(origin):
            raise ValueError("source-v4 copied runtime lineage differs from its origin")
    for relative, expected_hash in evidence.row_hashes.items():
        if artifact_by_path[relative]["sha256"] != expected_hash:
            raise ValueError("source-v4 row hash differs from committed runtime evidence")
    membership_hash = hashlib.sha256(
        _source_v4_membership_bytes(
            request.config.dataset_dir,
            sample_user_ids=sample_user_ids,
        )
    ).hexdigest()
    if artifact_by_path["latent-membership.csv"]["sha256"] != membership_hash:
        raise ValueError("source-v4 latent membership changed after closure")
    if _read_json(source / "fresh-request.json") != _source_v4_request_payload(request):
        raise ValueError("source-v4 frozen request is crossed")
    if _read_json(source / "schema.json") != _source_v4_schema_payload():
        raise ValueError("source-v4 schema document is crossed")
    expected_manifest = _source_v4_expected_manifest(
        request=request,
        identity_hash=identity_hash,
        result=result,
        progress=progress,
        evidence=evidence,
        artifacts=artifacts,
        reconciliation_entries=reconciliation_entries,
    )
    if manifest != expected_manifest:
        raise ValueError("source-v4 manifest differs from persisted fresh runtime facts")


def _source_v4_artifact_refs(source: Path) -> list[dict[str, object]]:
    return [
        {
            "relative_path": path.relative_to(source).as_posix(),
            "sha256": _sha256_file(path),
            "bytes": path.stat().st_size,
        }
        for path in sorted(source.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file() and not path.is_symlink() and path.name != "manifest.json"
    ]


def _discard_source_v4_staging(staging: Path, workspace: Path) -> None:
    if not staging.exists() and not staging.is_symlink():
        return
    if staging.is_symlink() or not staging.is_dir():
        raise ValueError("source-v4 staging path is unsafe")
    shutil.rmtree(staging)
    _fsync_directory(workspace)


def _true_cell(value: object) -> bool:
    if value is True or value == "true":
        return True
    if value is False or value == "false":
        return False
    raise ValueError("source-v4 boolean cell is malformed")


def _copy_file_durable(source: Path, target: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise ValueError("source-v4 copied artifact origin is missing or unsafe")
    _write_bytes_durable(target, source.read_bytes())


def _write_bytes_durable(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)
    _fsync_directory(path.parent)


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
        "source_root": str(result.source_root) if result.source_root is not None else None,
        "source_manifest_sha256": result.source_manifest_sha256,
        "production_deploy_eligible": result.production_deploy_eligible,
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
