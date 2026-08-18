from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import durable_pair_settlement as settlement_module
from ._concurrent_runtime_spool import (
    _ConcurrentRuntimeBatchSpool,
    _ConcurrentRuntimeSpoolChunk,
)
from .concurrent_execution_journal import ConcurrentExecutionJournal
from .concurrent_message_experiment import (
    _ConcurrentRuntimeKernel,
    _ConcurrentRuntimeKernelState,
    _PairExecutionPlan,
    _PrimaryOnlyConcurrentRuntimeConsumer,
)
from .decision import LLMDecisionAdapter
from .durable_pair_settlement import (
    DURABLE_PAIR_SETTLEMENT_JOURNAL_FILE,
    DurablePairDispatch,
    DurablePairSettlement,
    DurablePairTerminal,
)
from .full_pool_segmented_continuation import (
    _close_segmented_source_v2,
    _ContinuationLedger,
    _execute_settled_plans,
    _execute_typed_pair,
    _replay_continuation_ledger,
    _SegmentedKernelJournal,
    _typed_settlement_plan_identity,
    _WorkerResult,
)
from .full_pool_segmented_nested_recovery import (
    FullPoolSegmentedNestedRecoveryPreflight,
)
from .full_pool_segmented_operator import LocalOperatorFilesystem
from .full_pool_segmented_recovery_execution import (
    FullPoolSegmentedRecovery,
    SegmentedRecoveryExecutionRequest,
    _FailedLedgerReplay,
    _read_failed_ledger,
    _recovery_documents,
    _register_results,
    _snapshot_documents,
    _snapshot_pair_ids,
    _utc_datetime,
    _ValidatedRecoveryInputs,
)
from .full_pool_segmented_recovery_execution import (
    _assert_protected_unchanged as _assert_parent_recovery_unchanged,
)

AUTOMATED_RECOVERY_IDENTITY_FILE = "automated_recovery_identity.json"
AUTOMATED_RECOVERY_POLICY_FILE = "automated_recovery_policy.json"
AUTOMATED_RECOVERY_POLICY_LEDGER_FILE = "automated_recovery_policy_ledger.jsonl"
AUTOMATED_RECOVERY_STATUS_FILE = "automated_recovery_status.json"

_AUTOMATED_IDENTITY_SCHEMA = "full-pool-segmented-automated-recovery-identity-v3"
_AUTOMATED_POLICY_SCHEMA = "full-pool-segmented-automated-recovery-policy-v3"
_AUTOMATED_POLICY_ENVELOPE_SCHEMA = "full-pool-segmented-automated-recovery-policy-envelope-v3"
_AUTOMATED_POLICY_LEDGER_SCHEMA = "full-pool-segmented-automated-recovery-policy-ledger-v3"
_AUTOMATED_STATUS_SCHEMA = "full-pool-segmented-automated-recovery-status-v3"
_FORMAL_NESTED_PLAN_SHA256 = "eb0fcad9bc0994a35166efde3f8259eaaa24b2eff7e5175561669ce4693f38c6"
_FORMAL_NESTED_IDENTITY_HASH = "47a79fa855052a1fc69d653e02443eeb128e40fd0786ab31f9cafcef17031e56"
_FORMAL_PARENT_RECOVERY_IDENTITY_HASH = "8dffaa914b5f69da8baaee27cfdc5b1dacdb075af38aef65b22e41b1195f53dc"
_FORMAL_STOPPED_INVENTORY_SHA256 = "3f3e517db1681cac5bab71ca826f67a711ee5c77860f28593583e2a67a45fcd2"
_FORMAL_RETRY_PAIR_IDS = (
    "2726385359791149:message_3:24",
    "2726385761915815:message_3:24",
    "2726399652412872:message_3:24",
    "2726419687015373:message_3:24",
    "2727683308:message_3:24",
    "2728328409650713:message_3:24",
    "2729447809097123:message_3:24",
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RECOVERY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AutomatedNestedRecoveryRequest(_FrozenModel):
    """One explicit nested plan and its independent automated workspace."""

    nested_recovery_plan_path: Path
    nested_recovery_plan_sha256: str
    recovery_id: str = Field(min_length=1, max_length=160)
    recovery_workspace: Path

    @field_validator("nested_recovery_plan_path", "recovery_workspace", mode="before")
    @classmethod
    def _absolute_path(cls, value: object) -> Path:
        return Path(cast(str | Path, value)).expanduser().absolute()

    @field_validator("nested_recovery_plan_sha256")
    @classmethod
    def _hash(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("nested_recovery_plan_sha256 must be a lowercase SHA-256 digest")
        return value

    @field_validator("recovery_id")
    @classmethod
    def _identity(cls, value: str) -> str:
        if _RECOVERY_ID.fullmatch(value) is None:
            raise ValueError("recovery_id contains unsupported characters")
        return value

    @model_validator(mode="after")
    def _independent_workspace(self) -> AutomatedNestedRecoveryRequest:
        plan_root = self.nested_recovery_plan_path.parent
        if (
            self.recovery_workspace == plan_root
            or self.recovery_workspace.is_relative_to(plan_root)
            or plan_root.is_relative_to(self.recovery_workspace)
        ):
            raise ValueError("automated recovery workspace must be independent from its nested plan")
        return self


class AutomatedNestedRecoveryResult(_FrozenModel):
    status: Literal["complete", "resumable", "automation_exhausted", "implementation_failed"]
    workspace_root: Path
    recovery_identity_hash: str
    source_root: Path | None = None
    source_manifest_sha256: str | None = None
    logical_count: int = Field(ge=0)
    imported_durable_terminal_count: int = Field(ge=0)
    fresh_logical_count: int = Field(ge=0)
    historical_physical_attempts: int = Field(ge=0)
    uncertainty_physical_charge: int = Field(ge=0)
    new_uncertainty_physical_charge: int = Field(ge=0)
    retry_physical_attempts: int = Field(ge=0)
    reconciliation_physical_attempts: int = Field(ge=0)
    continuation_physical_attempts: int = Field(ge=0)
    physical_attempt_count: int = Field(ge=0)
    recovered_pair_ids: tuple[str, ...]
    unknown_pair_ids: tuple[str, ...]
    implementation_failed_pair_ids: tuple[str, ...]
    automation_exhausted_pair_ids: tuple[str, ...]
    provider_calls: Literal[0] = 0
    production_deploy_eligible: Literal[False] = False

    @model_validator(mode="after")
    def _closure_invariants(self) -> AutomatedNestedRecoveryResult:
        source_fields = (self.source_root, self.source_manifest_sha256)
        if self.status == "complete" and any(value is None for value in source_fields):
            raise ValueError("complete automated recovery requires source-v3 closure")
        if self.status != "complete" and any(value is not None for value in source_fields):
            raise ValueError("non-complete automated recovery cannot expose source-v3")
        if self.physical_attempt_count != (
            self.historical_physical_attempts
            + self.uncertainty_physical_charge
            + self.new_uncertainty_physical_charge
            + self.retry_physical_attempts
            + self.reconciliation_physical_attempts
            + self.continuation_physical_attempts
        ):
            raise ValueError("automated recovery physical accounting does not close")
        return self


@dataclass(frozen=True)
class _ValidatedAutomatedInputs:
    payload: dict[str, object]
    nested_recovery_plan_path: Path
    nested_recovery_plan_sha256: str
    parent_request: SegmentedRecoveryExecutionRequest
    parent_inputs: _ValidatedRecoveryInputs
    stopped_workspace: Path
    stopped_identity: dict[str, object]
    stopped_ledger: _FailedLedgerReplay
    historical_chunks: tuple[_ConcurrentRuntimeSpoolChunk, ...]
    snapshot_document_by_time_step: dict[int, dict[str, object]]
    active_snapshot_document: dict[str, object]
    active_terminal_payloads: tuple[dict[str, object], ...]
    unresolved_pair_ids: tuple[str, ...]
    imported_durable_terminal_count: int
    expected_logical_count: int
    historical_logical_count: int
    historical_physical_attempts: int
    uncertainty_physical_charge: int
    protected_inventory: dict[str, object]


@dataclass(frozen=True)
class _AutomatedRuntime:
    ledger: _ContinuationLedger
    journal: _SegmentedKernelJournal
    spool: _ConcurrentRuntimeBatchSpool
    kernel: _ConcurrentRuntimeKernel
    state: _ConcurrentRuntimeKernelState


@dataclass(frozen=True)
class _AutomatedPlanExecution:
    results: dict[str, _WorkerResult]
    physical_attempt_charge: int
    reconciliation_physical_attempts: int
    cap_stopped: bool
    unknown_pair_ids: tuple[str, ...]
    implementation_failed_pair_ids: tuple[str, ...]

    @property
    def stopped(self) -> bool:
        return bool(
            self.cap_stopped
            or self.unknown_pair_ids
            or self.implementation_failed_pair_ids
        )


class _ReplayPlanningJournal:
    read_only = False

    def __init__(
        self,
        *,
        workspace: Path,
        run_id: str,
        identity_hash: str,
        expected_snapshot: Mapping[str, object],
    ) -> None:
        self.workspace_dir = workspace
        self.run_id = run_id
        self.identity_hash = identity_hash
        self.expected_snapshot = dict(expected_snapshot)

    def persist_snapshot(
        self,
        *,
        snapshot_type: str,
        snapshot_identity: Mapping[str, object],
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        document = {
            "schema_version": "concurrent-message-execution-snapshot-v1",
            "snapshot_type": snapshot_type,
            "snapshot_identity": dict(snapshot_identity),
            "payload": dict(payload),
        }
        if document != self.expected_snapshot:
            raise ValueError("replayed active batch differs from its persisted snapshot")
        return {"snapshot_hash": _sha256_json(document)}

    def append(
        self,
        *,
        event_type: str,
        event_identity: Mapping[str, object],
        payload: Mapping[str, object],
        batch_snapshot_hash: str | None = None,
    ) -> dict[str, object]:
        return {
            "event_type": event_type,
            "event_identity": dict(event_identity),
            "payload": dict(payload),
            "batch_snapshot_hash": batch_snapshot_hash,
        }


@dataclass(frozen=True)
class _AutomatedDocuments:
    identity: dict[str, object]
    policy: dict[str, object]


class AutomatedRecoveryPolicy:
    """Own the immutable policy and its hash-chained single-use slot ledger."""

    def __init__(
        self,
        workspace: Path,
        *,
        identity_hash: str,
        expected_payload: Mapping[str, object],
    ) -> None:
        self.workspace = workspace
        self.identity_hash = identity_hash
        self.expected_payload = dict(expected_payload)
        self.path = workspace / AUTOMATED_RECOVERY_POLICY_FILE
        self.ledger_path = workspace / AUTOMATED_RECOVERY_POLICY_LEDGER_FILE

    def create_or_validate(self) -> dict[str, object]:
        if self.path.exists() or self.path.is_symlink():
            if self.path.is_symlink() or not self.path.is_file():
                raise ValueError("automated recovery policy must be one regular file")
            envelope = _read_json(self.path)
            self._validate_envelope(envelope)
        else:
            envelope = {
                "schema_version": _AUTOMATED_POLICY_ENVELOPE_SCHEMA,
                "payload": self.expected_payload,
                "payload_sha256": _sha256_json(self.expected_payload),
            }
            _exclusive_write_json(self.path, envelope)
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
        return self.expected_payload

    def consume_reconciliation_slot(
        self,
        *,
        pair_id: str,
        source_wave_index: int,
        source_outcome_audit_sha256: str,
        physical_attempt_count: int,
        reconciliation_identity_hash: str,
        journal_relative_path: str,
    ) -> bool:
        records = self.replay()
        consumed = {
            _non_empty(
                _mapping(record.get("payload"), "slot consumption payload").get("pair_id"),
                "consumed reconciliation pair id",
            )
            for record in records
            if record.get("event_type") == "reconciliation_slot_consumed"
        }
        reason: str | None = None
        if pair_id in consumed:
            reason = "reconciliation_slot_already_consumed"
        reservation = _non_negative_int(
            self.expected_payload.get("reconciliation_slot_physical_reservation"),
            "reconciliation slot reservation",
        )
        physical_cap = _non_negative_int(
            self.expected_payload.get("physical_cap"), "policy physical cap"
        )
        if physical_attempt_count + reservation > physical_cap:
            reason = "physical_cap_insufficient"
        if reason is not None:
            self.exhaust(pair_id=pair_id, reason=reason)
            return False
        self._append_event(
            "reconciliation_slot_consumed",
            {
                "pair_id": pair_id,
                "source_wave_index": source_wave_index,
                "source_outcome_audit_sha256": source_outcome_audit_sha256,
                "physical_reservation": reservation,
                "physical_attempt_count_before_reservation": physical_attempt_count,
                "reconciliation_identity_hash": reconciliation_identity_hash,
                "journal_relative_path": journal_relative_path,
            },
        )
        return True

    def resolve_reconciliation(
        self,
        *,
        pair_id: str,
        reconciliation_identity_hash: str,
        journal_sha256: str,
        terminal_sha256: str,
        physical_attempt_charge: int,
    ) -> None:
        records = self.replay()
        if any(
            record.get("event_type") == "reconciliation_resolved"
            and _mapping(record.get("payload"), "resolved payload").get("pair_id") == pair_id
            for record in records
        ):
            raise ValueError("automated reconciliation resolution is duplicated")
        self._append_event(
            "reconciliation_resolved",
            {
                "pair_id": pair_id,
                "reconciliation_identity_hash": reconciliation_identity_hash,
                "journal_sha256": journal_sha256,
                "terminal_sha256": terminal_sha256,
                "physical_attempt_charge": physical_attempt_charge,
            },
        )

    def exhaust(self, *, pair_id: str, reason: str) -> None:
        records = self.replay()
        if any(record.get("event_type") == "automation_exhausted" for record in records):
            return
        self._append_event(
            "automation_exhausted",
            {"pair_id": pair_id, "reason": reason},
        )

    def complete(self, *, logical_count: int, physical_attempt_count: int) -> None:
        records = self.replay()
        if any(record.get("event_type") == "policy_completed" for record in records):
            raise ValueError("automated recovery policy completion is duplicated")
        self._append_event(
            "policy_completed",
            {
                "logical_count": logical_count,
                "physical_attempt_count": physical_attempt_count,
            },
        )

    def replay(self) -> tuple[dict[str, object], ...]:
        if self.ledger_path.is_symlink() or not self.ledger_path.is_file():
            raise ValueError("automated recovery policy ledger is missing or unsafe")
        records: list[dict[str, object]] = []
        previous: str | None = None
        for expected_sequence, line in enumerate(
            self.ledger_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line:
                continue
            record = _mapping(json.loads(line), "automated recovery policy ledger record")
            checksum = _non_empty(record.get("checksum"), "policy ledger checksum")
            body = {key: value for key, value in record.items() if key != "checksum"}
            if (
                set(record)
                != {
                    "schema_version",
                    "sequence",
                    "previous_checksum",
                    "policy_identity_hash",
                    "event_type",
                    "payload",
                    "checksum",
                }
                or record.get("schema_version") != _AUTOMATED_POLICY_LEDGER_SCHEMA
                or record.get("sequence") != expected_sequence
                or record.get("previous_checksum") != previous
                or record.get("policy_identity_hash") != self.identity_hash
                or checksum != _sha256_json(body)
            ):
                raise ValueError("automated recovery policy ledger hash chain is invalid")
            records.append(record)
            previous = checksum
        if not records or records[0].get("event_type") != "policy_created":
            raise ValueError("automated recovery policy ledger lacks its create-once event")
        first_payload = _mapping(records[0].get("payload"), "policy created payload")
        if first_payload.get("policy_sha256") != _sha256_file(self.path):
            raise ValueError("automated recovery policy ledger is crossed with policy bytes")
        consumed: dict[str, dict[str, object]] = {}
        resolved: set[str] = set()
        terminal_event: str | None = None
        for index, record in enumerate(records):
            event_type = record.get("event_type")
            payload = _mapping(record.get("payload"), "policy event payload")
            if index == 0:
                continue
            if terminal_event is not None:
                raise ValueError("automated recovery policy ledger has events after terminal state")
            if event_type == "reconciliation_slot_consumed":
                pair_id = _non_empty(payload.get("pair_id"), "consumed reconciliation pair id")
                relative = Path(
                    _non_empty(payload.get("journal_relative_path"), "reconciliation journal path")
                )
                if (
                    pair_id in consumed
                    or relative.is_absolute()
                    or ".." in relative.parts
                    or payload.get("physical_reservation")
                    != self.expected_payload.get("reconciliation_slot_physical_reservation")
                    or _SHA256.fullmatch(
                        _non_empty(
                            payload.get("source_outcome_audit_sha256"),
                            "source outcome audit SHA-256",
                        )
                    )
                    is None
                    or _SHA256.fullmatch(
                        _non_empty(
                            payload.get("reconciliation_identity_hash"),
                            "reconciliation identity hash",
                        )
                    )
                    is None
                ):
                    raise ValueError("automated recovery reconciliation slot is duplicated or crossed")
                consumed[pair_id] = payload
            elif event_type == "reconciliation_resolved":
                pair_id = _non_empty(payload.get("pair_id"), "resolved reconciliation pair id")
                slot = consumed.get(pair_id)
                if (
                    slot is None
                    or pair_id in resolved
                    or payload.get("reconciliation_identity_hash")
                    != slot.get("reconciliation_identity_hash")
                    or _SHA256.fullmatch(
                        _non_empty(payload.get("journal_sha256"), "reconciliation journal SHA-256")
                    )
                    is None
                    or _SHA256.fullmatch(
                        _non_empty(payload.get("terminal_sha256"), "reconciliation terminal SHA-256")
                    )
                    is None
                    or _non_negative_int(
                        payload.get("physical_attempt_charge"),
                        "reconciliation physical attempt charge",
                    )
                    > _non_negative_int(
                        self.expected_payload.get("maximum_attempts_per_dispatch"),
                        "maximum attempts per dispatch",
                    )
                ):
                    raise ValueError("automated recovery reconciliation resolution is crossed")
                resolved.add(pair_id)
            elif event_type == "automation_exhausted":
                _non_empty(payload.get("pair_id"), "automation exhausted pair id")
                _non_empty(payload.get("reason"), "automation exhausted reason")
                terminal_event = "automation_exhausted"
            elif event_type == "policy_completed":
                if set(consumed) != resolved:
                    raise ValueError("automated recovery policy completed with unresolved slots")
                _non_negative_int(payload.get("logical_count"), "completed logical count")
                _non_negative_int(payload.get("physical_attempt_count"), "completed physical count")
                terminal_event = "policy_completed"
            else:
                raise ValueError("automated recovery policy ledger event type is unsupported")
        return tuple(records)

    def _append_event(self, event_type: str, payload: Mapping[str, object]) -> None:
        records = self.replay()
        previous = _non_empty(records[-1].get("checksum"), "policy ledger checksum")
        _append_policy_event(
            self.ledger_path,
            identity_hash=self.identity_hash,
            sequence=len(records) + 1,
            previous_checksum=previous,
            event_type=event_type,
            payload=payload,
        )

    def _validate_envelope(self, envelope: Mapping[str, object]) -> None:
        if set(envelope) != {"schema_version", "payload", "payload_sha256"} or envelope.get(
            "schema_version"
        ) != _AUTOMATED_POLICY_ENVELOPE_SCHEMA:
            raise ValueError("automated recovery policy envelope is not exact")
        payload = _mapping(envelope.get("payload"), "automated recovery policy payload")
        if (
            payload != self.expected_payload
            or envelope.get("payload_sha256") != _sha256_json(payload)
        ):
            raise ValueError("automated recovery policy drifted from its frozen contract")


class FullPoolSegmentedAutomatedRecovery:
    """Run one hash-bound nested recovery under a persisted bounded policy."""

    def run(
        self,
        request: AutomatedNestedRecoveryRequest,
        *,
        adapter_factory: Callable[[int], LLMDecisionAdapter],
    ) -> AutomatedNestedRecoveryResult:
        inputs = _validated_automated_inputs(request)
        documents = _automated_documents(request, inputs)
        workspace_exists = request.recovery_workspace.exists() or request.recovery_workspace.is_symlink()
        if workspace_exists:
            existing = _load_existing_status(request, inputs, documents)
            if existing is not None:
                return existing
        else:
            _initialize_automated_documents(request, documents)
        policy = AutomatedRecoveryPolicy(
            request.recovery_workspace,
            identity_hash=_non_empty(documents.identity.get("identity_hash"), "identity hash"),
            expected_payload=documents.policy,
        )
        policy.create_or_validate()
        _assert_inputs_unchanged(inputs)
        plan_accounting = _mapping(inputs.payload.get("accounting"), "nested accounting")
        required_retry_window = len(inputs.unresolved_pair_ids) * _non_negative_int(
            _mapping(inputs.payload.get("execution_contract"), "execution contract").get(
                "maximum_attempts_per_dispatch"
            ),
            "maximum attempts per dispatch",
        )
        if _non_negative_int(
            plan_accounting.get("remaining_physical_cap"), "remaining physical cap"
        ) < required_retry_window:
            blocked_pair_id = inputs.unresolved_pair_ids[0]
            policy.exhaust(pair_id=blocked_pair_id, reason="physical_cap_insufficient")
            result = _stopped_result(
                request,
                inputs,
                documents,
                status="automation_exhausted",
                implementation_failed_pair_ids=(),
                automation_exhausted_pair_ids=(blocked_pair_id,),
            )
            _write_status(request.recovery_workspace, result)
            return result
        runtime = (
            _load_automated_runtime(request, inputs, documents)
            if workspace_exists
            else _initialize_automated_runtime(request, inputs, documents)
        )
        _assert_inputs_unchanged(inputs)
        policy_completed = any(
            record.get("event_type") == "policy_completed"
            for record in policy.replay()
        )
        runtime_complete = (
            runtime.state.next_time_step == inputs.parent_inputs.config.horizon
            and runtime.kernel.active_batch is None
        )
        if policy_completed or runtime_complete:
            if policy_completed and not runtime_complete:
                raise ValueError("policy completion precedes the final batch barrier")
            maximum_attempts = _non_negative_int(
                _mapping(inputs.payload.get("execution_contract"), "execution contract").get(
                    "maximum_attempts_per_dispatch"
                ),
                "maximum attempts per dispatch",
            )
            settlement = DurablePairSettlement(
                request.recovery_workspace,
                settlement_identity_hash=_non_empty(
                    documents.identity.get("identity_hash"), "identity hash"
                ),
                maximum_attempts_per_dispatch=maximum_attempts,
                max_concurrency=10,
                legacy_event_sink=runtime.ledger.append,
            )
            result = _complete_automated_runtime(
                request=request,
                inputs=inputs,
                documents=documents,
                policy=policy,
                runtime=runtime,
                settlement=settlement,
                reconciliation_physical_attempts=(
                    _resolved_reconciliation_physical_attempts(policy)
                ),
                record_policy_completion=not policy_completed,
            )
            _assert_inputs_unchanged(inputs)
            return result
        adapters = [adapter_factory(lane_id) for lane_id in range(10)]
        result = _run_automated_runtime(
            request=request,
            inputs=inputs,
            documents=documents,
            policy=policy,
            runtime=runtime,
            adapters=adapters,
        )
        _assert_inputs_unchanged(inputs)
        return result

    def status(
        self,
        request: AutomatedNestedRecoveryRequest,
    ) -> AutomatedNestedRecoveryResult:
        inputs = _validated_automated_inputs(request)
        documents = _automated_documents(request, inputs)
        existing = _load_existing_status(request, inputs, documents)
        if existing is None:
            raise FileNotFoundError("automated nested recovery status does not exist")
        return existing


def _automated_documents(
    request: AutomatedNestedRecoveryRequest,
    inputs: _ValidatedAutomatedInputs,
) -> _AutomatedDocuments:
    nested_identity = _mapping(inputs.payload.get("recovery_identity"), "nested recovery identity")
    execution = _mapping(inputs.payload.get("execution_contract"), "nested execution contract")
    accounting = _mapping(inputs.payload.get("accounting"), "nested recovery accounting")
    snapshot = _mapping(inputs.payload.get("recovery_snapshot"), "nested recovery snapshot")
    unresolved_rows = _mapping_sequence(
        snapshot.get("unresolved_pairs"), "nested recovery unresolved pairs"
    )
    implementation = {
        "repository_commit": _repository_commit(),
        "automated_recovery_module_sha256": _sha256_file(Path(__file__).resolve()),
        "durable_pair_settlement_module_sha256": _sha256_file(
            Path(settlement_module.__file__).resolve()
        ),
    }
    identity_body = {
        "schema_version": _AUTOMATED_IDENTITY_SCHEMA,
        "recovery_id": request.recovery_id,
        "workspace": str(request.recovery_workspace),
        "run_id": f"automated-recovery-{request.recovery_id}",
        "nested_recovery_plan_sha256": request.nested_recovery_plan_sha256,
        "nested_recovery_identity_hash": nested_identity["identity_hash"],
        "parent_recovery_identity_hash": nested_identity["parent_recovery_identity_hash"],
        "stopped_recovery_identity_hash": inputs.stopped_identity["identity_hash"],
        "stopped_workspace_inventory_sha256": _sha256_json(inputs.protected_inventory),
        "provider_contract_sha256": execution["provider_contract_sha256"],
        "prompt_contract_sha256": execution["prompt_contract_sha256"],
        "logical_cap": accounting["logical_cap"],
        "physical_cap": accounting["physical_cap"],
        "implementation": implementation,
        "production_deploy_eligible": False,
    }
    identity = {**identity_body, "identity_hash": _sha256_json(identity_body)}
    policy = {
        "schema_version": _AUTOMATED_POLICY_SCHEMA,
        "lifecycle": "active",
        "recovery_identity_hash": identity["identity_hash"],
        "nested_recovery_plan_sha256": request.nested_recovery_plan_sha256,
        "nested_recovery_identity_hash": nested_identity["identity_hash"],
        "parent_recovery_lineage_sha256": _sha256_json(
            _mapping(inputs.payload.get("parent_recovery_lineage"), "parent recovery lineage")
        ),
        "stopped_workspace_inventory_sha256": _sha256_json(inputs.protected_inventory),
        "execution_contract": execution,
        "ordered_retry_pair_ids": [
            _non_empty(row.get("pair_id"), "policy retry pair id") for row in unresolved_rows
        ],
        "ordered_retry_terminal_row_ids": [
            _non_empty(row.get("terminal_row_id"), "policy retry terminal row id")
            for row in unresolved_rows
        ],
        "durable_terminal_count": inputs.imported_durable_terminal_count,
        "committed_batch_count": len(inputs.historical_chunks),
        "fresh_logical_count": inputs.expected_logical_count - inputs.historical_logical_count,
        "logical_cap": accounting["logical_cap"],
        "physical_cap": accounting["physical_cap"],
        "historical_physical_attempts": inputs.historical_physical_attempts,
        "historical_uncertainty_physical_charge": inputs.uncertainty_physical_charge,
        "maximum_attempts_per_dispatch": execution["maximum_attempts_per_dispatch"],
        "maximum_reconciliations_per_pair": 1,
        "reconciliation_slot_physical_reservation": execution[
            "maximum_attempts_per_dispatch"
        ],
        "stop_conditions": [
            "second_provenance_unknown",
            "reconciliation_dispatch_without_settlement",
            "policy_drift",
            "workspace_identity_mismatch",
            "physical_cap_insufficient",
            "implementation_failed",
        ],
        "implementation": implementation,
        "provider_calls": 0,
        "production_deploy_eligible": False,
    }
    return _AutomatedDocuments(identity=identity, policy=policy)


def _initialize_automated_documents(
    request: AutomatedNestedRecoveryRequest,
    documents: _AutomatedDocuments,
) -> None:
    workspace = request.recovery_workspace
    if workspace.parent.is_symlink() or not workspace.parent.is_dir():
        raise ValueError("automated recovery workspace parent must be one real directory")
    workspace.mkdir()
    try:
        _exclusive_write_json(workspace / AUTOMATED_RECOVERY_IDENTITY_FILE, documents.identity)
        AutomatedRecoveryPolicy(
            workspace,
            identity_hash=_non_empty(documents.identity.get("identity_hash"), "identity hash"),
            expected_payload=documents.policy,
        ).create_or_validate()
        _fsync_directory(workspace)
    except BaseException:
        for path in workspace.iterdir():
            if path.is_file() and not path.is_symlink():
                path.chmod(0o644)
                path.unlink()
        workspace.rmdir()
        raise


def _initialize_automated_runtime(
    request: AutomatedNestedRecoveryRequest,
    inputs: _ValidatedAutomatedInputs,
    documents: _AutomatedDocuments,
) -> _AutomatedRuntime:
    workspace = request.recovery_workspace
    identity_hash = _non_empty(documents.identity.get("identity_hash"), "identity hash")
    run_id = _non_empty(documents.identity.get("run_id"), "automated recovery run id")
    ledger = _ContinuationLedger(workspace, continuation_identity_hash=identity_hash)
    ledger.append(
        "kernel_automated_recovery_started",
        {
            "recovery_id": request.recovery_id,
            "nested_recovery_plan_sha256": request.nested_recovery_plan_sha256,
            "unresolved_pair_ids": list(inputs.unresolved_pair_ids),
            "max_concurrency": 10,
        },
    )
    journal = _SegmentedKernelJournal(
        workspace,
        run_id=run_id,
        identity_hash=identity_hash,
        ledger=ledger,
        base_time_step=0,
        record_runtime_events=True,
    )
    spool = _ConcurrentRuntimeBatchSpool(
        workspace,
        run_id=run_id,
        identity_hash=identity_hash,
        terminal_variants=("primary",),
        base_time_step=0,
    )
    for chunk in inputs.historical_chunks:
        document = inputs.snapshot_document_by_time_step.get(chunk.time_step)
        if document is None:
            raise ValueError("automated recovery historical snapshot is missing")
        snapshot_ref = journal.persist_snapshot(
            snapshot_type="batch_plan",
            snapshot_identity={"time_step": chunk.time_step},
            payload=_mapping(document.get("payload"), "historical snapshot payload"),
        )
        if snapshot_ref.get("snapshot_hash") != chunk.batch_snapshot_hash:
            raise ValueError("automated recovery imported snapshot hash changed")
        spool_ref = spool.prepare_batch(
            time_step=chunk.time_step,
            batch_snapshot_hash=chunk.batch_snapshot_hash,
            commit=chunk.commit,
            candidate_rows=chunk.candidate_rows,
            result_rows=chunk.result_rows,
            terminal_rows=chunk.terminal_rows,
            variant_evidence_rows=chunk.variant_evidence_rows,
        )
        committed_ids = _string_list(
            chunk.commit.get("committed_primary_positive_user_ids"),
            "imported committed feedback",
        )
        journal.append(
            event_type="batch_committed",
            event_identity={"time_step": chunk.time_step},
            payload={
                "time_step": chunk.time_step,
                "committed_user_ids": committed_ids,
                "committed_user_count": len(committed_ids),
                "batch_pair_count": len(chunk.result_rows),
                "batch_spool_chunk": spool_ref,
            },
            batch_snapshot_hash=chunk.batch_snapshot_hash,
        )
        spool.publish_prepared(spool_ref)

    prepared = inputs.parent_inputs.prepared
    config = inputs.parent_inputs.config
    state = _ConcurrentRuntimeKernelState(
        cohort=prepared.cohort,
        exposed_by_message={message.message_id: set() for message in config.messages},
        campaign_engaged_user_ids=set(),
    )
    kernel = _ConcurrentRuntimeKernel.primary_only(
        config=config,
        state=state,
        base_network_by_user=prepared.base_network_by_user,
        neighbors_by_user=prepared.neighbors_by_user,
        journal=cast(ConcurrentExecutionJournal, journal),
        spool_base_time_step=0,
    )
    for chunk in inputs.historical_chunks:
        kernel._restore_spooled_chunk(chunk)

    kernel.plan_batch()
    generated_snapshot = next(
        (
            _mapping(record.get("snapshot_document"), "generated active snapshot")
            for record in reversed(journal.records)
            if record.get("record_type") == "snapshot"
        ),
        None,
    )
    if generated_snapshot != inputs.active_snapshot_document:
        raise ValueError("automated recovery same-batch context differs from persisted snapshot")
    plans = kernel.pending_plans()
    if len(inputs.active_terminal_payloads) > len(plans):
        raise ValueError("automated recovery active terminal prefix exceeds its plan")
    for terminal_payload, plan in zip(inputs.active_terminal_payloads, plans, strict=False):
        pair_id = _non_empty(terminal_payload.get("pair_id"), "imported active pair id")
        if pair_id != plan.pair_id:
            raise ValueError("automated recovery imported active terminals are not canonical")
        terminal_row = _mapping(
            terminal_payload.get("terminal_row"), "imported active terminal row"
        )
        variant_evidence = _mapping(
            terminal_payload.get("variant_evidence"), "imported active variant evidence"
        )
        kernel.start_pair(plan)
        kernel.register_terminal(
            plan=plan,
            decision_variant="primary",
            terminal_row=terminal_row,
            variant_evidence=variant_evidence,
        )
        kernel.close_primary_pair(
            plan,
            _PrimaryOnlyConcurrentRuntimeConsumer._primary_result_row(plan, terminal_row),
        )
    ledger.append(
        "kernel_automated_recovery_imported",
        {
            "durable_terminal_count": inputs.imported_durable_terminal_count,
            "committed_batch_count": len(inputs.historical_chunks),
            "active_time_step": len(inputs.historical_chunks),
        },
    )
    return _AutomatedRuntime(
        ledger=ledger,
        journal=journal,
        spool=spool,
        kernel=kernel,
        state=state,
    )


def _execute_plans_with_policy(
    *,
    plans: Sequence[_PairExecutionPlan],
    adapters: Sequence[LLMDecisionAdapter],
    settlement: DurablePairSettlement,
    policy: AutomatedRecoveryPolicy,
    ledger: _ContinuationLedger,
    provider_metadata: Mapping[str, object],
    physical_attempts: int,
    maximum_attempts_per_dispatch: int,
) -> _AutomatedPlanExecution:
    results: dict[str, _WorkerResult] = {}
    main_charge = 0
    reconciliation_charge = 0
    cursor = 0
    while cursor < len(plans):
        remaining = plans[cursor:]
        remaining_ids = [plan.pair_id for plan in remaining]
        captured = next(
            (
                wave
                for wave in settlement.replay(seal_inflight=True).waves
                if wave.canonical_pair_ids
                and wave.canonical_pair_ids[0] == remaining_ids[0]
            ),
            None,
        )
        if captured is not None:
            if tuple(remaining_ids[: len(captured.canonical_pair_ids)]) != (
                captured.canonical_pair_ids
            ):
                raise ValueError("captured settlement wave is crossed with pending plans")
            if not any(pair_id in ledger.terminal_pair_ids for pair_id in captured.canonical_pair_ids):
                settlement._append_legacy_closure(captured)
            main_charge += captured.physical_attempt_charge
            results.update(
                {
                    pair_id: _WorkerResult(
                        pair_id=pair_id,
                        terminal_row=terminal.terminal_row,
                        variant_evidence=terminal.variant_evidence,
                    )
                    for pair_id, terminal in captured.terminal_results.items()
                }
            )
            if captured.implementation_failed_pair_ids:
                return _AutomatedPlanExecution(
                    results=results,
                    physical_attempt_charge=main_charge,
                    reconciliation_physical_attempts=reconciliation_charge,
                    cap_stopped=False,
                    unknown_pair_ids=captured.unknown_pair_ids,
                    implementation_failed_pair_ids=captured.implementation_failed_pair_ids,
                )
            if captured.unknown_pair_ids:
                resolved, charge, unresolved, failed = _reconcile_wave(
                    wave=captured,
                    plans=remaining[: len(captured.canonical_pair_ids)],
                    adapters=adapters,
                    policy=policy,
                    ledger=ledger,
                    provider_metadata=provider_metadata,
                    physical_attempts=(
                        physical_attempts + main_charge + reconciliation_charge
                    ),
                    maximum_attempts_per_dispatch=maximum_attempts_per_dispatch,
                )
                reconciliation_charge += charge
                results.update(resolved)
                if unresolved or failed:
                    return _AutomatedPlanExecution(
                        results=results,
                        physical_attempt_charge=main_charge,
                        reconciliation_physical_attempts=reconciliation_charge,
                        cap_stopped=False,
                        unknown_pair_ids=unresolved,
                        implementation_failed_pair_ids=failed,
                    )
            cursor += len(captured.canonical_pair_ids)
            continue
        policy_physical_cap = _non_negative_int(
            policy.expected_payload.get("physical_cap"), "policy physical cap"
        )
        available_pairs = max(
            0,
            (
                policy_physical_cap
                - physical_attempts
                - main_charge
                - reconciliation_charge
            )
            // maximum_attempts_per_dispatch,
        )
        if available_pairs == 0:
            return _AutomatedPlanExecution(
                results=results,
                physical_attempt_charge=main_charge,
                reconciliation_physical_attempts=reconciliation_charge,
                cap_stopped=True,
                unknown_pair_ids=(),
                implementation_failed_pair_ids=(),
            )
        bounded_remaining = remaining[:available_pairs]
        execution = _execute_settled_plans(
            plans=bounded_remaining,
            adapters=adapters,
            settlement=settlement,
            provider_metadata=provider_metadata,
            physical_attempts=physical_attempts + main_charge + reconciliation_charge,
            maximum_attempts_per_dispatch=maximum_attempts_per_dispatch,
            first_wave_observer_state=[None],
            qualification_artifact_state=[None],
        )
        main_charge += execution.physical_attempt_charge
        results.update(execution.results)
        if execution.cap_stopped:
            return _AutomatedPlanExecution(
                results=results,
                physical_attempt_charge=main_charge,
                reconciliation_physical_attempts=reconciliation_charge,
                cap_stopped=True,
                unknown_pair_ids=(),
                implementation_failed_pair_ids=(),
            )
        if not execution.settlement_stopped:
            cursor += len(bounded_remaining)
            if cursor < len(plans):
                continue
            return _AutomatedPlanExecution(
                results={plan.pair_id: results[plan.pair_id] for plan in plans},
                physical_attempt_charge=main_charge,
                reconciliation_physical_attempts=reconciliation_charge,
                cap_stopped=False,
                unknown_pair_ids=(),
                implementation_failed_pair_ids=(),
            )
        wave = settlement.replay().waves[-1]
        remaining_ids = [plan.pair_id for plan in remaining]
        try:
            wave_start = remaining_ids.index(wave.canonical_pair_ids[0])
        except ValueError as exc:
            raise ValueError("settlement stop is crossed with pending plans") from exc
        if tuple(remaining_ids[wave_start : wave_start + len(wave.canonical_pair_ids)]) != (
            wave.canonical_pair_ids
        ):
            raise ValueError("settlement stop wave is not one canonical pending slice")
        if wave.implementation_failed_pair_ids:
            return _AutomatedPlanExecution(
                results=results,
                physical_attempt_charge=main_charge,
                reconciliation_physical_attempts=reconciliation_charge,
                cap_stopped=False,
                unknown_pair_ids=wave.unknown_pair_ids,
                implementation_failed_pair_ids=wave.implementation_failed_pair_ids,
            )
        wave_plans = remaining[wave_start : wave_start + len(wave.canonical_pair_ids)]
        resolved, charge, unresolved, failed = _reconcile_wave(
            wave=wave,
            plans=wave_plans,
            adapters=adapters,
            policy=policy,
            ledger=ledger,
            provider_metadata=provider_metadata,
            physical_attempts=(
                physical_attempts + main_charge + reconciliation_charge
            ),
            maximum_attempts_per_dispatch=maximum_attempts_per_dispatch,
        )
        reconciliation_charge += charge
        results.update(resolved)
        if unresolved or failed:
            return _AutomatedPlanExecution(
                results=results,
                physical_attempt_charge=main_charge,
                reconciliation_physical_attempts=reconciliation_charge,
                cap_stopped=False,
                unknown_pair_ids=unresolved,
                implementation_failed_pair_ids=failed,
            )
        cursor += wave_start + len(wave.canonical_pair_ids)
    return _AutomatedPlanExecution(
        results={plan.pair_id: results[plan.pair_id] for plan in plans},
        physical_attempt_charge=main_charge,
        reconciliation_physical_attempts=reconciliation_charge,
        cap_stopped=False,
        unknown_pair_ids=(),
        implementation_failed_pair_ids=(),
    )


def _reconcile_wave(
    *,
    wave: settlement_module.DurableWaveSettlement,
    plans: Sequence[_PairExecutionPlan],
    adapters: Sequence[LLMDecisionAdapter],
    policy: AutomatedRecoveryPolicy,
    ledger: _ContinuationLedger,
    provider_metadata: Mapping[str, object],
    physical_attempts: int,
    maximum_attempts_per_dispatch: int,
) -> tuple[dict[str, _WorkerResult], int, tuple[str, ...], tuple[str, ...]]:
    plan_by_id = {plan.pair_id: plan for plan in plans}
    results = {
        pair_id: _WorkerResult(
            pair_id=pair_id,
            terminal_row=terminal.terminal_row,
            variant_evidence=terminal.variant_evidence,
        )
        for pair_id, terminal in wave.terminal_results.items()
    }
    reconciliation_charge = 0
    for pair_id in wave.unknown_pair_ids:
        plan = plan_by_id[pair_id]
        outcome = wave.outcomes_by_pair_id[pair_id]
        audit_sha256 = _non_empty(outcome.audit_sha256, "unknown settlement audit SHA-256")
        persisted = _load_resolved_reconciliation(
            policy=policy,
            pair_id=pair_id,
            source_wave_index=wave.wave_index,
            source_outcome_audit_sha256=audit_sha256,
            maximum_attempts_per_dispatch=maximum_attempts_per_dispatch,
        )
        if persisted is not None:
            terminal, persisted_charge = persisted
            reconciliation_charge += persisted_charge
            results[pair_id] = _WorkerResult(
                pair_id=pair_id,
                terminal_row=terminal.terminal_row,
                variant_evidence=terminal.variant_evidence,
            )
            continue
        reconciliation_identity = _sha256_json(
            {
                "policy_identity_hash": policy.identity_hash,
                "pair_id": pair_id,
                "source_wave_index": wave.wave_index,
                "source_outcome_audit_sha256": audit_sha256,
                "slot": 1,
            }
        )
        relative_root = Path("reconciliation-settlements") / reconciliation_identity[:24]
        if not policy.consume_reconciliation_slot(
            pair_id=pair_id,
            source_wave_index=wave.wave_index,
            source_outcome_audit_sha256=audit_sha256,
            physical_attempt_count=physical_attempts + reconciliation_charge,
            reconciliation_identity_hash=reconciliation_identity,
            journal_relative_path=relative_root.as_posix(),
        ):
            return results, reconciliation_charge, (pair_id,), ()
        root = policy.workspace / relative_root
        root.parent.mkdir(exist_ok=True)
        root.mkdir()
        reconciliation = DurablePairSettlement(
            root,
            settlement_identity_hash=reconciliation_identity,
            maximum_attempts_per_dispatch=maximum_attempts_per_dispatch,
            max_concurrency=1,
        )
        dispatch = DurablePairDispatch(
            pair_id=pair_id,
            plan_identity=_typed_settlement_plan_identity(plan),
            execute=lambda adapter, plan=plan: _execute_typed_pair(
                plan=plan,
                adapter=adapter,
                provider_metadata=provider_metadata,
            ),
        )
        reconciled = reconciliation.settle_wave(
            (dispatch,),
            (adapters[outcome.lane_id],),
            physical_reservation=maximum_attempts_per_dispatch,
        )
        reconciliation_charge += reconciled.physical_attempt_charge
        if reconciled.implementation_failed_pair_ids:
            policy.exhaust(pair_id=pair_id, reason="reconciliation_implementation_failed")
            return (
                results,
                reconciliation_charge,
                (),
                reconciled.implementation_failed_pair_ids,
            )
        if reconciled.unknown_pair_ids or not reconciled.all_pairs_terminal:
            policy.exhaust(pair_id=pair_id, reason="second_provenance_unknown")
            return results, reconciliation_charge, (pair_id,), ()
        terminal = reconciled.terminal_results[pair_id]
        policy.resolve_reconciliation(
            pair_id=pair_id,
            reconciliation_identity_hash=reconciliation_identity,
            journal_sha256=_sha256_file(reconciliation.path),
            terminal_sha256=_sha256_json(
                {
                    "terminal_row": terminal.terminal_row,
                    "variant_evidence": terminal.variant_evidence,
                }
            ),
            physical_attempt_charge=reconciled.physical_attempt_charge,
        )
        results[pair_id] = _WorkerResult(
            pair_id=pair_id,
            terminal_row=terminal.terminal_row,
            variant_evidence=terminal.variant_evidence,
        )
    if set(results) != set(wave.canonical_pair_ids):
        raise ValueError("automated reconciliation did not close every pair in its wave")
    for pair_id in wave.canonical_pair_ids:
        if pair_id in ledger.terminal_pair_ids:
            continue
        result = results[pair_id]
        ledger.append(
            "pair_terminal",
            {
                "pair_id": pair_id,
                "terminal_row": result.terminal_row,
                "variant_evidence": result.variant_evidence,
            },
        )
    return (
        {pair_id: results[pair_id] for pair_id in wave.canonical_pair_ids},
        reconciliation_charge,
        (),
        (),
    )


def _load_resolved_reconciliation(
    *,
    policy: AutomatedRecoveryPolicy,
    pair_id: str,
    source_wave_index: int,
    source_outcome_audit_sha256: str,
    maximum_attempts_per_dispatch: int,
) -> tuple[DurablePairTerminal, int] | None:
    records = policy.replay()
    slots = [
        _mapping(record.get("payload"), "persisted reconciliation slot")
        for record in records
        if record.get("event_type") == "reconciliation_slot_consumed"
        and _mapping(record.get("payload"), "persisted reconciliation slot").get(
            "pair_id"
        )
        == pair_id
    ]
    resolutions = [
        _mapping(record.get("payload"), "persisted reconciliation resolution")
        for record in records
        if record.get("event_type") == "reconciliation_resolved"
        and _mapping(record.get("payload"), "persisted reconciliation resolution").get(
            "pair_id"
        )
        == pair_id
    ]
    if not slots and not resolutions:
        return None
    if len(slots) != 1 or len(resolutions) != 1:
        raise ValueError("persisted reconciliation slot is consumed without exact resolution")
    slot = slots[0]
    resolution = resolutions[0]
    if (
        slot.get("source_wave_index") != source_wave_index
        or slot.get("source_outcome_audit_sha256")
        != source_outcome_audit_sha256
        or resolution.get("reconciliation_identity_hash")
        != slot.get("reconciliation_identity_hash")
    ):
        raise ValueError("persisted reconciliation is crossed with its source unknown")
    relative_root = Path(
        _non_empty(slot.get("journal_relative_path"), "persisted reconciliation path")
    )
    if relative_root.is_absolute() or ".." in relative_root.parts:
        raise ValueError("persisted reconciliation path is unsafe")
    identity_hash = _non_empty(
        slot.get("reconciliation_identity_hash"), "persisted reconciliation identity"
    )
    journal_path = policy.workspace / relative_root / DURABLE_PAIR_SETTLEMENT_JOURNAL_FILE
    if (
        journal_path.is_symlink()
        or not journal_path.is_file()
        or resolution.get("journal_sha256") != _sha256_file(journal_path)
    ):
        raise ValueError("persisted reconciliation journal bytes are crossed")
    reconciliation = DurablePairSettlement(
        journal_path.parent,
        settlement_identity_hash=identity_hash,
        maximum_attempts_per_dispatch=maximum_attempts_per_dispatch,
        max_concurrency=1,
    ).replay()
    if (
        reconciliation.unknown_pair_ids
        or reconciliation.implementation_failed_pair_ids
        or set(reconciliation.terminal_results) != {pair_id}
        or len(reconciliation.waves) != 1
    ):
        raise ValueError("persisted reconciliation does not close one terminal pair")
    terminal = reconciliation.terminal_results[pair_id]
    terminal_sha256 = _sha256_json(
        {
            "terminal_row": terminal.terminal_row,
            "variant_evidence": terminal.variant_evidence,
        }
    )
    if (
        resolution.get("terminal_sha256") != terminal_sha256
        or resolution.get("physical_attempt_charge")
        != reconciliation.physical_attempt_charge
    ):
        raise ValueError("persisted reconciliation terminal or accounting is crossed")
    return terminal, reconciliation.physical_attempt_charge


def _run_automated_runtime(
    *,
    request: AutomatedNestedRecoveryRequest,
    inputs: _ValidatedAutomatedInputs,
    documents: _AutomatedDocuments,
    policy: AutomatedRecoveryPolicy,
    runtime: _AutomatedRuntime,
    adapters: Sequence[LLMDecisionAdapter],
) -> AutomatedNestedRecoveryResult:
    identity_hash = _non_empty(documents.identity.get("identity_hash"), "identity hash")
    maximum_attempts = _non_negative_int(
        _mapping(inputs.payload.get("execution_contract"), "execution contract").get(
            "maximum_attempts_per_dispatch"
        ),
        "maximum attempts per dispatch",
    )
    settlement = DurablePairSettlement(
        request.recovery_workspace,
        settlement_identity_hash=identity_hash,
        maximum_attempts_per_dispatch=maximum_attempts,
        max_concurrency=10,
        legacy_event_sink=runtime.ledger.append,
    )
    base_physical = inputs.historical_physical_attempts + inputs.uncertainty_physical_charge
    pending = runtime.kernel.pending_plans()
    retry_plans = pending[: len(inputs.unresolved_pair_ids)]
    if [plan.pair_id for plan in retry_plans] != list(inputs.unresolved_pair_ids):
        raise ValueError("automated recovery retry plans are crossed with the frozen seven IDs")
    retry_execution = _execute_plans_with_policy(
        plans=retry_plans,
        adapters=adapters,
        settlement=settlement,
        policy=policy,
        ledger=runtime.ledger,
        provider_metadata=inputs.parent_inputs.prefix.provider_contract,
        physical_attempts=base_physical,
        maximum_attempts_per_dispatch=maximum_attempts,
    )
    if retry_execution.stopped:
        return _persist_execution_stop(
            request=request,
            inputs=inputs,
            documents=documents,
            policy=policy,
            retry_physical_attempts=retry_execution.physical_attempt_charge,
            reconciliation_physical_attempts=(
                retry_execution.reconciliation_physical_attempts
            ),
            continuation_physical_attempts=0,
            fresh_logical_count=0,
            cap_stopped=retry_execution.cap_stopped,
            unknown_pair_ids=retry_execution.unknown_pair_ids,
            implementation_failed_pair_ids=(
                retry_execution.implementation_failed_pair_ids
            ),
            cap_blocked_pair_id=(
                _first_unsettled_plan_id(retry_plans, retry_execution.results)
                if retry_execution.cap_stopped
                else None
            ),
        )
    retry_results = {
        plan.pair_id: retry_execution.results[plan.pair_id] for plan in retry_plans
    }
    _register_results(runtime.kernel, retry_plans, retry_results)
    retry_physical = retry_execution.physical_attempt_charge
    reconciliation_physical = retry_execution.reconciliation_physical_attempts
    continuation_physical = 0
    fresh_logical = 0

    remaining_active = runtime.kernel.pending_plans()
    active_execution = _execute_plans_with_policy(
        plans=remaining_active,
        adapters=adapters,
        settlement=settlement,
        policy=policy,
        ledger=runtime.ledger,
        provider_metadata=inputs.parent_inputs.prefix.provider_contract,
        physical_attempts=base_physical + retry_physical + reconciliation_physical,
        maximum_attempts_per_dispatch=maximum_attempts,
    )
    active_results = {
        plan.pair_id: active_execution.results[plan.pair_id]
        for plan in remaining_active[: len(active_execution.results)]
    }
    _register_results(
        runtime.kernel,
        remaining_active[: len(active_results)],
        active_results,
    )
    continuation_physical += active_execution.physical_attempt_charge
    reconciliation_physical += active_execution.reconciliation_physical_attempts
    fresh_logical += len(active_results)
    if active_execution.stopped:
        return _persist_execution_stop(
            request=request,
            inputs=inputs,
            documents=documents,
            policy=policy,
            retry_physical_attempts=retry_physical,
            reconciliation_physical_attempts=reconciliation_physical,
            continuation_physical_attempts=continuation_physical,
            fresh_logical_count=fresh_logical,
            cap_stopped=active_execution.cap_stopped,
            unknown_pair_ids=active_execution.unknown_pair_ids,
            implementation_failed_pair_ids=(
                active_execution.implementation_failed_pair_ids
            ),
            cap_blocked_pair_id=(
                _first_unsettled_plan_id(remaining_active, active_execution.results)
                if active_execution.cap_stopped
                else None
            ),
        )
    runtime.kernel.commit_primary_batch()

    while runtime.state.next_time_step < inputs.parent_inputs.config.horizon:
        if runtime.kernel.active_batch is None:
            runtime.kernel.plan_batch()
        plans = runtime.kernel.pending_plans()
        execution = _execute_plans_with_policy(
            plans=plans,
            adapters=adapters,
            settlement=settlement,
            policy=policy,
            ledger=runtime.ledger,
            provider_metadata=inputs.parent_inputs.prefix.provider_contract,
            physical_attempts=(
                base_physical
                + retry_physical
                + reconciliation_physical
                + continuation_physical
            ),
            maximum_attempts_per_dispatch=maximum_attempts,
        )
        results = {
            plan.pair_id: execution.results[plan.pair_id]
            for plan in plans[: len(execution.results)]
        }
        _register_results(runtime.kernel, plans[: len(results)], results)
        continuation_physical += execution.physical_attempt_charge
        reconciliation_physical += execution.reconciliation_physical_attempts
        fresh_logical += len(results)
        if execution.stopped:
            return _persist_execution_stop(
                request=request,
                inputs=inputs,
                documents=documents,
                policy=policy,
                retry_physical_attempts=retry_physical,
                reconciliation_physical_attempts=reconciliation_physical,
                continuation_physical_attempts=continuation_physical,
                fresh_logical_count=fresh_logical,
                cap_stopped=execution.cap_stopped,
                unknown_pair_ids=execution.unknown_pair_ids,
                implementation_failed_pair_ids=execution.implementation_failed_pair_ids,
                cap_blocked_pair_id=(
                    _first_unsettled_plan_id(plans, execution.results)
                    if execution.cap_stopped
                    else None
                ),
            )
        runtime.kernel.commit_primary_batch()

    return _complete_automated_runtime(
        request=request,
        inputs=inputs,
        documents=documents,
        policy=policy,
        runtime=runtime,
        settlement=settlement,
        reconciliation_physical_attempts=reconciliation_physical,
        record_policy_completion=True,
        expected_retry_charge=retry_physical,
        expected_continuation_charge=continuation_physical,
        expected_fresh_logical_count=fresh_logical,
    )


def _resolved_reconciliation_physical_attempts(
    policy: AutomatedRecoveryPolicy,
) -> int:
    return sum(
        _non_negative_int(
            _mapping(record.get("payload"), "resolved reconciliation payload").get(
                "physical_attempt_charge"
            ),
            "resolved reconciliation physical attempt charge",
        )
        for record in policy.replay()
        if record.get("event_type") == "reconciliation_resolved"
    )


def _complete_automated_runtime(
    *,
    request: AutomatedNestedRecoveryRequest,
    inputs: _ValidatedAutomatedInputs,
    documents: _AutomatedDocuments,
    policy: AutomatedRecoveryPolicy,
    runtime: _AutomatedRuntime,
    settlement: DurablePairSettlement,
    reconciliation_physical_attempts: int,
    record_policy_completion: bool,
    expected_retry_charge: int | None = None,
    expected_continuation_charge: int | None = None,
    expected_fresh_logical_count: int | None = None,
) -> AutomatedNestedRecoveryResult:
    (
        retry_actual,
        retry_uncertain,
        continuation_actual,
        continuation_uncertain,
        fresh_logical,
    ) = _main_settlement_detailed_accounting(request, inputs, documents)
    retry_charge = retry_actual + retry_uncertain
    continuation_charge = continuation_actual + continuation_uncertain
    if (
        (expected_retry_charge is not None and expected_retry_charge != retry_charge)
        or (
            expected_continuation_charge is not None
            and expected_continuation_charge != continuation_charge
        )
        or (
            expected_fresh_logical_count is not None
            and expected_fresh_logical_count != fresh_logical
        )
    ):
        raise ValueError("automated recovery settlement accounting is crossed")
    logical_count = inputs.historical_logical_count + fresh_logical
    new_uncertainty = retry_uncertain + continuation_uncertain
    physical_count = (
        inputs.historical_physical_attempts
        + inputs.uncertainty_physical_charge
        + new_uncertainty
        + retry_actual
        + reconciliation_physical_attempts
        + continuation_actual
    )
    if (
        logical_count != inputs.expected_logical_count
        or inputs.imported_durable_terminal_count
        + len(inputs.unresolved_pair_ids)
        + fresh_logical
        != inputs.expected_logical_count
        or runtime.state.next_time_step != inputs.parent_inputs.config.horizon
        or runtime.kernel.active_batch is not None
    ):
        raise ValueError("automated recovery did not close the full logical or batch denominator")
    if record_policy_completion:
        policy.complete(logical_count=logical_count, physical_attempt_count=physical_count)
    else:
        completions = [
            _mapping(record.get("payload"), "policy completion payload")
            for record in policy.replay()
            if record.get("event_type") == "policy_completed"
        ]
        if len(completions) != 1 or completions[0] != {
            "logical_count": logical_count,
            "physical_attempt_count": physical_count,
        }:
            raise ValueError("persisted policy completion is crossed with settlement accounting")
    accounting = _recovery_accounting(
        inputs,
        logical_count=logical_count,
        retry_physical_attempts=retry_actual,
        reconciliation_physical_attempts=reconciliation_physical_attempts,
        continuation_physical_attempts=continuation_actual,
        new_uncertainty_physical_charge=new_uncertainty,
    )
    existing_source = request.recovery_workspace / "source-v3"
    if not record_policy_completion and not existing_source.exists():
        _discard_incomplete_source_v3_projection(request.recovery_workspace)
    if existing_source.exists() or existing_source.is_symlink():
        if existing_source.is_symlink() or not existing_source.is_dir():
            raise ValueError("persisted source-v3 is unsafe")
        source_root = existing_source
        source_manifest_sha256 = _sha256_file(existing_source / "manifest.json")
    else:
        source_root, source_manifest_sha256 = _SourceV3Closure().close(
            request=request,
            inputs=inputs,
            documents=documents,
            runtime=runtime,
            settlement=settlement,
            accounting=accounting,
        )
    result = AutomatedNestedRecoveryResult(
        status="complete",
        workspace_root=request.recovery_workspace,
        recovery_identity_hash=_non_empty(documents.identity.get("identity_hash"), "identity hash"),
        source_root=source_root,
        source_manifest_sha256=source_manifest_sha256,
        logical_count=logical_count,
        imported_durable_terminal_count=inputs.imported_durable_terminal_count,
        fresh_logical_count=fresh_logical,
        historical_physical_attempts=inputs.historical_physical_attempts,
        uncertainty_physical_charge=inputs.uncertainty_physical_charge,
        new_uncertainty_physical_charge=new_uncertainty,
        retry_physical_attempts=retry_actual,
        reconciliation_physical_attempts=reconciliation_physical_attempts,
        continuation_physical_attempts=continuation_actual,
        physical_attempt_count=physical_count,
        recovered_pair_ids=inputs.unresolved_pair_ids,
        unknown_pair_ids=(),
        implementation_failed_pair_ids=(),
        automation_exhausted_pair_ids=(),
        provider_calls=0,
        production_deploy_eligible=False,
    )
    _validate_complete_source_v3(result, inputs, documents)
    _write_status(request.recovery_workspace, result)
    return result


def _discard_incomplete_source_v3_projection(workspace: Path) -> None:
    for path in (
        workspace / ".source-v3.staging",
        workspace / ".source-v3.building",
    ):
        if not path.exists() and not path.is_symlink():
            continue
        if path.is_symlink() or not path.is_dir():
            raise ValueError("incomplete source-v3 projection path is unsafe")
        shutil.rmtree(path)
    _fsync_directory(workspace)


def _first_unsettled_plan_id(
    plans: Sequence[_PairExecutionPlan],
    results: Mapping[str, _WorkerResult],
) -> str:
    for plan in plans:
        if plan.pair_id not in results:
            return plan.pair_id
    raise ValueError("cap stop lacks an unsettled canonical pair")


def _persist_execution_stop(
    *,
    request: AutomatedNestedRecoveryRequest,
    inputs: _ValidatedAutomatedInputs,
    documents: _AutomatedDocuments,
    policy: AutomatedRecoveryPolicy,
    retry_physical_attempts: int,
    reconciliation_physical_attempts: int,
    continuation_physical_attempts: int,
    fresh_logical_count: int,
    cap_stopped: bool,
    unknown_pair_ids: Sequence[str],
    implementation_failed_pair_ids: Sequence[str],
    cap_blocked_pair_id: str | None,
) -> AutomatedNestedRecoveryResult:
    implementation_failed = tuple(implementation_failed_pair_ids)
    unknown = tuple(unknown_pair_ids)
    status: Literal["automation_exhausted", "implementation_failed"] = (
        "implementation_failed" if implementation_failed else "automation_exhausted"
    )
    if not implementation_failed and not unknown and not cap_stopped:
        raise ValueError("automated recovery stop lacks a typed failure or cap reason")
    exhausted_pair_id = unknown[0] if unknown else cap_blocked_pair_id
    if status == "automation_exhausted":
        if exhausted_pair_id is None:
            raise ValueError("automation exhausted stop lacks its blocked pair")
        policy.exhaust(
            pair_id=exhausted_pair_id,
            reason=(
                "physical_cap_insufficient"
                if cap_stopped
                else "second_provenance_unknown"
            ),
        )
    (
        retry_actual,
        retry_uncertain,
        continuation_actual,
        continuation_uncertain,
        replayed_fresh_logical,
    ) = _main_settlement_detailed_accounting(request, inputs, documents)
    if (
        retry_actual + retry_uncertain != retry_physical_attempts
        or continuation_actual + continuation_uncertain
        != continuation_physical_attempts
        or replayed_fresh_logical != fresh_logical_count
    ):
        raise ValueError("stopped automated recovery accounting is crossed")
    new_uncertainty = retry_uncertain + continuation_uncertain
    physical = (
        inputs.historical_physical_attempts
        + inputs.uncertainty_physical_charge
        + new_uncertainty
        + retry_actual
        + reconciliation_physical_attempts
        + continuation_actual
    )
    result = AutomatedNestedRecoveryResult(
        status=status,
        workspace_root=request.recovery_workspace,
        recovery_identity_hash=_non_empty(documents.identity.get("identity_hash"), "identity hash"),
        logical_count=inputs.historical_logical_count + fresh_logical_count,
        imported_durable_terminal_count=inputs.imported_durable_terminal_count,
        fresh_logical_count=fresh_logical_count,
        historical_physical_attempts=inputs.historical_physical_attempts,
        uncertainty_physical_charge=inputs.uncertainty_physical_charge,
        new_uncertainty_physical_charge=new_uncertainty,
        retry_physical_attempts=retry_actual,
        reconciliation_physical_attempts=reconciliation_physical_attempts,
        continuation_physical_attempts=continuation_actual,
        physical_attempt_count=physical,
        recovered_pair_ids=(),
        unknown_pair_ids=unknown,
        implementation_failed_pair_ids=implementation_failed,
        automation_exhausted_pair_ids=(
            (cast(str, exhausted_pair_id),)
            if status == "automation_exhausted"
            else ()
        ),
        provider_calls=0,
        production_deploy_eligible=False,
    )
    _write_status(request.recovery_workspace, result)
    return result


def _recovery_accounting(
    inputs: _ValidatedAutomatedInputs,
    *,
    logical_count: int,
    retry_physical_attempts: int,
    reconciliation_physical_attempts: int,
    continuation_physical_attempts: int,
    new_uncertainty_physical_charge: int,
) -> dict[str, object]:
    physical = (
        inputs.historical_physical_attempts
        + inputs.uncertainty_physical_charge
        + new_uncertainty_physical_charge
        + retry_physical_attempts
        + reconciliation_physical_attempts
        + continuation_physical_attempts
    )
    return {
        "schema_version": "full-pool-segmented-automated-recovery-accounting-v3",
        "logical_cap": inputs.expected_logical_count,
        "logical_count": logical_count,
        "historical_logical_count": inputs.historical_logical_count,
        "logical_retry_charge": 0,
        "fresh_logical_count": logical_count - inputs.historical_logical_count,
        "physical_cap": _mapping(inputs.payload.get("accounting"), "accounting")[
            "physical_cap"
        ],
        "historical_physical_attempts": inputs.historical_physical_attempts,
        "historical_uncertainty_physical_charge": inputs.uncertainty_physical_charge,
        "new_uncertainty_physical_charge": new_uncertainty_physical_charge,
        "retry_physical_attempts": retry_physical_attempts,
        "reconciliation_physical_attempts": reconciliation_physical_attempts,
        "continuation_physical_attempts": continuation_physical_attempts,
        "physical_attempt_count": physical,
    }


class _SourceV3LedgerProjection:
    def __init__(self) -> None:
        self.prepared: dict[str, object] | None = None

    def append(self, event_type: str, payload: Mapping[str, object]) -> None:
        if event_type != "source_v2_prepared" or self.prepared is not None:
            raise ValueError("source-v3 projection received an unexpected source-v2 event")
        self.prepared = dict(payload)


class _SourceV3Closure:
    def close(
        self,
        *,
        request: AutomatedNestedRecoveryRequest,
        inputs: _ValidatedAutomatedInputs,
        documents: _AutomatedDocuments,
        runtime: _AutomatedRuntime,
        settlement: DurablePairSettlement,
        accounting: Mapping[str, object],
    ) -> tuple[Path, str]:
        workspace = request.recovery_workspace
        source_v3 = workspace / "source-v3"
        staging = workspace / ".source-v3.staging"
        building = workspace / ".source-v3.building"
        if any(path.exists() or path.is_symlink() for path in (source_v3, staging, building)):
            raise FileExistsError("segmented source-v3 target already exists")
        building.mkdir()
        projection = _SourceV3LedgerProjection()
        source_v2, _old_manifest_sha256, _old_status = _close_segmented_source_v2(
            continuation=building,
            prefix=inputs.parent_inputs.prefix,
            continuation_spool=runtime.spool,
            continuation_replay=runtime.journal.replay(),
            config=inputs.parent_inputs.config,
            logical_count=inputs.expected_logical_count,
            physical_attempt_count=_non_negative_int(
                accounting.get("physical_attempt_count"), "source-v3 physical count"
            ),
            cutoff_manifest_sha256=request.nested_recovery_plan_sha256,
            continuation_identity_hash=_non_empty(
                documents.identity.get("identity_hash"), "identity hash"
            ),
            qualification_artifact=inputs.parent_inputs.qualification_artifact,
            ledger=cast(_ContinuationLedger, projection),
            historical_chunks=(),
            recovery_retry_pair_ids=inputs.unresolved_pair_ids,
            recovery_lineage={
                "nested_recovery_plan_sha256": request.nested_recovery_plan_sha256
            },
            recovery_accounting=accounting,
        )
        os.replace(source_v2, staging)
        building.rmdir()
        _fsync_directory(workspace)
        copied = {
            "nested-recovery-plan.json": request.nested_recovery_plan_path,
            "automated-recovery-policy.json": workspace / AUTOMATED_RECOVERY_POLICY_FILE,
            "automated-recovery-policy-ledger.jsonl": workspace
            / AUTOMATED_RECOVERY_POLICY_LEDGER_FILE,
            "durable-pair-settlement-v2.jsonl": settlement.path,
        }
        reconciliation_entries: list[dict[str, object]] = []
        policy_records = AutomatedRecoveryPolicy(
            workspace,
            identity_hash=_non_empty(documents.identity.get("identity_hash"), "identity hash"),
            expected_payload=documents.policy,
        ).replay()
        resolved_by_pair = {
            _non_empty(_mapping(record.get("payload"), "resolved payload").get("pair_id"), "resolved pair id"):
            _mapping(record.get("payload"), "resolved payload")
            for record in policy_records
            if record.get("event_type") == "reconciliation_resolved"
        }
        for record in policy_records:
            if record.get("event_type") != "reconciliation_slot_consumed":
                continue
            slot = _mapping(record.get("payload"), "reconciliation slot payload")
            pair_id = _non_empty(slot.get("pair_id"), "reconciliation pair id")
            relative_root = Path(
                _non_empty(slot.get("journal_relative_path"), "reconciliation journal path")
            )
            if relative_root.is_absolute() or ".." in relative_root.parts:
                raise ValueError("reconciliation journal path is unsafe")
            journal = workspace / relative_root / DURABLE_PAIR_SETTLEMENT_JOURNAL_FILE
            resolved = resolved_by_pair.get(pair_id)
            if resolved is None or resolved.get("journal_sha256") != _sha256_file(journal):
                raise ValueError("reconciliation journal is not closed by policy evidence")
            target_name = (
                Path("reconciliation-settlements")
                / relative_root.name
                / "durable-pair-settlement-v2.jsonl"
            ).as_posix()
            copied[target_name] = journal
            reconciliation_entries.append(
                {
                    "pair_id": pair_id,
                    "reconciliation_identity_hash": slot["reconciliation_identity_hash"],
                    "relative_path": target_name,
                    "sha256": resolved["journal_sha256"],
                    "physical_attempt_charge": resolved["physical_attempt_charge"],
                }
            )
        for name, source in copied.items():
            _copy_file_durable(source, staging / name)
        manifest_path = staging / "manifest.json"
        manifest = _read_json(manifest_path)
        complete_status = _mapping(manifest.get("complete_status"), "source-v3 complete status")
        complete_status.update(
            {
                "terminal_rows_relative_path": "source-v3/terminal_rows.jsonl",
                "source_root_relative_path": "source-v3",
            }
        )
        manifest["schema_version"] = "full-pool-segmented-source-v3"
        manifest["complete_status"] = complete_status
        manifest.pop("recovery_lineage", None)
        manifest["nested_recovery_lineage"] = {
            "schema_version": "full-pool-segmented-nested-recovery-lineage-v3",
            "nested_recovery_plan_sha256": request.nested_recovery_plan_sha256,
            "nested_recovery_identity_hash": _mapping(
                inputs.payload.get("recovery_identity"), "nested recovery identity"
            )["identity_hash"],
            "parent_recovery_lineage": _mapping(
                inputs.payload.get("parent_recovery_lineage"), "parent recovery lineage"
            ),
            "imported_durable_terminal_count": inputs.imported_durable_terminal_count,
            "ordered_retry_pair_ids": list(inputs.unresolved_pair_ids),
        }
        replay = settlement.replay()
        manifest["settlement_v2"] = {
            "schema_version": settlement_module.DURABLE_PAIR_SETTLEMENT_SCHEMA,
            "journal_sha256": _sha256_file(settlement.path),
            "wave_count": len(replay.waves),
            "dispatched_pair_count": len(replay.dispatched_pair_ids),
            "terminal_pair_count": len(replay.terminal_results),
            "unknown_pair_ids": list(replay.unknown_pair_ids),
            "implementation_failed_pair_ids": list(replay.implementation_failed_pair_ids),
            "reconciliation_journals": reconciliation_entries,
        }
        manifest["automated_recovery_policy"] = {
            "policy_sha256": _sha256_file(workspace / AUTOMATED_RECOVERY_POLICY_FILE),
            "policy_ledger_sha256": _sha256_file(
                workspace / AUTOMATED_RECOVERY_POLICY_LEDGER_FILE
            ),
            "policy_identity_hash": documents.identity["identity_hash"],
        }
        manifest["recovery_accounting"] = dict(accounting)
        existing_artifacts = _mapping_sequence(manifest.get("artifacts"), "source-v3 artifacts")
        existing_artifacts.extend(_artifact_ref(staging, staging / name) for name in copied)
        manifest["artifacts"] = existing_artifacts
        _replace_json(manifest_path, manifest)
        manifest_sha256 = _sha256_file(manifest_path)
        os.replace(staging, source_v3)
        _fsync_directory(workspace)
        runtime.ledger.append(
            "source_v3_prepared",
            {
                "source_manifest_sha256": manifest_sha256,
                "logical_count": inputs.expected_logical_count,
                "complete_status": complete_status,
            },
        )
        return source_v3, manifest_sha256


def _close_unsettled_consumed_slot(
    *,
    request: AutomatedNestedRecoveryRequest,
    inputs: _ValidatedAutomatedInputs,
    documents: _AutomatedDocuments,
    policy: AutomatedRecoveryPolicy,
) -> AutomatedNestedRecoveryResult | None:
    records = policy.replay()
    resolved_pairs = {
        _non_empty(
            _mapping(record.get("payload"), "resolved reconciliation payload").get(
                "pair_id"
            ),
            "resolved reconciliation pair id",
        )
        for record in records
        if record.get("event_type") == "reconciliation_resolved"
    }
    pending = [
        _mapping(record.get("payload"), "consumed reconciliation slot payload")
        for record in records
        if record.get("event_type") == "reconciliation_slot_consumed"
        and _mapping(record.get("payload"), "consumed reconciliation slot payload").get(
            "pair_id"
        )
        not in resolved_pairs
    ]
    if not pending:
        return None
    slot = pending[0]
    pair_id = _non_empty(slot.get("pair_id"), "pending reconciliation pair id")
    relative_root = Path(
        _non_empty(slot.get("journal_relative_path"), "pending reconciliation journal path")
    )
    if relative_root.is_absolute() or ".." in relative_root.parts:
        raise ValueError("pending reconciliation journal path is unsafe")
    journal_path = (
        request.recovery_workspace / relative_root / DURABLE_PAIR_SETTLEMENT_JOURNAL_FILE
    )
    reconciliation_actual = 0
    reconciliation_uncertain = _non_negative_int(
        slot.get("physical_reservation"), "pending reconciliation reservation"
    )
    if journal_path.is_file() and not journal_path.is_symlink():
        reconciliation_identity = _non_empty(
            slot.get("reconciliation_identity_hash"), "reconciliation identity hash"
        )
        reconciliation = DurablePairSettlement(
            journal_path.parent,
            settlement_identity_hash=reconciliation_identity,
            maximum_attempts_per_dispatch=_non_negative_int(
                _mapping(inputs.payload.get("execution_contract"), "execution contract").get(
                    "maximum_attempts_per_dispatch"
                ),
                "maximum attempts per dispatch",
            ),
            max_concurrency=1,
        )
        replay = reconciliation.replay(seal_inflight=True)
        reconciliation_actual = replay.actual_physical_attempts
        reconciliation_uncertain = replay.uncertain_physical_attempts
        if (
            not replay.unknown_pair_ids
            and not replay.implementation_failed_pair_ids
            and pair_id in replay.terminal_results
        ):
            terminal = replay.terminal_results[pair_id]
            policy.resolve_reconciliation(
                pair_id=pair_id,
                reconciliation_identity_hash=reconciliation_identity,
                journal_sha256=_sha256_file(journal_path),
                terminal_sha256=_sha256_json(
                    {
                        "terminal_row": terminal.terminal_row,
                        "variant_evidence": terminal.variant_evidence,
                    }
                ),
                physical_attempt_charge=(
                    reconciliation_actual + reconciliation_uncertain
                ),
            )
            return None
    policy.exhaust(pair_id=pair_id, reason="reconciliation_dispatch_without_settlement")
    (
        retry_actual,
        retry_uncertain,
        continuation_actual,
        continuation_uncertain,
        fresh_logical,
    ) = _main_settlement_detailed_accounting(request, inputs, documents)
    new_uncertainty = (
        retry_uncertain + continuation_uncertain + reconciliation_uncertain
    )
    physical = (
        inputs.historical_physical_attempts
        + inputs.uncertainty_physical_charge
        + new_uncertainty
        + retry_actual
        + reconciliation_actual
        + continuation_actual
    )
    result = AutomatedNestedRecoveryResult(
        status="automation_exhausted",
        workspace_root=request.recovery_workspace,
        recovery_identity_hash=_non_empty(documents.identity.get("identity_hash"), "identity hash"),
        logical_count=inputs.historical_logical_count + fresh_logical,
        imported_durable_terminal_count=inputs.imported_durable_terminal_count,
        fresh_logical_count=fresh_logical,
        historical_physical_attempts=inputs.historical_physical_attempts,
        uncertainty_physical_charge=inputs.uncertainty_physical_charge,
        new_uncertainty_physical_charge=new_uncertainty,
        retry_physical_attempts=retry_actual,
        reconciliation_physical_attempts=reconciliation_actual,
        continuation_physical_attempts=continuation_actual,
        physical_attempt_count=physical,
        recovered_pair_ids=(),
        unknown_pair_ids=(pair_id,),
        implementation_failed_pair_ids=(),
        automation_exhausted_pair_ids=(pair_id,),
        provider_calls=0,
        production_deploy_eligible=False,
    )
    _write_status(request.recovery_workspace, result)
    return result


def _main_settlement_detailed_accounting(
    request: AutomatedNestedRecoveryRequest,
    inputs: _ValidatedAutomatedInputs,
    documents: _AutomatedDocuments,
) -> tuple[int, int, int, int, int]:
    path = request.recovery_workspace / settlement_module.DURABLE_PAIR_SETTLEMENT_JOURNAL_FILE
    if not path.is_file() or path.is_symlink():
        return 0, 0, 0, 0, 0
    replay = DurablePairSettlement(
        request.recovery_workspace,
        settlement_identity_hash=_non_empty(documents.identity.get("identity_hash"), "identity hash"),
        maximum_attempts_per_dispatch=_non_negative_int(
            _mapping(inputs.payload.get("execution_contract"), "execution contract").get(
                "maximum_attempts_per_dispatch"
            ),
            "maximum attempts per dispatch",
        ),
        max_concurrency=10,
    ).replay(seal_inflight=True)
    retry_ids = set(inputs.unresolved_pair_ids)
    retry_actual = 0
    retry_uncertain = 0
    continuation_actual = 0
    continuation_uncertain = 0
    fresh_ids: set[str] = set()
    for wave in replay.waves:
        for outcome in wave.outcomes:
            if outcome.pair_id in retry_ids:
                retry_actual += outcome.accounting.actual_physical_attempts
                retry_uncertain += outcome.accounting.uncertain_physical_attempts
            else:
                continuation_actual += outcome.accounting.actual_physical_attempts
                continuation_uncertain += outcome.accounting.uncertain_physical_attempts
                fresh_ids.add(outcome.pair_id)
    return (
        retry_actual,
        retry_uncertain,
        continuation_actual,
        continuation_uncertain,
        len(fresh_ids),
    )


def _load_automated_runtime(
    request: AutomatedNestedRecoveryRequest,
    inputs: _ValidatedAutomatedInputs,
    documents: _AutomatedDocuments,
) -> _AutomatedRuntime:
    workspace = request.recovery_workspace
    identity_hash = _non_empty(documents.identity.get("identity_hash"), "identity hash")
    run_id = _non_empty(documents.identity.get("run_id"), "automated recovery run id")
    ledger_path = workspace / "segmented_continuation_ledger.jsonl"
    ledger_bytes = ledger_path.read_bytes()
    ledger_lines = [line for line in ledger_bytes.splitlines(keepends=True) if line.strip()]
    ledger_rows = [
        _mapping(json.loads(line), "automated recovery ledger row")
        for line in ledger_lines
    ]
    source_v3_rows = [
        row for row in ledger_rows if row.get("event_type") == "source_v3_prepared"
    ]
    if source_v3_rows and (
        len(source_v3_rows) != 1 or ledger_rows[-1] is not source_v3_rows[0]
    ):
        raise ValueError("automated recovery source-v3 anchor is duplicated or reordered")
    replay_bytes = (
        b"".join(ledger_lines[:-1]) if source_v3_rows else ledger_bytes
    )
    dispatched, durable, _physical, source_anchor = _replay_continuation_ledger(
        ledger_path,
        expected_identity_hash=identity_hash,
        snapshot_bytes=replay_bytes,
        allow_inflight_wave=True,
    )
    if source_anchor is not None:
        raise ValueError("inflight automated recovery unexpectedly exposes source-v2")
    if source_v3_rows:
        anchor = _mapping(source_v3_rows[0].get("payload"), "source-v3 anchor payload")
        manifest_path = workspace / "source-v3" / "manifest.json"
        if (
            anchor.get("source_manifest_sha256") != _sha256_file(manifest_path)
            or anchor.get("logical_count") != inputs.expected_logical_count
        ):
            raise ValueError("automated recovery source-v3 anchor is crossed")
    records: list[dict[str, object]] = []
    for row in ledger_rows:
        event_type = row.get("event_type")
        payload = _mapping(row.get("payload"), "automated recovery ledger payload")
        if event_type == "kernel_batch_snapshot":
            relative = Path(
                _non_empty(payload.get("snapshot_path"), "kernel snapshot relative path")
            )
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("kernel snapshot path is unsafe")
            document = _read_json(workspace / relative)
            if _sha256_json(document) != payload.get("snapshot_hash"):
                raise ValueError("kernel snapshot bytes are crossed with the ledger")
            records.append(
                {
                    "record_type": "snapshot",
                    **payload,
                    "snapshot_document": document,
                }
            )
        elif event_type == "kernel_runtime_event":
            records.append(_mapping(payload.get("record"), "kernel runtime record"))
        elif event_type == "kernel_batch_committed":
            records.append(
                {
                    "record_type": "event",
                    "sequence": len(records) + 1,
                    "event_type": "batch_committed",
                    "event_identity": payload.get("event_identity"),
                    "batch_snapshot_hash": payload.get("batch_snapshot_hash"),
                    "payload": payload.get("payload"),
                }
            )
    ledger = _ContinuationLedger(workspace, continuation_identity_hash=identity_hash)
    ledger.sequence = len(ledger_rows)
    ledger.previous_checksum = (
        _non_empty(ledger_rows[-1].get("checksum"), "automated recovery ledger checksum")
        if ledger_rows
        else None
    )
    ledger.terminal_pair_ids = set(durable)
    journal = _SegmentedKernelJournal(
        workspace,
        run_id=run_id,
        identity_hash=identity_hash,
        ledger=ledger,
        base_time_step=0,
        record_runtime_events=True,
    )
    journal.records = records
    spool = _ConcurrentRuntimeBatchSpool(
        workspace,
        run_id=run_id,
        identity_hash=identity_hash,
        terminal_variants=("primary",),
        base_time_step=0,
    )
    committed_count = sum(
        record.get("record_type") == "event"
        and record.get("event_type") == "batch_committed"
        for record in records
    )
    runtime_replay = {
        "status": {"committed_batch_count": committed_count},
        "records": records,
    }
    committed_chunks = tuple(spool.iter_committed(runtime_replay))
    active_snapshot = next(
        (
            _mapping(record.get("snapshot_document"), "active replay snapshot")
            for record in records
            if record.get("record_type") == "snapshot"
            and _mapping(
                _mapping(record.get("snapshot_document"), "snapshot document").get(
                    "snapshot_identity"
                ),
                "snapshot identity",
            ).get("time_step")
            == committed_count
        ),
        None,
    )
    prepared = inputs.parent_inputs.prepared
    config = inputs.parent_inputs.config
    if active_snapshot is None and committed_count != config.horizon:
        raise ValueError("inflight automated recovery active snapshot is missing")
    if active_snapshot is not None and committed_count >= config.horizon:
        raise ValueError("completed automated recovery exposes an extra active snapshot")
    state = _ConcurrentRuntimeKernelState(
        cohort=prepared.cohort,
        exposed_by_message={message.message_id: set() for message in config.messages},
        campaign_engaged_user_ids=set(),
    )
    replay_journal: ConcurrentExecutionJournal
    if active_snapshot is None:
        replay_journal = cast(ConcurrentExecutionJournal, journal)
    else:
        replay_journal = cast(
            ConcurrentExecutionJournal,
            _ReplayPlanningJournal(
                workspace=workspace,
                run_id=run_id,
                identity_hash=identity_hash,
                expected_snapshot=active_snapshot,
            ),
        )
    kernel = _ConcurrentRuntimeKernel.primary_only(
        config=config,
        state=state,
        base_network_by_user=prepared.base_network_by_user,
        neighbors_by_user=prepared.neighbors_by_user,
        journal=replay_journal,
        spool_base_time_step=0,
    )
    for chunk in committed_chunks:
        kernel._restore_spooled_chunk(chunk)
    if active_snapshot is not None:
        kernel.plan_batch()
        active_hash = _sha256_json(active_snapshot)
        terminal_by_pair: dict[str, tuple[dict[str, object], dict[str, object]]] = {}
        closed_pairs: set[str] = set()
        for record in records:
            if record.get("record_type") != "event" or record.get(
                "batch_snapshot_hash"
            ) != active_hash:
                continue
            event_type = record.get("event_type")
            identity = _mapping(record.get("event_identity"), "active runtime event identity")
            pair_id = _non_empty(identity.get("pair_id"), "active runtime pair id")
            if event_type == "variant_terminal":
                payload = _mapping(record.get("payload"), "active terminal event payload")
                terminal_by_pair[pair_id] = (
                    _mapping(payload.get("terminal_row"), "active replay terminal row"),
                    _mapping(payload.get("variant_evidence"), "active replay variant evidence"),
                )
            elif event_type == "pair_closed":
                closed_pairs.add(pair_id)
        for plan in kernel.pending_plans():
            evidence = terminal_by_pair.get(plan.pair_id)
            if evidence is None:
                break
            if plan.pair_id not in closed_pairs:
                raise ValueError("active replay terminal lacks its pair closure")
            terminal_row, variant_evidence = evidence
            kernel.start_pair(plan)
            kernel.register_terminal(
                plan=plan,
                decision_variant="primary",
                terminal_row=terminal_row,
                variant_evidence=variant_evidence,
            )
            kernel.close_primary_pair(
                plan,
                _PrimaryOnlyConcurrentRuntimeConsumer._primary_result_row(
                    plan, terminal_row
                ),
            )
        if any(
            pair_id not in {plan.pair_id for plan in kernel.pending_plans()}
            for pair_id in set(terminal_by_pair).difference(closed_pairs)
        ):
            raise ValueError("active replay terminal ordering is crossed")
        kernel.journal = cast(ConcurrentExecutionJournal, journal)
    if set(dispatched).difference(settled_pair_ids := set(durable)) and not (
        workspace / settlement_module.DURABLE_PAIR_SETTLEMENT_JOURNAL_FILE
    ).is_file():
        raise ValueError("automated recovery ledger dispatches lack settlement evidence")
    del settled_pair_ids
    return _AutomatedRuntime(
        ledger=ledger,
        journal=journal,
        spool=spool,
        kernel=kernel,
        state=state,
    )


def _load_existing_status(
    request: AutomatedNestedRecoveryRequest,
    inputs: _ValidatedAutomatedInputs,
    documents: _AutomatedDocuments,
) -> AutomatedNestedRecoveryResult | None:
    workspace = request.recovery_workspace
    if workspace.is_symlink() or not workspace.is_dir():
        raise ValueError("automated recovery workspace must be one real directory")
    identity_path = workspace / AUTOMATED_RECOVERY_IDENTITY_FILE
    if identity_path.is_symlink() or not identity_path.is_file():
        raise ValueError("automated recovery workspace identity is missing")
    if _read_json(identity_path) != documents.identity:
        raise ValueError("automated recovery workspace identity or implementation drifted")
    policy = AutomatedRecoveryPolicy(
        workspace,
        identity_hash=_non_empty(documents.identity.get("identity_hash"), "identity hash"),
        expected_payload=documents.policy,
    )
    policy.create_or_validate()
    status_path = workspace / AUTOMATED_RECOVERY_STATUS_FILE
    if not status_path.exists():
        exhausted = _close_unsettled_consumed_slot(
            request=request,
            inputs=inputs,
            documents=documents,
            policy=policy,
        )
        if exhausted is not None:
            return exhausted
        return None
    if status_path.is_symlink() or not status_path.is_file():
        raise ValueError("automated recovery status is unsafe")
    document = _read_json(status_path)
    if set(document) != {"schema_version", "result"} or document.get(
        "schema_version"
    ) != _AUTOMATED_STATUS_SCHEMA:
        raise ValueError("automated recovery status document is not exact")
    result = AutomatedNestedRecoveryResult.model_validate(document.get("result"))
    if (
        result.workspace_root != workspace
        or result.recovery_identity_hash != documents.identity.get("identity_hash")
    ):
        raise ValueError("automated recovery status is crossed with its identity")
    if result.status == "complete":
        _validate_complete_source_v3(result, inputs, documents)
    elif any(
        path.exists() or path.is_symlink()
        for path in (
            workspace / "source-v3",
            workspace / ".source-v3.staging",
            workspace / ".source-v3.building",
        )
    ):
        raise ValueError("non-complete automated recovery exposes source-v3 bytes")
    return result


def _validate_complete_source_v3(
    result: AutomatedNestedRecoveryResult,
    inputs: _ValidatedAutomatedInputs,
    documents: _AutomatedDocuments,
) -> None:
    source = cast(Path, result.source_root)
    if source.is_symlink() or not source.is_dir() or source != result.workspace_root / "source-v3":
        raise ValueError("automated recovery source-v3 root is crossed or unsafe")
    manifest_path = source / "manifest.json"
    if (
        manifest_path.is_symlink()
        or not manifest_path.is_file()
        or _sha256_file(manifest_path) != result.source_manifest_sha256
    ):
        raise ValueError("automated recovery source-v3 manifest hash is crossed")
    manifest = _read_json(manifest_path)
    counts = _mapping(manifest.get("counts"), "source-v3 counts")
    if (
        manifest.get("schema_version") != "full-pool-segmented-source-v3"
        or manifest.get("logical_count") != inputs.expected_logical_count
        or counts.get("pair_rows") != inputs.expected_logical_count
        or counts.get("terminal_rows") != inputs.expected_logical_count
        or counts.get("steps") != inputs.parent_inputs.config.horizon
        or manifest.get("production_deploy_eligible") is not False
    ):
        raise ValueError("automated recovery source-v3 denominator or lifecycle is crossed")
    artifacts = _mapping_sequence(manifest.get("artifacts"), "source-v3 artifacts")
    seen: set[str] = set()
    for artifact in artifacts:
        relative = Path(_non_empty(artifact.get("relative_path"), "source-v3 artifact path"))
        if relative.is_absolute() or ".." in relative.parts or relative.as_posix() in seen:
            raise ValueError("source-v3 artifact path is unsafe or duplicated")
        seen.add(relative.as_posix())
        path = source / relative
        if (
            path.is_symlink()
            or not path.is_file()
            or artifact.get("bytes", artifact.get("byte_length")) != path.stat().st_size
            or artifact.get("sha256") != _sha256_file(path)
        ):
            raise ValueError("source-v3 artifact bytes differ from the manifest")
    policy = _mapping(manifest.get("automated_recovery_policy"), "source-v3 policy")
    settlement = _mapping(manifest.get("settlement_v2"), "source-v3 settlement")
    if (
        policy.get("policy_identity_hash") != documents.identity.get("identity_hash")
        or policy.get("policy_sha256")
        != _sha256_file(result.workspace_root / AUTOMATED_RECOVERY_POLICY_FILE)
        or policy.get("policy_ledger_sha256")
        != _sha256_file(result.workspace_root / AUTOMATED_RECOVERY_POLICY_LEDGER_FILE)
        or settlement.get("journal_sha256")
        != _sha256_file(
            result.workspace_root / settlement_module.DURABLE_PAIR_SETTLEMENT_JOURNAL_FILE
        )
        or set(_string_list(settlement.get("unknown_pair_ids"), "source-v3 settled unknowns"))
        != {
            _non_empty(row.get("pair_id"), "source-v3 reconciliation pair id")
            for row in _mapping_sequence(
                settlement.get("reconciliation_journals"),
                "source-v3 reconciliation journals",
            )
        }
        or settlement.get("implementation_failed_pair_ids") != []
    ):
        raise ValueError("source-v3 policy or settlement lineage is crossed")


def _stopped_result(
    request: AutomatedNestedRecoveryRequest,
    inputs: _ValidatedAutomatedInputs,
    documents: _AutomatedDocuments,
    *,
    status: Literal["automation_exhausted", "implementation_failed"],
    implementation_failed_pair_ids: Sequence[str],
    automation_exhausted_pair_ids: Sequence[str] = (),
) -> AutomatedNestedRecoveryResult:
    return AutomatedNestedRecoveryResult(
        status=status,
        workspace_root=request.recovery_workspace,
        recovery_identity_hash=_non_empty(documents.identity.get("identity_hash"), "identity hash"),
        logical_count=inputs.historical_logical_count,
        imported_durable_terminal_count=inputs.imported_durable_terminal_count,
        fresh_logical_count=0,
        historical_physical_attempts=inputs.historical_physical_attempts,
        uncertainty_physical_charge=inputs.uncertainty_physical_charge,
        new_uncertainty_physical_charge=0,
        retry_physical_attempts=0,
        reconciliation_physical_attempts=0,
        continuation_physical_attempts=0,
        physical_attempt_count=(
            inputs.historical_physical_attempts + inputs.uncertainty_physical_charge
        ),
        recovered_pair_ids=(),
        unknown_pair_ids=inputs.unresolved_pair_ids,
        implementation_failed_pair_ids=tuple(implementation_failed_pair_ids),
        automation_exhausted_pair_ids=tuple(automation_exhausted_pair_ids),
        provider_calls=0,
        production_deploy_eligible=False,
    )


def _write_status(workspace: Path, result: AutomatedNestedRecoveryResult) -> None:
    path = workspace / AUTOMATED_RECOVERY_STATUS_FILE
    if path.exists() or path.is_symlink():
        raise FileExistsError("automated recovery terminal status is create once")
    _exclusive_write_json(
        path,
        {
            "schema_version": _AUTOMATED_STATUS_SCHEMA,
            "result": result.model_dump(mode="json"),
        },
    )
    _fsync_directory(workspace)


def _validated_plan_payload(
    request: AutomatedNestedRecoveryRequest,
) -> dict[str, object]:
    path = _validated_plan_path(request)
    FullPoolSegmentedNestedRecoveryPreflight().status(path)
    envelope = _read_json(path)
    payload = _mapping(envelope.get("payload"), "nested recovery plan payload")
    lineage = _mapping(payload.get("parent_recovery_lineage"), "parent recovery lineage")
    stopped_identity = _mapping(
        lineage.get("stopped_recovery_identity"), "stopped recovery identity ref"
    )
    stopped_workspace = Path(
        _non_empty(stopped_identity.get("path"), "stopped recovery identity path")
    ).parent
    source_inventories = _mapping(
        payload.get("source_inventories"), "nested recovery source inventories"
    )
    expected_inventory = _mapping(
        source_inventories.get("stopped_recovery_workspace"),
        "stopped recovery workspace inventory",
    )
    if LocalOperatorFilesystem().inventory(stopped_workspace) != expected_inventory:
        raise ValueError("stopped recovery workspace changed after nested recovery planning")
    for source_root in (path.parent, stopped_workspace):
        if (
            request.recovery_workspace == source_root
            or request.recovery_workspace.is_relative_to(source_root)
            or source_root.is_relative_to(request.recovery_workspace)
        ):
            raise ValueError("automated recovery workspace must be independent from persisted inputs")
    return payload


def _validated_automated_inputs(
    request: AutomatedNestedRecoveryRequest,
) -> _ValidatedAutomatedInputs:
    payload = _validated_plan_payload(request)
    lineage = _mapping(payload.get("parent_recovery_lineage"), "parent recovery lineage")
    refs = {
        name: _validated_persisted_ref(
            _mapping(lineage.get(name), f"parent recovery lineage {name}"),
            f"parent recovery lineage {name}",
        )
        for name in (
            "parent_recovery_plan",
            "parent_human_authorization",
            "parent_qualification",
            "stopped_recovery_identity",
            "stopped_recovery_manifest",
            "stopped_recovery_ledger",
            "stopped_continuation_status",
            "stopped_recovery_status",
            "stopped_execution_result",
        )
    }
    stopped_workspace = refs["stopped_recovery_identity"].parent
    if any(
        path.parent != stopped_workspace
        for name, path in refs.items()
        if name.startswith("stopped_") and name != "stopped_execution_result"
    ):
        raise ValueError("stopped recovery lineage files are crossed across workspaces")

    parent_authorization_envelope = _read_json(refs["parent_human_authorization"])
    parent_authorization = _mapping(
        parent_authorization_envelope.get("payload"), "parent human authorization payload"
    )
    authorized_at = _utc_datetime(
        parent_authorization.get("authorized_at"), "parent authorization timestamp"
    )
    parent_request = SegmentedRecoveryExecutionRequest(
        recovery_plan_path=refs["parent_recovery_plan"],
        recovery_plan_sha256=_sha256_file(refs["parent_recovery_plan"]),
        authorization_path=refs["parent_human_authorization"],
        authorization_sha256=_sha256_file(refs["parent_human_authorization"]),
        recovery_id=_non_empty(parent_authorization.get("recovery_id"), "parent recovery id"),
        recovery_workspace=stopped_workspace,
    )
    parent_module = FullPoolSegmentedRecovery(now=lambda: authorized_at)
    parent_inputs = parent_module._validated_inputs(parent_request)
    parent_documents = _recovery_documents(parent_request, parent_inputs)

    stopped_identity = _read_json(refs["stopped_recovery_identity"])
    if stopped_identity != parent_documents.identity:
        raise ValueError("stopped recovery identity is crossed with its parent lineage")
    stopped_manifest = _read_json(refs["stopped_recovery_manifest"])
    expected_manifest = {
        "schema_version": "full-pool-segmented-recovery-cutoff-envelope-v1",
        "manifest": parent_documents.manifest,
        "manifest_sha256": parent_documents.manifest_sha256,
    }
    if stopped_manifest != expected_manifest:
        raise ValueError("stopped recovery manifest is crossed with its parent lineage")

    identity_hash = _non_empty(stopped_identity.get("identity_hash"), "stopped identity hash")
    stopped_ledger = _read_failed_ledger(
        refs["stopped_recovery_ledger"],
        continuation=stopped_workspace,
        expected_identity_hash=identity_hash,
    )
    spool = _ConcurrentRuntimeBatchSpool(
        stopped_workspace,
        run_id=_non_empty(stopped_identity.get("run_id"), "stopped recovery run id"),
        identity_hash=identity_hash,
        terminal_variants=("primary",),
        recover_prepared=False,
        base_time_step=0,
    )
    historical_chunks = tuple(spool.iter_committed(stopped_ledger.kernel_replay))
    if [chunk.time_step for chunk in historical_chunks] != list(range(len(historical_chunks))):
        raise ValueError("stopped recovery committed batches are missing or reordered")
    if any(len(chunk.result_rows) != len(chunk.terminal_rows) for chunk in historical_chunks):
        raise ValueError("stopped recovery committed batch lacks terminal closure")

    snapshot_documents = _snapshot_documents(stopped_ledger.kernel_replay)
    active_time_step = len(historical_chunks)
    if set(snapshot_documents) != set(range(active_time_step + 1)):
        raise ValueError("stopped recovery snapshots are missing, extra, or reordered")
    active_snapshot = snapshot_documents[active_time_step]
    active_pair_ids = _snapshot_pair_ids(active_snapshot)
    durable_active_ids: list[str] = []
    for pair_id in active_pair_ids:
        if pair_id not in stopped_ledger.terminal_payload_by_pair_id:
            break
        durable_active_ids.append(pair_id)
    if any(
        pair_id in stopped_ledger.terminal_payload_by_pair_id
        for pair_id in active_pair_ids[len(durable_active_ids) :]
    ):
        raise ValueError("stopped recovery active terminals are not one canonical prefix")

    snapshot = _mapping(payload.get("recovery_snapshot"), "nested recovery snapshot")
    batch_rows = _mapping_sequence(snapshot.get("batch_snapshots"), "nested batch snapshots")
    if len(batch_rows) != active_time_step + 1:
        raise ValueError("nested recovery batch count is crossed with persisted spool")
    committed_terminal_count = 0
    committed_digests: list[str] = []
    for chunk, row in zip(historical_chunks, batch_rows[:-1], strict=True):
        pair_ids = [
            _non_empty(terminal.get("pair_id"), "committed terminal pair id")
            for terminal in chunk.terminal_rows
        ]
        digest = _sequence_sha256(pair_ids)
        if (
            row.get("time_step") != chunk.time_step
            or row.get("state") != "committed"
            or row.get("batch_snapshot_hash") != chunk.batch_snapshot_hash
            or row.get("terminal_count") != len(pair_ids)
            or row.get("terminal_pair_ids_sha256") != digest
        ):
            raise ValueError("nested recovery committed snapshot is crossed with persisted spool")
        committed_terminal_count += len(pair_ids)
        committed_digests.append(digest)
    active_row = _mapping(batch_rows[-1], "nested active batch snapshot")
    active_document_hash = _sha256_json(active_snapshot)
    if (
        active_row.get("time_step") != active_time_step
        or active_row.get("state") != "active_incomplete"
        or active_row.get("batch_snapshot_hash") != active_document_hash
        or active_row.get("candidate_pair_count") != len(active_pair_ids)
        or active_row.get("candidate_pair_ids_sha256") != _sequence_sha256(active_pair_ids)
        or active_row.get("durable_terminal_count") != len(durable_active_ids)
        or active_row.get("durable_terminal_pair_ids_sha256")
        != _sequence_sha256(durable_active_ids)
    ):
        raise ValueError("nested recovery active snapshot is crossed with persisted bytes")

    summary = _mapping(snapshot.get("durable_terminal_summary"), "durable terminal summary")
    imported_count = committed_terminal_count + len(durable_active_ids)
    if (
        summary.get("count") != imported_count
        or summary.get("committed_terminal_count") != committed_terminal_count
        or summary.get("active_terminal_count") != len(durable_active_ids)
        or summary.get("pair_ids_sha256")
        != _sha256_json([*committed_digests, _sequence_sha256(durable_active_ids)])
    ):
        raise ValueError("nested recovery durable terminal summary is crossed")

    unresolved_rows = _mapping_sequence(
        snapshot.get("unresolved_pairs"), "nested recovery unresolved pairs"
    )
    unresolved_pair_ids = tuple(
        _non_empty(row.get("pair_id"), "nested unresolved pair id")
        for row in unresolved_rows
    )
    if len(unresolved_pair_ids) != 7 or active_pair_ids[
        len(durable_active_ids) : len(durable_active_ids) + 7
    ] != list(unresolved_pair_ids):
        raise ValueError("nested recovery unresolved pairs are not the exact canonical frontier")
    active_terminal_payloads = tuple(
        stopped_ledger.terminal_payload_by_pair_id[pair_id]
        for pair_id in durable_active_ids
    )

    accounting = _mapping(payload.get("accounting"), "nested recovery accounting")
    expected_logical = parent_inputs.config.sample_size * len(parent_inputs.config.messages)
    historical_logical = _non_negative_int(
        accounting.get("historical_logical_count"), "historical logical count"
    )
    historical_physical = _non_negative_int(
        accounting.get("historical_physical_attempts"), "historical physical attempts"
    )
    uncertainty = _non_negative_int(
        accounting.get("unresolved_uncertainty_physical_charge"), "uncertainty charge"
    )
    if (
        accounting.get("logical_cap") != expected_logical
        or historical_logical != imported_count + len(unresolved_pair_ids)
        or accounting.get("fresh_logical_remaining") != expected_logical - historical_logical
        or accounting.get("logical_retry_charge") != 0
        or accounting.get("physical_accounting_total") != historical_physical + uncertainty
        or accounting.get("remaining_physical_cap")
        != _non_negative_int(accounting.get("physical_cap"), "physical cap")
        - historical_physical
        - uncertainty
    ):
        raise ValueError("nested recovery accounting is crossed with reconstructed runtime")
    execution = _mapping(payload.get("execution_contract"), "nested execution contract")
    if (
        execution.get("provider_contract_sha256")
        != _sha256_json(parent_inputs.prefix.provider_contract)
        or execution.get("prompt_contract_sha256")
        != _sha256_json(parent_inputs.prefix.prompt_contract)
        or execution.get("maximum_attempts_per_dispatch")
        != parent_inputs.prefix.maximum_attempts_per_dispatch
    ):
        raise ValueError("nested recovery Provider or request contract is crossed")

    source_inventory = _mapping(
        _mapping(payload.get("source_inventories"), "nested source inventories").get(
            "stopped_recovery_workspace"
        ),
        "stopped recovery workspace inventory",
    )
    inputs = _ValidatedAutomatedInputs(
        payload=payload,
        nested_recovery_plan_path=request.nested_recovery_plan_path,
        nested_recovery_plan_sha256=request.nested_recovery_plan_sha256,
        parent_request=parent_request,
        parent_inputs=parent_inputs,
        stopped_workspace=stopped_workspace,
        stopped_identity=stopped_identity,
        stopped_ledger=stopped_ledger,
        historical_chunks=historical_chunks,
        snapshot_document_by_time_step=snapshot_documents,
        active_snapshot_document=active_snapshot,
        active_terminal_payloads=active_terminal_payloads,
        unresolved_pair_ids=unresolved_pair_ids,
        imported_durable_terminal_count=imported_count,
        expected_logical_count=expected_logical,
        historical_logical_count=historical_logical,
        historical_physical_attempts=historical_physical,
        uncertainty_physical_charge=uncertainty,
        protected_inventory=source_inventory,
    )
    _validate_formal_nested_contract(request, inputs)
    _assert_inputs_unchanged(inputs)
    return inputs


def _validate_formal_nested_contract(
    request: AutomatedNestedRecoveryRequest,
    inputs: _ValidatedAutomatedInputs,
) -> None:
    if inputs.expected_logical_count != 109_200:
        return
    identity = _mapping(inputs.payload.get("recovery_identity"), "nested recovery identity")
    accounting = _mapping(inputs.payload.get("accounting"), "nested recovery accounting")
    if (
        request.nested_recovery_plan_sha256 != _FORMAL_NESTED_PLAN_SHA256
        or identity.get("identity_hash") != _FORMAL_NESTED_IDENTITY_HASH
        or identity.get("parent_recovery_identity_hash")
        != _FORMAL_PARENT_RECOVERY_IDENTITY_HASH
        or _sha256_json(inputs.protected_inventory) != _FORMAL_STOPPED_INVENTORY_SHA256
        or inputs.unresolved_pair_ids != _FORMAL_RETRY_PAIR_IDS
        or inputs.imported_durable_terminal_count != 90_061
        or inputs.historical_logical_count != 90_068
        or inputs.historical_physical_attempts != 90_891
        or inputs.uncertainty_physical_charge != 21
        or len(inputs.historical_chunks) != 24
        or accounting.get("fresh_logical_remaining") != 19_132
        or accounting.get("logical_cap") != 109_200
        or accounting.get("physical_cap") != 120_120
    ):
        raise ValueError("nested recovery does not match the exact frozen Formal #210 contract")


def _assert_inputs_unchanged(inputs: _ValidatedAutomatedInputs) -> None:
    if (
        inputs.nested_recovery_plan_path.is_symlink()
        or not inputs.nested_recovery_plan_path.is_file()
        or _sha256_file(inputs.nested_recovery_plan_path)
        != inputs.nested_recovery_plan_sha256
    ):
        raise ValueError("nested recovery plan changed during automated recovery")
    _assert_parent_recovery_unchanged(inputs.parent_request, inputs.parent_inputs)
    if LocalOperatorFilesystem().inventory(inputs.stopped_workspace) != inputs.protected_inventory:
        raise ValueError("stopped recovery workspace changed during automated recovery validation")


def _validated_persisted_ref(ref: Mapping[str, object], context: str) -> Path:
    if set(ref) != {"path", "bytes", "sha256"}:
        raise ValueError(f"{context} fields are not exact")
    path = Path(_non_empty(ref.get("path"), f"{context} path"))
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError(f"{context} must reference one absolute regular file")
    if ref.get("bytes") != path.stat().st_size or ref.get("sha256") != _sha256_file(path):
        raise ValueError(f"{context} bytes changed after nested recovery planning")
    return path


def _validated_plan_path(request: AutomatedNestedRecoveryRequest) -> Path:
    path = request.nested_recovery_plan_path
    if path.is_symlink() or not path.is_file():
        raise ValueError("nested recovery plan must be one existing regular file")
    if _sha256_file(path) != request.nested_recovery_plan_sha256:
        raise ValueError("nested recovery plan bytes differ from the explicit hash")
    return path


def _read_json(path: Path) -> dict[str, object]:
    return _mapping(json.loads(path.read_text(encoding="utf-8")), f"JSON object {path}")


def _mapping(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{context} must be a mapping")
    return dict(value)


def _mapping_sequence(value: object, context: str) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{context} must be a sequence")
    return [_mapping(item, context) for item in value]


def _non_empty(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be a non-empty string")
    return value


def _non_negative_int(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{context} must be a non-negative int")
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sequence_sha256(values: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(_canonical_json(value).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _string_list(value: object, context: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{context} must be a sequence")
    result = [_non_empty(item, context) for item in value]
    if len(result) != len(set(result)):
        raise ValueError(f"{context} contains duplicates")
    return result


def _copy_file_durable(source: Path, target: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"source-v3 artifact is missing or unsafe: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as source_handle, target.open("xb") as target_handle:
        shutil.copyfileobj(source_handle, target_handle)
        target_handle.flush()
        os.fsync(target_handle.fileno())
    _fsync_directory(target.parent)


def _artifact_ref(root: Path, path: Path) -> dict[str, object]:
    return {
        "relative_path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _replace_json(path: Path, payload: Mapping[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(_canonical_json(payload) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def _append_policy_event(
    path: Path,
    *,
    identity_hash: str,
    sequence: int,
    previous_checksum: str | None,
    event_type: str,
    payload: Mapping[str, object],
) -> str:
    body = {
        "schema_version": _AUTOMATED_POLICY_LEDGER_SCHEMA,
        "sequence": sequence,
        "previous_checksum": previous_checksum,
        "policy_identity_hash": identity_hash,
        "event_type": event_type,
        "payload": dict(payload),
    }
    checksum = _sha256_json(body)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(_canonical_json({**body, "checksum": checksum}) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_directory(path.parent)
    return checksum


def _exclusive_write_json(path: Path, payload: Mapping[str, object]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(_canonical_json(payload) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _repository_commit() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(__file__).resolve().parents[2],
        check=True,
        capture_output=True,
        text=True,
    )
    commit = completed.stdout.strip()
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ValueError("repository HEAD is not one full commit hash")
    return commit


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
