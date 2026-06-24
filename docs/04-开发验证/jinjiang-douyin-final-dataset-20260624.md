# 锦江酒店 Douyin 最终数据集审计（2026-06-24）

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

## 隐私边界

本文档只记录聚合计数、路径和 lineage，不展示用户个人资料文本明细或 TikHub raw payload 明细；未读取或打印 `.env` / API 凭证 / 鉴权头 / 会话凭证。

## Cleanup 决策

用户已确认：`aggressive_cleanup`、`keep_final_processed_minimal_raw`、`keep_full_profile_raw`、`delete_both_inputs`。因此 final audit 通过后，可删除两个输入 processed run 和明显中间 run；完整 profile raw evidence 必须保留。
