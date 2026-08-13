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

## Concurrent Message Validation run

对 1,000-user / 30-batch / 3-message additive runtime 执行完整离线 validation 时，使用固定 mocked `openai_compatible` provider 入口：

```bash
. .venv/bin/activate
python scripts/run_concurrent_message_validation.py \
  --dataset-dir data/processed/jinjiang_douyin/<latent-v1-run> \
  --output-dir runs/jinjiang-concurrent-message-mock-validation-<UTC>
```

该脚本固定写出 `configuration_profile=production` 的 1,000-user contract，但保持 `sampling_status=validation_run`、`production_deploy_eligible=false` 和 `live_api_triggered=false`。它只用于完整 offline/mock evidence，不授权真实 Provider、SSH 或 deploy。默认 metadata 与 #99 的 human-approved contract 对齐：requested `gpt-5.4-mini`、observed `gpt-5.4-mini-2026-03-17`、timeout `30s`、adapter retry `2`、wire `responses`；如需改变这些字段，必须在独立 operational Ticket 中重新授权。

对已持久化的 concurrent-message report 做桌面/移动端本地验收时，可直接把 run 目录交给 Playwright：

```bash
CONCURRENT_MESSAGE_REPORT_DIR=runs/jinjiang-concurrent-message-mock-validation-<UTC> \
  npx playwright test tests/playwright/concurrent-message-report.spec.ts
```

这会复用既有 report smoke，在 `1440x1000` 与 `390x844` 视口验证五组 UI、trace drawer、downloads 和无水平溢出/文字重叠。

## Final Research release validation 与部署

本地 release evidence 验证使用唯一入口：

```bash
. .venv/bin/activate
python scripts/validate_abm_report_release.py \
  --repo-root . \
  --contract configs/deployments/<release-contract>.json \
  --source-dir runs/<persisted-run>
```

该命令支持历史 `abm-report-release-contract-v1` 的本地证据验证，以及 v2–v7 的版本化 Formal production 验证。v2/v3/v4 分别保护 Final Research 与 Concurrent Message 的既有合同；v5/v6/v7 通过独立 exact-field dispatch 保护 Concurrent Robustness release。v7 只接受 payload v2 + closure v2 的 semantic-only production：inventory 必须精确包含七个 Mermaid artifacts，并排除 `project-evidence-chain.mmd`、未批准 v4 PNG/WebP 与 `mechanism-image-generation-audit.json`。source directory 不允许绝对/父级 artifact path、symlink、FIFO/socket/device 等 non-regular entry、未声明文件、缺失下载或 hash 不一致；validation/mock/rule-based evidence 不能通过 `--require-formal-production`。

production deploy 只能显式提供通过本地 gate 的 v2–v7 Formal contract：

```bash
scripts/deploy_abm_report.sh \
  --contract configs/deployments/<authorized-formal-contract>.json \
  --source-dir runs/<authorized-formal-run> \
  --release-id <release-id>
```

部署脚本先复制随机本地 snapshot，并让 standalone validator 在任何 `ssh`、上传或远程配置前一次性产出 validated deployment facts；report kind、release/domain identity、完整 artifact hashes 与 public acceptance list 只来自显式 contract。后续 checksum、tar upload 和 public acceptance 继续读取同一只读 snapshot/facts，不扫描“最新”目录，也不按文件存在猜测版本。远端在 atomic `current` 切换前核对完整 regular-file inventory、report/manifest/release identity、candidate container 与 Nginx；任一步失败都保持或恢复部署前 fresh `current`，并重新核对旧 report/manifest hashes。切换后按 contract 对每个 artifact 做公网 hash 验收，再运行 desktop/mobile、双语、键盘与交互 Playwright acceptance。

实现代码、离线 runner candidate、synthetic persisted Formal fixture 和 `ready-for-agent` 状态均不授权真实 Provider 或 production deployment。后续 operational Ticket 必须单独记录 Provider、模型、adapter retry / SDK retry、调用或费用预算、独立 output directory、release ID 和 canonical deployment 授权。不要用 fake Adapter 写出 live 事实，也不要把测试 fixture 描述为真实研究运行；Concurrent Message Validation artifact 只能作为 #99 的离线 preflight evidence，不能直接生成或替代 `abm-report-release-contract-v4` Formal release。

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

详细说明见：[ABM Runtime 与仿真流程](../architecture/abm-runtime.md)。

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
