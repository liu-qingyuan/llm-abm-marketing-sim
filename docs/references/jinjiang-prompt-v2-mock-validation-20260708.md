# 锦江 Prompt v2 mocked provider 验收摘要

日期：2026-07-08

## 摘要

本记录是 #19 主 Prompt v2 实施链路的 aggregate-only 验收摘要。当前验收范围是 prompt contract、mocked provider 和 ABM event/report 端到端路径，不是 36,400 个用户的全量真实 LLM 批量运行。

| 项目 | 结果 |
|---|---|
| Prompt version | `jinjiang-green-marketing-prompt-v2` |
| Provider 模式 | `mocked_openai_compatible` |
| Mocked run artifact | `runs/jinjiang-prompt-v2-mock-20260708T111054Z/` |
| Provider decisions | 4 |
| Final exposed | 4 |
| Final engaged | 3 |
| Engagement rate | 0.75 |
| Actions | `comment`: 1, `like`: 1, `share`: 1, `ignore`: 1 |
| Decision source summary | `provider`: 4 |

## 方法

- 使用 mocked OpenAI-compatible client 经过真实 `OpenAICompatibleDecisionAdapter`、锦江 Prompt v2 builder、`ExperimentRunner`、event/report/artifact 写入路径。
- Mocked provider 覆盖互动和不互动两类场景：`comment`、`like`、`share` 以及 `engage=false/action=ignore`。
- 只读取聚合指标和 artifact 文件清单来写本摘要，不展开 raw prompt、raw provider payload 或用户级明细。
- Provider evidence 通过现有安全清洗路径写入报告；`base_url` 已去除 userinfo、query 和 fragment。

## Prompt 字段口径

主 Prompt v2 包含：

- 营销文案全文和内容主要强调的消费价值；
- 用户真实 profile 中的可观测兴趣标签；
- 三个核心观测指标：活跃度、全平台影响力、锦江酒店社群内的局部影响力；
- 合成实验标签中的环保意识倾向、前三个秸秆制品相关消费价值、最近入住锦江旗下酒店类型和出游目的；
- 其他用户行为摘要。

主 Prompt v2 不包含：

- `latent_class` 用户类型名称；
- 性别、年龄、教育、收入；
- `brand_attitude`、`like_tendency`、`comment_tendency`、`share_tendency`；
- raw prompt、raw provider response、headers、API key 或 provider secret。

9 个观测分量字段只用于审计和解释，不作为默认 prompt 输入或直接决策变量。

## 验证命令

#24 Prompt v2 provider contract：

```bash
/tmp/llm_abm_verify_23/bin/python -m py_compile $(find src tests -name '*.py' -print)
/tmp/llm_abm_verify_23/bin/python -m pytest -q
/tmp/llm_abm_verify_23/bin/ruff check src tests
```

结果：`217 passed, 2 deselected`，ruff 和 py_compile 通过。

#25 mocked provider E2E：

```bash
/tmp/llm-abm-marketing-sim-verify-venv/bin/python -m py_compile $(find src tests -name '*.py' -print)
/tmp/llm-abm-marketing-sim-verify-venv/bin/python -m ruff check src tests
/tmp/llm-abm-marketing-sim-verify-venv/bin/python -m mypy src/llm_abm_sim
/tmp/llm-abm-marketing-sim-verify-venv/bin/python -m pytest -q
```

结果：`218 passed, 2 deselected`，ruff、mypy 和 py_compile 通过。

本次 #26 文档收口验证见 issue 完成评论和提交记录。

## 边界与限制

- 当前验收不触发 live API，不读取 `.env`，不读取或打印 API key。
- 当前验收不读取 `data/raw/`、raw provider payload、nickname、bio、signature 或用户级私密明细。
- 真实 LLM 只在显式 provider-backed 模式运行；默认离线 deterministic/mock/baseline 验证不发起 live API。
- #20 demographic ablation 是后续可选项，不属于 #19 主 Prompt v2 实施链路。
- 如果未来需要对完整 final dataset 做 live provider 决策，应另建 issue/PRD，并显式授权 provider、模型、预算、样本范围、失败策略和输出路径。
