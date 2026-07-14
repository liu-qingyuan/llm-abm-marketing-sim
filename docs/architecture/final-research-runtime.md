# Final Research 30 批次 Runtime

Status: Architecture Note

本说明记录锦江 Final Research 的 mocked/live provider 运行路径。它建立在[离线基线](final-research-offline-baseline.md)之上，复用同一个公开 Interface：

```python
FinalResearchRunner(config: FinalResearchConfig, decision_adapter: LLMDecisionAdapter)
    .run_and_write(output_dir) -> Path
```

`provider.enabled=false` 时仍只执行离线评分和 Holdout Diagnostic，不调用 Decision Adapter。`provider.enabled=true` 时配置必须使用 `horizon=30`、`fail_closed_action=raise` 和 `jinjiang-green-marketing-prompt-v2`。具体 runtime 由 `research_model` 显式选择：

- `target_delivery_ranking_v2`：单目标视频全局 Top20 投放排序；
- `probability_v1`：保留历史固定分批概率抽签语义。

两个模型使用不同 manifest version 和 artifact contract，不能互相重建或静默转换。

## Target Delivery Ranking v2

- Batch 0 只强制曝光 Base Sample 选出的 seed union。
- Batch 1 至 29 每轮对全部尚未曝光的 eligible users 全局重排，选择稳定 Top20；相同分数按 `user_id` 打破平局。
- 用户实际曝光后，无论 `like/comment/share/ignore` 或 `provider_failed` 都永久离开 eligible 集合。
- 未进入当轮 Top20 的用户保留后续资格；30 批次结束仍未曝光时记录 `below_delivery_capacity`。
- 每个批次先冻结全部候选分数，再执行该批次 Decision Adapter 调用，最后统一提交成功互动，因此同批用户互不影响。
- Batch 0 最多 20 个 seeds，后续 29 批每批最多 20 人，总曝光和 Adapter task 上限为 600。

主排序公式为：

```text
engaged_neighbor_signal = min(1, engaged_neighbor_count / 3)

recommendation_score
= 0.50 * base_network_relevance
+ 0.30 * engaged_neighbor_signal
+ 0.20 * historical_tag_affinity
```

`engaged_neighbor_count` 只统计此前批次成功执行 `like/comment/share` 的 Historical Set 直接邻居。`ignore` 与 `provider_failed` 不传播。排序证据不进入 Final Research Prompt；Runner 通过现有 Decision Adapter Interface 传入中性 `PeerContext`。

## Probability v1 历史合同

- seed users 按稳定顺序在第 0 批次强制曝光。
- 其他样本用户使用固定随机种子打乱，再以 round-robin 方式分配到第 1 至 29 批次。
- 每个批次在批首冻结直接邻居状态、动态分数和 `PeerContext`，批末再统一提交该批次的曝光与参与；同批用户不会相互影响。
- 每个样本用户只生成一条 exposure event；非 seed 用户只抽签一次。
- `recommendation_score` 只与随机数比较，不参与用户排序。
- 抽签失败记录 `background_content`，不调用 Decision Adapter。

## 动态直接邻居反馈

平台使用 Historical Set 中 `source_challenge_name=锦江酒店` 的评论派生用户图：

```text
dynamic_network_score
= min(1.0, base_network_score + neighbor_boost * engaged_direct_neighbor_count)

recommendation_score
= network_weight * dynamic_network_score
 + tag_affinity_weight * historical_tag_affinity
```

只有 `like`、`comment`、`share` 会记录为参与并提升尚未处理的直接邻居；三种 action 的提升相同。`ignore`、背景内容和 `provider_failed` 不改变邻居参与状态。

## Decision Adapter 与失败语义

Runner 把 `TargetVideo` 投影为 `PostContent`，继续调用既有：

```python
decide(post, profile, peer_context, platform_context, time_step)
```

Provider Adapter 内部执行最多 5 次指数退避重试。`retry_backoff_seconds` 是退避基数，第 N 次重试前等待 `base * 2**N`；测试可以注入 sleeper 以避免真实等待。重试耗尽后 Adapter 抛出 `ProviderDecisionError`，Runner 只记录原始失败类型和安全 provider metadata，不保存异常消息或 raw payload，并继续处理后续用户。配置错误、live gate 错误和其他未标记的 Adapter 异常会终止 run，不会伪装成用户级 provider failure。

Holdout Set 在全部 runtime 完成后才揭示，仍只用于 diagnostic 和对照。

## Runtime Artifacts

`target_delivery_ranking_v2` 在离线基线 artifacts 之外写出：

- `ranking_runtime_steps.csv`：30 个批次的 eligible、候选、Top20、决策、参与、忽略、失败和当轮 capacity 计数；
- `ranking_runtime_candidates.csv`：每轮全部候选的稳定排名、三项分数和 Top20 选择结果；
- `ranking_runtime_outcomes.csv`：每个样本用户唯一的最终投放或 `below_delivery_capacity` 状态；
- `runtime_decisions.csv`：成功返回的结构化决策；
- `runtime_actions.csv`：`like/comment/share/ignore` action 流；
- `runtime_provider_failures.csv`：重试耗尽后的用户级安全失败记录；
- `ranking_runtime_summary.json`：调度方法、Top20 容量、公式、provider 安全 metadata 和聚合计数。

v2 manifest 使用 `final-research-ranking-runtime-v2`。这些 runtime artifacts 不包含 `random_draw`、概率曝光语义、背景视频 impression 或 `background_content`。

### 排名消融与权重敏感性

Target Delivery Ranking 主运行完成后，Runner 把 `ranking_runtime_candidates.csv` 对应的逐批候选证据视为冻结输入，交给 `RankingDiagnostics` Module。该 Module 对每个批次复用完全相同的 candidate set、eligible 口径和主运行已经观测到的历史互动状态，只重新计算排序：

- paired full ranking 使用预声明的 `50/30/20` 权重；
- paired no-network shadow ranking 使用 `0/0/100`，移除两项评论网络贡献；
- 最小敏感性只比较主方案 `50/30/20`、网络较弱 `40/20/40` 和无网络 `0/0/100`。

Shadow ranking 是持久化证据上的纯计算诊断，不调用 Decision Adapter，不推进第二套用户状态，也不表示完整反事实 ABM trajectory。每批报告 full/no-network Top20、overlap、network-added、network-removed 和 `network_rank_delta = no_network_rank - full_rank`；正值表示网络信号改善了用户在 full ranking 中的位置。

诊断同时区分：

- Recommendation Signal Inclusion：网络权重进入主公式；
- Observed Recommendation Signal Effect：在同批冻结证据上移除网络后，至少一个 Top20 投放选择发生变化。

如果网络进入公式但全部批次的 Top20 均未变化，summary 必须明确记录零 observed effect。历史 Top20 只保留 holdout-safe 排名完成后揭示的目标参与者交集和信号覆盖，并声明正样本稀疏、缺少真实曝光分母以及不构成生产推荐准确率。

新增 artifacts：

- `ranking_diagnostics.json`：逐批 paired ablation、三组敏感性、历史 Top20 限制和同源 summary；
- `ranking_diagnostics_summary.json`：Signal Inclusion、Observed Effect、批次数和诊断行数；
- `ranking_ablation_diagnostics.csv`：逐用户 full/no-network rank、selection effect 和三项冻结分数；
- `ranking_weight_sensitivity.csv`：逐批逐方案的 Top20、与主方案 overlap 及 added/removed users。

四个路径和对应计数由 `artifact_manifest.json` 登记；诊断阶段的 `diagnostic_decision_adapter_calls` 固定为 `0`。

`probability_v1` 继续写出：

- `runtime_steps.csv`：30 个批次的分配、曝光、决策、参与、忽略和失败计数；
- `runtime_exposures.csv`：每个样本用户唯一的一次机会及其动态分数、抽签和结果；
- `runtime_decisions.csv`：成功返回的结构化决策；
- `runtime_actions.csv`：`like/comment/share/ignore` action 流；
- `runtime_background_events.csv`：未展示目标视频的背景内容占用；
- `runtime_provider_failures.csv`：重试耗尽后的用户级安全失败记录；
- `runtime_summary.json`：调度方法、公式、provider 安全 metadata 和聚合计数。

v1 manifest 使用 `final-research-runtime-v1` 并登记以上路径。默认测试通过注入 mocked provider 运行，不读取凭证、不访问 `data/raw`、不触发 live API。

## Final Research 报告合同

全部研究模型在 artifacts 完成后调用内部 `FinalResearchReportWriter`，但使用两个互不转换的报告合同：

- 离线基线与 `probability_v1` 使用 `final-research-report-payload-v2` 和 `UserReportRow`，保留概率抽签、`random_draw` 与 `background_content` 的历史语义；
- `target_delivery_ranking_v2` 使用 `final-research-ranking-report-payload-v3`、`final-research-ranking-users-v3` 和 `RankingUserReportRow`，只表达 Network-Augmented Research Sample、逐轮 ranking evidence、目标曝光、`below_delivery_capacity`、provider 结果和排名诊断。

两个合同都隐藏在 `FinalResearchReportWriter` Module 内，不扩展通用 `ReportPayload`、`build_report_payload` 或全局 `safe_data` Interface。Writer 在 HTML、CSV 和 JSON 成功写出后最后写 `artifact_manifest.json`，避免 manifest 指向未完成的报告文件。

以下报告记录只适用于离线基线与 `probability_v1` 历史 artifacts。

每个样本用户恰好生成一条报告记录。runtime 启用时，记录合并唯一 exposure、成功 decision
或 provider failure；runtime 未启用时显式使用 `runtime_not_run`。统一 `result_status` 区分：

- `like`、`comment`、`share`、`ignore`；
- `background_content`；
- `provider_failed`；
- 防御性状态 `missing_decision`；
- 离线状态 `runtime_not_run`。

报告 writer 新增并由 `artifact_manifest.json` 登记：

- `report.html`：可直接以 `file://` 打开的静态研究页面，内嵌 payload 和交互逻辑；
- `final_research_report_payload.json`：独立页面 payload、聚合图表数据和完整用户记录；
- `final_research_users.csv`：全部样本用户的 allowlisted 明细；
- `final_research_users.json`：与 CSV 同批、同字段的完整用户记录和互链信息。

HTML 提供搜索、result/source scope/seed 筛选、用户时间线、桌面与移动布局，以及 CSV、JSON、
payload 和 manifest 相对链接。CSV 每行和用户 JSON 顶层也记录回链路径。页面只展示 processed/runtime
允许字段，包括清洗后的 `interest_tags`、历史互动 hashtags、观测代理指标、latent 实验标签和
仿真结果；请求敏感材料、源站原始响应和旧 demo preset 字段不会进入 payload。

### Ranking payload v3

Ranking v3 从 `network_augmented_sample_audit.json`、逐轮 candidates/steps/outcomes、provider decisions、provider failures 和 ranking diagnostics 构建。payload 同时包含：

- Base Sample、seeds、Network Cohort、普通用户替换、最终样本和 Base/final 两套 source-scope 分布；
- 每轮 eligible count、Delivery Capacity、selected users、provider/action 计数和最终 `below_delivery_capacity`；
- 完整用户 allowlist，包括 sample role、最新或曝光轮 ranking evidence、provider 状态、action、confidence 和 reason；
- 与 `Prompt Field Summary` 共用字段常量的 Prompt contract，ranking/network/holdout 字段明确不进入 Prompt；
- 覆盖全部用户导出字段的 Field Lineage Matrix，每个字段恰好一个 Field Provenance，并至少声明一个 Field Usage Stage。

Ranking v3 的基础 `report.html` 可通过 `file://` 打开，展示真实 TargetVideo、运行漏斗、Base/final 样本对照、字段血缘、完整用户表和同源下载链接。它不显示概率抽签或背景内容术语。

## Explainable payload v2 与报告重建

`FinalResearchRunner.run_and_write` 和已有 run 的重建路径共用同一个报告 payload builder、HTML renderer
和原子发布 Implementation。公开重建 Interface 为：

```python
rebuild_final_research_report(run_dir) -> Path
```

历史 v1/v2 重建继续使用 `artifact_manifest.json`、`final_research_report_payload.json` 和 `runtime_summary.json`。Ranking v3 重建按 manifest version 分流，并交叉校验 sample audit、ranking steps/candidates/outcomes、ranking runtime summary、diagnostics summary、用户 CSV/JSON 和下载路径。两条路径都不会运行仿真或调用 Decision Adapter。

输入 payload 可以是 v1 或 v2，输出统一为确定性的 `final-research-report-payload-v2`。v2 在既有用户
allowlist 和聚合图表之外，加入实际数字漏斗、方法阶段、视频用途、source-scope 抽样说明、评论派生
网络、推荐公式与抽签示例、固定批次、结构化决策合同、动作计数解释、动态邻居摘要和用户决策追踪。
用户追踪只标记为“重建的决策上下文”；未持久化的完整 `PeerContext` 和原始 Provider Prompt 明确
不可恢复。

发布前会交叉校验 schema、用户唯一性、样本/seed/summary/manifest 计数、字段血缘和全部下载目标。payload 与
HTML 都先写入同目录临时文件并完成验证，再先替换 payload，最后替换自包含 `report.html`。因此
`report.html` 仍是报告发布完成标志，用户 CSV/JSON、manifest 和既有决策值不会被重建修改。
