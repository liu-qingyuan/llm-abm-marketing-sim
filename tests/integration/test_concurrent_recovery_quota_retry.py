"""Offline public task extension tests; never real Formal evidence."""

from pathlib import Path

import pytest

from llm_abm_sim import concurrent_robustness_formal_execution as formal
from llm_abm_sim import concurrent_robustness_operator as operator
from llm_abm_sim import concurrent_robustness_recovery_task as task
from llm_abm_sim._concurrent_recovery_campaign import CampaignJournal
from llm_abm_sim.concurrent_robustness_study import ConcurrentRobustnessStudy
from tests.integration import test_concurrent_robustness_recovery_task as fixtures
from tests.integration.test_concurrent_robustness_recovery_epoch import _write
from tests.unit.test_concurrent_robustness_operator import _Transport

recovery_source = fixtures.recovery_source


def test_public_quota_retry_preserves_history_and_completes_only_gemini(tmp_path, monkeypatch, recovery_source):
    plan = fixtures._task_plan(tmp_path, monkeypatch, recovery_source)
    monkeypatch.setattr(ConcurrentRobustnessStudy, "run", fixtures._STUDY_RUN)
    clients = []

    def client(model, timeout):
        assert model in {"deepseek-v4-flash", "gemini-3.1-pro"}
        value = _Transport("deepseek" if model.startswith("deepseek") else "gemini", {})
        clients.append(value)
        return value

    monkeypatch.setattr(operator, "_new_client", client)
    monkeypatch.setenv("LLM_ABM_RUN_LIVE_LLM", "1")
    append = CampaignJournal.append
    interrupted = False

    def pause_after_batch(self, kind, payload):
        nonlocal interrupted
        row = append(self, kind, payload)
        if kind == "batch_committed" and payload["cell_index"] == 4 and not interrupted:
            interrupted = True
            raise RuntimeError("offline crash after durable batch")
        return row

    monkeypatch.setattr(CampaignJournal, "append", pause_after_batch)
    paused = operator.run_concurrent_robustness_recovery_task(plan)
    assert paused["status"] == "paused" and paused["successful_judgments"] == 7260
    monkeypatch.setattr(CampaignJournal, "append", append)
    approval = tmp_path / "parallel-approval.json"
    _write(
        approval,
        {
            "schema_version": "concurrent-recovery-parallel-approval-v1",
            "status": "approved",
            "authorization_reference": "fixture:explicit-four-way-gemini",
            "approved_at_utc": formal._utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "task_plan": {"path": str(plan), "sha256": formal._sha256_file(plan)},
            "paused_head_sha256": paused["campaign_head_sha256"],
            "requested_model": "gemini-3.1-pro",
            "maximum_inflight": 4,
            "stop_after_model": True,
        },
    )
    before = task.inspect_recovery_task(plan)
    calls = [len(c.calls) for c in clients]
    receipt = task.accept_recovery_task_parallelism(
        plan, approval_path=approval, approval_sha256=formal._sha256_file(approval)
    )
    after = task.inspect_recovery_task(plan)
    assert receipt["provider_calls"] == 0 and after["status"] == "paused"
    for key in ("physical_attempts", "new_physical_attempts", "successful_judgments", "self_check_attempts"):
        assert after[key] == before[key]
    assert (
        task.accept_recovery_task_parallelism(
            plan, approval_path=approval, approval_sha256=formal._sha256_file(approval)
        )
        == receipt
    )
    assert [len(c.calls) for c in clients] == calls
    assert task._context(plan).state.parallel_approval["maximum_inflight"] == 4
    changed = tmp_path / "crossed-approval.json"
    import json

    row = json.loads(approval.read_bytes())
    row["maximum_inflight"] = 5
    _write(changed, row)
    from llm_abm_sim._concurrent_recovery_campaign import RecoveryCampaignError

    with pytest.raises(RecoveryCampaignError):
        task.accept_recovery_task_parallelism(plan, approval_path=changed, approval_sha256=formal._sha256_file(changed))
    assert task.inspect_recovery_task(plan) == after

    import threading
    import time
    from llm_abm_sim.providers.robustness import ProviderAttemptFailure
    from llm_abm_sim._concurrent_recovery_quota_retry import terms
    from llm_abm_sim._concurrent_recovery_bundle import read_recovery_bundle

    barrier = threading.Barrier(4)
    lock = threading.Lock()
    initial_calls = 0
    class QuotaTransport(_Transport):
        def create_response(self, *args, **kwargs):
            nonlocal initial_calls
            with lock:
                initial_calls += 1
                number = initial_calls
            barrier.wait(timeout=5)
            if number == 1:
                raise ProviderAttemptFailure(category="quota_exhausted", retryable=False)
            time.sleep(.03)
            return super().create_response(*args, **kwargs)
    monkeypatch.setattr(operator, "_new_client", lambda model, timeout: QuotaTransport("gemini", {}))
    stopped = operator.run_concurrent_robustness_recovery_task(plan)
    assert stopped['status'] == 'stopped' and initial_calls == 4
    assert stopped['successful_judgments'] == 7260
    context = task._context(plan)
    assert len(set(context.state.success_decisions) - set(context.state.judgments)) == 3
    quota = tmp_path/'quota-retry.json'
    _write(quota, {'schema_version':'concurrent-recovery-quota-retry-approval-v1', 'status':'approved',
        'authorization_reference':'fixture:user-explicit-single-quota-retry',
        'approved_at_utc':formal._utc_now().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'task_plan':{'path':str(plan),'sha256':formal._sha256_file(plan)},
        'stopped_head_sha256':stopped['campaign_head_sha256'],'failed_attempts':terms(context.state),
        'initial_formal_attempts':1,'requested_model':'gemini-3.1-pro','maximum_inflight':4,
        'stop_after_model':True,'additional_probes':0})
    crossed_quota = tmp_path/'crossed-quota.json'
    crossed_body = json.loads(quota.read_bytes()); crossed_body['initial_formal_attempts'] = 4
    _write(crossed_quota, crossed_body)
    with pytest.raises(RecoveryCampaignError):
        task.accept_recovery_task_quota_retry(plan,approval_path=crossed_quota,approval_sha256=formal._sha256_file(crossed_quota))
    assert task.inspect_recovery_task(plan)['campaign_head_sha256'] == stopped['campaign_head_sha256']
    accepted = task.accept_recovery_task_quota_retry(plan,approval_path=quota,approval_sha256=formal._sha256_file(quota))
    assert accepted['provider_calls'] == 0 and initial_calls == 4
    assert task.accept_recovery_task_quota_retry(plan,approval_path=quota,approval_sha256=formal._sha256_file(quota)) == accepted
    after_retry = task.inspect_recovery_task(plan)
    for key in ('physical_attempts','successful_judgments','self_check_attempts'):
        assert after_retry[key] == stopped[key]
    calls = active = peak = 0
    first_returned = False
    created = []
    class RetryTransport(_Transport):
        def create_response(self,*args,**kwargs):
            nonlocal calls,active,peak,first_returned
            with lock:
                calls += 1
                number = calls
                assert number == 1 or first_returned
                active += 1
                peak = max(peak,active)
            try:
                time.sleep(.01)
                return super().create_response(*args,**kwargs)
            finally:
                with lock:
                    active -= 1
                    if number == 1: first_returned = True
    def resumed_client(model,timeout):
        assert model == 'gemini-3.1-pro'
        value=RetryTransport('gemini',{});created.append(value);return value
    monkeypatch.setattr(operator,'_new_client',resumed_client)
    finished=operator.run_concurrent_robustness_recovery_task(plan)
    assert finished['status']=='checkpoint' and finished['current_model']=='gemini-3.8-flash-high'
    assert finished['successful_judgments']==14400 and finished['physical_attempts']==14402
    assert finished['self_check_attempts']==2 and calls==7137 and peak==4
    assert len(created)==4 and all(c.closed==1 for c in created)
    bundle=read_recovery_bundle(finished['execution_bundle'])
    assert bundle['realization_verification']['verified_terminal_count']==14400
    assert bundle['realization_verification']['verified_batch_commit_count']==240
    assert str(quota) in {row['path'] for row in bundle['artifact_facts']}
    assert operator.run_concurrent_robustness_recovery_task(plan)==finished and calls==7137
    assert task.accept_recovery_task_quota_retry(plan,approval_path=quota,approval_sha256=formal._sha256_file(quota))==accepted
