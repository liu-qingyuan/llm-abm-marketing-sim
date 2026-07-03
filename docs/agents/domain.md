# 领域文档

本仓库是单上下文仓库。

工程 skills 在探索和修改代码前，应按需读取根目录 `CONTEXT.md` 和 `docs/adr/`。如果这些文件不存在，安静地继续；不要把缺失当作问题，也不要预先创建它们。

## 探索前读取

- 根目录 `CONTEXT.md`：项目领域语言、统一术语和容易混淆的概念
- `docs/adr/`：与当前修改区域相关的架构决策记录

只有当领域语言或架构决策已经明确时，才通过 `/domain-modeling-lqy`、`/grill-with-docs-lqy` 或 `/improve-codebase-architecture-lqy` 等工作流创建或更新这些文档。

## 期望布局

```text
/
├── CONTEXT.md
├── docs/adr/
└── src/
```

## 术语使用

在 issue 标题、重构提案、假设、测试名称或文档中命名领域概念时，优先使用 `CONTEXT.md` 中定义的术语。

如果需要的概念还没有出现在 `CONTEXT.md` 中，要么重新考虑这个术语是否属于本项目，要么记录需要通过 `/domain-modeling-lqy` 补充统一语言。

## ADR 冲突

如果某个提案或实现会违背现有 ADR，必须明确指出冲突，而不是静默覆盖已有决策。
