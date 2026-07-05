from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from .provider_config import sanitize_url

SupportedLanguage = Literal["en-US", "zh-CN"]
SUPPORTED_LANGUAGES: tuple[SupportedLanguage, ...] = ("en-US", "zh-CN")
LatentClass = Literal["class_1", "class_2", "class_3"]
HotelClassLabel = Literal["economy", "midscale", "upper_midscale"]
TravelPurposeLabel = Literal["business", "leisure"]
GenderLabel = Literal["female", "male"]
AgeLabel = Literal["age_18_25", "age_26_35", "age_36_45", "age_46_55", "age_56_plus"]
EducationLabel = Literal["high_school_or_below", "community_college", "bachelor", "master_or_above"]
MonthlyIncomeLabel = Literal[
    "income_8000_or_less",
    "income_8001_15000",
    "income_15001_25000",
    "income_25001_40000",
    "income_40001_or_more",
]
LATENT_VALUE_DIMENSIONS: tuple[str, ...] = (
    "epistemic",
    "environmental",
    "functional",
    "health",
    "emotional",
    "social",
)
LATENT_PROFILE_LABEL_FIELDS: tuple[str, ...] = (
    "hotel_class",
    "travel_purpose",
    "gender",
    "age",
    "education",
    "monthly_income",
)


class ValueDimensions(BaseModel):
    """Consumption value salience declared by one marketing post."""

    model_config = ConfigDict(extra="forbid")

    epistemic: float = Field(default=0.0, ge=0.0, le=1.0)
    environmental: float = Field(default=0.0, ge=0.0, le=1.0)
    functional: float = Field(default=0.0, ge=0.0, le=1.0)
    health: float = Field(default=0.0, ge=0.0, le=1.0)
    emotional: float = Field(default=0.0, ge=0.0, le=1.0)
    social: float = Field(default=0.0, ge=0.0, le=1.0)


def default_available_languages() -> list[SupportedLanguage]:
    return ["en-US", "zh-CN"]


class PostContent(BaseModel):
    """Marketing post to diffuse through the social graph."""

    post_id: str
    text: str
    topic_tags: list[str] = Field(default_factory=list)
    media_summary: str | None = None
    value_dimensions: ValueDimensions = Field(default_factory=ValueDimensions)


class PlatformContext(BaseModel):
    """Platform-level context visible to the environment and decisions."""

    time_label: str | None = None
    hot_topics: list[str] = Field(default_factory=list)
    platform_mood: str | None = None
    feed_ranking_weight: float = Field(default=1.0, ge=0.0)
    trace_visibility: float = Field(default=1.0, ge=0.0, le=1.0)


class LatentValueWeights(BaseModel):
    """Consumer value weights assigned to one latent class."""

    model_config = ConfigDict(extra="forbid")

    epistemic: float
    environmental: float
    functional: float
    health: float
    emotional: float
    social: float


class LatentProfileLabels(BaseModel):
    """Virtual experiment profile labels for grouping latent-class users."""

    model_config = ConfigDict(extra="forbid")

    hotel_class: HotelClassLabel
    travel_purpose: TravelPurposeLabel
    gender: GenderLabel
    age: AgeLabel
    education: EducationLabel
    monthly_income: MonthlyIncomeLabel


class LatentAttributes(BaseModel):
    """Structured runtime contract for latent user attributes."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    spec_id: str
    method: str
    seed: int
    latent_class: LatentClass
    environmental_consciousness_coef: float
    value_weights: LatentValueWeights
    profile_labels: LatentProfileLabels = Field(validation_alias=AliasChoices("profile_labels", "class_profile"))

    @field_validator("spec_id", "method")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value


class UserProfile(BaseModel):
    """Individual preference state for one social-media user agent.

    Real dataset ingestion preserves additional public, non-secret profile
    attributes such as community, segment, locale, lifecycle stage, or follower
    counts so experiments can use richer local social-network datasets without
    expanding the simulator core schema for every column.
    """

    model_config = ConfigDict(extra="allow")

    user_id: str
    interest_tags: list[str] = Field(default_factory=list)
    brand_attitude: float = Field(default=0.0, ge=-1.0, le=1.0)
    activity_score: float = Field(default=0.5, ge=0.0, le=1.0)
    like_tendency: float = Field(default=0.5, ge=0.0, le=1.0)
    comment_tendency: float = Field(default=0.2, ge=0.0, le=1.0)
    share_tendency: float = Field(default=0.2, ge=0.0, le=1.0)
    latent_attributes: LatentAttributes | None = None


class PeerContext(BaseModel):
    """Peer influence features visible to an agent during one time step."""

    engaged_neighbors: int = 0
    exposed_neighbors: int = 0
    influential_engaged_neighbors: int = 0
    visible_likes: int = 0
    visible_comments: int = 0
    visible_shares: int = 0

    @property
    def engagement_ratio(self) -> float:
        if self.exposed_neighbors <= 0:
            return 0.0
        return self.engaged_neighbors / self.exposed_neighbors


class SimulationConfig(BaseModel):
    """Config for one reproducible diffusion experiment."""

    horizon: int = Field(default=30, ge=1)
    time_step_label: str = "step"
    observation_window: str | None = None
    seed_user_ids: list[str] = Field(default_factory=list)
    base_exposure_probability: float = Field(default=0.15, ge=0.0, le=1.0)
    peer_exposure_boost: float = Field(default=0.10, ge=0.0, le=1.0)
    hot_topic_exposure_boost: float = Field(default=0.0, ge=0.0, le=1.0)
    share_exposure_boost: float = Field(default=0.0, ge=0.0, le=1.0)


class RuleBasedDecisionConfig(BaseModel):
    """Local configuration for the deterministic rule-based decision adapter."""

    latent_value_weight: float = Field(default=0.0, ge=0.0, le=1.0)


class ProfileFormat(str, Enum):
    """Supported profile file encodings for dataset-backed runs."""

    CSV = "csv"
    JSON = "json"


class MissingProfilePolicy(str, Enum):
    """How dataset loading should handle graph nodes without profile rows."""

    DEFAULT = "default"
    ERROR = "error"


class ExtraProfilePolicy(str, Enum):
    """How dataset loading should handle profile rows for IDs absent from the graph."""

    IGNORE = "ignore"
    INCLUDE_AS_NODE = "include_as_node"
    ERROR = "error"


class DatasetConfig(BaseModel):
    """Dataset inputs for a simulation run.

    Relative paths are resolved by ``load_simulation_input()`` against the
    directory containing the config file. Absolute paths are normalized.
    """

    edge_list_path: Path | None = None
    profile_path: Path | None = None
    profile_format: ProfileFormat | None = None
    delimiter: str | None = None
    directed: bool = False
    source_column: str | None = None
    target_column: str | None = None
    edge_weight_column: str | None = None
    edge_attribute_columns: list[str] = Field(default_factory=list)
    missing_profile_policy: MissingProfilePolicy = MissingProfilePolicy.DEFAULT
    extra_profile_policy: ExtraProfilePolicy = ExtraProfilePolicy.IGNORE

    @property
    def uses_files(self) -> bool:
        return self.edge_list_path is not None or self.profile_path is not None


class ReportConfig(BaseModel):
    """Output/report generation options."""

    title: str = "LLM-ABM Simulation Report"
    default_language: SupportedLanguage = "en-US"
    available_languages: list[SupportedLanguage] = Field(default_factory=default_available_languages)

    @field_validator("available_languages")
    @classmethod
    def _validate_languages(cls, value: list[SupportedLanguage]) -> list[SupportedLanguage]:
        if not value:
            raise ValueError("report.available_languages must not be empty")
        deduped = list(dict.fromkeys(value))
        for required in SUPPORTED_LANGUAGES:
            if required not in deduped:
                raise ValueError(f"report.available_languages must include {required}")
        return deduped


class FailClosedAction(str, Enum):
    """Provider failure behavior for explicitly enabled LLM adapters."""

    RAISE = "raise"
    NO_ENGAGE = "no_engage"
    SKIP_RUN = "skip_run"


class ProviderLLMConfig(BaseModel):
    """Optional provider-backed decision adapter configuration.

    Default values keep the simulator offline and deterministic. Real provider
    use requires ``enabled=true`` plus the live env gate unless tests inject a
    mocked client path.
    """

    enabled: bool = False
    provider: str = "openai_compatible"
    model: str | None = None
    base_url: str | None = None
    wire_api: str = "responses"
    use_codex_provider_config: bool = False
    require_live_env: bool = True
    api_key_env: str = "OPENAI_API_KEY"
    timeout_seconds: float = Field(default=30.0, gt=0.0)
    max_retries: int = Field(default=0, ge=0)
    fail_closed_action: FailClosedAction = FailClosedAction.RAISE
    prompt_version: str = "engage-provider-v1"

    def safe_metadata(self) -> dict[str, object]:
        """Return serialization-safe provider settings with no credentials."""

        return {
            "enabled": self.enabled,
            "provider": self.provider,
            "model": self.model,
            "base_url": sanitize_url(self.base_url),
            "wire_api": self.wire_api,
            "use_codex_provider_config": self.use_codex_provider_config,
            "require_live_env": self.require_live_env,
            "api_key_env": self.api_key_env,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "fail_closed_action": self.fail_closed_action.value,
            "prompt_version": self.prompt_version,
        }


class SimulationInput(BaseModel):
    """Full experiment input loaded from config."""

    run_id: str = "sample-run"
    random_seed: int = 42
    simulation: SimulationConfig = Field(default_factory=SimulationConfig)
    platform_context: PlatformContext = Field(default_factory=PlatformContext)
    post: PostContent = Field(
        default_factory=lambda: PostContent(
            post_id="sample-post",
            text="Sample marketing post",
            topic_tags=["marketing"],
        )
    )
    profiles: list[UserProfile] = Field(default_factory=list)
    graph_edges: list[tuple[str, str]] = Field(default_factory=list)
    dataset: DatasetConfig = Field(default_factory=DatasetConfig)
    report: ReportConfig = Field(default_factory=ReportConfig)
    rule_based_decision: RuleBasedDecisionConfig = Field(default_factory=RuleBasedDecisionConfig)
    provider_llm: ProviderLLMConfig = Field(default_factory=ProviderLLMConfig)
