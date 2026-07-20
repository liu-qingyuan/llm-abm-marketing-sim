# ADR 0003: 先选种子及评论网络邻居再补足研究样本

Status: Accepted

现行正式 run 先按来源分组抽取 1,000 人 Base Sample，再从其中选种子、加入种子的历史评论网络邻居并替换等量普通用户。该方法保留了原始分组样本对照，但主流程难以直观说明，而且种子及其邻居受先前 Base Sample 的候选范围限制。

目标方法改用 Seed-First Research Sample：从全部合格 processed users 中继续使用原有种子逻辑，即 Global Influence Proxy Top10 与 Local Influence Proxy Top10 取去重并集；再纳入这些种子在排除目标视频互动的锦江历史评论网络中的全部直接邻居。每位用户按其历史评论和回复次数最多的 Primary Video Source Scope 归组，多个 scope 并列时按稳定来源顺序决定。种子和邻居先计入各自分组配额，再从其他真实用户中按分组固定随机抽样补齐不足分组，直到总量达到 1,000 人。如果种子邻居超过剩余容量，优先保留与种子历史互动关系最强的用户。按当前数据离线投影，两个 Top10 无重叠，形成 20 位种子、60 位直接邻居和 920 位普通补足用户。

该选择牺牲了 Base Sample 前后替换对照，换取更直接的样本叙事，并确保与种子真实相连的用户进入后续 Global Reranking。它只确保评论网络权重和相关性有产生可观测影响的机会；网络是否真正改变 Top20 仍由 Paired Network Ranking Ablation 判断。Seed-First Research Sample 不得描述为总体代表性随机样本。

此 ADR 不改写现行正式 run 的历史口径。`seed_first_research_sample_v1` 已通过 offline/mock E2E、holdout-safe fixture 和当前 processed dataset 的只读 audit；当前数据由算法实际得到 20 位 seeds、60 位直接邻居和 920 位普通补足用户。该结果不是 Implementation 常量。

接受本 ADR 只表示抽样 Implementation 与离线验证证据已经落地，不表示已经执行新的 live provider 正式运行。旧正式 run 的 600 次决策和网络影响结果继续属于 Historical Network-Augmented Run，不能迁移为 Seed-First 结果；新的正式 Decision 与 diagnostics 仍须在用户单独授权后写入独立 run。
