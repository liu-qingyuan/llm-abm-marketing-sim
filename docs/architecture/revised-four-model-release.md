# Revised Four-Model Recovery Research（v15）

来源规格：[Issue #250](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/250)。v15 是独立修订范围，不修改旧五模型 v2/v14 的完成条件，也不改变原始交付的 `production_deploy_eligible=false`。

## Module 与接口

- `concurrent_robustness_revised.close_revised_evidence`：显式 Evidence SHA → 原 plan → control/bundle；重放不可变 ledger，逐条重建 judgment、realization、barrier、settled attempt 和 archived unknown。返回不含 Provider 执行权的闭合 projection。
- `analyze_revised_evidence`：16 cells、28,800 exposures、480 barriers；仅预声明 Batch 0 的 20 seeds × 3 messages 进入直接配对。使用既有用户块 bootstrap（500 次、seed 20260809）及直接 0.05 / realized 0.02 的分离阈值。自适应路径、等权主效应和差中差交互只作描述。
- Report Module 的 `render_revised_research`：同源 JSON/CSV、P0–P3 曲线、消息/模型/指标切换；在受保护研究网页内新增独立小节，不替换 Full-Pool、Historical、Primary/Shadow、排序权重或旧 GPT 析因。
- Release Module 的 `promote_revised_research_release`：绑定精确受保护 v13 contract/hash 和真实四模型 projection；复制原发布目录、保留旧下载 bytes，仅生成新 report/manifest 和新增下载；输出不可变 release 及 sibling v15 contract。
- `validate_revised_research_release`：从原 bundle 独立重建所有新产物，再验证完整 physical inventory；不能仅翻转 eligibility、传入假 fixture 或复用独立统计 HTML。
- Deployment Module 只消费 Release 的 v15 readiness/source identity，不理解或重算研究指标。新增 v15 operational authorization/operation schema；沿既有 host/root/container 和原子 current 事务执行，不改变部署拓扑。

## 发布与回退

必须显式传入 repository、verified source、Evidence SHA、protected v13 contract、destination、release id、40 位 implementation commit。输出不能存在或与输入重叠。原交付 bytes/mode 不变。

```python
from llm_abm_sim.concurrent_robustness_release import promote_revised_research_release
contract_path = promote_revised_research_release(
    repo_root=REPO, verified_source=VERIFIED_SOURCE,
    evidence_sha256=EVIDENCE_SHA256,
    protected_v13_contract=PROTECTED_CONTRACT,
    destination_dir=RELEASE_DIRECTORY, release_id=RELEASE_ID,
    implementation_commit=IMPLEMENTATION_COMMIT,
)
```

正式脚本继续执行 local preflight/snapshot、用户授权与 fresh rollback identity 绑定、候选 inventory/health、锁内 current 再核对和原子切换、公网 body hashes/下载/Playwright、锁内最终 readback。失败时保留原事务的原子回退并校验恢复后的 disk/container/public identity；成功后独立记录 operation facts，不改 immutable release。

## 必须保留的研究边界

同一个 1,000-user source 与 36,400-user Full-Pool 分离；新两阶段 realization 与旧 direct-action GPT run 不按名称合并。Kimi 33 条订阅 k3-256k + 7,167 条官方 kimi-k3；Gemini gateway observed identity 和不可观测 effective context 单独披露。108 已知失败、5 archived unknown、全历史 token null 均保留。取消 Gemini 3.8 Flash High 为零调用；四模型范围完成不等于原五模型 36,000/20/600 完成。重算、报告、发布全部新增 Provider calls=0。

## 两项敏感性研究追加发布（v16）

v15 合同保持不变。`sensitivity_release` 只接纳本次已完成 Parameter 与 Activity / Local Influence 的明确最终 manifest/audit hash，并保护现有 v15 的完整 inventory；它不是任意报告的通用 promotion 入口。原独立证据 `production_deploy_eligible=false` 与生成时未部署记录保留，新 v16 合同表达经独立接纳的复合发布资格。

- **Report Module**：`render_sensitivity_research` 添加研究导航与两个独立阅读章节；通过同源 iframe 复用完整原报告，可直接打开。结果、曲线和相对下载保持原 bytes，不另造统计 renderer。
- **Release Module**：`promote_sensitivity_release` 接受显式 protected v15 contract、Parameter manifest、指标 completion audit、destination、release ID 和 implementation commit。核验全部受保护文件、两项研究产物、路径矩阵、整数动作、100-seed 均值与基线复现；生成只读 release 和 sibling v16 contract。`validate_sensitivity_release` 独立重建发布产物并比较完整 inventory，可验证 deployment snapshot。
- **Deployment Module**：消费 v16 readiness，复用同一 authorization、fresh rollback、candidate health、原子 current、公网 body/hash 与 browser gate；不接收研究参数或重算统计。

这个 Seam 集中呈现与接纳知识，增加 Depth 而不增加透传层；独立报告仍拥有自己的数值、表格与图形，避免 Information Leakage。v16 是对固定已审计证据的 accession，不重跑路径，也不把 hash 校验表述为重新执行完整算法审计。指标 unknown 的原不曝光证明及实际曝光覆盖事实保留；不声称完整 eligible 判断库或纯指标因果效应。

本轮实施与验收记录见 [Operational #263](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/263)；实际上线状态由 [统一研究入口](../index.md) 维护。
