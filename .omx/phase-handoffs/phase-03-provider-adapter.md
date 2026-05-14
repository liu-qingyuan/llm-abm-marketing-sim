# Phase 3 Provider-backed LLM Adapter Handoff

loop_engine: ralph-orch-omx
config_path: .omx/ralph-orch/phase3-provider-omx.yml
prompt_path: .omx/prompts/ralph-orch-phase3-provider-adapter.md
retention: not-worktree-or-exclusive

## Baseline

- Phase 0 baseline: `287a93b Freeze the deterministic MVP baseline`
- Phase 3 starting commit: `c45a9131745480d85340d143202917f37c132000 Complete Phase 1 dataset ingestion baseline`
- Workspace/worktree status: no `.worktrees/` or `.omx/workspaces/` directories found; work executed in the main checkout.

## Changed files

- `src/llm_abm_sim/schemas.py` — adds `ProviderLLMConfig` and `FailClosedAction` enum (`raise`, `no_engage`, `skip_run`).
- `src/llm_abm_sim/prompting.py` — builds schema-safe engagement prompts from post content, user preference, peer influence, platform context, and required structured output.
- `src/llm_abm_sim/providers/__init__.py`
- `src/llm_abm_sim/providers/openai_compatible.py` — optional OpenAI Responses-compatible adapter, mocked-client protocol, retry loop, `EngageDecision` validation, fail-closed behavior, redacted safe metadata, and live client gate.
- `src/llm_abm_sim/runner.py` — keeps rule-based adapter as default and only constructs provider adapter when `provider_llm.enabled=true`; rejects `skip_run` before partial simulation.
- `src/llm_abm_sim/provider_config.py` — keeps live gate explicit, supports env-key readiness, preserves allowlisted metadata, and redacts non-allowlisted secret keys/values.
- `src/llm_abm_sim/outputs.py` — redacts normalized outputs and copied source config artifacts.
- `tests/unit/test_provider_adapter.py` — mocked provider success, malformed JSON, schema violation, timeout/retry, cache interaction, fail-closed policies, prompt fields, and metadata redaction.
- `tests/unit/test_provider_config.py` — provider config readiness/redaction plus source-config copy redaction.
- `tests/integration/test_mocked_provider_runner.py` — runner with mocked provider adapter and `skip_run` fail-closed gate.
- `tests/e2e/test_live_llm_gate.py` — real manual live smoke path, skipped unless explicitly ready.
- `docs/provider-config.md`, `docs/development-guide.md` — Phase 3 provider config and live gate guidance.
- `.ralph/orch/phase3-provider/scratchpad.md` — orchestration notes.

## Provider config metadata allowlist serialized

`runs/provider-offline-smoke/config.json` contains only schema-safe provider config fields:

```json
{
  "api_key_env": "OPENAI_API_KEY",
  "base_url": null,
  "enabled": false,
  "fail_closed_action": "raise",
  "max_retries": 0,
  "model": null,
  "prompt_version": "engage-provider-v1",
  "provider": "openai_compatible",
  "require_live_env": true,
  "timeout_seconds": 30.0,
  "use_codex_provider_config": false,
  "wire_api": "responses"
}
```

When Codex metadata is explicitly enabled, adapter metadata is allowlisted to `provider_name`, `base_url`, `wire_api`, `model`, `requires_openai_auth`, and `auth_available` via `CodexProviderConfig.redacted()`. The adapter deliberately does not read `auth.json` contents.

## Redaction and secret-safety proof

- `outputs.copy_config_source()` parses YAML/JSON config copies and redacts secret-bearing fields before writing copied source artifacts.
- `provider_config.redact_secrets()` recursively redacts common secret-bearing keys and bearer/key-like values, while preserving allowlisted metadata keys such as `api_key_env`, `requires_openai_auth`, and `auth_available`.
- Redaction grep over `.omx/phase-handoffs/logs` and `runs/provider-offline-smoke` found no API keys, bearer tokens, auth tokens, cookie headers, or authorization headers.
- Unit coverage: `test_provider_metadata_and_redaction_are_secret_safe`, `test_copy_config_source_redacts_secret_bearing_yaml`, `test_redact_secrets_recursively`, and `test_redact_preserves_allowlisted_provider_metadata_keys`.

## Mocked provider behavior evidence

- Success path validates provider JSON/dicts through `EngageDecision`.
- Malformed JSON and schema-invalid responses raise by default.
- `fail_closed_action=no_engage` returns a safe `ignore` decision with probability/confidence `0.0`.
- `fail_closed_action=skip_run` raises a skip signal in the adapter and is rejected by `ExperimentRunner` before partial simulation.
- Timeout/retry behavior is covered with a flaky mocked client.
- `CachedDecisionAdapter` cache interaction avoids duplicate mocked provider calls.

## Live gate behavior

- Default live marker command: `.omx/phase-handoffs/logs/phase3-live-default.log`
  - `1 skipped, 36 deselected`
  - Reason: default command lacks explicit live readiness, so no network/provider call runs.
- Manual command with `LLM_ABM_RUN_LIVE_LLM=1`: `.omx/phase-handoffs/logs/phase3-live-manual.log`
  - `1 skipped, 36 deselected`
  - Reason: manual live env was set, but concrete provider credentials/client auth were unavailable in this run. The skip reason is redacted and does not expose secrets.

## Phase 1 dataset smoke preservation

`python -m llm_abm_sim.run --config configs/fixtures/toy_dataset.yaml --output runs/provider-offline-smoke` wrote `runs/provider-offline-smoke`.

Confirmed metrics remain the Phase 1 toy dataset baseline:

```json
{
  "comment_count": 0,
  "conversion_trend": {"0": 1, "1": 1, "2": 1, "3": 1},
  "diffusion_depth": 2,
  "engagement_rate": 1.0,
  "final_engaged": 4,
  "final_exposed": 4,
  "key_influencers": ["u1", "u2"],
  "like_count": 4,
  "reach_rate": 1.0,
  "share_count": 0,
  "spread_speed": 0.75,
  "total_agents": 4
}
```

## GitNexus

Final live registry refresh after commit:

```text
Repository: /Users/lqy/work/llm-abm-marketing-sim
Indexed commit: 0bafcbc
Current commit: 0bafcbc
Status: up-to-date
```

Tracked pre-final GitNexus log artifacts are also present at `.omx/phase-handoffs/logs/phase3-gitnexus.log` and `.omx/phase-handoffs/logs/phase3-gitnexus-status.log`; the live final refresh was not amended again to avoid changing HEAD after indexing.

## Acceptance command evidence

| Command | Result | Log |
|---|---:|---|
| `. .venv/bin/activate && pytest -q tests/unit -k 'provider or prompt or llm or fail_closed or redaction'` | `16 passed, 13 deselected` | `.omx/phase-handoffs/logs/phase3-unit-provider.log` |
| `. .venv/bin/activate && pytest -q tests/integration -k 'mocked_provider or provider'` | `2 passed, 3 deselected` | `.omx/phase-handoffs/logs/phase3-integration-provider.log` |
| `. .venv/bin/activate && pytest -q -m live_llm` | `1 skipped, 36 deselected` | `.omx/phase-handoffs/logs/phase3-live-default.log` |
| `. .venv/bin/activate && pytest -q` | `36 passed, 1 deselected` | `.omx/phase-handoffs/logs/phase3-pytest-all.log` |
| `. .venv/bin/activate && ruff check .` | `All checks passed!` | `.omx/phase-handoffs/logs/phase3-ruff-check.log` |
| `. .venv/bin/activate && ruff format --check .` | `28 files already formatted` | `.omx/phase-handoffs/logs/phase3-ruff-format.log` |
| `. .venv/bin/activate && mypy src` | `Success: no issues found in 16 source files` | `.omx/phase-handoffs/logs/phase3-mypy.log` |
| `. .venv/bin/activate && python -m py_compile $(find src tests -name '*.py' -print)` | exit 0, no output | `.omx/phase-handoffs/logs/phase3-py-compile.log` |
| `. .venv/bin/activate && python -m llm_abm_sim.run --config configs/fixtures/toy_dataset.yaml --output runs/provider-offline-smoke` | `runs/provider-offline-smoke` | `.omx/phase-handoffs/logs/phase3-offline-smoke.log` |
| `. .venv/bin/activate && LLM_ABM_RUN_LIVE_LLM=1 pytest -q -m live_llm` | `1 skipped, 36 deselected` | `.omx/phase-handoffs/logs/phase3-live-manual.log` |

## Prompt-to-artifact audit

- Phase 3 roadmap tasks: implemented provider module, prompt builder, Codex metadata gate, mocked tests, live gate, fail-closed enum, redaction-safe serialization, and docs.
- PRD FR4: provider adapter is optional; prompt includes post/preference/peer/platform context; outputs validate through `EngageDecision`; failure policy enum is explicit and tested; config/output serialization is redacted/schema-safe; default tests are mocked/offline; manual live smoke exists.
- Test-spec Phase 3 gate: provider config schema and fail-closed behavior covered by unit/integration tests; mocked provider exercises adapter path; live marker remains manual and skips without ready credentials; default `pytest -q` excludes live provider calls.
- Required commands: all required commands ran with logs listed above.
- Provider output validation: `_parse_provider_decision()` calls `EngageDecision.model_validate()` for all provider payloads.
- Fail-closed behavior: `raise`, `no_engage`, and `skip_run` covered by tests.
- Default offline behavior: no `provider_llm.enabled` in default/toy configs; runner uses cached rule-based adapter.
- Secret safety: grep/audits found no secrets in handoff logs or smoke outputs; auth file contents are never read.
- Manual live gate: present and explicit; this run skipped because concrete live credentials were unavailable.
- Phase 1 preservation: toy dataset smoke metrics match baseline.
- Scope control: no Phase 4+ platform/batch/report/CI work started.
- Workspace residue: no `.worktrees/` or `.omx/workspaces/` residue.
