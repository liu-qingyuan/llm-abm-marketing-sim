from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomllib

SECRET_KEYS = ("api_key", "token", "secret", "password", "credential", "auth", "bearer")
SAFE_METADATA_KEYS = {"api_key_env", "requires_openai_auth", "auth_available"}


@dataclass(frozen=True)
class CodexProviderConfig:
    """Secret-free Codex-compatible provider metadata for manual live gates."""

    provider_name: str
    base_url: str
    wire_api: str
    model: str | None
    requires_openai_auth: bool
    auth_available: bool

    def redacted(self) -> dict[str, Any]:
        return {
            "provider_name": self.provider_name,
            "base_url": self.base_url,
            "wire_api": self.wire_api,
            "model": self.model,
            "requires_openai_auth": self.requires_openai_auth,
            "auth_available": self.auth_available,
        }


def load_codex_provider_config(codex_home: str | Path | None = None) -> CodexProviderConfig | None:
    """Load selected Codex provider metadata without reading or returning secret values."""

    home = Path(codex_home) if codex_home is not None else Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    config_path = home / "config.toml"
    if not config_path.exists():
        return None

    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    provider_name = data.get("model_provider")
    providers = data.get("model_providers") or {}
    if not provider_name or provider_name not in providers:
        return None
    provider = providers[provider_name]
    requires_openai_auth = bool(provider.get("requires_openai_auth", False))
    auth_available = requires_openai_auth and (home / "auth.json").exists()
    return CodexProviderConfig(
        provider_name=str(provider_name),
        base_url=str(provider.get("base_url", "")),
        wire_api=str(provider.get("wire_api", "")),
        model=data.get("model"),
        requires_openai_auth=requires_openai_auth,
        auth_available=auth_available,
    )


def should_run_live_llm(codex_home: str | Path | None = None) -> bool:
    """Return true only when the manual live gate is explicitly opted in and auth is available."""

    if os.environ.get("LLM_ABM_RUN_LIVE_LLM") != "1":
        return False
    if os.environ.get("OPENAI_API_KEY"):
        return True
    config = load_codex_provider_config(codex_home)
    return bool(config and config.requires_openai_auth and config.auth_available)


def redact_secrets(value: Any) -> Any:
    """Recursively redact common secret-bearing keys and bearer-like values."""

    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if key.lower() not in SAFE_METADATA_KEYS and any(secret in key.lower() for secret in SECRET_KEYS):
                redacted[key] = "<redacted>"
            else:
                redacted[key] = redact_secrets(item)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str) and ("Bearer " in value or value.startswith("sk-")):
        return "<redacted>"
    return value


def redacted_json(value: Any) -> str:
    return json.dumps(redact_secrets(value), indent=2, sort_keys=True)
