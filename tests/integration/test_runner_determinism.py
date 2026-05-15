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


def test_runner_loads_toy_dataset_fixture_with_config_relative_paths():
    runner = ExperimentRunner.from_config_file(Path("configs/fixtures/toy_dataset.yaml"))

    first = runner.run()
    report = runner.dataset_validation_report
    second = ExperimentRunner.from_config_file(Path("configs/fixtures/toy_dataset.yaml")).run()

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.run_id == "toy-dataset"
    assert first.metrics_summary == {
        "comment_count": 0,
        "conversion_trend": {"0": 1, "1": 1, "2": 1, "3": 1},
        "diffusion_depth": 2,
        "engagement_rate": 1.0,
        "final_engaged": 4,
        "final_exposed": 4,
        "key_influencers": ["u1", "u2"],
        "like_count": 4,
        "reach_rate": 1.0,
        "share_count": 0,
        "spread_speed": 0.75,
        "total_agents": 4,
    }
    assert report is not None
    assert report.dataset_used is True
    assert report.directed is True
    assert report.graph_node_count == 4
    assert report.graph_edge_count == 4
    assert report.profile_record_count == 4
    assert report.profile_count == 4
    assert report.missing_profile_ids == []
    assert report.extra_profile_ids == []
    assert report.edge_weight_column == "influence_weight"
    assert report.edge_attribute_columns == ["relationship", "touchpoint"]
    assert report.edge_list_path is not None
    assert Path(report.edge_list_path).is_absolute()
    assert Path(report.edge_list_path).name == "toy_edges.csv"
    assert report.profile_path is not None
    assert Path(report.profile_path).is_absolute()
    assert Path(report.profile_path).name == "toy_profiles.csv"


def test_runner_loads_realistic_marketing_dataset_deterministically():
    config = Path("configs/fixtures/realistic_marketing_dataset.yaml")
    first_runner = ExperimentRunner.from_config_file(config)
    first = first_runner.run()
    second_runner = ExperimentRunner.from_config_file(config)
    second = second_runner.run()

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.run_id == "realistic-marketing-dataset"
    assert first.metrics_summary["total_agents"] == 36
    assert first.metrics_summary["final_exposed"] >= 20
    assert first.metrics_summary["final_engaged"] >= 10
    assert first.metrics_summary["diffusion_depth"] >= 3
    report = first_runner.dataset_validation_report
    assert report is not None
    assert report.graph_node_count == 36
    assert report.graph_edge_count == 45
    assert report.profile_record_count == 36
    assert report.covered_seed_user_ids == ["u01", "u11", "u19", "u29"]
    assert report.missing_seed_user_ids == []
    assert "community" in report.preserved_profile_attribute_columns
    assert "touchpoint" in report.edge_attribute_columns
