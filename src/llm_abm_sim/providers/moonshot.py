"""One-attempt Moonshot transport; Study owns authorization and all retry policy.

Credentials live only in the HTTP client. Responses cross this Seam exclusively
as normalized decision/model/usage facts, never raw provider messages or reasoning.
"""
from __future__ import annotations

from typing import Any

from llm_abm_sim.decision import ProviderAttemptFailure, ProviderResponseProvenanceUnknown
from llm_abm_sim.provider_accounting import ProviderResponseEnvelope, normalize_provider_response_envelope
from llm_abm_sim.provider_request_contract import engage_decision_json_schema


class MoonshotOfficialClient:
    """Official K3 client, explicitly gated, with no retries or redirects.

    Inject a transport for offline tests. The owner must close the client, persist
    intent before dispatch, and handle unknown response provenance by reconciliation.
    Neither this client nor its live gate admits a recovery campaign migration.
    """

    external_provider_client = True
    provider_transport = "moonshot_official"
    adapter_identity = "moonshot-official-k3-client-v1"
    output_token_ceiling_enforcement = "wire_only"

    def __init__(self, *, api_key: str, live_enabled: bool = False, transport: Any = None) -> None:
        if live_enabled is not True or not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("Official Moonshot requires an explicit live gate and runtime credential")
        import httpx  # Optional live dependency, supplied by the existing llm extra.

        self._httpx = httpx
        self._client = httpx.Client(
            base_url="https://api.moonshot.cn/v1/",
            headers={"Authorization": "Bearer " + api_key},
            timeout=90, follow_redirects=False, trust_env=False,
            transport=transport if transport is not None else httpx.HTTPTransport(retries=0),
        )

    def __enter__(self) -> MoonshotOfficialClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    @property
    def safe_metadata(self) -> dict[str, object]:
        return {
            "adapter_identity": self.adapter_identity,
            "provider_transport": self.provider_transport,
            "base_url": "https://api.moonshot.cn/v1",
            "wire_model": "kimi-k3", "automatic_retries": 0,
            "output_token_ceiling_enforcement": self.output_token_ceiling_enforcement,
        }

    def create_response(
        self, messages: list[dict[str, str]], model: str, *,
        reasoning_effort: str | None = None, output_token_ceiling: int | None = None,
        thinking_mode: str | None = None,
    ) -> ProviderResponseEnvelope:
        if (model != "kimi-k3" or reasoning_effort != "low"
            or type(output_token_ceiling) is not int or output_token_ceiling != 1024
            or thinking_mode is not None):
            raise ValueError("Official K3 requires its exact model, low reasoning and 1024 ceiling")
        body = {
            "model": model, "messages": messages, "max_tokens": output_token_ceiling,
            "reasoning_effort": reasoning_effort, "tool_choice": "required",
            "tools": [{"type": "function", "function": {
                "name": "engage_decision", "description": "Return one structured engagement decision.",
                "parameters": engage_decision_json_schema()["schema"],
            }}],
        }
        try:
            response = self._client.post("chat/completions", json=body)
        except self._httpx.TransportError:
            raise ProviderResponseProvenanceUnknown("Official Moonshot response is unsettled") from None
        if response.status_code != 200:
            category = {
                400: "request_invalid", 401: "authentication", 402: "quota_exhausted",
                403: "entitlement", 429: "rate_limited",
            }.get(response.status_code, "provider_stop")
            # Status alone does not prove the provider's detailed reason; no body is retained.
            raise ProviderAttemptFailure(category=category, retryable=False, status_code=response.status_code)
        try:
            payload = response.json()
            if not isinstance(payload, dict):
                payload = {}
        except ValueError:
            payload = {}
        # A malformed decision still has a real response; retain its usage and
        # identity so the Adapter can account for it before failing closed.
        decision_text = ""
        try:
            choice, = payload["choices"]
            call, = choice["message"]["tool_calls"]
            if (choice["finish_reason"] == "tool_calls" and call.get("type") == "function"
                and call["function"]["name"] == "engage_decision"
                and isinstance(call["function"]["arguments"], str)):
                decision_text = call["function"]["arguments"]
        except (ValueError, TypeError, KeyError, AttributeError):
            pass
        return normalize_provider_response_envelope(
            decision_text=decision_text, observed_model=payload.get("model"),
            usage=payload.get("usage"), input_tokens_field="prompt_tokens",
            output_tokens_field="completion_tokens", cached_details_field="prompt_tokens_details",
        )
