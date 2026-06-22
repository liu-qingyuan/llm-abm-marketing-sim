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



## Profile 扩展与 sec_uid evidence recovery

Profile 扩展 run 仍使用相同目录约定：

```text
data/raw/tikhub/douyin/jinjiang_hotel/<profile_run_id>/
data/processed/jinjiang_douyin/<profile_run_id>/
```

扩展流程先读取最终 corrected processed dataset 的 `users.csv`，再从明确指定的 raw evidence runs 中恢复显式 `uid -> sec_uid/sec_user_id`。支持的证据入口包括 run 根目录下的 `comments.jsonl`、`comment_replies.jsonl`、`video_details.jsonl`、`user_profiles.jsonl`，以及同一 run 的 `pages/` / `pages_premerge_backup_*` 中可识别的 comments/replies/candidate video metadata JSON。`--sec-uid-evidence-run` 与 `--sec-uid-evidence-glob` 都限定在 `data/raw/tikhub/douyin/jinjiang_hotel/` 下，避免扫入无关目录。

当前 corrected dataset 的 36,400 个 observed users 需要同时使用 comments/replies raw evidence 与 `jinjiang-top10-jinjiang-only-video-metadata-unbounded-20260617T095743Z` 的 video metadata evidence，才能补齐 creator 侧 sec_uid。Profile API 默认可用 App V3 单用户 `handler_user_profile`；大规模扩展可使用 `--profile-api batch` 调用 Web batch profile endpoint（每批最多 50），但仍逐用户做 uid/sec_uid identity validation 和 checkpoint。

Profile 扩展输出应包含：

- `profile_target_users.csv`
- `sec_uid_evidence_audit.json` / `.md`
- `profile_collection_report.json`
- `profile_collection_audit.json` / `.md`
- `users.csv`、`profiles.csv`、`abm_user_profiles.csv`
- `missing_sec_uid_users.csv`、`failed_profile_users.csv`
- raw-only `user_profiles.jsonl`、`rejected_user_profiles.jsonl`、`profile_status.csv`

注意：`sec_uid_evidence_audit.md` 与验证文档只能写聚合统计和 provenance 计数，不展示昵称、bio、signature、raw payload、token、cookie、Authorization。processed CSV/profile 明细仍视为本地研究产物，不提交。

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
