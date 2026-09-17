from pathlib import Path

import pytest

from llm_abm_sim.concurrent_robustness_study import ConcurrentRobustnessStudy


def test_prepare_rejects_unverified_audit_before_output(tmp_path: Path) -> None:
    audit = tmp_path / 'audit.json'
    audit.write_text('{}')
    target = tmp_path / 'prepared'
    with pytest.raises(ValueError, match='audit SHA-256'):
        ConcurrentRobustnessStudy().prepare_parameter_study(audit, target)
    assert not target.exists()
    assert audit.read_text() == '{}'


@pytest.mark.parametrize('kind', ['missing', 'symlink', 'existing_output'])
def test_prepare_rejects_unsafe_paths(tmp_path: Path, kind: str) -> None:
    audit = tmp_path / 'audit.json'
    target = tmp_path / 'prepared'
    if kind == 'symlink':
        original = tmp_path / 'original.json'
        original.write_text('{}')
        audit.symlink_to(original)
    elif kind == 'existing_output':
        audit.write_text('{}')
        target.mkdir()
    with pytest.raises(ValueError):
        ConcurrentRobustnessStudy().prepare_parameter_study(audit, target)
    assert not target.exists() or list(target.iterdir()) == []


def _synthetic_audit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    import json
    from types import SimpleNamespace

    from llm_abm_sim import _parameter_judgment_bank as bank
    from llm_abm_sim.concurrent_message_experiment import _primary_variant_profile
    from llm_abm_sim.decision import DecisionInput
    from llm_abm_sim.schemas import PeerContext, PlatformContext
    from tests.unit.test_concurrent_message_experiment import _message, _research_user
    from tests.unit.test_concurrent_recovery_judgment import _payload, _rehash

    root = tmp_path / 'source'
    root.mkdir()
    users = {f'u{i:04}': _research_user(f'u{i:04}', environmental=1.0) for i in range(1000)}
    messages = [_message(f'message_{i}', environmental=1.0) for i in range(1, 4)]
    config = SimpleNamespace(messages=messages, horizon=30)
    prepared = SimpleNamespace(cohort=SimpleNamespace(sample_user_ids=list(users), users_by_id=users))
    monkeypatch.setattr(bank, '_inputs', lambda audit: (config, prepared, None))
    monkeypatch.setattr(bank.v2, '_assert_source_unchanged', lambda closure: None)
    sample = _payload(historical=False)
    condition = {'prompt_version': sample['cell']['prompt_version'], 'requested_model': bank.MODEL,
                 'wire_model': 'gpt-5.6-sol', 'observed_model': 'gpt-5.6-sol',
                 'provider_route': 'pi_openai_oauth_subscription', 'wire_api': 'pi_model_runtime',
                 'reasoning_effort': 'low', 'output_token_ceiling': 256,
                 'cache_retention': 'none', 'decision_store_policy': 'fresh-per-cell-no-cache-v1',
                 'effective_upstream_context_status': 'unobservable'}
    audit = {'historical_request_condition': condition}
    request_condition = bank._request_condition(audit)
    records = []
    checklist = []
    for index, user in enumerate(list(users.values())[:600]):
        for message in messages:
            data = DecisionInput(post=message.as_post(), profile=_primary_variant_profile(user),
                                 peer_context=PeerContext(), platform_context=PlatformContext(),
                                 time_step=index % 30, prompt_version=condition['prompt_version'])
            msg_hash, _ = bank.client_identity(data, request_condition)
            payload = _payload(historical=False)
            payload['cell'].update(cell_id='P0::'+bank.MODEL, requested_model=bank.MODEL,
                                   required_observed_model='gpt-5.6-sol')
            payload['pair'].update(user_id=user.user_id, message_id=message.message_id,
                                   pair_id=user.user_id+':'+message.message_id, time_step=index % 30)
            payload['new_attempts'][0].update(observed_model_counts={'gpt-5.6-sol': 1},
                provider_route='pi_openai_oauth_subscription', billing_currency=None,
                billing_semantics='subscription_quota_with_nominal_usd_reference',
                subscription_nominal_cost_usd=0.01)
            _rehash(payload)
            event = {'sequence': len(records), 'kind': 'judgment_persisted', 'payload': {'judgment': payload}}
            event['record_sha256'] = bank.fingerprint(event)
            records.append(event)
            checklist.append({'pair': payload['pair'], 'request_condition': condition,
                'rebuilt_client_input': {'client_messages_sha256': msg_hash, 'decision_input_sha256': data.cache_key()},
                'historical_judgment': {'judgment_id': payload['judgment_id'],
                    'origin': {'event_sequence': event['sequence'], 'event_checksum': event['record_sha256']}}})
    bank.write_jsonl(root/'ledger.jsonl', records)
    bank.write_jsonl(root/'judgment_evidence_checklist.jsonl', checklist)
    (root/'dummy.json').write_text('{}')
    audit.update(counts={'historical_judgments':1800, 'missing_pairs':1200,'eligible_pair_universe':3000,
                         'duplicate_pairs':0,'conflicting_pairs':0},
        lineage={k:{'path':str(root/'dummy.json'),'sha256':bank.file_hash(root/'dummy.json')}
                 for k in ('evidence','plan','source_bundle','source_manifest')},
        output_hashes={'judgment_evidence_checklist.jsonl':bank.file_hash(root/'judgment_evidence_checklist.jsonl')},
        frozen_identities={}, service_time_boundary={})
    audit['lineage']['ledger_prefix']={'path':str(root/'ledger.jsonl'),'sha256':bank.file_hash(root/'ledger.jsonl')}
    audit['lineage']['implementation_files']=[]
    audit_path=root/'audit.json'
    audit_path.write_text(json.dumps(audit))
    monkeypatch.setattr(bank,'AUDIT_SHA256',bank.file_hash(audit_path))
    return audit_path


def test_prepare_closes_fingerprints_and_origin_bank_through_study(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    from llm_abm_sim import _parameter_judgment_bank as bank

    audit = _synthetic_audit(tmp_path, monkeypatch)
    old = audit.read_bytes()
    output = tmp_path/'prepared'
    result = ConcurrentRobustnessStudy().prepare_parameter_study(audit, output)
    assert (result['accepted'],result['missing'],result['universe']) == (1800,1200,3000)
    assert result['provider_calls']==0 and result['client_time_invariance_checks']==90000
    assert not result['production_deploy_eligible']
    hashes=json.loads((output/'artifact-manifest.json').read_text())['sha256']
    assert all(bank.file_hash(output/name)==digest for name,digest in hashes.items())
    assert len((output/'accepted-bank.jsonl').read_text().splitlines())==1800
    assert len((output/'missing-pairs.jsonl').read_text().splitlines())==1200
    assert audit.read_bytes()==old
    with pytest.raises(ValueError,match='output must be a new'):
        ConcurrentRobustnessStudy().prepare_parameter_study(audit,output)


def test_prepare_rejects_visible_input_drift_before_publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from llm_abm_sim import _parameter_judgment_bank as bank

    audit = _synthetic_audit(tmp_path,monkeypatch)
    original = bank.build_engagement_prompt
    def changed(data):
        result = original(data)
        if data.time_step == 29:
            result = [*result, {'role':'user','content':'changed input'}]
        return result
    monkeypatch.setattr(bank,'build_engagement_prompt',changed)
    output=tmp_path/'rejected'
    with pytest.raises(ValueError,match='LLM-visible input changes'):
        ConcurrentRobustnessStudy().prepare_parameter_study(audit,output)
    assert not output.exists()


def test_collection_closes_once_without_resending_successes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    from llm_abm_sim.provider_accounting import ProviderResponseEnvelope

    audit = _synthetic_audit(tmp_path, monkeypatch)
    root=tmp_path/'prepared'
    study=ConcurrentRobustnessStudy()
    study.prepare_parameter_study(audit,root)
    class Client:
        external_provider_client = False
        calls = 0
        last_subscription_nominal_cost_usd = 0.01
        def create_response(self, messages, model, **kwargs):
            self.calls += 1
            assert model == 'gpt-5.6-sol'
            assert kwargs == {'reasoning_effort': 'low', 'output_token_ceiling': 256}
            return ProviderResponseEnvelope(decision_text=json.dumps({'engage': True, 'probability': 0.5,
                'action':'like','reason':'fixture','confidence':0.8}), observed_model='gpt-5.6-sol',
                observed_model_status='reported',usage_status='complete',input_tokens=10,output_tokens=5,
                total_tokens=15,cached_input_tokens=0)
    client=Client()
    result=study.collect_parameter_judgments(root,client=client)
    assert result['unique_pairs']==3000 and result['new_successes']==1200
    assert result['physical_requests']==1201 and client.calls==1201
    original=(root/'closed-bank.jsonl').read_bytes()
    assert study.collect_parameter_judgments(root,client=client)==result
    assert client.calls==1201 and (root/'closed-bank.jsonl').read_bytes()==original


@pytest.mark.parametrize('fault', ['unknown', 'wrong_model', 'missing_usage', 'retry_exhausted'])
def test_collection_stops_durably_and_never_resends_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
    import json

    from llm_abm_sim import _parameter_collection as collection
    from llm_abm_sim.decision import ProviderAttemptFailure, ProviderResponseProvenanceUnknown
    from llm_abm_sim.provider_accounting import ProviderResponseEnvelope

    monkeypatch.setattr(collection.time, 'sleep', lambda seconds: None)
    audit=_synthetic_audit(tmp_path,monkeypatch)
    root=tmp_path/'prepared'
    study=ConcurrentRobustnessStudy()
    study.prepare_parameter_study(audit,root)
    class Client:
        external_provider_client=False
        calls=0
        last_subscription_nominal_cost_usd=0.01
        def create_response(self,messages,model,**kwargs):
            self.calls+=1
            if self.calls>1:
                if fault=='unknown':
                    raise ProviderResponseProvenanceUnknown('sentinel never persisted')
                if fault=='retry_exhausted':
                    raise ProviderAttemptFailure(category='upstream_unavailable',retryable=True)
            kwargs={'decision_text':json.dumps({'engage':False,'probability':0.2,'confidence':0.8,'action':'ignore','reason':'fixture'}),
                'observed_model':'foreign' if self.calls>1 and fault=='wrong_model' else 'gpt-5.6-sol',
                'observed_model_status':'reported','usage_status':'complete','input_tokens':10,'output_tokens':5,'total_tokens':15,
                'cached_input_tokens':0}
            if self.calls>1 and fault=='missing_usage':
                kwargs.update(usage_status='missing',input_tokens=None,output_tokens=None,total_tokens=None,cached_input_tokens=None)
            return ProviderResponseEnvelope(**kwargs)
    client=Client()
    with pytest.raises(ValueError):
        study.collect_parameter_judgments(root,client=client)
    assert client.calls==(4 if fault=='retry_exhausted' else 2)
    calls=client.calls
    with pytest.raises(ValueError):
        study.collect_parameter_judgments(root,client=client)
    assert client.calls==calls
    assert not (root/'closed-bank.jsonl').exists()
    assert 'sentinel' not in (root/'collection/attempts.jsonl').read_text()


def test_collection_rejects_external_wrong_transport_before_any_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    audit=_synthetic_audit(tmp_path,monkeypatch)
    root=tmp_path/'prepared'
    study=ConcurrentRobustnessStudy()
    study.prepare_parameter_study(audit,root)
    monkeypatch.setenv('LLM_ABM_RUN_LIVE_LLM','1')
    class WrongTransport:
        external_provider_client=True
        def create_response(self,*args,**kwargs):
            pytest.fail('wrong transport must never dispatch')
    with pytest.raises(ValueError,match='exact approved Pi'):
        study.collect_parameter_judgments(root,client=WrongTransport())
    assert not (root/'collection').exists()


def test_collection_rejects_actual_pi_default_timeout_before_any_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from llm_abm_sim.providers.pi_subscription import PiSubscriptionProviderClient

    audit=_synthetic_audit(tmp_path,monkeypatch)
    root=tmp_path/'prepared'
    study=ConcurrentRobustnessStudy()
    study.prepare_parameter_study(audit,root)
    monkeypatch.setenv('LLM_ABM_RUN_LIVE_LLM','1')
    client=object.__new__(PiSubscriptionProviderClient)
    client.response_timeout_seconds=90.0
    with pytest.raises(ValueError,match='timeout/readiness'):
        study.collect_parameter_judgments(root,client=client)
    assert not (root/'collection').exists()


@pytest.mark.parametrize('name',['closed-bank.jsonl','collection/closure.json','collection/attempts.jsonl'])
def test_collection_rejects_symlink_outputs_without_altering_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,name: str) -> None:
    audit=_synthetic_audit(tmp_path,monkeypatch)
    root=tmp_path/'prepared'
    study=ConcurrentRobustnessStudy()
    study.prepare_parameter_study(audit,root)
    outside=tmp_path/'source-evidence'
    outside.write_text('immutable')
    link=root/name
    link.parent.mkdir(exist_ok=True)
    link.symlink_to(outside)
    class NeverClient:
        external_provider_client=False
        def create_response(self,*args,**kwargs):
            pytest.fail('must reject before dispatch')
    with pytest.raises(ValueError,match='non-symlink'):
        study.collect_parameter_judgments(root,client=NeverClient())
    assert outside.read_text()=='immutable'
