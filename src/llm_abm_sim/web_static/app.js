const I18N = {
  'en-US': {
    eyebrow:'Local single-user SaaS-like console',
    title:'LLM-ABM Marketing Simulator',
    subtitle:'Upload a social graph, validate it, run provider-backed diffusion, and inspect bilingual results locally.',
    providerKicker:'Provider gate',
    providerTitle:'Provider readiness',
    providerHelp:'Product mode requires the live gate and runtime credential. Mock mode is allowed only for local test/dev runs.',
    mockLabel:'Use mock provider for test/dev',
    mockHelper:'Mock mode is visibly labeled in UI and generated metadata; use it for demos and tests without API credentials.',
    providerCheckingTitle:'Checking provider',
    providerCheckingCopy:'Checking local readiness before a run can start.',
    providerReadyTitle:'Product provider ready',
    providerReadyCopy:'Live provider gate and credential checks passed. Runs can use product provider mode.',
    providerMockTitle:'Mock provider active',
    providerMockCopy:'Test/dev mode is active. Runs use deterministic mock decisions and are labeled as mock evidence.',
    providerBlockedTitle:'Product provider blocked',
    providerBlockedCopy:'Live provider runs are fail-closed until the missing gate or credential is fixed. Use mock only for demos/tests.',
    providerReadyReason:'Provider appears ready for product mode.',
    providerMockReason:'Mock provider mode is visibly labeled and secret-free.',
    stepData:'Data',
    stepDataHelp:'Upload and validate inputs',
    stepScenario:'Scenario',
    stepScenarioHelp:'Define campaign context',
    stepRun:'Run',
    stepRunHelp:'Create provider-gated simulation',
    stepResults:'Results',
    stepResultsHelp:'Review dashboard evidence',
    dataKicker:'Data source',
    dataTitle:'1. Dataset validation',
    dataHelp:'Upload users and edges as CSV or JSON. Edge JSON accepts either {edges:[...]} or a bare list.',
    usersFile:'Users CSV/JSON',
    usersHelp:'Required fields: user_id plus optional interest_tags, brand_attitude, activity_level. Sensitive columns are filtered from UI summaries.',
    edgesFile:'Edges CSV/JSON',
    edgesHelp:'Edges need source and target IDs that exist in the users file; weight and relationship are optional.',
    seedUsers:'Seed users',
    seedHelp:'Comma-separated user IDs that receive the initial campaign exposure. Validate again if you change files.',
    validate:'Validate dataset',
    template:'Download template',
    scenarioKicker:'Campaign scenario',
    runTitle:'2. Scenario and run',
    postText:'Marketing post',
    postHelp:'Describe the message the simulated audience will evaluate. Do not paste secrets or private provider prompts.',
    topics:'Topic tags',
    topicsHelp:'Comma-separated tags help deterministic and provider decisions compare content with user preferences.',
    mediaSummary:'Media summary',
    mediaHelp:'Short safe summary of attached creative; generated artifacts store summaries, not raw assets.',
    platformMood:'Platform context',
    platformHelp:'Capture launch context, trend mood, or campaign constraints that influence engagement.',
    horizon:'Horizon',
    horizonHelp:'Number of propagation steps to simulate. Keep small for fast local review; allowed range is 1–30.',
    runPrereq:'Validate a dataset first, then choose product or mock provider mode before starting a run.',
    validationWorking:'Validating dataset…',
    validationFailed:'Validation failed. Fix the files and try again.',
    validationReady:'Dataset validated. You can start a run.',
    validationFirst:'Validate a dataset first.',
    runCreating:'Creating run…',
    runBlocked:'Run blocked by provider readiness. Fix product provider setup or switch to mock test/dev mode.',
    runFailed:'Run failed. Review the safe error summary and retry after fixing inputs.',
    runSucceeded:'Run succeeded. Results dashboard is ready.',
    runPolling:'Run is still processing…',
    startRun:'Start run',
    resultsTitle:'3. Results dashboard',
    openReport:'Open generated report',
    trendTitle:'Trend chart',
    networkTitle:'Network propagation timeline',
    datasetTitle:'Dataset validation',
    providerEvidence:'Provider evidence',
    agentIO:'Agent I/O inspector',
    influencers:'Key influencers'
  },
  'zh-CN': {
    eyebrow:'本地单用户 SaaS 风格控制台',
    title:'LLM-ABM 营销传播模拟器',
    subtitle:'上传社交图数据，完成校验，运行 Provider 驱动的传播模拟，并在本地查看双语结果。',
    providerKicker:'Provider 闸口',
    providerTitle:'Provider 就绪状态',
    providerHelp:'产品模式需要开启 live gate 并具备运行时凭证。Mock 模式仅用于本地测试/演示。',
    mockLabel:'使用测试/开发 Mock Provider',
    mockHelper:'Mock 模式会在 UI 与生成元数据中显式标记；适合无 API 凭证的演示与测试。',
    providerCheckingTitle:'正在检查 Provider',
    providerCheckingCopy:'正在检查本地就绪状态，确认运行是否可以开始。',
    providerReadyTitle:'产品 Provider 已就绪',
    providerReadyCopy:'Live gate 与凭证检查已通过，可以使用产品 Provider 模式运行。',
    providerMockTitle:'Mock Provider 已启用',
    providerMockCopy:'当前为测试/开发模式。运行会使用确定性 Mock 决策，并标记为 Mock 证据。',
    providerBlockedTitle:'产品 Provider 被阻止',
    providerBlockedCopy:'缺少 gate 或凭证时，产品模式会 fail-closed。仅在演示/测试时切换 Mock。',
    providerReadyReason:'Provider 已可用于产品模式。',
    providerMockReason:'Mock Provider 模式已明确标记且不包含密钥。',
    stepData:'数据',
    stepDataHelp:'上传并校验输入',
    stepScenario:'场景',
    stepScenarioHelp:'定义营销语境',
    stepRun:'运行',
    stepRunHelp:'创建 Provider 闸口仿真',
    stepResults:'结果',
    stepResultsHelp:'查看仪表盘证据',
    dataKicker:'数据源',
    dataTitle:'1. 数据集校验',
    dataHelp:'上传 CSV 或 JSON 用户与边数据。边 JSON 支持 {edges:[...]} 或裸数组。',
    usersFile:'用户 CSV/JSON',
    usersHelp:'必需字段：user_id；可选 interest_tags、brand_attitude、activity_level。敏感列会从 UI 摘要中过滤。',
    edgesFile:'关系边 CSV/JSON',
    edgesHelp:'边数据需要 source 与 target，且必须存在于用户文件中；weight 与 relationship 可选。',
    seedUsers:'种子用户',
    seedHelp:'用英文逗号分隔初始曝光用户 ID。更换文件后请重新校验。',
    validate:'校验数据集',
    template:'下载模板',
    scenarioKicker:'营销场景',
    runTitle:'2. 场景与运行',
    postText:'营销帖子',
    postHelp:'描述模拟受众要评估的内容。不要粘贴密钥或私有 Provider prompt。',
    topics:'话题标签',
    topicsHelp:'用英文逗号分隔标签，帮助决策逻辑匹配内容与用户偏好。',
    mediaSummary:'素材摘要',
    mediaHelp:'填写安全的创意素材摘要；生成物保存摘要，不保存原始素材。',
    platformMood:'平台语境',
    platformHelp:'记录发布时间、趋势氛围或会影响互动的活动约束。',
    horizon:'仿真步数',
    horizonHelp:'传播模拟的步数。为了本地快速查看建议保持较小；允许范围 1–30。',
    runPrereq:'先校验数据集，再选择产品或 Mock Provider 模式并开始运行。',
    validationWorking:'正在校验数据集…',
    validationFailed:'数据集校验失败。修正文件后重试。',
    validationReady:'数据集已校验，可以开始运行。',
    validationFirst:'请先校验数据集。',
    runCreating:'正在创建运行…',
    runBlocked:'运行被 Provider 就绪状态阻止。请修复产品 Provider 设置，或切换 Mock 测试/演示模式。',
    runFailed:'运行失败。请查看安全错误摘要，修复输入后重试。',
    runSucceeded:'运行成功。结果仪表盘已就绪。',
    runPolling:'运行仍在处理中…',
    startRun:'开始运行',
    resultsTitle:'3. 结果仪表盘',
    openReport:'打开生成报告',
    trendTitle:'趋势图',
    networkTitle:'网络传播时间线',
    datasetTitle:'数据集校验',
    providerEvidence:'Provider 证据',
    agentIO:'Agent 输入/输出检查器',
    influencers:'关键影响者'
  }
};
let currentLang = 'en-US';
let validationId = null;
let validationPayload = null;
let lastReport = null;
let lastReadiness = null;

function t(key){ return (I18N[currentLang]||I18N['en-US'])[key] || key; }
function applyI18n(){
  document.documentElement.lang=currentLang;
  document.querySelectorAll('[data-i18n]').forEach(el=>{el.textContent=t(el.dataset.i18n)});
  if(lastReadiness) renderReadiness(lastReadiness);
  updateRunPrereqStatus();
  if(lastReport) renderReport(lastReport);
}
function announce(text){ document.getElementById('live-status').textContent = text; }
function setPanel(id, text){ document.getElementById(id).textContent = text; if(text) announce(text.split('\n')[0]); }
function safeJson(value){ return JSON.stringify(value, null, 2); }

async function refreshReadiness(){
  const mock = document.getElementById('mock-provider').checked;
  const res = await fetch(`/api/provider/readiness?mock_provider=${mock ? 'true':'false'}`);
  const data = await res.json();
  lastReadiness = data;
  renderReadiness(data);
}

function renderReadiness(data){
  const state = document.getElementById('provider-state');
  const modeCard = document.getElementById('provider-mode-card');
  const modeTitle = document.getElementById('provider-mode-title');
  const modeCopy = document.getElementById('provider-mode-copy');
  state.textContent = data.state + (data.mock ? ' / MOCK' : '');
  const isReady = data.state === 'ready';
  const isMock = data.state === 'mock' || data.mock;
  const stateClass = isMock ? 'warn' : (isReady ? 'good' : 'bad');
  state.className = 'pill ' + stateClass;
  modeCard.className = `mode-card ${stateClass}`;
  if(isMock){
    modeTitle.textContent = t('providerMockTitle');
    modeCopy.textContent = t('providerMockCopy');
  } else if(isReady){
    modeTitle.textContent = t('providerReadyTitle');
    modeCopy.textContent = t('providerReadyCopy');
  } else {
    modeTitle.textContent = t('providerBlockedTitle');
    modeCopy.textContent = t('providerBlockedCopy');
  }
  document.getElementById('provider-reasons').textContent = (data.reasons || []).join('; ') || (isMock ? t('providerMockReason') : t('providerReadyReason'));
  updateRunPrereqStatus();
  announce(`${modeTitle.textContent}. ${document.getElementById('provider-reasons').textContent}`);
}

function updateRunPrereqStatus(){
  const status = document.getElementById('run-prereq-status');
  if(!status) return;
  const pieces = [];
  pieces.push(validationId ? t('validationReady') : t('validationFirst'));
  if(lastReadiness){
    if(lastReadiness.state === 'blocked') pieces.push(t('providerBlockedCopy'));
    else if(lastReadiness.mock) pieces.push(t('providerMockCopy'));
    else pieces.push(t('providerReadyCopy'));
  }
  status.textContent = pieces.join(' ');
}

document.getElementById('language').addEventListener('change', e => { currentLang = e.target.value; applyI18n(); });
document.getElementById('mock-provider').addEventListener('change', refreshReadiness);

document.getElementById('dataset-form').addEventListener('submit', async e => {
  e.preventDefault();
  const form = e.currentTarget;
  const fd = new FormData(form);
  validationId = null;
  validationPayload = null;
  updateRunPrereqStatus();
  setPanel('validation-output', t('validationWorking'));
  const res = await fetch('/api/datasets/validate', { method:'POST', body: fd });
  const data = await res.json();
  if(!res.ok || !data.valid){
    setPanel('validation-output', `${t('validationFailed')}\n${safeJson(data.error || data)}`);
    updateRunPrereqStatus();
    return;
  }
  validationId = data.validation_id;
  validationPayload = data.dataset_validation;
  setPanel('validation-output', `${t('validationReady')} validation_id=${validationId}\nprofiles=${data.preview.profile_count} edges=${data.preview.edge_count}\n` + safeJson(data.preview));
  updateRunPrereqStatus();
});

document.getElementById('run-form').addEventListener('submit', async e => {
  e.preventDefault();
  if(!validationId){ setPanel('run-output', t('validationFirst')); updateRunPrereqStatus(); return; }
  const mock = document.getElementById('mock-provider').checked;
  setPanel('run-output', t('runCreating'));
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
  setPanel('run-output', formatRunStatus(job));
  if(job.run_id && (job.state === 'queued' || job.state === 'running')){
    job = await pollRun(job.run_id);
  }
  if(job.state === 'blocked' || job.state === 'failed') setPanel('run-output', formatRunStatus(job));
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
    setPanel('run-output', formatRunStatus(job));
    if(!['queued','running'].includes(job.state)) return job;
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  throw new Error(`Timed out waiting for run ${runId}`);
}

function formatRunStatus(job){
  let prefix = '';
  if(job.state === 'blocked') prefix = `${t('runBlocked')}\n`;
  else if(job.state === 'failed') prefix = `${t('runFailed')}\n`;
  else if(job.state === 'succeeded') prefix = `${t('runSucceeded')}\n`;
  else if(job.state === 'queued' || job.state === 'running') prefix = `${t('runPolling')}\n`;
  return prefix + safeJson(job);
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
