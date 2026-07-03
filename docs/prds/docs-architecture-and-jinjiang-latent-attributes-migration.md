# PRD: 文档架构重组与锦江 Latent Attributes 迁移试点

Status: Published to GitHub issue tracker
Triage label: `ready-for-agent`
Decision map: `docs/decision-maps/refactor-test-hardening-2026-07.md`
GitHub issue: https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/1

## 问题陈述

当前项目文档把开发计划、源码结构、组件清单、测试策略、数据集审计、研究参考和未来实施规格混放在同一个“开发验证”目录下。对维护者和后续 agent 来说，这会造成三个问题：

1. 很难判断一份文档是已实现状态、未来计划、研究参考，还是一次性审计记录。
2. 锦江用户 `latent attributes` 相关文档已经写出目标数据结构和实施方案，但当前代码尚未实现核心能力，文档没有明确标记实现状态。
3. Matt Pocock 工程 skills 需要稳定入口：领域术语、ADR、PRD、参考资料、架构说明和 issue tracker 约定；当前文档布局还没有完整支持这种工作流。

用户需要一个职责清晰、按时间和状态可维护的文档架构，使后续重构、测试补强和 latent attributes 实现可以通过 PRD 与 GitHub issues 稳定推进。

## 解决方案

重组文档职责边界，并以锦江 `latent attributes` 三份文档作为迁移试点。

目标布局：

- `CONTEXT.md`：领域术语，只放稳定概念，不放实现计划。
- `docs/adr/`：架构决策记录，只记录难以逆转、有真实权衡、未来读者会疑惑的决策。
- `docs/prds/`：PRD，描述要做什么、为什么、验收标准和后续 issue plan。
- `docs/references/`：外部研究资料、数据集说明、不可执行参考。
- `docs/architecture/`：当前/目标架构说明、数据结构图、边界说明。
- `docs/agents/`：工程 skills 的工作约定，保持已有配置。

迁移试点：

- 锦江用户潜在属性参考整理迁移为 Reference。
- 锦江用户数据结构图迁移为 Architecture Note。
- 锦江用户 Latent Attributes 实施规格迁移为 PRD，并明确“当前代码未实现”的状态。
- 旧“开发验证”入口改成薄 README，只做迁移索引和 legacy redirect，不再承载新的规格内容。

## 用户故事

1. 作为项目维护者，我想一眼看出文档是参考资料、架构说明、PRD、ADR 还是验证报告，这样我能更快判断它是否代表当前实现状态。
2. 作为项目维护者，我想让锦江 `latent attributes` 文档明确标记哪些能力已实现、哪些尚未实现，这样后续不会误以为 spec 已落地。
3. 作为项目维护者，我想把未来要做的工作写成 PRD 和 GitHub issues，这样可以按依赖顺序交给 agent 或人类执行。
4. 作为实现 agent，我想从 PRD 中看到清楚的验收标准和非目标，这样我不会把文档迁移和 runtime 功能实现混在同一个任务里。
5. 作为实现 agent，我想从 Reference 里读取研究先验，而不是从参考文档推断实现状态，这样我不会把研究材料误当作产品合同。
6. 作为实现 agent，我想从 Architecture Note 里理解“真实观测数据 + 虚拟实验标签”的目标结构，这样我能设计代码边界而不是猜字段语义。
7. 作为测试维护者，我想有一个稳定的 Documentation Navigation Contract，这样可以用轻量测试保护关键入口和链接，而不是对文档正文做脆弱断言。
8. 作为未来读者，我想旧的“开发验证”入口仍能告诉我文档搬到了哪里，这样历史链接不会突然失效。
9. 作为数据研究者，我想保留锦江 final dataset 审计和 latent attributes 研究先验的 lineage，这样我能追溯数据口径和限制。
10. 作为架构维护者，我想把领域术语放入 `CONTEXT.md`，把真正的架构权衡放入 ADR，这样后续 skills 能用一致语言推进重构。

## 实现决策

- 本 PRD 只处理文档架构和锦江 `latent attributes` 文档迁移试点，不实现 latent attributes runtime 功能。
- 保留现有中文文档内容的主体信息，但按职责迁移到新的目录结构。
- `CONTEXT.md` 第一版只收录项目稳定领域术语，例如 ABM Simulation、Social User Agent、Platform Environment、Decision Adapter、Observed Profile Attributes、Latent Attributes、Virtual Experiment Labels、Processed Variant、Dataset Audit、Live Provider Gate。
- Reference 文档只表达研究先验和限制，不表达实现状态或待办任务。
- Architecture Note 表达当前/目标数据结构与边界，并明确当前代码只支持保留未知 profile columns，不支持结构化 latent attributes contract。
- PRD 明确状态、目标、非目标、验收标准、实现状态和后续 issue plan。
- 旧开发验证目录不继续承载新规格；保留薄 README 作为迁移索引，避免历史入口断裂。
- 更新项目文档索引，使新入口成为后续阅读路径。
- 后续可由 `$to-issues-lqy` 把该 PRD 拆成 GitHub issues，并按依赖顺序发布。
- 本 PRD 的核心测试接缝是 Documentation Navigation Contract：验证文档职责入口、旧入口跳转、PRD 状态标记和 issue plan，而不是验证全文内容。

## 测试决策

- 好的测试应保护文档导航和状态合同，不测试具体行文风格或正文全文。
- 首选一个高层接缝：Documentation Navigation Contract。
- 可测试行为包括：
  - 新职责目录存在，并包含 README 或关键文档入口。
  - 锦江 latent attributes 的 Reference、Architecture Note 和 PRD 都有对应入口。
  - 旧开发验证 README 指向新路径，并声明自身是迁移索引或 legacy redirect。
  - PRD 明确包含实现状态、非目标、验收标准和 issue plan。
  - 项目文档索引指向新的职责目录。
- 不需要测试 Python runtime、CLI/Web、数据采集或仿真结果，因为本 PRD 不改变这些行为。
- 若添加自动化测试，应使用轻量 Markdown/link 检查，避免对长文本做脆弱快照。

## 超出范围

- 不实现 `UserProfile.latent_attributes`。
- 不实现 `PostContent.value_dimensions`。
- 不实现 latent spec schema/config。
- 不实现 quota assignment engine。
- 不生成新的 processed dataset variant。
- 不接入 rule-based latent score。
- 不改变 ABM 仿真规则、指标口径、CLI/Web 输入输出、报告产物语义。
- 不运行 TikHub live API。
- 不读取或打印 `.env`、API key、raw payload、nickname、bio 或 signature 明细。
- 不删除历史审计证据或 raw/processed 数据。

## 进一步说明

当前代码状态：

- 用户画像 schema 允许额外字段，但没有结构化 `latent_attributes`。
- 营销帖子 schema 没有 `value_dimensions`。
- 当前没有 latent attribute spec 配置、assignment engine、生成脚本或 audit 输出。
- 当前 rule-based decision adapter 没有 latent score。

后续 issue plan：

1. [#2 建立文档职责目录与导航骨架](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/2)
2. [#3 创建最小领域术语表 CONTEXT.md](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/3)
3. [#4 迁移锦江 latent attributes 参考资料](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/4)
4. [#5 迁移锦江用户数据结构架构说明](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/5) - 本地文档已迁移到 [`../architecture/jinjiang-user-profile-data-structure.md`](../architecture/jinjiang-user-profile-data-structure.md)
5. [#6 迁移锦江 latent attributes 实施规格为 PRD](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/6) - 本地文档已迁移到 [`jinjiang-user-latent-attributes-v1.md`](jinjiang-user-latent-attributes-v1.md)
6. [#7 添加 Documentation Navigation Contract 检查](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/7)

GitHub 发布状态：

- 已发布到 GitHub issue tracker： https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/1
- 已应用 `ready-for-agent` 标签。
