from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from llm_abm_sim import ConcurrentMessageExperimentConfig, ConcurrentMessageExperimentRunner
from llm_abm_sim.concurrent_message_report import write_concurrent_message_report_artifacts
from llm_abm_sim.prompt_field_summary import (
    CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
    CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
)
from llm_abm_sim.providers.openai_compatible import OpenAICompatibleDecisionAdapter, _OpenAISDKClient
from llm_abm_sim.schemas import ProviderLLMConfig, ReportConfig

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts" / "validate_abm_report_release.py"
_CONCURRENT_HELPERS_SPEC = importlib.util.spec_from_file_location(
    "concurrent_message_test_helpers",
    REPO_ROOT / "tests" / "integration" / "test_concurrent_message_experiment_runner.py",
)
if _CONCURRENT_HELPERS_SPEC is None or _CONCURRENT_HELPERS_SPEC.loader is None:
    raise RuntimeError("cannot load concurrent message test helpers")
_CONCURRENT_HELPERS = importlib.util.module_from_spec(_CONCURRENT_HELPERS_SPEC)
_CONCURRENT_HELPERS_SPEC.loader.exec_module(_CONCURRENT_HELPERS)
_SequencedEnvelopeClient = _CONCURRENT_HELPERS._SequencedEnvelopeClient
_make_concurrent_fixture = _CONCURRENT_HELPERS._make_concurrent_fixture
_provider_response = _CONCURRENT_HELPERS._provider_response


def _sdk_wrapper_stub(client: _SequencedEnvelopeClient) -> _OpenAISDKClient:
    sdk_client = object.__new__(_OpenAISDKClient)
    sdk_client.create_response = client.create_response  # type: ignore[attr-defined]
    return sdk_client


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_release(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "runs" / "approved"
    source.mkdir(parents=True)
    role_counts = {"seed": 1, "network_cohort": 1, "ordinary": 1}

    (source / "report.html").write_text("<title>Approved report</title>", encoding="utf-8")
    _write_json(
        source / "final_research_report_payload.json",
        {
            "schema_version": "final-research-ranking-report-payload-v4",
            "run": {
                "sampling_method": "seed_first_research_sample_v1",
                "sampling_status": "validation_run",
                "sample_size": 3,
            },
            "sample_role_counts": role_counts,
            "downloads": {
                "manifest": "artifact_manifest.json",
                "report": "report.html",
            },
        },
    )
    _write_json(
        source / "seed_first_sample_audit.json",
        {
            "schema_version": "seed-first-sample-audit-v1",
            "sampling_method": "seed_first_research_sample_v1",
            "sampling_status": "validation_run",
            "roles": {"counts": role_counts},
        },
    )
    _write_json(source / "field_lineage_catalog.json", {"fields": []})
    _write_json(source / "user_field_trace.json", {"records": []})
    _write_json(
        source / "sample_manifest.json",
        [
            {"user_id": "seed", "sample_role": "seed"},
            {"user_id": "network", "sample_role": "network_cohort"},
            {"user_id": "ordinary", "sample_role": "ordinary"},
        ],
    )
    _write_json(
        source / "artifact_manifest.json",
        {
            "manifest_version": "final-research-ranking-runtime-v2",
            "sampling_method": "seed_first_research_sample_v1",
            "sampling_status": "validation_run",
            "live_api_triggered": False,
            "sample_role_counts": role_counts,
            "counts": {"sample_users": 3},
            "artifacts": {
                "final_research_report": "report.html",
                "final_research_report_payload": "final_research_report_payload.json",
                "sample_manifest_json": "sample_manifest.json",
                "seed_first_sample_audit": "seed_first_sample_audit.json",
                "field_lineage_catalog": "field_lineage_catalog.json",
                "user_field_trace": "user_field_trace.json",
            },
        },
    )

    hashed_artifacts = [
        "report.html",
        "artifact_manifest.json",
        "final_research_report_payload.json",
        "seed_first_sample_audit.json",
        "field_lineage_catalog.json",
        "user_field_trace.json",
    ]
    contract = tmp_path / "release-contract.json"
    _write_json(
        contract,
        {
            "schema_version": "abm-report-release-contract-v1",
            "source_directory": "runs/approved",
            "payload_schema_version": "final-research-ranking-report-payload-v4",
            "manifest_version": "final-research-ranking-runtime-v2",
            "sampling_method": "seed_first_research_sample_v1",
            "sampling_status": "validation_run",
            "sample_role_counts": role_counts,
            "artifact_sha256": {name: _sha256(source / name) for name in hashed_artifacts},
        },
    )
    return source, contract


def _make_repo_release() -> tuple[tempfile.TemporaryDirectory[str], Path, Path]:
    temporary = tempfile.TemporaryDirectory(prefix="issue-78-release-", dir=REPO_ROOT / "tmp")
    source, contract = _make_release(Path(temporary.name))
    contract_document = json.loads(contract.read_text(encoding="utf-8"))
    contract_document["source_directory"] = source.relative_to(REPO_ROOT).as_posix()
    _write_json(contract, contract_document)
    return temporary, source, contract


def _validate(tmp_path: Path, source: Path, contract: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--repo-root",
            str(tmp_path),
            "--contract",
            str(contract),
            "--source-dir",
            str(source),
        ],
        text=True,
        capture_output=True,
    )


CONCURRENT_FORMAL_REQUESTED_MODEL = "gpt-5.4-mini"
CONCURRENT_FORMAL_OBSERVED_MODEL = "gpt-5.4-mini-2026-03-17"
CONCURRENT_FORMAL_STATUS = "persisted_seed_first_formal_run"
CONCURRENT_FORMAL_TITLE = "Concurrent Message Experiment Formal Report"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        import csv

        return list(csv.DictReader(handle))


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _rewrite_concurrent_manifest_hashes(run_dir: Path, *artifact_keys: str) -> None:
    manifest_path = run_dir / "artifact_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for artifact_key in artifact_keys:
        relative_path = manifest["artifacts"][artifact_key]
        manifest["sha256"][artifact_key] = _sha256(run_dir / relative_path)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _refresh_v4_contract_hashes(contract_path: Path, source: Path) -> None:
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["artifact_sha256"] = {
        relative_path: _sha256(source / relative_path)
        for relative_path in sorted(contract["artifact_sha256"].keys())
    }
    _write_json(contract_path, contract)



def _write_v4_release_contract(repo_root: Path, run_dir: Path, contract_path: Path) -> Path:
    manifest = json.loads((run_dir / "artifact_manifest.json").read_text(encoding="utf-8"))
    payload = json.loads((run_dir / "concurrent_message_report_payload.json").read_text(encoding="utf-8"))
    users = json.loads((run_dir / "concurrent_message_users.json").read_text(encoding="utf-8"))
    runtime = json.loads((run_dir / "concurrent_message_runtime.json").read_text(encoding="utf-8"))
    diagnostics = json.loads((run_dir / "concurrent_message_diagnostics.json").read_text(encoding="utf-8"))
    decision_trace = json.loads((run_dir / "concurrent_message_decision_trace.json").read_text(encoding="utf-8"))
    field_lineage = json.loads((run_dir / "concurrent_message_field_lineage.json").read_text(encoding="utf-8"))
    validation = json.loads((run_dir / "concurrent_validation.json").read_text(encoding="utf-8"))
    campaign_diagnostics = json.loads((run_dir / "concurrent_campaign_diagnostics.json").read_text(encoding="utf-8"))
    artifact_paths = {"artifact_manifest.json", *manifest["artifacts"].values()}
    contract = {
        "schema_version": "abm-report-release-contract-v4",
        "release_purpose": "formal_research",
        "source_directory": run_dir.relative_to(repo_root).as_posix(),
        "artifact_manifest_schema_version": manifest["schema_version"],
        "payload_schema_version": payload["schema_version"],
        "users_schema_version": users["schema_version"],
        "runtime_schema_version": runtime["schema_version"],
        "diagnostics_schema_version": diagnostics["schema_version"],
        "decision_trace_schema_version": decision_trace["schema_version"],
        "field_lineage_schema_version": field_lineage["schema_version"],
        "validation_schema_version": validation["schema_version"],
        "campaign_diagnostics_schema_version": campaign_diagnostics["schema_version"],
        "sampling_method": validation["sampling_method"],
        "sampling_status": validation["sampling_status"],
        "configuration_profile": validation["configuration"]["configuration_profile"],
        "primary_prompt_token": manifest["primary_prompt_token"],
        "shadow_prompt_token": manifest["shadow_prompt_token"],
        "production_deploy_eligible": validation["production_deploy_eligible"],
        "provider": "openai_compatible",
        "requested_model": CONCURRENT_FORMAL_REQUESTED_MODEL,
        "observed_model": CONCURRENT_FORMAL_OBSERVED_MODEL,
        "wire_api": "responses",
        "timeout_seconds": 30.0,
        "max_retries": 2,
        "fail_closed_action": "raise",
        "logical_primary_decision_opportunities": 1800,
        "logical_shadow_decision_opportunities": 1800,
        "logical_decision_opportunities": 3600,
        "below_delivery_capacity_pairs": 1200,
        "counts": validation["counts"],
        "per_message": validation["per_message"],
        "variant_provider_accounting": validation["variant_provider_accounting"],
        "artifact_sha256": {
            relative_path: _sha256(run_dir / relative_path) for relative_path in sorted(artifact_paths)
        },
    }
    _write_json(contract_path, contract)
    return contract_path



def _promote_concurrent_output_to_formal_release(run_dir: Path) -> None:
    config_snapshot = json.loads((run_dir / "config_snapshot.json").read_text(encoding="utf-8"))
    config_snapshot["sampling_status"] = CONCURRENT_FORMAL_STATUS
    config_snapshot["production_deploy_eligible"] = True
    config_snapshot["report"]["title"] = CONCURRENT_FORMAL_TITLE

    validation = json.loads((run_dir / "concurrent_validation.json").read_text(encoding="utf-8"))
    validation["sampling_status"] = CONCURRENT_FORMAL_STATUS
    validation["production_deploy_eligible"] = True
    validation["configuration"]["sampling_status"] = CONCURRENT_FORMAL_STATUS
    validation["configuration"]["production_deploy_eligible"] = True
    validation["configuration"]["report"]["title"] = CONCURRENT_FORMAL_TITLE

    sample_audit = json.loads((run_dir / "seed_first_sample_audit.json").read_text(encoding="utf-8"))
    sample_audit["sampling_status"] = CONCURRENT_FORMAL_STATUS

    _rewrite_concurrent_release_artifacts(
        run_dir,
        title=CONCURRENT_FORMAL_TITLE,
        config_snapshot=config_snapshot,
        validation_summary=validation,
        sample_audit=sample_audit,
    )



def _rewrite_concurrent_release_artifacts(
    run_dir: Path,
    *,
    title: str,
    config_snapshot: dict[str, object],
    validation_summary: dict[str, object],
    sample_audit: dict[str, object],
) -> None:
    write_concurrent_message_report_artifacts(
        run_dir,
        title=title,
        config_snapshot=config_snapshot,
        message_snapshot=json.loads((run_dir / "message_snapshot.json").read_text(encoding="utf-8")),
        sample_users=json.loads((run_dir / "sample_manifest.json").read_text(encoding="utf-8")),
        sample_audit=sample_audit,
        candidate_rows=_read_csv(run_dir / "concurrent_runtime_candidates.csv"),
        pair_rows=_read_csv(run_dir / "concurrent_runtime_pairs.csv"),
        terminal_rows=_read_csv(run_dir / "concurrent_runtime_terminal_rows.csv"),
        step_rows=json.loads((run_dir / "concurrent_runtime_steps.json").read_text(encoding="utf-8")),
        validation_summary=validation_summary,
        campaign_diagnostics=json.loads((run_dir / "concurrent_campaign_diagnostics.json").read_text(encoding="utf-8")),
    )



def _make_concurrent_v4_release(repo_root: Path, work_dir: Path) -> tuple[Path, Path]:
    dataset_dir = _make_concurrent_fixture(work_dir, user_count=1000, seed_user_count=20)
    primary_client = _SequencedEnvelopeClient(
        [
            _provider_response(
                '{"engage": false, "probability": 0.1, "reason": "primary formal", "confidence": 0.9, "action": "ignore"}',
                observed_model=CONCURRENT_FORMAL_OBSERVED_MODEL,
                input_usage=9,
                output_usage=4,
            )
            for _ in range(1800)
        ]
    )
    shadow_client = _SequencedEnvelopeClient(
        [
            _provider_response(
                '{"engage": false, "probability": 0.1, "reason": "shadow formal", "confidence": 0.9, "action": "ignore"}',
                observed_model=CONCURRENT_FORMAL_OBSERVED_MODEL,
                input_usage=8,
                output_usage=3,
            )
            for _ in range(1800)
        ]
    )
    primary_provider = OpenAICompatibleDecisionAdapter(
        ProviderLLMConfig(
            enabled=True,
            provider="openai_compatible",
            model=CONCURRENT_FORMAL_REQUESTED_MODEL,
            require_live_env=True,
            prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
            max_retries=2,
        ),
        sleep=lambda _delay: None,
    )
    shadow_provider = OpenAICompatibleDecisionAdapter(
        ProviderLLMConfig(
            enabled=True,
            provider="openai_compatible",
            model=CONCURRENT_FORMAL_REQUESTED_MODEL,
            require_live_env=True,
            prompt_version=CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
            max_retries=2,
        ),
        sleep=lambda _delay: None,
    )
    primary_provider._build_live_client = lambda: _sdk_wrapper_stub(primary_client)  # type: ignore[method-assign]
    shadow_provider._build_live_client = lambda: _sdk_wrapper_stub(shadow_client)  # type: ignore[method-assign]

    output_dir = ConcurrentMessageExperimentRunner(
        ConcurrentMessageExperimentConfig(
            dataset_dir=dataset_dir,
            report=ReportConfig(title=CONCURRENT_FORMAL_TITLE),
        ),
        primary_provider,
        shadow_provider,
    ).run_and_write(work_dir / "runs" / "synthetic-concurrent-v4-formal-fixture")
    contract_path = work_dir / "synthetic-concurrent-v4-formal-fixture.json"
    return output_dir, _write_v4_release_contract(repo_root, output_dir, contract_path)


@pytest.fixture(scope="module")
def concurrent_v4_release_baseline(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, Path]:
    repo_root = tmp_path_factory.mktemp("concurrent-v4-release")
    source, contract = _make_concurrent_v4_release(repo_root, repo_root)
    return repo_root, source, contract



def _copy_concurrent_release(repo_root: Path, baseline_source: Path, baseline_contract: Path) -> tuple[Path, Path]:
    copied_source = repo_root / "runs" / baseline_source.name
    shutil.copytree(baseline_source, copied_source)
    copied_contract = repo_root / baseline_contract.name
    contract_document = json.loads(baseline_contract.read_text(encoding="utf-8"))
    contract_document["source_directory"] = copied_source.relative_to(repo_root).as_posix()
    _write_json(copied_contract, contract_document)
    return copied_source, copied_contract



def _make_repo_concurrent_release_from_baseline(
    baseline_source: Path, baseline_contract: Path
) -> tuple[tempfile.TemporaryDirectory[str], Path, Path]:
    temporary = tempfile.TemporaryDirectory(prefix="issue-97-concurrent-v4-", dir=REPO_ROOT / "tmp")
    source_dir = Path(temporary.name) / "runs" / baseline_source.name
    shutil.copytree(baseline_source, source_dir)
    contract_path = Path(temporary.name) / baseline_contract.name
    contract_document = json.loads(baseline_contract.read_text(encoding="utf-8"))
    contract_document["source_directory"] = source_dir.relative_to(REPO_ROOT).as_posix()
    _write_json(contract_path, contract_document)
    return temporary, source_dir, contract_path


def test_release_validator_accepts_only_matching_persisted_evidence(tmp_path: Path):
    source, contract = _make_release(tmp_path)

    completed = _validate(tmp_path, source, contract)

    assert completed.returncode == 0, completed.stderr
    assert "Release evidence validated" in completed.stdout
    assert "seed_first_research_sample_v1" in completed.stdout


def test_release_v1_rejects_v5_validation_candidate(tmp_path: Path):
    source, contract_path = _make_release(tmp_path)
    payload_path = source / "final_research_report_payload.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    payload["schema_version"] = "final-research-ranking-report-payload-v5"
    _write_json(payload_path, payload)
    manifest_path = source / "artifact_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["manifest_version"] = "final-research-ranking-runtime-v3"
    _write_json(manifest_path, manifest)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["payload_schema_version"] = "final-research-ranking-report-payload-v5"
    contract["manifest_version"] = "final-research-ranking-runtime-v3"
    contract["artifact_sha256"]["final_research_report_payload.json"] = _sha256(payload_path)
    contract["artifact_sha256"]["artifact_manifest.json"] = _sha256(manifest_path)
    _write_json(contract_path, contract)

    completed = _validate(tmp_path, source, contract_path)

    assert completed.returncode == 1
    assert "v1 payload_schema_version" in completed.stderr


def test_release_validator_rejects_tampered_evidence(tmp_path: Path):
    source, contract = _make_release(tmp_path)
    (source / "report.html").write_text("tampered", encoding="utf-8")

    completed = _validate(tmp_path, source, contract)

    assert completed.returncode == 1
    assert "SHA-256 for report.html mismatch" in completed.stderr


def test_release_validator_rejects_a_different_run_directory(tmp_path: Path):
    source, contract = _make_release(tmp_path)
    historical_source = tmp_path / "runs" / "historical-20-13-967"
    historical_source.mkdir()

    completed = _validate(tmp_path, historical_source, contract)

    assert completed.returncode == 1
    assert "source directory mismatch" in completed.stderr


def test_release_validator_accepts_external_v1_contract_for_historical_validation(tmp_path: Path):
    repo_root = tmp_path / "repo"
    source, contract = _make_release(repo_root)
    external_contract = tmp_path / "historical-v1-contract.json"
    contract.replace(external_contract)

    completed = _validate(repo_root, source, external_contract)

    assert completed.returncode == 0, completed.stderr
    assert "abm-report-release-contract-v1" in completed.stdout


def test_release_validator_rejects_source_ancestor_symlink(tmp_path: Path):
    source, contract = _make_release(tmp_path)
    real_runs = tmp_path / "real-runs"
    source.parent.replace(real_runs)
    os.symlink(real_runs, tmp_path / "runs")
    symlinked_source = tmp_path / "runs" / "approved"

    completed = _validate(tmp_path, symlinked_source, contract)

    assert completed.returncode == 1
    assert "source directory must not contain symlink components" in completed.stderr


def test_release_validator_rejects_symlinked_artifacts(tmp_path: Path):
    source, contract = _make_release(tmp_path)
    catalog = source / "field_lineage_catalog.json"
    catalog.unlink()
    os.symlink(source / "user_field_trace.json", catalog)

    completed = _validate(tmp_path, source, contract)

    assert completed.returncode == 1
    assert "source directory contains symlink" in completed.stderr



def test_release_v4_accepts_synthetic_concurrent_formal_fixture(
    tmp_path: Path,
    concurrent_v4_release_baseline: tuple[Path, Path, Path],
):
    _, baseline_source, baseline_contract = concurrent_v4_release_baseline
    source, contract = _copy_concurrent_release(tmp_path, baseline_source, baseline_contract)

    completed = _validate(tmp_path, source, contract)

    assert completed.returncode == 0, completed.stderr
    assert "abm-report-release-contract-v4" in completed.stdout
    assert "persisted_seed_first_formal_run" in completed.stdout



def test_release_v4_rejects_crossed_prompt_token(
    tmp_path: Path,
    concurrent_v4_release_baseline: tuple[Path, Path, Path],
):
    _, baseline_source, baseline_contract = concurrent_v4_release_baseline
    source, contract = _copy_concurrent_release(tmp_path, baseline_source, baseline_contract)
    trace_path = source / "concurrent_message_decision_trace.json"
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    trace["primary_prompt_token"] = CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION
    trace["rows"][0]["primary_prompt_version"] = CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION
    trace_path.write_text(json.dumps(trace, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    _rewrite_concurrent_manifest_hashes(source, "decision_trace_json")
    _refresh_v4_contract_hashes(contract, source)

    completed = _validate(tmp_path, source, contract)

    assert completed.returncode == 1
    assert "prompt token" in completed.stderr or "crossed" in completed.stderr



def test_release_v4_rejects_extra_file_and_path_escape(
    tmp_path: Path,
    concurrent_v4_release_baseline: tuple[Path, Path, Path],
):
    _, baseline_source, baseline_contract = concurrent_v4_release_baseline
    source, contract = _copy_concurrent_release(tmp_path, baseline_source, baseline_contract)
    (source / "rogue.txt").write_text("rogue", encoding="utf-8")

    extra = _validate(tmp_path, source, contract)

    assert extra.returncode == 1
    assert "files outside the v4 artifact manifest" in extra.stderr or "unlisted artifacts" in extra.stderr

    escaped_root = tmp_path / "escape"
    escaped_root.mkdir()
    source, contract = _copy_concurrent_release(escaped_root, baseline_source, baseline_contract)
    manifest_path = source / "artifact_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"]["users_json"] = "../escape.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    contract_document = json.loads(contract.read_text(encoding="utf-8"))
    escaped_hash = contract_document["artifact_sha256"].pop("concurrent_message_users.json")
    contract_document["artifact_sha256"]["../escape.json"] = escaped_hash
    contract_document["artifact_sha256"]["artifact_manifest.json"] = _sha256(manifest_path)
    _write_json(contract, contract_document)

    escaped = _validate(escaped_root, source, contract)

    assert escaped.returncode == 1
    assert (
        "artifact path escape rejected" in escaped.stderr
        or "safe relative path" in escaped.stderr
        or "escapes the run directory" in escaped.stderr
    )



def test_release_v4_rejects_missing_terminal_row(
    tmp_path: Path,
    concurrent_v4_release_baseline: tuple[Path, Path, Path],
):
    import csv

    _, baseline_source, baseline_contract = concurrent_v4_release_baseline
    source, contract = _copy_concurrent_release(tmp_path, baseline_source, baseline_contract)
    terminal_path = source / "concurrent_runtime_terminal_rows.csv"
    rows = _read_csv(terminal_path)
    with terminal_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows[:-1])
    _rewrite_concurrent_manifest_hashes(source, "terminals_csv")
    _refresh_v4_contract_hashes(contract, source)

    completed = _validate(tmp_path, source, contract)

    assert completed.returncode == 1
    assert "terminal row count" in completed.stderr or "both primary and shadow entries" in completed.stderr



def test_release_v4_rejects_terminal_accounting_mismatch(
    tmp_path: Path,
    concurrent_v4_release_baseline: tuple[Path, Path, Path],
):
    import csv

    _, baseline_source, baseline_contract = concurrent_v4_release_baseline
    source, contract = _copy_concurrent_release(tmp_path, baseline_source, baseline_contract)
    terminal_path = source / "concurrent_runtime_terminal_rows.csv"
    rows = _read_csv(terminal_path)
    rows[0]["request_invocations"] = "2"
    with terminal_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    _rewrite_concurrent_manifest_hashes(source, "terminals_csv")
    _refresh_v4_contract_hashes(contract, source)

    completed = _validate(tmp_path, source, contract)

    assert completed.returncode == 1
    assert "terminal provider accounting primary mismatch" in completed.stderr



def test_release_v4_rejects_incomplete_usage_and_model_mismatch(
    tmp_path: Path,
    concurrent_v4_release_baseline: tuple[Path, Path, Path],
):
    import csv

    _, baseline_source, baseline_contract = concurrent_v4_release_baseline
    source, contract = _copy_concurrent_release(tmp_path, baseline_source, baseline_contract)
    terminal_path = source / "concurrent_runtime_terminal_rows.csv"
    rows = _read_csv(terminal_path)
    rows[0]["usage_complete"] = "false"
    rows[0]["usage_complete_response_count"] = "0"
    rows[0]["usage_missing_response_count"] = rows[0]["provider_response_count"]
    rows[0]["input_usage"] = ""
    rows[0]["output_usage"] = ""
    rows[0]["total_usage"] = ""
    with terminal_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    _rewrite_concurrent_manifest_hashes(source, "terminals_csv")
    _refresh_v4_contract_hashes(contract, source)

    usage_failed = _validate(tmp_path, source, contract)

    assert usage_failed.returncode == 1
    assert "complete usage" in usage_failed.stderr

    model_root = tmp_path / "model"
    model_root.mkdir()
    source, contract = _copy_concurrent_release(model_root, baseline_source, baseline_contract)
    terminal_path = source / "concurrent_runtime_terminal_rows.csv"
    rows = _read_csv(terminal_path)
    metadata = json.loads(rows[0]["provider_metadata"])
    metadata["model"] = "other-model"
    rows[0]["provider_metadata"] = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    rows[0]["observed_model_counts"] = json.dumps({"other-observed-model": 1}, ensure_ascii=False, sort_keys=True)
    with terminal_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    _rewrite_concurrent_manifest_hashes(source, "terminals_csv")
    _refresh_v4_contract_hashes(contract, source)

    model_failed = _validate(model_root, source, contract)

    assert model_failed.returncode == 1
    assert "observed_model" in model_failed.stderr or "requested model" in model_failed.stderr



def test_deploy_rejects_v4_validation_candidate_before_any_remote_action(
    tmp_path: Path,
    concurrent_v4_release_baseline: tuple[Path, Path, Path],
):
    deploy_script = REPO_ROOT / "scripts" / "deploy_abm_report.sh"
    _, baseline_source, baseline_contract = concurrent_v4_release_baseline
    temporary, source, contract = _make_repo_concurrent_release_from_baseline(baseline_source, baseline_contract)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ssh_marker = tmp_path / "ssh-invoked"
    ssh = bin_dir / "ssh"
    ssh.write_text(
        '#!/usr/bin/env bash\nprintf invoked > "${FAKE_SSH_MARKER}"\nexit 0\n',
        encoding="utf-8",
    )
    ssh.chmod(0o755)

    config_snapshot = json.loads((source / "config_snapshot.json").read_text(encoding="utf-8"))
    config_snapshot["sampling_status"] = "validation_run"
    config_snapshot["production_deploy_eligible"] = False
    config_snapshot["report"]["title"] = "Concurrent Message Experiment Validation"
    validation = json.loads((source / "concurrent_validation.json").read_text(encoding="utf-8"))
    validation["sampling_status"] = "validation_run"
    validation["production_deploy_eligible"] = False
    validation["configuration"]["sampling_status"] = "validation_run"
    validation["configuration"]["production_deploy_eligible"] = False
    validation["configuration"]["report"]["title"] = "Concurrent Message Experiment Validation"
    sample_audit = json.loads((source / "seed_first_sample_audit.json").read_text(encoding="utf-8"))
    sample_audit["sampling_status"] = "validation_run"
    _rewrite_concurrent_release_artifacts(
        source,
        title="Concurrent Message Experiment Validation",
        config_snapshot=config_snapshot,
        validation_summary=validation,
        sample_audit=sample_audit,
    )
    _refresh_v4_contract_hashes(contract, source)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
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
            "v4-validation-must-not-deploy",
        ],
        text=True,
        capture_output=True,
        env=env,
        cwd=REPO_ROOT,
    )

    try:
        assert completed.returncode != 0
        assert not ssh_marker.exists()
        assert "release validation error" in completed.stderr or "sampling_status" in completed.stderr
    finally:
        temporary.cleanup()


def test_deploy_interface_requires_explicit_contract_source_and_release(tmp_path: Path):
    deploy_script = REPO_ROOT / "scripts" / "deploy_abm_report.sh"
    env = os.environ.copy()
    env["ABM_REPORT_SOURCE_DIR"] = str(tmp_path / "missing")

    completed = subprocess.run([str(deploy_script)], text=True, capture_output=True, env=env)

    assert completed.returncode != 0
    assert "--contract" in completed.stderr
    assert "--source-dir" in completed.stderr
    assert "--release-id" in completed.stderr


def test_deploy_rejects_v1_contract_before_any_remote_action(tmp_path: Path):
    deploy_script = REPO_ROOT / "scripts" / "deploy_abm_report.sh"
    temporary, source, contract = _make_repo_release()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ssh_marker = tmp_path / "ssh-invoked"
    ssh = bin_dir / "ssh"
    ssh.write_text(
        '#!/usr/bin/env bash\nprintf invoked > "${FAKE_SSH_MARKER}"\nexit 0\n',
        encoding="utf-8",
    )
    ssh.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
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
            "v1-must-not-deploy",
        ],
        text=True,
        capture_output=True,
        env=env,
        cwd=REPO_ROOT,
    )

    try:
        assert completed.returncode != 0
        assert "formal production deployment requires abm-report-release-contract-v2" in completed.stderr
        assert not ssh_marker.exists()
    finally:
        temporary.cleanup()


def test_deploy_stops_on_validator_failure_before_any_remote_action(tmp_path: Path):
    deploy_script = REPO_ROOT / "scripts" / "deploy_abm_report.sh"
    source = tmp_path / "candidate"
    source.mkdir()
    (source / "report.html").write_text("candidate", encoding="utf-8")
    (source / "artifact_manifest.json").write_text("{}", encoding="utf-8")
    contract = tmp_path / "formal-contract.json"
    contract.write_text("{}", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    validator_log = tmp_path / "validator-args"
    ssh_marker = tmp_path / "ssh-invoked"
    snapshot_root = tmp_path / "snapshots"
    snapshot_root.mkdir()
    python = bin_dir / "python"
    python.write_text(
        '#!/usr/bin/env bash\nprintf \'%s\\n\' "$*" > "${FAKE_VALIDATOR_LOG}"\nexit 19\n',
        encoding="utf-8",
    )
    python.chmod(0o755)
    ssh = bin_dir / "ssh"
    ssh.write_text(
        '#!/usr/bin/env bash\nprintf invoked > "${FAKE_SSH_MARKER}"\nexit 0\n',
        encoding="utf-8",
    )
    ssh.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "ABM_DEPLOY_PYTHON": str(python),
            "FAKE_VALIDATOR_LOG": str(validator_log),
            "FAKE_SSH_MARKER": str(ssh_marker),
            "TMPDIR": str(snapshot_root),
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
            "rejected-candidate",
        ],
        text=True,
        capture_output=True,
        env=env,
        cwd=REPO_ROOT,
    )

    assert completed.returncode == 19
    validator_args = validator_log.read_text(encoding="utf-8")
    assert f"--contract {contract}" in validator_args
    assert "--require-formal-production" in validator_args
    assert not ssh_marker.exists()
    assert list(snapshot_root.iterdir()) == []


def test_deploy_rejects_symlink_contract_before_any_remote_action(tmp_path: Path):
    deploy_script = REPO_ROOT / "scripts" / "deploy_abm_report.sh"
    temporary, source, contract = _make_repo_release()
    symlink_contract = Path(temporary.name) / "symlink-contract.json"
    os.symlink(contract, symlink_contract)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ssh_marker = tmp_path / "ssh-invoked"
    ssh = bin_dir / "ssh"
    ssh.write_text(
        '#!/usr/bin/env bash\nprintf invoked > "${FAKE_SSH_MARKER}"\nexit 0\n',
        encoding="utf-8",
    )
    ssh.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "ABM_DEPLOY_PYTHON": sys.executable,
            "FAKE_SSH_MARKER": str(ssh_marker),
        }
    )

    completed = subprocess.run(
        [
            str(deploy_script),
            "--contract",
            str(symlink_contract),
            "--source-dir",
            str(source),
            "--release-id",
            "symlink-must-not-deploy",
        ],
        text=True,
        capture_output=True,
        env=env,
        cwd=REPO_ROOT,
    )

    try:
        assert completed.returncode != 0
        assert "release contract must not contain symlink components" in completed.stderr
        assert not ssh_marker.exists()
    finally:
        temporary.cleanup()


def test_deploy_preserves_candidate_checks_atomic_switch_and_transaction_rollback_order():
    deploy_script = REPO_ROOT / "scripts" / "deploy_abm_report.sh"
    script = deploy_script.read_text(encoding="utf-8")
    remote_transaction = script.split("<<'REMOTE_DEPLOY'", maxsplit=1)[1].split("REMOTE_DEPLOY", maxsplit=1)[0]

    candidate_started = remote_transaction.index("docker run -d")
    candidate_name_bound = remote_transaction.index('--name "${candidate_name}"', candidate_started)
    candidate_healthy = remote_transaction.index('wait_healthy "${candidate_name}"', candidate_started)
    candidate_report_checked = remote_transaction.index(
        'docker exec "${candidate_name}" test -f /usr/share/nginx/html/report.html',
        candidate_healthy,
    )
    current_switched = remote_transaction.index('atomic_current "${remote_release}"', candidate_report_checked)
    host_guard = remote_transaction.index('grep -Fq "${managed_marker}" "${site_available}"')
    host_config_checked = remote_transaction.index("nginx -t", current_switched)
    rollback_started = remote_transaction.index("rollback() {")
    rollback_previous = remote_transaction.index('atomic_current "${previous_release}"', rollback_started)

    assert host_guard < candidate_started < candidate_name_bound < candidate_healthy < candidate_report_checked
    assert candidate_report_checked < current_switched
    assert current_switched < host_config_checked
    assert rollback_started < rollback_previous
    assert "trap finish EXIT" in remote_transaction


def test_deploy_rolls_back_when_public_acceptance_fails(tmp_path: Path):
    deploy_script = REPO_ROOT / "scripts" / "deploy_abm_report.sh"
    source = tmp_path / "approved-run"
    source.mkdir()
    (source / "report.html").write_text("approved", encoding="utf-8")
    (source / "artifact_manifest.json").write_text("{}", encoding="utf-8")
    contract = tmp_path / "formal-contract.json"
    contract.write_text(
        json.dumps(
            {
                "schema_version": "abm-report-release-contract-v2",
                "artifact_sha256": {
                    "artifact_manifest.json": "0" * 64,
                    "report.html": "0" * 64,
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ssh_count = tmp_path / "ssh-count"
    ssh_log = tmp_path / "ssh-log"
    upload_archive = tmp_path / "uploaded-release.tar.gz"
    snapshot_root = tmp_path / "snapshots"
    snapshot_root.mkdir()
    shims = {
        "python": f"""#!/usr/bin/env bash
set -euo pipefail
if [[ \"$1\" == \"-\" ]]; then
  exec {sys.executable} \"$@\"
fi
source_dir=""
while (( $# > 0 )); do
  if [[ "$1" == "--source-dir" ]]; then
    source_dir="$2"
    shift 2
  else
    shift
  fi
done
printf 'tampered after validation' > "${{source_dir}}/report.html"
exit 0
""",
        "curl": "#!/usr/bin/env bash\nexit 22\n",
        "sleep": "#!/usr/bin/env bash\nexit 0\n",
        "ssh": """#!/usr/bin/env bash
set -euo pipefail
count=0
[[ ! -f "${FAKE_SSH_COUNT}" ]] || count="$(<"${FAKE_SSH_COUNT}")"
count=$((count + 1))
printf '%s' "${count}" > "${FAKE_SSH_COUNT}"
printf '%s %s\n' "${count}" "$*" >> "${FAKE_SSH_LOG}"
if [[ "${count}" == "3" ]]; then
  cat > "${FAKE_UPLOAD_ARCHIVE}"
else
  while IFS= read -r _line; do :; done
fi
if [[ "${count}" == "1" ]]; then
  printf '%s\n' '/tmp/abm-report/releases/previous'
fi
exit 0
""",
    }
    for name, body in shims.items():
        path = bin_dir / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "ABM_DEPLOY_PYTHON": str(bin_dir / "python"),
            "ABM_DEPLOY_HOST": "test-host",
            "ABM_DEPLOY_DOMAIN": "abm.example.test",
            "ABM_DEPLOY_REMOTE_ROOT": "/tmp/abm-report",
            "FAKE_SSH_COUNT": str(ssh_count),
            "FAKE_SSH_LOG": str(ssh_log),
            "FAKE_UPLOAD_ARCHIVE": str(upload_archive),
            "TMPDIR": str(snapshot_root),
        }
    )

    completed = subprocess.run(
        [
            "bash",
            str(deploy_script),
            "--contract",
            str(contract),
            "--source-dir",
            str(source),
            "--release-id",
            "candidate",
        ],
        text=True,
        capture_output=True,
        env=env,
        cwd=REPO_ROOT,
    )

    assert completed.returncode != 0
    assert "Public acceptance failed; restoring previous release" in completed.stderr
    assert ssh_count.read_text(encoding="utf-8") == "5"
    assert "/tmp/abm-report/releases/previous" in ssh_log.read_text(encoding="utf-8").splitlines()[-1]
    uploaded_report = subprocess.run(
        ["tar", "-xOzf", str(upload_archive), "./report.html"],
        check=True,
        text=True,
        capture_output=True,
    )
    assert uploaded_report.stdout == "approved"
    assert (source / "report.html").read_text(encoding="utf-8") == "tampered after validation"
    assert list(snapshot_root.iterdir()) == []
