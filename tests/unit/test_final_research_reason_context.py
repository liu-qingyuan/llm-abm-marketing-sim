from __future__ import annotations

import pytest

from llm_abm_sim.final_research_reason_context import build_reason_context_diagnostics
from llm_abm_sim.schemas import PeerContext


def test_reason_context_diagnostics_preserve_exact_reason_and_prompt_ranking_boundaries():
    decision_rows = [
        {"reason": "Same"},
        {"reason": "Same"},
        {"reason": " same"},
        {"reason": "Same "},
        {"reason": "é"},
        {"reason": "e\u0301"},
        {"reason": ""},
    ]
    peer_contexts = [PeerContext() for _ in range(3)]
    candidate_rows = [
        {"selected": "true", "engaged_neighbor_count": 0},
        {"selected": "true", "engaged_neighbor_count": 2},
        {"selected": True, "engaged_neighbor_count": "0"},
        {"selected": "false", "engaged_neighbor_count": 9},
    ]

    diagnostics = build_reason_context_diagnostics(
        decision_rows=decision_rows,
        peer_contexts=peer_contexts,
        candidate_rows=candidate_rows,
    )

    assert diagnostics.exact_reason_facts.model_dump() == {
        "decision_row_count": 7,
        "non_empty_reason_count": 6,
        "empty_reason_count": 1,
        "exact_unique_reason_count": 5,
        "exact_duplicate_row_count": 1,
        "maximum_exact_reason_frequency": 2,
    }
    assert diagnostics.decision_visible_peer_context.model_dump() == {
        "context_count": 3,
        "neutral_context_count": 3,
        "non_neutral_context_count": 0,
        "counter_totals": {
            "engaged_neighbors": 0,
            "exposed_neighbors": 0,
            "influential_engaged_neighbors": 0,
            "visible_likes": 0,
            "visible_comments": 0,
            "visible_shares": 0,
        },
    }
    assert diagnostics.selected_ranking_context.model_dump() == {
        "selected_candidate_count": 3,
        "zero_engaged_neighbor_count": 2,
        "positive_engaged_neighbor_count": 1,
        "engaged_neighbor_count_total": 2,
        "maximum_engaged_neighbor_count": 2,
    }


def test_reason_context_diagnostics_use_zero_maximum_when_all_reasons_are_empty():
    diagnostics = build_reason_context_diagnostics(
        decision_rows=[{"reason": ""}, {"reason": ""}],
        peer_contexts=[PeerContext()],
        candidate_rows=[{"selected": "true", "engaged_neighbor_count": 0}],
    )

    assert diagnostics.exact_reason_facts.non_empty_reason_count == 0
    assert diagnostics.exact_reason_facts.exact_unique_reason_count == 0
    assert diagnostics.exact_reason_facts.exact_duplicate_row_count == 0
    assert diagnostics.exact_reason_facts.maximum_exact_reason_frequency == 0


def test_reason_context_diagnostics_reject_context_denominator_mismatch():
    with pytest.raises(ValueError, match="PeerContext count must equal selected Ranking count"):
        build_reason_context_diagnostics(
            decision_rows=[],
            peer_contexts=[],
            candidate_rows=[{"selected": "true", "engaged_neighbor_count": 0}],
        )
