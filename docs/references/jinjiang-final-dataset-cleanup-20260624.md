# 锦江酒店 Douyin 最终数据集清理记录（2026-06-24）

Status: Dataset Cleanup Reference
Legacy source: `docs/04-开发验证/06-jinjiang-douyin-final-dataset-cleanup-20260624.md`（已删除；迁移索引见 [`../04-开发验证/README.md`](../04-开发验证/README.md)）

## 清理结论

- final processed run retained: `data/processed/jinjiang_douyin/jinjiang-final-caption-hashtag-comments-profiles-20260624T092200Z`
- complete profile raw evidence retained: `data/raw/tikhub/douyin/jinjiang_hotel/jinjiang-profile-expansion-derived-20260622T151059Z-batch-full`
- removed paths: 28
- removed files: 54280
- removed bytes: 2623326100
- live API collection in this step: `false`
- `.env`、代码、docs、非锦江数据未删除；未读取或打印任何 API 凭证。

## 删除的目录/文件

| 路径 | 原因 | 文件数 | 字节 |
|---|---|---:|---:|
| `data/processed/jinjiang_douyin/.DS_Store` | macOS metadata cleanup | 1 | 10244 |
| `data/processed/jinjiang_douyin/jinjiang-caption-hashtag-comments-excluding-binguan-adding-jian-derived-20260621T025127Z` | aggressive_cleanup processed intermediate/input run | 16 | 39179144 |
| `data/processed/jinjiang_douyin/jinjiang-profile-expansion-derived-20260622T151059Z-batch-full` | aggressive_cleanup processed intermediate/input run | 14 | 48257588 |
| `data/processed/jinjiang_douyin/jinjiang-profile-expansion-derived-20260622T151059Z-batch-full.zip` | aggressive_cleanup processed archive/duplicate | 1 | 8109466 |
| `data/processed/jinjiang_douyin/jinjiang-top10-caption-hashtag-all-comments-excluding-safety-20260617T140519Z` | aggressive_cleanup processed intermediate/input run | 13 | 51291979 |
| `data/processed/jinjiang_douyin/jinjiang-top10-caption-hashtag-all-comments-excluding-safety-20260617T140519Z-shard01` | aggressive_cleanup processed intermediate/input run | 13 | 3350398 |
| `data/processed/jinjiang_douyin/jinjiang-top10-caption-hashtag-all-comments-excluding-safety-20260617T140519Z-shard02` | aggressive_cleanup processed intermediate/input run | 13 | 3337720 |
| `data/processed/jinjiang_douyin/jinjiang-top10-caption-hashtag-all-comments-excluding-safety-20260617T140519Z-shard03` | aggressive_cleanup processed intermediate/input run | 13 | 3505102 |
| `data/processed/jinjiang_douyin/jinjiang-top10-caption-hashtag-all-comments-excluding-safety-20260617T140519Z-shard04` | aggressive_cleanup processed intermediate/input run | 13 | 3243821 |
| `data/processed/jinjiang_douyin/jinjiang-top10-caption-hashtag-all-comments-excluding-safety-20260617T140519Z-shard05` | aggressive_cleanup processed intermediate/input run | 13 | 6550494 |
| `data/processed/jinjiang_douyin/jinjiang-top10-caption-hashtag-all-comments-excluding-safety-20260617T140519Z-shard06` | aggressive_cleanup processed intermediate/input run | 13 | 3311750 |
| `data/processed/jinjiang_douyin/jinjiang-top10-caption-hashtag-all-comments-excluding-safety-20260617T140519Z-shard07` | aggressive_cleanup processed intermediate/input run | 13 | 3240303 |
| `data/processed/jinjiang_douyin/jinjiang-top10-caption-hashtag-all-comments-excluding-safety-20260617T140519Z-shard08` | aggressive_cleanup processed intermediate/input run | 13 | 3218378 |
| `data/processed/jinjiang_douyin/jinjiang-top10-jinjiang-only-video-metadata-unbounded-20260617T095743Z` | aggressive_cleanup processed intermediate/input run | 13 | 8270905 |
| `data/processed/jinjiang_douyin/jinjiang-top12-jian-comments-replies-live-20260620T072706Z` | aggressive_cleanup processed intermediate/input run | 13 | 624821 |
| `data/processed/jinjiang_douyin/jinjiang-top12-jian-video-metadata-live-20260620T072428Z` | aggressive_cleanup processed intermediate/input run | 7 | 255914 |
| `data/raw/tikhub/douyin/jinjiang_hotel/jinjiang-top10-caption-hashtag-all-comments-excluding-safety-20260617T140519Z` | aggressive_cleanup raw intermediate/predecessor run | 36088 | 717556375 |
| `data/raw/tikhub/douyin/jinjiang_hotel/jinjiang-top10-caption-hashtag-all-comments-excluding-safety-20260617T140519Z-shard01` | aggressive_cleanup raw intermediate/predecessor run | 1288 | 36330690 |
| `data/raw/tikhub/douyin/jinjiang_hotel/jinjiang-top10-caption-hashtag-all-comments-excluding-safety-20260617T140519Z-shard02` | aggressive_cleanup raw intermediate/predecessor run | 1397 | 42527144 |
| `data/raw/tikhub/douyin/jinjiang_hotel/jinjiang-top10-caption-hashtag-all-comments-excluding-safety-20260617T140519Z-shard03` | aggressive_cleanup raw intermediate/predecessor run | 1355 | 41412459 |
| `data/raw/tikhub/douyin/jinjiang_hotel/jinjiang-top10-caption-hashtag-all-comments-excluding-safety-20260617T140519Z-shard04` | aggressive_cleanup raw intermediate/predecessor run | 1260 | 42978358 |
| `data/raw/tikhub/douyin/jinjiang_hotel/jinjiang-top10-caption-hashtag-all-comments-excluding-safety-20260617T140519Z-shard05` | aggressive_cleanup raw intermediate/predecessor run | 2965 | 44424776 |
| `data/raw/tikhub/douyin/jinjiang_hotel/jinjiang-top10-caption-hashtag-all-comments-excluding-safety-20260617T140519Z-shard06` | aggressive_cleanup raw intermediate/predecessor run | 1325 | 44098071 |
| `data/raw/tikhub/douyin/jinjiang_hotel/jinjiang-top10-caption-hashtag-all-comments-excluding-safety-20260617T140519Z-shard07` | aggressive_cleanup raw intermediate/predecessor run | 1205 | 41252388 |
| `data/raw/tikhub/douyin/jinjiang_hotel/jinjiang-top10-caption-hashtag-all-comments-excluding-safety-20260617T140519Z-shard08` | aggressive_cleanup raw intermediate/predecessor run | 1413 | 41534613 |
| `data/raw/tikhub/douyin/jinjiang_hotel/jinjiang-top10-jinjiang-only-video-metadata-unbounded-20260617T095743Z` | aggressive_cleanup raw intermediate/predecessor run | 5211 | 1333196215 |
| `data/raw/tikhub/douyin/jinjiang_hotel/jinjiang-top12-jian-comments-replies-live-20260620T072706Z` | aggressive_cleanup raw intermediate/predecessor run | 355 | 2694310 |
| `data/raw/tikhub/douyin/jinjiang_hotel/jinjiang-top12-jian-video-metadata-live-20260620T072428Z` | aggressive_cleanup raw intermediate/predecessor run | 236 | 49562674 |

## 保留的关键路径

| 路径 | 原因 |
|---|---|
| `data/processed/jinjiang_douyin/README.md` | directory README |
| `data/processed/jinjiang_douyin/jinjiang-final-caption-hashtag-comments-profiles-20260624T092200Z` | final processed run |
| `data/raw/tikhub/douyin/jinjiang_hotel/jinjiang-profile-expansion-derived-20260622T151059Z-batch-full` | complete profile raw evidence retained by user decision |

## 隐私边界

本文档只记录聚合清理统计和路径，不展示用户 profile 文本明细或 TikHub raw payload 明细。
