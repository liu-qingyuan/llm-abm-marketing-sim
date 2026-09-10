"""Provider-free replay verification for a recovered concurrent campaign."""
from __future__ import annotations

import hashlib
import json
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import concurrent_robustness_v2 as _v2
from ._concurrent_recovery_campaign import RecoveryCampaignError
from ._concurrent_recovery_judgment import RecoveryJudgmentV1
from ._concurrent_recovery_progress import CampaignProgress
from ._concurrent_recovery_runtime import _coordinates, _kernel, inherited_terminals


class _MissingTerminal(RuntimeError):
    """Stop replay at the first terminal which has not been persisted."""


@dataclass(frozen=True)
class _RecoveryReplayFacts:
    summary: dict[str, Any]
    batch_commits: tuple[dict[str, Any], ...]


def _verified_recovery_realization(
    *,
    proposal: Mapping[str, Any],
    manifest: _v2.ConcurrentRobustnessManifestV2,
    state: CampaignProgress,
    records: tuple[dict[str, Any], ...],
) -> _RecoveryReplayFacts:
    """Recompute the runtime prefix without dispatching or writing durable outputs."""
    manifest_sha = str(proposal["frozen_context"]["manifest_sha256"])
    _v2._require_sha256(manifest_sha, "frozen manifest SHA")
    if manifest_sha != hashlib.sha256(_v2._manifest_bytes(manifest)).hexdigest():
        raise RecoveryCampaignError("recovery manifest identity is crossed")

    terminals = inherited_terminals(proposal, manifest)
    for key, judgment_payload in state.judgments.items():
        judgment = RecoveryJudgmentV1.model_validate(judgment_payload)
        cell = manifest.prompt_model_cells[key[0]]
        expected = _v2._judgment_source_identity(
            manifest=manifest, manifest_sha256=manifest_sha,
            cell_index=key[0], cell=cell,
        )
        if judgment.judgment_source_identity != expected:
            raise RecoveryCampaignError("recovery Judgment source identity is crossed")
        if (judgment.cell_index, judgment.pair.pair_schedule_position) != key:
            raise RecoveryCampaignError("recovery Judgment key is crossed")
        terminals[key] = judgment.realized_projection(
            realization_source_identity=manifest.realization_source.source_identity,
        )

    reserved: dict[tuple[int, int], dict[str, Any]] = {}
    recorded_commits: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for record in records:
        kind = record.get("kind")
        payload = record.get("payload")
        if not isinstance(payload, Mapping):
            continue
        if kind == "pair_reserved":
            index, position = payload.get("cell_index"), payload.get("pair_schedule_position")
            if type(index) is not int or type(position) is not int:
                raise RecoveryCampaignError("recovery reservation coordinates are malformed")
            key = index, position
            coordinates = dict(payload)
            if key in reserved and _v2._canonical_json_bytes(reserved[key]) != _v2._canonical_json_bytes(coordinates):
                raise RecoveryCampaignError("recovery reservation is duplicated with different coordinates")
            reserved[key] = coordinates
        elif kind == "batch_committed":
            index, step = payload.get("cell_index"), payload.get("time_step")
            if type(index) is not int or type(step) is not int:
                raise RecoveryCampaignError("recovery batch coordinates are malformed")
            recorded_commits.setdefault((index, step), []).append(dict(payload["commit"]))

    closure = _v2._close_source(manifest.source.source_dir)
    _v2._validate_source_against_manifest(manifest, closure, manifest.source.source_dir)  # type: ignore[arg-type]
    config = _v2._dynamic_runtime_config(closure)
    prepared = _v2._prepare_concurrent_runtime_inputs(config)
    sample_sha = hashlib.sha256(json.dumps(prepared.cohort.sample_user_ids, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    if sample_sha != manifest.sample.sample_identity or _v2._effective_graph_identity(prepared) != manifest.realization_source.graph_identity_sha256:
        raise RecoveryCampaignError("recovery graph differs from the frozen source")

    encountered_pairs: set[tuple[int, int]] = set()
    visited_terminals: set[tuple[int, int]] = set()
    encountered_reserved: set[tuple[int, int]] = set()
    encountered_commits: set[tuple[int, int, int]] = set()
    encountered_parallel_batches: set[tuple[int, int]] = set()
    verified_terminals = 0
    verified_batches = 0
    recomputed_batches: list[dict[str, Any]] = []
    stopped = False
    with tempfile.TemporaryDirectory(prefix="concurrent-recovery-replay-") as directory:
        root = Path(directory)
        for index, cell in enumerate(manifest.prompt_model_cells):
            cell_terminals = {key: value for key, value in terminals.items() if key[0] == index}
            target = root / f"cell-{index:02d}" / "runtime"
            target.parent.mkdir()
            kernel, native_journal = _kernel(
                config=config, prepared=prepared, manifest=manifest, cell_index=index,
                target=target, epoch_identity=manifest_sha,
                invocation_identity=_v2._json_sha256({"verifier": manifest_sha, "cell_index": index}),
            )
            try:
                def resolve(plan: Any, *, index: int = index, kernel: Any = kernel,
                            cell_terminals: Mapping[tuple[int, int], Any] = cell_terminals) -> Any:
                    key = (index, plan.pair_schedule_position)
                    encountered_pairs.add(key)
                    reservation = reserved.get(key)
                    if reservation is not None:
                        if _v2._canonical_json_bytes(reservation) != _v2._canonical_json_bytes(_coordinates(index, plan)):
                            raise RecoveryCampaignError("recovery reservation differs from recomputed ranking")
                        encountered_reserved.add(key)
                    terminal = cell_terminals.get(key)
                    if terminal is None:
                        raise _MissingTerminal
                    visited_terminals.add(key)
                    runtime_terminal = _v2._runtime_terminal(plan, terminal)
                    kernel.start_pair(plan)
                    kernel.register_terminal(
                        plan=plan, decision_variant="primary",
                        terminal_row=runtime_terminal,
                        variant_evidence=_v2._runtime_evidence(plan, runtime_terminal),
                    )
                    return terminal

                def settled(plan: Any, terminal: Any) -> None:
                    nonlocal verified_terminals
                    verified_terminals += 1

                def committed(commit: Any, *, index: int = index, cell: Any = cell) -> None:
                    nonlocal verified_batches
                    row = _v2._commit_row(cell_index=index, cell_id=cell.cell_id, commit=commit)
                    matches = [key for key in state.batch_commits if key[1:] == (index, commit.time_step)]
                    expected = recorded_commits.get((index, commit.time_step), [])
                    if any(_v2._canonical_json_bytes(state.batch_commits[key]) != _v2._canonical_json_bytes(row) for key in matches):
                        raise RecoveryCampaignError("replayed batch differs from persisted recovery accounting")
                    for key in matches:
                        encountered_commits.add(key)
                    if expected and any(_v2._canonical_json_bytes(item) != _v2._canonical_json_bytes(row) for item in expected):
                        raise RecoveryCampaignError("replayed batch differs from campaign records")
                    recomputed_batches.append(row)
                    verified_batches += 1

                def batch_ready(plans: tuple[Any, ...], *, index: int = index, cell: Any = cell) -> None:
                    from ._concurrent_recovery_parallel_runtime import freeze_work
                    if not plans:
                        return
                    key = index, plans[0].time_step
                    expected = state.parallel_batches.get(key)
                    if expected is None:
                        return
                    work = freeze_work(index, cell, plans)
                    actual = {"cell_index":index,"time_step":key[1],"pairs":[item.reservation() for item in work]}
                    if actual != expected:
                        raise RecoveryCampaignError("Parallel reservation differs from independently rebuilt frozen batch")
                    encountered_parallel_batches.add(key)
                _v2._drive_primary_runtime(kernel, resolve_pair=resolve, pair_settled=settled, batch_committed=committed,
                                          batch_ready=batch_ready if state.parallel_approval is not None else None)
            except _MissingTerminal:
                stopped = True
            finally:
                native_journal.close()
            if stopped and state.model_lane_approval is None:
                break

    _v2._assert_source_unchanged(closure)
    if encountered_parallel_batches != set(state.parallel_batches):
        raise RecoveryCampaignError("Replay did not encounter every frozen parallel batch")
    if visited_terminals != set(terminals) or set(reserved) != encountered_reserved:
        raise RecoveryCampaignError("replay did not encounter the complete terminal and reservation prefix")
    if set(recorded_commits) != {(key[1], key[2]) for key in encountered_commits} or set(state.batch_commits) != encountered_commits:
        raise RecoveryCampaignError("replay did not encounter every persisted batch commit")
    summary = {
        "verified_terminal_count": verified_terminals,
        "verified_reserved_pair_count": len(encountered_reserved),
        "verified_batch_commit_count": verified_batches,
        "provider_calls": 0,
    }
    return _RecoveryReplayFacts(summary=summary, batch_commits=tuple(recomputed_batches))


def verify_recovery_realization(
    *,
    proposal: Mapping[str, Any],
    manifest: _v2.ConcurrentRobustnessManifestV2,
    state: CampaignProgress,
    records: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    """Preserve the historical summary API while hiding recomputed rows."""
    return _verified_recovery_realization(
        proposal=proposal, manifest=manifest, state=state, records=records
    ).summary
