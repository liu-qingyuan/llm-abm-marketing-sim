from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .events import SimulationRunResult
from .provider_config import redact_secrets, sanitize_url

PROVIDER_METADATA_ALLOWLIST = {
    "adapter",
    "adapter_version",
    "auth_available",
    "base_url",
    "codex_provider",
    "configured",
    "decision_source_summary",
    "enabled",
    "fail_closed_action",
    "first_provider_decision",
    "model",
    "prompt_version",
    "provider",
    "provider_decision_count",
    "provider_metadata",
    "provider_name",
    "provider_readiness",
    "require_live_env",
    "requires_openai_auth",
    "use_codex_provider_config",
    "wire_api",
    "time_step",
    "user_id",
    "action",
    "probability",
    "confidence",
    "reason",
}

_FORBIDDEN_KEY_FRAGMENTS = (
    "authorization",
    "bearer",
    "cookie",
    "credential",
    "header",
    "password",
    "raw_auth",
    "raw_prompt",
    "raw_provider",
    "request_payload",
    "response_payload",
    "secret",
    "token",
)


def decision_source_summary(result: SimulationRunResult) -> dict[str, int]:
    summary: dict[str, int] = {}
    for event in result.decision_events:
        source = event.decision.decision_source or "unknown"
        summary[source] = summary.get(source, 0) + 1
    return dict(sorted(summary.items()))


def provider_evidence(
    result: SimulationRunResult, provider_readiness: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    provider_decisions = [event for event in result.decision_events if event.decision.decision_source == "provider"]
    if provider_readiness is None and not provider_decisions:
        return None
    evidence: dict[str, Any] = {
        "decision_source_summary": decision_source_summary(result),
        "provider_decision_count": len(provider_decisions),
    }
    if provider_decisions:
        first = provider_decisions[0]
        evidence["first_provider_decision"] = {
            "time_step": first.time_step,
            "user_id": first.user_id,
            "action": first.decision.action,
            "probability": first.decision.probability,
            "confidence": first.decision.confidence,
            "reason": first.decision.reason,
        }
        evidence["provider_metadata"] = first.decision.provider_metadata
    if provider_readiness is not None:
        evidence["provider_readiness"] = provider_readiness
    return allowlisted_provider_evidence(evidence)


def allowlisted_provider_evidence(value: Any) -> Any:
    """Keep only provider product evidence fields and redact the kept values."""

    if isinstance(value, dict):
        kept: dict[str, Any] = {}
        for key, item in value.items():
            lowered = key.lower()
            if any(fragment in lowered for fragment in _FORBIDDEN_KEY_FRAGMENTS):
                continue
            if key not in PROVIDER_METADATA_ALLOWLIST:
                continue
            kept[key] = allowlisted_provider_evidence(item)
        return redact_secrets(kept)
    if isinstance(value, list):
        return [allowlisted_provider_evidence(item) for item in value]
    if isinstance(value, str) and (value.startswith("http://") or value.startswith("https://")):
        return sanitize_url(value)
    return redact_secrets(value)
