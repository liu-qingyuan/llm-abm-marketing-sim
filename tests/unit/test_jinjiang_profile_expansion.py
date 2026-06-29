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
    assert by_uid["u1"]["sec_user_id_source"] == "raw_comments:source-run"
    assert audit["confirmed_sec_uid_users"] == 2
    assert audit["source_raw_run_path"] == str(raw_source)
    assert audit["sec_uid_evidence_audit"]["accepted_users"] == 1


def test_raw_placeholder_sec_uid_evidence_is_rejected(tmp_path: Path) -> None:
    src = make_source(tmp_path, sec="u1", creator_sec="creator")
    raw_source = tmp_path / "raw" / "source-run"
    write_jsonl(raw_source / "comments.jsonl", [{"user": {"uid": "u1", "sec_uid": "u1"}}])

    rows, audit, _historical = profiles.build_profile_targets(src, tmp_path / "processed", tmp_path / "raw")

    by_uid = {row["user_id"]: row for row in rows}
    assert by_uid["u1"]["sec_user_id_confidence"] == "placeholder"
    assert by_uid["u1"]["profile_fetch_status"] == "skipped"
    evidence_audit = audit["sec_uid_evidence_audit"]
    assert evidence_audit["accepted_users"] == 0
    assert evidence_audit["rejected_empty_or_placeholder"] == 1


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
    assert by_uid["u1"]["sec_user_id_source"] == "raw_comments:renamed-source-raw"
    assert audit["source_raw_run_path"] == str(raw_source)


def test_sec_uid_evidence_run_must_stay_under_raw_root(tmp_path: Path) -> None:
    src = make_source(tmp_path, sec="u1")
    outside = tmp_path / "outside" / "raw-run"
    outside.mkdir(parents=True)

    with pytest.raises(ValueError, match="raw evidence run must be under"):
        profiles.build_profile_targets(
            src,
            tmp_path / "processed",
            tmp_path / "raw",
            sec_uid_evidence_runs=[outside],
        )


def test_multi_run_sec_uid_evidence_glob_and_conflict_audit(tmp_path: Path) -> None:
    src = make_source(tmp_path, sec="u1", creator_sec="creator")
    raw_root = tmp_path / "raw"
    write_jsonl(raw_root / "evidence-b" / "comments.jsonl", [{"user": {"uid": "u1", "sec_uid": "sec_from_b"}}])
    write_jsonl(raw_root / "evidence-a" / "comments.jsonl", [{"user": {"uid": "u1", "sec_uid": "sec_from_a"}}])
    write_jsonl(raw_root / "explicit-run" / "comment_replies.jsonl", [{"user": {"uid": "creator", "sec_uid": "sec_creator_raw"}}])

    rows, audit, _historical = profiles.build_profile_targets(
        src,
        tmp_path / "processed",
        raw_root,
        sec_uid_evidence_runs=[Path("explicit-run")],
        sec_uid_evidence_globs=["evidence-*"],
    )

    by_uid = {row["user_id"]: row for row in rows}
    assert by_uid["u1"]["sec_user_id"] == "sec_from_a"
    assert by_uid["u1"]["sec_user_id_source"] == "raw_comments:evidence-a"
    assert by_uid["creator"]["sec_user_id"] == "sec_creator_raw"
    assert by_uid["creator"]["sec_user_id_source"] == "raw_replies:explicit-run"
    evidence_audit = audit["sec_uid_evidence_audit"]
    assert evidence_audit["conflict_count"] == 1
    assert evidence_audit["scanned_run_count"] == 3  # explicit plus two glob runs; default source raw is missing
    assert str(raw_root / "source-run") in evidence_audit["missing_run_paths"]
    assert evidence_audit["accepted_by_source"]["raw_comments:evidence-a"] == 1


def test_page_level_raw_evidence_is_scanned_without_payload_leak(tmp_path: Path) -> None:
    src = make_source(tmp_path, sec="u1", creator_sec="creator")
    raw_root = tmp_path / "raw"
    (raw_root / "page-run" / "pages").mkdir(parents=True)
    (raw_root / "page-run" / "pages" / "candidate_video_metadata_v1.json").write_text(
        json.dumps({"author": {"uid": "u1", "sec_uid": "sec_from_page"}}, ensure_ascii=False),
        encoding="utf-8",
    )

    rows, audit, _historical = profiles.build_profile_targets(
        src,
        tmp_path / "processed",
        raw_root,
        sec_uid_evidence_runs=[Path("page-run")],
    )

    by_uid = {row["user_id"]: row for row in rows}
    assert by_uid["u1"]["sec_user_id"] == "sec_from_page"
    assert by_uid["u1"]["sec_user_id_source"] == "raw_video_details:page-run"
    evidence_audit = audit["sec_uid_evidence_audit"]
    assert evidence_audit["scanned_file_count"] == 1
    assert "sec_from_page" not in json.dumps(evidence_audit, ensure_ascii=False)


def test_historical_processed_sec_uid_does_not_promote_live_call_without_raw_evidence(tmp_path: Path) -> None:
    src = make_source(tmp_path, sec="u1", creator_sec="creator")
    processed_root = tmp_path / "processed"
    write_csv(
        processed_root / "old" / "users.csv",
        ["user_id", "sec_user_id", "nickname", "follower_count"],
        [{"user_id": "u1", "sec_user_id": "sec_from_processed", "nickname": "HIST", "follower_count": "7"}],
    )

    rows, audit, historical = profiles.build_profile_targets(src, processed_root, tmp_path / "raw")
    by_uid = {row["user_id"]: row for row in rows}
    assert by_uid["u1"]["sec_user_id_confidence"] == "placeholder"
    assert by_uid["u1"]["profile_fetch_status"] == "skipped"
    assert "u1" in historical
    assert audit["historical_sec_uid_users"] == 1
    assert audit["confirmed_sec_uid_users"] == 0


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


def test_max_users_applies_after_resume_successes_are_skipped(tmp_path: Path) -> None:
    src = make_source(tmp_path, sec="sec_u1", creator_sec="sec_creator")
    raw_run = tmp_path / "raw" / "profile-run"
    write_csv(raw_run / "profile_status.csv", profiles.STATUS_COLUMNS, [
        {"user_id": "creator", "sec_user_id": "sec_creator", "status": "success", "error": "", "attempted_at": "old"},
    ])
    write_jsonl(raw_run / "user_profiles.jsonl", [
        {"user_id": "creator", "sec_user_id": "sec_creator", "items": [{"uid": "creator", "sec_uid": "sec_creator", "follower_count": 8}]},
    ])

    class OnePendingClient:
        endpoint_call_counts: dict[str, int] = {}

        def handler_user_profile(self, sec_user_id: str) -> Any:
            self.endpoint_call_counts["handler_user_profile"] = self.endpoint_call_counts.get("handler_user_profile", 0) + 1
            return {"user": {"uid": "u1", "sec_uid": "sec_u1", "follower_count": 5}}

    targets, _audit, _historical = profiles.build_profile_targets(src, tmp_path / "processed", tmp_path / "raw")
    stats = profiles.collect_profiles(
        targets,
        raw_run,
        OnePendingClient(),
        resume=True,
        max_users=1,
        api_key="",
    )  # type: ignore[arg-type]

    assert stats.attempted == 1
    assert stats.succeeded == 1
    statuses = {row["user_id"]: row for row in read_csv(raw_run / "profile_status.csv")}
    assert statuses["creator"]["status"] == "success"
    assert statuses["u1"]["status"] == "success"


def test_resumed_report_counts_prior_successes_cumulatively(tmp_path: Path) -> None:
    src = make_source(tmp_path, sec="sec_u1")
    raw_run = tmp_path / "raw" / "profile-run"
    processed_run = tmp_path / "processed" / "profile-run"
    write_csv(raw_run / "profile_status.csv", profiles.STATUS_COLUMNS, [
        {"user_id": "u1", "sec_user_id": "sec_u1", "status": "success", "error": "", "attempted_at": "now"},
    ])
    write_jsonl(raw_run / "user_profiles.jsonl", [
        {"user_id": "u1", "sec_user_id": "sec_u1", "items": [{"uid": "u1", "sec_uid": "sec_u1", "follower_count": 5}]},
    ])
    targets, target_audit, historical = profiles.build_profile_targets(src, tmp_path / "processed", tmp_path / "raw")
    stats = profiles.CollectionStats(attempted=0, succeeded=0)
    counts = profiles.build_processed_outputs(src, processed_run, raw_run, targets, historical, stats)
    report = profiles.build_collection_report(
        run_id="profile-run",
        source_run=src,
        processed_dir=processed_run,
        raw_dir=raw_run,
        target_rows=targets,
        target_audit=target_audit,
        processed_counts=counts,
        stats=stats,
        settings=profiles.TikHubSettings(live_fetch=True, api_key="test-key"),
    )

    assert report["attempted_profiles"] == 1
    assert report["successful_profiles"] == 1
    assert report["profiles_collected"] is True
    assert report["expansion_state"] == "live_profile_partial"
    assert report["current_run_attempted_profiles"] == 0


def test_report_preserves_prior_quota_stopped_partial_reason(tmp_path: Path) -> None:
    src = make_source(tmp_path, sec="sec_u1")
    raw_run = tmp_path / "raw" / "profile-run"
    processed_run = tmp_path / "processed" / "profile-run"
    write_csv(raw_run / "profile_status.csv", profiles.STATUS_COLUMNS, [
        {"user_id": "u1", "sec_user_id": "sec_u1", "status": "success", "error": "", "attempted_at": "now"},
        {"user_id": "creator", "sec_user_id": "sec_creator", "status": "quota_stopped", "error": "HTTP 402", "attempted_at": "now"},
    ])
    write_jsonl(raw_run / "user_profiles.jsonl", [
        {"user_id": "u1", "sec_user_id": "sec_u1", "items": [{"uid": "u1", "sec_uid": "sec_u1", "follower_count": 5}]},
    ])
    targets, target_audit, historical = profiles.build_profile_targets(src, tmp_path / "processed", tmp_path / "raw")
    stats = profiles.CollectionStats()
    counts = profiles.build_processed_outputs(src, processed_run, raw_run, targets, historical, stats)
    report = profiles.build_collection_report(
        run_id="profile-run",
        source_run=src,
        processed_dir=processed_run,
        raw_dir=raw_run,
        target_rows=targets,
        target_audit=target_audit,
        processed_counts=counts,
        stats=stats,
        settings=profiles.TikHubSettings(live_fetch=True, api_key="test-key"),
    )

    assert report["partial"] is True
    assert report["partial_reason"] == "quota_or_rate_limit"
    assert report["quota_or_rate_limited"] is True
    assert report["failed_profiles"] == 1


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


def test_batch_profile_api_validates_each_identity_and_checkpoints(tmp_path: Path) -> None:
    src = make_source(tmp_path, sec="sec_u1", creator_sec="sec_creator")
    targets, _audit, _historical = profiles.build_profile_targets(src, tmp_path / "processed", tmp_path / "raw")

    class BatchClient:
        endpoint_call_counts: dict[str, int] = {}

        def fetch_batch_user_profile(self, sec_user_ids: list[str]) -> Any:
            self.endpoint_call_counts["fetch_batch_user_profile_v2"] = self.endpoint_call_counts.get("fetch_batch_user_profile_v2", 0) + 1
            assert sec_user_ids == ["sec_creator", "sec_u1"]
            return {
                "data": [
                    {"uid": "creator", "sec_uid": "sec_creator", "follower_count": 10},
                    {"uid": "wrong", "sec_uid": "sec_u1", "follower_count": 5},
                ]
            }

    raw_run = tmp_path / "raw" / "profile-run"
    stats = profiles.collect_profiles(targets, raw_run, BatchClient(), resume=True, max_users=None, api_key="", profile_api="batch")  # type: ignore[arg-type]

    assert stats.attempted == 2
    assert stats.succeeded == 1
    assert stats.failed == 1
    statuses = {row["user_id"]: row for row in read_csv(raw_run / "profile_status.csv")}
    assert statuses["creator"]["status"] == "success"
    assert statuses["u1"]["status"] == "failed"
    assert sum(1 for _ in (raw_run / "user_profiles.jsonl").open(encoding="utf-8")) == 1
    assert (raw_run / "rejected_user_profiles.jsonl").exists()


def test_batch_failure_falls_back_to_single_handler_per_user(tmp_path: Path) -> None:
    src = make_source(tmp_path, sec="sec_u1", creator_sec="sec_creator")
    targets, _audit, _historical = profiles.build_profile_targets(src, tmp_path / "processed", tmp_path / "raw")

    class BatchFailHandlerSuccessClient:
        endpoint_call_counts: dict[str, int] = {}

        def fetch_batch_user_profile(self, sec_user_ids: list[str]) -> Any:
            self.endpoint_call_counts["fetch_batch_user_profile_v2"] = self.endpoint_call_counts.get("fetch_batch_user_profile_v2", 0) + 1
            raise RuntimeError("HTTP 400: batch failed")

        def handler_user_profile(self, sec_user_id: str) -> Any:
            self.endpoint_call_counts["handler_user_profile"] = self.endpoint_call_counts.get("handler_user_profile", 0) + 1
            if sec_user_id == "sec_creator":
                return {"user": {"uid": "creator", "sec_uid": "sec_creator", "follower_count": 10}}
            return {"user": {"uid": "u1", "sec_uid": "sec_u1", "follower_count": 5}}

    raw_run = tmp_path / "raw" / "profile-run"
    stats = profiles.collect_profiles(
        targets,
        raw_run,
        BatchFailHandlerSuccessClient(),
        resume=True,
        max_users=None,
        api_key="",
        profile_api="batch",
        batch_handler_fallback=True,
        max_batch_http400_splits=1,
    )  # type: ignore[arg-type]

    assert stats.attempted == 2
    assert stats.succeeded == 2
    assert stats.failed == 0
    statuses = {row["user_id"]: row for row in read_csv(raw_run / "profile_status.csv")}
    assert statuses["creator"]["status"] == "success"
    assert statuses["u1"]["status"] == "success"


def test_http_400_batch_error_with_request_id_digits_is_not_quota() -> None:
    message = (
        'TikHub request failed for fetch_batch_user_profile_v2: HTTP 400: '
        '{"detail":{"code":400,"request_id":"89c75839-2a46-4829-b860-be69fa4b23ec",'
        '"message":"Request failed. Please retry."}}'
    )

    assert profiles.is_quota_error(message) is False
    assert profiles.is_quota_error('TikHub request failed: HTTP 402: {"detail":{"code":402,"message":"Insufficient balance"}}') is True


def test_batch_failure_splits_before_single_handler_fallback(tmp_path: Path) -> None:
    src = make_source(tmp_path, sec="sec_u1", creator_sec="sec_creator")
    targets, _audit, _historical = profiles.build_profile_targets(src, tmp_path / "processed", tmp_path / "raw")
    calls: list[tuple[str, tuple[str, ...]]] = []

    class SplitClient:
        endpoint_call_counts: dict[str, int] = {}

        def fetch_batch_user_profile(self, sec_user_ids: list[str]) -> Any:
            calls.append(("batch", tuple(sec_user_ids)))
            self.endpoint_call_counts["fetch_batch_user_profile_v2"] = self.endpoint_call_counts.get("fetch_batch_user_profile_v2", 0) + 1
            if "sec_u1" in sec_user_ids:
                raise RuntimeError("HTTP 400: batch failed")
            return {"data": [{"uid": "creator", "sec_uid": "sec_creator", "follower_count": 10}]}

        def handler_user_profile(self, sec_user_id: str) -> Any:
            calls.append(("handler", (sec_user_id,)))
            self.endpoint_call_counts["handler_user_profile"] = self.endpoint_call_counts.get("handler_user_profile", 0) + 1
            return {"user": {"uid": "u1", "sec_uid": "sec_u1", "follower_count": 5}}

    raw_run = tmp_path / "raw" / "profile-run"
    stats = profiles.collect_profiles(
        targets,
        raw_run,
        SplitClient(),
        resume=True,
        max_users=None,
        api_key="",
        profile_api="batch",
        batch_handler_fallback=True,
        max_batch_http400_splits=1,
    )  # type: ignore[arg-type]

    assert stats.attempted == 2
    assert stats.succeeded == 2
    assert ("batch", ("sec_creator", "sec_u1")) in calls
    assert ("batch", ("sec_creator",)) in calls
    assert ("handler", ("sec_u1",)) in calls


def test_returned_sec_match_with_wrong_known_uid_is_rejected(tmp_path: Path) -> None:
    src = make_source(tmp_path, sec="sec_u1", creator_sec="sec_creator")
    targets, _audit, _historical = profiles.build_profile_targets(src, tmp_path / "processed", tmp_path / "raw")

    class WrongUidClient:
        endpoint_call_counts: dict[str, int] = {}

        def handler_user_profile(self, sec_user_id: str) -> Any:
            self.endpoint_call_counts["handler_user_profile"] = self.endpoint_call_counts.get("handler_user_profile", 0) + 1
            return {"user": {"uid": "u1", "sec_uid": sec_user_id, "follower_count": 999}}

    raw_run = tmp_path / "raw" / "profile-run"
    stats = profiles.collect_profiles(targets, raw_run, WrongUidClient(), resume=True, max_users=1, api_key="")  # type: ignore[arg-type]
    assert stats.attempted == 1
    assert stats.succeeded == 0
    assert stats.failed == 1
    assert read_csv(raw_run / "profile_status.csv")[0]["error"] == "identity_mismatch_or_empty_profile_response"

def test_resume_can_retry_failed_and_quota_stopped_users(tmp_path: Path) -> None:
    src = make_source(tmp_path, sec="sec_u1", creator_sec="sec_creator")
    raw_run = tmp_path / "raw" / "profile-run"
    write_csv(raw_run / "profile_status.csv", profiles.STATUS_COLUMNS, [
        {"user_id": "u1", "sec_user_id": "sec_u1", "status": "failed", "error": "prior mismatch", "attempted_at": "old"},
        {"user_id": "creator", "sec_user_id": "sec_creator", "status": "quota_stopped", "error": "prior quota", "attempted_at": "old"},
    ])

    class RetryClient:
        endpoint_call_counts: dict[str, int] = {}

        def fetch_batch_user_profile(self, sec_user_ids: list[str]) -> Any:
            self.endpoint_call_counts["fetch_batch_user_profile_v2"] = self.endpoint_call_counts.get("fetch_batch_user_profile_v2", 0) + 1
            return {
                "data": [
                    {"uid": "creator", "sec_uid": "sec_creator", "follower_count": 10},
                    {"uid": "u1", "sec_uid": "sec_u1", "follower_count": 5},
                ]
            }

    targets, _audit, _historical = profiles.build_profile_targets(src, tmp_path / "processed", tmp_path / "raw")
    stats = profiles.collect_profiles(
        targets,
        raw_run,
        RetryClient(),
        resume=True,
        max_users=None,
        api_key="",
        profile_api="batch",
        retry_failed_profiles=True,
    )  # type: ignore[arg-type]

    assert stats.attempted == 2
    assert stats.succeeded == 2
    statuses = {row["user_id"]: row for row in read_csv(raw_run / "profile_status.csv")}
    assert statuses["u1"]["status"] == "success"
    assert statuses["creator"]["status"] == "success"


def test_resume_without_retry_failed_keeps_prior_failures(tmp_path: Path) -> None:
    src = make_source(tmp_path, sec="sec_u1", creator_sec="sec_creator")
    raw_run = tmp_path / "raw" / "profile-run"
    write_csv(raw_run / "profile_status.csv", profiles.STATUS_COLUMNS, [
        {"user_id": "u1", "sec_user_id": "sec_u1", "status": "failed", "error": "prior mismatch", "attempted_at": "old"},
        {"user_id": "creator", "sec_user_id": "sec_creator", "status": "quota_stopped", "error": "prior quota", "attempted_at": "old"},
    ])

    class NoCallBatchClient:
        endpoint_call_counts: dict[str, int] = {}

        def fetch_batch_user_profile(self, sec_user_ids: list[str]) -> Any:  # pragma: no cover - should not be called
            raise AssertionError("failed statuses should not be retried without retry_failed_profiles")

    targets, _audit, _historical = profiles.build_profile_targets(src, tmp_path / "processed", tmp_path / "raw")
    stats = profiles.collect_profiles(
        targets,
        raw_run,
        NoCallBatchClient(),
        resume=True,
        max_users=None,
        api_key="",
        profile_api="batch",
        retry_failed_profiles=False,
    )  # type: ignore[arg-type]

    assert stats.attempted == 0
    statuses = {row["user_id"]: row for row in read_csv(raw_run / "profile_status.csv")}
    assert statuses["u1"]["status"] == "failed"
    assert statuses["creator"]["status"] == "quota_stopped"


def test_quota_error_classifier_distinguishes_request_ids_from_cost_errors() -> None:
    non_quota_messages = [
        'TikHub request failed for fetch_batch_user_profile_v2: HTTP 400: {"detail":{"code":400,"request_id":"89c75839-2a46-4829-b860-be69fa4b23ec","message":"Request failed. Please retry."}}',
        'TikHub request failed: {"code":400,"request_id":"402-429-like-digits","message":"bad request"}',
    ]
    quota_messages = [
        'TikHub request failed: HTTP 402: {"detail":{"code":402,"message":"Insufficient balance"}}',
        'TikHub request failed: {"code":402,"message":"Insufficient balance"}',
        'TikHub request failed: HTTP 429: {"detail":{"code":429,"message":"Too many requests"}}',
        'TikHub request failed: {"code":429,"message":"rate limit"}',
        'insufficient balance / paid quota不足',
        'rate limit exceeded',
        'too many requests',
    ]
    for message in non_quota_messages:
        classified = profiles.classify_profile_error(message)
        assert classified.quota_or_rate_limited is False
        assert profiles.is_quota_error(message) is False
    for message in quota_messages:
        classified = profiles.classify_profile_error(message)
        assert classified.quota_or_rate_limited is True
        assert profiles.is_quota_error(message) is True


def test_batch_quota_error_marks_batch_quota_stopped_without_split_or_handler_fallback(tmp_path: Path) -> None:
    src = make_source(tmp_path, sec="sec_u1", creator_sec="sec_creator")
    targets, _audit, _historical = profiles.build_profile_targets(src, tmp_path / "processed", tmp_path / "raw")
    calls: list[tuple[str, tuple[str, ...]]] = []

    class BatchQuotaClient:
        endpoint_call_counts: dict[str, int] = {}

        def fetch_batch_user_profile(self, sec_user_ids: list[str]) -> Any:
            calls.append(("batch", tuple(sec_user_ids)))
            self.endpoint_call_counts["fetch_batch_user_profile_v2"] = self.endpoint_call_counts.get("fetch_batch_user_profile_v2", 0) + 1
            raise RuntimeError('HTTP 402: {"detail":{"code":402,"message":"Insufficient balance"}}')

        def handler_user_profile(self, sec_user_id: str) -> Any:  # pragma: no cover - must not fallback on quota
            calls.append(("handler", (sec_user_id,)))
            raise AssertionError("batch quota must stop immediately")

    raw_run = tmp_path / "raw" / "profile-run"
    stats = profiles.collect_profiles(
        targets,
        raw_run,
        BatchQuotaClient(),
        resume=True,
        max_users=None,
        api_key="",
        profile_api="batch",
        batch_handler_fallback=True,
    )  # type: ignore[arg-type]

    assert calls == [("batch", ("sec_creator", "sec_u1"))]
    assert stats.partial is True
    assert stats.partial_reason == "quota_or_rate_limit"
    assert stats.quota_or_rate_limited is True
    assert stats.cost_guard_triggered is True
    statuses = {row["user_id"]: row for row in read_csv(raw_run / "profile_status.csv")}
    assert {row["status"] for row in statuses.values()} == {"quota_stopped"}
    assert {row["endpoint"] for row in statuses.values()} == {"fetch_batch_user_profile_v2"}
    assert {row["http_status"] for row in statuses.values()} == {"402"}


def test_handler_quota_error_stops_before_next_user(tmp_path: Path) -> None:
    src = make_source(tmp_path, sec="sec_u1", creator_sec="sec_creator")
    targets, _audit, _historical = profiles.build_profile_targets(src, tmp_path / "processed", tmp_path / "raw")
    calls: list[str] = []

    class HandlerQuotaClient:
        endpoint_call_counts: dict[str, int] = {}

        def handler_user_profile(self, sec_user_id: str) -> Any:
            calls.append(sec_user_id)
            self.endpoint_call_counts["handler_user_profile"] = self.endpoint_call_counts.get("handler_user_profile", 0) + 1
            raise RuntimeError("HTTP 402: insufficient balance")

    raw_run = tmp_path / "raw" / "profile-run"
    stats = profiles.collect_profiles(targets, raw_run, HandlerQuotaClient(), resume=True, max_users=None, api_key="")  # type: ignore[arg-type]

    assert calls == ["sec_creator"]
    assert stats.attempted == 1
    assert stats.partial is True
    statuses = read_csv(raw_run / "profile_status.csv")
    assert len(statuses) == 1
    assert statuses[0]["status"] == "quota_stopped"
    assert statuses[0]["endpoint"] == "handler_user_profile"


def test_cost_safe_default_handler_mode_never_calls_batch(tmp_path: Path) -> None:
    src = make_source(tmp_path, sec="sec_u1", creator_sec="sec_creator")
    targets, _audit, _historical = profiles.build_profile_targets(src, tmp_path / "processed", tmp_path / "raw")

    class HandlerOnlyClient:
        endpoint_call_counts: dict[str, int] = {}

        def fetch_batch_user_profile(self, sec_user_ids: list[str]) -> Any:  # pragma: no cover - cost-safe must not call batch
            raise AssertionError("cost-safe/default mode must not call batch")

        def handler_user_profile(self, sec_user_id: str) -> Any:
            self.endpoint_call_counts["handler_user_profile"] = self.endpoint_call_counts.get("handler_user_profile", 0) + 1
            if sec_user_id == "sec_creator":
                return {"user": {"uid": "creator", "sec_uid": "sec_creator", "follower_count": 10}}
            return {"user": {"uid": "u1", "sec_uid": "sec_u1", "follower_count": 5}}

    stats = profiles.collect_profiles(
        targets,
        tmp_path / "raw" / "profile-run",
        HandlerOnlyClient(),
        resume=True,
        max_users=None,
        api_key="",
        profile_api="cost-safe",
    )  # type: ignore[arg-type]

    assert stats.profile_api_requested == "cost-safe"
    assert stats.profile_api_resolved == "handler"
    assert stats.attempted == 2
    assert stats.succeeded == 2
    assert stats.endpoint_call_counts == {"handler_user_profile": 2}


def test_batch_http400_default_downgrades_to_handler_without_recursive_split(tmp_path: Path) -> None:
    src = make_source(tmp_path, sec="sec_u1", creator_sec="sec_creator")
    targets, _audit, _historical = profiles.build_profile_targets(src, tmp_path / "processed", tmp_path / "raw")
    calls: list[tuple[str, tuple[str, ...]]] = []

    class Batch400HandlerSuccessClient:
        endpoint_call_counts: dict[str, int] = {}

        def fetch_batch_user_profile(self, sec_user_ids: list[str]) -> Any:
            calls.append(("batch", tuple(sec_user_ids)))
            self.endpoint_call_counts["fetch_batch_user_profile_v2"] = self.endpoint_call_counts.get("fetch_batch_user_profile_v2", 0) + 1
            raise RuntimeError('HTTP 400: {"detail":{"code":400,"request_id":"abc-402-like","message":"Request failed"}}')

        def handler_user_profile(self, sec_user_id: str) -> Any:
            calls.append(("handler", (sec_user_id,)))
            self.endpoint_call_counts["handler_user_profile"] = self.endpoint_call_counts.get("handler_user_profile", 0) + 1
            if sec_user_id == "sec_creator":
                return {"user": {"uid": "creator", "sec_uid": "sec_creator", "follower_count": 10}}
            return {"user": {"uid": "u1", "sec_uid": "sec_u1", "follower_count": 5}}

    raw_run = tmp_path / "raw" / "profile-run"
    stats = profiles.collect_profiles(
        targets,
        raw_run,
        Batch400HandlerSuccessClient(),
        resume=True,
        max_users=None,
        api_key="",
        profile_api="batch",
        batch_handler_fallback=True,
    )  # type: ignore[arg-type]

    assert calls == [("batch", ("sec_creator", "sec_u1")), ("handler", ("sec_creator",)), ("handler", ("sec_u1",))]
    assert stats.cost_guard_triggered is True
    assert stats.cost_guard_reason == "batch_http400_downgrade_handler"
    assert stats.partial is False
    assert stats.quota_or_rate_limited is False
    assert stats.succeeded == 2
    statuses = {row["user_id"]: row for row in read_csv(raw_run / "profile_status.csv")}
    assert {row["status"] for row in statuses.values()} == {"success"}


def test_report_includes_aggregate_cost_audit_and_quota_state(tmp_path: Path) -> None:
    src = make_source(tmp_path, sec="sec_u1")
    raw_run = tmp_path / "raw" / "profile-run"
    processed_run = tmp_path / "processed" / "profile-run"
    write_csv(raw_run / "profile_status.csv", profiles.STATUS_COLUMNS, [
        {"user_id": "u1", "sec_user_id": "sec_u1", "status": "success", "endpoint": "handler_user_profile", "http_status": "", "error_category": "", "error": "", "attempted_at": "now"},
        {"user_id": "creator", "sec_user_id": "sec_creator", "status": "quota_stopped", "endpoint": "handler_user_profile", "http_status": "402", "error_category": "quota_or_balance", "error": "HTTP 402: insufficient balance", "attempted_at": "now"},
    ])
    write_jsonl(raw_run / "user_profiles.jsonl", [
        {"user_id": "u1", "sec_user_id": "sec_u1", "items": [{"uid": "u1", "sec_uid": "sec_u1", "follower_count": 5}]},
    ])
    targets, target_audit, historical = profiles.build_profile_targets(src, tmp_path / "processed", tmp_path / "raw")
    stats = profiles.CollectionStats(profile_api_requested="cost-safe", profile_api_resolved="handler")
    counts = profiles.build_processed_outputs(src, processed_run, raw_run, targets, historical, stats)
    report = profiles.build_collection_report(
        run_id="profile-run",
        source_run=src,
        processed_dir=processed_run,
        raw_dir=raw_run,
        target_rows=targets,
        target_audit=target_audit,
        processed_counts=counts,
        stats=stats,
        settings=profiles.TikHubSettings(live_fetch=True, api_key="test-key"),
    )

    assert report["quota_stopped_profiles"] == 1
    assert report["http_status_counts"] == {"402": 1}
    assert report["rejected_by_endpoint_status"] == {"handler_user_profile:402": 1}
    assert report["profile_api_requested"] == "cost-safe"
    assert report["profile_api_resolved"] == "handler"
    assert report["recommended_resume_mode"] == "handler"
    assert "--profile-api handler" in report["next_resume_command"]
    assert {row["user_id"]: row for row in read_csv(processed_run / "profile_target_users.csv")}["creator"]["profile_fetch_status"] == "quota_stopped"


def test_profile_index_normalization_helpers() -> None:
    assert profiles.log_p95_score(0, 10) == 0.0
    assert profiles.log_p95_score(10, 10) == pytest.approx(1.0)
    assert profiles.log_p95_score(20, 10) == pytest.approx(1.0)
    assert profiles.percentile([0, 10, 20, 30, 40], 0.90) == pytest.approx(36.0)
    assert profiles.percentile([0, 10, 20, 30, 40], 0.95) == pytest.approx(38.0)
    assert profiles.percentile([0, 10, 20, 30, 40], 0.99) == pytest.approx(39.6)
    assert profiles.rank_percentile_scores([0, 10, 20]) == pytest.approx([0.0, 0.5, 1.0])


def test_profile_index_uses_reference_weighted_v2_formula() -> None:
    signals = [
        {"video_count": 0, "comment_count": 0, "reply_count": 0, "follower_count": 0, "comment_like_sum": 0, "edge_degree": 0},
        {"video_count": 100, "comment_count": 20, "reply_count": 10, "follower_count": 1000, "comment_like_sum": 50, "edge_degree": 5},
        {"video_count": 200, "comment_count": 40, "reply_count": 20, "follower_count": 10000, "comment_like_sum": 100, "edge_degree": 10},
    ]
    thresholds = profiles.compute_profile_index_thresholds(signals)
    assert thresholds["video_count"] > 100
    assert thresholds["comment_count"] > 20
    assert thresholds["reply_count"] > 10
    score = profiles.compute_profile_index_scores(signals[1], thresholds)
    assert 0.0 < score["activity_video_score"] < 1.0
    assert 0.0 < score["activity_comment_score"] < 1.0
    assert 0.0 < score["activity_reply_score"] < 1.0
    assert score["activity_publish_score"] == score["activity_video_score"]
    assert score["activity_score"] == pytest.approx(
        0.25 * score["activity_video_score"] + 0.45 * score["activity_comment_score"] + 0.30 * score["activity_reply_score"]
    )
    assert score["global_influence_score"] == score["influence_coverage_score"]
    assert score["local_influence_score"] == pytest.approx(
        0.60 * score["local_network_score"] + 0.40 * score["local_recognition_score"]
    )
    assert score["observed_activity_level"] == pytest.approx(score["activity_score"])
    assert score["observed_influence"] == pytest.approx(
        0.5 * score["global_influence_score"] + 0.5 * score["local_influence_score"]
    )


def test_profile_index_global_influence_uses_only_follower_count() -> None:
    thresholds = {
        "video_count": 100,
        "comment_count": 100,
        "reply_count": 100,
        "follower_count": 1000,
        "comment_like_sum": 100,
        "edge_degree": 100,
    }
    low_activity = {
        "video_count": 0,
        "comment_count": 0,
        "reply_count": 0,
        "follower_count": 100,
        "comment_like_sum": 0,
        "edge_degree": 0,
    }
    high_activity = dict(low_activity, video_count=999, comment_count=999, reply_count=999, comment_like_sum=999, edge_degree=999)
    assert profiles.compute_profile_index_scores(low_activity, thresholds)["global_influence_score"] == pytest.approx(
        profiles.compute_profile_index_scores(high_activity, thresholds)["global_influence_score"]
    )


def test_profile_index_robustness_report_is_aggregate_only() -> None:
    signals = [
        {"video_count": idx, "comment_count": idx % 5, "reply_count": idx % 3, "follower_count": idx * 10, "edge_degree": idx % 7, "comment_like_sum": idx % 11}
        for idx in range(1, 31)
    ]
    report = profiles.profile_index_robustness_report(signals)
    assert report["user_count"] == 30
    assert "activity_score" in report["metrics"]
    comparison = report["metrics"]["activity_score"]["comparisons"]["activity_weights:activity_base"]
    assert comparison["spearman"] == pytest.approx(1.0)
    assert comparison["top10_overlap"] == pytest.approx(1.0)
    text = json.dumps(report, ensure_ascii=False)
    for forbidden in ["Authorization", "Cookie", "Bearer", "nickname", "bio", "signature"]:
        assert forbidden not in text


def test_build_abm_row_records_reference_based_profile_index() -> None:
    target = {
        "user_id": "u1",
        "comment_count": "10",
        "reply_count": "5",
        "edge_degree": "3",
        "comment_like_sum": "20",
        "user_role": "observed",
    }
    user = {"user_id": "u1", "follower_count": "100", "following_count": "5", "video_count": "12"}
    thresholds = {
        "video_count": 24,
        "comment_count": 20,
        "reply_count": 10,
        "follower_count": 1000,
        "comment_like_sum": 100,
        "edge_degree": 10,
    }
    row = profiles.build_abm_row(target, user, "live_current", "success", profile_index_thresholds=thresholds)
    assert row["activity_level"] == row["observed_activity_level"]
    assert row["activity_level"] == row["activity_score"]
    assert row["observed_influence"] == pytest.approx(0.5 * row["global_influence_score"] + 0.5 * row["local_influence_score"])
    assert row["profile_index_method"] == "log1p_p95_reference_weighted_v2"
    assert row["profile_index_variant"] == "base"
    for field in [
        "activity_score",
        "activity_video_score",
        "activity_publish_score",
        "activity_comment_score",
        "activity_reply_score",
        "global_influence_score",
        "local_influence_score",
        "local_network_score",
        "local_recognition_score",
        "influence_coverage_score",
        "influence_recognition_score",
        "influence_network_score",
    ]:
        assert 0.0 <= row[field] <= 1.0
    provenance = row["attribute_provenance"]
    assert provenance["profile_index_method"] == profiles.PROFILE_INDEX_METHOD
    assert provenance["profile_index_thresholds"] == thresholds
    assert "Qingbo DCI" in provenance["profile_index_reference_basis"][0]
