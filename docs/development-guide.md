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

Manual live-gate readiness check:

```bash
LLM_ABM_RUN_LIVE_LLM=1 pytest -q -m live_llm
```

The current scaffold validates explicit opt-in and Codex provider readiness. It does not perform mandatory live provider calls in default verification.

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

1. Implement `LLMDecisionAdapter` in a new optional module.
2. Keep the dependency under `[project.optional-dependencies].llm`.
3. Validate provider output through `EngageDecision`.
4. Wrap with `CachedDecisionAdapter`.
5. Keep real network tests behind `live_llm` and explicit env opt-in.
6. Never log or snapshot API keys, bearer tokens, cookies, or auth files.

### Add dataset ingestion

1. Extend `DatasetConfig` in `schemas.py`.
2. Add loader behavior in `graph_loader.py` and `runner.py`.
3. Preserve explicit missing-profile behavior.
4. Add a toy fixture and integration test.
5. Update `docs/dataset-ingestion.md` with schema examples, validation policies, and path-resolution rules.

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
