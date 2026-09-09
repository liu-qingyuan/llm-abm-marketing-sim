"""Offline recovery contract drafts; synthetic inputs, no execution authority."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from llm_abm_sim import concurrent_robustness_formal_execution as formal
from llm_abm_sim import concurrent_robustness_recovery_epoch as initial
from llm_abm_sim import concurrent_robustness_recovery_execution as execution
from tests.integration import test_concurrent_robustness_recovery as source_fixtures
from tests.integration.test_concurrent_robustness_recovery_epoch import _approval, _request, _write

recovery_source = source_fixtures.recovery_source


def _execution_plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path) -> Path:
    initial_request, _ = _request(tmp_path, monkeypatch, recovery_source)
    approval_path, approval_sha = _approval(initial_request, tmp_path / "epoch-1/authorization.json")
    handoff_path = tmp_path / "epoch-1/initial-plan.json"
    handoff = initial.authorize_recovery_initial_epoch(
        request=initial_request, authorization_path=approval_path, authorization_sha256=approval_sha,
        plan_output=handoff_path,
    )
    request = execution.RecoveryExecutionRequest(
        initial_handoff=formal.FormalArtifactReference(path=handoff_path, sha256=formal._sha256_file(handoff_path)),
        qualification_artifacts=initial_request.qualification_artifacts,
        expected_head_sha256=handoff["authorization"]["request_identity"]["campaign"]["campaign_identity_sha256"],
    )
    ready = execution.prepare_recovery_execution(request)
    assert ready["request_identity"]["maximum_remaining_physical_attempts"] == 107996
    assert ready["request_identity"]["requested_model"] == "deepseek-v4-flash"
    assert ready["execution_authority"] is False
    authorization = copy.deepcopy(ready["authorization_template"])
    authorization.update(authorization_reference="fixture:explicit-recovery-execution-only",
                         approved_at_utc=handoff["authorization"]["approved_at_utc"],
                         expires_at_utc=handoff["authorization"]["expires_at_utc"])
    approved = tmp_path / "epoch-1/execution-authorization.json"
    approved_sha = _write(approved, authorization)
    plan_path = tmp_path / "epoch-1/execution-plan.json"
    plan = execution.authorize_recovery_execution(
        request=request, authorization_path=approved, authorization_sha256=approved_sha, plan_output=plan_path,
    )
    assert plan == execution.read_recovery_execution_plan(plan_path)
    assert plan["schema_version"] != initial.INITIAL_EPOCH_PLAN_SCHEMA
    for name in ("control_root", "source_anchor_path"):
        assert not Path(ready["request_identity"]["campaign"][name]).exists()
    with pytest.raises(ValueError):
        execution.read_recovery_execution_plan(handoff_path)
    return plan_path


def test_recovery_execution_plan_requires_its_own_exact_approval_and_creates_no_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path,
) -> None:
    _execution_plan(tmp_path, monkeypatch, recovery_source)


def test_private_recovery_resolver_rebuilds_old_success_and_stops_on_new_usage_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path,
) -> None:
    """Private core exercise, NOT a production entry or authorized Formal run."""
    from llm_abm_sim import concurrent_robustness_v2 as v2
    from llm_abm_sim._concurrent_recovery_campaign import CampaignJournal, recovery_scope
    from llm_abm_sim._concurrent_recovery_progress import CampaignProgress
    from llm_abm_sim._concurrent_recovery_runtime import inherited_terminals, run_recovery_model
    from llm_abm_sim.providers.robustness import DeepSeekV4FlashDecisionAdapter
    from tests.unit.test_concurrent_robustness_operator import _Transport

    request, _ = _request(tmp_path, monkeypatch, recovery_source)
    readiness, proposal = initial._initial_readiness(request, now=formal._utc_now())
    _, source = initial._inherited_context(request.proposal)
    manifest = source.manifest
    closure = v2._close_source(manifest.source.source_dir)
    config = v2._dynamic_runtime_config(closure)
    prepared = v2._prepare_concurrent_runtime_inputs(config)
    inherited = inherited_terminals(proposal, manifest)

    class Transport(_Transport):
        def create_response(self, *args: Any, **kwargs: Any) -> Any:
            response = super().create_response(*args, **kwargs)
            if len(self.calls) > 1:
                return response.model_copy(update={"usage_status": "missing", "input_tokens": None,
                    "output_tokens": None, "total_tokens": None, "cached_input_tokens": None})
            return response

    transport = Transport("deepseek", {})
    adapters = {cell.cell_id: DeepSeekV4FlashDecisionAdapter(prompt_version=cell.prompt_version, client=transport)
                for cell in manifest.prompt_model_cells if cell.requested_model == "deepseek-v4-flash"}
    campaign = readiness["request_identity"]["campaign"]
    before = source_fixtures._inventory(source.request.output_root, v2._operational_root(source.request.output_root), recovery_source)
    with recovery_scope(campaign):
        journal = CampaignJournal.open(campaign)
        state = CampaignProgress(proposal)
        state.append(journal, "epoch_admitted", {"ordinal": 1, "requested_model": "deepseek-v4-flash",
            "epoch_identity_sha256": "e" * 64, "plan_path": "/synthetic-only/no-execution-authority.json", "plan_sha256": "f" * 64})
        with pytest.raises(v2._V2CellStopped):
            run_recovery_model(config=config, prepared=prepared, manifest=manifest, state=state, journal=journal,
                adapters_by_cell=adapters, inherited=inherited, check_dispatch_window=lambda: None)
        replayed = CampaignProgress.replay(proposal, CampaignJournal.read(campaign))
        assert state.status == replayed.status == "stopped"
        assert state.physical_attempts == replayed.physical_attempts == len(transport.calls) == 2
        assert state.new_valid_judgments == replayed.new_valid_judgments == 1
        assert [row.attempt_number for row in state.attempts(state.failed_key)] == [1, 2]
        assert replayed.prefix[0] == 2 and replayed.inflight is None
        assert len(inherited) == 1 and len(state.judgments) == 1
    after = source_fixtures._inventory(source.request.output_root, v2._operational_root(source.request.output_root), recovery_source)
    assert before == after
