#!/usr/bin/env python3
"""One formal zero-new-judgment cell, using four-model (not sensitivity) draws."""
import json,hashlib
from pathlib import Path
from llm_abm_sim import _parameter_judgment_bank as bank
from llm_abm_sim.concurrent_message_experiment import _prepare_concurrent_runtime_inputs,_primary_variant_profile,_ConcurrentRuntimeKernel,_message_user_fit_components
from llm_abm_sim.decision import DecisionInput,EngageDecision
from llm_abm_sim.schemas import PeerContext,PlatformContext
from llm_abm_sim.engagement_realization import EngagementRealizationPolicy
ROOT=Path(__file__).resolve().parents[1]
ORIGINAL=Path('/Users/liuqingyuan/work/llm-abm-marketing-sim')
def main():
 output=ROOT/'formal-paths/P0--gpt-5.6-sol.json'
 if output.exists():raise ValueError('existing formal cell must be independently accepted, not overwritten')
 old=bank.read_json(ORIGINAL/'runs/gpt-p0-bank-topup-20260917-authorized-01/preparation.json')
 fresh=ROOT.parent/'ten-topic-gpt-studies-20261006/final-bank'
 preparation=bank.read_json(fresh/'preparation.json');condition=preparation['request_condition']
 assert old['request_condition']==condition
 config,_,_=bank._inputs(bank.read_json(Path(old['audit']['path'])))
 config=config.model_copy(update={'network_scope':'final_collected_topics'})
 prepared=_prepare_concurrent_runtime_inputs(config)
 accepted=next(r for r in bank.read_json(ROOT.parent/'ten-topic-gpt-studies-20261006/preflight-final/samples.json') if r['arm']=='baseline')
 assert set(prepared.cohort.sample_user_ids)==set(accepted['sample_user_ids'])
 assert set(prepared.cohort.seed_user_ids)==set(accepted['seed_user_ids'])
 assert config.horizon==30 and config.delivery_capacity==20 and len(config.messages)==3
 records=[json.loads(x) for x in (fresh/'closed-bank.jsonl').read_text().splitlines()]
 index={(r['user_id'],r['message_id'],r['client_condition_sha256']):r for r in records}
 entries={}
 for u in prepared.cohort.sample_user_ids:
  for m in config.messages:
   data=DecisionInput(post=m.as_post(),profile=_primary_variant_profile(prepared.cohort.users_by_id[u]),peer_context=PeerContext(),platform_context=PlatformContext(),time_step=0,prompt_version=condition['prompt_version'])
   mh,ch=bank.client_identity(data,condition);r=index[u,m.message_id,ch];assert r['client_messages_sha256']==mh
   EngageDecision.model_validate(r['decision']);entries[u,m.message_id]=r
 assert len(entries)==3000
 proof=bank.read_json(ROOT/'protocol/DRAW_PROOF.json')
 policy=EngagementRealizationPolicy(source_identity=proof['source_identity'])
 def resolve(user,message,step):
  r=entries[user.user_id,message.message_id]
  data=DecisionInput(post=message.as_post(),profile=_primary_variant_profile(user),peer_context=PeerContext(),platform_context=PlatformContext(),time_step=step,prompt_version=condition['prompt_version'])
  assert bank.client_identity(data,condition)==(r['client_messages_sha256'],r['client_condition_sha256'])
  draw=policy.realize(EngageDecision.model_validate(r['decision']),user_id=user.user_id,message_id=message.message_id)
  return {'client_condition_sha256':r['client_condition_sha256'],'bank_source':r['source'],'uniform_draw':draw.uniform_draw,'realized_engage':draw.realized_engage,'realized_action':draw.realized_action,'realization_key':draw.realization_key,'realization_status':draw.realization_status}
 fits={m.message_id:{u:_message_user_fit_components(m,prepared.cohort.users_by_id[u]) for u in prepared.cohort.sample_user_ids} for m in config.messages}
 result=_ConcurrentRuntimeKernel.fixed_judgment_path(config=config,prepared=prepared,weights=(.5,.3,.2),neighbor_saturation=3,message_fits=fits,resolve=resolve)
 assert len(result['terminals'])==1800 and len(result['barriers'])==30
 output.parent.mkdir(exist_ok=True)
 result.update(schema_version='ten-topic-four-model-formal-cell-v1',cell_id='P0::openai-codex/gpt-5.6-sol',behavior_seed=20260823,realization_source_identity=proof['source_identity'],network_scope='final_collected_topics',network_source_manifest_sha256=preparation['network_source_manifest_sha256'],p95=preparation['p95'],sample_user_ids=list(prepared.cohort.sample_user_ids),seed_user_ids=list(prepared.cohort.seed_user_ids),request_condition=condition,candidate_judgments=3000,new_judgment_calls=0,bank_path=str(fresh/'closed-bank.jsonl'),bank_sha256=bank.file_hash(fresh/'closed-bank.jsonl'),independent_acceptance_status='pending',production_deploy_eligible=False)
 bank.write_json(output,result)
 print('FORMAL cell=GPT/P0 exposures=1800 barriers=30 new_judgment_calls=0 hash='+bank.file_hash(output))
if __name__=='__main__':main()
