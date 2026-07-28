from __future__ import annotations

import html
from base64 import b64encode
from collections.abc import Callable, Mapping
from importlib.resources import files
from typing import Any

_MECHANISM_ASSETS = {
    "overview": "multi-message-mechanism-overview.webp",
    "sample": "multi-message-mechanism-sample.webp",
    "ranking": "multi-message-mechanism-ranking.webp",
    "decision": "multi-message-mechanism-decision.webp",
    "feedback": "multi-message-mechanism-feedback.webp",
}


def _embedded_mechanism_asset(asset_key: str) -> str:
    file_name = _MECHANISM_ASSETS[asset_key]
    image_bytes = files("llm_abm_sim").joinpath("report_assets").joinpath(file_name).read_bytes()
    return f"data:image/webp;base64,{b64encode(image_bytes).decode('ascii')}"


def _value(source: object, key: str, default: object = "") -> object:
    if isinstance(source, Mapping):
        return source.get(key, default)
    return getattr(source, key, default)


def _escaped(value: object, *, quote: bool = False) -> str:
    return html.escape(str(value), quote=quote)


def _legacy_run_fragments(payload: Any, legacy_renderer: Callable[[Any], str]) -> tuple[str, str, str]:
    """Reuse legacy evidence markup while keeping its shared drawer outside hidden panels."""
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
    main_start = legacy_body.index(main_open)
    main_end = legacy_body.index("</main>", main_start) + len("</main>")
    legacy_main = legacy_body[main_start:main_end]
    legacy_extras = legacy_body[:main_start] + legacy_body[main_end:]
    legacy_main = legacy_main.replace(main_open, '<div class="legacy-run-main">', 1)
    legacy_main = legacy_main.replace("</main>", "</div>", 1)

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
        if original not in legacy_main:
            raise ValueError(f"legacy concurrent report is missing anchor source: {original}")
        legacy_main = legacy_main.replace(original, replacement, 1)
    return legacy_style, legacy_main, legacy_extras


def _queue_cards(payload: Any) -> str:
    cards: list[str] = []
    for index, message in enumerate(payload.messages, start=1):
        message_id = _escaped(_value(message, "message_id"), quote=True)
        title = _escaped(_value(message, "title", message_id))
        audience = _escaped(_value(message, "intended_audience_segment", "当前 message 的设计受众"))
        cards.append(
            f"""
            <article class="current-queue-card current-queue-card-{index}" data-testid="mechanism-message-queue-{index}">
              <span class="current-queue-index">MESSAGE 0{index}</span>
              <h3>{title}</h3>
              <p><code>{message_id}</code> 维护自己的 personalized candidate queue。</p>
              <span class="current-queue-audience">Intended audience：{audience}</span>
            </article>
            """
        )
    return "".join(cards)


def _hotspot(
    key: str,
    test_id: str,
    label: str,
    caption: str,
    class_name: str = "",
) -> str:
    classes = f"current-hotspot {class_name}".strip()
    return (
        f'<button class="{classes}" type="button" data-mechanism-key="{_escaped(key, quote=True)}" '
        f'data-testid="{_escaped(test_id, quote=True)}" aria-label="查看{_escaped(label)}详情" '
        'aria-expanded="false" aria-controls="trace-drawer">'
        f"<strong>{_escaped(label)}</strong><span>{_escaped(caption)}</span></button>"
    )


def _legend(items: tuple[tuple[str, str], ...]) -> str:
    return "<div class=\"current-legend\" role=\"list\" aria-label=\"机制图例\">" + "".join(
        f'<span role="listitem"><i class="legend-swatch legend-swatch-{_escaped(color, quote=True)}" aria-hidden="true"></i>{_escaped(label)}</span>'
        for color, label in items
    ) + "</div>"


def _mechanism_html(payload: Any) -> str:
    overview_asset = _embedded_mechanism_asset("overview")
    sample_asset = _embedded_mechanism_asset("sample")
    ranking_asset = _embedded_mechanism_asset("ranking")
    decision_asset = _embedded_mechanism_asset("decision")
    feedback_asset = _embedded_mechanism_asset("feedback")
    queue_cards = _queue_cards(payload)
    return f"""
      <section id="overview" class="current-section current-scene current-overview-scene" data-section-anchor="overview" data-testid="mechanism-overview-section" tabindex="-1">
        <div class="current-scene-heading">
          <div>
            <span class="current-kicker">MECHANISM / 机制说明</span>
            <h1>三条 message，从同一个研究样本同时开始</h1>
          </div>
          <p>这是一份稳定机制说明：三条 message 同时进入独立 queue，分别维护自己的候选排序；平台先决定 exposure，LLM 只处理已经曝光的 user × message pair。机制模式不读取本次 run 的 outcome。</p>
        </div>
        <div class="current-contract-grid" aria-label="Multi-Message stable contract">
          <article data-testid="mechanism-sample-size"><strong>1,000</strong><span>Research Sample<br>研究样本用户</span></article>
          <article data-testid="mechanism-eligible-pairs"><strong>3,000</strong><span>eligible user-message pairs<br>合格 user × message pairs</span></article>
          <article data-testid="mechanism-message-count"><strong>3</strong><span>messages start together<br>三条 message 同时开始</span></article>
          <article data-testid="mechanism-batch-contract"><strong>30 × Top20</strong><span>per message<br>每条 message 的批次与容量合同</span></article>
        </div>
        <div class="current-queue-grid" data-testid="mechanism-message-queues">{queue_cards}</div>
        <figure class="current-visual current-visual-overview" data-testid="mechanism-overview-visual">
          <img data-testid="multi-message-overview-illustration" src="{overview_asset}" width="1024" height="576" alt="三条 message 同时进入三条独立 queue，再进入同一研究样本边界的机制示意图">
          {_hotspot("overview-start", "mechanism-overview-hotspot-start", "同时开始边界", "三条 queue 同时建立")}
          {_hotspot("overview-pair", "mechanism-overview-hotspot-pair", "user × message pair", "已曝光后才产生 Decision")}
          <figcaption>同一研究样本允许跨 message overlap；这里展示的是 queue 与 exposure 的稳定关系，不是任何一次运行的结果图。</figcaption>
        </figure>
        {_legend((("navy", "研究样本边界"), ("blue", "message queue"), ("green", "同时开始"), ("amber", "exposure 后才进入 Decision")))}
        <p class="current-boundary-note" data-testid="mechanism-boundary-note"><strong>读法边界</strong>：1,000、3,000、3 条、30 batches × Top20 是方法合同；实际 exposure、action 和 Provider 状态只在“本次运行”模式中读取 persisted evidence。</p>
      </section>

      <section id="sample" class="current-section current-scene current-sample-scene" data-section-anchor="sample" data-testid="mechanism-sample-section" tabindex="-1">
        <div class="current-scene-heading">
          <div>
            <span class="current-kicker">SAMPLE / 样本</span>
            <h2>Full-Pool Influence Seed Union 先确定研究起点</h2>
          </div>
          <p>研究样本由 seed、network cohort 和 ordinary 三种角色组成。它用于观察网络信号如何有机会进入后续排序，不是总体代表性随机样本。</p>
        </div>
        <figure class="current-visual current-visual-sample" data-testid="mechanism-sample-visual">
          <img data-testid="multi-message-sample-illustration" src="{sample_asset}" width="1024" height="576" alt="完整合格用户池经过 Full-Pool Influence Seed Union、network cohort 和 ordinary 补足形成研究样本的机制示意图">
          {_hotspot("sample-seed", "mechanism-sample-hotspot-seed", "Full-Pool Influence Seed Union", "影响力种子研究起点")}
          {_hotspot("sample-network", "mechanism-sample-hotspot-network", "network cohort", "seed 的历史直接邻居角色")}
          {_hotspot("sample-ordinary", "mechanism-sample-hotspot-ordinary", "ordinary sample", "补足研究样本的普通角色")}
          {_hotspot("sample-labels", "mechanism-sample-hotspot-labels", "Synthetic Experiment Labels", "Class 与 value weights 的实验标签边界")}
          <figcaption>pool → seed union → network cohort → ordinary sample。每个角色说明样本构造位置，不生成用户结果。</figcaption>
        </figure>
        {_legend((("blue", "Full-Pool Influence Seed Union"), ("green", "network cohort"), ("navy", "ordinary sample"), ("amber", "Synthetic Experiment Labels")))}
        <div class="current-sample-notes">
          <article class="current-open-note" data-testid="mechanism-sample-limitation"><strong>Sample limitation</strong><p>Seed-first 设计让研究样本保留与历史网络相连的用户，但不应解读为总体代表性随机抽样。</p></article>
          <article class="current-open-note" data-testid="mechanism-synthetic-labels"><strong>Synthetic Experiment Labels</strong><p>Class 与 value weights 用于实验构造、审计和分组解释；它们不是自然人口学事实，也不形成 Class 硬匹配 routing。</p></article>
        </div>
      </section>

      <section id="exposure-ranking" class="current-section current-scene current-ranking-scene" data-section-anchor="exposure-ranking" data-testid="mechanism-exposure-ranking-section" tabindex="-1">
        <div class="current-scene-heading">
          <div>
            <span class="current-kicker">EXPOSURE / 曝光排序</span>
            <h2>三条独立 queue，Batch 0 共享 seed，之后各自重排</h2>
          </div>
          <p>Batch 0 三条 message 使用同一个 Full-Pool Influence Seed Union；后续每条 queue 在自己的 eligible user-message pairs 上执行 per-message global reranking。</p>
        </div>
        <figure class="current-visual current-visual-ranking" data-testid="mechanism-exposure-ranking-visual">
          <img data-testid="multi-message-ranking-illustration" src="{ranking_asset}" width="1024" height="576" alt="三条独立候选 queue 共享 Batch 0 seeds，之后分别进行 per-message global reranking 并经过一次 exposure gate 的机制示意图">
          {_hotspot("ranking-seeds", "mechanism-exposure-hotspot-seeds", "Batch 0 shared seeds", "三条 queue 共用同一 seed union")}
          {_hotspot("ranking-queues", "mechanism-exposure-hotspot-queues", "three independent queues", "每条 message 维护自己的候选排序")}
          {_hotspot("ranking-pair-gate", "mechanism-exposure-hotspot-pair-gate", "same pair at most once", "同一 user × message 最多一次 exposure")}
          {_hotspot("ranking-overlap", "mechanism-exposure-hotspot-overlap", "cross-message overlap", "同一用户可以进入多条 message")}
          <figcaption>Batch 0 的 shared seeds 是共同起点；后续的排序与 capacity 选择在 message 维度独立发生。</figcaption>
        </figure>
        {_legend((("navy", "Batch 0 shared seed union"), ("blue", "per-message candidate queue"), ("green", "cross-message user overlap"), ("amber", "one exposure gate per pair")))}
        <div class="current-rule-columns">
          <article data-testid="mechanism-queue-contract"><strong>Queue contract</strong><p>三条 queue 独立维护候选；同一用户可出现在一条或多条 message queue。</p></article>
          <article data-testid="mechanism-exposure-contract"><strong>Exposure contract</strong><p>同一 <code>user × message</code> pair 最多 exposure 一次；未曝光 pair 不进入 Decision。</p></article>
          <article data-testid="mechanism-reranking-contract"><strong>Reranking contract</strong><p>Batch 1 起每条 message 都按自己的全局候选重新排序，每条 30 batches × Top20。</p></article>
        </div>
        <div class="current-signal-boundary" data-testid="mechanism-signal-boundary">
          <article><strong>Recommendation Signal Inclusion</strong><p>表示 campaign feedback 被允许作为下一批 ranking signal；这是公式和流程的纳入边界。</p></article>
          <article><strong>Observed Recommendation Signal Effect</strong><p>只有“本次运行”的 persisted paired diagnostics 才能描述是否出现排序变化；机制模式不预设变化。</p></article>
          <p>0.50 / 0.30 / 0.20 是本研究的预声明配置，不是抖音参数、训练结果或真实因果效果。</p>
        </div>
      </section>

      <section id="llm-decision" class="current-section current-scene current-decision-scene" data-section-anchor="llm-decision" data-testid="mechanism-llm-decision-section" tabindex="-1">
        <div class="current-scene-heading">
          <div>
            <span class="current-kicker">FIT + DECISION / 适配与决策</span>
            <h2>Message-User Fit 使用六维 cosine，LLM 只处理已曝光 pair</h2>
          </div>
          <p>Platform Environment 负责 candidate、ranking 和 exposure；Decision Adapter 在 exposure 之后处理当前 user × message。两者的职责和证据边界不混合。</p>
        </div>
        <div class="current-fit-explainer" data-testid="mechanism-message-user-fit">
          <div>
            <h3>Message-User Fit</h3>
            <p>当前 message 的六维 0/1 value vector 与用户 signed value weights 做 cosine similarity。六维顺序固定为：</p>
            <div class="current-dimension-list" aria-label="六维价值向量"><span>认知</span><span>环境</span><span>功能</span><span>健康</span><span>情感</span><span>社会</span></div>
          </div>
          <div class="current-formula-stack">
            <code data-testid="mechanism-fit-cosine">raw_message_user_fit = cosine(message value vector, user signed value weights)</code>
            <code data-testid="mechanism-fit-normalization">normalized_message_user_fit = (raw + 1) / 2：[-1,1] → [0,1]</code>
            <code data-testid="mechanism-fit-score">score = 0.50 × base_network_relevance + 0.30 × campaign_engaged_neighbor_signal + 0.20 × normalized_message_user_fit</code>
            <code data-testid="mechanism-fit-historical-boundary">historical_tag_affinity = 0：不参与 Multi-Message fit</code>
          </div>
        </div>
        <figure class="current-visual current-visual-decision" data-testid="mechanism-decision-visual">
          <img data-testid="multi-message-decision-illustration" src="{decision_asset}" width="1024" height="576" alt="Platform Environment 先选择曝光，Decision Adapter 再处理当前 user-message pair，并生成 Primary 与 Shadow 配对决策的机制示意图">
          {_hotspot("platform", "mechanism-platform-hotspot", "Platform Environment", "选择 exposure，不调用 LLM 做排序")}
          {_hotspot("adapter", "mechanism-adapter-hotspot", "Decision Adapter", "只处理已曝光的当前 pair")}
          {_hotspot("primary", "mechanism-primary-hotspot", "Primary decision", "正常 runtime action path")}
          {_hotspot("shadow", "mechanism-shadow-hotspot", "Shadow decision", "只增加四项 synthetic fields")}
          {_hotspot("fit", "mechanism-fit-hotspot", "six-dimensional Message-User Fit", "ranking-only fit evidence")}
          <figcaption>Platform Environment → exposure → Decision Adapter。Ranking evidence、Class 和其他 messages 不进入当前 pair 的 Prompt。</figcaption>
        </figure>
        {_legend((("navy", "Platform Environment"), ("blue", "current user × message"), ("green", "Message-User Fit"), ("amber", "Primary / Shadow comparison")))}
        <div class="current-responsibility-grid">
          <article data-testid="mechanism-platform-responsibility"><strong>Platform Environment</strong><p>负责 candidate queue、per-message ranking、delivery capacity 和 exposure gate；不由 LLM 选择谁被曝光。</p></article>
          <article data-testid="mechanism-adapter-responsibility"><strong>Decision Adapter</strong><p>仅在 exposure 后处理当前 <code>user × message</code>，输出 <code>engage / probability / reason / confidence / action</code>。</p></article>
        </div>
        <div class="current-variant-grid" data-testid="mechanism-primary-shadow-boundary">
          <article><strong>Primary</strong><p>当前 pair 的正常 Decision path；可作为后续 Primary feedback 的唯一来源。</p></article>
          <article><strong>Shadow</strong><p>同一次 exposure 的 paired computation，只增加 <code>gender</code>、<code>age</code>、<code>education</code>、<code>monthly_income</code> 四项 Synthetic Experiment Labels。</p></article>
        </div>
        <p class="current-boundary-note"><strong>Shadow boundary</strong>：Shadow 仅作 report-only；它不是第二次 exposure，不改变 action、ranking、feedback 或 runtime state；Ranking evidence、Class 和其他 messages 也不进入 Prompt。</p>
      </section>

      <section id="network-feedback" class="current-section current-scene current-feedback-scene" data-section-anchor="network-feedback" data-testid="mechanism-network-feedback-section" tabindex="-1">
        <div class="current-scene-heading">
          <div>
            <span class="current-kicker">FEEDBACK / 网络反馈</span>
            <h2>成功 Primary 互动只影响下一批，当前批次保持冻结</h2>
          </div>
          <p>只有成功的 Primary <code>like / comment / share</code> 进入按 campaign user 去重的下一批排序信号。Shadow、ignore 和 provider failure 都在传播边界外。</p>
        </div>
        <figure class="current-visual current-visual-feedback" data-testid="mechanism-feedback-visual">
          <img data-testid="multi-message-feedback-illustration" src="{feedback_asset}" width="1024" height="576" alt="Primary like comment share 经过 campaign user 去重进入下一批排序，Shadow ignore provider failure 停止传播且同批 context 冻结的机制示意图">
          {_hotspot("feedback-primary", "mechanism-feedback-hotspot-primary", "Primary like / comment / share", "成功互动才产生 campaign signal")}
          {_hotspot("feedback-dedup", "mechanism-feedback-hotspot-dedup", "campaign user deduplication", "跨 message 成功用户只计一次")}
          {_hotspot("feedback-next", "mechanism-feedback-hotspot-next", "next-batch reranking", "只进入下一批 per-message ranking")}
          {_hotspot("feedback-stop", "mechanism-feedback-hotspot-stop", "Shadow / ignore / provider_failed", "不传播")}
          {_hotspot("feedback-freeze", "mechanism-feedback-hotspot-freeze", "same-batch context freeze", "同一批不回写当前 ranking")}
          <figcaption>成功 Primary → deduplicated campaign signal → next batch；不满足条件的 variant/action 在当前批次边界停止。</figcaption>
        </figure>
        {_legend((("blue", "successful Primary"), ("green", "campaign-deduplicated signal"), ("navy", "next-batch ranking"), ("amber", "no propagation")))}
        <div class="current-feedback-grid">
          <article data-testid="mechanism-feedback-positive"><strong>传播来源</strong><p>仅成功 Primary 的 <code>like</code>、<code>comment</code>、<code>share</code>；按 campaign user 去重。</p></article>
          <article data-testid="mechanism-feedback-stop"><strong>停止条件</strong><p><code>Shadow</code>、<code>ignore</code>、<code>provider_failed</code> 不形成传播信号。</p></article>
          <article data-testid="mechanism-feedback-freeze"><strong>时间边界</strong><p>同批 context 保持冻结；传播信号只在下一批 per-message global reranking 生效。</p></article>
        </div>
        <p class="current-boundary-note"><strong>研究边界</strong>：这是 simulation contract 中的 ranking feedback，不等于真实平台观察、用户心理或文案效果的因果判断。</p>
      </section>
"""


_CURRENT_CSS = """
.current-report-shell {
  --current-ink: #10213d;
  --current-muted: #5d6c80;
  --current-line: #d5dfeb;
  --current-paper: #ffffff;
  --current-page: #f5f8fb;
  --current-blue: #2166b1;
  --current-green: #21765d;
  --current-amber: #a56415;
  min-height: 100vh;
  min-width: 0;
  color: var(--current-ink);
  background: var(--current-page);
}
.current-report-shell *, .current-report-shell *::before, .current-report-shell *::after { box-sizing: border-box; }
.current-topbar {
  position: sticky;
  top: 0;
  z-index: 20;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 20px;
  min-height: 72px;
  padding: 10px 52px;
  border-bottom: 1px solid var(--current-line);
  background: #fbfcfe;
}
.current-brand { color: var(--current-ink); font-size: 17px; font-weight: 800; white-space: nowrap; }
.current-workflow-nav {
  display: flex;
  justify-content: center;
  gap: 32px;
  min-width: 0;
  overflow-x: auto;
  white-space: nowrap;
}
.current-workflow-nav a { position: relative; display: flex; align-items: center; min-height: 42px; padding: 8px 0; color: var(--current-muted); font-size: 13px; font-weight: 760; text-decoration: none; }
.current-workflow-nav a::after { content: ""; position: absolute; right: 0; bottom: 0; left: 0; height: 3px; background: transparent; }
.current-workflow-nav a:hover, .current-workflow-nav a:focus-visible, .current-workflow-nav a[aria-current="location"] { color: var(--current-blue); }
.current-workflow-nav a[aria-current="location"]::after { background: var(--current-blue); }
.current-workflow-nav a:focus-visible, .current-mode-switch button:focus-visible, .current-hotspot:focus-visible { outline: 2px solid var(--current-blue); outline-offset: 3px; }
.current-mode-switch { display: flex; gap: 4px; padding: 3px; border: 1px solid var(--current-line); border-radius: 6px; background: var(--current-paper); }
.current-mode-switch button { min-height: 38px; padding: 8px 13px; border: 0; border-radius: 4px; background: transparent; color: var(--current-muted); font: inherit; font-size: 13px; font-weight: 760; cursor: pointer; white-space: nowrap; }
.current-mode-switch button[aria-selected="true"] { background: var(--current-blue); color: #fff; }
.current-mode-panel[hidden] { display: none !important; }
.legacy-run-main { width: 100%; min-width: 0; background: #fff; }
.current-section { min-width: 0; padding: 76px 7vw; border-bottom: 1px solid var(--current-line); scroll-margin-top: 86px; }
.current-overview-scene { background: #f7fbff; }
.current-scene-heading { display: grid; grid-template-columns: minmax(0, 1.12fr) minmax(300px, .88fr); gap: 56px; align-items: end; max-width: 1260px; margin: 0 auto 34px; }
.current-kicker { display: inline-block; margin-bottom: 12px; color: var(--current-green); font-size: 11px; font-weight: 800; letter-spacing: .06em; }
.current-scene h1, .current-scene h2 { max-width: 820px; margin: 0 0 14px; color: var(--current-ink); line-height: 1.12; }
.current-scene h1 { font-size: 52px; }
.current-scene h2 { font-size: 38px; }
.current-scene h3 { margin: 0 0 8px; font-size: 17px; line-height: 1.25; }
.current-scene-heading > p { max-width: 520px; margin: 0; color: var(--current-muted); font-size: 16px; line-height: 1.7; }
.current-contract-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; max-width: 1260px; margin: 0 auto 18px; }
.current-contract-grid article { min-width: 0; min-height: 116px; padding: 18px; border-top: 3px solid var(--current-blue); border-bottom: 1px solid var(--current-line); background: var(--current-paper); }
.current-contract-grid article:nth-child(2) { border-top-color: var(--current-green); }
.current-contract-grid article:nth-child(3) { border-top-color: var(--current-amber); }
.current-contract-grid article:nth-child(4) { border-top-color: var(--current-ink); }
.current-contract-grid strong { display: block; margin-bottom: 8px; font-size: 28px; line-height: 1; }
.current-contract-grid span { color: var(--current-muted); font-size: 12px; line-height: 1.45; }
.current-queue-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; max-width: 1260px; margin: 0 auto 28px; }
.current-queue-card { min-width: 0; min-height: 138px; padding: 18px; border: 1px solid var(--current-line); border-radius: 6px; background: var(--current-paper); }
.current-queue-card-1 { border-left: 4px solid var(--current-blue); }
.current-queue-card-2 { border-left: 4px solid var(--current-green); }
.current-queue-card-3 { border-left: 4px solid var(--current-amber); }
.current-queue-index, .current-queue-audience { display: block; color: var(--current-blue); font-size: 11px; font-weight: 800; }
.current-queue-card-2 .current-queue-index { color: var(--current-green); }
.current-queue-card-3 .current-queue-index { color: var(--current-amber); }
.current-queue-card h3 { margin: 8px 0; overflow-wrap: anywhere; }
.current-queue-card p { margin: 0 0 12px; color: var(--current-muted); line-height: 1.55; }
.current-queue-audience { color: var(--current-muted); font-weight: 700; line-height: 1.45; }
.current-visual { position: relative; max-width: 1260px; min-width: 0; margin: 0 auto; overflow: visible; }
.current-visual > img { display: block; width: 100%; height: auto; aspect-ratio: 16 / 9; border: 1px solid var(--current-line); border-radius: 6px; background: #fff; object-fit: cover; }
.current-visual figcaption { max-width: 940px; margin: 12px 0 0; color: var(--current-muted); font-size: 12px; line-height: 1.55; }
.current-hotspot { position: absolute; z-index: 3; display: grid; gap: 3px; min-width: 138px; min-height: 52px; padding: 8px 11px; border: 2px solid rgba(33, 102, 177, .74); border-radius: 6px; background: rgba(255, 255, 255, .94); color: var(--current-ink); text-align: left; cursor: pointer; box-shadow: 0 7px 18px rgba(16, 33, 61, .12); }
.current-hotspot strong, .current-hotspot span { display: block; overflow-wrap: anywhere; }
.current-hotspot strong { font-size: 12px; line-height: 1.2; }
.current-hotspot span { color: var(--current-muted); font-size: 11px; line-height: 1.25; }
.current-hotspot:hover, .current-hotspot[aria-expanded="true"] { border-color: var(--current-blue); background: #fff; outline: 3px solid rgba(33, 102, 177, .2); outline-offset: 2px; transform: translateY(-2px); }
.current-hotspot:active { transform: translateY(1px); }
.current-visual-overview .current-hotspot-start { top: 7%; left: 3%; width: 19%; }
.current-visual-overview .current-hotspot-pair { right: 4%; bottom: 17%; width: 20%; }
.current-visual-sample .current-hotspot-seed { top: 25%; left: 27%; width: 22%; }
.current-visual-sample .current-hotspot-network { top: 29%; left: 49%; width: 18%; }
.current-visual-sample .current-hotspot-ordinary { right: 4%; bottom: 16%; width: 18%; }
.current-visual-sample .current-hotspot-labels { right: 3%; top: 6%; width: 20%; border-color: rgba(165, 100, 21, .78); }
.current-visual-ranking .current-hotspot-seeds { top: 10%; left: 4%; width: 19%; }
.current-visual-ranking .current-hotspot-queues { top: 7%; left: 35%; width: 19%; }
.current-visual-ranking .current-hotspot-pair-gate { right: 4%; top: 41%; width: 20%; }
.current-visual-ranking .current-hotspot-overlap { left: 33%; bottom: 7%; width: 20%; }
.current-visual-decision .current-hotspot-platform { top: 9%; left: 3%; width: 22%; }
.current-visual-decision .current-hotspot-adapter { top: 10%; left: 55%; width: 20%; }
.current-visual-decision .current-hotspot-primary { right: 3%; top: 22%; width: 19%; }
.current-visual-decision .current-hotspot-shadow { right: 3%; bottom: 11%; width: 20%; border-color: rgba(165, 100, 21, .78); }
.current-visual-decision .current-hotspot-fit { left: 39%; top: 42%; width: 20%; }
.current-visual-feedback .current-hotspot-primary { top: 7%; left: 3%; width: 25%; }
.current-visual-feedback .current-hotspot-dedup { left: 35%; top: 43%; width: 21%; }
.current-visual-feedback .current-hotspot-next { right: 3%; top: 10%; width: 20%; }
.current-visual-feedback .current-hotspot-stop { right: 3%; bottom: 9%; width: 22%; border-color: rgba(165, 100, 21, .78); }
.current-visual-feedback .current-hotspot-freeze { left: 39%; bottom: 8%; width: 21%; }
.current-legend { display: flex; flex-wrap: wrap; gap: 10px 20px; max-width: 1260px; margin: 14px auto 0; color: var(--current-muted); font-size: 12px; line-height: 1.4; }
.current-legend span { display: inline-flex; align-items: center; gap: 7px; }
.legend-swatch { display: inline-block; width: 10px; height: 10px; border-radius: 50%; background: var(--current-blue); }
.legend-swatch-navy { background: var(--current-ink); }
.legend-swatch-blue { background: var(--current-blue); }
.legend-swatch-green { background: var(--current-green); }
.legend-swatch-amber { background: var(--current-amber); }
.current-boundary-note { max-width: 1260px; margin: 26px auto 0; padding: 14px 16px; border-left: 4px solid var(--current-amber); background: #fff9f2; color: #6b4818; line-height: 1.6; }
.current-boundary-note strong { color: var(--current-ink); }
.current-sample-notes, .current-rule-columns, .current-responsibility-grid, .current-variant-grid, .current-feedback-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; max-width: 1260px; margin: 28px auto 0; }
.current-sample-notes { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.current-open-note, .current-rule-columns article, .current-responsibility-grid article, .current-variant-grid article, .current-feedback-grid article { min-width: 0; padding: 18px; border-top: 2px solid var(--current-line); background: rgba(255, 255, 255, .72); }
.current-open-note strong, .current-rule-columns strong, .current-responsibility-grid strong, .current-variant-grid strong, .current-feedback-grid strong { display: block; margin-bottom: 8px; color: var(--current-ink); }
.current-open-note p, .current-rule-columns p, .current-responsibility-grid p, .current-variant-grid p, .current-feedback-grid p { margin: 0; color: var(--current-muted); line-height: 1.6; }
.current-open-note:nth-child(2) { border-top-color: var(--current-amber); }
.current-rule-columns article:nth-child(1), .current-responsibility-grid article:nth-child(1), .current-feedback-grid article:nth-child(1) { border-top-color: var(--current-blue); }
.current-rule-columns article:nth-child(2), .current-responsibility-grid article:nth-child(2), .current-feedback-grid article:nth-child(2) { border-top-color: var(--current-green); }
.current-rule-columns article:nth-child(3), .current-feedback-grid article:nth-child(3) { border-top-color: var(--current-amber); }
.current-signal-boundary { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; max-width: 1260px; margin: 28px auto 0; padding: 18px; border: 1px solid var(--current-line); background: #eef5fc; }
.current-signal-boundary article { min-width: 0; padding-right: 18px; border-right: 1px solid var(--current-line); }
.current-signal-boundary article:nth-child(2) { border-right: 0; }
.current-signal-boundary strong { display: block; margin-bottom: 7px; color: var(--current-blue); }
.current-signal-boundary article:nth-child(2) strong { color: var(--current-green); }
.current-signal-boundary p { margin: 0; color: var(--current-muted); line-height: 1.55; }
.current-signal-boundary > p { grid-column: 1 / -1; margin: 4px 0 0; padding-top: 12px; border-top: 1px solid var(--current-line); color: #6b4818; font-size: 12px; }
.current-sample-scene { background: #fff; }
.current-ranking-scene { background: #f7f9fc; }
.current-decision-scene { background: #fff; }
.current-feedback-scene { background: #f7fbf8; }
.current-fit-explainer { display: grid; grid-template-columns: minmax(260px, .7fr) minmax(0, 1.3fr); gap: 28px; max-width: 1260px; margin: 0 auto 28px; padding: 22px; border: 1px solid var(--current-line); background: #fff; }
.current-fit-explainer p { margin: 0; color: var(--current-muted); line-height: 1.6; }
.current-dimension-list { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 14px; }
.current-dimension-list span { padding: 7px 10px; border: 1px solid #cfe2d7; border-radius: 4px; background: #edf7f2; color: var(--current-green); font-size: 12px; font-weight: 750; }
.current-formula-stack { display: grid; gap: 9px; min-width: 0; }
.current-formula-stack code { display: block; min-width: 0; padding: 10px 12px; border-left: 3px solid var(--current-blue); background: #f4f7fb; color: var(--current-ink); font: 12px/1.55 ui-monospace, SFMono-Regular, Menlo, monospace; overflow-wrap: anywhere; }
.current-formula-stack code:nth-child(3) { border-left-color: var(--current-green); }
.current-formula-stack code:nth-child(4) { border-left-color: var(--current-amber); }
.current-variant-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.current-variant-grid article:first-child { border-top-color: var(--current-blue); }
.current-variant-grid article:last-child { border-top-color: var(--current-amber); }
.current-feedback-grid { margin-top: 28px; }
.current-feedback-grid article { background: rgba(255, 255, 255, .8); }
.current-report-shell code { overflow-wrap: anywhere; }
.current-report-shell .drawer { z-index: 40; }
@media (max-width: 1000px) {
  .current-topbar { grid-template-columns: 1fr auto; padding-right: 28px; padding-left: 28px; }
  .current-workflow-nav { grid-column: 1 / -1; grid-row: 2; justify-content: flex-start; order: 3; }
  .current-scene-heading { grid-template-columns: 1fr; gap: 10px; }
  .current-contract-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .current-queue-grid, .current-rule-columns, .current-responsibility-grid, .current-feedback-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .current-signal-boundary { grid-template-columns: 1fr; }
  .current-signal-boundary article { padding-right: 0; padding-bottom: 14px; border-right: 0; border-bottom: 1px solid var(--current-line); }
  .current-signal-boundary article:nth-child(2) { padding-bottom: 0; border-bottom: 0; }
}
@media (max-width: 600px) {
  .current-topbar { grid-template-columns: 1fr; gap: 8px; padding: 10px 18px; }
  .current-mode-switch { width: 100%; }
  .current-mode-switch button { flex: 1; }
  .current-workflow-nav { gap: 20px; }
  .current-section { padding: 42px 18px; }
  .current-scene h1 { font-size: 32px; }
  .current-scene h2 { font-size: 29px; }
  .current-scene-heading > p { font-size: 15px; }
  .current-contract-grid, .current-queue-grid, .current-sample-notes, .current-rule-columns, .current-responsibility-grid, .current-variant-grid, .current-feedback-grid, .current-fit-explainer { grid-template-columns: 1fr; }
  .current-contract-grid article { min-height: 100px; }
  .current-fit-explainer { padding: 16px; }
  .current-visual { display: block; }
  .current-visual > img { aspect-ratio: 16 / 9; }
  .current-hotspot { position: static; width: auto !important; min-width: 0; max-width: 100%; display: inline-grid; margin: 9px 8px 0 0; vertical-align: top; box-shadow: none; }
  .current-visual figcaption { margin-top: 14px; }
  .current-legend { gap: 8px 15px; }
  .current-boundary-note { font-size: 13px; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: .01ms !important; animation-iteration-count: 1 !important; scroll-behavior: auto !important; transition-duration: .01ms !important; }
}
"""


def render_current_report(payload: Any, legacy_renderer: Callable[[Any], str]) -> str:
    legacy_style, legacy_main, legacy_extras = _legacy_run_fragments(payload, legacy_renderer)
    title = _escaped(payload.title, quote=True)
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
      {legacy_main}
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
    {legacy_extras}
    <script>
    (() => {{
      const drawer = document.getElementById('trace-drawer');
      const drawerBody = document.getElementById('trace-drawer-body');
      const drawerTitle = document.getElementById('trace-drawer-title');
      const closeButton = document.getElementById('trace-drawer-close');
      const mechanismButtons = [...document.querySelectorAll('[data-mechanism-key]')];
      let returnFocusTarget = null;
      let bodyOverflowBeforeDrawer = '';

      const details = {{
        'overview-start': {{ title: '同时开始边界', definition: '三条 authoritative message 在同一个发布边界进入各自的 candidate queue，不按 message 顺序获得先发优势。', provenance: 'Synthetic Experiment Contract（合成实验合同）', usage: 'Campaign setup（活动初始化） / Ranking（排序）', limitation: '这里解释稳定流程，不展示任意一次 run 的实际 exposure 或 action。' }},
        'overview-pair': {{ title: 'user × message pair', definition: '一个 user × message pair 只有在 Platform Environment 选择 exposure 后才会产生 Primary 与 Shadow 的配对 Decision opportunity。', provenance: 'Runtime Contract（运行时合同）', usage: 'Exposure（曝光） / Decision（决策）', limitation: '没有 exposure 的 pair 不调用 Decision Adapter。' }},
        'sample-seed': {{ title: 'Full-Pool Influence Seed Union', definition: '从完整合格用户池形成研究起点的 seed union；它让后续队列有机会观察与历史网络相连的用户。', provenance: 'Derived Proxy Metric（派生代理指标）', usage: 'Sampling（抽样） / Batch 0 setup（Batch 0 初始化）', limitation: 'Seed-first 样本不是总体代表性随机样本，也不是本次 run 的 outcome。' }},
        'sample-network': {{ title: 'network cohort', definition: 'network cohort 是 seed union 的历史直接邻居角色，用于保留网络传播识别机会。', provenance: 'Historical Behavioral Evidence（历史行为证据）', usage: 'Sampling（抽样） / Ranking（排序）', limitation: '连接来自评论、回复或 mention 派生关系，不等于好友关系或真实可见同伴行为。' }},
        'sample-ordinary': {{ title: 'ordinary sample', definition: 'ordinary 角色在 seed 与 network cohort 进入配额后补足研究样本，保持完整 sample 的研究范围。', provenance: 'Sample Construction（样本构造）', usage: 'Sampling（抽样）', limitation: 'ordinary 不表示合成用户，也不保证总体代表性。' }},
        'sample-labels': {{ title: 'Synthetic Experiment Labels', definition: 'Class 与 value weights 是用于实验构造、审计和分组解释的合成实验标签，不是自然人口学事实。', provenance: 'Synthetic Experiment Label（合成实验标签）', usage: 'Fit（适配） / Report Only（仅报告展示）', limitation: 'Class 名称不作为硬匹配 routing 条件。' }},
        'ranking-seeds': {{ title: 'Batch 0 shared seeds', definition: '三条 queue 在 Batch 0 共用同一个 Full-Pool Influence Seed Union；这是共同起点，不是三条结果的比较。', provenance: 'Synthetic Experiment Contract（合成实验合同）', usage: 'Batch 0 Ranking（Batch 0 排序）', limitation: '共同 seed 起点不预设任意 message 的 outcome。' }},
        'ranking-queues': {{ title: 'three independent queues', definition: '每条 message 维护自己的 personalized candidate queue，并在后续 batch 进行自己的全局重排。', provenance: 'Per-Message Personalized Top20 Contract', usage: 'Ranking（排序） / Exposure（曝光）', limitation: 'message queue 独立不代表用户受众互斥。' }},
        'ranking-pair-gate': {{ title: 'same pair at most once', definition: '同一个 user × message pair 一旦获得 exposure，就从该 message 的 eligible queue 移除；其他 message 仍可保留该用户。', provenance: 'Runtime Contract（运行时合同）', usage: 'Eligibility（资格） / Exposure（曝光）', limitation: '这是 pair-level 规则，不是 user-level 全局屏蔽。' }},
        'ranking-overlap': {{ title: 'cross-message overlap', definition: '同一用户可以进入多条 message queue；每个 message 都独立计算该 user × message 的 fit 与 ranking evidence。', provenance: 'Per-Message Queue Contract', usage: 'Ranking（排序） / Campaign Coverage（活动覆盖）', limitation: '跨 message overlap 只说明受众可重叠，不生成 message 比较结论。' }},
        'platform': {{ title: 'Platform Environment', definition: 'Platform Environment 负责候选、per-message ranking、delivery capacity 和 exposure gate；LLM 不参与曝光调度。', provenance: 'Platform Environment Contract', usage: 'Ranking（排序） / Exposure（曝光）', limitation: '平台排序证据不等同已曝光用户的 action。' }},
        'adapter': {{ title: 'Decision Adapter', definition: 'Decision Adapter 只在 exposure 之后处理当前 user × message，并返回 engage、probability、reason、confidence、action。', provenance: 'Decision Adapter Contract', usage: 'LLM Decision（LLM 决策）', limitation: 'Ranking evidence、Class 和其他 messages 不进入当前 pair 的 Prompt。' }},
        'primary': {{ title: 'Primary decision', definition: 'Primary 是当前 user × message exposure 的正常 Decision path，只有成功的 Primary positive action 可以产生 campaign feedback。', provenance: 'Runtime Simulation Contract（仿真运行合同）', usage: 'Decision（决策） / Feedback（反馈）', limitation: '机制模式不展示本次 run 的 action 计数或分布。' }},
        'shadow': {{ title: 'Shadow decision', definition: 'Shadow 与同一 exposure 配对，只增加 gender、age、education、monthly_income 四项 Synthetic Experiment Labels。', provenance: 'Synthetic Experiment Label（合成实验标签）', usage: 'Paired Sensitivity（配对敏感性） / Report Only（仅报告展示）', limitation: 'Shadow 不是第二次 exposure，不改变 action、ranking、feedback 或 runtime state。' }},
        'fit': {{ title: 'six-dimensional Message-User Fit', definition: 'Message-User Fit 使用六维 message value vector 与 user signed value weights 的 cosine similarity；Class 不做硬匹配。', provenance: 'Derived Proxy Metric（派生代理指标）', usage: 'Ranking（排序） / Report Only（仅报告展示）', limitation: 'raw cosine 从 [-1,1] 归一化到 [0,1]；historical_tag_affinity 固定为 0，不作为 Multi-Message fit。' }},
        'feedback-primary': {{ title: 'Primary like / comment / share', definition: '只有成功的 Primary like、comment、share 才能形成 campaign feedback signal。', provenance: 'Runtime Simulation Contract（仿真运行合同）', usage: 'Feedback（反馈） / Next-batch Ranking（下一批排序）', limitation: 'signal inclusion 不等于本次 run 已观察到排序变化。' }},
        'feedback-dedup': {{ title: 'campaign user deduplication', definition: '跨三条 message 的成功 Primary 用户按 campaign user 去重后形成下一批的统一反馈集合。', provenance: 'Campaign Feedback Contract', usage: 'Feedback（反馈） / Ranking（排序）', limitation: '同一用户成功互动多条 message 也只计一次 campaign signal。' }},
        'feedback-next': {{ title: 'next-batch reranking', definition: '去重后的 Primary feedback 只在下一批进入三条 message 各自的 per-message global reranking。', provenance: 'Runtime Contract（运行时合同）', usage: 'Next-batch Ranking（下一批排序）', limitation: '这是推荐信号进入路径，不是已观测因果效果。' }},
        'feedback-stop': {{ title: 'Shadow / ignore / provider_failed', definition: 'Shadow、ignore 和 provider_failed 都不形成 campaign propagation signal。', provenance: 'Runtime Contract（运行时合同）', usage: 'Feedback boundary（反馈边界）', limitation: '它们不会回写同批 ranking，也不会改变当前 message 的其他 pair。' }},
        'feedback-freeze': {{ title: 'same-batch context freeze', definition: '当前 batch 的 candidate 与 context 在该 batch 内保持冻结；feedback 不回写当前 batch 的已选结果。', provenance: 'Batch Scheduling Contract', usage: 'Batch Isolation（批次隔离）', limitation: '只有下一批才会重新计算相对排序。' }},
      }};

      function createElement(tag, className, text) {{
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
      }}

      function closeMechanismDrawer(restoreFocus = true) {{
        if (!drawer || drawer.dataset.selectionKind !== 'mechanism') return;
        const target = returnFocusTarget;
        returnFocusTarget = null;
        drawer.hidden = true;
        drawer.removeAttribute('data-selection-kind');
        drawer.removeAttribute('aria-modal');
        document.body.style.overflow = bodyOverflowBeforeDrawer;
        bodyOverflowBeforeDrawer = '';
        mechanismButtons.forEach((button) => button.setAttribute('aria-expanded', 'false'));
        if (restoreFocus && target?.isConnected) target.focus({{ preventScroll: true }});
      }}

      function renderMechanismDetail(key, trigger) {{
        const detail = details[key];
        if (!detail || !drawer || !drawerBody || !drawerTitle) return;
        returnFocusTarget = trigger;
        drawerTitle.textContent = detail.title;
        drawerBody.replaceChildren();
        const card = createElement('section', 'drawer-card');
        card.append(createElement('h3', '', detail.title), createElement('p', 'muted', detail.definition));
        const facts = document.createElement('dl');
        [
          ['Field Provenance（字段来源）', detail.provenance],
          ['Field Usage Stage（字段使用阶段）', detail.usage],
          ['研究限制', detail.limitation],
        ].forEach(([label, value]) => {{
          facts.append(createElement('dt', '', label), createElement('dd', '', value));
        }});
        card.appendChild(facts);
        drawerBody.appendChild(card);
        drawer.dataset.selectionKind = 'mechanism';
        drawer.setAttribute('aria-modal', 'true');
        bodyOverflowBeforeDrawer = document.body.style.overflow;
        document.body.style.overflow = 'hidden';
        drawer.hidden = false;
        mechanismButtons.forEach((button) => button.setAttribute('aria-expanded', String(button === trigger)));
        closeButton?.focus({{ preventScroll: true }});
      }}

      mechanismButtons.forEach((button) => button.addEventListener('click', () => renderMechanismDetail(button.dataset.mechanismKey, button)));
      closeButton?.addEventListener('click', () => closeMechanismDrawer(true));
      document.addEventListener('keydown', (event) => {{
        if (event.key === 'Escape' && drawer?.dataset.selectionKind === 'mechanism') {{
          event.preventDefault();
          event.stopImmediatePropagation();
          closeMechanismDrawer(true);
        }}
      }}, true);
      document.querySelectorAll('[data-report-mode-target]').forEach((button) => button.addEventListener('click', () => closeMechanismDrawer(false)));
      window.addEventListener('hashchange', () => closeMechanismDrawer(false));
    }})();
    </script>
  </main>
</body>
</html>"""
    return template
