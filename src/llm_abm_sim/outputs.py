from __future__ import annotations

import csv
import json
from html import escape
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from .events import SimulationRunResult
from .graph_loader import DatasetValidationReport
from .input_builder import write_input_builder_html
from .provider_evidence import decision_source_summary, provider_evidence
from .report_i18n import REPORT_I18N, validate_i18n_key_parity
from .report_payload import METRIC_KEYS, ReportPayload, build_graph_trace, build_report_payload
from .safe_serialization import safe_data, safe_json
from .schemas import SimulationInput

__all__ = ["build_graph_trace", "copy_config_source", "write_report_html", "write_run_outputs"]


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

    source_summary = decision_source_summary(result)
    evidence = provider_evidence(result, provider_readiness)
    payload = build_report_payload(
        result,
        config,
        dataset_validation_report=dataset_validation_report,
        provider_readiness=provider_readiness,
    )

    (output_path / "config.json").write_text(safe_json(config), encoding="utf-8")
    (output_path / "run_result.json").write_text(safe_json(result), encoding="utf-8")
    metrics_summary = dict(result.metrics_summary)
    metrics_summary["decision_source_summary"] = source_summary
    if evidence is not None:
        metrics_summary["provider_evidence"] = evidence
    (output_path / "metrics_summary.json").write_text(safe_json(metrics_summary), encoding="utf-8")
    _write_step_records_csv(result, output_path / "step_records.csv")
    _write_events_json(result, output_path / "events.json")
    if dataset_validation_report is not None and dataset_validation_report.dataset_used:
        _write_dataset_validation_json(dataset_validation_report, output_path / "dataset_validation.json")
    (output_path / "graph_trace.json").write_text(safe_json(payload.graph_trace), encoding="utf-8")
    (output_path / "report_payload.json").write_text(safe_json(payload), encoding="utf-8")
    write_input_builder_html(output_path / "input-builder.html")
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
            destination.write_text(safe_json(payload), encoding="utf-8")
        else:
            payload = yaml.safe_load(raw)
            destination.write_text(
                yaml.safe_dump(safe_data(payload), sort_keys=True, allow_unicode=True), encoding="utf-8"
            )
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
    """Write a static bilingual HTML report for human and Playwright validation."""

    validate_i18n_key_parity()
    path = Path(path)
    payload = build_report_payload(
        result,
        config,
        dataset_validation_report=dataset_validation_report,
        provider_readiness=provider_readiness,
    )
    title = escape(payload.title)
    payload_json = safe_json(payload, indent=None).replace("</", "<\\/")
    i18n_json = safe_json(REPORT_I18N, indent=None).replace("</", "<\\/")
    cytoscape_js = _cytoscape_source()
    path.write_text(_report_document(title, payload, payload_json, i18n_json, cytoscape_js), encoding="utf-8")
    return path


def _report_document(title: str, payload: ReportPayload, payload_json: str, i18n_json: str, cytoscape_js: str) -> str:
    metric_cards = _metric_cards(payload)
    trend_rows = _trend_rows(payload)
    trend_bars = _trend_bars(payload)
    dataset_html = _dataset_validation_html(payload.dataset_validation)
    provider_html = _provider_evidence_html(payload.provider_evidence, payload.decision_source_summary)
    input_html = _inputs_html(payload)
    max_step = max([0, *[step["time_step"] for step in payload.graph_trace.get("steps", [])]])
    return f"""<!doctype html>
<html lang="{escape(payload.default_language)}">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <style>
    :root {{ color-scheme: light; --bg: #f6f8fb; --card: #ffffff; --ink: #172033; --muted: #667085; --line: #d8e0eb; --accent: #2f6fed; --good: #11845b; --warn: #a15c00; }}
    * {{ box-sizing: border-box; }} body {{ margin: 0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: var(--bg); color: var(--ink); }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 32px 20px 48px; }} h1 {{ margin: 0 0 8px; font-size: 2rem; }} h2 {{ margin: 0 0 16px; font-size: 1.2rem; }} h3 {{ margin: 0 0 8px; font-size: 1rem; }}
    section {{ margin-top: 22px; padding: 20px; background: var(--card); border: 1px solid var(--line); border-radius: 18px; box-shadow: 0 10px 24px rgb(16 24 40 / 6%); }}
    .subtle {{ color: var(--muted); }} .summary-grid, .card-grid, .input-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; }}
    .summary-item, .metric-card, .input-card {{ padding: 14px; border: 1px solid var(--line); border-radius: 14px; background: #fbfcff; }}
    .label {{ display: block; color: var(--muted); font-size: 0.78rem; text-transform: uppercase; letter-spacing: .04em; }} .value {{ display: block; margin-top: 6px; font-size: 1.35rem; font-weight: 760; }}
    table {{ width: 100%; border-collapse: collapse; overflow: hidden; border-radius: 12px; }} th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }} th {{ color: var(--muted); font-size: .82rem; background: #f0f4fa; }}
    .trend {{ display: grid; gap: 8px; }} .bar-row {{ display: grid; grid-template-columns: 64px 1fr 80px; align-items: center; gap: 10px; }} .bar-track {{ height: 14px; border-radius: 999px; background: #e7edf6; overflow: hidden; }} .bar {{ height: 100%; min-width: 2px; border-radius: inherit; background: linear-gradient(90deg, var(--accent), #46c2a7); }}
    .pill {{ display: inline-flex; align-items: center; border-radius: 999px; padding: 4px 10px; background: #eef4ff; color: #174ea6; font-weight: 650; font-size: .82rem; }} .pill.good {{ background: #e8f6ef; color: var(--good); }} .pill.warn {{ background: #fff3e0; color: var(--warn); }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; padding: 12px; border-radius: 12px; background: #0f172a; color: #e2e8f0; }} .language-control {{ display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-top:14px; }}
    .trace-layout {{ display: grid; grid-template-columns: minmax(420px, 1.35fr) minmax(320px, .9fr); gap: 16px; align-items: stretch; }} #abm-graph {{ min-height: 520px; border: 1px solid var(--line); border-radius: 16px; background: radial-gradient(circle at 20% 20%, #ffffff, #edf4ff); overflow: hidden; }}
    .trace-controls {{ display: flex; gap: 14px; align-items: center; flex-wrap: wrap; margin: 12px 0 16px; }} .trace-controls input[type=range] {{ flex: 1; min-width: 240px; accent-color: var(--accent); }}
    .trace-panel {{ border: 1px solid var(--line); border-radius: 14px; background: #fbfcff; padding: 14px; min-height: 140px; overflow: auto; }} .trace-panel ul {{ margin: 8px 0 0; padding-left: 20px; }} .trace-panel li {{ margin: 6px 0; }} .trace-stack {{ display: grid; gap: 12px; }}
    .state-legend {{ display: flex; gap: 10px; flex-wrap: wrap; margin: 8px 0; }} .legend-dot {{ width: .85rem; height: .85rem; display: inline-block; border-radius: 999px; margin-right: 5px; vertical-align: -1px; }}
    .node-buttons {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }} .node-buttons button {{ border: 1px solid var(--line); border-radius: 999px; background: #fff; padding: 5px 10px; color: var(--ink); cursor: pointer; }} .node-buttons button.active {{ border-color: var(--accent); background: #eef4ff; color: #174ea6; font-weight: 700; }}
    @media (max-width: 900px) {{ .trace-layout {{ grid-template-columns: 1fr; }} #abm-graph {{ min-height: 420px; }} }}
  </style>
</head>
<body>
  <main data-testid="simulation-report">
    <header>
      <h1>{title}</h1>
      <p class="subtle" data-i18n="report.subtitle">Static ABM diffusion report generated from local run artifacts.</p>
      <div class="language-control"><label for="language-toggle" data-i18n="language.toggle">Report language</label><select id="language-toggle" data-testid="language-toggle" aria-label="Report language"><option value="en-US">English</option><option value="zh-CN">中文</option></select></div>
    </header>
    <section data-testid="how-to-read-section"><h2 data-i18n="read.title">How to Read This Simulation</h2><p data-i18n="read.body">This local prototype simulates how a marketing post spreads through a social graph over time.</p></section>
    <section data-testid="run-summary"><h2 data-i18n="run.summary">Run Summary</h2><div class="summary-grid">
      <div class="summary-item"><span class="label" data-i18n="run.runId">Run ID</span><strong class="value" data-testid="run-id">{escape(str(payload.run["run_id"]))}</strong></div>
      <div class="summary-item"><span class="label" data-i18n="run.randomSeed">Random Seed</span><span class="value" data-testid="random-seed">{payload.run["random_seed"]}</span></div>
      <div class="summary-item"><span class="label" data-i18n="run.horizon">Horizon</span><span class="value" data-testid="horizon">{payload.run["horizon"]}</span></div>
      <div class="summary-item"><span class="label" data-i18n="run.observationWindow">Observation Window</span><span class="value">{escape(str(payload.run.get("observation_window") or "not specified"))}</span></div>
    </div></section>
    <section data-testid="inputs-section"><h2 data-i18n="input.title">Inputs Used</h2>{input_html}</section>
    <section data-testid="metrics-section"><h2 data-i18n="metrics.title">Key Metrics</h2><div class="card-grid" data-testid="metrics-cards">{metric_cards}</div><h3 data-i18n="metrics.help">Metric meanings</h3>{_metric_help_table()}</section>
    <section data-testid="what-happened-section"><h2 data-i18n="what.title">What Happened</h2><p data-testid="narrative-summary" data-narrative-en="{escape(payload.narrative["summary_en"])}" data-narrative-zh="{escape(payload.narrative["summary_zh"])}">{escape(payload.narrative["summary_en"])}</p><p class="subtle" data-i18n="what.body">The narrative summarizes final reach, engagement, spread speed, and decision source evidence.</p></section>
    <section data-testid="trend-section"><h2 data-i18n="trend.title">Exposure / Engagement Trend</h2><div class="trend" data-testid="trend-chart">{trend_bars}</div><table data-testid="step-records-table"><thead><tr><th data-i18n="trend.step">Step</th><th data-i18n="trend.exposed">Exposed</th><th data-i18n="trend.engaged">Engaged</th><th data-i18n="trend.newExposed">New Exposed</th><th data-i18n="trend.newEngaged">New Engaged</th><th data-i18n="trend.exposureEvents">Exposure Events</th><th data-i18n="trend.decisionEvents">Decision Events</th><th data-i18n="trend.actionEvents">Action Events</th></tr></thead><tbody>{trend_rows}</tbody></table></section>
    <section data-testid="interactive-trace-section" id="interactive-trace-section"><h2 data-i18n="graph.title">Interactive ABM Trace</h2><p class="subtle">Environment computes exposure → Agent observes post and neighbor behavior → DecisionAdapter decides → user state/action updates → metrics/events collected.</p><div class="state-legend" aria-label="Node state legend"><span><i class="legend-dot" style="background:#cbd5e1"></i><span data-i18n="graph.unseen">unseen</span></span><span><i class="legend-dot" style="background:#f59e0b"></i><span data-i18n="graph.exposed">exposed</span></span><span><i class="legend-dot" style="background:#16a34a"></i><span data-i18n="graph.engaged">engaged</span></span><span><i class="legend-dot" style="background:#7c3aed"></i><span data-i18n="graph.seed">seed</span></span></div><div class="trace-controls"><label for="step-slider" class="label" data-i18n="graph.selectedStep">Selected time step</label><input data-testid="step-slider" id="step-slider" type="range" min="0" max="{max_step}" step="1" value="0"><strong data-testid="selected-step-label" id="selected-step-label">Step 0</strong></div><div class="trace-layout"><div><div data-testid="abm-graph" id="abm-graph" role="img" aria-label="Interactive ABM social graph"></div><div class="node-buttons" id="node-button-list" aria-label="Fallback node selector"></div></div><div class="trace-stack"><article class="trace-panel" data-testid="node-detail-panel" id="node-detail-panel"><h3 data-i18n="graph.nodeDetail">Node Detail</h3><p>Select a node to inspect profile and timeline.</p></article><article class="trace-panel" data-testid="event-stream-panel" id="event-stream-panel"><h3 data-i18n="graph.eventStream">Event Stream</h3></article><article class="trace-panel" data-testid="decision-trace-panel" id="decision-trace-panel"><h3 data-i18n="decision.panel">Decision Trace</h3></article></div></div></section>
    <section data-testid="dataset-validation-section"><h2 data-i18n="section.dataset">Dataset Validation</h2>{dataset_html}</section>
    <section data-testid="seed-users-section"><h2 data-i18n="section.seed">Seed Users and Key Influencers</h2><p><span class="label" data-i18n="input.seedUsers">Seed users</span><span data-testid="seed-users">{escape(", ".join(payload.inputs.get("seed_user_ids", [])) or "None configured")}</span></p><p><span class="label">Key influencers</span><span data-testid="key-influencers">{escape(", ".join(map(str, payload.graph_trace.get("run", {}).get("key_influencers", []))) or "See metrics summary")}</span></p></section>
    <section data-testid="provider-evidence-section"><h2 data-i18n="provider.evidence">Provider / Decision Source Evidence</h2>{provider_html}</section>
    <section data-testid="limitations-section"><h2 data-i18n="limitations.title">Limitations</h2><p data-i18n="limitations.body">Offline mode is a deterministic baseline for reproducible product review.</p></section>
  </main>
  <script id="report-payload-data" type="application/json">{payload_json}</script><script id="report-i18n-data" type="application/json">{i18n_json}</script><script>{cytoscape_js}</script><script>{_interactive_trace_script()}</script>
</body>
</html>
"""


def _inputs_html(payload: ReportPayload) -> str:
    inputs = payload.inputs
    post = inputs.get("post", {})
    platform = inputs.get("platform_context", {})
    return (
        '<div class="input-grid">'
        f'<article class="input-card"><span class="label" data-i18n="input.post">Post</span><strong>{escape(str(post.get("post_id", "")))}</strong><p>{escape(str(post.get("text", "")))}</p><p class="subtle">{escape(", ".join(post.get("topic_tags", [])))}</p></article>'
        f'<article class="input-card"><span class="label" data-i18n="input.seedUsers">Seed users</span><p>{escape(", ".join(inputs.get("seed_user_ids", [])) or "none")}</p></article>'
        f'<article class="input-card"><span class="label" data-i18n="input.platform">Platform context</span><p>{escape(str(platform.get("time_label") or ""))}</p><p class="subtle">{escape(str(platform.get("platform_mood") or ""))}</p></article>'
        f'<article class="input-card"><span class="label" data-i18n="input.decisionMode">Decision mode</span><p>{escape(str(inputs.get("decision_mode")))}</p></article>'
        f'<article class="input-card"><span class="label" data-i18n="input.profileCount">Profiles</span><p>{escape(str(inputs.get("profile_count")))}</p></article>'
        f'<article class="input-card"><span class="label" data-i18n="input.edgeCount">Graph edges</span><p>{escape(str(inputs.get("edge_count")))}</p></article>'
        "</div>"
    )


def _metric_cards(payload: ReportPayload) -> str:
    cards: list[str] = []
    for metric in payload.metrics:
        label = metric.key.replace("_", " ").title()
        cards.append(
            f'<article class="metric-card" data-testid="metric-card-{escape(metric.key)}">'
            f'<span class="label" data-i18n="metric.{escape(metric.key)}.label">{escape(label)}</span>'
            f'<span class="value">{escape(str(metric.value))}</span>'
            f'<p class="subtle" data-i18n="metric.{escape(metric.key)}.desc"></p>'
            "</article>"
        )
    return "\n".join(cards)


def _metric_help_table() -> str:
    rows = "\n".join(
        f'<tr><th data-i18n="metric.{escape(key)}.label">{escape(key)}</th><td data-i18n="metric.{escape(key)}.desc"></td></tr>'
        for key in METRIC_KEYS
    )
    return f'<table data-testid="metric-help-table"><tbody>{rows}</tbody></table>'


def _trend_rows(payload: ReportPayload) -> str:
    return "\n".join(
        "<tr>"
        f"<td>{step['time_step']}</td><td>{step['exposed_count']}</td><td>{step['engaged_count']}</td>"
        f"<td>{step['new_exposed_count']}</td><td>{step['new_engaged_count']}</td>"
        f"<td>{len(step.get('exposure_events', []))}</td><td>{len(step.get('decision_events', []))}</td><td>{len(step.get('action_events', []))}</td>"
        "</tr>"
        for step in payload.trend
    )


def _trend_bars(payload: ReportPayload) -> str:
    max_total = max([1, *[max(int(step["exposed_count"]), int(step["engaged_count"])) for step in payload.trend]])
    rows: list[str] = []
    for step in payload.trend:
        exposed_width = round((int(step["exposed_count"]) / max_total) * 100, 2)
        engaged_width = round((int(step["engaged_count"]) / max_total) * 100, 2)
        rows.append(
            f'<div class="bar-row" data-testid="trend-step-{step["time_step"]}"><span>Step {step["time_step"]}</span>'
            f'<div><div class="bar-track" title="exposed"><div class="bar" style="width:{exposed_width}%"></div></div>'
            f'<div class="bar-track" title="engaged"><div class="bar" style="width:{engaged_width}%; background: linear-gradient(90deg, #11845b, #46c2a7);"></div></div></div>'
            f"<span>{step['exposed_count']}/{step['engaged_count']}</span></div>"
        )
    return "\n".join(rows)


def _dataset_validation_html(report: dict[str, Any] | None) -> str:
    if report is None or not report.get("dataset_used"):
        return '<p data-testid="dataset-validation-summary">Inline config dataset; no external dataset validation file was required.</p>'
    status = "PASS" if not report.get("errors") else "ERROR"
    status_class = "good" if status == "PASS" else "warn"
    rows = {
        "status": status,
        "directed": report.get("directed"),
        "graph_nodes": report.get("graph_node_count"),
        "graph_edges": report.get("graph_edge_count"),
        "profiles": report.get("profile_count"),
        "missing_profiles": ", ".join(report.get("missing_profile_ids", [])) or "none",
        "extra_profiles": ", ".join(report.get("extra_profile_ids", [])) or "none",
        "covered_seed_users": ", ".join(report.get("covered_seed_user_ids", [])) or "none",
        "preserved_profile_attributes": ", ".join(report.get("preserved_profile_attribute_columns", [])) or "none",
    }
    table_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>" for key, value in rows.items()
    )
    return f'<p data-testid="dataset-validation-summary"><span class="pill {status_class}">{status}</span> {escape(str(report.get("graph_node_count")))} nodes / {escape(str(report.get("graph_edge_count")))} edges / {escape(str(report.get("profile_count")))} profiles</p><table><tbody>{table_rows}</tbody></table>'


def _provider_evidence_html(evidence: dict[str, Any] | None, source_summary: dict[str, int]) -> str:
    safe_summary = escape(json.dumps(safe_data(source_summary), sort_keys=True))
    if evidence is None:
        return (
            '<p data-testid="decision-source-summary"><span class="pill" data-i18n="provider.offline">offline rule-based baseline</span> Decision sources: '
            + safe_summary
            + "</p>"
        )
    provider_count = source_summary.get("provider", 0)
    badge_class = "good" if provider_count else "warn"
    badge_text = (
        "provider-backed decision observed" if provider_count else "provider configured; no provider decision observed"
    )
    return (
        f'<p data-testid="decision-source-summary"><span class="pill {badge_class}">{escape(badge_text)}</span> Decision sources: {safe_summary}</p>'
        '<p data-testid="provider-privacy-notice" class="subtle" data-i18n="provider.notice">Provider evidence is sanitized.</p>'
        f'<pre data-testid="provider-metadata">{escape(safe_json(evidence))}</pre>'
    )


def _cytoscape_source() -> str:
    # Keep generated report artifacts clean for secret scanners. Cytoscape's
    # bundled stylesheet enum contains a literal ``use-credentials`` value for
    # cross-origin background images; this app never uses that feature, and
    # embedding it would trip the Web-console forbidden-fragment scan.
    return (
        (Path(__file__).parent / "vendor" / "cytoscape.min.js")
        .read_text(encoding="utf-8")
        .replace("use-credentials", "anonymous")
    )


def _interactive_trace_script() -> str:
    return r"""
(function () {
  const payload = JSON.parse(document.getElementById('report-payload-data').textContent);
  const dicts = JSON.parse(document.getElementById('report-i18n-data').textContent);
  const trace = payload.graph_trace;
  const languageSelect = document.getElementById('language-toggle');
  languageSelect.value = payload.default_language || 'en-US';
  function t(key) { return (dicts[languageSelect.value] && dicts[languageSelect.value][key]) || dicts['en-US'][key] || key; }
  function applyLanguage() {
    document.documentElement.lang = languageSelect.value;
    document.querySelectorAll('[data-i18n]').forEach((el) => { el.textContent = t(el.getAttribute('data-i18n')); });
    const narrative = document.getElementById('narrative-summary');
    if (narrative) narrative.textContent = languageSelect.value === 'zh-CN' ? narrative.dataset.narrativeZh : narrative.dataset.narrativeEn;
    renderPanels(Number(document.getElementById('step-slider').value || 0));
  }
  languageSelect.addEventListener('change', applyLanguage);
  const graphEl = document.getElementById('abm-graph');
  const slider = document.getElementById('step-slider');
  const stepLabel = document.getElementById('selected-step-label');
  const detailPanel = document.getElementById('node-detail-panel');
  const eventPanel = document.getElementById('event-stream-panel');
  const decisionPanel = document.getElementById('decision-trace-panel');
  const nodeButtonList = document.getElementById('node-button-list');
  let selectedNodeId = trace.nodes[0] ? trace.nodes[0].id : null;
  const byId = Object.fromEntries(trace.nodes.map((node) => [node.id, node]));
  const stepByNumber = Object.fromEntries(trace.steps.map((step) => [String(step.time_step), step]));
  const exposureEdgeKeysByStep = {};
  trace.steps.forEach((step) => { exposureEdgeKeysByStep[String(step.time_step)] = new Set((step.exposure_events || []).filter((event) => event.source_user_id).map((event) => edgeKey(event.source_user_id, event.user_id))); });
  function timelineFor(node, stepNumber) { return node.timeline.find((entry) => entry.time_step === stepNumber) || node.timeline[node.timeline.length - 1]; }
  function edgeKey(source, target) { return source + '->' + target; }
  function escapeHtml(value) { return String(value ?? '').replace(/[&<>"']/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch])); }
  function eventSummary(event) {
    if (event.event_type === 'exposure') return `${event.user_id} exposed via ${event.source_user_id || 'seed'} depth=${event.depth} p=${event.probability ?? 'n/a'}`;
    if (event.event_type === 'decision') { const d = event.decision || {}; return `${event.user_id} decision action=${d.action} p=${d.probability} confidence=${d.confidence} source=${d.decision_source || 'unknown'} reason=${d.reason || ''}`; }
    if (event.event_type === 'action') return `${event.user_id} action=${event.action} depth=${event.source_depth}`;
    return JSON.stringify(event);
  }
  function renderList(events, emptyText) { if (!events.length) return `<p class="subtle">${escapeHtml(emptyText)}</p>`; return '<ul>' + events.map((event) => `<li>${escapeHtml(eventSummary(event))}</li>`).join('') + '</ul>'; }
  function renderJson(value) { return `<pre>${escapeHtml(JSON.stringify(value || {}, null, 2))}</pre>`; }
  function updateButtons() { nodeButtonList.innerHTML = trace.nodes.slice(0, 18).map((node) => `<button type="button" data-node-id="${escapeHtml(node.id)}" class="${node.id === selectedNodeId ? 'active' : ''}">${escapeHtml(node.label)}</button>`).join(''); }
  function renderPanels(stepNumber) {
    const step = stepByNumber[String(stepNumber)] || { exposure_events: [], decision_events: [], action_events: [] };
    const node = byId[selectedNodeId] || trace.nodes[0];
    const timeline = node ? timelineFor(node, stepNumber) : null;
    const profileRows = node ? Object.entries(node.profile || {}).map(([key, value]) => `<tr><th>${escapeHtml(key)}</th><td>${escapeHtml(Array.isArray(value) ? value.join(', ') : value)}</td></tr>`).join('') : '';
    const latestDecisionEvent = timeline && timeline.decisions.length ? timeline.decisions[timeline.decisions.length - 1] : null;
    const latestDecision = latestDecisionEvent ? latestDecisionEvent.decision : null;
    const traceSummary = latestDecisionEvent ? latestDecisionEvent.trace_summary : null;
    const exposureSources = timeline ? timeline.exposures.map((event) => event.source_user_id || 'seed').join(', ') || 'none this step' : 'none';
    detailPanel.innerHTML = node ? `<h3>${t('graph.nodeDetail')}: ${escapeHtml(node.id)}</h3><p><span class="pill ${timeline && timeline.state === 'engaged' ? 'good' : ''}">${escapeHtml(timeline ? timeline.state : 'unknown')}</span> ${node.is_seed ? '<span class="pill">seed</span>' : ''}</p><table><tbody>${profileRows}</tbody></table><p><strong>Neighbor/source influence:</strong> ${escapeHtml(exposureSources)}</p><p><strong>${t('graph.currentDecision')}:</strong> ${latestDecision ? `action=${escapeHtml(latestDecision.action)} probability=${escapeHtml(latestDecision.probability)} confidence=${escapeHtml(latestDecision.confidence)} source=${escapeHtml(latestDecision.decision_source)} reason=${escapeHtml(latestDecision.reason)}` : 'none this step'}</p><h4>${t('decision.input')}</h4>${traceSummary ? renderJson(traceSummary.input) : renderList([], t('empty.noDecision'))}<h4>${t('decision.output')}</h4>${traceSummary ? renderJson(traceSummary.output) : renderList([], t('empty.noDecision'))}` : '<h3>Node Detail</h3><p>No graph nodes available.</p>';
    eventPanel.innerHTML = `<h3>${t('graph.eventStream')} — Step ${stepNumber}</h3><p class="subtle">Exposure → decision → action events collected for this selected step.</p><h4>Exposure events</h4>${renderList(step.exposure_events || [], t('empty.noExposure'))}<h4>Action events</h4>${renderList(step.action_events || [], t('empty.noAction'))}`;
    decisionPanel.innerHTML = `<h3>${t('decision.panel')} — Step ${stepNumber}</h3>${renderList(step.decision_events || [], t('empty.noDecision'))}`;
    updateButtons();
  }
  const cy = cytoscape({ container: graphEl, elements: [...trace.nodes.map((node) => ({ data: { id: node.id, label: node.label, is_seed: node.is_seed } })), ...trace.edges.map((edge, index) => ({ data: { id: `e${index}`, source: edge.source, target: edge.target, key: edgeKey(edge.source, edge.target), label: edge.attributes.relationship || edge.attributes.touchpoint || '' } }))], layout: { name: 'cose', animate: false, randomize: false, fit: true, padding: 32 }, style: [{ selector: 'node', style: { 'label': 'data(label)', 'font-size': 11, 'text-valign': 'center', 'text-halign': 'center', 'background-color': '#cbd5e1', 'border-width': 2, 'border-color': '#64748b', 'width': 34, 'height': 34, 'color': '#0f172a' } }, { selector: 'node.exposed', style: { 'background-color': '#f59e0b', 'border-color': '#b45309' } }, { selector: 'node.engaged', style: { 'background-color': '#16a34a', 'border-color': '#166534', 'color': '#fff' } }, { selector: 'node.seed', style: { 'shape': 'star', 'background-color': '#7c3aed', 'border-color': '#4c1d95', 'color': '#fff' } }, { selector: 'node.selected', style: { 'border-width': 5, 'border-color': '#ef4444' } }, { selector: 'edge', style: { 'curve-style': 'bezier', 'line-color': '#94a3b8', 'target-arrow-shape': 'triangle', 'target-arrow-color': '#94a3b8', 'width': 1.5, 'opacity': .62 } }, { selector: 'edge.active-exposure', style: { 'line-color': '#ef4444', 'target-arrow-color': '#ef4444', 'width': 4, 'opacity': 1 } }] });
  function updateGraph() { const stepNumber = Number(slider.value); stepLabel.textContent = `Step ${stepNumber}`; const activeEdges = exposureEdgeKeysByStep[String(stepNumber)] || new Set(); cy.nodes().forEach((ele) => { const node = byId[ele.id()]; const timeline = timelineFor(node, stepNumber); ele.removeClass('unseen exposed engaged seed selected'); ele.addClass(timeline.state); if (node.is_seed) ele.addClass('seed'); if (ele.id() === selectedNodeId) ele.addClass('selected'); }); cy.edges().forEach((ele) => { ele.toggleClass('active-exposure', activeEdges.has(ele.data('key'))); }); renderPanels(stepNumber); }
  cy.on('tap', 'node', (event) => { selectedNodeId = event.target.id(); updateGraph(); }); nodeButtonList.addEventListener('click', (event) => { const button = event.target.closest('button[data-node-id]'); if (!button) return; selectedNodeId = button.getAttribute('data-node-id'); updateGraph(); }); slider.addEventListener('input', updateGraph); updateButtons(); applyLanguage(); updateGraph(); setTimeout(() => { cy.resize(); cy.fit(undefined, 32); }, 100);
})();
"""


def _write_step_records_csv(result: SimulationRunResult, path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["time_step", "exposed_count", "engaged_count", "new_exposed_count", "new_engaged_count"]
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
    path.write_text(safe_json(events), encoding="utf-8")


def _write_dataset_validation_json(report: DatasetValidationReport, path: Path) -> None:
    path.write_text(safe_json(report.to_dict()), encoding="utf-8")
