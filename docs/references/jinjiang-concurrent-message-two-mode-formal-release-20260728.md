# 锦江 Concurrent Message 双模式 Formal Presentation Release

统计周期：2026-07-28；口径更新时间：2026-07-28T12:04:21Z

## 核心成果

- 从明确固定的 persisted Formal source run 派生新的 immutable two-mode presentation destination；没有扫描 latest，没有重跑 Provider，也没有改写原始 3,600 个 Decisions。
- 原始 Formal source：`runs/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z/`
- 原始 Formal contract：`configs/deployments/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z.json`
- 新 presentation destination：`runs/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z-two-mode-20260728T112653Z/`
- 新 v4 contract：`configs/deployments/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z-two-mode-20260728T112653Z.json`
- 实际成功部署 Release ID：`jinjiang-concurrent-message-formal-formal-v1-gpt-5.4-mini-20260727T023746Z-two-mode-20260728T112653Z`
- canonical endpoint：`https://abm.q1ngyuan.top/`

Destination 含 23 个文件。除 `report.html` 与 `artifact_manifest.json` 外，其余 21 个 approved artifacts 与 source 逐文件 byte-identical；source 目录、原始 contract 和原始 release evidence 的 SHA-256 保持不变。

## Hash 与 Contract

| 项目 | SHA-256 |
| --- | --- |
| 原始 source `report.html` | `740f55a30bc4183a75724592496c6b6aa809a85ab385ccf96bc53093cb49a76d` |
| 原始 source `artifact_manifest.json` | `bfc793bb7322edabe6fb5eb4cce7e6990ca008a8cb0310e19507b9c14839063d` |
| 新 destination `report.html` | `ba006c5e18d091a77e8eebd73e86287209ccaf2571023d1114e35fd64872f556` |
| 新 destination `artifact_manifest.json` | `cac6fca8e94c55518d902853dd91f82071b90c7cbd6b640043e13fbf32e6734f` |
| 新 v4 contract | `782d30c2be8105d44cfd9be1d15094d901379aabf01b187163f0ad5eb015512` |

新 contract 的 `source_directory` 精确指向 destination，`artifact_sha256` 覆盖 manifest 声明的 22 个 artifacts 加 manifest 自身，共 23 项。Local v4 validator 通过：`formal_research`、`persisted_seed_first_formal_run`、`live_provider` evidence tuple、report hash `ba006c...`。

## 本地验收

- `python -m py_compile $(find src tests scripts -name '*.py' -print)`：通过。
- `pytest -q`：`488 passed, 2 deselected`。
- `ruff check src tests scripts`：通过。
- `npx --yes pyright --pythonpath .venv/bin/python src/llm_abm_sim/data_sources tests scripts`：`0 errors, 0 warnings, 0 informations`。
- `npx playwright test tests/playwright/concurrent-message-report.spec.ts`：`3 passed`；覆盖 1440x1000、1600x1000、390x844、两个 modes、五段 anchors、分页/filter、trace drawer、keyboard/hash/focus、visual snapshots、overflow 和 console/page errors。
- deterministic `rebuild_concurrent_message_report(destination)`：通过；report 和 manifest hash 均保持不变。
- source immutability check：原始 Formal source 23 个文件全部匹配原始 contract hash。
- artifact safety scan：22 个 persisted non-report artifacts 通过；report 仅保留现有 human-readable `notes` 免责声明中的 `headers` 词，不含 raw provider/header 字段、credential、secret token 或 raw request/response。

## Candidate 与公网验收

- Deploy script 在首条 SSH 前对只读 snapshot 重新执行 v4 Formal validation；没有调用 live Provider、TikHub、Douyin 或 profile API。
- Candidate container 使用 read-only Nginx volume；health check、host checks、Nginx config test、artifact hash 和 uploaded report hash 通过。
- 第一次 candidate 的公网 acceptance 因 deployed test 未先切换到默认 mechanism mode 对应的 run-evidence panel 而失败；deploy script 自动 rollback 到原始 Release ID `jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z`。原始 source、原始 contract 和 canonical serving state 未被破坏。
- 修复 deployed acceptance helper 后，第二次 candidate 使用上方实际 Release ID 完成 atomic `current` 切换；公网 acceptance：`1 passed`。
- 公网 acceptance 覆盖 1440x1000 与 390x844，默认 mechanism mode、五个 anchors、run-evidence sections、downloads、首条 trace/detail drawer、无页面级 overflow、无 console/page errors。
- Remote `current` readback 指向实际 Release ID；`/healthz` 通过。
- Response header `X-Artifact-SHA256`、public `report.html` body hash 均为 `ba006c...`；public `artifact_manifest.json` body hash 为 `cac6fc...`。
- `artifact_manifest.json`、`concurrent_message_report_payload.json`、`concurrent_message_users.json`、`concurrent_validation.json`、`concurrent_campaign_diagnostics.json` 和 `seed_first_sample_audit.json` 的 public HEAD checks 全部通过。

## 边界与风险

- 本次没有读取、打印或写入 `.env`、API key、credentials、raw Prompt、raw Provider request/response、鉴权 headers 或 raw payload。
- 历史 Formal source 的 pre-pagination renderer 由内部 frozen adapter 精确恢复；Medium follow-up 是补充一个直接绑定正式 v4 report hash 的自动化回归 fixture，当前 operational validation 已覆盖该 hash。
- 实际 Release ID 是部署命令显式传入的合法唯一 ID；contract 的 `source_directory` 与 artifact hashes 是唯一 release validation identity，保持不变。
- 无最终 rollback；canonical 当前服务上述 two-mode presentation release，上一 release 保留在 managed `releases` 目录中。
