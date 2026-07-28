from __future__ import annotations

import hashlib
import html
import json
from collections.abc import Mapping, Sequence
from typing import Any

from .concurrent_message_current_renderer import render_current_report as _render_current_report


def _legacy_render_report(payload: Any, *, include_pagination: bool = True) -> str:
    counts = _required_mapping(payload.validation_summary, "counts", "validation summary")
    funnel = payload.campaign_funnel
    allocation = payload.message_allocation
    response = payload.primary_audience_response
    feedback = payload.campaign_feedback_effect
    sensitivity = payload.demographic_decision_sensitivity
    formal_seed_first_run = payload.run.get("sampling_status") == "persisted_seed_first_formal_run"
    deploy_eligible = _as_bool(payload.run.get("production_deploy_eligible"))
    if formal_seed_first_run and deploy_eligible:
        hero_copy = (
            "This additive Multi-Message v1 report is a persisted Seed-First Formal artifact. "
            "It is rebuilt from the approved tuple, remains descriptive and non-causal, and "
            "does not call a provider during report regeneration."
        )
        status_label = "Persisted Seed-First Formal Run · deploy eligible"
    elif formal_seed_first_run:
        hero_copy = (
            "This additive Multi-Message v1 report is a persisted Seed-First Formal artifact with a blocked deploy gate. "
            "It is rebuilt from the approved tuple, remains descriptive and non-causal, and does not call a provider "
            "during report regeneration."
        )
        status_label = "Persisted Seed-First Formal Run · deploy blocked"
    else:
        hero_copy = (
            "This additive Multi-Message v1 report is validation-only, descriptive, and non-causal. "
            "It is rebuilt from the persisted tuple and does not call a provider during report regeneration."
        )
        status_label = "Validation only · no deploy"
    summary_cards = [
        ("Research sample", f"{_as_int(counts.get('sample_users')):,}"),
        ("Actual exposures", f"{_as_int(counts.get('actual_exposures')):,}"),
        (
            "Primary success / fail",
            f"{_as_int(counts.get('primary_successes'))} / {_as_int(counts.get('primary_failures'))}",
        ),
        (
            "Shadow success / fail",
            f"{_as_int(counts.get('shadow_successes'))} / {_as_int(counts.get('shadow_failures'))}",
        ),
        ("Distinct exposed users", f"{_as_int(funnel.get('distinct_exposed_users')):,}"),
        (
            "Paired decision coverage",
            str(_required_mapping(sensitivity, "paired_decision_coverage", "sensitivity").get("value")),
        ),
        (
            "Changed message-batches",
            str(_required_mapping(feedback, "overall", "feedback overall").get("changed_message_batch_count")),
        ),
        (
            "Flagged shadow reasons",
            str(
                _as_int(
                    _required_mapping(sensitivity, "reason_screening", "reason screening").get("flagged_pair_count")
                )
            ),
        ),
    ]
    summary_html = "".join(
        f'<article class="summary-card"><span>{html.escape(label)}</span><strong>{html.escape(value)}</strong></article>'
        for label, value in summary_cards
    )
    downloads = payload.downloads.model_dump(mode="json")
    download_links = "".join(
        f'<a data-testid="download-{html.escape(key.replace("_", "-"), quote=True)}" href="{html.escape(relative_path)}">{html.escape(key.replace("_", " ").title())}</a>'
        for key, relative_path in downloads.items()
    )
    message_rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(row['message_id']))}</td>"
        f"<td>{html.escape(str(row['title']))}</td>"
        f"<td>{html.escape(str(row['intended_audience_segment']))}</td>"
        f"<td>{html.escape(str(row['body'])[:96])}...</td>"
        "</tr>"
        for row in payload.messages
    )
    funnel_rows = "".join(
        f"<tr><td>{html.escape(label)}</td><td>{html.escape(value)}</td></tr>"
        for label, value in (
            ("Sample users", f"{_as_int(funnel.get('sample_users')):,}"),
            ("Eligible user-message pairs", f"{_as_int(funnel.get('eligible_user_message_pairs')):,}"),
            ("Actual exposures", f"{_as_int(funnel.get('actual_exposures')):,}"),
            ("Distinct exposed users", f"{_as_int(funnel.get('distinct_exposed_users')):,}"),
            ("Below delivery capacity pairs", f"{_as_int(funnel.get('below_delivery_capacity_pairs')):,}"),
            ("Primary attempted / succeeded / failed", _three_part(funnel.get("primary"))),
            ("Shadow attempted / succeeded / failed", _three_part(funnel.get("shadow"))),
        )
    )
    coverage_rows = "".join(
        f"<tr><td>{html.escape(str(coverage))} message(s)</td><td>{html.escape(str(count))}</td></tr>"
        for coverage, count in sorted(
            _required_mapping(funnel, "campaign_exposure_coverage", "campaign funnel").items()
        )
    )
    allocation_batches = _required_list(allocation.get("batch_capacity"), "message allocation.batch_capacity")
    allocation_rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(row['message_id']))}</td>"
        f"<td>{html.escape(str(row['time_step']))}</td>"
        f"<td>{html.escape(str(row['configured_capacity']))}</td>"
        f"<td>{html.escape(str(row['eligible_users']))}</td>"
        f"<td>{html.escape(str(row['selected_pairs']))}</td>"
        f"<td>{html.escape(str(row['below_delivery_capacity']))}</td>"
        "</tr>"
        for row in allocation_batches
    )
    class_matrix = _required_mapping(allocation, "class_message_matrix", "message allocation")
    class_headers = "".join(f"<th>{html.escape(message['message_id'])}</th>" for message in payload.messages)
    class_rows = "".join(
        "<tr>"
        f"<td>{html.escape(latent_class)}</td>"
        + "".join(
            f"<td>{html.escape(str(values.get(latent_message['message_id'], 0)))}</td>"
            for latent_message in payload.messages
        )
        + "</tr>"
        for latent_class, values in sorted(class_matrix.items())
    )
    response_rows = "".join(
        "<tr>"
        f"<td>{html.escape(message_id)}</td>"
        f"<td>{html.escape(str(message_payload['message_title']))}</td>"
        f"<td>{html.escape(str(_required_mapping(message_payload, 'action_counts', 'message response')['like']))}</td>"
        f"<td>{html.escape(str(_required_mapping(message_payload, 'action_counts', 'message response')['comment']))}</td>"
        f"<td>{html.escape(str(_required_mapping(message_payload, 'action_counts', 'message response')['share']))}</td>"
        f"<td>{html.escape(str(_required_mapping(message_payload, 'action_counts', 'message response')['ignore']))}</td>"
        f"<td>{html.escape(str(_required_mapping(message_payload, 'action_counts', 'message response')['provider_failed']))}</td>"
        f"<td>{html.escape(_rate_label(message_payload['exposure_engagement_rate']))}</td>"
        f"<td>{html.escape(_rate_label(message_payload['decision_engagement_rate']))}</td>"
        "</tr>"
        for message_id, message_payload in sorted(
            _required_mapping(response, "per_message", "primary audience response").items()
        )
    )
    feedback_rows = "".join(
        "<tr>"
        f"<td>{html.escape(message_id)}</td>"
        f"<td>{html.escape(str(batch['time_step']))}</td>"
        f"<td>{html.escape(str(batch['top_overlap_count']))}</td>"
        f"<td>{html.escape(str(batch['top_selection_changed']).lower())}</td>"
        f"<td>{html.escape(', '.join(batch['feedback_added_user_ids']))}</td>"
        f"<td>{html.escape(', '.join(batch['feedback_removed_user_ids']))}</td>"
        "</tr>"
        for message_id, message_payload in sorted(
            _required_mapping(feedback, "per_message", "feedback per_message").items()
        )
        for batch in _required_list(message_payload.get("batches"), "feedback batches")
    )
    transition_rows = "".join(
        f"<tr><td>{html.escape(transition)}</td><td>{html.escape(str(count))}</td></tr>"
        for transition, count in sorted(
            _required_mapping(sensitivity, "action_transition_counts", "sensitivity").items()
        )
    )
    sensitivity_rows = "".join(
        f"<tr><td>{html.escape(label)}</td><td>{html.escape(value)}</td></tr>"
        for label, value in (
            (
                "Pair terminal coverage",
                _rate_label(_required_mapping(sensitivity, "pair_terminal_coverage", "sensitivity")),
            ),
            (
                "Paired decision coverage",
                _rate_label(_required_mapping(sensitivity, "paired_decision_coverage", "sensitivity")),
            ),
            ("Dual-success pairs", str(_as_int(sensitivity.get("dual_success_pair_count")))),
            (
                "Engage disagreement rate",
                _rate_label(_required_mapping(sensitivity, "engage_disagreement_rate", "sensitivity")),
            ),
            (
                "Mean absolute probability delta",
                _delta_label(_required_mapping(sensitivity, "mean_absolute_probability_delta", "sensitivity")),
            ),
        )
    )
    payload_json = json.dumps(
        payload.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).replace("</", "<\\/")
    template = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(payload.title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #0f1b2d;
      --muted: #5e6e82;
      --line: #d8e1ee;
      --panel: #ffffff;
      --page: #f4f7fb;
      --green: #206b56;
      --amber: #9a5b12;
      --blue: #1f5fa6;
      --red: #9c2f37;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font: 14px/1.5 -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; color: var(--ink); background: var(--page); }}
    a {{ color: var(--blue); }}
    main {{ width: min(1480px, 100%); margin: 0 auto; background: #fff; }}
    .hero, .content-band, .downloads-band {{ padding: 30px clamp(18px, 4vw, 52px); border-bottom: 1px solid var(--line); }}
    .hero {{ background: linear-gradient(180deg, #f7fbff 0%, #ffffff 100%); }}
    .eyebrow {{ display: inline-block; margin-bottom: 8px; font-size: 11px; font-weight: 800; letter-spacing: 0.08em; text-transform: uppercase; color: var(--green); }}
    .hero-head {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; }}
    .hero h1, .content-band h2 {{ margin: 0 0 10px; line-height: 1.15; }}
    .hero h1 {{ font-size: clamp(2rem, 2.8vw, 3rem); }}
    .status-badge {{ display: inline-flex; align-items: center; gap: 8px; min-height: 34px; padding: 6px 10px; border: 1px solid #cfe2d7; border-radius: 6px; background: #edf7f2; color: var(--green); font-weight: 700; }}
    .summary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-top: 22px; }}
    .summary-card {{ min-height: 90px; padding: 14px 16px; border: 1px solid var(--line); border-radius: 6px; background: var(--panel); }}
    .summary-card span {{ display: block; color: var(--muted); font-size: 12px; }}
    .summary-card strong {{ display: block; margin-top: 6px; font-size: 24px; }}
    .hero-copy, .section-copy, .muted {{ color: var(--muted); }}
    .split-grid {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 20px; }}
    .stack {{ display: grid; gap: 18px; }}
    .panel, .split-grid > *, .stack > * {{ min-width: 0; }}
    .panel {{ border: 1px solid var(--line); border-radius: 6px; background: #fff; }}
    .panel h3 {{ margin: 0; padding: 14px 16px 0; font-size: 15px; }}
    .panel .section-copy, .panel .muted {{ padding: 0 16px; }}
    .table-wrap {{ overflow-x: auto; min-width: 0; max-width: 100%; }}
    table {{ width: 100%; border-collapse: collapse; min-width: 640px; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid #e5ebf4; text-align: left; vertical-align: top; }}
    th {{ font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }}
    .filters {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin: 16px 0 18px; }}
    .filters label {{ display: grid; gap: 6px; font-size: 12px; color: var(--muted); }}
    input, select {{ width: 100%; min-height: 38px; padding: 8px 10px; border: 1px solid var(--line); border-radius: 6px; font: inherit; color: var(--ink); background: #fff; }}
    .downloads {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; }}
    .downloads a {{ min-height: 42px; display: flex; align-items: center; padding: 8px 10px; border: 1px solid var(--line); border-radius: 6px; text-decoration: none; font-weight: 700; }}
    .downloads a:hover, .downloads a:focus-visible {{ border-color: var(--green); outline: 2px solid rgba(32, 107, 86, 0.22); outline-offset: 2px; }}
    .trace-count {{ margin: 16px 0 8px; font-weight: 700; color: var(--blue); }}
    .trace-pagination {{ display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 14px 20px; align-items: end; margin: 12px 0 18px; }}
    .trace-page-size {{ display: grid; gap: 6px; max-width: 180px; color: var(--muted); font-size: 12px; }}
    .trace-page-size select {{ min-width: 0; }}
    .trace-page-status {{ margin: 8px 0 0; color: var(--muted); font-size: 12px; }}
    .trace-page-controls {{ display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 6px; }}
    .trace-page-controls button {{ min-width: 38px; min-height: 38px; padding: 7px 10px; border: 1px solid var(--line); border-radius: 6px; background: #fff; color: var(--ink); font: inherit; font-size: 12px; font-weight: 700; cursor: pointer; white-space: nowrap; }}
    .trace-page-controls button:hover:not(:disabled), .trace-page-controls button:focus-visible {{ border-color: var(--blue); outline: 2px solid rgba(31, 95, 166, 0.18); outline-offset: 2px; }}
    .trace-page-controls button[aria-current="page"] {{ border-color: var(--blue); background: #edf4fc; color: var(--blue); }}
    .trace-page-controls button:disabled {{ cursor: not-allowed; opacity: .45; }}
    .trace-page-numbers {{ display: inline-flex; flex-wrap: wrap; justify-content: center; gap: 6px; }}
    [data-testid="decision-trace-table"] tbody tr {{ cursor: pointer; }}
    [data-testid="decision-trace-table"] tbody tr:hover, [data-testid="decision-trace-table"] tbody tr:focus {{ background: #f2f7fd; outline: 2px solid rgba(31, 95, 166, 0.18); outline-offset: -2px; }}
    .note-list {{ display: grid; gap: 10px; margin: 18px 0 0; padding: 0; list-style: none; }}
    .note-list li {{ padding: 12px 14px; border-left: 4px solid var(--amber); background: #fff9f2; color: #6f4a18; }}
    .drawer {{ position: fixed; top: 0; right: 0; bottom: 0; z-index: 30; width: min(520px, 100vw); border-left: 1px solid var(--line); background: #fff; box-shadow: -22px 0 48px rgba(15, 27, 45, 0.12); overflow: auto; }}
    .drawer[hidden] {{ display: none; }}
    .drawer-header {{ position: sticky; top: 0; z-index: 2; display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; min-height: 72px; padding: 14px 16px; border-bottom: 1px solid var(--line); background: rgba(255, 255, 255, 0.98); }}
    .drawer-header span {{ display: block; font-size: 11px; font-weight: 800; letter-spacing: 0.08em; text-transform: uppercase; color: var(--green); }}
    .drawer-header h2 {{ margin: 4px 0 0; font-size: 1.15rem; }}
    .drawer-close {{ width: 38px; min-height: 38px; padding: 0; border: 1px solid var(--line); border-radius: 6px; background: #fff; font-size: 1.35rem; line-height: 1; color: var(--ink); cursor: pointer; }}
    .drawer-body {{ padding: 18px; display: grid; gap: 18px; }}
    .drawer-grid {{ display: grid; gap: 14px; }}
    .drawer-card {{ padding: 14px; border: 1px solid var(--line); border-radius: 6px; background: #fff; }}
    .drawer-card h3 {{ margin: 0 0 10px; font-size: 15px; }}
    .drawer-card dl {{ display: grid; grid-template-columns: minmax(0, 140px) minmax(0, 1fr); gap: 8px 10px; margin: 0; }}
    .drawer-card dt {{ color: var(--muted); font-size: 12px; }}
    .drawer-card dd {{ margin: 0; word-break: break-word; }}
    .field-diff-list, .shadow-field-list {{ display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }}
    .field-diff-list li, .shadow-field-list li {{ padding: 10px 12px; border: 1px solid var(--line); border-radius: 6px; background: #f8fafc; }}
    .drawer-empty {{ color: var(--muted); }}
    .footer-note {{ color: var(--muted); font-size: 12px; }}
    @media (max-width: 900px) {{
      .hero-head, .split-grid {{ grid-template-columns: 1fr; display: grid; }}
      .hero-head {{ gap: 14px; }}
    }}
    @media (max-width: 680px) {{
      .hero, .content-band, .downloads-band {{ padding-top: 24px; padding-bottom: 24px; }}
      .summary-grid, .filters, .downloads {{ grid-template-columns: 1fr; }}
      .trace-pagination {{ grid-template-columns: 1fr; align-items: stretch; }}
      .trace-page-size {{ max-width: none; }}
      .trace-page-controls {{ justify-content: flex-start; }}
      .trace-page-numbers {{ justify-content: flex-start; }}
      .drawer {{ width: 100vw; }}
    }}
  </style>
</head>
<body>
  <main data-testid="concurrent-message-report">
    <header class="hero">
      <span class="eyebrow">Concurrent Message Experiment</span>
      <div class="hero-head">
        <div>
          <h1>{html.escape(payload.title)}</h1>
          <p class="hero-copy">{html.escape(hero_copy)}</p>
        </div>
        <span class="status-badge" data-testid="validation-status">{html.escape(status_label)}</span>
      </div>
      <div class="summary-grid">{summary_html}</div>
      <ul class="note-list" data-testid="shadow-boundary-notes">{''.join(f'<li>{html.escape(note)}</li>' for note in payload.notes)}</ul>
    </header>

    <section class="content-band" data-testid="messages-section">
      <span class="eyebrow">Contract</span>
      <h2>Approved message snapshot</h2>
      <p class="section-copy">The report freezes the three authoritative message bodies and their Intended Audience Segments, alongside the paired prompt tokens and safe tuple artifacts. Intended Audience Segment is a design descriptor only: it is not exposure eligibility and is not a Prompt field. Changing any crossed token, aggregate, or artifact hash fails the rebuild.</p>
      <div class="table-wrap"><table><thead><tr><th>Message</th><th>Title</th><th>Audience segment</th><th>Body preview</th></tr></thead><tbody>{message_rows}</tbody></table></div>
    </section>

    <section class="content-band" data-testid="campaign-funnel-section">
      <div class="split-grid">
        <div class="panel">
          <h3>Campaign Funnel</h3>
          <p class="section-copy">Counts and denominators come from the persisted payload and validation evidence.</p>
          <div class="table-wrap"><table><tbody>{funnel_rows}</tbody></table></div>
        </div>
        <div class="panel">
          <h3>Campaign Exposure Coverage</h3>
          <p class="section-copy">Coverage counts are user-level descriptive evidence and do not imply causal message effects.</p>
          <div class="table-wrap"><table><thead><tr><th>Coverage</th><th>User count</th></tr></thead><tbody>{coverage_rows}</tbody></table></div>
        </div>
      </div>
    </section>

    <section class="content-band" data-testid="message-allocation-section">
      <span class="eyebrow">Allocation</span>
      <h2>Message Allocation</h2>
      <p class="section-copy">Ranking evidence stays platform-internal. The page shows it only as explainable allocation evidence, not as prompt input.</p>
      <div class="stack">
        <div class="panel">
          <h3>Batch capacity</h3>
          <div class="table-wrap"><table><thead><tr><th>Message</th><th>Batch</th><th>Configured capacity</th><th>Eligible users</th><th>Selected pairs</th><th>Below capacity</th></tr></thead><tbody>{allocation_rows}</tbody></table></div>
        </div>
        <div class="panel">
          <h3>Class × Message Exposure Matrix</h3>
          <div class="table-wrap"><table><thead><tr><th>Latent class</th>{class_headers}</tr></thead><tbody>{class_rows}</tbody></table></div>
        </div>
      </div>
    </section>

    <section class="content-band" data-testid="primary-audience-response-section">
      <span class="eyebrow">Response</span>
      <h2>Primary Audience Response</h2>
      <p class="section-copy">Both rates keep their persisted denominators visible. Provider failures are shown directly and are never patched by the page.</p>
      <div class="table-wrap"><table><thead><tr><th>Message</th><th>Title</th><th>Like</th><th>Comment</th><th>Share</th><th>Ignore</th><th>Provider failed</th><th>Positive / exposures</th><th>Positive / successful Primary decisions</th></tr></thead><tbody>{response_rows}</tbody></table></div>
    </section>

    <section class="content-band" data-testid="campaign-feedback-effect-section">
      <span class="eyebrow">Feedback</span>
      <h2>Campaign Feedback Effect</h2>
      <p class="section-copy">No-feedback comparisons reuse the same frozen candidates and full-precision score components while setting only the campaign-feedback term to 0.</p>
      <div class="table-wrap"><table><thead><tr><th>Message</th><th>Batch</th><th>Top overlap</th><th>Changed</th><th>Feedback-added users</th><th>Feedback-removed users</th></tr></thead><tbody>{feedback_rows}</tbody></table></div>
    </section>

    <section class="content-band" data-testid="demographic-decision-sensitivity-section">
      <span class="eyebrow">Sensitivity</span>
      <h2>Demographic Decision Sensitivity</h2>
      <p class="section-copy">Shadow is report-only. Paired comparisons stay descriptive and do not become a second exposure or a second runtime path.</p>
      <div class="split-grid">
        <div class="panel">
          <h3>Summary</h3>
          <div class="table-wrap"><table><tbody>{sensitivity_rows}</tbody></table></div>
        </div>
        <div class="panel">
          <h3>Action transitions</h3>
          <div class="table-wrap"><table><thead><tr><th>Transition</th><th>Count</th></tr></thead><tbody>{transition_rows}</tbody></table></div>
        </div>
      </div>
    </section>

    <section class="content-band" data-testid="decision-trace-section">
      <span class="eyebrow">Decision Trace</span>
      <h2>Exposure trace table</h2>
      <p class="section-copy">Each row is one unique <code>user × message × exposure</code>. Filters only hide or show persisted rows; they never rewrite reasons or add synthetic actions.</p>
      <div class="filters">
        <label><span>Search</span><input data-testid="trace-search" id="trace-search" type="search" placeholder="user_id / message / reason"></label>
        <label><span>Message</span><select data-testid="message-filter" id="message-filter"><option value="">All</option></select></label>
        <label><span>Class</span><select data-testid="class-filter" id="class-filter"><option value="">All</option></select></label>
        <label><span>Batch</span><select data-testid="batch-filter" id="batch-filter"><option value="">All</option></select></label>
        <label><span>Primary action</span><select data-testid="primary-action-filter" id="primary-action-filter"><option value="">All</option></select></label>
        <label><span>Provider status</span><select data-testid="provider-status-filter" id="provider-status-filter"><option value="">All</option><option value="succeeded">Succeeded</option><option value="provider_failed">Provider failed</option></select></label>
        <label><span>Primary / Shadow disagreement</span><select data-testid="disagreement-filter" id="disagreement-filter"><option value="">All</option><option value="true">Disagree</option><option value="false">Agree</option></select></label>
      </div>
      <p class="trace-count" data-testid="visible-trace-count" id="visible-trace-count"><span data-testid="trace-match-count" id="trace-match-count"></span></p>
      <div class="trace-pagination" data-testid="trace-pagination" aria-label="Exposure trace pagination">
        <div>
          <label class="trace-page-size"><span>Rows per page</span><select data-testid="trace-page-size" id="trace-page-size"><option value="25">25</option><option value="50" selected>50</option><option value="100">100</option></select></label>
          <p class="trace-page-status" data-testid="trace-page-status" id="trace-page-status" role="status" aria-live="polite"></p>
        </div>
        <nav class="trace-page-controls" data-testid="trace-page-controls" aria-label="Trace pages">
          <button type="button" data-testid="trace-previous-page" id="trace-previous-page" aria-label="Previous trace page">Previous</button>
          <span class="trace-page-numbers" data-testid="trace-page-numbers" id="trace-page-numbers"></span>
          <button type="button" data-testid="trace-next-page" id="trace-next-page" aria-label="Next trace page">Next</button>
        </nav>
      </div>
      <div class="table-wrap"><table data-testid="decision-trace-table"><thead><tr><th>Batch</th><th>Message</th><th>User</th><th>Class</th><th>Rank</th><th>Selection</th><th>Fit</th><th>Primary</th><th>Shadow</th><th>Provider</th><th>Disagree</th></tr></thead><tbody id="decision-trace-body"></tbody></table></div>
    </section>

    <section class="downloads-band" data-testid="downloads-section">
      <span class="eyebrow">Artifacts</span>
      <h2>Safe downloads</h2>
      <p class="section-copy">Downloads expose only approved processed/runtime fields. Raw prompt text, raw provider responses, headers, secrets, nickname, bio, and signature remain excluded.</p>
      <div class="downloads">{download_links}</div>
      <p class="footer-note">The manifest records SHA-256 for release-relevant artifacts and the rebuild validates path safety, hashes, schema tokens, and aggregate closure before publishing HTML.</p>
    </section>
  </main>

  <aside id="trace-drawer" class="drawer" data-testid="trace-drawer" role="dialog" aria-labelledby="trace-drawer-title" hidden>
    <header class="drawer-header">
      <div><span>Trace detail</span><h2 id="trace-drawer-title">Evidence detail</h2></div>
      <button id="trace-drawer-close" class="drawer-close" type="button" aria-label="Close trace detail" title="Close trace detail">×</button>
    </header>
    <div id="trace-drawer-body" class="drawer-body"></div>
  </aside>

  <script id="concurrent-message-payload" type="application/json">{payload_json}</script>
  <script>
const payload = JSON.parse(document.getElementById('concurrent-message-payload').textContent || '{}');
function compareTraceTokens(left, right) {{
  const leftToken = String(left);
  const rightToken = String(right);
  return leftToken < rightToken ? -1 : leftToken > rightToken ? 1 : 0;
}}
const traces = [...(payload.exposure_rows || [])].sort((left, right) => {{
  const timeDifference = Number(left.time_step) - Number(right.time_step);
  if (timeDifference) return timeDifference;
  const messageDifference = compareTraceTokens(left.message_id, right.message_id);
  if (messageDifference) return messageDifference;
  const userDifference = compareTraceTokens(left.user_id, right.user_id);
  if (userDifference) return userDifference;
  return compareTraceTokens(left.trace_id || left.pair_id, right.trace_id || right.pair_id);
}});
const lineages = payload.field_lineage || [];
const drawer = document.getElementById('trace-drawer');
const drawerBody = document.getElementById('trace-drawer-body');
const drawerTitle = document.getElementById('trace-drawer-title');
const closeButton = document.getElementById('trace-drawer-close');
const traceBody = document.getElementById('decision-trace-body');
const visibleTraceCount = document.getElementById('trace-match-count');
const tracePageStatus = document.getElementById('trace-page-status');
const tracePageSize = document.getElementById('trace-page-size');
const tracePageNumbers = document.getElementById('trace-page-numbers');
const previousTracePage = document.getElementById('trace-previous-page');
const nextTracePage = document.getElementById('trace-next-page');
const searchInput = document.getElementById('trace-search');
const filterIds = ['message-filter','class-filter','batch-filter','primary-action-filter','provider-status-filter','disagreement-filter'];
let returnFocusTarget = null;
let bodyOverflowBeforeDrawer = '';

function optionize(selectId, values) {{
  const select = document.getElementById(selectId);
  const distinct = [...new Set(values)].filter((value) => value !== undefined && value !== null && String(value) !== '').sort();
  distinct.forEach((value) => {{
    const option = document.createElement('option');
    option.value = String(value);
    option.textContent = String(value);
    select.appendChild(option);
  }});
}}

optionize('message-filter', traces.map((row) => row.message_id));
optionize('class-filter', traces.map((row) => row.latent_class));
optionize('batch-filter', traces.map((row) => row.time_step));
optionize('primary-action-filter', traces.map((row) => row.primary_action));

function element(tag, className, text) {{
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}}

function asSearchText(row) {{
  return [
    row.user_id,
    row.message_id,
    row.message_title,
    row.message_body,
    row.latent_class,
    row.time_step,
    row.selection_reason,
    row.provider_status,
    row.primary_action,
    row.shadow_action,
    row.primary_reason,
    row.shadow_reason,
  ].join(' ').toLowerCase();
}}

function passesFilters(row) {{
  const search = (searchInput.value || '').trim().toLowerCase();
  if (search && !asSearchText(row).includes(search)) return false;
  const messageValue = document.getElementById('message-filter').value;
  if (messageValue && row.message_id !== messageValue) return false;
  const classValue = document.getElementById('class-filter').value;
  if (classValue && row.latent_class !== classValue) return false;
  const batchValue = document.getElementById('batch-filter').value;
  if (batchValue && String(row.time_step) !== batchValue) return false;
  const primaryActionValue = document.getElementById('primary-action-filter').value;
  if (primaryActionValue && row.primary_action !== primaryActionValue) return false;
  const providerStatusValue = document.getElementById('provider-status-filter').value;
  if (providerStatusValue && row.provider_status !== providerStatusValue) return false;
  const disagreementValue = document.getElementById('disagreement-filter').value;
  if (disagreementValue && String(row.primary_shadow_disagreement) !== disagreementValue) return false;
  return true;
}}

function jsonBlock(value) {{
  const pre = element('pre', 'drawer-empty');
  pre.textContent = JSON.stringify(value, null, 2);
  return pre;
}}

function definitionList(items) {{
  const dl = element('dl');
  items.forEach(([label, value]) => {{
    dl.append(element('dt','',label), element('dd','', value === undefined || value === null ? '' : value));
  }});
  return dl;
}}

function renderLineage() {{
  const groups = {{ persisted_input: [], reconstructed_context: [], aggregate_evidence: [] }};
  lineages.forEach((entry) => groups[entry.evidence_class]?.push(entry));
  const wrapper = element('div', 'drawer-grid');
  [['persisted_input','Persisted input'],['reconstructed_context','Reconstructed context'],['aggregate_evidence','Aggregate evidence']].forEach(([key, label]) => {{
    const card = element('section', 'drawer-card');
    card.appendChild(element('h3', '', label));
    const list = element('ul', 'field-diff-list');
    (groups[key] || []).forEach((entry) => {{
      const item = element('li');
      item.appendChild(element('strong','',`${{entry.label}}`));
      item.appendChild(element('div','muted',`${{entry.description}} · source: ${{entry.source_artifact}} · visibility: ${{entry.prompt_visibility}}`));
      list.appendChild(item);
    }});
    card.appendChild(list);
    wrapper.appendChild(card);
  }});
  return wrapper;
}}

function openDrawer(row, trigger) {{
  returnFocusTarget = trigger || document.activeElement;
  bodyOverflowBeforeDrawer = document.body.style.overflow;
  drawer.dataset.selectionKind = 'trace';
  drawer.setAttribute('aria-modal', 'true');
  document.body.style.overflow = 'hidden';
  drawerTitle.textContent = `${{row.user_id}} · ${{row.message_id}} · batch ${{row.time_step}}`;
  drawerBody.replaceChildren();

  const messageCard = element('section', 'drawer-card');
  messageCard.appendChild(element('h3', '', 'Message and ranking evidence'));
  messageCard.appendChild(element('p', 'muted', 'Ranking evidence is platform-internal and did not enter either prompt.'));
  messageCard.appendChild(element('p', '', row.message_body));
  messageCard.appendChild(definitionList([
    ['Ranking position', row.ranking_position],
    ['Selection reason', row.selection_reason],
    ['Personalized delivery score', row.personalized_delivery_score],
    ['Base network relevance', row.ranking_evidence.base_network_relevance],
    ['Campaign engaged neighbor count', row.ranking_evidence.campaign_engaged_neighbor_count],
    ['Campaign engaged neighbor signal', row.ranking_evidence.campaign_engaged_neighbor_signal],
    ['Raw message-user fit', row.ranking_evidence.raw_message_user_fit],
    ['Normalized message-user fit', row.ranking_evidence.normalized_message_user_fit],
  ]));

  const primaryCard = element('section', 'drawer-card');
  primaryCard.appendChild(element('h3', '', 'Primary decision'));
  primaryCard.appendChild(definitionList([
    ['Status', row.primary_status],
    ['Action', row.primary_action],
    ['Probability', row.primary_probability],
    ['Confidence', row.primary_confidence],
    ['Reason', row.primary_reason],
    ['Decision source', row.primary_decision_source],
    ['Prompt token', row.primary_prompt_version],
  ]));
  primaryCard.appendChild(jsonBlock({{ profile_context: row.primary_context, peer_context: row.primary_peer_context }}));

  const shadowCard = element('section', 'drawer-card');
  shadowCard.appendChild(element('h3', '', 'Shadow decision'));
  shadowCard.appendChild(element('p', 'muted', 'Shadow is report-only and adds four synthetic demographic labels without mutating runtime state.'));
  shadowCard.appendChild(definitionList([
    ['Status', row.shadow_status],
    ['Action', row.shadow_action],
    ['Probability', row.shadow_probability],
    ['Confidence', row.shadow_confidence],
    ['Reason', row.shadow_reason],
    ['Decision source', row.shadow_decision_source],
    ['Prompt token', row.shadow_prompt_version],
  ]));
  const shadowFields = element('ul', 'shadow-field-list');
  Object.entries(row.shadow_added_fields || {{}}).forEach(([fieldName, value]) => {{
    const item = element('li');
    item.append(element('strong','',fieldName), element('div','muted',value));
    shadowFields.appendChild(item);
  }});
  shadowCard.appendChild(shadowFields);
  shadowCard.appendChild(jsonBlock({{ profile_context: row.shadow_context, peer_context: row.shadow_peer_context }}));

  const diffCard = element('section', 'drawer-card');
  diffCard.appendChild(element('h3', '', 'Field differences'));
  const diffList = element('ul', 'field-diff-list');
  (row.field_differences || []).forEach((difference) => {{
    const item = element('li');
    item.append(
      element('strong','',difference.label),
      element('div','muted',`Primary: ${{difference.primary_display}}`),
      element('div','muted',`Shadow: ${{difference.shadow_display}}`),
      element('div','muted',difference.note),
    );
    diffList.appendChild(item);
  }});
  diffCard.appendChild(diffList);

  const aggregateCard = element('section', 'drawer-card');
  aggregateCard.appendChild(element('h3', '', 'Aggregate evidence'));
  aggregateCard.appendChild(jsonBlock(row.aggregate_evidence));

  drawerBody.append(messageCard, primaryCard, shadowCard, diffCard, aggregateCard, renderLineage());
  drawer.hidden = false;
  closeButton.focus({{ preventScroll: true }});
}}

function closeDrawer(restoreFocus = true) {{
  if (drawer.dataset.selectionKind !== 'trace') return;
  const target = returnFocusTarget;
  returnFocusTarget = null;
  drawer.hidden = true;
  drawer.removeAttribute('data-selection-kind');
  drawer.removeAttribute('aria-modal');
  document.body.style.overflow = bodyOverflowBeforeDrawer;
  bodyOverflowBeforeDrawer = '';
  if (restoreFocus && target?.isConnected) target.focus({{ preventScroll: true }});
}}

const traceViewModel = {
  page: 1,
  pageSize: 50,
  filteredRows() {{ return traces.filter(passesFilters); }},
  totalPages(totalRows) {{ return Math.max(1, Math.ceil(totalRows / this.pageSize)); }},
  setPage(page, totalRows) {{
    this.page = Math.min(Math.max(1, Number(page) || 1), this.totalPages(totalRows));
  }},
  setPageSize(pageSize) {{
    const allowedSizes = [25, 50, 100];
    this.pageSize = allowedSizes.includes(Number(pageSize)) ? Number(pageSize) : 50;
    this.page = 1;
  }},
  currentRows(rows) {{
    const start = (this.page - 1) * this.pageSize;
    return rows.slice(start, start + this.pageSize);
  }},
}};

function renderTable() {{
  const rows = traceViewModel.filteredRows();
  const totalRows = rows.length;
  const totalPages = traceViewModel.totalPages(totalRows);
  traceViewModel.setPage(traceViewModel.page, totalRows);
  const currentRows = traceViewModel.currentRows(rows);
  const firstRow = totalRows ? (traceViewModel.page - 1) * traceViewModel.pageSize + 1 : 0;
  const lastRow = totalRows ? firstRow + currentRows.length - 1 : 0;
  visibleTraceCount.textContent = `${{totalRows.toLocaleString()}} matching trace row(s)`;
  tracePageStatus.textContent = totalRows
    ? `Showing ${{firstRow}}-${{lastRow}} of ${{totalRows.toLocaleString()}} matching trace rows - Page ${{traceViewModel.page}} of ${{totalPages}}`
    : 'Showing 0-0 of 0 matching trace rows - Page 1 of 1';
  previousTracePage.disabled = traceViewModel.page <= 1;
  nextTracePage.disabled = traceViewModel.page >= totalPages;
  tracePageSize.value = String(traceViewModel.pageSize);
  tracePageNumbers.replaceChildren();
  for (let page = 1; page <= totalPages; page += 1) {{
    const pageButton = element('button', '', page);
    pageButton.type = 'button';
    pageButton.dataset.page = String(page);
    pageButton.setAttribute('aria-label', `Go to trace page ${{page}}`);
    if (page === traceViewModel.page) pageButton.setAttribute('aria-current', 'page');
    pageButton.addEventListener('click', () => {{
      traceViewModel.setPage(page, totalRows);
      renderTable();
    }});
    tracePageNumbers.appendChild(pageButton);
  }}
  traceBody.replaceChildren();
  currentRows.forEach((row) => {{
    const tr = document.createElement('tr');
    tr.tabIndex = 0;
    tr.dataset.traceId = String(row.trace_id || row.pair_id || '');
    tr.dataset.pairId = String(row.pair_id || '');
    const cells = [
      row.time_step,
      row.message_id,
      row.user_id,
      row.latent_class,
      row.ranking_position,
      row.selection_reason,
      row.personalized_delivery_score,
      `${{row.primary_status}} / ${{row.primary_action}}`,
      `${{row.shadow_status}} / ${{row.shadow_action}}`,
      row.provider_status,
      row.primary_shadow_disagreement ? 'true' : 'false',
    ];
    cells.forEach((value) => tr.appendChild(element('td', '', value)));
    tr.addEventListener('click', () => openDrawer(row, tr));
    tr.addEventListener('keydown', (event) => {{
      if (event.key === 'Enter' || event.key === ' ') {{
        event.preventDefault();
        openDrawer(row, tr);
      }}
    }});
    traceBody.appendChild(tr);
  }});
}}

searchInput.addEventListener('input', () => {{ traceViewModel.page = 1; renderTable(); }});
filterIds.forEach((id) => document.getElementById(id).addEventListener('change', () => {{ traceViewModel.page = 1; renderTable(); }}));
tracePageSize.addEventListener('change', () => {{ traceViewModel.setPageSize(tracePageSize.value); renderTable(); }});
previousTracePage.addEventListener('click', () => {{ traceViewModel.setPage(traceViewModel.page - 1, traceViewModel.filteredRows().length); renderTable(); }});
nextTracePage.addEventListener('click', () => {{ traceViewModel.setPage(traceViewModel.page + 1, traceViewModel.filteredRows().length); renderTable(); }});
closeButton.addEventListener('click', () => closeDrawer(true));
document.querySelectorAll('[data-report-mode-target]').forEach((button) => button.addEventListener('click', () => closeDrawer(false)));
window.addEventListener('hashchange', () => closeDrawer(false));
document.addEventListener('keydown', (event) => {{
  if (event.key === 'Escape' && drawer.dataset.selectionKind === 'trace') closeDrawer(true);
}});
renderTable();
  </script>
</body>
</html>
"""

    rendered = (
        template.replace("{{", "{")
        .replace("}}", "}")
        .replace("{html.escape(payload.title)}", html.escape(payload.title))
        .replace("{html.escape(hero_copy)}", html.escape(hero_copy))
        .replace("{html.escape(status_label)}", html.escape(status_label))
        .replace("{summary_html}", summary_html)
        .replace(
            "{''.join(f'<li>{html.escape(note)}</li>' for note in payload.notes)}",
            "".join(f"<li>{html.escape(note)}</li>" for note in payload.notes),
        )
        .replace("{message_rows}", message_rows)
        .replace("{funnel_rows}", funnel_rows)
        .replace("{coverage_rows}", coverage_rows)
        .replace("{allocation_rows}", allocation_rows)
        .replace("{class_headers}", class_headers)
        .replace("{class_rows}", class_rows)
        .replace("{response_rows}", response_rows)
        .replace("{feedback_rows}", feedback_rows)
        .replace("{sensitivity_rows}", sensitivity_rows)
        .replace("{transition_rows}", transition_rows)
        .replace("{download_links}", download_links)
        .replace("{payload_json}", payload_json)
    )
    return rendered if include_pagination else _restore_pre_pagination_legacy_report(rendered)


def _restore_pre_pagination_legacy_report(rendered: str) -> str:
    """Restore the renderer bytes used by persisted reports before trace pagination."""
    def replace_between(value: str, start_marker: str, end_marker: str, replacement: str, label: str) -> str:
        start = value.find(start_marker)
        end = value.find(end_marker, start + len(start_marker)) if start >= 0 else -1
        if start < 0 or end < 0:
            raise ValueError(f"cannot restore historical Concurrent renderer fragment {label}")
        return value[:start] + replacement + value[end:]

    for current, historical, label in (
        (
            "    .trace-count { margin: 16px 0 8px; font-weight: 700; color: var(--blue); }\n",
            "    .trace-count { font-weight: 700; color: var(--blue); }\n",
            "legacy trace count style",
        ),
        (
            "    .trace-pagination { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 14px 20px; align-items: end; margin: 12px 0 18px; }\n",
            "",
            "legacy pagination style",
        ),
        (
            "    .trace-page-size { display: grid; gap: 6px; max-width: 180px; color: var(--muted); font-size: 12px; }\n",
            "",
            "legacy page-size style",
        ),
        ("    .trace-page-size select { min-width: 0; }\n", "", "legacy page-size select style"),
        (
            "    .trace-page-status { margin: 8px 0 0; color: var(--muted); font-size: 12px; }\n",
            "",
            "legacy page-status style",
        ),
        (
            "    .trace-page-controls { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 6px; }\n",
            "",
            "legacy page-controls style",
        ),
        (
            "    .trace-page-controls button { min-width: 38px; min-height: 38px; padding: 7px 10px; border: 1px solid var(--line); border-radius: 6px; background: #fff; color: var(--ink); font: inherit; font-size: 12px; font-weight: 700; cursor: pointer; white-space: nowrap; }\n",
            "",
            "legacy page button style",
        ),
        (
            "    .trace-page-controls button:hover:not(:disabled), .trace-page-controls button:focus-visible { border-color: var(--blue); outline: 2px solid rgba(31, 95, 166, 0.18); outline-offset: 2px; }\n",
            "",
            "legacy page hover style",
        ),
        (
            "    .trace-page-controls button[aria-current=\"page\"] { border-color: var(--blue); background: #edf4fc; color: var(--blue); }\n",
            "",
            "legacy current page style",
        ),
        ("    .trace-page-controls button:disabled { cursor: not-allowed; opacity: .45; }\n", "", "legacy disabled page style"),
        (
            "    .trace-page-numbers { display: inline-flex; flex-wrap: wrap; justify-content: center; gap: 6px; }\n",
            "",
            "legacy page numbers style",
        ),
        ("      .trace-pagination { grid-template-columns: 1fr; align-items: stretch; }\n", "", "legacy mobile pagination style"),
        ("      .trace-page-size { max-width: none; }\n", "", "legacy mobile page-size style"),
        ("      .trace-page-controls { justify-content: flex-start; }\n", "", "legacy mobile page-controls style"),
        ("      .trace-page-numbers { justify-content: flex-start; }\n", "", "legacy mobile page numbers style"),
    ):
        occurrences = rendered.count(current)
        if occurrences != 1:
            raise ValueError(f"cannot restore historical Concurrent renderer fragment {label}: found {occurrences}")
        rendered = rendered.replace(current, historical, 1)

    rendered = rendered.replace(
        "The report freezes the three authoritative message bodies and their Intended Audience Segments, alongside the paired prompt tokens and safe tuple artifacts. Intended Audience Segment is a design descriptor only: it is not exposure eligibility and is not a Prompt field. Changing any crossed token, aggregate, or artifact hash fails the rebuild.",
        "The report freezes the three authoritative message bodies, the paired prompt tokens, and the safe tuple artifacts. Changing any crossed token, aggregate, or artifact hash fails the rebuild.",
        1,
    )
    rendered = replace_between(
        rendered,
        '      <p class="trace-count" data-testid="visible-trace-count" id="visible-trace-count"><span',
        '      <div class="table-wrap"><table data-testid="decision-trace-table">',
        '      <p class="trace-count" data-testid="visible-trace-count" id="visible-trace-count"></p>\n',
        "legacy pagination markup",
    )
    rendered = replace_between(
        rendered,
        "function compareTraceTokens(left, right) {\n",
        "const lineages = payload.field_lineage || [];\n",
        "const traces = payload.exposure_rows || [];\n",
        "legacy trace sorting",
    )
    rendered = replace_between(
        rendered,
        "const visibleTraceCount = document.getElementById('trace-match-count');\n",
        "const searchInput = document.getElementById('trace-search');\n",
        "const visibleTraceCount = document.getElementById('visible-trace-count');\n",
        "legacy trace controls",
    )
    rendered = rendered.replace(
        "let returnFocusTarget = null;\nlet bodyOverflowBeforeDrawer = '';\n",
        "",
        1,
    )
    rendered = rendered.replace(
        """    row.message_body,
    row.latent_class,
    row.time_step,
    row.selection_reason,
    row.provider_status,
    row.primary_action,
    row.shadow_action,
    row.primary_reason,
    row.shadow_reason,
""",
        """    row.primary_action,
    row.shadow_action,
    row.primary_reason,
    row.shadow_reason,
    row.latent_class,
""",
        1,
    )
    rendered = replace_between(
        rendered,
        "function openDrawer(row, trigger) {\n",
        "  drawerTitle.textContent =",
        "function openDrawer(row) {\n",
        "legacy drawer open",
    )
    rendered = replace_between(
        rendered,
        "function closeDrawer(restoreFocus = true) {\n",
        "  currentRows.forEach((row) => {\n",
        """function closeDrawer() {
  drawer.hidden = true;
}

function renderTable() {
  const rows = traces.filter(passesFilters);
  visibleTraceCount.textContent = `${rows.length.toLocaleString()} visible trace row(s)`;
  traceBody.replaceChildren();
  rows.forEach((row) => {
""",
        "legacy trace pagination model",
    )
    rendered = rendered.replace(
        "  currentRows.forEach((row) => {\n",
        "",
        1,
    )
    rendered = rendered.replace(
        """    tr.dataset.traceId = String(row.trace_id || row.pair_id || '');
    tr.dataset.pairId = String(row.pair_id || '');
""",
        "",
        1,
    )
    rendered = rendered.replace(
        """    tr.addEventListener('click', () => openDrawer(row, tr));
    tr.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        openDrawer(row, tr);
      }
    });
""",
        """    tr.addEventListener('click', () => openDrawer(row));
    tr.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); openDrawer(row); } });
""",
        1,
    )
    rendered = rendered.replace(
        """searchInput.addEventListener('input', () => { traceViewModel.page = 1; renderTable(); });
filterIds.forEach((id) => document.getElementById(id).addEventListener('change', () => { traceViewModel.page = 1; renderTable(); }));
tracePageSize.addEventListener('change', () => { traceViewModel.setPageSize(tracePageSize.value); renderTable(); });
previousTracePage.addEventListener('click', () => { traceViewModel.setPage(traceViewModel.page - 1, traceViewModel.filteredRows().length); renderTable(); });
nextTracePage.addEventListener('click', () => { traceViewModel.setPage(traceViewModel.page + 1, traceViewModel.filteredRows().length); renderTable(); });
closeButton.addEventListener('click', () => closeDrawer(true));
document.querySelectorAll('[data-report-mode-target]').forEach((button) => button.addEventListener('click', () => closeDrawer(false)));
window.addEventListener('hashchange', () => closeDrawer(false));
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && drawer.dataset.selectionKind === 'trace') closeDrawer(true);
});
""",
        """searchInput.addEventListener('input', renderTable);
filterIds.forEach((id) => document.getElementById(id).addEventListener('change', renderTable));
closeButton.addEventListener('click', closeDrawer);
document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && !drawer.hidden) closeDrawer(); });
""",
        1,
    )
    return rendered


def _three_part(payload: object) -> str:
    mapping = _required_mapping(payload, "attempt/succeed/fail payload", "summary")
    return f"{_as_int(mapping.get('attempted'))} / {_as_int(mapping.get('succeeded'))} / {_as_int(mapping.get('provider_failed'))}"


class _LegacyRendererAdapter:
    """Compatibility adapter for the existing single-flow Concurrent HTML."""

    def render(self, payload: Any) -> str:
        return _legacy_render_report(payload)


class _CurrentRendererAdapter:
    """Mechanism-first two-mode adapter for new Concurrent Message artifacts."""

    def render(self, payload: Any) -> str:
        return _render_current_report(payload, _legacy_render_report)


class _HistoricalRendererAdapter:
    """Frozen adapter for persisted Concurrent reports before trace pagination."""

    def render(self, payload: Any) -> str:
        return _legacy_render_report(payload, include_pagination=False)


_LEGACY_ADAPTER = _LegacyRendererAdapter()
_CURRENT_ADAPTER = _CurrentRendererAdapter()
_HISTORICAL_ADAPTER = _HistoricalRendererAdapter()
_FIXED_ADAPTERS = (_CURRENT_ADAPTER, _LEGACY_ADAPTER, _HISTORICAL_ADAPTER)


def render_report(payload: Any, *, expected_sha256: str | None = None) -> str:
    """Render current artifacts, or dispatch to a historical exact adapter by hash."""
    if expected_sha256 is None:
        return _CURRENT_ADAPTER.render(payload)
    for adapter in _FIXED_ADAPTERS:
        rendered = adapter.render(payload)
        if _sha256_text(rendered) == expected_sha256:
            return rendered
    raise ValueError(
        "no concurrent message renderer matched the expected report SHA-256; "
        "report bytes may be crossed, tampered, or have changed provider metadata "
        "(observed_model/requested model)"
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _rate_label(rate_payload: Mapping[str, Any]) -> str:
    return f"{rate_payload.get('numerator')} / {rate_payload.get('denominator')} = {rate_payload.get('value')}"


def _delta_label(delta_payload: Mapping[str, Any]) -> str:
    return (
        f"{delta_payload.get('absolute_delta_sum')} / {delta_payload.get('denominator')} = {delta_payload.get('value')}"
    )


def _required_mapping(value: object, description: str, parent: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{parent} must contain a mapping for {description}")
    if description in value:
        nested = value[description]
        if not isinstance(nested, Mapping):
            raise ValueError(f"{parent} must contain a mapping for {description}")
        return {str(key): item for key, item in nested.items()}
    return {str(key): item for key, item in value.items()}


def _required_list(value: object, description: str) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{description} must be a list")
    rows: list[dict[str, Any]] = []
    for row in value:
        if not isinstance(row, Mapping):
            raise ValueError(f"{description} must contain only objects")
        rows.append({str(key): item for key, item in row.items()})
    return rows


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        token = value.strip().lower()
        if token in {"true", "1", "yes"}:
            return True
        if token in {"false", "0", "no", ""}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    raise ValueError(f"cannot coerce {value!r} to bool")


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError(f"cannot coerce bool {value!r} to int")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        token = value.strip()
        if not token:
            return 0
        return int(token)
    raise ValueError(f"cannot coerce {value!r} to int")
