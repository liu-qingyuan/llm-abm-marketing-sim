from __future__ import annotations

import csv
import json
from html import escape
from pathlib import Path
from typing import Any

import yaml

from .events import SimulationRunResult
from .graph_loader import DatasetValidationReport, load_network_dataset
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
    graph_trace = build_graph_trace(result, config)
    (output_path / "graph_trace.json").write_text(
        json.dumps(redact_secrets(graph_trace), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    write_report_html(
        result,
        config,
        output_path / "report.html",
        dataset_validation_report=dataset_validation_report,
        provider_readiness=provider_readiness,
    )
    return output_path


def build_graph_trace(result: SimulationRunResult, config: SimulationInput) -> dict[str, Any]:
    """Build the offline interactive graph trace consumed by report.html."""

    dataset = load_network_dataset(
        config.dataset,
        inline_edges=[(str(left), str(right)) for left, right in config.graph_edges],
        inline_profiles=config.profiles,
        seed_user_ids=config.simulation.seed_user_ids,
    )
    graph = dataset.graph
    profiles = dataset.profiles
    seed_ids = set(config.simulation.seed_user_ids)
    max_step = max([0, *[step.time_step for step in result.step_records]])

    exposures_by_user: dict[str, list[dict[str, Any]]] = {}
    decisions_by_user: dict[str, list[dict[str, Any]]] = {}
    actions_by_user: dict[str, list[dict[str, Any]]] = {}
    exposed_steps: dict[str, int] = {}
    engaged_steps: dict[str, int] = {}

    for exposure_event in result.exposure_events:
        payload = exposure_event.model_dump(mode="json")
        exposures_by_user.setdefault(exposure_event.user_id, []).append(payload)
        exposed_steps[exposure_event.user_id] = min(
            exposed_steps.get(exposure_event.user_id, exposure_event.time_step), exposure_event.time_step
        )
    for decision_event in result.decision_events:
        payload = decision_event.model_dump(mode="json")
        decisions_by_user.setdefault(decision_event.user_id, []).append(payload)
    for action_event in result.action_events:
        payload = action_event.model_dump(mode="json")
        actions_by_user.setdefault(action_event.user_id, []).append(payload)
        engaged_steps[action_event.user_id] = min(
            engaged_steps.get(action_event.user_id, action_event.time_step), action_event.time_step
        )

    nodes = []
    for node_id in sorted(str(node) for node in graph.nodes):
        profile = profiles.get(node_id)
        profile_payload = profile.model_dump(mode="json") if profile is not None else {"user_id": node_id}
        nodes.append(
            {
                "id": node_id,
                "label": node_id,
                "profile": profile_payload,
                "is_seed": node_id in seed_ids,
                "timeline": [
                    _node_timeline_entry(
                        node_id,
                        time_step,
                        exposed_steps,
                        engaged_steps,
                        exposures_by_user,
                        decisions_by_user,
                        actions_by_user,
                    )
                    for time_step in range(max_step + 1)
                ],
            }
        )

    edges = [
        {"source": str(source), "target": str(target), "attributes": dict(attributes)}
        for source, target, attributes in sorted(graph.edges(data=True), key=lambda edge: (str(edge[0]), str(edge[1])))
    ]
    steps = [
        {
            "time_step": step.time_step,
            "exposed_count": step.exposed_count,
            "engaged_count": step.engaged_count,
            "new_exposed_count": step.new_exposed_count,
            "new_engaged_count": step.new_engaged_count,
            "exposure_events": [event.model_dump(mode="json") for event in step.exposure_events],
            "decision_events": [event.model_dump(mode="json") for event in step.decision_events],
            "action_events": [event.model_dump(mode="json") for event in step.action_events],
        }
        for step in result.step_records
    ]
    return redact_secrets(
        {
            "schema_version": "graph-trace-v1",
            "nodes": nodes,
            "edges": edges,
            "steps": steps,
            "post": config.post.model_dump(mode="json"),
            "run": {
                "run_id": result.run_id,
                "random_seed": result.random_seed,
                "horizon": result.horizon,
                "time_step_label": config.simulation.time_step_label,
                "observation_window": config.simulation.observation_window,
                "decision_source_summary": _decision_source_summary(result),
            },
            "process": [
                "Environment computes exposure",
                "Agent observes post and neighbor behavior",
                "DecisionAdapter decides",
                "User state/action updates",
                "Metrics/events collected",
            ],
        }
    )


def _node_timeline_entry(
    node_id: str,
    time_step: int,
    exposed_steps: dict[str, int],
    engaged_steps: dict[str, int],
    exposures_by_user: dict[str, list[dict[str, Any]]],
    decisions_by_user: dict[str, list[dict[str, Any]]],
    actions_by_user: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    exposures = [event for event in exposures_by_user.get(node_id, []) if event["time_step"] == time_step]
    decisions = [event for event in decisions_by_user.get(node_id, []) if event["time_step"] == time_step]
    actions = [event for event in actions_by_user.get(node_id, []) if event["time_step"] == time_step]
    if node_id in engaged_steps and engaged_steps[node_id] <= time_step:
        state = "engaged"
    elif node_id in exposed_steps and exposed_steps[node_id] <= time_step:
        state = "exposed"
    else:
        state = "unseen"
    return {
        "time_step": time_step,
        "state": state,
        "exposures": exposures,
        "decisions": decisions,
        "actions": actions,
    }


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
    interactive_trace_html = _interactive_trace_html(result, config)

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
    .trace-layout {{ display: grid; grid-template-columns: minmax(420px, 1.35fr) minmax(320px, .9fr); gap: 16px; align-items: stretch; }}
    #abm-graph {{ min-height: 520px; border: 1px solid var(--line); border-radius: 16px; background: radial-gradient(circle at 20% 20%, #ffffff, #edf4ff); overflow: hidden; }}
    .trace-controls {{ display: flex; gap: 14px; align-items: center; flex-wrap: wrap; margin: 12px 0 16px; }}
    .trace-controls input[type=range] {{ flex: 1; min-width: 240px; accent-color: var(--accent); }}
    .trace-panel {{ border: 1px solid var(--line); border-radius: 14px; background: #fbfcff; padding: 14px; min-height: 140px; overflow: auto; }}
    .trace-panel h3 {{ margin: 0 0 8px; font-size: 1rem; }}
    .trace-panel ul {{ margin: 8px 0 0; padding-left: 20px; }}
    .trace-panel li {{ margin: 6px 0; }}
    .trace-stack {{ display: grid; gap: 12px; }}
    .state-legend {{ display: flex; gap: 10px; flex-wrap: wrap; margin: 8px 0; }}
    .legend-dot {{ width: .85rem; height: .85rem; display: inline-block; border-radius: 999px; margin-right: 5px; vertical-align: -1px; }}
    .node-buttons {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }}
    .node-buttons button {{ border: 1px solid var(--line); border-radius: 999px; background: #fff; padding: 5px 10px; color: var(--ink); cursor: pointer; }}
    .node-buttons button.active {{ border-color: var(--accent); background: #eef4ff; color: #174ea6; font-weight: 700; }}
    @media (max-width: 900px) {{ .trace-layout {{ grid-template-columns: 1fr; }} #abm-graph {{ min-height: 420px; }} }}
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
    {interactive_trace_html}
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


def _interactive_trace_html(result: SimulationRunResult, config: SimulationInput) -> str:
    graph_trace = build_graph_trace(result, config)
    trace_json = json.dumps(graph_trace, sort_keys=True, separators=(",", ":")).replace("</", "<\\/")
    cytoscape_js = _cytoscape_source()
    max_step = max([0, *[step["time_step"] for step in graph_trace["steps"]]])
    return f'''
    <section data-testid="interactive-trace-section" id="interactive-trace-section">
      <h2>Interactive ABM Trace</h2>
      <p class="subtle">Offline Cytoscape trace demo: Environment computes exposure → Agent observes post and neighbor behavior → DecisionAdapter decides → user state/action updates → metrics/events collected.</p>
      <div class="state-legend" aria-label="Node state legend">
        <span><i class="legend-dot" style="background:#cbd5e1"></i>unseen</span>
        <span><i class="legend-dot" style="background:#f59e0b"></i>exposed</span>
        <span><i class="legend-dot" style="background:#16a34a"></i>engaged</span>
        <span><i class="legend-dot" style="background:#7c3aed"></i>seed</span>
      </div>
      <div class="trace-controls">
        <label for="step-slider" class="label">Selected time step</label>
        <input data-testid="step-slider" id="step-slider" type="range" min="0" max="{max_step}" step="1" value="0">
        <strong data-testid="selected-step-label" id="selected-step-label">Step 0</strong>
      </div>
      <div class="trace-layout">
        <div>
          <div data-testid="abm-graph" id="abm-graph" role="img" aria-label="Interactive ABM social graph"></div>
          <div class="node-buttons" id="node-button-list" aria-label="Fallback node selector"></div>
        </div>
        <div class="trace-stack">
          <article class="trace-panel" data-testid="node-detail-panel" id="node-detail-panel"><h3>Node Detail</h3><p>Select a node to inspect profile and timeline.</p></article>
          <article class="trace-panel" data-testid="event-stream-panel" id="event-stream-panel"><h3>Event Stream</h3></article>
          <article class="trace-panel" data-testid="decision-trace-panel" id="decision-trace-panel"><h3>Decision Trace</h3></article>
        </div>
      </div>
      <script id="graph-trace-data" type="application/json">{trace_json}</script>
      <script>{cytoscape_js}</script>
      <script>{_interactive_trace_script()}</script>
    </section>'''


def _cytoscape_source() -> str:
    return (Path(__file__).parent / "vendor" / "cytoscape.min.js").read_text(encoding="utf-8")


def _interactive_trace_script() -> str:
    return r"""
(function () {
  const trace = JSON.parse(document.getElementById('graph-trace-data').textContent);
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
  trace.steps.forEach((step) => {
    exposureEdgeKeysByStep[String(step.time_step)] = new Set(
      step.exposure_events
        .filter((event) => event.source_user_id)
        .map((event) => edgeKey(event.source_user_id, event.user_id))
    );
  });

  function timelineFor(node, stepNumber) {
    return node.timeline.find((entry) => entry.time_step === stepNumber) || node.timeline[node.timeline.length - 1];
  }
  function edgeKey(source, target) { return source + '->' + target; }
  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  }
  function eventSummary(event) {
    if (event.event_type === 'exposure') {
      return `${event.user_id} exposed via ${event.source_user_id || 'seed'} depth=${event.depth} p=${event.probability ?? 'n/a'}`;
    }
    if (event.event_type === 'decision') {
      const d = event.decision || {};
      return `${event.user_id} decision action=${d.action} p=${d.probability} confidence=${d.confidence} source=${d.decision_source || 'unknown'} reason=${d.reason || ''}`;
    }
    if (event.event_type === 'action') {
      return `${event.user_id} action=${event.action} depth=${event.source_depth}`;
    }
    return JSON.stringify(event);
  }
  function renderList(events, emptyText) {
    if (!events.length) return `<p class="subtle">${escapeHtml(emptyText)}</p>`;
    return '<ul>' + events.map((event) => `<li>${escapeHtml(eventSummary(event))}</li>`).join('') + '</ul>';
  }
  function updateButtons() {
    nodeButtonList.innerHTML = trace.nodes.slice(0, 18).map((node) => (
      `<button type="button" data-node-id="${escapeHtml(node.id)}" class="${node.id === selectedNodeId ? 'active' : ''}">${escapeHtml(node.label)}</button>`
    )).join('');
  }
  function renderPanels(stepNumber) {
    const step = stepByNumber[String(stepNumber)] || { exposure_events: [], decision_events: [], action_events: [] };
    const node = byId[selectedNodeId] || trace.nodes[0];
    const timeline = node ? timelineFor(node, stepNumber) : null;
    const profileRows = node ? Object.entries(node.profile || {}).map(([key, value]) => `<tr><th>${escapeHtml(key)}</th><td>${escapeHtml(Array.isArray(value) ? value.join(', ') : value)}</td></tr>`).join('') : '';
    const latestDecision = timeline && timeline.decisions.length ? timeline.decisions[timeline.decisions.length - 1].decision : null;
    const exposureSources = timeline ? timeline.exposures.map((event) => event.source_user_id || 'seed').join(', ') || 'none this step' : 'none';
    detailPanel.innerHTML = node ? `<h3>Node Detail: ${escapeHtml(node.id)}</h3>
      <p><span class="pill ${timeline && timeline.state === 'engaged' ? 'good' : ''}">${escapeHtml(timeline ? timeline.state : 'unknown')}</span> ${node.is_seed ? '<span class="pill">seed</span>' : ''}</p>
      <table><tbody>${profileRows}</tbody></table>
      <p><strong>Neighbor/source influence:</strong> ${escapeHtml(exposureSources)}</p>
      <p><strong>Current decision:</strong> ${latestDecision ? `action=${escapeHtml(latestDecision.action)} probability=${escapeHtml(latestDecision.probability)} confidence=${escapeHtml(latestDecision.confidence)} source=${escapeHtml(latestDecision.decision_source)} reason=${escapeHtml(latestDecision.reason)}` : 'none this step'}</p>
      <h4>Exposure timeline</h4>${renderList(timeline ? timeline.exposures : [], 'No exposure event for selected step.')}
      <h4>Decision timeline</h4>${renderList(timeline ? timeline.decisions : [], 'No decision event for selected step.')}
      <h4>Action timeline</h4>${renderList(timeline ? timeline.actions : [], 'No action event for selected step.')}` : '<h3>Node Detail</h3><p>No graph nodes available.</p>';
    eventPanel.innerHTML = `<h3>Event Stream — Step ${stepNumber}</h3>
      <p class="subtle">Exposure → decision → action events collected for this selected step.</p>
      <h4>Exposure events</h4>${renderList(step.exposure_events || [], 'No exposure events this step.')}
      <h4>Action events</h4>${renderList(step.action_events || [], 'No action events this step.')}`;
    decisionPanel.innerHTML = `<h3>Decision Trace — Step ${stepNumber}</h3>
      ${renderList(step.decision_events || [], 'No decision events this step.')}`;
    updateButtons();
  }

  const cy = cytoscape({
    container: graphEl,
    elements: [
      ...trace.nodes.map((node) => ({ data: { id: node.id, label: node.label, is_seed: node.is_seed } })),
      ...trace.edges.map((edge, index) => ({ data: { id: `e${index}`, source: edge.source, target: edge.target, key: edgeKey(edge.source, edge.target), label: edge.attributes.relationship || edge.attributes.touchpoint || '' } }))
    ],
    layout: { name: 'cose', animate: false, randomize: false, fit: true, padding: 32 },
    style: [
      { selector: 'node', style: { 'label': 'data(label)', 'font-size': 11, 'text-valign': 'center', 'text-halign': 'center', 'background-color': '#cbd5e1', 'border-width': 2, 'border-color': '#64748b', 'width': 34, 'height': 34, 'color': '#0f172a' } },
      { selector: 'node.exposed', style: { 'background-color': '#f59e0b', 'border-color': '#b45309' } },
      { selector: 'node.engaged', style: { 'background-color': '#16a34a', 'border-color': '#166534', 'color': '#fff' } },
      { selector: 'node.seed', style: { 'shape': 'star', 'background-color': '#7c3aed', 'border-color': '#4c1d95', 'color': '#fff' } },
      { selector: 'node.selected', style: { 'border-width': 5, 'border-color': '#ef4444' } },
      { selector: 'edge', style: { 'curve-style': 'bezier', 'line-color': '#94a3b8', 'target-arrow-shape': 'triangle', 'target-arrow-color': '#94a3b8', 'width': 1.5, 'opacity': .62 } },
      { selector: 'edge.active-exposure', style: { 'line-color': '#ef4444', 'target-arrow-color': '#ef4444', 'width': 4, 'opacity': 1 } }
    ]
  });

  function updateGraph() {
    const stepNumber = Number(slider.value);
    stepLabel.textContent = `Step ${stepNumber}`;
    const activeEdges = exposureEdgeKeysByStep[String(stepNumber)] || new Set();
    cy.nodes().forEach((ele) => {
      const node = byId[ele.id()];
      const timeline = timelineFor(node, stepNumber);
      ele.removeClass('unseen exposed engaged seed selected');
      ele.addClass(timeline.state);
      if (node.is_seed) ele.addClass('seed');
      if (ele.id() === selectedNodeId) ele.addClass('selected');
    });
    cy.edges().forEach((ele) => {
      ele.toggleClass('active-exposure', activeEdges.has(ele.data('key')));
    });
    renderPanels(stepNumber);
  }

  cy.on('tap', 'node', (event) => {
    selectedNodeId = event.target.id();
    updateGraph();
  });
  nodeButtonList.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-node-id]');
    if (!button) return;
    selectedNodeId = button.getAttribute('data-node-id');
    updateGraph();
  });
  slider.addEventListener('input', updateGraph);
  updateButtons();
  updateGraph();
  setTimeout(() => { cy.resize(); cy.fit(undefined, 32); }, 100);
})();"""


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
