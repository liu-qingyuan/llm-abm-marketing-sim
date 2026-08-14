from __future__ import annotations

import hashlib
import importlib.util
import json
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


@pytest.mark.parametrize(
    "mutation",
    [
        {"sampling_status": "validation_run"},
        {"decision_execution_mode": "rule_based"},
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
        "production_deploy_eligible": True,
    }

    validator._require_formal_production(valid_v7)
    validator._require_formal_production(valid_v8)
    with pytest.raises(validator.ReleaseValidationError, match="formal production deployment"):
        validator._require_formal_production(valid_v7 | mutation)
    with pytest.raises(validator.ReleaseValidationError, match="formal production deployment"):
        validator._require_formal_production(valid_v8 | mutation)
    with pytest.raises(validator.ReleaseValidationError, match="formal production deployment"):
        validator._require_formal_production(
            valid_v8 | {"release_purpose": "concurrent_robustness_formal_research"}
        )


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


def test_deploy_consumes_validated_facts_and_checks_the_snapshot_before_ssh() -> None:
    script = (REPO_ROOT / "scripts" / "deploy_abm_report.sh").read_text(encoding="utf-8")

    facts_gate = script.index("--deployment-facts-output")
    snapshot_check = script.index('shasum -a 256 -c "${LOCAL_CHECKSUMS_FILE}"')
    first_ssh = script.index('if ssh "${DEPLOY_HOST}"')
    assert facts_gate < snapshot_check < first_ssh
    assert "--deployment-release-id" in script
    assert "--deployment-domain" in script
    assert "PUBLIC_ACCEPTANCE_ARTIFACTS_JSON" in script
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
    assert "validated_contract_sha" in remote


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


def test_public_acceptance_hashes_every_contract_artifact() -> None:
    script = (REPO_ROOT / "scripts" / "deploy_abm_report.sh").read_text(encoding="utf-8")

    assert 'for artifact, digest in sorted(facts["artifact_sha256"].items())' in script
    assert "public artifact checksum mismatch: ${artifact}" in script
    assert 'shasum -a 256 "${public_artifact}"' in script
