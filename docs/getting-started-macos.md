# Getting Started on macOS from Zero

This is the canonical fresh-start guide (`docs/getting-started-macos.md`) for running `llm-abm-marketing-sim` on a new macOS machine. It covers the deterministic CLI demo, the local Web console, test/dev mock provider mode, optional live LLM provider mode, generated artifacts, troubleshooting, and cleanup.

The default path is offline and deterministic: it does **not** need an API key, does **not** call a live LLM, and writes all run artifacts under ignored `runs/` directories.

## 1. What you will have at the end

After following the full local setup path, you should be able to run:

```bash
python -m llm_abm_sim.run --config configs/default.yaml --output runs/sample
python -m llm_abm_sim.run --config configs/fixtures/realistic_marketing_dataset.yaml --output runs/realistic-sample
python -m llm_abm_sim.web --host 127.0.0.1 --port 8000 --artifact-root runs/web
```

Then open:

```text
http://127.0.0.1:8000
```

## 2. macOS prerequisites

Install Apple command-line tools if this is a fresh Mac:

```bash
xcode-select --install
```

Install Python and Node. Homebrew is the simplest common path on macOS:

```bash
brew install python node
python3 --version
node --version
npm --version
```

Requirements:

- Python 3.10 or newer.
- Node.js 18 or newer.
- npm, bundled with Node.
- Terminal access to create a Python virtual environment.

If you prefer `pyenv`, `asdf`, or another version manager, that is fine as long as `python3` resolves to Python 3.10+ and `node` resolves to Node 18+.

## 3. Clone the repository

Use the repository URL you were given by the maintainer. Example shape:

```bash
mkdir -p ~/work
cd ~/work
git clone <repository-url> llm-abm-marketing-sim
cd llm-abm-marketing-sim
```

All following commands assume your shell is inside the repository root.

## 4. Create and activate the Python environment

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
```

Install the full local product/development stack:

```bash
python -m pip install -e ".[dev,web,llm]"
```

What the extras mean:

- `dev`: tests, linting, and type-check tooling.
- `web`: local FastAPI/Uvicorn Web console support.
- `llm`: optional OpenAI-compatible SDK support for explicitly gated live provider runs.

For a minimal CLI-only development install, use:

```bash
python -m pip install -e ".[dev]"
```

## 5. Install browser test dependencies

The Web console and static report are ordinary local HTML/JS surfaces. Automated browser checks use Playwright:

```bash
npm ci
npx playwright install chromium
```

Use `npm ci` for reproducible installs from `package-lock.json`.

## 6. Run the default offline CLI simulation

```bash
. .venv/bin/activate
python -m llm_abm_sim.run --config configs/default.yaml --output runs/sample
```

Expected files under `runs/sample/` include:

```text
config.json
run_result.json
events.json
metrics_summary.json
step_records.csv
report.html
report_payload.json
graph_trace.json
input-builder.html
```

Open the report directly from Finder or Terminal:

```bash
open runs/sample/report.html
open runs/sample/input-builder.html
```

The report is bilingual (`en-US` / `zh-CN`) and shows the post, seed users, graph/profile summary, metrics, decision-source evidence, and an Agent input/output trace. The default decision source is the deterministic rule-based baseline.

## 7. Run the realistic marketing fixture

```bash
. .venv/bin/activate
python -m llm_abm_sim.run \
  --config configs/fixtures/realistic_marketing_dataset.yaml \
  --output runs/realistic-sample
```

Expected extra artifact:

```text
runs/realistic-sample/dataset_validation.json
```

This fixture uses commit-safe, real-like CSV data under `tests/fixtures/datasets/`. Relative dataset paths in configs resolve from the config file's directory, so the fixture can run from a fresh clone without editing paths.

## 8. Start the local Web console

Install the `web` extra first if you used the minimal CLI install:

```bash
python -m pip install -e ".[dev,web,llm]"
```

Start the local single-user console:

```bash
. .venv/bin/activate
python -m llm_abm_sim.web --host 127.0.0.1 --port 8000 --artifact-root runs/web
```

Alternative installed script:

```bash
llm-abm-web --host 127.0.0.1 --port 8000 --artifact-root runs/web
```

Open:

```text
http://127.0.0.1:8000
```

Useful local endpoints:

```text
GET  /api/health
GET  /api/provider/readiness
POST /api/datasets/validate
POST /api/runs
GET  /api/runs/{run_id}
GET  /api/runs/{run_id}/report-payload
GET  /api/runs/{run_id}/artifact/{name}
GET  /api/templates/users.csv
GET  /api/templates/edges.csv
```

### Web console mock-provider demo

For a no-network Web demo:

1. Open `http://127.0.0.1:8000`.
2. Check **Use mock provider for test/dev**.
3. Download or use these local templates:
   - `configs/templates/web_users.csv`
   - `configs/templates/web_edges.csv`
4. Upload users and edges.
5. Click **Validate dataset**.
6. Click **Start run**.
7. Inspect the results dashboard and download allowlisted artifacts.

Mock provider mode is intentionally for tests/dev only. It is visibly labeled in readiness cards, result panels, metadata, and payloads. It avoids network calls and secrets.

### Product provider behavior in the Web console

If **Use mock provider for test/dev** is unchecked, the Web console behaves like product mode: it requires a real provider to be ready. Without the explicit live gate, credentials, optional SDK, and provider metadata, the run is marked `blocked` instead of silently falling back to offline rule-based decisions.

This fail-closed behavior is expected and protects reviewers from mistaking offline demo output for live provider output.

## 9. Optional live LLM/provider mode

Live provider execution is manual and opt-in. Do not run these commands unless you intentionally want a live provider call and have credentials configured outside the repository.

Read the full provider guide first:

```text
docs/provider-config.md
```

Manual live smoke shape:

```bash
LLM_ABM_RUN_LIVE_LLM=1 python -m llm_abm_sim.run \
  --config configs/live/provider_smoke.yaml \
  --output runs/live-provider-smoke
```

Provider tests are also gated:

```bash
LLM_ABM_RUN_LIVE_LLM=1 pytest -q -m live_llm -rs
```

Credentials can come from a compatible local Codex provider configuration or an environment variable expected by the provider config. Secret values must stay outside git, logs, docs, fixtures, run artifacts, and screenshots.

## 10. Run the validation checks

For a full local verification pass after setup:

```bash
. .venv/bin/activate
ruff check .
python -m py_compile $(find src tests -name '*.py' -print)
pytest -q tests/web/test_web_api.py
python -m llm_abm_sim.run --config configs/default.yaml --output runs/sample
python -m llm_abm_sim.run --config configs/fixtures/realistic_marketing_dataset.yaml --output runs/realistic-sample
npx playwright test tests/playwright/web-console.spec.ts
```

The default tests are offline. `pytest -q` excludes live-provider tests unless you explicitly opt into the `live_llm` marker and gate.

## 11. Artifact locations

CLI default run:

```text
runs/sample/
```

Realistic fixture run:

```text
runs/realistic-sample/
```

Web console runs:

```text
runs/web/<run-id>/
```

Common generated artifacts:

```text
config.json
run_result.json
events.json
metrics_summary.json
step_records.csv
report.html
report_payload.json
graph_trace.json
input-builder.html
dataset_validation.json       # dataset-backed runs only
web_run_metadata.json         # Web console runs only
```

Generated run directories are ignored by git. Keep private/raw datasets in ignored local directories such as `data/raw/` or `data/processed/`, not in committed fixtures.

## 12. Troubleshooting

### `python3: command not found` or wrong Python version

Install or select Python 3.10+:

```bash
brew install python
python3 --version
```

Then recreate `.venv` with that interpreter.

### `pip install -e ".[dev,web,llm]"` fails on an old pip

Upgrade pip inside the virtual environment:

```bash
. .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev,web,llm]"
```

### `npm ci` fails because `package-lock.json` is missing or changed

This repository should include `package-lock.json`. From a clean clone, prefer:

```bash
npm ci
```

If you intentionally changed Node dependencies, update the lockfile in a separate reviewed change.

### Playwright says Chromium is missing

Install the browser used by the tests:

```bash
npx playwright install chromium
```

### Port 8000 is already in use

Choose another port:

```bash
python -m llm_abm_sim.web --host 127.0.0.1 --port 8010 --artifact-root runs/web
```

Then open `http://127.0.0.1:8010`.

### Web product mode is `blocked`

This is expected when live provider readiness is missing. For offline Web demos, check **Use mock provider for test/dev**. For live provider mode, confirm all of these are true:

- You intentionally set `LLM_ABM_RUN_LIVE_LLM=1` for the process that starts the server or command.
- The optional `llm` extra is installed.
- Provider metadata and runtime credentials are available outside the repository.
- You are not expecting the Web console to silently fall back to the offline adapter.

### Dataset validation fails

Check that:

- Users and edges use supported CSV/JSON formats.
- Edge `source` and `target` IDs match profile `user_id` values.
- Required columns exist.
- Relative dataset paths are correct from the directory containing the config file.

Start with the committed templates:

```text
configs/templates/web_users.csv
configs/templates/web_edges.csv
configs/templates/web_users.json
configs/templates/web_edges.json
```

### A generated report will not open in the browser

Open the HTML artifact directly:

```bash
open runs/sample/report.html
```

If the path differs, check the `--output` directory passed to the CLI or the Web run ID under `runs/web/`.

## 13. Cleanup

Stop the Web server with `Ctrl-C` in the terminal where it is running.

Remove generated local artifacts and dependency folders:

```bash
rm -rf runs test-results playwright-report blob-report
rm -rf node_modules
rm -rf .venv .ruff_cache .mypy_cache .pytest_cache
```

Recreate everything later by repeating the setup steps above.
