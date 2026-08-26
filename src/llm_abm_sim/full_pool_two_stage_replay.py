from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
import sqlite3
import tempfile
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from itertools import zip_longest
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast

from ._concurrent_runtime_spool import _ConcurrentRuntimeBatchSpool
from .concurrent_execution_journal import (
    ConcurrentExecutionJournal,
    _build_primary_only_concurrent_execution_run_identity,
)
from .concurrent_message_experiment import (
    CONCURRENT_MESSAGE_CANDIDATE_FIELDS,
    CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_DELIVERY_CAPACITY,
    CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_HORIZON,
    CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_SAMPLE_SIZE,
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
_REALIZED_MESSAGE_SUMMARY_FIELDS = frozenset(
    {
        "message_id",
        "message_title",
        "eligible_users",
        "ranked_candidates",
        "selected_user_ids",
        "seed_user_ids",
        "personalized_topup_user_ids",
        "realized_positive_user_ids",
        "below_delivery_capacity",
        "selection_reason_counts",
    }
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
_UPSTREAM_ACCOUNTING_FIELDS = frozenset(
    {
        "logical_judgments",
        "provider_responses",
        "successful_decisions",
        "external_request_invocations",
        "requested_model",
        "observed_model_counts",
        "usage_complete_response_count",
        "usage_missing_response_count",
        "usage_malformed_response_count",
        "provider_accounting",
        "settled_actual_attempts",
        "dispatched_without_settlement_uncertainty",
        "charged_physical_attempts",
        "physical_cap",
        "original_dispatch_count",
        "reconciliation_dispatch_count",
        "maximum_dispatches_for_one_pair",
        "maximum_request_invocations_for_one_dispatch",
        "evidence_profile",
        "formal_research_evidence",
        "production_deploy_eligible",
        "live_api_triggered",
    }
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
class ClosedFullPoolTwoStageSource:
    """Independently revalidated persisted facts for downstream consumers."""

    root: Path
    manifest_sha256: str
    source_identity: str
    classification: str
    production_deploy_eligible: bool
    formal_research_evidence: bool
    manifest: Mapping[str, object]
    evidence: Mapping[str, object]
    projection: Mapping[str, object]
    counts: Mapping[str, int]
    artifact_hashes: Mapping[str, str]
    projection_rows: tuple[Mapping[str, object], ...]

    @property
    def message_ids(self) -> tuple[str, ...]:
        return tuple(_MESSAGE_CODES)

    @property
    def horizon(self) -> int:
        return self.counts["batch_commits"]

    def iter_pair_terminal_rows(
        self,
    ) -> Iterator[tuple[Mapping[str, object], Mapping[str, object]]]:
        pairs = _iter_canonical_jsonl(self.root / _PAIR_FILE)
        terminals = _iter_canonical_jsonl(self.root / _REALIZED_TERMINAL_FILE)
        for pair, terminal in zip_longest(pairs, terminals):
            if pair is None or terminal is None:
                raise ValueError("realized pair and terminal streams have crossed denominators")
            if (
                pair.get("replay_pair_id") != terminal.get("replay_pair_id")
                or pair.get("realized_terminal_id") != terminal.get("realized_terminal_id")
                or pair.get("user_id") != terminal.get("user_id")
                or pair.get("message_id") != terminal.get("message_id")
                or pair.get("replay_time_step") != terminal.get("replay_time_step")
            ):
                raise ValueError("realized pair and terminal stream identities are crossed")
            yield pair, terminal

    def iter_batch_commits(self) -> Iterator[Mapping[str, object]]:
        yield from _iter_canonical_jsonl(self.root / _COMMIT_FILE)


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
    workspace: Path
    run_id: str
    identity_hash: str
    runtime_replay: Mapping[str, object]
    realized_terminal_spool: Path
    commits: tuple[dict[str, object], ...]
    runtime_resident_row_high_water: int


@dataclass(frozen=True)
class _StreamedRuntimeArtifacts:
    candidate_row_count: int
    pair_row_count: int
    realized_terminal_count: int
    batch_commit_count: int
    action_counts: dict[str, int]
    realization_status_counts: dict[str, int]
    projection_rows: list[dict[str, int | str]]


class _OneShotReplayJournal(ConcurrentExecutionJournal):
    """Keep only spool commit bindings for a non-resumable validation replay.

    The shared runtime kernel requires the journal protocol, but this one-shot path
    publishes only after complete validation and discards its staging directory on
    failure. Persisting three durable events per pair and a full candidate snapshot
    per batch would duplicate the independently hashed runtime spool without adding
    a recovery contract, so only compact snapshot identities and commit refs remain.
    """

    def __init__(self, workspace_dir: Path, identity: dict[str, Any]) -> None:
        super().__init__(workspace_dir, identity)
        self._runtime_records: list[dict[str, Any]] = []
        self._snapshot_hashes: set[str] = set()
        self._runtime_committed_batch_count = 0
        self._runtime_sequence = 0

    @classmethod
    def open_new(
        cls,
        workspace_dir: str | Path,
        *,
        identity: Mapping[str, Any],
    ) -> _OneShotReplayJournal:
        workspace = Path(workspace_dir)
        if os.path.lexists(workspace):
            raise FileExistsError(f"one-shot replay workspace already exists: {workspace}")
        workspace.mkdir(parents=True)
        return cls(workspace, dict(safe_data(identity)))

    def persist_snapshot(
        self,
        *,
        snapshot_type: str,
        snapshot_identity: Mapping[str, Any],
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        self._runtime_sequence += 1
        identity = dict(safe_data(snapshot_identity))
        snapshot_hash = _json_sha256(
            {
                "schema_version": "full-pool-two-stage-one-shot-snapshot-v1",
                "run_id": self.run_id,
                "identity_hash": self.identity_hash,
                "snapshot_type": _non_empty(snapshot_type, "snapshot type"),
                "snapshot_identity": identity,
                "planned_pair_count": _non_negative_int(
                    payload.get("planned_pair_count"), "planned pair count"
                ),
                "planned_variant_count": _non_negative_int(
                    payload.get("planned_variant_count"), "planned variant count"
                ),
            }
        )
        if snapshot_hash in self._snapshot_hashes:
            raise ValueError("one-shot replay snapshot identity is duplicate")
        self._snapshot_hashes.add(snapshot_hash)
        self._runtime_records.append(
            {
                "record_type": "snapshot",
                "snapshot_identity": identity,
                "snapshot_hash": snapshot_hash,
            }
        )
        return {
            "sequence": self._runtime_sequence,
            "snapshot_type": snapshot_type,
            "snapshot_identity": identity,
            "snapshot_hash": snapshot_hash,
            "snapshot_path": "one-shot-memory-only",
        }

    def append(
        self,
        *,
        event_type: str,
        event_identity: Mapping[str, Any],
        payload: Mapping[str, Any],
        batch_snapshot_hash: str | None = None,
    ) -> dict[str, Any]:
        self._runtime_sequence += 1
        identity = dict(safe_data(event_identity))
        if event_type in {
            "variant_started",
            "variant_terminal",
            "pair_closed",
            "batch_committed",
        } and batch_snapshot_hash not in self._snapshot_hashes:
            raise ValueError("one-shot replay event references an unknown batch snapshot")
        if event_type == "batch_committed":
            time_step = _non_negative_int(identity.get("time_step"), "commit time step")
            if time_step != self._runtime_committed_batch_count:
                raise ValueError("one-shot replay batch commits are not contiguous")
            self._runtime_records.append(
                {
                    "record_type": "event",
                    "event_type": event_type,
                    "event_identity": identity,
                    "batch_snapshot_hash": batch_snapshot_hash,
                    "payload": dict(safe_data(payload)),
                }
            )
            self._runtime_committed_batch_count += 1
        return {
            "sequence": self._runtime_sequence,
            "event_type": event_type,
            "event_identity": identity,
            "batch_snapshot_hash": batch_snapshot_hash,
        }

    def _replay_runtime(self) -> dict[str, Any]:
        return {
            "status": {
                "committed_batch_count": self._runtime_committed_batch_count,
            },
            "records": list(self._runtime_records),
        }


class _ProviderJudgmentStore:
    """Ephemeral disk index for unique Source-v4 judgments."""

    def __init__(
        self,
        *,
        connection: sqlite3.Connection,
        path: Path,
        source: _ClosedStrictFullPoolSource,
    ) -> None:
        self._connection = connection
        self.path = path
        self.source = source

    @classmethod
    def build(
        cls,
        source: _ClosedStrictFullPoolSource,
        *,
        path: Path,
    ) -> _ProviderJudgmentStore:
        if os.path.lexists(path):
            raise FileExistsError(f"Provider Judgment index already exists: {path}")
        connection = sqlite3.connect(path)
        try:
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute(
                """
                CREATE TABLE judgments (
                    user_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    pair_schedule_position INTEGER NOT NULL UNIQUE,
                    terminal_json TEXT NOT NULL,
                    PRIMARY KEY (user_id, message_id)
                ) WITHOUT ROWID
                """
            )
            try:
                with connection:
                    for terminal in _iter_source_terminal_rows(source):
                        judgment = _provider_judgment_from_terminal(source, terminal)
                        connection.execute(
                            "INSERT INTO judgments VALUES (?, ?, ?, ?)",
                            (
                                judgment.user_id,
                                judgment.message_id,
                                _non_negative_int(
                                    terminal.get("pair_schedule_position"),
                                    "upstream pair schedule position",
                                ),
                                _canonical_json(terminal),
                            ),
                        )
            except sqlite3.IntegrityError as exc:
                raise ValueError(
                    "Source-v4 Provider Judgment mapping is duplicate, failed, or crossed"
                ) from exc

            expected_count = len(source.membership) * len(_MESSAGE_CODES)
            count, minimum_position, maximum_position = cast(
                tuple[int, int | None, int | None],
                connection.execute(
                    "SELECT COUNT(*), MIN(pair_schedule_position), MAX(pair_schedule_position) "
                    "FROM judgments"
                ).fetchone(),
            )
            if (
                count != expected_count
                or minimum_position != 0
                or maximum_position != expected_count - 1
            ):
                raise ValueError("Source-v4 Provider Judgment inventory is missing or crossed")
            return cls(connection=connection, path=path, source=source)
        except BaseException:
            connection.close()
            path.unlink(missing_ok=True)
            raise

    def resolve(self, *, user_id: str, message_id: str) -> _ProviderJudgment:
        row = self._connection.execute(
            "SELECT terminal_json FROM judgments WHERE user_id = ? AND message_id = ?",
            (user_id, message_id),
        ).fetchone()
        if row is None:
            raise ValueError("replay selected a pair without one unique Provider Judgment")
        try:
            terminal = _mapping(json.loads(str(row[0])), "indexed Source-v4 terminal row")
        except json.JSONDecodeError as exc:
            raise ValueError("indexed Source-v4 terminal row is malformed") from exc
        return _provider_judgment_from_terminal(self.source, terminal)

    def close(self) -> None:
        self._connection.close()


class _RealizedFactsAccumulator:
    def __init__(
        self,
        *,
        membership: Mapping[str, str],
        committed_batches: int,
    ) -> None:
        self.membership = membership
        self.committed_batches = committed_batches
        self.terminal_count = 0
        self._actions: Counter[str] = Counter()
        self._statuses: Counter[str] = Counter()
        self._projection = {
            (latent_class, message_id, time_step): Counter[str]()
            for latent_class in _SEGMENT_CODES
            for message_id in _MESSAGE_CODES
            for time_step in range(committed_batches)
        }

    def consume(self, terminal: FullPoolRealizedTerminal) -> None:
        latent_class = self.membership.get(terminal.user_id)
        key = (latent_class, terminal.message_id, terminal.replay_time_step)
        if key not in self._projection:
            raise ValueError(
                "realized terminal is crossed with projection membership or run"
            )
        counter = self._projection[cast(tuple[str, str, int], key)]
        counter["Exposure"] += 1
        if terminal.realized_action == "like":
            counter["Total Likes"] += 1
        elif terminal.realized_action == "comment":
            counter["Total Comments"] += 1
        elif terminal.realized_action == "share":
            counter["Total Shares"] += 1
        self._actions[terminal.realized_action] += 1
        self._statuses[terminal.realization_status] += 1
        self.terminal_count += 1

    @property
    def action_counts(self) -> dict[str, int]:
        return {action: self._actions[action] for action in _ACTIONS}

    @property
    def status_counts(self) -> dict[str, int]:
        return {
            status: self._statuses[status]
            for status in ("provider_ignore", "draw_pass", "draw_fail")
        }

    def projection_rows(self) -> list[dict[str, int | str]]:
        rows: list[dict[str, int | str]] = []
        for latent_class, segment in _SEGMENT_CODES.items():
            for message_id, message in _MESSAGE_CODES.items():
                for time_step in range(self.committed_batches):
                    counter = self._projection[(latent_class, message_id, time_step)]
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
        if sum(cast(int, row["Exposure"]) for row in rows) != self.terminal_count:
            raise ValueError("realized projection does not close total exposure")
        return rows


class FullPoolTwoStageReplay:
    """High-level replay Interface: verify one source, rebuild feedback, and close artifacts."""

    def run_and_close(
        self,
        request: FullPoolTwoStageReplayRequest,
    ) -> FullPoolTwoStageReplayResult:
        source_snapshot = _source_snapshot(request.source_root)
        closed = read_closed_strict_full_pool_source(
            request.source_root,
            manifest_sha256=request.source_manifest_sha256,
        )
        if _source_snapshot(request.source_root) != source_snapshot:
            raise ValueError("immutable Source-v4 bytes changed during source verification")
        if closed.source_identity != request.source_identity:
            raise ValueError("Source-v4 identity differs from the explicit replay binding")
        config, prepared, dataset_lineage = _prepare_replay_runtime(closed)
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
        published = False
        try:
            judgment_index_path = staging / ".provider-judgments.sqlite3"
            judgments = _ProviderJudgmentStore.build(closed, path=judgment_index_path)
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
            finally:
                judgments.close()
                _remove_sqlite_files(judgment_index_path)
            _write_closed_source(
                staging=staging,
                request=request,
                closed=closed,
                config=config,
                runtime=runtime,
                replay_identity=replay_identity,
                dataset_lineage=dataset_lineage,
            )
            shutil.rmtree(runtime.workspace)
            manifest_sha256 = _sha256_file(staging / "manifest.json")
            _validate_closed_source(staging, manifest_sha256=manifest_sha256)
            if _source_snapshot(request.source_root) != source_snapshot:
                raise ValueError("immutable Source-v4 bytes changed during realization replay")
            os.replace(staging, request.output_dir)
            published = True
            _fsync_directory(request.output_dir.parent)

            manifest_sha256 = _sha256_file(request.output_dir / "manifest.json")
            manifest = _validate_closed_source(
                request.output_dir,
                manifest_sha256=manifest_sha256,
            )
            if _source_snapshot(request.source_root) != source_snapshot:
                raise ValueError("immutable Source-v4 bytes changed after realization replay closure")
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            if published:
                _remove_published_output(request.output_dir)
            raise

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


def read_closed_full_pool_two_stage_source(
    source_root: str | Path,
    *,
    manifest_sha256: str,
) -> ClosedFullPoolTwoStageSource:
    """Validate one explicit realized source and expose only persisted source-bound facts."""
    root = _explicit_directory(Path(source_root), "realized source")
    before = _source_snapshot(root)
    manifest = _validate_closed_source(root, manifest_sha256=manifest_sha256)
    if _source_snapshot(root) != before:
        raise ValueError("immutable realized source bytes changed during persisted read")
    evidence = _json_object(root / _EVIDENCE_FILE, "realization evidence")
    projection = _json_object(root / _PROJECTION_JSON, "realized projection")
    counts_raw = _mapping(manifest.get("counts"), "realized source counts")
    counts = {
        field: _non_negative_int(counts_raw.get(field), f"realized {field}")
        for field in sorted(_COUNT_FIELDS)
    }
    artifacts = {
        _non_empty(row.get("relative_path"), "realized artifact path"): _digest(
            row.get("sha256"), "realized artifact SHA-256"
        )
        for raw in _sequence(manifest.get("artifacts"), "realized artifacts")
        for row in (_mapping(raw, "realized artifact"),)
    }
    projection_rows = tuple(
        _mapping(row, "realized projection row")
        for row in _sequence(projection.get("rows"), "realized projection rows")
    )
    return ClosedFullPoolTwoStageSource(
        root=root,
        manifest_sha256=_digest(manifest_sha256, "realized manifest SHA-256"),
        source_identity=_non_empty(manifest.get("source_identity"), "realized source identity"),
        classification=_non_empty(manifest.get("classification"), "realized source classification"),
        production_deploy_eligible=_canonical_bool(
            manifest.get("production_deploy_eligible"),
            "realized production eligibility",
        ),
        formal_research_evidence=_canonical_bool(
            manifest.get("formal_research_evidence"),
            "realized Formal classification",
        ),
        manifest=manifest,
        evidence=evidence,
        projection=projection,
        counts=counts,
        artifact_hashes=artifacts,
        projection_rows=projection_rows,
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


def _iter_source_terminal_rows(
    source: _ClosedStrictFullPoolSource,
) -> Iterator[dict[str, object]]:
    yield from _iter_canonical_jsonl(source.root / "terminal_rows.jsonl")


def _provider_judgment_from_terminal(
    source: _ClosedStrictFullPoolSource,
    terminal: Mapping[str, object],
    *,
    expected_time_step: int | None = None,
) -> _ProviderJudgment:
    terminal_time_step = _non_negative_int(
        terminal.get("time_step"), "upstream terminal time step"
    )
    user_id = _non_empty(terminal.get("user_id"), "upstream terminal user")
    message_id = _non_empty(terminal.get("message_id"), "upstream terminal message")
    pair_id = _non_empty(terminal.get("pair_id"), "upstream pair id")
    terminal_id = _non_empty(terminal.get("terminal_row_id"), "upstream terminal row id")
    if (
        (expected_time_step is not None and terminal_time_step != expected_time_step)
        or terminal_time_step >= source.facts.committed_batches
        or terminal.get("decision_variant") != "primary"
        or terminal.get("terminal_status") != "succeeded"
        or terminal.get("provider_status") != "succeeded"
        or pair_id != f"{user_id}:{message_id}:{terminal_time_step}"
        or terminal_id != f"{pair_id}:primary"
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
    return _ProviderJudgment(
        terminal_row_id=terminal_id,
        pair_id=pair_id,
        time_step=terminal_time_step,
        message_id=message_id,
        user_id=user_id,
        decision=decision,
        prompt_version=_non_empty(terminal.get("prompt_version"), "upstream prompt version"),
        environmental_consciousness_prompt_inclusion="included",
        source_terminal=terminal,
    )


def _provider_judgment_inventory(
    source: _ClosedStrictFullPoolSource,
) -> dict[tuple[str, str, str, str], _ProviderJudgment]:
    """Small-fixture audit helper; production replay uses the disk-backed store."""
    inventory: dict[tuple[str, str, str, str], _ProviderJudgment] = {}
    schedule_positions: set[int] = set()
    for time_step in range(source.facts.committed_batches):
        batch = source.read_batch(time_step)
        rows = _mapping(batch.get("rows"), "Source-v4 batch rows")
        for raw in _sequence(rows.get("terminal_rows"), "Source-v4 terminal rows"):
            terminal = _mapping(raw, "Source-v4 terminal row")
            judgment = _provider_judgment_from_terminal(
                source,
                terminal,
                expected_time_step=time_step,
            )
            key = (source.source_identity, judgment.user_id, judgment.message_id, "primary")
            position = _non_negative_int(
                terminal.get("pair_schedule_position"), "upstream pair schedule position"
            )
            if key in inventory or position in schedule_positions:
                raise ValueError(
                    "Source-v4 Provider Judgment mapping is duplicate, failed, or crossed"
                )
            inventory[key] = judgment
            schedule_positions.add(position)

    expected = {
        (source.source_identity, user_id, message_id, "primary")
        for user_id in source.membership
        for message_id in _MESSAGE_CODES
    }
    if (
        set(inventory) != expected
        or schedule_positions != set(range(len(expected)))
    ):
        raise ValueError("Source-v4 Provider Judgment inventory is missing or crossed")
    return inventory


def _run_replay_runtime(
    *,
    config: ConcurrentMessageExperimentConfig,
    prepared: _PreparedConcurrentRuntimeInputs,
    closed: _ClosedStrictFullPoolSource,
    judgments: _ProviderJudgmentStore,
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
    journal = _OneShotReplayJournal.open_new(workspace, identity=identity)
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
    realized_terminal_spool = workspace / "realized-terminal-spool.jsonl"
    commits: list[dict[str, object]] = []
    replay: Mapping[str, object]
    try:
        with realized_terminal_spool.open("x", encoding="utf-8", newline="\n") as handle:
            while state.next_time_step < config.horizon:
                kernel.plan_batch()
                plans = kernel.pending_plans()
                for plan in plans:
                    judgment = judgments.resolve(
                        user_id=plan.user.user_id,
                        message_id=plan.message.message_id,
                    )
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
                    handle.write(realized_terminal.canonical_json_line())
                commit = kernel.commit_primary_batch()
                commits.append(_realized_commit(commit))

        replay = journal._replay_runtime()
        if kernel.validate_spool(replay) != config.horizon:
            raise ValueError("replay runtime spool does not close every committed batch")
    finally:
        journal.close()

    expected_pairs = len(prepared.cohort.sample_user_ids) * len(config.messages)
    if (
        state.pair_schedule_position != expected_pairs
        or state.pair_schedule_position != closed.facts.logical_pairs
        or kernel.runtime_resident_row_count != 0
        or len(commits) != config.horizon
    ):
        raise ValueError("replay runtime did not close and release every realized pair")
    return _ReplayRuntimeResult(
        workspace=workspace,
        run_id=journal.run_id,
        identity_hash=journal.identity_hash,
        runtime_replay=replay,
        realized_terminal_spool=realized_terminal_spool,
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


def _stream_runtime_artifacts(
    *,
    staging: Path,
    closed: _ClosedStrictFullPoolSource,
    config: ConcurrentMessageExperimentConfig,
    runtime: _ReplayRuntimeResult,
) -> _StreamedRuntimeArtifacts:
    spool = _ConcurrentRuntimeBatchSpool(
        runtime.workspace,
        run_id=runtime.run_id,
        identity_hash=runtime.identity_hash,
        terminal_variants=("primary",),
    )
    terminal_rows = iter(_iter_canonical_jsonl(runtime.realized_terminal_spool))
    commits = iter(runtime.commits)
    accumulator = _RealizedFactsAccumulator(
        membership=closed.membership,
        committed_batches=config.horizon,
    )
    candidate_count = 0
    pair_count = 0
    commit_count = 0
    with (
        (staging / _CANDIDATE_FILE).open("x", encoding="utf-8", newline="\n") as candidate_handle,
        (staging / _PAIR_FILE).open("x", encoding="utf-8", newline="\n") as pair_handle,
        (staging / _REALIZED_TERMINAL_FILE).open(
            "x", encoding="utf-8", newline="\n"
        ) as terminal_handle,
        (staging / _COMMIT_FILE).open("x", encoding="utf-8", newline="\n") as commit_handle,
    ):
        for chunk in spool.iter_committed(runtime.runtime_replay):
            try:
                commit = next(commits)
            except StopIteration as exc:
                raise ValueError("realized commit stream ends before the runtime spool") from exc
            if commit.get("replay_time_step") != chunk.time_step:
                raise ValueError("realized commit stream is crossed with the runtime spool")
            for candidate in chunk.candidate_rows:
                candidate_handle.write(_canonical_json(candidate) + "\n")
                candidate_count += 1
            for result_row in chunk.result_rows:
                try:
                    terminal_payload = next(terminal_rows)
                except StopIteration as exc:
                    raise ValueError(
                        "realized terminal stream ends before the runtime spool"
                    ) from exc
                terminal = FullPoolRealizedTerminal.model_validate(terminal_payload)
                if (
                    terminal.replay_time_step != chunk.time_step
                    or terminal.replay_pair_schedule_position != pair_count
                    or terminal.replay_pair_id != result_row.get("pair_id")
                ):
                    raise ValueError("realized terminal stream is crossed with runtime pairs")
                pair = _realized_pair_row(result_row, terminal, closed.membership)
                pair_handle.write(_canonical_json(pair) + "\n")
                terminal_handle.write(terminal.canonical_json_line())
                accumulator.consume(terminal)
                pair_count += 1
            commit_handle.write(_canonical_json(commit) + "\n")
            commit_count += 1

    if next(terminal_rows, None) is not None or next(commits, None) is not None:
        raise ValueError("realized terminal or commit stream exceeds the runtime spool")
    if (
        candidate_count != closed.facts.candidate_rows
        or pair_count != closed.facts.logical_pairs
        or accumulator.terminal_count != pair_count
        or commit_count != config.horizon
    ):
        raise ValueError("streamed replay artifacts do not close the runtime denominator")
    return _StreamedRuntimeArtifacts(
        candidate_row_count=candidate_count,
        pair_row_count=pair_count,
        realized_terminal_count=accumulator.terminal_count,
        batch_commit_count=commit_count,
        action_counts=accumulator.action_counts,
        realization_status_counts=accumulator.status_counts,
        projection_rows=accumulator.projection_rows(),
    )


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
    streamed = _stream_runtime_artifacts(
        staging=staging,
        closed=closed,
        config=config,
        runtime=runtime,
    )
    membership_bytes = (closed.root / _MEMBERSHIP_FILE).read_bytes()
    (staging / _MEMBERSHIP_FILE).write_bytes(membership_bytes)

    projection_rows = streamed.projection_rows
    projection_csv = _projection_csv_bytes(projection_rows)
    (staging / _PROJECTION_CSV).write_bytes(projection_csv)
    action_counts = streamed.action_counts
    projection_body = {
        "schema_version": FULL_POOL_TWO_STAGE_PROJECTION_SCHEMA,
        "replay_identity": replay_identity,
        "upstream_source_identity": closed.source_identity,
        "rows": projection_rows,
        "rows_sha256": _json_sha256(projection_rows),
        "csv_file": _PROJECTION_CSV,
        "csv_sha256": hashlib.sha256(projection_csv).hexdigest(),
        "action_counts": action_counts,
        "total_exposure": streamed.realized_terminal_count,
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
    status_counts = streamed.realization_status_counts
    counts = {
        "users": len(closed.membership),
        "messages": len(config.messages),
        "pairs": streamed.pair_row_count,
        "exposures": streamed.realized_terminal_count,
        "realized_terminals": streamed.realized_terminal_count,
        "batch_commits": streamed.batch_commit_count,
        "candidate_rows": streamed.candidate_row_count,
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
    persisted_provider_accounting = _mapping(
        closed.manifest.get("provider_accounting"),
        "upstream persisted Provider accounting",
    )
    upstream_accounting = {
        "logical_judgments": closed.facts.logical_pairs,
        "provider_responses": closed.facts.provider_responses,
        "successful_decisions": closed.facts.successful_decisions,
        "external_request_invocations": closed.facts.external_request_invocations,
        "requested_model": closed.contract.formal_execution.requested_model,
        "observed_model_counts": dict(closed.facts.observed_model_counts),
        "usage_complete_response_count": closed.facts.usage_complete_response_count,
        "usage_missing_response_count": closed.facts.usage_missing_response_count,
        "usage_malformed_response_count": closed.facts.usage_malformed_response_count,
        "provider_accounting": persisted_provider_accounting,
        "settled_actual_attempts": closed.facts.settled_actual_attempts,
        "dispatched_without_settlement_uncertainty": (
            closed.facts.dispatched_without_settlement_uncertainty
        ),
        "charged_physical_attempts": closed.facts.charged_physical_attempts,
        "physical_cap": closed.facts.physical_cap,
        "original_dispatch_count": closed.facts.original_dispatch_count,
        "reconciliation_dispatch_count": closed.facts.reconciliation_dispatch_count,
        "maximum_dispatches_for_one_pair": closed.facts.maximum_dispatches_for_one_pair,
        "maximum_request_invocations_for_one_dispatch": (
            closed.facts.maximum_request_invocations_for_one_dispatch
        ),
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


def _validate_upstream_accounting(
    accounting: Mapping[str, object],
    *,
    logical_judgments: int,
    expected_formal: bool,
) -> None:
    if set(accounting) != _UPSTREAM_ACCOUNTING_FIELDS:
        raise ValueError("realized upstream accounting fields are not exact")
    requested_model = _non_empty(accounting.get("requested_model"), "upstream requested model")
    provider_responses = _non_negative_int(
        accounting.get("provider_responses"), "upstream Provider responses"
    )
    successful_decisions = _non_negative_int(
        accounting.get("successful_decisions"), "upstream successful decisions"
    )
    observed_models = _mapping(
        accounting.get("observed_model_counts"), "upstream observed models"
    )
    observed_counts = {
        model: _non_negative_int(count, "upstream observed model count")
        for model, count in observed_models.items()
    }
    provider_accounting = _mapping(
        accounting.get("provider_accounting"), "upstream persisted Provider accounting"
    )
    input_tokens = _non_negative_int(
        provider_accounting.get("input_tokens"), "upstream input tokens"
    )
    output_tokens = _non_negative_int(
        provider_accounting.get("output_tokens"), "upstream output tokens"
    )
    total_tokens = _non_negative_int(
        provider_accounting.get("total_tokens"), "upstream total tokens"
    )
    cached_tokens = provider_accounting.get("cached_input_tokens")
    if cached_tokens is not None:
        _non_negative_int(cached_tokens, "upstream cached input tokens")
    cached_reported = _non_negative_int(
        provider_accounting.get("cached_input_tokens_reported_response_count"),
        "upstream cached usage response count",
    )
    settled_attempts = _non_negative_int(
        accounting.get("settled_actual_attempts"), "upstream settled attempts"
    )
    uncertain_attempts = _non_negative_int(
        accounting.get("dispatched_without_settlement_uncertainty"),
        "upstream uncertain attempts",
    )
    charged_attempts = _non_negative_int(
        accounting.get("charged_physical_attempts"), "upstream charged attempts"
    )
    physical_cap = _non_negative_int(accounting.get("physical_cap"), "upstream physical cap")
    original_dispatches = _non_negative_int(
        accounting.get("original_dispatch_count"), "upstream original dispatches"
    )
    reconciliations = _non_negative_int(
        accounting.get("reconciliation_dispatch_count"),
        "upstream reconciliation dispatches",
    )
    external_requests = _non_negative_int(
        accounting.get("external_request_invocations"), "upstream external requests"
    )
    if (
        _non_negative_int(accounting.get("logical_judgments"), "upstream judgments")
        != logical_judgments
        or provider_responses != logical_judgments
        or successful_decisions != logical_judgments
        or observed_counts != {requested_model: provider_responses}
        or provider_accounting.get("provider_response_count") != provider_responses
        or provider_accounting.get("successful_decision_count") != successful_decisions
        or provider_accounting.get("external_request_invocations") != external_requests
        or provider_accounting.get("observed_model_counts") != observed_counts
        or accounting.get("usage_complete_response_count") != provider_responses
        or provider_accounting.get("usage_complete_response_count") != provider_responses
        or accounting.get("usage_missing_response_count") != 0
        or provider_accounting.get("usage_missing_response_count") != 0
        or accounting.get("usage_malformed_response_count") != 0
        or provider_accounting.get("usage_malformed_response_count") != 0
        or total_tokens != input_tokens + output_tokens
        or cached_reported > provider_responses
        or original_dispatches != logical_judgments
        or charged_attempts != settled_attempts + uncertain_attempts
        or charged_attempts > physical_cap
        or reconciliations > logical_judgments
        or accounting.get("maximum_dispatches_for_one_pair") not in {1, 2}
        or not 1
        <= _positive_int(
            accounting.get("maximum_request_invocations_for_one_dispatch"),
            "upstream maximum request invocations",
        )
        <= 3
        or (expected_formal and external_requests < logical_judgments)
        or (expected_formal and uncertain_attempts != 0)
    ):
        raise ValueError("realized upstream model, usage, or attempt accounting is crossed")


class _StepRowReader:
    """Read canonical JSONL in nondecreasing time-step groups without retaining history."""

    def __init__(
        self,
        rows: Iterable[dict[str, object]],
        *,
        field_name: str,
        context: str,
    ) -> None:
        self._rows = iter(rows)
        self._field_name = field_name
        self._context = context
        self._next: dict[str, object] | None = None
        self._next_step: int | None = None
        self._last_step = -1
        self._advance()

    def _advance(self) -> None:
        try:
            row = next(self._rows)
        except StopIteration:
            self._next = None
            self._next_step = None
            return
        step = _non_negative_int(row.get(self._field_name), self._context)
        if step < self._last_step:
            raise ValueError(f"{self._context} rows are not grouped in canonical order")
        self._last_step = step
        self._next = row
        self._next_step = step

    def take(self, expected_step: int) -> Iterator[dict[str, object]]:
        if self._next_step is not None and self._next_step < expected_step:
            raise ValueError(f"{self._context} rows repeat an already closed batch")
        while self._next is not None and self._next_step == expected_step:
            row = self._next
            self._advance()
            yield row

    def assert_exhausted(self) -> None:
        if self._next is not None:
            raise ValueError(f"{self._context} rows exceed the committed batch denominator")


def _string_values(value: object, context: str) -> list[str]:
    return [_non_empty(item, context) for item in _sequence(value, context)]


def _validate_streamed_rows(
    *,
    root: Path,
    manifest: Mapping[str, object],
    upstream: Mapping[str, object],
    membership: Mapping[str, str],
    commits: Sequence[Mapping[str, object]],
) -> _StreamedRuntimeArtifacts:
    candidate_reader = _StepRowReader(
        _iter_canonical_jsonl(root / _CANDIDATE_FILE),
        field_name="time_step",
        context="realized candidate time step",
    )
    pair_reader = _StepRowReader(
        _iter_canonical_jsonl(root / _PAIR_FILE),
        field_name="replay_time_step",
        context="realized pair time step",
    )
    terminal_reader = _StepRowReader(
        _iter_canonical_jsonl(root / _REALIZED_TERMINAL_FILE),
        field_name="replay_time_step",
        context="realized terminal time step",
    )
    replay_identity = _digest(manifest.get("replay_identity"), "realized replay identity")
    upstream_identity = _non_empty(upstream.get("source_identity"), "upstream source identity")
    accumulator = _RealizedFactsAccumulator(
        membership=membership,
        committed_batches=len(commits),
    )
    seen_users_by_message = {message_id: set[str]() for message_id in _MESSAGE_CODES}
    candidate_count = 0
    pair_count = 0
    committed_before: list[str] = []
    production_upstream = upstream.get("production_deploy_eligible") is True
    final_capacity = (
        CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_SAMPLE_SIZE
        - CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_DELIVERY_CAPACITY
        * (CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_HORIZON - 1)
    )

    for expected_step, commit in enumerate(commits):
        if set(commit) != set(_COMMIT_FIELDS) or commit.get("replay_time_step") != expected_step:
            raise ValueError("realized batch commit fields or order are not exact")
        if commit.get("frozen_realized_positive_user_ids") != committed_before:
            raise ValueError("realized batch commits violate the full-batch feedback barrier")

        selected_candidates: dict[tuple[str, str], Mapping[str, object]] = {}
        candidate_keys: set[tuple[str, str]] = set()
        candidate_counts: Counter[str] = Counter()
        next_ranking_position: Counter[str] = Counter()
        for candidate in candidate_reader.take(expected_step):
            if set(candidate) != set(CONCURRENT_MESSAGE_CANDIDATE_FIELDS):
                raise ValueError("realized candidate row fields are not exact")
            message_id = _non_empty(candidate.get("message_id"), "candidate message")
            user_id = _non_empty(candidate.get("user_id"), "candidate user")
            key = (message_id, user_id)
            ranking_position = _positive_int(
                candidate.get("ranking_position"), "candidate ranking position"
            )
            next_ranking_position[message_id] += 1
            if (
                message_id not in _MESSAGE_CODES
                or user_id not in membership
                or key in candidate_keys
                or ranking_position != next_ranking_position[message_id]
            ):
                raise ValueError("realized candidate identity is duplicate or crossed")
            candidate_keys.add(key)
            candidate_counts[message_id] += 1
            candidate_count += 1
            if _canonical_bool(candidate.get("selected"), "selected candidate"):
                selected_candidates[key] = candidate

        selected_user_ids = {message_id: [] for message_id in _MESSAGE_CODES}
        seed_user_ids = {message_id: [] for message_id in _MESSAGE_CODES}
        topup_user_ids = {message_id: [] for message_id in _MESSAGE_CODES}
        positive_user_ids = {message_id: [] for message_id in _MESSAGE_CODES}
        selection_reason_counts = {
            message_id: Counter[str]() for message_id in _MESSAGE_CODES
        }
        message_titles: dict[str, str] = {}
        batch_positive_users: set[str] = set()
        sentinel = object()
        pair_rows = pair_reader.take(expected_step)
        terminal_rows = terminal_reader.take(expected_step)
        for pair_raw, terminal_raw in zip_longest(
            pair_rows,
            terminal_rows,
            fillvalue=sentinel,
        ):
            if pair_raw is sentinel or terminal_raw is sentinel:
                raise ValueError("realized pair and terminal row counts differ within a batch")
            pair = cast(dict[str, object], pair_raw)
            terminal = FullPoolRealizedTerminal.model_validate(
                cast(dict[str, object], terminal_raw)
            )
            if set(pair) != set(_PAIR_FIELDS):
                raise ValueError("realized pair row fields are not exact")
            if terminal.replay_pair_schedule_position != pair_count:
                raise ValueError("realized terminal schedule positions are not contiguous")
            if (
                terminal.upstream_source_identity != upstream_identity
                or terminal.upstream_terminal_row_id
                != f"{terminal.upstream_pair_id}:primary"
                or not terminal.upstream_pair_id.startswith(
                    f"{terminal.user_id}:{terminal.message_id}:"
                )
                or terminal.replay_pair_id
                != f"{terminal.user_id}:{terminal.message_id}:{expected_step}"
                or terminal.realized_terminal_id
                != _realized_terminal_identity(
                    replay_identity=replay_identity,
                    upstream_terminal_row_id=terminal.upstream_terminal_row_id,
                    replay_pair_id=terminal.replay_pair_id,
                )
            ):
                raise ValueError("realized terminal lineage or identity is crossed")
            message_seen = seen_users_by_message.get(terminal.message_id)
            if message_seen is None or terminal.user_id in message_seen:
                raise ValueError("realized source repeats a user-message exposure")
            message_seen.add(terminal.user_id)
            candidate = selected_candidates.pop(
                (terminal.message_id, terminal.user_id),
                None,
            )
            if (
                candidate is None
                or candidate.get("ranking_position") != pair.get("ranking_position")
                or candidate.get("personalized_delivery_score_full_precision")
                != pair.get("personalized_delivery_score_full_precision")
                or pair.get("replay_pair_id") != terminal.replay_pair_id
                or pair.get("realized_terminal_id") != terminal.realized_terminal_id
                or pair.get("upstream_terminal_row_id")
                != terminal.upstream_terminal_row_id
                or pair.get("realization_status") != terminal.realization_status
                or pair.get("realized_engage") is not terminal.realized_engage
                or pair.get("realized_action") != terminal.realized_action
                or pair.get("latent_class") != membership.get(terminal.user_id)
                or pair.get("campaign_feedback_committed")
                is not terminal.realized_engage
                or pair.get("selection_reason") != candidate.get("selection_reason")
                or pair.get("is_seed")
                is not _canonical_bool(candidate.get("is_seed"), "candidate seed flag")
            ):
                raise ValueError(
                    "realized pair row is crossed with terminal, candidate, or membership"
                )
            message_id = terminal.message_id
            selected_user_ids[message_id].append(terminal.user_id)
            message_titles.setdefault(
                message_id,
                _non_empty(pair.get("message_title"), "realized message title"),
            )
            if pair.get("message_title") != message_titles[message_id]:
                raise ValueError("realized pair message titles are crossed")
            if pair.get("is_seed") is True:
                seed_user_ids[message_id].append(terminal.user_id)
            selection_reason = _non_empty(
                pair.get("selection_reason"), "realized selection reason"
            )
            selection_reason_counts[message_id][selection_reason] += 1
            if selection_reason == "personalized_topup":
                topup_user_ids[message_id].append(terminal.user_id)
            if terminal.realized_engage:
                positive_user_ids[message_id].append(terminal.user_id)
                batch_positive_users.add(terminal.user_id)
            accumulator.consume(terminal)
            pair_count += 1

        if selected_candidates:
            raise ValueError("selected candidates exceed realized pairs in one batch")
        summaries = _sequence(commit.get("messages"), "realized commit messages")
        if len(summaries) != len(_MESSAGE_CODES):
            raise ValueError("realized commit message denominator is crossed")
        for message_id, summary_raw in zip(_MESSAGE_CODES, summaries, strict=True):
            summary = _mapping(summary_raw, "realized commit message summary")
            if (
                set(summary) != _REALIZED_MESSAGE_SUMMARY_FIELDS
                or summary.get("message_id") != message_id
                or summary.get("message_title") != message_titles.get(message_id)
                or summary.get("eligible_users") != candidate_counts[message_id]
                or summary.get("ranked_candidates") != candidate_counts[message_id]
                or summary.get("selected_user_ids") != selected_user_ids[message_id]
                or summary.get("seed_user_ids") != seed_user_ids[message_id]
                or summary.get("personalized_topup_user_ids")
                != topup_user_ids[message_id]
                or summary.get("realized_positive_user_ids")
                != positive_user_ids[message_id]
                or summary.get("below_delivery_capacity")
                != candidate_counts[message_id] - len(selected_user_ids[message_id])
                or summary.get("selection_reason_counts")
                != dict(selection_reason_counts[message_id])
            ):
                raise ValueError(
                    "realized batch commit differs from candidates, pairs, or terminals"
                )
            if production_upstream:
                expected_capacity = (
                    final_capacity
                    if expected_step
                    == CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_HORIZON - 1
                    else CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_DELIVERY_CAPACITY
                )
                if len(selected_user_ids[message_id]) != expected_capacity:
                    raise ValueError("realized production delivery capacity is crossed")

        expected_committed = sorted(batch_positive_users)
        if commit.get("committed_realized_positive_user_ids") != expected_committed:
            raise ValueError("realized batch commit differs from realized-positive users")
        committed_before = sorted(set(committed_before) | batch_positive_users)

    candidate_reader.assert_exhausted()
    pair_reader.assert_exhausted()
    terminal_reader.assert_exhausted()
    membership_users = set(membership)
    if any(users != membership_users for users in seen_users_by_message.values()):
        raise ValueError("realized source does not close the user-message denominator")

    if production_upstream:
        expected_candidate_rows = len(_MESSAGE_CODES) * sum(
            CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_SAMPLE_SIZE
            - CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_DELIVERY_CAPACITY * time_step
            for time_step in range(CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_HORIZON)
        )
        if (
            len(membership) != CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_SAMPLE_SIZE
            or len(commits) != CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_HORIZON
            or pair_count
            != CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_SAMPLE_SIZE * len(_MESSAGE_CODES)
            or candidate_count != expected_candidate_rows
        ):
            raise ValueError("realized production Full-Pool topology is incomplete")

    return _StreamedRuntimeArtifacts(
        candidate_row_count=candidate_count,
        pair_row_count=pair_count,
        realized_terminal_count=accumulator.terminal_count,
        batch_commit_count=len(commits),
        action_counts=accumulator.action_counts,
        realization_status_counts=accumulator.status_counts,
        projection_rows=accumulator.projection_rows(),
    )


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

    commits = list(_iter_canonical_jsonl(root / _COMMIT_FILE))
    membership = _read_membership(root / _MEMBERSHIP_FILE)
    counts = _mapping(manifest.get("counts"), "realized counts")
    if set(counts) != _COUNT_FIELDS or any(
        _non_negative_int(counts.get(field), f"realized {field}") != counts.get(field)
        for field in _COUNT_FIELDS
    ):
        raise ValueError("realized source count fields are not exact")
    _validate_upstream_accounting(
        upstream_accounting,
        logical_judgments=_non_negative_int(counts.get("pairs"), "realized pairs"),
        expected_formal=expected_upstream_formal,
    )
    streamed = _validate_streamed_rows(
        root=root,
        manifest=manifest,
        upstream=upstream,
        membership=membership,
        commits=commits,
    )
    if (
        len(membership) != counts.get("users")
        or len(membership) != counts.get("membership_rows")
        or streamed.pair_row_count != counts.get("pairs")
        or streamed.realized_terminal_count != counts.get("realized_terminals")
        or streamed.realized_terminal_count != counts.get("exposures")
        or streamed.batch_commit_count != counts.get("batch_commits")
        or streamed.candidate_row_count != counts.get("candidate_rows")
        or len(streamed.projection_rows) != counts.get("projection_rows")
    ):
        raise ValueError("realized source denominators or terminal identities are crossed")
    if streamed.action_counts != manifest.get("action_counts"):
        raise ValueError("realized source action counts are crossed")
    if streamed.realization_status_counts != manifest.get("realization_status_counts"):
        raise ValueError("realized source status counts are crossed")
    upstream_identity = _non_empty(upstream.get("source_identity"), "upstream source identity")

    projection = _json_object(root / _PROJECTION_JSON, "realized projection")
    projection_identity = projection.pop("projection_identity", None)
    if (
        projection.get("schema_version") != FULL_POOL_TWO_STAGE_PROJECTION_SCHEMA
        or projection_identity != _json_sha256(projection)
        or projection.get("rows_sha256") != _json_sha256(projection.get("rows"))
        or projection.get("csv_sha256") != _sha256_file(root / _PROJECTION_CSV)
        or projection.get("total_exposure") != streamed.realized_terminal_count
        or projection.get("action_counts") != streamed.action_counts
    ):
        raise ValueError("realized projection closure is crossed")
    projection_rows = [
        _mapping(row, "realized projection row")
        for row in _sequence(projection.get("rows"), "realized projection rows")
    ]
    if _projection_csv_bytes(projection_rows) != (root / _PROJECTION_CSV).read_bytes():
        raise ValueError("realized projection CSV differs from its rows")
    if (
        projection_rows != streamed.projection_rows
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


def _projection_csv_bytes(rows: Sequence[Mapping[str, object]]) -> bytes:
    stream = io.StringIO(newline="")
    fieldnames: list[str] = list(_PROJECTION_FIELDS)
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


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


def _iter_canonical_jsonl(path: Path) -> Iterator[dict[str, object]]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"realized JSONL is missing or unsafe: {path.name}")
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.endswith("\n") or not line.strip():
                raise ValueError(
                    f"realized JSONL line is noncanonical: {path.name}:{line_number}"
                )
            try:
                row = _mapping(json.loads(line), f"{path.name}:{line_number}")
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"realized JSONL is malformed: {path.name}:{line_number}"
                ) from exc
            if line != _canonical_json(row) + "\n":
                raise ValueError(
                    f"realized JSONL line bytes are noncanonical: {path.name}:{line_number}"
                )
            yield row


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


def _remove_sqlite_files(path: Path) -> None:
    for candidate in (path, Path(f"{path}-journal"), Path(f"{path}-wal"), Path(f"{path}-shm")):
        candidate.unlink(missing_ok=True)


def _remove_published_output(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        raise ValueError("published realized output became unsafe during failure cleanup")
    shutil.rmtree(path)
    _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_DIRECTORY)
    except (AttributeError, FileNotFoundError, NotADirectoryError, OSError):
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


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
