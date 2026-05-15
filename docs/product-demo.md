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
