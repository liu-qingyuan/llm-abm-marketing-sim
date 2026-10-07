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
# Reviewed source identities, not caller-supplied declarations of Formal status.
SOURCE_SHA256 = {'whole_sample_manifest': '26b1bf7b796940952910ccfd78b5b259ff4f22ce48bf131f32be6a306300839d', 'gpt_acceptance': '5df02d59afb8d287257554103af156724f890f5c2b5229ff583df3e10cf4a576', 'gpt_inventory': '906637cc3997732c842996bf20b7d17911c57f8d2f4d2e6cffb3968e945935cd', 'gpt_path_manifest': 'd01006705b1ef826193b86d94c41741669f96b4626b6fd605ee7d505a0a123fa', 'gpt_evidence': '302d20eec48ab8c8d1dd61199fc048df9f8f61b2b002c54f0501f105485651e4', 'four_model_acceptance': '0b17d7df5b0fd55d18ff648a3c7a917d3c86dd43e48ed37e63d5d984dd257831', 'four_model_inventory': '268471c4a479a60eb95298e06896e88089fa788841a4351d7163111c86d6d5c1', 'four_model_bank_manifest': 'cbad2e56f7b615b47e40428bb83d52da43cd44a19f0b712e998e7595ac1aea98', 'protected_v16_contract': '6ef1f9baf777d29223fa1e9fab8d3cd1c86b368162f4f9f7491d86e83db63ef0'}

def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _bound(path: Path, expected: str) -> dict[str, Any]:
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
    documents = {}
    paths = {}
    for name, expected in SOURCE_SHA256.items():
        reference = source_bindings[name]
        if reference.get('sha256') != expected or not isinstance(reference.get('path'), str):
            raise ValueError(f'Reviewed source binding mismatch: {name}')
        path = Path(str(reference['path'])).absolute()
        if name != 'protected_v16_contract' and not path.is_relative_to(root):
            raise ValueError('New source binding escaped the existing worktree')
        documents[name] = _bound(path, expected)
        paths[name] = path
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
            'protected_v16_directory': protected['source_directory'],
            'source_eligibility_flags_preserved': True,
            'new_release_and_public_validation_required': True}
