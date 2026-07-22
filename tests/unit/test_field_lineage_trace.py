from __future__ import annotations

import json

import pytest

from llm_abm_sim.field_lineage_trace import FieldLineageTraceModule, FieldLineageTraceSource


def test_field_lineage_trace_locates_direct_profile_fields_in_persisted_sample_record() -> None:
    source = FieldLineageTraceSource(
        users=[
            {
                "user_id": "u1",
                "nickname": "锦江观察者",
                "bio": "",
                "signature": "绿色旅行",
                "interest_tags": [],
                "follower_count": 42,
                "following_count": 7,
                "video_count": 3,
            }
        ],
        historical_tags_by_user={"u1": []},
        historical_tag_evidence_by_user={},
        exposed_user_ids=set(),
        prompt_inclusion_by_user={},
        artifact_paths={
            "sample_manifest_json": "sample_manifest.json",
            "field_source_records": "field_source_records.json",
        },
    )

    bundle = FieldLineageTraceModule().build(source)

    catalog = {entry.field_name: entry for entry in bundle.catalog}
    assert catalog["nickname"].provenance == "Direct Observed Profile Field"
    assert catalog["nickname"].source_artifact_kind == "persisted processed research sample record"
    assert catalog["nickname"].record_key_fields == ["user_id"]
    assert catalog["nickname"].source_fields == ["nickname"]
    traces = {trace.field_name: trace for trace in bundle.trace_index["u1"]}
    assert traces["nickname"].value_status == "present"
    assert traces["nickname"].source_record_locator.artifact_id == "sample_manifest_json"
    assert traces["nickname"].source_record_locator.relative_path == "sample_manifest.json"
    assert traces["nickname"].source_record_locator.record_key == {"user_id": "u1"}
    assert traces["nickname"].actual_usage_stages == ["Report Only"]
    assert traces["nickname"].prompt_inclusion_status == "not_allowlisted"
    assert traces["nickname"].omission_reason == "field_not_in_prompt_allowlist"
    assert traces["bio"].value_status == "empty"


def test_field_lineage_trace_records_recomputable_derived_proxy_inputs_and_prompt_usage() -> None:
    source = FieldLineageTraceSource(
        users=[
            {
                "user_id": "u1",
                "interest_tags": [],
                "activity_score": 0.44,
                "activity_video_score": 0.2,
                "activity_comment_score": 0.6,
                "activity_reply_score": 0.4,
                "global_influence_score": 0.7,
                "local_influence_score": 0.5,
                "local_network_score": 0.4,
                "local_recognition_score": 0.65,
            }
        ],
        historical_tags_by_user={"u1": []},
        historical_tag_evidence_by_user={},
        exposed_user_ids={"u1"},
        prompt_inclusion_by_user={
            "u1": {
                "activity_score": "included",
                "global_influence_score": "included",
                "local_influence_score": "included",
            }
        },
        artifact_paths={
            "sample_manifest_json": "sample_manifest.json",
            "field_source_records": "field_source_records.json",
        },
        derived_proxy_inputs_by_user={
            "u1": {
                "video_count": 2,
                "comment_count": 4,
                "reply_count": 1,
                "edge_degree": 3,
                "comment_like_sum": 9,
                "video_count_p95": 10.0,
                "comment_count_p95": 8.0,
                "reply_count_p95": 5.0,
                "edge_degree_p95": 12.0,
                "comment_like_sum_p95": 20.0,
                "target_scope_weighted_degree": 5,
                "target_scope_p95_weighted_degree": 12.0,
            }
        },
    )

    bundle = FieldLineageTraceModule().build(source)

    catalog = {entry.field_name: entry for entry in bundle.catalog}
    assert catalog["activity_score"].provenance == "Derived Proxy Metric"
    assert catalog["activity_score"].transformation_method == "holdout_safe_activity_proxy_v1"
    assert catalog["activity_comment_score"].source_fields == ["comment_count", "comment_count_p95"]
    assert catalog["local_influence_score"].source_fields == ["local_network_score", "local_recognition_score"]
    assert catalog["base_network_relevance"].source_fields == [
        "target_scope_weighted_degree",
        "target_scope_p95_weighted_degree",
    ]
    assert catalog["base_network_relevance"].record_key_fields == ["user_id"]
    assert catalog["engaged_neighbor_count"].record_key_fields == ["user_id", "time_step"]
    assert catalog["engaged_neighbor_count"].value_range == "大于或等于 0 的整数。"
    assert catalog["historical_tag_affinity"].source_fields == ["historical_tag_affinity"]
    source_record = bundle.source_records[0]
    assert source_record.derived_proxy_inputs["comment_count"] == 4
    traces = {trace.field_name: trace for trace in bundle.trace_index["u1"]}
    activity = traces["activity_score"]
    assert activity.source_record_locator.artifact_id == "sample_manifest_json"
    assert activity.source_record_locator.record_key == {"user_id": "u1"}
    assert activity.actual_usage_stages == ["LLM Prompt", "Report Only"]
    assert activity.prompt_inclusion_status == "included"
    assert activity.omission_reason == ""
    assert activity.evidence[0].evidence_kind == "derived_proxy_inputs"
    assert activity.evidence[0].source_fields == [
        "activity_video_score",
        "activity_comment_score",
        "activity_reply_score",
    ]
    assert activity.evidence[0].matched_values == [
        "activity_video_score=0.2",
        "activity_comment_score=0.6",
        "activity_reply_score=0.4",
    ]
    base_network = traces["base_network_relevance"]
    assert base_network.source_record_locator.artifact_id == "field_source_records"
    assert base_network.evidence[0].matched_values == [
        "target_scope_weighted_degree=5",
        "target_scope_p95_weighted_degree=12.0",
    ]
    assert traces["activity_video_score"].prompt_inclusion_status == "not_allowlisted"


def test_field_lineage_trace_marks_latent_fields_as_synthetic_with_reproduction_contract() -> None:
    latent = {
        "latent_attribute_spec_id": "jinjiang_user_latent_attributes_v1",
        "latent_attribute_method": "latent_class_exact_quota_v1",
        "latent_attribute_seed": 20260630,
        "latent_class": "class_2",
        "latent_environmental_consciousness_coef": 1.037,
        "latent_epistemic_value_weight": 0.4,
        "latent_environmental_value_weight": 0.9,
        "latent_functional_value_weight": 0.6,
        "latent_health_value_weight": 0.7,
        "latent_emotional_value_weight": 0.2,
        "latent_social_value_weight": 0.1,
        "latent_hotel_class": "midscale",
        "latent_travel_purpose": "leisure",
        "latent_gender": "female",
        "latent_age": "age_26_35",
        "latent_education": "bachelor",
        "latent_monthly_income": "income_8001_15000",
    }
    source = FieldLineageTraceSource(
        users=[{"user_id": "u1", "interest_tags": [], "latent_attributes": latent}],
        historical_tags_by_user={"u1": []},
        historical_tag_evidence_by_user={},
        exposed_user_ids={"u1"},
        prompt_inclusion_by_user={
            "u1": {
                "latent_environmental_consciousness_coef": "included",
                "latent_epistemic_value_weight": "included",
                "latent_environmental_value_weight": "included",
                "latent_functional_value_weight": "included",
                "latent_health_value_weight": "included",
                "latent_emotional_value_weight": "included",
                "latent_social_value_weight": "included",
                "latent_hotel_class": "included",
                "latent_travel_purpose": "included",
            }
        },
        artifact_paths={
            "sample_manifest_json": "sample_manifest.json",
            "field_source_records": "field_source_records.json",
        },
    )

    bundle = FieldLineageTraceModule().build(source)

    catalog = {entry.field_name: entry for entry in bundle.catalog}
    latent_catalog = {name: entry for name, entry in catalog.items() if name.startswith("latent_")}
    assert set(latent_catalog) == set(latent)
    assert {entry.provenance for entry in latent_catalog.values()} == {"Synthetic Experiment Label"}
    assert catalog["latent_hotel_class"].transformation_method == "jinjiang_latent_attribute_assignment_v1"
    traces = {trace.field_name: trace for trace in bundle.trace_index["u1"]}
    hotel = traces["latent_hotel_class"]
    assert hotel.value_status == "present"
    assert hotel.source_record_locator.artifact_id == "sample_manifest_json"
    assert hotel.prompt_inclusion_status == "included"
    assert hotel.actual_usage_stages == ["LLM Prompt", "Report Only"]
    assert hotel.evidence[0].evidence_kind == "synthetic_experiment_contract"
    assert hotel.evidence[0].source_fields == [
        "latent_attribute_spec_id",
        "latent_attribute_method",
        "latent_attribute_seed",
        "latent_hotel_class",
    ]
    assert hotel.evidence[0].matched_values == [
        "latent_attribute_spec_id=jinjiang_user_latent_attributes_v1",
        "latent_attribute_method=latent_class_exact_quota_v1",
        "latent_attribute_seed=20260630",
        "latent_hotel_class=midscale",
    ]
    assert traces["latent_class"].prompt_inclusion_status == "not_allowlisted"
    assert traces["latent_class"].omission_reason == "field_not_in_prompt_allowlist"


def test_field_lineage_trace_keeps_historical_tags_independent_and_omits_revoked_interest_contract() -> None:
    source = FieldLineageTraceSource(
        users=[
            {"user_id": "u1", "interest_tags": ["绿色酒店", "锦江ESG"]},
            {"user_id": "u2", "interest_tags": []},
        ],
        historical_tags_by_user={"u1": ["锦江ESG"], "u2": ["乡村振兴"]},
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
        exposed_user_ids={"u1", "u2"},
        prompt_inclusion_by_user={"u1": {}, "u2": {}},
        artifact_paths={
            "sample_manifest_json": "sample_manifest.json",
            "field_source_records": "field_source_records.json",
        },
    )

    bundle = FieldLineageTraceModule().build(source)

    catalog = {entry.field_name: entry for entry in bundle.catalog}
    assert "interest_tags" not in catalog
    assert catalog["historical_tags"].provenance == "Historical Behavioral Evidence"
    assert catalog["historical_tags"].transformation_method == "historical_interaction_video_tags_v1"
    assert catalog["historical_tags"].declared_usage_stages == ["Ranking", "Report Only"]
    for user_traces in bundle.trace_index.values():
        assert "interest_tags" not in {trace.field_name for trace in user_traces}
    assert bundle.source_records[1].historical_tags == ["乡村振兴"]
    assert "interest_tags" not in bundle.source_records[1].model_dump(mode="json")
    persisted_documents = json.dumps(
        [bundle.catalog_document(), bundle.trace_document(), bundle.source_document()],
        ensure_ascii=False,
    )
    assert "interest_tags" not in persisted_documents


def test_field_lineage_trace_rejects_historical_tags_without_matching_evidence() -> None:
    source = FieldLineageTraceSource(
        users=[{"user_id": "u1"}],
        historical_tags_by_user={"u1": ["无法追溯"]},
        historical_tag_evidence_by_user={},
        exposed_user_ids={"u1"},
        prompt_inclusion_by_user={"u1": {}},
        artifact_paths={
            "sample_manifest_json": "sample_manifest.json",
            "field_source_records": "field_source_records.json",
        },
    )

    with pytest.raises(ValueError, match="historical_tags values must exactly match"):
        FieldLineageTraceModule().build(source)
