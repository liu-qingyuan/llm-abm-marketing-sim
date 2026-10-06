import csv
from pathlib import Path

import pytest

from llm_abm_sim.concurrent_message_experiment import (
    ConcurrentMessageExperimentConfig,
    _prepare_full_pool_concurrent_runtime_inputs,
)
from llm_abm_sim.final_research import _TARGET_DELIVERY_RANKING_POLICY, _ResearchCohortPreparer
from llm_abm_sim.ten_topic_replay import run_ten_topic_replay
from tests.integration.test_full_pool_segmented_multibatch import _dataset


def test_merged_network_is_default_and_keeps_proxy_values(tmp_path: Path):
    dataset = _multitopic_dataset(tmp_path)
    config = ConcurrentMessageExperimentConfig(
        dataset_dir=dataset, sample_size=7, horizon=2, delivery_capacity=4, configuration_profile="validation"
    )
    merged = _prepare_full_pool_concurrent_runtime_inputs(config, seed_top_k_per_proxy=1)
    legacy = _prepare_full_pool_concurrent_runtime_inputs(
        config.model_copy(update={"network_scope": "legacy_target_topic"}), seed_top_k_per_proxy=1
    )
    assert merged.cohort.users_by_id == legacy.cohort.users_by_id
    assert merged.cohort.thresholds == legacy.cohort.thresholds
    assert merged.cohort.seed_user_ids == legacy.cohort.seed_user_ids
    assert merged.cohort.comment_graph != legacy.cohort.comment_graph
    assert config.snapshot()["network_scope"] == "final_collected_topics"
    assert "network_scope" not in config.model_copy(update={"network_scope": "legacy_target_topic"}).snapshot()


def test_preparer_uses_non_target_comments_and_preserves_holdout(tmp_path: Path):
    dataset = _multitopic_dataset(tmp_path)
    merged = _ResearchCohortPreparer(
        dataset_dir=dataset,
        sample_size=7,
        random_seed=1,
        model_policy=_TARGET_DELIVERY_RANKING_POLICY,
        holdout_video_ids=("7328592728139353363",),
    ).prepare_full_pool(seed_top_k_per_proxy=1)
    assert all(c.video_id != "7328592728139353363" for c in merged.historical_comments)
    assert merged.sample_audit["network_scope"] == "final_collected_topics"
    assert merged.sample_audit["network_source_topics"] == ["锦江之星"]
    assert sum(merged.comment_graph.weighted_degree_by_user.values()) == 2 * sum(
        merged.comment_graph.edge_weights.values()
    )


def test_network_scope_fails_closed(tmp_path: Path):
    dataset = _multitopic_dataset(tmp_path)
    with pytest.raises(ValueError):
        ConcurrentMessageExperimentConfig(dataset_dir=dataset, network_scope="platform_all_topics")


def test_replay_does_not_accept_nonexistent_sources(tmp_path: Path):
    with pytest.raises((ValueError, FileNotFoundError)):
        run_ten_topic_replay(
            judgment_source=tmp_path / "missing",
            realized_source=tmp_path / "missing2",
            final_dataset=tmp_path / "missing3",
            output_dir=tmp_path / "result",
        )
    assert not (tmp_path / "result").exists()


def _multitopic_dataset(tmp_path):
    dataset = _dataset(tmp_path)
    path = dataset / "videos.csv"
    with path.open() as h:
        r = csv.DictReader(h)
        fields = r.fieldnames
        rows = list(r)
    # Reclassify the historical video; the holdout stays unchanged.
    for row in rows:
        if row["video_id"] == "history":
            row["source_challenge_name"] = "锦江之星"
    with path.open("w", newline="") as h:
        w = csv.DictWriter(h, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    return dataset


def test_seed_neighbor_supplement_uses_merged_connection_strength(tmp_path: Path):
    dataset = _multitopic_dataset(tmp_path)
    kwargs = dict(
        dataset_dir=dataset,
        sample_size=5,
        random_seed=1,
        model_policy=_TARGET_DELIVERY_RANKING_POLICY,
        holdout_video_ids=("7328592728139353363",),
    )
    merged = _ResearchCohortPreparer(**kwargs).prepare()
    legacy = _ResearchCohortPreparer(**kwargs, network_scope="legacy_target_topic").prepare()
    candidates = merged.sample_audit["neighbor_selection"]["candidates"]
    assert candidates and all(r["seed_edge_weight"] > 0 for r in candidates)
    assert candidates == sorted(candidates, key=lambda r: (-r["seed_edge_weight"], r["user_id"]))
    assert legacy.sample_audit["neighbor_selection"]["candidate_count"] == 0
    for uid in merged.users_by_id:
        for field in ("activity_score", "local_influence_score", "global_influence_score"):
            assert getattr(merged.users_by_id[uid], field) == getattr(legacy.users_by_id[uid], field)
