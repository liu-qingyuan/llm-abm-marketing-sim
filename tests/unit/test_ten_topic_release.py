from pathlib import Path

import pytest

from llm_abm_sim.ten_topic_release import accept_ten_topic_sources


def test_arbitrary_mock_report_is_not_admitted(tmp_path: Path):
    candidate = tmp_path / 'mock.json'
    candidate.write_text('{"status":"pass","classification":"mock"}')
    with pytest.raises(ValueError,match='binding'):
        accept_ten_topic_sources(repo_root=tmp_path,source_bindings={'whole_sample_manifest':{'path':str(candidate),'sha256':'0'*64}})


def test_v17_contract_never_accepts_old_schema_or_extra_fields(tmp_path: Path):
    from llm_abm_sim.ten_topic_release import validate_ten_topic_release

    with pytest.raises(ValueError, match='contract'):
        validate_ten_topic_release(repo_root=tmp_path, contract_document={'schema_version': 'abm-report-release-contract-v16'}, source_dir=tmp_path)
