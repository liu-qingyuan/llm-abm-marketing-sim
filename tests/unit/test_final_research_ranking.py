from llm_abm_sim.final_research import PlatformRecommendationModel, RankingCandidate


def test_target_delivery_ranking_uses_full_precision_before_user_id_tiebreak() -> None:
    ranked = PlatformRecommendationModel.rank_candidates(
        [
            RankingCandidate(
                user_id="u-a-lower-score",
                base_network_relevance=0.5000002,
                engaged_neighbor_count=0,
                engaged_neighbor_signal=0.0,
                historical_tag_affinity=0.0,
                recommendation_score=0.2500001,
            ),
            RankingCandidate(
                user_id="u-z-higher-score",
                base_network_relevance=0.5000004,
                engaged_neighbor_count=0,
                engaged_neighbor_signal=0.0,
                historical_tag_affinity=0.0,
                recommendation_score=0.2500002,
            ),
        ]
    )

    assert [candidate.user_id for candidate in ranked] == ["u-z-higher-score", "u-a-lower-score"]
