from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .concurrent_message_experiment import (
    CONCURRENT_MESSAGE_CANDIDATE_FIELDS,
    CONCURRENT_MESSAGE_ENGAGED_NEIGHBOR_FORMULA,
    CONCURRENT_MESSAGE_PRODUCTION_DELIVERY_CAPACITY,
    CONCURRENT_MESSAGE_PRODUCTION_HORIZON,
    CONCURRENT_MESSAGE_PRODUCTION_SAMPLE_SIZE,
    CONCURRENT_MESSAGE_RANKING_FORMULA,
)
from .concurrent_message_report import (
    CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_SCHEMA,
    ConcurrentMessageArtifactClosure,
    close_concurrent_message_artifacts,
)
from .decision import LLMDecisionAdapter
from .final_research import FORMAL_RUN_STATUS, SEED_FIRST_SAMPLING_METHOD, VALIDATION_RUN_STATUS
from .prompt_contracts import CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY
from .provider_request_contract import OMITTED_SAMPLING_PARAMETERS, STRUCTURED_OUTPUT_SCHEMA_HASH

__all__ = [
    "ConcurrentRobustnessError",
    "ConcurrentRobustnessErrorCode",
    "ConcurrentRobustnessManifest",
    "ConcurrentRobustnessStudy",
    "ConcurrentRobustnessStudyResult",
    "ConcurrentRobustnessStudyStatus",
]

CONCURRENT_ROBUSTNESS_MANIFEST_SCHEMA = "concurrent-robustness-manifest-v1"
CONCURRENT_ROBUSTNESS_RANKING_CONTRACT_SCHEMA = "concurrent-robustness-ranking-contract-v1"
CONCURRENT_ROBUSTNESS_P95_TOKEN = "holdout-safe-log1p-p95-weighted-degree-v1"
CONCURRENT_ROBUSTNESS_COMPONENT_CONTRACT_TOKEN = "concurrent-ranking-components-v1"
CONCURRENT_ROBUSTNESS_TIE_BREAK_TOKEN = "score-desc-user-id-asc-v1"
CONCURRENT_ROBUSTNESS_SCHEDULE_TOKEN = "shared-seed-launch-then-per-message-top-k-v1"
CONCURRENT_ROBUSTNESS_SCORE_PRECISION_TOKEN = "binary64-full-precision-no-rounding-v1"
CONCURRENT_ROBUSTNESS_DECISION_STORE_POLICY = "fresh-per-cell-no-cache-v1"

_ROBUSTNESS_MESSAGE_IDS = ("message_1", "message_2", "message_3")
_ROBUSTNESS_MODELS = (
    "gpt-5.4-mini",
    "gpt-5.4-2026-03-05",
    "gpt-5.5-2026-04-23",
    "gpt-5.6-sol",
)
_RANKING_COMPONENTS = (
    "base_network_relevance",
    "campaign_engaged_neighbor_signal",
    "normalized_message_user_fit",
)
_BASELINE_WEIGHTS = {
    "base_network_relevance": 0.50,
    "campaign_engaged_neighbor_signal": 0.30,
    "normalized_message_user_fit": 0.20,
}
_TRANSFER_MASSES = (0.05, 0.10, 0.15)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_OUTPUT_IDENTITY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

_RankingComponent = Literal[
    "base_network_relevance",
    "campaign_engaged_neighbor_signal",
    "normalized_message_user_fit",
]
_PromptVariant = Literal["P0", "P1", "P2", "P3"]


class ConcurrentRobustnessStudyStatus(str, Enum):
    """Observable lifecycle status of a robustness study workspace."""

    RESUMABLE = "resumable"
    READY_FOR_HUMAN = "ready_for_human"
    COMPLETE = "complete"


class ConcurrentRobustnessErrorCode(str, Enum):
    """Bounded failure categories exposed by the study Interface."""

    INVALID_MANIFEST = "invalid_manifest"
    UNSUPPORTED_ADAPTERS = "unsupported_adapters"
    INVALID_SOURCE = "invalid_source"
    SOURCE_MUTATED = "source_mutated"
    WORKSPACE_CONFLICT = "workspace_conflict"
    WORKSPACE_CORRUPT = "workspace_corrupt"
    PATH_VIOLATION = "path_violation"
    ANALYSIS_INVALID = "analysis_invalid"


class ConcurrentRobustnessError(ValueError):
    """One bounded study failure with a stable machine-readable code."""

    def __init__(self, code: ConcurrentRobustnessErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


class _FrozenContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _ArtifactHash(_FrozenContractModel):
    relative_path: str
    sha256: str

    @field_validator("relative_path")
    @classmethod
    def _validate_relative_path(cls, value: str) -> str:
        path = Path(value)
        if not value or path.is_absolute() or ".." in path.parts or path.as_posix() != value:
            raise ValueError("source artifact paths must be normalized relative paths")
        return value

    @field_validator("sha256")
    @classmethod
    def _validate_sha256(cls, value: str) -> str:
        if not _SHA256_PATTERN.fullmatch(value):
            raise ValueError("artifact sha256 must be 64 lowercase hexadecimal characters")
        return value


class _SourceIdentity(_FrozenContractModel):
    kind: Literal["formal", "fixture"]
    source_id: str = Field(min_length=1, max_length=160)
    source_dir: Path
    manifest_schema: str
    manifest_sha256: str
    artifacts: tuple[_ArtifactHash, ...]
    candidate_artifact: str
    feedback_artifact: str

    @field_validator("source_dir")
    @classmethod
    def _validate_source_dir(cls, value: Path) -> Path:
        if not value.is_absolute() or ".." in value.parts:
            raise ValueError("formal source path must be absolute and normalized")
        return value

    @field_validator("manifest_sha256")
    @classmethod
    def _validate_manifest_sha256(cls, value: str) -> str:
        if not _SHA256_PATTERN.fullmatch(value):
            raise ValueError("source manifest sha256 must be 64 lowercase hexadecimal characters")
        return value

    @model_validator(mode="after")
    def _validate_source_identity(self) -> _SourceIdentity:
        if self.manifest_schema != CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_SCHEMA:
            raise ValueError("source manifest schema is not the frozen Concurrent Message contract")
        if self.candidate_artifact != "concurrent_runtime_candidates.csv":
            raise ValueError("candidate artifact must be the frozen Concurrent candidate table")
        if self.feedback_artifact != "concurrent_runtime_steps.json":
            raise ValueError("feedback artifact must be the frozen Concurrent step table")
        paths = tuple(artifact.relative_path for artifact in self.artifacts)
        if paths != tuple(sorted(paths)) or len(paths) != len(set(paths)):
            raise ValueError("source artifacts must be unique and sorted by relative path")
        hashes = {artifact.relative_path: artifact.sha256 for artifact in self.artifacts}
        required = {
            "artifact_manifest.json",
            self.candidate_artifact,
            self.feedback_artifact,
            "sample_manifest.json",
            "seed_first_sample_audit.json",
            "message_snapshot.json",
        }
        missing = sorted(required - set(hashes))
        if missing:
            raise ValueError(f"source artifact identity is incomplete: {', '.join(missing)}")
        if hashes["artifact_manifest.json"] != self.manifest_sha256:
            raise ValueError("source manifest hash does not match its artifact identity")
        return self


class _SampleIdentity(_FrozenContractModel):
    sample_size: int = Field(ge=1)
    sample_identity: str
    sample_manifest_sha256: str
    sample_audit_sha256: str

    @field_validator("sample_identity", "sample_manifest_sha256", "sample_audit_sha256")
    @classmethod
    def _validate_hash(cls, value: str) -> str:
        if not _SHA256_PATTERN.fullmatch(value):
            raise ValueError("sample identity fields must be 64 lowercase hexadecimal characters")
        return value


class _RankingContract(_FrozenContractModel):
    schema_version: Literal["concurrent-robustness-ranking-contract-v1"]
    p95_normalization_token: str
    component_contract_token: str
    components: tuple[_RankingComponent, ...]
    tie_break_token: str
    schedule_token: str
    score_precision_token: str
    ranking_formula: str
    feedback_formula: str
    horizon: int = Field(ge=1)
    delivery_capacity: int = Field(ge=1)

    @model_validator(mode="after")
    def _validate_tokens(self) -> _RankingContract:
        expected = {
            "p95_normalization_token": CONCURRENT_ROBUSTNESS_P95_TOKEN,
            "component_contract_token": CONCURRENT_ROBUSTNESS_COMPONENT_CONTRACT_TOKEN,
            "tie_break_token": CONCURRENT_ROBUSTNESS_TIE_BREAK_TOKEN,
            "schedule_token": CONCURRENT_ROBUSTNESS_SCHEDULE_TOKEN,
            "score_precision_token": CONCURRENT_ROBUSTNESS_SCORE_PRECISION_TOKEN,
            "ranking_formula": CONCURRENT_MESSAGE_RANKING_FORMULA,
            "feedback_formula": CONCURRENT_MESSAGE_ENGAGED_NEIGHBOR_FORMULA,
        }
        for field_name, expected_value in expected.items():
            if getattr(self, field_name) != expected_value:
                raise ValueError(f"ranking contract {field_name} does not match the frozen token")
        if self.components != _RANKING_COMPONENTS:
            raise ValueError("ranking contract must freeze the three components in canonical order")
        return self


class _RankingWeights(_FrozenContractModel):
    base_network_relevance: float
    campaign_engaged_neighbor_signal: float
    normalized_message_user_fit: float

    @model_validator(mode="after")
    def _validate_simplex(self) -> _RankingWeights:
        values = (
            self.base_network_relevance,
            self.campaign_engaged_neighbor_signal,
            self.normalized_message_user_fit,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("ranking weights must be finite")
        if any(value < 0.0 for value in values):
            raise ValueError("ranking weights must be non-negative")
        if not math.isclose(sum(values), 1.0, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("ranking weights must have unit sum")
        return self

    def by_component(self) -> dict[str, float]:
        return {
            "base_network_relevance": self.base_network_relevance,
            "campaign_engaged_neighbor_signal": self.campaign_engaged_neighbor_signal,
            "normalized_message_user_fit": self.normalized_message_user_fit,
        }


class _WeightPoint(_FrozenContractModel):
    scenario_id: str = Field(min_length=1, max_length=200)
    weights: _RankingWeights
    transfer_from: _RankingComponent | None
    transfer_to: _RankingComponent | None
    transfer_mass: float

    @model_validator(mode="after")
    def _validate_transfer(self) -> _WeightPoint:
        if not math.isfinite(self.transfer_mass) or self.transfer_mass < 0.0:
            raise ValueError("weight transfer mass must be finite and non-negative")
        if self.scenario_id == "baseline":
            if self.transfer_from is not None or self.transfer_to is not None or self.transfer_mass != 0.0:
                raise ValueError("baseline weight point must not declare a transfer")
        elif self.transfer_from is None or self.transfer_to is None or self.transfer_from == self.transfer_to:
            raise ValueError("non-baseline weight points require distinct transfer components")
        return self


class _PromptModelCell(_FrozenContractModel):
    cell_id: str
    prompt_variant: _PromptVariant
    prompt_version: str
    prompt_canonical_hash: str
    requested_model: str


class _RequestContract(_FrozenContractModel):
    schema_version: Literal["provider-request-contract-v1"]
    provider: str
    wire_api: str
    reasoning_effort: str
    output_token_ceiling: int = Field(ge=1)
    timeout_seconds: float = Field(gt=0.0)
    max_retries: int = Field(ge=0)
    retry_backoff_seconds: float = Field(ge=0.0)
    structured_output_schema_version: str
    structured_output_schema_hash: str
    omitted_parameters: tuple[str, ...]
    decision_store_policy: str

    @model_validator(mode="after")
    def _validate_request_contract(self) -> _RequestContract:
        if not math.isfinite(self.timeout_seconds) or not math.isfinite(self.retry_backoff_seconds):
            raise ValueError("request timing values must be finite")
        expected = {
            "provider": "openai_compatible",
            "wire_api": "responses",
            "reasoning_effort": "low",
            "structured_output_schema_version": "engage-decision-output-v1",
            "structured_output_schema_hash": STRUCTURED_OUTPUT_SCHEMA_HASH,
            "decision_store_policy": CONCURRENT_ROBUSTNESS_DECISION_STORE_POLICY,
        }
        for field_name, expected_value in expected.items():
            if getattr(self, field_name) != expected_value:
                raise ValueError(f"request contract {field_name} does not match the robustness policy")
        if self.omitted_parameters != OMITTED_SAMPLING_PARAMETERS:
            raise ValueError("request contract must omit temperature, top_p, and seed")
        return self


class _RequestCaps(_FrozenContractModel):
    weight_logical_judgment_cap: Literal[0]
    logical_judgments_per_cell: int = Field(ge=1)
    logical_judgment_cap: int = Field(ge=1)
    physical_attempt_cap: int = Field(ge=1)
    fee_ceiling_usd: float = Field(ge=0.0)

    @field_validator("fee_ceiling_usd")
    @classmethod
    def _validate_fee(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("fee ceiling must be finite")
        return value


class _PracticalThresholds(_FrozenContractModel):
    engagement_rate_absolute: float
    decision_probability_absolute: float
    audience_jaccard_distance: float
    terminal_unique_positive_user_fraction: float
    terminal_unique_positive_user_count: int = Field(ge=1)

    @model_validator(mode="after")
    def _validate_thresholds(self) -> _PracticalThresholds:
        expected = {
            "engagement_rate_absolute": 0.05,
            "decision_probability_absolute": 0.05,
            "audience_jaccard_distance": 0.10,
            "terminal_unique_positive_user_fraction": 0.05,
        }
        for field_name, expected_value in expected.items():
            value = getattr(self, field_name)
            if not math.isfinite(value) or not math.isclose(value, expected_value, rel_tol=0.0, abs_tol=1e-12):
                raise ValueError(f"practical threshold {field_name} is not predeclared")
        return self


def _canonical_weight_points() -> tuple[dict[str, object], ...]:
    points: list[dict[str, object]] = [
        {
            "scenario_id": "baseline",
            "weights": dict(_BASELINE_WEIGHTS),
            "transfer_from": None,
            "transfer_to": None,
            "transfer_mass": 0.0,
        }
    ]
    for left, right in (
        (_RANKING_COMPONENTS[0], _RANKING_COMPONENTS[1]),
        (_RANKING_COMPONENTS[0], _RANKING_COMPONENTS[2]),
        (_RANKING_COMPONENTS[1], _RANKING_COMPONENTS[2]),
    ):
        for transfer_mass in _TRANSFER_MASSES:
            for source, target in ((left, right), (right, left)):
                weights = dict(_BASELINE_WEIGHTS)
                weights[source] -= transfer_mass
                weights[target] += transfer_mass
                points.append(
                    {
                        "scenario_id": f"transfer-{source}-to-{target}-{transfer_mass:.2f}",
                        "weights": weights,
                        "transfer_from": source,
                        "transfer_to": target,
                        "transfer_mass": transfer_mass,
                    }
                )
    return tuple(points)


def _weight_point_matches(point: _WeightPoint, expected: Mapping[str, object]) -> bool:
    if (
        point.scenario_id != expected["scenario_id"]
        or point.transfer_from != expected["transfer_from"]
        or point.transfer_to != expected["transfer_to"]
        or not math.isclose(point.transfer_mass, float(str(expected["transfer_mass"])), rel_tol=0.0, abs_tol=1e-12)
    ):
        return False
    expected_weights = expected["weights"]
    if not isinstance(expected_weights, Mapping):
        return False
    return all(
        math.isclose(
            point.weights.by_component()[component],
            float(str(expected_weights[component])),
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        for component in _RANKING_COMPONENTS
    )


class ConcurrentRobustnessManifest(_FrozenContractModel):
    """Immutable identity and policy contract for one robustness study workspace."""

    schema_version: Literal["concurrent-robustness-manifest-v1"] = "concurrent-robustness-manifest-v1"
    source: _SourceIdentity
    sample: _SampleIdentity
    message_ids: tuple[str, ...]
    message_snapshot_sha256: str
    ranking_contract: _RankingContract
    weight_points: tuple[_WeightPoint, ...]
    prompt_model_cells: tuple[_PromptModelCell, ...]
    request_contract: _RequestContract
    request_caps: _RequestCaps
    practical_thresholds: _PracticalThresholds
    authorization_reference: str = Field(min_length=1, max_length=240)
    output_identity: str

    @field_validator("message_snapshot_sha256")
    @classmethod
    def _validate_message_hash(cls, value: str) -> str:
        if not _SHA256_PATTERN.fullmatch(value):
            raise ValueError("message snapshot sha256 must be 64 lowercase hexadecimal characters")
        return value

    @field_validator("output_identity")
    @classmethod
    def _validate_output_identity(cls, value: str) -> str:
        if not _OUTPUT_IDENTITY_PATTERN.fullmatch(value):
            raise ValueError("output identity must be a bounded stable token")
        return value

    @model_validator(mode="after")
    def _validate_manifest_contract(self) -> ConcurrentRobustnessManifest:
        source_hashes = {artifact.relative_path: artifact.sha256 for artifact in self.source.artifacts}
        if self.sample.sample_manifest_sha256 != source_hashes["sample_manifest.json"]:
            raise ValueError("sample manifest hash is crossed with the source identity")
        if self.sample.sample_audit_sha256 != source_hashes["seed_first_sample_audit.json"]:
            raise ValueError("sample audit hash is crossed with the source identity")
        if self.message_snapshot_sha256 != source_hashes["message_snapshot.json"]:
            raise ValueError("message snapshot hash is crossed with the source identity")
        if self.message_ids != _ROBUSTNESS_MESSAGE_IDS:
            raise ValueError("manifest must freeze the authoritative three message IDs")

        expected_points = _canonical_weight_points()
        if len(self.weight_points) != 19:
            raise ValueError("manifest requires exactly 19 canonical weight points")
        if len({point.scenario_id for point in self.weight_points}) != 19:
            raise ValueError("manifest requires 19 canonical weight points without duplicates")
        if not all(
            _weight_point_matches(point, expected)
            for point, expected in zip(self.weight_points, expected_points, strict=True)
        ):
            raise ValueError("manifest weight points do not match the 19 canonical mass transfers")

        expected_cells = tuple(
            (
                f"{prompt.variant_id}::{model}",
                prompt.variant_id,
                prompt.prompt_version,
                prompt.canonical_hash,
                model,
            )
            for prompt in CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.all()
            for model in _ROBUSTNESS_MODELS
        )
        actual_cells = tuple(
            (
                cell.cell_id,
                cell.prompt_variant,
                cell.prompt_version,
                cell.prompt_canonical_hash,
                cell.requested_model,
            )
            for cell in self.prompt_model_cells
        )
        if len(actual_cells) != 16 or len(set(actual_cells)) != 16 or actual_cells != expected_cells:
            raise ValueError("manifest requires exactly 16 canonical Prompt-Model cells")

        logical_per_cell = self.ranking_contract.horizon * self.ranking_contract.delivery_capacity * 3
        if self.request_caps.logical_judgments_per_cell != logical_per_cell:
            raise ValueError("logical judgments per cell do not match the frozen schedule")
        if self.request_caps.logical_judgment_cap != logical_per_cell * 16:
            raise ValueError("logical judgment cap does not match the 16-cell universe")
        expected_physical_cap = self.request_caps.logical_judgment_cap * (self.request_contract.max_retries + 1)
        if self.request_caps.physical_attempt_cap != expected_physical_cap:
            raise ValueError("physical attempt cap does not match the retry contract")
        expected_positive_count = math.ceil(self.sample.sample_size * 0.05)
        if self.practical_thresholds.terminal_unique_positive_user_count != expected_positive_count:
            raise ValueError("terminal positive-user threshold must be five percent of the sample")

        if self.source.kind == "formal":
            if self.sample.sample_size != CONCURRENT_MESSAGE_PRODUCTION_SAMPLE_SIZE:
                raise ValueError("Formal robustness source must freeze the 1,000-user sample")
            if self.ranking_contract.horizon != CONCURRENT_MESSAGE_PRODUCTION_HORIZON:
                raise ValueError("Formal robustness source must freeze the 30-batch schedule")
            if self.ranking_contract.delivery_capacity != CONCURRENT_MESSAGE_PRODUCTION_DELIVERY_CAPACITY:
                raise ValueError("Formal robustness source must freeze per-message Top20")
        return self


class ConcurrentRobustnessStudyResult(_FrozenContractModel):
    """Observable static-study result; final roots are absent until a future complete state."""

    status: ConcurrentRobustnessStudyStatus
    workspace_root: Path
    validation_report: Path
    manifest_sha256: str
    logical_provider_attempts: int = Field(ge=0)
    physical_provider_attempts: int = Field(ge=0)
    study_root: Path | None = None
    report_candidate: Path | None = None

    @model_validator(mode="after")
    def _validate_result_state(self) -> ConcurrentRobustnessStudyResult:
        if not _SHA256_PATTERN.fullmatch(self.manifest_sha256):
            raise ValueError("result manifest sha256 is invalid")
        if self.status != ConcurrentRobustnessStudyStatus.COMPLETE:
            if self.study_root is not None or self.report_candidate is not None:
                raise ValueError("non-complete results cannot expose final study or report roots")
        elif self.study_root is None or self.report_candidate is None:
            raise ValueError("complete results require both final study and report roots")
        return self


@dataclass(frozen=True)
class _FrozenCandidate:
    time_step: int
    message_id: str
    user_id: str
    ranking_position: int
    base_network_relevance: float
    campaign_engaged_neighbor_signal: float
    normalized_message_user_fit: float
    persisted_score: float


_WORKSPACE_MANIFEST = "study_manifest.json"
_WORKSPACE_ANALYSIS = "ranking_weight_sensitivity.json"
_WORKSPACE_VALIDATION = "validation_report.json"
_WORKSPACE_REGISTRY = "workspace_registry.json"
_WORKSPACE_ARTIFACTS = {
    "study_manifest": _WORKSPACE_MANIFEST,
    "weight_sensitivity": _WORKSPACE_ANALYSIS,
    "validation_report": _WORKSPACE_VALIDATION,
}
_WORKSPACE_FILES = {*_WORKSPACE_ARTIFACTS.values(), _WORKSPACE_REGISTRY}


class _WorkspaceRegistry(_FrozenContractModel):
    schema_version: Literal["concurrent-robustness-workspace-registry-v1"]
    workspace_type: Literal["private_resumable"]
    status: Literal["ready_for_human"]
    output_identity: str
    output_root_sha256: str
    manifest_sha256: str
    source_manifest_sha256: str
    artifacts: dict[str, str]
    sha256: dict[str, str]
    logical_provider_attempts: Literal[0]
    physical_provider_attempts: Literal[0]
    production_deploy_eligible: Literal[False]
    study_root: None
    report_candidate: None

    @model_validator(mode="after")
    def _validate_registry(self) -> _WorkspaceRegistry:
        for value in (self.output_root_sha256, self.manifest_sha256, self.source_manifest_sha256):
            if not _SHA256_PATTERN.fullmatch(value):
                raise ValueError("workspace registry contains an invalid identity hash")
        if self.artifacts != _WORKSPACE_ARTIFACTS:
            raise ValueError("workspace registry artifact paths do not match the static contract")
        if set(self.sha256) != set(self.artifacts):
            raise ValueError("workspace registry artifact paths and hashes must share the same keys")
        if not all(_SHA256_PATTERN.fullmatch(value) for value in self.sha256.values()):
            raise ValueError("workspace registry contains an invalid artifact hash")
        return self


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")


def _manifest_bytes(manifest: ConcurrentRobustnessManifest) -> bytes:
    return _json_bytes(manifest.model_dump(mode="json"))


def _output_root_sha256(output_path: Path) -> str:
    return _sha256_bytes(str(output_path).encode("utf-8"))


def _read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain one JSON object")
    return payload


def _resolve_source_path(path: Path) -> Path:
    try:
        absolute = Path(os.path.abspath(path))
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ConcurrentRobustnessError(
            ConcurrentRobustnessErrorCode.PATH_VIOLATION,
            "explicit Formal source path does not resolve to a directory",
        ) from exc
    if absolute != resolved or path.is_symlink() or not resolved.is_dir():
        raise ConcurrentRobustnessError(
            ConcurrentRobustnessErrorCode.PATH_VIOLATION,
            "explicit Formal source path must be a real directory without symlink components",
        )
    return resolved


def _resolve_output_path(path: str | Path) -> Path:
    raw = Path(path)
    absolute = Path(os.path.abspath(raw))
    try:
        resolved = raw.resolve(strict=False)
    except OSError as exc:
        raise ConcurrentRobustnessError(
            ConcurrentRobustnessErrorCode.PATH_VIOLATION,
            "robustness output path cannot be resolved safely",
        ) from exc
    if ".." in raw.parts or absolute != resolved or raw.is_symlink():
        raise ConcurrentRobustnessError(
            ConcurrentRobustnessErrorCode.PATH_VIOLATION,
            "robustness output path must not contain traversal or symlink components",
        )
    if resolved.exists() and not resolved.is_dir():
        raise ConcurrentRobustnessError(
            ConcurrentRobustnessErrorCode.WORKSPACE_CONFLICT,
            "robustness output target exists and is not a workspace directory",
        )
    return resolved


def _validate_study_paths(source_path: Path, output_path: Path) -> None:
    if (
        source_path == output_path
        or output_path.is_relative_to(source_path)
        or source_path.is_relative_to(output_path)
    ):
        raise ConcurrentRobustnessError(
            ConcurrentRobustnessErrorCode.PATH_VIOLATION,
            "robustness output target must not overlap the frozen Formal source",
        )


def _close_source(source_path: Path) -> ConcurrentMessageArtifactClosure:
    try:
        return close_concurrent_message_artifacts(source_path)
    except (FileNotFoundError, OSError, TypeError, ValueError) as exc:
        raise ConcurrentRobustnessError(
            ConcurrentRobustnessErrorCode.INVALID_SOURCE,
            "explicit Concurrent Formal source failed its existing artifact closure",
        ) from exc


def _ordered_user_ids_sha256(rows: Sequence[Mapping[str, Any]]) -> str:
    user_ids: list[str] = []
    for row in rows:
        user_id = str(row.get("user_id", ""))
        if not user_id:
            raise ValueError("sample manifest contains an empty user identity")
        user_ids.append(user_id)
    if len(user_ids) != len(set(user_ids)):
        raise ValueError("sample manifest contains duplicate user identities")
    encoded = json.dumps(user_ids, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(encoded)


def _validate_source_against_manifest(
    manifest: ConcurrentRobustnessManifest,
    closure: ConcurrentMessageArtifactClosure,
    source_path: Path,
) -> None:
    source = manifest.source
    if source.source_dir != source_path or source.source_id != source_path.name:
        raise ValueError("Formal source path or identity does not match the study manifest")
    expected_source_hashes = {artifact.relative_path: artifact.sha256 for artifact in source.artifacts}
    if closure.artifact_hashes != expected_source_hashes:
        raise ValueError("Formal source artifact hashes do not match the study manifest")
    if closure.artifact_hashes["artifact_manifest.json"] != source.manifest_sha256:
        raise ValueError("Formal source manifest hash does not match the study manifest")
    if closure.manifest.schema_version != source.manifest_schema:
        raise ValueError("Formal source schema does not match the study manifest")
    if closure.manifest.artifacts.get("rankings_csv") != source.candidate_artifact:
        raise ValueError("Formal source candidate artifact is crossed")
    if closure.manifest.artifacts.get("runtime_steps_json") != source.feedback_artifact:
        raise ValueError("Formal source feedback artifact is crossed")

    evidence = closure.source_evidence
    config = evidence.config_snapshot
    validation = evidence.validation_summary
    if int(config.get("sample_size", -1)) != manifest.sample.sample_size:
        raise ValueError("Formal source sample size does not match the study manifest")
    if len(evidence.sample_manifest_rows) != manifest.sample.sample_size:
        raise ValueError("Formal source sample manifest row count is crossed")
    if _ordered_user_ids_sha256(evidence.sample_manifest_rows) != manifest.sample.sample_identity:
        raise ValueError("Formal source ordered sample identity does not match the study manifest")
    if int(config.get("horizon", -1)) != manifest.ranking_contract.horizon:
        raise ValueError("Formal source horizon does not match the study manifest")
    if int(config.get("delivery_capacity", -1)) != manifest.ranking_contract.delivery_capacity:
        raise ValueError("Formal source delivery capacity does not match the study manifest")
    if config.get("ranking_formula") != manifest.ranking_contract.ranking_formula:
        raise ValueError("Formal source ranking formula does not match the study manifest")
    if config.get("engaged_neighbor_formula") != manifest.ranking_contract.feedback_formula:
        raise ValueError("Formal source feedback formula does not match the study manifest")
    if config.get("sampling_method") != SEED_FIRST_SAMPLING_METHOD:
        raise ValueError("Formal source sampling method is unsupported")
    message_ids = tuple(str(row.get("message_id", "")) for row in evidence.message_snapshot)
    if message_ids != manifest.message_ids:
        raise ValueError("Formal source messages do not match the study manifest")

    if source.kind == "formal":
        if config.get("configuration_profile") != "production":
            raise ValueError("Formal source must use the production configuration profile")
        if config.get("sampling_status") != FORMAL_RUN_STATUS or validation.get("sampling_status") != FORMAL_RUN_STATUS:
            raise ValueError("Formal source must contain persisted Formal sampling evidence")
        if config.get("production_deploy_eligible") is not True or validation.get("production_deploy_eligible") is not True:
            raise ValueError("Formal source must contain its original deploy-eligibility evidence")
    else:
        if config.get("configuration_profile") == "production":
            raise ValueError("compact fixture source cannot claim the production configuration profile")
        if config.get("sampling_status") != VALIDATION_RUN_STATUS or validation.get("sampling_status") != VALIDATION_RUN_STATUS:
            raise ValueError("compact fixture source must contain validation-run evidence")
        if config.get("production_deploy_eligible") is not False or validation.get("production_deploy_eligible") is not False:
            raise ValueError("compact fixture source must remain non-deployable")


def _assert_source_unchanged(closure: ConcurrentMessageArtifactClosure) -> None:
    source_path = closure.run_dir.resolve(strict=True)
    try:
        actual_files: dict[str, Path] = {}
        for path in source_path.rglob("*"):
            relative_path = path.relative_to(source_path).as_posix()
            if path.is_symlink():
                raise ValueError(f"source contains symlink {relative_path}")
            if path.is_file():
                actual_files[relative_path] = path
            elif not path.is_dir():
                raise ValueError(f"source contains non-regular path {relative_path}")
        if set(actual_files) != set(closure.source_files):
            raise ValueError("source file set changed")
        if set(actual_files) != set(closure.artifact_hashes):
            raise ValueError("source closure and artifact hashes are crossed")
        for relative_path, expected_hash in closure.artifact_hashes.items():
            if _sha256_file(actual_files[relative_path]) != expected_hash:
                raise ValueError(f"source artifact changed: {relative_path}")
    except (OSError, ValueError) as exc:
        raise ConcurrentRobustnessError(
            ConcurrentRobustnessErrorCode.SOURCE_MUTATED,
            "frozen Concurrent Formal source changed during robustness analysis",
        ) from exc


def _as_int(value: object, label: str) -> int:
    text = str(value)
    if not re.fullmatch(r"-?\d+", text):
        raise ValueError(f"{label} must be an integer")
    return int(text)


def _as_finite_float(value: object, label: str) -> float:
    try:
        parsed = float(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{label} must be finite")
    return parsed


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _sequence(value: object, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{label} must be a sequence")
    return value


def _string_list(value: object, label: str) -> list[str]:
    values = [str(item) for item in _sequence(value, label)]
    if any(not item for item in values) or len(values) != len(set(values)):
        raise ValueError(f"{label} must contain unique non-empty identities")
    return values


def _round_metric(value: float) -> float:
    rounded = round(value, 12)
    return 0.0 if rounded == 0.0 else rounded


class _WeightSensitivityAnalyzer:
    """Private owner of the additive robustness schema and frozen ranking calculation."""

    def __init__(
        self,
        *,
        manifest: ConcurrentRobustnessManifest,
        candidate_rows: Sequence[Mapping[str, Any]],
        feedback_rows: Sequence[Mapping[str, Any]],
    ) -> None:
        self.manifest = manifest
        self._groups = self._parse_candidates(candidate_rows)
        self._validate_feedback(feedback_rows)

    def analyze(self, *, manifest_sha256: str) -> dict[str, Any]:
        scenarios: list[dict[str, Any]] = []
        for point in self.manifest.weight_points:
            message_results: list[dict[str, Any]] = []
            scenario_baseline_reproduced = True
            for message_id in self.manifest.message_ids:
                batch_results: list[dict[str, Any]] = []
                distances: list[float] = []
                first_divergent_batch: int | None = None
                for time_step in range(self.manifest.ranking_contract.horizon):
                    candidates = self._groups[(message_id, time_step)]
                    source_order = [candidate.user_id for candidate in candidates]
                    scenario_order = [
                        candidate.user_id
                        for candidate in sorted(
                            candidates,
                            key=lambda candidate: (
                                -self._score(candidate, point.weights),
                                candidate.user_id,
                            ),
                        )
                    ]
                    top_count = min(self.manifest.ranking_contract.delivery_capacity, len(candidates))
                    baseline_top = source_order[:top_count]
                    scenario_top = scenario_order[:top_count]
                    baseline_set = set(baseline_top)
                    scenario_set = set(scenario_top)
                    union = baseline_set | scenario_set
                    distance = 0.0 if not union else 1.0 - len(baseline_set & scenario_set) / len(union)
                    distance = _round_metric(distance)
                    distances.append(distance)
                    entered = [user_id for user_id in scenario_top if user_id not in baseline_set]
                    exited = [user_id for user_id in baseline_top if user_id not in scenario_set]
                    first_divergent_rank = next(
                        (
                            position
                            for position, (baseline_user, scenario_user) in enumerate(
                                zip(baseline_top, scenario_top, strict=True),
                                start=1,
                            )
                            if baseline_user != scenario_user
                        ),
                        None,
                    )
                    if first_divergent_rank is not None and first_divergent_batch is None:
                        first_divergent_batch = time_step
                    if point.scenario_id == "baseline" and baseline_top != scenario_top:
                        scenario_baseline_reproduced = False
                    baseline_rank = {user_id: rank for rank, user_id in enumerate(source_order, start=1)}
                    scenario_rank = {user_id: rank for rank, user_id in enumerate(scenario_order, start=1)}
                    rank_delta_users = sorted(
                        union,
                        key=lambda user_id: (
                            min(baseline_rank[user_id], scenario_rank[user_id]),
                            user_id,
                        ),
                    )
                    rank_deltas = [
                        {
                            "user_id": user_id,
                            "baseline_rank": baseline_rank[user_id],
                            "scenario_rank": scenario_rank[user_id],
                            "rank_delta": scenario_rank[user_id] - baseline_rank[user_id],
                            "membership": (
                                "entered"
                                if user_id in scenario_set and user_id not in baseline_set
                                else "exited"
                                if user_id in baseline_set and user_id not in scenario_set
                                else "retained"
                            ),
                        }
                        for user_id in rank_delta_users
                    ]
                    batch_results.append(
                        {
                            "time_step": time_step,
                            "eligible_user_count": len(candidates),
                            "top_count": top_count,
                            "baseline_top_user_ids": baseline_top,
                            "scenario_top_user_ids": scenario_top,
                            "jaccard_distance": distance,
                            "entered_user_ids": entered,
                            "exited_user_ids": exited,
                            "first_divergent_rank": first_divergent_rank,
                            "rank_delta_sign_convention": "scenario_rank_minus_baseline_rank",
                            "rank_deltas": rank_deltas,
                        }
                    )
                curve_mean = sum(distances) / len(distances)
                if len(distances) == 1:
                    curve_auc = distances[0]
                else:
                    curve_auc = sum(
                        (left + right) / 2.0 for left, right in zip(distances, distances[1:], strict=False)
                    )
                message_results.append(
                    {
                        "message_id": message_id,
                        "first_divergent_batch": first_divergent_batch,
                        "curve_mean_jaccard_distance": _round_metric(curve_mean),
                        "curve_auc_jaccard_distance": _round_metric(curve_auc),
                        "curve_auc_method": "trapezoidal_over_zero_based_batch_index",
                        "batches": batch_results,
                    }
                )
            all_distances = [
                float(batch["jaccard_distance"])
                for message in message_results
                for batch in message["batches"]
            ]
            scenarios.append(
                {
                    "scenario_id": point.scenario_id,
                    "weights": point.weights.model_dump(mode="json"),
                    "transfer_from": point.transfer_from,
                    "transfer_to": point.transfer_to,
                    "transfer_mass": point.transfer_mass,
                    "baseline_reproduced": scenario_baseline_reproduced if point.scenario_id == "baseline" else None,
                    "overall_mean_jaccard_distance": _round_metric(sum(all_distances) / len(all_distances)),
                    "messages": message_results,
                }
            )
        if scenarios[0]["baseline_reproduced"] is not True:
            raise ValueError("baseline weight scenario did not reproduce the frozen Top K rankings")
        horizon = self.manifest.ranking_contract.horizon
        return {
            "schema_version": "concurrent-ranking-weight-sensitivity-v1",
            "manifest_sha256": manifest_sha256,
            "source": {
                "source_id": self.manifest.source.source_id,
                "manifest_sha256": self.manifest.source.manifest_sha256,
                "candidate_artifact": self.manifest.source.candidate_artifact,
                "candidate_sha256": self._source_hash(self.manifest.source.candidate_artifact),
                "feedback_artifact": self.manifest.source.feedback_artifact,
                "feedback_sha256": self._source_hash(self.manifest.source.feedback_artifact),
            },
            "method": {
                "candidate_sets": "frozen_per_message_per_batch",
                "feedback": "frozen_source_signal_only",
                "eligibility_advanced": False,
                "propagation_advanced": False,
                "top_k_basis": "persisted_ranking_not_batch_zero_forced_exposure",
                "tie_break_token": self.manifest.ranking_contract.tie_break_token,
                "score_precision_token": self.manifest.ranking_contract.score_precision_token,
            },
            "counts": {
                "scenario_count": len(scenarios),
                "message_count": len(self.manifest.message_ids),
                "batch_count_per_message": horizon,
                "scenario_message_batch_count": len(scenarios) * len(self.manifest.message_ids) * horizon,
            },
            "logical_provider_attempts": 0,
            "physical_provider_attempts": 0,
            "scenarios": scenarios,
        }

    def _source_hash(self, relative_path: str) -> str:
        return next(
            artifact.sha256
            for artifact in self.manifest.source.artifacts
            if artifact.relative_path == relative_path
        )

    @staticmethod
    def _score(candidate: _FrozenCandidate, weights: _RankingWeights) -> float:
        return (
            weights.base_network_relevance * candidate.base_network_relevance
            + weights.campaign_engaged_neighbor_signal * candidate.campaign_engaged_neighbor_signal
            + weights.normalized_message_user_fit * candidate.normalized_message_user_fit
        )

    def _parse_candidates(
        self,
        rows: Sequence[Mapping[str, Any]],
    ) -> dict[tuple[str, int], tuple[_FrozenCandidate, ...]]:
        if not rows:
            raise ValueError("weight sensitivity requires frozen candidate rows")
        groups: dict[tuple[str, int], list[_FrozenCandidate]] = defaultdict(list)
        seen: set[tuple[str, int, str]] = set()
        expected_fields = set(CONCURRENT_MESSAGE_CANDIDATE_FIELDS)
        for row in rows:
            if set(row) != expected_fields:
                raise ValueError("frozen candidate rows do not match the dedicated robustness input schema")
            time_step = _as_int(row.get("time_step"), "candidate time_step")
            message_id = str(row.get("message_id", ""))
            user_id = str(row.get("user_id", ""))
            if message_id not in self.manifest.message_ids:
                raise ValueError("candidate row has an unknown message identity")
            if time_step < 0 or time_step >= self.manifest.ranking_contract.horizon:
                raise ValueError("candidate row has an out-of-contract time_step")
            if not user_id:
                raise ValueError("candidate row has an empty user identity")
            key = (message_id, time_step, user_id)
            if key in seen:
                raise ValueError("candidate rows contain a duplicate message/batch/user identity")
            seen.add(key)
            base = _as_finite_float(
                row.get("base_network_relevance_full_precision"),
                "base network relevance",
            )
            feedback = _as_finite_float(
                row.get("campaign_engaged_neighbor_signal_full_precision"),
                "campaign feedback signal",
            )
            fit = _as_finite_float(
                row.get("normalized_message_user_fit_full_precision"),
                "normalized message-user fit",
            )
            persisted_score = _as_finite_float(
                row.get("personalized_delivery_score_full_precision"),
                "persisted personalized delivery score",
            )
            if any(value < 0.0 or value > 1.0 for value in (base, feedback, fit)):
                raise ValueError("frozen ranking components must remain within [0, 1]")
            candidate = _FrozenCandidate(
                time_step=time_step,
                message_id=message_id,
                user_id=user_id,
                ranking_position=_as_int(row.get("ranking_position"), "candidate ranking_position"),
                base_network_relevance=base,
                campaign_engaged_neighbor_signal=feedback,
                normalized_message_user_fit=fit,
                persisted_score=persisted_score,
            )
            groups[(message_id, time_step)].append(candidate)

        expected_group_keys = {
            (message_id, time_step)
            for message_id in self.manifest.message_ids
            for time_step in range(self.manifest.ranking_contract.horizon)
        }
        if set(groups) != expected_group_keys:
            raise ValueError("frozen candidate evidence is missing or adds message/batch groups")
        ordered_groups: dict[tuple[str, int], tuple[_FrozenCandidate, ...]] = {}
        baseline_weights = self.manifest.weight_points[0].weights
        for group_key, candidates in groups.items():
            ordered = sorted(candidates, key=lambda candidate: candidate.ranking_position)
            if [candidate.ranking_position for candidate in ordered] != list(range(1, len(ordered) + 1)):
                raise ValueError("frozen candidate ranking positions must be contiguous from one")
            for candidate in ordered:
                recomputed = self._score(candidate, baseline_weights)
                if not math.isclose(recomputed, candidate.persisted_score, rel_tol=0.0, abs_tol=1e-12):
                    raise ValueError("frozen baseline score does not match the three ranking components")
            reranked = sorted(
                candidates,
                key=lambda candidate: (-self._score(candidate, baseline_weights), candidate.user_id),
            )
            if [candidate.user_id for candidate in ordered] != [candidate.user_id for candidate in reranked]:
                raise ValueError("frozen baseline ranking does not match score and user_id tie-break")
            ordered_groups[group_key] = tuple(ordered)
        return ordered_groups

    def _validate_feedback(self, rows: Sequence[Mapping[str, Any]]) -> None:
        if len(rows) != self.manifest.ranking_contract.horizon:
            raise ValueError("frozen feedback evidence must contain one row per batch")
        for expected_time_step, row_raw in enumerate(rows):
            row = _mapping(row_raw, "feedback row")
            if _as_int(row.get("time_step"), "feedback time_step") != expected_time_step:
                raise ValueError("frozen feedback batches must be contiguous from zero")
            _string_list(row.get("frozen_campaign_engaged_user_ids", []), "frozen campaign feedback users")
            _string_list(
                row.get("deduplicated_committed_primary_positive_user_ids", []),
                "committed campaign feedback users",
            )
            messages = [_mapping(item, "feedback message") for item in _sequence(row.get("messages"), "messages")]
            if tuple(str(item.get("message_id", "")) for item in messages) != self.manifest.message_ids:
                raise ValueError("frozen feedback message order or identity is crossed")
            for message in messages:
                message_id = str(message["message_id"])
                candidate_count = len(self._groups[(message_id, expected_time_step)])
                if _as_int(message.get("eligible_users"), "feedback eligible_users") != candidate_count:
                    raise ValueError("frozen feedback eligible count does not match candidate evidence")
                if _as_int(message.get("ranked_candidates"), "feedback ranked_candidates") != candidate_count:
                    raise ValueError("frozen feedback ranking count does not match candidate evidence")


def _validation_payload(
    manifest: ConcurrentRobustnessManifest,
    *,
    manifest_sha256: str,
    analysis_sha256: str,
) -> dict[str, Any]:
    return {
        "schema_version": "concurrent-robustness-validation-v1",
        "status": ConcurrentRobustnessStudyStatus.READY_FOR_HUMAN.value,
        "manifest_sha256": manifest_sha256,
        "source_manifest_sha256": manifest.source.manifest_sha256,
        "ranking_weight_sensitivity_sha256": analysis_sha256,
        "checks": {
            "source_closure_valid": True,
            "source_unchanged": True,
            "baseline_reproduced": True,
            "weight_point_count": 19,
            "prompt_model_cell_count": 16,
            "provider_attempts_zero": True,
            "workspace_resumable": True,
        },
        "logical_provider_attempts": 0,
        "physical_provider_attempts": 0,
        "production_deploy_eligible": False,
        "study_root": None,
        "report_candidate": None,
    }


def _workspace_registry_payload(
    manifest: ConcurrentRobustnessManifest,
    *,
    output_path: Path,
    manifest_sha256: str,
    artifact_hashes: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "schema_version": "concurrent-robustness-workspace-registry-v1",
        "workspace_type": "private_resumable",
        "status": ConcurrentRobustnessStudyStatus.READY_FOR_HUMAN.value,
        "output_identity": manifest.output_identity,
        "output_root_sha256": _output_root_sha256(output_path),
        "manifest_sha256": manifest_sha256,
        "source_manifest_sha256": manifest.source.manifest_sha256,
        "artifacts": dict(_WORKSPACE_ARTIFACTS),
        "sha256": dict(artifact_hashes),
        "logical_provider_attempts": 0,
        "physical_provider_attempts": 0,
        "production_deploy_eligible": False,
        "study_root": None,
        "report_candidate": None,
    }


def _expected_workspace_payloads(
    output_path: Path,
    *,
    manifest: ConcurrentRobustnessManifest,
    manifest_payload: bytes,
    analysis: Mapping[str, Any],
) -> dict[str, bytes]:
    manifest_sha256 = _sha256_bytes(manifest_payload)
    analysis_payload = _json_bytes(analysis)
    validation_payload = _json_bytes(
        _validation_payload(
            manifest,
            manifest_sha256=manifest_sha256,
            analysis_sha256=_sha256_bytes(analysis_payload),
        )
    )
    artifact_payloads = {
        "study_manifest": manifest_payload,
        "weight_sensitivity": analysis_payload,
        "validation_report": validation_payload,
    }
    registry_payload = _json_bytes(
        _workspace_registry_payload(
            manifest,
            output_path=output_path,
            manifest_sha256=manifest_sha256,
            artifact_hashes={name: _sha256_bytes(payload) for name, payload in artifact_payloads.items()},
        )
    )
    return {
        **{_WORKSPACE_ARTIFACTS[name]: payload for name, payload in artifact_payloads.items()},
        _WORKSPACE_REGISTRY: registry_payload,
    }


def _validate_workspace(
    workspace_path: Path,
    *,
    output_path: Path,
    manifest: ConcurrentRobustnessManifest,
    manifest_sha256: str,
    analysis: Mapping[str, Any],
) -> ConcurrentRobustnessStudyResult:
    try:
        if workspace_path.is_symlink() or not workspace_path.is_dir():
            raise ValueError("workspace root is not a real directory")
        actual_files: set[str] = set()
        for path in workspace_path.iterdir():
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"workspace contains a non-regular artifact: {path.name}")
            actual_files.add(path.name)
        if actual_files != _WORKSPACE_FILES:
            raise ValueError("workspace has missing or extra artifacts")
        expected_payloads = _expected_workspace_payloads(
            output_path,
            manifest=manifest,
            manifest_payload=_manifest_bytes(manifest),
            analysis=analysis,
        )
        for relative_path, expected_payload in expected_payloads.items():
            if (workspace_path / relative_path).read_bytes() != expected_payload:
                raise ValueError(f"workspace artifact does not reproduce frozen evidence: {relative_path}")

        registry = _WorkspaceRegistry.model_validate(_read_json_object(workspace_path / _WORKSPACE_REGISTRY))
        if registry.output_identity != manifest.output_identity:
            raise ValueError("workspace output identity is crossed")
        if registry.output_root_sha256 != _output_root_sha256(output_path):
            raise ValueError("workspace root identity is crossed")
        if registry.manifest_sha256 != manifest_sha256:
            raise ValueError("workspace manifest hash is crossed")
        if registry.source_manifest_sha256 != manifest.source.manifest_sha256:
            raise ValueError("workspace source identity is crossed")
        for artifact_name, relative_path in registry.artifacts.items():
            artifact_path = workspace_path / relative_path
            if _sha256_file(artifact_path) != registry.sha256[artifact_name]:
                raise ValueError(f"workspace artifact hash mismatch: {relative_path}")

        persisted_manifest_path = workspace_path / _WORKSPACE_MANIFEST
        if _sha256_file(persisted_manifest_path) != manifest_sha256:
            raise ValueError("persisted study manifest hash is crossed")
        persisted_manifest = ConcurrentRobustnessManifest.model_validate(_read_json_object(persisted_manifest_path))
        if persisted_manifest != manifest:
            raise ValueError("persisted study manifest does not match the requested manifest")

        analysis = _read_json_object(workspace_path / _WORKSPACE_ANALYSIS)
        if analysis.get("schema_version") != "concurrent-ranking-weight-sensitivity-v1":
            raise ValueError("workspace weight sensitivity schema is unsupported")
        if analysis.get("manifest_sha256") != manifest_sha256:
            raise ValueError("workspace analysis manifest identity is crossed")
        analysis_source = _mapping(analysis.get("source"), "workspace analysis source")
        if analysis_source.get("manifest_sha256") != manifest.source.manifest_sha256:
            raise ValueError("workspace analysis source identity is crossed")
        if analysis.get("logical_provider_attempts") != 0 or analysis.get("physical_provider_attempts") != 0:
            raise ValueError("static workspace contains Provider attempts")

        validation = _read_json_object(workspace_path / _WORKSPACE_VALIDATION)
        if validation.get("schema_version") != "concurrent-robustness-validation-v1":
            raise ValueError("workspace validation schema is unsupported")
        if validation.get("status") != ConcurrentRobustnessStudyStatus.READY_FOR_HUMAN.value:
            raise ValueError("workspace validation status is not resumable")
        if validation.get("manifest_sha256") != manifest_sha256:
            raise ValueError("workspace validation manifest identity is crossed")
        if validation.get("source_manifest_sha256") != manifest.source.manifest_sha256:
            raise ValueError("workspace validation source identity is crossed")
        if validation.get("ranking_weight_sensitivity_sha256") != registry.sha256["weight_sensitivity"]:
            raise ValueError("workspace validation analysis hash is crossed")
        if validation.get("production_deploy_eligible") is not False:
            raise ValueError("ready workspace must remain non-deployable")
        if validation.get("study_root") is not None or validation.get("report_candidate") is not None:
            raise ValueError("ready workspace cannot expose complete-study artifacts")
    except ConcurrentRobustnessError:
        raise
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ConcurrentRobustnessError(
            ConcurrentRobustnessErrorCode.WORKSPACE_CORRUPT,
            "existing robustness workspace failed registry and artifact closure",
        ) from exc

    return ConcurrentRobustnessStudyResult(
        status=ConcurrentRobustnessStudyStatus.READY_FOR_HUMAN,
        workspace_root=output_path,
        validation_report=output_path / _WORKSPACE_VALIDATION,
        manifest_sha256=manifest_sha256,
        logical_provider_attempts=0,
        physical_provider_attempts=0,
        study_root=None,
        report_candidate=None,
    )


def _write_new_workspace(
    output_path: Path,
    *,
    manifest: ConcurrentRobustnessManifest,
    manifest_payload: bytes,
    analysis: Mapping[str, Any],
) -> ConcurrentRobustnessStudyResult:
    if output_path.exists():
        raise ConcurrentRobustnessError(
            ConcurrentRobustnessErrorCode.WORKSPACE_CONFLICT,
            "new robustness output target already exists",
        )
    manifest_sha256 = _sha256_bytes(manifest_payload)
    workspace_payloads = _expected_workspace_payloads(
        output_path,
        manifest=manifest,
        manifest_payload=manifest_payload,
        analysis=analysis,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    staging_path = Path(
        tempfile.mkdtemp(
            prefix=f".{output_path.name}.{manifest.output_identity}.",
            suffix=".staging",
            dir=output_path.parent,
        )
    )
    try:
        for relative_path, payload in workspace_payloads.items():
            (staging_path / relative_path).write_bytes(payload)
        _validate_workspace(
            staging_path,
            output_path=output_path,
            manifest=manifest,
            manifest_sha256=manifest_sha256,
            analysis=analysis,
        )
        if output_path.exists():
            raise ConcurrentRobustnessError(
                ConcurrentRobustnessErrorCode.WORKSPACE_CONFLICT,
                "robustness output target appeared during atomic workspace creation",
            )
        os.replace(staging_path, output_path)
    except Exception:
        if staging_path.exists():
            shutil.rmtree(staging_path, ignore_errors=True)
        raise
    return _validate_workspace(
        output_path,
        output_path=output_path,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        analysis=analysis,
    )


class ConcurrentRobustnessStudy:
    """Run one validated static study behind a single high-level Interface.

    ``None`` is the only accepted Adapter value in this first slice. The Module
    validates and reads one explicit frozen Concurrent source, recomputes all 19
    ranking points without advancing runtime state, and atomically creates (or
    safely resumes) a private non-deployable workspace.
    """

    def run(
        self,
        manifest: ConcurrentRobustnessManifest,
        adapters_by_cell: Mapping[str, LLMDecisionAdapter] | None,
        output_dir: str | Path,
    ) -> ConcurrentRobustnessStudyResult:
        if not isinstance(manifest, ConcurrentRobustnessManifest):
            raise ConcurrentRobustnessError(
                ConcurrentRobustnessErrorCode.INVALID_MANIFEST,
                "ConcurrentRobustnessStudy requires a typed immutable manifest",
            )
        if adapters_by_cell is not None:
            raise ConcurrentRobustnessError(
                ConcurrentRobustnessErrorCode.UNSUPPORTED_ADAPTERS,
                "dynamic Prompt-Model adapters are unavailable in the static robustness slice",
            )

        source_path = _resolve_source_path(manifest.source.source_dir)
        output_path = _resolve_output_path(output_dir)
        _validate_study_paths(source_path, output_path)
        closure = _close_source(source_path)
        try:
            _validate_source_against_manifest(manifest, closure, source_path)
        except (KeyError, TypeError, ValueError) as exc:
            raise ConcurrentRobustnessError(
                ConcurrentRobustnessErrorCode.INVALID_SOURCE,
                "explicit Concurrent source identity or frozen contract does not match the study manifest",
            ) from exc
        _assert_source_unchanged(closure)

        manifest_payload = _manifest_bytes(manifest)
        manifest_sha256 = _sha256_bytes(manifest_payload)
        try:
            analyzer = _WeightSensitivityAnalyzer(
                manifest=manifest,
                candidate_rows=closure.source_evidence.candidate_rows,
                feedback_rows=closure.source_evidence.step_rows,
            )
            analysis = analyzer.analyze(manifest_sha256=manifest_sha256)
        except (KeyError, TypeError, ValueError) as exc:
            raise ConcurrentRobustnessError(
                ConcurrentRobustnessErrorCode.ANALYSIS_INVALID,
                "frozen candidate or feedback evidence failed the dedicated weight analysis contract",
            ) from exc
        _assert_source_unchanged(closure)
        if output_path.exists():
            result = _validate_workspace(
                output_path,
                output_path=output_path,
                manifest=manifest,
                manifest_sha256=manifest_sha256,
                analysis=analysis,
            )
            _assert_source_unchanged(closure)
            return result
        try:
            result = _write_new_workspace(
                output_path,
                manifest=manifest,
                manifest_payload=manifest_payload,
                analysis=analysis,
            )
        except ConcurrentRobustnessError:
            raise
        except OSError as exc:
            raise ConcurrentRobustnessError(
                ConcurrentRobustnessErrorCode.WORKSPACE_CONFLICT,
                "robustness workspace could not be written atomically",
            ) from exc
        _assert_source_unchanged(closure)
        return result
