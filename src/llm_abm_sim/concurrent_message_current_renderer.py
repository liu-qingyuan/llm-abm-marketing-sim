from __future__ import annotations

import html
from collections.abc import Callable
from typing import Any


def _legacy_run_fragments(payload: Any, legacy_renderer: Callable[[Any], str]) -> tuple[str, str]:
    """Reuse legacy evidence markup inside the current shell."""
    legacy_document = legacy_renderer(payload)
    style_start = legacy_document.index("<style>")
    style_end = legacy_document.index("</style>", style_start) + len("</style>")
    legacy_style = legacy_document[style_start:style_end]
    body_start = legacy_document.index("<body>") + len("<body>")
    body_end = legacy_document.index("</body>", body_start)
    legacy_body = legacy_document[body_start:body_end]

    main_open = '<main data-testid="concurrent-message-report">'
    if main_open not in legacy_body:
        raise ValueError("legacy concurrent report is missing its compatibility root")
    legacy_body = legacy_body.replace(main_open, '<div class="legacy-run-main">', 1)
    legacy_body = legacy_body.replace("</main>", "</div>", 1)
    anchor_replacements = (
        (
            '<header class="hero">',
            '<header class="hero" data-section-anchor="overview" tabindex="-1">',
        ),
        (
            '<section class="content-band" data-testid="messages-section">',
            '<section class="content-band" data-testid="messages-section" data-section-anchor="sample" tabindex="-1">',
        ),
        (
            '<section class="content-band" data-testid="message-allocation-section">',
            '<section class="content-band" data-testid="message-allocation-section" data-section-anchor="exposure-ranking" tabindex="-1">',
        ),
        (
            '<section class="content-band" data-testid="primary-audience-response-section">',
            '<section class="content-band" data-testid="primary-audience-response-section" data-section-anchor="llm-decision" tabindex="-1">',
        ),
        (
            '<section class="content-band" data-testid="campaign-feedback-effect-section">',
            '<section class="content-band" data-testid="campaign-feedback-effect-section" data-section-anchor="network-feedback" tabindex="-1">',
        ),
    )
    for original, replacement in anchor_replacements:
        if original not in legacy_body:
            raise ValueError(f"legacy concurrent report is missing anchor source: {original}")
        legacy_body = legacy_body.replace(original, replacement, 1)
    return legacy_style, legacy_body


def _queue_cards(payload: Any) -> str:
    return "".join(
        (
            '<article class="current-queue-card">'
            '<span class="current-queue-label">独立 queue</span>'
            f"<h3>{html.escape(str(message.get('title', message.get('message_id', ''))))}</h3>"
            f"<p>{html.escape(str(message.get('intended_audience_segment', '')))}：该 message 维护自己的候选队列。</p>"
            '<span class="current-queue-boundary">platform-owned exposure queue</span>'
            "</article>"
        )
        for message in payload.messages
    )


def _mechanism_html(payload: Any) -> str:
    return f"""
        <section id="overview" class="current-section current-mechanism-overview" data-section-anchor="overview" tabindex="-1">
          <span class="current-eyebrow">MECHANISM / 机制说明</span>
          <h1 id="mechanism-overview-title">Multi-Message 机制说明</h1>
          <p class="current-lede">这里解释稳定的 Multi-Message 运行边界，不展示或推断某次 run 的 outcome。三条 message 同时进入独立 queue；平台先决定 exposure，LLM 只处理已经曝光的 user × message pair。</p>
          <div class="current-queue-grid" data-testid="mechanism-message-queues">{_queue_cards(payload)}</div>
          <div class="current-rule-grid">
            <article class="current-rule-card"><strong>01</strong><h2>同时入队</h2><p>三条 message 在同一发布边界进入各自 queue，不按文案顺序获得先发优势。</p></article>
            <article class="current-rule-card"><strong>02</strong><h2>平台决定 exposure</h2><p>Platform Environment 负责候选、排序和 delivery capacity；LLM 不参与曝光调度。</p></article>
            <article class="current-rule-card"><strong>03</strong><h2>LLM 处理已曝光 pair</h2><p>Decision Adapter 只接收已经选定的 user × message × exposure context，并返回结构化 Decision。</p></article>
            <article class="current-rule-card"><strong>04</strong><h2>Shadow 仅作 report-only</h2><p>Demographic Shadow 只做配对敏感性比较，不写入 action、ranking、feedback 或 runtime state。</p></article>
          </div>
          <p class="current-boundary-note" data-testid="mechanism-boundary-note">机制说明不把 persisted run 计数、Provider 结果或用户结果写入稳定规则；请切换到“本次运行”查看现有 evidence。</p>
        </section>

        <section id="sample" class="current-section" data-section-anchor="sample" tabindex="-1">
          <span class="current-eyebrow">SAMPLE / 样本</span>
          <h2>同一研究样本，多条独立 message queue</h2>
          <p>用户可以进入一条或多条 message queue。样本角色、覆盖率和实际 pair 数属于本次运行的 persisted evidence，不在机制模式中预设。</p>
          <div class="current-callout"><strong>稳定边界</strong><span>queue eligibility 以 user 尚未获得该 message exposure 为边界；同一用户在不同 message 上是不同 pair。</span></div>
        </section>

        <section id="exposure-ranking" class="current-section" data-section-anchor="exposure-ranking" tabindex="-1">
          <span class="current-eyebrow">EXPOSURE / 曝光排序</span>
          <h2>先排序，再形成 Recommendation Opportunity</h2>
          <p>每条 message 维护自己的 personalized candidate queue。平台在每个 batch 冻结排序并选择有限 delivery capacity，未获得 exposure 的 pair 不产生 Decision Trace。</p>
          <div class="current-signal-row"><span>candidate queue</span><span>platform ranking</span><span>delivery capacity</span></div>
        </section>

        <section id="llm-decision" class="current-section" data-section-anchor="llm-decision" tabindex="-1">
          <span class="current-eyebrow">DECISION / LLM 决策</span>
          <h2>结构化 Decision 只描述已曝光 pair</h2>
          <p>LLM 输出 engage、probability、reason、confidence 和 action。Ranking evidence 留在平台内部，不被误写成 Prompt 输入；机制模式不把任意 provider response 当作本次结果。</p>
          <div class="current-contract-row"><code>engage</code><code>probability</code><code>reason</code><code>confidence</code><code>action</code></div>
        </section>

        <section id="network-feedback" class="current-section" data-section-anchor="network-feedback" tabindex="-1">
          <span class="current-eyebrow">FEEDBACK / 网络反馈</span>
          <h2>Primary feedback 与 Shadow 边界分开</h2>
          <p>Primary 的 like、comment、share 可以形成下一轮排序信号；ignore 不传播。Shadow 是 report-only 的 paired computation，不改变 exposure、Decision 或网络状态。</p>
          <div class="current-callout"><strong>研究限制</strong><span>这些规则解释 simulation contract，不等于真实平台观察、用户心理或 message 的因果胜负。</span></div>
        </section>
        """


_CURRENT_CSS = """
.current-report-shell { min-height: 100vh; background: #fff; }
.current-topbar { position: sticky; top: 0; z-index: 20; display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 18px; min-height: 72px; padding: 10px clamp(18px, 4vw, 52px); border-bottom: 1px solid #d8e1ee; background: #fbfcfe; }
.current-brand { color: #0f1b2d; font-size: 17px; font-weight: 800; white-space: nowrap; }
.current-workflow-nav { display: flex; justify-content: center; gap: clamp(16px, 2.2vw, 34px); min-width: 0; overflow-x: auto; white-space: nowrap; }
.current-workflow-nav a { position: relative; display: flex; align-items: center; min-height: 42px; padding: 8px 0; color: #5e6e82; font-size: 13px; font-weight: 760; text-decoration: none; }
.current-workflow-nav a::after { content: ""; position: absolute; right: 0; bottom: 0; left: 0; height: 3px; background: transparent; }
.current-workflow-nav a:hover, .current-workflow-nav a:focus-visible, .current-workflow-nav a[aria-current="location"] { color: #1f5fa6; }
.current-workflow-nav a[aria-current="location"]::after { background: #1f5fa6; }
.current-workflow-nav a:focus-visible, .current-mode-switch button:focus-visible { outline: 2px solid #1f5fa6; outline-offset: 3px; }
.current-mode-switch { display: flex; gap: 4px; padding: 3px; border: 1px solid #d8e1ee; border-radius: 6px; background: #fff; }
.current-mode-switch button { min-height: 38px; padding: 8px 12px; border: 0; border-radius: 4px; background: transparent; color: #5e6e82; font: inherit; font-size: 13px; font-weight: 760; cursor: pointer; }
.current-mode-switch button[aria-selected="true"] { background: #1f5fa6; color: #fff; }
.current-mode-panel[hidden] { display: none !important; }
.legacy-run-main { width: 100%; min-width: 0; background: #fff; }
.current-section { min-height: 420px; padding: clamp(34px, 6vw, 76px) clamp(18px, 7vw, 104px); border-bottom: 1px solid #d8e1ee; scroll-margin-top: 84px; }
.current-mechanism-overview { min-height: 680px; background: #f7fbff; }
.current-eyebrow { display: inline-block; margin-bottom: 10px; color: #206b56; font-size: 11px; font-weight: 800; }
.current-section h1, .current-section h2 { max-width: 820px; margin: 0 0 14px; color: #0f1b2d; line-height: 1.15; }
.current-section h1 { font-size: 3.2rem; }
.current-section h2 { font-size: 2.35rem; }
.current-lede, .current-section > p { max-width: 820px; color: #5e6e82; font-size: 16px; line-height: 1.7; }
.current-queue-grid, .current-rule-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-top: 28px; }
.current-rule-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); margin-top: 18px; }
.current-queue-card, .current-rule-card, .current-callout { min-width: 0; padding: 18px; border: 1px solid #d8e1ee; border-radius: 6px; background: #fff; }
.current-queue-card h3, .current-rule-card h2 { margin: 8px 0; font-size: 16px; line-height: 1.3; }
.current-queue-card p, .current-rule-card p, .current-callout span { margin: 0; color: #5e6e82; line-height: 1.6; }
.current-queue-label, .current-queue-boundary { display: block; color: #1f5fa6; font-size: 11px; font-weight: 800; }
.current-queue-boundary { margin-top: 12px; color: #206b56; }
.current-rule-card > strong { color: #1f5fa6; font-size: 12px; }
.current-boundary-note { margin-top: 28px; padding: 14px 16px; border-left: 4px solid #9a5b12; background: #fff9f2; color: #6f4a18 !important; }
.current-callout { display: grid; grid-template-columns: minmax(120px, .28fr) minmax(0, 1fr); gap: 16px; max-width: 820px; margin-top: 26px; }
.current-callout strong { color: #206b56; }
.current-signal-row, .current-contract-row { display: flex; flex-wrap: wrap; gap: 8px; max-width: 820px; margin-top: 26px; }
.current-signal-row span, .current-contract-row code { min-height: 38px; display: inline-flex; align-items: center; padding: 8px 12px; border: 1px solid #cfe2d7; border-radius: 6px; background: #edf7f2; color: #206b56; font: inherit; font-weight: 700; }
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: .01ms !important; animation-iteration-count: 1 !important; scroll-behavior: auto !important; transition-duration: .01ms !important; }
}
@media (max-width: 900px) {
  .current-topbar { grid-template-columns: 1fr auto; }
  .current-workflow-nav { grid-column: 1 / -1; justify-content: flex-start; order: 3; }
  .current-queue-grid, .current-rule-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 560px) {
  .current-topbar { grid-template-columns: 1fr; gap: 8px; padding: 10px 18px; }
  .current-mode-switch { width: 100%; }
  .current-mode-switch button { flex: 1; }
  .current-workflow-nav { gap: 20px; }
  .current-queue-grid, .current-rule-grid { grid-template-columns: 1fr; }
  .current-section { min-height: 360px; padding: 34px 18px; }
  .current-section h1 { font-size: 2rem; }
  .current-callout { grid-template-columns: 1fr; gap: 8px; }
}
"""


def render_current_report(payload: Any, legacy_renderer: Callable[[Any], str]) -> str:
    legacy_style, legacy_body = _legacy_run_fragments(payload, legacy_renderer)
    title = html.escape(str(payload.title), quote=True)
    mechanism_html = _mechanism_html(payload)
    template = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>{_CURRENT_CSS}</style>
  {legacy_style}
</head>
<body>
  <main class="current-report-shell" data-testid="concurrent-message-report" data-report-mode="mechanism">
    <header class="current-topbar">
      <div class="current-brand">Concurrent Message</div>
      <nav class="current-workflow-nav" aria-label="五段报告导航">
        <a data-report-anchor="overview" href="#overview">概览</a>
        <a data-report-anchor="sample" href="#sample">样本</a>
        <a data-report-anchor="exposure-ranking" href="#exposure-ranking">曝光排序</a>
        <a data-report-anchor="llm-decision" href="#llm-decision">LLM 决策</a>
        <a data-report-anchor="network-feedback" href="#network-feedback">网络反馈</a>
      </nav>
      <div class="current-mode-switch" role="tablist" aria-label="报告模式">
        <button id="mechanism-mode-tab" type="button" role="tab" aria-selected="true" aria-controls="mechanism-mode-panel" tabindex="0" data-report-mode-target="mechanism" data-testid="mechanism-mode-button">机制说明</button>
        <button id="run-evidence-mode-tab" type="button" role="tab" aria-selected="false" aria-controls="run-evidence-mode-panel" tabindex="-1" data-report-mode-target="run-evidence" data-testid="run-evidence-mode-button">本次运行</button>
      </div>
    </header>
    <section id="mechanism-mode-panel" role="tabpanel" aria-labelledby="mechanism-mode-tab" data-report-mode-panel="mechanism" data-testid="mechanism-mode-panel">
      {mechanism_html}
    </section>
    <section id="run-evidence-mode-panel" role="tabpanel" aria-labelledby="run-evidence-mode-tab" data-report-mode-panel="run-evidence" data-testid="run-evidence-mode-panel" hidden>
      {legacy_body}
    </section>
    <script>
    (() => {{
      const root = document.querySelector('[data-testid="concurrent-message-report"]');
      const modeButtons = [...root.querySelectorAll('[data-report-mode-target]')];
      const modePanels = [...root.querySelectorAll('[data-report-mode-panel]')];
      const navigationLinks = [...root.querySelectorAll('[data-report-anchor]')];
      const anchors = ['overview', 'sample', 'exposure-ranking', 'llm-decision', 'network-feedback'];
      const state = {{ mode: 'mechanism', anchor: 'overview' }};

      function hashFor(mode, anchor) {{
        return mode === 'run-evidence' ? `#run/${{anchor}}` : `#${{anchor}}`;
      }}

      function parseHash() {{
        const raw = window.location.hash.slice(1);
        if (raw.startsWith('run/') && anchors.includes(raw.slice(4))) return {{ mode: 'run-evidence', anchor: raw.slice(4) }};
        if (anchors.includes(raw)) return {{ mode: 'mechanism', anchor: raw }};
        return {{ mode: 'mechanism', anchor: 'overview' }};
      }}

      function targetFor(mode, anchor) {{
        const panel = modePanels.find((candidate) => candidate.dataset.reportModePanel === mode);
        return panel?.querySelector(`[data-section-anchor="${{anchor}}"]`) || null;
      }}

      function setActiveNavigation(anchor) {{
        state.anchor = anchor;
        navigationLinks.forEach((link) => {{
          if (link.dataset.reportAnchor === anchor) link.setAttribute('aria-current', 'location');
          else link.removeAttribute('aria-current');
          link.setAttribute('href', hashFor(state.mode, link.dataset.reportAnchor));
        }});
      }}

      function setMode(mode) {{
        state.mode = mode;
        root.dataset.reportMode = mode;
        modeButtons.forEach((button) => {{
          const selected = button.dataset.reportModeTarget === mode;
          button.setAttribute('aria-selected', String(selected));
          button.tabIndex = selected ? 0 : -1;
        }});
        modePanels.forEach((panel) => {{ panel.hidden = panel.dataset.reportModePanel !== mode; }});
        setActiveNavigation(state.anchor);
      }}

      function applyLocation({{ focus = false }} = {{}}) {{
        const location = parseHash();
        state.anchor = location.anchor;
        setMode(location.mode);
        setActiveNavigation(location.anchor);
        const target = targetFor(location.mode, location.anchor);
        if (focus && target) {{
          target.scrollIntoView({{ block: 'start' }});
          target.setAttribute('tabindex', '-1');
          target.focus({{ preventScroll: true }});
        }}
      }}

      function navigate(mode, anchor, focus) {{
        const nextHash = hashFor(mode, anchor);
        if (window.location.hash !== nextHash) history.pushState(null, '', nextHash);
        state.mode = mode;
        state.anchor = anchor;
        applyLocation({{ focus }});
      }}

      modeButtons.forEach((button, index) => {{
        button.addEventListener('click', () => navigate(button.dataset.reportModeTarget, state.anchor, false));
        button.addEventListener('keydown', (event) => {{
          if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
          event.preventDefault();
          const offset = event.key === 'ArrowRight' ? 1 : -1;
          const next = modeButtons[(index + offset + modeButtons.length) % modeButtons.length];
          next.focus();
          navigate(next.dataset.reportModeTarget, state.anchor, false);
        }});
      }});

      navigationLinks.forEach((link) => link.addEventListener('click', (event) => {{
        const anchor = link.dataset.reportAnchor;
        if (!anchor) return;
        event.preventDefault();
        navigate(state.mode, anchor, true);
      }}));

      window.addEventListener('hashchange', () => applyLocation({{ focus: true }}));
      window.addEventListener('popstate', () => applyLocation({{ focus: true }}));

      if (typeof IntersectionObserver === 'function') {{
        const visibleSections = new Set();
        const observer = new IntersectionObserver((entries) => {{
          entries.forEach((entry) => {{
            if (entry.isIntersecting && !entry.target.closest('[hidden]')) visibleSections.add(entry.target);
            else visibleSections.delete(entry.target);
          }});
          const current = [...visibleSections]
            .filter((section) => !section.closest('[hidden]'))
            .sort((left, right) => Math.abs(left.getBoundingClientRect().top - 84) - Math.abs(right.getBoundingClientRect().top - 84))[0];
          if (current) setActiveNavigation(current.dataset.sectionAnchor);
        }}, {{ rootMargin: '-84px 0px -55% 0px', threshold: 0 }});
        root.querySelectorAll('[data-report-mode-panel] [data-section-anchor]').forEach((section) => observer.observe(section));
      }}

      applyLocation({{ focus: window.location.hash.length > 0 }});
    }})();
    </script>
  </main>
</body>
</html>"""
    return template
