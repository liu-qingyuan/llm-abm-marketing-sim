# Final Research 离线基线

Status: Architecture Note

本说明记录锦江 Final Research Report Run 的离线准备 Module。它只负责在真实 processed 数据上建立可复现的研究输入与推荐 diagnostic，不执行 LLM 决策，也不代表完整的最终研究运行或网页报告。

## 公开 Interface

```python
FinalResearchRunner(config: FinalResearchConfig, decision_adapter: LLMDecisionAdapter)
    .run_and_write(output_dir) -> Path
```

`FinalResearchRunner` 是公开深 Module。调用方只提供经过校验的配置、现有 `LLMDecisionAdapter` 接缝上的适配器和输出目录；数据读取、Target Holdout、holdout-safe 画像投影、抽样、seed 选择、静态评分和 artifact 写出均由 Module 内部完成。

离线基线保留 `decision_adapter` 参数以稳定后续 Final Research Interface，但本阶段不得调用它。artifact manifest 会显式记录 `decision_adapter_calls=0` 和 `live_api_triggered=false`。

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
- 推荐主权重之和必须为 `1.0`；默认公式为 `0.70 * base_network_score + 0.30 * historical_tag_affinity`。
- 相同 processed dataset、配置和随机种子必须产生一致的样本、seeds、分数和 diagnostic。

## 离线 artifacts

`run_and_write` 返回输出目录，具体相对路径记录在 `artifact_manifest.json`。离线基线写出：

- 配置和目标视频 snapshot；
- CSV/JSON sample manifest；
- holdout-safe reference 与 seed audit；
- 36,400 用户规模的离线分数 CSV 和聚合摘要；
- Top20 holdout diagnostic；
- artifact manifest。

这些产物不包含 `.env`、凭证、headers、raw provider payload、raw Douyin payload或旧 demo preset 字段。
