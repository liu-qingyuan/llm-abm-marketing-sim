# References

本目录只保留必须读取的数据 lineage、Formal release、Retention evidence、研究先验和按需 presentation audit。Reference 不替代代码、Architecture、ADR 或 GitHub `Spec:` issue；删除的过程叙事由 Git history 和 issue history 保留，不在这里建立 archive、redirect 或兼容索引。

## AI 阅读决策表

默认 AI 阅读顺序不超过 `current dataset`、`current Formal release`、`current Retention` 三个入口；只有问题需要时才进入 research prior 或 rollback evidence，machine evidence 仅用于 forensic-only 核验。

| 模式 | 入口 | 读取场景 |
|---|---|---|
| 默认读取 | [current dataset：锦江 final dataset 审计](jinjiang-final-dataset-audit-20260624.md)、[current Formal release：Concurrent Robustness v7](jinjiang-concurrent-robustness-v7-canonical-release-20260813.md)、[current Retention：Retention final evidence](retention-cleanup-final-evidence-20260730.md) | 先确定数据 lineage、当前发布身份和保留/质量 closure。 |
| 按需 research | [final dataset cleanup](jinjiang-final-dataset-cleanup-20260624.md)、[latent-v1 validation](jinjiang-final-dataset-latent-v1-validation-20260705.md)、[Latent Attributes 研究先验](jinjiang-user-latent-attributes-reference-zh.md) | 需要追溯数据清理、合成 variant 或研究先验时读取。 |
| 按需 presentation audit | [v4 机制语义母版低保真审批集](concurrent-message-mechanism-semantic-masters-v4-review.md)、[已拒绝的 v4 图像历史审阅包](concurrent-message-mechanism-images-v4-review.md)、[Concurrent Message legend 与视觉语义调查](concurrent-message-legend-visual-semantics-audit-20260803.md)、[Editorial v2 Visual Encoding References](concurrent-message-editorial-v2-visual-encoding-references/)、[Sensitivity 多曲线视觉参考](concurrent-message-sensitivity-curve-visual-reference-20260803.md) | Mermaid masters 是 v7 的已批准语义源；v4 PNG/WebP 审阅包只保留被拒绝的 pre-release audit，不是 payload、closure、release 或 deployment 输入；legend audit 是历史视觉语义 source of truth；五张 Visual Encoding References 是已一次性批准的固定 mark inventory；sensitivity 参考只提供宽幅多曲线 composition、外置图例和线型 grammar。它们都不提供新的研究数据或部署授权。 |
| 按需 rollback | [Concurrent Robustness v6 rollback release](jinjiang-concurrent-robustness-v6-local-release-20260813.md)、[Concurrent Robustness v5 rollback release](jinjiang-concurrent-robustness-formal-release-20260810.md)、[Editorial v3 rollback release](jinjiang-concurrent-message-editorial-v3-formal-release-20260807.md)、[Editorial v2 rollback release](jinjiang-concurrent-message-editorial-v2-formal-release-20260807.md)、[Editorial v1 rollback release](jinjiang-concurrent-message-editorial-formal-release-20260729.md)、[Original Formal release](jinjiang-concurrent-message-formal-release-20260727.md)、[Two-mode rollback release](jinjiang-concurrent-message-two-mode-formal-release-20260728.md) | 需要检查当前 Robustness v7 release 之前的 release lineage 或回滚身份时读取。 |
| forensic-only | [Retention machine evidence](retention-cleanup-execution-20260730.json) | 需要核对 exact machine-readable cleanup evidence、文件 bytes 或目录 postcondition 时读取；不要把它当作默认叙事入口。 |

## Asset ownership

五张 `media-mechanism-*.png` 与 `editorial-mechanism-*-v1.webp` 继续冻结 Editorial v1 rollback；五组 `editorial-mechanism-*-v2.png/.webp` 冻结 Editorial v2 rollback；五组 versioned `editorial-mechanism-*-v3.png/.webp` 继续作为当前 Robustness canonical report 的历史 mechanism presentation source/derivative assets。它们统一由 `src/llm_abm_sim/report_assets/` 拥有，source/derivative SHA-256、renderer compatibility goldens 和 published v1/v2/v3 report bytes 由代码、测试与 Formal release evidence 保护。

六张 `mechanism-*.mmd` / `real-batch-mechanism.mmd` 由 package-internal Mechanism Presentation Module 确定性生成并保存在 `src/llm_abm_sim/report_assets/`；`concurrent-message-mechanism-semantic-masters-v4-review.md` 保留网页外整组审批证据。GitHub #185 已批准这组 bytes；它们已通过 payload v2、closure v2、immutable v7 release 与 deployment gate 进入 canonical download set，同时没有原地改变 v1/v6 presentation。被拒绝的 v4 PNG/WebP 与 generation audit 只由历史审阅包记录，不属于该 release lineage。

`concurrent-message-editorial-v2-visual-encoding-references/` 包含五张独立 `1536 × 1024` Visual Encoding References 及一个 set-level README；它们已一次性批准，并只固定 audit 的 27 个 target items 与 annotation boundary，不是 production mechanism assets、研究数据或部署证据。

`concurrent-message-sensitivity-curve-visual-reference-20260803.jpg` 是用户提供的 presentation-only 构图参考，原始 publication metadata 未记录；它不得作为研究证据或 production chart 直接发布。creation-time desktop/run/trace screenshots 仍不属于当前 References。
