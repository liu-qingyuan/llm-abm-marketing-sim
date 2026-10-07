#!/usr/bin/env python3
"""Independent ledger accounting from an immutable byte snapshot; SQLite cache is ignored."""
import json,hashlib,collections,datetime
from decimal import Decimal
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
 raw=(ROOT/'request-ledger.jsonl').read_bytes();assert raw.endswith(b'\n');out=ROOT/'ledger-audit';out.mkdir(exist_ok=True)
 snapshot=out/'request-ledger-snapshot.jsonl';snapshot.write_bytes(raw)
 events=[json.loads(x) for x in raw.splitlines()];intents={};responses={};success={};failures={};wire={};positions={}
 for position,e in enumerate(events):
  identity=e['request_id'];kind=e['type']
  if kind=='intent':
   assert identity not in intents;intents[identity]=e;positions[identity]=position
   assert e['model'] in ['openai-codex/gpt-5.6-sol','kimi-k3','gemini-3.1-pro','deepseek-flash','deepseek-v4-flash']
   actual=hashlib.sha256(json.dumps(e['full_client_messages'],sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
   if e.get('client_messages_sha256') is not None:assert e['client_messages_sha256']==actual
  elif kind=='wire_request':
   assert identity in intents and identity not in wire;wire[identity]=e
   actual=hashlib.sha256(json.dumps(intents[identity]['full_client_messages'],sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest();assert e['client_messages_sha256']==actual
  elif kind=='response':assert identity in intents and identity not in responses;responses[identity]=e['response']
  elif kind=='succeeded':
   assert identity in intents and identity in responses and identity not in success and identity not in failures;success[identity]=e
   model=intents[identity]['model'];expected={'openai-codex/gpt-5.6-sol':'gpt-5.6-sol','kimi-k3':'kimi-k3','gemini-3.1-pro':'gemini-pro-agent','deepseek-flash':'deepseek-flash'}[model]
   assert responses[identity]['observed_model']==expected and e['accounting']['successful_decision_count']==1 and e['accounting']['external_request_invocations']==1
   assert 0<=e['decision']['probability']<=1 and 0<=e['decision']['confidence']<=1 and e['decision']['action'] in ['like','comment','share','ignore']
   if responses[identity]['usage_status']=='complete':assert responses[identity]['input_tokens']+responses[identity]['output_tokens']==responses[identity]['total_tokens']
  elif kind=='failed_or_unknown':assert identity in intents and identity not in success and identity not in failures;failures[identity]=e
  elif kind=='unknown_classified':assert identity in intents and identity not in responses
  else:raise ValueError('unexpected ledger kind '+kind)
 assert len(intents)<=29143
 logical=collections.defaultdict(list);collections_by_id=collections.defaultdict(list);retry_after_violations=[];cooldown_checked=0
 for identity,e in intents.items():
  # Older intents omitted the logical_id field; physical suffixes are explicit and stable.
  key=e.get('logical_request_id') or identity.split(':attempt')[0].split(':explicit-reissue')[0];logical[key].append(identity)
  collection=e.get('collection_id') or key;collections_by_id[collection].append(identity)
  if e.get('collection_number',1)>1:
   assert e['model']=='gemini-3.1-pro' and e['logical_request_id']==key
   authorization=json.loads(Path(e['collection_user_authorization']).read_text());assert authorization['global_physical_cap']==29143 and authorization['maximum_physical_attempts_per_collection']==3
   parent=e['exhausted_collection_parent_request_id'];assert parent in failures and parent not in success
   assert e['full_client_messages']==intents[parent]['full_client_messages'] and e['request_condition']==intents[parent]['request_condition']
  if e.get('purpose')=='explicit_unknown_new_collection':
   parent=e.get('unknown_parent_request_id') or key;assert parent in intents and parent not in responses and parent in failures
   assert e['full_client_messages']==intents[parent]['full_client_messages'] and e['request_condition']==intents[parent]['request_condition']
   assert e.get('explicit_user_authorization') and Path(e['explicit_user_authorization']).exists()
 for key,identities in collections_by_id.items():
  assert len(identities)<=3
  first=intents[identities[0]]
  if first.get('collection_number',1)>1:
   parent=first['exhausted_collection_parent_request_id'];previous=intents[parent].get('collection_id') or first['logical_request_id']
   assert len(collections_by_id[previous])==3 and all(i in failures for i in collections_by_id[previous])
   assert parent==collections_by_id[previous][-1]
 for key,identities in logical.items():
  deadline=None
  for identity in identities:
   e=intents[identity];at=datetime.datetime.fromisoformat(e['at_utc']) if 'at_utc' in e else None
   if deadline and at and at<deadline:
    assert not e.get('cooldown_policy'), 'post-fix dispatch precedes observed Retry-After'
    retry_after_violations.append({'request_id':identity,'model':e['model'],'template':e.get('template'),'intent_at_utc':at.isoformat(),'observed_not_before_utc':deadline.isoformat(),'scope':'pre-fix failure attempts preserved; no retroactive ledger correction'})
   if e.get('cooldown_policy'):
    cooldown_checked+=1
    declared=e.get('dispatch_not_before_utc')
    if declared:assert at>=datetime.datetime.fromisoformat(declared)
   failure=failures.get(identity,{})
   wait=failure.get('wait_seconds')
   if isinstance(wait,(int,float)) and not isinstance(wait,bool) and wait>0 and 'at_utc' in failure:
    observed=datetime.datetime.fromisoformat(failure['at_utc'])+datetime.timedelta(seconds=wait);deadline=max(deadline,observed) if deadline else observed
  if len(identities)>3:assert all(intents[i]['model']=='gemini-3.1-pro' for i in identities)
 nominal=Decimal('0');nominal_known=0;fee=Decimal('0');fee_known=0;by_model=collections.defaultdict(collections.Counter)
 for identity,e in intents.items():
  model=e['model'];by_model[model]['physical_requests']+=1
  if identity in success:by_model[model]['successful_response_judgments']+=1
  if identity in failures:
   failed=failures[identity];is_unknown=identity not in responses and (failed.get('error_type')=='ProviderResponseProvenanceUnknown' or (failed.get('failure_category') in ['transport','timeout'] and failed.get('status_code') is None))
   by_model[model]['unknown_original']+=is_unknown
   by_model[model]['known_failure']+=not is_unknown
  settled=success.get(identity) or failures.get(identity)
  if settled and settled.get('nominal_usd') is not None:nominal+=Decimal(str(settled['nominal_usd']));nominal_known+=1
  if settled and settled.get('provider_fee_cny') is not None:fee+=Decimal(str(settled['provider_fee_cny']));fee_known+=1
 unresolved=sorted(set(intents)-set(success)-set(failures));unknown=sorted(k for k,e in failures.items() if k not in responses and (e.get('error_type')=='ProviderResponseProvenanceUnknown' or (e.get('failure_category') in ['transport','timeout'] and e.get('status_code') is None)))
 result={'status':'all_observed_events_consistent_live_snapshot' if unresolved else 'all_settled_events_consistent','at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'snapshot_path':str(snapshot),'snapshot_sha256':hashlib.sha256(raw).hexdigest(),'physical_requests':len(intents),'logical_request_groups_including_qualifications':len(logical),'pre_fix_retry_after_violations_retained':retry_after_violations,'post_fix_cooldown_intents_checked':cooldown_checked,'explicit_additional_collection_count':sum(':collection' in k for k in collections_by_id),'qualified_successes':sum(intents[k]['purpose']=='qualification' for k in success),'successful_judgments_including_qualifications':len(success),'formal_successes':sum(intents[k]['purpose']!='qualification' for k in success),'known_failures_with_response_or_typed_HTTP_status':len(failures)-len(unknown),'original_unknowns_retained':unknown,'inflight_not_unknown':unresolved,'wire_evidence_records':len(wire),'older_wire_evidence_scope':'earlier stages retained intent metadata and typed response; new stages additionally retain actual adapter wire model/controls','by_model':{k:dict(v) for k,v in by_model.items()},'known_nominal_usd_subtotal':str(nominal),'nominal_cost_known_settlements':nominal_known,'unknown_nominal_settlements':len(success)+len(failures)-nominal_known,'known_fee_cny_subtotal':str(fee) if fee_known else None,'actual_cash_fee':None,'actual_cash_fee_is_not_zero':True,'cash_ceiling':'user_authorized_unlimited','physical_cap':29143,'provider_calls_during_audit':0,'shared_components':'JSON/Decimal/hashlib only; no production ledger index or accounting tracker'}
 (out/'LEDGER_AUDIT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print('PASS ledger physical='+str(len(intents))+' success='+str(len(success))+' unknown='+str(len(unknown))+' inflight='+str(len(unresolved)))
if __name__=='__main__':main()
