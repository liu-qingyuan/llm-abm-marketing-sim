from __future__ import annotations

import json
from html import escape
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from .report_i18n import REPORT_I18N
from .safe_serialization import safe_data, safe_json
from .schemas import (
    FailClosedAction,
    PlatformContext,
    PostContent,
    ProviderLLMConfig,
    ReportConfig,
    SimulationConfig,
    SimulationInput,
    UserProfile,
)


def default_builder_input() -> SimulationInput:
    """Typed default config used by the static input builder and round-trip tests."""

    return SimulationInput(
        run_id="builder-sample-run",
        random_seed=20260515,
        simulation=SimulationConfig(
            horizon=5,
            seed_user_ids=["seed_creator"],
            base_exposure_probability=0.45,
            peer_exposure_boost=0.16,
            hot_topic_exposure_boost=0.10,
            share_exposure_boost=0.05,
            time_step_label="day",
            observation_window="5 days after campaign launch",
        ),
        platform_context=PlatformContext(
            time_label="launch week",
            hot_topics=["skincare", "eco", "creator"],
            platform_mood="creator-led sustainability discussion",
            feed_ranking_weight=1.1,
            trace_visibility=0.85,
        ),
        post=PostContent(
            post_id="builder-post",
            text="Refillable skincare launch with creator bundles and lower-waste packaging.",
            media_summary="Short video with product texture, refill pod, and creator testimonial.",
            topic_tags=["skincare", "eco"],
        ),
        profiles=[
            UserProfile(
                user_id="seed_creator",
                interest_tags=["skincare", "eco", "creator"],
                brand_attitude=0.8,
                activity_score=0.9,
                like_tendency=0.8,
                comment_tendency=0.4,
                share_tendency=0.7,
            ),
            UserProfile(
                user_id="follower_a",
                interest_tags=["skincare", "beauty"],
                brand_attitude=0.35,
                activity_score=0.7,
                like_tendency=0.7,
                comment_tendency=0.2,
                share_tendency=0.25,
            ),
            UserProfile(
                user_id="skeptic_b",
                interest_tags=["gaming"],
                brand_attitude=-0.1,
                activity_score=0.35,
                like_tendency=0.25,
                comment_tendency=0.15,
                share_tendency=0.1,
            ),
        ],
        graph_edges=[("seed_creator", "follower_a"), ("follower_a", "skeptic_b")],
        report=ReportConfig(title="LLM-ABM Builder Demo Report", default_language="en-US"),
        provider_llm=ProviderLLMConfig(enabled=False, fail_closed_action=FailClosedAction.RAISE),
    )


def builder_config_yaml() -> str:
    payload = safe_data(default_builder_input())
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


def write_input_builder_html(path: str | Path) -> Path:
    path = Path(path)
    path.write_text(render_input_builder_html(), encoding="utf-8")
    return path


def render_input_builder_html() -> str:
    config_yaml = builder_config_yaml()
    i18n_json = safe_json(REPORT_I18N, indent=None)
    config_json = json.dumps(config_yaml, ensure_ascii=False)
    escaped_yaml = escape(config_yaml)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>LLM-ABM Input Builder</title>
  <style>
    :root {{ --bg:#f6f8fb; --card:#fff; --ink:#172033; --muted:#667085; --line:#d8e0eb; --accent:#2f6fed; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; font-family:Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background:var(--bg); color:var(--ink); }}
    main {{ max-width:1120px; margin:0 auto; padding:32px 20px 48px; }} section {{ margin-top:18px; padding:20px; border:1px solid var(--line); border-radius:18px; background:var(--card); }}
    label {{ display:block; font-weight:700; margin:12px 0 6px; }} input, textarea, select {{ width:100%; padding:10px; border:1px solid var(--line); border-radius:10px; font:inherit; }}
    textarea {{ min-height:280px; font-family:ui-monospace, SFMono-Regular, Menlo, monospace; }} .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(230px,1fr)); gap:14px; }}
    .subtle {{ color:var(--muted); }} button {{ border:0; border-radius:999px; background:var(--accent); color:white; padding:10px 16px; font-weight:700; cursor:pointer; }} .actions {{ display:flex; gap:10px; flex-wrap:wrap; margin-top:12px; }}
    code, pre {{ white-space:pre-wrap; overflow-wrap:anywhere; }} .help {{ padding:12px; border:1px dashed var(--line); border-radius:12px; background:#fbfcff; }}
  </style>
</head>
<body>
  <main data-testid="input-builder">
    <header>
      <h1 data-i18n="builder.title">LLM-ABM Input Builder</h1>
      <p class="subtle" data-i18n="builder.intro">Edit product-facing inputs, then copy or download YAML and run it with python -m llm_abm_sim.run.</p>
      <label for="builder-language" data-i18n="builder.language">Builder language</label>
      <select id="builder-language" data-testid="builder-language" aria-label="Builder language"><option value="en-US">English</option><option value="zh-CN">中文</option></select>
    </header>
    <section>
      <h2 data-i18n="builder.fieldHelp">Field help</h2>
      <div class="grid">
        <p class="help"><strong data-i18n="input.post">Post</strong><br>post.text, media_summary, topic_tags</p>
        <p class="help"><strong data-i18n="input.platform">Platform context</strong><br>hot_topics, platform_mood, feed_ranking_weight</p>
        <p class="help"><strong data-i18n="input.seedUsers">Seed users</strong><br>simulation.seed_user_ids</p>
        <p class="help"><strong data-i18n="input.decisionMode">Decision mode</strong><br><span data-i18n="builder.provider.help">Offline rule-based is default. Provider-backed runs require explicit config plus the live gate.</span></p>
        <p class="help"><strong data-i18n="input.dataset">Dataset</strong><br><span data-i18n="builder.dataset.help">Use inline profiles/edges for small demos or dataset paths for larger social graphs.</span></p>
      </div>
    </section>
    <section>
      <h2 data-i18n="builder.generatedConfig">Generated config</h2>
      <textarea data-testid="generated-config" id="generated-config" spellcheck="false">{escaped_yaml}</textarea>
      <div class="actions">
        <button type="button" id="copy-yaml" data-i18n="action.copyYaml">Copy YAML</button>
        <button type="button" id="download-yaml" data-i18n="builder.download">Download config</button>
      </div>
      <p class="subtle">Run: <code>python -m llm_abm_sim.run --config builder-config.yaml --output runs/builder-demo</code></p>
    </section>
  </main>
  <script id="builder-i18n" type="application/json">{i18n_json}</script>
  <script>
    const BUILDER_DEFAULT_CONFIG = {config_json};
    const dicts = JSON.parse(document.getElementById('builder-i18n').textContent);
    const language = document.getElementById('builder-language');
    const area = document.getElementById('generated-config');
    function t(key) {{ return (dicts[language.value] && dicts[language.value][key]) || dicts['en-US'][key] || key; }}
    function applyLanguage() {{ document.documentElement.lang = language.value; document.querySelectorAll('[data-i18n]').forEach((el) => {{ el.textContent = t(el.getAttribute('data-i18n')); }}); }}
    language.addEventListener('change', applyLanguage);
    document.getElementById('copy-yaml').addEventListener('click', async () => {{ await navigator.clipboard?.writeText(area.value); }});
    document.getElementById('download-yaml').addEventListener('click', () => {{ const blob = new Blob([area.value], {{type:'text/yaml'}}); const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'llm-abm-config.yaml'; a.click(); URL.revokeObjectURL(a.href); }});
    if (!area.value.trim()) area.value = BUILDER_DEFAULT_CONFIG;
    applyLanguage();
  </script>
</body>
</html>
"""
