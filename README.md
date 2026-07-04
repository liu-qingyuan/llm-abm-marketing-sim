# LLM-ABM Marketing Diffusion Simulator

A lightweight agent-based modeling project for simulating how a marketing post diffuses through a social network.

The design goal is not a generic autonomous agent framework. The core is a reproducible ABM simulation engine where each social user agent makes a binary `engage / not engage` decision with an LLM-supported decision boundary.

## Core Modeling Contract

- **Agent**: social-media user with individual preference, history, and neighbor context.
- **Environment**: simulation scenario built on a social network graph.
- **Decision**: binary decision using post content, individual preference, and peer influence.
- **Simulation**: multi-step post diffusion process over a graph.
- **Outputs**: structured event/run-result artifacts, metrics summary, and a static HTML report shell.

## Quickstart on macOS

For a true from-zero macOS walkthrough, use the canonical guide: [`docs/03-使用指南/getting-started-macos.md`](docs/03-使用指南/getting-started-macos.md). The short path for a fresh clone is:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev,web,llm]"
npm ci
npx playwright install chromium

python -m llm_abm_sim.run --config configs/default.yaml --output runs/sample
python -m llm_abm_sim.run --config configs/fixtures/realistic_marketing_dataset.yaml --output runs/realistic-sample
python -m llm_abm_sim.web --host 127.0.0.1 --port 8000 --artifact-root runs/web
```

Open the Web console at `http://127.0.0.1:8000`. The default CLI and mock-provider development paths are offline and deterministic; live LLM calls require the explicit `LLM_ABM_RUN_LIVE_LLM=1` gate plus credentials.


## Recommended Stack

- Python src-layout package under `src/llm_abm_sim`.
- NetworkX for graph loading and neighbor queries.
- Pydantic for config, events, and decision schemas.
- Pandas for later analysis/export work.
- Pytest for unit/integration/E2E tests.
- Ruff and mypy for lint/format/type checks.
- Playwright for browser validation of the Web console and generated report surfaces.

## Setup variants

The macOS quickstart above installs the full local stack. For a minimal CLI-only development install:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

Add `web` for the local FastAPI/Uvicorn Web console and `llm` for explicitly gated live-provider experiments:

```bash
python -m pip install -e ".[dev,web,llm]"
npm ci
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
- `report_payload.json`
- `graph_trace.json`
- `input-builder.html`

The report is bilingual (`en-US` / `zh-CN`) and includes explanatory sections, metric meanings, provider/decision-source evidence, and an Agent input/output inspector in the graph trace panel. `input-builder.html` is a static offline config builder/template that can be opened without a server.

Dataset-backed fixture run:

```bash
. .venv/bin/activate
python -m llm_abm_sim.run --config configs/fixtures/realistic_marketing_dataset.yaml --output runs/realistic-sample
```

Dataset-backed runs also write `dataset_validation.json`, which records resolved edge/profile paths, graph/profile counts, validation policies, and missing/extra profile diagnostics. Relative `dataset.edge_list_path` and `dataset.profile_path` values are resolved against the directory containing the config file; absolute paths are normalized and remain absolute. See `docs/03-使用指南/dataset-ingestion.md` for CSV/JSON schema examples.


## Local Web console

Start the SaaS-like single-user console locally:

```bash
. .venv/bin/activate
python -m llm_abm_sim.web --host 127.0.0.1 --port 8000 --artifact-root runs/web
# or after install: llm-abm-web --host 127.0.0.1 --port 8000
```

The browser flow supports users CSV/JSON plus edges CSV/JSON upload, dataset validation, provider readiness preflight, POST-and-poll run contracts, bilingual result panels, and allowlisted artifact downloads. Product-mode Web runs require real provider readiness and block visibly when the live gate or credentials are missing; the explicit mock-provider mode is for tests/dev only and is labeled in the UI and payloads. See `docs/01-项目概览/product-demo.md` for API contracts, templates, and safety notes.


## Douyin Data Collection Docs

For TikHub / Douyin / 锦江酒店 data collection work, start with the staged architecture docs instead of inspecting raw runs first:

- [`docs/02-架构设计/douyin-data-collection-architecture.md`](docs/02-架构设计/douyin-data-collection-architecture.md): current staged collector architecture, Mermaid architecture diagram, and sequence diagram.
- [`data/README.md`](data/README.md): raw/processed directory semantics, current metadata baseline, and safety boundaries.
- [`docs/references/jinjiang-final-dataset-audit-20260624.md`](docs/references/jinjiang-final-dataset-audit-20260624.md): current final dataset audit, aggregate validation evidence, and privacy boundaries.

Current rule: validate `challenge_index` and `video_metadata` first; do not treat comments/replies/profiles as the primary collection path until the video metadata denominator is trusted.

## Quality commands

```bash
. .venv/bin/activate
ruff check .
ruff format --check .
mypy src
pytest -q
python -m py_compile $(find src tests -name '*.py' -print)
python -m llm_abm_sim.run --config configs/default.yaml --output runs/sample
python -m llm_abm_sim.run --config configs/fixtures/realistic_marketing_dataset.yaml --output runs/realistic-sample
npx playwright test
```

`pytest -q` is offline and excludes `live_llm` by default.

## Manual live LLM gate

Live provider checks are manual and opt-in:

```bash
LLM_ABM_RUN_LIVE_LLM=1 pytest -q -m live_llm
# Current scaffold validates readiness/schema and xfails before real provider calls until an adapter is added.
```

The live gate may reuse local Codex/sub2api-compatible provider metadata at runtime, but secrets must never be committed, logged, documented, or snapshotted. See `docs/03-使用指南/provider-config.md`.


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

- `docs/03-使用指南/getting-started-macos.md`
- `docs/02-架构设计/architecture.md`
- `docs/02-架构设计/simulation-flow.md`
- `docs/02-架构设计/framework-analysis.md`
- `docs/prds/initial-abm-mvp-development-plan.md`
- `docs/03-使用指南/dataset-ingestion.md`
- `docs/architecture/testing-strategy.md`
- `docs/03-使用指南/provider-config.md`
- `docs/01-项目概览/product-demo.md`
- `docs/01-项目概览/requirements-alignment.md`
