# 锦江用户字段血缘与逐用户追溯离线验证记录

统计周期：2026-07-20；口径更新时间：2026-07-20

## 核心成果

- `FieldLineageTraceModule` 已覆盖报告中全部非 runtime 用户字段。字段全集从本次 report lineage 动态计算，不把数量写成 Implementation 常量。
- 当前 1,000 用户 Seed-First mock Validation Run 动态得到 41 个 catalog 字段和 41,000 条 User Field Trace：Direct Observed Profile Field 7 个、Historical Behavioral Evidence 4 个、Derived Proxy Metric 13 个、Synthetic Experiment Label 17 个。
- value status audit 为 `present=38,623`、`empty=2,377`、`unavailable=0`。空 profile、空历史标签与实际数值 0 保持不同语义，没有创建或回填 `interest_tags`。
- 直接观测字段定位同 run 的 `sample_manifest.json`；历史网络度定位 `offline_scores.csv`；用户级 ranking proxy 使用 `user_id + time_step` 定位 `ranking_runtime_candidates.csv`；标签与代理聚合输入定位 `field_source_records.json`。
- `activity_score`、`global_influence_score` 和 `local_influence_score` 的输入与结果同在 `sample_manifest.json`，因此定位该 sample record；`base_network_relevance` 则定位 `field_source_records.json` 中持久化的 `target_scope_weighted_degree` 与 holdout-safe P95 reference，可按 method id 复算。
- rebuild 会把直接观测、sample-scope proxy 与 synthetic label 逐字段对照 `sample_manifest.json`，把动态代理对照 `user_id + time_step` candidate，并从 payload traces 重算 coverage audit；source value、derived input 或 audit 被篡改时会在发布前失败。
- latent 字段逐用户记录 `latent_attribute_spec_id`、`latent_attribute_method`、`latent_attribute_seed` 和实际值，并始终标记为 Synthetic Experiment Label。
- 本次使用本地 `RuleBasedDecisionAdapter`，没有构建 provider Prompt。Prompt audit 如实记录 `not_rendered=7,200`、`not_exposed=5,200`、`empty_omitted=600`、`not_allowlisted=28,000`，没有把 mock 决策伪装成 provider Prompt inclusion。

## 验证输出

- Run directory：`runs/jinjiang-field-lineage-mock-validation-20260720T111651Z/`
- 报告：`report.html`
- Field Lineage Catalog：`field_lineage_catalog.json`
- User Field Trace：`user_field_trace.json`
- Field source records：`field_source_records.json`
- Report SHA-256：`ac762cf9e4e12338881384ea3e6cc49ea7cf24362ab8c74bb3fa4b4dbbf63055`
- Catalog SHA-256：`044b631a37f733b2f07df56fc7e4a26159c0aa419d5b387598d4a30fda709763`
- Trace SHA-256：`77e399077f7f065aacb4f1aba5edafb8d393fa4c647b141725c70284ab61c051`
- Source records SHA-256：`4a2ed2b0eb6d4f4e3ebaf32d490fb040e5bfa47a589f53b58792782116ed03a9`

该 run 使用 `sampling_method=seed_first_research_sample_v1`、`sampling_status=validation_run`，实际角色为 20 位 seed、60 位 network cohort 和 920 位 ordinary user；600 次本地 deterministic decision 后有 400 位用户保持 `below_delivery_capacity`。报告执行 deterministic rebuild 后 SHA-256 不变。

## 验证命令

```bash
. .venv/bin/activate
pytest -q tests/unit/test_field_lineage_trace.py
pytest -q tests/integration/test_final_research_runner.py::test_target_delivery_ranking_v4_persists_interest_and_historical_field_traces
pytest -q tests/integration/test_final_research_runner.py::test_target_delivery_ranking_report_rebuild_is_deterministic
pytest -q tests/integration/test_final_research_runner.py::test_target_delivery_ranking_report_rebuild_rejects_invalid_evidence_before_publish
mypy --python-version 3.12 src
npx playwright test tests/playwright/final-research-ranking-report.spec.ts --grep "user drawer expands v4 field traces"
```

当前数据 audit 使用旧验证 run 的 config snapshot 中 `FinalResearchConfig` 声明字段重建配置，并写入新的独立 run directory；没有改写旧 run。

最终验证结果：完整 Python test suite 为 `286 passed, 2 deselected`，`mypy --python-version 3.12 src` 检查 43 个 source files 无问题；完整 ranking report Playwright 文件为 `16 passed, 1 skipped`，跳过项仅为未设置 `FINAL_RESEARCH_FORMAL_RUN_DIR` 的既有 formal run 验收。1280×800 与 1440×1000 全页截图已检查，无横向溢出或 incoherent overlap。

## 边界与风险

- 本次没有读取 `.env`、`data/raw` 或 raw Provider Payload，没有调用 TikHub、Douyin 或真实 LLM provider；`artifact_manifest.json` 记录 `live_api_triggered=false`。
- 对 trace、payload 和 HTML 的敏感 token 扫描没有发现 `raw_prompt`、`raw_provider_response`、测试 secret 或 cookie。
- 自包含 HTML 包含 41,000 条 trace，文件约 37 MB；本 Ticket 验证桌面交互，后续 #69 应继续验证 1,000 用户报告的浏览器加载性能与下载体验。
- 当前 run 是 mock Validation Run，不是 live formal run；真实 provider 正式运行仍需用户单独授权。
