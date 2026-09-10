"""Explicit same-task quota retry; all transports below are offline."""
import pytest
from llm_abm_sim._concurrent_recovery_campaign import CampaignJournal, RecoveryCampaignError, recovery_scope
from llm_abm_sim._concurrent_recovery_progress import CampaignProgress
from tests.unit.test_concurrent_recovery_parallel_progress import start, proposal, intent, settlement, attempt
from tests.unit.test_concurrent_recovery_progress import _journal

def stopped(journal):
    state, decision = start(journal)
    for p in range(1,5):
        state.append(journal,'parallel_attempt_intent',intent(p))
    for p in range(1,5):
        row=attempt(1, outcome='nonretryable_failure',no_response=True) if p<3 else attempt()
        if p<3: row['failure_category']='quota_exhausted'
        state.append(journal,'parallel_attempt_settled',settlement(p, None if p<3 else decision,row))
    return state,decision

def acceptance(state):
    from llm_abm_sim._concurrent_recovery_quota_retry import terms
    return {'approval':{'path':'/fixture/quota.json','sha256':'f'*64},'failed_attempts':terms(state)}

def test_quota_retry_is_one_single_formal_attempt_preserving_budget_and_successes(tmp_path):
    identity=_journal(tmp_path)
    with recovery_scope(identity):
        journal=CampaignJournal.open(identity);state,decision=stopped(journal)
        payload=acceptance(state)
        state.append(journal,'quota_retry_accepted',payload)
        assert state.status=='paused' and state.physical_attempts==4
        state=CampaignProgress.replay(proposal(),CampaignJournal.read(identity))
        assert state.quota_retry_pending==(4,1) and set(state.success_decisions)=={(4,3),(4,4)}
        state.append(journal,'invocation_started',{'epoch_identity_sha256':'e'*64,'ordinal':2})
        with pytest.raises(RecoveryCampaignError):state.append(journal,'parallel_attempt_intent',intent(2,2))
        state.append(journal,'parallel_attempt_intent',intent(1,2))
        state.append(journal,'parallel_attempt_settled',settlement(1,decision,attempt(2)))
        assert state.quota_retry_pending is None and state.status=='running'
        state.append(journal,'parallel_attempt_intent',intent(2,2))
        state.append(journal,'parallel_attempt_settled',settlement(2,decision,attempt(2)))
        assert state.physical_attempts==6 and len(state.attempts((4,1)))==2
        assert state.attempts((4,1))[0].failure_category=='quota_exhausted'
        with pytest.raises(RecoveryCampaignError):state.append(journal,'quota_retry_accepted',payload)

@pytest.mark.parametrize('category',['quota_exhausted','timeout'])
def test_trial_failure_is_terminal_without_automatic_retry(tmp_path,category):
    identity=_journal(tmp_path)
    with recovery_scope(identity):
        j=CampaignJournal.open(identity);s,d=stopped(j);s.append(j,'quota_retry_accepted',acceptance(s))
        s.append(j,'invocation_started',{'epoch_identity_sha256':'e'*64,'ordinal':2})
        s.append(j,'parallel_attempt_intent',intent(1,2))
        row=attempt(2,outcome='retryable_failure' if category=='timeout' else 'nonretryable_failure',no_response=True)
        row['failure_category']=category
        s.append(j,'parallel_attempt_settled',settlement(1,None,row))
        assert s.status=='stopped' and not s.has_inflight and s.physical_attempts==5
        with pytest.raises(RecoveryCampaignError):s.append(j,'parallel_attempt_intent',intent(1,3))

@pytest.mark.parametrize('change',['unknown','revoked','identity','exhausted','crossed','budget'])
def test_other_hard_stops_and_exhausted_or_crossed_history_are_not_released(tmp_path,change):
    identity=_journal(tmp_path)
    with recovery_scope(identity):
        j=CampaignJournal.open(identity);s,d=stopped(j)
        payload=acceptance(s)
        if change=='unknown':s.parallel_unknown.add((4,1))
        elif change=='revoked':s.task_revoked=True
        elif change=='identity':s.new_attempts[(4,1)][0]=s.new_attempts[(4,1)][0].model_copy(update={'failure_category':'identity_mismatch'})
        elif change=='exhausted':s.new_attempts[(4,1)]*=3
        elif change=='budget':s.physical_attempts=s.proposal['maximum_new_physical_attempts']
        else:payload['failed_attempts']=payload['failed_attempts'][:1]
        head=j.head
        with pytest.raises(RecoveryCampaignError):s.append(j,'quota_retry_accepted',payload)
        assert j.head==head

@pytest.mark.parametrize('trial_failure',[True,False])
def test_real_worker_seam_trial_is_single_and_failure_never_retries(tmp_path,trial_failure):
    import threading
    import time
    from llm_abm_sim import _concurrent_recovery_parallel_runtime as runtime
    from llm_abm_sim import concurrent_robustness_operator as operator
    from llm_abm_sim import concurrent_robustness_v2 as v2
    from llm_abm_sim.concurrent_message_experiment import _VariantDecisionContext
    from llm_abm_sim.providers.robustness import ProviderAttemptFailure
    from tests.unit.test_concurrent_robustness_operator import _Transport
    from tests.unit.test_robustness_provider_adapters import _context
    from tests.unit.test_concurrent_recovery_parallel_progress import batch
    lock=threading.Lock(); barrier=threading.Barrier(4)
    count=0; phase='initial'; trial_done=False
    class Transport(_Transport):
        def create_response(self,*args,**kwargs):
            nonlocal count,trial_done
            with lock:
                count+=1; number=count
                if phase=='trial':assert number==1 or trial_done
            if phase=='initial':barrier.wait(timeout=5)
            if number==1 and (phase=='initial' or trial_failure):
                raise ProviderAttemptFailure(category='quota_exhausted',retryable=False)
            time.sleep(.01)
            result=super().create_response(*args,**kwargs)
            if phase=='trial' and number==1:trial_done=True
            return result
    cell=v2._PromptModelCell.model_validate(proposal()['frozen_context']['prompt_model_cells'][4])
    pool=runtime.ParallelAdapterPool(tuple(operator._adapter_for_cell(cell,Transport('gemini',{})) for _ in range(4)))
    data=_context()
    context=_VariantDecisionContext(decision_variant='primary',prompt_token=cell.prompt_version,
        **{k:data[k] for k in ('post','profile','peer_context','platform_context')})
    work=tuple(runtime.FrozenWork(row['coordinates'],context) for row in batch()['pairs'])
    identity=_journal(tmp_path)
    with recovery_scope(identity):
        j=CampaignJournal.open(identity);s,d=start(j,reserve=False)
        with pytest.raises(v2._V2CellStopped):
            runtime.run_frozen_batch(state=s,journal=j,pool=pool,work=work,check_dispatch_window=lambda:None,backoff_seconds=.01)
        assert count==4 and not s.has_inflight and len(s.success_decisions)==3
        s.append(j,'quota_retry_accepted',acceptance(s))
        s=CampaignProgress.replay(proposal(),CampaignJournal.read(identity))
        s.append(j,'invocation_started',{'epoch_identity_sha256':'e'*64,'ordinal':2})
        phase='trial';count=0
        def run():runtime.run_frozen_batch(state=s,journal=j,pool=pool,work=work,check_dispatch_window=lambda:None,backoff_seconds=.01)
        if trial_failure:
            with pytest.raises(v2._V2CellStopped):run()
            assert count==1 and s.physical_attempts==5 and s.status=='stopped'
        else:
            run();assert count==57 and s.physical_attempts==61 and len(s.success_decisions)==60
        assert not s.has_inflight

def test_quota_judgment_has_explicit_v2_schema_and_v1_remains_strict():
    from copy import deepcopy
    from llm_abm_sim._concurrent_recovery_judgment import RecoveryJudgmentV1
    from tests.unit.test_concurrent_recovery_judgment import _payload,_rehash
    raw=_payload(historical=False)
    raw['cell_index']=4
    raw['cell']=proposal()['frozen_context']['prompt_model_cells'][4]
    fail=attempt(1,outcome='nonretryable_failure',no_response=True);fail['failure_category']='quota_exhausted'
    raw['new_attempts']=[fail,attempt(2)]
    for a in raw['new_attempts']:
        a.update(provider_route='antigravity_openai_compatible_gateway',billing_semantics='gateway_quota_usage',billing_currency=None)
    _rehash(raw)
    with pytest.raises(ValueError):RecoveryJudgmentV1.model_validate(raw)
    raw['schema_version']='concurrent-recovery-provider-judgment-v2'
    raw['quota_retry_approval']={'path':'/fixture/approval.json','sha256':'f'*64}
    _rehash(raw)
    saved=deepcopy(raw)
    read=RecoveryJudgmentV1.model_validate(raw)
    assert read.model_dump(mode='json')==saved
    assert read.new_attempts[0].outcome=='nonretryable_failure'
    for category in ['identity_mismatch','usage_evidence','timeout']:
        bad=deepcopy(raw);bad['new_attempts'][0]['failure_category']=category;_rehash(bad)
        with pytest.raises(ValueError):RecoveryJudgmentV1.model_validate(bad)
    legacy=_payload();assert RecoveryJudgmentV1.model_validate(legacy).model_dump(mode='json')==legacy
