# ADR 0001: Deterministic Event-Sourced ABM MVP

Status: Accepted
Date: 2026-06
Legacy source: [`../04-开发验证/01-development-plan.md`](../04-开发验证/01-development-plan.md)

## Context

项目需要构建一个可复现的 LLM-supported ABM 仿真器，用于模拟营销帖子如何在真实或模拟社交网络中扩散。项目可信度依赖可重复仿真、可验证指标和真实图导入，而真实 Provider 调用成本高、非确定、难调试。

## Decision

先构建确定性、事件溯源的自定义 ABM MVP。保留 `LLMDecisionAdapter` 为中心，但真实 Provider 调用必须等事件日志、可复现性、`DecisionInput` 和 `DecisionCache` 边界存在后再接入。

## Alternatives Considered

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| 先做自定义确定性 ABM MVP | 小、可检查、可复现、可测试 | 需要显式设计事件和调度 | 选择 |
| 立即做 Provider-backed LLM adapter | 早展示 LLM 特色 | 成本高、非确定、难调试 | 延后 |
| Mesa-first | 有成熟 ABM 约定 | 域合约未稳定前容易过早耦合 | 保持可选 |
| LangChain/LangGraph/GenericAgent 核心 | 适合工具/工作流 Agent | 不适合重复图状态决策函数 | 核心拒绝 |

## Consequences

- 默认测试和样例运行不需要 API 凭证。
- LLM Provider 集成是 opt-in 能力。
- 事件和指标 schema 优先于复杂报告和可视化。
- ABM 循环拥有时间、状态和可复现性。
- LLM 是可替换决策函数，不是仿真调度器。
