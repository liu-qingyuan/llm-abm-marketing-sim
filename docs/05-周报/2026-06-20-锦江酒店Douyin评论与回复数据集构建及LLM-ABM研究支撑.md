# 本周工作进展报告（2026.06.15-2026.06.21）：锦江酒店 Douyin 评论与回复数据集构建

## 小结

> 本周统计周期：`2026.06.15-2026.06.21`；核心数据口径更新时间：`2026.06.21`。

本周完成的是 LLM-ABM 研究前置的数据基础建设和验证工作。核心成果包括：

- 明确从 4 个高评论候选视频修正为 caption hashtag 覆盖视频集合，使样本不再局限于少数异常高互动视频；
- 复用既有 metadata-only source run，没有重新跑 top10 metadata 全量采集；
- 完成旧口径 4,427 个目标视频的一级评论与 replies 采集；
- 完成二次口径修正：剔除 `#锦江宾馆`，跳过 `#临空锦江宾馆`，将 `#锦江都城酒店吉安` 列为补充目标；
- 在授权 live API 后补齐 top12 `#锦江都城酒店吉安`：metadata 201 个视频、top-level comments 222 条、replies 29 条；
- 派生出完整新口径 4,212 个目标视频、50,640 条 comments + replies，并补齐 47,624 条用户互动边；
- 明确禁用 profiles，避免不必要的隐私与成本风险；
- 为后续互动网络、文本分析和 ABM 传播模拟提供了可追溯的数据基础。

当前完整新口径数据集位于：

```text
data/processed/jinjiang_douyin/jinjiang-caption-hashtag-comments-excluding-binguan-adding-jian-derived-20260621T025127Z/
```

因此，本周工作可以概括为：**完成了锦江酒店 Douyin 评论与回复数据集的阶段性构建、研究对象边界二次修正、授权 top12 补采与完整新口径派生，为后续 LLM-ABM 营销传播模拟打下了更清晰的数据基础；下一步应基于已生成的 interaction network 与 text corpus 开展质量审计、文本分析和 ABM 初始化设计。**
