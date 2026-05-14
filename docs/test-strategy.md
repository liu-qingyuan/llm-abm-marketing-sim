# Test Strategy

Default verification is offline, deterministic, and secret-free. Live LLM checks are a manual release gate.

## Layers

- **Unit**: schemas, rule-based decisions, provider-config redaction, metrics, event serialization.
- **Integration**: config loading, toy graph/profile construction, deterministic simulation runtime.
- **Python E2E**: `python -m llm_abm_sim.run --config configs/default.yaml --output runs/sample` verifies config -> simulation -> output artifacts.
- **Browser smoke**: Playwright opens only a generated local `report.html` static shell. It must not require a frontend dev server, external network, real dataset, or live LLM.
- **Manual live LLM gate**: tests marked `live_llm` are skipped by default and run only with explicit opt-in plus runtime credentials/config.

## Quality commands

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

Manual live gate:

```bash
LLM_ABM_RUN_LIVE_LLM=1 pytest -q -m live_llm
```

The live gate is allowed to skip/fail closed when provider config or credentials are missing.

## Obsidian acceptance coverage

- `tests/integration/test_obsidian_metrics_contract.py` covers reach, engagement, diffusion depth, spread speed, key influencers, conversion trend, time-series records, and action labels (`like/comment/share/ignore`).
- `tests/unit/test_decision_cache.py` covers the DecisionInput/cache boundary needed before provider-backed LLM calls.
- `tests/e2e/test_cli_outputs.py` proves config -> simulation -> artifacts runs offline.
- `tests/playwright/report-smoke.spec.ts` proves the generated local report renders without a web app or live provider.

