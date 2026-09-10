from copy import deepcopy
from typing import Any

import pytest

from llm_abm_sim._concurrent_recovery_campaign import CampaignJournal, RecoveryCampaignError, recovery_scope
from tests.unit.test_concurrent_recovery_progress import _journal
from tests.unit.test_kimi_migration_runtime import running


def stopped(journal, with_success=False):
    state = running(journal)
    if with_success:
        from tests.unit.test_kimi_migration_judgment import official_payload
        p = official_payload()
        state.append(journal, 'parallel_attempt_intent', {'cell_index': 12, 'pair_schedule_position': 1, 'attempt_number': 1})
        state.append(journal, 'parallel_attempt_settled', {'cell_index': 12, 'pair_schedule_position': 1,
                     'attempt': p['new_attempts'][0], 'decision': p['decision']})
    rows = []
    for pos in (10, 11, 12, 13):
        e = state.append(journal, 'parallel_attempt_intent',
                         {'cell_index': 12, 'pair_schedule_position': pos, 'attempt_number': 1})
        rows.append({'cell_index': 12, 'pair_schedule_position': pos,
                     'attempt_number': 1, 'intent_sha256': e['record_sha256']})
    state.append(journal, 'epoch_finished', {'status': 'reconciliation_required'})
    return state, {'approval': {'path': '/fixture/manual.json', 'sha256': 'a' * 64}, 'unknown_intents': rows}


def test_manual_acceptance_preserves_physical_history_and_next_ordinal(tmp_path):
    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state, payload = stopped(journal)
        old = deepcopy(state.new_attempts)
        budget = state.physical_attempts
        from llm_abm_sim._concurrent_recovery_kimi_migration import cash_budget
        cash = cash_budget(state)
        state.append(journal, 'kimi_manual_retry_accepted', payload)
        assert state.status == 'paused' and not state.has_inflight
        assert len(state.kimi_archived_unknown) == 4
        assert state.next_attempt_number((12, 10)) == 2
        assert state.physical_attempts == budget and state.new_attempts == old
        updated = cash_budget(state)
        assert updated['settled_upper_micro_cny'] + updated['reserved_micro_cny'] == cash['settled_upper_micro_cny'] + cash['reserved_micro_cny']
        with pytest.raises(RecoveryCampaignError):
            state.append(journal, 'kimi_manual_retry_accepted', payload)


@pytest.mark.parametrize('fault', ['partial', 'duplicate', 'ordinal', 'hash', 'revoked', 'success', 'foreign'])
def test_manual_acceptance_rejects_crossed_history_without_mutation(tmp_path, fault):
    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state, payload = stopped(journal)
        if fault == 'partial':
            payload['unknown_intents'].pop()
        elif fault == 'duplicate':
            payload['unknown_intents'][1] = deepcopy(payload['unknown_intents'][0])
        elif fault == 'ordinal':
            payload['unknown_intents'][0]['attempt_number'] = 2
        elif fault == 'hash':
            payload['unknown_intents'][0]['intent_sha256'] = 'bad'
        elif fault == 'revoked':
            state.task_revoked = True
        elif fault == 'success':
            state.old_successes.add((12, 10))
        else:
            payload['unknown_intents'][0]['cell_index'] = 4
        before = deepcopy(state.__dict__)
        head = journal.head
        with pytest.raises((RecoveryCampaignError, ValueError)):
            state.append(journal, 'kimi_manual_retry_accepted', payload)
        assert state.__dict__ == before and journal.head == head


def test_manual_retries_run_once_and_repeat_reuses_successes(tmp_path, monkeypatch):
    from llm_abm_sim import _concurrent_recovery_kimi_migration as migration
    from llm_abm_sim import _concurrent_recovery_parallel_runtime as runtime
    from llm_abm_sim.concurrent_message_experiment import _VariantDecisionContext
    from llm_abm_sim.providers.robustness import OfficialKimiDecisionAdapter
    from tests.unit.test_moonshot_official_adapter import Client
    from tests.unit.test_robustness_provider_adapters import _context
    monkeypatch.setattr(migration, '_RESERVE_MICRO_CNY', 1)  # Offline fixture only.
    monkeypatch.setattr(runtime, '_OFFICIAL_DISPATCH_INTERVAL_SECONDS', 0)
    clients: list[Any] = [Client() for _ in range(5)]
    for client in clients:
        client.external_provider_client = True
        client.output_token_ceiling_enforcement = 'wire_only'
    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state, payload = stopped(journal)
        state.append(journal, 'kimi_manual_retry_accepted', payload)
        state.status = 'running'  # State-only fixture; public epoch admission stays unchanged.
        cell = state.cells[12]
        data = _context()
        context = _VariantDecisionContext(decision_variant='primary', prompt_token=cell.prompt_version,
                  **{k: data[k] for k in ('post', 'profile', 'peer_context', 'platform_context')})
        work = tuple(runtime.FrozenWork(row['coordinates'], context) for row in state.parallel_batches[12, 0]['pairs'])
        state.parallel_batches[12, 0]['pairs'] = [w.reservation() for w in work]
        pool = runtime.ParallelAdapterPool(tuple(OfficialKimiDecisionAdapter(prompt_version=cell.prompt_version, client=c) for c in clients))
        before = state.physical_attempts
        runtime.run_frozen_batch(state=state, journal=journal, pool=pool, work=work,
                                 check_dispatch_window=lambda: None, backoff_seconds=0)
        assert state.physical_attempts == before + 60
        for key in state.kimi_archived_unknown:
            assert state.new_attempts[key][0].attempt_number == 2
        after = state.physical_attempts
        runtime.run_frozen_batch(state=state, journal=journal, pool=pool, work=work,
                                 check_dispatch_window=lambda: None, backoff_seconds=0)
        assert state.physical_attempts == after


def test_receipt_accepts_immutable_user_json_and_rejects_hash_drift(tmp_path, monkeypatch):
    import hashlib
    import json
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    from llm_abm_sim import concurrent_robustness_formal_execution as formal
    from llm_abm_sim import concurrent_robustness_recovery_task as task
    from llm_abm_sim._concurrent_recovery_manual_retry import validate_receipt
    identity = _journal(tmp_path)
    with recovery_scope(identity):
        journal = CampaignJournal.open(identity)
        state, payload = stopped(journal, with_success=True)
        by_hash = {row['record_sha256']: row for row in journal.records}
        original = formal.FormalArtifactReference(path=tmp_path/'original.json', sha256='f'*64)
        doc = {'schema_version': 'kimi-manual-unknown-retry-user-consent-v1',
               'status': 'user_approved_pending_runtime_admission',
               'stopped_head': {'record_sha256': journal.head, 'sequence': len(journal.records)},
               'original_plan': original.model_dump(mode='json'),
               'additional_attempts_per_listed_logical': 1, 'maximum_historical_attempts_per_logical': 3,
               'automatic_retries': 0, 'maximum_inflight': 5, 'maximum_spend_cny': 100,
               'cash_cap_increase_authorized': False, 'usage_unknown_preserved': True,
               'other_models_enabled': False, 'production_deploy_eligible': False,
               'goal': {'judgments': 7200, 'cells': 4, 'complete_barriers': 120},
               'recorded_at_utc': (datetime.now(timezone.utc)-timedelta(seconds=5)).isoformat(),
               'unknown_intents': [{**row, 'recorded_at_utc': by_hash[row['intent_sha256']]['recorded_at_utc']}
                                   for row in payload['unknown_intents']], 'preserved_successes': [
                   {'cell_index': 12, 'pair_schedule_position': 1, 'event_sha256': event['record_sha256'],
                    'attempt_sha256': hashlib.sha256(json.dumps(event['payload']['attempt'], ensure_ascii=False,
                                                               sort_keys=True, separators=(',', ':')).encode()).hexdigest()}
                   for event in journal.records if event['kind'] == 'parallel_attempt_settled'
                   and event['payload']['cell_index'] == 12 and event['payload']['pair_schedule_position'] == 1]}
        path = tmp_path/'consent.json'
        path.write_text(json.dumps(doc, indent=2))
        path.chmod(0o444)
        payload['approval'] = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        origins = SimpleNamespace(campaign=identity, task_plan={}, handoff=original)
        monkeypatch.setattr(task, '_current', lambda *args: True)
        validate_receipt(origins, state, payload, datetime.now(timezone.utc), journal.head)
    context = SimpleNamespace(origins=origins, state=state, journal=journal, plan={})
    monkeypatch.setattr(task, '_context', lambda *args: context)
    monkeypatch.setattr(task, '_read_revocation', lambda *args: None)
    result = task.accept_recovery_task_kimi_manual_retry(tmp_path/'plan.json', approval_path=path,
                                                        approval_sha256=payload['approval']['sha256'])
    head = journal.head
    again = task.accept_recovery_task_kimi_manual_retry(tmp_path/'plan.json', approval_path=path,
                                                       approval_sha256=payload['approval']['sha256'])
    assert again == result and result['provider_calls'] == 0 and journal.head == head
    payload['approval']['sha256'] = 'b'*64
    with pytest.raises(RecoveryCampaignError):
        validate_receipt(origins, state, payload, datetime.now(timezone.utc), journal.head)
