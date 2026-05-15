# Phase 05 Handoff - Live LLM Provider Closure + Static Report Enrichment

## Summary

Closed the live-provider gap and enriched the generated static report. Default simulator operation remains offline/no-key/no-network; live provider execution now requires the explicit `LLM_ABM_RUN_LIVE_LLM=1` gate plus local optional `llm` extra/provider readiness.

## Changed files

- `configs/live/provider_smoke.yaml` — committed no-secret live smoke config using Codex provider metadata at runtime.
- `docs/provider-config.md` — documents live smoke config, optional extra strategy, and sanitized provider artifact policy.
- `docs/development-guide.md` — adds manual live provider smoke command.
- `src/llm_abm_sim/decision.py` — adds `decision_source` and optional sanitized `provider_metadata` to `EngageDecision`.
- `src/llm_abm_sim/provider_config.py` — sanitizes URL metadata by stripping query/fragment/userinfo.
- `src/llm_abm_sim/providers/openai_compatible.py` — stamps provider decisions/fail-closed decisions with source metadata and supports the configured wire API.
- `src/llm_abm_sim/runner.py` — passes sanitized provider readiness metadata to output writers.
- `src/llm_abm_sim/schemas.py` — keeps provider config metadata URL-sanitized.
- `src/llm_abm_sim/outputs.py` — enriches static HTML report and writes `decision_source_summary` / sanitized `provider_evidence` in metrics output.
- `tests/e2e/test_live_llm_gate.py` — asserts gated live path really returns a provider-sourced decision.
- `tests/integration/test_mocked_provider_runner.py` — updates mocked provider evidence assertions.
- `tests/playwright/report-smoke.spec.ts` — validates enriched static report sections with stable `data-testid` hooks.
- `tests/unit/test_provider_adapter.py` — updates provider source/metadata expectations.
- `.omx/experiments/phase5-live-visual-scorecard.md` — mode scorecard and comparison record.
- `.omx/phase-handoffs/phase-05-live-llm-visual-evolution.md` — this handoff.

## Live provider proof

Sanitized provider readiness observed in this run:

- provider: `sub2api`
- base URL host/path: `https://api.q1ngyuan.top`
- wire API: `responses`
- model: `gpt-5.5`
- `requires_openai_auth`: true
- auth availability: true
- optional SDK installed locally via `python -m pip install -e '.[llm]'`

Commands/proof:

- `LLM_ABM_RUN_LIVE_LLM=1 pytest -q -m live_llm -rs` -> `1 passed, 43 deselected`.
- `LLM_ABM_RUN_LIVE_LLM=1 python -m llm_abm_sim.run --config configs/live/provider_smoke.yaml --output runs/live-provider-smoke` -> wrote `runs/live-provider-smoke`.
- `runs/live-provider-smoke/metrics_summary.json` includes `decision_source_summary: {"provider": 1}` and `provider_evidence.provider_decision_count: 1`.
- First live smoke decision artifact: user `live_u1`, action `like`, probability `0.82`, confidence `0.86`; reason is provider text but no raw request/response or credentials are written.

## Final verification command evidence

All commands were run from `/Users/lqy/work/llm-abm-marketing-sim` with `. .venv/bin/activate` unless noted.

| Command | Result |
|---|---|
| `pytest -q` | `43 passed, 1 deselected in 1.33s` |
| `pytest -q tests/e2e` | `3 passed, 1 deselected in 1.52s` |
| `pytest -q -m live_llm -rs` | `1 skipped, 43 deselected`; skip is expected because live gate is not set |
| `LLM_ABM_RUN_LIVE_LLM=1 pytest -q -m live_llm -rs` | `1 passed, 43 deselected in 5.91s` |
| `ruff check .` | `All checks passed!` |
| `ruff format --check .` | `28 files already formatted` |
| `mypy src` | `Success: no issues found in 16 source files` |
| `python -m py_compile $(find src tests -name '*.py' -print)` | passed, no compiler output |
| `python -m llm_abm_sim.run --config configs/fixtures/realistic_marketing_dataset.yaml --output runs/realistic-marketing-dataset` | wrote `runs/realistic-marketing-dataset`; `decision_source_summary: {"rule_based": 31}` |
| `npx playwright test` | `1 passed (2.0s)`; report opens from disk and enriched sections are asserted |
| `LLM_ABM_RUN_LIVE_LLM=1 python -m llm_abm_sim.run --config configs/live/provider_smoke.yaml --output runs/live-provider-smoke` | wrote `runs/live-provider-smoke`; `decision_source_summary: {"provider": 1}`, `provider_decision_count: 1` |

Secret scan note: grep over retained run outputs and phase handoff/scorecard found no API-key/token-shaped values; matches were only safety prose such as “bearer tokens” in the privacy notice.

## Static report artifact paths

- Realistic dataset report: `runs/realistic-marketing-dataset/report.html`
- Live provider smoke report: `runs/live-provider-smoke/report.html`
- Playwright HTML artifact coverage: `npx playwright test` validates the report opens from disk and contains summary, metric cards, trend chart, dataset validation, seed/key user, and provider evidence sections.

## Output paths

- `runs/realistic-marketing-dataset/`
- `runs/live-provider-smoke/`

## Scorecard

- `.omx/experiments/phase5-live-visual-scorecard.md`
- Score: 96/100. Main improvement over earlier `ralphy-omx` evidence: true live provider pytest and CLI smoke replaced the dependency-missing live skip.

## Remaining risks

- Live provider availability may be intermittent and may incur cost; keep it manually gated.
- Codex auth/provider config shape may drift; failures should remain redacted and fail closed.
- Static HTML report is intentionally dependency-free; richer interactive visuals are out of scope for this phase.

## Workspace status

Run `git status --short` for current review state. Generated run outputs are under ignored `runs/`; no secrets are intentionally written or committed.
