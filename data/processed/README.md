# data/processed 说明

`data/processed/` 是归一化输出层，通常被 git 忽略。每个 run 目录应至少包含：

- `videos.csv`：视频 metadata 分母；
- `comments.csv`：一级评论和回复，可能为空；
- `users.csv`：从视频/评论/profile 聚合出的用户 ID 表；
- `edges.csv`：互动边表；
- `profiles.csv`：ABM 用户画像候选，可能为空；
- `text_items.csv`：视频文案、评论、回复等文本项；
- `collection_report.json`：判断 run 是否可用的主入口。

不要只用 CSV 行数判断采集是否成功；必须同时看 `collection_report.json` 中的 `stage_status`、`stage_counts`、`failed_pages` 和 `comments_collected/profiles_collected`。
