from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts" / "validate_abm_report_release.py"


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


def test_release_validator_accepts_only_matching_persisted_evidence(tmp_path: Path):
    source, contract = _make_release(tmp_path)

    completed = _validate(tmp_path, source, contract)

    assert completed.returncode == 0, completed.stderr
    assert "Release evidence validated" in completed.stdout
    assert "seed_first_research_sample_v1" in completed.stdout


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


def test_release_validator_rejects_symlinked_artifacts(tmp_path: Path):
    source, contract = _make_release(tmp_path)
    catalog = source / "field_lineage_catalog.json"
    catalog.unlink()
    os.symlink(source / "user_field_trace.json", catalog)

    completed = _validate(tmp_path, source, contract)

    assert completed.returncode == 1
    assert "source directory contains symlink" in completed.stderr


def test_deploy_interface_requires_explicit_source_and_release(tmp_path: Path):
    deploy_script = REPO_ROOT / "scripts" / "deploy_abm_report.sh"
    env = os.environ.copy()
    env["ABM_REPORT_SOURCE_DIR"] = str(tmp_path / "missing")

    completed = subprocess.run([str(deploy_script)], text=True, capture_output=True, env=env)

    assert completed.returncode != 0
    assert "--source-dir" in completed.stderr
    assert "--release-id" in completed.stderr


def test_deploy_rolls_back_when_public_acceptance_fails(tmp_path: Path):
    deploy_script = REPO_ROOT / "scripts" / "deploy_abm_report.sh"
    source = tmp_path / "approved-run"
    source.mkdir()
    (source / "report.html").write_text("approved", encoding="utf-8")
    (source / "artifact_manifest.json").write_text("{}", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ssh_count = tmp_path / "ssh-count"
    ssh_log = tmp_path / "ssh-log"
    shims = {
        "python": "#!/usr/bin/env bash\nexit 0\n",
        "tar": "#!/usr/bin/env bash\nexit 0\n",
        "curl": "#!/usr/bin/env bash\nexit 22\n",
        "sleep": "#!/usr/bin/env bash\nexit 0\n",
        "ssh": """#!/usr/bin/env bash
set -euo pipefail
count=0
[[ ! -f "${FAKE_SSH_COUNT}" ]] || count="$(<"${FAKE_SSH_COUNT}")"
count=$((count + 1))
printf '%s' "${count}" > "${FAKE_SSH_COUNT}"
printf '%s %s\n' "${count}" "$*" >> "${FAKE_SSH_LOG}"
while IFS= read -r _line; do :; done
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
        }
    )

    completed = subprocess.run(
        [
            "bash",
            str(deploy_script),
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
