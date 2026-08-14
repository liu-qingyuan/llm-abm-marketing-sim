#!/usr/bin/env python3
"""Run the explicit, zero-Provider Full-Pool Validation trajectory.

This is a slow operational command, not part of the default pytest suite. It only
accepts the deterministic Validation profile and requires an exact opt-in token.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from llm_abm_sim import concurrent_robustness_evidence as evidence_module
from llm_abm_sim import concurrent_robustness_report as report_module
from llm_abm_sim import full_pool_formal_experiment as full_pool_module
from llm_abm_sim.concurrent_robustness_release import (
    ConcurrentRobustnessReleaseError,
    promote_concurrent_robustness_release,
)
from llm_abm_sim.decision import EngageDecision, LLMDecisionAdapter, ProviderDecisionError
from llm_abm_sim.full_pool_formal_experiment import (
    FULL_POOL_AUTHORITATIVE_MESSAGES_SHA256,
    FULL_POOL_CONTRACT_SCHEMA,
    FULL_POOL_PRODUCTION_CANDIDATE_ROWS,
    FULL_POOL_PRODUCTION_CAPACITY,
    FULL_POOL_PRODUCTION_ELIGIBLE_PAIRS,
    FULL_POOL_PRODUCTION_FINAL_BATCH_PAIRS_PER_MESSAGE,
    FULL_POOL_PRODUCTION_HORIZON,
    FULL_POOL_PRODUCTION_USER_COUNT,
    FULL_POOL_PRODUCTION_USER_IDS_SHA256,
    FULL_POOL_VALIDATION_DATASET_IDENTITY,
    FULL_POOL_VALIDATION_TOKEN,
    FullPoolExperimentContract,
    FullPoolFormalExperiment,
    FullPoolRunStatus,
)
from llm_abm_sim.prompt_contracts import (
    APPROVED_EXCLUDED_FIELDS,
    APPROVED_VISIBLE_FIELD_ALLOWLIST,
    CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY,
)
from llm_abm_sim.prompt_field_summary import CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION
from llm_abm_sim.provider_request_contract import OMITTED_SAMPLING_PARAMETERS, STRUCTURED_OUTPUT_SCHEMA_HASH
from llm_abm_sim.schemas import PeerContext, PlatformContext, PostContent, UserProfile

_OPT_IN_TOKEN = "FULL_POOL_ZERO_CALL_VALIDATION"
_MESSAGE_IDS = ("message_1", "message_2", "message_3")
_POSITIVE_ACTIONS = {"like", "comment", "share"}
_COMMIT = re.compile(r"^[0-9a-f]{7,64}$")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the slow 36,400-user deterministic Full-Pool Validation and presentation closure"
    )
    parser.add_argument(
        "--confirm-full-pool-validation",
        required=True,
        metavar="TOKEN",
        help=f"Exact opt-in token: {_OPT_IN_TOKEN}",
    )
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--dataset-dir", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--output-identity", required=True)
    parser.add_argument("--historical-formal-root", required=True, type=Path)
    parser.add_argument("--historical-study-root", required=True, type=Path)
    parser.add_argument("--historical-candidate-dir", required=True, type=Path)
    parser.add_argument("--implementation-commit", required=True)
    parser.add_argument(
        "--continue-closed-source",
        action="store_true",
        help="Continue an interrupted invocation only after its exact source is already closed",
    )
    return parser.parse_args()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_sha256(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected one JSON object: {path}")
    return value


def _csv_bool(value: object, context: str) -> bool:
    if value in (True, "true"):
        return True
    if value in (False, "false"):
        return False
    raise ValueError(f"{context} is not a canonical boolean")


def _require_real_directory(path: Path, *, root: Path | None = None) -> Path:
    absolute = Path(os.path.abspath(path.expanduser()))
    resolved = path.expanduser().resolve(strict=True)
    if absolute != resolved or resolved.is_symlink() or not resolved.is_dir():
        raise ValueError(f"directory must be one explicit real path: {path}")
    if root is not None and resolved != root and not resolved.is_relative_to(root):
        raise ValueError(f"directory must remain under repository root: {path}")
    return resolved


def _new_output_root(path: Path, *, repo_root: Path) -> Path:
    absolute = Path(os.path.abspath(path.expanduser()))
    resolved = path.expanduser().resolve(strict=False)
    if absolute != resolved or ".." in path.parts:
        raise ValueError("output root must be one canonical path")
    if resolved == repo_root or not resolved.is_relative_to(repo_root):
        raise ValueError("output root must be a new directory under repository root")
    if os.path.lexists(resolved):
        raise FileExistsError(f"output root already exists: {resolved}")
    resolved.mkdir(parents=True)
    return resolved


def _existing_output_root(path: Path, *, repo_root: Path) -> Path:
    resolved = _require_real_directory(path, root=repo_root)
    if resolved == repo_root:
        raise ValueError("continued output root cannot be the repository root")
    if (resolved / "validation-audit.json").exists():
        raise FileExistsError("continued output root already contains its final audit")
    return resolved


def _user_set_sha256(dataset_dir: Path) -> tuple[str, int]:
    user_ids: list[str] = []
    with (dataset_dir / "users.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            user_id = str(row.get("user_id", "")).strip()
            if not user_id:
                raise ValueError("dataset users.csv contains a blank user_id")
            user_ids.append(user_id)
    if len(user_ids) != len(set(user_ids)):
        raise ValueError("dataset users.csv contains duplicate user_id values")
    ordered = sorted(user_ids)
    return _canonical_json_sha256(ordered), len(ordered)


class _DeterministicFullPoolAdapter(LLMDecisionAdapter):
    """Hash-based fixture with bounded state and explicit failure terminals."""

    prompt_version = CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION
    external_request_invocations = 0

    def __init__(self) -> None:
        self.request_invocations = 0
        self.safe_metadata = {
            "adapter": "full_pool_ticket_202_validation_fixture",
            "provider": "deterministic",
            "model": "deterministic-full-pool-validation-v1",
            "prompt_version": self.prompt_version,
        }

    def decide(
        self,
        post: PostContent,
        profile: UserProfile,
        peer_context: PeerContext,
        platform_context: PlatformContext | None = None,
        time_step: int = 0,
    ) -> EngageDecision:
        del peer_context, platform_context, time_step
        self.request_invocations += 1
        digest = hashlib.sha256(f"{post.post_id}\0{profile.user_id}".encode()).digest()
        bucket = int.from_bytes(digest[:4], "big") % 1000
        if bucket < 10:
            raise ProviderDecisionError(TimeoutError("deterministic validation failure bucket"))
        if bucket < 170:
            action, probability = "like", 0.88
        elif bucket < 260:
            action, probability = "comment", 0.78
        elif bucket < 330:
            action, probability = "share", 0.82
        else:
            action, probability = "ignore", 0.12
        positive = action != "ignore"
        return EngageDecision(
            engage=positive,
            probability=probability,
            reason=f"deterministic full-pool validation: {action}",
            confidence=0.91,
            action=action,
            decision_source="full_pool_ticket_202_validation_fixture",
            provider_metadata={
                "adapter": "full_pool_ticket_202_validation_fixture",
                "model": "deterministic-full-pool-validation-v1",
            },
        )


class _ReplayTripwireAdapter(LLMDecisionAdapter):
    prompt_version = CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION
    external_request_invocations = 0

    def __init__(self) -> None:
        self.request_invocations = 0

    def decide(
        self,
        post: PostContent,
        profile: UserProfile,
        peer_context: PeerContext,
        platform_context: PlatformContext | None = None,
        time_step: int = 0,
    ) -> EngageDecision:
        del post, profile, peer_context, platform_context, time_step
        self.request_invocations += 1
        raise AssertionError("closed Validation replay must not request a new logical judgment")


def _contract(dataset_dir: Path, output_identity: str) -> FullPoolExperimentContract:
    return FullPoolExperimentContract(
        schema_version=FULL_POOL_CONTRACT_SCHEMA,
        profile="deterministic_validation",
        validation_token=FULL_POOL_VALIDATION_TOKEN,
        dataset_dir=dataset_dir,
        dataset_identity=FULL_POOL_VALIDATION_DATASET_IDENTITY,
        eligible_user_set_identity="full-pool-validation-eligible-users-v1",
        eligible_user_ids_sha256=FULL_POOL_PRODUCTION_USER_IDS_SHA256,
        eligible_user_count=FULL_POOL_PRODUCTION_USER_COUNT,
        message_ids=_MESSAGE_IDS,
        message_snapshot_sha256=FULL_POOL_AUTHORITATIVE_MESSAGES_SHA256,
        horizon=FULL_POOL_PRODUCTION_HORIZON,
        per_message_capacity=FULL_POOL_PRODUCTION_CAPACITY,
        seed_top_k_per_proxy=10,
        primary_only=True,
        expected_eligible_pairs=FULL_POOL_PRODUCTION_ELIGIBLE_PAIRS,
        expected_exposures=FULL_POOL_PRODUCTION_ELIGIBLE_PAIRS,
        expected_primary_terminals=FULL_POOL_PRODUCTION_ELIGIBLE_PAIRS,
        expected_committed_batches=FULL_POOL_PRODUCTION_HORIZON,
        expected_candidate_ranking_rows=FULL_POOL_PRODUCTION_CANDIDATE_ROWS,
        expected_final_batch_pairs_per_message=FULL_POOL_PRODUCTION_FINAL_BATCH_PAIRS_PER_MESSAGE,
        output_identity=output_identity,
    )


def _audit_source(source: Path, manifest_sha256: str) -> dict[str, Any]:
    manifest_path = source / "manifest.json"
    if _sha256_file(manifest_path) != manifest_sha256:
        raise ValueError("persisted manifest differs from the run result")
    manifest = _read_json(manifest_path)
    aggregates = _read_json(source / "aggregates.json")
    diagnostics = _read_json(source / "diagnostics.json")

    candidate_counts: Counter[str] = Counter()
    candidate_batch_counts: Counter[tuple[str, int]] = Counter()
    candidate_hasher = hashlib.sha256()
    candidate_bytes = 0
    with (source / "candidate_rows.jsonl").open("rb") as stream:
        for line_number, line in enumerate(stream, 1):
            candidate_hasher.update(line)
            candidate_bytes += len(line)
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"candidate row {line_number} is not an object")
            message_id = str(row.get("message_id"))
            time_step = int(row.get("time_step", -1))
            candidate_counts[message_id] += 1
            candidate_batch_counts[(message_id, time_step)] += 1

    terminals: dict[str, tuple[str, str, int, str, str]] = {}
    terminal_ids: set[str] = set()
    terminal_counts: Counter[str] = Counter()
    terminal_status_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    terminal_hasher = hashlib.sha256()
    terminal_bytes = 0
    with (source / "terminal_rows.jsonl").open("rb") as stream:
        for line_number, line in enumerate(stream, 1):
            terminal_hasher.update(line)
            terminal_bytes += len(line)
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"terminal row {line_number} is not an object")
            if row.get("decision_variant") != "primary":
                raise ValueError("Validation source contains a Shadow terminal")
            pair_id = str(row.get("pair_id", ""))
            terminal_id = str(row.get("terminal_row_id", ""))
            if not pair_id or not terminal_id or pair_id in terminals or terminal_id in terminal_ids:
                raise ValueError("terminal identities are blank or duplicated")
            message_id = str(row.get("message_id"))
            time_step = int(row.get("time_step", -1))
            status = str(row.get("terminal_status"))
            action = str(row.get("action"))
            reason = str(row.get("reason"))
            user_id = str(row.get("user_id", ""))
            terminals[pair_id] = (status, action, time_step, message_id, user_id)
            terminal_ids.add(terminal_id)
            terminal_counts[message_id] += 1
            terminal_status_counts[status] += 1
            action_counts[action if action else "provider_failed"] += 1
            reason_counts[reason if reason else "provider_failed"] += 1

    pair_ids: set[str] = set()
    pair_counts: Counter[str] = Counter()
    pair_batch_counts: Counter[tuple[str, int]] = Counter()
    coverage: Counter[str] = Counter()
    positive_by_batch: dict[int, set[str]] = defaultdict(set)
    pair_hasher = hashlib.sha256()
    pair_bytes = 0
    with (source / "pair_rows.jsonl").open("rb") as stream:
        for line_number, line in enumerate(stream, 1):
            pair_hasher.update(line)
            pair_bytes += len(line)
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"pair row {line_number} is not an object")
            pair_id = str(row.get("pair_id", ""))
            if not pair_id or pair_id in pair_ids:
                raise ValueError("pair identities are blank or duplicated")
            pair_ids.add(pair_id)
            terminal = terminals.get(pair_id)
            if terminal is None:
                raise ValueError("pair has no Primary terminal")
            status, action, terminal_step, terminal_message, terminal_user = terminal
            message_id = str(row.get("message_id"))
            time_step = int(row.get("time_step", -1))
            user_id = str(row.get("user_id", ""))
            if (terminal_step, terminal_message, terminal_user) != (time_step, message_id, user_id):
                raise ValueError("pair and terminal identities are crossed")
            positive = status == "succeeded" and action in _POSITIVE_ACTIONS
            feedback = _csv_bool(row.get("campaign_feedback_committed"), "campaign feedback")
            if feedback != positive:
                raise ValueError("feedback is not limited to succeeded positive Primary terminals")
            if status == "provider_failed" and feedback:
                raise ValueError("provider_failed terminal propagated feedback")
            if status == "succeeded" and action == "ignore" and feedback:
                raise ValueError("ignore terminal propagated feedback")
            if positive:
                positive_by_batch[time_step].add(user_id)
            pair_counts[message_id] += 1
            pair_batch_counts[(message_id, time_step)] += 1
            coverage[user_id] += 1

    if set(terminals) != pair_ids:
        raise ValueError("terminal and pair identity sets differ")
    expected_per_message_candidates = FULL_POOL_PRODUCTION_CANDIDATE_ROWS // len(_MESSAGE_IDS)
    if candidate_counts != Counter({message_id: expected_per_message_candidates for message_id in _MESSAGE_IDS}):
        raise ValueError("candidate rows do not close per message")
    expected_message_counts = Counter({message_id: FULL_POOL_PRODUCTION_USER_COUNT for message_id in _MESSAGE_IDS})
    if pair_counts != expected_message_counts or terminal_counts != expected_message_counts:
        raise ValueError("pair or terminal rows do not close per message")
    if len(coverage) != FULL_POOL_PRODUCTION_USER_COUNT or Counter(coverage.values()) != Counter({3: 36_400}):
        raise ValueError("per-user three-message coverage does not close")
    for message_id in _MESSAGE_IDS:
        for time_step in range(FULL_POOL_PRODUCTION_HORIZON):
            expected_selected = (
                FULL_POOL_PRODUCTION_CAPACITY
                if time_step < FULL_POOL_PRODUCTION_HORIZON - 1
                else FULL_POOL_PRODUCTION_FINAL_BATCH_PAIRS_PER_MESSAGE
            )
            expected_candidates = FULL_POOL_PRODUCTION_USER_COUNT - time_step * FULL_POOL_PRODUCTION_CAPACITY
            if pair_batch_counts[(message_id, time_step)] != expected_selected:
                raise ValueError("selected pair count differs from the frozen batch schedule")
            if candidate_batch_counts[(message_id, time_step)] != expected_candidates:
                raise ValueError("candidate count differs from the frozen batch schedule")

    cumulative_positive: set[str] = set()
    batches = diagnostics.get("batches")
    if not isinstance(batches, list) or len(batches) != FULL_POOL_PRODUCTION_HORIZON:
        raise ValueError("diagnostics do not contain 30 closed batches")
    for expected_step, row in enumerate(batches):
        if not isinstance(row, dict) or row.get("time_step") != expected_step:
            raise ValueError("diagnostic batches are missing or out of order")
        if row.get("frozen_campaign_engaged_user_ids") != sorted(cumulative_positive):
            raise ValueError("batch ranking context is not frozen at the prior barrier")
        committed = sorted(positive_by_batch[expected_step])
        if row.get("committed_primary_positive_user_ids") != committed:
            raise ValueError("batch feedback differs from succeeded positive terminals")
        cumulative_positive.update(committed)

    expected_counts = {
        "distinct_users": 36_400,
        "eligible_pairs": 109_200,
        "exposures": 109_200,
        "primary_terminals": 109_200,
        "committed_batches": 30,
        "candidate_ranking_rows": 1_691_730,
        "below_delivery_capacity_pairs": 0,
    }
    aggregate_counts = aggregates.get("counts")
    manifest_counts = manifest.get("counts")
    if not isinstance(aggregate_counts, dict) or not isinstance(manifest_counts, dict):
        raise ValueError("persisted aggregate counts are missing")
    if any(aggregate_counts.get(key) != value or manifest_counts.get(key) != value for key, value in expected_counts.items()):
        raise ValueError("persisted source counts differ from independent recomputation")

    expected_high_water = len(_MESSAGE_IDS) * FULL_POOL_PRODUCTION_USER_COUNT + 3 * (
        len(_MESSAGE_IDS) * FULL_POOL_PRODUCTION_CAPACITY
    )
    if diagnostics.get("runtime_resident_row_high_water") != expected_high_water:
        raise ValueError("resident-row high-water is not the deterministic single-batch bound")
    if diagnostics.get("runtime_resident_rows_after_commit") != 0:
        raise ValueError("runtime retained rows after the final batch commit")
    feedback = diagnostics.get("feedback")
    if not isinstance(feedback, dict) or any(
        feedback.get(key) is not expected
        for key, expected in {
            "full_batch_barrier": True,
            "next_batch_only": True,
            "ignore_propagates": False,
            "provider_failed_propagates": False,
            "shadow_present": False,
        }.items()
    ):
        raise ValueError("persisted feedback diagnostics are crossed")
    if terminal_status_counts["provider_failed"] <= 0 or action_counts["ignore"] <= 0:
        raise ValueError("fixture did not exercise ignore and provider_failed terminals")
    if any(action_counts[action] <= 0 for action in _POSITIVE_ACTIONS):
        raise ValueError("fixture did not exercise every positive Primary action")

    streamed = {
        "candidate_rows.jsonl": (candidate_hasher.hexdigest(), candidate_bytes),
        "pair_rows.jsonl": (pair_hasher.hexdigest(), pair_bytes),
        "terminal_rows.jsonl": (terminal_hasher.hexdigest(), terminal_bytes),
    }
    artifact_rows = manifest.get("artifacts")
    if not isinstance(artifact_rows, list):
        raise ValueError("manifest artifact inventory is missing")
    expected_paths: set[str] = set()
    for item in artifact_rows:
        if not isinstance(item, dict):
            raise ValueError("manifest artifact row is invalid")
        relative_path = str(item.get("relative_path", ""))
        if not relative_path or relative_path in expected_paths:
            raise ValueError("manifest artifact path is blank or duplicated")
        expected_paths.add(relative_path)
        artifact = source / relative_path
        if relative_path in streamed:
            actual_hash, actual_bytes = streamed[relative_path]
        else:
            actual_hash, actual_bytes = _sha256_file(artifact), artifact.stat().st_size
        if item.get("sha256") != actual_hash or item.get("bytes") != actual_bytes:
            raise ValueError(f"manifest hash or size differs for {relative_path}")
    actual_paths = {
        path.relative_to(source).as_posix()
        for path in source.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    if actual_paths != expected_paths:
        raise ValueError("source artifact inventory contains missing or extra files")

    return {
        "counts": expected_counts,
        "per_message_candidate_ranking_rows": dict(sorted(candidate_counts.items())),
        "per_message_exposures": dict(sorted(pair_counts.items())),
        "terminal_status_counts": dict(sorted(terminal_status_counts.items())),
        "action_counts": dict(sorted(action_counts.items())),
        "reason_counts": dict(sorted(reason_counts.items())),
        "coverage_distribution": {"3": 36_400},
        "runtime_resident_row_high_water": expected_high_water,
        "runtime_resident_rows_after_commit": 0,
        "single_batch_resident_row_bound": expected_high_water,
        "source_artifact_count": len(expected_paths) + 1,
        "source_hash": manifest.get("source_hash"),
        "source_identity": manifest.get("source_identity"),
        "provider_calls": manifest.get("provider_calls"),
        "physical_provider_attempts": manifest.get("physical_provider_attempts"),
        "live_api_triggered": manifest.get("live_api_triggered"),
        "production_deploy_eligible": manifest.get("production_deploy_eligible"),
    }


def _presentation_audit(bundle: Path, candidate: Path) -> dict[str, Any]:
    report_html = (candidate / "report.html").read_text(encoding="utf-8")
    required_markers = (
        'data-testid="full-pool-main-experiment"',
        'data-testid="historical-sensitivity-1000"',
        'data-production-deploy-eligible="false"',
        "36,400",
        "109,200",
        "1,214",
        "1,194",
        'data-provider-calls-during-composition="0"',
    )
    if any(marker not in report_html for marker in required_markers):
        raise ValueError("Full-Pool presentation is missing a required Validation marker")
    if len(report_html.encode("utf-8")) >= 3 * 1024 * 1024:
        raise ValueError("Full-Pool report.html exceeds the presentation limit")
    trace_index = _read_json(candidate / "trace" / "full-pool-trace-index.json")
    partitions = trace_index.get("partitions")
    if trace_index.get("terminal_count") != 109_200 or not isinstance(partitions, list) or len(partitions) != 90:
        raise ValueError("Full-Pool trace index does not close 109,200 terminals over 90 partitions")
    mermaid = sorted(path.relative_to(candidate).as_posix() for path in candidate.rglob("*.mmd"))
    if len(mermaid) != 8 or "full-pool-mechanism.mmd" not in mermaid:
        raise ValueError("Full-Pool candidate does not contain the exact eight Mermaid masters")
    candidate_manifest = _read_json(candidate / "artifact_manifest.json")
    release_evidence = _read_json(candidate / "release_evidence.json")
    if (
        candidate_manifest.get("production_deploy_eligible") is not False
        or release_evidence.get("production_deploy_eligible") is not False
        or release_evidence.get("provider_calls_during_composition") != 0
    ):
        raise ValueError("Full-Pool candidate is not an explicit zero-call non-production artifact")
    return {
        "bundle_root": str(bundle),
        "candidate_root": str(candidate),
        "report_sha256": _sha256_file(candidate / "report.html"),
        "report_bytes": (candidate / "report.html").stat().st_size,
        "candidate_manifest_sha256": _sha256_file(candidate / "artifact_manifest.json"),
        "candidate_identity_sha256": candidate_manifest.get("candidate_identity_sha256"),
        "trace_index_sha256": _sha256_file(candidate / "trace" / "full-pool-trace-index.json"),
        "trace_partition_count": 90,
        "trace_terminal_count": 109_200,
        "mermaid_downloads": mermaid,
        "provider_calls_during_composition": 0,
        "production_deploy_eligible": False,
    }


def _reject_v8_promotion(
    *,
    repo_root: Path,
    source: Path,
    manifest_sha256: str,
    historical_formal: Path,
    historical_study: Path,
    candidate: Path,
    closure: Path,
    output_root: Path,
    implementation_commit: str,
) -> str:
    destination = output_root / "must-not-exist-v8-release"
    contract = output_root / "must-not-exist-v8-release-contract.json"
    try:
        promote_concurrent_robustness_release(
            repo_root=repo_root,
            formal_root=historical_formal,
            study_root=historical_study,
            candidate_dir=candidate,
            destination_dir=destination,
            release_contract_path=contract,
            release_id="full-pool-validation-ticket-202-must-reject",
            presentation_closure_path=closure,
            full_pool_source_root=source,
            full_pool_manifest_sha256=manifest_sha256,
            implementation_commit=implementation_commit,
        )
    except ConcurrentRobustnessReleaseError as exc:
        if destination.exists() or contract.exists():
            raise ValueError("rejected v8 promotion left a release or contract") from exc
        return str(exc)
    raise ValueError("v8 promotion accepted deterministic Validation evidence")


def _candidate_hashes(candidate: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(candidate.rglob("*")):
        if path.is_symlink():
            raise ValueError("Validation candidate contains a symlink")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError("Validation candidate contains a non-regular entry")
        hashes[path.relative_to(candidate).as_posix()] = _sha256_file(path)
    if not hashes:
        raise ValueError("Validation candidate inventory is empty")
    return hashes


def _write_text_once(path: Path, payload: str, *, mode: int = 0o644) -> None:
    encoded = payload.encode("utf-8")
    if os.path.lexists(path):
        if path.is_symlink() or not path.is_file() or path.read_bytes() != encoded:
            raise FileExistsError(f"existing artifact differs from the expected bytes: {path}")
        return
    staging = path.with_name(f".{path.name}.{os.getpid()}.staging")
    try:
        with staging.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        staging.chmod(mode)
        os.link(staging, path)
    finally:
        staging.unlink(missing_ok=True)


def _write_audit(path: Path, document: dict[str, Any]) -> None:
    payload = json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    _write_text_once(path, payload)


def _bounded_process_failure(command: list[str], *, cwd: Path, env: dict[str, str]) -> dict[str, Any]:
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        timeout=300,
        check=False,
    )
    if completed.returncode == 0:
        raise ValueError(f"expected command to reject Validation evidence: {shlex.join(command)}")
    return {
        "command": shlex.join(command),
        "returncode": completed.returncode,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "stdout_tail": completed.stdout.strip()[-4000:],
        "stderr_tail": completed.stderr.strip()[-4000:],
    }


def _run_actual_playwright(*, repo_root: Path, candidate: Path) -> dict[str, Any]:
    playwright = repo_root / "node_modules" / ".bin" / "playwright"
    if not playwright.is_file() or playwright.is_symlink() or not os.access(playwright, os.X_OK):
        raise ValueError("local Playwright executable is unavailable")
    command = [str(playwright), "test", "tests/playwright/full-pool-presentation.spec.ts"]
    env = {
        "PATH": f"{Path(sys.executable).parent}:{os.environ.get('PATH', os.defpath)}",
        "FULL_POOL_PRESENTATION_BUNDLE": str(candidate),
        "CI": "1",
    }
    for name in ("HOME", "TMPDIR", "PLAYWRIGHT_BROWSERS_PATH"):
        value = os.environ.get(name)
        if value:
            env[name] = value
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=600,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[-4000:]
        raise ValueError(f"actual Full-Pool Playwright failed: {detail}")
    return {
        "command": shlex.join(command),
        "returncode": 0,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "stdout_tail": completed.stdout.strip()[-4000:],
        "bundle": str(candidate),
        "third_party_requests": 0,
        "console_errors": 0,
        "page_errors": 0,
    }


def _production_rejection_gates(*, repo_root: Path, candidate: Path, output_root: Path) -> dict[str, Any]:
    release_id = "full-pool-validation-ticket-202-must-reject"
    rejection_contract = output_root / "validation-v8-rejection-contract.json"
    contract_document = {
        "schema_version": "abm-report-release-contract-v8",
        "release_id": release_id,
        "release_purpose": "validation",
        "source_directory": candidate.relative_to(repo_root).as_posix(),
        "sampling_status": "deterministic_validation",
        "decision_execution_mode": "deterministic_fixture",
        "live_api_triggered": False,
        "production_deploy_eligible": False,
        "artifact_sha256": _candidate_hashes(candidate),
    }
    _write_audit(rejection_contract, contract_document)

    tripwire_bin = output_root / "network-tripwire-bin"
    tripwire_bin.mkdir(exist_ok=True)
    marker_root = output_root / "network-tripwire-invocations"
    tripwire = """#!/usr/bin/env bash
set -euo pipefail
mkdir -p -- "${FULL_POOL_VALIDATION_NETWORK_MARKER}"
printf 'invoked\n' > "${FULL_POOL_VALIDATION_NETWORK_MARKER}/${0##*/}"
exit 97
"""
    for name in ("ssh", "scp", "rsync", "curl", "docker", "npx"):
        _write_text_once(tripwire_bin / name, tripwire, mode=0o755)
    env = {
        "PATH": f"{tripwire_bin}:{os.environ.get('PATH', os.defpath)}",
        "ABM_DEPLOY_PYTHON": sys.executable,
        "FULL_POOL_VALIDATION_NETWORK_MARKER": str(marker_root),
    }
    validator_command = [
        sys.executable,
        str(repo_root / "scripts" / "validate_abm_report_release.py"),
        "--repo-root",
        str(repo_root),
        "--contract",
        str(rejection_contract),
        "--source-dir",
        str(candidate),
        "--require-formal-production",
    ]
    validator = _bounded_process_failure(validator_command, cwd=repo_root, env=env)
    if marker_root.exists():
        raise ValueError("standalone rejection invoked a network or deployment command")

    deploy_command = [
        "bash",
        str(repo_root / "scripts" / "deploy_abm_report.sh"),
        "--contract",
        str(rejection_contract),
        "--source-dir",
        str(candidate),
        "--release-id",
        release_id,
    ]
    deployment = _bounded_process_failure(deploy_command, cwd=repo_root, env=env)
    if marker_root.exists():
        raise ValueError("deployment preflight reached SSH, upload, container, or public acceptance")
    return {
        "rejection_contract": str(rejection_contract),
        "rejection_contract_sha256": _sha256_file(rejection_contract),
        "standalone_require_formal_production": validator,
        "deployment_preflight": deployment,
        "network_tripwire_invocations": [],
        "ssh_or_upload_attempted": False,
        "public_request_attempted": False,
    }


def _formal_handoff_document(
    *,
    implementation_commit: str,
    source: Path,
    source_manifest_sha256: str,
    source_audit: dict[str, Any],
    candidate: Path,
    presentation_audit: dict[str, Any],
    closure_facts: Any,
) -> dict[str, Any]:
    prompt = CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.resolve(CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION)
    return {
        "schema_version": "full-pool-ticket-202-formal-execution-handoff-v1",
        "status": "authorized_execution_ready_after_issue_202_closes",
        "authorization": {
            "execution_ticket": "https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/205",
            "authorization_reference": "#205 body and authorization comment",
            "authorization_status": "explicitly_approved",
            "provider": "openai_compatible",
            "transport": full_pool_module.FULL_POOL_FORMAL_TRANSPORT,
            "credential_transport": "pi_openai_codex_oauth_subscription",
            "adapter_identity": full_pool_module.FULL_POOL_FORMAL_ADAPTER_IDENTITY,
            "requested_model": full_pool_module.FULL_POOL_FORMAL_REQUESTED_MODEL,
            "required_observed_identity": "fresh bounded qualification exact match before main run",
        },
        "request_contract": {
            "prompt_version": CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
            "prompt_canonical_hash": prompt.canonical_hash,
            "visible_field_allowlist": list(APPROVED_VISIBLE_FIELD_ALLOWLIST),
            "excluded_fields": list(APPROVED_EXCLUDED_FIELDS),
            "wire_api": "responses",
            "reasoning_effort": "low",
            "structured_output_schema_version": "engage-decision-output-v1",
            "structured_output_schema_hash": STRUCTURED_OUTPUT_SCHEMA_HASH,
            "max_output_tokens": 256,
            "timeout_seconds": 30.0,
            "max_retries": 2,
            "retry_backoff_seconds": 1.0,
            "omitted_parameters": list(OMITTED_SAMPLING_PARAMETERS),
        },
        "execution_contract": {
            "dataset_identity": full_pool_module.FULL_POOL_PRODUCTION_DATASET_IDENTITY,
            "eligible_user_ids_sha256": FULL_POOL_PRODUCTION_USER_IDS_SHA256,
            "eligible_users": FULL_POOL_PRODUCTION_USER_COUNT,
            "message_ids": list(_MESSAGE_IDS),
            "message_snapshot_sha256": FULL_POOL_AUTHORITATIVE_MESSAGES_SHA256,
            "batches": FULL_POOL_PRODUCTION_HORIZON,
            "primary_only": True,
            "shadow_present": False,
            "worker_count": full_pool_module.FULL_POOL_FORMAL_WORKER_COUNT,
            "logical_judgment_cap": full_pool_module.FULL_POOL_FORMAL_LOGICAL_JUDGMENT_CAP,
            "physical_attempt_cap": full_pool_module.FULL_POOL_FORMAL_PHYSICAL_ATTEMPT_CAP,
            "decision_store_policy": full_pool_module.FULL_POOL_FORMAL_DECISION_STORE_POLICY,
            "attempt_reservation_policy": full_pool_module.FULL_POOL_FORMAL_ATTEMPT_RESERVATION_POLICY,
            "reconciliation_policy": full_pool_module.FULL_POOL_FORMAL_RECONCILIATION_POLICY,
            "subscription_billed_cost_usd": 0.0,
        },
        "first_request_freeze": {
            "output_identity_pattern": "jinjiang-concurrent-full-pool-formal-v1-gpt-5.6-sol-<UTC>",
            "actual_output_identity": None,
            "absolute_operational_root": None,
            "absolute_source_root": None,
            "absolute_candidate_root": None,
            "fresh_qualification_artifacts": None,
            "must_be_generated_and_atomically_frozen_by_issue_205_before_first_request": True,
            "implementation_commit": implementation_commit,
        },
        "canonical_contract": {
            "endpoint": "https://abm.q1ngyuan.top/",
            "ssh_target": "BandwagonHost2",
            "remote_root": "/opt/llm-abm-marketing-sim-report",
            "container": "abm-research-report",
            "loopback_port": 18083,
            "image": "nginx:1.27-alpine",
            "topology": "immutable releases plus atomic current symlink",
            "changes_authorized": False,
            "deploy_only_after_formal_source_candidate_closure_v8_snapshot_and_acceptance": True,
        },
        "validation_evidence": {
            "classification": "Validation; never Formal production source",
            "source_root": str(source),
            "source_manifest_sha256": source_manifest_sha256,
            "source_identity": source_audit["source_identity"],
            "counts": source_audit["counts"],
            "provider_calls": 0,
            "live_api_triggered": False,
            "production_deploy_eligible": False,
            "candidate_root": str(candidate),
            "candidate_manifest_sha256": presentation_audit["candidate_manifest_sha256"],
            "report_sha256": presentation_audit["report_sha256"],
            "presentation_closure_path": str(closure_facts.closure_path),
            "presentation_closure_sha256": closure_facts.closure_sha256,
        },
        "transition": {
            "blocked_by": "#202 until closed",
            "next_step": "#205 may begin fresh qualification immediately after #202 closes",
            "additional_ready_for_human_gate_required": False,
            "provider_requests_in_ticket_202": 0,
            "ssh_or_deployment_in_ticket_202": False,
        },
        "secret_policy": {
            "read_print_or_persist_oauth_value": False,
            "read_env_file": False,
            "persist_headers_raw_prompt_or_raw_provider_payload": False,
        },
    }


def _validation_report(
    *,
    audit: dict[str, Any],
    audit_path: Path,
    handoff_path: Path,
    source_window_seconds: float,
) -> str:
    source_audit = audit["source_audit"]
    presentation = audit["presentation"]
    gate = audit["production_gate"]
    invocation = shlex.join([sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]])
    action_counts = ", ".join(f"`{key}={value}`" for key, value in source_audit["action_counts"].items())
    return f"""# Full-Pool 36,400-user 零调用 Validation 报告

- 状态：**complete Validation；不是 Formal production source**
- output identity：`{audit['output_identity']}`
- implementation commit：`{audit['implementation_commit']}`
- 执行模式：`{audit['execution']['mode']}`
- 本次 subprocess elapsed：`{audit['elapsed_seconds']}` 秒
- 首次 source closure filesystem observed window：`{source_window_seconds}` 秒

## 命令

```bash
{invocation}
```

## 闭合结果

- users / pairs / exposures / Primary terminals：`36,400 / 109,200 / 109,200 / 109,200`
- batches / candidate ranking rows：`30 / 1,691,730`
- 每条 message candidate rows：`563,910`；Batch 0–28 为 `1,214`，Batch 29 为 `1,194`
- coverage：`36,400 × 3`；`below_delivery_capacity_pairs=0`
- actions / failures：{action_counts}
- resident-row high-water：`{source_audit['runtime_resident_row_high_water']}`；单批边界：`{source_audit['single_batch_resident_row_bound']}`；commit 后：`0`
- same-identity replay：新增 logical judgments `0`，manifest/source identity 未改变

## Presentation 与门禁

- candidate `report.html`：`{presentation['report_sha256']}`（`{presentation['report_bytes']}` bytes）
- lazy trace：`{presentation['trace_terminal_count']}` terminals / `{presentation['trace_partition_count']}` partitions
- Mermaid downloads：`8`；主实验、Historical Sensitivity、zh/en、desktop/mobile、keyboard、downloads 与 fail-closed trace 已由 actual Playwright 通过
- composition / closure Provider calls：`0 / 0`
- v8 promotion：拒绝（`{gate['v8_promotion_rejection']}`）
- standalone `--require-formal-production`：拒绝，return code `{gate['standalone_require_formal_production']['returncode']}`
- deployment preflight：在首次 SSH/upload/public request 前拒绝，network tripwire invocations `0`

## Artifacts

- source：`{audit['source_root']}`
- source manifest SHA-256：`{audit['source_manifest_sha256']}`
- candidate：`{presentation['candidate_root']}`
- presentation closure：`{audit['presentation_closure']['path']}` / `{audit['presentation_closure']['sha256']}`
- machine audit：`{audit_path}`
- Formal execution handoff：`{handoff_path}` / `{audit['formal_execution_handoff']['sha256']}`

## 边界与风险

- `provider_calls=0`、`live_api_triggered=false`、`production_deploy_eligible=false`。
- 未调用 TikHub、Douyin、profile API、image generation、SSH 或 canonical endpoint。
- 未读取、打印或写入 credential、`.env`、OAuth value、raw Prompt、raw Provider payload。
- 本结果只验证 deterministic Validation trajectory；fresh observed-model qualification、真实 Provider usage、0 provider failure、actual UTC identity 与 absolute Formal destinations仍由已授权 Ticket #205 在首次请求前冻结并执行。
"""


def main() -> int:
    args = _parse_args()
    if args.confirm_full_pool_validation != _OPT_IN_TOKEN:
        raise SystemExit("refusing slow run: exact Full-Pool Validation opt-in token is required")
    if not _COMMIT.fullmatch(args.implementation_commit):
        raise SystemExit("implementation commit must be a 7-64 character lowercase git hash")

    started_at = _utc_now()
    started = time.monotonic()
    repo_root = _require_real_directory(args.repo_root)
    dataset_dir = _require_real_directory(args.dataset_dir, root=repo_root)
    historical_formal = _require_real_directory(args.historical_formal_root, root=repo_root)
    historical_study = _require_real_directory(args.historical_study_root, root=repo_root)
    historical_candidate = _require_real_directory(args.historical_candidate_dir, root=repo_root)
    output_root = (
        _existing_output_root(args.output_root, repo_root=repo_root)
        if args.continue_closed_source
        else _new_output_root(args.output_root, repo_root=repo_root)
    )
    source_window_started = output_root.stat().st_mtime

    print("[full-pool-validation] independently hashing the exact eligible user set", flush=True)
    user_set_sha256, user_count = _user_set_sha256(dataset_dir)
    if (user_set_sha256, user_count) != (FULL_POOL_PRODUCTION_USER_IDS_SHA256, FULL_POOL_PRODUCTION_USER_COUNT):
        raise ValueError("dataset does not match the frozen 36,400-user eligible pool")

    contract = _contract(dataset_dir, args.output_identity)
    source = output_root / "source" / args.output_identity
    source_preexisted = source.is_dir() and (source / "manifest.json").is_file()
    if args.continue_closed_source:
        if not source_preexisted:
            raise ValueError("continued output root does not contain the exact closed source")
        adapter: _DeterministicFullPoolAdapter | _ReplayTripwireAdapter = _ReplayTripwireAdapter()
        execution_mode = "controlled_closed_source_continuation"
        expected_initial_invocations = 0
        print("[full-pool-validation] continuing the exact closed source with a zero-judgment tripwire", flush=True)
    else:
        adapter = _DeterministicFullPoolAdapter()
        execution_mode = "fresh_slow_validation"
        expected_initial_invocations = 109_200
        print("[full-pool-validation] running 109,200 deterministic Primary judgments", flush=True)
    result = FullPoolFormalExperiment().run(contract, adapter, source)
    if (
        result.status is not FullPoolRunStatus.COMPLETE
        or result.source_root != source
        or result.manifest_sha256 is None
        or result.logical_adapter_decisions != 109_200
        or adapter.request_invocations != expected_initial_invocations
        or result.provider_calls != 0
        or result.live_api_triggered
        or result.production_deploy_eligible
    ):
        raise ValueError("Full-Pool Validation result does not close the zero-call contract")
    source_window_seconds = round(max(0.0, (source / "manifest.json").stat().st_mtime - source_window_started), 3)

    print("[full-pool-validation] streaming an independent persisted-source recomputation", flush=True)
    source_audit = _audit_source(source, result.manifest_sha256)
    manifest_before_replay = _sha256_file(source / "manifest.json")
    replay_adapter = _ReplayTripwireAdapter()
    replay = FullPoolFormalExperiment().run(contract, replay_adapter, source)
    if (
        replay.status is not FullPoolRunStatus.COMPLETE
        or replay.manifest_sha256 != result.manifest_sha256
        or replay.source_identity != result.source_identity
        or replay.logical_adapter_decisions != 109_200
        or replay_adapter.request_invocations != 0
        or _sha256_file(source / "manifest.json") != manifest_before_replay
    ):
        raise ValueError("closed same-identity replay changed hashes or duplicated judgments")

    bundle = output_root / "presentation-bundle"
    candidate = output_root / "candidate"
    closure = output_root / "presentation-closure.json"
    print("[full-pool-validation] composing or validating the historical + Validation presentation", flush=True)
    if bundle.exists():
        if not args.continue_closed_source:
            raise FileExistsError("fresh Validation output unexpectedly contains a presentation bundle")
        report_module._REPORT_PRESENTATION.validate_full_pool_presentation_bundle(
            bundle,
            full_pool_source_root=source,
            full_pool_manifest_sha256=result.manifest_sha256,
            historical_candidate_dir=historical_candidate,
        )
    else:
        report_module._REPORT_PRESENTATION.compose_full_pool_presentation_bundle(
            full_pool_source_root=source,
            full_pool_manifest_sha256=result.manifest_sha256,
            historical_formal_root=historical_formal,
            historical_study_root=historical_study,
            historical_candidate_dir=historical_candidate,
            destination_dir=bundle,
        )
    if candidate.exists():
        if not args.continue_closed_source:
            raise FileExistsError("fresh Validation output unexpectedly contains a candidate")
        report_module._REPORT_PRESENTATION.validate_full_pool_candidate(
            candidate,
            full_pool_source_root=source,
            full_pool_manifest_sha256=result.manifest_sha256,
            historical_formal_root=historical_formal,
            historical_study_root=historical_study,
            presentation_bundle_dir=bundle,
            implementation_commit=args.implementation_commit,
        )
    else:
        report_module._REPORT_PRESENTATION.compose_full_pool_candidate(
            full_pool_source_root=source,
            full_pool_manifest_sha256=result.manifest_sha256,
            historical_formal_root=historical_formal,
            historical_study_root=historical_study,
            presentation_bundle_dir=bundle,
            implementation_commit=args.implementation_commit,
            destination_dir=candidate,
        )
    if closure.exists():
        if not args.continue_closed_source:
            raise FileExistsError("fresh Validation output unexpectedly contains a presentation closure")
        closure_facts = evidence_module.validate_full_pool_presentation_closure(
            repo_root=repo_root,
            closure_path=closure,
            full_pool_source_root=source,
            full_pool_manifest_sha256=result.manifest_sha256,
            historical_formal_root=historical_formal,
            historical_study_root=historical_study,
            presentation_bundle_dir=bundle,
            candidate_dir=candidate,
        )
    else:
        closure_facts = evidence_module.close_full_pool_presentation(
            repo_root=repo_root,
            full_pool_source_root=source,
            full_pool_manifest_sha256=result.manifest_sha256,
            historical_formal_root=historical_formal,
            historical_study_root=historical_study,
            presentation_bundle_dir=bundle,
            candidate_dir=candidate,
            destination_path=closure,
            implementation_commit=args.implementation_commit,
        )
    presentation_audit = _presentation_audit(bundle, candidate)

    print("[full-pool-validation] running actual desktop/mobile Playwright against the candidate", flush=True)
    playwright_audit = _run_actual_playwright(repo_root=repo_root, candidate=candidate)

    print("[full-pool-validation] proving every production and deployment gate rejects Validation", flush=True)
    v8_rejection = _reject_v8_promotion(
        repo_root=repo_root,
        source=source,
        manifest_sha256=result.manifest_sha256,
        historical_formal=historical_formal,
        historical_study=historical_study,
        candidate=candidate,
        closure=closure,
        output_root=output_root,
        implementation_commit=args.implementation_commit,
    )
    production_gates = _production_rejection_gates(
        repo_root=repo_root,
        candidate=candidate,
        output_root=output_root,
    )

    handoff_path = output_root / "formal-execution-handoff.json"
    handoff = _formal_handoff_document(
        implementation_commit=args.implementation_commit,
        source=source,
        source_manifest_sha256=result.manifest_sha256,
        source_audit=source_audit,
        candidate=candidate,
        presentation_audit=presentation_audit,
        closure_facts=closure_facts,
    )
    _write_audit(handoff_path, handoff)

    finished_at = _utc_now()
    audit_path = output_root / "validation-audit.json"
    audit = {
        "schema_version": "full-pool-ticket-202-validation-audit-v1",
        "status": "complete",
        "started_at_utc": started_at,
        "finished_at_utc": finished_at,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "implementation_commit": args.implementation_commit,
        "execution": {
            "mode": execution_mode,
            "source_preexisted": source_preexisted,
            "initial_adapter_invocations_this_process": adapter.request_invocations,
            "filesystem_observed_source_closure_window_seconds": source_window_seconds,
        },
        "dataset_dir": str(dataset_dir),
        "eligible_user_ids_sha256": user_set_sha256,
        "output_identity": args.output_identity,
        "output_root": str(output_root),
        "source_root": str(source),
        "source_manifest_sha256": result.manifest_sha256,
        "source_identity": result.source_identity,
        "operational_root": str(result.workspace_root),
        "source_audit": source_audit,
        "same_identity_replay": {
            "logical_judgments_reused": replay.logical_adapter_decisions,
            "new_logical_judgments": replay_adapter.request_invocations,
            "manifest_sha256": replay.manifest_sha256,
            "source_identity": replay.source_identity,
        },
        "presentation": presentation_audit,
        "presentation_closure": {
            "path": str(closure_facts.closure_path),
            "sha256": closure_facts.closure_sha256,
            "schema_version": closure_facts.closure_schema_version,
            "provider_calls_during_closure": 0,
            "production_deploy_eligible": False,
        },
        "actual_playwright": playwright_audit,
        "formal_execution_handoff": {
            "path": str(handoff_path),
            "sha256": _sha256_file(handoff_path),
            "schema_version": handoff["schema_version"],
            "authorization_ticket": "#205",
            "additional_ready_for_human_gate_required": False,
        },
        "production_gate": {
            "v8_promotion_rejected": True,
            "v8_promotion_rejection": v8_rejection,
            "release_created": False,
            "release_contract_created": False,
            **production_gates,
        },
        "external_effects": {
            "provider_calls": 0,
            "live_api_triggered": False,
            "tikhub_triggered": False,
            "douyin_triggered": False,
            "profile_api_triggered": False,
            "image_generation_triggered": False,
            "ssh_triggered": False,
            "upload_triggered": False,
            "canonical_endpoint_requested": False,
            "credentials_read_printed_or_written": False,
        },
    }
    _write_audit(audit_path, audit)
    report_path = output_root / "validation-report.md"
    _write_text_once(
        report_path,
        _validation_report(
            audit=audit,
            audit_path=audit_path,
            handoff_path=handoff_path,
            source_window_seconds=source_window_seconds,
        ),
    )
    print(
        json.dumps(
            {
                "status": "complete",
                "audit": str(audit_path),
                "audit_sha256": _sha256_file(audit_path),
                "report": str(report_path),
                "report_sha256": _sha256_file(report_path),
                "formal_execution_handoff": str(handoff_path),
                "formal_execution_handoff_sha256": _sha256_file(handoff_path),
                "source": str(source),
                "source_manifest_sha256": result.manifest_sha256,
                "candidate": str(candidate),
                "closure": str(closure),
                "provider_calls": 0,
                "production_deploy_eligible": False,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Full-Pool Validation interrupted; no final audit was written", file=sys.stderr)
        raise
