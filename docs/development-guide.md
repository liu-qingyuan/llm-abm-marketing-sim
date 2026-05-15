# llm-abm-marketing-sim - Development Guide

**Date:** 2026-05-14T11:55:12Z

## Prerequisites

- Python 3.10+
- Node.js 18+
- npm
- Optional: local Codex/sub2api config for manual live-gate readiness checks

## Setup

For a fresh macOS clone, use the canonical zero-to-run guide first: `docs/getting-started-macos.md`. The development install below matches that guide and includes the Web console plus optional provider SDK so one environment can run the documented CLI, API, and Playwright checks. The default test/run path remains offline unless the live gate is explicitly set.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev,web,llm]"
npm ci
npx playwright install chromium
```

For CLI-only work, `python -m pip install -e ".[dev]"` is enough. Use `npm ci`, not `npm install`, when validating a fresh clone against `package-lock.json`.

## Run the simulator

```bash
. .venv/bin/activate
python -m llm_abm_sim.run --config configs/default.yaml --output runs/sample
```

Expected generated files include:

```text
runs/sample/config.json
runs/sample/default.yaml
runs/sample/events.json
runs/sample/metrics_summary.json
runs/sample/report.html
runs/sample/run_result.json
runs/sample/step_records.csv
runs/sample/report_payload.json
runs/sample/graph_trace.json
runs/sample/input-builder.html
```


### Run the realistic dataset fixture

```bash
. .venv/bin/activate
python -m llm_abm_sim.run --config configs/fixtures/realistic_marketing_dataset.yaml --output runs/realistic-sample
```

This uses a commit-safe real-like social-network sample with directed weighted
edges, relationship/touchpoint metadata, communities, seed users, platform
context, time settings, and marketing content. Replace it with local private
data by placing cleaned files under ignored `data/raw/` or `data/processed/`
and updating `dataset.edge_list_path` / `dataset.profile_path` in a local config.
Do not commit raw/private exports, handles, emails, tokens, cookies, API keys,
or secret-bearing headers. The realistic fixture writes `runs/realistic-sample/dataset_validation.json` in addition to the common report artifacts.

## Quality Gates

Run all default checks:

```bash
. .venv/bin/activate
ruff check .
ruff format --check .
mypy src
pytest -q
python -m py_compile $(find src tests -name '*.py' -print)
python -m llm_abm_sim.run --config configs/default.yaml --output runs/sample
python -m llm_abm_sim.run --config configs/fixtures/realistic_marketing_dataset.yaml --output runs/realistic-sample
pytest -q tests/web/test_web_api.py
npx playwright test tests/playwright/web-console.spec.ts
```

Manual live-gate checks:

```bash
pytest -q -m live_llm -rs                         # should skip/fail closed without the live gate
LLM_ABM_RUN_LIVE_LLM=1 pytest -q -m live_llm -rs
OPENAI_API_KEY=... LLM_ABM_RUN_LIVE_LLM=1 pytest -q -m live_llm -rs
```

The live gate performs one provider decision only when explicitly opted in and when either Codex provider config/auth or `OPENAI_API_KEY` is available with the optional `openai` dependency. Codex config is read from `CODEX_HOME/config.toml` or `~/.codex/config.toml`; auth reuse is runtime-only and allowed only when the selected provider has `requires_openai_auth=true`. Default verification never performs live network calls.

## Common Tasks

### Add a new simulation config field

1. Add the field to `src/llm_abm_sim/schemas.py`.
2. Wire usage in `runner.py`, `environment.py`, or `model.py`.
3. Update `configs/default.yaml` if it should be visible in the sample run.
4. Add/adjust tests in `tests/unit` or `tests/integration`.
5. Re-run the quality gates.

### Add a new metric

1. Capture required event data in `events.py` if it is not already recorded.
2. Update `MetricsCollector.summary` or step records in `metrics.py`.
3. Update `outputs.py` if the metric should appear in report artifacts.
4. Add exact expectations in `tests/integration/test_obsidian_metrics_contract.py`.

### Add a provider-backed LLM adapter

1. Implement `LLMDecisionAdapter` under `src/llm_abm_sim/providers/`.
2. Keep provider SDKs under `[project.optional-dependencies].llm`.
3. Build prompts with `DecisionInput`/`prompting.py` so post content, preference, peer influence, and platform context are explicit.
4. Validate provider output through `EngageDecision`.
5. Configure `provider_llm.fail_closed_action` as `raise`, `no_engage`, or `skip_run`; default is `raise`.
6. Wrap provider adapters with `CachedDecisionAdapter` in runner code.
7. Keep real network tests behind `live_llm` and `LLM_ABM_RUN_LIVE_LLM=1`.
8. Never log or snapshot API keys, bearer tokens, cookies, headers, or auth files.

### Add dataset ingestion

1. Extend `DatasetConfig` in `schemas.py`.
2. Add loader behavior in `graph_loader.py` and `runner.py`.
3. Preserve explicit missing-profile behavior.
4. Add a commit-safe fixture and integration test. Use a toy fixture for small contracts and a richer real-like fixture when exercising real dataset shape.
5. Update `docs/dataset-ingestion.md` with schema examples, validation policies, seed/platform/time configuration, privacy rules, and path-resolution rules.

## Local Web console

Start the single-user Web console after installing the `web` extra:

```bash
. .venv/bin/activate
python -m llm_abm_sim.web --host 127.0.0.1 --port 8000 --artifact-root runs/web
# or: llm-abm-web --host 127.0.0.1 --port 8000 --artifact-root runs/web
```

Open `http://127.0.0.1:8000`. Product mode preflights `/api/provider/readiness` and is `blocked` until the live gate, optional SDK, provider metadata, and runtime credential are ready. For offline demos/tests, enable **Use mock provider for test/dev**; mock runs are visibly labeled and avoid network/secrets. Web artifacts are written under `runs/web/<run-id>/` and include `web_run_metadata.json` plus the common report artifacts.

## Testing Strategy

- Prefer unit tests for pure schema/decision/cache behavior.
- Use integration tests for runner/model/environment interactions.
- Use Python E2E tests only for full CLI/output workflows.
- Use Playwright for generated static report smoke tests and the local Web console browser flow; keep business logic covered by Python tests.
- Keep default test suite offline and deterministic.

## Generated Artifact Policy

Ignored by git:

- `.venv/`
- `.mypy_cache/`, `.ruff_cache/`, `.pytest_cache/`
- `runs/`
- `test-results/`, `playwright-report/`, `blob-report/`
- `node_modules/`
- `.agents/`, `_bmad/`
- `*.egg-info/`

## Commit/Review Notes

- Keep diffs small and behavior-covered.
- Include command evidence in handoffs.
- Do not introduce LangChain/LangGraph/GenericAgent into the core ABM runtime without a new approved requirement.

---

_Generated using BMAD Method `document-project` workflow._


## Manual live provider smoke

Default development and CI-style tests remain offline. After installing the optional LLM extra locally (`python -m pip install -e '.[dev,web,llm]'` or `python -m pip install -e '.[llm]'` on top of an existing environment) and confirming provider readiness, run a single provider-backed smoke with:

```bash
LLM_ABM_RUN_LIVE_LLM=1 python -m llm_abm_sim.run --config configs/live/provider_smoke.yaml --output runs/live-provider-smoke
```

Inspect `runs/live-provider-smoke/metrics_summary.json` for `decision_source_summary` and sanitized `provider_evidence`. Never commit run outputs or credentials.
