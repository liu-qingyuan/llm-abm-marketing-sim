from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "collect_jinjiang_user_profiles.py"
spec = importlib.util.spec_from_file_location("collect_jinjiang_user_profiles", SCRIPT_PATH)
assert spec and spec.loader
profiles = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = profiles
spec.loader.exec_module(profiles)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def make_source(tmp_path: Path, *, sec: str = "u1", creator_sec: str = "sec_creator") -> Path:
    src = tmp_path / "processed" / "source-run"
    write_csv(
        src / "users.csv",
        ["user_id", "sec_user_id", "nickname", "follower_count", "following_count", "video_count", "verified_type", "bio", "observed_activity_level", "observed_influence"],
        [
            {"user_id": "u1", "sec_user_id": sec},
            {"user_id": "creator", "sec_user_id": creator_sec},
        ],
    )
    write_csv(
        src / "videos.csv",
        ["video_id", "caption", "hashtags", "creator_user_id", "source_challenge_name"],
        [{"video_id": "v1", "caption": "#锦江都城酒店吉安", "hashtags": '["锦江都城酒店吉安"]', "creator_user_id": "creator", "source_challenge_name": "锦江都城酒店吉安"}],
    )
    write_csv(
        src / "target_video_manifest.csv",
        ["video_id", "matched_caption_hashtags"],
        [{"video_id": "v1", "matched_caption_hashtags": "#锦江都城酒店吉安"}],
    )
    write_csv(
        src / "comments.csv",
        ["comment_id", "video_id", "parent_comment_id", "commenter_user_id", "mentioned_user_ids", "like_count", "comment_level", "content"],
        [{"comment_id": "c1", "video_id": "v1", "commenter_user_id": "u1", "mentioned_user_ids": '["m1"]', "like_count": "3", "comment_level": "comment", "content": "喜欢锦江"}],
    )
    write_csv(src / "edges.csv", ["source", "target", "weight"], [{"source": "u1", "target": "creator", "weight": "2"}])
    write_csv(src / "text_items.csv", ["user_id", "text"], [{"user_id": "u1", "text": "锦江 酒店"}])
    write_csv(src / "profiles.csv", profiles.PROFILE_COLUMNS, [])
    (src / "collection_report.json").write_text(json.dumps({"profiles_collected": False}, ensure_ascii=False), encoding="utf-8")
    return src


def test_placeholder_sec_user_id_produces_no_call_state_b(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = make_source(tmp_path, sec="u1", creator_sec="creator")
    called = False

    class BoomClient:
        def __init__(self, settings: Any) -> None:
            nonlocal called
            called = True

    monkeypatch.setattr(profiles, "TikHubClient", BoomClient)
    code = profiles.main([
        "--source-run", str(src),
        "--processed-root", str(tmp_path / "out"),
        "--raw-root", str(tmp_path / "raw"),
        "--docs-dir", str(tmp_path / "docs"),
        "--output-run-id", "profile-run",
        "--resume",
    ])
    assert code == 0
    assert called is False
    report = json.loads((tmp_path / "out" / "profile-run" / "profile_collection_report.json").read_text(encoding="utf-8"))
    assert report["attempted_profiles"] == 0
    assert report["partial"] is True
    assert report["partial_reason"] == "no_confirmed_sec_uid"
    targets = read_csv(tmp_path / "out" / "profile-run" / "profile_target_users.csv")
    assert {row["user_id"]: row["sec_user_id_confidence"] for row in targets}["u1"] == "placeholder"


def test_raw_sec_uid_recovery_and_abm_provenance(tmp_path: Path) -> None:
    src = make_source(tmp_path, sec="u1")
    raw_source = tmp_path / "raw" / "source-run"
    write_jsonl(raw_source / "comments.jsonl", [{"user": {"uid": "u1", "sec_uid": "sec_u1_real"}}])
    rows, audit, _historical = profiles.build_profile_targets(src, tmp_path / "processed", tmp_path / "raw")
    by_uid = {row["user_id"]: row for row in rows}
    assert by_uid["u1"]["sec_user_id"] == "sec_u1_real"
    assert by_uid["u1"]["sec_user_id_source"] == "raw_comments"
    assert audit["confirmed_sec_uid_users"] == 2
    assert audit["source_raw_run_path"] == str(raw_source)


def test_source_raw_run_override_recovers_sec_uid_when_run_id_differs(tmp_path: Path) -> None:
    src = make_source(tmp_path, sec="u1")
    raw_source = tmp_path / "raw" / "renamed-source-raw"
    write_jsonl(raw_source / "comments.jsonl", [{"user": {"uid": "u1", "sec_uid": "sec_u1_real"}}])

    rows, audit, _historical = profiles.build_profile_targets(
        src,
        tmp_path / "processed",
        tmp_path / "raw",
        source_raw_run=raw_source,
    )

    by_uid = {row["user_id"]: row for row in rows}
    assert by_uid["u1"]["sec_user_id"] == "sec_u1_real"
    assert by_uid["u1"]["sec_user_id_source"] == "raw_comments"
    assert audit["source_raw_run_path"] == str(raw_source)


def test_live_profile_wins_over_historical_and_reports_are_private(tmp_path: Path) -> None:
    src = make_source(tmp_path, sec="sec_u1")
    processed_root = tmp_path / "processed"
    hist = processed_root / "old" / "users.csv"
    write_csv(hist, ["user_id", "sec_user_id", "nickname", "follower_count", "following_count", "video_count", "verified_type", "bio"], [{"user_id": "u1", "sec_user_id": "sec_u1", "nickname": "OLDNAME", "follower_count": "1", "bio": "OLDBIO"}])
    raw_run = tmp_path / "raw" / "profile-run"
    write_jsonl(raw_run / "user_profiles.jsonl", [{"user_id": "u1", "sec_user_id": "sec_u1", "items": [{"uid": "u1", "sec_uid": "sec_u1", "nickname": "LIVENAME", "follower_count": 99, "signature": "LIVEBIO"}]}])
    target_rows, _audit, historical = profiles.build_profile_targets(src, processed_root, tmp_path / "raw")
    stats = profiles.CollectionStats(attempted=1, succeeded=1)
    profiles.build_processed_outputs(src, processed_root / "profile-run", raw_run, target_rows, historical, stats)
    users = read_csv(processed_root / "profile-run" / "users.csv")
    u1 = {row["user_id"]: row for row in users}["u1"]
    assert u1["nickname"] == "LIVENAME"
    assert u1["follower_count"] == "99"
    abm = {row["user_id"]: row for row in read_csv(processed_root / "profile-run" / "abm_user_profiles.csv")}["u1"]
    provenance = json.loads(abm["attribute_provenance"])
    assert "brand_attitude" in provenance["defaulted_future_model_fields"]
    assert "share_tendency" in provenance["defaulted_future_model_fields"]


def test_resume_skips_success_and_no_duplicate_profiles(tmp_path: Path) -> None:
    src = make_source(tmp_path, sec="sec_u1")
    raw_run = tmp_path / "raw" / "profile-run"
    write_csv(raw_run / "profile_status.csv", profiles.STATUS_COLUMNS, [
        {"user_id": "u1", "sec_user_id": "sec_u1", "status": "success", "error": "", "attempted_at": "now"},
        {"user_id": "creator", "sec_user_id": "sec_creator", "status": "success", "error": "", "attempted_at": "now"},
    ])
    write_jsonl(raw_run / "user_profiles.jsonl", [
        {"user_id": "u1", "sec_user_id": "sec_u1", "items": [{"uid": "u1", "sec_uid": "sec_u1", "follower_count": 5}]},
        {"user_id": "creator", "sec_user_id": "sec_creator", "items": [{"uid": "creator", "sec_uid": "sec_creator", "follower_count": 8}]},
    ])

    class NoCallClient:
        endpoint_call_counts: dict[str, int] = {}
        def handler_user_profile(self, sec_user_id: str) -> Any:  # pragma: no cover - should not be called
            raise AssertionError("resume should skip")

    targets, _audit, historical = profiles.build_profile_targets(src, tmp_path / "processed", tmp_path / "raw")
    stats = profiles.collect_profiles(targets, raw_run, NoCallClient(), resume=True, max_users=None, api_key="")  # type: ignore[arg-type]
    assert stats.attempted == 0
    profiles.build_processed_outputs(src, tmp_path / "processed" / "profile-run", raw_run, targets, historical, stats)
    prof_rows = read_csv(tmp_path / "processed" / "profile-run" / "profiles.csv")
    assert len([row for row in prof_rows if row["user_id"] == "u1"]) == 1


def test_markdown_scan_rejects_headers_not_fixture_names(tmp_path: Path) -> None:
    safe = tmp_path / "safe.md"
    safe.write_text("聚合统计 only; no nickname details.\n", encoding="utf-8")
    unsafe = tmp_path / "unsafe.md"
    unsafe.write_text("Authorization: Bearer abc\n", encoding="utf-8")
    assert profiles.scan_report_safety([safe]) == []
    assert profiles.scan_report_safety([unsafe])


def test_default_capped_mode_uses_settings_max_users(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = make_source(tmp_path, sec="sec_u1")
    monkeypatch.setenv("TIKHUB_LIVE_FETCH", "1")
    monkeypatch.setenv("TIKHUB_API_KEY", "test-key")
    monkeypatch.setenv("TIKHUB_MAX_USERS", "1")

    class CountingClient:
        def __init__(self, settings: Any) -> None:
            self.settings = settings
            self.endpoint_call_counts: dict[str, int] = {}

        def handler_user_profile(self, sec_user_id: str) -> Any:
            self.endpoint_call_counts["handler_user_profile"] = self.endpoint_call_counts.get("handler_user_profile", 0) + 1
            if sec_user_id == "sec_creator":
                return {"user": {"uid": "creator", "sec_uid": "sec_creator", "follower_count": 10}}
            return {"user": {"uid": "u1", "sec_uid": "sec_u1", "follower_count": 5}}

    monkeypatch.setattr(profiles, "TikHubClient", CountingClient)
    code = profiles.main([
        "--source-run", str(src),
        "--processed-root", str(tmp_path / "out"),
        "--raw-root", str(tmp_path / "raw"),
        "--docs-dir", str(tmp_path / "docs"),
        "--output-run-id", "profile-run",
        "--resume",
    ])
    assert code == 0
    report = json.loads((tmp_path / "out" / "profile-run" / "profile_collection_report.json").read_text(encoding="utf-8"))
    assert report["attempted_profiles"] == 1
    assert report["successful_profiles"] == 1
    assert report["limit_profile"] == "capped"


def test_identity_mismatch_or_empty_live_profile_is_not_success(tmp_path: Path) -> None:
    src = make_source(tmp_path, sec="sec_u1", creator_sec="creator")
    targets, _audit, historical = profiles.build_profile_targets(src, tmp_path / "processed", tmp_path / "raw")

    class MismatchClient:
        endpoint_call_counts: dict[str, int] = {}

        def handler_user_profile(self, sec_user_id: str) -> Any:
            self.endpoint_call_counts["handler_user_profile"] = self.endpoint_call_counts.get("handler_user_profile", 0) + 1
            return {"user": {"uid": "other", "sec_uid": "sec_other", "follower_count": 999}}

    raw_run = tmp_path / "raw" / "profile-run"
    stats = profiles.collect_profiles(targets, raw_run, MismatchClient(), resume=True, max_users=None, api_key="")  # type: ignore[arg-type]
    assert stats.attempted == 1
    assert stats.succeeded == 0
    assert stats.failed == 1
    statuses = read_csv(raw_run / "profile_status.csv")
    assert statuses[0]["status"] == "failed"
    assert statuses[0]["error"] == "identity_mismatch_or_empty_profile_response"
    assert not (raw_run / "user_profiles.jsonl").exists()
    profiles.build_processed_outputs(src, tmp_path / "processed" / "profile-run", raw_run, targets, historical, stats)
    assert read_csv(tmp_path / "processed" / "profile-run" / "profiles.csv") == []
