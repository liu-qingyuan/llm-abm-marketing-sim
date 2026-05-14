# LLM-ABM Marketing Diffusion Simulator

A lightweight agent-based modeling project for simulating how a marketing post diffuses through a social network.

The design goal is not a generic autonomous agent framework. The core is a reproducible ABM simulation engine where each social user agent makes a binary `engage / not engage` decision with an LLM-supported decision boundary.

## Core Modeling Contract

- **Agent**: social-media user with individual preference, history, and neighbor context.
- **Environment**: simulation scenario built on a social network graph.
- **Decision**: binary decision using post content, individual preference, and peer influence.
- **Simulation**: multi-step post diffusion process over a graph.
- **Outputs**: structured event/run-result artifacts, metrics summary, and a static HTML report shell.

## Recommended Stack

- Python src-layout package under `src/llm_abm_sim`.
- NetworkX for graph loading and neighbor queries.
- Pydantic for config, events, and decision schemas.
- Pandas for later analysis/export work.
- Pytest for unit/integration/E2E tests.
- Ruff and mypy for lint/format/type checks.
- Playwright for a minimal static report smoke test only.

## Setup

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
```

Browser smoke tests need Node dependencies and a browser install:

```bash
npm install
npx playwright install chromium
```

## Run a sample simulation

```bash
. .venv/bin/activate
python -m llm_abm_sim.run --config configs/default.yaml --output runs/sample
```

Expected artifacts include:

- `config.json`
- `run_result.json`
- `events.json`
- `metrics_summary.json`
- `step_records.csv`
- `report.html`

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

`pytest -q` is offline and excludes `live_llm` by default.

## Manual live LLM gate

Live provider checks are manual and opt-in:

```bash
LLM_ABM_RUN_LIVE_LLM=1 pytest -q -m live_llm
# Current scaffold validates readiness/schema and xfails before real provider calls until an adapter is added.
```

The live gate may reuse local Codex/sub2api-compatible provider metadata at runtime, but secrets must never be committed, logged, documented, or snapshotted. See `docs/provider-config.md`.


## Obsidian Requirement Alignment

This scaffold maps the Obsidian knowledge-base requirements into executable code:

- Six-layer framing: config/post/profile/platform context inputs, NetworkX graph layer, custom ABM runtime, `LLMDecisionAdapter` decision layer, event records, and output reports.
- Platform environment: `PlatformContext`, exposure probabilities, hot-topic/feed weights, visible interaction traces, and neighbor/share-based diffusion.
- User agent state: interests, brand attitude, activity, like/comment/share tendencies, exposure state, absorbing engagement, and repeated ignore decisions after exposure.
- Decision contract: `DecisionInput` combines post content, individual preference, peer influence, platform context, and time step; output validates as `EngageDecision` with `action`, `probability`, `reason`, and `confidence`.
- Multi-step feedback: user actions update visible traces and downstream exposures; each step writes exposure, decision, and action events.
- Metrics: reach, engagement rate, diffusion depth, spread speed, key influencers, conversion trend, and time-series records.
- Decision cache: `CachedDecisionAdapter` and `InMemoryDecisionCache` provide stable keys for future provider-backed LLM calls while keeping the default run offline.

## Architecture Notes

See:

- `docs/architecture.md`
- `docs/simulation-flow.md`
- `docs/framework-analysis.md`
- `docs/development-plan.md`
- `docs/test-strategy.md`
- `docs/provider-config.md`
