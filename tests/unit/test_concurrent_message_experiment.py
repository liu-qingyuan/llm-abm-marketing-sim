from __future__ import annotations

import pytest

from llm_abm_sim.concurrent_message_experiment import (
    ExperimentalMessageDefinition,
    _message_user_fit_components,
    _rank_message_candidates,
)
from llm_abm_sim.final_research import ResearchUser
from llm_abm_sim.schemas import ValueDimensions

_LATENT_LABELS = {
    "latent_attribute_spec_id": "fixture-latent-v1",
    "latent_attribute_method": "fixture-exact-quota",
    "latent_attribute_seed": 7,
    "latent_environmental_consciousness_coef": 1.0,
    "latent_hotel_class": "midscale",
    "latent_travel_purpose": "leisure",
    "latent_gender": "female",
    "latent_age": "age_26_35",
    "latent_education": "bachelor",
    "latent_monthly_income": "income_8001_15000",
}


def _research_user(user_id: str, *, latent_class: str = "class_1", **weights: float) -> ResearchUser:
    latent = dict(_LATENT_LABELS)
    latent["latent_class"] = latent_class
    for dimension in ("epistemic", "environmental", "functional", "health", "emotional", "social"):
        latent[f"latent_{dimension}_value_weight"] = weights.get(dimension, 0.0)
    return ResearchUser(user_id=user_id, latent_attributes=latent)


def _message(message_id: str, **value_dimensions: float) -> ExperimentalMessageDefinition:
    return ExperimentalMessageDefinition(
        message_id=message_id,
        title=message_id,
        intended_audience_segment="class_1",
        body=f"body for {message_id}",
        value_dimensions=ValueDimensions(**value_dimensions),
    )


def test_message_user_fit_maps_negative_and_positive_cosine_into_unit_interval() -> None:
    message = _message("message-1", environmental=1.0, health=1.0, social=1.0)

    aligned_raw, aligned_normalized = _message_user_fit_components(
        message,
        _research_user("u-aligned", environmental=1.0, health=1.0, social=1.0),
    )
    opposed_raw, opposed_normalized = _message_user_fit_components(
        message,
        _research_user("u-opposed", environmental=-1.0, health=-1.0, social=-1.0),
    )

    assert aligned_raw == pytest.approx(1.0)
    assert aligned_normalized == pytest.approx(1.0)
    assert opposed_raw == pytest.approx(-1.0)
    assert opposed_normalized == pytest.approx(0.0)


@pytest.mark.parametrize(
    ("message", "user", "expected"),
    [
        (_message("zero-message"), _research_user("u1", environmental=1.0), "zero-message/u1"),
        (
            _message("nonzero-message", environmental=1.0),
            _research_user("u2"),
            "nonzero-message/u2",
        ),
    ],
)
def test_message_user_fit_rejects_zero_norm_inputs(
    message: ExperimentalMessageDefinition,
    user: ResearchUser,
    expected: str,
) -> None:
    with pytest.raises(ValueError, match=expected):
        _message_user_fit_components(message, user)


def test_rank_message_candidates_uses_score_before_user_id_tiebreak() -> None:
    message = _message("precision-message", environmental=1.0, health=1.0, social=1.0)
    users_by_id = {
        "u-a-lower-score": _research_user(
            "u-a-lower-score",
            environmental=1.0,
            health=1.0,
            social=0.999,
        ),
        "u-z-higher-score": _research_user(
            "u-z-higher-score",
            environmental=1.0,
            health=1.0,
            social=1.0,
        ),
    }

    ranked = _rank_message_candidates(
        message=message,
        users_by_id=users_by_id,
        eligible_user_ids=["u-a-lower-score", "u-z-higher-score"],
        base_network_by_user={"u-a-lower-score": 0.5, "u-z-higher-score": 0.5},
        neighbors_by_user={},
        campaign_engaged_user_ids=set(),
    )

    assert [candidate.user_id for candidate in ranked] == ["u-z-higher-score", "u-a-lower-score"]
