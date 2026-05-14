from __future__ import annotations

from pydantic import BaseModel, Field


class PostContent(BaseModel):
    """Marketing post to diffuse through the social graph."""

    post_id: str
    text: str
    topic_tags: list[str] = Field(default_factory=list)


class UserProfile(BaseModel):
    """Individual preference state for one social-media user agent."""

    user_id: str
    interest_tags: list[str] = Field(default_factory=list)
    brand_attitude: float = Field(default=0.0, ge=-1.0, le=1.0)
    activity_level: float = Field(default=0.5, ge=0.0, le=1.0)


class PeerContext(BaseModel):
    """Peer influence features visible to an agent during one time step."""

    engaged_neighbors: int = 0
    exposed_neighbors: int = 0
    influential_engaged_neighbors: int = 0

    @property
    def engagement_ratio(self) -> float:
        if self.exposed_neighbors <= 0:
            return 0.0
        return self.engaged_neighbors / self.exposed_neighbors


class SimulationConfig(BaseModel):
    """Config for one reproducible diffusion experiment."""

    horizon: int = Field(default=30, ge=1)
    seed_user_ids: list[str] = Field(default_factory=list)
    base_exposure_probability: float = Field(default=0.15, ge=0.0, le=1.0)
    peer_exposure_boost: float = Field(default=0.10, ge=0.0, le=1.0)
