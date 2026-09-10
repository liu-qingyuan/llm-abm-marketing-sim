"""Independent Evidence closure for a complete concurrent recovery bundle.

This module deliberately consumes the private, verified bundle facts and never
calls a Provider.  It is separate from the legacy v2 Evidence contract: the
old failed response is retained as historical attempt evidence, while each
successful sequence is proved independently.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from . import _concurrent_recovery_bundle as _bundle
from . import concurrent_robustness_recovery as _paths
from . import concurrent_robustness_recovery_epoch as _immutable
from . import concurrent_robustness_v2 as _v2
from . import concurrent_robustness_v2_evidence as _v2_evidence
from ._concurrent_recovery_judgment import RecoveryJudgmentV1

RECOVERY_EVIDENCE_SCHEMA = "concurrent-robustness-recovery-evidence-v1"
RECOVERY_EVIDENCE_MANIFEST_SCHEMA = "concurrent-robustness-recovery-evidence-manifest-v1"
_MEMBERSHIP = "membership.json"
_MESSAGES = "messages.jsonl"
_FINAL_JUDGMENTS = "final_judgments.jsonl"
_TERMINALS = "realized_terminals.jsonl"
_ATTEMPTS = "all_attempts.jsonl"
_SELF_CHECKS = "self_checks.jsonl"
_BATCH_COMMITS = "batch_commits.jsonl"
_EVIDENCE = "evidence.json"
_MANIFEST = "artifact_manifest.json"
_INVENTORY = (
    _EVIDENCE, _FINAL_JUDGMENTS, _TERMINALS, _ATTEMPTS, _SELF_CHECKS,
    _BATCH_COMMITS, _MEMBERSHIP, _MESSAGES, _MANIFEST,
)
_PAYLOAD_FILES = tuple(name for name in _INVENTORY if name != _MANIFEST)
_SEGMENTS = {"class_1": "S1", "class_2": "S2", "class_3": "S3"}


class RecoveryEvidenceError(ValueError):
    """The recovery bundle cannot be independently closed as Evidence."""


@dataclass(frozen=True)
class ClosedRecoveryEvidence:
    evidence_path: Path
    manifest: _v2.ConcurrentRobustnessManifestV2
    document: dict[str, Any]
    final_judgments: tuple[dict[str, Any], ...]
    terminals: tuple[_v2._V2RealizedTerminal, ...]
    batch_commits: tuple[dict[str, Any], ...]
    attempts: tuple[dict[str, Any], ...]
    self_checks: tuple[dict[str, Any], ...]
    membership_by_user: dict[str, str]
    messages: tuple[dict[str, Any], ...]


def _json_bytes(value: object) -> bytes:
    return _v2._canonical_json_bytes(value)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def summarize_recovery_attempt_usage(
    attempts: Sequence[_v2._V2AttemptEvidence],
) -> dict[str, Any]:
    """Summarize nullable token usage without turning missing data into zero.

    A token total is known only when every Provider response represented by the
    attempts has complete usage.  Known subtotals remain useful even when the
    total is unknown.  An empty sequence has null totals and zero counters.
    """
    rows = tuple(attempts)
    result: dict[str, Any] = {
        "provider_response_count": sum(row.provider_response_count for row in rows),
        "usage_complete_response_count": sum(row.usage_complete_response_count for row in rows),
        "usage_missing_response_count": sum(row.usage_missing_response_count for row in rows),
        "usage_malformed_response_count": sum(row.usage_malformed_response_count for row in rows),
    }
    complete = (
        result["provider_response_count"] > 0
        and result["usage_complete_response_count"] == result["provider_response_count"]
        and result["usage_missing_response_count"] == 0
        and result["usage_malformed_response_count"] == 0
    )
    for field in ("input_usage", "output_usage", "total_usage", "cached_input_usage"):
        known = [getattr(row, field) for row in rows if getattr(row, field) is not None]
        subtotal = sum(known) if known else None
        result[f"{field}_known_subtotal"] = subtotal
        result[field] = subtotal if complete else None
    return result


def _origin(
    *, kind: str, path: Path, sha256: str, sequence: int, checksum: str,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "file_path": str(path),
        "file_sha256": sha256,
        "event_sequence": sequence,
        "event_checksum": checksum,
    }


def _file_sha(path: Path) -> str:
    _paths._safe_path(path)
    try:
        info = path.lstat()
    except OSError as exc:
        raise RecoveryEvidenceError(f"Evidence origin is unavailable: {path}") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or path.is_symlink():
        raise RecoveryEvidenceError(f"Evidence origin must be a dedicated regular file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inherited_facts(
    proposal: Mapping[str, Any], manifest: _v2.ConcurrentRobustnessManifestV2,
) -> tuple[dict[tuple[int, int], _v2._V2Judgment], dict[tuple[int, int], _v2._V2RealizedTerminal],
           dict[tuple[int, int], dict[str, Any]], dict[tuple[int, int], tuple[_v2._V2AttemptEvidence, ...]],
           dict[tuple[int, int], dict[str, Any]]]:
    """Read each exact old ledger and retain its physical origin metadata."""
    judgments: dict[tuple[int, int], _v2._V2Judgment] = {}
    terminals: dict[tuple[int, int], _v2._V2RealizedTerminal] = {}
    origins: dict[tuple[int, int], dict[str, Any]] = {}
    attempts: dict[tuple[int, int], tuple[_v2._V2AttemptEvidence, ...]] = {}
    failed_origins: dict[tuple[int, int], dict[str, Any]] = {}
    digest = str(proposal["frozen_context"]["manifest_sha256"])
    for raw_cell in proposal["inherited_cells"]:
        index = int(raw_cell["cell_index"])
        cell = manifest.prompt_model_cells[index]
        ledger_path = Path(str(raw_cell["ledger_path"]))
        scope = ledger_path.parent
        identity = _v2._cell_ledger_identity(
            manifest=manifest, manifest_sha256=digest, cell_index=index,
            cell=cell, cell_scope=scope,
        )
        try:
            ledger = _v2._V2PairLedger.read(scope, identity=identity)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise RecoveryEvidenceError("Inherited v2 ledger cannot be independently verified") from exc
        file_sha = _file_sha(ledger.journal_path)
        records = cast(Sequence[Mapping[str, Any]], ledger.records)
        records_by_pair = {
            (int(row["cell_index"]), int(row["pair_schedule_position"])): row
            for row in records
            if row["state"] == "judgment_persisted"
        }
        expected_pairs = {
            (index, int(row["pair_schedule_position"])): row
            for row in raw_cell["inherited_pairs"]
        }
        for judgment in ledger.judgments():
            key = (judgment.cell_index, judgment.pair_schedule_position)
            if key in judgments:
                raise RecoveryEvidenceError("Inherited Judgment is duplicated")
            expected = expected_pairs.get(key)
            if expected is None or expected.get("judgment_id") != judgment.judgment_id or expected.get("pair_id") != judgment.pair_id:
                raise RecoveryEvidenceError("Inherited Judgment differs from the frozen proposal")
            record = records_by_pair.get(key)
            if record is None:
                raise RecoveryEvidenceError("Inherited Judgment origin is missing")
            judgments[key] = judgment
            attempts[key] = judgment.attempt_evidence
            origins[key] = _origin(
                kind="legacy_v2", path=ledger.journal_path, sha256=file_sha,
                sequence=int(record["sequence"]), checksum=str(record["checksum"]),
            )
        for terminal in ledger.terminals():
            key = (terminal.cell_index, terminal.pair_schedule_position)
            if key in terminals:
                raise RecoveryEvidenceError("Inherited terminal is duplicated")
            terminals[key] = terminal
        if set(expected_pairs) != {key for key in judgments if key[0] == index}:
            raise RecoveryEvidenceError("Inherited Judgment inventory differs from the frozen proposal")
        for record in records:
            if record["state"] == "stopped":
                key = (int(record["cell_index"]), int(record["pair_schedule_position"]))
                if key in failed_origins:
                    raise RecoveryEvidenceError("Inherited failed origin is duplicated")
                failed_origins[key] = _origin(
                    kind="legacy_v2", path=ledger.journal_path, sha256=file_sha,
                    sequence=int(record["sequence"]), checksum=str(record["checksum"]),
                )
    return judgments, terminals, origins, attempts, failed_origins


def _event_origins(
    facts: _bundle._VerifiedRecoveryBundleFacts,
) -> tuple[dict[tuple[int, int], dict[int, dict[str, Any]]], dict[tuple[int, int], dict[str, Any]],
           dict[str, dict[str, Any]]]:
    path = facts.bundle_path.parent / "ledger-prefix.jsonl"
    digest = _file_sha(path)
    attempts: dict[tuple[int, int], dict[int, dict[str, Any]]] = {}
    judgments: dict[tuple[int, int], dict[str, Any]] = {}
    checks: dict[str, dict[str, Any]] = {}
    active_key: tuple[int, int] | None = None
    for row in facts.records:
        origin = _origin(
            kind="recovery_v1", path=path, sha256=digest,
            sequence=int(row["sequence"]), checksum=str(row["record_sha256"]),
        )
        payload = row["payload"]
        if row["kind"] == "pair_reserved":
            if not isinstance(payload, Mapping):
                raise RecoveryEvidenceError("Recovery reservation origin is malformed")
            active_key = (int(payload["cell_index"]), int(payload["pair_schedule_position"]))
        elif row["kind"] == "attempt_settled" and isinstance(payload, Mapping) and "attempt" in payload:
            # Formal pair attempt_settled payloads inherit the active reservation;
            # self-check attempts have no reservation and stay in their own audit.
            attempt = payload["attempt"]
            if isinstance(attempt, Mapping) and active_key is not None:
                number = int(attempt["attempt_number"])
                if number in attempts.setdefault(active_key, {}):
                    raise RecoveryEvidenceError("Recovery attempt origin is duplicated")
                attempts[active_key][number] = origin
        elif row["kind"] == "judgment_persisted" and isinstance(payload, Mapping):
            judgment = RecoveryJudgmentV1.model_validate(payload["judgment"])
            key = (judgment.cell_index, judgment.pair.pair_schedule_position)
            if key in judgments:
                raise RecoveryEvidenceError("Recovery Judgment origin is duplicated")
            judgments[key] = origin
        elif row["kind"] == "pair_settled":
            active_key = None
        elif row["kind"] == "self_check_intent" and isinstance(payload, Mapping):
            checks[str(payload["requested_model"])] = {"intent_origin": origin}
        elif row["kind"] == "self_check_recheck_accepted":
            from ._concurrent_recovery_recheck import _checked
            approval = _checked(payload["approval"])
            checks[str(payload["requested_model"]) + "::explicit-recheck"] = {
                "intent_origin": {"kind": "explicit_recheck_v1", **approval["probe_intent"]},
                "result_origin": {"kind": "explicit_recheck_v1", **approval["probe_result"]},
                "acceptance_origin": origin,
                "acceptance_approval": payload["approval"],
            }
        elif row["kind"] == "self_check_settled" and isinstance(payload, Mapping):
            model = str(payload["requested_model"])
            checks.setdefault(model, {})["result_origin"] = origin
    return attempts, judgments, checks


def _serialized_attempt(row: _v2._V2AttemptEvidence) -> dict[str, Any]:
    return row.model_dump(mode="json")


def _final_judgment_row(
    judgment: _v2._V2Judgment | RecoveryJudgmentV1,
    origin: dict[str, Any],
    successful_attempts: Sequence[_v2._V2AttemptEvidence],
) -> dict[str, Any]:
    cell_fields = ("cell_id", "prompt_variant", "prompt_version", "prompt_canonical_hash", "requested_model")
    pair_fields = ("pair_schedule_position", "pair_id", "time_step", "user_id", "message_id")
    if isinstance(judgment, RecoveryJudgmentV1):
        cell = judgment.cell.model_dump(mode="json")
        pair = judgment.pair.model_dump(mode="json")
        decision = judgment.decision
        observed_model = judgment.cell.required_observed_model
    else:
        cell = {field: getattr(judgment, field) for field in cell_fields}
        pair = {field: getattr(judgment, field) for field in pair_fields}
        decision = judgment.decision()
        observed_model = judgment.observed_model
    row = {
        "cell_index": judgment.cell_index,
        "cell_id": cell["cell_id"],
        **{field: pair[field] for field in pair_fields},
        **{field: cell[field] for field in cell_fields if field != "cell_id"},
        "observed_model": observed_model,
        "judgment_id": judgment.judgment_id,
        "provider_engage": decision.engage,
        "provider_probability": decision.probability,
        "provider_reason": decision.reason,
        "provider_confidence": decision.confidence,
        "provider_action": decision.action,
        "origin": origin,
        "successful_attempts": [_serialized_attempt(attempt) for attempt in successful_attempts],
    }
    expected = (
        "cell_index", "cell_id", "pair_schedule_position", "pair_id", "time_step", "user_id", "message_id",
        "prompt_variant", "prompt_version", "prompt_canonical_hash", "requested_model", "observed_model",
        "judgment_id", "provider_engage", "provider_probability", "provider_reason", "provider_confidence",
        "provider_action", "origin", "successful_attempts",
    )
    if tuple(row) != expected:
        raise RecoveryEvidenceError("Final Judgment row contract is crossed")
    return row


def _attempt_row(
    *, cell_index: int, position: int, requested_model: str, prompt_variant: str,
    user_id: str, message_id: str, origin: dict[str, Any], attempt: _v2._V2AttemptEvidence,
) -> dict[str, Any]:
    return {
        "cell_index": cell_index,
        "pair_schedule_position": position,
        "requested_model": requested_model,
        "prompt_variant": prompt_variant,
        "user_id": user_id,
        "message_id": message_id,
        "origin": origin,
        "attempt": _serialized_attempt(attempt),
    }


def _membership_and_messages(
    manifest: _v2.ConcurrentRobustnessManifestV2,
) -> tuple[dict[str, str], tuple[dict[str, Any], ...]]:
    try:
        closure = _v2._close_source(manifest.source.source_dir)
        sample_rows = closure.source_evidence.sample_manifest_rows
        messages = tuple(dict(row) for row in closure.source_evidence.message_snapshot)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RecoveryEvidenceError("Frozen source membership or messages cannot be read") from exc
    membership: dict[str, str] = {}
    for row in sample_rows:
        user_id = row.get("user_id")
        latent = row.get("latent_class")
        if not isinstance(user_id, str) or not user_id or user_id in membership or latent not in _SEGMENTS:
            raise RecoveryEvidenceError("Frozen sample membership is malformed")
        membership[user_id] = _SEGMENTS[latent]
    if len(membership) != manifest.sample.sample_size:
        raise RecoveryEvidenceError("Frozen sample membership denominator is incomplete")
    if tuple(str(row.get("message_id")) for row in messages) != manifest.message_ids:
        raise RecoveryEvidenceError("Frozen messages are crossed with the manifest")
    return membership, messages


def _derive(
    facts: _bundle._VerifiedRecoveryBundleFacts,
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...], tuple[_v2._V2RealizedTerminal, ...],
           tuple[dict[str, Any], ...], tuple[dict[str, Any], ...], dict[str, str], tuple[dict[str, Any], ...]]:
    manifest = facts.origins.source.manifest
    if manifest.source.kind != "formal" or manifest.execution_profile != "formal":
        raise RecoveryEvidenceError("Recovery Evidence requires a real Formal source")
    if manifest.sample.sample_size != 1000 or manifest.ranking_contract.horizon != 30 or manifest.ranking_contract.delivery_capacity != 20:
        raise RecoveryEvidenceError("Recovery Evidence requires the complete 20x1800 topology")
    state = facts.state
    if (
        state.status != "complete" or state.current_model is not None or state.inflight is not None
        or state.reservation is not None or state.pending_judgment is not None or state.pending_realized is not None
        or state.self_check_inflight is not None or state.task_revoked
    ):
        raise RecoveryEvidenceError("Recovery bundle is not a closed campaign")
    if state.failed_key not in state.new_attempts or state.failed_key not in state.judgments:
        raise RecoveryEvidenceError("Recovery failed pair is not successfully closed")
    membership, messages = _membership_and_messages(manifest)
    old_judgments, old_terminals, old_origins, old_attempts, failed_origins = _inherited_facts(facts.origins.proposal, manifest)
    event_attempt_origins, event_judgment_origins, event_check_origins = _event_origins(facts)
    new_judgments = {key: RecoveryJudgmentV1.model_validate(value) for key, value in state.judgments.items()}
    if set(old_judgments) & set(new_judgments):
        raise RecoveryEvidenceError("Inherited and recovery Judgment keys overlap")
    final_by_key: dict[tuple[int, int], dict[str, Any]] = {}
    all_attempt_rows: list[dict[str, Any]] = []
    all_attempt_models: list[_v2._V2AttemptEvidence] = []
    successful_sequence: list[_v2._V2AttemptEvidence] = []
    inherited_physical = 0
    new_physical = 0
    for key, judgment in old_judgments.items():
        origin = old_origins[key]
        final_by_key[key] = _final_judgment_row(judgment, origin, old_attempts[key])
        successful_sequence.extend(old_attempts[key])
        cell = manifest.prompt_model_cells[key[0]]
        for attempt in old_attempts[key]:
            all_attempt_rows.append(_attempt_row(
                cell_index=key[0], position=key[1], requested_model=cell.requested_model,
                prompt_variant=cell.prompt_variant, user_id=judgment.user_id, message_id=judgment.message_id,
                origin=origin, attempt=attempt,
            ))
            all_attempt_models.append(attempt)
            inherited_physical += 1
    failure = facts.origins.proposal["failed_pair"]
    failed_key = (int(failure["cell_index"]), int(failure["pair_schedule_position"]))
    if set(failed_origins) != {failed_key}:
        raise RecoveryEvidenceError("Recovery requires exactly one original failed pair")
    failed_origin = failed_origins[failed_key]
    if (
        failed_origin["event_sequence"] != failure.get("stopped_record_sequence")
        or failed_origin["event_checksum"] != failure.get("stopped_record_sha256")
    ):
        raise RecoveryEvidenceError("Original failed attempt origin differs from the frozen proposal")
    # The failed response is represented once, separately from the recovery Judgment's
    # historical_attempts field (which is not traversed a second time).
    failed_attempts = tuple(_v2._V2AttemptEvidence.model_validate(row) for row in failure["attempt_evidence"])
    failed_cell = manifest.prompt_model_cells[failed_key[0]]
    for attempt in failed_attempts:
        all_attempt_rows.append(_attempt_row(
            cell_index=failed_key[0], position=failed_key[1], requested_model=failed_cell.requested_model,
            prompt_variant=failed_cell.prompt_variant, user_id=str(failure["user_id"]), message_id=str(failure["message_id"]),
            origin=failed_origins[failed_key], attempt=attempt,
        ))
        all_attempt_models.append(attempt)
        inherited_physical += 1
    expected_new_attempt_origins = {
        (key, attempt.attempt_number)
        for key, judgment in new_judgments.items()
        for attempt in judgment.new_attempts
    }
    actual_new_attempt_origins = {
        (key, number)
        for key, by_number in event_attempt_origins.items()
        for number in by_number
    }
    if actual_new_attempt_origins != expected_new_attempt_origins or set(event_judgment_origins) != set(new_judgments):
        raise RecoveryEvidenceError("Recovery event origin inventory is crossed")
    for key, judgment in new_judgments.items():
        if key not in event_judgment_origins:
            raise RecoveryEvidenceError("Recovery Judgment origin is missing")
        if key == failed_key and tuple(judgment.historical_attempts) != failed_attempts:
            raise RecoveryEvidenceError("Recovery history is not bound to the original failed response")
        cell = manifest.prompt_model_cells[key[0]]
        new = tuple(judgment.new_attempts)
        successful_sequence.extend(new)
        final_by_key[key] = _final_judgment_row(judgment, event_judgment_origins[key], new)
        for attempt in new:
            origin = event_attempt_origins.get(key, {}).get(attempt.attempt_number)
            if origin is None:
                raise RecoveryEvidenceError("Recovery physical attempt origin is missing")
            all_attempt_rows.append(_attempt_row(
                cell_index=key[0], position=key[1], requested_model=cell.requested_model,
                prompt_variant=cell.prompt_variant, user_id=judgment.pair.user_id,
                message_id=judgment.pair.message_id, origin=origin, attempt=attempt,
            ))
            all_attempt_models.append(attempt)
            new_physical += 1
    expected_keys = {(i, p) for i in range(20) for p in range(1800)}
    if set(final_by_key) != expected_keys:
        raise RecoveryEvidenceError("Recovery final Judgment denominator is incomplete")
    attempts_keys = [(row["cell_index"], row["pair_schedule_position"], row["attempt"]["attempt_number"]) for row in all_attempt_rows]
    if len(attempts_keys) != len(set(attempts_keys)) or any(number > 3 for _, _, number in attempts_keys):
        raise RecoveryEvidenceError("Recovery physical attempt union is duplicated or exceeds its cap")
    final_judgments = tuple(final_by_key[key] for key in sorted(final_by_key))
    terminals_by_key = dict(old_terminals)
    for key, judgment in new_judgments.items():
        terminals_by_key[key] = judgment.realized_projection(
            realization_source_identity=manifest.realization_source.source_identity,
        )
    if set(terminals_by_key) != expected_keys:
        raise RecoveryEvidenceError("Recovery terminal denominator is incomplete")
    terminals = tuple(terminals_by_key[key] for key in sorted(terminals_by_key))
    # Bundle verification has already run the shared kernel replay and exposed
    # its recomputed commit rows as private facts; do not implement or run a
    # second scheduler here.
    batch_commits = facts.batch_commits
    if len(batch_commits) != 600 or len(terminals) != 36000:
        raise RecoveryEvidenceError("Recovery batch barrier denominator is incomplete")
    self_checks: list[dict[str, Any]] = []
    for model in sorted(state.self_checks, key=lambda value: tuple(_v2._V2_MODELS).index(value)):
        payload = state.self_checks[model]
        attempt = _v2._V2AttemptEvidence.model_validate(payload["attempt"])
        origins = event_check_origins.get(model)
        if origins is None or set(origins) != {"intent_origin", "result_origin"}:
            raise RecoveryEvidenceError("Self-check intent/result origins are incomplete")
        self_checks.append({
            "requested_model": model, "attempt": _serialized_attempt(attempt),
            "decision": payload["decision"], **origins,
        })
    for model, payload in state.accepted_rechecks.items():
        origins = event_check_origins.get(model + "::explicit-recheck")
        if origins is None:
            raise RecoveryEvidenceError("Explicit recheck origins are incomplete")
        self_checks.append({"requested_model": model,
            "attempt": _serialized_attempt(_v2._V2AttemptEvidence.model_validate(payload["attempt"])),
            "decision": payload["decision"], **origins})
    self_check_attempts = len(self_checks)
    all_usage = summarize_recovery_attempt_usage(all_attempt_models)
    successful_usage = summarize_recovery_attempt_usage(successful_sequence)
    if (inherited_physical + new_physical != len(all_attempt_rows)
            or new_physical != state.physical_attempts
            or len(all_attempt_rows) != facts.document["progress"]["physical_attempts"]):
        raise RecoveryEvidenceError("Recovery physical attempt union differs from the cumulative ledger")
    if (successful_usage["usage_complete_response_count"] != successful_usage["provider_response_count"]
            or successful_usage["usage_missing_response_count"] or successful_usage["usage_malformed_response_count"]
            or any(successful_usage[field] is None for field in ("input_usage", "output_usage", "total_usage"))):
        raise RecoveryEvidenceError("Final successful sequences require complete usage")
    document = {
        "schema_version": RECOVERY_EVIDENCE_SCHEMA,
        "evidence_path": "",
        "source_bundle": {},
        "manifest_sha256": _sha256_bytes(_v2._manifest_bytes(manifest)),
        "counts": {
            "cells": 20, "logical_judgments": 36000, "physical_attempts": len(all_attempt_rows),
            "inherited_successes": len(old_judgments), "inherited_physical_attempts": inherited_physical,
            "new_physical_attempts": new_physical, "self_check_attempts": self_check_attempts,
            "batch_commits": len(batch_commits),
        },
        "all_attempt_usage": all_usage,
        "successful_sequence_usage": successful_usage,
        "fees": _v2_evidence._fee_summary(all_attempt_models),
        "formal_evidence_closed": True,
        "production_deploy_eligible": False,
        "provider_calls_during_composition": 0,
        "artifacts": {"final_judgments": _FINAL_JUDGMENTS, "realized_terminals": _TERMINALS,
                      "all_attempts": _ATTEMPTS, "self_checks": _SELF_CHECKS, "batch_commits": _BATCH_COMMITS,
                      "membership": _MEMBERSHIP, "messages": _MESSAGES, "manifest": _MANIFEST},
    }
    return document, final_judgments, terminals, tuple(all_attempt_rows), tuple(self_checks), membership, messages


def _set_identity(document: dict[str, Any], target: Path, bundle_path: Path) -> dict[str, Any]:
    result = dict(document)
    result["evidence_path"] = str(target)
    result["source_bundle"] = {"path": str(bundle_path), "sha256": _file_sha(bundle_path)}
    result["output_identity"] = _sha256_bytes(_json_bytes({
        "schema_version": RECOVERY_EVIDENCE_SCHEMA, "evidence_path": str(target),
        "source_bundle_sha256": result["source_bundle"]["sha256"],
    }))
    return result


def _payloads(
    closed: tuple[dict[str, Any], tuple[dict[str, Any], ...], tuple[_v2._V2RealizedTerminal, ...],
                 tuple[dict[str, Any], ...], tuple[dict[str, Any], ...], dict[str, str], tuple[dict[str, Any], ...]],
    batch_commits: Sequence[dict[str, Any]],
) -> dict[str, bytes]:
    document, final, terminals, attempts, checks, membership, messages = closed
    return {
        _EVIDENCE: _json_bytes(document),
        _FINAL_JUDGMENTS: b"".join(_json_bytes(row) for row in final),
        _TERMINALS: b"".join(_json_bytes(row.model_dump(mode="json")) for row in terminals),
        _ATTEMPTS: b"".join(_json_bytes(row) for row in attempts),
        _SELF_CHECKS: b"".join(_json_bytes(row) for row in checks),
        _BATCH_COMMITS: b"".join(_json_bytes(row) for row in batch_commits),
        _MEMBERSHIP: _json_bytes({"schema_version": "concurrent-robustness-recovery-membership-v1", "membership_by_user": membership}),
        _MESSAGES: b"".join(_json_bytes(row) for row in messages),
    }


def _safe_output_dir(path: str | Path) -> Path:
    target = _paths._safe_path(path)
    if any(parent.is_symlink() for parent in (target, *target.parents)):
        raise RecoveryEvidenceError("Evidence output paths cannot contain symlinks")
    if target.exists() and (target.is_symlink() or not target.is_dir()):
        raise RecoveryEvidenceError("Evidence output must be a real directory")
    if target.parent.exists():
        if target.parent.is_symlink() or not target.parent.is_dir():
            raise RecoveryEvidenceError("Evidence output parent must be a real directory")
    elif not target.parent.parent.is_dir() or target.parent.parent.is_symlink():
        raise RecoveryEvidenceError(
            "Evidence output may create only one missing immediate parent"
        )
    return target


def _protected_output(target: Path, facts: _bundle._VerifiedRecoveryBundleFacts) -> None:
    proposal = facts.origins.proposal
    protected = {Path(facts.origins.campaign["control_root"]), Path(facts.origins.campaign["source_anchor_path"]),
                 Path(facts.origins.source.manifest.source.source_dir)}
    for name in ("source_output_root", "output_root"):
        if isinstance(proposal.get(name), str):
            protected.add(Path(proposal[name]))
    protected.update(Path(row["path"]) for row in proposal["source_artifacts"])
    protected.update(Path(row["path"]) for row in facts.document["artifact_facts"])
    for row in proposal["inherited_cells"]:
        for name in ("ledger_path", "runtime_workspace"):
            if isinstance(row.get(name), str):
                protected.add(Path(row[name]))
    for path in protected:
        absolute = Path(os.path.abspath(path))
        if target == absolute or target.is_relative_to(absolute) or absolute.is_relative_to(target):
            raise RecoveryEvidenceError("Evidence output overlaps a protected source or campaign path")


def _write_immutable(path: Path, payload: bytes) -> None:
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444)
    except OSError as exc:
        raise RecoveryEvidenceError(f"Evidence output collision: {path}") from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        path.chmod(0o444)
    except Exception:
        raise


def _read_json(path: Path, label: str) -> dict[str, Any]:
    _paths._safe_path(path)
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mode & 0o222:
            raise RecoveryEvidenceError(f"{label} is not immutable canonical JSON")
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecoveryEvidenceError(f"{label} is malformed") from exc
    if not isinstance(value, dict) or raw != _json_bytes(value):
        raise RecoveryEvidenceError(f"{label} is not immutable canonical JSON")
    return value


def _read_jsonl(path: Path, label: str) -> tuple[dict[str, Any], ...]:
    _paths._safe_path(path)
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mode & 0o222:
            raise RecoveryEvidenceError(f"{label} is not immutable")
        raw_rows = path.read_bytes().splitlines(keepends=True)
    except OSError as exc:
        raise RecoveryEvidenceError(f"{label} is unavailable") from exc
    rows: list[dict[str, Any]] = []
    for raw in raw_rows:
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RecoveryEvidenceError(f"{label} is malformed") from exc
        if not isinstance(value, dict) or raw != _json_bytes(value):
            raise RecoveryEvidenceError(f"{label} is not canonical JSONL")
        rows.append(value)
    return tuple(rows)


def _manifest_document(document: Mapping[str, Any], payloads: Mapping[str, bytes], manifest: _v2.ConcurrentRobustnessManifestV2) -> dict[str, Any]:
    return {
        "schema_version": RECOVERY_EVIDENCE_MANIFEST_SCHEMA,
        "evidence_path": document["evidence_path"], "output_identity": document["output_identity"],
        "source_bundle": document["source_bundle"], "study_manifest": manifest.model_dump(mode="json"),
        "inventory": {name: {"sha256": _sha256_bytes(body), "bytes": len(body)} for name, body in payloads.items()},
        "formal_evidence_closed": True, "production_deploy_eligible": False,
        "provider_calls_during_composition": 0,
    }


def _build_closed(
    evidence_path: Path,
) -> ClosedRecoveryEvidence:
    manifest_doc = _read_json(evidence_path.parent / _MANIFEST, "Evidence manifest")
    if manifest_doc.get("schema_version") != RECOVERY_EVIDENCE_MANIFEST_SCHEMA or manifest_doc.get("evidence_path") != str(evidence_path):
        raise RecoveryEvidenceError("Evidence closure manifest identity is crossed")
    if not isinstance(manifest_doc.get("inventory"), Mapping) or set(manifest_doc["inventory"]) != set(_PAYLOAD_FILES):
        raise RecoveryEvidenceError("Evidence closure inventory is incomplete")
    for name, fact in manifest_doc["inventory"].items():
        path = evidence_path.parent / name
        if not isinstance(fact, Mapping) or _file_sha(path) != fact.get("sha256") or path.stat().st_size != fact.get("bytes"):
            raise RecoveryEvidenceError("Evidence artifact hash or size is crossed")
    document = _read_json(evidence_path, "Evidence document")
    source = document.get("source_bundle")
    if not isinstance(source, Mapping) or not isinstance(source.get("path"), str):
        raise RecoveryEvidenceError("Evidence source bundle binding is missing")
    bundle = Path(source["path"])
    if _file_sha(bundle) != source.get("sha256"):
        raise RecoveryEvidenceError("Evidence source bundle changed")
    try:
        facts = _bundle._read_verified_recovery_bundle(bundle)
    except Exception as exc:
        raise RecoveryEvidenceError("Evidence source bundle is not independently verifiable") from exc
    _protected_output(evidence_path.parent, facts)
    if facts.origins.source.manifest.model_dump(mode="json") != manifest_doc.get("study_manifest"):
        raise RecoveryEvidenceError("Evidence study manifest is crossed")
    if (
        manifest_doc.get("output_identity") != document.get("output_identity")
        or manifest_doc.get("source_bundle") != document.get("source_bundle")
        or manifest_doc.get("formal_evidence_closed") is not True
        or manifest_doc.get("production_deploy_eligible") is not False
        or manifest_doc.get("provider_calls_during_composition") != 0
    ):
        raise RecoveryEvidenceError("Evidence closure metadata is crossed")
    try:
        derived = _derive(facts)
    except RecoveryEvidenceError:
        raise
    except Exception as exc:
        raise RecoveryEvidenceError("Recovery facts cannot be independently reconstructed") from exc
    expected_document = _set_identity(derived[0], evidence_path, bundle)
    expected_payloads = _payloads((expected_document, *derived[1:]), facts.batch_commits)
    if (document != expected_document
            or manifest_doc != _manifest_document(expected_document, expected_payloads, facts.origins.source.manifest)):
        raise RecoveryEvidenceError("Evidence document or manifest is not independently reconstructed")
    actual_rows = {
        _FINAL_JUDGMENTS: _read_jsonl(evidence_path.parent / _FINAL_JUDGMENTS, _FINAL_JUDGMENTS),
        _TERMINALS: _read_jsonl(evidence_path.parent / _TERMINALS, _TERMINALS),
        _ATTEMPTS: _read_jsonl(evidence_path.parent / _ATTEMPTS, _ATTEMPTS),
        _SELF_CHECKS: _read_jsonl(evidence_path.parent / _SELF_CHECKS, _SELF_CHECKS),
        _BATCH_COMMITS: _read_jsonl(evidence_path.parent / _BATCH_COMMITS, _BATCH_COMMITS),
        _MESSAGES: _read_jsonl(evidence_path.parent / _MESSAGES, _MESSAGES),
    }
    membership_doc = _read_json(evidence_path.parent / _MEMBERSHIP, _MEMBERSHIP)
    expected_membership = {"schema_version": "concurrent-robustness-recovery-membership-v1", "membership_by_user": derived[5]}
    if membership_doc != expected_membership:
        raise RecoveryEvidenceError("Evidence membership is crossed")
    expected_rows = {
        _FINAL_JUDGMENTS: tuple(derived[1]), _TERMINALS: tuple(row.model_dump(mode="json") for row in derived[2]),
        _ATTEMPTS: tuple(derived[3]), _SELF_CHECKS: tuple(derived[4]), _BATCH_COMMITS: tuple(facts.batch_commits),
        _MESSAGES: tuple(derived[6]),
    }
    if any(actual_rows[name] != expected_rows[name] for name in actual_rows):
        raise RecoveryEvidenceError("Evidence payload is not independently reconstructed")
    inventory = manifest_doc["inventory"]
    for name, payload in expected_payloads.items():
        if _sha256_bytes(payload) != inventory[name]["sha256"]:
            raise RecoveryEvidenceError("Evidence payload bytes are not closed")
    return ClosedRecoveryEvidence(
        evidence_path=evidence_path, manifest=facts.origins.source.manifest, document=document,
        final_judgments=tuple(derived[1]), terminals=tuple(derived[2]), batch_commits=tuple(facts.batch_commits),
        attempts=tuple(derived[3]), self_checks=tuple(derived[4]), membership_by_user=dict(derived[5]),
        messages=tuple(derived[6]),
    )


def close_concurrent_robustness_recovery_evidence(
    bundle_path: str | Path, *, output_dir: str | Path,
) -> Path:
    """Close and atomically publish an immutable recovery Evidence root."""
    try:
        facts = _bundle._read_verified_recovery_bundle(bundle_path)
    except Exception as exc:
        raise RecoveryEvidenceError("Recovery bundle is not independently verifiable") from exc
    target_dir = _safe_output_dir(output_dir)
    _protected_output(target_dir, facts)
    evidence_path = target_dir / _EVIDENCE
    if target_dir.exists():
        if {path.name for path in target_dir.iterdir()} != set(_INVENTORY):
            raise RecoveryEvidenceError("Incomplete or foreign Evidence output cannot be repaired")
        closed = read_concurrent_robustness_recovery_evidence(evidence_path)
        if closed.document["source_bundle"] != {"path": str(facts.bundle_path), "sha256": _file_sha(facts.bundle_path)}:
            raise RecoveryEvidenceError("Existing Evidence belongs to a different explicit bundle")
        return closed.evidence_path
    # Complete the frozen-source and protected-path preflight before creating
    # either the optional report workspace parent or the Evidence child.
    try:
        derived = _derive(facts)
    except RecoveryEvidenceError:
        raise
    except Exception as exc:
        raise RecoveryEvidenceError("Recovery facts cannot be independently reconstructed") from exc
    if not target_dir.parent.exists():
        try:
            target_dir.parent.mkdir(mode=0o755)
        except OSError as exc:
            raise RecoveryEvidenceError("Evidence output parent could not be created") from exc
    try:
        target_dir.mkdir(mode=0o755)
    except OSError as exc:
        raise RecoveryEvidenceError("Evidence output root could not be created") from exc
    document = _set_identity(derived[0], evidence_path, facts.bundle_path)
    payloads = _payloads((document, *derived[1:]), facts.batch_commits)
    for name in _PAYLOAD_FILES:
        _write_immutable(target_dir / name, payloads[name])
    closure_manifest = _manifest_document(document, payloads, facts.origins.source.manifest)
    _immutable._publish_immutable(target_dir / _MANIFEST, closure_manifest)
    _v2._fsync_directory(target_dir)
    return read_concurrent_robustness_recovery_evidence(evidence_path).evidence_path


def read_concurrent_robustness_recovery_evidence(
    evidence_path: str | Path,
) -> ClosedRecoveryEvidence:
    """Independently reconstruct a previously published Evidence root."""
    path = Path(os.path.abspath(os.fspath(evidence_path)))
    if path.name != _EVIDENCE or any(parent.is_symlink() for parent in (path, *path.parents)):
        raise RecoveryEvidenceError("Evidence path must be an exact regular path")
    try:
        info = path.lstat()
    except OSError as exc:
        raise RecoveryEvidenceError("Evidence path does not exist") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or path.is_symlink():
        raise RecoveryEvidenceError("Evidence path must be a dedicated regular file")
    if {child.name for child in path.parent.iterdir()} != set(_INVENTORY):
        raise RecoveryEvidenceError("Evidence inventory is incomplete or foreign")
    return _build_closed(path)


__all__ = [
    "ClosedRecoveryEvidence", "RecoveryEvidenceError",
    "close_concurrent_robustness_recovery_evidence",
    "read_concurrent_robustness_recovery_evidence",
    "summarize_recovery_attempt_usage",
]
