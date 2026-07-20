# 锦江 Runtime、Decision 与 diagnostics 字段追溯离线验证记录

统计周期：2026-07-20；口径更新时间：2026-07-20

## 核心成果

- 当前 1,000 用户 Seed-First mock Validation Run 动态得到 114 个 Field Lineage Catalog 字段和 75,000 条 `user_id`-keyed User Field Trace；字段数来自 report lineage，不是 Implementation 常量。
- 75 个逐用户字段覆盖画像、ranking candidate、Decision、provider outcome、传播反馈与 diagnostics。ranking locator 使用 `user_id + time_step`，Decision 使用 `user_id + video_id + time_step`，provider failure、outcome 和 diagnostics 分别定位同 run 的 persisted artifacts。
- catalog provenance 计数为 Direct Observed 15、Historical Behavioral Evidence 4、Derived Proxy 20、Synthetic Experiment Label 20、Runtime Simulation Result 55；trace value status 为 `present=68,823`、`empty=4,577`、`unavailable=1,600`。
- Prompt audit 为 `not_allowlisted=62,000`、`not_exposed=5,200`、`not_rendered=7,200`、`empty_omitted=600`。ranking、网络和 diagnostics evidence 没有进入 Decision Adapter Prompt。
- 本次 `RuleBasedDecisionAdapter` 的 600 次 Decision 全部为 `ignore`，trace 如实记录 `no_propagation_action=600`；400 位 `below_delivery_capacity` 用户记录 `not_exposed_no_action`，没有从方法投影补造 runtime 结果。`like/comment/share` 的下一批直接邻居信号由 deterministic integration fixture 验证。
- paired ablation、weight sensitivity、Historical Top20 和 summary 全部定位本次 run 的 diagnostics artifacts；rebuild 会校验 runtime、diagnostics 与复合 locator 后再发布报告。

## 验证输出

- Run directory：`runs/jinjiang-runtime-trace-mock-validation-20260720T120534Z/`
- 报告：`report.html`
- Report SHA-256：`a0bbc16e2b69f35c4c0bc82b0c768c4a4d1f5f7cdde49f55ad0417d4e787787b`
- Catalog SHA-256：`8d6d4edf4f06b140cb77eae3ecd3f4e9aba2c4b8e51e30059a1c6c9acc0d3097`
- Trace SHA-256：`f1ec5f8849d19d2029c3faf3615c6afccae617608bd9867ff3168c463b14a690`
- Sampling：`seed_first_research_sample_v1` / `validation_run`
- 角色：20 seed、60 network cohort、920 ordinary；600 次本地 deterministic Decision，400 位 `below_delivery_capacity`

报告约 61 MB，trace artifact 约 77 MB。deterministic rebuild 后 Report SHA-256 不变。

## 验证命令

```bash
. .venv/bin/activate
pytest -q tests/unit/test_field_lineage_trace.py
pytest -q tests/integration/test_final_research_runner.py
mypy --python-version 3.12 src/llm_abm_sim
npx playwright test tests/playwright/final-research-ranking-report.spec.ts --grep "user drawer expands v4 field traces"
python -m py_compile $(find src tests scripts -name '*.py' -print)
ruff check src/llm_abm_sim/data_sources tests scripts src/llm_abm_sim
```

最终结果：完整 Python suite 为 `287 passed, 2 deselected`；ranking report Playwright 为 `16 passed, 1 skipped`，跳过项仅为未设置 `FINAL_RESEARCH_FORMAL_RUN_DIR` 的既有 formal run 验收；ruff、Python 编译和 mypy 均通过。桌面与 laptop 截图已检查，无横向溢出或 incoherent overlap。

## 边界与风险

- 本次没有读取 `.env`、`data/raw`、密钥、原始 Prompt 或 raw Provider Payload，没有调用 TikHub、Douyin 或真实 LLM provider；`live_api_triggered=false`。
- trace、payload 和 HTML 的敏感 token 扫描无匹配。
- 当前 run 是离线 Validation Run，不是 live formal run。真实 provider 正式运行仍需用户单独授权。
- 完整报告体积增加，后续 #69 继续验证 1,000 用户桌面加载、搜索和下载体验。
