from __future__ import annotations

import json
from dataclasses import fields

import pytest
from pydantic import ValidationError

from llm_abm_sim.decision import EngageDecision
from llm_abm_sim.engagement_realization import (
    FULL_POOL_REALIZED_TERMINAL_SCHEMA,
    REALIZATION_RULE_VERSION,
    REALIZATION_SEED,
    REALIZED_TERMINAL_FIELDS,
    EngagementRealization,
    EngagementRealizationPolicy,
    FullPoolRealizedTerminal,
)


def test_provider_ignore_never_draws_or_invents_an_action() -> None:
    policy = EngagementRealizationPolicy(
        source_identity="fixture-source-v4",
        realization_seed=REALIZATION_SEED,
        realization_rule_version=REALIZATION_RULE_VERSION,
    )

    result = policy.realize(
        EngageDecision(
            engage=False,
            probability=0.91,
            action="ignore",
            reason="Provider judgment reason",
            confidence=0.73,
            decision_source="fixture-provider",
        ),
        user_id="u1",
        message_id="message_1",
    )

    assert result == EngagementRealization(
        realization_key="f752308a814de0f1a02272953fff231fa9a3570032b098f86350193de8dc0bbb",
        realization_status="provider_ignore",
        uniform_draw=None,
        realized_engage=False,
        realized_action="ignore",
    )
    assert [field.name for field in fields(result)] == [
        "realization_key",
        "realization_status",
        "uniform_draw",
        "realized_engage",
        "realized_action",
    ]


def test_positive_judgments_use_fixed_vectors_and_preserve_only_passed_actions() -> None:
    policy = EngagementRealizationPolicy(source_identity="fixture-source-v4")

    passed = policy.realize(
        EngageDecision(engage=True, probability=0.9, action="comment", reason="intent", confidence=0.8),
        user_id="u1",
        message_id="message_1",
    )
    failed = policy.realize(
        EngageDecision(engage=True, probability=0.6, action="share", reason="intent", confidence=0.8),
        user_id="u1",
        message_id="message_2",
    )
    zero = policy.realize(
        EngageDecision(engage=True, probability=0.0, action="like", reason="intent", confidence=0.8),
        user_id="u2",
        message_id="message_1",
    )
    one = policy.realize(
        EngageDecision(engage=True, probability=1.0, action="share", reason="intent", confidence=0.8),
        user_id="u2",
        message_id="message_2",
    )
    like_pass = policy.realize(
        EngageDecision(engage=True, probability=1.0, action="like", reason="intent", confidence=0.8),
        user_id="u3",
        message_id="message_3",
    )

    assert passed == EngagementRealization(
        realization_key="f752308a814de0f1a02272953fff231fa9a3570032b098f86350193de8dc0bbb",
        realization_status="draw_pass",
        uniform_draw=0.8652130761947683,
        realized_engage=True,
        realized_action="comment",
    )
    assert failed == EngagementRealization(
        realization_key="1e8178faf04a810008bc2a7d4315183a9b28dc59802131117accf4a30b73e914",
        realization_status="draw_fail",
        uniform_draw=0.6099436202383672,
        realized_engage=False,
        realized_action="ignore",
    )
    assert zero.realization_status == "draw_fail"
    assert zero.realized_action == "ignore"
    assert one.realization_status == "draw_pass"
    assert one.realized_action == "share"
    assert like_pass.realization_status == "draw_pass"
    assert like_pass.realized_action == "like"


def test_realization_is_independent_of_schedule_and_completion_order() -> None:
    policy = EngagementRealizationPolicy(source_identity="fixture-source-v4")
    judgment = EngageDecision(
        engage=True,
        probability=0.7,
        action="like",
        reason="Provider provenance only",
        confidence=0.6,
    )
    pairs = [("u1", "message_1"), ("u2", "message_3"), ("u1", "message_2")]

    forward = {
        pair: policy.realize(judgment, user_id=pair[0], message_id=pair[1])
        for pair in pairs
    }
    reverse = {
        pair: policy.realize(judgment, user_id=pair[0], message_id=pair[1])
        for pair in reversed(pairs)
    }

    assert forward == reverse


def _terminal_payload(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "realized_terminal_id": "realized-terminal-1",
        "upstream_source_identity": "fixture-source-v4",
        "upstream_terminal_row_id": "u1:message_1:0:primary",
        "upstream_pair_id": "u1:message_1:0",
        "realization_key": "f752308a814de0f1a02272953fff231fa9a3570032b098f86350193de8dc0bbb",
        "replay_pair_id": "u1:message_1:7",
        "replay_pair_schedule_position": 21,
        "replay_time_step": 7,
        "message_id": "message_1",
        "user_id": "u1",
        "provider_engage": True,
        "provider_probability": 0.9,
        "provider_action": "comment",
        "provider_reason": "Provider intent provenance",
        "provider_confidence": 0.73,
        "provider_decision_source": "fixture-provider",
        "prompt_version": "jinjiang-concurrent-message-primary-prompt-v1",
        "environmental_consciousness_prompt_inclusion": "included",
        "realization_rule_version": REALIZATION_RULE_VERSION,
        "realization_seed": REALIZATION_SEED,
        "realization_status": "draw_pass",
        "uniform_draw": 0.8652130761947683,
        "realized_engage": True,
        "realized_action": "comment",
    }
    payload.update(updates)
    return payload


def test_realized_terminal_has_exact_24_fields_and_canonical_jsonl() -> None:
    terminal = FullPoolRealizedTerminal.model_validate(_terminal_payload())

    assert FULL_POOL_REALIZED_TERMINAL_SCHEMA == "full-pool-realized-terminal-v1"
    assert tuple(terminal.model_dump(mode="json")) == REALIZED_TERMINAL_FIELDS
    assert len(REALIZED_TERMINAL_FIELDS) == 24
    assert terminal.provider_reason == "Provider intent provenance"
    assert terminal.provider_confidence == 0.73
    assert "realized_reason" not in terminal.model_dump(mode="json")
    assert terminal.canonical_json_line() == json.dumps(
        terminal.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ) + "\n"


@pytest.mark.parametrize(
    "updates",
    [
        {"realized_reason": "invented"},
        {"realization_status": "draw_fail", "realized_engage": True},
        {"uniform_draw": None},
        {"uniform_draw": 0.1},
        {"provider_action": "ignore"},
        {"realization_key": "0" * 64},
        {"provider_probability": float("nan")},
    ],
)
def test_realized_terminal_rejects_extra_or_crossed_facts(updates: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        FullPoolRealizedTerminal.model_validate(_terminal_payload(**updates))


def test_provider_ignore_terminal_requires_no_draw_and_cannot_become_positive() -> None:
    terminal = FullPoolRealizedTerminal.model_validate(
        _terminal_payload(
            provider_engage=False,
            provider_action="ignore",
            provider_probability=0.99,
            realization_status="provider_ignore",
            uniform_draw=None,
            realized_engage=False,
            realized_action="ignore",
        )
    )
    assert terminal.uniform_draw is None

    with pytest.raises(ValidationError):
        FullPoolRealizedTerminal.model_validate(
            _terminal_payload(
                provider_engage=False,
                provider_action="ignore",
                realization_status="provider_ignore",
                uniform_draw=0.2,
                realized_engage=True,
                realized_action="like",
            )
        )
