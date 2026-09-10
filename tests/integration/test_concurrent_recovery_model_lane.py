"""Offline public task extension tests; never real Formal evidence."""

from typing import Any

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


def test_public_kimi_lane_completes_7200_and_120_barriers_with_shared_budget(tmp_path, monkeypatch, recovery_source):
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
    original_calls = [len(c.calls) for c in clients]
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
    assert [len(c.calls) for c in clients] == original_calls
    parallel = task._context(plan).state.parallel_approval
    assert parallel is not None and parallel["maximum_inflight"] == 4
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

    from llm_abm_sim._concurrent_recovery_bundle import read_recovery_bundle
    from llm_abm_sim.providers.robustness import ProviderAttemptFailure

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
            time.sleep(0.03)
            return super().create_response(*args, **kwargs)

    monkeypatch.setattr(operator, "_new_client", lambda model, timeout: QuotaTransport("gemini", {}))
    stopped: dict[str, Any] = operator.run_concurrent_robustness_recovery_task(plan)
    assert stopped["status"] == "stopped" and initial_calls == 4
    assert stopped["successful_judgments"] == 7260
    context = task._context(plan)
    assert len(set(context.state.success_decisions) - set(context.state.judgments)) == 3
    lane = tmp_path / "kimi-lane.json"
    _write(
        lane,
        {
            "schema_version": "concurrent-recovery-model-lane-approval-v1",
            "status": "approved",
            "authorization_reference": "fixture:user-confirmed-kimi-only",
            "approved_at_utc": formal._utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "task_plan": {"path": str(plan), "sha256": formal._sha256_file(plan)},
            "stopped_head_sha256": stopped["campaign_head_sha256"],
            "requested_model": "kimi-coding/k3-256k",
            "maximum_inflight": 10,
            "global_maximum_inflight": 10,
            "stop_after_model": True,
        },
    )

    def accept():
        return task.accept_recovery_task_model_lane(plan, approval_path=lane, approval_sha256=formal._sha256_file(lane))

    old_prefix = context.journal.records
    old_state = context.state
    receipt = accept()
    assert accept() == receipt and receipt["provider_calls"] == 0
    # Preserve an actual adapter-level 256 failure before the explicit 1024 amendment.
    failures = 0

    class CeilingTransport(_Transport):
        def create_response(self, *args, **kwargs):
            nonlocal failures
            failures += 1
            assert kwargs['output_token_ceiling'] == 256
            raise ProviderAttemptFailure(category='output_ceiling_exceeded', retryable=False)

    monkeypatch.setattr(operator, '_new_client', lambda model, timeout: CeilingTransport('kimi', {}))
    ceiling_stop = operator.run_concurrent_robustness_recovery_task(plan)
    assert ceiling_stop['status'] == 'stopped' and failures == 1
    assert ceiling_stop['physical_attempts'] == stopped['physical_attempts']
    failed_context = task._context(plan)
    original_check = failed_context.state.self_checks['kimi-coding/k3-256k']
    output_approval = tmp_path / 'kimi-output1024.json'
    _write(output_approval, {
        'schema_version': 'concurrent-recovery-kimi-output-amendment-v1', 'status': 'approved',
        'authorization_reference': 'fixture:user-approved-1024-and-one-additional-check',
        'approved_at_utc': formal._utc_now().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'task_plan': {'path': str(plan), 'sha256': formal._sha256_file(plan)},
        'stopped_head_sha256': ceiling_stop['campaign_head_sha256'],
        'original_self_check_sha256': task._v2._json_sha256(original_check),
        'previous_output_token_ceiling': 256, 'requested_model': 'kimi-coding/k3-256k',
        'output_token_ceiling': 1024, 'additional_self_check_cap': 1,
    })
    def amend():
        return task.accept_recovery_task_kimi_output_amendment(
            plan, approval_path=output_approval, approval_sha256=formal._sha256_file(output_approval))
    output_receipt = amend()
    assert amend() == output_receipt and output_receipt['provider_calls'] == 0
    calls = active = peak = 0
    created = []
    ten = threading.Barrier(10)

    class KimiTransport(_Transport):
        def create_response(self, *args, **kwargs):
            nonlocal calls, active, peak
            assert kwargs["output_token_ceiling"] == 1024
            with lock:
                calls += 1
                number = calls
                active += 1
                peak = max(peak, active)
            try:
                # First call is the sole self-check. The first Formal batch proves ten lanes.
                if 2 <= number <= 11:
                    ten.wait(timeout=10)
                time.sleep(0.01)
                return super().create_response(*args, **kwargs)
            finally:
                with lock:
                    active -= 1

    def kimi_client(model, timeout):
        assert model == "kimi-coding/k3-256k"
        value = KimiTransport("kimi", {})
        created.append(value)
        return value

    monkeypatch.setattr(operator, "_new_client", kimi_client)
    finished: dict[str, Any] = operator.run_concurrent_robustness_recovery_task(plan)
    assert finished["status"] == "model_complete", finished
    assert finished["current_model"] == "kimi-coding/k3-256k"
    assert finished["successful_judgments"] == stopped["successful_judgments"] + 7200
    assert finished["physical_attempts"] == stopped["physical_attempts"] + 7200
    assert finished["self_check_attempts"] == stopped["self_check_attempts"] + 2
    assert finished["cell_prefixes"][12:16] == [1800] * 4
    assert finished["cell_prefixes"][:12] == stopped["cell_prefixes"][:12]
    assert finished["cell_prefixes"][16:] == [0] * 4
    assert calls == 7201 and peak == 10
    assert len(created) == 10 and all(c.closed == 1 for c in created)
    bundle = read_recovery_bundle(finished["execution_bundle"])
    assert bundle["realization_verification"]["verified_terminal_count"] == 14460
    assert bundle["realization_verification"]["verified_batch_commit_count"] == 241
    assert str(lane) in {row["path"] for row in bundle["artifact_facts"]}
    reread = task._context(plan)
    assert reread.journal.records[: len(old_prefix)] == old_prefix
    assert reread.state.suspended_models["gemini-3.1-pro"]["status"] == "stopped"
    assert reread.state.parallel_approval == old_state.parallel_approval
    assert reread.state.quota_retry_approval == old_state.quota_retry_approval
    kimi_commits = [key for key in reread.state.batch_commits if key[1] in range(12, 16)]
    assert len(kimi_commits) == 120
    assert operator.run_concurrent_robustness_recovery_task(plan) == finished and calls == 7201
    assert accept() == receipt and len(created) == 10
    assert reread.state.self_checks['kimi-coding/k3-256k'] == original_check
    assert reread.state.amended_self_check is not None
    assert reread.state.amended_self_check['attempt']['outcome'] == 'succeeded'
    judgments = [v for k, v in reread.state.judgments.items() if k[0] in range(12, 16)]
    assert len(judgments) == 7200
    assert all(v['schema_version'] == 'concurrent-recovery-provider-judgment-v3' for v in judgments)
    assert all(v['output_amendment_approval']['sha256'] == formal._sha256_file(output_approval) for v in judgments)
    assert str(output_approval) in {row['path'] for row in bundle['artifact_facts']}
    assert amend() == output_receipt and calls == 7201
