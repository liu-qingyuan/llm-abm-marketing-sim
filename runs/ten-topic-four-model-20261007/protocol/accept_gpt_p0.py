#!/usr/bin/env python3
"""Independent ordering/barrier/draw implementation; shared cohort and prompt renderer only."""
import json,hashlib,collections
from pathlib import Path
from llm_abm_sim import _parameter_judgment_bank as bank
from llm_abm_sim.concurrent_message_experiment import _prepare_concurrent_runtime_inputs,_message_user_fit_components,_primary_variant_profile
from llm_abm_sim.decision import DecisionInput
from llm_abm_sim.schemas import PeerContext,PlatformContext
ROOT=Path(__file__).resolve().parents[1]
ORIGINAL=Path('/Users/liuqingyuan/work/llm-abm-marketing-sim')
def main():
 path=ROOT/'formal-paths/P0--gpt-5.6-sol.json';result=bank.read_json(path)
 assert bank.file_hash(Path(result['bank_path']))==result['bank_sha256']
 old=bank.read_json(ORIGINAL/'runs/gpt-p0-bank-topup-20260917-authorized-01/preparation.json')
 config,_,_=bank._inputs(bank.read_json(Path(old['audit']['path'])))
 config=config.model_copy(update={'network_scope':'final_collected_topics'});p=_prepare_concurrent_runtime_inputs(config)
 assert set(result['sample_user_ids'])==set(p.cohort.sample_user_ids) and set(result['seed_user_ids'])==set(p.cohort.seed_user_ids)
 records=[json.loads(x) for x in Path(result['bank_path']).read_text().splitlines()]
 indexed={(r['user_id'],r['message_id'],r['client_condition_sha256']):r for r in records}
 exposed={m.message_id:set() for m in config.messages};positive=set();cursor=0;stats=collections.defaultdict(collections.Counter);curves=[]
 for step in range(30):
  frozen=set(positive);committed=set()
  for m in config.messages:
   ranked=[]
   for u in p.cohort.sample_user_ids:
    if u in exposed[m.message_id]:continue
    n=len(p.neighbors_by_user.get(u,set())&frozen)
    score=.5*p.base_network_by_user.get(u,0)+.3*min(1,n/3)+.2*_message_user_fit_components(m,p.cohort.users_by_id[u])[1]
    ranked.append((u,score,n))
   ranked.sort(key=lambda x:(-x[1],x[0]));seeds=set(p.cohort.seed_user_ids)
   chosen=([x for x in ranked if x[0] in seeds]+[x for x in ranked if x[0] not in seeds][:20-len(seeds)]) if step==0 else ranked[:20]
   assert len(chosen)==20
   for u,score,n in chosen:
    r=result['terminals'][cursor];assert (r['user_id'],r['message_id'],r['time_step'])==(u,m.message_id,step)
    assert r['ranking_score']==score and r['engaged_neighbor_count']==n
    expected_reason=('seed_union' if u in seeds else 'personalized_topup') if step==0 else 'personalized_top20'
    assert r['selection_reason']==expected_reason
    data=DecisionInput(post=m.as_post(),profile=_primary_variant_profile(p.cohort.users_by_id[u]),peer_context=PeerContext(),platform_context=PlatformContext(),time_step=step,prompt_version=result['request_condition']['prompt_version'])
    mh,ch=bank.client_identity(data,result['request_condition']);entry=indexed[u,m.message_id,ch]
    assert entry['client_messages_sha256']==mh and entry['source']==r['bank_source']
    assert r['client_condition_sha256']==ch
    decision=entry['decision'];key=hashlib.sha256(b'\0'.join(x.encode() for x in [result['realization_source_identity'],u,m.message_id])).hexdigest()
    draw=(int.from_bytes(hashlib.sha256(('20260823\0'+key).encode()).digest()[:8],'big')>>11)/9007199254740992 if decision['engage'] else None
    good=draw is not None and draw<decision['probability'];action=decision['action'] if good else 'ignore'
    assert r['realization_key']==key and r['uniform_draw']==draw and r['realized_engage']==good and r['realized_action']==action
    assert r['realization_status']==('draw_pass' if good else 'draw_fail' if decision['engage'] else 'provider_ignore')
    assert u not in exposed[m.message_id];exposed[m.message_id].add(u)
    if good:committed.add(u)
    stats[m.message_id][action]+=1;cursor+=1
  positive.update(committed)
  assert result['barriers'][step]=={'time_step':step,'exposure_count':60,'frozen_positive_user_ids':sorted(frozen),'committed_positive_user_ids':sorted(committed),'campaign_positive_user_count':len(positive)}
  curves.append({'batch':step, 'campaign_positive_users':len(positive),'messages':{k:dict(v) for k,v in stats.items()}})
 assert cursor==1800 and len(result['barriers'])==30 and all(len(s)==600 for s in exposed.values())
 proof={'status':'passed_this_cell_only','cell':'GPT/P0','formal_path':str(path),'formal_path_sha256':bank.file_hash(path),'exposures':cursor,'barriers':30,'message_stats':{k:dict(v) for k,v in stats.items()},'curves':curves,'provider_calls_during_acceptance':0,'shared_components':'cohort builder, profile-to-prompt renderer, message fit calculation; ordering, exposure dedup, barrier, draw and action reconstruction independently implemented','other_15_conditions':'not completed'}
 bank.write_json(ROOT/'protocol/GPT_P0_ACCEPTANCE.json',proof)
 print('PASS GPT/P0 exposures=1800 barriers=30 new_calls=0')
if __name__=='__main__':main()
