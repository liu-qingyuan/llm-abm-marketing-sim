"""Three-attempt original retry bound. Unknown dispatches are never auto reissued."""
import json,time
from dataclasses import replace
from llm_abm_sim.providers.robustness import PiOpenAIDecisionAdapter,OfficialKimiDecisionAdapter,AntigravityGeminiDecisionAdapter,_FrozenRobustnessDecisionAdapter,_DEEPSEEK
from llm_abm_sim.prompting import build_engagement_prompt
from llm_abm_sim import _parameter_judgment_bank as bank
from qualify import RecordedClient,append,LEDGER
from ledger_store import ROOT,intent_exists

def missing_response_is_unknown(*,error_type,category,status,observed):
 return not observed and (error_type=='ProviderResponseProvenanceUnknown' or (category in ['transport','timeout'] and status is None))

def known_retry_allowed(*,retryable,observed,status,category,attempt):
 known=observed or (status in [429,503] and category in ['temporary_rate_limit','temporary_overload','rate_limited','upstream_unavailable','http_status'])
 return bool(retryable and known and attempt<3)

def decide_observed(client,model,data,logical_id,user_id,message_id,template):
 identity=logical_id;unknown_parent=None
 for attempt in range(1,4):
  if intent_exists(identity):raise ValueError('prior durable intent requires explicit recovery audit')
  wrapper=RecordedClient(client,identity)
  adapter=PiOpenAIDecisionAdapter(prompt_version=data.prompt_version,client=wrapper) if model=='openai-codex/gpt-5.6-sol' else OfficialKimiDecisionAdapter(prompt_version=data.prompt_version,client=wrapper) if model=='kimi-k3' else AntigravityGeminiDecisionAdapter(requested_model=model,prompt_version=data.prompt_version,client=wrapper) if model=='gemini-3.1-pro' else _FrozenRobustnessDecisionAdapter(condition=replace(_DEEPSEEK,requested_model='deepseek-flash',wire_model='deepseek-flash',required_observed_model='deepseek-flash'),prompt_version=data.prompt_version,client=wrapper)
  messages=build_engagement_prompt(data)
  append({'type':'intent','purpose':'explicit_unknown_new_collection' if unknown_parent else 'formal_exposure','unknown_parent_request_id':unknown_parent,'explicit_user_authorization':str(ROOT/'protocol/UNKNOWN_CONTINUATION_AUTHORIZATION.json') if unknown_parent else None,'request_id':identity,'logical_request_id':logical_id,'attempt_number':attempt,'model':model,'template':template,'user_id':user_id,'message_id':message_id,'time_step':data.time_step,'full_client_messages':messages,'client_messages_sha256':bank.fingerprint(messages),'request_condition':adapter.safe_metadata,'timeout_seconds':90 if model=='kimi-k3' else 30,'physical_budget_cap':29143})
  try:
   decision=adapter.decide(data.post,data.profile,data.peer_context,data.platform_context,data.time_step)
   append({'type':'succeeded','request_id':identity,'decision':decision.model_dump(mode='json'),'accounting':adapter.provider_accounting.model_dump(mode='json'),'provider_fee_cny':adapter.last_provider_fee_cny,'nominal_usd':adapter.last_subscription_nominal_cost_usd})
   return decision,identity
  except Exception as exc:
   category=getattr(exc,'failure_category',None);status=getattr(exc,'status_code',None);retryable=getattr(exc,'retryable',False)
   append({'type':'failed_or_unknown','request_id':identity,'error_type':type(exc).__name__,'failure_category':category,'status_code':status,'retryable':retryable,'provider_fee_cny':adapter.last_provider_fee_cny,'nominal_usd':adapter.last_subscription_nominal_cost_usd})
   history=[json.loads(x) for x in LEDGER.read_text().splitlines()]
   observed=any(r['type']=='response' and r['request_id']==identity for r in history)
   unknown=missing_response_is_unknown(error_type=type(exc).__name__,category=category,status=status,observed=observed)
   if unknown:
    authorization=json.loads((ROOT/'protocol/UNKNOWN_CONTINUATION_AUTHORIZATION.json').read_text());assert authorization['preserve_original_unknown'] and authorization['maximum_total_physical_attempts_per_logical_input']==3
    append({'type':'unknown_classified','request_id':identity,'reason':'transport failed without durable provider response','authorization_for_separate_new_collection':str(ROOT/'protocol/UNKNOWN_CONTINUATION_AUTHORIZATION.json')})
    if attempt==3:raise
    unknown_parent=identity;identity=logical_id+':explicit-reissue'+str(attempt)
   else:
    if not known_retry_allowed(retryable=retryable,observed=observed,status=status,category=category,attempt=attempt):raise
    unknown_parent=None;identity=logical_id+':attempt'+str(attempt+1)
   wait=getattr(exc,'wait_seconds',None)
   time.sleep(min(60,max(.5,float(wait or .5))))
 raise AssertionError('bounded loop exhausted without terminal state')
