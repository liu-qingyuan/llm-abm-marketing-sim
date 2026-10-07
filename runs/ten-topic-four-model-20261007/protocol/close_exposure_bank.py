#!/usr/bin/env python3
"""Freeze judgments actually used by accepted cells, not a fictitious full48k bank."""
import json,hashlib,collections,argparse
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main(partial):
 acceptance=json.loads((ROOT/'independent-acceptance/ACCEPTANCE_PROGRESS.json').read_text())
 if not partial and acceptance['verified_conditions']!=16:raise ValueError('sixteen independently accepted paths required')
 fresh=ROOT.parent/'ten-topic-gpt-studies-20261006/final-bank';bank_file=fresh/'closed-bank.jsonl';bank_sha256=hashlib.sha256(bank_file.read_bytes()).hexdigest();fresh_index={(r['user_id'],r['message_id'],r['client_condition_sha256']):r for r in (json.loads(x) for x in bank_file.read_text().splitlines())}
 folder=ROOT/('bank-progress' if partial else 'final-bank');folder.mkdir(exist_ok=True);rows=[];seen=set();counts=collections.defaultdict(collections.Counter)
 for cell in acceptance['cells']:
  path=Path(cell['path']);assert hashlib.sha256(path.read_bytes()).hexdigest()==cell['sha256'];payload=json.loads(path.read_text());model,template=payload['cell_id'].split('::')[1],payload['cell_id'].split('::')[0]
  for terminal in payload['terminals']:
   key=model,template,terminal['user_id'],terminal['message_id'];assert key not in seen;seen.add(key)
   if 'judgment' in terminal:
    decision=terminal['judgment'];source=terminal['judgment_source'];input_hash=terminal['client_messages_sha256']
    origin_type='historical_four_model' if source['type']=='reused_four_model' else 'new_formal_or_explicit_collection'
   else:
    original=fresh_index[terminal['user_id'],terminal['message_id'],terminal['client_condition_sha256']];decision=original['decision'];source={'type':'accepted_GPT_P0_bank','path':str(bank_file),'bank_sha256':bank_sha256,'entry_key':original.get('key',original['client_condition_sha256']),'entry_source':original['source'],'exact_client_condition_sha256':original['client_condition_sha256']};input_hash=original['client_messages_sha256'];origin_type='accepted_GPT_P0_bank'
   rows.append({'model':model,'template':template,'user_id':terminal['user_id'],'message_id':terminal['message_id'],'client_messages_sha256':input_hash,'decision':decision,'source':source,'used_by_path':str(path),'used_by_path_sha256':cell['sha256'],'actual_exposure_batch':terminal['time_step'],'behavior_seed':payload['behavior_seed'],'draw_anchor':payload['realization_source_identity']});counts[payload['cell_id']][origin_type]+=1
 out=folder/'exposure-judgments.jsonl'
 with out.open('w') as stream:
  for r in rows:stream.write(json.dumps(r,sort_keys=True,ensure_ascii=False)+'\n')
 result={'status':'partial_exposure_judgment_bank' if acceptance['verified_conditions']!=16 else 'closed_actual_exposure_judgment_bank','accepted_conditions':acceptance['verified_conditions'],'expected_conditions':16,'actual_exposure_unique_pairs':len(rows),'candidate_universe_total':48000,'full_candidate_bank_closed':False,'candidate_inventory_reference':str(ROOT/'protocol/MODEL_REUSE_AMENDED.csv'),'scope':'only judgments actually used in canonical accepted paths; no unavailable or unexposed inputs simulated','path':str(out),'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'by_cell':{k:dict(v) for k,v in counts.items()},'provider_calls':0}
 (folder/'manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print('BANK actual_exposure_pairs='+str(len(rows))+' conditions='+str(acceptance['verified_conditions'])+' provider_calls=0')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--partial',action='store_true');main(p.parse_args().partial)
