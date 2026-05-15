from __future__ import annotations

from dataclasses import dataclass, field

from .agent import SocialUserAgent
from .decision import LLMDecisionAdapter
from .environment import PlatformEnvironment
from .events import ActionEvent, DecisionEvent, ExposureEvent, SimulationRunResult, StepRecord
from .metrics import MetricsCollector
from .schemas import PlatformContext, PostContent
from .trace import build_decision_trace_summary


@dataclass
class SimulationModel:
    """Top-level ABM model for post diffusion over a social network."""

    post: PostContent
    agents: dict[str, SocialUserAgent]
    environment: PlatformEnvironment
    decision_adapter: LLMDecisionAdapter
    metrics: MetricsCollector
    platform_context: PlatformContext = field(default_factory=PlatformContext)
    run_id: str = "sample-run"
    random_seed: int = 42
    step_records: list[StepRecord] = field(default_factory=list)

    def run(self, horizon: int) -> SimulationRunResult:
        self.environment.platform_context = self.platform_context
        self.environment.post = self.post
        seed_events = self.environment.seed_exposure()
        for user_id in sorted(self.environment.exposed_users):
            if user_id in self.agents:
                self.agents[user_id].exposed = True

        for time_step in range(horizon):
            self.step(time_step, seed_events if time_step == 0 else [])

        return SimulationRunResult(
            run_id=self.run_id,
            random_seed=self.random_seed,
            horizon=horizon,
            step_records=self.step_records,
            metrics_summary=self.metrics.summary(total_agents=len(self.agents)),
        )

    def step(self, time_step: int, initial_exposures: list[ExposureEvent] | None = None) -> None:
        previous_exposed = len(self.environment.exposed_users)
        previous_engaged = len(self.environment.engaged_users)
        decision_events: list[DecisionEvent] = []
        action_events: list[ActionEvent] = []

        for user_id in sorted(self.agents):
            agent = self.agents[user_id]
            peer_context = self.environment.peer_context_for(user_id)
            decision = agent.step(
                self.post,
                peer_context,
                self.decision_adapter,
                platform_context=self.platform_context,
                time_step=time_step,
            )
            if decision is None:
                continue
            prompt_version = getattr(self.decision_adapter, "prompt_version", "engage-v1")
            decision_events.append(
                DecisionEvent(
                    time_step=time_step,
                    user_id=user_id,
                    decision=decision,
                    trace_summary=build_decision_trace_summary(
                        user_id=user_id,
                        post=self.post,
                        profile=agent.profile,
                        peer_context=peer_context,
                        platform_context=self.platform_context,
                        time_step=time_step,
                        decision=decision,
                        prompt_version=str(prompt_version),
                    ),
                )
            )
            self.environment.apply_action(user_id, decision.action)
            if decision.engage:
                agent.engaged = True
                action_events.append(
                    ActionEvent(
                        time_step=time_step,
                        user_id=user_id,
                        action=decision.action,
                        source_depth=self.environment.exposure_depths.get(user_id, 0),
                    )
                )

        exposure_events = list(initial_exposures or [])
        exposure_events.extend(self.environment.update_exposure(self.agents, time_step=time_step))
        step_metrics = self.metrics.record(
            time_step=time_step,
            exposed_count=len(self.environment.exposed_users),
            engaged_count=len(self.environment.engaged_users),
            previous_exposed_count=previous_exposed,
            previous_engaged_count=previous_engaged,
            exposure_events=exposure_events,
            action_events=action_events,
        )
        self.step_records.append(
            StepRecord(
                time_step=time_step,
                exposed_count=step_metrics.exposed_count,
                engaged_count=step_metrics.engaged_count,
                new_exposed_count=step_metrics.new_exposed_count,
                new_engaged_count=step_metrics.new_engaged_count,
                exposure_events=exposure_events,
                decision_events=decision_events,
                action_events=action_events,
            )
        )
