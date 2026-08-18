from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from llm_abm_sim.full_pool_automation import (
    AUTOMATION_EXECUTION_RECEIPT_FILE,
    AutomationExecutionManifestRequest,
    AutomationLiveGates,
    FullPoolAutomationOperator,
    create_automation_execution_manifest,
    validate_automation_execution_manifest,
)
from llm_abm_sim.full_pool_formal_experiment import FULL_POOL_FORMAL_ADAPTER_IDENTITY
from llm_abm_sim.prompt_field_summary import CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION
from tests.integration.test_full_pool_segmented_automated_recovery import (
    _automated_request,
    _LaneAdapter,
)


class _ContractShapedValidationAdapter(_LaneAdapter):
    prompt_version = CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION
    safe_metadata = {
        "provider_transport": "openai-codex",
        "adapter_identity": FULL_POOL_FORMAL_ADAPTER_IDENTITY,
        "requested_model": "gpt-5.6-sol",
        "prompt_version": CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
    }


def _head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()


def _manifest_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> AutomationExecutionManifestRequest:
    nested = _automated_request(tmp_path, monkeypatch, logical_cap=90)
    return AutomationExecutionManifestRequest(
        repo_root=Path.cwd(),
        nested_recovery_plan_path=nested.nested_recovery_plan_path,
        nested_recovery_plan_sha256=nested.nested_recovery_plan_sha256,
        recovery_id="manifest-bound-offline-recovery-v3",
        recovery_workspace=tmp_path / "manifest-bound-recovery",
        manifest_path=tmp_path / "automation" / "execution-manifest.json",
        implementation_commit=_head(),
    )


def test_execution_manifest_is_create_once_and_recloses_exact_plan_contract_and_modules(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _manifest_request(tmp_path, monkeypatch)

    created = create_automation_execution_manifest(request)
    facts = validate_automation_execution_manifest(created)

    assert created == request.manifest_path
    assert facts.implementation_commit == _head()
    assert facts.nested_recovery_plan_sha256 == request.nested_recovery_plan_sha256
    assert len(facts.ordered_retry_pair_ids) == 7
    assert facts.provider_transport == "openai-codex"
    assert facts.requested_model == "gpt-5.6-sol"
    assert facts.prompt_variant_id == "P0"
    assert facts.wire_api == "responses"
    assert facts.reasoning_effort == "low"
    assert facts.max_output_tokens == 256
    assert facts.timeout_seconds == 30.0
    assert facts.max_retries == 2
    assert facts.configured_max_concurrency == 10
    assert facts.logical_cap == 90
    assert facts.physical_cap == 120_120
    assert facts.subscription_billed_cost_usd == 0.0
    assert facts.provider_calls_during_composition == 0
    assert facts.production_deploy_eligible is False

    with pytest.raises(FileExistsError, match="create once"):
        create_automation_execution_manifest(request)


def test_manifest_model_or_module_drift_is_rejected_without_adapter_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _manifest_request(tmp_path, monkeypatch)
    manifest_path = create_automation_execution_manifest(request)
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["payload"]["provider_contract"]["requested_model"] = "drifted-model"
    document["payload_sha256"] = hashlib.sha256(
        json.dumps(
            document["payload"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    manifest_path.write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    factory_calls: list[int] = []

    with pytest.raises(ValueError, match="manifest|Provider|model|drift"):
        FullPoolAutomationOperator().run(
            manifest_path,
            gates=AutomationLiveGates(
                explicit_live_authorization=True,
                external_requests_allowed=True,
                credentials_available=True,
                provider_transport="openai-codex",
                requested_model="gpt-5.6-sol",
                subscription_billed_cost_usd=0.0,
            ),
            adapter_factory=lambda lane_id: factory_calls.append(lane_id),  # type: ignore[arg-type,return-value]
        )

    assert factory_calls == []


def test_missing_live_gate_and_adapter_contract_mismatch_never_make_provider_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _manifest_request(tmp_path, monkeypatch)
    manifest_path = create_automation_execution_manifest(request)
    factory_calls: list[int] = []

    with pytest.raises(ValueError, match="live gates"):
        FullPoolAutomationOperator().run(
            manifest_path,
            gates=AutomationLiveGates(
                explicit_live_authorization=False,
                external_requests_allowed=False,
                credentials_available=False,
                provider_transport="openai-codex",
                requested_model="gpt-5.6-sol",
                subscription_billed_cost_usd=0.0,
            ),
            adapter_factory=lambda lane_id: factory_calls.append(lane_id),  # type: ignore[arg-type,return-value]
        )
    assert factory_calls == []

    adapter_calls: list[str] = []
    with pytest.raises(ValueError, match="Adapter.*contract"):
        FullPoolAutomationOperator().run(
            manifest_path,
            gates=AutomationLiveGates(
                explicit_live_authorization=True,
                external_requests_allowed=True,
                credentials_available=True,
                provider_transport="openai-codex",
                requested_model="gpt-5.6-sol",
                subscription_billed_cost_usd=0.0,
            ),
            adapter_factory=lambda lane_id: (
                factory_calls.append(lane_id) or _LaneAdapter(adapter_calls)
            ),
        )
    assert factory_calls == [0]
    assert adapter_calls == []
    assert not request.recovery_workspace.exists()


def test_exact_manifest_can_drive_only_a_non_deployable_validation_source_without_provider_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _manifest_request(tmp_path, monkeypatch)
    manifest_path = create_automation_execution_manifest(request)
    adapter_calls: list[str] = []

    result = FullPoolAutomationOperator().run(
        manifest_path,
        gates=AutomationLiveGates(
            explicit_live_authorization=True,
            external_requests_allowed=True,
            credentials_available=True,
            provider_transport="openai-codex",
            requested_model="gpt-5.6-sol",
            subscription_billed_cost_usd=0.0,
        ),
        adapter_factory=lambda _lane_id: _ContractShapedValidationAdapter(
            adapter_calls
        ),
    )

    assert result.status == "complete"
    assert result.source_root == request.recovery_workspace / "source-v3"
    assert result.provider_calls == 0
    assert result.production_deploy_eligible is False
    receipt = manifest_path.with_name(
        f"{manifest_path.name}.{AUTOMATION_EXECUTION_RECEIPT_FILE}"
    )
    assert receipt.is_file()
    with pytest.raises(ValueError, match="already consumed"):
        FullPoolAutomationOperator().preflight(
            manifest_path,
            gates=AutomationLiveGates(
                explicit_live_authorization=True,
                external_requests_allowed=True,
                credentials_available=True,
                provider_transport="openai-codex",
                requested_model="gpt-5.6-sol",
                subscription_billed_cost_usd=0.0,
            ),
        )
