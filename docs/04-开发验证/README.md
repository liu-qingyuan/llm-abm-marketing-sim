# 04-开发验证（迁移索引）

本目录是旧开发验证入口和迁移索引。新 PRD、Reference、Architecture Note 和 ADR 不再新增到本目录。

后续新增或迁移文档优先使用：

- [`../prds/`](../prds/)：PRD、用户故事、验收标准和 issue plan。
- [`../references/`](../references/)：外部资料、研究先验、数据口径参考。
- [`../architecture/`](../architecture/)：当前/目标架构说明、数据结构图、边界说明。
- [`../adr/`](../adr/)：架构决策记录。

## 文档顺序

- [01 开发计划](01-development-plan.md)：阶段路线、架构决策和验收证据。
- [02 源码结构分析](02-source-tree-analysis.md)：目录说明、入口点、文件组织模式。
- [03 组件清单](03-component-inventory.md)：运行时、输出、Provider、测试组件职责。
- [04 测试策略](04-test-strategy.md)：单元、集成、E2E、Playwright 和 live LLM 手动门禁。
- [05 锦江酒店 Douyin 最终数据集审计（2026-06-24）](05-jinjiang-douyin-final-dataset-20260624.md)：当前最终数据集入口，整合话题/评论/视频/边表与 36,400 个完整 profile。
- [06 锦江酒店 Douyin 最终数据集清理记录（2026-06-24）](06-jinjiang-douyin-final-dataset-cleanup-20260624.md)：本地旧 run 和中间数据清理记录，只含聚合统计。
- [07 锦江用户潜在属性参考文档中文整理](07-jinjiang-user-latent-attributes-reference-zh.md)：用户 latent class、价值权重、Table 11 成员画像分布的中文参考资料。
- [08 锦江用户数据结构简图](08-jinjiang-user-data-structure-diagrams.md)：说明当前用户数据与目标版本如何拆成真实观测数据和虚拟实验标签。
- [09 锦江用户 Latent Attributes 新标签版本实施 Spec](09-jinjiang-user-latent-attributes-spec.md)：latent class 标签生成、数据版本、ABM 用户对象和规则决策接入方案。

## 迁移计划

当前迁移父级 PRD：

- [文档架构重组与锦江 Latent Attributes 迁移试点](../prds/docs-architecture-and-jinjiang-latent-attributes-migration.md)
- GitHub issue: [#1](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/1)

已拆分的迁移 issues：

- [#2 建立文档职责目录与导航骨架](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/2)
- [#3 创建最小领域术语表 CONTEXT.md](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/3)
- [#4 迁移锦江 latent attributes 参考资料](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/4)
- [#5 迁移锦江用户数据结构架构说明](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/5)
- [#6 迁移锦江 latent attributes 实施规格为 PRD](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/6)
- [#7 添加 Documentation Navigation Contract 检查](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/7)

本目录中的现有文档在对应 issue 完成前仍是旧入口；迁移完成后应从本 README 指向新路径，而不是复制两份长期维护。

## 外部入口

- [TikHub / Douyin 数据收集架构](../02-架构设计/douyin-data-collection-architecture.md)：阶段化收集体系总览。
- [data 目录说明](../../data/README.md)：raw/processed 目录语义、安全边界和不提交规则。

## 已清理内容

为避免后续阅读混乱，本目录已删除非最终版 Jinjiang Douyin 过程文档。当前数据集口径以 05 和 06 为准；latent attributes 后续方案以 08 和 09 为准。
