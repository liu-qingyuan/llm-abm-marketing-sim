from __future__ import annotations

import csv
import json
import shutil
from html import escape
from pathlib import Path
from typing import Any

from .events import SimulationRunResult
from .schemas import SimulationInput


def write_run_outputs(result: SimulationRunResult, config: SimulationInput, output_dir: str | Path) -> Path:
    """Write deterministic run artifacts and return the output directory."""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    (output_path / "config.json").write_text(
        json.dumps(config.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output_path / "run_result.json").write_text(
        json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output_path / "metrics_summary.json").write_text(
        json.dumps(result.metrics_summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _write_step_records_csv(result, output_path / "step_records.csv")
    _write_events_json(result, output_path / "events.json")
    write_report_html(result, config, output_path / "report.html")
    return output_path


def copy_config_source(config_path: str | Path, output_dir: str | Path) -> None:
    """Copy the source config next to normalized config artifacts when available."""

    source = Path(config_path)
    if source.exists():
        shutil.copyfile(source, Path(output_dir) / source.name)


def write_report_html(result: SimulationRunResult, config: SimulationInput, path: str | Path) -> Path:
    """Write a minimal static HTML report for Playwright smoke validation."""

    path = Path(path)
    title = escape(config.report.title)
    run_id = escape(result.run_id)
    metrics_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in sorted(result.metrics_summary.items())
    )
    step_rows = "\n".join(
        "<tr>"
        f"<td>{step.time_step}</td>"
        f"<td>{step.exposed_count}</td>"
        f"<td>{step.engaged_count}</td>"
        f"<td>{step.new_exposed_count}</td>"
        f"<td>{step.new_engaged_count}</td>"
        f"<td>{len(step.exposure_events)}</td>"
        f"<td>{len(step.decision_events)}</td>"
        f"<td>{len(step.action_events)}</td>"
        "</tr>"
        for step in result.step_records
    )
    path.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
</head>
<body>
  <main data-testid="simulation-report">
    <h1>{title}</h1>
    <section data-testid="run-summary">
      <h2>Run Summary</h2>
      <p>Run ID: <strong data-testid="run-id">{run_id}</strong></p>
      <p>Random Seed: <span data-testid="random-seed">{result.random_seed}</span></p>
      <p>Horizon: <span data-testid="horizon">{result.horizon}</span></p>
    </section>
    <section data-testid="metrics-section">
      <h2>Metrics</h2>
      <table><tbody>{metrics_rows}</tbody></table>
    </section>
    <section data-testid="events-section">
      <h2>Step Records</h2>
      <table>
        <thead><tr><th>Step</th><th>Exposed</th><th>Engaged</th><th>New Exposed</th><th>New Engaged</th><th>Exposure Events</th><th>Decision Events</th><th>Action Events</th></tr></thead>
        <tbody>{step_rows}</tbody>
      </table>
    </section>
  </main>
</body>
</html>
""",
        encoding="utf-8",
    )
    return path


def _write_step_records_csv(result: SimulationRunResult, path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["time_step", "exposed_count", "engaged_count", "new_exposed_count", "new_engaged_count"],
        )
        writer.writeheader()
        for step in result.step_records:
            writer.writerow(
                {
                    "time_step": step.time_step,
                    "exposed_count": step.exposed_count,
                    "engaged_count": step.engaged_count,
                    "new_exposed_count": step.new_exposed_count,
                    "new_engaged_count": step.new_engaged_count,
                }
            )


def _write_events_json(result: SimulationRunResult, path: Path) -> None:
    events: dict[str, list[dict[str, Any]]] = {
        "exposure_events": [event.model_dump(mode="json") for event in result.exposure_events],
        "decision_events": [event.model_dump(mode="json") for event in result.decision_events],
        "action_events": [event.model_dump(mode="json") for event in result.action_events],
    }
    path.write_text(json.dumps(events, indent=2, sort_keys=True), encoding="utf-8")
