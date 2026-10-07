#!/usr/bin/env python3
"""User-authorized original official Kimi and explicitly amended DeepSeek qualification."""
import os,json,shlex
from pathlib import Path
from dataclasses import replace
from qualify import ROOT,ORIGINAL,LEDGER,append,RecordedClient
from llm_abm_sim import _parameter_judgment_bank as bank
from llm_abm_sim.concurrent_message_experiment import _prepare_concurrent_runtime_inputs,_primary_variant_profile
from llm_abm_sim.providers.moonshot import MoonshotOfficialClient
from llm_abm_sim.providers.robustness import OfficialKimiDecisionAdapter,_FrozenRobustnessDecisionAdapter,_DEEPSEEK
from llm_abm_sim.concurrent_robustness_operator import _new_client
from llm_abm_sim.decision import DecisionInput
from llm_abm_sim.prompting import build_engagement_prompt
from llm_abm_sim.schemas import PeerContext,PlatformContext

def main():
 approval=bank.read_json(ROOT/'protocol/authorization-partial.json');assert approval['deepseek_update_authorized'] and approval['cash_fee_approval'].startswith('user explicitly')
 for f in [ORIGINAL/'.env',Path(approval['kimi_credential_reference'])]:
  for l in f.read_text().splitlines():
   if '=' in l and not l.lstrip().startswith('#'):
    k,v=l.split('=',1);k=k.removeprefix('export ').strip()
    if k in ['DEEPSEEK_API_KEY','MOONSHOT_API_KEY']:os.environ[k]=shlex.split(v,comments=True)[0]
 os.environ['LLM_ABM_RUN_LIVE_LLM']='1'
 prep=bank.read_json(ORIGINAL/'runs/gpt-p0-bank-topup-20260917-authorized-01/preparation.json');config,_,_=bank._inputs(bank.read_json(Path(prep['audit']['path'])));config=config.model_copy(update={'network_scope':'final_collected_topics'});p=_prepare_concurrent_runtime_inputs(config)
 accepted=next(r for r in bank.read_json(ROOT.parent/'ten-topic-gpt-studies-20261006/preflight-final/samples.json') if r['arm']=='baseline');assert set(p.cohort.sample_user_ids)==set(accepted['sample_user_ids'])
 u=p.cohort.users_by_id[accepted['seed_user_ids'][0]];data=DecisionInput(post=config.messages[0].as_post(),profile=_primary_variant_profile(u),peer_context=PeerContext(),platform_context=PlatformContext(),time_step=0,prompt_version=prep['request_condition']['prompt_version'])
 for model in ['kimi-k3','deepseek-flash']:
  request_id=bank.fingerprint({'phase':'amended-qualification-v1','model':model})
  history=[json.loads(x) for x in LEDGER.read_text().splitlines()]
  if any(r['type']=='intent' and r['request_id']==request_id for r in history):continue
  assert sum(r['type']=='intent' for r in history)<29143
  client=MoonshotOfficialClient(api_key=os.environ['MOONSHOT_API_KEY'],live_enabled=True) if model=='kimi-k3' else _new_client('deepseek-v4-flash',30)
  wrapper=RecordedClient(client,request_id)
  adapter=OfficialKimiDecisionAdapter(prompt_version=data.prompt_version,client=wrapper) if model=='kimi-k3' else _FrozenRobustnessDecisionAdapter(condition=replace(_DEEPSEEK,requested_model='deepseek-flash',wire_model='deepseek-flash',required_observed_model='deepseek-flash'),prompt_version=data.prompt_version,client=wrapper)
  append({'type':'intent','purpose':'qualification','request_id':request_id,'model':model,'full_client_messages':build_engagement_prompt(data),'request_condition':adapter.safe_metadata,'user_id':u.user_id,'message_id':config.messages[0].message_id,'budget_pool':'global29143'})
  try:
   decision=adapter.decide(data.post,data.profile,data.peer_context,data.platform_context,0)
   append({'type':'succeeded','request_id':request_id,'decision':decision.model_dump(mode='json'),'accounting':adapter.provider_accounting.model_dump(mode='json'),'provider_fee_cny':adapter.last_provider_fee_cny,'nominal_usd':adapter.last_subscription_nominal_cost_usd})
   print(model,'qualification succeeded',flush=True)
  except Exception as exc:
   append({'type':'failed_or_unknown','request_id':request_id,'error_type':type(exc).__name__,'failure_category':getattr(exc,'failure_category',None),'retryable':getattr(exc,'retryable',False),'provider_fee_cny':adapter.last_provider_fee_cny,'nominal_usd':adapter.last_subscription_nominal_cost_usd});print(model,'qualification not successful',type(exc).__name__,flush=True)
  finally:client.close()
if __name__=='__main__':main()
