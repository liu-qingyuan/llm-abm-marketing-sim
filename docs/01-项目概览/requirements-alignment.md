# 与 Obsidian 设计笔记的需求对齐

本文说明当前实现如何对应 Obsidian 知识库中“LLM-ABM 营销传播模拟”的六层设计。

## 六层对齐

| Obsidian 设计层 | 当前实现 | 状态 |
|---|---|---|
| 1. 输入场景 | `SimulationInput`、YAML 配置、帖子内容、种子用户、平台上下文、内联或数据集驱动的用户/边 | 已实现本地原型 |
| 2. 平台环境 | `PlatformEnvironment` 基于基础曝光概率、同伴加成、热话题加成、分享加成、可见互动痕迹和 NetworkX 邻居计算曝光 | 已实现，简化真实平台排序 |
| 3. 用户 Agent | `SocialUserAgent` 保存用户画像、曝光状态、吸收式互动状态和决策历史 | 已实现 |
| 4. LLM 决策结构 | `LLMDecisionAdapter` 边界、规则基线、可选 OpenAI-compatible Provider、`DecisionInput` 缓存键、`EngageDecision` schema | 已实现；真实 Provider 需显式开启 |
| 5. 多轮传播反馈 | `SimulationModel.step()` 按 horizon 循环，记录曝光/决策/动作事件和每步时间序列 | 已实现 |
| 6. 输出指标 | `MetricsCollector`、JSON/CSV 产物、双语报告、图追踪、决策检查器、数据集校验、Provider 证据 | 已实现本地原型主要能力 |

## Agent 决策输入/输出可解释性

每个 `DecisionEvent` 都带有 `DecisionTraceSummary`，用于解释 Agent 为什么做出某个决策：

- 帖子摘要：`post_id`、文本、话题标签、素材摘要；
- 用户画像：公开可用于决策的兴趣、品牌态度、活跃度、互动倾向；
- 同伴影响：已互动邻居、已曝光邻居、可见点赞/评论/分享、邻居互动比例；
- 平台上下文：时间标签、热话题、平台氛围、feed 权重、可见痕迹权重；
- 时间步、Prompt/Schema 版本；
- 输出：结构化 `EngageDecision`，包含 engage、probability、reason、confidence、action、decision_source 和安全 Provider 元数据。

报告页的节点详情面板会展示这组安全摘要；`graph_trace.json` 和 `report_payload.json` 使用同一条安全序列化路径。

## 双语产品合约

生成的报告内置 `en-US` 与 `zh-CN` 字典。测试会检查翻译 key 的一致性，避免某些产品文案只在一种语言中存在。

语言切换覆盖代表性产品区域：

- 摘要说明；
- 指标标签；
- 图节点/图例；
- Provider 证据说明；
- Agent 输入/输出标签。

## Provider 与密钥安全对齐

默认模式仍是确定性离线仿真。Provider-backed 决策必须满足：

1. 配置中显式启用 `provider_llm.enabled`；
2. live provider 运行显式设置 `LLM_ABM_RUN_LIVE_LLM=1`，除非测试注入 mock client；
3. Provider 返回值通过 `EngageDecision` 校验；
4. 输出只包含 allowlist 元数据。

项目不会序列化或提交：原始 Provider prompt、原始响应、headers、cookies、bearer/API token、auth 文件、credential 路径。

## 有意简化与后续方向

已实现：

- 自定义轻量 ABM 运行时；
- NetworkX 图层；
- Pydantic Schema；
- 确定性规则基线 + 可选 Provider adapter；
- 事件溯源产物和双语静态报告；
- 静态配置构建器和本地 Web 控制台。

暂未追求或留待后续：

- 平台推荐排序仍是透明加权近似，不是生产级推荐系统；
- 决策缓存目前以进程内缓存为主，持久化缓存可后续加入；
- 输入构建器偏静态复制/下载，不是完整 SaaS 编辑器；
- 核心中不引入 LangChain、LangGraph 或通用自主 Agent 框架；
- 高级图表、仪表盘、实验数据库、多人协作在 schema 稳定后再做。
