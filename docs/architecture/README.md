# Architecture

本目录只保存当前系统结构、Module 边界、数据流、运行生命周期和 Retention 规则。可执行需求属于 GitHub `Spec:` issues；架构选择属于 [`docs/adr/`](../adr/README.md)；一次性验证结果属于 [`docs/references/`](../references/README.md)。

## 当前入口

- [ABM Runtime 与仿真流程](abm-runtime.md)：通用 SimulationModel、PlatformEnvironment、SocialUserAgent、Decision Adapter、事件和输出边界。
- [Concurrent Message Competition Experiment](concurrent-message-competition-experiment.md)：当前三 message runtime、ranking、Primary/Shadow、diagnostics、report rebuild 和发布边界。
- [Full-Pool Segmented Continuation Runtime](full-pool-segmented-continuation.md)：只读 v1 prefix、十 lane continuation、显式/自动 recovery、strict fresh replay，以及 source-v2/v3/v4 到 Report/Evidence/Release v9/v10/v11 的版本化 persisted contracts。
- [Full-Pool Two-Stage Engagement Realization](full-pool-two-stage-realization.md)：从显式 Source-v4 Provider Judgments重建 realized action、full-batch feedback、validation source/evidence/projection，并保持 legacy direct-action合同不变。
- [Report Deployment Authorization and Rollback](report-deployment.md)：Release Interface消费、v13独立operational authorization、fresh rollback readback、candidate/atomic switch、公网验收与失败恢复。
- [Full-Pool Segmented Continuation Operator](full-pool-segmented-continuation-operator.md)：显式 prepare/status/dry-run/cutover/run、人工单 PID stop、frozen-prefix reconciliation、十 lane first-wave qualification；终点为 source-v2，不含 Report/Release v9 或部署。
- [锦江用户数据结构](jinjiang-user-profile-data-structure.md)：Observed Profile Attributes、latent attributes、`interest_tags` 当前边界、`PostContent` runtime contract 和 message snapshot ownership。
- [TikHub / Douyin 数据收集架构](douyin-data-collection-architecture.md)：阶段化 collector、视频 metadata 分母、profile evidence recovery 和 quota guard。
- [Retention Audit](retention-audit.md)：tracked manifest v2、metadata-only audit、evidence reference 和删除授权边界。

## 使用规则

- 新增 current system behavior 时更新对应 Architecture Note，并保持它与实现和 release contract 一致。
- 难以逆转且存在真实替代方案的选择写入 ADR；不要在 Architecture 复制相同 rationale。
- Ticket Mermaid Gate 图只属于对应 GitHub issue；长期 Architecture 不复制 Ticket 图或强制其数量。
- 删除的 source-tree inventory、component inventory、testing strategy 和历史 single-message narrative 不再建立兼容入口。
