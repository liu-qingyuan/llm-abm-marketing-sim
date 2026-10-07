from pathlib import Path

import pytest

from llm_abm_sim.ten_topic_release import accept_ten_topic_sources


def test_arbitrary_mock_report_is_not_admitted(tmp_path: Path):
    candidate = tmp_path / 'mock.json'
    candidate.write_text('{"status":"pass","classification":"mock"}')
    with pytest.raises(ValueError,match='binding'):
        accept_ten_topic_sources(repo_root=tmp_path,source_bindings={'whole_sample_manifest':{'path':str(candidate),'sha256':'0'*64}})
