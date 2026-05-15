"""LLM-supported ABM simulator for social-network post diffusion."""

from .agent import SocialUserAgent
from .decision import (
    CachedDecisionAdapter,
    DecisionCache,
    DecisionInput,
    EngageDecision,
    InMemoryDecisionCache,
    LLMDecisionAdapter,
    RuleBasedDecisionAdapter,
)
from .environment import PlatformEnvironment
from .events import ActionEvent, DecisionEvent, ExposureEvent, SimulationRunResult, StepRecord
from .model import SimulationModel
from .runner import ExperimentRunner
from .schemas import PlatformContext

__all__ = [
    "PlatformContext",
    "CachedDecisionAdapter",
    "InMemoryDecisionCache",
    "DecisionCache",
    "DecisionInput",
    "ActionEvent",
    "DecisionEvent",
    "EngageDecision",
    "ExperimentRunner",
    "ExposureEvent",
    "LLMDecisionAdapter",
    "PlatformEnvironment",
    "RuleBasedDecisionAdapter",
    "SimulationModel",
    "SimulationRunResult",
    "SocialUserAgent",
    "StepRecord",
]

__version__ = "0.1.0"
