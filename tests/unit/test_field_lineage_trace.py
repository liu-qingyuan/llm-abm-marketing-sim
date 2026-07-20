from __future__ import annotations

import pytest

from llm_abm_sim.field_lineage_trace import FieldLineageTraceModule, FieldLineageTraceSource


def test_field_lineage_trace_builds_independent_interest_and_historical_tag_evidence() -> None:
    source = FieldLineageTraceSource(
        users=[
            {"user_id": "u1", "interest_tags": ["绿色酒店", "锦江ESG"]},
            {"user_id": "u2", "interest_tags": []},
            {"user_id": "u3", "interest_tags": ["未曝光兴趣"]},
            {"user_id": "u4", "interest_tags": ["未构建摘要"]},
        ],
        historical_tags_by_user={
            "u1": ["锦江ESG"],
            "u2": ["乡村振兴"],
            "u3": [],
            "u4": [],
        },
        interest_tag_evidence_by_user={
            "u1": [
                {
                    "evidence_kind": "historical_video_hashtags",
                    "record_key": {"video_id": "history-1"},
                    "source_fields": ["hashtags"],
                    "matched_values": ["锦江ESG"],
                },
                {
                    "evidence_kind": "historical_text_topic_terms",
                    "record_key": {"comment_id": "comment-1"},
                    "source_fields": ["content"],
                    "matched_values": ["绿色酒店"],
                },
            ],
            "u3": [
                {
                    "evidence_kind": "historical_text_topic_terms",
                    "record_key": {"comment_id": "comment-3"},
                    "source_fields": ["content"],
                    "matched_values": ["未曝光兴趣"],
                }
            ],
            "u4": [
                {
                    "evidence_kind": "historical_text_topic_terms",
                    "record_key": {"comment_id": "comment-4"},
                    "source_fields": ["content"],
                    "matched_values": ["未构建摘要"],
                }
            ],
        },
        historical_tag_evidence_by_user={
            "u1": [
                {
                    "evidence_kind": "historical_interaction_video_hashtags",
                    "record_key": {"video_id": "history-1"},
                    "source_fields": ["hashtags"],
                    "matched_values": ["锦江ESG"],
                }
            ],
            "u2": [
                {
                    "evidence_kind": "historical_interaction_video_hashtags",
                    "record_key": {"video_id": "history-2"},
                    "source_fields": ["hashtags"],
                    "matched_values": ["乡村振兴"],
                }
            ],
        },
        exposed_user_ids={"u1", "u2", "u4"},
        prompt_inclusion_by_user={
            "u1": {"interest_tags": "included"},
            "u2": {"interest_tags": "empty_omitted"},
        },
        artifact_paths={"field_source_records": "field_source_records.json"},
    )

    bundle = FieldLineageTraceModule().build(source)

    catalog = {entry.field_name: entry for entry in bundle.catalog}
    assert set(catalog) == {"interest_tags", "historical_tags"}
    assert catalog["interest_tags"].provenance == "Historical Behavioral Evidence"
    assert catalog["interest_tags"].source_fields == [
        "historical_video_hashtags",
        "historical_text_topic_terms",
    ]
    assert catalog["interest_tags"].transformation_method == "historical_topic_tags_stable_unique_v1"
    assert catalog["historical_tags"].transformation_method == "historical_interaction_video_tags_v1"

    traces = {
        (trace.user_id, trace.field_name): trace for user_traces in bundle.trace_index.values() for trace in user_traces
    }
    u1_interest = traces[("u1", "interest_tags")]
    assert u1_interest.value_status == "present"
    assert u1_interest.prompt_inclusion_status == "included"
    assert u1_interest.actual_usage_stages == ["LLM Prompt", "Report Only"]
    assert u1_interest.source_record_locator.artifact_id == "field_source_records"
    assert u1_interest.source_record_locator.relative_path == "field_source_records.json"
    assert u1_interest.source_record_locator.record_key == {"user_id": "u1"}
    assert {item.evidence_kind for item in u1_interest.evidence} == {
        "historical_video_hashtags",
        "historical_text_topic_terms",
    }

    u2_interest = traces[("u2", "interest_tags")]
    assert u2_interest.value_status == "empty"
    assert u2_interest.prompt_inclusion_status == "empty_omitted"
    assert u2_interest.omission_reason == "empty_value_omitted_from_prompt"
    assert u2_interest.actual_usage_stages == ["Report Only"]

    u2_history = traces[("u2", "historical_tags")]
    assert u2_history.value_status == "present"
    assert u2_history.prompt_inclusion_status == "not_allowlisted"
    assert u2_history.omission_reason == "field_not_in_prompt_allowlist"
    assert u2_history.actual_usage_stages == ["Ranking", "Report Only"]

    u3_interest = traces[("u3", "interest_tags")]
    assert u3_interest.prompt_inclusion_status == "not_exposed"
    assert u3_interest.omission_reason == "user_not_exposed_to_target_video"

    u4_interest = traces[("u4", "interest_tags")]
    assert u4_interest.prompt_inclusion_status == "not_rendered"
    assert u4_interest.omission_reason == "prompt_summary_not_built"

    assert bundle.source_records[1].interest_tags == []
    assert bundle.source_records[1].historical_tags == ["乡村振兴"]


def test_field_lineage_trace_rejects_present_tags_without_matching_historical_evidence() -> None:
    source = FieldLineageTraceSource(
        users=[{"user_id": "u1", "interest_tags": ["无法追溯"]}],
        historical_tags_by_user={"u1": []},
        interest_tag_evidence_by_user={},
        historical_tag_evidence_by_user={},
        exposed_user_ids={"u1"},
        prompt_inclusion_by_user={"u1": {"interest_tags": "included"}},
        artifact_paths={"field_source_records": "field_source_records.json"},
    )

    with pytest.raises(ValueError, match="interest_tags values must exactly match"):
        FieldLineageTraceModule().build(source)
