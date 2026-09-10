"""Offline, immutable-journal checks for the explicitly approved parallel lane."""

from copy import deepcopy

import pytest

from llm_abm_sim._concurrent_recovery_campaign import CampaignJournal, RecoveryCampaignError, recovery_scope
from llm_abm_sim._concurrent_recovery_progress import CampaignProgress
from llm_abm_sim.decision import EngageDecision
from tests.unit.test_concurrent_recovery_judgment import _attempt
from tests.unit.test_concurrent_recovery_progress import _epoch, _journal, _proposal

MODEL = "gemini-3.1-pro"


def proposal():
    value = deepcopy(_proposal())
    value["model_budgets"][0]["remaining_valid_judgments"] = 0
    value["inherited_cells"] = [
        {"cell_index": i, "inherited_pairs": [{"pair_schedule_position": j} for j in range(1800)]} for i in range(4)
    ]
    value["failed_pair"].update(cell_index=4, pair_schedule_position=0, pair_id="pair-0", user_id="u0")
    return value


def attempt(number=1, **kwargs):
    row = _attempt(number, **kwargs)
    if row["observed_model_counts"]:
        row["observed_model_counts"] = {"gemini-pro-agent": row["provider_response_count"]}
    return row


def approval():
    return {
        "approval": {"path": "/fixture/parallel-approval.json", "sha256": "f" * 64},
        "requested_model": MODEL,
        "maximum_inflight": 4,
        "stop_after_model": True,
    }


def batch():
    return {
        "cell_index": 4,
        "time_step": 0,
        "pairs": [
            {
                "coordinates": {
                    "cell_index": 4,
                    "pair_schedule_position": i,
                    "pair_id": f"pair-{i}",
                    "time_step": 0,
                    "message_id": "m0",
                    "user_id": f"u{i}",
                },
                "context_sha256": "b" * 64,
            }
            for i in range(60)
        ],
    }


def start(journal, reserve=True):
    state = CampaignProgress(proposal())
    state.append(journal, "task_admitted", {"task_plan": {"path": "/fixture/task.json", "sha256": "a" * 64}})
    state.append(journal, "self_check_intent", {"requested_model": MODEL, "contract_sha256": "b" * 64})
    decision = EngageDecision(engage=True, probability=0.5, action="like", reason="offline", confidence=0.8).model_dump(
        mode="json"
    )
    state.append(journal, "self_check_settled", {"requested_model": MODEL, "attempt": attempt(), "decision": decision})
    state.append(journal, "epoch_admitted", _epoch(model=MODEL))
    state.append(journal, "epoch_finished", {"status": "paused"})
    state.append(journal, "parallel_execution_accepted", approval())
    state.append(journal, "invocation_started", {"epoch_identity_sha256": "e" * 64, "ordinal": 1})
    if reserve:
        state.append(journal, "parallel_batch_reserved", batch())
    return state, decision


def test_four_out_of_order_intents_survive_durable_reread_without_budget_reset(tmp_path):
    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state, decision = start(journal)
        for position in range(4):
            state.append(
                journal,
                "parallel_attempt_intent",
                {"cell_index": 4, "pair_schedule_position": position, "attempt_number": 2 if position == 0 else 1},
            )
        assert state.has_inflight and state.physical_attempts == 4
        for position in reversed(range(4)):
            state.append(
                journal,
                "parallel_attempt_settled",
                {
                    "cell_index": 4,
                    "pair_schedule_position": position,
                    "attempt": attempt(2 if position == 0 else 1),
                    "decision": decision,
                },
            )
        reread = CampaignProgress.replay(proposal(), CampaignJournal.read(identity))
        assert reread.physical_attempts == 4 and not reread.has_inflight
        assert set(reread.success_decisions) == {(4, i) for i in range(4)}
        assert len(reread.attempts((4, 0))) == 2
        assert reread.prefix == [1800] * 4 + [0] * 16
        assert reread.parallel_approval == approval()


def intent(position, number=None):
    return {
        "cell_index": 4,
        "pair_schedule_position": position,
        "attempt_number": (2 if position == 0 else 1) if number is None else number,
    }


def settlement(position, decision, row=None):
    return {
        "cell_index": 4,
        "pair_schedule_position": position,
        "attempt": attempt(2 if position == 0 else 1) if row is None else row,
        "decision": decision,
    }


def test_fifth_intent_duplicate_success_and_other_model_are_rejected(tmp_path):
    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state, decision = start(journal)
        for p in range(4):
            state.append(journal, "parallel_attempt_intent", intent(p))
        head = journal.head
        for row in [intent(4), intent(1), {"cell_index": 8, "pair_schedule_position": 0, "attempt_number": 1}]:
            with pytest.raises(RecoveryCampaignError):
                state.append(journal, "parallel_attempt_intent", row)
        assert journal.head == head and state.physical_attempts == 4
        state.append(journal, "parallel_attempt_settled", settlement(2, decision))
        with pytest.raises(RecoveryCampaignError):
            state.append(journal, "parallel_attempt_intent", intent(2, 2))
        with pytest.raises(RecoveryCampaignError):
            state.append(journal, "parallel_attempt_settled", settlement(2, decision))
        state.append(journal, "parallel_attempt_intent", intent(4))
        assert state.physical_attempts == 5 and len(state.parallel_inflight) == 4


@pytest.mark.parametrize("unknown", [False, True])
def test_hard_stop_drains_prior_responses_but_never_admits_another_call(tmp_path, unknown):
    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state, decision = start(journal)
        for p in range(4):
            state.append(journal, "parallel_attempt_intent", intent(p))
        if unknown:
            state.append(journal, "parallel_dispatch_unknown", intent(1))
        else:
            row = attempt(1, outcome="nonretryable_failure", no_response=True)
            row["failure_category"] = "quota_exhausted"
            state.append(journal, "parallel_attempt_settled", settlement(1, None, row))
        for p in [3, 2, 0]:
            state.append(journal, "parallel_attempt_settled", settlement(p, decision))
        state = CampaignProgress.replay(proposal(), CampaignJournal.read(identity))
        assert state.status == ("reconciliation_required" if unknown else "stopped")
        assert state.has_inflight == unknown
        assert state.physical_attempts == 4 and len(state.success_decisions) == 3
        for kind, row in [
            ("parallel_attempt_intent", intent(4)),
            ("parallel_execution_accepted", approval()),
            ("invocation_started", {"epoch_identity_sha256": "e" * 64, "ordinal": 2}),
        ]:
            with pytest.raises(RecoveryCampaignError):
                state.append(journal, kind, row)


def test_unknown_ordinal_rejects_boolean_without_changing_head(tmp_path):
    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state, _ = start(journal)
        state.append(journal, "parallel_attempt_intent", intent(1))
        with pytest.raises(RecoveryCampaignError):
            state.append(journal, "parallel_dispatch_unknown", intent(1, True))


def test_historical_failed_pair_keeps_two_slots_and_third_success_can_project(tmp_path):
    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state, decision = start(journal)
        state.append(journal, "parallel_attempt_intent", intent(0, 2))
        state.append(
            journal,
            "parallel_attempt_settled",
            settlement(0, None, attempt(2, outcome="retryable_failure", no_response=True)),
        )
        state.append(journal, "parallel_attempt_intent", intent(0, 3))
        state.append(journal, "parallel_attempt_settled", settlement(0, decision, attempt(3)))
        with pytest.raises(RecoveryCampaignError):
            state.append(journal, "parallel_attempt_intent", intent(0, 4))
        state.append(journal, "pair_reserved", batch()["pairs"][0]["coordinates"])
        reopened = CampaignProgress.replay(proposal(), CampaignJournal.read(identity))
        assert len(reopened.attempts((4, 0))) == 3 and reopened.physical_attempts == 2
        assert reopened.attempts((4, 0))[0].usage_missing_response_count == 1
        assert reopened.reservation == batch()["pairs"][0]["coordinates"]


@pytest.mark.parametrize("scope", ["model", "campaign"])
def test_parallel_attempt_budget_exhaustion_does_not_write_intent(tmp_path, scope):
    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state, _ = start(journal)
        # The inherited Origin verifier owns cap values; exercise both independent ceilings.
        if scope == "model":
            state.physical_by_model[MODEL] = 21600
        else:
            state.physical_attempts = state.proposal["maximum_new_physical_attempts"]
        head = journal.head
        with pytest.raises(RecoveryCampaignError):
            state.append(journal, "parallel_attempt_intent", intent(0))
        assert journal.head == head and not state.has_inflight


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "stopped"),
        ("status", "reconciliation_required"),
        ("task_revoked", True),
        ("inflight", ((4, 0), 2)),
        ("reservation", {}),
        ("pending_judgment", {}),
        ("pending_realized", {}),
        ("self_check_inflight", MODEL),
    ],
)
def test_parallel_receipt_never_releases_a_hard_stop_or_unsettled_work(tmp_path, field, value):
    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state, _ = start(journal)
        state.parallel_approval = None
        state.status = "paused"
        setattr(state, field, value)
        with pytest.raises(RecoveryCampaignError):
            state.transition("parallel_execution_accepted", approval())


@pytest.mark.parametrize("bad", ["identity", "usage", "decision", "ordinal", "count"])
def test_crossed_response_never_consumes_the_matching_intent(tmp_path, bad):
    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state, decision = start(journal)
        state.append(journal, "parallel_attempt_intent", intent(1))
        row = settlement(1, decision)
        if bad == "identity":
            row["attempt"]["observed_model_counts"] = {"wrong": 1}
        elif bad == "usage":
            row["attempt"]["usage_complete_response_count"] = 0
            row["attempt"]["usage_missing_response_count"] = 1
        elif bad == "decision":
            row["decision"] = {**decision, "probability": 2}
        elif bad == "ordinal":
            row["attempt"]["attempt_number"] = 2
        else:
            row["attempt"]["request_invocations"] = 2
        head = journal.head
        with pytest.raises((RecoveryCampaignError, ValueError)):
            state.append(journal, "parallel_attempt_settled", row)
        assert journal.head == head and state.parallel_inflight == {(4, 1): 1}


def test_unknown_after_hard_failure_is_recorded_once_and_is_not_settled_implicitly(tmp_path):
    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state, decision = start(journal)
        state.append(journal, "parallel_attempt_intent", intent(1))
        state.append(journal, "parallel_attempt_intent", intent(2))
        state.append(
            journal,
            "parallel_attempt_settled",
            settlement(1, None, attempt(1, outcome="nonretryable_failure", no_response=True)),
        )
        state.append(journal, "parallel_dispatch_unknown", intent(2))
        assert state.status == "reconciliation_required" and state.has_inflight
        with pytest.raises(RecoveryCampaignError):
            state.append(journal, "parallel_dispatch_unknown", intent(2))
        with pytest.raises(RecoveryCampaignError):
            state.append(journal, "parallel_attempt_settled", settlement(2, decision))


def test_existing_execution_action_and_progress_never_hide_keyed_inflight(tmp_path):
    from types import SimpleNamespace
    from llm_abm_sim import concurrent_robustness_recovery_execution as execution
    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state, _ = start(journal)
        for position in range(4):
            state.append(journal, 'parallel_attempt_intent', intent(position))
        origins = SimpleNamespace(proposal={'progress':{
            'successful_judgments':7200,'attempted_logical_judgments':7201,'physical_attempts':7201}})
        context = SimpleNamespace(plan={'plan_identity_sha256':'e'*64},state=state,journal=journal)
        assert execution._action(context) == 'return'
        progress = execution._progress(origins,state)
        assert progress['status'] == 'reconciliation_required'
        assert progress['attempted_logical_judgments'] == 7204
        assert progress['physical_attempts'] == 7205
