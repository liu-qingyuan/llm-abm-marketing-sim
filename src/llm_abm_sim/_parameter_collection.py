"""Bounded, append-only collection for the Study-owned GPT-P0 Judgment Bank."""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import _parameter_judgment_bank as bank
from .concurrent_message_experiment import _primary_variant_profile
from .concurrent_robustness_recovery_task import _self_check_input
from .decision import DecisionInput, ProviderDecisionError
from .providers.robustness import PiOpenAIDecisionAdapter
from .schemas import PeerContext, PlatformContext


def _load(root: Path) -> dict[str, Any]:
    artifacts = bank.read_json(root / 'artifact-manifest.json')
    if artifacts['schema_version'] != bank.SCHEMA:
        raise ValueError('preparation schema mismatch')
    for name, digest in artifacts['sha256'].items():
        if Path(name).name != name:
            raise ValueError('non-local preparation artifact')
        bank.bound(root / name, digest, name)
    prep = bank.read_json(root / 'preparation.json')
    if prep['schema_version'] != bank.SCHEMA or prep['audit']['sha256'] != bank.AUDIT_SHA256:
        raise ValueError('preparation identity mismatch')
    return prep


def _events(path: Path, identity: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    previous = identity
    if path.exists():
        bank.regular(path)
        for line in path.read_text().splitlines():
            event = json.loads(line)
            checksum = event.pop('sha256')
            if event['previous_sha256'] != previous or bank.fingerprint(event) != checksum:
                raise ValueError('collection ledger hash mismatch')
            event['sha256'] = checksum
            previous = checksum
            result.append(event)
    return result


def _append(path: Path, events: list[dict[str, Any]], identity: str, kind: str, payload: dict[str, Any]) -> None:
    event = {'sequence': len(events), 'previous_sha256': events[-1]['sha256'] if events else identity,
             'recorded_at_utc': datetime.now(timezone.utc).isoformat(), 'kind': kind, 'payload': payload}
    event['sha256'] = bank.fingerprint(event)
    with path.open('ab') as stream:
        stream.write(bank.canonical(event) + b'\n')
        stream.flush()
        os.fsync(stream.fileno())
    events.append(event)


def _state(events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], bool]:
    intents = []
    accepted = {}
    pending = None
    qualified = False
    for event in events:
        payload = event['payload']
        if event['kind'] == 'intent':
            if pending is not None:
                raise ValueError('unreconciled collection intent')
            pending = payload
            intents.append(payload)
        elif event['kind'] == 'settled':
            if pending is None or payload['intent_sequence'] != pending['intent_sequence']:
                raise ValueError('crossed collection settlement')
            if payload['outcome'] == 'succeeded':
                if pending['purpose'] == 'qualification':
                    qualified = True
                else:
                    key = pending['pair_key']
                    if key in accepted:
                        raise ValueError('duplicate collection success')
                    accepted[key] = {**payload['bank_entry'], 'collection_event_sha256': event['sha256'],
                                     'collected_at_utc': event['recorded_at_utc']}
            elif payload['outcome'] != 'retryable_failure':
                raise ValueError('collection stopped; unknown or nonretryable attempt')
            pending = None
        else:
            raise ValueError('unknown collection ledger event')
    if pending is not None:
        raise ValueError('unreconciled collection intent; no automatic resend')
    return intents, accepted, qualified


def collect(root: Path, client: Any) -> dict[str, Any]:
    """Use the supplied bounded transport; never construct credentials or resources."""
    root = root.absolute()
    prep = _load(root)
    if getattr(client, 'external_provider_client', False) and os.environ.get('LLM_ABM_RUN_LIVE_LLM') != '1':
        raise ValueError('explicit live gate required')
    if getattr(client, 'external_provider_client', False):
        from .providers.pi_subscription import PiSubscriptionProviderClient
        if type(client) is not PiSubscriptionProviderClient:
            raise ValueError('collection requires the exact approved Pi subscription transport')
        if client.response_timeout_seconds != 30.0 or not client.ready:
            raise ValueError('collection transport timeout/readiness differs from frozen contract')
        metadata = client.safe_metadata
        aliases = metadata['requested_model_aliases']
        if (metadata['provider_transport'] != 'openai-codex'
                or metadata['authentication'] != 'local_oauth_subscription'
                or not isinstance(aliases, dict)
                or aliases.get('gpt-5.6-sol') != 'gpt-5.6-sol'
                or metadata['output_token_ceiling_enforcement'] != 'application_fail_closed'):
            raise ValueError('collection transport identity differs from frozen contract')
        audit = bank.read_json(bank.bound(Path(prep['audit']['path']), prep['audit']['sha256'], 'audit'))
        worker = next(r for r in audit['lineage']['implementation_files']
                      if r['relative_path'] == 'scripts/pi_subscription_provider_worker.mjs')
        bank.bound(client._worker_path, worker['sha256'], 'Pi worker implementation')
    scope = root / 'collection'
    for target in (root / 'closed-bank.jsonl', scope / 'closure.json', scope / 'attempts.jsonl'):
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise ValueError('collection output must be a regular non-symlink file')
    scope.mkdir(exist_ok=True)
    if scope.is_symlink():
        raise ValueError('collection scope must not be a symlink')
    lock_path = scope / 'writer.lock'
    if lock_path.is_symlink():
        raise ValueError('collection lock must not be a symlink')
    with lock_path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _collect_locked(root, scope, prep, client)


def _collect_locked(root: Path, scope: Path, prep: dict[str, Any], client: Any) -> dict[str, Any]:
    identity = bank.file_hash(root / 'preparation.json')
    ledger = scope / 'attempts.jsonl'
    events = _events(ledger, identity)
    intents, accepted, qualified = _state(events)
    old = [json.loads(line) for line in (root / 'accepted-bank.jsonl').read_text().splitlines()]
    missing = [json.loads(line) for line in (root / 'missing-pairs.jsonl').read_text().splitlines()]
    expected = {bank.fingerprint([r['user_id'], r['message_id']]): r for r in missing}
    if len(old) != 1800 or len(expected) != 1200 or not accepted.keys() <= expected.keys():
        raise ValueError('collection coverage mismatch')
    caps = prep['live_authorization_caps']
    if caps != {'successes': 1200, 'physical': 1262, 'qualification': 2, 'global_retries': 60,
                'pair_retries': 2, 'concurrency': 1, 'additional_spend': 0}:
        raise ValueError('collection caps changed')
    audit_path = bank.bound(Path(prep['audit']['path']), prep['audit']['sha256'], 'audit')
    audit = bank.read_json(audit_path)
    config, prepared, closure = bank._inputs(audit)
    by_message = {m.message_id: m for m in config.messages}
    condition = prep['request_condition']
    if condition != bank._request_condition(audit):
        raise ValueError('collection request condition differs from audited client contract')
    attempts_by_pair = Counter(i['pair_key'] for i in intents if i['purpose'] == 'judgment')
    retries = sum(max(n - 1, 0) for n in attempts_by_pair.values())

    def invoke(data: DecisionInput, row: dict[str, Any], purpose: str) -> bool:
        nonlocal retries
        key = bank.fingerprint([row.get('user_id', 'qualification'), row.get('message_id', 'qualification')])
        if len(intents) >= caps['physical']:
            raise ValueError('physical request cap reached')
        if purpose == 'qualification':
            if sum(i['purpose'] == purpose for i in intents) >= caps['qualification']:
                raise ValueError('qualification cap reached')
        else:
            n = attempts_by_pair[key]
            if n >= 3 or (n and retries >= caps['global_retries']):
                raise ValueError('retry cap reached')
            retries += int(n > 0)
            attempts_by_pair[key] += 1
        adapter = PiOpenAIDecisionAdapter(prompt_version=condition['prompt_version'], client=client)
        before = {'purpose': purpose, 'pair_key': key, 'client_condition_sha256': row['client_condition_sha256'], 'intent_sequence': len(events)}
        _append(ledger, events, identity, 'intent', before)
        intents.append(before)
        result: dict[str, Any] = {'intent_sequence': before['intent_sequence']}
        retryable = False
        try:
            decision = adapter.decide(data.post, data.profile, data.peer_context, data.platform_context, data.time_step)
            result.update(outcome='succeeded', bank_entry={**row, 'decision': decision.model_dump(mode='json'),
                'source': 'topup', 'acceptance_policy': bank.ACCEPTANCE})
        except ProviderDecisionError as exc:
            retryable = bool(exc.retryable) and purpose != 'qualification'
            result.update(outcome='retryable_failure' if retryable else 'nonretryable_failure',
                          failure_category=exc.failure_category)
        except BaseException:
            # A dispatched request with no trustworthy result remains unknown.
            # Never serialize exception text or invent a zero-cost failure.
            result.update(outcome='unknown', failure_category='response_provenance_unknown')
        result['accounting'] = adapter.provider_accounting.model_dump(mode='json')
        result['subscription_nominal_cost_usd'] = adapter.last_subscription_nominal_cost_usd
        result['actual_incremental_fee'] = None
        _append(ledger, events, identity, 'settled', result)
        if result['outcome'] == 'succeeded':
            if purpose == 'judgment':
                accepted[key] = {**result['bank_entry'], 'collection_event_sha256': events[-1]['sha256'],
                                 'collected_at_utc': events[-1]['recorded_at_utc']}
            return True
        if retryable:
            time.sleep(0.5 * 2 ** max(attempts_by_pair[key] - 1, 0))
            return False
        raise ValueError('collection stopped: ' + result['failure_category'])

    try:
        if not qualified:
            data = _self_check_input()
            msg_hash, key = bank.client_identity(data, condition)
            invoke(data, {'client_messages_sha256': msg_hash, 'client_condition_sha256': key}, 'qualification')
        for row in missing:
            key = bank.fingerprint([row.get('user_id', 'qualification'), row.get('message_id', 'qualification')])
            if key in accepted:
                continue
            data = DecisionInput(post=by_message[row['message_id']].as_post(),
                profile=_primary_variant_profile(prepared.cohort.users_by_id[row['user_id']]),
                peer_context=PeerContext(), platform_context=PlatformContext(), time_step=0,
                prompt_version=condition['prompt_version'])
            if bank.client_identity(data, condition) != (row['client_messages_sha256'], row['client_condition_sha256']):
                raise ValueError('collection client input drift')
            while not invoke(data, row, 'judgment'):
                pass
        if len(accepted) != 1200:
            raise ValueError('incomplete collection')
        merged = sorted([*old, *accepted.values()], key=lambda r: (r['user_id'], r['message_id']))
        if len({(r['user_id'], r['message_id']) for r in merged}) != 3000:
            raise ValueError('closed bank pair conflict')
        bank.v2._assert_source_unchanged(closure)
        closed = root / 'closed-bank.jsonl'
        _publish(closed, merged, rows=True)
        summary = {'schema_version': 'gpt-p0-collection-closure-v1', 'status': 'complete',
                   'bank_sha256': bank.file_hash(closed), 'unique_pairs': len(merged),
                   'new_successes': len(accepted), 'physical_requests': len(intents),
                   'qualification_requests': sum(i['purpose'] == 'qualification' for i in intents),
                   'retry_requests': retries, 'attempt_ledger_sha256': bank.file_hash(ledger),
                   'known_nominal_cost_usd': sum(e['payload']['subscription_nominal_cost_usd'] or 0
                       for e in events if e['kind'] == 'settled'),
                   'nominal_cost_unknown_attempts': sum(e['payload']['subscription_nominal_cost_usd'] is None
                       for e in events if e['kind'] == 'settled'),
                   'actual_incremental_fee': None, 'production_deploy_eligible': False}
        _publish(scope / 'closure.json', summary, rows=False)
        return summary
    finally:
        bank.v2._assert_source_unchanged(closure)


def _publish(target: Path, value: Any, *, rows: bool) -> None:
    descriptor, name = tempfile.mkstemp(prefix='.bank-publish-', dir=target.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        if rows:
            bank.write_jsonl(temporary, value)
        else:
            bank.write_json(temporary, value)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
