# Framework Analysis

## Current status

This repository is a lightweight **LLM-supported agent-based model (ABM)** for social-network marketing post diffusion. It already has the right first-level boundaries:

- `SimulationModel` controls the run loop.
- `PlatformEnvironment` owns exposure and peer-influence state.
- `SocialUserAgent` represents a social user.
- `LLMDecisionAdapter` isolates binary `engage / not engage` decisions.
- `RuleBasedDecisionAdapter` provides a deterministic baseline.
- Pydantic schemas validate post, user, peer context, decisions, and config.
- NetworkX loads social-network edge lists.
- `MetricsCollector` records simple per-step counts.

The local development environment has been bootstrapped with the declared project dependencies:

- `pydantic`
- `networkx`
- `pandas`
- `pytest`

## Framework decision

Use a **custom lightweight ABM core** first, with Mesa kept optional.

The simulator's core problem is not autonomous tool use. It is a repeated, controlled decision function over a graph state:

```text
post content + individual preference + peer influence -> engage / not engage
```

Therefore:

- Keep **NetworkX** as the graph/data layer.
- Keep **Pydantic** as the schema and validation layer.
- Keep **LLMDecisionAdapter** as the only LLM boundary.
- Keep **Mesa** optional until scheduler complexity justifies it.
- Do not put **LangChain**, **LangGraph**, or **GenericAgent** in the core for the first development phases.

## Fit against the Obsidian architecture notes

The Obsidian notes describe this target stack:

```text
Mesa / custom ABM kernel + NetworkX + LLMDecisionAdapter + Pydantic Schema + DuckDB/SQLite cache
```

The current repo already covers the minimum skeleton for custom ABM, NetworkX, adapter, and Pydantic. The missing parts are the runtime contracts that make the simulator scientifically useful.

## Main gaps

### 1. Event and state contracts are too thin

Current state is mostly snapshot-based: exposed users, engaged users, and simple decisions. The target simulation needs longitudinal events:

- exposure events
- decision events
- action/engagement events
- per-step summaries
- final run result

Without these events, diffusion depth, speed, influence path, and replay are hard to compute.

### 2. Reproducibility is not yet explicit

`PlatformEnvironment` uses randomness for exposure. The next version needs seeded RNG and config fields such as:

- `run_id`
- `random_seed`
- scheduler mode
- directed/undirected graph policy
- engagement semantics

### 3. Engagement semantics need to be decided

The current code can let `agent.engaged` and `environment.engaged_users` diverge if an agent makes repeated decisions over time. The plan should choose explicit semantics:

- **absorbing engagement** for MVP: once engaged, the user remains engaged for diffusion influence;
- repeated exposure can be added later as a separate event type.

### 4. Dataset ingestion is only an edge-list loader

Real social-network experiments need a dataset contract containing:

- graph
- node/user profile table
- optional edge weights/directions
- seed user selection
- validation of graph node IDs against profile user IDs

### 5. Metrics are count-only

The MVP should add event-derived metrics:

- coverage/reach
- engagement rate
- new engagements per step
- diffusion speed
- approximate diffusion depth/path for engaged users
- key influencer contribution where graph data supports it

### 6. LLM integration should wait behind cache/replay

The LLM layer should not be provider-backed until the deterministic simulation loop, event log, cache key, and replay path are stable. Otherwise provider variance and cost will hide simulator bugs.

## Recommended component boundaries

| Component | Owns | Should not own |
|---|---|---|
| `ExperimentRunner` | config, dataset loading, run setup, output paths | low-level exposure mutation |
| `SimulationModel` | deterministic step order and dispatch | provider SDK calls |
| `PlatformEnvironment` | exposure rules, peer visibility, action application | experiment file IO |
| `SocialUserAgent` | observation-to-decision behavior | cache persistence |
| `LLMDecisionAdapter` | decision interface and provider isolation | simulation scheduling |
| `DecisionCache` | cache key, hit/miss, persistence | prompt/business logic |
| `MetricsCollector` | event ingestion, summaries, exports | platform exposure policy |

## Dependency posture

### Required now

- `pydantic`: schemas, config validation, LLM decision output validation.
- `networkx`: graph loading and graph metrics.
- `pandas`: event/metric table export and experiment analysis.
- `pytest`: deterministic unit and integration tests.

### Optional later

- `openai`: provider-backed adapter once the cache boundary exists.
- `mesa`: only if custom scheduling becomes too limited.
- `duckdb` or `sqlite`: persistent decision cache and experiment records.
- `matplotlib`/`plotly`: report charts after metric tables stabilize.

## Near-term architectural verdict

The current skeleton is directionally correct. The next implementation should **not** start by adding LangChain or live LLM calls. It should first make the ABM loop event-sourced, reproducible, configurable, and testable on a tiny graph.
