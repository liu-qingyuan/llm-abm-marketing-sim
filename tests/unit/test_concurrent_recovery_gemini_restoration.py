"""Durable restoration retains both model histories; no live providers."""

from copy import deepcopy

import pytest

from llm_abm_sim._concurrent_recovery_campaign import CampaignJournal, RecoveryCampaignError, recovery_scope
from llm_abm_sim._concurrent_recovery_gemini_restoration import terms
from llm_abm_sim._concurrent_recovery_progress import CampaignProgress
from tests.unit.test_concurrent_recovery_model_lane import kimi_attempt, running_kimi
from tests.unit.test_concurrent_recovery_parallel_progress import proposal
from tests.unit.test_concurrent_recovery_progress import _journal


def stopped_kimi(journal):
    state, decision = running_kimi(journal)
    from tests.unit.test_concurrent_recovery_parallel_progress import batch, intent, settlement

    reservation = batch()
    reservation["cell_index"] = 12
    for pair in reservation["pairs"]:
        pair["coordinates"]["cell_index"] = 12
    state.append(journal, "parallel_batch_reserved", reservation)
    dispatch = intent(0, 1)
    dispatch["cell_index"] = 12
    state.append(journal, "parallel_attempt_intent", dispatch)
    row = kimi_attempt()
    row.update(
        outcome="nonretryable_failure",
        failure_category="entitlement",
        status_code=403,
        provider_response_count=0,
        successful_decision_count=0,
        observed_model_counts={},
        usage_complete_response_count=0,
        input_usage=None,
        output_usage=None,
        total_usage=None,
        cached_input_usage=None,
    )
    settled = settlement(0, None, row)
    settled["cell_index"] = 12
    state.append(journal, "parallel_attempt_settled", settled)
    return state


def payload(state):
    return {
        "approval": {"path": "/fixture/restoration.json", "sha256": "a" * 64},
        "requested_model": "gemini-3.1-pro",
        "maximum_inflight": 4,
        "stop_after_model": True,
        "failed_attempts": terms(state),
    }


def test_restoration_rereads_gemini_selection_without_erasing_kimi_stop(tmp_path):
    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state = stopped_kimi(journal)
        before = deepcopy(state.new_attempts)
        count = state.physical_attempts
        state.append(journal, "gemini_restoration_accepted", payload(state))
        state = CampaignProgress.replay(proposal(), CampaignJournal.read(identity))
        assert state.current_model == "gemini-3.1-pro"
        assert state.status == "ready" and state.quota_retry_pending == (4, 0)
        assert state.parallel_active_batch == (4, 0)
        assert state.effective_parallel_approval["maximum_inflight"] == 4
        assert state.suspended_models["kimi-coding/k3-256k"]["status"] == "stopped"
        assert state.new_attempts == before and state.physical_attempts == count
        assert state.model_lane_approval is not None
        with pytest.raises(RecoveryCampaignError):
            state.append(journal, "gemini_restoration_accepted", payload(state))


@pytest.mark.parametrize(
    "fault",
    [
        "unknown",
        "inflight",
        "revoked",
        "budget",
        "gemini_identity",
        "kimi_usage",
        "exhausted",
        "crossed_failures",
        "capacity",
    ],
)
def test_restoration_other_hard_stops_and_budget_rejected_before_append(tmp_path, fault):
    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state = stopped_kimi(journal)
        grant = payload(state)
        if fault == "unknown":
            state.parallel_unknown.add((12, 1))
        elif fault == "inflight":
            state.parallel_inflight[12, 1] = 1
        elif fault == "revoked":
            state.task_revoked = True
        elif fault == "budget":
            state.physical_attempts = state.proposal["maximum_new_physical_attempts"]
        elif fault == "gemini_identity":
            state.new_attempts[4, 0][-1] = state.new_attempts[4, 0][-1].model_copy(
                update={"failure_category": "model_identity"}
            )
        elif fault == "kimi_usage":
            state.new_attempts[12, 0][-1] = state.new_attempts[12, 0][-1].model_copy(
                update={"failure_category": "usage_evidence"}
            )
        elif fault == "exhausted":
            state.new_attempts[4, 0] *= 3
        elif fault == "crossed_failures":
            grant["failed_attempts"] = []
        else:
            grant["maximum_inflight"] = 10
        before = journal.head
        with pytest.raises(RecoveryCampaignError):
            state.append(journal, "gemini_restoration_accepted", grant)
        assert journal.head == before


@pytest.mark.parametrize(
    "fault", [None, "prompt", "wire", "missing_field", "identity", "usage", "probe_head", "second_attempt"]
)
def test_probe_binding_checks_frozen_request_and_success_before_admission(tmp_path, fault):
    import json
    from types import SimpleNamespace

    from llm_abm_sim import concurrent_robustness_formal_execution as formal
    from llm_abm_sim import concurrent_robustness_operator as operator
    from llm_abm_sim._concurrent_recovery_gemini_restoration import validate_receipt
    from tests.integration.test_concurrent_recovery_gemini_restoration import _probe_and_restoration_approval
    from tests.integration.test_concurrent_robustness_recovery_epoch import _write
    from tests.unit.test_concurrent_robustness_operator import _Transport

    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state = stopped_kimi(journal)
        plan_path = tmp_path / "plan.json"
        now = formal._utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")
        document = {
            "authorization": {
                "approved_at_utc": now,
                "request_identity": {
                    "provider_routes": [
                        {"requested_model": "gemini-3.1-pro", "required_observed_model": "gemini-pro-agent"}
                    ],
                    "self_check_prompt_sha256": "a" * 64,
                    "self_check_policy": "fixture",
                },
            },
            "request": {"deadline_utc": None},
        }
        _write(plan_path, document)
        context = SimpleNamespace(state=state, journal=journal)
        path = _probe_and_restoration_approval(tmp_path, plan_path, context)
        approval = json.loads(path.read_text())
        evidence = operator._adapter_for_cell(state.cells[4], _Transport("gemini", {})).request_evidence
        origins = SimpleNamespace(
            task_plan=document,
            handoff=formal.FormalArtifactReference(path=plan_path, sha256=formal._sha256_file(plan_path)),
            source=SimpleNamespace(
                manifest=SimpleNamespace(
                    prompt_model_cells=state.cells,
                    request_contract=SimpleNamespace(
                        structured_output_schema_version=evidence["structured_output_schema_version"],
                        structured_output_schema_hash=evidence["structured_output_schema_hash"],
                    ),
                )
            ),
        )
        if fault:
            ref = (
                "probe_intent"
                if fault in {"prompt", "wire", "missing_field", "second_attempt"}
                else ("probe_receipt" if fault == "probe_head" else "probe_result")
            )
            body = json.loads(open(approval[ref]["path"]).read())
            if fault == "prompt":
                body["request_evidence"]["prompt_canonical_hash"] = "sha256:" + "d" * 64
            elif fault == "wire":
                body["request_evidence"]["wire_output_token_ceiling"] = 2048
            elif fault == "missing_field":
                del body["request_evidence"]["thinking_budget"]
            elif fault == "second_attempt":
                body["attempt_number"] = 2
            elif fault == "identity":
                body["attempt"]["observed_model_counts"] = {"another-model": 1}
            elif fault == "usage":
                body["attempt"]["usage_complete_response_count"] = 0
            else:
                body["head_after"] = "c" * 64
            changed = tmp_path / "crossed-probe.json"
            digest = _write(changed, body)
            approval[ref] = {"path": str(changed), "sha256": digest}
        changed_approval = tmp_path / "checked-approval.json"
        digest = _write(changed_approval, approval)
        grant = payload(state)
        grant["approval"] = {"path": str(changed_approval), "sha256": digest}
        before = journal.head
        if fault:
            with pytest.raises((RecoveryCampaignError, ValueError)):
                validate_receipt(origins, state, grant, formal._utc_now(), journal.head)
        else:
            validate_receipt(origins, state, grant, formal._utc_now(), journal.head)
        assert journal.head == before


def test_restored_gemini_preflight_does_not_apply_retained_kimi_output_condition(tmp_path):
    from llm_abm_sim import concurrent_robustness_operator as operator
    from llm_abm_sim._concurrent_recovery_output_amendment import preflight
    from tests.unit.test_concurrent_robustness_operator import _Transport

    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state = stopped_kimi(journal)
        state.output_amendment = {"requested_model": "kimi-coding/k3-256k", "output_token_ceiling": 1024}
        state.amended_self_check = state.self_checks["kimi-coding/k3-256k"]
        state.append(journal, "gemini_restoration_accepted", payload(state))
        cell = state.cells[4]
        adapter = operator._adapter_for_cell(cell, _Transport("gemini", {}))
        assert adapter.request_evidence["output_token_ceiling"] == 256
        assert adapter.request_evidence["wire_output_token_ceiling"] == 1024
        preflight(state, {cell.cell_id: adapter})
        assert state.output_amendment["output_token_ceiling"] == 1024


@pytest.mark.parametrize("fault", [None, "crossed", "inflight", "missing_prior"])
def test_new_gemini_epoch_replays_only_identical_previously_closed_barrier(tmp_path, fault):
    from tests.unit.test_concurrent_recovery_progress import _epoch

    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state = stopped_kimi(journal)
        state.append(journal, "gemini_restoration_accepted", payload(state))
        epoch = _epoch(model="gemini-3.1-pro")
        epoch.update(ordinal=3, epoch_identity_sha256="8" * 64, plan_sha256="8" * 64)
        state.append(journal, "epoch_admitted", epoch)
        state.prefix[4] = 120
        state.parallel_active_batch = (4, 2)
        commit = {"fixture": "previously closed barrier"}
        state.batch_commits[1, 4, 0] = commit.copy()
        if fault == "crossed":
            commit["fixture"] = "different feedback"
        elif fault == "inflight":
            state.parallel_inflight[4, 120] = 1
        elif fault == "missing_prior":
            del state.batch_commits[1, 4, 0]
        grant = {"cell_index": 4, "time_step": 0, "commit": commit}
        if fault:
            with pytest.raises(RecoveryCampaignError):
                state.transition("batch_committed", grant)
        else:
            state.transition("batch_committed", grant)()
            assert state.batch_commits[3, 4, 0] == commit
        assert state.parallel_active_batch == (4, 2)


def test_gemini_adapter_passes_visible256_and_retains_wire1024():
    from llm_abm_sim import concurrent_robustness_operator as operator
    from llm_abm_sim import concurrent_robustness_v2 as v2
    from tests.unit.test_concurrent_robustness_operator import _Transport
    from tests.unit.test_robustness_provider_adapters import _context

    class Transport(_Transport):
        def create_response(self, *args, **kwargs):
            assert kwargs["output_token_ceiling"] == 256
            return super().create_response(*args, **kwargs)

    cell = v2._PromptModelCell.model_validate(proposal()["frozen_context"]["prompt_model_cells"][4])
    adapter = operator._adapter_for_cell(cell, Transport("gemini", {}))
    adapter.decide(**_context())
    assert adapter.request_evidence["wire_output_token_ceiling"] == 1024
    assert adapter.request_evidence["thinking_budget"] == 128
