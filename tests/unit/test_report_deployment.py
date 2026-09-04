from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import cast

import pytest

from llm_abm_sim.report_deployment import (
    DEPLOYMENT_AUTHORIZATION_SCHEMA_V1,
    DEPLOYMENT_AUTHORIZATION_SCHEMA_V14,
    DEPLOYMENT_READINESS_SCHEMA_V1,
    DEPLOYMENT_READINESS_SCHEMA_V14,
    V14_PUBLIC_ACCEPTANCE_CHECKS,
    DeploymentAuthorizationError,
    DeploymentAuthorizationRequired,
    DeploymentTarget,
    authorize_deployment,
    execute_v14_local_deployment,
    verify_fresh_rollback_identity,
    write_v14_deployment_operation_facts,
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


def _v14_facts() -> dict[str, object]:
    release_id = "prompt-model-realized-v14"
    full_pool_identity = "1" * 64
    v2_identity = "2" * 64
    protected_v13_identity = "3" * 64
    workbook_sha256 = "f" * 64
    return {
        "schema_version": "abm-report-deployment-facts-v1",
        "release_contract_schema_version": "abm-report-release-contract-v14",
        "report_kind": "full-pool",
        "release_id": release_id,
        "canonical_endpoint": "https://abm.q1ngyuan.top/",
        "canonical_domain": "abm.q1ngyuan.top",
        "contract_sha256": "b" * 64,
        "release_identity_sha256": "c" * 64,
        "physical_snapshot_identity_sha256": "4" * 64,
        "report_sha256": "d" * 64,
        "manifest_sha256": "e" * 64,
        "workbook_relative_path": "prompt_model_realized_results.xlsx",
        "workbook_sha256": workbook_sha256,
        "artifact_sha256": {
            "artifact_manifest.json": "e" * 64,
            "prompt_model_realized_results.xlsx": workbook_sha256,
            "prompt-model-realized-mechanism.mmd": "0" * 64,
            "report.html": "d" * 64,
        },
        "approved_downloads": [
            "prompt-model-realized-mechanism.mmd",
            "prompt_model_realized_results.xlsx",
        ],
        "public_acceptance_artifacts": [
            "artifact_manifest.json",
            "prompt-model-realized-mechanism.mmd",
            "prompt_model_realized_results.xlsx",
            "report.html",
        ],
        "full_pool_source_identity": full_pool_identity,
        "v2_study_root_identity_sha256": v2_identity,
        "protected_v13_release_id": "full-pool-two-stage-v13-production-20260826T142827Z",
        "protected_v13_release_identity_sha256": protected_v13_identity,
        "release_readiness": {
            "schema_version": "full-pool-v14-release-readiness-v1",
            "release_id": release_id,
            "release_contract_schema": "abm-report-release-contract-v14",
            "v2_study_root_identity_sha256": v2_identity,
            "protected_v13_release_id": "full-pool-two-stage-v13-production-20260826T142827Z",
            "protected_v13_release_identity_sha256": protected_v13_identity,
            "canonical_endpoint": "https://abm.q1ngyuan.top/",
            "provider_calls_during_promotion": 0,
            "image_generation_triggered": False,
            "canonical_deployment_triggered": False,
            "operational_authorization_required": True,
            "deployment_authorized": False,
            "public_acceptance_recorded": False,
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
    assert str(captured.value) == (
        "v13 operational deployment authorization is required"
    )
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


def test_v14_missing_authorization_returns_hash_bound_readiness_without_a_plan(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "deployment-plan.json"

    with pytest.raises(DeploymentAuthorizationRequired) as captured:
        authorize_deployment(
            deployment_facts=_v14_facts(),
            target=_target(),
            authorization_path=None,
            plan_output=plan,
        )

    readiness = captured.value.readiness
    assert str(captured.value) == (
        "v14 operational deployment authorization is required"
    )
    assert readiness == {
        "schema_version": DEPLOYMENT_READINESS_SCHEMA_V14,
        "status": "awaiting_operational_authorization",
        "authorization_schema_version": DEPLOYMENT_AUTHORIZATION_SCHEMA_V14,
        "release_contract_schema": "abm-report-release-contract-v14",
        "contract_sha256": "b" * 64,
        "release_id": "prompt-model-realized-v14",
        "release_identity_sha256": "c" * 64,
        "physical_snapshot_identity_sha256": "4" * 64,
        "full_pool_source_identity": "1" * 64,
        "v2_study_root_identity_sha256": "2" * 64,
        "protected_v13_release_id": "full-pool-two-stage-v13-production-20260826T142827Z",
        "protected_v13_release_identity_sha256": "3" * 64,
        "canonical_endpoint": "https://abm.q1ngyuan.top/",
        "report_sha256": "d" * 64,
        "manifest_sha256": "e" * 64,
        "workbook_relative_path": "prompt_model_realized_results.xlsx",
        "workbook_sha256": "f" * 64,
        "artifact_count": 4,
        "release_readiness": _v14_facts()["release_readiness"],
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


def _v14_authorization_document() -> dict[str, object]:
    facts = _v14_facts()
    return {
        "schema_version": DEPLOYMENT_AUTHORIZATION_SCHEMA_V14,
        "authorization_kind": "explicit_operational_deployment",
        "authorization_status": "approved",
        "authorization_reference": "github:#v14-deploy:explicit-approval",
        "release_contract_schema": "abm-report-release-contract-v14",
        "contract_sha256": facts["contract_sha256"],
        "release_id": facts["release_id"],
        "release_identity_sha256": facts["release_identity_sha256"],
        "physical_snapshot_identity_sha256": facts[
            "physical_snapshot_identity_sha256"
        ],
        "full_pool_source_identity": facts["full_pool_source_identity"],
        "v2_study_root_identity_sha256": facts[
            "v2_study_root_identity_sha256"
        ],
        "protected_v13_release_id": facts["protected_v13_release_id"],
        "protected_v13_release_identity_sha256": facts[
            "protected_v13_release_identity_sha256"
        ],
        "canonical_endpoint": facts["canonical_endpoint"],
        "report_sha256": facts["report_sha256"],
        "manifest_sha256": facts["manifest_sha256"],
        "workbook_relative_path": facts["workbook_relative_path"],
        "workbook_sha256": facts["workbook_sha256"],
        "artifact_count": len(cast(dict[str, str], facts["artifact_sha256"])),
        "deployment_target": _target().as_document(),
        "rollback_identity": {
            "schema_version": "abm-report-fresh-rollback-identity-v1",
            "release_id": "full-pool-two-stage-v13-production-20260826T142827Z",
            "remote_release": (
                "/opt/llm-abm-marketing-sim-report/releases/"
                "full-pool-two-stage-v13-production-20260826T142827Z"
            ),
            "report_sha256": "6" * 64,
            "manifest_sha256": "7" * 64,
        },
    }


def test_v14_authorization_closes_all_release_and_rollback_identities(
    tmp_path: Path,
) -> None:
    authorization_path = tmp_path / "v14-authorization.json"
    authorization_bytes = (
        json.dumps(
            _v14_authorization_document(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    authorization_path.write_bytes(authorization_bytes)
    plan_path = tmp_path / "v14-deployment-plan.json"

    plan = authorize_deployment(
        deployment_facts=_v14_facts(),
        target=_target(),
        authorization_path=authorization_path,
        plan_output=plan_path,
    )

    assert plan["release_contract_schema"] == "abm-report-release-contract-v14"
    assert plan["full_pool_source_identity"] == "1" * 64
    assert plan["v2_study_root_identity_sha256"] == "2" * 64
    assert plan["protected_v13_release_identity_sha256"] == "3" * 64
    assert plan["physical_snapshot_identity_sha256"] == "4" * 64
    assert plan["workbook_relative_path"] == "prompt_model_realized_results.xlsx"
    assert plan["workbook_sha256"] == "f" * 64
    assert plan["authorization_sha256"] == hashlib.sha256(
        authorization_bytes
    ).hexdigest()
    assert plan["rollback_identity"] == _v14_authorization_document()[
        "rollback_identity"
    ]
    assert json.loads(plan_path.read_text(encoding="utf-8")) == plan


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


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", DEPLOYMENT_AUTHORIZATION_SCHEMA_V1),
        ("release_contract_schema", "abm-report-release-contract-v13"),
        ("workbook_sha256", "8" * 64),
        ("v2_study_root_identity_sha256", "9" * 64),
        ("artifact_count", 3),
    ],
)
def test_v14_authorization_rejects_schema_confusion_or_crossed_release_facts(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    authorization = _v14_authorization_document()
    authorization[field] = value
    authorization_path = tmp_path / f"crossed-{field}.json"
    authorization_path.write_text(
        json.dumps(
            authorization,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(DeploymentAuthorizationError, match="authorization|crossed"):
        authorize_deployment(
            deployment_facts=_v14_facts(),
            target=_target(),
            authorization_path=authorization_path,
            plan_output=tmp_path / f"plan-{field}.json",
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


@pytest.mark.parametrize(
    ("facts_factory", "release_id"),
    [
        (_v13_facts, "formal-two-stage-v13"),
        (_v14_facts, "prompt-model-realized-v14"),
    ],
)
def test_deploy_script_stops_missing_authorization_before_ssh(
    tmp_path: Path,
    facts_factory: Callable[[], dict[str, object]],
    release_id: str,
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
    facts = facts_factory()
    if facts["release_contract_schema_version"] == "abm-report-release-contract-v14":
        (source / "prompt_model_realized_results.xlsx").write_bytes(b"workbook\n")
        (source / "prompt-model-realized-mechanism.mmd").write_text(
            "flowchart LR\n",
            encoding="utf-8",
        )
    facts["artifact_sha256"] = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source.iterdir()
    }
    facts["report_sha256"] = facts["artifact_sha256"]["report.html"]
    facts["manifest_sha256"] = facts["artifact_sha256"][
        "artifact_manifest.json"
    ]
    if facts["release_contract_schema_version"] == "abm-report-release-contract-v14":
        facts["workbook_sha256"] = facts["artifact_sha256"][
            "prompt_model_realized_results.xlsx"
        ]
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
            release_id,
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


def test_v13_v14_authorization_and_fresh_readback_gates_precede_remote_writes() -> None:
    script = (REPO_ROOT / "scripts" / "deploy_abm_report.sh").read_text(encoding="utf-8")

    authorization_gate = script.index("validate_abm_report_deployment.py")
    operation_output_gate = script.index(
        "v14 requires --operation-facts-output"
    )
    first_ssh = script.index('if ssh "${DEPLOY_HOST}"')
    readback_gate = script.index("verify-readback")
    first_remote_write = script.index('REMOTE_RELEASE_STATE="$(ssh "${DEPLOY_HOST}"')
    playwright_gate = script.index("npx playwright test tests/playwright/deployed-abm-report.spec.ts")
    final_current_readback = script.index("FINAL_CURRENT_READBACK")
    operation_facts = script.index("write_v14_deployment_operation_facts")
    completion = script.index("printf 'Deployment complete")
    assert authorization_gate < operation_output_gate < first_ssh
    assert authorization_gate < first_ssh < readback_gate < first_remote_write
    assert playwright_gate < final_current_readback < operation_facts < completion
    assert "write-operation" not in script
    assert script.index("flock -n 9") < script.index(
        'atomic_current "${remote_release}"'
    )
    assert script.count("flock -n 9") >= 2
    assert "current changed outside this transaction before rollback" in script
    cleanup_handler = script[
        script.index("cleanup_and_rollback_on_failure()") :
        script.index("trap cleanup_and_rollback_on_failure EXIT")
    ]
    assert "cleanup_public_artifacts || true" in cleanup_handler
    assert cleanup_handler.index("cleanup_public_artifacts || true") < (
        cleanup_handler.index('rollback_on_failure "${status}"')
    )


def _authorized_v14_plan(tmp_path: Path) -> dict[str, object]:
    authorization = tmp_path / "v14-authorization.json"
    authorization.write_text(
        json.dumps(
            _v14_authorization_document(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    return authorize_deployment(
        deployment_facts=_v14_facts(),
        target=_target(),
        authorization_path=authorization,
        plan_output=tmp_path / "v14-plan.json",
    )


class _LocalDeploymentAdapter:
    def __init__(
        self,
        *,
        fail_at: str | None = None,
        fresh_drift: bool = False,
        current_drift: bool = False,
        rollback_failure: bool = False,
    ) -> None:
        self.fail_at = fail_at
        self.fresh_drift = fresh_drift
        self.current_drift = current_drift
        self.rollback_failure = rollback_failure
        self.events: list[str] = []
        self.read_count = 0
        self.rollback = cast(
            dict[str, object],
            _v14_authorization_document()["rollback_identity"],
        )

    def _step(self, name: str) -> None:
        self.events.append(name)
        if self.fail_at == name:
            raise RuntimeError(f"injected {name} failure")

    def read_current_rollback_identity(self) -> Mapping[str, object]:
        self.events.append("read_current_rollback_identity")
        self.read_count += 1
        if (self.fresh_drift and self.read_count == 1) or (
            self.current_drift and self.read_count == 2
        ):
            return {**self.rollback, "report_sha256": "0" * 64}
        return dict(self.rollback)

    def stage_candidate(self, _plan: Mapping[str, object]) -> None:
        self._step("stage_candidate")

    def verify_candidate_inventory(self, _plan: Mapping[str, object]) -> None:
        self._step("candidate_inventory")

    def verify_candidate_health(self, _plan: Mapping[str, object]) -> None:
        self._step("candidate_health")

    def atomic_switch(self, _plan: Mapping[str, object]) -> None:
        self._step("atomic_switch")

    def verify_post_switch_health(self, _plan: Mapping[str, object]) -> None:
        self._step("post_switch_health")

    def verify_public_acceptance(
        self,
        _plan: Mapping[str, object],
    ) -> Mapping[str, object]:
        self._step("public_acceptance")
        return {name: True for name in V14_PUBLIC_ACCEPTANCE_CHECKS}

    def atomic_restore(
        self,
        _plan: Mapping[str, object],
        _rollback: Mapping[str, object],
    ) -> None:
        self.events.append("atomic_restore")
        if self.rollback_failure:
            raise RuntimeError("injected rollback failure")

    def verify_restored_disk_identity(
        self,
        _rollback: Mapping[str, object],
    ) -> Mapping[str, object]:
        self._step("restored_disk_identity")
        return dict(self.rollback)

    def verify_restored_container_identity(
        self,
        _rollback: Mapping[str, object],
    ) -> Mapping[str, object]:
        self._step("restored_container_identity")
        return dict(self.rollback)


def test_v14_local_adapter_closes_success_without_mutating_release_facts(
    tmp_path: Path,
) -> None:
    plan = _authorized_v14_plan(tmp_path)
    adapter = _LocalDeploymentAdapter()
    release_facts = _v14_facts()
    before = deepcopy(release_facts)

    result = execute_v14_local_deployment(
        plan=plan,
        adapter=adapter,
        operated_at_utc="2026-09-04T12:00:00Z",
    )

    assert result["status"] == "succeeded"
    assert result["switched"] is True
    assert result["rollback_attempted"] is False
    assert result["rollback_verified"] is False
    assert result["operation_facts"] is None
    local_evidence = cast(
        dict[str, object],
        result["local_validation_evidence"],
    )
    assert local_evidence["schema_version"] == (
        "abm-report-v14-local-deployment-operation-v1"
    )
    assert local_evidence["status"] == "local_adapter_succeeded"
    assert local_evidence["execution_mode"] == "local_adapter_validation"
    assert local_evidence["remote_connection_authorized"] is False
    assert local_evidence["canonical_deployment_triggered"] is False
    assert local_evidence["release_id"] == "prompt-model-realized-v14"
    assert local_evidence["provider_calls"] == 0
    assert local_evidence["public_acceptance"] == {
        name: True for name in V14_PUBLIC_ACCEPTANCE_CHECKS
    }
    assert adapter.events[:2] == [
        "read_current_rollback_identity",
        "stage_candidate",
    ]
    assert adapter.events[-2:] == [
        "post_switch_health",
        "public_acceptance",
    ]
    assert release_facts == before

    operation_path = tmp_path / "operation.json"
    with pytest.raises(DeploymentAuthorizationError, match="incomplete"):
        write_v14_deployment_operation_facts(
            path=operation_path,
            operation_facts=local_evidence,
        )
    operation = {
        **local_evidence,
        "schema_version": "abm-report-v14-deployment-operation-v1",
        "status": "succeeded",
        "execution_mode": "authorized_remote_deployment",
        "remote_connection_authorized": True,
        "canonical_deployment_triggered": True,
        "final_current_identity_revalidated": True,
        "public_body_summary_sha256": "5" * 64,
        "playwright_acceptance_passed": True,
    }
    for required_gate in (
        "final_current_identity_revalidated",
        "playwright_acceptance_passed",
    ):
        with pytest.raises(DeploymentAuthorizationError, match="incomplete"):
            write_v14_deployment_operation_facts(
                path=operation_path,
                operation_facts={**operation, required_gate: False},
            )
    write_v14_deployment_operation_facts(
        path=operation_path,
        operation_facts=operation,
    )
    assert json.loads(operation_path.read_text(encoding="utf-8")) == operation
    with pytest.raises(DeploymentAuthorizationError, match="new regular"):
        write_v14_deployment_operation_facts(
            path=operation_path,
            operation_facts=operation,
        )


def test_v14_local_adapter_stops_fresh_readback_drift_before_candidate_write(
    tmp_path: Path,
) -> None:
    adapter = _LocalDeploymentAdapter(fresh_drift=True)

    result = execute_v14_local_deployment(
        plan=_authorized_v14_plan(tmp_path),
        adapter=adapter,
        operated_at_utc="2026-09-04T12:00:00Z",
    )

    assert result["status"] == "failed"
    assert result["failure_stage"] == "fresh_rollback_readback"
    assert result["switched"] is False
    assert adapter.events == ["read_current_rollback_identity"]


@pytest.mark.parametrize(
    ("failure", "current_drift", "expected_status", "rollback_attempted"),
    [
        ("candidate_inventory", False, "failed", False),
        ("candidate_health", False, "failed", False),
        (None, True, "failed", False),
        ("atomic_switch", False, "failed_rolled_back", True),
        ("post_switch_health", False, "failed_rolled_back", True),
        ("public_acceptance", False, "failed_rolled_back", True),
    ],
)
def test_v14_local_adapter_failure_matrix_never_reports_success(
    tmp_path: Path,
    failure: str | None,
    current_drift: bool,
    expected_status: str,
    rollback_attempted: bool,
) -> None:
    adapter = _LocalDeploymentAdapter(
        fail_at=failure,
        current_drift=current_drift,
    )

    result = execute_v14_local_deployment(
        plan=_authorized_v14_plan(tmp_path),
        adapter=adapter,
        operated_at_utc="2026-09-04T12:00:00Z",
    )

    assert result["status"] == expected_status
    assert result["operation_facts"] is None
    assert result["local_validation_evidence"] is None
    assert result["rollback_attempted"] is rollback_attempted
    assert result["rollback_verified"] is rollback_attempted
    if rollback_attempted:
        assert adapter.events[-3:] == [
            "atomic_restore",
            "restored_disk_identity",
            "restored_container_identity",
        ]
    else:
        assert "atomic_restore" not in adapter.events


def test_v14_local_adapter_reports_rollback_failure_separately(
    tmp_path: Path,
) -> None:
    adapter = _LocalDeploymentAdapter(
        fail_at="public_acceptance",
        rollback_failure=True,
    )

    result = execute_v14_local_deployment(
        plan=_authorized_v14_plan(tmp_path),
        adapter=adapter,
        operated_at_utc="2026-09-04T12:00:00Z",
    )

    assert result["status"] == "rollback_failed"
    assert result["operation_facts"] is None
    assert result["local_validation_evidence"] is None
    assert result["switched"] is True
    assert result["rollback_attempted"] is True
    assert result["rollback_verified"] is False
    assert adapter.events[-1] == "atomic_restore"
