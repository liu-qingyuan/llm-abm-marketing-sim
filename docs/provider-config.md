# Provider Config and Live LLM Gate

The simulator keeps live provider checks out of default tests. Default runs use the deterministic rule-based adapter and require no API key or network.

## Codex-compatible provider resolution

A manual live gate may reuse local Codex-compatible provider metadata at runtime. The simulator reads `CODEX_HOME/config.toml` when `CODEX_HOME` is set, otherwise `~/.codex/config.toml`, and derives only secret-free metadata from the selected `model_provider`:

- provider name
- `base_url`
- `wire_api`
- selected `model`
- `requires_openai_auth`
- whether a usable Codex runtime credential appears available

Do not hardcode a host in configs or tests; the current provider URL is read from Codex config. The implementation must never copy auth files, bearer tokens, API keys, cookies, raw headers, or other secrets into repository files, logs, docs, fixtures, pytest output, run artifacts, caches, or handoffs.

Codex auth reuse is allowed only when the selected provider config explicitly declares `requires_openai_auth = true`. Otherwise the gate fails closed or requires explicit provider credentials. `OPENAI_API_KEY` remains the fallback for OpenAI-compatible/sub2api API keys.

## Required behavior

- `pytest -q` excludes `live_llm` by default.
- `LLM_ABM_RUN_LIVE_LLM=1 pytest -q -m live_llm -rs` is the explicit manual gate shape; it makes one real provider decision only when Codex config/auth or `OPENAI_API_KEY` and the optional SDK are available.
- Provider-shaped responses must validate through `EngageDecision`; default unit coverage uses a mocked/provider-shaped payload so no network or API key is needed.
- Redaction tests must prove secrets are not emitted.

## Phase 3 provider-backed adapter

Phase 3 adds an optional `provider_llm` config block. Omit it, or keep
`enabled: false`, for the deterministic offline rule-based adapter.

```yaml
provider_llm:
  enabled: true
  provider: openai_compatible
  model: gpt-5.5
  base_url: https://api.example.test/v1
  wire_api: responses
  use_codex_provider_config: false
  require_live_env: true
  api_key_env: OPENAI_API_KEY
  fail_closed_action: raise  # raise | no_engage | skip_run
```

Safety rules:

- Real provider use is opt-in and gated by `LLM_ABM_RUN_LIVE_LLM=1` unless a test injects a mocked client.
- The adapter validates every provider response with `EngageDecision`.
- `fail_closed_action: raise` is the default and the manual live smoke policy.
- `fail_closed_action: no_engage` returns an `ignore` decision only when explicitly configured.
- `fail_closed_action: skip_run` is a fail-closed run-level stop signal and is rejected before a normal runner starts partial simulation work.
- Codex/sub2api reuse prefers Codex provider metadata and can read the minimum runtime credential from Codex auth at call time only for `requires_openai_auth=true`; otherwise use the configured API-key environment fallback.
- Serialized provider metadata is allowlisted to provider name, base URL, wire API, model, auth-required/readiness booleans, and adapter version fields. Free-form provider dictionaries, headers, tokens, cookies, and auth file contents are never serialized.


Codex-config-backed live smoke:

```bash
LLM_ABM_RUN_LIVE_LLM=1 pytest -q -m live_llm -rs
```

API-key fallback smoke:

```bash
OPENAI_API_KEY=... LLM_ABM_RUN_LIVE_LLM=1 pytest -q -m live_llm -rs
```

If Codex auth is absent, provider config is not OpenAI-auth scoped, the optional
`openai` dependency is missing, or credentials are otherwise unavailable, the
test skips/fails closed with a redacted reason. Default `pytest -q` remains
offline because `live_llm` is excluded by pytest configuration.
