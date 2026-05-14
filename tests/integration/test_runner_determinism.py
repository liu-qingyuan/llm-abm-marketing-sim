from pathlib import Path

from llm_abm_sim.runner import ExperimentRunner


def test_runner_produces_identical_events_for_fixed_seed():
    config = Path("configs/default.yaml")
    first = ExperimentRunner.from_config_file(config).run()
    second = ExperimentRunner.from_config_file(config).run()

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.run_id == "sample-run"
    assert first.metrics_summary["final_exposed"] == 3
    assert first.metrics_summary["final_engaged"] >= 1
