"""Closed four-model recovery evidence and its research estimands.

The five-model contracts remain unchanged. This Interface consumes an explicitly
hash-bound delivery and replays its original immutable bundle, never a Provider.
"""
from __future__ import annotations

import hashlib
import json
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import concurrent_robustness_recovery_evidence as recovery
from . import concurrent_robustness_study as historical
from . import concurrent_robustness_v2_evidence as v2
from ._concurrent_recovery_bundle import _read_verified_recovery_bundle
from ._concurrent_recovery_judgment import RecoveryJudgmentV1

MODELS = ("deepseek-v4-flash", "gemini-3.1-pro", "kimi-coding/k3-256k", "openai-codex/gpt-5.6-sol")
PROMPTS = ("P0", "P1", "P2", "P3")
MESSAGES = ("message_1", "message_2", "message_3")
SCHEMA = "concurrent-revised-four-model-evidence-v1"
ANALYSIS_SCHEMA = "concurrent-revised-four-model-analysis-v1"


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def inventory(root: Path) -> dict[str, dict[str, Any]]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Evidence directory must be regular")
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Evidence inventory rejects symlinks")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = {"sha256": sha(path), "bytes": path.stat().st_size, "mode": path.stat().st_mode & 0o777}
        elif not path.is_dir():
            raise ValueError("Evidence inventory rejects special files")
    return result


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


@dataclass(frozen=True)
class ClosedRevisedEvidence:
    """Read-only facts, not execution authority or production eligibility."""
    source: Path
    document: dict[str, Any]
    judgments: tuple[dict[str, Any], ...]
    terminals: tuple[dict[str, Any], ...]
    commits: tuple[dict[str, Any], ...]
    membership: dict[str, str]
    seed_users: tuple[str, ...]
    messages: tuple[dict[str, Any], ...]
    source_inventory: dict[str, dict[str, Any]]


def close_revised_evidence(source: str | Path, *, evidence_sha256: str) -> ClosedRevisedEvidence:
    """Independently close the approved 4×4×1800 recovery scope, fail closed.

    Preserves original bytes/modes, cancellation, retry ordinals and nullable
    usage. Missing, crossed or still in-flight evidence raises ValueError.
    """
    root = Path(source).absolute()
    if not (root / "Evidence.json").is_file() or (root / "Evidence.json").is_symlink() or sha(root / "Evidence.json") != evidence_sha256:
        raise ValueError("Evidence hash binding is missing or crossed")
    before = inventory(root)
    doc = json.loads((root / "Evidence.json").read_text())
    if doc.get("schema_version") != "revised-four-model-stage-evidence-v1" or doc.get("revised_scope_data_complete") is not True or doc.get("original_five_model_scope_complete") is not False or doc.get("production_deploy_eligible") is not False:
        raise ValueError("Evidence must be the unmodified revised four-model delivery")
    for item in json.loads((root / "artifact_manifest.json").read_text())["artifacts"]:
        path = Path(item["path"])
        if path.parent != root or before.get(path.name) != {"sha256": item["sha256"], "bytes": item["bytes"], "mode": int(item["mode"], 8)}:
            raise ValueError("Evidence delivery manifest differs from bytes/mode")
    plan_path = Path(doc["original_plan"]["path"])
    if sha(plan_path) != doc["original_plan"]["sha256"]:
        raise ValueError("Evidence original plan hash drift")
    plan = json.loads(plan_path.read_text())
    campaign = plan["authorization"]["request_identity"]["campaign"]
    bundle_path = Path(doc["source_bundle"]["path"])
    if bundle_path != Path(campaign["control_root"]) / "bundles" / doc["head_sha256"] / "bundle.json" or sha(bundle_path) != doc["source_bundle"]["sha256"]:
        raise ValueError("Evidence bundle not bound to explicit plan/control/head")
    facts = _read_verified_recovery_bundle(bundle_path)
    state, manifest = facts.state, facts.origins.source.manifest
    expected_indices = [i for i, c in enumerate(manifest.prompt_model_cells) if c.requested_model in MODELS]
    if (manifest.source.kind != "formal" or manifest.execution_profile != "formal"
            or manifest.sample.sample_size != 1000 or manifest.ranking_contract.horizon != 30
            or manifest.ranking_contract.delivery_capacity != 20 or len(expected_indices) != 16
            or state.status != "model_complete" or not state.model_stage_complete
            or state.current_model != MODELS[-1] or state.has_inflight or state.reservation is not None
            or state.pending_judgment is not None or state.pending_realized is not None
            or state.self_check_inflight is not None or state.task_revoked
            or state.final_model_continuation is None
            or state.final_model_continuation["excluded_model"] != "gemini-3.8-flash-high"
            or state.prefix != [1800 if i in expected_indices else 0 for i in range(20)]):
        raise ValueError("Evidence has not closed the approved revised topology")
    membership, messages = recovery._membership_and_messages(manifest)
    sample_path = manifest.source.source_dir / "sample_manifest.json"
    sample = json.loads(sample_path.read_text())
    seeds = tuple(sorted(r["user_id"] for r in sample if r["is_seed"]))
    old_j, old_t, old_origins, old_attempts, failed_origins = recovery._inherited_facts(facts.origins.proposal, manifest)
    ao, jo, _checks = recovery._event_origins(facts)
    new_j = {key: RecoveryJudgmentV1.model_validate(value) for key, value in state.judgments.items()}
    expected_keys = {(i, p) for i in expected_indices for p in range(1800)}
    if set(old_j) & set(new_j) or set(old_j) | set(new_j) != expected_keys:
        raise ValueError("Evidence logical union is incomplete or duplicates prior successes")
    expected_j = {key: recovery._final_judgment_row(j, old_origins[key], old_attempts[key]) for key, j in old_j.items()}
    expected_j.update({key: recovery._final_judgment_row(j, jo[key], j.new_attempts) for key, j in new_j.items()})
    expected_t = {key: t.model_dump(mode="json") for key, t in old_t.items()}
    expected_t.update({key: j.realized_projection(realization_source_identity=manifest.realization_source.source_identity).model_dump(mode="json") for key, j in new_j.items()})
    judgments, terminals, commits, attempts = [_rows(root / n) for n in ("judgments.jsonl", "realized_terminals.jsonl", "batch_commits.jsonl", "attempts.jsonl")]
    if judgments != [expected_j[k] for k in sorted(expected_keys)] or terminals != [expected_t[k] for k in sorted(expected_keys)] or commits != list(facts.batch_commits) or len(commits) != 480:
        raise ValueError("Evidence row bytes/semantics differ from independent bundle reconstruction")
    expected_a = {}
    for key, rows in old_attempts.items():
        for a in rows:
            expected_a[(*key, a.attempt_number)] = (a.model_dump(mode="json"), old_origins[key])
    failed_key = state.failed_key
    for a in state.historical_failure:
        expected_a[(*failed_key, a.attempt_number)] = (a.model_dump(mode="json"), failed_origins[failed_key])
    for key, rows in state.new_attempts.items():
        for a in rows:
            expected_a[(*key, a.attempt_number)] = (a.model_dump(mode="json"), ao[key][a.attempt_number])
    unknown_keys = set(state.kimi_archived_unknown) | set(state.gpt_archived_unknown)
    seen = set()
    known = []
    for row in attempts:
        key = (row["cell_index"], row["pair_schedule_position"], row["attempt_number"])
        if key in seen or not 1 <= key[2] <= 3 or row["requested_model"] != manifest.prompt_model_cells[key[0]].requested_model:
            raise ValueError("Evidence attempt ordinal duplicated, crossed or over cap")
        seen.add(key)
        if row["kind"] == "settled_attempt":
            if (row["attempt"], row["origin"]) != expected_a.get(key):
                raise ValueError("Evidence historical settled attempt differs from origin")
            known.append(recovery._v2._V2AttemptEvidence.model_validate(row["attempt"]))
        elif row["kind"] == "archived_unknown_intent":
            origin = row["origin"]
            event = facts.records[origin["sequence"] - 1]
            if (key[:2] not in unknown_keys or key[2] != 1 or row["attempt"] is not None
                    or row["usage"] is not None or event["record_sha256"] != origin["event_sha256"]
                    or event["kind"] != "parallel_attempt_intent"
                    or event["payload"] != {"cell_index": key[0], "pair_schedule_position": key[1], "attempt_number": key[2]}):
                raise ValueError("Evidence archived unknown differs from immutable intent")
        else:
            raise ValueError("Evidence has an unsupported attempt kind")
    if seen != set(expected_a) | {(*k, 1) for k in unknown_keys} or len(attempts) != facts.document["progress"]["physical_attempts"]:
        raise ValueError("Evidence cumulative physical accounting differs from ledger")
    if any(a.successful_decision_count for a in known if a.outcome != "succeeded"):
        raise ValueError("Failed attempt represented as success")
    routes = Counter((r["requested_model"], r["prompt_variant"], r["observed_model"], r["successful_attempts"][-1]["provider_route"]) for r in judgments)
    usage = recovery.summarize_recovery_attempt_usage(known)
    document = {
        "schema_version": SCHEMA, "formal_research_evidence": True, "production_deploy_eligible": False,
        "scope": "revised_four_model_recovery", "original_five_model_complete": False,
        "models": list(MODELS), "prompts": list(PROMPTS), "messages": list(MESSAGES),
        "sample_users": len(membership), "seed_user_count": len(seeds), "source_sample_identity": manifest.sample.sample_identity,
        "formal_source_manifest_sha256": manifest.source.manifest_sha256,
        "realization_source": manifest.realization_source.model_dump(mode="json"),
        "prompt_model_mapping": [c.model_dump(mode="json") for c in manifest.prompt_model_cells if c.requested_model in MODELS],
        "message_snapshot_sha256": manifest.message_snapshot_sha256,
        "initial_request_contract": manifest.request_contract.model_dump(mode="json"),
        "request_contract_boundary": "Initial source contract only; approved recovery amendments and route changes remain bound to the immutable bundle, not a uniform effective request condition.",
        "source": {"path": str(root), "evidence_sha256": evidence_sha256, "inventory": before},
        "bundle": dict(doc["source_bundle"]), "plan": dict(doc["original_plan"]), "head_sha256": doc["head_sha256"],
        "counts": {"judgments": len(judgments), "cells": 16, "barriers": len(commits), "physical": len(attempts),
                   "new_physical": facts.document["progress"]["new_physical_attempts"],
                   "known_failures": sum(a.outcome != "succeeded" for a in known), "archived_unknown": len(unknown_keys), "unsettled": 0},
        "cancelled_model": "gemini-3.8-flash-high", "cancelled_model_calls": 0,
        "settled_attempt_usage": usage, "all_history_token_total": None if unknown_keys else usage["total_usage"],
        "fees": v2._fee_summary(known),
        "identity_strata": [dict(model=k[0], prompt=k[1], observed_model=k[2], route=k[3], judgments=n) for k, n in sorted(routes.items())],
        "provider_calls": 0,
    }
    document["identity_sha256"] = hashlib.sha256(json_bytes(document)).hexdigest()
    if inventory(root) != before:
        raise ValueError("Evidence bytes or mode changed during closure")
    return ClosedRevisedEvidence(root, document, tuple(judgments), tuple(terminals), tuple(commits), membership, seeds, messages, before)


def analyze_revised_evidence(evidence: ClosedRevisedEvidence) -> dict[str, Any]:
    """Project same-source descriptive paths and predeclared seed-only comparisons.

    No adaptive terminal is included in the direct paired bootstrap. Thresholds
    remain outcome-specific: historical direct 0.05; v2 realized paths 0.02.
    """
    by_cell: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in evidence.terminals:
        by_cell[row["requested_model"], row["prompt_variant"]].append(row)
    if set(by_cell) != {(m, p) for m in MODELS for p in PROMPTS} or any(len(v) != 1800 for v in by_cell.values()):
        raise ValueError("Analysis requires 16 complete 1800-exposure cells")
    seed_pairs = {(u, m) for u in evidence.seed_users for m in MESSAGES}
    fixed = {k: {(r["user_id"], r["message_id"]): r for r in rows if r["time_step"] == 0 and r["user_id"] in evidence.seed_users} for k, rows in by_cell.items()}
    if not seed_pairs or any(set(v) != seed_pairs for v in fixed.values()):
        raise ValueError("Analysis requires every predeclared seed/message pair in every cell")
    result: dict[str, Any] = {"schema_version": ANALYSIS_SCHEMA, "evidence_identity_sha256": evidence.document["identity_sha256"],
        "models": list(MODELS), "prompts": list(PROMPTS), "messages": list(MESSAGES),
        "sample_users": len(evidence.membership), "seed_users": len(evidence.seed_users), "seed_pairs_per_cell": len(seed_pairs),
        "primary_outcome": "abm_realized_engagement", "direct_outcome": "provider_engage_on_shared_seed_batch_0",
        "direct_rate_threshold": 0.05, "realized_rate_threshold": v2._RATE_THRESHOLD,
        "bootstrap": {"seed": historical._BOOTSTRAP_SEED, "iterations": historical._BOOTSTRAP_ITERATIONS,
                      "block": "predeclared_seed_user_all_selected_messages", "interval": "percentile_2.5_97.5_linear_interpolation"},
        "cells": [], "message_slices": [], "segment_message_slices": [], "curves": [], "growth": [], "direct": [], "realized_contrasts": [],
        "identity_strata": evidence.document["identity_strata"], "accounting": evidence.document["counts"],
        "claim_boundary": "Fixed sample/graph; seed-only paired decision panel; adaptive paths descriptive; no equivalence/calibration/causal/external validity claim."}

    def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
        n = len(rows)
        return {"exposures": n, "judgment_positive": sum(r["provider_engage"] for r in rows),
            "judgment_rate": sum(r["provider_engage"] for r in rows) / n if n else None,
            "mean_probability": sum(r["provider_probability"] for r in rows) / n if n else None,
            "mean_confidence": sum(r["provider_confidence"] for r in rows) / n if n else None,
            "realized_positive": sum(r["realized_engage"] for r in rows),
            "realized_rate": sum(r["realized_engage"] for r in rows) / n if n else None,
            "campaign_positive_users": len({r["user_id"] for r in rows if r["realized_engage"]}),
            **{a: sum(r["realized_action"] == a for r in rows) for a in ("like", "comment", "share", "ignore")}}

    for model in MODELS:
        for prompt in PROMPTS:
            rows = by_cell[model, prompt]
            dims = {"model": model, "prompt": prompt}
            result["cells"].append({**dims, **summarize(rows)})
            for message in MESSAGES:
                selected = [r for r in rows if r["message_id"] == message]
                result["message_slices"].append({**dims, "message": message, **summarize(selected)})
                for segment in ("S1", "S2", "S3"):
                    result["segment_message_slices"].append({**dims, "message": message, "segment": segment,
                        **summarize([r for r in selected if evidence.membership[r["user_id"]] == segment])})
                for batch in range(30):
                    cumulative = [r for r in selected if r["time_step"] <= batch]
                    a = {r["user_id"] for r in cumulative}
                    b = {r["user_id"] for r in by_cell[MODELS[-1], prompt] if r["message_id"] == message and r["time_step"] <= batch}
                    result["curves"].append({**dims, "message": message, "batch": batch, **summarize(cumulative),
                        "reference_cell": f"{prompt}::{MODELS[-1]}", "audience_jaccard_distance": 1 - len(a & b) / len(a | b)})
            previous: set[str] = set()
            for batch in range(30):
                positives = {r["user_id"] for r in rows if r["time_step"] == batch and r["realized_engage"]}
                commit = next(c for c in evidence.commits if c["cell_id"] == f"{prompt}::{model}" and c["time_step"] == batch)
                if set(commit["frozen_campaign_engaged_user_ids"]) != previous or set(commit["committed_realized_positive_user_ids"]) != positives:
                    raise ValueError("Analysis growth differs from full-batch feedback barrier")
                result["growth"].append({**dims, "batch": batch, "new_positive_users": len(positives - previous), "cumulative_positive_users": len(previous | positives)})
                previous |= positives
            for comparison, reference in (("prompt_within_model", (model, "P0")), ("model_within_prompt", (MODELS[-1], prompt))):
                left, right = fixed[model, prompt], fixed[reference]
                for message in ("all", *MESSAGES):
                    keys = sorted(k for k in seed_pairs if message == "all" or k[1] == message)
                    users = sorted({k[0] for k in keys})
                    n = len(keys)
                    transitions = Counter(f"{right[k]['provider_action']}->{left[k]['provider_action']}" for k in keys)
                    entry = {**dims, "comparison": comparison, "message": message, "reference_cell": f"{reference[1]}::{reference[0]}",
                        "pairs": n, "user_blocks": len(users),
                        "engage_rate": sum(left[k]["provider_engage"] for k in keys) / n,
                        "mean_probability": sum(left[k]["provider_probability"] for k in keys) / n,
                        "mean_confidence": sum(left[k]["provider_confidence"] for k in keys) / n,
                        "engage_disagreements": sum(left[k]["provider_engage"] != right[k]["provider_engage"] for k in keys),
                        "action_transitions": dict(sorted(transitions.items())),
                        "observed_identity_counts": dict(Counter(left[k]["observed_model"] for k in keys))}
                    for field in ("engage", "probability", "confidence"):
                        values = {u: sum(float(left[k]["provider_" + field]) - float(right[k]["provider_" + field]) for k in keys if k[0] == u) / sum(k[0] == u for k in keys) for u in users}
                        estimate = sum(values.values()) / len(users)
                        rng = random.Random(historical._BOOTSTRAP_SEED)
                        replicates = [sum(values[users[rng.randrange(len(users))]] for _ in users) / len(users) for _ in range(historical._BOOTSTRAP_ITERATIONS)]
                        entry[field + "_delta"] = estimate
                        entry[field + "_lower_95"] = historical._quantile(replicates, 0.025)
                        entry[field + "_upper_95"] = historical._quantile(replicates, 0.975)
                    entry["direct_rate_label"] = historical._threshold_classification(entry["engage_delta"], 0.05)
                    entry["direct_probability_label"] = historical._threshold_classification(entry["probability_delta"], 0.05)
                    result["direct"].append(entry)
                delta = summarize(rows)["realized_rate"] - summarize(by_cell[reference])["realized_rate"]
                result["realized_contrasts"].append({**dims, "comparison": comparison, "reference_cell": f"{reference[1]}::{reference[0]}", "rate_delta": delta, "threshold": v2._RATE_THRESHOLD, "label": v2._difference_label(delta), "scope": "descriptive_adaptive_path"})
    rates = {(r["model"], r["prompt"]): r["realized_rate"] for r in result["cells"]}
    result["planned_contrasts"] = []
    for model in MODELS[:-1]:
        delta = round(sum(rates[model, p] - rates[MODELS[-1], p] for p in PROMPTS) / 4, 12)
        result["planned_contrasts"].append(dict(factor="model", model=model, prompt="all", reference=MODELS[-1], rate_delta=delta, label=v2._difference_label(delta), scope="descriptive_adaptive_path"))
    for prompt in PROMPTS[1:]:
        delta = round(sum(rates[m, prompt] - rates[m, "P0"] for m in MODELS) / 4, 12)
        result["planned_contrasts"].append(dict(factor="prompt", model="all", prompt=prompt, reference="P0", rate_delta=delta, label=v2._difference_label(delta), scope="descriptive_adaptive_path"))
    result["prompt_model_interactions"] = []
    for model in MODELS[:-1]:
        for prompt in PROMPTS[1:]:
            delta = round((rates[model, prompt] - rates[model, "P0"]) - (rates[MODELS[-1], prompt] - rates[MODELS[-1], "P0"]), 12)
            result["prompt_model_interactions"].append(dict(model=model, prompt=prompt, reference_model=MODELS[-1], reference_prompt="P0", rate_delta=delta, label=v2._difference_label(delta), scope="descriptive_adaptive_path"))
    if sum(r["exposures"] for r in result["cells"]) != 28800 or len(result["curves"]) != 1440 or len(result["growth"]) != 480:
        raise ValueError("Analysis denominators do not close")
    return result
