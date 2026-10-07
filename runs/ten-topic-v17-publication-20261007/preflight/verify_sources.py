"""Explicit source hash/admission inspection; no simulation or Provider imports."""
import json,hashlib,datetime
from pathlib import Path
W=Path('/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim');O=Path('/Users/liuqingyuan/work/llm-abm-marketing-sim');OUT=Path(__file__).resolve().parent

def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()

def fact(p):
 assert p.is_file() and not p.is_symlink()
 return {'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size}

def main():
 mainroot=W/'runs/ten-topic-full-pool-20261006/main';gpt=W/'runs/ten-topic-gpt-studies-20261006';ga=W/'runs/ten-topic-gpt-final-acceptance-20261007';four=W/'runs/ten-topic-four-model-20261007'
 bindings={};checks={}
 mm=json.loads((mainroot/'manifest.json').read_text());assert mm['schema_version']=='full-pool-ten-topic-network-replay-v1' and mm['classification']=='offline_formal_judgment_network_intervention' and mm['counts']['exposures']==109200 and mm['counts']['users']==36400 and mm['counts']['batches']==30 and mm['provider_calls']==0 and mm['production_deploy_eligible'] is False
 for e in mm['artifacts']:assert sha(mainroot/e['relative_path'])==e['sha256']
 bindings['whole_sample_manifest']=fact(mainroot/'manifest.json');checks['whole_sample_artifacts']=len(mm['artifacts'])
 a=json.loads((ga/'ACCEPTANCE.json').read_text());assert a['status']=='pass' and a['paths']==2800 and a['exposures']==5040000 and a['barriers']==84000 and not a['unresolved_research_correctness_findings']
 inv=json.loads((ga/'final-artifact-inventory.json').read_text())['final_objects']
 for p,h in inv.items():assert sha(Path(p))==h
 gm=json.loads((gpt/'formal-paths/manifest.json').read_text());assert len(gm['paths'])==2800
 for p,h in gm['paths'].items():assert sha(gpt/'formal-paths'/p)==h
 for key,p in [('gpt_acceptance',ga/'ACCEPTANCE.json'),('gpt_inventory',ga/'final-artifact-inventory.json'),('gpt_path_manifest',gpt/'formal-paths/manifest.json'),('gpt_evidence',gpt/'formal-report/evidence.json')]:bindings[key]=fact(p)
 checks['gpt_formal_paths']=2800
 fa=json.loads((four/'ACCEPTANCE_FINAL.json').read_text());assert fa['status']=='pass_complete_16_conditions_with_disclosures' and fa['conditions']==16 and fa['exposures']==28800 and fa['barriers']==480 and not fa['unresolved_data_authenticity_path_or_statistics_findings']
 fi=json.loads((four/'DELIVERY_INVENTORY.json').read_text())
 for e in fi:assert sha(Path(e['path']))==e['sha256']
 for key,p in [('four_model_acceptance',four/'ACCEPTANCE_FINAL.json'),('four_model_inventory',four/'DELIVERY_INVENTORY.json'),('four_model_bank_manifest',four/'final-bank/manifest.json')]:bindings[key]=fact(p)
 checks['four_model_final_files']=len(fi)
 old=O/'runs/sensitivity-v16-ticket-263-20260920/sensitivity-v16-20260920T113800Z-release-contract.json';c=json.loads(old.read_text());assert c['schema_version']=='abm-report-release-contract-v16' and c['production_deploy_eligible'] is True and c['provider_calls']==0
 for p,h in c['artifact_sha256'].items():assert sha(Path(c['source_directory'])/p)==h
 bindings['protected_v16_contract']=fact(old);checks['protected_v16_files']=len(c['artifact_sha256'])
 result={'status':'explicit_all_four_studies_source_hash_and_acceptance_pass','at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'sources':bindings,'checks':checks,'old_source_eligibility_flags_not_modified':True,'publication_requires_new_v17_admission':True,'provider_calls':0,'public_policy':'new downloads only aggregate statistics/curves/protocol/source summary/workbooks; exclude raw responses/credentials/per-user judgment banks'}
 (OUT/'SOURCE_BINDINGS.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print('PASS sources '+json.dumps(checks)+' provider_calls=0')
if __name__=='__main__':main()
