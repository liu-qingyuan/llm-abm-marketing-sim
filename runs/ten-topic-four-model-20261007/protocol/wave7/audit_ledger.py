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
 logical=collections.defaultdict(list)
 for identity,e in intents.items():
  # Older intents omitted the logical_id field; physical suffixes are explicit and stable.
  key=e.get('logical_request_id') or identity.split(':attempt')[0].split(':explicit-reissue')[0];logical[key].append(identity)
  if e.get('purpose')=='explicit_unknown_new_collection':
   parent=e.get('unknown_parent_request_id') or key;assert parent in intents and parent not in responses and parent in failures
   assert e['full_client_messages']==intents[parent]['full_client_messages'] and e['request_condition']==intents[parent]['request_condition']
   assert e.get('explicit_user_authorization') and Path(e['explicit_user_authorization']).exists()
 for key,identities in logical.items():assert len(identities)<=3
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
 result={'status':'all_observed_events_consistent_live_snapshot' if unresolved else 'all_settled_events_consistent','at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'snapshot_path':str(snapshot),'snapshot_sha256':hashlib.sha256(raw).hexdigest(),'physical_requests':len(intents),'logical_request_groups_including_qualifications':len(logical),'qualified_successes':sum(intents[k]['purpose']=='qualification' for k in success),'successful_judgments_including_qualifications':len(success),'formal_successes':sum(intents[k]['purpose']!='qualification' for k in success),'known_failures_with_response_or_typed_HTTP_status':len(failures)-len(unknown),'original_unknowns_retained':unknown,'inflight_not_unknown':unresolved,'wire_evidence_records':len(wire),'older_wire_evidence_scope':'earlier stages retained intent metadata and typed response; new stages additionally retain actual adapter wire model/controls','by_model':{k:dict(v) for k,v in by_model.items()},'known_nominal_usd_subtotal':str(nominal),'nominal_cost_known_settlements':nominal_known,'unknown_nominal_settlements':len(success)+len(failures)-nominal_known,'known_fee_cny_subtotal':str(fee) if fee_known else None,'actual_cash_fee':None,'actual_cash_fee_is_not_zero':True,'cash_ceiling':'user_authorized_unlimited','physical_cap':29143,'provider_calls_during_audit':0,'shared_components':'JSON/Decimal/hashlib only; no production ledger index or accounting tracker'}
 (out/'LEDGER_AUDIT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print('PASS ledger physical='+str(len(intents))+' success='+str(len(success))+' unknown='+str(len(unknown))+' inflight='+str(len(unresolved)))
if __name__=='__main__':main()
