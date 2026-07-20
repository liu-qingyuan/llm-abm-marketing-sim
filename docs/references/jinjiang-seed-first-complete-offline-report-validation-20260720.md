# 锦江 Seed-First 完整离线报告验收记录

统计周期：2026-07-20；口径更新时间：2026-07-20

## 核心成果

- 最终验收对象固定为 `runs/jinjiang-runtime-trace-mock-validation-20260720T130020Z/`，不按目录时间或名称猜测最新 run。
- 该 run 使用 `sampling_method=seed_first_research_sample_v1`、`sampling_status=validation_run` 和本地 deterministic `RuleBasedDecisionAdapter`；`live_api_triggered=false`，不是 live formal run。
- 当前 processed latent-v1 dataset 的 36,400 位合格用户经只读 audit 形成 1,000 位唯一用户：20 位 seed、60 位 network cohort、920 位 ordinary user。sample audit、sample manifest、runtime outcomes、report payload 和 User Field Trace 的成员集合完全一致，Batch 0 恰好覆盖 20 位 seeds。
- 30 个 Batch 共持久化 600 次 Recommendation Opportunity 和 600 次 mock Decision；400 位用户的实际 runtime 状态为 `below_delivery_capacity`。本次 adapter 的 600 次 Decision 均为 `ignore`，报告没有补造传播效果。
- Field Lineage Catalog 动态得到 114 个唯一可见字段，超过父 spec 记录的 111 字段审计基线；实现和验收均未把字段数量写成常量。每位用户形成 75 条 trace，其中 72 条 locator 包含 `user_id`，3 条引用同源共享 diagnostics，共 75,000 条 trace。
- Mechanism Explanation Mode 使用 Predeclared Ranking Weights `0.50 / 0.30 / 0.20`；Run Evidence Mode 读取同一 persisted run 的 method、weights、Decision 与 diagnostics。
- 27 个 manifest artifacts 和 11 个 report download targets 全部存在、无 symlink；source locator 均为不含 `..` 的相对路径。report-only rebuild 后除 `report.html` 外的 persisted artifacts 逐字节不变，report SHA-256 保持稳定。

## 验收输出

- Run directory：`runs/jinjiang-runtime-trace-mock-validation-20260720T130020Z/`
- 自包含报告：`report.html`
- Report SHA-256：`3541e405583aac0f8eaac8aa90c28023603028c08824614fd7de0b75532558ad`
- Artifact manifest SHA-256：`39c35c88cb19d4e5938c12377777b3d5ec1b2811daf8950e570c073fe6a19335`
- Ranking payload SHA-256：`a7135a91c14631e77054c5fe5e2078a39748820922bda524e2730ef2b49c56cb`
- Seed-First sample audit SHA-256：`f95f6dc269f3ac60c03220d3f26babd2f3bca1b45a7e2c1c73410c9582c9995e`
- Field Lineage Catalog SHA-256：`e5c8eb2896b1486a89fedbde62f14b56975583db4f318f02293d337265f356a5`
- User Field Trace SHA-256：`02b290587a6fca16c7fe5cf614bef7cdc87708c93810c9e7b2698d209fe8a3bb`
- Field source records SHA-256：`4a2ed2b0eb6d4f4e3ebaf32d490fb040e5bfa47a589f53b58792782116ed03a9`

历史 v3 rebuild 验收对象为 `runs/jinjiang-prompt-v2-final-research-20260714T180251Z/`：

- Payload schema：`final-research-ranking-report-payload-v3`
- Report SHA-256：`65f96f8e9d418e3ddd564d3c0a42d62a1e817903a1c660c77d83d53eda593fb6`
- Payload SHA-256：`c953986f262fd3335bfd17baf23b0961876fef62230a538b77f10e2eba05ffd5`
- Manifest SHA-256：`17808281b384bb0d744d0749312065a27b45d49ec280244bb80276055224e30e`
- canonical rebuild 后连续两次公开 rebuild 的全部 25 个文件 hash 不变。

## 验证结果

```bash
.venv/bin/python -m py_compile $(find src tests -name '*.py' -print)
.venv/bin/pytest -q
.venv/bin/ruff check src/llm_abm_sim/data_sources tests scripts src/llm_abm_sim
.venv/bin/mypy --python-version 3.12 src/llm_abm_sim
FINAL_RESEARCH_FORMAL_RUN_DIR=runs/jinjiang-runtime-trace-mock-validation-20260720T130020Z \
  npx playwright test tests/playwright/final-research-ranking-report.spec.ts
```

- Python compile：通过。
- Python suite：`288 passed, 2 deselected`。
- Ruff：通过。
- Mypy：43 个 source files 通过。
- Ranking report Playwright：`17 passed`。验收覆盖 1,000 用户搜索、result/role/scope/seed/cohort 与 provenance 过滤、字段展开、source locator、全部下载链接、键盘关闭与焦点恢复；1280×800 和 1440×1000 视口无横向溢出、文字溢出、结构重叠或 console error。
- 完整 Python suite 覆盖 ranking payload v3 的历史 rebuild 和 v4 的 deterministic rebuild、evidence tamper rejection、symlink rejection 与 artifact 安全合同。
- 本地历史 v3 formal run 通过两次连续 `rebuild_final_research_report` 验收；没有运行仿真或调用 Decision Adapter，payload 保持 v3，当前 25 个 artifacts 在两次 rebuild 前后逐字节一致。
- processed dataset 只读 audit：`users.csv`、`profiles.csv`、`abm_user_profiles.csv` 均为 36,400 行和 36,400 个唯一 `user_id`，三者集合一致；36,400 位用户的 latent contract 字段完整，Seed-First eligible pool 同为 36,400。

## 边界与风险

- 本次未执行新的仿真或数据采集，复用 #68 已持久化并在当前 `HEAD` 验证的完整 offline/mock run；没有触发真实 LLM、TikHub、Douyin 或其他 live API。
- 未读取或打印 `.env`、密钥、`data/raw`、原始 Prompt 或 raw Provider Payload，也未写入秘密。
- 历史 Network-Augmented formal run 的 users、sample、runtime、diagnostics、ablation、sensitivity 与 manifest evidence hashes 保持 2026-07-15 验收值。首次使用当前代码 rebuild 时重新序列化派生 v3 payload/report；没有迁移 schema、样本或 runtime evidence，后续连续 rebuild 已证明确定性。
- 自包含报告约 61 MB，payload 约 90 MB，trace 约 77 MB；桌面交互已通过，但本 Ticket 不承诺低性能设备或移动端体验。
- 当前成果只代表 Seed-First Validation Run。新的 live provider formal run 仍需用户单独授权，并写入独立目录。
