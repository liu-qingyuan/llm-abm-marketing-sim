#!/usr/bin/env python3
"""One-pass immutable origin/condition audit; uses raw checksums, not recovery replay."""
import json,hashlib,collections
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OLD=Path('/Users/liuqingyuan/work/llm-abm-marketing-sim/outputs/01a08bb3-1446-7f51-8933-cd49b50e9ccb/four-model-final-20260912-verified')
def canonical(v):return (json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False)+'\n').encode()
def main():
 rows=[json.loads(x) for x in (OLD/'judgments.jsonl').read_text().splitlines()]
 targets=collections.defaultdict(dict)
 for r in rows:
  o=r['origin'];assert o['event_sequence'] not in targets[o['file_path']]
  targets[o['file_path']][o['event_sequence']]=r
 ledger=[json.loads(x) for x in (ROOT/'request-ledger.jsonl').read_text().splitlines()]
 successes={r['request_id'] for r in ledger if r['type']=='succeeded'}
 conditions={r['model']:r['request_condition'] for r in ledger if r.get('purpose')=='qualification' and r['request_id'] in successes}
 assert all(m in conditions for m in ['openai-codex/gpt-5.6-sol','gemini-3.1-pro','kimi-k3'])
 closure=ROOT/'protocol/OLD_SOURCE_BINDING.json'
 assert closure.exists() and json.loads(closure.read_text())['status']=='immutable_original_formal_contract_evidence_bound'
 initial_plan=Path('/Users/liuqingyuan/work/llm-abm-marketing-sim/runs/concurrent-robustness-v2-formal-rebound-20260906T184929Z/formal-execution-plan.json')
 source_doc=json.loads((OLD/'Evidence.json').read_text());bundle=json.loads(Path(source_doc['source_bundle']['path']).read_text())
 initial_ref=next(x for x in bundle['artifact_facts'] if x['path']==str(initial_plan))
 assert hashlib.sha256(initial_plan.read_bytes()).hexdigest()==initial_ref['sha256']
 initial_plan_document=json.loads(initial_plan.read_text())
 verified=0;condition_modes=collections.Counter();condition_pass=collections.Counter();condition_excluded=collections.Counter();refs=[];records=[]
 for filename,expected in targets.items():
  path=Path(filename);sha=hashlib.sha256(path.read_bytes()).hexdigest();assert {r['origin']['file_sha256'] for r in expected.values()}=={sha}
  found=set();receipts=[]
  for line in path.open():
   e=json.loads(line);sequence=e['sequence']
   if e.get('kind') in ['parallel_execution_accepted','kimi_official_migration_accepted','final_model_parallel_accepted','gpt_manual_retry_accepted']:
    receipt=e['payload']['approval'];assert hashlib.sha256(Path(receipt['path']).read_bytes()).hexdigest()==receipt['sha256'];receipts.append({'kind':e['kind'],'approval':receipt})
   if sequence not in expected:continue
   r=expected[sequence];o=r['origin'];field='checksum' if o['kind']=='legacy_v2' else 'record_sha256';checksum=e[field];body={k:v for k,v in e.items() if k!=field};assert hashlib.sha256(canonical(body)).hexdigest()==checksum==o['event_checksum']
   j=e['payload']['judgment'];assert j['judgment_id']==r['judgment_id']
   if o['kind']=='legacy_v2':
    assert all(j[f]==r[f] for f in ['user_id','message_id','requested_model','observed_model','prompt_variant','prompt_version','prompt_canonical_hash','provider_engage','provider_probability','provider_action','provider_reason','provider_confidence'])
    condition_match=False;metadata=None
    if r['requested_model']=='gemini-3.1-pro':
     # Initial V2 deliberately stores attempt facts rather than full adapter metadata.
     # Bind the original initial formal plan/qualification, not a fabricated raw field.
     initial_plan=Path('/Users/liuqingyuan/work/llm-abm-marketing-sim/runs/concurrent-robustness-v2-formal-rebound-20260906T184929Z/formal-execution-plan.json')
     plan=initial_plan_document
     assert plan['status']=='ready' or plan['formal_run_authorized'] is True
     route=next(x for x in plan['request']['provider_routes'] if x['requested_model']=='gemini-3.1-pro')
     assert route['provider_route']==r['successful_attempts'][-1]['provider_route']==conditions['gemini-3.1-pro']['provider_route']
     assert route['required_observed_model']==r['observed_model']==conditions['gemini-3.1-pro']['required_observed_model']
     metadata=dict(conditions['gemini-3.1-pro'],prompt_version=r['prompt_version'],prompt_canonical_hash=r['prompt_canonical_hash'])
     condition_match=True;condition_pass['gemini-3.1-pro']+=1;condition_modes['initial_v2_frozen_contract_reconstruction_metadata_unstored']+=1
    else:condition_excluded[r['requested_model']]+=1
   else:
    d=j['decision'];assert all(d[a]==r[b] for a,b in [('engage','provider_engage'),('probability','provider_probability'),('action','provider_action'),('reason','provider_reason'),('confidence','provider_confidence')])
    metadata=d['provider_metadata']
    reconstructed=False
    if metadata is None:
     # Parallel/task journals deliberately exclude provider_metadata. Do not invent it.
     # Recover only the frozen effective route admitted by the independently hash-bound old contract.
     route=r['successful_attempts'][-1]['provider_route']
     model='kimi-k3' if route=='moonshot_official' else r['requested_model']
     blueprint=dict(conditions[model]) if model in conditions else None
     if blueprint is not None:
      metadata=dict(blueprint,prompt_version=r['prompt_version'],prompt_canonical_hash=r['prompt_canonical_hash'])
      reconstructed=True
    else:
     model=metadata['requested_model'];blueprint=dict(conditions[model]) if model in conditions else None
    if blueprint is not None:
     blueprint.update(prompt_version=r['prompt_version'],prompt_canonical_hash=r['prompt_canonical_hash'])
     condition_match=metadata==blueprint
     if not condition_match:
      differing={k:(metadata.get(k),blueprint.get(k)) for k in metadata.keys()|blueprint.keys() if metadata.get(k)!=blueprint.get(k)}
      raise ValueError('effective request conditions differ: '+repr(differing))
     condition_pass[model]+=1
     condition_modes['frozen_contract_reconstruction_metadata_excluded' if reconstructed else 'direct_persisted_provider_metadata']+=1
    else:condition_match=False;condition_excluded[r['requested_model']]+=1
   found.add(sequence);verified+=1
   if condition_match:records.append({'cell_id':r['cell_id'],'judgment_id':r['judgment_id'],'user_id':r['user_id'],'message_id':r['message_id'],'origin':o,'effective_condition_sha256':hashlib.sha256(canonical(metadata)).hexdigest(),'effective_request_condition':metadata})
  assert found==set(expected)
  refs.append({'path':filename,'sha256':sha,'matched_judgments':len(found),'generation_setting_receipts':receipts})
 assert verified==28800
 out=ROOT/'protocol/OLD_ORIGIN_ACCEPTANCE.json';out.write_text(json.dumps({'status':'origin_and_effective_conditions_verified','raw_origin_judgments':verified,'exact_current_qualification_condition_matches':dict(condition_pass),'excluded_version_or_transport':dict(condition_excluded),'origin_sources':refs,'qualified_condition_source':'actual successful qualification intent metadata, P0–P3 canonical version/hash substituted per record','full_client_input_check':'separate reuse audit reconstructs and matches rendered user/message inputs','condition_evidence_modes':dict(condition_modes),'parallel_metadata_omission':'_concurrent_recovery_parallel_runtime.py: decision.model_dump(exclude={provider_metadata}); reconstructed conditions explicitly labeled, not purported raw observed metadata','old_contract_closure_reference':str(closure),'provider_calls_during_audit':0},indent=2))
 with (ROOT/'protocol/eligible-old-judgment-origins.jsonl').open('w') as f:
  for r in records:f.write(json.dumps(r,sort_keys=True)+'\n')
 print('PASS raw_origins=28800 effective_conditions='+str(sum(condition_pass.values()))+' provider_calls=0')
if __name__=='__main__':main()
