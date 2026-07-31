# Guides

本目录统一保存运行、演示、开发、数据导入和 Provider 配置指南。

- [macOS 从零开始运行指南](getting-started-macos.md)：从安装依赖到离线 CLI、Web 控制台和本地测试。
- [本地离线/Web Demo](product-demo.md)：区分通用本地 demo 与 Multi-Message Formal Research。
- [开发指南](development-guide.md)：开发环境、质量门禁、release validation 和常见修改边界。
- [数据集与用户画像导入](dataset-ingestion.md)：边列表、画像 schema、校验策略和隐私规则。
- [Provider 配置与 Live LLM 闸门](provider-config.md)：可选真实 Provider 的显式开关、响应安全边界和 accounting。

TikHub / Douyin 数据收集的阶段化架构属于 [Architecture](../architecture/douyin-data-collection-architecture.md)；数据目录语义属于 [`data/README.md`](../../data/README.md)。

所有默认命令保持离线、确定和无凭证。真实 Provider、TikHub、Douyin 或 profile API 只能在明确授权后运行，且不得把 secrets、raw payload 或用户级 raw records 写入仓库。
