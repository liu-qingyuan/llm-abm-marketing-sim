from __future__ import annotations

import gzip
import hashlib
import re
from pathlib import Path

import pytest

from llm_abm_sim import concurrent_message_editorial_candidate as candidate
from llm_abm_sim.concurrent_message_mechanism_presentation import _MECHANISM_PRESENTATION
from llm_abm_sim.concurrent_message_renderer import _FIXED_RENDERERS, render_report
from llm_abm_sim.concurrent_message_report import ConcurrentMessageReportPayload

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "concurrent_message_renderer"
ASSET_DIR = Path(__file__).resolve().parents[2] / "src" / "llm_abm_sim" / "report_assets"
SOURCE_DIR = Path(__file__).resolve().parents[2] / "src" / "llm_abm_sim" / "report_assets"

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

_EDITORIAL_V2_ASSET_HASHES = {
    "editorial-mechanism-overview-v2.webp": "fe112e7d898e881dd7d379333e2192e87c62278820a52ea4b0f6bd39fee550bc",
    "editorial-mechanism-sample-v2.webp": "a01d8ea31980568b06bf8a03a42592e83387883ed0f60ea097218879bb120b37",
    "editorial-mechanism-exposure-ranking-v2.webp": "92073c232aa770bb400375ce3495ac21a59f121a4e823e789e01a8fb0e917812",
    "editorial-mechanism-llm-decision-v2.webp": "96a5a87a01da39ef73a8c2a1cb510bcd008697cf595b760acc891e911ff53368",
    "editorial-mechanism-network-feedback-v2.webp": "548f0d601e84291125fac1926ea1304f723ad8fff37c013297b1f4e54719df50",
}

_EDITORIAL_V3_ASSET_HASHES = {
    "editorial-mechanism-overview-v3.webp": "fe112e7d898e881dd7d379333e2192e87c62278820a52ea4b0f6bd39fee550bc",
    "editorial-mechanism-sample-v3.webp": "a01d8ea31980568b06bf8a03a42592e83387883ed0f60ea097218879bb120b37",
    "editorial-mechanism-exposure-ranking-v3.webp": "0866e463948e95329d3949ebe7f41edfa3f5e9c708e55f309b6877b7df2b9367",
    "editorial-mechanism-llm-decision-v3.webp": "96a5a87a01da39ef73a8c2a1cb510bcd008697cf595b760acc891e911ff53368",
    "editorial-mechanism-network-feedback-v3.webp": "d28d30437865965b3b72a6be2cfa5b516f6e6741208bc250232695b9b1f38b14",
}

_V2_LEGEND_ITEMS = {
    "overview": {
        "overview-first-message-channel",
        "overview-second-message-channel",
        "overview-third-message-channel",
        "overview-research-sample",
        "overview-eligible-pair",
        "overview-per-message-queue",
        "overview-exposure-gate",
        "overview-decision-pair",
    },
    "sample": {
        "sample-influence-seed-union",
        "sample-direct-one-hop-network-cohort",
        "sample-ordinary-fill",
    },
    "exposure-ranking": {
        "ranking-first-message-channel",
        "ranking-second-message-channel",
        "ranking-third-message-channel",
        "ranking-personalized-top20",
        "ranking-cross-message-overlap",
        "ranking-single-exposure",
    },
    "llm-decision": {
        "decision-exposure-gate",
        "decision-primary",
        "decision-shadow",
    },
    "network-feedback": {
        "feedback-first-message-channel",
        "feedback-second-message-channel",
        "feedback-third-message-channel",
        "feedback-propagating-primary",
        "feedback-engaged-user-dedup",
        "feedback-next-batch-reranking",
        "feedback-no-campaign-feedback",
    },
}


@pytest.fixture(scope="module")
def formal_payload() -> ConcurrentMessageReportPayload:
    with gzip.open(FIXTURE_DIR / "formal_report_payload.json.gz", "rb") as stream:
        return ConcurrentMessageReportPayload.model_validate_json(stream.read())


def test_editorial_catalog_has_zh_en_key_parity() -> None:
    assert set(candidate._EDITORIAL_CATALOG["zh-CN"]) == set(candidate._EDITORIAL_CATALOG["en-US"])
    assert set(candidate._EDITORIAL_V2_CATALOG["zh-CN"]) == set(candidate._EDITORIAL_V2_CATALOG["en-US"])
    assert set(candidate._EDITORIAL_V3_CATALOG["zh-CN"]) == set(candidate._EDITORIAL_V3_CATALOG["en-US"])
    assert candidate._EDITORIAL_DETAILS
    for details in (candidate._EDITORIAL_DETAILS, candidate._EDITORIAL_V3_DETAILS):
        for detail in details.values():
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


def test_editorial_v2_assets_and_legend_close_the_audited_mark_contract(
    formal_payload: ConcurrentMessageReportPayload,
) -> None:
    assert set(candidate._EDITORIAL_V2_ASSET_CATALOG) == set(_V2_LEGEND_ITEMS)
    for asset in candidate._EDITORIAL_V2_ASSET_CATALOG.values():
        source_path = SOURCE_DIR / asset["source"]
        source_data = source_path.read_bytes()
        derivative_path = ASSET_DIR / asset["file"]
        derivative_data = derivative_path.read_bytes()

        assert asset["version"] == "v2"
        assert source_path.name.endswith("-v2.png")
        assert derivative_path.name.endswith("-v2.webp")
        assert source_data.startswith(b"\x89PNG\r\n\x1a\n")
        assert int.from_bytes(source_data[16:20], "big") == 1536
        assert int.from_bytes(source_data[20:24], "big") == 1024
        assert hashlib.sha256(source_data).hexdigest() == asset["source_sha256"]
        assert derivative_data.startswith(b"RIFF") and derivative_data[8:12] == b"WEBP"
        assert len(derivative_data) > 1_000
        assert hashlib.sha256(derivative_data).hexdigest() == asset["sha256"]
        assert asset["sha256"] == _EDITORIAL_V2_ASSET_HASHES[derivative_path.name]

    html = candidate._render_editorial_v2(formal_payload)
    assert html != candidate._render_editorial_candidate(formal_payload)
    assert 'data-editorial-version="v2"' in html
    assert html.count('class="editorial-legend editorial-legend-v2"') == 5
    assert html.count('data-legend-item="') == 27
    assert html.count('data-encoding-axis="message-identity"') == 9
    assert html.count('data-encoding-axis="sample-role"') == 3

    for section, expected_items in _V2_LEGEND_ITEMS.items():
        start = html.index(f'data-legend-section="{section}"')
        end = html.index("</div>", start)
        actual_items = set(re.findall(r'data-legend-item="([^"]+)"', html[start:end]))
        assert actual_items == expected_items

    for annotation_only in (
        "sample-synthetic-label-lineage",
        "ranking-shared-seed-launch",
        "decision-platform-environment",
        "decision-message-user-fit",
        "decision-not-selected",
        "feedback-same-batch-frozen",
    ):
        assert f'data-legend-item="{annotation_only}"' not in html


def test_editorial_v3_assets_are_versioned_packaged_and_nonblank() -> None:
    assert set(candidate._EDITORIAL_V3_ASSET_CATALOG) == set(_V2_LEGEND_ITEMS)
    for asset in candidate._EDITORIAL_V3_ASSET_CATALOG.values():
        source_path = SOURCE_DIR / asset["source"]
        source_data = source_path.read_bytes()
        derivative_path = ASSET_DIR / asset["file"]
        derivative_data = derivative_path.read_bytes()

        assert asset["version"] == "v3"
        assert source_path.name.endswith("-v3.png")
        assert derivative_path.name.endswith("-v3.webp")
        assert source_data.startswith(b"\x89PNG\r\n\x1a\n")
        assert int.from_bytes(source_data[16:20], "big") == 1536
        assert int.from_bytes(source_data[20:24], "big") == 1024
        assert hashlib.sha256(source_data).hexdigest() == asset["source_sha256"]
        assert derivative_data.startswith(b"RIFF") and derivative_data[8:12] == b"WEBP"
        assert len(derivative_data) > 1_000
        assert hashlib.sha256(derivative_data).hexdigest() == asset["sha256"]
        assert asset["sha256"] == _EDITORIAL_V3_ASSET_HASHES[derivative_path.name]


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


def test_run_evidence_recomputes_persisted_formal_fixture(formal_payload: ConcurrentMessageReportPayload) -> None:
    data = candidate._run_evidence_data(formal_payload)

    assert (data["sample_users"], data["eligible_pairs"], data["actual_exposures"]) == (1000, 3000, 1800)
    assert data["coverage"] == {"0": 0, "1": 434, "2": 332, "3": 234}
    assert data["role_counts"] == {"seed": 20, "network_cohort": 60, "ordinary": 920}
    assert data["class_counts"] == {"class_1": 422, "class_2": 417, "class_3": 161}
    assert [row["values"] for row in data["class_matrix"]] == [[422, 168, 388], [51, 417, 51], [127, 15, 161]]
    assert data["union_count"] == 1000
    assert data["three_way_count"] == 234
    assert [(row["min"], row["mean"], row["max"]) for row in data["fit_ranges"]] == [
        (0.588110057966, 0.760953182281, 0.833353574559),
        (0.493275781501, 0.775782336835, 0.811959203577),
        (0.574908137029, 0.692596514244, 0.828893393071),
    ]
    assert len(data["batch_rows"]) == 90
    assert len(data["trace_rows"]) == 1800
    assert data["per_message"][0]["action_counts"] == {"like": 480, "comment": 37, "share": 3, "ignore": 80, "provider_failed": 0}
    assert [
        (row["positive_numerator"], row["positive_denominator"])
        for row in data["per_message"]
    ] == [(520, 600), (487, 600), (585, 600)]
    assert data["trace_sensitivity"] == {
        "paired_coverage": {"numerator": 1800, "denominator": 1800, "value": 1.0},
        "disagreement": {"numerator": 244, "denominator": 1800, "value": 0.135555555556},
        "mean_delta": 0.121361111111,
        "flagged_reasons": 0,
    }
    assert len(data["field_lineage"]) == 7
    assert sum(row["disagreement"] for row in data["trace_rows"]) == 244
    assert data["feedback"]["message_batch_count"] == 90
    assert data["feedback"]["changed_message_batch_count"] == 15
    assert [message["changed_batch_count"] for message in data["feedback"]["per_message"]] == [5, 5, 5]
    assert [message["overlap_range"] for message in data["feedback"]["per_message"]] == [
        {"min": 5, "max": 20},
        {"min": 8, "max": 20},
        {"min": 6, "max": 20},
    ]
    assert [
        (
            batch["top_overlap_count"],
            len(batch["feedback_added_user_ids"]),
            len(batch["feedback_removed_user_ids"]),
        )
        for batch in data["feedback"]["per_message"][0]["batches"][1:6]
    ] == [(15, 5, 5), (10, 10, 10), (19, 1, 1), (5, 15, 15), (19, 1, 1)]
    assert data["downloads"] == formal_payload.downloads.model_dump(mode="json")
    assert len(candidate._EDITORIAL_DOWNLOAD_KEYS) == 17

    html = candidate._render_editorial_candidate(formal_payload)
    assert 'data-testid="run-coverage-sequence">0/434/332/234</code>' in html
    assert 'data-fit-min=".588"' in html
    assert 'data-fit-mean=".776"' in html
    assert 'data-fit-max=".829"' in html
    assert html.count("data-download-key=") == 17
    assert html.count('data-testid="run-download-group-') == 4
    assert 'data-testid="run-feedback-changed-total"' in html
    assert '15 / 90' in html
    assert formal_payload.messages[0]["body"].split("\n\n", 1)[0] in html


@pytest.mark.parametrize("corruption", ["missing", "renamed", "crossed", "escaped"])
def test_editorial_candidate_rejects_noncanonical_download_targets(
    formal_payload: ConcurrentMessageReportPayload,
    corruption: str,
) -> None:
    downloads = formal_payload.downloads.model_dump(mode="json")
    if corruption == "missing":
        downloads.pop("users_json")
    elif corruption == "renamed":
        downloads["users_json"] = "renamed_users.json"
    elif corruption == "crossed":
        downloads["users_json"], downloads["users_csv"] = downloads["users_csv"], downloads["users_json"]
    else:
        downloads["users_json"] = "../users.json"
    broken = formal_payload.model_copy(update={"downloads": downloads})

    with pytest.raises(ValueError, match="approved download|approved downloads"):
        candidate._run_evidence_data(broken)


def test_editorial_candidate_rejects_non_top20_feedback_batch(
    formal_payload: ConcurrentMessageReportPayload,
) -> None:
    broken = formal_payload.model_copy(deep=True)
    broken.campaign_feedback_effect["per_message"]["message_1"]["batches"][0]["top_count"] = 19

    with pytest.raises(ValueError, match="Top20 rankings"):
        candidate._run_evidence_data(broken)


def test_run_evidence_allows_provider_failure_outside_dual_success_sensitivity(
    formal_payload: ConcurrentMessageReportPayload,
) -> None:
    broken = formal_payload.model_copy(deep=True)
    broken.exposure_rows[0].primary_status = "provider_failed"
    broken.exposure_rows[0].primary_action = "provider_failed"

    data = candidate._run_evidence_data(broken)

    assert len(data["trace_rows"]) == 1800
    assert sum(row["disagreement"] for row in data["trace_rows"]) == 244


def test_run_evidence_rejects_inconsistent_persisted_coverage(formal_payload: ConcurrentMessageReportPayload) -> None:
    broken = formal_payload.model_copy(deep=True)
    broken.campaign_funnel["campaign_exposure_coverage"]["1"] = 435

    with pytest.raises(ValueError, match="exposure coverage"):
        candidate._run_evidence_data(broken)



def test_editorial_v3_closes_three_channel_overlap_and_campaign_feedback_semantics(
    formal_payload: ConcurrentMessageReportPayload,
) -> None:
    html = candidate._render_editorial_v3(formal_payload)

    assert 'data-editorial-version="v3"' in html
    assert html.count('data-legend-item="ranking-cross-message-overlap"') == 1
    assert 'editorial-mark-overlap-three' in html
    assert "同一 user 可以进入任意两条或全部三条 queue，但不要求发生 overlap" in html
    assert "the same user may enter any two or all three queues; overlap is allowed, not required" in html
    assert "相同 user × message pair 最多 exposure 一次" in html
    assert "the same user × message pair can be exposed at most once" in html.lower()

    assert 'editorial-mark-dedup-three' in html
    assert 'editorial-mark-shared-context' in html
    assert "terminal `succeeded` 且 action 为 like / comment / share" in html
    assert "terminal `succeeded` with action like / comment / share" in html
    assert "按 `user_id` 跨 message 汇聚为唯一 campaign engaged-user set" in html
    assert "deduplicated by `user_id` across messages into one campaign engaged-user set" in html
    assert "不把用户直接注入任何 queue" in html
    assert "does not inject those users into any queue" in html
    assert "Shadow、ignore、provider_failed" in html
    assert "Shadow, ignore, and provider_failed" in html


def test_editorial_v4_projects_the_single_owner_semantics_without_legacy_visuals(
    formal_payload: ConcurrentMessageReportPayload,
) -> None:
    presentation = _MECHANISM_PRESENTATION.build()
    html = candidate._render_editorial_v4(formal_payload)

    assert 'data-editorial-version="v4-semantic"' in html
    assert 'data-production-deploy-eligible="false"' in html
    assert tuple(
        re.findall(r'<section id="([^"]+)"[^>]+data-section-anchor="[^"]+"', html)
    )[:5] == candidate._EDITORIAL_ANCHORS
    assert tuple(
        re.findall(r'data-mechanism-diagram-id="([^"]+)"', html)
    ) == tuple(diagram.diagram_id for diagram in presentation.diagrams)
    assert html.count('data-mechanism-method-disclosure="') == 6
    assert '<button class="editorial-hotspot' not in html
    assert 'data-mechanism-key="' not in html
    assert 'data-legend-item="' not in html
    assert "data:image/webp" not in html
    assert "mechanism-image-generation-audit.json" not in html
    assert "mechanism-sample-first-v4.png" not in html
    assert "mermaid.min.js" not in html
    assert "cdn.jsdelivr" not in html
    assert {
        key
        for key, value in candidate._EDITORIAL_V4_CATALOG["zh-CN"].items()
        if value == candidate._EDITORIAL_V4_CATALOG["en-US"][key]
    } == {"language.zh", "language.en"}

    for diagram in presentation.diagrams:
        for node in diagram.nodes:
            assert f'data-semantic-node-id="{node.semantic_id}"' in html
        for edge in diagram.edges:
            assert f'data-semantic-edge-id="{edge.semantic_id}"' in html


def test_editorial_v4_never_reads_legacy_raster_assets(
    formal_payload: ConcurrentMessageReportPayload,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_legacy_asset(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("semantic candidate attempted to read a legacy raster")

    for name in (
        "_mechanism_html",
        "_embedded_asset",
        "_v2_embedded_asset",
        "_v3_embedded_asset",
    ):
        monkeypatch.setattr(candidate, name, reject_legacy_asset)

    html = candidate._render_editorial_v4(formal_payload)

    assert 'data-editorial-version="v4-semantic"' in html
    assert "data:image/webp" not in html


def test_editorial_v3_is_default_while_v1_and_v2_stay_exact(
    formal_payload: ConcurrentMessageReportPayload,
) -> None:
    v1 = candidate._render_editorial_candidate(formal_payload)
    v2 = candidate._render_editorial_v2(formal_payload)
    v3 = candidate._render_editorial_v3(formal_payload)

    assert hashlib.sha256(v1.encode("utf-8")).hexdigest() == (
        "1d1e1ead3691aa275c74ff723a79960019c42fd58f179d8b74619f0a0b218ea9"
    )
    assert hashlib.sha256(v2.encode("utf-8")).hexdigest() == (
        "4e6680caf8476aa2b7839a20a985c320ce423c64b974d592b449ee2afa0ddbd8"
    )
    assert hashlib.sha256(v3.encode("utf-8")).hexdigest() == (
        "ed661dcc53304b33a37c52e7540db5422c8206bec0e823991e22d7b8c3b46073"
    )
    assert render_report(formal_payload) == v3
    assert [renderer.__name__ for renderer in _FIXED_RENDERERS] == [
        "_render_editorial_v3",
        "_render_editorial_v2",
        "_render_editorial_candidate",
        "_render_two_mode_report",
        "_legacy_render_report",
        "_render_historical_report",
    ]
