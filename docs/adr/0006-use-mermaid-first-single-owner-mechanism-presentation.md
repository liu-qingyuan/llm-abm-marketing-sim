# ADR 0006: 机制展示使用 Mermaid-first 单一语义所有者

Status: Accepted (architecture decision; semantic master set approval pending)

## Context

Final Research 的机制关系此前分别由 Report semantic helpers、Editorial 图像目录、DOM 文案和文本 fallback 持有。一次关系变更需要多个 Module 重复理解节点、边、标签和图像意图，容易让 Research Sample、三条独立投放容量、同次曝光 Primary/Shadow 以及 next-batch feedback 边界发生漂移。直接重画 raster 或原地修改 v6 还会失去可审计语义源，并破坏历史 release compatibility。

## Decision

未来机制 presentation 采用以下合同：

1. **Mermaid-first。** 先由确定性的 Mermaid Semantic Masters 固定节点、边、泳道和稳定英文 semantic IDs；DOM、完整文本 fallback 与 image-generation brief 都是同一语义定义的投影，而不是从 raster 反向解释关系。
2. **Single owner。** package-internal `concurrent_message_mechanism_presentation` Module 通过一个 Interface 拥有六张母版、三层 ownership、双语标签、Mermaid serialization、DOM/fallback projection keys 和 image brief。Report 与 Editorial 只作为该 Interface 的 Adapter，不分别维护同一知识；不新增 public Interface 或通用 diagram framework。
3. **完整双语投影。** Mermaid 母版使用“中文在前、英文在后”的审阅标签；网页 Adapter 从同一 catalog 分别投影纯 `zh-CN` 与纯 `en-US`，稳定 ID、公式、schema token 和 artifact filename 不翻译。
4. **两次整组审批。** 六张 Mermaid masters 必须以一个 exact filename/hash set 获得整组人工批准，之后才可生成五张 raster；五张 accepted PNG 还必须作为一个 exact hash set 再次批准。缺图、部分批准、跨 comment 拼接或批准后 byte mutation 都失败关闭。
5. **Additive release。** 新 presentation 只能通过 additive payload、closure 和 release contract 晋升；现有 payload v1、closure v1、v5/v6 release、v1–v3 assets 与 persisted evidence bytes 保持不变。未批准的语义或图像资产不能进入 canonical release。

## Consequences

- 机制关系的变化集中在一个 Module，Mermaid、DOM、fallback 和资产 brief 可以通过同一 package-internal Interface 与 deterministic tests 对照。
- 人工审批成为明确的 hash gate；image generation 不得先于语义批准，renderer integration 不得先于视觉批准。
- 中文和英文不再由不同调用方手工拼接，但 authoritative source values 与稳定 token 继续保持原值。
- 当前 v1/v6 presentation 不因接受本 ADR 自动变化；新 Module 在审批和 additive release 合同完成前只是独立的、不可部署语义源。
- 代价是新增两个人工等待点和版本化资产管理，但它们换取可审计语义、视觉一致性和历史 release compatibility。

## Rejected alternatives

- **Raster-first，再补 Mermaid。** 像素不能可靠持有 edge endpoints、反馈停止路径或双语 key parity。
- **Report 与 Editorial 各自维护投影。** 继续泄漏同一机制知识，并允许 DOM、fallback 和生成图 brief 独立漂移。
- **直接替换 v6 下载和资产。** 会把 presentation redesign 伪装成历史 release 的 byte-compatible 修改。
- **引入通用 diagram framework。** 当前六图不需要新的 public abstraction 或依赖；专用深 Module 已足以隐藏语义复杂度。
