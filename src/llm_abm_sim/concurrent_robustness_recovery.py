"""Study-owned, zero-call recovery proposals; no execution or authorization path.

The original stopped workspace remains terminal. A proposal pins immutable
origins and unused budgets for a separately approved recovery implementation.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

from . import concurrent_execution_journal as _journal
from . import concurrent_robustness_formal_execution as _formal
from . import concurrent_robustness_v2 as _v2

RECOVERY_PROPOSAL_SCHEMA = "concurrent-robustness-formal-recovery-proposal-v1"
RECOVERY_PROPOSAL_FILE = "recovery-proposal.json"


class ConcurrentRobustnessRecoveryError(ValueError):
    """The proposed inheritance failed closed; no recovery authority was issued."""


def _safe_path(value: str | Path) -> Path:
    path = _formal._safe_path(_formal._absolute_path(value), "recovery path")
    if path.name.lower() in {"auth.json", "credentials.json"}:
        raise ConcurrentRobustnessRecoveryError("Recovery cannot read credential artifacts")
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ConcurrentRobustnessRecoveryError("Recovery paths cannot contain symlinks")
    return path


def _file_fact(path: Path) -> dict[str, object]:
    _safe_path(path)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ConcurrentRobustnessRecoveryError("Recovery requires dedicated regular files")
    return {
        "path": str(path), "sha256": _formal._sha256_file(path),
        "bytes": info.st_size, "mode": stat.S_IMODE(info.st_mode),
    }


def _tree_files(root: Path) -> set[Path]:
    _safe_path(root)
    files: set[Path] = set()
    if root.exists():
        if not root.is_dir():
            raise ConcurrentRobustnessRecoveryError("Recovery evidence root must be a directory")
        for path in root.rglob("*"):
            _safe_path(path)
            if path.is_file():
                files.add(path)
            elif not path.is_dir():
                raise ConcurrentRobustnessRecoveryError("Recovery evidence contains a special file")
    return files


def _inspect_inputs(plan_path: Path) -> _formal.FormalPlanInspection:
    # Guard references before the existing reader can follow them. No recursive
    # scan of the plan directory, OAuth profile, raw payload or credential store.
    _file_fact(plan_path)
    plan, _ = _formal._load_canonical_object(plan_path, "recovery source plan")
    request = _formal._request_from_plan(plan.get("request"))
    for path in (
        request.manifest.path, *(row.path for row in request.qualification_artifacts),
        Path(cast(str, plan["authorization_artifact_path"])),
    ):
        _file_fact(path)
    manifest, _ = _formal._manifest_from_request(request)
    for root in (manifest.source.source_dir, request.output_root, _v2._operational_root(request.output_root)):
        _tree_files(root)
    return _formal.inspect_formal_execution_plan(plan_path)


def _input_files(plan_path: Path, inspected: _formal.FormalPlanInspection) -> set[Path]:
    request, manifest = inspected.request, inspected.manifest
    files = {
        plan_path, request.manifest.path,
        Path(cast(str, inspected.plan["authorization_artifact_path"])),
        *(row.path for row in request.qualification_artifacts),
    }
    for root in (manifest.source.source_dir, request.output_root, _v2._operational_root(request.output_root)):
        files.update(_tree_files(root))
    return files


def _inventory(files: set[Path]) -> list[dict[str, object]]:
    return [_file_fact(path) for path in sorted(files)]


def _runtime_replay(
    scope: Path, identity: Mapping[str, Any],
) -> tuple[_journal.ConcurrentExecutionJournal, dict[str, Any]]:
    workspace = _journal.derive_concurrent_execution_workspace(scope / "runtime")
    allowed = {
        _journal.CONCURRENT_MESSAGE_EXECUTION_RUN_IDENTITY_JSON,
        _journal.CONCURRENT_MESSAGE_EXECUTION_JOURNAL_JSONL,
        _journal.CONCURRENT_MESSAGE_EXECUTION_STATUS_JSON,
        _journal.CONCURRENT_MESSAGE_EXECUTION_LOCK_FILE,
        _journal.CONCURRENT_MESSAGE_EXECUTION_SNAPSHOTS_DIR,
        "concurrent_runtime_batch_spool",
    }
    if (scope / "runtime").exists() or not workspace.is_dir():
        raise ConcurrentRobustnessRecoveryError("Recovery needs the original private runtime")
    required = allowed - {"concurrent_runtime_batch_spool"}
    names = {p.name for p in workspace.iterdir()}
    if {p.name for p in scope.iterdir()} != {
        _v2._V2_LEDGER_IDENTITY, _v2._V2_LEDGER_JSONL, workspace.name,
    } or not required.issubset(names) or not names.issubset(allowed):
        raise ConcurrentRobustnessRecoveryError("Recovery runtime contains missing or unexpected entries")
    # The legacy journal reader owns checksum/state semantics. Guard its snapshot
    # references first, including path escape and extra snapshot files.
    records = _v2._read_canonical_jsonl(workspace / _journal.CONCURRENT_MESSAGE_EXECUTION_JOURNAL_JSONL)
    snapshots = set()
    snapshot_root = workspace / _journal.CONCURRENT_MESSAGE_EXECUTION_SNAPSHOTS_DIR
    for row in records:
        if row.get("record_type") == "snapshot":
            reference = Path(cast(str, row["snapshot_path"]))
            if reference.is_absolute() or len(reference.parts) != 2 or reference.parts[0] != snapshot_root.name:
                raise ConcurrentRobustnessRecoveryError("Recovery runtime snapshot escapes its scope")
            snapshots.add(_safe_path(workspace / reference))
    if _tree_files(snapshot_root) != snapshots:
        raise ConcurrentRobustnessRecoveryError("Recovery runtime snapshot inventory is crossed")
    journal = _journal.ConcurrentExecutionJournal.open_existing(workspace)
    if journal.identity != identity:
        raise ConcurrentRobustnessRecoveryError("Recovery runtime identity differs from the frozen context")
    replay = journal._replay_runtime()
    expected_status = {**replay["status"], "inflight_unknown": False}
    # The runtime records only successful Realizations; the separately verified
    # pair ledger owns the known Provider failure. Its writer calls this running,
    # while the source-only runtime replay conservatively calls it unknown.
    if expected_status["lifecycle"] == "inflight_unknown":
        expected_status["lifecycle"] = "running"
    if journal.status_path.read_bytes() != _formal._canonical_json_bytes(expected_status).rstrip(b"\n"):
        raise ConcurrentRobustnessRecoveryError("Recovery runtime status differs from its journal")
    return journal, replay


def _inherit_cell(
    inspected: _formal.FormalPlanInspection, index: int, config: Any, prepared: Any,
) -> tuple[dict[str, object], dict[str, object] | None]:
    manifest = inspected.manifest
    digest = hashlib.sha256(_v2._manifest_bytes(manifest)).hexdigest()
    cell = manifest.prompt_model_cells[index]
    scope = _v2._operational_root(inspected.request.output_root) / f"cell-{index:02d}"
    identity = _v2._cell_ledger_identity(
        manifest=manifest, manifest_sha256=digest, cell_index=index, cell=cell, cell_scope=scope,
    )
    ledger = _v2._V2PairLedger.read(scope, identity=identity)
    if any(state not in {"settled", "stopped"} for state in ledger.state_by_pair.values()):
        raise ConcurrentRobustnessRecoveryError("Recovery requires fully settled inherited successes")
    judgments, terminals = ledger.judgments(), ledger.terminals()
    terminal_by_pair = {terminal.pair_id: terminal for terminal in terminals}
    policy = _v2.EngagementRealizationPolicy(source_identity=manifest.realization_source.source_identity)
    origins = []
    judgment_records = {str(row["pair_id"]): row for row in ledger.records if row["state"] == "judgment_persisted"}
    for judgment in judgments:
        if not judgment.usage_complete or any(
            attempt.usage_complete_response_count != attempt.provider_response_count
            or attempt.usage_missing_response_count or attempt.usage_malformed_response_count
            for attempt in judgment.attempt_evidence
        ):
            raise ConcurrentRobustnessRecoveryError("Inherited successful Judgment lacks complete usage")
        terminal = terminal_by_pair.get(judgment.pair_id)
        expected = _v2._build_realized_terminal(
            manifest=manifest, judgment=judgment,
            realization=policy.realize(judgment.decision(), user_id=judgment.user_id, message_id=judgment.message_id),
        )
        if terminal != expected:
            raise ConcurrentRobustnessRecoveryError("Inherited Realization differs from its Judgment")
        origins.append({
            "pair_id": judgment.pair_id, "pair_schedule_position": judgment.pair_schedule_position,
            "judgment_id": judgment.judgment_id, "realized_terminal_id": expected.realized_terminal_id,
            "judgment_record_sequence": judgment_records[judgment.pair_id]["sequence"],
            "judgment_record_sha256": judgment_records[judgment.pair_id]["checksum"],
            "request_invocations": judgment.request_invocations,
        })
    stops = [row for row in ledger.records if row["state"] == "stopped"]
    failed = None
    if stops:
        if len(stops) != 1:
            raise ConcurrentRobustnessRecoveryError("Recovery requires one known stopped pair")
        stop = stops[0]
        payload = cast(dict[str, object], stop["payload"])
        attempts = tuple(_v2._V2AttemptEvidence.model_validate(row) for row in cast(list[object], payload["attempt_evidence"]))
        if (
            not 0 < len(attempts) < _v2._V2_MAXIMUM_ATTEMPTS
            or attempts[-1].failure_category != "usage_evidence"
            or attempts[-1].outcome != "nonretryable_failure"
            or attempts[-1].usage_missing_response_count != 1
        ):
            raise ConcurrentRobustnessRecoveryError("Recovery requires a known missing-usage failure with unused slots")
        failed = {
            key: stop[key] for key in ("cell_index", "cell_id", "pair_id", "pair_schedule_position", "time_step", "message_id", "user_id")
        }
        failed.update({
            "stopped_record_sequence": stop["sequence"], "stopped_record_sha256": stop["checksum"],
            "attempt_evidence": [row.model_dump(mode="json") for row in attempts],
            "request_invocations": len(attempts), "remaining_attempt_budget": _v2._V2_MAXIMUM_ATTEMPTS - len(attempts),
            "recovery_authorized": False,
        })
    count = len(judgments) + len(stops)
    ordered = [(j.pair_schedule_position, j.pair_id) for j in judgments]
    ordered.extend((cast(int, row["pair_schedule_position"]), str(row["pair_id"])) for row in stops)
    if [position for position, _ in ordered] != list(range(count)) or len(terminal_by_pair) != len(judgments):
        raise ConcurrentRobustnessRecoveryError("Inherited pairs are not a unique settled prefix")

    runtime_workspace = _journal.derive_concurrent_execution_workspace(scope / "runtime")
    runtime_identity = _v2._runtime_identity(
        config=config, prepared=prepared, manifest=manifest, manifest_sha256=digest,
        cell_index=index, cell=cell, runtime_target=scope / "runtime", runtime_workspace=runtime_workspace,
        judgment_source_identity=str(identity["judgment_source_identity"]),
    )
    journal, replay = _runtime_replay(scope, runtime_identity)
    state = _v2._ConcurrentRuntimeKernelState(
        cohort=prepared.cohort, exposed_by_message={message.message_id: set() for message in config.messages},
        campaign_engaged_user_ids=set(),
    )
    kernel = _v2._ConcurrentRuntimeKernel.primary_only(
        config=config, state=state, base_network_by_user=prepared.base_network_by_user,
        neighbors_by_user=prepared.neighbors_by_user, journal=journal,
    )
    commits = kernel.restore(replay, result_builder=_v2._PrimaryOnlyConcurrentRuntimeConsumer._replayed_primary_result_row)
    seen = set()

    def check_terminal(row: Mapping[str, object]) -> None:
        pair = str(row["pair_id"])
        if pair in seen or pair not in terminal_by_pair or row != _v2._realized_runtime_terminal(terminal_by_pair[pair]):
            raise ConcurrentRobustnessRecoveryError("Inherited runtime terminal is crossed with its Realization")
        seen.add(pair)

    for chunk in kernel._spool.iter_committed(replay):
        for row in chunk.terminal_rows:
            check_terminal(row)
    for row in state.terminal_rows:
        check_terminal(row)
    if seen != set(terminal_by_pair) or any(replay["status"][key] != expected for key, expected in {
        "started_variant_count": count, "terminal_variant_count": len(judgments), "closed_pair_count": len(judgments),
    }.items()):
        raise ConcurrentRobustnessRecoveryError("Inherited runtime and ledger progress differ")
    if failed is not None:
        pending = kernel.pending_plans()
        if not pending or pending[0].pair_id != failed["pair_id"]:
            raise ConcurrentRobustnessRecoveryError("Stopped pair does not match the runtime cursor")
    elif state.next_time_step != manifest.ranking_contract.horizon:
        raise ConcurrentRobustnessRecoveryError("Recovery skipped an incomplete predecessor cell")
    return {
        "cell_index": index, "cell_id": cell.cell_id, "requested_model": cell.requested_model,
        "ledger_path": str(ledger.journal_path), "ledger_head_sha256": ledger.records[-1]["checksum"],
        "judgment_source_identity": identity["judgment_source_identity"],
        "runtime_workspace": str(runtime_workspace), "runtime_identity_sha256": journal.identity_hash,
        "completed_batches": len(commits), "inherited_pairs": origins,
    }, failed


def _read_source(plan_path: Path) -> tuple[_formal.FormalPlanInspection, dict[str, object]]:
    inspected = _inspect_inputs(plan_path)
    files = _input_files(plan_path, inspected)
    before = _inventory(files)
    manifest = inspected.manifest
    progress = _v2._inspect_v2_progress(
        manifest=manifest, output_path=inspected.request.output_root, formal_execution_plan=inspected.plan,
    )
    if (
        progress["status"] != "stopped" or progress["failed_logical_judgments"] != 1
        or progress["unknown_postdispatch_pairs"] != 0 or progress["execution_published"]
    ):
        raise ConcurrentRobustnessRecoveryError("Recovery requires one known stopped, unpublished source")
    closure = _v2._close_source(manifest.source.source_dir)
    # Same shared v1/v2 source-validation Seam used by the v2 Study runner.
    _v2._validate_source_against_manifest(manifest, closure, manifest.source.source_dir)  # type: ignore[arg-type]
    dataset = _safe_path(str(closure.source_evidence.config_snapshot["dataset_dir"]))
    dataset_files = {
        dataset / name for name in (
            *_journal._CONCURRENT_MESSAGE_REQUIRED_DATASET_FILES, *_journal._CONCURRENT_MESSAGE_OPTIONAL_COMMENT_FILES,
        ) if (dataset / name).exists()
    }
    dataset_before = _inventory(dataset_files)
    config = _v2._dynamic_runtime_config(closure)
    prepared = _v2._prepare_concurrent_runtime_inputs(config)
    sample_hash = hashlib.sha256(json.dumps(
        prepared.cohort.sample_user_ids, ensure_ascii=False, separators=(",", ":"),
    ).encode()).hexdigest()
    if sample_hash != manifest.sample.sample_identity or _v2._effective_graph_identity(prepared) != manifest.realization_source.graph_identity_sha256:
        raise ConcurrentRobustnessRecoveryError("Recovery sample or graph differs from the frozen context")
    cell_count = cast(int, progress["completed_cells"]) + 1
    inherited = [_inherit_cell(inspected, index, config, prepared) for index in range(cell_count)]
    failures = [failure for _, failure in inherited if failure is not None]
    if len(failures) != 1 or sum(len(cast(list[object], cell["inherited_pairs"])) for cell, _ in inherited) != progress["successful_judgments"]:
        raise ConcurrentRobustnessRecoveryError("Recovery prefix counts are crossed")
    _v2._assert_source_unchanged(closure)
    if before != _inventory(_input_files(plan_path, inspected)) or dataset_before != _inventory(dataset_files):
        raise ConcurrentRobustnessRecoveryError("Recovery source changed during inspection")
    return inspected, {
        "source_plan": {"path": str(plan_path), "sha256": _formal._sha256_file(plan_path)},
        "source_output_root": str(inspected.request.output_root),
        "source_artifacts": _inventory(files | dataset_files),
        "frozen_context": {
            "manifest_sha256": inspected.request.manifest.sha256,
            "source_manifest_sha256": manifest.source.manifest_sha256,
            "sample_identity": manifest.sample.sample_identity,
            "message_snapshot_sha256": manifest.message_snapshot_sha256,
            "realization_source_identity": manifest.realization_source.source_identity,
            "prompt_model_cells": [row.model_dump(mode="json") for row in manifest.prompt_model_cells],
        },
        "progress": progress, "inherited_cells": [cell for cell, _ in inherited], "failed_pair": failures[0],
    }


def _destination(output: str | Path, inspected: _formal.FormalPlanInspection, *, creating: bool) -> Path:
    target = _safe_path(output)
    if not _v2._OUTPUT_IDENTITY_PATTERN.fullmatch(target.name) or target.name == inspected.manifest.output_identity:
        raise ConcurrentRobustnessRecoveryError("Recovery requires an independent output identity")
    protected = {
        inspected.manifest.source.source_dir, inspected.request.output_root,
        _v2._operational_root(inspected.request.output_root),
        inspected.request.manifest.path.parent,
        *(row.path.parent for row in inspected.request.qualification_artifacts),
    }
    if any(target == p or target.is_relative_to(p) or p.is_relative_to(target) for p in protected):
        raise ConcurrentRobustnessRecoveryError("Recovery destination overlaps protected evidence")
    if not target.parent.is_dir() or (creating and target.exists()):
        raise ConcurrentRobustnessRecoveryError("Recovery destination must be new with an existing parent")
    return target


def _proposal_body(
    inspected: _formal.FormalPlanInspection, source: dict[str, object], target: Path, gate: dict[str, object],
) -> dict[str, object]:
    progress = cast(dict[str, Any], source["progress"])
    failure = cast(dict[str, Any], source["failed_pair"])
    budgets = []
    for cap, model in zip(inspected.request.provider_caps, progress["models"], strict=True):
        remaining = cap.logical_judgment_cap - model["successful_judgments"]
        consumed_failed = failure["request_invocations"] if failure["cell_id"].endswith(f"::{model['requested_model']}") else 0
        maximum_new = remaining * _v2._V2_MAXIMUM_ATTEMPTS - consumed_failed
        if maximum_new < 0 or maximum_new + model["physical_attempts"] > cap.physical_attempt_cap:
            raise ConcurrentRobustnessRecoveryError("Recovery model budget is exhausted or crossed")
        budgets.append({
            "requested_model": model["requested_model"], "remaining_valid_judgments": remaining,
            "maximum_new_physical_attempts": maximum_new, "physical_attempt_cap": cap.physical_attempt_cap,
        })
    maximum_new = sum(row["maximum_new_physical_attempts"] for row in budgets)
    cumulative = progress["physical_attempts"] + maximum_new
    if cumulative > inspected.request.physical_attempt_cap:
        raise ConcurrentRobustnessRecoveryError("Recovery exceeds cumulative Formal cap")
    return {
        "schema_version": RECOVERY_PROPOSAL_SCHEMA, "status": "ready_for_human",
        **source, "output_root": str(target), "output_identity": target.name,
        "model_budgets": budgets,
        "remaining_valid_judgments": inspected.request.logical_judgment_cap - progress["successful_judgments"],
        "maximum_new_physical_attempts": maximum_new, "maximum_cumulative_physical_attempts": cumulative,
        "logical_judgment_cap": inspected.request.logical_judgment_cap,
        "physical_attempt_cap": inspected.request.physical_attempt_cap,
        "historical_all_attempts_usage_complete": False, "historical_all_attempts_total_tokens": None,
        "current_gate_at_preparation": gate,
        "execution_authority": False, "recovery_slots_consumed": 0,
        "provider_calls_during_preparation": 0, "credential_reads_during_preparation": 0,
        "live_api_triggered": False, "production_deploy_eligible": False,
    }


def prepare_concurrent_robustness_recovery(
    source_plan: str | Path, *, output_dir: str | Path,
) -> dict[str, object]:
    """Create one immutable, non-executable proposal in a new output directory.

    Revalidates the original plan, ledger, runtime and frozen inputs read-only.
    Rejects unknown dispatch, unsupported failure, path overlap and exhausted
    budgets before writing. Failure may leave an explicitly incomplete new
    directory; it never repairs or overwrites either source or destination.
    """
    plan_path = _safe_path(source_plan)
    inspected, source = _read_source(plan_path)
    target = _destination(output_dir, inspected, creating=True)
    for row in cast(list[dict[str, object]], source["source_artifacts"]):
        path = Path(cast(str, row["path"]))
        if target == path or target.is_relative_to(path.parent) or path.is_relative_to(target):
            raise ConcurrentRobustnessRecoveryError("Recovery destination overlaps an input scope")
    body = _proposal_body(inspected, source, target, inspected.current_gate)
    proposal = {**body, "proposal_identity_sha256": _v2._json_sha256(body)}
    target.mkdir(mode=0o755, exist_ok=False)
    pending = target / ".recovery-proposal.pending"
    with pending.open("xb") as handle:
        handle.write(_formal._canonical_json_bytes(proposal))
        handle.flush()
        os.fsync(handle.fileno())
    pending.chmod(0o444)
    # link is an atomic no-overwrite install, unlike rename/replace. A crash
    # before unlink leaves a visibly incomplete (two-link) proposal, never ready.
    os.link(pending, target / RECOVERY_PROPOSAL_FILE, follow_symlinks=False)
    pending.unlink()
    _v2._fsync_directory(target)
    _v2._fsync_directory(target.parent)
    return proposal


def _read_recovery_proposal(
    proposal_path: str | Path,
) -> tuple[dict[str, Any], _formal.FormalPlanInspection]:
    """Private inherited-context Seam shared by inspection and recovery execution."""
    path = _safe_path(proposal_path)
    fact = _file_fact(path)
    if cast(int, fact["mode"]) & 0o222:
        raise ConcurrentRobustnessRecoveryError("Recovery proposal must be immutable")
    proposal, payload = _formal._load_canonical_object(path, "recovery proposal")
    reference = _formal.FormalArtifactReference.model_validate(proposal["source_plan"])
    if _file_fact(reference.path)["sha256"] != reference.sha256:
        raise ConcurrentRobustnessRecoveryError("Recovery source plan hash is crossed")
    inspected, source = _read_source(reference.path)
    target = _destination(cast(str, proposal["output_root"]), inspected, creating=False)
    if path != target / RECOVERY_PROPOSAL_FILE or {p.name for p in target.iterdir()} != {RECOVERY_PROPOSAL_FILE}:
        raise ConcurrentRobustnessRecoveryError("Recovery proposal location or inventory is crossed")
    gate = cast(dict[str, object], proposal["current_gate_at_preparation"])
    instant = datetime.fromisoformat(cast(str, gate["checked_at_utc"]))
    if instant.utcoffset() != timedelta(0):
        raise ConcurrentRobustnessRecoveryError("Recovery preparation time must be UTC")
    expected_gate = _formal._inspection_time_gate(inspected.plan, instant)
    body = _proposal_body(inspected, source, target, expected_gate)
    expected = {**body, "proposal_identity_sha256": _v2._json_sha256(body)}
    if payload != _formal._canonical_json_bytes(expected):
        raise ConcurrentRobustnessRecoveryError("Recovery proposal differs from its persisted origins")
    return expected, inspected


def inspect_concurrent_robustness_recovery_proposal(proposal_path: str | Path) -> dict[str, object]:
    """Re-read immutable origins and proposal facts without locks, writes or calls.

    The returned current gates are fresh; the proposal's preparation-time gates
    remain a historical annotation and cannot authorize any dispatch.
    """
    expected, inspected = _read_recovery_proposal(proposal_path)
    body = expected
    return {
        "schema_version": "concurrent-robustness-recovery-proposal-inspection-v1",
        "status": "ready_for_human", "proposal_identity_sha256": expected["proposal_identity_sha256"],
        "remaining_valid_judgments": body["remaining_valid_judgments"],
        "maximum_new_physical_attempts": body["maximum_new_physical_attempts"],
        "current_gate": inspected.current_gate, "execution_authority": False,
        "inspection_only": True, "provider_calls_during_inspection": 0,
        "credential_reads_during_inspection": 0, "production_deploy_eligible": False,
    }
