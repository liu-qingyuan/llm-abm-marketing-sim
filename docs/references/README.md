# References

本目录只保留必须读取的数据 lineage、Formal release、Retention evidence、研究先验和按需 presentation audit。Reference 不替代代码、Architecture、ADR 或 GitHub `Spec:` issue；删除的过程叙事由 Git history 和 issue history 保留，不在这里建立 archive、redirect 或兼容索引。

## AI 阅读决策表

默认 AI 阅读顺序不超过 `current dataset`、`current Editorial`、`current Retention` 三个入口；只有问题需要时才进入 research prior 或 rollback evidence，machine evidence 仅用于 forensic-only 核验。

| 模式 | 入口 | 读取场景 |
|---|---|---|
| 默认读取 | [current dataset：锦江 final dataset 审计](jinjiang-final-dataset-audit-20260624.md)、[current Editorial：Editorial Formal release](jinjiang-concurrent-message-editorial-formal-release-20260729.md)、[current Retention：Retention final evidence](retention-cleanup-final-evidence-20260730.md) | 先确定数据 lineage、当前发布身份和保留/质量 closure。 |
| 按需 research | [final dataset cleanup](jinjiang-final-dataset-cleanup-20260624.md)、[latent-v1 validation](jinjiang-final-dataset-latent-v1-validation-20260705.md)、[Latent Attributes 研究先验](jinjiang-user-latent-attributes-reference-zh.md) | 需要追溯数据清理、合成 variant 或研究先验时读取。 |
| 按需 presentation audit | [Concurrent Message legend 与视觉语义调查](concurrent-message-legend-visual-semantics-audit-20260803.md)、[Editorial v2 Visual Encoding References](concurrent-message-editorial-v2-visual-encoding-references/)、[Sensitivity 多曲线视觉参考](concurrent-message-sensitivity-curve-visual-reference-20260803.md) | legend audit 是视觉语义 source of truth；五张 Visual Encoding References 是等待一次性人工批准的固定审批集合；sensitivity 参考只提供宽幅多曲线 composition、外置图例和线型 grammar。它们都不提供新的研究数据或部署授权。 |
| 按需 rollback | [Original Formal release](jinjiang-concurrent-message-formal-release-20260727.md)、[Two-mode rollback release](jinjiang-concurrent-message-two-mode-formal-release-20260728.md) | 需要检查当前 Editorial 之前的 release lineage 或回滚身份时读取。 |
| forensic-only | [Retention machine evidence](retention-cleanup-execution-20260730.json) | 需要核对 exact machine-readable cleanup evidence、文件 bytes 或目录 postcondition 时读取；不要把它当作默认叙事入口。 |

## Asset ownership

五张 `media-mechanism-*.png` 是 Editorial candidate 的 exact source assets，现由 `src/llm_abm_sim/report_assets/` 与同目录 generated WebP 共同拥有。source SHA-256、candidate contract、generated assets 和 published report bytes 由代码、测试和 Formal evidence 持续验证。

`concurrent-message-editorial-v2-visual-encoding-references/` 包含五张独立 `1536 × 1024` Visual Encoding References 及一个 set-level README；它们只固定 audit 的 27 个 target items 与 annotation boundary，获得一次性人工批准前不得生成完整 v2 机制图。

`concurrent-message-sensitivity-curve-visual-reference-20260803.jpg` 是用户提供的 presentation-only 构图参考，原始 publication metadata 未记录；它不得作为研究证据或 production chart 直接发布。creation-time desktop/run/trace screenshots 仍不属于当前 References。
