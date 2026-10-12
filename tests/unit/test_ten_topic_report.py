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


def _five_model_data():
    identities = ['gpt-6-sol', 'gpt-6.1-sol', 'qwen3.8-max', 'deepseek-flash', 'gpt-5.6-sol']
    return {
        'schema_version': 'ten-topic-public-statistics-v1', 'network': {'p95': 5},
        'whole': {'summary': {'exposures': 109200, 'like': 63420, 'comment': 5,
                             'share': 189, 'ignore': 45586},
                  'rows': [{'exposures': 109200}],
                  'curves': [{'message': 'message_1', 'batch': 30, 'realized_rate': .5}]},
        'parameters': {'estimates': [{'metric': 'engagement_rate', 'message': 'all', 'mean': .5}],
                       'curves': [{'message': 'all', 'configuration': 'baseline', 'batch': 30,
                                   'new_rate_mean': .5}], 'paired': [{'fixture': 'offline'}]},
        'index': {'local_p99_rebuilt_overlap': 23,
                  'estimates': [{'metric': 'engagement_rate', 'message': 'all', 'mean': .5}],
                  'curves': [{'message': 'all', 'configuration': 'baseline', 'batch': 30,
                              'new_rate_mean': .5}], 'paired': [{'fixture': 'offline'}],
                  'composition': [{'fixture': 'offline'}]},
        'models': {'conditions': [
            {'model_id': model, 'model': model, 'template': f'P{template}',
             'exposures': 1800, 'like': 0, 'comment': 0, 'share': 0, 'ignore': 1800,
             'realized_positive': 0, 'realized_rate': 0.0}
            for model in identities for template in range(4)],
            'messages': [{'fixture': 'offline'}], 'segments': [{'fixture': 'offline'}],
            'curves': [{'model': 'gpt-6-sol', 'template': 'P0', 'message': 'message_1',
                        'batch': 29, 'realized_rate': 0.0}],
            'segment_curves': [{'fixture': 'offline'}],
            'comparison': [{'fixture': 'offline'}], 'paired_seed': [{'fixture': 'offline'}]},
        'download_links': [],
    }


def test_five_model_report_discloses_new_and_reused_scope_without_rate_selection():
    from llm_abm_sim.ten_topic_report import render_ten_topic_research, ten_topic_workbook_tables

    data = _five_model_data()
    rendered = render_ten_topic_research(BASE, data, release_id='revision-offline-test').decode()
    current = rendered.split('<details id="single-topic-history">')[0]
    assert 'content="abm-report-release-contract-v18"' in current
    assert '五模型与P0–P3' in current and '36,000' in current
    assert '21,600' in current and '14,400' in current
    assert '跨时点' in current and '观察后选型' in current
    assert '不可变权重' in current and 'unknown' in current
    assert '准确率' in current and '推理等级' in current
    assert '原500次用户block bootstrap' not in current
    methods = ten_topic_workbook_tables(data)['Methods']
    assert any(row['Item'] == 'Five models' and '20 conditions' in row['Value'] for row in methods)
    assert not any(row['Item'] == 'Gemini' for row in methods)


def test_five_model_download_methods_are_same_scope_as_page_and_workbook():
    import csv
    import io
    import json

    from llm_abm_sim.ten_topic_report import ten_topic_public_downloads

    data = _five_model_data()
    downloads = ten_topic_public_downloads(data)
    rows = list(csv.DictReader(io.StringIO(downloads['ten-topic/models/conditions.csv'].decode('utf-8-sig'))))
    assert len(rows) == 20 and sum(int(row['exposures']) for row in rows) == 36000
    methods = json.loads(downloads['ten-topic/methods.json'])
    assert methods['model_matrix'] == {'models': 5, 'conditions': 20, 'exposures': 36000,
                                      'new_conditions': 12, 'new_exposures': 21600,
                                      'legacy_conditions': 8, 'legacy_exposures': 14400}
    assert methods['unreported_reasoning_tokens'] == 'unknown'
    assert methods['provider_reasoning_levels_equivalent'] is False
    assert methods['selection_after_observation'] is True
    assert methods['interaction_rate_is_accuracy'] is False
    assert 'gemini_observed_model' not in methods and 'model_version_change' not in methods


def test_every_report_entry_rejects_incomplete_duplicate_or_crossed_revision():
    from copy import deepcopy

    import pytest

    from llm_abm_sim import ten_topic_report as report

    valid = _five_model_data()
    corruptions = [
        lambda rows: rows.pop(),
        lambda rows: rows.__setitem__(0, deepcopy(rows[1])),
        lambda rows: rows[0].update(model_id='qwen3.8-max-0902'),
        lambda rows: rows[0].update(exposures=1799),
        lambda rows: rows[0].update(ignore=1801),
        lambda rows: rows[0].update(like=-1, ignore=1801),
        lambda rows: rows[0].update(realized_positive=False),
        lambda rows: rows[0].update(realized_rate=.6),
    ]
    for corrupt in corruptions:
        data = deepcopy(valid)
        corrupt(data['models']['conditions'])
        for entry in (lambda d: report.render_ten_topic_research(BASE, d, release_id='offline-test'),
                      report.ten_topic_public_downloads, report.ten_topic_workbook_tables):
            with pytest.raises(ValueError, match='five-model public'):
                entry(data)


def test_v17_report_download_and_workbook_bytes_are_unchanged():
    import hashlib
    import json

    from llm_abm_sim import ten_topic_report as report

    # Golden outputs from the v17 implementation at fixed point 1787488.
    # No live Provider, private run fixture or Git-history lookup is required.
    def digest(value):
        return hashlib.sha256(value).hexdigest()

    def encoded(value):
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()

    data = _five_model_data()
    data['models']['conditions'] = [
        dict(row, model_id=f'historical-{index // 4}', model=f'historical-{index // 4}')
        for index, row in enumerate(data['models']['conditions'][:16])]
    assert digest(report.render_ten_topic_research(BASE, data, release_id='v17-test')) == '6e66da8fe7b186d15b94d81edc5bfa33bff98826d6e6ee1e488e65951f24acc7'
    downloads = {name: digest(value) for name, value in report.ten_topic_public_downloads(data).items()}
    assert digest(encoded(downloads)) == '8178ed71fd4f595533b65aff7267a4511ccc8f9b6cd86486a5809714e0b72218'
    assert digest(encoded(report.ten_topic_workbook_tables(data))) == '42474af22c4c9643faa3734cd49c251ca8e95e04eb3bd50c1da269063547f14e'
