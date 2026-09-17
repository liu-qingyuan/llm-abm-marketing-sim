from pathlib import Path
from typing import Any

import pytest

from llm_abm_sim.concurrent_robustness_study import ConcurrentRobustnessStudy


def test_path_study_requires_closed_bank_without_creating_output(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='closed bank'):
        ConcurrentRobustnessStudy().run_parameter_study(tmp_path/'unclosed', tmp_path/'paths', maximum_paths=1)
    assert not (tmp_path/'paths').exists()


def test_study_executes_and_resumes_real_dynamic_paths_without_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    from llm_abm_sim import _parameter_judgment_bank as bank
    from llm_abm_sim import _parameter_study as paths
    from llm_abm_sim.provider_accounting import ProviderResponseEnvelope
    from tests.unit.test_parameter_judgment_bank import _synthetic_audit

    audit=_synthetic_audit(tmp_path,monkeypatch)
    original=bank._inputs
    def prepared_inputs(document):
        config,prepared,closure=original(document)
        config.delivery_capacity=20
        prepared.cohort.seed_user_ids=list(prepared.cohort.sample_user_ids[:20])
        prepared.base_network_by_user={u:i/1000 for i,u in enumerate(prepared.cohort.sample_user_ids)}
        prepared.neighbors_by_user={u:{f'u{(i+1)%1000:04}'} for i,u in enumerate(prepared.cohort.sample_user_ids)}
        return config,prepared,closure
    monkeypatch.setattr(bank,'_inputs',prepared_inputs)
    root=tmp_path/'bank'
    study=ConcurrentRobustnessStudy()
    study.prepare_parameter_study(audit,root)
    class Client:
        external_provider_client=False
        last_subscription_nominal_cost_usd=0.01
        def create_response(self,*args,**kwargs):
            return ProviderResponseEnvelope(decision_text=json.dumps({'engage':True,'probability':0.5,'confidence':0.8,
                'action':'like','reason':'fixture'}),observed_model='gpt-5.6-sol',observed_model_status='reported',
                usage_status='complete',input_tokens=10,output_tokens=5,total_tokens=15,cached_input_tokens=0)
    study.collect_parameter_judgments(root,client=Client())
    output=tmp_path/'paths'
    result=study.run_parameter_study(root,output,maximum_paths=1)
    assert result=={'status':'partial','completed_paths':1,'new_paths':1,'provider_calls':0}
    first=output/f'w0-h1-s{paths.SEEDS[0]}.json'
    original_bytes=first.read_bytes()
    doc=json.loads(original_bytes)['path']
    assert len(doc['terminals'])==1800 and len(doc['barriers'])==30
    assert len({(r['user_id'],r['message_id']) for r in doc['terminals']})==1800
    assert all(b['exposure_count']==60 for b in doc['barriers'])
    assert doc['barriers'][0]['frozen_positive_user_ids']==[]
    assert set(doc['barriers'][1]['frozen_positive_user_ids'])==set(doc['barriers'][0]['committed_positive_user_ids'])
    result=study.run_parameter_study(root,output,maximum_paths=1)
    assert result['completed_paths']==2 and first.read_bytes()==original_bytes
    second=json.loads((output/f'w0-h1-s{paths.SEEDS[1]}.json').read_text())['path']
    assert second!=doc
    closure_path=root/'collection/closure.json'
    original_closure=closure_path.read_bytes()
    for field in ('known_nominal_cost_usd','physical_requests'):
        changed=json.loads(original_closure)
        changed[field]+=1
        closure_path.write_text(json.dumps(changed))
        with pytest.raises(ValueError,match='independently recomputed ledger'):
            study.report_parameter_study(root,output)
        closure_path.write_bytes(original_closure)
    assert not (output/'report').exists()
    first.write_bytes(b'{}')
    with pytest.raises((ValueError,KeyError)):
        study.run_parameter_study(root,output,maximum_paths=1)


def test_kernel_parameters_change_future_exposure_with_committed_feedback() -> None:
    from types import SimpleNamespace

    from llm_abm_sim.concurrent_message_experiment import _ConcurrentRuntimeKernel, _message_user_fit_components
    from tests.unit.test_concurrent_message_experiment import _message, _research_user

    users={f'u{i}':_research_user(f'u{i}',environmental=1.0) for i in range(5)}
    message=_message('message_1',environmental=1.0)
    config: Any=SimpleNamespace(messages=[message],horizon=2,delivery_capacity=1)
    prepared: Any=SimpleNamespace(cohort=SimpleNamespace(users_by_id=users,sample_user_ids=list(users),seed_user_ids=['u0']),
        base_network_by_user={'u0':1.,'u1':.4,'u2':.8,'u3':.1,'u4':0.},
        neighbors_by_user={'u1':{'u0'}})
    fits={'message_1':{u:_message_user_fit_components(message,user) for u,user in users.items()}}
    def resolve(user,message,step):
        return {'realized_engage':True,'realized_action':'like'}
    results=[]
    for h in [1,6]:
        result=_ConcurrentRuntimeKernel.fixed_judgment_path(config=config,prepared=prepared,weights=(.5,.3,.2),
            neighbor_saturation=h,message_fits=fits,resolve=resolve)
        results.append([r['user_id'] for r in result['terminals']])
    assert results==[['u0','u1'],['u0','u2']]
    assert prepared.cohort.sample_user_ids==list(users)


def test_parameter_draw_is_explicit_seed_pair_identity() -> None:
    import hashlib
    import json

    from llm_abm_sim._parameter_study import RULE, draw

    payload=json.dumps([RULE,'b'*64,2026091700,'u1','message_1'],ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    expected=(int.from_bytes(hashlib.sha256(payload).digest(),'big') >> (256-53))/2**53
    assert draw('b'*64,2026091700,'u1','message_1')==expected
    assert draw('b'*64,2026091701,'u1','message_1')!=expected


def test_t_intervals_match_reference_quantile_and_paired_constant_effect() -> None:
    from llm_abm_sim._parameter_evidence import _estimate, t_quantile

    assert t_quantile(.975,99)==pytest.approx(1.9842169515,abs=1e-8)
    assert t_quantile(1-.05/(2*123),99)==pytest.approx(3.6601697394,abs=1e-8)
    result=_estimate([.01]*100,t_quantile(.975))
    assert result['lower']==result['upper']==.01 and result['mcse']==0
