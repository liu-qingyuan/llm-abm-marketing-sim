"""Recovery gates precede resources and reject rehashed caller claims."""
from __future__ import annotations

import copy
import json
from datetime import timedelta
from pathlib import Path

import pytest

from llm_abm_sim import concurrent_robustness_formal_execution as formal
from llm_abm_sim import concurrent_robustness_operator as operator
from llm_abm_sim import concurrent_robustness_recovery_execution as execution
from llm_abm_sim import concurrent_robustness_v2 as v2
from scripts import run_concurrent_robustness_v2 as cli
from tests.integration import test_concurrent_robustness_recovery as fixtures
from tests.integration.test_concurrent_robustness_recovery_epoch import _write
from tests.integration.test_concurrent_robustness_recovery_execution import _execution_plan

recovery_source = fixtures.recovery_source


def test_expired_execution_is_historically_valid_but_cannot_create_scope_or_clients(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path,
) -> None:
    plan = _execution_plan(tmp_path, monkeypatch, recovery_source)
    now = formal._utc_now()
    monkeypatch.setattr(formal, "_utc_now", lambda: now + timedelta(days=2))
    before = fixtures._inventory(tmp_path)
    checked = execution.inspect_recovery_execution(plan)
    assert checked["current_window_valid"] is False
    assert checked["physical_attempts"] == 2 and checked["successful_judgments"] == 1
    monkeypatch.setenv("LLM_ABM_RUN_LIVE_LLM", "1")
    with pytest.raises(operator.ConcurrentRobustnessOperatorError, match="not current"):
        operator.run_concurrent_robustness_recovery(plan)
    assert fixtures._inventory(tmp_path) == before


@pytest.mark.parametrize("corruption", ["epoch-identity", "expired-admission", "stale-new-grant"])
def test_legal_epoch_reader_rejects_forged_or_expired_admission_before_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path, corruption: str,
) -> None:
    from llm_abm_sim._concurrent_recovery_campaign import CampaignJournal, recovery_scope

    path = _execution_plan(tmp_path, monkeypatch, recovery_source)
    context = execution._load_context(path)
    document = context.plan
    identity = document["authorization"]["request_identity"]
    payload = {"ordinal": 1, "requested_model": identity["requested_model"],
        "epoch_identity_sha256": document["plan_identity_sha256"], "plan_path": str(path),
        "plan_sha256": formal._sha256_file(path)}
    if corruption == "epoch-identity":
        payload["epoch_identity_sha256"] = "f" * 64
    elif corruption == "expired-admission":
        now = formal._utc_now()
        monkeypatch.setattr(formal, "_utc_now", lambda: now + timedelta(days=2))
    with recovery_scope(context.origins.campaign):
        journal = CampaignJournal.open(context.origins.campaign)
        journal.append("epoch_admitted", payload)
    before = fixtures._inventory(tmp_path)
    if corruption == "stale-new-grant":
        request = execution.RecoveryExecutionRequest.model_validate(document["request"])
        with pytest.raises(ValueError, match="stale head"):
            execution.prepare_recovery_execution(request)
    else:
        with pytest.raises(ValueError):
            execution.read_recovery_execution_plan(path)
        monkeypatch.setenv("LLM_ABM_RUN_LIVE_LLM", "1")
        with pytest.raises(ValueError):
            operator.run_concurrent_robustness_recovery(path)
    assert fixtures._inventory(tmp_path) == before


def test_rehashed_execution_budget_and_authority_are_not_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path,
) -> None:
    source = _execution_plan(tmp_path, monkeypatch, recovery_source)
    original = json.loads(source.read_text())
    for corruption in ("budget", "authority", "model", "epoch"):
        path = source.with_name(f"forged-{corruption}.json")
        document = copy.deepcopy(original)
        document["plan_path"] = str(path)
        if corruption == "authority":
            document["execution_authority"] = True
        else:
            identity = document["authorization"]["request_identity"]
            if corruption == "budget":
                identity["maximum_remaining_physical_attempts"] = 108000
            elif corruption == "model":
                identity["requested_model"] = "gemini-3.1-pro"
            else:
                identity["epoch_ordinal"] = 2
            document["authorization"]["request_identity_sha256"] = v2._json_sha256(identity)
            auth = source.with_name(f"forged-{corruption}-approval.json")
            digest = _write(auth, document["authorization"])
            document["authorization_artifact"] = {"path": str(auth), "sha256": digest}
        document["plan_identity_sha256"] = v2._json_sha256({k: val for k, val in document.items() if k != "plan_identity_sha256"})
        _write(path, document)
        before = fixtures._inventory(tmp_path)
        with pytest.raises(ValueError):
            execution.read_recovery_execution_plan(path)
        assert fixtures._inventory(tmp_path) == before


def test_cli_requires_explicit_recovery_schema_and_never_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    plan = _execution_plan(tmp_path, monkeypatch, recovery_source)
    assert cli.main(["status-recovery", "--plan", str(plan)]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["inspection_only"] is True and status["provider_calls"] == 0
    assert cli.main(["run", "--plan", str(plan)]) == 1
    assert json.loads(capsys.readouterr().out)["category"] == "operator_error"
    initial = plan.with_name("initial-plan.json")
    assert cli.main(["run-recovery", "--plan", str(initial)]) == 1
    assert json.loads(capsys.readouterr().out)["category"] == "operator_error"
    before = fixtures._inventory(tmp_path)
    assert cli.main(["run-recovery", "--plan", str(plan)]) == 1
    assert json.loads(capsys.readouterr().out)["category"] == "operator_error"
    assert fixtures._inventory(tmp_path) == before


def test_study_recovery_requires_live_source_scope_even_with_a_valid_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_source: Path,
) -> None:
    from llm_abm_sim._concurrent_recovery_campaign import RecoveryCampaignError

    plan = _execution_plan(tmp_path, monkeypatch, recovery_source)
    document = json.loads(plan.read_text())
    manifest = execution.RecoveryExecutionManifest(execution_plan=formal.FormalArtifactReference(path=plan, sha256=formal._sha256_file(plan)))
    before = fixtures._inventory(tmp_path)
    with pytest.raises(RecoveryCampaignError, match="source-bound Operator lock"):
        execution._run_recovery_study(manifest=manifest, adapters_by_cell=None,
            output_dir=document["authorization"]["request_identity"]["campaign"]["control_root"],
            formal_execution_plan=None, report_destination=None)
    assert fixtures._inventory(tmp_path) == before
