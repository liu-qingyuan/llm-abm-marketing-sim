"""Kimi-only admission preserves the stopped model and common durable ledger."""

from copy import deepcopy

import pytest

from llm_abm_sim import concurrent_robustness_v2 as v2
from llm_abm_sim._concurrent_recovery_campaign import CampaignJournal, RecoveryCampaignError, recovery_scope
from llm_abm_sim._concurrent_recovery_progress import CampaignProgress
from tests.unit.test_concurrent_recovery_parallel_progress import attempt, intent, proposal, settlement, start
from tests.unit.test_concurrent_recovery_progress import _journal


def admission():
    return {
        "approval": {"path": "/fixture/kimi-lane.json", "sha256": "c" * 64},
        "requested_model": "kimi-coding/k3-256k",
        "maximum_inflight": 10,
        "global_maximum_inflight": 10,
        "stop_after_model": True,
    }


def stopped(journal):
    state, _ = start(journal)
    state.append(journal, "parallel_attempt_intent", intent(0))
    row = attempt(2, outcome="nonretryable_failure", no_response=True)
    row["failure_category"] = "quota_exhausted"
    state.append(journal, "parallel_attempt_settled", settlement(0, None, row))
    return state


def test_model_lane_admission_preserves_stopped_gemini_and_cumulative_budget(tmp_path):
    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state = stopped(journal)
        prior = deepcopy(state.parallel_approval)
        prefixes = list(state.prefix)
        state.append(journal, "model_lane_accepted", admission())
        reread = CampaignProgress.replay(proposal(), CampaignJournal.read(identity))
        assert reread.current_model == "kimi-coding/k3-256k"
        assert reread.current_key == (12, 0)
        assert reread.status == "ready"
        assert reread.physical_attempts == 1 and reread.prefix == prefixes
        assert reread.parallel_approval == prior
        assert reread.suspended_models["gemini-3.1-pro"]["status"] == "stopped"
        assert reread.suspended_models["gemini-3.1-pro"]["parallel_active_batch"] == (4, 0)
        assert reread.attempts((4, 0))[-1].failure_category == "quota_exhausted"
        assert reread.effective_parallel_approval["maximum_inflight"] == 10


@pytest.mark.parametrize(
    "fault",
    ["unknown", "inflight", "revoked", "identity", "selfcheck", "budget", "foreign_model", "capacity", "duplicate"],
)
def test_model_lane_rejects_other_hard_stops_or_changed_grant_without_append(tmp_path, fault):
    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state = stopped(journal)
        payload = admission()
        if fault == "unknown":
            state.parallel_unknown.add((4, 5))
        if fault == "inflight":
            state.parallel_inflight[4, 5] = 1
        if fault == "revoked":
            state.task_revoked = True
        if fault == "identity":
            state.new_attempts[4, 0][-1] = state.new_attempts[4, 0][-1].model_copy(
                update={"failure_category": "model_identity"}
            )
        if fault == "selfcheck":
            state.self_check_intents["kimi-coding/k3-256k"] = {}
        if fault == "budget":
            state.physical_attempts = state.proposal["maximum_new_physical_attempts"]
        if fault == "foreign_model":
            payload["requested_model"] = "gemini-3.8-flash-high"
        if fault == "capacity":
            payload["maximum_inflight"] = 11
        if fault == "duplicate":
            state.append(journal, "model_lane_accepted", payload)
        head = journal.head
        with pytest.raises(RecoveryCampaignError):
            state.append(journal, "model_lane_accepted", payload)
        assert journal.head == head


def running_kimi(journal):
    from tests.unit.test_concurrent_recovery_progress import _epoch

    state = stopped(journal)
    state.append(journal, "model_lane_accepted", admission())
    state.append(journal, "self_check_intent", {"requested_model": "kimi-coding/k3-256k", "contract_sha256": "d" * 64})
    row = kimi_attempt()
    decision = {"engage": True, "probability": 0.8, "confidence": 0.9, "action": "like", "reason": "offline"}
    state.append(
        journal, "self_check_settled", {"requested_model": "kimi-coding/k3-256k", "attempt": row, "decision": decision}
    )
    epoch = _epoch(model="kimi-coding/k3-256k")
    epoch.update(ordinal=2, epoch_identity_sha256="d" * 64, plan_sha256="d" * 64)
    state.append(journal, "epoch_admitted", epoch)
    state.append(journal, "invocation_started", {"epoch_identity_sha256": "d" * 64, "ordinal": 2})
    return state, decision


def kimi_attempt():
    row = attempt()
    row.update(
        observed_model_counts={"k3-256k": 1},
        provider_route="pi_kimi_oauth_subscription",
        billing_semantics="subscription_quota_with_nominal_usd_reference",
        billing_currency=None,
    )
    return row


@pytest.mark.parametrize("failure", [None, "quota", "unknown"])
def test_kimi_ten_worker_dispatch_drain_and_duplicate_zero_calls(tmp_path, monkeypatch, failure):
    import threading
    import time

    from llm_abm_sim import _concurrent_recovery_parallel_runtime as runtime
    from llm_abm_sim import concurrent_robustness_operator as operator
    from llm_abm_sim.concurrent_message_experiment import _VariantDecisionContext
    from llm_abm_sim.decision import ProviderResponseProvenanceUnknown
    from llm_abm_sim.providers.robustness import ProviderAttemptFailure
    from tests.unit.test_concurrent_robustness_operator import _Transport
    from tests.unit.test_robustness_provider_adapters import _context

    lock = threading.Lock()
    barrier = threading.Barrier(10)
    calls = peak = active = 0

    class Transport(_Transport):
        def create_response(self, *args, **kwargs):
            nonlocal calls, peak, active
            with lock:
                calls += 1
                number = calls
                active += 1
                peak = max(peak, active)
            try:
                if number <= 10:
                    barrier.wait(timeout=5)
                if failure and number == 1:
                    if failure == "quota":
                        raise ProviderAttemptFailure(category="quota_exhausted", retryable=False)
                    raise ProviderResponseProvenanceUnknown("offline unknown")
                time.sleep(0.03)
                return super().create_response(*args, **kwargs)
            finally:
                with lock:
                    active -= 1

    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state, _ = running_kimi(journal)
        clients = [Transport("kimi", {}) for _ in range(10)]
        pool = runtime.ParallelAdapterPool(tuple(operator._adapter_for_cell(state.cells[12], c) for c in clients))
        data = _context()
        context = _VariantDecisionContext(
            decision_variant="primary",
            prompt_token=state.cells[12].prompt_version,
            **{k: data[k] for k in ("post", "profile", "peer_context", "platform_context")},
        )
        work = tuple(
            runtime.FrozenWork(
                {
                    "cell_index": 12,
                    "pair_schedule_position": i,
                    "pair_id": f"p-{i}",
                    "time_step": 0,
                    "message_id": "m0",
                    "user_id": f"u{i}",
                },
                context,
            )
            for i in range(60)
        )

        def run():
            runtime.run_frozen_batch(
                state=state,
                journal=journal,
                pool=pool,
                work=work,
                check_dispatch_window=lambda: None,
                backoff_seconds=0.01,
            )

        if failure:
            with pytest.raises((RecoveryCampaignError, v2._V2CellStopped)):
                run()
            assert calls == 10 and peak == 10
            assert state.status == ("stopped" if failure == "quota" else "reconciliation_required")
            assert state.has_inflight == (failure == "unknown")
        else:
            run()
            assert calls == 60 and peak == 10
            state = CampaignProgress.replay(proposal(), CampaignJournal.read(identity))
            run()
            assert calls == 60 and state.physical_attempts == 61
        before = calls
        if failure:
            with pytest.raises(RecoveryCampaignError):
                run()
        assert calls == before
        assert state.suspended_models["gemini-3.1-pro"]["status"] == "stopped"


def test_source_drift_is_detected_before_dispatch_and_preserves_stop(tmp_path):
    from llm_abm_sim._concurrent_recovery_model_lane import source_guard
    from llm_abm_sim.concurrent_robustness_recovery import _file_fact
    path = tmp_path / 'source.json'
    path.write_text('{}')
    guard = source_guard([_file_fact(path)])
    guard()
    path.write_text('[]')
    with pytest.raises(RecoveryCampaignError, match='drift'):
        guard()
    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state, _ = running_kimi(journal)
        state.append(journal, 'model_lane_source_drift', {'failure_category': 'source_drift'})
        assert state.status == 'stopped'
        with pytest.raises(RecoveryCampaignError):
            state.append(journal, 'model_lane_accepted', admission())
