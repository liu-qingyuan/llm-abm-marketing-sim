# llm-abm-marketing-sim - Development Guide

**Date:** 2026-05-14T11:55:12Z

## Prerequisites

- Python 3.10+
- Node.js 18+
- npm
- Optional: local Codex/sub2api config for manual live-gate readiness checks

## Setup

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
npm install
npx playwright install chromium
```

## Run the simulator

```bash
. .venv/bin/activate
python -m llm_abm_sim.run --config configs/default.yaml --output runs/sample
```

Expected generated files:

```text
runs/sample/config.json
runs/sample/default.yaml
runs/sample/events.json
runs/sample/metrics_summary.json
runs/sample/report.html
runs/sample/run_result.json
runs/sample/step_records.csv
```


### Run the realistic dataset fixture

```bash
. .venv/bin/activate
python -m llm_abm_sim.run --config configs/fixtures/realistic_marketing_dataset.yaml --output runs/realistic-marketing-dataset
```

This uses a commit-safe real-like social-network sample with directed weighted
edges, relationship/touchpoint metadata, communities, seed users, platform
context, time settings, and marketing content. Replace it with local private
data by placing cleaned files under ignored `data/raw/` or `data/processed/`
and updating `dataset.edge_list_path` / `dataset.profile_path` in a local config.
Do not commit raw/private exports, handles, emails, tokens, cookies, API keys,
or secret-bearing headers.

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
npx playwright test
```

Manual live-gate checks:

```bash
pytest -q -m live_llm -rs
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

## Testing Strategy

- Prefer unit tests for pure schema/decision/cache behavior.
- Use integration tests for runner/model/environment interactions.
- Use Python E2E tests only for full CLI/output workflows.
- Use Playwright only for generated static report smoke tests, not business logic.
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
