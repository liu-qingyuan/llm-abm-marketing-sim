# llm-abm-marketing-sim - Component Inventory

**Date:** 2026-05-14T11:55:12Z

## Overview

This inventory documents the major runtime, output, and test components for future contributors and AI agents.

## Runtime Components

| Component | File | Responsibility | Key collaborators |
|---|---|---|---|
| `SimulationInput`, `SimulationConfig`, `PostContent`, `PlatformContext`, `UserProfile`, `PeerContext` | `src/llm_abm_sim/schemas.py` | Pydantic input/config/state schemas | `runner.py`, `decision.py`, `environment.py` |
| `SocialUserAgent` | `agent.py` | User-level exposure/engagement state and decision invocation | `SimulationModel`, `LLMDecisionAdapter` |
| `EngageDecision` | `decision.py` | Structured action decision: engage, action, probability, reason, confidence | All adapters and events |
| `DecisionInput` | `decision.py` | Stable cache/prompt input schema | `CachedDecisionAdapter` |
| `LLMDecisionAdapter` | `decision.py` | Provider-agnostic decision function interface | `RuleBasedDecisionAdapter`, future providers |
| `RuleBasedDecisionAdapter` | `decision.py` | Deterministic offline baseline | `ExperimentRunner` |
| `DecisionCache`, `InMemoryDecisionCache`, `CachedDecisionAdapter` | `decision.py` | Cache boundary and default in-memory wrapper | `ExperimentRunner`, future provider adapter |
| `PlatformEnvironment` | `environment.py` | Exposure mechanics, visible interaction traces, peer context, spread candidates | `SimulationModel` |
| `SimulationModel` | `model.py` | Run lifecycle, time-step scheduling, event collection | `PlatformEnvironment`, agents, metrics |
| `MetricsCollector` | `metrics.py` | Time-series and aggregate diffusion metrics | `SimulationModel`, outputs |
| `ExperimentRunner` | `runner.py` | Config loading, graph/profile/agent/model construction, output orchestration | CLI, tests |

## Event and Output Components

| Component | File | Responsibility |
|---|---|---|
| `ExposureEvent` | `events.py` | Records first exposure, source, probability, depth, channel |
| `DecisionEvent` | `events.py` | Records adapter evaluation and structured decision |
| `ActionEvent` | `events.py` | Records like/comment/share action and source depth |
| `StepRecord` | `events.py` | Per-time-step counts and event groups |
| `SimulationRunResult` | `events.py` | Full serializable run output |
| `write_run_outputs` | `outputs.py` | Writes `config.json`, `run_result.json`, `metrics_summary.json`, `step_records.csv`, `events.json`, `report.html` |
| `write_report_html` | `outputs.py` | Generates minimal local static report for browser smoke tests |

## Provider and Live-Gate Components

| Component | File | Responsibility |
|---|---|---|
| `CodexProviderConfig` | `provider_config.py` | Secret-free provider metadata summary |
| `load_codex_provider_config` | `provider_config.py` | Runtime-only Codex config metadata loader |
| `should_run_live_llm` | `provider_config.py` | Explicit env + auth/provider readiness gate |
| `redact_secrets` | `provider_config.py` | Recursive redaction for secret-bearing keys/values |

## Test Components

| Test area | Files | Coverage |
|---|---|---|
| Unit | `tests/unit/*.py` | Rule-based decision, absorbing engagement, provider config, cache behavior |
| Integration | `tests/integration/*.py` | Deterministic runner and Obsidian metric contract |
| Python E2E | `tests/e2e/test_cli_outputs.py` | CLI writes offline run artifacts |
| Manual live gate | `tests/e2e/test_live_llm_gate.py` | Skipped unless runtime is explicitly ready |
| Browser smoke | `tests/playwright/report-smoke.spec.ts` | Generated local `report.html` renders run/metric/event sections |

## Reuse Guidance

- Add new simulation inputs to `schemas.py` first, then wire through `runner.py` or `environment.py`.
- Add new event fields in `events.py` and update `outputs.py`/tests together.
- Add provider-backed decisions by implementing `LLMDecisionAdapter`; do not change `SimulationModel` for provider details.
- Add persistent decision caching by implementing `DecisionCache`; keep `CachedDecisionAdapter` as the wrapper boundary.

---

_Generated using BMAD Method `document-project` workflow._
