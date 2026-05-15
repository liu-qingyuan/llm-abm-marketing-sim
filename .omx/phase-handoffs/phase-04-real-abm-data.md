# Phase 04 - Real ABM Data Handoff

## Summary

Implemented the next data-focused step for `llm-abm-marketing-sim`: a richer real-data-shaped dataset workflow, validation diagnostics, realistic marketing social-network fixture, E2E smoke coverage, and Codex-config-backed live LLM gate documentation/tests. Default runs remain offline, deterministic, and no-key/no-network.

## Changed files

- `.gitignore`
  - Keeps `.ralphy/`, `.ralphy-worktrees/`, and `.ralphy-sandboxes/` ignored without touching protected runtime files.
- `configs/fixtures/realistic_marketing_dataset.yaml`
  - New realistic fixture config with seed users, platform context, marketing post, time settings, and dataset file references.
- `tests/fixtures/datasets/realistic_marketing_edges.csv`
  - New commit-safe real-like directed weighted relationship/touchpoint sample with 36 users and 45 edges.
- `tests/fixtures/datasets/realistic_marketing_profiles.csv`
  - New commit-safe profile sample with communities/segments, interests, brand attitude, activity/tendencies, follower counts, locale, and lifecycle stage.
- `src/llm_abm_sim/schemas.py`
  - `UserProfile` now preserves extra non-secret public profile attributes via Pydantic `extra="allow"`.
- `src/llm_abm_sim/graph_loader.py`
  - Adds validation diagnostics for available edge columns, preserved profile attribute columns, and seed-user coverage.
  - Validates configured edge weight/attribute columns exist.
  - Preserves configured edge relationship/touchpoint/weight attributes.
- `src/llm_abm_sim/runner.py`
  - Passes configured seed users into dataset validation.
- `src/llm_abm_sim/provider_config.py`
  - Adds Codex-config-backed runtime credential resolution with `requires_openai_auth=true` scoping and `OPENAI_API_KEY` fallback.
  - Keeps credentials runtime-only and redacted.
- `src/llm_abm_sim/providers/openai_compatible.py`
  - Uses Codex runtime credential resolution or configured API-key env at call time.
- `tests/unit/test_dataset_loader.py`
  - Adds real-like fixture loader assertions for graph/profile attribute preservation and validation diagnostics.
- `tests/integration/test_runner_determinism.py`
  - Adds deterministic repeated-run coverage for the realistic fixture.
- `tests/e2e/test_cli_outputs.py`
  - Adds CLI smoke verifying realistic fixture output artifacts and dataset diagnostics.
- `tests/unit/test_provider_config.py`
  - Adds Codex credential resolution tests, env precedence, OpenAI-auth scoping, and redaction proof.
- `docs/dataset-ingestion.md`
  - Documents real social-network ABM input contract, required/optional columns, seed/platform/time settings, privacy rules, and realistic fixture command.
- `docs/development-guide.md`
  - Adds realistic fixture run guidance and live LLM command shapes.
- `docs/provider-config.md`
  - Documents Codex-config-backed provider resolution, API-key fallback, and secret-safety constraints.

## Obsidian-source alignment

Aligned with the required Obsidian design source:

- `01-项目框架说明.md`: real inputs now cover marketing content, real social network, seed users, platform context, and time settings.
- `02-仿真流程与时序.md`: realistic fixture runs over multiple time steps and emits longitudinal events/metrics.
- `05-开发架构设计.md`: loader builds NetworkX graph plus user profile attributes before SimulationModel/Environment/Agent decisions.
- `06-开发流程与运行时序.md`: runner flow remains load graph/profile -> initialize model/agents -> seed exposure -> step diffusion -> collect metrics/report.

## Dataset schema summary

Edge CSV contract:

- Required: `source`, `target`.
- Optional weight: configured `edge_weight_column`, copied to NetworkX `weight`.
- Optional relationship/touchpoint metadata: configured `edge_attribute_columns`.
- Realistic fixture attributes: `relationship`, `touchpoint`, `frequency_per_week`, `recency_days`, `community_bridge`.

Profile CSV/JSON contract:

- Required: `user_id`.
- Validated decision fields: `interest_tags`, `brand_attitude`, `activity_level`, `like_tendency`, `comment_tendency`, `share_tendency`.
- Preserved non-secret extra fields: e.g. `community`, `segment`, `follower_count`, `locale`, `lifecycle_stage`.

Validation diagnostics now include:

- source filenames, directedness, graph/profile counts;
- missing/default/extra profile IDs and policies;
- edge weight column, edge attribute columns, available edge columns;
- preserved profile attribute columns;
- configured seed users, covered seed users, missing seed users;
- errors list.

## Route A live LLM status

- Codex provider metadata is read from `CODEX_HOME/config.toml` or `~/.codex/config.toml`.
- Runtime credential resolution prefers `OPENAI_API_KEY`; otherwise it reads the minimum Codex auth credential only when the selected provider has `requires_openai_auth=true`.
- Credentials are never serialized to config copies, run artifacts, logs, tests, or handoff.
- Default tests exclude `live_llm`; manual live smoke remains gated by `LLM_ABM_RUN_LIVE_LLM=1`.
- Current verification status: live gate skipped safely because the optional `openai` dependency is not installed in this venv, even though provider/auth metadata is present.

## Verification commands

All required commands were run from `/Users/lqy/work/llm-abm-marketing-sim` with `. .venv/bin/activate`:

```bash
pytest -q tests/unit tests/integration -k 'dataset or graph or profile or realistic or real'
# 12 passed, 27 deselected

pytest -q tests/e2e
# 3 passed, 1 deselected

pytest -q
# 42 passed, 1 deselected

pytest -q -m live_llm -rs
# 1 skipped, 42 deselected; optional openai dependency is not installed

LLM_ABM_RUN_LIVE_LLM=1 pytest -q -m live_llm -rs
# 1 skipped, 42 deselected; optional openai dependency is not installed

ruff check .
# All checks passed

ruff format --check .
# 28 files already formatted

mypy src
# Success: no issues found in 16 source files

python -m py_compile $(find src tests -name '*.py' -print)
# passed

python -m llm_abm_sim.run --config configs/fixtures/realistic_marketing_dataset.yaml --output runs/realistic-marketing-dataset
# wrote runs/realistic-marketing-dataset
```

## Sample output path

`runs/realistic-marketing-dataset/` contains:

- `config.json`
- `realistic_marketing_dataset.yaml`
- `dataset_validation.json`
- `run_result.json`
- `events.json`
- `metrics_summary.json`
- `step_records.csv`
- `report.html`

Observed deterministic metrics include 36 total agents, 21 final exposed, 15 final engaged, and diffusion depth 3.

## Remaining limitations

- Edge weights and preserved profile extras are loaded and reported but not yet used by exposure/decision scoring beyond current graph topology and validated preference fields.
- The realistic fixture is commit-safe and real-like, not a private/raw production dataset.
- Live LLM smoke did not make a network call in this environment because the optional `openai` dependency is absent; it skipped closed with a redacted reason.
- No Phase 5+ work was added: no dashboards, databases, cache persistence, CI, Mesa, LangChain, LangGraph, or GenericAgent.
