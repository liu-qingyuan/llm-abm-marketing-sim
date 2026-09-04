from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

DEPLOYMENT_AUTHORIZATION_SCHEMA_V13 = "abm-report-v13-deployment-authorization-v1"
DEPLOYMENT_READINESS_SCHEMA_V13 = "abm-report-v13-deployment-readiness-v1"
# Backward-compatible names remain the exact v13 public contract.
DEPLOYMENT_AUTHORIZATION_SCHEMA_V1 = DEPLOYMENT_AUTHORIZATION_SCHEMA_V13
DEPLOYMENT_READINESS_SCHEMA_V1 = DEPLOYMENT_READINESS_SCHEMA_V13
DEPLOYMENT_AUTHORIZATION_SCHEMA_V14 = "abm-report-v14-deployment-authorization-v1"
DEPLOYMENT_READINESS_SCHEMA_V14 = "abm-report-v14-deployment-readiness-v1"
DEPLOYMENT_PLAN_SCHEMA_V1 = "abm-report-deployment-plan-v1"
DEPLOYMENT_TARGET_SCHEMA_V1 = "abm-report-deployment-target-v1"
DEPLOYMENT_TOPOLOGY = "immutable-releases-atomic-current-v1"
FRESH_ROLLBACK_IDENTITY_SCHEMA_V1 = "abm-report-fresh-rollback-identity-v1"
V13_RELEASE_CONTRACT_SCHEMA = "abm-report-release-contract-v13"
V14_RELEASE_CONTRACT_SCHEMA = "abm-report-release-contract-v14"
V14_DEPLOYMENT_OPERATION_SCHEMA = "abm-report-v14-deployment-operation-v1"
V14_LOCAL_DEPLOYMENT_OPERATION_SCHEMA = (
    "abm-report-v14-local-deployment-operation-v1"
)
V14_LOCAL_DEPLOYMENT_OUTCOME_SCHEMA = "abm-report-v14-local-deployment-outcome-v1"
V14_PUBLIC_ACCEPTANCE_CHECKS = (
    "release_inventory_hashes",
    "realized_default_view",
    "judgment_view_toggle",
    "prompt_locator",
    "two_stage_inline_svg",
    "bilingual_fallback",
    "mermaid_complete_body_hash_download",
    "workbook_complete_body_hash_download",
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RELEASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{0,254}$")
_REMOTE_ROOT = re.compile(r"^/[A-Za-z0-9._/-]+$")
_CONTAINER = re.compile(r"^[A-Za-z0-9_.-]+$")
_IMAGE = re.compile(r"^[A-Za-z0-9._/:@-]+$")
_UTC_SECOND = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class DeploymentAuthorizationError(ValueError):
    """The Deployment Module could not close an operational authorization."""


class DeploymentAuthorizationRequired(DeploymentAuthorizationError):
    """A valid release is ready, but no operational authorization was supplied."""

    def __init__(
        self,
        readiness: dict[str, object],
        release_contract_schema: str = V13_RELEASE_CONTRACT_SCHEMA,
    ) -> None:
        message = (
            "v13 operational deployment authorization is required"
            if release_contract_schema == V13_RELEASE_CONTRACT_SCHEMA
            else "v14 operational deployment authorization is required"
        )
        super().__init__(message)
        self.readiness = readiness


class V14DeploymentAdapter(Protocol):
    """Side-effect boundary used to exercise the v14 deployment state machine locally."""

    def read_current_rollback_identity(self) -> Mapping[str, object]: ...

    def stage_candidate(self, _plan: Mapping[str, object]) -> None: ...

    def verify_candidate_inventory(self, _plan: Mapping[str, object]) -> None: ...

    def verify_candidate_health(self, _plan: Mapping[str, object]) -> None: ...

    def atomic_switch(self, _plan: Mapping[str, object]) -> None: ...

    def verify_post_switch_health(self, _plan: Mapping[str, object]) -> None: ...

    def verify_public_acceptance(
        self,
        _plan: Mapping[str, object],
    ) -> Mapping[str, object]: ...

    def atomic_restore(
        self,
        _plan: Mapping[str, object],
        _rollback: Mapping[str, object],
    ) -> None: ...

    def verify_restored_disk_identity(
        self,
        _rollback: Mapping[str, object],
    ) -> Mapping[str, object]: ...

    def verify_restored_container_identity(
        self,
        _rollback: Mapping[str, object],
    ) -> Mapping[str, object]: ...


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


def _v14_release_facts(
    deployment_facts: Mapping[str, object],
    target: DeploymentTarget,
) -> dict[str, object]:
    expected_fields = {
        "schema_version",
        "release_contract_schema_version",
        "report_kind",
        "release_id",
        "canonical_endpoint",
        "canonical_domain",
        "contract_sha256",
        "release_identity_sha256",
        "physical_snapshot_identity_sha256",
        "report_sha256",
        "manifest_sha256",
        "workbook_relative_path",
        "workbook_sha256",
        "artifact_sha256",
        "approved_downloads",
        "public_acceptance_artifacts",
        "full_pool_source_identity",
        "v2_study_root_identity_sha256",
        "protected_v13_release_id",
        "protected_v13_release_identity_sha256",
        "release_readiness",
    }
    if (
        set(deployment_facts) != expected_fields
        or deployment_facts.get("schema_version")
        != "abm-report-deployment-facts-v1"
        or deployment_facts.get("release_contract_schema_version")
        != V14_RELEASE_CONTRACT_SCHEMA
        or deployment_facts.get("report_kind") != "full-pool"
    ):
        raise DeploymentAuthorizationError(
            "v14 deployment facts fields or schema are unsupported"
        )
    release_id = _string(
        deployment_facts.get("release_id"),
        "deployment release id",
    )
    protected_release_id = _string(
        deployment_facts.get("protected_v13_release_id"),
        "protected v13 release id",
    )
    if not _RELEASE_ID.fullmatch(release_id) or not _RELEASE_ID.fullmatch(
        protected_release_id
    ):
        raise DeploymentAuthorizationError("deployment release id is invalid")
    canonical_endpoint = _string(
        deployment_facts.get("canonical_endpoint"),
        "deployment canonical endpoint",
    )
    parsed = urlparse(canonical_endpoint)
    if (
        canonical_endpoint != target.canonical_endpoint
        or parsed.hostname != deployment_facts.get("canonical_domain")
    ):
        raise DeploymentAuthorizationError("deployment canonical endpoint is crossed")
    artifact_hashes = _mapping(
        deployment_facts.get("artifact_sha256"),
        "deployment artifact hashes",
    )
    if not artifact_hashes:
        raise DeploymentAuthorizationError("deployment artifact hashes are empty")
    for relative_path, digest in artifact_hashes.items():
        if (
            not isinstance(relative_path, str)
            or not relative_path
            or relative_path.startswith("/")
            or "\\" in relative_path
            or "/./" in f"/{relative_path}/"
            or "/../" in f"/{relative_path}/"
            or not isinstance(digest, str)
            or not _SHA256.fullmatch(digest)
        ):
            raise DeploymentAuthorizationError(
                "deployment artifact hashes are invalid"
            )
    report_sha256 = _sha256(
        deployment_facts.get("report_sha256"),
        "report SHA-256",
    )
    manifest_sha256 = _sha256(
        deployment_facts.get("manifest_sha256"),
        "manifest SHA-256",
    )
    workbook_path = _string(
        deployment_facts.get("workbook_relative_path"),
        "workbook relative path",
    )
    workbook_sha256 = _sha256(
        deployment_facts.get("workbook_sha256"),
        "workbook SHA-256",
    )
    if (
        artifact_hashes.get("report.html") != report_sha256
        or artifact_hashes.get("artifact_manifest.json") != manifest_sha256
        or artifact_hashes.get(workbook_path) != workbook_sha256
        or not workbook_path.endswith(".xlsx")
    ):
        raise DeploymentAuthorizationError(
            "v14 report, manifest, or workbook inventory is crossed"
        )
    approved_downloads = deployment_facts.get("approved_downloads")
    acceptance_artifacts = deployment_facts.get("public_acceptance_artifacts")
    if (
        not isinstance(approved_downloads, list)
        or any(not isinstance(path, str) for path in approved_downloads)
        or len(approved_downloads) != len(set(approved_downloads))
        or workbook_path not in approved_downloads
        or not any(path.endswith(".mmd") for path in approved_downloads)
        or any(path not in artifact_hashes for path in approved_downloads)
        or not isinstance(acceptance_artifacts, list)
        or acceptance_artifacts != sorted(artifact_hashes)
    ):
        raise DeploymentAuthorizationError(
            "v14 approved download or public acceptance inventory is crossed"
        )
    full_pool_identity = _sha256(
        deployment_facts.get("full_pool_source_identity"),
        "Full-Pool source identity",
    )
    v2_identity = _sha256(
        deployment_facts.get("v2_study_root_identity_sha256"),
        "v2 study root identity",
    )
    protected_identity = _sha256(
        deployment_facts.get("protected_v13_release_identity_sha256"),
        "protected v13 release identity",
    )
    readiness = _mapping(
        deployment_facts.get("release_readiness"),
        "release readiness",
    )
    if (
        set(readiness)
        != {
            "schema_version",
            "release_id",
            "release_contract_schema",
            "v2_study_root_identity_sha256",
            "protected_v13_release_id",
            "protected_v13_release_identity_sha256",
            "canonical_endpoint",
            "provider_calls_during_promotion",
            "image_generation_triggered",
            "canonical_deployment_triggered",
            "operational_authorization_required",
            "deployment_authorized",
            "public_acceptance_recorded",
        }
        or readiness.get("schema_version")
        != "full-pool-v14-release-readiness-v1"
        or readiness.get("release_id") != release_id
        or readiness.get("release_contract_schema")
        != V14_RELEASE_CONTRACT_SCHEMA
        or readiness.get("v2_study_root_identity_sha256") != v2_identity
        or readiness.get("protected_v13_release_id") != protected_release_id
        or readiness.get("protected_v13_release_identity_sha256")
        != protected_identity
        or readiness.get("canonical_endpoint") != canonical_endpoint
        or readiness.get("provider_calls_during_promotion") != 0
        or readiness.get("image_generation_triggered") is not False
        or readiness.get("canonical_deployment_triggered") is not False
        or readiness.get("operational_authorization_required") is not True
        or readiness.get("deployment_authorized") is not False
        or readiness.get("public_acceptance_recorded") is not False
    ):
        raise DeploymentAuthorizationError(
            "v14 immutable release readiness is crossed"
        )
    return {
        "release_contract_schema": V14_RELEASE_CONTRACT_SCHEMA,
        "contract_sha256": _sha256(
            deployment_facts.get("contract_sha256"),
            "release contract SHA-256",
        ),
        "release_id": release_id,
        "release_identity_sha256": _sha256(
            deployment_facts.get("release_identity_sha256"),
            "release identity SHA-256",
        ),
        "physical_snapshot_identity_sha256": _sha256(
            deployment_facts.get("physical_snapshot_identity_sha256"),
            "physical snapshot identity SHA-256",
        ),
        "full_pool_source_identity": full_pool_identity,
        "v2_study_root_identity_sha256": v2_identity,
        "protected_v13_release_id": protected_release_id,
        "protected_v13_release_identity_sha256": protected_identity,
        "canonical_endpoint": canonical_endpoint,
        "report_sha256": report_sha256,
        "manifest_sha256": manifest_sha256,
        "workbook_relative_path": workbook_path,
        "workbook_sha256": workbook_sha256,
        "artifact_count": len(artifact_hashes),
        "release_readiness": dict(readiness),
    }


def _release_facts(
    deployment_facts: Mapping[str, object],
    target: DeploymentTarget,
) -> dict[str, object]:
    schema = deployment_facts.get("release_contract_schema_version")
    if schema == V14_RELEASE_CONTRACT_SCHEMA:
        return _v14_release_facts(deployment_facts, target)
    if schema == V13_RELEASE_CONTRACT_SCHEMA:
        return _v13_release_facts(deployment_facts, target)
    raise DeploymentAuthorizationError(
        "operational authorization supports only exact v13 or v14 deployment facts"
    )


def _deployment_schemas(release_contract_schema: object) -> tuple[str, str]:
    if release_contract_schema == V14_RELEASE_CONTRACT_SCHEMA:
        return DEPLOYMENT_READINESS_SCHEMA_V14, DEPLOYMENT_AUTHORIZATION_SCHEMA_V14
    if release_contract_schema == V13_RELEASE_CONTRACT_SCHEMA:
        return DEPLOYMENT_READINESS_SCHEMA_V13, DEPLOYMENT_AUTHORIZATION_SCHEMA_V13
    raise DeploymentAuthorizationError("deployment release schema is unsupported")


def authorization_readiness(
    *,
    deployment_facts: Mapping[str, object],
    target: DeploymentTarget,
) -> dict[str, object]:
    release = _release_facts(deployment_facts, target)
    readiness_schema, authorization_schema = _deployment_schemas(
        release["release_contract_schema"]
    )
    return {
        "schema_version": readiness_schema,
        "status": "awaiting_operational_authorization",
        "authorization_schema_version": authorization_schema,
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
        raise DeploymentAuthorizationRequired(
            readiness,
            release_contract_schema=str(readiness["release_contract_schema"]),
        )
    authorization, authorization_bytes = _load_canonical_json_object(
        authorization_path,
        "deployment authorization artifact",
    )
    release_schema = readiness["release_contract_schema"]
    _readiness_schema, authorization_schema = _deployment_schemas(release_schema)
    if release_schema == V14_RELEASE_CONTRACT_SCHEMA:
        release_binding_keys = (
            "release_contract_schema",
            "contract_sha256",
            "release_id",
            "release_identity_sha256",
            "physical_snapshot_identity_sha256",
            "full_pool_source_identity",
            "v2_study_root_identity_sha256",
            "protected_v13_release_id",
            "protected_v13_release_identity_sha256",
            "canonical_endpoint",
            "report_sha256",
            "manifest_sha256",
            "workbook_relative_path",
            "workbook_sha256",
            "artifact_count",
        )
    else:
        release_binding_keys = (
            "release_contract_schema",
            "contract_sha256",
            "release_id",
            "release_identity_sha256",
            "realized_source_identity",
            "canonical_endpoint",
        )
    expected_fields = {
        "schema_version",
        "authorization_kind",
        "authorization_status",
        "authorization_reference",
        "deployment_target",
        "rollback_identity",
        *release_binding_keys,
    }
    if set(authorization) != expected_fields:
        raise DeploymentAuthorizationError(
            "deployment authorization fields are missing or unexpected"
        )
    release_fields = {key: readiness[key] for key in release_binding_keys}
    if (
        authorization.get("schema_version") != authorization_schema
        or authorization.get("authorization_kind")
        != "explicit_operational_deployment"
        or authorization.get("authorization_status") != "approved"
        or any(
            authorization.get(key) != value
            for key, value in release_fields.items()
        )
        or authorization.get("deployment_target") != target.as_document()
    ):
        raise DeploymentAuthorizationError(
            "deployment authorization release or target identity is crossed"
        )
    reference = _string(
        authorization.get("authorization_reference"),
        "deployment authorization reference",
    )
    rollback = _rollback_identity(
        authorization.get("rollback_identity"),
        target=target,
    )
    facts_sha256 = hashlib.sha256(_canonical_json_bytes(dict(deployment_facts))).hexdigest()
    plan_binding_keys = tuple(
        dict.fromkeys(
            (
                *release_binding_keys,
                "report_sha256",
                "manifest_sha256",
                "artifact_count",
            )
        )
    )
    plan = {
        "schema_version": DEPLOYMENT_PLAN_SCHEMA_V1,
        "authorization_required": True,
        "authorization_reference": reference,
        "authorization_sha256": hashlib.sha256(authorization_bytes).hexdigest(),
        "deployment_facts_sha256": facts_sha256,
        **{key: readiness[key] for key in plan_binding_keys},
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


_V14_PLAN_FIELDS = {
    "schema_version",
    "authorization_required",
    "authorization_reference",
    "authorization_sha256",
    "deployment_facts_sha256",
    "release_contract_schema",
    "contract_sha256",
    "release_id",
    "release_identity_sha256",
    "physical_snapshot_identity_sha256",
    "full_pool_source_identity",
    "v2_study_root_identity_sha256",
    "protected_v13_release_id",
    "protected_v13_release_identity_sha256",
    "canonical_endpoint",
    "report_sha256",
    "manifest_sha256",
    "workbook_relative_path",
    "workbook_sha256",
    "artifact_count",
    "deployment_target",
    "rollback_identity",
}


def _validated_v14_plan(plan: Mapping[str, object]) -> tuple[dict[str, object], dict[str, object]]:
    if (
        set(plan) != _V14_PLAN_FIELDS
        or plan.get("schema_version") != DEPLOYMENT_PLAN_SCHEMA_V1
        or plan.get("authorization_required") is not True
        or plan.get("release_contract_schema") != V14_RELEASE_CONTRACT_SCHEMA
    ):
        raise DeploymentAuthorizationError(
            "local v14 execution requires an exact authorized deployment plan"
        )
    target = _target_from_document(plan.get("deployment_target"))
    if plan.get("canonical_endpoint") != target.canonical_endpoint:
        raise DeploymentAuthorizationError("v14 deployment plan target is crossed")
    for key in (
        "authorization_sha256",
        "deployment_facts_sha256",
        "contract_sha256",
        "release_identity_sha256",
        "physical_snapshot_identity_sha256",
        "full_pool_source_identity",
        "v2_study_root_identity_sha256",
        "protected_v13_release_identity_sha256",
        "report_sha256",
        "manifest_sha256",
        "workbook_sha256",
    ):
        _sha256(plan.get(key), key)
    release_id = _string(plan.get("release_id"), "deployment release id")
    protected_id = _string(
        plan.get("protected_v13_release_id"),
        "protected v13 release id",
    )
    workbook_path = _string(
        plan.get("workbook_relative_path"),
        "workbook relative path",
    )
    artifact_count = plan.get("artifact_count")
    if (
        not _RELEASE_ID.fullmatch(release_id)
        or not _RELEASE_ID.fullmatch(protected_id)
        or not workbook_path.endswith(".xlsx")
        or type(artifact_count) is not int
        or artifact_count <= 0
    ):
        raise DeploymentAuthorizationError("v14 deployment plan facts are invalid")
    rollback = _rollback_identity(plan.get("rollback_identity"), target=target)
    return target.as_document(), rollback


def _v14_local_validation_evidence(
    *,
    plan: Mapping[str, object],
    operated_at_utc: str,
    public_acceptance: Mapping[str, object],
) -> dict[str, object]:
    target, rollback = _validated_v14_plan(plan)
    if not _UTC_SECOND.fullmatch(operated_at_utc):
        raise DeploymentAuthorizationError("deployment operation timestamp is invalid")
    if (
        set(public_acceptance) != set(V14_PUBLIC_ACCEPTANCE_CHECKS)
        or any(public_acceptance.get(name) is not True for name in V14_PUBLIC_ACCEPTANCE_CHECKS)
    ):
        raise DeploymentAuthorizationError(
            "v14 public acceptance is incomplete"
        )
    return {
        "schema_version": V14_LOCAL_DEPLOYMENT_OPERATION_SCHEMA,
        "status": "local_adapter_succeeded",
        "execution_mode": "local_adapter_validation",
        "remote_connection_authorized": False,
        "canonical_deployment_triggered": False,
        "operated_at_utc": operated_at_utc,
        "release_contract_schema": V14_RELEASE_CONTRACT_SCHEMA,
        "contract_sha256": plan["contract_sha256"],
        "deployment_facts_sha256": plan["deployment_facts_sha256"],
        "authorization_reference": plan["authorization_reference"],
        "authorization_sha256": plan["authorization_sha256"],
        "release_id": plan["release_id"],
        "release_identity_sha256": plan["release_identity_sha256"],
        "physical_snapshot_identity_sha256": plan[
            "physical_snapshot_identity_sha256"
        ],
        "full_pool_source_identity": plan["full_pool_source_identity"],
        "v2_study_root_identity_sha256": plan[
            "v2_study_root_identity_sha256"
        ],
        "protected_v13_release_id": plan["protected_v13_release_id"],
        "protected_v13_release_identity_sha256": plan[
            "protected_v13_release_identity_sha256"
        ],
        "canonical_endpoint": plan["canonical_endpoint"],
        "report_sha256": plan["report_sha256"],
        "manifest_sha256": plan["manifest_sha256"],
        "workbook_relative_path": plan["workbook_relative_path"],
        "workbook_sha256": plan["workbook_sha256"],
        "artifact_count": plan["artifact_count"],
        "deployment_target": target,
        "fresh_rollback_identity": rollback,
        "candidate_inventory_validated": True,
        "candidate_health_validated": True,
        "current_identity_revalidated_before_switch": True,
        "atomic_current_switched": True,
        "post_switch_health_validated": True,
        "public_acceptance": dict(public_acceptance),
        "rollback_required": False,
        "provider_calls": 0,
    }


def execute_v14_local_deployment(
    *,
    plan: Mapping[str, object],
    adapter: V14DeploymentAdapter,
    operated_at_utc: str,
) -> dict[str, object]:
    """Exercise v14 cutover ordering against a local adapter; this function never opens a network."""
    _target, rollback = _validated_v14_plan(plan)
    if not _UTC_SECOND.fullmatch(operated_at_utc):
        raise DeploymentAuthorizationError("deployment operation timestamp is invalid")
    stage = "fresh_rollback_readback"
    switched = False
    rollback_attempted = False
    rollback_verified = False
    try:
        verify_fresh_rollback_identity(
            plan=plan,
            readback=adapter.read_current_rollback_identity(),
        )
        stage = "stage_candidate"
        adapter.stage_candidate(plan)
        stage = "candidate_inventory"
        adapter.verify_candidate_inventory(plan)
        stage = "candidate_health"
        adapter.verify_candidate_health(plan)
        stage = "current_revalidation"
        verify_fresh_rollback_identity(
            plan=plan,
            readback=adapter.read_current_rollback_identity(),
        )
        stage = "atomic_switch"
        switched = True
        adapter.atomic_switch(plan)
        stage = "post_switch_health"
        adapter.verify_post_switch_health(plan)
        stage = "public_acceptance"
        public_acceptance = adapter.verify_public_acceptance(plan)
        local_validation_evidence = _v14_local_validation_evidence(
            plan=plan,
            operated_at_utc=operated_at_utc,
            public_acceptance=public_acceptance,
        )
    except Exception:
        status = "failed"
        if switched:
            rollback_attempted = True
            try:
                adapter.atomic_restore(plan, rollback)
                verify_fresh_rollback_identity(
                    plan=plan,
                    readback=adapter.verify_restored_disk_identity(rollback),
                )
                verify_fresh_rollback_identity(
                    plan=plan,
                    readback=adapter.verify_restored_container_identity(rollback),
                )
                rollback_verified = True
                status = "failed_rolled_back"
            except Exception:
                status = "rollback_failed"
        return {
            "schema_version": V14_LOCAL_DEPLOYMENT_OUTCOME_SCHEMA,
            "status": status,
            "failure_stage": stage,
            "switched": switched,
            "rollback_attempted": rollback_attempted,
            "rollback_verified": rollback_verified,
            "provider_calls": 0,
            "operation_facts": None,
            "local_validation_evidence": None,
        }
    return {
        "schema_version": V14_LOCAL_DEPLOYMENT_OUTCOME_SCHEMA,
        "status": "succeeded",
        "failure_stage": None,
        "switched": True,
        "rollback_attempted": False,
        "rollback_verified": False,
        "provider_calls": 0,
        "operation_facts": None,
        "local_validation_evidence": local_validation_evidence,
    }


_V14_OPERATION_FIELDS = {
    "schema_version",
    "status",
    "execution_mode",
    "remote_connection_authorized",
    "canonical_deployment_triggered",
    "operated_at_utc",
    "release_contract_schema",
    "contract_sha256",
    "deployment_facts_sha256",
    "authorization_reference",
    "authorization_sha256",
    "release_id",
    "release_identity_sha256",
    "physical_snapshot_identity_sha256",
    "full_pool_source_identity",
    "v2_study_root_identity_sha256",
    "protected_v13_release_id",
    "protected_v13_release_identity_sha256",
    "canonical_endpoint",
    "report_sha256",
    "manifest_sha256",
    "workbook_relative_path",
    "workbook_sha256",
    "artifact_count",
    "deployment_target",
    "fresh_rollback_identity",
    "candidate_inventory_validated",
    "candidate_health_validated",
    "current_identity_revalidated_before_switch",
    "atomic_current_switched",
    "post_switch_health_validated",
    "final_current_identity_revalidated",
    "public_acceptance",
    "public_body_summary_sha256",
    "playwright_acceptance_passed",
    "rollback_required",
    "provider_calls",
}


def write_v14_deployment_operation_facts(
    *,
    path: Path,
    operation_facts: Mapping[str, object],
) -> None:
    """Persist successful operational evidence separately from the immutable Release."""
    if (
        set(operation_facts) != _V14_OPERATION_FIELDS
        or operation_facts.get("schema_version")
        != V14_DEPLOYMENT_OPERATION_SCHEMA
        or operation_facts.get("status") != "succeeded"
        or operation_facts.get("execution_mode")
        != "authorized_remote_deployment"
        or operation_facts.get("remote_connection_authorized") is not True
        or operation_facts.get("canonical_deployment_triggered") is not True
        or operation_facts.get("release_contract_schema")
        != V14_RELEASE_CONTRACT_SCHEMA
        or operation_facts.get("candidate_inventory_validated") is not True
        or operation_facts.get("candidate_health_validated") is not True
        or operation_facts.get("current_identity_revalidated_before_switch")
        is not True
        or operation_facts.get("atomic_current_switched") is not True
        or operation_facts.get("post_switch_health_validated") is not True
        or operation_facts.get("final_current_identity_revalidated") is not True
        or operation_facts.get("playwright_acceptance_passed") is not True
        or operation_facts.get("rollback_required") is not False
        or operation_facts.get("provider_calls") != 0
        or not _UTC_SECOND.fullmatch(
            str(operation_facts.get("operated_at_utc", ""))
        )
    ):
        raise DeploymentAuthorizationError(
            "v14 deployment operation facts are incomplete"
        )
    public_acceptance = _mapping(
        operation_facts.get("public_acceptance"),
        "v14 public acceptance",
    )
    if (
        set(public_acceptance) != set(V14_PUBLIC_ACCEPTANCE_CHECKS)
        or any(public_acceptance.get(name) is not True for name in V14_PUBLIC_ACCEPTANCE_CHECKS)
    ):
        raise DeploymentAuthorizationError(
            "v14 deployment operation public acceptance is incomplete"
        )
    target = _target_from_document(operation_facts.get("deployment_target"))
    release_id = _string(operation_facts.get("release_id"), "release id")
    protected_release_id = _string(
        operation_facts.get("protected_v13_release_id"),
        "protected v13 release id",
    )
    workbook_path = _string(
        operation_facts.get("workbook_relative_path"),
        "workbook relative path",
    )
    artifact_count = operation_facts.get("artifact_count")
    _string(
        operation_facts.get("authorization_reference"),
        "authorization reference",
    )
    if (
        operation_facts.get("canonical_endpoint") != target.canonical_endpoint
        or not _RELEASE_ID.fullmatch(release_id)
        or not _RELEASE_ID.fullmatch(protected_release_id)
        or workbook_path.startswith("/")
        or "\\" in workbook_path
        or "/./" in f"/{workbook_path}/"
        or "/../" in f"/{workbook_path}/"
        or not workbook_path.endswith(".xlsx")
        or type(artifact_count) is not int
        or artifact_count <= 0
    ):
        raise DeploymentAuthorizationError(
            "v14 deployment operation identity or inventory is crossed"
        )
    _rollback_identity(
        operation_facts.get("fresh_rollback_identity"),
        target=target,
    )
    for key in (
        "contract_sha256",
        "deployment_facts_sha256",
        "authorization_sha256",
        "release_identity_sha256",
        "physical_snapshot_identity_sha256",
        "full_pool_source_identity",
        "v2_study_root_identity_sha256",
        "protected_v13_release_identity_sha256",
        "report_sha256",
        "manifest_sha256",
        "workbook_sha256",
        "public_body_summary_sha256",
    ):
        _sha256(operation_facts.get(key), key)
    if (
        path.is_symlink()
        or path.exists()
        or not path.parent.is_dir()
        or path.parent.is_symlink()
    ):
        raise DeploymentAuthorizationError(
            "deployment operation output must be a new regular non-symlink file"
        )
    try:
        with path.open("xb") as stream:
            stream.write(_canonical_json_bytes(dict(operation_facts)))
    except OSError as exc:
        raise DeploymentAuthorizationError(
            "deployment operation output could not be created exclusively"
        ) from exc
