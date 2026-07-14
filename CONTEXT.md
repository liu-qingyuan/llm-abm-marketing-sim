# Project Context

本文件记录项目稳定领域语言。它只解释概念边界，不记录实现计划、任务拆分、验证步骤或架构决策。

## Glossary

### ABM Simulation

Agent-Based Modeling 仿真过程。系统在社交网络上按时间步推进曝光、观察、决策、行动和指标收集，用于研究营销内容如何扩散。

### Social User Agent

仿真中的社交媒体用户个体。它拥有可观测画像、偏好、邻居可见状态和当前曝光状态，并在每个相关时间步形成一次结构化互动决策。

### Platform Environment

仿真中的平台规则层。它负责决定用户是否看到内容、哪些邻居互动对用户可见，以及平台上下文如何影响传播机会。

### Comment-Derived User Interaction Graph

从真实视频下的一级评论、二级回复和 `@` mention 关系派生的用户互动网络。节点是用户，边表示评论者到视频作者、回复者到被回复评论者或提及者到被提及用户的历史互动；它不是好友或关注关系。

### Platform Recommendation Score

平台估计某条视频应否推荐给某个用户的相对分数。基础模型以 Comment-Derived User Interaction Graph 信号为主要权重，以用户与视频内容的兴趣匹配为辅助权重，不额外构建用户相似度模型。

### Ranking-Based Exposure

平台把 Platform Recommendation Score 解释为候选用户之间的相对排序分数，而不是单个用户的曝光概率。每个推荐批次按分数选择容量范围内的 Top K eligible users；系数决定排序，批次容量决定曝光人数，不再生成 `random_draw`。

### Target Delivery Ranking

在只有一条 Target Marketing Video 的基础研究版本中，平台按 Platform Recommendation Score 对尚未处理的 eligible users 排序，并把目标视频投放给每批 Top K 用户。它是单条营销内容的用户定向排序，不是对多个视频为每个用户执行排序的完整 Feed Ranking。

### Delivery Capacity

Target Delivery Ranking 在一个推荐批次中最多可以投放目标视频的用户数量。锦江单目标视频研究使用固定 `Top20`：Batch 0 强制曝光 20 个 seeds，Batch 1–29 每轮最多向 20 个 non-seed eligible users 投放，总曝光上限为 600。

### Global Reranking

每个推荐批次都对全部尚未处理的 eligible users 重新计算 Platform Recommendation Score，并选择全局 Top K，而不是先随机分组后在小组内排序。上一批次的新互动可以改变 Network Cohort 用户的网络信号和下一轮 ranking position。

### Holdout-Safe Network Normalization

使用 Historical Set 的评论网络 weighted degree 和 P95 reference 计算 `base_network_relevance = min(1, log1p(degree) / log1p(P95_degree))`。该归一化降低极端 hub 对普通网络用户分数的压缩，Target Holdout 不得进入 degree 或 reference 计算。

### Dynamic Network Ranking Signal

平台根据已经对 Target Marketing Video 产生 `like/comment/share` 的用户，计算其 Comment-Derived User Interaction Graph 直接邻居的动态排序信号：`engaged_neighbor_signal = min(1, engaged_neighbor_count / 3)`。该信号只影响下一轮 Target Delivery Ranking，不作为用户可见同伴行为传入 Final Research LLM Prompt，避免同一网络证据同时放大曝光和互动决策。它不声称用户真实看到了邻居的点赞或评论。

### Below Delivery Capacity

用户在某轮参与排序但没有进入 Delivery Capacity 的结果状态。它表示该用户的 ranking position 低于本轮 Top K，不表示平台实际向其展示了某条背景视频，也不等同于用户看到目标视频后选择 `ignore`。

### Recommendation Signal Inclusion

某个推荐信号以明确权重进入 Platform Recommendation Score。它只能证明算法使用了该信号，不能单独证明该信号改变了本次运行的曝光结果。

### Observed Recommendation Signal Effect

在保持同一批用户、seed 行为、Delivery Capacity 和 eligible user 口径不变时，移除某个推荐信号会改变至少一个用户的排名或投放结果。它用于说明该信号在一次具体运行中产生了可观测结果影响，不等同于真实平台因果效应。

### Paired Network Ranking Ablation

在保持同一 Network-Augmented Research Sample、seed 行为、Delivery Capacity 和逐轮 eligible user 集合的条件下，成对比较 full ranking 与移除评论网络贡献的 no-network ranking。该离线对照不额外调用 LLM，逐轮报告 Top20 overlap、network-added users、network-removed users、ranking position change 和累计投放差异。Ranking-Based Exposure 不使用 random draw，因此不再进行随机抽签重复实验。

### Predeclared Ranking Weights

Target Delivery Ranking 的主模型把 `0.50 * base_network_relevance + 0.30 * engaged_neighbor_signal + 0.20 * historical_tag_affinity` 作为预先声明的研究假设。权重通过历史 Top20 diagnostic、敏感性分析和 Paired Network Ranking Ablation 检查，不描述为从真实曝光日志训练得到，也不声称等同抖音平台参数。

### Ranking Weight Sensitivity Check

对预先声明的推荐权重进行小规模离线稳健性检查，用于判断 Top20 排名是否过度依赖单一权重假设。基础研究只比较主方案、网络较弱方案和无网络对照，不穷举参数、不增加 LLM 调用，也不把结果描述为真实平台推荐准确率。

### Video Source Scope

由 processed 视频字段 `source_challenge_name` 表达的真实采集来源分组。它用于视频分层切分和用户样本配额，不等同于视频语义类别。

### Video Catalog

processed 数据中可用于构建历史信号的视频集合。对于单目标视频 Final Research Report Run，Video Catalog 包含一条 Target Marketing Video 和其他历史视频；历史视频不作为 runtime 中主动竞争的对象。

### Target Marketing Video

从 processed Video Catalog 中选定的一条真实采集锦江营销视频。它是 runtime、真实 LLM 决策和最终研究报告的唯一视频入口；研究运行不创建合成替代视频。

### Background Video

Video Catalog 中除 Target Marketing Video 之外的视频。它们只用于构建历史评论网络、历史标签亲和度和用户样本来源；当前基础版本不对这些视频执行 runtime 排序、曝光或 LLM 决策。

### User-Video Interaction

用户与特定视频之间的一次推荐、曝光或互动关系。曝光轮次、`like/comment/share/ignore` 和决策结果必须同时归属于用户与视频，不能只记录为用户全局状态。

### Video Engagement

用户对目标视频产生的非忽略互动。`like`、`comment` 和 `share` 均计入参与；历史一级评论和二级回复统一作为文字互动证据映射到 `comment`，`ignore` 不计入参与。

### Observed User-Video Engagement

processed 数据中能够关联到具体用户与视频的历史互动证据，来自一级评论者和二级回复者。`@` mention 用于建立用户关系边，但被提及用户不能仅凭被提及就算作视频参与者；视频级点赞、分享和收藏聚合计数不能还原为具体用户行为。

### Unobserved User-Video Pair

数据中没有发现用户与视频互动记录的用户—视频组合。它只表示“未观测到互动”，不能直接解释为用户看过视频后选择 `ignore`，因为项目没有真实曝光日志。

### Simulated Engagement Probability

模型在假设用户已获得一次 Recommendation Opportunity 后给出的参与倾向。它是仿真条件概率或相对倾向，不等同于由真实曝光分母计算出的平台点击率或参与率。

### Recommendation Opportunity

尚未获得 Target Marketing Video 曝光的用户进入某轮 Target Delivery Ranking 的资格。低于当轮 Delivery Capacity 的用户保留后续资格；实际获得曝光后，无论结果是 `like`、`comment`、`share`、`ignore` 还是 `provider_failed`，都不再参与后续排序。每个用户在整个 Final Research Report Run 中最多获得一次目标视频曝光和一次 provider-backed 决策机会。

### Decision Adapter

把帖子、用户画像、平台上下文和同伴影响转换为结构化决策的边界。Decision Adapter 可以由规则、缓存或显式启用的 provider 支持，但不负责调度仿真生命周期。

### Decision

用户代理在一次观察后的结构化输出。核心含义是是否互动、互动概率、动作、置信度和简短理由；它是仿真事件和指标的输入，而不是自由文本解释。

### Observed Profile Attributes

从数据源或派生统计中可观察到的用户画像属性。它们可以包括行为计数、互动网络代理指标或已记录的 profile 字段，但只能表达数据中可观测或可复算的事实与代理指标。

### Latent Attributes

为实验建模推断或分配的潜在用户属性。它们可以支持分组分析、价值偏好假设或决策输入扩展，但不等同于真实抖音用户身份、心理画像或第三方认证标签。

### Virtual Experiment Labels

为仿真实验构造的虚拟标签。它们用于比较实验组、解释模拟假设或驱动受控变体，不应被描述为真实采集字段或真实用户属性。

### Field Provenance

研究字段的数据来源类别，用于回答“这个值从哪里来”。统一分为 Direct Observed Profile Field、Historical Behavioral Evidence、Derived Proxy Metric、Synthetic Experiment Label 和 Runtime Simulation Result。Field Provenance 不表示字段是否参与推荐或决策。

### Field Usage Stage

研究字段在实验流程中的实际用途，用于回答“这个值在哪一步被使用”。统一分为 Sampling、Seed Selection、Ranking、LLM Prompt 和 Report Only。同一字段可以进入多个阶段；未进入 LLM Prompt 的字段即使出现在报告中，也不能描述为 LLM 的决策依据。

### Field Lineage Matrix

在研究报告中同时展示 Field Provenance 与 Field Usage Stage 的字段追踪表。它用于区分字段来源和用途，并明确哪些真实证据、派生代理指标或合成实验标签实际进入了样本筛选、seed 选择、推荐排序、LLM Prompt 或仅用于报告展示。

### Processed Variant

在既有数据基础上经过规范化、清理、补充或标签分配后形成的数据版本。Processed Variant 应保留来源口径、变换口径和限制说明，使后续仿真能够复现输入语义。

### Dataset Audit

对数据集口径、覆盖率、行数一致性、重复率、阶段状态和限制的聚合检查记录。Dataset Audit 用于说明数据是否适合某类使用，不展示用户明细或原始 payload。

### Live Provider Gate

显式启用真实外部 provider 的安全边界。默认开发、测试和示例运行应离线、确定性、无需凭证；只有通过 Live Provider Gate 时，才允许调用真实 LLM 或数据 provider。

### Provider-Backed Exposure Decision

Final Research Report Run 中，用户实际获得 Target Marketing Video 曝光后，由显式启用的真实 LLM provider 生成的结构化 Decision。正式研究运行中的全部实际曝光用户使用同一种 provider-backed 决策路径，不以 mock 或规则决策混合补齐；超过重试上限的调用记录为 `provider_failed`，不得伪装成有效互动决策。

### Douyin Data Collection Stage

抖音数据采集的阶段化工作单元。阶段之间应保持可解释边界，例如先建立可信视频分母，再决定是否采集评论、回复或用户画像。

### Provider Payload

发送给外部 provider 或从外部 provider 返回的数据载荷。Provider Payload 可能包含敏感上下文，文档和报告只应保留必要的聚合信息、schema 状态或脱敏证据。

### Final Research Report Run

使用真实 processed 用户数据、对应合成实验标签和显式启用的真实 LLM provider 生成研究展示产物的仿真运行。它不同于 mock 验收运行：目标不是验证 prompt contract 是否可用，而是在受限样本、受限周期和隐私边界内生成最终网页报告与聚合结果。

### Research Sample

从 processed dataset 中按稳定规则抽取的研究运行样本。对于锦江 Prompt v2 final research report，样本来自 final latent-v1 processed variant，并按 `source_challenge_name` 配额抽取真实评论者和回复者；每个入选用户同时携带真实观测数据和合成实验标签。

### Base Sample

在加入 Network Cohort 前，先按 `source_challenge_name` 配额、去重和固定随机种子形成的候选 Research Sample。Seed users 从 Base Sample 内的 global influence top10 与 holdout-safe local influence top10 并集产生，使网络增强实验仍可与原始分层样本口径对照。

### Network Cohort

Research Sample 中为 Comment-Derived User Interaction Graph 传播分析预留的用户子集。它包含 Base Sample seed users 的直接历史互动邻居，并与其他未曝光用户共同进入 Global Reranking，使网络信号既能进入推荐公式，也有机会在具体运行中产生 Observed Recommendation Signal Effect。Network Cohort 不应被描述为总体代表性随机样本。

### Network-Augmented Research Sample

在保持总样本数和 Base Sample seeds 不变的前提下，把 Network Cohort 加入 Base Sample，并使用固定随机种子移除等量普通 non-seed 用户后形成的最终 Research Sample。报告必须分别展示 Base Sample 与 Network-Augmented Research Sample 的构成，并说明 Network Cohort 是传播识别设计，不是总体代表性抽样。

### Final Research Report Artifact

Final Research Report Run 生成的研究展示产物集合。它至少包含网页版本报告、聚合图表、用户级表格，以及可下载 CSV/JSON artifact，使报告既能快速阅读，也能用于后续标注、复核和论文分析。

### Documentation Navigation Contract

文档入口、职责目录和状态标记之间的导航约定。它保护读者能判断一份文档是领域语言、参考资料、架构说明、PRD、ADR 还是数据审计。
