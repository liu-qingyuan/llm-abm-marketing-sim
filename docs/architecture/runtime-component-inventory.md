# 组件清单

Status: Architecture Note
Legacy source: `docs/04-开发验证/03-component-inventory.md`（已删除；迁移索引见 [`../04-开发验证/README.md`](../04-开发验证/README.md)）

本文记录主要运行时、输出、Provider 和测试组件，方便后续开发者与 AI Agent 快速定位职责。

## 运行时组件

| 组件 | 文件 | 职责 | 关键协作者 |
|---|---|---|---|
| `SimulationInput`、`SimulationConfig`、`PostContent`、`PlatformContext`、`UserProfile`、`PeerContext` | `src/llm_abm_sim/schemas.py` | Pydantic 输入、配置和状态 schema | `runner.py`、`decision.py`、`environment.py` |
| `SocialUserAgent` | `src/llm_abm_sim/agent.py` | 用户级曝光/互动状态与决策调用边界 | `SimulationModel`、`LLMDecisionAdapter` |
| `EngageDecision` | `src/llm_abm_sim/decision.py` | 结构化动作决策：engage、action、probability、reason、confidence | 所有 adapter 和事件 |
| `DecisionInput` | `src/llm_abm_sim/decision.py` | 稳定缓存/Prompt 输入 schema | `CachedDecisionAdapter`、`prompting.py` |
| `LLMDecisionAdapter` | `src/llm_abm_sim/decision.py` | Provider 无关的决策函数接口 | `RuleBasedDecisionAdapter`、未来 Provider |
| `RuleBasedDecisionAdapter` | `src/llm_abm_sim/decision.py` | 确定性离线基线 | `ExperimentRunner` |
| `DecisionCache`、`InMemoryDecisionCache`、`CachedDecisionAdapter` | `src/llm_abm_sim/decision.py` | 缓存边界与默认内存 wrapper | `ExperimentRunner`、Provider adapter |
| `PlatformEnvironment` | `src/llm_abm_sim/environment.py` | 曝光机制、可见互动痕迹、peer context、传播候选 | `SimulationModel` |
| `SimulationModel` | `src/llm_abm_sim/model.py` | 运行生命周期、time-step 调度、事件收集 | `PlatformEnvironment`、agents、metrics |
| `MetricsCollector` | `src/llm_abm_sim/metrics.py` | 时间序列和聚合扩散指标 | `SimulationModel`、outputs |
| `ExperimentRunner` | `src/llm_abm_sim/runner.py` | 配置加载、图/画像/Agent/模型构建、输出编排 | CLI、测试、Web service |

## 事件与输出组件

| 组件 | 文件 | 职责 |
|---|---|---|
| `ExposureEvent` | `src/llm_abm_sim/events.py` | 记录首次曝光、来源、概率、深度、渠道 |
| `DecisionEvent` | `src/llm_abm_sim/events.py` | 记录 adapter 评估与结构化决策 |
| `ActionEvent` | `src/llm_abm_sim/events.py` | 记录 like/comment/share 动作与来源深度 |
| `StepRecord` | `src/llm_abm_sim/events.py` | 每个 time step 的计数和事件组 |
| `SimulationRunResult` | `src/llm_abm_sim/events.py` | 完整可序列化运行输出 |
| `write_run_outputs` | `src/llm_abm_sim/outputs.py` | 写出 `config.json`、`run_result.json`、`metrics_summary.json`、`step_records.csv`、`events.json`、`report.html` |
| `write_report_html` | `src/llm_abm_sim/outputs.py` | 生成最小本地静态报告，供浏览器冒烟测试 |
| `report_payload.py` | `src/llm_abm_sim/report_payload.py` | 构建报告 view-model 与安全图追踪 payload |
| `safe_serialization.py` | `src/llm_abm_sim/safe_serialization.py` | 过滤秘密字段，防止 raw Provider/credential 信息进入产物 |

## Provider 与 live gate 组件

| 组件 | 文件 | 职责 |
|---|---|---|
| `CodexProviderConfig` | `src/llm_abm_sim/provider_config.py` | 无秘密 Provider metadata 摘要 |
| `load_codex_provider_config` | `src/llm_abm_sim/provider_config.py` | 运行时读取 Codex config metadata |
| `should_run_live_llm` | `src/llm_abm_sim/provider_config.py` | 显式 env + auth/provider readiness gate |
| `redact_secrets` | `src/llm_abm_sim/provider_config.py` | 递归脱敏 secret-bearing key/value |
| `OpenAICompatibleDecisionAdapter` | `src/llm_abm_sim/providers/openai_compatible.py` | 可选 OpenAI-compatible Provider 决策 adapter |
| Provider evidence helpers | `src/llm_abm_sim/provider_evidence.py` | 生成 allowlisted Provider 证据摘要 |

## Web 组件

| 组件 | 文件 | 职责 |
|---|---|---|
| FastAPI app | `src/llm_abm_sim/web/app.py` | 本地 API、静态资源挂载、运行状态查询 |
| Web service | `src/llm_abm_sim/web/service.py` | Web run orchestration、artifact 管理、blocked/succeeded 状态 |
| Dataset imports | `src/llm_abm_sim/web/imports.py` | 浏览器上传的 users/edges CSV/JSON 规范化 |
| Static UI | `src/llm_abm_sim/web_static/` | 单用户本地控制台 HTML/CSS/JS |

## 测试组件

| 测试层 | 文件 | 覆盖内容 |
|---|---|---|
| 单元测试 | `tests/unit/*.py` | 规则决策、吸收式互动、Provider config、cache、数据集 loader、图追踪 |
| 集成测试 | `tests/integration/*.py` | runner 确定性、Obsidian 指标合约、mocked Provider runner |
| Python E2E | `tests/e2e/*.py` | CLI 离线产物、产品输出、live LLM gate |
| Web API | `tests/web/test_web_api.py` | 本地 Web API、数据校验、运行状态、artifact 行为 |
| Browser smoke | `tests/playwright/*.spec.ts` | 静态报告与 Web 控制台浏览器流程 |

## 复用建议

- 新增仿真输入：先改 `schemas.py`，再接入 `runner.py` / `environment.py` / `model.py`。
- 新增事件字段：同步更新 `events.py`、`outputs.py`、report payload 和测试。
- 新增 Provider-backed 决策：实现 `LLMDecisionAdapter`，不要让 `SimulationModel` 感知 Provider 细节。
- 新增持久化缓存：实现 `DecisionCache`，保留 `CachedDecisionAdapter` 作为 wrapper 边界。
- 新增 Web 上传格式：先在 `web/imports.py` 规范化，再走已有 `DatasetConfig` / graph loader 校验。
