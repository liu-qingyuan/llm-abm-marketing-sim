from __future__ import annotations

import pytest

from llm_abm_sim.data_sources.douyin_models import (
    PROFILE_COLUMNS,
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
    assert user.observed_activity_level == 0.5
    profile = DouyinProfileRecord(user_id="u1", observed_activity_level=0.8, value_proposition="extra")
    assert profile.activity_level == 0.8
    assert profile.brand_attitude == 0.0
    assert "value_proposition" in PROFILE_COLUMNS


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
