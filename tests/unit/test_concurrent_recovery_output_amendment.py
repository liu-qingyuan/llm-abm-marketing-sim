"""Explicit Kimi output amendment retains the failed original self-check."""
from copy import deepcopy
from typing import Any

import pytest

from llm_abm_sim._concurrent_recovery_campaign import CampaignJournal, RecoveryCampaignError, recovery_scope
from llm_abm_sim._concurrent_recovery_progress import CampaignProgress
from tests.unit.test_concurrent_recovery_model_lane import admission, kimi_attempt, stopped
from tests.unit.test_concurrent_recovery_parallel_progress import attempt, proposal
from tests.unit.test_concurrent_recovery_progress import _journal

MODEL = 'kimi-coding/k3-256k'


def failed_kimi(journal):
    state = stopped(journal)
    state.append(journal, 'model_lane_accepted', admission())
    state.append(journal, 'self_check_intent', {'requested_model': MODEL, 'contract_sha256': 'd' * 64})
    row = attempt(outcome='nonretryable_failure', no_response=True)
    row.update(failure_category='output_ceiling_exceeded', provider_route='pi_kimi_oauth_subscription', billing_semantics='subscription_quota_with_nominal_usd_reference', billing_currency=None)
    state.append(journal, 'self_check_settled', {'requested_model': MODEL, 'attempt': row, 'decision': None})
    return state


def approval():
    return {'approval': {'path': '/fixture/output1024.json', 'sha256': 'f' * 64},
            'requested_model': MODEL, 'output_token_ceiling': 1024, 'additional_self_check_cap': 1}


def test_amendment_preserves_failure_and_replays_exactly_one_additional_check(tmp_path):
    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state = failed_kimi(journal)
        old = deepcopy(state.self_checks)
        state.append(journal, 'kimi_output_amendment_accepted', approval())
        assert state.status == 'ready' and state.effective_self_check(MODEL) is None
        payload = {'requested_model': MODEL, 'contract_sha256': 'e' * 64}
        state.append(journal, 'amended_self_check_intent', payload)
        head = journal.head
        with pytest.raises(RecoveryCampaignError):
            state.append(journal, 'amended_self_check_intent', payload)
        assert journal.head == head
        decision = {'engage': True, 'probability': 0.8, 'confidence': 0.9, 'action': 'like', 'reason': 'offline'}
        state.append(journal, 'amended_self_check_settled', {'requested_model': MODEL, 'attempt': kimi_attempt(), 'decision': decision})
        reread = CampaignProgress.replay(proposal(), CampaignJournal.read(identity))
        assert reread.self_checks == old
        check = reread.effective_self_check(MODEL)
        assert check is not None and check['attempt']['outcome'] == 'succeeded'
        assert reread.physical_attempts == 1 and reread.suspended_models['gemini-3.1-pro']['status'] == 'stopped'


@pytest.mark.parametrize('fault', ['duplicate', 'quota', 'unknown', 'inflight', 'budget_scope', 'ceiling', 'revoked', 'formal'])
def test_amendment_rejects_other_stops_and_scope_changes(tmp_path, fault):
    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state = failed_kimi(journal)
        payload = approval()
        if fault == 'duplicate':
            state.append(journal, 'kimi_output_amendment_accepted', payload)
        elif fault == 'quota':
            state.self_checks[MODEL]['attempt']['failure_category'] = 'quota_exhausted'
        elif fault == 'unknown':
            state.parallel_unknown.add((12, 0))
        elif fault == 'inflight':
            state.self_check_inflight = MODEL
        elif fault == 'budget_scope':
            payload['additional_self_check_cap'] = 2
        elif fault == 'ceiling':
            payload['output_token_ceiling'] = 2048
        elif fault == 'revoked':
            state.task_revoked = True
        elif fault == 'formal':
            state.new_attempts[12, 0] = []
        head = journal.head
        with pytest.raises(RecoveryCampaignError):
            state.append(journal, 'kimi_output_amendment_accepted', payload)
        assert journal.head == head


def test_amended_failure_stays_terminal_and_unknown_intent_cannot_resend(tmp_path):
    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state = failed_kimi(journal)
        state.append(journal, 'kimi_output_amendment_accepted', approval())
        intent = {'requested_model': MODEL, 'contract_sha256': 'e' * 64}
        state.append(journal, 'amended_self_check_intent', intent)
        state = CampaignProgress.replay(proposal(), CampaignJournal.read(identity))
        assert state.self_check_inflight == MODEL
        with pytest.raises(RecoveryCampaignError):
            state.append(journal, 'amended_self_check_intent', intent)
        old = deepcopy(state.self_checks)
        state.append(journal, 'amended_self_check_settled', old[MODEL])
        assert state.status == 'stopped' and state.self_checks == old
        head = journal.head
        with pytest.raises(RecoveryCampaignError):
            state.append(journal, 'amended_self_check_intent', intent)
        assert journal.head == head


def test_amended_adapter_uses_explicit_wire_ceiling_and_leaves_default_256(tmp_path):
    from llm_abm_sim import concurrent_robustness_operator as operator
    from llm_abm_sim._concurrent_recovery_output_amendment import preflight
    from llm_abm_sim.concurrent_robustness_recovery_task import _self_check_input
    from tests.unit.test_concurrent_robustness_operator import _Transport

    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state = failed_kimi(journal)
        state.append(journal, 'kimi_output_amendment_accepted', approval())
    cell = state.cells[12]
    client: Any = _Transport('kimi', {})
    default: Any = operator._adapter_for_cell(cell, client)
    amended: Any = operator._adapter_for_cell(cell, client, kimi_output_token_ceiling=1024)
    assert default.request_evidence['output_token_ceiling'] == 256
    with pytest.raises(RecoveryCampaignError):
        preflight(state, {cell.cell_id: default})
    preflight(state, {cell.cell_id: amended})
    data = _self_check_input()
    amended.decide(post=data.post, profile=data.profile, peer_context=data.peer_context,
                   platform_context=data.platform_context, time_step=data.time_step)
    assert len(client.calls) == 1 and client.calls[0]['output_token_ceiling'] == 1024
    assert default.request_evidence['output_token_ceiling'] == 256


@pytest.mark.parametrize('fault', [None, 'missing', 'downgrade', 'foreign', 'excess'])
def test_judgment_v3_binds_output_amendment_and_rejects_masquerading(fault):
    from llm_abm_sim._concurrent_recovery_judgment import RecoveryJudgmentV1
    from tests.unit.test_concurrent_recovery_judgment import _payload, _rehash

    payload = _payload(historical=False)
    payload['schema_version'] = 'concurrent-recovery-provider-judgment-v3'
    payload['cell'].update(requested_model=MODEL, required_observed_model='k3-256k', cell_id='P0::' + MODEL)
    payload['cell_index'] = 12
    payload['new_attempts'] = [kimi_attempt()]
    payload['output_amendment_approval'] = approval()['approval']
    if fault == 'missing':
        del payload['output_amendment_approval']
    elif fault == 'downgrade':
        payload['schema_version'] = 'concurrent-recovery-provider-judgment-v1'
    elif fault == 'foreign':
        payload['cell'].update(requested_model='deepseek-v4-flash', required_observed_model='deepseek-v4-flash', cell_id='P0::deepseek-v4-flash')
    elif fault == 'excess':
        payload['new_attempts'][0].update(output_usage=1025, total_usage=1035)
    _rehash(payload)
    if fault:
        with pytest.raises(ValueError):
            RecoveryJudgmentV1.model_validate(payload)
    else:
        assert RecoveryJudgmentV1.model_validate(payload).model_dump(mode='json') == payload
