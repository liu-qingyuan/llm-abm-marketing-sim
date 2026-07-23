from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator

ObservedModelStatus = Literal["reported", "missing", "malformed"]
ProviderUsageStatus = Literal["complete", "missing", "malformed"]
_OBSERVED_MODEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
_UNSAFE_MODEL_FRAGMENTS = (
    "api_key",
    "apikey",
    "auth",
    "bearer",
    "cookie",
    "credential",
    "header",
    "password",
    "secret",
    "session",
    "token",
)
_UNSAFE_MODEL_PREFIXES = ("akia", "eyj", "ghp_", "github_pat_", "sk-", "xox")


class _NormalizedUsage(TypedDict):
    usage_status: ProviderUsageStatus
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cached_input_tokens: int | None


class ProviderResponseEnvelope(BaseModel):
    """Safe response facts retained after an OpenAI-compatible call returns."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    decision_text: str
    observed_model: str | None
    observed_model_status: ObservedModelStatus
    usage_status: ProviderUsageStatus
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _validate_normalized_response(self) -> ProviderResponseEnvelope:
        if self.observed_model_status == "reported":
            if not self.observed_model or not _is_safe_observed_model(self.observed_model):
                raise ValueError("reported observed model must be a safe model identifier")
        elif self.observed_model is not None:
            raise ValueError("missing or malformed observed model must not retain a value")

        token_values = (self.input_tokens, self.output_tokens, self.total_tokens)
        if self.usage_status != "complete":
            if any(value is not None for value in (*token_values, self.cached_input_tokens)):
                raise ValueError("incomplete usage must not retain token counters")
            return self
        if any(value is None for value in token_values):
            raise ValueError("complete usage requires input, output, and total token counters")
        input_tokens = self.input_tokens
        output_tokens = self.output_tokens
        total_tokens = self.total_tokens
        assert input_tokens is not None and output_tokens is not None and total_tokens is not None
        if total_tokens != input_tokens + output_tokens:
            raise ValueError("complete usage total_tokens must equal input_tokens + output_tokens")
        if self.cached_input_tokens is not None and self.cached_input_tokens > input_tokens:
            raise ValueError("cached input tokens cannot exceed input tokens")
        return self


class ProviderAccounting(BaseModel):
    """Strict cumulative or run-local aggregate of safe Provider response facts."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["provider-accounting-v1"] = "provider-accounting-v1"
    external_request_invocations: int = Field(ge=0)
    provider_response_count: int = Field(ge=0)
    successful_decision_count: int = Field(ge=0)
    observed_model_counts: dict[str, int]
    observed_model_missing_response_count: int = Field(ge=0)
    observed_model_malformed_response_count: int = Field(ge=0)
    usage_complete_response_count: int = Field(ge=0)
    usage_missing_response_count: int = Field(ge=0)
    usage_malformed_response_count: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens_reported_response_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate_denominators(self) -> ProviderAccounting:
        if any(
            not _is_safe_observed_model(model) or type(count) is not int or count < 0
            for model, count in self.observed_model_counts.items()
        ):
            raise ValueError("observed model counts require non-empty model names and non-negative strict integers")
        observed_total = (
            sum(self.observed_model_counts.values())
            + self.observed_model_missing_response_count
            + self.observed_model_malformed_response_count
        )
        if observed_total != self.provider_response_count:
            raise ValueError("observed model accounting must cover every Provider response")
        usage_total = (
            self.usage_complete_response_count + self.usage_missing_response_count + self.usage_malformed_response_count
        )
        if usage_total != self.provider_response_count:
            raise ValueError("usage accounting must cover every Provider response")
        if self.successful_decision_count > self.provider_response_count:
            raise ValueError("successful Decisions cannot exceed returned Provider responses")
        if self.cached_input_tokens_reported_response_count > self.usage_complete_response_count:
            raise ValueError("cached-token response count cannot exceed complete-usage response count")

        token_values = (self.input_tokens, self.output_tokens, self.total_tokens)
        if self.usage_complete_response_count == 0:
            if any(value is not None for value in (*token_values, self.cached_input_tokens)):
                raise ValueError("token aggregates must be null when no response has complete usage")
            return self
        if any(value is None for value in token_values):
            raise ValueError("complete usage responses require input, output, and total aggregates")
        input_tokens = self.input_tokens
        output_tokens = self.output_tokens
        total_tokens = self.total_tokens
        assert input_tokens is not None and output_tokens is not None and total_tokens is not None
        if total_tokens != input_tokens + output_tokens:
            raise ValueError("aggregate total_tokens must equal input_tokens + output_tokens")
        has_cached_reports = self.cached_input_tokens_reported_response_count > 0
        if has_cached_reports != (self.cached_input_tokens is not None):
            raise ValueError("cached token aggregate is available only when at least one response reports it")
        if self.cached_input_tokens is not None and self.cached_input_tokens > input_tokens:
            raise ValueError("aggregate cached input tokens cannot exceed aggregate input tokens")
        return self


class ProviderAccountingTracker:
    """Mutable Adapter-local tracker with immutable typed snapshots."""

    def __init__(self) -> None:
        self._provider_response_count = 0
        self._successful_decision_count = 0
        self._observed_model_counts: Counter[str] = Counter()
        self._observed_model_status_counts: Counter[str] = Counter()
        self._usage_status_counts: Counter[str] = Counter()
        self._input_tokens = 0
        self._output_tokens = 0
        self._total_tokens = 0
        self._cached_input_tokens = 0
        self._cached_input_tokens_reported_response_count = 0

    def record_response(self, response: ProviderResponseEnvelope) -> None:
        self._provider_response_count += 1
        self._observed_model_status_counts[response.observed_model_status] += 1
        if response.observed_model_status == "reported":
            assert response.observed_model is not None
            self._observed_model_counts[response.observed_model] += 1
        self._usage_status_counts[response.usage_status] += 1
        if response.usage_status == "complete":
            assert response.input_tokens is not None
            assert response.output_tokens is not None
            assert response.total_tokens is not None
            self._input_tokens += response.input_tokens
            self._output_tokens += response.output_tokens
            self._total_tokens += response.total_tokens
            if response.cached_input_tokens is not None:
                self._cached_input_tokens += response.cached_input_tokens
                self._cached_input_tokens_reported_response_count += 1

    def record_successful_decision(self) -> None:
        self._successful_decision_count += 1

    def snapshot(self, *, external_request_invocations: int) -> ProviderAccounting:
        complete_count = self._usage_status_counts["complete"]
        has_complete_usage = complete_count > 0
        has_cached_reports = self._cached_input_tokens_reported_response_count > 0
        return ProviderAccounting(
            external_request_invocations=external_request_invocations,
            provider_response_count=self._provider_response_count,
            successful_decision_count=self._successful_decision_count,
            observed_model_counts=dict(sorted(self._observed_model_counts.items())),
            observed_model_missing_response_count=self._observed_model_status_counts["missing"],
            observed_model_malformed_response_count=self._observed_model_status_counts["malformed"],
            usage_complete_response_count=complete_count,
            usage_missing_response_count=self._usage_status_counts["missing"],
            usage_malformed_response_count=self._usage_status_counts["malformed"],
            input_tokens=self._input_tokens if has_complete_usage else None,
            output_tokens=self._output_tokens if has_complete_usage else None,
            total_tokens=self._total_tokens if has_complete_usage else None,
            cached_input_tokens=self._cached_input_tokens if has_cached_reports else None,
            cached_input_tokens_reported_response_count=self._cached_input_tokens_reported_response_count,
        )


def coerce_provider_response_envelope(value: object) -> ProviderResponseEnvelope:
    """Keep legacy injected clients usable while marking unavailable accounting as missing."""

    if isinstance(value, ProviderResponseEnvelope):
        return value
    if isinstance(value, str):
        decision_text = value
    elif isinstance(value, dict):
        decision_text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    else:
        decision_text = str(value)
    return ProviderResponseEnvelope(
        decision_text=decision_text,
        observed_model=None,
        observed_model_status="missing",
        usage_status="missing",
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
        cached_input_tokens=None,
    )


def empty_provider_accounting() -> ProviderAccounting:
    return ProviderAccounting(
        external_request_invocations=0,
        provider_response_count=0,
        successful_decision_count=0,
        observed_model_counts={},
        observed_model_missing_response_count=0,
        observed_model_malformed_response_count=0,
        usage_complete_response_count=0,
        usage_missing_response_count=0,
        usage_malformed_response_count=0,
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
        cached_input_tokens=None,
        cached_input_tokens_reported_response_count=0,
    )


def provider_accounting_delta(
    current: ProviderAccounting,
    baseline: ProviderAccounting,
) -> ProviderAccounting:
    """Return a strict non-negative run-local delta between cumulative snapshots."""

    scalar_fields = (
        "external_request_invocations",
        "provider_response_count",
        "successful_decision_count",
        "observed_model_missing_response_count",
        "observed_model_malformed_response_count",
        "usage_complete_response_count",
        "usage_missing_response_count",
        "usage_malformed_response_count",
        "cached_input_tokens_reported_response_count",
    )
    deltas: dict[str, int] = {}
    for field_name in scalar_fields:
        delta = getattr(current, field_name) - getattr(baseline, field_name)
        if delta < 0:
            raise ValueError(f"provider accounting counter moved backwards: {field_name}")
        deltas[field_name] = delta

    observed_model_counts: dict[str, int] = {}
    for model in sorted(set(current.observed_model_counts) | set(baseline.observed_model_counts)):
        delta = current.observed_model_counts.get(model, 0) - baseline.observed_model_counts.get(model, 0)
        if delta < 0:
            raise ValueError(f"provider accounting observed model counter moved backwards: {model}")
        if delta:
            observed_model_counts[model] = delta

    complete_delta = deltas["usage_complete_response_count"]
    cached_report_delta = deltas["cached_input_tokens_reported_response_count"]
    return ProviderAccounting(
        external_request_invocations=deltas["external_request_invocations"],
        provider_response_count=deltas["provider_response_count"],
        successful_decision_count=deltas["successful_decision_count"],
        observed_model_counts=observed_model_counts,
        observed_model_missing_response_count=deltas["observed_model_missing_response_count"],
        observed_model_malformed_response_count=deltas["observed_model_malformed_response_count"],
        usage_complete_response_count=complete_delta,
        usage_missing_response_count=deltas["usage_missing_response_count"],
        usage_malformed_response_count=deltas["usage_malformed_response_count"],
        input_tokens=_optional_counter_delta(current.input_tokens, baseline.input_tokens) if complete_delta else None,
        output_tokens=_optional_counter_delta(current.output_tokens, baseline.output_tokens)
        if complete_delta
        else None,
        total_tokens=_optional_counter_delta(current.total_tokens, baseline.total_tokens) if complete_delta else None,
        cached_input_tokens=(
            _optional_counter_delta(current.cached_input_tokens, baseline.cached_input_tokens)
            if cached_report_delta
            else None
        ),
        cached_input_tokens_reported_response_count=cached_report_delta,
    )


def _optional_counter_delta(current: int | None, baseline: int | None) -> int:
    delta = (current or 0) - (baseline or 0)
    if delta < 0:
        raise ValueError("provider accounting token aggregate moved backwards")
    return delta


_MISSING = object()
_MALFORMED_FIELD = object()


def response_field(value: object, name: str) -> Any:
    """Read one SDK response field without allowing metadata access to fail a Decision."""

    try:
        if isinstance(value, dict):
            return value.get(name, _MISSING)
        return getattr(value, name, _MISSING)
    except Exception:
        return _MALFORMED_FIELD


def normalize_provider_response_envelope(
    *,
    decision_text: str,
    observed_model: object,
    usage: object,
    input_tokens_field: str,
    output_tokens_field: str,
    cached_details_field: str,
) -> ProviderResponseEnvelope:
    model_value, model_status = _normalize_observed_model(observed_model)
    usage_values = _normalize_usage(
        usage,
        input_tokens_field=input_tokens_field,
        output_tokens_field=output_tokens_field,
        cached_details_field=cached_details_field,
    )
    return ProviderResponseEnvelope(
        decision_text=decision_text,
        observed_model=model_value,
        observed_model_status=model_status,
        **usage_values,
    )


def _normalize_observed_model(value: object) -> tuple[str | None, ObservedModelStatus]:
    if value is _MISSING or value is None:
        return None, "missing"
    if isinstance(value, str) and _is_safe_observed_model(value):
        return value, "reported"
    return None, "malformed"


def _normalize_usage(
    usage: object,
    *,
    input_tokens_field: str,
    output_tokens_field: str,
    cached_details_field: str,
) -> _NormalizedUsage:
    if usage is _MISSING or usage is None:
        return _unavailable_usage("missing")

    input_tokens = response_field(usage, input_tokens_field)
    output_tokens = response_field(usage, output_tokens_field)
    total_tokens = response_field(usage, "total_tokens")
    if not all(_is_non_negative_integer(value) for value in (input_tokens, output_tokens, total_tokens)):
        return _unavailable_usage("malformed")
    assert type(input_tokens) is int and type(output_tokens) is int and type(total_tokens) is int
    if total_tokens != input_tokens + output_tokens:
        return _unavailable_usage("malformed")

    cached_input_tokens: int | None = None
    details = response_field(usage, cached_details_field)
    if details is not _MISSING and details is not None:
        if details is _MALFORMED_FIELD:
            return _unavailable_usage("malformed")
        if isinstance(details, (str, bytes, list, tuple, set, int, float, bool)):
            return _unavailable_usage("malformed")
        cached_value = response_field(details, "cached_tokens")
        if cached_value is not _MISSING and cached_value is not None:
            if not _is_non_negative_integer(cached_value) or cached_value > input_tokens:
                return _unavailable_usage("malformed")
            assert type(cached_value) is int
            cached_input_tokens = cached_value
    return {
        "usage_status": "complete",
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cached_input_tokens": cached_input_tokens,
    }


def _unavailable_usage(status: Literal["missing", "malformed"]) -> _NormalizedUsage:
    return {
        "usage_status": status,
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "cached_input_tokens": None,
    }


def _is_non_negative_integer(value: object) -> bool:
    return type(value) is int and value >= 0


def _is_safe_observed_model(value: str) -> bool:
    lowered = value.lower()
    return (
        _OBSERVED_MODEL_PATTERN.fullmatch(value) is not None
        and not lowered.startswith(_UNSAFE_MODEL_PREFIXES)
        and not any(fragment in lowered for fragment in _UNSAFE_MODEL_FRAGMENTS)
    )
