# Concurrent Message Competition Experiment

Status: Implemented and published architecture note
Current release evidence: [`../references/jinjiang-concurrent-message-editorial-formal-release-20260729.md`](../references/jinjiang-concurrent-message-editorial-formal-release-20260729.md)
Canonical endpoint: [`https://abm.q1ngyuan.top/`](https://abm.q1ngyuan.top/)

本文记录“三个营销 message 同时投放”的目标领域行为、当前 runtime 覆盖和已发布报告边界。它保留设计 rationale，不替代 GitHub `Spec:` issue 的 executable requirements；新的 Formal Run、Provider 和 deploy 仍必须经过各自显式授权。

## 参考边界

- 三条文案原文及研究对象约定：[`../references/PostContent.md`](../references/PostContent.md)
- 当前单视频投放决策（历史合同）：[`../adr/0002-use-target-delivery-ranking.md`](../adr/0002-use-target-delivery-ranking.md)
- 当前 Seed-First 样本决策：[`../adr/0003-use-seed-first-research-sampling.md`](../adr/0003-use-seed-first-research-sampling.md)
- 多 message 独立个性化 Top20 决策：[`../adr/0004-use-per-message-personalized-top20.md`](../adr/0004-use-per-message-personalized-top20.md)
- 历史单视频 runtime 和报告合同：[`final-research-runtime.md`](final-research-runtime.md)
- 当前 Editorial release evidence：[`../references/jinjiang-concurrent-message-editorial-formal-release-20260729.md`](../references/jinjiang-concurrent-message-editorial-formal-release-20260729.md)
- 稳定领域语言：[`../../CONTEXT.md`](../../CONTEXT.md)

## 当前合同与目标设计

### 现有推荐逻辑

当前 `Target Delivery Ranking v2` 只处理一条固定的 Target Marketing Video。它的候选单位是 `user`，不是 `user × message`：平台只回答“下一批把这条目标视频推给哪些用户”，不回答“给这个用户选择哪条视频”。

平台使用 holdout-safe Comment-Derived User Interaction Graph 和目标视频历史标签计算排序：

```text
base_network_relevance
= min(1, log1p(historical weighted degree) / log1p(P95 degree))

engaged_neighbor_signal
= min(1, engaged direct neighbor count / 3)

historical_tag_affinity
= target video hashtags 与用户 Historical Set tags 的归一化交集

recommendation_score
= 0.50 * base_network_relevance
+ 0.30 * engaged_neighbor_signal
+ 0.20 * historical_tag_affinity
```

Batch 0 强制曝光 seed users；Batch 1-29 对全部尚未曝光用户全局重排，每批取 Top20，同分按 `user_id` 稳定处理。用户一旦曝光，无论 Decision 或 provider 结果如何，都从后续候选集中移除。1,000 人样本的理论曝光上限为 600，其余用户可结束为 `below_delivery_capacity`。

该模型没有 message 维度，不使用 `latent_class` 或 `PostContent.value_dimensions` 选择视频，也不是完整 Feed Ranking。若不新增 message-specific 候选与分数，三个 Experimental Message Videos 不会被自动分给不同人群。

现有历史 v3-v6 artifacts、Prompt token 和 release contract 保持冻结，不因本设计讨论而迁移或改写。

### 已确认的目标边界

目标设计改为一个 Concurrent Message Competition Experiment：

- `Message for Class 1/2/3` 是三个独立的 Experimental Message Videos；
- 三条原文保持不变，不补造视频、图片、音频、时长、发布时间或初始互动量；
- 三个视频从同一发布边界开始，各自运行 Per-Message Personalized Top20，每条每批最多曝光 20 个 eligible users；
- 同一用户可进入多条 message 的受众，但对同一 message 最多曝光一次；
- 平台负责每条 message 的个性化曝光选择，LLM 只对已经选定的 `user × message × exposure context` 返回结构化 Decision；
- Decision 继续包含 `engage`、`probability`、`reason`、`confidence` 和 `action: like/comment/share/ignore`。

“同一发布边界”表示三条 message 从 Batch 0 起同时进入各自队列，不按文案顺序获得先发优势。Batch 0 将同一个 Full-Pool Influence Seed Union 强制曝光给三条 message；若 union 少于 20，每条 message 再按自己的 Personalized Delivery Score 独立补足到 20。按当前数据 union 为 20 时，三条 message 的 Batch 0 用户集合完全相同，每位 seed 同时形成三个实际 `user × message` exposures。

每批三条队列的 Ranking 和上下文先冻结，再分别选择最多 20 个 pairs；同一用户可以在同批进入多条队列。该批最多 60 条 Primary Decisions 全部结束后，才把 `like/comment/share` 用户按 campaign 去重并提交下一批 Campaign Engagement Ranking Signal，同批 Decision 互不影响。

### 已确认的 Per-Message Personalized Top20

每条 message 独立维护 `user × message` 候选队列：

```text
eligible(user, message)
= user 尚未获得该 message 曝光

每个 batch：
Message 1 -> 自己的 personalized Top20
Message 2 -> 自己的 personalized Top20
Message 3 -> 自己的 personalized Top20
```

某个 pair 一旦曝光，无论 Primary Decision 或 provider 结果如何，只从该 message 队列移除；用户仍可进入其他两个队列。因此 30 批后每条 message 各形成 600 个实际 exposures，总计 1,800 个 `user × message` exposures，三个 600 人受众集合允许重叠。用户级 Campaign Exposure Coverage 可以为 0、1、2 或 3。

新 message 没有自身历史评论或 hashtag 亲和证据，因此 `historical_tag_affinity` 固定记录为 0；其旧内容相关性权重槽位改由归一化 Message-User Fit 使用：

```text
historical_tag_affinity = 0

campaign_engaged_neighbor_signal
= min(1, engaged direct neighbor count / 3)

raw_message_user_fit
= cosine(message value vector, user signed value weights)

normalized_message_user_fit
= (raw_message_user_fit + 1) / 2

personalized_delivery_score(user, message)
= 0.50 * base_network_relevance
+ 0.30 * campaign_engaged_neighbor_signal
+ 0.20 * normalized_message_user_fit
```

`base_network_relevance` 继续来自 holdout-safe Historical Set 评论图，不因新 message 无历史互动而归零。Campaign Engagement Ranking Signal 在 Batch 0 为 0；之后由三条 message 任意一条的 `like/comment/share` 用户集合统一激活，同一用户即使成功互动多条 message 也只计一次，`ignore` 和 `provider_failed` 不传播。

Fit 固定使用当前 message 的 Post 六维 `0/1` 强调向量与用户原始六维价值系数的余弦相似度，不使用 Class 相等硬规则。`[-1,1]` raw cosine 映射到 `[0,1]` 后进入原有 `0.20` 内容适配槽位，保留相对顺序且不新增另一套权重。每条队列按完整精度的 Personalized Delivery Score 降序选择 Top20，完全同分时按 `user_id` 升序。

平台不会在曝光前为候选调用 LLM。每个实际 pair 只在曝光后形成一条 Primary Campaign Decision 和一条配对 Demographic Shadow Decision。

## Class 与 message 语义

每条 Experimental Message Video 都有一个 Intended Audience Segment，表示该文案在设计上主要回应哪个 Class 的价值关注。

已确认：

- Intended Audience Segment 不是硬性曝光资格；
- `user.latent_class == message.intended_segment` 不直接产生 Class 相等加分；
- Class 名称用于设计来源和事后分群分析；
- 平台如需内容适配度，应使用可解释的 message-specific 特征，而不是把 Class 相等当作适配度；
- Message Content Profile 固定保留完整六类消费价值维度作为 Ranking-only 研究编码，不降为单一 `primary_value`，也不向 LLM 展示。

### Class 研究先验分析

权威语义来源是 [`../references/jinjiang-user-latent-attributes-reference-zh.md`](../references/jinjiang-user-latent-attributes-reference-zh.md)。该文档是 Reference only；runtime 使用其结构化版本 `configs/latent_attributes/jinjiang_user_latent_attributes_v1.yaml`，不会动态解析 Markdown。

六维选择模型系数表达锦江秸秆产品语境中的相对价值权重，保留原始正负号且不归一化到 `[0,1]`：

- Class 1：环境价值最强，其次健康价值，社会价值为正；环境意识系数也为正；
- Class 2：健康价值最强，其次功能价值，环境价值接近零；
- Class 3：认知/新奇价值最强，环境和健康价值为较弱正值。

当前 latent assignment 会把所属 Class 的同一组六维系数赋给该 Class 的每位用户，不生成 class 内个体化 value weights。因此，只使用这六维计算的 Message-User Fit 实际是 class-derived personalization：它会让每条 message 对不同 Class 形成不同适配度，但不能证明同一 Class 内的个体内容偏好不同。Comment-Derived User Interaction Graph 等用户级信号仍可在每条 message 的队列中区分同一 Class 的具体用户。

类别分配概率用于生成 Synthetic Experiment Labels；Table 11 的酒店档次、出行目的、性别、年龄、教育和收入只用于合成画像、审计和分组分析，不进入 message routing。

Message Content Profile 按固定顺序“认知、环境、功能、健康、情感、社会”使用旧 PRD 已声明的六维 `0/1` 向量：

```text
Message 1 = [0, 1, 0, 1, 0, 1]
Message 2 = [0, 1, 1, 1, 0, 0]
Message 3 = [1, 1, 0, 1, 0, 0]
```

Message-User Fit 使用该向量与用户原始六维系数的余弦相似度，不再使用旧 rule-based clipped dot-product。当前 Class prototype 的离线诊断为：

| Class | Message 1 | Message 2 | Message 3 | 最高适配 |
|---|---:|---:|---:|---|
| Class 1 | 0.667 | 0.422 | 0.303 | Message 1 |
| Class 2 | 0.176 | 0.624 | 0.150 | Message 2 |
| Class 3 | 0.180 | -0.013 | 0.658 | Message 3 |

该方法使用完整六维和实际文案设计，不比较 Class 名称，也不增加额外 salience 权重。

### 确定性同分规则

每条 message 的最终候选排序使用完整浮点精度的 Personalized Delivery Score，不按报告展示位数预先取整；分数完全相同时按 `user_id` 升序稳定处理。三个队列按稳定 `message_id` 顺序执行和持久化，但该顺序不提供 Ranking 优先权。系统不使用随机数、当前曝光份额或 action 多样性处理同分。

### 设计阶段实现覆盖审计（历史快照）

以下表格保留 2026-07-26 Design Consensus 阶段的实现快照；它说明当时为什么需要实现 Ticket，不代表当前 runtime、renderer 或发布状态。

| 边界 | 当前状态 | 这组六维系数的实际用途 |
|---|---|---|
| latent spec | 已实现 | YAML 完整保存 Class 1/2/3 原始正负系数 |
| latent assignment | 已实现 | 每位用户按所属 Class 获得对应 `value_weights` |
| dataset loader/runtime profile | 已实现 | 扁平 CSV 字段恢复为 `UserProfile.latent_attributes.value_weights` |
| Prompt v3 用户摘要 | 已实现 | 按系数降序展示前三个消费价值及数值，不展示 `latent_class` |
| 通用 RuleBasedDecisionAdapter | 可选实现 | 只有显式设置 `latent_value_weight > 0` 才把旧 clipped dot-product 加入 Decision；默认权重为 `0.0` |
| 当前 Final Research PostContent（历史单视频路径） | 未接入内容向量 | 只从单条真实 TargetVideo 构造 caption 和 hashtags，`value_dimensions` 保持默认全 0 |
| 历史单视频 Target Delivery Ranking | 未使用 | 只使用 base network、engaged-neighbor 和 historical-tag affinity，不读取 Class 六维系数 |
| 三 message personalized queues（设计阶段快照） | 设计阶段未实现 | 当前实现已提供独立 `user × message` eligibility、Per-Message Top20 和 Message-User Fit Ranking |

设计阶段快照对应的是历史单视频合同；当前多 message path 已使用这组六维系数完成推荐分流。

### 当前实现与发布闭合

- 三条 message 已各自运行独立 `user × message` eligibility、Per-Message Personalized Top20、30 batches 和每条 600 次曝光。
- Primary/Shadow Decision、逐曝光 trace、五组核心指标、campaign diagnostics 和双模式 Editorial report 已写入 persisted artifacts，并通过 v4 contract validation。
- 当前 Editorial renderer 已从 design/media source 生成受控 derivatives，已完成 candidate/public acceptance 并切换 canonical `current`；详细 hash、rollback 和公网证据见当前 release evidence。
- 当前首次发布仍只覆盖 1,000 位 Research Sample users；36,400 用户完整 provider-backed experiment 是后续独立研究范围，不推定其批次、容量、调用量或结果。


## 研究主张边界

本实验的主问题是：

> 在同一 1,000 用户池中，三条 message 各自如何通过 Message-User Fit 与用户级网络信号完成 600 次个性化投放，以及各自获配受众如何响应？

实验可以描述每条 message 的个性化受众构成、三组受众重叠、Class-derived personalization、Primary Decision、campaign feedback 对各队列后续 Top20 的影响，以及 Demographic Shadow sensitivity。

三条 message 的受众由各自 Ranking 选择，可以部分重叠，但不是随机可互换实验组。因此，各 message 的互动率和 action 分布仍是 descriptive result，不能解释为真实世界文案效果的因果排名。对于实际重叠用户，可以展示同用户跨 message 的配对描述，但仍不得越过合成画像、选择机制和 LLM 仿真的限制宣称真实因果效果。

## 核心指标与报告 UI

1,000 用户验证固定展示五组核心指标；它们不合成为单一分数，也不生成 message winner。

### Campaign Funnel

- `research_sample_users = 1,000`；
- `eligible_user_message_pairs = 3,000`；
- `actual_exposures = 1,800`，并验证每条 message 各 600；
- `distinct_exposed_users`；
- 用户级 0/1/2/3-message Campaign Exposure Coverage；
- Primary 与 Shadow 各自的调用、成功和 provider failure；
- `message_below_delivery_capacity_pairs = 1,200`。

### Message Allocation

- 每条 message 每批 20、累计 600 的容量兑现；
- 三组受众的 pairwise overlap、三者交集和 distinct union；
- Class × message 曝光矩阵；
- 每条 message 的 raw/normalized Message-User Fit、三个 score components、full-precision Personalized Delivery Score 和 Ranking position；
- 每个曝光用户对三条 message 的 Fit 对照，仅作适配度解释，不伪装成未曝光 message 的 LLM Decision。

### Primary Audience Response

每条 message 分别展示 `like/comment/share/ignore/provider_failed` 数量，并同时给出两个明确分母的描述性比率：

```text
exposure_engagement_rate(message)
= positive Primary actions for message / 600 actual exposures for message

decision_engagement_rate(message)
= positive Primary actions for message / successful Primary Decisions for message
```

### Campaign Feedback Effect

对每条 message 分别在同批冻结候选上比较主 Ranking 与 no-feedback Ranking，展示 Top20 成员发生变化的批次数、每批 Top20 overlap，以及因 campaign feedback 新增和移出的用户数；另汇总三条队列的 observed effect，但不把同一用户重复计为多个 campaign engaged users。

### Demographic Decision Sensitivity

同一次曝光的 Primary 与 Shadow 只做配对比较，展示 `paired_decision_coverage`、`engage_disagreement_rate`、action transition counts、mean absolute probability delta 和 demographic-only reason violation count。违反反刻板化约束的 Shadow reason 不被改写、筛选或重跑。

上述五组必须在报告 UI 中分别有用户可见的概览或图表，不能只存在于 JSON/CSV 下载。UI 必须展示计数、分母、provider failure 和 descriptive/non-causal 边界；不得以排行榜、综合得分或视觉强调暗示某条 message 是因果赢家。每个展示值必须能够追溯到 persisted exposure、Primary Decision、Shadow pair 或冻结 Ranking evidence。

### 逐曝光 Decision Trace UI

指标概览下方提供可筛选的实际曝光明细表，每行对应唯一 `user × message × exposure`，直接展示 batch、`user_id`、`message_id`、report-only `latent_class`、ranking position、selected fit、Primary action/probability/confidence/provider status、Shadow action/probability/pair status 和两者是否分歧。表格支持按 message、Class、batch、Primary action、provider status 和 Primary/Shadow disagreement 筛选。

点击一行打开配对详情，分别展示当前 message 完整原文、Primary 实际可见用户上下文、Primary 结构化 Decision、Shadow 额外可见的四个 demographic labels、Shadow 结构化 Decision、字段差异，以及明确标记为“平台内部、未进入 Prompt”的 Ranking evidence。详情还要区分 persisted input、reconstructed context 和 aggregate evidence。raw Provider Prompt、raw response、密钥和 raw payload 不进入页面；未曝光的 `user × message` pairs 只进入 Message-Level Below Delivery Capacity 与用户 0/1/2/3-message coverage 明细，不生成 Decision Trace。

## LLM-Visible Decision Context

LLM 针对一次实际曝光形成 Decision。message 一侧只向 LLM 提供当前视频原文，让模型从文案本身理解其价值表达：

- 不提供 `Message for Class N` 或 Intended Audience Segment；
- 不提供“本内容主要强调 XX 价值”的显式摘要；
- 不提供 `value_dimensions` 数值；
- 不提供其他竞争视频、竞争分数、Ranking components 或 holdout 证据。

Primary 用户侧固定提供：

- `activity_score`、`global_influence_score`、`local_influence_score` 三个可观测代理指标；
- `environmental_consciousness_coef`；
- 全部六个有符号价值系数；
- 最近入住酒店类型和出行目的。

除三个可观测代理指标外，其余用户字段均明确标注为 Synthetic Experiment Labels；六维价值系数只适用于锦江秸秆产品语境，其正负值不是概率，也不代表真实心理画像。Primary 不提供 `latent_class`、性别、年龄、教育、收入、nickname、bio、signature、原始 follower/following counts、historical tags 或任何 Ranking evidence。

Primary 与 Demographic Shadow 的 PeerContext 均保持中性：`engaged_neighbors`、`exposed_neighbors`、`influential_engaged_neighbors`、`visible_likes`、`visible_comments` 和 `visible_shares` 全部为 0。Campaign Engagement Ranking Signal 只改变下一批投放顺序，不重新解释为用户实际看见的同伴行为，也不同时影响曝光后的 LLM action。

PlatformContext 不进入 Primary 或 Demographic Shadow Prompt。`time_label`、`hot_topics`、`platform_mood`、`feed_ranking_weight`、`trace_visibility`、batch 和 time step 只作为 runtime 或 LLM Decision Trace 元数据；不为三条新 message 补造发布时间、热榜或平台氛围。Prompt 只声明这是允许 `like/comment/share/ignore` 的短视频平台互动场景。

历史 Prompt v2/v3 只展示按系数排序的前三个消费价值；旧 PRD 的理由是使用 compact summary 降低 token 和误读风险，并与三版文案各自声明的三个主要价值保持一致。该 Top3 历史合同保持冻结。完整六维和上述 allowlist 属于新的多 message Prompt 合同，不能原地改写 Prompt v3。

### Primary 与 Demographic Shadow Decision

每次实际曝光先产生一条 Primary Campaign Decision。Primary Prompt 不包含性别、年龄、教育或收入；只有 Primary Decision 可以决定 action、计入 campaign 主指标并激活后续 Campaign Engagement Ranking Signal。

同一次曝光必须使用相同 provider、model、参数和其余上下文再产生一条 Demographic Shadow Decision。Shadow Prompt 只额外加入以下四个粗粒度字段：

- 性别；
- 年龄段；
- 教育程度；
- 月收入区间。

四者均明确标注为 Synthetic Experiment Labels，不代表真实 Douyin 用户身份。Prompt 要求模型不得将人口类别视为固定行为倾向，不得把 demographic 作为唯一或主要互动依据，并优先依据当前 message 原文、六维价值系数和其他已允许的用户上下文解释 Decision。

Demographic Shadow Decision 只用于与 Primary Decision 做配对敏感性比较，不写入 action、Ranking、传播反馈或任何 ABM 状态。即使 Shadow `reason` 出现 demographic-only 归因，也不通过改写、筛选或重试掩盖，应保留允许持久化的结构化输出并标记该限制。该设计复用既有 [`jinjiang-demographic-prompt-ablation.md`](../prds/jinjiang-demographic-prompt-ablation.md)，不改写其历史主 Prompt 合同。

## LLM Decision Trace

`LLM Decision Trace` 的基本证据单位是一次实际曝光，而不是每个用户一条全局记录或每个 message 一组聚合记录：

```text
user × message × exposure context
  -> Primary Campaign Decision
  -> paired Demographic Shadow Decision
```

目标报告的 `LLM 决策`板块应能够区分：

- Primary 与 Demographic Shadow 各自的 LLM-Visible Decision Context；
- 明确未向 LLM 展示的 Ranking 和实验设计证据；
- LLM 返回的完整结构化 Decision 及其 decision variant；
- 实际持久化输入、重建上下文和聚合证据。

仓库已有通用 `decision-trace-summary-v1` 作为安全 Agent 输入/输出包的历史原型，但它不是新的多 message 合同。现有 Final Research 报告只组合了重建上下文、Prompt inclusion、逐用户 Decision 和聚合 reason/context evidence，不能自动升级为逐曝光 trace。

## Multi-Message Formal Contract

新实验采用独立 additive contract，而不是扩写或重解释历史单视频 schema。设计阶段没有在本 Note 预先硬编码 schema token；当前实现使用 `abm-report-release-contract-v4`，由 validator 和 Editorial release evidence 拥有三个 Experimental Message Videos、三条 Per-Message Personalized Top20 队列、Primary/Shadow Decisions、逐曝光 traces、五组核心指标、报告 UI 和 production eligibility evidence 的精确闭合。

历史 Final Research v3-v6 contracts、artifacts、Prompt tokens 和 readers 完全冻结，并继续支持旧报告的只读重建。新 Formal Run 写入独立目录，不迁移或改写旧 run；reader 和 deploy gate 对任何新旧 token 交叉失败关闭。可复用现有数据加载、Provider Adapter 和 release infrastructure，但复用实现不代表复用历史 persisted contract。

## Canonical 发布边界（设计目标已完成）

设计阶段目标已由当前 Multi-Message Formal release 完成：经过独立 v4 contract validation、candidate deployment、health check、atomic `current` switch 和公网 evidence 验收后，Editorial report 已发布到 `https://abm.q1ngyuan.top/`。offline/mock/rule-based/Validation artifact 不能替换该线上版本。

后续 release 仍必须使用显式 Formal release contract、明确 source directory 和 release id，完成本地 contract validation、candidate deployment、health check 和公网 evidence 验收后，才能原子切换 canonical `current`；失败时回退上一 release。现有 release evidence 和历史 v3-v6 artifacts 保持只读 lineage。

## 首次验证与发布边界（历史记录）

首次验证和首次 canonical release 只使用 1,000 位 Research Sample users，不运行 36,400 用户完整实验。以下容量与调用量是已发布首次 release 的合同边界，不是 36,400 用户的推断结果。

每条 message 在 30 批后各完成 600 次实际曝光，总计 1,800 条 Primary Campaign Decisions；每条实际曝光必须再形成一条 report-only Demographic Shadow Decision，因此形成 1,800 条 Shadow Decision opportunities 和 3,600 个逻辑 Decision calls。三个受众集合允许重叠，distinct exposed users 和 0/1/2/3-message coverage 由实际 Ranking 结果决定。每个 message 仍有 400 个未曝光 pairs，三个队列合计 1,200 个 Message-Level Below Delivery Capacity pairs。

首次发布必须先在同一合同上完成完整 offline/mock E2E，再另行明确真实 Provider、模型、重试策略、调用/费用预算和独立 Formal Run 目录。Provider 网络请求数可能因重试超过 3,600，不能把逻辑 Decision call 数直接解释为最高 API request 数。只有通过 Multi-Message Formal contract 的真实 Formal artifact 才能进入 canonical deploy gate。

36,400 用户完整实验是后续独立研究范围，不属于首次 canonical release；当前不推定其批次数、Delivery Capacity、Primary/Shadow 调用量或结果。

当前领域行为、runtime、report UI 和 canonical release 已经闭合。本文不替代 GitHub `Spec:` issue，也不自动授权新的 live API 或部署；当前 release 的真实 Provider、模型、预算、source directory 和 release id 由独立 evidence/contract 明确记录。36,400 用户完整实验仍是后续独立研究范围。
