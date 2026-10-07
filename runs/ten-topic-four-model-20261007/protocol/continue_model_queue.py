#!/usr/bin/env python3
"""Wait for a bound live process, then run only its remaining preauthorized cells."""
import argparse,json,subprocess,time,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
WORKTREE=ROOT.parents[1]

def live_identity(pid):
 return subprocess.run(['ps','-p',str(pid),'-o','lstart=,args='],capture_output=True,text=True).stdout.strip()
def main(label, independent_after_partial=False):
 binding=json.loads((ROOT/'protocol/active-process-bindings.json').read_text())[label]
 status=ROOT/f'protocol/queue-{label}.json'
 def save(state,**extra):status.write_text(json.dumps({'model':label,'status':state,'binding':binding,**extra},indent=2))
 while True:
  current=live_identity(binding['pid'])
  if not current:break
  if current!=binding['identity']:raise ValueError('PID reused; never infer original execution success')
  save('verified_wait_existing_process')
  time.sleep(60)
 model={'GPT':'openai-codex/gpt-5.6-sol','Gemini':'gemini-3.1-pro','Kimi':'kimi-k3','DeepSeek':'deepseek-flash'}[label]
 slug={'GPT':'gpt-5.6-sol','Gemini':'gemini-3.1-pro','Kimi':'Kimi','DeepSeek':'DeepSeek-V4.1-Flash'}[label]
 start='P1' if label=='GPT' else 'P0';existing=ROOT/f'formal-paths/{start}--{slug}.json'
 if not existing.exists() and not (independent_after_partial and label=='GPT'):
  save('stopped_existing_execution_partial',cause='terminal process did not publish a complete formal cell');return 1
 if existing.exists():
  current=json.loads(existing.read_text())
  if len(current['terminals'])!=1800 or len(current['barriers'])!=30:save('stopped_existing_cell_incomplete');return 1
 else:
  pending=json.loads((ROOT/'protocol/UNKNOWN_PENDING.json').read_text());assert pending['cell']=='GPT/P1' and not pending['automatic_reissue']
  save('independent_remaining_cells_original_unknown_preserved')
 tasks=['P2','P3'] if label=='GPT' else ['P1','P2','P3']
 env=dict(os.environ,PYTHONPATH=str(WORKTREE/'src'),PYTHONDONTWRITEBYTECODE='1')
 for template in tasks:
  target=ROOT/f'formal-paths/{template}--{slug}.json'
  if target.exists():save('stopped_unexpected_existing_cell',template=template);return 1
  script=ROOT/('protocol/run_adaptive_gpt_persistent.py' if label=='GPT' else 'protocol/run_adaptive_other_persistent.py')
  command=[sys.executable,str(script),'--template',template]
  if label!='GPT':command+=['--model',model]
  log=ROOT/f'protocol/{label.lower()}-{template.lower()}-queued-run.log'
  with log.open('x') as output:
   process=subprocess.Popen(command,cwd=WORKTREE,env=env,stdout=output,stderr=subprocess.STDOUT)
   save('running_formal_cell',template=template,pid=process.pid,command=command,log=str(log))
   code=process.wait()
  if code!=0:save('stopped_formal_cell_partial',template=template,exit_status=code,log=str(log));return code
  cell=json.loads(target.read_text());assert len(cell['terminals'])==1800 and len(cell['barriers'])==30
  save('cell_completed_acceptance_pending',template=template)
 save('all_model_cells_executed_acceptance_pending' if existing.exists() else 'remaining_cells_executed_original_cell_unresolved');return 0
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--label',choices=['GPT','Gemini','Kimi','DeepSeek'],required=True);p.add_argument('--independent-after-partial',action='store_true');args=p.parse_args();sys.exit(main(args.label,args.independent_after_partial))
