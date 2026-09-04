from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .concurrent_robustness_study import _OUTPUT_IDENTITY_PATTERN
from .concurrent_robustness_v2 import (
    _V2_CELLS_PER_MODEL,
    _V2_FORMAL_LOGICAL_CAP,
    _V2_FORMAL_LOGICAL_PER_CELL,
    _V2_FORMAL_LOGICAL_PER_MODEL,
    _V2_FORMAL_PHYSICAL_CAP,
    _V2_FORMAL_PHYSICAL_PER_MODEL,
    _V2_MAXIMUM_ATTEMPTS,
    _V2_MODELS,
    _V2_REQUIRED_OBSERVED_MODELS,
    ConcurrentRobustnessManifestV2,
)
from .prompt_contracts import CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY
from .providers.robustness import robustness_provider_disclosures

FORMAL_EXECUTION_REQUEST_SCHEMA = "concurrent-robustness-formal-execution-request-v1"
FORMAL_EXECUTION_REQUEST_IDENTITY_SCHEMA = "concurrent-robustness-formal-execution-identity-v1"
FORMAL_QUALIFICATION_SCHEMA = "concurrent-robustness-formal-model-qualification-v1"
FORMAL_AUTHORIZATION_SCHEMA = "concurrent-robustness-formal-authorization-v1"
FORMAL_READINESS_SCHEMA = "concurrent-robustness-formal-readiness-v1"
FORMAL_EXECUTION_PLAN_SCHEMA = "concurrent-robustness-formal-execution-plan-v1"
FORMAL_RESUME_POLICY = "unresolved-with-remaining-attempt-budget-only-v1"
FORMAL_MODEL_BATCH_POLICY = "finish-current-model-before-next-model-v1"
FORMAL_RUN_SCOPE = "five_serial_model_batches_twenty_cells_thirty_six_thousand_judgments_v1"
FORMAL_BACKOFF_CEILING_SECONDS = 60.0

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/#@+-]{0,239}$")
_UTC_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_MAX_AUTHORIZATION_WINDOW = timedelta(hours=24)
_MAX_QUALIFICATION_WINDOW = timedelta(hours=24)

_CREDENTIAL_ROUTES: Mapping[str, str] = {
    "deepseek-v4-flash": "runtime-injected-deepseek-credential-v1",
    "gemini-3.1-pro": "runtime-injected-antigravity-credential-v1",
    "gemini-3.8-flash-high": "runtime-injected-antigravity-credential-v1",
    "kimi-coding/k3-256k": "pi-kimi-current-user-profile-v1",
    "openai-codex/gpt-5.6-sol": "pi-openai-current-user-profile-v1",
}
_SECRET_MARKERS = (
    ".env",
    "api_key=",
    "apikey=",
    "password=",
    "secret=",
    "token=",
    "bearer ",
    "authorization:",
    "cookie:",
    "raw_prompt",
    "raw_response",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ConcurrentRobustnessFormalPreflightError(ValueError):
    """Formal execution inputs did not close without exposing supplied values."""


class ConcurrentRobustnessFormalAuthorizationRequired(ConcurrentRobustnessFormalPreflightError):
    """All non-authorization facts close, but exact human approval is absent."""

    def __init__(self, readiness: dict[str, object]) -> None:
        super().__init__("exact Formal Provider execution authorization is required")
        self.readiness = readiness


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


def _absolute_path(value: object) -> Path:
    return Path(os.path.abspath(Path(cast(str | os.PathLike[str], value)).expanduser()))


def _validate_digest(value: str, label: str) -> str:
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _safe_reference(value: str, label: str) -> str:
    lowered = value.lower()
    if _REFERENCE_PATTERN.fullmatch(value) is None or any(marker in lowered for marker in _SECRET_MARKERS):
        raise ValueError(f"{label} must be a bounded safe reference")
    return value


def _safe_path(value: Path, label: str) -> Path:
    lowered = str(value).lower()
    if any(marker in lowered for marker in _SECRET_MARKERS):
        raise ValueError(f"{label} must not contain a secret-like segment")
    return value


class FormalArtifactReference(_FrozenModel):
    path: Path
    sha256: str

    @field_validator("path", mode="before")
    @classmethod
    def _normalize_path(cls, value: object) -> Path:
        return _safe_path(_absolute_path(value), "artifact path")

    @field_validator("sha256")
    @classmethod
    def _digest(cls, value: str) -> str:
        return _validate_digest(value, "artifact hash")


class FormalQualificationArtifactReference(FormalArtifactReference):
    requested_model: str


class FormalProviderRoute(_FrozenModel):
    requested_model: str
    required_observed_model: str
    provider_route: str
    credential_route: str

    @field_validator("credential_route")
    @classmethod
    def _credential_route_is_safe(cls, value: str) -> str:
        return _safe_reference(value, "credential route")


class FormalRunParameters(_FrozenModel):
    worker_count: int = Field(ge=1, le=64)
    max_in_flight: int = Field(ge=1, le=64)
    request_timeout_seconds: float = Field(gt=0.0, le=600.0)
    retry_backoff_seconds: float = Field(ge=0.0, le=600.0)
    backoff_ceiling_seconds: float = Field(gt=0.0, le=3_600.0)
    maximum_physical_attempts_per_judgment: Literal[3]
    resume_policy: Literal["unresolved-with-remaining-attempt-budget-only-v1"]

    @model_validator(mode="after")
    def _validate_parameters(self) -> FormalRunParameters:
        values = (
            self.request_timeout_seconds,
            self.retry_backoff_seconds,
            self.backoff_ceiling_seconds,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Formal execution timing values must be finite")
        if self.max_in_flight > self.worker_count:
            raise ValueError("Formal max-in-flight cannot exceed worker count")
        if self.retry_backoff_seconds > self.backoff_ceiling_seconds:
            raise ValueError("Formal retry backoff cannot exceed its ceiling")
        return self


class FormalProviderCap(_FrozenModel):
    provider_route: str
    requested_models: tuple[str, ...]
    logical_judgment_cap: int = Field(ge=1)
    physical_attempt_cap: int = Field(ge=1)
    cap_kind: Literal["provider_fee_cny", "gateway_quota", "subscription_quota"]
    currency: Literal["CNY"] | None
    fee_ceiling: float | None

    @model_validator(mode="after")
    def _validate_fee(self) -> FormalProviderCap:
        if self.fee_ceiling is not None and (
            not math.isfinite(self.fee_ceiling) or self.fee_ceiling < 0.0
        ):
            raise ValueError("Formal Provider fee ceiling must be finite and non-negative")
        return self


class ConcurrentRobustnessFormalExecutionRequest(_FrozenModel):
    """Caller-owned facts that the local Gate can validate without credentials."""

    schema_version: Literal["concurrent-robustness-formal-execution-request-v1"] = (
        FORMAL_EXECUTION_REQUEST_SCHEMA
    )
    manifest: FormalArtifactReference
    qualification_artifacts: tuple[FormalQualificationArtifactReference, ...]
    provider_routes: tuple[FormalProviderRoute, ...]
    run_parameters: FormalRunParameters
    provider_caps: tuple[FormalProviderCap, ...]
    logical_judgment_cap: Literal[36000]
    physical_attempt_cap: Literal[108000]
    output_identity: str
    output_root: Path

    @field_validator("output_identity")
    @classmethod
    def _output_identity(cls, value: str) -> str:
        if _OUTPUT_IDENTITY_PATTERN.fullmatch(value) is None:
            raise ValueError("Formal output identity is not a bounded stable token")
        return value

    @field_validator("output_root", mode="before")
    @classmethod
    def _output_root(cls, value: object) -> Path:
        return _safe_path(_absolute_path(value), "Formal output root")

    @model_validator(mode="after")
    def _canonical_orders(self) -> ConcurrentRobustnessFormalExecutionRequest:
        if tuple(row.requested_model for row in self.qualification_artifacts) != _V2_MODELS:
            raise ValueError("Formal qualification references must cover five models in canonical order")
        if tuple(row.requested_model for row in self.provider_routes) != _V2_MODELS:
            raise ValueError("Formal Provider routes must cover five models in canonical order")
        return self


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _collect_object_pairs(label: str):  # type: ignore[no-untyped-def]
    def collect(pairs: list[tuple[str, object]]) -> dict[str, object]:
        keys = [key for key, _ in pairs]
        if len(keys) != len(set(keys)):
            raise ConcurrentRobustnessFormalPreflightError(
                f"{label} contains duplicate fields"
            )
        return dict(pairs)

    return collect


def _load_canonical_object(path: Path, label: str) -> tuple[dict[str, object], bytes]:
    if path.is_symlink() or not path.is_file():
        raise ConcurrentRobustnessFormalPreflightError(
            f"{label} must be a regular non-symlink file"
        )
    try:
        payload = path.read_bytes()
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_collect_object_pairs(label),
        )
    except ConcurrentRobustnessFormalPreflightError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConcurrentRobustnessFormalPreflightError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise ConcurrentRobustnessFormalPreflightError(f"{label} must be a JSON object")
    if payload != _canonical_json_bytes(value):
        raise ConcurrentRobustnessFormalPreflightError(
            f"{label} must use canonical JSON serialization"
        )
    return cast(dict[str, object], value), payload


def _load_referenced_object(
    reference: FormalArtifactReference,
    label: str,
) -> tuple[dict[str, object], bytes]:
    document, payload = _load_canonical_object(reference.path, label)
    if _sha256_bytes(payload) != reference.sha256:
        raise ConcurrentRobustnessFormalPreflightError(f"{label} hash is crossed")
    return document, payload


def _parse_utc(value: object, label: str) -> datetime:
    if not isinstance(value, str) or _UTC_PATTERN.fullmatch(value) is None:
        raise ConcurrentRobustnessFormalPreflightError(f"{label} must be a UTC second token")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ConcurrentRobustnessFormalPreflightError(f"{label} is invalid") from exc


def _validate_current_window(
    *,
    starts_at: object,
    expires_at: object,
    label: str,
    maximum_window: timedelta,
    now: datetime,
) -> None:
    start = _parse_utc(starts_at, f"{label} start")
    end = _parse_utc(expires_at, f"{label} expiry")
    if end <= start or end - start > maximum_window:
        raise ConcurrentRobustnessFormalPreflightError(f"{label} validity window is invalid")
    if start > now or now >= end:
        raise ConcurrentRobustnessFormalPreflightError(f"{label} is not currently valid")


def _expected_routes() -> tuple[dict[str, object], ...]:
    by_model = {
        str(disclosure["requested_model"]): disclosure
        for disclosure in robustness_provider_disclosures()
    }
    return tuple(
        {
            "requested_model": model,
            "required_observed_model": _V2_REQUIRED_OBSERVED_MODELS[model],
            "provider_route": by_model[model]["provider_route"],
            "credential_route": _CREDENTIAL_ROUTES[model],
        }
        for model in _V2_MODELS
    )


def _expected_provider_caps() -> tuple[dict[str, object], ...]:
    route_by_model = {
        row["requested_model"]: row["provider_route"] for row in _expected_routes()
    }
    return tuple(
        {
            "provider_route": route_by_model[model],
            "requested_models": [model],
            "logical_judgment_cap": _V2_FORMAL_LOGICAL_PER_MODEL,
            "physical_attempt_cap": _V2_FORMAL_PHYSICAL_PER_MODEL,
            "cap_kind": (
                "provider_fee_cny"
                if model == "deepseek-v4-flash"
                else "gateway_quota"
                if model.startswith("gemini-")
                else "subscription_quota"
            ),
            "currency": "CNY" if model == "deepseek-v4-flash" else None,
            "fee_ceiling": 25.0 if model == "deepseek-v4-flash" else None,
        }
        for model in _V2_MODELS
    )


def _manifest_from_request(
    request: ConcurrentRobustnessFormalExecutionRequest,
) -> tuple[ConcurrentRobustnessManifestV2, dict[str, object]]:
    document, _ = _load_referenced_object(request.manifest, "Formal v2 study manifest")
    try:
        manifest = ConcurrentRobustnessManifestV2.model_validate(document)
    except ValueError as exc:
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal v2 study manifest contract is invalid"
        ) from exc
    if manifest.execution_profile != "formal":
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal preflight requires the exact live execution profile"
        )
    if (
        manifest.output_identity != request.output_identity
        or manifest.request_caps.logical_judgment_cap != _V2_FORMAL_LOGICAL_CAP
        or manifest.request_caps.physical_attempt_cap != _V2_FORMAL_PHYSICAL_CAP
        or manifest.request_caps.logical_judgments_per_cell != _V2_FORMAL_LOGICAL_PER_CELL
    ):
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal manifest output identity or denominator is crossed"
        )
    return manifest, document


def _validate_source_artifacts(
    manifest: ConcurrentRobustnessManifestV2,
    request: ConcurrentRobustnessFormalExecutionRequest,
) -> dict[str, object]:
    source = manifest.source
    try:
        source_path = _safe_path(source.source_dir, "Formal source root")
        for relative_path in (row.relative_path for row in source.artifacts):
            _safe_path(Path(relative_path), "Formal source artifact path")
    except ValueError as exc:
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal source contains a secret-like path"
        ) from exc
    if (
        source.kind != "formal"
        or source_path.is_symlink()
        or not source_path.is_dir()
        or source.source_id != source_path.name
    ):
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal source identity must reference one explicit real directory"
        )
    declared = {row.relative_path: row.sha256 for row in source.artifacts}
    try:
        actual = {
            path.relative_to(source_path).as_posix(): path
            for path in source_path.rglob("*")
            if path.is_file() or path.is_symlink()
        }
    except OSError as exc:
        raise ConcurrentRobustnessFormalPreflightError("Formal source is unreadable") from exc
    if set(actual) != set(declared):
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal source artifact inventory is crossed"
        )
    for relative_path, expected_hash in declared.items():
        path = actual[relative_path]
        if path.is_symlink() or not path.is_file() or _sha256_file(path) != expected_hash:
            raise ConcurrentRobustnessFormalPreflightError(
                "Formal source contains a non-regular or hash-crossed artifact"
            )
    protected_inputs = [request.manifest.path, *(row.path for row in request.qualification_artifacts)]
    if any(
        path == request.output_root or path.is_relative_to(request.output_root)
        for path in protected_inputs
    ):
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal contract artifacts must remain outside the output root"
        )
    if request.output_root == source_path or request.output_root.is_relative_to(source_path):
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal output root must remain outside the frozen source"
        )
    if request.output_root.is_symlink() or (
        request.output_root.exists() and not request.output_root.is_dir()
    ):
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal output root must be absent or a real resumable directory"
        )
    return {
        "source_id": source.source_id,
        "source_root": str(source_path),
        "source_manifest_schema": source.manifest_schema,
        "source_manifest_sha256": source.manifest_sha256,
        "artifact_count": len(declared),
        "artifact_sha256": dict(sorted(declared.items())),
    }


def _validate_qualification(
    *,
    reference: FormalQualificationArtifactReference,
    route: FormalProviderRoute,
    now: datetime,
) -> dict[str, object]:
    document, _ = _load_referenced_object(
        reference,
        "Formal model qualification artifact",
    )
    expected_fields = {
        "schema_version",
        "qualification_kind",
        "qualification_reference",
        "qualified_at_utc",
        "expires_at_utc",
        "provider_route",
        "credential_route",
        "requested_model",
        "observed_model",
        "status",
        "structured_decision_valid",
        "usage_complete",
        "raw_prompt_persisted",
        "raw_response_persisted",
        "credential_material_persisted",
    }
    if set(document) != expected_fields:
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal model qualification fields are missing or unexpected"
        )
    qualification_reference = document.get("qualification_reference")
    if not isinstance(qualification_reference, str):
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal model qualification reference is invalid"
        )
    try:
        _safe_reference(qualification_reference, "qualification reference")
    except ValueError as exc:
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal model qualification reference is unsafe"
        ) from exc
    expected = {
        "schema_version": FORMAL_QUALIFICATION_SCHEMA,
        "qualification_kind": "independent_provider_observed",
        "provider_route": route.provider_route,
        "credential_route": route.credential_route,
        "requested_model": route.requested_model,
        "observed_model": route.required_observed_model,
        "status": "qualified",
        "structured_decision_valid": True,
        "usage_complete": True,
        "raw_prompt_persisted": False,
        "raw_response_persisted": False,
        "credential_material_persisted": False,
    }
    if any(document.get(key) != value for key, value in expected.items()):
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal model qualification identity, route, or status is crossed"
        )
    _validate_current_window(
        starts_at=document.get("qualified_at_utc"),
        expires_at=document.get("expires_at_utc"),
        label="Formal model qualification",
        maximum_window=_MAX_QUALIFICATION_WINDOW,
        now=now,
    )
    return {
        "requested_model": reference.requested_model,
        "artifact_path": str(reference.path),
        "artifact_sha256": reference.sha256,
        "evidence": document,
    }


def _validated_request_identity(
    request: ConcurrentRobustnessFormalExecutionRequest,
) -> dict[str, object]:
    manifest, _ = _manifest_from_request(request)
    source = _validate_source_artifacts(manifest, request)
    route_documents = [row.model_dump(mode="json") for row in request.provider_routes]
    if route_documents != list(_expected_routes()):
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal Provider or credential routes are crossed"
        )
    if (
        request.run_parameters.worker_count != 1
        or request.run_parameters.max_in_flight != 1
        or not math.isclose(
            request.run_parameters.request_timeout_seconds,
            manifest.request_contract.timeout_seconds,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        or not math.isclose(
            request.run_parameters.retry_backoff_seconds,
            manifest.request_contract.retry_backoff_seconds,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        or not math.isclose(
            request.run_parameters.backoff_ceiling_seconds,
            FORMAL_BACKOFF_CEILING_SECONDS,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        or request.run_parameters.maximum_physical_attempts_per_judgment
        != _V2_MAXIMUM_ATTEMPTS
    ):
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal worker, in-flight, timeout, or backoff policy is crossed"
        )
    cap_documents = [row.model_dump(mode="json") for row in request.provider_caps]
    if cap_documents != list(_expected_provider_caps()):
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal Provider caps or billing semantics are crossed"
        )
    if (
        request.logical_judgment_cap != _V2_FORMAL_LOGICAL_CAP
        or request.physical_attempt_cap != _V2_FORMAL_PHYSICAL_CAP
        or sum(row.logical_judgment_cap for row in request.provider_caps)
        != request.logical_judgment_cap
        or sum(row.physical_attempt_cap for row in request.provider_caps)
        != request.physical_attempt_cap
    ):
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal global and per-model caps do not close"
        )
    now = _utc_now()
    qualification_documents = [
        _validate_qualification(reference=reference, route=route, now=now)
        for reference, route in zip(
            request.qualification_artifacts,
            request.provider_routes,
            strict=True,
        )
    ]
    allowed_cell_ids = [cell.cell_id for cell in manifest.prompt_model_cells]
    prompt_contracts = [
        {
            "prompt_variant": prompt.variant_id,
            "prompt_version": prompt.prompt_version,
            "prompt_canonical_hash": prompt.canonical_hash,
        }
        for prompt in CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.all()
    ]
    for model_index, model in enumerate(_V2_MODELS):
        start = model_index * _V2_CELLS_PER_MODEL
        model_cells = manifest.prompt_model_cells[start : start + _V2_CELLS_PER_MODEL]
        if [
            {
                "prompt_variant": cell.prompt_variant,
                "prompt_version": cell.prompt_version,
                "prompt_canonical_hash": cell.prompt_canonical_hash,
            }
            for cell in model_cells
        ] != prompt_contracts or any(cell.requested_model != model for cell in model_cells):
            raise ConcurrentRobustnessFormalPreflightError(
                "Formal model-major P0-P3 Prompt schedule is crossed"
            )
    return {
        "schema_version": FORMAL_EXECUTION_REQUEST_IDENTITY_SCHEMA,
        "manifest": request.manifest.model_dump(mode="json"),
        "source": source,
        "allowed_cell_ids": allowed_cell_ids,
        "model_conditions": route_documents,
        "prompt_contracts": prompt_contracts,
        "qualification_artifacts": qualification_documents,
        "run_parameters": request.run_parameters.model_dump(mode="json"),
        "provider_caps": cap_documents,
        "logical_judgment_cap": request.logical_judgment_cap,
        "physical_attempt_cap": request.physical_attempt_cap,
        "output_identity": request.output_identity,
        "output_root": str(request.output_root),
        "lifecycle_policy": _expected_lifecycle_policy(),
        "formal_run_scope": FORMAL_RUN_SCOPE,
        "release_authorized": False,
        "deployment_authorized": False,
        "production_deploy_eligible": False,
    }


def _authorization_template(
    *,
    request_identity: Mapping[str, object],
    request_identity_sha256: str,
    readiness_sha256: str,
) -> dict[str, object]:
    return {
        "schema_version": FORMAL_AUTHORIZATION_SCHEMA,
        "authorization_kind": "explicit_formal_live_provider",
        "authorization_status": "approved",
        "authorization_reference": "REPLACE-WITH-INDEPENDENT-OPERATIONAL-ISSUE",
        "authorized_at_utc": "REPLACE-WITH-UTC-SECOND",
        "expires_at_utc": "REPLACE-WITH-UTC-SECOND-WITHIN-24-HOURS",
        "readiness_sha256": readiness_sha256,
        "request_identity_sha256": request_identity_sha256,
        "request_identity": dict(request_identity),
        "external_requests_allowed": True,
        "formal_run_authorized": True,
        "release_authorized": False,
        "deployment_authorized": False,
        "production_deploy_eligible": False,
    }


def _handoff(
    *,
    request_identity: Mapping[str, object],
    request_identity_sha256: str,
    readiness_sha256: str,
    authorization_template: Mapping[str, object],
) -> dict[str, object]:
    source = cast(Mapping[str, object], request_identity["source"])
    parameters = cast(Mapping[str, object], request_identity["run_parameters"])
    body = "\n".join(
        (
            "## Formal execution authorization request",
            "",
            f"- Readiness SHA-256: `{readiness_sha256}`",
            f"- Request identity SHA-256: `{request_identity_sha256}`",
            f"- Source: `{source['source_id']}` / `{source['source_manifest_sha256']}`",
            f"- Output identity: `{request_identity['output_identity']}`",
            "- Cells: `5 serial model batches × P0-P3 = 20`",
            "- Per model: `7,200 logical / 21,600 physical attempts`; next model waits for closure.",
            "- Caps: `36,000 logical / 108,000 physical attempts`",
            (
                "- Runtime: "
                f"`workers={parameters['worker_count']}` / "
                f"`max_in_flight={parameters['max_in_flight']}` / "
                f"`timeout={parameters['request_timeout_seconds']}s` / "
                f"`backoff={parameters['retry_backoff_seconds']}..{parameters['backoff_ceiling_seconds']}s`"
            ),
            "- DeepSeek cash ceiling: `CNY ¥25`; gateway and subscription quotas remain separate.",
            "- Qualification artifacts: five independent, hash-bound, currently valid Provider observations.",
            "- This request does not authorize Release or Deployment.",
            "",
            "## Decision requested",
            "",
            "Review the exact identity above. If approved, persist the following template as canonical JSON after replacing only the three `REPLACE-*` values:",
            "",
            "```json",
            json.dumps(authorization_template, ensure_ascii=False, sort_keys=True, indent=2),
            "```",
        )
    )
    return {
        "title": f"授权五 Provider Formal execution：{request_identity['output_identity']}",
        "labels": ["ready-for-human"],
        "body": body,
    }


def authorization_readiness(
    request: ConcurrentRobustnessFormalExecutionRequest,
) -> dict[str, object]:
    """Validate all non-authorization facts and return a zero-call handoff."""

    if not isinstance(request, ConcurrentRobustnessFormalExecutionRequest):
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal preflight requires a typed immutable execution request"
        )
    try:
        request = ConcurrentRobustnessFormalExecutionRequest.model_validate(
            request.model_dump(mode="python")
        )
    except ValueError as exc:
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal execution request contains missing, extra, or malformed facts"
        ) from exc
    request_identity = _validated_request_identity(request)
    request_identity_sha256 = _sha256_bytes(_canonical_json_bytes(request_identity))
    base: dict[str, object] = {
        "schema_version": FORMAL_READINESS_SCHEMA,
        "status": "ready_for_human",
        "authorization_schema_version": FORMAL_AUTHORIZATION_SCHEMA,
        "request_identity": request_identity,
        "request_identity_sha256": request_identity_sha256,
        "provider_calls": 0,
        "live_api_triggered": False,
        "credential_read_triggered": False,
        "output_workspace_created": False,
        "formal_run_authorized": False,
        "release_authorized": False,
        "deployment_authorized": False,
        "production_deploy_eligible": False,
    }
    readiness_sha256 = _sha256_bytes(_canonical_json_bytes(base))
    template = _authorization_template(
        request_identity=request_identity,
        request_identity_sha256=request_identity_sha256,
        readiness_sha256=readiness_sha256,
    )
    return {
        **base,
        "readiness_sha256": readiness_sha256,
        "authorization_template": template,
        "operational_issue_handoff": _handoff(
            request_identity=request_identity,
            request_identity_sha256=request_identity_sha256,
            readiness_sha256=readiness_sha256,
            authorization_template=template,
        ),
    }


def _validate_authorization_document(
    *,
    request: ConcurrentRobustnessFormalExecutionRequest,
    readiness: Mapping[str, object],
    authorization_path: Path,
    authorization_sha256: str,
) -> tuple[dict[str, object], bytes]:
    try:
        reference = FormalArtifactReference(
            path=_safe_path(authorization_path, "Formal authorization path"),
            sha256=authorization_sha256,
        )
    except ValueError as exc:
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal authorization artifact reference is invalid"
        ) from exc
    protected = {
        request.manifest.path,
        *(row.path for row in request.qualification_artifacts),
    }
    if (
        reference.path in protected
        or reference.path == request.output_root
        or reference.path.is_relative_to(request.output_root)
        or reference.path == Path(
            cast(Mapping[str, object], readiness["request_identity"])["source"]["source_root"]  # type: ignore[index]
        )
        or reference.path.is_relative_to(
            Path(cast(Mapping[str, object], readiness["request_identity"])["source"]["source_root"])  # type: ignore[index]
        )
    ):
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal authorization artifact must remain independent of source and output roots"
        )
    document, payload = _load_referenced_object(reference, "Formal authorization artifact")
    template = cast(Mapping[str, object], readiness["authorization_template"])
    if set(document) != set(template):
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal authorization fields are missing or unexpected"
        )
    fixed_fields = set(template) - {
        "authorization_reference",
        "authorized_at_utc",
        "expires_at_utc",
    }
    if any(document.get(key) != template[key] for key in fixed_fields):
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal authorization is crossed with the hash-bound readiness"
        )
    authorization_reference = document.get("authorization_reference")
    if not isinstance(authorization_reference, str) or authorization_reference.startswith("REPLACE-"):
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal authorization reference is not explicit"
        )
    try:
        _safe_reference(authorization_reference, "authorization reference")
    except ValueError as exc:
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal authorization reference is unsafe"
        ) from exc
    _validate_current_window(
        starts_at=document.get("authorized_at_utc"),
        expires_at=document.get("expires_at_utc"),
        label="Formal authorization",
        maximum_window=_MAX_AUTHORIZATION_WINDOW,
        now=_utc_now(),
    )
    return document, payload


def _plan_body(
    *,
    request: ConcurrentRobustnessFormalExecutionRequest,
    readiness: Mapping[str, object],
    authorization_path: Path,
    authorization_sha256: str,
    authorization: Mapping[str, object],
) -> dict[str, object]:
    return {
        "schema_version": FORMAL_EXECUTION_PLAN_SCHEMA,
        "status": "authorized_for_formal_execution",
        "request": request.model_dump(mode="json"),
        "request_identity": readiness["request_identity"],
        "request_identity_sha256": readiness["request_identity_sha256"],
        "readiness_sha256": readiness["readiness_sha256"],
        "authorization_artifact_path": str(authorization_path),
        "authorization_sha256": authorization_sha256,
        "authorization": dict(authorization),
        "provider_calls_during_preflight": 0,
        "live_api_triggered_during_preflight": False,
        "credential_read_triggered_during_preflight": False,
        "output_workspace_created_during_preflight": False,
        "formal_run_authorized": True,
        "release_authorized": False,
        "deployment_authorized": False,
        "production_deploy_eligible": False,
    }


def _validate_plan_output(
    plan_output: Path,
    *,
    request: ConcurrentRobustnessFormalExecutionRequest,
    authorization_path: Path,
    source_root: Path,
) -> Path:
    try:
        target = _safe_path(_absolute_path(plan_output), "Formal execution plan path")
    except ValueError as exc:
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal execution plan path is unsafe"
        ) from exc
    protected_files = {
        request.manifest.path,
        authorization_path,
        *(row.path for row in request.qualification_artifacts),
    }
    if (
        target in protected_files
        or target == request.output_root
        or target.is_relative_to(request.output_root)
        or target == source_root
        or target.is_relative_to(source_root)
    ):
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal execution plan must remain outside inputs, source, and output roots"
        )
    parent = target.parent
    if parent.is_symlink() or not parent.is_dir() or target.exists() or target.is_symlink():
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal execution plan destination must be a new file in a real directory"
        )
    return target


def _write_new_canonical_file(path: Path, document: Mapping[str, object]) -> None:
    try:
        with path.open("xb") as handle:
            handle.write(_canonical_json_bytes(document))
            handle.flush()
            os.fsync(handle.fileno())
        path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as exc:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal execution plan could not be written atomically"
        ) from exc


def authorize_formal_execution(
    *,
    request: ConcurrentRobustnessFormalExecutionRequest,
    authorization_path: Path | None,
    plan_output: Path,
    authorization_sha256: str | None = None,
) -> dict[str, object]:
    """Close an execution plan locally; Provider clients belong after this call."""

    readiness = authorization_readiness(request)
    if authorization_path is None:
        if authorization_sha256 is not None:
            raise ConcurrentRobustnessFormalPreflightError(
                "Formal authorization path and hash must be supplied together"
            )
        raise ConcurrentRobustnessFormalAuthorizationRequired(readiness)
    if authorization_sha256 is None:
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal authorization path and hash must be supplied together"
        )
    normalized_authorization_path = _absolute_path(authorization_path)
    authorization, _ = _validate_authorization_document(
        request=request,
        readiness=readiness,
        authorization_path=normalized_authorization_path,
        authorization_sha256=authorization_sha256,
    )
    request_identity = cast(Mapping[str, object], readiness["request_identity"])
    source = cast(Mapping[str, object], request_identity["source"])
    target = _validate_plan_output(
        plan_output,
        request=request,
        authorization_path=normalized_authorization_path,
        source_root=Path(cast(str, source["source_root"])),
    )
    body = _plan_body(
        request=request,
        readiness=readiness,
        authorization_path=normalized_authorization_path,
        authorization_sha256=authorization_sha256,
        authorization=authorization,
    )
    plan = {
        **body,
        "plan_identity_sha256": _sha256_bytes(_canonical_json_bytes(body)),
    }
    _write_new_canonical_file(target, plan)
    try:
        validated = validate_formal_execution_plan(target)
    except Exception:
        try:
            target.unlink()
        except OSError:
            pass
        raise
    return validated


def _request_from_plan(value: object) -> ConcurrentRobustnessFormalExecutionRequest:
    if not isinstance(value, Mapping):
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal execution plan request is malformed"
        )
    try:
        return ConcurrentRobustnessFormalExecutionRequest.model_validate(value)
    except ValueError as exc:
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal execution plan request is malformed"
        ) from exc


def _validate_embedded_qualification(
    value: object,
    *,
    reference: FormalQualificationArtifactReference,
    route: FormalProviderRoute,
) -> None:
    if not isinstance(value, Mapping):
        raise ConcurrentRobustnessFormalPreflightError(
            "embedded Formal qualification is malformed"
        )
    expected_fields = {
        "schema_version",
        "qualification_kind",
        "qualification_reference",
        "qualified_at_utc",
        "expires_at_utc",
        "provider_route",
        "credential_route",
        "requested_model",
        "observed_model",
        "status",
        "structured_decision_valid",
        "usage_complete",
        "raw_prompt_persisted",
        "raw_response_persisted",
        "credential_material_persisted",
    }
    qualification_reference = value.get("qualification_reference")
    if set(value) != expected_fields or not isinstance(qualification_reference, str):
        raise ConcurrentRobustnessFormalPreflightError(
            "embedded Formal qualification fields are not exact"
        )
    try:
        _safe_reference(qualification_reference, "qualification reference")
    except ValueError as exc:
        raise ConcurrentRobustnessFormalPreflightError(
            "embedded Formal qualification reference is unsafe"
        ) from exc
    expected = {
        "schema_version": FORMAL_QUALIFICATION_SCHEMA,
        "qualification_kind": "independent_provider_observed",
        "provider_route": route.provider_route,
        "credential_route": route.credential_route,
        "requested_model": route.requested_model,
        "observed_model": route.required_observed_model,
        "status": "qualified",
        "structured_decision_valid": True,
        "usage_complete": True,
        "raw_prompt_persisted": False,
        "raw_response_persisted": False,
        "credential_material_persisted": False,
    }
    if any(value.get(key) != expected_value for key, expected_value in expected.items()):
        raise ConcurrentRobustnessFormalPreflightError(
            "embedded Formal qualification identity or status is crossed"
        )
    start = _parse_utc(value.get("qualified_at_utc"), "embedded qualification start")
    end = _parse_utc(value.get("expires_at_utc"), "embedded qualification expiry")
    if end <= start or end - start > _MAX_QUALIFICATION_WINDOW:
        raise ConcurrentRobustnessFormalPreflightError(
            "embedded Formal qualification validity window is invalid"
        )


def _expected_source_identity(
    manifest: ConcurrentRobustnessManifestV2,
) -> dict[str, object]:
    artifacts = {
        row.relative_path: row.sha256
        for row in manifest.source.artifacts
    }
    return {
        "source_id": manifest.source.source_id,
        "source_root": str(manifest.source.source_dir),
        "source_manifest_schema": manifest.source.manifest_schema,
        "source_manifest_sha256": manifest.source.manifest_sha256,
        "artifact_count": len(artifacts),
        "artifact_sha256": dict(sorted(artifacts.items())),
    }


def _expected_lifecycle_policy() -> dict[str, object]:
    return {
        "resumable": "safe_pre_dispatch_or_persisted_terminal_interruption_with_remaining_budget",
        "stopped": "attempts_exhausted_or_nonretryable_failure_no_same-output-resume",
        "reconciliation_required": "unknown_dispatch_provenance_no_automatic_resend",
        "resume_policy": FORMAL_RESUME_POLICY,
        "model_batch_policy": FORMAL_MODEL_BATCH_POLICY,
    }


def validate_embedded_formal_execution_plan(
    plan: object,
    *,
    expected_manifest: ConcurrentRobustnessManifestV2,
    expected_output_root: str | Path | None = None,
) -> dict[str, object]:
    """Validate persisted legal lineage without recency or external-file reads."""

    if not isinstance(plan, Mapping):
        raise ConcurrentRobustnessFormalPreflightError(
            "embedded Formal execution plan must be an object"
        )
    document = dict(plan)
    expected_fields = {
        "schema_version",
        "status",
        "request",
        "request_identity",
        "request_identity_sha256",
        "readiness_sha256",
        "authorization_artifact_path",
        "authorization_sha256",
        "authorization",
        "provider_calls_during_preflight",
        "live_api_triggered_during_preflight",
        "credential_read_triggered_during_preflight",
        "output_workspace_created_during_preflight",
        "formal_run_authorized",
        "release_authorized",
        "deployment_authorized",
        "production_deploy_eligible",
        "plan_identity_sha256",
    }
    if (
        set(document) != expected_fields
        or document.get("schema_version") != FORMAL_EXECUTION_PLAN_SCHEMA
        or document.get("status") != "authorized_for_formal_execution"
        or document.get("provider_calls_during_preflight") != 0
        or document.get("live_api_triggered_during_preflight") is not False
        or document.get("credential_read_triggered_during_preflight") is not False
        or document.get("output_workspace_created_during_preflight") is not False
        or document.get("formal_run_authorized") is not True
        or document.get("release_authorized") is not False
        or document.get("deployment_authorized") is not False
        or document.get("production_deploy_eligible") is not False
    ):
        raise ConcurrentRobustnessFormalPreflightError(
            "embedded Formal execution plan fields or scope are crossed"
        )
    body = {
        key: value
        for key, value in document.items()
        if key != "plan_identity_sha256"
    }
    if document.get("plan_identity_sha256") != _sha256_bytes(_canonical_json_bytes(body)):
        raise ConcurrentRobustnessFormalPreflightError(
            "embedded Formal execution plan identity is crossed"
        )
    request = _request_from_plan(document.get("request"))
    if (
        expected_manifest.execution_profile != "formal"
        or request.output_identity != expected_manifest.output_identity
        or request.manifest.sha256
        != _sha256_bytes(_canonical_json_bytes(expected_manifest.model_dump(mode="json")))
        or request.logical_judgment_cap != _V2_FORMAL_LOGICAL_CAP
        or request.physical_attempt_cap != _V2_FORMAL_PHYSICAL_CAP
    ):
        raise ConcurrentRobustnessFormalPreflightError(
            "embedded Formal request is crossed with the study manifest"
        )
    if expected_output_root is not None and _absolute_path(expected_output_root) != request.output_root:
        raise ConcurrentRobustnessFormalPreflightError(
            "embedded Formal request is crossed with the output root"
        )
    identity = document.get("request_identity")
    if not isinstance(identity, Mapping):
        raise ConcurrentRobustnessFormalPreflightError(
            "embedded Formal request identity is malformed"
        )
    identity_fields = {
        "schema_version",
        "manifest",
        "source",
        "allowed_cell_ids",
        "model_conditions",
        "prompt_contracts",
        "qualification_artifacts",
        "run_parameters",
        "provider_caps",
        "logical_judgment_cap",
        "physical_attempt_cap",
        "output_identity",
        "output_root",
        "lifecycle_policy",
        "formal_run_scope",
        "release_authorized",
        "deployment_authorized",
        "production_deploy_eligible",
    }
    routes = [row.model_dump(mode="json") for row in request.provider_routes]
    caps = [row.model_dump(mode="json") for row in request.provider_caps]
    prompts = [
        {
            "prompt_variant": prompt.variant_id,
            "prompt_version": prompt.prompt_version,
            "prompt_canonical_hash": prompt.canonical_hash,
        }
        for prompt in CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.all()
    ]
    fixed_identity = {
        "schema_version": FORMAL_EXECUTION_REQUEST_IDENTITY_SCHEMA,
        "manifest": request.manifest.model_dump(mode="json"),
        "source": _expected_source_identity(expected_manifest),
        "allowed_cell_ids": [cell.cell_id for cell in expected_manifest.prompt_model_cells],
        "model_conditions": routes,
        "prompt_contracts": prompts,
        "run_parameters": request.run_parameters.model_dump(mode="json"),
        "provider_caps": caps,
        "logical_judgment_cap": request.logical_judgment_cap,
        "physical_attempt_cap": request.physical_attempt_cap,
        "output_identity": request.output_identity,
        "output_root": str(request.output_root),
        "lifecycle_policy": _expected_lifecycle_policy(),
        "formal_run_scope": FORMAL_RUN_SCOPE,
        "release_authorized": False,
        "deployment_authorized": False,
        "production_deploy_eligible": False,
    }
    if set(identity) != identity_fields or any(
        identity.get(key) != value
        for key, value in fixed_identity.items()
        if key != "qualification_artifacts"
    ):
        raise ConcurrentRobustnessFormalPreflightError(
            "embedded Formal request identity is crossed"
        )
    qualification_rows = identity.get("qualification_artifacts")
    if not isinstance(qualification_rows, Sequence) or isinstance(
        qualification_rows, (str, bytes)
    ) or len(qualification_rows) != len(request.qualification_artifacts):
        raise ConcurrentRobustnessFormalPreflightError(
            "embedded Formal qualification inventory is malformed"
        )
    for row, reference, route in zip(
        qualification_rows,
        request.qualification_artifacts,
        request.provider_routes,
        strict=True,
    ):
        if not isinstance(row, Mapping) or (
            set(row) != {"requested_model", "artifact_path", "artifact_sha256", "evidence"}
            or row.get("requested_model") != reference.requested_model
            or row.get("artifact_path") != str(reference.path)
            or row.get("artifact_sha256") != reference.sha256
        ):
            raise ConcurrentRobustnessFormalPreflightError(
                "embedded Formal qualification reference is crossed"
            )
        qualification_evidence = row.get("evidence")
        if not isinstance(qualification_evidence, Mapping) or _sha256_bytes(
            _canonical_json_bytes(dict(qualification_evidence))
        ) != reference.sha256:
            raise ConcurrentRobustnessFormalPreflightError(
                "embedded Formal qualification bytes are crossed"
            )
        _validate_embedded_qualification(
            qualification_evidence,
            reference=reference,
            route=route,
        )
    request_identity_sha256 = _sha256_bytes(_canonical_json_bytes(dict(identity)))
    if document.get("request_identity_sha256") != request_identity_sha256:
        raise ConcurrentRobustnessFormalPreflightError(
            "embedded Formal request identity hash is crossed"
        )
    readiness_base = {
        "schema_version": FORMAL_READINESS_SCHEMA,
        "status": "ready_for_human",
        "authorization_schema_version": FORMAL_AUTHORIZATION_SCHEMA,
        "request_identity": dict(identity),
        "request_identity_sha256": request_identity_sha256,
        "provider_calls": 0,
        "live_api_triggered": False,
        "credential_read_triggered": False,
        "output_workspace_created": False,
        "formal_run_authorized": False,
        "release_authorized": False,
        "deployment_authorized": False,
        "production_deploy_eligible": False,
    }
    readiness_sha256 = _sha256_bytes(_canonical_json_bytes(readiness_base))
    if document.get("readiness_sha256") != readiness_sha256:
        raise ConcurrentRobustnessFormalPreflightError(
            "embedded Formal readiness hash is crossed"
        )
    authorization = document.get("authorization")
    authorization_sha256 = document.get("authorization_sha256")
    authorization_path = document.get("authorization_artifact_path")
    try:
        normalized_authorization_path = (
            _safe_path(
                _absolute_path(authorization_path),
                "embedded Formal authorization path",
            )
            if isinstance(authorization_path, str)
            else None
        )
    except ValueError as exc:
        raise ConcurrentRobustnessFormalPreflightError(
            "embedded Formal authorization path is unsafe"
        ) from exc
    if (
        not isinstance(authorization, Mapping)
        or not isinstance(authorization_sha256, str)
        or _SHA256_PATTERN.fullmatch(authorization_sha256) is None
        or _sha256_bytes(_canonical_json_bytes(dict(authorization)))
        != authorization_sha256
        or not isinstance(authorization_path, str)
        or normalized_authorization_path != Path(authorization_path)
    ):
        raise ConcurrentRobustnessFormalPreflightError(
            "embedded Formal authorization artifact identity is crossed"
        )
    authorization_fields = {
        "schema_version",
        "authorization_kind",
        "authorization_status",
        "authorization_reference",
        "authorized_at_utc",
        "expires_at_utc",
        "readiness_sha256",
        "request_identity_sha256",
        "request_identity",
        "external_requests_allowed",
        "formal_run_authorized",
        "release_authorized",
        "deployment_authorized",
        "production_deploy_eligible",
    }
    authorization_reference = authorization.get("authorization_reference")
    if (
        set(authorization) != authorization_fields
        or authorization.get("schema_version") != FORMAL_AUTHORIZATION_SCHEMA
        or authorization.get("authorization_kind") != "explicit_formal_live_provider"
        or authorization.get("authorization_status") != "approved"
        or authorization.get("readiness_sha256") != readiness_sha256
        or authorization.get("request_identity_sha256") != request_identity_sha256
        or authorization.get("request_identity") != dict(identity)
        or authorization.get("external_requests_allowed") is not True
        or authorization.get("formal_run_authorized") is not True
        or authorization.get("release_authorized") is not False
        or authorization.get("deployment_authorized") is not False
        or authorization.get("production_deploy_eligible") is not False
        or not isinstance(authorization_reference, str)
    ):
        raise ConcurrentRobustnessFormalPreflightError(
            "embedded Formal authorization scope is crossed"
        )
    try:
        _safe_reference(authorization_reference, "authorization reference")
    except ValueError as exc:
        raise ConcurrentRobustnessFormalPreflightError(
            "embedded Formal authorization reference is unsafe"
        ) from exc
    authorization_start = _parse_utc(
        authorization.get("authorized_at_utc"), "embedded authorization start"
    )
    authorization_end = _parse_utc(
        authorization.get("expires_at_utc"), "embedded authorization expiry"
    )
    if (
        authorization_end <= authorization_start
        or authorization_end - authorization_start > _MAX_AUTHORIZATION_WINDOW
    ):
        raise ConcurrentRobustnessFormalPreflightError(
            "embedded Formal authorization validity window is invalid"
        )
    expected_body = _plan_body(
        request=request,
        readiness={
            "request_identity": dict(identity),
            "request_identity_sha256": request_identity_sha256,
            "readiness_sha256": readiness_sha256,
        },
        authorization_path=cast(Path, normalized_authorization_path),
        authorization_sha256=authorization_sha256,
        authorization=authorization,
    )
    if body != expected_body:
        raise ConcurrentRobustnessFormalPreflightError(
            "embedded Formal execution plan drifted from its legal lineage"
        )
    return document


def validate_formal_execution_plan(
    plan_path: str | Path,
    *,
    expected_manifest: ConcurrentRobustnessManifestV2 | None = None,
    expected_output_root: str | Path | None = None,
) -> dict[str, object]:
    """Re-read a plan and all mutable external evidence before Provider setup."""

    path = _absolute_path(plan_path)
    plan, _ = _load_canonical_object(path, "Formal execution plan")
    if path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal execution plan must be immutable"
        )
    expected_fields = {
        "schema_version",
        "status",
        "request",
        "request_identity",
        "request_identity_sha256",
        "readiness_sha256",
        "authorization_artifact_path",
        "authorization_sha256",
        "authorization",
        "provider_calls_during_preflight",
        "live_api_triggered_during_preflight",
        "credential_read_triggered_during_preflight",
        "output_workspace_created_during_preflight",
        "formal_run_authorized",
        "release_authorized",
        "deployment_authorized",
        "production_deploy_eligible",
        "plan_identity_sha256",
    }
    if (
        set(plan) != expected_fields
        or plan.get("schema_version") != FORMAL_EXECUTION_PLAN_SCHEMA
        or plan.get("status") != "authorized_for_formal_execution"
        or plan.get("provider_calls_during_preflight") != 0
        or plan.get("live_api_triggered_during_preflight") is not False
        or plan.get("credential_read_triggered_during_preflight") is not False
        or plan.get("output_workspace_created_during_preflight") is not False
        or plan.get("formal_run_authorized") is not True
        or plan.get("release_authorized") is not False
        or plan.get("deployment_authorized") is not False
        or plan.get("production_deploy_eligible") is not False
    ):
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal execution plan fields or lifecycle scope are crossed"
        )
    body = {key: value for key, value in plan.items() if key != "plan_identity_sha256"}
    if plan.get("plan_identity_sha256") != _sha256_bytes(_canonical_json_bytes(body)):
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal execution plan identity is crossed"
        )
    request = _request_from_plan(plan.get("request"))
    readiness = authorization_readiness(request)
    if (
        plan.get("request_identity") != readiness["request_identity"]
        or plan.get("request_identity_sha256") != readiness["request_identity_sha256"]
        or plan.get("readiness_sha256") != readiness["readiness_sha256"]
    ):
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal execution plan request or readiness identity is crossed"
        )
    authorization_path_raw = plan.get("authorization_artifact_path")
    authorization_sha256 = plan.get("authorization_sha256")
    authorization = plan.get("authorization")
    if (
        not isinstance(authorization_path_raw, str)
        or not isinstance(authorization_sha256, str)
        or not isinstance(authorization, Mapping)
    ):
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal execution plan authorization reference is malformed"
        )
    observed_authorization, _ = _validate_authorization_document(
        request=request,
        readiness=readiness,
        authorization_path=_absolute_path(authorization_path_raw),
        authorization_sha256=authorization_sha256,
    )
    if observed_authorization != dict(authorization):
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal execution plan authorization bytes changed"
        )
    expected_body = _plan_body(
        request=request,
        readiness=readiness,
        authorization_path=_absolute_path(authorization_path_raw),
        authorization_sha256=authorization_sha256,
        authorization=observed_authorization,
    )
    if body != expected_body:
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal execution plan drifted from its validated inputs"
        )
    manifest, _ = _manifest_from_request(request)
    if expected_manifest is not None and (
        not isinstance(expected_manifest, ConcurrentRobustnessManifestV2)
        or expected_manifest.model_dump(mode="json") != manifest.model_dump(mode="json")
    ):
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal execution plan is crossed with the supplied study manifest"
        )
    if expected_output_root is not None and _absolute_path(expected_output_root) != request.output_root:
        raise ConcurrentRobustnessFormalPreflightError(
            "Formal execution plan is crossed with the supplied output root"
        )
    validate_embedded_formal_execution_plan(
        plan,
        expected_manifest=manifest,
        expected_output_root=expected_output_root,
    )
    return plan
