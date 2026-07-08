import json
from pathlib import Path

from llm_abm_sim.decision import EngageDecision
from llm_abm_sim.outputs import copy_config_source
from llm_abm_sim.provider_config import (
    load_codex_provider_config,
    redact_secrets,
    resolve_runtime_credential,
    should_run_live_llm,
)


def write_codex_config(home: Path, requires_auth: bool = True) -> None:
    home.mkdir(exist_ok=True)
    (home / "config.toml").write_text(
        f"""
model = "gpt-5.5"
model_provider = "sub2api"

[model_providers.sub2api]
name = "sub2api"
base_url = "https://api.example.test"
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
    assert config.base_url == "https://api.example.test"
    assert config.wire_api == "responses"
    assert config.requires_openai_auth is True
    assert config.auth_available is True
    assert "secret" not in json.dumps(config.redacted())


def test_provider_metadata_url_redaction_strips_userinfo_query_and_fragment(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "config.toml").write_text(
        """
model = "gpt-5.5"
model_provider = "sub2api"

[model_providers.sub2api]
name = "sub2api"
base_url = "https://user:password@api.example.test/v1?api_key=secret#fragment"
wire_api = "responses"
requires_openai_auth = true
""",
        encoding="utf-8",
    )
    (tmp_path / "auth.json").write_text('{"tokens":{"access_token":"secret"}}')

    config = load_codex_provider_config(tmp_path)

    assert config is not None
    assert config.redacted()["base_url"] == "https://api.example.test/v1"
    serialized = json.dumps(config.redacted())
    assert "password" not in serialized
    assert "api_key=secret" not in serialized
    assert "fragment" not in serialized


def test_live_llm_gate_requires_explicit_opt_in_and_auth(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    write_codex_config(tmp_path)
    (tmp_path / "auth.json").write_text('{"OPENAI_API_KEY":"codex-secret"}', encoding="utf-8")

    monkeypatch.delenv("LLM_ABM_RUN_LIVE_LLM", raising=False)
    assert should_run_live_llm(tmp_path) is False

    monkeypatch.setenv("LLM_ABM_RUN_LIVE_LLM", "1")
    assert should_run_live_llm(tmp_path) is True


def test_codex_auth_fallback_requires_provider_flag(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    write_codex_config(tmp_path, requires_auth=False)
    (tmp_path / "auth.json").write_text('{"OPENAI_API_KEY":"codex-secret"}', encoding="utf-8")
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
        "action": "like",
    }

    decision = EngageDecision.model_validate(payload)

    assert decision.engage is True
    assert decision.probability == 0.73
    assert decision.confidence == 0.91
    assert decision.action == "like"


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


def test_resolve_runtime_credential_prefers_env_without_reading_codex(monkeypatch, tmp_path):
    write_codex_config(tmp_path)
    (tmp_path / "auth.json").write_text('{"OPENAI_API_KEY":"codex-secret"}', encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "env-secret")

    credential = resolve_runtime_credential(codex_home=tmp_path)

    assert credential is not None
    assert credential.value == "env-secret"
    assert credential.source == "env:OPENAI_API_KEY"
    assert "env-secret" not in repr(credential)


def test_resolve_runtime_credential_uses_codex_auth_only_for_openai_auth_provider(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    write_codex_config(tmp_path, requires_auth=True)
    (tmp_path / "auth.json").write_text('{"OPENAI_API_KEY":"codex-secret"}', encoding="utf-8")

    credential = resolve_runtime_credential(codex_home=tmp_path)

    assert credential is not None
    assert credential.value == "codex-secret"
    assert credential.source == "codex_auth"
    assert "codex-secret" not in repr(credential)


def test_resolve_runtime_credential_does_not_use_codex_auth_for_unscoped_provider(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    write_codex_config(tmp_path, requires_auth=False)
    (tmp_path / "auth.json").write_text('{"OPENAI_API_KEY":"codex-secret"}', encoding="utf-8")

    assert resolve_runtime_credential(codex_home=tmp_path) is None
