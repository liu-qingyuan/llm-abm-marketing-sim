from copy import deepcopy
from typing import Any

import pytest

from llm_abm_sim._concurrent_recovery_campaign import CampaignJournal, RecoveryCampaignError, recovery_scope
from llm_abm_sim._concurrent_recovery_kimi_migration import cash_budget
from tests.unit.test_concurrent_recovery_progress import _journal
from tests.unit.test_kimi_migration_judgment import official_payload
from tests.unit.test_kimi_migration_runtime import running


def cash_stopped(journal):
    state = running(journal)
    for pos in range(4):
        data = official_payload(pos == 0)
        a = data["new_attempts"][-1]
        a.update(input_usage=1000000, total_usage=1000000 + a["output_usage"])
        state.append(
            journal,
            "parallel_attempt_intent",
            dict(cell_index=12, pair_schedule_position=pos, attempt_number=2 if pos == 0 else 1),
        )
        state.append(
            journal,
            "parallel_attempt_settled",
            dict(cell_index=12, pair_schedule_position=pos, attempt=a, decision=data["decision"]),
        )
    assert not cash_budget(state)["can_reserve_one"]
    state.append(journal, "kimi_official_cash_budget_stopped", {"budget": cash_budget(state)})
    return state


def grant():
    return {
        "approval": {"path": "/fixture/cap.json", "sha256": "c" * 64},
        "previous_maximum_spend_cny": 100,
        "maximum_spend_cny": 350,
    }


def test_cash_amendment_retains_cumulative_spend_and_original_grant(tmp_path):
    with recovery_scope(identity := _journal(tmp_path)):
        journal = CampaignJournal.open(identity)
        s = cash_stopped(journal)
        before = cash_budget(s)
        attempts = deepcopy(s.new_attempts)
        physical = s.physical_attempts
        s.append(journal, "kimi_cash_cap_amendment_accepted", grant())
        assert s.status == "paused"
        after = cash_budget(s)
        assert after["maximum_micro_cny"] == 350000000 and after["can_reserve_one"]
        assert after["settled_upper_micro_cny"] == before["settled_upper_micro_cny"]
        assert s.new_attempts == attempts and s.physical_attempts == physical
        assert s.kimi_migration_approval is not None
        assert s.kimi_migration_approval["maximum_spend_cny"] == 100
        with pytest.raises(RecoveryCampaignError):
            s.append(journal, "kimi_cash_cap_amendment_accepted", grant())


@pytest.mark.parametrize(
    "field,value", [("maximum_spend_cny", 351), ("maximum_spend_cny", True), ("previous_maximum_spend_cny", 0)]
)
def test_cap_amendment_rejects_other_terms(tmp_path, field, value):
    with recovery_scope(identity := _journal(tmp_path)):
        journal = CampaignJournal.open(identity)
        s = cash_stopped(journal)
        wrong = grant()
        wrong[field] = value
        with pytest.raises(RecoveryCampaignError):
            s.append(journal, "kimi_cash_cap_amendment_accepted", wrong)
        assert cash_budget(s)["maximum_micro_cny"] == 100000000


def receipt(tmp_path):
    import hashlib
    import json
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    now = datetime.now(timezone.utc).replace(microsecond=0)
    plan = {"path": "/fixture/task.json", "sha256": "d" * 64}
    origins = SimpleNamespace(
        handoff=SimpleNamespace(model_dump=lambda **_: plan),
        task_plan={"authorization": {"approved_at_utc": (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")}},
    )

    def write(previous, **changes):
        body = {
            "schema_version": "kimi-cash-cap-consent-v1",
            "status": "approved",
            "user_confirmation": "已经充值，现在请你继续。",
            "confirmation_context": "上限350",
            "recorded_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "plan": plan,
            "expected_head_sha256": previous["record_sha256"],
            "previous_maximum_spend_cny": 100,
            "maximum_spend_cny": 350,
            "other_models_enabled": False,
            "production_deploy_eligible": False,
            **changes,
        }
        f = tmp_path / "cap-consent.json"
        f.write_text(json.dumps(body))
        f.chmod(0o444)
        return {**grant(), "approval": {"path": str(f), "sha256": hashlib.sha256(f.read_bytes()).hexdigest()}}

    return now, origins, write


@pytest.mark.parametrize("bad", ["head", "kind", "expired", "other_model"])
def test_receipt_rejects_crossed_or_unapproved_restart(tmp_path, monkeypatch, bad):
    from llm_abm_sim import concurrent_robustness_recovery_task as task
    from llm_abm_sim._concurrent_recovery_kimi_migration import validate_cash_cap_receipt

    with recovery_scope(identity := _journal(tmp_path)):
        journal = CampaignJournal.open(identity)
        s = cash_stopped(journal)
        now, origins, write = receipt(tmp_path)
        previous = deepcopy(journal.records[-1])
        payload = write(
            previous,
            **(
                {"expected_head_sha256": "f" * 64}
                if bad == "head"
                else {"other_models_enabled": True}
                if bad == "other_model"
                else {}
            ),
        )
        if bad == "kind":
            previous["kind"] = "parallel_attempt_settled"
        monkeypatch.setattr(task, "_current", lambda *_: bad != "expired")
        with pytest.raises(RecoveryCampaignError):
            validate_cash_cap_receipt(origins, s, payload, now, previous)
        assert s.status == "stopped" and cash_budget(s)["maximum_micro_cny"] == 100000000


def test_public_admission_is_idempotent_and_zero_provider(tmp_path, monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace

    from llm_abm_sim import concurrent_robustness_recovery_task as task

    with recovery_scope(identity := _journal(tmp_path)):
        journal = CampaignJournal.open(identity)
        s = cash_stopped(journal)
    _, origins, write = receipt(tmp_path)
    origins.campaign = identity
    payload = write(journal.records[-1])
    context = SimpleNamespace(origins=origins, state=s, journal=journal, plan={})
    monkeypatch.setattr(task, "_context", lambda _: context)
    monkeypatch.setattr(task, "_current", lambda *_: True)
    monkeypatch.setattr(task, "_read_revocation", lambda _: None)
    args: dict[str, Any] = dict(approval_path=Path(payload["approval"]["path"]), approval_sha256=payload["approval"]["sha256"])
    first = task.accept_recovery_task_kimi_cash_cap("/fixture/task.json", **args)
    head = journal.head
    second = task.accept_recovery_task_kimi_cash_cap("/fixture/task.json", **args)
    assert first == second and journal.head == head and first["provider_calls"] == 0
    assert first["credential_reads"] == 0 and cash_budget(s)["maximum_micro_cny"] == 350000000
