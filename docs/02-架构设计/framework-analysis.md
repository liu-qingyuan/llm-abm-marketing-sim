# 框架选型分析

## 当前状态

本仓库已经具备轻量 LLM-ABM 营销扩散仿真的主要边界：

- `SimulationModel` 控制运行循环。
- `PlatformEnvironment` 管理曝光和同伴影响状态。
- `SocialUserAgent` 表示社交用户。
- `LLMDecisionAdapter` 隔离二元 `engage / not engage` 决策。
- `RuleBasedDecisionAdapter` 提供确定性离线基线。
- Pydantic 校验帖子、用户、同伴上下文、决策、配置和事件。
- NetworkX 加载社交网络边列表。
- `MetricsCollector` 记录每步和汇总指标。

## 选型结论

首版继续使用 **自定义轻量 ABM Core**，Mesa 暂时作为可选项保留。

本项目核心不是自主工具调用，而是在图状态上反复执行受控决策函数：

```text
post content + individual preference + peer influence -> engage / not engage
```

因此：

- 保留 **NetworkX** 作为图和数据层。
- 保留 **Pydantic** 作为 schema 和验证层。
- 保留 **LLMDecisionAdapter** 作为唯一 LLM 边界。
- 保留 **Mesa** 为可选项，等调度复杂度真的需要再引入。
- 首阶段不把 **LangChain**、**LangGraph** 或 **GenericAgent** 放进核心。

## 与 Obsidian 架构笔记的匹配

Obsidian 笔记描述的目标栈是：

```text
Mesa / custom ABM kernel + NetworkX + LLMDecisionAdapter + Pydantic Schema + DuckDB/SQLite cache
```

当前仓库已经覆盖自定义 ABM、NetworkX、adapter、Pydantic 的最小骨架。后续重点是增强科学实验可用性：事件、复现、缓存、指标和报告。

## 主要差距与处理状态

### 1. 事件与状态合约

早期实现偏快照：已曝光用户、已互动用户、简单决策。当前已经增加：

- `ExposureEvent`
- `DecisionEvent`
- `ActionEvent`
- `StepRecord`
- `SimulationRunResult`

这些事件让扩散深度、速度、路径和回放更容易计算。

### 2. 显式可复现性

可复现性依赖：

- `run_id`
- `random_seed`
- 调度顺序
- 图方向性策略
- 吸收式互动语义

默认测试和样例应持续证明同一配置 + seed 产生稳定结果。

### 3. 互动语义

MVP 使用 **absorbing engagement**：用户一旦 engage，就一直作为后续扩散影响源。重复曝光或疲劳效应可以后续作为新事件类型加入。

### 4. 数据集导入

当前支持边列表和用户画像 CSV/JSON，并输出 `dataset_validation.json`。后续如接入真实平台数据，需要继续强化：

- 匿名化/脱敏流程；
- profile 字段映射；
- 权重/关系类型语义；
- 数据版本与实验追踪。

### 5. 指标

已覆盖 reach、engagement rate、diffusion depth、spread speed、key influencers、conversion trend、action counts 等核心指标。后续可以增加：

- 社群级扩散；
- 影响路径贡献；
- 平台规则敏感性；
- A/B 内容对比。

### 6. LLM 集成

Provider 集成必须在缓存、事件日志和安全序列化之后进行。原因：真实 LLM 昂贵、非确定、调试困难；没有事件和缓存时无法解释或复现。

## 推荐组件边界

| 边界 | 推荐做法 |
|---|---|
| ABM 运行时 | 保持自定义、显式、可测试 |
| 图层 | 继续使用 NetworkX |
| Schema | 继续集中在 Pydantic 模型 |
| LLM | 只通过 `LLMDecisionAdapter` 接入 |
| 缓存 | 以 `DecisionInput` 为稳定 key；后续可持久化到 SQLite/DuckDB |
| 输出 | 事件溯源 JSON/CSV + 本地 HTML 报告 |
| Web | 单用户本地控制台，不改变核心仿真边界 |

## 依赖策略

### 现在需要

- `pydantic`
- `networkx`
- `pandas`
- `PyYAML`
- `pytest`
- `ruff`
- `mypy`
- `playwright`（仅浏览器验证）

### 后续可选

- `openai`：Provider-backed adapter。
- `mesa`：当调度器复杂度需要 ABM 框架支持时再引入。
- `duckdb` / `sqlite`：持久化决策缓存和实验记录。
- 图表库：等指标 schema 稳定后再加入。

## 近期架构判断

继续投资以下方向：

1. 更清晰的数据导入和校验产物；
2. 更完整的事件派生指标；
3. 更安全可解释的 Provider 证据；
4. 更易理解的中文文档和本地演示体验。

不建议现在做：

- 把核心改成 LangChain/LangGraph；
- 为了“像 Agent”而引入通用自主 Agent 编排；
- 默认测试依赖真实 Provider；
- 把私密社交平台导出样例提交进仓库。
