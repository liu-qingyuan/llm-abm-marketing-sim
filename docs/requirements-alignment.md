# Requirements Alignment with Obsidian Design Notes

This document maps the current implementation to the Obsidian knowledge-base framing for the LLM-ABM marketing diffusion simulator.

## Six-layer alignment

| Obsidian layer | Current implementation | Status |
|---|---|---|
| 1. Input scenario | `SimulationInput`, YAML configs, post content, seed users, platform context, inline or dataset-backed profiles/edges, static input builder | Implemented for local prototype |
| 2. Platform environment | `PlatformEnvironment` computes seed/feed/neighbor exposures using base probability, peer boost, hot-topic boost, share boost, visible traces, and NetworkX graph neighbors | Implemented, simplified from real platform ranking |
| 3. User Agents | `SocialUserAgent` stores profile, exposure state, absorbing engagement state, and decision history | Implemented |
| 4. LLM decision structure | `LLMDecisionAdapter` boundary, rule-based baseline, optional OpenAI-compatible provider adapter, `DecisionInput` cache key, `EngageDecision` schema | Implemented; real provider is opt-in |
| 5. Multi-round propagation/feedback | `SimulationModel.step()` loops over horizon, applies actions to environment, records exposure/decision/action events and time-series step records | Implemented |
| 6. Outputs/metrics | `MetricsCollector`, JSON/CSV artifacts, bilingual report, graph trace, decision inspector, dataset validation, provider evidence | Implemented for 90% local prototype |

## Decision input/output inspectability

Each `DecisionEvent` now carries a `DecisionTraceSummary`:

- post summary: `post_id`, text, topic tags, media summary;
- profile fields: public user profile attributes;
- peer context: engaged/exposed neighbors, visible likes/comments/shares, engagement ratio;
- platform context: time label, hot topics, mood, feed/trace weights;
- time step and prompt/schema version;
- output `EngageDecision`: engage, probability, reason, confidence, action, decision source, allowlisted provider metadata.

The report displays this packet in the node detail panel. `graph_trace.json` and `report_payload.json` use the same safe serialization path.

## Bilingual product contract

The generated report embeds `en-US` and `zh-CN` dictionaries from `report_i18n.py`. Key parity is tested, so missing translations fail tests. The visible report language selector switches representative product sections, including summaries, metric labels, graph labels, provider evidence copy, and Agent I/O labels.

## Provider and secret-safety alignment

Default mode remains deterministic and offline. Provider-backed decisions require explicit `provider_llm.enabled` and live provider runs require `LLM_ABM_RUN_LIVE_LLM=1` unless a test injects a mocked adapter.

Provider evidence is intentionally limited to an allowlist. The project does not serialize raw provider prompts, raw responses, headers, cookies, bearer/API tokens, auth files, or local credential paths. This preserves the Obsidian intent that the LLM is a controlled decision function, not the simulation orchestrator or a secret-bearing runtime log.

## Intentional simplifications and future work

Implemented now:

- custom lightweight ABM runtime;
- NetworkX graph layer;
- Pydantic schemas;
- deterministic baseline + optional provider adapter;
- event-sourced artifacts and bilingual static report;
- static config builder.

Partial or future work:

- platform ranking is a transparent weighted approximation, not a production recommender;
- provider cache persistence is in-memory only;
- input builder is static and copy/download oriented, not a server that runs simulations;
- no LangChain/LangGraph/general autonomous Agent framework is introduced;
- advanced charting, dashboards, experiment database, and hosted collaboration are deferred until schemas stabilize.
