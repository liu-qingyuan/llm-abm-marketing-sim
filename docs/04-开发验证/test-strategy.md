# 测试策略

默认验证必须离线、确定性、无秘密。真实 LLM 检查是手动发布/冒烟门禁，不属于默认测试路径。

## 测试分层

| 层级 | 目标 | 示例 |
|---|---|---|
| 单元测试 | 验证纯函数、schema、决策、cache、脱敏等小边界 | `tests/unit/test_rule_based_decision.py`、`tests/unit/test_provider_config.py` |
| 集成测试 | 验证 runner/model/environment 组合行为和确定性 | `tests/integration/test_runner_determinism.py` |
| Python E2E | 验证 CLI 从配置到产物的完整链路 | `tests/e2e/test_cli_outputs.py` |
| Web API | 验证本地 Web 控制台 API、上传、运行、artifact | `tests/web/test_web_api.py` |
| Browser smoke | 用 Playwright 打开生成报告或 Web 控制台 | `tests/playwright/report-smoke.spec.ts`、`tests/playwright/web-console.spec.ts` |
| Manual live LLM gate | 只在显式 opt-in 和凭证就绪时发起真实 Provider 决策 | `pytest -q -m live_llm -rs` |

## 常规质量命令

```bash
. .venv/bin/activate
ruff check .
ruff format --check .
mypy src
pytest -q
python -m py_compile $(find src tests -name '*.py' -print)
python -m llm_abm_sim.run --config configs/default.yaml --output runs/sample
npx playwright test
```

手动 live gate：

```bash
LLM_ABM_RUN_LIVE_LLM=1 pytest -q -m live_llm -rs
```

缺少 Provider config、可选 SDK 或凭证时，live gate 可以 skip/fail closed。

## Obsidian 验收覆盖

- `tests/integration/test_obsidian_metrics_contract.py` 覆盖 reach、engagement、diffusion depth、spread speed、key influencers、conversion trend、时间序列记录和动作标签（`like/comment/share/ignore`）。
- `tests/unit/test_decision_cache.py` 覆盖 Provider-backed LLM 调用前需要稳定的 `DecisionInput` / cache 边界。
- `tests/e2e/test_cli_outputs.py` 证明 config -> simulation -> artifacts 可离线运行。
- `tests/playwright/report-smoke.spec.ts` 证明生成的本地报告不需要 Web app 或 live Provider。
- `tests/playwright/web-console.spec.ts` 验证 Web 控制台 mock happy path、product blocked path、双语结果标签、渐进披露和 artifact secret filtering。

## 测试编写原则

- 默认测试不得需要 API key、网络、真实 Provider 或私密数据。
- 与随机有关的行为必须通过 seed 固定。
- Provider 测试优先使用 mock/provider-shaped payload；真实调用只放在 `live_llm` marker 后。
- 输出安全测试应覆盖 token、cookie、authorization、raw prompt、raw provider response、credential path 等敏感词和字段。
- 指标测试应基于事件和确定性 fixture 写精确期望，避免只检查“字段存在”。
