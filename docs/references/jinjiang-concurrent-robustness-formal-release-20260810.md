# 锦江 Concurrent Robustness Formal Run 与 Production Release 记录

统计周期：2026-08-10—2026-08-11；口径更新时间：2026-08-11T19:49:48Z；历史 canonical release：`jinjiang-concurrent-robustness-production-v1-repair-20260811T193031Z`

> 状态更新（2026-08-13）：本 release 已由 [Concurrent Robustness v6](jinjiang-concurrent-robustness-v6-local-release-20260813.md) 取代，继续作为 managed rollback evidence；以下记录保留其当时的发布事实。

## 发布结论

- canonical endpoint [`https://abm.q1ngyuan.top/`](https://abm.q1ngyuan.top/) 已同步到 zero-call repair release；Ranking Weight family、Prompt–Model message/metric controls 与 production evidence download 均恢复闭包。
- 页面保留历史 Concurrent Formal 的 mechanism、Run Evidence、field lineage、Demographic Shadow 与 Primary + Shadow barrier；Shadow 明确不属于本次 Primary-only factorial。
- 本次 Formal matrix 完成 `4 Prompts × 4 models = 16 cells`、28,800 logical judgments；29,402 physical attempts 全部形成 28,800 successful Decisions，`provider_failed=0`。repair 未重跑或改写这些 Decisions。
- 发布使用 `abm-report-release-contract-v5`。validation candidate 的 `production_deploy_eligible=false` manifest/evidence bytes 被原样保留；只有新的独立 production layer 标记为 `production_deploy_eligible=true`。
- 公网 38 个 contract artifacts 全部逐文件 SHA-256 验收通过；14/14 approved downloads 可达；deployed Playwright 在 desktop 与 `390 × 844` 完成全部交互验收，未触发 rollback。

## Release Identity

| 项目 | 路径 / 值 | SHA-256 |
|---|---|---|
| 历史 Formal source | `runs/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z/` | manifest：`bfc793bb7322edabe6fb5eb4cce7e6990ca008a8cb0310e19507b9c14839063d` |
| Formal run identity | `jinjiang-concurrent-robustness-formal-v1-openai-codex-20260810T003438Z` | study manifest：`f885844e596489c13e482887b3535dbdedb061e5c8317cf3f185498da66b2bad` |
| Immutable study root | `runs/jinjiang-concurrent-robustness-formal-v1-openai-codex-20260810T003438Z-workspace.study-root/` | artifact manifest：`012e7bbb6263991b24479881bfcb30977f67c2217b9e652010d3f258ad23dec4` |
| Additive validation candidate | `runs/jinjiang-concurrent-robustness-formal-v1-openai-codex-20260810T003438Z-report-candidate/` | manifest：`4b42bd45a6c0a4de09eac2f7177a3652b352718f3c6418b24caebd9ef0f4be45` |
| Production source | `runs/jinjiang-concurrent-robustness-production-v1-repair-20260811T193031Z/` | report：`541bcf04820c8643c73ca9e7d927fe6a1d44c23d02f849532bcb18ab6c5eeb43` |
| Production manifest | 同上 `artifact_manifest.json` | `8c14f1447af4f2ad3d77b60e4935e902dfbfa62b74b944c348ebebda3bb96e0a` |
| Production identity | 同上 manifest | `f4471399fded9a7879c3d9c653e36ed495374ede2e40b7ec0362428fbae5d259` |
| v5 release contract | `runs/jinjiang-concurrent-robustness-formal-v1-openai-codex-20260810T003438Z-contracts/jinjiang-concurrent-robustness-production-v1-repair-20260811T193031Z.json` | `446f177189b2e618e0b9b0e4bbdb7f8374eb1738bbbbaada6ae119375340ea34` |
| Canonical release ID | `jinjiang-concurrent-robustness-production-v1-repair-20260811T193031Z` | deployment identity |
| Managed rollback release | `jinjiang-concurrent-robustness-production-v1-20260810T063938Z` | report：`9b8bface904781f5cde66aff1f9a5696ccb698a9d5e6dcba4536036a3be714dc` |

## Provider 与调用闭包

- Transport：本机 Pi `ModelRuntime` → `openai-codex` OAuth subscription；Adapter identity 为 `openai-codex-subscription-client-v1`。
- Billing：实际 subscription billed cost 为 `USD 0`。Pi catalog 的 API-equivalent nominal reference cost 为 `USD 170.8630665`，仅作参考，不表示 OAuth subscription 扣费。
- Qualification 的 requested → observed identity：
  - `gpt-5.4-mini → gpt-5.4-mini`
  - `gpt-5.4-2026-03-05 → gpt-5.4`
  - `gpt-5.5-2026-04-23 → gpt-5.5`
  - `gpt-5.6-sol → gpt-5.6-sol`
- 每个 requested model 完成 7,200 responses；四个 observed aliases 各 7,200。完整 usage 为 28,712,688 input tokens、3,672,557 output tokens、0 cached-input tokens。
- Retry 分布：28,215 judgments 使用 1 次 physical attempt，568 使用 2 次，17 使用 3 次；合计 29,402，低于 86,400 hard cap。
- 15 个 bounded workers 只写入彼此独立的最终 cell journals；唯一主 `ConcurrentRobustnessStudy.run(...)` 最终逐 cell replay、汇总 caps 并关闭 study root。
- 2026-08-11 repair 的 promotion、validation、deployment 与 public acceptance 均复用 immutable evidence，`provider_calls=0`；没有重跑 28,800 个 Decisions，也没有调用 TikHub、Douyin、profile API 或 image generation。

## 研究结果摘要

### Ranking Weight Sensitivity

- 19 个预声明 simplex points、3 条 messages、30 batches，共 1,710 个 scenario-message-batch observations。
- 10/19 scenarios 的 overall mean Jaccard distance 为 0；1,710 个 batch observations 中 40 个出现非零 audience divergence。
- 最大 scenario-level overall mean Jaccard distance 为 `0.031741037214`，发生在把 `0.15` mass 从 campaign feedback 移到 message–user fit 时。
- 局部 batch 不能被 overall mean 掩盖：28 个 batch observations 达到或超过 `0.10` practical threshold，最大单批 Jaccard distance 为 `0.947368421053`。因此只能称整体平均变化较小但存在集中式局部敏感批次，不能声称 ranking policy 全局稳健。

### Prompt–Model Robustness

- shared-seed direct Decision 的 grand mean engage rate 为 `0.96875`。
- model marginal engage rates：`gpt-5.4-mini=0.991666666667`、`gpt-5.4=0.929166666667`、`gpt-5.5=0.970833333333`、`gpt-5.6-sol=0.983333333333`。
- 预声明 contrasts：`5.4-mini − 5.4 = 0.0625`、`5.4 − 5.5 = -0.041666666667`、`5.5 − 5.6-sol = -0.0125`。这些是固定 sample/graph/shared-seed panel 上的 observed differences，不是模型质量排名。
- Prompt contrasts 相对 P0：`P1=-0.004166666667`、`P2=0.029166666667`、`P3=0.016666666667`。
- 189 个 practical-threshold classifications 中，33 个为 `practically_meaningful`、156 个为 `small_observed_difference`。其中 realized-path 指标依赖单次动态路径，不能解释为 causal effect 或 population robustness。

## Closure 修正

真实 journals 暴露并修正了三个此前 deterministic fixture 未覆盖的 closure 问题：

1. Batch 0 shared seed panel 原先错误比较 per-message ranking tuple 顺序；真实 evidence 显示三条 message 的 seed set 完全相同但排序不同。validator 改为比较 identity set，同时继续逐 message 验证 terminal order。
2. Robustness composer 原先复用历史 source 的 legacy report bytes，却要求 Editorial mechanism markers；现从同一 typed historical payload 零调用生成 Editorial v3 presentation，再附加 robustness evidence。
3. Production manifest 的 logical artifact names 原先会让同 stem 的 CSV/JSON 冲突；现把扩展名纳入 logical name。

所有修正都只作用于 replay/closure/presentation；没有重放或改写 28,800 个 Provider Decisions。最终 closure replay 的 Provider request count 为 0。

关键实现 commits：`098d843`（subscription Formal runner）、`71e9c54`（v5 gate / bounded workers）、`81bbd29`（shared seed set closure）、`1f7606d`（Editorial composition）、`5b21e65`（zero-call closure binding）、`6774b8a`（artifact logical names）。

## Deployment 与公网证据

- 授权 infrastructure 未改变：SSH target `BandwagonHost2`、remote root `/opt/llm-abm-marketing-sim-report`、canonical domain `abm.q1ngyuan.top`、container `abm-research-report` 与原子 `current` 结构全部沿用。
- 切换前回读确认 `current` 精确指向 `jinjiang-concurrent-robustness-production-v1-20260810T063938Z`；container 为 `healthy`，rollback report/manifest hashes 分别为 `9b8bface…` / `b7ae1c0f…`，38 个 regular files、0 symlink。
- 首次 repair deploy 在任何 SSH、release creation、upload 或 switch 前由本地 strict snapshot gate 拒绝：macOS `TMPDIR` 的 `/var → /private/var` 逻辑路径未先规范化。部署脚本现以 `pwd -P` 把随机 snapshot 交给 validator，并有 symlink-ancestor regression test；该次失败无需 rollback，远端状态未变化。
- 成功事务通过 v5 snapshot validation、upload hash、remote candidate/container/Nginx checks 后，于 `2026-08-11T19:45:43Z` 原子切换 `current` 到：
  - `/opt/llm-abm-marketing-sim-report/releases/jinjiang-concurrent-robustness-production-v1-repair-20260811T193031Z`
- Remote container 为 `healthy`；repair release 含 38 个 regular files、0 symlink，逐文件 hashes 全部匹配 v5 contract。原 production release 保持为已验证 managed rollback target。
- Public `/healthz=ok`；header/body report hash 为 `541bcf04820c8643c73ca9e7d927fe6a1d44c23d02f849532bcb18ab6c5eeb43`，manifest 为 `8c14f1447af4f2ad3d77b60e4935e902dfbfa62b74b944c348ebebda3bb96e0a`，payload 为 `2c426aca2edda7fdb4c0117abb6b11f19c6bf5002e7f862e92a49cbb46289440`，production evidence 为 `d7f648026b2479f25ee11eb55c317f35b35dd603d5f815865952c508324a37a0`；38/38 contract artifact hashes 和 14/14 approved download HEAD 均匹配。
- Public Playwright 往返切换三组 Ranking Weight families，覆盖 `3 messages × 2 metrics` 的唯一 view、四 model panels、每 panel 四 Prompt series 与当前 message 的 16-row shared-seed table；desktop 与 `390 × 844` 均无横向溢出、console/page error 或第三方请求。
- Public transport 曾出现两次可重试 TLS connection error，既有 bounded retry 随后成功；最终 acceptance 全部通过，rollback 未触发。

## Validation

- v5 original source 与独立 physical snapshot contract validation：passed。
- immutable historical Formal、workspace、study root、validation candidate、原 production 与 repair production 六个 roots 前后 tree closure 一致，changed files `0`。
- Python compile：passed；full pytest：`621 passed, 2 deselected`；Ruff：passed；selected Pyright：`0 errors, 0 warnings, 0 informations`；Bash syntax：passed。
- deployment regression suite：`30 passed`。
- local production deployed-contract Playwright：`1 passed`。
- canonical deployed Playwright：`1 passed`，包含完整 interaction、responsive、same-origin artifact/download checks。
- deploy transaction 与独立 post-deploy readback：38/38 public artifact hashes matched；remote `current`、container health、report/manifest hashes 与 rollback target matched。

## 解释边界与安全

本研究无 ground truth，不称 Calibration；不做 causal、statistical-equivalence、population-robust 或模型质量排名结论。所有结果只条件于固定 1,000-user Research Sample、固定 graph、固定 messages、shared-seed direct panel 与每 cell 一条 realized path。

未读取、打印或提交 `.env`、OAuth credential、API key、raw Prompt 或 raw Provider payload/response。run artifacts 只包含 allowlisted Decision/evidence；qualification、Formal calls 与 deployment 均使用显式 gate。没有调用 TikHub、Douyin、profile API 或 image generation。
