from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from llm_abm_sim.input_builder import builder_config_yaml, default_builder_input
from llm_abm_sim.provider_evidence import allowlisted_provider_evidence, provider_evidence
from llm_abm_sim.report_i18n import REPORT_I18N, REQUIRED_I18N_KEYS, validate_i18n_key_parity
from llm_abm_sim.report_payload import build_report_payload
from llm_abm_sim.runner import ExperimentRunner, load_simulation_input
from llm_abm_sim.schemas import ReportConfig, SimulationInput
from llm_abm_sim.trace import DecisionTraceSummary


def test_i18n_key_parity_and_metric_copy():
    validate_i18n_key_parity()
    assert set(REPORT_I18N["zh-CN"]) == REQUIRED_I18N_KEYS
    assert REPORT_I18N["en-US"]["metric.final_engaged.label"] == "Final Engaged"
    assert REPORT_I18N["zh-CN"]["metric.final_engaged.label"] == "最终互动"


def test_report_config_language_validation_and_backcompat():
    config = load_simulation_input("configs/default.yaml")
    assert config.report.default_language == "en-US"
    assert config.report.available_languages == ["en-US", "zh-CN"]
    assert ReportConfig(default_language="zh-CN").default_language == "zh-CN"
    with pytest.raises(ValidationError):
        ReportConfig(default_language="fr-FR")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        ReportConfig(available_languages=["en-US"])


def test_report_payload_is_sanitized_view_model_with_trace_schema():
    config = load_simulation_input("configs/default.yaml")
    result = ExperimentRunner(config).run()
    payload = build_report_payload(result, config)
    text = payload.model_dump_json()
    assert payload.schema_version == "report-payload-v1"
    assert payload.graph_trace["schema_version"] == "graph-trace-v1"
    assert "decision_source_summary" in payload.run or "decision_source_summary" in payload.graph_trace["run"]
    assert "api_key" not in text.lower()
    first_trace = next(
        event["trace_summary"]
        for step in payload.graph_trace["steps"]
        for event in step["decision_events"]
        if event.get("trace_summary")
    )
    summary = DecisionTraceSummary.model_validate(first_trace)
    assert summary.input.post["post_id"] == config.post.post_id
    assert summary.input.profile["user_id"] == summary.user_id
    assert "engagement_ratio" in summary.input.peer_context
    assert summary.output.action in {"ignore", "like", "comment", "share"}


def test_input_builder_default_config_round_trips(tmp_path: Path):
    yaml_text = builder_config_yaml()
    config_path = tmp_path / "builder.yaml"
    config_path.write_text(yaml_text, encoding="utf-8")
    loaded = load_simulation_input(config_path)
    typed_default = default_builder_input()
    assert loaded.run_id == typed_default.run_id
    assert loaded.post.post_id == "builder-post"
    assert loaded.provider_llm.enabled is False
    assert loaded.report.default_language == "en-US"
    SimulationInput.model_validate(loaded.model_dump(mode="json"))


def test_provider_evidence_allowlist_drops_forbidden_fields():
    raw = {
        "provider_decision_count": 1,
        "decision_source_summary": {"provider": 1},
        "provider_metadata": {
            "provider": "mock",
            "base_url": "https://user:pass@example.test/v1?token=secret",
            "model": "mock-model",
            "headers": {"authorization": "Bearer sk-secret"},
            "raw_prompt": "secret prompt",
            "raw_provider_response": {"token": "sk-secret"},
            "credential_path": "/Users/me/.codex/auth.json",
            "adapter": "mock-adapter",
            "adapter_version": "test-v1",
            "wire_api": "responses",
            "prompt_version": "engage-provider-v1",
        },
    }
    safe = allowlisted_provider_evidence(raw)
    text = json.dumps(safe, sort_keys=True).lower()
    assert safe["provider_metadata"]["base_url"] == "https://example.test/v1"
    assert "headers" not in text
    assert "raw_prompt" not in text
    assert "raw_provider_response" not in text
    assert "credential_path" not in text
    assert "sk-secret" not in text


def test_provider_evidence_from_default_run_is_absent_without_provider():
    config = load_simulation_input("configs/default.yaml")
    result = ExperimentRunner(config).run()
    assert provider_evidence(result) is None
