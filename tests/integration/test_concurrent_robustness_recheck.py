"""Offline transports exercise the public one-time recheck acceptance Seam."""
from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from llm_abm_sim import concurrent_robustness_formal_execution as formal
from llm_abm_sim import concurrent_robustness_operator as operator
from llm_abm_sim import concurrent_robustness_recovery_task as task
from llm_abm_sim import concurrent_robustness_v2 as v2
from tests.integration import test_concurrent_robustness_recovery_task as task_fixtures
from tests.integration.test_concurrent_robustness_recovery_epoch import _write
from tests.unit.test_concurrent_robustness_operator import _Transport

_task_plan = task_fixtures._task_plan
recovery_source = task_fixtures.recovery_source


def _ref(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": formal._sha256_file(path)}


def _packet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: Path,
            failure: str = "connection") -> tuple[Path, Path, list[Any]]:
    plan = _task_plan(tmp_path, monkeypatch, source)
    clients: list[Any] = []

    class Broken(_Transport):
        def create_response(self, *args: Any, **kwargs: Any) -> Any:
            from llm_abm_sim.providers.robustness import ProviderAttemptFailure
            self.calls.append({})
            raise ProviderAttemptFailure(category=failure, retryable=False)

    def client(model: str, timeout: float) -> Any:
        value = Broken("deepseek", {})
        clients.append(value)
        return value

    monkeypatch.setattr(operator, "_new_client", client)
    monkeypatch.setenv("LLM_ABM_RUN_LIVE_LLM", "1")
    stopped = operator.run_concurrent_robustness_recovery_task(plan)
    assert stopped["status"] == "stopped"
    context = task._context(plan)
    model = context.state.current_model
    assert model is not None
    cell = context.state.cells[0]
    probe: Any = operator._adapter_for_cell(cell, cast(Any, _Transport("deepseek", {})))
    before = v2._v2_adapter_snapshot(probe)
    data = task._self_check_input()
    decision = probe.decide(post=data.post, profile=data.profile, peer_context=data.peer_context,
                            platform_context=data.platform_context, time_step=data.time_step)
    attempt = v2._v2_attempt_evidence(adapter=probe, before=before, attempt_number=1,
        outcome="succeeded", error=None, wait_seconds=None, wait_source=None)
    health = task._health_contract(context.origins, model)
    auth = tmp_path / "probe-authorization.json"
    _write(auth, {"schema_version": "recovery-explicit-single-probe-authorization-v1",
        "previous_task_plan": _ref(plan), "approved_at_utc": formal._utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "maximum_new_attempts": 1, "automatic_retries": 0, "effective_probe_retries": 0,
        "new_formal_attempts_authorized": 0, "previous_task_self_check_attempts": 1,
        "requested_model": model, "required_observed_model": cell.required_observed_model,
        "route": health["route"], "self_check_prompt_sha256": health["prompt_sha256"],
        "inherited_formal_request_contract": context.origins.source.manifest.request_contract.model_dump(mode="json"),
        "request_timeout_seconds": context.origins.source.request.run_parameters.request_timeout_seconds,
        "other_models_authorized": [], "old_failure_kept": True,
        "task_reset_or_reauthorization": False, "release_or_deployment": False,
        "production_deploy_eligible": False, "fee_policy": "optional_best_effort_no_cash_ceiling_v1"})
    intent = tmp_path / "probe-intent.json"
    _write(intent, {"schema_version": "recovery-explicit-single-probe-intent-v1",
        "at_utc": formal._utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"), "attempt_number": 1,
        "authorization_sha256": _ref(auth)["sha256"], "maximum_attempts": 1,
        "requested_model": model, "request_evidence": probe.request_evidence})
    result = tmp_path / "probe-result.json"
    _write(result, {"schema_version": "recovery-explicit-single-probe-result-v1", "status": "succeeded",
        "settled_at_utc": formal._utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "authorization_sha256": _ref(auth)["sha256"], "intent_sha256": _ref(intent)["sha256"],
        "attempt": attempt.model_dump(mode="json"), "decision": decision.model_dump(mode="json", exclude={"provider_metadata"}),
        "campaign_not_resumed": True, "new_formal_attempts": 0, "release_or_deployment": False})
    approval = tmp_path / "recheck-approval.json"
    _write(approval, {"schema_version": "concurrent-recovery-recheck-approval-v1", "status": "approved",
        "authorization_reference": "fixture:explicit-acceptance", "approved_at_utc": formal._utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "task_plan": _ref(plan), "stopped_head_sha256": context.journal.head,
        "failed_settlement": _ref(context.journal.root / "events" / "00000003.json"),
        "probe_authorization": _ref(auth), "probe_intent": _ref(intent), "probe_result": _ref(result)})
    return plan, approval, clients


def test_accept_recheck_is_durable_idempotent_and_keeps_failure_and_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path,
) -> None:
    plan, approval, clients = _packet(tmp_path, monkeypatch, recovery_source)
    before = task.inspect_recovery_task(plan)
    result = task.accept_recovery_task_recheck(plan, approval_path=approval, approval_sha256=formal._sha256_file(approval))
    assert result["provider_calls"] == 0
    after = task.inspect_recovery_task(plan)
    assert after["status"] == "ready"
    assert after["self_check_attempts"] == 2
    assert after["self_check_failures"] == {"deepseek-v4-flash": "connection"}
    assert after["physical_attempts"] == before["physical_attempts"]
    assert after["successful_judgments"] == before["successful_judgments"]
    assert len(clients) == len(clients[0].calls) == 1
    again = task.accept_recovery_task_recheck(plan, approval_path=approval, approval_sha256=formal._sha256_file(approval))
    assert again == result
    assert task.inspect_recovery_task(plan) == after
    context = task._context(plan)
    epoch = task._epoch_body(context.origins, context.state, context.journal.head)
    assert epoch["derivation"]["maximum_remaining_physical_attempts"] == context.origins.proposal["maximum_new_physical_attempts"]
    assert context.state.attempts(context.state.failed_key) == context.state.historical_failure


def test_recheck_does_not_relax_other_failures_or_crossed_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path,
) -> None:
    import json

    from llm_abm_sim._concurrent_recovery_campaign import RecoveryCampaignError

    plan, approval, clients = _packet(tmp_path, monkeypatch, recovery_source, failure="usage_evidence")
    before = task.inspect_recovery_task(plan)
    with pytest.raises(RecoveryCampaignError, match="hard stop"):
        task.accept_recovery_task_recheck(plan, approval_path=approval, approval_sha256=formal._sha256_file(approval))
    assert task.inspect_recovery_task(plan) == before
    body = json.loads(approval.read_text())
    body["stopped_head_sha256"] = "a" * 64
    crossed = tmp_path / "crossed-approval.json"
    _write(crossed, body)
    with pytest.raises(RecoveryCampaignError):
        task.accept_recovery_task_recheck(plan, approval_path=crossed, approval_sha256=formal._sha256_file(crossed))
    assert len(clients) == len(clients[0].calls) == 1


def test_accepted_recheck_skips_probe_preserves_bundle_and_later_hard_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path,
) -> None:
    from llm_abm_sim._concurrent_recovery_bundle import read_recovery_bundle
    from llm_abm_sim.concurrent_robustness_study import ConcurrentRobustnessStudy

    plan, approval, clients = _packet(tmp_path, monkeypatch, recovery_source)
    receipt = task.accept_recovery_task_recheck(plan, approval_path=approval, approval_sha256=formal._sha256_file(approval))

    class Transport(_Transport):
        def create_response(self, *args: Any, **kwargs: Any) -> Any:
            response = super().create_response(*args, **kwargs)
            if len(self.calls) == 2:
                return response.model_copy(update={"usage_status": "missing", "input_tokens": None,
                    "output_tokens": None, "total_tokens": None, "cached_input_tokens": None})
            return response

    new_clients = []

    def client(model: str, timeout: float) -> Any:
        value = Transport("deepseek", {})
        new_clients.append(value)
        return value

    monkeypatch.setattr(operator, "_new_client", client)
    monkeypatch.setattr(ConcurrentRobustnessStudy, "run", task_fixtures._STUDY_RUN)
    result = operator.run_concurrent_robustness_recovery_task(plan)
    assert result["status"] == "stopped"
    assert result["self_check_attempts"] == 2
    assert result["successful_judgments"] == 2
    assert result["physical_attempts"] == 4
    assert len(new_clients) == 1 and len(new_clients[0].calls) == 2
    bundle_path = result["execution_bundle"]
    assert isinstance(bundle_path, str)
    bundle = read_recovery_bundle(bundle_path)
    paths = {row["path"] for row in bundle["artifact_facts"]}
    assert str(approval) in paths and str(tmp_path / "probe-result.json") in paths
    assert bundle["progress"]["historical_all_attempts_total_tokens"] is None
    assert task.accept_recovery_task_recheck(plan, approval_path=approval, approval_sha256=formal._sha256_file(approval)) == receipt
    assert task.inspect_recovery_task(plan)["status"] == "stopped"
    assert operator.run_concurrent_robustness_recovery_task(plan)["status"] == "stopped"
    assert len(clients) == len(new_clients) == 1


def test_recheck_checks_probe_contract_and_durable_publication_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path,
) -> None:
    import copy
    import json

    from llm_abm_sim._concurrent_recovery_campaign import CampaignJournal, RecoveryCampaignError

    plan, approval, clients = _packet(tmp_path, monkeypatch, recovery_source)
    original = json.loads(approval.read_text())
    for index, change in enumerate(("wire", "usage", "identity", "decision", "future", "result_hash")):
        packet = copy.deepcopy(original)
        intent = json.loads(Path(original["probe_intent"]["path"]).read_text())
        result = json.loads(Path(original["probe_result"]["path"]).read_text())
        if change == "wire":
            intent["request_evidence"]["wire_output_token_ceiling"] = 999
        elif change == "usage":
            result["attempt"]["usage_complete_response_count"] = 0
        elif change == "identity":
            result["attempt"]["observed_model_counts"] = {"wrong-model": 1}
        elif change == "decision":
            result["decision"]["probability"] = 2
        elif change == "future":
            packet["approved_at_utc"] = "2099-01-01T00:00:00Z"
        intent_path = tmp_path / f"bad-intent-{index}.json"
        _write(intent_path, intent)
        packet["probe_intent"] = _ref(intent_path)
        result["intent_sha256"] = "f" * 64 if change == "result_hash" else _ref(intent_path)["sha256"]
        result_path = tmp_path / f"bad-result-{index}.json"
        _write(result_path, result)
        packet["probe_result"] = _ref(result_path)
        packet_path = tmp_path / f"bad-approval-{index}.json"
        _write(packet_path, packet)
        with pytest.raises(ValueError):
            task.accept_recovery_task_recheck(plan, approval_path=packet_path, approval_sha256=formal._sha256_file(packet_path))
    append = CampaignJournal.append

    def crash(self: CampaignJournal, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        row = append(self, kind, payload)
        if kind == "self_check_recheck_accepted":
            raise OSError("offline interruption after committed receipt")
        return row

    monkeypatch.setattr(CampaignJournal, "append", crash)
    with pytest.raises(OSError):
        task.accept_recovery_task_recheck(plan, approval_path=approval, approval_sha256=formal._sha256_file(approval))
    receipt = task.accept_recovery_task_recheck(plan, approval_path=approval, approval_sha256=formal._sha256_file(approval))
    assert receipt["provider_calls"] == 0
    context = task._context(plan)
    assert context.state.status == "ready" and len(context.journal.records) == 4
    assert len(clients) == len(clients[0].calls) == 1
    # Same evidence with a second approval path is not another admission.
    other = tmp_path / "second-approval.json"
    _write(other, original)
    with pytest.raises(RecoveryCampaignError, match="different recheck"):
        task.accept_recovery_task_recheck(plan, approval_path=other, approval_sha256=formal._sha256_file(other))
    Path(original["probe_result"]["path"]).chmod(0o600)
    with pytest.raises(RecoveryCampaignError, match="immutable"):
        task.inspect_recovery_task(plan)
