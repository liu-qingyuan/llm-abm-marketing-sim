from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ._concurrent_runtime_spool import _ConcurrentRuntimeBatchSpool
from .full_pool_formal_experiment import (
    FULL_POOL_FORMAL_REQUESTED_MODEL,
    FULL_POOL_FORMAL_REQUIRED_OBSERVED_MODEL,
)
from .full_pool_segmented_continuation import (
    FULL_POOL_SEGMENTED_LOGICAL_CAP,
    FULL_POOL_SEGMENTED_MAX_CONCURRENCY,
    FULL_POOL_SEGMENTED_PHYSICAL_CAP,
)
from .full_pool_segmented_operator import LocalOperatorFilesystem
from .full_pool_segmented_recovery import FullPoolSegmentedRecoveryPreflight
from .full_pool_segmented_recovery_execution import (
    FullPoolSegmentedRecovery,
    SegmentedRecoveryExecutionRequest,
    SegmentedRecoveryExecutionResult,
    _read_failed_ledger,
    _recovery_documents,
    _snapshot_documents,
)

_NESTED_RECOVERY_PLAN_SCHEMA = "full-pool-segmented-nested-recovery-plan-v2"
_NESTED_RECOVERY_PLAN_ENVELOPE_SCHEMA = (
    "full-pool-segmented-nested-recovery-plan-envelope-v2"
)
_NESTED_RECOVERY_IDENTITY_SCHEMA = "full-pool-segmented-nested-recovery-identity-v2"
_NESTED_RECOVERY_HANDOFF_SCHEMA = (
    "full-pool-segmented-nested-recovery-human-authorization-handoff-v2"
)
_NESTED_RECOVERY_ARTIFACT_FILE = "nested-recovery-plan.json"
_PARENT_AUTHORIZATION_ENVELOPE_SCHEMA = (
    "full-pool-segmented-recovery-human-authorization-envelope-v1"
)
_PARENT_RECOVERY_IDENTITY_SCHEMA = "full-pool-segmented-recovery-execution-identity-v1"
_PARENT_RECOVERY_MANIFEST_ENVELOPE_SCHEMA = (
    "full-pool-segmented-recovery-cutoff-envelope-v1"
)
_PARENT_RECOVERY_STATUS_SCHEMA = "full-pool-segmented-recovery-status-v1"
_PARENT_CONTINUATION_STATUS_SCHEMA = "full-pool-segmented-continuation-status-v1"
_PARENT_RESULT_WRAPPER_SCHEMA = "full-pool-ticket-205-live-recovery-result-v1"
_PARENT_IDENTITY_FILE = "segmented_continuation_identity.json"
_PARENT_MANIFEST_FILE = "cutoff_manifest.json"
_PARENT_LEDGER_FILE = "segmented_continuation_ledger.jsonl"
_PARENT_CONTINUATION_STATUS_FILE = "segmented_continuation_status.json"
_PARENT_RECOVERY_STATUS_FILE = "segmented_recovery_status.json"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_RECOVERY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")

_PARENT_RESULT_WRAPPER_FIELDS = frozenset(
    {
        "schema_version",
        "recorded_at",
        "implementation_commit",
        "recovery_plan_sha256",
        "human_authorization_sha256",
        "configured_max_concurrency",
        "observed_external_request_invocations",
        "subscription_billed_cost_usd",
        "subscription_nominal_cost_usd",
        "raw_prompt_request_response_persisted",
        "result",
    }
)
_PARENT_CONTINUATION_STATUS_FIELDS = frozenset(
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
        "source_root_relative_path",
        "source_manifest_sha256",
        "production_deploy_eligible",
    }
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SegmentedNestedRecoveryPlanRequest(_FrozenModel):
    """Explicit stopped recovery and independent create-once plan destinations."""

    parent_recovery_plan_path: Path
    parent_authorization_path: Path
    stopped_workspace: Path
    execution_result_path: Path
    execution_result_sha256: str
    recovery_id: str = Field(min_length=1, max_length=160)
    recovery_root: Path
    proposed_authorization_path: Path
    proposed_recovery_workspace: Path

    @field_validator(
        "parent_recovery_plan_path",
        "parent_authorization_path",
        "stopped_workspace",
        "execution_result_path",
        "recovery_root",
        "proposed_authorization_path",
        "proposed_recovery_workspace",
        mode="before",
    )
    @classmethod
    def _absolute_path(cls, value: object) -> Path:
        return Path(cast(str | Path, value)).expanduser().absolute()

    @field_validator("execution_result_sha256")
    @classmethod
    def _hash(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("execution_result_sha256 must be a lowercase SHA-256 digest")
        return value

    @field_validator("recovery_id")
    @classmethod
    def _identity(cls, value: str) -> str:
        if _RECOVERY_ID.fullmatch(value) is None:
            raise ValueError("recovery_id contains unsupported characters")
        return value

    @model_validator(mode="after")
    def _independent_paths(self) -> SegmentedNestedRecoveryPlanRequest:
        source_files = {
            self.parent_recovery_plan_path,
            self.parent_authorization_path,
            self.execution_result_path,
        }
        if len(source_files) != 3:
            raise ValueError("parent plan, authorization, and execution result must be distinct")
        outputs = {
            self.recovery_root,
            self.proposed_authorization_path,
            self.proposed_recovery_workspace,
        }
        if len(outputs) != 3:
            raise ValueError("nested recovery output paths must be distinct")
        sources = (*source_files, self.stopped_workspace)
        for output in outputs:
            for source in sources:
                if output == source or output.is_relative_to(source) or source.is_relative_to(output):
                    raise ValueError("nested recovery outputs must be independent from persisted inputs")
        for left in outputs:
            for right in outputs:
                if left == right:
                    continue
                if left.is_relative_to(right) or right.is_relative_to(left):
                    raise ValueError("nested recovery outputs must not contain one another")
        return self


class SegmentedNestedRecoveryPlanResult(_FrozenModel):
    status: Literal["recovery_prepared"]
    artifact_path: Path
    artifact_sha256: str
    configured_max_concurrency: Literal[10]
    worker_state: Literal["recorded_stopped"]
    durable_terminal_count: int = Field(ge=0)
    unresolved_count: Literal[7]
    provider_calls: Literal[0] = 0
    production_deploy_eligible: Literal[False] = False

    @field_validator("artifact_sha256")
    @classmethod
    def _artifact_hash(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("artifact_sha256 must be a lowercase SHA-256 digest")
        return value


@dataclass(frozen=True)
class _StoppedRecoveryContract:
    parent_recovery_plan_sha256: str
    parent_authorization_sha256: str
    stopped_identity_hash: str
    stopped_identity_file_sha256: str
    stopped_manifest_sha256: str
    stopped_manifest_file_sha256: str
    stopped_ledger_sha256: str
    stopped_workspace_inventory_sha256: str
    stopped_continuation_status_sha256: str
    stopped_recovery_status_sha256: str
    execution_result_sha256: str
    implementation_commit: str
    historical_logical_count: int
    historical_physical_attempts: int
    imported_durable_terminal_count: int
    durable_terminal_count: int
    explicit_dispatched_count: int
    explicit_durable_terminal_count: int
    explicit_physical_attempts: int
    committed_batch_count: int
    accounted_wave_count: int
    ledger_sequence: int
    recovered_pair_ids: tuple[str, ...]
    unknown_pair_ids: tuple[str, ...]
    unknown_schedule_positions: tuple[int, ...]


_EXPECTED_STOPPED_RECOVERY = _StoppedRecoveryContract(
    parent_recovery_plan_sha256=(
        "a4f8ca4f178e9a233fcabca8ea0d5f5aa50d39b6e929a04fbe5465bd0f4d4be0"
    ),
    parent_authorization_sha256=(
        "841bfe1f96ac4c501f3f0c990b2174251eea64c3ed96909d4c3fed639c12ccd1"
    ),
    stopped_identity_hash=(
        "8dffaa914b5f69da8baaee27cfdc5b1dacdb075af38aef65b22e41b1195f53dc"
    ),
    stopped_identity_file_sha256=(
        "2ce3d0996eeeaf65060cd677af871c06143c380f53c9d5569a7ce4a52398ba6a"
    ),
    stopped_manifest_sha256=(
        "0ec5ef15f06e24b36807441a9b5dc4a26a891359f70fa2a36c3f5251eca82e00"
    ),
    stopped_manifest_file_sha256=(
        "29ae5ce61bfb7317414dc59481984561f32a054014bc440408ec2de73bbd9dda"
    ),
    stopped_ledger_sha256=(
        "0e419723d20e2821f8764801abb9edc51178ac92a3c2a9f670e4821a0cc0627a"
    ),
    stopped_workspace_inventory_sha256=(
        "3f3e517db1681cac5bab71ca826f67a711ee5c77860f28593583e2a67a45fcd2"
    ),
    stopped_continuation_status_sha256=(
        "585dd9f487c7234fa2e25439733aa5c474b1864193edca21c2e5f348e99a56a9"
    ),
    stopped_recovery_status_sha256=(
        "eab4db3f10b6fb8a881a48648039761c6b4b0e6092669074117a7b0a2a70ec01"
    ),
    execution_result_sha256=(
        "bbc52b7758927f7c91a2871d48b2aea9a1d7b9dbb5ebae6af45c2939ea16254f"
    ),
    implementation_commit="b099a7688128373aba30d919dfdeb39e481f7286",
    historical_logical_count=90_068,
    historical_physical_attempts=90_891,
    imported_durable_terminal_count=18_998,
    durable_terminal_count=90_061,
    explicit_dispatched_count=71_070,
    explicit_durable_terminal_count=71_063,
    explicit_physical_attempts=71_768,
    committed_batch_count=24,
    accounted_wave_count=7_123,
    ledger_sequence=364_024,
    recovered_pair_ids=(
        "70400636033:message_1:5",
        "70401299326:message_1:5",
    ),
    unknown_pair_ids=(
        "2726385359791149:message_3:24",
        "2726385761915815:message_3:24",
        "2726399652412872:message_3:24",
        "2726419687015373:message_3:24",
        "2727683308:message_3:24",
        "2728328409650713:message_3:24",
        "2729447809097123:message_3:24",
    ),
    unknown_schedule_positions=tuple(range(90_061, 90_068)),
)


@dataclass(frozen=True)
class _PreparedNestedRecovery:
    payload: dict[str, object]
    observed_contract: _StoppedRecoveryContract
    protected: dict[str, object]


class FullPoolSegmentedNestedRecoveryPreflight:
    """Publish one read-only, nondeployable second-recovery plan.

    The Interface accepts no Adapter, Provider client, live gate, or authorization
    boolean. Existing recovery artifacts are reclosed before one independent plan is
    created with provider_calls fixed to zero.
    """

    def __init__(self, *, filesystem: LocalOperatorFilesystem | None = None) -> None:
        self.filesystem = filesystem or LocalOperatorFilesystem()

    def prepare(
        self,
        request: SegmentedNestedRecoveryPlanRequest,
    ) -> SegmentedNestedRecoveryPlanResult:
        for output in (
            request.recovery_root,
            request.proposed_authorization_path,
            request.proposed_recovery_workspace,
        ):
            if output.exists() or output.is_symlink():
                raise FileExistsError("nested recovery output paths must be new")
        prepared = self._prepare_payload(request)
        if prepared.observed_contract != _EXPECTED_STOPPED_RECOVERY:
            raise ValueError("stopped recovery does not match the exact Issue #205 second-recovery contract")
        self._assert_protected_unchanged(prepared.protected)
        artifact_path = request.recovery_root / _NESTED_RECOVERY_ARTIFACT_FILE
        try:
            request.recovery_root.mkdir(parents=False)
            envelope = {
                "schema_version": _NESTED_RECOVERY_PLAN_ENVELOPE_SCHEMA,
                "payload": prepared.payload,
                "payload_sha256": _sha256_json(prepared.payload),
            }
            _exclusive_write_json(artifact_path, envelope)
            artifact_path.chmod(0o444)
            _fsync_directory(request.recovery_root)
            self._assert_protected_unchanged(prepared.protected)
            return self.status(artifact_path)
        except BaseException:
            if artifact_path.exists() and not artifact_path.is_symlink():
                artifact_path.chmod(0o644)
                artifact_path.unlink()
            if request.recovery_root.is_dir():
                request.recovery_root.rmdir()
            raise

    def status(self, artifact_path: str | Path) -> SegmentedNestedRecoveryPlanResult:
        path = _require_regular_file(
            Path(artifact_path).expanduser().absolute(), "nested recovery plan"
        )
        envelope = _read_json(path)
        if set(envelope) != {"schema_version", "payload", "payload_sha256"}:
            raise ValueError("nested recovery plan envelope fields are not exact")
        if envelope.get("schema_version") != _NESTED_RECOVERY_PLAN_ENVELOPE_SCHEMA:
            raise ValueError("nested recovery plan envelope schema is unsupported")
        payload = _mapping(envelope.get("payload"), "nested recovery plan payload")
        if envelope.get("payload_sha256") != _sha256_json(payload):
            raise ValueError("nested recovery plan payload hash mismatch")
        _validate_nested_recovery_payload(payload, artifact_path=path)
        status = _mapping(payload.get("status_output"), "nested recovery status")
        durable = _strict_non_negative_int(
            status.get("durable_terminal_count"), "durable terminal count"
        )
        return SegmentedNestedRecoveryPlanResult(
            status="recovery_prepared",
            artifact_path=path,
            artifact_sha256=_sha256_file(path),
            configured_max_concurrency=FULL_POOL_SEGMENTED_MAX_CONCURRENCY,
            worker_state="recorded_stopped",
            durable_terminal_count=durable,
            unresolved_count=7,
            provider_calls=0,
            production_deploy_eligible=False,
        )

    def _prepare_payload(
        self,
        request: SegmentedNestedRecoveryPlanRequest,
    ) -> _PreparedNestedRecovery:
        parent_plan_path = _require_regular_file(
            request.parent_recovery_plan_path, "parent recovery plan"
        )
        parent_plan_sha256 = _sha256_file(parent_plan_path)
        FullPoolSegmentedRecoveryPreflight().status(parent_plan_path)
        parent_plan_envelope = _read_json(parent_plan_path)
        parent_plan = _mapping(parent_plan_envelope.get("payload"), "parent recovery plan payload")

        parent_authorization_path = _require_regular_file(
            request.parent_authorization_path, "parent human authorization"
        )
        parent_authorization_sha256 = _sha256_file(parent_authorization_path)
        parent_authorization_envelope = _read_json(parent_authorization_path)
        if set(parent_authorization_envelope) != {
            "schema_version",
            "payload",
            "payload_sha256",
        } or parent_authorization_envelope.get(
            "schema_version"
        ) != _PARENT_AUTHORIZATION_ENVELOPE_SCHEMA:
            raise ValueError("parent human authorization envelope is not exact")
        parent_authorization = _mapping(
            parent_authorization_envelope.get("payload"), "parent authorization payload"
        )
        if parent_authorization_envelope.get("payload_sha256") != _sha256_json(
            parent_authorization
        ):
            raise ValueError("parent human authorization payload hash mismatch")
        authorized_at = _utc_datetime(
            parent_authorization.get("authorized_at"), "parent authorization timestamp"
        )
        parent_request = SegmentedRecoveryExecutionRequest(
            recovery_plan_path=parent_plan_path,
            recovery_plan_sha256=parent_plan_sha256,
            authorization_path=parent_authorization_path,
            authorization_sha256=parent_authorization_sha256,
            recovery_id=_non_empty(
                parent_authorization.get("recovery_id"), "parent recovery id"
            ),
            recovery_workspace=request.stopped_workspace,
        )
        parent_module = FullPoolSegmentedRecovery(now=lambda: authorized_at)
        parent_inputs = parent_module._validated_inputs(parent_request)
        parent_documents = _recovery_documents(parent_request, parent_inputs)

        workspace = request.stopped_workspace
        if workspace.is_symlink() or not workspace.is_dir():
            raise ValueError("stopped recovery workspace must be one real directory")
        for forbidden in (workspace / "source-v2", workspace / ".source-v2.staging"):
            if forbidden.exists() or forbidden.is_symlink():
                raise ValueError("stopped recovery workspace unexpectedly contains source-v2")
        workspace_inventory = self.filesystem.inventory(workspace)
        identity_path = workspace / _PARENT_IDENTITY_FILE
        manifest_path = workspace / _PARENT_MANIFEST_FILE
        ledger_path = workspace / _PARENT_LEDGER_FILE
        continuation_status_path = workspace / _PARENT_CONTINUATION_STATUS_FILE
        recovery_status_path = workspace / _PARENT_RECOVERY_STATUS_FILE

        identity = _read_json(_require_regular_file(identity_path, "stopped recovery identity"))
        if identity != parent_documents.identity or identity.get(
            "schema_version"
        ) != _PARENT_RECOVERY_IDENTITY_SCHEMA:
            raise ValueError("stopped recovery identity is crossed with its parent authorization")
        manifest_envelope = _read_json(
            _require_regular_file(manifest_path, "stopped recovery manifest")
        )
        expected_manifest_envelope = {
            "schema_version": _PARENT_RECOVERY_MANIFEST_ENVELOPE_SCHEMA,
            "manifest": parent_documents.manifest,
            "manifest_sha256": parent_documents.manifest_sha256,
        }
        if manifest_envelope != expected_manifest_envelope:
            raise ValueError("stopped recovery manifest is crossed with its identity")

        ledger_bytes = _require_regular_file(ledger_path, "stopped recovery ledger").read_bytes()
        if not ledger_bytes.endswith(b"\n"):
            raise ValueError("stopped recovery ledger snapshot is truncated")
        failed_ledger = _read_failed_ledger(
            ledger_path,
            continuation=workspace,
            expected_identity_hash=_non_empty(identity.get("identity_hash"), "identity hash"),
        )
        ledger_rows = [
            _mapping(json.loads(line), "stopped recovery ledger row")
            for line in ledger_bytes.decode("utf-8").splitlines()
            if line
        ]

        spool = _ConcurrentRuntimeBatchSpool(
            workspace,
            run_id=_non_empty(identity.get("run_id"), "stopped recovery run id"),
            identity_hash=_non_empty(identity.get("identity_hash"), "stopped identity hash"),
            terminal_variants=("primary",),
            recover_prepared=False,
            base_time_step=0,
        )
        seen_pairs: set[str] = set()
        committed_terminal_count = 0
        batch_refs: list[dict[str, object]] = []
        for chunk in spool.iter_committed(failed_ledger.kernel_replay):
            if len(chunk.result_rows) != len(chunk.terminal_rows):
                raise ValueError("stopped recovery committed batch lacks terminal closure")
            chunk_pair_ids: list[str] = []
            for row in chunk.terminal_rows:
                pair_id = _non_empty(row.get("pair_id"), "committed terminal pair id")
                if pair_id in seen_pairs:
                    raise ValueError("stopped recovery durable terminal pair is duplicated")
                seen_pairs.add(pair_id)
                chunk_pair_ids.append(pair_id)
            committed_terminal_count += len(chunk_pair_ids)
            batch_refs.append(
                {
                    "time_step": chunk.time_step,
                    "state": "committed",
                    "batch_snapshot_hash": chunk.batch_snapshot_hash,
                    "terminal_count": len(chunk_pair_ids),
                    "terminal_pair_ids_sha256": _sequence_sha256(chunk_pair_ids),
                }
            )
        committed_batch_count = len(batch_refs)
        if [row["time_step"] for row in batch_refs] != list(range(committed_batch_count)):
            raise ValueError("stopped recovery committed batches are missing or out of order")

        snapshot_documents = _snapshot_documents(failed_ledger.kernel_replay)
        active_snapshot = snapshot_documents.get(committed_batch_count)
        if active_snapshot is None or set(snapshot_documents) != set(
            range(committed_batch_count + 1)
        ):
            raise ValueError("stopped recovery snapshot inventory is not one committed prefix plus active")
        active_plans = _snapshot_plan_rows(active_snapshot)
        active_pair_ids = [
            _non_empty(row.get("pair_id"), "active pair id")
            for row in active_plans
        ]
        active_durable_ids: list[str] = []
        for pair_id in active_pair_ids:
            if pair_id not in failed_ledger.terminal_payload_by_pair_id:
                break
            if pair_id in seen_pairs:
                raise ValueError("active terminal duplicates one committed terminal")
            seen_pairs.add(pair_id)
            active_durable_ids.append(pair_id)
        active_durable_set = set(active_durable_ids)
        if any(
            pair_id in failed_ledger.terminal_payload_by_pair_id
            for pair_id in active_pair_ids[len(active_durable_ids) :]
        ):
            raise ValueError("stopped recovery active terminals are not one canonical prefix")
        durable_terminal_count = committed_terminal_count + len(active_durable_ids)

        recovery_status_document = _read_json(
            _require_regular_file(recovery_status_path, "stopped recovery status")
        )
        if set(recovery_status_document) != {"schema_version", "result"} or (
            recovery_status_document.get("schema_version") != _PARENT_RECOVERY_STATUS_SCHEMA
        ):
            raise ValueError("stopped recovery status fields or schema are crossed")
        stopped_result = SegmentedRecoveryExecutionResult.model_validate(
            recovery_status_document.get("result")
        )
        unknown_pair_ids = tuple(
            pair_id
            for pair_id in failed_ledger.dispatched_pair_ids
            if pair_id not in set(failed_ledger.durable_pair_ids)
        )
        recovered_pair_ids = tuple(stopped_result.recovered_pair_ids)
        parent_unresolved_ids = tuple(parent_inputs.unresolved_pair_ids)
        fresh_dispatched_count = sum(
            pair_id not in set(parent_unresolved_ids)
            for pair_id in failed_ledger.dispatched_pair_ids
        )
        parent_accounting = _mapping(parent_plan.get("accounting"), "parent accounting")
        expected_logical = _strict_non_negative_int(
            parent_accounting.get("historical_logical_count"), "parent historical logical"
        ) + fresh_dispatched_count
        expected_physical = (
            _strict_non_negative_int(
                parent_accounting.get("historical_physical_attempts"),
                "parent historical physical",
            )
            + _strict_non_negative_int(
                parent_accounting.get("unresolved_uncertainty_physical_charge"),
                "parent uncertainty charge",
            )
            + failed_ledger.wave_physical_attempts
        )
        if (
            stopped_result.status != "reconciliation_required"
            or stopped_result.workspace_root != workspace
            or stopped_result.recovery_identity_hash != identity.get("identity_hash")
            or stopped_result.source_root is not None
            or stopped_result.source_manifest_sha256 is not None
            or stopped_result.logical_count != expected_logical
            or stopped_result.physical_attempt_count != expected_physical
            or stopped_result.imported_durable_terminal_count
            != parent_inputs.imported_durable_terminal_count
            or recovered_pair_ids != parent_unresolved_ids
            or stopped_result.unknown_pair_ids != unknown_pair_ids
            or stopped_result.provider_calls != 0
            or stopped_result.production_deploy_eligible is not False
        ):
            raise ValueError("stopped recovery result is crossed with parent accounting or ledger")
        if durable_terminal_count != stopped_result.logical_count - len(unknown_pair_ids):
            raise ValueError("stopped recovery durable denominator is crossed")
        if durable_terminal_count != (
            stopped_result.imported_durable_terminal_count
            + len(failed_ledger.durable_pair_ids)
        ):
            raise ValueError("stopped recovery imported and explicit terminals do not close")

        next_active_ids = active_pair_ids[
            len(active_durable_ids) : len(active_durable_ids) + len(unknown_pair_ids)
        ]
        if next_active_ids != list(unknown_pair_ids):
            raise ValueError("stopped recovery unresolved pairs are not the next canonical frontier")
        position_by_pair_id = {
            cast(str, row["pair_id"]): cast(int, row["pair_schedule_position"])
            for row in active_plans
        }
        unresolved_rows = _unresolved_rows(
            ledger_rows,
            unknown_pair_ids=unknown_pair_ids,
            position_by_pair_id=position_by_pair_id,
            maximum_attempts_per_dispatch=3,
            active_durable_ids=active_durable_set,
        )
        unknown_positions = tuple(
            cast(int, row["canonical_schedule_position"]) for row in unresolved_rows
        )

        continuation_status = _read_json(
            _require_regular_file(
                continuation_status_path, "stopped continuation status"
            )
        )
        if set(continuation_status) != _PARENT_CONTINUATION_STATUS_FIELDS or (
            continuation_status.get("schema_version")
            != _PARENT_CONTINUATION_STATUS_SCHEMA
            or continuation_status.get("lifecycle") != "reconciliation_required"
            or continuation_status.get("manifest_sha256")
            != parent_documents.manifest_sha256
            or continuation_status.get("unknown_pair_ids") != list(unknown_pair_ids)
            or continuation_status.get("logical_count") != stopped_result.logical_count
            or continuation_status.get("physical_attempt_count")
            != stopped_result.physical_attempt_count
            or continuation_status.get("terminal_rows_relative_path") is not None
            or continuation_status.get("terminal_rows_sha256") is not None
            or continuation_status.get("source_root_relative_path") is not None
            or continuation_status.get("source_manifest_sha256") is not None
            or continuation_status.get("production_deploy_eligible") is not False
        ):
            raise ValueError("stopped continuation status is crossed")

        execution_result_path = _require_regular_file(
            request.execution_result_path, "stopped execution result"
        )
        if _sha256_file(execution_result_path) != request.execution_result_sha256:
            raise ValueError("stopped execution result bytes differ from the explicit hash")
        execution_result = _read_json(execution_result_path)
        if set(execution_result) != _PARENT_RESULT_WRAPPER_FIELDS or execution_result.get(
            "schema_version"
        ) != _PARENT_RESULT_WRAPPER_SCHEMA:
            raise ValueError("stopped execution result fields or schema are crossed")
        _utc_datetime(execution_result.get("recorded_at"), "execution result timestamp")
        implementation_commit = _non_empty(
            execution_result.get("implementation_commit"), "parent implementation commit"
        )
        if _GIT_COMMIT.fullmatch(implementation_commit) is None:
            raise ValueError("parent implementation commit is invalid")
        if (
            execution_result.get("recovery_plan_sha256") != parent_plan_sha256
            or execution_result.get("human_authorization_sha256")
            != parent_authorization_sha256
            or execution_result.get("configured_max_concurrency")
            != FULL_POOL_SEGMENTED_MAX_CONCURRENCY
            or execution_result.get("observed_external_request_invocations")
            != failed_ledger.wave_physical_attempts
            or execution_result.get("subscription_billed_cost_usd") != 0
            or not isinstance(execution_result.get("subscription_nominal_cost_usd"), int | float)
            or cast(float, execution_result.get("subscription_nominal_cost_usd")) < 0
            or execution_result.get("raw_prompt_request_response_persisted") is not False
            or execution_result.get("result") != stopped_result.model_dump(mode="json")
        ):
            raise ValueError("stopped execution result is crossed with persisted recovery facts")

        accounted_wave_count = sum(
            row.get("event_type") == "wave_accounting" for row in ledger_rows
        )
        observed_contract = _StoppedRecoveryContract(
            parent_recovery_plan_sha256=parent_plan_sha256,
            parent_authorization_sha256=parent_authorization_sha256,
            stopped_identity_hash=_non_empty(identity.get("identity_hash"), "identity hash"),
            stopped_identity_file_sha256=_sha256_file(identity_path),
            stopped_manifest_sha256=parent_documents.manifest_sha256,
            stopped_manifest_file_sha256=_sha256_file(manifest_path),
            stopped_ledger_sha256=_sha256_file(ledger_path),
            stopped_workspace_inventory_sha256=_sha256_json(workspace_inventory),
            stopped_continuation_status_sha256=_sha256_file(continuation_status_path),
            stopped_recovery_status_sha256=_sha256_file(recovery_status_path),
            execution_result_sha256=request.execution_result_sha256,
            implementation_commit=implementation_commit,
            historical_logical_count=stopped_result.logical_count,
            historical_physical_attempts=stopped_result.physical_attempt_count,
            imported_durable_terminal_count=stopped_result.imported_durable_terminal_count,
            durable_terminal_count=durable_terminal_count,
            explicit_dispatched_count=len(failed_ledger.dispatched_pair_ids),
            explicit_durable_terminal_count=len(failed_ledger.durable_pair_ids),
            explicit_physical_attempts=failed_ledger.wave_physical_attempts,
            committed_batch_count=committed_batch_count,
            accounted_wave_count=accounted_wave_count,
            ledger_sequence=len(ledger_rows),
            recovered_pair_ids=recovered_pair_ids,
            unknown_pair_ids=unknown_pair_ids,
            unknown_schedule_positions=unknown_positions,
        )

        uncertainty_charge = len(unresolved_rows) * 3
        physical_accounting_total = stopped_result.physical_attempt_count + uncertainty_charge
        if (
            stopped_result.logical_count > FULL_POOL_SEGMENTED_LOGICAL_CAP
            or physical_accounting_total > FULL_POOL_SEGMENTED_PHYSICAL_CAP
        ):
            raise ValueError("nested recovery accounting exceeds a frozen cap")
        accounting = {
            "logical_cap": FULL_POOL_SEGMENTED_LOGICAL_CAP,
            "historical_logical_count": stopped_result.logical_count,
            "logical_retry_charge": 0,
            "fresh_logical_remaining": (
                FULL_POOL_SEGMENTED_LOGICAL_CAP - stopped_result.logical_count
            ),
            "physical_cap": FULL_POOL_SEGMENTED_PHYSICAL_CAP,
            "historical_physical_attempts": stopped_result.physical_attempt_count,
            "unresolved_uncertainty_physical_charge": uncertainty_charge,
            "future_retry_physical_attempts": 0,
            "future_continuation_physical_attempts": 0,
            "physical_accounting_total": physical_accounting_total,
            "remaining_physical_cap": (
                FULL_POOL_SEGMENTED_PHYSICAL_CAP - physical_accounting_total
            ),
        }
        active_snapshot_ref = _snapshot_ref(
            active_snapshot,
            workspace=workspace,
            workspace_inventory=workspace_inventory,
        )
        active_durable_pair_ids_sha256 = _sequence_sha256(active_durable_ids)
        batch_refs.append(
            {
                "time_step": committed_batch_count,
                "state": "active_incomplete",
                "batch_snapshot_hash": active_snapshot_ref["snapshot_hash"],
                "candidate_pair_count": len(active_pair_ids),
                "durable_terminal_count": len(active_durable_ids),
                "candidate_pair_ids_sha256": _sequence_sha256(active_pair_ids),
                "durable_terminal_pair_ids_sha256": active_durable_pair_ids_sha256,
                "snapshot_ref": active_snapshot_ref,
            }
        )
        durable_pair_ids_sha256 = _sha256_json(
            [
                *[
                    _non_empty(
                        row.get("terminal_pair_ids_sha256"),
                        "committed terminal pair digest",
                    )
                    for row in batch_refs[:-1]
                ],
                active_durable_pair_ids_sha256,
            ]
        )
        recovery_snapshot = {
            "durable_terminal_summary": {
                "count": durable_terminal_count,
                "pair_ids_sha256": durable_pair_ids_sha256,
                "committed_terminal_count": committed_terminal_count,
                "active_terminal_count": len(active_durable_ids),
            },
            "batch_snapshots": batch_refs,
            "active_time_step": committed_batch_count,
            "active_candidate_pair_count": len(active_pair_ids),
            "active_durable_terminal_count": len(active_durable_ids),
            "unresolved_pairs": unresolved_rows,
        }

        parent_failed_lineage = _mapping(
            parent_plan.get("failed_run_lineage"), "parent failed run lineage"
        )
        parent_artifact_refs = _mapping(
            parent_failed_lineage.get("artifact_refs"), "parent failed artifact refs"
        )
        qualification_ref = _mapping(
            parent_artifact_refs.get("qualification"), "parent qualification ref"
        )
        parent_plan_identity = _mapping(
            parent_plan.get("recovery_identity"), "parent recovery identity"
        )
        parent_snapshot = _mapping(
            parent_plan.get("recovery_snapshot"), "parent recovery snapshot"
        )
        first_unresolved = _mapping_sequence(
            parent_snapshot.get("unresolved_pairs"), "parent unresolved pairs"
        )
        parent_recovery_lineage = {
            "schema_version": "full-pool-segmented-parent-recovery-lineage-v2",
            "parent_recovery_plan": _file_ref(parent_plan_path),
            "parent_human_authorization": _file_ref(parent_authorization_path),
            "parent_qualification": qualification_ref,
            "parent_recovery_identity_hash": parent_documents.identity["identity_hash"],
            "parent_failed_continuation_identity_hash": parent_plan_identity[
                "failed_continuation_identity_hash"
            ],
            "parent_unresolved_pair_ids": [
                _non_empty(row.get("pair_id"), "parent unresolved pair id")
                for row in first_unresolved
            ],
            "stopped_recovery_identity": _file_ref(identity_path),
            "stopped_recovery_manifest": _file_ref(manifest_path),
            "stopped_recovery_ledger": _file_ref(ledger_path),
            "stopped_continuation_status": _file_ref(continuation_status_path),
            "stopped_recovery_status": _file_ref(recovery_status_path),
            "stopped_execution_result": _file_ref(execution_result_path),
        }
        module_path = Path(__file__).resolve()
        implementation = {
            "repository_commit": _repository_commit(),
            "nested_recovery_module_sha256": _sha256_file(module_path),
            "parent_recovery_implementation_commit": implementation_commit,
        }
        identity_body = {
            "schema_version": _NESTED_RECOVERY_IDENTITY_SCHEMA,
            "recovery_id": request.recovery_id,
            "recovery_root": str(request.recovery_root),
            "proposed_authorization_path": str(request.proposed_authorization_path),
            "proposed_recovery_workspace": str(request.proposed_recovery_workspace),
            "parent_recovery_identity_hash": parent_documents.identity["identity_hash"],
            "stopped_ledger_sha256": _sha256_file(ledger_path),
            "stopped_workspace_inventory_sha256": _sha256_json(workspace_inventory),
            "accounting_sha256": _sha256_json(accounting),
            "recovery_snapshot_sha256": _sha256_json(recovery_snapshot),
            "implementation": implementation,
        }
        recovery_identity = {**identity_body, "identity_hash": _sha256_json(identity_body)}
        execution_contract = _mapping(
            parent_plan.get("execution_contract"), "parent execution contract"
        )
        provider_transport = "openai-codex"
        wire_api = "responses"
        reasoning_effort = "low"
        max_output_tokens = 256
        timeout_seconds = 30.0
        max_retries = 2
        omitted_parameters = ["temperature", "top_p", "seed"]
        handoff = {
            "schema_version": _NESTED_RECOVERY_HANDOFF_SCHEMA,
            "authorization_required": True,
            "retry_authorized": False,
            "scope": "retry-seven-unresolved-and-complete-source-v3",
            "recovery_plan_artifact_sha256_binding_required": True,
            "recovery_plan_identity_hash": recovery_identity["identity_hash"],
            "parent_recovery_identity_hash": parent_documents.identity["identity_hash"],
            "unresolved_pair_ids": list(unknown_pair_ids),
            "unresolved_terminal_row_ids": [
                f"{pair_id}:primary" for pair_id in unknown_pair_ids
            ],
            "configured_max_concurrency": FULL_POOL_SEGMENTED_MAX_CONCURRENCY,
            "prompt_version": execution_contract["prompt_version"],
            "provider_contract_sha256": execution_contract[
                "provider_contract_sha256"
            ],
            "prompt_contract_sha256": execution_contract["prompt_contract_sha256"],
            "requested_model": FULL_POOL_FORMAL_REQUESTED_MODEL,
            "required_observed_model": FULL_POOL_FORMAL_REQUIRED_OBSERVED_MODEL,
            "provider_transport": provider_transport,
            "wire_api": wire_api,
            "reasoning_effort": reasoning_effort,
            "max_output_tokens": max_output_tokens,
            "timeout_seconds": timeout_seconds,
            "max_retries": max_retries,
            "omitted_parameters": omitted_parameters,
            "fresh_no_cache": True,
            "maximum_attempts_per_dispatch": 3,
            "logical_retry_charge": 0,
            "uncertainty_physical_charge": uncertainty_charge,
            "historical_logical_count": stopped_result.logical_count,
            "historical_physical_attempts": stopped_result.physical_attempt_count,
            "logical_cap": FULL_POOL_SEGMENTED_LOGICAL_CAP,
            "physical_cap": FULL_POOL_SEGMENTED_PHYSICAL_CAP,
            "subscription_billed_cost_usd": 0,
            "proposed_authorization_path": str(request.proposed_authorization_path),
            "proposed_recovery_workspace": str(request.proposed_recovery_workspace),
            "authorization_expiry_required": True,
            "implementation_commit": implementation["repository_commit"],
            "implementation_module_sha256": implementation[
                "nested_recovery_module_sha256"
            ],
            "provider_calls": 0,
            "production_deploy_eligible": False,
        }
        payload: dict[str, object] = {
            "schema_version": _NESTED_RECOVERY_PLAN_SCHEMA,
            "lifecycle": "recovery_prepared",
            "recovery_identity": recovery_identity,
            "parent_recovery_lineage": parent_recovery_lineage,
            "execution_contract": {
                "configured_max_concurrency": FULL_POOL_SEGMENTED_MAX_CONCURRENCY,
                "prompt_version": execution_contract["prompt_version"],
                "provider_contract_sha256": execution_contract[
                    "provider_contract_sha256"
                ],
                "prompt_contract_sha256": execution_contract[
                    "prompt_contract_sha256"
                ],
                "requested_model": FULL_POOL_FORMAL_REQUESTED_MODEL,
                "required_observed_model": FULL_POOL_FORMAL_REQUIRED_OBSERVED_MODEL,
                "provider_transport": provider_transport,
                "wire_api": wire_api,
                "reasoning_effort": reasoning_effort,
                "max_output_tokens": max_output_tokens,
                "timeout_seconds": timeout_seconds,
                "max_retries": max_retries,
                "omitted_parameters": omitted_parameters,
                "fresh_no_cache": True,
                "maximum_attempts_per_dispatch": 3,
            },
            "accounting": accounting,
            "recovery_snapshot": recovery_snapshot,
            "source_inventories": {"stopped_recovery_workspace": workspace_inventory},
            "human_authorization_handoff": handoff,
            "status_output": {
                "lifecycle": "recovery_prepared",
                "configured_max_concurrency": FULL_POOL_SEGMENTED_MAX_CONCURRENCY,
                "worker_state": "recorded_stopped",
                "durable_terminal_count": durable_terminal_count,
                "committed_batch_count": committed_batch_count,
                "unresolved_count": len(unknown_pair_ids),
            },
            "provider_calls": 0,
            "production_deploy_eligible": False,
        }
        protected = {
            "stopped_workspace": workspace,
            "stopped_inventory": workspace_inventory,
            "parent_plan_ref": _file_ref(parent_plan_path),
            "parent_authorization_ref": _file_ref(parent_authorization_path),
            "execution_result_ref": _file_ref(execution_result_path),
            "parent_artifact_refs": parent_artifact_refs,
            "parent_frozen_path": parent_inputs.cutover_request.frozen_prefix_workspace,
            "parent_failed_path": parent_inputs.cutover_request.continuation_workspace,
            "parent_source_inventories": _mapping(
                parent_plan.get("source_inventories"), "parent source inventories"
            ),
        }
        return _PreparedNestedRecovery(
            payload=payload,
            observed_contract=observed_contract,
            protected=protected,
        )

    def _assert_protected_unchanged(self, protected: Mapping[str, object]) -> None:
        workspace = cast(Path, protected["stopped_workspace"])
        if self.filesystem.inventory(workspace) != protected["stopped_inventory"]:
            raise ValueError("stopped recovery workspace changed during nested planning")
        for label in (
            "parent_plan_ref",
            "parent_authorization_ref",
            "execution_result_ref",
        ):
            ref = _mapping(protected[label], f"protected {label}")
            path = Path(_non_empty(ref.get("path"), f"protected {label} path"))
            if _file_ref(path) != ref:
                raise ValueError(f"protected {label} changed during nested planning")
        parent_refs = _mapping(protected["parent_artifact_refs"], "parent artifact refs")
        for label, raw in parent_refs.items():
            ref = _mapping(raw, f"parent {label} ref")
            path = Path(_non_empty(ref.get("path"), f"parent {label} path"))
            if _file_ref(path) != ref:
                raise ValueError(f"parent {label} artifact changed during nested planning")
        parent_inventories = _mapping(
            protected["parent_source_inventories"], "parent source inventories"
        )
        if self.filesystem.inventory(cast(Path, protected["parent_frozen_path"])) != _mapping(
            parent_inventories.get("frozen_prefix"), "parent frozen inventory"
        ):
            raise ValueError("parent frozen prefix changed during nested planning")
        if self.filesystem.inventory(cast(Path, protected["parent_failed_path"])) != _mapping(
            parent_inventories.get("failed_continuation"), "parent failed inventory"
        ):
            raise ValueError("parent failed continuation changed during nested planning")


def _validate_nested_recovery_payload(
    payload: Mapping[str, object],
    *,
    artifact_path: Path,
) -> None:
    expected_fields = {
        "schema_version",
        "lifecycle",
        "recovery_identity",
        "parent_recovery_lineage",
        "execution_contract",
        "accounting",
        "recovery_snapshot",
        "source_inventories",
        "human_authorization_handoff",
        "status_output",
        "provider_calls",
        "production_deploy_eligible",
    }
    if (
        set(payload) != expected_fields
        or payload.get("schema_version") != _NESTED_RECOVERY_PLAN_SCHEMA
        or payload.get("lifecycle") != "recovery_prepared"
        or payload.get("provider_calls") != 0
        or payload.get("production_deploy_eligible") is not False
    ):
        raise ValueError("nested recovery plan payload fields or lifecycle are not exact")
    identity = _mapping(payload.get("recovery_identity"), "nested recovery identity")
    identity_fields = {
        "schema_version",
        "recovery_id",
        "recovery_root",
        "proposed_authorization_path",
        "proposed_recovery_workspace",
        "parent_recovery_identity_hash",
        "stopped_ledger_sha256",
        "stopped_workspace_inventory_sha256",
        "accounting_sha256",
        "recovery_snapshot_sha256",
        "implementation",
        "identity_hash",
    }
    if set(identity) != identity_fields or identity.get(
        "schema_version"
    ) != _NESTED_RECOVERY_IDENTITY_SCHEMA:
        raise ValueError("nested recovery identity fields or schema are not exact")
    identity_body = {key: value for key, value in identity.items() if key != "identity_hash"}
    if identity.get("identity_hash") != _sha256_json(identity_body):
        raise ValueError("nested recovery identity hash mismatch")
    if Path(_non_empty(identity.get("recovery_root"), "nested recovery root")) != artifact_path.parent:
        raise ValueError("nested recovery artifact path is crossed with its identity")

    parent_lineage = _mapping(
        payload.get("parent_recovery_lineage"), "parent recovery lineage"
    )
    parent_lineage_fields = {
        "schema_version",
        "parent_recovery_plan",
        "parent_human_authorization",
        "parent_qualification",
        "parent_recovery_identity_hash",
        "parent_failed_continuation_identity_hash",
        "parent_unresolved_pair_ids",
        "stopped_recovery_identity",
        "stopped_recovery_manifest",
        "stopped_recovery_ledger",
        "stopped_continuation_status",
        "stopped_recovery_status",
        "stopped_execution_result",
    }
    if (
        set(parent_lineage) != parent_lineage_fields
        or parent_lineage.get("schema_version")
        != "full-pool-segmented-parent-recovery-lineage-v2"
        or parent_lineage.get("parent_recovery_identity_hash")
        != identity.get("parent_recovery_identity_hash")
        or not isinstance(parent_lineage.get("parent_unresolved_pair_ids"), list)
        or len(cast(list[object], parent_lineage.get("parent_unresolved_pair_ids"))) != 2
    ):
        raise ValueError("parent recovery lineage fields or identity are crossed")
    for field in (
        "parent_recovery_plan",
        "parent_human_authorization",
        "parent_qualification",
        "stopped_recovery_identity",
        "stopped_recovery_manifest",
        "stopped_recovery_ledger",
        "stopped_continuation_status",
        "stopped_recovery_status",
        "stopped_execution_result",
    ):
        _validate_persisted_ref(
            _mapping(parent_lineage.get(field), f"parent recovery lineage {field}"),
            f"parent recovery lineage {field}",
        )
    stopped_ledger_ref = _mapping(
        parent_lineage.get("stopped_recovery_ledger"), "stopped recovery ledger ref"
    )
    if stopped_ledger_ref.get("sha256") != identity.get("stopped_ledger_sha256"):
        raise ValueError("parent recovery lineage stopped ledger is crossed")

    implementation = _mapping(identity.get("implementation"), "nested recovery implementation")
    if set(implementation) != {
        "repository_commit",
        "nested_recovery_module_sha256",
        "parent_recovery_implementation_commit",
    } or any(
        _GIT_COMMIT.fullmatch(
            _non_empty(implementation.get(field), f"nested recovery {field}")
        )
        is None
        for field in ("repository_commit", "parent_recovery_implementation_commit")
    ):
        raise ValueError("nested recovery implementation identity is crossed")
    module_sha256 = _non_empty(
        implementation.get("nested_recovery_module_sha256"),
        "nested recovery module SHA-256",
    )
    if _SHA256.fullmatch(module_sha256) is None:
        raise ValueError("nested recovery implementation module hash is invalid")

    execution = _mapping(payload.get("execution_contract"), "nested execution contract")
    execution_fields = {
        "configured_max_concurrency",
        "prompt_version",
        "provider_contract_sha256",
        "prompt_contract_sha256",
        "requested_model",
        "required_observed_model",
        "provider_transport",
        "wire_api",
        "reasoning_effort",
        "max_output_tokens",
        "timeout_seconds",
        "max_retries",
        "omitted_parameters",
        "fresh_no_cache",
        "maximum_attempts_per_dispatch",
    }
    if (
        set(execution) != execution_fields
        or execution.get("configured_max_concurrency")
        != FULL_POOL_SEGMENTED_MAX_CONCURRENCY
        or execution.get("requested_model") != FULL_POOL_FORMAL_REQUESTED_MODEL
        or execution.get("required_observed_model")
        != FULL_POOL_FORMAL_REQUIRED_OBSERVED_MODEL
        or execution.get("provider_transport") != "openai-codex"
        or execution.get("wire_api") != "responses"
        or execution.get("reasoning_effort") != "low"
        or execution.get("max_output_tokens") != 256
        or execution.get("timeout_seconds") != 30.0
        or execution.get("max_retries") != 2
        or execution.get("omitted_parameters") != ["temperature", "top_p", "seed"]
        or execution.get("fresh_no_cache") is not True
        or execution.get("maximum_attempts_per_dispatch") != 3
        or _SHA256.fullmatch(
            _non_empty(execution.get("provider_contract_sha256"), "provider contract hash")
        )
        is None
        or _SHA256.fullmatch(
            _non_empty(execution.get("prompt_contract_sha256"), "prompt contract hash")
        )
        is None
    ):
        raise ValueError("nested execution contract is crossed")

    source_inventories = _mapping(
        payload.get("source_inventories"), "nested recovery source inventory"
    )
    if set(source_inventories) != {"stopped_recovery_workspace"}:
        raise ValueError("nested recovery source inventory fields are not exact")
    stopped_inventory = _mapping(
        source_inventories.get("stopped_recovery_workspace"),
        "stopped recovery source inventory",
    )
    if not stopped_inventory:
        raise ValueError("stopped recovery source inventory is empty")
    for relative, raw in stopped_inventory.items():
        ref = _mapping(raw, f"stopped recovery source inventory {relative}")
        if set(ref) != {"relative_path", "bytes", "sha256"} or ref.get(
            "relative_path"
        ) != relative:
            raise ValueError("stopped recovery source inventory entry is crossed")
        relative_path = Path(str(relative))
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError("stopped recovery source inventory path is unsafe")
        _strict_non_negative_int(ref.get("bytes"), "stopped inventory bytes")
        digest = _non_empty(ref.get("sha256"), "stopped inventory SHA-256")
        if _SHA256.fullmatch(digest) is None:
            raise ValueError("stopped recovery source inventory hash is invalid")
    if identity.get("stopped_workspace_inventory_sha256") != _sha256_json(
        stopped_inventory
    ):
        raise ValueError("stopped recovery source inventory hash is crossed")

    accounting = _mapping(payload.get("accounting"), "nested recovery accounting")
    expected_accounting_fields = {
        "logical_cap",
        "historical_logical_count",
        "logical_retry_charge",
        "fresh_logical_remaining",
        "physical_cap",
        "historical_physical_attempts",
        "unresolved_uncertainty_physical_charge",
        "future_retry_physical_attempts",
        "future_continuation_physical_attempts",
        "physical_accounting_total",
        "remaining_physical_cap",
    }
    if set(accounting) != expected_accounting_fields:
        raise ValueError("nested recovery accounting fields are not exact")
    historical_logical = _strict_non_negative_int(
        accounting.get("historical_logical_count"), "historical logical count"
    )
    historical_physical = _strict_non_negative_int(
        accounting.get("historical_physical_attempts"), "historical physical attempts"
    )
    uncertainty = _strict_non_negative_int(
        accounting.get("unresolved_uncertainty_physical_charge"), "uncertainty charge"
    )
    if (
        accounting.get("logical_cap") != FULL_POOL_SEGMENTED_LOGICAL_CAP
        or accounting.get("logical_retry_charge") != 0
        or accounting.get("fresh_logical_remaining")
        != FULL_POOL_SEGMENTED_LOGICAL_CAP - historical_logical
        or accounting.get("physical_cap") != FULL_POOL_SEGMENTED_PHYSICAL_CAP
        or uncertainty != 21
        or accounting.get("future_retry_physical_attempts") != 0
        or accounting.get("future_continuation_physical_attempts") != 0
        or accounting.get("physical_accounting_total")
        != historical_physical + uncertainty
        or accounting.get("remaining_physical_cap")
        != FULL_POOL_SEGMENTED_PHYSICAL_CAP - historical_physical - uncertainty
        or identity.get("accounting_sha256") != _sha256_json(accounting)
    ):
        raise ValueError("nested recovery accounting is crossed")

    snapshot = _mapping(payload.get("recovery_snapshot"), "nested recovery snapshot")
    if set(snapshot) != {
        "durable_terminal_summary",
        "batch_snapshots",
        "active_time_step",
        "active_candidate_pair_count",
        "active_durable_terminal_count",
        "unresolved_pairs",
    } or identity.get("recovery_snapshot_sha256") != _sha256_json(snapshot):
        raise ValueError("nested recovery snapshot fields or hash are crossed")
    durable_summary = _mapping(
        snapshot.get("durable_terminal_summary"), "durable terminal summary"
    )
    if set(durable_summary) != {
        "count",
        "pair_ids_sha256",
        "committed_terminal_count",
        "active_terminal_count",
    }:
        raise ValueError("durable terminal summary fields are not exact")
    durable_count = _strict_non_negative_int(
        durable_summary.get("count"), "durable terminal summary count"
    )
    committed_terminal_count = _strict_non_negative_int(
        durable_summary.get("committed_terminal_count"),
        "durable committed terminal count",
    )
    active_terminal_count = _strict_non_negative_int(
        durable_summary.get("active_terminal_count"), "durable active terminal count"
    )
    batches = _mapping_sequence(snapshot.get("batch_snapshots"), "nested batch snapshots")
    active_time_step = _strict_non_negative_int(
        snapshot.get("active_time_step"), "nested active time_step"
    )
    if len(batches) != active_time_step + 1 or [
        row.get("time_step") for row in batches
    ] != list(range(active_time_step + 1)):
        raise ValueError("nested batch snapshot time steps are crossed")
    committed_digests: list[str] = []
    observed_committed_terminals = 0
    for row in batches[:-1]:
        if set(row) != {
            "time_step",
            "state",
            "batch_snapshot_hash",
            "terminal_count",
            "terminal_pair_ids_sha256",
        } or row.get("state") != "committed":
            raise ValueError("nested committed batch snapshot fields are crossed")
        observed_committed_terminals += _strict_non_negative_int(
            row.get("terminal_count"), "nested committed terminal count"
        )
        for field in ("batch_snapshot_hash", "terminal_pair_ids_sha256"):
            digest = _non_empty(row.get(field), f"nested committed {field}")
            if _SHA256.fullmatch(digest) is None:
                raise ValueError("nested committed batch hash is invalid")
        committed_digests.append(cast(str, row["terminal_pair_ids_sha256"]))
    active = batches[-1]
    if set(active) != {
        "time_step",
        "state",
        "batch_snapshot_hash",
        "candidate_pair_count",
        "durable_terminal_count",
        "candidate_pair_ids_sha256",
        "durable_terminal_pair_ids_sha256",
        "snapshot_ref",
    } or active.get("state") != "active_incomplete":
        raise ValueError("nested active batch snapshot fields are crossed")
    active_candidate_count = _strict_non_negative_int(
        active.get("candidate_pair_count"), "nested active candidate count"
    )
    observed_active_terminals = _strict_non_negative_int(
        active.get("durable_terminal_count"), "nested active terminal count"
    )
    for field in (
        "batch_snapshot_hash",
        "candidate_pair_ids_sha256",
        "durable_terminal_pair_ids_sha256",
    ):
        digest = _non_empty(active.get(field), f"nested active {field}")
        if _SHA256.fullmatch(digest) is None:
            raise ValueError("nested active batch hash is invalid")
    snapshot_ref = _mapping(active.get("snapshot_ref"), "nested active snapshot ref")
    if set(snapshot_ref) != {"time_step", "snapshot_hash", "relative_path", "sha256", "bytes"}:
        raise ValueError("nested active snapshot ref fields are not exact")
    relative_snapshot = Path(
        _non_empty(snapshot_ref.get("relative_path"), "nested active snapshot path")
    )
    if relative_snapshot.is_absolute() or ".." in relative_snapshot.parts:
        raise ValueError("nested active snapshot path is unsafe")
    if (
        snapshot_ref.get("time_step") != active_time_step
        or snapshot_ref.get("snapshot_hash") != active.get("batch_snapshot_hash")
        or _SHA256.fullmatch(
            _non_empty(snapshot_ref.get("sha256"), "nested active snapshot SHA-256")
        )
        is None
    ):
        raise ValueError("nested active snapshot ref is crossed")
    _strict_non_negative_int(snapshot_ref.get("bytes"), "nested active snapshot bytes")
    expected_durable_digest = _sha256_json(
        [*committed_digests, active["durable_terminal_pair_ids_sha256"]]
    )
    summary_digest = _non_empty(
        durable_summary.get("pair_ids_sha256"), "durable terminal summary hash"
    )
    if (
        _SHA256.fullmatch(summary_digest) is None
        or summary_digest != expected_durable_digest
        or committed_terminal_count != observed_committed_terminals
        or active_terminal_count != observed_active_terminals
        or durable_count != committed_terminal_count + active_terminal_count
        or snapshot.get("active_candidate_pair_count") != active_candidate_count
        or snapshot.get("active_durable_terminal_count") != active_terminal_count
    ):
        raise ValueError("durable terminal summary is crossed with batch snapshots")

    unresolved = _mapping_sequence(snapshot.get("unresolved_pairs"), "nested unresolved pairs")
    if len(unresolved) != 7:
        raise ValueError("nested recovery plan requires exactly seven unresolved pairs")
    expected_classes = ["missing_terminal_evidence", *(["blocked_by_prior_canonical_gap"] * 6)]
    positions: list[int] = []
    unresolved_ids: list[str] = []
    for index, row in enumerate(unresolved):
        if set(row) != {
            "pair_id",
            "terminal_row_id",
            "canonical_schedule_position",
            "classification",
            "historical_physical_attempts",
            "terminal_evidence_request_invocations",
            "uncertainty_physical_charge",
            "logical_retry_charge",
        }:
            raise ValueError("nested unresolved pair fields are not exact")
        unresolved_ids.append(_non_empty(row.get("pair_id"), "nested unresolved pair id"))
        position = _strict_non_negative_int(
            row.get("canonical_schedule_position"), "nested unresolved schedule position"
        )
        positions.append(position)
        if (
            row.get("terminal_row_id") != f"{unresolved_ids[-1]}:primary"
            or row.get("classification") != expected_classes[index]
            or row.get("uncertainty_physical_charge") != 3
            or row.get("logical_retry_charge") != 0
        ):
            raise ValueError("nested unresolved pair contract is crossed")
    if positions != list(range(positions[0], positions[0] + 7)):
        raise ValueError("nested unresolved pairs are not one contiguous canonical frontier")

    handoff = _mapping(
        payload.get("human_authorization_handoff"), "nested authorization handoff"
    )
    handoff_fields = {
        "schema_version",
        "authorization_required",
        "retry_authorized",
        "scope",
        "recovery_plan_artifact_sha256_binding_required",
        "recovery_plan_identity_hash",
        "parent_recovery_identity_hash",
        "unresolved_pair_ids",
        "unresolved_terminal_row_ids",
        "configured_max_concurrency",
        "prompt_version",
        "provider_contract_sha256",
        "prompt_contract_sha256",
        "requested_model",
        "required_observed_model",
        "provider_transport",
        "wire_api",
        "reasoning_effort",
        "max_output_tokens",
        "timeout_seconds",
        "max_retries",
        "omitted_parameters",
        "fresh_no_cache",
        "maximum_attempts_per_dispatch",
        "logical_retry_charge",
        "uncertainty_physical_charge",
        "historical_logical_count",
        "historical_physical_attempts",
        "logical_cap",
        "physical_cap",
        "subscription_billed_cost_usd",
        "proposed_authorization_path",
        "proposed_recovery_workspace",
        "authorization_expiry_required",
        "implementation_commit",
        "implementation_module_sha256",
        "provider_calls",
        "production_deploy_eligible",
    }
    if (
        set(handoff) != handoff_fields
        or handoff.get("schema_version") != _NESTED_RECOVERY_HANDOFF_SCHEMA
        or handoff.get("authorization_required") is not True
        or handoff.get("retry_authorized") is not False
        or handoff.get("scope") != "retry-seven-unresolved-and-complete-source-v3"
        or handoff.get("recovery_plan_artifact_sha256_binding_required") is not True
        or handoff.get("recovery_plan_identity_hash") != identity.get("identity_hash")
        or handoff.get("unresolved_pair_ids") != unresolved_ids
        or handoff.get("unresolved_terminal_row_ids")
        != [f"{pair_id}:primary" for pair_id in unresolved_ids]
        or handoff.get("configured_max_concurrency")
        != FULL_POOL_SEGMENTED_MAX_CONCURRENCY
        or handoff.get("prompt_version") != execution.get("prompt_version")
        or handoff.get("provider_contract_sha256")
        != execution.get("provider_contract_sha256")
        or handoff.get("prompt_contract_sha256")
        != execution.get("prompt_contract_sha256")
        or handoff.get("requested_model") != execution.get("requested_model")
        or handoff.get("required_observed_model")
        != execution.get("required_observed_model")
        or handoff.get("provider_transport") != execution.get("provider_transport")
        or handoff.get("wire_api") != execution.get("wire_api")
        or handoff.get("reasoning_effort") != execution.get("reasoning_effort")
        or handoff.get("max_output_tokens") != execution.get("max_output_tokens")
        or handoff.get("timeout_seconds") != execution.get("timeout_seconds")
        or handoff.get("max_retries") != execution.get("max_retries")
        or handoff.get("omitted_parameters") != execution.get("omitted_parameters")
        or handoff.get("fresh_no_cache") is not True
        or handoff.get("maximum_attempts_per_dispatch")
        != execution.get("maximum_attempts_per_dispatch")
        or handoff.get("implementation_commit")
        != implementation.get("repository_commit")
        or handoff.get("implementation_module_sha256")
        != implementation.get("nested_recovery_module_sha256")
        or handoff.get("logical_retry_charge") != 0
        or handoff.get("uncertainty_physical_charge") != 21
        or handoff.get("historical_logical_count") != historical_logical
        or handoff.get("historical_physical_attempts") != historical_physical
        or handoff.get("logical_cap") != FULL_POOL_SEGMENTED_LOGICAL_CAP
        or handoff.get("physical_cap") != FULL_POOL_SEGMENTED_PHYSICAL_CAP
        or handoff.get("subscription_billed_cost_usd") != 0
        or handoff.get("authorization_expiry_required") is not True
        or handoff.get("provider_calls") != 0
        or handoff.get("production_deploy_eligible") is not False
    ):
        raise ValueError("nested authorization handoff is crossed")

    status = _mapping(payload.get("status_output"), "nested recovery status output")
    if set(status) != {
        "lifecycle",
        "configured_max_concurrency",
        "worker_state",
        "durable_terminal_count",
        "committed_batch_count",
        "unresolved_count",
    } or (
        status.get("lifecycle") != "recovery_prepared"
        or status.get("configured_max_concurrency")
        != FULL_POOL_SEGMENTED_MAX_CONCURRENCY
        or status.get("worker_state") != "recorded_stopped"
        or status.get("durable_terminal_count") != durable_summary.get("count")
        or status.get("committed_batch_count") != snapshot.get("active_time_step")
        or status.get("unresolved_count") != 7
    ):
        raise ValueError("nested recovery status output is crossed")


def _validate_persisted_ref(ref: Mapping[str, object], context: str) -> None:
    if set(ref) != {"path", "bytes", "sha256"}:
        raise ValueError(f"{context} fields are not exact")
    path = _non_empty(ref.get("path"), f"{context} path")
    if not Path(path).is_absolute():
        raise ValueError(f"{context} path must be absolute")
    _strict_non_negative_int(ref.get("bytes"), f"{context} bytes")
    digest = _non_empty(ref.get("sha256"), f"{context} SHA-256")
    if _SHA256.fullmatch(digest) is None:
        raise ValueError(f"{context} SHA-256 is invalid")


def _snapshot_plan_rows(document: Mapping[str, object]) -> list[dict[str, object]]:
    payload = _mapping(document.get("payload"), "active snapshot payload")
    plans = [
        plan
        for message in _mapping_sequence(payload.get("messages"), "active snapshot messages")
        for plan in _mapping_sequence(
            message.get("selected_pair_plans"), "active selected pair plans"
        )
    ]
    plans.sort(
        key=lambda row: _strict_non_negative_int(
            row.get("pair_schedule_position"), "active pair schedule position"
        )
    )
    positions = [
        _strict_non_negative_int(row.get("pair_schedule_position"), "active schedule position")
        for row in plans
    ]
    if positions and positions != list(range(positions[0], positions[0] + len(positions))):
        raise ValueError("active pair schedule positions are not contiguous")
    return [
        {
            "pair_id": _non_empty(row.get("pair_id"), "active pair id"),
            "pair_schedule_position": position,
        }
        for row, position in zip(plans, positions, strict=True)
    ]


def _unresolved_rows(
    ledger_rows: Sequence[Mapping[str, object]],
    *,
    unknown_pair_ids: Sequence[str],
    position_by_pair_id: Mapping[str, int],
    maximum_attempts_per_dispatch: int,
    active_durable_ids: set[str],
) -> list[dict[str, object]]:
    if len(unknown_pair_ids) != 7:
        raise ValueError("second recovery requires exactly seven unresolved pair IDs")
    matching_waves: list[dict[str, object]] = []
    unknown_set = set(unknown_pair_ids)
    for record in ledger_rows:
        if record.get("event_type") != "wave_accounting":
            continue
        payload = _mapping(record.get("payload"), "wave accounting payload")
        pair_ids = _string_list(payload.get("pair_ids"), "wave pair IDs")
        if unknown_set.intersection(pair_ids):
            matching_waves.append(payload)
    if len(matching_waves) != 1:
        raise ValueError("unresolved pairs must belong to one exact accounted wave")
    wave = matching_waves[0]
    pair_ids = _string_list(wave.get("pair_ids"), "unresolved wave pair IDs")
    first_index = pair_ids.index(unknown_pair_ids[0])
    if pair_ids[first_index:] != list(unknown_pair_ids):
        raise ValueError("unresolved pairs are not one canonical wave suffix")
    if any(pair_id not in active_durable_ids for pair_id in pair_ids[:first_index]):
        raise ValueError("terminal wave prefix is not durable")
    lanes = _mapping_sequence(wave.get("lanes"), "unresolved wave lanes")
    lane_by_pair_id = {
        _non_empty(row.get("pair_id"), "wave lane pair id"): row for row in lanes
    }
    if set(lane_by_pair_id) != set(pair_ids):
        raise ValueError("wave lane accounting is crossed with pair IDs")
    rows: list[dict[str, object]] = []
    for index, pair_id in enumerate(unknown_pair_ids):
        lane = lane_by_pair_id[pair_id]
        terminal_evidence = _strict_non_negative_int(
            lane.get("terminal_evidence_request_invocations"),
            "terminal evidence request invocations",
        )
        actual_physical = _strict_non_negative_int(
            lane.get("actual_physical_attempts"), "unresolved actual physical attempts"
        )
        if actual_physical < 1 or actual_physical > maximum_attempts_per_dispatch:
            raise ValueError("unresolved historical physical attempts exceed the dispatch contract")
        expected_terminal_evidence = 0 if index == 0 else 1
        if terminal_evidence != expected_terminal_evidence:
            raise ValueError("unresolved terminal evidence classification is crossed")
        rows.append(
            {
                "pair_id": pair_id,
                "terminal_row_id": f"{pair_id}:primary",
                "canonical_schedule_position": position_by_pair_id[pair_id],
                "classification": (
                    "missing_terminal_evidence"
                    if index == 0
                    else "blocked_by_prior_canonical_gap"
                ),
                "historical_physical_attempts": actual_physical,
                "terminal_evidence_request_invocations": terminal_evidence,
                "uncertainty_physical_charge": maximum_attempts_per_dispatch,
                "logical_retry_charge": 0,
            }
        )
    positions = [cast(int, row["canonical_schedule_position"]) for row in rows]
    if positions != list(range(positions[0], positions[0] + len(positions))):
        raise ValueError("unresolved schedule positions are not contiguous")
    return rows


def _snapshot_ref(
    document: Mapping[str, object],
    *,
    workspace: Path,
    workspace_inventory: Mapping[str, object],
) -> dict[str, object]:
    identity = _mapping(document.get("snapshot_identity"), "snapshot identity")
    time_step = _strict_non_negative_int(identity.get("time_step"), "snapshot time_step")
    expected_hash = _sha256_json(document)
    matches = [
        _mapping(raw, "workspace inventory ref")
        for relative, raw in workspace_inventory.items()
        if str(relative).startswith("segmented_runtime_snapshots/batch-plan-")
        and _mapping(raw, "workspace inventory ref").get("sha256")
        == _sha256_file(workspace / str(relative))
        and _read_json(workspace / str(relative)) == document
    ]
    if len(matches) != 1:
        raise ValueError("active snapshot file reference is missing or duplicated")
    ref = matches[0]
    return {
        "time_step": time_step,
        "snapshot_hash": expected_hash,
        "relative_path": ref["relative_path"],
        "sha256": ref["sha256"],
        "bytes": ref["bytes"],
    }


def _update_sequence_hash(hasher: object, value: str) -> None:
    digest = cast("hashlib._Hash", hasher)
    digest.update(_canonical_json(value).encode("utf-8"))
    digest.update(b"\n")


def _sequence_sha256(values: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for value in values:
        _update_sequence_hash(digest, value)
    return digest.hexdigest()


def _repository_commit() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(__file__).resolve().parents[2],
        check=True,
        capture_output=True,
        text=True,
    )
    commit = completed.stdout.strip()
    if _GIT_COMMIT.fullmatch(commit) is None:
        raise ValueError("repository commit is not one full Git SHA")
    return commit


def _utc_datetime(value: object, context: str) -> datetime:
    text = _non_empty(value, context)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{context} is not an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{context} must be timezone-aware")
    return parsed


def _file_ref(path_raw: Path) -> dict[str, object]:
    path = _require_regular_file(path_raw, "artifact reference")
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": _sha256_file(path)}


def _exclusive_write_json(path: Path, payload: Mapping[str, object]) -> None:
    data = (_canonical_json(payload) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _require_regular_file(path: Path, context: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{context} must be one existing regular file")
    return path


def _read_json(path: Path) -> dict[str, object]:
    return _mapping(json.loads(path.read_text(encoding="utf-8")), str(path))


def _mapping(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{context} must be an object")
    return dict(value)


def _mapping_sequence(value: object, context: str) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{context} must be a sequence")
    return [_mapping(item, context) for item in value]


def _string_list(value: object, context: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{context} must be a string sequence")
    return [_non_empty(item, context) for item in value]


def _strict_non_negative_int(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TypeError(f"{context} must be a non-negative integer")
    return value


def _non_empty(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{context} must be a non-empty string")
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
