# GPT-P0 旧判断复用审计（2026-09-16）

Status: Offline Evidence Audit  
Ticket: `#258`  
Machine run: `runs/gpt-p0-judgment-reuse-audit-ticket-258-20260916T051735Z`  
Result: **历史完整性通过，但当前无一条可直接接纳进新 Judgment Bank**  
Provider calls: `0`

## 结论

固定 1,000-user × 3-message universe 共 `3,000` 个组合。旧 GPT-P0 证据包含 `1,800` 个唯一组合；逐条 lineage、settled attempt、Decision、Realized terminal、随机性与 30 个 barrier 均闭合。但是，原始 client payload digest 未持久化，只能从 hash-bound source 与记录的实现 commit 重建；effective upstream context / service snapshot 不可观测，未来补采合同也尚未冻结。因此本审计按 fail-closed 规则把旧 `1,800` 条全部保留为 `undetermined`，而不是自动接受或武断拒绝。

- accepted: `0`
- rejected: `0`
- undetermined / evidence insufficient: `1,800`
- physically missing pairs: `1,200`
- duplicate pairs: `0`；conflicting pairs: `0`
- 当前 accepted coverage: `0/3,000`；未闭合组合: `3,000`

只有未来先冻结目标请求条件、再证明全部旧 1,800 条与之同条件时，新增成功 Judgment 才是 `1,200`。当前未闭合量为 `3,000`，明显高于该目标；这只是 coverage 结论，**不是** 3,000 次 Provider 调用授权或预算。

## 2026-09-17 接手复核：如何理解“待定”

本审计区分两件事：**历史记录是否完整**与**是否批准用于未来判断库**。前者的逐条检查通过；后者尚未确认。全部 `undetermined` 是当前接纳政策作用于同一证据条件的结果，并非逐条查出了 1,800 个输入差异，也不是 1,800 条判断作废。

实际未采组合是 **1,200**。`3,000` 未闭合组合是“1,800 待确认＋1,200 未采”，不是重采预算。#259 应明确提出是否接受“冻结来源与历史实现重建客户端输入＋观测模型/路由一致＋服务漂移披露”的条件性接纳方案，由研究者确认。服务端隐藏上下文不可观测这一限制也会存在于新采数据，不能通过盲目全量重采自动消除。

在接纳条件获批前，本报告保留原始 `undetermined`，不修改旧证据，不把重建摘要宣称为原请求直接观测。

## 输入 lineage

| 输入 | SHA-256 |
|---|---|
| Evidence `outputs/01a08bb3-1446-7f51-8933-cd49b50e9ccb/four-model-final-20260912-verified/Evidence.json` | `a7407bf355d6049af8667a69b540fe2b29591d7f8e7ef71d6cb08d01fee72b17` |
| Plan `runs/concurrent-robustness-recovery-formal-20260909T213305Z/plan.json` | `2d64026ce755a5a5c3e8dd42f6c74add7dc1435b42adef3cbc47dac030da9b16` |
| Recovery bundle `.../bundles/a28681fbaf27c90552dd4a8c4e410696353e99ff18dc176d6ec5a41872311977/bundle.json` | `ce26efded477a0f4dbed5fb5299639b99dcf4f95c4e3e20177281748cbbadc4a` |
| Ledger prefix `.../bundles/a28681fbaf27c90552dd4a8c4e410696353e99ff18dc176d6ec5a41872311977/ledger-prefix.jsonl` | `82724fa9dc579b50eb9dcc538b66fd5114d1d43322ae8cc1aa2da14b864a111d` |
| Source manifest `runs/jinjiang-prompt-model-v2-formal-20260906T140259Z/study_manifest.json` | `d203cbea3cd17597751d879235ab6091c8145ee4df52c952de5811335641825e` |

审计只沿上述 Evidence → plan → explicit bundle/control/source lineage 读取；没有扫描 `latest` 或其他候选 run。bundle reader 复验 `397` 个 hash-bound artifact facts 及原 event origins。

## 冻结身份与逐条核对

| 项目 | 结果 |
|---|---|
| sample | `b639cb264d1e475ad065264e385caae5d90b3dd902d5fd19bb9c2d83461b811b`；1,000 users，重算一致 |
| graph | `47d536d4f550b675cff0f6634cab25f22521e5eca33fd971b4b86611d3c20716`；effective graph 重算一致 |
| messages | `e30eb1ce039019aa9b4b3f6c2e17617fb5e7c62157df257c415a49599cb9ed27`；`message_1..3` |
| Prompt | `jinjiang-concurrent-message-primary-prompt-v1` / `sha256:cc50affc4e658a9a1804f5e1824710cb073003aff3cc6af8f8c5cd8edf5cdc7c` |
| structured schema | `engage-decision-output-v1` / `sha256:baa4b5ac3950d8834bd296b184b8544c707633d5e668e1ee23cb8570e0e46654` |
| model | requested `openai-codex/gpt-5.6-sol`；wire/observed `gpt-5.6-sol` / `gpt-5.6-sol` |
| route / wire | `pi_openai_oauth_subscription` / `pi_model_runtime` |
| reasoning / ceiling | `low` / `256` total completion tokens；`application_fail_closed` |
| timeout / retry | `30.0s` / max `2` retries / `0.5s` backoff；每 logical pair 最多 `3` attempts |
| sampling | omitted `temperature, top_p, seed` |
| realization | seed `20260823`；`sha256-source-user-message-first-53-bits-uniform-v1` |
| store | `fresh-per-cell-no-cache-v1` / cache retention `none`（历史合同，不改写为新 bank 合同） |

对每个旧 Judgment 都从冻结 sample、effective graph、message snapshot、同路径 batch feedback 与 P0 template 重建完整 `DecisionInput`，保存 `decision_input_sha256`、`client_messages_sha256` 和 observable-condition key；不在报告或清单中复制 raw Prompt/profile 文本。`1,800` 条 Judgment、`1,804` 个 physical attempts（其中 `4` 个已结算 retryable failure）、`1,800` 个 Realized terminals 与 `30` 个 batch commits 均逐条回链到 immutable ledger。

P0 的 1,800 个 Judgment 均为 `concurrent-recovery-provider-judgment-v1`，无 per-Judgment amendment；它们在 campaign-level `final_model_continuation_accepted`（event `91476`，approval SHA-256 `d43f41179444e2c481ec13eac44497b12f25f7306ed5975186e595991da15183`）、成功 self-check（event `91478`）与 epoch admission（event `91479`，epoch plan SHA-256 `31de16f7bd9edf5de60134575297f50a21db9e0f0f4694c4b9af493c69e68dee`）后执行。后续 GPT parallel/manual-retry amendment 不追溯改变 P0。所有成功 response 都报告 `gpt-5.6-sol` 且 usage complete；审计相关实现 bytes 与 completion audit 记录的 commit `739f2e03388ad3b8c7433458ee8a06bb6e4af0a1` 一致。

## 按 message 闭合

| message | universe | accepted | rejected | undetermined | duplicate | conflict | missing |
|---|---:|---:|---:|---:|---:|---:|---:|
| `message_1` | 1,000 | 0 | 0 | 600 | 0 | 0 | 400 |
| `message_2` | 1,000 | 0 | 0 | 600 | 0 | 0 | 400 |
| `message_3` | 1,000 | 0 | 0 | 600 | 0 | 0 | 400 |

旧判断库大小 `1,800` 是一条历史 GPT-P0 动态路径的实际 exposure/Judgment 数，不是每条未来参数路径都要把 3,000 pairs 全部曝光。固定 Top20 × 30 batches × 3 messages 的路径分母仍是 `1,800`；`3,000` 只是完整 Judgment Bank 的 eligible universe。

## 为什么保持未定

1. **原请求 payload digest 不存在。** 代码与 hash-bound 输入允许重建 client-submitted messages，但历史 evidence 没有保存逐请求原始 digest，不能把重建结果表述成原 payload 的直接观测。
2. **effective upstream context 不可观测。** Pi ModelRuntime 路由、模型服务端 system context / rollout 与服务版本没有可闭合 snapshot；client contract 相同不等于 upstream effective context 已证明相同。
3. **服务时间漂移。** P0 Judgment 持久化窗口为 `2026-09-11T17:52:17Z` 至 `2026-09-11T20:37:35Z`。未来补采发生在另一服务时间，不能自动并入统一条件。
4. **目标合同未冻结。** 新 Judgment Bank 的最终 route/model qualification、complete input identity 与 collection-time contract 尚未批准；本审计不能替未来合同作出相等性判断。

## 可复核产物

Machine run：`runs/gpt-p0-judgment-reuse-audit-ticket-258-20260916T051735Z`

| 文件 | SHA-256 |
|---|---|
| `audit.json` | `fe81956c94e6185173426c853293f5dcec13e0a3162d70eec5af11497e24043f` |
| `judgment_evidence_checklist.jsonl` | `4135ccb474cbfa0fbc8a8c214afcfcbd156186faf8a753dc536725ba6ba1f814` |
| `pair_coverage_checklist.csv` | `8253b64c99871b9011c00f1927dce0bd47833859fe231d16c962a5e5895a4abe` |
| `report.md` | `26aaf6cef768608934a295af7c6b7ee761ddfb4a1390c22ba298f47c733e2635` |
| `artifact_manifest.json` | `d26d3999045601764af9d0ea7dde8ade2ad34d9884fbb8d68bfc8e7b037af8d5` |

复现命令：

```bash
. .venv/bin/activate
python scripts/audit_gpt_p0_judgment_reuse.py \
  --evidence outputs/01a08bb3-1446-7f51-8933-cd49b50e9ccb/four-model-final-20260912-verified/Evidence.json \
  --plan runs/concurrent-robustness-recovery-formal-20260909T213305Z/plan.json \
  --output-dir runs/gpt-p0-judgment-reuse-audit-ticket-258-<new-run-id> \
  --audit-date 2026-09-16
```

`pair_coverage_checklist.csv` 覆盖全部 3,000 pairs；`judgment_evidence_checklist.jsonl` 对 1,800 条旧记录保存输入 fingerprint、request condition、attempt/origin 与 fail-closed disposition。原 Evidence、source、control、Provider response 与生产接口均未修改。

## 边界

- `provider_calls=0`；未调用 LLM、TikHub、Douyin、profile API、Ralph、Release 或 Deployment。
- 未读取、打印或写入 `.env`、credential、Authorization header、raw Provider payload 或 raw Prompt。
- 本结果不拒绝历史 Judgment 的研究真实性；它只表示目前无法证明它们与未来补采属于同一完整请求条件。
- 本次不影响 canonical endpoint，不改变生产合同，也不产生部署资格。

## 2026-09-17 验收记录

- 直接离线重跑：`runs/gpt-p0-judgment-reuse-audit-ticket-258-20260917-direct`，退出0，`provider_calls=0`；4份manifest产物哈希通过。两份逐条/覆盖清单与2026-09-16原产物逐字节一致。
- 聚焦测试：`python -m pytest -q tests/unit/test_gpt_p0_judgment_reuse_audit.py tests/unit/test_concurrent_recovery_judgment.py tests/unit/test_recovery_final_model.py`，14 passed。新增CLI负例覆盖篡改、缺失和符号链接输入，拒绝后不生成结果、不修改输入。
- `python -m py_compile $(find src tests scripts -name '*.py' -print)`通过；当前新增脚本与测试的Ruff及Pyright检查通过。离线拒绝Provider的client返回类型已修正为NoReturn，无行为变化。
- 全仓默认pytest尝试在约193秒后主动停止：89 passed、7 deselected，未完成全套，不声称全仓绿色。
- 全仓指定范围Ruff 42项、Pyright 81项既有问题，分别位于3和15份本次未修改文件，已与基线18fc90f逐字节核对；未扩展本Ticket修复历史问题。
- Standards与Spec两轴只读review未发现Critical/High阻塞。审计完成不等于未来复用政策已批准；后续由#259提出方案。
