# Full-Pool 两阶段 authoritative replay 发布门禁（2026-08-26）

## 状态

- parent Spec：[#228](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/228)
- execution Ticket：[#235](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/235)
- 状态：**Formal realized source 已闭合；冻结诊断 action totals 不匹配，已在 presentation、v13 release、deployment readiness 与 cutover handoff 前失败关闭**
- canonical endpoint：`https://abm.q1ngyuan.top/`；本次未连接、未切换、未修改
- realization Provider calls：`0`
- realization live API：`false`
- upstream Formal lineage：`live_api_triggered=true`，requested/observed model 为 `gpt-5.6-sol`
- secrets 读取、打印或写入：否

本记录是失败关闭的 Formal operation audit，不是 v13 release、deployment authorization 或 canonical 发布记录。下面的 realized source 虽通过 source-level Formal closure，仍不得在 #235 的诊断门禁解决前晋升。

## 显式输入与规则

本次没有扫描 `latest`，也没有消费 exploratory counterfactual：

- Source-v4：`runs/full-pool-strict-formal-ticket-205-production-replacement-20260819T153532Z/formal-source-v4/`
- source identity：`de46305782293a7abf363ef9dff5d6a85cb44c4c9ad2f827d94a1e1feb50acfe`
- source manifest SHA-256：`841087cf5632a12c0834045942a1c893564c48aead8f94f2576438bf152cad21`
- realization rule：`sha256-source-user-message-first-53-bits-uniform-v1`
- realization seed：`20260823`
- Historical Formal：`runs/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z/`
- Historical study：`runs/jinjiang-concurrent-robustness-formal-v1-openai-codex-20260810T003438Z-workspace.study-root/`
- Historical candidate：`runs/jinjiang-concurrent-robustness-report-candidate-v4-semantic-v7-20260813T152334Z/`
- protected v12 release：`runs/full-pool-strict-formal-v12-production-delivery-runs-20260823T132643Z/`
- protected v12 contract：`runs/full-pool-strict-formal-v12-production-delivery-runs-20260823T132643Z-release-contract.json`

规则按已冻结的嵌套哈希执行：先计算 `realization_key = SHA256(source_identity NUL user_id NUL message_id)`，再以 `SHA256(decimal_seed NUL realization_key_hex)` 的前 53 bits 形成 draw。没有更换 seed、按 Segment 缩放、筛选 pair、补造 action 或手工修正结果。

## Authoritative source identity

- run root：`runs/full-pool-two-stage-authoritative-ticket-235-20260826T122716Z/`
- Formal realized source：`formal-realized-source/`
- classification：`formal_two_stage_realized`
- manifest SHA-256：`2b72356e205e670212f3a7a9dbc88fd64fbabe61c5de004047b82a629c1e33eb`
- source identity：`b348c1bd309788df41b2a86106fe5216ce6fc6dc9317a67bc19351d3a249e1d7`
- source hash：`4190c25fb7f7d8ec73c0498048f042f17fe6f7919cd2e62ef2f5bf5481dca467`
- run record：`formal-replay-run-record.json`
- run record SHA-256：`93424ab06c1ae5f077529c6770c8b888fad0175e960707030811b2b64257407d`
- machine gate audit：`release-gate-audit.json`
- machine gate audit SHA-256：`92efc89e302df5d4bae426db82a161f63d161f03ae2d5e4d2dab67f84f01f7ae`
- human gate report：`release-gate-audit.md`
- human gate report SHA-256：`04c10e8738a0601b12cf2c8005f0ddc0d0582ab6a9cc7d1be5ef19eefdf7d3b7`
- duration：`812.180169s`
- peak RSS：`3,632,988,160` bytes

Source 闭合 `36,400` users、`109,200` pairs/exposures/terminals、`3` messages、`30` batch commits、`1,691,730` candidate rows、`270` projection rows。realization accounting 为 `provider_calls=0`、`live_api_triggered=false`；复合 Formal 顶层仍保留 upstream live Provider、`110,320` external requests / settled attempts 与完整 usage lineage。

## Blocking mismatch

Action totals 均由 realized terminal rows流式重算，并与 manifest、projection 独立闭合：

| Action | #235 冻结参照 | Authoritative artifact | Delta |
|---|---:|---:|---:|
| Like | 63,259 | 63,420 | +161 |
| Comment | 6 | 5 | -1 |
| Share | 177 | 189 | +12 |
| Ignore | 45,758 | 45,586 | -172 |

冻结参照合计 `63,442 / 109,200 = 58.097070%`；authoritative artifact 为 `63,614 / 109,200 = 58.254579%`，相差 `+172` engagements / `+0.157509` percentage points。

总体 Segment 结果为：

| Segment | Engagement / Exposure | Rate |
|---|---:|---:|
| S1 | 35,435 / 46,848 | 75.638234% |
| S2 | 20,419 / 45,210 | 45.164787% |
| S3 | 7,760 / 17,142 | 45.268930% |

九格结果为：

| Cell | #235 诊断参照 | Authoritative artifact | Delta |
|---|---:|---:|---:|
| S1–M1 | 75.06% | 75.2561% | +0.1961 pp |
| S1–M2 | 74.84% | 75.2497% | +0.4097 pp |
| S1–M3 | 75.81% | 76.4088% | +0.5988 pp |
| S2–M1 | 28.36% | 28.4207% | +0.0607 pp |
| S2–M2 | 56.40% | 56.7551% | +0.3551 pp |
| S2–M3 | 51.01% | 50.3185% | -0.6915 pp |
| S3–M1 | 37.64% | 37.2069% | -0.4331 pp |
| S3–M2 | 41.88% | 42.9471% | +1.0671 pp |
| S3–M3 | 55.86% | 55.6528% | -0.2072 pp |

排序仍闭合为 S2 `M2 > M3 > M1`、S3 `M3 > M2 > M1`；S1 为 `M3 > M1 > M2`，不能声称偏向 M1。

## 原因与发布决定

[#231 completion evidence](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/231#issuecomment-5423253336) 已隔离同一差异：父 Spec 的约 `58.10%` 与 `63,259 / 6 / 177 / 45,758` 参照来自 `SHA256(seed NUL source NUL user NUL message)` 单哈希 shortcut；#230 后冻结的 v1 production contract 则使用“先 stable realization key、再 draw digest”的嵌套哈希。两者即使使用相同 source、pairs 与 seed，也会形成不同的确定性随机流。

因此不能通过以下方式让结果贴合参照：

- 不得在 `sha256-source-user-message-first-53-bits-uniform-v1` 名下静默更换算法；
- 不得挑选新 seed、按 Segment 校准或修改 persisted outcomes；
- 不得硬编码 action totals 或手工改 report；
- 不得把 #231 validation artifact或 exploratory counterfactual 晋升为 Formal。

#235 明确要求 action totals 不同即解释并停止发布。本次据此没有生成 presentation candidate、v13 release、v13 contract、deployment readiness 或 `ready-for-human` cutover Ticket。后续需要 human triage 明确选择：接受并版本化嵌套 v1 的 authoritative counts，或定义新的 rule version并重新走 contract/tests/Formal replay；不能把两个随机算法视为同一合同。

## 本地验证

通过：

- formal source persisted reader 与独立 terminal / projection roll-up；
- `python -m py_compile $(find src tests scripts -name '*.py' -print)`；
- `pytest -q`：`1075 passed, 4 deselected`；
- `ruff check .`；
- `uvx pyright --pythonpath .venv/bin/python src/llm_abm_sim`：`0 errors`；
- `npx playwright test tests/playwright/full-pool-presentation.spec.ts`：`2 passed`；
- 文档导航、run artifact hash与publication-boundary assertions。

实际 authoritative v13 presentation Playwright、release round-trip和deployment preflight没有运行：action totals gate先失败，继续 materialize或promotion会违反 #235 的停止发布条件。Playwright结果只证明既有fixture合同仍为绿色，不冒充本次未生成artifact的验收。

## Immutability 与未触发边界

Replay 前后 protected inventories exact match：

| Protected input | Files | Inventory SHA-256 |
|---|---:|---|
| Source-v4 | 49 | `608cdbaf5e36c99c0f9cc2131f02ec977a48568264cee38f2ea7bfce4d6f8e2e` |
| Historical Formal | 23 | `a705db55bd19032d5716bed3141c40c2953590e825737b8d878cf05380edb453` |
| Historical study | 7 | `106b57006d57154cbbe74ff1603691ad2f76d543795cc81f4169f65535ab8074` |
| Historical candidate | 43 | `27e1bdd663f0ff6881f5039918713e87441a8cfecdbb47d6c589bcaa7d225823` |
| v12 release | 193 | `3e7c2eadceb0909b2b336283741c48e8ded83b5687f15efec736df2578f3660f` |

- v12 contract SHA-256：`8f3f2ed3448b98705a55ace8b95d4bcae00527619b4ec2a1b45d2f7b7e370c89`
- protected local v12 `report.html` SHA-256：`32823528e6ea1d871c8f0157e0bb72c4c19fe1b11881454c8b623b89ef82bf17`
- canonical connection / SSH / upload / remote write / public request：`0`
- canonical deployment triggered：`false`
- Provider、TikHub、Douyin、profile API calls：`0`
- secrets 读取、打印或写入：否

Canonical 是否仍返回该 v12 hash没有在本 Ticket 中通过网络重验；这是“不连接 canonical”边界的有意结果，而不是 public acceptance 声明。
