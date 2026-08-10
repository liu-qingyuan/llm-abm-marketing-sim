# Provider 配置与 Live LLM 闸门

仿真器默认不在测试中调用真实 Provider。默认 CLI 运行使用确定性规则 adapter，不需要 API key 或网络。本地 Web 控制台有两种显式模式：

1. **test/dev mock provider**：用于离线演示和测试；
2. **product provider mode**：真实 Provider 未就绪前 fail closed，状态为 `blocked`。

## Codex-compatible Provider 解析

手动 live gate 可以在运行时复用本地 Codex-compatible Provider metadata。读取顺序：

- 设置了 `CODEX_HOME` 时读取 `CODEX_HOME/config.toml`；
- 否则读取 `~/.codex/config.toml`。

只派生无秘密元数据：

- provider name；
- `base_url`；
- `wire_api`；
- selected `model`；
- `requires_openai_auth`；
- 是否存在可用的 Codex runtime credential；
- selected provider 声明的 `http_headers` 名称与数量，不包含 header value。

不要在 committed config 或测试中硬编码真实 host。实现不得把 auth files、bearer token、API key、cookie、raw headers 或其他秘密复制到仓库文件、日志、文档、fixtures、pytest output、run artifacts、cache 或 handoff。

Codex auth 只允许复用到当前 selected Provider 和它声明的 `base_url`。`requires_openai_auth = true` 时可直接复用 Codex auth snapshot；`requires_openai_auth = false` 通常不复用，但 selected provider 声明 `x-openai-actor-authorization` 时遵循 Codex 0.145 的组合语义：已有 Codex auth snapshot 作为 Bearer，actor header 作为附加 header，两者缺一时 live gate 都 fail closed。其他 selected-provider 静态 `http_headers` 仍可走 header-only 路径，不会自动生成 `Authorization: Bearer ...`；若 provider 自己显式声明 `Authorization` header，则保留该值。所有 header value 只在 live gate 后以 runtime-only container 传给 SDK，不能进入脱敏 metadata 或 persisted artifacts。`OPENAI_API_KEY` 仍是 OpenAI-compatible/sub2api API key 的显式环境 fallback。

## Pi OAuth subscription transport

显式授权的 Formal operational run 可以使用 `PiSubscriptionProviderClient`。它通过本机 Pi `ModelRuntime` 与 OAuth subscription 调用 `openai-codex`，只在 `LLM_ABM_RUN_LIVE_LLM=1` 时启动，并通过 JSONL worker 返回 typed Decision、observed model 与 usage；Python artifact 侧只看到 `openai-codex-subscription-client-v1` 脱敏 identity。worker 必须应用 Pi 的 HTTP proxy settings，模型必须位于固定 allowlist，且 dated requested IDs 与实际 Pi alias 的映射进入 qualification artifact。该 transport 不读取或打印 credential，不持久化 raw Prompt/response，也不能用于默认测试或自动降级。

Codex subscription endpoint 若拒绝 wire-level `max_output_tokens`，worker 省略该参数，但仍要求完整 usage，并在返回后对 Manifest 的 output-token ceiling 做 application-level fail-closed 检查。subscription billing 的显式 billed fee ceiling 为 `USD 0`；Pi catalog 返回的 API-equivalent `usage.cost` 只作为 nominal reference cost 单独累计，不表示 OAuth subscription 的实际扣费，也不替代 auth/transport gate。logical/physical attempt caps 仍独立执行，不能因为无 per-token 费用而失效。

## 必需行为

- `pytest -q` 默认排除 `live_llm`。
- `LLM_ABM_RUN_LIVE_LLM=1 pytest -q -m live_llm -rs` 是显式手动 gate；只有 Codex config/auth 或 `OPENAI_API_KEY` 与可选 SDK 可用时才发起一次真实 Provider 决策。
- Provider-shaped 响应必须通过 `EngageDecision` 校验；默认单元覆盖使用 mock/provider-shaped payload，因此不需要网络或 API key。
- Redaction 测试必须证明秘密不会出现在输出中。
- `GET /api/provider/readiness?mock_provider=true` 返回明确标记的 mock readiness，用于离线 Web demo/tests。
- `GET /api/provider/readiness` 不带 mock 模式时，必须在 optional SDK、`LLM_ABM_RUN_LIVE_LLM=1`、Provider metadata、runtime credential 全部可用前返回 `blocked`；`POST /api/runs` 也应镜像 blocked 状态，不得回退到离线决策。

## Safe response envelope 与 accounting

OpenAI-compatible Adapter 的 Responses 与 chat-compatible wire path 都先归一化为内部 safe response envelope。Envelope 只保留：

- 用于解析结构化 Decision 的 `decision_text`；
- allowlisted `observed_model` 及其 `reported` / `missing` / `malformed` 状态；
- `complete` / `missing` / `malformed` usage 状态；
- complete usage 的 `input_tokens`、`output_tokens`、`total_tokens` 和可选 `cached_input_tokens`。

Envelope 不保留 response id、headers、credential、request body、raw response 或 SDK object。Complete usage 只接受非 boolean 的非负整数，要求 `total_tokens == input_tokens + output_tokens`；cached tokens 是 input 子集，不能再次加入 total。未提供 cached detail 时保留 `null`，不合成 0。缺失或畸形 model/usage 只降低 evidence completeness，不改变可解析 Decision，也不触发额外 retry。

Adapter 的 `provider_accounting` 是独立 strict typed evidence，不放入 `provider_metadata`、`safe_metadata` 或 metadata allowlist。计数语义为：

- `external_request_invocations`：真实 SDK call attempts，包括随后 transport failure 的尝试；injected deterministic client 与 cache hit 不增加；
- `provider_response_count`：所有已返回 safe envelope，包括 Decision text 随后解析失败并 retry 的 response；
- `successful_decision_count`：Provider leaf 成功解析的 Decision；cached `decision_source=provider` 不构成本 run 的 response/model/usage evidence；
- model/usage 状态计数覆盖每个 returned response；token aggregate 只汇总 complete usage，不估算 missing/malformed usage。

这些 usage 只描述 Provider 在 returned response 中报告的 allowlisted metadata。Transport failure 可能没有 returned usage，因此 persisted usage 不是完整 billed cost、价格、折扣、模型可用性或节省成本的证明。

显式 request settings 另由 `provider-request-contract-v1` 和 `provider-request-accounting-v1` 记录：requested model 与 request contract 位于请求侧，observed-model counts 与 usage 位于 response accounting，二者不会因 alias 名称相似而合并。历史未配置 `reasoning_effort` / `max_output_tokens` 的 Adapter 继续保留原 request 调用形状和 safe metadata；新合同不包含 credential、raw Prompt、raw request 或 raw response。

Final Research v6 只在 `require_live_env=true` 且内部 OpenAI-compatible SDK wrapper 实际 invocation 后写 `ranking-v6-formal-evidence-v1`，但 Formal status 不等于 production eligibility。`abm-report-release-contract-v3` 只接受 bare `["openai_compatible"]`、exact requested `gpt-5.4-mini`、独立 exact observed `gpt-5.4-mini-2026-03-17`、每个 returned response 的 complete usage，以及与 persisted Decisions/actions/终态一致的 run-local accounting。该唯一 exact mapping 来自 #87 qualification；dated snapshot 不表示不同 model family，也不提供价格或质量结论。未来 snapshot 的任何变化都必须新建 Ticket 并重新 qualification，不能使用 wildcard、前缀、后缀或动态“最新”解析。缺失、畸形、mixed model、partial usage、cache wrapper 或 count mismatch 都保留为可审计事实并使 `production_deploy_eligible=false`；不会估算 transport failure 的 tokens。Injected client 或任意替代 SDK builder 的 protocol client 仍是 mock evidence，不能产生 live fact。

## Web 控制台 Provider 模式

离线浏览器 demo 使用 **Use mock provider for test/dev**。这条路径使用确定性 mock decisions，并在 UI、payload、artifact 中标记 mock provider evidence，输出到 `runs/web/<run-id>/`。

只有做 product-provider 验证时才不勾选 mock。Product 模式在运行前检查同一套 live gate 和 credential readiness。缺失 readiness 不是离线 demo 的错误，而是 product state 的预期 fail-closed 结果。

## `provider_llm` 配置块

可选 Provider-backed adapter 使用 `provider_llm` 配置。省略它，或保持 `enabled: false`，就继续使用离线规则基线。

```yaml
provider_llm:
  enabled: true
  provider: openai_compatible
  # 提交 live smoke config 时优先使用 Codex runtime metadata，
  # 避免硬编码真实 provider host/model。
  model: gpt-5.5
  base_url: https://api.example.test/v1
  wire_api: responses
  use_codex_provider_config: false
  require_live_env: true
  api_key_env: OPENAI_API_KEY
  fail_closed_action: raise  # raise | no_engage | skip_run
  # Optional Responses-only request settings. Omit both to preserve the
  # historical request and safe-metadata contract.
  reasoning_effort: low
  max_output_tokens: 256
```

安全规则：

- 真实 Provider 使用必须 opt-in，并由 `LLM_ABM_RUN_LIVE_LLM=1` 门禁控制，除非测试注入 mock client。
- Adapter 必须用 `EngageDecision` 校验每个 Provider 响应。
- `reasoning_effort` 是 typed optional setting；未配置时不会进入 request 或 safe metadata。Prompt–Model Robustness contract 只接受显式 `low`、`wire_api: responses` 和显式 `max_output_tokens`，并在调用前 fail closed。
- Robustness Responses request 固定 structured `EngageDecision` schema，并显式记录 Prompt hash、requested model、output-token ceiling、timeout/retry 与 `temperature` / `top_p` / `seed` 的省略；逐用户 Prompt、request payload 和 response payload 不进入该合同。
- `fail_closed_action: raise` 是默认策略，也是手动 live smoke 策略。
- `fail_closed_action: no_engage` 只有显式配置时才返回 `ignore` 决策。
- `fail_closed_action: skip_run` 是 run-level fail-closed stop signal，应在正常 runner 启动部分仿真前拒绝。
- Codex/sub2api 复用优先读取 Codex Provider metadata；`requires_openai_auth=true` 时读取最小 Codex runtime credential；actor-authorized relay 路径只允许同一 selected provider 的 Codex auth snapshot 与已验证 header 组合，不能跨 provider 或跨 `base_url` 混用。
- Runtime headers 拒绝非法名称、CR/LF value 和 `host`、`content-length`、`connection`、`transfer-encoding` 等传输级覆盖。
- Actor-authorization 不是主 API credential；仅有 `x-openai-actor-authorization` 时 readiness 必须为 false，不能发起必然失败的请求。
- Header-only 请求必须在最终 wire headers 中省略 SDK 合成的 `Authorization`，不得发送 placeholder bearer；selected provider 显式配置的 `Authorization` 除外。
- OpenAI SDK 内建重试固定为 `0`；所有 Provider 重试只由 `provider_llm.max_retries` 控制并计入 adapter invocation budget。
- Runtime readiness 使用的脱敏 Codex metadata 可以包含 header names/count 以解释 gate；persisted Provider evidence 的 allowlist 继续剔除所有 header 相关键。
- 不序列化 free-form provider dictionaries、header names/values、tokens、cookies、auth file contents、raw prompts、raw responses、credential paths。

## 手动 live smoke

Codex-config-backed live smoke：

```bash
LLM_ABM_RUN_LIVE_LLM=1 pytest -q -m live_llm -rs
```

API-key fallback smoke：

```bash
OPENAI_API_KEY=... LLM_ABM_RUN_LIVE_LLM=1 pytest -q -m live_llm -rs
```

如果 Codex auth、selected-provider runtime headers 与 API-key fallback 均不可用，或可选 `openai` 依赖缺失，测试会以脱敏原因 skip/fail closed。默认 `pytest -q` 仍然离线。

## Live Provider smoke config

`configs/live/provider_smoke.yaml` 是可提交的 provider-enabled fixture，用于手动 gate。它不包含秘密，并设置 `use_codex_provider_config: true`，因此 Provider host/model/auth readiness 在运行时从 Codex config 或 `OPENAI_API_KEY` 解析。

命令：

```bash
LLM_ABM_RUN_LIVE_LLM=1 python -m llm_abm_sim.run \
  --config configs/live/provider_smoke.yaml \
  --output runs/live-provider-smoke
```

生成的 `metrics_summary.json`、`events.json`、`run_result.json`、`report_payload.json`、`graph_trace.json` 和 `report.html` 会包含脱敏 decision-source/provider evidence，例如观察到 provider-backed decision 时 `decision_source_summary.provider == 1`。这些产物不得包含原始 Provider request/response payload 或秘密。
