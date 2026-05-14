import json
from pathlib import Path

from llm_abm_sim.decision import EngageDecision
from llm_abm_sim.outputs import copy_config_source
from llm_abm_sim.provider_config import load_codex_provider_config, redact_secrets, should_run_live_llm


def write_codex_config(home: Path, requires_auth: bool = True) -> None:
    home.mkdir(exist_ok=True)
    (home / "config.toml").write_text(
        f"""
model = "gpt-5.5"
model_provider = "sub2api"

[model_providers.sub2api]
name = "sub2api"
base_url = "https://api.q1ngyuan.top"
wire_api = "responses"
requires_openai_auth = {str(requires_auth).lower()}
"""
    )


def test_load_codex_provider_config_metadata_without_secret_values(tmp_path):
    write_codex_config(tmp_path)
    (tmp_path / "auth.json").write_text('{"tokens":{"access_token":"secret"}}')

    config = load_codex_provider_config(tmp_path)

    assert config is not None
    assert config.provider_name == "sub2api"
    assert config.base_url == "https://api.q1ngyuan.top"
    assert config.wire_api == "responses"
    assert config.requires_openai_auth is True
    assert config.auth_available is True
    assert "secret" not in json.dumps(config.redacted())


def test_live_llm_gate_requires_explicit_opt_in_and_auth(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    write_codex_config(tmp_path)
    (tmp_path / "auth.json").write_text("{}")

    monkeypatch.delenv("LLM_ABM_RUN_LIVE_LLM", raising=False)
    assert should_run_live_llm(tmp_path) is False

    monkeypatch.setenv("LLM_ABM_RUN_LIVE_LLM", "1")
    assert should_run_live_llm(tmp_path) is True


def test_codex_auth_fallback_requires_provider_flag(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    write_codex_config(tmp_path, requires_auth=False)
    (tmp_path / "auth.json").write_text("{}")
    monkeypatch.setenv("LLM_ABM_RUN_LIVE_LLM", "1")

    assert should_run_live_llm(tmp_path) is False


def test_redact_secrets_recursively():
    payload = {
        "api_key": "sk-test",
        "nested": {"authorization": "Bearer token", "safe": "value"},
        "items": [{"refresh_token": "hidden"}],
    }

    assert redact_secrets(payload) == {
        "api_key": "<redacted>",
        "nested": {"authorization": "<redacted>", "safe": "value"},
        "items": [{"refresh_token": "<redacted>"}],
    }


def test_provider_shaped_response_validates_as_engage_decision():
    payload = {
        "engage": True,
        "probability": 0.73,
        "reason": "matches skincare interest and peer influence",
        "confidence": 0.91,
    }

    decision = EngageDecision.model_validate(payload)

    assert decision.engage is True
    assert decision.probability == 0.73
    assert decision.confidence == 0.91


def test_copy_config_source_redacts_secret_bearing_yaml(tmp_path):
    source = tmp_path / "provider.yaml"
    output = tmp_path / "out"
    output.mkdir()
    source.write_text(
        "provider_llm:\n  api_key: sk-raw-secret\n  api_key_env: OPENAI_API_KEY\n  nested:\n    access_token: hidden\n",
        encoding="utf-8",
    )

    copy_config_source(source, output)

    copied = (output / "provider.yaml").read_text(encoding="utf-8")
    assert "sk-raw-secret" not in copied
    assert "hidden" not in copied
    assert "OPENAI_API_KEY" in copied
    assert "<redacted>" in copied


def test_redact_preserves_allowlisted_provider_metadata_keys():
    payload = {"requires_openai_auth": True, "auth_available": False, "api_key_env": "OPENAI_API_KEY"}

    assert redact_secrets(payload) == payload
