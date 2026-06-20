# 锦江酒店 Douyin processed runs

本目录保存锦江酒店 Douyin 相关清洗结果。后续 AI Agent 进入时，优先读：

1. `docs/02-架构设计/douyin-data-collection-architecture.md`
2. `data/README.md`
3. `docs/04-开发验证/jinjiang-douyin-video-metadata-validation-20260617T035450Z.md`
4. 对应 run 的 `collection_report.json`

## 当前推荐基线

```text
jinjiang-top10-non-generic-video-metadata-1y-20260617T035450Z/
```

用途：验证非泛化 top tags 的视频 metadata，确认 `caption`、`hashtags`、来源 challenge 和聚合统计字段可用。

不要把旧 run `jinjiang-top10-tags-unbounded-1y-20260615T105143Z` 当成最终评论数据集；它是重要问题样本，说明旧流程存在视频详情与评论分母不一致。
