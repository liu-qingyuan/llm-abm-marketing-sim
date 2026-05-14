# Architecture

```mermaid
graph TB
    dataset[Real social network dataset] --> graph[NetworkX graph layer]
    graph --> env[PlatformEnvironment]
    post[Post content] --> model[SimulationModel]
    env --> model
    model --> agents[SocialUserAgent population]
    agents --> decision[LLMDecisionAdapter]
    decision --> schema[EngageDecision schema]
    schema --> agents
    agents --> env
    env --> metrics[MetricsCollector]
    metrics --> report[Diffusion report]
```

## Key Principle

The ABM loop owns state and time. The LLM is a replaceable decision function, not the orchestrator.

## Obsidian Contract Mapping

| Obsidian layer / object | Code artifact | Status |
|---|---|---|
| 输入场景：营销内容、网络、种子、平台上下文、时间设置 | `SimulationInput`, `PostContent`, `PlatformContext`, `SimulationConfig`, `configs/default.yaml` | Implemented |
| 真实社交平台环境：推荐、曝光、互动痕迹、平台规则 | `PlatformEnvironment`, `interaction_traces`, exposure boost fields | Implemented lightweight MVP |
| 用户 Agent：偏好、历史倾向、同伴影响、平台暴露、时间状态 | `UserProfile`, `PeerContext`, `SocialUserAgent.step(... time_step ...)` | Implemented lightweight MVP |
| LLM 决策结构 | `DecisionInput`, `LLMDecisionAdapter`, `EngageDecision`, `CachedDecisionAdapter` | Interface + deterministic baseline |
| 多轮传播反馈 | `SimulationModel.run/step`, `ExposureEvent`, `DecisionEvent`, `ActionEvent`, `StepRecord` | Implemented |
| 输出指标 | `MetricsCollector.summary`, `write_run_outputs`, `report.html` | Implemented core metrics |

首版仍保持轻量：没有把 LangChain/LangGraph/GenericAgent 放入核心；真实 provider 调用仍是手动 gate。
