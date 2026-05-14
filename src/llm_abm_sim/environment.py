from __future__ import annotations

import random
from dataclasses import dataclass, field

import networkx as nx

from .agent import SocialUserAgent
from .decision import EngagementAction
from .events import ExposureEvent
from .schemas import PeerContext, PlatformContext, PostContent, SimulationConfig


@dataclass
class PlatformEnvironment:
    """Platform exposure, visible traces, and peer-influence environment over a social graph."""

    graph: nx.Graph
    config: SimulationConfig
    rng: random.Random = field(default_factory=random.Random)
    platform_context: PlatformContext = field(default_factory=PlatformContext)
    post: PostContent | None = None
    exposed_users: set[str] = field(default_factory=set)
    engaged_users: set[str] = field(default_factory=set)
    exposure_depths: dict[str, int] = field(default_factory=dict)
    interaction_traces: dict[EngagementAction, set[str]] = field(
        default_factory=lambda: {"like": set(), "comment": set(), "share": set(), "ignore": set()}
    )

    def seed_exposure(self) -> list[ExposureEvent]:
        events: list[ExposureEvent] = []
        for user_id in sorted(self.config.seed_user_ids):
            if user_id not in self.exposed_users:
                self.exposed_users.add(user_id)
                self.exposure_depths[user_id] = 0
                events.append(
                    ExposureEvent(
                        time_step=0,
                        user_id=user_id,
                        source_user_id=None,
                        probability=1.0,
                        depth=0,
                        channel="seed",
                    )
                )
        return events

    def peer_context_for(self, user_id: str) -> PeerContext:
        neighbors = sorted(str(node) for node in self.graph.neighbors(user_id)) if user_id in self.graph else []
        exposed = [node for node in neighbors if node in self.exposed_users]
        engaged = [node for node in neighbors if node in self.engaged_users]
        visible_scale = self.platform_context.trace_visibility
        return PeerContext(
            exposed_neighbors=len(exposed),
            engaged_neighbors=len(engaged),
            influential_engaged_neighbors=len(engaged),
            visible_likes=round(len(self.interaction_traces["like"] & set(neighbors)) * visible_scale),
            visible_comments=round(len(self.interaction_traces["comment"] & set(neighbors)) * visible_scale),
            visible_shares=round(len(self.interaction_traces["share"] & set(neighbors)) * visible_scale),
        )

    def apply_action(self, user_id: str, action: EngagementAction) -> None:
        self.interaction_traces.setdefault(action, set()).add(user_id)
        if action != "ignore":
            self.engaged_users.add(user_id)

    def update_exposure(self, agents: dict[str, SocialUserAgent], time_step: int) -> list[ExposureEvent]:
        candidates: dict[str, list[str]] = {}
        spread_sources = self.engaged_users | self.interaction_traces.get("share", set())
        for user_id in sorted(spread_sources):
            if user_id in self.graph:
                for neighbor in sorted(str(n) for n in self.graph.neighbors(user_id)):
                    candidates.setdefault(neighbor, []).append(user_id)

        events: list[ExposureEvent] = []
        for user_id in sorted(candidates):
            if user_id in self.exposed_users or user_id not in agents:
                continue
            peer_context = self.peer_context_for(user_id)
            topic_boost = self._topic_boost()
            share_boost = self.config.share_exposure_boost * peer_context.visible_shares
            p = min(
                1.0,
                self.config.base_exposure_probability
                + self.config.peer_exposure_boost * peer_context.engaged_neighbors
                + topic_boost
                + share_boost,
            )
            if self.rng.random() < p:
                source = sorted(candidates[user_id])[0]
                depth = self.exposure_depths.get(source, 0) + 1
                self.exposed_users.add(user_id)
                self.exposure_depths[user_id] = depth
                agents[user_id].exposed = True
                events.append(
                    ExposureEvent(
                        time_step=time_step,
                        user_id=user_id,
                        source_user_id=source,
                        probability=round(p, 6),
                        depth=depth,
                        channel="neighbor",
                    )
                )
        return events

    def _topic_boost(self) -> float:
        if not self.post:
            return 0.0
        if set(self.post.topic_tags) & set(self.platform_context.hot_topics):
            return self.config.hot_topic_exposure_boost * self.platform_context.feed_ranking_weight
        return 0.0
