# 锦江 Target Delivery Ranking 正式研究验收记录

日期：2026-07-15（Asia/Singapore）

Status: Final Live Research Validation

## 摘要

本记录对应 GitHub issue #43，发布由 #39、#40、#42 验收的 Target Delivery Ranking Interface 的真实 Provider 正式运行结果。运行只读取权威 final latent-v1 processed variant；36,400 个用户全部进行离线评分，真实 Provider 只处理最终 1,000 用户研究样本中实际获得目标视频曝光的 600 人。

| 项目 | 结果 |
|---|---|
| Run directory | `runs/jinjiang-prompt-v2-final-research-20260714T180251Z/` |
| 运行时间 | 2026-07-14 18:02:51 至 19:01:43 UTC；2026-07-15 02:02:51 至 03:01:43 Asia/Singapore |
| Runtime elapsed | 3,532.60 秒 |
| Target video | `7328592728139353363` |
| Processed users offline scored | 36,400 |
| Base Sample / Final Sample | 1,000 / 1,000 个唯一真实用户 |
| Seed users / Network Cohort | 20 / 13 |
| Ordinary replacements | 13 |
| Recommendation batches | 30 |
| Target exposures / Adapter tasks | 600 / 600 |
| Provider success / failure | 600 / 0 |
| Actions | `like`: 258；`ignore`: 342；`comment`: 0；`share`: 0 |
| Below delivery capacity | 400 |
| Batches with paired Top20 change | 8 / 30 |
| Top20 holdout intersection | 0；仅作为 diagnostic，不代表生产准确率 |

## 配置口径

- 输入：`data/processed/jinjiang_douyin/jinjiang-final-caption-hashtag-comments-profiles-latent-v1-validation-20260705T000000Z/`。
- `research_model=target_delivery_ranking_v2`、`sample_size=1000`、`horizon=30`、`random_seed=20260713`。
- Batch 0 强制曝光 20 个 seed union；Batch 1-29 每轮对 remaining eligible users 全局重排并固定选择 Top20。
- 主排序公式：`0.50 * base_network_relevance + 0.30 * engaged_neighbor_signal + 0.20 * historical_tag_affinity`。
- Provider：`openai_compatible`，复用 Codex-compatible runtime metadata，model 为 `gpt-5.6-sol`，`wire_api=responses`。
- Live Provider Gate：`LLM_ABM_RUN_LIVE_LLM=1`，`require_live_env=true`。
- Prompt：`jinjiang-green-marketing-prompt-v2`；ranking、network 和 Target Holdout evidence 不进入 Prompt。
- 失败策略：`fail_closed_action=raise`，初始调用后最多指数退避重试五次，退避基数 `1.0` 秒，单次 timeout `30.0` 秒。
- 本次 600 个任务全部成功返回结构化 Decision，因此 `runtime_provider_failures.csv` 只有表头。

## 样本与网络结果

- Base Sample 为 1,000 人；seed union 在 network augmentation 前固定为 20 人。
- Historical Set 中 13 个 seed 直接邻居构成 Network Cohort；13 人均为新增用户，并固定替换 13 个普通 non-seed 用户，最终样本仍为 1,000 人。
- 动态 `engaged_neighbor_signal` 在 Batch 1-4 激活，共出现 30 条 positive-signal candidate evidence，其中 23 条进入实际 Top20 投放。
- 实际最大 `engaged_neighbor_signal=0.666666666667`。
- paired full/no-network shadow ranking 在 8 个批次改变至少一个 Top20 选择，证明本次运行同时存在 Recommendation Signal Inclusion 和 Observed Recommendation Signal Effect。
- sensitivity 和 paired ablation 完全复用冻结证据，`diagnostic_decision_adapter_calls=0`，没有增加 Provider 调用或推进第二套用户状态。

这些结果只说明预声明网络信号在本次仿真样本与权重下改变了排序投放，不构成真实抖音平台因果效果、生产推荐准确率或真实用户传播结论。

## Artifact 清单

`artifact_manifest.json` 使用 `final-research-ranking-runtime-v2`，登记 24 个交付物；加上 manifest 自身，run 目录共有 25 个文件，约 37 MB。

- 页面与下载：`report.html`、`final_research_report_payload.json`、`final_research_users.csv`、`final_research_users.json`。
- 输入与样本审计：`config_snapshot.json`、`target_video_snapshot.json`、`sample_manifest.csv`、`sample_manifest.json`、`network_augmented_sample_audit.json`、`holdout_safe_audit.json`。
- 离线评分与 holdout diagnostic：`offline_scores.csv`、`offline_score_summary.json`、`top20_holdout_diagnostic.json`。
- 排名 runtime：`ranking_runtime_steps.csv`、`ranking_runtime_candidates.csv`、`ranking_runtime_outcomes.csv`、`ranking_runtime_summary.json`。
- Provider runtime：`runtime_decisions.csv`、`runtime_actions.csv`、`runtime_provider_failures.csv`。
- 排名诊断：`ranking_diagnostics.json`、`ranking_diagnostics_summary.json`、`ranking_ablation_diagnostics.csv`、`ranking_weight_sensitivity.csv`。

结构化 reconciliation 通过 25 项断言：

- sample manifest、用户 CSV、用户 JSON、report payload 和 runtime outcomes 均为 1,000 个唯一用户；
- 30 个 batch 的 exposure 和 decision 合计均为 600；
- success decisions、actions 和实际 exposure 完全一致；
- `like/comment/share/ignore/provider_failed/below_delivery_capacity` 与 summary、用户导出和页面计数一致；
- ablation 20,320 行、sensitivity 90 行与 diagnostics summary 一致；
- manifest 登记的 24 个文件全部存在，run 目录不含 symlink。

## 网页验收与真实数据回归

mocked fixture 的 Playwright 测试通过后，使用 `playwright-cli` 对正式 `report.html` 做了独立桌面和移动验收：

- 1440×1000：无页面横向溢出、文本溢出或指定同组元素重叠；首屏展示真实 TargetVideo、600 exposures、600 decisions、action/failure/below-capacity 漏斗，并露出下一节。
- 390×844：真实长 caption 与 5 个 hashtags 初次使下一节顶部位于 `852px`，暴露 mocked fixture 未覆盖的 8px 首屏回归。
- 新增长标题 + 5 hashtags Playwright regression；修复前稳定收到 `851.8125 >= 844`，修复后通过。
- mobile hero H1 在 `max-width:700px` 下使用固定 `2.35rem`；正式页面下一节顶部为 `831px`，无横向溢出、文本溢出或检测到的重叠。
- 6 张聚合图表均有有效布局高度；8 个下载链接全部返回 HTTP 200。
- 用户搜索可缩小到 1 / 1,000；`below_delivery_capacity`、`ignore`、Network Cohort、seed 筛选分别得到 400、342、13、20 行。
- 用户详情展示直接观测、历史行为、派生代理、合成标签、样本与 ranking、曝光与 provider、最终 action 七组证据；未曝光用户展示完整 29 轮 ranking history。

截图证据保存在本地 `test-results/final-research-43/ranking-report-desktop.png` 和 `test-results/final-research-43/ranking-report-mobile.png`，不作为用户级 artifact 提交。

修复后通过公开 `rebuild_final_research_report(run_dir)` 只重建派生 HTML，没有重新评分、运行仿真或调用 Provider。`final_research_users.csv`、`final_research_users.json`、`artifact_manifest.json`、`ranking_runtime_summary.json` 和 report payload 的 SHA-256 保持不变；只有 `report.html` 从 `490df709...` 更新为 `56f97c7e...`。

## 验证证据

```bash
.venv/bin/python -m py_compile $(find src tests scripts -name '*.py' -print)
.venv/bin/ruff check src tests scripts
.venv/bin/mypy --python-version 3.12 src/llm_abm_sim
.venv/bin/pytest -q tests/unit/test_final_research_ranking.py tests/unit/test_ranking_diagnostics.py tests/integration/test_final_research_runner.py
.venv/bin/pytest -q
PATH="$PWD/.venv/bin:$PATH" npx playwright test
env -u ALL_PROXY -u HTTP_PROXY -u HTTPS_PROXY -u all_proxy -u http_proxy -u https_proxy \
  NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
  LLM_ABM_RUN_LIVE_LLM=1 .venv/bin/pytest -q -m live_llm -rs
```

结果：

- `py_compile`、`ruff` 和 `mypy` 通过；mypy 检查 41 个 source files。
- ranking focused tests：`39 passed`。
- 默认完整测试：`258 passed, 2 deselected`，默认不触发 live API。
- ranking Playwright：`3 passed`；全量 Playwright：`10 passed`。
- 显式 live smoke：`1 passed, 259 deselected`。
- 正式 run artifact safety scan：25 个文件未发现 credential、headers、raw Prompt、raw Provider payload 或 legacy forbidden terms。

## 研究限制

- 600 次 Target exposure 是固定 Delivery Capacity 下的仿真投放，不是真实抖音曝光日志。
- `like`/`ignore` 是真实 Provider 基于受控 Prompt 生成的仿真 Decision，不是真实用户行为。
- Network Cohort 是传播识别 cohort，不是代表性随机样本；13 个网络用户是本数据与 seed union 的实际结果，不是永久常量。
- paired ablation 是同批冻结证据上的 shadow ranking，不是第二条完整反事实 ABM trajectory。
- Top20 holdout intersection 为 0，只反映当前正样本稀疏和缺少真实曝光分母，不构成生产推荐质量结论。
- Provider 没有视频媒体输入，只读取允许的 caption、hashtags、processed profile、代理指标和合成实验标签。
- run 目录包含 processed/runtime 用户级明细，保持本地且由 `.gitignore` 排除；Git 只提交本聚合验收说明和回归修复。

## 安全边界

- 本次正式运行触发真实 LLM Provider API，没有触发 TikHub 或其他数据采集 API。
- 没有读取 `data/raw/`，没有打印或提交 `.env`、API key、Codex auth token、headers、raw Provider request/response 或 raw Douyin payload。
- Provider Adapter 只在运行时内存中解析最小 credential；持久化 metadata 只保留 allowlisted、脱敏字段。

