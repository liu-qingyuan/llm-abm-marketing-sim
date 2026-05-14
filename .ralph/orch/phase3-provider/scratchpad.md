
## 2026-05-14 Phase 3 provider adapter plan

Current baseline: Phase 1 dataset ingestion commit c45a9131745480d85340d143202917f37c132000. Task is Phase 3 only: optional provider-backed LLM adapter behind LLMDecisionAdapter, explicit live gate, fail-closed behavior, mocked tests, docs and handoff evidence.

Prioritized tasks:
- [ ] Map current decision/config/runner/output boundaries and Phase 3 gates.
- [ ] Add prompt construction and optional OpenAI-compatible adapter with schema validation and redaction-safe metadata.
- [ ] Add config/env gating plus fail_closed_action enum values raise/no_engage/skip_run.
- [ ] Add mocked provider tests, integration runner provider path, and real manual live_llm smoke gate that skips unless explicit runtime is ready.
- [ ] Update provider/development docs and phase handoff artifact with command evidence.
- [ ] Run required acceptance commands; fix failures without expanding into Phase 4+.

Implementation choices: keep deterministic RuleBasedDecisionAdapter default; provider activation should require config opt-in and explicit env for actual live use. Codex metadata remains allowlisted provider_name/base_url/wire_api/model/requires_openai_auth/auth_available only. Do not read or serialize auth.json contents.

## 2026-05-14 Phase 3 completion notes

- [x] Map current decision/config/runner/output boundaries and Phase 3 gates.
- [x] Add prompt construction and optional OpenAI-compatible adapter with schema validation, retry, cache compatibility, and redaction-safe metadata.
- [x] Add config/env gating plus fail_closed_action enum values raise/no_engage/skip_run.
- [x] Add mocked provider tests, integration runner provider path, and real manual live_llm smoke gate that skips unless explicit runtime is ready.
- [x] Update provider/development docs and phase handoff artifact with command evidence.
- [x] Run required acceptance commands and record logs under .omx/phase-handoffs/logs/phase3-*.log.

Completion audit passed: default remains offline and deterministic, Phase 1 toy dataset smoke preserved, live gate manual-only and skipped in this run due to unavailable concrete provider credentials, no Phase 4+ scope, no worktree/workspace residue.
