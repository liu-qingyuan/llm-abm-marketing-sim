import json

from llm_abm_sim.outputs import build_graph_trace
from llm_abm_sim.runner import ExperimentRunner, load_simulation_input


def test_graph_trace_contains_nodes_edges_steps_and_timelines():
    config = load_simulation_input("configs/default.yaml")
    result = ExperimentRunner(config).run()

    trace = build_graph_trace(result, config)

    assert trace["schema_version"] == "graph-trace-v1"
    assert trace["run"]["run_id"] == "sample-run"
    assert trace["post"]["post_id"] == "p1"
    assert {node["id"] for node in trace["nodes"]} == {"u1", "u2", "u3"}
    assert {node["id"] for node in trace["nodes"] if node["is_seed"]} == {"u1"}
    assert {tuple(edge[key] for key in ("source", "target")) for edge in trace["edges"]} == {("u1", "u2"), ("u2", "u3")}
    assert [step["time_step"] for step in trace["steps"]] == [0, 1, 2, 3]

    u2 = next(node for node in trace["nodes"] if node["id"] == "u2")
    assert u2["timeline"][0]["state"] in {"unseen", "exposed", "engaged"}
    assert any(entry["exposures"] for entry in u2["timeline"])
    assert any(entry["decisions"] for entry in u2["timeline"])
    assert any("decision_source" in event["decision"] for event in trace["steps"][1]["decision_events"])


def test_run_outputs_write_redacted_graph_trace(tmp_path):
    output_dir = tmp_path / "run"
    ExperimentRunner.from_config_file("configs/default.yaml").run_and_write(
        output_dir, config_path="configs/default.yaml"
    )

    trace_path = output_dir / "graph_trace.json"
    assert trace_path.exists()
    trace = json.loads(trace_path.read_text())
    assert trace["nodes"]
    assert trace["steps"]
    assert "api_key" not in trace_path.read_text().lower()
