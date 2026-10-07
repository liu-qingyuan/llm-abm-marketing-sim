#!/usr/bin/env python3
"""Re-read original formal paths; do not call report summarize/percentile helpers."""
import argparse,csv,json,collections,random,math
from pathlib import Path
from llm_abm_sim import _parameter_judgment_bank as bank
ROOT=Path(__file__).resolve().parents[1]

def main(partial):
 report=ROOT/('progress-report' if partial else 'formal-report');evidence=json.loads((report/'evidence.json').read_text())
 acceptance=json.loads((ROOT/'independent-acceptance/ACCEPTANCE_PROGRESS.json').read_text());groups={}
 latent_csv=Path('/Users/liuqingyuan/work/llm-abm-marketing-sim/data/processed/jinjiang_douyin/jinjiang-final-caption-hashtag-comments-profiles-latent-v1-validation-20260705T000000Z/latent_attribute_assignments.csv')
 segments={r['user_id']:{'class_1':'S1','class_2':'S2','class_3':'S3'}[r['latent_class']] for r in csv.DictReader(latent_csv.open())}
 fresh=ROOT.parent/'ten-topic-gpt-studies-20261006/final-bank';fresh_index={(r['user_id'],r['message_id'],r['client_condition_sha256']):r for r in (json.loads(x) for x in (fresh/'closed-bank.jsonl').read_text().splitlines())}
 for fact in acceptance['cells']:
  path=Path(fact['path']);assert bank.file_hash(path)==fact['sha256'];cell=json.loads(path.read_text());model,template=cell['cell_id'].split('::')[1],cell['cell_id'].split('::')[0];rows=[]
  for r in cell['terminals']:
   d=r.get('judgment') or fresh_index[r['user_id'],r['message_id'],r['client_condition_sha256']]['decision']
   rows.append({**r,'provider_engage':d['engage'],'provider_probability':d['probability'],'provider_confidence':d['confidence']})
  groups[model,template]=rows
 assert len(groups)==evidence['conditions']
 if not partial:assert len(groups)==16
 def check_stats(rows,values):
  n=len(rows);assert int(values['exposures'])==n
  for action in ['like','comment','share','ignore']:assert int(values[action])==sum(r['realized_action']==action for r in rows)
  assert int(values['realized_positive'])==sum(r['realized_engage'] for r in rows)
  assert int(values['judgment_positive'])==sum(r['provider_engage'] for r in rows)
  assert int(values['campaign_positive_users'])==len({r['user_id'] for r in rows if r['realized_engage']})
  for field in ['engage','probability','confidence']:
   name='judgment_rate' if field=='engage' else 'mean_'+field
   expected=sum(float(r['provider_'+field]) for r in rows)/n if n else None
   assert (values[name]=='' and expected is None) or math.isclose(float(values[name]),expected,abs_tol=1e-12)
  expected=sum(r['realized_engage'] for r in rows)/n if n else None;assert (values['realized_rate']=='' and expected is None) or math.isclose(float(values['realized_rate']),expected,abs_tol=1e-12)
 checked=0
 for filename in ['conditions.csv','messages.csv','segments-messages.csv','curves.csv']:
  for values in csv.DictReader((report/filename).open()):
   rows=groups[values['model_id'],values['template']]
   if 'message' in values:rows=[r for r in rows if r['message_id']==values['message']]
   if 'segment' in values:rows=[r for r in rows if segments[r['user_id']]==values['segment']]
   if 'batch' in values:rows=[r for r in rows if r['time_step']<=int(values['batch'])]
   check_stats(rows,values);checked+=1
 old_path=Path('/Users/liuqingyuan/work/llm-abm-marketing-sim/outputs/01a08bb3-1446-7f51-8933-cd49b50e9ccb/four-model-final-20260912-verified/realized_terminals.jsonl')
 old_groups=collections.defaultdict(list)
 for line in old_path.open():
  r=json.loads(line);old_groups[r['requested_model'],r['prompt_variant']].append(r)
 for values in csv.DictReader((report/'old-new.csv').open()):
  old=old_groups[values['old_model_id'],values['template']];new=groups[values['model_id'],values['template']]
  assert len(old)==len(new)==1800
  a=sum(r['realized_engage'] for r in old);b=sum(r['realized_engage'] for r in new)
  assert int(values['old_realized_positive'])==a and int(values['new_realized_positive'])==b
  assert math.isclose(float(values['old_realized_rate']),a/1800,abs_tol=1e-12) and math.isclose(float(values['new_realized_rate']),b/1800,abs_tol=1e-12)
  assert math.isclose(float(values['rate_delta']),(b-a)/1800,abs_tol=1e-12)
  checked+=1
 sample=next(r for r in json.loads((ROOT.parent/'ten-topic-gpt-studies-20261006/preflight-final/samples.json').read_text()) if r['arm']=='baseline');seeds=set(sample['seed_user_ids']);bootstrap_rows=0
 for values in csv.DictReader((report/'direct-seed-panel.csv').open()):
  left={(r['user_id'],r['message_id']):r for r in groups[values['model_id'],values['template']] if r['time_step']==0 and r['user_id'] in seeds};right={(r['user_id'],r['message_id']):r for r in groups[values['reference_model_id'],values['reference_template']] if r['time_step']==0 and r['user_id'] in seeds};assert set(left)==set(right)
  keys=[k for k in sorted(left) if values['message']=='all' or k[1]==values['message']];users=sorted({k[0] for k in keys});assert int(values['pairs'])==len(keys) and int(values['user_blocks'])==len(users)==20
  differences=[]
  for u in users:
   selected=[k for k in keys if k[0]==u];differences.append(sum(float(left[k]['provider_'+values['field']])-float(right[k]['provider_'+values['field']]) for k in selected)/len(selected))
  assert math.isclose(float(values['delta']),sum(differences)/20,abs_tol=1e-12)
  rng=random.Random(20260809);replicates=sorted(sum(differences[rng.randrange(20)] for j in range(20))/20 for i in range(500))
  for column,q in [('lower_95',.025),('upper_95',.975)]:
   pos=499*q;a=math.floor(pos);b=math.ceil(pos);expected=replicates[a]*(b-pos)+replicates[b]*(pos-a) if b!=a else replicates[a];assert math.isclose(float(values[column]),expected,abs_tol=1e-12)
  bootstrap_rows+=1
 result={'status':'passed_complete_statistics' if len(groups)==16 else 'passed_partial_statistics_only','conditions':len(groups),'source':'original formal cell terminal JSON, not report normalized records','tables_and_curves_checked_rows':checked,'paired_seed_bootstrap_checked_rows':bootstrap_rows,'segment_csv_source':str(latent_csv),'segment_csv_sha256':bank.file_hash(latent_csv),'bootstrap_shared_component':'Python random.Random algorithm/declared seed only; statistics and percentile calculation independently implemented','provider_calls':0}
 (report/'STATISTICS_VERIFICATION.json').write_text(json.dumps(result,indent=2));print('PASS statistics conditions='+str(len(groups))+' tables='+str(checked)+' bootstrap='+str(bootstrap_rows)+' provider_calls=0')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--partial',action='store_true');main(p.parse_args().partial)
