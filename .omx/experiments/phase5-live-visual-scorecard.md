# Phase 5 Scorecard - Live LLM Provider Closure + Static Report Enrichment

Date: 2026-05-15
Mode under evaluation: `ralph-omx`
Plan: `.omx/plans/plan-live-llm-visual-evolution-20260515T044010Z.md`
Spec: `.omx/specs/deep-interview-live-llm-visual-evolution.md`

## Provider readiness snapshot (sanitized)

- Optional dependency strategy: keep `openai` in optional `llm` extra; local venv prepared with `python -m pip install -e '.[llm]'`.
- Provider name: `sub2api`
- Base URL host/path: `https://api.q1ngyuan.top`
- Wire API: `responses`
- Model: `gpt-5.5`
- `requires_openai_auth`: true
- Auth availability: true
- Secret handling: no API keys, bearer tokens, cookies, auth files, raw request payloads, or raw responses are committed or written to handoff text.

## Evidence summary

- Default offline gate: `pytest -q` passes and still deselects `live_llm`.
- Manual live test gate: `LLM_ABM_RUN_LIVE_LLM=1 pytest -q -m live_llm -rs` passed with one real provider decision.
- Live CLI smoke: `LLM_ABM_RUN_LIVE_LLM=1 python -m llm_abm_sim.run --config configs/live/provider_smoke.yaml --output runs/live-provider-smoke` wrote a provider-backed decision artifact.
- Live artifact proof: `runs/live-provider-smoke/metrics_summary.json` has `decision_source_summary.provider == 1` and `provider_evidence.provider_decision_count == 1`.
- Static report proof: enriched `report.html` sections are covered by `npx playwright test` using stable `data-testid` hooks.

## 100-point rubric score

| Category | Max | Score | Evidence |
|---|---:|---:|---|
| Requirement completeness | 15 | 15 | Live provider closure, smoke config, enriched report, scorecard, handoff artifacts completed. |
| Verification quality and freshness | 15 | 15 | Full required command set run fresh in `.venv`; live and offline commands both exercised. |
| True E2E evidence | 12 | 12 | Real provider pytest plus live CLI smoke wrote run artifacts. |
| Offline/no-secret safety | 12 | 12 | Default tests remain offline; outputs redact secrets and only serialize allowlisted provider metadata. |
| Handoff/report quality | 10 | 9 | Handoff and report artifacts name changed files, commands, paths, risks; no screenshot was necessary because static HTML artifact path is retained. |
| Loop control and premature-completion resistance | 10 | 10 | Did not finish at Phase 3 skip-safe status; required true live provider pass before closure. |
| Workspace and runtime cleanup hygiene | 10 | 9 | Run artifacts stay under ignored `runs/`; no worktree/runtime clone residue. Local `.venv` dependency install is intentional. |
| Commit hygiene | 8 | 7 | No automatic commit made in this Codex App surface; changes remain reviewable with focused diffs. |
| Runtime cost/time efficiency | 5 | 4 | Single live pytest plus two live CLI smokes; small unavoidable provider cost. |
| Developer ergonomics/debuggability | 3 | 3 | Dedicated `configs/live/provider_smoke.yaml`, report test ids, and provider evidence fields. |
| **Total** | **100** | **96** | `ralph-omx` improved over the earlier `ralphy-omx` Phase 4 outcome by closing the live-call gap instead of recording a dependency-missing skip. |

## Comparison note

Prior `ralphy-omx`/Phase 4 evidence ended with live LLM skipped because the optional `openai` dependency was absent. This `ralph-omx` run prepared the optional local venv, kept the dependency optional in `pyproject.toml`, and produced true provider-backed pytest and CLI evidence. For similar closure tasks, reuse this pattern: keep defaults offline, prepare optional extras locally, require gated live evidence before promise completion.

## Limitations / next recommended mode

- Provider availability can still be intermittent; future runs should treat provider transport failures as environment evidence, not default-test failures.
- The report is intentionally static HTML/CSS; if richer visual analysis is needed, use a later design/visual workflow rather than adding a frontend stack by default.
- Recommended next mode: solo execute or `ralph-omx` for gated closure tasks; `ralplan` first only if adding non-static dashboards or changing dependency policy.


## Fresh Iteration 2 verification refresh

- `pytest -q` -> `43 passed, 1 deselected in 1.45s`.
- `pytest -q tests/e2e` -> `3 passed, 1 deselected in 1.53s`.
- `pytest -q -m live_llm -rs` -> `1 skipped, 43 deselected` with gate unset.
- `LLM_ABM_RUN_LIVE_LLM=1 pytest -q -m live_llm -rs` -> `1 passed, 43 deselected in 5.91s`.
- Live CLI smoke rewrote `runs/live-provider-smoke`; `provider_decision_count == 1`, first decision action `like`, probability `0.82`, confidence `0.86`.
- `npx playwright test` -> `1 passed (2.0s)`.
- Secret-shaped scan over retained run outputs plus this handoff/scorecard found no API-key/token-shaped values.

## Fresh Iteration 3 verification refresh

- Preflight: local `.venv` Python 3.14.3; optional `openai` dependency installed; Codex provider readiness sanitized as `sub2api`, `https://api.q1ngyuan.top`, `responses`, model `gpt-5.5`, `requires_openai_auth=true`, `auth_available=true`.
- `pytest -q` -> `43 passed, 1 deselected in 2.16s`.
- `pytest -q tests/e2e` -> `3 passed, 1 deselected in 1.85s`.
- `pytest -q -m live_llm -rs` -> `1 skipped, 43 deselected in 0.34s` with gate unset.
- `LLM_ABM_RUN_LIVE_LLM=1 pytest -q -m live_llm -rs` -> `1 passed, 43 deselected in 5.37s`.
- `ruff check .` and `ruff format --check .` -> all checks passed / 28 files already formatted.
- `mypy src` -> `Success: no issues found in 16 source files`.
- `python -m py_compile $(find src tests -name '*.py' -print)` -> passed with no output.
- `python -m llm_abm_sim.run --config configs/fixtures/realistic_marketing_dataset.yaml --output runs/realistic-marketing-dataset` -> wrote `runs/realistic-marketing-dataset`; `decision_source_summary == {'rule_based': 31}`.
- `LLM_ABM_RUN_LIVE_LLM=1 python -m llm_abm_sim.run --config configs/live/provider_smoke.yaml --output runs/live-provider-smoke` -> wrote `runs/live-provider-smoke`; `decision_source_summary == {'provider': 1}` and `provider_decision_count == 1`.
- `npx playwright test` -> `1 passed (2.3s)`; report smoke validates enriched static sections and `data-testid` hooks.
- Secret-shaped scan over retained run outputs plus this Phase 5 scorecard -> `secret_scan_ok 16 files`.
