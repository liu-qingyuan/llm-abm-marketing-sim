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


def test_parallel_acceptance_is_hash_bound_idempotent_and_zero_provider(tmp_path, monkeypatch, recovery_source):
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

    # Same public Operator/Study entry completes the allowed model only. These
    # transports are synthetic; 14,400 below is never a real-experiment claim.
    import threading
    import time

    from llm_abm_sim._concurrent_recovery_bundle import read_recovery_bundle

    mutex = threading.Lock()
    active = 0
    peak = 0
    new_clients = []

    class ParallelTransport(_Transport):
        def create_response(self, *args, **kwargs):
            nonlocal active, peak
            with mutex:
                active += 1
                peak = max(active, peak)
            try:
                time.sleep(0.01)
                return super().create_response(*args, **kwargs)
            finally:
                with mutex:
                    active -= 1

    def parallel_client(model, timeout):
        assert model == "gemini-3.1-pro"
        value = ParallelTransport("gemini", {})
        new_clients.append(value)
        return value

    monkeypatch.setattr(operator, "_new_client", parallel_client)
    finished = operator.run_concurrent_robustness_recovery_task(plan)
    assert finished["status"] == "checkpoint"
    assert finished["current_model"] == "gemini-3.8-flash-high"
    assert finished["successful_judgments"] == 14400 and finished["physical_attempts"] == 14401
    assert finished["self_check_attempts"] == 2 and finished["historical_all_attempts_total_tokens"] is None
    assert peak == 4 and len(new_clients) == 4 and sum(len(c.calls) for c in new_clients) == 7140
    assert all(c.closed == 1 for c in new_clients)
    bundle = read_recovery_bundle(Path(finished["execution_bundle"]))
    assert bundle["realization_verification"]["verified_terminal_count"] == 14400
    assert bundle["realization_verification"]["verified_batch_commit_count"] == 240
    assert str(approval) in {row["path"] for row in bundle["artifact_facts"]}
    repeated = operator.run_concurrent_robustness_recovery_task(plan)
    assert repeated == finished and len(new_clients) == 4
    assert (
        task.accept_recovery_task_parallelism(
            plan, approval_path=approval, approval_sha256=formal._sha256_file(approval)
        )
        == receipt
    )
