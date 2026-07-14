# References

本目录保存外部资料整理、研究先验、数据集说明和不可执行参考。

## 使用规则

- 写这里：研究表格整理、数据口径参考、外部方法说明、只读背景资料。
- 不写这里：实现规格、验收标准、架构决策、当前任务状态。
- Reference 可以被 PRD、Architecture Note 或 ADR 引用，但自身不代表已实现状态。

## 当前入口

- [锦江 final dataset 审计](jinjiang-final-dataset-audit-20260624.md)：最终数据集 lineage、聚合计数、验收结果、profile 指标口径和隐私边界。
- [锦江 final dataset 清理记录](jinjiang-final-dataset-cleanup-20260624.md)：本地旧 run 和中间数据清理记录，只含聚合统计和路径。
- [锦江 final dataset latent-v1 本地验收记录](jinjiang-final-dataset-latent-v1-validation-20260705.md)：36,400 用户 latent-v1 processed variant 的聚合验收、class counts、Table 11 profile counts 和隐私边界。
- [锦江 Prompt v2 mocked provider 验收摘要](jinjiang-prompt-v2-mock-validation-20260708.md)：#19 主 Prompt v2 的 prompt contract、mocked provider、ABM event/report 端到端 aggregate-only 验收摘要。
- [锦江 Final Research 真实 Provider 验收记录](jinjiang-final-research-live-validation-20260713.md)：#31 的 1,000 用户、30 批次真实 Provider 最终研究运行配置、聚合结果、artifact 清单、浏览器验证和研究限制。
- [锦江 Target Delivery Ranking 正式研究验收记录](jinjiang-target-delivery-ranking-final-validation-20260715.md)：#43 的 1,000 用户、30 批次、600 次真实 Provider 排序运行、网络配对消融、artifact reconciliation 和真实网页验收。
- [锦江用户潜在属性研究先验整理](jinjiang-user-latent-attributes-reference-zh.md)：latent class、价值权重、Table 11 成员画像分布和使用边界，只作为外部研究先验，不代表当前代码实现状态。

`../04-开发验证/` 只保留迁移索引；迁移后的 Reference 文档必须保留 lineage、旧文件名和聚合口径说明。
