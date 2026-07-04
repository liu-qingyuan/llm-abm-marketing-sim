# 开发计划

Status: Historical PRD
Legacy source: [`../04-开发验证/01-development-plan.md`](../04-开发验证/01-development-plan.md)
Related ADR: [`../adr/0001-deterministic-event-sourced-abm-mvp.md`](../adr/0001-deterministic-event-sourced-abm-mvp.md)

本文是项目早期 ABM MVP 开发计划的历史记录，用于追溯初始目标、阶段路线和验收思路。它不代表当前待办状态；新的可执行工作应从当前 PRD 或 GitHub issues 派生。

## 产品目标

构建一个可复现的 LLM-supported ABM 仿真器，用于模拟营销帖子如何在真实或模拟社交网络中扩散。每个社交用户 Agent 基于以下信息做二元决策：

1. 帖子内容；
2. 个人偏好；
3. 同伴影响；
4. 平台上下文。

默认情况下，仿真器必须不依赖真实 LLM 调用；同时保留清晰 adapter 边界，便于后续接入 Provider-backed 决策。

## RALPLAN-DR 摘要

### 原则

1. ABM 循环拥有时间、状态和可复现性。
2. LLM 是可替换决策函数，不是仿真调度器。
3. Pydantic schema 定义所有外部输入/输出边界。
4. 指标和可回放性是研究输出的一等公民。
5. 核心保持轻量；只有后续需求证明必要时才加入 Mesa、LangChain 等更重依赖。

### 核心决策驱动

1. 端到端可运行实验循环必须匹配 Obsidian 时序。
2. 昂贵、非确定的 Provider 调用之前，必须先有确定性基线。
3. 研究可用性：配置、数据集、事件、指标和报告都应可检查。

### 方案对比

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| 先做自定义确定性 ABM MVP | 小、可检查、可复现、可测试 | 需要显式设计事件和调度 | 选择 |
| 立即做 Provider-backed LLM adapter | 早展示 LLM 特色 | 成本高、非确定、难调试 | 延后 |
| Mesa-first | 有成熟 ABM 约定 | 域合约未稳定前容易过早耦合 | 保持可选 |
| LangChain/LangGraph/GenericAgent 核心 | 适合工具/工作流 Agent | 不适合重复图状态决策函数 | 核心拒绝 |

### ADR

**决策：** 先构建确定性、事件溯源的自定义 ABM MVP。保留 `LLMDecisionAdapter` 为中心，但真实 Provider 调用必须等事件日志、可复现性、`DecisionInput` 和 `DecisionCache` 边界存在后再接入。

**原因：** 项目可信度取决于可重复仿真、可验证指标和真实图导入。过早接 live LLM 会让结果更难验证。

**影响：**

- 默认测试和样例运行不需要 API 凭证。
- LLM Provider 集成是 opt-in 能力。
- 事件和指标 schema 优先于复杂报告和可视化。

## 阶段路线与状态

### Phase 0：依赖与基线验证

状态：已完成。

交付：

- 创建 `.venv`。
- editable 安装 dev extras。
- 验证 `pydantic`、`networkx`、`pandas`、`pytest`。
- 运行测试与 Python 编译检查。

### Phase 1：确定性 ABM 运行时合约

状态：已完成核心能力。

交付：

- `SimulationConfig` 支持随机种子等可复现字段。
- 替换全局随机，使用注入 RNG。
- MVP 定义 absorbing engagement。
- 事件 schema：`ExposureEvent`、`DecisionEvent`、`ActionEvent`、`StepRecord`、`SimulationRunResult`。
- `SimulationModel.step()` 使用稳定调度顺序。

验收：

- 同一 config + seed 产生相同事件和指标。
- 小图集成测试覆盖 exposure -> decision -> update -> collect。
- Agent 与 environment 的互动状态在 absorbing semantics 下不发散。

### Phase 2：ExperimentRunner 与配置加载

状态：已完成。

交付：

- `ExperimentRunner`。
- 从 `configs/default.yaml` 加载 Pydantic config。
- 从配置构建 graph、profiles、agents、environment、adapter、metrics collector。
- CLI 入口：`python -m llm_abm_sim.run ...`。

验收：

- 本地命令可从配置运行样例仿真。
- 输出结构化 `SimulationRunResult` 和报告产物。
- README 与文档记录安装和样例运行方式。

### Phase 3：数据集/用户画像导入

状态：已完成主要能力。

交付：

- 支持 edge-list 加载。
- 支持 profile CSV/JSON。
- 图节点与 profile 记录校验。
- 支持 directedness、edge weight、edge attributes。
- 输出 `dataset_validation.json`。

验收：

- 集成测试加载 toy edge list 和 profile 文件。
- missing profile 策略明确：默认画像或校验错误。
- loader 返回 graph + profile mapping + validation metadata。

### Phase 4：事件派生指标与导出

状态：已完成核心指标。

交付：

- Metrics collector 消费事件。
- 计算 reach/coverage、engagement rate、new engagements per step、diffusion speed、approx diffusion depth/path、key influencers、action counts。
- 导出 JSON/CSV/HTML/report payload/graph trace。

验收：

- 固定 toy graph 上指标确定。
- 测试断言精确时间序列和汇总值。
- 输出文件可被常见工具读取。

### Phase 5：DecisionInput 与缓存边界

状态：已完成核心能力。

交付：

- `DecisionInput` schema 包含 post、profile、peer context、platform context、time step、prompt/schema version。
- `DecisionCache` 接口和内存实现。
- 稳定 cache key。
- `CachedDecisionAdapter` wrapper。

验收：

- 相同决策输入触发 cache hit，避免重复 adapter 调用。
- post/profile/peer/prompt version 改变时 cache key 改变。
- 默认测试仍无网络依赖。

### Phase 6：可选 Provider-backed LLM adapter

状态：已实现可选路径，默认关闭。

交付：

- Provider-backed adapter 放在 optional `[llm]` 依赖后。
- 秘密只来自环境变量或仓库外本地配置。
- Provider 输出通过 `EngageDecision` 解析校验。
- mock Provider 测试与 live gate 测试。
- Web product mode fail closed。

验收：

- 默认测试不需要 API 凭证。
- Mocked LLM 测试覆盖 schema、fallback/cache 行为。
- live-provider smoke opt-in，默认跳过/关闭。

### Phase 7：报告与可视化

状态：本地产品原型已完成主要能力。

交付：

- 本地静态 `report.html`。
- JSON/CSV 输出表。
- `report_payload.json`、`graph_trace.json`。
- 双语报告与输入构建器。
- 本地 Web 控制台。

验收：

- 样例运行生成包含 config、events、metrics、summary、report 的输出目录。
- 报告解释输入、过程、指标和决策来源。
- Playwright 验证静态报告和 Web 控制台关键流程。

## 后续建议路线

1. **真实数据清洗流程**：定义从平台导出到匿名化 fixture 的数据处理脚本和数据字典。
2. **持久化决策缓存**：在 `DecisionCache` 后增加 SQLite/DuckDB 实现。
3. **实验批处理**：支持多配置、多 seed、A/B 帖子内容批量运行。
4. **更丰富指标**：社群级传播、路径贡献、平台参数敏感性、内容对比。
5. **报告体验强化**：增加更多图表，但保持静态可打开和无秘密输出。

## 测试策略

### 单元测试

- Pydantic schema 校验。
- 规则决策概率和阈值行为。
- seeded exposure policy。
- 事件 schema 序列化。
- cache hit/miss 和 key stability。
- 指标聚合。
- Provider config redaction。

### 集成测试

- 加载 toy graph 和 profiles。
- 用固定 seed 运行固定 horizon 仿真。
- 断言事件序列和指标摘要。
- 数据集校验 metadata。
- mocked Provider runner 行为。

### 冒烟检查

```bash
. .venv/bin/activate
pytest -q
python -m py_compile $(find src tests -name '*.py' -print)
python -m llm_abm_sim.run --config configs/default.yaml --output runs/sample
python -m llm_abm_sim.run --config configs/fixtures/realistic_marketing_dataset.yaml --output runs/realistic-sample
npx playwright test tests/playwright/report-smoke.spec.ts
```

## OMX/Agent 执行建议

### `$ralph`

适合单人持续执行某个具体阶段，例如“实现持久化缓存”或“增加批处理实验 runner”。

示例：

```text
$ralph implement persistent DecisionCache storage for llm-abm-marketing-sim, preserving deterministic defaults and no API-key requirement.
```

### `$team`

适合拆分 runtime、metrics、dataset、docs、tests 的多 lane 工作。

建议 lanes：

1. Runtime lane：模型/环境/事件改动。
2. Runner lane：配置加载和输出编排。
3. Metrics lane：事件派生指标。
4. Test lane：单元/集成/E2E 覆盖。
5. Docs lane：中文文档、README、Obsidian 对齐。

### `$ultragoal`

适合把完整多阶段路线变成持久目标：

```text
$ultragoal "Deliver a reproducible LLM-ABM marketing diffusion simulator with deterministic ABM runtime, event-derived metrics, decision cache, optional LLM adapter, and report outputs."
```

如果主要工作变成数据/文献研究，可用 `$autoresearch-goal`；如果主要工作变成规模化或吞吐优化，可用 `$performance-goal`。
