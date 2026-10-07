#!/usr/bin/env python3
"""Independent raw-cell acceptance; no production scheduler or realization helper imports."""
import json,hashlib,math,collections
from pathlib import Path
from llm_abm_sim import _parameter_judgment_bank as bank
from llm_abm_sim.concurrent_message_experiment import _prepare_concurrent_runtime_inputs,_message_user_fit_components,_primary_variant_profile
from llm_abm_sim.decision import DecisionInput,EngageDecision
from llm_abm_sim.prompting import build_engagement_prompt
from llm_abm_sim.prompt_contracts import CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY
from llm_abm_sim.schemas import PeerContext,PlatformContext
ROOT=Path(__file__).resolve().parents[1];ORIGINAL=Path('/Users/liuqingyuan/work/llm-abm-marketing-sim');OLD=ORIGINAL/'outputs/01a08bb3-1446-7f51-8933-cd49b50e9ccb/four-model-final-20260912-verified'
def main():
 prep=bank.read_json(ORIGINAL/'runs/gpt-p0-bank-topup-20260917-authorized-01/preparation.json');config,_,_=bank._inputs(bank.read_json(Path(prep['audit']['path'])));config=config.model_copy(update={'network_scope':'final_collected_topics'});p=_prepare_concurrent_runtime_inputs(config)
 degrees=collections.Counter();neighbors=collections.defaultdict(set)
 for (a,b),weight in p.cohort.comment_graph.edge_weights.items():
  assert a!=b and weight>0;degrees[a]+=weight;degrees[b]+=weight;neighbors[a].add(b);neighbors[b].add(a)
 eligible=sorted(degrees.get(u,0) for u in p.cohort.users_by_id);position=.95*(len(eligible)-1);lo=math.floor(position);p95=eligible[lo]+(eligible[math.ceil(position)]-eligible[lo])*(position-lo);assert p95==p.cohort.comment_graph.p95_weighted_degree==5
 assert len(p.cohort.users_by_id)==36400 and len(p.cohort.sample_user_ids)==1000
 for u in p.cohort.users_by_id:
  assert degrees.get(u,0)==p.cohort.comment_graph.weighted_degree_by_user.get(u,0)
  assert neighbors.get(u,set())==p.neighbors_by_user.get(u,set())
  assert p.base_network_by_user[u]==min(1,math.log1p(degrees.get(u,0))/math.log1p(p95))
 accepted=next(r for r in bank.read_json(ROOT.parent/'ten-topic-gpt-studies-20261006/preflight-final/samples.json') if r['arm']=='baseline');assert set(accepted['sample_user_ids'])==set(p.cohort.sample_user_ids)
 ledger=[json.loads(x) for x in (ROOT/'request-ledger.jsonl').read_text().splitlines()];intents={r['request_id']:r for r in ledger if r['type']=='intent'};success={r['request_id']:r for r in ledger if r['type']=='succeeded'};responses={r['request_id']:r['response'] for r in ledger if r['type']=='response'}
 old={r['judgment_id']:r for r in [json.loads(x) for x in (OLD/'judgments.jsonl').read_text().splitlines()]};eligible_old={json.loads(x)['judgment_id'] for x in (ROOT/'protocol/eligible-old-judgment-origins.jsonl').read_text().splitlines()}
 fresh=ROOT.parent/'ten-topic-gpt-studies-20261006/final-bank';condition=bank.read_json(fresh/'preparation.json')['request_condition'];fresh_rows=[json.loads(x) for x in (fresh/'closed-bank.jsonl').read_text().splitlines()];fresh_index={(r['user_id'],r['message_id'],r['client_condition_sha256']):r for r in fresh_rows}
 result=[];out=ROOT/'independent-acceptance';out.mkdir(exist_ok=True)
 for path in sorted((ROOT/'formal-paths').glob('*.json')):
  cell=bank.read_json(path);model=cell['cell_id'].split('::',1)[1];template=cell['cell_id'].split('::')[0];token=CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.resolve(template).prompt_version
  assert set(cell['sample_user_ids'])==set(p.cohort.sample_user_ids) and set(cell['seed_user_ids'])==set(p.cohort.seed_user_ids)
  assert cell['behavior_seed']==20260823 and cell['realization_source_identity']==bank.read_json(ROOT/'protocol/DRAW_PROOF.json')['source_identity']
  exposed={m.message_id:set() for m in config.messages};positive=set();cursor=0;summary=collections.defaultdict(collections.Counter);rows=[]
  for step in range(30):
   frozen=set(positive);committed=set()
   for m in config.messages:
    ranked=[]
    for u in p.cohort.sample_user_ids:
     if u in exposed[m.message_id]:continue
     n=len(neighbors.get(u,set())&frozen);score=.5*min(1,math.log1p(degrees.get(u,0))/math.log1p(p95))+.3*min(1,n/3)+.2*_message_user_fit_components(m,p.cohort.users_by_id[u])[1];ranked.append((u,score,n))
    ranked.sort(key=lambda x:(-x[1],x[0]));seeds=set(p.cohort.seed_user_ids);chosen=([x for x in ranked if x[0] in seeds]+[x for x in ranked if x[0] not in seeds][:20-len(seeds)]) if step==0 else ranked[:20];assert len(chosen)==20
    for u,score,n in chosen:
     r=cell['terminals'][cursor];assert (r['user_id'],r['message_id'],r['time_step'])==(u,m.message_id,step);assert r['ranking_score']==score and r['engaged_neighbor_count']==n
     assert r['selection_reason']==(('seed_union' if u in seeds else 'personalized_topup') if step==0 else 'personalized_top20')
     data=DecisionInput(post=m.as_post(),profile=_primary_variant_profile(p.cohort.users_by_id[u]),peer_context=PeerContext(),platform_context=PlatformContext(),time_step=step,prompt_version=token);messages=build_engagement_prompt(data);mh=bank.fingerprint(messages)
     if 'judgment' not in r:
      ch=bank.client_identity(data,condition)[1];entry=fresh_index[u,m.message_id,ch];assert entry['client_messages_sha256']==mh;assert entry['source']==r['bank_source'];decision=entry['decision']
     else:
      decision=r['judgment'];source=r['judgment_source'];assert r['client_messages_sha256']==mh
      if source['type']=='reused_four_model':
       j=old[source['judgment_id']];assert j['judgment_id'] in eligible_old;assert j['user_id']==u and j['message_id']==m.message_id and j['prompt_variant']==template
       assert all(decision[a]==j[b] for a,b in [('engage','provider_engage'),('probability','provider_probability'),('action','provider_action'),('reason','provider_reason'),('confidence','provider_confidence')])
      else:
       identity=source['request_id'];request=intents[identity];assert identity in responses and identity in success;assert success[identity]['decision']==decision;assert request['full_client_messages']==messages and request['model']==model and request['template']==template
       assert responses[identity]['observed_model']==('gpt-5.6-sol' if model=='openai-codex/gpt-5.6-sol' else 'gemini-pro-agent' if model=='gemini-3.1-pro' else model)
     EngageDecision.model_validate(decision);key=hashlib.sha256(b'\0'.join(x.encode() for x in [cell['realization_source_identity'],u,m.message_id])).hexdigest();draw=(int.from_bytes(hashlib.sha256(('20260823\0'+key).encode()).digest()[:8],'big')>>11)/9007199254740992 if decision['engage'] else None;good=draw is not None and draw<decision['probability'];action=decision['action'] if good else 'ignore'
     assert r['realization_key']==key and r['uniform_draw']==draw and r['realized_engage']==good and r['realized_action']==action;assert r['realization_status']==('draw_pass' if good else 'draw_fail' if decision['engage'] else 'provider_ignore')
     assert u not in exposed[m.message_id];exposed[m.message_id].add(u)
     if good:committed.add(u)
     segment={'class_1':'S1','class_2':'S2','class_3':'S3'}[p.cohort.users_by_id[u].latent_attributes['latent_class']]
     summary[m.message_id][action]+=1;rows.append({'model':model,'template':template,'user_id':u,'message_id':m.message_id,'segment':segment,'batch':step,'provider_engage':decision['engage'],'provider_probability':decision['probability'],'provider_confidence':decision['confidence'],'provider_action':decision['action'],'realized_engage':good,'realized_action':action});cursor+=1
   positive.update(committed);assert cell['barriers'][step]=={'time_step':step,'exposure_count':60,'frozen_positive_user_ids':sorted(frozen),'committed_positive_user_ids':sorted(committed),'campaign_positive_user_count':len(positive)}
  assert cursor==1800 and len(cell['barriers'])==30 and all(len(s)==600 for s in exposed.values())
  fact={'status':'passed_this_cell','cell_id':cell['cell_id'],'path':str(path),'sha256':bank.file_hash(path),'exposures':1800,'barriers':30,'message_statistics':{k:dict(v) for k,v in summary.items()},'provider_calls_during_acceptance':0,'shared_components':'cohort builder, P0-P3 renderer and message-fit; raw edge-derived degree/neighbors/P95, ranking, draws, barriers and stats independently implemented'}
  normalized=out/(path.stem+'-normalized.jsonl');bank.write_jsonl(normalized,rows);fact.update(normalized_path=str(normalized),normalized_sha256=bank.file_hash(normalized));bank.write_json(out/(path.stem+'-acceptance.json'),fact);result.append(fact)
 bank.write_json(out/'ACCEPTANCE_PROGRESS.json',{'status':'all_16_cells_verified' if len(result)==16 else 'partial_verified_completed_cells_only','required_conditions':16,'verified_conditions':len(result),'verified_exposures':1800*len(result),'verified_barriers':30*len(result),'p95':p95,'source_graph_edges':len(p.cohort.comment_graph.edge_weights),'source_graph_weight':sum(p.cohort.comment_graph.edge_weights.values()),'cells':result,'provider_calls':0})
 print('PASS completed_cells='+str(len(result))+' exposures='+str(1800*len(result))+' provider_calls=0')
if __name__=='__main__':main()
