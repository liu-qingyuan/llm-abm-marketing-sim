from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from llm_abm_sim.decision import (
    DecisionInput,
    EngageDecision,
    LLMDecisionAdapter,
    ProviderAttemptFailure,
    ProviderDecisionError,
    ProviderResponseProvenanceUnknown,
)
from llm_abm_sim.prompt_contracts import CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY
from llm_abm_sim.prompting import build_engagement_prompt
from llm_abm_sim.provider_accounting import (
    ProviderAccounting,
    ProviderAccountingTracker,
    ProviderResponseEnvelope,
)
from llm_abm_sim.provider_request_contract import (
    DECISION_OUTPUT_SCHEMA,
    STRUCTURED_OUTPUT_SCHEMA_HASH,
    ReasoningEffortValue,
)
from llm_abm_sim.providers.openai_compatible import _parse_provider_decision
from llm_abm_sim.schemas import PeerContext, PlatformContext, PostContent, UserProfile

_MAXIMUM_PHYSICAL_ATTEMPTS = 3


class _RobustnessProviderClient(Protocol):
    """One-attempt transport shape used by the five frozen provider Adapters."""

    def create_response(
        self,
        messages: list[dict[str, str]],
        model: str,
        *,
        reasoning_effort: ReasoningEffortValue | None = None,
        output_token_ceiling: int | None = None,
        thinking_mode: Literal["disabled"] | None = None,
    ) -> ProviderResponseEnvelope:
        raise NotImplementedError


@dataclass(frozen=True)
class _ProviderCondition:
    provider_route: str
    requested_model: str
    wire_model: str
    required_observed_model: str
    wire_api: Literal["chat_completions", "responses", "pi_model_runtime"]
    reasoning_effort: Literal["low"] | None
    thinking_mode: Literal["disabled"] | None
    output_token_ceiling: int
    billing_semantics: str
    billing_currency: Literal["CNY"] | None
    fee_ceiling: float | None


_DEEPSEEK = _ProviderCondition(
    provider_route="deepseek_official",
    requested_model="deepseek-v4-flash",
    wire_model="deepseek-v4-flash",
    required_observed_model="deepseek-v4-flash",
    wire_api="chat_completions",
    reasoning_effort=None,
    thinking_mode="disabled",
    output_token_ceiling=256,
    billing_semantics="provider_fee_cny",
    billing_currency="CNY",
    fee_ceiling=25.0,
)
_GEMINI_CONDITIONS = {
    "gemini-3.1-pro": _ProviderCondition(
        provider_route="antigravity_openai_compatible_gateway",
        requested_model="gemini-3.1-pro",
        wire_model="gemini-3.1-pro",
        required_observed_model="gemini-pro-agent",
        wire_api="responses",
        reasoning_effort="low",
        thinking_mode=None,
        output_token_ceiling=256,
        billing_semantics="gateway_quota_usage",
        billing_currency=None,
        fee_ceiling=None,
    ),
    "gemini-3.8-flash-high": _ProviderCondition(
        provider_route="antigravity_openai_compatible_gateway",
        requested_model="gemini-3.8-flash-high",
        wire_model="gemini-3.8-flash-high",
        required_observed_model="gemini-3.8-flash-high",
        wire_api="responses",
        reasoning_effort="low",
        thinking_mode=None,
        output_token_ceiling=256,
        billing_semantics="gateway_quota_usage",
        billing_currency=None,
        fee_ceiling=None,
    ),
}
_KIMI = _ProviderCondition(
    provider_route="pi_kimi_oauth_subscription",
    requested_model="kimi-coding/k3-256k",
    wire_model="kimi-coding/k3-256k",
    required_observed_model="k3-256k",
    wire_api="pi_model_runtime",
    reasoning_effort="low",
    thinking_mode=None,
    output_token_ceiling=256,
    billing_semantics="subscription_quota_with_nominal_usd_reference",
    billing_currency=None,
    fee_ceiling=None,
)
_OPENAI = _ProviderCondition(
    provider_route="pi_openai_oauth_subscription",
    requested_model="openai-codex/gpt-5.6-sol",
    wire_model="gpt-5.6-sol",
    required_observed_model="gpt-5.6-sol",
    wire_api="pi_model_runtime",
    reasoning_effort="low",
    thinking_mode=None,
    output_token_ceiling=256,
    billing_semantics="subscription_quota_with_nominal_usd_reference",
    billing_currency=None,
    fee_ceiling=None,
)


_WAIT_SECONDS_PATTERN = re.compile(r"\bWait\s+([0-9]+(?:\.[0-9]+)?)\s*s\b", re.IGNORECASE)
_HTTP_STATUS_PATTERN = re.compile(
    r"\b(?:HTTP(?:\s+status)?|status(?:\s+code)?)[ :=]+(4\d\d|5\d\d)\b",
    re.IGNORECASE,
)
_RETRYABLE_HTTP_STATUSES = frozenset({408, 409, 429})


def _status_code(error: Exception) -> int | None:
    value = getattr(error, "status_code", None)
    if type(value) is int:
        return value
    response = getattr(error, "response", None)
    value = getattr(response, "status_code", None)
    if type(value) is int:
        return value
    matched = _HTTP_STATUS_PATTERN.search(str(error))
    return int(matched.group(1)) if matched is not None else None


def _retry_wait(error: Exception) -> tuple[float | None, str | None]:
    explicit_wait = getattr(error, "wait_seconds", None)
    if (
        not isinstance(explicit_wait, bool)
        and isinstance(explicit_wait, (int, float))
        and math.isfinite(float(explicit_wait))
        and float(explicit_wait) >= 0.0
    ):
        source = getattr(error, "wait_source", None)
        return float(explicit_wait), source if source in {"retry_after", "provider_wait"} else "provider_wait"
    headers = getattr(error, "headers", None)
    if not isinstance(headers, Mapping):
        response = getattr(error, "response", None)
        headers = getattr(response, "headers", None)
    if isinstance(headers, Mapping):
        value = next(
            (item for name, item in headers.items() if isinstance(name, str) and name.lower() == "retry-after"),
            None,
        )
        if isinstance(value, str):
            try:
                seconds = float(value.strip())
            except ValueError:
                seconds = -1.0
            if math.isfinite(seconds) and seconds >= 0.0:
                return seconds, "retry_after"
    matched = _WAIT_SECONDS_PATTERN.search(str(error))
    if matched is None:
        return None, None
    seconds = float(matched.group(1))
    return (seconds, "provider_wait") if math.isfinite(seconds) else (None, None)


def _normalize_attempt_failure(error: Exception) -> ProviderAttemptFailure:
    if isinstance(error, ProviderAttemptFailure):
        return error
    status_code = _status_code(error)
    wait_seconds, wait_source = _retry_wait(error)
    if status_code == 401:
        category = "authentication"
        retryable = False
    elif status_code == 403:
        category = "permission"
        retryable = False
    elif status_code is not None:
        category = "http_status"
        retryable = status_code in _RETRYABLE_HTTP_STATUSES or 500 <= status_code <= 599
    elif isinstance(error, TimeoutError) or "timeout" in type(error).__name__.lower():
        category = "timeout"
        retryable = True
    elif isinstance(error, ConnectionError) or any(
        token in type(error).__name__.lower() for token in ("connection", "connecterror")
    ):
        category = "connection"
        retryable = True
    elif "authentication" in type(error).__name__.lower() or "unauthorized" in type(error).__name__.lower():
        category = "authentication"
        retryable = False
    elif "permission" in type(error).__name__.lower() or "forbidden" in type(error).__name__.lower():
        category = "permission"
        retryable = False
    else:
        category = "provider_error"
        retryable = False
    return ProviderAttemptFailure(
        category=category,
        retryable=retryable,
        status_code=status_code,
        wait_seconds=wait_seconds,
        wait_source=wait_source,
        lane_cooldown=status_code in {429, 503},
    )


class _FrozenRobustnessDecisionAdapter(LLMDecisionAdapter):
    """Single-physical-attempt Adapter; the Study privately owns retries and cooldowns."""

    robustness_provider_adapter = True

    def __init__(
        self,
        *,
        condition: _ProviderCondition,
        prompt_version: str,
        client: _RobustnessProviderClient,
    ) -> None:
        prompt = CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.resolve(prompt_version)
        self.condition = condition
        self.prompt_version = prompt.prompt_version
        self.client = client
        self.request_invocations = 0
        self.external_request_invocations = 0
        self._provider_accounting = ProviderAccountingTracker()
        self._provider_fee_cny_total = 0.0
        self.deterministic_validation = not bool(getattr(client, "external_provider_client", False))
        self._request_evidence: dict[str, object] = {
            "schema_version": "robustness-provider-request-evidence-v2",
            "provider_route": condition.provider_route,
            "requested_model": condition.requested_model,
            "required_observed_model": condition.required_observed_model,
            "wire_api": condition.wire_api,
            "reasoning_effort": condition.reasoning_effort,
            "thinking_mode": condition.thinking_mode,
            "output_token_ceiling": condition.output_token_ceiling,
            "structured_output_schema_version": DECISION_OUTPUT_SCHEMA.schema_version,
            "structured_output_schema_hash": STRUCTURED_OUTPUT_SCHEMA_HASH,
            "maximum_physical_attempts_per_logical_pair": _MAXIMUM_PHYSICAL_ATTEMPTS,
            "prompt_version": prompt.prompt_version,
            "prompt_canonical_hash": prompt.canonical_hash,
            "billing_semantics": condition.billing_semantics,
            "billing_currency": condition.billing_currency,
            "fee_ceiling": condition.fee_ceiling,
        }

    @property
    def model(self) -> str:
        return self.condition.requested_model

    @property
    def required_observed_model(self) -> str:
        return self.condition.required_observed_model

    @property
    def provider_route(self) -> str:
        return self.condition.provider_route

    @property
    def request_evidence(self) -> dict[str, object]:
        return dict(self._request_evidence)

    @property
    def provider_accounting(self) -> ProviderAccounting:
        return self._provider_accounting.snapshot(
            external_request_invocations=self.external_request_invocations,
        )

    @property
    def provider_fee_cny_total(self) -> float | None:
        return self._provider_fee_cny_total if self.condition.billing_currency == "CNY" else None

    @property
    def subscription_nominal_cost_usd_total(self) -> float | None:
        if self.condition.billing_semantics != "subscription_quota_with_nominal_usd_reference":
            return None
        value = getattr(self.client, "subscription_nominal_cost_usd_total", 0.0)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("subscription nominal cost must be a finite USD reference")
        normalized = float(value)
        if not math.isfinite(normalized) or normalized < 0.0:
            raise ValueError("subscription nominal cost must be a finite non-negative USD reference")
        return normalized

    @property
    def maximum_provider_fee_cny_per_attempt(self) -> float | None:
        if self.condition.billing_currency != "CNY":
            return None
        value = getattr(self.client, "maximum_provider_fee_cny_per_attempt", None)
        if value is None:
            return 0.0 if self.deterministic_validation else None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("DeepSeek maximum attempt fee must be a finite CNY number")
        normalized = float(value)
        if not math.isfinite(normalized) or normalized < 0.0:
            raise ValueError("DeepSeek maximum attempt fee must be a finite non-negative CNY number")
        return normalized

    @property
    def live_api_triggered(self) -> bool:
        return self.external_request_invocations > 0

    @property
    def safe_metadata(self) -> dict[str, object]:
        return {
            "adapter": "frozen_robustness_provider",
            "adapter_version": "v2",
            **self.request_evidence,
        }

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
            prompt_version=self.prompt_version,
        )
        messages = build_engagement_prompt(decision_input)
        self.request_invocations += 1
        if bool(getattr(self.client, "external_provider_client", False)):
            self.external_request_invocations += 1
        try:
            if self.condition.thinking_mode is None:
                response = self.client.create_response(
                    messages,
                    self.condition.wire_model,
                    reasoning_effort=self.condition.reasoning_effort,
                    output_token_ceiling=self.condition.output_token_ceiling,
                )
            else:
                response = self.client.create_response(
                    messages,
                    self.condition.wire_model,
                    reasoning_effort=self.condition.reasoning_effort,
                    output_token_ceiling=self.condition.output_token_ceiling,
                    thinking_mode=self.condition.thinking_mode,
                )
        except ProviderResponseProvenanceUnknown:
            raise
        except Exception as exc:
            failure = _normalize_attempt_failure(exc)
            raise ProviderDecisionError(failure) from failure
        if not isinstance(response, ProviderResponseEnvelope):
            failure = ProviderAttemptFailure(category="response_evidence", retryable=False)
            raise ProviderDecisionError(failure) from failure
        self._provider_accounting.record_response(response)
        if self.condition.billing_currency == "CNY":
            fee = getattr(self.client, "last_provider_fee_cny", None)
            if fee is None:
                if not self.deterministic_validation:
                    failure = ProviderAttemptFailure(category="billing_evidence", retryable=False)
                    raise ProviderDecisionError(failure) from failure
            elif isinstance(fee, bool) or not isinstance(fee, (int, float)):
                failure = ProviderAttemptFailure(category="billing_evidence", retryable=False)
                raise ProviderDecisionError(failure) from failure
            else:
                normalized_fee = float(fee)
                if not math.isfinite(normalized_fee) or normalized_fee < 0.0:
                    failure = ProviderAttemptFailure(category="billing_evidence", retryable=False)
                    raise ProviderDecisionError(failure) from failure
                self._provider_fee_cny_total += normalized_fee
        elif getattr(self.client, "last_provider_fee_cny", None) is not None:
            failure = ProviderAttemptFailure(category="billing_currency", retryable=False)
            raise ProviderDecisionError(failure) from failure
        if (
            response.observed_model_status != "reported"
            or response.observed_model != self.condition.required_observed_model
        ):
            failure = ProviderAttemptFailure(category="model_identity", retryable=False)
            raise ProviderDecisionError(failure) from failure
        if response.usage_status != "complete":
            failure = ProviderAttemptFailure(category="usage_evidence", retryable=False)
            raise ProviderDecisionError(failure) from failure
        try:
            decision = _parse_provider_decision(response.decision_text)
        except Exception as exc:
            failure = ProviderAttemptFailure(category="malformed_structured_response", retryable=True)
            raise ProviderDecisionError(failure) from exc
        self._provider_accounting.record_successful_decision()
        return decision.model_copy(
            update={
                "decision_source": "provider",
                "provider_metadata": self.safe_metadata,
            }
        )


class DeepSeekV4FlashDecisionAdapter(_FrozenRobustnessDecisionAdapter):
    def __init__(self, *, prompt_version: str, client: _RobustnessProviderClient) -> None:
        super().__init__(condition=_DEEPSEEK, prompt_version=prompt_version, client=client)


class AntigravityGeminiDecisionAdapter(_FrozenRobustnessDecisionAdapter):
    def __init__(
        self,
        *,
        requested_model: str,
        prompt_version: str,
        client: _RobustnessProviderClient,
    ) -> None:
        try:
            condition = _GEMINI_CONDITIONS[requested_model]
        except KeyError as exc:
            raise ValueError("Antigravity Adapter requires one of the two frozen Gemini conditions") from exc
        super().__init__(condition=condition, prompt_version=prompt_version, client=client)


class PiKimiDecisionAdapter(_FrozenRobustnessDecisionAdapter):
    def __init__(self, *, prompt_version: str, client: _RobustnessProviderClient) -> None:
        super().__init__(condition=_KIMI, prompt_version=prompt_version, client=client)


class PiOpenAIDecisionAdapter(_FrozenRobustnessDecisionAdapter):
    def __init__(self, *, prompt_version: str, client: _RobustnessProviderClient) -> None:
        super().__init__(condition=_OPENAI, prompt_version=prompt_version, client=client)
