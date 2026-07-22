# 锦江 `interest_tags` 合同撤销聚合审计（2026-07-23）

Status: Dataset Contract Audit Reference
Related spec: GitHub #72
Related implementation: GitHub #75

## 审计对象

本次只读审计使用权威 latent-v1 processed variant：

```text
data/processed/jinjiang_douyin/
  jinjiang-final-caption-hashtag-comments-profiles-latent-v1-validation-20260705T000000Z/
```

该目录包含 36,400 位用户。审计只读取三张 CSV 的 header、行数和 `interest_tags` 单列，不输出用户记录，也不读取 nickname、bio、signature 或其他自由文本。

## 聚合结果

| 表 | rows | `interest_tags` 列 | 语义非空 |
|---|---:|---|---:|
| `users.csv` | 36,400 | 无 | 不适用 |
| `profiles.csv` | 36,400 | 有 | 0 / 36,400 |
| `abm_user_profiles.csv` | 36,400 | 有 | 0 / 36,400 |

两个 profile 表的列值均解析为字符串列表后统计；序列化空列表 `[]` 按空值处理，不按非空字符串误计为标签覆盖。

## 合同结论

- 权威 `users.csv` 没有该字段，两个兼容 profile 表也没有任何实际标签值，因此不存在把它作为锦江真实画像或 Prompt 输入的覆盖证据。
- GitHub #19、#63 与 #66 中把该字段描述为锦江真实观测字段、历史兴趣代理或 Prompt 输入的现行合同，由 #72/#75 的 ranking v5 与 Prompt v3 撤销。
- `historical_tags` 是独立的 Historical Behavioral Evidence，继续只用于 `historical_tag_affinity` Ranking；本审计不允许把它复制、改名或回填为用户兴趣画像。
- 通用 `UserProfile.interest_tags` 继续服务默认示例、toy dataset 和非锦江 rule-based 仿真；本次只收敛锦江 Final Research Interface。

## 方法与边界

审计使用 Python `csv.DictReader` 流式计数，并用 `ast.literal_eval` 解析该单列的列表序列化。没有把本地大型 CSV、用户明细或新数据产物加入 Git。

本次没有调用 LLM Provider、TikHub、Douyin 或其他 live API；没有读取 `data/raw/`、`.env`、密钥、原始 Prompt 或 raw Provider payload。
