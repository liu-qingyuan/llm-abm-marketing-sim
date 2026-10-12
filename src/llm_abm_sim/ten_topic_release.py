"""Exact v17 accession of four reviewed ten-topic Formal studies.

Source eligibility flags are historical facts and remain unchanged. Publication
readiness belongs to this new contract, never a forged v15/v16 compatibility view.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SCHEMA = "abm-report-release-contract-v17"
ENDPOINT = "https://abm.q1ngyuan.top/"
_REVISION_SCHEMA = 'abm-report-release-contract-v18'
_REVISION_SHA256: dict[str, str | None] = {
    'four_model_acceptance': '5927d54ce8c8b9a56be3b1f596f469331f1a6f41f28e12f705bc5168eeb1f4e8',
    'four_model_inventory': '89b748c6f7e5a17154ad85491f2df54a364d471074116478a5005f5a139fcd66',
    # Reviewed complete usage and supplier posted cash at cutoff; not a final month invoice.
    'four_model_bank_manifest': '7802d3327372cf260196fa0371a4ca40deaef928f6bd1d48218d33f5c4ecb0af',
}
# Reviewed source identities, not caller-supplied declarations of Formal status.
SOURCE_SHA256 = {'whole_sample_manifest': '26b1bf7b796940952910ccfd78b5b259ff4f22ce48bf131f32be6a306300839d', 'gpt_acceptance': '5df02d59afb8d287257554103af156724f890f5c2b5229ff583df3e10cf4a576', 'gpt_inventory': '906637cc3997732c842996bf20b7d17911c57f8d2f4d2e6cffb3968e945935cd', 'gpt_path_manifest': 'd01006705b1ef826193b86d94c41741669f96b4626b6fd605ee7d505a0a123fa', 'gpt_evidence': '302d20eec48ab8c8d1dd61199fc048df9f8f61b2b002c54f0501f105485651e4', 'four_model_acceptance': '0b17d7df5b0fd55d18ff648a3c7a917d3c86dd43e48ed37e63d5d984dd257831', 'four_model_inventory': '268471c4a479a60eb95298e06896e88089fa788841a4351d7163111c86d6d5c1', 'four_model_bank_manifest': 'cbad2e56f7b615b47e40428bb83d52da43cd44a19f0b712e998e7595ac1aea98', 'protected_v16_contract': '6ef1f9baf777d29223fa1e9fab8d3cd1c86b368162f4f9f7491d86e83db63ef0'}

def _sha(path: Path) -> str:
    path = _physical_source(path)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _physical_source(path: Path) -> Path:
    """Read hash-bound preserved bytes, never rebuild a cleaned historical tree."""
    if path.exists():
        return path
    root = Path(__file__).resolve().parents[2]
    mapping_path = root / 'runs/ten-topic-main-integration-20261008/PRESERVATION_MAPPING.json'
    cleanup_path = root / 'runs/local-storage-cleanup-20261010/LOCAL_STORAGE_MAP.json'
    if not mapping_path.is_file() or not cleanup_path.is_file():
        return path
    mapping = json.loads(mapping_path.read_bytes())
    cleanup = json.loads(cleanup_path.read_bytes())
    exact = {item['old_path']: item['current_path'] for item in cleanup['exact_files']}
    target = Path(exact.get(str(path), mapping['exact_overrides'].get(str(path), str(path))))
    if target == path:
        for route in sorted(mapping['routes'], key=lambda item: -len(item['original_prefix'])):
            prefix = Path(route['original_prefix'])
            if target.is_relative_to(prefix):
                target = Path(route['persistent_prefix']) / target.relative_to(prefix)
                break
    target = Path(exact.get(str(target), str(target)))
    if not target.is_absolute() or '..' in target.parts or not target.is_relative_to(root):
        raise ValueError('Preserved publication source escaped main repository')
    return target


def _bound(path: Path, expected: str) -> dict[str, Any]:
    path = _physical_source(path)
    if (not path.is_file() or path.is_symlink() or path.absolute() != path.resolve()
            or _sha(path) != expected):
        raise ValueError(f'Formal source binding or regular-file identity drift: {path}')
    return json.loads(path.read_bytes())


def accept_ten_topic_sources(*, repo_root: str | Path,
                            source_bindings: Mapping[str, Mapping[str, object]]) -> dict[str, Any]:
    """Admit only the reviewed source bytes and their complete Formal inventories.

    Caller supplies every explicit path/hash. No latest-directory search, Provider
    invocation, simulation, source write, or public disclosure occurs here.
    Returns accepted source facts for Report/Release composition; never deploys.
    """
    root = Path(repo_root).resolve()
    if set(source_bindings) != set(SOURCE_SHA256):
        raise ValueError('Exact four-study source binding set required')
    if source_bindings['four_model_acceptance'].get('sha256') == _REVISION_SHA256['four_model_acceptance']:
        return _accept_revision_sources(root, source_bindings)
    documents = {}
    paths = {}
    for name, expected in SOURCE_SHA256.items():
        reference = source_bindings[name]
        if reference.get('sha256') != expected or not isinstance(reference.get('path'), str):
            raise ValueError(f'Reviewed source binding mismatch: {name}')
        path = Path(str(reference['path'])).absolute()
        physical = _physical_source(path)
        if name != 'protected_v16_contract' and not physical.is_relative_to(root):
            raise ValueError('New source binding escaped the existing worktree')
        documents[name] = _bound(path, expected)
        paths[name] = physical
    main = documents['whole_sample_manifest']
    gpt = documents['gpt_acceptance']
    four = documents['four_model_acceptance']
    if (main['schema_version'] != 'full-pool-ten-topic-network-replay-v1'
            or main['classification'] != 'offline_formal_judgment_network_intervention'
            or main['counts']['exposures'] != 109200 or main['counts']['users'] != 36400
            or main['production_deploy_eligible'] is not False
            or gpt['status'] != 'pass' or gpt['paths'] != 2800
            or gpt['exposures'] != 5040000 or gpt['unresolved_research_correctness_findings']
            or four['status'] != 'pass_complete_16_conditions_with_disclosures'
            or four['conditions'] != 16 or four['exposures'] != 28800
            or four['unresolved_data_authenticity_path_or_statistics_findings']):
        raise ValueError('Reviewed Formal scope or acceptance crossed')
    for item in main['artifacts']:
        path = paths['whole_sample_manifest'].parent / item['relative_path']
        if _sha(path) != item['sha256']:
            raise ValueError('Whole-sample artifact binding drift')
    for name, expected in documents['gpt_inventory']['final_objects'].items():
        if _sha(Path(name)) != expected:
            raise ValueError('GPT final object binding drift')
    gpt_manifest = documents['gpt_path_manifest']
    if len(gpt_manifest['paths']) != 2800:
        raise ValueError('GPT path matrix incomplete')
    for name, expected in gpt_manifest['paths'].items():
        path = paths['gpt_path_manifest'].parent / name
        if _sha(path) != expected:
            raise ValueError('GPT formal path binding drift')
    for item in documents['four_model_inventory']:
        if _sha(Path(item['path'])) != item['sha256']:
            raise ValueError('Four-model final object binding drift')
    protected = documents['protected_v16_contract']
    if protected['schema_version'] != 'abm-report-release-contract-v16':
        raise ValueError('Expected protected historical v16')
    for name, expected in protected['artifact_sha256'].items():
        if _sha(Path(protected['source_directory']) / name) != expected:
            raise ValueError('Protected historical release inventory drift')
    return {'schema_version': 'ten-topic-reviewed-publication-sources-v1',
            'publication_contract_schema': SCHEMA, 'provider_calls': 0,
            'whole_sample': {'users': 36400, 'exposures': 109200, 'behavior_seeds': 1},
            'parameters': {'configurations': 21, 'behavior_seeds': 100, 'paths': 2100},
            'index': {'arms': 7, 'behavior_seeds': 100, 'paths': 700},
            'four_models': {'conditions': 16, 'exposures': 28800, 'behavior_seeds': 1},
            'paths': {name: str(path) for name, path in paths.items()},
            'source_sha256': dict(SOURCE_SHA256),
            'protected_v16_directory': str(_physical_source(Path(protected['source_directory']))),
            'source_eligibility_flags_preserved': True,
            'new_release_and_public_validation_required': True}


def _accept_revision_sources(root: Path, bindings: Mapping[str, Mapping[str, object]]) -> dict[str, Any]:
    """Admit a pinned twenty-condition revision without relaxing v17 admission."""
    if _REVISION_SHA256['four_model_bank_manifest'] is None:
        raise ValueError('v18 requires reviewed cash reconciliation and evidence capsule')
    expected = {**SOURCE_SHA256, **_REVISION_SHA256}
    documents, paths = {}, {}
    for name, sha in expected.items():
        ref = bindings[name]
        path = Path(str(ref.get('path', ''))).absolute()
        physical = _physical_source(path)
        if ref.get('sha256') != sha or (name != 'protected_v16_contract' and not physical.is_relative_to(root)):
            raise ValueError('Reviewed v18 source binding mismatch')
        documents[name], paths[name] = _bound(path, str(sha)), physical
    acceptance = documents['four_model_acceptance']
    manifest = documents['four_model_inventory']
    capsule = documents['four_model_bank_manifest']
    if (acceptance.get('schema_version') != 'ten-topic-model-revision-acceptance-v2'
            or acceptance.get('status') != '12_new_paths_and_8_legacy_controls_verified'
            or acceptance.get('new_conditions') != 12 or acceptance.get('legacy_conditions') != 8
            or acceptance.get('new_exposures') != 21600 or acceptance.get('legacy_exposures') != 14400
            or len(acceptance.get('conditions', [])) != 20
            or acceptance.get('unrecovered_unknown_attempts') != 0
            or acceptance.get('provider_calls_during_verification') != 0
            or acceptance.get('production_deploy_eligible') is not False
            or manifest.get('schema_version') != 'ten-topic-model-revision-manifest-v2'
            or capsule.get('schema_version') != 'ten-topic-reviewed-revision-capsule-v1'):
        raise ValueError('Reviewed v18 Formal scope or independent acceptance gap')
    for item in manifest['files']:
        path = Path(item['path']).absolute()
        if not path.is_relative_to(root) or path.is_symlink() or _sha(path) != item['sha256']:
            raise ValueError('Reviewed v18 Formal inventory drift')
    legacy = capsule['historical_source_bindings']
    if set(legacy) != set(SOURCE_SHA256) or any(legacy[k].get('sha256') != sha for k, sha in SOURCE_SHA256.items()):
        raise ValueError('Exact protected v17 source bindings required')
    historical = accept_ten_topic_sources(repo_root=root, source_bindings=legacy)
    for name in SOURCE_SHA256.keys() - _REVISION_SHA256.keys():
        if bindings[name] != legacy[name]:
            raise ValueError('Whole/parameter/index/historical source change not authorized')
    old = capsule['protected_v17_contract']
    contract = _bound(Path(old['path']), old['sha256'])
    if contract.get('schema_version') != SCHEMA or contract.get('sources') != legacy:
        raise ValueError('Protected v17 contract source mismatch')
    for name, sha in contract['artifact_sha256'].items():
        if _sha(Path(contract['source_directory']) / name) != sha:
            raise ValueError('Protected v17 release inventory drift')
    cash_ref = capsule['cash_reconciliation']
    cash = _bound(Path(cash_ref['path']), cash_ref['sha256'])
    import math
    amount = cash.get('actual_experiment_cash_CNY')
    if (cash.get('schema_version') != 'ten-topic-supplier-cash-reconciliation-v1'
            or cash.get('status') != 'complete_at_supplier_ledger_cutoff'
            or cash.get('exact_requested_SKU') != 'qwen3.8-max'
            or cash.get('workspace_id') != 'llm-sdz7b6ijrlj9pwm1' or cash.get('region') != 'beijing'
            or cash.get('original_account_and_API_key_bound') is not True
            or cash.get('full_experiment_period_and_usage_reconciled') is not True
            or type(amount) not in (int, float) or not math.isfinite(amount) or not 0 <= amount <= 100
            or not cash.get('supplier_evidence')):
        raise ValueError('Actual supplier cash reconciliation not closed')
    for item in cash['supplier_evidence']:
        path = Path(item['path']).absolute()
        if not path.is_relative_to(root) or path.is_symlink() or _sha(path) != item['sha256']:
            raise ValueError('Supplier cash evidence binding drift')
    return {**historical, 'schema_version': 'ten-topic-reviewed-publication-sources-v2',
            'publication_contract_schema': _REVISION_SCHEMA,
            'four_models': {'conditions': 20, 'exposures': 36000, 'behavior_seeds': 1,
                            'new_conditions': 12, 'legacy_conditions': 8},
            'paths': {name: str(path) for name, path in paths.items()}, 'source_sha256': expected,
            'historical_publication_sources': historical,
            'protected_v17_directory': str(_physical_source(Path(contract['source_directory']))),
            'actual_experiment_cash_CNY': amount, 'source_eligibility_flags_preserved': True}


def collect_ten_topic_public_data(accepted_sources: Mapping[str, Any]) -> dict[str, Any]:
    """Project reviewed v17/v18 aggregates through the same public Interface."""
    if accepted_sources.get('schema_version') == 'ten-topic-reviewed-publication-sources-v1':
        return _collect_historical_public_data(accepted_sources)
    if accepted_sources.get('schema_version') != 'ten-topic-reviewed-publication-sources-v2':
        raise ValueError('Accepted publication sources required')
    data = _collect_historical_public_data(accepted_sources['historical_publication_sources'])
    refs = accepted_sources['paths']
    hashes = accepted_sources['source_sha256']
    acceptance = _bound(Path(refs['four_model_acceptance']), hashes['four_model_acceptance'])
    capsule = _bound(Path(refs['four_model_bank_manifest']), hashes['four_model_bank_manifest'])
    map_ref = capsule['sample_segments']
    membership = _bound(Path(map_ref['path']), map_ref['sha256'])
    cells = _revision_raw_cells(acceptance, capsule.get('legacy_exposure_bank'))
    previous = data['models']
    data['models'] = _project_revision_model_paths(acceptance, membership, cells, previous)
    return data


def _revision_raw_cells(acceptance: Mapping[str, Any], bank_ref: Mapping[str, str] | None) -> dict[str, Any]:
    cells = {item['cell_id']: _bound(Path(item['path']), item['sha256']) for item in acceptance['conditions']}
    missing = [cell_id for cell_id, cell in cells.items() if any('judgment' not in row for row in cell['terminals'])]
    if not missing:
        return cells
    if bank_ref is None:
        raise ValueError('Hash-bound historical exposure judgments required')
    path = _physical_source(Path(bank_ref['path']))
    if path.is_symlink() or _sha(path) != bank_ref['sha256']:
        raise ValueError('Historical exposure judgment bank drift')
    records = [json.loads(line) for line in path.read_text().splitlines()]
    lookup = {(item['model'], item['template'], item['user_id'], item['message_id']): item for item in records}
    refs = {item['cell_id']: item for item in acceptance['conditions']}
    for cell_id in missing:
        template, model = cell_id.split('::', 1)
        if model not in ('deepseek-flash', 'openai-codex/gpt-5.6-sol'):
            raise ValueError('New model judgment missing from actual path')
        for row in cells[cell_id]['terminals']:
            item = lookup[model, template, row['user_id'], row['message_id']]
            if item['used_by_path_sha256'] != refs[cell_id]['sha256']:
                raise ValueError('Historical judgment/path identity drift')
            row['judgment'] = item['decision']
    return cells


def _project_revision_model_paths(acceptance: Mapping[str, Any], membership: Mapping[str, Any],
                                  cells: Mapping[str, Any], previous: Mapping[str, Any]) -> dict[str, Any]:
    """Aggregate accepted raw paths without exposing new users or judgments."""
    import random
    from collections import Counter, defaultdict

    from .concurrent_robustness_study import _quantile

    identities = {'gpt-6-sol': 'GPT 6.0', 'gpt-6.1-sol': 'GPT 6.1', 'qwen3.8-max': 'Qwen3.8 Max',
                  'deepseek-flash': 'DeepSeek (historical)', 'openai-codex/gpt-5.6-sol': 'GPT 5.6 (historical)'}
    expected = {f'{template}::{model}' for template in ('P0', 'P1', 'P2', 'P3') for model in identities}
    sample, seeds = membership['sample_user_ids'], membership['seed_user_ids']
    groups = {item['user_id']: item['segment'] for item in membership['segments']}
    if (set(cells) != expected or len(sample) != len(set(sample)) or len(sample) != 1000
            or len(seeds) != len(set(seeds)) or len(seeds) != 20 or not set(seeds) <= set(sample)
            or set(groups) != set(sample) or not set(groups.values()) <= {'S1', 'S2', 'S3'}):
        raise ValueError('Revised publication matrix or original sample membership gap')
    conditions, messages, segments, curves, segment_curves = [], [], [], [], []
    seed_rows = {}
    def statistics(counts, **scope):
        positive = sum(counts[key] for key in ('like', 'comment', 'share'))
        return {**scope, 'exposures': counts['exposures'],
                **{key: counts[key] for key in ('like', 'comment', 'share', 'ignore')},
                'realized_positive': positive,
                'realized_rate': positive / counts['exposures'] if counts['exposures'] else None}
    accepted = {item['cell_id']: item for item in acceptance['conditions']}
    for cell_id in sorted(cells):
        template, original_model = cell_id.split('::', 1)
        model_id = original_model.removeprefix('openai-codex/')
        scope = {'model': identities[original_model], 'model_id': model_id, 'template': template,
                 'source_model_id': original_model,
                 'source_mode': 'new_formal' if original_model in ('gpt-6-sol', 'gpt-6.1-sol', 'qwen3.8-max') else 'accepted_legacy_control'}
        cell = cells[cell_id]
        if (cell['sample_user_ids'] != sample or cell['seed_user_ids'] != seeds
                or len(cell['terminals']) != 1800 or len(cell['barriers']) != 30
                or cell['behavior_seed'] != 20260823):
            raise ValueError('Revised public raw-path scope crossed')
        total, by_message, by_segment, batch = Counter(), defaultdict(Counter), defaultdict(Counter), defaultdict(Counter)
        exposed = set()
        for row in cell['terminals']:
            user, message, step, action = row['user_id'], row['message_id'], row['time_step'], row['realized_action']
            if (user not in groups or message not in ('message_1', 'message_2', 'message_3')
                    or type(step) is not int or not 0 <= step < 30
                    or action not in ('like', 'comment', 'share', 'ignore') or (user, message) in exposed):
                raise ValueError('Revised public exposure identity crossed')
            exposed.add((user, message))
            segment = groups[user]
            for counter in (total, by_message[message], by_segment[message, segment], batch[message, segment, step]):
                counter.update({'exposures': 1, action: 1})
            if step == 0:
                if user not in seeds:
                    raise ValueError('Revised direct panel crossed original seed set')
                seed_rows[cell_id, user, message] = row['judgment']
        summary = statistics(total, **scope)
        if summary['realized_positive'] != accepted[cell_id]['realized_positive']:
            raise ValueError('Revised accepted/public statistics mismatch')
        conditions.append(summary)
        for message in ('message_1', 'message_2', 'message_3'):
            if by_message[message]['exposures'] != 600:
                raise ValueError('Revised message denominator crossed')
            messages.append(statistics(by_message[message], **scope, message=message))
            cumulative = Counter()
            cumulatives = {segment: Counter() for segment in ('S1', 'S2', 'S3')}
            for segment in ('S1', 'S2', 'S3'):
                segments.append(statistics(by_segment[message, segment], **scope, message=message, segment=segment))
            for step in range(30):
                for segment, counts in cumulatives.items():
                    counts.update(batch[message, segment, step])
                    cumulative.update(batch[message, segment, step])
                    segment_curves.append(statistics(counts, **scope, message=message, segment=segment, batch=step))
                curves.append(statistics(cumulative, **scope, message=message, batch=step))
    users = sorted(seeds)
    generator = random.Random(20260809)
    samples = [[generator.randrange(20) for _ in users] for _ in range(500)]
    paired = []
    for cell_id in sorted(cells):
        template, original_model = cell_id.split('::', 1)
        for comparison, reference in [('prompt_within_model', 'P0::' + original_model),
                                      ('model_within_prompt', template + '::openai-codex/gpt-5.6-sol')]:
            for message in ('all', 'message_1', 'message_2', 'message_3'):
                chosen = ('message_1', 'message_2', 'message_3') if message == 'all' else (message,)
                for field in ('engage', 'probability', 'confidence'):
                    diffs = [sum(float(seed_rows[cell_id, user, msg][field])
                                 - float(seed_rows[reference, user, msg][field]) for msg in chosen) / len(chosen)
                             for user in users]
                    estimates = [sum(diffs[index] for index in sampled) / 20 for sampled in samples]
                    paired.append({'model': identities[original_model], 'model_id': original_model.removeprefix('openai-codex/'),
                        'template': template, 'comparison': comparison, 'reference_model_id': reference.split('::', 1)[1].removeprefix('openai-codex/'),
                        'reference_template': reference.split('::', 1)[0], 'message': message, 'field': field,
                        'pairs': 20 * len(chosen), 'user_blocks': 20, 'delta': sum(diffs) / 20,
                        'lower_95': _quantile(estimates, .025), 'upper_95': _quantile(estimates, .975),
                        'bootstrap_iterations': 500, 'bootstrap_seed': 20260809,
                        'scope': 'recomputed original common Batch0 user-block protocol; cross-time controls; not independent simulation repeats'})
    old = {(row['model_id'].removeprefix('openai-codex/'), row['template']): row for row in previous['conditions']}
    comparison = [{**row, 'old_realized_rate': old.get((row['model_id'], row['template']), {}).get('realized_rate'),
                   'comparison_scope': 'historical control reused, not fresh evidence' if row['source_mode'] == 'accepted_legacy_control'
                       else 'new model; no same-model historical counterpart; adaptive cross-time comparison'} for row in conditions]
    return {'conditions': conditions, 'messages': messages, 'segments': segments,
            'curves': curves, 'segment_curves': segment_curves, 'paired_seed': paired, 'comparison': comparison}


def _collect_historical_public_data(accepted_sources: Mapping[str, Any]) -> dict[str, Any]:
    """Project accepted aggregate records, deriving displayed denominators and rates.

    No user-level judgments, raw responses, credentials, or private diagnostics are
    returned. Stored estimates remain conditional 100-behavior-seed statistics.
    """
    import csv
    import statistics
    from collections import Counter, defaultdict

    if accepted_sources.get('schema_version') != 'ten-topic-reviewed-publication-sources-v1':
        raise ValueError('Accepted publication sources required')
    paths = accepted_sources['paths']
    main = Path(paths['whole_sample_manifest']).parent
    gpt = Path(paths['gpt_evidence']).parent
    four = Path(paths['four_model_acceptance']).parent

    def rows(path: Path) -> list[dict[str, Any]]:
        with path.open(encoding='utf-8-sig', newline='') as stream:
            result = list(csv.DictReader(stream))
        for row in result:
            for key, value in list(row.items()):
                if value == '':
                    row[key] = None
                else:
                    try:
                        row[key] = int(value)
                    except ValueError:
                        try:
                            row[key] = float(value)
                        except ValueError:
                            pass
        return result

    projection = rows(main / 'full-pool-realized-projection.csv')
    by_group: dict[tuple[str, str], Counter] = defaultdict(Counter)
    total: Counter = Counter()
    for row in projection:
        counts = {'exposures': row['Exposure'], 'like': row['Total Likes'],
                  'comment': row['Total Comments'], 'share': row['Total Shares']}
        counts['ignore'] = counts['exposures'] - sum(counts[k] for k in ('like', 'comment', 'share'))
        if counts['ignore'] < 0:
            raise ValueError('Whole-sample mutually exclusive actions crossed')
        by_group[row['Message'], row['Segment']].update(counts)
        total.update(counts)
    if total['exposures'] != 109200:
        raise ValueError('Whole-sample public denominator drift')
    whole_rows = []
    for (message, segment), counts in sorted(by_group.items()):
        item = dict(counts, message=message, segment=segment)
        for action in ('like', 'comment', 'share', 'ignore'):
            item[action + '_rate'] = counts[action] / counts['exposures']
        item['realized_rate'] = sum(counts[k] for k in ('like', 'comment', 'share')) / counts['exposures']
        whole_rows.append(item)
    comparison = rows(main / 'curve-comparison.csv')
    trajectories: dict[tuple[str, int], dict[str, Any]] = defaultdict(dict)
    for row in comparison:
        key = row['message_id'], row['batch']
        trajectories[key][row['action']] = row['new_cumulative']
    whole_curves = []
    for (message, batch), counts in sorted(trajectories.items()):
        exposures = 36400 if batch == 30 else 1214 * batch
        positive = sum(counts[k] for k in ('like', 'comment', 'share'))
        whole_curves.append({'message': message, 'batch': batch, 'exposures': exposures,
                             'realized_positive': positive, 'realized_rate': positive / exposures,
                             **counts})
    estimates = rows(gpt / 'arm-parameter-estimates.csv')
    metrics = rows(gpt / 'old-new-path-metrics.csv')
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in metrics:
        grouped[row['study'], row['configuration'], row['message']].append(row)
        if sum(row['new_' + k] for k in ('like', 'comment', 'share', 'ignore')) != row['new_exposures']:
            raise ValueError('Sensitivity public action denominator drift')
    for estimate in estimates:
        selected = grouped[estimate['study'], estimate['configuration'], estimate['message']]
        metric = estimate['metric']
        column = 'new_' + ('engagement_rate' if metric == 'engagement_rate' else metric)
        if len(selected) != 100 or estimate['n'] != 100:
            raise ValueError('Sensitivity statistic is not a 100-seed mean')
        if abs(statistics.mean(r[column] for r in selected) - estimate['mean']) > 1e-10:
            raise ValueError('Sensitivity published mean drift')
    curves = rows(gpt / 'old-new-mean-curves.csv')
    model_conditions = rows(four / 'formal-report/conditions.csv')
    if len(model_conditions) != 16:
        raise ValueError('Four-model public matrix incomplete')
    for row in model_conditions:
        if row['exposures'] != 1800 or sum(row[k] for k in ('like', 'comment', 'share', 'ignore')) != 1800:
            raise ValueError('Four-model public denominator drift')
        if abs(row['realized_positive'] / 1800 - row['realized_rate']) > 1e-12:
            raise ValueError('Four-model realized rate drift')
    model_labels = {r['model_id']: r['model'] for r in model_conditions}
    segment_batches: dict[tuple[str, str, str, str, int], Counter] = defaultdict(Counter)
    model_acceptance = json.loads((four / 'independent-acceptance/ACCEPTANCE_PROGRESS.json').read_bytes())
    if model_acceptance['verified_conditions'] != 16:
        raise ValueError('Bound model normalization matrix incomplete')
    for reference in model_acceptance['cells']:
        source = _physical_source(Path(reference['normalized_path']))
        if _sha(source) != reference['normalized_sha256']:
            raise ValueError('Bound model normalization source drift')
        for line in source.read_text().splitlines():
            event = json.loads(line)
            key = event['model'], event['template'], event['message_id'], event['segment'], event['batch']
            segment_batches[key]['exposures'] += 1
            segment_batches[key][event['realized_action']] += 1
    segment_curves = []
    groups = sorted({k[:4] for k in segment_batches})
    for model, template, message, segment in groups:
        cumulative: Counter = Counter()
        for batch in range(30):
            cumulative.update(segment_batches[model, template, message, segment, batch])
            positive = sum(cumulative[k] for k in ('like', 'comment', 'share'))
            segment_curves.append({'model': model_labels[model], 'model_id': model,
                                   'template': template, 'message': message, 'segment': segment,
                                   'batch': batch, **dict(cumulative),
                                   'realized_positive': positive,
                                   'realized_rate': positive / cumulative['exposures']
                                   if cumulative['exposures'] else None})
    network = json.loads((four / 'FINAL_CORROBORATION.json').read_bytes())
    prepared = json.loads((four / 'protocol/PREPARED_CONTRACT.json').read_bytes())
    sample_reference = prepared['sample_reference']
    if _sha(Path(sample_reference['path'])) != sample_reference['sha256']:
        raise ValueError('Accepted sample reference drift')
    samples = json.loads(_physical_source(Path(sample_reference['path'])).read_bytes())
    baseline_ids = set(next(r['sample_user_ids'] for r in samples if r['arm'] == 'baseline'))
    rebuilt_ids = set(next(r['sample_user_ids'] for r in samples if r['arm'] == 'local_p99_rebuilt'))
    rebuilt_overlap = len(baseline_ids & rebuilt_ids)
    return {'schema_version': 'ten-topic-public-statistics-v1',
            'network': {k: network[k] for k in ('p95', 'actual_ten_topic_names', 'raw_graph_identity',
                                                'holdout_excluded', 'history_comments', 'history_videos')},
            'whole': {'summary': dict(total), 'rows': whole_rows, 'curves': whole_curves},
            'parameters': {'estimates': [r for r in estimates if r['study'] == 'parameters'],
                           'curves': [r for r in curves if r['study'] == 'parameters'],
                           'paired': rows(gpt / 'parameter-message-contrasts.csv')},
            'index': {'local_p99_rebuilt_overlap': rebuilt_overlap, 'estimates': [r for r in estimates if r['study'] == 'index'],
                      'curves': [r for r in curves if r['study'] == 'index'],
                      'paired': rows(gpt / 'index-paired-estimates.csv'),
                      'composition': rows(gpt / 'sample-composition.csv')},
            'models': {'conditions': model_conditions, 'messages': rows(four / 'formal-report/messages.csv'),
                       'segments': rows(four / 'formal-report/segments-messages.csv'),
                       'curves': rows(four / 'formal-report/curves.csv'), 'segment_curves': segment_curves,
                       'paired_seed': rows(four / 'formal-report/direct-seed-panel.csv'),
                       'comparison': rows(four / 'formal-report/old-new.csv')},
            'download_links': []}


_CONTRACT_FIELDS = {'schema_version', 'release_purpose', 'release_id', 'source_directory',
                    'implementation_commit', 'canonical_endpoint', 'sources', 'workbook',
                    'artifact_sha256', 'release_identity_sha256', 'production_deploy_eligible',
                    'provider_calls'}
PURPOSE = 'reviewed_ten_topic_four_studies_with_protected_single_topic_history'


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def _digest(value: Any) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _validate_workbook(path: Path, expected_sha: str, data: dict[str, Any]) -> None:
    """Decode exported XLSX independently and compare every typed aggregate cell."""
    import math
    import posixpath
    import xml.etree.ElementTree as ET
    import zipfile

    from .ten_topic_report import ten_topic_workbook_tables

    if not path.is_file() or path.is_symlink() or _sha(path) != expected_sha:
        raise ValueError('Publication workbook binding drift')
    ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    rns = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    expected = ten_topic_workbook_tables(data)
    with zipfile.ZipFile(path) as archive:
        shared = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            shared = [''.join(t.text or '' for t in v.findall('.//s:t', ns))
                      for v in ET.fromstring(archive.read('xl/sharedStrings.xml'))]
        relationships = {e.attrib['Id']: e.attrib['Target'] for e in
                         ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))}
        sheets = ET.fromstring(archive.read('xl/workbook.xml')).findall('s:sheets/s:sheet', ns)
        if {s.attrib['name'] for s in sheets} != set(expected):
            raise ValueError('Workbook study sheet set crossed')
        for sheet in sheets:
            name = sheet.attrib['name']
            target = relationships[sheet.attrib['{' + rns + '}id']]
            target = target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/' + target)
            cells = {}
            for cell in ET.fromstring(archive.read(target)).findall('.//s:sheetData/s:row/s:c', ns):
                kind = cell.attrib.get('t')
                value = cell.find('s:v', ns)
                text = value.text if value is not None else None
                if kind == 's':
                    parsed = shared[int(text)]
                elif kind == 'inlineStr':
                    parsed = ''.join(x.text or '' for x in cell.findall('.//s:t', ns))
                elif kind == 'b':
                    parsed = text == '1'
                elif text is None:
                    parsed = None
                elif kind == 'str':
                    parsed = text
                else:
                    parsed = float(text)
                cells[cell.attrib['r']] = parsed
            rows = expected[name]
            columns = list(dict.fromkeys(k for row in rows for k in row))
            matrix = [columns, *[[row.get(k) for k in columns] for row in rows]]
            expected_addresses = set()
            for row_index, row in enumerate(matrix, 1):
                for column, wanted in enumerate(row, 1):
                    letters = ''
                    n = column
                    while n:
                        n, digit = divmod(n - 1, 26)
                        letters = chr(65 + digit) + letters
                    address = letters + str(row_index)
                    expected_addresses.add(address)
                    actual = cells.get(address)
                    if isinstance(wanted, (float, int)) and not isinstance(wanted, bool):
                        valid = isinstance(actual, (float, int)) and math.isclose(actual, wanted, rel_tol=1e-12, abs_tol=1e-10)
                    else:
                        valid = actual == wanted
                    if not valid:
                        raise ValueError(f'Workbook cell/source mismatch: {name}!{address}')
            if any(v is not None and k not in expected_addresses for k, v in cells.items()):
                raise ValueError('Unexpected public workbook data')


def _materialize_ten_topic(root: Path, sources: Mapping[str, Mapping[str, object]],
                           workbook: Mapping[str, str], release_id: str, commit: str):
    from .concurrent_robustness_report import _REPORT_PRESENTATION
    from .ten_topic_report import ten_topic_public_downloads

    accepted = accept_ten_topic_sources(repo_root=root, source_bindings=sources)
    if accepted['publication_contract_schema'] == _REVISION_SCHEMA:
        return _materialize_revision(root, sources, workbook, release_id, commit, accepted)
    data = collect_ten_topic_public_data(accepted)
    _validate_workbook(Path(workbook['path']), workbook['sha256'], data)
    downloads = ten_topic_public_downloads(data)
    downloads['ten-topic/ten-topic-research.xlsx'] = Path(workbook['path']).read_bytes()
    data['download_links'] = [{'path': name, 'label': name.removeprefix('ten-topic/')} for name in sorted(downloads)]
    downloads['ten-topic/public-statistics.json'] = _json_bytes(data)
    data['download_links'].append({'path': 'ten-topic/public-statistics.json', 'label': 'Public statistics JSON'})
    base = Path(accepted['protected_v16_directory'])
    old = json.loads(Path(str(sources['protected_v16_contract']['path'])).read_bytes())
    report = _REPORT_PRESENTATION.render_ten_topic_research((base / 'report.html').read_bytes(), data, release_id=release_id)
    public_sources = {'schema_version': 'ten-topic-public-source-map-v1',
                      'network': data['network'], 'studies': {k: accepted[k] for k in ('whole_sample', 'parameters', 'index', 'four_models')},
                      'source_sha256': accepted['source_sha256'], 'source_eligibility_preserved': True,
                      'publication_provider_calls': 0, 'actual_deepseek_model': 'deepseek-flash / V4.1 Flash',
                      'gemini_observed_alias': 'gemini-pro-agent;hidden context not observed'}
    downloads['ten-topic/source-map.json'] = _json_bytes(public_sources)
    downloads['single-topic-report.html'] = (base / 'report.html').read_bytes()
    downloads['single-topic-artifact-manifest.json'] = (base / 'artifact_manifest.json').read_bytes()
    data['download_links'].append({'path': 'ten-topic/source-map.json', 'label': 'Formal source map JSON'})
    report = _REPORT_PRESENTATION.render_ten_topic_research((base / 'report.html').read_bytes(), data, release_id=release_id)
    content = {name: digest for name, digest in old['artifact_sha256'].items() if name not in {'report.html', 'artifact_manifest.json'}}
    if set(content) & set(downloads):
        raise ValueError('New public downloads overlap protected historical files')
    content.update({name: hashlib.sha256(payload).hexdigest() for name, payload in downloads.items()})
    content['report.html'] = hashlib.sha256(report).hexdigest()
    identity = _digest({'schema': SCHEMA, 'release_id': release_id, 'implementation_commit': commit,
                        'sources': sources, 'workbook': workbook, 'content_sha256': content})
    old_manifest = json.loads((base / 'artifact_manifest.json').read_bytes())
    approved = old_manifest['approved_downloads']
    if isinstance(approved, dict):
        approved = list(approved.values())
    manifest = {'schema_version': 'abm-report-release-manifest-v17', 'release_contract_schema': SCHEMA,
                'release_id': release_id, 'release_identity_sha256': identity, 'implementation_commit': commit,
                'production_deploy_eligible': True, 'provider_calls': 0, 'content_sha256': content,
                'approved_downloads': sorted(set(approved) | set(downloads)),
                'protected_v16_release_identity': old['release_identity_sha256'],
                'public_policy': 'new artifacts aggregate only;no new raw responses/credentials/user judgment bank'}
    files = {**downloads, 'report.html': report, 'artifact_manifest.json': _json_bytes(manifest)}
    hashes = {**content, 'artifact_manifest.json': _digest(manifest)}
    return base, files, hashes, identity


def _schema_for_sources(sources: Mapping[str, Mapping[str, object]]) -> str:
    return (_REVISION_SCHEMA if sources.get('four_model_acceptance', {}).get('sha256')
            == _REVISION_SHA256['four_model_acceptance'] else SCHEMA)


def _materialize_revision(root: Path, sources: Mapping[str, Mapping[str, object]],
                          workbook: Mapping[str, str], release_id: str, commit: str,
                          accepted: Mapping[str, Any]):
    from .ten_topic_report import render_ten_topic_research, ten_topic_public_downloads

    data = collect_ten_topic_public_data(accepted)
    _validate_workbook(Path(workbook['path']), workbook['sha256'], data)
    downloads = ten_topic_public_downloads(data)
    downloads['ten-topic/ten-topic-research.xlsx'] = Path(workbook['path']).read_bytes()
    capsule = _bound(Path(str(sources['four_model_bank_manifest']['path'])), str(sources['four_model_bank_manifest']['sha256']))
    old_ref = capsule['protected_v17_contract']
    old = _bound(Path(old_ref['path']), old_ref['sha256'])
    base = Path(accepted['protected_v17_directory'])
    preserved = dict(old['artifact_sha256'])
    replaced_downloads = set(downloads) | {'ten-topic/source-map.json', 'ten-topic/public-statistics.json'}
    for name, sha in old['artifact_sha256'].items():
        if name.startswith('ten-topic/'):
            alias = 'ten-topic-v17/' + name.removeprefix('ten-topic/')
            downloads[alias] = (base / name).read_bytes()
            if hashlib.sha256(downloads[alias]).hexdigest() != sha:
                raise ValueError('Protected v17 download byte drift')
            if name in replaced_downloads:
                preserved.pop(name)
    for name in ('report.html', 'artifact_manifest.json'):
        downloads['ten-topic-v17-' + name] = (base / name).read_bytes()
        preserved.pop(name)
    downloads['ten-topic/source-map.json'] = _json_bytes({
        'schema_version': 'ten-topic-public-source-map-v2', 'source_sha256': accepted['source_sha256'],
        'studies': {key: accepted[key] for key in ('whole_sample', 'parameters', 'index', 'four_models')},
        'source_eligibility_preserved': True, 'publication_provider_calls': 0,
        'new_conditions': 12, 'historical_conditions': 8,
        'actual_experiment_cash_CNY': accepted['actual_experiment_cash_CNY'],
        'identity_scope': 'native GPT response-ID tracing; undated Max SKU; historical control grain retained',
        'protected_v17_identity': old['release_identity_sha256'],
    })
    data['download_links'] = [{'path': name, 'label': name} for name in sorted(downloads)]
    data['download_links'].append({'path': 'ten-topic/public-statistics.json', 'label': 'Public statistics JSON'})
    downloads['ten-topic/public-statistics.json'] = _json_bytes(data)
    shell = Path(accepted['protected_v16_directory']) / 'report.html'
    report = render_ten_topic_research(shell.read_bytes(), data, release_id=release_id)
    for name in set(preserved) & set(downloads):
        if hashlib.sha256(downloads[name]).hexdigest() != preserved[name]:
            raise ValueError('v18 changed a protected historical file')
    content = {**preserved, **{name: hashlib.sha256(value).hexdigest() for name, value in downloads.items()},
               'report.html': hashlib.sha256(report).hexdigest()}
    identity = _digest({'schema': _REVISION_SCHEMA, 'release_id': release_id,
                        'implementation_commit': commit, 'sources': sources, 'workbook': workbook,
                        'content_sha256': content})
    old_manifest = json.loads((base / 'artifact_manifest.json').read_bytes())
    approved = old_manifest['approved_downloads']
    if isinstance(approved, dict):
        approved = list(approved.values())
    manifest = {'schema_version': 'abm-report-release-manifest-v18', 'release_contract_schema': _REVISION_SCHEMA,
                'release_id': release_id, 'release_identity_sha256': identity, 'implementation_commit': commit,
                'production_deploy_eligible': True, 'provider_calls': 0, 'content_sha256': content,
                'approved_downloads': sorted(set(approved) | set(downloads)),
                'protected_v17_release_identity': old['release_identity_sha256'],
                'public_policy': 'new aggregates only; legacy v17 byte-preserved; no new user judgments/credentials'}
    files = {**downloads, 'report.html': report, 'artifact_manifest.json': _json_bytes(manifest)}
    return base, files, {**content, 'artifact_manifest.json': _digest(manifest)}, identity


def promote_ten_topic_release(*, repo_root: str | Path, source_bindings: Mapping[str, Mapping[str, object]],
                              workbook: Mapping[str, str], destination_dir: str | Path,
                              release_id: str, implementation_commit: str) -> Path:
    """Create the immutable v17 publication from explicit reviewed sources, never deploy."""
    import os
    import re
    import shutil
    import tempfile

    root = Path(repo_root).resolve()
    destination = Path(destination_dir).absolute()
    contract_path = destination.with_name(destination.name + '-release-contract.json')
    if (destination.is_symlink() or destination != destination.resolve() or not destination.is_relative_to(root)
            or destination.exists() or contract_path.exists()
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,159}', release_id)
            or not re.fullmatch(r'[0-9a-f]{40}', implementation_commit)):
        raise ValueError('Invalid or overlapping immutable release destination/identity')
    for ref in source_bindings.values():
        if destination.is_relative_to(Path(str(ref['path'])).parent):
            raise ValueError('Release destination overlaps an input')
    if set(workbook) != {'path', 'sha256'}:
        raise ValueError('Exact workbook binding required')
    base, files, hashes, identity = _materialize_ten_topic(root, source_bindings, workbook, release_id, implementation_commit)
    if base.is_relative_to(destination) or destination.is_relative_to(base):
        raise ValueError('Protected release overlap')
    contract = {'schema_version': _schema_for_sources(source_bindings), 'release_purpose': PURPOSE, 'release_id': release_id,
                'source_directory': str(destination), 'implementation_commit': implementation_commit,
                'canonical_endpoint': ENDPOINT, 'sources': dict(source_bindings), 'workbook': dict(workbook),
                'artifact_sha256': hashes, 'release_identity_sha256': identity,
                'production_deploy_eligible': True, 'provider_calls': 0}
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.v17-', dir=destination.parent))
    installed = False
    try:
        shutil.copytree(base, staging, dirs_exist_ok=True)
        for folder in [staging, *(p for p in staging.rglob('*') if p.is_dir())]:
            folder.chmod(0o755)
        for name, payload in files.items():
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                target.chmod(0o644)
            target.write_bytes(payload)
        from .concurrent_robustness_revised import inventory
        if {k: v['sha256'] for k, v in inventory(staging).items()} != hashes:
            raise ValueError('Staged v17 inventory drift')
        for target in staging.rglob('*'):
            if target.is_file():
                target.chmod(0o444)
        with contract_path.open('xb') as stream:
            installed = True
            stream.write(_json_bytes(contract))
        contract_path.chmod(0o444)
        os.rename(staging, destination)
    except BaseException:
        if installed:
            contract_path.unlink()
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return contract_path


def validate_ten_topic_release(*, repo_root: str | Path, contract_document: Mapping[str, Any],
                               source_dir: str | Path, snapshot_dir: str | Path | None = None) -> dict[str, Any]:
    """Rebuild expected publication bytes and compare complete physical inventories."""
    import re

    from .concurrent_robustness_revised import inventory

    c = dict(contract_document)
    if (set(c) != _CONTRACT_FIELDS or c['schema_version'] != _schema_for_sources(c.get('sources', {})) or c['release_purpose'] != PURPOSE
            or c['canonical_endpoint'] != ENDPOINT or c['provider_calls'] != 0
            or c['production_deploy_eligible'] is not True):
        raise ValueError('Invalid ten-topic publication contract')
    root = Path(repo_root).resolve()
    source = Path(source_dir).absolute()
    if (source != source.resolve() or not source.is_relative_to(root) or str(source) != c['source_directory']
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,159}', c['release_id'])
            or not re.fullmatch(r'[0-9a-f]{40}', c['implementation_commit'])):
        raise ValueError('Publication contract source/identity drift')
    _, _, hashes, identity = _materialize_ten_topic(root, c['sources'], c['workbook'], c['release_id'], c['implementation_commit'])
    if hashes != c['artifact_sha256'] or identity != c['release_identity_sha256']:
        raise ValueError('Publication contract reconstruction drift')
    for folder in [source, *([Path(snapshot_dir)] if snapshot_dir else [])]:
        if {k: v['sha256'] for k, v in inventory(folder).items()} != hashes:
            raise ValueError('Publication physical inventory drift')
    return {**c, 'formal_research_evidence': True, 'realized_source_identity': identity,
            'report_sha256': hashes['report.html'], 'manifest_sha256': hashes['artifact_manifest.json'],
            'sampling_method': 'accepted_final_ten_topic_studies_and_protected_historical',
            'sampling_status': 'all_four_studies_accepted',
            'decision_execution_mode': 'persisted_formal_evidence_zero_provider_publication'}


def require_ten_topic_deployment_profile(result: Mapping[str, Any]) -> dict[str, Any]:
    """Project validated v17 facts only; deployment does not own study knowledge."""
    if (result.get('schema_version') not in (SCHEMA, _REVISION_SCHEMA) or result.get('formal_research_evidence') is not True
            or result.get('production_deploy_eligible') is not True or result.get('provider_calls') != 0):
        raise ValueError('v17 requires validated four-study Formal publication')
    return {'realized_source_identity': result['realized_source_identity'], 'release_readiness': {
        'schema_version': 'ten-topic-v18-release-readiness-v1' if result['schema_version'] == _REVISION_SCHEMA else 'ten-topic-v17-release-readiness-v1',
        'release_contract_schema': result['schema_version'],
        'release_id': result['release_id'], 'realized_source_identity': result['realized_source_identity'],
        'canonical_endpoint': ENDPOINT, 'provider_calls': 0, 'operational_authorization_required': True,
        'deployment_authorized': False, 'public_acceptance_recorded': False}}
