# PRDs

本目录保存 Product Requirements Documents（PRD）。PRD 描述要解决的问题、用户故事、实现决策、测试决策、非目标和后续 issue plan。

## 使用规则

- PRD 应发布到 GitHub issue tracker，但本地 Markdown 只保留长期产品决策、稳定合同解释和 historical lineage。
- GitHub `Spec:` issue 是当前 executable requirements、验收标准和 Ticket 状态的 canonical source；本地 PRD 不复制会变化的 backlog 或当前 issue 状态。
- 可执行工作应从 GitHub `Spec:` issue 拆成 `ready-for-agent` issues。

## Local PRD lineage

- [Initial ABM MVP Development Plan](initial-abm-mvp-development-plan.md)
  - Status: Historical PRD; not current backlog state
  - Related ADR: [`../adr/0001-deterministic-event-sourced-abm-mvp.md`](../adr/0001-deterministic-event-sourced-abm-mvp.md)
- [文档架构重组与锦江 Latent Attributes 迁移试点](docs-architecture-and-jinjiang-latent-attributes-migration.md)
  - Status: Completed historical PRD; superseded as executable source
  - Current replacement: [`../index.md`](../index.md) and current role READMEs; executable retention requirements live in GitHub [#124](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/124) and its Tickets.
- [锦江用户 Latent Attributes v1](jinjiang-user-latent-attributes-v1.md)
  - GitHub migration issue: [#6](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/6)
  - GitHub implementation issue: [#10](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/10)
  - Implementation issues: [#11](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/11)、[#12](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/12)、[#13](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/13)、[#14](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/14)、[#15](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/15)、[#16](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/16)、[#17](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/17)
  - Status: Published PRD; first runtime/data/reporting implementation completed and validated on the final dataset
- [锦江 ABM 用户画像合同收敛与 LLM Prompt v2](jinjiang-abm-profile-contract-and-llm-prompt-v2.md)
  - GitHub issue: [#19](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/19)
  - 实现 issues: [#21](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/21)、[#22](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/22)、[#23](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/23)、[#24](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/24)、[#25](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/25)、[#26](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/26)
  - 状态：Prompt v2 与 mocked provider E2E 作为历史 lineage 保留；#72/#75 已用 Prompt v3 撤销锦江 `interest_tags` 合同，见 [`../references/jinjiang-interest-tags-contract-audit-20260723.md`](../references/jinjiang-interest-tags-contract-audit-20260723.md)
- [锦江 LLM Prompt 人口画像消融实验](jinjiang-demographic-prompt-ablation.md)
  - GitHub issue: [#20](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/20)
  - Status: Published PRD; future optional ablation
