# ADR 0008: Full-Pool 主结果采用两阶段互动实现

Status: Accepted

Full-Pool Provider 输出首先解释为 **Provider Judgment**，不再自动等同已经发生的用户行动。决定在 Judgment 与 ABM feedback commit 的接缝加入单一 `Engagement Realization Module`：Provider `ignore` 不抽样且始终保持 `ignore`；只有 Provider 已选择 `like/comment/share` 时，ABM 才按持久化 probability、固定 seed `20260823` 和 source/user/message 稳定 key 实现该 action。draw pass 保留 Provider action，draw fail 变为 `ignore`。

Provider `reason/confidence` 继续只属于 Judgment provenance。ABM 不推断新 action，不为 Provider ignore补造 action，也不生成 `realized_reason`。进入指标和下一批 Campaign Engagement Ranking Signal 的集合改为 `realized_engage=true` 的 campaign-level 去重 users；同批全部 pairs 完成 realization 后才能跨过 full-batch barrier。

该决策 supersede ADR 0007 中“正向 Primary Provider Decision 直接成为行动并进入 feedback”以及“旧 Full-Pool 主结果只作增量呈现”的部分。新的 canonical 方向是以独立 immutable two-stage source、report 和 release替换 Full-Pool 主结果，而不是把旧 direct-action结果作为并排 sensitivity 主区。旧 Source-v4、v12 release和既有 canonical bytes保持 immutable；本 ADR 和 validation replay本身不构成 report promotion 或部署授权。

ADR 0004 的 Per-Message Ranking、独立容量、single exposure、cross-message overlap、campaign user去重与 next-batch-only barrier继续有效；其“成功 Primary”feedback consequence在 two-stage路径中具体解释为“成功实现的 positive action”。ADR 0007 的 36,400-user denominator、109,200 pairs、30 batches、每消息 1,214 / 末批 1,194 capacity和 Historical 1,000-User Sensitivity 保留。

## Considered Options

- **继续直接消费 Provider action**：实现简单，但把二元互动判断误写成已实现行动，并使 Full-Pool engagement接近饱和。
- **对全部 Judgment 直接按 probability 抽样**：会让 Provider `ignore` 获得虚构的 like/comment/share，破坏 action provenance。
- **按 Segment 缩放、封顶或选择不同 seed**：可以调整表面 rate，但引入结果导向校准，不能由现有证据支持。
- **固定旧 exposure schedule只做 sensitivity**：适合诊断，但不重建 realized feedback与后续 ranking trajectory，不能成为新的主结果。
- **修改 `EngageDecision` 为 realized contract**：会改变 Decision Adapter 与历史 artifacts语义，并把 Provider Judgment和ABM outcome混在同一字段层。

## Consequences

- `EngageDecision`、legacy direct-action callers、旧 Source-v4 与 v12 contract不变。
- realization key不绑定 upstream/replay batch、time step、遍历顺序或 completion order，同一 source/user/message outcome可逐字节复现。
- 新 persisted terminal必须同时保存 Provider Judgment和ABM Realization，并以 exact 24-field schema拒绝额外字段。
- Replay必须从 Batch 0重建 ranking；Provider ignore、draw fail和failure都不能进入 feedback。
- upstream Provider accounting与 realization zero-call accounting必须分栏，不能把复合 Formal误报为整体 zero-Provider。
- 新 source/report/release必须使用独立版本和 immutable identity；canonical cutover仍需要独立 operational authorization、原子 `current`切换和失败回退。
