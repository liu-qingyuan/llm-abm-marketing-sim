from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .decision import EngageDecision, EngagementAction
from .trace import DecisionTraceSummary


class ExposureEvent(BaseModel):
    """A user became exposed to the post at a simulation step."""

    time_step: int = Field(ge=0)
    user_id: str
    source_user_id: str | None = None
    probability: float | None = Field(default=None, ge=0.0, le=1.0)
    depth: int = Field(default=0, ge=0)
    channel: Literal["seed", "neighbor", "feed", "topic", "search"] = "neighbor"
    event_type: Literal["exposure"] = "exposure"


class DecisionEvent(BaseModel):
    """A decision adapter evaluated an exposed user."""

    time_step: int = Field(ge=0)
    user_id: str
    decision: EngageDecision
    trace_summary: DecisionTraceSummary | None = None
    event_type: Literal["decision"] = "decision"


class ActionEvent(BaseModel):
    """A user action that affects downstream diffusion."""

    time_step: int = Field(ge=0)
    user_id: str
    action: EngagementAction
    source_depth: int = Field(default=0, ge=0)
    event_type: Literal["action"] = "action"


class StepRecord(BaseModel):
    """Serializable summary for one simulation step."""

    time_step: int = Field(ge=0)
    exposed_count: int = Field(ge=0)
    engaged_count: int = Field(ge=0)
    new_exposed_count: int = Field(ge=0)
    new_engaged_count: int = Field(ge=0)
    exposure_events: list[ExposureEvent] = Field(default_factory=list)
    decision_events: list[DecisionEvent] = Field(default_factory=list)
    action_events: list[ActionEvent] = Field(default_factory=list)


class SimulationRunResult(BaseModel):
    """Structured output for one complete simulation run."""

    run_id: str
    random_seed: int
    horizon: int = Field(ge=1)
    step_records: list[StepRecord]
    metrics_summary: dict[str, float | int | list[str] | dict[str, int]]

    @property
    def exposure_events(self) -> list[ExposureEvent]:
        return [event for step in self.step_records for event in step.exposure_events]

    @property
    def decision_events(self) -> list[DecisionEvent]:
        return [event for step in self.step_records for event in step.decision_events]

    @property
    def action_events(self) -> list[ActionEvent]:
        return [event for step in self.step_records for event in step.action_events]
