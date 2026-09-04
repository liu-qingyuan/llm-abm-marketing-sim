# Prompt–Model Realized Table-First Report

本模块把已闭合的 Full-Pool、Historical 与五模型 Prompt–Model v2 证据组合成教师可直接查看的双语候选报告。它只做确定性 projection 与 presentation，不运行 Provider，也不触发 release 或 deployment。

## Interface 与输入边界

公开入口位于 `_REPORT_PRESENTATION`：

- `compose_v2_realized_candidate(...)`：消费显式 source roots、Full-Pool manifest hash 与全新 destination，原子生成候选目录；
- `validate_v2_realized_candidate(...)`：重新读取相同 source roots，独立重建 projection、CSV、XLSX、HTML 与 manifest 后逐字节验证候选。

输入必须同时闭合：

1. Formal Full-Pool two-stage Realized source；
2. Historical 16-cell Formal run 与 closed study；
3. Historical presentation candidate；
4. 五模型、20-cell、two-stage v2 closed study。

Report Interface 会在组合前后重算输入目录 hashes。destination 不能与任何输入、workspace 或 frozen source 重叠；symlink、partial root、Validation/fixture 假冒 Formal source、缺失 artifact 或 hash 漂移均 fail closed。

## 单一 validated projection

`concurrent_robustness_v2_report.py` 先构建一个 package-private validated projection，再由该 projection 同时生成 JSON、CSV、XLSX 与 HTML。各展示格式不得自行重算指标。

projection 固定区分两类事实：

- **Realized Main**：ABM 实际产生的 `like/comment/share`、互动数、曝光数与互动率；
- **Judgment Audit**：Provider 返回的 action、概率、置信度、失败、attempt、usage、requested/observed model identity、route 与计费语义。

Realized Main 的稳定分组顺序是 `Model → Prompt(P0–P3) → Segment(S1–S3) → Message(M1–M3)`。Provider reason 只属于 Judgment；模块不生成 `realized_reason`，也不宣称 winner、准确性、校准、因果或外部有效性。

## Workbook contract

`robustness_v2_teacher_results.xlsx` 由固定版本范围内的 XlsxWriter 生成，并由 openpyxl 独立重读。ZIP timestamps、document properties、sheet 顺序、headers、typed cells、freeze panes 与 autofilters 都属于确定性 contract。

固定六张 sheet：

1. `README & Lineage`
2. `Realized Main`
3. `Judgment Audit`
4. `Prompt Catalog`
5. `Provider Audit`
6. `Cell-Batch Evidence`

重复 build 必须逐字节一致；validator 不接受 Excel 可打开但 cells、类型、顺序或 metadata 已漂移的文件。

## Prompt、Provider 与隐私边界

Prompt Catalog 展示四个静态 client-submitted system/user templates、P0–P3 唯一受控差异、版本/hash、Decision JSON schema、request settings 与三条 authoritative messages。它不保存逐用户 rendered Prompt，也不提供 raw Prompt/response 下载。

Provider Audit 必须把 Provider Module 拥有的 `planned_*` condition 与 closed Judgment evidence 重算出的 observed route/billing counters 分列展示；`deterministic_validation` 只能标为未执行 planned Formal condition。若 manifest 声明 `formal`，observed route、billing 与 required identity 必须和 planned condition 完全一致，否则 Report closure 失败。

Gemini 行必须同时披露 Antigravity OpenAI-compatible gateway、observed identity 与限制：该路径不是 direct Gemini Developer API，gateway 可能注入 client 不可观测上下文，因此 client-submitted Prompt 不能被描述为完整 effective Prompt。

## Candidate 与部署边界

候选目录使用 `concurrent-robustness-v2-report-candidate-manifest-v1` 闭合完整 inventory、hashes、sizes、downloads 与 source lineage。HTML 下载集合必须与 manifest 的 `approved_downloads` 完全相等。

该接口始终固定：

```text
provider_calls_during_composition = 0
canonical_deployment_triggered = false
production_deploy_eligible = false
```

因此它是独立、可审阅、可复现的 candidate，不是 canonical release。

## v14 immutable Release 边界

唯一 Release Interface 对 `abm-report-release-contract-v14` 使用独立 exact-field dispatch。调用方必须显式提供 Formal Full-Pool two-stage source、Historical Formal、Historical 16-cell study、Historical candidate、新 v2 Formal study、教师 candidate、protected v13 release/contract、release ID、implementation commit 与全新 destination；不能传入网页指标或 caller 汇总代替持久化证据。

Release Module 会重新读取并闭合全部 schema、identity、classification、count、hash 与 physical inventory。protected v13 不接受调用方任选的同 schema release，而是固定到[当前 canonical v13 发布记录](../references/full-pool-two-stage-v13-canonical-release-20260827.md)中的 release、contract、report、manifest 与 physical snapshot identity。新 v2 evidence 只有同时满足 20 cells、每 cell 1,800 judgments、36,000 个成功 logical judgments、完整 usage、exact requested/observed identity、合法 embedded Formal authorization lineage、无 terminal Provider failure且所有 pair settled，才可提升；Release facts 还显式保存 `concurrent-robustness-formal-topology-v2`、`model-major-serial-one-model-per-invocation-v1`、五模型顺序与 P0–P3 顺序。Validation、mock、rule-based、manual zero-provider Formal shape、partial、stopped 与 reconciliation-required evidence 均不能进入 v14。

Report Module 不决定 release eligibility。Release 仅向 `_REPORT_PRESENTATION.materialize_v2_realized_production(...)` 传递 release/source/study/candidate identity 组成的 typed stage facts；Report 从已关闭输入重新生成 production HTML，原 candidate bytes 和其中的 `production_deploy_eligible=false` 保持不变。v14 release 另行保存 candidate manifest、production evidence、release manifest、workbook、Prompt/provider accounting、mechanism 与 approved-download hashes，并以 staging、完整 inventory validation、原子安装和 standalone round-trip 关闭。

v14 purpose 固定为 `full_pool_two_stage_prompt_model_realized_robustness_formal_research`，sampling status 固定为 `persisted_full_pool_two_stage_and_prompt_model_realized_formal_runs`，readiness schema 固定为 `full-pool-v14-release-readiness-v1`。本地 immutable release 仍固定：

```text
operational_authorization_required = true
deployment_authorized = false
canonical_deployment_triggered = false
public_acceptance_recorded = false
```

Release 不连接 Provider、SSH 或公网，也不切换 canonical endpoint；v14 operational authorization、rollback execution 与 public acceptance 属于独立 Deployment contract。
