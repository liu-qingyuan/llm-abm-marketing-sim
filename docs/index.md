# llm-abm-marketing-sim Documentation Index

**Type:** Monolith Python library/CLI with local Web console and Playwright browser tests  
**Primary Language:** Python  
**Architecture:** Lightweight custom ABM core + NetworkX + Pydantic + adapter/cache boundaries  
**Last Updated:** 2026-05-16T00:00:00+08:00

## Project Overview

`llm-abm-marketing-sim` simulates marketing-post diffusion over a social network. It models users as social-media agents, uses platform exposure mechanics and visible interaction traces, and records longitudinal propagation events and metrics. The default path is deterministic and offline; live LLM/provider checks are manual and opt-in.

## Quick Reference

- **Tech Stack:** Python 3.10+, Pydantic, NetworkX, PyYAML, pandas, pytest, ruff, mypy, Playwright
- **CLI Entry Point:** `python -m llm_abm_sim.run --config configs/default.yaml --output runs/sample`
- **Web Console Entry Point:** `python -m llm_abm_sim.web --host 127.0.0.1 --port 8000 --artifact-root runs/web`
- **Architecture Pattern:** Event-sourced custom ABM runtime with provider-agnostic decision adapter
- **Database:** None in MVP; future DecisionCache persistence may use SQLite/DuckDB
- **Deployment:** Local library/CLI plus single-user FastAPI Web console; no production multi-user service

## Generated Documentation

### Core Documentation

- [Project Overview](./project-overview.md) - Executive summary and high-level architecture
- [Architecture](./architecture.md) - Technical architecture and Obsidian contract mapping
- [Source Tree Analysis](./source-tree-analysis.md) - Annotated directory structure
- [Component Inventory](./component-inventory.md) - Catalog of major runtime/test components
- [Getting Started on macOS](./getting-started-macos.md) - Canonical from-zero macOS setup, CLI/Web console runs, mock provider, optional live LLM gate, artifacts, troubleshooting, and cleanup
- [Development Guide](./development-guide.md) - Local setup and development workflow
- [Dataset and Profile Ingestion](./dataset-ingestion.md) - Dataset schema examples, validation policies, and config-relative path rules
- [Test Strategy](./test-strategy.md) - Test layers and acceptance coverage
- [Provider Config](./provider-config.md) - Secret-safe Codex/sub2api manual live gate
- [Product Demo](./product-demo.md) - 90% local prototype demo flow and review checklist
- [Requirements Alignment](./requirements-alignment.md) - Obsidian six-layer alignment and simplification notes

### Existing Planning/Analysis Docs

- [Framework Analysis](./framework-analysis.md) - Framework selection and architectural tradeoffs
- [Development Plan](./development-plan.md) - Phased roadmap and staffing guidance
- [Simulation Flow](./simulation-flow.md) - Runtime flow and sequence diagrams

## Getting Started

### Prerequisites

Python 3.10+, Node.js 18+, npm. For a true fresh macOS setup, follow [Getting Started on macOS](./getting-started-macos.md).

### Setup

```bash
. .venv/bin/activate
python -m pip install -e ".[dev,web,llm]"
npm ci
npx playwright install chromium
```

### Run Locally

```bash
python -m llm_abm_sim.run --config configs/default.yaml --output runs/sample
python -m llm_abm_sim.run --config configs/fixtures/realistic_marketing_dataset.yaml --output runs/realistic-sample
python -m llm_abm_sim.web --host 127.0.0.1 --port 8000 --artifact-root runs/web
```

Open the Web console at `http://127.0.0.1:8000`. The default CLI and Web mock-provider development paths are offline and deterministic. Product-mode Web runs fail closed unless the explicit live gate, provider readiness metadata, and credentials are present.

### Run Tests

```bash
ruff check .
ruff format --check .
mypy src
pytest -q
python -m py_compile $(find src tests -name '*.py' -print)
npx playwright test
```

## For AI-Assisted Development

This documentation is generated for future agents and human reviewers.

### When planning simulator/runtime changes

Reference: `architecture.md`, `component-inventory.md`, `source-tree-analysis.md`, `development-plan.md`.

### When changing outputs or metrics

Reference: `component-inventory.md`, `test-strategy.md`, `tests/integration/test_obsidian_metrics_contract.py`.

### When changing dataset/profile ingestion

Reference: `dataset-ingestion.md`, `schemas.py`, `graph_loader.py`, `runner.py`, `configs/fixtures/toy_dataset.yaml`, `tests/unit/test_dataset_loader.py`, `tests/unit/test_dataset_config.py`, `tests/integration/test_runner_determinism.py`.

### When changing provider/LLM behavior

Reference: `provider-config.md`, `decision.py`, `provider_config.py`, `tests/unit/test_provider_config.py`, `tests/e2e/test_live_llm_gate.py`.

### When changing browser/report behavior

Reference: `web_app.py`, `web_static/`, `report_payload.py`, `report_i18n.py`, `input_builder.py`, `outputs.py`, `tests/web/test_web_api.py`, `tests/playwright/web-console.spec.ts`, `tests/playwright/report-smoke.spec.ts`, `playwright.config.ts`.

---

_Documentation generated by BMAD Method `document-project` workflow._
