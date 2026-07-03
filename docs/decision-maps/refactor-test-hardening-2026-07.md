# Refactor And Test Hardening Decision Map

本决策图用于规划 `llm-abm-marketing-sim` 的一轮重构与测试补强。目标是降低模块耦合、明确数据收集边界，并让测试保护核心行为。

## Confirmed Boundaries

- 用户可见行为保持不变：CLI/Web 输入输出、离线默认运行、事件/指标/报告产物语义不改。
- 本轮先补结构和测试安全网，不顺手改变仿真规则、指标口径或数据采集策略。
- 文档架构目标是补齐 Matt Pocock 工程 skills 需要的稳定入口，而不是推倒重写现有中文文档。
- 新文档职责边界：
  - `CONTEXT.md`：领域术语，只放稳定概念。
  - `docs/adr/`：架构决策记录。
  - `docs/prds/`：PRD，描述要做什么、为什么、验收标准。
  - `docs/references/`：外部资料整理、研究先验、不可执行参考。
  - `docs/architecture/`：当前/目标架构说明、数据结构图、边界说明。
  - `docs/agents/`：工程 skills 工作约定。
- `docs/04-开发验证/` 后续只保留薄 README 作为迁移索引或 legacy redirect。
- 第一优先级是锦江 latent attributes 文档迁移试点，然后才进入核心仿真测试补强和模块重构。

## #1: Jinjiang Latent Attributes Docs Migration Pilot

Blocked by: none
Type: Grilling

### Question

如何把 `docs/04-开发验证/07/08/09` 从混合开发验证文档改成职责清晰、可维护、能被后续 PRD/issue 工作流消费的结构？

### Current Evidence

- `docs/references/jinjiang-user-latent-attributes-reference-zh.md` 是研究先验整理，适合作为 Reference。
- `08-jinjiang-user-data-structure-diagrams.md` 是目标数据结构图，适合作为 `docs/architecture/` 下的 Architecture Note。
- `09-jinjiang-user-latent-attributes-spec.md` 是实施规格，但当前代码未实现其核心功能，应改成 `docs/prds/` 下的 PRD 并显式标记实现状态。
- 当前代码没有结构化 `UserProfile.latent_attributes`、`PostContent.value_dimensions`、latent spec config、latent assignment engine、生成脚本或 rule-based latent score。
- `UserProfile` 目前通过 `extra="allow"` 只能保留未知列，不能表达 structured latent attributes contract。

### Answer

已产出 PRD：`docs/prds/docs-architecture-and-jinjiang-latent-attributes-migration.md`。

PRD 决策：先以锦江 latent attributes 三份文档作为迁移试点，迁移为 Reference / Architecture Note / PRD，并明确当前代码未实现结构化 latent attributes。测试接缝采用 Documentation Navigation Contract，保护职责目录、旧入口跳转、PRD 状态标记和 issue plan。

GitHub issue: https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/1

Child issues:

- #2: https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/2
- #3: https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/3
- #4: https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/4
- #5: https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/5
- #6: https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/6
- #7: https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/7

## #2: Minimal Domain Language For Refactor Work

Blocked by: #1
Type: Grilling

### Question

`CONTEXT.md` 第一版应该收录哪些稳定领域术语，才能支持后续重构、测试和 PRD 拆分，同时避免把实现细节写成领域语言？

### Current Evidence

候选术语包括：ABM Simulation、Social User Agent、Platform Environment、Decision Adapter、Observed Profile Attributes、Latent Attributes、Virtual Experiment Labels、Processed Variant、Dataset Audit、Live Provider Gate。

### Answer

Unresolved. 解决时应创建或更新根目录 `CONTEXT.md`，只写领域术语，不写实现计划或架构决策。

## #3: Migrate Remaining Development Verification Docs

Blocked by: #1, #2
Type: Grilling

### Question

`docs/04-开发验证/01-06` 应该如何迁移到 `docs/prds/`、`docs/architecture/`、`docs/references/` 或报告目录，并如何保留旧入口跳转？

### Current Evidence

- `01-development-plan.md` 更像旧开发计划或初始 PRD。
- `02-source-tree-analysis.md` 和 `03-component-inventory.md` 更像架构说明。
- `04-test-strategy.md` 是测试策略，可归入 architecture 或 testing strategy。
- `05-jinjiang-douyin-final-dataset-20260624.md` 是数据集审计/参考。
- `06-jinjiang-douyin-final-dataset-cleanup-20260624.md` 是清理报告。

### Answer

Unresolved. 解决时应避免丢失当前最终数据集 lineage，并更新 `docs/index.md`、`docs/04-开发验证/README.md` 和任何内部链接。

## #4: Core Simulation Characterization Tests

Blocked by: #3
Type: Grilling

### Question

重构前哪些核心仿真行为必须被 characterization tests 锁住，才能保护曝光、决策、动作、指标和 trace 语义？

### Current Evidence

核心协作链路是 `ExperimentRunner -> SimulationModel -> PlatformEnvironment -> SocialUserAgent -> LLMDecisionAdapter -> MetricsCollector -> outputs/report_payload`。已有测试覆盖默认离线运行、部分 runner determinism、指标合同和报告 smoke，但需要按行为合同重新审查覆盖缺口。

### Answer

Unresolved. 推荐重点检查：seed exposure、peer exposure boost、share exposure boost、absorbing engagement、decision cache key、event ordering、metrics summary、graph trace payload、dataset validation。

## #5: Runtime Boundary Refactor Plan

Blocked by: #4
Type: Grilling

### Question

如何降低核心 runtime 与 runner/output/web/data loading 的耦合，同时保持 CLI/Web 行为和产物语义不变？

### Current Evidence

当前 `ExperimentRunner` 同时负责配置加载、dataset 构建、adapter 选择、model 组装和输出编排。`SimulationModel` 持有 step orchestration，`PlatformEnvironment` 持有曝光和互动状态，`SocialUserAgent` 调用决策边界。

### Answer

Unresolved. 解决时应先做依赖方向和公开 contract 设计，再拆小 issues；不要先做大规模文件移动。

## #6: Data Collection Boundary Refactor Plan

Blocked by: #3, #4
Type: Grilling

### Question

如何明确 TikHub/Douyin 数据采集、processed dataset 派生、latent attribute 生成和 ABM dataset loading 之间的边界？

### Current Evidence

现有项目规则要求数据采集阶段化：`challenge_index`、`video_metadata`、`comments`、`replies`、`profiles`。锦江 latent attributes 方案明确不应写死在 TikHub collector 主流程里，应作为 processed variant 生成能力。

### Answer

Unresolved. 解决时应明确：live collection、processed normalization、profile index、latent attributes assignment、ABM ingestion 分别属于哪个模块和测试层。

## #7: Latent Attributes Implementation Backlog

Blocked by: #1, #6
Type: Grilling

### Question

`jinjiang-latent-attributes-v1` PRD 应拆成哪些 GitHub issues，才能按可验证增量实现并防止“文档写了但代码没标记”的状态再次出现？

### Current Evidence

候选 issue 序列：latent spec schema/config、quota assignment engine、generated processed variant + audit、`UserProfile.latent_attributes` loader support、`PostContent.value_dimensions`、rule-based latent score、report/group analysis、tests/CI coverage。

### Answer

Unresolved. 解决时应使用 `docs/agents/issue-tracker.md` 和 `docs/agents/triage-labels.md` 的约定，把可执行工作发布到 GitHub Issues。
