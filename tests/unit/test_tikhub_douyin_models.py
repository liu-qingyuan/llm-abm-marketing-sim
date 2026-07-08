from __future__ import annotations

import pytest

from llm_abm_sim.data_sources.douyin_models import (
    PROFILE_COLUMNS,
    REMOVED_DEMO_PRESET_FIELDS,
    DouyinCollectionReport,
    DouyinCommentRecord,
    DouyinEdgeRecord,
    DouyinProfileRecord,
    DouyinUserRecord,
    DouyinVideoRecord,
    FieldProvenance,
)


def test_models_have_safe_defaults_and_profile_columns() -> None:
    video = DouyinVideoRecord(video_id="v1")
    assert video.like_count == 0
    assert video.source_challenge_id == ""
    assert video.raw_detail_status == "unknown"
    comment = DouyinCommentRecord(comment_id="c1", video_id="v1", commenter_user_id="u1")
    assert comment.comment_level == "comment"
    user = DouyinUserRecord(user_id="u1")
    assert user.activity_score == 0.5
    profile = DouyinProfileRecord(user_id="u1", activity_score=0.8, value_proposition="extra")
    assert profile.activity_score == 0.8
    assert "value_proposition" in PROFILE_COLUMNS
    assert "activity_score" in PROFILE_COLUMNS
    assert "global_influence_score" in PROFILE_COLUMNS
    assert "local_influence_score" in PROFILE_COLUMNS
    assert "profile_index_method" in PROFILE_COLUMNS
    assert "observed_activity_level" not in PROFILE_COLUMNS
    assert "observed_influence" not in PROFILE_COLUMNS
    assert "activity_level" not in PROFILE_COLUMNS
    for removed in REMOVED_DEMO_PRESET_FIELDS:
        assert removed not in PROFILE_COLUMNS
        assert removed not in DouyinProfileRecord.model_fields


def test_profile_activity_score_does_not_create_legacy_activity_fields() -> None:
    profile = DouyinProfileRecord(
        user_id="u1",
        activity_score=0.42,
        global_influence_score=0.2,
        local_influence_score=0.6,
    )
    assert profile.activity_score == 0.42
    assert "observed_activity_level" not in DouyinProfileRecord.model_fields
    assert "observed_influence" not in DouyinProfileRecord.model_fields
    assert "activity_level" not in DouyinProfileRecord.model_fields


def test_comment_level_and_edge_weight_validation() -> None:
    with pytest.raises(ValueError):
        DouyinCommentRecord(comment_id="r1", video_id="v1", commenter_user_id="u2", comment_level="reply")
    edge = DouyinEdgeRecord(source="u1", target="u2", comment_count=1, reply_count=1, mention_count=1)
    assert edge.weight == 3
    with pytest.raises(ValueError):
        DouyinEdgeRecord(source="u1", target="u2", weight=99, comment_count=1)


def test_collection_report_provenance() -> None:
    report = DouyinCollectionReport(
        run_id="run",
        field_provenance={"profiles": FieldProvenance(observed=["follower_count"], defaulted=["brand_attitude"])},
    )
    assert report.field_provenance["profiles"].observed == ["follower_count"]
