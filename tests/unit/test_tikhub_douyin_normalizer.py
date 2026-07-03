from __future__ import annotations

import csv
import json
from pathlib import Path

from llm_abm_sim.data_sources.douyin_normalizer import normalize_run
from llm_abm_sim.data_sources.tikhub_client import TikHubSettings


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_normalizer_outputs_processed_contract(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    processed = tmp_path / "processed"
    write_jsonl(
        raw / "video_details.jsonl",
        [
            {
                "aweme_id": "v1",
                "desc": "#锦江酒店 绿色入住",
                "author": {"uid": "creator1"},
                "statistics": {"digg_count": 10, "comment_count": 1},
            }
        ],
    )
    write_jsonl(
        raw / "comments.jsonl",
        [{"cid": "c1", "aweme_id": "v1", "user": {"uid": "u1"}, "text": "锦江酒店", "mentions": [{"uid": "u2"}]}],
    )
    write_jsonl(
        raw / "comment_replies.jsonl",
        [{"cid": "r1", "aweme_id": "v1", "reply_id": "c1", "user": {"uid": "u2"}, "text": "同意"}],
    )
    write_jsonl(raw / "user_profiles.jsonl", [{"uid": "u1", "follower_count": 10, "aweme_count": 5}])
    report = normalize_run(raw, processed, run_id="run", mode="mock", settings=TikHubSettings())
    for name in ["videos.csv", "comments.csv", "text_items.csv", "users.csv", "edges.csv", "profiles.csv", "collection_report.json"]:
        assert (processed / name).exists()
    profile = rows(processed / "profiles.csv")[0]
    assert "observed_activity_level" not in profile
    assert "observed_influence" not in profile
    assert "activity_level" not in profile
    assert 0.0 <= float(profile["activity_score"]) <= 1.0
    assert profile["brand_attitude"] == "0.0"
    assert "interest_tags" in profile
    assert "value_proposition" in profile
    text_items = rows(processed / "text_items.csv")
    by_type = {row["item_type"]: row for row in text_items}
    assert by_type["video_caption"]["text"] == "#锦江酒店 绿色入住"
    assert by_type["comment"]["target_user_id"] == "creator1"
    assert by_type["reply"]["target_user_id"] == "u1"
    assert by_type["mention"]["target_user_id"] == "u2"
    assert report.counts["videos"] == 1
    assert report.counts["text_items"] == 4
    assert report.mode == "mock"


def test_normalizer_unwraps_live_app_v3_video_detail_shape(tmp_path: Path) -> None:
    raw = tmp_path / "raw-live"
    processed = tmp_path / "processed-live"
    write_jsonl(
        raw / "video_details.jsonl",
        [
            {
                "video_id": "v-live",
                "data": {
                    "aweme_detail": {
                        "aweme_id": "v-live",
                        "caption": "#锦江酒店 最近一个月文本",
                        "create_time": 1781200000,
                        "author_user_id": 12345,
                        "statistics": {"digg_count": 7, "comment_count": 2, "share_count": 1, "collect_count": 0},
                        "cha_list": [{"cha_name": "锦江酒店"}],
                    }
                },
            }
        ],
    )
    write_jsonl(raw / "comments.jsonl", [{"cid": "c-live", "aweme_id": "v-live", "user": {"uid": "u1"}, "text": "文本评论"}])
    write_jsonl(raw / "comment_replies.jsonl", [])
    write_jsonl(raw / "user_profiles.jsonl", [])

    report = normalize_run(raw, processed, run_id="live-shape", mode="mock", settings=TikHubSettings())

    video = rows(processed / "videos.csv")[0]
    assert video["caption"] == "#锦江酒店 最近一个月文本"
    assert video["creator_user_id"] == "12345"
    assert video["like_count"] == "7"
    text_items = rows(processed / "text_items.csv")
    assert text_items[0]["item_type"] == "video_caption"
    assert text_items[1]["target_user_id"] == "12345"
    assert report.counts["text_items"] == 2


def test_normalizer_stage_aware_merge_prefers_detail_but_promotes_challenge_metadata(tmp_path: Path) -> None:
    raw = tmp_path / "raw-stage"
    processed = tmp_path / "processed-stage"
    write_jsonl(
        raw / "challenge_posts.jsonl",
        [
            {"aweme_id": "v1", "desc": "challenge stale", "author": {"uid": "c1"}},
            {
                "aweme_id": "v2",
                "caption": "",
                "desc": "#锦江都城酒店 challenge only",
                "author": {"uid": "c2"},
                "source_challenge_id": "cid2",
                "source_challenge_name": "锦江都城酒店",
                "source_challenge_rank": 6,
                "_metadata_source": "challenge_page",
            },
        ],
    )
    write_jsonl(raw / "video_details.jsonl", [{"aweme_id": "v1", "desc": "detail wins", "author": {"uid": "c1"}}])
    write_jsonl(raw / "comments.jsonl", [])
    write_jsonl(raw / "comment_replies.jsonl", [])
    write_jsonl(raw / "user_profiles.jsonl", [])

    report = normalize_run(
        raw,
        processed,
        run_id="stage-aware",
        mode="mock",
        settings=TikHubSettings(),
        include_comments=False,
        include_replies=False,
        include_profiles=False,
        video_source_mode="merged_detail_preferred",
    )

    videos = rows(processed / "videos.csv")
    assert [row["video_id"] for row in videos] == ["v1", "v2"]
    assert {row["video_id"]: row["caption"] for row in videos}["v1"] == "detail wins"
    challenge_row = {row["video_id"]: row for row in videos}["v2"]
    assert challenge_row["caption"] == "#锦江都城酒店 challenge only"
    assert challenge_row["source_challenge_id"] == "cid2"
    assert challenge_row["source_challenge_name"] == "锦江都城酒店"
    assert challenge_row["source_challenge_rank"] == "6"
    assert challenge_row["raw_detail_status"] == "promoted_from_challenge"
    assert report.stage_counts["video_rows_from_detail"] == 1
    assert report.stage_counts["video_rows_from_challenge"] == 1
    assert report.comments_collected is False
    assert report.profiles_collected is False
