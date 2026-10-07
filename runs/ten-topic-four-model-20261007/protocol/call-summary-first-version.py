#!/usr/bin/env python3
"""Aggregate only independently audited physical intents; no Provider or pricing lookup."""
import argparse,json,csv,hashlib,collections,datetime
from decimal import Decimal
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
MODELS={'openai-codex/gpt-5.6-sol':'GPT-5.6 Sol','kimi-k3':'Kimi','gemini-3.1-pro':'Gemini 3.1 Pro','deepseek-flash':'DeepSeek V4.1 Flash'}

def input_signature(intent):
 v={k:intent.get(k) for k in ['model','template','full_client_messages','request_condition']}
 return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def amount(records,field):
 values=[Decimal(str(r[field])) for r in records if r.get(field) is not None]
 assert all(v.is_finite() and v>=0 for v in values)
 return str(sum(values,Decimal('0'))) if values else None,len(values)

def main(partial):
 audit=json.loads((ROOT/'ledger-audit/LEDGER_AUDIT.json').read_text());raw=Path(audit['snapshot_path']).read_bytes();assert hashlib.sha256(raw).hexdigest()==audit['snapshot_sha256']
 acceptance=json.loads((ROOT/'independent-acceptance/ACCEPTANCE_PROGRESS.json').read_text())
 if not partial:assert acceptance['verified_conditions']==16 and acceptance['verified_exposures']==28800 and not audit['inflight_not_unknown']
 events=[json.loads(x) for x in raw.splitlines()];intents={x['request_id']:x for x in events if x['type']=='intent'};success={x['request_id']:x for x in events if x['type']=='succeeded'};failed={x['request_id']:x for x in events if x['type']=='failed_or_unknown'};unknown=set(audit['original_unknowns_retained']);groups=collections.defaultdict(list);qual=[]
 for rid,i in intents.items():
  if i['purpose']=='qualification':qual.append(rid)
  else:
   assert i['model'] in MODELS and i['template'] in ['P0','P1','P2','P3'];groups[i['model'],i['template']].append(rid)
 cells={}
 for fact in acceptance['cells']:
  p=Path(fact['path']);assert hashlib.sha256(p.read_bytes()).hexdigest()==fact['sha256'];cell=json.loads(p.read_text());t,m=cell['cell_id'].split('::');counts=collections.Counter()
  for r in cell['terminals']:
   source=r.get('judgment_source',{}).get('type','reused_accepted_gpt_bank');counts[source]+=1
  assert sum(counts.values())==1800;cells[m,t]=counts
 rows=[]
 for model,display in MODELS.items():
  for template in ['P0','P1','P2','P3']:
   ids=groups[model,template];settled=[success.get(i) or failed.get(i) for i in ids if i in success or i in failed];nominal,nknown=amount(settled,'nominal_usd');fee,fknown=amount(settled,'provider_fee_cny');c=cells.get((model,template),{})
   rows.append({'model':display,'model_id':model,'template':template,'physical_requests':len(ids),'unique_full_input_condition_signatures':len({input_signature(intents[i]) for i in ids}),'new_successful_judgments_collected':sum(i in success for i in ids),'known_failures_retained':sum(i in failed and i not in unknown for i in ids),'unknown_requests_retained':sum(i in unknown for i in ids),'inflight':sum(i not in success and i not in failed for i in ids),'complete_cell_exposures':1800 if c else 0,'old_four_model_judgments_used_complete_cell':c.get('reused_four_model',0),'prior_gpt_bank_judgments_used_complete_cell':c.get('reused_accepted_gpt_bank',0),'new_judgments_used_complete_cell':c.get('new_formal_exposure',0),'known_nominal_usd_reference_subtotal':nominal,'nominal_known_settlements':nknown,'nominal_unknown_settlements':len(settled)-nknown,'known_provider_fee_cny_field_subtotal':fee,'provider_fee_known_settlements':fknown,'provider_fee_unknown_settlements':len(settled)-fknown,'actual_cash_fee':None})
 assert sum(x['physical_requests'] for x in rows)+len(qual)==audit['physical_requests']
 out=ROOT/('call-ledger-progress' if partial else 'formal-call-ledger');out.mkdir(exist_ok=True)
 with (out/'model-template-calls-costs.csv').open('w') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 summary={'status':'partial_audited_snapshot' if partial else 'all16_call_ledger_closed','at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_ledger_snapshot_sha256':audit['snapshot_sha256'],'source_acceptance_sha256':hashlib.sha256((ROOT/'independent-acceptance/ACCEPTANCE_PROGRESS.json').read_bytes()).hexdigest(),'conditions_verified':acceptance['verified_conditions'],'physical_requests_including_qualification':audit['physical_requests'],'qualification_physical_requests':len(qual),'qualification_successes':sum(i in success for i in qual),'qualification_failures':sum(i in failed for i in qual),'qualification_models':dict(collections.Counter(intents[i]['model'] for i in qual)),'successful_judgments_including_qualification':audit['successful_judgments_including_qualifications'],'unknown_requests_retained':len(unknown),'known_nominal_usd_reference_subtotal':audit['known_nominal_usd_subtotal'],'known_provider_fee_cny_field_subtotal':audit['known_fee_cny_subtotal'],'actual_cash_fee':None,'actual_cash_fee_not_zero_assumption':True,'cash_ceiling':'user_authorized_unlimited','physical_cap':29143,'nominal_reference_is_not_cash':'Frozen subscription nominal pricing fields only; no inferred cash payment or USD/CNY conversion. Prior reused-bank costs are not recharged as this task calls.','candidate_universe':48000,'candidate_universe_is_not_call_budget':True,'partial_count_definition':'complete_cell_exposures excludes live partial journals; collected successes may exceed complete-cell uses until all16 close','legacy_and_current_contract':'legacy request metadata max3 unchanged; user-amended Gemini admission allows separately identified max3 collection batches on same input; all count toward global cap','upstream_gateway_physical_requests':'gateway hidden upstream invocations not observable; count is client-side physical intent/dispatch','unknown_charge_is_unknown':True,'provider_calls_during_accounting':0}
 (out/'COST_LEDGER.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print('CALL_LEDGER conditions='+str(summary['conditions_verified'])+' physical='+str(summary['physical_requests_including_qualification'])+' qualification='+str(len(qual))+' cash=unknown provider_calls=0')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--partial',action='store_true');main(p.parse_args().partial)
