from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import os
import re
import subprocess
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from . import durable_pair_settlement as settlement_module
from . import full_pool_segmented_automated_recovery as automated_module
from . import full_pool_segmented_continuation as segmented_module
from .full_pool_segmented_automated_recovery import (
    AUTOMATED_RECOVERY_IDENTITY_FILE,
    AUTOMATED_RECOVERY_POLICY_FILE,
    AUTOMATED_RECOVERY_POLICY_LEDGER_FILE,
    AUTOMATED_RECOVERY_STATUS_FILE,
    AutomatedNestedRecoveryRequest,
    AutomatedNestedRecoveryResult,
)

FULL_POOL_SOURCE_V3_SCHEMA = "full-pool-segmented-source-v3"
FULL_POOL_RESULT_CSV = "full-pool-segment-results.csv"
FULL_POOL_RESULT_LINEAGE_MARKDOWN = "full-pool-segment-lineage.md"
FULL_POOL_RESULT_PROJECTION_SCHEMA = "full-pool-segment-result-projection-v1"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{7,40}$")
_MESSAGE_CODES = {"message_1": "M1", "message_2": "M2", "message_3": "M3"}
_SEGMENT_CODES = {"class_1": "S1", "class_2": "S2", "class_3": "S3"}
_RESULT_FIELDS = (
    "Run",
    "Message",
    "Segment",
    "Total Likes",
    "Total Comments",
    "Total Shares",
    "Exposure",
)
_PRODUCTION_SEGMENT_DENOMINATORS = {"class_1": 15_616, "class_2": 15_070, "class_3": 5_714}
_SOURCE_V3_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "counts",
        "logical_count",
        "physical_attempt_count",
        "cutoff_manifest_sha256",
        "continuation_identity_hash",
        "prefix_identity_hash",
        "max_concurrency",
        "concurrency_qualification_artifact_sha256",
        "accounting",
        "complete_status",
        "production_deploy_eligible",
        "nested_recovery_lineage",
        "settlement_v2",
        "automated_recovery_policy",
        "recovery_accounting",
        "artifacts",
    }
)
_SOURCE_V3_COUNT_FIELDS = frozenset(
    {"candidate_rows", "pair_rows", "terminal_rows", "steps"}
)
_SOURCE_V3_RECOVERY_ACCOUNTING_FIELDS = frozenset(
    {
        "schema_version",
        "logical_cap",
        "historical_logical_count",
        "logical_retry_charge",
        "fresh_logical_count",
        "logical_count",
        "physical_cap",
        "historical_physical_attempts",
        "historical_uncertainty_physical_charge",
        "new_uncertainty_physical_charge",
        "retry_physical_attempts",
        "reconciliation_physical_attempts",
        "continuation_physical_attempts",
        "physical_attempt_count",
    }
)
_SOURCE_V3_LINEAGE_FIELDS = frozenset(
    {
        "schema_version",
        "nested_recovery_plan_sha256",
        "nested_recovery_identity_hash",
        "parent_recovery_lineage",
        "imported_durable_terminal_count",
        "ordered_retry_pair_ids",
    }
)
_SOURCE_V3_SETTLEMENT_FIELDS = frozenset(
    {
        "schema_version",
        "journal_sha256",
        "wave_count",
        "dispatched_pair_count",
        "terminal_pair_count",
        "unknown_pair_ids",
        "implementation_failed_pair_ids",
        "reconciliation_journals",
    }
)
_SOURCE_V3_POLICY_FIELDS = frozenset(
    {"policy_sha256", "policy_ledger_sha256", "policy_identity_hash"}
)


@dataclass(frozen=True)
class AutomatedFullPoolSourceFacts:
    """Persisted source-v3 facts reconstructed without caller-supplied Formal claims."""

    source_root: Path
    workspace_root: Path
    source_schema_version: str
    source_identity: str
    source_manifest_sha256: str
    source_hash: str
    contract_sha256: str
    dataset_dir: Path
    membership_path: Path
    membership_sha256: str
    evidence_profile: str
    configuration_profile: str
    provider_transport: str
    adapter_identity: str
    requested_model: str
    qualified_observed_model: str
    prompt_variant_id: str
    prompt_version: str
    prompt_canonical_hash: str
    distinct_users: int
    eligible_pairs: int
    exposures: int
    primary_terminals: int
    committed_batches: int
    candidate_ranking_rows: int
    provider_failed_terminals: int
    logical_judgments: int
    physical_attempts: int
    physical_attempt_cap: int
    provider_responses: int
    successful_decisions: int
    external_request_invocations: int
    observed_model_counts: Mapping[str, int]
    usage_complete_response_count: int
    usage_missing_response_count: int
    usage_malformed_response_count: int
    imported_durable_terminal_count: int
    historical_logical_count: int
    fresh_logical_count: int
    historical_physical_attempts: int
    historical_uncertainty_physical_charge: int
    new_uncertainty_physical_charge: int
    retry_physical_attempts: int
    reconciliation_physical_attempts: int
    continuation_physical_attempts: int
    ordered_retry_pair_ids: tuple[str, ...]
    settlement_identity_hash: str
    settlement_wave_count: int
    settlement_dispatched_pair_count: int
    settlement_terminal_pair_count: int
    settlement_unknown_pair_ids: tuple[str, ...]
    policy_sha256: str
    policy_ledger_sha256: str
    policy_payload: Mapping[str, object]
    nested_recovery_lineage: Mapping[str, object]
    recovery_accounting: Mapping[str, object]
    settlement_v2: Mapping[str, object]
    artifact_hashes: Mapping[str, str]
    implementation_commit: str
    live_api_triggered: bool
    production_deploy_eligible: bool


@dataclass(frozen=True)
class _ClosedAutomatedFullPoolSource:
    """Read-only source-v3 Adapter for the existing Report source Seam."""

    root: Path
    contract: Any
    source_identity: str
    manifest_sha256: str
    manifest: Mapping[str, object]
    aggregates: Mapping[str, object]
    diagnostics: Mapping[str, object]
    batch_paths: tuple[Any, ...]
    facts: AutomatedFullPoolSourceFacts

    def read_batch(self, time_step: int) -> Mapping[str, object]:
        if time_step < 0 or time_step >= len(self.batch_paths):
            raise IndexError("source-v3 batch index is outside the closed source")
        batch = self.batch_paths[time_step]
        if batch.time_step != time_step:
            raise ValueError("source-v3 batch order is crossed")
        return {
            "time_step": time_step,
            "commit": dict(batch.step),
            "rows": {
                "candidate_rows": segmented_module._read_jsonl_range(
                    self.root / "candidate_rows.jsonl", batch.candidate
                ),
                "pair_rows": segmented_module._read_jsonl_range(
                    self.root / "pair_rows.jsonl", batch.pair
                ),
                "terminal_rows": segmented_module._read_jsonl_range(
                    self.root / "terminal_rows.jsonl", batch.terminal
                ),
            },
        }


@dataclass(frozen=True)
class FullPoolResultProjection:
    schema_version: str
    rows: tuple[Mapping[str, int | str], ...]
    rows_sha256: str
    csv_filename: str
    csv_bytes: bytes
    csv_sha256: str
    lineage_filename: str
    lineage_bytes: bytes
    lineage_sha256: str
    html_fragment: str
    segment_denominators: Mapping[str, int]
    total_exposure: int

    @property
    def lineage_markdown(self) -> str:
        return self.lineage_bytes.decode("utf-8")


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _json_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"persisted source-v3 artifact is missing or unsafe: {path.name}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mapping(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be an object")
    return {str(key): item for key, item in value.items()}


def _mapping_rows(value: object, context: str) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{context} must be an array")
    return [_mapping(row, context) for row in value]


def _non_empty(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be a non-empty string")
    return value


def _non_negative_int(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{context} must be a non-negative integer")
    return value


def _string_list(value: object, context: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{context} must be an array")
    values = [_non_empty(item, context) for item in value]
    if len(values) != len(set(values)):
        raise ValueError(f"{context} contains duplicates")
    return values


def _read_json(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"persisted JSON is missing or unsafe: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"persisted JSON is malformed: {path.name}") from exc
    return _mapping(value, path.name)


def _read_jsonl_by_pair(path: Path) -> dict[str, dict[str, object]]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"persisted JSONL is missing or unsafe: {path.name}")
    rows: dict[str, dict[str, object]] = {}
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise ValueError(f"{path.name} contains a blank row at line {line_number}")
            try:
                row = _mapping(json.loads(line), f"{path.name} line {line_number}")
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path.name} contains malformed JSON") from exc
            pair_id = _non_empty(row.get("pair_id"), f"{path.name} pair_id")
            if pair_id in rows:
                raise ValueError(f"{path.name} duplicates pair_id")
            rows[pair_id] = row
    return rows


def _artifact_inventory(source: Path, manifest: Mapping[str, object]) -> dict[str, str]:
    refs = _mapping_rows(manifest.get("artifacts"), "source-v3 artifacts")
    hashes: dict[str, str] = {}
    for ref in refs:
        if set(ref) not in (
            {"relative_path", "sha256", "bytes"},
            {"relative_path", "sha256", "byte_length"},
        ):
            raise ValueError("source-v3 artifact reference fields are not exact")
        relative = _non_empty(ref.get("relative_path"), "source-v3 artifact path")
        relative_path = Path(relative)
        if (
            relative_path.is_absolute()
            or ".." in relative_path.parts
            or relative_path.as_posix() != relative
            or relative in hashes
        ):
            raise ValueError("source-v3 artifact path is unsafe or duplicated")
        path = source / relative
        byte_field = "bytes" if "bytes" in ref else "byte_length"
        if (
            path.is_symlink()
            or not path.is_file()
            or ref.get(byte_field) != path.stat().st_size
            or ref.get("sha256") != _sha256_file(path)
        ):
            raise ValueError("source-v3 artifact hash or byte length is crossed")
        hashes[relative] = cast(str, ref["sha256"])
    actual = {
        path.relative_to(source).as_posix()
        for path in source.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    if actual != set(hashes) | {"manifest.json"}:
        raise ValueError("source-v3 artifact inventory is missing, extra, or unsafe")
    for path in source.rglob("*"):
        if path.is_symlink() or (not path.is_dir() and not path.is_file()):
            raise ValueError("source-v3 artifact inventory contains an unsafe entry")
    return dict(sorted(hashes.items()))


def _original_nested_plan(copied_plan: Path) -> tuple[Path, dict[str, object]]:
    copied = _read_json(copied_plan)
    payload = _mapping(copied.get("payload"), "copied nested recovery plan payload")
    identity = _mapping(payload.get("recovery_identity"), "nested recovery identity")
    original = Path(_non_empty(identity.get("recovery_root"), "nested recovery root")) / copied_plan.name
    if original.is_symlink() or not original.is_file() or original.read_bytes() != copied_plan.read_bytes():
        raise ValueError("source-v3 nested recovery plan copy differs from its persisted origin")
    return original, payload


def _git_blob_sha256(repo_root: Path, commit: str, relative_path: str) -> str:
    try:
        payload = subprocess.run(
            ["git", "-C", str(repo_root), "show", f"{commit}:{relative_path}"],
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("source-v3 implementation commit or module blob is unavailable") from exc
    return hashlib.sha256(payload).hexdigest()


def _validate_persisted_implementation(
    implementation: Mapping[str, object],
) -> str:
    if set(implementation) != {
        "repository_commit",
        "automated_recovery_module_sha256",
        "durable_pair_settlement_module_sha256",
    }:
        raise ValueError("source-v3 implementation fields are not exact")
    commit = _non_empty(implementation.get("repository_commit"), "implementation commit")
    if _COMMIT.fullmatch(commit) is None:
        raise ValueError("source-v3 implementation commit is invalid")
    repo_root = Path(__file__).resolve().parents[2]
    current_head = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    current = {
        "automated_recovery_module_sha256": _sha256_file(
            Path(automated_module.__file__).resolve()
        ),
        "durable_pair_settlement_module_sha256": _sha256_file(
            Path(settlement_module.__file__).resolve()
        ),
    }
    if current_head == commit and all(
        implementation.get(key) == value for key, value in current.items()
    ):
        return commit
    expected = {
        "automated_recovery_module_sha256": _git_blob_sha256(
            repo_root,
            commit,
            "src/llm_abm_sim/full_pool_segmented_automated_recovery.py",
        ),
        "durable_pair_settlement_module_sha256": _git_blob_sha256(
            repo_root,
            commit,
            "src/llm_abm_sim/durable_pair_settlement.py",
        ),
    }
    if any(implementation.get(key) != value for key, value in expected.items()):
        raise ValueError("source-v3 implementation module bytes differ from the bound commit")
    return commit


def _persisted_automated_closure(
    source: Path,
    manifest: Mapping[str, object],
) -> tuple[
    AutomatedNestedRecoveryResult,
    Any,
    Mapping[str, object],
    Mapping[str, object],
    str,
]:
    copied_plan = source / "nested-recovery-plan.json"
    original_plan, _copied_payload = _original_nested_plan(copied_plan)
    lineage = _mapping(manifest.get("nested_recovery_lineage"), "source-v3 nested lineage")
    nested_plan_sha256 = _non_empty(
        lineage.get("nested_recovery_plan_sha256"), "source-v3 nested plan hash"
    )
    if (
        _SHA256.fullmatch(nested_plan_sha256) is None
        or _sha256_file(copied_plan) != nested_plan_sha256
        or _sha256_file(original_plan) != nested_plan_sha256
    ):
        raise ValueError("source-v3 nested recovery plan hash is crossed")

    workspace = source.parent
    identity = _read_json(workspace / AUTOMATED_RECOVERY_IDENTITY_FILE)
    recovery_id = _non_empty(identity.get("recovery_id"), "automated recovery id")
    request = AutomatedNestedRecoveryRequest(
        nested_recovery_plan_path=original_plan,
        nested_recovery_plan_sha256=nested_plan_sha256,
        recovery_id=recovery_id,
        recovery_workspace=workspace,
    )
    inputs = automated_module._validated_automated_inputs(request)

    copied_policy = _read_json(source / "automated-recovery-policy.json")
    if set(copied_policy) != {"schema_version", "payload", "payload_sha256"}:
        raise ValueError("source-v3 copied policy envelope is not exact")
    policy_payload = _mapping(copied_policy.get("payload"), "source-v3 policy payload")
    if copied_policy.get("payload_sha256") != _json_sha256(policy_payload):
        raise ValueError("source-v3 policy payload hash is crossed")
    implementation = _mapping(policy_payload.get("implementation"), "source-v3 implementation")
    implementation_commit = _validate_persisted_implementation(implementation)

    current_documents = automated_module._automated_documents(request, inputs)
    identity_body = {
        key: value for key, value in current_documents.identity.items() if key != "identity_hash"
    }
    identity_body["implementation"] = dict(implementation)
    expected_identity = {**identity_body, "identity_hash": _json_sha256(identity_body)}
    expected_policy = dict(current_documents.policy)
    expected_policy["implementation"] = dict(implementation)
    expected_policy["recovery_identity_hash"] = expected_identity["identity_hash"]
    if identity != expected_identity or policy_payload != expected_policy:
        raise ValueError("source-v3 persisted identity or automated policy is crossed")

    source_policy = _mapping(manifest.get("automated_recovery_policy"), "source-v3 policy refs")
    if (
        set(source_policy) != _SOURCE_V3_POLICY_FIELDS
        or source_policy.get("policy_identity_hash") != expected_identity["identity_hash"]
        or source_policy.get("policy_sha256") != _sha256_file(source / "automated-recovery-policy.json")
        or source_policy.get("policy_ledger_sha256")
        != _sha256_file(source / "automated-recovery-policy-ledger.jsonl")
        or (workspace / AUTOMATED_RECOVERY_POLICY_FILE).read_bytes()
        != (source / "automated-recovery-policy.json").read_bytes()
        or (workspace / AUTOMATED_RECOVERY_POLICY_LEDGER_FILE).read_bytes()
        != (source / "automated-recovery-policy-ledger.jsonl").read_bytes()
    ):
        raise ValueError("source-v3 copied automated policy lineage is crossed")

    status_path = workspace / AUTOMATED_RECOVERY_STATUS_FILE
    if status_path.is_symlink() or not status_path.is_file():
        raise ValueError("complete source-v3 requires one persisted terminal status")
    documents = automated_module._AutomatedDocuments(
        identity=dict(expected_identity),
        policy=dict(expected_policy),
    )
    result = automated_module._load_existing_status(request, inputs, documents)
    if (
        result is None
        or result.status != "complete"
        or result.source_root != source
        or result.source_manifest_sha256 != _sha256_file(source / "manifest.json")
    ):
        raise ValueError("source-v3 terminal status does not close the persisted source")
    return result, inputs, policy_payload, expected_identity, implementation_commit


def _terminal_evidence_map(inputs: Any) -> dict[str, Mapping[str, object]]:
    terminals: dict[str, Mapping[str, object]] = {}
    for chunk in inputs.historical_chunks:
        for row in chunk.terminal_rows:
            pair_id = _non_empty(row.get("pair_id"), "imported terminal pair_id")
            if pair_id in terminals:
                raise ValueError("imported source-v3 terminal evidence is duplicated")
            terminals[pair_id] = row
    for payload in inputs.active_terminal_payloads:
        pair_id = _non_empty(payload.get("pair_id"), "active terminal pair_id")
        terminal = _mapping(payload.get("terminal_row"), "active terminal row")
        if pair_id in terminals or terminal.get("pair_id") != pair_id:
            raise ValueError("active source-v3 terminal evidence is crossed")
        terminals[pair_id] = terminal
    return terminals


def _validate_settlement_terminal_mapping(
    source: Path,
    manifest: Mapping[str, object],
    *,
    inputs: Any,
    source_terminals: Mapping[str, Mapping[str, object]],
    ordered_pair_ids: Sequence[str],
    identity_hash: str,
) -> tuple[Any, dict[str, int]]:
    settlement = _mapping(manifest.get("settlement_v2"), "source-v3 settlement")
    if (
        set(settlement) != _SOURCE_V3_SETTLEMENT_FIELDS
        or settlement.get("schema_version") != settlement_module.DURABLE_PAIR_SETTLEMENT_SCHEMA
        or settlement.get("journal_sha256")
        != _sha256_file(source / "durable-pair-settlement-v2.jsonl")
        or settlement.get("implementation_failed_pair_ids") != []
    ):
        raise ValueError("source-v3 settlement manifest is crossed")
    main = settlement_module._replay_journal(
        source / "durable-pair-settlement-v2.jsonl",
        expected_identity_hash=identity_hash,
        expected_maximum_attempts=inputs.parent_inputs.prefix.maximum_attempts_per_dispatch,
        allow_inflight=False,
    )
    expected_dispatched = (
        *inputs.unresolved_pair_ids,
        *ordered_pair_ids[inputs.historical_logical_count :],
    )
    if (
        main.dispatched_pair_ids != expected_dispatched
        or len(main.waves) != settlement.get("wave_count")
        or len(main.dispatched_pair_ids) != settlement.get("dispatched_pair_count")
        or len(main.terminal_results) != settlement.get("terminal_pair_count")
        or list(main.unknown_pair_ids) != settlement.get("unknown_pair_ids")
        or main.implementation_failed_pair_ids
    ):
        raise ValueError("source-v3 settlement dispatch, outcome, or wave accounting is crossed")

    settled_terminals: dict[str, Mapping[str, object]] = {
        pair_id: terminal.terminal_row for pair_id, terminal in main.terminal_results.items()
    }
    reconciliation_rows = _mapping_rows(
        settlement.get("reconciliation_journals"), "source-v3 reconciliation journals"
    )
    reconciliation_ids: list[str] = []
    reconciliation_actual = 0
    for row in reconciliation_rows:
        if set(row) != {
            "pair_id",
            "reconciliation_identity_hash",
            "relative_path",
            "sha256",
            "physical_attempt_charge",
        }:
            raise ValueError("source-v3 reconciliation journal fields are not exact")
        pair_id = _non_empty(row.get("pair_id"), "reconciliation pair_id")
        relative = Path(_non_empty(row.get("relative_path"), "reconciliation path"))
        identity = _non_empty(
            row.get("reconciliation_identity_hash"), "reconciliation identity"
        )
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("source-v3 reconciliation journal path is unsafe")
        path = source / relative
        if row.get("sha256") != _sha256_file(path):
            raise ValueError("source-v3 reconciliation journal hash is crossed")
        replay = settlement_module._replay_journal(
            path,
            expected_identity_hash=identity,
            expected_maximum_attempts=inputs.parent_inputs.prefix.maximum_attempts_per_dispatch,
            allow_inflight=False,
        )
        if (
            replay.dispatched_pair_ids != (pair_id,)
            or tuple(replay.terminal_results) != (pair_id,)
            or replay.unknown_pair_ids
            or replay.implementation_failed_pair_ids
            or replay.physical_attempt_charge != row.get("physical_attempt_charge")
        ):
            raise ValueError("source-v3 reconciliation settlement is not one exact terminal")
        settled_terminals[pair_id] = replay.terminal_results[pair_id].terminal_row
        reconciliation_ids.append(pair_id)
        reconciliation_actual += replay.actual_physical_attempts
    if tuple(reconciliation_ids) != main.unknown_pair_ids:
        raise ValueError("source-v3 unknown pairs do not close through reconciliation journals")
    if set(settled_terminals) != set(expected_dispatched):
        raise ValueError("source-v3 settlement terminals do not cover every retried or fresh pair")

    imported = _terminal_evidence_map(inputs)
    if tuple(imported) != tuple(ordered_pair_ids[: inputs.imported_durable_terminal_count]):
        raise ValueError("source-v3 imported terminals are not the persisted canonical prefix")
    if set(imported).intersection(settled_terminals):
        raise ValueError("source-v3 imported and newly settled terminal identities overlap")
    expected_terminals = {**imported, **settled_terminals}
    if set(expected_terminals) != set(source_terminals):
        raise ValueError("source-v3 terminal mapping has missing or extra pairs")
    projection_only_fields = {"execution_segment", "reconciliation_retry"}
    for pair_id, expected in expected_terminals.items():
        expected_row = {
            key: value for key, value in expected.items() if key not in projection_only_fields
        }
        source_row = {
            key: value
            for key, value in source_terminals[pair_id].items()
            if key not in projection_only_fields
        }
        if expected_row != source_row:
            raise ValueError("source-v3 terminal row differs from persisted settlement evidence")
    return main, {"reconciliation_actual": reconciliation_actual}


def _read_membership(path: Path, expected_user_ids: set[str]) -> tuple[dict[str, str], str]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("source-v3 frozen latent membership file is missing or unsafe")
    membership: dict[str, str] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or not {"user_id", "latent_class"}.issubset(reader.fieldnames):
            raise ValueError("source-v3 latent membership columns are incomplete")
        for row in reader:
            user_id = row.get("user_id", "")
            latent_class = row.get("latent_class", "")
            if (
                not user_id
                or user_id in membership
                or latent_class not in _SEGMENT_CODES
            ):
                raise ValueError("source-v3 latent membership row is invalid or duplicated")
            membership[user_id] = latent_class
    if set(membership) != expected_user_ids:
        raise ValueError("source-v3 latent membership has missing or extra users")
    return membership, _sha256_file(path)


def _read_closed_automated_full_pool_source(
    source_root: str | Path,
    *,
    manifest_sha256: str,
) -> _ClosedAutomatedFullPoolSource:
    """Close one explicit source-v3 solely from persisted artifacts and their hashes."""
    source = Path(source_root).expanduser()
    if ".." in source.parts or _SHA256.fullmatch(manifest_sha256) is None:
        raise ValueError("source-v3 path or explicit manifest hash is invalid")
    absolute = Path(os.path.abspath(source))
    resolved = source.resolve(strict=True)
    if absolute != resolved or source.is_symlink() or not resolved.is_dir():
        raise ValueError("source-v3 must be one explicit real directory")
    manifest_path = resolved / "manifest.json"
    if _sha256_file(manifest_path) != manifest_sha256:
        raise ValueError("source-v3 manifest differs from the explicit hash")
    manifest = _read_json(manifest_path)
    counts = _mapping(manifest.get("counts"), "source-v3 counts")
    lineage = _mapping(manifest.get("nested_recovery_lineage"), "source-v3 lineage")
    recovery_accounting = _mapping(
        manifest.get("recovery_accounting"), "source-v3 recovery accounting"
    )
    if (
        set(manifest) != _SOURCE_V3_MANIFEST_FIELDS
        or manifest.get("schema_version") != FULL_POOL_SOURCE_V3_SCHEMA
        or set(counts) != _SOURCE_V3_COUNT_FIELDS
        or set(lineage) != _SOURCE_V3_LINEAGE_FIELDS
        or lineage.get("schema_version")
        != "full-pool-segmented-nested-recovery-lineage-v3"
        or set(recovery_accounting) != _SOURCE_V3_RECOVERY_ACCOUNTING_FIELDS
        or recovery_accounting.get("schema_version")
        != "full-pool-segmented-automated-recovery-accounting-v3"
        or manifest.get("production_deploy_eligible") is not False
    ):
        raise ValueError("source-v3 manifest fields, schema, or lifecycle are not exact")
    artifact_hashes = _artifact_inventory(resolved, manifest)
    membership_name = automated_module.SOURCE_V3_MEMBERSHIP_FILE
    if membership_name not in artifact_hashes:
        raise ValueError("source-v3 manifest omits frozen latent membership")
    result, inputs, policy_payload, persisted_identity, implementation_commit = (
        _persisted_automated_closure(resolved, manifest)
    )

    config = inputs.parent_inputs.config
    message_ids = tuple(message.message_id for message in config.messages)
    message_titles = {message.message_id: message.title for message in config.messages}
    if message_ids != tuple(_MESSAGE_CODES):
        raise ValueError("source-v3 message topology is crossed")
    horizon = config.horizon
    sample_size = config.sample_size
    capacity = config.delivery_capacity
    final_capacity = sample_size - capacity * (horizon - 1)
    expected_pairs = sample_size * len(message_ids)
    expected_candidates = len(message_ids) * (
        horizon * sample_size - capacity * horizon * (horizon - 1) // 2
    )
    prompt_version = inputs.parent_inputs.prefix.prompt_version

    candidate_scan = segmented_module._scan_segmented_candidates(
        resolved / "candidate_rows.jsonl",
        message_ids=message_ids,
        horizon=horizon,
        sample_size=sample_size,
        capacity=capacity,
        allowed_selection_reasons=frozenset(
            {"seed_union", "personalized_topup", "personalized_top20"}
        ),
    )
    pair_scan = segmented_module._scan_segmented_pairs_and_terminals(
        resolved / "pair_rows.jsonl",
        resolved / "terminal_rows.jsonl",
        message_ids=message_ids,
        horizon=horizon,
        capacity=capacity,
        final_capacity=final_capacity,
        maximum_attempts=inputs.parent_inputs.prefix.maximum_attempts_per_dispatch,
        prompt_version=prompt_version,
        selected_rows=candidate_scan.selected_rows,
        allow_provider_failed_empty_decision=True,
    )
    step_rows = segmented_module._scan_segmented_steps(
        resolved / "steps.jsonl",
        horizon=horizon,
        message_ids=message_ids,
        message_titles=message_titles,
        candidate_summary=candidate_scan.summary_by_batch_message,
        pair_scan=pair_scan,
    )
    observed_counts = {
        "candidate_rows": candidate_scan.row_count,
        "pair_rows": pair_scan.pair_count,
        "terminal_rows": pair_scan.terminal_count,
        "steps": len(step_rows),
    }
    expected_counts = {
        "candidate_rows": expected_candidates,
        "pair_rows": expected_pairs,
        "terminal_rows": expected_pairs,
        "steps": horizon,
    }
    if (
        counts != expected_counts
        or observed_counts != expected_counts
        or manifest.get("logical_count") != expected_pairs
        or result.logical_count != expected_pairs
        or len(pair_scan.distinct_users) != sample_size
        or pair_scan.coverage
        != {user_id: len(message_ids) for user_id in pair_scan.distinct_users}
    ):
        raise ValueError("source-v3 36,400/109,200/30 topology or fixture denominator is incomplete")

    source_terminals = _read_jsonl_by_pair(resolved / "terminal_rows.jsonl")
    main_settlement, settlement_totals = _validate_settlement_terminal_mapping(
        resolved,
        manifest,
        inputs=inputs,
        source_terminals=source_terminals,
        ordered_pair_ids=pair_scan.ordered_pair_ids,
        identity_hash=_non_empty(persisted_identity.get("identity_hash"), "source-v3 identity"),
    )
    settlement_document = _mapping(manifest.get("settlement_v2"), "source-v3 settlement")

    accounting = pair_scan.accounting
    terminal_invocations = _non_negative_int(accounting.get("invocations"), "terminal invocations")
    physical = _non_negative_int(manifest.get("physical_attempt_count"), "source-v3 physical attempts")
    historical_physical = _non_negative_int(
        recovery_accounting.get("historical_physical_attempts"), "historical physical attempts"
    )
    historical_uncertainty = _non_negative_int(
        recovery_accounting.get("historical_uncertainty_physical_charge"),
        "historical uncertainty charge",
    )
    new_uncertainty = _non_negative_int(
        recovery_accounting.get("new_uncertainty_physical_charge"),
        "new uncertainty charge",
    )
    retry_physical = _non_negative_int(
        recovery_accounting.get("retry_physical_attempts"), "retry physical attempts"
    )
    reconciliation_physical = _non_negative_int(
        recovery_accounting.get("reconciliation_physical_attempts"),
        "reconciliation physical attempts",
    )
    continuation_physical = _non_negative_int(
        recovery_accounting.get("continuation_physical_attempts"),
        "continuation physical attempts",
    )
    if (
        recovery_accounting.get("logical_cap") != expected_pairs
        or recovery_accounting.get("logical_count") != expected_pairs
        or recovery_accounting.get("logical_retry_charge") != 0
        or recovery_accounting.get("historical_logical_count")
        != inputs.historical_logical_count
        or recovery_accounting.get("fresh_logical_count")
        != expected_pairs - inputs.historical_logical_count
        or recovery_accounting.get("physical_cap")
        != segmented_module.FULL_POOL_SEGMENTED_PHYSICAL_CAP
        or historical_physical != inputs.historical_physical_attempts
        or historical_uncertainty != inputs.uncertainty_physical_charge
        or retry_physical + continuation_physical != main_settlement.actual_physical_attempts
        or reconciliation_physical != settlement_totals["reconciliation_actual"]
        or new_uncertainty != main_settlement.uncertain_physical_attempts
        or physical
        != historical_physical
        + historical_uncertainty
        + new_uncertainty
        + retry_physical
        + reconciliation_physical
        + continuation_physical
        or recovery_accounting.get("physical_attempt_count") != physical
        or physical > segmented_module.FULL_POOL_SEGMENTED_PHYSICAL_CAP
        or terminal_invocations > physical
    ):
        raise ValueError("source-v3 logical, physical, uncertainty, or settlement accounting is crossed")

    observed_models = {
        str(key): _non_negative_int(value, "source-v3 observed model count")
        for key, value in _mapping(
            accounting.get("observed_model_counts"), "source-v3 observed models"
        ).items()
    }
    formal_lineage = segmented_module._read_segmented_formal_lineage(
        run_identity=inputs.parent_inputs.prefix.run_identity,
        formal_identity=inputs.parent_inputs.prefix.formal_identity,
    )
    provider_by_variant = _mapping(
        inputs.parent_inputs.prefix.run_identity.get("provider_contract"),
        "source-v3 provider contract",
    )
    provider = _mapping(provider_by_variant.get("primary"), "source-v3 Primary provider")
    if formal_lineage is not None:
        formal_execution = formal_lineage.contract.formal_execution
        if formal_execution is None:
            raise ValueError("source-v3 Formal lineage omits execution evidence")
        formal_terminal_evidence = (
            formal_lineage.contract.profile == "production"
            and formal_execution.evidence_profile == "formal_live"
            and observed_models == {formal_execution.required_observed_model: expected_pairs}
            and accounting.get("usage_complete_response_count") == expected_pairs
            and accounting.get("usage_missing_response_count") == 0
            and accounting.get("usage_malformed_response_count") == 0
        )
        configuration_profile = "production" if formal_terminal_evidence else "validation"
        evidence_profile = (
            formal_execution.evidence_profile
            if formal_terminal_evidence
            else "validation_mixed_provider_evidence"
        )
        provider_transport = formal_execution.transport
        adapter_identity = formal_execution.adapter_identity
        requested_model = formal_execution.requested_model
        qualified_model = formal_execution.required_observed_model
        contract_sha256 = formal_lineage.contract_sha256
        prompt_variant_id = formal_lineage.prompt_variant_id
        prompt_version = formal_lineage.prompt_version
        prompt_canonical_hash = formal_lineage.prompt_canonical_hash
        live_api_triggered = formal_terminal_evidence
    else:
        configuration_profile = "validation"
        evidence_profile = "deterministic_validation_fixture"
        provider_transport = "deterministic"
        adapter_identity = _non_empty(provider.get("adapter"), "source-v3 adapter")
        requested_model = _non_empty(provider.get("model"), "source-v3 model")
        qualified_model = requested_model
        contract_sha256 = _non_empty(
            inputs.parent_inputs.prefix.formal_identity.get("contract_sha256"),
            "source-v3 contract hash",
        )
        primary_prompt = _mapping(
            inputs.parent_inputs.prefix.prompt_contract, "source-v3 prompt contract"
        )
        prompt_variant_id = _non_empty(primary_prompt.get("variant_id"), "source-v3 prompt variant")
        prompt_canonical_hash = _non_empty(
            primary_prompt.get("canonical_hash"), "source-v3 prompt hash"
        )
        live_api_triggered = False
    if _SHA256.fullmatch(contract_sha256) is None:
        raise ValueError("source-v3 contract hash is invalid")

    membership_path = resolved / membership_name
    _membership, membership_sha256 = _read_membership(
        membership_path,
        set(pair_scan.distinct_users),
    )
    source_hash = _json_sha256(dict(sorted(artifact_hashes.items())))
    external_requests = (
        physical - historical_uncertainty - new_uncertainty
        if live_api_triggered
        else 0
    )
    source_identity = _non_empty(
        persisted_identity.get("identity_hash"), "source-v3 identity hash"
    )
    facts = AutomatedFullPoolSourceFacts(
        source_root=resolved,
        workspace_root=resolved.parent,
        source_schema_version=FULL_POOL_SOURCE_V3_SCHEMA,
        source_identity=source_identity,
        source_manifest_sha256=manifest_sha256,
        source_hash=source_hash,
        contract_sha256=contract_sha256,
        dataset_dir=Path(config.dataset_dir).resolve(strict=True),
        membership_path=membership_path.resolve(strict=True),
        membership_sha256=membership_sha256,
        evidence_profile=evidence_profile,
        configuration_profile=configuration_profile,
        provider_transport=provider_transport,
        adapter_identity=adapter_identity,
        requested_model=requested_model,
        qualified_observed_model=qualified_model,
        prompt_variant_id=prompt_variant_id,
        prompt_version=prompt_version,
        prompt_canonical_hash=prompt_canonical_hash,
        distinct_users=sample_size,
        eligible_pairs=expected_pairs,
        exposures=expected_pairs,
        primary_terminals=expected_pairs,
        committed_batches=horizon,
        candidate_ranking_rows=expected_candidates,
        provider_failed_terminals=pair_scan.provider_failed,
        logical_judgments=expected_pairs,
        physical_attempts=physical,
        physical_attempt_cap=segmented_module.FULL_POOL_SEGMENTED_PHYSICAL_CAP,
        provider_responses=_non_negative_int(accounting.get("responses"), "source-v3 responses"),
        successful_decisions=_non_negative_int(
            accounting.get("successful_decisions"), "source-v3 successful decisions"
        ),
        external_request_invocations=external_requests,
        observed_model_counts=observed_models,
        usage_complete_response_count=_non_negative_int(
            accounting.get("usage_complete_response_count"), "source-v3 complete usage"
        ),
        usage_missing_response_count=_non_negative_int(
            accounting.get("usage_missing_response_count"), "source-v3 missing usage"
        ),
        usage_malformed_response_count=_non_negative_int(
            accounting.get("usage_malformed_response_count"), "source-v3 malformed usage"
        ),
        imported_durable_terminal_count=inputs.imported_durable_terminal_count,
        historical_logical_count=inputs.historical_logical_count,
        fresh_logical_count=expected_pairs - inputs.historical_logical_count,
        historical_physical_attempts=historical_physical,
        historical_uncertainty_physical_charge=historical_uncertainty,
        new_uncertainty_physical_charge=new_uncertainty,
        retry_physical_attempts=retry_physical,
        reconciliation_physical_attempts=reconciliation_physical,
        continuation_physical_attempts=continuation_physical,
        ordered_retry_pair_ids=inputs.unresolved_pair_ids,
        settlement_identity_hash=source_identity,
        settlement_wave_count=len(main_settlement.waves),
        settlement_dispatched_pair_count=len(main_settlement.dispatched_pair_ids),
        settlement_terminal_pair_count=len(main_settlement.terminal_results),
        settlement_unknown_pair_ids=main_settlement.unknown_pair_ids,
        policy_sha256=_non_empty(
            _mapping(manifest.get("automated_recovery_policy"), "source-v3 policy").get(
                "policy_sha256"
            ),
            "source-v3 policy hash",
        ),
        policy_ledger_sha256=_non_empty(
            _mapping(manifest.get("automated_recovery_policy"), "source-v3 policy").get(
                "policy_ledger_sha256"
            ),
            "source-v3 policy ledger hash",
        ),
        policy_payload=dict(policy_payload),
        nested_recovery_lineage=dict(lineage),
        recovery_accounting=dict(recovery_accounting),
        settlement_v2=dict(settlement_document),
        artifact_hashes=artifact_hashes,
        implementation_commit=implementation_commit,
        live_api_triggered=live_api_triggered,
        production_deploy_eligible=False,
    )
    facade_counts = {
        "candidate_ranking_rows": expected_candidates,
        "committed_batches": horizon,
        "distinct_users": sample_size,
        "eligible_pairs": expected_pairs,
        "exposures": expected_pairs,
        "primary_terminals": expected_pairs,
        "provider_failed_terminals": pair_scan.provider_failed,
        "below_delivery_capacity_pairs": expected_candidates - expected_pairs,
    }
    facade_accounting = {
        "logical_judgments": expected_pairs,
        "physical_attempts": physical,
        "provider_responses": facts.provider_responses,
        "successful_decisions": facts.successful_decisions,
        "external_request_invocations": external_requests,
        "observed_model_counts": observed_models,
        "observed_model_missing_response_count": accounting[
            "observed_model_missing_response_count"
        ],
        "observed_model_malformed_response_count": accounting[
            "observed_model_malformed_response_count"
        ],
        "usage_complete_attempts": accounting["usage_complete_attempts"],
        "usage_incomplete_attempts": accounting["usage_incomplete_attempts"],
        "usage_complete_response_count": facts.usage_complete_response_count,
        "usage_missing_response_count": facts.usage_missing_response_count,
        "usage_malformed_response_count": facts.usage_malformed_response_count,
        "input_usage": accounting["input_usage"],
        "output_usage": accounting["output_usage"],
        "total_usage": accounting["total_usage"],
        "cached_input_usage": accounting["cached_input_usage"],
        "subscription_billed_cost_usd": 0.0,
    }
    nested_execution = {
        "schema_version": "full-pool-segmented-nested-execution-view-v3",
        "original_run_identity_hash": inputs.parent_inputs.prefix.run_identity.get(
            "identity_hash"
        ),
        "first_recovery_identity_hash": lineage["parent_recovery_lineage"].get(
            "parent_recovery_identity_hash"
        )
        if isinstance(lineage["parent_recovery_lineage"], Mapping)
        else None,
        "second_recovery_identity_hash": lineage["nested_recovery_identity_hash"],
        "automated_policy_identity_hash": source_identity,
        "settlement_schema_version": settlement_document["schema_version"],
        "ordered_retry_pair_ids": list(inputs.unresolved_pair_ids),
        "serial_prefix_terminal_count": pair_scan.serial_count,
        "concurrent_suffix_terminal_count": pair_scan.suffix_count,
        "max_concurrency": manifest["max_concurrency"],
        "unknown_pair_count": len(main_settlement.unknown_pair_ids),
        "reconciliation_retry_count": len(
            _mapping_rows(
                settlement_document.get("reconciliation_journals"),
                "source-v3 reconciliation journals",
            )
        ),
        "total_physical_attempts": physical,
        "cutoff_manifest_sha256": lineage["nested_recovery_plan_sha256"],
        "recovery_accounting": dict(recovery_accounting),
    }
    facade_manifest = {
        "schema_version": FULL_POOL_SOURCE_V3_SCHEMA,
        "source_schema_version": FULL_POOL_SOURCE_V3_SCHEMA,
        "source_identity": source_identity,
        "contract_sha256": contract_sha256,
        "source_hash": source_hash,
        "profile": "production" if live_api_triggered else "deterministic_validation",
        "evidence_profile": evidence_profile,
        "counts": facade_counts,
        "provider_calls": external_requests,
        "physical_provider_attempts": physical,
        "live_api_triggered": live_api_triggered,
        "production_deploy_eligible": False,
        "segmented_execution": nested_execution,
        "nested_recovery": nested_execution,
    }
    aggregates = {
        "schema_version": "full-pool-segmented-aggregates-view-v3",
        "source_identity": source_identity,
        "evidence_profile": evidence_profile,
        "counts": facade_counts,
        "provider_accounting": facade_accounting,
        "production_deploy_eligible": False,
    }
    diagnostics = {
        "schema_version": "full-pool-segmented-diagnostics-view-v3",
        "source_identity": source_identity,
        "schedule": {
            "per_message_capacity": capacity,
            "final_batch_pairs_per_message": final_capacity,
        },
        "nested_recovery": nested_execution,
    }
    execution = segmented_module._SegmentedExecutionView(
        requested_model=requested_model,
        required_observed_model=qualified_model,
        transport=provider_transport,
        adapter_identity=adapter_identity,
        physical_attempt_cap=segmented_module.FULL_POOL_SEGMENTED_PHYSICAL_CAP,
    )
    contract = segmented_module._SegmentedContractView(
        schema_version="full-pool-segmented-contract-view-v3",
        message_ids=cast(tuple[str, str, str], message_ids),
        horizon=horizon,
        eligible_user_count=sample_size,
        per_message_capacity=capacity,
        expected_primary_terminals=expected_pairs,
        expected_final_batch_pairs_per_message=final_capacity,
        formal_execution=execution,
    )
    batch_paths = tuple(
        segmented_module._SegmentedBatchSlice(
            time_step=time_step,
            candidate=candidate_scan.ranges[time_step],
            pair=pair_scan.pair_ranges[time_step],
            terminal=pair_scan.terminal_ranges[time_step],
            step=step_rows[time_step],
        )
        for time_step in range(horizon)
    )
    return _ClosedAutomatedFullPoolSource(
        root=resolved,
        contract=contract,
        source_identity=source_identity,
        manifest_sha256=manifest_sha256,
        manifest=facade_manifest,
        aggregates=aggregates,
        diagnostics=diagnostics,
        batch_paths=batch_paths,
        facts=facts,
    )


def _projection_rows(
    source: _ClosedAutomatedFullPoolSource,
) -> tuple[tuple[dict[str, int | str], ...], dict[str, int]]:
    membership, membership_sha256 = _read_membership(
        source.facts.membership_path,
        {
            _non_empty(row.get("user_id"), "source-v3 terminal user_id")
            for row in _read_jsonl_by_pair(source.root / "terminal_rows.jsonl").values()
        },
    )
    if membership_sha256 != source.facts.membership_sha256:
        raise ValueError("source-v3 latent membership changed after source closure")
    denominators = dict(Counter(membership.values()))
    if source.facts.distinct_users == 36_400 and denominators != _PRODUCTION_SEGMENT_DENOMINATORS:
        raise ValueError("source-v3 production latent segment denominators are crossed")
    counters: dict[tuple[str, str], Counter[str]] = {
        (latent_class, message_id): Counter()
        for latent_class in _SEGMENT_CODES
        for message_id in _MESSAGE_CODES
    }
    for terminal in _read_jsonl_by_pair(source.root / "terminal_rows.jsonl").values():
        user_id = _non_empty(terminal.get("user_id"), "projection user_id")
        message_id = _non_empty(terminal.get("message_id"), "projection message_id")
        if message_id not in _MESSAGE_CODES:
            raise ValueError("source-v3 projection contains an unknown message")
        counter = counters[(membership[user_id], message_id)]
        counter["exposure"] += 1
        if terminal.get("terminal_status") == "succeeded":
            action = terminal.get("action")
            if action in {"like", "comment", "share"}:
                counter[str(action)] += 1
    rows: list[dict[str, int | str]] = []
    for latent_class, segment_code in _SEGMENT_CODES.items():
        for message_id, message_code in _MESSAGE_CODES.items():
            counter = counters[(latent_class, message_id)]
            rows.append(
                {
                    "Run": 1,
                    "Message": message_code,
                    "Segment": segment_code,
                    "Total Likes": counter["like"],
                    "Total Comments": counter["comment"],
                    "Total Shares": counter["share"],
                    "Exposure": counter["exposure"],
                }
            )
    for latent_class, segment_code in _SEGMENT_CODES.items():
        expected = denominators[latent_class]
        if any(
            row["Exposure"] != expected
            for row in rows
            if row["Segment"] == segment_code
        ):
            raise ValueError("source-v3 segment exposure denominator is incomplete")
    if sum(cast(int, row["Exposure"]) for row in rows) != source.facts.exposures:
        raise ValueError("source-v3 nine-cell exposure denominator is crossed")
    return tuple(rows), denominators


def _csv_bytes(rows: Sequence[Mapping[str, int | str]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(_RESULT_FIELDS)
    for row in rows:
        writer.writerow([row[field] for field in _RESULT_FIELDS])
    return output.getvalue().encode("utf-8")


def _html_projection(rows: Sequence[Mapping[str, int | str]]) -> str:
    body = "".join(
        "<tr>"
        + "".join(f"<td>{html.escape(str(row[field]))}</td>" for field in _RESULT_FIELDS)
        + "</tr>"
        for row in rows
    )
    headings = "".join(f"<th>{html.escape(field)}</th>" for field in _RESULT_FIELDS)
    return (
        '<section id="full-pool-segment-results" class="full-pool-section" '
        'data-testid="full-pool-segment-results">'
        "<h2>Full-Pool segment results</h2>"
        "<p>Rows are ordered Segment → Message → Run. Exposure includes ignore; interaction "
        "columns count only succeeded terminal actions.</p>"
        '<div class="full-pool-table-wrap"><table data-testid="full-pool-segment-table">'
        f"<thead><tr>{headings}</tr></thead><tbody>{body}</tbody></table></div>"
        '<ul class="full-pool-download-list">'
        f'<li><a class="full-pool-download-link" href="{FULL_POOL_RESULT_CSV}" download>'
        f"{FULL_POOL_RESULT_CSV}</a></li>"
        f'<li><a class="full-pool-download-link" href="{FULL_POOL_RESULT_LINEAGE_MARKDOWN}" download>'
        f"{FULL_POOL_RESULT_LINEAGE_MARKDOWN}</a></li>"
        "</ul></section>"
    )


def compose_full_pool_result_projection(
    source: _ClosedAutomatedFullPoolSource,
    *,
    historical_artifact_hashes: Mapping[str, str] | None = None,
) -> FullPoolResultProjection:
    """Project one validated source-v3 aggregation into stable HTML, CSV, and Markdown."""
    if not isinstance(source.facts, AutomatedFullPoolSourceFacts):
        raise ValueError("result projection requires typed source-v3 facts")
    rows, denominators = _projection_rows(source)
    rows_document = [dict(row) for row in rows]
    rows_sha256 = _json_sha256(rows_document)
    csv_bytes = _csv_bytes(rows)
    csv_sha256 = hashlib.sha256(csv_bytes).hexdigest()
    historical_hashes = dict(sorted((historical_artifact_hashes or {}).items()))
    historical_identity = _json_sha256(historical_hashes)
    lineage = "\n".join(
        (
            "# Full-Pool segment result lineage and data dictionary",
            "",
            f"- schema: `{FULL_POOL_RESULT_PROJECTION_SCHEMA}`",
            f"- source-v3 manifest SHA-256: `{source.manifest_sha256}`",
            f"- source-v3 identity: `{source.source_identity}`",
            f"- rows SHA-256: `{rows_sha256}`",
            f"- CSV SHA-256: `{csv_sha256}`",
            f"- frozen latent-v1 membership SHA-256: `{source.facts.membership_sha256}`",
            f"- historical artifact inventory identity SHA-256: `{historical_identity}`",
            f"- original / first / second recovery implementation commit: `{source.facts.implementation_commit}`",
            f"- automated policy SHA-256: `{source.facts.policy_sha256}`",
            f"- settlement v2 journal SHA-256: `{source.facts.settlement_v2['journal_sha256']}`",
            "",
            "## Data dictionary",
            "",
            "| Column | Meaning |",
            "|---|---|",
            "| Run | Frozen experiment run identifier; this delivery uses `1`. |",
            "| Message | `M1` / `M2` / `M3`, mapped from the three persisted messages. |",
            "| Segment | `S1` / `S2` / `S3`, joined by `user_id` from frozen latent-v1 membership. |",
            "| Total Likes | Count of `terminal_status=succeeded` and `action=like`. |",
            "| Total Comments | Count of `terminal_status=succeeded` and `action=comment`. |",
            "| Total Shares | Count of `terminal_status=succeeded` and `action=share`. |",
            "| Exposure | Every persisted terminal row, including `ignore`. |",
            "",
            "## Interpretation boundary",
            "",
            "The Full-Pool experiment and the historical 1,000-user sensitivity evidence are separate layers. "
            "Between them, population and model both change; this is not a single-factor comparison or a causal attribution. "
            "Historical bytes, hashes, and denominators remain unchanged and are copied from the approved historical candidate.",
            "",
        )
    ).encode("utf-8")
    return FullPoolResultProjection(
        schema_version=FULL_POOL_RESULT_PROJECTION_SCHEMA,
        rows=tuple(rows_document),
        rows_sha256=rows_sha256,
        csv_filename=FULL_POOL_RESULT_CSV,
        csv_bytes=csv_bytes,
        csv_sha256=csv_sha256,
        lineage_filename=FULL_POOL_RESULT_LINEAGE_MARKDOWN,
        lineage_bytes=lineage,
        lineage_sha256=hashlib.sha256(lineage).hexdigest(),
        html_fragment=_html_projection(rows),
        segment_denominators=dict(denominators),
        total_exposure=sum(cast(int, row["Exposure"]) for row in rows),
    )
