from __future__ import annotations

import importlib.util
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, cast

from llm_abm_sim.decision import DecisionInput, EngageDecision, LLMDecisionAdapter, ProviderDecisionError
from llm_abm_sim.prompting import build_engagement_prompt
from llm_abm_sim.provider_config import (
    load_codex_provider_config,
    resolve_runtime_credential,
    resolve_runtime_http_headers,
    sanitize_url,
    should_run_live_llm,
)
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
        raise NotImplementedError


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
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config or ProviderLLMConfig(enabled=True)
        self.codex_home = codex_home
        try:
            self.codex_provider_config = (
                load_codex_provider_config(codex_home) if self.config.use_codex_provider_config else None
            )
        except (OSError, ValueError) as exc:
            raise ProviderConfigurationError("invalid Codex provider configuration") from exc
        self.prompt_version = self.config.prompt_version
        model = self.config.model or (self.codex_provider_config.model if self.codex_provider_config else None)
        self.model = model or "gpt-5.5"
        self.client = client
        self._sleep = sleep
        self.external_request_invocations = 0

    @property
    def live_api_triggered(self) -> bool:
        return self.external_request_invocations > 0

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
        uses_live_client = self.client is None
        client = self.client or self._build_live_client()
        last_error: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                if uses_live_client:
                    self.external_request_invocations += 1
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
                if attempt < self.config.max_retries:
                    self._sleep(self.config.retry_backoff_seconds * (2**attempt))
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
        runtime_headers = None
        if self.codex_provider_config is not None:
            try:
                runtime_headers = resolve_runtime_http_headers(
                    codex_home=self.codex_home,
                    codex_provider=self.codex_provider_config,
                )
            except ValueError as exc:
                raise ProviderConfigurationError(str(exc)) from exc
        if credential is None and runtime_headers is None:
            raise ProviderConfigurationError(
                f"missing runtime auth from selected Codex provider or API key env {self.config.api_key_env}"
            )
        codex_base_url = self.codex_provider_config.base_url if self.codex_provider_config else None
        base_url: str | None
        if runtime_headers is not None:
            if not codex_base_url:
                raise ProviderConfigurationError("selected Codex provider headers require a provider base_url")
            if self.config.base_url and sanitize_url(self.config.base_url) != sanitize_url(codex_base_url):
                raise ProviderConfigurationError("selected Codex provider headers cannot be used with a base_url override")
            base_url = codex_base_url
        else:
            base_url = self.config.base_url or codex_base_url
        wire_api = self.config.wire_api or (
            self.codex_provider_config.wire_api if self.codex_provider_config else "responses"
        )
        return _OpenAISDKClient(
            api_key=credential.value if credential is not None else "codex-config-http-headers",
            base_url=base_url,
            timeout=self.config.timeout_seconds,
            wire_api=wire_api,
            default_headers=runtime_headers.values if runtime_headers is not None else None,
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
        raise ProviderDecisionError(exc) from exc


class _OpenAISDKClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None,
        timeout: float,
        wire_api: str = "responses",
        default_headers: dict[str, str] | None = None,
    ) -> None:
        from openai import OpenAI  # type: ignore[import-not-found]

        kwargs: dict[str, Any] = {"api_key": api_key, "timeout": timeout}
        if base_url:
            kwargs["base_url"] = base_url
        if default_headers:
            kwargs["default_headers"] = default_headers
        self._client = OpenAI(**kwargs)
        self._wire_api = wire_api

    def create_response(self, messages: list[dict[str, str]], model: str) -> str:
        sdk_messages = cast(Any, messages)
        if self._wire_api == "chat":
            chat_response = self._client.chat.completions.create(
                model=model,
                messages=sdk_messages,
                response_format={"type": "json_object"},
            )
            content = chat_response.choices[0].message.content
            return content or ""
        provider_response = self._client.responses.create(
            model=model,
            input=sdk_messages,
            text=cast(Any, {"format": _engage_decision_json_schema()}),
        )
        return str(provider_response.output_text)


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
