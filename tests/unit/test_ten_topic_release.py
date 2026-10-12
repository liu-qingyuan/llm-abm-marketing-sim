from pathlib import Path

import pytest

from llm_abm_sim.ten_topic_release import accept_ten_topic_sources


def test_arbitrary_mock_report_is_not_admitted(tmp_path: Path):
    candidate = tmp_path / 'mock.json'
    candidate.write_text('{"status":"pass","classification":"mock"}')
    with pytest.raises(ValueError,match='binding'):
        accept_ten_topic_sources(repo_root=tmp_path,source_bindings={'whole_sample_manifest':{'path':str(candidate),'sha256':'0'*64}})


def test_reviewed_twenty_condition_source_still_waits_for_reviewed_cash_capsule(tmp_path: Path, monkeypatch):
    from llm_abm_sim import ten_topic_release as release

    monkeypatch.setattr(release, '_REVISION_SHA256', {**release._REVISION_SHA256,
                                                   'four_model_bank_manifest': None})

    bindings = {name: {'path': str(tmp_path / f'{name}.json'), 'sha256': value}
                for name, value in release.SOURCE_SHA256.items()}
    bindings['four_model_acceptance']['sha256'] = '5927d54ce8c8b9a56be3b1f596f469331f1a6f41f28e12f705bc5168eeb1f4e8'
    bindings['four_model_inventory']['sha256'] = '89b748c6f7e5a17154ad85491f2df54a364d471074116478a5005f5a139fcd66'
    with pytest.raises(ValueError, match='reviewed cash.*capsule'):
        release.accept_ten_topic_sources(repo_root=tmp_path, source_bindings=bindings)


def test_revision_checks_preserved_physical_location_before_hash_binding(tmp_path: Path, monkeypatch):
    from llm_abm_sim import ten_topic_release as release

    expected = {**release.SOURCE_SHA256, **release._REVISION_SHA256,
                'four_model_bank_manifest': 'a' * 64}
    monkeypatch.setattr(release, '_REVISION_SHA256', {**release._REVISION_SHA256,
                                                   'four_model_bank_manifest': 'a' * 64})
    bindings = {name: {'path': '/cleaned-checkout/' + name + '.json', 'sha256': sha}
                for name, sha in expected.items()}
    monkeypatch.setattr(release, '_physical_source', lambda path: tmp_path / path.name)
    checked = []
    def bound(path, sha):
        checked.append((path, sha))
        raise ValueError('Preserved source hash binding reached')
    monkeypatch.setattr(release, '_bound', bound)
    with pytest.raises(ValueError, match='Preserved source hash binding reached'):
        release.accept_ten_topic_sources(repo_root=tmp_path, source_bindings=bindings)
    assert checked == [(Path(bindings['whole_sample_manifest']['path']), expected['whole_sample_manifest'])]


def test_revised_projection_uses_twenty_paths_and_exposes_only_aggregates(tmp_path: Path, monkeypatch):
    import hashlib
    import json

    from llm_abm_sim import ten_topic_release as release

    def saved(name, value):
        path = tmp_path / name
        path.write_text(json.dumps(value))
        return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

    users = [f'private-user-{i:04}' for i in range(1000)]
    seeds = users[:20]
    membership = saved('groups.json', {'sample_user_ids': users, 'seed_user_ids': seeds,
        'segments': [{'user_id': user, 'segment': f'S{i % 3 + 1}'} for i, user in enumerate(users)]})
    conditions = []
    for model in ('gpt-6-sol', 'gpt-6.1-sol', 'qwen3.8-max', 'deepseek-flash', 'openai-codex/gpt-5.6-sol'):
        for template in ('P0', 'P1', 'P2', 'P3'):
            rows = [{'user_id': users[step * 20 + i], 'message_id': f'message_{message}',
                     'time_step': step, 'realized_action': 'ignore',
                     'judgment': {'engage': False, 'probability': 0.0, 'confidence': .5}}
                    for step in range(30) for message in range(1, 4) for i in range(20)]
            ref = saved(f'cell-{len(conditions)}.json', {'sample_user_ids': users, 'seed_user_ids': seeds,
                        'behavior_seed': 20260823, 'barriers': [{}] * 30, 'terminals': rows})
            conditions.append({'cell_id': f'{template}::{model}', 'realized_positive': 0, **ref})
    acceptance = saved('acceptance.json', {'conditions': conditions})
    capsule = saved('capsule.json', {'sample_segments': membership})
    monkeypatch.setattr(release, '_collect_historical_public_data', lambda old: {'models': {'conditions': []}})
    accepted = {'schema_version': 'ten-topic-reviewed-publication-sources-v2',
        'historical_publication_sources': {}, 'paths': {'four_model_acceptance': acceptance['path'],
            'four_model_bank_manifest': capsule['path']},
        'source_sha256': {'four_model_acceptance': acceptance['sha256'],
                         'four_model_bank_manifest': capsule['sha256']}}
    result = release.collect_ten_topic_public_data(accepted)['models']
    assert len(result['conditions']) == 20
    assert sum(row['exposures'] for row in result['conditions']) == 36000
    assert len(result['messages']) == 60 and len(result['segments']) == 180
    assert len(result['curves']) == 1800 and len(result['segment_curves']) == 5400
    assert all(row['realized_rate'] == 0 for row in result['conditions'])
    assert {row['source_mode'] for row in result['conditions']} == {'new_formal', 'accepted_legacy_control'}
    assert all(row['delta'] == 0 and row['lower_95'] == 0 and row['upper_95'] == 0 for row in result['paired_seed'])
    assert {row['bootstrap_seed'] for row in result['paired_seed']} == {20260809}
    assert 'private-user-' not in json.dumps(result)


def test_v17_contract_never_accepts_old_schema_or_extra_fields(tmp_path: Path):
    from llm_abm_sim.ten_topic_release import validate_ten_topic_release

    with pytest.raises(ValueError, match='contract'):
        validate_ten_topic_release(repo_root=tmp_path, contract_document={'schema_version': 'abm-report-release-contract-v16'}, source_dir=tmp_path)


def test_v18_readiness_keeps_original_endpoint_and_requires_validated_facts():
    from llm_abm_sim.ten_topic_release import require_ten_topic_deployment_profile

    result = {'schema_version': 'abm-report-release-contract-v18', 'formal_research_evidence': True,
              'production_deploy_eligible': True, 'provider_calls': 0,
              'realized_source_identity': 'pinned-test-identity', 'release_id': 'offline-v18-test'}
    projected = require_ten_topic_deployment_profile(result)['release_readiness']
    assert projected['schema_version'] == 'ten-topic-v18-release-readiness-v1'
    assert projected['canonical_endpoint'] == 'https://abm.q1ngyuan.top/'
    assert projected['deployment_authorized'] is False
    with pytest.raises(ValueError):
        require_ten_topic_deployment_profile({**result, 'formal_research_evidence': False})


def test_v18_materialization_preserves_v17_downloads_and_exact_inventory(tmp_path: Path, monkeypatch):
    import hashlib
    import json

    from test_ten_topic_report import BASE, _five_model_data

    from llm_abm_sim import ten_topic_release as release

    inputs, old, shell = tmp_path / 'inputs', tmp_path / 'old-v17', tmp_path / 'old-v16'
    for path in (inputs, old, shell):
        path.mkdir()
    (shell / 'report.html').write_bytes(BASE)
    (old / 'ten-topic').mkdir()
    contents = {'report.html': b'protected old v17', 'artifact_manifest.json':
                json.dumps({'approved_downloads': ['ten-topic/old.csv', 'historical.txt']}).encode(),
                'ten-topic/old.csv': b'protected old table', 'historical.txt': b'old v16 file',
                'ten-topic/source-map.json': b'protected old source map',
                'ten-topic/public-statistics.json': b'protected old statistics'}
    for name, value in contents.items():
        (old / name).write_bytes(value)
    def digest(value):
        return hashlib.sha256(value).hexdigest()
    contract = inputs / 'old-contract.json'
    contract.write_text(json.dumps({'schema_version': release.SCHEMA, 'source_directory': str(old),
        'release_identity_sha256': 'historical-identity', 'artifact_sha256': {name: digest(v) for name, v in contents.items()}}))
    capsule = inputs / 'capsule.json'
    capsule.write_text(json.dumps({'protected_v17_contract': {'path': str(contract), 'sha256': digest(contract.read_bytes())}}))
    placeholder = inputs / 'source.json'
    placeholder.write_text('{}')
    sources = {name: {'path': str(placeholder), 'sha256': value} for name, value in release.SOURCE_SHA256.items()}
    sources['four_model_acceptance']['sha256'] = release._REVISION_SHA256['four_model_acceptance']
    sources['four_model_bank_manifest'] = {'path': str(capsule), 'sha256': digest(capsule.read_bytes())}
    accepted = {'publication_contract_schema': release._REVISION_SCHEMA,
        'protected_v17_directory': str(old), 'protected_v16_directory': str(shell), 'source_sha256': {},
        'actual_experiment_cash_CNY': 0, **{key: {} for key in ('whole_sample', 'parameters', 'index', 'four_models')}}
    monkeypatch.setattr(release, 'accept_ten_topic_sources', lambda **kw: accepted)
    monkeypatch.setattr(release, 'collect_ten_topic_public_data', lambda a: _five_model_data())
    monkeypatch.setattr(release, '_validate_workbook', lambda *args: None)
    workbook = inputs / 'offline-workbook.xlsx'
    workbook.write_bytes(b'offline serialization fixture, never production')
    target = tmp_path / 'v18-test'
    path = release.promote_ten_topic_release(repo_root=tmp_path, source_bindings=sources,
        workbook={'path': str(workbook), 'sha256': digest(workbook.read_bytes())},
        destination_dir=target, release_id='offline-v18-test', implementation_commit='1' * 40)
    doc = json.loads(path.read_text())
    assert doc['schema_version'] == release._REVISION_SCHEMA
    assert (target / 'ten-topic-v17/old.csv').read_bytes() == contents['ten-topic/old.csv']
    for name in ('source-map.json', 'public-statistics.json'):
        assert (target / 'ten-topic-v17' / name).read_bytes() == contents['ten-topic/' + name]
        assert (target / 'ten-topic' / name).read_bytes() != contents['ten-topic/' + name]
    assert (target / 'ten-topic-v17-report.html').read_bytes() == contents['report.html']
    assert (target / 'historical.txt').read_bytes() == contents['historical.txt']
    assert b'abm-report-release-contract-v18' in (target / 'report.html').read_bytes()
    validated = release.validate_ten_topic_release(repo_root=tmp_path, contract_document=doc, source_dir=target)
    assert validated['formal_research_evidence'] is True
    assert all((old / name).read_bytes() == value for name, value in contents.items())
    assert all(digest((target / name).read_bytes()) == value for name, value in doc['artifact_sha256'].items())


def test_shell_admits_versioned_ten_topic_only_after_validated_facts():
    shell = (Path(__file__).resolve().parents[2] / 'scripts/deploy_abm_report.sh').read_text()
    gate = '^abm-report-release-contract-v([2-9]|10|11|12|13|14|15|16|17|18)$'
    assert shell.count(gate) == 2  # Local facts and remote candidate schema checks.
    assert shell.index('--require-formal-production') < shell.index(gate)


@pytest.mark.parametrize('version', ('v17', 'v18'))
def test_production_validator_delegates_ten_topic_to_its_owner(tmp_path: Path, monkeypatch, version):
    from llm_abm_sim import ten_topic_release
    from llm_abm_sim.concurrent_robustness_release import validate_concurrent_robustness_production_release

    observed = []
    def validate(**arguments):
        observed.append(arguments)
        return {'schema_version': f'abm-report-release-contract-{version}', 'provider_calls': 0}
    monkeypatch.setattr(ten_topic_release, 'validate_ten_topic_release', validate)
    contract = {'schema_version': f'abm-report-release-contract-{version}'}
    result = validate_concurrent_robustness_production_release(repo_root=tmp_path,
        contract_document=contract, source_dir=tmp_path / 'source', snapshot_dir=tmp_path / 'snapshot')
    assert result['schema_version'] == contract['schema_version']
    assert observed == [{'repo_root': tmp_path, 'contract_document': contract,
                         'source_dir': tmp_path / 'source', 'snapshot_dir': tmp_path / 'snapshot'}]
