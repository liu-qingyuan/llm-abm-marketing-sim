"""Report-owned rendering of revised recovery research into the protected page."""
from __future__ import annotations

import csv
import html
import io
import re
from typing import Any

from .concurrent_robustness_revised import MESSAGES, MODELS, PROMPTS, ClosedRevisedEvidence, json_bytes
from .full_pool_presentation import _REVISED_RELEASE_RESPONSIVE_CSS

_NAMES = dict(zip(MODELS, ("DeepSeek V4 Flash", "Gemini 3.1 Pro", "Kimi（双路由 / mixed routes）", "GPT-5.6 Sol"), strict=True))
_COLORS = ("#0e657d", "#bd5200", "#4b7c08", "#853ff2")
_DASHES = ("", "8 5", "2 5", "10 4 2 4")


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _csv(rows: list[dict[str, Any]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows({k: json_bytes(v).decode().strip() if isinstance(v, (dict, list)) else v for k, v in row.items()} for row in rows)
    return output.getvalue().encode("utf-8-sig")


def revised_downloads(evidence: ClosedRevisedEvidence, analysis: dict[str, Any]) -> dict[str, bytes]:
    """Generate all public downloads from the same closed projection, no raw payload."""
    outputs = {"revised-robustness/analysis.json": json_bytes(analysis), "revised-robustness/evidence.json": json_bytes(evidence.document),
        "revised-robustness/messages.json": json_bytes(evidence.messages)}
    for key in ("cells", "message_slices", "segment_message_slices", "curves", "growth", "direct", "realized_contrasts", "planned_contrasts", "prompt_model_interactions", "identity_strata"):
        outputs[f"revised-robustness/{key}.csv"] = _csv(analysis[key])
    return outputs


def _chart(analysis: dict[str, Any], model: str, message: str, metric: str) -> str:
    max_y = 1000 if metric == "growth" else 1
    lines = []
    for i, prompt in enumerate(PROMPTS):
        if metric == "growth":
            values = [r["cumulative_positive_users"] for r in analysis["growth"] if r["model"] == model and r["prompt"] == prompt]
        else:
            key = {"realized": "realized_rate", "judgment": "judgment_rate", "audience": "audience_jaccard_distance"}[metric]
            values = [r[key] for r in analysis["curves"] if r["model"] == model and r["prompt"] == prompt and r["message"] == message]
        points = [(45 + n * 420 / 29, 168 - value * 140 / max_y) for n, value in enumerate(values)]
        poly = " ".join(f"{x:.3f},{y:.3f}" for x, y in points)
        dots = "".join(f'<circle cx="{x:.3f}" cy="{y:.3f}" r="2.4" fill="{_COLORS[i]}"/>' for x, y in points[::3])
        lines.append(f'<g data-prompt="{prompt}"><polyline points="{poly}" fill="none" stroke="{_COLORS[i]}" stroke-width="2" stroke-dasharray="{_DASHES[i]}"/>{dots}</g>')
    grid = ''.join(f'<line x1="45" x2="465" y1="{168-v*140:.2f}" y2="{168-v*140:.2f}" stroke="#dce3eb"/><text x="36" y="{172-v*140:.2f}" text-anchor="end" font-size="10">{v*max_y:g}</text>' for v in (0, .25, .5, .75, 1))
    legend = ''.join(f'<span><i style="border-color:{_COLORS[i]};border-top-style:{"solid" if i == 0 else "dashed"}"></i>{p}</span>' for i, p in enumerate(PROMPTS))
    label = {"realized": "Realized rate / 累计实现互动率", "judgment": "Judgment rate / 累计判断互动率", "audience": "Audience Jaccard distance / 受众距离（同Prompt GPT基准）", "growth": "Campaign distinct positive users / 跨消息去重正向用户"}[metric]
    return f'<article data-r15-plot="{_escape(model)}|{message}|{metric}" class="robustness-model-panel" {"" if message == MESSAGES[0] and metric == "realized" else "hidden"}><h3>{_escape(_NAMES[model])}</h3><p>{label}</p><svg role="img" aria-label="{_escape(_NAMES[model]+" "+label)}" viewBox="0 0 490 205">{grid}{"".join(lines)}<text x="45" y="190" font-size="10">Batch 0</text><text x="422" y="190" font-size="10">Batch 29</text></svg><div class="r15-legend">{legend}</div></article>'


def _table(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> str:
    def display(k: str, v: Any) -> str:
        if v is None:
            return "unknown / 未知"
        if isinstance(v, float):
            return f"{v:.2%}" if any(x in k for x in ("rate", "delta", "lower", "upper")) else f"{v:.4f}"
        return _escape(v)
    body = []
    for row in rows:
        attrs = f'data-r15-row data-model="{_escape(row["model"])}"'
        if "message" in row:
            attrs += f' data-message="{row["message"]}"'
        cells = ''.join(f'<td>{display(k, row[k])}</td>' for k, _ in columns)
        body.append(f'<tr {attrs}>{cells}</tr>')
    return '<div class="r15-table"><table><thead><tr>'+''.join(f'<th scope="col">{_escape(label)}</th>' for _, label in columns)+'</tr></thead><tbody>'+''.join(body)+'</tbody></table></div>'


def render_revised_research(base_html: bytes, evidence: ClosedRevisedEvidence, analysis: dict[str, Any], *, release_id: str | None = None) -> bytes:
    """Preserve historical/main HTML and add the separately labelled research section."""
    base = base_html.decode()
    anchor = '<section class="robustness-section" data-testid="prompt-model-robustness-section" aria-labelledby="prompt-model-title">'
    if base.count(anchor) != 1 or 'data-testid="revised-robustness-section"' in base:
        raise ValueError("Protected research report insertion anchor is crossed")
    options = ''.join(f'<option value="{_escape(m)}">{_escape(_NAMES[m])}</option>' for m in MODELS)
    plots = ''.join(_chart(analysis, m, msg, metric) for m in MODELS for msg in MESSAGES for metric in ("realized", "judgment", "audience", "growth"))
    cells = _table(analysis["cells"], [("model", "Model"), ("prompt", "Prompt"), ("exposures", "Exposures 曝光"), ("judgment_rate", "Judgment率"), ("mean_probability", "辅助概率"), ("mean_confidence", "辅助置信度"), ("realized_positive", "Realized互动"), ("realized_rate", "Realized率"), ("campaign_positive_users", "去重正向用户")])
    slices = _table(analysis["segment_message_slices"], [("model", "Model"), ("prompt", "Prompt"), ("segment", "Segment"), ("message", "Message"), ("exposures", "Exposures"), ("realized_positive", "Realized互动"), ("realized_rate", "Realized率"), ("judgment_rate", "Judgment率")])
    direct = _table(analysis["direct"], [("model", "Model"), ("prompt", "Prompt"), ("comparison", "Contrast"), ("message", "Message"), ("reference_cell", "Reference"), ("pairs", "Pairs"), ("engage_disagreements", "Engage disagreement"), ("engage_delta", "Δ engage"), ("engage_lower_95", "95% lower"), ("engage_upper_95", "95% upper"), ("probability_delta", "Δ probability"), ("confidence_delta", "Δ confidence")])
    contrasts = _table(analysis["planned_contrasts"], [("factor", "Factor"), ("model", "Model"), ("prompt", "Prompt"), ("reference", "Reference"), ("rate_delta", "Δ realized rate"), ("label", "0.02 threshold label")])
    interactions = _table(analysis["prompt_model_interactions"], [("model", "Model"), ("prompt", "Prompt"), ("reference_model", "Reference model"), ("reference_prompt", "Reference prompt"), ("rate_delta", "Difference in differences"), ("label", "0.02 threshold label")])
    routes = _table(analysis["identity_strata"], [("model", "Requested model"), ("prompt", "Prompt"), ("observed_model", "Observed identity"), ("route", "Route"), ("judgments", "Judgments")])
    downloads = ''.join(f'<li><a download href="{name}">{name.rsplit("/",1)[-1]}</a></li>' for name in revised_downloads(evidence, analysis))
    ranges = []
    for model in MODELS:
        rows = [r for r in analysis["cells"] if r["model"] == model]
        lo, hi = min(r["realized_rate"] for r in rows), max(r["realized_rate"] for r in rows)
        ranges.append(f'{_escape(_NAMES[model])}: {lo:.2%}–{hi:.2%}（range {(hi-lo)*100:.2f} pp）')
    status = "已闭合正式四模型研究 / Released revised four-model research" if release_id else "独立研究候选，未发布 / Nondeployable candidate"
    section = f'''<section class="robustness-section r15" data-testid="revised-robustness-section" id="revised-robustness" data-release-state="{"production" if release_id else "candidate"}">
<style>{_REVISED_RELEASE_RESPONSIVE_CSS}.r15{{border-top:4px solid #153f75;margin:3rem 0;padding-top:2rem}}.r15 [hidden]{{display:none!important}}.r15 p{{max-width:105ch;line-height:1.65}}.r15-controls{{display:flex;flex-wrap:wrap;gap:1rem;margin:1.5rem 0}}.r15 label{{display:grid;gap:.4rem}}.r15 select{{font:inherit;padding:.6rem;background:white;border:1px solid #8292a4;border-radius:4px;max-width:100%}}.r15-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem}}.r15-grid article{{min-width:0;border-top:1px solid #a5b4c6;padding:1rem;background:#f6f8fc}}.r15 svg{{width:100%;height:auto}}.r15 h3{{font-size:1.1rem}}.r15-legend{{display:flex;gap:1rem;flex-wrap:wrap}}.r15-legend i{{display:inline-block;width:1.5rem;border-top:3px solid;margin-right:.4rem;vertical-align:middle}}.r15-table{{overflow:auto;max-width:100%;margin:1rem 0}}.r15 table{{border-collapse:collapse;font-size:.8rem;width:max-content;min-width:100%}}.r15 th,.r15 td{{padding:.6rem;border-bottom:1px solid #d8e0ea;text-align:left;white-space:nowrap}}.r15 th{{background:#eef3f9}}.r15 details{{margin:1.2rem 0}}.r15 summary{{cursor:pointer;font-weight:600}}.r15-notice{{padding:1rem;background:#f3f6fb;border-left:3px solid #153f75}}.r15 :focus-visible{{outline:3px solid #357bbe}}@media(max-width:700px){{.r15-grid{{grid-template-columns:1fr}}.r15-controls{{display:grid}}}}</style>
<p class="r15-notice">{status} · 2026-09-12 · <a href="#prompt-model-title">旧GPT析因证据 / Historical GPT evidence ↓</a></p>
<h2>提示词—模型稳健性：跨厂商四模型恢复实验<br><small>Prompt–Model sensitivity · cross-provider recovery</small></h2>
<p>本节使用同一 <strong>1,000-user sample</strong>、P0–P3、三条消息，每cell 1,800 exposures。四模型共28,800判断、16cells、480完整barriers；不是36,400-user Full-Pool主实验，也不是原五模型36,000/20/600全部完成。取消的Gemini3.8 Flash High为0调用。</p>
<p>旧GPT析因保留在下方：旧路径是直接action；本节是<strong>Provider Judgment → 固定draw → ABM Realization</strong>，只有realized-positive在完整batch barrier之后进入下一批推荐反馈。相同模型名不合并不同run，概率／置信度属于Judgment辅助指标。两阶段机制图与主实验、Historical、Primary／Shadow、排序权重证据保持独立。</p>
<p class="r15-notice"><strong>Observed sensitivity / 观察结论：</strong>{'; '.join(ranges)}。这些是每cell单条自适应路径的P0–P3范围，不是配对因果效应或总体“稳健”证明。模型间差异包含route、identity、request settings和路径反馈；未估计重复run的模型随机性。</p>
<div class="r15-controls"><label>Model / 模型<select data-testid="revised-model"><option value="all">全部四模型 / All models</option>{options}</select></label><label>Message / 消息<select data-testid="revised-message">{''.join(f'<option value="{m}">{m}</option>' for m in MESSAGES)}</select></label><label>Metric / 指标<select data-testid="revised-metric"><option value="realized">Realized rate / 实现互动率</option><option value="judgment">Judgment rate / 判断互动率</option><option value="audience">Audience distance / 受众距离</option><option value="growth">Campaign growth / 去重正向用户增长</option></select></label></div>
<p>曲线分母为截至该批次的实际user × message exposures；audience以同Prompt的GPT-5.6 Sol为基准。Growth是跨三条message去重的campaign users，与message选择无关。</p><div class="r15-grid" data-testid="revised-curves">{plots}</div>
<h3>P0–P3 结果 / Cell results</h3>{cells}
<details><summary>Segment × Message 切片（144格；分母随实际受众变化）</summary>{slices}</details>
<h3>共享种子直接决策 / Shared-seed direct decisions</h3><p>唯一直接配对面板为预声明Batch 0的{analysis['seed_users']}用户 × 3消息 = {analysis['seed_pairs_per_cell']} pairs，每cell均完整。按用户块bootstrap，保留同用户的全部所选消息；500次，seed20260809，2.5%/97.5%线性percentile区间。后续自适应轨迹没有进入这个配对bootstrap。比较分为同模型P0及同Prompt GPT-5.6 Sol；区间是固定设计下的条件不确定性，不证明统计等价。</p>
<p>直接engage与辅助概率阈值保留0.05；v2 realized路径阈值为0.02，低于阈值仅称small_observed_difference。两类阈值与基准不混用；下方旧GPT分析继续使用其原基准。</p><details><summary>配对结果：engage 95%区间、概率／置信度差值（其区间见 direct.csv） / Paired comparisons</summary>{direct}</details>
<h3>预定主效应与交互 / Planned contrasts and interactions</h3><p>沿v2合同按本次四模型等权汇总：模型对比平均P0–P3，Prompt对比平均四模型；交互为各模型相对P0的差值再减去GPT-5.6 Sol的对应差值。取消模型不进入平均。所有结果仍为描述性自适应路径，不赋予配对因果解释。</p>{contrasts}<details><summary>Prompt × Model 描述性交互</summary>{interactions}</details>
<h3>Model identity、route与失败历史</h3><p>Kimi：33条订阅<strong>k3-256k</strong>，7167条官方<strong>kimi-k3</strong>；双路由不能描述为单一一致模型条件，P0内也存在路由分层。Gemini requested <strong>gemini-3.1-pro</strong> / observed <strong>gemini-pro-agent</strong>，通过Antigravity OpenAI-compatible gateway，非direct Gemini Developer API；client-submitted prompt不代表不可观测gateway上下文之后的完整effective prompt。</p><p>Formal physical 28,913；新增20,052；108已知失败、5归档unknown原样保留；成功后重发0、未决0、每logical历史最多3次。全历史token总额<strong>unknown/null</strong>而非0。恢复过程中经显式批准的route、输出ceiling、usage reconciliation与重试政策沿原bundle保留；cash guard是保守预算，不是发票。Kimi官方与订阅费用不混币加总。</p><details><summary>逐Prompt identity／route分层</summary>{routes}</details>
<h3>同源分析下载 / Reproducible analysis downloads</h3><p>CSV与JSON由本节同一个闭合projection生成；不含raw Provider payload。Evidence保留原source/hash、历史失败及取消范围。旧研究下载保持原bytes。</p><ul data-testid="revised-downloads">{downloads}</ul>
<p>Evidence identity: <code>{evidence.document['identity_sha256']}</code> · 本次新增Provider calls=0。</p>
<script>(()=>{{const root=document.querySelector('[data-testid="revised-robustness-section"]');const model=root.querySelector('[data-testid="revised-model"]'),message=root.querySelector('[data-testid="revised-message"]'),metric=root.querySelector('[data-testid="revised-metric"]');function update(){{root.querySelectorAll('[data-r15-plot]').forEach(el=>{{const [m,msg,k]=el.dataset.r15Plot.split('|');el.hidden=(model.value!=='all'&&model.value!==m)||message.value!==msg||metric.value!==k}});root.querySelectorAll('[data-r15-row]').forEach(el=>{{el.hidden=(model.value!=='all'&&el.dataset.model!=='all'&&model.value!==el.dataset.model)||(el.dataset.message&&el.dataset.message!=='all'&&el.dataset.message!==message.value)}})}}[model,message,metric].forEach(el=>el.addEventListener('change',update));update()}})();</script>
</section>
'''
    result = base.replace(anchor, section + anchor)
    if release_id:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", release_id):
            raise ValueError("Release id must be a stable token")
        result, count = re.subn(r'<meta name="abm-release-id" content="[^"]+">', f'<meta name="abm-release-id" content="{release_id}">', result)
        if count != 1:
            raise ValueError("Report release metadata not unique")
        result = result.replace('<meta name="abm-release-contract" content="abm-report-release-contract-v13">', '<meta name="abm-release-contract" content="abm-report-release-contract-v15">')
    return result.encode()
