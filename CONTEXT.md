# Project Context

本文件记录项目稳定领域语言。它只解释概念边界，不记录实现计划、任务拆分、验证步骤或架构决策。

## Glossary

### ABM Simulation

Agent-Based Modeling 仿真过程。系统在社交网络上按时间步推进曝光、观察、决策、行动和指标收集，用于研究营销内容如何扩散。

### Social User Agent

仿真中的社交媒体用户个体。它拥有可观测画像、偏好、邻居可见状态和当前曝光状态，并在每个相关时间步形成一次结构化互动决策。

### Platform Environment

仿真中的平台规则层。它负责决定用户是否看到内容、哪些邻居互动对用户可见，以及平台上下文如何影响传播机会。

### Historical Data Layer

机制展示三层中的**历史数据层（Historical Data Layer）**。它拥有已采集并清洗的用户画像、历史互动证据，以及由这些证据派生的 Comment-Derived User Interaction Graph，并为研究样本与静态 ranking signals 提供输入。它不表示 runtime live database、在线抓取、当前平台 feed 或一次仿真中的动态反馈。

### Platform Recommendation Layer

机制展示三层中的**平台推荐层（Platform Recommendation Layer）**。它拥有 eligible `user × message` pairs、Per-Message Queue、ranking、Delivery Capacity、Exposure Gate、full-batch barrier 和 next-batch ranking contexts。它决定哪些 pair 获得曝光；不能把这一层误写成 LLM、Decision Adapter 或模拟用户在调度曝光。

### Simulated User Decision Layer

机制展示三层中的**模拟用户决策层（Simulated User Decision Layer）**。它只在 pair 实际曝光后形成 Primary Campaign Decision 和同次曝光的 report-only Demographic Shadow Decision。它不创建 Research Sample、不维护推荐 queue，也不把 Shadow、`ignore` 或 `provider_failed` 写成可传播反馈。

### Comment-Derived User Interaction Graph

从真实视频下的一级评论、二级回复和 `@` mention 关系派生的用户互动网络。节点是用户，边表示评论者到视频作者、回复者到被回复评论者或提及者到被提及用户的历史互动；它不是好友或关注关系。

### Platform Recommendation Score

平台估计某条视频应否推荐给某个用户的相对分数。基础模型以 Comment-Derived User Interaction Graph 信号为主要权重，以用户与视频内容的兴趣匹配为辅助权重，不额外构建用户相似度模型。

### Ranking-Based Exposure

平台把 Platform Recommendation Score 解释为候选用户之间的相对排序分数，而不是单个用户的曝光概率。每个推荐批次按分数选择容量范围内的 Top K eligible users；系数决定排序，批次容量决定曝光人数，不再生成 `random_draw`。

### Target Delivery Ranking

在只有一条 Target Marketing Video 的基础研究版本中，平台按 Platform Recommendation Score 对尚未处理的 eligible users 排序，并把目标视频投放给每批 Top K 用户。它是单条营销内容的用户定向排序，不是对多个视频为每个用户执行排序的完整 Feed Ranking。

### Per-Message Personalized Top20

Concurrent Message Competition Experiment 中，每条 Experimental Message Video 都对尚未看过该 message 的 eligible users 维护独立个性化 Ranking，并在每批选择自己的 Top20。候选单位是 `user × message`；最终使用 `0.50 * base_network_relevance + 0.30 * campaign_engaged_neighbor_signal + 0.20 * normalized_message_user_fit`，同一用户可以同时出现在多条 message 的队列中。

### Per-Message Delivery Capacity

每条 Experimental Message Video 在每个推荐批次各自拥有 Top20 曝光容量。当前 1,000 人验证中，三个 message 每批合计最多形成 60 个 `user × message` exposures，30 批后每条 message 各 600 次、总计 1,800 次；该容量不要求三个受众集合互斥。

### Shared Seed Launch

Batch 0 将同一个 Full-Pool Influence Seed Union 强制曝光给三条 Experimental Message Videos。若 seed union 少于某条 message 的 Top20 容量，该 message 再按自己的 Personalized Delivery Score 独立补足；因此三条 message 的 seeds 相同，只有补足用户可能不同。Batch 0 的全部 Primary Decisions 完成后，成功互动用户按 campaign 去重再传播。

### Message-Level Single Exposure

同一用户对同一 Experimental Message Video 最多曝光一次；该 pair 一旦曝光，无论 Primary Decision 或 provider 结果如何，都退出该 message 的后续候选集合。用户仍可进入其他 message 的 Ranking，因此整个 campaign 最多接收三条不同 message。

### Campaign Exposure Coverage

用户在三个 Experimental Message Videos 中实际获得曝光的 distinct message 数，取值为 0、1、2 或 3。它用于区分完全未覆盖、部分覆盖和三 message 全覆盖，不把多个 user-message exposures 误写成多个 distinct users。

### Message-Level Below Delivery Capacity

某个 `user × message` pair 在全部推荐批次结束后仍未获得该 message 曝光的最终状态。它表示该 pair 从未进入对应 message 的 Per-Message Delivery Capacity，不等同于用户看过该 message 后选择 `ignore`；同一用户对其他 message 可以已有曝光和 Decision。

### Delivery Capacity

Target Delivery Ranking 在一个推荐批次中最多可以投放目标视频的用户数量。锦江单目标视频研究使用固定 `Top20`：Batch 0 强制曝光 20 个 seeds，Batch 1–29 每轮最多向 20 个 non-seed eligible users 投放，总曝光上限为 600。

### Global Reranking

每个推荐批次都对全部尚未处理的 eligible users 重新计算 Platform Recommendation Score，并选择全局 Top K，而不是先随机分组后在小组内排序。上一批次的新互动可以改变 Network Cohort 用户的网络信号和下一轮 ranking position。

### Holdout-Safe Network Normalization

使用 Historical Set 的评论网络 weighted degree 和 P95 reference 计算 `base_network_relevance = min(1, log1p(degree) / log1p(P95_degree))`。该归一化降低极端 hub 对普通网络用户分数的压缩，Target Holdout 不得进入 degree 或 reference 计算。

### Dynamic Network Ranking Signal

平台根据已经对 Target Marketing Video 产生 `like/comment/share` 的用户，计算其 Comment-Derived User Interaction Graph 直接邻居的动态排序信号：`engaged_neighbor_signal = min(1, engaged_neighbor_count / 3)`。该信号只影响下一轮 Target Delivery Ranking，不作为用户可见同伴行为传入 Final Research LLM Prompt，避免同一网络证据同时放大曝光和互动决策。它不声称用户真实看到了邻居的点赞或评论。

### Campaign Engagement Ranking Signal

Concurrent Message Competition Experiment 中，平台根据此前批次对任意 Experimental Message Video 产生 `like/comment/share` 的去重用户集合，计算候选用户在历史评论图中的直接邻居互动信号。该信号在 Batch 0 固定为 0，之后只影响三条 message 的个性化 Ranking，不进入 LLM-Visible Decision Context；同一用户对多条 message 的成功互动在 campaign engaged-user 集合中只计一次，`ignore` 和 `provider_failed` 不传播。

### Below Delivery Capacity

用户在某轮参与排序但没有进入 Delivery Capacity 的结果状态。它表示该用户的 ranking position 低于本轮 Top K，不表示平台实际向其展示了某条背景视频，也不等同于用户看到目标视频后选择 `ignore`。

### Recommendation Signal Inclusion

某个推荐信号以明确权重进入 Platform Recommendation Score。它只能证明算法使用了该信号，不能单独证明该信号改变了本次运行的曝光结果。

### Observed Recommendation Signal Effect

在保持同一批用户、seed 行为、Delivery Capacity 和 eligible user 口径不变时，移除某个推荐信号会改变至少一个用户的排名或投放结果。它用于说明该信号在一次具体运行中产生了可观测结果影响，不等同于真实平台因果效应。

### Paired Network Ranking Ablation

在保持同一 Network-Augmented Research Sample、seed 行为、Delivery Capacity 和逐轮 eligible user 集合的条件下，成对比较 full ranking 与移除评论网络贡献的 no-network ranking。该离线对照不额外调用 LLM，逐轮报告 Top20 overlap、network-added users、network-removed users、ranking position change 和累计投放差异。Ranking-Based Exposure 不使用 random draw，因此不再进行随机抽签重复实验。

### Predeclared Ranking Weights

Target Delivery Ranking 的主模型把 `0.50 * base_network_relevance + 0.30 * engaged_neighbor_signal + 0.20 * historical_tag_affinity` 作为预先声明的研究假设。Ranking signal 是随 user、message 或 batch 状态取值的输入，Ranking weight 才是乘在 signal 上的政策参数；二者不能混称为同一类“变量”。权重通过历史 Top20 diagnostic、敏感性分析和 Paired Network Ranking Ablation 检查，不描述为从真实曝光日志训练得到，也不声称等同抖音平台参数。

### Ranking Weight Sensitivity Check

对预先声明的推荐权重进行小规模离线稳健性检查，用于判断 Top20 排名是否过度依赖单一权重假设。基础研究只比较主方案、网络较弱方案和无网络对照，不穷举参数、不增加 LLM 调用，也不把结果描述为真实平台推荐准确率。

### Concurrent Ranking Weight Sensitivity Study

在固定 1,000-user Research Sample 上，以 19 个预声明 simplex points 只调整 Personalized Delivery Score 的三个 Ranking Weights，同时固定 P95 normalization 和 component definitions。该层只离线比较 frozen Top20 overlap 与 rank change，不调用 Provider、不推进传播；三个受约束权重不使用标准 Morris 或标准 Sobol。

### Video Source Scope

由 processed 视频字段 `source_challenge_name` 表达的真实采集来源分组。它用于视频分层切分和用户样本配额，不等同于视频语义类别。

### Primary Video Source Scope

用户在 Historical Set 中产生评论和回复次数最多的 Video Source Scope，用于 Seed-First Research Sample 的分组配额与报告解释。多个 scope 次数相同时按稳定来源顺序选择；它不改变用户在评论网络中的连接。

### Video Catalog

processed 数据中可用于构建历史信号的视频集合。对于单目标视频 Final Research Report Run，Video Catalog 包含一条 Target Marketing Video 和其他历史视频；历史视频不作为 runtime 中主动竞争的对象。

### Target Marketing Video

从 processed Video Catalog 中选定的一条真实采集锦江营销视频。它是当前单视频 runtime、真实 LLM 决策和最终研究报告的唯一视频入口；研究运行不创建合成替代视频。

### Experimental Message Video

由研究者设计的一条营销 message 原文，在仿真中作为独立发布的视频内容对象。当前多 message 研究包含三个 Experimental Message Videos；它们不暗示存在实际视频、图片、音频或历史互动数据。

### Concurrent Message Competition Experiment

三个 Experimental Message Videos 从 Batch 0 起同时运行独立的 Per-Message Personalized Top20，并在同一 1,000 用户池中形成允许重叠的个性化受众。每条 message 固定每批 Top20、30 批共 600 次曝光；“competition”表示三条并行 campaign 面向同一用户池并产生可比较的受众响应，不表示争抢同一个 20-slot message quota。实验不提供真实世界文案效果的因果排名。

### Full-Pool 30-Batch Run

使用全部 36,400 位合格 processed users、现有三条 Experimental Message Videos 和固定 30 个推荐批次的 Concurrent Message 运行。每条 message 每批容量为 1,214、最后一批为 1,194，使 109,200 个 `user × message` pairs 各获得一次曝光和一次 Primary Campaign Decision；不执行新的 Shadow，现有 ranking、barrier 和正向 Primary 的 next-batch feedback 边界保持不变。

### Full-Pool Formal Main Experiment

通过显式 Live Provider Gate 为 Full-Pool 30-Batch Run 生成 fresh Primary Decisions 的 Formal experiment。它是下一版 additive report 的主要运行证据，并使用独立 run、candidate 和 release lineage，immutable v7 保持不变。

### Strict Full-Pool Formal Replay

从 Batch 0、logical/physical/pair position 0 初始化全新 Full-Pool trajectory 的最高 runtime Seam。调用方只提交冻结 request 与十 lane Adapter factory；Module 内部拥有 ranking、wave settlement、strict reconciliation、full-batch barrier、feedback commit 和 source closure。它不导入历史 terminal、batch commit、ranking state 或 feedback；被拒绝的 mixed source 只能作为 hash-bound audit lineage。

### Strict Pair Policy

Fresh replay 在 batch commit 前闭合非成功 pair 的持久化规则。标准 dispatch 的 `provider_failed` 或 provenance unknown 只是 provisional outcome；同一 frozen pair context 最多消费一个原子 slot-plus-dispatch reconciliation。只有 final `succeeded` terminal 可以跨过 full-batch barrier，第二次非成功、implementation failure 或 cap 不足都会形成 typed strict stop，且不生成完整 source。

### Segmented Source-v4

Strict Full-Pool Formal Replay 从 fresh workspace 的 persisted identity、30 个 batch commits、spool、settlement v2、Strict Pair Policy 和 final terminal evidence 原子生成的 additive source。每个 logical pair 必须恰有一个 final successful response、exact observed model 和完整 usage；provisional failures、failed attempts、reconciliation 与 uncertainty 只保留在 attempt/physical accounting，不伪装成 final Decision。旧 mixed source-v3 只以 manifest hash、path 和 rejection reason 进入 lineage，不参与 trajectory 计算。

### Durable Pair Settlement

Full-Pool segmented runtime 中把每个已派发 pair 独立归约为 terminal、typed provenance unknown 或 `implementation_failed` 的持久化机制。completion order 只决定 settlement capture 顺序；canonical pair order 只决定完整 batch 的 ABM commit。一个 pair 的未知来源或实现失败不能抹掉同波 sibling 已形成的安全 evidence。

### Automated Recovery Policy

为 typed provenance unknown 提供 create-once、hash-bound、无需逐次人工批准的有界恢复合同。Policy 对同一 pair 最多消费一个 reconciliation slot，并在 Provider 调用前持久化 slot 与完整 retry-window reservation；它不承诺 Provider exactly-once，也不能从 issue label、latest directory 或未持久化状态推定执行参数。

### Automation Exhausted

Automated Recovery Policy 的 nondeployable 终止状态。second unknown、reconciliation dispatch 后缺少 settlement、slot 重复消费、policy/workspace identity drift 或 cap 不足都会进入该状态；unknown 不产生 terminal，所在 batch 不提交，也不能生成 source、Report candidate 或 Release 输入。

### Segmented Source-v3

完整 automated nested recovery 的 additive persisted source。它在 109,200 logical terminals、30 batch barriers、settlement v2、automated policy 与 original/first/second recovery lineage 全部闭合后原子生成，并分栏保留 historical physical、uncertainty、retry、reconciliation 与 continuation accounting。它不改写 source-v2 或 Release v9，也不因 Validation/mock rehearsal 自动获得 production deploy eligibility。

### Automation Execution Manifest

在 automated nested recovery 启动前 create once 的执行身份合同。它精确绑定 implementation commit 与 Module hashes、nested plan、七个 retry mappings、绝对 paths、Provider/model/P0 request contract、十 lanes、logical/physical caps、USD 0 billing和自动停止规则；operator只能消费 exact manifest，不从 latest directory、issue label或测试 fixture推定执行参数。

### Full-Pool Segment Result Projection

从 closed Segmented Source-v3 terminal rows 按 `user_id` 连接冻结 latent-v1 membership 后形成的九格同源投影。固定列为 `Run | Message | Segment | Total Likes | Total Comments | Total Shares | Exposure`，按 Segment → Message → Run 排序；Exposure包含`ignore`，互动列只统计成功 terminal 的对应 action。Canonical HTML、UTF-8 CSV与Markdown lineage/data dictionary共享同一 rows identity。

### Release v10

只接受 exact manifest-driven Formal Source-v3 的 additive production release contract。它显式绑定 original/first/second recovery、automated policy、settlement v2、aggregate accounting与结果 projection；Release v9继续只表达source-v2。Validation/mock、incomplete、`implementation_failed`和`automation_exhausted`证据均不可晋升。

### Full-Pool Mechanism Master

为 Full-Pool Formal Main Experiment 新增的单张端到端 Mermaid 总图，文件名为 `full-pool-mechanism.mmd`。它只表达全池分母、30-batch delivery、Primary-only Decision 和 feedback 主路径；现有五张主机制图、`real-batch-mechanism.mmd` 与 Prompt–Model factorial 保持原字节，不复制另一套分图。

### Historical 1,000-User Sensitivity Layer

与全池主实验并列保留的历史 Primary–Shadow sensitivity、19-point Ranking Weight Sensitivity 和 `4 Prompt × 4 model` Robustness evidence。该层继续绑定原始 1,000-user sources、hashes 与分母，不在全池上重跑，也不能解释为 36,400-user 结果。

### Prompt–Model Robustness Study

在固定 1,000-user Research Sample 和三条 Experimental Message Videos 上，对 4 个信息等价 Prompt 与 4 个同 provider 精确模型做完整 categorical factorial。每个 cell 只运行一次 1,800-Primary-Decision 动态轨迹，统一使用 low reasoning contract、fresh calls 和独立 store，不重跑 Shadow、不建立完整 Decision Bank；Batch 0 shared seeds 支持配对 `engage` 比较，其余互动、曝光和传播结果只描述单次 realized path。该研究没有 ground truth，不称为 Calibration，也不单独估计模型随机性。

### Incremental Robustness Presentation

保留当前 canonical report 的机制、Run Evidence、Demographic Shadow 和 barrier 内容，再增量加入 Ranking Weight 与 Prompt–Model 结果。旧 Shadow evidence 继续绑定原始 Formal source；新增曲线只借鉴批准视觉参考的宽幅、外置图例和 line/dash/marker grammar。

### Multi-Message Formal Contract

Concurrent Message Competition Experiment 独立使用的 additive persisted/release contract。它为三 message、Primary/Shadow Decisions、逐曝光 traces、五组指标和新报告 UI 声明一致的 schema tuple；历史 Final Research v3-v6 contracts、artifacts 和 readers 保持冻结，任何新旧 token 交叉都失败关闭。

### Intended Audience Segment

某条 Experimental Message Video 在设计上对应的 `Class 1/2/3` 分群，表示文案主要回应哪类用户的价值关注。它是设计来源和分析维度，不是硬性曝光资格、直接 Class 相等加分或 LLM 可见标签。

### Message Content Profile

某条 Experimental Message Video 在“认知、环境、功能、健康、情感、社会”六类消费价值维度上的 Ranking-only `0/1` 向量：旧文案设计声明强调的维度为 `1`，其余为 `0`。它不改写 message 原文、不直接复制 Intended Audience Segment，也不进入 LLM-Visible Decision Context。

### Message-User Fit

Message Content Profile 与用户原始六维价值系数之间的余弦相似度，保留 raw `[-1,1]` 值，并以 `(cosine_similarity + 1) / 2` 映射为 Ranking 使用的 `[0,1]` signal。它不使用 Class 相等规则或旧 clipped dot-product，也不表示曝光概率、互动概率或 LLM Decision。

### Personalized Delivery Score

Concurrent Message Competition Experiment 中每个 eligible `user × message` pair 的最终排序分数：`0.50 * base_network_relevance + 0.30 * campaign_engaged_neighbor_signal + 0.20 * normalized_message_user_fit`。三项使用完整精度，完全同分时按 `user_id` 升序；`historical_tag_affinity` 因新 message 无历史证据而固定记录为 0，但不占最终分数。

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

### LLM-Visible Decision Context

LLM 在一次具体 User-Video Interaction 获得曝光后实际可见的 allowlisted 语义输入。message 一侧只提供当前视频原文，不提供 Intended Audience Segment 或内部六维 `0/1` 向量；Primary 用户侧只提供三个可观测代理指标、环保意识、全部六个有符号价值系数、入住酒店类型和出行目的，不提供 `latent_class`。Primary 与 Demographic Shadow 的 PeerContext 均保持全 0，PlatformContext 全部留在 runtime/trace；Ranking、holdout、campaign feedback 和竞争视频分数不属于该上下文。

### Primary Campaign Decision

实际曝光后产生、且唯一能够写入 action、指标和后续 Campaign Engagement Ranking Signal 的结构化 Decision。它不向 LLM 暴露性别、年龄、教育或收入等 demographic labels。

### Demographic Shadow Decision

与同一次实际曝光的 Primary Campaign Decision 成对执行的 report-only Decision。它使用相同的 `user × message × exposure context`、provider、model 和参数，只额外暴露性别、年龄段、教育程度和月收入区间四个 Synthetic Experiment Labels；它不影响 action、Ranking、传播反馈或 ABM 状态，只用于衡量 demographic prompt sensitivity。

### Descriptive Message Response

Experimental Message Video 在其实际获配受众中的曝光后 action 和互动率。`exposure_engagement_rate = positive actions / actual exposures`，`decision_engagement_rate = positive actions / successful Primary Campaign Decisions`；两者都不构成 message 文案效果的因果排名，必须在报告 UI 中连同分母和 provider failures 展示。

### Demographic Decision Sensitivity

同一次实际曝光的 Primary Campaign Decision 与 Demographic Shadow Decision 之间的配对差异，包括 pair coverage、engage disagreement、action transition 和 probability delta。它只衡量 Prompt 对 Synthetic Demographic Labels 的敏感性，不代表真实人口群体行为差异。

### LLM Decision Trace

把一次具体 `user × message × exposure context` 的 LLM-Visible Decision Context 与其结构化 Decision 配对的研究证据。它必须标明 Primary Campaign Decision 或 Demographic Shadow Decision，不是 raw Provider Prompt 或 Provider Payload，并且必须区分实际持久化输入、重建上下文和聚合证据。

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

### Global Influence Proxy

基于用户粉丝数归一化得到的 0..1 可观测代理指标，表达潜在全平台覆盖能力。它不是抖音官方影响力指数或真实传播效果。

### Local Influence Proxy

结合历史评论网络位置与历史评论获赞认可得到的 0..1 可观测代理指标，表达用户在锦江历史互动语境中的局部影响力。`Local` 表示评论网络内部，不是地理位置或因果影响力。

### Full-Pool Influence Seed Union

在形成 Research Sample 之前，从全部合格 processed users 中取 Global Influence Proxy Top10 与 Local Influence Proxy Top10 的去重并集。它是 Seed-First Research Sample 的传播起点；两个 Top10 重叠时并集可能少于 20 人。

### Seed Neighbor Cohort

Full-Pool Influence Seed Union 在 holdout-safe Comment-Derived User Interaction Graph 中的直接历史互动邻居集合。该 cohort 用于确保评论网络信号有机会影响后续排序，不是代表性随机样本。

### Seed-First Research Sample

先从全部合格 processed users 中形成 Full-Pool Influence Seed Union，再纳入 Seed Neighbor Cohort，将两者计入 Primary Video Source Scope 配额后用分组固定随机普通用户补齐不足分组的 Research Sample。它是传播识别设计，只确保网络信号有作用机会，不预先保证 Observed Recommendation Signal Effect。

### Final Research Report Artifact

Final Research Report Run 生成的研究展示产物集合。它至少包含网页版本报告、聚合图表、用户级表格，以及可下载 CSV/JSON artifact，使报告既能快速阅读，也能用于后续标注、复核和论文分析。

### Interactive Mechanism Report

在同一个页面叙事中同时提供通俗机制概览和可按需展开的本次运行证据的研究展示产物。它必须持续区分稳定研究规则与某次 Final Research Report Run 的观测结果，不能把预设权重或信号纳入误述为已观测效果。

### Editorial Legend Contract

Interactive Mechanism Report 中每个 Legend item 必须对应当前 Interaction State 内真实、可辨认的 Visual mark，并明确该 mark 是否绑定 Data field/series；当前状态没有对应 mark 时隐藏该 item，并用 Narrative annotation 说明无数据。Narrative annotation、公式和边界说明不能使用 series swatch 伪装成 Legend item。

### Visual Encoding Reference

Editorial 机制图完整资产生成前批准的视觉编码依据，逐项固定 Legend item、Visual mark、Data field/series、Interaction State 和 Narrative annotation 边界；完整图必须按该依据生成并反向核对。

### Mechanism Explanation Mode

Interactive Mechanism Report 的默认阅读模式，用通俗视觉和稳定术语解释研究机制，不展示或暗示某次运行才成立的结果。

### Run Evidence Mode

Interactive Mechanism Report 中基于持久化 artifacts 展示本次运行计数、逐轮排名、决策、诊断和限制的证据模式。基础版本直接使用允许公开的真实 processed/runtime 用户字段，不另设匿名或授权视图，也不暴露 raw Provider Payload。

### Documentation Navigation Contract

文档入口、职责目录和状态标记之间的导航约定。它保护读者能判断一份文档是领域语言、参考资料、架构说明、PRD、ADR 还是数据审计。
