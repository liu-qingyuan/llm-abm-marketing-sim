from pathlib import Path

import pytest

from llm_abm_sim.sensitivity_release import (
    SCHEMA,
    _bound,
    promote_sensitivity_release,
    require_sensitivity_deployment_profile,
    validate_sensitivity_release,
)


def test_arbitrary_report_cannot_become_formal(tmp_path: Path):
    (tmp_path / 'inputs').mkdir()
    source = tmp_path / 'inputs' / 'source.json'
    source.write_text('{}')
    with pytest.raises(ValueError, match='hash'):
        promote_sensitivity_release(repo_root=tmp_path, protected_v15_contract=source,
                                    parameter_manifest=source, index_audit=source,
                                    destination_dir=tmp_path/'release', release_id='test',
                                    implementation_commit='a'*40)
    assert not (tmp_path/'release').exists()


def test_bound_source_rejects_symlink(tmp_path: Path):
    import hashlib
    source = tmp_path/'source'
    source.write_bytes(b'content')
    link = tmp_path/'link'
    link.symlink_to(source)
    with pytest.raises(ValueError, match='regular-file'):
        _bound(link, hashlib.sha256(b'content').hexdigest())


def test_contract_extra_field_rejected(tmp_path: Path):
    with pytest.raises(ValueError, match='contract'):
        validate_sensitivity_release(repo_root=tmp_path, contract_document={'schema_version': SCHEMA, 'extra': True}, source_dir=tmp_path)


def test_profile_requires_validated_evidence():
    with pytest.raises(ValueError, match='validated'):
        require_sensitivity_deployment_profile({'schema_version': SCHEMA, 'production_deploy_eligible': True})
    profile = require_sensitivity_deployment_profile(dict(schema_version=SCHEMA, formal_research_evidence=True,
        production_deploy_eligible=True, provider_calls=0, realized_source_identity='a'*64, release_id='test'))
    assert profile['release_readiness']['deployment_authorized'] is False
    assert profile['release_readiness']['release_contract_schema'] == SCHEMA
