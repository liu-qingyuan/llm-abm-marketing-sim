"""LLM-supported ABM simulator for social-network post diffusion."""

from .agent import SocialUserAgent
from .concurrent_message_experiment import (
    ConcurrentMessageExperimentConfig,
    ConcurrentMessageExperimentRunner,
    ExperimentalMessageDefinition,
)
from .concurrent_message_report import rebuild_concurrent_message_report
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
from .final_research import FinalResearchConfig, FinalResearchModel, FinalResearchRunner, ResearchUser, TargetVideo
from .final_research_report import rebuild_final_research_report
from .model import SimulationModel
from .runner import ExperimentRunner
from .retention import (
    CacheEvidence,
    DuplicateEvidence,
    RetentionAuditResult,
    RetentionAuditor,
    RetentionEntry,
    RetentionEvidenceReference,
    RetentionManifest,
    audit_retention,
    load_retention_manifest,
    render_retention_report,
)
from .schemas import PlatformContext

__all__ = [
    "ConcurrentMessageExperimentConfig",
    "ConcurrentMessageExperimentRunner",
    "ExperimentalMessageDefinition",
    "PlatformContext",
    "CachedDecisionAdapter",
    "CacheEvidence",
    "InMemoryDecisionCache",
    "DecisionCache",
    "DecisionInput",
    "DuplicateEvidence",
    "ActionEvent",
    "DecisionEvent",
    "EngageDecision",
    "ExperimentRunner",
    "ExposureEvent",
    "FinalResearchConfig",
    "FinalResearchModel",
    "FinalResearchRunner",
    "RetentionAuditResult",
    "RetentionAuditor",
    "RetentionEntry",
    "RetentionEvidenceReference",
    "RetentionManifest",
    "rebuild_concurrent_message_report",
    "rebuild_final_research_report",
    "audit_retention",
    "load_retention_manifest",
    "render_retention_report",
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
