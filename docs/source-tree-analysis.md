# llm-abm-marketing-sim - Source Tree Analysis

**Date:** 2026-05-14T11:55:12Z

## Overview

This is a single Python package with a small Node/Playwright sidecar for validating generated static HTML reports. The project intentionally keeps runtime simulation code separate from generated artifacts and local BMAD/OMX tooling.

## Complete Directory Structure

```text
llm-abm-marketing-sim/
├── AGENTS.md                         # Project-specific Codex/OMX guidance
├── README.md                         # Setup, commands, and Obsidian alignment
├── configs/
│   └── default.yaml                  # Toy reproducible simulation config
├── data/
│   ├── raw/                          # Ignored real/raw datasets, .gitkeep retained
│   └── processed/                    # Ignored processed datasets, .gitkeep retained
├── docs/
│   ├── architecture.md               # Architecture and Obsidian contract mapping
│   ├── development-guide.md          # Generated local workflow guide
│   ├── development-plan.md           # Roadmap and implementation phases
│   ├── framework-analysis.md         # Framework selection analysis
│   ├── index.md                      # Generated documentation index
│   ├── project-overview.md           # Generated project overview
│   ├── provider-config.md            # Manual live LLM gate docs
│   ├── simulation-flow.md            # Sequence/flow diagrams
│   ├── source-tree-analysis.md       # This file
│   └── test-strategy.md              # Test strategy and acceptance coverage
├── package.json                      # Playwright smoke-test dependency/scripts
├── playwright.config.ts              # Browser smoke config, no web server
├── pyproject.toml                    # Python package, tooling, pytest markers
├── src/
│   └── llm_abm_sim/
│       ├── __init__.py               # Public exports
│       ├── agent.py                  # SocialUserAgent state and step boundary
│       ├── decision.py               # LLMDecisionAdapter, EngageDecision, cache
│       ├── environment.py            # Platform exposure/traces/peer context
│       ├── events.py                 # Pydantic event and run-result schemas
│       ├── graph_loader.py           # NetworkX edge-list loader
│       ├── metrics.py                # Time-series and aggregate metrics
│       ├── model.py                  # SimulationModel lifecycle/time-step loop
│       ├── outputs.py                # JSON/CSV/static HTML writers
│       ├── provider_config.py        # Secret-safe Codex provider metadata loader
│       ├── run.py                    # CLI entrypoint
│       ├── runner.py                 # Config -> graph/agents/model/output orchestration
│       └── schemas.py                # Config, post, platform, profile schemas
└── tests/
    ├── e2e/                          # Python CLI/output and live-gate tests
    ├── integration/                  # Runner determinism and Obsidian metric contract
    ├── playwright/                   # Browser smoke for generated report.html
    └── unit/                         # Decision/cache/provider/agent unit tests
```

## Critical Directories

### `src/llm_abm_sim/`

**Purpose:** Core simulator package.  
**Contains:** Schemas, ABM runtime, platform environment, decision adapters, metrics, outputs, and CLI orchestration.  
**Entry Points:** `run.py`, `runner.py`, `SimulationModel`.

### `tests/`

**Purpose:** Layered verification.  
**Contains:** Unit tests for pure contracts, integration tests for deterministic runs, Python E2E tests for CLI artifacts, and Playwright smoke tests for static report rendering.

### `configs/`

**Purpose:** Reproducible experiment inputs.  
**Contains:** `default.yaml`, a toy graph/profile/post/platform config used by tests and smoke runs.

### `docs/`

**Purpose:** Human and AI-readable project knowledge.  
**Contains:** Architecture, flow, strategy, provider gate, and generated BMAD project documentation.

### `data/`

**Purpose:** Placeholder for raw/processed datasets.  
**Contains:** `.gitkeep` only by default; actual data files are ignored.

## Entry Points

- **CLI:** `python -m llm_abm_sim.run --config configs/default.yaml --output runs/sample`
- **Package API:** `ExperimentRunner.from_config_file(...).run()`
- **Browser smoke:** `npx playwright test`

## File Organization Patterns

- Runtime objects are plain Python dataclasses or Pydantic models.
- Simulation state transition is centralized in `SimulationModel.step` and `PlatformEnvironment`.
- Provider/live LLM concerns are isolated in `provider_config.py` and tests marked `live_llm`.
- Output writing is isolated in `outputs.py`, keeping core simulation separate from serialization/reporting.

## Key File Types

| File type | Pattern | Purpose | Examples |
|---|---|---|---|
| Python source | `src/llm_abm_sim/*.py` | Simulator runtime and package API | `model.py`, `decision.py` |
| Python tests | `tests/**/*.py` | Unit/integration/E2E verification | `test_obsidian_metrics_contract.py` |
| Playwright spec | `tests/playwright/*.ts` | Static report browser smoke | `report-smoke.spec.ts` |
| Config | `configs/*.yaml` | Simulation inputs | `default.yaml` |
| Docs | `docs/*.md` | Architecture and workflow knowledge | `architecture.md` |

## Asset Locations

No significant binary assets are part of the simulator package. Playwright and run artifacts are generated under ignored output directories.

## Configuration Files

- `pyproject.toml`: Python dependencies, packaging, ruff, mypy, pytest markers.
- `package.json`: Playwright scripts and dev dependency.
- `playwright.config.ts`: Static report smoke-test configuration.
- `configs/default.yaml`: Sample simulation input.
- `.gitignore`: Generated artifacts, local caches, BMAD/agent payloads, and data outputs.

## Notes for Development

- Keep default verification offline and API-key-free.
- Add provider-backed LLM calls only behind optional dependencies and explicit manual gates.
- Do not move LangChain/LangGraph/GenericAgent into the core simulation loop.
- Treat generated run outputs as disposable artifacts unless a fixture is explicitly needed.

---

_Generated using BMAD Method `document-project` workflow._
