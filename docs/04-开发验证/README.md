# 04-开发验证（迁移索引）

本目录是旧开发验证入口和迁移索引。新 PRD、Reference、Architecture Note 和 ADR 不再新增到本目录。

保留本目录的目的只有两个：让历史链接继续可达；说明历史开发验证文档迁移到了哪些 canonical 目录。目录中的 `01-06`、`08`、`09` 文件均为 legacy redirect，不再承载正文维护。

后续新增或迁移文档优先使用：

- [`../prds/`](../prds/)：PRD、用户故事、验收标准和 issue plan。
- [`../references/`](../references/)：外部资料、研究先验、数据口径参考。
- [`../architecture/`](../architecture/)：当前/目标架构说明、数据结构图、边界说明。
- [`../adr/`](../adr/)：架构决策记录。

## Legacy redirect

- [01 开发计划](01-development-plan.md)：已迁移到 [Initial ABM MVP Development Plan](../prds/initial-abm-mvp-development-plan.md) 和 [ADR 0001](../adr/0001-deterministic-event-sourced-abm-mvp.md)。
- [02 源码结构分析](02-source-tree-analysis.md)：已迁移到 [源码结构与入口点](../architecture/source-tree-and-entrypoints.md)。
- [03 组件清单](03-component-inventory.md)：已迁移到 [运行时组件清单](../architecture/runtime-component-inventory.md)。
- [04 测试策略](04-test-strategy.md)：已迁移到 [测试策略](../architecture/testing-strategy.md)。
- [05 锦江酒店 Douyin 最终数据集审计（2026-06-24）](05-jinjiang-douyin-final-dataset-20260624.md)：已迁移到 [锦江 final dataset 审计](../references/jinjiang-final-dataset-audit-20260624.md)。
- [06 锦江酒店 Douyin 最终数据集清理记录（2026-06-24）](06-jinjiang-douyin-final-dataset-cleanup-20260624.md)：已迁移到 [锦江 final dataset 清理记录](../references/jinjiang-final-dataset-cleanup-20260624.md)。
- [锦江用户潜在属性研究先验整理](../references/jinjiang-user-latent-attributes-reference-zh.md)：已迁移到 Reference，保存 latent class、价值权重、Table 11 成员画像分布和使用边界。
- [锦江用户数据结构 Architecture Note](../architecture/jinjiang-user-profile-data-structure.md)：已迁移到 Architecture Notes，说明当前用户数据与目标版本如何拆成真实观测画像属性和 latent attributes。旧入口 [08 锦江用户数据结构简图](08-jinjiang-user-data-structure-diagrams.md) 仅保留 redirect。
- [锦江用户 Latent Attributes v1 PRD](../prds/jinjiang-user-latent-attributes-v1.md)：已迁移到 PRD，说明 latent class 标签生成、数据版本、ABM 用户对象、规则决策接入、当前未实现能力和后续 issue plan。旧入口 [09 锦江用户 Latent Attributes 新标签版本实施 Spec](09-jinjiang-user-latent-attributes-spec.md) 仅保留 redirect。

## 迁移计划

当前迁移父级 PRD：

- [文档架构重组与锦江 Latent Attributes 迁移试点](../prds/docs-architecture-and-jinjiang-latent-attributes-migration.md)
- GitHub issue: [#1](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/1)

已拆分的迁移 issues：

- [#2 建立文档职责目录与导航骨架](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/2)
- [#3 创建最小领域术语表 CONTEXT.md](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/3)
- [#4 迁移锦江 latent attributes 参考资料](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/4)
- [#5 迁移锦江用户数据结构架构说明](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/5)（本地文档已迁移）
- [#6 迁移锦江 latent attributes 实施规格为 PRD](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/6)（本地文档已迁移）
- [#7 添加 Documentation Navigation Contract 检查](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/7)

本目录中的现有文档均为旧入口；当前内容应从本 README 指向新路径，而不是复制两份长期维护。锦江 latent attributes 实施方案的当前入口是 [`../prds/jinjiang-user-latent-attributes-v1.md`](../prds/jinjiang-user-latent-attributes-v1.md)。

## 外部入口

- [TikHub / Douyin 数据收集架构](../02-架构设计/douyin-data-collection-architecture.md)：阶段化收集体系总览。
- [data 目录说明](../../data/README.md)：raw/processed 目录语义、安全边界和不提交规则。

## 已清理内容

为避免后续阅读混乱，本目录已删除非最终版 Jinjiang Douyin 过程文档，并将 `01-06` 正文迁移到职责型目录。当前数据集口径以 References 中的 final dataset audit 和 cleanup record 为准；latent attributes 研究先验以 Reference 为准，用户数据结构以 Architecture Note 为准，后续实施方案以 PRD 为准。
