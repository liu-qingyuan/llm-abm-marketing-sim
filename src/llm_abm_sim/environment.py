from __future__ import annotations

import random
from dataclasses import dataclass, field

import networkx as nx

from .agent import SocialUserAgent
from .schemas import PeerContext, SimulationConfig


@dataclass
class PlatformEnvironment:
    """Platform exposure and peer-influence environment over a social graph."""

    graph: nx.Graph
    config: SimulationConfig
    exposed_users: set[str] = field(default_factory=set)
    engaged_users: set[str] = field(default_factory=set)

    def seed_exposure(self) -> None:
        self.exposed_users.update(self.config.seed_user_ids)

    def peer_context_for(self, user_id: str) -> PeerContext:
        neighbors = list(self.graph.neighbors(user_id)) if user_id in self.graph else []
        exposed = [node for node in neighbors if node in self.exposed_users]
        engaged = [node for node in neighbors if node in self.engaged_users]
        return PeerContext(
            exposed_neighbors=len(exposed),
            engaged_neighbors=len(engaged),
            influential_engaged_neighbors=len(engaged),
        )

    def update_exposure(self, agents: dict[str, SocialUserAgent]) -> None:
        candidates: set[str] = set()
        for user_id in self.engaged_users:
            if user_id in self.graph:
                candidates.update(str(n) for n in self.graph.neighbors(user_id))
        for user_id in candidates:
            if user_id in self.exposed_users or user_id not in agents:
                continue
            peer_context = self.peer_context_for(user_id)
            p = min(
                1.0,
                self.config.base_exposure_probability
                + self.config.peer_exposure_boost * peer_context.engaged_neighbors,
            )
            if random.random() < p:
                self.exposed_users.add(user_id)
                agents[user_id].exposed = True
