# Full-Pool Two-Stage Engagement Realization

本文描述 Full-Pool 两阶段 replay、realized presentation 与 Release v13。它在已关闭的 Strict Source-v4 Provider Judgment 与 ABM feedback commit 之间加入 `Engagement Realization Module`，但不修改旧 Source-v4、`EngageDecision`、v12 release 或 canonical endpoint。既有validation入口继续只生成nonproduction、nondeployable输出；独立formal closure只消费persisted consumer重新证明的production Source-v4。任何本地source、candidate或release都不自行授权Provider、部署或canonical cutover。

## Module 与 Interface

`EngagementRealizationPolicy` 是 judgment-to-commit 规则的唯一 Module。其 Interface 只接收一个已验证的 `EngageDecision` 以及 Source-v4 identity、`user_id`、`message_id`、冻结 seed 和规则版本，返回：

- `provider_ignore`：Provider 为 `engage=false, action=ignore`；不生成 draw，结果保持 `false / ignore`；
- `draw_pass`：Provider 为正向 action，稳定 draw 小于 `provider_probability`；保留原 `like/comment/share`；
- `draw_fail`：Provider 为正向 action，稳定 draw 大于或等于 probability；结果变为 `false / ignore`。

规则版本固定为 `sha256-source-user-message-first-53-bits-uniform-v1`，seed 固定为 `20260823`。`realization_key` 对 UTF-8 `source_identity NUL user_id NUL message_id` 取 SHA-256；draw 对十进制 seed、NUL 和 key hex 取 SHA-256，再把前 53 bits 映射到 `[0, 1)`。key 不含 upstream/replay batch、time step、遍历顺序或 completion order。

`FullPoolTwoStageReplay.run_and_close(request)` 是调用方使用的高层 Interface。request 精确绑定：

- explicit Source-v4 root；
- manifest SHA-256；
- Source-v4 identity；
- 独立且尚不存在的 output directory；
- 冻结 realization seed 与规则版本。

Replay 内部重新调用 Source-v4 persisted consumer、验证 dataset fingerprints、重建 Full-Pool ranking inputs、按 `(source_identity, user_id, message_id, primary)` 唯一解析 Provider Judgment，并从 Batch 0 运行既有 Per-Message Ranking。调用方不协调 draw、candidate ranking、barrier、feedback 或 source closure，也不能提供 direct Provider-action fallback。

## Judgment 与 realization 边界

`EngageDecision` 继续表示 Provider Judgment。Provider 的 `engage`、`probability`、`action`、`reason`、`confidence` 和 `decision_source` 不被原地重定义。`reason` 只解释互动意向；ABM 只记录规则、draw、status 和 realized outcome，不生成 `realized_reason`。

persisted `full-pool-realized-terminal-v1` row 使用父 Spec 冻结的 24 个字段，字段集合 exact、extra-field fail-closed。JSONL 使用 UTF-8、sorted keys、compact separators、有限数值和每行一个换行。`provider_ignore`、`draw_pass`、`draw_fail` 的 draw/action 不变量由同一 terminal model 复验；realization key 与 source/user/message、draw 与 key/seed 也会重算。

## Batch barrier 与 feedback

Replay 每批先冻结既有 `campaign_engaged_user_ids`，再为三条 message 规划 selected pairs。每个 selected pair 必须先解析唯一 upstream Judgment并形成 realized terminal。只有整批全部完成后，Runtime Kernel 才提交该批 `realized_engage=true` 的 campaign-level 去重 users；Provider ignore、draw fail 和任何缺失、重复、failed 或 crossed Judgment均不能进入 feedback。下一批 ranking 只读取此前已提交的 realized-positive users。

Runtime Kernel 的 legacy Interface 和 direct-action callers不变。Two-stage Replay 只向其私有执行路径注册由 `Engagement Realization Module` 决定的 outcome；persisted realized terminal仍同时保留 Provider Judgment 与 ABM Realization 两层事实。

## Persisted validation source

一次成功 closure 原子写出 `full-pool-two-stage-realized-source-v1`，inventory 固定包含：

- `candidate-rows.jsonl`；
- `pair-rows.jsonl`；
- `realized-terminal-rows.jsonl`；
- `batch-commits.jsonl`；
- `latent-membership.csv`；
- `realized-projection.json` 与 `full-pool-realized-projection.csv`；
- `realization-evidence.json`；
- `schema.json`；
- `manifest.json`。

source、evidence 和 projection 分别使用：

- `full-pool-two-stage-realized-source-v1`；
- `full-pool-two-stage-realization-evidence-v1`；
- `full-pool-two-stage-realized-projection-v1`。

manifest 关闭 users、messages、pairs、exposures、terminals、batch commits、candidate rows、membership、projection rows、action/status counts、row hashes、artifact inventory、upstream identity/hash与 realization policy。projection 继续以 one-based delivery round、Message 和 Segment 输出 Likes、Comments、Shares 与 Exposure；Exposure 包含 realized ignore，Segment 只通过冻结 membership 的 `user_id` join 获得。

## Realized presentation candidate

`Report Presentation Interface` 会先按 manifest schema 分派到 realized persisted reader，再从已复验的 terminal、pair、batch commit 与 projection 重算 headline、总体、Message、Segment、Segment × Message 九格、batch trajectory、realized feedback 和概率口径。调用方仍只提交显式 source path、manifest SHA-256、历史 Formal/study/candidate 与新 destination，不能注入 metric 或 claim。

页面以单次 `user × message` exposure 作为唯一 Primary engagement 单位。`Exposure` 包含 realized ignore，`like + comment + share` 精确等于 realized engagements。raw `provider_probability` mean 与 `sum(provider_engage × provider_probability) / exposures` 分栏展示；后者只表示固定 Judgment 分组下的 effective gate expectation，不解释为 trajectory expectation 或多-seed 区间。

trace partition 同时投影 `provider_judgment` 与 `abm_realization`：Provider reason 明确属于互动意向，realization 只展示 rule、seed、draw、status、engage 与 action。页面不创建新的心理理由。浏览器继续先验证 index，再按 message 与 batch 加载一个分区；加载失败保持可访问的 fail-closed 状态。

`Mechanism Presentation Module` 新增独立的 two-stage Full-Pool master builder。旧 Full-Pool master Interface 与 Historical 1,000-User master bytes保持不变；新 builder以稳定 node/edge IDs拥有 Provider Judgment、ignore/positive gate、stable draw、realized outcome、full-batch barrier、realized feedback、next-batch ranking和realized projection语义。Report只从该语义对象生成 deterministic inline SVG、双语DOM fallback与同字节 `.mmd`，不会成为第二个机制语义所有者。

当前 presentation继承 source的`nonproduction_two_stage_validation`与`production_deploy_eligible=false`分类。它复制同源 realized source/projection、upstream lineage和历史candidate原字节，composition阶段 Provider calls为0，且不触发 canonical、release promotion或secrets访问。

## Evidence 与失败模式

evidence 分开保存 upstream Provider accounting 与 realization accounting。upstream requested/observed model、responses、usage、settled/charged attempts、`validation/formal_live` evidence profile和production eligibility来自Source-v4 persisted consumer；`upstream_live_api_triggered`与`formal_research_evidence`只投影该closed profile，不从realization零调用或caller声明推断。realization固定记录`provider_calls=0`与`live_api_triggered=false`。复合研究不能因为replay零调用而被标成整体zero-Provider Formal。

以下情况在 closed output 发布前失败：

- explicit path、manifest hash、source identity 或 schema 漂移；
- dataset fingerprint、membership 或 Prompt Environmental Consciousness inclusion 漂移；
- Judgment 缺失、重复、provider failure、crossed user/message/pair identity；
- realization key、draw、status、action、reason contract不一致；
- batch commit不满足 full-batch barrier；
- users/pairs/candidates/terminals/projection/action counts不能互相重算；
- extra/missing file、symlink、path escape、artifact hash或canonical JSONL漂移。

Replay 在开始和发布后重复 inventory immutable Source-v4；任何 upstream bytes变化都会失败。Validation source、evidence 和 projection始终声明 `production_deploy_eligible=false`，且不调用真实 Provider、live API、SSH 或 canonical deployment。

## Formal closure 与 Release v13

`FullPoolTwoStageReplay`保留原`run_and_close(request)` validation Interface，并新增语义独立的`run_and_close_formal(request)`。Formal入口没有mode矩阵或caller-supplied claims；它只在Source-v4 persisted facts同时闭合`profile=production`、production topology、formal-live accounting、非零upstream external requests与`production_deploy_eligible=true`时运行。输出继续使用同一realized source/evidence/projection schema，但classification固定为`formal_two_stage_realized`，source identity通过独立closure profile与artifact bytes区分；validation bytes与行为保持不变。

Report Presentation Interface可以从formal realized source生成仍为nondeployable的source-bound candidate，并通过独立production materialization把Release批准的release ID与contract schema投影到deterministic HTML。Report会重新闭合source、Historical Formal/study/candidate、trace、两阶段机制与页面bytes；它不决定purpose、sampling status、Provider accounting或promotion eligibility。Validation candidate不能作为formal candidate使用，也不能通过替换DOM marker直接晋升。

Release Module唯一拥有：

- schema `abm-report-release-contract-v13`；
- purpose `full_pool_two_stage_realization_formal_research`；
- sampling status `persisted_two_stage_realized_full_pool_formal_run`；
- upstream live Provider与realization zero-call的composite accounting；
- realized source/evidence/projection、presentation、Historical artifacts、v12 baseline、mechanism、downloads与physical inventory closure；
- 只含部署前immutable facts的`full-pool-v13-release-readiness-v1`。

Promotion只接收显式source path/hash/identity、Historical roots、candidate、v12 release/contract、release ID与新destination。全部输入必须为repository内real path、互不重叠且在写出前后hash snapshot一致。Materialization先exact复制candidate，再由Report提供production HTML，加入canonical JSON evidence与manifest，在staging内验证missing/extra/symlink/non-regular/hash/identity后才原子安装release与contract；round-trip失败会删除二者。

Package validator与standalone CLI都dispatch到同一Release v13 validator。Validator重新读取formal realized source与upstream Source-v4、复算accounting/metrics/projection、验证Report production bytes、Historical与v12 snapshots、两阶段mechanism、downloads、release identity和完整artifact hashes，不信任caller summary。顶层`live_api_triggered=true`表达复合Formal继承upstream live evidence；同时独立保留`realization_provider_calls=0`与`realization_live_api_triggered=false`，不会把整个研究误报为zero-Provider。

Release readiness固定声明`operational_authorization_required=true`、`deployment_authorized=false`、`canonical_deployment_triggered=false`和`public_acceptance_recorded=false`。Operational authorization、remote candidate health、atomic `current`切换、public acceptance与rollback仍由后续Deployment Module拥有，不能反向写入immutable v13 release。
