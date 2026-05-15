from __future__ import annotations

import csv
import json
from html import escape
from pathlib import Path
from typing import Any

import yaml

from .events import SimulationRunResult
from .graph_loader import DatasetValidationReport
from .provider_config import redact_secrets
from .schemas import SimulationInput


def write_run_outputs(
    result: SimulationRunResult,
    config: SimulationInput,
    output_dir: str | Path,
    dataset_validation_report: DatasetValidationReport | None = None,
    provider_readiness: dict[str, Any] | None = None,
) -> Path:
    """Write deterministic run artifacts and return the output directory."""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    decision_source_summary = _decision_source_summary(result)
    provider_evidence = _provider_evidence(result, provider_readiness)

    (output_path / "config.json").write_text(
        json.dumps(redact_secrets(config.model_dump(mode="json")), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output_path / "run_result.json").write_text(
        json.dumps(redact_secrets(result.model_dump(mode="json")), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    metrics_summary = dict(result.metrics_summary)
    metrics_summary["decision_source_summary"] = decision_source_summary
    if provider_evidence is not None:
        metrics_summary["provider_evidence"] = provider_evidence
    (output_path / "metrics_summary.json").write_text(
        json.dumps(redact_secrets(metrics_summary), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _write_step_records_csv(result, output_path / "step_records.csv")
    _write_events_json(result, output_path / "events.json")
    if dataset_validation_report is not None and dataset_validation_report.dataset_used:
        _write_dataset_validation_json(dataset_validation_report, output_path / "dataset_validation.json")
    write_report_html(
        result,
        config,
        output_path / "report.html",
        dataset_validation_report=dataset_validation_report,
        provider_readiness=provider_readiness,
    )
    return output_path


def copy_config_source(config_path: str | Path, output_dir: str | Path) -> None:
    """Copy the source config next to normalized config artifacts when available."""

    source = Path(config_path)
    if not source.exists():
        return
    destination = Path(output_dir) / source.name
    raw = source.read_text(encoding="utf-8")
    try:
        if source.suffix.lower() == ".json":
            payload = json.loads(raw)
            destination.write_text(json.dumps(redact_secrets(payload), indent=2, sort_keys=True), encoding="utf-8")
        else:
            payload = yaml.safe_load(raw)
            destination.write_text(yaml.safe_dump(redact_secrets(payload), sort_keys=True), encoding="utf-8")
    except Exception:
        destination.write_text(_redact_source_text(raw), encoding="utf-8")


def _redact_source_text(raw: str) -> str:
    redacted_lines: list[str] = []
    for line in raw.splitlines():
        lowered = line.lower()
        if any(
            secret in lowered
            for secret in ("api_key:", "token:", "secret:", "password:", "credential:", "authorization:", "cookie:")
        ):
            prefix = line.split(":", 1)[0]
            redacted_lines.append(f"{prefix}: <redacted>")
        else:
            redacted_lines.append(line)
    return "\n".join(redacted_lines) + ("\n" if raw.endswith("\n") else "")


def write_report_html(
    result: SimulationRunResult,
    config: SimulationInput,
    path: str | Path,
    *,
    dataset_validation_report: DatasetValidationReport | None = None,
    provider_readiness: dict[str, Any] | None = None,
) -> Path:
    """Write a static HTML report for human and Playwright smoke validation."""

    path = Path(path)
    title = escape(config.report.title)
    run_id = escape(result.run_id)
    decision_source_summary = _decision_source_summary(result)
    provider_evidence = _provider_evidence(result, provider_readiness)
    cards = _metric_cards(result.metrics_summary)
    trend_rows = _trend_rows(result)
    trend_bars = _trend_bars(result)
    dataset_html = _dataset_validation_html(dataset_validation_report)
    seed_users = ", ".join(escape(user_id) for user_id in config.simulation.seed_user_ids) or "None configured"
    raw_key_influencers = result.metrics_summary.get("key_influencers", [])
    key_influencers = raw_key_influencers if isinstance(raw_key_influencers, list) else []
    key_users = ", ".join(escape(str(user_id)) for user_id in key_influencers) if key_influencers else "None observed"
    provider_html = _provider_evidence_html(provider_evidence, decision_source_summary)

    path.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <style>
    :root {{ color-scheme: light; --bg: #f6f8fb; --card: #ffffff; --ink: #172033; --muted: #667085; --line: #d8e0eb; --accent: #2f6fed; --good: #11845b; --warn: #a15c00; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: var(--bg); color: var(--ink); }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 32px 20px 48px; }}
    h1 {{ margin: 0 0 8px; font-size: 2rem; }}
    h2 {{ margin: 0 0 16px; font-size: 1.2rem; }}
    section {{ margin-top: 22px; padding: 20px; background: var(--card); border: 1px solid var(--line); border-radius: 18px; box-shadow: 0 10px 24px rgb(16 24 40 / 6%); }}
    .subtle {{ color: var(--muted); }}
    .summary-grid, .card-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; }}
    .summary-item, .metric-card {{ padding: 14px; border: 1px solid var(--line); border-radius: 14px; background: #fbfcff; }}
    .label {{ display: block; color: var(--muted); font-size: 0.78rem; text-transform: uppercase; letter-spacing: .04em; }}
    .value {{ display: block; margin-top: 6px; font-size: 1.4rem; font-weight: 760; }}
    table {{ width: 100%; border-collapse: collapse; overflow: hidden; border-radius: 12px; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }}
    th {{ color: var(--muted); font-size: .82rem; background: #f0f4fa; }}
    .trend {{ display: grid; gap: 8px; }}
    .bar-row {{ display: grid; grid-template-columns: 64px 1fr 80px; align-items: center; gap: 10px; }}
    .bar-track {{ height: 14px; border-radius: 999px; background: #e7edf6; overflow: hidden; }}
    .bar {{ height: 100%; min-width: 2px; border-radius: inherit; background: linear-gradient(90deg, var(--accent), #46c2a7); }}
    .pill {{ display: inline-flex; align-items: center; border-radius: 999px; padding: 4px 10px; background: #eef4ff; color: #174ea6; font-weight: 650; font-size: .82rem; }}
    .pill.good {{ background: #e8f6ef; color: var(--good); }}
    .pill.warn {{ background: #fff3e0; color: var(--warn); }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; padding: 12px; border-radius: 12px; background: #0f172a; color: #e2e8f0; }}
  </style>
</head>
<body>
  <main data-testid="simulation-report">
    <header>
      <h1>{title}</h1>
      <p class="subtle">Static ABM diffusion report generated from local run artifacts.</p>
    </header>
    <section data-testid="run-summary">
      <h2>Run Summary</h2>
      <div class="summary-grid">
        <div class="summary-item"><span class="label">Run ID</span><strong class="value" data-testid="run-id">{run_id}</strong></div>
        <div class="summary-item"><span class="label">Random Seed</span><span class="value" data-testid="random-seed">{result.random_seed}</span></div>
        <div class="summary-item"><span class="label">Horizon</span><span class="value" data-testid="horizon">{result.horizon}</span></div>
        <div class="summary-item"><span class="label">Observation Window</span><span class="value">{escape(str(config.simulation.observation_window or "not specified"))}</span></div>
      </div>
    </section>
    <section data-testid="metrics-section">
      <h2>Key Metrics</h2>
      <div class="card-grid" data-testid="metrics-cards">{cards}</div>
    </section>
    <section data-testid="trend-section">
      <h2>Exposure / Engagement Trend</h2>
      <div class="trend" data-testid="trend-chart">{trend_bars}</div>
      <table data-testid="step-records-table">
        <thead><tr><th>Step</th><th>Exposed</th><th>Engaged</th><th>New Exposed</th><th>New Engaged</th><th>Exposure Events</th><th>Decision Events</th><th>Action Events</th></tr></thead>
        <tbody>{trend_rows}</tbody>
      </table>
    </section>
    <section data-testid="dataset-validation-section">
      <h2>Dataset Validation</h2>
      {dataset_html}
    </section>
    <section data-testid="seed-users-section">
      <h2>Seed Users and Key Influencers</h2>
      <p><span class="label">Configured seed users</span><span data-testid="seed-users">{seed_users}</span></p>
      <p><span class="label">Observed key influencers</span><span data-testid="key-influencers">{key_users}</span></p>
    </section>
    <section data-testid="provider-evidence-section">
      <h2>Provider / Decision Source Evidence</h2>
      {provider_html}
    </section>
  </main>
</body>
</html>
""",
        encoding="utf-8",
    )
    return path


def _metric_cards(metrics: dict[str, float | int | list[str] | dict[str, int]]) -> str:
    keys = [
        "total_agents",
        "final_exposed",
        "final_engaged",
        "reach_rate",
        "engagement_rate",
        "diffusion_depth",
        "spread_speed",
        "like_count",
        "comment_count",
        "share_count",
    ]
    cards: list[str] = []
    for key in keys:
        if key not in metrics:
            continue
        cards.append(
            f'<article class="metric-card" data-testid="metric-card-{escape(key)}">'
            f'<span class="label">{escape(key.replace("_", " ").title())}</span>'
            f'<span class="value">{escape(str(metrics[key]))}</span>'
            "</article>"
        )
    return "\n".join(cards)


def _trend_rows(result: SimulationRunResult) -> str:
    return "\n".join(
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


def _trend_bars(result: SimulationRunResult) -> str:
    max_total = max([1, *[max(step.exposed_count, step.engaged_count) for step in result.step_records]])
    rows: list[str] = []
    for step in result.step_records:
        exposed_width = round((step.exposed_count / max_total) * 100, 2)
        engaged_width = round((step.engaged_count / max_total) * 100, 2)
        rows.append(
            f'<div class="bar-row" data-testid="trend-step-{step.time_step}">'
            f"<span>Step {step.time_step}</span>"
            f'<div><div class="bar-track" title="exposed"><div class="bar" style="width:{exposed_width}%"></div></div>'
            f'<div class="bar-track" title="engaged"><div class="bar" style="width:{engaged_width}%; background: linear-gradient(90deg, #11845b, #46c2a7);"></div></div></div>'
            f"<span>{step.exposed_count}/{step.engaged_count}</span></div>"
        )
    return "\n".join(rows)


def _dataset_validation_html(report: DatasetValidationReport | None) -> str:
    if report is None or not report.dataset_used:
        return '<p data-testid="dataset-validation-summary">Inline config dataset; no external dataset validation file was required.</p>'
    status = "PASS" if not report.errors else "ERROR"
    status_class = "good" if not report.errors else "warn"
    rows = {
        "status": status,
        "directed": report.directed,
        "graph_nodes": report.graph_node_count,
        "graph_edges": report.graph_edge_count,
        "profiles": report.profile_count,
        "missing_profiles": ", ".join(report.missing_profile_ids) or "none",
        "extra_profiles": ", ".join(report.extra_profile_ids) or "none",
        "covered_seed_users": ", ".join(report.covered_seed_user_ids) or "none",
        "preserved_profile_attributes": ", ".join(report.preserved_profile_attribute_columns) or "none",
    }
    table_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>" for key, value in rows.items()
    )
    return (
        f'<p data-testid="dataset-validation-summary"><span class="pill {status_class}">{status}</span> '
        f"{report.graph_node_count} nodes / {report.graph_edge_count} edges / {report.profile_count} profiles</p>"
        f"<table><tbody>{table_rows}</tbody></table>"
    )


def _provider_evidence_html(provider_evidence: dict[str, Any] | None, source_summary: dict[str, int]) -> str:
    safe_summary = escape(json.dumps(redact_secrets(source_summary), sort_keys=True))
    if provider_evidence is None:
        return (
            '<p data-testid="decision-source-summary"><span class="pill">offline</span> '
            f"Decision sources: {safe_summary}</p>"
        )
    safe_payload = escape(json.dumps(redact_secrets(provider_evidence), indent=2, sort_keys=True))
    provider_count = source_summary.get("provider", 0)
    badge_class = "good" if provider_count else "warn"
    badge_text = (
        "provider-backed decision observed" if provider_count else "provider configured; no provider decision observed"
    )
    return (
        f'<p data-testid="decision-source-summary"><span class="pill {badge_class}">{badge_text}</span> '
        f"Decision sources: {safe_summary}</p>"
        '<p data-testid="provider-privacy-notice" class="subtle">Provider evidence is sanitized: credentials, bearer tokens, cookies, and raw payloads are not written.</p>'
        f'<pre data-testid="provider-metadata">{safe_payload}</pre>'
    )


def _decision_source_summary(result: SimulationRunResult) -> dict[str, int]:
    summary: dict[str, int] = {}
    for event in result.decision_events:
        source = event.decision.decision_source or "unknown"
        summary[source] = summary.get(source, 0) + 1
    return dict(sorted(summary.items()))


def _provider_evidence(
    result: SimulationRunResult, provider_readiness: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    provider_decisions = [event for event in result.decision_events if event.decision.decision_source == "provider"]
    if provider_readiness is None and not provider_decisions:
        return None
    evidence: dict[str, Any] = {
        "decision_source_summary": _decision_source_summary(result),
        "provider_decision_count": len(provider_decisions),
    }
    if provider_decisions:
        first = provider_decisions[0]
        evidence["first_provider_decision"] = {
            "time_step": first.time_step,
            "user_id": first.user_id,
            "action": first.decision.action,
            "probability": first.decision.probability,
            "confidence": first.decision.confidence,
            "reason": first.decision.reason,
        }
        evidence["provider_metadata"] = first.decision.provider_metadata
    if provider_readiness is not None:
        evidence["provider_readiness"] = provider_readiness
    return redact_secrets(evidence)


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
    path.write_text(json.dumps(redact_secrets(events), indent=2, sort_keys=True), encoding="utf-8")


def _write_dataset_validation_json(report: DatasetValidationReport, path: Path) -> None:
    path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
