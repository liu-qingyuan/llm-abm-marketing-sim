"""Add research navigation without duplicating the standalone research renderers."""
from __future__ import annotations

import html
import re


def render_sensitivity_research(base_html: bytes, *, release_id: str) -> bytes:
    """Append two independent reports to v15; retain its content and download URLs.

    The Release Module installs the byte-identical standalone reports and their
    relative downloads under parameter/ and index-sensitivity/. Native details
    keep this addition independent of the existing language/filter scripts.
    """
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}", release_id):
        raise ValueError("Invalid sensitivity release id")
    base = base_html.decode("utf-8")
    if (base.count("<body>") != 1 or base.count("</body>") != 1
            or 'id="research-navigation"' in base
            or base.count('<meta name="abm-release-contract" content="abm-report-release-contract-v15">') != 1):
        raise ValueError("Expected the protected v15 report, without sensitivity sections")
    navigation = '''
<nav id="research-navigation" aria-label="研究导航 / Research navigation" style="padding:1rem;max-width:1200px;margin:auto">
<h2>研究导航 / Research navigation</h2>
<p>各研究分别保留样本、判断库和统计单位；不合并分母。</p>
<ul>
<li><a href="#full-pool-main">Whole sample</a>：36,400 用户、3 条营销消息、109,200 次曝光；GPT-5.6 Sol / P0，Judgment → Realization，单个固定行为 seed。</li>
<li><a href="#revised-robustness">Prompt–Model 修订研究</a>：1,000 用户样本；4 模型 × P0–P3，16 cells、28,800 次曝光。原五模型计划并非全部完成。</li>
<li><a href="#parameter-study">Parameter</a>：21 组参数 × 100 行为 seed，2,100 条路径。</li>
<li><a href="#index-sensitivity-study">Activity / Local Influence</a>：7 组 × 100 行为 seed，700 条路径。</li>
<li><a href="#historical-sensitivity-1000">历史研究</a>：早期 direct-action 与新两阶段研究分开；历史指标排序分析不是传播仿真实验。</li>
</ul>
<p>P0–P3 = AI 判断模板；M1–M3 = 营销消息；S1–S3 = 用户群。每次实现互动次数为整数；两项敏感性研究中的小数为100次行为实现的均值，不表示LLM重复判断100次，不与单次结果混作同一统计口径。</p>
<p lang="en">Separate studies, samples and denominators. Sensitivity estimates average 100 behavior seeds conditional on fixed judgments; they are not 100 repeated LLM judgments. The historical ranking audit is not a diffusion experiment.</p>
</nav>
'''
    sections = '''
<section id="parameter-study" aria-labelledby="parameter-study-title" style="padding:1rem;max-width:1200px;margin:auto">
<h2 id="parameter-study-title">Parameter · 推荐参数敏感性研究</h2>
<p>问题：推荐权重及邻居饱和阈值是否改变终点或时间路径？固定 GPT-5.6 Sol / P0、判断库、1,000用户样本、消息和网络；改变7组推荐权重与阈值1/3/6。每配置100行为seed，每路径1,800曝光。</p>
<p>所测矩阵中同seed终点相同，但曝光顺序和时间过程变化；不推断参数普遍不敏感。结果、图表和下载复用已完成研究的原产物。</p>
<p><a href="parameter/report.html">打开完整报告 / Open full report</a> · <a download href="parameter/evidence.json">Evidence</a> · <a download href="parameter/path-summary.csv">路径结果 CSV</a> · <a download href="parameter/trajectories.csv">曲线 CSV</a></p>
<details open><summary>阅读结果与图表 / Results and charts</summary>
<iframe title="Parameter study report" src="parameter/report.html" loading="lazy" style="width:100%;height:80vh;border:1px solid #cbd5e1"></iframe>
</details></section>
<section id="index-sensitivity-study" aria-labelledby="index-sensitivity-title" style="padding:1rem;max-width:1200px;margin:auto">
<h2 id="index-sensitivity-title">Activity / Local Influence · 指标敏感性研究</h2>
<p>问题：指标权重、归一化及其抽样联动如何改变传播？固定 GPT-5.6 Sol / P0、推荐权重0.50/0.30/0.20、邻居饱和阈值3。7组，每组1,000用户、100行为seed，每路径1,800曝光。</p>
<p>固定样本但重选初始种子，与按原规则重建样本，是不同估计对象。Local p99重建后仅108/1000用户与基线重合，差异包含样本构成影响。新旧判断时点与模型回答波动未充分分离，不宣称普遍稳健或纯指标因果效应。</p>
<p>原证据保留1条unknown及其不曝光证明：实际曝光判断完整，不等于完整eligible判断库。原独立产物的未部署标记记录生成时状态，不由本次发布改写。</p>
<p><a href="index-sensitivity/report.html">打开完整报告 / Open full report</a> · <a download href="index-sensitivity/evidence.json">Evidence</a> · <a download href="index-sensitivity/paired-estimates.csv">配对结果 CSV</a> · <a download href="index-sensitivity/curve-estimates.csv">曲线 CSV</a> · <a download href="index-sensitivity/curves.svg">图表 SVG</a></p>
<details open><summary>阅读结果与图表 / Results and charts</summary>
<iframe title="Activity and Local Influence study report" src="index-sensitivity/report.html" loading="lazy" style="width:100%;height:80vh;border:1px solid #cbd5e1"></iframe>
</details></section>
'''
    result = base.replace("<body>", "<body>" + navigation).replace("</body>", sections + "</body>")
    result, count = re.subn(r'<meta name="abm-release-id" content="[^"]+">',
                            f'<meta name="abm-release-id" content="{html.escape(release_id)}">', result)
    if count != 1:
        raise ValueError("Report release metadata must be unique")
    return result.replace('<meta name="abm-release-contract" content="abm-report-release-contract-v15">',
                          '<meta name="abm-release-contract" content="abm-report-release-contract-v16">').encode()


def index_curve_svg(report_html: bytes) -> bytes:
    """Export the original inline curve verbatim, adding only the XML namespace."""
    matches = re.findall(rb"<svg\b[^>]*>.*?</svg>", report_html, flags=re.DOTALL)
    if len(matches) != 1:
        raise ValueError("Expected exactly one source index curve")
    return matches[0].replace(b"<svg ", b'<svg xmlns="http://www.w3.org/2000/svg" ', 1)
