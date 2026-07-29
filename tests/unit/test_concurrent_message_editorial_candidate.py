from __future__ import annotations

import gzip
import hashlib
from pathlib import Path

import pytest

from llm_abm_sim import concurrent_message_editorial_candidate as candidate
from llm_abm_sim.concurrent_message_renderer import _FIXED_ADAPTERS
from llm_abm_sim.concurrent_message_report import ConcurrentMessageReportPayload

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "concurrent_message_renderer"
ASSET_DIR = Path(__file__).resolve().parents[2] / "src" / "llm_abm_sim" / "report_assets"
SOURCE_DIR = Path(__file__).resolve().parents[2] / "docs" / "references" / "concurrent-message-editorial-ui-design"

_OLD_ASSET_HASHES = {
    "multi-message-mechanism-overview.webp": "b2733d4e1bd4bb7790b980f10588fa399cc0d5ddaf5a4a7a7c31faccaacaa0e0",
    "multi-message-mechanism-sample.webp": "2a95789abdbf14852233ddf2c900310bda3dc1f7c6ca43238af59df12cdb5839",
    "multi-message-mechanism-ranking.webp": "0dca58a1dad5c00d876f87217b45300b7b475f74ba9e79ecc23ff5dee4eef7bf",
    "multi-message-mechanism-decision.webp": "047b4999d3dfb7065697cdba7e6241d94c73a0afe110dcdd05c4ec5796eafcf7",
    "multi-message-mechanism-feedback.webp": "f7ac5a1d727b43f7ebe0fc63de36ee2163d7dc206320642015b50bf417207f97",
}

_EDITORIAL_ASSET_HASHES = {
    "editorial-mechanism-overview-v1.webp": "1ba062f0c8b1dea458c63f4b2eaa1a5c605e7c164051212330cab51c3c6b3806",
    "editorial-mechanism-sample-v1.webp": "d6738cae46fd3925af4f5d4375d978c0e170afd1435b16f0ad0baba4e8a598f8",
    "editorial-mechanism-exposure-ranking-v1.webp": "76a8361b5ad8e0448275d1b69815408ddac0463bef21f4f4677fbc8e7fd68613",
    "editorial-mechanism-llm-decision-v1.webp": "52f7f62b0a0969055c21fe46fb88ba158664c3e7aeb42ec2ba69db3c5bad4828",
    "editorial-mechanism-network-feedback-v1.webp": "3b15835acc900c446d72636638fcd884159ba0d1103bf014c90587b5cd4e8f37",
}



@pytest.fixture(scope="module")
def formal_payload() -> ConcurrentMessageReportPayload:
    with gzip.open(FIXTURE_DIR / "formal_report_payload.json.gz", "rb") as stream:
        return ConcurrentMessageReportPayload.model_validate_json(stream.read())


def test_editorial_catalog_has_zh_en_key_parity() -> None:
    assert set(candidate._EDITORIAL_CATALOG["zh-CN"]) == set(candidate._EDITORIAL_CATALOG["en-US"])
    assert candidate._EDITORIAL_DETAILS
    for detail in candidate._EDITORIAL_DETAILS.values():
        assert set(detail) == {"zh-CN", "en-US"}
        assert set(detail["zh-CN"]) == set(detail["en-US"])


def test_editorial_assets_are_versioned_packaged_and_nonblank() -> None:
    assert set(candidate._EDITORIAL_ASSET_CATALOG) == {
        "overview",
        "sample",
        "exposure-ranking",
        "llm-decision",
        "network-feedback",
    }
    for asset in candidate._EDITORIAL_ASSET_CATALOG.values():
        source_path = SOURCE_DIR / asset["source"]
        assert hashlib.sha256(source_path.read_bytes()).hexdigest() == asset["source_sha256"]
        path = ASSET_DIR / asset["file"]
        data = path.read_bytes()
        assert asset["version"] == "v1"
        assert path.name.endswith("-v1.webp")
        assert data.startswith(b"RIFF") and data[8:12] == b"WEBP"
        assert len(data) > 1_000
        assert hashlib.sha256(data).hexdigest() == _EDITORIAL_ASSET_HASHES[path.name]


def test_existing_compatibility_assets_remain_byte_identical() -> None:
    for file_name, expected_hash in _OLD_ASSET_HASHES.items():
        assert hashlib.sha256((ASSET_DIR / file_name).read_bytes()).hexdigest() == expected_hash


def test_editorial_candidate_is_deterministic_private_and_direct(formal_payload: ConcurrentMessageReportPayload) -> None:
    first = candidate._render_editorial_candidate(formal_payload)
    second = candidate._render_editorial_candidate(formal_payload)

    assert first == second
    assert '<html lang="zh-CN">' in first
    assert 'data-report-mode="mechanism"' in first
    assert 'data-drawer-state="closed"' in first
    assert first.count('data-section-anchor="overview"') >= 2
    assert all(f'data-section-anchor="{anchor}"' in first for anchor in candidate._EDITORIAL_ANCHORS)
    assert all(asset["file"] in first for asset in candidate._EDITORIAL_ASSET_CATALOG.values())
    assert "localStorage" not in first
    assert "fetch(" not in first
    assert "XMLHttpRequest" not in first
    assert "legacy-run-main" not in first
    assert "render_current_report" not in first
    assert "multi-message-mechanism-overview.webp" not in first
    candidate_source = Path(candidate.__file__).read_text(encoding="utf-8")
    assert "concurrent_message_renderer" not in candidate_source
    assert "render_current_report" not in candidate_source

    for message in formal_payload.messages:
        assert message["message_id"] in first
        assert message["title"] in first
        assert message["body"].split("\n\n", 1)[0] in first
    assert formal_payload.run["prompt_tokens"]["primary"] in first
    assert formal_payload.run["prompt_tokens"]["shadow"] in first
    assert formal_payload.downloads.report_payload in first


def test_editorial_candidate_does_not_enter_public_fixed_adapters() -> None:
    assert all("Editorial" not in type(adapter).__name__ for adapter in _FIXED_ADAPTERS)
    assert len(_FIXED_ADAPTERS) == 3
