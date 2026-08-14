from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import shutil
import stat
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from ._concurrent_runtime_spool import _ConcurrentRuntimeBatchSpool
from .concurrent_execution_journal import ConcurrentExecutionJournal
from .concurrent_message_experiment import (
    CONCURRENT_MESSAGE_CANDIDATE_FIELDS,
    CONCURRENT_MESSAGE_ENGAGED_NEIGHBOR_FORMULA,
    CONCURRENT_MESSAGE_POSITIVE_ACTIONS,
    CONCURRENT_MESSAGE_RANKING_FORMULA,
    CONCURRENT_MESSAGE_TERMINAL_FIELDS,
    ConcurrentMessageExperimentConfig,
    _adapter_external_request_invocations,
    _prepare_full_pool_concurrent_runtime_inputs,
    _PrimaryOnlyConcurrentRuntimeConsumer,
    _PrimaryOnlyConcurrentRuntimeSpoolResult,
    authoritative_message_definitions,
)
from .decision import LLMDecisionAdapter
from .final_research import FULL_POOL_MEMBERSHIP_METHOD
from .prompt_contracts import (
    APPROVED_EXCLUDED_FIELDS,
    APPROVED_VISIBLE_FIELD_ALLOWLIST,
    CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY,
)
from .prompt_field_summary import CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION
from .provider_request_contract import (
    OMITTED_SAMPLING_PARAMETERS,
    STRUCTURED_OUTPUT_SCHEMA_HASH,
    ProviderRequestContract,
)
from .providers.openai_compatible import OpenAICompatibleDecisionAdapter
from .providers.pi_subscription import PI_SUBSCRIPTION_ADAPTER_IDENTITY, PiSubscriptionProviderClient
from .schemas import ReportConfig

__all__ = [
    "FULL_POOL_AUTHORITATIVE_MESSAGES_SHA256",
    "FULL_POOL_CONTRACT_SCHEMA",
    "FULL_POOL_FORMAL_ADAPTER_IDENTITY",
    "FULL_POOL_FORMAL_ATTEMPT_RESERVATION_POLICY",
    "FULL_POOL_FORMAL_AUTHORIZATION_SCHEMA",
    "FULL_POOL_FORMAL_DECISION_STORE_POLICY",
    "FULL_POOL_FORMAL_EXECUTION_SCHEMA",
    "FULL_POOL_FORMAL_LOGICAL_JUDGMENT_CAP",
    "FULL_POOL_FORMAL_OBSERVED_EVIDENCE_SCHEMA",
    "FULL_POOL_FORMAL_OBSERVED_MODEL_POLICY",
    "FULL_POOL_FORMAL_OAUTH_ACCOUNT_BINDING",
    "FULL_POOL_FORMAL_PHYSICAL_ATTEMPT_CAP",
    "FULL_POOL_FORMAL_QUALIFICATION_FRESHNESS_POLICY",
    "FULL_POOL_FORMAL_QUALIFICATION_SCHEMA",
    "FULL_POOL_FORMAL_RECONCILIATION_POLICY",
    "FULL_POOL_FORMAL_REQUESTED_MODEL",
    "FULL_POOL_FORMAL_TRANSPORT",
    "FULL_POOL_FORMAL_VALIDATION_ACCOUNT_BINDING",
    "FULL_POOL_FORMAL_VALIDATION_ADAPTER_IDENTITY",
    "FULL_POOL_VALIDATION_DATASET_IDENTITY",
    "FULL_POOL_VALIDATION_TOKEN",
    "FullPoolExperimentContract",
    "FullPoolExperimentError",
    "FullPoolExperimentErrorCode",
    "FullPoolFormalAuthorization",
    "FullPoolFormalExecutionContract",
    "FullPoolFormalExperiment",
    "FullPoolFormalQualification",
    "FullPoolFormalRequestContract",
    "FullPoolRunResult",
    "FullPoolRunStatus",
]

FULL_POOL_CONTRACT_SCHEMA = "full-pool-experiment-contract-v1"
FULL_POOL_FORMAL_EXECUTION_SCHEMA = "full-pool-formal-execution-contract-v1"
FULL_POOL_FORMAL_AUTHORIZATION_SCHEMA = "full-pool-formal-execution-authorization-v1"
FULL_POOL_FORMAL_QUALIFICATION_SCHEMA = "full-pool-formal-model-qualification-v1"
FULL_POOL_FORMAL_OBSERVED_EVIDENCE_SCHEMA = "full-pool-formal-observed-model-evidence-v1"
FULL_POOL_FORMAL_REQUESTED_MODEL = "gpt-5.6-sol"
FULL_POOL_FORMAL_REQUIRED_OBSERVED_MODEL = "gpt-5.6-sol"
FULL_POOL_FORMAL_TRANSPORT = "openai-codex"
FULL_POOL_FORMAL_ADAPTER_IDENTITY = PI_SUBSCRIPTION_ADAPTER_IDENTITY
FULL_POOL_FORMAL_VALIDATION_ADAPTER_IDENTITY = "full-pool-formal-validation-injected-client-v1"
FULL_POOL_FORMAL_LOGICAL_JUDGMENT_CAP = 109_200
FULL_POOL_FORMAL_PHYSICAL_ATTEMPT_CAP = 120_120
FULL_POOL_FORMAL_WORKER_COUNT = 1
FULL_POOL_FORMAL_DECISION_STORE_POLICY = "fresh-per-judgment-no-cache-v1"
FULL_POOL_FORMAL_ATTEMPT_RESERVATION_POLICY = "reserve-retry-window-before-dispatch-v1"
FULL_POOL_FORMAL_OBSERVED_MODEL_POLICY = "qualified-observed-model-exact-match-v1"
FULL_POOL_FORMAL_RECONCILIATION_POLICY = "no-readback-no-automatic-replay-v1"
FULL_POOL_FORMAL_QUALIFICATION_FRESHNESS_POLICY = "same-output-identity-max-24h-v1"
FULL_POOL_FORMAL_OAUTH_ACCOUNT_BINDING = "pi-runtime-openai-codex-oauth-current-user-v1"
FULL_POOL_FORMAL_VALIDATION_ACCOUNT_BINDING = "deterministic-validation-fixture-v1"
FULL_POOL_SOURCE_SCHEMA = "full-pool-validation-source-v1"
FULL_POOL_MANIFEST_SCHEMA = "full-pool-validation-manifest-v1"
FULL_POOL_BATCH_SCHEMA = "full-pool-validation-batch-v1"
FULL_POOL_AGGREGATES_SCHEMA = "full-pool-validation-aggregates-v1"
FULL_POOL_DIAGNOSTICS_SCHEMA = "full-pool-validation-diagnostics-v1"
FULL_POOL_SCHEMA_DOCUMENT_VERSION = "full-pool-validation-schema-document-v1"
FULL_POOL_FORMAL_SOURCE_SCHEMA = "full-pool-formal-source-v1"
FULL_POOL_FORMAL_MANIFEST_SCHEMA = "full-pool-formal-manifest-v1"
FULL_POOL_FORMAL_BATCH_SCHEMA = "full-pool-formal-batch-v1"
FULL_POOL_FORMAL_AGGREGATES_SCHEMA = "full-pool-formal-aggregates-v1"
FULL_POOL_FORMAL_DIAGNOSTICS_SCHEMA = "full-pool-formal-diagnostics-v1"
FULL_POOL_FORMAL_SCHEMA_DOCUMENT_VERSION = "full-pool-formal-schema-document-v1"
FULL_POOL_VALIDATION_TOKEN = "full-pool-deterministic-validation-v1"
FULL_POOL_VALIDATION_DATASET_IDENTITY = "full-pool-validation-dataset-v1"
FULL_POOL_VALIDATION_USER_SET_IDENTITY = "full-pool-validation-eligible-users-v1"
FULL_POOL_PRODUCTION_DATASET_IDENTITY = (
    "jinjiang-final-caption-hashtag-comments-profiles-latent-v1-validation-20260705T000000Z"
)
FULL_POOL_PRODUCTION_USER_SET_IDENTITY = "jinjiang-latent-v1-eligible-users-v1"
FULL_POOL_PRODUCTION_USER_IDS_SHA256 = "c9b5c7d30e5197828d61f4f92df2fd6d5720d814aeb01bc0edfe0d4631bc7669"
FULL_POOL_AUTHORITATIVE_MESSAGES_SHA256 = "b2f99563123e673a5db714532c6831580c8481257892eeff41e4eaf4c0afdcfc"
FULL_POOL_MESSAGE_IDS = ("message_1", "message_2", "message_3")
FULL_POOL_PRODUCTION_USER_COUNT = 36_400
FULL_POOL_PRODUCTION_HORIZON = 30
FULL_POOL_PRODUCTION_CAPACITY = 1_214
FULL_POOL_PRODUCTION_FINAL_BATCH_PAIRS_PER_MESSAGE = 1_194
FULL_POOL_PRODUCTION_ELIGIBLE_PAIRS = 109_200
FULL_POOL_PRODUCTION_CANDIDATE_ROWS = 1_691_730

_CANDIDATE_ROWS_FILE = "candidate_rows.jsonl"
_PAIR_ROWS_FILE = "pair_rows.jsonl"
_TERMINAL_ROWS_FILE = "terminal_rows.jsonl"
_CONTRACT_FILE = "contract.json"
_SCHEMA_FILE = "schema.json"
_AGGREGATES_FILE = "aggregates.json"
_DIAGNOSTICS_FILE = "diagnostics.json"
_MANIFEST_FILE = "manifest.json"
_BATCHES_DIR = "batches"
_FORMAL_EXECUTION_IDENTITY_FILE = "full_pool_execution_identity.json"
_FORMAL_EXECUTION_STATUS_FILE = "full_pool_execution_status.json"
_FORMAL_ATTEMPT_LEDGER_FILE = "full_pool_attempt_ledger.jsonl"
_FORMAL_AUTHORIZATION_SOURCE_FILE = "execution_authorization.json"
_FORMAL_QUALIFICATION_SOURCE_FILE = "model_qualification.json"
_FORMAL_OBSERVED_EVIDENCE_SOURCE_FILE = "observed_model_evidence.json"
_FORMAL_EXECUTION_IDENTITY_SCHEMA = "full-pool-formal-operational-identity-v1"
_FORMAL_EXECUTION_STATUS_SCHEMA = "full-pool-formal-operational-status-v1"
_FORMAL_ATTEMPT_LEDGER_SCHEMA = "full-pool-formal-attempt-ledger-v1"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_OUTPUT_IDENTITY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_VALIDATION_OUTPUT_IDENTITY_PATTERN = re.compile(r"^full-pool-validation-v1-[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_PRODUCTION_OUTPUT_IDENTITY_PATTERN = re.compile(
    r"^jinjiang-concurrent-full-pool-formal-v1-gpt-5\.6-sol-[0-9]{8}T[0-9]{6}Z$"
)
_PRIMARY_PAIR_FIELDS = (
    "pair_id",
    "pair_schedule_position",
    "time_step",
    "message_id",
    "message_title",
    "user_id",
    "is_seed",
    "selection_reason",
    "ranking_position",
    "base_network_relevance",
    "base_network_relevance_full_precision",
    "campaign_engaged_neighbor_count",
    "campaign_engaged_neighbor_signal",
    "campaign_engaged_neighbor_signal_full_precision",
    "historical_tag_affinity",
    "raw_message_user_fit",
    "raw_message_user_fit_full_precision",
    "normalized_message_user_fit",
    "normalized_message_user_fit_full_precision",
    "personalized_delivery_score",
    "personalized_delivery_score_full_precision",
    "primary_status",
    "primary_action",
    "primary_probability",
    "primary_confidence",
    "primary_reason",
    "primary_decision_source",
    "primary_prompt_version",
    "primary_provider_metadata",
    "campaign_feedback_committed",
    "primary_terminal_coverage",
)


class FullPoolRunStatus(str, Enum):
    RESUMABLE = "resumable"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    COMPLETE = "complete"


class FullPoolExperimentErrorCode(str, Enum):
    INVALID_CONTRACT = "invalid_contract"
    UNSUPPORTED_PROFILE = "unsupported_profile"
    INVALID_ADAPTER = "invalid_adapter"
    INVALID_DATASET = "invalid_dataset"
    PATH_VIOLATION = "path_violation"
    OUTPUT_CONFLICT = "output_conflict"
    RUNTIME_FAILED = "runtime_failed"
    SOURCE_CLOSURE_FAILED = "source_closure_failed"


class FullPoolExperimentError(ValueError):
    """One bounded failure exposed by the Full-Pool experiment Interface."""

    def __init__(self, code: FullPoolExperimentErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


class _FrozenContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _parse_utc_token(value: str, context: str) -> datetime:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError(f"{context} must be an exact UTC second token") from exc
    return parsed


def _validate_artifact_window(start: str, end: str, context: str) -> None:
    started = _parse_utc_token(start, f"{context} start")
    ended = _parse_utc_token(end, f"{context} expiry")
    if not started < ended or ended - started > timedelta(hours=24):
        raise ValueError(f"{context} must have a positive validity window no longer than 24 hours")


def _safe_artifact_reference(value: str) -> str:
    lowered = value.lower()
    if "\n" in value or "\r" in value or any(
        marker in lowered
        for marker in (
            "bearer ",
            "api_key=",
            "apikey=",
            "access_token",
            "refresh_token",
            "cookie=",
            "password=",
            "secret=",
        )
    ):
        raise ValueError("artifact reference must not contain credential material")
    return value


class FullPoolFormalRequestContract(_FrozenContractModel):
    """Exact P0 Responses request facts without Prompt or Provider payloads."""

    schema_version: Literal["provider-request-contract-v1"]
    requested_model: str
    prompt_version: str
    prompt_canonical_hash: str
    wire_api: str
    reasoning_effort: str
    output_token_ceiling: int = Field(ge=1)
    timeout_seconds: float = Field(gt=0.0)
    max_retries: int = Field(ge=0)
    retry_backoff_seconds: float = Field(ge=0.0)
    structured_output_schema_version: str
    structured_output_schema_hash: str
    omitted_parameters: tuple[str, ...]

    @model_validator(mode="after")
    def _validate_frozen_request(self) -> FullPoolFormalRequestContract:
        prompt = CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.resolve(CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION)
        expected: dict[str, object] = {
            "requested_model": FULL_POOL_FORMAL_REQUESTED_MODEL,
            "prompt_version": CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
            "prompt_canonical_hash": prompt.canonical_hash,
            "wire_api": "responses",
            "reasoning_effort": "low",
            "output_token_ceiling": 256,
            "timeout_seconds": 30.0,
            "max_retries": 2,
            "retry_backoff_seconds": 1.0,
            "structured_output_schema_version": "engage-decision-output-v1",
            "structured_output_schema_hash": STRUCTURED_OUTPUT_SCHEMA_HASH,
            "omitted_parameters": OMITTED_SAMPLING_PARAMETERS,
        }
        for field_name, expected_value in expected.items():
            value = getattr(self, field_name)
            if isinstance(expected_value, float):
                if not isinstance(value, (int, float)) or not math.isclose(
                    float(value), expected_value, rel_tol=0.0, abs_tol=1e-12
                ):
                    raise ValueError(f"Formal request {field_name} does not match the frozen P0 policy")
            elif value != expected_value:
                raise ValueError(f"Formal request {field_name} does not match the frozen P0 policy")
        return self


class FullPoolFormalAuthorization(_FrozenContractModel):
    """Explicit authorization artifact facts bound to one output identity."""

    schema_version: Literal["full-pool-formal-execution-authorization-v1"]
    authorization_kind: Literal["deterministic_validation_fixture", "formal_live_provider"]
    authorization_reference: str = Field(min_length=1, max_length=240)
    artifact_path: Path
    artifact_sha256: str
    authorized_at_utc: str
    expires_at_utc: str
    account_binding: str
    output_identity: str
    dataset_identity: str
    eligible_user_ids_sha256: str
    message_snapshot_sha256: str
    provider: str
    transport: str
    adapter_identity: str
    requested_model: str
    required_observed_model: str
    logical_judgment_cap: int = Field(ge=1)
    physical_attempt_cap: int = Field(ge=1)
    worker_count: int = Field(ge=1)
    subscription_billed_cost_usd: float = Field(ge=0.0)
    external_requests_allowed: bool
    production_deploy_eligible: Literal[False]

    @field_validator("authorization_reference")
    @classmethod
    def _safe_authorization_reference(cls, value: str) -> str:
        return _safe_artifact_reference(value)

    @field_validator("artifact_path", mode="before")
    @classmethod
    def _normalize_authorization_path(cls, value: object) -> Path:
        return Path(cast(str | os.PathLike[str], value)).expanduser().resolve(strict=False)

    @model_validator(mode="after")
    def _validate_authorization(self) -> FullPoolFormalAuthorization:
        if not _SHA256_PATTERN.fullmatch(self.artifact_sha256):
            raise ValueError("Formal authorization artifact hash is invalid")
        _validate_artifact_window(self.authorized_at_utc, self.expires_at_utc, "Formal authorization")
        return self


class FullPoolFormalQualification(_FrozenContractModel):
    """Fresh observed-model qualification facts bound to the same run identity."""

    schema_version: Literal["full-pool-formal-model-qualification-v1"]
    qualification_kind: Literal["deterministic_validation_fixture", "provider_observed"]
    artifact_reference: str = Field(min_length=1, max_length=240)
    artifact_path: Path
    artifact_sha256: str
    authorization_artifact_sha256: str
    qualified_at_utc: str
    expires_at_utc: str
    account_binding: str
    observed_response_artifact_path: Path
    observed_response_sha256: str
    output_identity: str
    provider: str
    transport: str
    requested_model: str
    required_observed_model: str
    freshness_policy: str
    status: Literal["qualified"]

    @field_validator("artifact_reference")
    @classmethod
    def _safe_qualification_reference(cls, value: str) -> str:
        return _safe_artifact_reference(value)

    @field_validator("artifact_path", "observed_response_artifact_path", mode="before")
    @classmethod
    def _normalize_qualification_path(cls, value: object) -> Path:
        return Path(cast(str | os.PathLike[str], value)).expanduser().resolve(strict=False)

    @model_validator(mode="after")
    def _validate_qualification(self) -> FullPoolFormalQualification:
        if any(
            not _SHA256_PATTERN.fullmatch(value)
            for value in (
                self.artifact_sha256,
                self.authorization_artifact_sha256,
                self.observed_response_sha256,
            )
        ):
            raise ValueError("Formal qualification artifact hashes are invalid")
        _validate_artifact_window(self.qualified_at_utc, self.expires_at_utc, "Formal qualification")
        return self


class FullPoolFormalExecutionContract(_FrozenContractModel):
    """Production request, authorization, cap, and durable output identity."""

    schema_version: Literal["full-pool-formal-execution-contract-v1"]
    evidence_profile: Literal["deterministic_validation_fixture", "formal_live"]
    provider: str
    transport: str
    adapter_identity: str
    requested_model: str
    required_observed_model: str
    prompt_version: str
    prompt_canonical_hash: str
    visible_field_allowlist: tuple[str, ...]
    excluded_fields: tuple[str, ...]
    request_contract: FullPoolFormalRequestContract
    decision_store_policy: str
    attempt_reservation_policy: str
    observed_model_policy: str
    reconciliation_policy: str
    worker_count: int = Field(ge=1)
    logical_judgment_cap: int = Field(ge=1)
    physical_attempt_cap: int = Field(ge=1)
    active_logical_judgment_cap: int = Field(ge=1)
    active_physical_attempt_cap: int = Field(ge=1)
    subscription_billed_cost_usd: float = Field(ge=0.0)
    operational_root: Path
    source_root: Path
    candidate_root: Path
    authorization: FullPoolFormalAuthorization
    qualification: FullPoolFormalQualification

    @field_validator("operational_root", "source_root", "candidate_root", mode="before")
    @classmethod
    def _normalize_execution_path(cls, value: object) -> Path:
        return Path(cast(str | os.PathLike[str], value)).expanduser().resolve(strict=False)

    @model_validator(mode="after")
    def _validate_execution(self) -> FullPoolFormalExecutionContract:
        prompt = CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.resolve(CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION)
        expected: dict[str, object] = {
            "provider": "openai_compatible",
            "transport": FULL_POOL_FORMAL_TRANSPORT,
            "requested_model": FULL_POOL_FORMAL_REQUESTED_MODEL,
            "required_observed_model": FULL_POOL_FORMAL_REQUIRED_OBSERVED_MODEL,
            "prompt_version": CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
            "prompt_canonical_hash": prompt.canonical_hash,
            "visible_field_allowlist": APPROVED_VISIBLE_FIELD_ALLOWLIST,
            "excluded_fields": APPROVED_EXCLUDED_FIELDS,
            "decision_store_policy": FULL_POOL_FORMAL_DECISION_STORE_POLICY,
            "attempt_reservation_policy": FULL_POOL_FORMAL_ATTEMPT_RESERVATION_POLICY,
            "observed_model_policy": FULL_POOL_FORMAL_OBSERVED_MODEL_POLICY,
            "reconciliation_policy": FULL_POOL_FORMAL_RECONCILIATION_POLICY,
            "worker_count": FULL_POOL_FORMAL_WORKER_COUNT,
            "logical_judgment_cap": FULL_POOL_FORMAL_LOGICAL_JUDGMENT_CAP,
            "physical_attempt_cap": FULL_POOL_FORMAL_PHYSICAL_ATTEMPT_CAP,
            "subscription_billed_cost_usd": 0.0,
        }
        for field_name, expected_value in expected.items():
            value = getattr(self, field_name)
            if isinstance(expected_value, float):
                if not math.isclose(float(value), expected_value, rel_tol=0.0, abs_tol=1e-12):
                    raise ValueError(f"Formal execution {field_name} does not match the frozen policy")
            elif value != expected_value:
                raise ValueError(f"Formal execution {field_name} does not match the frozen policy")
        if self.active_logical_judgment_cap > self.logical_judgment_cap:
            raise ValueError("active logical cap exceeds the authorized Full-Pool cap")
        if self.active_physical_attempt_cap > self.physical_attempt_cap:
            raise ValueError("active physical cap exceeds the authorized Full-Pool cap")
        if (
            self.evidence_profile == "formal_live"
            and self.active_physical_attempt_cap < self.active_logical_judgment_cap
        ):
            raise ValueError("Formal live physical cap cannot be smaller than its logical cap")
        expected_adapter_identity = (
            FULL_POOL_FORMAL_VALIDATION_ADAPTER_IDENTITY
            if self.evidence_profile == "deterministic_validation_fixture"
            else FULL_POOL_FORMAL_ADAPTER_IDENTITY
        )
        if self.adapter_identity != expected_adapter_identity:
            raise ValueError("Formal execution Adapter identity is crossed with its evidence profile")
        expected_account_binding = (
            FULL_POOL_FORMAL_VALIDATION_ACCOUNT_BINDING
            if self.evidence_profile == "deterministic_validation_fixture"
            else FULL_POOL_FORMAL_OAUTH_ACCOUNT_BINDING
        )
        if (
            self.authorization.account_binding != expected_account_binding
            or self.qualification.account_binding != expected_account_binding
        ):
            raise ValueError("Formal authorization and qualification account binding is crossed")
        if self.source_root.name != self.authorization.output_identity:
            raise ValueError("Formal source path is crossed with the authorization output identity")
        if self.operational_root != self.source_root.parent / f".{self.source_root.name}.operational":
            raise ValueError("Formal operational path is not derived from the frozen source identity")
        if self.candidate_root != self.source_root.with_name(f"{self.source_root.name}-report-candidate"):
            raise ValueError("Formal candidate path is not derived from the frozen source identity")
        if len({self.operational_root, self.source_root, self.candidate_root}) != 3:
            raise ValueError("Formal operational, source, and candidate paths must be mutually exclusive")

        authorization = self.authorization
        qualification = self.qualification
        artifact_paths = (
            authorization.artifact_path,
            qualification.artifact_path,
            qualification.observed_response_artifact_path,
        )
        if len(set(artifact_paths)) != 3:
            raise ValueError("Formal authorization, qualification, and observed evidence need independent files")
        protected_roots = (self.operational_root, self.source_root, self.candidate_root)
        if any(
            artifact_path == root or artifact_path.is_relative_to(root)
            for artifact_path in artifact_paths
            for root in protected_roots
        ):
            raise ValueError("Formal authorization artifacts must remain outside runtime output roots")
        if len(
            {
                authorization.artifact_sha256,
                qualification.artifact_sha256,
                qualification.observed_response_sha256,
            }
        ) != 3:
            raise ValueError("Formal authorization, qualification, and observed response hashes must be independent")
        authorized_at = _parse_utc_token(authorization.authorized_at_utc, "Formal authorization time")
        authorization_expires = _parse_utc_token(authorization.expires_at_utc, "Formal authorization expiry")
        qualified_at = _parse_utc_token(qualification.qualified_at_utc, "Formal qualification time")
        qualification_expires = _parse_utc_token(qualification.expires_at_utc, "Formal qualification expiry")
        if not authorized_at <= qualified_at <= authorization_expires:
            raise ValueError("Formal qualification is outside its authorization validity window")
        if self.evidence_profile == "formal_live":
            if _PRODUCTION_OUTPUT_IDENTITY_PATTERN.fullmatch(authorization.output_identity) is None:
                raise ValueError("Formal live authorization output identity has no UTC run token")
            run_token = authorization.output_identity.rsplit("-", 1)[-1]
            run_time = datetime.strptime(run_token, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            if not (authorized_at <= run_time <= authorization_expires):
                raise ValueError("Formal live run identity falls outside authorization freshness")
            if not (qualified_at <= run_time <= qualification_expires):
                raise ValueError("Formal live run identity falls outside model qualification freshness")
        crossed_authorization = {
            "provider": self.provider,
            "transport": self.transport,
            "adapter_identity": self.adapter_identity,
            "requested_model": self.requested_model,
            "required_observed_model": self.required_observed_model,
            "logical_judgment_cap": self.logical_judgment_cap,
            "physical_attempt_cap": self.physical_attempt_cap,
            "worker_count": self.worker_count,
            "subscription_billed_cost_usd": self.subscription_billed_cost_usd,
        }
        for field_name, expected_value in crossed_authorization.items():
            if getattr(authorization, field_name) != expected_value:
                raise ValueError(f"Formal authorization {field_name} is crossed")
        crossed_qualification = {
            "authorization_artifact_sha256": authorization.artifact_sha256,
            "output_identity": authorization.output_identity,
            "provider": self.provider,
            "transport": self.transport,
            "requested_model": self.requested_model,
            "required_observed_model": self.required_observed_model,
            "freshness_policy": FULL_POOL_FORMAL_QUALIFICATION_FRESHNESS_POLICY,
            "account_binding": authorization.account_binding,
        }
        for field_name, expected_value in crossed_qualification.items():
            if getattr(qualification, field_name) != expected_value:
                raise ValueError(f"Formal qualification {field_name} is crossed")
        if self.evidence_profile == "deterministic_validation_fixture":
            if (
                authorization.authorization_kind != "deterministic_validation_fixture"
                or authorization.external_requests_allowed
                or qualification.qualification_kind != "deterministic_validation_fixture"
            ):
                raise ValueError("Formal-shaped Validation requires explicit zero-call fixture artifacts")
        elif (
            authorization.authorization_kind != "formal_live_provider"
            or not authorization.external_requests_allowed
            or qualification.qualification_kind != "provider_observed"
            or self.active_logical_judgment_cap != self.logical_judgment_cap
            or self.active_physical_attempt_cap != self.physical_attempt_cap
        ):
            raise ValueError("Formal live execution requires exact authorization, qualification, and caps")
        return self


class FullPoolExperimentContract(_FrozenContractModel):
    """Frozen full-pool membership, schedule, and output identity contract."""

    schema_version: Literal["full-pool-experiment-contract-v1"] = FULL_POOL_CONTRACT_SCHEMA
    profile: Literal["deterministic_validation", "production"]
    validation_token: str | None
    dataset_dir: Path
    dataset_identity: str = Field(min_length=1, max_length=200)
    eligible_user_set_identity: str = Field(min_length=1, max_length=200)
    eligible_user_ids_sha256: str
    eligible_user_count: int = Field(ge=1)
    message_ids: tuple[str, str, str]
    message_snapshot_sha256: str
    horizon: int = Field(ge=2)
    per_message_capacity: int = Field(ge=1)
    seed_top_k_per_proxy: int = Field(ge=1)
    primary_only: Literal[True]
    expected_eligible_pairs: int = Field(ge=1)
    expected_exposures: int = Field(ge=1)
    expected_primary_terminals: int = Field(ge=1)
    expected_committed_batches: int = Field(ge=2)
    expected_candidate_ranking_rows: int = Field(ge=1)
    expected_final_batch_pairs_per_message: int = Field(ge=1)
    output_identity: str
    formal_execution: FullPoolFormalExecutionContract | None = None

    @field_validator("dataset_dir", mode="before")
    @classmethod
    def _normalize_dataset_dir(cls, value: object) -> Path:
        path = Path(cast(str | os.PathLike[str], value)).expanduser()
        return path.resolve(strict=False)

    @field_validator("eligible_user_ids_sha256", "message_snapshot_sha256")
    @classmethod
    def _validate_sha256(cls, value: str) -> str:
        if not _SHA256_PATTERN.fullmatch(value):
            raise ValueError("contract hash fields must be lowercase SHA-256 digests")
        return value

    @field_validator("output_identity")
    @classmethod
    def _validate_output_identity(cls, value: str) -> str:
        if not _OUTPUT_IDENTITY_PATTERN.fullmatch(value):
            raise ValueError("output_identity must be a bounded stable token")
        return value

    @model_validator(mode="after")
    def _validate_closed_shape(self) -> FullPoolExperimentContract:
        if self.message_ids != FULL_POOL_MESSAGE_IDS:
            raise ValueError("full-pool contract must freeze the authoritative three message IDs")
        if self.message_snapshot_sha256 != FULL_POOL_AUTHORITATIVE_MESSAGES_SHA256:
            raise ValueError("full-pool contract message snapshot hash is not authoritative")
        if self.seed_top_k_per_proxy > self.per_message_capacity:
            raise ValueError("seed top-k cannot exceed per-message delivery capacity")
        if not (self.per_message_capacity * (self.horizon - 1) < self.eligible_user_count):
            raise ValueError("full-pool schedule must fill every non-final batch")
        if self.eligible_user_count > self.per_message_capacity * self.horizon:
            raise ValueError("full-pool schedule cannot deliver every eligible user")
        final_batch_count = self.eligible_user_count - self.per_message_capacity * (self.horizon - 1)
        expected_pairs = self.eligible_user_count * len(self.message_ids)
        expected_candidates = len(self.message_ids) * (
            self.horizon * self.eligible_user_count
            - self.per_message_capacity * self.horizon * (self.horizon - 1) // 2
        )
        computed = {
            "expected_eligible_pairs": expected_pairs,
            "expected_exposures": expected_pairs,
            "expected_primary_terminals": expected_pairs,
            "expected_committed_batches": self.horizon,
            "expected_candidate_ranking_rows": expected_candidates,
            "expected_final_batch_pairs_per_message": final_batch_count,
        }
        for field_name, expected in computed.items():
            if getattr(self, field_name) != expected:
                raise ValueError(f"{field_name} does not close the full-pool schedule")

        if self.profile == "deterministic_validation":
            expected_validation = {
                "validation_token": FULL_POOL_VALIDATION_TOKEN,
                "dataset_identity": FULL_POOL_VALIDATION_DATASET_IDENTITY,
                "eligible_user_set_identity": FULL_POOL_VALIDATION_USER_SET_IDENTITY,
            }
            for field_name, expected in expected_validation.items():
                if getattr(self, field_name) != expected:
                    raise ValueError(f"Validation contract {field_name} does not match the frozen token")
            if not _VALIDATION_OUTPUT_IDENTITY_PATTERN.fullmatch(self.output_identity):
                raise ValueError("Validation output_identity must remain distinct from production Full-Pool identities")
        else:
            expected_production: dict[str, object] = {
                "validation_token": None,
                "dataset_identity": FULL_POOL_PRODUCTION_DATASET_IDENTITY,
                "eligible_user_set_identity": FULL_POOL_PRODUCTION_USER_SET_IDENTITY,
                "eligible_user_ids_sha256": FULL_POOL_PRODUCTION_USER_IDS_SHA256,
                "eligible_user_count": FULL_POOL_PRODUCTION_USER_COUNT,
                "horizon": FULL_POOL_PRODUCTION_HORIZON,
                "per_message_capacity": FULL_POOL_PRODUCTION_CAPACITY,
                "seed_top_k_per_proxy": 10,
                "expected_eligible_pairs": FULL_POOL_PRODUCTION_ELIGIBLE_PAIRS,
                "expected_exposures": FULL_POOL_PRODUCTION_ELIGIBLE_PAIRS,
                "expected_primary_terminals": FULL_POOL_PRODUCTION_ELIGIBLE_PAIRS,
                "expected_committed_batches": FULL_POOL_PRODUCTION_HORIZON,
                "expected_candidate_ranking_rows": FULL_POOL_PRODUCTION_CANDIDATE_ROWS,
                "expected_final_batch_pairs_per_message": FULL_POOL_PRODUCTION_FINAL_BATCH_PAIRS_PER_MESSAGE,
            }
            for field_name, expected in expected_production.items():
                if getattr(self, field_name) != expected:
                    raise ValueError(f"production contract {field_name} does not match the frozen Full-Pool fact")
            if not _PRODUCTION_OUTPUT_IDENTITY_PATTERN.fullmatch(self.output_identity):
                raise ValueError("production output_identity does not match the frozen Full-Pool identity")
        execution = self.formal_execution
        if execution is not None:
            authorization = execution.authorization
            crossed = {
                "output_identity": self.output_identity,
                "dataset_identity": self.dataset_identity,
                "eligible_user_ids_sha256": self.eligible_user_ids_sha256,
                "message_snapshot_sha256": self.message_snapshot_sha256,
            }
            for field_name, expected_value in crossed.items():
                if getattr(authorization, field_name) != expected_value:
                    raise ValueError(f"Formal authorization {field_name} is crossed with the Full-Pool contract")
            if execution.source_root.name != self.output_identity:
                raise ValueError("Formal execution source path is crossed with output_identity")
            if any(
                artifact_path == self.dataset_dir or artifact_path.is_relative_to(self.dataset_dir)
                for artifact_path in (
                    execution.authorization.artifact_path,
                    execution.qualification.artifact_path,
                    execution.qualification.observed_response_artifact_path,
                )
            ):
                raise ValueError("Formal authorization artifacts must remain outside dataset_dir")
            if self.profile == "deterministic_validation" and execution.evidence_profile != "deterministic_validation_fixture":
                raise ValueError("Validation Full-Pool contract cannot carry live Formal authorization")
            if self.profile == "production" and execution.evidence_profile != "formal_live":
                raise ValueError("production Full-Pool contract requires live Formal authorization")
        return self


class FullPoolRunResult(_FrozenContractModel):
    status: FullPoolRunStatus
    workspace_root: Path
    source_root: Path | None
    source_identity: str | None
    manifest_sha256: str | None
    logical_adapter_decisions: int = Field(ge=0)
    physical_provider_attempts: int = Field(default=0, ge=0)
    provider_calls: int = Field(ge=0)
    live_api_triggered: bool
    production_deploy_eligible: bool

    @field_validator("manifest_sha256")
    @classmethod
    def _result_manifest_hash(cls, value: str | None) -> str | None:
        if value is not None and not _SHA256_PATTERN.fullmatch(value):
            raise ValueError("result manifest_sha256 is invalid")
        return value

    @model_validator(mode="after")
    def _validate_result_state(self) -> FullPoolRunResult:
        source_fields = (self.source_root, self.source_identity, self.manifest_sha256)
        if self.status is FullPoolRunStatus.COMPLETE and any(value is None for value in source_fields):
            raise ValueError("complete Full-Pool result requires a closed source identity")
        if self.status is not FullPoolRunStatus.COMPLETE and any(value is not None for value in source_fields):
            raise ValueError("partial Full-Pool result cannot expose a final source identity")
        if self.production_deploy_eligible and self.status is not FullPoolRunStatus.COMPLETE:
            raise ValueError("partial Full-Pool result cannot be production eligible")
        return self


class _SourceAccumulator:
    def __init__(self, contract: FullPoolExperimentContract, *, expected_user_ids: set[str]) -> None:
        self.contract = contract
        self.expected_user_ids = expected_user_ids
        self.seen_pairs: set[tuple[str, str]] = set()
        self.seen_terminal_ids: set[str] = set()
        self.coverage_by_user: Counter[str] = Counter()
        self.candidate_count = 0
        self.pair_count = 0
        self.terminal_count = 0
        self.provider_failed_count = 0
        self.candidates_per_message: Counter[str] = Counter()
        self.pairs_per_message: Counter[str] = Counter()
        self.terminals_per_message: Counter[str] = Counter()
        self.provider_failed_per_message: Counter[str] = Counter()
        self.batch_diagnostics: list[dict[str, object]] = []
        self.cumulative_positive_user_ids: set[str] = set()

    def consume_batch(
        self,
        *,
        time_step: int,
        commit: Mapping[str, object],
        candidate_rows: Sequence[Mapping[str, object]],
        pair_rows: Sequence[Mapping[str, object]],
        terminal_rows: Sequence[Mapping[str, object]],
        expected_seed_user_ids: set[str],
    ) -> None:
        if time_step != len(self.batch_diagnostics):
            raise ValueError("source batches are missing, extra, or out of order")
        frozen = _string_list(commit.get("frozen_campaign_engaged_user_ids"), "frozen campaign users")
        if frozen != sorted(self.cumulative_positive_user_ids):
            raise ValueError("batch ranking context does not use the previous full-batch feedback set")
        committed = _string_list(commit.get("committed_primary_positive_user_ids"), "committed Primary users")

        candidates_by_message: dict[str, list[Mapping[str, object]]] = defaultdict(list)
        pairs_by_message: dict[str, list[Mapping[str, object]]] = defaultdict(list)
        terminals_by_pair: dict[str, Mapping[str, object]] = {}
        for row in candidate_rows:
            message_id = _message_id(row)
            _require_time_step(row, time_step, "candidate")
            candidates_by_message[message_id].append(row)
        for row in pair_rows:
            message_id = _message_id(row)
            _require_time_step(row, time_step, "pair")
            pairs_by_message[message_id].append(row)
        for row in terminal_rows:
            _require_time_step(row, time_step, "terminal")
            if row.get("decision_variant") != "primary":
                raise ValueError("Full-Pool source contains a non-Primary terminal")
            pair_id = _non_empty(row.get("pair_id"), "terminal pair_id")
            terminal_id = _non_empty(row.get("terminal_row_id"), "terminal_row_id")
            if terminal_id in self.seen_terminal_ids or pair_id in terminals_by_pair:
                raise ValueError("Full-Pool source contains duplicate terminal identity")
            self.seen_terminal_ids.add(terminal_id)
            terminals_by_pair[pair_id] = row

        expected_candidate_count = self.contract.eligible_user_count - time_step * self.contract.per_message_capacity
        expected_selected_count = (
            self.contract.per_message_capacity
            if time_step < self.contract.horizon - 1
            else self.contract.expected_final_batch_pairs_per_message
        )
        selected_pairs_per_message: dict[str, int] = {}
        candidate_rows_per_message: dict[str, int] = {}
        batch_positive_user_ids: set[str] = set()
        seed_ids_by_message: list[set[str]] = []

        for message_id in self.contract.message_ids:
            message_candidates = candidates_by_message.get(message_id, [])
            message_pairs = pairs_by_message.get(message_id, [])
            if len(message_candidates) != expected_candidate_count:
                raise ValueError(f"{message_id} batch {time_step} candidate count does not close the ranking queue")
            if len(message_pairs) != expected_selected_count:
                raise ValueError(f"{message_id} batch {time_step} selected count does not close delivery capacity")
            positions = [int(cast(int | str, row.get("ranking_position"))) for row in message_candidates]
            if positions != list(range(1, len(message_candidates) + 1)):
                raise ValueError(f"{message_id} batch {time_step} ranking positions are not canonical")
            selected_candidate_ids = {
                _non_empty(row.get("user_id"), "candidate user_id")
                for row in message_candidates
                if _csv_boolean(row.get("selected"), "candidate selected")
            }
            pair_user_ids = {_non_empty(row.get("user_id"), "pair user_id") for row in message_pairs}
            if selected_candidate_ids != pair_user_ids:
                raise ValueError("selected candidate rows do not match exposed pair rows")
            if time_step == 0:
                seed_ids = {
                    _non_empty(row.get("user_id"), "seed user_id")
                    for row in message_pairs
                    if row.get("selection_reason") == "seed_union"
                }
                if seed_ids != expected_seed_user_ids:
                    raise ValueError("Batch 0 does not begin with the complete shared seed union")
                seed_ids_by_message.append(seed_ids)

            for row in message_pairs:
                user_id = _non_empty(row.get("user_id"), "pair user_id")
                if user_id not in self.expected_user_ids:
                    raise ValueError("pair row contains a user outside the complete eligible pool")
                key = (user_id, message_id)
                if key in self.seen_pairs:
                    raise ValueError("user × message pair was exposed more than once")
                self.seen_pairs.add(key)
                self.coverage_by_user[user_id] += 1
                pair_id = _non_empty(row.get("pair_id"), "pair_id")
                terminal = terminals_by_pair.get(pair_id)
                if terminal is None:
                    raise ValueError("pair row does not have exactly one Primary terminal")
                if terminal.get("user_id") != user_id or terminal.get("message_id") != message_id:
                    raise ValueError("Primary terminal identity is crossed with its pair")
                if terminal.get("terminal_status") != row.get("primary_status"):
                    raise ValueError("Primary terminal status is crossed with its pair")
                terminal_status = str(terminal.get("terminal_status"))
                action = str(terminal.get("action"))
                positive = terminal_status == "succeeded" and action in CONCURRENT_MESSAGE_POSITIVE_ACTIONS
                feedback_flag = _csv_boolean(row.get("campaign_feedback_committed"), "campaign feedback flag")
                if feedback_flag != positive:
                    raise ValueError("only succeeded positive Primary terminals may commit campaign feedback")
                if positive:
                    batch_positive_user_ids.add(user_id)
                if terminal_status == "provider_failed":
                    self.provider_failed_count += 1
                    self.provider_failed_per_message[message_id] += 1

            self.candidate_count += len(message_candidates)
            self.pair_count += len(message_pairs)
            self.terminal_count += len(message_pairs)
            self.candidates_per_message[message_id] += len(message_candidates)
            self.pairs_per_message[message_id] += len(message_pairs)
            self.terminals_per_message[message_id] += len(message_pairs)
            selected_pairs_per_message[message_id] = len(message_pairs)
            candidate_rows_per_message[message_id] = len(message_candidates)

        if time_step == 0 and not all(seed_ids == seed_ids_by_message[0] for seed_ids in seed_ids_by_message):
            raise ValueError("Batch 0 seed identity differs across message rankings")
        if set(terminals_by_pair) != {_non_empty(row.get("pair_id"), "pair_id") for row in pair_rows}:
            raise ValueError("batch terminal denominator does not match exposed pairs")
        if committed != sorted(batch_positive_user_ids):
            raise ValueError("batch commit does not deduplicate the succeeded Primary-positive user set")

        self.cumulative_positive_user_ids.update(batch_positive_user_ids)
        self.batch_diagnostics.append(
            {
                "time_step": time_step,
                "candidate_rows_per_message": candidate_rows_per_message,
                "selected_pairs_per_message": selected_pairs_per_message,
                "frozen_campaign_engaged_user_ids": frozen,
                "committed_primary_positive_user_ids": committed,
            }
        )

    def close(self) -> tuple[dict[str, object], dict[str, object]]:
        contract = self.contract
        expected_pairs = {(user_id, message_id) for user_id in self.expected_user_ids for message_id in contract.message_ids}
        if self.seen_pairs != expected_pairs:
            raise ValueError("closed source does not expose the complete eligible user × message pool")
        if self.candidate_count != contract.expected_candidate_ranking_rows:
            raise ValueError("candidate ranking rows do not close the scaled full-pool formula")
        if self.pair_count != contract.expected_exposures or self.terminal_count != contract.expected_primary_terminals:
            raise ValueError("pair or terminal rows do not close the full-pool denominator")
        coverage_distribution = dict(sorted(Counter(self.coverage_by_user.values()).items()))
        if coverage_distribution != {len(contract.message_ids): contract.eligible_user_count}:
            raise ValueError("every Full-Pool user must receive all three authoritative messages")

        counts = {
            "candidate_ranking_rows": self.candidate_count,
            "committed_batches": len(self.batch_diagnostics),
            "distinct_users": len(self.coverage_by_user),
            "eligible_pairs": contract.expected_eligible_pairs,
            "exposures": self.pair_count,
            "primary_terminals": self.terminal_count,
            "provider_failed_terminals": self.provider_failed_count,
            "below_delivery_capacity_pairs": contract.expected_eligible_pairs - self.pair_count,
        }
        per_message = {
            message_id: {
                "candidate_ranking_rows": self.candidates_per_message[message_id],
                "exposures": self.pairs_per_message[message_id],
                "primary_terminals": self.terminals_per_message[message_id],
                "provider_failed_terminals": self.provider_failed_per_message[message_id],
                "below_delivery_capacity_pairs": contract.eligible_user_count - self.pairs_per_message[message_id],
            }
            for message_id in contract.message_ids
        }
        aggregates = {
            "schema_version": FULL_POOL_AGGREGATES_SCHEMA,
            "counts": counts,
            "per_message": per_message,
            "provider_calls": 0,
            "live_api_triggered": False,
            "production_deploy_eligible": False,
        }
        diagnostics = {
            "schema_version": FULL_POOL_DIAGNOSTICS_SCHEMA,
            "membership": {
                "sampling_method": FULL_POOL_MEMBERSHIP_METHOD,
                "membership_filtering_applied": False,
                "seed_first_quota_filtering_applied": False,
            },
            "schedule": {
                "ranking_formula": CONCURRENT_MESSAGE_RANKING_FORMULA,
                "feedback_formula": CONCURRENT_MESSAGE_ENGAGED_NEIGHBOR_FORMULA,
                "per_message_capacity": contract.per_message_capacity,
                "final_batch_pairs_per_message": contract.expected_final_batch_pairs_per_message,
                "ranking_determines_batch_and_order_only": True,
            },
            "coverage": {
                "per_user_message_count_distribution": {
                    str(key): value for key, value in coverage_distribution.items()
                },
                "complete_message_coverage": len(contract.message_ids),
            },
            "feedback": {
                "positive_actions": sorted(CONCURRENT_MESSAGE_POSITIVE_ACTIONS),
                "requires_terminal_status": "succeeded",
                "campaign_user_id_deduplicated": True,
                "full_batch_barrier": True,
                "next_batch_only": True,
                "ignore_propagates": False,
                "provider_failed_propagates": False,
                "shadow_present": False,
            },
            "batches": self.batch_diagnostics,
        }
        return aggregates, diagnostics


class _FullPoolCapExhausted(RuntimeError):
    pass


class _FullPoolReconciliationRequired(RuntimeError):
    pass


@dataclass(frozen=True)
class _AttemptProgress:
    logical_judgments: int
    physical_attempts: int
    provider_responses: int
    successful_decisions: int
    observed_model_counts: dict[str, int]
    usage_complete_response_count: int
    usage_missing_response_count: int
    usage_malformed_response_count: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cached_input_tokens: int


class _FullPoolAttemptGuard:
    """Private durable guard for one frozen Full-Pool execution contract."""

    def __init__(
        self,
        *,
        contract: FullPoolExperimentContract,
        adapter: OpenAICompatibleDecisionAdapter,
        workspace: Path,
    ) -> None:
        execution = contract.formal_execution
        if execution is None:
            raise ValueError("Formal attempt guard requires an execution contract")
        self.contract = contract
        self.execution = execution
        self.adapter = adapter
        self.workspace = workspace
        self.external_baseline = adapter.external_request_invocations
        self.logical_judgments = 0
        self.physical_attempts = 0
        self.provider_responses = 0
        self.successful_decisions = 0
        self.observed_model_counts: Counter[str] = Counter()
        self.usage_complete_response_count = 0
        self.usage_missing_response_count = 0
        self.usage_malformed_response_count = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0
        self.cached_input_tokens = 0
        self.sequence = 0
        self.previous_checksum: str | None = None
        self.pending_pair_id: str | None = None
        self.persisted_status: dict[str, object] | None = None
        self._opened = False

    @property
    def identity_path(self) -> Path:
        return self.workspace / _FORMAL_EXECUTION_IDENTITY_FILE

    @property
    def status_path(self) -> Path:
        return self.workspace / _FORMAL_EXECUTION_STATUS_FILE

    @property
    def ledger_path(self) -> Path:
        return self.workspace / _FORMAL_ATTEMPT_LEDGER_FILE

    def before(self, judgment: Mapping[str, object]) -> None:
        self._open()
        if self.pending_pair_id is not None:
            raise RuntimeError("Formal attempt guard already has a reserved judgment")
        pair_id = _non_empty(judgment.get("pair_id"), "Formal judgment pair_id")
        max_attempts = self.execution.request_contract.max_retries + 1
        reserved_logical = self.logical_judgments + 1
        reserved_physical = self.physical_attempts + max_attempts
        if (
            reserved_logical > self.execution.active_logical_judgment_cap
            or reserved_physical > self.execution.active_physical_attempt_cap
        ):
            if self.persisted_status == {
                "schema_version": _FORMAL_EXECUTION_STATUS_SCHEMA,
                "lifecycle": "resumable_cap_stop",
                "execution_contract_sha256": _sha256_json(self.execution.model_dump(mode="json")),
                "logical_judgments": self.logical_judgments,
                "physical_attempts": self.physical_attempts,
                "reserved_logical_judgments": reserved_logical,
                "reserved_physical_attempts": reserved_physical,
                "last_pair_id": pair_id,
                "production_deploy_eligible": False,
            }:
                raise _FullPoolCapExhausted("next Full-Pool judgment still exceeds the frozen active cap")
            self._append(
                "cap_stop",
                {
                    "pair_id": pair_id,
                    "reserved_logical_judgments": reserved_logical,
                    "reserved_physical_attempts": reserved_physical,
                },
            )
            self._write_status(
                lifecycle="resumable_cap_stop",
                last_pair_id=pair_id,
                reserved_logical_judgments=reserved_logical,
                reserved_physical_attempts=reserved_physical,
            )
            raise _FullPoolCapExhausted("next Full-Pool judgment would exceed the frozen active cap")
        self.pending_pair_id = pair_id
        self._append(
            "judgment_reserved",
            {
                "pair_id": pair_id,
                "reserved_logical_judgments": reserved_logical,
                "reserved_physical_attempts": reserved_physical,
                "maximum_physical_attempts": max_attempts,
            },
        )
        self._write_status(
            lifecycle="attempt_reserved",
            last_pair_id=pair_id,
            reserved_logical_judgments=reserved_logical,
            reserved_physical_attempts=reserved_physical,
        )

    def validate_terminal(self, evidence: Mapping[str, object]) -> None:
        if self.pending_pair_id is None or evidence.get("pair_id") != self.pending_pair_id:
            raise ValueError("Formal terminal identity is crossed with the reserved judgment")
        requests = _strict_non_negative_int(evidence.get("request_invocations"), "terminal request invocations")
        responses = _strict_non_negative_int(evidence.get("provider_response_count"), "terminal responses")
        successes = _strict_non_negative_int(evidence.get("successful_decision_count"), "terminal successes")
        if not 1 <= requests <= self.execution.request_contract.max_retries + 1:
            raise ValueError("Formal terminal physical attempts exceed the retry contract")
        if not requests >= responses >= successes or successes not in {0, 1}:
            raise ValueError("Formal terminal accounting violates invocations >= responses >= successes")
        observed_raw = evidence.get("observed_model_counts")
        if not isinstance(observed_raw, Mapping):
            raise ValueError("Formal terminal observed-model accounting is missing")
        observed_counts = {
            str(model): _strict_non_negative_int(count, "observed-model count")
            for model, count in observed_raw.items()
        }
        missing = _strict_non_negative_int(
            evidence.get("observed_model_missing_response_count"), "missing observed models"
        )
        malformed = _strict_non_negative_int(
            evidence.get("observed_model_malformed_response_count"), "malformed observed models"
        )
        if missing or malformed or sum(observed_counts.values()) != responses:
            raise ValueError("Formal terminal responses require complete observed-model identity")
        if set(observed_counts) - {self.execution.required_observed_model}:
            raise ValueError("Formal terminal observed model drifted from fresh qualification")
        usage_complete = evidence.get("usage_complete") is True
        complete_count = _strict_non_negative_int(
            evidence.get("usage_complete_response_count"), "complete usage responses"
        )
        usage_missing = _strict_non_negative_int(
            evidence.get("usage_missing_response_count"), "missing usage responses"
        )
        usage_malformed = _strict_non_negative_int(
            evidence.get("usage_malformed_response_count"), "malformed usage responses"
        )
        if responses > 0 and (
            not usage_complete
            or complete_count != responses
            or usage_missing != 0
            or usage_malformed != 0
        ):
            raise ValueError("Formal terminal responses require complete token usage")
        if responses == 0 and (complete_count != 0 or usage_complete):
            raise ValueError("provider_failed terminal cannot claim complete response usage")
        if usage_complete:
            input_tokens = _strict_non_negative_int(evidence.get("input_usage"), "input usage")
            output_tokens = _strict_non_negative_int(evidence.get("output_usage"), "output usage")
            total_tokens = _strict_non_negative_int(evidence.get("total_usage"), "total usage")
            cached_tokens = _strict_non_negative_int(evidence.get("cached_input_usage"), "cached input usage")
            if output_tokens > self.execution.request_contract.output_token_ceiling:
                raise ValueError("Formal terminal output usage exceeds the frozen ceiling")
            if total_tokens != input_tokens + output_tokens or cached_tokens > input_tokens:
                raise ValueError("Formal terminal usage totals are crossed")
        external_delta = self.adapter.external_request_invocations - self.external_baseline
        if external_delta < 0:
            raise ValueError("Formal Adapter external request counter moved backwards")
        if self.execution.evidence_profile == "deterministic_validation_fixture" and external_delta != 0:
            raise ValueError("Formal-shaped Validation Adapter triggered an external request")
        if self.execution.evidence_profile == "formal_live" and external_delta != self.adapter.request_invocations:
            raise ValueError("Formal live physical and external request accounting diverged")

    def after(self, evidence: Mapping[str, object]) -> None:
        self.validate_terminal(evidence)
        assert self.pending_pair_id is not None
        pair_id = self.pending_pair_id
        requests = _strict_non_negative_int(evidence.get("request_invocations"), "terminal request invocations")
        terminal_status = "succeeded" if evidence.get("successful_decision_count") == 1 else "provider_failed"
        for attempt_index in range(1, requests + 1):
            self._append(
                "physical_attempt_accounted",
                {
                    "pair_id": pair_id,
                    "attempt_index": attempt_index,
                    "attempt_outcome": (
                        f"terminal_{terminal_status}" if attempt_index == requests else "retry_consumed"
                    ),
                },
            )
        accounting = {
            field_name: evidence.get(field_name)
            for field_name in (
                "request_invocations",
                "provider_response_count",
                "successful_decision_count",
                "observed_model_counts",
                "observed_model_missing_response_count",
                "observed_model_malformed_response_count",
                "usage_complete",
                "usage_complete_response_count",
                "usage_missing_response_count",
                "usage_malformed_response_count",
                "input_usage",
                "output_usage",
                "total_usage",
                "cached_input_usage",
            )
        }
        self._append(
            "judgment_terminal",
            {
                "pair_id": pair_id,
                "terminal_status": terminal_status,
                "accounting": accounting,
            },
        )
        self._consume_accounting(accounting)
        self.pending_pair_id = None
        self._write_status(
            lifecycle="running",
            last_pair_id=pair_id,
            reserved_logical_judgments=self.logical_judgments,
            reserved_physical_attempts=self.physical_attempts,
        )

    def reconcile_runtime(self, replay: Mapping[str, object]) -> None:
        self._open()
        status = replay.get("status")
        records = replay.get("records")
        if not isinstance(status, Mapping) or not isinstance(records, Sequence):
            raise ValueError("Formal runtime replay is missing status or active records")
        if status.get("inflight_unknown") is True:
            raise _FullPoolReconciliationRequired(
                "dispatched Full-Pool request has no verifiable response provenance"
            )
        if self.pending_pair_id is None:
            return
        pending_pair_id = self.pending_pair_id
        started = False
        terminal_evidence: Mapping[str, object] | None = None
        for raw_record in records:
            if not isinstance(raw_record, Mapping) or raw_record.get("record_type") != "event":
                continue
            event_identity = raw_record.get("event_identity")
            if not isinstance(event_identity, Mapping) or event_identity.get("pair_id") != pending_pair_id:
                continue
            if raw_record.get("event_type") == "variant_started":
                started = True
            elif raw_record.get("event_type") == "variant_terminal":
                payload = raw_record.get("payload")
                if not isinstance(payload, Mapping) or not isinstance(payload.get("variant_evidence"), Mapping):
                    raise ValueError("durable terminal is missing Formal variant evidence")
                terminal_evidence = cast(Mapping[str, object], payload["variant_evidence"])
        if terminal_evidence is not None:
            self.after(terminal_evidence)
            return
        if started:
            raise _FullPoolReconciliationRequired(
                "started Full-Pool request lacks a durable terminal and cannot be replayed"
            )
        self._append("reservation_released", {"pair_id": pending_pair_id, "reason": "no_dispatch_evidence"})
        self.pending_pair_id = None
        self._write_status(
            lifecycle="running",
            last_pair_id=pending_pair_id,
            reserved_logical_judgments=self.logical_judgments,
            reserved_physical_attempts=self.physical_attempts,
        )

    def mark_interrupted(self, *, reconciliation_required: bool) -> None:
        self._open()
        self._write_status(
            lifecycle=("reconciliation_required" if reconciliation_required else "resumable_interruption"),
            last_pair_id=self.pending_pair_id,
            reserved_logical_judgments=self.logical_judgments + (1 if self.pending_pair_id is not None else 0),
            reserved_physical_attempts=(
                self.physical_attempts + self.execution.request_contract.max_retries + 1
                if self.pending_pair_id is not None
                else self.physical_attempts
            ),
        )

    def ready_to_close(self) -> None:
        self._open()
        if self.pending_pair_id is not None:
            raise RuntimeError("Formal source cannot close with a pending attempt reservation")
        if self.logical_judgments != self.contract.expected_primary_terminals:
            raise ValueError("Formal attempt ledger does not close the logical judgment denominator")
        self._write_status(
            lifecycle="ready_to_close",
            last_pair_id=None,
            reserved_logical_judgments=self.logical_judgments,
            reserved_physical_attempts=self.physical_attempts,
        )

    def progress(self) -> _AttemptProgress:
        return _AttemptProgress(
            logical_judgments=self.logical_judgments,
            physical_attempts=self.physical_attempts,
            provider_responses=self.provider_responses,
            successful_decisions=self.successful_decisions,
            observed_model_counts=dict(sorted(self.observed_model_counts.items())),
            usage_complete_response_count=self.usage_complete_response_count,
            usage_missing_response_count=self.usage_missing_response_count,
            usage_malformed_response_count=self.usage_malformed_response_count,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            total_tokens=self.total_tokens,
            cached_input_tokens=self.cached_input_tokens,
        )

    def provider_accounting(self) -> dict[str, object]:
        progress = self.progress()
        return {
            "schema_version": "full-pool-formal-provider-accounting-v1",
            "logical_judgments": progress.logical_judgments,
            "physical_attempts": progress.physical_attempts,
            "provider_responses": progress.provider_responses,
            "successful_decisions": progress.successful_decisions,
            "observed_model_counts": progress.observed_model_counts,
            "usage_complete_response_count": progress.usage_complete_response_count,
            "usage_missing_response_count": progress.usage_missing_response_count,
            "usage_malformed_response_count": progress.usage_malformed_response_count,
            "input_tokens": progress.input_tokens,
            "output_tokens": progress.output_tokens,
            "total_tokens": progress.total_tokens,
            "cached_input_tokens": progress.cached_input_tokens,
            "external_request_invocations": (
                0
                if self.execution.evidence_profile == "deterministic_validation_fixture"
                else progress.physical_attempts
            ),
            "subscription_billed_cost_usd": self.execution.subscription_billed_cost_usd,
        }

    def _open(self) -> None:
        if self._opened:
            return
        if not self.workspace.is_dir() or self.workspace.is_symlink():
            raise ValueError("Formal operational workspace is not a real directory")
        identity = _formal_execution_identity(self.contract)
        if self.identity_path.exists():
            if _read_json_object(self.identity_path) != identity:
                raise ValueError("Formal operational execution identity is crossed")
            self._replay_ledger()
            status = _read_json_object(self.status_path)
            self.persisted_status = status
            if (
                status.get("schema_version") != _FORMAL_EXECUTION_STATUS_SCHEMA
                or status.get("execution_contract_sha256")
                != _sha256_json(self.execution.model_dump(mode="json"))
                or status.get("logical_judgments") != self.logical_judgments
                or status.get("physical_attempts") != self.physical_attempts
            ):
                raise ValueError("Formal operational status is crossed with the durable attempt ledger")
        else:
            _atomic_write_json_file(self.identity_path, identity)
            self._write_status(
                lifecycle="initialized",
                last_pair_id=None,
                reserved_logical_judgments=0,
                reserved_physical_attempts=0,
            )
        self._opened = True

    def _replay_ledger(self) -> None:
        if not self.ledger_path.exists():
            return
        pending: str | None = None
        pending_physical_attempts = 0
        expected_execution_hash = _sha256_json(self.execution.model_dump(mode="json"))
        with self.ledger_path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                raw = line.strip()
                if not raw:
                    continue
                value = json.loads(raw)
                if not isinstance(value, Mapping):
                    raise ValueError(f"Formal attempt ledger line {line_number} is not an object")
                record = dict(value)
                checksum = _non_empty(record.pop("checksum", None), "Formal attempt ledger checksum")
                if (
                    record.get("schema_version") != _FORMAL_ATTEMPT_LEDGER_SCHEMA
                    or record.get("execution_contract_sha256") != expected_execution_hash
                ):
                    raise ValueError("Formal attempt ledger schema or execution identity is crossed")
                if record.get("sequence") != self.sequence + 1 or record.get("previous_checksum") != self.previous_checksum:
                    raise ValueError("Formal attempt ledger sequence or checksum chain is broken")
                if _sha256_json(record) != checksum:
                    raise ValueError("Formal attempt ledger checksum mismatch")
                event_type = record.get("event_type")
                payload = record.get("payload")
                if not isinstance(payload, Mapping):
                    raise ValueError("Formal attempt ledger payload is invalid")
                if event_type == "judgment_reserved":
                    if pending is not None:
                        raise ValueError("Formal attempt ledger contains overlapping reservations")
                    pending = _non_empty(payload.get("pair_id"), "reserved pair_id")
                    pending_physical_attempts = 0
                elif event_type == "physical_attempt_accounted":
                    if _non_empty(payload.get("pair_id"), "physical attempt pair_id") != pending:
                        raise ValueError("Formal physical attempt is crossed with its reservation")
                    pending_physical_attempts += 1
                elif event_type == "judgment_terminal":
                    pair_id = _non_empty(payload.get("pair_id"), "terminal pair_id")
                    if pair_id != pending:
                        raise ValueError("Formal attempt ledger terminal is crossed with its reservation")
                    accounting = payload.get("accounting")
                    if not isinstance(accounting, Mapping):
                        raise ValueError("Formal attempt ledger terminal accounting is missing")
                    if pending_physical_attempts != _strict_non_negative_int(
                        accounting.get("request_invocations"), "ledger terminal request invocations"
                    ):
                        raise ValueError("Formal physical attempt rows do not close terminal accounting")
                    self._consume_accounting(accounting)
                    pending = None
                    pending_physical_attempts = 0
                elif event_type == "reservation_released":
                    if _non_empty(payload.get("pair_id"), "released reservation pair_id") != pending:
                        raise ValueError("released Formal reservation identity is crossed")
                    pending = None
                    pending_physical_attempts = 0
                elif event_type != "cap_stop":
                    raise ValueError("Formal attempt ledger event type is unsupported")
                self.sequence = int(cast(int, record["sequence"]))
                self.previous_checksum = checksum
        self.pending_pair_id = pending

    def _consume_accounting(self, accounting: Mapping[str, object]) -> None:
        self.logical_judgments += 1
        self.physical_attempts += _strict_non_negative_int(
            accounting.get("request_invocations"), "ledger request invocations"
        )
        self.provider_responses += _strict_non_negative_int(
            accounting.get("provider_response_count"), "ledger Provider responses"
        )
        self.successful_decisions += _strict_non_negative_int(
            accounting.get("successful_decision_count"), "ledger successful decisions"
        )
        observed = accounting.get("observed_model_counts")
        if not isinstance(observed, Mapping):
            raise ValueError("ledger observed-model accounting is invalid")
        for model, count in observed.items():
            self.observed_model_counts[str(model)] += _strict_non_negative_int(count, "ledger observed-model count")
        self.usage_complete_response_count += _strict_non_negative_int(
            accounting.get("usage_complete_response_count"), "ledger complete usage count"
        )
        self.usage_missing_response_count += _strict_non_negative_int(
            accounting.get("usage_missing_response_count"), "ledger missing usage count"
        )
        self.usage_malformed_response_count += _strict_non_negative_int(
            accounting.get("usage_malformed_response_count"), "ledger malformed usage count"
        )
        if accounting.get("usage_complete") is True:
            self.input_tokens += _strict_non_negative_int(accounting.get("input_usage"), "ledger input usage")
            self.output_tokens += _strict_non_negative_int(accounting.get("output_usage"), "ledger output usage")
            self.total_tokens += _strict_non_negative_int(accounting.get("total_usage"), "ledger total usage")
            self.cached_input_tokens += _strict_non_negative_int(
                accounting.get("cached_input_usage"), "ledger cached input usage"
            )

    def _append(self, event_type: str, payload: Mapping[str, object]) -> None:
        record = {
            "schema_version": _FORMAL_ATTEMPT_LEDGER_SCHEMA,
            "sequence": self.sequence + 1,
            "previous_checksum": self.previous_checksum,
            "execution_contract_sha256": _sha256_json(self.execution.model_dump(mode="json")),
            "event_type": event_type,
            "payload": dict(payload),
        }
        checksum = _sha256_json(record)
        serialized = _canonical_json({**record, "checksum": checksum})
        with self.ledger_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(serialized + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self.sequence += 1
        self.previous_checksum = checksum

    def _write_status(
        self,
        *,
        lifecycle: str,
        last_pair_id: str | None,
        reserved_logical_judgments: int,
        reserved_physical_attempts: int,
    ) -> None:
        payload = {
            "schema_version": _FORMAL_EXECUTION_STATUS_SCHEMA,
            "lifecycle": lifecycle,
            "execution_contract_sha256": _sha256_json(self.execution.model_dump(mode="json")),
            "logical_judgments": self.logical_judgments,
            "physical_attempts": self.physical_attempts,
            "reserved_logical_judgments": reserved_logical_judgments,
            "reserved_physical_attempts": reserved_physical_attempts,
            "last_pair_id": last_pair_id,
            "production_deploy_eligible": False,
        }
        _atomic_write_json_file(self.status_path, payload)
        self.persisted_status = payload


def _formal_execution_identity(contract: FullPoolExperimentContract) -> dict[str, object]:
    execution = contract.formal_execution
    if execution is None:
        raise ValueError("Formal operational identity requires an execution contract")
    return {
        "schema_version": _FORMAL_EXECUTION_IDENTITY_SCHEMA,
        "output_identity": contract.output_identity,
        "contract_sha256": _sha256_json(contract.model_dump(mode="json")),
        "execution_contract_sha256": _sha256_json(execution.model_dump(mode="json")),
        "authorization_artifact_sha256": execution.authorization.artifact_sha256,
        "qualification_artifact_sha256": execution.qualification.artifact_sha256,
        "operational_root": str(execution.operational_root),
        "source_root": str(execution.source_root),
        "candidate_root": str(execution.candidate_root),
        "production_deploy_eligible": False,
    }


def _strict_non_negative_int(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{context} must be a non-negative strict integer")
    return value


class FullPoolFormalExperiment:
    """Run one complete Full-Pool Validation trajectory behind a single high-level Interface."""

    def run(
        self,
        contract: FullPoolExperimentContract,
        adapter: LLMDecisionAdapter,
        output_dir: str | Path,
    ) -> FullPoolRunResult:
        frozen = _revalidate_contract(contract)
        execution = frozen.formal_execution
        if frozen.profile == "production" and execution is None:
            raise FullPoolExperimentError(
                FullPoolExperimentErrorCode.UNSUPPORTED_PROFILE,
                "production Full-Pool execution requires the frozen durable lifecycle contract",
            )
        try:
            output_path = _prepare_output_path(output_dir, frozen)
            if execution is not None:
                if output_path != execution.source_root:
                    raise ValueError("output_dir is crossed with the frozen Formal source root")
                if execution.candidate_root.exists() or execution.candidate_root.is_symlink():
                    raise FileExistsError("future Formal candidate root already exists before source closure")
                if execution.operational_root.exists() and (
                    execution.operational_root.is_symlink() or not execution.operational_root.is_dir()
                ):
                    raise ValueError("Formal operational root must be a real resumable directory")
        except FileExistsError as exc:
            existing = Path(output_dir).expanduser().resolve(strict=False)
            if existing.is_dir() and not existing.is_symlink():
                return _load_closed_source_result(frozen, existing)
            raise FullPoolExperimentError(FullPoolExperimentErrorCode.OUTPUT_CONFLICT, str(exc)) from exc
        except (OSError, ValueError) as exc:
            raise FullPoolExperimentError(
                FullPoolExperimentErrorCode.PATH_VIOLATION,
                "Full-Pool output path violates the explicit source identity",
            ) from exc
        if not isinstance(adapter, LLMDecisionAdapter):
            raise FullPoolExperimentError(
                FullPoolExperimentErrorCode.INVALID_ADAPTER,
                "FullPoolFormalExperiment requires one typed Primary Decision Adapter",
            )
        formal_adapter = _preflight_formal_adapter(frozen, adapter) if execution is not None else None

        external_baseline = _external_request_count(adapter)
        if external_baseline != 0:
            raise FullPoolExperimentError(
                FullPoolExperimentErrorCode.INVALID_ADAPTER,
                "Full-Pool Adapter must have zero prior external request invocations",
            )
        try:
            config, prepared, expected_user_ids = _prepare_runtime_inputs(frozen)
        except (OSError, TypeError, ValueError) as exc:
            raise FullPoolExperimentError(
                FullPoolExperimentErrorCode.INVALID_DATASET,
                "dataset membership or frozen Full-Pool identity failed before the first Adapter call",
            ) from exc

        logical_decisions = 0
        attempt_guard = (
            _FullPoolAttemptGuard(
                contract=frozen,
                adapter=formal_adapter,
                workspace=execution.operational_root,
            )
            if formal_adapter is not None and execution is not None
            else None
        )

        def before_judgment(judgment: Mapping[str, object]) -> None:
            nonlocal logical_decisions
            if attempt_guard is not None:
                attempt_guard.before(judgment)
            else:
                if _external_request_count(adapter) != external_baseline:
                    raise ValueError("Validation Adapter triggered an external request")
                logical_decisions += 1

        def validate_terminal(evidence: Mapping[str, object]) -> None:
            if attempt_guard is not None:
                attempt_guard.validate_terminal(evidence)
            elif _external_request_count(adapter) != external_baseline:
                raise ValueError("Validation Adapter triggered an external request")

        def after_judgment(evidence: Mapping[str, object]) -> None:
            nonlocal logical_decisions
            if attempt_guard is not None:
                attempt_guard.after(evidence)
                logical_decisions = attempt_guard.logical_judgments

        consumer = _PrimaryOnlyConcurrentRuntimeConsumer(
            config,
            adapter,
            expected_prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
            execution_contract=frozen.model_dump(mode="json"),
            expected_sample_identity=frozen.eligible_user_ids_sha256,
            prepared_inputs=prepared,
            before_logical_judgment=before_judgment,
            validate_terminal=validate_terminal,
            after_logical_judgment=after_judgment if attempt_guard is not None else None,
            before_resume_runtime=attempt_guard.reconcile_runtime if attempt_guard is not None else None,
        )
        workspace_preexists = bool(execution is not None and execution.operational_root.exists())
        try:
            spooled = (
                consumer._resume_to_spool(output_path)
                if workspace_preexists and execution is not None
                else consumer._run_new_to_spool(output_path)
            )
        except _FullPoolCapExhausted:
            assert attempt_guard is not None and execution is not None
            return FullPoolRunResult(
                status=FullPoolRunStatus.RESUMABLE,
                workspace_root=execution.operational_root,
                source_root=None,
                source_identity=None,
                manifest_sha256=None,
                logical_adapter_decisions=attempt_guard.logical_judgments,
                physical_provider_attempts=attempt_guard.physical_attempts,
                provider_calls=_external_request_count(adapter) - external_baseline,
                live_api_triggered=_external_request_count(adapter) > external_baseline,
                production_deploy_eligible=False,
            )
        except RuntimeError as exc:
            if attempt_guard is not None and execution is not None and execution.operational_root.is_dir():
                try:
                    replay = ConcurrentExecutionJournal.open_existing(execution.operational_root)._replay_runtime()
                    status = replay.get("status")
                    if not isinstance(status, Mapping):
                        raise ValueError("Formal interruption replay status is missing")
                    reconciliation_required = bool(status.get("inflight_unknown"))
                    attempt_guard.mark_interrupted(reconciliation_required=reconciliation_required)
                    return FullPoolRunResult(
                        status=(
                            FullPoolRunStatus.RECONCILIATION_REQUIRED
                            if reconciliation_required
                            else FullPoolRunStatus.RESUMABLE
                        ),
                        workspace_root=execution.operational_root,
                        source_root=None,
                        source_identity=None,
                        manifest_sha256=None,
                        logical_adapter_decisions=attempt_guard.logical_judgments,
                        physical_provider_attempts=attempt_guard.physical_attempts,
                        provider_calls=_external_request_count(adapter) - external_baseline,
                        live_api_triggered=_external_request_count(adapter) > external_baseline,
                        production_deploy_eligible=False,
                    )
                except (OSError, TypeError, ValueError, json.JSONDecodeError):
                    pass
            raise FullPoolExperimentError(
                FullPoolExperimentErrorCode.RUNTIME_FAILED,
                "Full-Pool runtime stopped without a final source",
            ) from exc
        except Exception as exc:
            raise FullPoolExperimentError(
                FullPoolExperimentErrorCode.RUNTIME_FAILED,
                "Full-Pool runtime or durable checkpoint failed closed",
            ) from exc
        if attempt_guard is not None:
            attempt_guard.ready_to_close()
            logical_decisions = attempt_guard.logical_judgments
        if logical_decisions != frozen.expected_primary_terminals:
            raise FullPoolExperimentError(
                FullPoolExperimentErrorCode.RUNTIME_FAILED,
                "Full-Pool Adapter accounting does not close the Primary terminal denominator",
            )
        if execution is None and _external_request_count(adapter) != external_baseline:
            raise FullPoolExperimentError(
                FullPoolExperimentErrorCode.RUNTIME_FAILED,
                "Full-Pool Validation Adapter triggered an external request",
            )

        provider_accounting = attempt_guard.provider_accounting() if attempt_guard is not None else None
        try:
            source_identity, manifest_sha256 = _close_full_pool_source(
                contract=frozen,
                output_path=output_path,
                spooled=spooled,
                expected_user_ids=expected_user_ids,
                expected_seed_user_ids=set(prepared.cohort.seed_user_ids),
                provider_accounting=provider_accounting,
            )
        except FileExistsError as exc:
            raise FullPoolExperimentError(FullPoolExperimentErrorCode.OUTPUT_CONFLICT, str(exc)) from exc
        except Exception as exc:
            raise FullPoolExperimentError(
                FullPoolExperimentErrorCode.SOURCE_CLOSURE_FAILED,
                "persisted Full-Pool spool failed atomic source closure",
            ) from exc
        closed_manifest = _read_json_object(output_path / _MANIFEST_FILE)
        physical_attempts = _strict_non_negative_int(
            closed_manifest.get("physical_provider_attempts"), "closed physical Provider attempts"
        )
        provider_calls = _strict_non_negative_int(closed_manifest.get("provider_calls"), "closed Provider calls")
        production_eligible = closed_manifest.get("production_deploy_eligible") is True
        return FullPoolRunResult(
            status=FullPoolRunStatus.COMPLETE,
            workspace_root=spooled.workspace_root,
            source_root=output_path,
            source_identity=source_identity,
            manifest_sha256=manifest_sha256,
            logical_adapter_decisions=logical_decisions,
            physical_provider_attempts=physical_attempts,
            provider_calls=provider_calls,
            live_api_triggered=provider_calls > 0,
            production_deploy_eligible=production_eligible,
        )


def _revalidate_contract(contract: object) -> FullPoolExperimentContract:
    if not isinstance(contract, FullPoolExperimentContract):
        raise FullPoolExperimentError(
            FullPoolExperimentErrorCode.INVALID_CONTRACT,
            "FullPoolFormalExperiment requires a typed immutable contract",
        )
    try:
        return FullPoolExperimentContract.model_validate(contract.model_dump(mode="python"))
    except ValidationError as exc:
        raise FullPoolExperimentError(
            FullPoolExperimentErrorCode.INVALID_CONTRACT,
            "Full-Pool contract contains missing, extra, or crossed facts",
        ) from exc


def _artifact_document(model: FullPoolFormalAuthorization | FullPoolFormalQualification) -> dict[str, object]:
    payload = model.model_dump(
        mode="json",
        exclude={"artifact_path", "artifact_sha256", "observed_response_artifact_path"},
    )
    if not isinstance(payload, dict):
        raise TypeError("Formal execution artifact must serialize to an object")
    return cast(dict[str, object], payload)


def _observed_model_evidence_document(execution: FullPoolFormalExecutionContract) -> dict[str, object]:
    return {
        "schema_version": FULL_POOL_FORMAL_OBSERVED_EVIDENCE_SCHEMA,
        "evidence_kind": (
            "deterministic_validation_fixture"
            if execution.evidence_profile == "deterministic_validation_fixture"
            else "provider_observed"
        ),
        "output_identity": execution.authorization.output_identity,
        "provider": execution.provider,
        "transport": execution.transport,
        "adapter_identity": execution.adapter_identity,
        "requested_model": execution.requested_model,
        "observed_model": execution.required_observed_model,
        "account_binding": execution.authorization.account_binding,
        "qualified_at_utc": execution.qualification.qualified_at_utc,
        "usage_complete": True,
        "raw_provider_payload_persisted": False,
    }


def _validate_formal_execution_artifacts(contract: FullPoolExperimentContract) -> None:
    execution = contract.formal_execution
    if execution is None:
        raise ValueError("Formal artifact validation requires an execution contract")
    for label, artifact in (
        ("authorization", execution.authorization),
        ("qualification", execution.qualification),
    ):
        _require_regular_file(artifact.artifact_path, f"Formal {label} artifact")
        if _sha256_file(artifact.artifact_path) != artifact.artifact_sha256:
            raise ValueError(f"Formal {label} artifact hash is crossed")
        if _read_json_object(artifact.artifact_path) != _artifact_document(artifact):
            raise ValueError(f"Formal {label} artifact content is crossed with the frozen contract")
    observed_path = execution.qualification.observed_response_artifact_path
    _require_regular_file(observed_path, "Formal observed-model evidence artifact")
    if (
        _sha256_file(observed_path) != execution.qualification.observed_response_sha256
        or _read_json_object(observed_path) != _observed_model_evidence_document(execution)
    ):
        raise ValueError("Formal observed-model evidence is crossed with fresh qualification")


def _request_contract_matches(
    actual: ProviderRequestContract,
    expected: FullPoolFormalRequestContract,
) -> bool:
    return actual.audit_record() == expected.model_dump(mode="python")


def _preflight_formal_adapter(
    contract: FullPoolExperimentContract,
    candidate: LLMDecisionAdapter,
) -> OpenAICompatibleDecisionAdapter:
    execution = contract.formal_execution
    if execution is None:
        raise FullPoolExperimentError(
            FullPoolExperimentErrorCode.INVALID_CONTRACT,
            "Formal Adapter preflight requires a frozen execution contract",
        )
    if type(candidate) is not OpenAICompatibleDecisionAdapter:
        raise FullPoolExperimentError(
            FullPoolExperimentErrorCode.INVALID_ADAPTER,
            "Formal Full-Pool execution requires the exact OpenAI-compatible Adapter identity",
        )
    adapter = candidate
    try:
        _validate_formal_execution_artifacts(contract)
        if getattr(adapter, "wrapped", None) is not None or getattr(adapter, "cache", None) is not None:
            raise ValueError("cached or wrapped Adapters are forbidden")
        if not _request_contract_matches(adapter.request_contract, execution.request_contract):
            raise ValueError("request contract is crossed")
        config = adapter.config
        if (
            not config.enabled
            or config.provider != execution.provider
            or config.require_live_env is not True
            or config.use_codex_provider_config is not False
            or config.base_url is not None
            or config.fail_closed_action.value != "raise"
            or adapter.prompt_version != execution.prompt_version
            or adapter.model != execution.requested_model
        ):
            raise ValueError("Adapter configuration is crossed")
        if adapter.request_invocations != 0 or adapter.external_request_invocations != 0:
            raise ValueError("Adapter is not a fresh decision store")
        accounting = adapter.provider_accounting
        if (
            accounting.external_request_invocations != 0
            or accounting.provider_response_count != 0
            or accounting.successful_decision_count != 0
            or accounting.observed_model_counts
            or accounting.observed_model_missing_response_count != 0
            or accounting.observed_model_malformed_response_count != 0
            or accounting.usage_complete_response_count != 0
            or accounting.usage_missing_response_count != 0
            or accounting.usage_malformed_response_count != 0
        ):
            raise ValueError("Adapter contains prior Provider accounting")
        client = adapter.client
        metadata = getattr(client, "safe_metadata", None)
        if not isinstance(metadata, Mapping):
            raise ValueError("Adapter client lacks safe transport metadata")
        expected_authentication = (
            "deterministic_validation_fixture"
            if execution.evidence_profile == "deterministic_validation_fixture"
            else "local_oauth_subscription"
        )
        if (
            metadata.get("provider_transport") != execution.transport
            or metadata.get("adapter_identity") != execution.adapter_identity
            or metadata.get("authentication") != expected_authentication
        ):
            raise ValueError("Adapter transport identity is crossed")
        if execution.evidence_profile == "deterministic_validation_fixture":
            if client is None or bool(getattr(client, "external_provider_client", False)):
                raise ValueError("Formal-shaped Validation requires an injected zero-call client")
        elif (
            type(client) is not PiSubscriptionProviderClient
            or not client.ready
            or not math.isclose(
                client.response_timeout_seconds,
                execution.request_contract.timeout_seconds,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
        ):
            raise ValueError("Formal live execution requires the ready, 30-second Pi OAuth subscription client")
    except (AttributeError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise FullPoolExperimentError(
            FullPoolExperimentErrorCode.INVALID_ADAPTER,
            "Formal Adapter, request, transport, or fresh-store preflight failed before the first call",
        ) from exc
    return adapter


def _load_closed_source_result(
    contract: FullPoolExperimentContract,
    source_root: Path,
) -> FullPoolRunResult:
    try:
        manifest = _read_json_object(source_root / _MANIFEST_FILE)
        source_identity = _non_empty(manifest.get("source_identity"), "closed Full-Pool source identity")
        _validate_staged_source(source_root, contract=contract, source_identity=source_identity)
        aggregates = _read_json_object(source_root / _AGGREGATES_FILE)
        accounting = aggregates.get("provider_accounting")
        if not isinstance(accounting, Mapping):
            raise ValueError("closed Full-Pool source is missing provider accounting")
        logical = _strict_non_negative_int(accounting.get("logical_judgments"), "closed logical judgments")
        physical = _strict_non_negative_int(accounting.get("physical_attempts"), "closed physical attempts")
        provider_calls = _strict_non_negative_int(manifest.get("provider_calls"), "closed Provider calls")
        workspace = (
            contract.formal_execution.operational_root
            if contract.formal_execution is not None
            else source_root.parent / f".{source_root.name}.operational"
        )
        return FullPoolRunResult(
            status=FullPoolRunStatus.COMPLETE,
            workspace_root=workspace,
            source_root=source_root,
            source_identity=source_identity,
            manifest_sha256=_sha256_file(source_root / _MANIFEST_FILE),
            logical_adapter_decisions=logical,
            physical_provider_attempts=physical,
            provider_calls=provider_calls,
            live_api_triggered=manifest.get("live_api_triggered") is True,
            production_deploy_eligible=manifest.get("production_deploy_eligible") is True,
        )
    except FullPoolExperimentError:
        raise
    except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise FullPoolExperimentError(
            FullPoolExperimentErrorCode.SOURCE_CLOSURE_FAILED,
            "existing Full-Pool source failed read-only immutable closure",
        ) from exc


def _prepare_output_path(output_dir: str | Path, contract: FullPoolExperimentContract) -> Path:
    output_path = Path(output_dir).expanduser()
    if output_path.name != contract.output_identity:
        raise ValueError("output directory basename is crossed with output_identity")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    parent = output_path.parent.resolve(strict=True)
    _require_real_directory(parent, "Full-Pool output parent")
    output_path = parent / output_path.name
    if output_path.exists() or output_path.is_symlink():
        raise FileExistsError(f"Full-Pool final source already exists: {output_path}")
    if output_path.resolve(strict=False).is_relative_to(contract.dataset_dir.resolve(strict=True)):
        raise ValueError("Full-Pool output must be outside dataset_dir")
    return output_path


def _prepare_runtime_inputs(
    contract: FullPoolExperimentContract,
) -> tuple[ConcurrentMessageExperimentConfig, Any, set[str]]:
    dataset_dir = contract.dataset_dir
    _require_real_directory(dataset_dir, "Full-Pool dataset")
    authoritative_hash = _sha256_json(
        [message.model_dump(mode="json") for message in authoritative_message_definitions()]
    )
    if authoritative_hash != FULL_POOL_AUTHORITATIVE_MESSAGES_SHA256:
        raise ValueError("authoritative message bytes drifted from the Full-Pool contract")
    expected_user_ids = _read_user_ids(dataset_dir / "users.csv")
    if len(expected_user_ids) != contract.eligible_user_count:
        raise ValueError("eligible user count is crossed with users.csv")
    if _sha256_json(sorted(expected_user_ids)) != contract.eligible_user_ids_sha256:
        raise ValueError("eligible user-set identity is crossed with users.csv")
    config = ConcurrentMessageExperimentConfig(
        dataset_dir=dataset_dir,
        sample_size=contract.eligible_user_count,
        horizon=contract.horizon,
        delivery_capacity=contract.per_message_capacity,
        configuration_profile="validation",
        report=ReportConfig(title="Full-Pool deterministic Validation"),
    )
    prepared = _prepare_full_pool_concurrent_runtime_inputs(
        config,
        seed_top_k_per_proxy=contract.seed_top_k_per_proxy,
    )
    prepared_user_ids = set(prepared.cohort.sample_user_ids)
    if prepared_user_ids != expected_user_ids:
        raise ValueError("Full-Pool preparation filtered or added eligible members")
    audit = prepared.cohort.sample_audit
    membership = audit.get("membership")
    if (
        prepared.cohort.sampling_method != FULL_POOL_MEMBERSHIP_METHOD
        or not isinstance(membership, Mapping)
        or membership.get("membership_filtering_applied") is not False
        or membership.get("seed_first_quota_filtering_applied") is not False
    ):
        raise ValueError("Full-Pool preparation did not close the no-membership-filter contract")
    return config, prepared, expected_user_ids


class _PersistedProviderAccounting:
    """Stream provider accounting from persisted Primary terminal rows."""

    def __init__(self, contract: FullPoolExperimentContract) -> None:
        self.contract = contract
        self.logical_judgments = 0
        self.physical_attempts = 0
        self.provider_responses = 0
        self.successful_decisions = 0
        self.observed_model_counts: Counter[str] = Counter()
        self.usage_complete_response_count = 0
        self.usage_missing_response_count = 0
        self.usage_malformed_response_count = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0
        self.cached_input_tokens = 0

    def consume(self, row: Mapping[str, object]) -> None:
        if row.get("decision_variant") != "primary":
            raise ValueError("Full-Pool Provider accounting contains a non-Primary terminal")
        requests = _strict_int_cell(row.get("request_invocations"), "persisted request invocations")
        responses = _strict_int_cell(row.get("provider_response_count"), "persisted Provider responses")
        successes = _strict_int_cell(row.get("successful_decision_count"), "persisted successful decisions")
        if not requests >= responses >= successes or requests < 1 or successes not in {0, 1}:
            raise ValueError("persisted terminal accounting violates invocations >= responses >= successes")
        terminal_status = row.get("terminal_status")
        if (terminal_status == "succeeded") != (successes == 1):
            raise ValueError("persisted terminal status is crossed with successful Decision accounting")
        observed = _json_object_cell(row.get("observed_model_counts"), "persisted observed-model counts")
        observed_counts = {
            str(model): _strict_int_cell(count, "persisted observed-model count")
            for model, count in observed.items()
        }
        missing = _strict_int_cell(
            row.get("observed_model_missing_response_count"), "persisted missing observed models"
        )
        malformed = _strict_int_cell(
            row.get("observed_model_malformed_response_count"), "persisted malformed observed models"
        )
        if sum(observed_counts.values()) + missing + malformed != responses:
            raise ValueError("persisted observed-model accounting does not cover Provider responses")
        usage_complete = _csv_boolean(row.get("usage_complete"), "persisted usage_complete")
        complete_count = _strict_int_cell(
            row.get("usage_complete_response_count"), "persisted complete usage count"
        )
        usage_missing = _strict_int_cell(
            row.get("usage_missing_response_count"), "persisted missing usage count"
        )
        usage_malformed = _strict_int_cell(
            row.get("usage_malformed_response_count"), "persisted malformed usage count"
        )
        if complete_count + usage_missing + usage_malformed != responses:
            raise ValueError("persisted usage accounting does not cover Provider responses")
        if usage_complete != (responses > 0 and complete_count == responses):
            raise ValueError("persisted usage_complete is crossed with response accounting")
        input_tokens = output_tokens = total_tokens = cached_tokens = 0
        if usage_complete:
            input_tokens = _strict_int_cell(row.get("input_usage"), "persisted input usage")
            output_tokens = _strict_int_cell(row.get("output_usage"), "persisted output usage")
            total_tokens = _strict_int_cell(row.get("total_usage"), "persisted total usage")
            cached_tokens = _strict_int_cell(row.get("cached_input_usage"), "persisted cached input usage")
            if total_tokens != input_tokens + output_tokens or cached_tokens > input_tokens:
                raise ValueError("persisted token usage totals are crossed")

        self.logical_judgments += 1
        self.physical_attempts += requests
        self.provider_responses += responses
        self.successful_decisions += successes
        self.observed_model_counts.update(observed_counts)
        self.usage_complete_response_count += complete_count
        self.usage_missing_response_count += usage_missing
        self.usage_malformed_response_count += usage_malformed
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.total_tokens += total_tokens
        self.cached_input_tokens += cached_tokens

    def close(self) -> dict[str, object]:
        if self.logical_judgments != self.contract.expected_primary_terminals:
            raise ValueError("persisted Provider accounting does not close every logical judgment")
        execution = self.contract.formal_execution
        if execution is not None:
            if set(self.observed_model_counts) - {execution.required_observed_model}:
                raise ValueError("persisted Provider accounting contains observed-model drift")
            if self.physical_attempts > execution.physical_attempt_cap:
                raise ValueError("persisted physical attempts exceed the frozen Full-Pool cap")
        return {
            "schema_version": "full-pool-formal-provider-accounting-v1",
            "logical_judgments": self.logical_judgments,
            "physical_attempts": self.physical_attempts,
            "provider_responses": self.provider_responses,
            "successful_decisions": self.successful_decisions,
            "observed_model_counts": dict(sorted(self.observed_model_counts.items())),
            "usage_complete_response_count": self.usage_complete_response_count,
            "usage_missing_response_count": self.usage_missing_response_count,
            "usage_malformed_response_count": self.usage_malformed_response_count,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cached_input_tokens": self.cached_input_tokens,
        }


def _strict_int_cell(value: object, context: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{context} must be a non-negative integer")
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    raise ValueError(f"{context} must be a non-negative integer")


def _json_object_cell(value: object, context: str) -> dict[str, object]:
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, Mapping):
        raise ValueError(f"{context} must be an object")
    return {str(key): item for key, item in decoded.items()}


def _operational_workspace_lineage(workspace: Path) -> dict[str, object]:
    _require_real_directory(workspace, "Full-Pool operational workspace")
    artifacts: list[dict[str, object]] = []
    for path in sorted(workspace.rglob("*")):
        relative_path = path.relative_to(workspace).as_posix()
        if path.is_symlink():
            raise ValueError(f"Full-Pool operational lineage contains a symlink: {relative_path}")
        mode = path.stat(follow_symlinks=False).st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise ValueError(f"Full-Pool operational lineage contains a non-regular file: {relative_path}")
        artifacts.append(
            {
                "relative_path": relative_path,
                "sha256": _sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )
    if not artifacts:
        raise ValueError("Full-Pool operational lineage is empty")
    return {
        "schema_version": "full-pool-operational-lineage-v1",
        "workspace_identity": workspace.name,
        "artifacts": artifacts,
        "inventory_sha256": _sha256_json(artifacts),
    }


def _formal_source_is_production_eligible(
    contract: FullPoolExperimentContract,
    *,
    accounting: Mapping[str, object],
    provider_failed_count: int,
) -> bool:
    execution = contract.formal_execution
    return bool(
        contract.profile == "production"
        and execution is not None
        and execution.evidence_profile == "formal_live"
        and provider_failed_count == 0
        and accounting.get("logical_judgments") == contract.expected_primary_terminals
        and accounting.get("successful_decisions") == contract.expected_primary_terminals
        and accounting.get("provider_responses") == contract.expected_primary_terminals
        and accounting.get("observed_model_counts")
        == {execution.required_observed_model: contract.expected_primary_terminals}
        and accounting.get("usage_complete_response_count") == contract.expected_primary_terminals
        and accounting.get("usage_missing_response_count") == 0
        and accounting.get("usage_malformed_response_count") == 0
        and isinstance(accounting.get("physical_attempts"), int)
        and 0 < cast(int, accounting.get("physical_attempts")) <= execution.physical_attempt_cap
        and accounting.get("external_request_invocations") == accounting.get("physical_attempts")
        and accounting.get("subscription_billed_cost_usd") == 0.0
    )


def _full_pool_source_schemas(contract: FullPoolExperimentContract) -> dict[str, str]:
    if contract.formal_execution is None:
        return {
            "source": FULL_POOL_SOURCE_SCHEMA,
            "manifest": FULL_POOL_MANIFEST_SCHEMA,
            "batch": FULL_POOL_BATCH_SCHEMA,
            "aggregates": FULL_POOL_AGGREGATES_SCHEMA,
            "diagnostics": FULL_POOL_DIAGNOSTICS_SCHEMA,
            "document": FULL_POOL_SCHEMA_DOCUMENT_VERSION,
        }
    return {
        "source": FULL_POOL_FORMAL_SOURCE_SCHEMA,
        "manifest": FULL_POOL_FORMAL_MANIFEST_SCHEMA,
        "batch": FULL_POOL_FORMAL_BATCH_SCHEMA,
        "aggregates": FULL_POOL_FORMAL_AGGREGATES_SCHEMA,
        "diagnostics": FULL_POOL_FORMAL_DIAGNOSTICS_SCHEMA,
        "document": FULL_POOL_FORMAL_SCHEMA_DOCUMENT_VERSION,
    }


def _close_full_pool_source(
    *,
    contract: FullPoolExperimentContract,
    output_path: Path,
    spooled: _PrimaryOnlyConcurrentRuntimeSpoolResult,
    expected_user_ids: set[str],
    expected_seed_user_ids: set[str],
    provider_accounting: Mapping[str, object] | None = None,
) -> tuple[str, str]:
    contract_payload = contract.model_dump(mode="json")
    contract_sha256 = _sha256_json(contract_payload)
    schemas = _full_pool_source_schemas(contract)
    source_identity = f"{contract.output_identity}:{contract_sha256[:16]}"
    staging = output_path.parent / f".{output_path.name}.{contract_sha256[:12]}.staging"
    if output_path.exists() or output_path.is_symlink():
        raise FileExistsError(f"Full-Pool final source already exists: {output_path}")
    if staging.exists() or staging.is_symlink():
        raise FileExistsError(f"Full-Pool source staging already exists: {staging}")
    staging.mkdir()
    try:
        batches_dir = staging / _BATCHES_DIR
        batches_dir.mkdir()
        _write_json(staging / _CONTRACT_FILE, contract_payload)
        _write_json(
            staging / _SCHEMA_FILE,
            {
                "schema_version": schemas["document"],
                "source_schema_version": schemas["source"],
                "manifest_schema_version": schemas["manifest"],
                "batch_schema_version": schemas["batch"],
                "row_schemas": {
                    "candidate": list(CONCURRENT_MESSAGE_CANDIDATE_FIELDS),
                    "pair": list(_PRIMARY_PAIR_FIELDS),
                    "terminal": list(CONCURRENT_MESSAGE_TERMINAL_FIELDS),
                },
                "terminal_variants": ["primary"],
            },
        )
        if contract.formal_execution is not None:
            _validate_formal_execution_artifacts(contract)
            shutil.copyfile(
                contract.formal_execution.authorization.artifact_path,
                staging / _FORMAL_AUTHORIZATION_SOURCE_FILE,
            )
            shutil.copyfile(
                contract.formal_execution.qualification.artifact_path,
                staging / _FORMAL_QUALIFICATION_SOURCE_FILE,
            )
            shutil.copyfile(
                contract.formal_execution.qualification.observed_response_artifact_path,
                staging / _FORMAL_OBSERVED_EVIDENCE_SOURCE_FILE,
            )
        accumulator = _SourceAccumulator(contract, expected_user_ids=expected_user_ids)
        persisted_provider_accounting = _PersistedProviderAccounting(contract)
        journal = ConcurrentExecutionJournal.open_existing(spooled.workspace_root)
        replay = journal._replay_runtime()
        spool = _ConcurrentRuntimeBatchSpool(
            spooled.workspace_root,
            run_id=journal.run_id,
            identity_hash=journal.identity_hash,
            terminal_variants=("primary",),
        )
        with (
            (staging / _CANDIDATE_ROWS_FILE).open("x", encoding="utf-8", newline="\n") as candidate_handle,
            (staging / _PAIR_ROWS_FILE).open("x", encoding="utf-8", newline="\n") as pair_handle,
            (staging / _TERMINAL_ROWS_FILE).open("x", encoding="utf-8", newline="\n") as terminal_handle,
        ):
            for chunk in spool.iter_committed(replay):
                accumulator.consume_batch(
                    time_step=chunk.time_step,
                    commit=chunk.commit,
                    candidate_rows=chunk.candidate_rows,
                    pair_rows=chunk.result_rows,
                    terminal_rows=chunk.terminal_rows,
                    expected_seed_user_ids=expected_seed_user_ids,
                )
                for row in chunk.candidate_rows:
                    candidate_handle.write(_canonical_json(row) + "\n")
                for row in chunk.result_rows:
                    pair_handle.write(_canonical_json(row) + "\n")
                for row in chunk.terminal_rows:
                    persisted_provider_accounting.consume(row)
                    terminal_handle.write(_canonical_json(row) + "\n")
                _write_json(
                    batches_dir / f"batch-{chunk.time_step:06d}.json",
                    {
                        "schema_version": schemas["batch"],
                        "source_identity": source_identity,
                        "contract_sha256": contract_sha256,
                        "time_step": chunk.time_step,
                        "commit": chunk.commit,
                        "rows": {
                            "candidate_rows": chunk.candidate_rows,
                            "pair_rows": chunk.result_rows,
                            "terminal_rows": chunk.terminal_rows,
                        },
                    },
                )
        aggregates, diagnostics = accumulator.close()
        evidence_profile = (
            contract.formal_execution.evidence_profile
            if contract.formal_execution is not None
            else "deterministic_validation"
        )
        persisted_accounting = persisted_provider_accounting.close()
        supplied_accounting = dict(provider_accounting) if provider_accounting is not None else {}
        for field_name, expected_value in persisted_accounting.items():
            if provider_accounting is not None and supplied_accounting.get(field_name) != expected_value:
                raise ValueError(f"durable attempt ledger {field_name} is crossed with persisted terminal rows")
        accounting_payload = {
            **persisted_accounting,
            "external_request_invocations": supplied_accounting.get("external_request_invocations", 0),
            "subscription_billed_cost_usd": supplied_accounting.get("subscription_billed_cost_usd", 0.0),
        }
        provider_calls = _strict_non_negative_int(
            accounting_payload.get("external_request_invocations"), "source external Provider calls"
        )
        physical_attempts = _strict_non_negative_int(
            accounting_payload.get("physical_attempts"), "source physical Provider attempts"
        )
        production_eligible = _formal_source_is_production_eligible(
            contract,
            accounting=accounting_payload,
            provider_failed_count=accumulator.provider_failed_count,
        )
        aggregates["schema_version"] = schemas["aggregates"]
        diagnostics["schema_version"] = schemas["diagnostics"]
        aggregates["evidence_profile"] = evidence_profile
        aggregates["provider_accounting"] = accounting_payload
        aggregates["provider_calls"] = provider_calls
        aggregates["live_api_triggered"] = provider_calls > 0
        aggregates["production_deploy_eligible"] = production_eligible
        diagnostics["runtime_resident_row_high_water"] = spooled.runtime_resident_row_high_water
        diagnostics["runtime_resident_rows_after_commit"] = spooled.runtime_resident_rows_after_commit
        _write_json(staging / _AGGREGATES_FILE, aggregates)
        _write_json(staging / _DIAGNOSTICS_FILE, diagnostics)

        artifact_paths = sorted(
            path.relative_to(staging).as_posix()
            for path in staging.rglob("*")
            if path.is_file()
        )
        artifacts = [
            {
                "relative_path": relative_path,
                "sha256": _sha256_file(staging / relative_path),
                "bytes": (staging / relative_path).stat().st_size,
            }
            for relative_path in artifact_paths
        ]
        source_hash = _sha256_json(artifacts)
        operational_lineage = (
            _operational_workspace_lineage(spooled.workspace_root)
            if contract.formal_execution is not None
            else None
        )
        manifest = {
            "schema_version": schemas["manifest"],
            "source_schema_version": schemas["source"],
            "source_identity": source_identity,
            "contract_sha256": contract_sha256,
            "source_hash": source_hash,
            "profile": contract.profile,
            "evidence_profile": evidence_profile,
            "physical_provider_attempts": physical_attempts,
            "provider_calls": provider_calls,
            "live_api_triggered": provider_calls > 0,
            "production_deploy_eligible": production_eligible,
            "counts": aggregates["counts"],
            "operational_lineage": operational_lineage,
            "artifacts": artifacts,
        }
        _write_json(staging / _MANIFEST_FILE, manifest)
        manifest_sha256 = _sha256_file(staging / _MANIFEST_FILE)
        _validate_staged_source(
            staging,
            contract=contract,
            source_identity=source_identity,
            operational_root=spooled.workspace_root,
        )
        os.replace(staging, output_path)
        _fsync_directory(output_path.parent)
    except Exception:
        if staging.is_dir() and not staging.is_symlink():
            shutil.rmtree(staging)
        raise
    return source_identity, manifest_sha256


def _validate_staged_source(
    source_root: Path,
    *,
    contract: FullPoolExperimentContract,
    source_identity: str,
    operational_root: Path | None = None,
) -> None:
    _require_real_directory(source_root, "Full-Pool source staging")
    schemas = _full_pool_source_schemas(contract)
    manifest = _read_json_object(source_root / _MANIFEST_FILE)
    if manifest.get("schema_version") != schemas["manifest"]:
        raise ValueError("Full-Pool manifest schema is not supported")
    contract_payload = contract.model_dump(mode="json")
    contract_sha256 = _sha256_json(contract_payload)
    if (
        manifest.get("source_schema_version") != schemas["source"]
        or manifest.get("source_identity") != source_identity
        or manifest.get("contract_sha256") != contract_sha256
    ):
        raise ValueError("Full-Pool manifest identity is crossed")
    if _read_json_object(source_root / _CONTRACT_FILE) != contract_payload:
        raise ValueError("persisted Full-Pool contract does not match the frozen input")
    if contract.formal_execution is not None:
        for relative_path, artifact in (
            (_FORMAL_AUTHORIZATION_SOURCE_FILE, contract.formal_execution.authorization),
            (_FORMAL_QUALIFICATION_SOURCE_FILE, contract.formal_execution.qualification),
        ):
            source_artifact = source_root / relative_path
            _require_regular_file(source_artifact, f"persisted Formal artifact {relative_path}")
            if (
                _sha256_file(source_artifact) != artifact.artifact_sha256
                or _read_json_object(source_artifact) != _artifact_document(artifact)
            ):
                raise ValueError(f"persisted Formal artifact {relative_path} is crossed")
        observed_artifact = source_root / _FORMAL_OBSERVED_EVIDENCE_SOURCE_FILE
        _require_regular_file(observed_artifact, "persisted observed-model evidence")
        if (
            _sha256_file(observed_artifact)
            != contract.formal_execution.qualification.observed_response_sha256
            or _read_json_object(observed_artifact)
            != _observed_model_evidence_document(contract.formal_execution)
        ):
            raise ValueError("persisted observed-model evidence is crossed")
    expected_workspace = operational_root or (
        contract.formal_execution.operational_root
        if contract.formal_execution is not None
        else source_root.parent / f".{source_root.name}.operational"
    )
    if contract.formal_execution is not None:
        if manifest.get("operational_lineage") != _operational_workspace_lineage(expected_workspace):
            raise ValueError("Full-Pool operational journal or spool lineage changed after source closure")
    elif manifest.get("operational_lineage") is not None:
        raise ValueError("legacy Validation source must not bind path-specific operational lineage")

    artifacts_raw = manifest.get("artifacts")
    if not isinstance(artifacts_raw, Sequence) or isinstance(artifacts_raw, (str, bytes)):
        raise ValueError("Full-Pool manifest artifacts must be a sequence")
    artifacts: list[dict[str, object]] = []
    for raw in artifacts_raw:
        if not isinstance(raw, Mapping):
            raise ValueError("Full-Pool manifest artifact entry must be an object")
        relative_path = _safe_relative_path(raw.get("relative_path"))
        artifact_path = source_root / relative_path
        _require_regular_file(artifact_path, f"Full-Pool artifact {relative_path}")
        sha256 = _non_empty(raw.get("sha256"), "artifact sha256")
        if not _SHA256_PATTERN.fullmatch(sha256) or _sha256_file(artifact_path) != sha256:
            raise ValueError(f"Full-Pool artifact checksum mismatch: {relative_path}")
        if raw.get("bytes") != artifact_path.stat().st_size:
            raise ValueError(f"Full-Pool artifact size mismatch: {relative_path}")
        artifacts.append({"relative_path": relative_path, "sha256": sha256, "bytes": raw.get("bytes")})
    persisted_relative_paths = [cast(str, row["relative_path"]) for row in artifacts]
    if persisted_relative_paths != sorted(persisted_relative_paths):
        raise ValueError("Full-Pool artifact inventory is not canonical")
    actual_files = sorted(
        path.relative_to(source_root).as_posix()
        for path in source_root.rglob("*")
        if path.is_file()
    )
    expected_files = sorted([str(row["relative_path"]) for row in artifacts] + [_MANIFEST_FILE])
    if actual_files != expected_files:
        raise ValueError("Full-Pool source contains missing, extra, or unlisted files")
    if manifest.get("source_hash") != _sha256_json(artifacts):
        raise ValueError("Full-Pool source hash does not close the artifact inventory")

    batch_paths = sorted((source_root / _BATCHES_DIR).glob("batch-*.json"))
    if [path.name for path in batch_paths] != [f"batch-{step:06d}.json" for step in range(contract.horizon)]:
        raise ValueError("Full-Pool persisted batch inventory is incomplete")
    stream_hashes = {
        "candidate_rows": hashlib.sha256(),
        "pair_rows": hashlib.sha256(),
        "terminal_rows": hashlib.sha256(),
    }
    stream_counts = Counter[str]()
    persisted_pairs: set[tuple[str, str]] = set()
    coverage = Counter[str]()
    persisted_provider_accounting = _PersistedProviderAccounting(contract)
    for time_step, batch_path in enumerate(batch_paths):
        batch = _read_json_object(batch_path)
        if (
            batch.get("schema_version") != schemas["batch"]
            or batch.get("source_identity") != source_identity
            or batch.get("contract_sha256") != contract_sha256
            or batch.get("time_step") != time_step
        ):
            raise ValueError("Full-Pool persisted batch identity is crossed")
        rows = batch.get("rows")
        if not isinstance(rows, Mapping) or set(rows) != {"candidate_rows", "pair_rows", "terminal_rows"}:
            raise ValueError("Full-Pool persisted batch row kinds are incomplete or extra")
        for row_kind in ("candidate_rows", "pair_rows", "terminal_rows"):
            batch_rows = rows[row_kind]
            if not isinstance(batch_rows, Sequence) or isinstance(batch_rows, (str, bytes)):
                raise ValueError("Full-Pool persisted batch rows must be a sequence")
            for raw_row in batch_rows:
                if not isinstance(raw_row, Mapping):
                    raise ValueError("Full-Pool persisted source row must be an object")
                stream_hashes[row_kind].update((_canonical_json(raw_row) + "\n").encode("utf-8"))
                stream_counts[row_kind] += 1
                if row_kind == "terminal_rows":
                    persisted_provider_accounting.consume(raw_row)
                if row_kind == "pair_rows":
                    user_id = _non_empty(raw_row.get("user_id"), "persisted pair user_id")
                    message_id = _message_id(raw_row)
                    key = (user_id, message_id)
                    if key in persisted_pairs:
                        raise ValueError("persisted Full-Pool source duplicates an exposed pair")
                    persisted_pairs.add(key)
                    coverage[user_id] += 1
    stream_files = {
        "candidate_rows": _CANDIDATE_ROWS_FILE,
        "pair_rows": _PAIR_ROWS_FILE,
        "terminal_rows": _TERMINAL_ROWS_FILE,
    }
    for row_kind, relative_path in stream_files.items():
        if stream_hashes[row_kind].hexdigest() != _sha256_file(source_root / relative_path):
            raise ValueError(f"Full-Pool {row_kind} stream is crossed with persisted batch chunks")
    if stream_counts != Counter(
        {
            "candidate_rows": contract.expected_candidate_ranking_rows,
            "pair_rows": contract.expected_exposures,
            "terminal_rows": contract.expected_primary_terminals,
        }
    ):
        raise ValueError("Full-Pool persisted row streams do not close the contract counts")
    if len(persisted_pairs) != contract.expected_eligible_pairs:
        raise ValueError("Full-Pool persisted pair identity count is incomplete")
    if Counter(coverage.values()) != Counter({len(contract.message_ids): contract.eligible_user_count}):
        raise ValueError("Full-Pool persisted source does not give every user three-message coverage")

    aggregates = _read_json_object(source_root / _AGGREGATES_FILE)
    diagnostics = _read_json_object(source_root / _DIAGNOSTICS_FILE)
    if aggregates.get("schema_version") != schemas["aggregates"]:
        raise ValueError("Full-Pool aggregate schema is not supported")
    counts = aggregates.get("counts")
    if not isinstance(counts, Mapping) or counts != manifest.get("counts"):
        raise ValueError("Full-Pool aggregate counts are crossed with the manifest")
    accounting = aggregates.get("provider_accounting")
    if not isinstance(accounting, Mapping):
        raise ValueError("Full-Pool aggregate Provider accounting is missing")
    recomputed_accounting = persisted_provider_accounting.close()
    for field_name, expected_value in recomputed_accounting.items():
        if accounting.get(field_name) != expected_value:
            raise ValueError(f"Full-Pool aggregate {field_name} is crossed with persisted terminal rows")
    expected_evidence_profile = (
        contract.formal_execution.evidence_profile
        if contract.formal_execution is not None
        else "deterministic_validation"
    )
    if (
        aggregates.get("evidence_profile") != expected_evidence_profile
        or manifest.get("evidence_profile") != expected_evidence_profile
        or manifest.get("physical_provider_attempts") != accounting.get("physical_attempts")
        or manifest.get("provider_calls") != accounting.get("external_request_invocations")
        or manifest.get("live_api_triggered") is not (cast(int, manifest.get("provider_calls")) > 0)
        or aggregates.get("provider_calls") != manifest.get("provider_calls")
        or aggregates.get("live_api_triggered") != manifest.get("live_api_triggered")
        or aggregates.get("production_deploy_eligible") != manifest.get("production_deploy_eligible")
    ):
        raise ValueError("Full-Pool Provider accounting or evidence profile is crossed")
    if diagnostics.get("schema_version") != schemas["diagnostics"]:
        raise ValueError("Full-Pool diagnostics schema is not supported")
    batches = diagnostics.get("batches")
    if not isinstance(batches, Sequence) or len(batches) != contract.horizon:
        raise ValueError("Full-Pool diagnostics do not close every committed batch")


def _read_user_ids(path: Path) -> set[str]:
    _require_regular_file(path, "Full-Pool users.csv")
    user_ids: set[str] = set()
    with path.open(encoding="utf-8", newline="") as handle:
        for row_number, row in enumerate(csv.DictReader(handle), start=2):
            user_id = str(row.get("user_id", "") or "").strip()
            if not user_id:
                raise ValueError(f"users.csv row {row_number} has an empty user_id")
            if user_id in user_ids:
                raise ValueError(f"users.csv contains duplicate user_id: {user_id}")
            user_ids.add(user_id)
    return user_ids


def _external_request_count(adapter: LLMDecisionAdapter) -> int:
    try:
        return _adapter_external_request_invocations(adapter)
    except (TypeError, ValueError) as exc:
        raise FullPoolExperimentError(
            FullPoolExperimentErrorCode.INVALID_ADAPTER,
            "Validation Adapter external request accounting is invalid",
        ) from exc


def _message_id(row: Mapping[str, object]) -> str:
    message_id = _non_empty(row.get("message_id"), "message_id")
    if message_id not in FULL_POOL_MESSAGE_IDS:
        raise ValueError("row contains a message outside the authoritative contract")
    return message_id


def _require_time_step(row: Mapping[str, object], expected: int, row_kind: str) -> None:
    value = row.get("time_step")
    if isinstance(value, bool) or not isinstance(value, (int, str)) or int(value) != expected:
        raise ValueError(f"{row_kind} row time_step is crossed with its batch")


def _csv_boolean(value: object, context: str) -> bool:
    if value is True or value == "true":
        return True
    if value is False or value == "false":
        return False
    raise ValueError(f"{context} must be a canonical boolean")


def _string_list(value: object, context: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{context} must be a sequence")
    result = [_non_empty(item, context) for item in value]
    if len(result) != len(set(result)):
        raise ValueError(f"{context} contains duplicate identities")
    return result


def _non_empty(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be a non-empty string")
    return value


def _safe_relative_path(value: object) -> str:
    relative_path = _non_empty(value, "artifact relative_path")
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != relative_path:
        raise ValueError("Full-Pool artifact path must be a normalized relative path")
    return relative_path


def _write_json(path: Path, value: object) -> None:
    path.write_text(_canonical_json(value) + "\n", encoding="utf-8", newline="\n")


def _atomic_write_json_file(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(_canonical_json(value) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists() and not temporary.is_symlink():
            temporary.unlink()


def _read_json_object(path: Path) -> dict[str, object]:
    _require_regular_file(path, path.name)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"{path.name} must contain an object")
    return {str(key): item for key, item in value.items()}


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    _require_regular_file(path, path.name)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_real_directory(path: Path, context: str) -> None:
    if path.is_symlink():
        raise ValueError(f"{context} must not be a symlink")
    try:
        mode = path.stat(follow_symlinks=False).st_mode
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"{context} does not exist: {path}") from exc
    if not stat.S_ISDIR(mode):
        raise ValueError(f"{context} must be a regular directory")


def _require_regular_file(path: Path, context: str) -> None:
    if path.is_symlink():
        raise ValueError(f"{context} must be a regular file, not a symlink")
    try:
        mode = path.stat(follow_symlinks=False).st_mode
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"{context} is missing: {path}") from exc
    if not stat.S_ISREG(mode):
        raise ValueError(f"{context} must be a regular file")


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_DIRECTORY)
    except (AttributeError, FileNotFoundError, NotADirectoryError, OSError):
        return
    try:
        try:
            os.fsync(descriptor)
        except OSError:
            pass
    finally:
        os.close(descriptor)
