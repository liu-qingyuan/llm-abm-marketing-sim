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
