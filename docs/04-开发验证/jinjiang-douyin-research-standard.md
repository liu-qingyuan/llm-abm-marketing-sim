# 锦江酒店抖音社交网络与绿色营销仿真标准

本文记录 2026 年 6 月至 10 月 15 日后续工作的标准要求。后续数据采集、网络构建、仿真模型、实验运行和论文写作，均应优先对齐本文。

## 1. 总体目标

围绕抖音平台上与锦江酒店相关的内容，构建“锦江酒店抖音社交网络”，并在该网络上模拟不同绿色营销消息的传播效果。

核心研究链路：

```text
抖音数据采集
-> 有向互动网络构建
-> Douyin 用户 Agent 建模
-> 绿色营销帖子设计
-> 30 天传播仿真
-> 不同消息效果比较
-> 方法与结果写作
```

## 2. 时间线与交付要求

| 时间 | 主要任务 | 核心交付 |
|---|---|---|
| 2026 年 6 月–7 月 | 开发锦江酒店抖音社交网络 | 数据采集方案、原始/清洗数据表、有向互动网络、边权计算规则 |
| 2026 年 7 月–8 月 | 构建仿真模型 | Douyin 用户 Agent、绿色营销帖子、平台环境、30 步仿真机制 |
| 2026 年 8 月–9 月 | 运行仿真实验 | 多类绿色营销消息对比结果、传播模式、分群差异 |
| 2026 年 9 月–10 月 15 日 | 写作 | 方法章节、仿真结果章节、图表和附录说明 |

## 3. 阶段一：锦江酒店抖音社交网络开发（2026 年 6 月–7 月）

### 3.1 数据采集范围

围绕话题标签 `#锦江酒店`，采集过去 12 个月内发布的视频及其互动数据。

建议以采集日期为准定义窗口，例如若采集日为 2026 年 6 月，则时间范围约为 2025 年 6 月至 2026 年 6 月。实际执行时应在数据字典中记录精确起止日期。

### 3.2 视频数据

每条视频至少记录：

| 字段 | 含义 |
|---|---|
| `video_id` | 视频唯一 ID |
| `video_url` | 视频链接或可回溯定位信息 |
| `publish_time` | 发布时间 |
| `caption` | 视频标题/文案 |
| `hashtags` | 话题标签列表，必须包含或关联 `#锦江酒店` |
| `creator_user_id` | 创作者用户 ID |
| `like_count` | 点赞数，如可获得 |
| `comment_count` | 评论数，如可获得 |
| `share_count` | 分享数，如可获得 |
| `collect_count` | 收藏数，如可获得 |

### 3.3 评论与再评论数据

每条视频下采集评论和再评论，即一级评论与评论回复。

每条评论至少记录：

| 字段 | 含义 |
|---|---|
| `comment_id` | 评论唯一 ID |
| `video_id` | 所属视频 ID |
| `parent_comment_id` | 父评论 ID；一级评论可为空 |
| `commenter_user_id` | 评论者用户 ID |
| `content` | 评论内容 |
| `publish_time` | 评论发布时间 |
| `mentioned_user_ids` | 评论中被 @ 的用户 ID 列表，如可解析 |
| `like_count` | 评论点赞数，如可获得 |

再评论可使用同一张评论表表示：当 `parent_comment_id` 非空时，该记录为回复。

### 3.4 用户属性数据

对视频创作者、评论者、再评论者均采集用户属性。

每个用户至少记录：

| 字段 | 含义 |
|---|---|
| `user_id` | 用户唯一 ID |
| `nickname` | 昵称；后续公开文档和提交版本中应脱敏或避免展示 |
| `follower_count` | 粉丝数 |
| `following_count` | 关注数，如可获得 |
| `video_count` | 发布视频数，如可获得 |
| `verified_type` | 是否官方号、企业号、认证号、KOL 等，如可获得 |
| `bio` | 简介；含个人敏感信息时不得提交原文 |
| `observed_activity_level` | 基于发布/评论/回复频率计算的活跃度 |
| `observed_influence` | 基于粉丝数、互动数、被回复/@ 次数等计算的影响力 |

### 3.5 数据合规与安全要求

- 采集方式应遵守抖音平台规则、学校/机构伦理要求和适用法律法规。
- 原始数据不得提交到仓库；建议存放在被 git 忽略的 `data/raw/`。
- 清洗后数据可放在 `data/processed/`，但含昵称、简介、链接、可识别用户信息时仍不得提交。
- 可提交样例只能使用小型合成数据或充分匿名化数据。
- 文档、日志、测试快照和运行产物不得包含 cookie、token、账号凭证、请求头或私密用户信息。

## 4. 阶段二：有向网络构建规则

### 4.1 节点定义

网络节点为抖音用户，包括：

- 视频创作者；
- 一级评论者；
- 再评论者；
- 被 @ 提及的用户，如能解析到用户 ID。

### 4.2 有向边定义

网络为 directed network。有向边表示从源用户到目标用户的互动或影响关系。

建议规则：

| 互动类型 | source user | target user | 说明 |
|---|---|---|---|
| 一级评论 | 评论者 | 视频创作者 | 用户对视频创作者内容产生互动 |
| 回复评论 | 回复者 | 被回复评论者 | 用户对另一个用户的评论产生互动 |
| @ 提及 | 提及者 | 被 @ 用户 | 用户显式指向另一个用户 |
| 视频发布 | 创作者 | 观看/互动用户 | 可选；若建传播 exposure 网络，可表示内容从创作者流向互动者 |

### 4.3 边权计算

边权通过累计互动次数获得。基础公式：

```text
weight(source, target) = comments_count + replies_count + mentions_count
```

如需区分互动强度，可使用加权公式：

```text
weight(source, target)
= 1.0 * 一级评论次数
+ 1.5 * 回复次数
+ 1.2 * @提及次数
```

权重方案必须在方法章节中固定说明，并在代码/配置中可复现。

### 4.4 网络输出格式

建议生成边列表：

```csv
source,target,weight,comment_count,reply_count,mention_count,first_interaction_time,last_interaction_time
u001,u010,3.7,1,1,1,2026-01-05T10:30:00,2026-03-08T18:20:00
```

用户画像表：

```csv
user_id,user_type,follower_count,observed_activity_level,observed_influence,value_proposition
u001,KOL,120000,0.82,0.91,green_quality
```

## 5. 阶段三：仿真模型构建（2026 年 7 月–8 月）

### 5.1 Agent：抖音用户

每个 Agent 表示一个抖音用户。

#### Agent 属性

| 属性 | 来源 | 说明 |
|---|---|---|
| `user_id` | 抖音数据 | 用户唯一标识 |
| `value_proposition` | 识别/分类结果 | 用户对绿色营销价值主张的偏好类型 |
| `activity_level` | 观测数据计算 | 用户活跃度，如发布、评论、回复频率 |
| `influence` | 观测数据计算 | 用户影响力，如粉丝数、互动数、被回复/@ 次数 |
| `follower_count` | 抖音数据 | 粉丝数 |
| `active_periods` | 观测或估计 | 用户更可能活跃的时间段 |
| `engagement_history` | 仿真状态 | 是否已曝光、已互动、互动动作等 |

#### Agent 动作

Agent 在每个 time step 对帖子做二元互动决策：

```text
engage / not engage
```

决策依据：

1. post content：绿色营销消息内容；
2. peer influence：邻居曝光与互动情况；
3. individual attributes：价值主张、活跃度、影响力等；
4. active periods：用户是否处于活跃期；
5. LLM-supported reasoning：使用 LLM 或规则基线生成结构化理由。

输出仍保持结构化：

```text
engage: bool
probability: 0.0 到 1.0
reason: 简短理由
confidence: 0.0 到 1.0
action: like / comment / share / ignore
```

### 5.2 Posts：绿色营销消息类型

设计多种绿色营销消息，用于仿真对比。示例分类：

| 类型 | 说明 | 示例方向 |
|---|---|---|
| 环保运营型 | 强调节能减排、减少一次性用品、绿色客房 | “低碳入住”“减少塑料” |
| 健康舒适型 | 强调绿色材料、健康睡眠、空气质量 | “安心住”“健康空间” |
| 社会责任型 | 强调企业 ESG、公益、社区责任 | “可持续旅行”“绿色公益” |
| 经济激励型 | 强调绿色选择带来的优惠或积分 | “绿色入住积分奖励” |
| 情感认同型 | 强调消费者参与环保、身份认同 | “和锦江一起低碳旅行” |

每条帖子应记录：

| 字段 | 含义 |
|---|---|
| `post_id` | 仿真帖子 ID |
| `message_type` | 绿色营销消息类型 |
| `text` | 帖子文本 |
| `topic_tags` | 话题标签 |
| `media_summary` | 图片/视频素材摘要 |
| `target_value_propositions` | 主要面向的用户价值主张 |
| `active_period_days` | 活跃推荐期，标准为 7 天 |

### 5.3 Environment：锦江酒店抖音社交网络

环境基于阶段一构建的 directed network。

环境动作包括：

1. post publication：种子用户首先发布帖子；
2. dissemination：用户互动后带来邻居曝光；
3. platform recommendation：在帖子活跃期内，平台根据用户价值主张和帖子类型推荐内容。

### 5.4 仿真机制

标准仿真设置：

| 参数 | 标准值 | 说明 |
|---|---|---|
| `horizon` | 30 | 仿真 30 个 time steps |
| `time_step` | 1 天 | 每一步代表 1 天 |
| `post_active_period` | 7 天 | 每条帖子发布后 7 天内处于平台推荐活跃期 |
| `seed_users` | 官方账号、KOL 等影响力用户 | 首先发布或扩散帖子 |
| `network_type` | directed weighted network | 边权来自评论、回复、@ 等互动累计 |

推荐逻辑：

```text
在帖子发布后的 7 天活跃期内，平台优先把帖子推荐给价值主张匹配的用户；
用户是否互动由帖子内容、个人属性、同伴影响和活跃期共同决定；
互动用户继续作为后续扩散影响源。
```

## 6. 阶段四：运行仿真实验（2026 年 8 月–9 月）

对不同绿色营销消息进行比较。核心比较指标：

### 6.1 总互动量

包括：

- 总 engagement 数；
- 点赞、评论、分享数量；
- 每日新增互动；
- 30 天累计互动曲线。

### 6.2 传播模式

包括：

- 扩散深度；
- 扩散速度；
- 关键传播路径；
- KOL/官方号触发的传播差异；
- 7 天活跃推荐期内外的传播变化。

### 6.3 不同用户群体的 reach 与 interaction 差异

按用户群体比较：

- 不同 value proposition 用户；
- 高/中/低活跃用户；
- 高/中/低影响力用户；
- 官方账号、KOL、普通用户；
- 不同社群或网络位置的用户。

建议输出表：

| message_type | total_engagement | reach | engagement_rate | max_depth | avg_daily_engagement | top_user_group |
|---|---:|---:|---:|---:|---:|---|
| 环保运营型 |  |  |  |  |  |  |
| 健康舒适型 |  |  |  |  |  |  |
| 社会责任型 |  |  |  |  |  |  |

## 7. 阶段五：写作（2026 年 9 月–10 月 15 日）

### 7.1 方法章节应说明

- 数据来源：`#锦江酒店` 过去 12 个月视频、评论、再评论和用户属性；
- 数据采集窗口和清洗规则；
- 有向网络构建方法；
- source、target、weight 定义；
- 用户属性与 value proposition 识别方法；
- Agent 决策机制；
- 绿色营销消息设计；
- 30 天、每日一步、7 天活跃期、seed users 的仿真设置；
- LLM-supported reasoning 如何被约束为结构化决策；
- 复现设置：随机种子、配置文件、运行次数。

### 7.2 结果章节应呈现

- 不同绿色营销消息的总互动量对比；
- 传播曲线和传播深度对比；
- 不同用户群体的 reach / interaction 差异；
- 官方账号/KOL 作为 seed users 的影响；
- 7 天活跃推荐期对传播的影响；
- 关键发现和管理启示。

## 8. 与当前代码项目的对齐

当前 `llm-abm-marketing-sim` 已有能力可直接承接该标准：

| 新标准需求 | 当前项目对应能力 | 后续需要补充 |
|---|---|---|
| 抖音数据导入 | `dataset` edge/profile loader | 新增 Douyin 数据清洗脚本与字段映射 |
| 有向边权网络 | NetworkX directed graph + edge weight | 固化 comment/reply/@ 权重规则 |
| 用户 Agent | `SocialUserAgent` + `UserProfile` | 扩展 value proposition、active periods、influence 字段 |
| 二元互动决策 | `LLMDecisionAdapter` + `EngageDecision` | Prompt 中加入 Douyin 场景和绿色营销消息类型 |
| 30 天仿真 | `SimulationConfig.horizon` | 默认研究配置设为 30 |
| 7 天活跃期 | `PlatformContext` / exposure 规则 | 增加 post-level active period 推荐逻辑 |
| seed users | `simulation.seed_user_ids` | 从官方账号/KOL 自动或半自动筛选 |
| 指标比较 | `MetricsCollector` + outputs | 增加分用户群体指标和多消息对比 runner |

## 9. 推荐新增配置形态

后续可新增研究配置，例如：

```yaml
run_id: jinjiang-douyin-green-marketing
random_seed: 202606
simulation:
  horizon: 30
  time_step_label: day
  seed_user_ids: [official_jinjiang, kol_001, kol_002]
post:
  post_id: green-message-001
  text: "和锦江一起开启低碳旅行"
  topic_tags: [锦江酒店, 绿色旅行, 低碳入住]
  media_summary: "酒店绿色客房与低碳出行动画短视频"
  active_period_days: 7
  message_type: emotional_identity
network:
  directed: true
dataset:
  edge_list_path: ../../data/processed/jinjiang_douyin_edges.csv
  profile_path: ../../data/processed/jinjiang_douyin_profiles.csv
  profile_format: csv
  source_column: source
  target_column: target
  edge_weight_column: weight
  edge_attribute_columns: [comment_count, reply_count, mention_count]
```

## 10. 标准验收清单

### 数据阶段

- [ ] 明确过去 12 个月的采集起止日期。
- [ ] 视频、评论、再评论、用户属性字段完整。
- [ ] 原始数据与清洗数据分离存放。
- [ ] 用户可识别信息已脱敏或不进入仓库。
- [ ] 有向边 source、target、weight 规则固定。

### 模型阶段

- [ ] Agent 包含 value proposition、activity、influence、active periods。
- [ ] 帖子包含绿色营销消息类型和 7 天活跃期。
- [ ] 环境支持发布、传播、平台推荐。
- [ ] 仿真为 30 个 time steps，每步 1 天。
- [ ] seed users 来自官方账号、KOL 或其他高影响力用户。

### 实验阶段

- [ ] 至少比较多种绿色营销消息。
- [ ] 输出总互动量、传播模式、分群 reach/interaction。
- [ ] 结果可由配置、随机种子和数据版本复现。

### 写作阶段

- [ ] 方法章节解释数据、网络、Agent、帖子、环境、仿真机制。
- [ ] 结果章节包含图表和分群比较。
- [ ] 明确数据合规、隐私保护和 LLM 决策约束。
