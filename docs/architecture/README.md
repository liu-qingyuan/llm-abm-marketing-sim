# Architecture

本目录只保存当前系统结构、Module 边界、数据流、运行生命周期和 Retention 规则。可执行需求属于 GitHub `Spec:` issues；架构选择属于 [`docs/adr/`](../adr/README.md)；一次性验证结果属于 [`docs/references/`](../references/README.md)。

## 当前入口

- [ABM Runtime 与仿真流程](abm-runtime.md)：通用 SimulationModel、PlatformEnvironment、SocialUserAgent、Decision Adapter、事件和输出边界。
- [Concurrent Message Competition Experiment](concurrent-message-competition-experiment.md)：当前三 message runtime、ranking、Primary/Shadow、diagnostics、report rebuild 和发布边界。
- [锦江用户数据结构](jinjiang-user-profile-data-structure.md)：Observed Profile Attributes、latent attributes、`interest_tags` 当前边界、`PostContent` runtime contract 和 message snapshot ownership。
- [TikHub / Douyin 数据收集架构](douyin-data-collection-architecture.md)：阶段化 collector、视频 metadata 分母、profile evidence recovery 和 quota guard。
- [Retention Audit](retention-audit.md)：tracked manifest v2、metadata-only audit、evidence reference 和删除授权边界。

## 使用规则

- 新增 current system behavior 时更新对应 Architecture Note，并保持它与实现和 release contract 一致。
- 难以逆转且存在真实替代方案的选择写入 ADR；不要在 Architecture 复制相同 rationale。
- Ticket Mermaid Gate 图只属于对应 GitHub issue；长期 Architecture 不复制 Ticket 图或强制其数量。
- 删除的 source-tree inventory、component inventory、testing strategy 和历史 single-message narrative 不再建立兼容入口。
