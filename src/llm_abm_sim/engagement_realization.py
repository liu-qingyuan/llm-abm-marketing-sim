from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .decision import EngageDecision, EngagementAction

REALIZATION_RULE_VERSION = "sha256-source-user-message-first-53-bits-uniform-v1"
REALIZATION_SEED = 20260823
FULL_POOL_REALIZED_TERMINAL_SCHEMA = "full-pool-realized-terminal-v1"

RealizationStatus = Literal["provider_ignore", "draw_pass", "draw_fail"]
REALIZED_TERMINAL_FIELDS = (
    "realized_terminal_id",
    "upstream_source_identity",
    "upstream_terminal_row_id",
    "upstream_pair_id",
    "realization_key",
    "replay_pair_id",
    "replay_pair_schedule_position",
    "replay_time_step",
    "message_id",
    "user_id",
    "provider_engage",
    "provider_probability",
    "provider_action",
    "provider_reason",
    "provider_confidence",
    "provider_decision_source",
    "prompt_version",
    "environmental_consciousness_prompt_inclusion",
    "realization_rule_version",
    "realization_seed",
    "realization_status",
    "uniform_draw",
    "realized_engage",
    "realized_action",
)


@dataclass(frozen=True)
class EngagementRealization:
    """Observable ABM outcome for one validated Provider Judgment."""

    realization_key: str
    realization_status: RealizationStatus
    uniform_draw: float | None
    realized_engage: bool
    realized_action: EngagementAction


@dataclass(frozen=True)
class EngagementRealizationPolicy:
    """Own the stable key, draw, and action rules at the judgment-to-commit seam."""

    source_identity: str
    realization_seed: int = REALIZATION_SEED
    realization_rule_version: str = REALIZATION_RULE_VERSION

    def __post_init__(self) -> None:
        _identity_part(self.source_identity, "source_identity")
        if self.realization_seed != REALIZATION_SEED or isinstance(self.realization_seed, bool):
            raise ValueError(f"realization_seed must be the frozen value {REALIZATION_SEED}")
        if self.realization_rule_version != REALIZATION_RULE_VERSION:
            raise ValueError("realization_rule_version is unsupported")

    def realize(
        self,
        judgment: EngageDecision,
        *,
        user_id: str,
        message_id: str,
    ) -> EngagementRealization:
        """Realize one Provider Judgment without inventing an action or a reason."""

        user = _identity_part(user_id, "user_id")
        message = _identity_part(message_id, "message_id")
        key = _realization_key(
            source_identity=self.source_identity,
            user_id=user,
            message_id=message,
        )
        if not math.isfinite(judgment.probability):
            raise ValueError("Provider probability must be finite")
        if not judgment.engage:
            return EngagementRealization(
                realization_key=key,
                realization_status="provider_ignore",
                uniform_draw=None,
                realized_engage=False,
                realized_action="ignore",
            )

        draw = _uniform_draw(seed=self.realization_seed, realization_key=key)
        if draw < judgment.probability:
            return EngagementRealization(
                realization_key=key,
                realization_status="draw_pass",
                uniform_draw=draw,
                realized_engage=True,
                realized_action=judgment.action,
            )
        return EngagementRealization(
            realization_key=key,
            realization_status="draw_fail",
            uniform_draw=draw,
            realized_engage=False,
            realized_action="ignore",
        )


class FullPoolRealizedTerminal(BaseModel):
    """Exact persisted Provider-Judgment plus ABM-Realization terminal contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    realized_terminal_id: str
    upstream_source_identity: str
    upstream_terminal_row_id: str
    upstream_pair_id: str
    realization_key: str
    replay_pair_id: str
    replay_pair_schedule_position: int = Field(ge=0)
    replay_time_step: int = Field(ge=0)
    message_id: str
    user_id: str
    provider_engage: bool
    provider_probability: float = Field(ge=0.0, le=1.0)
    provider_action: EngagementAction
    provider_reason: str
    provider_confidence: float = Field(ge=0.0, le=1.0)
    provider_decision_source: str
    prompt_version: str
    environmental_consciousness_prompt_inclusion: Literal["included"]
    realization_rule_version: Literal[
        "sha256-source-user-message-first-53-bits-uniform-v1"
    ]
    realization_seed: Literal[20260823]
    realization_status: RealizationStatus
    uniform_draw: float | None = Field(default=None, ge=0.0, lt=1.0)
    realized_engage: bool
    realized_action: EngagementAction

    @field_validator(
        "realized_terminal_id",
        "upstream_source_identity",
        "upstream_terminal_row_id",
        "upstream_pair_id",
        "replay_pair_id",
        "message_id",
        "user_id",
        "provider_decision_source",
        "prompt_version",
    )
    @classmethod
    def _non_empty_identity(cls, value: str) -> str:
        return _identity_part(value, "realized terminal identity")

    @field_validator("provider_probability", "provider_confidence", "uniform_draw")
    @classmethod
    def _finite_number(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("realized terminal numbers must be finite")
        return value

    @model_validator(mode="after")
    def _validate_realization_invariants(self) -> FullPoolRealizedTerminal:
        expected_key = _realization_key(
            source_identity=self.upstream_source_identity,
            user_id=self.user_id,
            message_id=self.message_id,
        )
        if self.realization_key != expected_key:
            raise ValueError("realization_key is crossed with source, user, or message identity")
        if self.replay_pair_id != f"{self.user_id}:{self.message_id}:{self.replay_time_step}":
            raise ValueError("replay_pair_id is crossed with user, message, or replay time step")
        if self.provider_engage != (self.provider_action != "ignore"):
            raise ValueError("Provider engage and action are inconsistent")

        if self.realization_status == "provider_ignore":
            if (
                self.provider_engage
                or self.uniform_draw is not None
                or self.realized_engage
                or self.realized_action != "ignore"
            ):
                raise ValueError("provider_ignore must remain ignore without a draw")
            return self

        if not self.provider_engage or self.provider_action == "ignore" or self.uniform_draw is None:
            raise ValueError("draw outcomes require one positive Provider Judgment and a draw")
        expected_draw = _uniform_draw(
            seed=self.realization_seed,
            realization_key=self.realization_key,
        )
        if self.uniform_draw != expected_draw:
            raise ValueError("uniform_draw differs from the frozen realization vector")
        passed = self.uniform_draw < self.provider_probability
        if self.realization_status == "draw_pass":
            if not passed or not self.realized_engage or self.realized_action != self.provider_action:
                raise ValueError("draw_pass must preserve the positive Provider action")
        elif passed or self.realized_engage or self.realized_action != "ignore":
            raise ValueError("draw_fail must become ignore")
        return self

    def canonical_json_line(self) -> str:
        return (
            json.dumps(
                self.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        )


def _identity_part(value: str, context: str) -> str:
    if not isinstance(value, str) or not value or "\0" in value:
        raise ValueError(f"{context} must be a non-empty NUL-free string")
    return value


def _realization_key(*, source_identity: str, user_id: str, message_id: str) -> str:
    payload = b"\0".join(
        part.encode("utf-8") for part in (source_identity, user_id, message_id)
    )
    return hashlib.sha256(payload).hexdigest()


def _uniform_draw(*, seed: int, realization_key: str) -> float:
    digest = hashlib.sha256(f"{seed}\0{realization_key}".encode()).digest()
    first_53_bits = int.from_bytes(digest[:8], "big") >> 11
    return first_53_bits / float(1 << 53)
