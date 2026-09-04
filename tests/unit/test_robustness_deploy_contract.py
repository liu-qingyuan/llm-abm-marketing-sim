from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = REPO_ROOT / "scripts" / "validate_abm_report_release.py"


def _load_validator():
    spec = importlib.util.spec_from_file_location("validate_abm_report_release_v7_test", VALIDATOR_PATH)
    assert spec is not None and spec.loader is not None
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    return validator


def test_standalone_validator_dispatches_v7_through_its_own_branch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validator = _load_validator()
    source = tmp_path / "release"
    source.mkdir()
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    contract_path = tmp_path / "release-contract.json"
    contract_path.write_text(
        json.dumps({"schema_version": "abm-report-release-contract-v7"}),
        encoding="utf-8",
    )
    expected = {
        "schema_version": "abm-report-release-contract-v7",
        "release_purpose": "concurrent_robustness_formal_research",
        "source_directory": "release",
        "sampling_method": "seed_first_research_sample_v1",
        "sampling_status": "persisted_seed_first_formal_run",
        "decision_execution_mode": "live_provider",
        "report_sha256": "a" * 64,
        "production_deploy_eligible": True,
    }
    calls: list[dict[str, object]] = []

    def validate_v7(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return expected

    monkeypatch.setattr(validator, "_validate_v7", validate_v7, raising=False)

    assert (
        validator.validate_release(
            repo_root=tmp_path,
            contract_path=contract_path,
            source_dir=source,
            snapshot_dir=snapshot,
        )
        == expected
    )
    assert calls == [
        {
            "repo_root": tmp_path.resolve(),
            "contract_document": {"schema_version": "abm-report-release-contract-v7"},
            "source_dir": source,
            "snapshot_dir": snapshot,
        }
    ]

    contract_path.write_text(
        json.dumps(
            {
                "schema_version": "abm-report-release-contract-v6",
                "semantic_set_identity_sha256": "b" * 64,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(validator.ReleaseValidationError, match="invalid v6"):
        validator.validate_release(
            repo_root=tmp_path,
            contract_path=contract_path,
            source_dir=source,
        )

    contract_path.write_text(
        json.dumps({"schema_version": "abm-report-release-contract-v8"}),
        encoding="utf-8",
    )
    expected_v8 = {
        "schema_version": "abm-report-release-contract-v8",
        "release_purpose": "full_pool_formal_research",
        "source_directory": "release",
        "sampling_method": "full_pool_no_membership_filter_v1",
        "sampling_status": "persisted_full_pool_formal_run",
        "decision_execution_mode": "live_provider",
        "live_api_triggered": True,
        "report_sha256": "b" * 64,
        "production_deploy_eligible": True,
    }
    v8_calls: list[dict[str, object]] = []

    def validate_v8(**kwargs: object) -> dict[str, object]:
        v8_calls.append(kwargs)
        return expected_v8

    monkeypatch.setattr(validator, "_validate_v8", validate_v8, raising=False)
    assert validator.validate_release(
        repo_root=tmp_path,
        contract_path=contract_path,
        source_dir=source,
        snapshot_dir=snapshot,
    ) == expected_v8
    assert v8_calls == [
        {
            "repo_root": tmp_path.resolve(),
            "contract_document": {"schema_version": "abm-report-release-contract-v8"},
            "source_dir": source,
            "snapshot_dir": snapshot,
        }
    ]

    contract_path.write_text(
        json.dumps({"schema_version": "abm-report-release-contract-v9"}),
        encoding="utf-8",
    )
    expected_v9 = {
        **expected_v8,
        "schema_version": "abm-report-release-contract-v9",
        "release_purpose": "full_pool_segmented_formal_research",
        "sampling_status": "persisted_full_pool_segmented_formal_run",
    }
    v9_calls: list[dict[str, object]] = []

    def validate_v9(**kwargs: object) -> dict[str, object]:
        v9_calls.append(kwargs)
        return expected_v9

    monkeypatch.setattr(validator, "_validate_v9", validate_v9, raising=False)
    assert validator.validate_release(
        repo_root=tmp_path,
        contract_path=contract_path,
        source_dir=source,
        snapshot_dir=snapshot,
    ) == expected_v9
    assert v9_calls == [
        {
            "repo_root": tmp_path.resolve(),
            "contract_document": {"schema_version": "abm-report-release-contract-v9"},
            "source_dir": source,
            "snapshot_dir": snapshot,
        }
    ]

    contract_path.write_text(
        json.dumps({"schema_version": "abm-report-release-contract-v10"}),
        encoding="utf-8",
    )
    expected_v10 = {
        **expected_v8,
        "schema_version": "abm-report-release-contract-v10",
        "release_purpose": "full_pool_automated_nested_formal_research",
        "sampling_status": "persisted_full_pool_automated_nested_formal_run",
    }
    v10_calls: list[dict[str, object]] = []

    def validate_v10(**kwargs: object) -> dict[str, object]:
        v10_calls.append(kwargs)
        return expected_v10

    monkeypatch.setattr(validator, "_validate_v10", validate_v10, raising=False)
    assert validator.validate_release(
        repo_root=tmp_path,
        contract_path=contract_path,
        source_dir=source,
        snapshot_dir=snapshot,
    ) == expected_v10
    assert v10_calls == [
        {
            "repo_root": tmp_path.resolve(),
            "contract_document": {"schema_version": "abm-report-release-contract-v10"},
            "source_dir": source,
            "snapshot_dir": snapshot,
        }
    ]

    contract_path.write_text(
        json.dumps({"schema_version": "abm-report-release-contract-v11"}),
        encoding="utf-8",
    )
    expected_v11 = {
        **expected_v8,
        "schema_version": "abm-report-release-contract-v11",
        "release_purpose": "full_pool_strict_fresh_formal_research",
        "sampling_status": "persisted_strict_fresh_full_pool_formal_run",
    }
    v11_calls: list[dict[str, object]] = []

    def validate_v11(**kwargs: object) -> dict[str, object]:
        v11_calls.append(kwargs)
        return expected_v11

    monkeypatch.setattr(validator, "_validate_v11", validate_v11, raising=False)
    assert validator.validate_release(
        repo_root=tmp_path,
        contract_path=contract_path,
        source_dir=source,
        snapshot_dir=snapshot,
    ) == expected_v11
    assert v11_calls == [
        {
            "repo_root": tmp_path.resolve(),
            "contract_document": {"schema_version": "abm-report-release-contract-v11"},
            "source_dir": source,
            "snapshot_dir": snapshot,
        }
    ]

    contract_path.write_text(
        json.dumps({"schema_version": "abm-report-release-contract-v12"}),
        encoding="utf-8",
    )
    expected_v12 = {
        **expected_v11,
        "schema_version": "abm-report-release-contract-v12",
    }
    v12_calls: list[dict[str, object]] = []

    def validate_v12(**kwargs: object) -> dict[str, object]:
        v12_calls.append(kwargs)
        return expected_v12

    monkeypatch.setattr(validator, "_validate_v12", validate_v12, raising=False)
    assert validator.validate_release(
        repo_root=tmp_path,
        contract_path=contract_path,
        source_dir=source,
        snapshot_dir=snapshot,
    ) == expected_v12
    assert v12_calls == [
        {
            "repo_root": tmp_path.resolve(),
            "contract_document": {"schema_version": "abm-report-release-contract-v12"},
            "source_dir": source,
            "snapshot_dir": snapshot,
        }
    ]

    contract_path.write_text(
        json.dumps({"schema_version": "abm-report-release-contract-v13"}),
        encoding="utf-8",
    )
    expected_v13 = {
        **expected_v12,
        "schema_version": "abm-report-release-contract-v13",
        "release_purpose": "full_pool_two_stage_realization_formal_research",
        "sampling_status": "persisted_two_stage_realized_full_pool_formal_run",
    }
    v13_calls: list[dict[str, object]] = []

    def validate_v13(**kwargs: object) -> dict[str, object]:
        v13_calls.append(kwargs)
        return expected_v13

    monkeypatch.setattr(validator, "_validate_v13", validate_v13, raising=False)
    assert validator.validate_release(
        repo_root=tmp_path,
        contract_path=contract_path,
        source_dir=source,
        snapshot_dir=snapshot,
    ) == expected_v13
    assert v13_calls == [
        {
            "repo_root": tmp_path.resolve(),
            "contract_document": {"schema_version": "abm-report-release-contract-v13"},
            "source_dir": source,
            "snapshot_dir": snapshot,
        }
    ]


@pytest.mark.parametrize(
    "mutation",
    [
        {"sampling_status": "validation_run"},
        {"decision_execution_mode": "rule_based"},
        {"decision_execution_mode": "mock_provider"},
        {"production_deploy_eligible": False},
    ],
)
def test_formal_production_gate_accepts_only_matching_live_deployable_facts(
    mutation: dict[str, object],
) -> None:
    validator = _load_validator()
    valid_v7 = {
        "schema_version": "abm-report-release-contract-v7",
        "release_purpose": "concurrent_robustness_formal_research",
        "sampling_status": "persisted_seed_first_formal_run",
        "decision_execution_mode": "live_provider",
        "production_deploy_eligible": True,
    }
    valid_v8 = {
        "schema_version": "abm-report-release-contract-v8",
        "release_purpose": "full_pool_formal_research",
        "sampling_status": "persisted_full_pool_formal_run",
        "decision_execution_mode": "live_provider",
        "live_api_triggered": True,
        "production_deploy_eligible": True,
    }
    valid_v9 = {
        **valid_v8,
        "schema_version": "abm-report-release-contract-v9",
        "release_purpose": "full_pool_segmented_formal_research",
        "sampling_status": "persisted_full_pool_segmented_formal_run",
    }
    valid_v10 = {
        **valid_v8,
        "schema_version": "abm-report-release-contract-v10",
        "release_purpose": "full_pool_automated_nested_formal_research",
        "sampling_status": "persisted_full_pool_automated_nested_formal_run",
    }
    valid_v11 = {
        **valid_v8,
        "schema_version": "abm-report-release-contract-v11",
        "release_purpose": "full_pool_strict_fresh_formal_research",
        "sampling_status": "persisted_strict_fresh_full_pool_formal_run",
    }
    valid_v12 = {
        **valid_v11,
        "schema_version": "abm-report-release-contract-v12",
    }

    validator._require_formal_production(valid_v7)
    validator._require_formal_production(valid_v8)
    validator._require_formal_production(valid_v9)
    validator._require_formal_production(valid_v10)
    validator._require_formal_production(valid_v11)
    validator._require_formal_production(valid_v12)
    with pytest.raises(validator.ReleaseValidationError, match="formal production deployment"):
        validator._require_formal_production(valid_v7 | mutation)
    with pytest.raises(validator.ReleaseValidationError, match="formal production deployment"):
        validator._require_formal_production(valid_v8 | mutation)
    with pytest.raises(validator.ReleaseValidationError, match="formal production deployment"):
        validator._require_formal_production(valid_v9 | mutation)
    with pytest.raises(validator.ReleaseValidationError, match="formal production deployment"):
        validator._require_formal_production(valid_v10 | mutation)
    with pytest.raises(validator.ReleaseValidationError, match="formal production deployment"):
        validator._require_formal_production(valid_v11 | mutation)
    with pytest.raises(validator.ReleaseValidationError, match="formal production deployment"):
        validator._require_formal_production(valid_v12 | mutation)
    with pytest.raises(validator.ReleaseValidationError, match="formal production deployment"):
        validator._require_formal_production(
            valid_v8 | {"release_purpose": "concurrent_robustness_formal_research"}
        )
    with pytest.raises(validator.ReleaseValidationError, match="formal production deployment"):
        validator._require_formal_production(valid_v8 | {"live_api_triggered": False})
    with pytest.raises(validator.ReleaseValidationError, match="formal production deployment"):
        validator._require_formal_production(valid_v8 | {"schema_version": "abm-report-release-contract-v7"})
    with pytest.raises(validator.ReleaseValidationError, match="formal production deployment"):
        validator._require_formal_production(valid_v8 | {"schema_version": "unknown-v9"})


def test_formal_production_gate_accepts_only_the_release_owned_v13_composite_profile() -> None:
    validator = _load_validator()
    readiness = {
        "schema_version": "full-pool-v13-release-readiness-v1",
        "release_id": "formal-two-stage-v13",
        "release_contract_schema": "abm-report-release-contract-v13",
        "realized_source_identity": "a" * 64,
        "canonical_endpoint": "https://abm.q1ngyuan.top/",
        "provider_calls_during_promotion": 0,
        "image_generation_triggered": False,
        "canonical_deployment_triggered": False,
        "operational_authorization_required": True,
        "deployment_authorized": False,
        "public_acceptance_recorded": False,
    }
    accounting = {
        "schema_version": "full-pool-two-stage-provider-accounting-v1",
        "upstream_live_api_triggered": True,
        "upstream_formal_research_evidence": True,
        "upstream_production_deploy_eligible": True,
        "realization_provider_calls": 0,
        "realization_live_api_triggered": False,
        "composite_live_api_triggered": True,
        "composite_zero_provider_formal": False,
    }
    valid = {
        "schema_version": "abm-report-release-contract-v13",
        "release_purpose": "full_pool_two_stage_realization_formal_research",
        "release_id": "formal-two-stage-v13",
        "sampling_status": "persisted_two_stage_realized_full_pool_formal_run",
        "decision_execution_mode": "upstream_live_provider_plus_zero_call_realization",
        "live_api_triggered": True,
        "formal_research_evidence": True,
        "realized_source_identity": "a" * 64,
        "release_readiness": readiness,
        "composite_provider_accounting": accounting,
        "realization_provider_calls": 0,
        "realization_live_api_triggered": False,
        "production_deploy_eligible": True,
    }

    validator._require_formal_production(valid)
    for mutation in (
        {"sampling_status": "validation_run"},
        {"decision_execution_mode": "live_provider"},
        {"live_api_triggered": False},
        {"formal_research_evidence": False},
        {"realization_provider_calls": 1},
        {"realization_live_api_triggered": True},
        {"production_deploy_eligible": False},
        {
            "composite_provider_accounting": {
                **accounting,
                "composite_zero_provider_formal": True,
            }
        },
        {
            "release_readiness": {
                **readiness,
                "realized_source_identity": "b" * 64,
            }
        },
    ):
        with pytest.raises(validator.ReleaseValidationError, match="formal production deployment"):
            validator._require_formal_production(valid | mutation)


def test_v7_deployment_facts_bind_full_mermaid_inventory_and_explicit_identity(
    tmp_path: Path,
) -> None:
    validator = _load_validator()
    source = tmp_path / "production-v7"
    source.mkdir()
    mermaid = {
        "mechanism-sample-first.mmd",
        "mechanism-pair-formation.mmd",
        "mechanism-independent-delivery.mmd",
        "mechanism-exposure-decisions.mmd",
        "mechanism-feedback-boundary.mmd",
        "real-batch-mechanism.mmd",
        "prompt-model-factorial.mmd",
    }
    (source / "report.html").write_text("<!doctype html><title>v7</title>\n", encoding="utf-8")
    (source / "concurrent_robustness_report_payload.json").write_text("{}\n", encoding="utf-8")
    for artifact in mermaid:
        (source / artifact).write_text("flowchart LR\n", encoding="utf-8")
    release_identity = "b" * 64
    manifest = {
        "release_id": "semantic-v7-release",
        "release_identity_sha256": release_identity,
        "approved_downloads": {artifact: artifact for artifact in sorted(mermaid)},
    }
    (source / "artifact_manifest.json").write_text(
        json.dumps(manifest, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    artifact_sha256 = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in source.iterdir() if path.is_file()
    }
    contract_path = tmp_path / "release-contract.json"
    contract = {
        "schema_version": "abm-report-release-contract-v7",
        "release_id": "semantic-v7-release",
        "canonical_endpoint": "https://abm.q1ngyuan.top/",
        "artifact_sha256": artifact_sha256,
    }
    contract_path.write_text(json.dumps(contract, sort_keys=True) + "\n", encoding="utf-8")
    result = {
        "schema_version": "abm-report-release-contract-v7",
        "release_purpose": "concurrent_robustness_formal_research",
        "release_id": "semantic-v7-release",
        "source_directory": "production-v7",
        "sampling_status": "persisted_seed_first_formal_run",
        "decision_execution_mode": "live_provider",
        "report_sha256": artifact_sha256["report.html"],
        "production_deploy_eligible": True,
    }

    facts = validator._build_deployment_facts(
        contract_path=contract_path,
        contract=contract,
        result=result,
        evidence_dir=source,
        deployment_release_id="semantic-v7-release",
        deployment_domain="abm.q1ngyuan.top",
    )

    assert facts["schema_version"] == "abm-report-deployment-facts-v1"
    assert facts["release_contract_schema_version"] == "abm-report-release-contract-v7"
    assert facts["report_kind"] == "concurrent-robustness"
    assert facts["release_id"] == "semantic-v7-release"
    assert facts["canonical_domain"] == "abm.q1ngyuan.top"
    assert facts["release_identity_sha256"] == release_identity
    assert facts["artifact_sha256"] == artifact_sha256
    assert set(facts["public_acceptance_artifacts"]) == set(artifact_sha256)
    assert set(facts["approved_downloads"]) == mermaid
    assert {path for path in facts["public_acceptance_artifacts"] if path.endswith(".mmd")} == mermaid
    assert "mechanism-image-generation-audit.json" not in facts["public_acceptance_artifacts"]
    assert not any(path.endswith(("-v4.png", "-v4.webp")) for path in facts["public_acceptance_artifacts"])

    for crossed in (
        {"deployment_release_id": "other-release", "deployment_domain": "abm.q1ngyuan.top"},
        {"deployment_release_id": "semantic-v7-release", "deployment_domain": "other.example.test"},
    ):
        with pytest.raises(validator.ReleaseValidationError, match="release id|canonical endpoint"):
            validator._build_deployment_facts(
                contract_path=contract_path,
                contract=contract,
                result=result,
                evidence_dir=source,
                **crossed,
            )


def test_v14_deployment_facts_project_release_owned_identities_and_workbook(
    tmp_path: Path,
) -> None:
    validator = _load_validator()
    source = tmp_path / "production-v14"
    source.mkdir()
    payloads = {
        "report.html": "<!doctype html><title>v14</title>\n",
        "artifact_manifest.json": "",
        "prompt_model_realized_results.xlsx": "workbook\n",
        "prompt-model-realized-mechanism.mmd": "flowchart LR\n",
    }
    release_id = "prompt-model-realized-v14"
    release_identity = "a" * 64
    approved = {
        "teacher_results_xlsx": "prompt_model_realized_results.xlsx",
        "prompt_model_realized_mechanism_mermaid": (
            "prompt-model-realized-mechanism.mmd"
        ),
    }
    manifest = {
        "release_id": release_id,
        "release_identity_sha256": release_identity,
        "approved_downloads": approved,
    }
    payloads["artifact_manifest.json"] = (
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    )
    for relative_path, payload in payloads.items():
        (source / relative_path).write_text(payload, encoding="utf-8")
    artifact_sha256 = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source.iterdir()
        if path.is_file()
    }
    full_pool_identity = (
        "b348c1bd309788df41b2a86106fe5216ce6fc6dc9317a67bc19351d3a249e1d7"
    )
    v2_identity = "c" * 64
    protected_v13_release_id = (
        "full-pool-two-stage-v13-production-20260826T142827Z"
    )
    protected_v13_identity = (
        "27130adc334502f83a4467aa6e4a89ca9ed5436ed451d43732889eae7a2c1f89"
    )
    physical_snapshot_identity = "e" * 64
    readiness = {
        "schema_version": "full-pool-v14-release-readiness-v1",
        "release_id": release_id,
        "release_contract_schema": "abm-report-release-contract-v14",
        "v2_study_root_identity_sha256": v2_identity,
        "protected_v13_release_id": protected_v13_release_id,
        "protected_v13_release_identity_sha256": protected_v13_identity,
        "canonical_endpoint": "https://abm.q1ngyuan.top/",
        "provider_calls_during_promotion": 0,
        "image_generation_triggered": False,
        "canonical_deployment_triggered": False,
        "operational_authorization_required": True,
        "deployment_authorized": False,
        "public_acceptance_recorded": False,
    }
    prompt_model_accounting = {
        "schema_version": "concurrent-robustness-v2-formal-provider-accounting-v1",
        "logical_judgments": 36_000,
        "successful_judgments": 36_000,
        "terminal_failures": 0,
        "physical_attempts": 36_000,
        "physical_attempt_cap": 108_000,
        "provider_calls": 36_000,
        "provider_responses": 36_000,
        "usage_complete_response_count": 36_000,
        "usage_missing_response_count": 0,
        "usage_malformed_response_count": 0,
        "observed_model_counts": {"observed-model": 36_000},
        "observed_model_missing_response_count": 0,
        "observed_model_malformed_response_count": 0,
        "successful_judgment_requested_model_counts": {
            "deepseek-v4-flash": 7_200,
            "gemini-3.1-pro": 7_200,
            "gemini-3.8-flash-high": 7_200,
            "kimi-coding/k3-256k": 7_200,
            "openai-codex/gpt-5.6-sol": 7_200,
        },
        "successful_judgment_observed_model_counts": {
            "observed-model": 36_000
        },
        "provider_route_counts": {"test-route": 36_000},
        "billing_semantics_counts": {"test-billing": 36_000},
        "input_tokens": 36_000,
        "output_tokens": 18_000,
        "total_tokens": 54_000,
        "cached_input_tokens": 0,
        "provider_fee_cny": 24.0,
        "subscription_nominal_cost_usd_reference": 0.0,
        "cross_currency_total_reported": False,
        "live_api_triggered": True,
        "formal_research_evidence": True,
    }
    full_pool_accounting = {
        "schema_version": "full-pool-two-stage-provider-accounting-v1",
        "upstream_live_api_triggered": True,
        "upstream_formal_research_evidence": True,
        "upstream_production_deploy_eligible": True,
        "upstream_requested_model": "gpt-5.6-sol",
        "upstream_observed_model_counts": {"gpt-5.6-sol": 109_200},
        "upstream_logical_judgments": 109_200,
        "upstream_provider_responses": 109_200,
        "upstream_successful_decisions": 109_200,
        "upstream_external_request_invocations": 110_320,
        "upstream_usage_complete_response_count": 109_200,
        "upstream_usage_missing_response_count": 0,
        "upstream_usage_malformed_response_count": 0,
        "upstream_settled_actual_attempts": 110_320,
        "upstream_dispatched_without_settlement_uncertainty": 0,
        "upstream_charged_physical_attempts": 110_320,
        "upstream_physical_cap": 120_120,
        "upstream_provider_accounting": {
            "schema_version": "provider-accounting-v1",
            "external_request_invocations": 110_320,
            "provider_response_count": 109_200,
            "successful_decision_count": 109_200,
            "usage_complete_response_count": 109_200,
            "usage_missing_response_count": 0,
            "usage_malformed_response_count": 0,
            "observed_model_counts": {"gpt-5.6-sol": 109_200},
            "observed_model_missing_response_count": 0,
            "observed_model_malformed_response_count": 0,
            "input_tokens": 107_373_847,
            "output_tokens": 13_377_353,
            "total_tokens": 120_751_200,
            "cached_input_tokens": 0,
            "cached_input_tokens_reported_response_count": 109_200,
        },
        "realization_provider_calls": 0,
        "realization_live_api_triggered": False,
        "composite_live_api_triggered": True,
        "composite_zero_provider_formal": False,
    }
    provider_accounting = {
        "schema_version": "full-pool-prompt-model-provider-accounting-v1",
        "full_pool_two_stage": full_pool_accounting,
        "prompt_model_v2": prompt_model_accounting,
        "provider_calls_during_promotion": 0,
        "live_api_triggered_during_promotion": False,
        "composite_live_api_triggered": True,
        "cross_currency_total_reported": False,
    }
    contract_path = tmp_path / "release-contract-v14.json"
    contract = {
        "schema_version": "abm-report-release-contract-v14",
        "release_id": release_id,
        "canonical_endpoint": "https://abm.q1ngyuan.top/",
        "release_identity_sha256": release_identity,
        "physical_snapshot_identity_sha256": physical_snapshot_identity,
        "full_pool_source": {"source_identity": full_pool_identity},
        "v2_study": {"root_identity_sha256": v2_identity},
        "protected_v13": {
            "release_id": protected_v13_release_id,
            "release_identity_sha256": protected_v13_identity,
        },
        "workbook": {
            "relative_path": "prompt_model_realized_results.xlsx",
            "sha256": artifact_sha256["prompt_model_realized_results.xlsx"],
        },
        "artifact_sha256": artifact_sha256,
    }
    contract_path.write_text(
        json.dumps(contract, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    result = {
        "schema_version": "abm-report-release-contract-v14",
        "release_purpose": (
            "full_pool_two_stage_prompt_model_realized_robustness_formal_research"
        ),
        "release_id": release_id,
        "source_directory": "runs/prompt-model-realized-v14",
        "sampling_method": "full_pool_no_membership_filter_v1",
        "sampling_status": (
            "persisted_full_pool_two_stage_and_prompt_model_realized_formal_runs"
        ),
        "decision_execution_mode": "full_pool_upstream_and_prompt_model_two_stage_live",
        "live_api_triggered": True,
        "formal_research_evidence": True,
        "logical_judgments": 36_000,
        "physical_attempts": 36_000,
        "provider_calls": 36_000,
        "provider_responses": 36_000,
        "usage_complete_response_count": 36_000,
        "observed_model_counts": {"observed-model": 36_000},
        "provider_accounting": provider_accounting,
        "full_pool_source_identity": full_pool_identity,
        "v2_study_root_identity_sha256": v2_identity,
        "protected_v13_release_id": protected_v13_release_id,
        "release_readiness": readiness,
        "release_identity_sha256": release_identity,
        "physical_snapshot_identity_sha256": physical_snapshot_identity,
        "report_sha256": artifact_sha256["report.html"],
        "manifest_sha256": artifact_sha256["artifact_manifest.json"],
        "artifact_count": len(artifact_sha256),
        "production_deploy_eligible": True,
    }

    validator._require_formal_production(result)
    crossed_result = dict(result)
    crossed_result["provider_accounting"] = {
        **provider_accounting,
        "provider_calls_during_promotion": 1,
    }
    with pytest.raises(
        validator.ReleaseValidationError,
        match="exact v14 Prompt–Model profile",
    ):
        validator._require_formal_production(crossed_result)

    empty_full_pool = json.loads(json.dumps(result))
    empty_full_pool["provider_accounting"]["full_pool_two_stage"] = {}
    with pytest.raises(
        validator.ReleaseValidationError,
        match="exact v14 Prompt–Model profile",
    ):
        validator._require_formal_production(empty_full_pool)

    crossed_full_pool = json.loads(json.dumps(result))
    crossed_full_pool["provider_accounting"]["full_pool_two_stage"][
        "upstream_external_request_invocations"
    ] = 109_200
    with pytest.raises(
        validator.ReleaseValidationError,
        match="exact v14 Prompt–Model profile",
    ):
        validator._require_formal_production(crossed_full_pool)

    crossed_source = {
        **result,
        "full_pool_source_identity": "b" * 64,
    }
    with pytest.raises(
        validator.ReleaseValidationError,
        match="exact v14 Prompt–Model profile",
    ):
        validator._require_formal_production(crossed_source)

    crossed_protected = json.loads(json.dumps(result))
    crossed_protected["protected_v13_release_id"] = "protected-v13"
    with pytest.raises(
        validator.ReleaseValidationError,
        match="exact v14 Prompt–Model profile",
    ):
        validator._require_formal_production(crossed_protected)

    facts = validator._build_deployment_facts(
        contract_path=contract_path,
        contract=contract,
        result=result,
        evidence_dir=source,
        deployment_release_id=release_id,
        deployment_domain="abm.q1ngyuan.top",
    )

    assert facts["release_contract_schema_version"] == (
        "abm-report-release-contract-v14"
    )
    assert facts["full_pool_source_identity"] == full_pool_identity
    assert facts["v2_study_root_identity_sha256"] == v2_identity
    assert facts["protected_v13_release_identity_sha256"] == (
        protected_v13_identity
    )
    assert facts["physical_snapshot_identity_sha256"] == (
        physical_snapshot_identity
    )
    assert facts["workbook_relative_path"] == (
        "prompt_model_realized_results.xlsx"
    )
    assert facts["workbook_sha256"] == artifact_sha256[
        "prompt_model_realized_results.xlsx"
    ]
    assert facts["release_readiness"] == readiness
    assert "provider_accounting" not in facts

    crossed = dict(contract)
    crossed["workbook"] = {
        "relative_path": "prompt_model_realized_results.xlsx",
        "sha256": "0" * 64,
    }
    with pytest.raises(
        validator.ReleaseValidationError,
        match="workbook|deployment profile",
    ):
        validator._build_deployment_facts(
            contract_path=contract_path,
            contract=crossed,
            result=result,
            evidence_dir=source,
            deployment_release_id=release_id,
            deployment_domain="abm.q1ngyuan.top",
        )

    crossed_result_hash = {**result, "report_sha256": "0" * 64}
    with pytest.raises(
        validator.ReleaseValidationError,
        match="report hash|source or snapshot identity",
    ):
        validator._build_deployment_facts(
            contract_path=contract_path,
            contract=contract,
            result=crossed_result_hash,
            evidence_dir=source,
            deployment_release_id=release_id,
            deployment_domain="abm.q1ngyuan.top",
        )


def test_v8_deployment_facts_bind_full_pool_inventory_and_explicit_identity(
    tmp_path: Path,
) -> None:
    validator = _load_validator()
    source = tmp_path / "production-v8"
    source.mkdir()
    mermaid = {
        "full-pool-mechanism.mmd",
        "historical-1000/mechanism-sample-first.mmd",
        "historical-1000/mechanism-pair-formation.mmd",
        "historical-1000/mechanism-independent-delivery.mmd",
        "historical-1000/mechanism-exposure-decisions.mmd",
        "historical-1000/mechanism-feedback-boundary.mmd",
        "historical-1000/real-batch-mechanism.mmd",
        "historical-1000/prompt-model-factorial.mmd",
    }
    payloads = {
        "report.html": "<!doctype html><title>v8</title>\n",
        "concurrent_robustness_report_payload.json": "{}\n",
        "full_pool_production_release_evidence.json": "{}\n",
        "full_pool_presentation_closure.json": "{}\n",
        "full_pool_candidate_artifact_manifest.json": "{}\n",
        "full_pool_candidate_release_evidence.json": "{}\n",
        "trace/full-pool-trace-index.json": "{}\n",
        "trace/message_1/batch-000000.json": "{}\n",
        **{path: "flowchart LR\n" for path in mermaid},
    }
    for relative_path, payload in payloads.items():
        target = source / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload, encoding="utf-8")
    release_identity = "c" * 64
    approved = {
        "full_pool_trace_index": "trace/full-pool-trace-index.json",
        **{f"mermaid_{index}": path for index, path in enumerate(sorted(mermaid))},
    }
    manifest = {
        "release_id": "full-pool-v8-release",
        "release_identity_sha256": release_identity,
        "approved_downloads": approved,
    }
    (source / "artifact_manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    artifact_sha256 = {
        path.relative_to(source).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source.rglob("*")
        if path.is_file()
    }
    contract_path = tmp_path / "release-contract-v8.json"
    contract = {
        "schema_version": "abm-report-release-contract-v8",
        "release_id": "full-pool-v8-release",
        "canonical_endpoint": "https://abm.q1ngyuan.top/",
        "release_identity_sha256": release_identity,
        "artifact_sha256": artifact_sha256,
    }
    contract_path.write_text(json.dumps(contract, sort_keys=True) + "\n", encoding="utf-8")
    result = {
        "schema_version": "abm-report-release-contract-v8",
        "release_purpose": "full_pool_formal_research",
        "release_id": "full-pool-v8-release",
        "source_directory": "production-v8",
        "sampling_status": "persisted_full_pool_formal_run",
        "decision_execution_mode": "live_provider",
        "live_api_triggered": True,
        "report_sha256": artifact_sha256["report.html"],
        "production_deploy_eligible": True,
    }

    facts = validator._build_deployment_facts(
        contract_path=contract_path,
        contract=contract,
        result=result,
        evidence_dir=source,
        deployment_release_id="full-pool-v8-release",
        deployment_domain="abm.q1ngyuan.top",
    )

    assert facts["report_kind"] == "full-pool"
    assert facts["release_contract_schema_version"] == "abm-report-release-contract-v8"
    assert facts["release_identity_sha256"] == release_identity
    assert facts["artifact_sha256"] == artifact_sha256
    assert set(facts["approved_downloads"]) == set(approved.values())
    assert set(facts["public_acceptance_artifacts"]) == set(artifact_sha256)
    assert {path for path in artifact_sha256 if path.endswith(".mmd")} == mermaid
    assert "trace/full-pool-trace-index.json" in facts["public_acceptance_artifacts"]
    assert "trace/message_1/batch-000000.json" in facts["public_acceptance_artifacts"]


def test_v9_deployment_facts_preserve_segmented_release_identity(tmp_path: Path) -> None:
    validator = _load_validator()
    source = tmp_path / "production-v9"
    source.mkdir()
    (source / "report.html").write_text("<!doctype html><title>v9</title>\n", encoding="utf-8")
    release_identity = "d" * 64
    manifest = {
        "release_id": "full-pool-segmented-v9",
        "release_identity_sha256": release_identity,
        "approved_downloads": {},
    }
    (source / "artifact_manifest.json").write_text(
        json.dumps(manifest, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    artifact_sha256 = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source.iterdir()
        if path.is_file()
    }
    contract_path = tmp_path / "release-contract-v9.json"
    contract = {
        "schema_version": "abm-report-release-contract-v9",
        "release_id": "full-pool-segmented-v9",
        "canonical_endpoint": "https://abm.q1ngyuan.top/",
        "release_identity_sha256": release_identity,
        "artifact_sha256": artifact_sha256,
    }
    contract_path.write_text(json.dumps(contract, sort_keys=True) + "\n", encoding="utf-8")
    result = {
        "schema_version": "abm-report-release-contract-v9",
        "release_purpose": "full_pool_segmented_formal_research",
        "release_id": "full-pool-segmented-v9",
        "source_directory": "production-v9",
        "sampling_status": "persisted_full_pool_segmented_formal_run",
        "decision_execution_mode": "live_provider",
        "live_api_triggered": True,
        "report_sha256": artifact_sha256["report.html"],
        "production_deploy_eligible": True,
    }

    facts = validator._build_deployment_facts(
        contract_path=contract_path,
        contract=contract,
        result=result,
        evidence_dir=source,
        deployment_release_id="full-pool-segmented-v9",
        deployment_domain="abm.q1ngyuan.top",
    )

    assert facts["report_kind"] == "full-pool"
    assert facts["release_contract_schema_version"] == "abm-report-release-contract-v9"
    assert facts["release_identity_sha256"] == release_identity
    assert facts["artifact_sha256"] == artifact_sha256


def test_v8_schema_confusion_is_rejected_before_fake_ssh(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    deploy_script = scripts / "deploy_abm_report.sh"
    validator_script = scripts / "validate_abm_report_release.py"
    shutil.copy2(REPO_ROOT / "scripts" / "deploy_abm_report.sh", deploy_script)
    shutil.copy2(VALIDATOR_PATH, validator_script)
    source = repo / "production-v8"
    source.mkdir()
    (source / "report.html").write_text("candidate\n", encoding="utf-8")
    (source / "artifact_manifest.json").write_text("{}\n", encoding="utf-8")
    contract = repo / "release-contract-v8.json"
    contract.write_text(
        json.dumps({"schema_version": "abm-report-release-contract-v8"}) + "\n",
        encoding="utf-8",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    ssh_marker = tmp_path / "ssh-invoked"
    ssh = fake_bin / "ssh"
    ssh.write_text(
        '#!/usr/bin/env bash\nprintf invoked > "${FAKE_SSH_MARKER}"\nexit 0\n',
        encoding="utf-8",
    )
    ssh.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "ABM_DEPLOY_PYTHON": sys.executable,
            "FAKE_SSH_MARKER": str(ssh_marker),
        }
    )

    completed = subprocess.run(
        [
            str(deploy_script),
            "--contract",
            str(contract),
            "--source-dir",
            str(source),
            "--release-id",
            "full-pool-v8-rejected",
        ],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "invalid v8 Full-Pool release" in completed.stderr
    assert not ssh_marker.exists()


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


@pytest.mark.parametrize("failure_mode", ["candidate-health", "switch-failure"])
def test_remote_transaction_failures_preserve_fresh_rollback_identity(
    tmp_path: Path,
    failure_mode: str,
) -> None:
    script = (REPO_ROOT / "scripts" / "deploy_abm_report.sh").read_text(encoding="utf-8")
    remote_script = script.split("<<'REMOTE_DEPLOY'", maxsplit=1)[1].split(
        "REMOTE_DEPLOY", maxsplit=1
    )[0]
    host_nginx = tmp_path / "host-nginx"
    (host_nginx / "sites-available").mkdir(parents=True)
    (host_nginx / "sites-enabled").mkdir()
    remote_script = remote_script.replace("/etc/nginx", str(host_nginx))
    transaction = tmp_path / "remote-transaction.sh"
    _write_executable(transaction, "#!/usr/bin/env bash\n" + remote_script)

    remote_root = tmp_path / "remote"
    previous = remote_root / "releases" / "previous"
    candidate = remote_root / "releases" / "candidate"
    previous.mkdir(parents=True)
    candidate.mkdir()
    (previous / "report.html").write_text("previous report\n", encoding="utf-8")
    (previous / "artifact_manifest.json").write_text("{}\n", encoding="utf-8")
    release_id = "candidate"
    release_identity = "c" * 64
    report = (
        '<!doctype html><head><meta name="abm-release-id" content="candidate">'
        '<meta name="abm-release-contract" content="abm-report-release-contract-v8">'
        "</head><body>candidate</body>\n"
    )
    (candidate / "report.html").write_text(report, encoding="utf-8")
    (candidate / "artifact_manifest.json").write_text(
        json.dumps(
            {
                "release_id": release_id,
                "release_identity_sha256": release_identity,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    (remote_root / "nginx").mkdir()
    (remote_root / "tls").mkdir()
    (remote_root / "tls" / "abm.example.test.crt").write_text("crt\n", encoding="utf-8")
    (remote_root / "tls" / "abm.example.test.key").write_text("key\n", encoding="utf-8")
    (remote_root / "current").symlink_to(previous)

    previous_report_sha = hashlib.sha256((previous / "report.html").read_bytes()).hexdigest()
    previous_manifest_sha = hashlib.sha256(
        (previous / "artifact_manifest.json").read_bytes()
    ).hexdigest()
    report_sha = hashlib.sha256((candidate / "report.html").read_bytes()).hexdigest()
    manifest_sha = hashlib.sha256((candidate / "artifact_manifest.json").read_bytes()).hexdigest()
    checksum_rows = (
        f"{manifest_sha}  artifact_manifest.json\n"
        f"{report_sha}  report.html\n"
    )

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    compose_count = tmp_path / "compose-count"
    _write_executable(
        fake_bin / "docker",
        """#!/usr/bin/env bash
set -euo pipefail
command_name="$1"
shift
case "${command_name}" in
  rm|logs) exit 0 ;;
  run)
    [[ "${FAKE_DOCKER_MODE}" != "candidate-health" ]] || exit 71
    printf 'candidate-container\n'
    ;;
  inspect)
    printf 'healthy\n'
    ;;
  exec)
    container="$1"
    shift
    if [[ "$1" == "test" && "$2" == "-f" ]]; then
      relative_path="${3#/usr/share/nginx/html/}"
      if [[ "${container}" == *-candidate ]]; then
        [[ -f "${FAKE_REMOTE_RELEASE}/${relative_path}" ]]
      else
        [[ -f "$(readlink -f "${FAKE_REMOTE_ROOT}/current")/${relative_path}" ]]
      fi
      exit
    fi
    [[ "$1" == "wget" ]] || exit 2
    url="${*: -1}"
    case "${url}" in
      */healthz) printf 'ok\n' ;;
      */report.html) artifact='report.html' ;;
      */artifact_manifest.json) artifact='artifact_manifest.json' ;;
      *) exit 2 ;;
    esac
    if [[ -n "${artifact:-}" ]]; then
      if [[ "${container}" == *-candidate ]]; then
        cat "${FAKE_REMOTE_RELEASE}/${artifact}"
      else
        cat "$(readlink -f "${FAKE_REMOTE_ROOT}/current")/${artifact}"
      fi
    fi
    ;;
  compose)
    if [[ " $* " == *" up "* ]]; then
      count=0
      [[ ! -f "${FAKE_COMPOSE_COUNT}" ]] || count="$(<"${FAKE_COMPOSE_COUNT}")"
      count=$((count + 1))
      printf '%s' "${count}" > "${FAKE_COMPOSE_COUNT}"
      if [[ "${FAKE_DOCKER_MODE}" == "switch-failure" && "${count}" == "1" ]]; then
        exit 72
      fi
    fi
    ;;
  *) exit 2 ;;
esac
""",
    )
    _write_executable(fake_bin / "nginx", "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(fake_bin / "systemctl", "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(
        fake_bin / "mv",
        """#!/usr/bin/env bash
if [[ "$1" == "-Tf" ]]; then
  /bin/mv -f "$2" "$3"
else
  /bin/mv "$@"
fi
""",
    )
    _write_executable(
        fake_bin / "sed",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" != "-i" ]]; then
  exec /usr/bin/sed "$@"
fi
if /usr/bin/sed --version >/dev/null 2>&1; then
  /usr/bin/sed -i "$2" "$3"
else
  /usr/bin/sed -i '' "$2" "$3"
fi
""",
    )
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "FAKE_DOCKER_MODE": failure_mode,
            "FAKE_REMOTE_ROOT": str(remote_root),
            "FAKE_REMOTE_RELEASE": str(candidate),
            "FAKE_COMPOSE_COUNT": str(compose_count),
        }
    )
    completed = subprocess.run(
        [
            str(transaction),
            str(remote_root),
            str(candidate),
            str(previous),
            previous_report_sha,
            previous_manifest_sha,
            "abm.example.test",
            "18083",
            "abm-research-report",
            "nginx:1.27-alpine",
            report_sha,
            manifest_sha,
            release_id,
            release_identity,
            "d" * 64,
            base64.b64encode(checksum_rows.encode()).decode(),
            "2",
            "abm-report-release-contract-v8",
        ],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert (remote_root / "current").resolve() == previous.resolve()
    assert hashlib.sha256((previous / "report.html").read_bytes()).hexdigest() == previous_report_sha
    assert (
        hashlib.sha256((previous / "artifact_manifest.json").read_bytes()).hexdigest()
        == previous_manifest_sha
    )
    assert "remote rollback identity verification failed" not in completed.stderr
    if failure_mode == "switch-failure":
        assert compose_count.exists(), completed.stderr
        assert compose_count.read_text(encoding="utf-8") == "2"
    else:
        assert not compose_count.exists()


def test_deploy_accepts_v13_and_v14_through_authorized_atomic_contract() -> None:
    script = (REPO_ROOT / "scripts" / "deploy_abm_report.sh").read_text(
        encoding="utf-8"
    )
    remote = script.split("<<'REMOTE_DEPLOY'", maxsplit=1)[1].split(
        "REMOTE_DEPLOY", maxsplit=1
    )[0]
    acceptance = (REPO_ROOT / "tests/playwright/deployed-abm-report.spec.ts").read_text(
        encoding="utf-8"
    )

    assert "^abm-report-release-contract-v([2-9]|10|11|12|13|14)$" in script
    assert "^abm-report-release-contract-v([2-9]|10|11|12|13|14)$" in remote
    assert script.index("--require-formal-production") < script.index(
        'printf \'Uploading %s to %s:%s\\n\''
    )
    assert script.index('wait_healthy "${candidate_name}"') < script.index(
        'atomic_current "${remote_release}"'
    )
    assert "REMOTE_ROLLBACK" in script
    verifier = (REPO_ROOT / "scripts" / "verify_abm_public_artifact_bodies.py").read_text(
        encoding="utf-8"
    )
    assert "public artifact checksum mismatch" in verifier
    assert '"${SCRIPT_DIR}/verify_abm_public_artifact_bodies.py"' in script
    assert 'ABM_DEPLOY_RELEASE_CONTRACT_SCHEMA="${RELEASE_CONTRACT_SCHEMA}"' in script
    assert "process.env.ABM_DEPLOY_RELEASE_CONTRACT_SCHEMA" in acceptance
    assert "releaseContractSchema ?? 'abm-report-release-contract-v8'" in acceptance
    assert "'abm-report-release-contract-v13'" in acceptance
    assert "releaseContractSchema === 'abm-report-release-contract-v14'" in acceptance
    assert "robustness-v2-realized-view" in acceptance
    assert "robustness-v2-judgment-view" in acceptance
    assert "full-pool-mechanism-svg" in acceptance
    assert "full-pool-source/full-pool-realized-projection.csv" in acceptance


def test_deploy_consumes_validated_facts_and_checks_the_snapshot_before_ssh() -> None:
    script = (REPO_ROOT / "scripts" / "deploy_abm_report.sh").read_text(encoding="utf-8")

    facts_gate = script.index("--deployment-facts-output")
    snapshot_check = script.index('shasum -a 256 -c "${LOCAL_CHECKSUMS_FILE}"')
    first_ssh = script.index('if ssh "${DEPLOY_HOST}"')
    assert facts_gate < snapshot_check < first_ssh
    assert "--deployment-release-id" in script
    assert "--deployment-domain" in script
    assert "PUBLIC_ACCEPTANCE_ARTIFACTS_JSON" in script
    assert "^abm-report-release-contract-v([2-9]|10|11|12|13|14)$" in script
    assert "ARTIFACT_CHECKSUMS_B64" in script
    assert "Path(sys.argv[1]).read_text" not in script


def test_v5_deploy_binds_cli_release_id_and_canonical_domain() -> None:
    script = (REPO_ROOT / "scripts" / "deploy_abm_report.sh").read_text(encoding="utf-8")

    assert '[[ "${VALIDATED_RELEASE_ID}" == "${RELEASE_ID}" ]]' in script
    assert '[[ "${VALIDATED_DOMAIN}" == "${DOMAIN}" ]]' in script


def test_remote_candidate_closes_contract_inventory_and_nginx_before_atomic_switch() -> None:
    script = (REPO_ROOT / "scripts" / "deploy_abm_report.sh").read_text(encoding="utf-8")
    remote = script.split("<<'REMOTE_DEPLOY'", maxsplit=1)[1].split("REMOTE_DEPLOY", maxsplit=1)[0]

    inventory_verified = remote.index('sha256sum -c "${contract_checksums}"')
    candidate_started = remote.index("docker run -d")
    candidate_manifest_checked = remote.index("candidate_manifest_sha=", candidate_started)
    nginx_checked = remote.index("nginx -t", candidate_manifest_checked)
    current_switched = remote.index('atomic_current "${remote_release}"', nginx_checked)
    assert inventory_verified < candidate_started < candidate_manifest_checked < nginx_checked < current_switched
    assert 'validate_previous_identity "before candidate health"' in remote
    assert 'validate_previous_identity "before atomic current switch"' in remote
    assert 'grep -Fq "\\"release_id\\":\\"${release_id}\\""' in remote
    assert 'grep -Fq "\\"release_identity_sha256\\":\\"${release_identity_sha}\\""' in remote
    assert 'grep -Fq "<meta name=\\"abm-release-id\\" content=\\"${release_id}\\">"' in remote
    assert (
        'grep -Fq "<meta name=\\"abm-release-contract\\" content=\\"${release_contract_schema}\\">"'
        in remote
    )
    assert "validated_contract_sha" in remote


def test_public_acceptance_failure_adapter_always_invokes_rollback(tmp_path: Path) -> None:
    script = (REPO_ROOT / "scripts" / "deploy_abm_report.sh").read_text(encoding="utf-8")
    start = script.index("rollback_on_failure() {")
    stop = script.index("trap rollback_on_failure EXIT", start)
    rollback_function = script[start:stop]
    harness = tmp_path / "public-failure-adapter.sh"
    marker = tmp_path / "rollback-invoked"
    operation_facts = tmp_path / "operation-facts.json"
    operation_facts.write_text("false-success\n", encoding="utf-8")
    _write_executable(
        harness,
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "cutover_complete=1\n"
        "PREVIOUS_RELEASE=/remote/releases/previous\n"
        "OPERATION_FACTS_WRITE_ATTEMPTED=1\n"
        f"DEPLOYMENT_OPERATION_FACTS_OUTPUT={shlex.quote(str(operation_facts))}\n"
        f"ROLLBACK_MARKER={shlex.quote(str(marker))}\n"
        "rollback_remote() { printf invoked > \"${ROLLBACK_MARKER}\"; }\n"
        "cleanup_local_snapshot() { return 0; }\n"
        f"{rollback_function}\n"
        "rollback_on_failure 1\n",
    )

    completed = subprocess.run(
        [str(harness)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    assert marker.read_text(encoding="utf-8") == "invoked"
    assert not operation_facts.exists()
    assert "Public acceptance failed; restoring previous release" in completed.stderr


def test_public_failure_rollback_revalidates_fresh_report_and_manifest_identity() -> None:
    script = (REPO_ROOT / "scripts" / "deploy_abm_report.sh").read_text(encoding="utf-8")
    rollback = script.split("<<'REMOTE_ROLLBACK'", maxsplit=1)[1].split("REMOTE_ROLLBACK", maxsplit=1)[0]

    assert '"${PREVIOUS_REPORT_SHA_ARG}"' in script
    assert '"${PREVIOUS_MANIFEST_SHA_ARG}"' in script
    assert "restored_report_sha=" in rollback
    assert "restored_manifest_sha=" in rollback
    assert '"${restored_report_sha}" == "${previous_report_sha}"' in rollback
    assert '"${restored_manifest_sha}" == "${previous_manifest_sha}"' in rollback
    assert '"$(readlink -f "${remote_root}/current")" == "${previous_release}"' in rollback


def test_public_acceptance_accounts_for_every_contract_artifact() -> None:
    script = (REPO_ROOT / "scripts" / "deploy_abm_report.sh").read_text(encoding="utf-8")
    verifier = (REPO_ROOT / "scripts" / "verify_abm_public_artifact_bodies.py").read_text(
        encoding="utf-8"
    )

    assert "raw_public != sorted(raw_hashes)" in verifier
    assert "artifact.size_bytes <= _BODY_LIMIT_BYTES" in verifier
    assert "public artifact checksum mismatch" in verifier
    assert "full_body_count + manifest_bound_count == ARTIFACT_COUNT" in script


def test_success_emits_operational_time_and_fresh_acceptance_only_after_browser_gate() -> None:
    script = (REPO_ROOT / "scripts" / "deploy_abm_report.sh").read_text(encoding="utf-8")

    browser_gate = script.index("npx playwright test tests/playwright/deployed-abm-report.spec.ts")
    deployment_time = script.index("DEPLOYED_AT_UTC=", browser_gate)
    acceptance = script.index("Public acceptance: passed", deployment_time)
    assert browser_gate < deployment_time < acceptance
    assert "Deployment time (UTC): %s" in script
    assert "Fresh rollback release: %s" in script
