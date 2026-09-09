"""Cumulative recovery policy, using synthetic inherited origins only."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from llm_abm_sim import concurrent_robustness_v2 as v2
from llm_abm_sim._concurrent_recovery_campaign import CampaignJournal, RecoveryCampaignError, recovery_scope
from llm_abm_sim._concurrent_recovery_progress import CampaignProgress
from llm_abm_sim.decision import EngageDecision
from tests.unit.test_concurrent_recovery_judgment import _attempt


def _proposal() -> dict[str, Any]:
    cells = [
        {"cell_id": f"{p.variant_id}::{m}", "prompt_variant": p.variant_id, "prompt_version": p.prompt_version,
         "prompt_canonical_hash": p.canonical_hash, "requested_model": m, "required_observed_model": v2._V2_REQUIRED_OBSERVED_MODELS[m]}
        for m in v2._V2_MODELS for p in v2.CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.all()
    ]
    return {"logical_judgment_cap": 36000, "maximum_new_physical_attempts": 107996,
            "frozen_context": {"prompt_model_cells": cells, "realization_source_identity": "c" * 64},
            "model_budgets": [{"requested_model": m, "maximum_new_physical_attempts": 21596 if i == 0 else 21600,
                               "remaining_valid_judgments": 7199 if i == 0 else 7200} for i, m in enumerate(v2._V2_MODELS)],
            "inherited_cells": [{"cell_index": 0, "inherited_pairs": [{"pair_schedule_position": 0}]}],
            "failed_pair": {**_pair(), "attempt_evidence": [_attempt(1, outcome="nonretryable_failure", missing=True)]}}


def _pair() -> dict[str, Any]:
    return {"cell_index": 0, "pair_schedule_position": 1, "pair_id": "pair-1", "time_step": 0,
            "message_id": "m0", "user_id": "u1"}


def _epoch(ordinal: int = 1, *, model: str = "deepseek-v4-flash") -> dict[str, Any]:
    return {"ordinal": ordinal, "requested_model": model, "epoch_identity_sha256": "e" * 64,
            "plan_path": "/synthetic-only/plan.json", "plan_sha256": str(ordinal) * 64}


def _journal(tmp_path: Path) -> dict[str, str]:
    return {"campaign_identity_sha256": "a" * 64, "source_anchor_path": str(tmp_path / "anchor.json"),
            "control_root": str(tmp_path / "control")}


def test_cumulative_failed_pair_slots_and_unknown_dispatch_cannot_be_reset(tmp_path: Path) -> None:
    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state = CampaignProgress(_proposal())
        state.append(journal, "epoch_admitted", _epoch())
        state.append(journal, "pair_reserved", _pair())
        with pytest.raises(RecoveryCampaignError):
            state.append(journal, "attempt_intent", {"attempt_number": 1})
        state.append(journal, "attempt_intent", {"attempt_number": 2})
        assert state.physical_attempts == 1
        reopened = CampaignProgress.replay(_proposal(), CampaignJournal.read(identity))
        assert reopened.inflight == ((0, 1), 2)
        for kind, payload in [("attempt_intent", {"attempt_number": 2}), ("epoch_admitted", _epoch(2)),
                              ("epoch_finished", {"status": "paused"})]:
            with pytest.raises(RecoveryCampaignError):
                reopened.append(journal, kind, payload)
        state.append(journal, "attempt_settled", {"attempt": _attempt(2, outcome="retryable_failure", no_response=True), "decision": None})
        state.append(journal, "attempt_intent", {"attempt_number": 3})
        state.append(journal, "attempt_settled", {"attempt": _attempt(3, outcome="nonretryable_failure", missing=True), "decision": None})
        assert state.status == "stopped"
        assert [a.attempt_number for a in state.attempts((0, 1))] == [1, 2, 3]
        assert state.physical_attempts == 2
        with pytest.raises(RecoveryCampaignError):
            state.append(journal, "epoch_admitted", _epoch(2))


def test_persisted_success_is_recoverable_without_redispatch_and_cannot_skip_models(tmp_path: Path) -> None:
    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state = CampaignProgress(_proposal())
        with pytest.raises(RecoveryCampaignError):
            state.append(journal, "epoch_admitted", _epoch(model="gemini-3.1-pro"))
        state.append(journal, "epoch_admitted", _epoch())
        state.append(journal, "pair_reserved", _pair())
        state.append(journal, "attempt_intent", {"attempt_number": 2})
        decision = EngageDecision(engage=True, probability=0.5, action="like", reason="fixture", confidence=0.8,
                                  decision_source="provider_llm")
        state.append(journal, "attempt_settled", {"attempt": _attempt(2), "decision": decision.model_dump(mode="json")})
        reopened = CampaignProgress.replay(_proposal(), CampaignJournal.read(identity))
        assert reopened.success_decisions[(0, 1)] == decision
        with pytest.raises(RecoveryCampaignError):
            reopened.append(journal, "attempt_intent", {"attempt_number": 3})
        with pytest.raises(RecoveryCampaignError):
            reopened.append(journal, "epoch_finished", {"status": "checkpoint"})
