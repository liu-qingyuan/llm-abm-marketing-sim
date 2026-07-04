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
- [源码结构与入口点](source-tree-and-entrypoints.md)：仓库目录、入口点和文件组织方式。
- [运行时组件清单](runtime-component-inventory.md)：运行时、输出、Provider、Web 和测试组件职责。
- [测试策略](testing-strategy.md)：离线默认测试分层、质量命令和 live LLM 手动门禁。
- [锦江用户数据结构 Architecture Note](jinjiang-user-profile-data-structure.md)：说明目标模型是 Observed Profile Attributes + Latent Attributes，并标记当前代码只保留未知 profile columns、尚无结构化 `UserProfile.latent_attributes` contract。

`../02-架构设计/` 继续作为核心系统阅读路径保留；新增或迁移的长期架构说明默认放在本目录，并从 `../index.md` 或相关 README 指向。
