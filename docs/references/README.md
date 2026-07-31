# References

本目录只导航必须保留的数据 lineage、Formal release、Retention/GitNexus evidence 和研究先验。Reference 不替代代码、Architecture、ADR 或 GitHub `Spec:` issue；它也不把历史过程报告重新包装为 current truth。

## 数据与研究

- [锦江 final dataset 审计](jinjiang-final-dataset-audit-20260624.md)：真实 processed dataset lineage、聚合计数和隐私边界。
- [锦江 final dataset cleanup](jinjiang-final-dataset-cleanup-20260624.md)：最终真实数据的保留与清理 lineage。
- [锦江 final dataset latent-v1 validation](jinjiang-final-dataset-latent-v1-validation-20260705.md)：合成 latent variant 的确定性重建和聚合验收。
- [锦江用户 latent attributes 研究先验](jinjiang-user-latent-attributes-reference-zh.md)：latent class、value weights、Table 11 分布和使用限制。
- [PostContent](PostContent.md)：三条原始 message 文案 source，不包含 runtime evidence。

## Formal release

- [Original Concurrent Message Formal release](jinjiang-concurrent-message-formal-release-20260727.md)：原始 Multi-Message Formal source 与首次 release lineage。
- [Two-mode rollback release](jinjiang-concurrent-message-two-mode-formal-release-20260728.md)：Editorial 之前的 immutable rollback lineage。
- [Editorial Formal release](jinjiang-concurrent-message-editorial-formal-release-20260729.md)：当前 canonical endpoint、release id、contract/hash、rollback 和公网 acceptance。

## Retention 与 GitNexus

- [Retention baseline](retention-audit-baseline-20260730.md)：历史 v1 dry-run aggregate evidence。
- [Retention cleanup execution](retention-cleanup-execution-20260730.md)：精确 cleanup execution 与保留核验。
- [Retention cleanup machine evidence](retention-cleanup-execution-20260730.json)：机器可读的 cleanup evidence，bytes 保持不变。
- [Retention cleanup final evidence](retention-cleanup-final-evidence-20260730.md)：release、retention、documentation 和 quality gates 的最终 aggregate closure。
- [GitNexus index scope evidence](gitnexus-index-scope-20260730.md)：tracked `.gitnexusignore`、bounded rebuild 和 retention scope evidence。

## Asset ownership

五张 `media-mechanism-*.png` 是 Editorial candidate 的 exact source assets，现由 `src/llm_abm_sim/report_assets/` 与同目录 generated WebP 共同拥有。source SHA-256、candidate contract、generated assets 和 published report bytes 由代码、测试和 Formal evidence 持续验证；creation-time desktop/run/trace screenshots 不属于当前 References。
