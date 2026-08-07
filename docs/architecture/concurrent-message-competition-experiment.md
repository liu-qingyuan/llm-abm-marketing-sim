# Concurrent Message Competition Experiment

Status: Implemented and published architecture note
Current release evidence: [`../references/jinjiang-concurrent-message-editorial-v2-formal-release-20260807.md`](../references/jinjiang-concurrent-message-editorial-v2-formal-release-20260807.md)
Canonical endpoint: [`https://abm.q1ngyuan.top/`](https://abm.q1ngyuan.top/)

本文是当前三 message runtime、报告和发布边界的唯一 Architecture Note。它不替代 GitHub `Spec:` issue 的 executable requirements，也不授权新的 Formal Run、Provider 或 deployment。

## 当前实验合同

- 三条 Experimental Message Videos 从同一 Batch 0 发布边界开始，各自维护 `user × message` eligible queue。
- 每条 message 使用 Per-Message Personalized Top20，30 个 batch、每条 600 次 exposure；同一 pair 最多 exposure，同一 user 可以跨 message 重叠。
- Batch 0 使用共同的 Full-Pool Influence Seed Union；之后每条队列独立排序，完全同分按 `user_id` 稳定处理。
- Platform Environment 选择 exposure；Decision Adapter 只处理已曝光的 pair，并生成 Primary 与 report-only Demographic Shadow Decision。
- 成功 Primary 的 `like/comment/share` 用户按 campaign 去重，只影响下一批 ranking；`ignore`、`provider_failed` 和 Shadow 不传播。
- `Message-User Fit` 使用 message 六维 `0/1` vector 与用户 signed value weights 的 cosine similarity，并映射到 `[0, 1]`；Class 名称不是硬性 routing 条件。

当前首次 release 的固定研究边界为 1,000 sample users、3,000 eligible pairs、1,800 exposures 和 3,600 个 Primary/Shadow decision opportunities。结果是 descriptive simulation evidence，不构成真实世界文案的因果胜负或总体代表性结论。

## Ranking 与生命周期

每条 message 的候选排序使用完整精度的 Personalized Delivery Score：

```text
personalized_delivery_score
= 0.50 * base_network_relevance
+ 0.30 * campaign_engaged_neighbor_signal
+ 0.20 * normalized_message_user_fit
```

`base_network_relevance` 来自 holdout-safe Historical Set 评论图；`campaign_engaged_neighbor_signal` 在 Batch 0 为 0，只接收前一批成功 Primary 的 campaign-level 去重用户；`normalized_message_user_fit` 将 message 六维 value vector 与用户 signed value weights 的 cosine similarity 从 `[-1, 1]` 映射到 `[0, 1]`。每批三条队列先冻结 ranking/context，再分别选择最多 20 个 pairs；同批 Primary 全部闭合后，反馈才进入下一批，不能改变同批 Decision。

平台不会在曝光前为候选调用 LLM。每个实际 pair 只在 exposure 后形成 Primary 和配对 Shadow；pair 一旦曝光就从该 message queue 移除，但同一 user 仍可进入其他 message queue。

三条 message 的定义由 `src/llm_abm_sim/concurrent_message_experiment.py` 中的 `authoritative_message_definitions()` 提供；每个 run 把这组定义持久化为 `message_snapshot.json`，报告 rebuild 和 execution replay 都以该 snapshot 作为 message source of truth。Markdown 不再复制 message 文案或另建 alias；latent attributes 的研究先验由 [`../references/jinjiang-user-latent-attributes-reference-zh.md`](../references/jinjiang-user-latent-attributes-reference-zh.md) 持有。

## Module ownership

| Module / artifact | 当前职责 |
|---|---|
| `ConcurrentMessageExperimentRunner` | fresh/resume runtime、batch 调度、candidate/pair rows 和最终 source 组装 |
| `PlatformEnvironment` / ranking | 每条 message 的 candidates、delivery capacity、Top20、exposure gate 和稳定 tie-break |
| Decision Adapter | 对已曝光 `user × message` pair 生成 Primary/Shadow typed decisions；不选择 exposure |
| `ConcurrentCampaignDiagnostics` | 从 persisted candidate/pair rows 重建 funnel、allocation、response、feedback 和 sensitivity diagnostics |
| Report Module | typed closure、report payload、approved downloads、manifest 和 read-only rebuild |
| Editorial candidate | bilingual presentation grouping、五个 mechanism media derivatives、run evidence surface 和 canonical report bytes |
| Release validator/deploy | 显式 contract、source directory、release id、candidate health、atomic `current` 和公网验收 |

Diagnostics 的 source of truth 是同一 run 的 persisted candidate rows 与 pair rows。in-memory rows 在写出前会安全化，但不构成第二份事实来源；report writer 和 release validator 都会重新 rebuild 并比较 diagnostics、summary、schema tokens、manifest 与 approved artifact set。

## Report 与 durable execution

`rebuild_concurrent_message_report(run_dir, *, destination_dir=None)` 是报告 Module 的公开重建 Interface：

- in-place rebuild 先完成 typed artifact closure，再按 persisted source report hash 选择历史兼容 bytes；只替换 source 的 `report.html`，不重写 payload、runtime、diagnostics、downloads 或 manifest。
- explicit destination 在 source closure 完成后创建唯一 sibling staging，复制 canonical persisted views，用 Editorial default 生成 presentation，再重建 manifest 并 atomic rename。
- `explicit presentation destination 始终使用 Editorial default`；`in-place rebuild 仍按 persisted source report hash 选择历史兼容 bytes`。
- destination 必须原先不存在、与 source 不重叠、无 symlink/path escape 且同一 filesystem；失败时清理 staging，并保持 source 与 destination 不变。

运行状态分为四个 ownership 边界：

1. **private operational workspace**：identity、append-only journal、snapshot、lock 和 validated replay；永远不可 deploy。
2. **publish staging directory**：同一 run 的未公开 artifact set；不能跳过 closure 或 release contract。
3. **final source directory**：显式 runner output，包含 runtime rows、diagnostics、report、downloads 和 manifest；只有通过显式 Formal contract 才能进入 candidate deploy。
4. **canonical release**：使用明确 contract、source directory 和 release id 完成 candidate、health、atomic `current`、public acceptance 和失败回退。

普通 run 与 `contract-protected` Formal/release run 都遵守同一重建语义：前者可以删除后重建，后者仍必须按显式 contract 保留和验证；`contract-protected` Formal/release roots 不能仅按目录类型推断删除。workspace 或 staging 的存在不能替代 journal replay、source closure、release validation 或 deployment authorization。

## LLM visibility 与 evidence

Primary 只读取当前 message 原文、allowlisted observed profile 和 synthetic experiment fields：`activity_score`、`global_influence_score`、`local_influence_score`、environmental coefficient、六维 value weights、hotel class 和 travel purpose。Primary 不读取 `latent_class`、demographic labels、Ranking evidence、其他 messages、peer behavior、raw prompt 或 raw provider payload。

Primary 与 Shadow 的 PeerContext 保持中性；campaign ranking signal 只改变下一批投放顺序，不重新解释为用户实际看见的同伴行为。Shadow 只增加四个 report-only demographic labels，用于 paired sensitivity，不写入 action、ranking、feedback 或 runtime state。

报告必须分别展示 campaign funnel、message allocation、Primary response、campaign feedback effect 和 demographic sensitivity，并给出明确 numerator/denominator。受众 overlap 和 action rate 只能作 descriptive comparison，不生成 winner 或综合分数。

Canonical report 的 source/hash、model、budget、release id、rollback 和公网验收以三组 Formal evidence 为准：Original Formal、Two-mode rollback 和 Editorial Formal。代码、Validation/mock/rule-based artifact、`ready-for-agent` 状态和 issue 本身都不表示 production authorization。
