from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, cast

from .concurrent_execution_journal import (
    _build_primary_only_concurrent_execution_run_identity,
)
from .concurrent_message_experiment import (
    CONCURRENT_MESSAGE_CANDIDATE_FIELDS,
    ConcurrentMessageExperimentConfig,
    ExperimentalMessageDefinition,
    _ConcurrentRuntimeBatchCommit,
    _ConcurrentRuntimeKernel,
    _ConcurrentRuntimeKernelState,
    _PairExecutionPlan,
    _prepare_full_pool_concurrent_runtime_inputs,
    _PreparedConcurrentRuntimeInputs,
    _PrimaryOnlyConcurrentRuntimeConsumer,
)
from .decision import EngageDecision
from .engagement_realization import (
    FULL_POOL_REALIZED_TERMINAL_SCHEMA,
    REALIZATION_RULE_VERSION,
    REALIZATION_SEED,
    REALIZED_TERMINAL_FIELDS,
    EngagementRealization,
    EngagementRealizationPolicy,
    FullPoolRealizedTerminal,
)
from .final_research import VALIDATION_RUN_STATUS
from .full_pool_source_v4 import (
    _ClosedStrictFullPoolSource,
    read_closed_strict_full_pool_source,
)
from .safe_serialization import safe_data

FULL_POOL_TWO_STAGE_SOURCE_SCHEMA = "full-pool-two-stage-realized-source-v1"
FULL_POOL_TWO_STAGE_EVIDENCE_SCHEMA = "full-pool-two-stage-realization-evidence-v1"
FULL_POOL_TWO_STAGE_PROJECTION_SCHEMA = "full-pool-two-stage-realized-projection-v1"

_ENVIRONMENTAL_FIELD = "concurrent_environmental_consciousness_coef"
_MESSAGE_CODES = {"message_1": "M1", "message_2": "M2", "message_3": "M3"}
_SEGMENT_CODES = {"class_1": "S1", "class_2": "S2", "class_3": "S3"}
_ACTIONS = ("ignore", "like", "comment", "share")
_REALIZED_TERMINAL_FILE = "realized-terminal-rows.jsonl"
_PAIR_FILE = "pair-rows.jsonl"
_CANDIDATE_FILE = "candidate-rows.jsonl"
_COMMIT_FILE = "batch-commits.jsonl"
_MEMBERSHIP_FILE = "latent-membership.csv"
_PROJECTION_JSON = "realized-projection.json"
_PROJECTION_CSV = "full-pool-realized-projection.csv"
_EVIDENCE_FILE = "realization-evidence.json"
_SCHEMA_FILE = "schema.json"

_PAIR_FIELDS = (
    "replay_pair_id",
    "replay_pair_schedule_position",
    "replay_time_step",
    "message_id",
    "message_title",
    "user_id",
    "latent_class",
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
    "upstream_terminal_row_id",
    "realized_terminal_id",
    "realization_status",
    "realized_engage",
    "realized_action",
    "campaign_feedback_committed",
)
_COMMIT_FIELDS = (
    "replay_time_step",
    "frozen_realized_positive_user_ids",
    "committed_realized_positive_user_ids",
    "messages",
)
_PROJECTION_FIELDS = (
    "Run",
    "Message",
    "Segment",
    "Total Likes",
    "Total Comments",
    "Total Shares",
    "Exposure",
)
_COUNT_FIELDS = frozenset(
    {
        "users",
        "messages",
        "pairs",
        "exposures",
        "realized_terminals",
        "batch_commits",
        "candidate_rows",
        "membership_rows",
        "projection_rows",
        "runtime_resident_row_high_water",
    }
)
_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "source_identity",
        "replay_identity",
        "classification",
        "upstream_source",
        "realization_policy",
        "accounting",
        "counts",
        "action_counts",
        "realization_status_counts",
        "row_hashes",
        "projection",
        "evidence",
        "source_hash",
        "formal_research_evidence",
        "production_deploy_eligible",
        "artifacts",
    }
)


@dataclass(frozen=True)
class FullPoolTwoStageReplayRequest:
    """Frozen caller intent for one explicit Source-v4 two-stage replay."""

    source_root: Path
    source_manifest_sha256: str
    source_identity: str
    output_dir: Path
    realization_seed: int = REALIZATION_SEED
    realization_rule_version: str = REALIZATION_RULE_VERSION

    def __post_init__(self) -> None:
        source = _explicit_directory(self.source_root, "Source-v4 root")
        output = _new_output_path(self.output_dir, source=source)
        object.__setattr__(self, "source_root", source)
        object.__setattr__(self, "output_dir", output)
        object.__setattr__(
            self,
            "source_manifest_sha256",
            _digest(self.source_manifest_sha256, "Source-v4 manifest SHA-256"),
        )
        _non_empty(self.source_identity, "Source-v4 identity")
        if self.realization_seed != REALIZATION_SEED or isinstance(self.realization_seed, bool):
            raise ValueError(f"realization seed must be the frozen value {REALIZATION_SEED}")
        if self.realization_rule_version != REALIZATION_RULE_VERSION:
            raise ValueError("realization rule version is unsupported")


@dataclass(frozen=True)
class FullPoolTwoStageReplayResult:
    output_dir: Path
    manifest_sha256: str
    source_identity: str
    user_count: int
    pair_count: int
    committed_batch_count: int
    realization_provider_calls: int
    production_deploy_eligible: bool


@dataclass(frozen=True)
class _ProviderJudgment:
    terminal_row_id: str
    pair_id: str
    time_step: int
    message_id: str
    user_id: str
    decision: EngageDecision
    prompt_version: str
    environmental_consciousness_prompt_inclusion: Literal["included"]
    source_terminal: Mapping[str, object]


@dataclass(frozen=True)
class _ReplayRuntimeResult:
    candidate_rows: tuple[dict[str, object], ...]
    pair_rows: tuple[dict[str, object], ...]
    realized_terminals: tuple[FullPoolRealizedTerminal, ...]
    commits: tuple[dict[str, object], ...]
    runtime_resident_row_high_water: int


class FullPoolTwoStageReplay:
    """High-level replay Interface: verify one source, rebuild feedback, and close artifacts."""

    def run_and_close(
        self,
        request: FullPoolTwoStageReplayRequest,
    ) -> FullPoolTwoStageReplayResult:
        closed = read_closed_strict_full_pool_source(
            request.source_root,
            manifest_sha256=request.source_manifest_sha256,
        )
        if closed.source_identity != request.source_identity:
            raise ValueError("Source-v4 identity differs from the explicit replay binding")
        source_snapshot = _source_snapshot(request.source_root)
        config, prepared, dataset_lineage = _prepare_replay_runtime(closed)
        judgments = _provider_judgment_inventory(closed)
        replay_identity = _json_sha256(
            {
                "schema_version": "full-pool-two-stage-replay-identity-v1",
                "upstream_source_identity": closed.source_identity,
                "upstream_manifest_sha256": closed.manifest_sha256,
                "realization_rule_version": request.realization_rule_version,
                "realization_seed": request.realization_seed,
                "sample_user_ids": sorted(prepared.cohort.sample_user_ids),
                "message_ids": [message.message_id for message in config.messages],
                "horizon": config.horizon,
                "delivery_capacity": config.delivery_capacity,
            }
        )

        request.output_dir.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(
                prefix=f".{request.output_dir.name}.staging-",
                dir=request.output_dir.parent,
            )
        )
        try:
            runtime = _run_replay_runtime(
                config=config,
                prepared=prepared,
                closed=closed,
                judgments=judgments,
                replay_identity=replay_identity,
                policy=EngagementRealizationPolicy(
                    source_identity=closed.source_identity,
                    realization_seed=request.realization_seed,
                    realization_rule_version=request.realization_rule_version,
                ),
                workspace=staging / ".runtime-workspace",
                output_target=request.output_dir,
            )
            _write_closed_source(
                staging=staging,
                request=request,
                closed=closed,
                config=config,
                runtime=runtime,
                replay_identity=replay_identity,
                dataset_lineage=dataset_lineage,
            )
            shutil.rmtree(staging / ".runtime-workspace")
            manifest_sha256 = _sha256_file(staging / "manifest.json")
            _validate_closed_source(staging, manifest_sha256=manifest_sha256)
            if _source_snapshot(request.source_root) != source_snapshot:
                raise ValueError("immutable Source-v4 bytes changed during realization replay")
            os.replace(staging, request.output_dir)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

        manifest_sha256 = _sha256_file(request.output_dir / "manifest.json")
        manifest = _validate_closed_source(
            request.output_dir,
            manifest_sha256=manifest_sha256,
        )
        if _source_snapshot(request.source_root) != source_snapshot:
            raise ValueError("immutable Source-v4 bytes changed after realization replay closure")
        counts = _mapping(manifest.get("counts"), "realized source counts")
        return FullPoolTwoStageReplayResult(
            output_dir=request.output_dir,
            manifest_sha256=manifest_sha256,
            source_identity=_non_empty(manifest.get("source_identity"), "realized source identity"),
            user_count=_non_negative_int(counts.get("users"), "realized users"),
            pair_count=_non_negative_int(counts.get("pairs"), "realized pairs"),
            committed_batch_count=_non_negative_int(
                counts.get("batch_commits"), "realized batch commits"
            ),
            realization_provider_calls=0,
            production_deploy_eligible=False,
        )


def _prepare_replay_runtime(
    source: _ClosedStrictFullPoolSource,
) -> tuple[ConcurrentMessageExperimentConfig, _PreparedConcurrentRuntimeInputs, dict[str, object]]:
    identity = _json_object(source.root / "runtime" / "fresh-run-identity.json", "Source-v4 run identity")
    request = _json_object(source.root / "fresh-request.json", "Source-v4 frozen request")
    fingerprints = _mapping(identity.get("sample_data_fingerprints"), "Source-v4 dataset fingerprints")
    dataset = Path(_non_empty(fingerprints.get("dataset_dir"), "Source-v4 dataset path"))
    if request.get("dataset_dir") != str(dataset):
        raise ValueError("Source-v4 dataset path is crossed between frozen artifacts")
    dataset = _explicit_directory(dataset, "Source-v4 dataset")
    file_hashes = _mapping(fingerprints.get("dataset_files"), "Source-v4 dataset file hashes")
    verified_files: list[dict[str, object]] = []
    for relative_text, expected_hash in sorted(file_hashes.items()):
        relative = PurePosixPath(relative_text)
        path = dataset / Path(*relative.parts)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or path.is_symlink()
            or not path.is_file()
            or _sha256_file(path) != _digest(expected_hash, f"dataset {relative_text} SHA-256")
        ):
            raise ValueError(f"Source-v4 dataset hash drifted for {relative_text}")
        verified_files.append(_file_ref(dataset, path))

    configuration = _mapping(identity.get("configuration"), "Source-v4 runtime configuration")
    messages_raw = _sequence(identity.get("messages"), "Source-v4 messages")
    messages = tuple(ExperimentalMessageDefinition.model_validate(value) for value in messages_raw)
    profile = _non_empty(configuration.get("configuration_profile"), "Source-v4 profile")
    if profile not in {"production", "validation"}:
        raise ValueError("Source-v4 configuration profile is unsupported")
    config = ConcurrentMessageExperimentConfig(
        dataset_dir=dataset,
        sample_size=_positive_int(configuration.get("sample_size"), "Source-v4 sample size"),
        horizon=_positive_int(configuration.get("horizon"), "Source-v4 horizon"),
        delivery_capacity=_positive_int(
            configuration.get("delivery_capacity"), "Source-v4 delivery capacity"
        ),
        random_seed=_non_negative_int(configuration.get("random_seed"), "Source-v4 random seed"),
        configuration_profile=cast(Literal["production", "validation"], profile),
        sample_holdout_video_id=_non_empty(
            configuration.get("sample_holdout_video_id"), "Source-v4 holdout"
        ),
        messages=messages,
    )
    seed_top_k = _positive_int(request.get("seed_top_k_per_proxy"), "Source-v4 seed Top K")
    prepared = _prepare_full_pool_concurrent_runtime_inputs(
        config,
        seed_top_k_per_proxy=seed_top_k,
    )
    if set(prepared.cohort.sample_user_ids) != set(source.membership):
        raise ValueError("reconstructed replay membership differs from Source-v4 membership")
    return config, prepared, {
        "dataset_dir": str(dataset),
        "files": verified_files,
        "files_identity": _json_sha256(verified_files),
        "seed_top_k_per_proxy": seed_top_k,
    }


def _provider_judgment_inventory(
    source: _ClosedStrictFullPoolSource,
) -> dict[tuple[str, str, str, str], _ProviderJudgment]:
    inventory: dict[tuple[str, str, str, str], _ProviderJudgment] = {}
    schedule_positions: set[int] = set()
    for time_step in range(source.facts.committed_batches):
        batch = source.read_batch(time_step)
        rows = _mapping(batch.get("rows"), "Source-v4 batch rows")
        for raw in _sequence(rows.get("terminal_rows"), "Source-v4 terminal rows"):
            terminal = _mapping(raw, "Source-v4 terminal row")
            terminal_time_step = _non_negative_int(
                terminal.get("time_step"), "upstream terminal time step"
            )
            user_id = _non_empty(terminal.get("user_id"), "upstream terminal user")
            message_id = _non_empty(terminal.get("message_id"), "upstream terminal message")
            pair_id = _non_empty(terminal.get("pair_id"), "upstream pair id")
            terminal_id = _non_empty(
                terminal.get("terminal_row_id"), "upstream terminal row id"
            )
            position = _non_negative_int(
                terminal.get("pair_schedule_position"), "upstream pair schedule position"
            )
            key = (source.source_identity, user_id, message_id, "primary")
            if (
                terminal_time_step != time_step
                or terminal.get("decision_variant") != "primary"
                or terminal.get("terminal_status") != "succeeded"
                or terminal.get("provider_status") != "succeeded"
                or pair_id != f"{user_id}:{message_id}:{terminal_time_step}"
                or terminal_id != f"{pair_id}:primary"
                or key in inventory
                or position in schedule_positions
                or user_id not in source.membership
                or message_id not in _MESSAGE_CODES
            ):
                raise ValueError("Source-v4 Provider Judgment mapping is duplicate, failed, or crossed")
            inclusion = _json_text_object(
                terminal.get("prompt_field_inclusion"), "upstream Prompt field inclusion"
            )
            profile = _json_text_object(
                terminal.get("context_profile_payload"), "upstream profile context"
            )
            if (
                inclusion.get(_ENVIRONMENTAL_FIELD) != "included"
                or profile.get("user_id") != user_id
                or not isinstance(profile.get(_ENVIRONMENTAL_FIELD), (int, float))
                or isinstance(profile.get(_ENVIRONMENTAL_FIELD), bool)
            ):
                raise ValueError("Source-v4 Prompt inclusion or user context is crossed")
            decision = EngageDecision.model_validate(
                {
                    "engage": _canonical_bool(terminal.get("engage"), "Provider engage"),
                    "probability": terminal.get("probability"),
                    "reason": terminal.get("reason"),
                    "confidence": terminal.get("confidence"),
                    "action": terminal.get("action"),
                    "decision_source": terminal.get("decision_source"),
                }
            )
            inventory[key] = _ProviderJudgment(
                terminal_row_id=terminal_id,
                pair_id=pair_id,
                time_step=terminal_time_step,
                message_id=message_id,
                user_id=user_id,
                decision=decision,
                prompt_version=_non_empty(
                    terminal.get("prompt_version"), "upstream prompt version"
                ),
                environmental_consciousness_prompt_inclusion="included",
                source_terminal=terminal,
            )
            schedule_positions.add(position)

    expected = {
        (source.source_identity, user_id, message_id, "primary")
        for user_id in source.membership
        for message_id in _MESSAGE_CODES
    }
    if set(inventory) != expected or len(schedule_positions) != len(expected):
        raise ValueError("Source-v4 Provider Judgment inventory is missing or crossed")
    return inventory


def _run_replay_runtime(
    *,
    config: ConcurrentMessageExperimentConfig,
    prepared: _PreparedConcurrentRuntimeInputs,
    closed: _ClosedStrictFullPoolSource,
    judgments: Mapping[tuple[str, str, str, str], _ProviderJudgment],
    replay_identity: str,
    policy: EngagementRealizationPolicy,
    workspace: Path,
    output_target: Path,
) -> _ReplayRuntimeResult:
    configuration = config.snapshot(
        sampling_status=VALIDATION_RUN_STATUS,
        production_deploy_eligible=False,
    )
    configuration.update(
        {
            "runtime_consumer": "full_pool_two_stage_realization",
            "realization_rule_version": policy.realization_rule_version,
            "realization_seed": policy.realization_seed,
        }
    )
    identity = _build_primary_only_concurrent_execution_run_identity(
        output_target=output_target,
        operational_workspace=workspace,
        configuration_snapshot=configuration,
        message_snapshot=[message.model_dump(mode="json") for message in config.messages],
        sample_audit=prepared.cohort.sample_audit,
        dataset_dir=config.dataset_dir,
        primary_provider_metadata={
            "adapter": "persisted_source_v4_judgment_consumer",
            "source_identity": closed.source_identity,
            "provider_calls": 0,
        },
        prompt_contract={"primary": {"source": "persisted_source_v4"}},
        execution_contract={
            "schema_version": "full-pool-two-stage-replay-execution-v1",
            "replay_identity": replay_identity,
            "upstream_manifest_sha256": closed.manifest_sha256,
            "realization_rule_version": policy.realization_rule_version,
            "realization_seed": policy.realization_seed,
        },
    )
    from .concurrent_execution_journal import ConcurrentExecutionJournal

    journal = ConcurrentExecutionJournal.open_new(workspace, identity=identity)
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
    terminals: list[FullPoolRealizedTerminal] = []
    commits: list[dict[str, object]] = []
    try:
        while state.next_time_step < config.horizon:
            kernel.plan_batch()
            plans = kernel.pending_plans()
            for plan in plans:
                judgment_key = (
                    closed.source_identity,
                    plan.user.user_id,
                    plan.message.message_id,
                    "primary",
                )
                judgment = judgments.get(judgment_key)
                if judgment is None:
                    raise ValueError("replay selected a pair without one unique Provider Judgment")
                realization = policy.realize(
                    judgment.decision,
                    user_id=plan.user.user_id,
                    message_id=plan.message.message_id,
                )
                realized_terminal = _realized_terminal(
                    replay_identity=replay_identity,
                    source_identity=closed.source_identity,
                    plan=plan,
                    judgment=judgment,
                    realization=realization,
                    policy=policy,
                )
                kernel.start_pair(plan)
                runtime_terminal = _runtime_terminal(
                    plan=plan,
                    judgment=judgment,
                    realization=realization,
                )
                kernel.register_terminal(
                    plan=plan,
                    decision_variant="primary",
                    terminal_row=runtime_terminal,
                    variant_evidence=_runtime_evidence(plan, runtime_terminal),
                )
                kernel.close_primary_pair(
                    plan,
                    _PrimaryOnlyConcurrentRuntimeConsumer._primary_result_row(
                        plan,
                        runtime_terminal,
                    ),
                )
                terminals.append(realized_terminal)
            commit = kernel.commit_primary_batch()
            commits.append(_realized_commit(commit))

        replay = journal._replay_runtime()
        materialized = kernel.materialize_spool(replay)
    finally:
        journal.close()

    terminal_by_pair = {terminal.replay_pair_id: terminal for terminal in terminals}
    pair_rows: list[dict[str, object]] = []
    for raw in materialized.result_rows:
        result_row = dict(raw)
        pair_id = _non_empty(result_row.get("pair_id"), "replay pair id")
        terminal = terminal_by_pair.get(pair_id)
        if terminal is None:
            raise ValueError("replay result row is missing its realized terminal")
        pair_rows.append(_realized_pair_row(result_row, terminal, closed.membership))
    if len(pair_rows) != len(terminals) or kernel.runtime_resident_row_count != 0:
        raise ValueError("replay runtime did not close and release every realized pair")
    return _ReplayRuntimeResult(
        candidate_rows=tuple(dict(row) for row in materialized.candidate_rows),
        pair_rows=tuple(pair_rows),
        realized_terminals=tuple(terminals),
        commits=tuple(commits),
        runtime_resident_row_high_water=state.runtime_resident_row_high_water,
    )


def _realized_terminal(
    *,
    replay_identity: str,
    source_identity: str,
    plan: _PairExecutionPlan,
    judgment: _ProviderJudgment,
    realization: EngagementRealization,
    policy: EngagementRealizationPolicy,
) -> FullPoolRealizedTerminal:
    realized_terminal_id = _realized_terminal_identity(
        replay_identity=replay_identity,
        upstream_terminal_row_id=judgment.terminal_row_id,
        replay_pair_id=plan.pair_id,
    )
    return FullPoolRealizedTerminal(
        realized_terminal_id=realized_terminal_id,
        upstream_source_identity=source_identity,
        upstream_terminal_row_id=judgment.terminal_row_id,
        upstream_pair_id=judgment.pair_id,
        realization_key=realization.realization_key,
        replay_pair_id=plan.pair_id,
        replay_pair_schedule_position=plan.pair_schedule_position,
        replay_time_step=plan.time_step,
        message_id=plan.message.message_id,
        user_id=plan.user.user_id,
        provider_engage=judgment.decision.engage,
        provider_probability=judgment.decision.probability,
        provider_action=judgment.decision.action,
        provider_reason=judgment.decision.reason,
        provider_confidence=judgment.decision.confidence,
        provider_decision_source=judgment.decision.decision_source,
        prompt_version=judgment.prompt_version,
        environmental_consciousness_prompt_inclusion=(
            judgment.environmental_consciousness_prompt_inclusion
        ),
        realization_rule_version=REALIZATION_RULE_VERSION,
        realization_seed=REALIZATION_SEED,
        realization_status=realization.realization_status,
        uniform_draw=realization.uniform_draw,
        realized_engage=realization.realized_engage,
        realized_action=realization.realized_action,
    )


def _realized_terminal_identity(
    *,
    replay_identity: str,
    upstream_terminal_row_id: str,
    replay_pair_id: str,
) -> str:
    return hashlib.sha256(
        (
            "full-pool-realized-terminal-v1\0"
            + replay_identity
            + "\0"
            + upstream_terminal_row_id
            + "\0"
            + replay_pair_id
        ).encode()
    ).hexdigest()


def _runtime_terminal(
    *,
    plan: _PairExecutionPlan,
    judgment: _ProviderJudgment,
    realization: EngagementRealization,
) -> dict[str, object]:
    upstream = judgment.source_terminal
    return {
        "terminal_row_id": f"{plan.pair_id}:primary",
        "pair_id": plan.pair_id,
        "pair_schedule_position": plan.pair_schedule_position,
        "time_step": plan.time_step,
        "message_id": plan.message.message_id,
        "user_id": plan.user.user_id,
        "decision_variant": "primary",
        "prompt_version": judgment.prompt_version,
        "context_source_key": f"{plan.pair_id}:primary:realized",
        "cache_key": realization.realization_key,
        "context_profile_payload": upstream.get("context_profile_payload", "{}"),
        "peer_context_payload": upstream.get("peer_context_payload", "{}"),
        "prompt_field_inclusion": upstream.get("prompt_field_inclusion", "{}"),
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
        "engage": "true" if realization.realized_engage else "false",
        "probability": judgment.decision.probability,
        "confidence": judgment.decision.confidence,
        "action": realization.realized_action,
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


def _realized_pair_row(
    result: Mapping[str, object],
    terminal: FullPoolRealizedTerminal,
    membership: Mapping[str, str],
) -> dict[str, object]:
    user_id = terminal.user_id
    payload = {
        "replay_pair_id": terminal.replay_pair_id,
        "replay_pair_schedule_position": terminal.replay_pair_schedule_position,
        "replay_time_step": terminal.replay_time_step,
        "message_id": terminal.message_id,
        "message_title": result.get("message_title"),
        "user_id": user_id,
        "latent_class": membership[user_id],
        "is_seed": _canonical_bool(result.get("is_seed"), "replay pair seed flag"),
        "selection_reason": result.get("selection_reason"),
        "ranking_position": result.get("ranking_position"),
        "base_network_relevance": result.get("base_network_relevance"),
        "base_network_relevance_full_precision": result.get(
            "base_network_relevance_full_precision"
        ),
        "campaign_engaged_neighbor_count": result.get(
            "campaign_engaged_neighbor_count"
        ),
        "campaign_engaged_neighbor_signal": result.get(
            "campaign_engaged_neighbor_signal"
        ),
        "campaign_engaged_neighbor_signal_full_precision": result.get(
            "campaign_engaged_neighbor_signal_full_precision"
        ),
        "historical_tag_affinity": result.get("historical_tag_affinity"),
        "raw_message_user_fit": result.get("raw_message_user_fit"),
        "raw_message_user_fit_full_precision": result.get(
            "raw_message_user_fit_full_precision"
        ),
        "normalized_message_user_fit": result.get("normalized_message_user_fit"),
        "normalized_message_user_fit_full_precision": result.get(
            "normalized_message_user_fit_full_precision"
        ),
        "personalized_delivery_score": result.get("personalized_delivery_score"),
        "personalized_delivery_score_full_precision": result.get(
            "personalized_delivery_score_full_precision"
        ),
        "upstream_terminal_row_id": terminal.upstream_terminal_row_id,
        "realized_terminal_id": terminal.realized_terminal_id,
        "realization_status": terminal.realization_status,
        "realized_engage": terminal.realized_engage,
        "realized_action": terminal.realized_action,
        "campaign_feedback_committed": _canonical_bool(
            result.get("campaign_feedback_committed"),
            "replay feedback flag",
        ),
    }
    if tuple(payload) != _PAIR_FIELDS:
        raise AssertionError("realized pair row fields drifted")
    return payload


def _realized_commit(commit: _ConcurrentRuntimeBatchCommit) -> dict[str, object]:
    time_step = commit.time_step
    frozen = list(commit.frozen_campaign_engaged_user_ids)
    committed = list(commit.committed_primary_positive_user_ids)
    messages: list[dict[str, object]] = []
    for raw in commit.message_summaries:
        summary = dict(safe_data(raw))
        summary["realized_positive_user_ids"] = summary.pop("primary_positive_user_ids")
        summary.pop("primary_provider_failed_user_ids", None)
        summary.pop("shadow_provider_failed_user_ids", None)
        messages.append(summary)
    payload = {
        "replay_time_step": time_step,
        "frozen_realized_positive_user_ids": frozen,
        "committed_realized_positive_user_ids": committed,
        "messages": messages,
    }
    if tuple(payload) != _COMMIT_FIELDS:
        raise AssertionError("realized batch commit fields drifted")
    return payload


def _write_closed_source(
    *,
    staging: Path,
    request: FullPoolTwoStageReplayRequest,
    closed: _ClosedStrictFullPoolSource,
    config: ConcurrentMessageExperimentConfig,
    runtime: _ReplayRuntimeResult,
    replay_identity: str,
    dataset_lineage: Mapping[str, object],
) -> None:
    _write_jsonl(staging / _CANDIDATE_FILE, runtime.candidate_rows)
    _write_jsonl(staging / _PAIR_FILE, runtime.pair_rows)
    with (staging / _REALIZED_TERMINAL_FILE).open("x", encoding="utf-8", newline="\n") as handle:
        for terminal in runtime.realized_terminals:
            handle.write(terminal.canonical_json_line())
    _write_jsonl(staging / _COMMIT_FILE, runtime.commits)
    membership_bytes = (closed.root / _MEMBERSHIP_FILE).read_bytes()
    (staging / _MEMBERSHIP_FILE).write_bytes(membership_bytes)

    projection_rows = _projection_rows(
        terminals=runtime.realized_terminals,
        membership=closed.membership,
        committed_batches=config.horizon,
    )
    projection_csv = _projection_csv_bytes(projection_rows)
    (staging / _PROJECTION_CSV).write_bytes(projection_csv)
    action_counts = _action_counts(runtime.realized_terminals)
    projection_body = {
        "schema_version": FULL_POOL_TWO_STAGE_PROJECTION_SCHEMA,
        "replay_identity": replay_identity,
        "upstream_source_identity": closed.source_identity,
        "rows": projection_rows,
        "rows_sha256": _json_sha256(projection_rows),
        "csv_file": _PROJECTION_CSV,
        "csv_sha256": hashlib.sha256(projection_csv).hexdigest(),
        "action_counts": action_counts,
        "total_exposure": len(runtime.realized_terminals),
    }
    projection = {
        **projection_body,
        "projection_identity": _json_sha256(projection_body),
    }
    _write_json(staging / _PROJECTION_JSON, projection)

    schema = {
        "schema_version": "full-pool-two-stage-realized-source-schema-v1",
        "source_schema_version": FULL_POOL_TWO_STAGE_SOURCE_SCHEMA,
        "evidence_schema_version": FULL_POOL_TWO_STAGE_EVIDENCE_SCHEMA,
        "projection_schema_version": FULL_POOL_TWO_STAGE_PROJECTION_SCHEMA,
        "realized_terminal_schema_version": FULL_POOL_REALIZED_TERMINAL_SCHEMA,
        "realized_terminal_fields": list(REALIZED_TERMINAL_FIELDS),
        "pair_fields": list(_PAIR_FIELDS),
        "candidate_fields": list(CONCURRENT_MESSAGE_CANDIDATE_FIELDS),
        "batch_commit_fields": list(_COMMIT_FIELDS),
        "projection_fields": list(_PROJECTION_FIELDS),
        "canonical_jsonl": "utf-8-sorted-keys-compact-finite-json-lines-v1",
        "extra_fields": "fail_closed",
    }
    _write_json(staging / _SCHEMA_FILE, schema)

    row_hashes = {
        relative: _sha256_file(staging / relative)
        for relative in (_CANDIDATE_FILE, _PAIR_FILE, _REALIZED_TERMINAL_FILE, _COMMIT_FILE)
    }
    status_counts = _status_counts(runtime.realized_terminals)
    counts = {
        "users": len(closed.membership),
        "messages": len(config.messages),
        "pairs": len(runtime.pair_rows),
        "exposures": len(runtime.realized_terminals),
        "realized_terminals": len(runtime.realized_terminals),
        "batch_commits": len(runtime.commits),
        "candidate_rows": len(runtime.candidate_rows),
        "membership_rows": len(closed.membership),
        "projection_rows": len(projection_rows),
        "runtime_resident_row_high_water": runtime.runtime_resident_row_high_water,
    }
    upstream_evidence_profile = _non_empty(
        closed.aggregates.get("evidence_profile"), "upstream evidence profile"
    )
    if upstream_evidence_profile not in {"validation", "formal_live"}:
        raise ValueError("upstream evidence profile is unsupported")
    upstream_live_api_triggered = upstream_evidence_profile == "formal_live"
    upstream_formal_research_evidence = upstream_evidence_profile == "formal_live"
    upstream_accounting = {
        "logical_judgments": closed.facts.logical_pairs,
        "provider_responses": closed.facts.provider_responses,
        "successful_decisions": closed.facts.successful_decisions,
        "external_request_invocations": closed.facts.external_request_invocations,
        "observed_model_counts": dict(closed.facts.observed_model_counts),
        "usage_complete_response_count": closed.facts.usage_complete_response_count,
        "usage_missing_response_count": closed.facts.usage_missing_response_count,
        "usage_malformed_response_count": closed.facts.usage_malformed_response_count,
        "settled_actual_attempts": closed.facts.settled_actual_attempts,
        "charged_physical_attempts": closed.facts.charged_physical_attempts,
        "evidence_profile": upstream_evidence_profile,
        "formal_research_evidence": upstream_formal_research_evidence,
        "production_deploy_eligible": closed.facts.production_deploy_eligible,
        "live_api_triggered": upstream_live_api_triggered,
    }
    accounting = {
        "upstream": upstream_accounting,
        "realization": {"live_api_triggered": False, "provider_calls": 0},
        "composite_zero_provider_formal": False,
    }
    core_artifact_hashes = {
        relative: _sha256_file(staging / relative)
        for relative in (
            _CANDIDATE_FILE,
            _PAIR_FILE,
            _REALIZED_TERMINAL_FILE,
            _COMMIT_FILE,
            _MEMBERSHIP_FILE,
            _PROJECTION_JSON,
            _PROJECTION_CSV,
            _SCHEMA_FILE,
        )
    }
    evidence_body = {
        "schema_version": FULL_POOL_TWO_STAGE_EVIDENCE_SCHEMA,
        "classification": "nonproduction_two_stage_validation",
        "replay_identity": replay_identity,
        "upstream_lineage": {
            "source_root": str(closed.root),
            "source_schema_version": closed.manifest.get("schema_version"),
            "source_identity": closed.source_identity,
            "manifest_sha256": closed.manifest_sha256,
            "profile": closed.facts.profile,
            "artifact_hashes": dict(sorted(closed.facts.artifact_hashes.items())),
            "dataset": dict(dataset_lineage),
        },
        "realization_policy": {
            "rule_version": request.realization_rule_version,
            "seed": request.realization_seed,
            "decision_rule": "provider_ignore_without_draw_else_uniform_draw_lt_provider_probability",
            "reason_policy": "provider_reason_is_judgment_provenance_no_realized_reason",
        },
        "accounting": accounting,
        "counts": counts,
        "action_counts": action_counts,
        "realization_status_counts": status_counts,
        "artifact_hashes": core_artifact_hashes,
        "formal_research_evidence": upstream_formal_research_evidence,
        "production_deploy_eligible": False,
    }
    evidence = {**evidence_body, "evidence_identity": _json_sha256(evidence_body)}
    _write_json(staging / _EVIDENCE_FILE, evidence)

    artifact_names = (
        _CANDIDATE_FILE,
        _PAIR_FILE,
        _REALIZED_TERMINAL_FILE,
        _COMMIT_FILE,
        _MEMBERSHIP_FILE,
        _PROJECTION_JSON,
        _PROJECTION_CSV,
        _EVIDENCE_FILE,
        _SCHEMA_FILE,
    )
    artifacts = [_file_ref(staging, staging / relative) for relative in artifact_names]
    source_hash = _json_sha256(artifacts)
    source_identity = _json_sha256(
        {
            "schema_version": FULL_POOL_TWO_STAGE_SOURCE_SCHEMA,
            "replay_identity": replay_identity,
            "upstream_source_identity": closed.source_identity,
            "source_hash": source_hash,
        }
    )
    manifest = {
        "schema_version": FULL_POOL_TWO_STAGE_SOURCE_SCHEMA,
        "source_identity": source_identity,
        "replay_identity": replay_identity,
        "classification": "nonproduction_two_stage_validation",
        "upstream_source": {
            "source_root": str(closed.root),
            "schema_version": closed.manifest.get("schema_version"),
            "source_identity": closed.source_identity,
            "manifest_sha256": closed.manifest_sha256,
            "source_hash": closed.facts.source_hash,
            "production_deploy_eligible": closed.facts.production_deploy_eligible,
        },
        "realization_policy": evidence_body["realization_policy"],
        "accounting": accounting,
        "counts": counts,
        "action_counts": action_counts,
        "realization_status_counts": status_counts,
        "row_hashes": row_hashes,
        "projection": {
            "schema_version": FULL_POOL_TWO_STAGE_PROJECTION_SCHEMA,
            "identity": projection["projection_identity"],
            "json_sha256": _sha256_file(staging / _PROJECTION_JSON),
            "csv_sha256": _sha256_file(staging / _PROJECTION_CSV),
        },
        "evidence": {
            "schema_version": FULL_POOL_TWO_STAGE_EVIDENCE_SCHEMA,
            "identity": evidence["evidence_identity"],
            "sha256": _sha256_file(staging / _EVIDENCE_FILE),
        },
        "source_hash": source_hash,
        "formal_research_evidence": upstream_formal_research_evidence,
        "production_deploy_eligible": False,
        "artifacts": artifacts,
    }
    _write_json(staging / "manifest.json", manifest)


def _validate_closed_source(source: Path, *, manifest_sha256: str) -> dict[str, object]:
    root = _explicit_directory(source, "realized source")
    manifest_path = root / "manifest.json"
    if _sha256_file(manifest_path) != _digest(manifest_sha256, "realized manifest SHA-256"):
        raise ValueError("realized source manifest differs from its explicit hash")
    manifest = _json_object(manifest_path, "realized source manifest")
    if set(manifest) != _MANIFEST_FIELDS or manifest.get("schema_version") != FULL_POOL_TWO_STAGE_SOURCE_SCHEMA:
        raise ValueError("realized source manifest schema or fields are not exact")
    if (
        manifest.get("classification") != "nonproduction_two_stage_validation"
        or not isinstance(manifest.get("formal_research_evidence"), bool)
        or manifest.get("production_deploy_eligible") is not False
    ):
        raise ValueError("realized validation source cannot be production eligible")
    artifacts = _artifact_inventory(root, manifest)
    if set(artifacts) != {
        _CANDIDATE_FILE,
        _PAIR_FILE,
        _REALIZED_TERMINAL_FILE,
        _COMMIT_FILE,
        _MEMBERSHIP_FILE,
        _PROJECTION_JSON,
        _PROJECTION_CSV,
        _EVIDENCE_FILE,
        _SCHEMA_FILE,
    }:
        raise ValueError("realized source artifact inventory is incomplete")
    if manifest.get("source_hash") != _json_sha256(list(artifacts.values())):
        raise ValueError("realized source artifact identity is crossed")
    expected_row_hashes = {
        relative: artifacts[relative]["sha256"]
        for relative in (_CANDIDATE_FILE, _PAIR_FILE, _REALIZED_TERMINAL_FILE, _COMMIT_FILE)
    }
    if manifest.get("row_hashes") != expected_row_hashes:
        raise ValueError("realized source row hashes are crossed")
    upstream = _mapping(manifest.get("upstream_source"), "realized upstream source")
    expected_identity = _json_sha256(
        {
            "schema_version": FULL_POOL_TWO_STAGE_SOURCE_SCHEMA,
            "replay_identity": manifest.get("replay_identity"),
            "upstream_source_identity": upstream.get("source_identity"),
            "source_hash": manifest.get("source_hash"),
        }
    )
    if manifest.get("source_identity") != expected_identity:
        raise ValueError("realized source identity is crossed")
    realization_policy = _mapping(
        manifest.get("realization_policy"), "realized source policy"
    )
    if realization_policy != {
        "rule_version": REALIZATION_RULE_VERSION,
        "seed": REALIZATION_SEED,
        "decision_rule": (
            "provider_ignore_without_draw_else_uniform_draw_lt_provider_probability"
        ),
        "reason_policy": "provider_reason_is_judgment_provenance_no_realized_reason",
    }:
        raise ValueError("realized source policy is crossed")
    accounting = _mapping(manifest.get("accounting"), "realized source accounting")
    realization_accounting = _mapping(
        accounting.get("realization"), "realized source realization accounting"
    )
    upstream_accounting = _mapping(
        accounting.get("upstream"), "realized source upstream accounting"
    )
    upstream_evidence_profile = _non_empty(
        upstream_accounting.get("evidence_profile"), "upstream evidence profile"
    )
    if upstream_evidence_profile not in {"validation", "formal_live"}:
        raise ValueError("upstream evidence profile is unsupported")
    expected_upstream_formal = upstream_evidence_profile == "formal_live"
    if (
        realization_accounting != {"live_api_triggered": False, "provider_calls": 0}
        or upstream_accounting.get("live_api_triggered") is not expected_upstream_formal
        or upstream_accounting.get("formal_research_evidence")
        is not expected_upstream_formal
        or upstream_accounting.get("production_deploy_eligible")
        is not expected_upstream_formal
        or manifest.get("formal_research_evidence")
        is not upstream_accounting.get("formal_research_evidence")
        or accounting.get("composite_zero_provider_formal") is not False
    ):
        raise ValueError("realized source accounting is crossed")

    schema = _json_object(root / _SCHEMA_FILE, "realized source schema")
    if (
        schema.get("source_schema_version") != FULL_POOL_TWO_STAGE_SOURCE_SCHEMA
        or schema.get("realized_terminal_schema_version")
        != FULL_POOL_REALIZED_TERMINAL_SCHEMA
        or schema.get("realized_terminal_fields") != list(REALIZED_TERMINAL_FIELDS)
        or schema.get("pair_fields") != list(_PAIR_FIELDS)
        or schema.get("candidate_fields") != list(CONCURRENT_MESSAGE_CANDIDATE_FIELDS)
        or schema.get("batch_commit_fields") != list(_COMMIT_FIELDS)
        or schema.get("projection_fields") != list(_PROJECTION_FIELDS)
        or schema.get("extra_fields") != "fail_closed"
    ):
        raise ValueError("realized source schema document is crossed")

    terminals = [
        FullPoolRealizedTerminal.model_validate(row)
        for row in _canonical_jsonl(root / _REALIZED_TERMINAL_FILE)
    ]
    pairs = _canonical_jsonl(root / _PAIR_FILE)
    candidates = _canonical_jsonl(root / _CANDIDATE_FILE)
    commits = _canonical_jsonl(root / _COMMIT_FILE)
    if any(set(row) != set(_PAIR_FIELDS) for row in pairs):
        raise ValueError("realized pair row fields are not exact")
    if any(set(row) != set(CONCURRENT_MESSAGE_CANDIDATE_FIELDS) for row in candidates):
        raise ValueError("realized candidate row fields are not exact")
    if any(set(row) != set(_COMMIT_FIELDS) for row in commits):
        raise ValueError("realized batch commit fields are not exact")
    membership = _read_membership(root / _MEMBERSHIP_FILE)
    counts = _mapping(manifest.get("counts"), "realized counts")
    if (
        set(counts) != _COUNT_FIELDS
        or len(membership) != counts.get("users")
        or len(pairs) != counts.get("pairs")
        or len(terminals) != counts.get("realized_terminals")
        or len(terminals) != counts.get("exposures")
        or len(commits) != counts.get("batch_commits")
        or len(candidates) != counts.get("candidate_rows")
        or len(membership) != counts.get("membership_rows")
        or len({terminal.replay_pair_id for terminal in terminals}) != len(terminals)
        or len({terminal.realization_key for terminal in terminals}) != len(terminals)
        or len({terminal.realized_terminal_id for terminal in terminals}) != len(terminals)
        or len({terminal.upstream_terminal_row_id for terminal in terminals}) != len(terminals)
        or sorted(terminal.replay_pair_schedule_position for terminal in terminals)
        != list(range(len(terminals)))
    ):
        raise ValueError("realized source denominators or terminal identities are crossed")
    replay_identity = _digest(manifest.get("replay_identity"), "realized replay identity")
    upstream_identity = _non_empty(upstream.get("source_identity"), "upstream source identity")
    for terminal in terminals:
        if (
            terminal.upstream_source_identity != upstream_identity
            or terminal.upstream_terminal_row_id != f"{terminal.upstream_pair_id}:primary"
            or not terminal.upstream_pair_id.startswith(
                f"{terminal.user_id}:{terminal.message_id}:"
            )
            or terminal.realized_terminal_id
            != _realized_terminal_identity(
                replay_identity=replay_identity,
                upstream_terminal_row_id=terminal.upstream_terminal_row_id,
                replay_pair_id=terminal.replay_pair_id,
            )
        ):
            raise ValueError("realized terminal lineage or identity is crossed")
    expected_pairs = {
        (user_id, message_id) for user_id in membership for message_id in _MESSAGE_CODES
    }
    if {(terminal.user_id, terminal.message_id) for terminal in terminals} != expected_pairs:
        raise ValueError("realized source does not close the user-message denominator")
    if _action_counts(terminals) != manifest.get("action_counts"):
        raise ValueError("realized source action counts are crossed")
    if _status_counts(terminals) != manifest.get("realization_status_counts"):
        raise ValueError("realized source status counts are crossed")

    terminal_by_pair = {terminal.replay_pair_id: terminal for terminal in terminals}
    candidate_by_key: dict[tuple[int, str, str], Mapping[str, object]] = {}
    for candidate in candidates:
        candidate_key = (
            _non_negative_int(candidate.get("time_step"), "candidate time step"),
            _non_empty(candidate.get("message_id"), "candidate message"),
            _non_empty(candidate.get("user_id"), "candidate user"),
        )
        if (
            candidate_key in candidate_by_key
            or candidate_key[0] >= len(commits)
            or candidate_key[1] not in _MESSAGE_CODES
            or candidate_key[2] not in membership
        ):
            raise ValueError("realized candidate identity is duplicate or crossed")
        candidate_by_key[candidate_key] = candidate
    for row in pairs:
        terminal = terminal_by_pair.get(str(row.get("replay_pair_id")))
        if (
            terminal is None
            or row.get("realized_terminal_id") != terminal.realized_terminal_id
            or row.get("upstream_terminal_row_id") != terminal.upstream_terminal_row_id
            or row.get("realization_status") != terminal.realization_status
            or row.get("realized_engage") is not terminal.realized_engage
            or row.get("realized_action") != terminal.realized_action
            or row.get("latent_class") != membership.get(terminal.user_id)
            or row.get("campaign_feedback_committed") is not terminal.realized_engage
        ):
            raise ValueError("realized pair row is crossed with terminal or membership")
        candidate = candidate_by_key.get(
            (terminal.replay_time_step, terminal.message_id, terminal.user_id)
        )
        if (
            candidate is None
            or _canonical_bool(candidate.get("selected"), "selected candidate") is not True
            or candidate.get("ranking_position") != row.get("ranking_position")
            or candidate.get("personalized_delivery_score_full_precision")
            != row.get("personalized_delivery_score_full_precision")
        ):
            raise ValueError("realized pair row is crossed with its selected candidate")
    committed_before: list[str] = []
    for expected_step, commit in enumerate(commits):
        if (
            commit.get("replay_time_step") != expected_step
            or commit.get("frozen_realized_positive_user_ids") != committed_before
        ):
            raise ValueError("realized batch commits violate the full-batch feedback barrier")
        expected_committed = sorted(
            {
                terminal.user_id
                for terminal in terminals
                if terminal.replay_time_step == expected_step and terminal.realized_engage
            }
        )
        if commit.get("committed_realized_positive_user_ids") != expected_committed:
            raise ValueError("realized batch commit differs from realized-positive users")
        committed_before = sorted(set(committed_before) | set(expected_committed))

    projection = _json_object(root / _PROJECTION_JSON, "realized projection")
    projection_identity = projection.pop("projection_identity", None)
    if (
        projection.get("schema_version") != FULL_POOL_TWO_STAGE_PROJECTION_SCHEMA
        or projection_identity != _json_sha256(projection)
        or projection.get("rows_sha256") != _json_sha256(projection.get("rows"))
        or projection.get("csv_sha256") != _sha256_file(root / _PROJECTION_CSV)
        or projection.get("total_exposure") != len(terminals)
        or projection.get("action_counts") != _action_counts(terminals)
    ):
        raise ValueError("realized projection closure is crossed")
    projection_rows = [
        _mapping(row, "realized projection row")
        for row in _sequence(projection.get("rows"), "realized projection rows")
    ]
    if _projection_csv_bytes(projection_rows) != (root / _PROJECTION_CSV).read_bytes():
        raise ValueError("realized projection CSV differs from its rows")
    expected_projection_rows = _projection_rows(
        terminals=terminals,
        membership=membership,
        committed_batches=len(commits),
    )
    if (
        projection_rows != expected_projection_rows
        or len(projection_rows) != counts.get("projection_rows")
    ):
        raise ValueError("realized projection rows differ from terminal facts")
    projection_ref = _mapping(manifest.get("projection"), "realized projection reference")
    if projection_ref != {
        "schema_version": FULL_POOL_TWO_STAGE_PROJECTION_SCHEMA,
        "identity": projection_identity,
        "json_sha256": artifacts[_PROJECTION_JSON]["sha256"],
        "csv_sha256": artifacts[_PROJECTION_CSV]["sha256"],
    }:
        raise ValueError("realized projection manifest reference is crossed")

    evidence = _json_object(root / _EVIDENCE_FILE, "realization evidence")
    evidence_identity = evidence.pop("evidence_identity", None)
    evidence_accounting = _mapping(evidence.get("accounting"), "realization evidence accounting")
    realization_accounting = _mapping(
        evidence_accounting.get("realization"), "realization-stage accounting"
    )
    expected_evidence_artifacts = {
        relative: artifacts[relative]["sha256"]
        for relative in (
            _CANDIDATE_FILE,
            _PAIR_FILE,
            _REALIZED_TERMINAL_FILE,
            _COMMIT_FILE,
            _MEMBERSHIP_FILE,
            _PROJECTION_JSON,
            _PROJECTION_CSV,
            _SCHEMA_FILE,
        )
    }
    evidence_lineage = _mapping(evidence.get("upstream_lineage"), "evidence upstream lineage")
    if (
        evidence.get("schema_version") != FULL_POOL_TWO_STAGE_EVIDENCE_SCHEMA
        or evidence_identity != _json_sha256(evidence)
        or evidence.get("replay_identity") != manifest.get("replay_identity")
        or evidence_lineage.get("source_identity") != upstream_identity
        or evidence_lineage.get("manifest_sha256") != upstream.get("manifest_sha256")
        or evidence.get("counts") != counts
        or evidence.get("action_counts") != manifest.get("action_counts")
        or evidence.get("realization_status_counts")
        != manifest.get("realization_status_counts")
        or realization_accounting != {"live_api_triggered": False, "provider_calls": 0}
        or evidence_accounting.get("composite_zero_provider_formal") is not False
        or evidence.get("accounting") != manifest.get("accounting")
        or evidence.get("artifact_hashes") != expected_evidence_artifacts
        or evidence.get("formal_research_evidence")
        is not manifest.get("formal_research_evidence")
        or evidence.get("production_deploy_eligible") is not False
    ):
        raise ValueError("realization evidence closure is crossed")
    evidence_ref = _mapping(manifest.get("evidence"), "realization evidence reference")
    if evidence_ref != {
        "schema_version": FULL_POOL_TWO_STAGE_EVIDENCE_SCHEMA,
        "identity": evidence_identity,
        "sha256": artifacts[_EVIDENCE_FILE]["sha256"],
    }:
        raise ValueError("realization evidence manifest reference is crossed")
    return manifest


def _projection_rows(
    *,
    terminals: Sequence[FullPoolRealizedTerminal],
    membership: Mapping[str, str],
    committed_batches: int,
) -> list[dict[str, int | str]]:
    counters = {
        (latent_class, message_id, time_step): Counter[str]()
        for latent_class in _SEGMENT_CODES
        for message_id in _MESSAGE_CODES
        for time_step in range(committed_batches)
    }
    for terminal in terminals:
        latent_class = membership.get(terminal.user_id)
        key = (latent_class, terminal.message_id, terminal.replay_time_step)
        if key not in counters:
            raise ValueError("realized terminal is crossed with projection membership or run")
        counter = counters[cast(tuple[str, str, int], key)]
        counter["Exposure"] += 1
        if terminal.realized_action == "like":
            counter["Total Likes"] += 1
        elif terminal.realized_action == "comment":
            counter["Total Comments"] += 1
        elif terminal.realized_action == "share":
            counter["Total Shares"] += 1
    rows: list[dict[str, int | str]] = []
    for latent_class, segment in _SEGMENT_CODES.items():
        for message_id, message in _MESSAGE_CODES.items():
            for time_step in range(committed_batches):
                counter = counters[(latent_class, message_id, time_step)]
                rows.append(
                    {
                        "Run": time_step + 1,
                        "Message": message,
                        "Segment": segment,
                        "Total Likes": counter["Total Likes"],
                        "Total Comments": counter["Total Comments"],
                        "Total Shares": counter["Total Shares"],
                        "Exposure": counter["Exposure"],
                    }
                )
    if sum(cast(int, row["Exposure"]) for row in rows) != len(terminals):
        raise ValueError("realized projection does not close total exposure")
    return rows


def _projection_csv_bytes(rows: Sequence[Mapping[str, object]]) -> bytes:
    stream = io.StringIO(newline="")
    fieldnames: list[str] = list(_PROJECTION_FIELDS)
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _action_counts(terminals: Sequence[FullPoolRealizedTerminal]) -> dict[str, int]:
    counts = Counter(terminal.realized_action for terminal in terminals)
    return {action: counts[action] for action in _ACTIONS}


def _status_counts(terminals: Sequence[FullPoolRealizedTerminal]) -> dict[str, int]:
    counts = Counter(terminal.realization_status for terminal in terminals)
    return {
        status: counts[status]
        for status in ("provider_ignore", "draw_pass", "draw_fail")
    }


def _artifact_inventory(
    root: Path,
    manifest: Mapping[str, object],
) -> dict[str, dict[str, object]]:
    references = _sequence(manifest.get("artifacts"), "realized artifact inventory")
    artifacts: dict[str, dict[str, object]] = {}
    for raw in references:
        ref = _mapping(raw, "realized artifact reference")
        if set(ref) != {"relative_path", "sha256", "bytes"}:
            raise ValueError("realized artifact reference fields are not exact")
        relative_text = _non_empty(ref.get("relative_path"), "realized artifact path")
        relative = PurePosixPath(relative_text)
        target = root / Path(*relative.parts)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or relative_text in artifacts
            or target.is_symlink()
            or not target.is_file()
            or _sha256_file(target) != _digest(ref.get("sha256"), "artifact SHA-256")
            or target.stat().st_size != _non_negative_int(ref.get("bytes"), "artifact bytes")
        ):
            raise ValueError("realized artifact inventory is unsafe or crossed")
        artifacts[relative_text] = ref
    entries = tuple(root.rglob("*"))
    if any(path.is_symlink() or not (path.is_file() or path.is_dir()) for path in entries):
        raise ValueError("realized source contains an unsafe inventory entry")
    actual = {
        path.relative_to(root).as_posix()
        for path in entries
        if path.is_file()
    }
    if actual != set(artifacts) | {"manifest.json"}:
        raise ValueError("realized source contains missing, extra, or unsafe files")
    return artifacts


def _read_membership(path: Path) -> dict[str, str]:
    membership: dict[str, str] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["user_id", "latent_class"]:
            raise ValueError("realized membership fields are not exact")
        for row in reader:
            user_id = _non_empty(row.get("user_id"), "membership user")
            latent_class = _non_empty(row.get("latent_class"), "membership class")
            if user_id in membership or latent_class not in _SEGMENT_CODES:
                raise ValueError("realized membership contains duplicate or unknown values")
            membership[user_id] = latent_class
    if not membership:
        raise ValueError("realized membership cannot be empty")
    return membership


def _canonical_jsonl(path: Path) -> list[dict[str, object]]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"realized JSONL is missing or unsafe: {path.name}")
    rows: list[dict[str, object]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.endswith("\n") or not line.strip():
                raise ValueError(f"realized JSONL line is noncanonical: {path.name}:{line_number}")
            try:
                row = _mapping(json.loads(line), f"{path.name}:{line_number}")
            except json.JSONDecodeError as exc:
                raise ValueError(f"realized JSONL is malformed: {path.name}:{line_number}") from exc
            if line != _canonical_json(row) + "\n":
                raise ValueError(f"realized JSONL line bytes are noncanonical: {path.name}:{line_number}")
            rows.append(row)
    return rows


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(_canonical_json(row) + "\n")


def _source_snapshot(root: Path) -> dict[str, tuple[str, int]]:
    entries = tuple(root.rglob("*"))
    if any(path.is_symlink() or not (path.is_file() or path.is_dir()) for path in entries):
        raise ValueError("immutable Source-v4 contains an unsafe inventory entry")
    return {
        path.relative_to(root).as_posix(): (_sha256_file(path), path.stat().st_size)
        for path in entries
        if path.is_file()
    }


def _file_ref(root: Path, path: Path) -> dict[str, object]:
    return {
        "relative_path": path.relative_to(root).as_posix(),
        "sha256": _sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _json_object(path: Path, context: str) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{context} is missing or unsafe")
    try:
        return _mapping(json.loads(path.read_text(encoding="utf-8")), context)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{context} is malformed") from exc


def _json_text_object(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, str):
        raise ValueError(f"{context} must be persisted JSON text")
    try:
        return _mapping(json.loads(value), context)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{context} is malformed") from exc


def _mapping(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be an object")
    return {str(key): item for key, item in value.items()}


def _sequence(value: object, context: str) -> list[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{context} must be an array")
    return list(value)


def _canonical_bool(value: object, context: str) -> bool:
    if value in (True, "true"):
        return True
    if value in (False, "false"):
        return False
    raise ValueError(f"{context} must be a canonical boolean")


def _non_empty(value: object, context: str) -> str:
    if not isinstance(value, str) or not value or "\0" in value:
        raise ValueError(f"{context} must be a non-empty NUL-free string")
    return value


def _non_negative_int(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{context} must be a non-negative integer")
    return value


def _positive_int(value: object, context: str) -> int:
    result = _non_negative_int(value, context)
    if result < 1:
        raise ValueError(f"{context} must be positive")
    return result


def _digest(value: object, context: str) -> str:
    text = _non_empty(value, context)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{context} is malformed")
    return text


def _explicit_directory(path: Path, context: str) -> Path:
    candidate = path.expanduser()
    if candidate.is_symlink():
        raise ValueError(f"{context} must be one explicit real directory")
    resolved = candidate.resolve(strict=True)
    if resolved != candidate.absolute() or not resolved.is_dir():
        raise ValueError(f"{context} must be one explicit real directory")
    return resolved


def _new_output_path(path: Path, *, source: Path) -> Path:
    candidate = path.expanduser()
    resolved = candidate.resolve(strict=False)
    if resolved != candidate.absolute():
        raise ValueError("realized output must be one canonical path")
    if os.path.lexists(resolved):
        raise FileExistsError(f"realized output already exists: {resolved}")
    if resolved == source or resolved.is_relative_to(source) or source.is_relative_to(resolved):
        raise ValueError("realized output must be independent from immutable Source-v4")
    return resolved


def _canonical_json(value: object) -> str:
    return json.dumps(
        safe_data(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _json_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"artifact is missing or unsafe: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(
            safe_data(value),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
