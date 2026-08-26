# Full-Pool 两阶段 v13 Release Readiness（2026-08-27）

## 状态

- parent Spec：[GitHub #228](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/228)
- 原 authoritative operation：[GitHub #235](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/235)
- nested-v1 continuation：[GitHub #236](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/236)
- 状态：**authoritative presentation 与 immutable v13 Release 已闭合并通过独立 round-trip；deployment preflight 因缺少 operational authorization 在首次 SSH 前按设计停止**
- canonical endpoint：`https://abm.q1ngyuan.top/`，仍发布 v12；本次没有上传、远端写入或 `current` 切换
- realization / promotion Provider calls：`0`
- realization live API：`false`
- upstream Formal lineage：`live_api_triggered=true`，requested/observed model 为 `gpt-5.6-sol`
- secrets 读取、打印或写入：否

本记录是 release readiness 与 human handoff evidence，不是 deployment authorization 或公网发布记录。

## Nested-v1 决策

维护者已在 #236 前明确接受 `sha256-source-user-message-first-53-bits-uniform-v1` authoritative outcomes。#235 中的 `63,259 / 6 / 177 / 45,758` 保留为 single-hash shortcut diagnostic，不再作为 nested-v1 发布门禁；既有失败关闭审计保持原 bytes，不被改写。

正式规则、seed 与 source 均未改变：

- realization rule：`sha256-source-user-message-first-53-bits-uniform-v1`
- seed：`20260823`
- Formal realized source：`runs/full-pool-two-stage-authoritative-ticket-235-20260826T122716Z/formal-realized-source/`
- source identity：`b348c1bd309788df41b2a86106fe5216ce6fc6dc9317a67bc19351d3a249e1d7`
- manifest SHA-256：`2b72356e205e670212f3a7a9dbc88fd64fbabe61c5de004047b82a629c1e33eb`
- closure：36,400 users、109,200 exposures/terminals、3 messages、30 batch commits、1,691,730 candidate rows、270 projection rows

## Authoritative realized results

Action totals 均从 persisted realized terminal rows独立重算：

| Action | Count |
|---|---:|
| Like | 63,420 |
| Comment | 5 |
| Share | 189 |
| Ignore | 45,586 |
| Engagement | 63,614 / 109,200 = 58.254579% |

Segment 单次曝光结果：

| Segment | Engagement / Exposure | Rate |
|---|---:|---:|
| S1 | 35,435 / 46,848 | 75.638234% |
| S2 | 20,419 / 45,210 | 45.164787% |
| S3 | 7,760 / 17,142 | 45.268930% |

Segment × Message 九格：

| Cell | Engagement / Exposure | Rate |
|---|---:|---:|
| S1–M1 | 11,752 / 15,616 | 75.256148% |
| S1–M2 | 11,751 / 15,616 | 75.249744% |
| S1–M3 | 11,932 / 15,616 | 76.408811% |
| S2–M1 | 4,283 / 15,070 | 28.420703% |
| S2–M2 | 8,553 / 15,070 | 56.755143% |
| S2–M3 | 7,583 / 15,070 | 50.318514% |
| S3–M1 | 2,126 / 5,714 | 37.206860% |
| S3–M2 | 2,454 / 5,714 | 42.947147% |
| S3–M3 | 3,180 / 5,714 | 55.652783% |

排序为 S1 `M3 > M1 > M2`、S2 `M2 > M3 > M1`、S3 `M3 > M2 > M1`。报告不声称 S1 偏向 M1，也不把 simulated engagement 解释为真实抖音绝对互动率。

## Immutable v13 Release

- run root：`runs/full-pool-two-stage-v13-release-ticket-236-20260826T142827Z/`
- Release ID：`full-pool-two-stage-v13-production-20260826T142827Z`
- contract：`full-pool-two-stage-v13-production-20260826T142827Z-release-contract.json`
- contract schema：`abm-report-release-contract-v13`
- purpose：`full_pool_two_stage_realization_formal_research`
- sampling status：`persisted_two_stage_realized_full_pool_formal_run`
- production deploy eligible：`true`
- release identity SHA-256：`27130adc334502f83a4467aa6e4a89ca9ed5436ed451d43732889eae7a2c1f89`
- contract SHA-256：`91d03641c9c18abe62a5551be314cbe1aee304afe9ec8aff483916012318ff5a`
- report SHA-256：`4602ee446159e45610e360183091e6f86d802eb0f2fdfc6a6f44415fb662e784`
- manifest SHA-256：`95d3e1327e71eb19301a5d7b81a71e2a95d37d9442be268368045ab919740a12`
- physical inventory：148 files，identity `cfb66badc21e4f43244127316fb072134cec9ab26f46a49baa527c7d33121d5d`
- operation record SHA-256：`c1c620d4521334b0131a418757d1a5f8143df750e40503c5425dad8da9129217`
- immutable before/after snapshot SHA-256：均为 `23a8e8c4012bfd52229c4b6c4e5e172627eb5f10b302df415250e6886a95087f`

第一次自动执行在 create-once Release 已完成后，因通用 runner 的固定超时中断于重复的 independent validator。恢复流程没有重建或修改 Release bytes，而是复用既有 immutable Release，独立 validator通过后才写入 after-snapshot 与 operation record。该恢复事实保存在 operation record 的 `recovery` 字段。

## Deployment readiness

无 authorization 的真实 v13 preflight 对完整本地 snapshot执行 standalone Release validation，然后以 exit code `2` 在任何 SSH、upload、remote write 或 public deployment前停止：

- readiness schema：`abm-report-v13-deployment-readiness-v1`
- readiness SHA-256：`d3d603d36ddecb3eb20187151ead71c3040dee2112952c6ed3896c6c3ffb4913`
- status：`awaiting_operational_authorization`
- deployment authorized：`false`
- remote connection authorized：`false`
- rollback identity required：`true`
- target host：`BandwagonHost2`
- remote root：`/opt/llm-abm-marketing-sim-report`
- topology：`immutable-releases-atomic-current-v1`
- port / container / image：`18083` / `abm-research-report` / `nginx:1.27-alpine`

只读公网 baseline随后确认 canonical仍返回受保护 v12：

- v12 Release ID：`full-pool-strict-formal-v12-production-delivery-runs-20260823T132643Z`
- managed rollback path：`/opt/llm-abm-marketing-sim-report/releases/full-pool-strict-formal-v12-production-delivery-runs-20260823T132643Z`
- public `report.html` SHA-256：`32823528e6ea1d871c8f0157e0bb72c4c19fe1b11881454c8b623b89ef82bf17`
- public `artifact_manifest.json` SHA-256：`0cc7c9c56f34103da4679b74e92dd64627f797e96d103ee31339963b65da14c0`

这些 baseline facts 只用于 human authorization中的预期 rollback identity。获得授权后的第一次 SSH仍必须fresh readback远端`current`，并与授权 identity exact match后才允许candidate write。

## 验证

通过：

- authoritative realized source persisted reader与独立terminal/projection roll-up；
- v13 create-once promotion、package validator、standalone validator和round-trip validation；
- 无authorization deployment preflight：预期exit code `2`并生成canonical readiness JSON；
- actual v13 Release local deployed Playwright：`1 passed`，覆盖desktop/mobile、zh-CN/en-US、148个approved artifacts、visible SVG、fallback、trace与downloads；
- actual authoritative presentation Playwright：`2 passed`；
- synthetic presentation Playwright：`2 passed`；
- `ruff check .`；
- `pyright src/llm_abm_sim`：`0 errors`；
- full `py_compile`；
- `pytest -q`：`1075 passed, 4 deselected`；
- 文档exact-set与本地链接门禁。

## Human handoff

下一步只能由独立`ready-for-human` operational Ticket授权。Authorization必须exact绑定本记录中的v13 contract/release/source/target，以及上面的预期v12 rollback identity。合法授权后deployment仍需执行fresh rollback readback、candidate health、atomic `current`切换、公网report/manifest/全部approved downloads hashes和实际interaction验收；任一步失败必须恢复并重新验收旧v12。
