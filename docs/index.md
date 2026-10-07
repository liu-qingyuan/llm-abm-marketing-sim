# llm-abm-marketing-sim 文档索引

本文件是项目文档的唯一总入口。文档只保留当前运行方式、系统设计、稳定架构决策、必要 evidence、教师周报和 Agent workflow；可执行需求与过程讨论以 GitHub `Spec:` issues 为准。

## Current Research：统一研究入口

[Canonical Final Research](https://abm.q1ngyuan.top/) 已发布 **十话题 v17**：全样本、推荐参数、用户指标敏感性与四模型×P0–P3统一接入正式 Report / Release。2026-10-07 12:11 UTC 完成原子发布、公网正文/交互/下载及最终身份验收；发布过程零 Provider 调用。单话题 v16 与更早历史结果及下载保留为明确标识的旧版。[发布记录](references/ten-topic-v17-canonical-release-20261007.md)。
### 研究地图

十话题成果已并入原项目 main；本地正式目录持久保存、历史绝对路径与原字节不改写。[持久来源映射及读取方法](references/ten-topic-main-preservation-20261008.md)。

| 研究 / 问题 | 改变与固定设定 | 样本、seed 与统计单位 | 最终证据 / 发布状态 |
|---|---|---|---|
| **Whole sample**：全样本两阶段实际互动 | GPT-5.6 Sol / P0；十话题合并历史图，既有判断与抽样锚点离线复用 | 36,400用户；109,200曝光；单次行为seed20260823；实际互动63,614/109,200 = 58.255% | [正式来源及复验](../runs/ten-topic-full-pool-20261006/REPORT.md)；canonical v17默认视图 |
| **Prompt–Model**：四模型与P0–P3 | 同一新基准1,000人；4模型×4模板；新DeepSeek V4.1 Flash与旧V4 Flash有版本差异 | 16条件、28,800曝光；单次行为seed；共同初始用户panel配对，自适应路径描述 | [四模型正式验收](../runs/ten-topic-four-model-20261007/FINAL_REPORT.md)；canonical v17 |
| **Parameter**：推荐权重与邻居饱和阈值 | 十话题新基准样本；原21参数矩阵、GPT-5.6 Sol / P0 | 21×100行为seed=2,100路径；每路径1,800曝光；终点均值范围62.278%–65.848% | [GPT两研究最终验收](../runs/ten-topic-gpt-final-acceptance-20261007/REPORT.md)；canonical v17 |
| **Activity / Local Influence**：指标变体与抽样联动 | 原7臂，固定样本与重建样本按协议区分；Local原全话题度数口径不变 | 7×100行为seed=700路径；每路径1,800曝光；Local p99 rebuilt与新基准23/1000重合 | [正式统计](../runs/ten-topic-gpt-studies-20261006/formal-report/REPORT.md)；canonical v17 |
| **旧版与历史** | 单话题v16、早期direct-action与历史指标排序分别保留 | 不与十话题结果合并分母；排序审计不是传播实验 | canonical“旧版与历史研究”；v16仍保留为回滚版本 |

### 先读口径，再读结果

- P0–P3 是 AI 判断模板；M1–M3 是营销消息；S1–S3 是用户群，三者不互换。
- 每次行为实现的互动数是整数。Parameter 与指标研究表中的小数是 **100 次实现的均值**；100 个行为 seed 不表示 LLM 重复判断 100 次，也不与 Whole sample 单次结果混作同一统计单位。
- 十话题 Parameter 在所测矩阵中终点不再全部相同；差异包括曝光排序及反馈路径，不推断普遍稳健或不敏感。
- 指标研究区分**固定样本、重选初始种子**与**按原规则重建样本**。十话题 Local p99 重建后只有 23/1000 用户与新基线重合；差异包含样本构成影响。Local 权重固定/重建臂输入相同，不算独立重复证据。
- 行为 seed 区间仅反映固定判断/数据条件下的 Monte Carlo 不确定性。新旧判断时点与模型回答波动未充分分离；不宣称普遍稳健或纯指标因果效应。

### 权威 ownership 与发布接缝

本页唯一拥有跨研究导航、统计口径对照与当前发布状态，不另建平行研究目录。单项结论及数值由各自最终 evidence/report 拥有；Module 的稳定 Interface 由架构文档说明：

- [Whole sample / 两阶段机制](architecture/full-pool-two-stage-realization.md)
- [十采集话题合并网络与独立离线重放合同](architecture/ten-topic-full-pool-replay.md)（十话题当前方法；历史来源与结果保留）
- [十话题 Report / v17 Release 合同](architecture/ten-topic-report-release.md)
- [Prompt–Model / v15 Report、Release 合同](architecture/revised-four-model-release.md)
- [Parameter / Study、Evidence、Report](architecture/gpt-p0-parameter-study.md)
- [Deployment / 原子发布与回退](architecture/report-deployment.md)

Report Module 拥有研究呈现及表图同源知识；Release Module 拥有证据接纳、旧文件保留和 immutable inventory；Deployment Module 只消费验证后的发布事实。这个 Seam 保持 Locality，避免把研究判断规则复制到 shell 或网页拼接器而形成 Information Leakage；不为导航增加透传 Module 或通用框架，Depth 来自既有 Interface 对证据与产物的完整验证。

**当前合同：** v17 精确绑定已验收十话题四研究、工作簿及完整不可变库存，不改写旧来源 eligibility。公网来源/下载一致性和回滚证据见 [Operational #264](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/264)。

**历史发布合同：** v15 仍只接纳四模型闭合 projection；v16 以独立接纳合同追加这两项已完成研究。指标研究的 [evidence](../runs/gpt-p0-index-sensitivity-20260920-formal-01/evidence.json) 与 [曝光判断闭合](../runs/gpt-p0-index-sensitivity-20260920-formal-01/exposure-bank-closure.json) 明确 `production_deploy_eligible=false`：17,316 个 eligible inputs 中 17,315 个有判断，另 1 个 unknown 保留且已证明不会曝光，700 条路径所需曝光完整。这不等同完整判断库。经用户批准，v16 对明确绑定的最终证据与发布产物完成接纳验证；原字段、run 与账本不变。发布沿既有 Release / Deployment 事务完成，原 v15 保留为回退版本。验收记录见 [Operational #263](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/263)。

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
- [current ten-topic release：四研究 v17 发布记录](references/ten-topic-v17-canonical-release-20261007.md)
- [protected composite release：两项敏感性研究追加 v16 发布记录](references/sensitivity-v16-canonical-release-20260920.md)
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
