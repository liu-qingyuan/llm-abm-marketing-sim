"""Independent, nondeployable network intervention over immutable Formal judgments.

The existing source consumers remain authoritative. This contract deliberately does
not masquerade as the old two-stage contract or alter its random source identity.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import tempfile
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from . import full_pool_two_stage_replay as old
from .concurrent_message_experiment import (
    _ConcurrentRuntimeKernel,
    _prepare_full_pool_concurrent_runtime_inputs,
    _primary_variant_profile,
    _rank_message_candidates,
    _select_batch_candidates,
)
from .decision import DecisionInput
from .engagement_realization import EngagementRealizationPolicy, FullPoolRealizedTerminal
from .full_pool_source_v4 import read_closed_strict_full_pool_source
from .prompting import build_engagement_prompt
from .schemas import PeerContext, PlatformContext, UserProfile

SCHEMA = "full-pool-ten-topic-network-replay-v1"
POLICY = "final-collected-topics-holdout-safe-comment-reply-mention-v1"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _bank(root: Path) -> dict[tuple[str, str], dict[str, Any]]:
    bank = {}
    for row in old._iter_canonical_jsonl(root / "realized-terminal-rows.jsonl"):
        key = (str(row["user_id"]), str(row["message_id"]))
        _require(key not in bank, "duplicate old realized pair")
        bank[key] = row
    return bank


def _reuse_fields(row: dict[str, Any]) -> dict[str, Any]:
    return {
        k: v
        for k, v in row.items()
        if k
        not in {
            "realized_terminal_id",
            "replay_pair_id",
            "replay_pair_schedule_position",
            "replay_time_step",
        }
    }


def _lineage(final: Path, config: Any, prepared: Any) -> dict[str, Any]:
    audit = old._json_object(final / "scope_change_audit.json", "final topic correction")
    report = old._json_object(final / "final_collection_report.json", "final collection lineage")
    topics: dict[tuple[str, str], int] = Counter()
    historical: Counter[str] = Counter()
    with (final / "videos.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            topics[(row["source_challenge_id"], row["source_challenge_name"])] += 1
            if row["video_id"] != config.sample_holdout_video_id:
                historical[row["source_challenge_name"]] += 1
    names = {name for _, name in topics}
    _require(
        len(topics) == 10 and names == {x.lstrip("#") for x in audit["corrected_caption_hashtags"]},
        "final ten-topic lineage does not match corrected scope",
    )
    files = []
    for name in ["videos.csv", "all_comments.csv"]:
        digest = old._sha256_file(final / name)
        _require(digest == old._sha256_file(config.dataset_dir / name), "latent and final interaction bytes differ")
        _require(digest == report["tables"][name]["sha256"], "final interaction bytes differ from collection lineage")
    for name in ["videos.csv", "all_comments.csv", "scope_change_audit.json", "final_collection_report.json"]:
        files.append(old._file_ref(final, final / name))
    graph = prepared.cohort.comment_graph
    graph_identity = old._json_sha256(
        {
            "scope": POLICY,
            "holdout": config.sample_holdout_video_id,
            "edges": [[a, b, w] for (a, b), w in sorted(graph.edge_weights.items())],
            "degrees": sorted(graph.weighted_degree_by_user.items()),
            "neighbors": [[u, sorted(n)] for u, n in sorted(graph.neighbors_by_user.items())],
            "p95": graph.p95_weighted_degree,
        }
    )
    return {
        "policy": POLICY,
        "final_dataset": str(final),
        "files": files,
        "topics": [
            {"id": i, "name": n, "videos": c, "historical_videos": historical[n]}
            for (i, n), c in sorted(topics.items())
        ],
        "holdout_video_ids": [config.sample_holdout_video_id],
        "historical_videos": prepared.cohort.historical_video_count,
        "historical_comments": prepared.cohort.historical_interaction_rows,
        "edge_count": len(graph.edge_weights),
        "edge_weight_sum": sum(graph.edge_weights.values()),
        "graph_nodes": len(graph.weighted_degree_by_user),
        "p95_reference_users": len(prepared.cohort.users_by_id),
        "p95_weighted_degree": graph.p95_weighted_degree,
        "graph_identity": graph_identity,
        "normalization": "min(1,log1p(weighted_degree)/log1p(P95)); zero-degree=0",
        "local_activity_global_changed": False,
    }


def _inputs(judgment_root: Path, realized_root: Path, final: Path) -> tuple[Any, ...]:
    print("Validating immutable Source-v4 contract", flush=True)
    closed = read_closed_strict_full_pool_source(
        judgment_root, manifest_sha256=old._sha256_file(judgment_root / "manifest.json")
    )
    print("Validating immutable old realized contract", flush=True)
    realized = old.read_closed_full_pool_two_stage_source(
        realized_root, manifest_sha256=old._sha256_file(realized_root / "manifest.json")
    )
    _require(
        closed.facts.production_deploy_eligible and realized.production_deploy_eligible,
        "requires existing Formal evidence, not a validation fixture",
    )
    _require(
        realized.manifest["upstream_source"]["source_identity"] == closed.source_identity
        and realized.manifest["upstream_source"]["manifest_sha256"] == closed.manifest_sha256,
        "old realization is not bound to the judgment source",
    )
    config, legacy, dataset = old._prepare_replay_runtime(closed)
    _require(config.network_scope == "legacy_target_topic", "expected historical single-topic source")
    _require(
        (config.sample_size, config.horizon, config.delivery_capacity) == (36400, 30, 1214), "incorrect main topology"
    )
    config = config.model_copy(update={"network_scope": "final_collected_topics"})
    prepared = _prepare_full_pool_concurrent_runtime_inputs(
        config, seed_top_k_per_proxy=dataset["seed_top_k_per_proxy"]
    )
    _require(
        prepared.cohort.users_by_id == legacy.cohort.users_by_id
        and prepared.cohort.sample_user_ids == legacy.cohort.sample_user_ids
        and prepared.cohort.seed_user_ids == legacy.cohort.seed_user_ids
        and prepared.cohort.thresholds == legacy.cohort.thresholds,
        "network intervention changed users, proxies, membership or seed union",
    )
    network = _lineage(final, config, prepared)
    network["old_p95_weighted_degree"] = legacy.cohort.comment_graph.p95_weighted_degree
    network["old_edge_count"] = len(legacy.cohort.comment_graph.edge_weights)
    bank = _bank(realized_root)
    _require(len(bank) == 109200, "old realization coverage is incomplete")
    messages = {m.message_id: m for m in config.messages}
    identity = old._json_object(judgment_root / "runtime/fresh-run-identity.json", "old identity")
    from .prompt_contracts import CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY

    _require(
        identity["prompt_contract"]["primary"]
        == json.loads(json.dumps(CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.resolve("P0").audit_record())),
        "P0 prompt contract changed",
    )
    policy = EngagementRealizationPolicy(source_identity=closed.source_identity)
    seen = set()
    input_hashes = []
    print("Checking all 109200 visible inputs, judgments and original draws", flush=True)
    for terminal in old._iter_source_terminal_rows(closed):
        judgment = old._provider_judgment_from_terminal(closed, terminal)
        key = judgment.user_id, judgment.message_id
        _require(key not in seen and key in bank, "duplicate or missing source pair")
        seen.add(key)
        current_profile = _primary_variant_profile(prepared.cohort.users_by_id[judgment.user_id])
        prior_profile = UserProfile.model_validate(json.loads(str(terminal["context_profile_payload"])))
        prior_peer = PeerContext.model_validate(json.loads(str(terminal["peer_context_payload"])))
        current = DecisionInput(
            post=messages[judgment.message_id].as_post(),
            profile=current_profile,
            peer_context=PeerContext(),
            platform_context=PlatformContext(),
            time_step=0,
            prompt_version=judgment.prompt_version,
        )
        prior = current.model_copy(update={"profile": prior_profile, "peer_context": prior_peer})
        _require(build_engagement_prompt(current) == build_engagement_prompt(prior), "model-visible input changed")
        _require(
            judgment.prompt_version == identity["configuration"]["primary_prompt_version"], "prompt version crossed"
        )
        row = bank[key]
        outcome = policy.realize(judgment.decision, user_id=key[0], message_id=key[1])
        _require({k: row[k] for k in asdict(outcome)} == asdict(outcome), "old per-pair draw or realization differs")
        _require(
            row["upstream_source_identity"] == closed.source_identity
            and row["upstream_terminal_row_id"] == judgment.terminal_row_id
            and row["upstream_pair_id"] == judgment.pair_id,
            "old realization provenance crossed",
        )
        for field in ["engage", "probability", "action", "reason", "confidence", "decision_source"]:
            _require(row["provider_" + field] == getattr(judgment.decision, field), "old judgment differs")
        input_hashes.append((key[0], key[1], old._json_sha256(build_engagement_prompt(current))))
    _require(seen == set(bank), "judgment and realization denominators differ")
    preflight = {
        "judgment_pairs": len(seen),
        "visible_input_matches": len(seen),
        "draw_matches": len(seen),
        "client_input_inventory_sha256": old._json_sha256(sorted(input_hashes)),
        "provider_calls": 0,
        "seed_union_unchanged": True,
        "proxies_unchanged": True,
    }
    return closed, realized, config, prepared, network, preflight, bank


def _verify_rows(
    root: Path,
    manifest: dict[str, Any],
    prepared: Any,
    config: Any,
    closed: Any,
    bank: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    commits = list(old._iter_canonical_jsonl(root / "batch-commits.jsonl"))
    facts = old._validate_streamed_rows(
        root=root,
        manifest=manifest,
        upstream={"source_identity": closed.source_identity, "production_deploy_eligible": True},
        membership=closed.membership,
        commits=commits,
    )
    _require(
        facts.action_counts == manifest["action_counts"] and facts.projection_rows == manifest["projection_rows"],
        "result aggregates are crossed",
    )
    candidates = iter(old._iter_canonical_jsonl(root / "candidate-rows.jsonl"))
    exposed = {m.message_id: set() for m in config.messages}
    candidate_count = 0
    for step, commit in enumerate(commits):
        frozen = set(commit["frozen_realized_positive_user_ids"])
        for message in config.messages:
            ranked = _rank_message_candidates(
                message=message,
                users_by_id=prepared.cohort.users_by_id,
                eligible_user_ids=[u for u in prepared.cohort.sample_user_ids if u not in exposed[message.message_id]],
                base_network_by_user=prepared.base_network_by_user,
                neighbors_by_user=prepared.neighbors_by_user,
                campaign_engaged_user_ids=frozen,
            )
            selected, reasons = _select_batch_candidates(
                time_step=step,
                ranked_scores=ranked,
                seed_user_ids=prepared.cohort.seed_user_ids,
                delivery_capacity=config.delivery_capacity,
            )
            _require(len(selected) == (1214 if step < 29 else 1194), "batch exposure capacity changed")
            summary = next(s for s in commit["messages"] if s["message_id"] == message.message_id)
            _require(summary["selected_user_ids"] == [s.user_id for s in selected], "selection or tie order differs")
            for position, score in enumerate(ranked, 1):
                expected = _ConcurrentRuntimeKernel._candidate_row(
                    time_step=step,
                    message_id=message.message_id,
                    ranking_position=position,
                    score=score,
                    selection_reason_by_user=reasons,
                    seed_user_ids=prepared.cohort.seed_user_ids,
                )
                _require(
                    next(candidates, None) == expected, "network score, tie sorting or frozen neighbor feedback differs"
                )
                candidate_count += 1
            exposed[message.message_id].update(s.user_id for s in selected)
    _require(next(candidates, None) is None and candidate_count == facts.candidate_row_count, "extra candidates")
    seen = set()
    changed_batch = 0
    for row in old._iter_canonical_jsonl(root / "realized-terminal-rows.jsonl"):
        FullPoolRealizedTerminal.model_validate(row)
        key = str(row["user_id"]), str(row["message_id"])
        _require(
            key not in seen and key in bank and _reuse_fields(row) == _reuse_fields(bank[key]),
            "judgment, draw or realized action reuse differs",
        )
        seen.add(key)
        changed_batch += row["replay_time_step"] != bank[key]["replay_time_step"]
    _require(seen == set(bank) and all(len(e) == 36400 for e in exposed.values()), "exposure closure incomplete")
    return {
        "exposures": len(seen),
        "judgment_and_draw_matches": len(seen),
        "candidate_rows_recomputed": candidate_count,
        "pairs_with_changed_batch": changed_batch,
        "all_30_batch_barriers_verified": True,
        "seed_priority_and_tie_sort_verified": True,
        "final_action_counts_equal": Counter(r["realized_action"] for r in bank.values()) == facts.action_counts,
    }


def _write_comparison(root: Path, rows: list[dict[str, Any]], bank: dict[tuple[str, str], dict[str, Any]]) -> None:
    # Per-message, per-batch raw and cumulative actions, from terminals rather than claims.
    new_counts: Counter[tuple[str, int, str]] = Counter()
    old_counts: Counter[tuple[str, int, str]] = Counter()
    for r in old._iter_canonical_jsonl(root / "realized-terminal-rows.jsonl"):
        new_counts[(str(r["message_id"]), int(r["replay_time_step"]), str(r["realized_action"]))] += 1
    for r in bank.values():
        old_counts[(str(r["message_id"]), int(r["replay_time_step"]), str(r["realized_action"]))] += 1
    with (root / "curve-comparison.csv").open("w", encoding="utf-8", newline="") as h:
        fields = [
            "message_id",
            "batch",
            "action",
            "old_count",
            "new_count",
            "delta",
            "old_cumulative",
            "new_cumulative",
        ]
        writer = csv.DictWriter(h, fieldnames=fields)
        writer.writeheader()
        for message in ["message_1", "message_2", "message_3"]:
            totals_old: Counter[str] = Counter()
            totals_new: Counter[str] = Counter()
            for step in range(30):
                for action in ["like", "comment", "share", "ignore"]:
                    a = old_counts[message, step, action]
                    b = new_counts[message, step, action]
                    totals_old[action] += a
                    totals_new[action] += b
                    writer.writerow(
                        dict(
                            zip(
                                fields,
                                [message, step + 1, action, a, b, b - a, totals_old[action], totals_new[action]],
                                strict=True,
                            )
                        )
                    )
    (root / "full-pool-realized-projection.csv").write_bytes(old._projection_csv_bytes(rows))


def run_ten_topic_replay(
    *, judgment_source: Path, realized_source: Path, final_dataset: Path, output_dir: Path
) -> dict[str, Any]:
    """Validate explicit old contracts, reuse every judgment/draw, close a new network run.

    No Provider is accepted or constructed. A missing/different visible input fails
    before runtime execution. The output is independent and never deploy-eligible.
    """
    judgment_source = old._explicit_directory(judgment_source, "judgment source")
    realized_source = old._explicit_directory(realized_source, "realized source")
    final_dataset = old._explicit_directory(final_dataset, "final dataset")
    output_dir = old._new_output_path(output_dir, source=judgment_source)
    _require(
        not output_dir.is_relative_to(realized_source) and not output_dir.is_relative_to(final_dataset),
        "output overlaps input",
    )
    protected = {str(p): old._source_snapshot(p) for p in [judgment_source, realized_source]}
    closed, realized, config, prepared, network, preflight, bank = _inputs(
        judgment_source, realized_source, final_dataset
    )
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}-", dir=output_dir.parent))
    published = False
    try:
        replay_identity = old._json_sha256(
            {
                "schema_version": SCHEMA,
                "upstream_source_identity": closed.source_identity,
                "network": network,
                "realization_source_identity": realized.source_identity,
                "configuration": config.snapshot(),
                "realization_seed": 20260823,
            }
        )
        old._write_json(staging / "preflight.json", preflight)
        old._write_json(staging / "network.json", network)
        print("Running full-pool offline network intervention", flush=True)
        store = old._ProviderJudgmentStore.build(closed, path=staging / ".judgments.sqlite3")
        try:
            runtime = old._run_replay_runtime(
                config=config,
                prepared=prepared,
                closed=closed,
                judgments=store,
                replay_identity=replay_identity,
                policy=EngagementRealizationPolicy(source_identity=closed.source_identity),
                workspace=staging / ".runtime",
                output_target=output_dir,
            )
        finally:
            store.close()
            old._remove_sqlite_files(staging / ".judgments.sqlite3")
        streamed = old._stream_runtime_artifacts(staging=staging, closed=closed, config=config, runtime=runtime)
        shutil.rmtree(runtime.workspace)
        shutil.copyfile(judgment_source / "latent-membership.csv", staging / "latent-membership.csv")
        manifest: dict[str, Any] = {
            "schema_version": SCHEMA,
            "replay_identity": replay_identity,
            "classification": "offline_formal_judgment_network_intervention",
            "production_deploy_eligible": False,
            "provider_calls": 0,
            "live_api_triggered": False,
            "upstream_formal_provider_accounting": {"provider_accounting": dict(closed.manifest["provider_accounting"])},
            "judgment_source": {
                "root": str(judgment_source),
                "manifest_sha256": closed.manifest_sha256,
                "identity": closed.source_identity,
            },
            "realized_source": {
                "root": str(realized_source),
                "manifest_sha256": realized.manifest_sha256,
                "identity": realized.source_identity,
            },
            "final_dataset": str(final_dataset),
            "network": network,
            "configuration": config.snapshot(),
            "realization_source_identity": closed.source_identity,
            "realization_seed": 20260823,
            "realization_rule_version": EngagementRealizationPolicy(
                source_identity=closed.source_identity
            ).realization_rule_version,
            "preflight": preflight,
            "action_counts": streamed.action_counts,
            "projection_rows": streamed.projection_rows,
            "counts": {
                "users": 36400,
                "messages": 3,
                "pairs": streamed.pair_row_count,
                "exposures": streamed.realized_terminal_count,
                "batches": streamed.batch_commit_count,
                "candidate_rows": streamed.candidate_row_count,
            },
        }
        print("Independently recomputing every candidate, barrier, draw and final count", flush=True)
        manifest["verification"] = _verify_rows(staging, manifest, prepared, config, closed, bank)
        _write_comparison(staging, streamed.projection_rows, bank)
        for p in [judgment_source, realized_source]:
            _require(old._source_snapshot(p) == protected[str(p)], "protected historical source changed")
        _require(
            _lineage(final_dataset, config, prepared)["graph_identity"] == network["graph_identity"],
            "final lineage changed",
        )
        manifest["protected_before_after_equal"] = True
        manifest["artifacts"] = [old._file_ref(staging, p) for p in sorted(staging.iterdir())]
        manifest["source_identity"] = old._json_sha256(manifest)
        old._write_json(staging / "manifest.json", manifest)
        os.replace(staging, output_dir)
        published = True
        for ref in manifest["artifacts"]:
            _require(old._sha256_file(output_dir / ref["relative_path"]) == ref["sha256"], "published artifact changed")
        _require(
            old._json_object(output_dir / "manifest.json", "published manifest") == json.loads(json.dumps(manifest)),
            "manifest readback differs",
        )
        return manifest
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        if published:
            shutil.rmtree(output_dir)
        raise


def verify_ten_topic_replay(output_dir: Path) -> dict[str, Any]:
    """Reopen an independent replay and revalidate sources, network and all rows."""
    root = old._explicit_directory(output_dir, "ten-topic replay")
    manifest = old._json_object(root / "manifest.json", "ten-topic manifest")
    _require(
        manifest.get("schema_version") == SCHEMA
        and manifest.get("provider_calls") == 0
        and manifest.get("live_api_triggered") is False
        and manifest.get("production_deploy_eligible") is False,
        "ten-topic contract classification or Provider accounting differs",
    )
    _require(
        manifest["source_identity"] == old._json_sha256({k: v for k, v in manifest.items() if k != "source_identity"}),
        "ten-topic source identity differs",
    )
    expected_files = {ref["relative_path"] for ref in manifest["artifacts"]} | {"manifest.json"}
    _require(
        expected_files == {p.name for p in root.iterdir()}
        and all(p.is_file() and not p.is_symlink() for p in root.iterdir()),
        "ten-topic artifact inventory is not exact",
    )
    for ref in manifest["artifacts"]:
        _require(old._file_ref(root, root / ref["relative_path"]) == ref, "ten-topic artifact hash differs")
    closed, realized, config, prepared, network, preflight, bank = _inputs(
        Path(manifest["judgment_source"]["root"]),
        Path(manifest["realized_source"]["root"]),
        Path(manifest["final_dataset"]),
    )
    _require(
        manifest["judgment_source"]
        == {"root": str(closed.root), "manifest_sha256": closed.manifest_sha256, "identity": closed.source_identity}
        and manifest["realized_source"]
        == {
            "root": str(realized.root),
            "manifest_sha256": realized.manifest_sha256,
            "identity": realized.source_identity,
        },
        "ten-topic source lineage differs",
    )
    _require(
        network == manifest["network"]
        and preflight == manifest["preflight"]
        and old._json_object(root / "network.json", "network") == network
        and old._json_object(root / "preflight.json", "preflight") == preflight,
        "ten-topic input proof differs",
    )
    _require(
        config.snapshot() == manifest["configuration"]
        and manifest["realization_source_identity"] == closed.source_identity
        and manifest["realization_seed"] == 20260823,
        "ten-topic configuration or draw anchor differs",
    )
    expected_identity = old._json_sha256(
        {
            "schema_version": SCHEMA,
            "upstream_source_identity": closed.source_identity,
            "network": network,
            "realization_source_identity": realized.source_identity,
            "configuration": config.snapshot(),
            "realization_seed": 20260823,
        }
    )
    _require(manifest["replay_identity"] == expected_identity, "ten-topic replay identity differs")
    verification = _verify_rows(root, manifest, prepared, config, closed, bank)
    _require(verification == manifest["verification"], "ten-topic verification result differs")
    _require(
        (root / "latent-membership.csv").read_bytes() == (closed.root / "latent-membership.csv").read_bytes(),
        "membership differs",
    )
    _require(
        (root / "full-pool-realized-projection.csv").read_bytes()
        == old._projection_csv_bytes(manifest["projection_rows"]),
        "projection download differs",
    )
    return verification
