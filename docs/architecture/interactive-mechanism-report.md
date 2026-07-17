# Interactive Mechanism Report

Status: Target Interaction Design

## 目标

用一个可交互的单页报告让非技术读者先看懂 Target Delivery Ranking 机制，再按需检查本次 Final Research Report Run 的真实证据。页面必须区分稳定机制与本次运行结果。

## 页面结构

固定顶栏包含五个锚点：

```text
概览 / 样本 / 曝光排序 / LLM 决策 / 网络反馈
```

顶栏右侧提供全局模式切换：

```text
机制说明 | 本次运行
```

- `机制说明` 默认开启，使用通俗插画解释稳定规则。
- `本次运行` 读取持久化 artifacts，显示真实计数、排名、决策、诊断和限制。

## 交互合同

- `本次运行` 模式显示共享的 Batch 0-29 时间轴。
- 选择 Batch 后，曝光排序、LLM 决策、网络反馈和网络影响详情同步更新。
- 点击人物、信号或对照对象时，打开桌面右侧详情栏。
- 全站只使用一种详情容器，不增加不同对象的专用弹窗。
- 当前版本只承诺桌面布局，不设计或验收移动端导航、底部抽屉和移动端专用插画。

## 详情内容

基础版本直接展示允许公开的真实 processed/runtime 字段：

- `nickname`、`user_id` 和样本角色；
- Batch、ranking position 和三项 score contribution；
- 曝光状态、action、confidence 和 reason；
- 字段来源、使用阶段和必要研究限制。

页面不展示 raw Provider Payload、密钥、原始 Prompt 或未经验证的结果。

## 六段叙事

1. `概览`：TargetVideo、1,000 人样本、30 批和 Top20 容量。
2. `样本`：36,400 到 1,000，以及 20 seeds、60 历史邻居和 920 普通用户。
3. `曝光排序`：Batch 0 直接曝光，以及后续 50/30/20 全局重排。
4. `LLM 决策`：平台决定谁看到，LLM 只决定 `like/comment/share/ignore`。
5. `网络反馈`：成功互动提升直接邻居下一轮优先级，`ignore` 不传播。
6. `网络影响`：作为 `网络反馈` 内的展开内容，展示 600/400 容量边界和 full/no-network paired ranking，不占据一级导航，也不预设结果。

## 非目标

- 不拆成独立机制站点和独立证据站点。
- 不实现移动端布局或移动端交互。
- 不增加匿名、授权或多套用户详情视图。
- 不把预设权重描述为真实平台参数。
- 不把信号纳入描述为已观测结果影响。
- 不在视觉预览中虚构本次运行计数或用户结果。
