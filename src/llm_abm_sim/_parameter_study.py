"""Independent fixed-bank parameter paths owned by ConcurrentRobustnessStudy."""
from __future__ import annotations

import fcntl
import hashlib
import json
from pathlib import Path
from typing import Any

from . import _parameter_judgment_bank as bank
from ._parameter_collection import _load, _publish
from .concurrent_message_experiment import (
    _ConcurrentRuntimeKernel,
    _message_user_fit_components,
    _primary_variant_profile,
)
from .decision import DecisionInput, EngageDecision
from .schemas import PeerContext, PlatformContext

RULE = 'sha256-bank-seed-user-message-first53-v1'
WEIGHTS = ((.50,.30,.20),(.65,.15,.20),(.35,.45,.20),(.65,.30,.05),(.35,.30,.35),(.50,.45,.05),(.50,.15,.35))
CONFIGURATIONS = [(f'w{i}-h{h}', w, h) for i,w in enumerate(WEIGHTS) for h in (1,3,6)]
SEEDS = tuple(range(2026091700, 2026091800))


def draw(bank_identity: str, seed: int, user_id: str, message_id: str) -> float:
    digest=hashlib.sha256(bank.canonical([RULE,bank_identity,seed,user_id,message_id])).digest()
    return (int.from_bytes(digest[:7],'big') >> 3) / 2**53


def run(bank_dir: Path, output_dir: Path, maximum_paths: int | None) -> dict[str, Any]:
    bank_dir,output_dir=bank_dir.absolute(),output_dir.absolute()
    closed=bank_dir/'closed-bank.jsonl'
    if not closed.is_file():
        raise ValueError('parameter study requires a closed bank')
    if maximum_paths is not None and (type(maximum_paths) is not int or maximum_paths<1):
        raise ValueError('maximum_paths must be a positive invocation budget')
    prep=_load(bank_dir)
    from ._parameter_evidence import validate_collection
    closure=validate_collection(bank_dir)
    bank.bound(closed,closure['bank_sha256'],'closed bank')
    bank.bound(bank_dir/'collection/attempts.jsonl',closure['attempt_ledger_sha256'],'collection ledger')
    if closure['status']!='complete' or closure['unique_pairs']!=3000 or closure['new_successes']!=1200:
        raise ValueError('closed bank coverage is incomplete')
    if output_dir.is_relative_to(bank_dir) or any(p.is_symlink() for p in (output_dir,*output_dir.parents)):
        raise ValueError('path output must be separate from bank and non-symlink')
    audit=bank.read_json(bank.bound(Path(prep['audit']['path']),prep['audit']['sha256'],'audit'))
    config,prepared,source=bank._inputs(audit)
    records=[json.loads(line) for line in closed.read_text().splitlines()]
    entries={(r['user_id'],r['message_id']):r for r in records}
    universe={(u,m.message_id) for u in prepared.cohort.sample_user_ids for m in config.messages}
    if len(records)!=3000 or len(entries)!=3000 or set(entries)!=universe:
        raise ValueError('bank universe crossed or duplicated')
    decisions={k:EngageDecision.model_validate(r['decision']) for k,r in entries.items()}
    # Verify every complete request before any path starts; each resolve checks it
    # again at its actual time step, rather than trusting a user/message-only key.
    inputs={}
    for (u,m),entry in entries.items():
        message=next(msg for msg in config.messages if msg.message_id==m)
        data=DecisionInput(post=message.as_post(),profile=_primary_variant_profile(prepared.cohort.users_by_id[u]),
            peer_context=PeerContext(),platform_context=PlatformContext(),time_step=0,
            prompt_version=prep['request_condition']['prompt_version'])
        if bank.client_identity(data,prep['request_condition']) != (entry['client_messages_sha256'],entry['client_condition_sha256']):
            raise ValueError('bank client identity differs from runtime')
        inputs[(u,m)]=data
    fits={m.message_id:{u:_message_user_fit_components(m,prepared.cohort.users_by_id[u])
                      for u in prepared.cohort.sample_user_ids} for m in config.messages}
    manifest={'schema_version':'gpt-p0-parameter-study-v1','bank_sha256':closure['bank_sha256'],
        'audit_sha256':prep['audit']['sha256'],'configurations':CONFIGURATIONS,'seeds':SEEDS,
        'collection_closure_sha256':closure['collection_closure_sha256'],
        'realization_rule':RULE,'epsilon':.02,'mc_halfwidth_target':.005,'simultaneous_mean_count':123,
        'provider_calls':0,'exposures_per_path':1800,'production_deploy_eligible':False}
    output_dir.mkdir(parents=True,exist_ok=True)
    manifest_path=output_dir/'study.json'
    if manifest_path.exists():
        if bank.canonical(bank.read_json(manifest_path))!=bank.canonical(manifest):
            raise ValueError('parameter study manifest crossed')
    else:
        _publish(manifest_path,manifest,rows=False)
    lock_path=output_dir/'writer.lock'
    if lock_path.is_symlink():
        raise ValueError('writer lock symlink')
    with lock_path.open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        completed=[]
        executed=0
        for configuration,weights,threshold in CONFIGURATIONS:
            for seed in SEEDS:
                path=output_dir/f'{configuration}-s{seed}.json'
                identity={'bank_sha256':closure['bank_sha256'],'configuration':configuration,'seed':seed}
                if path.exists():
                    document=bank.read_json(path)
                    if document['identity']!=identity or bank.fingerprint(document['path'])!=document['path_sha256']:
                        raise ValueError('persisted parameter path changed')
                    completed.append({'path':path.name,'sha256':bank.file_hash(path)})
                    continue
                if maximum_paths is not None and executed>=maximum_paths:
                    return {'status':'partial','completed_paths':len(completed),'new_paths':executed,'provider_calls':0}
                def resolve(user: Any,message: Any,step: int, *, seed: int = seed) -> dict[str,Any]:
                    key=(user.user_id,message.message_id)
                    entry=entries[key]
                    if bank.client_identity(inputs[key].model_copy(update={'time_step':step}),prep['request_condition']) != (
                        entry['client_messages_sha256'],entry['client_condition_sha256']):
                        raise ValueError('runtime LLM-visible input drift')
                    judgment=decisions[key]
                    value=draw(closure['bank_sha256'],seed,*key) if judgment.engage else None
                    positive=value is not None and value<judgment.probability
                    return {'client_condition_sha256':entry['client_condition_sha256'],
                        'bank_source':entry['source'],'uniform_draw':value,
                        'realized_engage':positive,'realized_action':judgment.action if positive else 'ignore'}
                result=_ConcurrentRuntimeKernel.fixed_judgment_path(config=config,prepared=prepared,weights=weights,
                    neighbor_saturation=threshold,message_fits=fits,resolve=resolve)
                if len(result['terminals'])!=1800 or len(result['barriers'])!=30:
                    raise ValueError('parameter runtime path did not close')
                document={'identity':identity,'path':result,'path_sha256':bank.fingerprint(result)}
                _publish(path,document,rows=False)
                completed.append({'path':path.name,'sha256':bank.file_hash(path)})
                executed+=1
        bank.v2._assert_source_unchanged(source)
        summary={'status':'complete','completed_paths':len(completed),'provider_calls':0,
                 'manifest_sha256':bank.file_hash(manifest_path),'paths':completed}
        _publish(output_dir/'path-manifest.json',summary,rows=False)
        return summary
