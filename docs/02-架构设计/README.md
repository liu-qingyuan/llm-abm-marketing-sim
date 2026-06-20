# 02-架构设计

本分类解释系统如何拆分职责，以及为什么首版采用轻量自定义 ABM Core。

- [架构说明](architecture.md)：模块关系、核心原则、Obsidian 合约映射。
- [仿真流程](simulation-flow.md)：一次传播仿真的时序和数据流。
- [框架选型分析](framework-analysis.md)：为什么当前选择 NetworkX + Pydantic + 自定义运行时，暂不把 LangChain/LangGraph 放入核心。

- [TikHub / Douyin 数据收集架构](douyin-data-collection-architecture.md)：阶段化采集、视频 metadata 优先、Mermaid 架构图和时序图。
