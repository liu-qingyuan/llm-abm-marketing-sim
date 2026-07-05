# 锦江 final dataset latent-v1 本地验收记录（2026-07-05）

Status: Dataset Validation Reference
Related issue: `#17`
Source dataset audit: [`jinjiang-final-dataset-audit-20260624.md`](jinjiang-final-dataset-audit-20260624.md)

## 验收对象

| 项 | 值 |
|---|---|
| source run | `jinjiang-final-caption-hashtag-comments-profiles-20260624T092200Z` |
| source path | `data/processed/jinjiang_douyin/jinjiang-final-caption-hashtag-comments-profiles-20260624T092200Z` |
| output run | `jinjiang-final-caption-hashtag-comments-profiles-latent-v1-validation-20260705T000000Z` |
| output path | `data/processed/jinjiang_douyin/jinjiang-final-caption-hashtag-comments-profiles-latent-v1-validation-20260705T000000Z` |
| spec | `configs/latent_attributes/jinjiang_user_latent_attributes_v1.yaml` |
| spec id | `jinjiang_user_latent_attributes_v1` |
| method | `latent_class_exact_quota_v1` |
| seed | `20260630` |
| user count | `36,400` |

本次验收使用公开生成入口：

```bash
/tmp/llm-abm-marketing-sim-venv/bin/python scripts/generate_jinjiang_latent_attributes.py \
  --source-processed-dir data/processed/jinjiang_douyin/jinjiang-final-caption-hashtag-comments-profiles-20260624T092200Z \
  --spec configs/latent_attributes/jinjiang_user_latent_attributes_v1.yaml \
  --output-run-id jinjiang-final-caption-hashtag-comments-profiles-latent-v1-validation-20260705T000000Z \
  --seed 20260630
```

生成目录位于 `data/processed/` 下，按仓库规则被 `.gitignore` 忽略；本仓库提交不包含用户明细 CSV/JSONL。

## 行数与用户集合

| 表 | rows | unique user_id |
|---|---:|---:|
| `users.csv` | 36,400 | 36,400 |
| `profiles.csv` | 36,400 | 36,400 |
| `abm_user_profiles.csv` | 36,400 | 36,400 |

验收结果：

- `users.csv`、`profiles.csv`、`abm_user_profiles.csv` 的 `user_id` 集合一致。
- output run 的 `users.csv` 用户集合与 source run 的 `users.csv` 用户集合一致。
- `abm_user_profiles.csv` 中 `latent_class` 非空用户数为 36,400。
- `abm_user_profiles.csv` 中 6 个 latent value weight 均非空的用户数为 36,400。

## Class counts

| class | target | actual |
|---|---:|---:|
| `class_1` | 15,616 | 15,616 |
| `class_2` | 15,070 | 15,070 |
| `class_3` | 5,714 | 5,714 |

`latent_attribute_audit.json` 汇总：

| 指标 | 值 |
|---|---:|
| `max_count_deviation` | 0 |
| `max_proportion_deviation` | 0.0 |

## Table 11 profile counts

审计覆盖每个 class 内的 6 个 Table 11 profile fields：`hotel_class`、`travel_purpose`、`gender`、`age`、`education`、`monthly_income`。

| 指标 | 值 |
|---|---:|
| class-field groups | 18 |
| label count rows | 63 |
| max label count deviation | 0 |
| max label proportion deviation | 0.0 |

最大偏差样本仍为 0：`class_3 / travel_purpose / leisure` target = 3,891，actual = 3,891。

## Loader contract smoke

使用 `load_network_dataset` 对 output run 的 `abm_user_profiles.csv` 做 profile-only smoke，验证扁平 `latent_` columns 可解析为结构化 `UserProfile.latent_attributes`。

| 指标 | 值 |
|---|---:|
| graph nodes after `INCLUDE_AS_NODE` | 36,400 |
| profile records | 36,400 |
| profiles | 36,400 |
| profiles with structured latent attributes | 36,400 |

## 隐私与边界

- 本次分配只使用稳定 `user_id` 和 latent spec；不使用 nickname、bio、signature、raw payload、凭证或 live provider。
- 未读取 `.env`，未打印 API key、token、cookie、Authorization 或会话凭证。
- 未读取 `data/raw/`，未调用 TikHub、Douyin 或 LLM live API。
- latent labels 是 Virtual Experiment Labels，仅用于仿真分组和实验解释；不代表 Douyin 用户真实身份、真实人口属性、第三方认证标签或真实心理画像。
- Table 11 profile labels 是 class membership profile 的仿真实验标签，第一版不作为 rule-based probability 的直接输入。

## 验证命令

```bash
/tmp/llm-abm-marketing-sim-venv/bin/python scripts/generate_jinjiang_latent_attributes.py ...
/tmp/llm-abm-marketing-sim-venv/bin/python - <<'PY'
# aggregate-only row count, class count, audit deviation, and loader smoke checks
PY
```

后续代码验证结果见 issue `#17` 完成评论。
