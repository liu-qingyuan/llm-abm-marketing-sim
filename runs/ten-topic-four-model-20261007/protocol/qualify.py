#!/usr/bin/env python3
"""Explicitly authorized, one qualification request per available original route."""
import json,os,hashlib,shlex,datetime
from pathlib import Path
from llm_abm_sim import _parameter_judgment_bank as bank
from llm_abm_sim.concurrent_message_experiment import _prepare_concurrent_runtime_inputs,_primary_variant_profile
from llm_abm_sim.providers.robustness import PiOpenAIDecisionAdapter,DeepSeekV4FlashDecisionAdapter,AntigravityGeminiDecisionAdapter
from llm_abm_sim.concurrent_robustness_operator import _new_client
from llm_abm_sim.decision import DecisionInput
from llm_abm_sim.prompting import build_engagement_prompt
from llm_abm_sim.schemas import PeerContext,PlatformContext
ROOT=Path(__file__).resolve().parents[1]
ORIGINAL=Path('/Users/liuqingyuan/work/llm-abm-marketing-sim')
LEDGER=ROOT/'request-ledger.jsonl'

def append(event):
 from ledger_store import append_event
 append_event(event)

class RecordedClient:
 def __init__(self,client,identity):self.client=client;self.identity=identity
 def __getattr__(self,k):return getattr(self.client,k)
 def create_response(self,*args,**kwargs):
  append({'type':'wire_request','request_id':self.identity,'wire_model':args[1] if len(args)>1 else kwargs.get('model'),'client_messages_sha256':hashlib.sha256(json.dumps(args[0],sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest(),'requested_controls':kwargs})
  response=self.client.create_response(*args,**kwargs)
  append({'type':'response','request_id':self.identity,'response':response.model_dump(mode='json')})
  return response

def main():
 approval=json.loads((ROOT/'protocol/authorization-partial.json').read_text())
 assert approval['cash_fee_approval'].startswith('user explicitly') and approval['maximum_physical_requests']==29143
 if LEDGER.exists():
  previous=[json.loads(x) for x in LEDGER.read_text().splitlines()]
 else:previous=[]
 for line in (ORIGINAL/'.env').read_text().splitlines():
  if '=' in line and not line.lstrip().startswith('#'):
   k,v=line.split('=',1);k=k.removeprefix('export ').strip()
   if k in ['DEEPSEEK_API_KEY','MOONSHOT_API_KEY','KIMI_API_KEY']:
    parsed=shlex.split(v,comments=True);os.environ[k]=parsed[0] if parsed else ''
 gateway=json.loads((Path.home()/'.antigravity_tools/gui_config.json').read_text())['proxy']
 assert gateway['port']==8045
 os.environ['ANTIGRAVITY_API_KEY']=gateway['api_key'];os.environ['LLM_ABM_RUN_LIVE_LLM']='1'
 prep=bank.read_json(ORIGINAL/'runs/gpt-p0-bank-topup-20260917-authorized-01/preparation.json')
 config,_,_=bank._inputs(bank.read_json(Path(prep['audit']['path'])))
 config=config.model_copy(update={'network_scope':'final_collected_topics'})
 prepared=_prepare_concurrent_runtime_inputs(config)
 accepted=next(r for r in bank.read_json(ROOT.parent/'ten-topic-gpt-studies-20261006/preflight-final/samples.json') if r['arm']=='baseline')
 assert set(accepted['sample_user_ids'])==set(prepared.cohort.sample_user_ids)
 user=prepared.cohort.users_by_id[accepted['seed_user_ids'][0]];post=config.messages[0].as_post()
 variants=['openai-codex/gpt-5.6-sol','deepseek-v4-flash','gemini-3.1-pro']
 for model in variants:
  identity=hashlib.sha256(('qualification-v1\0'+model).encode()).hexdigest()
  # Any prior intent forbids silent reissue, including lost/unknown responses.
  if any(r.get('request_id')==identity and r['type']=='intent' for r in previous):continue
  count=sum(r['type']=='intent' for r in previous)
  assert count <29143
  client=_new_client(model,90)
  wrapper=RecordedClient(client,identity)
  adapter=(PiOpenAIDecisionAdapter(prompt_version=prep['request_condition']['prompt_version'],client=wrapper) if model.startswith('openai') else DeepSeekV4FlashDecisionAdapter(prompt_version=prep['request_condition']['prompt_version'],client=wrapper) if model.startswith('deepseek') else AntigravityGeminiDecisionAdapter(requested_model=model,prompt_version=prep['request_condition']['prompt_version'],client=wrapper))
  data=DecisionInput(post=post,profile=_primary_variant_profile(user),peer_context=PeerContext(),platform_context=PlatformContext(),time_step=0,prompt_version=prep['request_condition']['prompt_version'])
  append({'type':'intent','purpose':'qualification','request_id':identity,'model':model,'user_id':user.user_id,'message_id':config.messages[0].message_id,'full_client_messages':build_engagement_prompt(data),'request_condition':adapter.safe_metadata,'physical_ordinal':count+1})
  try:
   decision=adapter.decide(post,data.profile,data.peer_context,data.platform_context,0)
   append({'type':'succeeded','request_id':identity,'decision':decision.model_dump(mode='json'),'accounting':adapter.provider_accounting.model_dump(mode='json'),'provider_fee_cny':adapter.last_provider_fee_cny,'nominal_usd':adapter.last_subscription_nominal_cost_usd})
   print(model,'qualification succeeded',flush=True)
  except Exception as exc:
   append({'type':'failed_or_unknown','request_id':identity,'error_type':type(exc).__name__,'failure_category':getattr(exc,'failure_category',None),'retryable':getattr(exc,'retryable',False),'provider_fee_cny':adapter.last_provider_fee_cny,'nominal_usd':adapter.last_subscription_nominal_cost_usd})
   print(model,'qualification not successful',type(exc).__name__,flush=True)
  finally:client.close()
  previous=[json.loads(x) for x in LEDGER.read_text().splitlines()]
 if not (os.environ.get('MOONSHOT_API_KEY') or os.environ.get('KIMI_API_KEY')):
  print('Kimi official: runtime credential missing; no physical request',flush=True)
if __name__=='__main__':main()
