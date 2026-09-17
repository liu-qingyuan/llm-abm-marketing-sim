"""Private fixed-input Judgment Bank preparation owned by the Study Interface.

No Provider resources are constructed here. Historical dispositions remain immutable;
this module adds the explicitly approved client-reconstruction acceptance policy.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from . import concurrent_robustness_v2 as v2
from ._concurrent_recovery_judgment import RecoveryJudgmentV1
from .concurrent_message_experiment import _primary_variant_profile
from .decision import DecisionInput
from .prompting import build_engagement_prompt
from .schemas import PeerContext, PlatformContext

AUDIT_SHA256 = '6cc0d88ee6869f78d678723bc49a22de51f01bb74dbdb923b0221ba65c5bf896'
SCHEMA = 'gpt-p0-parameter-preparation-v1'
ACCEPTANCE = 'client-reconstruction-accepted-20260917-v1'
MODEL = 'openai-codex/gpt-5.6-sol'


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def fingerprint(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path) -> Path:
    if not path.is_file() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('input must be a regular non-symlink file')
    return path


def bound(path: Path, expected: str, label: str) -> Path:
    if file_hash(regular(path)) != expected:
        raise ValueError(f'{label} SHA-256 mismatch')
    return path


def read_json(path: Path) -> Any:
    return json.loads(regular(path).read_bytes())


def write_json(path: Path, value: object) -> None:
    path.write_bytes(canonical(value) + b'\n')


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open('wb') as stream:
        for row in rows:
            stream.write(canonical(row) + b'\n')


def client_identity(data: DecisionInput, condition: dict[str, Any]) -> tuple[str, str]:
    """Hash every client-visible message and the frozen observable request settings."""
    messages_hash = fingerprint(build_engagement_prompt(data))
    return messages_hash, fingerprint({'client_messages_sha256': messages_hash, 'request_condition': condition})


def _inputs(audit: dict[str, Any]) -> tuple[Any, Any, Any]:
    manifest = v2.ConcurrentRobustnessManifestV2.model_validate(
        read_json(Path(audit['lineage']['source_manifest']['path']))
    )
    closure = v2._close_source(manifest.source.source_dir)
    # V2 deliberately reuses the V1 structural source validator (same as V2 load).
    v2._validate_source_against_manifest(manifest, closure, manifest.source.source_dir)  # type: ignore[arg-type]
    config = v2._dynamic_runtime_config(closure)
    prepared = v2._prepare_concurrent_runtime_inputs(config)
    sample_hash = hashlib.sha256(json.dumps(
        prepared.cohort.sample_user_ids, ensure_ascii=False, separators=(',', ':')
    ).encode()).hexdigest()
    if sample_hash != audit['frozen_identities']['sample_identity']:
        raise ValueError('sample identity mismatch')
    if v2._effective_graph_identity(prepared) != audit['frozen_identities']['graph_identity_sha256']:
        raise ValueError('graph identity mismatch')
    return config, prepared, closure


def _request_condition(audit: dict[str, Any]) -> dict[str, Any]:
    condition = dict(audit['historical_request_condition'])
    # Cache retention is a historical storage policy, not a transmitted LLM input.
    # Keep it in provenance, not the new bank's request-equivalence identity.
    for key in ('cache_retention', 'decision_store_policy', 'effective_upstream_context_status'):
        condition.pop(key)
    return condition


def prepare(audit_path: Path, output_dir: Path) -> dict[str, Any]:
    """Verify the pinned audit and prepare a new immutable, incomplete bank."""
    audit_path = audit_path.absolute()
    output_dir = output_dir.absolute()
    if output_dir.exists() or any(p.is_symlink() for p in (output_dir, *output_dir.parents)):
        raise ValueError('output must be a new non-symlink directory')
    bound(audit_path, AUDIT_SHA256, 'audit')
    audit = read_json(audit_path)
    expected_counts = {'historical_judgments': 1800, 'missing_pairs': 1200,
                       'eligible_pair_universe': 3000, 'duplicate_pairs': 0, 'conflicting_pairs': 0}
    if any(audit['counts'][key] != value for key, value in expected_counts.items()):
        raise ValueError('audit coverage mismatch')
    for key in ('evidence', 'plan', 'source_bundle', 'ledger_prefix', 'source_manifest'):
        ref = audit['lineage'][key]
        bound(Path(ref['path']), ref['sha256'], key)
    for name, digest in audit['output_hashes'].items():
        bound(audit_path.parent / name, digest, name)
    # Preparation does not change these files. A changed renderer/transport must not
    # quietly rebuild historical input under a different implementation.
    root = Path(__file__).resolve().parents[2]
    for ref in audit['lineage']['implementation_files']:
        path = root / ref['relative_path']
        if (ref['relative_path'] == 'src/llm_abm_sim/concurrent_message_experiment.py'
                and file_hash(regular(path)) != ref['sha256']):
            historical = subprocess.run(
                ['git', 'show', f"{audit['lineage']['implementation_commit']}:{ref['relative_path']}"],
                cwd=root, check=True, capture_output=True,
            ).stdout
            if hashlib.sha256(historical).hexdigest() != ref['sha256']:
                raise ValueError('historical input-owner implementation mismatch')
            names = {'ExperimentalMessageDefinition', '_shared_variant_profile_payload', '_primary_variant_profile',
                     '_prepare_concurrent_runtime_inputs', '_runtime_inputs_from_cohort'}
            def owners(source: str, names: set[str] = names) -> dict[str, str]:
                return {node.name: ast.dump(node, include_attributes=False) for node in ast.parse(source).body
                        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names}
            old_owners, new_owners = owners(historical.decode()), owners(path.read_text())
            if set(old_owners) != names or old_owners != new_owners:
                raise ValueError('client-input owner changed with runtime implementation')
        else:
            bound(path, ref['sha256'], ref['relative_path'])
    protected = [audit_path.parent, *(Path(audit['lineage'][k]['path']).parent
                  for k in ('evidence', 'plan', 'source_bundle', 'ledger_prefix', 'source_manifest'))]
    manifest_source = read_json(Path(audit['lineage']['source_manifest']['path'])).get('source', {})
    if 'source_dir' in manifest_source:
        protected.append(Path(manifest_source['source_dir']))
    if any(output_dir.is_relative_to(path.absolute()) for path in protected):
        raise ValueError('output must be outside source evidence')
    condition = _request_condition(audit)
    checklist = [json.loads(line) for line in
                 (audit_path.parent / 'judgment_evidence_checklist.jsonl').read_text().splitlines()]
    historical = {(r['pair']['user_id'], r['pair']['message_id']): r for r in checklist}
    if len(historical) != 1800:
        raise ValueError('duplicate historical pair')
    origins = {r['historical_judgment']['origin']['event_sequence']: r for r in checklist}
    decisions = {}
    with Path(audit['lineage']['ledger_prefix']['path']).open() as stream:
        for line in stream:
            event = json.loads(line)
            row = origins.get(event['sequence'])
            if row is None:
                continue
            origin = row['historical_judgment']['origin']
            if event['record_sha256'] != origin['event_checksum'] or event['kind'] != 'judgment_persisted':
                raise ValueError('historical origin mismatch')
            j = event['payload']['judgment']
            judgment = RecoveryJudgmentV1.model_validate(j)
            if judgment.judgment_id != row['historical_judgment']['judgment_id']:
                raise ValueError('historical judgment identity mismatch')
            decisions[event['sequence']] = judgment.decision.model_dump(mode='json')
    if len(decisions) != 1800:
        raise ValueError('historical judgments missing')
    config, prepared, closure = _inputs(audit)
    identities: list[dict[str, Any]] = []
    bank: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    try:
        for user_id in sorted(prepared.cohort.sample_user_ids):
            profile = _primary_variant_profile(prepared.cohort.users_by_id[user_id])
            for message in config.messages:
                data = DecisionInput(post=message.as_post(), profile=profile, peer_context=PeerContext(),
                                     platform_context=PlatformContext(), time_step=0,
                                     prompt_version=condition['prompt_version'])
                messages_hash, key = client_identity(data, condition)
                for step in range(1, config.horizon):
                    if client_identity(data.model_copy(update={'time_step': step}), condition) != (messages_hash, key):
                        raise ValueError('LLM-visible input changes across time')
                identity = {'user_id': user_id, 'message_id': message.message_id,
                            'client_messages_sha256': messages_hash, 'client_condition_sha256': key}
                identities.append(identity)
                old = historical.get((user_id, message.message_id))
                if old is None:
                    missing.append(identity)
                    continue
                rebuilt = old['rebuilt_client_input']
                old_condition = dict(old['request_condition'])
                for name in ('decision_input_sha256', 'client_messages_sha256', 'cache_retention',
                             'decision_store_policy', 'effective_upstream_context_status'):
                    old_condition.pop(name, None)
                if old_condition != condition:
                    raise ValueError('historical request settings mismatch')
                if rebuilt['client_messages_sha256'] != messages_hash:
                    raise ValueError('historical client messages mismatch')
                if data.model_copy(update={'time_step': old['pair']['time_step']}).cache_key() != rebuilt['decision_input_sha256']:
                    raise ValueError('historical full decision input mismatch')
                bank.append({**identity, 'decision': decisions[old['historical_judgment']['origin']['event_sequence']],
                             'provenance': old['historical_judgment'], 'source': 'historical',
                             'acceptance_policy': ACCEPTANCE})
        if (len(identities), len(bank), len(missing)) != (3000, 1800, 1200):
            raise ValueError('prepared coverage is not 3000/1800/1200')
        v2._assert_source_unchanged(closure)
        manifest = {'schema_version': SCHEMA, 'status': 'prepared_incomplete_bank',
                    'acceptance_policy': ACCEPTANCE, 'authorization_reference': 'user-direct-execution-20260917',
                    'audit': {'path': str(audit_path), 'sha256': AUDIT_SHA256},
                    'frozen_identities': audit['frozen_identities'], 'request_condition': condition,
                    'historical_request_condition': audit['historical_request_condition'],
                    'source_manifest': audit['lineage']['source_manifest'],
                    'service_time_boundary': audit['service_time_boundary'],
                    'universe': 3000, 'accepted': 1800, 'missing': 1200, 'provider_calls': 0,
                    'client_time_invariance_checks': 3000 * config.horizon,
                    'live_authorization_caps': {'successes': 1200, 'physical': 1262, 'qualification': 2,
                                                'global_retries': 60, 'pair_retries': 2, 'concurrency': 1,
                                                'additional_spend': 0},
                    'production_deploy_eligible': False}
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.parameter-prepare-', dir=output_dir.parent) as temp:
            stage = Path(temp) / 'ready'
            stage.mkdir()
            write_jsonl(stage / 'client-identities.jsonl', identities)
            write_jsonl(stage / 'accepted-bank.jsonl', bank)
            write_jsonl(stage / 'missing-pairs.jsonl', missing)
            write_json(stage / 'preparation.json', manifest)
            hashes = {p.name: file_hash(p) for p in sorted(stage.iterdir())}
            write_json(stage / 'artifact-manifest.json', {'schema_version': SCHEMA, 'sha256': hashes})
            os.rename(stage, output_dir)
        return manifest
    finally:
        v2._assert_source_unchanged(closure)
