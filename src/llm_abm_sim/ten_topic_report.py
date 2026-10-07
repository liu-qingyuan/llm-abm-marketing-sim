"""Current ten-topic research presentation in the existing editorial shell."""
from __future__ import annotations

import html
import json
import re
from typing import Any

_STYLE = '''<style>
.ten-topic-current{max-width:1200px;margin:auto;padding:0 1.5rem 3rem}.tt-hero{display:grid;grid-template-columns:2fr 1fr;gap:2rem;padding:4rem 0 2rem}.tt-hero h1{font-size:clamp(2.5rem,6vw,5.8rem);line-height:1.08;margin:1rem 0;color:#19232c}.tt-shelf{color:#1e55be;letter-spacing:.08em;font-weight:700}.tt-stat{background:white;border:1px solid #ccd7e4;border-radius:12px;padding:1.5rem;align-self:center}.tt-stat strong{font-size:3rem;color:#245aba}.tt-controls{display:flex;gap:.7rem;flex-wrap:wrap;align-items:center;margin:1rem 0}.tt-controls select,.tt-controls button{padding:.6rem;border:1px solid #b8c6d8;border-radius:6px;background:#fff;color:#19232c}.tt-overflow{overflow:auto;margin:1rem 0}.tt-table{border-collapse:collapse;width:100%;background:#fff;font-size:.9rem}.tt-table td,.tt-table th{padding:.7rem;text-align:right;border-bottom:1px solid #d8e0ea;white-space:nowrap}.tt-table th:first-child,.tt-table td:first-child{text-align:left}.tt-table th{background:#edf2f8}.tt-note{color:#526377;font-size:.95rem;line-height:1.65}.tt-plots svg{max-width:100%;height:auto;display:block;background:#fff;border:1px solid #d8e0ea;border-radius:10px}.tt-legend{display:flex;flex-wrap:wrap;gap:1rem;padding:.7rem;font-size:.85rem}.tt-downloads{display:flex;flex-wrap:wrap;gap:.6rem 1rem}.tt-en{display:none}.ten-topic-current[data-language=en] .tt-en{display:initial}.ten-topic-current[data-language=en] .tt-zh{display:none}#single-topic-history{max-width:1200px;margin:2rem auto;border-top:1px solid #ccd7e4;padding:1rem}#single-topic-history>summary{font-size:1.35rem;font-weight:700;cursor:pointer}@media(max-width:650px){.tt-hero{grid-template-columns:1fr;padding-top:2rem}.ten-topic-current{padding:0 .9rem 2rem}.tt-table{font-size:.8rem}}
</style>'''

_SCRIPT = r'''<script>
(()=>{'use strict';const root=document.querySelector('.ten-topic-current');if(!root)return;
const d=JSON.parse(document.getElementById('ten-topic-public-data').textContent);const pct=x=>(100*Number(x)).toFixed(3)+'%';const num=x=>Number(x).toLocaleString(undefined,{maximumFractionDigits:3});
const title={baseline:'Baseline',activity_weights:'Activity weights',activity_p99:'Activity p99',local_weights_fixed:'Local weights · fixed',local_weights_rebuilt:'Local weights · rebuilt',local_p99_fixed:'Local p99 · fixed',local_p99_rebuilt:'Local p99 · rebuilt'};
const esc=x=>String(x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const table=(target,headers,rows)=>{target.innerHTML='<table class="tt-table"><thead><tr>'+headers.map(x=>'<th>'+esc(x)+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map(x=>'<td>'+esc(x)+'</td>').join('')+'</tr>').join('')+'</tbody></table>';};
function plot(target,groups){const colors=['#245aba','#bb5534','#188875','#9c4e95','#756b27','#333f6b','#657889'];let body='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 440" role="img" aria-label="Cumulative realized engagement rate / 累计实际互动率"><rect width="900" height="440" fill="white"/>';
for(let y=0;y<=4;y++){const sy=340-y*72;body+='<line x1="65" y1="'+sy+'" x2="850" y2="'+sy+'" stroke="#dbe2ea"/><text x="10" y="'+(sy+5)+'" fill="#526377">'+(y*25)+'%</text>';}
let legend='';groups.forEach((g,i)=>{const color=colors[i%colors.length];const points=g.rows.map(r=>[65+Number(r.batch)*785/30,340-Number(r.rate)*288].join(',')).join(' ');body+='<polyline fill="none" stroke="'+color+'" stroke-width="2.5" points="'+points+'"/>';legend+='<span style="color:'+color+'">'+esc(g.name)+'</span>';});
for(let x=0;x<=30;x+=5)body+='<text x="'+(65+x*785/30)+'" y="365" fill="#526377">'+x+'</text>';body+='<text x="65" y="405" fill="#526377">Batch / 传播批次 · cumulative realized interactions ÷ cumulative exposures</text></svg>';target.innerHTML=body+'<div class="tt-legend">'+legend+'</div>';}
function whole(){const rows=d.whole.rows.map(r=>[r.message,r.segment,num(r.exposures),pct(r.like_rate),pct(r.comment_rate),pct(r.share_rate),pct(r.ignore_rate),pct(r.realized_rate)]);table(root.querySelector('[data-tt-table=whole]'),['Message','Segment','Exposure','Like','Comment','Share','Ignore','Realized'],rows);plot(root.querySelector('[data-tt-plot=whole]'),['message_1','message_2','message_3'].map(m=>({name:m,rows:d.whole.curves.filter(r=>r.message===m).map(r=>({batch:r.batch,rate:r.realized_rate}))})));}
function sensitivity(study){const section=root.querySelector('[data-tt-study='+study+']');const m=section.querySelector('[data-tt-message]').value;const e=d[study].estimates.filter(r=>r.message===m);const keys=[...new Set(e.map(r=>r.configuration))];const rows=keys.map(k=>{const find=q=>e.find(r=>r.configuration===k&&r.metric===q);const rate=find('engagement_rate');const den=m==='all'?1800:600;return [title[k]||k,pct(rate.mean),pct(rate.lower)+' – '+pct(rate.upper),pct(find('like').mean/den),pct(find('comment').mean/den),pct(find('share').mean/den),pct(1-rate.mean),pct(rate.old_mean)];});table(section.querySelector('[data-tt-table]'),['Condition','Realized mean','95% interval','Like mean','Comment mean','Share mean','Ignore mean','Old mean'],rows);
const select=section.querySelector('[data-tt-condition]');if(!select.options.length){select.add(new Option('All conditions','all'));keys.forEach(k=>select.add(new Option(title[k]||k,k)));}const selected=select.value;const shown=keys.filter(k=>selected==='all'||selected===k);plot(section.querySelector('[data-tt-plot]'),shown.map(k=>({name:title[k]||k,rows:d[study].curves.filter(r=>r.configuration===k&&r.message===m).map(r=>({batch:r.batch,rate:r.new_rate_mean}))})));}
function models(){const section=root.querySelector('[data-tt-study=models]'),m=section.querySelector('[data-tt-message]').value,t=section.querySelector('[data-tt-template]').value,s=section.querySelector('[data-tt-segment]').value;let rows=m==='all'?d.models.conditions:s==='all'?d.models.messages:d.models.segments;const seg=section.querySelector('[data-tt-segment]');seg.disabled=m==='all';if(m==='all')seg.value='all';rows=rows.filter(r=>(m==='all'||r.message===m)&&(t==='all'||r.template===t)&&(m==='all'||s==='all'||r.segment===s));
table(section.querySelector('[data-tt-table]'),['Model','Prompt','Exposure','Realized','Like','Comment','Share','Ignore'],rows.map(r=>[r.model,r.template,num(r.exposures),pct(r.realized_rate),pct(r.like/r.exposures),pct(r.comment/r.exposures),pct(r.share/r.exposures),pct(r.ignore/r.exposures)]));
const templates=t==='all'?['P0','P1','P2','P3']:[t];const names=[...new Set(d.models.conditions.map(r=>r.model))];const groups=[];templates.forEach(tm=>names.forEach(n=>{const grouped=new Map();(m!=='all'&&s!=='all'?d.models.segment_curves:d.models.curves).filter(r=>r.model===n&&r.template===tm&&(m==='all'||r.message===m)&&(m==='all'||s==='all'||r.segment===s)).forEach(r=>{const b=Number(r.batch)+1;const sum=grouped.get(b)||{p:0,e:0};sum.p+=Number(r.realized_positive);sum.e+=Number(r.exposures);grouped.set(b,sum);});groups.push({name:n+' '+tm+' '+m,rows:[...grouped].filter(([b,v])=>v.e>0).sort((a,b)=>a[0]-b[0]).map(([batch,v])=>({batch,rate:v.p/v.e}))});}));plot(section.querySelector('[data-tt-plot]'),groups);}
root.addEventListener('change',e=>{const section=e.target.closest('[data-tt-study]');if(!section)return;const s=section.dataset.ttStudy;if(s==='models')models();else sensitivity(s);});
root.querySelectorAll('[data-tt-lang]').forEach(b=>b.addEventListener('click',()=>{root.dataset.language=b.dataset.ttLang;document.documentElement.lang=b.dataset.ttLang==='en'?'en-US':'zh-CN';const old=document.querySelector('[data-full-pool-language="'+document.documentElement.lang+'"]');if(old)old.click();root.querySelectorAll('[data-tt-lang]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));}));
function oldAnchor(){const hash=location.hash;if(!hash)return;const el=document.getElementById(decodeURIComponent(hash.slice(1)));if(el){let p=el.parentElement;while(p){if(p.tagName==='DETAILS')p.open=true;p=p.parentElement;}}}window.addEventListener('hashchange',oldAnchor);oldAnchor();
whole();sensitivity('parameters');sensitivity('index');models();
})();</script>'''


def _bi(zh: str, en: str) -> str:
    return f'<span class="tt-zh">{html.escape(zh)}</span><span class="tt-en">{html.escape(en)}</span>'


def _message_control() -> str:
    return '<label>Message <select data-tt-message><option value="all">All messages</option><option value="message_1">M1</option><option value="message_2">M2</option><option value="message_3">M3</option></select></label>'


def render_ten_topic_research(base_html: bytes, data: dict[str, Any], *, release_id: str) -> bytes:
    """Render current formal aggregate views and keep the old report explicitly historical."""
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,159}', release_id):
        raise ValueError('Invalid release id')
    base = base_html.decode('utf-8')
    marker = '<meta name="abm-release-contract" content="abm-report-release-contract-v16">'
    if base.count('<body>') != 1 or base.count('</body>') != 1 or base.count(marker) != 1:
        raise ValueError('Expected protected v16 editorial report')
    if data.get('schema_version') != 'ten-topic-public-statistics-v1':
        raise ValueError('Public aggregate statistics required')
    start, end = base.index('<body>') + 6, base.rindex('</body>')
    legacy = base[start:end]
    legacy, n = re.subn(r'<nav id="research-navigation".*?</nav>', '', legacy, flags=re.DOTALL)
    if n != 1:
        raise ValueError('Protected research navigation must be unique')
    for identifier in ('full-pool-main', 'revised-robustness', 'parameter-study', 'index-sensitivity-study'):
        legacy = re.sub(r'(?<![\w-])id="' + identifier + '"', 'id="legacy-' + identifier + '"', legacy)
        legacy = legacy.replace('href="#' + identifier + '"', 'href="#legacy-' + identifier + '"')
    whole = data['whole']['summary']
    denominator = whole['exposures']
    positive = sum(whole[k] for k in ('like', 'comment', 'share'))
    if denominator != 109200 or sum(whole[k] for k in ('like', 'comment', 'share', 'ignore')) != denominator:
        raise ValueError('Whole-sample display denominator or actions crossed')
    topics = '、'.join(data['network'].get('actual_ten_topic_names', []))
    navigation = '<nav id="research-navigation" aria-label="研究导航 / Research navigation" style="padding:1rem;max-width:1200px;margin:auto"><h2>研究导航 / Research navigation</h2><p>十话题合并历史网络 · Ten-topic historical interaction network</p><ul>'
    for anchor, label in [('full-pool-main','Whole sample'),('parameter-study','Parameter'),('index-sensitivity-study','Activity / Local Influence'),('revised-robustness','Prompt–Model'),('single-topic-history','旧版与历史研究 / Historical research')]:
        navigation += f'<li><a href="#{anchor}">{label}</a></li>'
    navigation += '</ul></nav>'
    current = '<main class="ten-topic-current" data-language="zh" data-testid="ten-topic-current"><div class="tt-controls" role="group" aria-label="报告语言"><button data-tt-lang="zh" aria-pressed="true">中文</button><button data-tt-lang="en" aria-pressed="false">English</button></div><section id="full-pool-main" class="tt-hero"><div><p class="tt-shelf">'+_bi('正式研究 · 十话题历史互动网络','Formal research · ten-topic historical network')+'<h1>'+_bi('全样本实际行为','Whole-sample realized behavior')+'</h1><p>'+_bi('36,400用户 · 三条消息 · 30传播批次','36,400 users · three messages · 30 batches')+f'</p></div><div class="tt-stat"><p>Realized interaction / 实际互动</p><strong>{positive/denominator:.3%}</strong><p>{positive:,} / {denominator:,} exposures</p></div></section>'
    current += '<section class="full-pool-section"><h2>'+_bi('方法与统计口径','Methods and units')+'</h2><p>'+_bi('仅合并最终正式数据集的十个实际采集话题，保留holdout排除、建边、去重与权重累计规则。Network Influence加权度及P95、反馈邻居和种子邻居补选均采用该网络；Local Influence原有全话题度数部分、Activity和Global Influence口径不变。','The network combines exactly ten collected topics in the final dataset, with unchanged holdout, edge and weight rules. Weighted Network Influence, feedback neighbors and sampling connections share it; existing Activity, Local and Global Influence definitions remain unchanged.')+'</p><p class="tt-note">P95 = '+str(data['network']['p95'])+' · '+html.escape(topics)+'</p><p>'+_bi('推荐权重0.50/0.30/0.20，邻居饱和阈值3。种子优先、逐用户消息仅曝光一次；三消息完成后才更新下一批反馈。意向判断经概率抽样才成为实际行为，二者不互换。','Recommendation weights 0.50/0.30/0.20 and neighbor saturation 3. Seed priority and unique user-message exposure are retained; feedback commits only after all three messages. Intent is not realized behavior.')+'</p></section>'
    current += '<section class="full-pool-section"><h2>'+_bi('全样本结果与传播曲线','Whole-sample results and trajectories')+'</h2><p class="tt-note">'+_bi('单次行为seed20260823；每条消息36,400次曝光。表格比例以相应消息/类别实际曝光为分母；曲线为逐批累计互动÷累计曝光。','One behavior seed, 20260823; 36,400 exposures per message. Table rates use the displayed group exposures; curves use cumulative interactions divided by cumulative exposures.')+'</p><div class="tt-overflow" data-tt-table="whole"></div><div class="tt-plots" data-tt-plot="whole"></div></section>'
    endpoint_rates = [r['mean'] for r in data['parameters']['estimates'] if r['metric'] == 'engagement_rate' and r['message'] == 'all']
    parameter_range = f'{min(endpoint_rates):.3%}–{max(endpoint_rates):.3%}' if endpoint_rates else ''
    rebuilt_overlap = data['index']['local_p99_rebuilt_overlap']
    for study, identifier, zh, en, note in [('parameters','parameter-study','推荐参数研究','Recommendation parameters',f'21组×100行为seed，共2,100路径。各路径1,800曝光，30批。终点不再全部相同，范围{parameter_range}；不是普遍稳健或不敏感结论。'),('index','index-sensitivity-study','用户指标敏感性研究','User-indicator sensitivity',f'原7臂×100行为seed，共700路径。区分fixed与rebuilt，Local p99重建与新基准重合{rebuilt_overlap}/1000；样本构成也是变化来源。Local权重fixed/rebuilt及两研究共享baseline不是独立重复证据。')]:
        current += f'<section id="{identifier}" class="full-pool-section" data-tt-study="{study}"><h2>'+_bi(zh,en)+'</h2><p class="tt-note">'+_bi(note, f'21 configurations and 100 behavior seeds: 2,100 paths. Endpoints differ in the tested matrix: {parameter_range}. This is not a universal robustness result.' if study == 'parameters' else f'Seven original arms and 100 behavior seeds: 700 paths. Fixed and rebuilt arms differ in meaning. Local p99 rebuilt overlaps the new baseline by {rebuilt_overlap}/1000 users. Shared baseline and identical Local-weight arms are not independent replications.')+'</p><p class="tt-note">'+_bi('分母每消息600、三消息合计1,800。显示100行为seed均值及df99 Student-t普通95%区间，仅描述固定判断/数据下的行为Monte Carlo误差；100seed不是100次LLM判断。原Bonferroni家族参数123、指标120的同时区间保留在对应数据下载。','Denominators are 600 per message and 1,800 overall. Means and ordinary df99 Student-t intervals reflect 100 behavior seeds conditional on fixed judgments/data, not 100 LLM judgments. Original simultaneous intervals remain in the downloads.')+'</p><div class="tt-controls">'+_message_control()+'<label>Curve <select data-tt-condition></select></label></div><div class="tt-overflow" data-tt-table></div><div class="tt-plots" data-tt-plot></div></section>'
    current += '<section id="revised-robustness" class="full-pool-section" data-tt-study="models"><h2>'+_bi('四模型与P0–P3','Four models and P0–P3')+'</h2><p class="tt-note">'+_bi('同一新基准1,000人，16条件×1,800曝光，共28,800曝光；单次行为seed20260823，非100seed均值。DeepSeek新版本V4.1 Flash，旧版V4 Flash。Kimi统一显示；Gemini观测为原网关alias gemini-pro-agent，隐藏上下文和原生后端不可观测。','The same new 1,000-user baseline: 16 conditions, 1,800 exposures each, 28,800 total. One behavior seed, not a 100-seed mean. DeepSeek is user-authorized V4.1 Flash versus old V4 Flash; Kimi remains one research model. Gemini exposes the original gateway alias, with hidden effective context/backend limits.')+'</p><div class="tt-controls">'+_message_control()+'<label>Prompt <select data-tt-template><option value="all">All</option>'+''.join(f'<option value="P{i}">P{i}</option>' for i in range(4))+'</select></label><label>Segment <select data-tt-segment><option value="all">All</option><option>S1</option><option>S2</option><option>S3</option></select></label></div><div class="tt-overflow" data-tt-table></div><div class="tt-plots" data-tt-plot></div><p class="tt-note">'+_bi('共同Batch0仅20seed用户×3消息，原500次用户block bootstrap配对区间见下载；自适应路径仅描述，不把曝光、用户或复用记录冒充独立实验重复。S1–S3是合成标签，不是确认的心理画像。','The fixed common Batch0 panel has 20 seed users and three messages; original 500 user-block bootstrap intervals are downloadable. Adaptive paths are descriptive, not independent repeated experiments. S1–S3 are synthetic labels, not verified psychological profiles.')+'</p></section>'
    current += '<section id="ten-topic-downloads" class="full-pool-section"><h2>'+_bi('对应结果与数据下载','Matching results and downloads')+'</h2><div class="tt-downloads">'
    for item in data.get('download_links', []):
        current += f'<a download href="{html.escape(item["path"],quote=True)}">{html.escape(item["label"])}</a>'
    current += '</div><p class="tt-note">'+_bi('各部分的CSV、JSON、工作簿与曲线均来自本版本已验收统计，不公开新原始响应、凭证或用户明细判断库。新旧差异共同包含网络、样本及服务时点，不作纯网络、纯指标因果推断。','CSV, JSON, workbooks and curves use the accepted statistics for this version. No new raw responses, credentials or user judgment banks are public. Changes jointly reflect network, sampling and service timing, not isolated causal effects.')+'</p></section></main>'
    payload=json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':')).replace('<',r'\u003c').replace('>',r'\u003e').replace('&',r'\u0026')
    body=navigation+current+'<details id="single-topic-history"><summary>旧版：单一话题网络及既有历史研究 / Previous single-topic and historical research</summary><p class="tt-note">以下保留旧版原统计、交互和下载，不属于上方十话题新版本；不同研究不合并分母。</p>'+legacy+'</details><script type="application/json" id="ten-topic-public-data">'+payload+'</script>'+_SCRIPT
    result=base[:start]+body+base[end:]
    result=result.replace(marker,'<meta name="abm-release-contract" content="abm-report-release-contract-v17">')
    result,n=re.subn(r'<meta name="abm-release-id" content="[^"]+">',f'<meta name="abm-release-id" content="{html.escape(release_id)}">',result)
    if n != 1:
        raise ValueError('Release metadata must be unique')
    return result.replace('</head>',_STYLE+'</head>',1).encode()


def public_curve_svg(groups: list[dict[str, Any]], *, title: str) -> bytes:
    """Export the same cumulative-rate coordinates/units used by the page plots."""
    colors = ['#245aba', '#bb5534', '#188875', '#9c4e95', '#756b27', '#333f6b', '#657889']
    height = max(480, 420 + ((len(groups) + 2) // 3) * 17)
    body = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 {height}" role="img">',
            '<rect width="900" height="480" fill="white"/>',
            f'<title>{html.escape(title)}</title>']
    for tick in range(5):
        y = 340 - tick * 72
        body += [f'<line x1="65" y1="{y}" x2="850" y2="{y}" stroke="#dbe2ea"/>',
                 f'<text x="10" y="{y + 5}" fill="#526377">{tick * 25}%</text>']
    for index, group in enumerate(groups):
        points = ' '.join(f"{65 + r['batch'] * 785 / 30:g},{340 - r['rate'] * 288:g}"
                          for r in group['rows'] if r['rate'] is not None)
        color = colors[index % len(colors)]
        body.append(f'<polyline fill="none" stroke="{color}" stroke-width="2.5" points="{points}"/>')
        body.append(f'<text x="{65 + (index % 3) * 265}" y="{395 + (index // 3) * 17}" fill="{color}" font-size="11">{html.escape(group["name"])}</text>')
    body.append('<text x="65" y="370" fill="#526377">Batch · cumulative realized interactions / cumulative exposures</text></svg>')
    return '\n'.join(body).encode()


def ten_topic_public_downloads(data: dict[str, Any]) -> dict[str, bytes]:
    """Publish only aggregate study tables, curve points and contextual JSON."""
    import csv
    import io

    def csv_bytes(rows: list[dict[str, Any]]) -> bytes:
        if not rows:
            raise ValueError('Empty formal public table')
        columns = list(dict.fromkeys(key for row in rows for key in row))
        stream = io.StringIO(newline='')
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
        return stream.getvalue().encode('utf-8-sig')

    tables = {
        'whole/results.csv': data['whole']['rows'], 'whole/curves.csv': data['whole']['curves'],
        'parameter/estimates.csv': data['parameters']['estimates'],
        'parameter/mean-curves.csv': data['parameters']['curves'],
        'parameter/paired-contrasts.csv': data['parameters']['paired'],
        'index/estimates.csv': data['index']['estimates'], 'index/mean-curves.csv': data['index']['curves'],
        'index/paired-contrasts.csv': data['index']['paired'], 'index/composition.csv': data['index']['composition'],
        'models/conditions.csv': data['models']['conditions'], 'models/messages.csv': data['models']['messages'],
        'models/segments.csv': data['models']['segments'], 'models/curves.csv': data['models']['curves'],
        'models/segment-curves.csv': data['models']['segment_curves'],
        'models/old-new.csv': data['models']['comparison'],
        'models/paired-seed-panel.csv': data['models']['paired_seed'],
    }
    files = {'ten-topic/' + name: csv_bytes(rows) for name, rows in tables.items()}
    for study in ('whole', 'parameters', 'index', 'models'):
        files['ten-topic/' + study + '/results.json'] = json.dumps(
            data[study], ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    files['ten-topic/methods.json'] = json.dumps({
        'network': data['network'], 'behavior_seed': 20260823,
        'whole_and_models_behavior_realizations': 1, 'sensitivity_behavior_seeds': 100,
        'sensitivity_interval': 'df99 Student-t conditional on fixed judgments/data; original families preserved',
        'holdout_rules_unchanged': True, 'sample_build_rule_unchanged_new_network': True,
        'local_p99_rebuilt_baseline_overlap': data['index']['local_p99_rebuilt_overlap'],
        'model_version_change': 'DeepSeek V4 Flash old versus user-approved V4.1 Flash new',
        'gemini_observed_model': 'gemini-pro-agent; original gateway, hidden effective context not observed',
        'comparison_scope': 'joint network/sample/service-time and indicator/model version effects; not isolated causal effects',
        'provider_calls_during_publication': 0,
    }, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    for message in ('message_1', 'message_2', 'message_3'):
        groups = [{'name': message, 'rows': [{'batch': r['batch'], 'rate': r['realized_rate']}
                                            for r in data['whole']['curves'] if r['message'] == message]}]
        files[f'ten-topic/whole/{message}-curves.svg'] = public_curve_svg(groups, title='Whole sample ' + message)
    for study, folder in [('parameters', 'parameter'), ('index', 'index')]:
        for message in ('all', 'message_1', 'message_2', 'message_3'):
            selected = [r for r in data[study]['curves'] if r['message'] == message]
            keys = sorted({r['configuration'] for r in selected})
            groups = [{'name': key, 'rows': [{'batch': r['batch'], 'rate': r['new_rate_mean']}
                                            for r in selected if r['configuration'] == key]} for key in keys]
            files[f'ten-topic/{folder}/{message}-curves.svg'] = public_curve_svg(groups, title=folder + ' 100-seed mean ' + message)
    for template in ('P0', 'P1', 'P2', 'P3'):
        for message in ('message_1', 'message_2', 'message_3'):
            selected = [r for r in data['models']['curves'] if r['template'] == template and r['message'] == message]
            names = sorted({r['model'] for r in selected})
            groups = [{'name': name, 'rows': [{'batch': r['batch'] + 1, 'rate': r['realized_rate']}
                                             for r in selected if r['model'] == name]} for name in names]
            files[f'ten-topic/models/{template}-{message}-curves.svg'] = public_curve_svg(groups, title=template + ' ' + message)
    return files


def ten_topic_workbook_tables(data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Aggregate workbook source tables; no private roots or per-user data."""
    return {
        'Methods': [
            {'Item': 'Network', 'Value': 'Ten actual collected topics; holdout-safe historical interactions'},
            {'Item': 'Network P95', 'Value': data['network']['p95']},
            {'Item': 'Whole sample', 'Value': '36,400 users;109,200 exposures;single behavior seed20260823'},
            {'Item': 'Parameter', 'Value': '21 configurations;100 behavior seeds;2,100 paths'},
            {'Item': 'Indicator', 'Value': '7 arms;100 behavior seeds;700 paths'},
            {'Item': 'Local p99 rebuilt overlap', 'Value': data['index']['local_p99_rebuilt_overlap']},
            {'Item': 'Four models', 'Value': '16 conditions;28,800 exposures;single behavior seed20260823'},
            {'Item': 'Intervals', 'Value': 'df99 Student-t, conditional behavior Monte Carlo; not LLM repetitions'},
            {'Item': 'Rates', 'Value': 'Actual interactions / stated exposures; curves use cumulative denominator'},
            {'Item': 'DeepSeek', 'Value': 'User-approved V4.1 Flash new;V4 Flash historical'},
            {'Item': 'Gemini', 'Value': 'Observed gateway alias gemini-pro-agent;hidden effective context unobserved'},
            {'Item': 'Interpretation', 'Value': 'Joint network/sample/indicator/model service-time changes;not isolated causal effects'},
        ],
        'Whole results': data['whole']['rows'], 'Whole curves': data['whole']['curves'],
        'Parameter estimates': data['parameters']['estimates'], 'Parameter curves': data['parameters']['curves'],
        'Parameter contrasts': data['parameters']['paired'],
        'Indicator estimates': data['index']['estimates'], 'Indicator curves': data['index']['curves'],
        'Indicator contrasts': data['index']['paired'], 'Sample composition': data['index']['composition'],
        'Model conditions': data['models']['conditions'], 'Model messages': data['models']['messages'],
        'Model segments': data['models']['segments'], 'Model curves': data['models']['curves'],
        'Category curves': data['models']['segment_curves'], 'Model old new': data['models']['comparison'],
        'Model paired seeds': data['models']['paired_seed'],
    }
