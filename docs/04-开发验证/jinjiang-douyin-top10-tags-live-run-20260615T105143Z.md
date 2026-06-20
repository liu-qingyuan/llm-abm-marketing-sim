# 锦江酒店 Douyin Top10 Tag/Challenge Live Run 报告（失败页重试后）

- run_id: `jinjiang-top10-tags-unbounded-1y-20260615T105143Z`
- 更新时间: `2026-06-17T02:46:25Z`
- raw 输出: `data/raw/tikhub/douyin/jinjiang_hotel/jinjiang-top10-tags-unbounded-1y-20260615T105143Z`
- processed 输出: `data/processed/jinjiang_douyin/jinjiang-top10-tags-unbounded-1y-20260615T105143Z`
- collection_report: `data/processed/jinjiang_douyin/jinjiang-top10-tags-unbounded-1y-20260615T105143Z/collection_report.json`
- selection manifest: `configs/jinjiang_top10_tags_selection.json`

## 结论

- 已按用户要求覆盖 top10 tag/challenge，scope 为 `top10_challenge_batch`，Douyin-only。
- 已使用同一 run_id + `--resume` 重试此前 4 个 profile failed_pages；重试后 `failed_pages=0`。
- 正式 run 使用 `--limit-profile unbounded`，`collection_report.json` 中 5 个业务限制字段均为 `null`。
- 当前 `quota_blocked=false`，未再遇到 TikHub `HTTP 402 Insufficient balance`。
- 需要特别注意：`videos=82` 与 `comments/replies=18,153` 不是同一严格分母口径；`comments.csv` 涉及 201 个 video_id，其中 72 个在 `videos.csv` 内、129 个不在 `videos.csv` 内。
- 本报告只写聚合统计；不复制用户昵称、bio、profile 明细或 sec_user_id。

## Top10 tag/challenge 覆盖

| rank | tag/challenge | cid | source |
|---:|---|---|---|
| 1 | 酒店 | `7419045480706869287` | existing aweme structured tag cid frequency |
| 2 | 锦江酒店 | `1614016211862532` | related_challenges.json exact name |
| 3 | 高性价比酒店推荐 | `1742310100775939` | existing aweme structured tag cid frequency |
| 4 | 锦江酒店中国区 | `1669845857481741` | related_challenges.json exact name |
| 5 | 锦江之星 | `1600871309340680` | related_challenges.json exact name |
| 6 | 锦江都城酒店 | `1629766950492163` | related_challenges.json exact name |
| 7 | 锦江宾馆 | `1608015311015939` | related_challenges.json exact name |
| 8 | 锦江之星酒店 | `1624819436442636` | related_challenges.json exact name |
| 9 | 住宿 | `1581697840816141` | existing aweme structured tag cid frequency |
| 10 | 南充锦江酒店 | `7362438499401730111` | related_challenges.json exact name |

## Limits / cap 记录

- `limit_profile`: `unbounded`

```json
{
  "max_videos": null,
  "max_comments_per_video": null,
  "max_replies_per_comment": null,
  "max_users": null,
  "max_search_pages": null
}
```

## 聚合输出计数

| artifact/count | value |
|---|---:|
| videos | 82 |
| comments | 11203 |
| replies | 6950 |
| users | 24191 |
| edges | 25232 |
| profiles | 24191 |
| text_items | 29245 |

Dedupe / raw journal 摘要：

| item | value |
|---|---:|
| raw_videos | 82 |
| deduped_videos | 82 |
| raw_comments_and_replies | 19493 |
| deduped_comments_and_replies | 18153 |
| raw page files | 36767 |
| checkpoints.json exists | true |

## “82 条视频 vs 1w+ 评论”口径核对

| metric | value |
|---|---:|
| `videos.csv` unique video_id | 82 |
| `comments.csv` rows total | 18153 |
| `comments.csv` 一级评论 | 11203 |
| `comments.csv` 回复 | 6950 |
| `comments.csv` 涉及 video_id | 201 |
| comments video_id 同时在 `videos.csv` 内 | 72 |
| comments video_id 不在 `videos.csv` 内 | 129 |
| `videos.csv` 内视频对应的 comment/reply rows | 13890 |
| `videos.csv` 外 video_id 对应的 comment/reply rows | 4263 |

分层计数：

| scope | comments | replies | total rows |
|---|---:|---:|---:|
| rows whose video_id is in `videos.csv` | 8540 | 5350 | 13890 |
| rows whose video_id is outside `videos.csv` | 2663 | 1600 | 4263 |

解释：`videos.csv` 是成功写入视频详情/可规范化详情的视频表；`comments.csv` 来自已完成的 comments/replies page journals，当前包含更多 video_id 的互动数据。因此不能表述为“82 条视频产生 18,153 条评论/回复”，更准确的说法是“本 run 输出 82 条视频详情；评论/回复表共 18,153 行，覆盖 201 个 video_id，其中 13,890 行可直接关联到 `videos.csv` 中的 72 条视频”。

## Endpoint calls

| endpoint | calls in latest retry invocation |
|---|---:|
| handler_user_profile | 4 |

说明：最终一次 `--resume` 仅重试 failed profile，因此当前 `collection_report.json` 的 endpoint_call_counts 只记录这次重试调用；重试前报告中记录过 comments/replies/profile 主采集调用。

## failed_pages / blocker

- failed_pages 数量: `0`
- quota_blocked: `False`

- 无 failed_pages。

## 输出文件

- `data/processed/jinjiang_douyin/jinjiang-top10-tags-unbounded-1y-20260615T105143Z/videos.csv`
- `data/processed/jinjiang_douyin/jinjiang-top10-tags-unbounded-1y-20260615T105143Z/comments.csv`
- `data/processed/jinjiang_douyin/jinjiang-top10-tags-unbounded-1y-20260615T105143Z/text_items.csv`
- `data/processed/jinjiang_douyin/jinjiang-top10-tags-unbounded-1y-20260615T105143Z/users.csv`
- `data/processed/jinjiang_douyin/jinjiang-top10-tags-unbounded-1y-20260615T105143Z/profiles.csv`
- `data/processed/jinjiang_douyin/jinjiang-top10-tags-unbounded-1y-20260615T105143Z/edges.csv`
- `data/processed/jinjiang_douyin/jinjiang-top10-tags-unbounded-1y-20260615T105143Z/collection_report.json`

## 是否可称全量

- 视频详情：当前 `videos.csv` 为 82 条去重视频详情。
- 评论/回复：当前 `comments.csv` 共有 18,153 行，覆盖 201 个 video_id；但由于它与 `videos.csv` 分母不同，做视频级分析时应先按 `video_id` 关联并选择口径。
- 用户资料/profile：failed_pages 已清零；可称本 run 在当前 TikHub 返回口径下 profile failed_pages 已重试完成。
- 不建议笼统写“82 条视频有 1w+ 评论”；建议写“82 条视频详情 + 覆盖 201 个 video_id 的 18,153 条评论/回复互动记录”。

## 验证

此前已运行并通过：

```bash
python -m py_compile $(find src tests scripts -name '*.py' -print)
pytest -q
ruff check src/llm_abm_sim/data_sources tests/integration/test_tikhub_douyin_collector_mock.py tests/e2e/test_tikhub_douyin_cli_mock.py
pyright src/llm_abm_sim/data_sources tests/integration/test_tikhub_douyin_collector_mock.py tests/e2e/test_tikhub_douyin_cli_mock.py
```

结果：`py_compile` 通过；`pytest -q` 为 `110 passed, 2 deselected`；`ruff` 为 `All checks passed!`；`pyright` 为 `0 errors, 0 warnings, 0 informations`。

## 下一步建议

1. 若要做“每条视频评论数”分析，先决定分母：仅限 `videos.csv` 82 条，还是扩展到 `comments.csv` 覆盖的 201 个 video_id。
2. 如果需要，我可以继续生成一个只含聚合字段的 `video_comment_coverage_summary.csv`，列出每个 video_id 的 comment/reply count 与是否在 `videos.csv` 中，不包含评论正文或用户资料。
