# llm-abm-marketing-sim 文档索引

本文件是项目文档的唯一总入口。文档只保留当前运行方式、系统设计、稳定架构决策、必要 evidence、教师周报和 Agent workflow；可执行需求与过程讨论以 GitHub `Spec:` issues 为准。

## Current Research

- **Canonical endpoint：** [Full-Pool Two-Stage Formal Research Report](https://abm.q1ngyuan.top/)。
- **Current architecture：** [Full-Pool Two-Stage Engagement Realization](architecture/full-pool-two-stage-realization.md)。
- **Historical architecture：** [Concurrent Message Competition Experiment](architecture/concurrent-message-competition-experiment.md)。

当前 v13 release 在 36,400 位 Full-Pool users、3 条 message、30 个 full-batch commits 与 109,200 次 `user × message` exposures 上，把 Provider Judgment 与 ABM Realization 分层；nested-v1 realization 得到 63,614 次 realized engagements（58.254579%）。页面发布新 Full-Pool 两阶段机制总图，并保持 Historical 1,000-user 六图及其 evidence bytes 隔离不变。默认 toy/realistic fixture、offline/mock validation 和 rule-based run 都不能替代 persisted Formal evidence 或 canonical release。

## 运行与演示

- [Guides 总览](guides/README.md)
- [macOS 从零开始运行指南](guides/getting-started-macos.md)
- [本地离线/Web Demo](guides/product-demo.md)
- [开发指南](guides/development-guide.md)
- [数据集与用户画像导入](guides/dataset-ingestion.md)
- [Provider 配置与 Live LLM 闸门](guides/provider-config.md)

默认 CLI、测试和 mock provider 路径离线、确定且无需凭证；真实 Provider 只能通过显式 live gate 运行。

## 系统设计

- [Architecture 总览](architecture/README.md)
- [ABM Runtime 与仿真流程](architecture/abm-runtime.md)
- [Concurrent Message Competition Experiment](architecture/concurrent-message-competition-experiment.md)
- [Full-Pool Segmented Continuation Runtime and Recovery Preflight](architecture/full-pool-segmented-continuation.md)
- [Full-Pool Two-Stage Engagement Realization](architecture/full-pool-two-stage-realization.md)
- [Report Deployment Authorization and Rollback](architecture/report-deployment.md)
- [Full-Pool Segmented Continuation Operator](architecture/full-pool-segmented-continuation-operator.md)
- [锦江用户数据结构](architecture/jinjiang-user-profile-data-structure.md)
- [TikHub / Douyin 数据收集架构](architecture/douyin-data-collection-architecture.md)
- [Retention Audit](architecture/retention-audit.md)
- [Architecture Decision Records](adr/README.md)

Architecture 描述当前 Module、数据边界和稳定运行语义；ADR 记录难以逆转且有真实权衡的选择。Ticket 的 executable requirements 不复制到长期 Architecture。

## Required Evidence

- [References 总览](references/README.md)
- [current dataset：锦江 final dataset 审计](references/jinjiang-final-dataset-audit-20260624.md)
- [current Formal release：Full-Pool 两阶段 v13 canonical 发布记录](references/full-pool-two-stage-v13-canonical-release-20260827.md)
- [current Retention：Retention final evidence](references/retention-cleanup-final-evidence-20260730.md)

References README 使用决策表区分默认读取、按需 research、按需 rollback 和 forensic-only evidence。Editorial v1/v2/v3 mechanism source PNG 由 `src/llm_abm_sim/report_assets/` 统一拥有；generated WebP 和 renderer compatibility contract 继续由代码与测试保护。

## 周报与 Agent workflow

- [教师周报](weekly/README.md)：按周期汇总成果和下一步，不覆盖 current Architecture、contract 或 Formal evidence。
- [Agent workflow](agents/README.md)：issue tracker、triage labels 和领域文档约定。

## 文档合同

- GitHub `Spec:` issues 是 executable requirements 和历史讨论的 canonical source。
- `CONTEXT.md`、Architecture 和 ADR 只持有稳定领域语言、当前系统边界和架构决策。
- 周报是面向教师的阅读摘要，不是实现规格、数据合同或当前架构入口。
- 删除的过程叙事由 Git history 和 GitHub issue history 保留；文档树不创建 archive、redirect tree 或兼容索引。

## 常用离线命令

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev,web,llm]"

python -m llm_abm_sim.run --config configs/default.yaml --output runs/sample
python -m llm_abm_sim.run --config configs/fixtures/realistic_marketing_dataset.yaml --output runs/realistic-sample
python -m llm_abm_sim.web --host 127.0.0.1 --port 8000 --artifact-root runs/web

python -m py_compile $(find src tests -name '*.py' -print)
pytest -q
ruff check .
```

默认验证不调用 Provider、TikHub、Douyin 或 profile API，不读取 secrets、raw Prompt 或 raw provider payload。
