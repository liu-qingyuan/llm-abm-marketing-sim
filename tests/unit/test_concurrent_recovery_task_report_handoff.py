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
    monkeypatch.setattr(operator, "_publish_task_report", lambda *_args: operator._TaskReportHandoff(report, False))
    def denied(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("Report-only composition must not access Provider resources")
    monkeypatch.setattr(operator, "_new_client", denied)
    monkeypatch.setattr(operator, "_runtime_credential", denied)
    monkeypatch.delenv("LLM_ABM_RUN_LIVE_LLM", raising=False)
    result = operator.run_concurrent_robustness_recovery_task(tmp_path / "task-plan.json")
    assert result["report_status"] == "complete"
    assert result["formal_evidence_closed"] is False
    assert result["production_deploy_eligible"] is False


@pytest.mark.parametrize("fault", ["crossed_bundle", "unclosed_evidence"])
def test_production_handoff_requires_matching_independently_closed_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    from llm_abm_sim import concurrent_robustness_recovery_report as report
    from llm_abm_sim.concurrent_robustness_formal_execution import _sha256_file

    bundle = tmp_path / "bundle.json"
    bundle.write_text("{}")
    destination = tmp_path / "report"
    destination.mkdir()
    target = destination / "report.html"
    target.write_text("Report Interface unit fixture")
    facts: dict[str, Any] = {"source_bundle": {"path": str(bundle), "sha256": _sha256_file(bundle)},
                             "formal_evidence_closed": True, "report_status": "complete"}
    if fault == "crossed_bundle":
        facts["source_bundle"]["path"] = str(tmp_path / "another-bundle.json")
    else:
        facts["formal_evidence_closed"] = False
    monkeypatch.setattr(report, "export_concurrent_robustness_recovery_report", lambda *_a, **_kw: target)
    monkeypatch.setattr(report, "inspect_concurrent_robustness_recovery_report", lambda *_a: facts)
    monkeypatch.delenv("LLM_ABM_RUN_LIVE_LLM", raising=False)
    with pytest.raises(operator.ConcurrentRobustnessOperatorError, match="closure differs"):
        operator._publish_task_report(bundle, destination)


def test_task_status_independently_recognizes_report_closure_without_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from llm_abm_sim import concurrent_robustness_recovery_report as report
    from llm_abm_sim.concurrent_robustness_formal_execution import _sha256_file

    bundle = tmp_path / "bundle.json"
    bundle.write_text("{}")
    destination = tmp_path / "report"
    destination.mkdir()
    (destination / "report.html").write_text("Read-only Report Interface fixture")
    context = SimpleNamespace(plan={"request": {"report_destination": str(destination)}})
    monkeypatch.setattr(task, "_context", lambda _path: context)
    monkeypatch.setattr(task, "_task_status", lambda _context: {
        "status": "execution_complete", "report_status": "report_pending",
        "execution_bundle": str(bundle), "formal_evidence_closed": False,
    })
    monkeypatch.setattr(report, "inspect_concurrent_robustness_recovery_report", lambda _path: {
        "source_bundle": {"path": str(bundle), "sha256": _sha256_file(bundle)},
        "formal_evidence_closed": True, "report_status": "complete",
    })
    result = task.inspect_recovery_task(tmp_path / "plan.json")
    assert result["status"] == result["report_status"] == "complete"
    assert result["formal_evidence_closed"] is True
    assert result["provider_calls"] == result["credential_reads"] == 0
