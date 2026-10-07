#!/usr/bin/env python3
"""Original GPT route, actual-exposure collection; durable intent prevents silent redispatch."""
import json,os,argparse,shlex
from pathlib import Path
from llm_abm_sim import _parameter_judgment_bank as bank
from llm_abm_sim.concurrent_message_experiment import _prepare_concurrent_runtime_inputs,_primary_variant_profile,_message_user_fit_components,_rank_message_candidates,_select_batch_candidates
from llm_abm_sim.decision import DecisionInput,EngageDecision
from llm_abm_sim.prompting import build_engagement_prompt
from llm_abm_sim.prompt_contracts import CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY
from llm_abm_sim.schemas import PeerContext,PlatformContext
from llm_abm_sim.engagement_realization import EngagementRealizationPolicy
from llm_abm_sim.providers.moonshot import MoonshotOfficialClient
from llm_abm_sim.concurrent_robustness_operator import _new_client
from qualify import LEDGER
from ledger_store import intent_exists,physical_count
from bounded_dispatch import decide_observed
ROOT=Path(__file__).resolve().parents[1]
ORIGINAL=Path('/Users/liuqingyuan/work/llm-abm-marketing-sim')
OLD=ORIGINAL/'outputs/01a08bb3-1446-7f51-8933-cd49b50e9ccb/four-model-final-20260912-verified'
def approval_path():return bank.read_json(ROOT/"protocol/authorization-partial.json")["kimi_credential_reference"]
def main(template,model):
 model_label={"gemini-3.1-pro":"gemini-3.1-pro","kimi-k3":"Kimi","deepseek-flash":"DeepSeek-V4.1-Flash"}[model]
 study_model="kimi-coding/k3-256k" if model=="kimi-k3" else model
 for f in [ORIGINAL/".env",Path(approval_path())]:
  for line in f.read_text().splitlines():
   if "=" in line and not line.lstrip().startswith("#"):
    k,v=line.split("=",1);k=k.removeprefix("export ").strip()
    if k in ["DEEPSEEK_API_KEY","MOONSHOT_API_KEY"]:os.environ[k]=shlex.split(v,comments=True)[0]
 gateway=bank.read_json(Path.home()/".antigravity_tools/gui_config.json")["proxy"];assert gateway["port"]==8045;os.environ["ANTIGRAVITY_API_KEY"]=gateway["api_key"]
 approval=bank.read_json(ROOT/'protocol/authorization-partial.json');assert approval['cash_fee_approval'].startswith('user explicitly')
 assert approval['maximum_physical_requests']==29143
 previous=[json.loads(x) for x in LEDGER.read_text().splitlines()]
 qids={r['request_id'] for r in previous if r.get('purpose')=='qualification' and r.get('model')==model}
 assert any(r['type']=='succeeded' and r['request_id'] in qids for r in previous)
 os.environ['LLM_ABM_RUN_LIVE_LLM']='1'
 prompt=CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.resolve(template)
 initial=bank.read_json(ORIGINAL/'runs/gpt-p0-bank-topup-20260917-authorized-01/preparation.json')
 config,legacy,_=bank._inputs(bank.read_json(Path(initial['audit']['path'])))
 config=config.model_copy(update={'network_scope':'final_collected_topics'})
 p=_prepare_concurrent_runtime_inputs(config)
 accepted=next(r for r in bank.read_json(ROOT.parent/'ten-topic-gpt-studies-20261006/preflight-final/samples.json') if r['arm']=='baseline')
 assert set(p.cohort.sample_user_ids)==set(accepted['sample_user_ids']) and set(p.cohort.seed_user_ids)==set(accepted['seed_user_ids'])
 source_sha=bank.file_hash(OLD/'judgments.jsonl')
 eligibility=bank.read_json(ROOT/'protocol/OLD_ORIGIN_ACCEPTANCE.json');assert eligibility['status']=='origin_and_effective_conditions_verified'
 admissible_old_ids={json.loads(line)['judgment_id'] for line in (ROOT/'protocol/eligible-old-judgment-origins.jsonl').read_text().splitlines()}
 known={}
 for r in [json.loads(x) for x in (OLD/'judgments.jsonl').read_text().splitlines()]:
  if model=='deepseek-flash' or r['requested_model']!=study_model or r['prompt_variant']!=template:continue
  if model=='kimi-k3' and r['successful_attempts'][-1]['provider_route']!='moonshot_official':continue
  assert r['observed_model']==('gemini-pro-agent' if model=='gemini-3.1-pro' else 'kimi-k3')
  assert r['successful_attempts'][-1]['provider_route']==('antigravity_openai_compatible_gateway' if model=='gemini-3.1-pro' else 'moonshot_official')
  assert r['judgment_id'] in admissible_old_ids
  assert r['prompt_canonical_hash']==prompt.canonical_hash and r['prompt_version']==prompt.prompt_version
  m=next(m for m in config.messages if m.message_id==r['message_id'])
  d=DecisionInput(post=m.as_post(),profile=_primary_variant_profile(legacy.cohort.users_by_id[r['user_id']]),peer_context=PeerContext(),platform_context=PlatformContext(),time_step=r['time_step'],prompt_version=prompt.prompt_version)
  known[r['user_id'],r['message_id'],bank.fingerprint(build_engagement_prompt(d))]=r
 proof=bank.read_json(ROOT/'protocol/DRAW_PROOF.json');policy=EngagementRealizationPolicy(source_identity=proof['source_identity'])
 output=ROOT/f'formal-paths/{template}--{model_label}.json';journal=ROOT/f'formal-paths/{template}--{model_label}-events.jsonl'
 if output.exists() or journal.exists():raise ValueError('existing cell: explicit resume audit required; no restart')
 client_cache=None
 output.parent.mkdir(exist_ok=True);positive=set();exposed={m.message_id:set() for m in config.messages};terminals=[];barriers=[];new=0;reused=0
 def event(e):
  with journal.open('a') as f:f.write(json.dumps(e,ensure_ascii=False,sort_keys=True)+'\n');f.flush();os.fsync(f.fileno())
 event({'kind':'cell_started','template':template,'source_judgments_sha256':source_sha,'historical_baseline_gpt_reconstruction_reference':initial['request_condition'],'actual_request_conditions':'per-intent adapter metadata; official Kimi HTTP timeout90, Gemini/DeepSeek timeout30','timeout_seconds':90 if model=='kimi-k3' else 30,'maximum_physical_requests':29143,'cash_fee_limit':None,'source_identity':proof['source_identity']})
 try:
  for step in range(config.horizon):
   frozen=set(positive);committed=set()
   for m in config.messages:
    fits={u:_message_user_fit_components(m,p.cohort.users_by_id[u]) for u in p.cohort.sample_user_ids}
    ranked=_rank_message_candidates(message=m,users_by_id=p.cohort.users_by_id,eligible_user_ids=[u for u in p.cohort.sample_user_ids if u not in exposed[m.message_id]],base_network_by_user=p.base_network_by_user,neighbors_by_user=p.neighbors_by_user,campaign_engaged_user_ids=frozen,weights=(.5,.3,.2),neighbor_saturation=3,message_fit_by_user=fits)
    selected,reasons=_select_batch_candidates(time_step=step,ranked_scores=ranked,seed_user_ids=p.cohort.seed_user_ids,delivery_capacity=20)
    assert len(selected)==20
    for score in selected:
     u=score.user_id
     data=DecisionInput(post=m.as_post(),profile=_primary_variant_profile(p.cohort.users_by_id[u]),peer_context=PeerContext(),platform_context=PlatformContext(),time_step=step,prompt_version=prompt.prompt_version)
     messages=build_engagement_prompt(data);mh=bank.fingerprint(messages);old=known.get((u,m.message_id,mh))
     if old:
      decision=EngageDecision(engage=old['provider_engage'],probability=old['provider_probability'],action=old['provider_action'],reason=old['provider_reason'],confidence=old['provider_confidence'])
      origin={'type':'reused_four_model','path':str(OLD/'judgments.jsonl'),'sha256':source_sha,'judgment_id':old['judgment_id'],'origin':old['origin']};reused+=1
     else:
      request_id=bank.fingerprint({'research':'ten-topic-four-model-20261007','model':model,'template':template,'user':u,'message':m.message_id,'messages_hash':mh})
      if intent_exists(request_id):raise ValueError('previous request intent: no silent resend')
      physical=physical_count()
      if physical>=29143:raise ValueError('physical budget reached')
      if client_cache is None:client_cache=MoonshotOfficialClient(api_key=os.environ['MOONSHOT_API_KEY'],live_enabled=True) if model=='kimi-k3' else _new_client('deepseek-v4-flash' if model=='deepseek-flash' else model,30)
      client=client_cache
      decision,request_id=decide_observed(client,model,data,request_id,u,m.message_id,template)
      origin={'type':'new_formal_exposure','request_id':request_id,'path':str(LEDGER)};new+=1
     realized=policy.realize(decision,user_id=u,message_id=m.message_id)
     row={'time_step':step,'user_id':u,'message_id':m.message_id,'selection_reason':reasons[u],'ranking_score':score.personalized_delivery_score,'engaged_neighbor_count':score.engaged_neighbor_count,'client_messages_sha256':mh,'judgment':decision.model_dump(mode='json'),'judgment_source':origin,'uniform_draw':realized.uniform_draw,'realization_key':realized.realization_key,'realization_status':realized.realization_status,'realized_action':realized.realized_action,'realized_engage':realized.realized_engage}
     terminals.append(row);exposed[m.message_id].add(u)
     if realized.realized_engage:committed.add(u)
     event({'kind':'terminal','terminal':row})
   positive.update(committed);barrier={'time_step':step,'exposure_count':60,'frozen_positive_user_ids':sorted(frozen),'committed_positive_user_ids':sorted(committed),'campaign_positive_user_count':len(positive)};barriers.append(barrier);event({'kind':'barrier','barrier':barrier});print(f'{template} batch={step} exposures={len(terminals)} new={new} reused={reused}',flush=True)
  assert len(terminals)==1800 and len(barriers)==30
  bank.write_json(output,{'schema_version':'ten-topic-four-model-formal-cell-v1','cell_id':template+'::'+model,'terminals':terminals,'barriers':barriers,'new_successful_judgments':new,'reused_judgments':reused,'realization_source_identity':proof['source_identity'],'behavior_seed':20260823,'sample_user_ids':list(p.cohort.sample_user_ids),'seed_user_ids':list(p.cohort.seed_user_ids),'network_source_manifest_sha256':bank.read_json(ROOT/'protocol/PREPARED_CONTRACT.json')['network_source_manifest_sha256'],'independent_acceptance_status':'pending','production_deploy_eligible':False})
  event({'kind':'cell_completed','path_sha256':bank.file_hash(output)});print('COMPLETE',template,flush=True)
 except Exception as exc:
  event({'kind':'cell_partial','error_type':type(exc).__name__,'completed_exposures':len(terminals),'completed_barriers':len(barriers)});print('PARTIAL',template,type(exc).__name__,flush=True);raise
 finally:
  if client_cache is not None:client_cache.close()
if __name__=='__main__':
 arg=argparse.ArgumentParser();arg.add_argument('--template',choices=['P0','P1','P2','P3'],required=True);arg.add_argument('--model',choices=['gemini-3.1-pro','kimi-k3','deepseek-flash'],required=True);args=arg.parse_args();main(args.template,args.model)
