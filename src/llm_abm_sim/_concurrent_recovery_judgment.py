"""Private recovery Judgment contract for the concurrent robustness resolver.

This module defines only the persisted contract and its pure realization projection.  It
must not be used as a recovery executor or as an alternate v2 Judgment reader.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import (
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
    model_validator,
)

from . import concurrent_robustness_formal_execution as _formal
from . import concurrent_robustness_v2 as _v2
from .concurrent_message_experiment import _PairExecutionPlan
from .decision import EngageDecision
from .engagement_realization import (
    REALIZATION_RULE_VERSION,
    REALIZATION_SEED,
    EngagementRealizationPolicy,
)

RECOVERY_JUDGMENT_V1_SCHEMA = "concurrent-recovery-provider-judgment-v1"


class PairCoordinates(_v2._V2FrozenModel):
    """The runtime pair identity, kept separate from the recovery epoch."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    pair_id: str = Field(min_length=1)
    pair_schedule_position: int = Field(ge=0)
    time_step: int = Field(ge=0)
    message_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)

    @field_validator("pair_id", "message_id", "user_id")
    @classmethod
    def _validate_identity_part(cls, value: str) -> str:
        if "\0" in value:
            raise ValueError("pair coordinates must be NUL-free")
        return value


class RecoveryJudgmentV1(_v2._V2FrozenModel):
    """A recovery-only Judgment that preserves the original attempt ordinals."""

    schema_version: Literal["concurrent-recovery-provider-judgment-v1", "concurrent-recovery-provider-judgment-v2", "concurrent-recovery-provider-judgment-v3", "concurrent-recovery-provider-judgment-v4"]
    quota_retry_approval: _formal.FormalArtifactReference | None = None
    output_amendment_approval: _formal.FormalArtifactReference | None = None
    official_migration_approval: _formal.FormalArtifactReference | None = None
    judgment_id: str
    epoch_identity_sha256: str
    judgment_source_identity: str
    cell_index: int = Field(ge=0, lt=_v2._V2_CELL_COUNT)
    cell: _v2._PromptModelCell
    pair: PairCoordinates
    decision: EngageDecision
    historical_attempts: tuple[_v2._V2AttemptEvidence, ...]
    new_attempts: tuple[_v2._V2AttemptEvidence, ...]

    @model_serializer(mode="wrap")
    def _serialize_version(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        payload = handler(self)
        if self.quota_retry_approval is None:
            payload.pop("quota_retry_approval", None)
        if self.output_amendment_approval is None:
            payload.pop("output_amendment_approval", None)
        if self.official_migration_approval is None:
            payload.pop("official_migration_approval", None)
        return payload

    @field_validator("judgment_id", "epoch_identity_sha256", "judgment_source_identity")
    @classmethod
    def _validate_sha256(cls, value: str) -> str:
        return _v2._require_sha256(value, "Recovery Judgment identity")

    @model_validator(mode="after")
    def _validate_recovery_judgment(self) -> RecoveryJudgmentV1:
        historical_count = len(self.historical_attempts)
        new_count = len(self.new_attempts)
        if not new_count:
            raise ValueError("recovery Judgment requires at least one new attempt")
        if historical_count + new_count > _v2._V2_MAXIMUM_ATTEMPTS:
            raise ValueError("recovery Judgment exceeds the physical-attempt cap")
        if tuple(row.attempt_number for row in self.historical_attempts) != tuple(
            range(1, historical_count + 1)
        ):
            raise ValueError("historical attempt ordinals must remain 1..N")
        if tuple(row.attempt_number for row in self.new_attempts) != tuple(
            range(historical_count + 1, historical_count + new_count + 1)
        ):
            raise ValueError("new attempt ordinals must continue at N+1..N+M")
        if any(row.outcome == "succeeded" for row in self.historical_attempts):
            raise ValueError("historical attempts cannot contain a success")
        if self.new_attempts[-1].outcome != "succeeded":
            raise ValueError("new attempts must end in one success")
        preceding = [row for row in self.new_attempts[:-1] if row.outcome != "retryable_failure"]
        official = self.schema_version == "concurrent-recovery-provider-judgment-v4"
        if not official and self.official_migration_approval is not None:
            raise ValueError("Official migration approval requires Judgment v4")
        if official:
            if (self.official_migration_approval is None or self.output_amendment_approval is not None
                or self.quota_retry_approval is not None or self.cell.requested_model != "kimi-coding/k3-256k"
                or historical_count or new_count not in {1, 2}
                or self.new_attempts[-1].provider_route != "moonshot_official"
                or self.new_attempts[-1].output_usage is None or self.new_attempts[-1].output_usage > 1024):
                raise ValueError("Official Kimi Judgment requires its migration reference and bounded new response")
            if new_count == 2:
                old = self.new_attempts[0]
                if (old.provider_route != "pi_kimi_oauth_subscription" or old.outcome != "nonretryable_failure"
                    or old.failure_category != "entitlement" or old.status_code != 403 or old.provider_response_count != 0):
                    raise ValueError("Official migration only preserves one original subscription 403 before success")
        elif self.schema_version == "concurrent-recovery-provider-judgment-v3":
            if (self.output_amendment_approval is None or self.quota_retry_approval is not None
                or self.cell.requested_model != "kimi-coding/k3-256k" or preceding
                or any(row.output_usage is not None and row.output_usage > 1024 for row in self.new_attempts)):
                raise ValueError("Kimi Judgment v3 requires its explicit 1024 approval and bounded usage")
        elif self.output_amendment_approval is not None:
            raise ValueError("Output amendment requires Judgment v3")
        elif self.schema_version == RECOVERY_JUDGMENT_V1_SCHEMA:
            if self.quota_retry_approval is not None or preceding:
                raise ValueError("new attempts before the success must be retryable failures")
        elif (self.quota_retry_approval is None or self.cell.requested_model != "gemini-3.1-pro"
              or len(preceding) != 1 or preceding[0].outcome != "nonretryable_failure"
              or preceding[0].failure_category != "quota_exhausted"):
            raise ValueError("quota Judgment v2 requires one preserved quota failure and its approval reference")

        required_observed_model = self.cell.required_observed_model
        if required_observed_model is None:
            raise ValueError("recovery cell must declare its required observed model")
        route = next(row["provider_route"] for row in _formal._expected_routes() if row["requested_model"] == self.cell.requested_model)
        for attempt in self.new_attempts:
            attempt_route = "moonshot_official" if official and attempt is self.new_attempts[-1] else route
            observed = "kimi-k3" if attempt_route == "moonshot_official" else required_observed_model
            if attempt.provider_route != attempt_route:
                raise ValueError("recovery attempt route differs from the frozen model route")
            if attempt.provider_response_count == 0:
                if (
                    attempt.outcome == "succeeded"
                    or attempt.observed_model_counts
                    or attempt.observed_model_missing_response_count
                    or attempt.observed_model_malformed_response_count
                    or attempt.usage_complete_response_count
                    or attempt.usage_missing_response_count
                    or attempt.usage_malformed_response_count
                    or any(
                        value is not None
                        for value in (
                            attempt.input_usage,
                            attempt.output_usage,
                            attempt.total_usage,
                            attempt.cached_input_usage,
                        )
                    )
                ):
                    raise ValueError("no-response recovery failures cannot manufacture response evidence")
                continue
            if (
                attempt.observed_model_counts != {observed: attempt.provider_response_count}
                or attempt.observed_model_missing_response_count
                or attempt.observed_model_malformed_response_count
                or attempt.usage_complete_response_count != attempt.provider_response_count
                or attempt.usage_missing_response_count
                or attempt.usage_malformed_response_count
            ):
                raise ValueError("new response evidence must have complete usage and the required model")

        payload = self.model_dump(mode="json")
        payload.pop("judgment_id")
        if self.judgment_id != _v2._json_sha256(payload):
            raise ValueError("recovery Judgment identity is crossed with its persisted facts")
        return self

    @property
    def successful_sequence_accounting(self) -> Any:
        """Accounting for the complete recovery sequence, excluding old attempts."""

        return _v2._variant_accounting_from_attempts(self.new_attempts)

    @property
    def historical_usage_accounting(self) -> dict[str, int | None]:
        """Complete totals plus explicitly separate known subtotals for old attempts."""

        result: dict[str, int | None] = {}
        for field in ("input_usage", "output_usage", "total_usage", "cached_input_usage"):
            values = [getattr(attempt, field) for attempt in self.historical_attempts]
            known = [value for value in values if value is not None]
            subtotal = sum(known) if known else None
            missing = any(
                attempt.provider_response_count > 0
                and attempt.usage_complete_response_count != attempt.provider_response_count
                for attempt in self.historical_attempts
            )
            result[field] = None if missing else subtotal
            result[f"{field}_known_subtotal"] = subtotal
        return result

    @property
    def observed_model(self) -> str:
        """Identity of the validated successful response, not the original cell label."""
        return next(iter(self.new_attempts[-1].observed_model_counts))

    def realized_projection(
        self,
        *,
        realization_source_identity: str,
    ) -> _v2._V2RealizedTerminal:
        """Project this recovery Judgment into the shared runtime terminal contract."""

        realization = EngagementRealizationPolicy(
            source_identity=realization_source_identity,
            realization_seed=REALIZATION_SEED,
            realization_rule_version=REALIZATION_RULE_VERSION,
        ).realize(
            self.decision,
            user_id=self.pair.user_id,
            message_id=self.pair.message_id,
        )
        payload: dict[str, object] = {
            "schema_version": _v2._V2_REALIZED_TERMINAL_SCHEMA,
            "judgment_id": self.judgment_id,
            "judgment_source_identity": self.judgment_source_identity,
            "realization_source_identity": realization_source_identity,
            "cell_index": self.cell_index,
            "cell_id": self.cell.cell_id,
            "pair_id": self.pair.pair_id,
            "pair_schedule_position": self.pair.pair_schedule_position,
            "time_step": self.pair.time_step,
            "message_id": self.pair.message_id,
            "user_id": self.pair.user_id,
            "prompt_variant": self.cell.prompt_variant,
            "prompt_version": self.cell.prompt_version,
            "prompt_canonical_hash": self.cell.prompt_canonical_hash,
            "requested_model": self.cell.requested_model,
            "observed_model": self.observed_model,
            "provider_engage": self.decision.engage,
            "provider_probability": self.decision.probability,
            "provider_action": self.decision.action,
            "provider_reason": self.decision.reason,
            "provider_confidence": self.decision.confidence,
            "provider_decision_source": self.decision.decision_source,
            "environmental_consciousness_prompt_inclusion": "included",
            "request_invocations": len(self.historical_attempts) + len(self.new_attempts),
            "realization_key": realization.realization_key,
            "realization_rule_version": REALIZATION_RULE_VERSION,
            "realization_seed": REALIZATION_SEED,
            "realization_status": realization.realization_status,
            "uniform_draw": realization.uniform_draw,
            "realized_engage": realization.realized_engage,
            "realized_action": realization.realized_action,
        }
        payload["realized_terminal_id"] = _v2._json_sha256(payload)
        return _v2._V2RealizedTerminal.model_validate(payload)


def build_recovery_judgment(
    *,
    cell_index: int,
    cell: _v2._PromptModelCell,
    plan: _PairExecutionPlan,
    decision: EngageDecision,
    historical_attempts: tuple[_v2._V2AttemptEvidence, ...],
    new_attempts: tuple[_v2._V2AttemptEvidence, ...],
    epoch_identity_sha256: str,
    judgment_source_identity: str,
    quota_retry_approval: dict[str, Any] | None = None,
    output_amendment_approval: dict[str, Any] | None = None,
    official_migration_approval: dict[str, Any] | None = None,
) -> RecoveryJudgmentV1:
    """Build and hash a recovery contract without rewriting old attempt ordinals."""

    pair = PairCoordinates(
        pair_id=plan.pair_id,
        pair_schedule_position=plan.pair_schedule_position,
        time_step=plan.time_step,
        message_id=plan.message.message_id,
        user_id=plan.user.user_id,
    )
    payload: dict[str, object] = {
        "schema_version": RECOVERY_JUDGMENT_V1_SCHEMA,
        "epoch_identity_sha256": epoch_identity_sha256,
        "judgment_source_identity": judgment_source_identity,
        "cell_index": cell_index,
        "cell": cell.model_dump(mode="json"),
        "pair": pair.model_dump(mode="json"),
        "decision": decision.model_dump(mode="json"),
        "historical_attempts": [row.model_dump(mode="json") for row in historical_attempts],
        "new_attempts": [row.model_dump(mode="json") for row in new_attempts],
    }
    if quota_retry_approval is not None:
        payload["schema_version"] = "concurrent-recovery-provider-judgment-v2"
        payload["quota_retry_approval"] = quota_retry_approval
    if output_amendment_approval is not None:
        payload["schema_version"] = "concurrent-recovery-provider-judgment-v3"
        payload["output_amendment_approval"] = output_amendment_approval
    if official_migration_approval is not None:
        payload["schema_version"] = "concurrent-recovery-provider-judgment-v4"
        payload["official_migration_approval"] = official_migration_approval
    payload["judgment_id"] = _v2._json_sha256(payload)
    return RecoveryJudgmentV1.model_validate(payload)


__all__ = [
    "PairCoordinates",
    "RECOVERY_JUDGMENT_V1_SCHEMA",
    "RecoveryJudgmentV1",
    "build_recovery_judgment",
]
