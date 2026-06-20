# 架构说明

本项目采用轻量自定义 ABM Core：仿真循环负责时间、状态和传播；LLM 只作为可替换的决策函数。

```mermaid
graph TB
    dataset[真实或模拟社交网络数据] --> graph[NetworkX 图层]
    graph --> env[PlatformEnvironment 平台环境]
    post[营销帖子内容] --> model[SimulationModel 仿真模型]
    env --> model
    model --> agents[SocialUserAgent 用户群]
    agents --> decision[LLMDecisionAdapter 决策适配器]
    decision --> schema[EngageDecision 结构化输出]
    schema --> agents
    agents --> env
    env --> metrics[MetricsCollector 指标收集]
    metrics --> report[扩散报告与运行产物]
```

## 核心原则

- **ABM 循环拥有时间和状态。** 每个 time step 的曝光、决策、互动和指标都由 `SimulationModel` 与 `PlatformEnvironment` 驱动。
- **LLM 不是调度器。** LLM/Provider 只在 `LLMDecisionAdapter` 边界内返回结构化决策。
- **默认可复现。** 默认使用规则基线和随机种子，不依赖外部网络或 API key。
- **事件先行。** 通过曝光、决策、动作和 step records 保留传播过程，方便复盘与指标计算。

## 主要职责边界

| 组件 | 职责 | 关键协作者 |
|---|---|---|
| `SimulationInput` / `SimulationConfig` | 描述实验输入、随机种子、仿真 horizon、用户和数据集配置 | `ExperimentRunner` |
| `PlatformEnvironment` | 管理曝光机制、邻居状态、可见互动痕迹和传播候选 | `SimulationModel`、NetworkX graph |
| `SocialUserAgent` | 保存用户画像、曝光状态、吸收式互动状态，调用决策适配器 | `LLMDecisionAdapter` |
| `LLMDecisionAdapter` | Provider 无关的决策函数接口 | 规则基线、Provider adapter、缓存 wrapper |
| `EngageDecision` | 结构化决策输出：engage、action、probability、reason、confidence | 所有 adapter 和事件 |
| `DecisionCache` | 以稳定 `DecisionInput` 为 key 缓存决策 | `CachedDecisionAdapter` |
| `MetricsCollector` | 计算覆盖率、互动率、扩散深度、速度、关键影响者等指标 | `SimulationModel`、输出层 |
| `write_run_outputs` | 输出 JSON、CSV、HTML 报告、图追踪、报告 payload | CLI、Web service |

## 与 Obsidian 合约映射

| Obsidian 层/对象 | 代码实现 | 状态 |
|---|---|---|
| 输入场景：营销内容、网络、种子、平台上下文、时间设置 | `SimulationInput`、`PostContent`、`PlatformContext`、`SimulationConfig`、`configs/default.yaml` | 已实现 |
| 真实社交平台环境：推荐、曝光、互动痕迹、平台规则 | `PlatformEnvironment`、`interaction_traces`、exposure boost 字段 | 轻量 MVP 已实现 |
| 用户 Agent：偏好、历史倾向、同伴影响、平台暴露、时间状态 | `UserProfile`、`PeerContext`、`SocialUserAgent.step(... time_step ...)` | 轻量 MVP 已实现 |
| LLM 决策结构 | `DecisionInput`、`LLMDecisionAdapter`、`EngageDecision`、`CachedDecisionAdapter` | 接口 + 确定性基线 + 可选 Provider |
| 多轮传播反馈 | `SimulationModel.run/step`、`ExposureEvent`、`DecisionEvent`、`ActionEvent`、`StepRecord` | 已实现 |
| 输出指标 | `MetricsCollector.summary`、`write_run_outputs`、`report.html` | 核心指标已实现 |

## 为什么核心不引入通用 Agent 框架

项目要解决的问题是“图状态上的重复决策函数”，而不是让一个 Agent 自主调用工具完成任务。核心公式是：

```text
帖子内容 + 用户偏好 + 同伴影响 + 平台上下文 -> EngageDecision
```

因此首版把 LangChain、LangGraph、GenericAgent 留在核心之外，避免把可复现仿真变成难以复盘的通用智能体流程。
