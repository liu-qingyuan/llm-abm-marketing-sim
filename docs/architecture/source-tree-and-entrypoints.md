# 源码结构分析

Status: Architecture Note
Legacy source: `docs/04-开发验证/02-source-tree-analysis.md`（已删除；迁移索引见 [`../04-开发验证/README.md`](../04-开发验证/README.md)）

本文说明仓库目录、入口点和文件组织方式。项目是一个 Python 包，旁边带少量 Node/Playwright sidecar，用于验证生成的静态 HTML 报告和本地 Web 控制台。

## 顶层结构

```text
llm-abm-marketing-sim/
├── AGENTS.md                         # 项目级 Codex/OMX 指南
├── README.md                         # 安装、命令、Obsidian 对齐摘要
├── configs/                          # 示例配置、fixture、live smoke、Web 模板
│   ├── default.yaml
│   ├── deployments/                  # release contract；不保存秘密或 raw payload
│   ├── fixtures/
│   ├── live/
│   └── templates/
├── data/
│   ├── raw/                          # 被忽略的真实/原始数据，本地使用
│   └── processed/                    # 被忽略的清洗后数据，本地使用
├── docs/                             # 中文文档入口和职责目录
│   ├── 01-项目概览/                 # 阅读路径
│   ├── 02-架构设计/                 # 阅读路径
│   ├── 03-使用指南/                 # 阅读路径
│   ├── 04-开发验证/                 # legacy migration index
│   ├── 05-周报/                     # reports archive
│   ├── architecture/
│   ├── adr/
│   ├── agents/
│   ├── decision-maps/
│   ├── prds/
│   ├── references/
│   └── 99-参考资料/                 # legacy low-frequency references
├── package.json                      # Playwright 依赖/脚本
├── playwright.config.ts              # 浏览器冒烟配置
├── pyproject.toml                    # Python 包、依赖、ruff、mypy、pytest marker
├── scripts/
│   ├── validate_abm_report_release.py # v1/v2/v3 persisted release evidence validator
│   └── deploy_abm_report.sh           # formal-only production deploy Interface
├── src/
│   └── llm_abm_sim/                  # 核心包
└── tests/                            # 分层测试
```

## `src/llm_abm_sim/` 结构

```text
src/llm_abm_sim/
├── __init__.py                       # 公共导出
├── agent.py                          # SocialUserAgent 状态与 step 边界
├── decision.py                       # LLMDecisionAdapter、EngageDecision、cache
├── environment.py                    # 平台曝光、痕迹、peer context
├── events.py                         # Pydantic 事件与 run-result schema
├── final_research.py                 # Final Research 输入、holdout、静态评分、30 批次 runtime 和 artifacts
├── final_research_report.py          # 独立 Final Research payload、用户 allowlist 与静态 HTML/CSV/JSON writer
├── graph_loader.py                   # NetworkX 边列表/数据集 loader
├── input_builder.py                  # 静态 input-builder 生成
├── metrics.py                        # 时间序列与汇总指标
├── model.py                          # SimulationModel 生命周期和 time-step 循环
├── outputs.py                        # JSON/CSV/静态 HTML 写出
├── prompting.py                      # Provider prompt/DecisionInput 构造辅助
├── provider_config.py                # 安全 Codex Provider metadata loader/live gate
├── provider_evidence.py              # Provider evidence allowlist 摘要
├── providers/
│   └── openai_compatible.py          # 可选 OpenAI-compatible adapter
├── report_i18n.py                    # 报告双语文案字典
├── report_payload.py                 # 报告 view-model 与图追踪 payload
├── run.py                            # CLI 入口
├── runner.py                         # config -> graph/agents/model/output 编排
├── safe_serialization.py             # 安全序列化/秘密过滤
├── trace.py                          # 图追踪与决策摘要
├── vendor/                           # vendored 前端依赖说明/文件
├── web/                              # 本地 FastAPI Web 控制台后端
└── web_static/                       # Web 控制台静态 HTML/CSS/JS
```

## `tests/` 结构

```text
tests/
├── e2e/                              # Python CLI/output/live-gate E2E
├── fixtures/datasets/                # 可提交 toy/realistic 数据集
├── integration/                      # runner 确定性、指标合约、mock Provider
├── playwright/                       # report 和 Web 控制台浏览器冒烟
├── unit/                             # 小边界单元测试
└── web/                              # Web API 测试
```

## 关键目录说明

### `configs/`

用于可复现实验输入：

- `default.yaml`：默认 toy 仿真。
- `fixtures/toy_dataset.yaml`：小型数据集导入样例。
- `fixtures/realistic_marketing_dataset.yaml`：真实感营销数据样例。
- `live/provider_smoke.yaml`：手动 live Provider smoke，配置无秘密。
- `templates/`：Web 上传模板。

### `data/`

本地真实/清洗数据占位目录。默认只保留 `.gitkeep`，实际数据被 git 忽略。不要提交原始私密社交平台导出。

### `docs/`

中文文档入口是 `docs/index.md`。新增或迁移的长期维护文档优先放入职责型目录：`prds/`、`references/`、`architecture/`、`adr/`、`agents/`、`decision-maps/`。

### `runs/`

CLI 和 Web 运行产物目录，git 忽略。可随时删除重建。

## 入口点

- CLI：

```bash
python -m llm_abm_sim.run --config configs/default.yaml --output runs/sample
```

- 安装后脚本：

```bash
llm-abm-sim --config configs/default.yaml --output runs/sample
llm-abm-web --host 127.0.0.1 --port 8000 --artifact-root runs/web
```

- Package API：

```python
from llm_abm_sim.runner import ExperimentRunner

runner = ExperimentRunner.from_config_file("configs/default.yaml")
result = runner.run()
```

- Final Research 离线基线与显式 provider runtime：

```python
from llm_abm_sim import FinalResearchConfig, FinalResearchRunner

config = FinalResearchConfig(dataset_dir="data/processed/jinjiang_douyin/<latent-v1-run>")
output_dir = FinalResearchRunner(config, decision_adapter).run_and_write("runs/final-research")
```

该路径保留现有 `LLMDecisionAdapter` 接缝。离线基线不调用适配器；显式启用 provider 后才运行 30 批次，并由 live gate 决定是否允许真实 API。

- Release validation 与 formal-only production deploy：

```bash
python scripts/validate_abm_report_release.py \
  --repo-root . \
  --contract configs/deployments/<release-contract>.json \
  --source-dir runs/<persisted-run>

scripts/deploy_abm_report.sh \
  --contract configs/deployments/<authorized-formal-contract>.json \
  --source-dir runs/<authorized-formal-run> \
  --release-id <release-id>
```

`validate_release(...)` 是唯一 release-validation Interface，按 exact schema additive dispatch v1/v2/v3。deploy 只接受通过本地 gate 的 v2 或 v3 Formal contract，并在任何 SSH/上传前拒绝 Validation、model/accounting、artifact 或 source mismatch；代码实现和 synthetic fixture 不构成 live/production 授权。

- Browser smoke：

```bash
npx playwright test
```

## 文件组织模式

- 运行时对象主要是普通 Python 类和 Pydantic 模型。
- 状态转移集中在 `SimulationModel.step` 与 `PlatformEnvironment`。
- Provider/live LLM 关注点隔离在 `provider_config.py`、`providers/` 和 `live_llm` marker 测试之后。
- 通用输出写入隔离在 `outputs.py` / `report_payload.py`；Final Research 专用输出隔离在
  `final_research_report.py`，避免研究字段扩展通用报告合同。
- Web 上传先在 `web/imports.py` 规范化，再走数据集 loader 的同一套校验。

## 关键文件类型

| 类型 | 模式 | 作用 | 示例 |
|---|---|---|---|
| Python source | `src/llm_abm_sim/**/*.py` | 仿真运行时和包 API | `model.py`、`decision.py` |
| Python tests | `tests/**/*.py` | 单元/集成/E2E/Web API 验证 | `test_obsidian_metrics_contract.py` |
| Playwright spec | `tests/playwright/*.ts` | 静态报告和 Web 控制台浏览器冒烟 | `report-smoke.spec.ts` |
| Config | `configs/**/*.yaml` | 仿真实验输入 | `default.yaml` |
| Docs | `docs/**/*.md` | 中文项目知识 | `architecture.md` |

## 配置文件

- `pyproject.toml`：Python dependencies、packaging、ruff、mypy、pytest markers。
- `package.json`：Playwright 脚本与 dev dependency。
- `playwright.config.ts`：浏览器测试配置。
- `configs/default.yaml`：默认仿真输入。
- `.gitignore`：运行产物、本地缓存、依赖、数据输出。

## 开发注意事项

- 默认验证保持离线、无 API 凭证。
- Provider-backed 调用只放在可选依赖和显式 manual gate 后。
- 不要把 LangChain/LangGraph/GenericAgent 移入核心仿真循环。
- 生成 run outputs 是可丢弃产物，除非明确设计为 fixture。
- 新文档请放入对应中文分类目录，并从 `docs/index.md` 链接。
