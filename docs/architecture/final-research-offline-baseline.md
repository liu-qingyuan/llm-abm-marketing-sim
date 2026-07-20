# Final Research 离线基线

Status: Architecture Note

本说明记录锦江 Final Research Report Run 的 Target Delivery Ranking 离线准备 Module。它只负责在真实 processed 数据上建立可复现的 Seed-First Research Sample 与推荐 diagnostic，不执行 LLM 决策，也不代表完整的 30 批次 live provider 正式运行。

## 公开 Interface

```python
FinalResearchRunner(config: FinalResearchConfig, decision_adapter: LLMDecisionAdapter)
    .run_and_write(output_dir) -> Path
```

`FinalResearchRunner` 是公开深 Module。调用方只提供经过校验的配置、现有 `LLMDecisionAdapter` 接缝上的适配器和输出目录；数据读取、Target Holdout、holdout-safe 画像投影、Seed-First sample selection、静态评分和 artifact 写出均由 Module 内部完成。

离线基线保留 `decision_adapter` 参数以稳定后续 Final Research Interface，但本阶段不得调用它。artifact manifest 会显式记录 `decision_adapter_calls=0` 和 `live_api_triggered=false`。

`FinalResearchConfig.research_model` 显式选择研究语义。默认 `target_delivery_ranking_v2` 产生本说明的离线基线；历史概率模型必须显式使用 `probability_v1`。`provider.enabled` 只控制 Decision Adapter 是否执行，不再隐式切换采样或评分模型。Target Delivery Ranking provider runtime 在后续 Ticket 落地前失败关闭。

## Seed-First Research Sample

`target_delivery_ranking_v2` 使用 `seed_first_research_sample_v1`。内部 sample Module 先从全部合格 processed users 形成 Global Influence Proxy Top10 与 Local Influence Proxy Top10 的实际去重并集，再纳入这些 seeds 在目标 source scope Historical Set 评论派生图中的直接邻居。邻居超过剩余容量时按与 seeds 的历史互动总边权降序选择，并按 `user_id` 打破并列。

每位用户按 Historical Set 中评论和回复次数最多的 Primary Video Source Scope 归组；并列时按 `source_challenge_rank` 和 scope name 稳定选择。seeds 与 Seed Neighbor Cohort 先占用 scope quota，普通真实用户按 scope 固定随机补足；scope 不足或预选角色造成 overage 时使用独立稳定 fallback。`seed`、`network_cohort` 和 `ordinary` 互斥并覆盖最终样本。

`seed_first_sample_audit.json` 使用 `seed-first-sample-audit-v1`，记录 method/status、eligible pool、两个 Top10、去重 seed union、邻居边权与容量、scope assignment/quota/tie/fallback、最终成员和互斥角色。Seed Neighbor Cohort 是传播识别设计，不代表总体随机样本。历史 `network_augmented_sample_audit.json` 只用于旧 run rebuild，不迁移或覆盖。

## 三个核心对象

- `TargetVideo`：唯一进入 runtime 的真实目标营销视频，只保留 caption、hashtags、URL、作者和 source scope 等非答案字段。
- `ResearchUser`：真实 Observed Profile Attributes、原有 Virtual Experiment Labels，以及从 Historical Set 重算的 holdout-safe activity/local influence 投影。
- `PlatformRecommendationModel`：使用历史评论网络和历史视频 hashtag 亲和度计算目标视频的静态推荐分数。

其他真实视频构成 Video Catalog 的 Historical Set，只提供历史信号，不是 runtime 中并行竞争的视频对象。

## Holdout 边界

```text
Historical Set = 全部非目标视频及其评论/回复
Holdout Set = 目标视频的真实评论/回复答案
```

实现从 Historical Set 重新构建评论派生用户图、评论数、回复数、评论获赞和 P95 reference。目标视频的互动行与视频级聚合热度不进入画像投影、用户抽样、seed 选择或推荐评分，只在评分完成后用于 Top20 diagnostic。

未观测到用户与目标视频互动，只表示数据中没有发现该组合的互动记录；不能解释为用户获得真实曝光后选择 `ignore`。

## 稳定运行语义

- `horizon=30` 表示 30 个固定推荐批次，不表示自然日。
- 每个用户在完整 Final Research Report Run 中最多获得一次目标视频推荐机会。
- 当前离线基线只计算静态分数，不执行 30 批次抽签或 LLM 决策。
- `base_network_relevance = min(1, log1p(weighted_degree) / log1p(P95_weighted_degree))`；degree 和 P95 都只来自目标 source scope Historical Set，零 degree 或零 P95 稳定返回 0。
- 离线排序使用新主模型的静态部分：`0.50 * base_network_relevance + 0.20 * historical_tag_affinity`。预留的 `0.30 * engaged_neighbor_signal` 只在后续逐批 runtime 中产生。
- 相同 processed dataset、配置和随机种子必须产生一致的样本、seeds、分数和 diagnostic。

## 离线 artifacts

`run_and_write` 返回输出目录，具体相对路径记录在 `artifact_manifest.json`。离线基线写出：

- 配置和目标视频 snapshot；
- 最终样本 CSV/JSON manifest；
- full-pool seed、Seed Neighbor Cohort、scope quota/fallback、互斥角色和最终样本 audit；
- holdout-safe reference 与 seed audit；
- 全量用户离线分数 CSV 和聚合摘要，包括 target-scope weighted degree 与 base network relevance；
- Top20 holdout diagnostic；
- artifact manifest。

这些产物不包含 `.env`、凭证、headers、raw provider payload、raw Douyin payload或旧 demo preset 字段。

离线 v2 manifest 使用 `final-research-offline-v2`，并显式记录 `sampling_method`、`sampling_status=validation_run` 和 `sample_role_counts`。显式 `research_model=probability_v1` 的历史概率抽签路径继续保留 `final-research-runtime-v1`、原抽样方法和 max-normalized `base_network_score`；该版本的 `base_network_relevance` 列留空，也不声明 log-P95 audit。旧 run 目录及其报告不被覆盖或重新解释。
