from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from llm_abm_sim.web import create_app
from llm_abm_sim.web.service import MockProviderDecisionAdapter


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(artifact_root=tmp_path / "web"))


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _wait_for_terminal(client: TestClient, run_id: str) -> dict[str, object]:
    for _ in range(100):
        job = client.get(f"/api/runs/{run_id}").json()
        if job["state"] not in {"queued", "running"}:
            return job
        time.sleep(0.02)
    raise AssertionError(f"run did not finish: {job}")


def test_health_endpoint(tmp_path: Path):
    client = _client(tmp_path)
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "report.html" in payload["artifact_allowlist"]


def test_validate_upload_accepts_csv_and_filters_forbidden_profile_columns(tmp_path: Path):
    client = _client(tmp_path)
    users = _write(
        tmp_path / "users.csv",
        "user_id,interest_tags,brand_attitude,authorization,cookie,segment\n"
        "u1,eco,0.8,Bearer sk-secret,chocolate,A\n"
        "u2,beauty,0.4,secret-cookie,chip,B\n",
    )
    edges = _write(tmp_path / "edges.csv", "source,target,weight\nu1,u2,1.0\n")

    with users.open("rb") as users_handle, edges.open("rb") as edges_handle:
        response = client.post(
            "/api/datasets/validate",
            data={"seed_user_ids": "u1"},
            files={
                "users_file": ("users.csv", users_handle, "text/csv"),
                "edges_file": ("edges.csv", edges_handle, "text/csv"),
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is True
    report = payload["dataset_validation"]
    assert report["profile_count"] == 2
    assert report["graph_edge_count"] == 1
    assert "segment" in report["preserved_profile_attribute_columns"]
    serialized = json.dumps(payload).lower()
    assert "authorization" not in serialized
    assert "cookie" not in serialized
    assert "sk-secret" not in serialized


def test_validate_upload_accepts_edges_json_object_and_bare_list(tmp_path: Path):
    client = _client(tmp_path)
    users = _write(
        tmp_path / "users.json",
        json.dumps({"profiles": [{"user_id": "u1"}, {"user_id": "u2"}, {"user_id": "u3"}]}),
    )
    for filename, edge_payload in [
        ("edges-object.json", {"edges": [{"source": "u1", "target": "u2", "weight": 1.0}]}),
        ("edges-list.json", [{"source": "u2", "target": "u3", "relationship": "follow"}]),
    ]:
        edges = _write(tmp_path / filename, json.dumps(edge_payload))
        with users.open("rb") as users_handle, edges.open("rb") as edges_handle:
            response = client.post(
                "/api/datasets/validate",
                files={
                    "users_file": ("users.json", users_handle, "application/json"),
                    "edges_file": (filename, edges_handle, "application/json"),
                },
            )
        assert response.status_code == 200, response.text
        assert response.json()["dataset_validation"]["graph_edge_count"] == 1


def test_validate_invalid_missing_source_target_returns_actionable_error(tmp_path: Path):
    client = _client(tmp_path)
    users = _write(tmp_path / "users.csv", "user_id\nu1\n")
    edges = _write(tmp_path / "edges.json", json.dumps([{"source": "u1"}]))
    with users.open("rb") as users_handle, edges.open("rb") as edges_handle:
        response = client.post(
            "/api/datasets/validate",
            files={
                "users_file": ("users.csv", users_handle, "text/csv"),
                "edges_file": ("edges.json", edges_handle, "application/json"),
            },
        )
    assert response.status_code == 400
    assert "source/target" in response.json()["error"]["message"]


def test_provider_readiness_mock_and_product_blocked_without_live_gate(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("LLM_ABM_RUN_LIVE_LLM", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = _client(tmp_path)

    mock_response = client.get("/api/provider/readiness?mock_provider=true")
    assert mock_response.json()["state"] == "mock"

    product = client.get("/api/provider/readiness")
    assert product.status_code == 200
    assert product.json()["state"] == "blocked"
    serialized = json.dumps(product.json()).lower()
    assert "sk-" not in serialized
    assert "bearer" not in serialized


def test_product_run_blocks_when_provider_not_ready(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("LLM_ABM_RUN_LIVE_LLM", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = _client(tmp_path)
    job = client.post("/api/runs", json={"validation_id": "missing", "scenario": {"horizon": 1}}).json()
    assert job["state"] == "blocked"
    assert job["error"]["class"] == "ProviderReadinessBlocked"


def test_mock_provider_run_writes_artifacts_and_report_payload(tmp_path: Path):
    client = _client(tmp_path)
    forbidden_fragments = [
        "sk-hidden",
        "authorization",
        "cookie",
        "access_token",
        "token",
        "secret",
        "password",
        "credential",
        "raw_prompt",
        "raw_provider",
        "headers",
        "bearer",
        "sk-",
    ]
    users = _write(
        tmp_path / "users.csv",
        "user_id,interest_tags,brand_attitude,access_token,segment\nu1,eco,0.8,sk-hidden,A\nu2,eco,0.5,sk-hidden,B\n",
    )
    edges = _write(tmp_path / "edges.csv", "source,target,weight\nu1,u2,1.0\n")
    with users.open("rb") as users_handle, edges.open("rb") as edges_handle:
        validation = client.post(
            "/api/datasets/validate",
            data={"seed_user_ids": "u1"},
            files={
                "users_file": ("users.csv", users_handle, "text/csv"),
                "edges_file": ("edges.csv", edges_handle, "text/csv"),
            },
        ).json()

    run = client.post(
        "/api/runs",
        json={
            "validation_id": validation["validation_id"],
            "mock_provider": True,
            "scenario": {"post_text": "Eco launch", "topic_tags": "eco", "seed_user_ids": "u1", "horizon": 2},
        },
    ).json()

    run = _wait_for_terminal(client, str(run["run_id"]))
    assert run["state"] == "succeeded", run
    payload = client.get(f"/api/runs/{run['run_id']}/report-payload").json()
    assert payload["decision_source_summary"]["provider"] > 0
    assert payload["provider_evidence"]["provider_metadata"]["provider"] == "mock"
    assert payload["dataset_validation"]["graph_edge_count"] == 1
    serialized_payload = json.dumps(payload).lower()
    for forbidden in forbidden_fragments:
        assert forbidden not in serialized_payload
    artifact = client.get(f"/api/runs/{run['run_id']}/artifact/report.html")
    assert artifact.status_code == 200
    artifact_dir = Path(run["artifact_dir"])
    joined = "\n".join(path.read_text(errors="ignore") for path in artifact_dir.iterdir() if path.is_file()).lower()
    for forbidden in forbidden_fragments:
        assert forbidden not in joined


def test_run_api_uses_polling_job_contract(tmp_path: Path, monkeypatch):
    original_decide = MockProviderDecisionAdapter.decide

    def slow_decide(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        time.sleep(0.05)
        return original_decide(self, *args, **kwargs)

    monkeypatch.setattr(MockProviderDecisionAdapter, "decide", slow_decide)
    client = _client(tmp_path)
    users = _write(tmp_path / "users.csv", "user_id,interest_tags,brand_attitude\nu1,eco,0.8\nu2,eco,0.5\n")
    edges = _write(tmp_path / "edges.csv", "source,target,weight\nu1,u2,1.0\n")
    with users.open("rb") as users_handle, edges.open("rb") as edges_handle:
        validation = client.post(
            "/api/datasets/validate",
            data={"seed_user_ids": "u1"},
            files={
                "users_file": ("users.csv", users_handle, "text/csv"),
                "edges_file": ("edges.csv", edges_handle, "text/csv"),
            },
        ).json()

    job = client.post(
        "/api/runs",
        json={
            "validation_id": validation["validation_id"],
            "mock_provider": True,
            "scenario": {"post_text": "Eco launch", "topic_tags": "eco", "seed_user_ids": "u1", "horizon": 2},
        },
    ).json()

    assert job["state"] in {"queued", "running", "succeeded"}
    polled = _wait_for_terminal(client, str(job["run_id"]))
    assert polled["state"] == "succeeded"
    assert client.get(f"/api/runs/{job['run_id']}/report-payload").json()["decision_source_summary"]["provider"] > 0
