# Decision Maps

本目录保存需要跨多轮会话推进的规划图。Decision map 用来记录问题序列、依赖关系、当前证据、推荐答案和未解决项。

## 使用规则

- 写这里：跨 issue、跨会话、需要先后决策的规划图。
- 不写这里：单个 PRD、一次性开发记录、研究参考、架构决策或当前实现状态。
- 当某个问题已经形成可执行需求，应迁移或引用到 `../prds/` 和 GitHub issues；当它成为难以逆转的架构权衡，应改写为 ADR 放到 `../adr/`。

## 当前入口

- [Refactor And Test Hardening Decision Map](refactor-test-hardening-2026-07.md)：规划文档迁移、重构和测试补强的多会话决策图。
