# 锦江酒店 Douyin 非泛化 Top Tag 视频元数据验证报告

- run_id: `jinjiang-top10-non-generic-video-metadata-1y-20260617T035450Z`
- raw 输出: `data/raw/tikhub/douyin/jinjiang_hotel/jinjiang-top10-non-generic-video-metadata-1y-20260617T035450Z`
- processed 输出: `data/processed/jinjiang_douyin/jinjiang-top10-non-generic-video-metadata-1y-20260617T035450Z`
- collection_report: `data/processed/jinjiang_douyin/jinjiang-top10-non-generic-video-metadata-1y-20260617T035450Z/collection_report.json`
- selection manifest: `configs/jinjiang_top10_non_generic_video_metadata_selection.json`
- 验证阶段: `challenge_index,video_metadata`
- comments/profiles: 显式 skipped / disabled，本 run 未抓评论、回复或用户 profile。
- 安全说明: 报告只写聚合统计；未打印 API 凭证、会话凭证或鉴权头，未列出用户个人资料文本或 profile 明细。

## Scope / tag 选择

本次按用户要求先验证视频级 metadata（caption/hashtags），不继续大规模爬评论。`#酒店` 因过泛化被排除；`住宿` 保留但标注为弱相关/泛化标签。

### Included tags

| rank | tag | cid | note | generic |
|---:|---|---|---|---|
| 2 | 锦江酒店 | `1614016211862532` | 锦江酒店核心品牌标签 | False |
| 3 | 高性价比酒店推荐 | `1742310100775939` | 酒店消费决策相关标签 | False |
| 4 | 锦江酒店中国区 | `1669845857481741` | 用户重点提到的锦江酒店中国区 | False |
| 5 | 锦江之星 | `1600871309340680` | 锦江旗下品牌标签 | False |
| 6 | 锦江都城酒店 | `1629766950492163` | 用户重点提到的锦江都城酒店 | False |
| 7 | 锦江宾馆 | `1608015311015939` | 锦江相关实体标签 | False |
| 8 | 锦江之星酒店 | `1624819436442636` | 用户重点提到的锦江之星酒店 | False |
| 9 | 住宿 | `1581697840816141` | 弱相关/泛化住宿标签；保留但报告中单独标注 | True |
| 10 | 南充锦江酒店 | `7362438499401730111` | 地理实体相关锦江酒店标签 | False |

### Excluded tags

| rank | tag | cid | reason |
|---:|---|---|---|
| 1 | 酒店 | `7419045480706869287` | 泛化酒店主题，不作为锦江酒店相关核心验证样本 |

重点覆盖：`锦江都城酒店`、`锦江之星酒店`、`锦江酒店中国区`。

## Stage counts

| metric | value |
|---|---:|
| indexed_video_refs | 18 |
| indexed_video_ids | 18 |
| selected_video_ids | 18 |
| video_detail_attempted | 0 |
| video_detail_succeeded | 8 |
| video_detail_failed | 0 |
| video_detail_skipped_out_of_window | 10 |
| video_metadata_promoted_from_challenge | 8 |
| videos_with_caption | 8 |
| videos_with_hashtags | 8 |
| video_rows_from_detail | 8 |
| video_rows_from_challenge | 0 |
| comments_video_ids_without_video_metadata | 0 |
| videos.csv rows | 8 |
| collection_report counts.videos | 8 |
| comments_collected | False |
| profiles_collected | False |
| failed_pages | 0 |

## Endpoint calls

| endpoint | calls |
|---|---:|
| fetch_hashtag_video_list | 2 |

说明：本 run 为 metadata-only；不应出现 `fetch_video_comments`、`fetch_video_comment_replies` 或 `handler_user_profile` 调用。

## 输出文件

- `data/processed/jinjiang_douyin/jinjiang-top10-non-generic-video-metadata-1y-20260617T035450Z/videos.csv`
- `data/processed/jinjiang_douyin/jinjiang-top10-non-generic-video-metadata-1y-20260617T035450Z/comments.csv`
- `data/processed/jinjiang_douyin/jinjiang-top10-non-generic-video-metadata-1y-20260617T035450Z/text_items.csv`
- `data/processed/jinjiang_douyin/jinjiang-top10-non-generic-video-metadata-1y-20260617T035450Z/users.csv`
- `data/processed/jinjiang_douyin/jinjiang-top10-non-generic-video-metadata-1y-20260617T035450Z/edges.csv`
- `data/processed/jinjiang_douyin/jinjiang-top10-non-generic-video-metadata-1y-20260617T035450Z/profiles.csv`
- `data/processed/jinjiang_douyin/jinjiang-top10-non-generic-video-metadata-1y-20260617T035450Z/collection_report.json`

## 结论

- 已按阶段化路径完成 tag/challenge index + video metadata 验证。
- 本 run 只验证视频级 `caption` / `hashtags` 可用性，不把评论作为主流程。
- `#酒店` 已排除；`住宿` 保留为弱相关/泛化标签并在 scope 中标注。
- 后续评论策略应基于已验证的视频 metadata 分母另行设计。


## Metadata 字段验收

本报告在重归一化后按视频级 metadata 要求核对 `videos.csv`：

| 字段/要求 | 覆盖 | 说明 |
|---|---:|---|
| video_id | 8/8 | 全部非空 |
| source_challenge_id | 8/8 | 可追溯到来源 tag/challenge |
| source_challenge_name | 8/8 | 可追溯到来源 tag/challenge 名称 |
| source_challenge_rank | 8/8 | 保留 top tag 排名 |
| caption | 8/8 | `caption` 为空时回退使用 `desc/title`，用于研究文本口径 |
| hashtags | 8/8 | 来自 `hashtags/cha_list/text_extra` 并补充 caption 中的 `#tag` |
| publish_time | 8/8 | 全部非空，可用于 1 年窗口过滤 |
| creator_user_id | 8/8 | 只保留聚合 ID 字段，报告不展开昵称/bio/profile 明细 |
| statistics | 8/8 | `like_count/comment_count/share_count/collect_count` 字段存在 |
| raw_detail_status | 8/8 | 本 run 均为 `promoted_from_challenge`，表示 topic/challenge page row 已足够归一化为视频 metadata |
| metadata_source | 8/8 | 本 run 均标记为 `challenge_page` |

结论：当前验证 run 的 `caption` 与 `hashtags` 已达到本阶段“先把对应视频 metadata 完整抓取并验证”的要求；comments/replies/profile 仍为 disabled，后续应基于这个视频 metadata 分母另行设计评论策略。
