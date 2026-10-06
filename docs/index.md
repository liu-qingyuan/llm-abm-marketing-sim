# llm-abm-marketing-sim 文档索引

本文件是项目文档的唯一总入口。文档只保留当前运行方式、系统设计、稳定架构决策、必要 evidence、教师周报和 Agent workflow；可执行需求与过程讨论以 GitHub `Spec:` issues 为准。

## Current Research：统一研究入口

[Canonical Final Research](https://abm.q1ngyuan.top/) 已发布 **composite v16**，保留 Whole sample、Prompt–Model 修订研究及历史结果/下载，追加 Parameter 与 Activity / Local Influence 两项独立研究。2026-09-20 11:44 UTC 完成原子发布与公网验收；HTML SHA-256 为 `e7c9cc0bffb8a148376fed4b49b58d8574784540a6b2dbaf0f8845a2d0cff659`。[发布及验证记录](references/sensitivity-v16-canonical-release-20260920.md)。

### 研究地图

| 研究 / 问题 | 改变与固定设定 | 样本、seed 与统计单位 | 最终证据 / 发布状态 |
|---|---|---|---|
| **Whole sample**：三条营销消息在全样本中的两阶段互动结果 | GPT-5.6 Sol / P0；Judgment → Realization；固定消息、网络与行为 seed | 36,400 用户 × M1–M3；109,200 次曝光；单次固定行为 seed，互动次数为整数 | [v13 主实验证据](references/full-pool-two-stage-v13-canonical-release-20260827.md)；已保留于 canonical v16 |
| **Prompt–Model 修订研究**：判断模板与模型变化对应什么结果 | 4 模型 × P0–P3；16 cells；新两阶段机制，与早期 direct-action 分开 | 1,000 用户样本；28,800 次曝光；直接配对限共同 Batch 0，后续自适应路径仅描述 | [v15 最终证据与下载](references/revised-four-model-v15-canonical-release-20260912.md)；已发布；**原五模型计划并非全部完成** |
| **Parameter**：推荐权重和邻居饱和阈值改变终点或时间路径吗 | GPT-5.6 Sol / P0；固定判断库、原样本/消息/图；7 权重点 × 阈值 1/3/6 | 1,000 用户；21 组 × 100 行为 seed = 2,100 路径；每路径 1,800 曝光；跨 seed 均值/区间 | [最终结果](references/gpt-p0-dynamic-parameter-results-20260917.md) · [本地报告](../runs/gpt-p0-dynamic-parameters-20260917-formal-01/report/report.html)；[已发布在线报告](https://abm.q1ngyuan.top/parameter/report.html) |
| **Activity / Local Influence**：指标变体及其抽样联动如何改变传播 | GPT-5.6 Sol / P0；推荐权重固定 0.50/0.30/0.20、阈值 3；改变指标权重或 p99 归一化 | 每臂 1,000 用户；7 组 × 100 行为 seed = 700 路径；每路径 1,800 曝光；同 seed 配对均值/区间 | [最终报告](../runs/gpt-p0-index-sensitivity-20260920-formal-01/REPORT.md) · [本地网页](../runs/gpt-p0-index-sensitivity-20260920-formal-01/report.html) · [完成审计](../runs/gpt-p0-index-sensitivity-20260920-formal-01/completion-audit.json)；[已发布在线报告](https://abm.q1ngyuan.top/index-sensitivity/report.html) |
| **历史研究**：direct-action 与指标排序审计 | 保留原机制、来源及原下载，不改写成新两阶段结果 | 原 1,000 用户研究与全样本分开；历史指标排序分析**不是传播仿真实验** | canonical 既有 Historical / Primary–Shadow / Ranking Weight / 旧 GPT 析因；不得与新研究合并分母 |

### 先读口径，再读结果

- P0–P3 是 AI 判断模板；M1–M3 是营销消息；S1–S3 是用户群，三者不互换。
- 每次行为实现的互动数是整数。Parameter 与指标研究表中的小数是 **100 次实现的均值**；100 个行为 seed 不表示 LLM 重复判断 100 次，也不与 Whole sample 单次结果混作同一统计单位。
- Parameter 在所测矩阵中，同 seed 终点相同，但曝光顺序和时间过程发生变化；不推断推荐参数普遍不敏感。
- 指标研究区分**固定样本、重选初始种子**与**按原规则重建样本**。Local p99 重建后只有 108/1000 用户与基线重合；差异包含样本构成影响。Local 权重固定/重建臂输入相同，不算独立重复证据。
- 行为 seed 区间仅反映固定判断/数据条件下的 Monte Carlo 不确定性。新旧判断时点与模型回答波动未充分分离；不宣称普遍稳健或纯指标因果效应。

### 权威 ownership 与发布接缝

本页唯一拥有跨研究导航、统计口径对照与当前发布状态，不另建平行研究目录。单项结论及数值由各自最终 evidence/report 拥有；Module 的稳定 Interface 由架构文档说明：

- [Whole sample / 两阶段机制](architecture/full-pool-two-stage-realization.md)
- [十采集话题合并网络与独立离线重放合同](architecture/ten-topic-full-pool-replay.md)（新方法；既有 canonical 及历史结果不变）
- [Prompt–Model / v15 Report、Release 合同](architecture/revised-four-model-release.md)
- [Parameter / Study、Evidence、Report](architecture/gpt-p0-parameter-study.md)
- [Deployment / 原子发布与回退](architecture/report-deployment.md)

Report Module 拥有研究呈现及表图同源知识；Release Module 拥有证据接纳、旧文件保留和 immutable inventory；Deployment Module 只消费验证后的发布事实。这个 Seam 保持 Locality，避免把研究判断规则复制到 shell 或网页拼接器而形成 Information Leakage；不为导航增加透传 Module 或通用框架，Depth 来自既有 Interface 对证据与产物的完整验证。

**发布合同：** v15 仍只接纳四模型闭合 projection；v16 以独立接纳合同追加这两项已完成研究。指标研究的 [evidence](../runs/gpt-p0-index-sensitivity-20260920-formal-01/evidence.json) 与 [曝光判断闭合](../runs/gpt-p0-index-sensitivity-20260920-formal-01/exposure-bank-closure.json) 明确 `production_deploy_eligible=false`：17,316 个 eligible inputs 中 17,315 个有判断，另 1 个 unknown 保留且已证明不会曝光，700 条路径所需曝光完整。这不等同完整判断库。经用户批准，v16 对明确绑定的最终证据与发布产物完成接纳验证；原字段、run 与账本不变。发布沿既有 Release / Deployment 事务完成，原 v15 保留为回退版本。验收记录见 [Operational #263](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/263)。

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
- [Prompt–Model Realized Table-First Report](architecture/prompt-model-realized-report.md)
- [Revised Four-Model Recovery Research / v15 release contract](architecture/revised-four-model-release.md)
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
- [current composite release：两项敏感性研究追加 v16 发布记录](references/sensitivity-v16-canonical-release-20260920.md)
- [protected v15：四模型恢复研究及回退记录](references/revised-four-model-v15-canonical-release-20260912.md)
- [protected main evidence：Full-Pool 两阶段 v13 canonical 发布记录](references/full-pool-two-stage-v13-canonical-release-20260827.md)
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
