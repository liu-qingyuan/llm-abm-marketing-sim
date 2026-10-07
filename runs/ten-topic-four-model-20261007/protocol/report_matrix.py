#!/usr/bin/env python3
"""Tables from independently normalized formal records. Partial mode is explicitly provisional."""
import argparse,csv,json,random,collections
from pathlib import Path
from llm_abm_sim import _parameter_judgment_bank as bank
ROOT=Path(__file__).resolve().parents[1]
OLD=Path('/Users/liuqingyuan/work/llm-abm-marketing-sim/outputs/01a08bb3-1446-7f51-8933-cd49b50e9ccb/four-model-final-20260912-verified')
MODELS={'openai-codex/gpt-5.6-sol':'GPT-5.6 Sol','kimi-k3':'Kimi','gemini-3.1-pro':'Gemini 3.1 Pro','deepseek-flash':'DeepSeek V4.1 Flash'}
HISTORICAL={'openai-codex/gpt-5.6-sol':'openai-codex/gpt-5.6-sol','kimi-k3':'kimi-coding/k3-256k','gemini-3.1-pro':'gemini-3.1-pro','deepseek-flash':'deepseek-v4-flash'}

def write_csv(path,rows):
 if not rows:return
 with path.open('w') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def summarize(rows):
 n=len(rows);positive=sum(r['realized_engage'] for r in rows)
 return {'exposures':n,'judgment_positive':sum(r['provider_engage'] for r in rows),'judgment_rate':sum(r['provider_engage'] for r in rows)/n if n else None,'mean_probability':sum(r['provider_probability'] for r in rows)/n if n else None,'mean_confidence':sum(r['provider_confidence'] for r in rows)/n if n else None,'realized_positive':positive,'realized_rate':positive/n if n else None,'campaign_positive_users':len({r['user_id'] for r in rows if r['realized_engage']}),**{a:sum(r['realized_action']==a for r in rows) for a in ['like','comment','share','ignore']}}
def percentile(values,q):
 values=sorted(values);position=(len(values)-1)*q;lo=int(position);hi=min(lo+1,len(values)-1);return values[lo]+(values[hi]-values[lo])*(position-lo)
def main(partial):
 acceptance=bank.read_json(ROOT/'independent-acceptance/ACCEPTANCE_PROGRESS.json')
 expected={(m,f'P{i}') for m in MODELS for i in range(4)};grouped={}
 for ref in acceptance['cells']:
  path=Path(ref['path']);assert bank.file_hash(path)==ref['sha256']
  normalized=Path(ref['normalized_path']);assert bank.file_hash(normalized)==ref['normalized_sha256']
  rows=[json.loads(x) for x in normalized.read_text().splitlines()]
  key=(rows[0]['model'],rows[0]['template']);assert key in expected and key not in grouped and len(rows)==1800;grouped[key]=rows
 if not partial and set(grouped)!=expected:raise ValueError('formal report requires all16 independently accepted conditions')
 out=ROOT/('progress-report' if partial else 'formal-report');out.mkdir(exist_ok=True)
 oldrows=[json.loads(x) for x in (OLD/'realized_terminals.jsonl').read_text().splitlines()];oldgroups=collections.defaultdict(list)
 for r in oldrows:oldgroups[r['requested_model'],r['prompt_variant']].append(r)
 estimates=[];messages=[];segments=[];curves=[];comparisons=[];direct=[]
 sample=next(r for r in bank.read_json(ROOT.parent/'ten-topic-gpt-studies-20261006/preflight-final/samples.json') if r['arm']=='baseline');seeds=set(sample['seed_user_ids'])
 for (model,template),rows in grouped.items():
  dims={'model':MODELS[model],'model_id':model,'template':template};stats=summarize(rows);assert sum(stats[a] for a in ['like','comment','share','ignore'])==1800
  estimates.append({**dims,**stats});old=summarize(oldgroups[HISTORICAL[model],template]);comparisons.append({**dims,'old_model_id':HISTORICAL[model],'old_realized_positive':old['realized_positive'],'new_realized_positive':stats['realized_positive'],'old_realized_rate':old['realized_rate'],'new_realized_rate':stats['realized_rate'],'rate_delta':stats['realized_rate']-old['realized_rate'],'comparison_scope':'joint graph/sample/collection-time effects; DeepSeek explicitly V4 to V4.1'})
  for mid in ['message_1','message_2','message_3']:
   selected=[r for r in rows if r['message_id']==mid];assert len(selected)==600
   messages.append({**dims,'message':mid,**summarize(selected)})
   for seg in ['S1','S2','S3']:segments.append({**dims,'message':mid,'segment':seg,**summarize([r for r in selected if r['segment']==seg])})
   for step in range(30):curves.append({**dims,'message':mid,'batch':step,**summarize([r for r in selected if r['batch']<=step])})
  fixed={(r['user_id'],r['message_id']):r for r in rows if r['batch']==0 and r['user_id'] in seeds};assert len(fixed)==60
  for family,ref in [('prompt_within_model',(model,'P0')),('model_within_prompt',('openai-codex/gpt-5.6-sol',template))]:
   if ref not in grouped:continue
   reference={(r['user_id'],r['message_id']):r for r in grouped[ref] if r['batch']==0 and r['user_id'] in seeds};assert set(reference)==set(fixed)
   for mid in ['all','message_1','message_2','message_3']:
    keys=sorted(k for k in fixed if mid=='all' or k[1]==mid);users=sorted({u for u,m in keys});assert len(users)==20
    for field in ['engage','probability','confidence']:
     diffs={u:sum(float(fixed[k]['provider_'+field])-float(reference[k]['provider_'+field]) for k in keys if k[0]==u)/sum(k[0]==u for k in keys) for u in users};rng=random.Random(20260809);rep=[sum(diffs[users[rng.randrange(len(users))]] for n in users)/len(users) for _ in range(500)]
     direct.append({**dims,'comparison':family,'reference_model_id':ref[0],'reference_template':ref[1],'message':mid,'field':field,'pairs':len(keys),'user_blocks':len(users),'delta':sum(diffs.values())/len(users),'lower_95':percentile(rep,.025),'upper_95':percentile(rep,.975),'bootstrap_iterations':500,'bootstrap_seed':20260809,'scope':'fixed common Batch0 seed-user blocks; not independent simulation repeats'})
 for name,rows in [('conditions.csv',estimates),('messages.csv',messages),('segments-messages.csv',segments),('curves.csv',curves),('old-new.csv',comparisons),('direct-seed-panel.csv',direct)]:write_csv(out/name,rows)
 evidence={'status':'partial_provisional' if set(grouped)!=expected else 'complete_statistics_pending_final_release_acceptance','conditions':len(grouped),'expected_conditions':16,'exposures':len(grouped)*1800,'behavior_seed':20260823,'independent_behavior_repeats':1,'rate_denominator':'actual exposures, wholecell1800/message600; subset denominators explicitly given','rate_is_100seed_mean':False,'bootstrap':{'iterations':500,'seed':20260809,'unit':'common Batch0 seed user with all selected messages','conditional_interval_only':True},'adaptive_paths':'descriptive; no exposure-based/binomial independent-repeat inference','model_display':'Kimi single research model; per-record route preserved','DeepSeek_amendment':'user authorized V4.1 Flash/current deepseek-flash; old V4 comparison contains generation change','shared_normalization':'uses independent acceptance normalized records; independent statistics verifier must re-read original path records','source_acceptance_path':str(ROOT/'independent-acceptance/ACCEPTANCE_PROGRESS.json'),'source_acceptance_sha256':bank.file_hash(ROOT/'independent-acceptance/ACCEPTANCE_PROGRESS.json'),'provider_calls_during_report':0}
 bank.write_json(out/'evidence.json',evidence)
 lines=['# 十话题四模型结果（'+('进行中' if partial else '完整16条件')+'）','',f"独立接纳条件{len(grouped)}/16；曝光{len(grouped)*1800}。单行为seed20260823，结果是整数次数，不是100-seed均值。",'', '| 模型 | 模板 | 互动/曝光 | 互动率 |','|---|---|---:|---:|']
 for r in estimates:lines.append(f"| {r['model']} | {r['template']} | {r['realized_positive']}/{r['exposures']} | {r['realized_rate']:.3%} |")
 lines+=['','共同Batch0配对仅20个seed用户×3消息。采用原500次、seed20260809用户block bootstrap；自适应传播路径仅描述，不将曝光或复用记录视作独立研究重复。','新旧差异同时涉及十话题网络、重选样本、服务时点和部分补采；DeepSeek还包含用户明确授权的V4→V4.1变化。不解释为单一网络或纯模型因果效应。','Kimi统一显示一个研究模型；后台逐条历史路由不改写。S1–S3是原虚拟标签，不是确认的心理画像。','完整判断候选库与实际曝光覆盖分开统计；此报告不宣称48000候选全部补齐。','论文与canonical未修改/部署。后续需同步方法/模型版本与网络P95说明、16条件结果/曲线、判断复用/unknown/费用账本及下载清单。']
 (out/'REPORT.md').write_text('\n'.join(lines)+'\n');print('REPORT conditions='+str(len(grouped))+' provider_calls=0 status='+evidence['status'])
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--partial',action='store_true');main(p.parse_args().partial)
