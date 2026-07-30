from __future__ import annotations

import csv
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_script(name: str, filename: str) -> ModuleType:
    path = REPO_ROOT / "scripts" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


profiles = load_script("jinjiang_report_profiles", "collect_jinjiang_user_profiles.py")
scope = load_script("jinjiang_report_scope", "derive_jinjiang_scope_change.py")
topic = cast(Any, load_script("jinjiang_report_topic", "summarize_jinjiang_topic_distribution.py"))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def make_profile_source(tmp_path: Path) -> Path:
    source = tmp_path / "profile-source"
    write_csv(
        source / "users.csv",
        ["user_id", "sec_user_id", "nickname", "follower_count", "following_count", "video_count", "verified_type", "bio"],
        [{"user_id": "u1", "sec_user_id": "u1"}, {"user_id": "creator", "sec_user_id": "creator"}],
    )
    write_csv(
        source / "videos.csv",
        ["video_id", "caption", "hashtags", "creator_user_id", "source_challenge_name"],
        [{"video_id": "v1", "caption": "#锦江都城酒店吉安", "hashtags": "[\"锦江都城酒店吉安\"]", "creator_user_id": "creator", "source_challenge_name": "锦江都城酒店吉安"}],
    )
    write_csv(
        source / "target_video_manifest.csv",
        ["video_id", "matched_caption_hashtags"],
        [{"video_id": "v1", "matched_caption_hashtags": "#锦江都城酒店吉安"}],
    )
    write_csv(
        source / "comments.csv",
        ["comment_id", "video_id", "parent_comment_id", "commenter_user_id", "mentioned_user_ids", "like_count", "comment_level", "content"],
        [{"comment_id": "c1", "video_id": "v1", "commenter_user_id": "u1", "mentioned_user_ids": "[]", "like_count": "1", "comment_level": "comment", "content": "喜欢"}],
    )
    write_csv(source / "edges.csv", ["source", "target", "weight"], [{"source": "u1", "target": "creator", "weight": "1"}])
    write_csv(source / "text_items.csv", ["user_id", "text"], [{"user_id": "u1", "text": "锦江"}])
    write_csv(source / "profiles.csv", profiles.PROFILE_COLUMNS, [])
    (source / "collection_report.json").write_text(json.dumps({"profiles_collected": False}), encoding="utf-8")
    return source


def profile_args(source: Path, tmp_path: Path) -> list[str]:
    return [
        "--source-run",
        str(source),
        "--processed-root",
        str(tmp_path / "processed"),
        "--raw-root",
        str(tmp_path / "raw"),
        "--output-run-id",
        "profile-run",
        "--resume",
    ]


def test_profile_default_keeps_curated_report_out_of_run(tmp_path: Path) -> None:
    code = profiles.main(profile_args(make_profile_source(tmp_path), tmp_path))

    assert code == 0
    run = tmp_path / "processed" / "profile-run"
    assert (run / "profile_collection_report.json").exists()
    report = json.loads((run / "profile_collection_report.json").read_text(encoding="utf-8"))
    assert report["curated_report_path"] is None
    assert report["curated_report_written"] is False
    assert not (tmp_path / "curated").exists()


def test_profile_explicit_destination_writes_aggregate_report(tmp_path: Path) -> None:
    destination = tmp_path / "curated" / "profile.md"
    args = profile_args(make_profile_source(tmp_path), tmp_path)
    args.extend(["--curated-report", str(destination)])

    code = profiles.main(args)

    assert code == 0
    assert destination.exists()
    text = destination.read_text(encoding="utf-8")
    assert "curated report destination" in text
    assert "python scripts/collect_jinjiang_user_profiles.py" in text
    assert "--resume" in text
    assert str(destination) in text
    assert "OLDBIO" not in text
    report = json.loads((tmp_path / "processed" / "profile-run" / "profile_collection_report.json").read_text(encoding="utf-8"))
    assert report["curated_report_path"] == str(destination)
    assert report["curated_report_written"] is True


class FixedDateTime:
    @classmethod
    def now(cls, tz: Any = None) -> datetime:
        return datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_scope_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    processed_root = tmp_path / "processed"
    old_run = processed_root / "old-run"
    source_run = processed_root / "source-run"
    manifest_fields = [
        "video_id",
        "source_challenge_name",
        "source_challenge_id",
        "caption",
        "hashtags",
        "matched_caption_hashtags",
        "metadata_comment_count",
        "excluded",
        "exclusion_reason",
    ]
    write_csv(
        old_run / "target_video_manifest.csv",
        manifest_fields,
        [{"video_id": "v1", "source_challenge_name": "锦江酒店", "matched_caption_hashtags": "#锦江酒店", "excluded": "false"}],
    )
    summary_fields = ["video_id", "source_challenge_name", "matched_caption_hashtags"]
    write_csv(old_run / "comment_video_summary.csv", summary_fields, [{"video_id": "v1", "source_challenge_name": "锦江酒店"}])
    comment_fields = [
        "comment_id",
        "video_id",
        "parent_comment_id",
        "commenter_user_id",
        "mentioned_user_ids",
        "like_count",
        "comment_level",
        "content",
        "publish_time",
    ]
    for filename in ("top_level_comments.csv", "replies.csv", "all_comments.csv", "comments.csv"):
        write_csv(old_run / filename, comment_fields, [{"comment_id": "dummy", "video_id": "unselected"}])
    (old_run / "comment_collection_audit.json").write_text(json.dumps({"target_video_count": 1}), encoding="utf-8")
    (old_run / "collection_report.json").write_text(
        json.dumps({"counts": {}, "stage_counts": {}, "stage_status": {}}, ensure_ascii=False),
        encoding="utf-8",
    )
    write_csv(
        source_run / "videos.csv",
        [
            "video_id",
            "source_challenge_id",
            "source_challenge_name",
            "source_challenge_rank",
            "raw_detail_status",
            "metadata_source",
            "video_url",
            "publish_time",
            "caption",
            "hashtags",
            "creator_user_id",
            "like_count",
            "comment_count",
            "share_count",
            "collect_count",
        ],
        [
            {
                "video_id": "v2",
                "source_challenge_name": "锦江都城酒店吉安",
                "caption": "#锦江都城酒店吉安",
                "hashtags": "[\"锦江都城酒店吉安\"]",
                "creator_user_id": "creator",
            }
        ],
    )
    return processed_root, old_run, source_run


def configure_scope(monkeypatch: pytest.MonkeyPatch, processed_root: Path, old_run: Path, source_run: Path) -> None:
    monkeypatch.setattr(scope, "PROCESSED_ROOT", processed_root)
    monkeypatch.setattr(scope, "OLD_RUN", old_run)
    monkeypatch.setattr(scope, "SOURCE_RUN", source_run)
    monkeypatch.setattr(scope, "datetime", FixedDateTime)


def test_scope_default_report_is_run_local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    processed_root, old_run, source_run = make_scope_inputs(tmp_path)
    configure_scope(monkeypatch, processed_root, old_run, source_run)

    scope.main([])
    result = json.loads(capsys.readouterr().out)
    out_dir = Path(result["out_dir"])

    assert Path(result["report_path"]) == out_dir / "scope_change_audit.md"
    assert (out_dir / "scope_change_audit.md").exists()
    assert "docs/04-开发验证" not in (out_dir / "scope_change_audit.md").read_text(encoding="utf-8")


def test_scope_explicit_report_moves_only_markdown_destination(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    processed_root, old_run, source_run = make_scope_inputs(tmp_path)
    configure_scope(monkeypatch, processed_root, old_run, source_run)
    destination = tmp_path / "curated" / "scope.md"

    scope.main(["--report-destination", str(destination)])
    result = json.loads(capsys.readouterr().out)
    out_dir = Path(result["out_dir"])

    assert Path(result["report_path"]) == destination
    assert destination.exists()
    assert not (out_dir / "scope_change_audit.md").exists()
    assert (out_dir / "scope_change_audit.json").exists()
    assert str(destination) in destination.read_text(encoding="utf-8")


def make_topic_inputs(tmp_path: Path) -> None:
    raw_run = tmp_path / "raw-run"
    pages_dir = raw_run / "pages"
    pages_dir.mkdir(parents=True)
    (raw_run / "related_challenges.json").write_text(
        json.dumps([{"cid": topic.EXACT_CID, "cha_name": topic.EXACT_NAME}], ensure_ascii=False),
        encoding="utf-8",
    )
    (pages_dir / f"hashtag_video_list_{topic.EXACT_CID}_cursor_0.json").write_text(
        json.dumps(
            {"items": [{"aweme_id": "v1", "create_time": 1750000000, "caption": "#锦江酒店", "cha_list": [{"cha_name": "锦江酒店"}]}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    processed = tmp_path / "processed"
    for run_id in (topic.RUN_ID_RELATED, topic.RUN_ID_CAPPED, topic.RUN_ID_EXACT_ONLY):
        report = {"counts": {"videos": 1, "comments": 0, "replies": 0}, "dedupe_counts": {"deduped_videos": 1}}
        path = processed / run_id / "collection_report.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report), encoding="utf-8")
    topic.PAGES_DIR = pages_dir
    topic.RELATED_CHALLENGES = raw_run / "related_challenges.json"
    topic.PROCESSED_DIR = processed
    topic.RELATED_REPORT = processed / topic.RUN_ID_RELATED / "collection_report.json"
    topic.CAPPED_REPORT = processed / topic.RUN_ID_CAPPED / "collection_report.json"
    topic.EXACT_ONLY_REPORT = processed / topic.RUN_ID_EXACT_ONLY / "collection_report.json"


def test_topic_requires_explicit_output_before_reading_inputs(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as error:
        topic.main([])

    assert error.value.code == 2
    assert list(tmp_path.iterdir()) == []


def test_topic_explicit_destination_writes_verified_aggregate_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_topic_inputs(tmp_path)
    destination = tmp_path / "curated" / "topics.md"

    def verify_fixture(agg: Any, markdown: str) -> None:
        assert agg.exact_raw_rows == 1
        assert topic.EXACT_NAME in markdown
        assert str(destination) in markdown

    monkeypatch.setattr(topic, "validate", verify_fixture)
    assert topic.main(["--output-report", str(destination)]) == 0

    assert destination.exists()
    text = destination.read_text(encoding="utf-8")
    assert str(destination) in text
    assert "docs/04-开发验证" not in text
