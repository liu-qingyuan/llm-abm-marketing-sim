"""Operator report composition does not itself confer Formal evidence status."""
from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from llm_abm_sim import _concurrent_recovery_campaign as campaign
from llm_abm_sim import concurrent_robustness_operator as operator
from llm_abm_sim import concurrent_robustness_recovery_task as task
from llm_abm_sim.concurrent_robustness_study import ConcurrentRobustnessStudy


def test_report_success_does_not_promote_an_execution_checkpoint_to_formal_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "report"
    destination.mkdir()
    report = destination / "report.html"
    report.write_text("Synthetic Report Interface; not Formal Evidence.")
    context = SimpleNamespace(plan={"request": {"report_destination": str(destination)}},
                              origins=SimpleNamespace(campaign={}))
    completed: dict[str, Any] = {"status": "execution_complete", "report_status": "report_pending",
                               "execution_bundle": str(tmp_path / "bundle.json"),
                               "formal_evidence_closed": False, "production_deploy_eligible": False}
    monkeypatch.setattr(task, "_context", lambda _path: context)
    monkeypatch.setattr(task, "_task_status", lambda _context: dict(completed))
    monkeypatch.setattr(campaign, "recovery_scope", lambda _identity: nullcontext())
    monkeypatch.setattr(ConcurrentRobustnessStudy, "run_task", lambda *_args, **_kwargs: dict(completed))
    monkeypatch.setattr(operator, "_publish_task_report", lambda *_args: report)
    def denied(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("Report-only composition must not access Provider resources")
    monkeypatch.setattr(operator, "_new_client", denied)
    monkeypatch.setattr(operator, "_runtime_credential", denied)
    monkeypatch.delenv("LLM_ABM_RUN_LIVE_LLM", raising=False)
    result = operator.run_concurrent_robustness_recovery_task(tmp_path / "task-plan.json")
    assert result["report_status"] == "complete"
    assert result["formal_evidence_closed"] is False
    assert result["production_deploy_eligible"] is False
