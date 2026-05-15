from __future__ import annotations

import json
from pathlib import Path

from llm_abm_sim.runner import ExperimentRunner


def test_cli_outputs_include_product_artifacts_and_safe_trace(tmp_path: Path):
    output_dir = tmp_path / "sample"
    ExperimentRunner.from_config_file("configs/default.yaml").run_and_write(
        output_dir, config_path="configs/default.yaml"
    )

    expected = {
        "config.json",
        "run_result.json",
        "events.json",
        "metrics_summary.json",
        "step_records.csv",
        "graph_trace.json",
        "report_payload.json",
        "report.html",
        "input-builder.html",
    }
    assert expected.issubset({path.name for path in output_dir.iterdir()})
    metrics = json.loads((output_dir / "metrics_summary.json").read_text())
    assert metrics["decision_source_summary"]["rule_based"] > 0
    trace = json.loads((output_dir / "graph_trace.json").read_text())
    assert any(
        event.get("trace_summary", {}).get("input", {}).get("peer_context") is not None
        for step in trace["steps"]
        for event in step["decision_events"]
    )
    artifact_text = "\n".join(path.read_text(errors="ignore") for path in output_dir.iterdir() if path.is_file())
    assert "sk-" not in artifact_text.lower()
    assert "authorization" not in artifact_text.lower()


def test_realistic_dataset_report_includes_input_summary(tmp_path: Path):
    output_dir = tmp_path / "realistic"
    ExperimentRunner.from_config_file("configs/fixtures/realistic_marketing_dataset.yaml").run_and_write(
        output_dir, config_path="configs/fixtures/realistic_marketing_dataset.yaml"
    )
    report = (output_dir / "report.html").read_text(encoding="utf-8")
    assert (output_dir / "dataset_validation.json").exists()
    assert "Inputs Used" in report
    assert "Clean Glow refillable moisturizer" in report
    assert "Provider / Decision Source Evidence" in report
    payload = json.loads((output_dir / "report_payload.json").read_text())
    assert payload["inputs"]["profile_count"] >= 30
    assert payload["inputs"]["edge_count"] > 0
