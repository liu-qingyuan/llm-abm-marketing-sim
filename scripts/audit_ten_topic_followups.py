#!/usr/bin/env python3
"""Offline eligible-input inventory; no dynamic paths and no Provider calls."""

from __future__ import annotations

import argparse
import csv
import dataclasses
import importlib.util
import json
from collections import Counter
from pathlib import Path
from typing import Any

from llm_abm_sim import _parameter_judgment_bank as bank
from llm_abm_sim import final_research as fr
from llm_abm_sim.concurrent_message_experiment import (
    _message_user_fit_components,
    _prepare_concurrent_runtime_inputs,
    _primary_variant_profile,
    _runtime_inputs_from_cohort,
)
from llm_abm_sim.decision import DecisionInput
from llm_abm_sim.prompt_contracts import CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY
from llm_abm_sim.prompting import build_engagement_prompt
from llm_abm_sim.schemas import PeerContext, PlatformContext


def _pair_input_key(row: dict[str, Any]) -> tuple[str, str, str]:
    """A matching client message never licenses reusing another user's judgment."""
    return row["user_id"], row["message_id"], row["client_condition_sha256"]


def _missing_identity(row: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return row["model"], row["template"], row["user_id"], row["message_id"], row["client_identity"]


def rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def _costs(four: Path, index: Path, output: Path, results: list[dict[str, Any]]) -> None:
    attempts = rows(four / "attempts.jsonl")
    by_cell: dict[tuple[str, str], list[dict[str, Any]]] = {}
    routes: Counter[tuple[str, str, str, str]] = Counter()
    judgments = rows(four / "judgments.jsonl")
    for row in judgments:
        for attempt in row["successful_attempts"]:
            if attempt.get("outcome") != "succeeded":
                continue
            route = attempt.get("provider_route", "unknown")
            routes[row["requested_model"], row["prompt_variant"], route, row["observed_model"]] += 1
    for row in attempts:
        variant = "P" + str(int(row["cell_index"]) % 4)
        by_cell.setdefault((row["requested_model"], variant), []).append(row["attempt"])
    cost_rows = []
    evidence_rows = []
    for (model, template), group in sorted(by_cell.items()):
        success = [a for a in group if isinstance(a, dict) and a.get("outcome") == "succeeded"]
        nominal = [
            a["subscription_nominal_cost_usd"] for a in success if a.get("subscription_nominal_cost_usd") is not None
        ]
        fees = [a["provider_fee_cny"] for a in success if a.get("provider_fee_cny") is not None]
        input_tokens = [a["input_usage"] for a in success if a.get("input_usage") is not None]
        output_tokens = [a["output_usage"] for a in success if a.get("output_usage") is not None]
        record = {
            "model": model,
            "template": template,
            "historical_physical_attempts": len(group),
            "successes_with_accounting": len(success),
            "known_fee_attempts": len(fees),
            "known_fee_cny_subtotal": sum(fees) if fees else None,
            "mean_known_provider_fee_cny": sum(fees) / len(fees) if fees else None,
            "known_nominal_attempts": len(nominal),
            "known_nominal_usd_subtotal": sum(nominal) if nominal else None,
            "mean_known_nominal_usd": sum(nominal) / len(nominal) if nominal else None,
            "mean_known_input_tokens": sum(input_tokens) / len(input_tokens) if input_tokens else None,
            "mean_known_output_tokens": sum(output_tokens) / len(output_tokens) if output_tokens else None,
            "actual_full_fee": None,
            "limitations": "Known settled response subtotals only; missing usage/fees and unknown attempts retained. No invoice; routes may be mixed.",
        }
        evidence_rows.append(record)
        nominal_complete = bool(success) and len(nominal) == len(success)
        fees_complete = bool(success) and len(fees) == len(success)
        for result in results:
            if result["experiment"] != "four_model" or result["model"] != model or result["template"] != template:
                continue
            gap = result["missing"]
            cost_rows.append(
                {
                    "experiment": result["experiment"],
                    "mode": result["mode"],
                    "arm": result["arm"],
                    "model": model,
                    "template": template,
                    "complete_bank_missing": gap,
                    "estimated_nominal_usd_complete_bank": gap * record["mean_known_nominal_usd"]
                    if nominal_complete
                    else None,
                    "estimated_fee_cny_complete_bank": gap * record["mean_known_provider_fee_cny"]
                    if fees_complete
                    else None,
                    "actual_incremental_fee_this_run": 0,
                    "actual_provider_calls_this_run": 0,
                    "interpretation": "historical response-mean extrapolation for complete-bank inventory, not exposure-path budget; excludes retries/qualification; unknown prices remain null",
                }
            )
    index_closure = bank.read_json(index / "exposure-bank-closure.json")
    mean_index = index_closure["known_nominal_cost_usd"] / (
        index_closure["physical_requests"] - index_closure["nominal_cost_unknown_attempts"]
    )
    for result in results:
        if result["experiment"] == "four_model":
            continue
        cost_rows.append(
            {
                "experiment": result["experiment"],
                "mode": result["mode"],
                "arm": result["arm"],
                "model": result["model"],
                "template": result["template"],
                "complete_bank_missing": result["missing"],
                "estimated_nominal_usd_complete_bank": result["missing"] * mean_index,
                "estimated_fee_cny_complete_bank": None,
                "actual_incremental_fee_this_run": 0,
                "actual_provider_calls_this_run": 0,
                "interpretation": "historical GPT subscription nominal USD response mean; not actual cash fee, not adaptive-path budget; arms share exact inputs and must not be summed",
            }
        )
    with (output / "cost-estimates.csv").open("w", encoding="utf-8", newline="") as h:
        writer = csv.DictWriter(h, fieldnames=list(cost_rows[0]))
        writer.writeheader()
        writer.writerows(cost_rows)
    bank.write_json(
        output / "cost-evidence.json",
        {
            "historical_costs": evidence_rows,
            "index_nominal_evidence": index_closure,
            "index_known_response_mean_usd": mean_index,
            "routes": [
                {"model": m, "template": p, "route": r, "observed_model": o, "successful_judgments": n}
                for (m, p, r, o), n in sorted(routes.items())
            ],
            "mixed_kimi_rule": "Kimi legacy subscription k3-256k and official kimi-k3 are separate observed strata. Reuse requires original per-pair route/model condition or explicit inherited mixed-evidence acceptance, not uniform official-model equivalence.",
            "sources": [
                {"path": str(p), "sha256": bank.file_hash(p)}
                for p in [four / "attempts.jsonl", four / "judgments.jsonl", index / "exposure-bank-closure.json"]
            ],
            "actual_provider_calls": 0,
            "actual_incremental_fee": 0,
            "new_prices_looked_up": False,
        },
    )


def main(repo: Path, output: Path) -> None:
    if output.exists():
        raise ValueError("new audit output required")
    index = repo / "runs/gpt-p0-index-sensitivity-20260920-formal-01"
    topup = repo / "runs/gpt-p0-bank-topup-20260917-authorized-01"
    four = repo / "outputs/01a08bb3-1446-7f51-8933-cd49b50e9ccb/four-model-final-20260912-verified"
    preparation = bank.read_json(topup / "preparation.json")
    # This reconstructs the old single-topic source via its original closure.
    config, legacy, source = bank._inputs(bank.read_json(Path(preparation["audit"]["path"])))
    new_config = config.model_copy(update={"network_scope": "final_collected_topics"})
    merged = _prepare_concurrent_runtime_inputs(new_config)
    assert all(
        _primary_variant_profile(u) == _primary_variant_profile(legacy.cohort.users_by_id[uid])
        for uid, u in merged.cohort.users_by_id.items()
    )
    spec = importlib.util.spec_from_file_location("historical_index_study", index / "study.py")
    assert spec and spec.loader
    study = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(study)
    manifest = bank.read_json(four / "artifact_manifest.json")
    protected = []
    for ref in manifest["artifacts"]:
        p = Path(ref["path"])
        if bank.file_hash(p) != ref["sha256"]:
            raise ValueError("four-model source artifact hash drift")
        protected.append({"path": str(p), "sha256": ref["sha256"]})
    parameter_rows = rows(topup / "closed-bank.jsonl")
    index_rows = rows(index / "unattempted-stage-01/closed-bank.jsonl")
    closure = bank.read_json(index / "exposure-bank-closure.json")
    assert bank.file_hash(index / "unattempted-stage-01/closed-bank.jsonl") == closure["bank_sha256"]
    for p in [
        topup / "closed-bank.jsonl",
        index / "unattempted-stage-01/closed-bank.jsonl",
        topup / "preparation.json",
        index / "prepared/inputs.json",
        index / "prepared/cohorts.json",
    ]:
        protected.append({"path": str(p), "sha256": bank.file_hash(p)})
    condition = preparation["request_condition"]
    parameter_keys = {_pair_input_key(r) for r in parameter_rows}
    index_keys = {_pair_input_key(r) for r in index_rows}
    # Extra GPT P0 bank rows can be reused only on their exact observed client condition.
    all_gpt_keys = parameter_keys | index_keys
    cohorts = bank.read_json(index / "prepared/cohorts.json")
    old_index_maps = bank.read_json(index / "prepared/inputs.json")
    old_cohorts = {r["arm"]: r for r in cohorts} if isinstance(cohorts, list) else cohorts
    four_rows = rows(four / "judgments.jsonl")
    four_bank: dict[tuple[str, str, str, str], str] = {}
    for r in four_rows:
        uid = r["user_id"]
        variant = r["prompt_variant"]
        mid = r["message_id"]
        message = next(m for m in config.messages if m.message_id == mid)
        token = CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.resolve(variant).prompt_version
        assert r["prompt_version"] == token
        assert r["prompt_canonical_hash"] == CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.resolve(variant).canonical_hash
        assert uid in legacy.cohort.sample_user_ids
        data = DecisionInput(
            post=message.as_post(),
            profile=_primary_variant_profile(legacy.cohort.users_by_id[uid]),
            peer_context=PeerContext(),
            platform_context=PlatformContext(),
            prompt_version=token,
            time_step=r["time_step"],
        )
        key = r["requested_model"], variant, uid, mid
        assert key not in four_bank
        four_bank[key] = bank.fingerprint(build_engagement_prompt(data))
    results = []
    samples = []
    missing_rows = []
    input_inventory = []
    unknown_proofs = []
    variants = [c.variant_id for c in CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.all()]
    models = sorted({r["requested_model"] for r in four_rows})
    for mode in ["fixed_original", "reselected_merged"]:
        base = legacy if mode == "fixed_original" else merged
        # Always inject merged ranking/feedback graph, including fixed-membership scenario.
        base_cohort = dataclasses.replace(base.cohort, comment_graph=merged.cohort.comment_graph)
        p = _runtime_inputs_from_cohort(new_config, base_cohort)
        ids = base_cohort.sample_user_ids
        samples.append(
            {
                "experiment": "parameter_and_four_model",
                "mode": mode,
                "sample_user_ids": ids,
                "overlap_original": len(set(ids) & set(legacy.cohort.sample_user_ids)),
            }
        )
        hashes: dict[tuple[str, str], tuple[str, str]] = {}
        for uid in ids:
            for m in config.messages:
                data = DecisionInput(
                    post=m.as_post(),
                    profile=_primary_variant_profile(base_cohort.users_by_id[uid]),
                    peer_context=PeerContext(),
                    platform_context=PlatformContext(),
                    time_step=0,
                    prompt_version=config.snapshot().get(
                        "primary_prompt_version", "jinjiang-concurrent-message-primary-prompt-v1"
                    ),
                )
                hashes[uid, m.message_id] = bank.client_identity(data, condition)
        reusable = sum((uid, mid, ch) in all_gpt_keys for (uid, mid), (_, ch) in hashes.items())
        results.append(
            {
                "experiment": "recommendation_parameters",
                "arm": "21_settings_shared_bank",
                "mode": mode,
                "model": "openai-codex/gpt-5.6-sol",
                "template": "P0",
                "eligible_pairs": len(hashes),
                "reusable": reusable,
                "missing": len(hashes) - reusable,
                "same_study_bank_matches": sum(
                    (uid, mid, ch) in parameter_keys for (uid, mid), (_, ch) in hashes.items()
                ),
                "new_calls_complete_bank": len(hashes) - reusable,
                "changed_visible_inputs_common_users": 0,
            }
        )
        for (uid, mid), (_mh, ch) in hashes.items():
            if (uid, mid, ch) not in all_gpt_keys:
                missing_rows.append(
                    {
                        "experiment": "recommendation_parameters",
                        "mode": mode,
                        "model": "openai-codex/gpt-5.6-sol",
                        "template": "P0",
                        "user_id": uid,
                        "message_id": mid,
                        "client_identity": ch,
                    }
                )
        for variant in variants:
            token = CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.resolve(variant).prompt_version
            for model in models:
                matches = 0
                own_matches = 0
                for uid in ids:
                    for m in config.messages:
                        data = DecisionInput(
                            post=m.as_post(),
                            profile=_primary_variant_profile(base_cohort.users_by_id[uid]),
                            peer_context=PeerContext(),
                            platform_context=PlatformContext(),
                            time_step=0,
                            prompt_version=token,
                        )
                        mh = bank.fingerprint(build_engagement_prompt(data))
                        old_hash = four_bank.get((model, variant, uid, m.message_id))
                        match = mh == old_hash
                        own_matches += match
                        # Parameter bank condition is verified only for the matching GPT/P0 route.
                        if model == "openai-codex/gpt-5.6-sol" and variant == "P0":
                            match = (
                                match or (uid, m.message_id, bank.client_identity(data, condition)[1]) in all_gpt_keys
                            )
                        matches += match
                        if not match:
                            missing_rows.append(
                                {
                                    "experiment": "four_model",
                                    "mode": mode,
                                    "model": model,
                                    "template": variant,
                                    "user_id": uid,
                                    "message_id": m.message_id,
                                    "client_identity": mh,
                                }
                            )
                results.append(
                    {
                        "experiment": "four_model",
                        "arm": "all_eligible_inputs",
                        "mode": mode,
                        "model": model,
                        "template": variant,
                        "eligible_pairs": 3000,
                        "reusable": matches,
                        "missing": 3000 - matches,
                        "same_study_bank_matches": own_matches,
                        "new_calls_complete_bank": 3000 - matches,
                        "changed_visible_inputs_common_users": 0,
                    }
                )
        for arm in study.ARMS:
            users = study.changed_users(base_cohort, arm)
            selected = study.selection(new_config, base_cohort, users)
            if mode == "fixed_original":
                arm_ids = old_cohorts[arm]["sample_user_ids"]
            else:
                arm_ids = selected.sample_user_ids if arm.endswith("_rebuilt") else ids
            seeds = (
                selected.seed_user_ids
                if mode != "fixed_original" and arm.endswith("_rebuilt")
                else fr._influence_seed_union({u: users[u] for u in arm_ids}, top_k_per_proxy=10)[2]
            )
            arm_cohort = dataclasses.replace(
                base_cohort, users_by_id=users, sample_user_ids=arm_ids, seed_user_ids=seeds
            )
            arm_prepared = _runtime_inputs_from_cohort(new_config, arm_cohort)
            original_ids = set(old_cohorts[arm]["sample_user_ids"])
            samples.append(
                {
                    "experiment": "index_sensitivity",
                    "arm": arm,
                    "mode": mode,
                    "sample_user_ids": arm_ids,
                    "overlap_original": len(set(arm_ids) & original_ids),
                }
            )
            matched = 0
            same_study = 0
            changed_visible = 0
            old_map = {(r["user_id"], r["message_id"]): r for r in old_index_maps[arm]}
            for uid in arm_ids:
                for m in config.messages:
                    data = study.decision_input(config, arm_prepared, condition, uid, m.message_id)
                    mh, ch = bank.client_identity(data, condition)
                    prior_input = old_map.get((uid, m.message_id))
                    if prior_input is not None:
                        changed_visible += (mh, ch) != (
                            prior_input["client_messages_sha256"],
                            prior_input["client_condition_sha256"],
                        )
                    match = (uid, m.message_id, ch) in all_gpt_keys
                    matched += match
                    same_study += (uid, m.message_id, ch) in index_keys
                    key = study.key({"user_id": uid, "message_id": m.message_id, "client_condition_sha256": ch})
                    input_inventory.append(
                        {
                            "experiment": "index_sensitivity",
                            "arm": arm,
                            "mode": mode,
                            "user_id": uid,
                            "message_id": m.message_id,
                            "client_messages_sha256": mh,
                            "client_condition_sha256": ch,
                            "key": key,
                        }
                    )
                    if not match:
                        missing_rows.append(
                            {
                                "experiment": "index_sensitivity",
                                "arm": arm,
                                "mode": mode,
                                "model": "openai-codex/gpt-5.6-sol",
                                "template": "P0",
                                "user_id": uid,
                                "message_id": m.message_id,
                                "client_identity": ch,
                            }
                        )
                    if key in {r["key"] for r in closure["unknowns"]}:
                        sample_set = set(arm_ids)
                        scores = {
                            u: 0.5 * arm_prepared.base_network_by_user[u]
                            + 0.2 * _message_user_fit_components(m, users[u])[1]
                            for u in sample_set
                        }
                        n = len(arm_prepared.neighbors_by_user.get(uid, set()) & sample_set)
                        upper = scores[uid] + 0.3 * min(1, n / 3)
                        higher = [u for u, v in scores.items() if u != uid and (v > upper or (v == upper and u < uid))]
                        unknown_proofs.append(
                            {
                                "mode": mode,
                                "arm": arm,
                                "key": key,
                                "sample_neighbor_count": n,
                                "score_upper_bound": upper,
                                "always_higher_candidates": len(higher),
                                "capacity": 600,
                                "is_seed": uid in seeds,
                                "proven_unexposed_under_new_network": uid not in seeds and len(higher) >= 600,
                            }
                        )
            results.append(
                {
                    "experiment": "index_sensitivity",
                    "arm": arm,
                    "mode": mode,
                    "model": "openai-codex/gpt-5.6-sol",
                    "template": "P0",
                    "eligible_pairs": 3000,
                    "reusable": matched,
                    "missing": 3000 - matched,
                    "same_study_bank_matches": same_study,
                    "new_calls_complete_bank": 3000 - matched,
                    "changed_visible_inputs_common_users": changed_visible,
                }
            )
    # Count unique client identities, never multiply by seeds or by topic count.
    totals = []
    for mode in ["fixed_original", "reselected_merged"]:
        for exp in ["recommendation_parameters", "index_sensitivity", "four_model"]:
            keys = {_missing_identity(r) for r in missing_rows if r["mode"] == mode and r["experiment"] == exp}
            totals.append(
                {
                    "mode": mode,
                    "experiment": exp,
                    "unique_missing_inputs_complete_bank": len(keys),
                    "exposure_path_new_calls": None,
                    "budget_status": "inventory_not_authorized_budget",
                    "reason": "No subsequent paths executed. Eligible input gap is not actual adaptive exposure demand.",
                }
            )
    output.mkdir(parents=True)
    _costs(four, index, output, results)
    with (output / "reuse-and-gaps.csv").open("w", encoding="utf-8", newline="") as h:
        writer = csv.DictWriter(h, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
    bank.write_json(
        output / "audit.json",
        {
            "schema_version": "ten-topic-followup-input-audit-v1",
            "provider_calls": 0,
            "old_network_p95": legacy.cohort.comment_graph.p95_weighted_degree,
            "new_network_p95": merged.cohort.comment_graph.p95_weighted_degree,
            "baseline_sample_overlap": len(set(legacy.cohort.sample_user_ids) & set(merged.cohort.sample_user_ids)),
            "sample_size": 1000,
            "totals": totals,
            "results": results,
            "unknown_recheck": unknown_proofs,
            "exact_match_condition": "same user/message, complete rendered client messages, model, P0-P3 canonical contract and frozen observed request condition; network and time excluded from visible input",
            "full_pool_judgments_as_supplement": "not_counted: transport/request condition differs; no silent cross-contract acceptance",
            "path_execution": False,
        },
    )
    bank.write_json(output / "samples.json", samples)
    bank.write_jsonl(output / "missing-inputs.jsonl", missing_rows)
    bank.write_jsonl(output / "eligible-inputs.jsonl", input_inventory)
    for ref in protected:
        assert bank.file_hash(Path(ref["path"])) == ref["sha256"]
    bank.write_json(output / "protected-inputs.json", {"before_after_equal": True, "files": protected})
    print(
        json.dumps(
            {
                "totals": totals,
                "unknown_recheck": unknown_proofs,
                "sample_overlap": len(set(legacy.cohort.sample_user_ids) & set(merged.cohort.sample_user_ids)),
                "provider_calls": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    main(args.repo, args.output)
