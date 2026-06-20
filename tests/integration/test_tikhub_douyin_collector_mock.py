from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest

from llm_abm_sim.data_sources.cli import FixtureClient
from llm_abm_sim.data_sources.douyin_collector import DouyinCollector, DouyinCollectRequest
from llm_abm_sim.data_sources.tikhub_client import TikHubSettings


def load_fixture(no_challenge: bool = False) -> dict[str, Any]:
    fixture = json.loads(Path("tests/fixtures/tikhub_douyin/small_batch.json").read_text(encoding="utf-8"))
    if no_challenge:
        fixture["topic_query"] = {"keyword": "锦江酒店"}
        fixture["video_details"]["sv1"] = {
            "aweme_id": "sv1",
            "desc": "锦江酒店 fallback",
            "author": {"uid": "creator1", "sec_uid": "sec_creator1"},
        }
        fixture["comments"]["sv1"] = []
    return fixture


def csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_mock_collector_outputs_raw_processed_and_resume_without_duplicates(tmp_path: Path) -> None:
    settings = TikHubSettings(max_videos=2, max_comments_per_video=1, max_replies_per_comment=1, max_users=4)
    client = FixtureClient(load_fixture())
    client.settings = settings
    collector = DouyinCollector(client, settings)  # type: ignore[arg-type]
    paths = collector.collect(DouyinCollectRequest(run_id="run", output_root=tmp_path, mode="mock"))
    raw = paths["raw_dir"]
    processed = paths["processed_dir"]
    for name in [
        "manifest.json",
        "checkpoints.json",
        "topic_query.jsonl",
        "challenge_posts.jsonl",
        "video_details.jsonl",
        "comments.jsonl",
        "comment_replies.jsonl",
        "user_profiles.jsonl",
    ]:
        assert (raw / name).exists()
    for name in ["videos.csv", "comments.csv", "text_items.csv", "users.csv", "edges.csv", "profiles.csv", "collection_report.json"]:
        assert (processed / name).exists()
    assert len(csv_rows(processed / "videos.csv")) == 2
    assert len(csv_rows(processed / "comments.csv")) == 2
    assert len(csv_rows(processed / "text_items.csv")) == 5
    text_items = csv_rows(processed / "text_items.csv")
    assert [row["item_type"] for row in text_items] == ["video_caption", "video_caption", "comment", "mention", "reply"]
    assert [row["source"] for row in text_items] == ["videos.csv", "videos.csv", "comments.csv", "comments.csv", "comments.csv"]
    by_type = {row["item_type"]: row for row in text_items}
    assert by_type["comment"]["target_user_id"] == "creator1"
    assert by_type["reply"]["target_user_id"] == "u1"
    assert by_type["mention"]["target_user_id"] == "u2"
    report = json.loads((processed / "collection_report.json").read_text(encoding="utf-8"))
    assert report["mode"] == "mock"
    assert report["limits"]["max_videos"] == 2

    client2 = FixtureClient(load_fixture())
    client2.settings = settings
    collector2 = DouyinCollector(client2, settings)  # type: ignore[arg-type]
    collector2.collect(DouyinCollectRequest(run_id="run", output_root=tmp_path, mode="mock", resume=True))
    assert len(csv_rows(processed / "videos.csv")) == 2
    assert len(csv_rows(processed / "comments.csv")) == 2
    text_items = csv_rows(processed / "text_items.csv")
    assert [row["item_type"] for row in text_items] == ["video_caption", "video_caption", "comment", "mention", "reply"]
    assert [row["source"] for row in text_items] == ["videos.csv", "videos.csv", "comments.csv", "comments.csv", "comments.csv"]
    by_type = {row["item_type"]: row for row in text_items}
    assert by_type["comment"]["target_user_id"] == "creator1"
    assert by_type["reply"]["target_user_id"] == "u1"
    assert by_type["mention"]["target_user_id"] == "u2"


def test_search_v2_default_when_no_challenge_id(tmp_path: Path) -> None:
    settings = TikHubSettings(max_videos=1, max_comments_per_video=0, max_replies_per_comment=0)
    client = FixtureClient(load_fixture(no_challenge=True))
    client.settings = settings
    paths = DouyinCollector(client, settings).collect(DouyinCollectRequest(run_id="fallback", output_root=tmp_path, mode="mock"))  # type: ignore[arg-type]
    assert client.endpoint_call_counts.get("hashtag_video_list", 0) == 1
    assert client.endpoint_call_counts.get("video_search_v2", 0) == 0
    assert client.endpoint_call_counts.get("video_search", 0) == 0
    assert csv_rows(paths["processed_dir"] / "videos.csv")[0]["video_id"] == "v1"


def test_partial_profile_failure_records_failed_pages_and_skipped_users(tmp_path: Path) -> None:
    class FailingProfileFixture(FixtureClient):
        def fetch_batch_user_profile(self, sec_user_ids: list[str]) -> Any:
            raise RuntimeError("profile batch failed")

        def handler_user_profile(self, sec_user_id: str) -> Any:
            raise RuntimeError("profile single failed")

    settings = TikHubSettings(max_videos=1, max_comments_per_video=1, max_replies_per_comment=1, max_users=2)
    client = FailingProfileFixture(load_fixture())
    client.settings = settings
    paths = DouyinCollector(client, settings).collect(DouyinCollectRequest(run_id="partial", output_root=tmp_path, mode="mock"))  # type: ignore[arg-type]
    report = json.loads(paths["report"].read_text(encoding="utf-8"))
    assert report["failed_pages"]
    assert report["skipped_users"]
    assert report["mode"] == "mock"


def test_live_marker_skips_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TIKHUB_LIVE_FETCH", raising=False)
    monkeypatch.delenv("TIKHUB_API_KEY", raising=False)
    settings = TikHubSettings.from_env({})
    ready, reason = settings.live_readiness()
    assert ready is False
    assert reason


def test_failed_pages_are_not_checkpointed_and_resume_retries(tmp_path: Path) -> None:
    class FlakyCommentsFixture(FixtureClient):
        def __init__(self, fixture: dict[str, Any]) -> None:
            super().__init__(fixture)
            self.fail_once = True

        def fetch_video_comments(self, **params: Any) -> Any:
            if self.fail_once:
                self.fail_once = False
                from llm_abm_sim.data_sources.tikhub_client import TikHubClientError

                raise TikHubClientError("temporary comments failure")
            return super().fetch_video_comments(**params)

    settings = TikHubSettings(max_videos=1, max_comments_per_video=1, max_replies_per_comment=1, max_users=4)
    client = FlakyCommentsFixture(load_fixture())
    client.settings = settings
    paths = DouyinCollector(client, settings).collect(DouyinCollectRequest(run_id="retry", output_root=tmp_path, mode="mock"))  # type: ignore[arg-type]
    checkpoint = json.loads((paths["raw_dir"] / "checkpoints.json").read_text(encoding="utf-8"))
    assert "comments:v1" not in checkpoint["completed"]
    assert json.loads(paths["report"].read_text(encoding="utf-8"))["failed_pages"]

    client2 = FixtureClient(load_fixture())
    client2.settings = settings
    paths = DouyinCollector(client2, settings).collect(DouyinCollectRequest(run_id="retry", output_root=tmp_path, mode="mock", resume=True))  # type: ignore[arg-type]
    checkpoint = json.loads((paths["raw_dir"] / "checkpoints.json").read_text(encoding="utf-8"))
    assert checkpoint["completed"]["comments:v1"] is True
    assert len(csv_rows(paths["processed_dir"] / "comments.csv")) == 2


def test_non_resume_refuses_existing_run_directory(tmp_path: Path) -> None:
    settings = TikHubSettings(max_videos=1, max_comments_per_video=0, max_replies_per_comment=0, max_users=0)
    client = FixtureClient(load_fixture())
    client.settings = settings
    DouyinCollector(client, settings).collect(DouyinCollectRequest(run_id="fresh-only", output_root=tmp_path, mode="mock"))  # type: ignore[arg-type]

    client2 = FixtureClient(load_fixture())
    client2.settings = settings
    with pytest.raises(FileExistsError, match="without --resume"):
        DouyinCollector(client2, settings).collect(DouyinCollectRequest(run_id="fresh-only", output_root=tmp_path, mode="mock"))  # type: ignore[arg-type]


def test_quota_blocker_records_failed_page_and_stops_before_profiles(tmp_path: Path) -> None:
    class QuotaBlockedRepliesFixture(FixtureClient):
        def __init__(self, fixture: dict[str, Any]) -> None:
            super().__init__(fixture)
            self.profile_calls = 0

        def fetch_video_comment_replies(self, **params: Any) -> Any:
            from llm_abm_sim.data_sources.tikhub_client import TikHubClientError

            raise TikHubClientError("HTTP 402: Insufficient balance")

        def handler_user_profile(self, sec_user_id: str) -> Any:
            self.profile_calls += 1
            return super().handler_user_profile(sec_user_id)

    settings = TikHubSettings(max_videos=1, max_comments_per_video=1, max_replies_per_comment=1, max_users=4)
    client = QuotaBlockedRepliesFixture(load_fixture())
    client.settings = settings
    paths = DouyinCollector(client, settings).collect(DouyinCollectRequest(run_id="quota", output_root=tmp_path, mode="mock"))  # type: ignore[arg-type]
    report = json.loads(paths["report"].read_text(encoding="utf-8"))

    assert report["selection_metadata"]["quota_blocked"] is True
    assert report["failed_pages"]
    assert "HTTP 402" in report["failed_pages"][0]["error"]
    assert client.profile_calls == 0


def test_date_window_filters_out_of_range_videos_before_comments(tmp_path: Path) -> None:
    fixture = load_fixture()
    fixture["video_details"]["v2"]["create_time"] = "2024-01-01T00:00:00"
    settings = TikHubSettings(max_videos=2, max_comments_per_video=1, max_replies_per_comment=1, max_users=4)
    client = FixtureClient(fixture)
    client.settings = settings
    paths = DouyinCollector(client, settings).collect(
        DouyinCollectRequest(
            run_id="date-window",
            output_root=tmp_path,
            mode="mock",
            start_date="2025-01-01",
            end_date="2025-12-31",
        )
    )  # type: ignore[arg-type]
    videos = csv_rows(paths["processed_dir"] / "videos.csv")
    assert [row["video_id"] for row in videos] == ["v1"]
    assert client.endpoint_call_counts.get("comments", 0) == 0 or "v2" not in (paths["raw_dir"] / "comments.jsonl").read_text(encoding="utf-8")


def test_hashtag_video_list_is_used_before_keyword_search(tmp_path: Path) -> None:
    class OrderedSearchFixture(FixtureClient):
        def __init__(self, fixture: dict[str, Any]) -> None:
            super().__init__(fixture)
            self.calls: list[str] = []

        def _get(self, key: str) -> Any:
            self.calls.append(key)
            return super()._get(key)

        def fetch_topic_query(self, **payload: Any) -> Any:  # pragma: no cover - should not be called when hashtag list succeeds.
            raise AssertionError("legacy topic_query must not run before successful hashtag video list")

    fixture = load_fixture()
    settings = TikHubSettings(max_videos=1, max_comments_per_video=0, max_replies_per_comment=0, max_users=4)
    client = OrderedSearchFixture(fixture)
    client.settings = settings

    paths = DouyinCollector(client, settings).collect(DouyinCollectRequest(run_id="search-v2", output_root=tmp_path, mode="mock"))  # type: ignore[arg-type]

    assert client.calls[:2] == ["challenge_search_v2", "hashtag_video_list"]
    assert "video_search_v2" not in client.calls
    assert "topic_query" not in client.calls
    assert csv_rows(paths["processed_dir"] / "videos.csv")[0]["video_id"] == "v1"


def test_search_v2_fallbacks_precede_legacy_topic_query(tmp_path: Path) -> None:
    class EmptyVideoSearchFixture(FixtureClient):
        def __init__(self, fixture: dict[str, Any]) -> None:
            super().__init__(fixture)
            self.calls: list[str] = []

        def _get(self, key: str) -> Any:
            self.calls.append(key)
            return super()._get(key)

        def fetch_topic_query(self, **payload: Any) -> Any:
            raise AssertionError("legacy topic_query must not run when general Search V2 succeeds")

    fixture = load_fixture()
    fixture["challenge_search_v2"] = {"data": {"business_data": []}}
    fixture["video_search_v2"] = {"data": {"business_data": []}}
    fixture["general_search_v2"] = {"data": {"business_data": [{"data": {"aweme_info": {"aweme_id": "v2"}}}]}}
    settings = TikHubSettings(max_videos=1, max_comments_per_video=0, max_replies_per_comment=0, max_users=4)
    client = EmptyVideoSearchFixture(fixture)
    client.settings = settings

    paths = DouyinCollector(client, settings).collect(DouyinCollectRequest(run_id="general-v2", output_root=tmp_path, mode="mock"))  # type: ignore[arg-type]

    assert client.calls[:3] == ["challenge_search_v2", "video_search_v2", "general_search_v2"]
    assert "topic_query" not in client.calls
    assert csv_rows(paths["processed_dir"] / "videos.csv")[0]["video_id"] == "v2"


def test_profiles_use_app_v3_single_profile_not_legacy_batch(tmp_path: Path) -> None:
    class NoBatchFixture(FixtureClient):
        def __init__(self, fixture: dict[str, Any]) -> None:
            super().__init__(fixture)
            self.profile_calls: list[str] = []

        def fetch_batch_user_profile(self, sec_user_ids: list[str]) -> Any:
            raise AssertionError("legacy batch profile endpoint should not be used by active collector")

        def handler_user_profile(self, sec_user_id: str) -> Any:
            self.profile_calls.append(sec_user_id)
            return super().handler_user_profile(sec_user_id)

    settings = TikHubSettings(max_videos=1, max_comments_per_video=1, max_replies_per_comment=1, max_users=4)
    client = NoBatchFixture(load_fixture())
    client.settings = settings

    paths = DouyinCollector(client, settings).collect(DouyinCollectRequest(run_id="profile-v3", output_root=tmp_path, mode="mock"))  # type: ignore[arg-type]

    assert client.profile_calls
    report = json.loads(paths["report"].read_text(encoding="utf-8"))
    assert report["counts"]["users"] >= 1


def test_missing_video_search_v2_uses_general_before_legacy_video_search(tmp_path: Path) -> None:
    class MissingVideoSearchV2Fixture(FixtureClient):
        def __init__(self, fixture: dict[str, Any]) -> None:
            super().__init__(fixture)
            self.calls: list[str] = []

        def _get(self, key: str) -> Any:
            self.calls.append(key)
            return super()._get(key)

        def fetch_video_search(self, **payload: Any) -> Any:
            raise AssertionError("legacy video_search must not run before general/challenge Search V2")

    fixture = load_fixture()
    fixture["challenge_search_v2"] = {"data": {"business_data": []}}
    fixture.pop("video_search_v2", None)
    fixture["general_search_v2"] = {"data": {"business_data": [{"data": {"aweme_info": {"aweme_id": "v2"}}}]}}
    settings = TikHubSettings(max_videos=1, max_comments_per_video=0, max_replies_per_comment=0, max_users=4)
    client = MissingVideoSearchV2Fixture(fixture)
    client.settings = settings

    paths = DouyinCollector(client, settings).collect(DouyinCollectRequest(run_id="missing-video-v2", output_root=tmp_path, mode="mock"))  # type: ignore[arg-type]

    assert client.calls[:3] == ["challenge_search_v2", "video_search_v2", "general_search_v2"]
    assert "video_search" not in client.calls
    assert csv_rows(paths["processed_dir"] / "videos.csv")[0]["video_id"] == "v2"


def test_date_window_uses_nested_app_v3_detail_create_time(tmp_path: Path) -> None:
    fixture = load_fixture()
    fixture["video_details"]["v1"] = {
        "video_id": "v1",
        "data": {"aweme_detail": {"aweme_id": "v1", "caption": "old", "create_time": "2024-01-01T00:00:00", "author_user_id": "creator1"}},
    }
    fixture["video_details"]["v2"] = {
        "video_id": "v2",
        "data": {"aweme_detail": {"aweme_id": "v2", "caption": "new", "create_time": "2025-06-02T00:00:00", "author_user_id": "creator2"}},
    }
    settings = TikHubSettings(max_videos=2, max_comments_per_video=0, max_replies_per_comment=0, max_users=4)
    client = FixtureClient(fixture)
    client.settings = settings

    paths = DouyinCollector(client, settings).collect(
        DouyinCollectRequest(run_id="nested-date", output_root=tmp_path, mode="mock", start_date="2025-01-01", end_date="2025-12-31")
    )  # type: ignore[arg-type]

    videos = csv_rows(paths["processed_dir"] / "videos.csv")
    assert [row["video_id"] for row in videos] == ["v2"]
    assert videos[0]["caption"] == "new"


def test_all_out_of_window_details_do_not_fallback_to_unfiltered_search_refs(tmp_path: Path) -> None:
    fixture = load_fixture()
    for video_id in ("v1", "v2"):
        fixture["video_details"][video_id] = {
            "video_id": video_id,
            "data": {
                "aweme_detail": {
                    "aweme_id": video_id,
                    "caption": f"old {video_id}",
                    "create_time": "2024-01-01T00:00:00",
                    "author_user_id": f"creator-{video_id}",
                }
            },
        }
    settings = TikHubSettings(max_videos=2, max_comments_per_video=1, max_replies_per_comment=1, max_users=4)
    client = FixtureClient(fixture)
    client.settings = settings

    paths = DouyinCollector(client, settings).collect(
        DouyinCollectRequest(run_id="all-out-of-window", output_root=tmp_path, mode="mock", start_date="2025-01-01", end_date="2025-12-31")
    )  # type: ignore[arg-type]

    processed = paths["processed_dir"]
    assert csv_rows(processed / "videos.csv") == []
    assert csv_rows(processed / "comments.csv") == []
    assert csv_rows(processed / "text_items.csv") == []
    report = json.loads((processed / "collection_report.json").read_text(encoding="utf-8"))
    assert report["counts"]["videos"] == 0
    assert report["counts"]["text_items"] == 0
    assert client.endpoint_call_counts.get("fetch_video_comments", 0) == 0


def test_search_v2_paginates_until_max_videos(tmp_path: Path) -> None:
    fixture = load_fixture()
    fixture["challenge_search_v2"] = {"data": {"business_data": []}}
    fixture["video_search_v2"] = {}
    fixture["video_search_v2_pages"] = {
        "0": {"data": {"business_data": [{"data": {"aweme_info": {"aweme_id": "v1"}}}]}},
        "1": {"data": {"business_data": [{"data": {"aweme_info": {"aweme_id": "v2"}}}]}},
        "2": {"data": {"business_data": []}},
    }
    settings = TikHubSettings(max_videos=2, max_comments_per_video=0, max_replies_per_comment=0, max_users=4, max_search_pages=3, search_page_size=1)
    client = FixtureClient(fixture)
    client.settings = settings

    paths = DouyinCollector(client, settings).collect(DouyinCollectRequest(run_id="paged", output_root=tmp_path, mode="mock"))  # type: ignore[arg-type]

    assert client.endpoint_call_counts.get("video_search_v2", 0) == 2
    assert [row["video_id"] for row in csv_rows(paths["processed_dir"] / "videos.csv")] == ["v1", "v2"]
    page_files = sorted(path.name for path in (paths["raw_dir"] / "pages").glob("video_search_v2_cursor_*.json"))
    assert page_files == ["video_search_v2_cursor_0.json", "video_search_v2_cursor_1.json"]


def test_batch_selection_manifest_unbounded_collects_all_fixture_pages(tmp_path: Path) -> None:
    fixture = load_fixture()
    fixture["hashtag_video_list_pages"] = {
        "0": {"data": {"aweme_list": [{"aweme_id": "v1"}], "cursor": 1, "has_more": True}},
        "1": {"data": {"aweme_list": [{"aweme_id": "v2"}], "cursor": 2, "has_more": False}},
    }
    settings = TikHubSettings(
        max_videos=None,
        max_comments_per_video=None,
        max_replies_per_comment=None,
        max_users=None,
        max_search_pages=None,
        search_page_size=1,
    )
    client = FixtureClient(fixture)
    client.settings = settings
    paths = DouyinCollector(client, settings).collect(
        DouyinCollectRequest(
            run_id="batch-unbounded",
            output_root=tmp_path,
            mode="mock",
            challenge_selections=[
                __import__("llm_abm_sim.data_sources.douyin_collector", fromlist=["DouyinChallengeSelection"]).DouyinChallengeSelection(
                    rank=1, name="锦江酒店", challenge_id="cha_jj", source="test-manifest"
                )
            ],
            selection_source="test-manifest.json",
            collection_scope="top10_challenge_batch",
        )
    )  # type: ignore[arg-type]

    assert client.endpoint_call_counts.get("hashtag_video_list", 0) == 2
    assert [row["video_id"] for row in csv_rows(paths["processed_dir"] / "videos.csv")] == ["v1", "v2"]
    report = json.loads(paths["report"].read_text(encoding="utf-8"))
    assert report["limit_profile"] == "unbounded"
    assert report["limits"]["max_videos"] is None
    assert report["selection_metadata"]["collection_scope"] == "top10_challenge_batch"
    assert report["selection_metadata"]["challenge_selections"][0]["challenge_id"] == "cha_jj"


def test_resume_does_not_probe_after_cached_partial_reply_page(tmp_path: Path) -> None:
    fixture = load_fixture()
    settings = TikHubSettings(
        max_videos=1,
        max_comments_per_video=None,
        max_replies_per_comment=None,
        max_users=4,
        search_page_size=20,
    )
    client = FixtureClient(fixture)
    client.settings = settings
    DouyinCollector(client, settings).collect(DouyinCollectRequest(run_id="resume-replies", output_root=tmp_path, mode="mock"))  # type: ignore[arg-type]

    class NoReplyProbeFixture(FixtureClient):
        def fetch_video_comment_replies(self, **params: Any) -> Any:
            if int(params.get("cursor", 0)) > 0:
                raise AssertionError("resume must not probe past cached partial reply pages")
            return super().fetch_video_comment_replies(**params)

    client2 = NoReplyProbeFixture(fixture)
    client2.settings = settings
    DouyinCollector(client2, settings).collect(
        DouyinCollectRequest(run_id="resume-replies", output_root=tmp_path, mode="mock", resume=True)
    )  # type: ignore[arg-type]


def test_metadata_only_stages_skip_comments_replies_and_profiles(tmp_path: Path) -> None:
    class EndpointGuardFixture(FixtureClient):
        def fetch_video_comments(self, **params: Any) -> Any:
            raise AssertionError("metadata-only run must not call comments endpoint")

        def fetch_video_comment_replies(self, **params: Any) -> Any:
            raise AssertionError("metadata-only run must not call replies endpoint")

        def handler_user_profile(self, sec_user_id: str) -> Any:
            raise AssertionError("metadata-only run must not call profile endpoint")

    settings = TikHubSettings(max_videos=2, max_comments_per_video=1, max_replies_per_comment=1, max_users=4)
    client = EndpointGuardFixture(load_fixture())
    client.settings = settings

    paths = DouyinCollector(client, settings).collect(
        DouyinCollectRequest(
            run_id="metadata-only",
            output_root=tmp_path,
            mode="mock",
            stages=("challenge_index", "video_metadata"),
        )
    )  # type: ignore[arg-type]

    processed = paths["processed_dir"]
    assert len(csv_rows(processed / "videos.csv")) == 2
    assert csv_rows(processed / "comments.csv") == []
    assert csv_rows(processed / "profiles.csv") == []
    report = json.loads(paths["report"].read_text(encoding="utf-8"))
    assert report["comments_collected"] is False
    assert report["profiles_collected"] is False
    assert report["stage_status"]["comments"] == "disabled"
    assert report["stage_status"]["profiles"] == "disabled"
    assert report["stage_counts"]["selected_video_ids"] == 2
    assert report["stage_counts"]["video_detail_succeeded"] == 2
    assert client.endpoint_call_counts.get("fetch_video_comments", 0) == 0
    assert client.endpoint_call_counts.get("fetch_video_comment_replies", 0) == 0
    assert client.endpoint_call_counts.get("handler_user_profile", 0) == 0
