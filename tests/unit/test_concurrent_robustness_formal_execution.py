from __future__ import annotations

import copy
import hashlib
import json
import stat
from collections.abc import Iterator, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn, cast

import pytest

from llm_abm_sim import concurrent_robustness_formal_execution as formal_module
from llm_abm_sim.concurrent_message_experiment import (
    CONCURRENT_MESSAGE_ENGAGED_NEIGHBOR_FORMULA,
    CONCURRENT_MESSAGE_RANKING_FORMULA,
)
from llm_abm_sim.concurrent_message_report import CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_SCHEMA
from llm_abm_sim.concurrent_robustness_formal_execution import (
    ConcurrentRobustnessFormalAuthorizationRequired,
    ConcurrentRobustnessFormalExecutionRequest,
    authorization_readiness,
    authorize_formal_execution,
    validate_embedded_formal_execution_plan,
    validate_formal_execution_plan,
)
from llm_abm_sim.concurrent_robustness_study import (
    CONCURRENT_ROBUSTNESS_COMPONENT_CONTRACT_TOKEN,
    CONCURRENT_ROBUSTNESS_DECISION_STORE_POLICY,
    CONCURRENT_ROBUSTNESS_P95_TOKEN,
    CONCURRENT_ROBUSTNESS_SCHEDULE_TOKEN,
    CONCURRENT_ROBUSTNESS_SCORE_PRECISION_TOKEN,
    CONCURRENT_ROBUSTNESS_TIE_BREAK_TOKEN,
    ConcurrentRobustnessError,
    ConcurrentRobustnessErrorCode,
    ConcurrentRobustnessStudy,
)
from llm_abm_sim.concurrent_robustness_v2 import (
    _V2_MODELS,
    _V2_REQUIRED_OBSERVED_MODELS,
    ConcurrentRobustnessManifestV2,
    _preflight_adapters,
    _realization_source_payload,
)
from llm_abm_sim.prompt_contracts import CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY
from llm_abm_sim.provider_request_contract import (
    OMITTED_SAMPLING_PARAMETERS,
    STRUCTURED_OUTPUT_SCHEMA_HASH,
)
from llm_abm_sim.providers.robustness import (
    AntigravityGeminiDecisionAdapter,
    DeepSeekV4FlashDecisionAdapter,
    PiKimiDecisionAdapter,
    PiOpenAIDecisionAdapter,
    robustness_provider_disclosures,
)

_NOW = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_canonical(path: Path, value: object) -> str:
    payload = _canonical_bytes(value)
    path.write_bytes(payload)
    return _sha256_bytes(payload)


def _manifest_payload(source: Path, *, output_identity: str) -> dict[str, object]:
    artifact_names = (
        "artifact_manifest.json",
        "concurrent_runtime_candidates.csv",
        "concurrent_runtime_steps.json",
        "message_snapshot.json",
        "sample_manifest.json",
        "seed_first_sample_audit.json",
    )
    source.mkdir()
    hashes: dict[str, str] = {}
    for name in artifact_names:
        payload = f"formal-source:{name}\n".encode()
        (source / name).write_bytes(payload)
        hashes[name] = _sha256_bytes(payload)
    cells = [
        {
            "cell_id": f"{prompt.variant_id}::{model}",
            "prompt_variant": prompt.variant_id,
            "prompt_version": prompt.prompt_version,
            "prompt_canonical_hash": prompt.canonical_hash,
            "requested_model": model,
            "required_observed_model": _V2_REQUIRED_OBSERVED_MODELS[model],
        }
        for prompt in CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.all()
        for model in _V2_MODELS
    ]
    return {
        "schema_version": "concurrent-robustness-manifest-v2",
        "source": {
            "kind": "formal",
            "source_id": source.name,
            "source_dir": str(source.resolve()),
            "manifest_schema": CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_SCHEMA,
            "manifest_sha256": hashes["artifact_manifest.json"],
            "artifacts": [
                {"relative_path": name, "sha256": hashes[name]}
                for name in sorted(hashes)
            ],
            "candidate_artifact": "concurrent_runtime_candidates.csv",
            "feedback_artifact": "concurrent_runtime_steps.json",
        },
        "sample": {
            "sample_size": 1_000,
            "sample_identity": "1" * 64,
            "sample_manifest_sha256": hashes["sample_manifest.json"],
            "sample_audit_sha256": hashes["seed_first_sample_audit.json"],
        },
        "message_ids": ["message_1", "message_2", "message_3"],
        "message_snapshot_sha256": hashes["message_snapshot.json"],
        "ranking_contract": {
            "schema_version": "concurrent-robustness-ranking-contract-v1",
            "p95_normalization_token": CONCURRENT_ROBUSTNESS_P95_TOKEN,
            "component_contract_token": CONCURRENT_ROBUSTNESS_COMPONENT_CONTRACT_TOKEN,
            "components": [
                "base_network_relevance",
                "campaign_engaged_neighbor_signal",
                "normalized_message_user_fit",
            ],
            "tie_break_token": CONCURRENT_ROBUSTNESS_TIE_BREAK_TOKEN,
            "schedule_token": CONCURRENT_ROBUSTNESS_SCHEDULE_TOKEN,
            "score_precision_token": CONCURRENT_ROBUSTNESS_SCORE_PRECISION_TOKEN,
            "ranking_formula": CONCURRENT_MESSAGE_RANKING_FORMULA,
            "feedback_formula": CONCURRENT_MESSAGE_ENGAGED_NEIGHBOR_FORMULA,
            "horizon": 30,
            "delivery_capacity": 20,
        },
        "prompt_model_cells": cells,
        "request_contract": {
            "schema_version": "provider-request-contract-v1",
            "provider": "openai_compatible",
            "wire_api": "responses",
            "reasoning_effort": "low",
            "output_token_ceiling": 256,
            "timeout_seconds": 30.0,
            "max_retries": 2,
            "retry_backoff_seconds": 1.0,
            "structured_output_schema_version": "engage-decision-output-v1",
            "structured_output_schema_hash": STRUCTURED_OUTPUT_SCHEMA_HASH,
            "omitted_parameters": list(OMITTED_SAMPLING_PARAMETERS),
            "decision_store_policy": CONCURRENT_ROBUSTNESS_DECISION_STORE_POLICY,
        },
        "request_caps": {
            "logical_judgments_per_cell": 1_800,
            "logical_judgment_cap": 36_000,
            "physical_attempt_cap": 108_000,
            "maximum_physical_attempts_per_judgment": 3,
        },
        "formal_contract": {
            "schema_version": "concurrent-robustness-formal-topology-v2",
            "model_count": 5,
            "prompt_variants": ["P0", "P1", "P2", "P3"],
            "cell_count": 20,
            "sample_size": 1_000,
            "batch_count": 30,
            "message_count": 3,
            "delivery_capacity_per_message": 20,
            "logical_judgments_per_cell": 1_800,
            "logical_judgment_cap": 36_000,
            "maximum_physical_attempts_per_judgment": 3,
            "physical_attempt_cap": 108_000,
        },
        "batch_barrier": {
            "schema_version": "concurrent-robustness-two-stage-barrier-v2",
            "required_terminal": "persisted-realized-terminal-per-selected-pair-v1",
            "feedback_source": "campaign-deduplicated-realized-positive-users-v1",
            "feedback_timing": "next-batch-only-v1",
        },
        "realization_source": _realization_source_payload(
            sample_identity="1" * 64,
            graph_identity_sha256="2" * 64,
            message_ids=("message_1", "message_2", "message_3"),
            message_snapshot_sha256=hashes["message_snapshot.json"],
        ),
        "execution_profile": "formal",
        "authorization_reference": f"formal-readiness:{output_identity}",
        "output_identity": output_identity,
    }


def _request_bundle(tmp_path: Path) -> tuple[ConcurrentRobustnessFormalExecutionRequest, dict[str, dict[str, Any]]]:
    output_identity = "jinjiang-prompt-model-v2-formal-20300101T120000Z"
    manifest_path = tmp_path / "study-manifest.json"
    manifest_payload = _manifest_payload(tmp_path / "formal-source", output_identity=output_identity)
    manifest_sha256 = _write_canonical(manifest_path, manifest_payload)
    disclosures = {str(row["requested_model"]): row for row in robustness_provider_disclosures()}
    credential_routes = {
        "deepseek-v4-flash": "runtime-injected-deepseek-credential-v1",
        "gemini-3.1-pro": "runtime-injected-antigravity-credential-v1",
        "gemini-3.8-flash-high": "runtime-injected-antigravity-credential-v1",
        "kimi-coding/k3-256k": "pi-kimi-current-user-profile-v1",
        "openai-codex/gpt-5.6-sol": "pi-openai-current-user-profile-v1",
    }
    qualification_refs: list[dict[str, object]] = []
    route_rows: list[dict[str, object]] = []
    qualification_payloads: dict[str, dict[str, object]] = {}
    for index, model in enumerate(_V2_MODELS):
        disclosure = disclosures[model]
        route_rows.append(
            {
                "requested_model": model,
                "required_observed_model": _V2_REQUIRED_OBSERVED_MODELS[model],
                "provider_route": disclosure["provider_route"],
                "credential_route": credential_routes[model],
            }
        )
        qualification = {
            "schema_version": "concurrent-robustness-formal-model-qualification-v1",
            "qualification_kind": "independent_provider_observed",
            "qualification_reference": f"qualification:{index}:{model}",
            "qualified_at_utc": "2030-01-01T11:00:00Z",
            "expires_at_utc": "2030-01-02T11:00:00Z",
            "provider_route": disclosure["provider_route"],
            "credential_route": credential_routes[model],
            "requested_model": model,
            "observed_model": _V2_REQUIRED_OBSERVED_MODELS[model],
            "status": "qualified",
            "structured_decision_valid": True,
            "usage_complete": True,
            "raw_prompt_persisted": False,
            "raw_response_persisted": False,
            "credential_material_persisted": False,
        }
        qualification_path = tmp_path / f"qualification-{index}.json"
        qualification_sha256 = _write_canonical(qualification_path, qualification)
        qualification_refs.append(
            {
                "requested_model": model,
                "path": str(qualification_path),
                "sha256": qualification_sha256,
            }
        )
        qualification_payloads[model] = qualification
    request_payload: dict[str, object] = {
        "schema_version": "concurrent-robustness-formal-execution-request-v1",
        "manifest": {"path": str(manifest_path), "sha256": manifest_sha256},
        "qualification_artifacts": qualification_refs,
        "provider_routes": route_rows,
        "run_parameters": {
            "worker_count": 1,
            "max_in_flight": 1,
            "request_timeout_seconds": 30.0,
            "retry_backoff_seconds": 1.0,
            "backoff_ceiling_seconds": 60.0,
            "maximum_physical_attempts_per_judgment": 3,
            "resume_policy": "unresolved-with-remaining-attempt-budget-only-v1",
        },
        "provider_caps": [
            {
                "provider_route": "deepseek_official",
                "requested_models": ["deepseek-v4-flash"],
                "logical_judgment_cap": 7_200,
                "physical_attempt_cap": 21_600,
                "cap_kind": "provider_fee_cny",
                "currency": "CNY",
                "fee_ceiling": 25.0,
            },
            {
                "provider_route": "antigravity_openai_compatible_gateway",
                "requested_models": ["gemini-3.1-pro", "gemini-3.8-flash-high"],
                "logical_judgment_cap": 14_400,
                "physical_attempt_cap": 43_200,
                "cap_kind": "gateway_quota",
                "currency": None,
                "fee_ceiling": None,
            },
            {
                "provider_route": "pi_kimi_oauth_subscription",
                "requested_models": ["kimi-coding/k3-256k"],
                "logical_judgment_cap": 7_200,
                "physical_attempt_cap": 21_600,
                "cap_kind": "subscription_quota",
                "currency": None,
                "fee_ceiling": None,
            },
            {
                "provider_route": "pi_openai_oauth_subscription",
                "requested_models": ["openai-codex/gpt-5.6-sol"],
                "logical_judgment_cap": 7_200,
                "physical_attempt_cap": 21_600,
                "cap_kind": "subscription_quota",
                "currency": None,
                "fee_ceiling": None,
            },
        ],
        "logical_judgment_cap": 36_000,
        "physical_attempt_cap": 108_000,
        "output_identity": output_identity,
        "output_root": str(tmp_path / "formal-output"),
    }
    return ConcurrentRobustnessFormalExecutionRequest.model_validate(request_payload), qualification_payloads


def _authorization_artifact(
    tmp_path: Path,
    request: ConcurrentRobustnessFormalExecutionRequest,
) -> tuple[Path, str, dict[str, object]]:
    readiness = authorization_readiness(request)
    authorization = dict(
        cast(Mapping[str, object], readiness["authorization_template"])
    )
    authorization.update(
        {
            "authorization_reference": "github:operational-issue-999",
            "authorized_at_utc": "2030-01-01T11:30:00Z",
            "expires_at_utc": "2030-01-02T11:30:00Z",
        }
    )
    authorization_path = tmp_path / "formal-authorization.json"
    return authorization_path, _write_canonical(authorization_path, authorization), authorization


def _replace_qualification(
    request: ConcurrentRobustnessFormalExecutionRequest,
    *,
    index: int,
    document: dict[str, object],
) -> ConcurrentRobustnessFormalExecutionRequest:
    payload = request.model_dump(mode="json")
    refs = payload["qualification_artifacts"]
    assert isinstance(refs, list)
    reference = refs[index]
    assert isinstance(reference, dict)
    path = Path(str(reference["path"]))
    reference["sha256"] = _write_canonical(path, document)
    return ConcurrentRobustnessFormalExecutionRequest.model_validate(payload)


def test_missing_authorization_returns_hash_bound_nonproduction_readiness_without_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, _qualifications = _request_bundle(tmp_path)
    plan_output = tmp_path / "formal-execution-plan.json"
    monkeypatch.setattr(formal_module, "_utc_now", lambda: _NOW)

    with pytest.raises(ConcurrentRobustnessFormalAuthorizationRequired) as captured:
        authorize_formal_execution(
            request=request,
            authorization_path=None,
            plan_output=plan_output,
        )

    readiness = captured.value.readiness
    request_identity = cast(dict[str, Any], readiness["request_identity"])
    operational_handoff = cast(dict[str, Any], readiness["operational_issue_handoff"])
    assert readiness["schema_version"] == "concurrent-robustness-formal-readiness-v1"
    assert readiness["status"] == "ready_for_human"
    assert request_identity["allowed_cell_ids"] == [
        f"{prompt.variant_id}::{model}"
        for prompt in CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.all()
        for model in _V2_MODELS
    ]
    assert request_identity["logical_judgment_cap"] == 36_000
    assert request_identity["physical_attempt_cap"] == 108_000
    assert request_identity["output_identity"] == request.output_identity
    assert request_identity["lifecycle_policy"] == {
        "resumable": "safe_pre_dispatch_or_persisted_terminal_interruption_with_remaining_budget",
        "stopped": "attempts_exhausted_or_nonretryable_failure_no_same-output-resume",
        "reconciliation_required": "unknown_dispatch_provenance_no_automatic_resend",
        "resume_policy": "unresolved-with-remaining-attempt-budget-only-v1",
    }
    assert readiness["provider_calls"] == 0
    assert readiness["live_api_triggered"] is False
    assert readiness["formal_run_authorized"] is False
    assert readiness["production_deploy_eligible"] is False
    assert operational_handoff["labels"] == ["ready-for-human"]
    assert readiness["readiness_sha256"] == _sha256_bytes(
        _canonical_bytes(
            {
                key: value
                for key, value in readiness.items()
                if key not in {"readiness_sha256", "authorization_template", "operational_issue_handoff"}
            }
        )
    )
    serialized = json.dumps(readiness, ensure_ascii=False).lower()
    assert "raw prompt" not in serialized
    assert "raw response" not in serialized
    assert "bearer " not in serialized
    assert not request.output_root.exists()
    assert not plan_output.exists()


def test_exact_authorization_closes_zero_call_execution_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, _qualifications = _request_bundle(tmp_path)
    plan_output = tmp_path / "formal-execution-plan.json"
    monkeypatch.setattr(formal_module, "_utc_now", lambda: _NOW)
    readiness = authorization_readiness(request)
    authorization_path, authorization_sha256, _authorization = _authorization_artifact(
        tmp_path, request
    )

    plan = authorize_formal_execution(
        request=request,
        authorization_path=authorization_path,
        authorization_sha256=authorization_sha256,
        plan_output=plan_output,
    )

    assert plan_output.read_bytes() == _canonical_bytes(plan)
    assert not plan_output.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
    assert plan["schema_version"] == "concurrent-robustness-formal-execution-plan-v1"
    assert plan["status"] == "authorized_for_formal_execution"
    assert plan["authorization_sha256"] == authorization_sha256
    assert plan["request_identity_sha256"] == readiness["request_identity_sha256"]
    assert plan["readiness_sha256"] == readiness["readiness_sha256"]
    assert plan["provider_calls_during_preflight"] == 0
    assert plan["live_api_triggered_during_preflight"] is False
    assert plan["release_authorized"] is False
    assert plan["deployment_authorized"] is False
    assert plan["production_deploy_eligible"] is False
    assert plan["plan_identity_sha256"] == _sha256_bytes(
        _canonical_bytes(
            {
                key: value
                for key, value in plan.items()
                if key != "plan_identity_sha256"
            }
        )
    )
    assert validate_formal_execution_plan(plan_output) == plan
    assert not request.output_root.exists()


def _rehash_embedded_plan(plan: dict[str, Any]) -> None:
    request_identity = cast(dict[str, Any], plan["request_identity"])
    request_identity_sha256 = _sha256_bytes(_canonical_bytes(request_identity))
    plan["request_identity_sha256"] = request_identity_sha256
    readiness_base = {
        "schema_version": "concurrent-robustness-formal-readiness-v1",
        "status": "ready_for_human",
        "authorization_schema_version": "concurrent-robustness-formal-authorization-v1",
        "request_identity": request_identity,
        "request_identity_sha256": request_identity_sha256,
        "provider_calls": 0,
        "live_api_triggered": False,
        "credential_read_triggered": False,
        "output_workspace_created": False,
        "formal_run_authorized": False,
        "release_authorized": False,
        "deployment_authorized": False,
        "production_deploy_eligible": False,
    }
    readiness_sha256 = _sha256_bytes(_canonical_bytes(readiness_base))
    plan["readiness_sha256"] = readiness_sha256
    authorization = cast(dict[str, Any], plan["authorization"])
    authorization["request_identity"] = request_identity
    authorization["request_identity_sha256"] = request_identity_sha256
    authorization["readiness_sha256"] = readiness_sha256
    plan["authorization_sha256"] = _sha256_bytes(_canonical_bytes(authorization))
    plan["plan_identity_sha256"] = _sha256_bytes(
        _canonical_bytes(
            {key: value for key, value in plan.items() if key != "plan_identity_sha256"}
        )
    )


def test_embedded_plan_retains_self_contained_legal_authorization_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _qualifications = _request_bundle(tmp_path)
    monkeypatch.setattr(formal_module, "_utc_now", lambda: _NOW)
    authorization_path, authorization_sha256, _authorization = _authorization_artifact(
        tmp_path, request
    )
    plan_path = tmp_path / "formal-execution-plan.json"
    plan = authorize_formal_execution(
        request=request,
        authorization_path=authorization_path,
        authorization_sha256=authorization_sha256,
        plan_output=plan_path,
    )
    manifest = ConcurrentRobustnessManifestV2.model_validate(
        json.loads(request.manifest.path.read_text(encoding="utf-8"))
    )
    authorization_path.unlink()
    request.manifest.path.unlink()
    for reference in request.qualification_artifacts:
        reference.path.unlink()

    assert validate_embedded_formal_execution_plan(
        plan,
        expected_manifest=manifest,
        expected_output_root=request.output_root,
    ) == plan

    crossed = copy.deepcopy(plan)
    identity = cast(dict[str, Any], crossed["request_identity"])
    qualification_rows = cast(list[dict[str, Any]], identity["qualification_artifacts"])
    qualification = cast(dict[str, Any], qualification_rows[0]["evidence"])
    qualification["qualification_reference"] = "github:crossed-qualification-1000"
    _rehash_embedded_plan(crossed)
    with pytest.raises(formal_module.ConcurrentRobustnessFormalPreflightError):
        validate_embedded_formal_execution_plan(
            crossed,
            expected_manifest=manifest,
            expected_output_root=request.output_root,
        )


def test_typed_request_redacts_and_rejects_secret_like_artifact_paths(
    tmp_path: Path,
) -> None:
    request, _qualifications = _request_bundle(tmp_path)
    payload = request.model_dump(mode="json")
    references = cast(list[dict[str, Any]], payload["qualification_artifacts"])
    references[0]["path"] = str(tmp_path / ".env")

    with pytest.raises(ValueError) as captured:
        ConcurrentRobustnessFormalExecutionRequest.model_validate(payload)

    assert ".env" not in str(captured.value)


@pytest.mark.parametrize(
    "corruption",
    ["crossed_identity", "expired", "secret_reference", "cap_mismatch"],
)
def test_preflight_rejects_crossed_expired_secret_or_cap_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
) -> None:
    request, qualifications = _request_bundle(tmp_path)
    monkeypatch.setattr(formal_module, "_utc_now", lambda: _NOW)
    if corruption == "cap_mismatch":
        payload = request.model_dump(mode="json")
        caps = payload["provider_caps"]
        assert isinstance(caps, list) and isinstance(caps[0], dict)
        caps[0]["fee_ceiling"] = 24.0
        request = ConcurrentRobustnessFormalExecutionRequest.model_validate(payload)
    else:
        qualification = dict(qualifications["deepseek-v4-flash"])
        if corruption == "crossed_identity":
            qualification["observed_model"] = "crossed-model"
        elif corruption == "expired":
            qualification["qualified_at_utc"] = "2029-12-30T10:00:00Z"
            qualification["expires_at_utc"] = "2029-12-31T10:00:00Z"
        else:
            qualification["qualification_reference"] = "token=do-not-persist-this"
        request = _replace_qualification(request, index=0, document=qualification)

    with pytest.raises(formal_module.ConcurrentRobustnessFormalPreflightError) as captured:
        authorization_readiness(request)

    assert "do-not-persist-this" not in str(captured.value)
    assert not request.output_root.exists()


@pytest.mark.parametrize(
    "corruption", ["hash", "noncanonical", "duplicate", "symlink", "expired", "crossed"]
)
def test_authorization_requires_hash_bound_canonical_regular_exact_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
) -> None:
    request, _qualifications = _request_bundle(tmp_path)
    monkeypatch.setattr(formal_module, "_utc_now", lambda: _NOW)
    authorization_path, authorization_sha256, authorization = _authorization_artifact(
        tmp_path, request
    )
    if corruption == "hash":
        authorization_sha256 = "0" * 64
    elif corruption == "noncanonical":
        authorization_path.write_text(
            json.dumps(authorization, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        authorization_sha256 = _sha256_bytes(authorization_path.read_bytes())
    elif corruption == "duplicate":
        canonical = _canonical_bytes(authorization).decode("utf-8")
        authorization_path.write_text(
            canonical.replace("{", '{"schema_version":"duplicate",', 1),
            encoding="utf-8",
        )
        authorization_sha256 = _sha256_bytes(authorization_path.read_bytes())
    elif corruption == "symlink":
        target = authorization_path.with_name("authorization-target.json")
        authorization_path.replace(target)
        authorization_path.symlink_to(target)
        authorization_sha256 = _sha256_bytes(target.read_bytes())
    elif corruption == "expired":
        authorization["authorized_at_utc"] = "2029-12-30T11:30:00Z"
        authorization["expires_at_utc"] = "2029-12-31T11:30:00Z"
        authorization_sha256 = _write_canonical(authorization_path, authorization)
    else:
        authorization["request_identity_sha256"] = "0" * 64
        authorization_sha256 = _write_canonical(authorization_path, authorization)
    plan_output = tmp_path / "rejected-plan.json"

    with pytest.raises(formal_module.ConcurrentRobustnessFormalPreflightError):
        authorize_formal_execution(
            request=request,
            authorization_path=authorization_path,
            authorization_sha256=authorization_sha256,
            plan_output=plan_output,
        )

    assert not plan_output.exists()
    assert not request.output_root.exists()


@pytest.mark.parametrize(
    "mutable_input", ["source", "qualification", "authorization", "plan_mode"]
)
def test_plan_revalidation_rejects_mutated_external_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutable_input: str,
) -> None:
    request, _qualifications = _request_bundle(tmp_path)
    monkeypatch.setattr(formal_module, "_utc_now", lambda: _NOW)
    authorization_path, authorization_sha256, _authorization = _authorization_artifact(
        tmp_path, request
    )
    plan_path = tmp_path / "formal-execution-plan.json"
    authorize_formal_execution(
        request=request,
        authorization_path=authorization_path,
        authorization_sha256=authorization_sha256,
        plan_output=plan_path,
    )
    if mutable_input == "source":
        source_file = tmp_path / "formal-source" / "artifact_manifest.json"
        source_file.write_bytes(source_file.read_bytes() + b" ")
    elif mutable_input == "qualification":
        request.qualification_artifacts[0].path.write_bytes(b"{}\n")
    elif mutable_input == "authorization":
        authorization_path.write_bytes(b"{}\n")
    else:
        plan_path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    with pytest.raises(formal_module.ConcurrentRobustnessFormalPreflightError):
        validate_formal_execution_plan(plan_path)

    assert not request.output_root.exists()


class _ExplodingAdapterMap(Mapping[str, object]):
    def __getitem__(self, _key: str) -> NoReturn:
        raise AssertionError("Adapter map must not be touched before Formal authorization")

    def __iter__(self) -> Iterator[str]:
        raise AssertionError("Adapter map must not be touched before Formal authorization")

    def __len__(self) -> int:
        raise AssertionError("Adapter map must not be touched before Formal authorization")


class _FreshExternalTransport:
    external_provider_client = True
    subscription_nominal_cost_usd_total = 0.0
    maximum_provider_fee_cny_per_attempt = 0.01

    def create_response(self, *_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("Formal adapter preflight must not send a Provider request")


def _formal_adapters(
    manifest: ConcurrentRobustnessManifestV2,
) -> tuple[dict[str, object], list[_FreshExternalTransport]]:
    adapters: dict[str, object] = {}
    transports: list[_FreshExternalTransport] = []
    for cell in manifest.prompt_model_cells:
        transport = _FreshExternalTransport()
        transports.append(transport)
        if cell.requested_model == "deepseek-v4-flash":
            adapter = DeepSeekV4FlashDecisionAdapter(
                prompt_version=cell.prompt_version, client=transport
            )
        elif cell.requested_model.startswith("gemini-"):
            adapter = AntigravityGeminiDecisionAdapter(
                requested_model=cell.requested_model,
                prompt_version=cell.prompt_version,
                client=transport,
            )
        elif cell.requested_model == "kimi-coding/k3-256k":
            adapter = PiKimiDecisionAdapter(
                prompt_version=cell.prompt_version, client=transport
            )
        else:
            adapter = PiOpenAIDecisionAdapter(
                prompt_version=cell.prompt_version, client=transport
            )
        adapters[cell.cell_id] = adapter
    return adapters, transports


def test_formal_adapter_preflight_accepts_only_fresh_external_profiles_without_calling_them(
    tmp_path: Path,
) -> None:
    request, _qualifications = _request_bundle(tmp_path)
    manifest = ConcurrentRobustnessManifestV2.model_validate(
        json.loads(request.manifest.path.read_text(encoding="utf-8"))
    )
    adapters, transports = _formal_adapters(manifest)

    preflight = _preflight_adapters(manifest, adapters)  # type: ignore[arg-type]

    assert [cell.cell_id for cell, _adapter in preflight] == [
        cell.cell_id for cell in manifest.prompt_model_cells
    ]
    assert all(transport.subscription_nominal_cost_usd_total == 0.0 for transport in transports)


def test_study_rejects_formal_execution_without_plan_before_workspace_or_adapters(
    tmp_path: Path,
) -> None:
    request, _qualifications = _request_bundle(tmp_path)
    manifest = ConcurrentRobustnessManifestV2.model_validate(
        json.loads(request.manifest.path.read_text(encoding="utf-8"))
    )

    with pytest.raises(ConcurrentRobustnessError) as captured:
        ConcurrentRobustnessStudy().run(
            manifest,
            adapters_by_cell=_ExplodingAdapterMap(),  # type: ignore[arg-type]
            output_dir=request.output_root,
        )

    assert captured.value.code is ConcurrentRobustnessErrorCode.FORMAL_AUTHORIZATION_REQUIRED
    assert not request.output_root.exists()


def test_study_revalidates_authorized_plan_and_source_before_workspace_or_adapters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _qualifications = _request_bundle(tmp_path)
    monkeypatch.setattr(formal_module, "_utc_now", lambda: _NOW)
    authorization_path, authorization_sha256, _authorization = _authorization_artifact(
        tmp_path, request
    )
    plan_path = tmp_path / "formal-execution-plan.json"
    authorize_formal_execution(
        request=request,
        authorization_path=authorization_path,
        authorization_sha256=authorization_sha256,
        plan_output=plan_path,
    )
    manifest = ConcurrentRobustnessManifestV2.model_validate(
        json.loads(request.manifest.path.read_text(encoding="utf-8"))
    )

    with pytest.raises(ConcurrentRobustnessError) as captured:
        ConcurrentRobustnessStudy().run(
            manifest,
            adapters_by_cell=_ExplodingAdapterMap(),  # type: ignore[arg-type]
            output_dir=request.output_root,
            formal_execution_plan=plan_path,
        )

    assert captured.value.code is ConcurrentRobustnessErrorCode.INVALID_SOURCE
    assert not request.output_root.exists()
