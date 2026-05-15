from __future__ import annotations

import json
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
        return EngageDecision(
            engage=True,
            probability=0.99,
            reason="mocked_provider",
            confidence=1.0,
            action="like",
            decision_source="provider",
            provider_metadata={
                "provider": "mock",
                "model": "mock-model",
                "base_url": "https://user:pass@example.test/v1?api_key=secret",
                "headers": {"authorization": "Bearer sk-secret"},
                "raw_provider_response": {"token": "sk-secret"},
                "adapter": "mock",
                "adapter_version": "test-v1",
                "wire_api": "responses",
                "prompt_version": "mock-v1",
            },
        )


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


def test_mocked_provider_run_writes_allowlisted_redacted_artifacts(tmp_path: Path):
    config = load_simulation_input(Path("configs/default.yaml"))
    config = config.model_copy(update={"provider_llm": config.provider_llm.model_copy(update={"enabled": True})})
    output_dir = tmp_path / "mock-provider"

    ExperimentRunner(config, decision_adapter=AlwaysLikeAdapter()).run_and_write(output_dir)

    metrics = json.loads((output_dir / "metrics_summary.json").read_text())
    assert metrics["decision_source_summary"]["provider"] > 0
    evidence = metrics["provider_evidence"]
    assert evidence["provider_decision_count"] > 0
    assert evidence["provider_metadata"]["base_url"] == "https://example.test/v1"
    artifact_text = "\n".join(path.read_text(errors="ignore") for path in output_dir.iterdir() if path.is_file())
    lowered = artifact_text.lower()
    assert "sk-secret" not in lowered
    assert "authorization" not in lowered
    assert "raw_provider_response" not in lowered
    assert "headers" not in lowered
    assert "provider-backed decision observed" in (output_dir / "report.html").read_text(encoding="utf-8")
