from __future__ import annotations

from pathlib import Path

import pytest

from llm_abm_sim.decision import EngageDecision, LLMDecisionAdapter
from llm_abm_sim.runner import ExperimentRunner, load_simulation_input
from llm_abm_sim.schemas import PeerContext, PlatformContext, PostContent, UserProfile


class AlwaysLikeAdapter(LLMDecisionAdapter):
    def decide(
        self,
        post: PostContent,
        profile: UserProfile,
        peer_context: PeerContext,
        platform_context: PlatformContext | None = None,
        time_step: int = 0,
    ) -> EngageDecision:
        return EngageDecision(engage=True, probability=0.99, reason="mocked_provider", confidence=1.0, action="like")


def test_mocked_provider_adapter_runs_through_experiment_runner():
    config = load_simulation_input(Path("configs/default.yaml"))
    runner = ExperimentRunner(config, decision_adapter=AlwaysLikeAdapter())

    result = runner.run()

    assert result.metrics_summary["final_engaged"] == 3
    assert all(event.decision.reason == "mocked_provider" for event in result.decision_events)


def test_provider_skip_run_config_fails_before_partial_simulation():
    config = load_simulation_input(Path("configs/default.yaml"))
    config = config.model_copy(
        update={
            "provider_llm": config.provider_llm.model_copy(update={"enabled": True, "fail_closed_action": "skip_run"})
        }
    )
    runner = ExperimentRunner(config)

    with pytest.raises(RuntimeError, match="skip_run"):
        runner.run()
