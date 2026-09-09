"""Task entry contracts use synthetic transports, never real Formal evidence."""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from llm_abm_sim import concurrent_robustness_formal_execution as formal
from llm_abm_sim import concurrent_robustness_operator as operator
from llm_abm_sim.concurrent_robustness_recovery import prepare_concurrent_robustness_recovery
from llm_abm_sim.concurrent_robustness_study import ConcurrentRobustnessStudy
from tests.integration import test_concurrent_robustness_recovery as fixtures
from tests.integration.test_concurrent_robustness_recovery_epoch import _write

recovery_source = fixtures.recovery_source
_STUDY_RUN = ConcurrentRobustnessStudy.run


def _task_plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: Path,
               *, deadline: timedelta | None = None) -> Path:
    from llm_abm_sim import concurrent_robustness_recovery_task as task

    original, _ = fixtures._stopped_plan(tmp_path, monkeypatch, source)
    output = tmp_path / "recovery"
    prepare_concurrent_robustness_recovery(original, output_dir=output)
    proposal = output / "recovery-proposal.json"
    request = task.RecoveryTaskRequest(
        proposal=formal.FormalArtifactReference(path=proposal, sha256=formal._sha256_file(proposal)),
        report_destination=tmp_path / "report",
        deadline_utc=None if deadline is None else (formal._utc_now() + deadline).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    approval = task.prepare_recovery_task(request)["authorization_template"]
    approval.update(authorization_reference="fixture:single-task-approval",
                    approved_at_utc=formal._utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"))
    path = tmp_path / "task-approval.json"
    digest = _write(path, approval)
    plan = tmp_path / "task-plan.json"
    task.authorize_recovery_task(request=request, authorization_path=path,
                                authorization_sha256=digest, plan_output=plan)
    return plan


def test_one_task_approval_outlives_legacy_qualification_windows_without_claiming_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path,
) -> None:
    from llm_abm_sim import concurrent_robustness_recovery_task as task

    original, _ = fixtures._stopped_plan(tmp_path, monkeypatch, recovery_source)
    output = tmp_path / "recovery"
    prepare_concurrent_robustness_recovery(original, output_dir=output)
    proposal = output / "recovery-proposal.json"
    request = task.RecoveryTaskRequest(
        proposal=formal.FormalArtifactReference(path=proposal, sha256=formal._sha256_file(proposal)),
        report_destination=tmp_path / "report",
    )
    before = fixtures._inventory(tmp_path, recovery_source)
    ready = task.prepare_recovery_task(request)
    assert fixtures._inventory(tmp_path, recovery_source) == before
    assert ready["provider_calls"] == ready["credential_reads"] == 0
    # This fixture stops in DeepSeek, so five (not the real source's four) remain.
    assert ready["request_identity"]["self_check_cap"] == 5
    assert ready["request_identity"]["maximum_new_physical_attempts"] == 107996
    approval = dict(ready["authorization_template"])
    approval.update(authorization_reference="fixture:single-task-approval",
                    approved_at_utc=formal._utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"))
    authorization = tmp_path / "task-approval.json"
    digest = _write(authorization, approval)
    plan = tmp_path / "task-plan.json"
    task.authorize_recovery_task(request=request, authorization_path=authorization,
                                authorization_sha256=digest, plan_output=plan)
    now = formal._utc_now()
    monkeypatch.setattr(formal, "_utc_now", lambda: now + timedelta(days=3))
    status = task.inspect_recovery_task(plan)
    assert status["authorization_current"] is True
    assert status["status"] == "ready"
    assert status["self_check_attempts"] == 0
    assert status["successful_judgments"] == 1
    assert status["physical_attempts"] == 2
    assert status["provider_calls"] == status["credential_reads"] == 0
    campaign = ready["request_identity"]["campaign"]
    assert not Path(campaign["source_anchor_path"]).exists()
    assert not Path(campaign["control_root"]).exists()


def test_failed_self_check_stops_without_formal_dispatch_and_cannot_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path,
) -> None:
    from llm_abm_sim import concurrent_robustness_recovery_task as task
    from tests.unit.test_concurrent_robustness_operator import _Transport

    plan = _task_plan(tmp_path, monkeypatch, recovery_source)
    clients: list[_Transport] = []

    class Transport(_Transport):
        def create_response(self, *args: Any, **kwargs: Any) -> Any:
            response = super().create_response(*args, **kwargs)
            return response.model_copy(update={"usage_status": "missing", "input_tokens": None,
                "output_tokens": None, "total_tokens": None, "cached_input_tokens": None})

    def client(model: str, timeout: float) -> Any:
        assert model == "deepseek-v4-flash"
        value = Transport("deepseek", {})
        clients.append(value)
        return value

    monkeypatch.setattr(operator, "_new_client", client)
    monkeypatch.setenv("LLM_ABM_RUN_LIVE_LLM", "1")
    result = operator.run_concurrent_robustness_recovery_task(plan)
    assert result["status"] == "stopped"
    assert result["self_check_attempts"] == 1
    assert result["self_check_failures"] == {"deepseek-v4-flash": "usage_evidence"}
    assert result["physical_attempts"] == 2
    assert result["successful_judgments"] == 1
    assert len(clients) == len(clients[0].calls) == clients[0].closed == 1
    assert task.inspect_recovery_task(plan)["status"] == "stopped"
    assert operator.run_concurrent_robustness_recovery_task(plan)["status"] == "stopped"
    assert len(clients) == 1


def test_task_self_check_and_formal_attempts_have_separate_durable_origins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path,
) -> None:
    from llm_abm_sim._concurrent_recovery_bundle import read_recovery_bundle
    from tests.unit.test_concurrent_robustness_operator import _Transport

    plan = _task_plan(tmp_path, monkeypatch, recovery_source)
    clients: list[_Transport] = []

    class Transport(_Transport):
        def create_response(self, *args: Any, **kwargs: Any) -> Any:
            response = super().create_response(*args, **kwargs)
            if len(self.calls) == 3:
                return response.model_copy(update={"usage_status": "missing", "input_tokens": None,
                    "output_tokens": None, "total_tokens": None, "cached_input_tokens": None})
            return response

    def client(model: str, timeout: float) -> Any:
        value = Transport("deepseek", {})
        clients.append(value)
        return value

    monkeypatch.setattr(ConcurrentRobustnessStudy, "run", _STUDY_RUN)
    monkeypatch.setattr(operator, "_new_client", client)
    monkeypatch.setenv("LLM_ABM_RUN_LIVE_LLM", "1")
    result = operator.run_concurrent_robustness_recovery_task(plan)
    assert result["status"] == "stopped"
    assert result["self_check_attempts"] == 1
    assert result["physical_attempts"] == 4
    assert result["successful_judgments"] == 2
    assert len(clients) == clients[0].closed == 1
    assert len(clients[0].calls) == 3
    bundle_path = result["execution_bundle"]
    assert isinstance(bundle_path, str)
    bundle = read_recovery_bundle(bundle_path)
    assert bundle["schema_version"] == "concurrent-recovery-task-execution-bundle-v1"
    assert "initial_handoff" not in bundle
    assert bundle["progress"]["physical_attempts"] == 4
    assert bundle["progress"]["historical_all_attempts_total_tokens"] is None
    assert bundle["realization_verification"]["verified_terminal_count"] == 2
    assert operator.run_concurrent_robustness_recovery_task(plan)["status"] == "stopped"
    assert len(clients) == 1


def test_task_inspection_rejects_orphan_internal_plan_without_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path,
) -> None:
    from llm_abm_sim import concurrent_robustness_recovery_task as task
    from llm_abm_sim._concurrent_recovery_campaign import CampaignJournal, RecoveryCampaignError, recovery_scope

    plan = _task_plan(tmp_path, monkeypatch, recovery_source)
    context = task._context(plan)
    with recovery_scope(context.origins.campaign):
        journal = CampaignJournal.open(context.origins.campaign)
    _write(journal.root / "plans" / "orphan.json", {"foreign": True})
    before = fixtures._inventory(tmp_path, recovery_source)
    with pytest.raises(RecoveryCampaignError, match="plan inventory"):
        task.inspect_recovery_task(plan)
    assert fixtures._inventory(tmp_path, recovery_source) == before


def test_new_task_approval_requires_immutability_without_changing_legacy_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path,
) -> None:
    from llm_abm_sim import concurrent_robustness_recovery_task as task
    from llm_abm_sim._concurrent_recovery_campaign import RecoveryCampaignError

    plan = _task_plan(tmp_path, monkeypatch, recovery_source)
    context = task._context(plan)
    approval = Path(context.plan["authorization_artifact"]["path"])
    approval.chmod(0o600)
    with pytest.raises(RecoveryCampaignError, match="Task approval must be immutable"):
        task.inspect_recovery_task(plan)


@pytest.mark.parametrize("crash_kind", ["self_check_intent", "self_check_settled", "epoch_admitted",
                                       "attempt_intent", "attempt_settled", "pair_settled"])
def test_task_crash_reuses_durable_health_and_never_resends_unknown_or_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path, crash_kind: str,
) -> None:
    from llm_abm_sim._concurrent_recovery_bundle import read_recovery_bundle
    from llm_abm_sim._concurrent_recovery_campaign import CampaignJournal
    from tests.unit.test_concurrent_robustness_operator import _Transport

    plan = _task_plan(tmp_path, monkeypatch, recovery_source)
    clients: list[_Transport] = []
    fail_formal = False

    class Transport(_Transport):
        def create_response(self, *args: Any, **kwargs: Any) -> Any:
            response = super().create_response(*args, **kwargs)
            if fail_formal:
                return response.model_copy(update={"usage_status": "missing", "input_tokens": None,
                    "output_tokens": None, "total_tokens": None, "cached_input_tokens": None})
            return response

    def client(model: str, timeout: float) -> Any:
        value = Transport("deepseek", {})
        clients.append(value)
        return value

    append = CampaignJournal.append
    crashed = False

    def crash(self: CampaignJournal, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal crashed
        record = append(self, kind, payload)
        if kind == crash_kind and not crashed:
            crashed = True
            raise OSError("synthetic crash after durable append")
        return record

    monkeypatch.setattr(CampaignJournal, "append", crash)
    monkeypatch.setattr(ConcurrentRobustnessStudy, "run", _STUDY_RUN)
    monkeypatch.setattr(operator, "_new_client", client)
    monkeypatch.setenv("LLM_ABM_RUN_LIVE_LLM", "1")
    first = operator.run_concurrent_robustness_recovery_task(plan)
    assert crashed
    assert first["self_check_attempts"] == 1
    bundle_path = first["execution_bundle"]
    assert isinstance(bundle_path, str)
    old_bundle = read_recovery_bundle(bundle_path)
    calls_before = sum(len(c.calls) for c in clients)
    fail_formal = True
    again = operator.run_concurrent_robustness_recovery_task(plan)
    assert again["self_check_attempts"] == 1
    if crash_kind in {"self_check_intent", "attempt_intent"}:
        assert first["status"] == again["status"] == "reconciliation_required"
        assert sum(len(c.calls) for c in clients) == calls_before
        assert len(clients) == 1
    else:
        assert first["status"] == "paused"
        assert again["status"] == "stopped"
        assert sum(len(c.calls) for c in clients) == calls_before + 1
        assert len(clients) == 2
        assert again["successful_judgments"] == (2 if crash_kind in {"attempt_settled", "pair_settled"} else 1)
    assert all(c.closed == 1 for c in clients)
    assert read_recovery_bundle(bundle_path) == old_bundle


def test_revocation_applies_to_copied_plans_even_before_source_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path,
) -> None:
    from llm_abm_sim import concurrent_robustness_recovery_task as task
    from llm_abm_sim._concurrent_recovery_campaign import recovery_scope

    plan = _task_plan(tmp_path, monkeypatch, recovery_source)
    context = task._context(plan)
    # Cancellation must work while the long-running task owns the source lock.
    with recovery_scope(context.origins.campaign):
        assert task.revoke_recovery_task(plan)["status"] == "revocation_requested"
    clone = tmp_path / "same-approval-other-plan.json"
    task.authorize_recovery_task(
        request=task.RecoveryTaskRequest.model_validate(context.plan["request"]),
        authorization_path=Path(context.plan["authorization_artifact"]["path"]),
        authorization_sha256=context.plan["authorization_artifact"]["sha256"], plan_output=clone,
    )
    assert task.inspect_recovery_task(plan)["status"] == "revoked"
    assert task.inspect_recovery_task(clone)["status"] == "revoked"
    assert operator.run_concurrent_robustness_recovery_task(clone)["status"] == "revoked"
    assert not Path(context.origins.campaign["source_anchor_path"]).exists()


def test_deadline_and_direct_study_lock_gates_precede_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path,
) -> None:
    from llm_abm_sim import concurrent_robustness_recovery_task as task
    from llm_abm_sim._concurrent_recovery_campaign import RecoveryCampaignError

    plan = _task_plan(tmp_path, monkeypatch, recovery_source, deadline=timedelta(hours=1))
    def denied(_model: str) -> Any:
        pytest.fail("A direct call without its source lock must not construct resources")
    with pytest.raises(RecoveryCampaignError, match="source-bound Operator lock"):
        ConcurrentRobustnessStudy().run_task(plan, model_resources=denied)
    with pytest.raises(operator.ConcurrentRobustnessOperatorError, match="explicit live gate"):
        operator.run_concurrent_robustness_recovery_task(plan)
    now = formal._utc_now()
    monkeypatch.setattr(formal, "_utc_now", lambda: now + timedelta(hours=1))
    status = task.inspect_recovery_task(plan)
    assert status["status"] == "authorization_not_current"
    assert operator.run_concurrent_robustness_recovery_task(plan)["status"] == "authorization_not_current"
    assert task.inspect_recovery_task(plan)["self_check_attempts"] == 0


@pytest.mark.parametrize("revoke_on_call", [1, 2])
def test_live_revocation_stops_before_next_dispatch_but_keeps_admitted_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path, revoke_on_call: int,
) -> None:
    from llm_abm_sim import concurrent_robustness_recovery_task as task
    from llm_abm_sim._concurrent_recovery_bundle import read_recovery_bundle
    from tests.unit.test_concurrent_robustness_operator import _Transport

    plan = _task_plan(tmp_path, monkeypatch, recovery_source)
    class Transport(_Transport):
        def create_response(self, *args: Any, **kwargs: Any) -> Any:
            response = super().create_response(*args, **kwargs)
            if len(self.calls) == revoke_on_call:
                task.revoke_recovery_task(plan)
            return response
    client = Transport("deepseek", {})
    monkeypatch.setattr(operator, "_new_client", lambda *_args: client)
    monkeypatch.setattr(ConcurrentRobustnessStudy, "run", _STUDY_RUN)
    monkeypatch.setenv("LLM_ABM_RUN_LIVE_LLM", "1")
    result = operator.run_concurrent_robustness_recovery_task(plan)
    assert result["status"] == "revoked"
    assert len(client.calls) == revoke_on_call
    assert result["self_check_attempts"] == 1
    assert result["physical_attempts"] == revoke_on_call + 1
    assert result["successful_judgments"] == revoke_on_call
    path = result["execution_bundle"]
    assert isinstance(path, str)
    assert read_recovery_bundle(path)["progress"]["successful_judgments"] == revoke_on_call


@pytest.mark.formal_shape_rehearsal
def test_one_task_command_closes_full_shape_across_days_then_retries_report_without_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path,
) -> None:
    """36k synthetic outcomes and an injected report, never real Formal evidence."""
    import os

    from llm_abm_sim import concurrent_robustness_recovery_task as task
    from llm_abm_sim._concurrent_recovery_bundle import read_recovery_bundle
    from tests.unit.test_concurrent_robustness_operator import _Transport

    # Only this opt-in full-shape rehearsal replaces fsync; crash tests do not.
    monkeypatch.setattr(os, "fsync", lambda *_args: None)
    plan = _task_plan(tmp_path, monkeypatch, recovery_source)
    clients: list[_Transport] = []
    models: list[str] = []
    def client(model: str, timeout: float) -> Any:
        now = formal._utc_now()
        monkeypatch.setattr(formal, "_utc_now", lambda: now + timedelta(days=2))
        value = _Transport("deepseek" if model == "deepseek-v4-flash" else "gemini" if model.startswith("gemini")
                           else "kimi" if model.startswith("kimi") else "openai", {})
        clients.append(value)
        models.append(model)
        return value
    def unavailable(_bundle: Path, _destination: Path) -> Path:
        raise RuntimeError("synthetic report outage")
    monkeypatch.setattr(operator, "_new_client", client)
    monkeypatch.setattr(ConcurrentRobustnessStudy, "run", _STUDY_RUN)
    monkeypatch.setattr(operator, "_publish_task_report", unavailable)
    monkeypatch.setenv("LLM_ABM_RUN_LIVE_LLM", "1")
    result = operator.run_concurrent_robustness_recovery_task(plan)
    assert result["status"] == "execution_complete" and result["report_status"] == "report_pending"
    assert result["successful_judgments"] == 36000
    assert result["physical_attempts"] == 36001
    assert result["self_check_attempts"] == 5
    assert sum(len(c.calls) for c in clients) == 36004  # 35,999 new Formal + five self-checks
    assert [len(c.calls) for c in clients] == [7200, 7201, 7201, 7201, 7201]
    assert len(set(models)) == len(clients) == 5 and all(c.closed == 1 for c in clients)
    context = task._context(plan)
    assert len(context.state.epochs) == len(context.state.invocations) == 5
    assert list(context.state.self_checks) == models
    path = result["execution_bundle"]
    assert isinstance(path, str)
    bundle = read_recovery_bundle(path)
    assert bundle["progress"]["cell_prefixes"] == [1800] * 20
    assert bundle["realization_verification"]["verified_batch_commit_count"] == 600
    def report(bundle_path: Path, destination: Path) -> operator._TaskReportHandoff:
        assert read_recovery_bundle(bundle_path)["progress"]["successful_judgments"] == 36000
        destination.mkdir()
        target = destination / "report.html"
        target.write_text("Synthetic Report Interface test; not Formal Evidence.")
        return operator._TaskReportHandoff(target, False)
    def denied(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("Report-only continuation must not enter Provider/Study execution")
    monkeypatch.setattr(operator, "_publish_task_report", report)
    monkeypatch.setattr(operator, "_new_client", denied)
    monkeypatch.setattr(operator, "_runtime_credential", denied)
    monkeypatch.setattr(ConcurrentRobustnessStudy, "run", denied)
    monkeypatch.delenv("LLM_ABM_RUN_LIVE_LLM")
    final = operator.run_concurrent_robustness_recovery_task(plan)
    assert final["status"] == final["report_status"] == "complete"
    assert final["successful_judgments"] == 36000
    assert final["physical_attempts"] == 36001 and final["self_check_attempts"] == 5
    assert final["production_deploy_eligible"] is False
    assert final["formal_evidence_closed"] is False
