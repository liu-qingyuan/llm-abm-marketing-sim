from __future__ import annotations

from llm_abm_sim.data_sources.douyin_models import DouyinCommentRecord, DouyinVideoRecord
from llm_abm_sim.data_sources.douyin_network import build_interaction_edges


def test_network_builder_creates_comment_reply_and_mention_edges() -> None:
    videos = [DouyinVideoRecord(video_id="v1", creator_user_id="creator1")]
    comments = [
        DouyinCommentRecord(
            comment_id="c1",
            video_id="v1",
            commenter_user_id="u1",
            mentioned_user_ids=["u2"],
            publish_time="2025-06-01T00:01:00",
        ),
        DouyinCommentRecord(
            comment_id="c2",
            video_id="v1",
            commenter_user_id="u1",
            publish_time="2025-06-01T00:03:00",
        ),
        DouyinCommentRecord(
            comment_id="r1",
            video_id="v1",
            parent_comment_id="c1",
            commenter_user_id="u2",
            comment_level="reply",
            publish_time="2025-06-01T00:02:00",
        ),
    ]
    by_pair = {(edge.source, edge.target): edge for edge in build_interaction_edges(videos, comments)}
    assert by_pair[("u1", "creator1")].comment_count == 2
    assert by_pair[("u1", "creator1")].weight == 2
    assert by_pair[("u1", "creator1")].first_interaction_time == "2025-06-01T00:01:00"
    assert by_pair[("u1", "creator1")].last_interaction_time == "2025-06-01T00:03:00"
    assert by_pair[("u2", "u1")].reply_count == 1
    assert by_pair[("u1", "u2")].mention_count == 1
