# PRD: 锦江 LLM Prompt 人口画像消融实验

Status: Published to GitHub issue tracker
GitHub issue: https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/20
Related PRD: [`jinjiang-abm-profile-contract-and-llm-prompt-v2.md`](jinjiang-abm-profile-contract-and-llm-prompt-v2.md)

## 问题陈述

锦江 ABM 主 prompt 当前不加入性别、年龄、教育、收入等人口画像标签，避免 LLM 决策被不必要的刻板判断引导。但研究上仍可能需要了解：如果把这些合成画像标签作为背景信息加入 prompt，LLM 的互动判断是否会发生系统性变化。

需要为人口画像信息设计一个后续可选的消融实验 PRD。该实验不改变主 prompt 口径，只作为 sensitivity / ablation 分析，用于比较含人口画像和不含人口画像两种 prompt 的结果差异。

## 解决方案

建立一个独立的人口画像 prompt ablation 方案：

- 主实验仍使用不含人口画像的 prompt。
- 消融实验使用独立 prompt version，显式加入性别、年龄段、教育程度、月收入区间。
- 人口画像只作为合成实验标签呈现，不描述为真实 Douyin 用户身份。
- Prompt 明确要求 LLM 不得基于性别、年龄、教育或收入做刻板化判断。
- 输出 `reason` 不得把人口画像作为单独互动理由。
- 报告必须同时展示主 prompt 和人口画像 prompt 的结果差异。

## 用户故事

1. 作为研究者，我想保留不含人口画像的主 prompt，这样主实验结论不被人口画像标签主导。
2. 作为研究者，我想单独测试加入人口画像后的 prompt，这样可以评估人口画像信息是否改变 LLM 决策结果。
3. 作为研究者，我想把人口画像明确标注为合成实验标签，这样不会被误解为真实 Douyin 用户身份识别。
4. 作为研究者，我想限制 LLM 不能基于人口画像做刻板归因，这样输出理由更符合研究伦理和解释边界。
5. 作为研究者，我想比较主 prompt 和人口画像 prompt 的结果差异，这样可以形成 sensitivity / ablation 分析。

## 实现决策

- 本 PRD 不修改主 prompt。
- 人口画像 prompt 必须使用独立 prompt version。
- 可加入的人口画像字段仅限：性别、年龄段、教育程度、月收入区间。
- 不加入任何更细粒度个人信息。
- Prompt 中必须说明这些字段是合成实验标签。
- LLM 可以把人口画像作为辅助背景，但不能把人口画像作为唯一互动依据。
- `reason` 中不能出现“因为是女性/年轻人/高收入所以会互动”这类直接刻板归因。
- 报告应按主 prompt 与 demographic prompt 两组结果比较互动率、action 分布和不同用户群体的差异。

## 测试决策

- Prompt builder 测试应验证主 prompt 不包含人口画像字段。
- Prompt builder 测试应验证 demographic prompt 只在显式 prompt version 下包含人口画像字段。
- Prompt builder 测试应验证 demographic prompt 包含反刻板化约束。
- Provider adapter 测试使用 mocked provider，不触发 live API。
- 报告测试应验证主 prompt 和 demographic prompt 的结果能被区分和聚合。

## 超出范围

- 不改变锦江 ABM 主 prompt v2。
- 不重新生成 latent attributes。
- 不重新采集 TikHub、Douyin 或其他 live API 数据。
- 不读取或打印 `.env`、API key、raw payload、nickname、bio、signature 或用户明细。
- 不在本 PRD 中决定是否把 demographic ablation 写入论文主结果。

## 进一步说明

该 PRD 是后续可选项。当前优先实现主 prompt v2；人口画像消融实验应在主 prompt 稳定并完成 mock/provider 验证后再推进。
