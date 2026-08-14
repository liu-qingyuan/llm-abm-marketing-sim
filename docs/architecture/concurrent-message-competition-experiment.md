# Concurrent Message Competition Experiment

Status: Implemented and published architecture note
Current release evidence: [`../references/jinjiang-concurrent-message-editorial-v3-formal-release-20260807.md`](../references/jinjiang-concurrent-message-editorial-v3-formal-release-20260807.md)
Canonical endpoint: [`https://abm.q1ngyuan.top/`](https://abm.q1ngyuan.top/)

本文是当前三 message runtime、报告和发布边界的唯一 Architecture Note。它不替代 GitHub `Spec:` issue 的 executable requirements，也不授权新的 Formal Run、Provider 或 deployment。

## 当前实验合同

- 三条 Experimental Message Videos 从同一 Batch 0 发布边界开始，各自维护 `user × message` eligible queue。
- 每条 message 使用 Per-Message Personalized Top20，30 个 batch、每条 600 次 exposure；同一 pair 最多 exposure，同一 user 可以跨 message 重叠。
- Batch 0 使用共同的 Full-Pool Influence Seed Union；之后每条队列独立排序，完全同分按 `user_id` 稳定处理。
- Platform Environment 选择 exposure；Decision Adapter 只处理已曝光的 pair，并生成 Primary 与 report-only Demographic Shadow Decision。
- 成功 Primary 的 `like/comment/share` 用户按 campaign 去重，只影响下一批 ranking；`ignore`、`provider_failed` 和 Shadow 不传播。
- `Message-User Fit` 使用 message 六维 `0/1` vector 与用户 signed value weights 的 cosine similarity，并映射到 `[0, 1]`；Class 名称不是硬性 routing 条件。

当前首次 release 的固定研究边界为 1,000 sample users、3,000 eligible pairs、1,800 exposures 和 3,600 个 Primary/Shadow decision opportunities。结果是 descriptive simulation evidence，不构成真实世界文案的因果胜负或总体代表性结论。

## Ranking 与生命周期

每条 message 的候选排序使用完整精度的 Personalized Delivery Score：

```text
personalized_delivery_score
= 0.50 * base_network_relevance
+ 0.30 * campaign_engaged_neighbor_signal
+ 0.20 * normalized_message_user_fit
```

`base_network_relevance` 来自 holdout-safe Historical Set 评论图；`campaign_engaged_neighbor_signal` 在 Batch 0 为 0，只接收前一批成功 Primary 的 campaign-level 去重用户；`normalized_message_user_fit` 将 message 六维 value vector 与用户 signed value weights 的 cosine similarity 从 `[-1, 1]` 映射到 `[0, 1]`。每批三条队列先冻结 ranking/context，再分别选择最多 20 个 pairs；同批 Primary 全部闭合后，反馈才进入下一批，不能改变同批 Decision。

平台不会在曝光前为候选调用 LLM。每个实际 pair 只在 exposure 后形成 Primary 和配对 Shadow；pair 一旦曝光就从该 message queue 移除，但同一 user 仍可进入其他 message queue。

三条 message 的定义由 `src/llm_abm_sim/concurrent_message_experiment.py` 中的 `authoritative_message_definitions()` 提供；每个 run 把这组定义持久化为 `message_snapshot.json`，报告 rebuild 和 execution replay 都以该 snapshot 作为 message source of truth。Markdown 不再复制 message 文案或另建 alias；latent attributes 的研究先验由 [`../references/jinjiang-user-latent-attributes-reference-zh.md`](../references/jinjiang-user-latent-attributes-reference-zh.md) 持有。

## Module ownership

| Module / artifact | 当前职责 |
|---|---|
| 私有 `_ConcurrentRuntimeKernel` | ranking plan、batch-start feedback snapshot、message-local single exposure、terminal closure、campaign 去重、next-batch commit 和 validated replay；只持有当前 batch 的完整 row objects |
| 私有 `_ConcurrentRuntimeBatchSpool` | 以 run/batch/snapshot identity 与 SHA-256 关闭 append-only regular-file chunks，拒绝缺失、额外、crossed、损坏、symlink 和 path escape，并按 canonical batch order 重放 |
| `ConcurrentMessageExperimentRunner` | 保持公开 Primary+Shadow preflight，执行 paired Decisions，并从私有 spool reader 投影既有 candidate/pair rows 和最终 source |
| 私有 `_PrimaryOnlyConcurrentRuntimeConsumer` | 只执行 Primary；现有调用仍从同一私有 spool reader 组装兼容结果，Full-Pool 调用则把已关闭 spool 交给流式 source closure；不建立 Shadow 或公共 storage Seam |
| package-internal `FullPoolFormalExperiment.run(...)` | 以 frozen contract、一个 Primary Adapter 和显式 output identity 驱动完整 eligible pool；当前只接受 deterministic Validation profile，并原子关闭独立、不可部署的 source |
| `PlatformEnvironment` / ranking | 每条 message 的 candidates、delivery capacity、Top20 或 Full-Pool scaled capacity、exposure gate 和稳定 tie-break |
| Decision Adapter | 对已曝光 `user × message` pair 生成 Primary/Shadow typed decisions；不选择 exposure |
| `ConcurrentCampaignDiagnostics` | 从 persisted candidate/pair rows 重建 funnel、allocation、response、feedback 和 sensitivity diagnostics |
| `ConcurrentRobustnessStudy` | 通过唯一公开 `run(...)` Interface 验证显式 hashed source，生成 19-point Ranking Weight workspace；在 exact 16-cell Adapter map 与 execution contract 通过全量 preflight 后运行或恢复独立 Primary-only cells，关闭 immutable study root，并调用 Report package-internal Interface 生成独立 candidate |
| Mechanism Presentation Module | package-internal、review-gated 的单一 Interface，确定性拥有下一代六张 Mermaid Semantic Masters、三层 ownership、双语 DOM/fallback projections 与 image briefs；批准和 additive release 完成前不接入当前 Report/Editorial Adapters，也不改变 v1/v6 presentation |
| Report Module | package-internal compose/materialize/validate Interface，统一拥有双 lineage closure、renderer、payload/HTML composition、Prompt disclosure、deterministic semantic SVG、stage formatting、DOM/selector/href、destination safety 与 presentation validation；不从 package root 公开；additive robustness composition 将唯一 1,800-row trace script 关闭为 deterministic gzip envelope，并由 browser bridge 在平台解压完成前保持 trace controls disabled |
| Editorial candidate | bilingual presentation grouping、五个 mechanism media derivatives、run evidence surface、异步 loading/ready/error trace state 和 canonical report bytes |
| Release Module / deploy | 独占 Formal eligibility、双 lineage、artifact inventory、approved downloads、release metadata、production identity 与 hash closure；只把已批准 stage facts 交给 Report Interface，并继续负责显式 contract、candidate health、atomic `current` 和公网验收 |

Diagnostics 的 source of truth 是同一 run 的 persisted candidate rows 与 pair rows。运行中只有当前 batch rows 驻留；batch commit 先写入带 identity/hash 的 hidden prepared file，再由 journal 记录对应 chunk reference，随后原子发布 chunk 并释放当前 batch row ownership；任一 commit window 中断都按同一 identity/hash 零调用续提。finalization 通过只读 canonical reader 投影原有 persisted rows；private spool 不是 Report、Release 或 Deployment 的新 Interface，也不构成可发布的第二份事实来源。report writer 和 release validator 仍会重新 rebuild 并比较 diagnostics、summary、schema tokens、manifest 与 approved artifact set。

## Full-Pool deterministic Validation 纵向切片

`FullPoolFormalExperiment.run(contract, adapter, output_dir)` 是 Full-Pool Module 当前唯一 package-internal 主测试 Seam；它没有从 package root 导出，也没有新增 planner、writer、reader、resume 或 Shadow Interface。Frozen contract 同时关闭 complete eligible user-set hash、三条 authoritative message hash、30-batch production shape、scaled Validation shape、Primary-only terminal 和 output identity。Production shape 静态固定 `36,400 users / 109,200 pairs / 30 batches / capacity 1,214 / final 1,194 / 1,691,730 candidates`，但当前 lifecycle 明确拒绝执行 production profile，不能把 Validation source 当成 Formal evidence。

Validation membership 直接包含 `users.csv` 的完整 eligible set，并单独标记 `full_pool_no_membership_filter_v1`；Primary Video Source Scope 只保留 lineage 观察，不执行 Seed-First quota membership filtering。Batch 0 对三条 message 先加入同一 Full-Pool Influence Seed Union，再由各 message ranking 独立补足；之后前 `N-1` 批各取 capacity，最后一批取自然余数。每个 pair 只曝光一次，完整 closure 要求每位用户的 Campaign Exposure Coverage 为 3。

运行继续复用私有 Primary-only kernel、journal 与 batch spool。Full-Pool source closure 不 materialize run-wide rows，而是按 batch 读取已提交 spool，确定性生成独立 schema、batch chunks、candidate/pair/terminal JSONL、aggregates、diagnostics 和完整 hash inventory；所有 persisted rows 再从 staging source 重放验收后才原子 rename。失败可以保留不可部署 operational evidence，但 final destination 必须不存在。Validation Adapter 的 external Provider calls 固定为 `0`，manifest 始终记录 `live_api_triggered=false` 与 `production_deploy_eligible=false`；本纵向切片不生成 Report candidate、release 或 canonical deployment。

## Robustness workspace 与分析闭包

`ConcurrentRobustnessStudy.run(manifest, adapters_by_cell, output_dir)` 是 additive robustness Module 的唯一公开执行 Interface。Manifest 固定显式 Concurrent source 及完整 artifact hashes、Research Sample 与三条 message identity、P95/component/tie-break/schedule tokens、19 个 simplex weight points、16 个 Prompt–Model cells、request caps、practical thresholds、authorization reference 和 output identity；进入 cell closure 时，16 cells 还必须全部绑定 Manifest 声明的 required observed-model identity。

首次 `adapters_by_cell=None` 调用先通过现有 Concurrent artifact closure 验证 source，再只使用 frozen candidate 与 batch feedback evidence 重算每条 message、每批次的 Top K ranking；eligible set、feedback signal 和传播状态保持冻结。输出包含 Jaccard distance、rank delta、entered/exited users、first divergence 与 message-level mean/AUC，不调用 Provider、不打开 processed dataset，也不改写 source。结果状态为 `ready_for_human`，只形成 manifest、weight evidence、validation 和 hash registry 四个文件组成的 private resumable workspace。

提供 Adapter map 时，Manifest 还必须冻结 dynamic execution profile、authorization artifact、四个 requested/required-observed model qualification artifacts、observed-model policy、pricing snapshot、input/output token ceilings、stopping rule 与 logical/physical/fee caps。Map 必须恰好覆盖 canonical order 的 `4 Prompt × 4 model`；每个 cell 使用独立、无 cache 的 fresh Adapter。deterministic validation profile 只接受显式 injected mock client，要求 `external_request_invocations=0`，不能充当 live authorization；Formal profile 则要求独立 live authorization 和 provider-observed qualification。Formal 可以使用原 live SDK client，或显式 `openai-codex-subscription-client-v1`：后者仅通过本机 Pi runtime 读取 OAuth，不把 credential、raw Prompt 或 raw response 写入 artifact，并把 dated requested IDs 与 provider-observed alias 分开记录。所有 cell 的 key、Prompt hash、provider/wire/model/reasoning/timeout/retry/store identity 会在首次 `decide()` 前一次性预检。

每个 cell 在独立 sibling operational scope 中复用私有 Primary-only kernel，从同一 dataset/sample/graph/messages/seeds 与 baseline ranking policy 启动。Journal identity 绑定 Manifest、source、sample、message、cell、request、authorization、pricing 和 store policy；append-only journal 保存 batch-start snapshot、Primary terminal 与 commit barrier。运行会在每个 logical judgment 前保守预留最多 `max_retries + 1` 个 physical attempts 与 token-ceiling cost，若下一次可能越过 logical、physical 或 fee cap，则返回 `resumable` 且不调用 Adapter。彼此独立的 Formal cells 可以由固定 commit 的 bounded workers 并行写入各自最终 journal scope，但不得共享或改写 root status；唯一主 `ConcurrentRobustnessStudy.run(...)` 必须随后逐 cell replay、汇总全局 caps，并关闭 immutable root。完成 cell 可直接 replay，不重放 terminal；crossed identity、活动 journal lock、损坏 journal、变更 completed cell 或 observed-model drift 均失败关闭。

通过验证后，同一个 `run(...)` resume path 私下计算 Batch 0 shared-seed strict paired `engage` panel、secondary action/probability/confidence/disagreement、逐 message 双 engagement-rate 分母、Provider failures、audience overlap/first divergence 和 campaign-deduplicated positive-user growth。Prompt、model、message 都按 fixed categorical factors 汇总；planned model contrasts、Prompt × model interaction 和 user-blocked deterministic bootstrap 只条件于 fixed sample、fixed graph 和 one realized path。阈值以下只标为 `small_observed_difference`，claim audit 不允许越界研究结论。

16 cells 全部闭合后，producer 才把完整 cell evidence 与 registry 加入 private workspace；缺失 terminal 永远不会伪装成 `ignore` 或 partial final artifact。分析 artifacts、cell evidence、validation、claim audit、Manifest 和全量 artifact hashes 通过 sibling staging 原子关闭为 immutable study root。动态调用随后自动使用显式 destination（未提供时使用该 output identity 的 deterministic sibling candidate）调用 Report package-internal Interface：Interface 重新执行未修改的 Concurrent source closure，独立验证 study root 的 schema、manifest、row counts、source links 和 hashes，再从两条只读 lineage 生成 companion JSON/CSV、增量页面和 `production_deploy_eligible=false` release evidence。candidate 保留原页面的 mechanism、Run Evidence、field lineage、Demographic Shadow 与 Primary + Shadow barrier，并把旧 Shadow 明确标为历史 Formal evidence；新增 Weight small multiples 和每个 model 最多四条 Prompt series，不改变历史 renderer 或 single-root rebuild。重复 dynamic resume 会验证而不重写既有 root/candidate。

Prompt disclosure 由 Report Module 在 candidate composition 时从已验证 `PromptContractRegistry` 与 Manifest cell identity 投影：registry 从受控 template 结构判定 baseline、wording-only、information-order-only 与 structured-rubric-only，Manifest 关闭每个 variant 的 stable token、canonical hash 和四 model cell coverage。页面只本地化这些已验证语义，展示共同 allowlist、task/action semantics 与 structured output contract，不持久化新的 Prompt schema，也不展示 rendered Prompt 或 Provider payload。`4 × 4 = 16` 是 execution-cell denominator；三条 message 只把它展开为 48 个 reporting slices。Batch 0 direct panel、每 cell 一条 30-batch realized path、Primary-only factorial 与 Historical Demographic Shadow 使用独立 scope 文案。

同一 projection 生成三张 reader diagram：项目证据链、真实批次机制与 Prompt-Model factorial。主图使用读者领域名称并合并只服务实现说明的中间节点；完整 provenance、condition、timing 与 effect 保留在键盘可访问的 Mermaid disclosure。每张图的同一 node/edge source 同时生成 deterministic inline SVG、bilingual embedded semantic master 和一个独立 `.mmd` approved download；contract-critical relation 使用稳定 semantic ID。真实批次图仍把三条独立 Per-Message Top20、cross-message overlap、single exposure、Batch 0 per-message fill、Historical Primary + Shadow / Robustness Primary-only required terminals、full-batch barrier、positive succeeded Primary feedback、campaign `user_id` 去重和 next-batch context-only 作为可查询关系；Shadow、ignore、provider failure 没有进入 campaign set 的 feedback edge。浏览器只加载 inline SVG、title、description 与 text fallback；不运行 Mermaid、不请求 CDN。Prompt 共同合同默认展开，P0-P3 的 stable token/hash 收进各自 native disclosure；Prompt chart 的每条 mark 和 legend 仍引用对应 disclosure row。language switch 不改变 source token、hash、diagram identity 或数据 series。历史 v1-v3 raster 在 current Robustness presentation 中仅作为 `aria-hidden` compatibility decoration 保留，不再承载 contract-critical 关系。

## Prompt–Model request contract

Robustness 请求侧是 additive Module，不改变现有 Concurrent Formal runtime：

- `PromptContractRegistry` 持有 `P0`–`P3` 的稳定 token、pinned canonical hash、LLM-visible field allowlist、排除字段、任务/动作语义、structured Decision schema、等价性清单与基于 template 结构验证的 controlled-change identity；模板字段增加、遗漏、跨维度变化或同 token 漂移会在使用前失败。
- `P0` 复用当前 Primary Prompt bytes；`P1` 只改词汇，`P2` 只重排同一信息，`P3` 只增加不输出 chain-of-thought 的结构化 rubric。四者继续只返回 `engage/probability/reason/confidence/action`。
- `provider-request-contract-v1` 把 Prompt hash、requested model、Responses wire、显式 `reasoning_effort=low`、output-token ceiling、structured schema hash、timeout/retry 和 sampling 参数省略固定在同一请求合同；response accounting 仍独立记录 observed model 与 usage。若 subscription transport 不接受 wire-level `max_output_tokens`，合同仍冻结 256-token ceiling，并在 transport 返回后、Decision 进入 runtime 前按 complete usage fail closed。
- 未配置 request settings 的历史 Adapter 保持原调用形状和 safe metadata。P1–P3 或显式 Robustness request 合同不完整时在 Provider 调用前 fail closed。

该请求 Module 现在由 16-cell producer 通过 injected Adapter 接缝复用，但不自行发现 credential、选择 Provider/model、扫描 latest source 或构造 live fallback。自动化 acceptance 只运行 deterministic validation profile；它不执行模型 qualification、真实 28,800-judgment matrix、Provider network call、Formal Run、canonical deployment 或 release gate 绕过。

## Report 与 durable execution

`rebuild_concurrent_message_report(run_dir, *, destination_dir=None)` 是报告 Module 的公开重建 Interface：

- in-place rebuild 先完成 typed artifact closure，再按 persisted source report hash 选择历史兼容 bytes；只替换 source 的 `report.html`，不重写 payload、runtime、diagnostics、downloads 或 manifest。
- explicit destination 在 source closure 完成后创建唯一 sibling staging，复制 canonical persisted views，用 Editorial default 生成 presentation，再重建 manifest 并 atomic rename。
- `explicit presentation destination 始终使用 Editorial default`；`in-place rebuild 仍按 persisted source report hash 选择历史兼容 bytes`。
- destination 必须原先不存在、与 source 不重叠、无 symlink/path escape 且同一 filesystem；失败时清理 staging，并保持 source 与 destination 不变。

运行状态分为四个 ownership 边界：

1. **private operational workspace**：identity、append-only journal、snapshot、lock 和 validated replay；永远不可 deploy。
2. **publish staging directory**：同一 run 的未公开 artifact set；不能跳过 closure 或 release contract。
3. **final source directory**：显式 runner output，包含 runtime rows、diagnostics、report、downloads 和 manifest；只有通过显式 Formal contract 才能进入 candidate deploy。
4. **canonical release**：使用明确 contract、source directory 和 release id 完成 candidate、health、atomic `current`、public acceptance 和失败回退。

Robustness production promotion 使用版本化 `abm-report-release-contract-v5/v6/v7`。它先重建并验证历史 Formal source、immutable study root、private workspace journals、28,800 logical judgments、provider-observed model aliases、qualification/authorization/pricing 与 `production_deploy_eligible=false` validation candidate；Release Module 再把已批准 stage facts 交给 Report Interface，由 Report materialize/validate production presentation，Release 随后在新目录中保留原 candidate manifest/evidence bytes并关闭 inventory、production identity 与 hashes。promotion 不调用 Provider，不能原地翻转 candidate，也不能接受 fixture、partial root、crossed hash、invalid presentation bundle 或超出 86,400 physical-attempt cap 的证据。部署必须显式传入 contract、source directory 和 release id；standalone validator 从同一只读 physical snapshot 产出 deployment facts，远端在 atomic `current` 前核对完整 inventory 与 report/manifest/release identity，切换后再完成逐 artifact 公网 hash、Robustness markers、旧 Shadow/barrier lineage、semantic v7 双语机制与 responsive Playwright 验收。

普通 run 与 `contract-protected` Formal/release run 都遵守同一重建语义：前者可以删除后重建，后者仍必须按显式 contract 保留和验证；`contract-protected` Formal/release roots 不能仅按目录类型推断删除。workspace 或 staging 的存在不能替代 journal replay、source closure、release validation 或 deployment authorization。

私有 runtime kernel 对 paired 与 Primary-only 使用显式 terminal contract：既有 paired journal 仍要求同一 `user × message` 的 Primary、Shadow 都 terminal 后才关闭；Primary-only workspace 只记录 Primary，但必须等同批三条 message 的全部已选 pairs terminal 后才能 commit。已提交 batch 从 spool chunk 恢复 exposure indexes、campaign feedback、schedule cursor 与 step aggregate；journal replay 仍验证完整 checksum/event chain，但 runtime path 只保留 commit references 和尚未提交的 active batch records。Robustness operational root 额外持有 execution identity 与 cap status，每个 cell journal 仍由 kernel 拥有；两者都从已验证 journal 与 spool 恢复，workspace identity、batch snapshot、chunk inventory、completed cell 或 terminal evidence 不一致时失败，不猜测缺失状态。Formal live cell 若在一次 external attempt 中断且 physical count 尚需 reconciliation，只返回 private resumable evidence，不自动重放未知请求。

## LLM visibility 与 evidence

Primary 只读取当前 message 原文、allowlisted observed profile 和 synthetic experiment fields：`activity_score`、`global_influence_score`、`local_influence_score`、environmental coefficient、六维 value weights、hotel class 和 travel purpose。Primary 不读取 `latent_class`、demographic labels、Ranking evidence、其他 messages、peer behavior、raw prompt 或 raw provider payload。

Primary 与 Shadow 的 PeerContext 保持中性；campaign ranking signal 只改变下一批投放顺序，不重新解释为用户实际看见的同伴行为。Shadow 只增加四个 report-only demographic labels，用于 paired sensitivity，不写入 action、ranking、feedback 或 runtime state。

报告必须分别展示 campaign funnel、message allocation、Primary response、campaign feedback effect 和 demographic sensitivity，并给出明确 numerator/denominator。受众 overlap 和 action rate 只能作 descriptive comparison，不生成 winner 或综合分数。

Canonical report 的 source/hash、model、budget、release id、rollback 和公网验收以 Original Formal、Two-mode rollback、Editorial rollback 和 current Editorial Formal evidence 为准。代码、Validation/mock/rule-based artifact、`ready-for-agent` 状态和 issue 本身都不表示 production authorization。
