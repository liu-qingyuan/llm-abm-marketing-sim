import re

import pytest

from llm_abm_sim.concurrent_robustness_report import _REPORT_PRESENTATION

BASE = b'''<html><head><meta name="abm-release-id" content="old-v15"><meta name="abm-release-contract" content="abm-report-release-contract-v15"></head><body><main id="full-pool-main">old results</main><section id="revised-robustness">four models</section><section id="historical-sensitivity-1000"><a href="old.csv" download>old download</a></section><script>/* old controls */</script></body></html>'''


def test_addition_preserves_all_previous_body_and_scripts():
    output = _REPORT_PRESENTATION.render_sensitivity_research(BASE, release_id="research-v16")
    old_body = BASE.split(b"<body>")[1].split(b"</body>")[0]
    assert old_body in output
    assert b'content="research-v16"' in output
    assert b'content="abm-report-release-contract-v16"' in output
    assert b'content="old-v15"' not in output
    for token in ("108/1000", "100行为seed", "不表示LLM重复判断100次", "原五模型计划并非全部完成", "不宣称普遍稳健或纯指标因果效应"):
        assert token in output.decode()
    assert output.count(b"<iframe ") == 2
    assert b'src="parameter/report.html"' in output
    assert b'src="index-sensitivity/report.html"' in output
    assert output == _REPORT_PRESENTATION.render_sensitivity_research(BASE, release_id="research-v16")


def test_navigation_targets_exist():
    output = _REPORT_PRESENTATION.render_sensitivity_research(BASE, release_id="research-v16").decode()
    ids = set(re.findall(r'\bid="([^"]+)"', output))
    targets = set(re.findall(r'href="#([^"]+)"', output))
    assert targets <= ids


@pytest.mark.parametrize("source", [BASE.replace(b"<body>", b"<body class='other'>"), BASE.replace(b"v15", b"v14"), BASE + BASE])
def test_rejects_crossed_base(source):
    with pytest.raises(ValueError):
        _REPORT_PRESENTATION.render_sensitivity_research(source, release_id="research-v16")


def test_rejects_repeated_append_and_invalid_identity():
    output = _REPORT_PRESENTATION.render_sensitivity_research(BASE, release_id="research-v16")
    with pytest.raises(ValueError):
        _REPORT_PRESENTATION.render_sensitivity_research(output, release_id="research-v16")
    with pytest.raises(ValueError):
        _REPORT_PRESENTATION.render_sensitivity_research(BASE, release_id='bad" onclick="x')


def test_index_curve_download_reuses_exact_plot():
    from llm_abm_sim.sensitivity_report import index_curve_svg
    svg = b'<svg viewBox="0 0 10 10"><polyline points="0,0 10,10"/></svg>'
    exported = index_curve_svg(b'<html>'+svg+b'</html>')
    assert exported.replace(b' xmlns="http://www.w3.org/2000/svg"', b'') == svg
    for source in [b'<html/>', svg+svg]:
        with pytest.raises(ValueError, match='exactly one'):
            index_curve_svg(source)
