# Architecture Notes

本目录保存当前/目标架构说明、模块边界、数据结构图和测试架构说明。

## 使用规则

- 写这里：系统结构、模块职责、数据流、目标架构、测试策略。
- 不写这里：外部研究资料、一次性审计报告、具体实现任务、issue 计划。
- 如果文档记录的是“为什么选择这个架构”，并且未来读者缺少上下文会疑惑，应改写为 ADR 放到 `docs/adr/`。

## 当前入口

- 核心架构仍在 [`../02-架构设计/architecture.md`](../02-架构设计/architecture.md)。
- 仿真流程仍在 [`../02-架构设计/simulation-flow.md`](../02-架构设计/simulation-flow.md)。
- Douyin 数据收集架构仍在 [`../02-架构设计/douyin-data-collection-architecture.md`](../02-架构设计/douyin-data-collection-architecture.md)。
- [锦江用户数据结构 Architecture Note](jinjiang-user-profile-data-structure.md)：说明目标模型是 Observed Profile Attributes + Latent Attributes，并标记当前代码只保留未知 profile columns、尚无结构化 `UserProfile.latent_attributes` contract。
