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
- [锦江用户数据结构 Architecture Note](jinjiang-user-profile-data-structure.md)：说明 Observed Profile Attributes + Latent Attributes，并记录 Prompt v3、锦江 v5 移除 `interest_tags`、通用 `UserProfile` 兼容及 `historical_tags` Ranking-only 边界。
- [Final Research 离线基线](final-research-offline-baseline.md)：历史单视频研究的离线基线，保留 Target Holdout、holdout-safe 画像投影、研究样本、静态平台推荐和旧 artifacts 的 lineage；当前多 message 研究以 Concurrent Message Note 为准。
- [Final Research 30 批次 Runtime](final-research-runtime.md)：历史单视频 runtime baseline，保留 v3/v4/v5/v6 的只读合同与重建边界；当前 canonical release 以 Concurrent Message Formal evidence 为准。
- [Concurrent Message Competition Experiment](concurrent-message-competition-experiment.md)：**已实现并发布**的三个营销 message 并发运行、Per-Message Personalized Top20、Primary/Shadow Decision Trace、报告 UI 和 canonical 发布边界；当前 release evidence 见 [`../references/jinjiang-concurrent-message-editorial-formal-release-20260729.md`](../references/jinjiang-concurrent-message-editorial-formal-release-20260729.md)。
- [Concurrent Message Campaign Diagnostics](concurrent-message-campaign-diagnostics.md)：记录并发三 message validation runtime 中从 persisted source rows 重建 campaign diagnostics、校验 summary、生成 report sections 和 release-time rebuild 的当前实现边界。
- [Concurrent Message Durable Execution](concurrent-message-durable-execution.md)：区分 private operational workspace、publish staging、final source directory 和 canonical release，记录 journal replay、resume、atomic publication 与 deploy gate 边界。
- [Interactive Mechanism Report](interactive-mechanism-report.md)：历史单视频交互目标，已被当前 Editorial report 替代。

`../02-架构设计/` 继续作为核心系统阅读路径保留；新增或迁移的长期架构说明默认放在本目录，并从 `../index.md` 或相关 README 指向。
