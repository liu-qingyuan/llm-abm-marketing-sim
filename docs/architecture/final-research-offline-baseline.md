# Final Research 离线基线

Status: Architecture Note

本说明记录锦江 Final Research Report Run 的 Target Delivery Ranking 离线准备 Module。它只负责在真实 processed 数据上建立可复现的 Network-Augmented Research Sample 与推荐 diagnostic，不执行 LLM 决策，也不代表完整的 30 批次运行或网页报告。

## 公开 Interface

```python
FinalResearchRunner(config: FinalResearchConfig, decision_adapter: LLMDecisionAdapter)
    .run_and_write(output_dir) -> Path
```

`FinalResearchRunner` 是公开深 Module。调用方只提供经过校验的配置、现有 `LLMDecisionAdapter` 接缝上的适配器和输出目录；数据读取、Target Holdout、holdout-safe 画像投影、Base Sample、seed 选择、Network Cohort、静态评分和 artifact 写出均由 Module 内部完成。

离线基线保留 `decision_adapter` 参数以稳定后续 Final Research Interface，但本阶段不得调用它。artifact manifest 会显式记录 `decision_adapter_calls=0` 和 `live_api_triggered=false`。

## Network-Augmented Research Sample

离线 v2 先完全复用既有 `source_challenge_name` 配额、去重、固定随机种子和稳定补齐规则形成 Base Sample。global influence top10 与 holdout-safe local influence top10 的 seed union 只从 Base Sample 选择，后续增强不重新选 seed。

Network Cohort 是这些 seeds 在目标 source scope Historical Set 评论派生图中的唯一直接邻居，排除 seed 本身并限制为 processed 用户。已经位于 Base Sample 的 cohort 用户原位保留；样本外 cohort 用户加入最终样本，并使用独立稳定随机种子移除等量普通 non-seed、non-cohort Base Sample 用户。最终样本必须保持配置的样本数和唯一 `user_id`，无法同时保留全部 seeds 与 cohort 时失败关闭。

`network_augmented_sample_audit.json` 使用独立 schema，记录 Base Sample、seed union、Network Cohort、实际新增用户、被替换普通用户、最终样本，以及 Base/最终两套 source-scope 分布。Network Cohort 是传播识别设计，不代表总体随机样本。

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
- Base Sample、seed、Network Cohort、替换用户和最终样本 audit；
- holdout-safe reference 与 seed audit；
- 全量用户离线分数 CSV 和聚合摘要，包括 target-scope weighted degree 与 base network relevance；
- Top20 holdout diagnostic；
- artifact manifest。

这些产物不包含 `.env`、凭证、headers、raw provider payload、raw Douyin payload或旧 demo preset 字段。

离线 v2 manifest 使用 `final-research-offline-v2`。现有 `provider.enabled=true` 概率抽签路径在新的 Target Delivery Ranking runtime 落地前继续保留 `final-research-runtime-v1`、Base Sample 和 max-normalized network score；旧 run 目录及其报告不被覆盖或重新解释。
