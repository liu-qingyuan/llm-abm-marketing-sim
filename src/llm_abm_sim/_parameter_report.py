"""Static standalone report derived only from closed parameter Evidence."""
from __future__ import annotations

import html
from pathlib import Path
from typing import Any

COLORS=('#166534','#1d4ed8','#b91c1c','#7e22ce','#c2410c','#0e7490','#a16207')
WEIGHT_LABELS=('0.50/0.30/0.20','0.65/0.15/0.20','0.35/0.45/0.20','0.65/0.30/0.05',
               '0.35/0.30/0.35','0.50/0.45/0.05','0.50/0.15/0.35')


def _svg(trajectories: list[dict[str,Any]], message: str, threshold: int) -> str:
    selected=[r for r in trajectories if r['message']==message and r['configuration'].endswith(f'-h{threshold}')]
    minimum=min(0.,min(r['seed_q025'] for r in selected))
    maximum=max(r['seed_q975'] for r in selected)
    margin=max(.02,(maximum-minimum)*.08)
    low,high=minimum-margin,maximum+margin
    def x(batch: int) -> float:
        return 65+(batch-1)/29*595
    def y(rate: float) -> float:
        return 275-(rate-low)/(high-low)*220
    pieces=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 710 370" role="img" aria-label="{message}, h={threshold}">',
            '<rect width="710" height="370" fill="white"/>',
            f'<text x="65" y="25" font-family="sans-serif" font-size="16">{message} · h={threshold}</text>']
    for i in range(5):
        value=low+(high-low)*i/4
        yy=y(value)
        pieces.append(f'<path d="M65 {yy:.2f}H660" stroke="#ddd"/><text x="57" y="{yy+4:.2f}" text-anchor="end" font-size="12">{value*100:.1f}%</text>')
    for batch in (1,5,10,15,20,25,30):
        pieces.append(f'<text x="{x(batch):.2f}" y="295" text-anchor="middle" font-size="12">{batch}</text>')
    for w,color in enumerate(COLORS):
        rows=sorted((r for r in selected if r['configuration']==f'w{w}-h{threshold}'),key=lambda r:r['batch'])
        # One pointwise seed-distribution band for B avoids 7 overlapping opaque bands.
        if w==0:
            points=[f"{x(r['batch']):.2f},{y(r['seed_q025']):.2f}" for r in rows]
            points += [f"{x(r['batch']):.2f},{y(r['seed_q975']):.2f}" for r in reversed(rows)]
            pieces.append(f'<polygon points="{" ".join(points)}" fill="{color}" opacity="0.1"/>')
        points=' '.join(f"{x(r['batch']):.2f},{y(r['mean_cumulative_rate']):.2f}" for r in rows)
        pieces.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="{3 if w==0 else 1.7}"/>')
        xx=65+(w%4)*155
        yy=320+(w//4)*22
        pieces.append(f'<path d="M{xx} {yy}h15" stroke="{color}" stroke-width="3"/><text x="{xx+20}" y="{yy+4}" font-size="11">{WEIGHT_LABELS[w]}</text>')
    return ''.join(pieces)+'</svg>'


def render(root: Path, evidence: dict[str,Any], trajectories: list[dict[str,Any]]) -> None:
    comparisons=evidence['comparisons']
    conclusions=[]
    for contrast in sorted({r['contrast'] for r in comparisons}):
        rows=[r for r in comparisons if r['contrast']==contrast]
        baseline=next(r for r in rows if r['configuration']=='w0-h3')
        same=baseline['direction']!='undetermined' and all(r['direction']==baseline['direction'] for r in rows)
        amplitude=[r['amplitude'] for r in rows if r['configuration']!='w0-h3']
        status=('所测配置内幅度等效' if all(v=='equivalent_in_tested_range' for v in amplitude)
                else '至少一个配置达到幅度敏感判据' if 'sensitive' in amplitude else '幅度等效证据不足')
        conclusions.append(f"{contrast}：基准方向 {baseline['direction']}；全矩阵方向{'保持' if same else '未统一确认'}；{status}。")
    charts=[]
    messages=['message_1','message_2','message_3','message_1-message_2','message_1-message_3','message_2-message_3']
    for message in messages:
        charts.append(f'<h3>{message}</h3><div class="charts">')
        for threshold in (1,3,6):
            name=f'{message}-h{threshold}.svg'
            (root/name).write_text(_svg(trajectories,message,threshold))
            charts.append(f'<img src="{name}" alt="{message}, feedback threshold {threshold}"/>')
        charts.append('</div>')
    rate_rows=''.join('<tr>'+''.join(f'<td>{html.escape(str(value))}</td>' for value in [r['configuration'],r['message'],
        f"{r['mean']*100:.2f}%",f"[{r['lower']*100:.2f}, {r['upper']*100:.2f}]%",
        f"{r['historical_exposure_mean']:.1f}/600"])+'</tr>' for r in evidence['rates'])
    contrast_rows=''.join('<tr>'+''.join(f'<td>{html.escape(str(value))}</td>' for value in [r['configuration'],r['contrast'],
        f"{r['difference_mean']*100:.2f} [{r['difference_lower']*100:.2f}, {r['difference_upper']*100:.2f}]",
        f"{r['delta_mean']*100:.2f} [{r['delta_lower']*100:.2f}, {r['delta_upper']*100:.2f}]",
        r['direction'],r['amplitude'],'达标' if r['mc_precision_met'] else '不足'])+'</tr>' for r in comparisons)
    collection=evidence['collection']
    nominal=collection['known_nominal_cost_usd']
    references='''<li><a href="https://link.springer.com/article/10.1023/A:1021240730564">Burke (2002)</a>：组合推荐理论背景，不证明本项目系数。</li>
<li><a href="https://doi.org/10.1007/978-3-540-72079-9_10">Pazzani &amp; Billsus (2007)</a>：用户内容匹配，不验证六维合成标签。</li>
<li><a href="https://arxiv.org/abs/1206.4327">Bakshy et al. (2012)</a>：社交定向关联与社交线索影响应区分。本研究评论图不是好友图，P0不展示动态邻居线索，反馈只改变推荐。</li>
<li><a href="https://arxiv.org/abs/1711.11359">Saltelli et al. (2019)</a>：合理探索输入空间；有限受约束21点不是全局敏感性保证。</li>'''
    limits='''结论仅条件于固定1000用户、历史图、三消息、GPT-5.6 Sol/P0及固定判断库。每消息600曝光，每路径1800；3000为判断库容量。自适应曝光不是IID配对样本；共同随机数配对的是完整seed路径。区间仅反映realization随机性，不含LLM重采样、服务漂移、样本/图不确定性；不推广至其他模型/Prompt、36400用户或真实平台因果效果。旧判断来自2026-09-11，新判断采集时间另列；隐藏服务端版本不可观测，完整客户端重建一致不证明隐藏上下文相同。P95、Top20、权重、阈值和2pp界值均为研究者设定，不是抖音系数或文献估计。'''
    document=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>GPT-P0 动态参数敏感性研究</title>
<style>body{{font:15px/1.65 system-ui,sans-serif;color:#18302c;background:#fafaf7;margin:40px auto;max-width:1500px;padding:0 24px}}h1,h2,h3{{line-height:1.25}}section{{margin:32px 0}}table{{border-collapse:collapse;width:100%;font-size:13px}}td,th{{border-bottom:1px solid #ddd;padding:8px;text-align:left}}th{{background:#edf2ee}}.charts{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}}img{{width:100%}}.scroll{{overflow:auto}}code{{overflow-wrap:anywhere}}@media(max-width:900px){{.charts{{grid-template-columns:1fr}}}}</style>
<h1>GPT-P0 千人样本动态参数敏感性研究</h1><p>21配置 × 100固定realization种子 · 2,100独立路径 · 3,780,000曝光 · 63,000完整barriers</p>
<section><h2>主要结论</h2><ul>{''.join('<li>'+html.escape(c)+'</li>' for c in conclusions)}</ul><p>结果由逐路径独立曝光、实现和反馈产生，非冻结反馈重排序。未预设“不敏感”。</p></section>
<section><h2>设计与解释</h2><p>基准w0-h3：网络/反馈/内容权重0.50/0.30/0.20；反馈min(1,engaged-neighbor-count/h)。7个权重点与h=1/3/6交叉；保留固定P95、共享Batch0 seed users、Top20与30批。realization种子2026091700..2026091799；同seed/pair的draw跨配置相同。旧1800判断按客户端重建新接纳政策复用，补齐1200后固定库。</p><p>三消息两两对比；实际意义ε=2pp。表中差异/Δ区间采用123个均值Bonferroni双侧t区间（df99，临界值{evidence['simultaneous_t_critical']:.8f}），近似解释不构成有限样本严格保证。普通95%均值区间半宽目标0.5pp；未达标明确显示。曲线是seed均值，w0阴影为点态2.5%–97.5%模拟分位带，不是全时程置信带；全部配置分位数见CSV。</p></section>
<section><h2>逐批动态曲线</h2>{''.join(charts)}</section>
<section><h2>消息差异与相对基准变化（百分点）</h2><div class="scroll"><table><thead><tr><th>配置</th><th>对比</th><th>差异 [校正区间]</th><th>Δ [校正区间]</th><th>方向</th><th>幅度</th><th>MC精度</th></tr></thead><tbody>{contrast_rows}</tbody></table></div></section>
<section><h2>参数终值与旧判断曝光比例</h2><table><tr><th>配置</th><th>消息</th><th>平均互动率</th><th>普通95%均值区间</th><th>平均旧判断曝光</th></tr>{rate_rows}</table></section>
<section><h2>账本与溯源</h2><p>旧账本：1800成功、1804物理请求（4次已结算失败）；成功响应名义参考$15.593085，不是实际发票。新增：{collection['new_successes']}成功，{collection['physical_requests']}物理请求，资格{collection['qualification_requests']}，重试{collection['retry_requests']}。已知名义成本小计${nominal:.6f}；成本未知attempts={collection['nominal_cost_unknown_attempts']}。已知response token小计：{html.escape(str(collection['known_response_usage']))}；无完整response usage的attempt数={collection['response_usage_missing_attempts']}。实际额外扣款未提供独立账单证据，保持null；无自动充值/购买/reset。离线动态研究Provider调用0。</p><p>新采窗口：{html.escape(str(evidence['new_collection_window']))}。旧/新曝光比例仅帮助识别时间混杂，不识别其因果效应。</p><p>Bank SHA256：<code>{evidence['bank_sha256']}</code><br>Study SHA256：<code>{evidence['study_manifest_sha256']}</code></p><p><a href="evidence.json">闭合Evidence</a> · <a href="path-summary.csv">2100路径摘要</a> · <a href="parameter-rates.csv">参数表</a> · <a href="message-contrasts.csv">消息对比</a> · <a href="trajectories.csv">曲线数据</a></p></section>
<section><h2>文献与研究限制</h2><ul>{references}</ul><p>{limits}</p><p>独立研究产物，非既有Formal发布合同；未自动部署canonical网站。</p></section></html>'''
    (root/'report.html').write_text(document)
    (root/'summary.md').write_text('# GPT-P0 动态参数敏感性研究\n\n'+'\n'.join('- '+c for c in conclusions)
        +'\n\n'+limits+'\n\n完整数据：parameter-rates.csv、message-contrasts.csv、trajectories.csv、path-summary.csv；交互查看 report.html。\n')
