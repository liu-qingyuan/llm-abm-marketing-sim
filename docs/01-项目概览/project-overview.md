# 项目总览

**项目名：** `llm-abm-marketing-sim`  
**类型：** Python 库 + CLI；Node/Playwright 仅用于浏览器冒烟测试  
**架构：** 轻量级、事件溯源、自定义 ABM 仿真器

## 一句话说明

本项目用于模拟一条营销帖子在社交网络中的传播过程。每个社交用户 Agent 会根据帖子内容、个人偏好和邻居影响，做出结构化的 `engage / not engage` 决策。

默认运行路径是离线、确定性、无需 API key 的；真实 LLM Provider 只是可选决策适配器，必须显式开启。

## 当前支持能力

- 从 YAML/JSON 配置启动可复现实验。
- 支持内联小图，也支持从边列表和用户画像文件加载社交网络。
- 用 Pydantic 校验输入、配置、事件、决策和运行结果。
- 默认使用 `RuleBasedDecisionAdapter` 提供可复现的规则基线。
- 保留 `LLMDecisionAdapter` 边界，后续可接 OpenAI-compatible Provider。
- 记录曝光、决策、互动和每步指标，便于复盘传播路径。
- 输出 JSON/CSV 机器可读文件和本地静态 `report.html`。
- 提供本地 Web 控制台，用于上传数据、配置场景、运行仿真和查看结果。
- 默认测试不需要真实 LLM、网络或密钥。

## 技术栈

| 类别 | 技术 | 作用 |
|---|---|---|
| 运行语言 | Python 3.10+ | 仿真核心、CLI、Web API |
| Schema | Pydantic v2 | 配置、事件、决策、输出校验 |
| 图建模 | NetworkX | 社交网络、邻居查询、边属性 |
| 配置 | PyYAML | 实验配置加载 |
| 表格/输出 | pandas + stdlib CSV/JSON | 指标表、事件表、运行产物 |
| 测试 | pytest | 单元、集成、E2E |
| 质量 | Ruff、mypy | Lint、格式、类型检查 |
| 浏览器冒烟 | Playwright | 静态报告和 Web 控制台验证 |
| 可选 Provider | OpenAI-compatible SDK | 显式 live gate 后调用真实 LLM |

## 核心模块

| 模块 | 职责 |
|---|---|
| `SimulationModel` | 仿真生命周期、时间步推进、调度顺序 |
| `PlatformEnvironment` | 曝光规则、邻居可见状态、互动痕迹、传播候选 |
| `SocialUserAgent` | 用户状态、曝光/互动状态、调用决策边界 |
| `LLMDecisionAdapter` | 把帖子、偏好、同伴影响转成 `EngageDecision` |
| `DecisionCache` | 缓存决策输入输出，降低成本并支持复现 |
| `ExperimentRunner` | 配置加载、图/用户构建、运行与输出编排 |
| `MetricsCollector` | 事件流、时间序列指标、覆盖率、互动率、扩散深度/速度 |

## 快速开始

```bash
. .venv/bin/activate
python -m llm_abm_sim.run --config configs/default.yaml --output runs/sample
open runs/sample/report.html
```

新机器完整安装请看：[macOS 从零开始运行指南](../03-使用指南/getting-started-macos.md)。

## 重要目录

```text
configs/                    # 示例配置、真实感样例、Web 上传模板
src/llm_abm_sim/            # 仿真核心、CLI、Web、输出、Provider 适配
src/llm_abm_sim/web_static/ # 本地 Web 控制台前端静态资源
tests/                      # 单元、集成、E2E、Playwright、Web API 测试
docs/                       # 当前中文文档
runs/                       # 本地运行产物，git 忽略
```

## 文档地图

- 架构与设计：[架构说明](../02-架构设计/architecture.md)、[框架选型分析](../02-架构设计/framework-analysis.md)
- 运行与演示：[产品演示说明](product-demo.md)、[开发指南](../03-使用指南/development-guide.md)
- 数据接入：[数据集与用户画像导入](../03-使用指南/dataset-ingestion.md)
- Provider/LLM：[Provider 配置与 Live LLM 闸门](../03-使用指南/provider-config.md)
- 开发验收：[开发计划](../04-开发验证/development-plan.md)、[测试策略](../04-开发验证/test-strategy.md)
