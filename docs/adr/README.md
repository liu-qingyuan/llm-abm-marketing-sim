# Architecture Decision Records

本目录保存 Architecture Decision Records（ADR）。

## 何时写 ADR

只有同时满足以下条件时才新增 ADR：

- 决策难以逆转，后续修改成本不低。
- 未来读者缺少上下文会疑惑为什么这样做。
- 存在真实替代方案，当前方案来自明确权衡。

## 不适合 ADR 的内容

- 普通任务拆分和 issue 计划。
- 可轻易改变的实现细节。
- 外部研究资料或数据审计。
- 单纯描述当前代码结构的说明文档。

## 当前 ADR

- [ADR 0001: Deterministic Event-Sourced ABM MVP](0001-deterministic-event-sourced-abm-mvp.md)：选择确定性、事件溯源、自定义 ABM MVP，并把真实 Provider 调用保留为显式 opt-in 边界。
- [ADR 0002: 使用目标投放排序替代概率曝光抽签](0002-use-target-delivery-ranking.md)：使用 Network-Augmented Research Sample 和逐轮全局 Top20 排序，使评论网络信号能够产生可观测的投放影响。
- [ADR 0003: 先选种子及评论网络邻居再补足研究样本](0003-use-seed-first-research-sampling.md)：接受从全部合格用户中先选影响力种子和其历史评论网络邻居，再按 Primary Video Source Scope 补足至 1,000 人的抽样方法；接受状态不代表已执行 live provider 正式运行。
- [ADR 0004: 为并行营销 message 使用独立个性化 Top20](0004-use-per-message-personalized-top20.md)：三条 message 各自完成每批 Top20、30 批 600 次个性化投放，使用 Message-Level Single Exposure 并允许受众重叠；不修改历史单视频 ADR 0002。
