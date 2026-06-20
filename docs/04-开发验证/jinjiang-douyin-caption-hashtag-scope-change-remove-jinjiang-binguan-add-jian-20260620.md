# 锦江 Douyin caption hashtag 口径二次修正审计

- generated_at: `20260620T064712Z`
- derived_run_id: `jinjiang-caption-hashtag-comments-excluding-binguan-adding-jian-derived-20260620T064712Z`
- old_run_id: `jinjiang-top10-caption-hashtag-all-comments-excluding-safety-20260617T140519Z`
- source_run_id: `jinjiang-top10-jinjiang-only-video-metadata-unbounded-20260617T095743Z`
- completion_status: `source_metadata_gap_for_top12`
- partial: `true`
- source_metadata_gap_for_top12: `true`
- live_api: `false`
- profiles_collected: `false`

## 口径变更

- 移除：`#锦江宾馆`，以旧 manifest 的 `matched_caption_hashtags` caption-hashtag 语义为主。
- 跳过：`#临空锦江宾馆`。
- 补充：`#锦江都城酒店吉安`，仅来自本地 source `videos.csv`，不进行 live API 补采。
- 保持排除 safety video_id：`7486704870804770107`, `7486891790218399034`。

## 离线审计结果

| 指标 | 数值 |
|---|---:|
| 当前 unique target videos | 4427 |
| manifest physical rows | 4427 |
| 含 #锦江宾馆 unique videos | 416 |
| 剔除 #锦江宾馆 后剩余 unique videos | 4011 |
| source metadata 中 #锦江都城酒店吉安 unique videos | 0 |
| top12 已在旧 comments run 覆盖 | 0 |
| top12 新增 unique videos | 0 |
| 修正后 unique target videos | 4011 |
| top-level comments | 33206 |
| replies | 17183 |
| all_comments | 50389 |
| needs_comment_fetch videos | 0 |
| partial | true |
| completion_status | source_metadata_gap_for_top12 |
| source_metadata_gap_for_top12 | true |

## Provenance

| input | sha256 |
|---|---|
| old target manifest | `f6e0d26ddb4643db74d384797f2b2bafec69d74decc045580df1bb671ea67257` |
| old top_level_comments | `ee281bcaf78c8a5a87893f0fcde8d23bc42985a5a8ee0d3d790862f143f0fd1b` |
| old replies | `a64368a16537cfbec9091db2f6cc477ccd9116f81ff48734156e5d09cf4e0c89` |
| old all_comments | `98c4106064e5e3f6dd10595cc085a0be7d79ec3a137359530d284e36e7773535` |
| source videos | `377965f764bb4de6ddb500bf390e44f7c7cb5f03e482217cbc7402a5c49b4bf4` |

## 结论

当前本地 source `videos.csv` 中 `#锦江都城酒店吉安` 视频数为 `0`。因此本次生成的是离线 derived scope audit：已完成 `#锦江宾馆` 剔除和旧评论/回复复用，但还不能声称完成 top12 `#锦江都城酒店吉安` 纳入。若后续补齐 metadata 后发现新增视频，需要用户另行授权 live API 后再补采评论/回复。

Derived processed path:

`data/processed/jinjiang_douyin/jinjiang-caption-hashtag-comments-excluding-binguan-adding-jian-derived-20260620T064712Z`
