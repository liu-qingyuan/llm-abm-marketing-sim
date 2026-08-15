from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .full_pool_segmented_continuation import (
    FULL_POOL_SEGMENTED_LOGICAL_CAP,
    FULL_POOL_SEGMENTED_MAX_CONCURRENCY,
    FULL_POOL_SEGMENTED_PHYSICAL_CAP,
    SegmentedQualificationArtifactRef,
    _complete_cutoff_manifest,
    _continuation_identity,
    _freeze_v1_prefix,
    _FrozenPrefix,
    _replay_continuation_ledger,
    _validated_concurrency_qualification_bytes,
)
from .full_pool_segmented_operator import (
    CutoverPlanRequest,
    FullPoolSegmentedCutoverOperator,
    LocalOperatorFilesystem,
    _request_fields,
)

_RECOVERY_PLAN_SCHEMA = "full-pool-segmented-recovery-plan-v1"
_RECOVERY_PLAN_ENVELOPE_SCHEMA = "full-pool-segmented-recovery-plan-envelope-v1"
_RECOVERY_IDENTITY_SCHEMA = "full-pool-segmented-recovery-identity-v1"
_RECOVERY_ARTIFACT_FILE = "recovery-plan.json"
_CONTINUATION_IDENTITY_SCHEMA = "full-pool-segmented-continuation-identity-v1"
_CONTINUATION_MANIFEST_ENVELOPE_SCHEMA = "full-pool-segmented-cutoff-envelope-v1"
_CONTINUATION_MANIFEST_SCHEMA = "full-pool-segmented-complete-cutoff-manifest-v2"
_CONTINUATION_LEDGER_SCHEMA = "full-pool-segmented-continuation-ledger-v1"
_CONTINUATION_STATUS_SCHEMA = "full-pool-segmented-continuation-status-v1"
_FAILURE_AUDIT_SCHEMA = "full-pool-segmented-reconciliation-required-audit-v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RECOVERY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")

_FAILURE_AUDIT_FIELDS = frozenset(
    {
        "schema_version",
        "recorded_at",
        "plan_path",
        "plan_sha256",
        "continuation_workspace",
        "worker_pid",
        "worker_running",
        "lifecycle",
        "configured_max_concurrency",
        "prefix_logical_count",
        "logical_count",
        "physical_attempt_count",
        "suffix_dispatched_count",
        "suffix_terminal_count",
        "unknown_pair_count",
        "unknown_pair_ids",
        "zero_terminal_evidence_count",
        "canonical_drain_blocked_following_pair_count",
        "accounted_wave_count",
        "accounted_suffix_physical_attempts",
        "continuation_ledger_bytes",
        "continuation_ledger_sha256",
        "continuation_status_sha256",
        "qualification_artifact_sha256",
        "qualification_lane_count",
        "result_artifact_sha256",
        "automatic_retry_performed",
        "recovery_authorized",
        "production_deploy_eligible",
        "raw_prompt_request_response_persisted",
    }
)
_RESULT_FIELDS = frozenset(
    {
        "status",
        "workspace_root",
        "manifest_sha256",
        "terminal_rows_path",
        "source_root",
        "source_manifest_sha256",
        "durable_prefix_terminal_count",
        "concurrent_suffix_terminal_count",
        "committed_feedback_user_ids",
        "unknown_pair_ids",
        "logical_count",
        "physical_attempt_count",
        "production_deploy_eligible",
    }
)
_STATUS_FIELDS = frozenset(
    {
        "schema_version",
        "lifecycle",
        "manifest_sha256",
        "durable_prefix_terminal_count",
        "concurrent_suffix_terminal_count",
        "committed_feedback_user_ids",
        "unknown_pair_ids",
        "logical_count",
        "physical_attempt_count",
        "terminal_rows_relative_path",
        "terminal_rows_sha256",
        "production_deploy_eligible",
    }
)
_LEDGER_FIELDS = frozenset(
    {
        "schema_version",
        "sequence",
        "previous_checksum",
        "continuation_identity_hash",
        "event_type",
        "payload",
        "checksum",
    }
)
_LEDGER_PAYLOAD_FIELDS = {
    "continuation_started": frozenset(
        {"continuation_id", "cutoff_manifest_sha256", "max_concurrency", "active_time_step", "expected_horizon"}
    ),
    "suffix_wave_reserved": frozenset(
        {"pair_ids", "physical_reservation", "maximum_attempts_per_dispatch"}
    ),
    "pair_dispatched": frozenset({"pair_id", "lane_id"}),
    "wave_accounting": frozenset({"pair_ids", "lanes", "actual_physical_attempts"}),
    "pair_terminal": frozenset({"pair_id", "terminal_row", "variant_evidence"}),
    "kernel_batch_committed": frozenset({"event_identity", "batch_snapshot_hash", "payload"}),
    "kernel_batch_snapshot": frozenset(
        {"sequence", "snapshot_type", "snapshot_identity", "snapshot_hash", "snapshot_path"}
    ),
}
_WAVE_LANE_FIELDS = frozenset(
    {
        "lane_id",
        "pair_id",
        "request_invocations_delta",
        "external_request_invocations_delta",
        "terminal_evidence_request_invocations",
        "actual_physical_attempts",
    }
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SegmentedRecoveryPlanRequest(_FrozenModel):
    """Explicit failed-run identity and independent create-once recovery destination."""

    cutover_plan_path: Path
    result_artifact_path: Path
    failure_audit_path: Path
    failure_audit_sha256: str
    recovery_id: str = Field(min_length=1, max_length=160)
    recovery_root: Path

    @field_validator(
        "cutover_plan_path",
        "result_artifact_path",
        "failure_audit_path",
        "recovery_root",
        mode="before",
    )
    @classmethod
    def _absolute_path(cls, value: object) -> Path:
        return Path(cast(str | Path, value)).expanduser().absolute()

    @field_validator("failure_audit_sha256")
    @classmethod
    def _hash(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("failure_audit_sha256 must be a lowercase SHA-256 digest")
        return value

    @field_validator("recovery_id")
    @classmethod
    def _identity(cls, value: str) -> str:
        if _RECOVERY_ID.fullmatch(value) is None:
            raise ValueError("recovery_id contains unsupported characters")
        return value

    @model_validator(mode="after")
    def _independent_request_paths(self) -> SegmentedRecoveryPlanRequest:
        source_files = {
            self.cutover_plan_path,
            self.result_artifact_path,
            self.failure_audit_path,
        }
        if len(source_files) != 3:
            raise ValueError("cutover plan, result, and failure audit paths must be distinct")
        if any(path == self.recovery_root or path.is_relative_to(self.recovery_root) for path in source_files):
            raise ValueError("recovery_root must not own a failed-run input")
        return self


class SegmentedRecoveryPlanResult(_FrozenModel):
    status: Literal["recovery_prepared"]
    artifact_path: Path
    artifact_sha256: str
    configured_max_concurrency: Literal[10]
    worker_state: Literal["recorded_stopped"]
    durable_progress: dict[str, int]
    unresolved_count: Literal[2]
    provider_calls: Literal[0] = 0
    production_deploy_eligible: Literal[False] = False

    @field_validator("artifact_sha256")
    @classmethod
    def _artifact_hash(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("artifact_sha256 must be a lowercase SHA-256 digest")
        return value


@dataclass(frozen=True)
class _LedgerTerminalRef:
    pair_id: str
    sequence: int
    payload_sha256: str


@dataclass(frozen=True)
class _LedgerScan:
    dispatched_pair_ids: tuple[str, ...]
    durable_pair_ids: tuple[str, ...]
    durable_terminal_refs: tuple[_LedgerTerminalRef, ...]
    terminal_evidence_attempts: dict[str, int]
    actual_physical_attempts: dict[str, int]
    wave_count: int
    wave_physical_attempts: int
    kernel_snapshots: tuple[dict[str, object], ...]
    kernel_commits: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class _PreparedRecovery:
    payload: dict[str, object]
    protected_inventories: dict[str, object]


@dataclass(frozen=True)
class _FailedRunContract:
    plan_sha256: str
    continuation_identity_hash: str
    cutoff_manifest_sha256: str
    continuation_ledger_sha256: str
    continuation_status_sha256: str
    qualification_artifact_sha256: str
    result_artifact_sha256: str
    failure_audit_sha256: str
    prefix_logical_count: int
    durable_prefix_terminal_count: int
    suffix_dispatched_count: int
    suffix_terminal_count: int
    logical_count: int
    physical_attempt_count: int
    accounted_wave_count: int
    accounted_suffix_physical_attempts: int
    unknown_pair_ids: tuple[str, ...]


_ISSUE_205_FAILED_RUN = _FailedRunContract(
    plan_sha256="19c52f173f28cc49882127ce96a82bb99e06e05f51afbadd5b7c77f13cf07240",
    continuation_identity_hash="ba5021de5ca68e315333f2bb21979a7aab06c62efeb0dfc12398bb320082a021",
    cutoff_manifest_sha256="817cce8e292b96cdddea887655349386f96eeb7c5910ddc1afdc8d901d9f5a63",
    continuation_ledger_sha256="303ae609ae51bded17b12f77a957cff34eb7e71bdba50dc68694010cdd1fde52",
    continuation_status_sha256="ce6c0562f951a6122e21d75b50ac3a12e8437a7ef7320ee24de5a90d23729b2e",
    qualification_artifact_sha256="243dceeb9722229a94e5ec8a41cf165b1f034921bf12fcc2103f6ff1f875fb12",
    result_artifact_sha256="35be1cb74f473c74c7bcdb3c3b4c3e0a9ceb5d7c18847815deec62aabb81cb66",
    failure_audit_sha256="5cfe79ca7b9dca8a3728a78e4d8c402c92029ef42fc4e0e71710f0f154f40f54",
    prefix_logical_count=8_782,
    durable_prefix_terminal_count=8_782,
    suffix_dispatched_count=10_218,
    suffix_terminal_count=10_216,
    logical_count=19_000,
    physical_attempt_count=19_117,
    accounted_wave_count=1_024,
    accounted_suffix_physical_attempts=10_314,
    unknown_pair_ids=("70400636033:message_1:5", "70401299326:message_1:5"),
)
_EXPECTED_FAILED_RUN = _ISSUE_205_FAILED_RUN


class FullPoolSegmentedRecoveryPreflight:
    """Replay one failed continuation and publish a nondeployable recovery plan.

    This Interface intentionally has no Adapter, client, authorization, or Provider
    parameter. It only reads persisted evidence and writes one independent artifact.
    """

    def __init__(self, *, filesystem: LocalOperatorFilesystem | None = None) -> None:
        self.filesystem = filesystem or LocalOperatorFilesystem()

    def prepare(self, request: SegmentedRecoveryPlanRequest) -> SegmentedRecoveryPlanResult:
        recovery_root = request.recovery_root
        if recovery_root.exists() or recovery_root.is_symlink():
            raise FileExistsError("recovery_root must be a new independent path")
        prepared = self._prepare_payload(request)
        self._assert_protected_unchanged(prepared.protected_inventories)
        artifact_path = recovery_root / _RECOVERY_ARTIFACT_FILE
        try:
            recovery_root.mkdir(parents=False)
            envelope = {
                "schema_version": _RECOVERY_PLAN_ENVELOPE_SCHEMA,
                "payload": prepared.payload,
                "payload_sha256": _sha256_json(prepared.payload),
            }
            _exclusive_write_json(artifact_path, envelope)
            artifact_path.chmod(0o444)
            _fsync_directory(recovery_root)
            self._assert_protected_unchanged(prepared.protected_inventories)
            return self.status(artifact_path)
        except BaseException:
            if artifact_path.exists() and not artifact_path.is_symlink():
                artifact_path.chmod(0o644)
                artifact_path.unlink()
            if recovery_root.is_dir():
                recovery_root.rmdir()
            raise

    def status(self, artifact_path: str | Path) -> SegmentedRecoveryPlanResult:
        path = _require_regular_file(Path(artifact_path).expanduser().absolute(), "recovery plan artifact")
        envelope = _read_json(path)
        if set(envelope) != {"schema_version", "payload", "payload_sha256"}:
            raise ValueError("recovery plan envelope fields are not exact")
        if envelope.get("schema_version") != _RECOVERY_PLAN_ENVELOPE_SCHEMA:
            raise ValueError("recovery plan envelope schema is unsupported")
        payload = _mapping(envelope.get("payload"), "recovery plan payload")
        if envelope.get("payload_sha256") != _sha256_json(payload):
            raise ValueError("recovery plan payload hash mismatch")
        if payload.get("schema_version") != _RECOVERY_PLAN_SCHEMA:
            raise ValueError("recovery plan schema is unsupported")
        _validate_recovery_payload(payload, artifact_path=path)
        status = _mapping(payload.get("status_output"), "recovery status output")
        if set(status) != {
            "lifecycle",
            "configured_max_concurrency",
            "worker_state",
            "worker_pid",
            "durable_progress",
            "unresolved_count",
        }:
            raise ValueError("recovery status output fields are not exact")
        if (
            status.get("lifecycle") != "recovery_prepared"
            or status.get("configured_max_concurrency") != FULL_POOL_SEGMENTED_MAX_CONCURRENCY
            or status.get("worker_state") != "recorded_stopped"
            or status.get("unresolved_count") != 2
            or payload.get("provider_calls") != 0
            or payload.get("production_deploy_eligible") is not False
        ):
            raise ValueError("recovery status output is crossed")
        durable_progress_raw = _mapping(status.get("durable_progress"), "recovery durable progress")
        durable_progress = {
            key: _strict_non_negative_int(value, f"durable progress {key}")
            for key, value in durable_progress_raw.items()
        }
        return SegmentedRecoveryPlanResult(
            status="recovery_prepared",
            artifact_path=path,
            artifact_sha256=_sha256_file(path),
            configured_max_concurrency=FULL_POOL_SEGMENTED_MAX_CONCURRENCY,
            worker_state="recorded_stopped",
            durable_progress=durable_progress,
            unresolved_count=2,
            provider_calls=0,
            production_deploy_eligible=False,
        )

    def _prepare_payload(self, request: SegmentedRecoveryPlanRequest) -> _PreparedRecovery:
        operator = FullPoolSegmentedCutoverOperator(filesystem=self.filesystem)
        plan, plan_sha256 = operator._read_plan(request.cutover_plan_path)
        cutover_request = CutoverPlanRequest.model_validate(_request_fields(plan))
        self._validate_independent_root(request.recovery_root, cutover_request, request)
        implementation_artifacts = _mapping(plan.get("implementation_artifacts"), "implementation artifacts")
        if implementation_artifacts != operator._implementation_artifacts():
            raise ValueError("failed-run implementation bytes differ from the prepared cutover plan")
        loaded_commit = _non_empty(plan.get("loaded_repository_commit"), "loaded repository commit")
        if re.fullmatch(r"[0-9a-f]{40}", loaded_commit) is None:
            raise ValueError("failed-run loaded repository commit is invalid")
        authorization, authorization_sha256 = operator._validate_run_artifacts(
            cutover_request,
            plan_file_hash=plan_sha256,
        )
        operator._validate_qualification_state(
            cutover_request,
            continuation_exists=True,
            authorization_hash=authorization_sha256,
        )
        qualification_bytes, qualification = _validated_concurrency_qualification_bytes(
            SegmentedQualificationArtifactRef(
                path=cutover_request.qualification_artifact,
                sha256=_sha256_file(cutover_request.qualification_artifact),
            )
        )
        del qualification_bytes

        prefix = _freeze_v1_prefix(cutover_request.frozen_prefix_workspace)
        continuation = cutover_request.continuation_workspace
        continuation_inventory = self.filesystem.inventory(continuation)
        frozen_inventory = self.filesystem.inventory(cutover_request.frozen_prefix_workspace)
        identity_path = continuation / "segmented_continuation_identity.json"
        manifest_path = continuation / "cutoff_manifest.json"
        ledger_path = continuation / "segmented_continuation_ledger.jsonl"
        status_path = continuation / "segmented_continuation_status.json"
        identity = _read_json(_require_regular_file(identity_path, "continuation identity"))
        manifest_envelope = _read_json(_require_regular_file(manifest_path, "cutoff manifest"))
        if set(manifest_envelope) != {"schema_version", "manifest", "manifest_sha256"}:
            raise ValueError("cutoff manifest envelope fields are not exact")
        if manifest_envelope.get("schema_version") != _CONTINUATION_MANIFEST_ENVELOPE_SCHEMA:
            raise ValueError("cutoff manifest envelope schema is unsupported")
        manifest = _mapping(manifest_envelope.get("manifest"), "cutoff manifest")
        manifest_sha256 = _non_empty(manifest_envelope.get("manifest_sha256"), "cutoff manifest hash")
        if manifest.get("schema_version") != _CONTINUATION_MANIFEST_SCHEMA:
            raise ValueError("recovery requires a complete segmented cutoff manifest v2")
        if _sha256_json(manifest) != manifest_sha256:
            raise ValueError("cutoff manifest hash mismatch")
        expected_logical = _strict_non_negative_int(
            manifest.get("expected_logical_count"), "expected logical count"
        )
        remaining_logical = _strict_non_negative_int(
            manifest.get("remaining_logical_count"), "remaining logical count"
        )
        if (
            manifest.get("logical_cap") != FULL_POOL_SEGMENTED_LOGICAL_CAP
            or manifest.get("physical_cap") != FULL_POOL_SEGMENTED_PHYSICAL_CAP
            or manifest.get("max_concurrency") != FULL_POOL_SEGMENTED_MAX_CONCURRENCY
            or expected_logical > FULL_POOL_SEGMENTED_LOGICAL_CAP
            or remaining_logical != expected_logical - prefix.attempt_prefix.logical_count
        ):
            raise ValueError("cutoff manifest cap or logical denominator is crossed")
        reconciliation_authorization = operator._migration_authorization(cutover_request, authorization)
        expected_manifest = _complete_cutoff_manifest(
            prefix=prefix,
            continuation_id=cutover_request.continuation_id,
            dataset_ref=_mapping(manifest.get("dataset"), "cutoff dataset ref"),
            expected_logical=expected_logical,
            remaining_logical=remaining_logical,
            reconciliation_authorization=reconciliation_authorization,
        )
        if manifest != expected_manifest:
            raise ValueError("cutoff manifest is crossed with the frozen prefix")
        expected_identity = _continuation_identity(
            continuation=continuation,
            continuation_id=cutover_request.continuation_id,
            prefix=prefix,
            manifest_sha256=manifest_sha256,
        )
        if identity != expected_identity or identity.get("schema_version") != _CONTINUATION_IDENTITY_SCHEMA:
            raise ValueError("continuation identity is crossed with the cutoff manifest")
        identity_hash = _non_empty(identity.get("identity_hash"), "continuation identity hash")
        ledger_bytes = _require_regular_file(ledger_path, "continuation ledger").read_bytes()
        if not ledger_bytes.endswith(b"\n"):
            raise ValueError("continuation ledger snapshot is truncated")
        replay_dispatched, replay_durable, replay_physical, source_anchor = _replay_continuation_ledger(
            ledger_path,
            expected_identity_hash=identity_hash,
            snapshot_bytes=ledger_bytes,
        )
        if source_anchor is not None:
            raise ValueError("reconciliation-required continuation cannot expose source-v2")
        ledger_scan = _scan_ledger(ledger_bytes, expected_identity_hash=identity_hash)
        if (
            list(ledger_scan.dispatched_pair_ids) != replay_dispatched
            or list(ledger_scan.durable_pair_ids) != replay_durable
            or ledger_scan.wave_physical_attempts != replay_physical
        ):
            raise ValueError("failed ledger replays disagree")

        batch_snapshots, schedule_positions, expected_continuation_files = _recovery_batch_snapshots(
            continuation=continuation,
            prefix=prefix,
            identity=identity,
            ledger_scan=ledger_scan,
        )
        expected_files = {
            "segmented_continuation_identity.json",
            "cutoff_manifest.json",
            "segmented_continuation_ledger.jsonl",
            "segmented_continuation_status.json",
            *expected_continuation_files,
        }
        if set(continuation_inventory) != expected_files:
            raise ValueError("failed continuation inventory is not exact")
        suffix_schedule = [
            pair_id
            for batch in batch_snapshots
            for pair_id in cast(list[str], batch["candidate_schedule_pair_ids"])
            if pair_id not in prefix.terminal_by_pair_id
        ]
        if list(ledger_scan.dispatched_pair_ids) != suffix_schedule[: len(ledger_scan.dispatched_pair_ids)]:
            raise ValueError("continuation dispatch order is crossed with the canonical candidate schedule")
        qualification_pair_ids = _string_list(qualification.get("pair_ids"), "qualification pair ids")
        if (
            qualification.get("continuation_authorization_sha256") != authorization_sha256
            or qualification_pair_ids != list(ledger_scan.dispatched_pair_ids[:10])
            or any(pair_id not in set(ledger_scan.durable_pair_ids) for pair_id in qualification_pair_ids)
        ):
            raise ValueError("ten-lane qualification is crossed with the first durable suffix wave")

        status = _read_json(_require_regular_file(status_path, "continuation status"))
        if set(status) != _STATUS_FIELDS or status.get("schema_version") != _CONTINUATION_STATUS_SCHEMA:
            raise ValueError("continuation status fields or schema are not exact")
        migration_charge = (
            reconciliation_authorization.physical_attempt_charge
            if reconciliation_authorization is not None
            else 0
        )
        unknown_pair_ids = [
            pair_id for pair_id in ledger_scan.dispatched_pair_ids if pair_id not in set(ledger_scan.durable_pair_ids)
        ]
        expected_status = {
            "schema_version": _CONTINUATION_STATUS_SCHEMA,
            "lifecycle": "reconciliation_required",
            "manifest_sha256": manifest_sha256,
            "durable_prefix_terminal_count": len(prefix.terminal_by_pair_id),
            "concurrent_suffix_terminal_count": len(ledger_scan.durable_pair_ids),
            "committed_feedback_user_ids": [],
            "unknown_pair_ids": unknown_pair_ids,
            "logical_count": prefix.attempt_prefix.logical_count + len(ledger_scan.dispatched_pair_ids),
            "physical_attempt_count": (
                prefix.attempt_prefix.physical_attempt_count
                + migration_charge
                + ledger_scan.wave_physical_attempts
            ),
            "terminal_rows_relative_path": None,
            "terminal_rows_sha256": None,
            "production_deploy_eligible": False,
        }
        if status != expected_status or len(unknown_pair_ids) != 2:
            raise ValueError("continuation status is crossed with the exact dual-unresolved ledger")

        result = _read_json(_require_regular_file(request.result_artifact_path, "continuation result"))
        if set(result) != _RESULT_FIELDS:
            raise ValueError("continuation result fields are not exact")
        expected_result = {
            "status": "reconciliation_required",
            "workspace_root": str(continuation),
            "manifest_sha256": manifest_sha256,
            "terminal_rows_path": None,
            "source_root": None,
            "source_manifest_sha256": None,
            "durable_prefix_terminal_count": len(prefix.terminal_by_pair_id),
            "concurrent_suffix_terminal_count": len(ledger_scan.durable_pair_ids),
            "committed_feedback_user_ids": [],
            "unknown_pair_ids": unknown_pair_ids,
            "logical_count": expected_status["logical_count"],
            "physical_attempt_count": expected_status["physical_attempt_count"],
            "production_deploy_eligible": False,
        }
        if result != expected_result:
            raise ValueError("continuation result is crossed with status and ledger")

        audit_path = _require_regular_file(request.failure_audit_path, "failure audit")
        if _sha256_file(audit_path) != request.failure_audit_sha256:
            raise ValueError("failure audit hash mismatch")
        audit = _read_json(audit_path)
        _validate_failure_audit(
            audit,
            request=request,
            cutover_request=cutover_request,
            plan_sha256=plan_sha256,
            ledger_path=ledger_path,
            status_path=status_path,
            qualification_path=cutover_request.qualification_artifact,
            result_path=request.result_artifact_path,
            prefix_logical=prefix.attempt_prefix.logical_count,
            status=expected_status,
            ledger_scan=ledger_scan,
            unknown_pair_ids=unknown_pair_ids,
        )
        observed_failed_run = _FailedRunContract(
            plan_sha256=plan_sha256,
            continuation_identity_hash=identity_hash,
            cutoff_manifest_sha256=manifest_sha256,
            continuation_ledger_sha256=_sha256_file(ledger_path),
            continuation_status_sha256=_sha256_file(status_path),
            qualification_artifact_sha256=_sha256_file(cutover_request.qualification_artifact),
            result_artifact_sha256=_sha256_file(request.result_artifact_path),
            failure_audit_sha256=request.failure_audit_sha256,
            prefix_logical_count=prefix.attempt_prefix.logical_count,
            durable_prefix_terminal_count=len(prefix.terminal_by_pair_id),
            suffix_dispatched_count=len(ledger_scan.dispatched_pair_ids),
            suffix_terminal_count=len(ledger_scan.durable_pair_ids),
            logical_count=_strict_non_negative_int(status["logical_count"], "failed logical count"),
            physical_attempt_count=_strict_non_negative_int(
                status["physical_attempt_count"], "failed physical count"
            ),
            accounted_wave_count=ledger_scan.wave_count,
            accounted_suffix_physical_attempts=ledger_scan.wave_physical_attempts,
            unknown_pair_ids=tuple(unknown_pair_ids),
        )
        if observed_failed_run != _EXPECTED_FAILED_RUN:
            raise ValueError("failed run does not match the exact Issue #205 recovery contract")
        unresolved_pairs = _unresolved_snapshot(
            unknown_pair_ids,
            schedule_positions=schedule_positions,
            ledger_scan=ledger_scan,
            maximum_attempts=prefix.maximum_attempts_per_dispatch,
        )

        historical_logical = _strict_non_negative_int(status["logical_count"], "historical logical count")
        historical_physical = _strict_non_negative_int(
            status["physical_attempt_count"], "historical physical count"
        )
        uncertainty_charge = len(unresolved_pairs) * prefix.maximum_attempts_per_dispatch
        physical_total = historical_physical + uncertainty_charge
        if historical_logical > FULL_POOL_SEGMENTED_LOGICAL_CAP or physical_total > FULL_POOL_SEGMENTED_PHYSICAL_CAP:
            raise ValueError("recovery accounting exceeds a frozen cap")
        accounting = {
            "logical_cap": FULL_POOL_SEGMENTED_LOGICAL_CAP,
            "historical_logical_count": historical_logical,
            "logical_retry_charge": 0,
            "remaining_logical_cap": FULL_POOL_SEGMENTED_LOGICAL_CAP - historical_logical,
            "physical_cap": FULL_POOL_SEGMENTED_PHYSICAL_CAP,
            "historical_physical_attempts": historical_physical,
            "unresolved_uncertainty_physical_charge": uncertainty_charge,
            "future_retry_physical_attempts": 0,
            "physical_accounting_total": physical_total,
            "remaining_physical_cap": FULL_POOL_SEGMENTED_PHYSICAL_CAP - physical_total,
        }
        durable_suffix = [
            {
                "pair_id": ref.pair_id,
                "ledger_sequence": ref.sequence,
                "terminal_evidence_sha256": ref.payload_sha256,
            }
            for ref in ledger_scan.durable_terminal_refs
        ]
        recovery_snapshot = {
            "durable_prefix_terminals": list(prefix.ordered_terminal_ids),
            "durable_suffix_terminals": durable_suffix,
            "batch_snapshots": batch_snapshots,
            "unresolved_pairs": unresolved_pairs,
        }
        artifact_refs = {
            "cutover_plan": _file_ref(request.cutover_plan_path),
            "preflight": _file_ref(cutover_request.preflight_artifact),
            "cutover": _file_ref(cutover_request.cutover_artifact),
            "reconciliation": _file_ref(cutover_request.reconciliation_artifact),
            "continuation_authorization": _file_ref(
                cutover_request.continuation_authorization_artifact
            ),
            "qualification": _file_ref(cutover_request.qualification_artifact),
            "continuation_identity": _file_ref(identity_path),
            "cutoff_manifest": _file_ref(manifest_path),
            "continuation_ledger": _file_ref(ledger_path),
            "continuation_status": _file_ref(status_path),
            "continuation_result": _file_ref(request.result_artifact_path),
            "failure_audit": _file_ref(request.failure_audit_path),
        }
        recovery_module = Path(__file__).resolve()
        recovery_implementation = {
            "repository_commit": _repository_commit(),
            "recovery_module_sha256": _sha256_file(recovery_module),
            "failed_run_loaded_repository_commit": loaded_commit,
            "failed_run_implementation_commit": cutover_request.implementation_commit,
            "failed_run_implementation_artifacts": dict(sorted(implementation_artifacts.items())),
        }
        failed_lineage = {
            "v1_run_identity_hash": cutover_request.expected_v1_run_identity_hash,
            "v1_execution_contract_sha256": cutover_request.expected_execution_contract_sha256,
            "continuation_id": cutover_request.continuation_id,
            "continuation_identity_hash": identity_hash,
            "cutoff_manifest_sha256": manifest_sha256,
            "qualification_artifact_sha256": _sha256_file(cutover_request.qualification_artifact),
            "continuation_ledger_sha256": _sha256_file(ledger_path),
            "continuation_status_sha256": _sha256_file(status_path),
            "continuation_result_sha256": _sha256_file(request.result_artifact_path),
            "failure_audit_sha256": request.failure_audit_sha256,
            "artifact_refs": artifact_refs,
        }
        identity_body = {
            "schema_version": _RECOVERY_IDENTITY_SCHEMA,
            "recovery_id": request.recovery_id,
            "recovery_root": str(request.recovery_root),
            "failed_continuation_identity_hash": identity_hash,
            "failure_audit_sha256": request.failure_audit_sha256,
            "accounting_sha256": _sha256_json(accounting),
            "recovery_snapshot_sha256": _sha256_json(recovery_snapshot),
            "recovery_implementation": recovery_implementation,
        }
        recovery_identity = {**identity_body, "identity_hash": _sha256_json(identity_body)}
        durable_progress = {
            "logical_count": historical_logical,
            "historical_physical_attempts": historical_physical,
            "durable_prefix_terminal_count": len(prefix.terminal_by_pair_id),
            "durable_suffix_terminal_count": len(ledger_scan.durable_pair_ids),
        }
        payload: dict[str, object] = {
            "schema_version": _RECOVERY_PLAN_SCHEMA,
            "lifecycle": "recovery_prepared",
            "recovery_identity": recovery_identity,
            "failed_run_lineage": failed_lineage,
            "execution_contract": {
                "configured_max_concurrency": FULL_POOL_SEGMENTED_MAX_CONCURRENCY,
                "prompt_version": prefix.prompt_version,
                "provider_contract_sha256": _sha256_json(prefix.provider_contract),
                "prompt_contract_sha256": _sha256_json(prefix.prompt_contract),
                "qualification_lane_count": qualification["lane_count"],
                "qualification_provider_concurrency_reduction": qualification[
                    "provider_concurrency_reduction"
                ],
            },
            "accounting": accounting,
            "recovery_snapshot": recovery_snapshot,
            "source_inventories": {
                "frozen_prefix": frozen_inventory,
                "failed_continuation": continuation_inventory,
            },
            "status_output": {
                "lifecycle": "recovery_prepared",
                "configured_max_concurrency": FULL_POOL_SEGMENTED_MAX_CONCURRENCY,
                "worker_state": "recorded_stopped",
                "worker_pid": audit["worker_pid"],
                "durable_progress": durable_progress,
                "unresolved_count": 2,
            },
            "provider_calls": 0,
            "production_deploy_eligible": False,
        }
        protected = {
            "frozen_prefix_path": cutover_request.frozen_prefix_workspace,
            "frozen_prefix_inventory": frozen_inventory,
            "continuation_path": continuation,
            "continuation_inventory": continuation_inventory,
            "artifact_refs": artifact_refs,
        }
        return _PreparedRecovery(payload=payload, protected_inventories=protected)

    @staticmethod
    def _validate_independent_root(
        recovery_root: Path,
        cutover_request: CutoverPlanRequest,
        request: SegmentedRecoveryPlanRequest,
    ) -> None:
        source_roots = {
            cutover_request.prefix_workspace,
            cutover_request.frozen_prefix_workspace,
            cutover_request.continuation_workspace,
            cutover_request.dataset_dir,
        }
        for source in source_roots:
            if recovery_root == source or recovery_root.is_relative_to(source) or source.is_relative_to(recovery_root):
                raise ValueError("recovery_root must be independent from failed-run data roots")
        for source_file in (
            request.cutover_plan_path,
            request.result_artifact_path,
            request.failure_audit_path,
            cutover_request.qualification_artifact,
        ):
            if recovery_root == source_file or source_file.is_relative_to(recovery_root):
                raise ValueError("recovery_root must be independent from failed-run artifacts")

    def _assert_protected_unchanged(self, protected: Mapping[str, object]) -> None:
        frozen_path = cast(Path, protected["frozen_prefix_path"])
        continuation_path = cast(Path, protected["continuation_path"])
        if self.filesystem.inventory(frozen_path) != protected["frozen_prefix_inventory"]:
            raise ValueError("frozen prefix changed during recovery planning")
        if self.filesystem.inventory(continuation_path) != protected["continuation_inventory"]:
            raise ValueError("failed continuation changed during recovery planning")
        refs = _mapping(protected["artifact_refs"], "protected artifact refs")
        for label, raw in refs.items():
            ref = _mapping(raw, f"protected {label} ref")
            path = Path(_non_empty(ref.get("path"), f"protected {label} path"))
            if _file_ref(path) != ref:
                raise ValueError(f"protected {label} changed during recovery planning")


def _validate_recovery_payload(payload: Mapping[str, object], *, artifact_path: Path) -> None:
    expected_fields = {
        "schema_version",
        "lifecycle",
        "recovery_identity",
        "failed_run_lineage",
        "execution_contract",
        "accounting",
        "recovery_snapshot",
        "source_inventories",
        "status_output",
        "provider_calls",
        "production_deploy_eligible",
    }
    if set(payload) != expected_fields or payload.get("lifecycle") != "recovery_prepared":
        raise ValueError("recovery plan payload fields or lifecycle are not exact")
    accounting = _mapping(payload.get("accounting"), "recovery accounting")
    if set(accounting) != {
        "logical_cap",
        "historical_logical_count",
        "logical_retry_charge",
        "remaining_logical_cap",
        "physical_cap",
        "historical_physical_attempts",
        "unresolved_uncertainty_physical_charge",
        "future_retry_physical_attempts",
        "physical_accounting_total",
        "remaining_physical_cap",
    }:
        raise ValueError("recovery accounting fields are not exact")
    historical_logical = _strict_non_negative_int(
        accounting.get("historical_logical_count"), "historical logical count"
    )
    historical_physical = _strict_non_negative_int(
        accounting.get("historical_physical_attempts"), "historical physical attempts"
    )
    uncertainty_charge = _strict_non_negative_int(
        accounting.get("unresolved_uncertainty_physical_charge"), "uncertainty physical charge"
    )
    physical_total = _strict_non_negative_int(
        accounting.get("physical_accounting_total"), "physical accounting total"
    )
    if (
        accounting.get("logical_cap") != FULL_POOL_SEGMENTED_LOGICAL_CAP
        or accounting.get("logical_retry_charge") != 0
        or accounting.get("remaining_logical_cap")
        != FULL_POOL_SEGMENTED_LOGICAL_CAP - historical_logical
        or accounting.get("physical_cap") != FULL_POOL_SEGMENTED_PHYSICAL_CAP
        or uncertainty_charge != 2 * 3
        or accounting.get("future_retry_physical_attempts") != 0
        or physical_total != historical_physical + uncertainty_charge
        or accounting.get("remaining_physical_cap")
        != FULL_POOL_SEGMENTED_PHYSICAL_CAP - physical_total
    ):
        raise ValueError("recovery accounting charge or cap closure is crossed")

    snapshot = _mapping(payload.get("recovery_snapshot"), "recovery snapshot")
    if set(snapshot) != {
        "durable_prefix_terminals",
        "durable_suffix_terminals",
        "batch_snapshots",
        "unresolved_pairs",
    }:
        raise ValueError("recovery snapshot fields are not exact")
    unresolved = _mapping_sequence(snapshot.get("unresolved_pairs"), "recovery unresolved pairs")
    if len(unresolved) != 2:
        raise ValueError("recovery snapshot must retain exactly two unresolved pairs")
    expected_classes = ["missing_terminal_evidence", "blocked_by_prior_canonical_gap"]
    positions: list[int] = []
    for index, row in enumerate(unresolved):
        if set(row) != {
            "pair_id",
            "canonical_schedule_position",
            "classification",
            "historical_physical_attempts",
            "uncertainty_physical_charge",
            "logical_retry_charge",
        }:
            raise ValueError("recovery unresolved pair fields are not exact")
        _non_empty(row.get("pair_id"), "recovery unresolved pair id")
        position = _strict_non_negative_int(
            row.get("canonical_schedule_position"), "recovery unresolved schedule position"
        )
        _strict_non_negative_int(
            row.get("historical_physical_attempts"), "recovery unresolved historical attempts"
        )
        if (
            row.get("classification") != expected_classes[index]
            or row.get("uncertainty_physical_charge") != 3
            or row.get("logical_retry_charge") != 0
        ):
            raise ValueError("recovery unresolved accounting or classification is crossed")
        positions.append(position)
    if positions[1] != positions[0] + 1:
        raise ValueError("recovery unresolved schedule order is crossed")

    status = _mapping(payload.get("status_output"), "recovery status output")
    durable_progress = _mapping(status.get("durable_progress"), "recovery durable progress")
    prefix_terminals = _string_list(
        snapshot.get("durable_prefix_terminals"), "recovery durable prefix terminals"
    )
    suffix_terminals = _mapping_sequence(
        snapshot.get("durable_suffix_terminals"), "recovery durable suffix terminals"
    )
    if (
        durable_progress.get("logical_count") != historical_logical
        or durable_progress.get("historical_physical_attempts") != historical_physical
        or durable_progress.get("durable_prefix_terminal_count") != len(prefix_terminals)
        or durable_progress.get("durable_suffix_terminal_count") != len(suffix_terminals)
    ):
        raise ValueError("recovery status durable progress is crossed with accounting or snapshot")

    identity = _mapping(payload.get("recovery_identity"), "recovery identity")
    if set(identity) != {
        "schema_version",
        "recovery_id",
        "recovery_root",
        "failed_continuation_identity_hash",
        "failure_audit_sha256",
        "accounting_sha256",
        "recovery_snapshot_sha256",
        "recovery_implementation",
        "identity_hash",
    }:
        raise ValueError("recovery identity fields are not exact")
    identity_body = {key: value for key, value in identity.items() if key != "identity_hash"}
    if (
        identity.get("schema_version") != _RECOVERY_IDENTITY_SCHEMA
        or identity.get("recovery_root") != str(artifact_path.parent)
        or _RECOVERY_ID.fullmatch(_non_empty(identity.get("recovery_id"), "recovery id")) is None
        or identity.get("accounting_sha256") != _sha256_json(accounting)
        or identity.get("recovery_snapshot_sha256") != _sha256_json(snapshot)
        or identity.get("identity_hash") != _sha256_json(identity_body)
    ):
        raise ValueError("recovery identity hash closure is crossed")


def _scan_ledger(raw: bytes, *, expected_identity_hash: str) -> _LedgerScan:
    dispatched: list[str] = []
    durable: list[str] = []
    terminal_refs: list[_LedgerTerminalRef] = []
    evidence_attempts: dict[str, int] = {}
    actual_attempts: dict[str, int] = {}
    kernel_snapshots: list[dict[str, object]] = []
    kernel_commits: list[dict[str, object]] = []
    wave_count = 0
    wave_physical = 0
    for line_number, line in enumerate(raw.splitlines(keepends=True), start=1):
        if not line.endswith(b"\n"):
            raise ValueError("continuation ledger bytes are truncated")
        record_bytes = line[:-1]
        record = _mapping(json.loads(record_bytes), f"recovery ledger line {line_number}")
        if record_bytes != _canonical_json(record).encode("utf-8"):
            raise ValueError("continuation ledger bytes are not canonical")
        if set(record) != _LEDGER_FIELDS:
            raise ValueError("continuation ledger record fields are not exact")
        if (
            record.get("schema_version") != _CONTINUATION_LEDGER_SCHEMA
            or record.get("continuation_identity_hash") != expected_identity_hash
        ):
            raise ValueError("continuation ledger schema or identity is crossed")
        event_type = _non_empty(record.get("event_type"), "continuation ledger event type")
        if event_type not in _LEDGER_PAYLOAD_FIELDS:
            raise ValueError("continuation ledger event type is unsupported for recovery")
        payload = _mapping(record.get("payload"), "continuation ledger payload")
        if set(payload) != _LEDGER_PAYLOAD_FIELDS[event_type]:
            raise ValueError(f"continuation ledger {event_type} payload fields are not exact")
        if event_type == "pair_dispatched":
            dispatched.append(_non_empty(payload.get("pair_id"), "dispatched pair id"))
        elif event_type == "wave_accounting":
            pair_ids = _string_list(payload.get("pair_ids"), "wave pair ids")
            lanes = _mapping_sequence(payload.get("lanes"), "wave lanes")
            if len(pair_ids) != len(lanes):
                raise ValueError("wave lane denominator is crossed")
            lane_total = 0
            for lane_id, (pair_id, lane) in enumerate(zip(pair_ids, lanes, strict=True)):
                if set(lane) != _WAVE_LANE_FIELDS or lane.get("lane_id") != lane_id or lane.get("pair_id") != pair_id:
                    raise ValueError("wave lane accounting fields or order are crossed")
                evidence = _strict_non_negative_int(
                    lane.get("terminal_evidence_request_invocations"), "terminal evidence attempts"
                )
                actual = _strict_non_negative_int(lane.get("actual_physical_attempts"), "actual attempts")
                evidence_attempts[pair_id] = evidence
                actual_attempts[pair_id] = actual
                lane_total += actual
            declared = _strict_non_negative_int(
                payload.get("actual_physical_attempts"), "wave physical attempts"
            )
            if declared != lane_total:
                raise ValueError("wave physical accounting total is crossed")
            wave_physical += declared
            wave_count += 1
        elif event_type == "pair_terminal":
            pair_id = _non_empty(payload.get("pair_id"), "durable pair id")
            durable.append(pair_id)
            terminal_refs.append(
                _LedgerTerminalRef(
                    pair_id=pair_id,
                    sequence=_strict_non_negative_int(record.get("sequence"), "terminal ledger sequence"),
                    payload_sha256=_sha256_json(payload),
                )
            )
        elif event_type == "kernel_batch_snapshot":
            kernel_snapshots.append(dict(payload))
        elif event_type == "kernel_batch_committed":
            kernel_commits.append(dict(payload))
    return _LedgerScan(
        dispatched_pair_ids=tuple(dispatched),
        durable_pair_ids=tuple(durable),
        durable_terminal_refs=tuple(terminal_refs),
        terminal_evidence_attempts=evidence_attempts,
        actual_physical_attempts=actual_attempts,
        wave_count=wave_count,
        wave_physical_attempts=wave_physical,
        kernel_snapshots=tuple(kernel_snapshots),
        kernel_commits=tuple(kernel_commits),
    )


def _recovery_batch_snapshots(
    *,
    continuation: Path,
    prefix: _FrozenPrefix,
    identity: Mapping[str, object],
    ledger_scan: _LedgerScan,
) -> tuple[list[dict[str, object]], dict[str, int], set[str]]:
    prefix_terminal_ids = set(prefix.terminal_by_pair_id)
    batches: dict[int, dict[str, object]] = {}
    expected_files: set[str] = set()
    for committed in prefix.committed_batches:
        time_step = _strict_non_negative_int(committed.get("time_step"), "prefix batch time_step")
        pair_ids = _string_list(committed.get("ordered_pair_ids"), "prefix committed pair ids")
        terminal_ids = _string_list(committed.get("ordered_terminal_ids"), "prefix committed terminal ids")
        if len(pair_ids) != len(terminal_ids):
            raise ValueError("prefix committed batch terminal denominator is crossed")
        batches[time_step] = {
            "time_step": time_step,
            "state": "committed",
            "candidate_schedule_pair_ids": pair_ids,
            "candidate_schedule_positions": [
                _strict_non_negative_int(
                    prefix.plan_by_pair_id[pair_id].get("pair_schedule_position"),
                    "prefix schedule position",
                )
                for pair_id in pair_ids
            ],
            "candidate_schedule_sha256": _sha256_json(pair_ids),
            "snapshot_ref": committed.get("spool_ref"),
            "frozen_feedback_user_ids": _string_list(
                committed.get("frozen_feedback_user_ids"), "prefix frozen feedback"
            ),
            "committed_feedback_user_ids": _string_list(
                committed.get("committed_feedback_user_ids"), "prefix committed feedback"
            ),
        }
    active = prefix.active_batch
    active_time = _strict_non_negative_int(active.get("time_step"), "prefix active time_step")
    active_pairs = _string_list(active.get("ordered_pair_ids"), "prefix active pair ids")
    batches[active_time] = {
        "time_step": active_time,
        "state": "active_incomplete",
        "candidate_schedule_pair_ids": active_pairs,
        "candidate_schedule_positions": [
            _strict_non_negative_int(
                prefix.plan_by_pair_id[pair_id].get("pair_schedule_position"),
                "prefix schedule position",
            )
            for pair_id in active_pairs
        ],
        "candidate_schedule_sha256": _sha256_json(active_pairs),
        "snapshot_ref": active.get("snapshot_ref"),
        "frozen_feedback_user_ids": _string_list(
            active.get("frozen_feedback_user_ids"), "active frozen feedback"
        ),
        "committed_feedback_user_ids": [],
    }

    snapshot_hash_by_time: dict[int, str] = {
        active_time: _non_empty(active.get("batch_snapshot_hash"), "active snapshot hash")
    }
    for snapshot in ledger_scan.kernel_snapshots:
        if snapshot.get("snapshot_type") != "batch_plan":
            raise ValueError("recovery accepts batch-plan kernel snapshots only")
        identity_raw = _mapping(snapshot.get("snapshot_identity"), "kernel snapshot identity")
        if set(identity_raw) != {"time_step"}:
            raise ValueError("kernel snapshot identity fields are not exact")
        time_step = _strict_non_negative_int(identity_raw.get("time_step"), "kernel snapshot time_step")
        relative = _safe_relative_path(snapshot.get("snapshot_path"), "kernel snapshot path")
        path = _require_regular_file(continuation / relative, "kernel snapshot")
        document = _read_json(path)
        if path.read_bytes() != _canonical_json(document).encode("utf-8"):
            raise ValueError("kernel snapshot bytes are not canonical")
        snapshot_hash = _non_empty(snapshot.get("snapshot_hash"), "kernel snapshot hash")
        if (
            set(document) != {"schema_version", "snapshot_type", "snapshot_identity", "payload"}
            or document.get("schema_version") != "concurrent-message-execution-snapshot-v1"
            or document.get("snapshot_type") != "batch_plan"
            or document.get("snapshot_identity") != identity_raw
            or _sha256_json(document) != snapshot_hash
        ):
            raise ValueError("kernel snapshot bytes or identity are crossed")
        payload = _mapping(document.get("payload"), "kernel snapshot payload")
        if (
            payload.get("schema_version") != "concurrent-message-execution-snapshot-v1"
            or payload.get("snapshot_type") != "batch_plan"
            or payload.get("snapshot_identity") != identity_raw
            or payload.get("time_step") != time_step
            or payload.get("terminal_variants") != ["primary"]
        ):
            raise ValueError("kernel batch-plan payload is crossed")
        plans: list[dict[str, object]] = []
        for message in _mapping_sequence(payload.get("messages"), "kernel snapshot messages"):
            plans.extend(_mapping_sequence(message.get("selected_pair_plans"), "selected pair plans"))
        plans.sort(key=lambda row: _strict_non_negative_int(row.get("pair_schedule_position"), "schedule position"))
        pair_ids = [_non_empty(row.get("pair_id"), "scheduled pair id") for row in plans]
        pair_positions = [
            _strict_non_negative_int(row.get("pair_schedule_position"), "scheduled pair position")
            for row in plans
        ]
        if (
            payload.get("planned_pair_count") != len(pair_ids)
            or payload.get("planned_variant_count") != len(pair_ids)
            or len(set(pair_ids)) != len(pair_ids)
            or any(row.get("time_step") != time_step for row in plans)
        ):
            raise ValueError("kernel candidate schedule denominator is crossed")
        if time_step in batches:
            raise ValueError("duplicate kernel batch snapshot time_step")
        batches[time_step] = {
            "time_step": time_step,
            "state": "active_incomplete",
            "candidate_schedule_pair_ids": pair_ids,
            "candidate_schedule_positions": pair_positions,
            "candidate_schedule_sha256": _sha256_json(pair_ids),
            "snapshot_ref": {
                "relative_path": relative.as_posix(),
                "sha256": _sha256_file(path),
                "snapshot_hash": snapshot_hash,
            },
            "frozen_feedback_user_ids": _string_list(
                payload.get("frozen_campaign_engaged_user_ids"), "kernel frozen feedback"
            ),
            "committed_feedback_user_ids": [],
        }
        snapshot_hash_by_time[time_step] = snapshot_hash
        expected_files.add(relative.as_posix())

    for commit in ledger_scan.kernel_commits:
        event_identity = _mapping(commit.get("event_identity"), "kernel commit identity")
        commit_payload = _mapping(commit.get("payload"), "kernel commit payload")
        if set(event_identity) != {"time_step"} or set(commit_payload) != {
            "time_step",
            "committed_user_ids",
            "committed_user_count",
            "batch_pair_count",
            "batch_spool_chunk",
        }:
            raise ValueError("kernel commit fields are not exact")
        time_step = _strict_non_negative_int(event_identity.get("time_step"), "kernel commit time_step")
        if commit_payload.get("time_step") != time_step or time_step not in batches:
            raise ValueError("kernel commit is crossed with its candidate schedule")
        committed_ids = _string_list(commit_payload.get("committed_user_ids"), "kernel committed feedback")
        batch = batches[time_step]
        pair_ids = cast(list[str], batch["candidate_schedule_pair_ids"])
        if (
            commit.get("batch_snapshot_hash") != snapshot_hash_by_time.get(time_step)
            or commit_payload.get("committed_user_count") != len(committed_ids)
            or commit_payload.get("batch_pair_count") != len(pair_ids)
        ):
            raise ValueError("kernel commit denominator or snapshot hash is crossed")
        spool_ref = _mapping(commit_payload.get("batch_spool_chunk"), "kernel spool ref")
        relative = _safe_relative_path(spool_ref.get("relative_path"), "kernel spool path")
        spool_path = _require_regular_file(continuation / relative, "kernel spool")
        if (
            spool_ref.get("schema_version") != "concurrent-runtime-batch-spool-ref-v1"
            or spool_ref.get("time_step") != time_step
            or spool_ref.get("identity_hash") != identity.get("identity_hash")
            or spool_ref.get("run_id") != identity.get("run_id")
            or spool_ref.get("terminal_variants") != ["primary"]
            or spool_ref.get("batch_snapshot_hash") != snapshot_hash_by_time.get(time_step)
            or spool_ref.get("sha256") != _sha256_file(spool_path)
        ):
            raise ValueError("kernel committed spool is crossed")
        row_counts = _mapping(spool_ref.get("row_counts"), "kernel spool row counts")
        if (
            row_counts.get("result_rows") != len(pair_ids)
            or row_counts.get("terminal_rows") != len(pair_ids)
            or row_counts.get("variant_evidence_rows") != len(pair_ids)
        ):
            raise ValueError("kernel committed spool terminal denominator is crossed")
        batch["state"] = "committed"
        batch["committed_feedback_user_ids"] = committed_ids
        batch["spool_ref"] = spool_ref
        expected_files.add(relative.as_posix())

    ordered = [batches[key] for key in sorted(batches)]
    if [batch["time_step"] for batch in ordered] != list(range(len(ordered))):
        raise ValueError("persisted batch schedule has a time-step gap")
    cumulative_feedback: set[str] = set()
    schedule_positions: dict[str, int] = {}
    expected_position = 0
    durable_pair_ids = prefix_terminal_ids | set(ledger_scan.durable_pair_ids)
    for index, batch in enumerate(ordered):
        frozen = _string_list(batch["frozen_feedback_user_ids"], "batch frozen feedback")
        if frozen != sorted(cumulative_feedback):
            raise ValueError("batch feedback barrier is crossed")
        pair_ids = cast(list[str], batch["candidate_schedule_pair_ids"])
        positions = cast(list[int], batch["candidate_schedule_positions"])
        if len(positions) != len(pair_ids):
            raise ValueError("candidate schedule position denominator is crossed")
        for pair_id, position in zip(pair_ids, positions, strict=True):
            if position != expected_position or pair_id in schedule_positions:
                raise ValueError("candidate schedule positions are not canonical")
            schedule_positions[pair_id] = position
            expected_position += 1
        committed = _string_list(batch["committed_feedback_user_ids"], "batch committed feedback")
        if batch["state"] == "committed":
            if any(pair_id not in durable_pair_ids for pair_id in pair_ids):
                raise ValueError("committed batch lacks a durable terminal")
            cumulative_feedback.update(committed)
        elif index != len(ordered) - 1:
            raise ValueError("only the final persisted batch may be incomplete")
        batch["durable_terminal_pair_ids"] = [pair_id for pair_id in pair_ids if pair_id in durable_pair_ids]
    return ordered, schedule_positions, expected_files


def _unresolved_snapshot(
    unknown_pair_ids: Sequence[str],
    *,
    schedule_positions: Mapping[str, int],
    ledger_scan: _LedgerScan,
    maximum_attempts: int,
) -> list[dict[str, object]]:
    if len(unknown_pair_ids) != 2:
        raise ValueError("recovery plan requires exactly two unresolved pairs")
    first, second = unknown_pair_ids
    if schedule_positions.get(second) != schedule_positions.get(first, -2) + 1:
        raise ValueError("unresolved pairs are not adjacent in canonical schedule order")
    if ledger_scan.terminal_evidence_attempts.get(first) != 0:
        raise ValueError("first unresolved pair must lack terminal evidence")
    if ledger_scan.terminal_evidence_attempts.get(second, 0) < 1:
        raise ValueError("second unresolved pair must be blocked only by the prior canonical gap")
    return [
        {
            "pair_id": pair_id,
            "canonical_schedule_position": schedule_positions[pair_id],
            "classification": classification,
            "historical_physical_attempts": ledger_scan.actual_physical_attempts[pair_id],
            "uncertainty_physical_charge": maximum_attempts,
            "logical_retry_charge": 0,
        }
        for pair_id, classification in (
            (first, "missing_terminal_evidence"),
            (second, "blocked_by_prior_canonical_gap"),
        )
    ]


def _validate_failure_audit(
    audit: Mapping[str, object],
    *,
    request: SegmentedRecoveryPlanRequest,
    cutover_request: CutoverPlanRequest,
    plan_sha256: str,
    ledger_path: Path,
    status_path: Path,
    qualification_path: Path,
    result_path: Path,
    prefix_logical: int,
    status: Mapping[str, object],
    ledger_scan: _LedgerScan,
    unknown_pair_ids: Sequence[str],
) -> None:
    expected = {
        "schema_version": _FAILURE_AUDIT_SCHEMA,
        "plan_path": str(request.cutover_plan_path),
        "plan_sha256": plan_sha256,
        "continuation_workspace": str(cutover_request.continuation_workspace),
        "worker_running": False,
        "lifecycle": "reconciliation_required",
        "configured_max_concurrency": FULL_POOL_SEGMENTED_MAX_CONCURRENCY,
        "prefix_logical_count": prefix_logical,
        "logical_count": status["logical_count"],
        "physical_attempt_count": status["physical_attempt_count"],
        "suffix_dispatched_count": len(ledger_scan.dispatched_pair_ids),
        "suffix_terminal_count": len(ledger_scan.durable_pair_ids),
        "unknown_pair_count": 2,
        "unknown_pair_ids": list(unknown_pair_ids),
        "zero_terminal_evidence_count": 1,
        "canonical_drain_blocked_following_pair_count": 1,
        "accounted_wave_count": ledger_scan.wave_count,
        "accounted_suffix_physical_attempts": ledger_scan.wave_physical_attempts,
        "continuation_ledger_bytes": ledger_path.stat().st_size,
        "continuation_ledger_sha256": _sha256_file(ledger_path),
        "continuation_status_sha256": _sha256_file(status_path),
        "qualification_artifact_sha256": _sha256_file(qualification_path),
        "qualification_lane_count": FULL_POOL_SEGMENTED_MAX_CONCURRENCY,
        "result_artifact_sha256": _sha256_file(result_path),
        "automatic_retry_performed": False,
        "recovery_authorized": False,
        "production_deploy_eligible": False,
        "raw_prompt_request_response_persisted": False,
    }
    if set(audit) != _FAILURE_AUDIT_FIELDS:
        raise ValueError("failure audit fields are not exact")
    if not isinstance(audit.get("recorded_at"), str) or not cast(str, audit["recorded_at"]).strip():
        raise ValueError("failure audit recorded_at is missing")
    if not isinstance(audit.get("worker_pid"), int) or isinstance(audit.get("worker_pid"), bool):
        raise ValueError("failure audit worker_pid is invalid")
    for field, value in expected.items():
        if audit.get(field) != value:
            raise ValueError(f"failure audit {field} is crossed")


def _repository_commit() -> str:
    repository = Path(__file__).resolve().parents[2]
    process = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    commit = process.stdout.strip()
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ValueError("recovery implementation commit is invalid")
    return commit


def _safe_relative_path(value: object, context: str) -> PurePosixPath:
    token = PurePosixPath(_non_empty(value, context))
    if token.is_absolute() or ".." in token.parts or token.as_posix() in {"", "."}:
        raise ValueError(f"{context} must be a safe relative path")
    return token


def _file_ref(path_raw: Path) -> dict[str, object]:
    path = _require_regular_file(path_raw, "artifact")
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": _sha256_file(path)}


def _exclusive_write_json(path: Path, payload: Mapping[str, object]) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o644)
    try:
        body = (_canonical_json(payload) + "\n").encode("utf-8")
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _require_regular_file(path: Path, context: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{context} must be an explicit regular file")
    return path


def _read_json(path: Path) -> dict[str, object]:
    return _mapping(json.loads(path.read_bytes()), f"JSON object {path}")


def _mapping(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be an object")
    return {str(key): item for key, item in value.items()}


def _mapping_sequence(value: object, context: str) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{context} must be an array")
    return [_mapping(item, context) for item in value]


def _string_list(value: object, context: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{context} must be an array")
    result = list(value)
    if any(not isinstance(item, str) or not item for item in result):
        raise ValueError(f"{context} must contain non-empty strings")
    return cast(list[str], result)


def _non_empty(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be a non-empty string")
    return value


def _strict_non_negative_int(value: object, context: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{context} must be a non-negative integer")
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
