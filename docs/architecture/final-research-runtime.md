# Final Research 30 批次 Runtime

Status: Architecture Note

本说明记录锦江 Final Research 的 mocked/live provider 运行路径。它建立在[离线基线](final-research-offline-baseline.md)之上，复用同一个公开 Interface：

```python
FinalResearchRunner(config: FinalResearchConfig, decision_adapter: LLMDecisionAdapter)
    .run_and_write(output_dir) -> Path
```

当前 writer 的版本矩阵为：

| lineage | payload/users | runtime | diagnostics | Prompt | 发布状态 |
|---|---|---|---|---|---|
| Historical Network-Augmented v3 | `payload-v3` / `users-v3` | `final-research-ranking-runtime-v2` | `ranking-diagnostics-v1` | Prompt v2 | 历史只读 |
| Seed-First Validation v4 | `payload-v4` / `users-v4` | `final-research-ranking-runtime-v2` | `ranking-diagnostics-v1` | Prompt v2 | 历史 Validation |
| Jinjiang v5 | `payload-v5` / `users-v5` | `final-research-ranking-runtime-v3` | `ranking-diagnostics-v2` | Prompt v3 | Validation expand 或 human-authorized Formal release |

v5 同时持久化 aggregate 与 Decision evidence。rule-based、缓存命中和 injected deterministic/mock client 使用 `ranking-v5-expand-evidence-v1`、`validation_run` 和 `production_deploy_eligible=false`。只有 `live_provider` 且本次 run 实际发出外部 request 时，writer 才生成 `ranking-v5-formal-evidence-v1`、`persisted_seed_first_formal_run` 和 `production_deploy_eligible=true`。两条路径都使用 `final-research-decision-execution-evidence-v1`，集中记录实际 Adapter chain、row-derived source/action/终态计数、安全 Provider metadata、真实 request invocation 和退化标记。

reader 继续只读兼容三种历史 v5 expand lineage：#75 的 aggregate/Decision 双 `pending`、#76 的 aggregate `persisted` + Decision `pending`，以及 #77 的双 `persisted`；同时接受新的 formal lineage。未声明的 aggregate `pending` + Decision `persisted` 和非 live Decision 塞入 formal envelope 等交叉组合都失败关闭。历史 Formal Decision + expand envelope 仍可只读重建，但不能通过 v2 release gate。任何 persisted Decision 阶段都必须从同 run 的 Decision/action/outcome/failure rows 复算并交叉验证，Provider metadata 也必须通过既有 allowlist 与脱敏自校验。

## Formal release contract 与 deploy gate

`validate_release(...)` 保持唯一 release-validation Interface。它按 `schema_version` 精确分流：历史 `abm-report-release-contract-v1` 仍可用于本地验证既有 v4 Validation evidence；`abm-report-release-contract-v2` 固定 `release_purpose=formal_research`，只接受完整 v5 Formal tuple。v2 会先执行只读 ranking reader，再交叉核对 sampling、Prompt、Decision source/action/终态计数、退化标记、raw holdout reference、manifest/download coverage，并要求 source directory 只包含目录和 regular file、全部文件恰好由 manifest 声明，且每个 artifact 连同 `artifact_manifest.json` 都有匹配 SHA-256。校验过程不会重建或改写报告。

production deploy Interface 为：

```bash
scripts/deploy_abm_report.sh \
  --contract configs/deployments/<authorized-formal-contract>.json \
  --source-dir runs/<authorized-formal-run> \
  --release-id <release-id>
```

`--contract` 必须是仓库内安全、非 symlink 的 regular file。deploy 先复制随机本地 snapshot，保留原始 source identity 检查，但对 snapshot 执行完整 v2 validation；之后的 local hash 和 tar upload 只读取同一个只读 snapshot，避免 validation 与上传之间的 source mutation。任何 snapshot 校验失败都会在第一次 `ssh`、上传、容器或远程配置动作前拒绝 v1、Validation、rule-based、mock-provider、source mismatch、hash/path/symlink 或 schema crossing。通过本地 gate 后，既有 candidate health check、宿主检查、原子 `current` 切换、public acceptance 和失败恢复上一 release 的流程保持不变。

Ralph-ready implementation、`ready-for-agent` label 和本地 synthetic persisted Formal fixture 都不构成 live 或 production 授权。后续 human-gated operational Ticket 必须分别记录 Provider、模型、预算上限、独立输出目录和 canonical deployment 授权；本地 fixture 只验证合同与 deploy guard，不得描述为真实 live run。

`provider.enabled=false` 时仍只执行离线评分和 Holdout Diagnostic，不调用 Decision Adapter。`provider.enabled=true` 时配置必须使用 `horizon=30`、`fail_closed_action=raise` 和 `jinjiang-green-marketing-prompt-v3`。具体 runtime 由 `research_model` 显式选择：

- `target_delivery_ranking_v2`：单目标视频全局 Top20 投放排序；
- `probability_v1`：保留历史固定分批概率抽签语义。

两个模型使用不同 manifest version 和 artifact contract，不能互相重建或静默转换。

## Target Delivery Ranking v2

- Batch 0 只强制曝光 Seed-First Research Sample 的 Full-Pool Influence Seed Union。
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

OpenAI-compatible Adapter 使用单调 external request invocation counter，只在非注入 SDK client 即将调用 `create_response` 时递增；配置解析、SDK client 构造、injected client 调用和缓存命中不会改变计数。Final Research evidence builder 在每次 run 前记录 baseline，并只以本次 run 的正向 delta 生成 `live_api_triggered=true`，因此复用曾执行 live request 的 cached Adapter 不会把后续全缓存 run 误报为 Formal。builder 只登记 exact `RuleBasedDecisionAdapter`、`OpenAICompatibleDecisionAdapter` 与 `CachedDecisionAdapter` wrapper；未知 leaf、未知 wrapper 或 wrapper cycle 在 runtime 前失败关闭，不通过类名或任意 `wrapped` 属性推断。

Decision evidence 只从 canonical persisted rows 聚合，并验证 `sample_users = exposed_users + below_delivery_capacity`、`exposed_users = decided_users + provider_failed`、`decided_users = sum(action_counts)`。每个成功 Decision 必须与唯一 action row 和 outcome 一致；`decision_source_counts` 只读取 Decision rows。`all_decisions_ignore`、`single_action_only` 与 `no_engagement_feedback` 只描述退化事实，不触发重跑、补造 action 或 Formal validity 筛选。

Holdout Set 在 optional runtime 全部完成后才通过 `_ResearchInputBuilder.reveal_holdout()` 一次揭示。该私有 typed return 同时携带 holdout comments 与目标 `videos.csv` 行的 raw aggregate reference；四个 count 在此之前不进入 `PreparedInputs`、`TargetVideo`、Prompt、DecisionInput、Sampling 或 Ranking evidence。揭示失败时 run 失败关闭，不写出伪造 reference。

## Runtime Artifacts

`target_delivery_ranking_v2` 在离线基线 artifacts 之外写出：

- `ranking_runtime_steps.csv`：30 个批次的 eligible、候选、Top20、决策、参与、忽略、失败和当轮 capacity 计数；
- `ranking_runtime_candidates.csv`：每轮全部候选的稳定排名、三项分数和 Top20 选择结果；
- `ranking_runtime_outcomes.csv`：每个样本用户唯一的最终投放或 `below_delivery_capacity` 状态；
- `runtime_decisions.csv`：成功返回的结构化决策；
- `runtime_actions.csv`：`like/comment/share/ignore` action 流；
- `runtime_provider_failures.csv`：重试耗尽后的用户级安全失败记录；
- `ranking_runtime_summary.json`：sampling method/status/role counts、调度方法、Top20 容量、公式，以及与 manifest/payload 同源的 execution mode、Decision source/action/终态计数、安全 Provider metadata、live fact 和退化标记；
- `field_lineage_catalog.json`：覆盖当前 ranking report 全部 allowlisted 可见字段的全局定义，只保存一次 provenance、source fields、transformation、Declared Usage Stage 和限制，并按本次 catalog 与用户 trace 动态记录 value status coverage audit；
- `user_field_trace.json`：per-user field trace index，覆盖 catalog 中以 `user_id` 为记录键的画像、ranking candidate、Decision、provider outcome、传播反馈和 diagnostics 字段，保存 value status、复合 locator、必要 evidence、Actual Usage Stage、Prompt inclusion 和 omission reason；
- `field_source_records.json`：由 `user_id` 定位的 allowlisted 标签来源快照、必要 hashtag/text evidence 与派生代理聚合输入，不保存 raw Prompt 或 Provider Payload。

新运行同时写出 `seed_first_sample_audit.json`。旧正式 run 保留 `network_augmented_sample_audit.json`，并在报告中标记为 Historical Network-Augmented Run；新 offline/mock 输出标记为 Validation Run。Validation Run 不表示已经执行 live provider 正式运行。只有单独授权且实际触发外部 request 的新 run 才使用 Formal sampling status；本地实现 Ticket 不构成 live 授权或 production deployment 授权。

新 v5 manifest 使用 `final-research-ranking-runtime-v3`；冻结的 v3/v4 reader 继续要求 `final-research-ranking-runtime-v2`。这些 runtime artifacts 不包含 `random_draw`、概率曝光语义、背景视频 impression 或 `background_content`。

### 排名消融与权重敏感性

Target Delivery Ranking 主运行完成后，Runner 把 `ranking_runtime_candidates.csv` 对应的逐批候选证据视为冻结输入，交给 `RankingDiagnostics` Module。该 Module 对每个批次复用完全相同的 candidate set、eligible 口径和主运行已经观测到的历史互动状态，只重新计算排序：

- paired full ranking 使用预声明的 `50/30/20` 权重；
- paired no-network shadow ranking 使用 `0/0/100`，移除两项评论网络贡献；
- 最小敏感性只比较主方案 `50/30/20`、网络较弱 `40/20/40` 和无网络 `0/0/100`。

Shadow ranking 是持久化证据上的纯计算诊断，不调用 Decision Adapter，不推进第二套用户状态，也不表示完整反事实 ABM trajectory。每批报告 full/no-network Top20、overlap、network-added、network-removed 和 `network_rank_delta = no_network_rank - full_rank`；正值表示网络信号改善了用户在 full ranking 中的位置。

诊断同时区分：

- Recommendation Signal Inclusion：网络权重进入主公式；
- Observed Recommendation Signal Effect：在同批冻结证据上移除网络后，至少一个 Top20 投放选择发生变化。

如果网络进入公式但全部批次的 Top20 均未变化，summary 必须明确记录零 observed effect。历史 Top20 在 holdout-safe 排名完成后揭示目标参与者交集、信号覆盖和 `target_aggregate_engagement_reference`。该 nested reference 固定记录 `source_artifact=videos.csv`、目标 `video_id`、`like_count/comment_count/share_count/collect_count` 以及曝光分母、用户级归属和 action 互斥性限制；它只提供 raw 背景，不构成生产推荐准确率、action benchmark 或校准依据。

新增 artifacts：

- `ranking_diagnostics.json`：逐批 paired ablation、三组敏感性、历史 Top20 限制、从 `top20_holdout_diagnostic.json` 原样转发的 nested aggregate reference 和同源 summary；
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
- 新的 `target_delivery_ranking_v2` runtime 使用 `final-research-ranking-report-payload-v5`、`final-research-ranking-users-v5` 和 `RankingUserReportRowV5`，表达 Seed-First Research Sample、逐轮 ranking evidence、目标曝光、`below_delivery_capacity`、provider 结果、排名诊断和 User Field Trace；历史 v3/v4 合同继续只用于既有 run rebuild。

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
payload 和 manifest 相对链接。CSV 每行和用户 JSON 顶层也记录回链路径。历史 v1-v4 合同保留各自
冻结的用户 allowlist；v5 只展示历史互动 hashtags、观测代理指标、latent 实验标签和仿真结果，
不再展示锦江兴趣占位字段。请求敏感材料、源站原始响应和旧 demo preset 字段不会进入 payload。

### Ranking payload v5

当前 Ranking v5 从 `seed_first_sample_audit.json`、逐轮 candidates/steps/outcomes、provider decisions/actions/failures、ranking diagnostics 和 field trace artifacts 构建，并显式保存 sampling method/status、角色计数和 validation-expand evidence state。它不包含锦江 `interest_tags`；`historical_tags` 仍保持独立 Ranking evidence。payload 同时包含：

- Base Sample、seeds、Network Cohort、普通用户替换、最终样本和 Base/final 两套 source-scope 分布；
- 每轮完整 candidate 排名、score components、eligible count、Delivery Capacity、selected users、动态网络激活、provider/action 计数和最终 `below_delivery_capacity`；
- 完整用户 allowlist，包括 sample role、最新或曝光轮 ranking evidence、provider 状态、action、confidence 和 reason；
- 完整 Decision execution evidence，包括登记的 Adapter chain、execution mode、row-derived source/action/terminal counts、live fact、sampling status 和三项退化标记；
- 与 `Prompt Field Summary` 共用字段常量的 Prompt contract，ranking/network/holdout 字段明确不进入 Prompt；
- 完整 paired ablation、三组 weight sensitivity、historical Top20 diagnostic、同源 diagnostics summary，以及只在 diagnostics 区域展示的目标视频 raw aggregate reference；
- 覆盖 TargetVideo、run、sample comparison、round/candidate、diagnostics 和全部用户导出研究字段的 Field Lineage Matrix，每个字段恰好一个 Field Provenance，并至少声明一个 Field Usage Stage；
- 全部 allowlisted 可见字段的 Field Lineage Catalog，以及全部 `user_id`-keyed 字段的 per-user trace。直接观测字段定位 `sample_manifest.json`，历史标签保留独立 evidence，派生代理记录 method 与实际聚合输入，合成字段记录 spec id、method 和 seed；ranking/Decision/provider/diagnostics 定位同 run 的 runtime artifacts。`like/comment/share` 只记录下一批仍 eligible 的直接邻居信号，`ignore` 明确记录不传播；Prompt inclusion 来自实际 Prompt Field Summary 路径，ranking 与网络证据始终 `not_allowlisted`。

Ranking v5 的基础 `report.html` 可通过 `file://` 打开，展示真实 TargetVideo、运行漏斗、样本角色、字段血缘、完整用户表和同源下载链接。Decision 区域展示 execution mode、live fact、source/action/terminal counts、退化标记及其非筛选语义，并持续区分 Target Delivery Ranking 与曝光后 Decision；v5 下载合同复用既有 decisions/actions/failures/outcomes/summary artifacts，不创建第二份 evidence artifact。现有 diagnostics 区域用一张紧凑表格展示 aggregate source、record key、四个 raw counts 和不可比较限制，不计算比例、距离、真实性评分或 action quality gate，也不增加 aggregate 下载项。统一右侧详情抽屉在用户字段展开后组合 catalog 与 trace，显示 artifact、相对路径、记录键、source fields、transformation、Declared/Actual Usage、Prompt inclusion 和限制。用户 CSV 每行包含 report/payload/JSON/manifest 回链；HTML 的 artifact 路径按属性值转义。页面、搜索和详情不包含已撤销字段，也不显示概率抽签或背景内容术语。

历史 Ranking v3 只读取 Historical Network-Augmented 合同：`final-research-ranking-report-payload-v3`、`final-research-ranking-users-v3`、`final-research-ranking-runtime-v2`、`ranking-diagnostics-v1`、`jinjiang-green-marketing-prompt-v2` 与 `network-augmented-sample-audit-v1`。Seed-First v4 固定使用 v4 payload/users、同一历史 runtime/diagnostics/Prompt token 与 `seed-first-sample-audit-v1`，并要求包含历史字段的 catalog、trace 和 source-record artifacts。v5 只接受 payload/users v5、runtime v3、diagnostics v2、Prompt v3、Seed-First audit 和相同 artifact set 的完整 tuple；sampling status 必须与 persisted Decision evidence 的 actual live fact 一致。三个 reader 使用各自冻结的用户、payload、audit 和精确 artifact-set 合同；任意未知、缺失或交叉组合在模型解析前失败关闭。v3/v4 重建不会迁移成 v5 或覆盖历史 artifacts。

## Explainable payload v2 与报告重建

`FinalResearchRunner.run_and_write` 和已有 run 的重建路径共用同一个报告 payload builder、HTML renderer
和原子发布 Implementation。公开重建 Interface 为：

```python
rebuild_final_research_report(run_dir) -> Path
```

历史 v1/v2 重建继续使用 `artifact_manifest.json`、`final_research_report_payload.json` 和 `runtime_summary.json`。Ranking rebuild 联合校验 payload、users、runtime、diagnostics、Prompt 和 sample-audit schema token，以及精确 artifact set 后，才分流到冻结的 v3、v4 或 v5 reader；不存在 fallback。reader 随后交叉校验 sample audit、ranking steps/candidates/outcomes、ranking runtime summary、diagnostics summary、用户 CSV/JSON 和下载路径。v5 aggregate `persisted` 阶段要求 `top20_holdout_diagnostic.json` 中的 authoritative reference 与 diagnostics/payload 转发值完全一致且目标 `video_id` 匹配；aggregate `pending` 阶段要求三处都不存在该 reference。Decision `persisted` 阶段重新读取 decisions/actions/outcomes/failures，复算 source/action/terminal counts 与退化标记，并与 summary、manifest、payload 交叉验证；Decision `pending` 阶段保留冻结的历史下载合同和报告语义。v3/v4/v5 各按自身阶段校验 catalog、trace、source records 与 manifest locator。所有路径都不会运行仿真或调用 Decision Adapter。

输入 payload 可以是 v1 或 v2，输出统一为确定性的 `final-research-report-payload-v2`。v2 在既有用户
allowlist 和聚合图表之外，加入实际数字漏斗、方法阶段、视频用途、source-scope 抽样说明、评论派生
网络、推荐公式与抽签示例、固定批次、结构化决策合同、动作计数解释、动态邻居摘要和用户决策追踪。
用户追踪只标记为“重建的决策上下文”；未持久化的完整 `PeerContext` 和原始 Provider Prompt 明确
不可恢复。

发布前会交叉校验 schema、用户唯一性、样本/seed/summary/manifest 计数、字段血缘和全部下载目标。payload 与
HTML 都先写入同目录临时文件并完成验证，再先替换 payload，最后替换自包含 `report.html`。因此
`report.html` 仍是报告发布完成标志，用户 CSV/JSON、manifest 和既有决策值不会被重建修改。
