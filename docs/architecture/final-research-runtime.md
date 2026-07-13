# Final Research 30 批次 Runtime

Status: Architecture Note

本说明记录锦江 Final Research 的 mocked/live provider 运行路径。它建立在[离线基线](final-research-offline-baseline.md)之上，复用同一个公开 Interface：

```python
FinalResearchRunner(config: FinalResearchConfig, decision_adapter: LLMDecisionAdapter)
    .run_and_write(output_dir) -> Path
```

`provider.enabled=false` 时仍只执行离线评分和 Holdout Diagnostic，不调用 Decision Adapter。`provider.enabled=true` 时配置必须使用 `horizon=30`、`fail_closed_action=raise` 和 `jinjiang-green-marketing-prompt-v2`，Runner 才进入固定批次 runtime。

## 固定批次与一次机会

- seed users 按稳定顺序在第 0 批次强制曝光。
- 其他样本用户使用固定随机种子打乱，再以 round-robin 方式分配到第 1 至 29 批次。
- 每个批次在批首冻结直接邻居状态、动态分数和 `PeerContext`，批末再统一提交该批次的曝光与参与；同批用户不会相互影响。
- 每个样本用户只生成一条 exposure event；非 seed 用户只抽签一次。
- `recommendation_score` 只与随机数比较，不参与用户排序。
- 抽签失败记录 `background_content`，不调用 Decision Adapter。

## 动态直接邻居反馈

平台使用 Historical Set 中 `source_challenge_name=锦江酒店` 的评论派生用户图：

```text
dynamic_network_score
= min(1.0, base_network_score + neighbor_boost * engaged_direct_neighbor_count)

recommendation_score
= network_weight * dynamic_network_score
 + tag_affinity_weight * historical_tag_affinity
```

只有 `like`、`comment`、`share` 会记录为参与并提升尚未处理的直接邻居；三种 action 的提升相同。`ignore`、背景内容和 `provider_failed` 不改变邻居参与状态。

## Decision Adapter 与失败语义

Runner 把 `TargetVideo` 投影为 `PostContent`，把当前直接邻居状态投影为 `PeerContext`，继续调用既有：

```python
decide(post, profile, peer_context, platform_context, time_step)
```

Provider Adapter 内部执行最多 5 次指数退避重试。`retry_backoff_seconds` 是退避基数，第 N 次重试前等待 `base * 2**N`；测试可以注入 sleeper 以避免真实等待。重试耗尽后 Adapter 抛出 `ProviderDecisionError`，Runner 只记录原始失败类型和安全 provider metadata，不保存异常消息或 raw payload，并继续处理后续用户。配置错误、live gate 错误和其他未标记的 Adapter 异常会终止 run，不会伪装成用户级 provider failure。

Holdout Set 在全部 runtime 完成后才揭示，仍只用于 diagnostic 和对照。

## Runtime Artifacts

启用 provider 的 run 在离线基线 artifacts 之外写出：

- `runtime_steps.csv`：30 个批次的分配、曝光、决策、参与、忽略和失败计数；
- `runtime_exposures.csv`：每个样本用户唯一的一次机会及其动态分数、抽签和结果；
- `runtime_decisions.csv`：成功返回的结构化决策；
- `runtime_actions.csv`：`like/comment/share/ignore` action 流；
- `runtime_background_events.csv`：未展示目标视频的背景内容占用；
- `runtime_provider_failures.csv`：重试耗尽后的用户级安全失败记录；
- `runtime_summary.json`：调度方法、公式、provider 安全 metadata 和聚合计数。

`artifact_manifest.json` 使用 `final-research-runtime-v1` 并登记以上路径。默认测试通过注入 mocked provider 运行，不读取凭证、不访问 `data/raw`、不触发 live API。

## Final Research 报告合同

`FinalResearchRunner.run_and_write` 在离线诊断和可选 runtime artifacts 完成后调用内部
`FinalResearchReportWriter`。该 Module 使用独立的 `FinalResearchReportPayload` 和显式
`UserReportRow` allowlist，不扩展通用 `ReportPayload`、`build_report_payload` 或全局
`safe_data` Interface。Writer 在 HTML、CSV 和 JSON 成功写出后最后写
`artifact_manifest.json`，避免 manifest 指向未完成的报告文件。

每个样本用户恰好生成一条报告记录。runtime 启用时，记录合并唯一 exposure、成功 decision
或 provider failure；runtime 未启用时显式使用 `runtime_not_run`。统一 `result_status` 区分：

- `like`、`comment`、`share`、`ignore`；
- `background_content`；
- `provider_failed`；
- 防御性状态 `missing_decision`；
- 离线状态 `runtime_not_run`。

报告 writer 新增并由 `artifact_manifest.json` 登记：

- `report.html`：可直接以 `file://` 打开的静态研究页面，内嵌 payload 和交互逻辑；
- `final_research_report_payload.json`：独立页面 payload、聚合图表数据和完整用户记录；
- `final_research_users.csv`：全部样本用户的 allowlisted 明细；
- `final_research_users.json`：与 CSV 同批、同字段的完整用户记录和互链信息。

HTML 提供搜索、result/source scope/seed 筛选、用户时间线、桌面与移动布局，以及 CSV、JSON、
payload 和 manifest 相对链接。CSV 每行和用户 JSON 顶层也记录回链路径。页面只展示 processed/runtime
允许字段，包括清洗后的 `interest_tags`、历史互动 hashtags、观测代理指标、latent 实验标签和
仿真结果；请求敏感材料、源站原始响应和旧 demo preset 字段不会进入 payload。
