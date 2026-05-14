from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


class PostContent(BaseModel):
    """Marketing post to diffuse through the social graph."""

    post_id: str
    text: str
    topic_tags: list[str] = Field(default_factory=list)
    media_summary: str | None = None


class PlatformContext(BaseModel):
    """Platform-level context visible to the environment and decisions."""

    time_label: str | None = None
    hot_topics: list[str] = Field(default_factory=list)
    platform_mood: str | None = None
    feed_ranking_weight: float = Field(default=1.0, ge=0.0)
    trace_visibility: float = Field(default=1.0, ge=0.0, le=1.0)


class UserProfile(BaseModel):
    """Individual preference state for one social-media user agent."""

    user_id: str
    interest_tags: list[str] = Field(default_factory=list)
    brand_attitude: float = Field(default=0.0, ge=-1.0, le=1.0)
    activity_level: float = Field(default=0.5, ge=0.0, le=1.0)
    like_tendency: float = Field(default=0.5, ge=0.0, le=1.0)
    comment_tendency: float = Field(default=0.2, ge=0.0, le=1.0)
    share_tendency: float = Field(default=0.2, ge=0.0, le=1.0)


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
