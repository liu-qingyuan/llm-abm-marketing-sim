from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_abm_sim.prompt_contracts import CONCURRENT_ROBUSTNESS_PROMPT_TOKENS
from llm_abm_sim.providers.openai_compatible import OpenAICompatibleDecisionAdapter
from llm_abm_sim.providers.pi_subscription import PiSubscriptionProviderClient, PiSubscriptionProviderError
from llm_abm_sim.schemas import PeerContext, PostContent, ProviderLLMConfig, UserProfile


def _fake_worker(path: Path) -> Path:
    path.write_text(
        """
let buffer = "";
const models = ["gpt-5.4-mini", "gpt-5.4", "gpt-5.5", "gpt-5.6-sol"];
function emit(value) { process.stdout.write(JSON.stringify(value) + "\\n"); }
process.stdin.setEncoding("utf8");
process.stdin.on("data", chunk => {
  buffer += chunk;
  while (true) {
    const index = buffer.indexOf("\\n");
    if (index < 0) break;
    const line = buffer.slice(0, index);
    buffer = buffer.slice(index + 1);
    if (!line) continue;
    const command = JSON.parse(line);
    if (command.type === "status") {
      emit({
        id: command.id,
        ok: true,
        provider: "openai-codex",
        auth_type: "oauth",
        models,
        requested_model_aliases: {
          "gpt-5.4-mini": "gpt-5.4-mini",
          "gpt-5.4-2026-03-05": "gpt-5.4",
          "gpt-5.5-2026-04-23": "gpt-5.5",
          "gpt-5.6-sol": "gpt-5.6-sol"
        }
      });
    } else if (command.type === "request") {
      emit({
        id: command.id,
        ok: true,
        provider: "openai-codex",
        requested_model: "gpt-5.4-mini",
        upstream_model: "gpt-5.4-mini",
        observed_model: "gpt-5.4-mini",
        decision_text: "{\\\"engage\\\":true,\\\"probability\\\":0.8,\\\"reason\\\":\\\"fit\\\",\\\"confidence\\\":0.9,\\\"action\\\":\\\"like\\\"}",
        usage: {
          input_tokens: 20,
          output_tokens: 10,
          total_tokens: 30,
          cached_input_tokens: 0,
          subscription_nominal_cost_usd: 0
        },
        output_token_ceiling_enforcement: "application_fail_closed"
      });
    } else if (command.type === "close") {
      emit({id: command.id, ok: true, closing: true});
      process.exit(0);
    }
  }
});
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return path


def _profile() -> UserProfile:
    return UserProfile.model_validate(
        {
            "user_id": "u1",
            "activity_score": 0.5,
            "global_influence_score": 0.9,
            "local_influence_score": 0.4,
            "concurrent_environmental_consciousness_coef": 1.0,
            "concurrent_epistemic_value_weight": 0.1,
            "concurrent_environmental_value_weight": 0.8,
            "concurrent_functional_value_weight": 0.4,
            "concurrent_health_value_weight": 0.7,
            "concurrent_emotional_value_weight": 0.2,
            "concurrent_social_value_weight": 0.3,
            "concurrent_hotel_class": "midscale",
            "concurrent_travel_purpose": "leisure",
        }
    )


def test_subscription_client_requires_explicit_live_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_ABM_RUN_LIVE_LLM", raising=False)
    with pytest.raises(PiSubscriptionProviderError, match="explicit"):
        PiSubscriptionProviderClient(worker_path=_fake_worker(tmp_path / "worker.mjs"))


def test_subscription_client_is_external_accounted_and_secret_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_ABM_RUN_LIVE_LLM", "1")
    client = PiSubscriptionProviderClient(worker_path=_fake_worker(tmp_path / "worker.mjs"))
    adapter = OpenAICompatibleDecisionAdapter(
        ProviderLLMConfig(
            enabled=True,
            provider="openai_compatible",
            model="gpt-5.4-mini",
            require_live_env=True,
            prompt_version=CONCURRENT_ROBUSTNESS_PROMPT_TOKENS[0],
            reasoning_effort="low",
            max_output_tokens=256,
        ),
        client=client,
    )
    try:
        decision = adapter.decide(
            post=PostContent(post_id="message-1", text="绿色酒店营销内容"),
            profile=_profile(),
            peer_context=PeerContext(),
        )
    finally:
        client.close()

    assert decision.action == "like"
    assert adapter.external_request_invocations == 1
    assert adapter.provider_accounting.observed_model_counts == {"gpt-5.4-mini": 1}
    assert adapter.safe_metadata["external_transport"] == {
        "provider_transport": "openai-codex",
        "adapter_identity": "openai-codex-subscription-client-v1",
        "authentication": "local_oauth_subscription",
        "requested_model_aliases": {
            "gpt-5.4-mini": "gpt-5.4-mini",
            "gpt-5.4-2026-03-05": "gpt-5.4",
            "gpt-5.5-2026-04-23": "gpt-5.5",
            "gpt-5.6-sol": "gpt-5.6-sol",
        },
        "output_token_ceiling_enforcement": "application_fail_closed",
    }
    serialized = json.dumps(adapter.safe_metadata, ensure_ascii=False).lower()
    assert all(token not in serialized for token in ("bearer ", "access_token", "refresh_token", "sk-"))
