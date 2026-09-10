from copy import deepcopy

import pytest

from llm_abm_sim._concurrent_recovery_campaign import CampaignJournal, RecoveryCampaignError, recovery_scope
from tests.unit.test_concurrent_recovery_gemini_restoration import payload, stopped_kimi
from tests.unit.test_concurrent_recovery_progress import _journal


def completed_gemini(journal):
    state = stopped_kimi(journal)
    state.append(journal, 'gemini_restoration_accepted', payload(state))
    # State-only fixture for the read-only admission invariant checker.
    state.status = 'model_complete'
    state.model_stage_complete = True
    state.quota_retry_pending = None
    state.parallel_active_batch = None
    for i in range(4, 8):
        state.prefix[i] = state.per_cell
    return state


def test_migration_terms_preserve_original_failed_attempt_and_budget(tmp_path):
    from llm_abm_sim._concurrent_recovery_kimi_migration import terms

    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state = completed_gemini(journal)
        before = deepcopy(state.__dict__)
        result = terms(state)
        assert result['failed_attempts'][0]['cell_index'] == 12
        assert result['failed_attempts'][0]['pair_schedule_position'] == 0
        assert result['remaining_logical_judgments'] == 7200
        assert result['frozen_batch'] == [12, 0]
        assert state.__dict__ == before


@pytest.mark.parametrize('fault', ['inflight', 'unknown', 'revoked', 'budget', 'incomplete', 'pending', 'batch', 'failed_kind'])
def test_migration_terms_reject_other_states(tmp_path, fault):
    from llm_abm_sim._concurrent_recovery_kimi_migration import terms

    identity = _journal(tmp_path)
    with recovery_scope(identity):
        state = completed_gemini(CampaignJournal.open(identity))
        if fault == 'inflight':
            state.parallel_inflight[12, 1] = 1
        elif fault == 'unknown':
            state.parallel_unknown.add((12, 1))
        elif fault == 'revoked':
            state.task_revoked = True
        elif fault == 'budget':
            state.physical_attempts = state.proposal['maximum_new_physical_attempts']
        elif fault == 'incomplete':
            state.prefix[7] -= 1
        elif fault == 'pending':
            state.quota_retry_pending = (4, 0)
        elif fault == 'batch':
            state.suspended_models['kimi-coding/k3-256k']['parallel_active_batch'] = (12, 1)
        else:
            state.new_attempts[12, 0][0] = state.new_attempts[12, 0][0].model_copy(update={'status_code': 401})
        with pytest.raises(RecoveryCampaignError):
            terms(state)


def test_receipt_admission_is_single_use_and_does_not_dispatch_or_change_stage(tmp_path):
    from llm_abm_sim._concurrent_recovery_kimi_migration import terms

    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state = completed_gemini(journal)
        before = deepcopy(state.__dict__)
        grant = {'approval': {'path': '/fixture/migration.json', 'sha256': 'e' * 64},
                 'destination_model': 'kimi-k3', 'maximum_inflight': 5,
                 'output_token_ceiling': 1024, 'maximum_spend_cny': 100,
                 'terms': terms(state)}
        state.append(journal, 'kimi_official_migration_accepted', grant)
        assert state.kimi_migration_approval == grant
        assert state.current_model == 'gemini-3.1-pro'
        assert state.status == 'model_complete'
        assert state.physical_attempts == before['physical_attempts']
        assert state.new_attempts == before['new_attempts']
        assert state.success_decisions == before['success_decisions']
        with pytest.raises(RecoveryCampaignError):
            state.append(journal, 'kimi_official_migration_accepted', grant)


def receipt_fixture(tmp_path, state):
    import hashlib
    import json
    from types import SimpleNamespace

    from llm_abm_sim import concurrent_robustness_formal_execution as formal
    from llm_abm_sim._concurrent_recovery_kimi_migration import terms
    from llm_abm_sim.concurrent_robustness_recovery_task import _self_check_input
    from llm_abm_sim.prompting import build_engagement_prompt
    from llm_abm_sim.provider_request_contract import engage_decision_json_schema

    def write(name, data, canonical=True):
        p = tmp_path / name
        p.write_bytes(formal._canonical_json_bytes(data) if canonical else json.dumps(data, indent=2).encode())
        p.chmod(0o444)
        return {'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}

    plan = {'authorization': {'approved_at_utc': '2026-09-09T00:00:00Z'}, 'request': {'deadline_utc': None}}
    ref = write('task.json', plan)
    origins = SimpleNamespace(task_plan=plan, handoff=formal.FormalArtifactReference.model_validate(ref))
    scope = terms(state)
    consent = {'schema_version': 'kimi-official-migration-user-consent-v1',
               'status': 'user_confirmed_pending_implementation', 'user_confirmation': '确认', 'plan': ref,
               'control_head': {'record_sha256': 'b' * 64}, 'destination_requested_model': 'kimi-k3',
               'destination_required_observed_model': 'kimi-k3', 'remaining_logical': scope['remaining_logical_judgments'],
               'maximum_inflight': 5, 'output_token_ceiling': 1024, 'existing_successes': [],
               'existing_failures': [{'cell_index': 12, 'pair_schedule_position': 0,
                                     'attempt': state.new_attempts[12, 0][0].model_dump(mode='json')}]}
    d = _self_check_input()
    body = {'model': 'kimi-k3', 'messages': build_engagement_prompt(d), 'max_tokens': 1024,
            'reasoning_effort': 'low', 'tools': [{'type': 'function', 'function': {
                'name': 'engage_decision', 'description': 'Return one structured engagement decision.',
                'parameters': engage_decision_json_schema()['schema']}}], 'tool_choice': 'required'}
    intent = {'requested_model': 'kimi-k3', 'base_url': 'https://api.moonshot.cn/v1',
              'input_sha256': d.cache_key(), 'request_sha256': hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest(),
              'maximum_client_attempts': 1, 'automatic_retries': 0, 'formal_calls': 0}
    result = {'requested_model': 'kimi-k3', 'observed_model': 'kimi-k3', 'status': 'succeeded', 'http_status': 200,
              'client_attempts': 1, 'automatic_retries': 0, 'formal_calls': 0, 'finish_reason': 'tool_calls',
              'usage': {'prompt_tokens': 660, 'completion_tokens': 302, 'total_tokens': 962},
              'decision': {'engage': False, 'probability': .32, 'reason': 'test', 'confidence': .78, 'action': 'ignore'}}
    receipt = {'schema_version': 'concurrent-recovery-kimi-official-migration-approval-v1', 'status': 'approved',
               'authorization_reference': 'user-confirmed-fixture', 'approved_at_utc': '2026-09-10T00:00:00Z',
               'task_plan': ref, 'expected_head_sha256': 'b' * 64, 'terms': scope,
               'destination_model': 'kimi-k3', 'maximum_inflight': 5, 'output_token_ceiling': 1024,
               'maximum_spend_cny': 100, 'user_consent': write('consent.json', consent, False),
               'health_intent': write('health-intent.json', intent, False),
               'health_result': write('health-result.json', result, False)}
    return origins, receipt, write


@pytest.mark.parametrize('fault', [None, 'head', 'model', 'usage', 'consent', 'attempt', 'cap'])
def test_bound_receipt_checks_health_and_consent_without_new_calls(tmp_path, fault):
    from datetime import datetime, timezone

    from llm_abm_sim._concurrent_recovery_kimi_migration import FIELDS, validate_receipt

    identity = _journal(tmp_path)
    with recovery_scope(identity):
        state = completed_gemini(CampaignJournal.open(identity))
        origins, receipt, write = receipt_fixture(tmp_path, state)
        if fault == 'head':
            receipt['expected_head_sha256'] = 'c' * 64
        elif fault == 'model':
            receipt['destination_model'] = 'k3-256k'
        elif fault in {'usage', 'consent', 'attempt'}:
            import json
            from pathlib import Path
            name = {'usage': 'health_result', 'consent': 'user_consent', 'attempt': 'health_intent'}[fault]
            data = json.loads(Path(receipt[name]['path']).read_text())
            if fault == 'usage':
                data['usage']['total_tokens'] += 1
            elif fault == 'consent':
                data['user_confirmation'] = None
            else:
                data['maximum_client_attempts'] = 2
            receipt[name] = write('crossed-evidence.json', data, False)
        elif fault == 'cap':
            receipt['maximum_spend_cny'] = 101
        grant = {'approval': write('approval.json', receipt), **{k: receipt[k] for k in FIELDS}}
        now = datetime(2026, 9, 11, tzinfo=timezone.utc)
        before = deepcopy(state.__dict__)
        if fault:
            with pytest.raises(RecoveryCampaignError):
                validate_receipt(origins, state, grant, now, 'b' * 64)
        else:
            validate_receipt(origins, state, grant, now, 'b' * 64)
        assert state.__dict__ == before
