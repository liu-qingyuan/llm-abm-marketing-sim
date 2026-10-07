#!/usr/bin/env python3
"""Zero-Provider finisher; requires all sixteen cells and no still-live study workers."""
import json,subprocess,sys,time,os,hashlib
from complete_authorized_matrix import ROOT,WORKTREE,MODELS,inventory_processes

def main():
 state=ROOT/'protocol/FINALIZER_STATUS.json'
 expected=[ROOT/f'formal-paths/P{i}--{slug}.json' for model,slug in MODELS.values() for i in range(4)]
 while True:
  workers,queues=inventory_processes()
  complete=[p for p in expected if p.exists()]
  if len(complete)==16 and not workers:break
  progress=json.loads((ROOT/'protocol/MATRIX_EXECUTION_PROGRESS.json').read_text())
  if progress.get('stopped') and not workers and not queues:
   state.write_text(json.dumps({'status':'partial_needs_intervention','completed':len(complete),'stopped':progress['stopped']},indent=2));return 1
  state.write_text(json.dumps({'status':'verified_wait_formal_cells','complete_paths':len(complete),'required':16,'live_cells':sorted('/'.join(x) for x in workers)},indent=2));time.sleep(60)
 env=dict(os.environ,PYTHONPATH=str(WORKTREE/'src'),PYTHONDONTWRITEBYTECODE='1',LLM_ABM_RUN_LIVE_LLM='0');commands=[]
 for script in ['accept_completed_cells.py','close_exposure_bank.py','report_matrix.py','verify_statistics.py','audit_ledger.py','plot_curves.py']:
  command=[sys.executable,str(ROOT/'protocol'/script)];log=ROOT/f'protocol/final-{script}.log'
  with log.open('x') as output:code=subprocess.run(command,cwd=WORKTREE,env=env,stdout=output,stderr=subprocess.STDOUT).returncode
  commands.append({'command':command,'exit_status':code,'log':str(log)})
  if code:state.write_text(json.dumps({'status':'verification_failed','commands':commands},indent=2));return code
 paths=[]
 for p in expected+list((ROOT/'final-bank').glob('*'))+list((ROOT/'formal-report').glob('*'))+list((ROOT/'independent-acceptance').glob('*'))+[ROOT/'ledger-audit/LEDGER_AUDIT.json']:
  if p.is_file():paths.append({'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size})
 (ROOT/'FINAL_DATA_INVENTORY.json').write_text(json.dumps(paths,indent=2));state.write_text(json.dumps({'status':'all16_data_and_statistics_verified_delivery_review_pending','provider_calls_during_finalizer':0,'commands':commands,'inventory_path':str(ROOT/'FINAL_DATA_INVENTORY.json'),'goal_not_marked_complete_by_process':True},indent=2));return 0
if __name__=='__main__':sys.exit(main())
