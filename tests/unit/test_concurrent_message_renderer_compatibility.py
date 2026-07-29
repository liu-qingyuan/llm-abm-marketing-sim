from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from llm_abm_sim.concurrent_message_renderer import render_report
from llm_abm_sim.concurrent_message_report import ConcurrentMessageReportPayload

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "concurrent_message_renderer"
GOLDENS: dict[str, Any] = json.loads(
    (FIXTURE_DIR / "compatibility_goldens.json").read_text(encoding="utf-8")
)
VARIANTS = tuple(variant["name"] for variant in GOLDENS["variants"])


def _read_gzip(relative_path: str) -> bytes:
    with gzip.open(FIXTURE_DIR / relative_path, "rb") as stream:
        return stream.read()


def _variant(name: str) -> dict[str, str]:
    return next(variant for variant in GOLDENS["variants"] if variant["name"] == name)


@pytest.fixture(scope="module")
def formal_payload() -> ConcurrentMessageReportPayload:
    payload_bytes = _read_gzip(GOLDENS["payload"])
    return ConcurrentMessageReportPayload.model_validate_json(payload_bytes)


@pytest.mark.parametrize("variant_name", VARIANTS)
def test_fixed_formal_renderer_goldens_match_exact_bytes(
    formal_payload: ConcurrentMessageReportPayload,
    variant_name: str,
) -> None:
    variant = _variant(variant_name)
    expected_bytes = _read_gzip(variant["golden"])

    rendered = render_report(formal_payload, expected_sha256=variant["sha256"])

    assert rendered.encode("utf-8") == expected_bytes
    assert hashlib.sha256(expected_bytes).hexdigest() == variant["sha256"]


def test_default_render_is_bound_to_editorial_golden(
    formal_payload: ConcurrentMessageReportPayload,
) -> None:
    variant = _variant("editorial_default")
    expected_bytes = _read_gzip(variant["golden"])

    rendered = render_report(formal_payload)

    assert rendered.encode("utf-8") == expected_bytes
    assert hashlib.sha256(rendered.encode("utf-8")).hexdigest() == variant["sha256"]
    assert '<html lang="zh-CN">' in rendered
    assert 'data-testid="editorial-report"' in rendered


def test_unknown_formal_renderer_hash_fails_closed(
    formal_payload: ConcurrentMessageReportPayload,
) -> None:
    with pytest.raises(ValueError, match="no concurrent message renderer matched"):
        render_report(formal_payload, expected_sha256="0" * 64)
