# 锦江 Douyin top10 名称带锦江视频集合统计报告

- run: `jinjiang-top10-non-generic-video-metadata-1y-20260617T035450Z`
- scope: 只统计 10 个名称带 `锦江` 的 source challenge 与 caption hashtag。
- caption hashtag 口径: 只认显式 `#锦江...`；普通文本不进入主计数。
- comments/replies/profiles: 本阶段不抓取。

## A. Scope

1. 锦江都城酒店
2. 锦江之星酒店
3. 锦江酒店
4. 锦江之星
5. 锦江宾馆
6. 绵阳锦江国际酒店
7. 锦江之星品尚
8. 锦江酒店华西区
9. 锦江之星海口
10. 锦江酒店中国区

### Excluded

- `酒店`: 泛化酒店主题，且名称不带锦江
- `住宿`: 泛化/弱相关住宿主题，且名称不带锦江
- `高性价比酒店推荐`: 消费决策相关但名称不带锦江，不属于本轮名称带锦江 top10

## B. Source challenge 统计

| source_challenge_name | source_challenge_id | indexed_video_ids | selected_video_ids | videos_with_caption | videos_with_hashtags |
| --- | --- | --- | --- | --- | --- |
| 锦江酒店 | 1614016211862532 | 8 | 8 | 8 | 8 |

## C. Caption hashtag 统计

| caption_hashtag | matched_video_count | unique_video_count |
| --- | --- | --- |
| #锦江都城酒店 | 0 | 0 |
| #锦江之星酒店 | 0 | 0 |
| #锦江酒店 | 8 | 8 |
| #锦江之星 | 0 | 0 |
| #锦江宾馆 | 0 | 0 |
| #绵阳锦江国际酒店 | 0 | 0 |
| #锦江之星品尚 | 0 | 0 |
| #锦江酒店华西区 | 0 | 0 |
| #锦江之星海口 | 0 | 0 |
| #锦江酒店中国区 | 0 | 0 |

## D. Source vs caption 差异

- deduped_video_total: `8`
- multilabel_match_total: `8`
- source_without_matching_caption_hashtag: `0`
- caption_hashtag_source_mismatch: `0`
- videos_with_multiple_top10_caption_hashtags: `0`

## E. 评论数过千判断（metadata-only）

本阶段不抓评论。`metadata_comment_count >= 1000` 先标记为 metadata 层面过千；缺失或 challenge-page provenance 需要后续 detail/comment 阶段确认。

| video_id | source_challenge_name | caption_hashtags | metadata_comment_count | over_1000_by_metadata | comment_count_confidence | needs_comment_fetch |
| --- | --- | --- | --- | --- | --- | --- |
| 7618907951377517859 | 锦江酒店 | #锦江酒店 | 21 | false | metadata_level_needs_confirmation | true |
| 7623213112837071525 | 锦江酒店 | #锦江酒店 | 2 | false | metadata_level_needs_confirmation | true |
| 7627864726677203962 | 锦江酒店 | #锦江酒店 | 425 | false | metadata_level_needs_confirmation | true |
| 7628268987356318995 | 锦江酒店 | #锦江酒店 | 20 | false | metadata_level_needs_confirmation | true |
| 7636752780337622907 | 锦江酒店 | #锦江酒店 | 44 | false | metadata_level_needs_confirmation | true |
| 7637819464923195833 | 锦江酒店 | #锦江酒店 | 8 | false | metadata_level_needs_confirmation | true |
| 7643342474107692532 | 锦江酒店 | #锦江酒店 | 19 | false | metadata_level_needs_confirmation | true |
| 7644415036031554661 | 锦江酒店 | #锦江酒店 | 315 | false | metadata_level_needs_confirmation | true |

## Safety audit

- comments_collected: `False`
- profiles_collected: `False`
- forbidden_endpoint_calls: `{}`
