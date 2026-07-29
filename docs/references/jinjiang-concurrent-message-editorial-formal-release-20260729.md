# 锦江 Concurrent Message Editorial Formal Presentation 发布与验收记录

统计周期：2026-07-29；口径更新时间：2026-07-29T13:44:25Z；成功 release atomic `current` switch：2026-07-29T13:42:32.890059498Z

## 发布结论

- 已从明确固定的原始 Formal evidence 派生新的 immutable Editorial Presentation；这次是 operational presentation release exception，不是新的 Formal Run。
- 没有调用 Provider、TikHub、Douyin 或 profile API；没有重跑、重试、过滤或改写原始 3,600 个 persisted Decisions。
- canonical endpoint：`https://abm.q1ngyuan.top/`
- 第二次 candidate 发布成功，公网 acceptance 通过；canonical `current` 已原子切换到 Editorial release。

## Release Identity

| 项目 | 路径 / 值 | SHA-256 |
| --- | --- | --- |
| 原始 Formal source | `runs/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z/` | `report.html`: `740f55a30bc4183a75724592496c6b6aa809a85ab385ccf96bc53093cb49a76d` |
| 原始 Formal contract | `configs/deployments/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z.json` | `122cfd6cd42b39f91c8a5a6343ca834fbc4d323d3332d8de23b4502d974d85d7` |
| 当前 rollback destination | `runs/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z-two-mode-20260728T112653Z/` | `report.html`: `ba006c5e18d091a77e8eebd73e86287209ccaf2571023d1114e35fd64872f556` |
| rollback v4 contract | `configs/deployments/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z-two-mode-20260728T112653Z.json` | `782d30c2be8105d44cfd9be1d15094d901379aabf01b187163f0ad5eb015512f` |
| Editorial destination | `runs/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z-editorial-20260729T131839Z/` | `report.html`: `1d1e1ead3691aa275c74ff723a79960019c42fd58f179d8b74619f0a0b218ea9` |
| Editorial v4 contract | `configs/deployments/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z-editorial-20260729T131839Z.json` | `fe2cacfc6d420aa586db485f89a3321137fb90c9bcba0dc8dda1d91ccbaa8fa9` |
| Editorial release ID | `jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z-editorial-20260729T134133Z` | deployment identity |

The Editorial contract `source_directory` points exactly to the Editorial destination. Its `artifact_sha256` records the destination report hash `1d1e1e...` and manifest hash `309ca67a3d3f5214b462ee9333a41cc157ca6952f2c0ef21abf214daa45b969b`.

## Derivation Closure

- The destination was created only through `rebuild_concurrent_message_report(source, destination_dir=destination)`.
- Source and destination both contain 23 regular files. Only `report.html` and `artifact_manifest.json` differ; the other 21 approved artifacts are byte-identical.
- The destination passed typed artifact closure, v4 production validation, exact in-place deterministic rebuild, manifest/hash reconciliation and source immutability checks.
- The original Formal source, original contract, two-mode rollback destination and rollback contract remained byte-identical throughout the release.
- The checked-in Editorial renderer golden was updated with the navigation-state fix: `tests/fixtures/concurrent_message_renderer/editorial_default.html.gz` now hashes to `1d1e1ead...`.

## Local Validation

The final candidate passed:

```bash
.venv/bin/python -m py_compile $(find src tests scripts -name '*.py' -print)
.venv/bin/pytest -q
.venv/bin/ruff check src tests scripts
npx --yes pyright --pythonpath .venv/bin/python src/llm_abm_sim/data_sources tests scripts
PATH="$PWD/.venv/bin:$PATH" npx playwright test
.venv/bin/python scripts/validate_abm_report_release.py \
  --repo-root . \
  --contract configs/deployments/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z-editorial-20260729T131839Z.json \
  --source-dir runs/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z-editorial-20260729T131839Z \
  --require-formal-production
```

Results: `pytest` reported `507 passed, 2 deselected`; Ruff passed; Pyright reported `0 errors, 0 warnings, 0 informations`; full Playwright reported `35 passed, 2 skipped` (the skipped test requires an explicit public URL). A local HTTP candidate run of the deployed Editorial acceptance helper passed `1 passed`.

The artifact safety scan found no forbidden terms outside the existing human-readable report notes; no credentials, raw Prompt, raw Provider request/response, authentication headers or raw payload was read into release evidence.

## Candidate and Public Evidence

- Deployment host: `q1ngyuan.top`.
- Remote root: `/opt/llm-abm-marketing-sim-report`.
- The first candidate release ID `jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z-editorial-20260729T131839Z` was uploaded at `2026-07-29T13:32:43Z` (remote `report.html` mtime). Its public acceptance used the old two-mode root assertion and failed to recognize `editorial-report`. The deploy transaction automatically restored the existing two-mode rollback release; the remote journal records the rollback compose/current restore window at `2026-07-29T13:33:11Z`–`2026-07-29T13:33:16Z`, and the pre-retry readback confirmed report hash `ba006c5e...`. Canonical stayed at that hash.
- The deployed acceptance helper was updated to cover the Editorial root and its actual contract: default `zh-CN` mechanism mode, English switch, five anchors, persisted Formal run metrics, trace filters and drawer, grouped downloads, 1440×1000 and 390×844 no-overflow behavior, and no console/page errors.
- The second candidate release ID `jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z-editorial-20260729T134133Z` was uploaded at `2026-07-29T13:42:01Z`; the remote `current` symlink was atomically switched at `2026-07-29T13:42:32.890059498Z`, followed by the host Nginx reload at `2026-07-29T13:42:38Z`. It passed candidate health, read-only container checks, uploaded report hash, host guards, Nginx validation and the deployed Playwright acceptance (`1 passed`).
- Remote readback after atomic switch: `current` points exactly to `/opt/llm-abm-marketing-sim-report/releases/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z-editorial-20260729T134133Z`.
- Remote `report.html` hash: `1d1e1ead3691aa275c74ff723a79960019c42fd58f179d8b74619f0a0b218ea9`.
- Public `X-Artifact-SHA256` header and public `report.html` body hash: `1d1e1ead3691aa275c74ff723a79960019c42fd58f179d8b74619f0a0b218ea9`.
- Public `artifact_manifest.json` body hash: `309ca67a3d3f5214b462ee9333a41cc157ca6952f2c0ef21abf214daa45b969b`.
- Public `/healthz` returned `ok`; HEAD checks passed for `artifact_manifest.json`, `concurrent_message_report_payload.json`, `concurrent_message_users.json`, `concurrent_validation.json`, `concurrent_campaign_diagnostics.json` and `seed_first_sample_audit.json`.
- No rollback was required for the successful second candidate. The previous two-mode release remains available as the managed rollback target.

## Boundary and Authorization

This release uses the already authorized Formal evidence tuple and does not infer new research results from the Editorial presentation. The v4 contract remains `formal_research`, `persisted_seed_first_formal_run`, `production` and `production_deploy_eligible=true`; presentation derivation changes only the report and manifest bytes. No `.env`, API key, credential, raw Prompt, raw Provider response, secret, request header or raw payload was read, printed or persisted. The eight Mermaid Gate diagrams remain in issue #123; the release lifecycle, contract ownership and rollback sequence were not changed.
