import json
import subprocess
import sys


def test_cli_writes_offline_run_artifacts(tmp_path):
    output_dir = tmp_path / "sample-run"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "llm_abm_sim.run",
            "--config",
            "configs/default.yaml",
            "--output",
            str(output_dir),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert str(output_dir) in completed.stdout
    expected = {
        "config.json",
        "default.yaml",
        "run_result.json",
        "metrics_summary.json",
        "step_records.csv",
        "events.json",
        "graph_trace.json",
        "report.html",
    }
    assert expected.issubset({path.name for path in output_dir.iterdir()})
    result = json.loads((output_dir / "run_result.json").read_text())
    assert result["run_id"] == "sample-run"
    assert result["step_records"]
    assert "LLM-ABM Simulation Report" in (output_dir / "report.html").read_text()
    trace = json.loads((output_dir / "graph_trace.json").read_text())
    assert trace["schema_version"] == "graph-trace-v1"
    assert trace["nodes"] and trace["steps"]


def test_cli_writes_dataset_validation_for_toy_dataset_fixture(tmp_path):
    output_dir = tmp_path / "toy-dataset"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "llm_abm_sim.run",
            "--config",
            "configs/fixtures/toy_dataset.yaml",
            "--output",
            str(output_dir),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert str(output_dir) in completed.stdout
    expected = {
        "config.json",
        "toy_dataset.yaml",
        "run_result.json",
        "metrics_summary.json",
        "step_records.csv",
        "events.json",
        "graph_trace.json",
        "report.html",
        "dataset_validation.json",
    }
    assert expected.issubset({path.name for path in output_dir.iterdir()})

    validation = json.loads((output_dir / "dataset_validation.json").read_text())
    assert validation["dataset_used"] is True
    assert validation["directed"] is True
    assert validation["graph_node_count"] == 4
    assert validation["graph_edge_count"] == 4
    assert validation["profile_record_count"] == 4
    assert validation["profile_count"] == 4
    assert validation["missing_profile_ids"] == []
    assert validation["extra_profile_ids"] == []
    assert validation["missing_profile_policy"] == "error"
    assert validation["extra_profile_policy"] == "error"
    assert validation["edge_weight_column"] == "influence_weight"
    assert validation["edge_attribute_columns"] == ["relationship", "touchpoint"]
    assert validation["edge_list_path"].endswith("tests/fixtures/datasets/toy_edges.csv")
    assert validation["profile_path"].endswith("tests/fixtures/datasets/toy_profiles.csv")

    metrics = json.loads((output_dir / "metrics_summary.json").read_text())
    assert metrics["final_exposed"] == 4
    assert metrics["final_engaged"] == 4
    assert metrics["diffusion_depth"] == 2
    assert metrics["key_influencers"] == ["u1", "u2"]

    events = json.loads((output_dir / "events.json").read_text())
    assert [event["user_id"] for event in events["exposure_events"]] == ["u1", "u2", "u3", "u4"]
    assert events["exposure_events"][1]["source_user_id"] == "u1"
    assert events["exposure_events"][-1]["source_user_id"] == "u2"
    assert "LLM-ABM Toy Dataset Fixture Report" in (output_dir / "report.html").read_text()


def test_cli_writes_realistic_marketing_dataset_artifacts(tmp_path):
    output_dir = tmp_path / "realistic-marketing-dataset"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "llm_abm_sim.run",
            "--config",
            "configs/fixtures/realistic_marketing_dataset.yaml",
            "--output",
            str(output_dir),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert str(output_dir) in completed.stdout
    expected = {
        "config.json",
        "realistic_marketing_dataset.yaml",
        "dataset_validation.json",
        "run_result.json",
        "events.json",
        "metrics_summary.json",
        "step_records.csv",
        "graph_trace.json",
        "report.html",
    }
    assert expected.issubset({path.name for path in output_dir.iterdir()})

    validation = json.loads((output_dir / "dataset_validation.json").read_text())
    assert validation["graph_node_count"] == 36
    assert validation["graph_edge_count"] == 45
    assert validation["profile_record_count"] == 36
    assert validation["directed"] is True
    assert validation["covered_seed_user_ids"] == ["u01", "u11", "u19", "u29"]
    assert validation["missing_seed_user_ids"] == []
    assert validation["edge_weight_column"] == "influence_weight"
    assert "touchpoint" in validation["edge_attribute_columns"]
    assert "community" in validation["preserved_profile_attribute_columns"]
    assert validation["edge_list_path"].endswith("realistic_marketing_edges.csv")
    assert validation["profile_path"].endswith("realistic_marketing_profiles.csv")

    result = json.loads((output_dir / "run_result.json").read_text())
    metrics = json.loads((output_dir / "metrics_summary.json").read_text())
    events = json.loads((output_dir / "events.json").read_text())
    assert result["run_id"] == "realistic-marketing-dataset"
    assert metrics["total_agents"] == 36
    assert len(events["exposure_events"]) >= 20
    trace = json.loads((output_dir / "graph_trace.json").read_text())
    assert len(trace["nodes"]) == 36
    assert len(trace["edges"]) == 45
    assert len(trace["steps"]) == result["horizon"]
    assert "LLM-ABM Realistic Marketing Dataset Fixture Report" in (output_dir / "report.html").read_text()
