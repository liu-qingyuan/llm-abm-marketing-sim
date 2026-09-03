from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import stat
import tempfile
import threading
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .concurrent_execution_journal import (
    ConcurrentExecutionJournal,
    _build_primary_only_concurrent_execution_run_identity,
    derive_concurrent_execution_workspace,
)
from .concurrent_message_experiment import (
    CONCURRENT_MESSAGE_POSITIVE_ACTIONS,
    CONCURRENT_MESSAGE_PRODUCTION_DELIVERY_CAPACITY,
    CONCURRENT_MESSAGE_PRODUCTION_HORIZON,
    CONCURRENT_MESSAGE_PRODUCTION_SAMPLE_SIZE,
    _adapter_external_request_invocations,
    _adapter_live_api_triggered,
    _adapter_prompt_version,
    _build_runtime_terminal_row,
    _ConcurrentRuntimeBatchCommit,
    _ConcurrentRuntimeKernel,
    _ConcurrentRuntimeKernelState,
    _execute_runtime_variant,
    _PairExecutionPlan,
    _prepare_concurrent_runtime_inputs,
    _PreparedConcurrentRuntimeInputs,
    _primary_variant_context,
    _PrimaryOnlyConcurrentRuntimeConsumer,
    _unwrap_adapter,
    _VariantAttemptAccounting,
)
from .concurrent_robustness_study import (
    _MODEL_ID_PATTERN,
    _OUTPUT_IDENTITY_PATTERN,
    _ROBUSTNESS_MESSAGE_IDS,
    ConcurrentRobustnessError,
    ConcurrentRobustnessErrorCode,
    ConcurrentRobustnessStudyResult,
    ConcurrentRobustnessStudyStatus,
    _assert_source_unchanged,
    _close_source,
    _dynamic_runtime_config,
    _ordered_user_ids_sha256,
    _PromptModelCell,
    _RankingContract,
    _RequestContract,
    _resolve_output_path,
    _resolve_source_path,
    _SampleIdentity,
    _SourceIdentity,
    _validate_source_against_manifest,
    _validate_study_paths,
)
from .decision import (
    EngageDecision,
    EngagementAction,
    LLMDecisionAdapter,
    ProviderDecisionError,
    ProviderResponseProvenanceUnknown,
)
from .engagement_realization import (
    REALIZATION_RULE_VERSION,
    REALIZATION_SEED,
    EngagementRealization,
    EngagementRealizationPolicy,
)
from .final_research import VALIDATION_RUN_STATUS
from .prompt_contracts import CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY
from .provider_accounting import ProviderAccounting, provider_accounting_delta

CONCURRENT_ROBUSTNESS_MANIFEST_V2_SCHEMA = "concurrent-robustness-manifest-v2"
CONCURRENT_ROBUSTNESS_REALIZATION_SOURCE_SCHEMA = "concurrent-robustness-realization-source-v1"
CONCURRENT_ROBUSTNESS_REALIZATION_IDENTITY_SCHEMA = "concurrent-robustness-realization-identity-v1"
CONCURRENT_ROBUSTNESS_BATCH_BARRIER_V2_SCHEMA = "concurrent-robustness-two-stage-barrier-v2"

_V2_MODELS = (
    "deepseek-v4-flash",
    "gemini-3.1-pro",
    "gemini-3.8-flash-high",
    "kimi-coding/k3-256k",
    "openai-codex/gpt-5.6-sol",
)
_V2_REQUIRED_OBSERVED_MODELS: Mapping[str, str] = {
    "deepseek-v4-flash": "deepseek-v4-flash",
    "gemini-3.1-pro": "gemini-pro-agent",
    "gemini-3.8-flash-high": "gemini-3.8-flash-high",
    "kimi-coding/k3-256k": "k3-256k",
    "openai-codex/gpt-5.6-sol": "gpt-5.6-sol",
}
_V2_CELL_COUNT = 20
_V2_FORMAL_LOGICAL_PER_CELL = 1_800
_V2_FORMAL_LOGICAL_CAP = 36_000
_V2_FORMAL_PHYSICAL_CAP = 108_000
_V2_MAXIMUM_ATTEMPTS = 3
_V2_BACKOFF_CEILING_SECONDS = 60.0
_V2_SLEEP = time.sleep
_V2_MONOTONIC = time.monotonic


class _V2FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


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


def _json_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _require_sha256(value: str, context: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{context} must be 64 lowercase hexadecimal characters")
    return value


def _effective_graph_identity(prepared: _PreparedConcurrentRuntimeInputs) -> str:
    """Hash exactly the graph facts that can affect this frozen sample's ranking."""

    sample_user_ids = tuple(prepared.cohort.sample_user_ids)
    sample_users = set(sample_user_ids)
    payload = {
        "schema_version": "concurrent-robustness-effective-sample-graph-v1",
        "sample_user_ids": list(sample_user_ids),
        "base_network_relevance": [
            [user_id, format(float(prepared.base_network_by_user.get(user_id, 0.0)), ".17g")]
            for user_id in sample_user_ids
        ],
        "sample_neighbors": [
            [
                user_id,
                sorted(set(prepared.neighbors_by_user.get(user_id, set())).intersection(sample_users)),
            ]
            for user_id in sample_user_ids
        ],
    }
    return _json_sha256(payload)


def _realization_facts(
    *,
    sample_identity: str,
    graph_identity_sha256: str,
    message_ids: tuple[str, ...],
    message_snapshot_sha256: str,
) -> dict[str, object]:
    return {
        "schema_version": CONCURRENT_ROBUSTNESS_REALIZATION_SOURCE_SCHEMA,
        "sample_identity": sample_identity,
        "graph_identity_sha256": graph_identity_sha256,
        "message_ids": list(message_ids),
        "message_snapshot_sha256": message_snapshot_sha256,
        "realization_rule_version": REALIZATION_RULE_VERSION,
        "realization_seed": REALIZATION_SEED,
    }


def _realization_source_payload(
    *,
    sample_identity: str,
    graph_identity_sha256: str,
    message_ids: tuple[str, ...],
    message_snapshot_sha256: str,
) -> dict[str, object]:
    facts = _realization_facts(
        sample_identity=sample_identity,
        graph_identity_sha256=graph_identity_sha256,
        message_ids=message_ids,
        message_snapshot_sha256=message_snapshot_sha256,
    )
    canonical_facts_sha256 = _json_sha256(facts)
    source_identity = _json_sha256(
        {
            "schema_version": CONCURRENT_ROBUSTNESS_REALIZATION_IDENTITY_SCHEMA,
            "canonical_facts_sha256": canonical_facts_sha256,
        }
    )
    return {
        **facts,
        "canonical_facts_sha256": canonical_facts_sha256,
        "source_identity": source_identity,
    }


class _V2RealizationSource(_V2FrozenModel):
    schema_version: Literal["concurrent-robustness-realization-source-v1"]
    sample_identity: str
    graph_identity_sha256: str
    message_ids: tuple[str, ...]
    message_snapshot_sha256: str
    realization_rule_version: Literal["sha256-source-user-message-first-53-bits-uniform-v1"]
    realization_seed: Literal[20260823]
    canonical_facts_sha256: str
    source_identity: str

    @field_validator(
        "sample_identity",
        "graph_identity_sha256",
        "message_snapshot_sha256",
        "canonical_facts_sha256",
        "source_identity",
    )
    @classmethod
    def _validate_hash(cls, value: str) -> str:
        return _require_sha256(value, "realization source hash")

    @model_validator(mode="after")
    def _validate_identity(self) -> _V2RealizationSource:
        expected = _realization_source_payload(
            sample_identity=self.sample_identity,
            graph_identity_sha256=self.graph_identity_sha256,
            message_ids=self.message_ids,
            message_snapshot_sha256=self.message_snapshot_sha256,
        )
        if self.model_dump(mode="json") != expected:
            raise ValueError(
                "realization source identity is crossed with its canonical sample, graph, message, or policy facts"
            )
        return self


class _V2RequestCaps(_V2FrozenModel):
    logical_judgments_per_cell: int = Field(ge=1)
    logical_judgment_cap: int = Field(ge=1)
    physical_attempt_cap: int = Field(ge=1)
    maximum_physical_attempts_per_judgment: Literal[3]


class _V2BatchBarrier(_V2FrozenModel):
    schema_version: Literal["concurrent-robustness-two-stage-barrier-v2"]
    required_terminal: Literal["persisted-realized-terminal-per-selected-pair-v1"]
    feedback_source: Literal["campaign-deduplicated-realized-positive-users-v1"]
    feedback_timing: Literal["next-batch-only-v1"]


class _V2FormalContract(_V2FrozenModel):
    schema_version: Literal["concurrent-robustness-formal-topology-v2"]
    model_count: Literal[5]
    prompt_variants: tuple[Literal["P0", "P1", "P2", "P3"], ...]
    cell_count: Literal[20]
    sample_size: Literal[1000]
    batch_count: Literal[30]
    message_count: Literal[3]
    delivery_capacity_per_message: Literal[20]
    logical_judgments_per_cell: Literal[1800]
    logical_judgment_cap: Literal[36000]
    maximum_physical_attempts_per_judgment: Literal[3]
    physical_attempt_cap: Literal[108000]

    @model_validator(mode="after")
    def _validate_prompt_order(self) -> _V2FormalContract:
        if self.prompt_variants != ("P0", "P1", "P2", "P3"):
            raise ValueError("v2 Formal Prompt variants must remain in canonical order")
        return self


class ConcurrentRobustnessManifestV2(_V2FrozenModel):
    """Additive 20-cell two-stage study contract behind the existing Study Interface."""

    schema_version: Literal["concurrent-robustness-manifest-v2"] = "concurrent-robustness-manifest-v2"
    source: _SourceIdentity
    sample: _SampleIdentity
    message_ids: tuple[str, ...]
    message_snapshot_sha256: str
    ranking_contract: _RankingContract
    prompt_model_cells: tuple[_PromptModelCell, ...]
    request_contract: _RequestContract
    request_caps: _V2RequestCaps
    formal_contract: _V2FormalContract
    batch_barrier: _V2BatchBarrier
    realization_source: _V2RealizationSource
    execution_profile: Literal["deterministic_validation", "formal"]
    authorization_reference: str = Field(min_length=1, max_length=240)
    output_identity: str

    @field_validator("message_snapshot_sha256")
    @classmethod
    def _validate_message_hash(cls, value: str) -> str:
        return _require_sha256(value, "message snapshot sha256")

    @field_validator("output_identity")
    @classmethod
    def _validate_output_identity(cls, value: str) -> str:
        if not _OUTPUT_IDENTITY_PATTERN.fullmatch(value):
            raise ValueError("output identity must be a bounded stable token")
        return value

    @model_validator(mode="after")
    def _validate_manifest(self) -> ConcurrentRobustnessManifestV2:
        source_hashes = {artifact.relative_path: artifact.sha256 for artifact in self.source.artifacts}
        if self.sample.sample_manifest_sha256 != source_hashes["sample_manifest.json"]:
            raise ValueError("sample manifest hash is crossed with the source identity")
        if self.sample.sample_audit_sha256 != source_hashes["seed_first_sample_audit.json"]:
            raise ValueError("sample audit hash is crossed with the source identity")
        if self.message_snapshot_sha256 != source_hashes["message_snapshot.json"]:
            raise ValueError("message snapshot hash is crossed with the source identity")
        if self.message_ids != _ROBUSTNESS_MESSAGE_IDS:
            raise ValueError("v2 manifest must freeze the authoritative three message IDs")

        expected_cells = tuple(
            (
                f"{prompt.variant_id}::{model}",
                prompt.variant_id,
                prompt.prompt_version,
                prompt.canonical_hash,
                model,
                _V2_REQUIRED_OBSERVED_MODELS[model],
            )
            for prompt in CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.all()
            for model in _V2_MODELS
        )
        actual_cells = tuple(
            (
                cell.cell_id,
                cell.prompt_variant,
                cell.prompt_version,
                cell.prompt_canonical_hash,
                cell.requested_model,
                cell.required_observed_model,
            )
            for cell in self.prompt_model_cells
        )
        if (
            len(actual_cells) != _V2_CELL_COUNT
            or len(set(actual_cells)) != _V2_CELL_COUNT
            or actual_cells != expected_cells
        ):
            raise ValueError("v2 manifest requires exactly 20 canonical Prompt-Model cells")

        if self.ranking_contract.horizon * self.ranking_contract.delivery_capacity > self.sample.sample_size:
            raise ValueError("v2 schedule exceeds the one-exposure-per-message sample")
        logical_per_cell = (
            self.ranking_contract.horizon * self.ranking_contract.delivery_capacity * len(self.message_ids)
        )
        if self.request_contract.max_retries + 1 != _V2_MAXIMUM_ATTEMPTS:
            raise ValueError("v2 request contract must allow exactly three physical attempts")
        if self.request_caps.logical_judgments_per_cell != logical_per_cell:
            raise ValueError("v2 logical judgments per cell do not match the schedule")
        if self.request_caps.logical_judgment_cap != logical_per_cell * _V2_CELL_COUNT:
            raise ValueError("v2 logical cap does not match the 20-cell topology")
        if self.request_caps.physical_attempt_cap != self.request_caps.logical_judgment_cap * _V2_MAXIMUM_ATTEMPTS:
            raise ValueError("v2 physical cap does not match three attempts per judgment")

        realization = self.realization_source
        if (
            realization.sample_identity != self.sample.sample_identity
            or realization.message_ids != self.message_ids
            or realization.message_snapshot_sha256 != self.message_snapshot_sha256
        ):
            raise ValueError("realization source is crossed with the manifest sample or messages")

        if self.execution_profile == "deterministic_validation":
            if self.source.kind != "fixture":
                raise ValueError("deterministic v2 validation requires a fixture source")
        else:
            if self.source.kind != "formal":
                raise ValueError("Formal v2 execution requires a Formal source")
            if (
                self.sample.sample_size != CONCURRENT_MESSAGE_PRODUCTION_SAMPLE_SIZE
                or self.ranking_contract.horizon != CONCURRENT_MESSAGE_PRODUCTION_HORIZON
                or self.ranking_contract.delivery_capacity != CONCURRENT_MESSAGE_PRODUCTION_DELIVERY_CAPACITY
                or self.request_caps.logical_judgments_per_cell != _V2_FORMAL_LOGICAL_PER_CELL
                or self.request_caps.logical_judgment_cap != _V2_FORMAL_LOGICAL_CAP
                or self.request_caps.physical_attempt_cap != _V2_FORMAL_PHYSICAL_CAP
            ):
                raise ValueError(
                    "Formal v2 profile must freeze 1,000 users, 30 batches, three messages, Top20, 1,800 judgments per cell, 36,000 logical judgments, and 108,000 physical attempts"
                )
        return self


def _derive_v2_realization_source_contract(
    source_dir: str | Path,
) -> dict[str, object]:
    """Derive private manifest facts from the source's effective sample graph."""

    source_path = _resolve_source_path(Path(source_dir))
    closure = _close_source(source_path)
    config = _dynamic_runtime_config(closure)
    prepared = _prepare_concurrent_runtime_inputs(config)
    sample_identity = _ordered_user_ids_sha256(closure.source_evidence.sample_manifest_rows)
    prepared_identity = hashlib.sha256(
        json.dumps(
            prepared.cohort.sample_user_ids,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if prepared_identity != sample_identity:
        raise ValueError("prepared sample is crossed with the frozen source sample")
    message_ids = tuple(str(row["message_id"]) for row in closure.source_evidence.message_snapshot)
    payload = _realization_source_payload(
        sample_identity=sample_identity,
        graph_identity_sha256=_effective_graph_identity(prepared),
        message_ids=message_ids,
        message_snapshot_sha256=closure.artifact_hashes["message_snapshot.json"],
    )
    return _V2RealizationSource.model_validate(payload).model_dump(mode="json")


_V2_JUDGMENT_SCHEMA = "concurrent-robustness-provider-judgment-v2"
_V2_REALIZED_TERMINAL_SCHEMA = "concurrent-robustness-realized-terminal-v2"
_V2_PAIR_LEDGER_SCHEMA = "concurrent-robustness-pair-lifecycle-v2"
_V2_PAIR_LEDGER_IDENTITY_SCHEMA = "concurrent-robustness-pair-ledger-identity-v2"
_V2_EXECUTION_SCHEMA = "concurrent-robustness-two-stage-execution-v2"
_V2_EXECUTION_ANCHOR_SCHEMA = "concurrent-robustness-two-stage-execution-anchor-v1"
_V2_CELL_REGISTRY_SCHEMA = "concurrent-robustness-two-stage-cell-registry-v2"
_V2_WORKSPACE_VALIDATION_SCHEMA = "concurrent-robustness-v2-validation-v1"
_V2_WORKSPACE_REGISTRY_SCHEMA = "concurrent-robustness-v2-workspace-registry-v1"
_V2_OPERATIONAL_IDENTITY_SCHEMA = "concurrent-robustness-v2-operational-identity-v1"
_V2_OPERATIONAL_STATUS_SCHEMA = "concurrent-robustness-v2-operational-status-v1"

_V2_WORKSPACE_MANIFEST = "study_manifest.json"
_V2_WORKSPACE_VALIDATION = "validation_report.json"
_V2_WORKSPACE_REGISTRY = "workspace_registry.json"
_V2_EXECUTION_DIR = "two_stage_execution"
_V2_EXECUTION_ANCHOR = "execution_anchor.json"
_V2_EXECUTION_PAYLOAD_FILES = {
    "cell_registry.json",
    "terminal_rows.jsonl",
    "batch_commits.jsonl",
    "pair_lifecycle.jsonl",
}
_V2_EXECUTION_FILES = {
    "execution_manifest.json",
    _V2_EXECUTION_ANCHOR,
    *_V2_EXECUTION_PAYLOAD_FILES,
}
_V2_LEDGER_IDENTITY = "pair_lifecycle_identity.json"
_V2_LEDGER_JSONL = "pair_lifecycle.jsonl"
_V2_OPERATIONAL_IDENTITY = "panel_identity.json"
_V2_OPERATIONAL_STATUS = "panel_status.json"

_V2_PAIR_STATES = (
    "pending",
    "reserved",
    "attempting",
    "judgment_persisted",
    "realized_persisted",
    "settled",
)
_V2_ATTEMPT_BILLING_PROFILES: Mapping[
    str,
    tuple[str, Literal["CNY"] | None, float | None],
] = {
    "deepseek_official": ("provider_fee_cny", "CNY", 25.0),
    "antigravity_openai_compatible_gateway": ("gateway_quota_usage", None, None),
    "pi_kimi_oauth_subscription": (
        "subscription_quota_with_nominal_usd_reference",
        None,
        None,
    ),
    "pi_openai_oauth_subscription": (
        "subscription_quota_with_nominal_usd_reference",
        None,
        None,
    ),
    "injected_deterministic_validation": ("none", None, None),
}
_V2_ALLOWED_TRANSITIONS: Mapping[str | None, set[str]] = {
    None: {"pending"},
    "pending": {"reserved"},
    "reserved": {"attempting"},
    "attempting": {"attempting", "judgment_persisted", "stopped"},
    "judgment_persisted": {"realized_persisted"},
    "realized_persisted": {"settled"},
    "settled": set(),
    "stopped": set(),
}


class _V2AttemptEvidence(_V2FrozenModel):
    schema_version: Literal["concurrent-robustness-provider-attempt-v2"]
    attempt_number: int = Field(ge=1, le=_V2_MAXIMUM_ATTEMPTS)
    outcome: Literal["succeeded", "retryable_failure", "nonretryable_failure", "attempts_exhausted"]
    failure_category: str | None = None
    status_code: int | None = Field(default=None, ge=100, le=599)
    wait_source: Literal["retry_after", "provider_wait", "exponential_backoff"] | None = None
    wait_seconds: float | None = Field(default=None, ge=0.0)
    lane_cooldown: bool
    request_invocations: Literal[1]
    provider_response_count: int = Field(ge=0, le=1)
    successful_decision_count: int = Field(ge=0, le=1)
    observed_model_counts: dict[str, int]
    observed_model_missing_response_count: int = Field(ge=0, le=1)
    observed_model_malformed_response_count: int = Field(ge=0, le=1)
    usage_complete_response_count: int = Field(ge=0, le=1)
    usage_missing_response_count: int = Field(ge=0, le=1)
    usage_malformed_response_count: int = Field(ge=0, le=1)
    input_usage: int | None = Field(default=None, ge=0)
    output_usage: int | None = Field(default=None, ge=0)
    total_usage: int | None = Field(default=None, ge=0)
    cached_input_usage: int | None = Field(default=None, ge=0)
    provider_route: str
    billing_semantics: str
    billing_currency: Literal["CNY"] | None
    provider_fee_cny: float | None = Field(default=None, ge=0.0)
    subscription_nominal_cost_usd: float | None = Field(default=None, ge=0.0)
    fee_ceiling: float | None = Field(default=None, ge=0.0)

    @model_validator(mode="after")
    def _validate_attempt(self) -> _V2AttemptEvidence:
        if self.outcome == "succeeded":
            if self.failure_category is not None or self.successful_decision_count != 1:
                raise ValueError("successful attempt evidence cannot carry a failure")
            if self.wait_source is not None or self.wait_seconds is not None or self.lane_cooldown:
                raise ValueError("successful attempt evidence cannot carry retry timing")
        else:
            if not self.failure_category or self.successful_decision_count != 0:
                raise ValueError("failed attempt evidence requires a safe failure category")
        if (self.wait_source is None) != (self.wait_seconds is None):
            raise ValueError("attempt retry source and delay must be present together")
        if self.wait_seconds is not None and not math.isfinite(self.wait_seconds):
            raise ValueError("attempt retry delay must be finite")
        if self.provider_fee_cny is not None and not math.isfinite(self.provider_fee_cny):
            raise ValueError("attempt Provider fee must be finite")
        if self.subscription_nominal_cost_usd is not None and not math.isfinite(
            self.subscription_nominal_cost_usd
        ):
            raise ValueError("attempt nominal USD reference must be finite")
        if (self.billing_currency == "CNY") != (self.fee_ceiling is not None):
            raise ValueError("CNY attempt evidence requires its independent fee ceiling")
        if self.billing_currency != "CNY" and self.provider_fee_cny is not None:
            raise ValueError("non-CNY Provider attempt cannot carry a CNY fee")
        if (
            self.subscription_nominal_cost_usd is not None
            and self.billing_semantics != "subscription_quota_with_nominal_usd_reference"
        ):
            raise ValueError("nominal USD reference belongs only to a subscription route")
        if _V2_ATTEMPT_BILLING_PROFILES.get(self.provider_route) != (
            self.billing_semantics,
            self.billing_currency,
            self.fee_ceiling,
        ):
            raise ValueError("attempt Provider route and billing semantics are crossed")
        if any(
            not _MODEL_ID_PATTERN.fullmatch(model) or type(count) is not int or count < 0
            for model, count in self.observed_model_counts.items()
        ):
            raise ValueError("attempt observed-model counts are malformed")
        if self.outcome == "retryable_failure":
            if self.wait_seconds is None or self.failure_category not in {
                "connection",
                "timeout",
                "http_status",
                "malformed_structured_response",
            }:
                raise ValueError("retryable attempt is outside the frozen failure allowlist")
        elif self.wait_seconds is not None:
            raise ValueError("terminal attempt failure cannot carry another retry delay")
        if self.outcome == "attempts_exhausted" and self.attempt_number != _V2_MAXIMUM_ATTEMPTS:
            raise ValueError("attempt exhaustion is valid only at the physical-attempt cap")
        if self.failure_category == "http_status" and self.status_code is None:
            raise ValueError("HTTP attempt failure requires a status code")
        if self.lane_cooldown != (self.status_code in {429, 503}):
            raise ValueError("model-lane cooldown must be caused only by 429 or 503")
        observed_total = (
            sum(self.observed_model_counts.values())
            + self.observed_model_missing_response_count
            + self.observed_model_malformed_response_count
        )
        usage_total = (
            self.usage_complete_response_count
            + self.usage_missing_response_count
            + self.usage_malformed_response_count
        )
        if observed_total != self.provider_response_count or usage_total != self.provider_response_count:
            raise ValueError("attempt response evidence must close model and usage denominators")
        required_usage = (self.input_usage, self.output_usage, self.total_usage)
        if self.usage_complete_response_count == 0:
            if any(value is not None for value in (*required_usage, self.cached_input_usage)):
                raise ValueError("attempt without complete usage cannot carry token counters")
        elif any(value is None for value in required_usage):
            raise ValueError("attempt complete usage requires input, output, and total counters")
        if self.total_usage is not None and self.total_usage != (self.input_usage or 0) + (self.output_usage or 0):
            raise ValueError("attempt token usage is crossed")
        if self.cached_input_usage is not None and self.cached_input_usage > (self.input_usage or 0):
            raise ValueError("attempt cached-input usage exceeds total input usage")
        return self


class _V2Judgment(_V2FrozenModel):
    schema_version: Literal["concurrent-robustness-provider-judgment-v2"]
    judgment_id: str
    judgment_source_identity: str
    cell_index: int = Field(ge=0, lt=_V2_CELL_COUNT)
    cell_id: str
    pair_id: str
    pair_schedule_position: int = Field(ge=0)
    time_step: int = Field(ge=0)
    message_id: str
    user_id: str
    prompt_variant: str
    prompt_version: str
    prompt_canonical_hash: str
    requested_model: str
    observed_model: str
    provider_engage: bool
    provider_probability: float = Field(ge=0.0, le=1.0)
    provider_action: EngagementAction
    provider_reason: str
    provider_confidence: float = Field(ge=0.0, le=1.0)
    provider_decision_source: str
    environmental_consciousness_prompt_inclusion: Literal["included"]
    request_invocations: int = Field(ge=1, le=_V2_MAXIMUM_ATTEMPTS)
    provider_response_count: int = Field(ge=1)
    successful_decision_count: Literal[1]
    usage_complete: bool
    input_usage: int | None = Field(default=None, ge=0)
    output_usage: int | None = Field(default=None, ge=0)
    total_usage: int | None = Field(default=None, ge=0)
    cached_input_usage: int | None = Field(default=None, ge=0)
    attempt_evidence: tuple[_V2AttemptEvidence, ...]

    @field_validator("judgment_id", "judgment_source_identity")
    @classmethod
    def _validate_identity_hash(cls, value: str) -> str:
        return _require_sha256(value, "Judgment identity")

    @model_validator(mode="after")
    def _validate_judgment(self) -> _V2Judgment:
        if self.provider_engage != (self.provider_action in CONCURRENT_MESSAGE_POSITIVE_ACTIONS):
            raise ValueError("Provider Judgment engage and action are inconsistent")
        if self.provider_response_count < self.successful_decision_count:
            raise ValueError("Provider Judgment response accounting is inconsistent")
        if (
            len(self.attempt_evidence) != self.request_invocations
            or tuple(row.attempt_number for row in self.attempt_evidence)
            != tuple(range(1, self.request_invocations + 1))
            or self.attempt_evidence[-1].outcome != "succeeded"
            or any(row.outcome == "succeeded" for row in self.attempt_evidence[:-1])
        ):
            raise ValueError("Provider Judgment attempt evidence is incomplete or reordered")
        observed = Counter[str]()
        for attempt in self.attempt_evidence:
            observed.update(attempt.observed_model_counts)
        if (
            sum(row.provider_response_count for row in self.attempt_evidence)
            != self.provider_response_count
            or sum(row.successful_decision_count for row in self.attempt_evidence)
            != self.successful_decision_count
            or observed != Counter({self.observed_model: self.provider_response_count})
        ):
            raise ValueError("Provider Judgment is crossed with physical-attempt response evidence")

        def attempt_token_sum(field: str) -> int | None:
            values = [
                getattr(attempt, field)
                for attempt in self.attempt_evidence
                if getattr(attempt, field) is not None
            ]
            return sum(cast(list[int], values)) if values else None

        if (
            attempt_token_sum("input_usage") != self.input_usage
            or attempt_token_sum("output_usage") != self.output_usage
            or attempt_token_sum("total_usage") != self.total_usage
            or attempt_token_sum("cached_input_usage") != self.cached_input_usage
        ):
            raise ValueError("Provider Judgment token usage is crossed with physical attempts")
        required_usage = (self.input_usage, self.output_usage, self.total_usage)
        if self.usage_complete != all(value is not None for value in required_usage):
            raise ValueError("Provider Judgment usage completeness is inconsistent")
        if self.total_usage is not None and self.total_usage != (self.input_usage or 0) + (self.output_usage or 0):
            raise ValueError("Provider Judgment token usage total is crossed")
        if self.cached_input_usage is not None and self.cached_input_usage > (self.input_usage or 0):
            raise ValueError("Provider Judgment cached-input usage exceeds input usage")
        payload = self.model_dump(mode="json")
        payload.pop("judgment_id")
        if self.judgment_id != _json_sha256(payload):
            raise ValueError("Provider Judgment identity is crossed with its persisted facts")
        return self

    def decision(self) -> EngageDecision:
        return EngageDecision(
            engage=self.provider_engage,
            probability=self.provider_probability,
            action=self.provider_action,
            reason=self.provider_reason,
            confidence=self.provider_confidence,
            decision_source=self.provider_decision_source,
        )


class _V2RealizedTerminal(_V2FrozenModel):
    schema_version: Literal["concurrent-robustness-realized-terminal-v2"]
    realized_terminal_id: str
    judgment_id: str
    judgment_source_identity: str
    realization_source_identity: str
    cell_index: int = Field(ge=0, lt=_V2_CELL_COUNT)
    cell_id: str
    pair_id: str
    pair_schedule_position: int = Field(ge=0)
    time_step: int = Field(ge=0)
    message_id: str
    user_id: str
    prompt_variant: str
    prompt_version: str
    prompt_canonical_hash: str
    requested_model: str
    observed_model: str
    provider_engage: bool
    provider_probability: float = Field(ge=0.0, le=1.0)
    provider_action: EngagementAction
    provider_reason: str
    provider_confidence: float = Field(ge=0.0, le=1.0)
    provider_decision_source: str
    environmental_consciousness_prompt_inclusion: Literal["included"]
    request_invocations: int = Field(ge=1, le=_V2_MAXIMUM_ATTEMPTS)
    realization_key: str
    realization_rule_version: Literal["sha256-source-user-message-first-53-bits-uniform-v1"]
    realization_seed: Literal[20260823]
    realization_status: Literal["provider_ignore", "draw_pass", "draw_fail"]
    uniform_draw: float | None = Field(default=None, ge=0.0, lt=1.0)
    realized_engage: bool
    realized_action: EngagementAction

    @field_validator(
        "realized_terminal_id",
        "judgment_id",
        "judgment_source_identity",
        "realization_source_identity",
        "realization_key",
    )
    @classmethod
    def _validate_hash(cls, value: str) -> str:
        return _require_sha256(value, "v2 terminal identity")

    @model_validator(mode="after")
    def _validate_terminal(self) -> _V2RealizedTerminal:
        decision = EngageDecision(
            engage=self.provider_engage,
            probability=self.provider_probability,
            action=self.provider_action,
            reason=self.provider_reason,
            confidence=self.provider_confidence,
            decision_source=self.provider_decision_source,
        )
        expected = EngagementRealizationPolicy(
            source_identity=self.realization_source_identity,
            realization_seed=self.realization_seed,
            realization_rule_version=self.realization_rule_version,
        ).realize(decision, user_id=self.user_id, message_id=self.message_id)
        actual = (
            self.realization_key,
            self.realization_status,
            self.uniform_draw,
            self.realized_engage,
            self.realized_action,
        )
        expected_tuple = (
            expected.realization_key,
            expected.realization_status,
            expected.uniform_draw,
            expected.realized_engage,
            expected.realized_action,
        )
        if actual != expected_tuple:
            raise ValueError("v2 terminal realization differs from the shared policy")
        payload = self.model_dump(mode="json")
        payload.pop("realized_terminal_id")
        if self.realized_terminal_id != _json_sha256(payload):
            raise ValueError("v2 terminal identity is crossed with its persisted facts")
        return self

    def canonical_json_line(self) -> bytes:
        return _canonical_json_bytes(self.model_dump(mode="json"))


@dataclass(frozen=True)
class _V2LedgerReplay:
    records: tuple[dict[str, object], ...]
    state_by_pair: dict[str, str]
    record_by_pair: dict[str, dict[str, object]]
    previous_checksum: str | None


class _V2PairLedger:
    """Private append-only owner of the six-stage v2 pair lifecycle."""

    def __init__(self, root: Path, *, identity: Mapping[str, object]) -> None:
        self.root = root
        self.identity = _json_object(identity)
        self.identity_path = root / _V2_LEDGER_IDENTITY
        self.journal_path = root / _V2_LEDGER_JSONL
        self._replay = _V2LedgerReplay((), {}, {}, None)

    @classmethod
    def open(
        cls,
        root: Path,
        *,
        identity: Mapping[str, object],
    ) -> _V2PairLedger:
        if root.is_symlink():
            raise ValueError("v2 cell scope cannot be a symlink")
        root.mkdir(parents=True, exist_ok=True)
        ledger = cls(root, identity=identity)
        identity_exists = ledger.identity_path.exists()
        journal_exists = ledger.journal_path.exists()
        if identity_exists != journal_exists:
            raise ValueError("v2 pair lifecycle files are incomplete")
        expected_identity = _canonical_json_bytes(ledger.identity)
        if identity_exists:
            if (
                ledger.identity_path.is_symlink()
                or ledger.journal_path.is_symlink()
                or not ledger.identity_path.is_file()
                or not ledger.journal_path.is_file()
                or ledger.identity_path.read_bytes() != expected_identity
            ):
                raise ValueError("v2 pair lifecycle identity is crossed")
        else:
            _atomic_write_bytes(ledger.identity_path, expected_identity)
            with ledger.journal_path.open("xb") as handle:
                handle.flush()
                os.fsync(handle.fileno())
            _fsync_directory(root)
        ledger._replay = ledger._read_replay()
        return ledger

    @property
    def records(self) -> tuple[dict[str, object], ...]:
        return self._replay.records

    @property
    def state_by_pair(self) -> Mapping[str, str]:
        return self._replay.state_by_pair

    def state(self, pair_id: str) -> str | None:
        return self._replay.state_by_pair.get(pair_id)

    def latest(self, pair_id: str) -> Mapping[str, object] | None:
        return self._replay.record_by_pair.get(pair_id)

    def append_state(
        self,
        plan: _PairExecutionPlan,
        state: str,
        *,
        payload: Mapping[str, object] | None = None,
    ) -> None:
        prior = self.state(plan.pair_id)
        if state not in _V2_ALLOWED_TRANSITIONS.get(prior, set()):
            raise ValueError(f"v2 pair lifecycle transition {prior!r} -> {state!r} is invalid")
        record_without_checksum: dict[str, object] = {
            "schema_version": _V2_PAIR_LEDGER_SCHEMA,
            "sequence": len(self._replay.records) + 1,
            "previous_checksum": self._replay.previous_checksum,
            "cell_index": self.identity["cell_index"],
            "cell_id": self.identity["cell_id"],
            "pair_id": plan.pair_id,
            "pair_schedule_position": plan.pair_schedule_position,
            "time_step": plan.time_step,
            "message_id": plan.message.message_id,
            "user_id": plan.user.user_id,
            "state": state,
            "payload": _json_object(payload or {}),
        }
        record = {
            **record_without_checksum,
            "checksum": _json_sha256(record_without_checksum),
        }
        next_replay = self._apply_record(self._replay, record)
        encoded = _canonical_json_bytes(record)
        with self.journal_path.open("ab") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        self._replay = next_replay

    def judgments(self) -> tuple[_V2Judgment, ...]:
        rows: list[_V2Judgment] = []
        for record in self.records:
            if record["state"] != "judgment_persisted":
                continue
            payload = cast(dict[str, object], record["payload"])
            rows.append(_V2Judgment.model_validate(payload["judgment"]))
        return tuple(rows)

    def terminals(self) -> tuple[_V2RealizedTerminal, ...]:
        rows: list[_V2RealizedTerminal] = []
        for record in self.records:
            if record["state"] != "realized_persisted":
                continue
            payload = cast(dict[str, object], record["payload"])
            rows.append(_V2RealizedTerminal.model_validate(payload["terminal"]))
        return tuple(rows)

    def _read_replay(self) -> _V2LedgerReplay:
        replay = _V2LedgerReplay((), {}, {}, None)
        with self.journal_path.open("rb") as handle:
            for raw_line in handle:
                if not raw_line.endswith(b"\n"):
                    raise ValueError("v2 pair lifecycle contains a partial record")
                try:
                    record = json.loads(raw_line)
                except json.JSONDecodeError as exc:
                    raise ValueError("v2 pair lifecycle contains malformed JSON") from exc
                if not isinstance(record, dict) or raw_line != _canonical_json_bytes(record):
                    raise ValueError("v2 pair lifecycle is not canonical JSONL")
                replay = self._apply_record(replay, record)
        return replay

    def _apply_record(
        self,
        replay: _V2LedgerReplay,
        record: Mapping[str, object],
    ) -> _V2LedgerReplay:
        expected_keys = {
            "schema_version",
            "sequence",
            "previous_checksum",
            "cell_index",
            "cell_id",
            "pair_id",
            "pair_schedule_position",
            "time_step",
            "message_id",
            "user_id",
            "state",
            "payload",
            "checksum",
        }
        if set(record) != expected_keys or record.get("schema_version") != _V2_PAIR_LEDGER_SCHEMA:
            raise ValueError("v2 pair lifecycle record schema is invalid")
        if record.get("sequence") != len(replay.records) + 1:
            raise ValueError("v2 pair lifecycle sequence is not contiguous")
        if record.get("previous_checksum") != replay.previous_checksum:
            raise ValueError("v2 pair lifecycle checksum chain is broken")
        if record.get("cell_index") != self.identity["cell_index"] or record.get("cell_id") != self.identity["cell_id"]:
            raise ValueError("v2 pair lifecycle cell identity is crossed")
        body = {key: value for key, value in record.items() if key != "checksum"}
        checksum = record.get("checksum")
        if checksum != _json_sha256(body):
            raise ValueError("v2 pair lifecycle record checksum is invalid")
        pair_id = str(record.get("pair_id", ""))
        state = str(record.get("state", ""))
        if not pair_id:
            raise ValueError("v2 pair lifecycle pair identity is empty")
        prior = replay.state_by_pair.get(pair_id)
        if state not in _V2_ALLOWED_TRANSITIONS.get(prior, set()):
            raise ValueError("v2 pair lifecycle state transition is invalid")
        prior_record = replay.record_by_pair.get(pair_id)
        identity_keys = (
            "cell_index",
            "cell_id",
            "pair_id",
            "pair_schedule_position",
            "time_step",
            "message_id",
            "user_id",
        )
        if prior_record is not None and any(record.get(key) != prior_record.get(key) for key in identity_keys):
            raise ValueError("v2 pair lifecycle identity changed between stages")
        payload = record.get("payload")
        if not isinstance(payload, Mapping):
            raise ValueError("v2 pair lifecycle payload must be an object")
        if state == "pending":
            if payload:
                raise ValueError("pending lifecycle stage cannot carry a payload")
        elif state == "attempting":
            if payload:
                expected_attempt_keys = {
                    "phase",
                    "next_attempt_number",
                    "attempt_evidence",
                    "retry_delay_seconds",
                }
                if set(payload) != expected_attempt_keys or payload.get("phase") not in {
                    "pre_dispatch",
                    "dispatching",
                    "retry_wait",
                }:
                    raise ValueError("attempting lifecycle payload schema is invalid")
                next_attempt = payload.get("next_attempt_number")
                raw_attempts = payload.get("attempt_evidence")
                retry_delay = payload.get("retry_delay_seconds")
                if (
                    not isinstance(next_attempt, int)
                    or not 1 <= next_attempt <= _V2_MAXIMUM_ATTEMPTS
                    or not isinstance(raw_attempts, list)
                ):
                    raise ValueError("attempting lifecycle attempt cursor is invalid")
                attempts = tuple(_V2AttemptEvidence.model_validate(row) for row in raw_attempts)
                if (
                    tuple(row.attempt_number for row in attempts) != tuple(range(1, len(attempts) + 1))
                    or next_attempt != len(attempts) + 1
                    or any(row.outcome == "succeeded" for row in attempts)
                ):
                    raise ValueError("attempting lifecycle evidence is incomplete or crossed")
                phase = payload.get("phase")
                if phase == "retry_wait":
                    if (
                        not attempts
                        or attempts[-1].outcome != "retryable_failure"
                        or not isinstance(retry_delay, (int, float))
                        or float(retry_delay) < 0.0
                    ):
                        raise ValueError("retry-wait lifecycle evidence is invalid")
                elif retry_delay is not None:
                    raise ValueError("non-waiting attempt lifecycle cannot carry a delay")
        elif state == "reserved":
            if payload != {"maximum_physical_attempts": _V2_MAXIMUM_ATTEMPTS}:
                raise ValueError("reserved lifecycle payload does not freeze the attempt cap")
        elif state == "judgment_persisted":
            if set(payload) != {"judgment"}:
                raise ValueError("Judgment lifecycle payload schema is invalid")
            judgment = _V2Judgment.model_validate(payload.get("judgment"))
            self._validate_record_identity(record, judgment)
        elif state == "realized_persisted":
            if set(payload) != {"terminal"}:
                raise ValueError("Realized lifecycle payload schema is invalid")
            terminal = _V2RealizedTerminal.model_validate(payload.get("terminal"))
            self._validate_record_identity(record, terminal)
            if prior_record is None or prior_record.get("state") != "judgment_persisted":
                raise ValueError("Realized lifecycle record has no Judgment predecessor")
            prior_payload = cast(Mapping[str, object], prior_record["payload"])
            judgment = _V2Judgment.model_validate(prior_payload.get("judgment"))
            self._validate_terminal_judgment(terminal, judgment)
        elif state == "settled":
            if set(payload) != {"realized_terminal_id"}:
                raise ValueError("settled lifecycle payload schema is invalid")
            terminal_id = payload.get("realized_terminal_id")
            if not isinstance(terminal_id, str):
                raise ValueError("settled lifecycle record requires a terminal identity")
            if prior_record is None:
                raise ValueError("settled lifecycle record has no Realized predecessor")
            prior_payload = cast(Mapping[str, object], prior_record["payload"])
            prior_terminal = cast(Mapping[str, object], prior_payload.get("terminal"))
            if terminal_id != prior_terminal.get("realized_terminal_id"):
                raise ValueError("settled lifecycle terminal identity is crossed")
        else:
            self._validate_stopped_payload(record, payload)
        state_by_pair = dict(replay.state_by_pair)
        record_by_pair = dict(replay.record_by_pair)
        state_by_pair[pair_id] = state
        record_copy = _json_object(record)
        record_by_pair[pair_id] = record_copy
        return _V2LedgerReplay(
            records=(*replay.records, record_copy),
            state_by_pair=state_by_pair,
            record_by_pair=record_by_pair,
            previous_checksum=str(checksum),
        )

    @staticmethod
    def _validate_stopped_payload(
        record: Mapping[str, object],
        payload: Mapping[str, object],
    ) -> None:
        del record
        if (
            set(payload) != {"terminal_status", "failure_type", "request_invocations", "attempt_evidence"}
            or payload.get("terminal_status") != "provider_failed"
            or not isinstance(payload.get("failure_type"), str)
        ):
            raise ValueError("stopped lifecycle payload is not a non-decision terminal")
        request_invocations = payload.get("request_invocations")
        if not isinstance(request_invocations, int) or request_invocations < 0:
            raise ValueError("stopped lifecycle payload has invalid physical-attempt evidence")
        raw_attempts = payload.get("attempt_evidence")
        if not isinstance(raw_attempts, list):
            raise ValueError("stopped lifecycle payload requires an attempt evidence list")
        attempts = tuple(_V2AttemptEvidence.model_validate(row) for row in raw_attempts)
        if attempts and (
            len(attempts) != request_invocations
            or tuple(row.attempt_number for row in attempts) != tuple(range(1, request_invocations + 1))
            or any(row.outcome == "succeeded" for row in attempts)
        ):
            raise ValueError("stopped lifecycle physical-attempt evidence is incomplete")

    @staticmethod
    def _validate_terminal_judgment(
        terminal: _V2RealizedTerminal,
        judgment: _V2Judgment,
    ) -> None:
        shared_fields = (
            "judgment_source_identity",
            "cell_index",
            "cell_id",
            "pair_id",
            "pair_schedule_position",
            "time_step",
            "message_id",
            "user_id",
            "prompt_variant",
            "prompt_version",
            "prompt_canonical_hash",
            "requested_model",
            "observed_model",
            "provider_engage",
            "provider_probability",
            "provider_action",
            "provider_reason",
            "provider_confidence",
            "provider_decision_source",
            "environmental_consciousness_prompt_inclusion",
            "request_invocations",
        )
        if terminal.judgment_id != judgment.judgment_id or any(
            getattr(terminal, field) != getattr(judgment, field) for field in shared_fields
        ):
            raise ValueError("Realized terminal is crossed with its persisted Judgment")

    def _validate_record_identity(
        self,
        record: Mapping[str, object],
        row: _V2Judgment | _V2RealizedTerminal,
    ) -> None:
        cell = cast(Mapping[str, object], self.identity["cell"])
        if (
            row.cell_index != record.get("cell_index")
            or row.cell_id != record.get("cell_id")
            or row.pair_id != record.get("pair_id")
            or row.pair_schedule_position != record.get("pair_schedule_position")
            or row.time_step != record.get("time_step")
            or row.message_id != record.get("message_id")
            or row.user_id != record.get("user_id")
            or row.judgment_source_identity != self.identity["judgment_source_identity"]
            or row.prompt_variant != cell.get("prompt_variant")
            or row.prompt_version != cell.get("prompt_version")
            or row.prompt_canonical_hash != cell.get("prompt_canonical_hash")
            or row.requested_model != cell.get("requested_model")
            or row.observed_model != cell.get("required_observed_model")
        ):
            raise ValueError("v2 pair lifecycle payload identity is crossed")
        if isinstance(row, _V2RealizedTerminal) and (
            row.realization_source_identity != self.identity["realization_source_identity"]
        ):
            raise ValueError("v2 pair lifecycle realization identity is crossed")


@dataclass(frozen=True)
class _V2CellResult:
    cell_index: int
    cell_id: str
    judgment_source_identity: str
    runtime_identity_hash: str
    terminals: tuple[_V2RealizedTerminal, ...]
    commits: tuple[dict[str, object], ...]
    lifecycle_records: tuple[dict[str, object], ...]

    @property
    def physical_attempts(self) -> int:
        return sum(terminal.request_invocations for terminal in self.terminals)


@dataclass(frozen=True)
class _V2PublishedExecution:
    logical_judgments: int
    physical_attempts: int


class _V2ReconciliationRequired(RuntimeError):
    pass


class _V2SafePreCallStop(RuntimeError):
    pass


class _V2CellStopped(RuntimeError):
    pass


def _json_object(value: Mapping[str, object] | object) -> dict[str, object]:
    normalized = json.loads(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=str,
        )
    )
    if not isinstance(normalized, dict):
        raise TypeError("canonical payload must be an object")
    return cast(dict[str, object], normalized)


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_bytes(manifest: ConcurrentRobustnessManifestV2) -> bytes:
    return _canonical_json_bytes(manifest.model_dump(mode="json"))


def _workspace_payloads(
    output_path: Path,
    *,
    manifest: ConcurrentRobustnessManifestV2,
    manifest_sha256: str,
) -> dict[str, bytes]:
    validation = {
        "schema_version": _V2_WORKSPACE_VALIDATION_SCHEMA,
        "status": "ready_for_execution",
        "manifest_sha256": manifest_sha256,
        "execution_profile": manifest.execution_profile,
        "counts": {
            "cells": len(manifest.prompt_model_cells),
            "messages": len(manifest.message_ids),
            "batches_per_cell": manifest.ranking_contract.horizon,
            "delivery_capacity_per_message": manifest.ranking_contract.delivery_capacity,
            "logical_judgments_per_cell": manifest.request_caps.logical_judgments_per_cell,
            "logical_judgment_cap": manifest.request_caps.logical_judgment_cap,
            "physical_attempt_cap": manifest.request_caps.physical_attempt_cap,
            "formal_cells": _V2_CELL_COUNT,
            "formal_logical_judgments_per_cell": _V2_FORMAL_LOGICAL_PER_CELL,
            "formal_logical_judgment_cap": _V2_FORMAL_LOGICAL_CAP,
            "formal_physical_attempt_cap": _V2_FORMAL_PHYSICAL_CAP,
        },
        "checks": {
            "exact_twenty_cell_topology": True,
            "canonical_prompt_hashes": True,
            "frozen_ranking_and_barrier": True,
            "shared_realization_source_closed": True,
            "provider_attempts_zero": True,
        },
        "provider_calls": 0,
        "live_api_triggered": False,
        "production_deploy_eligible": False,
    }
    validation_bytes = _canonical_json_bytes(validation)
    registry = {
        "schema_version": _V2_WORKSPACE_REGISTRY_SCHEMA,
        "workspace_type": "private_resumable",
        "status": "ready_for_execution",
        "output_identity": manifest.output_identity,
        "output_root": str(output_path),
        "manifest_sha256": manifest_sha256,
        "realization_source_identity": manifest.realization_source.source_identity,
        "artifacts": {
            "study_manifest": _V2_WORKSPACE_MANIFEST,
            "validation_report": _V2_WORKSPACE_VALIDATION,
        },
        "sha256": {
            "study_manifest": manifest_sha256,
            "validation_report": hashlib.sha256(validation_bytes).hexdigest(),
        },
        "execution_directory": _V2_EXECUTION_DIR,
        "execution_anchor": f"{_V2_EXECUTION_DIR}/{_V2_EXECUTION_ANCHOR}",
        "provider_calls": 0,
        "live_api_triggered": False,
        "production_deploy_eligible": False,
    }
    return {
        _V2_WORKSPACE_MANIFEST: _manifest_bytes(manifest),
        _V2_WORKSPACE_VALIDATION: validation_bytes,
        _V2_WORKSPACE_REGISTRY: _canonical_json_bytes(registry),
    }


def _open_workspace(
    output_path: Path,
    *,
    manifest: ConcurrentRobustnessManifestV2,
    manifest_sha256: str,
) -> None:
    expected = _workspace_payloads(
        output_path,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
    )
    if output_path.exists():
        if output_path.is_symlink() or not output_path.is_dir():
            raise ValueError("v2 workspace must be a real directory")
        entries = {path.name: path for path in output_path.iterdir()}
        allowed = {*expected, _V2_EXECUTION_DIR}
        if not set(entries).issubset(allowed) or not set(expected).issubset(entries):
            raise ValueError("v2 workspace contains missing or unexpected entries")
        for name, payload in expected.items():
            path = entries[name]
            if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
                raise ValueError(f"v2 workspace artifact is crossed: {name}")
        execution = entries.get(_V2_EXECUTION_DIR)
        if execution is not None and (execution.is_symlink() or not execution.is_dir()):
            raise ValueError("v2 execution artifact must be a real directory")
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{output_path.name}.{manifest.output_identity}.",
            suffix=".v2-workspace-staging",
            dir=output_path.parent,
        )
    )
    try:
        for name, payload in expected.items():
            (staging / name).write_bytes(payload)
        if output_path.exists():
            raise ValueError("v2 workspace appeared during atomic creation")
        os.replace(staging, output_path)
        _fsync_directory(output_path.parent)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _operational_root(output_path: Path) -> Path:
    return output_path.parent / f".{output_path.name}.two-stage-v2-operational"


def _operational_identity(
    *,
    manifest: ConcurrentRobustnessManifestV2,
    manifest_sha256: str,
    output_path: Path,
) -> dict[str, object]:
    return {
        "schema_version": _V2_OPERATIONAL_IDENTITY_SCHEMA,
        "workspace_type": "private_resumable",
        "manifest_sha256": manifest_sha256,
        "source_manifest_sha256": manifest.source.manifest_sha256,
        "output_identity": manifest.output_identity,
        "output_root": str(output_path),
        "operational_root": str(_operational_root(output_path)),
        "realization_source_identity": manifest.realization_source.source_identity,
        "cells": [
            {
                "cell_index": index,
                "cell_id": cell.cell_id,
                "cell_scope": f"cell-{index:02d}",
            }
            for index, cell in enumerate(manifest.prompt_model_cells)
        ],
        "provider_calls": 0,
        "live_api_triggered": False,
        "production_deploy_eligible": False,
    }


def _open_operational_root(
    *,
    manifest: ConcurrentRobustnessManifestV2,
    manifest_sha256: str,
    output_path: Path,
) -> Path:
    root = _operational_root(output_path)
    expected_identity = _canonical_json_bytes(
        _operational_identity(
            manifest=manifest,
            manifest_sha256=manifest_sha256,
            output_path=output_path,
        )
    )
    allowed_cells = {f"cell-{index:02d}" for index in range(_V2_CELL_COUNT)}
    if root.exists():
        if root.is_symlink() or not root.is_dir():
            raise ValueError("v2 operational root must be a real directory")
        entries = {path.name: path for path in root.iterdir()}
        if not set(entries).issubset({_V2_OPERATIONAL_IDENTITY, _V2_OPERATIONAL_STATUS, *allowed_cells}):
            raise ValueError("v2 operational root contains an unexpected entry")
        identity_path = entries.get(_V2_OPERATIONAL_IDENTITY)
        status_path = entries.get(_V2_OPERATIONAL_STATUS)
        if (
            identity_path is None
            or status_path is None
            or identity_path.is_symlink()
            or status_path.is_symlink()
            or not identity_path.is_file()
            or not status_path.is_file()
            or identity_path.read_bytes() != expected_identity
        ):
            raise ValueError("v2 operational identity or status is incomplete")
        status = json.loads(status_path.read_text(encoding="utf-8"))
        if (
            not isinstance(status, dict)
            or status.get("schema_version") != _V2_OPERATIONAL_STATUS_SCHEMA
            or status.get("manifest_sha256") != manifest_sha256
        ):
            raise ValueError("v2 operational status is crossed")
        for name in set(entries).intersection(allowed_cells):
            if entries[name].is_symlink() or not entries[name].is_dir():
                raise ValueError("v2 operational cell scope is unsafe")
        return root

    root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{root.name}.{manifest.output_identity}.",
            suffix=".staging",
            dir=root.parent,
        )
    )
    try:
        (staging / _V2_OPERATIONAL_IDENTITY).write_bytes(expected_identity)
        (staging / _V2_OPERATIONAL_STATUS).write_bytes(
            _canonical_json_bytes(
                {
                    "schema_version": _V2_OPERATIONAL_STATUS_SCHEMA,
                    "lifecycle": "initialized",
                    "manifest_sha256": manifest_sha256,
                    "logical_judgments": 0,
                    "physical_attempts": 0,
                    "completed_cells": 0,
                    "last_cell_id": None,
                    "last_pair_id": None,
                    "provider_calls": 0,
                    "live_api_triggered": False,
                    "production_deploy_eligible": False,
                }
            )
        )
        os.replace(staging, root)
        _fsync_directory(root.parent)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return root


def _write_operational_status(
    root: Path,
    *,
    manifest_sha256: str,
    lifecycle: str,
    logical_judgments: int,
    physical_attempts: int,
    completed_cells: int,
    last_cell_id: str | None,
    last_pair_id: str | None,
) -> None:
    _atomic_write_bytes(
        root / _V2_OPERATIONAL_STATUS,
        _canonical_json_bytes(
            {
                "schema_version": _V2_OPERATIONAL_STATUS_SCHEMA,
                "lifecycle": lifecycle,
                "manifest_sha256": manifest_sha256,
                "logical_judgments": logical_judgments,
                "physical_attempts": physical_attempts,
                "completed_cells": completed_cells,
                "last_cell_id": last_cell_id,
                "last_pair_id": last_pair_id,
                "provider_calls": 0,
                "live_api_triggered": False,
                "production_deploy_eligible": False,
            }
        ),
    )


def _judgment_source_identity(
    *,
    manifest: ConcurrentRobustnessManifestV2,
    manifest_sha256: str,
    cell_index: int,
    cell: _PromptModelCell,
) -> str:
    return _json_sha256(
        {
            "schema_version": "concurrent-robustness-judgment-source-identity-v2",
            "manifest_sha256": manifest_sha256,
            "source_manifest_sha256": manifest.source.manifest_sha256,
            "sample_identity": manifest.sample.sample_identity,
            "message_snapshot_sha256": manifest.message_snapshot_sha256,
            "cell_index": cell_index,
            "cell": cell.model_dump(mode="json"),
        }
    )


def _cell_ledger_identity(
    *,
    manifest: ConcurrentRobustnessManifestV2,
    manifest_sha256: str,
    cell_index: int,
    cell: _PromptModelCell,
    cell_scope: Path,
) -> dict[str, object]:
    return {
        "schema_version": _V2_PAIR_LEDGER_IDENTITY_SCHEMA,
        "manifest_sha256": manifest_sha256,
        "source_manifest_sha256": manifest.source.manifest_sha256,
        "cell_index": cell_index,
        "cell_id": cell.cell_id,
        "cell": cell.model_dump(mode="json"),
        "judgment_source_identity": _judgment_source_identity(
            manifest=manifest,
            manifest_sha256=manifest_sha256,
            cell_index=cell_index,
            cell=cell,
        ),
        "realization_source_identity": manifest.realization_source.source_identity,
        "expected_logical_judgments": manifest.request_caps.logical_judgments_per_cell,
        "cell_scope": str(cell_scope),
        "production_deploy_eligible": False,
    }


def _runtime_identity(
    *,
    config: Any,
    prepared: _PreparedConcurrentRuntimeInputs,
    manifest: ConcurrentRobustnessManifestV2,
    manifest_sha256: str,
    cell_index: int,
    cell: _PromptModelCell,
    runtime_target: Path,
    runtime_workspace: Path,
    judgment_source_identity: str,
) -> dict[str, Any]:
    configuration = config.snapshot(
        sampling_status=VALIDATION_RUN_STATUS,
        production_deploy_eligible=False,
    )
    configuration.update(
        {
            "runtime_consumer": "concurrent_robustness_two_stage_v2",
            "realization_rule_version": REALIZATION_RULE_VERSION,
            "realization_seed": REALIZATION_SEED,
        }
    )
    prompt = CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.resolve(cell.prompt_version)
    return _json_object(
        _build_primary_only_concurrent_execution_run_identity(
            output_target=runtime_target,
            operational_workspace=runtime_workspace,
            configuration_snapshot=configuration,
            message_snapshot=[message.model_dump(mode="json") for message in config.messages],
            sample_audit=prepared.cohort.sample_audit,
            dataset_dir=config.dataset_dir,
            primary_provider_metadata={
                "adapter": "injected-deterministic-v2",
                "requested_model": cell.requested_model,
                "required_observed_model": cell.required_observed_model,
                "provider_calls": 0,
            },
            prompt_contract={"primary": prompt.audit_record()},
            execution_contract={
                "schema_version": "concurrent-robustness-two-stage-cell-execution-v2",
                "manifest_sha256": manifest_sha256,
                "cell_index": cell_index,
                "cell": cell.model_dump(mode="json"),
                "judgment_source_identity": judgment_source_identity,
                "realization_source_identity": manifest.realization_source.source_identity,
                "batch_barrier": manifest.batch_barrier.model_dump(mode="json"),
                "maximum_physical_attempts_per_judgment": _V2_MAXIMUM_ATTEMPTS,
                "production_deploy_eligible": False,
            },
        )
    )


@dataclass(frozen=True)
class _V2AdapterAttemptSnapshot:
    request_invocations: int
    accounting: ProviderAccounting
    provider_fee_cny_total: float | None
    subscription_nominal_cost_usd_total: float | None


def _v2_adapter_snapshot(adapter: LLMDecisionAdapter) -> _V2AdapterAttemptSnapshot:
    request_invocations = getattr(adapter, "request_invocations", None)
    accounting = getattr(adapter, "provider_accounting", None)
    if type(request_invocations) is not int or request_invocations < 0 or not isinstance(accounting, ProviderAccounting):
        raise ValueError("v2 Provider Adapter counters are unavailable")
    provider_fee = getattr(adapter, "provider_fee_cny_total", None)
    if provider_fee is not None and (
        isinstance(provider_fee, bool)
        or not isinstance(provider_fee, (int, float))
        or not math.isfinite(float(provider_fee))
        or float(provider_fee) < 0.0
    ):
        raise ValueError("v2 Provider Adapter CNY accounting is invalid")
    nominal_cost = getattr(adapter, "subscription_nominal_cost_usd_total", None)
    if nominal_cost is not None and (
        isinstance(nominal_cost, bool)
        or not isinstance(nominal_cost, (int, float))
        or not math.isfinite(float(nominal_cost))
        or float(nominal_cost) < 0.0
    ):
        raise ValueError("v2 subscription nominal USD accounting is invalid")
    return _V2AdapterAttemptSnapshot(
        request_invocations=request_invocations,
        accounting=accounting,
        provider_fee_cny_total=float(provider_fee) if provider_fee is not None else None,
        subscription_nominal_cost_usd_total=(
            float(nominal_cost) if nominal_cost is not None else None
        ),
    )


def _v2_attempt_evidence(
    *,
    adapter: LLMDecisionAdapter,
    before: _V2AdapterAttemptSnapshot,
    attempt_number: int,
    outcome: str,
    error: ProviderDecisionError | None,
    wait_seconds: float | None,
    wait_source: str | None,
) -> _V2AttemptEvidence:
    after = _v2_adapter_snapshot(adapter)
    request_delta = after.request_invocations - before.request_invocations
    accounting = provider_accounting_delta(after.accounting, before.accounting)
    if request_delta != 1 or accounting.external_request_invocations not in {0, 1}:
        raise ValueError("v2 concrete Adapter must execute exactly one physical attempt per decide call")
    request_evidence = getattr(adapter, "request_evidence", None)
    if not isinstance(request_evidence, Mapping):
        raise ValueError("v2 concrete Adapter is missing its safe request evidence")
    provider_fee_cny: float | None = None
    if before.provider_fee_cny_total is not None or after.provider_fee_cny_total is not None:
        if before.provider_fee_cny_total is None or after.provider_fee_cny_total is None:
            raise ValueError("v2 Provider CNY accounting disappeared during an attempt")
        provider_fee_cny = after.provider_fee_cny_total - before.provider_fee_cny_total
        if provider_fee_cny < 0.0:
            raise ValueError("v2 Provider CNY accounting is not monotonic")
    nominal_cost_usd: float | None = None
    if (
        before.subscription_nominal_cost_usd_total is not None
        or after.subscription_nominal_cost_usd_total is not None
    ):
        if (
            before.subscription_nominal_cost_usd_total is None
            or after.subscription_nominal_cost_usd_total is None
        ):
            raise ValueError("v2 subscription nominal cost disappeared during an attempt")
        nominal_cost_usd = (
            after.subscription_nominal_cost_usd_total
            - before.subscription_nominal_cost_usd_total
        )
        if nominal_cost_usd < 0.0:
            raise ValueError("v2 subscription nominal cost is not monotonic")
    payload = {
        "schema_version": "concurrent-robustness-provider-attempt-v2",
        "attempt_number": attempt_number,
        "outcome": outcome,
        "failure_category": None if error is None else error.failure_category,
        "status_code": None if error is None else error.status_code,
        "wait_source": wait_source,
        "wait_seconds": wait_seconds,
        "lane_cooldown": bool(error is not None and error.lane_cooldown),
        "request_invocations": 1,
        "provider_response_count": accounting.provider_response_count,
        "successful_decision_count": accounting.successful_decision_count,
        "observed_model_counts": accounting.observed_model_counts,
        "observed_model_missing_response_count": accounting.observed_model_missing_response_count,
        "observed_model_malformed_response_count": accounting.observed_model_malformed_response_count,
        "usage_complete_response_count": accounting.usage_complete_response_count,
        "usage_missing_response_count": accounting.usage_missing_response_count,
        "usage_malformed_response_count": accounting.usage_malformed_response_count,
        "input_usage": accounting.input_tokens,
        "output_usage": accounting.output_tokens,
        "total_usage": accounting.total_tokens,
        "cached_input_usage": accounting.cached_input_tokens,
        "provider_route": request_evidence.get("provider_route"),
        "billing_semantics": request_evidence.get("billing_semantics"),
        "billing_currency": request_evidence.get("billing_currency"),
        "provider_fee_cny": provider_fee_cny,
        "subscription_nominal_cost_usd": nominal_cost_usd,
        "fee_ceiling": request_evidence.get("fee_ceiling"),
    }
    return _V2AttemptEvidence.model_validate(payload)


class _V2ModelLane:
    """Private per-model serialization, retry, and cooldown policy."""

    def __init__(
        self,
        *,
        requested_model: str,
        backoff_seconds: float,
        provider_fee_cny_spent: float = 0.0,
    ) -> None:
        self.requested_model = requested_model
        self.backoff_seconds = backoff_seconds
        self.cooldown_until = 0.0
        self.provider_fee_cny_spent = provider_fee_cny_spent
        self._lock = threading.Lock()

    def _enforce_pre_call_ceiling(self, adapter: LLMDecisionAdapter) -> None:
        request_evidence = getattr(adapter, "request_evidence", None)
        if not isinstance(request_evidence, Mapping) or request_evidence.get("billing_currency") != "CNY":
            return
        ceiling = request_evidence.get("fee_ceiling")
        maximum_attempt_fee = getattr(adapter, "maximum_provider_fee_cny_per_attempt", None)
        if (
            isinstance(ceiling, bool)
            or not isinstance(ceiling, (int, float))
            or maximum_attempt_fee is None
        ):
            raise _V2SafePreCallStop("DeepSeek CNY dispatch lacks a safe fee reservation")
        if self.provider_fee_cny_spent + float(maximum_attempt_fee) > float(ceiling):
            raise _V2SafePreCallStop("DeepSeek CNY fee ceiling reached before dispatch")

    def _record_provider_fee(self, attempt: _V2AttemptEvidence) -> None:
        if attempt.provider_fee_cny is None:
            return
        self.provider_fee_cny_spent += attempt.provider_fee_cny
        if attempt.fee_ceiling is None or self.provider_fee_cny_spent > attempt.fee_ceiling:
            raise ValueError("DeepSeek CNY fee evidence exceeded its independent ceiling")

    def execute(
        self,
        adapter: LLMDecisionAdapter,
        decide: Callable[[], EngageDecision],
        *,
        prior_evidence: tuple[_V2AttemptEvidence, ...] = (),
        observer: Callable[[str, int, tuple[_V2AttemptEvidence, ...], float | None], None] | None = None,
    ) -> tuple[EngageDecision, tuple[_V2AttemptEvidence, ...]]:
        evidence = list(prior_evidence)
        if tuple(row.attempt_number for row in evidence) != tuple(range(1, len(evidence) + 1)):
            raise ValueError("v2 resumed attempt evidence is incomplete")
        with self._lock:
            for attempt_number in range(len(evidence) + 1, _V2_MAXIMUM_ATTEMPTS + 1):
                remaining_cooldown = self.cooldown_until - _V2_MONOTONIC()
                if remaining_cooldown > 0.0:
                    _V2_SLEEP(remaining_cooldown)
                self._enforce_pre_call_ceiling(adapter)
                if observer is not None:
                    observer("dispatching", attempt_number, tuple(evidence), None)
                before = _v2_adapter_snapshot(adapter)
                try:
                    decision = decide()
                except ProviderResponseProvenanceUnknown:
                    raise
                except ProviderDecisionError as exc:
                    has_retry = exc.retryable and attempt_number < _V2_MAXIMUM_ATTEMPTS
                    wait_seconds: float | None = None
                    wait_source: str | None = None
                    if has_retry:
                        if exc.wait_seconds is not None:
                            wait_seconds = exc.wait_seconds
                            wait_source = exc.wait_source or "provider_wait"
                        else:
                            wait_seconds = min(
                                self.backoff_seconds * (2 ** (attempt_number - 1)),
                                _V2_BACKOFF_CEILING_SECONDS,
                            )
                            wait_source = "exponential_backoff"
                    outcome = (
                        "retryable_failure"
                        if has_retry
                        else ("attempts_exhausted" if exc.retryable else "nonretryable_failure")
                    )
                    attempt_evidence = _v2_attempt_evidence(
                        adapter=adapter,
                        before=before,
                        attempt_number=attempt_number,
                        outcome=outcome,
                        error=exc,
                        wait_seconds=wait_seconds,
                        wait_source=wait_source,
                    )
                    self._record_provider_fee(attempt_evidence)
                    evidence.append(attempt_evidence)
                    if not has_retry:
                        exc.attempt_evidence = tuple(evidence)
                        raise
                    assert wait_seconds is not None
                    if observer is not None:
                        observer("retry_wait", attempt_number + 1, tuple(evidence), wait_seconds)
                    if exc.lane_cooldown:
                        self.cooldown_until = max(self.cooldown_until, _V2_MONOTONIC() + wait_seconds)
                    else:
                        _V2_SLEEP(wait_seconds)
                    continue
                attempt_evidence = _v2_attempt_evidence(
                    adapter=adapter,
                    before=before,
                    attempt_number=attempt_number,
                    outcome="succeeded",
                    error=None,
                    wait_seconds=None,
                    wait_source=None,
                )
                self._record_provider_fee(attempt_evidence)
                evidence.append(attempt_evidence)
                return decision, tuple(evidence)
        raise RuntimeError("v2 model lane exhausted without a terminal result")


class _V2LaneDecisionAdapter(LLMDecisionAdapter):
    """Private Adapter wrapper that keeps Provider policy outside the runtime kernel."""

    def __init__(self, adapter: LLMDecisionAdapter, lane: _V2ModelLane) -> None:
        self._adapter = adapter
        self._lane = lane
        self.prompt_version = str(cast(Any, adapter).prompt_version)
        self.last_attempt_evidence: tuple[_V2AttemptEvidence, ...] = ()
        self._prior_attempt_evidence: tuple[_V2AttemptEvidence, ...] = ()
        self._attempt_observer: (
            Callable[[str, int, tuple[_V2AttemptEvidence, ...], float | None], None] | None
        ) = None

    def prepare_attempt(
        self,
        *,
        prior_evidence: tuple[_V2AttemptEvidence, ...],
        observer: Callable[[str, int, tuple[_V2AttemptEvidence, ...], float | None], None],
    ) -> None:
        self._prior_attempt_evidence = prior_evidence
        self._attempt_observer = observer
        self.last_attempt_evidence = prior_evidence

    @property
    def request_invocations(self) -> int:
        return _v2_adapter_snapshot(self._adapter).request_invocations

    @property
    def external_request_invocations(self) -> int:
        return _adapter_external_request_invocations(self._adapter)

    @property
    def provider_accounting(self) -> ProviderAccounting:
        return _v2_adapter_snapshot(self._adapter).accounting

    @property
    def live_api_triggered(self) -> bool:
        return _adapter_live_api_triggered(self._adapter)

    def decide(
        self,
        post: Any,
        profile: Any,
        peer_context: Any,
        platform_context: Any = None,
        time_step: int = 0,
    ) -> EngageDecision:
        try:
            decision, evidence = self._lane.execute(
                self._adapter,
                lambda: self._adapter.decide(post, profile, peer_context, platform_context, time_step),
                prior_evidence=self._prior_attempt_evidence,
                observer=self._attempt_observer,
            )
        except ProviderDecisionError as exc:
            self.last_attempt_evidence = cast(tuple[_V2AttemptEvidence, ...], getattr(exc, "attempt_evidence", ()))
            raise
        self.last_attempt_evidence = evidence
        return decision


def _attempting_payload(
    *,
    phase: Literal["pre_dispatch", "dispatching", "retry_wait"],
    next_attempt_number: int,
    evidence: tuple[_V2AttemptEvidence, ...],
    retry_delay_seconds: float | None,
) -> dict[str, object]:
    return {
        "phase": phase,
        "next_attempt_number": next_attempt_number,
        "attempt_evidence": [row.model_dump(mode="json") for row in evidence],
        "retry_delay_seconds": retry_delay_seconds,
    }


def _safe_resumable_attempts(
    record: Mapping[str, object] | None,
) -> tuple[tuple[_V2AttemptEvidence, ...], float] | None:
    if record is None:
        return None
    payload = record.get("payload")
    if not isinstance(payload, Mapping) or payload.get("phase") not in {"pre_dispatch", "retry_wait"}:
        return None
    raw_attempts = payload.get("attempt_evidence")
    if not isinstance(raw_attempts, list):
        return None
    attempts = tuple(_V2AttemptEvidence.model_validate(row) for row in raw_attempts)
    next_attempt = payload.get("next_attempt_number")
    if (
        type(next_attempt) is not int
        or next_attempt != len(attempts) + 1
        or next_attempt > _V2_MAXIMUM_ATTEMPTS
    ):
        return None
    retry_delay = payload.get("retry_delay_seconds")
    return attempts, (float(retry_delay) if isinstance(retry_delay, (int, float)) else 0.0)


def _variant_accounting_from_attempts(
    attempts: tuple[_V2AttemptEvidence, ...],
) -> _VariantAttemptAccounting:
    if not attempts:
        raise ValueError("v2 logical pair has no physical-attempt evidence")
    observed: Counter[str] = Counter()
    for attempt in attempts:
        observed.update(attempt.observed_model_counts)

    def token_sum(field: str) -> int | None:
        values = [getattr(attempt, field) for attempt in attempts if getattr(attempt, field) is not None]
        return sum(cast(list[int], values)) if values else None

    provider_responses = sum(attempt.provider_response_count for attempt in attempts)
    usage_complete_responses = sum(attempt.usage_complete_response_count for attempt in attempts)
    return _VariantAttemptAccounting(
        request_invocations=len(attempts),
        provider_response_count=provider_responses,
        successful_decision_count=sum(attempt.successful_decision_count for attempt in attempts),
        observed_model_counts=dict(observed),
        observed_model_missing_response_count=sum(
            attempt.observed_model_missing_response_count for attempt in attempts
        ),
        observed_model_malformed_response_count=sum(
            attempt.observed_model_malformed_response_count for attempt in attempts
        ),
        usage_complete=provider_responses > 0 and usage_complete_responses == provider_responses,
        usage_complete_response_count=usage_complete_responses,
        usage_missing_response_count=sum(attempt.usage_missing_response_count for attempt in attempts),
        usage_malformed_response_count=sum(attempt.usage_malformed_response_count for attempt in attempts),
        input_usage=token_sum("input_usage"),
        output_usage=token_sum("output_usage"),
        total_usage=token_sum("total_usage"),
        cached_input_usage=token_sum("cached_input_usage"),
    )


def _preflight_adapters(
    manifest: ConcurrentRobustnessManifestV2,
    adapters_by_cell: Mapping[str, LLMDecisionAdapter],
) -> tuple[tuple[_PromptModelCell, LLMDecisionAdapter], ...]:
    expected_keys = tuple(cell.cell_id for cell in manifest.prompt_model_cells)
    try:
        actual_keys = tuple(adapters_by_cell)
    except Exception as exc:
        raise ConcurrentRobustnessError(
            ConcurrentRobustnessErrorCode.UNSUPPORTED_ADAPTERS,
            "v2 Adapter map cannot be enumerated safely",
        ) from exc
    if len(actual_keys) != len(set(actual_keys)) or set(actual_keys) != set(expected_keys):
        raise ConcurrentRobustnessError(
            ConcurrentRobustnessErrorCode.UNSUPPORTED_ADAPTERS,
            "v2 Adapter map must contain exactly the 20 canonical cell keys",
        )
    adapters: list[tuple[_PromptModelCell, LLMDecisionAdapter]] = []
    identities: set[int] = set()
    for cell in manifest.prompt_model_cells:
        adapter = adapters_by_cell[cell.cell_id]
        if not isinstance(adapter, LLMDecisionAdapter):
            raise ConcurrentRobustnessError(
                ConcurrentRobustnessErrorCode.UNSUPPORTED_ADAPTERS,
                "v2 validation requires one independent LLMDecisionAdapter per cell",
            )
        try:
            leaf, caches = _unwrap_adapter(adapter)
        except ValueError as exc:
            raise ConcurrentRobustnessError(
                ConcurrentRobustnessErrorCode.UNSUPPORTED_ADAPTERS,
                f"v2 Adapter wrapper chain is invalid for {cell.cell_id}",
            ) from exc
        if leaf is not adapter or caches or id(leaf) in identities:
            raise ConcurrentRobustnessError(
                ConcurrentRobustnessErrorCode.UNSUPPORTED_ADAPTERS,
                "v2 validation requires one unwrapped independent Adapter per cell",
            )
        identities.add(id(leaf))
        try:
            prompt_version = _adapter_prompt_version(adapter)
            request_invocations = getattr(adapter, "request_invocations", 0)
            external_invocations = _adapter_external_request_invocations(adapter)
            live_triggered = _adapter_live_api_triggered(adapter)
        except (TypeError, ValueError) as exc:
            raise ConcurrentRobustnessError(
                ConcurrentRobustnessErrorCode.UNSUPPORTED_ADAPTERS,
                f"v2 validation Adapter metadata is invalid for {cell.cell_id}",
            ) from exc
        if (
            getattr(adapter, "deterministic_validation", False) is not True
            or prompt_version != cell.prompt_version
            or not isinstance(request_invocations, int)
            or request_invocations != 0
            or external_invocations != 0
            or live_triggered
        ):
            raise ConcurrentRobustnessError(
                ConcurrentRobustnessErrorCode.UNSUPPORTED_ADAPTERS,
                f"v2 validation Adapter is not fresh, offline, or Prompt-bound for {cell.cell_id}",
            )
        if bool(getattr(adapter, "robustness_provider_adapter", False)):
            request_evidence = getattr(adapter, "request_evidence", None)
            expected_route = {
                "deepseek-v4-flash": "deepseek_official",
                "gemini-3.1-pro": "antigravity_openai_compatible_gateway",
                "gemini-3.8-flash-high": "antigravity_openai_compatible_gateway",
                "kimi-coding/k3-256k": "pi_kimi_oauth_subscription",
                "openai-codex/gpt-5.6-sol": "pi_openai_oauth_subscription",
            }[cell.requested_model]
            if not isinstance(request_evidence, Mapping) or any(
                request_evidence.get(key) != value
                for key, value in {
                    "requested_model": cell.requested_model,
                    "required_observed_model": cell.required_observed_model,
                    "prompt_version": cell.prompt_version,
                    "prompt_canonical_hash": cell.prompt_canonical_hash,
                    "provider_route": expected_route,
                    "structured_output_schema_version": "engage-decision-output-v1",
                    "maximum_physical_attempts_per_logical_pair": _V2_MAXIMUM_ATTEMPTS,
                }.items()
            ):
                raise ConcurrentRobustnessError(
                    ConcurrentRobustnessErrorCode.UNSUPPORTED_ADAPTERS,
                    f"v2 concrete Provider profile is crossed for {cell.cell_id}",
                )
            try:
                _v2_adapter_snapshot(adapter)
            except ValueError as exc:
                raise ConcurrentRobustnessError(
                    ConcurrentRobustnessErrorCode.UNSUPPORTED_ADAPTERS,
                    f"v2 concrete Provider accounting is unavailable for {cell.cell_id}",
                ) from exc
        adapters.append((cell, adapter))
    return tuple(adapters)


def _build_judgment(
    *,
    manifest: ConcurrentRobustnessManifestV2,
    cell_index: int,
    cell: _PromptModelCell,
    judgment_source_identity: str,
    plan: _PairExecutionPlan,
    decision: EngageDecision,
    accounting: Any,
    attempt_evidence: tuple[_V2AttemptEvidence, ...] | None = None,
) -> _V2Judgment:
    required_observed_model = cell.required_observed_model
    if required_observed_model is None:
        raise ValueError("v2 cell is missing its required observed model")
    observed_counts = dict(accounting.observed_model_counts)
    if (
        set(observed_counts) != {required_observed_model}
        or sum(observed_counts.values()) != accounting.provider_response_count
        or accounting.observed_model_missing_response_count != 0
        or accounting.observed_model_malformed_response_count != 0
    ):
        raise ValueError("v2 Judgment observed model drifted from the frozen cell")
    deterministic_zero_usage = (
        manifest.execution_profile == "deterministic_validation" and attempt_evidence is None
    )
    usage_complete = True if deterministic_zero_usage else accounting.usage_complete
    usage_complete_responses = (
        accounting.provider_response_count
        if deterministic_zero_usage
        else accounting.usage_complete_response_count
    )
    usage_missing_responses = 0 if deterministic_zero_usage else accounting.usage_missing_response_count
    usage_malformed_responses = (
        0 if deterministic_zero_usage else accounting.usage_malformed_response_count
    )
    input_usage = 0 if deterministic_zero_usage else accounting.input_usage
    output_usage = 0 if deterministic_zero_usage else accounting.output_usage
    total_usage = 0 if deterministic_zero_usage else accounting.total_usage
    cached_input_usage = 0 if deterministic_zero_usage else accounting.cached_input_usage
    if attempt_evidence is None:
        attempt_evidence = (
            _V2AttemptEvidence(
                schema_version="concurrent-robustness-provider-attempt-v2",
                attempt_number=1,
                outcome="succeeded",
                failure_category=None,
                status_code=None,
                wait_source=None,
                wait_seconds=None,
                lane_cooldown=False,
                request_invocations=1,
                provider_response_count=accounting.provider_response_count,
                successful_decision_count=accounting.successful_decision_count,
                observed_model_counts=accounting.observed_model_counts,
                observed_model_missing_response_count=accounting.observed_model_missing_response_count,
                observed_model_malformed_response_count=accounting.observed_model_malformed_response_count,
                usage_complete_response_count=usage_complete_responses,
                usage_missing_response_count=usage_missing_responses,
                usage_malformed_response_count=usage_malformed_responses,
                input_usage=input_usage,
                output_usage=output_usage,
                total_usage=total_usage,
                cached_input_usage=cached_input_usage,
                provider_route="injected_deterministic_validation",
                billing_semantics="none",
                billing_currency=None,
                fee_ceiling=None,
            ),
        )
    payload: dict[str, object] = {
        "schema_version": _V2_JUDGMENT_SCHEMA,
        "judgment_source_identity": judgment_source_identity,
        "cell_index": cell_index,
        "cell_id": cell.cell_id,
        "pair_id": plan.pair_id,
        "pair_schedule_position": plan.pair_schedule_position,
        "time_step": plan.time_step,
        "message_id": plan.message.message_id,
        "user_id": plan.user.user_id,
        "prompt_variant": cell.prompt_variant,
        "prompt_version": cell.prompt_version,
        "prompt_canonical_hash": cell.prompt_canonical_hash,
        "requested_model": cell.requested_model,
        "observed_model": required_observed_model,
        "provider_engage": decision.engage,
        "provider_probability": decision.probability,
        "provider_action": decision.action,
        "provider_reason": decision.reason,
        "provider_confidence": decision.confidence,
        "provider_decision_source": decision.decision_source,
        "environmental_consciousness_prompt_inclusion": "included",
        "request_invocations": accounting.request_invocations,
        "provider_response_count": accounting.provider_response_count,
        "successful_decision_count": accounting.successful_decision_count,
        "usage_complete": usage_complete,
        "input_usage": input_usage,
        "output_usage": output_usage,
        "total_usage": total_usage,
        "cached_input_usage": cached_input_usage,
        "attempt_evidence": [row.model_dump(mode="json") for row in attempt_evidence],
    }
    payload["judgment_id"] = _json_sha256(payload)
    return _V2Judgment.model_validate(payload)


def _build_realized_terminal(
    *,
    manifest: ConcurrentRobustnessManifestV2,
    judgment: _V2Judgment,
    realization: EngagementRealization,
) -> _V2RealizedTerminal:
    payload: dict[str, object] = {
        "schema_version": _V2_REALIZED_TERMINAL_SCHEMA,
        "judgment_id": judgment.judgment_id,
        "judgment_source_identity": judgment.judgment_source_identity,
        "realization_source_identity": manifest.realization_source.source_identity,
        "cell_index": judgment.cell_index,
        "cell_id": judgment.cell_id,
        "pair_id": judgment.pair_id,
        "pair_schedule_position": judgment.pair_schedule_position,
        "time_step": judgment.time_step,
        "message_id": judgment.message_id,
        "user_id": judgment.user_id,
        "prompt_variant": judgment.prompt_variant,
        "prompt_version": judgment.prompt_version,
        "prompt_canonical_hash": judgment.prompt_canonical_hash,
        "requested_model": judgment.requested_model,
        "observed_model": judgment.observed_model,
        "provider_engage": judgment.provider_engage,
        "provider_probability": judgment.provider_probability,
        "provider_action": judgment.provider_action,
        "provider_reason": judgment.provider_reason,
        "provider_confidence": judgment.provider_confidence,
        "provider_decision_source": judgment.provider_decision_source,
        "environmental_consciousness_prompt_inclusion": (judgment.environmental_consciousness_prompt_inclusion),
        "request_invocations": judgment.request_invocations,
        "realization_key": realization.realization_key,
        "realization_rule_version": REALIZATION_RULE_VERSION,
        "realization_seed": REALIZATION_SEED,
        "realization_status": realization.realization_status,
        "uniform_draw": realization.uniform_draw,
        "realized_engage": realization.realized_engage,
        "realized_action": realization.realized_action,
    }
    payload["realized_terminal_id"] = _json_sha256(payload)
    return _V2RealizedTerminal.model_validate(payload)


def _runtime_terminal(
    plan: _PairExecutionPlan,
    terminal: _V2RealizedTerminal,
) -> dict[str, object]:
    return {
        "terminal_row_id": f"{plan.pair_id}:primary",
        "pair_id": plan.pair_id,
        "pair_schedule_position": plan.pair_schedule_position,
        "time_step": plan.time_step,
        "message_id": plan.message.message_id,
        "user_id": plan.user.user_id,
        "decision_variant": "primary",
        "prompt_version": terminal.prompt_version,
        "context_source_key": f"{terminal.judgment_id}:realized",
        "cache_key": terminal.realization_key,
        "context_profile_payload": "{}",
        "peer_context_payload": "{}",
        "prompt_field_inclusion": "{}",
        "request_invocations": 0,
        "provider_response_count": 0,
        "successful_decision_count": 0,
        "observed_model_counts": "{}",
        "observed_model_missing_response_count": 0,
        "observed_model_malformed_response_count": 0,
        "usage_complete": "false",
        "usage_complete_response_count": 0,
        "usage_missing_response_count": 0,
        "usage_malformed_response_count": 0,
        "input_usage": "",
        "output_usage": "",
        "total_usage": "",
        "cached_input_usage": "",
        "terminal_status": "succeeded",
        "provider_status": "succeeded",
        "engage": "true" if terminal.realized_engage else "false",
        "probability": terminal.provider_probability,
        "confidence": terminal.provider_confidence,
        "action": terminal.realized_action,
        "reason": "",
        "decision_source": "engagement_realization",
        "failure_type": "",
        "provider_metadata": "{}",
    }


def _runtime_evidence(
    plan: _PairExecutionPlan,
    terminal: Mapping[str, object],
) -> dict[str, object]:
    return {
        "terminal_row_id": terminal["terminal_row_id"],
        "pair_id": plan.pair_id,
        "message_id": plan.message.message_id,
        "user_id": plan.user.user_id,
        "decision_variant": "primary",
        "prompt_version": terminal["prompt_version"],
        "context_source_key": terminal["context_source_key"],
        "cache_key": terminal["cache_key"],
        "profile_payload": {},
        "peer_context_payload": {},
        "prompt_field_inclusion": {},
        "request_invocations": 0,
        "provider_response_count": 0,
        "successful_decision_count": 0,
        "observed_model_counts": {},
        "observed_model_missing_response_count": 0,
        "observed_model_malformed_response_count": 0,
        "usage_complete": False,
        "usage_complete_response_count": 0,
        "usage_missing_response_count": 0,
        "usage_malformed_response_count": 0,
        "input_usage": None,
        "output_usage": None,
        "total_usage": None,
        "cached_input_usage": None,
        "terminal_status": "succeeded",
        "provider_status": "succeeded",
        "action": terminal["action"],
        "decision_source": "engagement_realization",
    }


def _commit_row(
    *,
    cell_index: int,
    cell_id: str,
    commit: _ConcurrentRuntimeBatchCommit,
) -> dict[str, object]:
    messages: list[dict[str, object]] = []
    for summary in commit.message_summaries:
        messages.append(
            {
                "message_id": summary["message_id"],
                "selected_user_ids": list(summary["selected_user_ids"]),
                "realized_positive_user_ids": list(summary["primary_positive_user_ids"]),
                "provider_failed_user_ids": list(summary["primary_provider_failed_user_ids"]),
            }
        )
    return {
        "schema_version": "concurrent-robustness-two-stage-batch-commit-v2",
        "cell_index": cell_index,
        "cell_id": cell_id,
        "time_step": commit.time_step,
        "frozen_campaign_engaged_user_ids": list(commit.frozen_campaign_engaged_user_ids),
        "committed_realized_positive_user_ids": list(commit.committed_primary_positive_user_ids),
        "messages": messages,
    }


def _sync_closed_pairs(
    *,
    kernel: _ConcurrentRuntimeKernel,
    ledger: _V2PairLedger,
) -> None:
    active = kernel.active_batch
    if active is None:
        return
    plans = cast(list[_PairExecutionPlan], active["batch_plans"])
    next_pair_index = int(active["next_pair_index"])
    for plan in plans[:next_pair_index]:
        state = ledger.state(plan.pair_id)
        if state == "settled":
            continue
        if state != "realized_persisted":
            raise ValueError("runtime pair closure is crossed with v2 lifecycle state")
        latest = ledger.latest(plan.pair_id)
        assert latest is not None
        payload = cast(Mapping[str, object], latest["payload"])
        terminal = _V2RealizedTerminal.model_validate(payload["terminal"])
        ledger.append_state(
            plan,
            "settled",
            payload={"realized_terminal_id": terminal.realized_terminal_id},
        )


def _run_cell(
    *,
    config: Any,
    prepared: _PreparedConcurrentRuntimeInputs,
    manifest: ConcurrentRobustnessManifestV2,
    manifest_sha256: str,
    cell_index: int,
    cell: _PromptModelCell,
    adapter: LLMDecisionAdapter,
    lane: _V2ModelLane | None,
    operational_root: Path,
) -> _V2CellResult:
    cell_scope = operational_root / f"cell-{cell_index:02d}"
    cell_scope.mkdir(parents=True, exist_ok=True)
    ledger_identity = _cell_ledger_identity(
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        cell_index=cell_index,
        cell=cell,
        cell_scope=cell_scope,
    )
    ledger = _V2PairLedger.open(cell_scope, identity=ledger_identity)
    judgment_source_identity = str(ledger_identity["judgment_source_identity"])
    runtime_target = cell_scope / "runtime"
    runtime_workspace = derive_concurrent_execution_workspace(runtime_target)
    if runtime_target.exists():
        raise ValueError("v2 private runtime target must remain absent")
    identity = _runtime_identity(
        config=config,
        prepared=prepared,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        cell_index=cell_index,
        cell=cell,
        runtime_target=runtime_target,
        runtime_workspace=runtime_workspace,
        judgment_source_identity=judgment_source_identity,
    )
    if runtime_workspace.exists():
        journal = ConcurrentExecutionJournal.open_resume(
            runtime_workspace,
            identity=identity,
        )
        replay = journal._replay_runtime()
    else:
        journal = ConcurrentExecutionJournal.open_new(
            runtime_workspace,
            identity=identity,
        )
        replay = None

    state = _ConcurrentRuntimeKernelState(
        cohort=prepared.cohort,
        exposed_by_message={message.message_id: set() for message in config.messages},
        campaign_engaged_user_ids=set(),
    )
    kernel = _ConcurrentRuntimeKernel.primary_only(
        config=config,
        state=state,
        base_network_by_user=prepared.base_network_by_user,
        neighbors_by_user=prepared.neighbors_by_user,
        journal=journal,
    )
    commits: list[dict[str, object]] = []
    execution_adapter: LLMDecisionAdapter = _V2LaneDecisionAdapter(adapter, lane) if lane is not None else adapter
    external_baseline = _adapter_external_request_invocations(execution_adapter)
    policy = EngagementRealizationPolicy(
        source_identity=manifest.realization_source.source_identity,
    )
    try:
        if replay is not None:
            restored = kernel.restore(
                replay,
                result_builder=_PrimaryOnlyConcurrentRuntimeConsumer._replayed_primary_result_row,
            )
            commits.extend(
                _commit_row(cell_index=cell_index, cell_id=cell.cell_id, commit=commit) for commit in restored
            )
            _sync_closed_pairs(kernel=kernel, ledger=ledger)
        if "stopped" in ledger.state_by_pair.values():
            raise _V2CellStopped(f"cell {cell.cell_id} is durably stopped")
        if "attempting" in ledger.state_by_pair.values():
            for pair_id, pair_state in ledger.state_by_pair.items():
                if pair_state != "attempting":
                    continue
                if not isinstance(execution_adapter, _V2LaneDecisionAdapter) or _safe_resumable_attempts(
                    ledger.latest(pair_id)
                ) is None:
                    raise _V2ReconciliationRequired(
                        f"cell {cell.cell_id} contains an unresolved dispatched attempt"
                    )
        while state.next_time_step < config.horizon:
            if kernel.active_batch is None:
                kernel.plan_batch()
            for plan in kernel.pending_plans():
                lifecycle = ledger.state(plan.pair_id)
                if lifecycle is None:
                    ledger.append_state(plan, "pending")
                    lifecycle = "pending"
                terminal_evidence = kernel.terminal_evidence(plan, "primary")
                if terminal_evidence is not None:
                    if lifecycle != "realized_persisted":
                        raise ValueError("runtime terminal is crossed with the v2 Realized lifecycle")
                    latest = ledger.latest(plan.pair_id)
                    assert latest is not None
                    payload = cast(Mapping[str, object], latest["payload"])
                    realized_terminal = _V2RealizedTerminal.model_validate(payload["terminal"])
                    expected_runtime = _runtime_terminal(plan, realized_terminal)
                    if terminal_evidence[0] != expected_runtime:
                        raise ValueError("persisted runtime terminal is crossed")
                else:
                    if lifecycle == "pending":
                        ledger.append_state(
                            plan,
                            "reserved",
                            payload={"maximum_physical_attempts": _V2_MAXIMUM_ATTEMPTS},
                        )
                        lifecycle = "reserved"
                    prior_attempt_evidence: tuple[_V2AttemptEvidence, ...] = ()
                    if lifecycle == "reserved":
                        kernel.start_pair(plan)
                        ledger.append_state(
                            plan,
                            "attempting",
                            payload=(
                                _attempting_payload(
                                    phase="pre_dispatch",
                                    next_attempt_number=1,
                                    evidence=(),
                                    retry_delay_seconds=None,
                                )
                                if isinstance(execution_adapter, _V2LaneDecisionAdapter)
                                else None
                            ),
                        )
                        lifecycle = "attempting"
                    if lifecycle == "attempting" and isinstance(execution_adapter, _V2LaneDecisionAdapter):
                        resumable = _safe_resumable_attempts(ledger.latest(plan.pair_id))
                        should_dispatch = resumable is not None
                        if resumable is not None:
                            prior_attempt_evidence, resume_delay = resumable
                            if resume_delay > 0.0:
                                _V2_SLEEP(resume_delay)
                    else:
                        should_dispatch = False

                    if lifecycle == "attempting":
                        if not should_dispatch and isinstance(execution_adapter, _V2LaneDecisionAdapter):
                            raise _V2ReconciliationRequired(f"pair {plan.pair_id} has an unresolved dispatched attempt")
                        if not should_dispatch:
                            should_dispatch = ledger.latest(plan.pair_id) is not None and not isinstance(
                                execution_adapter, _V2LaneDecisionAdapter
                            )
                        if not should_dispatch:
                            raise _V2ReconciliationRequired(f"pair {plan.pair_id} has an unresolved dispatched attempt")
                        if isinstance(execution_adapter, _V2LaneDecisionAdapter):

                            def observe_attempt(
                                phase: str,
                                next_attempt_number: int,
                                evidence: tuple[_V2AttemptEvidence, ...],
                                retry_delay_seconds: float | None,
                                *,
                                bound_plan: _PairExecutionPlan = plan,
                            ) -> None:
                                ledger.append_state(
                                    bound_plan,
                                    "attempting",
                                    payload=_attempting_payload(
                                        phase=cast(Literal["pre_dispatch", "dispatching", "retry_wait"], phase),
                                        next_attempt_number=next_attempt_number,
                                        evidence=evidence,
                                        retry_delay_seconds=retry_delay_seconds,
                                    ),
                                )

                            execution_adapter.prepare_attempt(
                                prior_evidence=prior_attempt_evidence,
                                observer=observe_attempt,
                            )
                        context = _primary_variant_context(
                            plan,
                            prompt_token=cell.prompt_version,
                        )
                        try:
                            attempt, accounting = _execute_runtime_variant(
                                adapter=execution_adapter,
                                context=context,
                                pair_schedule_position=plan.pair_schedule_position,
                                time_step=plan.time_step,
                                message_id=plan.message.message_id,
                                default_provider_metadata={
                                    "adapter": "injected-deterministic-v2",
                                    "requested_model": cell.requested_model,
                                },
                            )
                        except ProviderResponseProvenanceUnknown as exc:
                            if _adapter_external_request_invocations(
                                execution_adapter
                            ) != external_baseline or _adapter_live_api_triggered(
                                execution_adapter, baseline=external_baseline
                            ):
                                raise ConcurrentRobustnessError(
                                    ConcurrentRobustnessErrorCode.UNSUPPORTED_ADAPTERS,
                                    "deterministic v2 Adapter triggered an external request",
                                ) from exc
                            raise _V2ReconciliationRequired(
                                f"pair {plan.pair_id} requires explicit reconciliation"
                            ) from exc
                        except ValueError as exc:
                            if _adapter_external_request_invocations(
                                execution_adapter
                            ) != external_baseline or _adapter_live_api_triggered(
                                execution_adapter, baseline=external_baseline
                            ):
                                raise ConcurrentRobustnessError(
                                    ConcurrentRobustnessErrorCode.UNSUPPORTED_ADAPTERS,
                                    "deterministic v2 Adapter triggered an external request",
                                ) from exc
                            raise _V2ReconciliationRequired(
                                f"pair {plan.pair_id} returned unverifiable response accounting"
                            ) from exc
                        if (
                            isinstance(execution_adapter, _V2LaneDecisionAdapter)
                            and execution_adapter.last_attempt_evidence
                        ):
                            accounting = _variant_accounting_from_attempts(
                                execution_adapter.last_attempt_evidence
                            )
                        if _adapter_external_request_invocations(
                            execution_adapter
                        ) != external_baseline or _adapter_live_api_triggered(
                            execution_adapter, baseline=external_baseline
                        ):
                            raise ValueError("deterministic v2 Adapter triggered an external request")
                        terminal_row, _, _ = _build_runtime_terminal_row(
                            pair_id=plan.pair_id,
                            pair_schedule_position=plan.pair_schedule_position,
                            time_step=plan.time_step,
                            message_id=plan.message.message_id,
                            user_id=plan.user.user_id,
                            context=context,
                            attempt=attempt,
                            accounting=accounting,
                            default_provider_metadata={
                                "adapter": "injected-deterministic-v2",
                                "model": cell.required_observed_model,
                            },
                        )
                        if attempt.provider_failure is not None:
                            ledger.append_state(
                                plan,
                                "stopped",
                                payload={
                                    "terminal_status": "provider_failed",
                                    "failure_type": terminal_row["failure_type"],
                                    "request_invocations": accounting.request_invocations,
                                    "attempt_evidence": (
                                        [
                                            row.model_dump(mode="json")
                                            for row in execution_adapter.last_attempt_evidence
                                        ]
                                        if isinstance(execution_adapter, _V2LaneDecisionAdapter)
                                        else []
                                    ),
                                },
                            )
                            raise _V2CellStopped(f"cell {cell.cell_id} stopped on Provider failure")
                        if not isinstance(attempt.decision, EngageDecision):
                            raise ValueError("v2 Adapter did not return an EngageDecision")
                        judgment = _build_judgment(
                            manifest=manifest,
                            cell_index=cell_index,
                            cell=cell,
                            judgment_source_identity=judgment_source_identity,
                            plan=plan,
                            decision=attempt.decision,
                            accounting=accounting,
                            attempt_evidence=(
                                execution_adapter.last_attempt_evidence
                                if isinstance(execution_adapter, _V2LaneDecisionAdapter)
                                else None
                            ),
                        )
                        ledger.append_state(
                            plan,
                            "judgment_persisted",
                            payload={"judgment": judgment.model_dump(mode="json")},
                        )
                        lifecycle = "judgment_persisted"

                    if lifecycle == "judgment_persisted":
                        latest = ledger.latest(plan.pair_id)
                        assert latest is not None
                        payload = cast(Mapping[str, object], latest["payload"])
                        judgment = _V2Judgment.model_validate(payload["judgment"])
                        realization = policy.realize(
                            judgment.decision(),
                            user_id=plan.user.user_id,
                            message_id=plan.message.message_id,
                        )
                        realized_terminal = _build_realized_terminal(
                            manifest=manifest,
                            judgment=judgment,
                            realization=realization,
                        )
                        ledger.append_state(
                            plan,
                            "realized_persisted",
                            payload={"terminal": realized_terminal.model_dump(mode="json")},
                        )
                        lifecycle = "realized_persisted"
                    if lifecycle != "realized_persisted":
                        raise ValueError("v2 pair did not reach a Realized terminal")
                    latest = ledger.latest(plan.pair_id)
                    assert latest is not None
                    payload = cast(Mapping[str, object], latest["payload"])
                    realized_terminal = _V2RealizedTerminal.model_validate(payload["terminal"])
                    runtime_terminal = _runtime_terminal(plan, realized_terminal)
                    kernel.register_terminal(
                        plan=plan,
                        decision_variant="primary",
                        terminal_row=runtime_terminal,
                        variant_evidence=_runtime_evidence(plan, runtime_terminal),
                    )
                kernel.start_pair(plan)
                runtime_terminal = _runtime_terminal(plan, realized_terminal)
                kernel.close_primary_pair(
                    plan,
                    _PrimaryOnlyConcurrentRuntimeConsumer._primary_result_row(
                        plan,
                        runtime_terminal,
                    ),
                )
                ledger.append_state(
                    plan,
                    "settled",
                    payload={"realized_terminal_id": realized_terminal.realized_terminal_id},
                )
            commit = kernel.commit_primary_batch()
            commits.append(
                _commit_row(
                    cell_index=cell_index,
                    cell_id=cell.cell_id,
                    commit=commit,
                )
            )
        if kernel.runtime_resident_row_count != 0:
            raise ValueError("v2 runtime retained rows after full-batch commit")
        replay = journal._replay_runtime()
        if kernel.validate_spool(replay) != manifest.ranking_contract.horizon:
            raise ValueError("v2 runtime spool does not close every batch")
    finally:
        journal.close()

    terminals = ledger.terminals()
    judgments = ledger.judgments()
    if (
        len(terminals) != manifest.request_caps.logical_judgments_per_cell
        or len(judgments) != len(terminals)
        or len(commits) != manifest.ranking_contract.horizon
        or any(state != "settled" for state in ledger.state_by_pair.values())
    ):
        raise ValueError("v2 cell did not close its exact schedule and lifecycle")
    if [terminal.pair_schedule_position for terminal in terminals] != list(range(len(terminals))):
        raise ValueError("v2 terminal pair schedule is not contiguous")
    return _V2CellResult(
        cell_index=cell_index,
        cell_id=cell.cell_id,
        judgment_source_identity=judgment_source_identity,
        runtime_identity_hash=str(identity["identity_hash"]),
        terminals=terminals,
        commits=tuple(commits),
        lifecycle_records=ledger.records,
    )


def _publish_execution(
    output_path: Path,
    *,
    manifest: ConcurrentRobustnessManifestV2,
    manifest_sha256: str,
    cells: Sequence[_V2CellResult],
) -> _V2PublishedExecution:
    destination = output_path / _V2_EXECUTION_DIR
    if destination.exists():
        return _validate_published_execution(
            destination,
            manifest=manifest,
            manifest_sha256=manifest_sha256,
        )
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{_V2_EXECUTION_DIR}.{manifest.output_identity}.",
            suffix=".staging",
            dir=output_path,
        )
    )
    try:
        terminals_path = staging / "terminal_rows.jsonl"
        commits_path = staging / "batch_commits.jsonl"
        lifecycle_path = staging / "pair_lifecycle.jsonl"
        with (
            terminals_path.open("wb") as terminal_handle,
            commits_path.open("wb") as commit_handle,
            lifecycle_path.open("wb") as lifecycle_handle,
        ):
            for cell in cells:
                for terminal in cell.terminals:
                    terminal_handle.write(terminal.canonical_json_line())
                for commit in cell.commits:
                    commit_handle.write(_canonical_json_bytes(commit))
                for record in cell.lifecycle_records:
                    lifecycle_handle.write(_canonical_json_bytes(record))
        cell_registry = {
            "schema_version": _V2_CELL_REGISTRY_SCHEMA,
            "manifest_sha256": manifest_sha256,
            "realization_source_identity": manifest.realization_source.source_identity,
            "cells": [
                {
                    "cell_index": cell.cell_index,
                    "cell_id": cell.cell_id,
                    "judgment_source_identity": cell.judgment_source_identity,
                    "runtime_identity_hash": cell.runtime_identity_hash,
                    "logical_judgments": len(cell.terminals),
                    "physical_attempts": cell.physical_attempts,
                    "realized_terminals": len(cell.terminals),
                    "batch_commits": len(cell.commits),
                    "lifecycle_records": len(cell.lifecycle_records),
                }
                for cell in cells
            ],
            "provider_calls": 0,
            "live_api_triggered": False,
            "production_deploy_eligible": False,
        }
        (staging / "cell_registry.json").write_bytes(_canonical_json_bytes(cell_registry))
        logical = sum(len(cell.terminals) for cell in cells)
        physical = sum(cell.physical_attempts for cell in cells)
        artifacts = {}
        for name in sorted(_V2_EXECUTION_PAYLOAD_FILES):
            path = staging / name
            artifacts[name] = {
                "sha256": _sha256_file(path),
                "bytes": path.stat().st_size,
            }
        execution_manifest = {
            "schema_version": _V2_EXECUTION_SCHEMA,
            "classification": "deterministic_two_stage_validation",
            "manifest_sha256": manifest_sha256,
            "realization_source_identity": manifest.realization_source.source_identity,
            "counts": {
                "cells": len(cells),
                "logical_judgments": logical,
                "physical_attempts": physical,
                "realized_terminals": logical,
                "batch_commits": sum(len(cell.commits) for cell in cells),
            },
            "artifacts": artifacts,
            "provider_calls": 0,
            "live_api_triggered": False,
            "production_deploy_eligible": False,
        }
        execution_manifest_path = staging / "execution_manifest.json"
        execution_manifest_path.write_bytes(_canonical_json_bytes(execution_manifest))
        anchor_facts = {
            "schema_version": _V2_EXECUTION_ANCHOR_SCHEMA,
            "manifest_sha256": manifest_sha256,
            "execution_manifest_sha256": _sha256_file(execution_manifest_path),
        }
        anchor = {
            **anchor_facts,
            "anchor_identity": _json_sha256(anchor_facts),
        }
        anchor_path = staging / _V2_EXECUTION_ANCHOR
        anchor_path.write_bytes(_canonical_json_bytes(anchor))
        anchor_path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        _validate_published_execution(
            staging,
            manifest=manifest,
            manifest_sha256=manifest_sha256,
        )
        if destination.exists():
            raise ValueError("v2 execution appeared during atomic publication")
        os.replace(staging, destination)
        _fsync_directory(output_path)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return _validate_published_execution(
        destination,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
    )


def _read_canonical_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open("rb") as handle:
        for raw_line in handle:
            if not raw_line.endswith(b"\n"):
                raise ValueError(f"{path.name} contains a partial row")
            row = json.loads(raw_line)
            if not isinstance(row, dict) or raw_line != _canonical_json_bytes(row):
                raise ValueError(f"{path.name} is not canonical JSONL")
            rows.append(cast(dict[str, object], row))
    return rows


def _validate_terminal_cell_contract(
    terminal: _V2RealizedTerminal,
    *,
    manifest: ConcurrentRobustnessManifestV2,
    manifest_sha256: str,
) -> None:
    cell = manifest.prompt_model_cells[terminal.cell_index]
    expected_judgment_source = _judgment_source_identity(
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        cell_index=terminal.cell_index,
        cell=cell,
    )
    if (
        terminal.cell_id != cell.cell_id
        or terminal.judgment_source_identity != expected_judgment_source
        or terminal.prompt_variant != cell.prompt_variant
        or terminal.prompt_version != cell.prompt_version
        or terminal.prompt_canonical_hash != cell.prompt_canonical_hash
        or terminal.requested_model != cell.requested_model
        or terminal.observed_model != cell.required_observed_model
        or terminal.message_id not in manifest.message_ids
        or terminal.time_step >= manifest.ranking_contract.horizon
    ):
        raise ValueError("v2 terminal is crossed with its Prompt-Model cell contract")


def _string_list(value: object, context: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{context} must be a sequence")
    if not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{context} contains an invalid identity")
    return cast(list[str], list(value))


def _validate_published_lifecycle(
    *,
    lifecycle: Sequence[Mapping[str, object]],
    terminals: Sequence[_V2RealizedTerminal],
    manifest: ConcurrentRobustnessManifestV2,
    manifest_sha256: str,
) -> None:
    records_by_cell: dict[int, list[Mapping[str, object]]] = {index: [] for index in range(_V2_CELL_COUNT)}
    for record in lifecycle:
        cell_index = record.get("cell_index")
        if not isinstance(cell_index, int) or cell_index not in records_by_cell:
            raise ValueError("v2 published lifecycle cell index is invalid")
        records_by_cell[cell_index].append(record)
    expected_records_per_cell = manifest.request_caps.logical_judgments_per_cell * len(_V2_PAIR_STATES)
    replayed_terminals: list[_V2RealizedTerminal] = []
    replayed_judgments: list[_V2Judgment] = []
    for cell_index, cell in enumerate(manifest.prompt_model_cells):
        records = records_by_cell[cell_index]
        if len(records) < expected_records_per_cell:
            raise ValueError("v2 published lifecycle cell denominator is incomplete")
        ledger = _V2PairLedger(
            Path("."),
            identity={
                "cell_index": cell_index,
                "cell_id": cell.cell_id,
                "cell": cell.model_dump(mode="json"),
                "judgment_source_identity": _judgment_source_identity(
                    manifest=manifest,
                    manifest_sha256=manifest_sha256,
                    cell_index=cell_index,
                    cell=cell,
                ),
                "realization_source_identity": manifest.realization_source.source_identity,
            },
        )
        replay = _V2LedgerReplay((), {}, {}, None)
        for record in records:
            replay = ledger._apply_record(replay, record)
            if record.get("state") == "judgment_persisted":
                payload = cast(Mapping[str, object], record["payload"])
                replayed_judgments.append(_V2Judgment.model_validate(payload.get("judgment")))
            if record.get("state") == "realized_persisted":
                payload = cast(Mapping[str, object], record["payload"])
                replayed_terminals.append(_V2RealizedTerminal.model_validate(payload.get("terminal")))
        if len(replay.state_by_pair) != manifest.request_caps.logical_judgments_per_cell or any(
            state != "settled" for state in replay.state_by_pair.values()
        ):
            raise ValueError("v2 published lifecycle does not close every pair")
    if [row.model_dump(mode="json") for row in replayed_terminals] != [
        row.model_dump(mode="json") for row in terminals
    ]:
        raise ValueError("v2 terminal artifact is crossed with lifecycle evidence")
    deepseek_fee_cny = sum(
        attempt.provider_fee_cny or 0.0
        for judgment in replayed_judgments
        if judgment.requested_model == "deepseek-v4-flash"
        for attempt in judgment.attempt_evidence
    )
    if deepseek_fee_cny > 25.0:
        raise ValueError("v2 execution DeepSeek CNY fee exceeds the independent ceiling")


def _validate_batch_commits(
    *,
    terminals: Sequence[_V2RealizedTerminal],
    commits: Sequence[Mapping[str, object]],
    manifest: ConcurrentRobustnessManifestV2,
) -> None:
    terminals_by_batch: dict[tuple[int, int], list[_V2RealizedTerminal]] = {}
    pair_keys_by_cell: dict[int, set[tuple[str, str]]] = {index: set() for index in range(_V2_CELL_COUNT)}
    for terminal in terminals:
        batch_key = (terminal.cell_index, terminal.time_step)
        terminals_by_batch.setdefault(batch_key, []).append(terminal)
        pair_key = (terminal.user_id, terminal.message_id)
        if pair_key in pair_keys_by_cell[terminal.cell_index]:
            raise ValueError("v2 execution repeats a message-level exposure")
        pair_keys_by_cell[terminal.cell_index].add(pair_key)

    expected_commit_keys = [
        (cell_index, time_step)
        for cell_index in range(_V2_CELL_COUNT)
        for time_step in range(manifest.ranking_contract.horizon)
    ]
    actual_commit_keys = [(int(str(commit.get("cell_index"))), int(str(commit.get("time_step")))) for commit in commits]
    if actual_commit_keys != expected_commit_keys:
        raise ValueError("v2 batch commits are missing, duplicated, or out of order")

    campaign_feedback_by_cell: dict[int, set[str]] = {index: set() for index in range(_V2_CELL_COUNT)}
    for commit in commits:
        if commit.get("schema_version") != "concurrent-robustness-two-stage-batch-commit-v2":
            raise ValueError("v2 batch commit schema is unsupported")
        cell_index = int(str(commit["cell_index"]))
        time_step = int(str(commit["time_step"]))
        if commit.get("cell_id") != manifest.prompt_model_cells[cell_index].cell_id:
            raise ValueError("v2 batch commit cell identity is crossed")
        frozen = _string_list(
            commit.get("frozen_campaign_engaged_user_ids"),
            "v2 frozen campaign feedback",
        )
        if frozen != sorted(campaign_feedback_by_cell[cell_index]):
            raise ValueError("v2 batch start did not freeze only prior committed feedback")
        batch_terminals = sorted(
            terminals_by_batch.get((cell_index, time_step), []),
            key=lambda row: row.pair_schedule_position,
        )
        if len(batch_terminals) != (len(manifest.message_ids) * manifest.ranking_contract.delivery_capacity):
            raise ValueError("v2 full-batch barrier lacks a Realized terminal")
        messages = commit.get("messages")
        if not isinstance(messages, Sequence) or isinstance(messages, (str, bytes)):
            raise ValueError("v2 batch commit messages must be a sequence")
        message_rows = [cast(Mapping[str, object], row) for row in messages if isinstance(row, Mapping)]
        if [row.get("message_id") for row in message_rows] != list(manifest.message_ids):
            raise ValueError("v2 batch commit message order is crossed")
        committed_from_messages: set[str] = set()
        for message_id, message_row in zip(manifest.message_ids, message_rows, strict=True):
            message_terminals = [terminal for terminal in batch_terminals if terminal.message_id == message_id]
            selected = [terminal.user_id for terminal in message_terminals]
            if (
                _string_list(
                    message_row.get("selected_user_ids"),
                    "v2 selected users",
                )
                != selected
            ):
                raise ValueError("v2 batch selected users are crossed with terminals")
            realized_positive = [terminal.user_id for terminal in message_terminals if terminal.realized_engage]
            if (
                _string_list(
                    message_row.get("realized_positive_user_ids"),
                    "v2 realized-positive users",
                )
                != realized_positive
            ):
                raise ValueError("v2 message feedback is crossed with Realized actions")
            if _string_list(
                message_row.get("provider_failed_user_ids"),
                "v2 Provider-failed users",
            ):
                raise ValueError("a committed v2 batch cannot contain Provider failures")
            committed_from_messages.update(realized_positive)
        committed = _string_list(
            commit.get("committed_realized_positive_user_ids"),
            "v2 committed realized-positive users",
        )
        if committed != sorted(committed_from_messages):
            raise ValueError("v2 campaign feedback is not the deduplicated Realized-positive set")
        campaign_feedback_by_cell[cell_index].update(committed)


def _validate_published_execution(
    root: Path,
    *,
    manifest: ConcurrentRobustnessManifestV2,
    manifest_sha256: str,
) -> _V2PublishedExecution:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("v2 execution root must be a real directory")
    entries = {path.name: path for path in root.iterdir()}
    if set(entries) != _V2_EXECUTION_FILES:
        raise ValueError("v2 execution artifact inventory is incomplete")
    if any(path.is_symlink() or not path.is_file() for path in entries.values()):
        raise ValueError("v2 execution inventory contains a non-regular file")
    anchor_path = entries[_V2_EXECUTION_ANCHOR]
    anchor_raw = anchor_path.read_bytes()
    anchor = json.loads(anchor_raw)
    if (
        not isinstance(anchor, dict)
        or anchor_raw != _canonical_json_bytes(anchor)
        or set(anchor)
        != {
            "schema_version",
            "manifest_sha256",
            "execution_manifest_sha256",
            "anchor_identity",
        }
        or anchor.get("schema_version") != _V2_EXECUTION_ANCHOR_SCHEMA
        or anchor.get("manifest_sha256") != manifest_sha256
        or anchor_path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
    ):
        raise ValueError("v2 execution immutable anchor is invalid")
    anchor_facts = {key: value for key, value in anchor.items() if key != "anchor_identity"}
    if anchor.get("anchor_identity") != _json_sha256(anchor_facts) or anchor.get(
        "execution_manifest_sha256"
    ) != _sha256_file(entries["execution_manifest.json"]):
        raise ValueError("v2 execution manifest is not bound to its immutable anchor")
    execution_manifest = json.loads(entries["execution_manifest.json"].read_text(encoding="utf-8"))
    if (
        not isinstance(execution_manifest, dict)
        or execution_manifest.get("schema_version") != _V2_EXECUTION_SCHEMA
        or execution_manifest.get("manifest_sha256") != manifest_sha256
        or execution_manifest.get("realization_source_identity") != manifest.realization_source.source_identity
        or execution_manifest.get("provider_calls") != 0
        or execution_manifest.get("live_api_triggered") is not False
        or execution_manifest.get("production_deploy_eligible") is not False
    ):
        raise ValueError("v2 execution manifest identity is crossed")
    artifacts = execution_manifest.get("artifacts")
    if not isinstance(artifacts, Mapping) or set(artifacts) != _V2_EXECUTION_PAYLOAD_FILES:
        raise ValueError("v2 execution artifact registry is incomplete")
    for name, reference in artifacts.items():
        if (
            not isinstance(reference, Mapping)
            or reference.get("sha256") != _sha256_file(entries[name])
            or reference.get("bytes") != entries[name].stat().st_size
        ):
            raise ValueError("v2 execution artifact hash is invalid")

    terminals = [
        _V2RealizedTerminal.model_validate(row) for row in _read_canonical_jsonl(entries["terminal_rows.jsonl"])
    ]
    commits = _read_canonical_jsonl(entries["batch_commits.jsonl"])
    lifecycle = _read_canonical_jsonl(entries["pair_lifecycle.jsonl"])
    registry = json.loads(entries["cell_registry.json"].read_text(encoding="utf-8"))
    if (
        not isinstance(registry, dict)
        or registry.get("schema_version") != _V2_CELL_REGISTRY_SCHEMA
        or registry.get("manifest_sha256") != manifest_sha256
        or registry.get("realization_source_identity") != manifest.realization_source.source_identity
        or registry.get("provider_calls") != 0
        or registry.get("live_api_triggered") is not False
    ):
        raise ValueError("v2 cell registry is crossed")
    expected_cell_ids = [cell.cell_id for cell in manifest.prompt_model_cells]
    registry_cells = registry.get("cells")
    if (
        not isinstance(registry_cells, list)
        or [row.get("cell_id") for row in registry_cells if isinstance(row, Mapping)] != expected_cell_ids
    ):
        raise ValueError("v2 cell registry order is invalid")

    if len(terminals) != manifest.request_caps.logical_judgment_cap:
        raise ValueError("v2 execution terminal denominator is incomplete")
    terminal_ids = [terminal.realized_terminal_id for terminal in terminals]
    if len(terminal_ids) != len(set(terminal_ids)):
        raise ValueError("v2 execution contains duplicate Realized terminals")
    by_cell = Counter(terminal.cell_id for terminal in terminals)
    if by_cell != Counter(
        {cell.cell_id: manifest.request_caps.logical_judgments_per_cell for cell in manifest.prompt_model_cells}
    ):
        raise ValueError("v2 execution cell terminal denominators are crossed")
    if any(
        terminal.realization_source_identity != manifest.realization_source.source_identity for terminal in terminals
    ):
        raise ValueError("v2 execution crossed the shared realization identity")
    for terminal in terminals:
        _validate_terminal_cell_contract(
            terminal,
            manifest=manifest,
            manifest_sha256=manifest_sha256,
        )
    positions_by_cell: dict[int, list[int]] = {index: [] for index in range(_V2_CELL_COUNT)}
    for terminal in terminals:
        positions_by_cell[terminal.cell_index].append(terminal.pair_schedule_position)
    expected_positions = list(range(manifest.request_caps.logical_judgments_per_cell))
    if any(sorted(positions) != expected_positions for positions in positions_by_cell.values()):
        raise ValueError("v2 execution pair schedule positions are incomplete or crossed")
    expected_commits = _V2_CELL_COUNT * manifest.ranking_contract.horizon
    if len(commits) != expected_commits:
        raise ValueError("v2 execution batch barrier evidence is incomplete")
    _validate_batch_commits(
        terminals=terminals,
        commits=commits,
        manifest=manifest,
    )
    if len(lifecycle) < len(terminals) * len(_V2_PAIR_STATES):
        raise ValueError("v2 execution lifecycle evidence is incomplete")
    _validate_published_lifecycle(
        lifecycle=lifecycle,
        terminals=terminals,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
    )
    physical_attempts = sum(terminal.request_invocations for terminal in terminals)
    counts = execution_manifest.get("counts")
    expected_counts = {
        "cells": _V2_CELL_COUNT,
        "logical_judgments": len(terminals),
        "physical_attempts": physical_attempts,
        "realized_terminals": len(terminals),
        "batch_commits": len(commits),
    }
    if counts != expected_counts:
        raise ValueError("v2 execution manifest counts are crossed")
    return _V2PublishedExecution(
        logical_judgments=len(terminals),
        physical_attempts=physical_attempts,
    )


def _operational_progress(root: Path) -> tuple[int, int, int, str | None, str | None]:
    logical = 0
    physical = 0
    completed = 0
    last_cell: str | None = None
    last_pair: str | None = None
    for cell_scope in sorted(root.glob("cell-*")):
        identity_path = cell_scope / _V2_LEDGER_IDENTITY
        journal_path = cell_scope / _V2_LEDGER_JSONL
        if not identity_path.is_file() or not journal_path.is_file():
            raise ValueError("v2 operational cell lifecycle is incomplete")
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
        ledger = _V2PairLedger.open(cell_scope, identity=identity)
        judgments = ledger.judgments()
        terminals = ledger.terminals()
        stopped_records = [record for record in ledger.records if record.get("state") == "stopped"]
        unresolved_records: list[Mapping[str, object]] = []
        for pair_id, state in ledger.state_by_pair.items():
            latest = ledger.latest(pair_id)
            if state == "attempting" and latest is not None:
                unresolved_records.append(latest)
        logical += len(judgments) + len(stopped_records) + len(unresolved_records)
        physical += sum(judgment.request_invocations for judgment in judgments)
        physical += sum(
            int(str(cast(Mapping[str, object], record["payload"])["request_invocations"])) for record in stopped_records
        )
        for record in unresolved_records:
            payload = cast(Mapping[str, object], record["payload"])
            raw_attempts = payload.get("attempt_evidence")
            completed_attempts = len(raw_attempts) if isinstance(raw_attempts, list) else 0
            # A dispatching/legacy marker reserves the in-flight attempt. A
            # pre-dispatch or retry-wait marker remains safely resumable and
            # counts only already persisted attempts.
            physical += completed_attempts + (payload.get("phase") in {None, "dispatching"})
        if len(terminals) == int(str(identity["expected_logical_judgments"])) and all(
            state == "settled" for state in ledger.state_by_pair.values()
        ):
            completed += 1
        if ledger.records:
            last_cell = str(identity.get("cell_id"))
            last_pair = str(ledger.records[-1].get("pair_id"))
    return logical, physical, completed, last_cell, last_pair


def _operational_provider_fee_cny(root: Path) -> dict[str, float]:
    totals: dict[str, float] = {}
    for cell_scope in sorted(root.glob("cell-*")):
        identity_path = cell_scope / _V2_LEDGER_IDENTITY
        journal_path = cell_scope / _V2_LEDGER_JSONL
        if not identity_path.is_file() or not journal_path.is_file():
            raise ValueError("v2 operational fee evidence is incomplete")
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
        cell = identity.get("cell")
        if not isinstance(cell, Mapping):
            raise ValueError("v2 operational fee cell identity is malformed")
        requested_model = cell.get("requested_model")
        if not isinstance(requested_model, str):
            raise ValueError("v2 operational fee model identity is malformed")
        ledger = _V2PairLedger.open(cell_scope, identity=identity)
        attempts_by_pair: dict[str, tuple[_V2AttemptEvidence, ...]] = {}
        for record in ledger.records:
            pair_id = str(record["pair_id"])
            payload = cast(Mapping[str, object], record["payload"])
            raw_attempts: object | None = None
            if record["state"] == "judgment_persisted":
                judgment = _V2Judgment.model_validate(payload.get("judgment"))
                attempts_by_pair[pair_id] = judgment.attempt_evidence
                continue
            if record["state"] in {"attempting", "stopped"}:
                raw_attempts = payload.get("attempt_evidence")
            if isinstance(raw_attempts, list):
                attempts_by_pair[pair_id] = tuple(
                    _V2AttemptEvidence.model_validate(attempt) for attempt in raw_attempts
                )
        total = sum(
            attempt.provider_fee_cny or 0.0
            for attempts in attempts_by_pair.values()
            for attempt in attempts
        )
        totals[requested_model] = totals.get(requested_model, 0.0) + total
    if totals.get("deepseek-v4-flash", 0.0) > 25.0:
        raise ValueError("v2 operational DeepSeek CNY fee exceeds the independent ceiling")
    return totals


def _result(
    *,
    status: ConcurrentRobustnessStudyStatus,
    output_path: Path,
    manifest_sha256: str,
    logical: int,
    physical: int,
    study_root: Path | None = None,
) -> ConcurrentRobustnessStudyResult:
    return ConcurrentRobustnessStudyResult(
        status=status,
        workspace_root=output_path,
        validation_report=(
            study_root / _V2_WORKSPACE_VALIDATION
            if study_root is not None
            else output_path / _V2_WORKSPACE_VALIDATION
        ),
        manifest_sha256=manifest_sha256,
        logical_provider_attempts=logical,
        physical_provider_attempts=physical,
        study_root=study_root,
        report_candidate=None,
    )


def _close_v2_study_result(
    *,
    output_path: Path,
    manifest_sha256: str,
    published: _V2PublishedExecution,
) -> ConcurrentRobustnessStudyResult:
    from .concurrent_robustness_v2_evidence import close_concurrent_robustness_v2_study

    closed = close_concurrent_robustness_v2_study(output_path)
    if (
        closed.manifest_sha256 != manifest_sha256
        or closed.logical_judgments != published.logical_judgments
        or closed.physical_attempts != published.physical_attempts
    ):
        raise ValueError("v2 Evidence closure is crossed with the completed execution")
    return _result(
        status=ConcurrentRobustnessStudyStatus.COMPLETE,
        output_path=output_path,
        manifest_sha256=manifest_sha256,
        logical=closed.logical_judgments,
        physical=closed.physical_attempts,
        study_root=closed.root_path,
    )


def _run_concurrent_robustness_v2(
    *,
    manifest: ConcurrentRobustnessManifestV2,
    adapters_by_cell: Mapping[str, LLMDecisionAdapter] | None,
    output_dir: str | Path,
    report_destination: str | Path | None,
) -> ConcurrentRobustnessStudyResult:
    """Exact v2 dispatch target; v1 execution remains wholly untouched."""

    if report_destination is not None:
        raise ConcurrentRobustnessError(
            ConcurrentRobustnessErrorCode.ANALYSIS_INVALID,
            "v2 report composition belongs to a later closed Evidence contract",
        )
    source_path = _resolve_source_path(manifest.source.source_dir)
    output_path = _resolve_output_path(output_dir)
    _validate_study_paths(source_path, output_path)
    closure = _close_source(source_path)
    try:
        _validate_source_against_manifest(manifest, closure, source_path)  # type: ignore[arg-type]
        config = _dynamic_runtime_config(closure)
        prepared = _prepare_concurrent_runtime_inputs(config)
        prepared_identity = hashlib.sha256(
            json.dumps(
                prepared.cohort.sample_user_ids,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if prepared_identity != manifest.sample.sample_identity:
            raise ValueError("v2 prepared sample identity is crossed")
        if _effective_graph_identity(prepared) != manifest.realization_source.graph_identity_sha256:
            raise ValueError("v2 effective graph identity is crossed")
    except ConcurrentRobustnessError:
        raise
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise ConcurrentRobustnessError(
            ConcurrentRobustnessErrorCode.INVALID_SOURCE,
            "v2 frozen source, sample, graph, messages, or ranking contract is crossed",
        ) from exc
    _assert_source_unchanged(closure)
    manifest_payload = _manifest_bytes(manifest)
    manifest_sha256 = hashlib.sha256(manifest_payload).hexdigest()
    try:
        _open_workspace(
            output_path,
            manifest=manifest,
            manifest_sha256=manifest_sha256,
        )
        published_path = output_path / _V2_EXECUTION_DIR
        if published_path.exists():
            published = _validate_published_execution(
                published_path,
                manifest=manifest,
                manifest_sha256=manifest_sha256,
            )
            _assert_source_unchanged(closure)
            result = _close_v2_study_result(
                output_path=output_path,
                manifest_sha256=manifest_sha256,
                published=published,
            )
            _assert_source_unchanged(closure)
            return result
        root = _operational_root(output_path)
        if adapters_by_cell is None:
            if not root.exists():
                return _result(
                    status=ConcurrentRobustnessStudyStatus.READY_FOR_HUMAN,
                    output_path=output_path,
                    manifest_sha256=manifest_sha256,
                    logical=0,
                    physical=0,
                )
            root = _open_operational_root(
                manifest=manifest,
                manifest_sha256=manifest_sha256,
                output_path=output_path,
            )
            logical, physical, _, _, _ = _operational_progress(root)
            return _result(
                status=ConcurrentRobustnessStudyStatus.RESUMABLE,
                output_path=output_path,
                manifest_sha256=manifest_sha256,
                logical=logical,
                physical=physical,
            )
        if manifest.execution_profile != "deterministic_validation":
            raise ConcurrentRobustnessError(
                ConcurrentRobustnessErrorCode.UNSUPPORTED_ADAPTERS,
                "Formal v2 Provider lanes require their independent execution contract",
            )
        if not isinstance(adapters_by_cell, Mapping):
            raise ConcurrentRobustnessError(
                ConcurrentRobustnessErrorCode.UNSUPPORTED_ADAPTERS,
                "v2 adapters_by_cell must be a Mapping",
            )
        adapters = _preflight_adapters(manifest, adapters_by_cell)
        root = _open_operational_root(
            manifest=manifest,
            manifest_sha256=manifest_sha256,
            output_path=output_path,
        )
        cells: list[_V2CellResult] = []
        restored_provider_fees = _operational_provider_fee_cny(root)
        lanes: dict[str, _V2ModelLane] = {}
        try:
            for cell_index, (cell, adapter) in enumerate(adapters):
                lane: _V2ModelLane | None = None
                if bool(getattr(adapter, "robustness_provider_adapter", False)):
                    lane = lanes.setdefault(
                        cell.requested_model,
                        _V2ModelLane(
                            requested_model=cell.requested_model,
                            backoff_seconds=manifest.request_contract.retry_backoff_seconds,
                            provider_fee_cny_spent=restored_provider_fees.get(cell.requested_model, 0.0),
                        ),
                    )
                cell_result = _run_cell(
                    config=config,
                    prepared=prepared,
                    manifest=manifest,
                    manifest_sha256=manifest_sha256,
                    cell_index=cell_index,
                    cell=cell,
                    adapter=adapter,
                    lane=lane,
                    operational_root=root,
                )
                cells.append(cell_result)
                logical = sum(len(row.terminals) for row in cells)
                physical = sum(row.physical_attempts for row in cells)
                _write_operational_status(
                    root,
                    manifest_sha256=manifest_sha256,
                    lifecycle="running",
                    logical_judgments=logical,
                    physical_attempts=physical,
                    completed_cells=len(cells),
                    last_cell_id=cell.cell_id,
                    last_pair_id=(cell_result.terminals[-1].pair_id if cell_result.terminals else None),
                )
        except (_V2ReconciliationRequired, _V2SafePreCallStop, _V2CellStopped) as pause:
            _assert_source_unchanged(closure)
            logical, physical, completed, last_cell, last_pair = _operational_progress(root)
            if isinstance(pause, _V2ReconciliationRequired):
                status = ConcurrentRobustnessStudyStatus.RECONCILIATION_REQUIRED
            elif isinstance(pause, _V2SafePreCallStop):
                status = ConcurrentRobustnessStudyStatus.RESUMABLE
            else:
                status = ConcurrentRobustnessStudyStatus.STOPPED
            _write_operational_status(
                root,
                manifest_sha256=manifest_sha256,
                lifecycle=status.value,
                logical_judgments=logical,
                physical_attempts=physical,
                completed_cells=completed,
                last_cell_id=last_cell,
                last_pair_id=last_pair,
            )
            return _result(
                status=status,
                output_path=output_path,
                manifest_sha256=manifest_sha256,
                logical=logical,
                physical=physical,
            )
        _assert_source_unchanged(closure)
        published = _publish_execution(
            output_path,
            manifest=manifest,
            manifest_sha256=manifest_sha256,
            cells=cells,
        )
        _write_operational_status(
            root,
            manifest_sha256=manifest_sha256,
            lifecycle="cells_complete",
            logical_judgments=published.logical_judgments,
            physical_attempts=published.physical_attempts,
            completed_cells=len(cells),
            last_cell_id=cells[-1].cell_id,
            last_pair_id=cells[-1].terminals[-1].pair_id,
        )
        _assert_source_unchanged(closure)
        result = _close_v2_study_result(
            output_path=output_path,
            manifest_sha256=manifest_sha256,
            published=published,
        )
        _assert_source_unchanged(closure)
        return result
    except ConcurrentRobustnessError:
        raise
    except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ConcurrentRobustnessError(
            ConcurrentRobustnessErrorCode.WORKSPACE_CORRUPT,
            "v2 two-stage workspace, lifecycle, runtime, or execution evidence failed closed",
        ) from exc
