# Project Context

本文件记录项目稳定领域语言。它只解释概念边界，不记录实现计划、任务拆分、验证步骤或架构决策。

## Glossary

### ABM Simulation

Agent-Based Modeling 仿真过程。系统在社交网络上按时间步推进曝光、观察、决策、行动和指标收集，用于研究营销内容如何扩散。

### Social User Agent

仿真中的社交媒体用户个体。它拥有可观测画像、偏好、邻居可见状态和当前曝光状态，并在每个相关时间步形成一次结构化互动决策。

### Platform Environment

仿真中的平台规则层。它负责决定用户是否看到内容、哪些邻居互动对用户可见，以及平台上下文如何影响传播机会。

### Decision Adapter

把帖子、用户画像、平台上下文和同伴影响转换为结构化决策的边界。Decision Adapter 可以由规则、缓存或显式启用的 provider 支持，但不负责调度仿真生命周期。

### Decision

用户代理在一次观察后的结构化输出。核心含义是是否互动、互动概率、动作、置信度和简短理由；它是仿真事件和指标的输入，而不是自由文本解释。

### Observed Profile Attributes

从数据源或派生统计中可观察到的用户画像属性。它们可以包括行为计数、互动网络代理指标或已记录的 profile 字段，但只能表达数据中可观测或可复算的事实与代理指标。

### Latent Attributes

为实验建模推断或分配的潜在用户属性。它们可以支持分组分析、价值偏好假设或决策输入扩展，但不等同于真实抖音用户身份、心理画像或第三方认证标签。

### Virtual Experiment Labels

为仿真实验构造的虚拟标签。它们用于比较实验组、解释模拟假设或驱动受控变体，不应被描述为真实采集字段或真实用户属性。

### Processed Variant

在既有数据基础上经过规范化、清理、补充或标签分配后形成的数据版本。Processed Variant 应保留来源口径、变换口径和限制说明，使后续仿真能够复现输入语义。

### Dataset Audit

对数据集口径、覆盖率、行数一致性、重复率、阶段状态和限制的聚合检查记录。Dataset Audit 用于说明数据是否适合某类使用，不展示用户明细或原始 payload。

### Live Provider Gate

显式启用真实外部 provider 的安全边界。默认开发、测试和示例运行应离线、确定性、无需凭证；只有通过 Live Provider Gate 时，才允许调用真实 LLM 或数据 provider。

### Douyin Data Collection Stage

抖音数据采集的阶段化工作单元。阶段之间应保持可解释边界，例如先建立可信视频分母，再决定是否采集评论、回复或用户画像。

### Provider Payload

发送给外部 provider 或从外部 provider 返回的数据载荷。Provider Payload 可能包含敏感上下文，文档和报告只应保留必要的聚合信息、schema 状态或脱敏证据。

### Documentation Navigation Contract

文档入口、职责目录和状态标记之间的导航约定。它保护读者能判断一份文档是领域语言、参考资料、架构说明、PRD、ADR 还是数据审计。
