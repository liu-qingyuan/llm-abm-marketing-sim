from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from .provider_config import redact_secrets, sanitize_url
from .provider_evidence import allowlisted_provider_evidence
from .schemas import LEGACY_DEMO_PRESET_FIELDS

FORBIDDEN_ARTIFACT_TERMS = (
    "authorization",
    "bearer ",
    "cookie",
    "headers",
    "raw_auth",
    "raw_prompt",
    "raw_provider_request",
    "raw_provider_response",
    "sk-",
)

_DROP_KEY_FRAGMENTS = (
    "authorization",
    "bio",
    "cookie",
    "headers",
    "nickname",
    "raw_auth",
    "raw payload",
    "raw_payload",
    "raw_prompt",
    "raw_provider",
    "signature",
    "credential_path",
)
_ALLOWED_USER_TEXT_FIELDS = frozenset({"bio", "nickname", "signature"})


def safe_data(value: Any) -> Any:
    """Convert Pydantic/native values into redacted JSON-safe artifact data."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return _artifact_scrub(redact_secrets(value))


def safe_json(value: Any, *, indent: int | None = 2, sort_keys: bool = True) -> str:
    """Serialize through the shared redaction path used by all artifacts."""

    return json.dumps(safe_data(value), indent=indent, sort_keys=sort_keys, ensure_ascii=False)


def safe_user_data(value: Any) -> Any:
    """Redact artifact data while preserving explicitly allowed processed user text."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return _artifact_scrub(redact_secrets(value), allowed_text_fields=_ALLOWED_USER_TEXT_FIELDS)


def safe_user_json(value: Any, *, indent: int | None = 2, sort_keys: bool = True) -> str:
    """Serialize processed/runtime user rows through their explicit field allowlist."""

    return json.dumps(safe_user_data(value), indent=indent, sort_keys=sort_keys, ensure_ascii=False)


def artifact_has_forbidden_terms(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in FORBIDDEN_ARTIFACT_TERMS)


def _artifact_scrub(value: Any, *, allowed_text_fields: frozenset[str] = frozenset()) -> Any:
    if isinstance(value, dict):
        scrubbed: dict[str, Any] = {}
        for key, item in value.items():
            lowered = key.lower()
            if key == "provider_metadata":
                scrubbed[key] = allowlisted_provider_evidence(item)
                continue
            if key in LEGACY_DEMO_PRESET_FIELDS:
                continue
            if key not in allowed_text_fields and any(fragment in lowered for fragment in _DROP_KEY_FRAGMENTS):
                continue
            if isinstance(item, str) and "url" in lowered:
                scrubbed[key] = sanitize_url(item.strip())
                continue
            scrubbed[key] = _artifact_scrub(item, allowed_text_fields=allowed_text_fields)
        return scrubbed
    if isinstance(value, list):
        return [_artifact_scrub(item, allowed_text_fields=allowed_text_fields) for item in value]
    return value
