"""Offline bounded collection scheduling and append-only replay contracts."""
import json
import threading
import time
from collections import Counter

import pytest
from test_parameter_judgment_bank import _synthetic_audit

from llm_abm_sim import _parameter_collection as collection
from llm_abm_sim import _parameter_judgment_bank as bank
from llm_abm_sim.concurrent_robustness_study import ConcurrentRobustnessStudy
from llm_abm_sim.decision import ProviderResponseProvenanceUnknown
from llm_abm_sim.provider_accounting import ProviderResponseEnvelope


def _prepared(tmp_path, monkeypatch):
    audit = _synthetic_audit(tmp_path, monkeypatch)
    root = tmp_path / 'prepared'
    study = ConcurrentRobustnessStudy()
    study.prepare_parameter_study(audit, root)
    scope = root / 'collection'
    scope.mkdir()
    bank.write_json(scope / 'concurrency-authorization.json', {
        'schema_version': 'gpt-p0-concurrency-authorization-v1',
        'preparation_sha256': bank.file_hash(root / 'preparation.json'),
        'maximum_concurrency': 5, 'reason': 'explicit_user_request_20260917',
    })
    return study, root


def _clients(*, hard_failure=False):
    lock = threading.Lock()
    barrier = threading.Barrier(5)
    state = {'calls': 0, 'active': 0, 'peak': 0}
    class Client:
        external_provider_client = False
        last_subscription_nominal_cost_usd = .01
        def create_response(self, messages, model, **kwargs):
            with lock:
                state['calls'] += 1
                n = state['calls']
                state['active'] += 1
                state['peak'] = max(state['peak'], state['active'])
            try:
                if 2 <= n <= 6:
                    barrier.wait(timeout=10)
                    if hard_failure and n == 2:
                        raise ProviderResponseProvenanceUnknown('not persisted')
                    time.sleep((7-n)*.01 if not hard_failure else .1)
                return ProviderResponseEnvelope(
                    decision_text=json.dumps({'engage': False, 'probability': .2, 'confidence': .8,
                                              'action': 'ignore', 'reason': 'fixture'}),
                    observed_model='gpt-5.6-sol', observed_model_status='reported', usage_status='complete',
                    input_tokens=10, output_tokens=5, total_tokens=15, cached_input_tokens=0)
            finally:
                with lock:
                    state['active'] -= 1
    return tuple(Client() for _ in range(5)), state


def test_five_clients_reach_five_and_replay_out_of_order_without_resend(tmp_path, monkeypatch):
    study, root = _prepared(tmp_path, monkeypatch)
    clients, state = _clients()
    result = study.collect_parameter_judgments(root, client=clients)
    assert state == {'calls': 1201, 'active': 0, 'peak': 5}
    events = collection._events(root/'collection/attempts.jsonl', bank.file_hash(root/'preparation.json'))
    intents, accepted, qualified = collection._state(events)
    assert len(intents) == 1201 and len(accepted) == 1200 and qualified
    assert [e['payload']['intent_sequence'] for e in events if e['kind']=='settled'] != sorted(
        e['payload']['intent_sequence'] for e in events if e['kind']=='settled')
    assert all('concurrency_authorization_sha256' in i for i in intents)
    assert result['concurrency_authorization_sha256'] == bank.file_hash(root/'collection/concurrency-authorization.json')
    prefix = (root/'collection/attempts.jsonl').read_bytes()
    assert study.collect_parameter_judgments(root, client=clients) == result
    assert state['calls'] == 1201 and (root/'collection/attempts.jsonl').read_bytes() == prefix
    from llm_abm_sim._parameter_evidence import validate_collection
    evidence = validate_collection(root)
    assert evidence['maximum_observed_in_flight'] == 5
    assert evidence['authorized_maximum_concurrency'] == 5
    auth_path = root/'collection/concurrency-authorization.json'
    authorization = bank.read_json(auth_path)
    authorization['maximum_concurrency'] = 6
    bank.write_json(auth_path, authorization)
    with pytest.raises(ValueError):
        validate_collection(root)


def test_hard_failure_stops_dispatch_but_drains_all_reserved_requests(tmp_path, monkeypatch):
    study, root = _prepared(tmp_path, monkeypatch)
    clients, state = _clients(hard_failure=True)
    with pytest.raises(ValueError, match='collection stopped'):
        study.collect_parameter_judgments(root, client=clients)
    assert state == {'calls': 6, 'active': 0, 'peak': 5}
    events = collection._events(root/'collection/attempts.jsonl', bank.file_hash(root/'preparation.json'))
    assert Counter(e['kind'] for e in events) == {'intent': 6, 'settled': 6}
    assert sum(e['kind']=='settled' and e['payload']['outcome']=='succeeded' for e in events) == 5
    with pytest.raises(ValueError, match='collection stopped'):
        study.collect_parameter_judgments(root, client=clients)
    assert state['calls'] == 6
    assert not (root/'closed-bank.jsonl').exists()


@pytest.mark.parametrize('fault', ['no_authorization','duplicate_client','too_many'])
def test_concurrency_requires_bounded_independent_clients_and_authorization(tmp_path, monkeypatch, fault):
    study, root = _prepared(tmp_path, monkeypatch)
    clients, state = _clients()
    if fault == 'no_authorization':
        (root/'collection/concurrency-authorization.json').unlink()
    elif fault == 'duplicate_client':
        clients = (clients[0], clients[0])
    else:
        clients = (*clients, object())
    with pytest.raises(ValueError):
        study.collect_parameter_judgments(root, client=clients)
    assert state['calls'] == 0


@pytest.mark.parametrize('duplicate', ['active', 'successful'])
def test_replay_rejects_duplicate_pair_dispatch(duplicate):
    before = {'purpose':'judgment','pair_key':'pair','intent_sequence':0}
    events = [{'sequence':0,'kind':'intent','payload':before}]
    if duplicate == 'successful':
        events.append({'sequence':1,'kind':'settled','payload':{'intent_sequence':0,'outcome':'succeeded',
                       'bank_entry':{}},'sha256':'hash','recorded_at_utc':'date'})
    events.append({'sequence':len(events),'kind':'intent','payload':{**before,'intent_sequence':len(events)}})
    with pytest.raises(ValueError, match='duplicate'):
        collection._state(events)


@pytest.mark.parametrize('limit', ['physical', 'pair', 'global_retry'])
def test_reserved_budget_is_shared_before_dispatch(tmp_path, monkeypatch, limit):
    study, root = _prepared(tmp_path, monkeypatch)
    rows = [json.loads(line) for line in (root/'missing-pairs.jsonl').read_text().splitlines()]
    keys = [bank.fingerprint([r['user_id'],r['message_id']]) for r in rows]
    def intent(key):
        return {'purpose':'judgment','pair_key':key}
    if limit == 'physical':
        prior = [intent(keys[1])] * 1262
    elif limit == 'pair':
        prior = [intent(keys[0])] * 3
    else:
        prior = [intent(keys[0])] + [intent(key) for key in keys[1:61] for _ in range(2)]
    # Inject the already-replayed state at the scheduler boundary; no live calls.
    monkeypatch.setattr(collection, '_state', lambda events: (prior, {}, True))
    clients, state = _clients()
    with pytest.raises(ValueError, match='cap reached'):
        study.collect_parameter_judgments(root, client=clients)
    assert state['calls'] == 0
