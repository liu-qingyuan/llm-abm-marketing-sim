# llm-abm-marketing-sim 文档索引

本目录已按阅读场景分类整理。建议第一次了解项目时，从“项目概览”开始；准备运行项目时看“使用指南”；准备改代码时看“架构设计”和“开发验证”。后续新增规划和长期维护文档优先使用职责型目录：PRD、Reference、Architecture Note、ADR。

## 分类结构

```text
docs/
├── 01-项目概览/      # 项目是什么、能演示什么、与 Obsidian 设计如何对齐
├── 02-架构设计/      # 核心架构、仿真流程、框架取舍
├── 03-使用指南/      # 安装运行、数据导入、Provider/LLM 配置
├── 04-开发验证/      # 旧验证入口和迁移索引；新规格不再放这里
├── agents/           # 工程 skills 的 issue tracker、triage 和领域文档约定
├── architecture/     # 当前/目标架构说明、数据结构图、边界说明
├── adr/              # 架构决策记录
├── decision-maps/    # 多会话决策图
├── prds/             # PRD 与 GitHub issue 父任务副本
├── references/       # 外部资料整理、研究先验、不可执行参考
└── 99-参考资料/      # 自动扫描报告等低频参考资料
```

## 职责型入口

新增或迁移文档时优先使用这些入口：

- [PRDs](prds/README.md)：产品需求、用户故事、验收标准和后续 issue plan。
- [References](references/README.md)：外部资料、研究先验和数据口径参考，不代表实现状态。
- [Architecture Notes](architecture/README.md)：当前/目标架构、模块边界、数据结构图和测试架构。
- [ADRs](adr/README.md)：难以逆转且有真实权衡的架构决策。
- [Agent skills](agents/README.md)：工程 skills 的 issue tracker、triage labels 和 domain docs 约定。
- [Decision maps](decision-maps/refactor-test-hardening-2026-07.md)：需要多轮推进的规划图。

## 推荐阅读路径

### 只想快速了解项目

1. [项目总览](01-项目概览/project-overview.md)
2. [产品演示说明](01-项目概览/product-demo.md)
3. [与 Obsidian 设计笔记的需求对齐](01-项目概览/requirements-alignment.md)

### 想在本机跑起来

1. [macOS 从零开始运行指南](03-使用指南/getting-started-macos.md)
2. [开发指南](03-使用指南/development-guide.md)
3. [数据集与用户画像导入](03-使用指南/dataset-ingestion.md)
4. [Provider 配置与 Live LLM 闸门](03-使用指南/provider-config.md)

### 想理解系统怎么设计

1. [架构说明](02-架构设计/architecture.md)
2. [仿真流程](02-架构设计/simulation-flow.md)
3. [框架选型分析](02-架构设计/framework-analysis.md)
4. [TikHub / Douyin 数据收集架构](02-架构设计/douyin-data-collection-architecture.md)

### 想继续开发或验收

1. [PRD：文档架构重组与锦江 Latent Attributes 迁移试点](prds/docs-architecture-and-jinjiang-latent-attributes-migration.md)
2. [Decision map：重构与测试补强](decision-maps/refactor-test-hardening-2026-07.md)
3. [TikHub / Douyin 数据收集架构](02-架构设计/douyin-data-collection-architecture.md)
4. [锦江用户潜在属性研究先验整理](references/jinjiang-user-latent-attributes-reference-zh.md)
5. [锦江酒店 Douyin 最终数据集审计](04-开发验证/05-jinjiang-douyin-final-dataset-20260624.md)
6. [源码结构分析](04-开发验证/02-source-tree-analysis.md)
7. [组件清单](04-开发验证/03-component-inventory.md)
8. [测试策略](04-开发验证/04-test-strategy.md)

## 快速命令

```bash
# 安装开发环境
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev,web,llm]"
npm ci
npx playwright install chromium

# 离线运行默认仿真
python -m llm_abm_sim.run --config configs/default.yaml --output runs/sample

# 离线运行真实感营销数据样例
python -m llm_abm_sim.run --config configs/fixtures/realistic_marketing_dataset.yaml --output runs/realistic-sample

# 启动本地 Web 控制台
python -m llm_abm_sim.web --host 127.0.0.1 --port 8000 --artifact-root runs/web

# 常规验证
ruff check .
ruff format --check .
mypy src
pytest -q
python -m py_compile $(find src tests -name '*.py' -print)
```

## 数据收集快速入口

- 当前数据收集架构：[`02-架构设计/douyin-data-collection-architecture.md`](02-架构设计/douyin-data-collection-architecture.md)
- 数据目录语义：[`../data/README.md`](../data/README.md)
- 当前最终数据集审计：[`04-开发验证/05-jinjiang-douyin-final-dataset-20260624.md`](04-开发验证/05-jinjiang-douyin-final-dataset-20260624.md)
- 当前最终数据集清理记录：[`04-开发验证/06-jinjiang-douyin-final-dataset-cleanup-20260624.md`](04-开发验证/06-jinjiang-douyin-final-dataset-cleanup-20260624.md)
- 锦江 latent attributes 研究先验：[`references/jinjiang-user-latent-attributes-reference-zh.md`](references/jinjiang-user-latent-attributes-reference-zh.md)
- 锦江 latent attributes 迁移计划：[`prds/docs-architecture-and-jinjiang-latent-attributes-migration.md`](prds/docs-architecture-and-jinjiang-latent-attributes-migration.md)
- 后续 AI Agent 应优先看最终数据集审计；如需追溯阶段化采集或历史口径，再查看 Git 历史。

## 核心约定

- 默认路径必须离线、确定性、无 API 凭证、无外部网络依赖。
- LLM 是可替换的决策函数，不是仿真调度器。
- ABM 循环负责时间、状态、扩散和可复现性。
- 所有输入、输出、事件和 Provider 响应都通过 Pydantic/安全序列化边界约束。
- 不提交真实私密数据、API 凭证、会话凭证、鉴权头、原始 Prompt 或原始 Provider 响应。
