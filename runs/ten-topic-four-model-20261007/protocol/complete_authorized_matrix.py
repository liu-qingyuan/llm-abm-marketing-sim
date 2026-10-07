#!/usr/bin/env python3
"""Execute only missing authorized cells; recover terminal partials, never restart live work."""
import json,subprocess,sys,os,time,hashlib,shlex
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];WORKTREE=ROOT.parents[1]
MODELS={'GPT':('openai-codex/gpt-5.6-sol','gpt-5.6-sol'),'Gemini':('gemini-3.1-pro','gemini-3.1-pro'),'Kimi':('kimi-k3','Kimi'),'DeepSeek':('deepseek-flash','DeepSeek-V4.1-Flash')}

def inventory_processes():
 lines=subprocess.run(['ps','-axo','pid=,args='],capture_output=True,text=True).stdout.splitlines();workers=set();queues=set()
 for line in lines:
  parts=line.split(None,1)
  if len(parts)!=2 or not parts[1].startswith('/opt/homebrew/') or '/MacOS/Python ' not in parts[1]:continue
  argv=shlex.split(parts[1]);command=' '.join(argv)
  if 'ten-topic-four-model-20261007/protocol/' not in command:continue
  if 'continue_model_queue.py' in command and '--label' in argv:queues.add(argv[argv.index('--label')+1])
  if '--template' not in argv:continue
  template=argv[argv.index('--template')+1]
  model=argv[argv.index('--model')+1] if '--model' in argv else 'openai-codex/gpt-5.6-sol' if 'run_adaptive_gpt' in command else None
  if model:workers.add((model,template))
 return workers,queues

def main():
 auth=json.loads((ROOT/'protocol/UNKNOWN_CONTINUATION_AUTHORIZATION.json').read_text());assert auth['global_physical_cap']==29143
 state=ROOT/'protocol/MATRIX_EXECUTION_PROGRESS.json';jobs={};stopped={};attempted=set();generation=max([200]+[int(q.name.split('-')[2]) for q in (ROOT/'protocol').glob('authorized-matrix-*-*-P*.log')])
 prior=ROOT/'protocol/MATRIX_EXECUTION_STOP_HISTORY.json'
 if prior.exists() and not (ROOT/'protocol/GEMINI_COLLECTION_AUTHORIZATION.json').exists():
  history=json.loads(prior.read_text());stopped={k:v for k,v in history.get('stopped',{}).items() if k=='Kimi/P1'}
 env=dict(os.environ,PYTHONPATH=str(WORKTREE/'src'),PYTHONDONTWRITEBYTECODE='1')
 while True:
  completed=[];live,queues=inventory_processes()
  for key,(process,log) in list(jobs.items()):
   code=process.poll()
   if code is not None:
    log.close();del jobs[key]
    if code!=0:stopped[key]={'exit_status':code,'reason':'recovery/execution exhausted or nonretryable; raw failure retained'}
  for label,(model,slug) in MODELS.items():
   for template in ['P0','P1','P2','P3']:
    key=label+'/'+template;output=ROOT/f'formal-paths/{template}--{slug}.json'
    if output.exists():
     payload=json.loads(output.read_text())
     assert len(payload['terminals'])==1800 and len(payload['barriers'])==30
     completed.append(key);continue
    if key in stopped or key in jobs or (model,template) in live:continue
    journals=list((ROOT/'formal-paths').glob(f'{template}--{slug}-events*.jsonl'))
    if journals:
     checkpoint=max(journals,key=lambda p:p.stat().st_mtime_ns);events=checkpoint.read_text().splitlines()
     if not events:continue
     last=json.loads(events[-1])
     if last.get('kind')!='cell_partial':continue
     digest=hashlib.sha256(checkpoint.read_bytes()).hexdigest()
     if digest in attempted:continue
     attempted.add(digest)
     command=[sys.executable,str(ROOT/'protocol/resume_any_authorized.py'),'--template',template,'--model',model]
    else:
     if label in queues or any(m==model for m,t in live) or any(k.startswith(label+'/') for k in jobs):continue
     # Start only the next missing condition after its predecessor is closed.
     prior=[ROOT/f'formal-paths/P{i}--{slug}.json' for i in range(int(template[1]))]
     if not all(p.exists() for p in prior):continue
     command=[sys.executable,str(ROOT/'protocol/run_adaptive_gpt_persistent.py' if label=='GPT' else ROOT/'protocol/run_adaptive_other_persistent.py'),'--template',template]
     if label!='GPT':command+=['--model',model]
    generation+=1;log_path=ROOT/f'protocol/authorized-matrix-{generation:03}-{label}-{template}.log';log=log_path.open('x')
    process=subprocess.Popen(command,cwd=WORKTREE,env=env,stdout=log,stderr=subprocess.STDOUT);jobs[key]=(process,log)
  state.write_text(json.dumps({'status':'all_cells_executed_acceptance_pending' if len(completed)==16 else 'running_partial','completed':completed,'required':16,'owned_jobs':{k:p.pid for k,(p,log) in jobs.items()},'observed_live_cells':sorted('/'.join(x) for x in live),'stopped':stopped,'original_unknowns_preserved':True,'provider_budget':29143,'unknown_new_collection_authorization':str(ROOT/'protocol/UNKNOWN_CONTINUATION_AUTHORIZATION.json')},indent=2))
  if len(completed)==16:return
  if not jobs and not live and not queues and stopped:print('PARTIAL needs intervention',json.dumps(stopped),flush=True);return
  time.sleep(60)
if __name__=='__main__':main()
