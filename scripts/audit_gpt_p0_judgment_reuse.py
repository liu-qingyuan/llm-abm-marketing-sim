from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, NoReturn

from llm_abm_sim import concurrent_robustness_v2 as _v2
from llm_abm_sim._concurrent_recovery_bundle import _read_verified_recovery_bundle
from llm_abm_sim._concurrent_recovery_judgment import RecoveryJudgmentV1
from llm_abm_sim._concurrent_recovery_runtime import _coordinates, _kernel
from llm_abm_sim.decision import decision_profile_payload
from llm_abm_sim.prompting import build_engagement_prompt
from llm_abm_sim.providers.robustness import PiOpenAIDecisionAdapter, robustness_provider_disclosures

AUDIT_SCHEMA = "gpt-p0-judgment-reuse-audit-v1"
CHECKLIST_SCHEMA = "gpt-p0-judgment-reuse-checklist-v1"
MANIFEST_SCHEMA = "gpt-p0-judgment-reuse-audit-manifest-v1"
TARGET_MODEL = "openai-codex/gpt-5.6-sol"
TARGET_OBSERVED_MODEL = "gpt-5.6-sol"
TARGET_PROMPT_VARIANT = "P0"
EXPECTED_EVIDENCE_SHA256 = "a7407bf355d6049af8667a69b540fe2b29591d7f8e7ef71d6cb08d01fee72b17"
EXPECTED_PLAN_SHA256 = "2d64026ce755a5a5c3e8dd42f6c74add7dc1435b42adef3cbc47dac030da9b16"
OMITTED_PARAMETERS = ("temperature", "top_p", "seed")
UNDETERMINED_REASON_CODES = (
    "target_collection_contract_not_frozen",
    "original_client_payload_digest_not_persisted",
    "effective_upstream_context_and_service_snapshot_unobservable",
)
RELEVANT_IMPLEMENTATION_PATHS = (
    "scripts/pi_subscription_provider_worker.mjs",
    "src/llm_abm_sim/_concurrent_recovery_bundle.py",
    "src/llm_abm_sim/_concurrent_recovery_judgment.py",
    "src/llm_abm_sim/_concurrent_recovery_progress.py",
    "src/llm_abm_sim/_concurrent_recovery_replay.py",
    "src/llm_abm_sim/_concurrent_recovery_runtime.py",
    "src/llm_abm_sim/concurrent_message_experiment.py",
    "src/llm_abm_sim/concurrent_robustness_v2.py",
    "src/llm_abm_sim/decision.py",
    "src/llm_abm_sim/prompt_contracts.py",
    "src/llm_abm_sim/prompt_field_summary.py",
    "src/llm_abm_sim/prompting.py",
    "src/llm_abm_sim/providers/pi_subscription.py",
    "src/llm_abm_sim/providers/robustness.py",
)


class AuditError(RuntimeError):
    """Fail closed when the pinned evidence cannot support the audit."""


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_sha256(value: object) -> str:
    return _sha256_bytes(_canonical_json_bytes(value))


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditError(f"cannot read canonical JSON input: {path}") from exc
    if not isinstance(value, dict):
        raise AuditError(f"expected a JSON object: {path}")
    return value


def _require_regular_file(path: Path, *, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if path.is_symlink() or not resolved.is_file():
        raise AuditError(f"{label} must be a regular non-symlink file: {path}")
    return resolved


def _require_sha256(path: Path, expected: str, *, label: str) -> None:
    actual = _sha256_file(path)
    if actual != expected:
        raise AuditError(f"{label} SHA-256 mismatch: {actual} != {expected}")


def _require_exact(value: object, expected: object, *, label: str) -> None:
    if _canonical_json_bytes(value) != _canonical_json_bytes(expected):
        raise AuditError(f"{label} differs from the pinned evidence")


def _artifact_paths(evidence_root: Path, names: Iterable[str]) -> dict[str, Path]:
    manifest_path = _require_regular_file(evidence_root / "artifact_manifest.json", label="evidence artifact manifest")
    manifest = _read_json(manifest_path)
    rows = manifest.get("artifacts")
    if not isinstance(rows, list):
        raise AuditError("evidence artifact manifest lacks its artifacts list")
    by_name: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("path"), str):
            raise AuditError("evidence artifact manifest contains a malformed row")
        name = Path(row["path"]).name
        if name in by_name:
            raise AuditError(f"evidence artifact manifest repeats {name}")
        by_name[name] = row
    result: dict[str, Path] = {}
    for name in names:
        row = by_name.get(name)
        if row is None:
            raise AuditError(f"evidence artifact manifest omits {name}")
        path = _require_regular_file(evidence_root / name, label=f"evidence artifact {name}")
        if Path(str(row["path"])).resolve() != path:
            raise AuditError(f"evidence artifact path is crossed for {name}")
        if row.get("bytes") != path.stat().st_size or row.get("sha256") != _sha256_file(path):
            raise AuditError(f"evidence artifact bytes or SHA-256 differ for {name}")
        result[name] = path
    result["artifact_manifest.json"] = manifest_path
    return result


def _git_bytes(repository_root: Path, commit: str, relative_path: str) -> bytes:
    process = subprocess.run(
        ["git", "show", f"{commit}:{relative_path}"],
        cwd=repository_root,
        check=False,
        capture_output=True,
    )
    if process.returncode != 0:
        raise AuditError(f"cannot read {relative_path} from implementation commit {commit}")
    return process.stdout


def _verify_implementation(repository_root: Path, commit: str) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for relative_path in RELEVANT_IMPLEMENTATION_PATHS:
        working_path = _require_regular_file(repository_root / relative_path, label="audit-relevant implementation")
        committed = _git_bytes(repository_root, commit, relative_path)
        working = working_path.read_bytes()
        if committed != working:
            raise AuditError(
                f"audit-relevant implementation drifted from recorded commit {commit}: {relative_path}"
            )
        result.append(
            {
                "relative_path": relative_path,
                "sha256": _sha256_bytes(working),
                "matches_recorded_commit": True,
            }
        )
    return result


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AuditError(f"malformed JSONL at {path}:{line_number}") from exc
            if not isinstance(value, dict):
                raise AuditError(f"non-object JSONL row at {path}:{line_number}")
            yield value


def _origin_event(
    origin: Mapping[str, Any],
    *,
    records_by_sequence: Mapping[int, Mapping[str, Any]],
    ledger_path: Path,
    ledger_sha256: str,
    allowed_kinds: set[str],
) -> Mapping[str, Any]:
    expected_fields = {"event_checksum", "event_sequence", "file_path", "file_sha256", "kind"}
    if set(origin) != expected_fields or origin.get("kind") != "recovery_v1":
        raise AuditError("final row has a malformed recovery origin")
    if Path(str(origin["file_path"])).resolve() != ledger_path or origin["file_sha256"] != ledger_sha256:
        raise AuditError("final row is crossed with another recovery ledger")
    sequence = origin.get("event_sequence")
    if type(sequence) is not int or sequence not in records_by_sequence:
        raise AuditError("final row refers to a missing recovery event")
    event = records_by_sequence[sequence]
    if event.get("kind") not in allowed_kinds or event.get("record_sha256") != origin.get("event_checksum"):
        raise AuditError("final row event kind or checksum differs from its origin")
    return event


def _expected_final_judgment(
    judgment: RecoveryJudgmentV1,
    *,
    origin: Mapping[str, Any],
) -> dict[str, Any]:
    attempts = (*judgment.historical_attempts, *judgment.new_attempts)
    return {
        "cell_id": judgment.cell.cell_id,
        "cell_index": judgment.cell_index,
        "judgment_id": judgment.judgment_id,
        "message_id": judgment.pair.message_id,
        "observed_model": judgment.observed_model,
        "origin": dict(origin),
        "pair_id": judgment.pair.pair_id,
        "pair_schedule_position": judgment.pair.pair_schedule_position,
        "prompt_canonical_hash": judgment.cell.prompt_canonical_hash,
        "prompt_variant": judgment.cell.prompt_variant,
        "prompt_version": judgment.cell.prompt_version,
        "provider_action": judgment.decision.action,
        "provider_confidence": judgment.decision.confidence,
        "provider_engage": judgment.decision.engage,
        "provider_probability": judgment.decision.probability,
        "provider_reason": judgment.decision.reason,
        "requested_model": judgment.cell.requested_model,
        "successful_attempts": [row.model_dump(mode="json") for row in attempts],
        "time_step": judgment.pair.time_step,
        "user_id": judgment.pair.user_id,
    }


def _validate_final_projection(
    *,
    artifacts: Mapping[str, Path],
    target_cell_index: int,
    judgments_by_position: Mapping[int, RecoveryJudgmentV1],
    records_by_sequence: Mapping[int, Mapping[str, Any]],
    ledger_path: Path,
    ledger_sha256: str,
    realization_source_identity: str,
    replay_batch_commits: tuple[dict[str, Any], ...],
) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[tuple[int, int], dict[str, Any]], dict[str, int]]:
    final_judgments = [
        row for row in _iter_jsonl(artifacts["judgments.jsonl"]) if row.get("cell_index") == target_cell_index
    ]
    if len(final_judgments) != len(judgments_by_position):
        raise AuditError("final GPT-P0 Judgment count differs from the recovered ledger")

    pair_rows: dict[tuple[str, str], dict[str, Any]] = {}
    judgment_rows_by_position: dict[int, dict[str, Any]] = {}
    for row in final_judgments:
        position = row.get("pair_schedule_position")
        if type(position) is not int or position not in judgments_by_position:
            raise AuditError("final GPT-P0 Judgment has an unknown schedule position")
        judgment = judgments_by_position[position]
        origin = row.get("origin")
        if not isinstance(origin, Mapping):
            raise AuditError("final GPT-P0 Judgment lacks its recovery origin")
        event = _origin_event(
            origin,
            records_by_sequence=records_by_sequence,
            ledger_path=ledger_path,
            ledger_sha256=ledger_sha256,
            allowed_kinds={"judgment_persisted"},
        )
        _require_exact(event.get("payload"), {"judgment": judgment.model_dump(mode="json")}, label="Judgment event")
        _require_exact(row, _expected_final_judgment(judgment, origin=origin), label="final Judgment projection")
        pair_key = (judgment.pair.user_id, judgment.pair.message_id)
        if pair_key in pair_rows or position in judgment_rows_by_position:
            raise AuditError("final GPT-P0 Judgment inventory contains a duplicate pair or position")
        pair_rows[pair_key] = row
        judgment_rows_by_position[position] = row

    attempts_by_key: dict[tuple[int, int], dict[str, Any]] = {}
    attempt_outcomes: Counter[str] = Counter()
    for row in _iter_jsonl(artifacts["attempts.jsonl"]):
        if row.get("cell_index") != target_cell_index:
            continue
        position = row.get("pair_schedule_position")
        attempt_number = row.get("attempt_number")
        if type(position) is not int or type(attempt_number) is not int:
            raise AuditError("final GPT-P0 attempt has malformed coordinates")
        key = (position, attempt_number)
        if key in attempts_by_key:
            raise AuditError("final GPT-P0 attempt inventory contains a duplicate")
        judgment = judgments_by_position.get(position)
        if judgment is None:
            raise AuditError("final GPT-P0 attempt does not belong to a Judgment")
        expected_attempts = (*judgment.historical_attempts, *judgment.new_attempts)
        expected = next((item for item in expected_attempts if item.attempt_number == attempt_number), None)
        if expected is None:
            raise AuditError("final GPT-P0 attempt ordinal is absent from its Judgment")
        origin = row.get("origin")
        if not isinstance(origin, Mapping):
            raise AuditError("final GPT-P0 attempt lacks its recovery origin")
        event = _origin_event(
            origin,
            records_by_sequence=records_by_sequence,
            ledger_path=ledger_path,
            ledger_sha256=ledger_sha256,
            allowed_kinds={"attempt_settled"},
        )
        expected_decision = (
            judgment.decision.model_dump(mode="json") if expected.outcome == "succeeded" else None
        )
        _require_exact(
            event.get("payload"),
            {"attempt": expected.model_dump(mode="json"), "decision": expected_decision},
            label="settled attempt event",
        )
        _require_exact(
            row,
            {
                "attempt": expected.model_dump(mode="json"),
                "attempt_number": attempt_number,
                "cell_index": target_cell_index,
                "kind": "settled_attempt",
                "origin": dict(origin),
                "pair_schedule_position": position,
                "requested_model": TARGET_MODEL,
            },
            label="final settled attempt projection",
        )
        attempts_by_key[key] = row
        attempt_outcomes[expected.outcome] += 1

    expected_attempt_count = sum(
        len(judgment.historical_attempts) + len(judgment.new_attempts)
        for judgment in judgments_by_position.values()
    )
    if len(attempts_by_key) != expected_attempt_count:
        raise AuditError("final GPT-P0 attempt inventory is incomplete")

    final_terminals = [
        row for row in _iter_jsonl(artifacts["realized_terminals.jsonl"]) if row.get("cell_index") == target_cell_index
    ]
    terminals_by_position: dict[int, dict[str, Any]] = {}
    for row in final_terminals:
        position = row.get("pair_schedule_position")
        if type(position) is not int or position not in judgments_by_position or position in terminals_by_position:
            raise AuditError("final GPT-P0 terminal inventory is crossed or duplicated")
        expected = judgments_by_position[position].realized_projection(
            realization_source_identity=realization_source_identity
        ).model_dump(mode="json")
        _require_exact(row, expected, label="final Realized terminal projection")
        terminals_by_position[position] = row
    if len(terminals_by_position) != len(judgments_by_position):
        raise AuditError("final GPT-P0 Realized terminal inventory is incomplete")

    final_commits = [
        row for row in _iter_jsonl(artifacts["batch_commits.jsonl"]) if row.get("cell_index") == target_cell_index
    ]
    expected_commits = [row for row in replay_batch_commits if row.get("cell_index") == target_cell_index]
    final_commits.sort(key=lambda row: int(row["time_step"]))
    expected_commits.sort(key=lambda row: int(row["time_step"]))
    _require_exact(final_commits, expected_commits, label="final GPT-P0 batch commits")

    return pair_rows, attempts_by_key, {
        "judgments": len(final_judgments),
        "physical_attempts": len(attempts_by_key),
        "succeeded_attempts": attempt_outcomes["succeeded"],
        "retryable_failed_attempts": attempt_outcomes["retryable_failure"],
        "nonretryable_failed_attempts": attempt_outcomes["nonretryable_failure"],
        "realized_terminals": len(final_terminals),
        "batch_commits": len(final_commits),
    }


class _NeverProviderClient:
    external_provider_client = False

    def create_response(self, *_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("audit must not call a Provider")


def _decision_input_payload(decision_input: Any) -> dict[str, Any]:
    payload = decision_input.model_dump(mode="json")
    payload["profile"] = decision_profile_payload(decision_input.profile)
    return payload


def _rebuild_inputs(
    *,
    verified_bundle: Any,
    target_cell_index: int,
    judgments_by_position: Mapping[int, RecoveryJudgmentV1],
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    manifest = verified_bundle.origins.source.manifest
    proposal = verified_bundle.origins.proposal
    cell = manifest.prompt_model_cells[target_cell_index]
    closure = _v2._close_source(manifest.source.source_dir)
    _v2._validate_source_against_manifest(manifest, closure, manifest.source.source_dir)
    config = _v2._dynamic_runtime_config(closure)
    prepared = _v2._prepare_concurrent_runtime_inputs(config)

    rebuilt: dict[int, dict[str, Any]] = {}
    commits: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="gpt-p0-reuse-audit-") as directory:
        target = Path(directory) / "runtime"
        kernel, journal = _kernel(
            config=config,
            prepared=prepared,
            manifest=manifest,
            cell_index=target_cell_index,
            target=target,
            epoch_identity=str(proposal["frozen_context"]["manifest_sha256"]),
            invocation_identity=_json_sha256(
                {"audit_schema": AUDIT_SCHEMA, "cell_index": target_cell_index}
            ),
        )
        try:

            def resolve(plan: Any) -> Any:
                position = plan.pair_schedule_position
                judgment = judgments_by_position.get(position)
                if judgment is None:
                    raise AuditError("runtime replay encountered a pair without a recovered GPT-P0 Judgment")
                _require_exact(
                    _coordinates(target_cell_index, plan),
                    {
                        "cell_index": target_cell_index,
                        "pair_schedule_position": judgment.pair.pair_schedule_position,
                        "pair_id": judgment.pair.pair_id,
                        "time_step": judgment.pair.time_step,
                        "message_id": judgment.pair.message_id,
                        "user_id": judgment.pair.user_id,
                    },
                    label="rebuilt pair coordinates",
                )
                context = _v2._primary_variant_context(plan, prompt_token=cell.prompt_version)
                decision_input = context.decision_input(time_step=plan.time_step)
                messages = build_engagement_prompt(decision_input)
                input_payload = _decision_input_payload(decision_input)
                decision_input_sha256 = _sha256_bytes(
                    json.dumps(input_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
                )
                if decision_input_sha256 != decision_input.cache_key():
                    raise AuditError("DecisionInput canonicalization differs from its cache key")
                client_messages_sha256 = _json_sha256(messages)
                request_condition = {
                    "decision_input_sha256": decision_input_sha256,
                    "client_messages_sha256": client_messages_sha256,
                    "prompt_version": cell.prompt_version,
                    "prompt_canonical_hash": cell.prompt_canonical_hash,
                    "structured_output_schema_version": manifest.request_contract.structured_output_schema_version,
                    "structured_output_schema_hash": manifest.request_contract.structured_output_schema_hash,
                    "requested_model": cell.requested_model,
                    "wire_model": TARGET_OBSERVED_MODEL,
                    "observed_model": judgment.observed_model,
                    "provider_route": judgment.new_attempts[-1].provider_route,
                    "wire_api": "pi_model_runtime",
                    "reasoning_effort": manifest.request_contract.reasoning_effort,
                    "thinking_mode": None,
                    "thinking_budget": None,
                    "output_token_ceiling": manifest.request_contract.output_token_ceiling,
                    "wire_output_token_ceiling": manifest.request_contract.output_token_ceiling,
                    "output_token_ceiling_scope": "total_completion_tokens",
                    "output_token_ceiling_enforcement": "application_fail_closed",
                    "timeout_seconds": manifest.request_contract.timeout_seconds,
                    "max_retries": manifest.request_contract.max_retries,
                    "retry_backoff_seconds": manifest.request_contract.retry_backoff_seconds,
                    "maximum_physical_attempts_per_logical_pair": 3,
                    "omitted_parameters": list(manifest.request_contract.omitted_parameters),
                    "cache_retention": "none",
                    "decision_store_policy": manifest.request_contract.decision_store_policy,
                    "client_prompt_scope": "client_submitted_messages",
                    "effective_upstream_context_status": "unobservable",
                }
                rebuilt[position] = {
                    "decision_input_sha256": decision_input_sha256,
                    "client_messages_sha256": client_messages_sha256,
                    "client_message_roles": [str(message["role"]) for message in messages],
                    "client_message_count": len(messages),
                    "observable_condition_key_sha256": _json_sha256(request_condition),
                }
                terminal = judgment.realized_projection(
                    realization_source_identity=manifest.realization_source.source_identity
                )
                runtime_terminal = _v2._runtime_terminal(plan, terminal)
                kernel.start_pair(plan)
                kernel.register_terminal(
                    plan=plan,
                    decision_variant="primary",
                    terminal_row=runtime_terminal,
                    variant_evidence=_v2._runtime_evidence(plan, runtime_terminal),
                )
                return terminal

            def settled(_plan: Any, _terminal: Any) -> None:
                return None

            def committed(commit: Any) -> None:
                commits.append(
                    _v2._commit_row(
                        cell_index=target_cell_index,
                        cell_id=cell.cell_id,
                        commit=commit,
                    )
                )

            _v2._drive_primary_runtime(
                kernel,
                resolve_pair=resolve,
                pair_settled=settled,
                batch_committed=committed,
            )
            replay = journal._replay_runtime()
            closed_batches = kernel.validate_spool(replay)
            if closed_batches != manifest.ranking_contract.horizon or kernel.runtime_resident_row_count:
                raise AuditError("GPT-P0 input replay did not close its full runtime")
        finally:
            journal.close()

    _v2._assert_source_unchanged(closure)
    if len(rebuilt) != len(judgments_by_position) or len(commits) != manifest.ranking_contract.horizon:
        raise AuditError("GPT-P0 input replay did not encounter all Judgments and barriers")
    return rebuilt, {
        "sample_user_ids": list(prepared.cohort.sample_user_ids),
        "message_ids": list(manifest.message_ids),
        "computed_sample_identity": hashlib.sha256(
            json.dumps(
                prepared.cohort.sample_user_ids,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "computed_graph_identity_sha256": _v2._effective_graph_identity(prepared),
        "rebuilt_batch_commits": commits,
    }


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def _write_coverage_csv(path: Path, rows: Iterable[Mapping[str, object]]) -> None:
    fieldnames = [
        "user_id",
        "message_id",
        "historical_judgment_present",
        "reuse_disposition",
        "reusable",
        "reason_codes",
        "pair_id",
        "pair_schedule_position",
        "time_step",
        "judgment_id",
        "decision_input_sha256",
        "client_messages_sha256",
        "observable_condition_key_sha256",
        "judgment_origin_event_sequence",
        "judgment_origin_event_checksum",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _message_summary(
    message_ids: list[str],
    coverage_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for message_id in message_ids:
        rows = [row for row in coverage_rows if row["message_id"] == message_id]
        counts = Counter(str(row["reuse_disposition"]) for row in rows)
        result.append(
            {
                "message_id": message_id,
                "eligible_pairs": len(rows),
                "accepted": counts["accepted"],
                "rejected": counts["rejected"],
                "undetermined": counts["undetermined"],
                "duplicate": 0,
                "conflict": 0,
                "missing": counts["missing"],
            }
        )
    return result


def _markdown_report(audit: Mapping[str, Any], output_hashes: Mapping[str, str], command: str) -> str:
    counts = audit["counts"]
    per_message = audit["per_message"]
    identities = audit["frozen_identities"]
    condition = audit["historical_request_condition"]
    lineage = audit["lineage"]
    rows = "\n".join(
        f"| `{row['message_id']}` | {row['eligible_pairs']} | {row['accepted']} | {row['rejected']} | "
        f"{row['undetermined']} | {row['duplicate']} | {row['conflict']} | {row['missing']} |"
        for row in per_message
    )
    output_rows = "\n".join(
        f"| `{name}` | `{digest}` |" for name, digest in sorted(output_hashes.items())
    )
    return f"""# GPT-P0 旧判断复用审计（{audit['audit_date']}）

Status: Offline Evidence Audit  
Ticket: `#258`  
Result: **历史完整性通过，但当前无一条可直接接纳进新 Judgment Bank**  
Provider calls: `0`

## 结论

固定 1,000-user × 3-message universe 共 `{counts['eligible_pair_universe']}` 个组合。旧 GPT-P0 证据包含 `{counts['historical_judgments']}` 个唯一组合；逐条 lineage、settled attempt、Decision、Realized terminal、随机性与 30 个 barrier 均闭合。但是，原始 client payload digest 未持久化，只能从 hash-bound source 与记录的实现 commit 重建；effective upstream context / service snapshot 不可观测，未来补采合同也尚未冻结。因此本审计按 fail-closed 规则把旧 `{counts['historical_judgments']}` 条全部保留为 `undetermined`，而不是自动接受或武断拒绝。

- accepted: `{counts['accepted']}`
- rejected: `{counts['rejected']}`
- undetermined / evidence insufficient: `{counts['undetermined']}`
- physically missing pairs: `{counts['missing_pairs']}`
- duplicate pairs: `{counts['duplicate_pairs']}`；conflicting pairs: `{counts['conflicting_pairs']}`
- 当前 accepted coverage: `{counts['accepted_bank_coverage']}/{counts['eligible_pair_universe']}`；未闭合组合: `{counts['unresolved_bank_pairs']}`

只有未来先冻结目标请求条件、再证明全部旧 1,800 条与之同条件时，新增成功 Judgment 才是 `1,200`。当前未闭合量为 `3,000`，明显高于该目标；这只是 coverage 结论，**不是** 3,000 次 Provider 调用授权或预算。

## 输入 lineage

| 输入 | SHA-256 |
|---|---|
| Evidence `{lineage['evidence']['path']}` | `{lineage['evidence']['sha256']}` |
| Plan `{lineage['plan']['path']}` | `{lineage['plan']['sha256']}` |
| Recovery bundle `{lineage['source_bundle']['path']}` | `{lineage['source_bundle']['sha256']}` |
| Ledger prefix `{lineage['ledger_prefix']['path']}` | `{lineage['ledger_prefix']['sha256']}` |
| Source manifest `{lineage['source_manifest']['path']}` | `{lineage['source_manifest']['sha256']}` |

审计只沿上述 Evidence → plan → explicit bundle/control/source lineage 读取；没有扫描 `latest` 或其他候选 run。bundle reader 复验 `{audit['integrity']['bound_artifact_facts']}` 个 hash-bound artifact facts 及原 event origins。

## 冻结身份与逐条核对

| 项目 | 结果 |
|---|---|
| sample | `{identities['sample_identity']}`；1,000 users，重算一致 |
| graph | `{identities['graph_identity_sha256']}`；effective graph 重算一致 |
| messages | `{identities['message_snapshot_sha256']}`；`message_1..3` |
| Prompt | `{condition['prompt_version']}` / `{condition['prompt_canonical_hash']}` |
| structured schema | `{condition['structured_output_schema_version']}` / `{condition['structured_output_schema_hash']}` |
| model | requested `{condition['requested_model']}`；wire/observed `{condition['wire_model']}` / `{condition['observed_model']}` |
| route / wire | `{condition['provider_route']}` / `{condition['wire_api']}` |
| reasoning / ceiling | `{condition['reasoning_effort']}` / `{condition['output_token_ceiling']}` total completion tokens；`{condition['output_token_ceiling_enforcement']}` |
| timeout / retry | `{condition['timeout_seconds']}s` / max `{condition['max_retries']}` retries / `{condition['retry_backoff_seconds']}s` backoff；每 logical pair 最多 `{condition['maximum_physical_attempts_per_logical_pair']}` attempts |
| sampling | omitted `{', '.join(condition['omitted_parameters'])}` |
| realization | seed `{identities['realization_seed']}`；`{identities['realization_rule_version']}` |
| store | `{condition['decision_store_policy']}` / cache retention `{condition['cache_retention']}`（历史合同，不改写为新 bank 合同） |

对每个旧 Judgment 都从冻结 sample、effective graph、message snapshot、同路径 batch feedback 与 P0 template 重建完整 `DecisionInput`，保存 `decision_input_sha256`、`client_messages_sha256` 和 observable-condition key；不在报告或清单中复制 raw Prompt/profile 文本。`{counts['historical_judgments']}` 条 Judgment、`{counts['physical_attempts']}` 个 physical attempts（其中 `{counts['retryable_failed_attempts']}` 个已结算 retryable failure）、`{counts['realized_terminals']}` 个 Realized terminals 与 `{counts['batch_commits']}` 个 batch commits 均逐条回链到 immutable ledger。

P0 的 1,800 个 Judgment 均为 `concurrent-recovery-provider-judgment-v1`，无 per-Judgment amendment；它们在 campaign-level `final_model_continuation_accepted`（event `91476`，approval SHA-256 `d43f41179444e2c481ec13eac44497b12f25f7306ed5975186e595991da15183`）、成功 self-check（event `91478`）与 epoch admission（event `91479`，epoch plan SHA-256 `31de16f7bd9edf5de60134575297f50a21db9e0f0f4694c4b9af493c69e68dee`）后执行。后续 GPT parallel/manual-retry amendment 不追溯改变 P0。所有成功 response 都报告 `gpt-5.6-sol` 且 usage complete；审计相关实现 bytes 与 completion audit 记录的 commit `{lineage['implementation_commit']}` 一致。

## 按 message 闭合

| message | universe | accepted | rejected | undetermined | duplicate | conflict | missing |
|---|---:|---:|---:|---:|---:|---:|---:|
{rows}

旧判断库大小 `1,800` 是一条历史 GPT-P0 动态路径的实际 exposure/Judgment 数，不是每条未来参数路径都要把 3,000 pairs 全部曝光。固定 Top20 × 30 batches × 3 messages 的路径分母仍是 `1,800`；`3,000` 只是完整 Judgment Bank 的 eligible universe。

## 为什么保持未定

1. **原请求 payload digest 不存在。** 代码与 hash-bound输入允许重建 client-submitted messages，但历史 evidence 没有保存逐请求原始 digest，不能把重建结果表述成原 payload 的直接观测。
2. **effective upstream context 不可观测。** Pi ModelRuntime 路由、模型服务端 system context / rollout 与服务版本没有可闭合 snapshot；client contract 相同不等于 upstream effective context 已证明相同。
3. **服务时间漂移。** P0 Judgment 持久化窗口为 `{audit['service_time_boundary']['first_judgment_recorded_at_utc']}` 至 `{audit['service_time_boundary']['last_judgment_recorded_at_utc']}`。未来补采发生在另一服务时间，不能自动并入统一条件。
4. **目标合同未冻结。** 新 Judgment Bank 的最终 route/model qualification、complete input identity 与 collection-time contract 尚未批准；本审计不能替未来合同作出相等性判断。

## 可复核产物

| 文件 | SHA-256 |
|---|---|
{output_rows}

复现命令：

```bash
{command}
```

`pair_coverage_checklist.csv` 覆盖全部 3,000 pairs；`judgment_evidence_checklist.jsonl` 对 1,800 条旧记录保存输入 fingerprint、request condition、attempt/origin 与 fail-closed disposition。原 Evidence、source、control、Provider response 与生产接口均未修改。

## 边界

- `provider_calls=0`；未调用 LLM、TikHub、Douyin、profile API、Ralph、Release 或 Deployment。
- 未读取、打印或写入 `.env`、credential、Authorization header、raw Provider payload 或 raw Prompt。
- 本结果不拒绝历史 Judgment 的研究真实性；它只表示目前无法证明它们与未来补采属于同一完整请求条件。
- 本次不改变 canonical endpoint，且不产生部署资格。
"""


def run_audit(
    *,
    evidence_path: Path,
    plan_path: Path,
    output_dir: Path,
    repository_root: Path,
    audit_date: str,
) -> Path:
    evidence_path = _require_regular_file(evidence_path, label="pinned Evidence")
    plan_path = _require_regular_file(plan_path, label="pinned recovery plan")
    repository_root = repository_root.expanduser().resolve()
    if not (repository_root / ".git").exists():
        raise AuditError("repository root must be the current Git checkout")
    _require_sha256(evidence_path, EXPECTED_EVIDENCE_SHA256, label="Evidence")
    _require_sha256(plan_path, EXPECTED_PLAN_SHA256, label="recovery plan")
    evidence = _read_json(evidence_path)
    plan = _read_json(plan_path)
    _require_exact(
        evidence.get("original_plan"),
        {"path": str(plan_path), "sha256": EXPECTED_PLAN_SHA256},
        label="Evidence plan reference",
    )
    if plan.get("schema_version") != "concurrent-recovery-task-plan-v1":
        raise AuditError("recovery plan schema differs from the approved task plan")

    evidence_root = evidence_path.parent
    artifacts = _artifact_paths(
        evidence_root,
        (
            "Evidence.json",
            "attempts.jsonl",
            "batch_commits.jsonl",
            "completion-audit.json",
            "delivery-verification.json",
            "judgments.jsonl",
            "realized_terminals.jsonl",
        ),
    )
    completion = _read_json(artifacts["completion-audit.json"])
    implementation_commit = completion.get("code_commit")
    if not isinstance(implementation_commit, str) or len(implementation_commit) != 40:
        raise AuditError("completion audit lacks its exact implementation commit")
    implementation_files = _verify_implementation(repository_root, implementation_commit)

    bundle_reference = evidence.get("source_bundle")
    if not isinstance(bundle_reference, Mapping):
        raise AuditError("Evidence lacks its explicit recovery bundle reference")
    bundle_path = _require_regular_file(Path(str(bundle_reference.get("path"))), label="recovery bundle")
    bundle_sha256 = str(bundle_reference.get("sha256"))
    _require_sha256(bundle_path, bundle_sha256, label="recovery bundle")
    verified_bundle = _read_verified_recovery_bundle(bundle_path)
    manifest = verified_bundle.origins.source.manifest
    source_manifest_path = _require_regular_file(
        Path(verified_bundle.origins.proposal["source_output_root"]) / "study_manifest.json",
        label="source study manifest",
    )
    source_manifest_sha256 = str(verified_bundle.origins.proposal["frozen_context"]["manifest_sha256"])
    _require_sha256(source_manifest_path, source_manifest_sha256, label="source study manifest")

    matching_cells = [
        (index, cell)
        for index, cell in enumerate(manifest.prompt_model_cells)
        if cell.requested_model == TARGET_MODEL and cell.prompt_variant == TARGET_PROMPT_VARIANT
    ]
    if len(matching_cells) != 1:
        raise AuditError("manifest must contain exactly one GPT-P0 cell")
    target_cell_index, cell = matching_cells[0]
    if cell.required_observed_model != TARGET_OBSERVED_MODEL:
        raise AuditError("GPT-P0 observed-model contract drifted")
    if tuple(manifest.request_contract.omitted_parameters) != OMITTED_PARAMETERS:
        raise AuditError("GPT-P0 sampling omission policy drifted")

    judgments_by_position: dict[int, RecoveryJudgmentV1] = {}
    judgment_events: dict[int, Mapping[str, Any]] = {}
    records_by_sequence: dict[int, Mapping[str, Any]] = {}
    for record in verified_bundle.records:
        sequence = record.get("sequence")
        if type(sequence) is not int or sequence in records_by_sequence:
            raise AuditError("recovery ledger sequence is malformed or duplicated")
        records_by_sequence[sequence] = record
        if record.get("kind") != "judgment_persisted":
            continue
        payload = record.get("payload")
        if not isinstance(payload, Mapping) or not isinstance(payload.get("judgment"), Mapping):
            raise AuditError("recovery ledger contains a malformed Judgment event")
        raw_judgment = payload["judgment"]
        if raw_judgment.get("cell_index") != target_cell_index:
            continue
        judgment = RecoveryJudgmentV1.model_validate(raw_judgment)
        position = judgment.pair.pair_schedule_position
        if position in judgments_by_position:
            raise AuditError("recovery ledger repeats a GPT-P0 schedule position")
        judgments_by_position[position] = judgment
        judgment_events[position] = record
    if len(judgments_by_position) != 1800 or set(judgments_by_position) != set(range(1800)):
        raise AuditError("recovery ledger does not contain the complete 1,800-row GPT-P0 path")

    expected_metadata = PiOpenAIDecisionAdapter(
        prompt_version=cell.prompt_version,
        client=_NeverProviderClient(),
    ).safe_metadata
    schema_counts: Counter[str] = Counter()
    for judgment in judgments_by_position.values():
        schema_counts[judgment.schema_version] += 1
        if judgment.decision.provider_metadata != expected_metadata:
            raise AuditError("GPT-P0 persisted request metadata differs from the recorded Adapter contract")
        if judgment.observed_model != TARGET_OBSERVED_MODEL:
            raise AuditError("GPT-P0 successful response reports an unexpected model")
        if judgment.cell != cell:
            raise AuditError("GPT-P0 Judgment is crossed with another cell")
    if schema_counts != {"concurrent-recovery-provider-judgment-v1": 1800}:
        raise AuditError("GPT-P0 Judgment amendments differ from the audited historical scope")

    ledger_path = _require_regular_file(
        bundle_path.parent / str(verified_bundle.document["ledger_prefix"]["relative_path"]),
        label="recovery ledger prefix",
    )
    ledger_sha256 = str(verified_bundle.document["ledger_prefix"]["sha256"])
    _require_sha256(ledger_path, ledger_sha256, label="recovery ledger prefix")
    pair_rows, attempts_by_key, projection_counts = _validate_final_projection(
        artifacts=artifacts,
        target_cell_index=target_cell_index,
        judgments_by_position=judgments_by_position,
        records_by_sequence=records_by_sequence,
        ledger_path=ledger_path,
        ledger_sha256=ledger_sha256,
        realization_source_identity=manifest.realization_source.source_identity,
        replay_batch_commits=verified_bundle.batch_commits,
    )

    rebuilt, runtime_facts = _rebuild_inputs(
        verified_bundle=verified_bundle,
        target_cell_index=target_cell_index,
        judgments_by_position=judgments_by_position,
    )
    if runtime_facts["computed_sample_identity"] != manifest.sample.sample_identity:
        raise AuditError("rebuilt sample identity differs from the manifest")
    if runtime_facts["computed_graph_identity_sha256"] != manifest.realization_source.graph_identity_sha256:
        raise AuditError("rebuilt effective graph identity differs from the manifest")
    replay_commits = runtime_facts["rebuilt_batch_commits"]
    expected_commits = [
        row for row in verified_bundle.batch_commits if row.get("cell_index") == target_cell_index
    ]
    replay_commits.sort(key=lambda row: int(row["time_step"]))
    expected_commits.sort(key=lambda row: int(row["time_step"]))
    _require_exact(replay_commits, expected_commits, label="rebuilt GPT-P0 batch feedback")

    provider_disclosure = next(
        row for row in robustness_provider_disclosures() if row["requested_model"] == TARGET_MODEL
    )
    request_condition = {
        "prompt_version": cell.prompt_version,
        "prompt_canonical_hash": cell.prompt_canonical_hash,
        "structured_output_schema_version": manifest.request_contract.structured_output_schema_version,
        "structured_output_schema_hash": manifest.request_contract.structured_output_schema_hash,
        "requested_model": cell.requested_model,
        "wire_model": provider_disclosure["wire_model"],
        "observed_model": cell.required_observed_model,
        "provider_route": provider_disclosure["provider_route"],
        "wire_api": provider_disclosure["wire_api"],
        "reasoning_effort": provider_disclosure["reasoning_effort"],
        "thinking_mode": provider_disclosure["thinking_mode"],
        "thinking_budget": provider_disclosure["thinking_budget"],
        "output_token_ceiling": provider_disclosure["output_token_ceiling"],
        "wire_output_token_ceiling": provider_disclosure["wire_output_token_ceiling"],
        "output_token_ceiling_scope": provider_disclosure["output_token_ceiling_scope"],
        "output_token_ceiling_enforcement": "application_fail_closed",
        "timeout_seconds": manifest.request_contract.timeout_seconds,
        "max_retries": manifest.request_contract.max_retries,
        "retry_backoff_seconds": manifest.request_contract.retry_backoff_seconds,
        "maximum_physical_attempts_per_logical_pair": 3,
        "omitted_parameters": list(manifest.request_contract.omitted_parameters),
        "cache_retention": "none",
        "decision_store_policy": manifest.request_contract.decision_store_policy,
        "client_prompt_scope": provider_disclosure["client_prompt_scope"],
        "effective_upstream_context_status": "unobservable",
    }

    judgment_checklist: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, object]] = []
    old_by_pair: dict[tuple[str, str], int] = {}
    for position, judgment in sorted(judgments_by_position.items()):
        pair_key = (judgment.pair.user_id, judgment.pair.message_id)
        if pair_key in old_by_pair:
            raise AuditError("GPT-P0 historical inventory repeats a user-message pair")
        old_by_pair[pair_key] = position
        final_row = pair_rows[pair_key]
        rebuilt_row = rebuilt[position]
        attempt_rows = [
            attempts_by_key[position, attempt.attempt_number]
            for attempt in (*judgment.historical_attempts, *judgment.new_attempts)
        ]
        origin = final_row["origin"]
        checklist_row = {
            "schema_version": CHECKLIST_SCHEMA,
            "pair": {
                "user_id": judgment.pair.user_id,
                "message_id": judgment.pair.message_id,
                "pair_id": judgment.pair.pair_id,
                "pair_schedule_position": position,
                "time_step": judgment.pair.time_step,
            },
            "historical_judgment": {
                "judgment_id": judgment.judgment_id,
                "schema_version": judgment.schema_version,
                "origin": origin,
                "settled_attempt_origins": [row["origin"] for row in attempt_rows],
                "physical_attempts": len(attempt_rows),
                "observed_model": judgment.observed_model,
            },
            "rebuilt_client_input": {
                **rebuilt_row,
                "status": "reconstructed_from_hash_bound_sources_not_original_payload_observation",
            },
            "request_condition": request_condition,
            "integrity_checks": {
                "sample_identity_match": True,
                "graph_identity_match": True,
                "message_identity_match": True,
                "runtime_coordinates_match": True,
                "prompt_and_schema_match": True,
                "request_metadata_match": True,
                "settled_attempts_match": True,
                "judgment_origin_match": True,
                "realization_match": True,
                "batch_feedback_match": True,
            },
            "reuse_assessment": {
                "disposition": "undetermined",
                "reusable": False,
                "reason_codes": list(UNDETERMINED_REASON_CODES),
                "complete_condition_key_status": "incomplete_unobservable_upstream_context",
            },
        }
        judgment_checklist.append(checklist_row)
        coverage_rows.append(
            {
                "user_id": judgment.pair.user_id,
                "message_id": judgment.pair.message_id,
                "historical_judgment_present": "true",
                "reuse_disposition": "undetermined",
                "reusable": "false",
                "reason_codes": ";".join(UNDETERMINED_REASON_CODES),
                "pair_id": judgment.pair.pair_id,
                "pair_schedule_position": position,
                "time_step": judgment.pair.time_step,
                "judgment_id": judgment.judgment_id,
                "decision_input_sha256": rebuilt_row["decision_input_sha256"],
                "client_messages_sha256": rebuilt_row["client_messages_sha256"],
                "observable_condition_key_sha256": rebuilt_row["observable_condition_key_sha256"],
                "judgment_origin_event_sequence": origin["event_sequence"],
                "judgment_origin_event_checksum": origin["event_checksum"],
            }
        )

    sample_user_ids = [str(value) for value in runtime_facts["sample_user_ids"]]
    message_ids = [str(value) for value in runtime_facts["message_ids"]]
    if len(sample_user_ids) != 1000 or len(set(sample_user_ids)) != 1000 or len(message_ids) != 3:
        raise AuditError("rebuilt fixed universe differs from 1,000 users × 3 messages")
    pair_universe = {(user_id, message_id) for user_id in sample_user_ids for message_id in message_ids}
    if not set(old_by_pair).issubset(pair_universe) or len(pair_universe) != 3000:
        raise AuditError("historical GPT-P0 pairs are outside the fixed eligible universe")
    for user_id, message_id in sorted(pair_universe - set(old_by_pair)):
        coverage_rows.append(
            {
                "user_id": user_id,
                "message_id": message_id,
                "historical_judgment_present": "false",
                "reuse_disposition": "missing",
                "reusable": "false",
                "reason_codes": "no_historical_gpt_p0_judgment",
                "pair_id": "",
                "pair_schedule_position": "",
                "time_step": "",
                "judgment_id": "",
                "decision_input_sha256": "",
                "client_messages_sha256": "",
                "observable_condition_key_sha256": "",
                "judgment_origin_event_sequence": "",
                "judgment_origin_event_checksum": "",
            }
        )
    coverage_rows.sort(key=lambda row: (str(row["message_id"]), str(row["user_id"])))
    per_message = _message_summary(message_ids, coverage_rows)
    if any(
        row != {
            "message_id": row["message_id"],
            "eligible_pairs": 1000,
            "accepted": 0,
            "rejected": 0,
            "undetermined": 600,
            "duplicate": 0,
            "conflict": 0,
            "missing": 400,
        }
        for row in per_message
    ):
        raise AuditError("per-message coverage does not close to 600 historical + 400 missing")

    judgment_times = [str(judgment_events[position]["recorded_at_utc"]) for position in judgments_by_position]
    continuation_events = [
        row for row in verified_bundle.records if row.get("kind") == "final_model_continuation_accepted"
    ]
    self_check_events = [
        row
        for row in verified_bundle.records
        if row.get("kind") == "self_check_settled"
        and isinstance(row.get("payload"), Mapping)
        and row["payload"].get("requested_model") == TARGET_MODEL
    ]
    epoch_events = [
        row
        for row in verified_bundle.records
        if row.get("kind") == "epoch_admitted"
        and isinstance(row.get("payload"), Mapping)
        and row["payload"].get("requested_model") == TARGET_MODEL
    ]
    if len(continuation_events) != 1 or len(self_check_events) != 1 or len(epoch_events) != 1:
        raise AuditError("GPT-P0 campaign-level admission lineage is incomplete")

    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists():
        raise AuditError(f"output directory already exists: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        checklist_path = staging / "judgment_evidence_checklist.jsonl"
        coverage_path = staging / "pair_coverage_checklist.csv"
        _write_jsonl(checklist_path, judgment_checklist)
        _write_coverage_csv(coverage_path, coverage_rows)
        checklist_hashes = {
            checklist_path.name: _sha256_file(checklist_path),
            coverage_path.name: _sha256_file(coverage_path),
        }

        counts = {
            "eligible_pair_universe": len(pair_universe),
            "historical_judgments": len(judgments_by_position),
            "accepted": 0,
            "rejected": 0,
            "undetermined": len(judgments_by_position),
            "missing_pairs": len(pair_universe - set(old_by_pair)),
            "duplicate_pairs": 0,
            "conflicting_pairs": 0,
            "accepted_bank_coverage": 0,
            "unresolved_bank_pairs": len(pair_universe),
            "nominal_new_successes_if_all_old_accepted": len(pair_universe) - len(judgments_by_position),
            **projection_counts,
        }
        audit = {
            "schema_version": AUDIT_SCHEMA,
            "audit_date": audit_date,
            "result": "HISTORICAL_INTEGRITY_VERIFIED_REUSE_UNDETERMINED",
            "scope": {
                "requested_model": TARGET_MODEL,
                "prompt_variant": TARGET_PROMPT_VARIANT,
                "cell_index": target_cell_index,
                "cell_id": cell.cell_id,
            },
            "lineage": {
                "evidence": {"path": str(evidence_path), "sha256": EXPECTED_EVIDENCE_SHA256},
                "evidence_artifact_manifest": {
                    "path": str(artifacts["artifact_manifest.json"]),
                    "sha256": _sha256_file(artifacts["artifact_manifest.json"]),
                },
                "plan": {"path": str(plan_path), "sha256": EXPECTED_PLAN_SHA256},
                "source_bundle": {"path": str(bundle_path), "sha256": bundle_sha256},
                "ledger_prefix": {"path": str(ledger_path), "sha256": ledger_sha256},
                "source_manifest": {"path": str(source_manifest_path), "sha256": source_manifest_sha256},
                "implementation_commit": implementation_commit,
                "implementation_files": implementation_files,
            },
            "frozen_identities": {
                "sample_identity": manifest.sample.sample_identity,
                "graph_identity_sha256": manifest.realization_source.graph_identity_sha256,
                "message_snapshot_sha256": manifest.message_snapshot_sha256,
                "realization_source_identity": manifest.realization_source.source_identity,
                "realization_seed": manifest.realization_source.realization_seed,
                "realization_rule_version": manifest.realization_source.realization_rule_version,
            },
            "historical_request_condition": request_condition,
            "campaign_admission": {
                "final_model_continuation_event": {
                    "sequence": continuation_events[0]["sequence"],
                    "record_sha256": continuation_events[0]["record_sha256"],
                    "approval": continuation_events[0]["payload"]["approval"],
                },
                "self_check_event": {
                    "sequence": self_check_events[0]["sequence"],
                    "record_sha256": self_check_events[0]["record_sha256"],
                    "outcome": self_check_events[0]["payload"]["attempt"]["outcome"],
                    "observed_model_counts": self_check_events[0]["payload"]["attempt"]["observed_model_counts"],
                },
                "epoch_event": {
                    "sequence": epoch_events[0]["sequence"],
                    "record_sha256": epoch_events[0]["record_sha256"],
                    "epoch_identity_sha256": epoch_events[0]["payload"]["epoch_identity_sha256"],
                    "plan_path": epoch_events[0]["payload"]["plan_path"],
                    "plan_sha256": epoch_events[0]["payload"]["plan_sha256"],
                },
                "p0_judgment_schema_counts": dict(sorted(schema_counts.items())),
                "per_judgment_amendments": 0,
            },
            "integrity": {
                "bound_artifact_facts": len(verified_bundle.document["artifact_facts"]),
                "bundle_replay_summary": verified_bundle.document["realization_verification"],
                "target_projection_counts": projection_counts,
                "rebuilt_client_inputs": len(rebuilt),
                "observable_condition_key_unique_count": len(
                    {str(row["observable_condition_key_sha256"]) for row in rebuilt.values()}
                ),
                "original_client_payload_digest_persisted": False,
                "effective_upstream_context_observable": False,
                "all_target_checks_passed": True,
            },
            "counts": counts,
            "per_message": per_message,
            "service_time_boundary": {
                "first_judgment_recorded_at_utc": min(judgment_times),
                "last_judgment_recorded_at_utc": max(judgment_times),
                "future_service_equivalence": "not_proven",
            },
            "reuse_policy": {
                "accepted_requires_complete_condition_equivalence": True,
                "historical_disposition": "undetermined",
                "reason_codes": list(UNDETERMINED_REASON_CODES),
                "missing_pair_disposition": "missing",
                "automatic_collection_authorized": False,
            },
            "output_hashes": checklist_hashes,
            "provider_calls": 0,
            "live_api_triggered": False,
            "secrets_read_printed_or_written": False,
            "raw_prompts_or_provider_payloads_written": False,
            "production_contract_changed": False,
            "deployment_triggered": False,
        }
        audit_path = staging / "audit.json"
        _write_json(audit_path, audit)
        report_hash_inputs = {**checklist_hashes, audit_path.name: _sha256_file(audit_path)}
        command = (
            ". .venv/bin/activate\n"
            f"python scripts/audit_gpt_p0_judgment_reuse.py \\\n"
            f"  --evidence {evidence_path} \\\n"
            f"  --plan {plan_path} \\\n"
            f"  --output-dir {output_dir} \\\n"
            f"  --audit-date {audit_date}"
        )
        report_path = staging / "report.md"
        report_path.write_text(
            _markdown_report(audit, report_hash_inputs, command),
            encoding="utf-8",
        )
        artifact_rows = []
        for path in sorted(staging.iterdir(), key=lambda item: item.name):
            if path.name == "artifact_manifest.json":
                continue
            artifact_rows.append(
                {
                    "relative_path": path.name,
                    "bytes": path.stat().st_size,
                    "sha256": _sha256_file(path),
                }
            )
        manifest_path = staging / "artifact_manifest.json"
        _write_json(
            manifest_path,
            {
                "schema_version": MANIFEST_SCHEMA,
                "provider_calls": 0,
                "artifacts": artifact_rows,
            },
        )
        for path in staging.iterdir():
            path.chmod(0o444)
        os.replace(staging, output_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return output_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit the pinned historical GPT-P0 Judgments without Provider calls"
    )
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--audit-date", required=True)
    args = parser.parse_args(argv)
    output = run_audit(
        evidence_path=args.evidence,
        plan_path=args.plan,
        output_dir=args.output_dir,
        repository_root=args.repository_root,
        audit_date=args.audit_date,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "output_dir": str(output),
                "provider_calls": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
