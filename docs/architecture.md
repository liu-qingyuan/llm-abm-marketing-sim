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
