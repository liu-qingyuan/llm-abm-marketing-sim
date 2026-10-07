#!/usr/bin/env python3
"""Fresh raw-data graph/sampler and independent JSON response corroboration; no Provider."""
import json,hashlib,importlib.util,math,collections
from pathlib import Path
from llm_abm_sim import _parameter_judgment_bank as bank
from llm_abm_sim.concurrent_message_experiment import _prepare_concurrent_runtime_inputs
ROOT=Path(__file__).resolve().parents[1];W=ROOT.parents[1];O=Path('/Users/liuqingyuan/work/llm-abm-marketing-sim')

def main():
 raw=(ROOT/'request-ledger.jsonl').read_bytes();events=[json.loads(x) for x in raw.splitlines()];responses={e['request_id']:e['response'] for e in events if e['type']=='response'};success={e['request_id']:e for e in events if e['type']=='succeeded'};checked=0
 for rid,e in success.items():
  decoded=json.loads(responses[rid]['decision_text']);assert isinstance(decoded,dict)
  assert all(k in decoded for k in ['engage','probability','action','reason','confidence'])
  assert type(decoded['engage']) is bool and decoded['action'] in ['like','comment','share','ignore']
  for k in ['probability','confidence']:assert type(decoded[k]) in [int,float] and math.isfinite(decoded[k]) and 0<=decoded[k]<=1
  assert isinstance(decoded['reason'],str)
  assert decoded['engage']==(decoded['action']!='ignore')
  assert all(decoded[k]==e['decision'][k] for k in ['engage','probability','action','reason','confidence']);checked+=1
 # Reuse a previous independently written acceptance raw-CSV algorithm, not the ABM builder.
 independent=W/'runs/ten-topic-gpt-final-acceptance-20261007/audit.py';spec=importlib.util.spec_from_file_location('raw_data_independent',independent);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 original=bank.read_json(O/'runs/gpt-p0-bank-topup-20260917-authorized-01/preparation.json');cfg,legacy,_=bank._inputs(bank.read_json(Path(original['audit']['path'])));cfg=cfg.model_copy(update={'network_scope':'final_collected_topics'});p=_prepare_concurrent_runtime_inputs(cfg)
 vids,comments,edges,degrees,neighbors,counts,likes,p95=module.raw_graph(cfg.dataset_dir,cfg.sample_holdout_video_id,list(legacy.cohort.users_by_id))
 assert dict(edges)==p.cohort.comment_graph.edge_weights and p95==5 and len(edges)==39779 and sum(edges.values())==52587
 mainmanifest=bank.read_json(W/'runs/ten-topic-full-pool-20261006/main/manifest.json')
 graph=module.fp({'scope':mainmanifest['network']['policy'],'holdout':cfg.sample_holdout_video_id,'edges':[[a,b,w] for (a,b),w in sorted(edges.items())],'degrees':sorted(degrees.items()),'neighbors':[[u,sorted(n)] for u,n in sorted(neighbors.items())],'p95':p95});assert graph==mainmanifest['network']['graph_identity']
 for u in p.cohort.users_by_id:assert degrees.get(u,0)==p.cohort.comment_graph.weighted_degree_by_user.get(u,0) and neighbors.get(u,set())==p.neighbors_by_user.get(u,set())
 histvids={u:v for u,v in vids.items() if u!=cfg.sample_holdout_video_id};sample,seeds=module.sample(legacy.cohort.users_by_id,histvids,comments,edges,neighbors,cfg.random_seed);assert set(sample)==set(p.cohort.sample_user_ids) and set(seeds)==set(p.cohort.seed_user_ids)
 topics=sorted({r['source_challenge_name'] for r in vids.values()});assert len(topics)==10 and len(vids)==4212 and len(histvids)==4211 and len(comments)==50604
 finaldataset=Path(mainmanifest['final_dataset']);lineage=[]
 for name in ['videos.csv','all_comments.csv']:
  a=cfg.dataset_dir/name;b=finaldataset/name;sha=hashlib.sha256(a.read_bytes()).hexdigest();assert sha==hashlib.sha256(b.read_bytes()).hexdigest();lineage.append({'name':name,'current_derivative_path':str(a),'final_actual_dataset_path':str(b),'sha256_equal':sha})
 result={'status':'pass_fresh_raw_corroboration','real_success_response_json_checked':checked,'source_ledger_sha256':hashlib.sha256(raw).hexdigest(),'raw_graph_identity':graph,'p95':p95,'eligible_population':len(p.cohort.users_by_id),'edges':len(edges),'total_edge_weight':sum(edges.values()),'actual_ten_topic_names':topics,'final_dataset_lineage':lineage,'holdout_excluded':cfg.sample_holdout_video_id,'history_comments':len(comments),'history_videos':len(histvids),'sample_rebuilt_independently':1000,'seeds':len(seeds),'shared_components':'user traits/cohort preparation only for comparison; raw graph/sampler reused previous independent acceptance source, not production graph/sampler; std JSON reparse uses no production decision parser','independent_raw_algorithm_path':str(independent),'independent_raw_algorithm_sha256':hashlib.sha256(independent.read_bytes()).hexdigest(),'provider_calls':0}
 (ROOT/'FINAL_CORROBORATION.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print('PASS corroboration response_json='+str(checked)+' raw_graph='+graph+' sample=1000 provider_calls=0')
if __name__=='__main__':main()
