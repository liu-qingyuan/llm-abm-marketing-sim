# 产品演示说明：90% 本地原型

这个里程碑把仿真器整理成一个可以本地评审的产品原型：非开发者也可以检查输入、运行确定性 demo、打开双语报告，并理解每个决策来自离线规则基线还是显式 Provider 路径。

## Demo 1：默认离线运行

```bash
. .venv/bin/activate
python -m llm_abm_sim.run --config configs/default.yaml --output runs/sample
```

打开：

- `runs/sample/report.html`：带语言切换的双语报告。
- `runs/sample/input-builder.html`：静态双语配置构建器/模板。
- `runs/sample/graph_trace.json`：安全的传播图与 Agent 决策追踪。
- `runs/sample/report_payload.json`：报告 HTML 使用的安全 view-model。

预期行为：

1. 报告无需服务器、无需网络即可打开。
2. 语言选择器可在英文和中文之间切换。
3. “如何阅读本仿真”解释 ABM 视角。
4. “使用的输入”展示帖子、种子用户、平台上下文、图/画像规模和决策模式。
5. 交互追踪可按时间步/节点查看 Agent 输入输出。
6. 未启用 Provider 时，Provider 证据显示离线规则基线。

## Demo 2：真实感营销数据样例

```bash
. .venv/bin/activate
python -m llm_abm_sim.run \
  --config configs/fixtures/realistic_marketing_dataset.yaml \
  --output runs/realistic-sample
```

打开：

- `runs/realistic-sample/report.html`
- `runs/realistic-sample/dataset_validation.json`

预期行为：

- 数据集校验报告展示用户画像、边数量和校验策略状态。
- 报告叙述解释 reach、engagement、decision source 等指标。
- 图追踪能展示每个用户的安全决策输入摘要，不暴露秘密。

## Demo 3：静态输入构建器

每次运行都会在输出目录写入 `input-builder.html`。它基于 `SimulationInput` 生成默认 YAML，不维护重复手写的 JavaScript 配置。

推荐流程：

1. 打开 `runs/sample/input-builder.html`。
2. 切换构建器语言。
3. 编辑或复制生成的 YAML。
4. 保存为 `builder-config.yaml`。
5. 运行：

```bash
python -m llm_abm_sim.run --config builder-config.yaml --output runs/builder-demo
```

支持字段包括 run ID、随机种子、帖子文本/素材/话题、平台上下文、仿真 horizon、种子用户、内联画像/边、Provider 模式和报告语言。

## Demo 4：本地 Web 控制台

安装完整本地栈后启动：

```bash
. .venv/bin/activate
python -m pip install -e ".[dev,web,llm]"
npm ci
npx playwright install chromium
python -m llm_abm_sim.web --host 127.0.0.1 --port 8000 --artifact-root runs/web
# 或：llm-abm-web --host 127.0.0.1 --port 8000 --artifact-root runs/web
```

打开：`http://127.0.0.1:8000`

Web 控制台按浏览器任务组织为：

1. **Hero 与 Provider 状态条**：说明本地评审目的，显示 Provider readiness，并把 mock 模式明确标为 test/dev。
2. **分步流程**：Data -> Scenario -> Run -> Results。
3. **数据与场景卡片**：上传用户/边文件，设置种子用户、营销帖子、话题、素材摘要、平台上下文和 horizon。
4. **结果仪表盘**：先给执行摘要和指标解释，再显示趋势条、网络时间线、数据诊断、Provider 证据、Agent I/O 和关键影响者。
5. **渐进披露**：先展示安全摘要卡片，需要时再展开 sanitized JSON；不暴露原始 Provider prompt/response。

稳定本地 API：

```text
GET  /api/health
POST /api/datasets/validate
GET  /api/provider/readiness
POST /api/runs
GET  /api/runs/{run_id}
GET  /api/runs/{run_id}/report-payload
GET  /api/runs/{run_id}/artifact/{name}
```

上传支持 users CSV/JSON 和 edges CSV/JSON。模板位于 `configs/templates/`，也可从 `/api/templates/users.csv`、`/api/templates/edges.csv`、`/api/templates/users.json`、`/api/templates/edges.json` 获取。

## Provider-backed 手动冒烟

默认测试和 demo 都保持离线。真实 Provider 运行必须手动显式开启：

```bash
LLM_ABM_RUN_LIVE_LLM=1 python -m llm_abm_sim.run \
  --config configs/live/provider_smoke.yaml \
  --output runs/live-provider-smoke
```

Provider 产物只暴露 allowlist 证据：provider 名称、脱敏 base URL、model、wire API、adapter/version、readiness 布尔值、fail-closed action、prompt version、provider decision count、decision source summary。不会序列化 raw prompts、raw responses、headers、cookies、tokens、auth files、credential paths。

## 人工评审清单

- [ ] `report.html` 能回答：仿真什么、用了哪些输入、发生了什么、指标含义、是否使用 LLM/Provider。
- [ ] 语言切换能明显切换中英文文案。
- [ ] Agent I/O 面板显示 post/profile/peer/platform/time/prompt-version 输入和 `EngageDecision` 输出。
- [ ] `input-builder.html` 提供双语字段说明和可运行配置模板。
- [ ] 默认产物不含秘密，不需要 API key 或网络。

## Web 控制台验证

自动化浏览器覆盖位于 `tests/playwright/web-console.spec.ts`：

```bash
npx playwright test tests/playwright/web-console.spec.ts
```

人工冒烟建议：

```bash
rm -rf runs/web-ui-polish
python -m llm_abm_sim.web --host 127.0.0.1 --port 8000 --artifact-root runs/web-ui-polish
# 打开 http://127.0.0.1:8000
# 上传 configs/templates/web_users.csv 和 configs/templates/web_edges.csv
# 勾选 “Use mock provider for test/dev”，校验数据，运行并检查结果
rg -i 'sk-|Bearer|authorization|cookie|access_token|raw_prompt|raw_provider|headers|credential|password|secret' runs/web-ui-polish || true
```

预期：生成的运行产物不包含真实 token、header、cookie、raw prompt 或 raw provider response。`secret` / `credential` 等词可能出现在安全策略说明中，需要确认不是实际值。
