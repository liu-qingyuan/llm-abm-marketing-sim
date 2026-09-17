"""Independent reconstruction of persisted parameter exposure, draws and feedback."""
from __future__ import annotations

import csv
import math
import statistics
from pathlib import Path
from typing import Any

from . import _parameter_judgment_bank as bank
from . import _parameter_study as paths
from ._parameter_collection import _events, _load, _publish, _state
from .concurrent_message_experiment import _message_user_fit_components
from .decision import EngageDecision


def t_quantile(probability: float, df: int = 99) -> float:
    """Invert the Student density with composite Simpson integration (no new dependency)."""
    factor=math.exp(math.lgamma((df+1)/2)-math.lgamma(df/2))/math.sqrt(df*math.pi)
    def cdf(x: float) -> float:
        n=2048
        step=x/n
        total=0.0
        for i in range(n+1):
            weight=1 if i in (0,n) else 4 if i%2 else 2
            total+=weight*factor*(1+(i*step)**2/df)**(-(df+1)/2)
        return .5+total*step/3
    lo,hi=0.0,12.0
    for _ in range(50):
        mid=(lo+hi)/2
        if cdf(mid)<probability:
            lo=mid
        else:
            hi=mid
    return (lo+hi)/2


def _estimate(values: list[float], critical: float) -> dict[str,float]:
    mean=statistics.mean(values)
    sd=statistics.stdev(values)
    se=sd/math.sqrt(len(values))
    return {'mean':mean,'sd':sd,'mcse':se,'lower':mean-critical*se,'upper':mean+critical*se}


def _quantile(values: list[float], p: float) -> float:
    ordered=sorted(values)
    index=(len(ordered)-1)*p
    low=int(index)
    high=min(low+1,len(ordered)-1)
    return ordered[low]+(index-low)*(ordered[high]-ordered[low])


def _csv(path: Path, rows: list[dict[str,Any]]) -> None:
    with path.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def validate_collection(root: Path) -> dict[str, Any]:
    """Independently rebuild collection totals and bank provenance from attempts."""
    import json
    from collections import Counter
    prep = _load(root)
    claimed = bank.read_json(root / 'collection/closure.json')
    ledger = root / 'collection/attempts.jsonl'
    events = _events(ledger, bank.file_hash(root / 'preparation.json'))
    if any(event['sequence'] != i for i, event in enumerate(events)):
        raise ValueError('collection event ordinals crossed')
    intents, accepted, qualified = _state(events)
    settled = [e['payload'] for e in events if e['kind'] == 'settled']
    attempts = Counter(i['pair_key'] for i in intents if i['purpose'] == 'judgment')
    qualifications = sum(i['purpose'] == 'qualification' for i in intents)
    retries = sum(n - 1 for n in attempts.values())
    if (not qualified or len(accepted) != 1200 or len(intents) != len(settled)
            or len(intents) > 1262 or qualifications > 2 or retries > 60
            or any(n > 3 for n in attempts.values())):
        raise ValueError('collection budget/coverage does not close')
    old = [json.loads(line) for line in (root / 'accepted-bank.jsonl').read_text().splitlines()]
    merged = sorted([*old, *accepted.values()], key=lambda r: (r['user_id'], r['message_id']))
    actual = [json.loads(line) for line in (root / 'closed-bank.jsonl').read_text().splitlines()]
    missing = [json.loads(line) for line in (root / 'missing-pairs.jsonl').read_text().splitlines()]
    expected_keys = {bank.fingerprint([r['user_id'], r['message_id']]): r for r in missing}
    if (len(old) != 1800 or len(actual) != 3000 or merged != actual
            or set(accepted) != set(expected_keys)
            or len({(r['user_id'], r['message_id']) for r in actual}) != 3000):
        raise ValueError('closed bank does not match historical origins and settled attempts')
    for key, entry in accepted.items():
        if any(entry[name] != value for name, value in expected_keys[key].items()):
            raise ValueError('top-up client identity differs from prepared missing pair')
        EngageDecision.model_validate(entry['decision'])
    for row in settled:
        accounting = row['accounting']
        if row['outcome'] == 'succeeded':
            if (accounting['provider_response_count'] != 1 or accounting['successful_decision_count'] != 1
                    or accounting['usage_complete_response_count'] != 1
                    or accounting['observed_model_counts'] != {'gpt-5.6-sol': 1}
                    or accounting['output_tokens'] > 256
                    or accounting['input_tokens'] + accounting['output_tokens'] != accounting['total_tokens']):
                raise ValueError('successful attempt accounting does not close')
    rebuilt = {'schema_version': 'gpt-p0-collection-closure-v1', 'status': 'complete',
        'bank_sha256': bank.file_hash(root / 'closed-bank.jsonl'), 'unique_pairs': len(actual),
        'new_successes': len(accepted), 'physical_requests': len(intents),
        'qualification_requests': qualifications, 'retry_requests': retries,
        'attempt_ledger_sha256': bank.file_hash(ledger),
        'known_nominal_cost_usd': sum(row['subscription_nominal_cost_usd'] for row in settled
                                    if row['subscription_nominal_cost_usd'] is not None),
        'nominal_cost_unknown_attempts': sum(row['subscription_nominal_cost_usd'] is None for row in settled),
        'actual_incremental_fee': None, 'production_deploy_eligible': False}
    if claimed != rebuilt:
        raise ValueError('collection closure differs from independently recomputed ledger')
    usage = {name: sum(row['accounting'][name] or 0 for row in settled)
             for name in ('input_tokens', 'output_tokens', 'total_tokens', 'cached_input_tokens')}
    return {**rebuilt, 'known_response_usage': usage,
            'response_usage_missing_attempts': sum(row['accounting']['provider_response_count'] != 1
                                                  or row['accounting']['usage_complete_response_count'] != 1
                                                  for row in settled),
            'collection_closure_sha256': bank.file_hash(root / 'collection/closure.json'),
            'preparation_sha256': bank.file_hash(root / 'preparation.json'),
            'authorization_reference': prep['authorization_reference']}


def close(bank_dir: Path, root: Path) -> dict[str,Any]:
    """Read all 2100 paths, independently reconstruct their selections, then report."""
    prep=_load(bank_dir)
    collection=validate_collection(bank_dir)
    bank.bound(bank_dir/'closed-bank.jsonl',collection['bank_sha256'],'closed bank')
    manifest=bank.read_json(root/'path-manifest.json')
    study=bank.read_json(root/'study.json')
    if manifest['status']!='complete' or manifest['completed_paths']!=2100:
        raise ValueError('parameter Evidence requires 2100 closed paths')
    bank.bound(root/'study.json',manifest['manifest_sha256'],'study manifest')
    if (study['bank_sha256']!=collection['bank_sha256']
            or study['collection_closure_sha256']!=collection['collection_closure_sha256']
            or study['seeds']!=list(paths.SEEDS)
            or study['configurations']!=[[c,list(w),h] for c,w,h in paths.CONFIGURATIONS]):
        raise ValueError('study matrix/seed identity changed')
    import json
    entries={(r['user_id'],r['message_id']):r for r in
             (json.loads(line) for line in (bank_dir/'closed-bank.jsonl').read_text().splitlines())}
    decisions={k:EngageDecision.model_validate(r['decision']) for k,r in entries.items()}
    audit=bank.read_json(bank.bound(Path(prep['audit']['path']),prep['audit']['sha256'],'audit'))
    config,prepared,source=bank._inputs(audit)
    users=prepared.cohort.sample_user_ids
    seed_users=set(prepared.cohort.seed_user_ids)
    fits={m.message_id:{u:_message_user_fit_components(m,prepared.cohort.users_by_id[u])[1] for u in users}
          for m in config.messages}
    references={ref['path']:ref['sha256'] for ref in manifest['paths']}
    expected={f'{c}-s{s}.json' for c,_,_ in paths.CONFIGURATIONS for s in paths.SEEDS}
    if set(references)!=expected or len(manifest['paths'])!=2100:
        raise ValueError('path inventory crossed')
    run_rows=[]
    path_curves={}
    message_ids=[m.message_id for m in config.messages]
    for configuration,weights,threshold in paths.CONFIGURATIONS:
        for seed in paths.SEEDS:
            name=f'{configuration}-s{seed}.json'
            document=bank.read_json(bank.bound(root/name,references[name],'path'))
            expected_identity={'bank_sha256':collection['bank_sha256'],'configuration':configuration,'seed':seed}
            if document['identity']!=expected_identity or bank.fingerprint(document['path'])!=document['path_sha256']:
                raise ValueError('path identity or payload crossed')
            terminal=document['path']['terminals']
            barriers=document['path']['barriers']
            if len(terminal)!=1800 or len(barriers)!=30:
                raise ValueError('wrong path dimensions')
            exposed={m:set() for m in message_ids}
            campaign=set()
            counts={m:0 for m in message_ids}
            old_counts={m:0 for m in message_ids}
            curves=[]
            cursor=0
            for step in range(30):
                before=sorted(campaign)
                positive=set()
                for m in message_ids:
                    # Deliberately do not use Kernel rank/select/commit helpers.
                    scored=[]
                    for u in users:
                        if u in exposed[m]:
                            continue
                        neighbors=len(prepared.neighbors_by_user.get(u,set()) & campaign)
                        score=(weights[0]*prepared.base_network_by_user.get(u,0.)
                               +weights[1]*min(1.,neighbors/threshold)+weights[2]*fits[m][u])
                        scored.append((u,score,neighbors))
                    scored.sort(key=lambda v:(-v[1],v[0]))
                    if step==0:
                        selected=[r for r in scored if r[0] in seed_users]
                        selected+= [r for r in scored if r[0] not in seed_users][:20-len(selected)]
                    else:
                        selected=scored[:20]
                    rows=terminal[cursor:cursor+20]
                    cursor+=20
                    if [r['user_id'] for r in rows]!=[u for u,_,_ in selected]:
                        raise ValueError('persisted exposure differs from independent dynamic ranking')
                    for row,(u,score,neighbors) in zip(rows,selected,strict=True):
                        entry=entries[(u,m)]
                        decision=decisions[(u,m)]
                        value=paths.draw(collection['bank_sha256'],seed,u,m) if decision.engage else None
                        realized=value is not None and value<decision.probability
                        expected_reason=('seed_union' if u in seed_users else 'personalized_topup') if step==0 else 'personalized_top20'
                        facts={'time_step':step,'user_id':u,'message_id':m,'uniform_draw':value,
                               'realized_engage':realized,'realized_action':decision.action if realized else 'ignore',
                               'ranking_score':score,'engaged_neighbor_count':neighbors,'bank_source':entry['source'],
                               'client_condition_sha256':entry['client_condition_sha256'],'selection_reason':expected_reason}
                        if row!=facts:
                            raise ValueError('persisted realization or exposure facts differ')
                        exposed[m].add(u)
                        counts[m]+=int(realized)
                        old_counts[m]+=int(entry['source']=='historical')
                        if realized:
                            positive.add(u)
                campaign.update(positive)
                expected_barrier={'time_step':step,'exposure_count':60,'frozen_positive_user_ids':before,
                    'committed_positive_user_ids':sorted(positive),'campaign_positive_user_count':len(campaign)}
                if barriers[step]!=expected_barrier:
                    raise ValueError('persisted feedback barrier differs')
                curves.append({m:counts[m]/(20*(step+1)) for m in message_ids})
            if any(len(exposed[m])!=600 for m in message_ids):
                raise ValueError('message exposure denominator is not 600')
            run_rows.append({'configuration':configuration,'seed':seed,
                **{m:counts[m]/600 for m in message_ids},'campaign_distinct_positive_users':len(campaign),
                **{f'{m}_historical_exposures':old_counts[m] for m in message_ids}})
            path_curves[(configuration,seed)]=curves
    ordinary=t_quantile(.975)
    corrected=t_quantile(1-.05/(2*123))
    by_key={(r['configuration'],r['seed']):r for r in run_rows}
    comparisons=[]
    trajectory=[]
    rates=[]
    for configuration,weights,threshold in paths.CONFIGURATIONS:
        for m in message_ids:
            values=[by_key[(configuration,s)][m] for s in paths.SEEDS]
            rate=_estimate(values,ordinary)
            rates.append({'configuration':configuration,'network_weight':weights[0],'feedback_weight':weights[1],
                'content_weight':weights[2],'feedback_threshold':threshold,'message':m,**rate,
                'historical_exposure_mean':statistics.mean(by_key[(configuration,s)][f'{m}_historical_exposures'] for s in paths.SEEDS)})
        for i,j in [(message_ids[0],message_ids[1]),(message_ids[0],message_ids[2]),(message_ids[1],message_ids[2])]:
            ds=[by_key[(configuration,s)][i]-by_key[(configuration,s)][j] for s in paths.SEEDS]
            delta=[d-(by_key[('w0-h3',s)][i]-by_key[('w0-h3',s)][j]) for d,s in zip(ds,paths.SEEDS,strict=True)]
            estimate=_estimate(ds,corrected)
            effect=_estimate(delta,corrected)
            direction=('positive' if estimate['lower']>.02 else 'negative' if estimate['upper']<-.02
                       else 'near_zero' if estimate['lower']>=-.02 and estimate['upper']<=.02 else 'undetermined')
            equivalence=('baseline' if configuration=='w0-h3' else
                'equivalent_in_tested_range' if effect['lower']>=-.02 and effect['upper']<=.02 else
                'sensitive' if effect['lower']>.02 or effect['upper']<-.02 else 'undetermined')
            comparisons.append({'configuration':configuration,'contrast':i+'-'+j,
                **{f'difference_{k}':v for k,v in estimate.items()},**{f'delta_{k}':v for k,v in effect.items()},
                'direction':direction,'amplitude':equivalence,
                'difference_ordinary_lower':statistics.mean(ds)-ordinary*estimate['mcse'],
                'difference_ordinary_upper':statistics.mean(ds)+ordinary*estimate['mcse'],
                'delta_ordinary_lower':statistics.mean(delta)-ordinary*effect['mcse'],
                'delta_ordinary_upper':statistics.mean(delta)+ordinary*effect['mcse'],
                'mc_precision_met':max(ordinary*estimate['mcse'],ordinary*effect['mcse'])<=.005,
                'positive_fraction':sum(d>.02 for d in ds)/100,'negative_fraction':sum(d<-.02 for d in ds)/100,
                'near_zero_fraction':sum(-.02<=d<=.02 for d in ds)/100})
        for step in range(30):
            for m in message_ids:
                values=[path_curves[(configuration,s)][step][m] for s in paths.SEEDS]
                trajectory.append({'configuration':configuration,'batch':step+1,'message':m,
                    'mean_cumulative_rate':statistics.mean(values),'seed_q025':_quantile(values,.025),
                    'seed_q975':_quantile(values,.975),'cumulative_exposures':20*(step+1)})
            for i,j in [(message_ids[0],message_ids[1]),(message_ids[0],message_ids[2]),(message_ids[1],message_ids[2])]:
                values=[path_curves[(configuration,s)][step][i]-path_curves[(configuration,s)][step][j] for s in paths.SEEDS]
                trajectory.append({'configuration':configuration,'batch':step+1,'message':i+'-'+j,
                    'mean_cumulative_rate':statistics.mean(values),'seed_q025':_quantile(values,.025),
                    'seed_q975':_quantile(values,.975),'cumulative_exposures':20*(step+1)})
    for row in trajectory:
        row['mean_cumulative_count']=row['mean_cumulative_rate']*row['cumulative_exposures']
        row['seed_count_q025']=row['seed_q025']*row['cumulative_exposures']
        row['seed_count_q975']=row['seed_q975']*row['cumulative_exposures']
    bank.v2._assert_source_unchanged(source)
    report=root/'report'
    if report.exists():
        raise ValueError('report must be new; no overwrite of closed evidence')
    report.mkdir()
    _csv(report/'path-summary.csv',run_rows)
    _csv(report/'parameter-rates.csv',rates)
    _csv(report/'message-contrasts.csv',comparisons)
    _csv(report/'trajectories.csv',trajectory)
    result={'schema_version':'gpt-p0-parameter-evidence-v1','status':'complete','paths':2100,
        'barriers':63000,'exposures':3780000,'independent_selection_and_feedback_reconstruction':True,
        'study_manifest_sha256':manifest['manifest_sha256'],'bank_sha256':collection['bank_sha256'],
        'historical_service_window':prep['service_time_boundary'],
        'new_collection_window':[min(r['collected_at_utc'] for r in entries.values() if r['source']=='topup'),
                                 max(r['collected_at_utc'] for r in entries.values() if r['source']=='topup')],
        'ordinary_t_critical':ordinary,'simultaneous_t_critical':corrected,'df':99,'family_size':123,
        'provider_calls_offline':0,'collection':collection,
        'comparisons':comparisons,'rates':rates,
        'uncertainty_scope':'realization seeds only; fixed bank/sample/graph; adaptive users are not IID pairs',
        'production_deploy_eligible':False}
    _publish(report/'evidence.json',result,rows=False)
    from ._parameter_report import render
    render(report,result,trajectory)
    _publish(report/'artifact-manifest.json',{'sha256':{p.name:bank.file_hash(p) for p in sorted(report.iterdir())}},rows=False)
    return {k:result[k] for k in ('status','paths','barriers','exposures','provider_calls_offline')}
