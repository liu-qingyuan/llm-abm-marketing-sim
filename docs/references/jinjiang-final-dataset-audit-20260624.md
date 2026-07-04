# 锦江酒店 Douyin 最终数据集审计（2026-06-24）

Status: Dataset Audit Reference
Legacy source: `docs/04-开发验证/05-jinjiang-douyin-final-dataset-20260624.md`（已删除；迁移索引见 [`../04-开发验证/README.md`](../04-开发验证/README.md)）

## 最终数据集

- final run: `jinjiang-final-caption-hashtag-comments-profiles-20260624T092200Z`
- processed path: `data/processed/jinjiang_douyin/jinjiang-final-caption-hashtag-comments-profiles-20260624T092200Z`
- live API collection in this step: `false`
- profile raw evidence retained: `data/raw/tikhub/douyin/jinjiang_hotel/jinjiang-profile-expansion-derived-20260622T151059Z-batch-full`

## 输入来源

| 输入 | 路径 | 用途 |
|---|---|---|
| 话题/评论/视频/边表 | `data/processed/jinjiang_douyin/jinjiang-caption-hashtag-comments-excluding-binguan-adding-jian-derived-20260621T025127Z` | 研究语料、互动网络与视频分母 |
| 完整 profile 扩展 | `data/processed/jinjiang_douyin/jinjiang-profile-expansion-derived-20260622T151059Z-batch-full` | 36,400 个用户 profile 与 ABM 用户画像 |

## 聚合计数

| 表 | 行数 |
|---|---:|
| videos.csv | 4212 |
| target_video_manifest.csv | 4212 |
| comments.csv | 50640 |
| all_comments.csv | 50640 |
| edges.csv | 47624 |
| users.csv | 36400 |
| profiles.csv | 36400 |
| abm_user_profiles.csv | 36400 |

## 验收结果

- final users: 36,400 unique `user_id`
- final profiles: 36,400 unique `user_id`
- ABM user profiles: 36,400 unique `user_id`
- profile failed users: 0
- topic users / final users / profiles / ABM profiles 的 `user_id` 集合完全对齐
- comments/all_comments/edges 行数保持源话题数据集不变
- scope exclusions absent: `7486704870804770107`, `7486891790218399034`, `#锦江宾馆`, `#临空锦江宾馆`

## Profile 指标方法更新（2026-06-29）

- method: `log1p_p95_reference_weighted_v2`
- variant: `base`
- offline recompute only: `true`
- robustness report: `data/processed/jinjiang_douyin/jinjiang-final-caption-hashtag-comments-profiles-20260624T092200Z/profile_index_robustness_report.md`
- JSON report: `data/processed/jinjiang_douyin/jinjiang-final-caption-hashtag-comments-profiles-20260624T092200Z/profile_index_robustness_report.json`

本次执行 breaking schema cleanup：最终数据集不再输出旧兼容字段，当前标准只保留三类可观测代理变量：

| 指标 | 字段 | 解释边界 |
|---|---|---|
| Activity | `activity_score` | 用户在本研究语境中的内容生产、评论、回复活跃度代理 |
| Global Influence | `global_influence_score` | 基于 `follower_count` 的平台潜在覆盖力代理 |
| Local Influence | `local_influence_score` | 基于评论网络连接与评论获赞的锦江语境局部影响力代理 |

归一化方式：

```text
Norm(x) = min(1, ln(1 + x) / ln(1 + P95))
```

P95 thresholds:

| signal | P95 |
|---|---:|
| video_count | 775 |
| comment_count | 0 |
| reply_count | 3 |
| follower_count | 7851 |
| edge_degree | 5 |
| comment_like_sum | 3 |

基准公式：

```text
activity_score =
  0.25 * Norm(video_count)
+ 0.45 * Norm(comment_count)
+ 0.30 * Norm(reply_count)

global_influence_score = Norm(follower_count)

local_influence_score =
  0.60 * Norm(edge_degree)
+ 0.40 * Norm(comment_like_sum)
```

Schema 边界：

- `users.csv`、`profiles.csv`、`abm_user_profiles.csv` 不再保留 `observed_activity_level`、`observed_influence`、`activity_level`
- 如后续分析需要总体影响力，应在分析层显式定义，不写入基础 final dataset 合同

参考依据只用于构建 proxy 逻辑，不表示复刻清博 DCI、飞瓜指数或新榜指数。由于本数据缺少播放量、曝光量、完整分享量、收藏量、新增粉丝数和完整视频点赞等后台字段，本文档只将这些字段称为 observable proxy，不将其表述为真实心理特征或真实因果影响力。

稳健性检验已输出聚合报告，覆盖 Activity 权重扰动、Local Influence 权重扰动、P90/P95/P99 与 rank percentile 归一化扰动，并报告 Spearman rank correlation、Top10% overlap、Top20% overlap 与分布统计。判定口径为 Spearman >= 0.90 且 Top10% overlap >= 80%。

## 隐私边界

本文档只记录聚合计数、路径和 lineage，不展示用户个人资料文本明细或 TikHub raw payload 明细；未读取或打印 `.env` / API 凭证 / 鉴权头 / 会话凭证。

## Cleanup 决策

用户已确认：`aggressive_cleanup`、`keep_final_processed_minimal_raw`、`keep_full_profile_raw`、`delete_both_inputs`。因此 final audit 通过后，可删除两个输入 processed run 和明显中间 run；完整 profile raw evidence 必须保留。
