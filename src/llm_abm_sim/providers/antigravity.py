from __future__ import annotations

import os
from typing import Any, Literal

from llm_abm_sim.provider_accounting import ProviderResponseEnvelope
from llm_abm_sim.provider_request_contract import ReasoningEffortValue
from llm_abm_sim.providers.openai_compatible import (
    ProviderConfigurationError,
    _OpenAISDKClient,
)

ANTIGRAVITY_GEMINI_MODEL_ROUTES = {
    # The real 3.1 ID bypasses Antigravity v4.6.6's canonical variant
    # resolver, which otherwise replaces the caller's bounded token controls.
    "gemini-3.1-pro": "gemini-pro-agent",
    "gemini-3.8-flash-high": "gemini-3.8-flash-high",
}
ANTIGRAVITY_GEMINI_MODELS = frozenset(ANTIGRAVITY_GEMINI_MODEL_ROUTES)
ANTIGRAVITY_GEMINI_THINKING_BUDGET = 128
ANTIGRAVITY_GEMINI_DECISION_TOKEN_CEILING = 256
ANTIGRAVITY_GEMINI_WIRE_OUTPUT_TOKEN_CEILING = 1024


class AntigravityGeminiProviderClient:
    """Chat-only OpenAI-compatible transport for the frozen Gemini conditions."""

    external_provider_client = True
    provider_transport = "antigravity_openai_compatible_gateway"
    wire_api = "chat_completions"
    thinking_budget = ANTIGRAVITY_GEMINI_THINKING_BUDGET
    reasoning_usage_mapping = "reasoning_included_in_completion_tokens"
    output_token_ceiling_scope = "visible_completion_tokens"
    output_token_ceiling_enforcement = "wire_total_and_visible_application_fail_closed"
    wire_output_token_ceiling = ANTIGRAVITY_GEMINI_WIRE_OUTPUT_TOKEN_CEILING

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "http://127.0.0.1:8045/v1",
        timeout: float = 90.0,
        http_client: Any | None = None,
    ) -> None:
        if os.environ.get("LLM_ABM_RUN_LIVE_LLM") != "1":
            raise ProviderConfigurationError(
                "Antigravity Gemini Provider use requires the explicit LLM_ABM_RUN_LIVE_LLM=1 gate"
            )
        self._client = _OpenAISDKClient(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            wire_api="chat",
            http_client=http_client,
            chat_output_token_field="max_tokens",
            chat_structured_output="json_schema",
            chat_thinking_budget=ANTIGRAVITY_GEMINI_THINKING_BUDGET,
            chat_additive_reasoning_usage=True,
        )

    @property
    def safe_metadata(self) -> dict[str, object]:
        return {
            "provider": self.provider_transport,
            "wire_api": self.wire_api,
            "thinking_budget": ANTIGRAVITY_GEMINI_THINKING_BUDGET,
            "reasoning_usage_mapping": "reasoning_included_in_completion_tokens",
            "decision_output_token_ceiling": ANTIGRAVITY_GEMINI_DECISION_TOKEN_CEILING,
            "wire_output_token_ceiling": ANTIGRAVITY_GEMINI_WIRE_OUTPUT_TOKEN_CEILING,
        }

    @property
    def last_safe_usage_diagnostics(self) -> dict[str, object] | None:
        diagnostics = self._client.last_safe_usage_diagnostics
        return None if diagnostics is None else dict(diagnostics)

    @property
    def last_output_tokens_for_ceiling(self) -> int | None:
        diagnostics = self.last_safe_usage_diagnostics
        if diagnostics is None:
            return None
        value = diagnostics.get("output_tokens")
        return value if type(value) is int else None

    def create_response(
        self,
        messages: list[dict[str, str]],
        model: str,
        *,
        reasoning_effort: ReasoningEffortValue | None = None,
        output_token_ceiling: int | None = None,
        thinking_mode: Literal["disabled"] | None = None,
    ) -> ProviderResponseEnvelope:
        if model not in ANTIGRAVITY_GEMINI_MODELS and model not in set(
            ANTIGRAVITY_GEMINI_MODEL_ROUTES.values()
        ):
            raise ProviderConfigurationError(
                "Antigravity Gemini transport requires a frozen Gemini model"
            )
        if reasoning_effort is not None:
            raise ProviderConfigurationError(
                "Antigravity Gemini Chat requests do not accept reasoning_effort"
            )
        if thinking_mode is not None:
            raise ProviderConfigurationError(
                "Antigravity Gemini Chat requests do not accept thinking_mode"
            )
        if output_token_ceiling != ANTIGRAVITY_GEMINI_DECISION_TOKEN_CEILING:
            raise ProviderConfigurationError(
                "Antigravity Gemini Chat requests require the frozen Decision-token ceiling"
            )
        return self._client.create_response(
            messages,
            ANTIGRAVITY_GEMINI_MODEL_ROUTES.get(model, model),
            output_token_ceiling=ANTIGRAVITY_GEMINI_WIRE_OUTPUT_TOKEN_CEILING,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> AntigravityGeminiProviderClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
