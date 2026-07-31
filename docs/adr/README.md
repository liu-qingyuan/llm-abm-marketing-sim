# ADR

本目录保存难以逆转、存在真实替代方案且未来读者会疑惑其原因的 Architecture Decision Records。普通实现细节、Ticket 计划、一次性验证和当前代码 inventory 不在这里维护。

## Current ADR

- [ADR 0001: Deterministic Event-Sourced ABM MVP](0001-deterministic-event-sourced-abm-mvp.md)：确定性、事件溯源的自定义 ABM Core，以及显式 opt-in 的 Provider 边界。
- [ADR 0002: 使用目标投放排序替代概率曝光抽签](0002-use-target-delivery-ranking.md)：Network-Augmented Research Sample 与逐轮 Global Top20。
- [ADR 0003: 先选种子及评论网络邻居再补足研究样本](0003-use-seed-first-research-sampling.md)：Seed-First sample、直接邻居和普通用户补足方法。
- [ADR 0004: 为并行营销 message 使用独立个性化 Top20](0004-use-per-message-personalized-top20.md)：每条 message 独立 queue、Top20、single exposure 和允许 overlap。

新的 executable requirements 发布到 GitHub `Spec:` issue；当前行为和实现边界写入对应 Architecture Note。
