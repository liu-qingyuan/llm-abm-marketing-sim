# 03-使用指南

本分类面向运行、演示和接入数据的人。

- [macOS 从零开始运行指南](getting-started-macos.md)：新机器从安装依赖到运行 CLI/Web/测试。
- [开发指南](development-guide.md)：常用开发命令、质量门禁、常见修改流程。
- [数据集与用户画像导入](dataset-ingestion.md)：边列表、用户画像、校验策略和隐私规则。
- [Provider 配置与 Live LLM 闸门](provider-config.md)：可选真实 Provider 调用的显式开关和安全要求。

## 数据收集相关入口

- [TikHub / Douyin 数据收集架构](../02-架构设计/douyin-data-collection-architecture.md)：先理解阶段化 collector，再运行真实采集。
- [`data/README.md`](../../data/README.md)：解释 raw/processed 目录、run 口径和安全边界。
