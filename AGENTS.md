# AGENTS.md — LLM-ABM 营销传播模拟项目指南

本文件用于指导后续 Codex / OMX / 子 Agent 在本项目中工作。进入本仓库时，应优先遵守本文件，再结合上级 `/Users/lqy/work/AGENTS.md` 的通用规则。

## 上游参考资料

本项目的架构、流程图、时序图和产品定位，主要参考 Obsidian 知识库目录：

```text
/Users/lqy/work/Obsidian_work/Obsidian_work/LLM-ABM营销传播模拟
```

关键参考文件：

```text
05-开发架构设计.md
06-开发流程与运行时序.md
01-项目框架说明.md
02-仿真流程与时序.md
03-指标与应用场景.md
```

如果代码实现、文档、测试与 Obsidian 参考资料产生冲突，应先检查这些参考文件，再判断是更新代码、更新项目文档，还是补充 ADR 说明偏离原因。

## 项目定位

本项目是：

> 使用 Agent-Based Modeling 模拟社交网络中帖子/营销内容扩散过程的轻量级仿真器。

核心不是通用自主 Agent 框架，而是在真实或模拟社交网络图上，让每个社交用户 Agent 基于以下三类信息做二元决策：

1. `post content`：帖子内容、话题、素材摘要；
2. `individual preference`：用户兴趣、品牌态度、活跃度、历史偏好；
3. `peer influence`：邻居曝光、邻居互动比例、关键邻居影响。

决策输出应保持结构化：

```text
engage: bool
probability: 0.0 到 1.0
reason: 简短理由
confidence: 0.0 到 1.0
```

## 推荐架构方向

首版保持轻量：

```text
自定义 ABM Core + NetworkX + Pydantic + LLMDecisionAdapter + DecisionCache
```

推荐职责边界：

| 模块 | 职责 |
|---|---|
| `SimulationModel` | 仿真生命周期、时间步推进、调度顺序 |
| `PlatformEnvironment` | 曝光机制、平台规则、邻居可见状态、互动痕迹 |
| `SocialUserAgent` | 用户状态、观察上下文、调用决策边界 |
| `LLMDecisionAdapter` | 把帖子、偏好、同伴影响转成 `EngageDecision` |
| `DecisionCache` | 缓存 LLM/决策结果，降低成本并支持复现 |
| `ExperimentRunner` | 配置加载、数据集加载、批量实验、输出管理 |
| `MetricsCollector` | 事件流、时间序列指标、覆盖率、互动率、扩散深度/速度 |

## 依赖策略

默认核心依赖：

- `pydantic`：Schema、配置和 LLM 输出校验；
- `networkx`：社交网络图、邻居查询、图指标；
- `pandas`：事件表、指标表、CSV/JSON 输出；
- `pytest`：本地确定性测试。

可选依赖：

- `openai`：后续 provider-backed LLM adapter；
- `mesa`：只有当自定义调度器不够用时再引入；
- `duckdb` / `sqlite`：后续持久化 DecisionCache 和实验记录；
- 图表库：等事件和指标 schema 稳定后再加入。

不要在首版核心中引入 LangChain、LangGraph 或 GenericAgent，除非新的需求明确需要复杂工具编排或图工作流。LLM 在本项目中应是 **decision function**，不是 simulator orchestrator。

## 当前规划文档

本仓库内已有后续开发规划：

```text
docs/framework-analysis.md
docs/development-plan.md
.omx/plans/prd-llm-abm-framework-*.md
.omx/plans/test-spec-llm-abm-framework-*.md
```

实现前应优先阅读 `docs/development-plan.md`。如果执行 `$ralph` 或 `$team`，优先从 Phase 1 / Phase 2 开始：

1. deterministic ABM runtime；
2. event schemas；
3. seeded reproducibility；
4. ExperimentRunner；
5. config loading；
6. toy graph integration tests。

## 实现原则

- 默认路径必须可以离线、无 API key 运行。
- 默认测试不能依赖真实 LLM provider。
- 先实现 rule-based deterministic baseline，再接 LLM adapter。
- 先建立 event-sourced runtime，再做复杂指标和可视化。
- 同一份 config + seed 应产生可复现结果。
- Engagement MVP 采用 absorbing 语义：用户一旦 engage，就持续作为后续扩散影响源。
- LLM provider 输出必须通过 Pydantic schema 校验。
- Secrets/API keys 不得写入仓库、日志、文档或测试快照。

## 测试与验证

常规验证命令：

```bash
. .venv/bin/activate
pytest -q
python -m py_compile $(find src tests -name '*.py' -print)
```

实现 ExperimentRunner 后，应增加 smoke run，例如：

```bash
python -m llm_abm_sim.run --config configs/default.yaml --output runs/sample
```

每次实现完成时，交付说明应包含：

- changed files；
- 测试命令和结果；
- 生成的样例输出路径；
- 未覆盖风险；
- 是否仍保持默认测试无 API key / 无网络依赖。

## GitNexus

本项目已注册 GitNexus alias：

```text
llm-abm-marketing-sim
```

结构性改动、文档大改或新增模块后，建议刷新索引：

```bash
GITNEXUS_NO_GITIGNORE=1 gitnexus analyze /Users/lqy/work/llm-abm-marketing-sim --name llm-abm-marketing-sim --skip-agents-md --force
gitnexus status
```

注意：如果希望 GitNexus 也读取本 `AGENTS.md`，不要使用 `--skip-agents-md`。如果只想避免 GitNexus 生成/改写 Agent 指导文件，可以继续使用 `--skip-agents-md`。
