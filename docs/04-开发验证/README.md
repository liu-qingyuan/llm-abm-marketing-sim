# 04-开发验证

本分类面向后续开发、测试验收和 AI Agent 接手维护。

- [锦江酒店抖音社交网络与绿色营销仿真标准](jinjiang-douyin-research-standard.md)：2026 年 6 月至 10 月 15 日的数据、网络、仿真、实验和写作标准。
- [开发计划](development-plan.md)：阶段路线、架构决策和验收证据。
- [组件清单](component-inventory.md)：运行时、输出、Provider、测试组件职责。
- [源码结构分析](source-tree-analysis.md)：目录说明、入口点、文件组织模式。
- [测试策略](test-strategy.md)：单元、集成、E2E、Playwright 和 live LLM 手动门禁。

## 锦江 Douyin 数据收集验证

- [TikHub / Douyin 数据收集架构](../02-架构设计/douyin-data-collection-architecture.md)：当前阶段化收集体系总览。
- [既有话题分布](jinjiang-douyin-existing-topic-distribution.md)：top10 tag/challenge scope 来源。
- [Top10 旧式 live run 问题报告](jinjiang-douyin-top10-tags-live-run-20260615T105143Z.md)：说明 5,934 indexed video_id、82 videos.csv、201 comment video_id 的口径问题。
- [非泛化 top tag 视频 metadata 验证](jinjiang-douyin-video-metadata-validation-20260617T035450Z.md)：当前推荐 metadata-only 基线。
