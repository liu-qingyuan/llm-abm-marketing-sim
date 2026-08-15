from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .decision import LLMDecisionAdapter
from .full_pool_formal_experiment import FullPoolFormalRequestContract
from .full_pool_segmented_continuation import (
    FULL_POOL_SEGMENTED_LOGICAL_CAP,
    FULL_POOL_SEGMENTED_MAX_CONCURRENCY,
    FULL_POOL_SEGMENTED_PHYSICAL_CAP,
    SEGMENTED_CONCURRENCY_QUALIFICATION_FILE,
    SEGMENTED_CONCURRENCY_QUALIFICATION_SCHEMA,
    SEGMENTED_OPERATOR_ARTIFACT_ENVELOPE_SCHEMA,
    FullPoolReconciliationAuthorization,
    FullPoolSegmentedContinuation,
    SegmentedContinuationResult,
    SegmentedQualificationArtifactRef,
    SegmentedQualificationWave,
    _freeze_v1_prefix,
    _replay_continuation_ledger,
)
from .prompt_field_summary import CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION
from .providers.openai_compatible import OpenAICompatibleDecisionAdapter
from .providers.pi_subscription import (
    PI_SUBSCRIPTION_ADAPTER_IDENTITY,
    PI_SUBSCRIPTION_MODEL_ALIASES,
    PI_SUBSCRIPTION_PROVIDER,
    PiSubscriptionProviderClient,
)
from .schemas import FailClosedAction, ProviderLLMConfig, ReasoningEffort

SEGMENTED_IMPLEMENTATION_COMMIT = "2884bbdb2adf7ec63ba229833fad424a2040169c"
SEGMENTED_AUTHORIZATION_REFERENCE = (
    "https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/205#issuecomment-5300395226"
)
SEGMENTED_REQUESTED_MODEL = "gpt-5.6-sol"
SEGMENTED_PROMPT_VERSION = CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION
SEGMENTED_LIVE_GATE = "LLM_ABM_RUN_FULL_POOL_SEGMENTED_CONTINUATION"

_PLAN_SCHEMA = "full-pool-segmented-cutover-plan-v1"
_PREFLIGHT_SCHEMA = "full-pool-segmented-cutover-preflight-v1"
_CUTOVER_SCHEMA = "full-pool-segmented-cutover-v1"
_RECONCILIATION_SCHEMA = "full-pool-segmented-operator-reconciliation-v1"
_CONTINUATION_AUTHORIZATION_SCHEMA = "full-pool-segmented-continuation-authorization-v1"
_QUALIFICATION_SCHEMA = SEGMENTED_CONCURRENCY_QUALIFICATION_SCHEMA
_ARTIFACT_ENVELOPE_SCHEMA = SEGMENTED_OPERATOR_ARTIFACT_ENVELOPE_SCHEMA
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CONTINUATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_RUNTIME_JOURNAL = "concurrent_message_execution_journal.jsonl"
_ATTEMPT_LEDGER = "full_pool_attempt_ledger.jsonl"
_RUNTIME_IDENTITY = "concurrent_message_execution_run_identity.json"
_FORMAL_IDENTITY = "full_pool_execution_identity.json"
_FORMAL_STATUS = "full_pool_execution_status.json"
_LOCK_FILE = "concurrent_message_execution.lock"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CutoverPlanRequest(_FrozenModel):
    """All facts required to prepare one non-scanning, manual-stop cutover."""

    prefix_workspace: Path
    frozen_prefix_workspace: Path
    frozen_prefix_staging: Path
    continuation_workspace: Path
    dataset_dir: Path
    pidfile: Path
    expected_pid: int = Field(gt=1)
    expected_command: str = Field(min_length=1, max_length=1000)
    expected_cwd: Path
    expected_v1_output_identity: str = Field(min_length=1, max_length=200)
    expected_v1_operational_root: str = Field(min_length=1, max_length=1000)
    expected_v1_source_root: str = Field(min_length=1, max_length=1000)
    expected_v1_candidate_root: str = Field(min_length=1, max_length=1000)
    expected_v1_recorded_runtime_workspace: str = Field(min_length=1, max_length=1000)
    expected_v1_recorded_output_target: str = Field(min_length=1, max_length=1000)
    expected_v1_dataset_dir: str = Field(min_length=1, max_length=1000)
    expected_v1_run_identity_hash: str
    expected_execution_contract_sha256: str
    implementation_commit: str
    dataset_hashes: dict[str, str]
    continuation_id: str
    authorization_reference: str
    preflight_artifact: Path
    cutover_artifact: Path
    reconciliation_artifact: Path
    continuation_authorization_artifact: Path
    qualification_artifact: Path
    logical_cap: int = FULL_POOL_SEGMENTED_LOGICAL_CAP
    physical_cap: int = FULL_POOL_SEGMENTED_PHYSICAL_CAP
    max_concurrency: int = FULL_POOL_SEGMENTED_MAX_CONCURRENCY
    migration_unknown_physical_charge: int = 3
    stability_interval_seconds: float = Field(default=2.0, gt=0.0, le=60.0)
    stop_wait_timeout_seconds: float = Field(default=120.0, gt=0.0, le=900.0)

    @field_validator(
        "prefix_workspace",
        "frozen_prefix_workspace",
        "frozen_prefix_staging",
        "continuation_workspace",
        "dataset_dir",
        "pidfile",
        "expected_cwd",
        "preflight_artifact",
        "cutover_artifact",
        "reconciliation_artifact",
        "continuation_authorization_artifact",
        "qualification_artifact",
        mode="before",
    )
    @classmethod
    def _absolute_path(cls, value: object) -> Path:
        path = Path(cast(str | Path, value)).expanduser().resolve(strict=False)
        if not path.is_absolute():  # pragma: no cover - resolve always makes this absolute.
            raise ValueError("operator paths must be absolute")
        return path

    @field_validator("expected_v1_run_identity_hash", "expected_execution_contract_sha256")
    @classmethod
    def _hash(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("identity hashes must be lowercase SHA-256 digests")
        return value

    @field_validator("expected_command")
    @classmethod
    def _safe_command(cls, value: str) -> str:
        lowered = value.lower()
        forbidden = (
            "bearer ",
            "api_key=",
            "apikey=",
            "access_token=",
            "refresh_token=",
            "authorization=",
            "password=",
            "secret=",
            "--api-key",
            "--access-token",
            "--refresh-token",
        )
        if "\n" in value or "\r" in value or any(marker in lowered for marker in forbidden):
            raise ValueError("expected process command must be one safe credential-free line")
        return value

    @field_validator("continuation_id")
    @classmethod
    def _continuation_id(cls, value: str) -> str:
        if _CONTINUATION_ID.fullmatch(value) is None:
            raise ValueError("continuation_id contains unsupported characters")
        return value

    @field_validator("dataset_hashes")
    @classmethod
    def _dataset_hashes(cls, value: dict[str, str]) -> dict[str, str]:
        if not value:
            raise ValueError("dataset hashes must be explicit")
        normalized: dict[str, str] = {}
        for relative, digest in value.items():
            token = PurePosixPath(relative)
            if token.is_absolute() or ".." in token.parts or str(token) in {"", "."}:
                raise ValueError("dataset hash paths must be safe relative paths")
            if _SHA256.fullmatch(digest) is None:
                raise ValueError("dataset hashes must be lowercase SHA-256 digests")
            normalized[token.as_posix()] = digest
        return dict(sorted(normalized.items()))

    @model_validator(mode="after")
    def _exact_contract(self) -> CutoverPlanRequest:
        if self.implementation_commit != SEGMENTED_IMPLEMENTATION_COMMIT:
            raise ValueError("implementation commit is not the frozen segmented source implementation")
        if self.authorization_reference != SEGMENTED_AUTHORIZATION_REFERENCE:
            raise ValueError("authorization must reference the exact Issue #205 segmented comment")
        if (
            self.logical_cap != FULL_POOL_SEGMENTED_LOGICAL_CAP
            or self.physical_cap != FULL_POOL_SEGMENTED_PHYSICAL_CAP
            or self.max_concurrency != FULL_POOL_SEGMENTED_MAX_CONCURRENCY
            or self.migration_unknown_physical_charge != 3
        ):
            raise ValueError("segmented caps, lane count, and migration charge are frozen")
        independent_roots = {
            self.prefix_workspace,
            self.frozen_prefix_workspace,
            self.frozen_prefix_staging,
            self.continuation_workspace,
            self.dataset_dir,
        }
        if len(independent_roots) != 5:
            raise ValueError("prefix, frozen, staging, continuation, and dataset roots must be independent")
        for left in independent_roots:
            for right in independent_roots:
                if left != right and (left.is_relative_to(right) or right.is_relative_to(left)):
                    raise ValueError("operator roots must not be nested")
        artifact_paths = {
            self.preflight_artifact,
            self.cutover_artifact,
            self.reconciliation_artifact,
            self.continuation_authorization_artifact,
            self.qualification_artifact,
        }
        if len(artifact_paths) != 5:
            raise ValueError("operator artifact paths must be independent")
        for artifact_path in artifact_paths:
            if any(artifact_path == root or artifact_path.is_relative_to(root) for root in independent_roots):
                raise ValueError("operator artifacts must stay outside data and runtime roots")
        if self.pidfile == self.prefix_workspace or self.pidfile.is_relative_to(self.prefix_workspace):
            raise ValueError("pidfile must stay outside the mutable v1 workspace")
        return self


@dataclass(frozen=True)
class ProcessSnapshot:
    pid: int
    command: str
    cwd: Path


class ProcessController(Protocol):
    """Read-only process seam. It intentionally exposes no signal operation."""

    def snapshot(self, pid: int) -> ProcessSnapshot | None: ...

    def lock_owner_pids(self, path: Path) -> tuple[int, ...]: ...

    def lock_is_released(self, path: Path) -> bool: ...

    def sleep(self, seconds: float) -> None: ...


class SystemProcessController:
    """Read process facts with ps/lsof; never send a signal or target a process group."""

    def snapshot(self, pid: int) -> ProcessSnapshot | None:
        process = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        command = process.stdout.strip()
        if process.returncode != 0 or not command:
            return None
        cwd_process = subprocess.run(
            ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        cwd_lines = [line[1:] for line in cwd_process.stdout.splitlines() if line.startswith("n")]
        if cwd_process.returncode != 0 or len(cwd_lines) != 1:
            raise RuntimeError("cannot establish the exact PID cwd without signals")
        return ProcessSnapshot(pid=pid, command=command, cwd=Path(cwd_lines[0]).resolve(strict=True))

    def lock_owner_pids(self, path: Path) -> tuple[int, ...]:
        process = subprocess.run(
            ["lsof", "-t", "--", str(path)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if process.returncode not in {0, 1}:
            raise RuntimeError("cannot establish workspace lock ownership")
        owners = {int(line) for line in process.stdout.splitlines() if line.strip().isdigit()}
        return tuple(sorted(owners))

    def lock_is_released(self, path: Path) -> bool:
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("workspace lock must remain an existing regular file")
        try:
            import fcntl

            flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
        except BlockingIOError:
            return False
        return True

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class LocalOperatorFilesystem:
    """Filesystem seam owning regular-file inventories, durable writes, and exact copies."""

    def sha256_file(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def inventory(self, root: Path) -> dict[str, dict[str, object]]:
        if root.is_symlink() or not root.is_dir():
            raise ValueError(f"operator inventory root must be a real directory: {root}")
        inventory: dict[str, dict[str, object]] = {}
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root).as_posix()
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                continue
            if not stat.S_ISREG(mode) or path.is_symlink():
                raise ValueError(f"operator refuses symlink or special workspace entry: {relative}")
            inventory[relative] = {
                "relative_path": relative,
                "bytes": path.stat().st_size,
                "sha256": self.sha256_file(path),
            }
        if not inventory:
            raise ValueError("operator workspace inventory is empty")
        return inventory

    def copy_tree_exact(self, source: Path, target: Path) -> None:
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"copy target already exists: {target}")
        target.mkdir(parents=True)
        for path in sorted(source.rglob("*")):
            relative = path.relative_to(source)
            destination = target / relative
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                destination.mkdir()
            elif stat.S_ISREG(mode) and not path.is_symlink():
                destination.parent.mkdir(parents=True, exist_ok=True)
                with path.open("rb") as source_handle, destination.open("xb") as target_handle:
                    shutil.copyfileobj(source_handle, target_handle, length=1024 * 1024)
                    target_handle.flush()
                    os.fsync(target_handle.fileno())
            else:
                raise ValueError(f"operator refuses symlink or special workspace entry: {relative}")
        directories = [path for path in target.rglob("*") if path.is_dir()]
        for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
            self.fsync_directory(directory)
        self.fsync_directory(target)

    def write_json(self, path: Path, payload: Mapping[str, object], *, exclusive: bool = False) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = _json_bytes(payload)
        if exclusive:
            with path.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        else:
            temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
            with temporary.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        self.fsync_directory(path.parent)

    def replace(self, source: Path, target: Path) -> None:
        os.replace(source, target)
        self.fsync_directory(target.parent)

    def fsync_file(self, path: Path) -> None:
        with path.open("rb") as handle:
            os.fsync(handle.fileno())

    def fsync_directory(self, path: Path) -> None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        descriptor = os.open(path, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


class FullPoolSegmentedCutoverOperator:
    """Auditable prepare/freeze/run Module with a mandatory external manual stop."""

    def __init__(
        self,
        *,
        process_controller: ProcessController | None = None,
        filesystem: LocalOperatorFilesystem | None = None,
    ) -> None:
        self.process_controller = process_controller or SystemProcessController()
        self.filesystem = filesystem or LocalOperatorFilesystem()

    def prepare(self, plan_path: str | Path, request: CutoverPlanRequest) -> dict[str, object]:
        target = Path(plan_path).expanduser().resolve(strict=False)
        if target.exists() or target.is_symlink():
            raise FileExistsError("cutover plan is immutable and already exists")
        forbidden_roots = (
            request.prefix_workspace,
            request.frozen_prefix_workspace,
            request.frozen_prefix_staging,
            request.continuation_workspace,
            request.dataset_dir,
        )
        if any(target == root or target.is_relative_to(root) for root in forbidden_roots):
            raise ValueError("cutover plan must stay outside data and runtime roots")
        facts = self._validate_static_facts(request, require_running=True)
        payload: dict[str, object] = {
            "schema_version": _PLAN_SCHEMA,
            "plan_path": str(target),
            **request.model_dump(mode="json"),
            "loaded_repository_commit": self._repository_commit(),
            "implementation_artifacts": self._implementation_artifacts(),
            "validated_v1_facts": facts,
            "automatic_signal_policy": "forbidden-freeze-after-external-stop-v1",
            "provider_calls": 0,
            "production_deploy_eligible": False,
        }
        self._write_artifact(target, payload, exclusive=True)
        return payload

    def dry_run(self, plan_path: str | Path) -> dict[str, object]:
        plan, plan_file_hash = self._read_plan(plan_path)
        self._validate_implementation_artifacts(plan)
        request = CutoverPlanRequest.model_validate(_request_fields(plan))
        facts = self._validate_static_facts(request, require_running=True)
        token = _confirmation_token(request, _sha256_json(plan))
        payload: dict[str, object] = {
            "schema_version": _PREFLIGHT_SCHEMA,
            "plan_sha256": plan_file_hash,
            "plan_payload_sha256": _sha256_json(plan),
            "pid": request.expected_pid,
            "command": request.expected_command,
            "cwd": str(request.expected_cwd),
            "lock_path": str(request.prefix_workspace / _LOCK_FILE),
            "lock_owner_pids": [request.expected_pid],
            "validated_v1_facts": facts,
            "manual_stop_required": True,
            "manual_stop_instruction": (
                f"Externally stop exactly PID {request.expected_pid}; do not signal a process group. "
                "Then invoke cutover with the exact confirmation token."
            ),
            "exact_confirmation_token": token,
            "operator_will_send_signals": False,
            "provider_calls": 0,
            "production_deploy_eligible": False,
        }
        self._write_artifact(request.preflight_artifact, payload)
        return payload

    def cutover(self, plan_path: str | Path, *, confirmation_token: str) -> dict[str, object]:
        plan, plan_file_hash = self._read_plan(plan_path)
        self._validate_implementation_artifacts(plan)
        request = CutoverPlanRequest.model_validate(_request_fields(plan))
        preflight, preflight_file_hash = self._read_artifact(request.preflight_artifact, _PREFLIGHT_SCHEMA)
        if preflight.get("plan_sha256") != plan_file_hash:
            raise ValueError("preflight artifact is crossed with the cutover plan")
        expected_token = _confirmation_token(request, _sha256_json(plan))
        if confirmation_token != expected_token or preflight.get("exact_confirmation_token") != expected_token:
            raise ValueError("exact high-risk confirmation token is required")
        self._validate_pidfile(request)
        self._wait_for_external_stop(request)
        self._assert_external_stop_state(request)
        self._validate_static_facts(request, require_running=False)
        stable_inventory = self._wait_for_stable_workspace(request)
        self._assert_external_stop_state(request)
        source_before = self.filesystem.inventory(request.prefix_workspace)
        if source_before != stable_inventory:
            raise ValueError("v1 workspace changed after the stable cutoff observation")
        self.filesystem.copy_tree_exact(request.prefix_workspace, request.frozen_prefix_staging)
        copied_raw = self.filesystem.inventory(request.frozen_prefix_staging)
        if copied_raw != source_before:
            raise ValueError("frozen-prefix raw copy is not byte-for-byte identical")

        truncations = [
            self._truncate_incomplete_jsonl_tail(
                request.frozen_prefix_staging / _RUNTIME_JOURNAL,
                expected_schema="concurrent-message-execution-journal-v1",
                identity_field="identity_hash",
                identity_value=request.expected_v1_run_identity_hash,
            ),
            self._truncate_incomplete_jsonl_tail(
                request.frozen_prefix_staging / _ATTEMPT_LEDGER,
                expected_schema="full-pool-formal-attempt-ledger-v1",
                identity_field="execution_contract_sha256",
                identity_value=request.expected_execution_contract_sha256,
            ),
        ]
        reconciliation = self._reconcile_cross_ledgers(request.frozen_prefix_staging, request)
        self.filesystem.fsync_directory(request.frozen_prefix_staging)
        self._assert_external_stop_state(request)
        source_after_reconciliation = self.filesystem.inventory(request.prefix_workspace)
        self._assert_external_stop_state(request)
        if source_after_reconciliation != source_before:
            raise ValueError("original v1 workspace changed during freeze; cutover is rejected")
        if request.frozen_prefix_workspace.exists() or request.frozen_prefix_workspace.is_symlink():
            raise FileExistsError("frozen-prefix target already exists")
        prefix = _freeze_v1_prefix(request.frozen_prefix_staging)
        unknown_pair_ids = prefix.unknown_pair_ids
        if len(unknown_pair_ids) > 1:
            raise ValueError("cutover has more than one migration unknown; Provider calls remain zero")
        migration_charge = 3 if unknown_pair_ids else 0
        logical_count = prefix.attempt_prefix.logical_count
        physical_count = prefix.attempt_prefix.physical_attempt_count
        remaining_logical = request.logical_cap - logical_count
        remaining_physical = request.physical_cap - physical_count - migration_charge
        if remaining_logical < len(unknown_pair_ids) or remaining_physical < 0:
            raise ValueError("cutover remaining caps do not close the 109200/120120 guard")
        frozen_inventory = self.filesystem.inventory(request.frozen_prefix_staging)
        self._assert_external_stop_state(request)
        if self.filesystem.inventory(request.prefix_workspace) != source_before:
            raise ValueError("original v1 workspace changed before the atomic frozen-prefix publish")
        self.filesystem.replace(request.frozen_prefix_staging, request.frozen_prefix_workspace)
        if self.filesystem.inventory(request.frozen_prefix_workspace) != frozen_inventory:
            raise ValueError("published frozen-prefix inventory differs from validated staging")
        cutover_payload: dict[str, object] = {
            "schema_version": _CUTOVER_SCHEMA,
            "plan_sha256": plan_file_hash,
            "preflight_sha256": preflight_file_hash,
            "manual_external_stop_verified": True,
            "operator_sent_signals": False,
            "pid": request.expected_pid,
            "prefix_workspace": str(request.prefix_workspace),
            "frozen_prefix_workspace": str(request.frozen_prefix_workspace),
            "source_inventory_before_copy": list(source_before.values()),
            "raw_copy_inventory": list(copied_raw.values()),
            "accepted_frozen_inventory": list(frozen_inventory.values()),
            "jsonl_tail_acceptance": truncations,
            "v1_run_identity_hash": request.expected_v1_run_identity_hash,
            "v1_execution_contract_sha256": request.expected_execution_contract_sha256,
            "implementation_commit": request.implementation_commit,
            "dataset_hashes": request.dataset_hashes,
            "provider_calls": 0,
            "production_deploy_eligible": False,
        }
        self._write_artifact(request.cutover_artifact, cutover_payload, exclusive=True)
        cutover_file_hash = self.filesystem.sha256_file(request.cutover_artifact)

        reconciliation_payload: dict[str, object] = {
            "schema_version": _RECONCILIATION_SCHEMA,
            "cutover_sha256": cutover_file_hash,
            **reconciliation,
            "unknown_count": len(unknown_pair_ids),
            "unknown_pair_ids": list(unknown_pair_ids),
            "migration_unknown_physical_charge": migration_charge,
            "silent_terminal_drop_count": 0,
            "terminal_replay_count": 0,
            "provider_calls": 0,
            "production_deploy_eligible": False,
        }
        self._write_artifact(request.reconciliation_artifact, reconciliation_payload, exclusive=True)
        reconciliation_file_hash = self.filesystem.sha256_file(request.reconciliation_artifact)

        authorization_payload: dict[str, object] = {
            "schema_version": _CONTINUATION_AUTHORIZATION_SCHEMA,
            "authorization_reference": request.authorization_reference,
            "issue_number": 205,
            "plan_sha256": plan_file_hash,
            "cutover_sha256": cutover_file_hash,
            "reconciliation_sha256": reconciliation_file_hash,
            "continuation_id": request.continuation_id,
            "continuation_workspace": str(request.continuation_workspace),
            "frozen_prefix_workspace": str(request.frozen_prefix_workspace),
            "dataset_dir": str(request.dataset_dir),
            "dataset_hashes": request.dataset_hashes,
            "implementation_commit": request.implementation_commit,
            "v1_output_identity": request.expected_v1_output_identity,
            "v1_run_identity_hash": request.expected_v1_run_identity_hash,
            "v1_execution_contract_sha256": request.expected_execution_contract_sha256,
            "prefix_logical_count": logical_count,
            "prefix_physical_attempt_count": physical_count,
            "migration_unknown_pair_ids": list(unknown_pair_ids),
            "migration_unknown_physical_charge": migration_charge,
            "remaining_logical_cap": remaining_logical,
            "remaining_physical_cap": remaining_physical,
            "logical_cap": request.logical_cap,
            "physical_cap": request.physical_cap,
            "max_concurrency": request.max_concurrency,
            "qualification_mode": "first-wave-formal-remaining-pairs",
            "source_stop_boundary": "source-v2-only-no-report-release-v9",
            "provider_calls": 0,
            "production_deploy_eligible": False,
        }
        self._write_artifact(
            request.continuation_authorization_artifact,
            authorization_payload,
            exclusive=True,
        )
        return authorization_payload

    def status(self, plan_path: str | Path) -> dict[str, object]:
        """Read status artifacts and process facts without consulting Git or writing files."""
        plan, _ = self._read_plan(plan_path)
        request = CutoverPlanRequest.model_validate(_request_fields(plan))
        process = self.process_controller.snapshot(request.expected_pid)
        process_state = "not_running"
        if process is not None:
            process_state = (
                "running"
                if process.command == request.expected_command and process.cwd == request.expected_cwd
                else "pid_reused_or_crossed"
            )
        response: dict[str, object] = {
            "schema_version": "full-pool-segmented-operator-status-v1",
            "pid": request.expected_pid,
            "process_state": process_state,
            "prefix_logical_count": None,
            "suffix_logical_count": 0,
            "physical_attempt_count": None,
            "unknown_pair_ids": [],
            "source_status": "not_cut_over",
            "remaining_logical_cap": None,
            "remaining_physical_cap": None,
            "production_deploy_eligible": False,
        }
        if request.continuation_authorization_artifact.is_file():
            authorization, _ = self._read_artifact(
                request.continuation_authorization_artifact,
                _CONTINUATION_AUTHORIZATION_SCHEMA,
            )
            prefix_logical = _strict_int(authorization.get("prefix_logical_count"), "prefix logical count")
            prefix_physical = _strict_int(
                authorization.get("prefix_physical_attempt_count"), "prefix physical count"
            )
            migration_unknown = _string_list(
                authorization.get("migration_unknown_pair_ids"), "migration unknown pair ids"
            )
            response.update(
                {
                    "prefix_logical_count": prefix_logical,
                    "physical_attempt_count": prefix_physical,
                    "unknown_pair_ids": migration_unknown,
                    "source_status": "frozen_prefix",
                    "remaining_logical_cap": authorization.get("remaining_logical_cap"),
                    "remaining_physical_cap": authorization.get("remaining_physical_cap"),
                }
            )
        continuation_status = request.continuation_workspace / "segmented_continuation_status.json"
        if continuation_status.is_file():
            status = _read_json(continuation_status)
            total_logical = _strict_int(status.get("logical_count"), "continuation logical count")
            total_physical = _strict_int(status.get("physical_attempt_count"), "continuation physical count")
            prefix_logical_value = response.get("prefix_logical_count")
            prefix_logical = prefix_logical_value if isinstance(prefix_logical_value, int) else 0
            unknown = _string_list(status.get("unknown_pair_ids"), "continuation unknown pair ids")
            source_root = request.continuation_workspace / "source-v2"
            source_manifest = source_root / "manifest.json"
            expected_source_hash = status.get("source_manifest_sha256")
            source_closed = (
                status.get("lifecycle") == "complete"
                and source_root.is_dir()
                and source_manifest.is_file()
                and isinstance(expected_source_hash, str)
                and self.filesystem.sha256_file(source_manifest) == expected_source_hash
            )
            response.update(
                {
                    "suffix_logical_count": total_logical - prefix_logical,
                    "physical_attempt_count": total_physical,
                    "unknown_pair_ids": unknown,
                    "source_status": (
                        "source-v2-closed"
                        if source_closed
                        else (
                            "source-v2-invalid"
                            if status.get("lifecycle") == "complete"
                            else str(status.get("lifecycle"))
                        )
                    ),
                    "remaining_logical_cap": request.logical_cap - total_logical,
                    "remaining_physical_cap": request.physical_cap - total_physical,
                }
            )
        elif request.continuation_workspace.is_dir():
            authorization, _ = self._read_artifact(
                request.continuation_authorization_artifact,
                _CONTINUATION_AUTHORIZATION_SCHEMA,
            )
            identity = _read_json(request.continuation_workspace / "segmented_continuation_identity.json")
            identity_hash = _non_empty(identity.get("identity_hash"), "continuation identity hash")
            ledger_path = request.continuation_workspace / "segmented_continuation_ledger.jsonl"
            dispatched, durable, suffix_physical, source_anchor = _replay_continuation_ledger(
                ledger_path,
                expected_identity_hash=identity_hash,
                snapshot_bytes=ledger_path.read_bytes(),
                allow_inflight_wave=True,
            )
            prefix_logical = _strict_int(
                authorization.get("prefix_logical_count"), "prefix logical count"
            )
            prefix_physical = _strict_int(
                authorization.get("prefix_physical_attempt_count"), "prefix physical count"
            )
            migration_charge = _strict_int(
                authorization.get("migration_unknown_physical_charge"), "migration physical charge"
            )
            total_logical = prefix_logical + len(dispatched)
            total_physical = prefix_physical + migration_charge + suffix_physical
            durable_set = set(durable)
            unknown = [pair_id for pair_id in dispatched if pair_id not in durable_set]
            response.update(
                {
                    "suffix_logical_count": len(dispatched),
                    "physical_attempt_count": total_physical,
                    "unknown_pair_ids": unknown,
                    "source_status": (
                        "source-v2-prepared" if source_anchor is not None else "concurrent_suffix_running"
                    ),
                    "remaining_logical_cap": request.logical_cap - total_logical,
                    "remaining_physical_cap": request.physical_cap - total_physical,
                }
            )
        elif request.continuation_workspace.exists() or request.continuation_workspace.is_symlink():
            response["source_status"] = "continuation-workspace-invalid"
        return response

    def run(
        self,
        plan_path: str | Path,
        *,
        client_factory: Callable[..., PiSubscriptionProviderClient] = PiSubscriptionProviderClient,
    ) -> SegmentedContinuationResult:
        plan, plan_file_hash = self._read_plan(plan_path)
        self._validate_implementation_artifacts(plan)
        request = CutoverPlanRequest.model_validate(_request_fields(plan))
        authorization, authorization_hash = self._validate_run_artifacts(
            request,
            plan_file_hash=plan_file_hash,
        )
        continuation_exists = request.continuation_workspace.exists() or request.continuation_workspace.is_symlink()
        self._validate_qualification_state(
            request,
            continuation_exists=continuation_exists,
            authorization_hash=authorization_hash,
        )
        if os.environ.get("LLM_ABM_RUN_LIVE_LLM") != "1" or os.environ.get(SEGMENTED_LIVE_GATE) != "1":
            raise RuntimeError(
                f"live segmented run requires LLM_ABM_RUN_LIVE_LLM=1 and {SEGMENTED_LIVE_GATE}=1"
            )
        if request.continuation_workspace.exists():
            return FullPoolSegmentedContinuation().run(
                request.frozen_prefix_workspace,
                request.continuation_workspace,
                continuation_id=request.continuation_id,
                dataset_dir=request.dataset_dir,
                adapter_factory=lambda _lane_id: (_ for _ in ()).throw(
                    AssertionError("existing continuation must replay without Adapter creation")
                ),
                reconciliation_authorization=self._migration_authorization(request, authorization),
            )

        run_identity = _read_json(request.frozen_prefix_workspace / _RUNTIME_IDENTITY)
        primary_contract = _mapping(
            _mapping(run_identity.get("provider_contract"), "v1 provider contract").get("primary"),
            "v1 Primary provider contract",
        )
        _validate_live_provider_contract(primary_contract)
        qualification = _QualificationRecorder(
            path=request.qualification_artifact,
            filesystem=self.filesystem,
            continuation_authorization_sha256=authorization_hash,
        )
        pool = LiveLanePool(prompt_version=SEGMENTED_PROMPT_VERSION, client_factory=client_factory)
        result: SegmentedContinuationResult | None = None
        try:
            result = FullPoolSegmentedContinuation().run(
                request.frozen_prefix_workspace,
                request.continuation_workspace,
                continuation_id=request.continuation_id,
                dataset_dir=request.dataset_dir,
                adapter_factory=pool.adapter_factory,
                reconciliation_authorization=self._migration_authorization(request, authorization),
                first_wave_observer=qualification.observe,
            )
        except Exception:
            if not request.qualification_artifact.is_file():
                qualification.record_unreconciled_failure(None)
            raise
        finally:
            pool.close()
        if not request.qualification_artifact.is_file():
            qualification.record_unreconciled_failure(result)
        assert result is not None
        return result

    def _validate_static_facts(
        self,
        request: CutoverPlanRequest,
        *,
        require_running: bool,
    ) -> dict[str, object]:
        if request.prefix_workspace.is_symlink() or not request.prefix_workspace.is_dir():
            raise ValueError("v1 prefix workspace must be an explicit real directory")
        if request.dataset_dir.is_symlink() or not request.dataset_dir.is_dir():
            raise ValueError("dataset_dir must be an explicit real directory")
        self._validate_pidfile(request)
        runtime = _read_json(request.prefix_workspace / _RUNTIME_IDENTITY)
        formal = _read_json(request.prefix_workspace / _FORMAL_IDENTITY)
        fingerprints = _mapping(runtime.get("sample_data_fingerprints"), "v1 dataset fingerprints")
        expected = {
            "output_identity": request.expected_v1_output_identity,
            "operational_root": request.expected_v1_operational_root,
            "source_root": request.expected_v1_source_root,
            "candidate_root": request.expected_v1_candidate_root,
            "execution_contract_sha256": request.expected_execution_contract_sha256,
        }
        for field_name, value in expected.items():
            if formal.get(field_name) != value:
                raise ValueError(f"v1 Formal identity {field_name} is crossed")
        if runtime.get("identity_hash") != request.expected_v1_run_identity_hash:
            raise ValueError("v1 runtime identity hash is crossed")
        if runtime.get("operational_workspace") != request.expected_v1_recorded_runtime_workspace:
            raise ValueError("v1 recorded runtime workspace is crossed")
        if runtime.get("output_target") != request.expected_v1_recorded_output_target:
            raise ValueError("v1 recorded output target is crossed")
        if fingerprints.get("dataset_dir") != request.expected_v1_dataset_dir:
            raise ValueError("v1 recorded dataset path is crossed")
        recorded_hashes = _mapping(fingerprints.get("dataset_files"), "v1 dataset hashes")
        if dict(sorted(recorded_hashes.items())) != request.dataset_hashes:
            raise ValueError("explicit dataset hashes are crossed with the v1 identity")
        for relative, expected_hash in request.dataset_hashes.items():
            path = request.dataset_dir / relative
            if not path.is_file() or self.filesystem.sha256_file(path) != expected_hash:
                raise ValueError(f"dataset hash mismatch for {relative}")
        if request.frozen_prefix_workspace.exists() or request.frozen_prefix_staging.exists():
            raise FileExistsError("frozen-prefix or its explicit staging path already exists")
        if request.continuation_workspace.exists():
            raise FileExistsError("continuation workspace already exists during prepare/preflight")
        if require_running:
            snapshot = self.process_controller.snapshot(request.expected_pid)
            if snapshot is None:
                raise ValueError("expected v1 PID is not running")
            if snapshot.command != request.expected_command or snapshot.cwd != request.expected_cwd:
                raise ValueError("PID command or cwd is crossed")
            owners = self.process_controller.lock_owner_pids(request.prefix_workspace / _LOCK_FILE)
            if owners != (request.expected_pid,):
                raise ValueError("workspace lock owner is not exactly the expected v1 PID")
        return {
            "v1_output_identity": request.expected_v1_output_identity,
            "v1_run_identity_hash": request.expected_v1_run_identity_hash,
            "execution_contract_sha256": request.expected_execution_contract_sha256,
            "dataset_hashes": request.dataset_hashes,
            "pid": request.expected_pid,
        }

    def _validate_pidfile(self, request: CutoverPlanRequest) -> None:
        if request.pidfile.is_symlink() or not request.pidfile.is_file():
            raise ValueError("pidfile must be an explicit regular file")
        raw = request.pidfile.read_text(encoding="utf-8")
        if raw.strip() != str(request.expected_pid) or not raw.endswith("\n"):
            raise ValueError("pidfile does not contain exactly the expected PID")

    def _wait_for_external_stop(self, request: CutoverPlanRequest) -> None:
        deadline = time.monotonic() + request.stop_wait_timeout_seconds
        lock_path = request.prefix_workspace / _LOCK_FILE
        while True:
            snapshot = self.process_controller.snapshot(request.expected_pid)
            if snapshot is not None and (
                snapshot.command != request.expected_command or snapshot.cwd != request.expected_cwd
            ):
                raise ValueError("expected PID was reused or crossed during the external-stop wait")
            owners = self.process_controller.lock_owner_pids(lock_path)
            released = self.process_controller.lock_is_released(lock_path)
            if snapshot is None and not owners and released:
                return
            if time.monotonic() >= deadline:
                raise TimeoutError("external stop did not release the exact PID and workspace lock")
            self.process_controller.sleep(min(request.stability_interval_seconds, 1.0))

    def _assert_external_stop_state(self, request: CutoverPlanRequest) -> None:
        lock_path = request.prefix_workspace / _LOCK_FILE
        if self.process_controller.snapshot(request.expected_pid) is not None:
            raise ValueError("expected v1 PID reappeared after the external stop")
        if self.process_controller.lock_owner_pids(lock_path):
            raise ValueError("v1 workspace lock regained an owner after the external stop")
        if not self.process_controller.lock_is_released(lock_path):
            raise ValueError("v1 workspace lock was reacquired after the external stop")

    def _wait_for_stable_workspace(self, request: CutoverPlanRequest) -> dict[str, dict[str, object]]:
        first = self.filesystem.inventory(request.prefix_workspace)
        self.process_controller.sleep(request.stability_interval_seconds)
        second = self.filesystem.inventory(request.prefix_workspace)
        if first != second:
            raise ValueError("v1 workspace files are not stable after the external stop")
        return second

    def _truncate_incomplete_jsonl_tail(
        self,
        path: Path,
        *,
        expected_schema: str,
        identity_field: str,
        identity_value: str,
    ) -> dict[str, object]:
        original = path.read_bytes()
        original_hash = hashlib.sha256(original).hexdigest()
        lines = original.splitlines(keepends=True)
        sequence = 0
        previous: str | None = None
        accepted_length = 0
        truncated = False
        for index, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                raise ValueError(f"{path.name} contains a blank checksum-chain record")
            terminated = line.endswith(b"\n")
            try:
                record = json.loads(stripped)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                if index != len(lines) - 1 or terminated:
                    raise ValueError(f"{path.name} is corrupt before its incomplete tail") from exc
                truncated = True
                break
            if not isinstance(record, dict):
                raise ValueError("JSONL record is not an object")
            checksum = record.get("checksum")
            body = {key: value for key, value in record.items() if key != "checksum"}
            if (
                record.get("schema_version") != expected_schema
                or record.get(identity_field) != identity_value
                or record.get("sequence") != sequence + 1
                or record.get("previous_checksum") != previous
                or not isinstance(checksum, str)
                or _sha256_json(body) != checksum
            ):
                raise ValueError("JSONL checksum chain is crossed")
            if not terminated:
                if index != len(lines) - 1:
                    raise ValueError(f"{path.name} contains an unterminated middle record")
                truncated = True
                break
            sequence += 1
            previous = checksum
            accepted_length += len(line)
        if sequence == 0:
            raise ValueError(f"{path.name} has no complete checksum-chain record")
        if truncated:
            with path.open("r+b") as handle:
                handle.truncate(accepted_length)
                handle.flush()
                os.fsync(handle.fileno())
        accepted_hash = self.filesystem.sha256_file(path)
        return {
            "relative_path": path.name,
            "original_bytes": len(original),
            "original_sha256": original_hash,
            "accepted_bytes": accepted_length if truncated else len(original),
            "accepted_sha256": accepted_hash,
            "truncated_bytes": len(original) - accepted_length if truncated else 0,
            "last_sequence": sequence,
            "last_checksum": previous,
        }

    def _reconcile_cross_ledgers(
        self,
        workspace: Path,
        request: CutoverPlanRequest,
    ) -> dict[str, object]:
        runtime_records = _read_jsonl(workspace / _RUNTIME_JOURNAL)
        ledger_records = _read_jsonl(workspace / _ATTEMPT_LEDGER)
        runtime_started: list[str] = []
        runtime_terminals: dict[str, dict[str, object]] = {}
        runtime_checksums: dict[str, str] = {}
        for record in runtime_records:
            if record.get("record_type") != "event":
                continue
            identity = _mapping(record.get("event_identity"), "runtime event identity")
            pair_id = identity.get("pair_id")
            if record.get("event_type") == "variant_started" and isinstance(pair_id, str):
                runtime_started.append(pair_id)
            elif record.get("event_type") == "variant_terminal" and isinstance(pair_id, str):
                if pair_id in runtime_terminals:
                    raise ValueError("runtime journal contains duplicate durable terminals")
                runtime_terminals[pair_id] = _mapping(record.get("payload"), "runtime terminal payload")
                runtime_checksums[pair_id] = cast(str, record.get("checksum"))
        ledger_state = _attempt_ledger_state(ledger_records)
        ledger_terminal_ids = set(cast(list[str], ledger_state["terminal_pair_ids"]))
        runtime_terminal_ids = set(runtime_terminals)
        if ledger_terminal_ids - runtime_terminal_ids:
            raise ValueError("attempt ledger terminal lacks runtime durable variant evidence")
        missing = sorted(runtime_terminal_ids - ledger_terminal_ids)
        if len(missing) > 1:
            raise ValueError("more than one runtime terminal is absent from the attempt ledger")
        imports: list[dict[str, object]] = []
        if missing:
            pair_id = missing[0]
            if ledger_state["pending_pair_id"] != pair_id:
                raise ValueError("runtime terminal cannot be reconciled to the pending attempt reservation")
            terminal_payload = runtime_terminals[pair_id]
            evidence = _mapping(terminal_payload.get("variant_evidence"), "runtime durable variant evidence")
            accounting = _allowlisted_accounting(evidence)
            requests = _strict_int(accounting.get("request_invocations"), "runtime request invocations")
            pending_attempts = _strict_int(ledger_state["pending_physical_count"], "pending attempts")
            if not 1 <= requests <= 3 or pending_attempts > requests:
                raise ValueError("runtime terminal request accounting cannot close the attempt ledger")
            imported_checksums: list[str] = []
            for attempt_index in range(pending_attempts + 1, requests + 1):
                checksum = _append_checksum_record(
                    workspace / _ATTEMPT_LEDGER,
                    ledger_records,
                    {
                        "schema_version": "full-pool-formal-attempt-ledger-v1",
                        "sequence": len(ledger_records) + 1,
                        "previous_checksum": ledger_records[-1]["checksum"],
                        "execution_contract_sha256": request.expected_execution_contract_sha256,
                        "event_type": "physical_attempt_accounted",
                        "payload": {
                            "pair_id": pair_id,
                            "attempt_index": attempt_index,
                            "attempt_outcome": (
                                f"terminal_{terminal_payload.get('terminal_status')}"
                                if attempt_index == requests
                                else "retry_consumed"
                            ),
                        },
                    },
                )
                imported_checksums.append(checksum)
            checksum = _append_checksum_record(
                workspace / _ATTEMPT_LEDGER,
                ledger_records,
                {
                    "schema_version": "full-pool-formal-attempt-ledger-v1",
                    "sequence": len(ledger_records) + 1,
                    "previous_checksum": ledger_records[-1]["checksum"],
                    "execution_contract_sha256": request.expected_execution_contract_sha256,
                    "event_type": "judgment_terminal",
                    "payload": {
                        "pair_id": pair_id,
                        "terminal_status": terminal_payload.get("terminal_status"),
                        "accounting": accounting,
                    },
                },
            )
            imported_checksums.append(checksum)
            imports.append(
                {
                    "pair_id": pair_id,
                    "runtime_terminal_record_checksum": runtime_checksums[pair_id],
                    "runtime_variant_evidence_sha256": _sha256_json(evidence),
                    "imported_attempt_ledger_checksums": imported_checksums,
                    "request_invocations": requests,
                }
            )
            ledger_state = _attempt_ledger_state(ledger_records)

        unknown = tuple(pair_id for pair_id in runtime_started if pair_id not in runtime_terminal_ids)
        if len(unknown) > 1 or len(set(unknown)) != len(unknown):
            raise ValueError("more than one migration unknown is forbidden")
        pending_pair_id = ledger_state["pending_pair_id"]
        if pending_pair_id != (unknown[0] if unknown else None):
            raise ValueError("runtime and attempt-ledger unknown identities are crossed")
        full_status = _read_json(workspace / _FORMAL_STATUS)
        full_status.update(
            {
                "schema_version": "full-pool-formal-operational-status-v1",
                "lifecycle": "reconciliation_required" if unknown else "resumable_interruption",
                "execution_contract_sha256": request.expected_execution_contract_sha256,
                "logical_judgments": ledger_state["logical_count"],
                "physical_attempts": ledger_state["physical_attempt_count"],
                "reserved_logical_judgments": _strict_int(ledger_state["logical_count"], "logical count")
                + len(unknown),
                "reserved_physical_attempts": _strict_int(
                    ledger_state["physical_attempt_count"], "physical count"
                )
                + (3 if unknown else 0),
                "last_pair_id": unknown[0] if unknown else cast(list[str], ledger_state["terminal_pair_ids"])[-1],
                "production_deploy_eligible": False,
            }
        )
        self.filesystem.write_json(workspace / _FORMAL_STATUS, full_status)
        return {
            "runtime_terminal_count": len(runtime_terminal_ids),
            "attempt_ledger_terminal_count": len(cast(list[str], ledger_state["terminal_pair_ids"])),
            "imported_terminal_count": len(imports),
            "imports": imports,
            "accepted_logical_count": ledger_state["logical_count"],
            "accepted_physical_attempt_count": ledger_state["physical_attempt_count"],
        }

    @staticmethod
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
            raise ValueError("loaded repository commit is not an exact Git identity")
        return commit

    def _implementation_artifacts(self) -> dict[str, str]:
        repository = Path(__file__).resolve().parents[2]
        paths = {
            "operator_module": Path(__file__).resolve(),
            "continuation_module": (repository / "src/llm_abm_sim/full_pool_segmented_continuation.py").resolve(),
            "operator_cli": (repository / "scripts/run_full_pool_segmented_continuation.py").resolve(),
        }
        artifacts: dict[str, str] = {}
        for label, path in paths.items():
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"tracked implementation artifact is missing or unsafe: {label}")
            artifacts[label] = self.filesystem.sha256_file(path)
        return artifacts

    def _validate_implementation_artifacts(self, plan: Mapping[str, object]) -> None:
        if plan.get("loaded_repository_commit") != self._repository_commit():
            raise ValueError("loaded repository commit differs from the prepared operator commit")
        expected = _mapping(plan.get("implementation_artifacts"), "implementation artifacts")
        if expected != self._implementation_artifacts():
            raise ValueError("loaded operator/source bytes differ from the prepared implementation artifacts")

    def _read_plan(self, path: str | Path) -> tuple[dict[str, object], str]:
        resolved = Path(path).expanduser().resolve(strict=True)
        payload, file_hash = self._read_artifact(resolved, _PLAN_SCHEMA)
        if payload.get("plan_path") != str(resolved):
            raise ValueError("cutover plan path is crossed")
        return payload, file_hash

    def _write_artifact(
        self,
        path: Path,
        payload: Mapping[str, object],
        *,
        exclusive: bool = False,
    ) -> None:
        envelope = {
            "schema_version": _ARTIFACT_ENVELOPE_SCHEMA,
            "payload": dict(payload),
            "payload_sha256": _sha256_json(payload),
        }
        self.filesystem.write_json(path, envelope, exclusive=exclusive)

    def _read_artifact(self, path: Path, schema: str) -> tuple[dict[str, object], str]:
        envelope = _read_json(path)
        if envelope.get("schema_version") != _ARTIFACT_ENVELOPE_SCHEMA:
            raise ValueError(f"unsupported operator artifact envelope: {path}")
        payload = _mapping(envelope.get("payload"), "operator artifact payload")
        if payload.get("schema_version") != schema or envelope.get("payload_sha256") != _sha256_json(payload):
            raise ValueError(f"operator artifact hash or schema mismatch: {path}")
        return payload, self.filesystem.sha256_file(path)

    def _validate_run_artifacts(
        self,
        request: CutoverPlanRequest,
        *,
        plan_file_hash: str,
    ) -> tuple[dict[str, object], str]:
        preflight, preflight_hash = self._read_artifact(request.preflight_artifact, _PREFLIGHT_SCHEMA)
        cutover, cutover_hash = self._read_artifact(request.cutover_artifact, _CUTOVER_SCHEMA)
        reconciliation, reconciliation_hash = self._read_artifact(
            request.reconciliation_artifact, _RECONCILIATION_SCHEMA
        )
        authorization, authorization_hash = self._read_artifact(
            request.continuation_authorization_artifact,
            _CONTINUATION_AUTHORIZATION_SCHEMA,
        )
        expected_preflight = {
            "plan_sha256": plan_file_hash,
            "pid": request.expected_pid,
            "command": request.expected_command,
            "cwd": str(request.expected_cwd),
            "lock_path": str(request.prefix_workspace / _LOCK_FILE),
            "lock_owner_pids": [request.expected_pid],
            "manual_stop_required": True,
            "operator_will_send_signals": False,
            "provider_calls": 0,
            "production_deploy_eligible": False,
        }
        for field, expected in expected_preflight.items():
            if preflight.get(field) != expected:
                raise ValueError(f"preflight artifact {field} is crossed with the current plan")
        expected_cutover = {
            "plan_sha256": plan_file_hash,
            "preflight_sha256": preflight_hash,
            "manual_external_stop_verified": True,
            "operator_sent_signals": False,
            "pid": request.expected_pid,
            "prefix_workspace": str(request.prefix_workspace),
            "frozen_prefix_workspace": str(request.frozen_prefix_workspace),
            "v1_run_identity_hash": request.expected_v1_run_identity_hash,
            "v1_execution_contract_sha256": request.expected_execution_contract_sha256,
            "implementation_commit": request.implementation_commit,
            "dataset_hashes": request.dataset_hashes,
            "provider_calls": 0,
            "production_deploy_eligible": False,
        }
        for field, expected in expected_cutover.items():
            if cutover.get(field) != expected:
                raise ValueError(f"cutover artifact {field} is crossed with the current plan")
        if reconciliation.get("cutover_sha256") != cutover_hash:
            raise ValueError("reconciliation artifact is crossed with cutover")
        unknown = _string_list(authorization.get("migration_unknown_pair_ids"), "unknown pairs")
        if len(unknown) > 1:
            raise ValueError("more than one migration unknown forbids Provider use")
        migration_charge = 3 if unknown else 0
        if (
            reconciliation.get("unknown_count") != len(unknown)
            or reconciliation.get("unknown_pair_ids") != unknown
            or reconciliation.get("migration_unknown_physical_charge") != migration_charge
            or reconciliation.get("silent_terminal_drop_count") != 0
            or reconciliation.get("terminal_replay_count") != 0
            or reconciliation.get("provider_calls") != 0
            or reconciliation.get("production_deploy_eligible") is not False
        ):
            raise ValueError("reconciliation artifact facts are crossed")
        prefix_logical = _strict_int(
            reconciliation.get("accepted_logical_count"), "accepted prefix logical count"
        )
        prefix_physical = _strict_int(
            reconciliation.get("accepted_physical_attempt_count"), "accepted prefix physical count"
        )
        expected_authorization = {
            "authorization_reference": request.authorization_reference,
            "issue_number": 205,
            "plan_sha256": plan_file_hash,
            "cutover_sha256": cutover_hash,
            "reconciliation_sha256": reconciliation_hash,
            "continuation_id": request.continuation_id,
            "continuation_workspace": str(request.continuation_workspace),
            "frozen_prefix_workspace": str(request.frozen_prefix_workspace),
            "dataset_dir": str(request.dataset_dir),
            "dataset_hashes": request.dataset_hashes,
            "implementation_commit": request.implementation_commit,
            "v1_output_identity": request.expected_v1_output_identity,
            "v1_run_identity_hash": request.expected_v1_run_identity_hash,
            "v1_execution_contract_sha256": request.expected_execution_contract_sha256,
            "prefix_logical_count": prefix_logical,
            "prefix_physical_attempt_count": prefix_physical,
            "migration_unknown_pair_ids": unknown,
            "migration_unknown_physical_charge": migration_charge,
            "remaining_logical_cap": request.logical_cap - prefix_logical,
            "remaining_physical_cap": request.physical_cap - prefix_physical - migration_charge,
            "logical_cap": request.logical_cap,
            "physical_cap": request.physical_cap,
            "max_concurrency": request.max_concurrency,
            "qualification_mode": "first-wave-formal-remaining-pairs",
            "source_stop_boundary": "source-v2-only-no-report-release-v9",
            "provider_calls": 0,
            "production_deploy_eligible": False,
        }
        for field, expected in expected_authorization.items():
            if authorization.get(field) != expected:
                raise ValueError(f"continuation authorization {field} is crossed with the current plan")
        if self.filesystem.inventory(request.prefix_workspace) != _inventory_mapping(
            cutover.get("source_inventory_before_copy")
        ):
            raise ValueError("original v1 workspace changed after cutover")
        if self.filesystem.inventory(request.frozen_prefix_workspace) != _inventory_mapping(
            cutover.get("accepted_frozen_inventory")
        ):
            raise ValueError("frozen-prefix inventory changed after cutover")
        for relative, digest in request.dataset_hashes.items():
            if self.filesystem.sha256_file(request.dataset_dir / relative) != digest:
                raise ValueError("dataset changed after cutover")
        remaining_logical = _strict_int(authorization.get("remaining_logical_cap"), "remaining logical cap")
        remaining_physical = _strict_int(authorization.get("remaining_physical_cap"), "remaining physical cap")
        if remaining_logical < FULL_POOL_SEGMENTED_MAX_CONCURRENCY or remaining_physical < 30:
            raise ValueError("remaining caps cannot reserve the mandatory ten-lane qualification wave")
        return authorization, authorization_hash

    def _validate_qualification_state(
        self,
        request: CutoverPlanRequest,
        *,
        continuation_exists: bool,
        authorization_hash: str,
    ) -> None:
        path = request.qualification_artifact
        if not continuation_exists:
            if path.exists() or path.is_symlink():
                raise FileExistsError("qualification artifact must be absent before the first official wave")
            return
        if path.is_symlink() or not path.is_file():
            raise ValueError("existing continuation lacks its bounded qualification artifact")
        qualification, _ = self._read_artifact(path, _QUALIFICATION_SCHEMA)
        if (
            qualification.get("continuation_authorization_sha256") != authorization_hash
            or qualification.get("status") != "qualified"
            or qualification.get("lane_count") != FULL_POOL_SEGMENTED_MAX_CONCURRENCY
            or qualification.get("provider_concurrency_reduction") is not False
        ):
            raise ValueError("existing continuation qualification is failed or crossed")
        qualification_hash = self.filesystem.sha256_file(path)
        source_manifest = request.continuation_workspace / "source-v2/manifest.json"
        if source_manifest.is_file():
            manifest = _read_json(source_manifest)
            copied_qualification = request.continuation_workspace / (
                "source-v2/" + SEGMENTED_CONCURRENCY_QUALIFICATION_FILE
            )
            if (
                manifest.get("concurrency_qualification_artifact_sha256") != qualification_hash
                or not copied_qualification.is_file()
                or self.filesystem.sha256_file(copied_qualification) != qualification_hash
            ):
                raise ValueError("source-v2 qualification lineage is crossed with the operator artifact")

    @staticmethod
    def _migration_authorization(
        request: CutoverPlanRequest,
        authorization: Mapping[str, object],
    ) -> FullPoolReconciliationAuthorization | None:
        unknown = _string_list(authorization.get("migration_unknown_pair_ids"), "migration unknown pairs")
        if not unknown:
            return None
        return FullPoolReconciliationAuthorization(
            prefix_run_identity_hash=request.expected_v1_run_identity_hash,
            unknown_pair_id=unknown[0],
            authorization_reference=request.authorization_reference,
            physical_attempt_charge=3,
            retry_authorized=True,
        )


class LiveLanePool:
    """Creates exactly ten isolated Pi clients and Adapters; it never reduces concurrency."""

    def __init__(
        self,
        *,
        prompt_version: str,
        client_factory: Callable[..., PiSubscriptionProviderClient] = PiSubscriptionProviderClient,
    ) -> None:
        if os.environ.get("LLM_ABM_RUN_LIVE_LLM") != "1" or os.environ.get(SEGMENTED_LIVE_GATE) != "1":
            raise RuntimeError("ten-lane pool requires both explicit live environment gates")
        self.prompt_version = prompt_version
        self.client_factory = client_factory
        self.clients: dict[int, PiSubscriptionProviderClient] = {}
        self.adapters: dict[int, LLMDecisionAdapter] = {}

    def adapter_factory(self, lane_id: int) -> LLMDecisionAdapter:
        if not 0 <= lane_id < FULL_POOL_SEGMENTED_MAX_CONCURRENCY:
            raise ValueError("lane_id is outside the frozen ten-lane range")
        if lane_id in self.adapters:
            raise ValueError("adapter_factory refuses duplicate lane creation")
        client = self.client_factory(response_timeout_seconds=30.0)
        try:
            if any(client is existing for existing in self.clients.values()):
                raise ValueError("Pi client factory returned a shared client")
            _validate_live_client(client)
            adapter = OpenAICompatibleDecisionAdapter(
                ProviderLLMConfig(
                    enabled=True,
                    provider="openai_compatible",
                    model=SEGMENTED_REQUESTED_MODEL,
                    wire_api="responses",
                    require_live_env=True,
                    timeout_seconds=30.0,
                    max_retries=2,
                    retry_backoff_seconds=1.0,
                    fail_closed_action=FailClosedAction.RAISE,
                    prompt_version=self.prompt_version,
                    reasoning_effort=ReasoningEffort.LOW,
                    max_output_tokens=256,
                ),
                client=client,
            )
            FullPoolFormalRequestContract.model_validate(adapter.request_contract.audit_record())
        except Exception:
            client.close()
            raise
        self.clients[lane_id] = client
        self.adapters[lane_id] = adapter
        return adapter

    def close(self) -> None:
        first_error: Exception | None = None
        for lane_id in sorted(self.clients, reverse=True):
            try:
                self.clients[lane_id].close()
            except Exception as exc:  # pragma: no cover - real transport cleanup failure.
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error


def _validate_live_client(client: PiSubscriptionProviderClient) -> None:
    if client.ready is not True or client.response_timeout_seconds != 30.0:
        raise ValueError("Pi client is not ready with the exact timeout contract")
    metadata = _mapping(client.safe_metadata, "Pi client safe metadata")
    expected = {
        "provider_transport": PI_SUBSCRIPTION_PROVIDER,
        "adapter_identity": PI_SUBSCRIPTION_ADAPTER_IDENTITY,
        "requested_model_aliases": PI_SUBSCRIPTION_MODEL_ALIASES,
        "output_token_ceiling_enforcement": "application_fail_closed",
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            raise ValueError(f"Pi client safe metadata {key} is crossed")


class _QualificationRecorder:
    def __init__(
        self,
        *,
        path: Path,
        filesystem: LocalOperatorFilesystem,
        continuation_authorization_sha256: str,
    ) -> None:
        self.path = path
        self.filesystem = filesystem
        self.authorization_hash = continuation_authorization_sha256

    def observe(self, wave: SegmentedQualificationWave) -> SegmentedQualificationArtifactRef:
        errors = wave.physical_attempt_count - wave.provider_response_count
        qualified = (
            len(wave.pair_ids) == FULL_POOL_SEGMENTED_MAX_CONCURRENCY
            and wave.physical_attempt_count == FULL_POOL_SEGMENTED_MAX_CONCURRENCY
            and wave.provider_response_count == FULL_POOL_SEGMENTED_MAX_CONCURRENCY
            and wave.successful_decision_count == FULL_POOL_SEGMENTED_MAX_CONCURRENCY
            and wave.terminal_status_counts == {"succeeded": FULL_POOL_SEGMENTED_MAX_CONCURRENCY}
            and wave.observed_model_counts == {SEGMENTED_REQUESTED_MODEL: FULL_POOL_SEGMENTED_MAX_CONCURRENCY}
            and wave.usage_complete_response_count == FULL_POOL_SEGMENTED_MAX_CONCURRENCY
            and wave.usage_missing_response_count == 0
            and wave.usage_malformed_response_count == 0
            and errors == 0
        )
        payload: dict[str, object] = {
            "schema_version": _QUALIFICATION_SCHEMA,
            "continuation_authorization_sha256": self.authorization_hash,
            "mode": "first-wave-formal-remaining-pairs",
            "status": "qualified" if qualified else "failed",
            "pair_ids": list(wave.pair_ids),
            "lane_count": len(wave.pair_ids),
            "elapsed_seconds": wave.elapsed_seconds,
            "actual_request_rate_per_second": len(wave.pair_ids) / wave.elapsed_seconds,
            "physical_attempt_count": wave.physical_attempt_count,
            "provider_response_count": wave.provider_response_count,
            "successful_decision_count": wave.successful_decision_count,
            "error_count": errors,
            "terminal_status_counts": wave.terminal_status_counts,
            "observed_model_counts": wave.observed_model_counts,
            "usage_complete_response_count": wave.usage_complete_response_count,
            "usage_missing_response_count": wave.usage_missing_response_count,
            "usage_malformed_response_count": wave.usage_malformed_response_count,
            "input_tokens": wave.input_tokens,
            "output_tokens": wave.output_tokens,
            "total_tokens": wave.total_tokens,
            "cached_input_tokens": wave.cached_input_tokens,
            "formal_remaining_pairs_consumed": len(wave.pair_ids),
            "provider_concurrency_reduction": False,
            "production_deploy_eligible": False,
        }
        FullPoolSegmentedCutoverOperator(filesystem=self.filesystem)._write_artifact(
            self.path, payload, exclusive=True
        )
        if not qualified:
            raise ValueError("ten-lane bounded qualification failed; concurrency will not be reduced")
        return SegmentedQualificationArtifactRef(
            path=self.path.resolve(strict=True),
            sha256=self.filesystem.sha256_file(self.path),
        )

    def record_unreconciled_failure(self, result: SegmentedContinuationResult | None) -> None:
        payload: dict[str, object] = {
            "schema_version": _QUALIFICATION_SCHEMA,
            "continuation_authorization_sha256": self.authorization_hash,
            "mode": "first-wave-formal-remaining-pairs",
            "status": "failed_unreconciled",
            "result_status": result.status.value if result is not None else "exception_before_result",
            "actual_metrics_status": "unavailable_due_to_unknown_response_provenance",
            "provider_concurrency_reduction": False,
            "production_deploy_eligible": False,
        }
        FullPoolSegmentedCutoverOperator(filesystem=self.filesystem)._write_artifact(
            self.path, payload, exclusive=True
        )


def _validate_live_provider_contract(contract: Mapping[str, object]) -> None:
    expected = {
        "enabled": True,
        "provider": "openai_compatible",
        "model": SEGMENTED_REQUESTED_MODEL,
        "wire_api": "responses",
        "require_live_env": True,
        "timeout_seconds": 30.0,
        "max_retries": 2,
        "retry_backoff_seconds": 1.0,
        "fail_closed_action": "raise",
        "prompt_version": SEGMENTED_PROMPT_VERSION,
        "reasoning_effort": "low",
        "max_output_tokens": 256,
        "adapter": "openai_compatible",
    }
    for key, value in expected.items():
        if contract.get(key) != value:
            raise ValueError(f"v1 Primary provider contract {key} is crossed")
    FullPoolFormalRequestContract.model_validate(
        _mapping(contract.get("request_contract"), "v1 P0 request contract")
    )
    transport = _mapping(contract.get("external_transport"), "v1 Pi transport")
    if (
        transport.get("provider_transport") != PI_SUBSCRIPTION_PROVIDER
        or transport.get("adapter_identity") != PI_SUBSCRIPTION_ADAPTER_IDENTITY
    ):
        raise ValueError("v1 Pi transport identity is crossed")


def _attempt_ledger_state(records: Sequence[Mapping[str, object]]) -> dict[str, object]:
    pending: str | None = None
    pending_physical = 0
    terminals: list[str] = []
    physical = 0
    for record in records:
        payload = _mapping(record.get("payload"), "attempt ledger payload")
        event_type = record.get("event_type")
        if event_type == "judgment_reserved":
            if pending is not None:
                raise ValueError("attempt ledger contains overlapping reservations")
            pending = _non_empty(payload.get("pair_id"), "reserved pair_id")
            pending_physical = 0
        elif event_type == "physical_attempt_accounted":
            if _non_empty(payload.get("pair_id"), "attempt pair_id") != pending:
                raise ValueError("attempt ledger physical event is crossed")
            pending_physical += 1
        elif event_type == "judgment_terminal":
            pair_id = _non_empty(payload.get("pair_id"), "terminal pair_id")
            accounting = _mapping(payload.get("accounting"), "terminal accounting")
            requests = _strict_int(accounting.get("request_invocations"), "request invocations")
            if pair_id != pending or requests != pending_physical or pair_id in terminals:
                raise ValueError("attempt ledger terminal is crossed")
            terminals.append(pair_id)
            physical += requests
            pending = None
            pending_physical = 0
        elif event_type == "reservation_released":
            if _non_empty(payload.get("pair_id"), "released pair_id") != pending:
                raise ValueError("attempt ledger release is crossed")
            pending = None
            pending_physical = 0
        elif event_type != "cap_stop":
            raise ValueError("unsupported attempt ledger event")
    return {
        "pending_pair_id": pending,
        "pending_physical_count": pending_physical,
        "terminal_pair_ids": terminals,
        "logical_count": len(terminals),
        "physical_attempt_count": physical,
    }


def _allowlisted_accounting(evidence: Mapping[str, object]) -> dict[str, object]:
    fields = (
        "request_invocations",
        "provider_response_count",
        "successful_decision_count",
        "observed_model_counts",
        "observed_model_missing_response_count",
        "observed_model_malformed_response_count",
        "usage_complete",
        "usage_complete_response_count",
        "usage_missing_response_count",
        "usage_malformed_response_count",
        "input_usage",
        "output_usage",
        "total_usage",
        "cached_input_usage",
    )
    if any(field not in evidence for field in fields):
        raise ValueError("runtime durable variant evidence lacks attempt-accounting fields")
    return {field: evidence[field] for field in fields}


def _append_checksum_record(path: Path, records: list[dict[str, object]], body: dict[str, object]) -> str:
    checksum = _sha256_json(body)
    record = {**body, "checksum": checksum}
    with path.open("ab") as handle:
        handle.write(_json_bytes(record))
        handle.flush()
        os.fsync(handle.fileno())
    records.append(record)
    return checksum


def _request_fields(plan: Mapping[str, object]) -> dict[str, object]:
    fields = CutoverPlanRequest.model_fields
    return {key: plan[key] for key in fields}


def _confirmation_token(request: CutoverPlanRequest, plan_payload_hash: str) -> str:
    return (
        f"CUTOVER-ISSUE-205-{request.expected_pid}-{request.expected_v1_run_identity_hash[:12]}-"
        f"{request.continuation_id}-{plan_payload_hash[:12]}"
    )


def _inventory_mapping(value: object) -> dict[str, dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError("artifact inventory must be a sequence")
    result: dict[str, dict[str, object]] = {}
    for raw in value:
        row = dict(_mapping(raw, "artifact inventory row"))
        relative = _non_empty(row.get("relative_path"), "artifact relative path")
        if relative in result:
            raise ValueError("artifact inventory contains duplicate paths")
        result[relative] = row
    return result


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _sha256_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON artifact is not an object: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"JSONL record is not an object: {path}")
            records.append(value)
    return records


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return dict(value)


def _strict_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _non_empty(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _string_list(value: object, label: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{label} must be a sequence")
    result = list(value)
    if any(not isinstance(item, str) or not item for item in result):
        raise ValueError(f"{label} must contain non-empty strings")
    return cast(list[str], result)
