# Architecture Note: ABM Runtime 与仿真流程

Status: Implemented current architecture note

本 Note 描述通用轻量 LLM + Agent-Based Modeling runtime。仿真器负责时间、状态、曝光和传播；LLM 只作为可替换的结构化决策函数。当前 Multi-Message Formal Research 另有独立的 [Concurrent Message Architecture](concurrent-message-competition-experiment.md) 和 release evidence。

## 核心 Module 边界

| Module / Interface | 职责 | 不负责 |
|---|---|---|
| `ExperimentRunner` | 读取 YAML/JSON、解析数据集路径、构建图和用户、编排 run 与输出 | 替代 runtime 调度或调用未授权的 live API |
| `SimulationModel` | 管理生命周期、time step、调度顺序和事件写出 | 选择 Provider 或解释外部平台真实日志 |
| `PlatformEnvironment` | 管理曝光候选、邻居可见状态、interaction traces 和传播规则 | 生成 LLM 决策 |
| `SocialUserAgent` | 保存 `UserProfile`、曝光状态、吸收式互动状态，并调用 adapter | 直接读取 Provider payload |
| `LLMDecisionAdapter` | 将 `DecisionInput` 转为结构化 `EngageDecision`；可由规则基线、Provider adapter 或 cache wrapper 实现 | 调度仿真、选择曝光对象或持久化 raw prompt |
| `DecisionCache` | 以稳定输入缓存决策，降低成本并支持复现 | 绕过 schema 校验 |
| `MetricsCollector` | 从事件流计算覆盖率、互动率、扩散深度、速度和时间序列 | 改写事件或产生用户画像 |
| `write_run_outputs` | 写 JSON、CSV、HTML、report payload 和安全 graph trace | 写入 `data/raw`、秘密或 raw Provider 内容 |

## 输入与决策合同

运行输入由营销内容、社交网络、用户画像、seed users、平台上下文和时间设置组成。图可以来自内联配置或 dataset 文件；路径由配置文件所在目录解析。

Decision Adapter 接收：

```text
post content + individual preference + peer influence + platform context + time step
```

输出必须保持结构化：

```text
engage: bool
probability: 0.0 到 1.0
reason: 简短理由
confidence: 0.0 到 1.0
action: like / comment / share / ignore
```

`EngageDecision`、事件和 report payload 经过 Pydantic/安全序列化边界。Provider-backed decision 只允许在显式 live gate 下运行；默认规则基线不访问网络、不需要 API key。

## 一次运行

1. `ExperimentRunner.from_config_file()` 读取配置，并解析相对 dataset 路径。
2. Graph loader 构建 NetworkX 图，校验边属性、画像覆盖和 seed user IDs。
3. Runner 创建 `SimulationModel`、`PlatformEnvironment`、`SocialUserAgent` 和 Decision Adapter。
4. Seed users 首先获得曝光；每个 time step 计算 peer context，再由 Agent 调用 adapter。
5. Model 记录 exposure、decision、action 和 step summary，并把成功互动反馈到后续候选。
6. `MetricsCollector` 从事件流生成 summary；输出层写入机器产物和本地静态报告。

常见产物：

```text
config.json
run_result.json
events.json
metrics_summary.json
step_records.csv
report.html
report_payload.json
graph_trace.json
input-builder.html
dataset_validation.json  # dataset-backed run
```

## 稳定边界

- LLM 不是仿真调度器；Platform Environment 决定曝光，Decision Adapter 只处理决策边界。
- 默认路径离线、确定、无凭证；live Provider 是显式 opt-in 的边界能力。
- event stream 是复盘和指标计算的事实来源；报告只输出 allowlisted、可解释和脱敏的摘要。
- 运行核心不引入通用自主 Agent framework；相关框架取舍见 [ADR 0001](../adr/0001-deterministic-event-sourced-abm-mvp.md)。
- 用户真实观测字段、合成 latent attributes 和研究解释边界见 [锦江用户数据结构](jinjiang-user-profile-data-structure.md)。
