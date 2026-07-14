"""LLM-supported ABM simulator for social-network post diffusion."""

from .agent import SocialUserAgent
from .decision import (
    CachedDecisionAdapter,
    DecisionCache,
    DecisionInput,
    EngageDecision,
    InMemoryDecisionCache,
    LLMDecisionAdapter,
    ProviderDecisionError,
    RuleBasedDecisionAdapter,
    RuleBasedDecisionConfig,
)
from .environment import PlatformEnvironment
from .events import ActionEvent, DecisionEvent, ExposureEvent, SimulationRunResult, StepRecord
from .final_research import FinalResearchConfig, FinalResearchRunner, ResearchUser, TargetVideo
from .final_research_report import rebuild_final_research_report
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
    "FinalResearchConfig",
    "FinalResearchRunner",
    "rebuild_final_research_report",
    "LLMDecisionAdapter",
    "ProviderDecisionError",
    "PlatformEnvironment",
    "ResearchUser",
    "RuleBasedDecisionAdapter",
    "RuleBasedDecisionConfig",
    "SimulationModel",
    "SimulationRunResult",
    "SocialUserAgent",
    "StepRecord",
    "TargetVideo",
]

__version__ = "0.1.0"
