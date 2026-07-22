from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
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
    contract.write_text("{}", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ssh_count = tmp_path / "ssh-count"
    ssh_log = tmp_path / "ssh-log"
    upload_archive = tmp_path / "uploaded-release.tar.gz"
    snapshot_root = tmp_path / "snapshots"
    snapshot_root.mkdir()
    shims = {
        "python": """#!/usr/bin/env bash
set -euo pipefail
source_dir=""
while (( $# > 0 )); do
  if [[ "$1" == "--source-dir" ]]; then
    source_dir="$2"
    shift 2
  else
    shift
  fi
done
printf 'tampered after validation' > "${source_dir}/report.html"
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
