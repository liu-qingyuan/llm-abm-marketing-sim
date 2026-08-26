from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

DEPLOYMENT_AUTHORIZATION_SCHEMA_V1 = "abm-report-v13-deployment-authorization-v1"
DEPLOYMENT_READINESS_SCHEMA_V1 = "abm-report-v13-deployment-readiness-v1"
DEPLOYMENT_PLAN_SCHEMA_V1 = "abm-report-deployment-plan-v1"
DEPLOYMENT_TARGET_SCHEMA_V1 = "abm-report-deployment-target-v1"
DEPLOYMENT_TOPOLOGY = "immutable-releases-atomic-current-v1"
FRESH_ROLLBACK_IDENTITY_SCHEMA_V1 = "abm-report-fresh-rollback-identity-v1"
V13_RELEASE_CONTRACT_SCHEMA = "abm-report-release-contract-v13"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RELEASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{0,254}$")
_REMOTE_ROOT = re.compile(r"^/[A-Za-z0-9._/-]+$")
_CONTAINER = re.compile(r"^[A-Za-z0-9_.-]+$")
_IMAGE = re.compile(r"^[A-Za-z0-9._/:@-]+$")


class DeploymentAuthorizationError(ValueError):
    """The Deployment Module could not close an operational authorization."""


class DeploymentAuthorizationRequired(DeploymentAuthorizationError):
    """A valid v13 release is ready, but no operational authorization was supplied."""

    def __init__(self, readiness: dict[str, object]) -> None:
        super().__init__("v13 operational deployment authorization is required")
        self.readiness = readiness


@dataclass(frozen=True)
class DeploymentTarget:
    canonical_endpoint: str
    host: str
    remote_root: str
    port: int
    container_name: str
    image: str

    def __post_init__(self) -> None:
        parsed = urlparse(self.canonical_endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.port is not None
            or parsed.path != "/"
            or parsed.params
            or parsed.query
            or parsed.fragment
        ):
            raise DeploymentAuthorizationError("deployment canonical endpoint is invalid")
        if not _HOST.fullmatch(self.host):
            raise DeploymentAuthorizationError("deployment host is invalid")
        if (
            not _REMOTE_ROOT.fullmatch(self.remote_root)
            or "//" in self.remote_root
            or "/./" in f"{self.remote_root}/"
            or "/../" in f"{self.remote_root}/"
        ):
            raise DeploymentAuthorizationError("deployment remote root is invalid")
        if not isinstance(self.port, int) or isinstance(self.port, bool) or not 1024 <= self.port <= 65535:
            raise DeploymentAuthorizationError("deployment port is invalid")
        if not _CONTAINER.fullmatch(self.container_name):
            raise DeploymentAuthorizationError("deployment container name is invalid")
        if not _IMAGE.fullmatch(self.image):
            raise DeploymentAuthorizationError("deployment image is invalid")

    def as_document(self) -> dict[str, object]:
        return {
            "schema_version": DEPLOYMENT_TARGET_SCHEMA_V1,
            "canonical_endpoint": self.canonical_endpoint,
            "host": self.host,
            "remote_root": self.remote_root,
            "topology": DEPLOYMENT_TOPOLOGY,
            "port": self.port,
            "container_name": self.container_name,
            "image": self.image,
        }


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise DeploymentAuthorizationError(f"{label} must be an object")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise DeploymentAuthorizationError(f"{label} is invalid")
    return value


def _sha256(value: object, label: str) -> str:
    text = _string(value, label)
    if not _SHA256.fullmatch(text):
        raise DeploymentAuthorizationError(f"{label} is invalid")
    return text


def _v13_release_facts(
    deployment_facts: Mapping[str, object],
    target: DeploymentTarget,
) -> dict[str, object]:
    if (
        deployment_facts.get("schema_version") != "abm-report-deployment-facts-v1"
        or deployment_facts.get("release_contract_schema_version") != V13_RELEASE_CONTRACT_SCHEMA
    ):
        raise DeploymentAuthorizationError("v13 deployment facts schema is unsupported")
    release_id = _string(deployment_facts.get("release_id"), "deployment release id")
    if not _RELEASE_ID.fullmatch(release_id):
        raise DeploymentAuthorizationError("deployment release id is invalid")
    canonical_endpoint = _string(
        deployment_facts.get("canonical_endpoint"),
        "deployment canonical endpoint",
    )
    if canonical_endpoint != target.canonical_endpoint:
        raise DeploymentAuthorizationError("deployment canonical endpoint is crossed")
    source_identity = _sha256(
        deployment_facts.get("realized_source_identity"),
        "realized source identity",
    )
    readiness = _mapping(deployment_facts.get("release_readiness"), "release readiness")
    accounting = _mapping(
        deployment_facts.get("composite_provider_accounting"),
        "composite Provider accounting",
    )
    if (
        readiness.get("schema_version") != "full-pool-v13-release-readiness-v1"
        or readiness.get("release_id") != release_id
        or readiness.get("release_contract_schema") != V13_RELEASE_CONTRACT_SCHEMA
        or readiness.get("realized_source_identity") != source_identity
        or readiness.get("canonical_endpoint") != canonical_endpoint
        or readiness.get("provider_calls_during_promotion") != 0
        or readiness.get("image_generation_triggered") is not False
        or readiness.get("operational_authorization_required") is not True
        or readiness.get("deployment_authorized") is not False
        or readiness.get("canonical_deployment_triggered") is not False
        or readiness.get("public_acceptance_recorded") is not False
    ):
        raise DeploymentAuthorizationError("v13 immutable release readiness is crossed")
    if (
        accounting.get("schema_version") != "full-pool-two-stage-provider-accounting-v1"
        or accounting.get("upstream_live_api_triggered") is not True
        or accounting.get("upstream_formal_research_evidence") is not True
        or accounting.get("upstream_production_deploy_eligible") is not True
        or accounting.get("realization_provider_calls") != 0
        or accounting.get("realization_live_api_triggered") is not False
        or accounting.get("composite_live_api_triggered") is not True
        or accounting.get("composite_zero_provider_formal") is not False
    ):
        raise DeploymentAuthorizationError("v13 composite Provider accounting is crossed")
    artifact_hashes = _mapping(
        deployment_facts.get("artifact_sha256"),
        "deployment artifact hashes",
    )
    if not artifact_hashes:
        raise DeploymentAuthorizationError("deployment artifact hashes are empty")
    for relative_path, digest in artifact_hashes.items():
        if not isinstance(relative_path, str) or not _SHA256.fullmatch(str(digest)):
            raise DeploymentAuthorizationError("deployment artifact hashes are invalid")
    return {
        "release_contract_schema": V13_RELEASE_CONTRACT_SCHEMA,
        "contract_sha256": _sha256(
            deployment_facts.get("contract_sha256"),
            "release contract SHA-256",
        ),
        "release_id": release_id,
        "release_identity_sha256": _sha256(
            deployment_facts.get("release_identity_sha256"),
            "release identity SHA-256",
        ),
        "realized_source_identity": source_identity,
        "canonical_endpoint": canonical_endpoint,
        "report_sha256": _sha256(
            deployment_facts.get("report_sha256"),
            "report SHA-256",
        ),
        "manifest_sha256": _sha256(
            deployment_facts.get("manifest_sha256"),
            "manifest SHA-256",
        ),
        "artifact_count": len(artifact_hashes),
        "release_readiness": dict(readiness),
    }


def authorization_readiness(
    *,
    deployment_facts: Mapping[str, object],
    target: DeploymentTarget,
) -> dict[str, object]:
    release = _v13_release_facts(deployment_facts, target)
    return {
        "schema_version": DEPLOYMENT_READINESS_SCHEMA_V1,
        "status": "awaiting_operational_authorization",
        "authorization_schema_version": DEPLOYMENT_AUTHORIZATION_SCHEMA_V1,
        **release,
        "deployment_target": target.as_document(),
        "rollback_identity_required": True,
        "remote_connection_authorized": False,
        "deployment_authorized": False,
    }


def _canonical_json_bytes(value: Mapping[str, object]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _load_canonical_json_object(path: Path, label: str) -> tuple[dict[str, object], bytes]:
    if path.is_symlink() or not path.is_file():
        raise DeploymentAuthorizationError(f"{label} must be a regular non-symlink file")
    try:
        payload = path.read_bytes()

        def collect_pairs(value: list[tuple[str, object]]) -> dict[str, object]:
            keys = [key for key, _item in value]
            if len(keys) != len(set(keys)):
                raise DeploymentAuthorizationError(f"{label} contains duplicate fields")
            return dict(value)

        value = json.loads(payload.decode("utf-8"), object_pairs_hook=collect_pairs)
    except DeploymentAuthorizationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DeploymentAuthorizationError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise DeploymentAuthorizationError(f"{label} must be a JSON object")
    if payload != _canonical_json_bytes(value):
        raise DeploymentAuthorizationError(f"{label} must use canonical JSON serialization")
    return value, payload


def _rollback_identity(
    value: object,
    *,
    target: DeploymentTarget,
) -> dict[str, object]:
    document = _mapping(value, "authorized rollback identity")
    expected_fields = {
        "schema_version",
        "release_id",
        "remote_release",
        "report_sha256",
        "manifest_sha256",
    }
    if set(document) != expected_fields:
        raise DeploymentAuthorizationError("authorized rollback identity fields are missing or unexpected")
    release_id = _string(document.get("release_id"), "rollback release id")
    if not _RELEASE_ID.fullmatch(release_id):
        raise DeploymentAuthorizationError("rollback release id is invalid")
    expected_remote = f"{target.remote_root}/releases/{release_id}"
    if (
        document.get("schema_version") != FRESH_ROLLBACK_IDENTITY_SCHEMA_V1
        or document.get("remote_release") != expected_remote
    ):
        raise DeploymentAuthorizationError("authorized rollback identity is crossed")
    return {
        "schema_version": FRESH_ROLLBACK_IDENTITY_SCHEMA_V1,
        "release_id": release_id,
        "remote_release": expected_remote,
        "report_sha256": _sha256(
            document.get("report_sha256"),
            "rollback report SHA-256",
        ),
        "manifest_sha256": _sha256(
            document.get("manifest_sha256"),
            "rollback manifest SHA-256",
        ),
    }


def _target_from_document(value: object) -> DeploymentTarget:
    document = _mapping(value, "deployment target")
    expected_fields = {
        "schema_version",
        "canonical_endpoint",
        "host",
        "remote_root",
        "topology",
        "port",
        "container_name",
        "image",
    }
    if (
        set(document) != expected_fields
        or document.get("schema_version") != DEPLOYMENT_TARGET_SCHEMA_V1
        or document.get("topology") != DEPLOYMENT_TOPOLOGY
    ):
        raise DeploymentAuthorizationError("deployment target is crossed")
    canonical_endpoint = document.get("canonical_endpoint")
    host = document.get("host")
    remote_root = document.get("remote_root")
    port = document.get("port")
    container_name = document.get("container_name")
    image = document.get("image")
    if (
        not isinstance(canonical_endpoint, str)
        or not isinstance(host, str)
        or not isinstance(remote_root, str)
        or not isinstance(port, int)
        or isinstance(port, bool)
        or not isinstance(container_name, str)
        or not isinstance(image, str)
    ):
        raise DeploymentAuthorizationError("deployment target fields are invalid")
    return DeploymentTarget(
        canonical_endpoint=canonical_endpoint,
        host=host,
        remote_root=remote_root,
        port=port,
        container_name=container_name,
        image=image,
    )


def _write_plan(path: Path, plan: dict[str, object]) -> None:
    if path.is_symlink() or (path.exists() and (not path.is_file() or path.stat().st_size != 0)):
        raise DeploymentAuthorizationError("deployment plan output must be a new or empty regular non-symlink file")
    path.write_bytes(_canonical_json_bytes(plan))


def authorize_deployment(
    *,
    deployment_facts: Mapping[str, object],
    target: DeploymentTarget,
    authorization_path: Path | None,
    plan_output: Path,
) -> dict[str, object]:
    """Close a local deployment plan before any remote connection is allowed."""
    readiness = authorization_readiness(
        deployment_facts=deployment_facts,
        target=target,
    )
    if authorization_path is None:
        raise DeploymentAuthorizationRequired(readiness)
    authorization, authorization_bytes = _load_canonical_json_object(
        authorization_path,
        "deployment authorization artifact",
    )
    expected_fields = {
        "schema_version",
        "authorization_kind",
        "authorization_status",
        "authorization_reference",
        "release_contract_schema",
        "contract_sha256",
        "release_id",
        "release_identity_sha256",
        "realized_source_identity",
        "canonical_endpoint",
        "deployment_target",
        "rollback_identity",
    }
    if set(authorization) != expected_fields:
        raise DeploymentAuthorizationError("deployment authorization fields are missing or unexpected")
    release_fields = {
        key: readiness[key]
        for key in (
            "release_contract_schema",
            "contract_sha256",
            "release_id",
            "release_identity_sha256",
            "realized_source_identity",
            "canonical_endpoint",
        )
    }
    if (
        authorization.get("schema_version") != DEPLOYMENT_AUTHORIZATION_SCHEMA_V1
        or authorization.get("authorization_kind") != "explicit_operational_deployment"
        or authorization.get("authorization_status") != "approved"
        or any(authorization.get(key) != value for key, value in release_fields.items())
        or authorization.get("deployment_target") != target.as_document()
    ):
        raise DeploymentAuthorizationError("deployment authorization release or target identity is crossed")
    reference = _string(
        authorization.get("authorization_reference"),
        "deployment authorization reference",
    )
    rollback = _rollback_identity(
        authorization.get("rollback_identity"),
        target=target,
    )
    facts_sha256 = hashlib.sha256(_canonical_json_bytes(dict(deployment_facts))).hexdigest()
    plan = {
        "schema_version": DEPLOYMENT_PLAN_SCHEMA_V1,
        "authorization_required": True,
        "authorization_reference": reference,
        "authorization_sha256": hashlib.sha256(authorization_bytes).hexdigest(),
        "deployment_facts_sha256": facts_sha256,
        **{
            key: readiness[key]
            for key in (
                "release_contract_schema",
                "contract_sha256",
                "release_id",
                "release_identity_sha256",
                "realized_source_identity",
                "canonical_endpoint",
                "report_sha256",
                "manifest_sha256",
                "artifact_count",
            )
        },
        "deployment_target": target.as_document(),
        "rollback_identity": rollback,
    }
    _write_plan(plan_output, plan)
    return plan


def authorize_deployment_files(
    *,
    deployment_facts_path: Path,
    target: DeploymentTarget,
    authorization_path: Path | None,
    plan_output: Path,
) -> dict[str, object]:
    deployment_facts, _payload = _load_canonical_json_object(
        deployment_facts_path,
        "deployment facts",
    )
    return authorize_deployment(
        deployment_facts=deployment_facts,
        target=target,
        authorization_path=authorization_path,
        plan_output=plan_output,
    )


def verify_fresh_rollback_identity(
    *,
    plan: Mapping[str, object],
    readback: Mapping[str, object],
) -> dict[str, object]:
    """Close the first remote readback before any remote write or switch."""
    if plan.get("schema_version") != DEPLOYMENT_PLAN_SCHEMA_V1 or plan.get("authorization_required") is not True:
        raise DeploymentAuthorizationError("fresh rollback readback requires an authorized deployment plan")
    target = _target_from_document(plan.get("deployment_target"))
    expected = _rollback_identity(plan.get("rollback_identity"), target=target)
    observed = _rollback_identity(readback, target=target)
    if observed != expected:
        raise DeploymentAuthorizationError("fresh rollback readback differs from the authorized rollback identity")
    return observed


def verify_fresh_rollback_files(
    *,
    plan_path: Path,
    readback_path: Path,
) -> dict[str, object]:
    plan, _plan_payload = _load_canonical_json_object(
        plan_path,
        "deployment plan",
    )
    readback, _readback_payload = _load_canonical_json_object(
        readback_path,
        "fresh rollback readback",
    )
    return verify_fresh_rollback_identity(plan=plan, readback=readback)
