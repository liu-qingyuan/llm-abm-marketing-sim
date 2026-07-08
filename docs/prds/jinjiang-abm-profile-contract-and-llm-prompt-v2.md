# PRD: 锦江 ABM 用户画像合同收敛与 LLM Prompt v2

Status: Published to GitHub issue tracker
GitHub issue: https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/19
Related PRD: [`jinjiang-user-latent-attributes-v1.md`](jinjiang-user-latent-attributes-v1.md)
Related Architecture Note: [`../architecture/jinjiang-user-profile-data-structure.md`](../architecture/jinjiang-user-profile-data-structure.md)

## 问题陈述

当前锦江酒店 Douyin ABM 已经有两类用户信息：一类是真实观测数据，例如活跃度和影响力代理指标；另一类是基于研究先验生成的合成实验标签，例如消费价值偏好、环保意识倾向和最近入住场景标签。

但早期 demo 里遗留的 `brand_attitude`、`like_tendency`、`comment_tendency`、`share_tendency` 仍然存在，并且会影响规则决策。这些字段没有可靠的锦江 Douyin 观测依据，容易让后续 ABM 结果被人为预设权重解释。同时，LLM prompt 还没有明确区分真实观测数据、合成实验标签、内容价值维度和其他用户互动信息，容易把内部字段名或不应进入决策的字段直接暴露给模型。

需要收敛锦江 ABM 的用户画像合同，删除早期 demo preset 字段，并设计面向锦江秸秆制品绿色营销文案的 LLM 决策 prompt，使 LLM 同时判断是否互动和互动动作。

## 解决方案

为锦江 ABM 建立新的用户画像和 prompt 合同：

- 删除 `brand_attitude`、`like_tendency`、`comment_tendency`、`share_tendency`，后续不进入数据表、schema、prompt 或决策。
- 真实观测用户数据只保留有观测依据的核心摘要：真实 profile 中的兴趣标签、活跃度、全平台影响力、锦江酒店社群内的局部影响力。
- 观测指标分量只用于审计、解释和方法透明，不作为最终 ABM 默认决策输入。
- 合成实验标签用于表达消费价值偏好、环保意识倾向、最近一次入住锦江旗下酒店类型和出游目的。
- `latent_class` 只作为内部实验分组 ID，不直接以自创用户类型名称暴露给 LLM。
- 性别、年龄、教育、收入等人口画像标签默认不进入 prompt，优先用于后续分组分析，避免引入不必要的刻板判断。
- LLM prompt 使用自然语言情境：模拟一名抖音用户无意间刷到锦江酒店集团使用秸秆制品的绿色营销内容。
- LLM 同时输出 `engage` 和 `action`，其中 action 允许 `like`、`comment`、`share`、`ignore`。

## 用户故事

1. 作为研究者，我想删除没有观测依据的品牌态度和互动倾向字段，这样锦江 ABM 的决策解释不会依赖人为预设权重。
2. 作为研究者，我想区分真实观测用户数据和合成实验标签，这样论文和报告能清楚说明哪些来自 Douyin 数据，哪些来自实验设计。
3. 作为研究者，我想把 `global_influence_score` 表述为“全平台影响力”，这样合作者和读者能更直观理解该指标。
4. 作为研究者，我想把 `local_influence_score` 表述为“锦江酒店社群内的局部影响力”，这样该指标的研究语境更清楚。
5. 作为研究者，我想把 9 个观测分量字段降级为审计和解释字段，这样最终 ABM 不会误用中间分量。
6. 作为研究者，我想把用户真实 profile 中的兴趣标签加入主 prompt，这样 LLM 能参考用户可观测兴趣，但不被过长标签列表干扰。
7. 作为研究者，我想把 environmental consciousness 明确写入 prompt 口径，这样合作者指出的环保意识变量不会被遗漏。
8. 作为研究者，我想区分“环保意识倾向”和“环保价值偏好”，这样 LLM 不会把两个概念混成同一个输入。
9. 作为研究者，我想在 prompt 中突出用户最看重的前三个秸秆制品相关消费价值，这样输入能和三版营销文案设计保持一致。
10. 作为研究者，我想默认不把性别、年龄、教育、收入放进 prompt，这样 LLM 决策不被不必要的人口画像标签引导。
11. 作为研究者，我想保留最近一次入住锦江旗下酒店类型和出游目的，这样 prompt 与酒店消费场景直接相关。
12. 作为研究者，我想删除自创“用户类型”名称，这样 LLM 不会被“环保型”“健康型”等总结性标签提前引导。
13. 作为仿真实验运行者，我想让 LLM 同时判断是否互动和互动动作，这样输出可以直接用于 ABM 传播过程。
14. 作为仿真实验运行者，我想 prompt 只包含营销内容文本和主要强调价值，这样内容输入不会被重复 topic tags 拉长。
15. 作为仿真实验运行者，我想在无 API 凭证时仍能用 deterministic 或 mock 决策路径跑通仿真和测试，这样默认离线路径保持可复现。
16. 作为维护者，我想文档中有字段标准表，这样后续 agent 实施时不会把旧字段重新加入 prompt 或 schema。

## 实现决策

- 锦江 ABM 用户画像分为两部分：真实观测数据和合成实验标签。
- 真实观测数据用于描述用户在 Douyin 锦江相关数据中的可见行为和网络位置。
- 合成实验标签用于描述研究先验生成的消费价值偏好和酒店消费场景标签，不描述为真实用户身份。
- 早期 demo preset 字段彻底删除，不保留为解释字段或最终物理字段。
- 决策层应通过现有 `LLMDecisionAdapter` 边界接入，不把 prompt 逻辑散落到 agent、runner 或数据生成脚本。
- Prompt 构建应通过单一 prompt builder 接缝完成，负责把内部字段转换为面向 LLM 的中文语义摘要。
- Provider-backed LLM 决策继续必须显式启用；默认离线、确定性、无 API 凭证路径不能被破坏。
- 真实 LLM 只在显式 provider-backed 模式中运行；默认离线路径只验证 prompt 构建、schema 校验、mock provider 或 deterministic baseline，不发起 live API。
- Rule-based/offline baseline 可以保留为测试和本地 smoke 使用，但不能继续依赖已删除的 demo preset 字段。
- `latent_class` 作为内部分组 ID 和报告维度保留，不直接写进 prompt 为“用户类型”。
- LLM prompt 不使用自创用户类型名称，只提供具体属性摘要。
- Post 输入保留营销文案全文和内容主要强调的消费价值。
- 其他用户行为输入保留为同伴影响摘要，例如已可见点赞、评论、分享或邻居互动比例。
- LLM 输出必须仍是结构化 JSON，并通过现有决策输出 schema 校验。

### 删除字段标准

| 字段 | 当前含义 | 新规则 | 原因 |
|---|---|---|---|
| `brand_attitude` | 预设用户对品牌好感度 | 删除 | 锦江数据没有可靠观测依据 |
| `like_tendency` | 预设点赞倾向 | 删除 | 人为设定，不作为可信观测变量 |
| `comment_tendency` | 预设评论倾向 | 删除 | 人为设定，不作为可信观测变量 |
| `share_tendency` | 预设分享倾向 | 删除 | 人为设定，不作为可信观测变量 |

这些字段后续不进入数据表、schema、prompt、LLM 决策或规则决策。

### 真实观测用户数据标准

| 字段 | Prompt 表述 | 含义 | 是否进 prompt |
|---|---|---|---|
| `activity_score` | 活跃度：中等偏高（0.65） | 用户在锦江相关 Douyin 数据中的活跃度综合指标 | 是 |
| `global_influence_score` | 全平台影响力：较低（0.21） | 基于粉丝量等平台可见信息的影响力代理 | 是 |
| `local_influence_score` | 锦江酒店社群内的局部影响力：中等（0.48） | 基于锦江评论网络位置和评论获赞的局部影响力代理 | 是 |
| `interest_tags` | 兴趣标签：绿色消费、酒店、旅行 | 用户真实 profile 中的可观测兴趣标签 | 是，长度受限 |

数值应保留，同时给出低/中/高等自然语言等级。等级转换规则应稳定、可测试。兴趣标签属于真实观测 profile，但进入 prompt 前应做长度限制和清洗，只保留少量短标签；空标签时省略该行。

### 真实观测指标分量标准

| 字段 | 解释 | 用途 |
|---|---|---|
| `activity_video_score` | 发布视频活跃分量 | 审计和解释 |
| `activity_publish_score` | 发布活跃分量 | 审计和解释 |
| `activity_comment_score` | 评论活跃分量 | 审计和解释 |
| `activity_reply_score` | 回复活跃分量 | 审计和解释 |
| `local_network_score` | 锦江互动网络位置分量 | 审计和解释 |
| `local_recognition_score` | 评论获赞/认可分量 | 审计和解释 |
| `influence_coverage_score` | 粉丝覆盖力分量 | 审计和解释 |
| `influence_recognition_score` | 被认可程度分量 | 审计和解释 |
| `influence_network_score` | 网络连接分量 | 审计和解释 |

这些字段不作为最终 ABM 默认 prompt 输入或直接决策变量。

### 合成实验标签标准

| 字段 | Prompt 表述 | 含义 | 是否进 prompt |
|---|---|---|---|
| `latent_class` | 不直接展示 | 内部实验分组 ID | 否 |
| `latent_environmental_consciousness_coef` | 环保意识倾向：较强（1.037） | 用户整体环保意识倾向 | 是 |
| `latent_environmental_value_weight` | 最看重的秸秆制品相关价值之一：环保价值 | 对锦江秸秆制品环保价值的感知偏好 | 是，作为前三价值之一时展示 |
| `latent_health_value_weight` | 最看重的秸秆制品相关价值之一：健康价值 | 对健康、安全、安心的感知偏好 | 是，作为前三价值之一时展示 |
| `latent_functional_value_weight` | 最看重的秸秆制品相关价值之一：功能价值 | 对实用性、耐用性、使用体验的感知偏好 | 是，作为前三价值之一时展示 |
| `latent_epistemic_value_weight` | 最看重的秸秆制品相关价值之一：知识/新奇价值 | 对新材料、新工艺、新奇信息的感知偏好 | 是，作为前三价值之一时展示 |
| `latent_emotional_value_weight` | 最看重的秸秆制品相关价值之一：情感价值 | 对情绪共鸣和体验氛围的感知偏好 | 是，作为前三价值之一时展示 |
| `latent_social_value_weight` | 最看重的秸秆制品相关价值之一：社会/责任价值 | 对社会责任、形象表达和共同参与的感知偏好 | 是，作为前三价值之一时展示 |
| `latent_hotel_class` | 最近一次入住锦江旗下酒店类型：中端酒店 | 酒店消费场景标签 | 是 |
| `latent_travel_purpose` | 最近一次入住锦江旗下酒店目的：休闲出行 | 酒店消费场景标签 | 是 |
| `latent_gender` | 不展示 | 合成画像标签 | 默认否 |
| `latent_age` | 不展示 | 合成画像标签 | 默认否 |
| `latent_education` | 不展示 | 合成画像标签 | 默认否 |
| `latent_monthly_income` | 不展示 | 合成画像标签 | 默认否 |

`environmental_consciousness` 表示用户整体环保意识倾向；`environmental value` 表示用户是否把“锦江使用秸秆制品”感知为有环保消费价值。两者必须在文档和 prompt builder 中保持区分。

### Post 输入标准

| 输入 | Prompt 表述 | 说明 |
|---|---|---|
| 营销文案 | 内容信息：原文 | 使用设计好的绿色营销文案 |
| 内容主要强调价值 | 内容主要强调了环保价值、健康价值、社会/责任价值 | 与六类消费价值维度对齐 |

三版绿色营销文案的默认价值摘要：

| 文案 | 内容主要强调价值 |
|---|---|
| Class 1 文案 | 环保价值、健康价值、社会/责任价值 |
| Class 2 文案 | 健康价值、功能价值、环保价值 |
| Class 3 文案 | 知识/新奇价值、环保价值、健康价值 |

### LLM Prompt 结构

System 情境应表达：

```text
你正在模拟一名抖音用户。某天，该用户无意间刷到一条关于锦江酒店集团使用秸秆制品、推进环保举措的营销内容。请你结合文案内容、用户特征和其他用户互动情况，判断该用户是否会互动，并选择最可能的互动动作。
```

User message 应按以下块组织：

```text
【营销内容】
<文案>

【内容主要强调的价值】
环保价值、健康价值、社会/责任价值

【用户可观测特征】
活跃度：中等偏高（0.65）
全平台影响力：较低（0.21）
锦江酒店社群内的局部影响力：中等（0.48）
兴趣标签：绿色消费、酒店、旅行

【用户消费偏好】
环保意识倾向：较强（1.037）
最看重的秸秆制品相关价值：环保价值、健康价值、社会/责任价值
最近一次入住锦江旗下酒店类型：中端酒店
最近一次入住锦江旗下酒店目的：休闲出行

【其他用户行为】
<同伴影响摘要>
```

### LLM 输出协议

| 字段 | 含义 | 允许值 |
|---|---|---|
| `engage` | 是否互动 | `true` / `false` |
| `action` | 互动动作 | `like` / `comment` / `share` / `ignore` |
| `probability` | 互动概率 | `0.0` 到 `1.0` |
| `confidence` | 判断置信度 | `0.0` 到 `1.0` |
| `reason` | 简短理由 | 1-2 句，不包含私密信息 |

规则：

- 如果 `engage = false`，则 `action = ignore`。
- 如果 `engage = true`，则 `action` 必须是 `like`、`comment`、`share` 之一。
- LLM 不能使用已删除字段。
- LLM 不能把合成画像标签描述为真实用户身份。

## 测试决策

- 测试应优先覆盖外部行为：加载数据后不再暴露删除字段、prompt 不包含删除字段、LLM 输出协议可校验、离线默认路径仍可运行。
- Dataset loader 测试应验证删除字段不会成为 `UserProfile` 的正式合同字段。
- Prompt builder 测试应验证 prompt 包含情境、营销内容、价值摘要、真实 profile 兴趣标签、三个真实观测指标、环保意识倾向、前三个消费价值、酒店类型、出游目的和同伴影响摘要。
- Prompt builder 测试应验证 prompt 不包含 `brand_attitude`、`like_tendency`、`comment_tendency`、`share_tendency`、`latent_class` 用户类型名称，以及默认不包含性别、年龄、教育、收入。
- Provider adapter 测试应继续使用 mocked provider，不触发 live API。
- Rule-based/offline baseline 测试应验证删除 preset 字段后仍能离线运行。
- 默认离线路径测试不应发起 live API；真实 LLM 只在显式 provider-backed 配置下运行。
- Processed variant 或 CSV 合同测试应验证最终锦江用户表不再输出删除字段。
- 文档导航测试应确保新 PRD 和后续架构说明可从 PRD README 或 docs index 找到。

## 超出范围

- 不重新采集 TikHub、Douyin 或其他 live API 数据。
- 不读取或打印 `.env`、API key、raw payload、nickname、bio、signature 或用户明细。
- 不重新设计 latent class 分配概率。
- 不把性别、年龄、教育、收入加入第一版 LLM prompt。
- 不在本 PRD 中决定具体 Provider、模型或成本预算。
- 不要求第一版实现真实 live LLM 批量实验；mocked provider 和 prompt contract 可以先完成。
- 不删除历史审计文档和 lineage 记录。

## 进一步说明

本 PRD 是对锦江 latent attributes v1 的后续收敛：v1 已经完成 latent 标签生成、runtime 解析和本地验收；本 PRD 解决“哪些字段真正应该进入 ABM 决策”和“LLM prompt 如何表达这些字段”的问题。

后续拆 issue 时建议顺序：

1. 清理 demo preset 字段的数据/schema/决策使用。
2. 建立 prompt field summary 和等级表述规则。
3. 实现锦江绿色营销 LLM prompt v2。
4. 更新文档，明确真实观测数据、观测分量、合成实验标签和 prompt 输入边界。
5. 用 mocked provider 验证 LLM 同时输出 `engage` 和 `action` 的完整流程。
