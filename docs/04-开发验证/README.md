# 04-开发验证

本目录只保留当前仍需要阅读/引用的开发验证入口。锦江 Douyin 相关文档已收敛到“最终数据集”两份文件；历史口径、metadata、profile retry、旧 live run 等过程报告不再放在当前树中，如需追溯请用 Git 历史。

## 当前锦江 Douyin 数据集入口

- [锦江酒店 Douyin 最终数据集审计（2026-06-24）](jinjiang-douyin-final-dataset-20260624.md)：当前最终数据集入口，整合话题/评论/视频/边表与 36,400 个完整 profile。
- [锦江酒店 Douyin 最终数据集清理记录（2026-06-24）](jinjiang-douyin-final-dataset-cleanup-20260624.md)：本地旧 run 和中间数据清理记录，只含聚合统计。

## 工程验证入口

- [开发计划](development-plan.md)：阶段路线、架构决策和验收证据。
- [组件清单](component-inventory.md)：运行时、输出、Provider、测试组件职责。
- [源码结构分析](source-tree-analysis.md)：目录说明、入口点、文件组织模式。
- [测试策略](test-strategy.md)：单元、集成、E2E、Playwright 和 live LLM 手动门禁。

## 数据收集架构入口

- [TikHub / Douyin 数据收集架构](../02-架构设计/douyin-data-collection-architecture.md)：阶段化收集体系总览。
- [data 目录说明](../../data/README.md)：raw/processed 目录语义、安全边界和不提交规则。

## 已清理内容

为避免后续阅读混乱，本目录已删除非最终版 Jinjiang Douyin 过程文档。当前口径以最终数据集审计和清理记录为准。
