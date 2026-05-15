const I18N = {
  'en-US': {eyebrow:'Local single-user SaaS-like console',title:'LLM-ABM Marketing Simulator',subtitle:'Upload a social graph, validate it, run provider-backed diffusion, and inspect bilingual results locally.',providerTitle:'Provider readiness',mockLabel:'Use mock provider for test/dev',dataTitle:'1. Dataset validation',dataHelp:'Upload users and edges as CSV or JSON. Edge JSON accepts either {edges:[...]} or a bare list.',usersFile:'Users CSV/JSON',edgesFile:'Edges CSV/JSON',seedUsers:'Seed users',validate:'Validate dataset',template:'Download template',runTitle:'2. Scenario and run',postText:'Marketing post',topics:'Topic tags',mediaSummary:'Media summary',platformMood:'Platform context',horizon:'Horizon',startRun:'Start run',resultsTitle:'3. Results',openReport:'Open generated report',trendTitle:'Trend chart',networkTitle:'Network propagation timeline',datasetTitle:'Dataset validation',providerEvidence:'Provider evidence',agentIO:'Agent I/O inspector',influencers:'Key influencers'},
  'zh-CN': {eyebrow:'本地单用户 SaaS 风格控制台',title:'LLM-ABM 营销传播模拟器',subtitle:'上传社交图数据，完成校验，运行 Provider 驱动的传播模拟，并在本地查看双语结果。',providerTitle:'Provider 就绪状态',mockLabel:'使用测试/开发 Mock Provider',dataTitle:'1. 数据集校验',dataHelp:'上传 CSV 或 JSON 用户与边数据。边 JSON 支持 {edges:[...]} 或裸数组。',usersFile:'用户 CSV/JSON',edgesFile:'关系边 CSV/JSON',seedUsers:'种子用户',validate:'校验数据集',template:'下载模板',runTitle:'2. 场景与运行',postText:'营销帖子',topics:'话题标签',mediaSummary:'素材摘要',platformMood:'平台语境',horizon:'仿真步数',startRun:'开始运行',resultsTitle:'3. 结果',openReport:'打开生成报告',trendTitle:'趋势图',networkTitle:'网络传播时间线',datasetTitle:'数据集校验',providerEvidence:'Provider 证据',agentIO:'Agent 输入/输出检查器',influencers:'关键影响者'}
};
let currentLang = 'en-US';
let validationId = null;
let validationPayload = null;
let lastReport = null;

function t(key){ return (I18N[currentLang]||I18N['en-US'])[key] || key; }
function applyI18n(){ document.documentElement.lang=currentLang; document.querySelectorAll('[data-i18n]').forEach(el=>{el.textContent=t(el.dataset.i18n)}); if(lastReport) renderReport(lastReport); }
function setPanel(id, text){ document.getElementById(id).textContent = text; }
function safeJson(value){ return JSON.stringify(value, null, 2); }

async function refreshReadiness(){
  const mock = document.getElementById('mock-provider').checked;
  const res = await fetch(`/api/provider/readiness?mock_provider=${mock ? 'true':'false'}`);
  const data = await res.json();
  const state = document.getElementById('provider-state');
  state.textContent = data.state + (data.mock ? ' / MOCK' : '');
  state.className = 'pill ' + (data.state === 'ready' || data.state === 'mock' ? 'good' : 'bad');
  document.getElementById('provider-reasons').textContent = (data.reasons || []).join('; ') || (data.mock ? 'Mock provider mode is visibly labeled and secret-free.' : 'Provider appears ready.');
}

document.getElementById('language').addEventListener('change', e => { currentLang = e.target.value; applyI18n(); });
document.getElementById('mock-provider').addEventListener('change', refreshReadiness);

document.getElementById('dataset-form').addEventListener('submit', async e => {
  e.preventDefault();
  const form = e.currentTarget;
  const fd = new FormData(form);
  setPanel('validation-output','Validating...');
  const res = await fetch('/api/datasets/validate', { method:'POST', body: fd });
  const data = await res.json();
  if(!res.ok || !data.valid){ setPanel('validation-output', 'Validation failed: ' + safeJson(data.error || data)); return; }
  validationId = data.validation_id;
  validationPayload = data.dataset_validation;
  setPanel('validation-output', `OK validation_id=${validationId}\nprofiles=${data.preview.profile_count} edges=${data.preview.edge_count}\n` + safeJson(data.preview));
});

document.getElementById('run-form').addEventListener('submit', async e => {
  e.preventDefault();
  if(!validationId){ setPanel('run-output','Validate a dataset first.'); return; }
  const mock = document.getElementById('mock-provider').checked;
  setPanel('run-output','Creating run...');
  const seedUsers = document.querySelector('[name="seed_user_ids"]').value;
  const payload = {
    validation_id: validationId,
    mock_provider: mock,
    scenario: {
      post_text: document.getElementById('post-text').value,
      topic_tags: document.getElementById('topic-tags').value,
      media_summary: document.getElementById('media-summary').value,
      platform_mood: document.getElementById('platform-mood').value,
      seed_user_ids: seedUsers,
      horizon: Number(document.getElementById('horizon').value || 4),
      report_language: currentLang,
      report_title: currentLang === 'zh-CN' ? 'LLM-ABM 本地 Web 控制台报告' : 'LLM-ABM Local Web Console Report'
    }
  };
  const res = await fetch('/api/runs', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
  let job = await res.json();
  setPanel('run-output', safeJson(job));
  if(job.run_id && (job.state === 'queued' || job.state === 'running')){
    job = await pollRun(job.run_id);
  }
  if(job.state === 'succeeded'){
    const report = await (await fetch(`/api/runs/${job.run_id}/report-payload`)).json();
    lastReport = report;
    document.getElementById('report-link').href = `/api/runs/${job.run_id}/artifact/report.html`;
    renderReport(report);
  }
});

async function pollRun(runId){
  for(let attempt = 0; attempt < 240; attempt++){
    const job = await (await fetch(`/api/runs/${runId}`)).json();
    setPanel('run-output', safeJson(job));
    if(!['queued','running'].includes(job.state)) return job;
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  throw new Error(`Timed out waiting for run ${runId}`);
}

function renderReport(report){
  document.getElementById('results').classList.remove('hidden');
  const metrics = document.getElementById('metrics');
  metrics.innerHTML = '';
  for(const metric of report.metrics || []){
    const div = document.createElement('div'); div.className='metric';
    div.innerHTML = `<span>${metric.key}</span><strong>${Array.isArray(metric.value)?metric.value.join(', '):JSON.stringify(metric.value).replace(/^"|"$/g,'')}</strong>`;
    metrics.appendChild(div);
  }
  renderTrend(report.trend || []);
  renderNetwork(report.graph_trace || {});
  document.getElementById('dataset-summary').textContent = safeJson(report.dataset_validation || validationPayload || {});
  document.getElementById('provider-summary').textContent = safeJson(report.provider_evidence || report.decision_source_summary || {});
  renderAgentIO(report.graph_trace || {});
  const influencerMetric = report.metrics?.find(m=>m.key==='key_influencers')?.value;
  const influencers = (report.graph_trace?.run?.key_influencers || influencerMetric || report.metrics?.find(m=>m.key==='share_count')?.value || []);
  document.getElementById('influencers').textContent = Array.isArray(influencers) ? (influencers.join(', ') || 'n/a') : String(influencers || 'n/a');
}
function renderTrend(trend){
  const root = document.getElementById('trend'); root.innerHTML='';
  const max = Math.max(1, ...trend.map(s=>Math.max(s.exposed_count||0, s.engaged_count||0)));
  for(const step of trend){
    const row=document.createElement('div'); row.className='bar-row';
    row.innerHTML = `<span>Step ${step.time_step}</span><div><div class="bar-track"><div class="bar" style="width:${((step.exposed_count||0)/max)*100}%"></div></div><div class="bar-track"><div class="bar" style="width:${((step.engaged_count||0)/max)*100}%;background:linear-gradient(90deg,#11845b,#46c2a7)"></div></div></div><span>${step.exposed_count}/${step.engaged_count}</span>`;
    root.appendChild(row);
  }
}
function renderNetwork(trace){
  const slider=document.getElementById('step-slider');
  const maxStep=Math.max(0, ...(trace.steps||[]).map(s=>s.time_step||0));
  slider.max=String(maxStep); slider.oninput=()=>drawNetwork(trace, Number(slider.value));
  drawNetwork(trace, Number(slider.value||0));
}
function drawNetwork(trace, step){
  const root=document.getElementById('network'); root.innerHTML='';
  for(const node of trace.nodes || []){
    const entry=(node.timeline||[]).find(x=>x.time_step===step) || {};
    const div=document.createElement('span'); div.className=`node ${entry.state||'unseen'} ${node.is_seed?'seed':''}`;
    div.textContent=`${node.id}: ${entry.state||'unseen'}`;
    root.appendChild(div);
  }
}
function renderAgentIO(trace){
  const root=document.getElementById('agent-io'); root.innerHTML='';
  const events=[];
  for(const step of trace.steps || []) for(const event of step.decision_events || []) if(event.trace_summary) events.push(event);
  for(const event of events.slice(0,8)){
    const card=document.createElement('div'); card.className='io-card';
    const summary=event.trace_summary;
    card.innerHTML=`<strong>${summary.user_id} · step ${event.time_step}</strong><pre>${safeJson(summary)}</pre>`;
    root.appendChild(card);
  }
}

applyI18n(); refreshReadiness();
