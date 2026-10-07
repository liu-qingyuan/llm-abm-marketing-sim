from llm_abm_sim.concurrent_robustness_report import _REPORT_PRESENTATION

BASE = b'<html><head><meta name="abm-release-id" content="old"><meta name="abm-release-contract" content="abm-report-release-contract-v16"></head><body><nav id="research-navigation">old navigation</nav><main id="full-pool-main"><p>old single-topic result</p></main><section id="revised-robustness">old models</section><section id="parameter-study">old parameters</section><section id="index-sensitivity-study">old index</section><section id="unrelated">unrelated preserved</section><script>/* unrelated controls preserved */</script></body></html>'


def test_new_research_is_default_old_research_explicit_and_unrelated_preserved():
    data = {'schema_version': 'ten-topic-public-statistics-v1', 'network': {'p95': 5},
            'whole': {'summary': {'exposures': 109200, 'like': 63420, 'comment': 5, 'share': 189, 'ignore': 45586}, 'rows': [], 'curves': []},
            'parameters': {'estimates': [], 'curves': []}, 'index': {'local_p99_rebuilt_overlap': 23, 'estimates': [], 'curves': []},
            'models': {'conditions': [], 'curves': []}, 'download_links': []}
    result = _REPORT_PRESENTATION.render_ten_topic_research(BASE, data, release_id='ten-topic-v17')
    assert b'content="abm-report-release-contract-v17"' in result
    assert b'content="ten-topic-v17"' in result
    assert b'id="full-pool-main"' in result and b'id="legacy-full-pool-main"' in result
    assert '十个实际采集话题'.encode() in result
    assert b'old single-topic result' in result and b'unrelated preserved' in result
    assert b'/* unrelated controls preserved */' in result
    assert result.index(b'id="full-pool-main"') < result.index(b'id="single-topic-history"')
    import json
    import re

    data['network']['fixture_text'] = '<script>&</script>'
    result = _REPORT_PRESENTATION.render_ten_topic_research(BASE, data, release_id='ten-topic-v17')
    payload = re.search(rb'<script type="application/json" id="ten-topic-public-data">(.*?)</script>', result, re.S)
    assert payload is not None
    assert b'<script>' not in payload[1]
    assert json.loads(payload[1])['network']['fixture_text'] == '<script>&</script>'
