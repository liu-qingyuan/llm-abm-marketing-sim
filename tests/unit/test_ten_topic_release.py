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


def test_shell_admits_v17_only_after_validated_facts():
    shell = (Path(__file__).resolve().parents[2] / 'scripts/deploy_abm_report.sh').read_text()
    gate = '^abm-report-release-contract-v([2-9]|10|11|12|13|14|15|16|17)$'
    assert shell.count(gate) == 2  # Local facts and remote candidate schema checks.
    assert shell.index('--require-formal-production') < shell.index(gate)
