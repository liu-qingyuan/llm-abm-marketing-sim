# Full-Pool Two-Stage Engagement Realization

本文描述当前可执行的 Full-Pool 两阶段 validation replay。它在已关闭的 Strict Source-v4 Provider Judgment 与 ABM feedback commit 之间加入 `Engagement Realization Module`，但不修改旧 Source-v4、`EngageDecision`、v12 release 或 canonical endpoint。当前输出固定为 nonproduction、nondeployable，也不授权 Provider、Report promotion 或部署。

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

Replay 在开始和发布后重复 inventory immutable Source-v4；任何 upstream bytes变化都会失败。当前 validation source、evidence 和 projection始终声明 `production_deploy_eligible=false`，且不调用真实 Provider、live API、SSH 或 canonical deployment。
