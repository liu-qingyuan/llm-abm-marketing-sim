from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
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
    with pytest.raises(validator.ReleaseValidationError, match="formal production deployment"):
        validator._require_formal_production(valid_v8 | {"live_api_triggered": False})
    with pytest.raises(validator.ReleaseValidationError, match="formal production deployment"):
        validator._require_formal_production(valid_v8 | {"schema_version": "abm-report-release-contract-v7"})
    with pytest.raises(validator.ReleaseValidationError, match="formal production deployment"):
        validator._require_formal_production(valid_v8 | {"schema_version": "unknown-v9"})


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


@pytest.mark.parametrize("failure_mode", ["candidate-health", "post-switch"])
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
      if [[ "${FAKE_DOCKER_MODE}" == "post-switch" && "${count}" == "1" ]]; then
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
    if failure_mode == "post-switch":
        assert compose_count.exists(), completed.stderr
        assert compose_count.read_text(encoding="utf-8") == "2"
    else:
        assert not compose_count.exists()


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
    assert 'grep -Fq "<meta name=\\"abm-release-id\\" content=\\"${release_id}\\">"' in remote
    assert (
        'grep -Fq "<meta name=\\"abm-release-contract\\" content=\\"${release_contract_schema}\\">"'
        in remote
    )
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


def test_success_emits_operational_time_and_fresh_acceptance_only_after_browser_gate() -> None:
    script = (REPO_ROOT / "scripts" / "deploy_abm_report.sh").read_text(encoding="utf-8")

    browser_gate = script.index("npx playwright test tests/playwright/deployed-abm-report.spec.ts")
    deployment_time = script.index("DEPLOYED_AT_UTC=", browser_gate)
    acceptance = script.index("Public acceptance: passed", deployment_time)
    assert browser_gate < deployment_time < acceptance
    assert "Deployment time (UTC): %s" in script
    assert "Fresh rollback release: %s" in script
