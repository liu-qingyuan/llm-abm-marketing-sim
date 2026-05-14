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
