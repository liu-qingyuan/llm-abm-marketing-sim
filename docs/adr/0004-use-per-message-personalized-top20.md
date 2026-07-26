# ADR 0004: 为并行营销 message 使用独立个性化 Top20

Status: Accepted

现有 ADR 0002 只为一条 Target Marketing Video 提供每批 Top20、30 批共 600 次投放。新的并行实验要求三条 Experimental Message Videos 各完成 600 次个性化投放，因此决定让每条 message 独立维护 `user × message` eligible queue 和 Per-Message Personalized Top20：同一用户对同一 message 最多曝光一次，但可以进入其他 message 的队列，使三个受众集合允许重叠。每条队列使用 `0.50 * base_network_relevance + 0.30 * campaign_engaged_neighbor_signal + 0.20 * normalized_message_user_fit`；Batch 0 向三条 message 使用同一个 Full-Pool Influence Seed Union，不足 Top20 时再分别按个性化分数补足；跨 message 的成功互动用户按 campaign 去重后只影响下一批 Ranking。

## Considered Options

- 三条 message 共享一个 Top20，并为每位用户只选择 Fit 最高的一条：保留严格共享容量，但 30 批只能形成 600 次总投放，不能满足每条 message 各 600 次。
- 固定同一批 600 位用户全部接收三条 message：满足 1,800 次总投放并便于配对比较，但取消每条 message 独立选择对应用户的个性化投放。
- 三条 message 使用互斥受众：在 1,000 用户样本中无法容纳 1,800 个互不重叠的 `user × message` exposures。

## Consequences

1,000 用户验证包含 3,000 个候选 pairs、1,800 个实际 exposures 和 1,200 个 Message-Level Below Delivery Capacity pairs；用户的 Campaign Exposure Coverage 可以为 0、1、2 或 3。每个实际 exposure 还形成一条 Primary Campaign Decision 和一条 report-only Demographic Shadow Decision，共 3,600 个逻辑 Decision opportunities。三个受众组由 Ranking 产生且可重叠，message 结果只能作描述性比较，不能声称真实世界文案因果胜负。

本 ADR 不修改或废弃 ADR 0002/0003，不迁移历史 Final Research v3-v6 artifacts，也不表示 runtime 已实现、真实 Provider 已授权或 canonical endpoint 已发布。多 message 实现和发布必须使用独立 additive Formal contract。
