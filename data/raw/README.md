# data/raw 说明

`data/raw/` 是本地原始证据层，通常被 git 忽略。

Douyin run 的 raw 目录应包含：

- `manifest.json`：run scope、selection manifest、脱敏配置摘要；
- `pages/*.json`：每个 API/page 调用的 journal，是 resume 和排错的权威证据；
- `checkpoints.json`：已完成 stage/page key；
- `challenge_posts.jsonl`：tag/challenge 页面索引结果；
- `video_details.jsonl`：可归一化的视频 metadata；
- `comments.jsonl`、`comment_replies.jsonl`、`user_profiles.jsonl`：仅在对应阶段启用时应有内容。

排错优先级：先看 `pages/*.json`，再看由 pages rebuild 出来的 jsonl，最后看 processed CSV。
