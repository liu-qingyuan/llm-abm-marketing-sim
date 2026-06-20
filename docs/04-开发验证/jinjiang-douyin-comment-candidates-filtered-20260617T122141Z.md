# 锦江 Douyin filtered candidate 一级评论采集报告

- run: `jinjiang-top10-jinjiang-comment-candidates-filtered-20260617T122141Z`
- collection: filtered candidate comments collection，不是全量 4552 视频评论采集。
- comment scope: 只抓一级评论正文。
- replies: 未抓 replies。
- profiles: 未抓 profiles。
- excluded: `7486704870804770107`, `7486891790218399034`；原因是女性安全/偷拍主题与当前锦江酒店学术研究目标不一致。
- capped videos: `7380282151763332403` 和 `7304930579651284264` 按 2000 cap。
- unbounded videos: `7498610642853858569` 和 `7219508986515606839` 按全抓/自然分页结束。
- total first-level comments rows: `3861`

## Per-video status

| video_id | source | metadata_comment_count | comment_fetch_limit | comments_collected | status | raw_pages | needs_more |
| --- | --- | ---: | --- | ---: | --- | ---: | --- |
| 7380282151763332403 | 锦江酒店 | 11955 | 2000 | 816 | complete_or_api_exhausted | 42 | false |
| 7304930579651284264 | 锦江之星 | 5040 | 2000 | 1558 | complete_or_api_exhausted | 79 | false |
| 7498610642853858569 | 锦江宾馆 | 2963 | unbounded | 927 | complete_or_api_exhausted | 59 | false |
| 7219508986515606839 | 锦江宾馆 | 1069 | unbounded | 560 | complete_or_api_exhausted | 29 | false |

## Partial / blocker notes

- No API/余额/限流/分页 blocker recorded in `failed_pages`.

## Output files

- comments: `data/processed/jinjiang_douyin/jinjiang-top10-jinjiang-comment-candidates-filtered-20260617T122141Z/comments.csv`
- summary: `data/processed/jinjiang_douyin/jinjiang-top10-jinjiang-comment-candidates-filtered-20260617T122141Z/comment_candidate_video_summary.csv`
- audit: `data/processed/jinjiang_douyin/jinjiang-top10-jinjiang-comment-candidates-filtered-20260617T122141Z/comment_collection_audit.json`
- collection_report: `data/processed/jinjiang_douyin/jinjiang-top10-jinjiang-comment-candidates-filtered-20260617T122141Z/collection_report.json`
