"""Production recovery Interface exercised with explicitly synthetic transports."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from llm_abm_sim import concurrent_robustness_formal_execution as formal
from llm_abm_sim import concurrent_robustness_operator as operator
from llm_abm_sim import concurrent_robustness_recovery_execution as execution
from llm_abm_sim.concurrent_robustness_study import ConcurrentRobustnessStudy
from tests.integration import test_concurrent_robustness_recovery as source_fixtures
from tests.integration.test_concurrent_robustness_recovery_epoch import _write
from tests.integration.test_concurrent_robustness_recovery_execution import _execution_plan
from tests.unit.test_concurrent_robustness_operator import _Transport

recovery_source = source_fixtures.recovery_source
_STUDY_RUN = ConcurrentRobustnessStudy.run


def test_operator_recovery_stops_and_publishes_independently_readable_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path,
) -> None:
    plan = _execution_plan(tmp_path, monkeypatch, recovery_source)
    clients: list[_Transport] = []

    class Transport(_Transport):
        def create_response(self, *args: Any, **kwargs: Any) -> Any:
            response = super().create_response(*args, **kwargs)
            if len(self.calls) > 1:
                return response.model_copy(update={"usage_status": "missing", "input_tokens": None,
                    "output_tokens": None, "total_tokens": None, "cached_input_tokens": None})
            return response

    def client(model: str, timeout: float) -> Any:
        value = Transport("deepseek" if model == "deepseek-v4-flash" else "gemini" if model.startswith("gemini") else "kimi" if model.startswith("kimi") else "openai", {})
        clients.append(value)
        return value

    monkeypatch.setattr(ConcurrentRobustnessStudy, "run", _STUDY_RUN)
    monkeypatch.setattr(operator, "_new_client", client)
    monkeypatch.setenv("LLM_ABM_RUN_LIVE_LLM", "1")
    result = operator.run_concurrent_robustness_recovery(plan)
    assert result.status == "stopped"
    assert result.logical_provider_attempts == 3
    assert result.successful_judgments == 2
    assert result.physical_provider_attempts == 4
    assert sum(len(c.calls) for c in clients) == 2
    assert all(c.closed == 1 for c in clients)
    assert result.execution_bundle is not None
    checked = execution.inspect_recovery_execution_bundle(result.execution_bundle)
    assert checked["successful_judgments"] == 2
    assert checked["physical_attempts"] == 4
    assert checked["historical_all_attempts_total_tokens"] is None
    assert checked["formal_evidence_closed"] is False
    assert checked["status"] == "stopped"
    again = operator.run_concurrent_robustness_recovery(plan)
    assert again.status == "stopped" and len(clients) == 5


@pytest.mark.parametrize("crash_kind", ["attempt_intent", "attempt_settled", "judgment_persisted", "realized_persisted", "pair_settled"])
def test_durable_stage_not_memory_controls_recovery_after_publication_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path, crash_kind: str,
) -> None:
    from llm_abm_sim._concurrent_recovery_campaign import CampaignJournal

    plan = _execution_plan(tmp_path, monkeypatch, recovery_source)
    clients: list[_Transport] = []
    fail_provider = False

    class Transport(_Transport):
        def create_response(self, *args: Any, **kwargs: Any) -> Any:
            response = super().create_response(*args, **kwargs)
            if fail_provider:
                return response.model_copy(update={"usage_status": "missing", "input_tokens": None,
                    "output_tokens": None, "total_tokens": None, "cached_input_tokens": None})
            return response

    def client(model: str, timeout: float) -> Any:
        value = Transport("deepseek" if model == "deepseek-v4-flash" else "gemini" if model.startswith("gemini") else "kimi" if model.startswith("kimi") else "openai", {})
        clients.append(value)
        return value

    append = CampaignJournal.append
    crashed = False

    def crash_after_durable_append(self: CampaignJournal, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal crashed
        row = append(self, kind, payload)
        if kind == crash_kind and not crashed:
            crashed = True
            raise OSError("synthetic crash after durable publication")
        return row

    monkeypatch.setattr(CampaignJournal, "append", crash_after_durable_append)
    monkeypatch.setattr(ConcurrentRobustnessStudy, "run", _STUDY_RUN)
    monkeypatch.setattr(operator, "_new_client", client)
    monkeypatch.setenv("LLM_ABM_RUN_LIVE_LLM", "1")
    first = operator.run_concurrent_robustness_recovery(plan)
    assert crashed and first.physical_provider_attempts == 3
    old_bundle = first.execution_bundle
    assert old_bundle is not None
    original = execution.inspect_recovery_execution_bundle(old_bundle)
    if crash_kind == "attempt_intent":
        assert first.status == "reconciliation_required"
        assert sum(len(c.calls) for c in clients) == 0
        assert operator.run_concurrent_robustness_recovery(plan).status == "reconciliation_required"
        assert len(clients) == 5
    else:
        assert first.recovery_status == "paused"
        assert sum(len(c.calls) for c in clients) == 1
        fail_provider = True
        resumed = operator.run_concurrent_robustness_recovery(plan)
        assert resumed.status == "stopped" and resumed.successful_judgments == 2
        assert resumed.physical_provider_attempts == 4
        assert sum(len(c.calls) for c in clients) == 2
        assert len(clients) == 10 and all(c.closed == 1 for c in clients)
        # A later HEAD must not invalidate or rewrite an immutable earlier prefix.
        assert execution.inspect_recovery_execution_bundle(old_bundle) == original


def _next_plan(first: Path, head: str, output: Path) -> Path:
    from datetime import timedelta

    document = execution.read_recovery_execution_plan(first)
    request = execution.RecoveryExecutionRequest.model_validate(document["request"]).model_copy(update={"expected_head_sha256": head})
    ready = execution.prepare_recovery_execution(request)
    now = formal._utc_now()
    approval = dict(ready["authorization_template"])
    approval.update(authorization_reference="fixture:explicit-next-recovery-epoch",
        approved_at_utc=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        expires_at_utc=(now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    output.mkdir()
    authorization = output / "authorization.json"
    digest = _write(authorization, approval)
    target = output / "plan.json"
    execution.authorize_recovery_execution(request=request, authorization_path=authorization,
        authorization_sha256=digest, plan_output=target)
    return target


@pytest.mark.formal_shape_rehearsal
def test_recovery_manual_full_shape_closes_36000_without_reissuing_successes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path,
) -> None:
    """Synthetic transports, never Formal evidence. Fsync speedup is manual only."""
    import os

    monkeypatch.setattr(os, "fsync", lambda *_args: None)
    first = _execution_plan(tmp_path, monkeypatch, recovery_source)
    clients: list[_Transport] = []

    def client(model: str, timeout: float) -> Any:
        value = _Transport("deepseek" if model == "deepseek-v4-flash" else "gemini" if model.startswith("gemini") else "kimi" if model.startswith("kimi") else "openai", {})
        clients.append(value)
        return value

    monkeypatch.setattr(ConcurrentRobustnessStudy, "run", _STUDY_RUN)
    monkeypatch.setattr(operator, "_new_client", client)
    monkeypatch.setenv("LLM_ABM_RUN_LIVE_LLM", "1")
    current = first
    result = None
    for model_number in range(5):
        before = sum(len(c.calls) for c in clients)
        result = operator.run_concurrent_robustness_recovery(current)
        assert result.successful_judgments == (model_number + 1) * 7200
        assert result.physical_provider_attempts == result.successful_judgments + 1
        assert result.logical_provider_attempts == result.successful_judgments
        assert result.recovery_status == ("complete" if model_number == 4 else "checkpoint")
        assert sum(len(c.calls) for c in clients) - before == (7199 if model_number == 0 else 7200)
        assert all(c.closed == 1 for c in clients)
        if model_number < 4:
            current = _next_plan(first, result.campaign_head_sha256, tmp_path / f"epoch-{model_number + 2}")
    assert result is not None and result.execution_bundle is not None
    checked = execution.inspect_recovery_execution_bundle(result.execution_bundle)
    assert checked["successful_judgments"] == 36000
    assert checked["physical_attempts"] == 36001
    assert checked["cell_prefixes"] == [1800] * 20
    assert checked["formal_evidence_closed"] is False
    assert sum(len(c.calls) for c in clients) == 35999
