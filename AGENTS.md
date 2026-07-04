# AGENTS.md — llm-abm-marketing-sim 项目指南

本文件只记录**稳定工作规则**。不要在这里写会随代码、数据 run、报告版本变化的“当前状态”。
可变信息应放在 `docs/`、`data/README.md`、具体 run 的 report/audit 文件中。

## 1. 渐进式读取

不要一进入仓库就全量读取 `docs/`、`data/`、raw 产物。按任务读取最小入口：

- 项目总览 / 架构 / 使用：先读 `docs/index.md`。
- 仿真核心 / ABM runtime：再读 `docs/02-架构设计/` 中相关文档。
- TikHub / Douyin 数据收集：先读 `data/README.md` 和 `docs/02-架构设计/douyin-data-collection-architecture.md`。
- 锦江酒店最终数据集 / 验证记录：读 `docs/references/jinjiang-final-dataset-audit-20260624.md` 和 `docs/references/jinjiang-final-dataset-cleanup-20260624.md`；旧入口只通过 `docs/04-开发验证/README.md` 追溯。
- 只有需要实现、排错或验证时，才读 `src/llm_abm_sim/data_sources/`、`scripts/` 和对应测试。

## 2. 项目定位

本项目是轻量级 LLM + Agent-Based Modeling 营销传播仿真器：

- 在真实或模拟社交网络上模拟内容扩散；
- LLM 是可替换的 decision function，不是仿真调度器；
- 默认必须支持离线、确定性、无 API 凭证运行；
- 真实 provider / live API 只能作为显式启用的边界能力。

核心决策输出保持结构化：

```text
engage: bool
probability: 0.0 到 1.0
reason: 简短理由
confidence: 0.0 到 1.0
action: like / comment / share / ignore
```

## 3. 架构与依赖原则

优先保持轻量：自定义 ABM Core + NetworkX + Pydantic + 可替换 LLMDecisionAdapter + DecisionCache。

稳定职责边界：

- `SimulationModel`：生命周期、时间步、调度顺序；
- `PlatformEnvironment`：曝光机制、平台规则、邻居可见状态；
- `SocialUserAgent`：用户状态、观察上下文、调用决策边界；
- `LLMDecisionAdapter`：把帖子、偏好、同伴影响转成结构化决策；
- `DecisionCache`：缓存决策、降低成本、支持复现；
- `ExperimentRunner`：配置加载、数据加载、批量实验；
- `MetricsCollector`：事件流和传播指标。

不要为了简单 ABM 任务引入 LangChain、LangGraph 或通用自主 Agent 框架，除非用户明确需要复杂工具编排。
新增依赖前先确认现有工具是否足够；默认不新增依赖。

## 4. 数据收集原则

数据采集必须阶段化，不要把 challenge、video metadata、comments、replies、profiles 混成不可解释的一次性 crawler。

稳定阶段模型：

1. `challenge_index`：索引候选视频；
2. `video_metadata`：形成可信视频分母；
3. `comments`：基于可信视频分母采集一级评论；
4. `replies`：基于一级评论采集回复；
5. `profiles`：基于已确认用户身份采集画像候选。

规则：

- 默认不启动 live 大规模抓取；用户明确授权后才运行。
- 默认测试不得依赖真实 TikHub / LLM provider。
- profile 抓取必须有 cost / quota guard；避免批量失败导致额度浪费。
- 用户指标如 activity / influence 是可观测代理指标，必须在报告中说明方法、reference、限制；不要声称等同第三方指数或真实心理画像。
- 分母、阶段状态和 partial 状态必须通过 report/audit 解释，不要只看单张 CSV 行数。

## 5. 数据与隐私安全边界

严禁：

```bash
cat .env
printenv | grep KEY
echo $TIKHUB_API_KEY
rm -rf data/raw data/processed
```

允许：

- 使用 `--env-file .env`，但不得打印秘密；
- 读取脱敏 report/audit；
- 统计 CSV 覆盖率、重复率、聚合计数；
- 写新的独立 run、Markdown 聚合报告、offline/mock tests；
- 在明确授权后运行小规模 live smoke 或指定 live 任务。

不要提交：

- `.env` 或任何密钥；
- `data/raw/` 原始响应；
- `data/processed/` 中含用户明细的大型 CSV/JSONL；
- nickname、bio、signature、raw payload 的明细报告。

Markdown 报告默认只写聚合统计、路径、方法和限制。

## 6. 测试与验证

常规验证：

```bash
. .venv/bin/activate
python -m py_compile $(find src tests -name '*.py' -print)
pytest -q
```

数据收集 / scripts 相关改动至少运行：

```bash
. .venv/bin/activate
python -m py_compile $(find src tests scripts -name '*.py' -print)
pytest -q
ruff check src/llm_abm_sim/data_sources tests scripts
pyright src/llm_abm_sim/data_sources tests scripts
```

仿真入口变化时增加 smoke：

```bash
python -m llm_abm_sim.run --config configs/default.yaml --output runs/sample
```

交付说明应包含：

- changed files；
- 测试命令和结果；
- 样例输出或报告路径；
- 未覆盖风险；
- 是否触发 live API；
- 是否读取、打印或写入秘密（正常应为否）。

## 7. 文档规则

- `AGENTS.md` 只写长期有效规则。
- 当前数据集、run id、计数、指标阈值、验证结果写到 `docs/` 或 run report，不写进本文件。
- 周报默认使用面向老师快速阅读的短版“小结”：标题 + 统计周期/口径更新时间 + 核心成果 + 下一步。
- 清理 docs/data 时先保留最终入口和 lineage；删除历史过程稿前确认不会断链。

## 8. Agent skills

### Issue tracker

本仓库使用 GitHub Issues 作为 issue tracker，并通过 `gh` CLI 读写；外部 PR 也作为 triage 请求入口。详见 `docs/agents/issue-tracker.md`。

### Triage labels

使用默认 Matt Pocock triage 标签词汇：`needs-triage`、`needs-info`、`ready-for-agent`、`ready-for-human`、`wontfix`。详见 `docs/agents/triage-labels.md`。

### Domain docs

本仓库是单上下文仓库；如存在根目录 `CONTEXT.md` 和 `docs/adr/`，工程 skills 应按需读取。详见 `docs/agents/domain.md`。

## 9. GitNexus

本项目 GitNexus alias：

```text
llm-abm-marketing-sim
```

结构性改动、文档大改或新增模块后刷新索引：

```bash
GITNEXUS_NO_GITIGNORE=1 gitnexus analyze /Users/lqy/work/llm-abm-marketing-sim --name llm-abm-marketing-sim --skip-agents-md --force
gitnexus status
```
