"""Classify only observed missing-response intents after verified worker disappearance."""
import json,datetime,hashlib
from pathlib import Path
from complete_authorized_matrix import inventory_processes
from ledger_store import append_event
ROOT=Path(__file__).resolve().parents[1]

def main():
 workers,queues=inventory_processes();assert not workers and not queues
 rows=[json.loads(x) for x in (ROOT/'request-ledger.jsonl').read_text().splitlines()]
 intents={e['request_id']:e for e in rows if e['type']=='intent'};responses={e['request_id'] for e in rows if e['type']=='response'};settled={e['request_id'] for e in rows if e['type'] in ['succeeded','failed_or_unknown']};pending=sorted(set(intents)-settled);classified=[]
 for rid in pending:
  assert rid not in responses, 'real response needs separate offline interpretation, not unknown classification'
  assert intents[rid]['model']=='kimi-k3'
  append_event({'type':'failed_or_unknown','request_id':rid,'error_type':'ProviderResponseProvenanceUnknown','failure_category':None,'retryable':False,'status_code':None,'wait_seconds':None,'provider_fee_cny':None,'nominal_usd':None,'classification_reason':'worker PID and original tool handle both missing after explicit turn abortion; no persisted response','classification_evidence':str(ROOT/'protocol/INTERRUPTION_RECOVERY.json')})
  append_event({'type':'unknown_classified','request_id':rid,'authorization_for_separate_new_collection':str(ROOT/'protocol/UNKNOWN_CONTINUATION_AUTHORIZATION.json')});classified.append({'request_id':rid,'model':intents[rid]['model'],'template':intents[rid]['template'],'original_intent_retained':True,'response_exists':False})
 checkpoints=[]
 for model,slug in [('kimi-k3','Kimi'),('gemini-3.1-pro','gemini-3.1-pro')]:
  for t in ['P1','P2','P3']:
   if (ROOT/f'formal-paths/{t}--{slug}.json').exists():continue
   f=max((ROOT/'formal-paths').glob(f'{t}--{slug}-events*.jsonl'),key=lambda q:q.stat().st_mtime_ns);raw=f.read_bytes();events=[json.loads(x) for x in raw.splitlines()]
   before=hashlib.sha256(raw).hexdigest()
   if events[-1]['kind'] not in ['cell_partial','cell_completed']:
    event={'kind':'cell_partial','error_type':'ObservedExternalTurnInterruption','completed_exposures':sum(e['kind']=='terminal' for e in events),'completed_barriers':sum(e['kind']=='barrier' for e in events),'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'verified_no_live_worker':True}
    with f.open('a') as out:out.write(json.dumps(event,sort_keys=True)+'\n')
   checkpoints.append({'path':str(f),'prefix_sha256_before_termination_marker':before,'sha256_after':hashlib.sha256(f.read_bytes()).hexdigest(),'original_bytes_preserved_as_prefix':f.read_bytes().startswith(raw)})
 evidence={'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'worker_inventory':[],'original_tool_handles_verified_missing':[6386,73528,27796,98340,86121,80186,42139],'classification':'verified terminal process disappearance, not observation timeout','classified_missing_response_intents':classified,'checkpoints':checkpoints,'provider_calls':0,'new_successes_not_fabricated':True}
 (ROOT/'protocol/INTERRUPTION_RECOVERY.json').write_text(json.dumps(evidence,indent=2));print('classified_unknown='+str(len(classified))+' provider_calls=0')
if __name__=='__main__':main()
