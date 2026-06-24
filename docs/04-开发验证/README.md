# 04-开发验证

本目录现在只保留“当前仍需要阅读/引用”的开发验证入口。历史过程报告已经从当前树清理；如需追溯，可通过 Git 历史查看。

## 当前必读

- [锦江酒店 Douyin 最终数据集审计（2026-06-24）](jinjiang-douyin-final-dataset-20260624.md)：当前最终数据集入口，整合话题/评论/视频/边表与 36,400 个完整 profile。
- [锦江酒店 Douyin 最终数据集清理记录（2026-06-24）](jinjiang-douyin-final-dataset-cleanup-20260624.md)：本地旧 run 和中间数据清理记录，只含聚合统计。
- [锦江酒店抖音社交网络与绿色营销仿真标准](jinjiang-douyin-research-standard.md)：研究口径、网络构建、仿真实验和写作标准。
- [既有话题分布](jinjiang-douyin-existing-topic-distribution.md)：top10 tag/challenge scope 来源与话题口径。
- [非泛化 top tag 视频 metadata 验证基线](jinjiang-douyin-video-metadata-validation-20260617T035450Z.md)：metadata-only 历史基线，保留给后续 Agent 对照阶段化采集口径。

## 工程验证入口

- [开发计划](development-plan.md)：阶段路线、架构决策和验收证据。
- [组件清单](component-inventory.md)：运行时、输出、Provider、测试组件职责。
- [源码结构分析](source-tree-analysis.md)：目录说明、入口点、文件组织模式。
- [测试策略](test-strategy.md)：单元、集成、E2E、Playwright 和 live LLM 手动门禁。

## 数据收集架构入口

- [TikHub / Douyin 数据收集架构](../02-架构设计/douyin-data-collection-architecture.md)：阶段化收集体系总览。
- [data 目录说明](../../data/README.md)：raw/processed 目录语义、安全边界和不提交规则。

## 已清理内容

为避免后续阅读混乱，本目录已删除旧式 live run、profile retry 过程稿、top10 smoke/unbounded 过程报告、重复 metadata 验证报告，以及大体量 caption/hashtag 过程报告。最终口径以本目录的最终数据集审计和清理记录为准。
