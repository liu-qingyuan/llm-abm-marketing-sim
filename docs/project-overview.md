# llm-abm-marketing-sim - Project Overview

**Date:** 2026-05-14T11:55:12Z  
**Type:** Python library/CLI with Playwright report smoke tests  
**Architecture:** Lightweight event-sourced custom ABM simulator

## Executive Summary

`llm-abm-marketing-sim` is a lightweight Agent-Based Modeling simulator for marketing-post diffusion through a social network. It keeps the ABM loop deterministic and offline by default, while exposing a clean `LLMDecisionAdapter` boundary for future provider-backed decisions.

The current framework supports:

- configuration-driven sample experiments from YAML/JSON;
- NetworkX graph construction from inline edges or edge-list datasets;
- Pydantic schemas for inputs, decisions, events, and run results;
- deterministic rule-based decisions with a cache wrapper;
- platform context, visible interaction traces, and multi-step exposure feedback;
- machine-readable outputs plus a local static `report.html`;
- Python unit/integration/E2E tests and Playwright smoke validation.

## Project Classification

- **Repository Type:** Monolith
- **Project Type:** Python library + CLI; Node/Playwright is used only for browser smoke tests of generated static reports.
- **Primary Languages:** Python, TypeScript for Playwright specs
- **Architecture Pattern:** Custom ABM core + adapter boundary + event-sourced outputs

## Technology Stack Summary

| Category | Technology | Location | Purpose |
|---|---|---|---|
| Runtime language | Python 3.10+ | `pyproject.toml` | Simulator package and CLI |
| Schema validation | Pydantic v2 | `src/llm_abm_sim/schemas.py`, `events.py`, `decision.py` | Typed config, decisions, events, results |
| Graph modeling | NetworkX | `runner.py`, `graph_loader.py`, `environment.py` | Social graph and neighbor lookup |
| Tabular/output support | pandas | `pyproject.toml` | Future metric table workflows; outputs currently use stdlib CSV/JSON |
| YAML config | PyYAML | `runner.py` | Load experiment configs |
| Python tests | pytest | `tests/unit`, `tests/integration`, `tests/e2e` | Offline verification |
| Lint/type | Ruff, mypy | `pyproject.toml` | Code quality gates |
| Browser smoke | Playwright | `tests/playwright`, `playwright.config.ts` | Validate generated local `report.html` |

## Key Features

1. **Offline deterministic baseline**: `RuleBasedDecisionAdapter` and seeded `PlatformEnvironment` make default runs reproducible.
2. **LLM-ready decision boundary**: `DecisionInput`, `EngageDecision`, `LLMDecisionAdapter`, and `CachedDecisionAdapter` isolate future provider work from simulation orchestration.
3. **Platform-aware diffusion**: `PlatformContext`, visible like/comment/share traces, and exposure boosts model platform influence without a full platform clone.
4. **Event-sourced records**: `ExposureEvent`, `DecisionEvent`, `ActionEvent`, and `StepRecord` preserve the longitudinal propagation sequence.
5. **Research-oriented metrics**: reach, engagement rate, diffusion depth, spread speed, key influencers, conversion trend, and action counts.
6. **Static report E2E**: CLI writes report artifacts; Playwright opens the generated `file://` report with no dev server.
7. **Secret-safe manual live gate**: Codex/sub2api metadata can be checked at runtime, but default tests never require live provider access.

## Development Overview

### Prerequisites

- Python 3.10+
- Node.js 18+ for Playwright smoke tests
- Existing `.venv` is used in this workspace; otherwise create one with `python -m venv .venv`.

### Getting Started

```bash
. .venv/bin/activate
python -m pip install -e ".[dev]"
npm install
npx playwright install chromium
```

### Key Commands

```bash
ruff check .
ruff format --check .
mypy src
pytest -q
python -m py_compile $(find src tests -name '*.py' -print)
python -m llm_abm_sim.run --config configs/default.yaml --output runs/sample
npx playwright test
pytest -q -m live_llm
```

## Repository Structure Summary

The source code lives under `src/llm_abm_sim`. Tests are split into unit, integration, Python E2E, and Playwright browser smoke layers. Documentation lives in `docs/`; generated runtime outputs live under ignored folders such as `runs/`, `test-results/`, and `playwright-report/`.

## Documentation Map

- [index.md](./index.md) - Master documentation index
- [architecture.md](./architecture.md) - Architecture and Obsidian requirement mapping
- [source-tree-analysis.md](./source-tree-analysis.md) - Annotated directory structure
- [component-inventory.md](./component-inventory.md) - Module inventory and responsibilities
- [development-guide.md](./development-guide.md) - Local setup and development workflow
- [test-strategy.md](./test-strategy.md) - Test layers and acceptance coverage
- [provider-config.md](./provider-config.md) - Codex/sub2api manual live gate

---

_Generated using BMAD Method `document-project` workflow._
