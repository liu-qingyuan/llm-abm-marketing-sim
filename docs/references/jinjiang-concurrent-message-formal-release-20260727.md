# 锦江 Concurrent Message Formal 发布与验收记录

统计周期：2026-07-27；口径更新时间：2026-07-27

## 核心成果

- 已用同一次 persisted source run 生成并固化 `abm-report-release-contract-v4` formal release contract。
- Persisted source run：`runs/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z/`
- Formal release contract：`configs/deployments/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z.json`
- Release ID：`jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z`
- Local validation 已通过，validator 识别为 `abm-report-release-contract-v4 | formal_research | runs/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z | seed_first_research_sample_v1 | persisted_seed_first_formal_run | live_provider`。
- 公网部署已完成，canonical endpoint `https://abm.q1ngyuan.top/` 现在服务 concurrent-message report。
- Deploy script 内置的 Playwright public acceptance 已通过：`1 passed (27.1s)`。
- 当前 release 保留完整 persisted counts：1,000 sample users、3,000 eligible pairs、1,800 exposures、3,600 terminal rows、1,800 Primary successes、1,800 Shadow successes、0 failures、100% pair terminal coverage 和 100% paired decision coverage。
- Provider accounting 保留为：3,603 invocations / 3,600 responses / 3,600 successful decisions；observed model 为 `gpt-5.4-mini-2026-03-17`。
- Action counts 原样保留为：`like=1513`、`ignore=208`、`comment=76`、`share=3`。

## 验证输出

- Report SHA-256：`740f55a30bc4183a75724592496c6b6aa809a85ab385ccf96bc53093cb49a76d`
- Artifact manifest SHA-256：`bfc793bb7322edabe6fb5eb4cce7e6990ca008a8cb0310e19507b9c14839063d`
- Release contract SHA-256：`122cfd6cd42b39f91c8a5a6343ca834fbc4d323d3332d8de23b4502d974d85d7`

## 验证命令

```bash
.venv/bin/python scripts/validate_abm_report_release.py \
  --repo-root . \
  --contract configs/deployments/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z.json \
  --source-dir runs/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z \
  --require-formal-production

ABM_DEPLOY_PYTHON=.venv/bin/python scripts/deploy_abm_report.sh \
  --contract configs/deployments/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z.json \
  --source-dir runs/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z \
  --release-id jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z
```

## 边界与风险

- 本次没有读取或打印 `.env`、API key、token、header 值、原始 Prompt 或 raw Provider response。
- 没有回退；部署脚本完成了候选检查、宿主检查、原子切换和公共验收。
- 这份记录只绑定上述单次 persisted run；若以后要重跑，必须重新生成独立 release contract 和 release ID。
