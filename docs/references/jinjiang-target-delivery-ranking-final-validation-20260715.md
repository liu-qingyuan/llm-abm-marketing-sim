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

## 无需领域背景的报告重建验收（#49）

在 #46-#48 完成样本与字段目录、排序与网络证据、聚合图表与用户代理指标解释后，#49 使用同一公开 `rebuild_final_research_report(run_dir) -> Path` Seam 重建正式 run。重建前后分别对 run 目录全部 25 个文件计算 SHA-256；文件集合保持 25 / 25，新增和缺失均为 0。24 个机器 evidence artifacts 全部逐字节一致，唯一变化是允许更新的派生 `report.html`，从 `a3f374601b67...` 更新为 `9a58fffcff46...`。

后续术语一致性复核把 `Global influence（全局影响力代理）` 统一为 Prompt/PRD 使用的 `Global influence（全平台影响力代理）`，并再次通过同一 report-only rebuild Seam 更新正式 HTML。24 个机器 evidence artifacts 继续逐字节一致，`report.html` 从 `9a58fffcff46...` 更新为 `3158325c1034...`；该修复没有重新评分、运行仿真或调用 Provider。

关键不可变 evidence hashes：

| Artifact | SHA-256 |
|---|---|
| `artifact_manifest.json` | `17808281b384bb0d744d0749312065a27b45d49ec280244bb80276055224e30e` |
| `final_research_report_payload.json` | `6742de8b4773d107324a478dab059de0eb8c7a4355d82240d1f58470cffaea8a` |
| `final_research_users.csv` | `8ef7b9cb764bbf136c4c4e0dbd57eca0beacd9205c5cdc239b9d16b301aae249` |
| `final_research_users.json` | `4dd387d0973b0c77316c3950b4d0d3241eab95bad58b150f939f748f72d9a4fe` |
| `ranking_runtime_summary.json` | `63b36eee92e0b0872734d085b8b5c56e7ddaef9680dea13129d840f327b47943` |
| `ranking_diagnostics.json` | `093f0aa418a962c1094b926af844f0b0c8c4bef983fb3ffcd4f115874cf9b072` |
| `ranking_diagnostics_summary.json` | `daf41d52b6f620ba3910994c6c30aa3f056762e368a30a643bcb0106989e4ed0` |
| `ranking_ablation_diagnostics.csv` | `7d2286b1f38abf59e451b3c0b5e5b8480b52a34506b4c8a28cde48a86d667b36` |
| `ranking_weight_sensitivity.csv` | `10197a34e953c22a1f1109f053e3ed1b5dc3ea40b5da75601bf6a9e27914e476` |
| `report.html` | `3158325c10340059e7e8cbc2a120efd3ca69ccdd75db5f1fa08436b8fd1ea714` |

正式页面验收覆盖：

- 桌面 `1440x1000` 和移动 `390x844` 均通过解释区、字段搜索/筛选/详情、真实 score 示例、8 / 30 network effect、三组 sensitivity、Prompt isolation、六张图表 captions 和用户代理说明检查。
- 样本、字段、逐轮排序、网络证据、Prompt、聚合图表和用户追踪七个主要区段都在区段开头回答“是什么”“为什么需要”“怎么形成或计算”“本次结果怎么看”，并使用正式 run 的实际计数。
- 页面 chrome、核心对象、区段标签、表头、筛选器、动态 summary、状态、下载入口和研究限制中的保留英文 token 均提供相邻中文；普通限制文案改为中文解释。
- Field Lineage 默认表格同时显示 technical field、中文名、简要含义、provenance 和 usage；renderer-owned 静态与动态 label surface 通过自动未配对英文扫描，英文 source scope、failure type 和 decision source 值在展示层增加相邻中文上下文。
- `ResearchExplanationCatalog` 统一拥有七个 concept explanation 与六个 chart interpretation templates；renderer 只注入当前 run 聚合值，浏览器只消费已格式化 catalog document。
- Base / Final Sample、20 个 Seeds、13 个 Network Cohort、13 个 Ordinary replacements 和 source-scope 变化均有相邻中文解释。
- 1,000 用户搜索、状态/网络 cohort/seed 筛选、详情与 ranking history 保持可用；8 个下载目标全部存在。
- 页面无水平溢出、文字溢出、无意义重叠或隐藏的主要区段标题；正式桌面和移动截图保存在本地 `test-results/playwright/`，不提交用户级页面产物。

#49 验证结果：

- explanation/ranking-focused Python：`46 passed`。
- ranking Playwright（mock desktop/mobile、paired identities 和正式 run）：`4 passed`。
- 完整非 live Python：`265 passed, 2 deselected`。
- 完整 Playwright（含 ranking、legacy report、web console 和正式 run）：`11 passed`。
- `py_compile`、`ruff` 和 `mypy` 通过；mypy 检查 42 个 source files。

重建过程没有运行仿真或 Decision Adapter，Provider 调用数为 0；没有触发 live LLM、TikHub 或其他外部 API。没有读取 `.env`、`data/raw/`、raw Prompt 或 raw Provider payload，也没有提交 ignored 的正式 run 用户级 artifacts。新增解释只改善研究证据的可读性，不提高样本代表性、因果识别强度或代理指标效度；本记录下方的既有研究限制继续完整适用。

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
