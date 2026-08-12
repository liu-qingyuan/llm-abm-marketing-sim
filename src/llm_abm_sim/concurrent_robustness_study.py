from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import shutil
import tempfile
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .concurrent_execution_journal import ConcurrentExecutionJournal, derive_concurrent_execution_workspace
from .concurrent_message_experiment import (
    CONCURRENT_MESSAGE_CANDIDATE_FIELDS,
    CONCURRENT_MESSAGE_ENGAGED_NEIGHBOR_FORMULA,
    CONCURRENT_MESSAGE_PRODUCTION_DELIVERY_CAPACITY,
    CONCURRENT_MESSAGE_PRODUCTION_HORIZON,
    CONCURRENT_MESSAGE_PRODUCTION_SAMPLE_SIZE,
    CONCURRENT_MESSAGE_RANKING_FORMULA,
    ConcurrentMessageExperimentConfig,
    _PrimaryOnlyConcurrentRuntimeConsumer,
    _PrimaryOnlyConcurrentRuntimeResult,
)
from .concurrent_message_report import (
    CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_SCHEMA,
    ConcurrentMessageArtifactClosure,
    close_concurrent_message_artifacts,
)
from .concurrent_robustness_report import (
    _compose_concurrent_robustness_report_candidate,
    _RobustnessReportClosureError,
    _RobustnessReportConflictError,
    _RobustnessReportPathError,
    _validate_concurrent_robustness_report_candidate,
)
from .decision import LLMDecisionAdapter
from .final_research import FORMAL_RUN_STATUS, SEED_FIRST_SAMPLING_METHOD, VALIDATION_RUN_STATUS
from .prompt_contracts import CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY
from .provider_accounting import ProviderResponseEnvelope
from .provider_request_contract import (
    OMITTED_SAMPLING_PARAMETERS,
    STRUCTURED_OUTPUT_SCHEMA_HASH,
    ProviderRequestContract,
)
from .providers.openai_compatible import OpenAICompatibleDecisionAdapter
from .providers.pi_subscription import (
    PI_SUBSCRIPTION_ADAPTER_IDENTITY,
    PI_SUBSCRIPTION_MODEL_ALIASES,
    PiSubscriptionProviderClient,
)

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
CONCURRENT_ROBUSTNESS_OBSERVED_MODEL_POLICY = "exact-required-model-per-response-v1"
CONCURRENT_ROBUSTNESS_STOPPING_RULE = "reject-next-attempt-before-cap-v1"
CONCURRENT_ROBUSTNESS_VALIDATION_ADAPTER_IDENTITY = "openai-compatible-injected-client-v1"
CONCURRENT_ROBUSTNESS_LIVE_ADAPTER_IDENTITY = "openai-compatible-live-client-v1"
CONCURRENT_ROBUSTNESS_SUBSCRIPTION_ADAPTER_IDENTITY = PI_SUBSCRIPTION_ADAPTER_IDENTITY

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
_MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")

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
    required_observed_model: str | None = None

    @field_validator("requested_model", "required_observed_model")
    @classmethod
    def _validate_model_identity(cls, value: str | None) -> str | None:
        if value is not None and not _MODEL_ID_PATTERN.fullmatch(value):
            raise ValueError("Prompt-Model cell model identities must be safe stable tokens")
        return value


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


class _ExecutionAuthorization(_FrozenContractModel):
    schema_version: Literal["concurrent-robustness-execution-authorization-v1"]
    authorization_kind: Literal["deterministic_validation_fixture", "formal_live_provider"]
    authorization_reference: str = Field(min_length=1, max_length=240)
    artifact_sha256: str
    source_manifest_sha256: str
    output_identity: str
    allowed_cell_ids: tuple[str, ...]
    logical_judgment_cap: int = Field(ge=1)
    physical_attempt_cap: int = Field(ge=1)
    fee_ceiling_usd: float = Field(ge=0.0)
    external_requests_allowed: bool
    production_deploy_eligible: Literal[False]

    @model_validator(mode="after")
    def _validate_authorization(self) -> _ExecutionAuthorization:
        if not _SHA256_PATTERN.fullmatch(self.artifact_sha256) or not _SHA256_PATTERN.fullmatch(
            self.source_manifest_sha256
        ):
            raise ValueError("execution authorization hashes must be 64 lowercase hexadecimal characters")
        if not math.isfinite(self.fee_ceiling_usd):
            raise ValueError("execution authorization fee ceiling must be finite")
        if len(self.allowed_cell_ids) != len(set(self.allowed_cell_ids)):
            raise ValueError("execution authorization cell identities must be unique")
        return self


class _ModelQualification(_FrozenContractModel):
    schema_version: Literal["concurrent-robustness-model-qualification-v1"]
    qualification_kind: Literal["deterministic_validation_fixture", "provider_observed"]
    artifact_reference: str = Field(min_length=1, max_length=240)
    artifact_sha256: str
    provider: str
    requested_model: str
    required_observed_model: str
    status: Literal["qualified"]

    @model_validator(mode="after")
    def _validate_qualification(self) -> _ModelQualification:
        if not _SHA256_PATTERN.fullmatch(self.artifact_sha256):
            raise ValueError("model qualification artifact hash is invalid")
        if not _MODEL_ID_PATTERN.fullmatch(self.requested_model) or not _MODEL_ID_PATTERN.fullmatch(
            self.required_observed_model
        ):
            raise ValueError("model qualification identities are invalid")
        return self


class _ModelPricing(_FrozenContractModel):
    requested_model: str
    input_usd_per_million_tokens: float = Field(ge=0.0)
    output_usd_per_million_tokens: float = Field(ge=0.0)

    @model_validator(mode="after")
    def _validate_pricing(self) -> _ModelPricing:
        if not _MODEL_ID_PATTERN.fullmatch(self.requested_model):
            raise ValueError("pricing requested model identity is invalid")
        if not math.isfinite(self.input_usd_per_million_tokens) or not math.isfinite(
            self.output_usd_per_million_tokens
        ):
            raise ValueError("pricing rates must be finite")
        return self


class _PricingSnapshot(_FrozenContractModel):
    schema_version: Literal["concurrent-robustness-pricing-snapshot-v1"]
    snapshot_reference: str = Field(min_length=1, max_length=240)
    snapshot_sha256: str
    currency: Literal["USD"]
    input_token_ceiling: int = Field(ge=1)
    model_pricing: tuple[_ModelPricing, ...]

    @model_validator(mode="after")
    def _validate_snapshot(self) -> _PricingSnapshot:
        if not _SHA256_PATTERN.fullmatch(self.snapshot_sha256):
            raise ValueError("pricing snapshot hash is invalid")
        requested_models = tuple(row.requested_model for row in self.model_pricing)
        if requested_models != _ROBUSTNESS_MODELS:
            raise ValueError("pricing snapshot must cover the four requested models in canonical order")
        return self

    def maximum_attempt_cost(self, *, requested_model: str, output_token_ceiling: int) -> float:
        price = next(row for row in self.model_pricing if row.requested_model == requested_model)
        return (
            self.input_token_ceiling * price.input_usd_per_million_tokens
            + output_token_ceiling * price.output_usd_per_million_tokens
        ) / 1_000_000.0


class _DynamicExecutionContract(_FrozenContractModel):
    schema_version: Literal["concurrent-robustness-dynamic-execution-v1"]
    profile: Literal["deterministic_validation", "formal_live"]
    provider: str
    adapter_identity: str
    observed_model_policy: str
    stopping_rule: str
    authorization: _ExecutionAuthorization
    qualifications: tuple[_ModelQualification, ...]
    pricing_snapshot: _PricingSnapshot

    @model_validator(mode="after")
    def _validate_execution_contract(self) -> _DynamicExecutionContract:
        if self.provider != "openai_compatible":
            raise ValueError("dynamic execution requires the frozen openai_compatible provider")
        if self.observed_model_policy != CONCURRENT_ROBUSTNESS_OBSERVED_MODEL_POLICY:
            raise ValueError("dynamic execution observed-model policy is not frozen")
        if self.stopping_rule != CONCURRENT_ROBUSTNESS_STOPPING_RULE:
            raise ValueError("dynamic execution stopping rule is not frozen")
        if tuple(row.requested_model for row in self.qualifications) != _ROBUSTNESS_MODELS:
            raise ValueError("dynamic execution qualifications must cover four models in canonical order")
        if len({row.artifact_sha256 for row in self.qualifications}) != len(self.qualifications):
            raise ValueError("dynamic execution qualification artifacts must be independent")
        if any(row.provider != self.provider for row in self.qualifications):
            raise ValueError("dynamic execution qualifications must use the frozen provider")
        if self.profile == "deterministic_validation":
            if self.adapter_identity != CONCURRENT_ROBUSTNESS_VALIDATION_ADAPTER_IDENTITY:
                raise ValueError("validation execution requires the injected-client Adapter identity")
            if self.authorization.authorization_kind != "deterministic_validation_fixture":
                raise ValueError("validation execution requires a fixture-only authorization")
            if self.authorization.external_requests_allowed:
                raise ValueError("validation execution must forbid external requests")
            if any(row.qualification_kind != "deterministic_validation_fixture" for row in self.qualifications):
                raise ValueError("validation execution requires fixture qualification artifacts")
        else:
            if self.adapter_identity not in {
                CONCURRENT_ROBUSTNESS_LIVE_ADAPTER_IDENTITY,
                CONCURRENT_ROBUSTNESS_SUBSCRIPTION_ADAPTER_IDENTITY,
            }:
                raise ValueError("Formal execution requires an approved external Adapter identity")
            if self.authorization.authorization_kind != "formal_live_provider":
                raise ValueError("Formal execution requires an explicit live authorization")
            if not self.authorization.external_requests_allowed:
                raise ValueError("Formal execution authorization must explicitly allow external requests")
            if any(row.qualification_kind != "provider_observed" for row in self.qualifications):
                raise ValueError("Formal execution requires provider-observed qualification artifacts")
        return self


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
    dynamic_execution: _DynamicExecutionContract | None = None

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
        observed_contract = [cell.required_observed_model for cell in self.prompt_model_cells]
        if any(model is not None for model in observed_contract):
            if any(model is None for model in observed_contract):
                raise ValueError("manifest observed-model contract must cover all 16 cells or none")
            observed_by_requested: dict[str, str] = {}
            for cell in self.prompt_model_cells:
                assert cell.required_observed_model is not None
                previous = observed_by_requested.setdefault(
                    cell.requested_model,
                    cell.required_observed_model,
                )
                if previous != cell.required_observed_model:
                    raise ValueError("manifest requested model has mixed required observed identities")
            if (
                self.dynamic_execution is not None
                and self.dynamic_execution.adapter_identity
                == CONCURRENT_ROBUSTNESS_SUBSCRIPTION_ADAPTER_IDENTITY
            ):
                if observed_by_requested != PI_SUBSCRIPTION_MODEL_ALIASES:
                    raise ValueError("subscription manifest must bind the exact qualified Pi model aliases")
            elif observed_by_requested["gpt-5.4-mini"] != "gpt-5.4-mini-2026-03-17":
                raise ValueError("manifest mini model must bind its qualified observed identity")

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

        execution = self.dynamic_execution
        if execution is not None:
            authorization = execution.authorization
            canonical_cell_ids = tuple(cell.cell_id for cell in self.prompt_model_cells)
            if authorization.authorization_reference != self.authorization_reference:
                raise ValueError("dynamic execution authorization reference is crossed")
            if authorization.source_manifest_sha256 != self.source.manifest_sha256:
                raise ValueError("dynamic execution authorization source identity is crossed")
            if authorization.output_identity != self.output_identity:
                raise ValueError("dynamic execution authorization output identity is crossed")
            if authorization.allowed_cell_ids != canonical_cell_ids:
                raise ValueError("dynamic execution authorization must cover the exact 16 cells")
            if authorization.logical_judgment_cap != self.request_caps.logical_judgment_cap:
                raise ValueError("dynamic execution authorization logical cap is crossed")
            if authorization.physical_attempt_cap != self.request_caps.physical_attempt_cap:
                raise ValueError("dynamic execution authorization physical cap is crossed")
            if not math.isclose(
                authorization.fee_ceiling_usd,
                self.request_caps.fee_ceiling_usd,
                rel_tol=0.0,
                abs_tol=1e-12,
            ):
                raise ValueError("dynamic execution authorization fee ceiling is crossed")
            qualification_by_model = {row.requested_model: row for row in execution.qualifications}
            for cell in self.prompt_model_cells:
                qualification = qualification_by_model[cell.requested_model]
                if cell.required_observed_model is None:
                    raise ValueError("dynamic execution requires observed-model qualification for every cell")
                if qualification.required_observed_model != cell.required_observed_model:
                    raise ValueError("dynamic execution qualification observed identity is crossed")
            if execution.profile == "deterministic_validation" and self.source.kind != "fixture":
                raise ValueError("deterministic validation execution requires a fixture source")
            if execution.profile == "formal_live" and self.source.kind != "formal":
                raise ValueError("Formal live execution requires a Formal source")

        if self.source.kind == "formal":
            if self.sample.sample_size != CONCURRENT_MESSAGE_PRODUCTION_SAMPLE_SIZE:
                raise ValueError("Formal robustness source must freeze the 1,000-user sample")
            if self.ranking_contract.horizon != CONCURRENT_MESSAGE_PRODUCTION_HORIZON:
                raise ValueError("Formal robustness source must freeze the 30-batch schedule")
            if self.ranking_contract.delivery_capacity != CONCURRENT_MESSAGE_PRODUCTION_DELIVERY_CAPACITY:
                raise ValueError("Formal robustness source must freeze per-message Top20")
        return self


class ConcurrentRobustnessStudyResult(_FrozenContractModel):
    """Observable study result; report composition may follow a closed study root."""

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
        elif self.study_root is None:
            raise ValueError("complete results require a final study root")
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
_CELL_EVIDENCE = "prompt_model_cell_evidence.json"
_CELL_REGISTRY = "prompt_model_cell_registry.json"
_CELL_WORKSPACE_ADDITIONS = {_CELL_EVIDENCE, _CELL_REGISTRY}
_STUDY_ROOT_SUFFIX = ".study-root"
_STUDY_ROOT_MANIFEST = "artifact_manifest.json"
_STUDY_ROOT_ANALYSIS = "prompt_model_analysis.json"
_STUDY_ROOT_CLAIMS = "claim_audit.json"
_STUDY_ROOT_FILES = {
    _STUDY_ROOT_MANIFEST,
    _STUDY_ROOT_ANALYSIS,
    _STUDY_ROOT_CLAIMS,
    _CELL_EVIDENCE,
    _WORKSPACE_ANALYSIS,
    _WORKSPACE_MANIFEST,
    _WORKSPACE_VALIDATION,
}
_PRODUCTION_ROBUSTNESS_LOGICAL_JUDGMENTS = 28_800
_BOOTSTRAP_SEED = 20_260_809
_BOOTSTRAP_ITERATIONS = 500
_SAFE_CLAIM_STATEMENTS = (
    "Results are descriptive and conditional on the fixed sample, fixed graph, and one realized path per cell.",
    "Below-threshold values are labelled small observed differences only.",
    "One path per cell leaves model stochasticity unestimated.",
)
_POSITIVE_ACTIONS = {"like", "comment", "share"}


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


class _CellTerminalRow(_FrozenContractModel):
    terminal_row_id: str = Field(min_length=1, max_length=400)
    pair_id: str = Field(min_length=1, max_length=320)
    pair_schedule_position: int = Field(ge=0)
    time_step: int = Field(ge=0)
    message_id: str
    user_id: str = Field(min_length=1, max_length=240)
    is_seed: bool
    selection_reason: str = Field(min_length=1, max_length=120)
    decision_variant: Literal["primary"]
    prompt_version: str
    prompt_canonical_hash: str
    requested_model: str
    request_contract_sha256: str
    terminal_status: Literal["succeeded", "provider_failed"]
    engage: bool | None
    probability: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    action: Literal["like", "comment", "share", "ignore"] | None
    reason: str | None
    failure_type: str | None
    request_invocations: int = Field(ge=1)
    provider_response_count: int = Field(ge=0)
    successful_decision_count: int = Field(ge=0, le=1)
    observed_model_counts: dict[str, int]
    observed_model_missing_response_count: int = Field(ge=0)
    observed_model_malformed_response_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate_terminal(self) -> _CellTerminalRow:
        if not _SHA256_PATTERN.fullmatch(self.request_contract_sha256):
            raise ValueError("cell terminal request contract hash is invalid")
        if not _MODEL_ID_PATTERN.fullmatch(self.requested_model):
            raise ValueError("cell terminal requested model is invalid")
        if any(
            not _MODEL_ID_PATTERN.fullmatch(model) or type(count) is not int or count < 0
            for model, count in self.observed_model_counts.items()
        ):
            raise ValueError("cell terminal observed model accounting is invalid")
        observed_total = (
            sum(self.observed_model_counts.values())
            + self.observed_model_missing_response_count
            + self.observed_model_malformed_response_count
        )
        if observed_total != self.provider_response_count:
            raise ValueError("cell terminal observed model accounting does not cover responses")
        if not self.request_invocations >= self.provider_response_count >= self.successful_decision_count:
            raise ValueError("cell terminal accounting must satisfy invocations >= responses >= successes")
        decision_values = (self.engage, self.probability, self.confidence, self.action, self.reason)
        if self.terminal_status == "provider_failed":
            if self.successful_decision_count != 0 or any(value is not None for value in decision_values):
                raise ValueError("provider_failed terminal rows cannot contain a successful Decision")
            if not self.failure_type:
                raise ValueError("provider_failed terminal rows require a failure type")
        else:
            if self.successful_decision_count != 1 or any(value is None for value in decision_values):
                raise ValueError("succeeded terminal rows require one complete Decision")
            if self.failure_type is not None:
                raise ValueError("succeeded terminal rows cannot contain a failure type")
            if self.engage != (self.action in _POSITIVE_ACTIONS):
                raise ValueError("engage and action semantics are inconsistent")
        return self


class _CellStepMessage(_FrozenContractModel):
    message_id: str
    selected_user_ids: tuple[str, ...]
    seed_user_ids: tuple[str, ...]
    primary_positive_user_ids: tuple[str, ...]
    primary_provider_failed_user_ids: tuple[str, ...]


class _CellStepRow(_FrozenContractModel):
    time_step: int = Field(ge=0)
    frozen_campaign_engaged_user_ids: tuple[str, ...]
    deduplicated_committed_primary_positive_user_ids: tuple[str, ...]
    messages: tuple[_CellStepMessage, ...]


class _PromptModelCellEvidence(_FrozenContractModel):
    cell_index: int = Field(ge=0)
    cell_id: str
    prompt_variant: _PromptVariant
    prompt_version: str
    prompt_canonical_hash: str
    requested_model: str
    observed_model: str
    source_identity_sha256: str
    request_contract_sha256: str
    logical_judgment_count: int = Field(ge=1)
    physical_attempt_count: int = Field(ge=1)
    terminal_rows: tuple[_CellTerminalRow, ...]
    step_rows: tuple[_CellStepRow, ...]

    @model_validator(mode="after")
    def _validate_cell_counts(self) -> _PromptModelCellEvidence:
        if not _MODEL_ID_PATTERN.fullmatch(self.requested_model) or not _MODEL_ID_PATTERN.fullmatch(
            self.observed_model
        ):
            raise ValueError("cell model identities are invalid")
        if not _SHA256_PATTERN.fullmatch(self.source_identity_sha256) or not _SHA256_PATTERN.fullmatch(
            self.request_contract_sha256
        ):
            raise ValueError("cell evidence identity hashes are invalid")
        if self.logical_judgment_count != len(self.terminal_rows):
            raise ValueError("cell logical accounting does not match terminal rows")
        if self.physical_attempt_count != sum(row.request_invocations for row in self.terminal_rows):
            raise ValueError("cell physical accounting does not match terminal rows")
        return self


class _CellEvidenceDocument(_FrozenContractModel):
    schema_version: Literal["concurrent-robustness-cell-evidence-v1"]
    evidence_profile: Literal["deterministic_fixture", "formal_live"]
    manifest_sha256: str
    source_identity: dict[str, object]
    request_contract: _RequestContract
    request_contract_sha256: str
    message_ids: tuple[str, ...]
    cell_count: int = Field(ge=1)
    logical_judgment_count: int = Field(ge=1)
    physical_attempt_count: int = Field(ge=1)
    external_request_invocations: int = Field(ge=0)
    live_api_triggered: bool
    production_deploy_eligible: Literal[False]
    conditional_scope: Literal["fixed-sample-fixed-graph-one-realized-path-per-cell"]
    claim_statements: tuple[str, ...]
    cells: tuple[_PromptModelCellEvidence, ...]

    @model_validator(mode="after")
    def _validate_document_counts(self) -> _CellEvidenceDocument:
        for value in (self.manifest_sha256, self.request_contract_sha256):
            if not _SHA256_PATTERN.fullmatch(value):
                raise ValueError("cell evidence contains an invalid identity hash")
        if self.cell_count != len(self.cells):
            raise ValueError("cell evidence count does not match its cells")
        if self.logical_judgment_count != sum(cell.logical_judgment_count for cell in self.cells):
            raise ValueError("cell evidence logical accounting is inconsistent")
        if self.physical_attempt_count != sum(cell.physical_attempt_count for cell in self.cells):
            raise ValueError("cell evidence physical accounting is inconsistent")
        if self.live_api_triggered != (self.external_request_invocations > 0):
            raise ValueError("cell evidence live-call state is inconsistent")
        if self.evidence_profile == "deterministic_fixture" and self.external_request_invocations != 0:
            raise ValueError("deterministic fixture evidence cannot contain external requests")
        if self.evidence_profile == "formal_live" and self.external_request_invocations == 0:
            raise ValueError("Formal live evidence requires external request invocations")
        return self


class _CellInventoryRow(_FrozenContractModel):
    cell_id: str
    observed_model: str
    source_identity_sha256: str
    logical_judgment_count: int = Field(ge=1)
    physical_attempt_count: int = Field(ge=1)
    terminal_row_count: int = Field(ge=1)


class _CellWorkspaceRegistry(_FrozenContractModel):
    schema_version: Literal["concurrent-robustness-cell-registry-v1"]
    workspace_type: Literal["private_resumable"]
    status: Literal["cells_complete"]
    output_identity: str
    output_root_sha256: str
    manifest_sha256: str
    source_manifest_sha256: str
    base_workspace_sha256: dict[str, str]
    cell_evidence: Literal["prompt_model_cell_evidence.json"]
    cell_evidence_sha256: str
    cell_inventory: tuple[_CellInventoryRow, ...]
    logical_judgment_count: int = Field(ge=1)
    physical_attempt_count: int = Field(ge=1)
    external_request_invocations: int = Field(ge=0)
    production_deploy_eligible: Literal[False]

    @model_validator(mode="after")
    def _validate_registry_hashes(self) -> _CellWorkspaceRegistry:
        hash_values = (
            self.output_root_sha256,
            self.manifest_sha256,
            self.source_manifest_sha256,
            self.cell_evidence_sha256,
            *self.base_workspace_sha256.values(),
        )
        if not all(_SHA256_PATTERN.fullmatch(value) for value in hash_values):
            raise ValueError("cell registry contains an invalid identity hash")
        if set(self.base_workspace_sha256) != _WORKSPACE_FILES:
            raise ValueError("cell registry must authenticate the complete ready workspace")
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
    payload = manifest.model_dump(mode="json")
    if payload.get("dynamic_execution") is None:
        payload.pop("dynamic_execution", None)
    cells = payload.get("prompt_model_cells")
    if isinstance(cells, list):
        for cell in cells:
            if isinstance(cell, dict) and cell.get("required_observed_model") is None:
                cell.pop("required_observed_model", None)
    return _json_bytes(payload)


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
    allowed_extra_files: set[str] | None = None,
) -> ConcurrentRobustnessStudyResult:
    try:
        if workspace_path.is_symlink() or not workspace_path.is_dir():
            raise ValueError("workspace root is not a real directory")
        actual_files: set[str] = set()
        for path in workspace_path.iterdir():
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"workspace contains a non-regular artifact: {path.name}")
            actual_files.add(path.name)
        expected_files = _WORKSPACE_FILES | (allowed_extra_files or set())
        if actual_files != expected_files:
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


def _expected_cell_source_identity(
    manifest: ConcurrentRobustnessManifest,
) -> dict[str, object]:
    ranking_contract_sha256 = _sha256_bytes(_json_bytes(manifest.ranking_contract.model_dump(mode="json")))
    return {
        "source_id": manifest.source.source_id,
        "source_manifest_sha256": manifest.source.manifest_sha256,
        "sample_identity": manifest.sample.sample_identity,
        "message_snapshot_sha256": manifest.message_snapshot_sha256,
        "ranking_contract_sha256": ranking_contract_sha256,
    }


def _cell_source_identity_sha256(
    *,
    manifest_sha256: str,
    source_identity: Mapping[str, object],
    cell_id: str,
) -> str:
    return _sha256_bytes(
        _json_bytes(
            {
                "manifest_sha256": manifest_sha256,
                "source_identity": dict(source_identity),
                "cell_id": cell_id,
            }
        )
    )


def _guard_claim_statements(statements: Sequence[str]) -> None:
    if tuple(statements) != _SAFE_CLAIM_STATEMENTS:
        raise ValueError("cell evidence claim boundary is not the canonical conditional scope")
    forbidden_patterns = (
        r"\bcalibrat(?:ion|ed)\b",
        r"\bground[- ]?truth\b",
        r"\bcausal(?:ity| effect| claim)?\b",
        r"\bpopulation[- ]robust\b",
        r"\bstatistical(?:ly)? (?:equivalent|equivalence)\b",
        r"\b(?:eliminat|resolv)\w*.{0,40}\bmodel random",
        r"校准|因果|总体稳健|统计等价|消除.{0,20}模型随机性",
    )
    for statement in statements:
        if any(re.search(pattern, statement, flags=re.IGNORECASE) for pattern in forbidden_patterns):
            raise ValueError("cell evidence contains an out-of-scope robustness claim")


def _validate_unique_ids(values: Sequence[str], label: str) -> None:
    if any(not value for value in values) or len(values) != len(set(values)):
        raise ValueError(f"{label} must contain unique non-empty identities")


def _validate_cell_evidence_contract(
    evidence: _CellEvidenceDocument,
    *,
    manifest: ConcurrentRobustnessManifest,
    manifest_sha256: str,
) -> None:
    expected_source_identity = _expected_cell_source_identity(manifest)
    request_contract_payload = manifest.request_contract.model_dump(mode="json")
    request_contract_sha256 = _sha256_bytes(_json_bytes(request_contract_payload))
    if evidence.manifest_sha256 != manifest_sha256:
        raise ValueError("cell evidence manifest identity is crossed")
    if evidence.source_identity != expected_source_identity:
        raise ValueError("cell evidence source identity is crossed")
    if evidence.request_contract != manifest.request_contract:
        raise ValueError("cell evidence request contract is crossed")
    if evidence.request_contract_sha256 != request_contract_sha256:
        raise ValueError("cell evidence request contract hash is crossed")
    if evidence.message_ids != manifest.message_ids:
        raise ValueError("cell evidence message identity or order is crossed")
    if evidence.cell_count != 16 or len(evidence.cells) != 16:
        raise ValueError("cell evidence requires exactly 16 Prompt-Model cells")
    if evidence.logical_judgment_count != manifest.request_caps.logical_judgment_cap:
        raise ValueError("cell evidence logical accounting does not match the manifest cap")
    if evidence.physical_attempt_count > manifest.request_caps.physical_attempt_cap:
        raise ValueError("cell evidence physical accounting exceeds the manifest cap")
    if evidence.external_request_invocations > evidence.physical_attempt_count:
        raise ValueError("cell evidence external requests cannot exceed physical attempts")
    if evidence.evidence_profile == "deterministic_fixture":
        if manifest.source.kind != "fixture" or evidence.external_request_invocations != 0:
            raise ValueError("deterministic cell evidence requires a zero-call fixture source")
    else:
        execution = manifest.dynamic_execution
        if (
            manifest.source.kind != "formal"
            or execution is None
            or execution.profile != "formal_live"
            or evidence.external_request_invocations != evidence.physical_attempt_count
        ):
            raise ValueError("Formal live cell evidence does not match its execution contract")
    _guard_claim_statements(evidence.claim_statements)

    expected_group_keys = {
        (time_step, message_id)
        for time_step in range(manifest.ranking_contract.horizon)
        for message_id in manifest.message_ids
    }
    observed_by_requested_model: dict[str, str] = {}
    shared_seed_users: tuple[str, ...] | None = None
    for cell_index, (cell, manifest_cell) in enumerate(
        zip(evidence.cells, manifest.prompt_model_cells, strict=True)
    ):
        expected_identity = (
            cell_index,
            manifest_cell.cell_id,
            manifest_cell.prompt_variant,
            manifest_cell.prompt_version,
            manifest_cell.prompt_canonical_hash,
            manifest_cell.requested_model,
        )
        actual_identity = (
            cell.cell_index,
            cell.cell_id,
            cell.prompt_variant,
            cell.prompt_version,
            cell.prompt_canonical_hash,
            cell.requested_model,
        )
        if actual_identity != expected_identity:
            raise ValueError("cell evidence identity or canonical ordering is crossed")
        if cell.request_contract_sha256 != request_contract_sha256:
            raise ValueError("cell request contract hash is crossed")
        if manifest_cell.required_observed_model is None:
            raise ValueError("cell closure requires a Manifest-bound observed-model identity")
        if cell.observed_model != manifest_cell.required_observed_model:
            raise ValueError("cell observed model does not match the Manifest contract")
        expected_cell_source = _cell_source_identity_sha256(
            manifest_sha256=manifest_sha256,
            source_identity=expected_source_identity,
            cell_id=cell.cell_id,
        )
        if cell.source_identity_sha256 != expected_cell_source:
            raise ValueError("cell source identity is crossed")
        if cell.logical_judgment_count != manifest.request_caps.logical_judgments_per_cell:
            raise ValueError("cell logical count does not close its scaled schedule")
        per_cell_physical_cap = cell.logical_judgment_count * (manifest.request_contract.max_retries + 1)
        if cell.physical_attempt_count > per_cell_physical_cap:
            raise ValueError("cell physical accounting exceeds its retry contract")
        previous_observed = observed_by_requested_model.setdefault(cell.requested_model, cell.observed_model)
        if previous_observed != cell.observed_model:
            raise ValueError("one requested model has mixed observed identities across Prompts")

        groups: dict[tuple[int, str], list[_CellTerminalRow]] = defaultdict(list)
        seen_pair_ids: set[str] = set()
        seen_terminal_ids: set[str] = set()
        seen_user_messages: set[tuple[str, str]] = set()
        for expected_position, row in enumerate(cell.terminal_rows):
            if row.pair_schedule_position != expected_position:
                raise ValueError("cell terminal schedule positions must be contiguous from zero")
            if row.time_step >= manifest.ranking_contract.horizon or row.message_id not in manifest.message_ids:
                raise ValueError("cell terminal row falls outside the schedule contract")
            if row.pair_id != f"{row.user_id}:{row.message_id}:{row.time_step}":
                raise ValueError("cell terminal pair identity is malformed")
            if row.terminal_row_id != f"{row.pair_id}:primary":
                raise ValueError("cell terminal row identity is malformed")
            if row.pair_id in seen_pair_ids or row.terminal_row_id in seen_terminal_ids:
                raise ValueError("cell evidence contains duplicate pair or terminal identities")
            user_message = (row.user_id, row.message_id)
            if user_message in seen_user_messages:
                raise ValueError("cell evidence violates message-level single exposure")
            seen_pair_ids.add(row.pair_id)
            seen_terminal_ids.add(row.terminal_row_id)
            seen_user_messages.add(user_message)
            if (
                row.prompt_version != cell.prompt_version
                or row.prompt_canonical_hash != cell.prompt_canonical_hash
                or row.requested_model != cell.requested_model
                or row.request_contract_sha256 != request_contract_sha256
            ):
                raise ValueError("cell terminal Prompt, model, or request identity is crossed")
            if row.observed_model_missing_response_count or row.observed_model_malformed_response_count:
                raise ValueError("cell evidence requires a complete observed-model identity for every response")
            if set(row.observed_model_counts) - {cell.observed_model}:
                raise ValueError("cell terminal evidence contains mixed observed models")
            groups[(row.time_step, row.message_id)].append(row)
        if set(groups) != expected_group_keys:
            raise ValueError("cell terminal evidence is missing or adds message/batch groups")
        if any(
            len(rows) != manifest.ranking_contract.delivery_capacity
            for rows in groups.values()
        ):
            raise ValueError("cell terminal evidence does not close every message delivery capacity")

        if len(cell.step_rows) != manifest.ranking_contract.horizon:
            raise ValueError("cell step evidence must contain every realized batch")
        cumulative_positive_users: set[str] = set()
        cell_batch_zero_seed_users: tuple[str, ...] | None = None
        for expected_time_step, step in enumerate(cell.step_rows):
            if step.time_step != expected_time_step:
                raise ValueError("cell step rows must be contiguous from zero")
            if tuple(message.message_id for message in step.messages) != manifest.message_ids:
                raise ValueError("cell step message identity or order is crossed")
            if set(step.frozen_campaign_engaged_user_ids) != cumulative_positive_users:
                raise ValueError("cell batch-start campaign feedback snapshot is inconsistent")
            _validate_unique_ids(step.frozen_campaign_engaged_user_ids, "frozen campaign users")
            batch_positive_users: set[str] = set()
            batch_seed_users: tuple[str, ...] | None = None
            for message_step in step.messages:
                rows = groups[(expected_time_step, message_step.message_id)]
                selected_user_ids = tuple(row.user_id for row in rows)
                expected_seed_ids = tuple(row.user_id for row in rows if row.is_seed)
                expected_positive_ids = tuple(
                    row.user_id
                    for row in rows
                    if row.terminal_status == "succeeded" and row.action in _POSITIVE_ACTIONS
                )
                expected_failed_ids = tuple(
                    row.user_id for row in rows if row.terminal_status == "provider_failed"
                )
                if message_step.selected_user_ids != selected_user_ids:
                    raise ValueError("cell step selected audience is crossed with terminal evidence")
                if message_step.seed_user_ids != expected_seed_ids:
                    raise ValueError("cell step seed audience is crossed with terminal evidence")
                if message_step.primary_positive_user_ids != expected_positive_ids:
                    raise ValueError("cell step positive users are crossed with terminal Decisions")
                if message_step.primary_provider_failed_user_ids != expected_failed_ids:
                    raise ValueError("cell step Provider failures are crossed with terminal evidence")
                for label, values in (
                    ("selected users", message_step.selected_user_ids),
                    ("seed users", message_step.seed_user_ids),
                    ("positive users", message_step.primary_positive_user_ids),
                    ("failed users", message_step.primary_provider_failed_user_ids),
                ):
                    _validate_unique_ids(values, label)
                if set(message_step.primary_positive_user_ids) & set(
                    message_step.primary_provider_failed_user_ids
                ):
                    raise ValueError("Provider failures cannot produce positive campaign feedback")
                batch_positive_users.update(message_step.primary_positive_user_ids)
                if expected_time_step == 0:
                    if batch_seed_users is None:
                        batch_seed_users = message_step.seed_user_ids
                    elif set(batch_seed_users) != set(message_step.seed_user_ids):
                        raise ValueError("Batch 0 shared seed set differs across messages")
            committed_users = step.deduplicated_committed_primary_positive_user_ids
            _validate_unique_ids(committed_users, "committed campaign users")
            if set(committed_users) != batch_positive_users:
                raise ValueError("cell committed campaign feedback is not deduplicated from Primary positives")
            cumulative_positive_users.update(batch_positive_users)
            if expected_time_step == 0:
                cell_batch_zero_seed_users = batch_seed_users
        if not cell_batch_zero_seed_users:
            raise ValueError("cell evidence requires a non-empty Batch 0 shared-seed panel")
        if shared_seed_users is None:
            shared_seed_users = cell_batch_zero_seed_users
        elif set(shared_seed_users) != set(cell_batch_zero_seed_users):
            raise ValueError("Batch 0 shared seed set differs across Prompt-Model cells")


def _load_cell_workspace(
    workspace_path: Path,
    *,
    output_path: Path,
    manifest: ConcurrentRobustnessManifest,
    manifest_sha256: str,
) -> tuple[_CellEvidenceDocument, _CellWorkspaceRegistry]:
    try:
        registry_path = workspace_path / _CELL_REGISTRY
        evidence_path = workspace_path / _CELL_EVIDENCE
        registry = _CellWorkspaceRegistry.model_validate(_read_json_object(registry_path))
        if registry.output_identity != manifest.output_identity:
            raise ValueError("cell registry output identity is crossed")
        if registry.output_root_sha256 != _output_root_sha256(output_path):
            raise ValueError("cell registry workspace identity is crossed")
        if registry.manifest_sha256 != manifest_sha256:
            raise ValueError("cell registry manifest identity is crossed")
        if registry.source_manifest_sha256 != manifest.source.manifest_sha256:
            raise ValueError("cell registry source identity is crossed")
        for relative_path, expected_hash in registry.base_workspace_sha256.items():
            if _sha256_file(workspace_path / relative_path) != expected_hash:
                raise ValueError("cell registry base workspace hash is crossed")
        if _sha256_file(evidence_path) != registry.cell_evidence_sha256:
            raise ValueError("cell registry evidence hash is crossed")
        evidence = _CellEvidenceDocument.model_validate(_read_json_object(evidence_path))
        _validate_cell_evidence_contract(
            evidence,
            manifest=manifest,
            manifest_sha256=manifest_sha256,
        )
        expected_inventory = tuple(
            _CellInventoryRow(
                cell_id=cell.cell_id,
                observed_model=cell.observed_model,
                source_identity_sha256=cell.source_identity_sha256,
                logical_judgment_count=cell.logical_judgment_count,
                physical_attempt_count=cell.physical_attempt_count,
                terminal_row_count=len(cell.terminal_rows),
            )
            for cell in evidence.cells
        )
        if registry.cell_inventory != expected_inventory:
            raise ValueError("cell registry inventory is crossed with cell evidence")
        if registry.logical_judgment_count != evidence.logical_judgment_count:
            raise ValueError("cell registry logical accounting is crossed")
        if registry.physical_attempt_count != evidence.physical_attempt_count:
            raise ValueError("cell registry physical accounting is crossed")
        if registry.external_request_invocations != evidence.external_request_invocations:
            raise ValueError("cell registry external request accounting is crossed")
        return evidence, registry
    except ConcurrentRobustnessError:
        raise
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ConcurrentRobustnessError(
            ConcurrentRobustnessErrorCode.WORKSPACE_CORRUPT,
            "Prompt-Model cell workspace failed registry or terminal evidence closure",
        ) from exc


def _mean(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("analysis mean requires at least one value")
    return sum(values) / len(values)


def _rate(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else _round_metric(numerator / denominator)


def _successful_probability(row: _CellTerminalRow) -> float:
    if row.terminal_status != "succeeded" or row.probability is None:
        raise ValueError("probability summaries require successful Primary Decisions")
    return row.probability


def _jaccard_distance(left: set[str], right: set[str]) -> float:
    union = left | right
    return 0.0 if not union else _round_metric(1.0 - len(left & right) / len(union))


def _quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("bootstrap interval requires at least one estimate")
    position = (len(ordered) - 1) * probability
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return ordered[lower_index]
    fraction = position - lower_index
    return ordered[lower_index] * (1.0 - fraction) + ordered[upper_index] * fraction


def _shared_seed_direct_analysis(
    evidence: _CellEvidenceDocument,
    manifest: ConcurrentRobustnessManifest,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cell_rows_by_pair: dict[str, dict[tuple[str, str], _CellTerminalRow]] = {}
    fixed_pair_sets: list[set[tuple[str, str]]] = []
    for cell in evidence.cells:
        rows_by_pair = {
            (row.user_id, row.message_id): row
            for row in cell.terminal_rows
            if row.time_step == 0 and row.is_seed
        }
        cell_rows_by_pair[cell.cell_id] = rows_by_pair
        fixed_pair_sets.append(set(rows_by_pair))
    fixed_pairs = set.intersection(*fixed_pair_sets)
    if not fixed_pairs:
        raise ValueError("shared-seed direct analysis has no common fixed pairs")
    message_set = set(manifest.message_ids)
    fixed_users = sorted(
        {
            user_id
            for user_id, _message_id in fixed_pairs
            if {message_id for candidate_user, message_id in fixed_pairs if candidate_user == user_id}
            == message_set
        }
    )
    complete_users = [
        user_id
        for user_id in fixed_users
        if all(
            cell_rows_by_pair[cell.cell_id][(user_id, message_id)].terminal_status == "succeeded"
            for cell in evidence.cells
            for message_id in manifest.message_ids
        )
    ]
    complete_pairs = [
        (user_id, message_id)
        for user_id in complete_users
        for message_id in manifest.message_ids
    ]
    if not complete_pairs:
        raise ValueError("shared-seed direct analysis has no complete user blocks")

    exact_rows: list[dict[str, Any]] = []
    for cell in evidence.cells:
        for user_id, message_id in complete_pairs:
            terminal = cell_rows_by_pair[cell.cell_id][(user_id, message_id)]
            assert terminal.engage is not None
            assert terminal.probability is not None
            assert terminal.confidence is not None
            assert terminal.action is not None
            exact_rows.append(
                {
                    "cell_id": cell.cell_id,
                    "prompt_variant": cell.prompt_variant,
                    "requested_model": cell.requested_model,
                    "observed_model": cell.observed_model,
                    "user_id": user_id,
                    "message_id": message_id,
                    "engage": terminal.engage,
                    "action": terminal.action,
                    "probability": terminal.probability,
                    "confidence": terminal.confidence,
                }
            )

    rows_by_cell: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for exact_row in exact_rows:
        rows_by_cell[str(exact_row["cell_id"])].append(exact_row)
    cell_summaries: list[dict[str, Any]] = []
    for cell in evidence.cells:
        rows = rows_by_cell[cell.cell_id]
        cell_summaries.append(
            {
                "cell_id": cell.cell_id,
                "engage_rate": _round_metric(_mean([float(bool(row["engage"])) for row in rows])),
                "mean_probability": _round_metric(_mean([float(row["probability"]) for row in rows])),
                "mean_confidence": _round_metric(_mean([float(row["confidence"]) for row in rows])),
                "observation_count": len(rows),
            }
        )

    baseline_cell_id = evidence.cells[0].cell_id
    baseline_by_pair = {
        (str(row["user_id"]), str(row["message_id"])): row
        for row in rows_by_cell[baseline_cell_id]
    }
    comparisons: list[dict[str, Any]] = []
    for cell in evidence.cells:
        rows = rows_by_cell[cell.cell_id]
        transitions: Counter[str] = Counter()
        disagreements = 0
        probability_deltas: list[float] = []
        confidence_deltas: list[float] = []
        engage_deltas: list[float] = []
        for comparison_row in rows:
            pair_key = (str(comparison_row["user_id"]), str(comparison_row["message_id"]))
            baseline = baseline_by_pair[pair_key]
            transitions[f"{baseline['action']}->{comparison_row['action']}"] += 1
            disagreements += int(bool(baseline["engage"]) != bool(comparison_row["engage"]))
            engage_deltas.append(
                float(bool(comparison_row["engage"])) - float(bool(baseline["engage"]))
            )
            probability_deltas.append(
                float(comparison_row["probability"]) - float(baseline["probability"])
            )
            confidence_deltas.append(
                float(comparison_row["confidence"]) - float(baseline["confidence"])
            )
        comparisons.append(
            {
                "cell_id": cell.cell_id,
                "reference_cell_id": baseline_cell_id,
                "engage_rate_difference": _round_metric(_mean(engage_deltas)),
                "engage_disagreement_count": disagreements,
                "engage_disagreement_rate": _rate(disagreements, len(rows)),
                "action_transitions": dict(sorted(transitions.items())),
                "mean_probability_difference": _round_metric(_mean(probability_deltas)),
                "mean_confidence_difference": _round_metric(_mean(confidence_deltas)),
                "secondary_metrics": [
                    "engage_disagreement",
                    "action_transition",
                    "mean_probability_difference",
                    "mean_confidence_difference",
                ],
            }
        )
    return (
        {
            "schema_version": "concurrent-shared-seed-direct-decision-analysis-v1",
            "exact_value_row_schema_version": "concurrent-shared-seed-decision-row-v1",
            "primary_outcome": "binary_engage",
            "pairing_basis": "Batch_0_shared_seed_user_message_pairs_common_to_all_cells",
            "fixed_user_count": len(fixed_users),
            "fixed_pair_count": len(fixed_users) * len(manifest.message_ids),
            "complete_user_block_count": len(complete_users),
            "complete_decision_pair_count": len(complete_pairs),
            "excluded_incomplete_user_block_count": len(fixed_users) - len(complete_users),
            "exact_value_row_count": len(exact_rows),
            "cell_summaries": cell_summaries,
            "baseline_comparisons": comparisons,
            "exact_value_rows": exact_rows,
        },
        exact_rows,
    )


def _factor_estimands(rows: Sequence[Mapping[str, Any]]) -> tuple[dict[str, float], dict[str, Any]]:
    def group_mean(field_name: str, value: str) -> float:
        values = [float(bool(row["engage"])) for row in rows if row[field_name] == value]
        return _mean(values)

    cell_ids = list(dict.fromkeys(str(row["cell_id"]) for row in rows))
    prompts = list(dict.fromkeys(str(row["prompt_variant"]) for row in rows))
    models = list(dict.fromkeys(str(row["requested_model"]) for row in rows))
    messages = list(dict.fromkeys(str(row["message_id"]) for row in rows))
    cell_means = {cell_id: group_mean("cell_id", cell_id) for cell_id in cell_ids}
    prompt_means = {prompt: group_mean("prompt_variant", prompt) for prompt in prompts}
    model_means = {model: group_mean("requested_model", model) for model in models}
    message_means = {message: group_mean("message_id", message) for message in messages}
    grand_mean = _mean([float(bool(row["engage"])) for row in rows])
    estimands: dict[str, float] = {}
    for prompt in prompts:
        estimands[f"prompt_effect:{prompt}"] = prompt_means[prompt] - grand_mean
    for prompt in prompts[1:]:
        estimands[f"prompt_contrast:{prompt}_vs_{prompts[0]}"] = prompt_means[prompt] - prompt_means[prompts[0]]
    for model in models:
        estimands[f"model_effect:{model}"] = model_means[model] - grand_mean
    for message in messages:
        estimands[f"message_effect:{message}"] = message_means[message] - grand_mean
    for message in messages[1:]:
        estimands[f"message_contrast:{message}_vs_{messages[0]}"] = (
            message_means[message] - message_means[messages[0]]
        )
    planned_specs = (
        ("gpt-5.4-mini_vs_gpt-5.4", models[0], models[1]),
        ("gpt-5.4_vs_gpt-5.5", models[1], models[2]),
        ("gpt-5.5_vs_gpt-5.6-sol", models[2], models[3]),
    )
    for contrast_id, left, right in planned_specs:
        estimands[f"planned_model_contrast:{contrast_id}"] = model_means[left] - model_means[right]
    cell_by_factor = {
        (str(row["prompt_variant"]), str(row["requested_model"])): str(row["cell_id"])
        for row in rows
    }
    baseline_prompt = prompts[0]
    baseline_model = models[0]
    for prompt in prompts[1:]:
        for model in models[1:]:
            estimate = (
                cell_means[cell_by_factor[(prompt, model)]]
                - cell_means[cell_by_factor[(baseline_prompt, model)]]
                - cell_means[cell_by_factor[(prompt, baseline_model)]]
                + cell_means[cell_by_factor[(baseline_prompt, baseline_model)]]
            )
            estimands[f"prompt_model_interaction:{prompt}::{model}"] = estimate
    return estimands, {
        "grand_mean": grand_mean,
        "cell_means": cell_means,
        "prompt_means": prompt_means,
        "model_means": model_means,
        "message_means": message_means,
        "prompts": prompts,
        "models": models,
        "messages": messages,
        "planned_specs": planned_specs,
    }


def _bootstrap_intervals(
    exact_rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, dict[str, float]], dict[str, Any]]:
    rows_by_user: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in exact_rows:
        rows_by_user[str(row["user_id"])].append(row)
    users = sorted(rows_by_user)
    if not users:
        raise ValueError("user-blocked bootstrap requires complete shared-seed users")
    expected_messages = {
        str(row["message_id"])
        for row in exact_rows
    }
    for user_id, user_rows in rows_by_user.items():
        if {str(row["message_id"]) for row in user_rows} != expected_messages:
            raise ValueError(f"bootstrap user block is missing one of the fixed messages: {user_id}")
    point_estimands, _ = _factor_estimands(exact_rows)
    sampled_values: dict[str, list[float]] = {estimate_id: [] for estimate_id in point_estimands}
    generator = random.Random(_BOOTSTRAP_SEED)
    for _iteration in range(_BOOTSTRAP_ITERATIONS):
        sampled_rows: list[Mapping[str, Any]] = []
        for _block in users:
            sampled_user = users[generator.randrange(len(users))]
            sampled_rows.extend(rows_by_user[sampled_user])
        replicate, _ = _factor_estimands(sampled_rows)
        for estimate_id, value in replicate.items():
            sampled_values[estimate_id].append(value)
    intervals = {
        estimate_id: {
            "lower": _round_metric(_quantile(values, 0.025)),
            "upper": _round_metric(_quantile(values, 0.975)),
        }
        for estimate_id, values in sampled_values.items()
    }
    return intervals, {
        "schema_version": "concurrent-user-blocked-bootstrap-v1",
        "seed": _BOOTSTRAP_SEED,
        "iterations": _BOOTSTRAP_ITERATIONS,
        "block": "user_with_all_three_messages",
        "block_user_count": len(users),
        "messages_per_user_block": len(expected_messages),
        "interval": "percentile_2.5_97.5_linear_interpolation",
        "conditional_scope": "fixed_sample_fixed_graph_one_realized_path_per_cell",
        "intervals": [
            {"estimate_id": estimate_id, **interval}
            for estimate_id, interval in sorted(intervals.items())
        ],
    }


def _fixed_factor_summary(
    exact_rows: Sequence[Mapping[str, Any]],
    intervals: Mapping[str, Mapping[str, float]],
) -> tuple[dict[str, Any], dict[str, float]]:
    estimands, values = _factor_estimands(exact_rows)

    def estimate_row(estimate_id: str, **identity: object) -> dict[str, Any]:
        return {
            **identity,
            "estimate_id": estimate_id,
            "estimate": _round_metric(estimands[estimate_id]),
            "conditional_interval": dict(intervals[estimate_id]),
        }

    prompts = list(values["prompts"])
    models = list(values["models"])
    messages = list(values["messages"])
    prompt_effects = [
        estimate_row(
            f"prompt_effect:{prompt}",
            prompt_variant=prompt,
            marginal_engage_rate=_round_metric(values["prompt_means"][prompt]),
        )
        for prompt in prompts
    ]
    prompt_contrasts = [
        estimate_row(
            f"prompt_contrast:{prompt}_vs_{prompts[0]}",
            contrast_id=f"{prompt}_vs_{prompts[0]}",
            left=prompt,
            right=prompts[0],
            direction="left_minus_right",
        )
        for prompt in prompts[1:]
    ]
    model_effects = [
        estimate_row(
            f"model_effect:{model}",
            requested_model=model,
            marginal_engage_rate=_round_metric(values["model_means"][model]),
        )
        for model in models
    ]
    planned_model_contrasts = [
        estimate_row(
            f"planned_model_contrast:{contrast_id}",
            contrast_id=contrast_id,
            left_model=left,
            right_model=right,
            direction="left_minus_right",
        )
        for contrast_id, left, right in values["planned_specs"]
    ]
    message_effects = [
        estimate_row(
            f"message_effect:{message}",
            message_id=message,
            marginal_engage_rate=_round_metric(values["message_means"][message]),
        )
        for message in messages
    ]
    interactions = [
        estimate_row(
            estimate_id,
            prompt_variant=estimate_id.split(":", 1)[1].split("::", 1)[0],
            requested_model=estimate_id.rsplit("::", 1)[1],
            form="difference_in_differences_against_P0_and_gpt-5.4-mini",
        )
        for estimate_id in estimands
        if estimate_id.startswith("prompt_model_interaction:")
    ]
    return (
        {
            "schema_version": "concurrent-fixed-factor-summary-v1",
            "primary_outcome": "binary_engage",
            "factor_types": {
                "prompt": "fixed_categorical",
                "model": "fixed_categorical",
                "message": "fixed_categorical",
            },
            "linear_model_version_trend_computed": False,
            "grand_mean_engage": _round_metric(values["grand_mean"]),
            "cell_engage_rates": [
                {"cell_id": cell_id, "engage_rate": _round_metric(rate)}
                for cell_id, rate in values["cell_means"].items()
            ],
            "prompt_effects": prompt_effects,
            "prompt_contrasts": prompt_contrasts,
            "model_effects": model_effects,
            "planned_model_contrasts": planned_model_contrasts,
            "message_effects": message_effects,
            "prompt_model_interactions": interactions,
        },
        estimands,
    )


def _realized_path_analysis(
    evidence: _CellEvidenceDocument,
    manifest: ConcurrentRobustnessManifest,
) -> dict[str, Any]:
    baseline = evidence.cells[0]
    baseline_batch_audiences = {
        (row.time_step, row.message_id): {
            candidate.user_id
            for candidate in baseline.terminal_rows
            if candidate.time_step == row.time_step and candidate.message_id == row.message_id
        }
        for row in baseline.terminal_rows
    }
    trajectory_rows: list[dict[str, Any]] = []
    message_summaries: list[dict[str, Any]] = []
    campaign_growth_rows: list[dict[str, Any]] = []
    macro_summaries: list[dict[str, Any]] = []
    for cell in evidence.cells:
        rows_by_message: dict[str, list[_CellTerminalRow]] = defaultdict(list)
        rows_by_batch_message: dict[tuple[int, str], list[_CellTerminalRow]] = defaultdict(list)
        for row in cell.terminal_rows:
            rows_by_message[row.message_id].append(row)
            rows_by_batch_message[(row.time_step, row.message_id)].append(row)
        message_rates: list[tuple[float, float]] = []
        for message_id in manifest.message_ids:
            message_rows = rows_by_message[message_id]
            first_divergent_batch: int | None = None
            cumulative_rows: list[_CellTerminalRow] = []
            for time_step in range(manifest.ranking_contract.horizon):
                batch_rows = rows_by_batch_message[(time_step, message_id)]
                cumulative_rows.extend(batch_rows)
                batch_successes = [row for row in batch_rows if row.terminal_status == "succeeded"]
                batch_positives = [row for row in batch_successes if row.action in _POSITIVE_ACTIONS]
                cumulative_successes = [row for row in cumulative_rows if row.terminal_status == "succeeded"]
                cumulative_positives = [row for row in cumulative_successes if row.action in _POSITIVE_ACTIONS]
                batch_audience = {row.user_id for row in batch_rows}
                baseline_batch = baseline_batch_audiences[(time_step, message_id)]
                batch_overlap = batch_audience & baseline_batch
                batch_union = batch_audience | baseline_batch
                batch_distance = _jaccard_distance(batch_audience, baseline_batch)
                if batch_distance > 0.0 and first_divergent_batch is None:
                    first_divergent_batch = time_step
                cumulative_audience = {row.user_id for row in cumulative_rows}
                baseline_cumulative = set().union(
                    *(
                        baseline_batch_audiences[(candidate_time, message_id)]
                        for candidate_time in range(time_step + 1)
                    )
                )
                cumulative_overlap = cumulative_audience & baseline_cumulative
                cumulative_union = cumulative_audience | baseline_cumulative
                cumulative_distance = _jaccard_distance(cumulative_audience, baseline_cumulative)
                trajectory_rows.append(
                    {
                        "cell_id": cell.cell_id,
                        "message_id": message_id,
                        "time_step": time_step,
                        "batch_actual_exposures": len(batch_rows),
                        "batch_successful_primary_decisions": len(batch_successes),
                        "batch_provider_failures": len(batch_rows) - len(batch_successes),
                        "batch_positive_actions": len(batch_positives),
                        "batch_exposure_engagement_rate": _rate(len(batch_positives), len(batch_rows)),
                        "batch_decision_engagement_rate": _rate(len(batch_positives), len(batch_successes)),
                        "batch_mean_probability_successful_decisions": (
                            _round_metric(_mean([_successful_probability(row) for row in batch_successes]))
                            if batch_successes
                            else None
                        ),
                        "cumulative_actual_exposures": len(cumulative_rows),
                        "cumulative_successful_primary_decisions": len(cumulative_successes),
                        "cumulative_provider_failures": len(cumulative_rows) - len(cumulative_successes),
                        "cumulative_positive_actions": len(cumulative_positives),
                        "cumulative_exposure_engagement_rate": _rate(
                            len(cumulative_positives), len(cumulative_rows)
                        ),
                        "cumulative_decision_engagement_rate": _rate(
                            len(cumulative_positives), len(cumulative_successes)
                        ),
                        "batch_audience_user_ids": sorted(batch_audience),
                        "batch_audience_overlap_count_with_baseline_cell": len(batch_overlap),
                        "batch_audience_union_count_with_baseline_cell": len(batch_union),
                        "batch_audience_jaccard_similarity_with_baseline_cell": _round_metric(
                            1.0 - batch_distance
                        ),
                        "batch_audience_jaccard_distance_from_baseline_cell": batch_distance,
                        "cumulative_audience_overlap_count_with_baseline_cell": len(cumulative_overlap),
                        "cumulative_audience_union_count_with_baseline_cell": len(cumulative_union),
                        "cumulative_audience_jaccard_similarity_with_baseline_cell": _round_metric(
                            1.0 - cumulative_distance
                        ),
                        "cumulative_audience_jaccard_distance_from_baseline_cell": cumulative_distance,
                        "cumulative_unique_positive_user_ids": sorted(
                            {row.user_id for row in cumulative_positives}
                        ),
                    }
                )
            successes = [row for row in message_rows if row.terminal_status == "succeeded"]
            positives = [row for row in successes if row.action in _POSITIVE_ACTIONS]
            exposure_rate = _rate(len(positives), len(message_rows))
            decision_rate = _rate(len(positives), len(successes))
            assert exposure_rate is not None and decision_rate is not None
            message_rates.append((exposure_rate, decision_rate))
            terminal_trajectory = trajectory_rows[-1]
            message_summaries.append(
                {
                    "cell_id": cell.cell_id,
                    "message_id": message_id,
                    "actual_exposures": len(message_rows),
                    "successful_primary_decisions": len(successes),
                    "provider_failures": len(message_rows) - len(successes),
                    "positive_actions": len(positives),
                    "exposure_engagement_rate": exposure_rate,
                    "decision_engagement_rate": decision_rate,
                    "mean_probability_successful_decisions": (
                        _round_metric(_mean([_successful_probability(row) for row in successes]))
                        if successes
                        else None
                    ),
                    "first_divergent_batch_from_baseline_cell": first_divergent_batch,
                    "terminal_audience_overlap_count_with_baseline_cell": terminal_trajectory[
                        "cumulative_audience_overlap_count_with_baseline_cell"
                    ],
                    "terminal_audience_jaccard_similarity_with_baseline_cell": terminal_trajectory[
                        "cumulative_audience_jaccard_similarity_with_baseline_cell"
                    ],
                    "terminal_audience_jaccard_distance_from_baseline_cell": terminal_trajectory[
                        "cumulative_audience_jaccard_distance_from_baseline_cell"
                    ],
                    "terminal_unique_positive_users": len(
                        terminal_trajectory["cumulative_unique_positive_user_ids"]
                    ),
                }
            )
        for time_step in range(manifest.ranking_contract.horizon):
            positive_users = {
                row.user_id
                for row in cell.terminal_rows
                if row.time_step <= time_step
                and row.terminal_status == "succeeded"
                and row.action in _POSITIVE_ACTIONS
            }
            campaign_growth_rows.append(
                {
                    "cell_id": cell.cell_id,
                    "time_step": time_step,
                    "cumulative_campaign_deduplicated_positive_user_count": len(positive_users),
                    "cumulative_campaign_deduplicated_positive_user_ids": sorted(positive_users),
                }
            )
        macro_summaries.append(
            {
                "cell_id": cell.cell_id,
                "scope": "secondary_macro_average_across_messages",
                "mean_exposure_engagement_rate": _round_metric(
                    _mean([rates[0] for rates in message_rates])
                ),
                "mean_decision_engagement_rate": _round_metric(
                    _mean([rates[1] for rates in message_rates])
                ),
            }
        )
    return {
        "schema_version": "concurrent-realized-path-analysis-v1",
        "trajectory_row_schema_version": "concurrent-realized-path-message-batch-row-v1",
        "reference_cell_id": baseline.cell_id,
        "message_summaries": message_summaries,
        "message_batch_trajectories": trajectory_rows,
        "campaign_deduplicated_positive_user_growth": campaign_growth_rows,
        "secondary_macro_summaries": macro_summaries,
    }


def _threshold_classification(value: float, threshold: float) -> str:
    return "practically_meaningful" if abs(value) >= threshold else "small_observed_difference"


def _practical_threshold_rows(
    *,
    direct: Mapping[str, Any],
    realized_paths: Mapping[str, Any],
    factor_estimands: Mapping[str, float],
    manifest: ConcurrentRobustnessManifest,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def append(
        comparison_id: str,
        domain: str,
        metric: str,
        difference: float,
        threshold: float,
    ) -> None:
        rows.append(
            {
                "comparison_id": comparison_id,
                "domain": domain,
                "metric": metric,
                "observed_difference": _round_metric(difference),
                "absolute_difference": _round_metric(abs(difference)),
                "threshold": threshold,
                "classification": _threshold_classification(difference, threshold),
            }
        )

    direct_comparisons = list(direct["baseline_comparisons"])
    for comparison in direct_comparisons[1:]:
        cell_id = str(comparison["cell_id"])
        append(
            f"{cell_id}:shared_seed_engage",
            "shared_seed_direct_decision",
            "engage_rate_difference",
            float(comparison["engage_rate_difference"]),
            manifest.practical_thresholds.engagement_rate_absolute,
        )
        append(
            f"{cell_id}:shared_seed_probability",
            "shared_seed_direct_decision_secondary",
            "mean_probability_difference",
            float(comparison["mean_probability_difference"]),
            manifest.practical_thresholds.decision_probability_absolute,
        )

    message_summaries = list(realized_paths["message_summaries"])
    baseline_cell_id = str(realized_paths["reference_cell_id"])
    baseline_messages = {
        str(row["message_id"]): row
        for row in message_summaries
        if row["cell_id"] == baseline_cell_id
    }
    for summary in message_summaries:
        if summary["cell_id"] == baseline_cell_id:
            continue
        baseline = baseline_messages[str(summary["message_id"])]
        prefix = f"{summary['cell_id']}:{summary['message_id']}"
        append(
            f"{prefix}:exposure_rate",
            "realized_path",
            "exposure_engagement_rate_difference",
            float(summary["exposure_engagement_rate"]) - float(baseline["exposure_engagement_rate"]),
            manifest.practical_thresholds.engagement_rate_absolute,
        )
        append(
            f"{prefix}:decision_rate",
            "realized_path",
            "decision_engagement_rate_difference",
            float(summary["decision_engagement_rate"]) - float(baseline["decision_engagement_rate"]),
            manifest.practical_thresholds.engagement_rate_absolute,
        )
        append(
            f"{prefix}:audience",
            "realized_path",
            "terminal_audience_jaccard_distance",
            float(summary["terminal_audience_jaccard_distance_from_baseline_cell"]),
            manifest.practical_thresholds.audience_jaccard_distance,
        )

    growth_rows = list(realized_paths["campaign_deduplicated_positive_user_growth"])
    terminal_step = manifest.ranking_contract.horizon - 1
    baseline_terminal = next(
        row
        for row in growth_rows
        if row["cell_id"] == baseline_cell_id and row["time_step"] == terminal_step
    )
    for row in growth_rows:
        if row["cell_id"] == baseline_cell_id or row["time_step"] != terminal_step:
            continue
        append(
            f"{row['cell_id']}:terminal_campaign_positive_users",
            "realized_path",
            "terminal_campaign_positive_user_count_difference",
            float(row["cumulative_campaign_deduplicated_positive_user_count"])
            - float(baseline_terminal["cumulative_campaign_deduplicated_positive_user_count"]),
            float(manifest.practical_thresholds.terminal_unique_positive_user_count),
        )
    for estimate_id, estimate in factor_estimands.items():
        if estimate_id.startswith("prompt_model_interaction:"):
            append(
                estimate_id,
                "fixed_factor_interaction",
                "engage_difference_in_differences",
                estimate,
                manifest.practical_thresholds.engagement_rate_absolute,
            )
    return rows


def _provider_accounting_analysis(
    evidence: _CellEvidenceDocument,
    manifest: ConcurrentRobustnessManifest,
) -> dict[str, Any]:
    execution = manifest.dynamic_execution
    reserved_cost_usd: float | None = None
    if execution is not None:
        reserved_cost_usd = sum(
            cell.physical_attempt_count
            * execution.pricing_snapshot.maximum_attempt_cost(
                requested_model=cell.requested_model,
                output_token_ceiling=manifest.request_contract.output_token_ceiling,
            )
            for cell in evidence.cells
        )
    cell_rows: list[dict[str, Any]] = []
    for cell in evidence.cells:
        observed_models: Counter[str] = Counter()
        for row in cell.terminal_rows:
            observed_models.update(row.observed_model_counts)
        cell_rows.append(
            {
                "cell_id": cell.cell_id,
                "requested_model": cell.requested_model,
                "observed_model": cell.observed_model,
                "logical_judgments": cell.logical_judgment_count,
                "physical_attempts": cell.physical_attempt_count,
                "provider_responses": sum(row.provider_response_count for row in cell.terminal_rows),
                "successful_primary_decisions": sum(
                    row.successful_decision_count for row in cell.terminal_rows
                ),
                "provider_failures": sum(
                    row.terminal_status == "provider_failed" for row in cell.terminal_rows
                ),
                "observed_model_counts": dict(sorted(observed_models.items())),
            }
        )
    return {
        "schema_version": "concurrent-robustness-provider-accounting-v1",
        "logical_judgments": evidence.logical_judgment_count,
        "physical_attempts": evidence.physical_attempt_count,
        "external_request_invocations": evidence.external_request_invocations,
        "live_api_triggered": evidence.live_api_triggered,
        "reserved_cost_usd": None if reserved_cost_usd is None else _round_metric(reserved_cost_usd),
        "fee_ceiling_usd": manifest.request_caps.fee_ceiling_usd,
        "cells": cell_rows,
    }


class _RobustnessAnalyzer:
    """Private owner of paired Decisions, realized paths, and conditional summaries."""

    def __init__(
        self,
        *,
        manifest: ConcurrentRobustnessManifest,
        evidence: _CellEvidenceDocument,
        manifest_sha256: str,
    ) -> None:
        self.manifest = manifest
        self.evidence = evidence
        self.manifest_sha256 = manifest_sha256

    def analyze(self) -> tuple[dict[str, Any], dict[str, Any]]:
        direct, exact_rows = _shared_seed_direct_analysis(self.evidence, self.manifest)
        intervals, bootstrap = _bootstrap_intervals(exact_rows)
        fixed_factors, factor_estimands = _fixed_factor_summary(exact_rows, intervals)
        realized_paths = _realized_path_analysis(self.evidence, self.manifest)
        practical_rows = _practical_threshold_rows(
            direct=direct,
            realized_paths=realized_paths,
            factor_estimands=factor_estimands,
            manifest=self.manifest,
        )
        provider_accounting = _provider_accounting_analysis(self.evidence, self.manifest)
        analysis = {
            "schema_version": "concurrent-prompt-model-robustness-analysis-v1",
            "manifest_sha256": self.manifest_sha256,
            "cell_evidence_schema_version": self.evidence.schema_version,
            "cell_count": len(self.evidence.cells),
            "primary_outcome": "binary_engage",
            "secondary_outcomes": [
                "action_transition",
                "decision_probability",
                "decision_confidence",
                "engage_disagreement",
                "realized_path_engagement",
                "audience_overlap",
                "campaign_positive_user_growth",
            ],
            "shared_seed_direct_decisions": direct,
            "fixed_factor_summaries": fixed_factors,
            "bootstrap": bootstrap,
            "provider_accounting": provider_accounting,
            "realized_paths": realized_paths,
            "practical_thresholds": {
                "engage_or_rate_absolute": self.manifest.practical_thresholds.engagement_rate_absolute,
                "mean_probability_absolute": self.manifest.practical_thresholds.decision_probability_absolute,
                "audience_jaccard_distance": self.manifest.practical_thresholds.audience_jaccard_distance,
                "terminal_positive_users_manifest_count": (
                    self.manifest.practical_thresholds.terminal_unique_positive_user_count
                ),
                "terminal_positive_users_production_count": 50,
                "below_threshold_label": "small_observed_difference",
            },
            "practical_threshold_classifications": practical_rows,
            "conditional_scope": "fixed_sample_fixed_graph_one_realized_path_per_cell",
        }
        claims = {
            "schema_version": "concurrent-robustness-claim-audit-v1",
            "status": "passed",
            "statements": list(self.evidence.claim_statements),
            "checked_statement_count": len(self.evidence.claim_statements),
            "below_threshold_label": "small_observed_difference",
            "conditional_intervals": True,
            "fixed_sample": True,
            "fixed_graph": True,
            "one_realized_path_per_cell": True,
            "ground_truth_used": False,
            "causal_claims_allowed": False,
            "population_robust_claims_allowed": False,
            "statistical_equivalence_claims_allowed": False,
            "model_randomness_resolved": False,
        }
        _guard_claim_statements(self.evidence.claim_statements)
        return analysis, claims


def _closed_study_payloads(
    *,
    workspace_path: Path,
    study_root: Path,
    manifest: ConcurrentRobustnessManifest,
    manifest_sha256: str,
    evidence: _CellEvidenceDocument,
    registry: _CellWorkspaceRegistry,
    analysis: Mapping[str, Any],
    claims: Mapping[str, Any],
) -> dict[str, bytes]:
    source_payloads = {
        _WORKSPACE_MANIFEST: (workspace_path / _WORKSPACE_MANIFEST).read_bytes(),
        _WORKSPACE_ANALYSIS: (workspace_path / _WORKSPACE_ANALYSIS).read_bytes(),
        _CELL_EVIDENCE: (workspace_path / _CELL_EVIDENCE).read_bytes(),
        _STUDY_ROOT_ANALYSIS: _json_bytes(analysis),
        _STUDY_ROOT_CLAIMS: _json_bytes(claims),
    }
    source_hashes = {relative_path: _sha256_bytes(payload) for relative_path, payload in source_payloads.items()}
    validation = {
        "schema_version": "concurrent-robustness-complete-validation-v1",
        "status": ConcurrentRobustnessStudyStatus.COMPLETE.value,
        "manifest_sha256": manifest_sha256,
        "source_manifest_sha256": manifest.source.manifest_sha256,
        "source_workspace_root_sha256": _output_root_sha256(workspace_path),
        "cell_registry_sha256": _sha256_file(workspace_path / _CELL_REGISTRY),
        "cell_evidence_sha256": registry.cell_evidence_sha256,
        "analysis_sha256": source_hashes[_STUDY_ROOT_ANALYSIS],
        "claim_audit_sha256": source_hashes[_STUDY_ROOT_CLAIMS],
        "counts": {
            "production_contract_logical_judgments": _PRODUCTION_ROBUSTNESS_LOGICAL_JUDGMENTS,
            "manifest_logical_judgments": manifest.request_caps.logical_judgment_cap,
            "realized_logical_judgments": evidence.logical_judgment_count,
            "realized_physical_attempts": evidence.physical_attempt_count,
            "external_request_invocations": evidence.external_request_invocations,
            "reserved_cost_usd": analysis["provider_accounting"]["reserved_cost_usd"],
            "fee_ceiling_usd": manifest.request_caps.fee_ceiling_usd,
            "cell_count": len(evidence.cells),
            "message_count": len(manifest.message_ids),
            "terminal_row_count": sum(len(cell.terminal_rows) for cell in evidence.cells),
        },
        "checks": {
            "exact_16_cell_cross_product": True,
            "canonical_cell_order": True,
            "all_terminal_rows_present": True,
            "prompt_hashes_match_manifest": True,
            "requested_models_match_manifest": True,
            "observed_models_single_identity_per_requested_model": True,
            "request_contract_matches_manifest": True,
            "source_identity_matches_manifest": True,
            "logical_physical_accounting_closed": True,
            "next_attempt_caps_enforced": True,
            "reserved_cost_within_fee_ceiling": (
                analysis["provider_accounting"]["reserved_cost_usd"] is None
                or float(analysis["provider_accounting"]["reserved_cost_usd"])
                <= manifest.request_caps.fee_ceiling_usd + 1e-12
            ),
            "external_request_profile_matches_manifest": (
                manifest.dynamic_execution is None
                or (
                    manifest.dynamic_execution.profile == "deterministic_validation"
                    and evidence.external_request_invocations == 0
                    and evidence.live_api_triggered is False
                )
                or (
                    manifest.dynamic_execution.profile == "formal_live"
                    and evidence.external_request_invocations == evidence.physical_attempt_count
                    and evidence.live_api_triggered is True
                )
            ),
            "provider_failures_in_exposure_denominator": True,
            "provider_failures_excluded_from_decision_denominator": True,
            "probability_uses_successful_decisions_only": True,
            "shared_seed_direct_panel_is_strictly_paired": True,
            "user_blocked_bootstrap_deterministic": True,
            "claims_guarded": True,
            "source_workspace_unchanged": True,
        },
        "conditional_scope": "fixed_sample_fixed_graph_one_realized_path_per_cell",
        "production_deploy_eligible": False,
        "report_candidate": None,
    }
    validation_payload = _json_bytes(validation)
    source_payloads[_WORKSPACE_VALIDATION] = validation_payload
    artifact_hashes = {
        relative_path: _sha256_bytes(payload) for relative_path, payload in source_payloads.items()
    }
    root_identity_sha256 = _sha256_bytes(_json_bytes(artifact_hashes))
    root_manifest = {
        "schema_version": "concurrent-robustness-study-artifact-manifest-v1",
        "root_type": "immutable_closed_study",
        "status": ConcurrentRobustnessStudyStatus.COMPLETE.value,
        "study_root": str(study_root),
        "root_identity_sha256": root_identity_sha256,
        "manifest_sha256": manifest_sha256,
        "source_manifest_sha256": manifest.source.manifest_sha256,
        "source_workspace_root_sha256": _output_root_sha256(workspace_path),
        "cell_registry_sha256": _sha256_file(workspace_path / _CELL_REGISTRY),
        "artifacts": sorted(artifact_hashes),
        "sha256": dict(sorted(artifact_hashes.items())),
        "counts": {
            "cell_count": len(evidence.cells),
            "logical_judgment_count": evidence.logical_judgment_count,
            "physical_attempt_count": evidence.physical_attempt_count,
        },
        "production_deploy_eligible": False,
        "report_candidate": None,
    }
    source_payloads[_STUDY_ROOT_MANIFEST] = _json_bytes(root_manifest)
    return source_payloads


def _validate_study_root(
    root_path: Path,
    *,
    expected_payloads: Mapping[str, bytes],
) -> None:
    try:
        if root_path.is_symlink() or not root_path.is_dir():
            raise ValueError("closed study root is not a real directory")
        actual_files: set[str] = set()
        for path in root_path.iterdir():
            if path.is_symlink() or not path.is_file():
                raise ValueError("closed study root contains a non-regular artifact")
            actual_files.add(path.name)
        if actual_files != _STUDY_ROOT_FILES or set(expected_payloads) != _STUDY_ROOT_FILES:
            raise ValueError("closed study root has missing or extra artifacts")
        for relative_path, expected_payload in expected_payloads.items():
            if (root_path / relative_path).read_bytes() != expected_payload:
                raise ValueError(f"closed study artifact is not reproducible: {relative_path}")
        root_manifest = _read_json_object(root_path / _STUDY_ROOT_MANIFEST)
        if root_manifest.get("schema_version") != "concurrent-robustness-study-artifact-manifest-v1":
            raise ValueError("closed study manifest schema is unsupported")
        if root_manifest.get("root_type") != "immutable_closed_study":
            raise ValueError("closed study root type is invalid")
        artifacts = _string_list(root_manifest.get("artifacts"), "closed study artifacts")
        hashes = _mapping(root_manifest.get("sha256"), "closed study hashes")
        if set(artifacts) != _STUDY_ROOT_FILES - {_STUDY_ROOT_MANIFEST} or set(hashes) != set(artifacts):
            raise ValueError("closed study manifest artifact inventory is incomplete")
        for relative_path in artifacts:
            expected_hash = str(hashes[relative_path])
            if not _SHA256_PATTERN.fullmatch(expected_hash):
                raise ValueError("closed study manifest contains an invalid artifact hash")
            if _sha256_file(root_path / relative_path) != expected_hash:
                raise ValueError("closed study artifact hash mismatch")
        if root_manifest.get("root_identity_sha256") != _sha256_bytes(
            _json_bytes(dict(sorted((path, str(hashes[path])) for path in artifacts)))
        ):
            raise ValueError("closed study root identity is crossed")
        validation = _read_json_object(root_path / _WORKSPACE_VALIDATION)
        if validation.get("schema_version") != "concurrent-robustness-complete-validation-v1":
            raise ValueError("closed study validation schema is unsupported")
        if validation.get("status") != ConcurrentRobustnessStudyStatus.COMPLETE.value:
            raise ValueError("closed study validation is not complete")
        if validation.get("production_deploy_eligible") is not False:
            raise ValueError("closed study fixture cannot be deploy eligible")
        if validation.get("report_candidate") is not None:
            raise ValueError("analysis closure cannot expose a report candidate")
    except ConcurrentRobustnessError:
        raise
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ConcurrentRobustnessError(
            ConcurrentRobustnessErrorCode.WORKSPACE_CORRUPT,
            "immutable closed study root failed artifact and hash validation",
        ) from exc


def _close_study_root(
    workspace_path: Path,
    *,
    manifest: ConcurrentRobustnessManifest,
    manifest_sha256: str,
    evidence: _CellEvidenceDocument,
    registry: _CellWorkspaceRegistry,
    analysis: Mapping[str, Any],
    claims: Mapping[str, Any],
) -> Path:
    root_path = workspace_path.with_name(f"{workspace_path.name}{_STUDY_ROOT_SUFFIX}")
    expected_payloads = _closed_study_payloads(
        workspace_path=workspace_path,
        study_root=root_path,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        evidence=evidence,
        registry=registry,
        analysis=analysis,
        claims=claims,
    )
    if root_path.exists() or root_path.is_symlink():
        _validate_study_root(root_path, expected_payloads=expected_payloads)
        return root_path
    staging_path = Path(
        tempfile.mkdtemp(
            prefix=f".{root_path.name}.{manifest.output_identity}.",
            suffix=".staging",
            dir=root_path.parent,
        )
    )
    try:
        for relative_path, payload in expected_payloads.items():
            (staging_path / relative_path).write_bytes(payload)
        _validate_study_root(staging_path, expected_payloads=expected_payloads)
        if root_path.exists() or root_path.is_symlink():
            raise ConcurrentRobustnessError(
                ConcurrentRobustnessErrorCode.WORKSPACE_CONFLICT,
                "closed study root appeared during atomic finalization",
            )
        os.replace(staging_path, root_path)
    except Exception:
        if staging_path.exists():
            shutil.rmtree(staging_path, ignore_errors=True)
        raise
    _validate_study_root(root_path, expected_payloads=expected_payloads)
    return root_path


_DYNAMIC_ROOT_SUFFIX = ".prompt-model-operational"
_DYNAMIC_IDENTITY = "execution_identity.json"
_DYNAMIC_STATUS = "execution_status.json"
_DYNAMIC_IDENTITY_SCHEMA = "concurrent-robustness-dynamic-identity-v1"
_DYNAMIC_STATUS_SCHEMA = "concurrent-robustness-dynamic-status-v1"
_DYNAMIC_REPORT_SUFFIX = ".report-candidate"


class _DeterministicValidationProviderClient:
    """In-memory response script accepted by the no-network validation profile."""

    __slots__ = ("_position", "_responses", "calls")

    def __init__(self, responses: Sequence[ProviderResponseEnvelope | Exception]) -> None:
        if not responses or any(
            not isinstance(response, (ProviderResponseEnvelope, Exception))
            for response in responses
        ):
            raise ValueError("validation Provider script requires typed responses or exceptions")
        self._responses = tuple(responses)
        self._position = 0
        self.calls: list[dict[str, object]] = []

    def create_response(
        self,
        messages: list[dict[str, str]],
        model: str,
        *,
        reasoning_effort: str,
        output_token_ceiling: int,
    ) -> ProviderResponseEnvelope:
        del messages
        if self._position >= len(self._responses):
            raise AssertionError("validation Provider response script is exhausted")
        response = self._responses[self._position]
        self._position += 1
        self.calls.append(
            {
                "model": model,
                "reasoning_effort": reasoning_effort,
                "output_token_ceiling": output_token_ceiling,
            }
        )
        if isinstance(response, Exception):
            raise response
        return response


@dataclass(frozen=True)
class _DynamicPreflight:
    adapters: tuple[tuple[_PromptModelCell, OpenAICompatibleDecisionAdapter], ...]
    external_request_baselines: dict[str, int]


@dataclass(frozen=True)
class _DynamicProgress:
    logical_judgments: int
    physical_attempts: int
    reserved_cost_usd: float
    inflight_unknown: bool


@dataclass(frozen=True)
class _DynamicRunOutcome:
    evidence: _CellEvidenceDocument | None
    logical_judgments: int
    physical_attempts: int


class _DynamicCapExhausted(RuntimeError):
    pass


def _dynamic_adapter_error(message: str, *, cause: Exception | None = None) -> ConcurrentRobustnessError:
    error = ConcurrentRobustnessError(ConcurrentRobustnessErrorCode.UNSUPPORTED_ADAPTERS, message)
    if cause is not None:
        error.__cause__ = cause
    return error


def _request_contract_matches_cell(
    actual: ProviderRequestContract,
    *,
    expected: _RequestContract,
    cell: _PromptModelCell,
) -> bool:
    return (
        actual.schema_version == expected.schema_version
        and actual.requested_model == cell.requested_model
        and actual.prompt_version == cell.prompt_version
        and actual.prompt_canonical_hash == cell.prompt_canonical_hash
        and actual.wire_api == expected.wire_api
        and actual.reasoning_effort == expected.reasoning_effort
        and actual.output_token_ceiling == expected.output_token_ceiling
        and math.isclose(actual.timeout_seconds, expected.timeout_seconds, rel_tol=0.0, abs_tol=1e-12)
        and actual.max_retries == expected.max_retries
        and math.isclose(
            actual.retry_backoff_seconds,
            expected.retry_backoff_seconds,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        and actual.structured_output_schema_version == expected.structured_output_schema_version
        and actual.structured_output_schema_hash == expected.structured_output_schema_hash
        and actual.omitted_parameters == expected.omitted_parameters
    )


def _preflight_dynamic_adapters(
    manifest: ConcurrentRobustnessManifest,
    adapters_by_cell: Mapping[str, LLMDecisionAdapter],
) -> _DynamicPreflight:
    execution = manifest.dynamic_execution
    if execution is None:
        raise _dynamic_adapter_error("dynamic execution requires an explicit authorization and qualification contract")
    expected_keys = tuple(cell.cell_id for cell in manifest.prompt_model_cells)
    try:
        actual_keys = tuple(adapters_by_cell.keys())
    except Exception as exc:
        raise _dynamic_adapter_error("dynamic Adapter map cannot be enumerated safely", cause=exc) from exc
    if len(actual_keys) != len(set(actual_keys)) or set(actual_keys) != set(expected_keys) or len(actual_keys) != 16:
        missing = sorted(set(expected_keys) - set(actual_keys))
        extra = sorted(set(actual_keys) - set(expected_keys))
        raise _dynamic_adapter_error(
            "dynamic Adapter map must contain exactly the 16 canonical cell keys "
            f"(missing={missing}, extra={extra})"
        )

    adapters: list[tuple[_PromptModelCell, OpenAICompatibleDecisionAdapter]] = []
    adapter_ids: set[int] = set()
    injected_client_ids: set[int] = set()
    baselines: dict[str, int] = {}
    for cell in manifest.prompt_model_cells:
        candidate = adapters_by_cell[cell.cell_id]
        if type(candidate) is not OpenAICompatibleDecisionAdapter:
            raise _dynamic_adapter_error(
                f"cell {cell.cell_id} must use the qualified OpenAICompatibleDecisionAdapter identity"
            )
        adapter = candidate
        if id(adapter) in adapter_ids:
            raise _dynamic_adapter_error("each Prompt-Model cell requires an independent fresh Adapter")
        adapter_ids.add(id(adapter))
        if getattr(adapter, "wrapped", None) is not None or getattr(adapter, "cache", None) is not None:
            raise _dynamic_adapter_error("dynamic robustness cells forbid cached or wrapped Decision Adapters")
        request_contract = adapter.request_contract
        if not _request_contract_matches_cell(request_contract, expected=manifest.request_contract, cell=cell):
            raise _dynamic_adapter_error(f"cell {cell.cell_id} request, Prompt, or model contract is crossed")
        if adapter.config.provider != execution.provider or adapter.config.fail_closed_action.value != "raise":
            raise _dynamic_adapter_error(f"cell {cell.cell_id} provider or fail-closed policy is crossed")
        if not adapter.config.enabled:
            raise _dynamic_adapter_error(f"cell {cell.cell_id} Adapter must be explicitly enabled")
        if adapter.request_invocations != 0 or adapter.external_request_invocations != 0:
            raise _dynamic_adapter_error(f"cell {cell.cell_id} Adapter is not a fresh decision store")
        accounting = adapter.provider_accounting
        if (
            accounting.provider_response_count != 0
            or accounting.successful_decision_count != 0
            or accounting.observed_model_counts
            or accounting.observed_model_missing_response_count != 0
            or accounting.observed_model_malformed_response_count != 0
        ):
            raise _dynamic_adapter_error(f"cell {cell.cell_id} Adapter contains prior Provider evidence")

        if execution.profile == "deterministic_validation":
            client = adapter.client
            if type(client) is not _DeterministicValidationProviderClient or adapter.config.require_live_env:
                raise _dynamic_adapter_error(
                    f"cell {cell.cell_id} validation profile requires the closed in-memory mock client"
                )
            if id(client) in injected_client_ids:
                raise _dynamic_adapter_error("validation cells require independent injected mock clients")
            injected_client_ids.add(id(client))
        elif execution.adapter_identity == CONCURRENT_ROBUSTNESS_SUBSCRIPTION_ADAPTER_IDENTITY:
            if (
                type(adapter.client) is not PiSubscriptionProviderClient
                or not adapter.config.require_live_env
                or not adapter.client.ready
            ):
                raise _dynamic_adapter_error(
                    f"cell {cell.cell_id} Formal subscription profile requires the ready Pi OAuth client"
                )
        elif adapter.client is not None or not adapter.config.require_live_env:
            raise _dynamic_adapter_error(
                f"cell {cell.cell_id} Formal profile requires the live-client Adapter identity"
            )
        baselines[cell.cell_id] = adapter.external_request_invocations
        adapters.append((cell, adapter))
    return _DynamicPreflight(adapters=tuple(adapters), external_request_baselines=baselines)


def _dynamic_runtime_config(closure: ConcurrentMessageArtifactClosure) -> ConcurrentMessageExperimentConfig:
    config = closure.source_evidence.config_snapshot
    try:
        return ConcurrentMessageExperimentConfig(
            dataset_dir=Path(str(config["dataset_dir"])),
            sample_size=int(config["sample_size"]),
            horizon=int(config["horizon"]),
            delivery_capacity=int(config["delivery_capacity"]),
            random_seed=int(config["random_seed"]),
            configuration_profile=cast(
                Literal["production", "validation"],
                config["configuration_profile"],
            ),
            sample_holdout_video_id=str(config["sample_holdout_video_id"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ConcurrentRobustnessError(
            ConcurrentRobustnessErrorCode.INVALID_SOURCE,
            "dynamic execution cannot reconstruct the frozen Concurrent runtime configuration",
        ) from exc


def _dynamic_root(output_path: Path) -> Path:
    return output_path.parent / f".{output_path.name}{_DYNAMIC_ROOT_SUFFIX}"


def _dynamic_report_destination(output_path: Path) -> Path:
    return output_path.with_name(f"{output_path.name}{_DYNAMIC_REPORT_SUFFIX}")


def _cell_output_target(root: Path, cell_index: int) -> Path:
    return root / f"cell-{cell_index:02d}" / "primary-only"


def _dynamic_identity_payload(
    *,
    manifest: ConcurrentRobustnessManifest,
    manifest_sha256: str,
    output_path: Path,
) -> dict[str, object]:
    execution = manifest.dynamic_execution
    assert execution is not None
    return {
        "schema_version": _DYNAMIC_IDENTITY_SCHEMA,
        "workspace_type": "private_resumable",
        "manifest_sha256": manifest_sha256,
        "source_manifest_sha256": manifest.source.manifest_sha256,
        "output_identity": manifest.output_identity,
        "output_root": str(output_path),
        "operational_root": str(_dynamic_root(output_path)),
        "report_candidate": str(_dynamic_report_destination(output_path)),
        "dynamic_execution": execution.model_dump(mode="json"),
        "cell_outputs": [
            {
                "cell_index": index,
                "cell_id": cell.cell_id,
                "output_target": str(_cell_output_target(_dynamic_root(output_path), index)),
            }
            for index, cell in enumerate(manifest.prompt_model_cells)
        ],
        "production_deploy_eligible": False,
    }


def _atomic_write_dynamic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
        handle.write(_json_bytes(dict(payload)))
        handle.flush()
        os.fsync(handle.fileno())
        temporary_path = Path(handle.name)
    os.replace(temporary_path, path)


def _dynamic_status_payload(
    *,
    manifest_sha256: str,
    lifecycle: str,
    logical_judgments: int,
    physical_attempts: int,
    reserved_logical_judgments: int,
    reserved_physical_attempts: int,
    reserved_cost_usd: float,
    last_cell_id: str | None,
    last_pair_id: str | None,
) -> dict[str, object]:
    return {
        "schema_version": _DYNAMIC_STATUS_SCHEMA,
        "lifecycle": lifecycle,
        "manifest_sha256": manifest_sha256,
        "logical_judgments": logical_judgments,
        "physical_attempts": physical_attempts,
        "reserved_logical_judgments": reserved_logical_judgments,
        "reserved_physical_attempts": reserved_physical_attempts,
        "reserved_cost_usd": round(reserved_cost_usd, 12),
        "last_cell_id": last_cell_id,
        "last_pair_id": last_pair_id,
        "production_deploy_eligible": False,
    }


def _open_dynamic_root(
    *,
    manifest: ConcurrentRobustnessManifest,
    manifest_sha256: str,
    output_path: Path,
    source_path: Path,
) -> Path:
    root = _dynamic_root(output_path)
    _validate_study_paths(source_path, root)
    expected_identity = _json_bytes(
        _dynamic_identity_payload(
            manifest=manifest,
            manifest_sha256=manifest_sha256,
            output_path=output_path,
        )
    )
    if root.exists():
        try:
            if root.is_symlink() or not root.is_dir():
                raise ValueError("dynamic root is not a real directory")
            entries = list(root.iterdir())
            allowed_cell_dirs = {f"cell-{index:02d}" for index in range(16)}
            for entry in entries:
                if entry.is_symlink():
                    raise ValueError("dynamic root contains a symlink")
                if entry.name in {_DYNAMIC_IDENTITY, _DYNAMIC_STATUS}:
                    if not entry.is_file():
                        raise ValueError("dynamic root metadata is not a regular file")
                elif entry.name in allowed_cell_dirs:
                    if not entry.is_dir():
                        raise ValueError("dynamic cell scope is not a directory")
                else:
                    raise ValueError("dynamic root contains an unexpected entry")
            if (root / _DYNAMIC_IDENTITY).read_bytes() != expected_identity:
                raise ValueError("dynamic execution identity is crossed")
            status = _read_json_object(root / _DYNAMIC_STATUS)
            if status.get("schema_version") != _DYNAMIC_STATUS_SCHEMA:
                raise ValueError("dynamic execution status schema is unsupported")
            if status.get("manifest_sha256") != manifest_sha256:
                raise ValueError("dynamic execution status manifest is crossed")
            return root
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ConcurrentRobustnessError(
                ConcurrentRobustnessErrorCode.WORKSPACE_CORRUPT,
                "dynamic Prompt-Model workspace identity or state is corrupt",
            ) from exc

    root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{root.name}.{manifest.output_identity}.",
            suffix=".staging",
            dir=root.parent,
        )
    )
    try:
        (staging / _DYNAMIC_IDENTITY).write_bytes(expected_identity)
        (staging / _DYNAMIC_STATUS).write_bytes(
            _json_bytes(
                _dynamic_status_payload(
                    manifest_sha256=manifest_sha256,
                    lifecycle="initialized",
                    logical_judgments=0,
                    physical_attempts=0,
                    reserved_logical_judgments=0,
                    reserved_physical_attempts=0,
                    reserved_cost_usd=0.0,
                    last_cell_id=None,
                    last_pair_id=None,
                )
            )
        )
        if root.exists():
            raise ConcurrentRobustnessError(
                ConcurrentRobustnessErrorCode.WORKSPACE_CONFLICT,
                "dynamic Prompt-Model workspace appeared during atomic creation",
            )
        os.replace(staging, root)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise
    return root


def _dynamic_progress(
    root: Path,
    *,
    manifest: ConcurrentRobustnessManifest,
    manifest_sha256: str,
) -> _DynamicProgress:
    execution = manifest.dynamic_execution
    assert execution is not None
    logical_judgments = 0
    physical_attempts = 0
    reserved_cost_usd = 0.0
    inflight_unknown = False
    for cell_index, cell in enumerate(manifest.prompt_model_cells):
        output_target = _cell_output_target(root, cell_index)
        workspace = derive_concurrent_execution_workspace(output_target)
        cell_scope = output_target.parent
        if not cell_scope.exists():
            continue
        if cell_scope.is_symlink() or not cell_scope.is_dir() or not workspace.is_dir():
            raise ValueError(f"dynamic cell {cell.cell_id} workspace is incomplete")
        replay = ConcurrentExecutionJournal.open_existing(workspace).replay()
        identity = _mapping(replay.get("identity"), "dynamic cell journal identity")
        expected_execution_identity = _cell_execution_identity(
            manifest=manifest,
            manifest_sha256=manifest_sha256,
            cell_index=cell_index,
            cell=cell,
        )
        if identity.get("execution_contract") != expected_execution_identity:
            raise ValueError(f"dynamic cell {cell.cell_id} journal identity is crossed")
        status = _mapping(replay.get("status"), "dynamic cell journal status")
        inflight_unknown = inflight_unknown or bool(status.get("inflight_unknown"))
        records = _sequence(replay.get("records"), "dynamic cell journal records")
        cell_physical = 0
        for record_raw in records:
            record = _mapping(record_raw, "dynamic cell journal record")
            if record.get("record_type") != "event" or record.get("event_type") != "variant_terminal":
                continue
            payload = _mapping(record.get("payload"), "dynamic cell terminal payload")
            evidence = _mapping(payload.get("variant_evidence"), "dynamic cell terminal evidence")
            logical_judgments += 1
            requests = _as_int(evidence.get("request_invocations"), "dynamic terminal request invocations")
            physical_attempts += requests
            cell_physical += requests
        attempt_cost = execution.pricing_snapshot.maximum_attempt_cost(
            requested_model=cell.requested_model,
            output_token_ceiling=manifest.request_contract.output_token_ceiling,
        )
        reserved_cost_usd += cell_physical * attempt_cost
    return _DynamicProgress(
        logical_judgments=logical_judgments,
        physical_attempts=physical_attempts,
        reserved_cost_usd=reserved_cost_usd,
        inflight_unknown=inflight_unknown,
    )


def _validate_completed_dynamic_root(
    *,
    manifest: ConcurrentRobustnessManifest,
    manifest_sha256: str,
    output_path: Path,
    source_path: Path,
    evidence: _CellEvidenceDocument,
) -> None:
    root = _dynamic_root(output_path)
    if not root.is_dir():
        raise ConcurrentRobustnessError(
            ConcurrentRobustnessErrorCode.WORKSPACE_CORRUPT,
            "completed dynamic evidence is missing its operational lineage",
        )
    root = _open_dynamic_root(
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        output_path=output_path,
        source_path=source_path,
    )
    try:
        progress = _dynamic_progress(root, manifest=manifest, manifest_sha256=manifest_sha256)
        status = _read_json_object(root / _DYNAMIC_STATUS)
        if status.get("lifecycle") != "cells_complete":
            raise ValueError("completed dynamic operational status is not closed")
        if (
            progress.inflight_unknown
            or progress.logical_judgments != evidence.logical_judgment_count
            or progress.physical_attempts != evidence.physical_attempt_count
            or _as_int(status.get("logical_judgments"), "dynamic status logical count")
            != evidence.logical_judgment_count
            or _as_int(status.get("physical_attempts"), "dynamic status physical count")
            != evidence.physical_attempt_count
        ):
            raise ValueError("completed dynamic operational accounting is crossed")
    except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ConcurrentRobustnessError(
            ConcurrentRobustnessErrorCode.WORKSPACE_CORRUPT,
            "completed dynamic cell journals failed immutable replay",
        ) from exc


def _cell_execution_identity(
    *,
    manifest: ConcurrentRobustnessManifest,
    manifest_sha256: str,
    cell_index: int,
    cell: _PromptModelCell,
) -> dict[str, object]:
    execution = manifest.dynamic_execution
    assert execution is not None
    payload = {
        "schema_version": "concurrent-robustness-cell-execution-identity-v1",
        "manifest_sha256": manifest_sha256,
        "source_manifest_sha256": manifest.source.manifest_sha256,
        "sample_identity": manifest.sample.sample_identity,
        "message_snapshot_sha256": manifest.message_snapshot_sha256,
        "cell_index": cell_index,
        "cell": cell.model_dump(mode="json"),
        "request_contract_sha256": _sha256_bytes(_json_bytes(manifest.request_contract.model_dump(mode="json"))),
        "approval_artifact_sha256": execution.authorization.artifact_sha256,
        "pricing_snapshot_sha256": execution.pricing_snapshot.snapshot_sha256,
        "decision_store_policy": manifest.request_contract.decision_store_policy,
        "production_deploy_eligible": False,
    }
    normalized = json.loads(_json_bytes(payload))
    if not isinstance(normalized, dict):
        raise TypeError("dynamic cell execution identity must normalize to an object")
    return normalized


class _DynamicBudgetGuard:
    def __init__(
        self,
        *,
        manifest: ConcurrentRobustnessManifest,
        manifest_sha256: str,
        root: Path,
        progress: _DynamicProgress,
    ) -> None:
        self.manifest = manifest
        self.manifest_sha256 = manifest_sha256
        self.root = root
        self.logical_judgments = progress.logical_judgments
        self.physical_attempts = progress.physical_attempts
        self.reserved_cost_usd = progress.reserved_cost_usd
        self.cell: _PromptModelCell | None = None
        self.pending_pair_id: str | None = None
        self.pending_attempt_cost = 0.0

    def select_cell(self, cell: _PromptModelCell) -> None:
        self.cell = cell
        execution = self.manifest.dynamic_execution
        assert execution is not None
        self.pending_attempt_cost = execution.pricing_snapshot.maximum_attempt_cost(
            requested_model=cell.requested_model,
            output_token_ceiling=self.manifest.request_contract.output_token_ceiling,
        )

    def before(self, judgment: Mapping[str, object]) -> None:
        if self.cell is None or self.pending_pair_id is not None:
            raise RuntimeError("dynamic budget guard lifecycle is invalid")
        pair_id = str(judgment.get("pair_id", ""))
        max_attempts = self.manifest.request_contract.max_retries + 1
        next_logical = self.logical_judgments + 1
        next_reserved_physical = self.physical_attempts + max_attempts
        next_reserved_cost = self.reserved_cost_usd + max_attempts * self.pending_attempt_cost
        caps = self.manifest.request_caps
        if (
            next_logical > caps.logical_judgment_cap
            or next_reserved_physical > caps.physical_attempt_cap
            or next_reserved_cost > caps.fee_ceiling_usd + 1e-12
        ):
            _atomic_write_dynamic_json(
                self.root / _DYNAMIC_STATUS,
                _dynamic_status_payload(
                    manifest_sha256=self.manifest_sha256,
                    lifecycle="cap_exhausted",
                    logical_judgments=self.logical_judgments,
                    physical_attempts=self.physical_attempts,
                    reserved_logical_judgments=next_logical,
                    reserved_physical_attempts=next_reserved_physical,
                    reserved_cost_usd=next_reserved_cost,
                    last_cell_id=self.cell.cell_id,
                    last_pair_id=pair_id,
                ),
            )
            raise _DynamicCapExhausted("next logical or physical attempt would exceed a frozen cap")
        self.pending_pair_id = pair_id
        _atomic_write_dynamic_json(
            self.root / _DYNAMIC_STATUS,
            _dynamic_status_payload(
                manifest_sha256=self.manifest_sha256,
                lifecycle="attempt_reserved",
                logical_judgments=self.logical_judgments,
                physical_attempts=self.physical_attempts,
                reserved_logical_judgments=next_logical,
                reserved_physical_attempts=next_reserved_physical,
                reserved_cost_usd=next_reserved_cost,
                last_cell_id=self.cell.cell_id,
                last_pair_id=pair_id,
            ),
        )

    def after(self, evidence: Mapping[str, object]) -> None:
        if self.cell is None or self.pending_pair_id is None:
            raise RuntimeError("dynamic budget guard has no reserved judgment")
        if evidence.get("pair_id") != self.pending_pair_id:
            raise ValueError("dynamic budget guard terminal identity is crossed")
        request_invocations = _as_int(
            evidence.get("request_invocations"),
            "dynamic terminal request invocations",
        )
        if not 1 <= request_invocations <= self.manifest.request_contract.max_retries + 1:
            raise ValueError("dynamic terminal physical attempts exceed the retry contract")
        self.logical_judgments += 1
        self.physical_attempts += request_invocations
        self.reserved_cost_usd += request_invocations * self.pending_attempt_cost
        pair_id = self.pending_pair_id
        self.pending_pair_id = None
        _atomic_write_dynamic_json(
            self.root / _DYNAMIC_STATUS,
            _dynamic_status_payload(
                manifest_sha256=self.manifest_sha256,
                lifecycle="running",
                logical_judgments=self.logical_judgments,
                physical_attempts=self.physical_attempts,
                reserved_logical_judgments=self.logical_judgments,
                reserved_physical_attempts=self.physical_attempts,
                reserved_cost_usd=self.reserved_cost_usd,
                last_cell_id=self.cell.cell_id,
                last_pair_id=pair_id,
            ),
        )


def _validate_dynamic_terminal(
    evidence: Mapping[str, object],
    *,
    manifest: ConcurrentRobustnessManifest,
    cell: _PromptModelCell,
    adapter: OpenAICompatibleDecisionAdapter,
    external_baseline: int,
) -> None:
    requests = _as_int(evidence.get("request_invocations"), "terminal request invocations")
    responses = _as_int(evidence.get("provider_response_count"), "terminal Provider responses")
    successes = _as_int(evidence.get("successful_decision_count"), "terminal successful Decisions")
    if not requests >= responses >= successes or requests > manifest.request_contract.max_retries + 1:
        raise ValueError("dynamic terminal accounting violates invocations >= responses >= successful Decisions")
    observed_counts = _mapping(evidence.get("observed_model_counts"), "terminal observed-model counts")
    missing = _as_int(evidence.get("observed_model_missing_response_count"), "missing observed models")
    malformed = _as_int(evidence.get("observed_model_malformed_response_count"), "malformed observed models")
    if missing or malformed:
        raise ValueError("dynamic terminal responses require complete observed-model identity")
    execution = manifest.dynamic_execution
    assert execution is not None
    usage_complete = evidence.get("usage_complete") is True
    if responses > 0 and not usage_complete:
        raise ValueError("dynamic terminal responses require complete token usage accounting")
    input_usage = evidence.get("input_usage")
    output_usage = evidence.get("output_usage")
    if usage_complete and (
        not isinstance(input_usage, int)
        or not isinstance(output_usage, int)
        or input_usage > execution.pricing_snapshot.input_token_ceiling
        or output_usage > manifest.request_contract.output_token_ceiling
    ):
        raise ValueError("dynamic terminal token usage exceeds its frozen ceiling")
    required_observed_model = cell.required_observed_model
    if required_observed_model is None or set(str(model) for model in observed_counts) - {required_observed_model}:
        raise ValueError("dynamic terminal observed model drifted from qualification")
    external_delta = adapter.external_request_invocations - external_baseline
    if external_delta < 0:
        raise ValueError("dynamic Adapter external request counter moved backwards")
    if execution.profile == "deterministic_validation" and external_delta != 0:
        raise ValueError("validation Adapter triggered an external request")
    if execution.profile == "formal_live" and external_delta != adapter.request_invocations:
        raise ValueError("Formal Adapter physical and external request accounting diverged")


def _candidate_bool(value: object) -> bool:
    if value is True or value == "true" or value == "True" or value == 1 or value == "1":
        return True
    if value is False or value == "false" or value == "False" or value == 0 or value == "0" or value == "":
        return False
    raise ValueError("candidate boolean field is malformed")


def _batch_zero_candidate_fingerprint(rows: Sequence[Mapping[str, Any]]) -> tuple[tuple[object, ...], ...]:
    fingerprint: list[tuple[object, ...]] = []
    for row in rows:
        if _as_int(row.get("time_step"), "candidate time_step") != 0:
            continue
        fingerprint.append(
            (
                str(row.get("message_id", "")),
                str(row.get("user_id", "")),
                _candidate_bool(row.get("is_seed")),
                _candidate_bool(row.get("selected")),
                str(row.get("selection_reason", "")),
                _as_int(row.get("ranking_position"), "candidate ranking position"),
                str(row.get("base_network_relevance_full_precision", "")),
                _as_int(row.get("campaign_engaged_neighbor_count"), "candidate engaged-neighbor count"),
                str(row.get("campaign_engaged_neighbor_signal_full_precision", "")),
                str(row.get("raw_message_user_fit_full_precision", "")),
                str(row.get("normalized_message_user_fit_full_precision", "")),
                str(row.get("personalized_delivery_score_full_precision", "")),
            )
        )
    return tuple(fingerprint)


def _validate_dynamic_initial_state(
    result: _PrimaryOnlyConcurrentRuntimeResult,
    *,
    source_candidate_rows: Sequence[Mapping[str, Any]],
) -> None:
    if _batch_zero_candidate_fingerprint(result.candidate_rows) != _batch_zero_candidate_fingerprint(
        source_candidate_rows
    ):
        raise ValueError("dynamic cell initial sample, graph, messages, seeds, or baseline ranking is crossed")


def _json_mapping_cell(value: object, label: str) -> dict[str, int]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{label} is not valid JSON") from exc
    mapping = _mapping(value, label)
    return {str(key): _as_int(count, label) for key, count in mapping.items()}


def _required_terminal_field(row: Mapping[str, Any], field_name: str) -> object:
    if field_name not in row:
        raise ValueError(f"dynamic terminal row is missing persisted {field_name}")
    return row[field_name]


def _optional_bool_cell(value: object) -> bool | None:
    if value is None or value == "":
        return None
    if value is True or value == "true":
        return True
    if value is False or value == "false":
        return False
    raise ValueError("terminal engage Decision field is malformed")


def _optional_float_cell(value: object) -> float | None:
    if value is None or value == "":
        return None
    return _as_finite_float(value, "terminal numeric Decision field")


def _build_dynamic_cell_evidence(
    *,
    manifest: ConcurrentRobustnessManifest,
    manifest_sha256: str,
    cell_index: int,
    cell: _PromptModelCell,
    result: _PrimaryOnlyConcurrentRuntimeResult,
) -> _PromptModelCellEvidence:
    request_contract_sha256 = _sha256_bytes(_json_bytes(manifest.request_contract.model_dump(mode="json")))
    source_identity = _expected_cell_source_identity(manifest)
    primary_by_pair = {str(row["pair_id"]): row for row in result.primary_rows}
    terminal_rows: list[_CellTerminalRow] = []
    for row in sorted(result.terminal_rows, key=lambda item: _as_int(item["pair_schedule_position"], "pair position")):
        pair_id = str(row["pair_id"])
        primary_row = primary_by_pair.get(pair_id)
        if primary_row is None:
            raise ValueError("dynamic terminal row has no matching realized exposure")
        terminal_status_raw = str(row["terminal_status"])
        if terminal_status_raw not in {"succeeded", "provider_failed"}:
            raise ValueError("dynamic terminal status is unsupported")
        terminal_status = cast(Literal["succeeded", "provider_failed"], terminal_status_raw)
        prompt_version = str(_required_terminal_field(row, "prompt_version"))
        if prompt_version != cell.prompt_version:
            raise ValueError("dynamic terminal Prompt identity is crossed")
        action_raw = _required_terminal_field(row, "action")
        if action_raw is None or action_raw == "":
            action_value = None
        elif isinstance(action_raw, str) and action_raw in {"like", "comment", "share", "ignore"}:
            action_value = cast(Literal["like", "comment", "share", "ignore"], action_raw)
        else:
            raise ValueError("dynamic terminal action is unsupported")
        reason_value = str(row.get("reason", "")) or None
        failure_value = str(row.get("failure_type", "")) or None
        terminal_rows.append(
            _CellTerminalRow(
                terminal_row_id=str(row["terminal_row_id"]),
                pair_id=pair_id,
                pair_schedule_position=_as_int(row["pair_schedule_position"], "pair position"),
                time_step=_as_int(row["time_step"], "terminal time_step"),
                message_id=str(row["message_id"]),
                user_id=str(row["user_id"]),
                is_seed=_candidate_bool(primary_row["is_seed"]),
                selection_reason=str(primary_row["selection_reason"]),
                decision_variant="primary",
                prompt_version=prompt_version,
                prompt_canonical_hash=cell.prompt_canonical_hash,
                requested_model=cell.requested_model,
                request_contract_sha256=request_contract_sha256,
                terminal_status=terminal_status,
                engage=_optional_bool_cell(_required_terminal_field(row, "engage")),
                probability=_optional_float_cell(row.get("probability")),
                confidence=_optional_float_cell(row.get("confidence")),
                action=action_value,
                reason=reason_value,
                failure_type=failure_value,
                request_invocations=_as_int(row["request_invocations"], "terminal request invocations"),
                provider_response_count=_as_int(row["provider_response_count"], "terminal responses"),
                successful_decision_count=_as_int(row["successful_decision_count"], "terminal successes"),
                observed_model_counts=_json_mapping_cell(row["observed_model_counts"], "observed model counts"),
                observed_model_missing_response_count=_as_int(
                    row["observed_model_missing_response_count"],
                    "missing observed models",
                ),
                observed_model_malformed_response_count=_as_int(
                    row["observed_model_malformed_response_count"],
                    "malformed observed models",
                ),
            )
        )
    if cell.required_observed_model is None:
        raise ValueError("dynamic cell lacks a required observed-model identity")
    physical_attempts = sum(row.request_invocations for row in terminal_rows)
    return _PromptModelCellEvidence(
        cell_index=cell_index,
        cell_id=cell.cell_id,
        prompt_variant=cell.prompt_variant,
        prompt_version=cell.prompt_version,
        prompt_canonical_hash=cell.prompt_canonical_hash,
        requested_model=cell.requested_model,
        observed_model=cell.required_observed_model,
        source_identity_sha256=_cell_source_identity_sha256(
            manifest_sha256=manifest_sha256,
            source_identity=source_identity,
            cell_id=cell.cell_id,
        ),
        request_contract_sha256=request_contract_sha256,
        logical_judgment_count=len(terminal_rows),
        physical_attempt_count=physical_attempts,
        terminal_rows=tuple(terminal_rows),
        step_rows=tuple(
            _CellStepRow(
                time_step=_as_int(step["time_step"], "step time_step"),
                frozen_campaign_engaged_user_ids=tuple(
                    str(user_id) for user_id in _sequence(
                        step["frozen_campaign_engaged_user_ids"],
                        "frozen campaign users",
                    )
                ),
                deduplicated_committed_primary_positive_user_ids=tuple(
                    str(user_id) for user_id in _sequence(
                        step["deduplicated_committed_primary_positive_user_ids"],
                        "committed positive users",
                    )
                ),
                messages=tuple(
                    _CellStepMessage(
                        message_id=str(message["message_id"]),
                        selected_user_ids=tuple(
                            str(user_id) for user_id in _sequence(message["selected_user_ids"], "selected users")
                        ),
                        seed_user_ids=tuple(
                            str(user_id) for user_id in _sequence(message["seed_user_ids"], "seed users")
                        ),
                        primary_positive_user_ids=tuple(
                            str(user_id)
                            for user_id in _sequence(message["primary_positive_user_ids"], "positive users")
                        ),
                        primary_provider_failed_user_ids=tuple(
                            str(user_id)
                            for user_id in _sequence(
                                message["primary_provider_failed_user_ids"],
                                "Provider failed users",
                            )
                        ),
                    )
                    for message in _sequence(step["messages"], "step messages")
                    if isinstance(message, Mapping)
                ),
            )
            for step in result.step_rows
        ),
    )


def _publish_dynamic_evidence(
    output_path: Path,
    *,
    manifest: ConcurrentRobustnessManifest,
    manifest_sha256: str,
    evidence: _CellEvidenceDocument,
) -> tuple[_CellEvidenceDocument, _CellWorkspaceRegistry]:
    _validate_cell_evidence_contract(evidence, manifest=manifest, manifest_sha256=manifest_sha256)
    evidence_payload = _json_bytes(evidence.model_dump(mode="json"))
    evidence_sha256 = _sha256_bytes(evidence_payload)
    registry = _CellWorkspaceRegistry(
        schema_version="concurrent-robustness-cell-registry-v1",
        workspace_type="private_resumable",
        status="cells_complete",
        output_identity=manifest.output_identity,
        output_root_sha256=_output_root_sha256(output_path),
        manifest_sha256=manifest_sha256,
        source_manifest_sha256=manifest.source.manifest_sha256,
        base_workspace_sha256={name: _sha256_file(output_path / name) for name in sorted(_WORKSPACE_FILES)},
        cell_evidence="prompt_model_cell_evidence.json",
        cell_evidence_sha256=evidence_sha256,
        cell_inventory=tuple(
            _CellInventoryRow(
                cell_id=cell.cell_id,
                observed_model=cell.observed_model,
                source_identity_sha256=cell.source_identity_sha256,
                logical_judgment_count=cell.logical_judgment_count,
                physical_attempt_count=cell.physical_attempt_count,
                terminal_row_count=len(cell.terminal_rows),
            )
            for cell in evidence.cells
        ),
        logical_judgment_count=evidence.logical_judgment_count,
        physical_attempt_count=evidence.physical_attempt_count,
        external_request_invocations=evidence.external_request_invocations,
        production_deploy_eligible=False,
    )
    registry_payload = _json_bytes(registry.model_dump(mode="json"))
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{output_path.name}.cells.",
            suffix=".staging",
            dir=output_path.parent,
        )
    )
    try:
        staged_payloads = {
            _CELL_EVIDENCE: evidence_payload,
            _CELL_REGISTRY: registry_payload,
        }
        for name, payload in staged_payloads.items():
            (staging / name).write_bytes(payload)
        for name, payload in staged_payloads.items():
            destination = output_path / name
            if destination.exists():
                if destination.is_symlink() or destination.read_bytes() != payload:
                    raise ConcurrentRobustnessError(
                        ConcurrentRobustnessErrorCode.WORKSPACE_CORRUPT,
                        "existing dynamic cell artifact conflicts with completed evidence",
                    )
                continue
            os.replace(staging / name, destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    return _load_cell_workspace(
        output_path,
        output_path=output_path,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
    )


class _DynamicPromptModelProducer:
    def __init__(
        self,
        *,
        manifest: ConcurrentRobustnessManifest,
        manifest_sha256: str,
        output_path: Path,
        source_path: Path,
        closure: ConcurrentMessageArtifactClosure,
        preflight: _DynamicPreflight,
    ) -> None:
        self.manifest = manifest
        self.manifest_sha256 = manifest_sha256
        self.output_path = output_path
        self.source_path = source_path
        self.closure = closure
        self.preflight = preflight

    def run(self) -> _DynamicRunOutcome:
        execution = self.manifest.dynamic_execution
        assert execution is not None
        root = _open_dynamic_root(
            manifest=self.manifest,
            manifest_sha256=self.manifest_sha256,
            output_path=self.output_path,
            source_path=self.source_path,
        )
        try:
            progress = _dynamic_progress(
                root,
                manifest=self.manifest,
                manifest_sha256=self.manifest_sha256,
            )
        except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ConcurrentRobustnessError(
                ConcurrentRobustnessErrorCode.WORKSPACE_CORRUPT,
                "dynamic Prompt-Model journals failed durable replay",
            ) from exc
        persisted_status = _read_json_object(root / _DYNAMIC_STATUS)
        persisted_lifecycle = str(persisted_status.get("lifecycle", ""))
        persisted_counts = (
            _as_int(persisted_status.get("logical_judgments"), "dynamic status logical count"),
            _as_int(persisted_status.get("physical_attempts"), "dynamic status physical count"),
        )
        if persisted_lifecycle != "attempt_reserved" and persisted_counts != (
            progress.logical_judgments,
            progress.physical_attempts,
        ):
            raise ConcurrentRobustnessError(
                ConcurrentRobustnessErrorCode.WORKSPACE_CORRUPT,
                "dynamic execution status is crossed with durable cell journals",
            )
        if execution.profile == "formal_live" and progress.inflight_unknown:
            _atomic_write_dynamic_json(
                root / _DYNAMIC_STATUS,
                _dynamic_status_payload(
                    manifest_sha256=self.manifest_sha256,
                    lifecycle="inflight_reconciliation_required",
                    logical_judgments=progress.logical_judgments,
                    physical_attempts=progress.physical_attempts,
                    reserved_logical_judgments=progress.logical_judgments,
                    reserved_physical_attempts=progress.physical_attempts,
                    reserved_cost_usd=progress.reserved_cost_usd,
                    last_cell_id=None,
                    last_pair_id=None,
                ),
            )
            return _DynamicRunOutcome(
                evidence=None,
                logical_judgments=progress.logical_judgments,
                physical_attempts=progress.physical_attempts,
            )

        _atomic_write_dynamic_json(
            root / _DYNAMIC_STATUS,
            _dynamic_status_payload(
                manifest_sha256=self.manifest_sha256,
                lifecycle="running",
                logical_judgments=progress.logical_judgments,
                physical_attempts=progress.physical_attempts,
                reserved_logical_judgments=progress.logical_judgments,
                reserved_physical_attempts=progress.physical_attempts,
                reserved_cost_usd=progress.reserved_cost_usd,
                last_cell_id=None,
                last_pair_id=None,
            ),
        )
        config = _dynamic_runtime_config(self.closure)
        guard = _DynamicBudgetGuard(
            manifest=self.manifest,
            manifest_sha256=self.manifest_sha256,
            root=root,
            progress=progress,
        )
        cells: list[_PromptModelCellEvidence] = []
        try:
            for cell_index, (cell, adapter) in enumerate(self.preflight.adapters):
                guard.select_cell(cell)
                external_baseline = self.preflight.external_request_baselines[cell.cell_id]

                def validate_terminal(
                    evidence: Mapping[str, object],
                    active_cell: _PromptModelCell = cell,
                    active_adapter: OpenAICompatibleDecisionAdapter = adapter,
                    baseline: int = external_baseline,
                ) -> None:
                    _validate_dynamic_terminal(
                        evidence,
                        manifest=self.manifest,
                        cell=active_cell,
                        adapter=active_adapter,
                        external_baseline=baseline,
                    )

                consumer = _PrimaryOnlyConcurrentRuntimeConsumer(
                    config,
                    adapter,
                    expected_prompt_version=cell.prompt_version,
                    execution_contract=_cell_execution_identity(
                        manifest=self.manifest,
                        manifest_sha256=self.manifest_sha256,
                        cell_index=cell_index,
                        cell=cell,
                    ),
                    expected_sample_identity=self.manifest.sample.sample_identity,
                    before_logical_judgment=guard.before,
                    validate_terminal=validate_terminal,
                    after_logical_judgment=guard.after,
                )
                output_target = _cell_output_target(root, cell_index)
                workspace = derive_concurrent_execution_workspace(output_target)
                try:
                    result = consumer.resume(output_target) if workspace.exists() else consumer.run_new(output_target)
                except _DynamicCapExhausted:
                    return _DynamicRunOutcome(
                        evidence=None,
                        logical_judgments=guard.logical_judgments,
                        physical_attempts=guard.physical_attempts,
                    )
                _validate_dynamic_initial_state(
                    result,
                    source_candidate_rows=self.closure.source_evidence.candidate_rows,
                )
                cell_evidence = _build_dynamic_cell_evidence(
                    manifest=self.manifest,
                    manifest_sha256=self.manifest_sha256,
                    cell_index=cell_index,
                    cell=cell,
                    result=result,
                )
                if cell_evidence.logical_judgment_count != self.manifest.request_caps.logical_judgments_per_cell:
                    raise ValueError("dynamic cell did not close its complete logical schedule")
                cells.append(cell_evidence)
        except ConcurrentRobustnessError:
            raise
        except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ConcurrentRobustnessError(
                ConcurrentRobustnessErrorCode.WORKSPACE_CORRUPT,
                "dynamic Prompt-Model runtime or durable checkpoint failed closed",
            ) from exc

        logical_judgments = sum(cell.logical_judgment_count for cell in cells)
        physical_attempts = sum(cell.physical_attempt_count for cell in cells)
        external_request_invocations = 0 if execution.profile == "deterministic_validation" else physical_attempts
        evidence = _CellEvidenceDocument(
            schema_version="concurrent-robustness-cell-evidence-v1",
            evidence_profile=(
                "deterministic_fixture" if execution.profile == "deterministic_validation" else "formal_live"
            ),
            manifest_sha256=self.manifest_sha256,
            source_identity=_expected_cell_source_identity(self.manifest),
            request_contract=self.manifest.request_contract,
            request_contract_sha256=_sha256_bytes(
                _json_bytes(self.manifest.request_contract.model_dump(mode="json"))
            ),
            message_ids=self.manifest.message_ids,
            cell_count=len(cells),
            logical_judgment_count=logical_judgments,
            physical_attempt_count=physical_attempts,
            external_request_invocations=external_request_invocations,
            live_api_triggered=external_request_invocations > 0,
            production_deploy_eligible=False,
            conditional_scope="fixed-sample-fixed-graph-one-realized-path-per-cell",
            claim_statements=_SAFE_CLAIM_STATEMENTS,
            cells=tuple(cells),
        )
        _atomic_write_dynamic_json(
            root / _DYNAMIC_STATUS,
            _dynamic_status_payload(
                manifest_sha256=self.manifest_sha256,
                lifecycle="cells_complete",
                logical_judgments=logical_judgments,
                physical_attempts=physical_attempts,
                reserved_logical_judgments=logical_judgments,
                reserved_physical_attempts=physical_attempts,
                reserved_cost_usd=guard.reserved_cost_usd,
                last_cell_id=cells[-1].cell_id,
                last_pair_id=cells[-1].terminal_rows[-1].pair_id,
            ),
        )
        return _DynamicRunOutcome(
            evidence=evidence,
            logical_judgments=logical_judgments,
            physical_attempts=physical_attempts,
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
    """Run or resume one robustness study behind a single high-level Interface.

    ``None`` creates the zero-call Ranking Weight workspace. An exact, explicitly
    authorized 16-cell Adapter map runs or resumes independent Primary-only cells;
    deterministic validation accepts injected clients only and cannot trigger an
    external request. Complete cell evidence is closed into an immutable study root
    and a separate non-deployable report candidate behind this same Interface.
    """

    def run(
        self,
        manifest: ConcurrentRobustnessManifest,
        adapters_by_cell: Mapping[str, LLMDecisionAdapter] | None,
        output_dir: str | Path,
        *,
        report_destination: str | Path | None = None,
    ) -> ConcurrentRobustnessStudyResult:
        if not isinstance(manifest, ConcurrentRobustnessManifest):
            raise ConcurrentRobustnessError(
                ConcurrentRobustnessErrorCode.INVALID_MANIFEST,
                "ConcurrentRobustnessStudy requires a typed immutable manifest",
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
        dynamic_preflight: _DynamicPreflight | None = None
        if adapters_by_cell is not None:
            if not isinstance(adapters_by_cell, Mapping):
                raise _dynamic_adapter_error("dynamic adapters_by_cell must be a Mapping")
            dynamic_preflight = _preflight_dynamic_adapters(manifest, adapters_by_cell)

        if output_path.exists():
            try:
                actual_files = {path.name for path in output_path.iterdir()}
            except OSError as exc:
                raise ConcurrentRobustnessError(
                    ConcurrentRobustnessErrorCode.WORKSPACE_CORRUPT,
                    "existing robustness workspace cannot be inspected safely",
                ) from exc
            workspace_extras = actual_files - _WORKSPACE_FILES
            cell_workspace = workspace_extras == _CELL_WORKSPACE_ADDITIONS
            dynamic_partial = (
                dynamic_preflight is not None
                and bool(workspace_extras)
                and workspace_extras < _CELL_WORKSPACE_ADDITIONS
                and _dynamic_root(output_path).is_dir()
            )
            ready_result = _validate_workspace(
                output_path,
                output_path=output_path,
                manifest=manifest,
                manifest_sha256=manifest_sha256,
                analysis=analysis,
                allowed_extra_files=(
                    _CELL_WORKSPACE_ADDITIONS
                    if cell_workspace
                    else workspace_extras
                    if dynamic_partial
                    else None
                ),
            )
            if not cell_workspace:
                _assert_source_unchanged(closure)
                if dynamic_preflight is not None:
                    return self._run_dynamic(
                        manifest=manifest,
                        manifest_sha256=manifest_sha256,
                        output_path=output_path,
                        source_path=source_path,
                        closure=closure,
                        preflight=dynamic_preflight,
                        report_destination=report_destination,
                    )
                if report_destination is not None:
                    raise ConcurrentRobustnessError(
                        ConcurrentRobustnessErrorCode.ANALYSIS_INVALID,
                        "robustness report composition requires an immutable complete study root",
                    )
                return ready_result
            evidence, registry = _load_cell_workspace(
                output_path,
                output_path=output_path,
                manifest=manifest,
                manifest_sha256=manifest_sha256,
            )
            if dynamic_preflight is not None:
                _validate_completed_dynamic_root(
                    manifest=manifest,
                    manifest_sha256=manifest_sha256,
                    output_path=output_path,
                    source_path=source_path,
                    evidence=evidence,
                )
            try:
                prompt_model_analysis, claim_audit = _RobustnessAnalyzer(
                    manifest=manifest,
                    evidence=evidence,
                    manifest_sha256=manifest_sha256,
                ).analyze()
            except (KeyError, TypeError, ValueError) as exc:
                raise ConcurrentRobustnessError(
                    ConcurrentRobustnessErrorCode.ANALYSIS_INVALID,
                    "Prompt-Model evidence failed the closed robustness analysis contract",
                ) from exc
            _assert_source_unchanged(closure)
            _validate_study_paths(
                source_path,
                output_path.with_name(f"{output_path.name}{_STUDY_ROOT_SUFFIX}"),
            )
            try:
                study_root = _close_study_root(
                    output_path,
                    manifest=manifest,
                    manifest_sha256=manifest_sha256,
                    evidence=evidence,
                    registry=registry,
                    analysis=prompt_model_analysis,
                    claims=claim_audit,
                )
            except ConcurrentRobustnessError:
                raise
            except OSError as exc:
                raise ConcurrentRobustnessError(
                    ConcurrentRobustnessErrorCode.WORKSPACE_CONFLICT,
                    "robustness study root could not be finalized atomically",
                ) from exc
            _assert_source_unchanged(closure)
            report_candidate: Path | None = None
            effective_report_destination = report_destination
            if dynamic_preflight is not None and effective_report_destination is None:
                effective_report_destination = _dynamic_report_destination(output_path)
            if effective_report_destination is not None:
                try:
                    if dynamic_preflight is not None and os.path.lexists(effective_report_destination):
                        report_candidate = _validate_concurrent_robustness_report_candidate(
                            formal_root=source_path,
                            study_root=study_root,
                            workspace_root=output_path,
                            manifest=manifest,
                            manifest_payload=manifest_payload,
                            manifest_sha256=manifest_sha256,
                            candidate_dir=effective_report_destination,
                        )
                    else:
                        report_candidate = _compose_concurrent_robustness_report_candidate(
                            formal_root=source_path,
                            study_root=study_root,
                            workspace_root=output_path,
                            manifest=manifest,
                            manifest_payload=manifest_payload,
                            manifest_sha256=manifest_sha256,
                            destination_dir=effective_report_destination,
                        )
                except _RobustnessReportPathError as exc:
                    raise ConcurrentRobustnessError(
                        ConcurrentRobustnessErrorCode.PATH_VIOLATION,
                        "robustness report source or destination path is unsafe",
                    ) from exc
                except _RobustnessReportConflictError as exc:
                    raise ConcurrentRobustnessError(
                        ConcurrentRobustnessErrorCode.WORKSPACE_CONFLICT,
                        "robustness report destination conflicts with existing state",
                    ) from exc
                except _RobustnessReportClosureError as exc:
                    raise ConcurrentRobustnessError(
                        ConcurrentRobustnessErrorCode.ANALYSIS_INVALID,
                        "combined Formal and robustness report closure failed",
                    ) from exc
                except OSError as exc:
                    raise ConcurrentRobustnessError(
                        ConcurrentRobustnessErrorCode.WORKSPACE_CONFLICT,
                        "robustness report candidate could not be published atomically",
                    ) from exc
                _assert_source_unchanged(closure)
            return ConcurrentRobustnessStudyResult(
                status=ConcurrentRobustnessStudyStatus.COMPLETE,
                workspace_root=output_path,
                validation_report=study_root / _WORKSPACE_VALIDATION,
                manifest_sha256=manifest_sha256,
                logical_provider_attempts=evidence.logical_judgment_count,
                physical_provider_attempts=evidence.physical_attempt_count,
                study_root=study_root,
                report_candidate=report_candidate,
            )
        if report_destination is not None and dynamic_preflight is None:
            raise ConcurrentRobustnessError(
                ConcurrentRobustnessErrorCode.ANALYSIS_INVALID,
                "robustness report composition requires an existing complete study workspace",
            )
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
        if dynamic_preflight is not None:
            return self._run_dynamic(
                manifest=manifest,
                manifest_sha256=manifest_sha256,
                output_path=output_path,
                source_path=source_path,
                closure=closure,
                preflight=dynamic_preflight,
                report_destination=report_destination,
            )
        return result

    def _run_dynamic(
        self,
        *,
        manifest: ConcurrentRobustnessManifest,
        manifest_sha256: str,
        output_path: Path,
        source_path: Path,
        closure: ConcurrentMessageArtifactClosure,
        preflight: _DynamicPreflight,
        report_destination: str | Path | None,
    ) -> ConcurrentRobustnessStudyResult:
        outcome = _DynamicPromptModelProducer(
            manifest=manifest,
            manifest_sha256=manifest_sha256,
            output_path=output_path,
            source_path=source_path,
            closure=closure,
            preflight=preflight,
        ).run()
        _assert_source_unchanged(closure)
        if outcome.evidence is None:
            return ConcurrentRobustnessStudyResult(
                status=ConcurrentRobustnessStudyStatus.RESUMABLE,
                workspace_root=output_path,
                validation_report=output_path / _WORKSPACE_VALIDATION,
                manifest_sha256=manifest_sha256,
                logical_provider_attempts=outcome.logical_judgments,
                physical_provider_attempts=outcome.physical_attempts,
                study_root=None,
                report_candidate=None,
            )
        _publish_dynamic_evidence(
            output_path,
            manifest=manifest,
            manifest_sha256=manifest_sha256,
            evidence=outcome.evidence,
        )
        _assert_source_unchanged(closure)
        destination = report_destination or _dynamic_report_destination(output_path)
        return self.run(
            manifest,
            None,
            output_path,
            report_destination=destination,
        )
