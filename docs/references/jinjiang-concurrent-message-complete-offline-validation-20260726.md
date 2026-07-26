# 锦江 Concurrent Message 完整离线验证记录

统计周期：2026-07-26；口径更新时间：2026-07-26

## 核心成果

- 最终验收对象固定为 `runs/jinjiang-concurrent-message-mock-validation-20260726T201800Z/`；两个独立 rerun `runs/jinjiang-concurrent-message-mock-validation-20260726T202200Z/` 与 `runs/jinjiang-concurrent-message-mock-validation-20260726T203300Z/` 的文件集合与全部 SHA-256 完全一致，证明当前 mocked concurrent runtime 可 deterministic 重放。
- 新增 `scripts/run_concurrent_message_validation.py` 作为 1,000-user / 30-batch / 3-message additive runtime 的固定 offline/mock 入口。它使用 mocked `openai_compatible` provider、requested `gpt-5.4-mini`、observed `gpt-5.4-mini-2026-03-17`、timeout `30s`、adapter retry `2`，但保持 `sampling_status=validation_run`、`production_deploy_eligible=false`，不授权 live Provider 或 deploy。
- 本次 Validation artifact 从 persisted source rows 闭合出 1,000 sample users、3,000 eligible user-message pairs、每条 message 600 exposures、总 1,800 exposures、1,200 message-level below-delivery-capacity pairs、1,800 Primary attempts、1,800 Shadow attempts 和 3,600 terminal rows；pair terminal coverage 与 paired Decision coverage 都为 `1.0`。
- 三条 queue 的 Batch 0 共享同一组 20 位 seeds；30 个 batch 的每条 message 都维持 20 个 selected users。mock Provider 全部返回 `ignore`，因此 committed primary feedback 为 0；报告如实保留这一结果，没有补造传播效果或 Formal live evidence。
- 对同一 persisted tuple 连续执行 `rebuild_concurrent_message_report(...)` 前后，`report.html` 的 SHA-256 保持稳定；22 个 manifest artifacts 与 17 个下载项全部闭合。
- 使用伪造 Formal `abm-report-release-contract-v4` candidate 对该 Validation artifact 做本地 preflight，validator 直接在本地拒绝：`v4 validation sampling_status mismatch: expected 'persisted_seed_first_formal_run', got 'validation_run'`。拒绝发生在任何 SSH、upload 或 remote mutation 之前。

## 验收输出

- Validation run：`runs/jinjiang-concurrent-message-mock-validation-20260726T201800Z/`
- Deterministic rerun A：`runs/jinjiang-concurrent-message-mock-validation-20260726T202200Z/`
- Deterministic rerun B（计时回放）：`runs/jinjiang-concurrent-message-mock-validation-20260726T203300Z/`
- 自包含报告：`report.html`
- Report SHA-256：`b1ab0b0c50ac1df61739869ceb4cb39f41986d8acc6e1e76bc404d05f8be4790`
- Artifact manifest SHA-256：`3c9b6bba52f9cd1a2953c8917678338ae10ddc6e903f428095697b014a3de21a`
- Report payload SHA-256：`dc6a753807f131a8b4be3d0797b76ba4e1ed8b4b27548e445abe40349a136eb9`
- Validation evidence SHA-256：`7d4c6f720f362402b51f026d0bf309f0ea2d66a556671925bbfac6d77a08499c`
- Campaign diagnostics SHA-256：`c89d201b9892f844d155725e655d18f72f005b53653ef1b701f5b520137a30c5`
- Decision trace SHA-256：`95d1b02431b308acbb98d429fa22f2b3fefcc106b2c637b973b9259c372029cb`
- Users JSON SHA-256：`8cce51f9981a99206e396af9f8857000954ce827a0ce8168270a786b6bbe5d3e`
- Seed-First sample audit SHA-256：`dd3326d521dec92977b6aff2b422d33b7ad9da4613b1305d7bf5050163b79442`

## 合同闭合

- `sample_manifest.json` 实际为 1,000 行，`user_id` 唯一值也是 1,000。
- `concurrent_runtime_pairs.csv` 实际为 1,800 行，`pair_id` 唯一值 1,800，`(message_id, user_id)` 唯一键 1,800；允许同一用户跨 message 重复，但不允许同一 `user × message` 再次曝光。
- `concurrent_runtime_terminal_rows.csv` 实际为 3,600 行；每个 `pair_id` 恰好两条 terminal rows，且变体集合严格等于 `{primary, shadow}`。
- `concurrent_validation.json` 的 `counts` 闭合为：
  - `sample_users=1000`
  - `eligible_user_message_pairs=3000`
  - `actual_exposures=1800`
  - `primary_attempted=1800`、`primary_successes=1800`、`primary_failures=0`
  - `shadow_attempted=1800`、`shadow_successes=1800`、`shadow_failures=0`
  - `terminal_rows=3600`
  - `pair_terminal_coverage=1.0`
  - `paired_decision_coverage=1.0`
- `per_message` 闭合为三条 message 各 600 exposures、各 400 below-delivery-capacity pairs，总计 1,200 below-capacity pairs。
- `campaign_exposure_coverage` 如实记录 `{0: 0, 1: 434, 2: 332, 3: 234}`，总和为 1,000；`distinct_exposed_users=1000`，说明当前 mocked ranking 在三条 queue 上最终覆盖了全部 sample users。

## Batch 与 feedback 语义

- `concurrent_runtime_steps.json` 的 Batch 0 三条 message `seed_user_ids` 集合完全相同，shared seed union size 为 20。
- 30 个 batch 的每条 message 都保持 `selected_user_ids` 数量为 20，满足 queue capacity contract。
- 本次 mocked Provider 全部返回 `ignore`，因此 `campaign_feedback_committed=true` 的 pair 数量为 0，`deduplicated_committed_primary_positive_user_ids` 在每个 batch 都为空。这个结果被原样保留，没有为了展示“传播效果”而补造 committed feedback。
- `primary_only_committed_feedback` 检查通过：若 future run 出现 committed feedback，只允许来自 Primary positive actions；当前 run 因 0 committed pairs 而平凡成立。

## Prompt / Provider accounting

- Prompt tokens 固定为：
  - Primary：`jinjiang-concurrent-message-primary-prompt-v1`
  - Shadow：`jinjiang-concurrent-message-demographic-shadow-prompt-v1`
- Persisted payload 与 runtime 都记录 `configuration_profile=production`、`sample_size=1000`、`horizon=30`、`delivery_capacity=20`，但 `sampling_status=validation_run`、`production_deploy_eligible=false`。
- Primary accounting：1,800 invocations、1,800 responses、1,800 successful decisions、`observed_model_counts={'gpt-5.4-mini-2026-03-17': 1800}`、`total_usage=23400`。
- Shadow accounting：1,800 invocations、1,800 responses、1,800 successful decisions、`observed_model_counts={'gpt-5.4-mini-2026-03-17': 1800}`、`total_usage=19800`。
- Total accounting：3,600 invocations、3,600 responses、3,600 successful decisions、`total_usage=43200`。
- 这些 usage 数字是 mocked response envelopes 的安全 accounting，不是 live cost 或真实账单；文档不把它们表述为 Formal provider 计费证据。

## Report rebuild 与下载闭合

- `rebuild_concurrent_message_report(runs/jinjiang-concurrent-message-mock-validation-20260726T201800Z)` 前后的 `report.html` SHA-256 都是 `b1ab0b0c50ac1df61739869ceb4cb39f41986d8acc6e1e76bc404d05f8be4790`。
- Validation run 的 22 个 manifest artifacts 与 17 个 report download targets 全部存在；deterministic rerun A/B 的文件集合与每个同名文件的 SHA-256 全部一致，没有 path escape、extra file 或 hash drift。
- `report.html` 明确包含 `Validation only`、`validation-only`、`non-causal` 与 `Safe downloads` 标记；本 Ticket 没有把 fixture、cache-only、rule-based 或 mocked artifact 伪装成 Formal release 页面。

## v4 rejection preflight

本地生成一个仅用于 preflight 的伪 Formal `abm-report-release-contract-v4` candidate，指向上述 Validation run，再执行：

```bash
python scripts/validate_abm_report_release.py \
  --repo-root . \
  --contract tmp/issue-98-concurrent-validation-rejected-v4.json \
  --source-dir runs/jinjiang-concurrent-message-mock-validation-20260726T201800Z
```

结果：

```text
release validation error: v4 validation sampling_status mismatch: expected 'persisted_seed_first_formal_run', got 'validation_run'
```

该拒绝是纯本地 validator 结果；本 Ticket 没有调用 `scripts/deploy_abm_report.sh`、没有 SSH、没有 upload，也没有 remote mutation。

## 对 #99 的 operational handoff

- 保持 `ready-for-agent`。本 Ticket 只解除 #98 blocker，不改写 #99 正文中的 Provider / model / retry / budget / output / deployment contract。
- 已验证当前 runtime 可以持久化 #99 所需的 requested/observed split：requested `gpt-5.4-mini` 与 observed `gpt-5.4-mini-2026-03-17` 不再被 runtime 错误拒绝；exact observed-model qualification 仍由 `abm-report-release-contract-v4` validator 在 Formal path 上强制执行。
- #99 的 human-gated Formal Run 仍必须显式提供：selected actor-authorized `openai_compatible`、requested exact `gpt-5.4-mini`、唯一 allowed observed `gpt-5.4-mini-2026-03-17`、adapter retry `2`、SDK retry `0`、最多 3,600 logical Decisions、最多 10,800 network request invocations、独立 `runs/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-<UTC>/` output 和显式 release ID。
- canonical endpoint 仍是 `https://abm.q1ngyuan.top/`；禁止用 Validation / mock / rule-based / cache-only / synthetic fixture 替换线上版本。
- Formal path 的顺序保持不变：live preflight -> one-shot persisted Formal run -> same-run v4 contract -> local validator -> candidate deployment -> `/healthz` and host checks -> atomic `current` switch -> public acceptance -> rollback on failure。

## 验证命令与结果

```bash
. .venv/bin/activate
python scripts/run_concurrent_message_validation.py \
  --dataset-dir data/processed/jinjiang_douyin/jinjiang-final-caption-hashtag-comments-profiles-latent-v1-validation-20260705T000000Z \
  --output-dir runs/jinjiang-concurrent-message-mock-validation-20260726T201800Z
python scripts/run_concurrent_message_validation.py \
  --dataset-dir data/processed/jinjiang_douyin/jinjiang-final-caption-hashtag-comments-profiles-latent-v1-validation-20260705T000000Z \
  --output-dir runs/jinjiang-concurrent-message-mock-validation-20260726T202200Z
/usr/bin/time -p bash -lc '. .venv/bin/activate
python scripts/run_concurrent_message_validation.py \
  --dataset-dir data/processed/jinjiang_douyin/jinjiang-final-caption-hashtag-comments-profiles-latent-v1-validation-20260705T000000Z \
  --output-dir runs/jinjiang-concurrent-message-mock-validation-20260726T203300Z'
python -m py_compile $(find src tests scripts -name '*.py' -print)
pytest -q
ruff check src/llm_abm_sim/data_sources tests scripts
npx pyright --pythonpath .venv/bin/python src/llm_abm_sim/data_sources tests scripts
CONCURRENT_MESSAGE_REPORT_DIR=runs/jinjiang-concurrent-message-mock-validation-20260726T201800Z \
  npx playwright test tests/playwright/concurrent-message-report.spec.ts
```

- Validation run A：通过。
- Validation run B：通过；与 run A 的文件集合和全部 SHA-256 完全一致。
- 计时回放 run C：通过；`real 6.34s`、`user 6.13s`、`sys 0.18s`，且与 run A 的文件集合和全部 SHA-256 完全一致。
- Python compile：通过。
- 完整 pytest：`472 passed, 2 deselected in 163.37s (0:02:43)`。
- Ruff：通过。
- Pyright：使用 `npx pyright --pythonpath .venv/bin/python ...` 后 `0 errors, 0 warnings, 0 informations`。当前环境没有全局 `pyright` 可执行文件，因此没有把缺失 CLI 误记为通过。
- Concurrent Message Playwright：`1 passed (8.0s)`；覆盖 `1440x1000` 与 `390x844` 视口、五组 UI、trace drawer、downloads 和无水平溢出/布局重叠。

## 边界与风险

- 本 Ticket 没有执行真实 Provider、没有读取 `.env`、没有打印 API key / token / headers、没有读取 `data/raw/`、没有 SSH、没有 candidate deployment，也没有 public endpoint 切换。
- 当前 evidence 只证明 offline/mock contract、report rebuild、validator gate 和 operational handoff 已闭合；不代表 live provider、真实成本、网络重试、公网 `/healthz`、candidate host state 或 canonical endpoint 已验收。
- `campaign_feedback_committed` 为 0 是 mocked `ignore` 结果，不应外推为 live Formal run 的预期行为；#99 必须原样接受任何真实 action/reason 分布，不得因“结果不好看”而筛选或重跑。
- 36,400-user full Decision experiment 仍不在本 Ticket 范围内。
