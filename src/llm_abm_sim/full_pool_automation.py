from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .decision import LLMDecisionAdapter
from .full_pool_formal_experiment import FULL_POOL_FORMAL_ADAPTER_IDENTITY
from .full_pool_segmented_automated_recovery import (
    AUTOMATED_RECOVERY_POLICY_FILE,
    AUTOMATED_RECOVERY_STATUS_FILE,
    AutomatedNestedRecoveryRequest,
    AutomatedNestedRecoveryResult,
    FullPoolSegmentedAutomatedRecovery,
    _validated_automated_inputs,
)

AUTOMATION_EXECUTION_MANIFEST_SCHEMA = (
    "full-pool-automated-recovery-execution-manifest-v1"
)
AUTOMATION_EXECUTION_MANIFEST_ENVELOPE_SCHEMA = (
    "full-pool-automated-recovery-execution-manifest-envelope-v1"
)
AUTOMATION_EXECUTION_RECEIPT_FILE = "automation_execution_receipt.json"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{7,40}$")
_RECOVERY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_MODULE_PATHS = (
    "src/llm_abm_sim/durable_pair_settlement.py",
    "src/llm_abm_sim/full_pool_segmented_automated_recovery.py",
    "src/llm_abm_sim/full_pool_source_v3.py",
    "src/llm_abm_sim/full_pool_automation.py",
    "src/llm_abm_sim/full_pool_presentation.py",
    "src/llm_abm_sim/concurrent_robustness_report.py",
    "src/llm_abm_sim/concurrent_robustness_evidence.py",
    "src/llm_abm_sim/concurrent_robustness_release.py",
)
_STOP_CONDITIONS = (
    "second_provenance_unknown",
    "reconciliation_dispatch_without_settlement",
    "policy_drift",
    "workspace_identity_mismatch",
    "physical_cap_insufficient",
    "implementation_failed",
)
_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "lifecycle",
        "manifest_identity",
        "implementation",
        "nested_recovery_plan",
        "ordered_retry_mappings",
        "provider_contract",
        "execution_topology",
        "accounting_caps",
        "billing_contract",
        "output_paths",
        "stop_conditions",
        "live_gates",
        "provider_calls_during_composition",
        "production_deploy_eligible",
    }
)


@dataclass(frozen=True)
class AutomationExecutionManifestRequest:
    repo_root: Path
    nested_recovery_plan_path: Path
    nested_recovery_plan_sha256: str
    recovery_id: str
    recovery_workspace: Path
    manifest_path: Path
    implementation_commit: str


@dataclass(frozen=True)
class AutomationExecutionManifestFacts:
    manifest_path: Path
    manifest_sha256: str
    manifest_identity_sha256: str
    repo_root: Path
    implementation_commit: str
    nested_recovery_plan_path: Path
    nested_recovery_plan_sha256: str
    recovery_id: str
    recovery_workspace: Path
    ordered_retry_pair_ids: tuple[str, ...]
    provider_transport: str
    requested_model: str
    prompt_variant_id: str
    wire_api: str
    reasoning_effort: str
    max_output_tokens: int
    timeout_seconds: float
    max_retries: int
    configured_max_concurrency: int
    logical_cap: int
    physical_cap: int
    subscription_billed_cost_usd: float
    provider_calls_during_composition: int
    production_deploy_eligible: bool
    payload: Mapping[str, object]


@dataclass(frozen=True)
class AutomationLiveGates:
    explicit_live_authorization: bool
    external_requests_allowed: bool
    credentials_available: bool
    provider_transport: str
    requested_model: str
    subscription_billed_cost_usd: float


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _json_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"automation artifact is missing or unsafe: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mapping(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be an object")
    return {str(key): item for key, item in value.items()}


def _rows(value: object, context: str) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{context} must be an array")
    return [_mapping(row, context) for row in value]


def _non_empty(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be a non-empty string")
    return value


def _int(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{context} must be a non-negative integer")
    return value


def _float(value: object, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"{context} must be a non-negative number")
    return float(value)


def _real_directory(path: Path, context: str) -> Path:
    if ".." in path.parts or path.is_symlink():
        raise ValueError(f"{context} is unsafe")
    absolute = Path(os.path.abspath(path))
    resolved = path.resolve(strict=True)
    if absolute != resolved or not resolved.is_dir():
        raise ValueError(f"{context} must be one explicit real directory")
    return resolved


def _head(repo_root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("automation manifest cannot resolve the repository commit") from exc


def _module_refs(repo_root: Path) -> list[dict[str, object]]:
    refs: list[dict[str, object]] = []
    for relative in _MODULE_PATHS:
        path = repo_root / relative
        refs.append(
            {
                "relative_path": relative,
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    return refs


def _git_module_refs(repo_root: Path, commit: str) -> list[dict[str, object]]:
    refs: list[dict[str, object]] = []
    for relative in _MODULE_PATHS:
        try:
            payload = subprocess.run(
                ["git", "-C", str(repo_root), "show", f"{commit}:{relative}"],
                check=True,
                capture_output=True,
            ).stdout
        except (OSError, subprocess.CalledProcessError) as exc:
            raise ValueError(
                "automation manifest implementation commit lacks a bound Module blob"
            ) from exc
        refs.append(
            {
                "relative_path": relative,
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    return refs


def _validated_implementation(
    repo_root: Path,
    implementation: Mapping[str, object],
    *,
    require_current: bool,
) -> dict[str, object]:
    if set(implementation) != {
        "repository_commit",
        "modules",
        "module_set_identity_sha256",
    }:
        raise ValueError("automation manifest implementation fields are not exact")
    commit = _non_empty(
        implementation.get("repository_commit"), "manifest implementation commit"
    )
    if _COMMIT.fullmatch(commit) is None:
        raise ValueError("automation manifest implementation commit is invalid")
    rows = _rows(implementation.get("modules"), "manifest implementation modules")
    if any(set(row) != {"relative_path", "bytes", "sha256"} for row in rows):
        raise ValueError("automation manifest Module reference fields are not exact")
    expected = _module_refs(repo_root) if require_current else _git_module_refs(repo_root, commit)
    if (
        rows != expected
        or implementation.get("module_set_identity_sha256") != _json_sha256(rows)
        or (require_current and _head(repo_root) != commit)
    ):
        raise ValueError("automation manifest implementation commit or Module hashes drifted")
    return dict(implementation)


def _request_paths(
    request: AutomationExecutionManifestRequest,
    *,
    require_new_workspace: bool,
) -> tuple[Path, Path, Path]:
    repo_root = _real_directory(Path(request.repo_root).expanduser(), "repository root")
    plan_path = Path(request.nested_recovery_plan_path).expanduser().absolute()
    workspace = Path(request.recovery_workspace).expanduser().absolute()
    manifest_path = Path(request.manifest_path).expanduser().absolute()
    if (
        plan_path.is_symlink()
        or not plan_path.is_file()
        or workspace == plan_path.parent
        or workspace.is_relative_to(plan_path.parent)
        or plan_path.parent.is_relative_to(workspace)
        or manifest_path == plan_path
        or manifest_path == workspace
        or manifest_path.is_relative_to(workspace)
        or workspace.is_relative_to(manifest_path)
    ):
        raise ValueError("automation manifest input and output paths overlap or are unsafe")
    if require_new_workspace and (workspace.exists() or workspace.is_symlink()):
        raise ValueError("automation recovery workspace must not exist before manifest creation")
    if not require_new_workspace and workspace.is_symlink():
        raise ValueError("automation recovery workspace is unsafe")
    return repo_root, plan_path, manifest_path


def _compose_payload(
    request: AutomationExecutionManifestRequest,
    *,
    require_new_workspace: bool,
    persisted_implementation: Mapping[str, object] | None = None,
) -> dict[str, object]:
    repo_root, plan_path, manifest_path = _request_paths(
        request,
        require_new_workspace=require_new_workspace,
    )
    workspace = Path(request.recovery_workspace).expanduser().absolute()
    if _SHA256.fullmatch(request.nested_recovery_plan_sha256) is None or _sha256_file(
        plan_path
    ) != request.nested_recovery_plan_sha256:
        raise ValueError("automation manifest nested recovery plan hash is crossed")
    if _RECOVERY_ID.fullmatch(request.recovery_id) is None:
        raise ValueError("automation manifest recovery id is invalid")
    if _COMMIT.fullmatch(request.implementation_commit) is None:
        raise ValueError("automation manifest implementation commit is invalid")
    if persisted_implementation is None and _head(repo_root) != request.implementation_commit:
        raise ValueError("automation manifest implementation commit differs from HEAD")

    automated_request = AutomatedNestedRecoveryRequest(
        nested_recovery_plan_path=plan_path,
        nested_recovery_plan_sha256=request.nested_recovery_plan_sha256,
        recovery_id=request.recovery_id,
        recovery_workspace=workspace,
    )
    inputs = _validated_automated_inputs(automated_request)
    plan_payload = inputs.payload
    execution = _mapping(plan_payload.get("execution_contract"), "nested execution contract")
    accounting = _mapping(plan_payload.get("accounting"), "nested accounting")
    snapshot = _mapping(plan_payload.get("recovery_snapshot"), "nested recovery snapshot")
    unresolved = _rows(snapshot.get("unresolved_pairs"), "nested unresolved pairs")
    retry_mappings = [
        {
            "ordinal": index,
            "pair_id": _non_empty(row.get("pair_id"), "retry pair_id"),
            "terminal_row_id": _non_empty(
                row.get("terminal_row_id"), "retry terminal_row_id"
            ),
            "canonical_schedule_position": _int(
                row.get("canonical_schedule_position"), "retry schedule position"
            ),
            "classification": _non_empty(
                row.get("classification"), "retry classification"
            ),
            "logical_retry_charge": _int(
                row.get("logical_retry_charge"), "retry logical charge"
            ),
            "uncertainty_physical_charge": _int(
                row.get("uncertainty_physical_charge"), "retry uncertainty charge"
            ),
        }
        for index, row in enumerate(unresolved)
    ]
    if len(retry_mappings) != 7 or [row["ordinal"] for row in retry_mappings] != list(
        range(7)
    ):
        raise ValueError("automation manifest requires the exact seven ordered retry mappings")
    if persisted_implementation is None:
        implementation = {
            "repository_commit": request.implementation_commit,
            "modules": _module_refs(repo_root),
        }
        implementation["module_set_identity_sha256"] = _json_sha256(
            implementation["modules"]
        )
    else:
        implementation = _validated_implementation(
            repo_root,
            persisted_implementation,
            require_current=False,
        )
        if implementation.get("repository_commit") != request.implementation_commit:
            raise ValueError("automation manifest persisted implementation is crossed")
    plan_ref = {
        "path": str(plan_path),
        "bytes": plan_path.stat().st_size,
        "sha256": request.nested_recovery_plan_sha256,
        "identity_hash": _mapping(
            plan_payload.get("recovery_identity"), "nested recovery identity"
        ).get("identity_hash"),
        "stopped_workspace_inventory_sha256": _mapping(
            plan_payload.get("recovery_identity"), "nested recovery identity"
        ).get("stopped_workspace_inventory_sha256"),
    }
    provider_contract = {
        "provider": "Pi",
        "provider_transport": execution.get("provider_transport"),
        "adapter_identity": FULL_POOL_FORMAL_ADAPTER_IDENTITY,
        "requested_model": execution.get("requested_model"),
        "required_observed_model": execution.get("required_observed_model"),
        "prompt_variant_id": "P0",
        "prompt_version": execution.get("prompt_version"),
        "prompt_contract_sha256": execution.get("prompt_contract_sha256"),
        "provider_contract_sha256": execution.get("provider_contract_sha256"),
        "wire_api": execution.get("wire_api"),
        "reasoning_effort": execution.get("reasoning_effort"),
        "max_output_tokens": execution.get("max_output_tokens"),
        "timeout_seconds": execution.get("timeout_seconds"),
        "max_retries": execution.get("max_retries"),
        "maximum_attempts_per_dispatch": execution.get(
            "maximum_attempts_per_dispatch"
        ),
        "omitted_parameters": execution.get("omitted_parameters"),
        "fresh_no_cache": execution.get("fresh_no_cache"),
    }
    expected_provider = {
        "provider": "Pi",
        "provider_transport": "openai-codex",
        "adapter_identity": FULL_POOL_FORMAL_ADAPTER_IDENTITY,
        "requested_model": "gpt-5.6-sol",
        "required_observed_model": "gpt-5.6-sol",
        "prompt_variant_id": "P0",
        "wire_api": "responses",
        "reasoning_effort": "low",
        "max_output_tokens": 256,
        "timeout_seconds": 30.0,
        "max_retries": 2,
        "maximum_attempts_per_dispatch": 3,
        "omitted_parameters": ["temperature", "top_p", "seed"],
        "fresh_no_cache": True,
    }
    if any(provider_contract.get(key) != value for key, value in expected_provider.items()):
        raise ValueError("automation manifest Provider/model/request contract is crossed")
    payload_without_identity: dict[str, object] = {
        "schema_version": AUTOMATION_EXECUTION_MANIFEST_SCHEMA,
        "lifecycle": "ready_for_exact_operator",
        "implementation": implementation,
        "nested_recovery_plan": plan_ref,
        "ordered_retry_mappings": retry_mappings,
        "provider_contract": provider_contract,
        "execution_topology": {
            "configured_max_concurrency": execution.get("configured_max_concurrency"),
            "isolated_adapter_per_lane": True,
            "latest_directory_scan_allowed": False,
            "single_reconciliation_slot_per_pair": True,
        },
        "accounting_caps": {
            "logical_cap": accounting.get("logical_cap"),
            "physical_cap": accounting.get("physical_cap"),
            "historical_logical_count": accounting.get("historical_logical_count"),
            "historical_physical_attempts": accounting.get(
                "historical_physical_attempts"
            ),
            "historical_uncertainty_physical_charge": accounting.get(
                "unresolved_uncertainty_physical_charge"
            ),
            "logical_retry_charge": accounting.get("logical_retry_charge"),
            "full_retry_window_reserved_before_dispatch": True,
        },
        "billing_contract": {
            "subscription_billed_cost_usd": 0.0,
            "fee_ceiling_usd": 0.0,
            "billing_mode": "Pi subscription",
        },
        "output_paths": {
            "repo_root": str(repo_root),
            "manifest_path": str(manifest_path),
            "recovery_id": request.recovery_id,
            "recovery_workspace": str(workspace),
            "source_v3": str(workspace / "source-v3"),
            "terminal_status": str(workspace / AUTOMATED_RECOVERY_STATUS_FILE),
            "automated_policy": str(workspace / AUTOMATED_RECOVERY_POLICY_FILE),
            "execution_receipt": str(
                manifest_path.with_name(
                    f"{manifest_path.name}.{AUTOMATION_EXECUTION_RECEIPT_FILE}"
                )
            ),
        },
        "stop_conditions": list(_STOP_CONDITIONS),
        "live_gates": {
            "explicit_live_authorization_required": True,
            "external_requests_allowed_required": True,
            "credentials_available_required": True,
            "workspace_identity_exact_required": True,
            "provider_contract_exact_required": True,
            "caps_exact_required": True,
        },
        "provider_calls_during_composition": 0,
        "production_deploy_eligible": False,
    }
    identity = _json_sha256(payload_without_identity)
    return {
        **payload_without_identity,
        "manifest_identity": {
            "schema_version": "full-pool-automation-execution-identity-v1",
            "sha256": identity,
        },
    }


def _exclusive_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise ValueError("automation manifest parent must be one real directory")
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise FileExistsError("automation execution manifest is create once") from exc


def create_automation_execution_manifest(
    request: AutomationExecutionManifestRequest,
) -> Path:
    """Create one zero-call manifest bound to exact implementation and artifacts."""
    payload = _compose_payload(request, require_new_workspace=True)
    envelope = {
        "schema_version": AUTOMATION_EXECUTION_MANIFEST_ENVELOPE_SCHEMA,
        "payload": payload,
        "payload_sha256": _json_sha256(payload),
    }
    target = Path(request.manifest_path).expanduser().absolute()
    _exclusive_write(target, (_canonical_json(envelope) + "\n").encode("utf-8"))
    validate_automation_execution_manifest(target)
    return target


def _request_from_payload(
    manifest_path: Path,
    payload: Mapping[str, object],
) -> AutomationExecutionManifestRequest:
    implementation = _mapping(payload.get("implementation"), "manifest implementation")
    plan = _mapping(payload.get("nested_recovery_plan"), "manifest nested plan")
    outputs = _mapping(payload.get("output_paths"), "manifest output paths")
    if outputs.get("manifest_path") != str(manifest_path):
        raise ValueError("automation manifest path is crossed")
    return AutomationExecutionManifestRequest(
        repo_root=Path(_non_empty(outputs.get("repo_root"), "manifest repo root")),
        nested_recovery_plan_path=Path(
            _non_empty(plan.get("path"), "manifest nested plan path")
        ),
        nested_recovery_plan_sha256=_non_empty(
            plan.get("sha256"), "manifest nested plan hash"
        ),
        recovery_id=_non_empty(outputs.get("recovery_id"), "manifest recovery id"),
        recovery_workspace=Path(
            _non_empty(outputs.get("recovery_workspace"), "manifest recovery workspace")
        ),
        manifest_path=manifest_path,
        implementation_commit=_non_empty(
            implementation.get("repository_commit"), "manifest implementation commit"
        ),
    )


def validate_automation_execution_manifest(
    manifest_path: str | Path,
) -> AutomationExecutionManifestFacts:
    path = Path(manifest_path).expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise ValueError("automation execution manifest must be one regular file")
    try:
        document = _mapping(
            json.loads(path.read_text(encoding="utf-8")), "automation manifest envelope"
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("automation execution manifest is malformed") from exc
    if set(document) != {"schema_version", "payload", "payload_sha256"} or document.get(
        "schema_version"
    ) != AUTOMATION_EXECUTION_MANIFEST_ENVELOPE_SCHEMA:
        raise ValueError("automation execution manifest envelope is not exact")
    payload = _mapping(document.get("payload"), "automation manifest payload")
    if (
        set(payload) != _MANIFEST_FIELDS
        or payload.get("schema_version") != AUTOMATION_EXECUTION_MANIFEST_SCHEMA
        or payload.get("lifecycle") != "ready_for_exact_operator"
        or payload.get("provider_calls_during_composition") != 0
        or payload.get("production_deploy_eligible") is not False
        or document.get("payload_sha256") != _json_sha256(payload)
    ):
        raise ValueError("automation execution manifest fields, hash, or lifecycle are crossed")
    request = _request_from_payload(path, payload)
    implementation = _mapping(payload.get("implementation"), "manifest implementation")
    try:
        _validated_implementation(
            request.repo_root,
            implementation,
            require_current=True,
        )
        persisted_implementation: Mapping[str, object] | None = None
    except ValueError:
        _validated_implementation(
            request.repo_root,
            implementation,
            require_current=False,
        )
        persisted_implementation = implementation
    expected = _compose_payload(
        request,
        require_new_workspace=False,
        persisted_implementation=persisted_implementation,
    )
    if payload != expected:
        raise ValueError("automation execution manifest drifted from exact persisted inputs")
    manifest_identity = _mapping(payload.get("manifest_identity"), "manifest identity")
    identity_body = {key: value for key, value in payload.items() if key != "manifest_identity"}
    if manifest_identity != {
        "schema_version": "full-pool-automation-execution-identity-v1",
        "sha256": _json_sha256(identity_body),
    }:
        raise ValueError("automation execution manifest identity is crossed")
    provider = _mapping(payload.get("provider_contract"), "manifest Provider contract")
    topology = _mapping(payload.get("execution_topology"), "manifest topology")
    caps = _mapping(payload.get("accounting_caps"), "manifest caps")
    billing = _mapping(payload.get("billing_contract"), "manifest billing")
    retry_mappings = _rows(payload.get("ordered_retry_mappings"), "manifest retry mappings")
    return AutomationExecutionManifestFacts(
        manifest_path=path,
        manifest_sha256=_sha256_file(path),
        manifest_identity_sha256=_non_empty(
            manifest_identity.get("sha256"), "manifest identity hash"
        ),
        repo_root=Path(
            _non_empty(
                _mapping(payload.get("output_paths"), "manifest outputs").get(
                    "repo_root"
                ),
                "manifest repo root",
            )
        ),
        implementation_commit=request.implementation_commit,
        nested_recovery_plan_path=request.nested_recovery_plan_path,
        nested_recovery_plan_sha256=request.nested_recovery_plan_sha256,
        recovery_id=request.recovery_id,
        recovery_workspace=request.recovery_workspace,
        ordered_retry_pair_ids=tuple(
            _non_empty(row.get("pair_id"), "manifest retry pair_id")
            for row in retry_mappings
        ),
        provider_transport=_non_empty(
            provider.get("provider_transport"), "manifest provider transport"
        ),
        requested_model=_non_empty(provider.get("requested_model"), "manifest model"),
        prompt_variant_id=_non_empty(
            provider.get("prompt_variant_id"), "manifest prompt variant"
        ),
        wire_api=_non_empty(provider.get("wire_api"), "manifest wire API"),
        reasoning_effort=_non_empty(
            provider.get("reasoning_effort"), "manifest reasoning effort"
        ),
        max_output_tokens=_int(
            provider.get("max_output_tokens"), "manifest max output tokens"
        ),
        timeout_seconds=_float(
            provider.get("timeout_seconds"), "manifest timeout seconds"
        ),
        max_retries=_int(provider.get("max_retries"), "manifest max retries"),
        configured_max_concurrency=_int(
            topology.get("configured_max_concurrency"), "manifest concurrency"
        ),
        logical_cap=_int(caps.get("logical_cap"), "manifest logical cap"),
        physical_cap=_int(caps.get("physical_cap"), "manifest physical cap"),
        subscription_billed_cost_usd=_float(
            billing.get("subscription_billed_cost_usd"), "manifest billed cost"
        ),
        provider_calls_during_composition=0,
        production_deploy_eligible=False,
        payload=payload,
    )


class FullPoolAutomationOperator:
    """Consume only one exact manifest; never discover plans or workspaces by recency."""

    def preflight(
        self,
        manifest_path: str | Path,
        *,
        gates: AutomationLiveGates,
    ) -> AutomationExecutionManifestFacts:
        facts = validate_automation_execution_manifest(manifest_path)
        _validated_implementation(
            facts.repo_root,
            _mapping(facts.payload.get("implementation"), "manifest implementation"),
            require_current=True,
        )
        if (
            gates.explicit_live_authorization is not True
            or gates.external_requests_allowed is not True
            or gates.credentials_available is not True
            or gates.provider_transport != facts.provider_transport
            or gates.requested_model != facts.requested_model
            or gates.subscription_billed_cost_usd != facts.subscription_billed_cost_usd
        ):
            raise ValueError("automation operator live gates do not exactly match the manifest")
        outputs = _mapping(facts.payload.get("output_paths"), "manifest outputs")
        receipt = Path(
            _non_empty(outputs.get("execution_receipt"), "manifest execution receipt")
        )
        if receipt.exists() or receipt.is_symlink():
            raise ValueError("automation execution manifest was already consumed")
        return facts

    @staticmethod
    def _validate_adapter(
        adapter: LLMDecisionAdapter,
        *,
        facts: AutomationExecutionManifestFacts,
    ) -> None:
        metadata = getattr(adapter, "safe_metadata", None)
        if not isinstance(metadata, Mapping):
            raise ValueError("automation Adapter contract metadata is missing")
        transport = metadata.get("provider_transport", metadata.get("provider"))
        model = metadata.get("requested_model", metadata.get("model"))
        adapter_identity = metadata.get("adapter_identity", metadata.get("adapter"))
        prompt_version = metadata.get("prompt_version", getattr(adapter, "prompt_version", None))
        provider = _mapping(facts.payload.get("provider_contract"), "manifest Provider")
        if (
            transport != facts.provider_transport
            or model not in {None, facts.requested_model}
            or adapter_identity != provider.get("adapter_identity")
            or prompt_version != provider.get("prompt_version")
        ):
            raise ValueError("automation Adapter contract differs from the execution manifest")

    def run(
        self,
        manifest_path: str | Path,
        *,
        gates: AutomationLiveGates,
        adapter_factory: Callable[[int], LLMDecisionAdapter],
    ) -> AutomatedNestedRecoveryResult:
        facts = self.preflight(manifest_path, gates=gates)
        adapters: list[LLMDecisionAdapter] = []
        for lane_id in range(facts.configured_max_concurrency):
            adapter = adapter_factory(lane_id)
            self._validate_adapter(adapter, facts=facts)
            adapters.append(adapter)
        outputs = _mapping(facts.payload.get("output_paths"), "manifest outputs")
        receipt = Path(
            _non_empty(outputs.get("execution_receipt"), "manifest execution receipt")
        )
        receipt_payload = {
            "schema_version": "full-pool-automation-execution-receipt-v1",
            "manifest_path": str(facts.manifest_path),
            "manifest_sha256": facts.manifest_sha256,
            "manifest_identity_sha256": facts.manifest_identity_sha256,
            "implementation_commit": facts.implementation_commit,
            "provider_calls_before_dispatch": 0,
            "production_deploy_eligible": False,
        }
        try:
            with receipt.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(_canonical_json(receipt_payload) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError as exc:
            raise ValueError("automation execution manifest was already consumed") from exc
        request = AutomatedNestedRecoveryRequest(
            nested_recovery_plan_path=facts.nested_recovery_plan_path,
            nested_recovery_plan_sha256=facts.nested_recovery_plan_sha256,
            recovery_id=facts.recovery_id,
            recovery_workspace=facts.recovery_workspace,
        )
        adapter_by_lane = tuple(adapters)
        return FullPoolSegmentedAutomatedRecovery().run(
            request,
            adapter_factory=lambda lane_id: adapter_by_lane[lane_id],
        )
