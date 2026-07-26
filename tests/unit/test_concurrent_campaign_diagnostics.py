from __future__ import annotations

import pytest

from llm_abm_sim.concurrent_campaign_diagnostics import (
    ConcurrentCampaignDiagnostics,
    validate_concurrent_validation_summary,
)


def _full(value: float) -> str:
    return format(value, ".17g")


def _candidate_row(
    *,
    message_id: str = "message_1",
    time_step: int = 0,
    user_id: str,
    ranking_position: int,
    selected: bool,
    base_network_relevance: float,
    campaign_engaged_neighbor_signal: float,
    raw_message_user_fit: float,
    normalized_message_user_fit: float,
) -> dict[str, object]:
    personalized_delivery_score = (
        0.50 * base_network_relevance
        + 0.30 * campaign_engaged_neighbor_signal
        + 0.20 * normalized_message_user_fit
    )
    return {
        "time_step": time_step,
        "message_id": message_id,
        "user_id": user_id,
        "is_seed": "false",
        "selected": "true" if selected else "false",
        "selection_reason": "personalized_top20" if selected else "",
        "ranking_position": ranking_position,
        "base_network_relevance": round(base_network_relevance, 12),
        "base_network_relevance_full_precision": _full(base_network_relevance),
        "campaign_engaged_neighbor_count": 0,
        "campaign_engaged_neighbor_signal": round(campaign_engaged_neighbor_signal, 12),
        "campaign_engaged_neighbor_signal_full_precision": _full(campaign_engaged_neighbor_signal),
        "historical_tag_affinity": 0.0,
        "raw_message_user_fit": round(raw_message_user_fit, 12),
        "raw_message_user_fit_full_precision": _full(raw_message_user_fit),
        "normalized_message_user_fit": round(normalized_message_user_fit, 12),
        "normalized_message_user_fit_full_precision": _full(normalized_message_user_fit),
        "personalized_delivery_score": round(personalized_delivery_score, 12),
        "personalized_delivery_score_full_precision": _full(personalized_delivery_score),
    }


def _pair_row(
    candidate_row: dict[str, object],
    *,
    primary_action: str = "like",
    shadow_action: str = "ignore",
    primary_probability: float = 0.91,
    shadow_probability: float = 0.24,
    primary_reason: str = "primary reason",
    shadow_reason: str = "shadow reason",
) -> dict[str, object]:
    return {
        "pair_id": f"{candidate_row['user_id']}:{candidate_row['message_id']}:{candidate_row['time_step']}",
        "pair_schedule_position": 0,
        "time_step": candidate_row["time_step"],
        "message_id": candidate_row["message_id"],
        "message_title": "Message 1",
        "user_id": candidate_row["user_id"],
        "latent_class": "class_1",
        "shadow_gender": "female",
        "shadow_age": "age_26_35",
        "shadow_education": "bachelor",
        "shadow_monthly_income": "income_8001_15000",
        "is_seed": "false",
        "selection_reason": candidate_row["selection_reason"],
        "ranking_position": candidate_row["ranking_position"],
        "base_network_relevance": candidate_row["base_network_relevance"],
        "base_network_relevance_full_precision": candidate_row["base_network_relevance_full_precision"],
        "campaign_engaged_neighbor_count": candidate_row["campaign_engaged_neighbor_count"],
        "campaign_engaged_neighbor_signal": candidate_row["campaign_engaged_neighbor_signal"],
        "campaign_engaged_neighbor_signal_full_precision": candidate_row[
            "campaign_engaged_neighbor_signal_full_precision"
        ],
        "historical_tag_affinity": 0.0,
        "raw_message_user_fit": candidate_row["raw_message_user_fit"],
        "raw_message_user_fit_full_precision": candidate_row["raw_message_user_fit_full_precision"],
        "normalized_message_user_fit": candidate_row["normalized_message_user_fit"],
        "normalized_message_user_fit_full_precision": candidate_row[
            "normalized_message_user_fit_full_precision"
        ],
        "personalized_delivery_score": candidate_row["personalized_delivery_score"],
        "personalized_delivery_score_full_precision": candidate_row[
            "personalized_delivery_score_full_precision"
        ],
        "primary_status": "succeeded",
        "primary_action": primary_action,
        "primary_probability": primary_probability,
        "primary_confidence": 0.9,
        "primary_reason": primary_reason,
        "primary_decision_source": "fixture",
        "primary_prompt_version": "fixture-primary",
        "primary_provider_metadata": "{}",
        "shadow_status": "succeeded",
        "shadow_action": shadow_action,
        "shadow_probability": shadow_probability,
        "shadow_confidence": 0.88,
        "shadow_reason": shadow_reason,
        "shadow_decision_source": "fixture",
        "shadow_prompt_version": "fixture-shadow",
        "shadow_provider_metadata": "{}",
        "campaign_feedback_committed": "true",
        "pair_terminal_coverage": "true",
        "paired_decision_coverage": "true",
    }


def _basic_diagnostics(shadow_reason: str) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    selected = _candidate_row(
        user_id="u1",
        ranking_position=1,
        selected=True,
        base_network_relevance=0.6,
        campaign_engaged_neighbor_signal=0.2,
        raw_message_user_fit=0.8,
        normalized_message_user_fit=0.9,
    )
    not_selected = _candidate_row(
        user_id="u2",
        ranking_position=2,
        selected=False,
        base_network_relevance=0.2,
        campaign_engaged_neighbor_signal=0.0,
        raw_message_user_fit=0.1,
        normalized_message_user_fit=0.55,
    )
    pair = _pair_row(selected, shadow_reason=shadow_reason)
    return [selected, not_selected], [pair]


def test_demographic_reason_screening_flags_label_value_and_direct_causal_phrases() -> None:
    candidate_rows, pair_rows = _basic_diagnostics("性别标签：女性，因为她是女性，所以更愿意点赞。")

    diagnostics = ConcurrentCampaignDiagnostics(delivery_capacity=1).build(
        candidate_rows=candidate_rows,
        pair_rows=pair_rows,
    )

    screening = diagnostics.payload["demographic_decision_sensitivity"]["reason_screening"]
    assert screening["method_version"] == "shadow-demographic-lexical-screen-v1"
    assert screening["flagged_pair_count"] == 1
    matched_spans = screening["flagged_pairs"][0]["matched_spans"]
    assert any(match["match_type"] == "label_reference" and match["matched_span"] == "性别标签" for match in matched_spans)
    assert any(match["match_type"] == "value_reference" and "女性" in match["matched_span"] for match in matched_spans)
    assert any(match["match_type"] == "direct_causal_phrase" and "因为她是女性" in match["matched_span"] for match in matched_spans)


@pytest.mark.parametrize(
    "shadow_reason",
    [
        "她喜欢女性化的包装设计。",
        "female",
        "这个阶段更适合当前内容。",
    ],
)
def test_demographic_reason_screening_stays_conservative_for_non_matches(shadow_reason: str) -> None:
    candidate_rows, pair_rows = _basic_diagnostics(shadow_reason)

    diagnostics = ConcurrentCampaignDiagnostics(delivery_capacity=1).build(
        candidate_rows=candidate_rows,
        pair_rows=pair_rows,
    )

    screening = diagnostics.payload["demographic_decision_sensitivity"]["reason_screening"]
    assert screening["flagged_pair_count"] == 0


def test_validation_summary_closure_detects_tampered_aggregate_counts() -> None:
    candidate_rows, pair_rows = _basic_diagnostics("shadow reason")
    diagnostics = ConcurrentCampaignDiagnostics(delivery_capacity=1).build(
        candidate_rows=candidate_rows,
        pair_rows=pair_rows,
    )
    funnel = diagnostics.payload["campaign_funnel"]
    sensitivity = diagnostics.payload["demographic_decision_sensitivity"]
    validation_summary = {
        "counts": {
            "sample_users": funnel["sample_users"],
            "eligible_user_message_pairs": funnel["eligible_user_message_pairs"],
            "actual_exposures": funnel["actual_exposures"],
            "distinct_exposed_users": funnel["distinct_exposed_users"],
            "primary_attempted": funnel["primary"]["attempted"],
            "primary_successes": funnel["primary"]["succeeded"],
            "primary_failures": funnel["primary"]["provider_failed"],
            "shadow_attempted": funnel["shadow"]["attempted"],
            "shadow_successes": funnel["shadow"]["succeeded"],
            "shadow_failures": funnel["shadow"]["provider_failed"],
            "pair_terminal_coverage": sensitivity["pair_terminal_coverage"]["value"],
            "paired_decision_coverage": sensitivity["paired_decision_coverage"]["value"],
        },
        "campaign_exposure_coverage": funnel["campaign_exposure_coverage"],
        "per_message": {
            message_id: {
                "exposures": payload["exposures"],
                "primary_successes": payload["primary_successes"],
                "primary_failures": payload["primary_failures"],
                "shadow_successes": payload["shadow_successes"],
                "shadow_failures": payload["shadow_failures"],
                "below_delivery_capacity": payload["below_delivery_capacity"],
            }
            for message_id, payload in funnel["per_message"].items()
        },
    }

    validate_concurrent_validation_summary(validation_summary, diagnostics)

    validation_summary["counts"]["actual_exposures"] = 99
    with pytest.raises(ValueError, match="counts.actual_exposures"):
        validate_concurrent_validation_summary(validation_summary, diagnostics)
