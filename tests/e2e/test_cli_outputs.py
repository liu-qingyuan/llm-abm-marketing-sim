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
        "report.html",
    }
    assert expected.issubset({path.name for path in output_dir.iterdir()})
    result = json.loads((output_dir / "run_result.json").read_text())
    assert result["run_id"] == "sample-run"
    assert result["step_records"]
    assert "LLM-ABM Simulation Report" in (output_dir / "report.html").read_text()
