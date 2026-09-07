from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from llm_abm_sim import concurrent_robustness_formal_execution as formal_module
from llm_abm_sim import concurrent_robustness_operator as operator_module
from llm_abm_sim import concurrent_robustness_v2 as v2_module
from llm_abm_sim.concurrent_robustness_study import ConcurrentRobustnessStudyStatus
from llm_abm_sim.decision import ProviderResponseProvenanceUnknown
from llm_abm_sim.providers.robustness import ProviderAttemptFailure
from tests.integration.test_concurrent_message_experiment_runner import _make_validation_report_source
from tests.integration.test_concurrent_robustness_v2 import _v2_manifest
from tests.unit.test_concurrent_robustness_operator import _clients


@pytest.mark.parametrize(("outcome", "corruption"), [
    ("complete", None), ("quota_exhausted", None), ("unknown", None), ("usage_evidence", None),
    *(("usage_evidence", kind) for kind in (
        "checksum", "model", "usage", "diagnostic", "panel_leads", "missing_identity",
    )),
])
def test_operator_real_study_checkpoints_and_terminal_reentry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: str, corruption: str | None,
) -> None:
    """Real scheduling/persistence with synthetic transports, NOT Formal evidence.

    A small validation source substitutes for production size and the authorization
    boundary. Real gate/credential ordering is tested separately in the unit suite;
    the manual 36,000-case rehearsal checks the full zero-Provider shape.
    """
    source = _make_validation_report_source(tmp_path, f"operator-{outcome}-source")
    validation = _v2_manifest(source, output_identity=f"operator-{outcome}")
    manifest = validation.model_copy(update={
        "source": validation.source.model_copy(update={"kind": "formal"}),
        "execution_profile": "formal",
    })
    workspace = tmp_path / "operator-workspace"
    plan_path = tmp_path / "synthetic-plan.json"
    plan = {"plan_identity_sha256": "a" * 64, "authorization_sha256": "b" * 64, "request": {}}
    request = SimpleNamespace(output_root=workspace, run_parameters=SimpleNamespace(request_timeout_seconds=30.0))
    monkeypatch.setenv("LLM_ABM_RUN_LIVE_LLM", "1")
    monkeypatch.setattr(operator_module, "validate_formal_execution_plan", lambda *_a, **_k: plan)
    monkeypatch.setattr(operator_module, "_request_from_plan", lambda *_a: request)
    monkeypatch.setattr(operator_module, "_manifest_from_request", lambda *_a: (manifest, {}))
    monkeypatch.setattr(operator_module, "inspect_formal_execution_plan", lambda *_a: SimpleNamespace(
        plan=plan, request=request, manifest=manifest, current_gate={"currently_valid": False},
    ))
    monkeypatch.setattr(formal_module, "validate_formal_execution_plan", lambda *_a, **_k: plan)
    monkeypatch.setattr(formal_module, "validate_embedded_formal_execution_plan", lambda embedded, **_k: dict(embedded))
    monkeypatch.setattr(v2_module, "_validate_source_against_manifest", lambda *_a: None)

    def close_validation(*, output_path: Path, manifest_sha256: str, published: Any) -> Any:
        return v2_module._result(
            status=ConcurrentRobustnessStudyStatus.COMPLETE, output_path=output_path,
            manifest_sha256=manifest_sha256, logical=published.logical_judgments,
            physical=published.physical_attempts, study_root=output_path,
        )

    monkeypatch.setattr(v2_module, "_close_v2_study_result", close_validation)
    expected = manifest.request_caps.logical_judgments_per_cell * 4
    result = None
    for index in range(5 if outcome == "complete" else 1):
        clients = _clients(monkeypatch)
        if outcome != "complete":
            original_factory = operator_module._OpenAISDKClient

            def failing_factory(_factory: Any = original_factory, **settings: Any) -> Any:
                client = _factory(**settings)
                original_call = client.create_response

                def respond(*args: Any, **kwargs: Any) -> Any:
                    response = original_call(*args, **kwargs)
                    if len(client.calls) == 2:
                        if outcome == "quota_exhausted":
                            raise ProviderAttemptFailure(category="quota_exhausted", retryable=False, status_code=429)
                        if outcome == "usage_evidence":
                            client.last_safe_usage_diagnostics = {
                                "usage_status": "missing", "normalized_usage_status": "missing",
                                "input_tokens": None, "output_tokens": None, "total_tokens": None,
                                "cached_input_tokens": None, "reasoning_tokens": None,
                                "normalized_output_tokens": None, "total_delta": None,
                                "failure_invariant": "usage_absent",
                            }
                            return response.model_copy(update={
                                "usage_status": "missing", "input_tokens": None, "output_tokens": None,
                                "total_tokens": None, "cached_input_tokens": None,
                            })
                        raise ProviderResponseProvenanceUnknown("synthetic unknown post-dispatch")
                    return response

                monkeypatch.setattr(client, "create_response", respond)
                return client

            monkeypatch.setattr(operator_module, "_OpenAISDKClient", failing_factory)
        result = operator_module.run_concurrent_robustness_formal(plan_path)
        assert len(clients) == 5 and all(c.closed == 1 for c in clients)
        assert all(not c.calls for other, c in enumerate(clients) if other != index)
        if outcome == "complete":
            assert len(clients[index].calls) == expected
            assert result.logical_provider_attempts == expected * (index + 1)
            assert result.status == ("complete" if index == 4 else "resumable")
            assert (workspace / "two_stage_execution").exists() == (index == 4)
        else:
            assert len(clients[0].calls) == 2
            assert result.status == ("reconciliation_required" if outcome == "unknown" else "stopped")

    assert result is not None
    # An explicit reentry may read/repair persisted status, never resend or set up
    # a credential-bearing client after a terminal state or complete publication.
    clients = _clients(monkeypatch)
    repeated = operator_module.run_concurrent_robustness_formal(plan_path)
    assert repeated.status == result.status
    assert repeated.logical_provider_attempts == result.logical_provider_attempts
    assert repeated.physical_provider_attempts == result.physical_provider_attempts
    assert clients == []
    if outcome == "complete":
        execution = json.loads((workspace / "two_stage_execution" / "execution_manifest.json").read_text())
        assert execution["counts"]["cells"] == 20
        assert execution["counts"]["logical_judgments"] == expected * 5

    operational = v2_module._operational_root(workspace)

    def persisted_bytes() -> dict[Path, bytes]:
        return {p: p.read_bytes() for root in (workspace, operational) for p in root.rglob("*") if p.is_file()}

    before = persisted_bytes()
    monkeypatch.delenv("LLM_ABM_RUN_LIVE_LLM", raising=False)
    inspected: Any = operator_module.inspect_concurrent_robustness_formal(plan_path)
    assert persisted_bytes() == before
    assert clients == []
    assert inspected["inspection_only"] and inspected["automatic_resume_allowed"] is False
    assert inspected["provider_calls_during_inspection"] == inspected["credential_reads_during_inspection"] == 0
    if outcome == "complete":
        assert inspected["successful_judgments"] == expected * 5
        assert inspected["completed_cells"] == 20
        assert all(row["status"] == "complete" for row in inspected["models"])
    else:
        assert inspected["successful_judgments"] == 1
        assert inspected["attempted_logical_judgments"] == inspected["physical_attempts"] == 2
        assert inspected["failed_logical_judgments"] == (0 if outcome == "unknown" else 1)
        assert inspected["status"] == result.status
        assert all(row["status"] == "not_started" for row in inspected["models"][1:])
        if outcome == "usage_evidence":
            failure = inspected["failures"][0]
            assert failure["category"] == "usage_evidence"
            assert failure["remaining_attempt_budget"] == 2 and failure["recovery_authorized"] is False
            assert failure["usage_diagnostics"]["failure_invariant"] == "usage_absent"

    if corruption is None:
        return
    scope = operational / "cell-00"
    if corruption == "panel_leads":
        panel = operational / v2_module._V2_OPERATIONAL_STATUS
        value = json.loads(panel.read_text())
        value["logical_judgments"] += 1
        panel.write_bytes(v2_module._canonical_json_bytes(value))
    elif corruption == "missing_identity":
        (scope / v2_module._V2_LEDGER_IDENTITY).unlink()
    else:
        journal = scope / v2_module._V2_LEDGER_JSONL
        records = [json.loads(line) for line in journal.read_text().splitlines()]
        judgment = next(row["payload"]["judgment"] for row in records if row["state"] == "judgment_persisted")
        if corruption == "model":
            judgment["observed_model"] = "wrong-model"
        elif corruption == "usage":
            judgment["attempt_evidence"][0]["total_usage"] += 1
        elif corruption == "diagnostic":
            stopped = next(row for row in records if row["state"] == "stopped")
            stopped["payload"]["attempt_evidence"][0]["usage_diagnostics"]["failure_invariant"] = "RAW_SENTINEL"
        if corruption == "checksum":
            records[-1]["checksum"] = "f" * 64
        else:
            for index, row in enumerate(records):
                if index:
                    row["previous_checksum"] = records[index - 1]["checksum"]
                row["checksum"] = v2_module._json_sha256({k: v for k, v in row.items() if k != "checksum"})
        journal.write_bytes(b"".join(v2_module._canonical_json_bytes(row) for row in records))
    damaged = persisted_bytes()
    with pytest.raises(ValueError):
        operator_module.inspect_concurrent_robustness_formal(plan_path)
    assert persisted_bytes() == damaged and clients == []
