# 锦江 Final Research 真实 Provider 验收记录

日期：2026-07-13

## 摘要

本记录对应 GitHub issue #31，发布已经由 #28、#29、#30 验收的 Final Research Interface 的真实 Provider 运行结果。运行只读取 final latent-v1 processed variant，不读取 `data/raw/`，不修改源数据，不在 live 阶段改变架构、状态机、Decision Adapter contract 或报告合同。

| 项目 | 结果 |
|---|---|
| Run directory | `runs/jinjiang-prompt-v2-final-research-20260713T145200Z/` |
| 运行时间 | 2026-07-13 14:52 UTC / 22:52 Asia/Singapore |
| Runtime elapsed | 166.31 秒 |
| Target video | `7328592728139353363` |
| Processed users offline scored | 36,400 |
| Research sample | 1,000 个唯一真实用户 |
| Recommendation batches | 30 |
| Seed users | 20 |
| Target exposures / Provider decisions | 28 / 28 |
| Provider success / failure | 28 / 0 |
| Actions | `like`: 16；`ignore`: 12；`comment`: 0；`share`: 0 |
| Background impressions | 972 |
| Top20 holdout intersection | 0；仅作为 diagnostic，不代表生产准确率 |

## 配置口径

- 输入：`data/processed/jinjiang_douyin/jinjiang-final-caption-hashtag-comments-profiles-latent-v1-validation-20260705T000000Z/`。
- `sample_size=1000`、`horizon=30`、`random_seed=20260713`。
- 推荐公式：`0.70 * dynamic_network_score + 0.30 * historical_tag_affinity`。
- 直接邻居参与提升：`neighbor_boost=0.20`，动态网络分数封顶 `1.0`。
- Provider：`openai_compatible`，复用 Codex-compatible runtime metadata，`wire_api=responses`。
- Live Provider Gate：`LLM_ABM_RUN_LIVE_LLM=1`，`require_live_env=true`。
- Prompt：`jinjiang-green-marketing-prompt-v2`。
- 失败策略：`fail_closed_action=raise`，`max_retries=5`，指数退避基数 `1.0` 秒，单次 timeout `30.0` 秒。
- 36,400 用户全部只进行离线评分；真实 Provider 只处理 1,000 用户样本中实际曝光的 28 人。

## Artifact 清单

`artifact_manifest.json` 使用 `final-research-runtime-v1`，登记 19 个交付物：

- 页面与下载：`report.html`、`final_research_report_payload.json`、`final_research_users.csv`、`final_research_users.json`。
- 输入与审计：`config_snapshot.json`、`target_video_snapshot.json`、`sample_manifest.csv`、`sample_manifest.json`、`holdout_safe_audit.json`。
- 离线评分与诊断：`offline_scores.csv`、`offline_score_summary.json`、`top20_holdout_diagnostic.json`。
- Runtime：`runtime_steps.csv`、`runtime_exposures.csv`、`runtime_decisions.csv`、`runtime_actions.csv`、`runtime_background_events.csv`、`runtime_provider_failures.csv`、`runtime_summary.json`。

用户级 CSV 和 JSON 均覆盖完整 1,000 用户样本。浏览器验收确认页面展示 `TargetVideo`、`ResearchUser`、`PlatformRecommendationModel` 及推荐、曝光、决策关系；CSV、JSON 和 manifest 下载入口均返回 HTTP 200。

## 验证证据

```bash
.venv/bin/python -m py_compile $(find src tests scripts -name '*.py' -print)
.venv/bin/ruff check src/llm_abm_sim/data_sources tests scripts
.venv/bin/ruff check src tests scripts
npx pyright --pythonpath .venv/bin/python --pythonversion 3.12 src/llm_abm_sim/data_sources tests scripts
.venv/bin/mypy --python-version 3.12 src/llm_abm_sim
.venv/bin/pytest -q
PLAYWRIGHT_CHROMIUM_EXECUTABLE=<local-chromium> npx playwright test tests/playwright/final-research-report.spec.ts
env -u ALL_PROXY -u HTTP_PROXY -u HTTPS_PROXY \
  NO_PROXY=127.0.0.1,localhost LLM_ABM_RUN_LIVE_LLM=1 \
  .venv/bin/pytest -q -m live_llm -rs
```

结果：

- `py_compile`、两组 `ruff`、`pyright` 和 `mypy` 通过。
- 默认测试：`224 passed, 2 deselected`，默认不触发 live API。
- Final Research Playwright：桌面与移动 `2 passed`。
- 显式 live smoke：`1 passed, 225 deselected`，完成一次真实结构化 Provider 决策。
- 对最终 `report.html` 的浏览器复核：桌面与 390×844 移动首屏无重叠；1,000 行用户表加载完成；搜索筛选有效；三个下载入口 HTTP 200。
- Run artifact 安全扫描：未发现 credentials、headers、legacy demo preset、raw Provider payload 或 raw Douyin payload forbidden terms。

## 研究限制

- 28 次 Target exposure 是平台模型在固定 Recommendation Opportunity 下的仿真曝光，不是真实抖音曝光日志。
- `like`/`ignore` 是真实 Provider 基于受控 Prompt 生成的仿真 Decision，不是真实用户行为；未观测用户—视频组合不能解释为真实 `ignore`。
- Top20 holdout intersection 为 0，只说明当前稀疏历史信号的限制，不构成生产推荐准确率结论。
- 当前没有视频媒体文件，Provider 只读取真实 caption、hashtags、holdout-safe observed profile、允许的 latent 实验属性和简短网络上下文，不分析画面、音频或字幕。
- 本 run 目录包含 processed/runtime 用户级明细，保持本地且由 `.gitignore` 排除；Git 只提交本聚合验收说明，不提交用户明细或大型 CSV/JSON。

## 安全边界

- 本轮触发真实 LLM Provider API；没有触发 TikHub 或其他数据采集 API。
- 没有读取 `.env`，也没有人工检查 credential 内容；Provider Adapter 只在运行时内存中解析最小 Codex-compatible credential。
- 没有打印、写入或提交 API key、Codex auth token、headers、raw Provider request/response 或 raw Douyin payload。
- Provider metadata 只保留 allowlisted、脱敏的运行信息；run artifact 安全扫描结果为通过。
