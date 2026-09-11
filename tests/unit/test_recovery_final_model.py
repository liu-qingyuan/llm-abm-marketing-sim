from copy import deepcopy

from llm_abm_sim._concurrent_recovery_campaign import CampaignJournal, recovery_scope
from tests.unit.test_concurrent_recovery_progress import _journal
from tests.unit.test_kimi_migration_runtime import running


def completed(journal):
    s = running(journal)
    s.status = "model_complete"
    s.model_stage_complete = True
    s.parallel_active_batch = None
    for i in (*range(8), *range(12, 16)):
        s.prefix[i] = 1800
        for step in range(30):
            s.batch_commits[(len(s.epochs), i, step)] = {"fixture": True}
    return s


def grant():
    return {"approval": {"path": "/fixture/final.json", "sha256": "c" * 64},
            "requested_model": "openai-codex/gpt-5.6-sol",
            "excluded_model": "gemini-3.8-flash-high", "stop_after_model": True}


def test_final_model_continuation_preserves_history_and_selects_original_gpt(tmp_path):
    with recovery_scope(identity := _journal(tmp_path)):
        journal = CampaignJournal.open(identity)
        s = completed(journal)
        before = deepcopy((s.prefix, s.new_attempts, s.kimi_migration_approval, s.physical_attempts))
        s.append(journal, "final_model_continuation_accepted", grant())
        assert s.current_model == "openai-codex/gpt-5.6-sol"
        assert s.status == "ready" and not s.model_stage_complete
        assert s.effective_parallel_approval is None
        assert not s.kimi_migration_active
        assert before == (s.prefix, s.new_attempts, s.kimi_migration_approval, s.physical_attempts)
        assert s.current_key == (16, 0)


def test_continuation_rejects_incomplete_unsettled_or_wrong_scope(tmp_path):
    import pytest

    from llm_abm_sim._concurrent_recovery_campaign import RecoveryCampaignError
    with recovery_scope(identity := _journal(tmp_path)):
        journal = CampaignJournal.open(identity)
        baseline = completed(journal)
        for field, value in [
            ("status", "stopped"), ("task_revoked", True), ("parallel_inflight", {(12, 0): 1}),
            ("self_check_inflight", "openai-codex/gpt-5.6-sol"),
            ("physical_attempts", baseline.proposal["maximum_new_physical_attempts"]),
        ]:
            s = deepcopy(baseline)
            setattr(s, field, value)
            with pytest.raises(RecoveryCampaignError):
                s.append(journal, "final_model_continuation_accepted", grant())
        for index in (0, 4, 12, 16, 8):
            s = deepcopy(baseline)
            s.prefix[index] = 1
            with pytest.raises(RecoveryCampaignError):
                s.append(journal, "final_model_continuation_accepted", grant())
        for field, value in [("excluded_model", "gemini-3.1-pro"), ("requested_model", "kimi-k3"),
                             ("stop_after_model", False)]:
            payload = grant()
            payload[field] = value
            with pytest.raises(RecoveryCampaignError):
                baseline.append(journal, "final_model_continuation_accepted", payload)
        baseline.append(journal, "final_model_continuation_accepted", grant())
        with pytest.raises(RecoveryCampaignError):
            baseline.append(journal, "final_model_continuation_accepted", grant())


def test_final_model_self_check_uses_original_not_kimi_amendment(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import patch

    from llm_abm_sim import _concurrent_recovery_task_runtime as runtime
    with recovery_scope(identity := _journal(tmp_path)):
        journal = CampaignJournal.open(identity)
        s = completed(journal)
        s.append(journal, "final_model_continuation_accepted", grant())
        context = SimpleNamespace(state=s, origins=SimpleNamespace(source=SimpleNamespace(
            manifest=SimpleNamespace(prompt_model_cells=s.cells))))
        class StopBeforeDispatch(Exception):
            pass
        captured = []
        def capture(context, kind, payload):
            captured.append(kind)
            raise StopBeforeDispatch
        import pytest
        with patch.object(runtime._v2, "_preflight_cell_adapters"),              patch("llm_abm_sim._concurrent_recovery_output_amendment.preflight"),              patch.object(runtime._v2, "_v2_adapter_snapshot"),              patch.object(runtime._task, "_task_status", return_value={"status": "ready"}),              patch.object(runtime._task, "_health_contract", return_value={}),              patch.object(runtime, "_append", side_effect=capture):
            with pytest.raises(StopBeforeDispatch):
                runtime._check_model(context, {c.cell_id: object() for c in s.cells})
        assert captured == ["self_check_intent"]


def test_public_final_admission_binds_receipt_and_repeats_without_append(tmp_path, monkeypatch):
    import hashlib
    from datetime import datetime, timedelta, timezone
    from pathlib import Path
    from types import SimpleNamespace

    import pytest

    from llm_abm_sim import concurrent_robustness_recovery_task as task
    from llm_abm_sim._concurrent_recovery_campaign import RecoveryCampaignError
    from llm_abm_sim._concurrent_recovery_final_model import validate_receipt
    with recovery_scope(identity := _journal(tmp_path)):
        journal = CampaignJournal.open(identity)
        s = completed(journal)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    ref = {"path": "/fixture/task.json", "sha256": "d" * 64}
    origins = SimpleNamespace(campaign=identity, handoff=SimpleNamespace(model_dump=lambda **_: ref),
                              task_plan={"authorization": {"approved_at_utc": (now-timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")}})
    a = {"schema_version": "concurrent-recovery-final-model-approval-v1", "status": "approved",
         "authorization_reference": "user-cancel-flash-run-gpt", "approved_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
         "task_plan": ref, "completed_head_sha256": journal.head,
         **{k:v for k,v in grant().items() if k != "approval"}}
    path = tmp_path / "approval.json"
    from llm_abm_sim.concurrent_robustness_formal_execution import _canonical_json_bytes
    path.write_bytes(_canonical_json_bytes(a))
    path.chmod(0o444)
    payload = {**grant(), "approval": {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}}
    monkeypatch.setattr(task, "_current", lambda *_: True)
    with pytest.raises(RecoveryCampaignError):
        validate_receipt(origins, s, payload, now, "0"*64)
    context = SimpleNamespace(origins=origins, state=s, journal=journal, plan={})
    monkeypatch.setattr(task, "_context", lambda _: context)
    monkeypatch.setattr(task, "_read_revocation", lambda _: None)
    args = {"approval_path": Path(payload["approval"]["path"]), "approval_sha256": payload["approval"]["sha256"]}
    first = task.accept_recovery_task_final_model("/fixture/task.json", **args)
    head = journal.head
    second = task.accept_recovery_task_final_model("/fixture/task.json", **args)
    assert first == second and head == journal.head and first["provider_calls"] == 0
    assert first["credential_reads"] == 0
