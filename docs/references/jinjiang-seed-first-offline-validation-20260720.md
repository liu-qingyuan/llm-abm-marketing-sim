# 锦江 Seed-First Research Sample 离线验证记录

统计周期：2026-07-20；口径更新时间：2026-07-20

## 核心成果

- `FinalResearchRunner.run_and_write(output_dir)` 已使用 `seed_first_research_sample_v1` 从 36,400 位合格 processed users 形成独立 deterministic mock Validation Run。
- 只读 audit 实际得到 20 位 seeds、60 位 Seed Neighbor Cohort 和 920 位 ordinary users；最终样本为 1,000 位唯一真实用户。这些数量来自当前数据与算法，不是 Implementation 常量。
- audit 同时记录 383 位 Primary Video Source Scope 并列用户和 17 位 deterministic fallback 用户，全部 tie-break、quota 与 fallback 可复核。
- `seed_first_sample_audit.json`、`sample_manifest.json`、`ranking_runtime_outcomes.csv` 与 `final_research_report_payload.json` 的 1,000 位成员完全一致；三个 sample role 互斥并覆盖全部成员。
- 当前 20 / 60 / 920 样本已重新执行 Batch 0、后续 29 轮 Global Reranking、600 次 deterministic mock Decision、30 批 ranking diagnostics 和 paired ablation；400 位用户保持 `below_delivery_capacity`，未复用旧正式 run 的 13 位邻居、action counts 或 rank delta。
- paired ablation 在同批冻结 evidence 下得到 6 个网络改变 Top20 的批次；这是本次 mock Validation Run 的诊断结果，不是 live provider 或真实平台因果证据。

## 验证输出

- Run directory：`runs/jinjiang-seed-first-mock-validation-20260720T090552Z/`
- Sample audit：`seed_first_sample_audit.json`
- Artifact manifest：`artifact_manifest.json`
- 离线报告：`report.html`
- 当前 run 使用 `sampling_status=validation_run`、`decision_adapter_calls=600`、`live_api_triggered=false`；Decision Adapter 是仓库内确定性 `RuleBasedDecisionAdapter`。

## 验证命令

```bash
.venv/bin/pytest -q tests/integration/test_final_research_runner.py tests/unit/test_final_research_ranking.py tests/unit/test_ranking_diagnostics.py tests/unit/test_research_explanation_catalog.py
jq '{seed:.roles.counts.seed, network_cohort:.roles.counts.network_cohort, ordinary:.roles.counts.ordinary, final:.final_sample.count}' runs/jinjiang-seed-first-mock-validation-20260720T090552Z/seed_first_sample_audit.json
jq '{sampling_status, decision_adapter_calls, counts, live_api_triggered}' runs/jinjiang-seed-first-mock-validation-20260720T090552Z/artifact_manifest.json
```

## 边界与风险

- 本次没有读取 `.env`、`data/raw` 或 raw Provider Payload，没有调用 TikHub、Douyin 或真实 LLM provider。
- 本次执行 deterministic mock sample/runtime/audit/report；它不是新的 live formal run，600 个结构化 Decision 都不是 provider-backed Decision。
- 旧 Historical Network-Augmented Run 及其 artifacts 保持原样；新的 live provider 正式运行仍需用户单独授权并写入独立目录。
- Seed Neighbor Cohort 是传播识别设计，不代表总体随机样本；Primary Scope fallback 不提高样本代表性。
