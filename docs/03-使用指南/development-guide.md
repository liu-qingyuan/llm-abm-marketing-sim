# 开发指南

本文面向需要修改代码、运行质量门禁或接入新能力的开发者。新机器安装请优先看：[macOS 从零开始运行指南](getting-started-macos.md)。

## 前置条件

- Python 3.10+
- Node.js 18+
- npm
- 可选：本地 Codex/sub2api Provider 配置，用于手动 live gate readiness 检查

## 安装

完整开发环境：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev,web,llm]"
npm ci
npx playwright install chromium
```

CLI-only 开发可只安装：

```bash
python -m pip install -e ".[dev]"
```

验证新克隆环境时请使用 `npm ci`，不要用 `npm install` 替代 lockfile 校验。

## 运行仿真

默认离线样例：

```bash
. .venv/bin/activate
python -m llm_abm_sim.run --config configs/default.yaml --output runs/sample
```

预期生成：

```text
runs/sample/config.json
runs/sample/default.yaml
runs/sample/events.json
runs/sample/metrics_summary.json
runs/sample/report.html
runs/sample/run_result.json
runs/sample/step_records.csv
runs/sample/report_payload.json
runs/sample/graph_trace.json
runs/sample/input-builder.html
```

真实感数据样例：

```bash
. .venv/bin/activate
python -m llm_abm_sim.run --config configs/fixtures/realistic_marketing_dataset.yaml --output runs/realistic-sample
```

该样例使用可提交的真实感社交网络数据：有向加权边、关系/触点元数据、社群、种子用户、平台上下文、时间设置和营销内容。替换为本地私密数据时，请把清洗后的文件放在被忽略的 `data/raw/` 或 `data/processed/`，并在本地配置中更新 `dataset.edge_list_path` / `dataset.profile_path`。不要提交原始导出、handle、email、token、cookie、API key 或 secret-bearing headers。

## 质量门禁

常规完整检查：

```bash
. .venv/bin/activate
ruff check .
ruff format --check .
mypy src
pytest -q
python -m py_compile $(find src tests -name '*.py' -print)
python -m llm_abm_sim.run --config configs/default.yaml --output runs/sample
python -m llm_abm_sim.run --config configs/fixtures/realistic_marketing_dataset.yaml --output runs/realistic-sample
pytest -q tests/web/test_web_api.py
npx playwright test tests/playwright/web-console.spec.ts
```

手动 live gate 检查：

```bash
pytest -q -m live_llm -rs                         # 无 live gate 时应 skip/fail closed
LLM_ABM_RUN_LIVE_LLM=1 pytest -q -m live_llm -rs
OPENAI_API_KEY=... LLM_ABM_RUN_LIVE_LLM=1 pytest -q -m live_llm -rs
```

live gate 只有在显式 opt-in，并且 Codex Provider config/auth 或 `OPENAI_API_KEY` 与可选 `openai` 依赖可用时，才会发起一次真实 Provider 决策。默认验证不进行网络调用。

## 常见开发任务

### 新增仿真配置字段

1. 在 `src/llm_abm_sim/schemas.py` 添加字段。
2. 在 `runner.py`、`environment.py` 或 `model.py` 中接入使用。
3. 如果希望样例可见，更新 `configs/default.yaml`。
4. 在 `tests/unit` 或 `tests/integration` 添加/调整测试。
5. 重新运行质量门禁。

### 新增指标

1. 如果现有事件不够，先在 `events.py` 捕获所需数据。
2. 更新 `metrics.py` 中的 `MetricsCollector.summary` 或 step records。
3. 如果指标需要出现在产物里，更新 `outputs.py` / report payload。
4. 在 `tests/integration/test_obsidian_metrics_contract.py` 加精确期望。

### 新增 Provider-backed LLM adapter

1. 在 `src/llm_abm_sim/providers/` 实现 `LLMDecisionAdapter`。
2. Provider SDK 放入 `[project.optional-dependencies].llm`。
3. 用 `DecisionInput` / `prompting.py` 构造 prompt，显式包含帖子、偏好、同伴影响和平台上下文。
4. Provider 输出必须通过 `EngageDecision` 校验。
5. 支持 `provider_llm.fail_closed_action`：`raise`、`no_engage`、`skip_run`；默认 `raise`。
6. 在 runner 中用 `CachedDecisionAdapter` 包裹 Provider adapter。
7. 真实网络测试必须放在 `live_llm` 和 `LLM_ABM_RUN_LIVE_LLM=1` 后面。
8. 不记录、不快照 API key、bearer token、cookie、header、auth file。

### 新增数据集导入能力

1. 扩展 `schemas.py` 中的 `DatasetConfig`。
2. 在 `graph_loader.py` 和 `runner.py` 增加加载行为。
3. 保留明确的 missing-profile / extra-profile 策略。
4. 添加可提交的安全 fixture 和集成测试。
5. 更新 [数据集与用户画像导入](dataset-ingestion.md)，说明 schema、校验策略、种子/平台/时间配置、隐私规则和路径解析。

## 本地 Web 控制台

安装 `web` extra 后启动：

```bash
. .venv/bin/activate
python -m llm_abm_sim.web --host 127.0.0.1 --port 8000 --artifact-root runs/web
# 或：llm-abm-web --host 127.0.0.1 --port 8000 --artifact-root runs/web
```

打开 `http://127.0.0.1:8000`。Product 模式会预检 `/api/provider/readiness`，在 live gate、可选 SDK、Provider metadata 和 runtime credential 就绪前保持 `blocked`。离线 demo/tests 请启用 **Use mock provider for test/dev**；mock run 会明确标记并避免网络/秘密。

Web 产物写入 `runs/web/<run-id>/`，包含 `web_run_metadata.json` 和常规报告产物。

## 测试策略摘要

- 纯 schema、decision、cache 行为优先写单元测试。
- runner/model/environment 交互写集成测试。
- CLI 到输出产物的完整链路写 Python E2E。
- 生成静态报告和 Web 控制台浏览器流程用 Playwright。
- 默认测试套件必须离线、确定性、无密钥。

详细说明见：[测试策略](../04-开发验证/test-strategy.md)。

## 生成产物策略

以下目录/文件应保持 git 忽略：

- `.venv/`
- `.mypy_cache/`、`.ruff_cache/`、`.pytest_cache/`
- `runs/`
- `test-results/`、`playwright-report/`、`blob-report/`
- `node_modules/`
- `.agents/`、`_bmad/`
- `*.egg-info/`

## Commit / Review 注意事项

- 保持 diff 小、可审查、可回滚。
- handoff 中包含命令证据。
- 没有新批准需求时，不要把 LangChain、LangGraph 或 GenericAgent 引入核心 ABM runtime。

## 手动 live Provider smoke

默认开发和 CI 风格测试都离线。安装可选 LLM extra，并确认 Provider readiness 后，可手动执行：

```bash
LLM_ABM_RUN_LIVE_LLM=1 python -m llm_abm_sim.run --config configs/live/provider_smoke.yaml --output runs/live-provider-smoke
```

检查 `runs/live-provider-smoke/metrics_summary.json` 中的 `decision_source_summary` 和脱敏 `provider_evidence`。不要提交运行产物或凭证。
