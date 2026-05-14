# Provider Config and Live LLM Gate

The simulator keeps live provider checks out of default tests. Default runs use the deterministic rule-based adapter and require no API key or network.

## Codex/sub2api compatibility

A manual live gate may reuse local Codex-compatible provider metadata at runtime. On this workstation the inspected, redacted shape is:

- provider name: `sub2api`
- base URL: `https://api.q1ngyuan.top`
- wire API: `responses`

The implementation must never copy auth files, bearer tokens, API keys, cookies, or other secrets into repository files, logs, docs, fixtures, or snapshots.

Codex auth fallback is allowed only when the selected provider config explicitly declares that OpenAI auth is required. Otherwise the gate fails closed or requires explicit provider credentials.

## Required behavior

- `pytest -q` excludes `live_llm` by default.
- `LLM_ABM_RUN_LIVE_LLM=1 pytest -q -m live_llm` is the explicit manual gate shape; until a provider-backed adapter is implemented, the gate validates runtime readiness and xfails rather than making a real network call.
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
- Codex/sub2api reuse is metadata-only unless the caller supplies concrete provider credentials through the configured environment variable. The implementation does not read `auth.json` contents.
- Serialized provider metadata is allowlisted to provider name, base URL, wire API, model, auth-required/readiness booleans, and adapter version fields. Free-form provider dictionaries, headers, tokens, cookies, and auth file contents are never serialized.

Manual live smoke:

```bash
LLM_ABM_RUN_LIVE_LLM=1 pytest -q -m live_llm
```

If `OPENAI_API_KEY` or a compatible live client credential is not present, the test skips with a redacted readiness reason. Default `pytest -q` remains offline because `live_llm` is excluded by pytest configuration.
