from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import stat
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
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
from .prompt_field_summary import CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION
from .schemas import ReportConfig

__all__ = [
    "FULL_POOL_AUTHORITATIVE_MESSAGES_SHA256",
    "FULL_POOL_CONTRACT_SCHEMA",
    "FULL_POOL_VALIDATION_DATASET_IDENTITY",
    "FULL_POOL_VALIDATION_TOKEN",
    "FullPoolExperimentContract",
    "FullPoolExperimentError",
    "FullPoolExperimentErrorCode",
    "FullPoolFormalExperiment",
    "FullPoolRunResult",
    "FullPoolRunStatus",
]

FULL_POOL_CONTRACT_SCHEMA = "full-pool-experiment-contract-v1"
FULL_POOL_SOURCE_SCHEMA = "full-pool-validation-source-v1"
FULL_POOL_MANIFEST_SCHEMA = "full-pool-validation-manifest-v1"
FULL_POOL_BATCH_SCHEMA = "full-pool-validation-batch-v1"
FULL_POOL_AGGREGATES_SCHEMA = "full-pool-validation-aggregates-v1"
FULL_POOL_DIAGNOSTICS_SCHEMA = "full-pool-validation-diagnostics-v1"
FULL_POOL_SCHEMA_DOCUMENT_VERSION = "full-pool-validation-schema-document-v1"
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
        return self


class FullPoolRunResult(_FrozenContractModel):
    status: FullPoolRunStatus
    source_root: Path
    source_identity: str
    manifest_sha256: str
    logical_adapter_decisions: int = Field(ge=0)
    provider_calls: Literal[0]
    live_api_triggered: Literal[False]
    production_deploy_eligible: Literal[False]

    @field_validator("manifest_sha256")
    @classmethod
    def _result_manifest_hash(cls, value: str) -> str:
        if not _SHA256_PATTERN.fullmatch(value):
            raise ValueError("result manifest_sha256 is invalid")
        return value


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


class FullPoolFormalExperiment:
    """Run one complete Full-Pool Validation trajectory behind a single high-level Interface."""

    def run(
        self,
        contract: FullPoolExperimentContract,
        adapter: LLMDecisionAdapter,
        output_dir: str | Path,
    ) -> FullPoolRunResult:
        frozen = _revalidate_contract(contract)
        if frozen.profile != "deterministic_validation":
            raise FullPoolExperimentError(
                FullPoolExperimentErrorCode.UNSUPPORTED_PROFILE,
                "production Full-Pool durable execution is reserved for the next lifecycle contract",
            )
        if not isinstance(adapter, LLMDecisionAdapter):
            raise FullPoolExperimentError(
                FullPoolExperimentErrorCode.INVALID_ADAPTER,
                "FullPoolFormalExperiment requires one typed Primary Decision Adapter",
            )
        try:
            output_path = _prepare_output_path(output_dir, frozen)
        except FileExistsError as exc:
            raise FullPoolExperimentError(FullPoolExperimentErrorCode.OUTPUT_CONFLICT, str(exc)) from exc
        except (OSError, ValueError) as exc:
            raise FullPoolExperimentError(
                FullPoolExperimentErrorCode.PATH_VIOLATION,
                "Full-Pool output path violates the explicit source identity",
            ) from exc

        external_baseline = _external_request_count(adapter)
        if external_baseline != 0:
            raise FullPoolExperimentError(
                FullPoolExperimentErrorCode.INVALID_ADAPTER,
                "Validation Adapter must have zero prior external request invocations",
            )
        try:
            config, prepared, expected_user_ids = _prepare_runtime_inputs(frozen)
        except (OSError, TypeError, ValueError) as exc:
            raise FullPoolExperimentError(
                FullPoolExperimentErrorCode.INVALID_DATASET,
                "dataset membership or frozen Full-Pool identity failed before the first Adapter call",
            ) from exc

        logical_decisions = 0

        def before_judgment(_: Mapping[str, object]) -> None:
            nonlocal logical_decisions
            if _external_request_count(adapter) != external_baseline:
                raise ValueError("Validation Adapter triggered an external request")
            logical_decisions += 1

        def validate_terminal(_: Mapping[str, object]) -> None:
            if _external_request_count(adapter) != external_baseline:
                raise ValueError("Validation Adapter triggered an external request")

        consumer = _PrimaryOnlyConcurrentRuntimeConsumer(
            config,
            adapter,
            expected_prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
            execution_contract=frozen.model_dump(mode="json"),
            expected_sample_identity=frozen.eligible_user_ids_sha256,
            prepared_inputs=prepared,
            before_logical_judgment=before_judgment,
            validate_terminal=validate_terminal,
        )
        try:
            spooled = consumer._run_new_to_spool(output_path)
        except Exception as exc:
            raise FullPoolExperimentError(
                FullPoolExperimentErrorCode.RUNTIME_FAILED,
                "Full-Pool Validation runtime stopped without a final source",
            ) from exc
        if logical_decisions != frozen.expected_primary_terminals or _external_request_count(adapter) != external_baseline:
            raise FullPoolExperimentError(
                FullPoolExperimentErrorCode.RUNTIME_FAILED,
                "Full-Pool Validation Adapter accounting does not close the Primary terminal denominator",
            )

        try:
            source_identity, manifest_sha256 = _close_validation_source(
                contract=frozen,
                output_path=output_path,
                spooled=spooled,
                expected_user_ids=expected_user_ids,
                expected_seed_user_ids=set(prepared.cohort.seed_user_ids),
            )
        except FileExistsError as exc:
            raise FullPoolExperimentError(FullPoolExperimentErrorCode.OUTPUT_CONFLICT, str(exc)) from exc
        except Exception as exc:
            raise FullPoolExperimentError(
                FullPoolExperimentErrorCode.SOURCE_CLOSURE_FAILED,
                "persisted Full-Pool spool failed atomic Validation source closure",
            ) from exc
        return FullPoolRunResult(
            status=FullPoolRunStatus.COMPLETE,
            source_root=output_path,
            source_identity=source_identity,
            manifest_sha256=manifest_sha256,
            logical_adapter_decisions=logical_decisions,
            provider_calls=0,
            live_api_triggered=False,
            production_deploy_eligible=False,
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


def _close_validation_source(
    *,
    contract: FullPoolExperimentContract,
    output_path: Path,
    spooled: _PrimaryOnlyConcurrentRuntimeSpoolResult,
    expected_user_ids: set[str],
    expected_seed_user_ids: set[str],
) -> tuple[str, str]:
    contract_payload = contract.model_dump(mode="json")
    contract_sha256 = _sha256_json(contract_payload)
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
                "schema_version": FULL_POOL_SCHEMA_DOCUMENT_VERSION,
                "source_schema_version": FULL_POOL_SOURCE_SCHEMA,
                "manifest_schema_version": FULL_POOL_MANIFEST_SCHEMA,
                "batch_schema_version": FULL_POOL_BATCH_SCHEMA,
                "row_schemas": {
                    "candidate": list(CONCURRENT_MESSAGE_CANDIDATE_FIELDS),
                    "pair": list(_PRIMARY_PAIR_FIELDS),
                    "terminal": list(CONCURRENT_MESSAGE_TERMINAL_FIELDS),
                },
                "terminal_variants": ["primary"],
            },
        )
        accumulator = _SourceAccumulator(contract, expected_user_ids=expected_user_ids)
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
                    terminal_handle.write(_canonical_json(row) + "\n")
                _write_json(
                    batches_dir / f"batch-{chunk.time_step:06d}.json",
                    {
                        "schema_version": FULL_POOL_BATCH_SCHEMA,
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
        manifest = {
            "schema_version": FULL_POOL_MANIFEST_SCHEMA,
            "source_schema_version": FULL_POOL_SOURCE_SCHEMA,
            "source_identity": source_identity,
            "contract_sha256": contract_sha256,
            "source_hash": source_hash,
            "profile": contract.profile,
            "provider_calls": 0,
            "live_api_triggered": False,
            "production_deploy_eligible": False,
            "counts": aggregates["counts"],
            "artifacts": artifacts,
        }
        _write_json(staging / _MANIFEST_FILE, manifest)
        manifest_sha256 = _sha256_file(staging / _MANIFEST_FILE)
        _validate_staged_source(staging, contract=contract, source_identity=source_identity)
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
) -> None:
    _require_real_directory(source_root, "Full-Pool source staging")
    manifest = _read_json_object(source_root / _MANIFEST_FILE)
    if manifest.get("schema_version") != FULL_POOL_MANIFEST_SCHEMA:
        raise ValueError("Full-Pool manifest schema is not supported")
    contract_payload = contract.model_dump(mode="json")
    contract_sha256 = _sha256_json(contract_payload)
    if (
        manifest.get("source_schema_version") != FULL_POOL_SOURCE_SCHEMA
        or manifest.get("source_identity") != source_identity
        or manifest.get("contract_sha256") != contract_sha256
        or manifest.get("provider_calls") != 0
        or manifest.get("live_api_triggered") is not False
        or manifest.get("production_deploy_eligible") is not False
    ):
        raise ValueError("Full-Pool manifest identity or Validation boundary is crossed")
    if _read_json_object(source_root / _CONTRACT_FILE) != contract_payload:
        raise ValueError("persisted Full-Pool contract does not match the frozen input")

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
    for time_step, batch_path in enumerate(batch_paths):
        batch = _read_json_object(batch_path)
        if (
            batch.get("schema_version") != FULL_POOL_BATCH_SCHEMA
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
    if aggregates.get("schema_version") != FULL_POOL_AGGREGATES_SCHEMA:
        raise ValueError("Full-Pool aggregate schema is not supported")
    counts = aggregates.get("counts")
    if not isinstance(counts, Mapping) or counts != manifest.get("counts"):
        raise ValueError("Full-Pool aggregate counts are crossed with the manifest")
    if diagnostics.get("schema_version") != FULL_POOL_DIAGNOSTICS_SCHEMA:
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
