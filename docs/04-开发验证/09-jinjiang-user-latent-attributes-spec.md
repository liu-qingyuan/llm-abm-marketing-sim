# 锦江用户 Latent Attributes 新标签版本实施 Spec

## 目标

基于用户潜在属性研究文档为锦江酒店 Douyin final dataset 生成一套新的用户 latent attribute 标签版本，并把这些标签接入 ABM 用户对象与规则决策。

本方案目标不是推断用户真实人口属性或心理画像，而是根据外部研究表格构造一组**可复现、可调整、可解释的实验先验标签**，用于后续 LLM-ABM 初始化和分组实验。

设计原则：

- 不覆盖现有 final dataset，生成新的 processed variant。
- 不把分布逻辑写死在 TikHub 采集脚本里。
- 用结构化 spec 管理分布和权重，后续调整只改配置。
- CSV 保持可读、可统计；运行时用户对象保持结构化。
- 第一版使用文档先验，不用 Douyin 活跃度或影响力字段反向调整分布。

## 数据结构总览

本方案的用户数据结构按 [08 锦江用户数据结构简图](08-jinjiang-user-data-structure-diagrams.md) 理解：

```text
UserProfile = 真实观测数据 + 虚拟实验标签
```

- 真实观测数据来自 Douyin final dataset，例如 `comment_count`、`reply_count`、`edge_degree`、`activity_score` 和 influence scores。
- 虚拟实验标签来自用户潜在属性研究文档，例如 `latent_class`、6 个消费价值权重和 Table 11 画像标签。
- LLM 输入也按这两部分组织：一部分是可观测平台行为摘要，一部分是实验标签解释摘要。

## 输入依据

来源材料为用户潜在属性研究文档；中文整理见 [07 锦江用户潜在属性参考文档中文整理](07-jinjiang-user-latent-attributes-reference-zh.md)。

文档给出三类 latent class：

| class | allocation probability |
|---|---:|
| class_1 | 42.9% |
| class_2 | 41.4% |
| class_3 | 15.7% |

每个 class 有 6 个消费价值维度权重：

| value dimension | class_1 | class_2 | class_3 |
|---|---:|---:|---:|
| epistemic | -1.678 | -1.706 | 0.866 |
| environmental | 2.054 | 0.099 | 0.487 |
| functional | -0.938 | 1.544 | -0.831 |
| health | 1.502 | 2.634 | 0.310 |
| emotional | -1.517 | -1.047 | -0.489 |
| social | 0.576 | -1.525 | -0.343 |

文档还给出 `environmental_consciousness` 对 class allocation 的系数：

| class | environmental_consciousness coefficient |
|---|---:|
| class_1 | 1.037 |
| class_2 | -0.833 |
| class_3 | -0.205 |

第一版实现只保存该系数，不用它重新推断 class；class 分配严格按照 allocation probability 生成。

### Table 11: class membership profile distribution

Table 11 是 latent class 的用户构成画像，不是消费价值权重。第一版必须把它作为 `class_profile` 标签生成依据，用于后续分组分析和结果解释。

最近入住锦江酒店档次：

| hotel_class | class_1 | class_2 | class_3 |
|---|---:|---:|---:|
| economy | 0.371 | 0.351 | 0.315 |
| midscale | 0.359 | 0.470 | 0.274 |
| upper_midscale | 0.270 | 0.179 | 0.411 |

最近入住锦江的出行目的：

| travel_purpose | class_1 | class_2 | class_3 |
|---|---:|---:|---:|
| business | 0.427 | 0.212 | 0.319 |
| leisure | 0.573 | 0.788 | 0.681 |

性别：

| gender | class_1 | class_2 | class_3 |
|---|---:|---:|---:|
| female | 0.594 | 0.640 | 0.558 |
| male | 0.406 | 0.360 | 0.442 |

年龄：

| age | class_1 | class_2 | class_3 |
|---|---:|---:|---:|
| age_18_25 | 0.168 | 0.312 | 0.153 |
| age_26_35 | 0.405 | 0.361 | 0.351 |
| age_36_45 | 0.273 | 0.198 | 0.361 |
| age_46_55 | 0.096 | 0.101 | 0.064 |
| age_56_plus | 0.058 | 0.028 | 0.071 |

教育水平：

| education | class_1 | class_2 | class_3 |
|---|---:|---:|---:|
| high_school_or_below | 0.048 | 0.019 | 0.029 |
| community_college | 0.062 | 0.119 | 0.107 |
| bachelor | 0.656 | 0.737 | 0.647 |
| master_or_above | 0.234 | 0.124 | 0.217 |

月收入：

| monthly_income | class_1 | class_2 | class_3 |
|---|---:|---:|---:|
| income_8000_or_less | 0.302 | 0.507 | 0.276 |
| income_8001_15000 | 0.448 | 0.365 | 0.400 |
| income_15001_25000 | 0.212 | 0.103 | 0.286 |
| income_25001_40000 | 0.030 | 0.015 | 0.026 |
| income_40001_or_more | 0.009 | 0.011 | 0.012 |

实现边界：

- Table 11 生成的是模拟 class membership profile 标签，不代表 Douyin 用户真实人口属性。
- 第一版按每个 class 内的边际分布独立生成各字段，不构造字段之间的联合分布。
- Table 11 字段用于分组分析、审计和结果解释；第一版不直接进入 rule-based probability。

## 标签字段合同

### 结构化用户对象

在核心用户对象中增加 `latent_attributes`，建议结构如下：

```text
latent_attributes:
  spec_id: string
  method: string
  seed: int
  latent_class: class_1 | class_2 | class_3
  value_weights:
    epistemic: float
    environmental: float
    functional: float
    health: float
    emotional: float
    social: float
  class_profile:
    hotel_class: economy | midscale | upper_midscale
    travel_purpose: business | leisure
    gender: female | male
    age: age_18_25 | age_26_35 | age_36_45 | age_46_55 | age_56_plus
    education: high_school_or_below | community_college | bachelor | master_or_above
    monthly_income: income_8000_or_less | income_8001_15000 | income_15001_25000 | income_25001_40000 | income_40001_or_more
```

### CSV 扁平字段

新 variant 的 `users.csv`、`profiles.csv`、`abm_user_profiles.csv` 增加以下字段：

```text
latent_attribute_spec_id
latent_attribute_method
latent_attribute_seed
latent_class
latent_environmental_consciousness_coef
latent_epistemic_value_weight
latent_environmental_value_weight
latent_functional_value_weight
latent_health_value_weight
latent_emotional_value_weight
latent_social_value_weight
latent_hotel_class
latent_travel_purpose
latent_gender
latent_age
latent_education
latent_monthly_income
```

字段命名规则：

- 所有新列使用 `latent_` 前缀，避免和现有 profile index 字段混淆。
- value weights 保留 docx 原始系数，不强行归一化到 `[0, 1]`。
- 人口/入住标签是模拟实验标签，不表示真实用户身份。

## 分布生成规则

### 配置来源

新增结构化 spec 文件，例如：

```text
configs/latent_attributes/jinjiang_user_latent_attributes_v1.yaml
```

该 spec 是运行时唯一可信输入。用户潜在属性研究文档只作为来源材料，不在生产生成器中动态解析。

建议 spec 包含：

```text
spec_id: jinjiang_user_latent_attributes_v1
method: latent_class_exact_quota_v1
default_seed: 20260630
classes:
  class_1:
    probability: 0.429
    environmental_consciousness_coef: 1.037
    value_weights: ...
    profile_distributions:
      hotel_class: ...
      travel_purpose: ...
      gender: ...
      age: ...
      education: ...
      monthly_income: ...
  class_2: ...
  class_3: ...
```

### 精确配额

对 final dataset 的 `36,400` 个用户做 deterministic quota assignment。

第一步：按 class allocation probability 生成 latent class。class 目标计数按最大余数法从概率换算：

| class | probability | exact expected count | target count |
|---|---:|---:|---:|
| class_1 | 0.429 | 15615.6 | 15616 |
| class_2 | 0.414 | 15069.6 | 15070 |
| class_3 | 0.157 | 5714.8 | 5714 |

合计：`36,400`。

第二步：在每个 class 内，根据 Table 11 分别生成 membership profile 标签。每个字段都在 class 内独立按百分比分布换算成整数配额。

例如 class_1 的 gender：

```text
class_1_count = 15616
female target = round-by-largest-remainder(15616 * 0.594)
male target = remaining count
```

再例如 class_2 的 hotel_class：

```text
class_2_count = 15070
economy target = round-by-largest-remainder(15070 * 0.351)
midscale target = round-by-largest-remainder(15070 * 0.470)
upper_midscale target = remaining count after largest-remainder allocation
```

实现时应对以下字段分别执行 class 内配额分配：

| profile field | labels |
|---|---|
| hotel_class | economy, midscale, upper_midscale |
| travel_purpose | business, leisure |
| gender | female, male |
| age | age_18_25, age_26_35, age_36_45, age_46_55, age_56_plus |
| education | high_school_or_below, community_college, bachelor, master_or_above |
| monthly_income | income_8000_or_less, income_8001_15000, income_15001_25000, income_25001_40000, income_40001_or_more |

所有分配必须满足：

- 同一 `spec_id + seed + input user_id set` 生成结果完全一致。
- class 分配先确定，再在每个 class 内分配 hotel/travel/gender/age/education/income。
- Table 11 的每个 profile 字段都按 class 内边际分布单独做精确配额。
- Table 11 profile 字段只用于分组分析与报告解释，不参与第一版 rule-based 决策概率。
- 用户排序使用稳定键：`user_id` 字符串排序后结合 seed 洗牌。
- 不使用 nickname、bio、raw payload 或 API response 参与分配。

## 生成流程

建议新增独立模块，不放进 TikHub collector 主流程：

```text
src/llm_abm_sim/data_sources/latent_attributes.py
```

建议新增 CLI 或脚本入口：

```text
python scripts/generate_jinjiang_latent_attributes.py \
  --source-run data/processed/jinjiang_douyin/jinjiang-final-caption-hashtag-comments-profiles-20260624T092200Z \
  --spec configs/latent_attributes/jinjiang_user_latent_attributes_v1.yaml \
  --output-run-id jinjiang-final-caption-hashtag-comments-profiles-latent-v1-<timestamp> \
  --seed 20260630
```

输出目录：

```text
data/processed/jinjiang_douyin/<output-run-id>/
```

输出内容：

- 原 final run 中需要保留的 CSV 原样复制。
- `users.csv`、`profiles.csv`、`abm_user_profiles.csv` 增加 latent 字段。
- 新增 `latent_attribute_spec.yaml`，保存本次使用的 spec 快照。
- 新增 `latent_attribute_audit.json` / `latent_attribute_audit.md`。
- 新增 `README.md`，说明该 run 是 latent-v1 派生版本。

不做：

- 不触发 TikHub live API。
- 不读取 `.env`。
- 不覆盖 source run。
- 不删除历史 run。

## ABM 决策接入

### PostContent 增加内容价值向量

`PostContent` 增加 `value_dimensions`：

```text
value_dimensions:
  epistemic: float = 0.0
  environmental: float = 0.0
  functional: float = 0.0
  health: float = 0.0
  emotional: float = 0.0
  social: float = 0.0
```

含义：当前营销内容突出哪些消费价值维度。例如环保主题内容可设置：

```yaml
value_dimensions:
  environmental: 1.0
  health: 0.4
  social: 0.2
```

### RuleBasedDecisionAdapter 增加 latent score

新增可配置项：

```text
latent_value_weight: 0.10
```

规则决策计算：

```text
latent_raw_score =
  dot(user.latent_attributes.value_weights, post.value_dimensions)

latent_value_score =
  normalize(latent_raw_score to [0, 1])
```

然后进入 baseline：

```text
probability_score =
  existing_baseline_terms
+ latent_value_weight * latent_value_score
```

第一版建议：

- 默认 `latent_value_weight = 0.10`。
- 没有 `latent_attributes` 或没有 `post.value_dimensions` 时，`latent_value_score = 0`。
- 只有 6 个消费价值维度权重进入 `latent_value_score`。
- `latent_hotel_class`、`latent_travel_purpose`、`latent_gender`、`latent_age`、`latent_education`、`latent_monthly_income` 第一版只用于分组分析，不直接影响 probability。
- 最终 probability 继续裁剪到 `[0, 1]`。
- Provider-backed LLM prompt 不直接裸露 raw coefficients；如需接入 latent attributes，使用 compact summary 形式描述用户所属 class、主要价值偏好和必要边界提示。

### LLM 输入解释口径

LLM 决策输入分为两部分：

```text
真实观测信息：
用户在锦江相关 Douyin 数据中的活跃度、影响力代理指标和互动网络位置。

虚拟实验标签解释：
用户在本次仿真实验中的 latent class、主要价值偏好，以及必要的入住场景标签。
```

LLM prompt 必须明确：

- 价值偏好只指用户对锦江酒店秸秆产品或相关绿色服务的感知价值，不代表泛化人格或长期消费观。
- Table 11 画像标签是仿真实验设定，不代表真实 Douyin 用户身份。
- 默认不要把 raw coefficients、完整 Table 11 标签和本地来源路径直接塞入 prompt；优先使用短摘要降低 token 消耗和误读风险。

## 审计与验收

### 数据验收

生成后必须满足：

- `users.csv` 行数仍为 `36,400`。
- `profiles.csv` 行数仍为 `36,400`。
- `abm_user_profiles.csv` 行数仍为 `36,400`。
- 三张用户表的 `user_id` 集合完全一致。
- 每个用户都有非空 `latent_class`。
- 每个用户都有 6 个 value weight。
- class target count 符合：
  - `class_1 = 15,616`
  - `class_2 = 15,070`
  - `class_3 = 5,714`
- 每个 class 内各 Table 11 profile 属性计数与 spec 配额一致。

### 审计报告

`latent_attribute_audit.json/.md` 至少包含：

- `source_run`
- `output_run`
- `spec_id`
- `method`
- `seed`
- `user_count`
- class target vs actual counts
- 每个 class 内每个 Table 11 profile attribute 的 target vs actual counts
- 最大比例偏差
- 隐私声明：只使用 `user_id` 做稳定分配，不使用昵称、bio、raw payload、凭证或 live API

### 测试验收

需要覆盖：

- spec schema 校验：概率字段完整、每组分布合计约等于 1。
- Table 11 schema 校验：每个 class 都包含 hotel/travel/gender/age/education/income 分布。
- quota 工具：最大余数法总数精确、固定 seed 稳定。
- assignment：同一输入多次生成完全一致。
- Table 11 assignment：每个 class 内 profile 标签计数符合配额。
- loader：CSV 扁平 latent 字段能解析成 `UserProfile.latent_attributes`。
- backward compatibility：没有 latent 字段的旧 profiles 仍能加载。
- decision：`value_dimensions` 与 latent weights 会影响 rule-based probability；关闭 latent 权重时回到旧 baseline。
- decision：Table 11 profile 标签不影响第一版 rule-based probability。
- integration：对 36,400 用户生成 latent-v1 variant 并通过 audit。

建议验证命令：

```bash
. .venv/bin/activate
python -m py_compile $(find src tests scripts -name '*.py' -print)
pytest -q
ruff check src/llm_abm_sim/data_sources tests scripts
pyright src/llm_abm_sim/data_sources tests scripts
```

## 后续扩展

第一版完成后，可扩展：

- 支持 `observed_adjusted` 分配策略，用 Douyin activity/influence 对 class prior 做弱调整。
- 支持多个 latent spec 并行生成，用于敏感性分析。
- 将 latent attributes 注入 provider-backed LLM prompt。
- 在报告中按 latent class 展示传播结果差异。
- 为论文方法部分补充“实验先验标签”与“非真实画像”的说明。
