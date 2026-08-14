# ADR 0007: 采用增量全池主实验并保留历史敏感性

Status: Accepted

下一版主实验使用全部 36,400 位合格用户、现有三条 message 和固定 30 batches。每条 message 每批最多曝光 1,214 个剩余 pairs，最后一批为 1,194；109,200 个 pairs 各执行一次 Primary Decision，不执行新 Shadow。现有 ranking、single exposure、full-batch barrier 和正向 Primary 的 next-batch feedback 保持不变，因此排序只决定曝光次序。

Formal Run 使用 Pi `openai-codex` subscription、单一 `gpt-5.6-sol` 和现有 P0 low-reasoning request contract。运行上限为 109,200 logical judgments 和 120,120 physical attempts，subscription billed cost 必须为 USD 0，API-equivalent nominal cost 只作审计；达到上限时保留 `resumable` evidence。输出 identity 使用 `jinjiang-concurrent-full-pool-formal-v1-gpt-5.6-sol-<UTC>`，operational、Formal source 和 report candidate 相互独立。

新网页以全池 Formal evidence 为主区，原样保留历史 1,000-user Primary–Shadow、19-point Ranking Weight 和 `4 × 4` Prompt–Model sensitivity，并明确各自分母与 lineage。机制展示只新增一张 `full-pool-mechanism.mmd` 端到端总图；现有五张主图、`real-batch-mechanism.mmd`、Prompt–Model factorial、immutable v7 和历史 artifacts 均不覆盖、不重跑。本 ADR 记录目标合同，不授权当前会话执行 Provider、实现或部署。

## Rejected alternatives

- `Top20 × 30`：只能扩大 ranking 分母，不能让全部 pairs 曝光。
- Top20 扩展为 1,820 batches：违反固定 30-batch 边界。
- 全池重跑 Shadow 或 sensitivity：不影响核心传播机制，却显著增加调用量。
