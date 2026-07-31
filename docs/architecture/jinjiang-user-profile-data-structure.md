# Architecture Note: 锦江用户数据结构

Status: Implemented current architecture note
Scope: Jinjiang Douyin final dataset profile model and implemented latent attributes boundary

该 Note 持有当前用户画像与 latent attributes 的稳定边界。研究先验见 [`../references/jinjiang-user-latent-attributes-reference-zh.md`](../references/jinjiang-user-latent-attributes-reference-zh.md)；真实 final dataset lineage 见 [`../references/jinjiang-final-dataset-audit-20260624.md`](../references/jinjiang-final-dataset-audit-20260624.md) 和 [`../references/jinjiang-final-dataset-latent-v1-validation-20260705.md`](../references/jinjiang-final-dataset-latent-v1-validation-20260705.md)。

## 当前模型

```text
UserProfile = Observed Profile Attributes + optional Latent Attributes
```

Observed Profile Attributes 来自锦江 Douyin final dataset，包含用户身份键、互动行为、网络位置和可观测代理指标。Latent Attributes 是可复现、可审计的合成实验标签，不是 Douyin 用户真实人口属性、心理画像或第三方认证标签。

| 部分 | 来源 | 用途 | 当前状态 |
|---|---|---|---|
| Observed Profile Attributes | final processed dataset | 用户活动、影响力和互动网络位置 | 已进入 `UserProfile` |
| `latent_attributes` | `configs/latent_attributes/jinjiang_user_latent_attributes_v1.yaml` 与离线 variant generator | latent class、六维 value weights、Table 11 profile labels | 已接入 runtime contract |
| `PostContent.value_dimensions` | typed post content | 声明 message 突出的消费价值维度 | 已接入，多 message ranking 使用 |

## `interest_tags` 边界

GitHub #72/#75 已撤销把 `interest_tags` 作为锦江真实观测画像、历史兴趣代理或 Prompt 输入的现行承诺。当前 processed variant 的 `users.csv`、`profiles.csv` 和 `abm_user_profiles.csv` 不把它作为锦江字段；runtime 创建通用 `UserProfile` 时保持默认空列表，不从 `historical_tags`、nickname、bio、signature 或其他字段回填。

`historical_tags` 仍是 Historical Behavioral Evidence，只用于 `historical_tag_affinity` Ranking，不进入 Prompt。通用 `UserProfile.interest_tags` 和非锦江 rule-based 路径继续保持兼容；该兼容性不改变锦江 current contract。

## Latent runtime contract

完整 processed variant 的 `latent_` columns 会由 loader 恢复为结构化对象：

```text
latent_attributes:
  spec_id: jinjiang_user_latent_attributes_v1
  method: latent_class_exact_quota_v1
  seed: <integer>
  latent_class: class_1 | class_2 | class_3
  environmental_consciousness_coef: <float>
  value_weights:
    epistemic: <float>
    environmental: <float>
    functional: <float>
    health: <float>
    emotional: <float>
    social: <float>
  profile_labels:
    hotel_class: <label>
    travel_purpose: <label>
    gender: <label>
    age: <label>
    education: <label>
    monthly_income: <label>
```

`src/llm_abm_sim/data_sources/latent_attributes.py` 负责离线 spec 校验、稳定 seed assignment、quota、aggregate audit 和 snapshot；`latent_processed_variant.py` 与生成脚本只生成新的 processed variant，不调用 live API、不覆盖 source run、不删除数据。

`RuleBasedDecisionAdapter` 只消费 runtime `UserProfile.latent_attributes` 与 `PostContent.value_dimensions`；它不读取研究 Markdown、spec 或 audit 文件。report 只输出 aggregate latent group metrics，不展示用户级 latent 明细。

## 使用限制

- latent class、value weights 和 Table 11 labels 是 synthetic experiment labels，只用于实验构造、审计、分组分析和结果解释。
- 六维 value weights 只适用于锦江酒店秸秆产品或相关绿色服务语境，不代表长期人格或整体消费观。
- Table 11 labels 不等同真实人口属性；当前 rule-based probability 不直接使用这些 labels。
- 36,400 用户完整 provider-backed LLM experiment 尚未执行；任何新的 Formal Run 都必须有独立授权。
- `PostContent.value_dimensions` 的字段定义和三条 message source 由 [`../references/PostContent.md`](../references/PostContent.md) 持有。

## 相关实现

- `src/llm_abm_sim/schemas.py`：通用 `UserProfile`、`PostContent` 和 typed contract。
- `src/llm_abm_sim/graph_loader.py`：profile loading 与 latent field projection。
- `src/llm_abm_sim/data_sources/latent_attributes.py`：离线 assignment seam。
- `src/llm_abm_sim/data_sources/latent_processed_variant.py`：processed variant adapter。
- `scripts/generate_jinjiang_latent_attributes.py`：显式生成入口。
