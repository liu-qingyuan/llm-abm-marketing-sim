from copy import deepcopy

import pytest

from llm_abm_sim._concurrent_recovery_campaign import CampaignJournal, recovery_scope
from tests.unit.test_concurrent_recovery_progress import _journal
from tests.unit.test_recovery_final_parallel import approval, prepared


def stopped(journal):
    s = prepared(journal)
    s.append(journal, "final_model_parallel_accepted", approval())
    s.status = "reconciliation_required"
    s.parallel_active_batch = (19, 6)
    s.parallel_inflight = {(19, 417): 1}
    s.parallel_unknown = {(19, 417)}
    s.prefix[16:] = [1800, 1800, 1800, 360]
    return s


def grant():
    return {
        "approval": {"path": "/fixture/gpt-manual.json", "sha256": "f" * 64},
        "unknown_intents": [
            {
                "cell_index": 19,
                "pair_schedule_position": 417,
                "attempt_number": 1,
                "intent_sha256": "a" * 64,
                "intent_sequence": 126297,
            }
        ],
    }


def test_archive_one_gpt_unknown_preserves_kimi_and_budget(tmp_path):
    with recovery_scope(identity := _journal(tmp_path)):
        journal = CampaignJournal.open(identity)
        s = stopped(journal)
        before = deepcopy((s.physical_attempts, s.prefix, s.success_decisions, s.kimi_archived_unknown))
        s.append(journal, "gpt_manual_retry_accepted", grant())
        assert s.status == "paused" and not s.has_inflight
        assert before == (s.physical_attempts, s.prefix, s.success_decisions, s.kimi_archived_unknown)
        assert s.next_attempt_number((19, 417)) == 2
        assert s.gpt_archived_unknown[(19, 417)]["intent_sha256"] == "a" * 64


def test_gpt_v7_preserves_unknown_and_rejects_extra_retry():
    import pytest

    from llm_abm_sim._concurrent_recovery_judgment import RecoveryJudgmentV1
    from tests.unit.test_concurrent_recovery_judgment import _payload, _rehash
    from tests.unit.test_concurrent_recovery_parallel_progress import proposal

    p = _payload(historical=False)
    p["schema_version"] = "concurrent-recovery-provider-judgment-v7"
    p["cell_index"] = 19
    p["cell"] = proposal()["frozen_context"]["prompt_model_cells"][19]
    p["unknown_attempts"] = [{"attempt_number": 1, "intent_sha256": "a" * 64}]
    p["manual_retry_approval"] = {"path": "/fixture/manual.json", "sha256": "f" * 64}
    a = p["new_attempts"][0]
    a["attempt_number"] = 2
    a["observed_model_counts"] = {"gpt-5.6-sol": 1}
    a["provider_route"] = "pi_openai_oauth_subscription"
    a["billing_semantics"] = "subscription_quota_with_nominal_usd_reference"
    a["billing_currency"] = None
    _rehash(p)
    j = RecoveryJudgmentV1.model_validate(p)
    assert (
        j.unknown_usage_present and j.realized_projection(realization_source_identity="b" * 64).request_invocations == 2
    )
    p["new_attempts"].append(deepcopy(a))
    p["new_attempts"][-1]["attempt_number"] = 3
    _rehash(p)
    with pytest.raises(ValueError):
        RecoveryJudgmentV1.model_validate(p)


@pytest.mark.parametrize("fail", [False, True])
def test_gpt_unknown_retry_dispatches_only_missing_pair_once(tmp_path, fail):
    from llm_abm_sim import _concurrent_recovery_parallel_runtime as runtime
    from llm_abm_sim import concurrent_robustness_operator as operator
    from llm_abm_sim.concurrent_message_experiment import _VariantDecisionContext
    from llm_abm_sim.decision import EngageDecision
    from tests.unit.test_concurrent_robustness_operator import _Transport
    from tests.unit.test_robustness_provider_adapters import _context

    with recovery_scope(identity := _journal(tmp_path)):
        journal = CampaignJournal.open(identity)
        s = stopped(journal)
        s.append(journal, "gpt_manual_retry_accepted", grant())
        s.status = "running"
        s.epochs[-1]["epoch_identity_sha256"] = "e" * 64
        cell = s.cells[19]
        data = _context()
        context = _VariantDecisionContext(
            decision_variant="primary",
            prompt_token=cell.prompt_version,
            **{k: data[k] for k in ("post", "profile", "peer_context", "platform_context")},
        )
        work = tuple(
            runtime.FrozenWork(
                {
                    "cell_index": 19,
                    "pair_schedule_position": n,
                    "pair_id": f"p{n}",
                    "time_step": 6,
                    "message_id": "m0",
                    "user_id": f"u{n}",
                },
                context,
            )
            for n in range(360, 420)
        )
        s.parallel_batches[19, 6] = {"cell_index": 19, "time_step": 6, "pairs": [w.reservation() for w in work]}
        for w in work:
            if w.key != (19, 417):
                s.success_decisions[w.key] = EngageDecision(
                    engage=False, probability=0.2, reason="preserved", confidence=0.8, action="ignore"
                )

        class Transport(_Transport):
            def create_response(self, *args, **kwargs):
                value = super().create_response(*args, **kwargs)
                if fail:
                    from llm_abm_sim.decision import ProviderAttemptFailure

                    raise ProviderAttemptFailure(category="transport", retryable=True)
                return value

        clients = [Transport("openai", {}) for _ in range(5)]
        pool = runtime.ParallelAdapterPool(tuple(operator._adapter_for_cell(cell, c) for c in clients))
        before = s.physical_attempts
        from contextlib import nullcontext

        from llm_abm_sim import concurrent_robustness_v2 as v2

        with pytest.raises(v2._V2CellStopped) if fail else nullcontext():
            runtime.run_frozen_batch(
                state=s, journal=journal, pool=pool, work=work, check_dispatch_window=lambda: None, backoff_seconds=0
            )
        assert sum(len(c.calls) for c in clients) == 1 and s.physical_attempts == before + 1
        assert s.new_attempts[19, 417][0].attempt_number == 2
        if fail:
            assert s.status == "stopped" and not s.has_inflight
            assert s.new_attempts[19, 417][0].outcome == "nonretryable_failure"
            return
        runtime.run_frozen_batch(
            state=s, journal=journal, pool=pool, work=work, check_dispatch_window=lambda: None, backoff_seconds=0
        )
        assert sum(len(c.calls) for c in clients) == 1


def test_public_gpt_receipt_is_exact_and_idempotent(tmp_path, monkeypatch):
    import hashlib
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    import pytest

    from llm_abm_sim import concurrent_robustness_recovery_task as task
    from llm_abm_sim._concurrent_recovery_campaign import RecoveryCampaignError
    from llm_abm_sim._concurrent_recovery_manual_retry import validate_gpt_receipt
    from llm_abm_sim.concurrent_robustness_formal_execution import _canonical_json_bytes

    with recovery_scope(identity := _journal(tmp_path)):
        journal = CampaignJournal.open(identity)
        s = stopped(journal)
        event = journal.append(
            "parallel_attempt_intent", {"cell_index": 19, "pair_schedule_position": 417, "attempt_number": 1}
        )
    now = datetime.now(timezone.utc).replace(microsecond=0)
    ref = {"path": "/fixture/task.json", "sha256": "d" * 64}
    origins = SimpleNamespace(
        campaign=identity,
        handoff=SimpleNamespace(model_dump=lambda **_: ref),
        task_plan={"authorization": {"approved_at_utc": (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")}},
    )
    rows = [{**event["payload"], "intent_sequence": event["sequence"], "intent_sha256": event["record_sha256"]}]
    a = {
        "schema_version": "gpt-manual-unknown-retry-approval-v1",
        "status": "approved",
        "authorization_reference": "user-continue-one-unknown-retry",
        "approved_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "task_plan": ref,
        "stopped_head_sha256": journal.head,
        "unknown_intents": rows,
        "additional_attempts": 1,
        "usage_unknown_preserved": True,
        "maximum_inflight": 5,
        "production_deploy_eligible": False,
    }
    path = tmp_path / "approval.json"
    path.write_bytes(_canonical_json_bytes(a))
    path.chmod(0o444)
    payload = {
        "approval": {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
        "unknown_intents": rows,
    }
    monkeypatch.setattr(task, "_current", lambda *_: True)
    with pytest.raises(RecoveryCampaignError):
        validate_gpt_receipt(origins, s, payload, now, "0" * 64)
    context = SimpleNamespace(origins=origins, state=s, journal=journal, plan={})
    monkeypatch.setattr(task, "_context", lambda _: context)
    monkeypatch.setattr(task, "_read_revocation", lambda _: None)
    args = {"approval_path": path, "approval_sha256": payload["approval"]["sha256"]}
    first = task.accept_recovery_task_gpt_manual_retry("/fixture/task.json", **args)
    head = journal.head
    second = task.accept_recovery_task_gpt_manual_retry("/fixture/task.json", **args)
    assert first == second and journal.head == head and first["provider_calls"] == 0
