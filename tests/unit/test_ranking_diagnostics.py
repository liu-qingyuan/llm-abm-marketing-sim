from llm_abm_sim.ranking_diagnostics import RankingDiagnostics


def _holdout_diagnostic(**overrides: object) -> dict[str, object]:
    diagnostic: dict[str, object] = {
        "target_aggregate_engagement_reference": {
            "source_artifact": "videos.csv",
            "record_key": {"video_id": "target-video"},
            "like_count": 11,
            "comment_count": 12,
            "share_count": 13,
            "collect_count": 14,
            "real_exposure_denominator_available": False,
            "user_level_attribution_available": False,
            "action_mutual_exclusivity_known": False,
            "diagnostic_only": True,
        }
    }
    diagnostic.update(overrides)
    return diagnostic


def test_paired_ablation_compares_full_and_no_network_on_frozen_candidates() -> None:
    diagnostics = RankingDiagnostics(delivery_capacity=2).build(
        candidate_rows=[
            {
                "time_step": 1,
                "ranking_position": 1,
                "user_id": "u-network",
                "selected": "true",
                "base_network_relevance": 1.0,
                "engaged_neighbor_signal": 0.0,
                "historical_tag_affinity": 0.0,
            },
            {
                "time_step": 1,
                "ranking_position": 2,
                "user_id": "u-tag-a",
                "selected": "true",
                "base_network_relevance": 0.0,
                "engaged_neighbor_signal": 0.0,
                "historical_tag_affinity": 0.4,
            },
            {
                "time_step": 1,
                "ranking_position": 3,
                "user_id": "u-tag-b",
                "selected": "false",
                "base_network_relevance": 0.0,
                "engaged_neighbor_signal": 0.0,
                "historical_tag_affinity": 0.3,
            },
        ],
        holdout_diagnostic=_holdout_diagnostic(),
    )

    batch = diagnostics.payload["paired_ablation"]["batches"][0]
    assert batch["candidate_user_ids"] == ["u-network", "u-tag-a", "u-tag-b"]
    assert batch["full_top_user_ids"] == ["u-network", "u-tag-a"]
    assert batch["no_network_top_user_ids"] == ["u-tag-a", "u-tag-b"]
    assert batch["top_overlap_user_ids"] == ["u-tag-a"]
    assert batch["network_added_user_ids"] == ["u-network"]
    assert batch["network_removed_user_ids"] == ["u-tag-b"]
    assert batch["rank_deltas"] == [
        {"user_id": "u-network", "full_rank": 1, "no_network_rank": 3, "network_rank_delta": 2},
        {"user_id": "u-tag-a", "full_rank": 2, "no_network_rank": 1, "network_rank_delta": -1},
        {"user_id": "u-tag-b", "full_rank": 3, "no_network_rank": 2, "network_rank_delta": -1},
    ]


def test_sensitivity_uses_only_predeclared_weights_and_reports_research_limits() -> None:
    diagnostics = RankingDiagnostics(delivery_capacity=2).build(
        candidate_rows=[
            {
                "time_step": 1,
                "ranking_position": 1,
                "user_id": "u-network",
                "selected": True,
                "base_network_relevance": 1.0,
                "engaged_neighbor_signal": 0.0,
                "historical_tag_affinity": 0.0,
            },
            {
                "time_step": 1,
                "ranking_position": 2,
                "user_id": "u-tag-a",
                "selected": True,
                "base_network_relevance": 0.0,
                "engaged_neighbor_signal": 0.0,
                "historical_tag_affinity": 0.4,
            },
            {
                "time_step": 1,
                "ranking_position": 3,
                "user_id": "u-tag-b",
                "selected": False,
                "base_network_relevance": 0.0,
                "engaged_neighbor_signal": 0.0,
                "historical_tag_affinity": 0.3,
            },
        ],
        holdout_diagnostic=_holdout_diagnostic(
            observed_holdout_participant_count=2,
            observed_holdout_participant_ids=["u-network", "u-tag-b"],
            model_recommended_user_count=2,
            model_recommended_user_ids=["u-network", "u-tag-a"],
            intersection_count=1,
            intersection_user_ids=["u-network"],
            observed_participant_signal_coverage={
                "with_non_target_history": 2,
                "with_network_connection": 1,
                "with_historical_tag_affinity": 1,
                "rows": [],
            },
        ),
    )

    sensitivity = diagnostics.payload["weight_sensitivity"]
    assert [(variant["variant_id"], variant["weights"]) for variant in sensitivity["variants"]] == [
        ("main_50_30_20", {"base_network": 0.5, "engaged_neighbor": 0.3, "tag_affinity": 0.2}),
        ("weaker_network_40_20_40", {"base_network": 0.4, "engaged_neighbor": 0.2, "tag_affinity": 0.4}),
        ("no_network_0_0_100", {"base_network": 0.0, "engaged_neighbor": 0.0, "tag_affinity": 1.0}),
    ]
    assert [variant["batches"][0]["top_user_ids"] for variant in sensitivity["variants"]] == [
        ["u-network", "u-tag-a"],
        ["u-network", "u-tag-a"],
        ["u-tag-a", "u-tag-b"],
    ]
    assert sensitivity["parameter_search_performed"] is False
    assert diagnostics.summary["diagnostic_decision_adapter_calls"] == 0
    assert diagnostics.summary["recommendation_signal_inclusion"]["network_signals_in_formula"] is True
    assert diagnostics.summary["observed_recommendation_signal_effect"]["top_selection_changed"] is True

    historical = diagnostics.payload["historical_top20_diagnostic"]
    assert historical["intersection_count"] == 1
    assert historical["intersection_user_ids"] == ["u-network"]
    assert historical["observed_participant_signal_coverage"]["with_network_connection"] == 1
    assert historical["positive_sample_sparsity_limit"] is True
    assert historical["real_exposure_denominator_available"] is False
    assert historical["production_accuracy_claim"] is False
    assert "recall" not in str(historical).lower()


def test_signal_inclusion_reports_zero_observed_effect_when_top_selection_is_unchanged() -> None:
    diagnostics = RankingDiagnostics(delivery_capacity=2).build(
        candidate_rows=[
            {
                "time_step": 1,
                "ranking_position": 1,
                "user_id": "u-network",
                "selected": True,
                "base_network_relevance": 1.0,
                "engaged_neighbor_signal": 0.0,
                "historical_tag_affinity": 0.0,
            },
            {
                "time_step": 1,
                "ranking_position": 2,
                "user_id": "u-tag",
                "selected": True,
                "base_network_relevance": 0.0,
                "engaged_neighbor_signal": 0.0,
                "historical_tag_affinity": 1.0,
            },
        ],
        holdout_diagnostic=_holdout_diagnostic(),
    )

    assert diagnostics.summary["recommendation_signal_inclusion"]["network_signals_in_formula"] is True
    effect = diagnostics.summary["observed_recommendation_signal_effect"]
    assert effect["top_selection_changed"] is False
    assert effect["batches_with_top_selection_change"] == 0
    assert "changed no" in effect["meaning"]


def test_full_diagnostic_preserves_persisted_main_ranking_when_components_tie() -> None:
    diagnostics = RankingDiagnostics(delivery_capacity=1).build(
        candidate_rows=[
            {
                "time_step": 1,
                "ranking_position": 1,
                "user_id": "u-z-higher",
                "selected": True,
                "base_network_relevance": 0.5,
                "engaged_neighbor_signal": 0.0,
                "historical_tag_affinity": 0.0,
                "recommendation_score": 0.250000000002,
            },
            {
                "time_step": 1,
                "ranking_position": 2,
                "user_id": "u-a-lower",
                "selected": False,
                "base_network_relevance": 0.5,
                "engaged_neighbor_signal": 0.0,
                "historical_tag_affinity": 0.0,
                "recommendation_score": 0.250000000001,
            },
        ],
        holdout_diagnostic=_holdout_diagnostic(),
    )

    assert diagnostics.payload["paired_ablation"]["batches"][0]["full_top_user_ids"] == ["u-z-higher"]
