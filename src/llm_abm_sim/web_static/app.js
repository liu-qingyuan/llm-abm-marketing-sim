const I18N = {
  'en-US': {
    eyebrow:'Local single-user SaaS-like console',
    title:'LLM-ABM Marketing Simulator',
    subtitle:'Upload a social graph, validate it, run provider-backed diffusion, and inspect bilingual results locally.',
    providerKicker:'Provider gate',
    providerTitle:'Provider readiness',
    providerHelp:'Product mode requires the live gate and runtime auth check. Mock mode is allowed only for local test/dev runs.',
    mockLabel:'Use mock provider for test/dev',
    mockHelper:'Mock mode is visibly labeled in UI and generated metadata; use it for demos and tests without API auth values.',
    providerCheckingTitle:'Checking provider',
    providerCheckingCopy:'Checking local readiness before a run can start.',
    providerReadyTitle:'Product provider ready',
    providerReadyCopy:'Live provider gate and auth checks passed. Runs can use product provider mode.',
    providerMockTitle:'Mock provider active',
    providerMockCopy:'Test/dev mode is active. Runs use deterministic mock decisions and are labeled as mock evidence.',
    providerBlockedTitle:'Product provider blocked',
    providerBlockedCopy:'Live provider runs are fail-closed until the missing gate or auth setup is fixed. Use mock only for demos/tests.',
    providerReadyReason:'Provider appears ready for product mode.',
    providerMockReason:'Mock provider mode is visibly labeled and private-auth-free.',
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
    validateBusy:'Validating…',
    template:'Download template',
    scenarioKicker:'Campaign scenario',
    runTitle:'2. Scenario and run',
    postText:'Marketing post',
    postHelp:'Describe the message the simulated audience will evaluate. Do not paste private auth values or internal provider request text.',
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
    startRunBusy:'Starting run…',
    startRunPolling:'Waiting for run…',
    resultsKicker:'Executive view',
    resultsTitle:'3. Results dashboard',
    resultsHelp:'Start with the narrative, then inspect metrics, trends, and node-level evidence.',
    openReport:'Open generated report',
    executiveSummaryTitle:'Executive summary',
    executiveWhatHappened:'What happened',
    executiveReach:'Reach',
    executiveEngagement:'Engagement',
    executiveSource:'Decision source',
    executiveNext:'Inspect the trend, timeline, and Agent I/O cards next.',
    metricsTitle:'Key metrics',
    metricsHelp:'Each card explains what the metric means and how to read the value.',
    trendTitle:'Trend chart',
    trendSummary:'Trend summary',
    trendTableSummary:'Show accessible trend table',
    networkTitle:'Network propagation timeline',
    selectedStepLabel:'Selected time step',
    selectedStepSummary:'Step {step}: {exposed} exposed, {engaged} engaged, {newExposed} newly exposed, {newEngaged} newly engaged.',
    selectedStepEmpty:'Step {step}: no recorded exposures or engagements yet.',
    legendExposed:'Exposed',
    legendEngaged:'Engaged',
    legendUnseen:'Unseen',
    legendSeed:'Seed',
    metric_total_agents_label:'Total agents',
    metric_total_agents_desc:'Users represented in the social graph.',
    metric_final_exposed_label:'Final exposed',
    metric_final_exposed_desc:'Unique users reached by the final step.',
    metric_final_engaged_label:'Final engaged',
    metric_final_engaged_desc:'Unique users who engaged by the final step.',
    metric_reach_rate_label:'Reach rate',
    metric_reach_rate_desc:'Final exposed users divided by total agents.',
    metric_engagement_rate_label:'Engagement rate',
    metric_engagement_rate_desc:'Final engaged users divided by final exposed users.',
    metric_diffusion_depth_label:'Diffusion depth',
    metric_diffusion_depth_desc:'Deepest social-hop depth reached by engaged users.',
    metric_spread_speed_label:'Spread speed',
    metric_spread_speed_desc:'Average new exposures per simulation step.',
    metric_like_count_label:'Likes',
    metric_like_count_desc:'Number of like actions observed.',
    metric_comment_count_label:'Comments',
    metric_comment_count_desc:'Number of comment actions observed.',
    metric_share_count_label:'Shares',
    metric_share_count_desc:'Number of share actions observed.',
    metric_key_influencers_label:'Key influencers',
    metric_key_influencers_desc:'Users with the strongest downstream influence signals.',
    trendTableStep:'Step',
    trendTableExposed:'Exposed',
    trendTableEngaged:'Engaged',
    trendTableNewExposed:'New exposed',
    trendTableNewEngaged:'New engaged',
    datasetTitle:'Dataset validation',
    providerEvidence:'Provider evidence',
    providerEvidenceHelp:'Safe summary cards are shown first. Sanitized JSON details are collapsed below.',
    showProviderRaw:'Show sanitized provider JSON',
    providerSourceTitle:'Decision source',
    providerSourceDesc:'Provider-backed decisions versus other decision paths.',
    providerModeTitle:'Mode and readiness',
    providerModeDesc:'Fail-closed product readiness or visibly labeled mock mode.',
    providerConfigTitle:'Provider config',
    providerConfigDesc:'Allowlisted provider, model, wire API, and prompt version only.',
    providerFirstDecisionTitle:'First provider decision',
    providerFirstDecisionDesc:'First sanitized provider-backed action without raw request or response payloads.',
    providerNoEvidence:'No provider evidence was reported for this run.',
    agentIO:'Agent I/O inspector',
    agentIOHelp:'Each decision is summarized first; open details only when sanitized input/output JSON is needed.',
    agentIORawSummary:'Show sanitized Agent I/O JSON',
    agentIOEmpty:'No Agent I/O trace summaries were recorded.',
    agentDecision:'Decision',
    agentInputs:'Inputs',
    agentPeer:'Peer context',
    agentPlatform:'Platform context',
    agentReason:'Reason',
    influencers:'Key influencers'
  },
  'zh-CN': {
    eyebrow:'本地单用户 SaaS 风格控制台',
    title:'LLM-ABM 营销传播模拟器',
    subtitle:'上传社交图数据，完成校验，运行 Provider 驱动的传播模拟，并在本地查看双语结果。',
    providerKicker:'Provider 闸口',
    providerTitle:'Provider 就绪状态',
    providerHelp:'产品模式需要开启 live gate 并通过运行时鉴权检查。Mock 模式仅用于本地测试/演示。',
    mockLabel:'使用测试/开发 Mock Provider',
    mockHelper:'Mock 模式会在 UI 与生成元数据中显式标记；适合无 API 鉴权值的演示与测试。',
    providerCheckingTitle:'正在检查 Provider',
    providerCheckingCopy:'正在检查本地就绪状态，确认运行是否可以开始。',
    providerReadyTitle:'产品 Provider 已就绪',
    providerReadyCopy:'Live gate 与鉴权检查已通过，可以使用产品 Provider 模式运行。',
    providerMockTitle:'Mock Provider 已启用',
    providerMockCopy:'当前为测试/开发模式。运行会使用确定性 Mock 决策，并标记为 Mock 证据。',
    providerBlockedTitle:'产品 Provider 被阻止',
    providerBlockedCopy:'缺少 gate 或鉴权配置时，产品模式会 fail-closed。仅在演示/测试时切换 Mock。',
    providerReadyReason:'Provider 已可用于产品模式。',
    providerMockReason:'Mock Provider 模式已明确标记且不包含私有鉴权值。',
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
    validateBusy:'正在校验…',
    template:'下载模板',
    scenarioKicker:'营销场景',
    runTitle:'2. 场景与运行',
    postText:'营销帖子',
    postHelp:'描述模拟受众要评估的内容。不要粘贴私有鉴权值或内部 Provider 请求文本。',
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
    startRunBusy:'正在启动运行…',
    startRunPolling:'等待运行完成…',
    resultsKicker:'执行视图',
    resultsTitle:'3. 结果仪表盘',
    resultsHelp:'先阅读叙事摘要，再检查指标、趋势和节点级证据。',
    openReport:'打开生成报告',
    executiveSummaryTitle:'执行摘要',
    executiveWhatHappened:'发生了什么',
    executiveReach:'覆盖',
    executiveEngagement:'互动',
    executiveSource:'决策来源',
    executiveNext:'下一步查看趋势、时间线与 Agent 输入/输出卡片。',
    metricsTitle:'核心指标',
    metricsHelp:'每张卡片都会说明指标含义与数值解读方式。',
    trendTitle:'趋势图',
    trendSummary:'趋势摘要',
    trendTableSummary:'显示无障碍趋势表格',
    networkTitle:'网络传播时间线',
    selectedStepLabel:'所选时间步',
    selectedStepSummary:'第 {step} 步：{exposed} 个已曝光，{engaged} 个已互动，{newExposed} 个新增曝光，{newEngaged} 个新增互动。',
    selectedStepEmpty:'第 {step} 步：尚无已记录曝光或互动。',
    legendExposed:'已曝光',
    legendEngaged:'已互动',
    legendUnseen:'未触达',
    legendSeed:'种子用户',
    metric_total_agents_label:'Agent 总数',
    metric_total_agents_desc:'社交图中建模的用户数。',
    metric_final_exposed_label:'最终曝光',
    metric_final_exposed_desc:'最终时间步已触达的唯一用户数。',
    metric_final_engaged_label:'最终互动',
    metric_final_engaged_desc:'最终时间步已发生互动的唯一用户数。',
    metric_reach_rate_label:'覆盖率',
    metric_reach_rate_desc:'最终曝光用户数除以总 Agent 数。',
    metric_engagement_rate_label:'互动率',
    metric_engagement_rate_desc:'最终互动用户数除以最终曝光用户数。',
    metric_diffusion_depth_label:'传播深度',
    metric_diffusion_depth_desc:'已互动用户达到的最深社交跳数。',
    metric_spread_speed_label:'扩散速度',
    metric_spread_speed_desc:'每个时间步平均新增曝光数。',
    metric_like_count_label:'点赞数',
    metric_like_count_desc:'观察到的点赞动作次数。',
    metric_comment_count_label:'评论数',
    metric_comment_count_desc:'观察到的评论动作次数。',
    metric_share_count_label:'转发数',
    metric_share_count_desc:'观察到的转发动作次数。',
    metric_key_influencers_label:'关键影响者',
    metric_key_influencers_desc:'具备最强下游影响信号的用户。',
    trendTableStep:'时间步',
    trendTableExposed:'已曝光',
    trendTableEngaged:'已互动',
    trendTableNewExposed:'新增曝光',
    trendTableNewEngaged:'新增互动',
    datasetTitle:'数据集校验',
    providerEvidence:'Provider 证据',
    providerEvidenceHelp:'优先展示安全摘要卡片；已清洗的 JSON 细节默认折叠在下方。',
    showProviderRaw:'显示已清洗 Provider JSON',
    providerSourceTitle:'决策来源',
    providerSourceDesc:'Provider 驱动决策与其他决策路径的数量。',
    providerModeTitle:'模式与就绪',
    providerModeDesc:'产品模式 fail-closed 状态，或明确标记的 Mock 模式。',
    providerConfigTitle:'Provider 配置',
    providerConfigDesc:'仅展示白名单中的 provider、模型、wire API 与 prompt 版本。',
    providerFirstDecisionTitle:'首个 Provider 决策',
    providerFirstDecisionDesc:'首个已清洗的 Provider 动作，不包含原始请求或响应载荷。',
    providerNoEvidence:'本次运行未报告 Provider 证据。',
    agentIO:'Agent 输入/输出检查器',
    agentIOHelp:'每个决策先展示摘要；需要时再展开已清洗的输入/输出 JSON。',
    agentIORawSummary:'显示已清洗 Agent 输入/输出 JSON',
    agentIOEmpty:'未记录 Agent 输入/输出追踪摘要。',
    agentDecision:'决策',
    agentInputs:'输入',
    agentPeer:'同伴语境',
    agentPlatform:'平台语境',
    agentReason:'理由',
    influencers:'关键影响者'
  }
};
let currentLang = 'en-US';
let validationId = null;
let validationPayload = null;
let lastReport = null;
let lastReadiness = null;
let isValidating = false;
let isRunning = false;
let runBusyKey = 'startRunBusy';

function t(key){ return (I18N[currentLang]||I18N['en-US'])[key] || key; }
function applyI18n(){
  document.documentElement.lang=currentLang;
  document.querySelectorAll('[data-i18n]').forEach(el=>{el.textContent=t(el.dataset.i18n)});
  if(lastReadiness) renderReadiness(lastReadiness);
  updateRunPrereqStatus();
  updateActionStates();
  if(lastReport) renderReport(lastReport);
}
function announce(text){ document.getElementById('live-status').textContent = text; }
function setPanel(id, text){ document.getElementById(id).textContent = text; if(text) announce(text.split('\n')[0]); }
function sanitizeForUi(value){
  const forbidden = ['authorization','bearer','cookie','credential','header','password','raw_auth','raw_prompt','raw_provider','request_payload','response_payload','secret','token','access_token'];
  const redactString = text => {
    const source = String(text ?? '');
    const lowered = source.toLowerCase();
    if(forbidden.some(fragment => lowered.includes(fragment))) return '[redacted]';
    if(/sk-[A-Za-z0-9_-]+/.test(source)) return '[redacted]';
    if(/Bearer\s+\S+/i.test(source)) return '[redacted]';
    return source;
  };
  const visit = item => {
    if(Array.isArray(item)) return item.map(visit);
    if(item && typeof item === 'object'){
      const kept = {};
      for(const [key, child] of Object.entries(item)){
        const lowered = key.toLowerCase();
        if(forbidden.some(fragment => lowered.includes(fragment))) continue;
        kept[key] = visit(child);
      }
      return kept;
    }
    if(typeof item === 'string') return redactString(item);
    return item;
  };
  return visit(value);
}
function safeJson(value){ return JSON.stringify(sanitizeForUi(value), null, 2); }
function escapeHtml(value){
  return String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[char]));
}
function formatTemplate(template, values){
  return template.replace(/\{(\w+)\}/g, (_, key) => values[key] ?? '');
}
function formatValue(value){
  const safeValue = sanitizeForUi(value);
  if(Array.isArray(safeValue)) return safeValue.join(', ') || 'n/a';
  if(safeValue && typeof safeValue === 'object') return JSON.stringify(safeValue);
  if(typeof safeValue === 'number' && !Number.isInteger(safeValue)) return String(Math.round(safeValue * 1000) / 1000);
  return String(safeValue ?? 'n/a');
}
function metricLabel(key){ return t(`metric_${key}_label`) || key.replace(/_/g, ' '); }
function metricDescription(key){ return t(`metric_${key}_desc`) || ''; }
function metricValue(report, key, fallback = 0){
  const metric = (report.metrics || []).find(item => item.key === key);
  return metric ? metric.value : fallback;
}
function setButtonState(button, { disabled, busy, labelKey }){
  if(!button) return;
  button.disabled = disabled;
  button.setAttribute('aria-busy', busy ? 'true' : 'false');
  button.classList.toggle('is-loading', Boolean(busy));
  button.textContent = t(labelKey);
}
function updateActionStates(){
  setButtonState(document.getElementById('validate-button'), {
    disabled: isValidating,
    busy: isValidating,
    labelKey: isValidating ? 'validateBusy' : 'validate'
  });
  setButtonState(document.getElementById('run-button'), {
    disabled: !validationId || isRunning,
    busy: isRunning,
    labelKey: isRunning ? runBusyKey : 'startRun'
  });
}

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
  if(isValidating) return;
  validationId = null;
  validationPayload = null;
  isValidating = true;
  updateRunPrereqStatus();
  updateActionStates();
  setPanel('validation-output', t('validationWorking'));
  try {
    const res = await fetch('/api/datasets/validate', { method:'POST', body: fd });
    const data = await res.json();
    if(!res.ok || !data.valid){
      setPanel('validation-output', `${t('validationFailed')}\n${safeJson(data.error || data)}`);
      return;
    }
    validationId = data.validation_id;
    validationPayload = data.dataset_validation;
    setPanel('validation-output', `${t('validationReady')} validation_id=${validationId}\nprofiles=${data.preview.profile_count} edges=${data.preview.edge_count}\n` + safeJson(data.preview));
  } catch (error) {
    setPanel('validation-output', `${t('validationFailed')}\n${error.message || String(error)}`);
  } finally {
    isValidating = false;
    updateRunPrereqStatus();
    updateActionStates();
  }
});

document.getElementById('run-form').addEventListener('submit', async e => {
  e.preventDefault();
  if(isRunning) return;
  if(!validationId){ setPanel('run-output', t('validationFirst')); updateRunPrereqStatus(); updateActionStates(); return; }
  const mock = document.getElementById('mock-provider').checked;
  isRunning = true;
  runBusyKey = 'startRunBusy';
  updateActionStates();
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
  try {
    const res = await fetch('/api/runs', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
    let job = await res.json();
    setPanel('run-output', formatRunStatus(job));
    if(job.run_id && (job.state === 'queued' || job.state === 'running')){
      runBusyKey = 'startRunPolling';
      updateActionStates();
      job = await pollRun(job.run_id);
    }
    if(job.state === 'blocked' || job.state === 'failed') setPanel('run-output', formatRunStatus(job));
    if(job.state === 'succeeded'){
      const report = await (await fetch(`/api/runs/${job.run_id}/report-payload`)).json();
      lastReport = report;
      document.getElementById('report-link').href = `/api/runs/${job.run_id}/artifact/report.html`;
      renderReport(report);
    }
  } catch (error) {
    setPanel('run-output', `${t('runFailed')}
${error.message || String(error)}`);
  } finally {
    isRunning = false;
    runBusyKey = 'startRunBusy';
    updateActionStates();
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
  renderExecutiveSummary(report);
  renderMetrics(report.metrics || []);
  renderTrend(report.trend || []);
  renderNetwork(report.graph_trace || {});
  document.getElementById('dataset-summary').textContent = safeJson(report.dataset_validation || validationPayload || {});
  renderProviderEvidence(report.provider_evidence || { decision_source_summary: report.decision_source_summary || {} });
  renderAgentIO(report.graph_trace || {});
  const influencerMetric = report.metrics?.find(m=>m.key==='key_influencers')?.value;
  const influencers = (report.graph_trace?.run?.key_influencers || influencerMetric || report.metrics?.find(m=>m.key==='share_count')?.value || []);
  document.getElementById('influencers').textContent = Array.isArray(influencers) ? (influencers.join(', ') || 'n/a') : String(influencers || 'n/a');
}

function renderExecutiveSummary(report){
  const narrative = currentLang === 'zh-CN' ? report.narrative?.summary_zh : report.narrative?.summary_en;
  const totalAgents = metricValue(report, 'total_agents');
  const finalExposed = metricValue(report, 'final_exposed');
  const finalEngaged = metricValue(report, 'final_engaged');
  const shareCount = metricValue(report, 'share_count');
  const reachRate = metricValue(report, 'reach_rate');
  const engagementRate = metricValue(report, 'engagement_rate');
  const source = report.inputs?.decision_mode || Object.entries(report.decision_source_summary || {}).map(([k,v]) => `${k}=${v}`).join(', ') || 'n/a';
  const fallback = currentLang === 'zh-CN'
    ? `本次模拟覆盖 ${finalExposed}/${totalAgents} 个用户，${finalEngaged} 个用户发生互动，转发数 ${shareCount}。`
    : `This run reached ${finalExposed}/${totalAgents} users, with ${finalEngaged} engaged users and ${shareCount} shares.`;
  const summary = document.getElementById('executive-summary');
  summary.textContent = narrative || fallback;
  const highlights = document.getElementById('executive-highlights');
  highlights.innerHTML = '';
  [
    [t('executiveReach'), `${finalExposed}/${totalAgents} · ${metricLabel('reach_rate')} ${formatValue(reachRate)}`],
    [t('executiveEngagement'), `${finalEngaged} · ${metricLabel('engagement_rate')} ${formatValue(engagementRate)} · ${metricLabel('share_count')} ${formatValue(shareCount)}`],
    [t('executiveSource'), `${source}`],
    [t('executiveWhatHappened'), t('executiveNext')]
  ].forEach(([label, value]) => {
    const item = document.createElement('li');
    item.innerHTML = `<span>${label}</span><strong>${value}</strong>`;
    highlights.appendChild(item);
  });
}

function renderMetrics(metricList){
  const metrics = document.getElementById('metrics');
  metrics.innerHTML = '';
  for(const metric of metricList){
    const div = document.createElement('article');
    div.className = 'metric';
    div.setAttribute('aria-label', `${metricLabel(metric.key)}: ${formatValue(metric.value)}. ${metricDescription(metric.key)}`);
    div.innerHTML = `<span class="sr-only">${metric.key}</span><span>${metricLabel(metric.key)}</span><strong>${formatValue(metric.value)}</strong><p>${metricDescription(metric.key)}</p>`;
    metrics.appendChild(div);
  }
}

function renderTrend(trend){
  const root = document.getElementById('trend'); root.innerHTML='';
  const summary = document.getElementById('trend-summary');
  const max = Math.max(1, ...trend.map(s=>Math.max(s.exposed_count||0, s.engaged_count||0)));
  const finalStep = trend[trend.length - 1] || {};
  const peakNewEngaged = trend.reduce((best, step) => (step.new_engaged_count || 0) > (best.new_engaged_count || 0) ? step : best, {});
  summary.textContent = currentLang === 'zh-CN'
    ? `${t('trendSummary')}：最终第 ${finalStep.time_step ?? 0} 步有 ${finalStep.exposed_count ?? 0} 个曝光、${finalStep.engaged_count ?? 0} 个互动；新增互动峰值在第 ${peakNewEngaged.time_step ?? 0} 步。`
    : `${t('trendSummary')}: final step ${finalStep.time_step ?? 0} has ${finalStep.exposed_count ?? 0} exposed and ${finalStep.engaged_count ?? 0} engaged; peak new engagement occurs at step ${peakNewEngaged.time_step ?? 0}.`;
  root.setAttribute('aria-label', summary.textContent);
  for(const step of trend){
    const row=document.createElement('div'); row.className='bar-row';
    const label = currentLang === 'zh-CN' ? `第 ${step.time_step} 步` : `Step ${step.time_step}`;
    row.innerHTML = `<span>${label}</span><div><div class="bar-track" aria-label="${t('legendExposed')} ${step.exposed_count||0}"><div class="bar" style="width:${((step.exposed_count||0)/max)*100}%"></div></div><div class="bar-track" aria-label="${t('legendEngaged')} ${step.engaged_count||0}"><div class="bar engaged" style="width:${((step.engaged_count||0)/max)*100}%"></div></div></div><span>${step.exposed_count}/${step.engaged_count}</span>`;
    root.appendChild(row);
  }
  renderTrendTable(trend);
}

function renderTrendTable(trend){
  const root = document.getElementById('trend-table');
  const rows = trend.map(step => `<tr><td>${step.time_step}</td><td>${step.exposed_count||0}</td><td>${step.engaged_count||0}</td><td>${step.new_exposed_count||0}</td><td>${step.new_engaged_count||0}</td></tr>`).join('');
  root.innerHTML = `<table><thead><tr><th>${t('trendTableStep')}</th><th>${t('trendTableExposed')}</th><th>${t('trendTableEngaged')}</th><th>${t('trendTableNewExposed')}</th><th>${t('trendTableNewEngaged')}</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function renderNetwork(trace){
  const slider=document.getElementById('step-slider');
  const maxStep=Math.max(0, ...(trace.steps||[]).map(s=>s.time_step||0));
  slider.max=String(maxStep);
  if(Number(slider.value) > maxStep) slider.value = String(maxStep);
  slider.oninput=()=>drawNetwork(trace, Number(slider.value));
  drawNetwork(trace, Number(slider.value||0));
}
function drawNetwork(trace, step){
  const root=document.getElementById('network'); root.innerHTML='';
  const stepRecord = (trace.steps || []).find(s => (s.time_step || 0) === step) || {};
  const summaryText = ((stepRecord.exposed_count || 0) || (stepRecord.engaged_count || 0))
    ? formatTemplate(t('selectedStepSummary'), {
        step,
        exposed: stepRecord.exposed_count || 0,
        engaged: stepRecord.engaged_count || 0,
        newExposed: stepRecord.new_exposed_count || 0,
        newEngaged: stepRecord.new_engaged_count || 0
      })
    : formatTemplate(t('selectedStepEmpty'), { step });
  document.getElementById('selected-step-summary').textContent = summaryText;
  root.setAttribute('aria-label', summaryText);
  for(const node of trace.nodes || []){
    const entry=(node.timeline||[]).find(x=>x.time_step===step) || {};
    const state = entry.state || 'unseen';
    const div=document.createElement('span'); div.className=`node ${state} ${node.is_seed?'seed':''}`;
    div.textContent=`${node.id}: ${state}${node.is_seed ? ' · seed' : ''}`;
    div.setAttribute('aria-label', `${node.id}: ${state}${node.is_seed ? ', seed user' : ''}`);
    root.appendChild(div);
  }
}
function renderProviderEvidence(evidence){
  const safeEvidence = sanitizeForUi(evidence || {});
  const root = document.getElementById('provider-summary');
  const raw = document.getElementById('provider-raw');
  root.innerHTML = '';
  if(raw) raw.textContent = safeJson(safeEvidence);
  if(!safeEvidence || Object.keys(safeEvidence).length === 0){
    const empty = document.createElement('p');
    empty.className = 'helper-text';
    empty.textContent = t('providerNoEvidence');
    root.appendChild(empty);
    return;
  }
  const sourceSummary = safeEvidence.decision_source_summary || {};
  const readiness = safeEvidence.provider_readiness || {};
  const configured = readiness.provider?.configured || readiness.configured || safeEvidence.provider_metadata || {};
  const firstDecision = safeEvidence.first_provider_decision || {};
  const cards = [
    {
      title: t('providerSourceTitle'),
      value: Object.entries(sourceSummary).map(([key, value]) => `${key}: ${value}`).join(' · ') || `${t('executiveSource')}: n/a`,
      desc: t('providerSourceDesc'),
      meta: [`provider decisions: ${safeEvidence.provider_decision_count ?? sourceSummary.provider ?? 0}`]
    },
    {
      title: t('providerModeTitle'),
      value: readiness.label || readiness.state || configured.provider || 'n/a',
      desc: t('providerModeDesc'),
      meta: [readiness.mock ? 'mock / test-dev' : (readiness.state || 'product'), ...(readiness.reasons || []).slice(0,2)]
    },
    {
      title: t('providerConfigTitle'),
      value: [configured.provider || safeEvidence.provider_metadata?.provider, configured.model || safeEvidence.provider_metadata?.model].filter(Boolean).join(' · ') || 'n/a',
      desc: t('providerConfigDesc'),
      meta: [configured.wire_api || safeEvidence.provider_metadata?.wire_api, configured.prompt_version || safeEvidence.provider_metadata?.prompt_version].filter(Boolean)
    },
    {
      title: t('providerFirstDecisionTitle'),
      value: firstDecision.user_id ? `${firstDecision.user_id} · ${firstDecision.action || 'decision'} · p=${formatValue(firstDecision.probability)}` : 'n/a',
      desc: t('providerFirstDecisionDesc'),
      meta: [firstDecision.reason, firstDecision.confidence !== undefined ? `confidence ${formatValue(firstDecision.confidence)}` : ''].filter(Boolean)
    }
  ];
  for(const card of cards){
    const article = document.createElement('article');
    article.className = 'evidence-card';
    const meta = card.meta.length ? `<ul>${card.meta.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul>` : '';
    article.innerHTML = `<span>${escapeHtml(card.title)}</span><strong>${escapeHtml(card.value)}</strong><p>${escapeHtml(card.desc)}</p>${meta}`;
    root.appendChild(article);
  }
}

function renderAgentIO(trace){
  const root=document.getElementById('agent-io'); root.innerHTML='';
  const events=[];
  for(const step of trace.steps || []) for(const event of step.decision_events || []) if(event.trace_summary) events.push(event);
  if(!events.length){
    const empty = document.createElement('p');
    empty.className = 'helper-text';
    empty.textContent = t('agentIOEmpty');
    root.appendChild(empty);
    return;
  }
  for(const event of events.slice(0,8)){
    const card=document.createElement('article'); card.className='io-card';
    const summary=sanitizeForUi(event.trace_summary);
    const input = summary.input || {};
    const output = summary.output || {};
    const postTags = input.post?.topic_tags || [];
    const visiblePeers = input.peer_context?.visible_engaged_neighbors ?? input.peer_context?.visible_neighbor_count ?? 0;
    const stateLabel = output.engage ? 'engaged' : 'ignored';
    card.innerHTML=`
      <div class="io-summary">
        <div>
          <strong>${escapeHtml(summary.user_id || 'agent')} · step ${escapeHtml(event.time_step)}</strong>
          <p>${escapeHtml(t('agentDecision'))}: ${escapeHtml(output.action || 'n/a')} · p=${escapeHtml(formatValue(output.probability))} · confidence=${escapeHtml(formatValue(output.confidence))}</p>
        </div>
        <span class="pill ${output.engage ? 'good' : 'bad'}">${escapeHtml(stateLabel)}</span>
      </div>
      <dl class="io-facts">
        <div><dt>${escapeHtml(t('agentInputs'))}</dt><dd>${escapeHtml((postTags || []).join(', ') || 'n/a')}</dd></div>
        <div><dt>${escapeHtml(t('agentPeer'))}</dt><dd>${escapeHtml(visiblePeers)} · ratio ${escapeHtml(formatValue(input.peer_context?.engagement_ratio))}</dd></div>
        <div><dt>${escapeHtml(t('agentPlatform'))}</dt><dd>${escapeHtml(input.platform_context?.platform_name || input.platform_context?.platform || 'n/a')}</dd></div>
        <div><dt>${escapeHtml(t('agentReason'))}</dt><dd>${escapeHtml(output.reason || 'n/a')}</dd></div>
      </dl>
      <details class="raw-disclosure">
        <summary>${escapeHtml(t('agentIORawSummary'))}</summary>
        <pre>${escapeHtml(safeJson(summary))}</pre>
      </details>`;
    root.appendChild(card);
  }
}


applyI18n();
updateActionStates();
refreshReadiness();
