# 源码结构分析

本文说明仓库目录、入口点和文件组织方式。项目是一个 Python 包，旁边带少量 Node/Playwright sidecar，用于验证生成的静态 HTML 报告和本地 Web 控制台。

## 顶层结构

```text
llm-abm-marketing-sim/
├── AGENTS.md                         # 项目级 Codex/OMX 指南
├── README.md                         # 安装、命令、Obsidian 对齐摘要
├── configs/                          # 示例配置、fixture、live smoke、Web 模板
│   ├── default.yaml
│   ├── fixtures/
│   ├── live/
│   └── templates/
├── data/
│   ├── raw/                          # 被忽略的真实/原始数据，本地使用
│   └── processed/                    # 被忽略的清洗后数据，本地使用
├── docs/                             # 中文分类文档
│   ├── 01-项目概览/
│   ├── 02-架构设计/
│   ├── 03-使用指南/
│   ├── 04-开发验证/
│   └── 99-参考资料/
├── package.json                      # Playwright 依赖/脚本
├── playwright.config.ts              # 浏览器冒烟配置
├── pyproject.toml                    # Python 包、依赖、ruff、mypy、pytest marker
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

中文文档已按场景分类：概览、架构、使用指南、开发验证、参考资料。

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

- Browser smoke：

```bash
npx playwright test
```

## 文件组织模式

- 运行时对象主要是普通 Python 类和 Pydantic 模型。
- 状态转移集中在 `SimulationModel.step` 与 `PlatformEnvironment`。
- Provider/live LLM 关注点隔离在 `provider_config.py`、`providers/` 和 `live_llm` marker 测试之后。
- 输出写入隔离在 `outputs.py` / `report_payload.py`，避免核心仿真混入序列化细节。
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
