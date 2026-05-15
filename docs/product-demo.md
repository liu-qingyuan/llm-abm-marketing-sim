# Product Demo: 90% Local Prototype

This milestone turns the simulator into a reviewable local product prototype: a non-developer can inspect inputs, run deterministic demos, open a bilingual report, and understand whether decisions came from the offline baseline or an opt-in provider path.

## Demo 1: default offline run

```bash
. .venv/bin/activate
python -m llm_abm_sim.run --config configs/default.yaml --output runs/sample
```

Open:

- `runs/sample/report.html` — bilingual report with language toggle.
- `runs/sample/input-builder.html` — static bilingual config builder/template.
- `runs/sample/graph_trace.json` — safe graph + Agent decision trace.
- `runs/sample/report_payload.json` — sanitized report view-model consumed by HTML.

Expected product behavior:

1. The report opens without a server or network.
2. The language selector switches between English and Chinese labels/explanations.
3. “How to Read This Simulation” explains the ABM framing.
4. “Inputs Used” shows post, seed users, platform context, graph/profile counts, and decision mode.
5. The interactive trace lets the reviewer choose a time step/node and inspect Agent input/output.
6. Provider evidence shows the offline rule-based baseline when no provider is enabled.

## Demo 2: realistic marketing dataset

```bash
. .venv/bin/activate
python -m llm_abm_sim.run \
  --config configs/fixtures/realistic_marketing_dataset.yaml \
  --output runs/realistic-sample
```

Open:

- `runs/realistic-sample/report.html`
- `runs/realistic-sample/dataset_validation.json`

Expected product behavior:

- Dataset validation reports profile/edge counts and policy status.
- The report narrative explains reach, engagement, and decision sources.
- The graph trace exposes per-user decision input summaries without secrets.

## Demo 3: static input builder

The input builder is written beside every run as `input-builder.html`. It contains a typed default YAML generated from `SimulationInput`, not a duplicated hand-authored JavaScript config.

Recommended flow:

1. Open `runs/sample/input-builder.html`.
2. Switch Builder language between English and Chinese.
3. Edit or copy the generated YAML.
4. Save it as `builder-config.yaml`.
5. Run:

```bash
python -m llm_abm_sim.run --config builder-config.yaml --output runs/builder-demo
```

Supported fields include run ID, seed, post text/media/topics, platform context, horizon/time-step/seed users, inline profiles/edges, provider mode, and report language.

## Provider-backed smoke path

Default tests and demos stay offline. A real provider run is manual and requires both explicit config and `LLM_ABM_RUN_LIVE_LLM=1`:

```bash
LLM_ABM_RUN_LIVE_LLM=1 python -m llm_abm_sim.run \
  --config configs/live/provider_smoke.yaml \
  --output runs/live-provider-smoke
```

Provider artifacts expose only allowlisted evidence: provider name, sanitized base URL, model, wire API, adapter/version, readiness booleans, fail-closed action, prompt version, provider decision count, and decision source summary. Raw prompts, raw responses, headers, cookies, tokens, auth files, and credential paths are not serialized.

## Manual review checklist

- [ ] `report.html` answers: what this simulates, what inputs were used, what happened, what metrics mean, and whether LLM/provider mode was used.
- [ ] Language toggle visibly switches English/Chinese copy.
- [ ] Agent I/O panel shows post/profile/peer/platform/time/prompt-version input and `EngageDecision` output.
- [ ] `input-builder.html` provides bilingual field help and a runnable config template.
- [ ] Default artifacts contain no secrets and require no API key/network.

## Local Web Console polished dashboard

Start the SaaS-like single-user local Web console:

```bash
. .venv/bin/activate
python -m pip install -e ".[dev,web]"
python -m llm_abm_sim.web --host 127.0.0.1 --port 8000 --artifact-root runs/web
# or: llm-abm-web --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. The polished Web console keeps the same FastAPI + static HTML/CSS/JS architecture while organizing the browser flow into a bilingual dashboard:

1. **Hero and provider strip** — states the local review purpose, shows product provider readiness, and keeps mock mode visibly labeled as test/dev.
2. **Stepper workflow** — guides reviewers through Data -> Scenario -> Run -> Results without changing backend contracts.
3. **Data and scenario cards** — add helper text for uploads, seed users, marketing post, topics, media summary, platform context, and horizon.
4. **Results dashboard** — starts with an executive summary and metric descriptions before trend bars, network timeline, dataset diagnostics, provider evidence, Agent I/O, and key influencers.
5. **Progressive disclosure** — safe summary cards appear before sanitized JSON; raw provider prompts/responses are never exposed.

The console exposes these stable local API contracts:

- `GET /api/health`
- `POST /api/datasets/validate`
- `GET /api/provider/readiness`
- `POST /api/runs`
- `GET /api/runs/{run_id}`
- `GET /api/runs/{run_id}/report-payload`
- `GET /api/runs/{run_id}/artifact/{name}`

Dataset uploads accept users CSV/JSON and edges CSV/JSON. Edge JSON supports both:

```json
{"edges":[{"source":"u1","target":"u2","weight":1.0}]}
```

and a bare list:

```json
[{"source":"u1","target":"u2","weight":1.0}]
```

The Web import boundary normalizes uploads into canonical local files and then validates through the existing `DatasetConfig` / `load_network_dataset` semantics. Template files are available under `configs/templates/` and through `/api/templates/users.csv`, `/api/templates/edges.csv`, `/api/templates/users.json`, and `/api/templates/edges.json`. Run creation follows the browser-safe job contract: `POST /api/runs` returns `queued`/`running`/terminal job state, and the UI polls `GET /api/runs/{run_id}` until `succeeded`, `failed`, or `blocked`.

### Provider modes

Product-mode Web runs default to provider-backed LLM decisions and preflight `/api/provider/readiness`. If the live gate, SDK, credential, or Codex provider metadata is missing, the provider strip and run prerequisite copy show `blocked`, and the run is marked `blocked` instead of silently falling back to the offline rule-based adapter. For intentional local tests, check “Use mock provider for test/dev”; this mode is visibly labeled as mock in the provider strip, result cards, report payload, and generated metadata while still avoiding network and secrets.

Manual live validation remains opt-in only:

```bash
LLM_ABM_RUN_LIVE_LLM=1 pytest -q -m live_llm -rs
```

### Result experience and safety

Successful Web runs write sanitized artifacts under `runs/web/<run-id>` by default, including `report.html`, `report_payload.json`, `graph_trace.json`, `metrics_summary.json`, `dataset_validation.json`, `events.json`, `run_result.json`, `config.json`, and `step_records.csv`. The UI shows:

- executive summary highlights for reach, engagement, and decision source;
- metric cards with plain-language descriptions;
- trend bars with an accessible table alternative;
- network propagation timeline with node-state legend and selected-step summary;
- dataset diagnostics and provider evidence summary cards;
- safe Agent I/O cards with sanitized JSON behind disclosure controls;
- key influencer summary and generated report link.

Raw prompts, raw provider responses, headers, cookies, auth fields, tokens, secrets, credentials, and forbidden uploaded profile attributes are filtered from Web responses and generated artifacts.

### Web console verification

Automated browser coverage lives in `tests/playwright/web-console.spec.ts` and exercises the polished shell, loading/disabled states, mock-provider happy path, product-provider blocked path, bilingual result labels, progressive disclosure, and artifact secret filtering:

```bash
npx playwright test tests/playwright/web-console.spec.ts
```

Manual smoke for this polish lane uses the local templates and mock provider mode:

```bash
rm -rf runs/web-ui-polish
python -m llm_abm_sim.web --host 127.0.0.1 --port 8000 --artifact-root runs/web-ui-polish
# open http://127.0.0.1:8000
# upload configs/templates/web_users.csv and configs/templates/web_edges.csv
# check “Use mock provider for test/dev”, validate, run, inspect results
rg -i 'sk-|Bearer|authorization|cookie|access_token|raw_prompt|raw_provider|headers|credential|password|secret' runs/web-ui-polish || true
```

Expected scan result: no generated run artifact contains forbidden raw/provider/secret fragments.

