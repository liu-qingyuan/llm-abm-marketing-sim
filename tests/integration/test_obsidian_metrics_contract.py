from pathlib import Path
from typing import cast

from llm_abm_sim.runner import ExperimentRunner


def test_sample_run_reports_obsidian_diffusion_metrics():
    result = ExperimentRunner.from_config_file(Path("configs/default.yaml")).run()
    summary = result.metrics_summary

    assert summary["final_exposed"] == 3
    assert summary["final_engaged"] == 3
    assert summary["diffusion_depth"] == 2
    assert cast(float, summary["spread_speed"]) > 0
    assert summary["key_influencers"] == ["u1", "u2"]
    assert summary["conversion_trend"] == {"0": 1, "1": 1, "2": 1, "3": 0}
    assert (
        cast(int, summary["like_count"])
        + cast(int, summary["comment_count"])
        + cast(int, summary["share_count"])
        == 3
    )
    actions = [event.decision.action for event in result.decision_events]
    assert set(actions) <= {"like", "comment", "share", "ignore"}
    assert actions == ["like", "like", "like"]
