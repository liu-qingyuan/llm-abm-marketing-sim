from __future__ import annotations

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


class DatasetConfig(BaseModel):
    """Dataset inputs for a simulation run."""

    edge_list_path: str | None = None
    delimiter: str | None = None


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
