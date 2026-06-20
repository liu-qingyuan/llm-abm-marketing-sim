# AGENTS.md — LLM-ABM 营销传播模拟项目指南

本文件用于指导后续 Codex / OMX / 子 Agent 在 `/Users/lqy/work/llm-abm-marketing-sim` 中工作。进入本仓库时，应优先遵守本文件，再结合上级 `/Users/lqy/work/AGENTS.md` 的通用规则。

## 0. 渐进式披露原则

不要一进入仓库就全量读取所有 docs、data 和 raw 产物。先按任务类型读取最小必要入口：

1. 仿真核心 / ABM runtime / Provider / Web：读本文件第 1 部分，再读 `docs/index.md` 中的架构和使用指南。
2. TikHub / Douyin / 锦江酒店数据收集：读本文件第 2 部分，再读 `docs/02-架构设计/douyin-data-collection-architecture.md` 和 `data/README.md`。
3. 锦江酒店研究口径：再读 `docs/04-开发验证/jinjiang-douyin-research-standard.md`。
4. top10 tag/challenge scope：再读 `docs/04-开发验证/jinjiang-douyin-existing-topic-distribution.md` 和 `configs/jinjiang_top10_non_generic_video_metadata_selection.json`。
5. 只有在需要实现或排错时，才读 `src/llm_abm_sim/data_sources/` 和对应测试。

---

# 1. 仿真核心部分

## 1.1 上游参考资料

本项目的架构、流程图、时序图和产品定位，主要参考 Obsidian 知识库目录：

```text
/Users/lqy/work/Obsidian_work/Obsidian_work/LLM-ABM营销传播模拟
```

关键参考文件：

```text
05-开发架构设计.md
06-开发流程与运行时序.md
01-项目框架说明.md
02-仿真流程与时序.md
03-指标与应用场景.md
```

如果代码实现、文档、测试与 Obsidian 参考资料产生冲突，应先检查这些参考文件，再判断是更新代码、更新项目文档，还是补充 ADR 说明偏离原因。

## 1.2 项目定位

本项目是：

> 使用 Agent-Based Modeling 模拟社交网络中帖子/营销内容扩散过程的轻量级仿真器。

核心不是通用自主 Agent 框架，而是在真实或模拟社交网络图上，让每个社交用户 Agent 基于以下三类信息做二元决策：

1. `post content`：帖子内容、话题、素材摘要；
2. `individual preference`：用户兴趣、品牌态度、活跃度、历史偏好；
3. `peer influence`：邻居曝光、邻居互动比例、关键邻居影响。

决策输出应保持结构化：

```text
engage: bool
probability: 0.0 到 1.0
reason: 简短理由
confidence: 0.0 到 1.0
action: like / comment / share / ignore
```

## 1.3 推荐架构方向

首版保持轻量：

```text
自定义 ABM Core + NetworkX + Pydantic + LLMDecisionAdapter + DecisionCache
```

推荐职责边界：

| 模块 | 职责 |
|---|---|
| `SimulationModel` | 仿真生命周期、时间步推进、调度顺序 |
| `PlatformEnvironment` | 曝光机制、平台规则、邻居可见状态、互动痕迹 |
| `SocialUserAgent` | 用户状态、观察上下文、调用决策边界 |
| `LLMDecisionAdapter` | 把帖子、偏好、同伴影响转成 `EngageDecision` |
| `DecisionCache` | 缓存 LLM/决策结果，降低成本并支持复现 |
| `ExperimentRunner` | 配置加载、数据集加载、批量实验、输出管理 |
| `MetricsCollector` | 事件流、时间序列指标、覆盖率、互动率、扩散深度/速度 |

## 1.4 仿真依赖策略

默认核心依赖：

- `pydantic`：Schema、配置和 LLM 输出校验；
- `networkx`：社交网络图、邻居查询、图指标；
- `pandas`：事件表、指标表、CSV/JSON 输出；
- `pytest`：本地确定性测试。

可选依赖：

- `openai`：后续 provider-backed LLM adapter；
- `mesa`：只有当自定义调度器不够用时再引入；
- `duckdb` / `sqlite`：后续持久化 DecisionCache 和实验记录；
- 图表库：等事件和指标 schema 稳定后再加入。

不要在首版核心中引入 LangChain、LangGraph 或 GenericAgent，除非新的需求明确需要复杂工具编排或图工作流。LLM 在本项目中应是 **decision function**，不是 simulator orchestrator。

## 1.5 实现原则

- 默认路径必须可以离线、无 API key 运行。
- 默认测试不能依赖真实 LLM provider。
- 先实现 rule-based deterministic baseline，再接 LLM adapter。
- 先建立 event-sourced runtime，再做复杂指标和可视化。
- 同一份 config + seed 应产生可复现结果。
- Engagement MVP 采用 absorbing 语义：用户一旦 engage，就持续作为后续扩散影响源。
- LLM provider 输出必须通过 Pydantic schema 校验。
- Secrets/API keys 不得写入仓库、日志、文档或测试快照。

---

# 2. 数据收集部分：TikHub / Douyin / 锦江酒店

## 2.1 必读入口

数据收集任务必须先按以下顺序渐进式读取：

1. `docs/02-架构设计/douyin-data-collection-architecture.md`：当前阶段化数据收集架构、Mermaid 架构图和时序图。
2. `data/README.md`：raw/processed/run 目录语义和安全边界。
3. `docs/04-开发验证/jinjiang-douyin-video-metadata-validation-20260617T035450Z.md`：当前 metadata-only 验证基线。
4. 若涉及研究标准，再读 `docs/04-开发验证/jinjiang-douyin-research-standard.md`。
5. 若涉及 top10 tag/challenge，再读 `docs/04-开发验证/jinjiang-douyin-existing-topic-distribution.md` 与 `configs/jinjiang_top10_non_generic_video_metadata_selection.json`。

## 2.2 当前数据收集架构

当前架构是阶段化 collector，不是一次性全量 crawler：

| 阶段 | 作用 | 默认优先级 |
|---|---|---|
| `challenge_index` | 从 tag/challenge 页面索引视频 ID 和摘要 metadata | 必须先做 |
| `video_metadata` | 形成可信视频级 metadata 分母，验证 caption/hashtags/source challenge | 当前主流程 |
| `comments` | 基于已验证视频分母采集一级评论 | 后续可选 |
| `replies` | 基于一级评论采集回复 | 后续可选，依赖 comments |
| `profiles` | 基于用户 ID 采集 profile /画像候选 | 后续可选 |

当前需求默认不继续大规模抓评论。必须先确保视频级数据完整：

- `video_id`
- `source_challenge_id`
- `source_challenge_name`
- `source_challenge_rank`
- `caption`
- `hashtags`
- `publish_time`
- `creator_user_id`
- `like_count/comment_count/share_count/collect_count`
- `raw_detail_status`
- `metadata_source`

## 2.3 当前推荐验证基线

推荐 metadata-only run：

```text
jinjiang-top10-non-generic-video-metadata-1y-20260617T035450Z
```

关键路径：

```text
data/raw/tikhub/douyin/jinjiang_hotel/jinjiang-top10-non-generic-video-metadata-1y-20260617T035450Z/
data/processed/jinjiang_douyin/jinjiang-top10-non-generic-video-metadata-1y-20260617T035450Z/
docs/04-开发验证/jinjiang-douyin-video-metadata-validation-20260617T035450Z.md
```

该 run 已验证：

| 指标 | 值 |
|---|---:|
| `indexed_video_ids` | 18 |
| `videos.csv` rows | 8 |
| `videos_with_caption` | 8 |
| `videos_with_hashtags` | 8 |
| `comments_collected` | false |
| `profiles_collected` | false |

## 2.4 旧 run 口径风险

旧 run `jinjiang-top10-tags-unbounded-1y-20260615T105143Z` 是问题样本：

- top10 话题页索引去重 video_id：`5,934`
- `videos.csv` 视频详情：`82`
- `comments.csv` 涉及 video_id：`201`
- `comments.csv` 行数：`18,153`

不能说“82 条视频对应 18,153 条评论”。原因是旧 collector/normalizer 把 video detail、challenge page metadata 和 comments/replies 阶段混在一起，导致视频详情分母与评论分母不一致。后续必须用 `collection_report.json` 的 `stage_status`、`stage_counts`、`comments_collected`、`profiles_collected` 解释 run 状态。

## 2.5 锦江酒店 tag/challenge 口径

`#酒店` 太泛化，不应作为锦江酒店核心样本。当前非泛化 metadata 验证优先覆盖：

- 锦江酒店
- 高性价比酒店推荐
- 锦江酒店中国区
- 锦江之星
- 锦江都城酒店
- 锦江宾馆
- 锦江之星酒店
- 住宿（弱相关/泛化，保留但标注）
- 南充锦江酒店

用户特别关注：`锦江都城酒店`、`锦江之星酒店`、`锦江酒店中国区`。

## 2.6 数据收集安全边界

严禁：

```bash
cat .env
printenv | grep KEY
echo $TIKHUB_API_KEY
rm -rf data/raw data/processed
```

允许：

- 使用 `--env-file .env`，但不要打印内容；
- 写新的 raw/processed run 目录；
- 写新的 Markdown 报告；
- 使用 mock/offline tests；
- 做小规模 metadata-only live smoke；
- 统计 CSV 字段覆盖率和读取脱敏 `collection_report.json`。

---

# 3. 测试与验证

常规验证命令：

```bash
. .venv/bin/activate
pytest -q
python -m py_compile $(find src tests -name '*.py' -print)
```

数据收集相关改动至少运行：

```bash
. .venv/bin/activate
python -m py_compile $(find src tests scripts -name '*.py' -print)
pytest -q
ruff check src/llm_abm_sim/data_sources tests
pyright src/llm_abm_sim/data_sources tests
```

实现 ExperimentRunner 后，应增加 smoke run，例如：

```bash
python -m llm_abm_sim.run --config configs/default.yaml --output runs/sample
```

每次实现完成时，交付说明应包含：

- changed files；
- 测试命令和结果；
- 生成的样例输出路径；
- 未覆盖风险；
- 是否仍保持默认测试无 API key / 无网络依赖；
- 若涉及数据收集，说明是否运行 comments/replies/profiles，以及有没有打印或写入秘密。

---

# 4. GitNexus

本项目已注册 GitNexus alias：

```text
llm-abm-marketing-sim
```

结构性改动、文档大改或新增模块后，建议刷新索引：

```bash
GITNEXUS_NO_GITIGNORE=1 gitnexus analyze /Users/lqy/work/llm-abm-marketing-sim --name llm-abm-marketing-sim --skip-agents-md --force
gitnexus status
```

注意：如果希望 GitNexus 也读取本 `AGENTS.md`，不要使用 `--skip-agents-md`。如果只想避免 GitNexus 生成/改写 Agent 指导文件，可以继续使用 `--skip-agents-md`。
