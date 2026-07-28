# Concurrent Message Durable Execution

Status: Implemented runtime architecture note

本 Note 说明 Concurrent Message runtime 的 durable execution 边界。它描述 offline、mock 和已获得授权的 Formal run 如何持久化、恢复和发布 artifact；它不授权 Provider、SSH 或 canonical deploy。

相关实现：

- [`src/llm_abm_sim/concurrent_execution_journal.py`](../../src/llm_abm_sim/concurrent_execution_journal.py)：identity、append-only journal、snapshot、checksum replay、status 和 single-writer lock；
- [`src/llm_abm_sim/concurrent_message_experiment.py`](../../src/llm_abm_sim/concurrent_message_experiment.py)：fresh/resume runtime、staging build、atomic final-source publication；
- [`src/llm_abm_sim/concurrent_message_report.py`](../../src/llm_abm_sim/concurrent_message_report.py)：报告 artifact set、manifest 和 read-only rebuild；
- [`scripts/validate_abm_report_release.py`](../../scripts/validate_abm_report_release.py)：显式 release contract 的本地 validator；
- [`scripts/deploy_abm_report.sh`](../../scripts/deploy_abm_report.sh)：formal-only canonical deployment boundary。

## 四个目录边界

| 目录 / 对象 | 产生方式 | 允许内容与职责 | 发布资格 |
|---|---|---|---|
| private operational workspace | `derive_concurrent_execution_workspace(output_dir)` 返回 output sibling `.<name>.operational` | run identity、append-only journal JSONL、status snapshot、batch snapshots 和 single-writer lock；用于 validated replay、safe resume、corruption detection 和 lifecycle 诊断 | 永远不可 deploy；`deploy_eligibility` 固定为 `false`，不能作为 release `source-dir` |
| publish staging directory | `derive_concurrent_execution_publish_staging_dir(output_dir, run_id=...)` 返回 `.<name>.<run_id>.staging` | 完整但尚未公开的 report artifact set；writer 先生成并 rebuild report，再计算 `artifact_manifest.json` hash | 只服务同一 run 的原子发布和 crash recovery；不能绕过 release contract 直接 deploy |
| final source directory | runner 的显式 `output_dir`，例如 `runs/<persisted-run>` | `config_snapshot`、runtime rows、diagnostics、report payload、HTML、downloads 和 manifest；staging 通过 `Path.replace` 成为该目录 | 仅是本地 release validator 的 source；只有匹配且通过显式 Formal contract 才能进入 candidate deploy |
| canonical release | deploy script 使用的显式 contract、final source snapshot 和 release id | candidate deployment、health/host checks、atomic `current` switch、public acceptance 和失败回退 | canonical endpoint 的唯一发布边界；不能从 workspace 或 staging 推断授权 |

`rebuild_concurrent_message_report(run_dir, *, destination_dir=None)` 是报告 Module 的唯一公开重建 Interface。省略或显式传入 `None` 时，它先完成 typed artifact closure，再以 persisted report hash 选择冻结的 renderer bytes，并只原子替换 source 的 `report.html`；manifest、payload、runtime、diagnostics、downloads 和其他 source artifacts 不会被重建写入。显式 destination 时，source closure 在任何 staging 创建前完成；Module 只按 canonical artifact table 复制 approved persisted views 到 destination sibling 的唯一 staging directory，使用 current two-mode renderer 生成新的 `report.html`，重建 manifest，并再次通过 closure 与默认 exact rebuild 验证后才 atomic rename。destination 必须原先不存在且与 source 不重叠、无 symlink/path escape，并与 staging 保持同一 filesystem；任何 copy、render、hash、closure 或 rename 失败都会清理 staging，source 和最终 destination 保持不变。该 Interface 返回 source 或 candidate 的 `report.html` 路径，不创建 release contract、不调用 `validate_release(...)`，Formal eligibility 与 deploy policy 仍归 release Module。


Operational workspace 是私有运行状态，不是报告 source。它与 final source 位于不同路径，默认被 git 忽略，可能包含恢复所需的用户/run evidence；不得复制到报告目录或部署包。Status JSON 是 operational observation，`ConcurrentExecutionJournal.status()` 会重新执行 validated replay，不把旧 status 文件当作事实来源。

## Runtime 生命周期

1. `open_new` 校验 run identity，创建 workspace、identity file、snapshot directory 和 lock，并 append `run_started`。
2. 每个 batch 先持久化 ranking snapshot，再按 `variant_started`、`variant_terminal`、`pair_closed` 和 `batch_committed` 的顺序 append event。每个 event 都绑定 snapshot hash；replay 校验 sequence、run identity、checksum chain、snapshot identity、pair order 和 count closure。
3. 所有 batch commit 完成后，runner 在 staging directory 写出完整 artifact set，rebuild report，并以 manifest hash append `run_finalized`。此时仍未把 workspace 变成 release source。
4. staging 通过 atomic rename/replace 成为 final source directory；runner 再 append `run_published`。published 状态要求 final source 和 manifest 存在，且 manifest hash 与 journal evidence 一致。
5. resume 通过同一 identity 打开 workspace lock，先 replay journal，再从 durable records 恢复 runtime state。它不会因为缺少 in-memory state 而重新调用已完成的 Provider decision。

## Crash Recovery

`run_finalized` 与 `run_published` 是两个不同的 durable boundary：前者证明 staging artifact 已闭合，后者证明 final source 已完成替换并可被读取。

如果进程在 staging 生成后、rename 前退出，resume 仍以 journal snapshot 和 event records 为输入，重新构建或验证 staging，不跳过 source-row、manifest 和 report closure。若进程在 rename 后、`run_published` 前退出，replay 会识别完整 final source；resume 只 rebuild/verify report 并补记安全的 `run_published` state，不重复 Provider calls。

任何 journal corruption、truncation、duplicate/out-of-order event、unknown snapshot、identity mismatch、second writer 或 inflight-unknown 状态，必须在新的 Adapter call 或 final publication 前失败关闭。Workspace 的存在不能替代这些检查，也不能被解释为已完成 release。

## Canonical Deploy Gate

Canonical deploy 的输入必须是显式指定的 final source directory、仓库内安全的 release contract 和 release id。validator 从 final source 只读重建 report/diagnostics，并检查 artifact manifest、schema/token、provider accounting、sampling status、source identity 和 contract closure；deploy 随后使用同一只读 source snapshot 完成 candidate、health、atomic `current` 和 public acceptance 流程。

因此：

- `.<name>.operational` 只能用于 runtime replay/resume，不能传给 `--source-dir`；
- `.<name>.<run_id>.staging` 只能用于同一 run 的本地 finalization，不能跳过 final source 或 contract validation；
- validation/mock/rule-based artifacts、`ready-for-agent` 状态和代码实现本身都不表示 production authorization；
- 只有独立记录 Provider、模型、调用/费用预算、output directory、release id 和 canonical deployment authorization 的 Formal run，才可以进入 canonical release gate。
