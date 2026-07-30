# References

本目录保存外部资料整理、研究先验、数据集说明、validation/release evidence 和不可执行设计参考。Reference 不替代代码、GitHub `Spec:` issue 或 release contract；每个入口通过 Status 区分 current evidence 与 historical lineage。

## Current authoritative data

- [锦江 final dataset 审计](jinjiang-final-dataset-audit-20260624.md)：最终真实 processed dataset 的 lineage、聚合计数、验收结果、profile 指标口径和隐私边界。
- [锦江 final dataset 清理记录](jinjiang-final-dataset-cleanup-20260624.md)：最终真实数据的保留与清理 lineage。
- [锦江 final dataset latent-v1 本地验收记录](jinjiang-final-dataset-latent-v1-validation-20260705.md)：36,400 用户 synthetic latent-v1 variant 的当前验证入口。
- [Retention v2 audit architecture](../architecture/retention-audit.md)：当前 tracked-manifest 只读审计合同；历史 v1 baseline 仅作为不可重执行 lineage。
- [Historical repository retention audit baseline](retention-audit-baseline-20260730.md)：历史 v1 dry-run evidence，不是当前 CLI 输入。
- [Repository retention cleanup execution](retention-cleanup-execution-20260730.md)：Ticket #130 的精确删除执行、manifest 状态更新、protected/lineage 保留核验和 post-audit aggregate evidence。
- [Repository retention cleanup final evidence](retention-cleanup-final-evidence-20260730.md)：Ticket #131 的三组 v4 contract/source closure、最终 retention audit、aggregate cleanup measurements、文档/generator/GitNexus/quality gates。
- [GitNexus index scope evidence](gitnexus-index-scope-20260730.md)：tracked `.gitnexusignore` 的 bounded source graph、exact cache reset、forced rebuild 和 symbol/query smoke。
- [锦江 `interest_tags` 合同撤销聚合审计](jinjiang-interest-tags-contract-audit-20260723.md)：当前 ranking/Prompt 字段边界的聚合审计。

## Current canonical release

- [锦江 Concurrent Message Editorial Formal 发布与验收记录](jinjiang-concurrent-message-editorial-formal-release-20260729.md)：当前 canonical `https://abm.q1ngyuan.top/` 的 Editorial destination、release id、contract/hash、rollback 和公网 acceptance。

## Release lineage

- [锦江 Concurrent Message Formal 发布与验收记录](jinjiang-concurrent-message-formal-release-20260727.md)：原始 Multi-Message Formal source 与首次 canonical release lineage。
- [锦江 Concurrent Message 双模式 Formal Presentation 发布与验收记录](jinjiang-concurrent-message-two-mode-formal-release-20260728.md)：当前 Editorial 之前的 immutable two-mode rollback lineage。
- [Multi-Message Editorial UI Design Reference](concurrent-message-editorial-ui-design/README.md)：创建时的 image-first design/media source；图片不等同 runtime evidence。

## Historical validation

- [锦江 Concurrent Message 完整离线验证记录](jinjiang-concurrent-message-complete-offline-validation-20260726.md)：offline/mock validation、deterministic rebuild 和 v4 rejection preflight，不是 Formal release。
- [锦江 Final Research 真实 Provider 验收记录](jinjiang-final-research-live-validation-20260713.md)：历史单视频 live validation。
- [锦江 Target Delivery Ranking 正式研究验收记录](jinjiang-target-delivery-ranking-final-validation-20260715.md)：历史单视频 ranking Formal validation。
- [锦江 Runtime、Decision 与 diagnostics 字段追溯离线验证记录](jinjiang-runtime-field-trace-validation-20260720.md)：历史单视频 report lineage 与 trace validation。
- [锦江 Seed-First 完整离线报告验收记录](jinjiang-seed-first-complete-offline-report-validation-20260720.md)：历史单视频完整离线报告与 rebuild evidence。
- [锦江 Prompt v2 mocked provider 验收摘要](jinjiang-prompt-v2-mock-validation-20260708.md)：历史 Prompt v2 contract 和 mocked provider E2E。

## Research and design reference

- [锦江用户潜在属性研究先验整理](jinjiang-user-latent-attributes-reference-zh.md)：latent class、价值权重、Table 11 分布和使用边界，不代表实现状态。
- [PostContent](PostContent.md)：三条原始 message 文案 source，不包含视频媒体或 runtime evidence。

`../04-开发验证/` 只保留迁移索引；不移动现有 evidence，不把历史报告改写成 current truth。
