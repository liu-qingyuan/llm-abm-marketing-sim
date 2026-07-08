from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any, Protocol, cast

from llm_abm_sim.decision import DecisionInput, EngageDecision, LLMDecisionAdapter
from llm_abm_sim.prompting import build_engagement_prompt
from llm_abm_sim.provider_config import load_codex_provider_config, resolve_runtime_credential, should_run_live_llm
from llm_abm_sim.schemas import (
    FailClosedAction,
    PeerContext,
    PlatformContext,
    PostContent,
    ProviderLLMConfig,
    UserProfile,
)


class ProviderClient(Protocol):
    """Minimal client protocol used by tests and optional OpenAI SDK wrapper."""

    def create_response(self, messages: list[dict[str, str]], model: str) -> str | dict[str, Any]:
        """Return provider text or a parsed dict containing an engagement decision."""


class ProviderRunSkipped(RuntimeError):
    """Raised when provider use is explicitly configured to skip the run on failure."""


class ProviderConfigurationError(RuntimeError):
    """Raised for missing provider SDK/auth/gate configuration."""


REQUIRED_PROVIDER_DECISION_FIELDS = frozenset({"engage", "probability", "reason", "confidence", "action"})


class OpenAICompatibleDecisionAdapter(LLMDecisionAdapter):
    """Optional OpenAI Responses-compatible implementation of LLMDecisionAdapter."""

    def __init__(
        self,
        config: ProviderLLMConfig | None = None,
        *,
        client: ProviderClient | None = None,
        codex_home: str | Path | None = None,
    ) -> None:
        self.config = config or ProviderLLMConfig(enabled=True)
        self.codex_home = codex_home
        self.codex_provider_config = (
            load_codex_provider_config(codex_home) if self.config.use_codex_provider_config else None
        )
        self.prompt_version = self.config.prompt_version
        model = self.config.model or (self.codex_provider_config.model if self.codex_provider_config else None)
        self.model = model or "gpt-5.5"
        self.client = client

    @property
    def safe_metadata(self) -> dict[str, Any]:
        metadata = self.config.safe_metadata()
        metadata["adapter"] = "openai_compatible"
        metadata["adapter_version"] = "phase3-v1"
        metadata["model"] = self.model
        if self.codex_provider_config is not None:
            metadata["codex_provider"] = self.codex_provider_config.redacted()
        return metadata

    def decide(
        self,
        post: PostContent,
        profile: UserProfile,
        peer_context: PeerContext,
        platform_context: PlatformContext | None = None,
        time_step: int = 0,
    ) -> EngageDecision:
        decision_input = DecisionInput(
            post=post,
            profile=profile,
            peer_context=peer_context,
            platform_context=platform_context or PlatformContext(),
            time_step=time_step,
            prompt_version=self.config.prompt_version,
        )
        messages = build_engagement_prompt(decision_input)
        client = self.client or self._build_live_client()
        last_error: Exception | None = None
        for _attempt in range(self.config.max_retries + 1):
            try:
                raw = client.create_response(messages, cast(str, self.model))
                decision = _parse_provider_decision(raw)
                return decision.model_copy(
                    update={
                        "decision_source": "provider",
                        "provider_metadata": self.safe_metadata,
                    }
                )
            except Exception as exc:
                last_error = exc
        if last_error is None:  # defensive; max_retries validation keeps this unreachable.
            last_error = ProviderConfigurationError("provider request did not run")
        return self._handle_failure(last_error)

    def _build_live_client(self) -> ProviderClient:
        if self.config.require_live_env and not should_run_live_llm(self.codex_home):
            raise ProviderConfigurationError(
                "live provider use requires LLM_ABM_RUN_LIVE_LLM=1 and ready Codex provider/auth metadata"
            )
        if importlib.util.find_spec("openai") is None:
            raise ProviderConfigurationError("optional openai dependency is not installed")

        credential = resolve_runtime_credential(
            api_key_env=self.config.api_key_env,
            codex_home=self.codex_home,
            codex_provider=self.codex_provider_config,
        )
        if credential is None:
            raise ProviderConfigurationError(
                f"missing runtime credential from Codex auth or API key env {self.config.api_key_env}"
            )
        base_url = self.config.base_url or (self.codex_provider_config.base_url if self.codex_provider_config else None)
        wire_api = self.config.wire_api or (
            self.codex_provider_config.wire_api if self.codex_provider_config else "responses"
        )
        return _OpenAISDKClient(
            api_key=credential.value,
            base_url=base_url,
            timeout=self.config.timeout_seconds,
            wire_api=wire_api,
        )

    def _handle_failure(self, exc: Exception) -> EngageDecision:
        action = self.config.fail_closed_action
        if action == FailClosedAction.NO_ENGAGE:
            return EngageDecision(
                engage=False,
                probability=0.0,
                reason=f"provider failed closed: {exc.__class__.__name__}",
                confidence=0.0,
                action="ignore",
                decision_source="provider_fail_closed",
                provider_metadata=self.safe_metadata,
            )
        if action == FailClosedAction.SKIP_RUN:
            raise ProviderRunSkipped("provider failure configured to skip run") from exc
        raise exc


class _OpenAISDKClient:
    def __init__(self, *, api_key: str, base_url: str | None, timeout: float, wire_api: str = "responses") -> None:
        from openai import OpenAI  # type: ignore[import-not-found]

        kwargs: dict[str, Any] = {"api_key": api_key, "timeout": timeout}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = OpenAI(**kwargs)
        self._wire_api = wire_api

    def create_response(self, messages: list[dict[str, str]], model: str) -> str:
        if self._wire_api == "chat":
            response = self._client.chat.completions.create(  # type: ignore[call-overload]
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            return content or ""
        response = self._client.responses.create(  # type: ignore[call-overload]
            model=model,
            input=messages,
            text={"format": _engage_decision_json_schema()},
        )
        return str(response.output_text)


def _engage_decision_json_schema() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "name": "engage_decision",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["engage", "probability", "reason", "confidence", "action"],
            "properties": {
                "engage": {"type": "boolean"},
                "probability": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "reason": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "action": {"type": "string", "enum": ["ignore", "like", "comment", "share"]},
            },
        },
    }


def _parse_provider_decision(raw: str | dict[str, Any]) -> EngageDecision:
    payload = raw
    if isinstance(raw, str):
        payload = _loads_json_object(raw)
    if not isinstance(payload, dict):
        raise ValueError("provider response JSON must be an object")
    missing_fields = sorted(REQUIRED_PROVIDER_DECISION_FIELDS - payload.keys())
    if missing_fields:
        raise ValueError(f"provider response missing required fields: {', '.join(missing_fields)}")
    return EngageDecision.model_validate(payload)


def _loads_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ValueError("provider response was not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("provider response JSON must be an object")
    return payload
