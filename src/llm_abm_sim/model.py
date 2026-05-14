from __future__ import annotations

from dataclasses import dataclass

from .agent import SocialUserAgent
from .decision import LLMDecisionAdapter
from .environment import PlatformEnvironment
from .metrics import MetricsCollector
from .schemas import PostContent


@dataclass
class SimulationModel:
    """Top-level ABM model for post diffusion over a social network."""

    post: PostContent
    agents: dict[str, SocialUserAgent]
    environment: PlatformEnvironment
    decision_adapter: LLMDecisionAdapter
    metrics: MetricsCollector

    def run(self, horizon: int) -> MetricsCollector:
        self.environment.seed_exposure()
        for user_id in self.environment.exposed_users:
            if user_id in self.agents:
                self.agents[user_id].exposed = True

        for time_step in range(horizon):
            self.step(time_step)
        return self.metrics

    def step(self, time_step: int) -> None:
        previous_engaged = len(self.environment.engaged_users)
        for user_id, agent in self.agents.items():
            peer_context = self.environment.peer_context_for(user_id)
            decision = agent.step(self.post, peer_context, self.decision_adapter)
            if decision and decision.engage:
                self.environment.engaged_users.add(user_id)
        self.environment.update_exposure(self.agents)
        self.metrics.record(
            time_step=time_step,
            exposed_count=len(self.environment.exposed_users),
            engaged_count=len(self.environment.engaged_users),
            previous_engaged_count=previous_engaged,
        )
