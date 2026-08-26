from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import cast

import pytest

from llm_abm_sim.report_deployment import (
    DEPLOYMENT_AUTHORIZATION_SCHEMA_V1,
    DEPLOYMENT_READINESS_SCHEMA_V1,
    DeploymentAuthorizationError,
    DeploymentAuthorizationRequired,
    DeploymentTarget,
    authorize_deployment,
    verify_fresh_rollback_identity,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOYMENT_VALIDATOR = REPO_ROOT / "scripts" / "validate_abm_report_deployment.py"


def _v13_facts() -> dict[str, object]:
    source_identity = "a" * 64
    release_id = "formal-two-stage-v13"
    return {
        "schema_version": "abm-report-deployment-facts-v1",
        "release_contract_schema_version": "abm-report-release-contract-v13",
        "report_kind": "full-pool",
        "release_id": release_id,
        "canonical_endpoint": "https://abm.q1ngyuan.top/",
        "canonical_domain": "abm.q1ngyuan.top",
        "contract_sha256": "b" * 64,
        "release_identity_sha256": "c" * 64,
        "report_sha256": "d" * 64,
        "manifest_sha256": "e" * 64,
        "artifact_sha256": {
            "artifact_manifest.json": "e" * 64,
            "report.html": "d" * 64,
        },
        "approved_downloads": [],
        "public_acceptance_artifacts": [
            "artifact_manifest.json",
            "report.html",
        ],
        "realized_source_identity": source_identity,
        "release_readiness": {
            "schema_version": "full-pool-v13-release-readiness-v1",
            "release_id": release_id,
            "release_contract_schema": "abm-report-release-contract-v13",
            "realized_source_identity": source_identity,
            "canonical_endpoint": "https://abm.q1ngyuan.top/",
            "provider_calls_during_promotion": 0,
            "image_generation_triggered": False,
            "canonical_deployment_triggered": False,
            "operational_authorization_required": True,
            "deployment_authorized": False,
            "public_acceptance_recorded": False,
        },
        "composite_provider_accounting": {
            "schema_version": "full-pool-two-stage-provider-accounting-v1",
            "upstream_live_api_triggered": True,
            "upstream_formal_research_evidence": True,
            "upstream_production_deploy_eligible": True,
            "realization_provider_calls": 0,
            "realization_live_api_triggered": False,
            "composite_live_api_triggered": True,
            "composite_zero_provider_formal": False,
        },
    }


def _target() -> DeploymentTarget:
    return DeploymentTarget(
        canonical_endpoint="https://abm.q1ngyuan.top/",
        host="BandwagonHost2",
        remote_root="/opt/llm-abm-marketing-sim-report",
        port=18083,
        container_name="abm-research-report",
        image="nginx:1.27-alpine",
    )


def test_v13_missing_authorization_returns_exact_readiness_without_a_plan(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "deployment-plan.json"

    with pytest.raises(DeploymentAuthorizationRequired) as captured:
        authorize_deployment(
            deployment_facts=_v13_facts(),
            target=_target(),
            authorization_path=None,
            plan_output=plan,
        )

    readiness = captured.value.readiness
    assert readiness == {
        "schema_version": DEPLOYMENT_READINESS_SCHEMA_V1,
        "status": "awaiting_operational_authorization",
        "authorization_schema_version": DEPLOYMENT_AUTHORIZATION_SCHEMA_V1,
        "release_contract_schema": "abm-report-release-contract-v13",
        "contract_sha256": "b" * 64,
        "release_id": "formal-two-stage-v13",
        "release_identity_sha256": "c" * 64,
        "realized_source_identity": "a" * 64,
        "canonical_endpoint": "https://abm.q1ngyuan.top/",
        "report_sha256": "d" * 64,
        "manifest_sha256": "e" * 64,
        "artifact_count": 2,
        "release_readiness": _v13_facts()["release_readiness"],
        "deployment_target": _target().as_document(),
        "rollback_identity_required": True,
        "remote_connection_authorized": False,
        "deployment_authorized": False,
    }
    assert not plan.exists()


def _authorization_document() -> dict[str, object]:
    return {
        "schema_version": DEPLOYMENT_AUTHORIZATION_SCHEMA_V1,
        "authorization_kind": "explicit_operational_deployment",
        "authorization_status": "approved",
        "authorization_reference": "github:#234:explicit-operational-approval",
        "release_contract_schema": "abm-report-release-contract-v13",
        "contract_sha256": "b" * 64,
        "release_id": "formal-two-stage-v13",
        "release_identity_sha256": "c" * 64,
        "realized_source_identity": "a" * 64,
        "canonical_endpoint": "https://abm.q1ngyuan.top/",
        "deployment_target": _target().as_document(),
        "rollback_identity": {
            "schema_version": "abm-report-fresh-rollback-identity-v1",
            "release_id": "canonical-v12",
            "remote_release": ("/opt/llm-abm-marketing-sim-report/releases/canonical-v12"),
            "report_sha256": "f" * 64,
            "manifest_sha256": "0" * 64,
        },
    }


def test_v13_authorization_closes_a_hash_bound_plan(tmp_path: Path) -> None:
    authorization_path = tmp_path / "authorization.json"
    authorization_bytes = (
        json.dumps(
            _authorization_document(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    authorization_path.write_bytes(authorization_bytes)
    plan_path = tmp_path / "deployment-plan.json"

    plan = authorize_deployment(
        deployment_facts=_v13_facts(),
        target=_target(),
        authorization_path=authorization_path,
        plan_output=plan_path,
    )

    assert plan["schema_version"] == "abm-report-deployment-plan-v1"
    assert plan["authorization_required"] is True
    assert plan["authorization_reference"] == "github:#234:explicit-operational-approval"
    assert plan["authorization_sha256"] == hashlib.sha256(authorization_bytes).hexdigest()
    assert plan["release_contract_schema"] == "abm-report-release-contract-v13"
    assert plan["release_id"] == "formal-two-stage-v13"
    assert plan["realized_source_identity"] == "a" * 64
    assert plan["deployment_target"] == _target().as_document()
    assert plan["rollback_identity"] == _authorization_document()["rollback_identity"]
    assert json.loads(plan_path.read_text(encoding="utf-8")) == plan


@pytest.mark.parametrize(
    "mutation",
    [
        "contract",
        "release",
        "source",
        "endpoint",
        "host",
        "root",
        "topology",
        "rollback",
        "status",
        "extra",
    ],
)
def test_v13_authorization_rejects_crossed_release_target_and_rollback_facts(
    tmp_path: Path,
    mutation: str,
) -> None:
    document = deepcopy(_authorization_document())
    if mutation == "contract":
        document["contract_sha256"] = "1" * 64
    elif mutation == "release":
        document["release_id"] = "other-release"
    elif mutation == "source":
        document["realized_source_identity"] = "2" * 64
    elif mutation == "endpoint":
        document["canonical_endpoint"] = "https://other.example.test/"
    elif mutation in {"host", "root", "topology"}:
        target = cast(dict[str, object], document["deployment_target"])
        field, value = {
            "host": ("host", "OtherHost"),
            "root": ("remote_root", "/opt/other"),
            "topology": ("topology", "direct-report-overwrite"),
        }[mutation]
        target[field] = value
    elif mutation == "rollback":
        rollback = cast(dict[str, object], document["rollback_identity"])
        rollback["remote_release"] = "/opt/llm-abm-marketing-sim-report/releases/other-release"
    elif mutation == "status":
        document["authorization_status"] = "collaborator_confirmed"
    else:
        document["release_readiness_is_authorization"] = True
    authorization_path = tmp_path / f"authorization-{mutation}.json"
    authorization_path.write_text(
        json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        DeploymentAuthorizationError,
        match="authorization|rollback|release|target|crossed|unexpected",
    ):
        authorize_deployment(
            deployment_facts=_v13_facts(),
            target=_target(),
            authorization_path=authorization_path,
            plan_output=tmp_path / f"plan-{mutation}.json",
        )


def test_v13_authorization_rejects_noncanonical_or_symlink_artifacts(
    tmp_path: Path,
) -> None:
    pretty = tmp_path / "pretty-authorization.json"
    pretty.write_text(json.dumps(_authorization_document(), indent=2) + "\n", encoding="utf-8")
    symlink = tmp_path / "authorization-link.json"
    symlink.symlink_to(pretty)

    for authorization_path in (pretty, symlink):
        with pytest.raises(
            DeploymentAuthorizationError,
            match="canonical JSON|regular non-symlink",
        ):
            authorize_deployment(
                deployment_facts=_v13_facts(),
                target=_target(),
                authorization_path=authorization_path,
                plan_output=tmp_path / f"{authorization_path.stem}-plan.json",
            )


def test_fresh_remote_readback_must_equal_the_authorized_rollback_identity(
    tmp_path: Path,
) -> None:
    authorization_path = tmp_path / "authorization.json"
    authorization_path.write_text(
        json.dumps(
            _authorization_document(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    plan = authorize_deployment(
        deployment_facts=_v13_facts(),
        target=_target(),
        authorization_path=authorization_path,
        plan_output=tmp_path / "plan.json",
    )
    expected = _authorization_document()["rollback_identity"]
    assert isinstance(expected, dict)

    assert verify_fresh_rollback_identity(plan=plan, readback=expected) == expected
    for mutation in (
        {"release_id": "other-release"},
        {"remote_release": "/opt/llm-abm-marketing-sim-report/releases/other-release"},
        {"report_sha256": "1" * 64},
        {"manifest_sha256": "2" * 64},
    ):
        with pytest.raises(
            DeploymentAuthorizationError,
            match="fresh rollback|rollback identity|readback",
        ):
            verify_fresh_rollback_identity(
                plan=plan,
                readback=expected | mutation,
            )


def test_deployment_cli_emits_machine_readable_readiness_when_authorization_is_missing(
    tmp_path: Path,
) -> None:
    facts_path = tmp_path / "deployment-facts.json"
    facts_path.write_text(
        json.dumps(
            _v13_facts(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    plan_path = tmp_path / "plan.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(DEPLOYMENT_VALIDATOR),
            "preflight",
            "--deployment-facts",
            str(facts_path),
            "--canonical-endpoint",
            "https://abm.q1ngyuan.top/",
            "--host",
            "BandwagonHost2",
            "--remote-root",
            "/opt/llm-abm-marketing-sim-report",
            "--port",
            "18083",
            "--container-name",
            "abm-research-report",
            "--image",
            "nginx:1.27-alpine",
            "--plan-output",
            str(plan_path),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 2
    prefix = "deployment authorization required: "
    assert completed.stderr.startswith(prefix)
    assert json.loads(completed.stderr.removeprefix(prefix)) == {
        **authorize_readiness_for_test(),
    }
    assert not plan_path.exists()


def authorize_readiness_for_test() -> dict[str, object]:
    with pytest.raises(DeploymentAuthorizationRequired) as captured:
        authorize_deployment(
            deployment_facts=_v13_facts(),
            target=_target(),
            authorization_path=None,
            plan_output=Path("unused-plan.json"),
        )
    return captured.value.readiness


def test_deployment_cli_validates_authorization_and_fresh_readback(
    tmp_path: Path,
) -> None:
    facts_path = tmp_path / "facts.json"
    authorization_path = tmp_path / "authorization.json"
    readback_path = tmp_path / "readback.json"
    for path, document in (
        (facts_path, _v13_facts()),
        (authorization_path, _authorization_document()),
        (readback_path, _authorization_document()["rollback_identity"]),
    ):
        path.write_text(
            json.dumps(
                document,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
    plan_path = tmp_path / "plan.json"
    target_args = [
        "--canonical-endpoint",
        "https://abm.q1ngyuan.top/",
        "--host",
        "BandwagonHost2",
        "--remote-root",
        "/opt/llm-abm-marketing-sim-report",
        "--port",
        "18083",
        "--container-name",
        "abm-research-report",
        "--image",
        "nginx:1.27-alpine",
    ]

    preflight = subprocess.run(
        [
            sys.executable,
            str(DEPLOYMENT_VALIDATOR),
            "preflight",
            "--deployment-facts",
            str(facts_path),
            "--authorization",
            str(authorization_path),
            *target_args,
            "--plan-output",
            str(plan_path),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    readback = subprocess.run(
        [
            sys.executable,
            str(DEPLOYMENT_VALIDATOR),
            "verify-readback",
            "--plan",
            str(plan_path),
            "--readback",
            str(readback_path),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert preflight.returncode == 0, preflight.stderr
    assert "Deployment authorization validated" in preflight.stdout
    assert readback.returncode == 0, readback.stderr
    assert "Fresh rollback identity validated" in readback.stdout


def test_deploy_script_stops_missing_v13_authorization_before_ssh(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    deploy_script = scripts / "deploy_abm_report.sh"
    shutil.copy2(REPO_ROOT / "scripts" / "deploy_abm_report.sh", deploy_script)
    shutil.copy2(DEPLOYMENT_VALIDATOR, scripts / DEPLOYMENT_VALIDATOR.name)

    source = repo / "release"
    source.mkdir()
    (source / "report.html").write_text("candidate\n", encoding="utf-8")
    (source / "artifact_manifest.json").write_text("{}\n", encoding="utf-8")
    facts = _v13_facts()
    facts["artifact_sha256"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in source.iterdir()}
    facts["report_sha256"] = facts["artifact_sha256"]["report.html"]
    facts["manifest_sha256"] = facts["artifact_sha256"]["artifact_manifest.json"]
    fake_release_validator = scripts / "validate_abm_report_release.py"
    fake_release_validator.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "import sys\n"
        f"facts = json.loads({json.dumps(json.dumps(facts))})\n"
        "args = sys.argv[1:]\n"
        "output = args[args.index('--deployment-facts-output') + 1]\n"
        "with open(output, 'w', encoding='utf-8') as stream:\n"
        "    json.dump(facts, stream, ensure_ascii=False, sort_keys=True, separators=(',', ':'))\n"
        "    stream.write('\\n')\n",
        encoding="utf-8",
    )
    fake_release_validator.chmod(0o755)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    ssh_marker = tmp_path / "ssh-invoked"
    ssh = fake_bin / "ssh"
    ssh.write_text(
        '#!/usr/bin/env bash\nprintf invoked > "${FAKE_SSH_MARKER}"\nexit 0\n',
        encoding="utf-8",
    )
    ssh.chmod(0o755)
    contract = repo / "contract.json"
    contract.write_text("{}\n", encoding="utf-8")
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
            "formal-two-stage-v13",
        ],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "deployment authorization required:" in completed.stderr
    assert not ssh_marker.exists()


def test_v13_authorization_and_fresh_readback_gates_precede_remote_writes() -> None:
    script = (REPO_ROOT / "scripts" / "deploy_abm_report.sh").read_text(encoding="utf-8")

    authorization_gate = script.index("validate_abm_report_deployment.py")
    first_ssh = script.index('if ssh "${DEPLOY_HOST}"')
    readback_gate = script.index("verify-readback")
    first_remote_write = script.index('REMOTE_RELEASE_STATE="$(ssh "${DEPLOY_HOST}"')
    assert authorization_gate < first_ssh < readback_gate < first_remote_write
