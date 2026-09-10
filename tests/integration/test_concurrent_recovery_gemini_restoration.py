"""One explicit Gemini restoration; all test Provider activity is offline."""

from typing import Any

import pytest

from llm_abm_sim import concurrent_robustness_formal_execution as formal
from llm_abm_sim import concurrent_robustness_operator as operator
from llm_abm_sim import concurrent_robustness_recovery_task as task
from llm_abm_sim._concurrent_recovery_campaign import CampaignJournal, RecoveryCampaignError
from llm_abm_sim.concurrent_robustness_study import ConcurrentRobustnessStudy
from tests.integration import test_concurrent_robustness_recovery_task as fixtures
from tests.integration.test_concurrent_robustness_recovery_epoch import _write
from tests.unit.test_concurrent_robustness_operator import _Transport

recovery_source = fixtures.recovery_source


def test_public_restoration_rejects_untouched_task_without_campaign_mutation(
    tmp_path,
    monkeypatch,
    recovery_source,
):
    plan = fixtures._task_plan(tmp_path, monkeypatch, recovery_source)
    before = task.inspect_recovery_task(plan)
    approval = tmp_path / "restoration.json"
    digest = _write(approval, {"schema_version": "concurrent-recovery-gemini-restoration-approval-v1"})
    with pytest.raises(RecoveryCampaignError):
        task.accept_recovery_task_gemini_restoration(
            plan,
            approval_path=approval,
            approval_sha256=digest,
        )
    assert task.inspect_recovery_task(plan) == before


def test_public_gemini_restoration_after_consumed_retry_and_kimi_stop(tmp_path, monkeypatch, recovery_source):
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
    original_calls = [len(c.calls) for c in clients]
    receipt = task.accept_recovery_task_parallelism(
        plan, approval_path=approval, approval_sha256=formal._sha256_file(approval)
    )
    assert receipt["provider_calls"] == 0
    assert [len(c.calls) for c in clients] == original_calls
    # Old parallel/lane/amendment idempotence is covered by their own tests;
    # this scenario retains the entire sequence and tests new restoration twice.

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
    from llm_abm_sim._concurrent_recovery_quota_retry import terms as quota_terms

    quota = tmp_path / "old-quota-retry.json"
    _write(
        quota,
        {
            "schema_version": "concurrent-recovery-quota-retry-approval-v1",
            "status": "approved",
            "authorization_reference": "fixture:one-old-retry",
            "approved_at_utc": formal._utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "task_plan": {"path": str(plan), "sha256": formal._sha256_file(plan)},
            "stopped_head_sha256": stopped["campaign_head_sha256"],
            "failed_attempts": quota_terms(context.state),
            "initial_formal_attempts": 1,
            "requested_model": "gemini-3.1-pro",
            "maximum_inflight": 4,
            "stop_after_model": True,
            "additional_probes": 0,
        },
    )
    quota_receipt = task.accept_recovery_task_quota_retry(
        plan, approval_path=quota, approval_sha256=formal._sha256_file(quota)
    )
    retry_calls = 0

    class SecondQuotaTransport(_Transport):
        def create_response(self, *args, **kwargs):
            nonlocal retry_calls
            with lock:
                retry_calls += 1
                n = retry_calls
            # Reuse three responses, finish the old batch including its quota Judgment,
            # then stop in the following batch. The old retry grant is truly consumed.
            if n == 58:
                raise ProviderAttemptFailure(category="quota_exhausted", retryable=False)
            time.sleep(0.01)
            return super().create_response(*args, **kwargs)

    monkeypatch.setattr(operator, "_new_client", lambda model, timeout: SecondQuotaTransport("gemini", {}))
    stopped = operator.run_concurrent_robustness_recovery_task(plan)
    assert stopped["status"] == "stopped" and stopped["successful_judgments"] == 7320
    context = task._context(plan)
    assert context.state.quota_retry_pending is None
    assert any(
        j.get("quota_retry_approval", {}).get("sha256") == formal._sha256_file(quota)
        for j in context.state.judgments.values()
    )
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

    receipt = accept()
    assert receipt["provider_calls"] == 0
    # Preserve an actual adapter-level 256 failure before the explicit 1024 amendment.
    failures = 0

    class CeilingTransport(_Transport):
        def create_response(self, *args, **kwargs):
            nonlocal failures
            failures += 1
            assert kwargs["output_token_ceiling"] == 256
            raise ProviderAttemptFailure(category="output_ceiling_exceeded", retryable=False)

    monkeypatch.setattr(operator, "_new_client", lambda model, timeout: CeilingTransport("kimi", {}))
    ceiling_stop = operator.run_concurrent_robustness_recovery_task(plan)
    assert ceiling_stop["status"] == "stopped" and failures == 1
    assert ceiling_stop["physical_attempts"] == stopped["physical_attempts"]
    failed_context = task._context(plan)
    original_check = failed_context.state.self_checks["kimi-coding/k3-256k"]
    output_approval = tmp_path / "kimi-output1024.json"
    _write(
        output_approval,
        {
            "schema_version": "concurrent-recovery-kimi-output-amendment-v1",
            "status": "approved",
            "authorization_reference": "fixture:user-approved-1024-and-one-additional-check",
            "approved_at_utc": formal._utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "task_plan": {"path": str(plan), "sha256": formal._sha256_file(plan)},
            "stopped_head_sha256": ceiling_stop["campaign_head_sha256"],
            "original_self_check_sha256": task._v2._json_sha256(original_check),
            "previous_output_token_ceiling": 256,
            "requested_model": "kimi-coding/k3-256k",
            "output_token_ceiling": 1024,
            "additional_self_check_cap": 1,
        },
    )

    def amend():
        return task.accept_recovery_task_kimi_output_amendment(
            plan, approval_path=output_approval, approval_sha256=formal._sha256_file(output_approval)
        )

    output_receipt = amend()
    assert output_receipt["provider_calls"] == 0
    kimi_calls = 0

    class KimiEntitlementTransport(_Transport):
        def create_response(self, *args, **kwargs):
            nonlocal kimi_calls
            assert kwargs["output_token_ceiling"] == 1024
            with lock:
                kimi_calls += 1
                n = kimi_calls
            if n == 3:
                raise ProviderAttemptFailure(category="entitlement", retryable=False, status_code=403)
            time.sleep(0.01)
            return super().create_response(*args, **kwargs)

    monkeypatch.setattr(operator, "_new_client", lambda model, timeout: KimiEntitlementTransport("kimi", {}))
    kimi_stop = operator.run_concurrent_robustness_recovery_task(plan)
    assert kimi_stop["status"] == "stopped"
    context = task._context(plan)
    assert context.state.current_model == "kimi-coding/k3-256k"
    assert any(a[-1].failure_category == "entitlement" for a in context.state.new_attempts.values())
    original_records = context.journal.records
    original_attempts = {k: v for k, v in context.state.new_attempts.items() if k[0] in range(12, 16)}
    original_successes = {k: v for k, v in context.state.success_decisions.items() if k[0] in range(12, 16)}
    restore = _probe_and_restoration_approval(tmp_path, plan, context)

    def restore_once():
        return task.accept_recovery_task_gemini_restoration(
            plan, approval_path=restore, approval_sha256=formal._sha256_file(restore)
        )

    restored = restore_once()
    assert restore_once() == restored and restored["provider_calls"] == 0
    restored_state = task.inspect_recovery_task(plan)
    assert restored_state["current_model"] == "gemini-3.1-pro"
    for key in ("physical_attempts", "successful_judgments", "self_check_attempts"):
        assert restored_state[key] == kimi_stop[key]

    calls = active = peak = 0
    trial_returned = False

    class RestoredTransport(_Transport):
        def create_response(self, *args, **kwargs):
            nonlocal calls, active, peak, trial_returned
            assert kwargs["output_token_ceiling"] == 256  # Adapter passes visible ceiling; gateway owns wire1024
            with lock:
                calls += 1
                n = calls
                assert n == 1 or trial_returned
                active += 1
                peak = max(peak, active)
            try:
                time.sleep(0.01)
                return super().create_response(*args, **kwargs)
            finally:
                with lock:
                    active -= 1
                    if n == 1:
                        trial_returned = True

    def restored_client(model, timeout):
        assert model == "gemini-3.1-pro"
        return RestoredTransport("gemini", {})

    monkeypatch.setattr(operator, "_new_client", restored_client)
    finished = operator.run_concurrent_robustness_recovery_task(plan)
    assert finished["status"] == "model_complete", finished
    assert finished["current_model"] == "gemini-3.1-pro"
    assert finished["successful_judgments"] == 14400
    assert finished["cell_prefixes"][4:8] == [1800] * 4
    assert finished["cell_prefixes"][8:] == [0] * 12
    assert peak == 4 and finished["self_check_attempts"] == kimi_stop["self_check_attempts"]
    reread = task._context(plan)
    assert reread.journal.records[: len(original_records)] == original_records
    assert {k: v for k, v in reread.state.new_attempts.items() if k[0] in range(12, 16)} == original_attempts
    assert {k: v for k, v in reread.state.success_decisions.items() if k[0] in range(12, 16)} == original_successes
    assert reread.state.quota_retry_approval == context.state.quota_retry_approval
    assert quota_receipt["provider_calls"] == 0
    assert reread.state.output_amendment == context.state.output_amendment
    bundle = read_recovery_bundle(finished["execution_bundle"])
    assert bundle["realization_verification"]["verified_terminal_count"] == 14400
    # Gemini runs in a new epoch, replay barriers remain independently verifiable.
    assert (
        len([k for k in reread.state.batch_commits if k[0] == len(reread.state.epochs) and k[1] in range(4, 8)]) == 120
    )
    assert str(restore) in {f["path"] for f in bundle["artifact_facts"]}
    assert restore_once() == restored
    before_calls = calls
    assert operator.run_concurrent_robustness_recovery_task(plan) == finished
    assert calls == before_calls


def _probe_and_restoration_approval(tmp_path, plan, context):
    from llm_abm_sim._concurrent_recovery_gemini_restoration import terms
    from tests.unit.test_concurrent_recovery_parallel_progress import attempt

    now = formal._utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")
    plan_ref = {"path": str(plan), "sha256": formal._sha256_file(plan)}

    def save(name, body):
        path = tmp_path / name
        digest = _write(path, body)
        return {"path": str(path), "sha256": digest}

    auth = save(
        "probe-auth.json",
        {
            "schema_version": "recovery-explicit-single-probe-authorization-v1",
            "task_plan": plan_ref,
            "requested_model": "gemini-3.1-pro",
            "required_observed_model": "gemini-pro-agent",
            "maximum_new_attempts": 1,
            "automatic_retries": 0,
            "new_formal_attempts_authorized": 0,
            "other_models_authorized": [],
            "approved_at_utc": now,
        },
    )
    cell = context.state.cells[4]
    adapter = operator._adapter_for_cell(cell, _Transport("gemini", {}))
    intent = save(
        "probe-intent.json",
        {
            "authorization_sha256": auth["sha256"],
            "at_utc": now,
            "attempt_number": 1,
            "maximum_attempts": 1,
            "request_evidence": dict(adapter.request_evidence),
        },
    )
    probe_attempt = attempt()
    probe_attempt.update(
        provider_route="antigravity_openai_compatible_gateway",
        billing_semantics="gateway_quota_usage",
        billing_currency=None,
    )
    result = save(
        "probe-result.json",
        {
            "status": "succeeded",
            "decision_valid": True,
            "automatic_retries": 0,
            "new_formal_attempts": 0,
            "campaign_not_resumed": True,
            "settled_at_utc": now,
            "attempt": probe_attempt,
        },
    )
    receipt = save(
        "probe-receipt.json",
        {
            "campaign_head_unchanged": True,
            "head_before": context.journal.head,
            "head_after": context.journal.head,
            "campaign_writes_by_probe": 0,
            "new_formal_attempts": 0,
        },
    )
    approval = tmp_path / "gemini-restoration.json"
    _write(
        approval,
        {
            "schema_version": "concurrent-recovery-gemini-restoration-approval-v1",
            "status": "approved",
            "authorization_reference": "fixture:explicit-one-restoration",
            "approved_at_utc": now,
            "task_plan": plan_ref,
            "stopped_head_sha256": context.journal.head,
            "initial_formal_attempts": 1,
            "additional_probes": 0,
            "requested_model": "gemini-3.1-pro",
            "maximum_inflight": 4,
            "stop_after_model": True,
            "failed_attempts": terms(context.state),
            "probe_authorization": auth,
            "probe_intent": intent,
            "probe_result": result,
            "probe_receipt": receipt,
        },
    )
    return approval
