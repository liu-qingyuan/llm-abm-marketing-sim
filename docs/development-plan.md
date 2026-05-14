# Development Plan

## Product goal

Build a reproducible LLM-supported ABM simulator that models how a marketing post diffuses through a real social network. Each social user agent makes a binary `engage / not engage` decision from:

1. post content,
2. individual preference,
3. peer influence.

The simulator must work without live LLM calls by default and expose a clean adapter boundary for later LLM-backed decisions.

## RALPLAN-DR summary

### Principles

1. The ABM loop owns time, state, and reproducibility.
2. The LLM is a replaceable decision function, not the simulator orchestrator.
3. Pydantic schemas define all external/input/output boundaries.
4. Metrics and replayability are first-class research outputs.
5. Keep the core lightweight; add Mesa/LangChain only if a later requirement proves the need.

### Top decision drivers

1. End-to-end runnable experiment loop matching the Obsidian sequence.
2. Deterministic baseline before expensive/nondeterministic provider calls.
3. Research usability: inspectable config, datasets, events, metrics, and reports.

### Options considered

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| Custom deterministic ABM MVP first | Small, inspectable, reproducible, testable | Requires explicit event/scheduler design | Choose |
| Provider-backed LLM adapter now | Shows LLM novelty early | Cost, nondeterminism, harder debugging | Defer |
| Mesa-first implementation | Existing ABM conventions | Premature coupling before domain contracts stabilize | Keep optional |
| LangChain/LangGraph/GenericAgent core | Useful for tool/workflow agents | Not needed for repeated graph-state decision function | Reject for core MVP |

### ADR

**Decision:** Build a deterministic, event-sourced custom ABM MVP first. Keep `LLMDecisionAdapter` central, but defer real provider calls until event logging, reproducibility, `DecisionInput`, and `DecisionCache` exist.

**Why:** The project's credibility depends on repeatable simulation, validated metrics, and real graph ingestion. Live LLM integration before those contracts would make results harder to verify.

**Consequences:**

- Default tests and sample runs require no API keys.
- LLM provider integration becomes an opt-in later phase.
- Event and metric schemas should be implemented before richer reports.

## Phased roadmap

### Phase 0: Dependency and baseline validation

Status: done.

Deliverables:

- Create local `.venv`.
- Install project in editable mode with dev extras.
- Validate `pydantic`, `networkx`, `pandas`, `pytest` imports.
- Run tests and Python compile check.

Acceptance evidence:

- `python -m pip install -e ".[dev]"`
- Pydantic 2.13.4, NetworkX 3.6.1, Pandas 3.0.3 observed in `.venv`.
- `pytest -q` passes.
- `python -m py_compile ...` passes.

### Phase 1: Deterministic ABM runtime contract

Deliverables:

- Add seeded reproducibility fields to `SimulationConfig`.
- Replace global random usage with injected RNG.
- Define engagement as absorbing for MVP.
- Add event schemas:
  - `ExposureEvent`
  - `DecisionEvent`
  - `ActionEvent`
  - `StepRecord`
  - `SimulationRunResult`
- Ensure `SimulationModel.step()` follows a stable scheduler order.

Acceptance criteria:

- Same config and seed produce identical event and metric outputs.
- Tiny graph integration test verifies exposure -> decision -> update -> collect.
- Agent and environment engagement states cannot diverge under absorbing semantics.

### Phase 2: Experiment runner and config loading

Deliverables:

- Add `ExperimentRunner`.
- Load `configs/default.yaml` into Pydantic config.
- Build graph, profiles, agents, environment, adapter, and metrics collector from config.
- Add a sample run command or module entry point.

Acceptance criteria:

- One local command runs a sample simulation from config.
- The run returns or writes a structured `SimulationRunResult`.
- README documents setup and sample run.

### Phase 3: Dataset/profile ingestion

Deliverables:

- Add a `NetworkDataset` abstraction.
- Support edge-list loading plus optional node profile CSV/JSON.
- Validate graph nodes against profile records.
- Support directedness and edge attributes where feasible.

Acceptance criteria:

- Integration test loads a toy edge list and profile file.
- Missing profile behavior is explicit: default profile or validation error.
- Dataset loader returns graph + profile mapping.

### Phase 4: Event-derived metrics and exports

Deliverables:

- Metrics collector consumes events.
- Compute:
  - reach/coverage,
  - engagement rate,
  - new engagements per step,
  - diffusion speed,
  - approximate diffusion depth/path,
  - key engaged nodes/influencers.
- Export event and metric tables via pandas to CSV/JSON.

Acceptance criteria:

- Metrics are deterministic on a fixed toy graph.
- Tests assert exact time-series and aggregate values.
- Generated output files are readable by pandas.

### Phase 5: Decision input and cache boundary

Deliverables:

- Add `DecisionInput` schema containing post, profile, peer context, time step, and prompt/schema version.
- Add `DecisionCache` interface and in-memory implementation.
- Add stable cache key generation.
- Wrap `LLMDecisionAdapter` with cache lookup/store.

Acceptance criteria:

- Cache hit avoids repeated adapter call for identical decision input.
- Cache key changes when post/profile/peer/prompt version changes.
- Default tests remain network-free.

### Phase 6: Optional provider-backed LLM adapter

Deliverables:

- Add provider-backed adapter behind optional `[llm]` dependency.
- Keep secrets in environment variables or local config outside repo.
- Parse and validate provider output with `EngageDecision`.
- Add mocked provider tests.

Acceptance criteria:

- Default test suite does not require API keys.
- Mocked LLM test validates schema, fallback, and cache behavior.
- Live-provider smoke test is opt-in and skipped by default.

### Phase 7: Reporting and visualization

Deliverables:

- Markdown summary report.
- CSV/JSON output tables.
- Optional charts after metric schemas stabilize.
- Obsidian-friendly diagrams/docs kept aligned with code architecture.

Acceptance criteria:

- Sample run produces a report folder with config, events, metrics, and summary.
- Report names include run id and timestamp.
- README points to report interpretation.

## Test strategy

### Unit tests

- Pydantic schema validation.
- Rule-based decision probability and threshold behavior.
- Seeded exposure policy.
- Event schema serialization.
- Cache hit/miss and key stability.
- Metrics aggregation.

### Integration tests

- Load toy graph and profiles.
- Run fixed-horizon simulation with fixed seed.
- Assert event sequence and metric summaries.
- Export metrics and read them back with pandas.

### Smoke checks

```bash
. .venv/bin/activate
pytest -q
python -m py_compile $(find src tests -name '*.py' -print)
python -m llm_abm_sim.run --config configs/default.yaml --output runs/sample
```

The final command is a target for Phase 2; it does not exist yet.

## Staffing guidance

### `$ralph`

Best immediate execution path for Phases 1-2.

```text
$ralph implement Phases 1-2 from docs/development-plan.md in /Users/lqy/work/llm-abm-marketing-sim, preserving deterministic default tests and no external API requirement.
```

Suggested roles:

- `executor`: runtime config, event schemas, runner.
- `test-engineer`: toy graph integration tests.
- `verifier`: run pytest, py_compile, and sample smoke once available.

### `$team`

Use once work is split across runtime, metrics, dataset ingestion, and docs.

Suggested lanes:

1. Runtime lane: seeded environment and event schemas.
2. Runner lane: config loading and sample command.
3. Metrics lane: event-derived summaries and exports.
4. Test lane: unit/integration coverage.
5. Docs lane: README and Obsidian alignment.

### `$ultragoal`

Best if the full multi-phase roadmap should become a durable project goal:

```text
$ultragoal "Deliver a reproducible LLM-ABM marketing diffusion simulator with deterministic ABM runtime, event-derived metrics, decision cache, optional LLM adapter, and report outputs."
```

Use `$autoresearch-goal` later if the primary work becomes dataset/literature research. Use `$performance-goal` later if the primary work becomes scaling or throughput optimization.
