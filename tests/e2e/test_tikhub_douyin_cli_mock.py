from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path


def test_tikhub_douyin_cli_mock_outputs_processed_six_pack(tmp_path: Path) -> None:
    fixture = Path("tests/fixtures/tikhub_douyin/small_batch.json")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "llm_abm_sim.data_sources.cli",
            "collect-douyin",
            "--hashtag",
            "锦江酒店",
            "--start-date",
            "2025-06-01",
            "--end-date",
            "2026-06-01",
            "--max-videos",
            "2",
            "--mock-fixture",
            str(fixture),
            "--output-root",
            str(tmp_path),
            "--run-id",
            "cli-run",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    assert "Bearer" not in result.stdout
    assert "TIKHUB_API_KEY" not in result.stdout
    payload = json.loads(result.stdout)
    processed = Path(payload["processed_dir"])
    assert processed == tmp_path / "data" / "processed" / "jinjiang_douyin" / "cli-run"
    for name in ["videos.csv", "comments.csv", "text_items.csv", "users.csv", "edges.csv", "profiles.csv", "collection_report.json"]:
        assert (processed / name).exists()
    report = json.loads((processed / "collection_report.json").read_text(encoding="utf-8"))
    assert report["mode"] == "mock"


def test_tikhub_cli_refuses_live_without_gate(tmp_path: Path) -> None:
    env = {key: value for key, value in os.environ.items() if not key.startswith("TIKHUB_")}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "llm_abm_sim.data_sources.cli",
            "collect-douyin",
            "--output-root",
            str(tmp_path),
        ],
        text=True,
        capture_output=True,
        env=env,
    )
    assert result.returncode == 2
    assert "TIKHUB_LIVE_FETCH" in result.stderr


def test_tikhub_douyin_cli_mock_accepts_unbounded_selection_manifest(tmp_path: Path) -> None:
    fixture = Path("tests/fixtures/tikhub_douyin/small_batch.json")
    manifest = tmp_path / "selection.json"
    manifest.write_text(
        json.dumps([{"rank": 1, "tag": "锦江酒店", "challenge_id": "cha_jj", "source": "test"}], ensure_ascii=False),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "llm_abm_sim.data_sources.cli",
            "collect-douyin",
            "--mock-fixture",
            str(fixture),
            "--selection-manifest",
            str(manifest),
            "--limit-profile",
            "unbounded",
            "--collection-scope",
            "top10_challenge_batch",
            "--output-root",
            str(tmp_path),
            "--run-id",
            "cli-unbounded",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    assert "Bearer" not in result.stdout
    report = json.loads((tmp_path / "data" / "processed" / "jinjiang_douyin" / "cli-unbounded" / "collection_report.json").read_text(encoding="utf-8"))
    assert report["limit_profile"] == "unbounded"
    assert report["selection_metadata"]["challenge_selections"][0]["name"] == "锦江酒店"


def test_tikhub_cli_metadata_only_stages_skip_interaction_outputs(tmp_path: Path) -> None:
    fixture = Path("tests/fixtures/tikhub_douyin/small_batch.json")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "llm_abm_sim.data_sources.cli",
            "collect-douyin",
            "--mock-fixture",
            str(fixture),
            "--stages",
            "challenge_index,video_metadata",
            "--output-root",
            str(tmp_path),
            "--run-id",
            "cli-metadata-only",
            "--max-videos",
            "2",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    assert "Bearer" not in result.stdout
    processed = tmp_path / "data" / "processed" / "jinjiang_douyin" / "cli-metadata-only"
    report = json.loads((processed / "collection_report.json").read_text(encoding="utf-8"))
    assert report["comments_collected"] is False
    assert report["profiles_collected"] is False
    assert report["stage_counts"]["selected_video_ids"] == 2
    assert report["counts"]["comments"] == 0
    assert report["counts"]["profiles"] == 0


def test_tikhub_cli_video_metadata_alias(tmp_path: Path) -> None:
    fixture = Path("tests/fixtures/tikhub_douyin/small_batch.json")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "llm_abm_sim.data_sources.cli",
            "collect-douyin-video-metadata",
            "--mock-fixture",
            str(fixture),
            "--output-root",
            str(tmp_path),
            "--run-id",
            "cli-metadata-alias",
            "--max-videos",
            "1",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    report = json.loads(
        (tmp_path / "data" / "processed" / "jinjiang_douyin" / "cli-metadata-alias" / "collection_report.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["selection_metadata"]["enabled_stages"] == ["challenge_index", "video_metadata"]
    assert report["comments_collected"] is False


def test_tikhub_cli_jinjiang_top10_metadata_scope_requires_manifest(tmp_path: Path) -> None:
    fixture = Path("tests/fixtures/tikhub_douyin/small_batch.json")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "llm_abm_sim.data_sources.cli",
            "collect-douyin-video-metadata",
            "--mock-fixture",
            str(fixture),
            "--collection-scope",
            "jinjiang_top10_jinjiang_only_video_metadata_unbounded",
            "--output-root",
            str(tmp_path),
            "--run-id",
            "missing-manifest",
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 2
    assert "--selection-manifest" in result.stderr



def test_tikhub_cli_candidate_comments_manifest_enforces_scope_and_caps(tmp_path: Path) -> None:
    fixture = {
        "comments": {
            "7380282151763332403": [
                {"cid": "c1", "aweme_id": "7380282151763332403", "user": {"uid": "u1"}, "text": "one"},
                {"cid": "c2", "aweme_id": "7380282151763332403", "user": {"uid": "u2"}, "text": "two"},
                {"cid": "c3", "aweme_id": "7380282151763332403", "user": {"uid": "u3"}, "text": "three"},
            ],
            "7304930579651284264": [
                {"cid": "c4", "aweme_id": "7304930579651284264", "user": {"uid": "u4"}, "text": "four"},
                {"cid": "c5", "aweme_id": "7304930579651284264", "user": {"uid": "u5"}, "text": "five"},
            ],
            "7498610642853858569": [
                {"cid": "c6", "aweme_id": "7498610642853858569", "user": {"uid": "u6"}, "text": "six"}
            ],
            "7219508986515606839": [],
            "7486704870804770107": [{"cid": "excluded", "aweme_id": "7486704870804770107", "text": "must not collect"}],
        }
    }
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
    source = tmp_path / "source"
    source.mkdir()
    (source / "videos.csv").write_text(
        "video_id,source_challenge_name,source_challenge_id,caption,comment_count\n"
        "7380282151763332403,锦江酒店,1614016211862532,caption,11955\n"
        "7304930579651284264,锦江之星,1600871309340680,caption,5040\n"
        "7498610642853858569,锦江宾馆,1608015311015939,caption,2963\n"
        "7219508986515606839,锦江宾馆,1608015311015939,caption,1069\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "candidates.json"
    manifest.write_text(
        json.dumps(
            {
                "excluded_video_ids": [
                    {"video_id": "7486704870804770107", "exclusion_reason": "女性安全/偷拍主题与当前锦江酒店学术研究目标不一致"},
                    {"video_id": "7486891790218399034", "exclusion_reason": "女性安全/偷拍主题与当前锦江酒店学术研究目标不一致"},
                ],
                "comment_candidates": [
                    {"video_id": "7380282151763332403", "source_challenge_name": "锦江酒店", "source_challenge_id": "1614016211862532", "metadata_comment_count": 11955, "comment_fetch_limit": 2},
                    {"video_id": "7304930579651284264", "source_challenge_name": "锦江之星", "source_challenge_id": "1600871309340680", "metadata_comment_count": 5040, "comment_fetch_limit": 2},
                    {"video_id": "7498610642853858569", "source_challenge_name": "锦江宾馆", "source_challenge_id": "1608015311015939", "metadata_comment_count": 2963, "comment_fetch_limit": "unbounded"},
                    {"video_id": "7219508986515606839", "source_challenge_name": "锦江宾馆", "source_challenge_id": "1608015311015939", "metadata_comment_count": 1069, "comment_fetch_limit": "unbounded"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    report_path = tmp_path / "report.md"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "llm_abm_sim.data_sources.cli",
            "collect-douyin-candidate-comments",
            "--mock-fixture",
            str(fixture_path),
            "--source-processed-dir",
            str(source),
            "--comment-candidate-manifest",
            str(manifest),
            "--output-root",
            str(tmp_path),
            "--run-id",
            "candidate-comments",
            "--report-path",
            str(report_path),
            "--search-page-size",
            "20",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    assert "Bearer" not in result.stdout
    assert "Authorization" not in result.stdout
    assert "TIKHUB_API_KEY" not in result.stdout
    processed = tmp_path / "data" / "processed" / "jinjiang_douyin" / "candidate-comments"
    report = json.loads((processed / "collection_report.json").read_text(encoding="utf-8"))
    assert report["profiles_collected"] is False
    assert report["stage_status"]["replies"] == "disabled"
    assert report["stage_status"]["profiles"] == "disabled"
    assert report["limits"]["max_search_pages"] is None
    with (processed / "comment_candidate_video_summary.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    actual = {row["video_id"] for row in rows}
    assert actual == {
        "7380282151763332403",
        "7304930579651284264",
        "7498610642853858569",
        "7219508986515606839",
    }
    assert "7486704870804770107" not in actual
    caps = {row["video_id"]: row["comment_fetch_limit"] for row in rows}
    assert caps["7380282151763332403"] == "2"
    assert caps["7304930579651284264"] == "2"
    assert caps["7498610642853858569"] == "unbounded"
    comments = list(csv.DictReader((processed / "comments.csv").open(encoding="utf-8")))
    assert len([row for row in comments if row["video_id"] == "7380282151763332403"]) == 2
    assert {row["comment_level"] for row in comments} <= {"comment"}
    audit = json.loads((processed / "comment_collection_audit.json").read_text(encoding="utf-8"))
    assert audit["excluded_video_ids"] == ["7486704870804770107", "7486891790218399034"]
    assert "filtered candidate comments collection" in report_path.read_text(encoding="utf-8")



def test_tikhub_cli_candidate_comments_rejects_manifest_exclusion_overlap(tmp_path: Path) -> None:
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps({"comments": {}}, ensure_ascii=False), encoding="utf-8")
    source = tmp_path / "source"
    source.mkdir()
    (source / "videos.csv").write_text("video_id,caption\n7486704870804770107,excluded\n", encoding="utf-8")
    manifest = tmp_path / "bad-candidates.json"
    manifest.write_text(
        json.dumps(
            {
                "excluded_video_ids": [{"video_id": "7486704870804770107", "exclusion_reason": "excluded"}],
                "comment_candidates": [{"video_id": "7486704870804770107", "metadata_comment_count": 1, "comment_fetch_limit": 1}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "llm_abm_sim.data_sources.cli",
            "collect-douyin-candidate-comments",
            "--mock-fixture",
            str(fixture_path),
            "--source-processed-dir",
            str(source),
            "--comment-candidate-manifest",
            str(manifest),
            "--output-root",
            str(tmp_path),
            "--run-id",
            "bad-candidate-comments",
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 2
    assert "excluded video_id" in result.stderr


def test_tikhub_cli_caption_hashtag_comments_collects_replies_and_excludes_safety_ids(tmp_path: Path) -> None:
    fixture = {
        "comments": {
            "v1": [
                {"cid": "c1", "aweme_id": "v1", "user": {"uid": "u1"}, "text": "comment one"},
                {"cid": "c2", "aweme_id": "v1", "user": {"uid": "u2"}, "text": "comment two"},
            ],
            "v2": [{"cid": "c3", "aweme_id": "v2", "user": {"uid": "u3"}, "text": "comment three"}],
            "7486704870804770107": [
                {"cid": "excluded", "aweme_id": "7486704870804770107", "user": {"uid": "ux"}, "text": "must not collect"}
            ],
        },
        "replies": {
            "c1": [{"cid": "r1", "aweme_id": "v1", "user": {"uid": "u4"}, "text": "reply one"}],
            "c2": [],
            "c3": [{"cid": "r2", "aweme_id": "v2", "user": {"uid": "u5"}, "text": "reply two"}],
            "excluded": [{"cid": "rx", "aweme_id": "7486704870804770107", "text": "must not collect"}],
        },
    }
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
    source = tmp_path / "source"
    source.mkdir()
    (source / "videos.csv").write_text(
        "video_id,source_challenge_name,source_challenge_id,caption,hashtags,comment_count\n"
        "v1,锦江酒店,1,caption,\"[\"\"锦江酒店\"\"]\",2\n"
        "v2,锦江之星酒店,2,caption,\"[\"\"锦江之星酒店\"\", \"\"锦江酒店\"\"]\",1\n"
        "v3,其他,3,caption,\"[\"\"酒店\"\"]\",9\n"
        "7486704870804770107,锦江酒店,1,caption,\"[\"\"锦江酒店\"\"]\",99\n"
        "7486891790218399034,锦江之星酒店,2,caption,\"[\"\"锦江之星酒店\"\"]\",88\n",
        encoding="utf-8",
    )
    report_path = tmp_path / "caption-report.md"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "llm_abm_sim.data_sources.cli",
            "collect-douyin-caption-hashtag-comments",
            "--mock-fixture",
            str(fixture_path),
            "--source-processed-dir",
            str(source),
            "--output-root",
            str(tmp_path),
            "--run-id",
            "caption-comments",
            "--report-path",
            str(report_path),
            "--caption-hashtag",
            "锦江酒店",
            "--caption-hashtag",
            "锦江之星酒店",
            "--search-page-size",
            "20",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    assert "Bearer" not in result.stdout
    assert "Authorization" not in result.stdout
    assert "TIKHUB_API_KEY" not in result.stdout
    processed = tmp_path / "data" / "processed" / "jinjiang_douyin" / "caption-comments"
    manifest_rows = list(csv.DictReader((processed / "target_video_manifest.csv").open(encoding="utf-8")))
    assert {row["video_id"] for row in manifest_rows} == {"v1", "v2"}
    assert "#锦江之星酒店" in {tag for row in manifest_rows for tag in row["matched_caption_hashtags"].split(";")}
    comments = list(csv.DictReader((processed / "comments.csv").open(encoding="utf-8")))
    top_level = list(csv.DictReader((processed / "top_level_comments.csv").open(encoding="utf-8")))
    replies = list(csv.DictReader((processed / "replies.csv").open(encoding="utf-8")))
    all_comments = list(csv.DictReader((processed / "all_comments.csv").open(encoding="utf-8")))
    assert len(comments) == 5
    assert len(top_level) == 3
    assert len(replies) == 2
    assert len(all_comments) == 5
    assert {row["comment_level"] for row in top_level} == {"comment"}
    assert {row["comment_level"] for row in replies} == {"reply"}
    assert {row["comment_level"] for row in comments} == {"comment", "reply"}
    assert "7486704870804770107" not in {row["video_id"] for row in all_comments}
    assert "7486891790218399034" not in {row["video_id"] for row in all_comments}
    summary_rows = list(csv.DictReader((processed / "comment_video_summary.csv").open(encoding="utf-8")))
    assert {row["collection_status"] for row in summary_rows} == {"complete"}
    report = json.loads((processed / "collection_report.json").read_text(encoding="utf-8"))
    assert report["profiles_collected"] is False
    assert report["stage_status"]["comments"] == "enabled"
    assert report["stage_status"]["replies"] == "enabled"
    assert report["stage_status"]["profiles"] == "disabled"
    assert report["target_video_count"] == 2
    audit = json.loads((processed / "comment_collection_audit.json").read_text(encoding="utf-8"))
    assert audit["collection_type"] == "top10_caption_hashtag_all_comments"
    assert audit["target_video_count"] == 2
    assert audit["excluded_video_ids"] == ["7486704870804770107", "7486891790218399034"]
    assert audit["profiles_collected"] is False
    assert "不是 4 个高评论候选视频" in report_path.read_text(encoding="utf-8")



def test_tikhub_cli_caption_hashtag_comments_partial_reply_failure_reports_blocker(tmp_path: Path) -> None:
    fixture = {
        "comments": {"v1": [{"cid": "c1", "aweme_id": "v1", "user": {"uid": "u1"}, "text": "comment"}]},
        "replies": {},
    }
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
    source = tmp_path / "source"
    source.mkdir()
    (source / "videos.csv").write_text(
        "video_id,source_challenge_name,source_challenge_id,caption,hashtags,comment_count\n"
        "v1,锦江酒店,1,caption,\"[\"\"锦江酒店\"\"]\",1\n",
        encoding="utf-8",
    )

    # Monkeypatch by using a fixture client subclass through direct collector wiring is
    # overkill for the CLI; instead, assert the normal summary logic handles a
    # failed reply page journal generated by collector-compatible files.
    from llm_abm_sim.data_sources.cli import write_caption_hashtag_comment_outputs
    from llm_abm_sim.data_sources.douyin_collector import DouyinCommentCandidate
    from llm_abm_sim.data_sources.douyin_models import COMMENT_COLUMNS

    raw = tmp_path / "data" / "raw" / "tikhub" / "douyin" / "jinjiang_hotel" / "partial"
    processed = tmp_path / "data" / "processed" / "jinjiang_douyin" / "partial"
    raw.mkdir(parents=True)
    (raw / "pages").mkdir()
    processed.mkdir(parents=True)
    with (processed / "comments.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COMMENT_COLUMNS)
        writer.writeheader()
        writer.writerow({"comment_id": "c1", "video_id": "v1", "commenter_user_id": "u1", "comment_level": "comment"})
    (raw / "pages" / "comments_v1_cursor_0.json").write_text(
        json.dumps({"page_key": "comments:v1:cursor:0", "raw_kind": "comments", "items": [{"cid": "c1", "video_id": "v1"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (processed / "collection_report.json").write_text(
        json.dumps(
            {
                "failed_pages": [{"page": "replies:c1:cursor:0", "error": "HTTP 402: Insufficient balance"}],
                "stage_status": {"comments": "enabled", "replies": "enabled", "profiles": "disabled"},
                "profiles_collected": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    write_caption_hashtag_comment_outputs(
        processed_dir=processed,
        raw_dir=raw,
        run_id="partial",
        candidates=[DouyinCommentCandidate(video_id="v1", source_challenge_name="锦江酒店", metadata_comment_count=1, caption_hashtags="#锦江酒店")],
        target_manifest_rows=[{"video_id": "v1", "source_challenge_name": "锦江酒店", "matched_caption_hashtags": "#锦江酒店", "metadata_comment_count": 1}],
        caption_hashtags=["锦江酒店"],
        source_processed_dir=source,
    )
    summary = list(csv.DictReader((processed / "comment_video_summary.csv").open(encoding="utf-8")))
    assert summary[0]["collection_status"] == "reply_partial"
    assert summary[0]["needs_more_replies"] == "true"
    audit = json.loads((processed / "comment_collection_audit.json").read_text(encoding="utf-8"))
    assert audit["partial"] is True
