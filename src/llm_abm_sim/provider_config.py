from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

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
            "base_url": sanitize_url(self.base_url),
            "wire_api": self.wire_api,
            "model": self.model,
            "requires_openai_auth": self.requires_openai_auth,
            "auth_available": self.auth_available,
        }


@dataclass(frozen=True)
class RuntimeCredential:
    """Runtime-only credential container; never serialize or log the value."""

    value: str
    source: str

    def __repr__(self) -> str:  # pragma: no cover - defensive display guard.
        return f"RuntimeCredential(value=<redacted>, source={self.source!r})"


def _codex_home(codex_home: str | Path | None = None) -> Path:
    return Path(codex_home) if codex_home is not None else Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))


def load_codex_provider_config(codex_home: str | Path | None = None) -> CodexProviderConfig | None:
    """Load selected Codex provider metadata without reading or returning secret values."""

    home = _codex_home(codex_home)
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
    return CodexProviderConfig(
        provider_name=str(provider_name),
        base_url=str(provider.get("base_url", "")),
        wire_api=str(provider.get("wire_api", "")),
        model=data.get("model"),
        requires_openai_auth=requires_openai_auth,
        auth_available=_codex_auth_available(home) if requires_openai_auth else False,
    )


def should_run_live_llm(codex_home: str | Path | None = None) -> bool:
    """Return true only when the manual live gate is explicitly opted in and auth is available."""

    if os.environ.get("LLM_ABM_RUN_LIVE_LLM") != "1":
        return False
    if os.environ.get("OPENAI_API_KEY"):
        return True
    config = load_codex_provider_config(codex_home)
    return bool(config and config.requires_openai_auth and config.auth_available)


def resolve_runtime_credential(
    *,
    api_key_env: str = "OPENAI_API_KEY",
    codex_home: str | Path | None = None,
    codex_provider: CodexProviderConfig | None = None,
) -> RuntimeCredential | None:
    """Resolve one runtime credential without exposing it to config or artifacts.

    OPENAI_API_KEY remains the explicit fallback. Codex auth reuse is allowed
    only for the selected provider when `requires_openai_auth=true`, matching
    Codex's provider-scoping guardrail.
    """

    env_value = os.environ.get(api_key_env)
    if env_value:
        return RuntimeCredential(value=env_value, source=f"env:{api_key_env}")

    provider = codex_provider or load_codex_provider_config(codex_home)
    if not provider or not provider.requires_openai_auth:
        return None
    token = _read_codex_auth_token(_codex_home(codex_home))
    if not token:
        return None
    return RuntimeCredential(value=token, source="codex_auth")


def _codex_auth_available(home: Path) -> bool:
    return _read_codex_auth_token(home) is not None


def _read_codex_auth_token(home: Path) -> str | None:
    auth_path = home / "auth.json"
    if not auth_path.exists():
        return None
    try:
        payload = json.loads(auth_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    candidates = [
        payload.get("OPENAI_API_KEY") if isinstance(payload, dict) else None,
        payload.get("api_key") if isinstance(payload, dict) else None,
        payload.get("access_token") if isinstance(payload, dict) else None,
    ]
    if isinstance(payload, dict):
        tokens = payload.get("tokens")
        if isinstance(tokens, dict):
            candidates.extend([tokens.get("access_token"), tokens.get("id_token")])
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def sanitize_url(value: str | None) -> str | None:
    """Return URL scheme/host/path only, stripping query, fragment, and userinfo."""

    if not value:
        return value
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        return value.split("?", 1)[0].split("#", 1)[0]
    host = parsed.hostname or ""
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path.rstrip("/"), "", ""))


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
