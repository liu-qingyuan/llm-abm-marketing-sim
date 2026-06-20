# data 目录说明

本目录保存本地数据收集与清洗产物。默认原则：不提交秘密、不删除旧 run、不把评论/profile 当作视频 metadata 的替代分母。

## 目录语义

```text
data/
├── raw/                 # API 原始响应、page journals、checkpoints，本地证据源
└── processed/           # 归一化 CSV、collection_report.json、可供 ABM/分析使用的表
```

`data/raw/` 与 `data/processed/` 下的 run 数据通常被 `.gitignore` 忽略。可提交的只有说明文件、小型匿名 fixture 或明确脱敏的验证摘要。

## Douyin run 约定

当前锦江酒店 Douyin 数据位于：

```text
data/raw/tikhub/douyin/jinjiang_hotel/<run_id>/
data/processed/jinjiang_douyin/<run_id>/
```

每个 run 应通过 `collection_report.json` 说明：

- `stage_status`：哪些阶段 enabled/disabled；
- `stage_counts`：索引、详情、caption/hashtags、评论分母差异等指标；
- `endpoint_call_counts`：实际调用过哪些 endpoint；
- `failed_pages`：失败页和错误摘要；
- `comments_collected` / `profiles_collected`：评论和 profile 阶段是否真的运行；
- `redacted_config`：脱敏配置，不得出现 API key/token/cookie/Authorization。

## 当前视频 metadata 基线

优先参考：

```text
data/processed/jinjiang_douyin/jinjiang-top10-non-generic-video-metadata-1y-20260617T035450Z/
```

该 run 是 metadata-only 验证：

- `challenge_index`: enabled
- `video_metadata`: enabled
- `comments`: disabled
- `replies`: disabled
- `profiles`: disabled

关键验收：

| 表/字段 | 当前状态 |
|---|---|
| `videos.csv` | 8 行 |
| `caption` | 8/8 非空 |
| `hashtags` | 8/8 非空 |
| `source_challenge_id/name/rank` | 8/8 非空 |
| `comments.csv` | 空表，仅保留 schema |
| `profiles.csv` | 空表，仅保留 schema |

## 不要误读的历史 run

`jinjiang-top10-tags-unbounded-1y-20260615T105143Z` 是旧式 top10 run，已确认存在口径不一致：

- topic/challenge index 可得到大量 video_id；
- `videos.csv` 只有 82 条视频详情；
- `comments.csv` 覆盖 201 个 video_id；
- 因此不能说“82 条视频对应 18,153 条评论”。

后续分析应以 `collection_report.json` 的 stage counts 和 report 文档解释分母，不要只看单张 CSV 行数。

## 安全边界

禁止：

```bash
cat .env
printenv | grep KEY
echo $TIKHUB_API_KEY
rm -rf data/raw data/processed
```

允许：

- 读取脱敏 `collection_report.json`；
- 统计 CSV 行数和字段覆盖率；
- 新建独立 run 目录；
- 写新的 Markdown 报告；
- 做 metadata-only 小规模 live smoke；
- 在明确授权后再设计评论/回复/profile 阶段。
