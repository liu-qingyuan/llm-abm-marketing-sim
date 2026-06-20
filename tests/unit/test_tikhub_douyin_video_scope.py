from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

from llm_abm_sim.data_sources.cli import load_selection_manifest
from llm_abm_sim.data_sources.douyin_models import VIDEO_COLUMNS
from llm_abm_sim.data_sources.douyin_video_scope import analyze_processed_run, load_scope_tags, markdown_table

MANIFEST = Path("configs/jinjiang_top10_jinjiang_only_video_metadata_selection.json")


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=VIDEO_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in VIDEO_COLUMNS})


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def make_processed_run(tmp_path: Path) -> Path:
    processed = tmp_path / "processed"
    write_csv(
        processed / "videos.csv",
        [
            {
                "video_id": "v1",
                "source_challenge_id": "1629766950492163",
                "source_challenge_name": "锦江都城酒店",
                "source_challenge_rank": 1,
                "raw_detail_status": "promoted_from_challenge",
                "metadata_source": "challenge_page",
                "caption": "#锦江酒店 #锦江之星 普通文本锦江都城酒店 #酒店",
                "hashtags": json.dumps(["锦江酒店", "锦江之星", "酒店"], ensure_ascii=False),
                "comment_count": 1001,
            },
            {
                "video_id": "v2",
                "source_challenge_id": "1624819436442636",
                "source_challenge_name": "锦江之星酒店",
                "source_challenge_rank": 2,
                "raw_detail_status": "detail",
                "metadata_source": "app_v3_detail",
                "caption": "锦江酒店 普通文本但没有hashtag",
                "hashtags": json.dumps([], ensure_ascii=False),
                "comment_count": 8,
            },
            {
                "video_id": "v3",
                "source_challenge_id": "1614016211862532",
                "source_challenge_name": "锦江酒店",
                "source_challenge_rank": 3,
                "raw_detail_status": "detail",
                "metadata_source": "app_v3_detail",
                "caption": "#锦江酒店中国区",
                "hashtags": json.dumps(["锦江酒店中国区"], ensure_ascii=False),
                "comment_count": 12000,
            },
            {
                "video_id": "v3",
                "source_challenge_id": "1629766950492163",
                "source_challenge_name": "锦江都城酒店",
                "source_challenge_rank": 1,
                "raw_detail_status": "promoted_from_challenge",
                "metadata_source": "challenge_page",
                "caption": "duplicate row without scoped hashtag",
                "hashtags": json.dumps([], ensure_ascii=False),
                "comment_count": 2,
            },
        ],
    )
    report = {
        "run_id": "unit-run",
        "stage_status": {
            "challenge_index": "enabled",
            "video_metadata": "enabled",
            "comments": "disabled",
            "replies": "disabled",
            "profiles": "disabled",
        },
        "stage_counts": {"indexed_video_ids": 3, "selected_video_ids": 3},
        "comments_collected": False,
        "profiles_collected": False,
        "endpoint_call_counts": {"fetch_hashtag_video_list": 1},
    }
    (processed / "collection_report.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    return processed


def test_jinjiang_only_manifest_locks_scope_and_exclusions() -> None:
    tags = load_scope_tags(MANIFEST)
    assert tags == [
        "锦江都城酒店",
        "锦江之星酒店",
        "锦江酒店",
        "锦江之星",
        "锦江宾馆",
        "绵阳锦江国际酒店",
        "锦江之星品尚",
        "锦江酒店华西区",
        "锦江之星海口",
        "锦江酒店中国区",
    ]
    assert all("锦江" in tag for tag in tags)
    assert {"酒店", "住宿", "高性价比酒店推荐"}.isdisjoint(tags)
    selections = load_selection_manifest(MANIFEST)
    assert [selection.name for selection in selections] == tags
    assert all(selection.include for selection in selections)


def test_video_scope_analysis_hashtag_only_multilabel_and_metadata_comment_policy(tmp_path: Path) -> None:
    processed = make_processed_run(tmp_path)
    out = tmp_path / "out"
    paths = analyze_processed_run(processed, output_dir=out, manifest_path=MANIFEST, run_label="unit-run")

    caption_rows = read_csv(paths.caption_matches)
    by_tag = {row["caption_hashtag"]: row for row in caption_rows}
    assert by_tag["#锦江酒店"]["matched_video_count"] == "1"
    assert by_tag["#锦江之星"]["matched_video_count"] == "1"
    assert by_tag["#锦江酒店中国区"]["over_10000_video_count"] == "1"
    assert by_tag["#锦江酒店中国区"]["max_metadata_comment_count"] == "12000"
    assert by_tag["#锦江酒店中国区"]["sum_metadata_comment_count"] == "12000"
    assert by_tag["#锦江都城酒店"]["matched_video_count"] == "0"  # plain text is intentionally ignored.
    assert "#酒店" not in by_tag

    multilabel = read_csv(paths.multilabel_detail)
    assert [row["caption_hashtag"] for row in multilabel if row["video_id"] == "v1"] == ["#锦江酒店", "#锦江之星"]
    assert [row["over_10000_by_metadata"] for row in multilabel if row["video_id"] == "v3"] == ["true"]
    universe = {row["video_id"]: row for row in read_csv(paths.video_universe)}
    assert universe["v1"]["caption_hashtag_count"] == "2"
    assert universe["v1"]["over_1000_by_metadata"] == "true"
    assert universe["v1"]["over_10000_by_metadata"] == "false"
    assert universe["v1"]["needs_comment_fetch"] == "true"
    assert universe["v2"]["caption_hashtag_count"] == "0"
    assert universe["v2"]["comment_count_confidence"] == "detail_metadata"
    assert universe["v3"]["over_10000_by_metadata"] == "true"

    candidates = read_csv(paths.comment_count_candidates)
    assert [row["video_id"] for row in candidates] == ["v3", "v1"]
    assert candidates[0]["metadata_comment_count"] == "12000"

    audit = json.loads(paths.metadata_audit.read_text(encoding="utf-8"))
    assert audit["analysis_schema_version"] == "top10_jinjiang_video_scope.v1"
    assert audit["scope_manifest"]["path"] == str(MANIFEST)
    assert len(audit["scope_manifest"]["sha256"]) == 64
    assert audit["authoritative_outputs"]["comment_count_candidates"] == "top10_jinjiang_comment_count_candidates.csv"
    assert audit["counts"]["deduped_video_total"] == 3
    assert audit["counts"]["source_challenge_rows"] == 10
    assert len(universe) == 3  # video_universe is explicitly deduped even if videos.csv repeats a video_id.
    assert audit["counts"]["multilabel_match_total"] == 3
    assert audit["counts"]["over_1000_candidate_videos"] == 2
    assert audit["counts"]["over_10000_candidate_videos"] == 1
    assert audit["comments_collected"] is False
    assert audit["profiles_collected"] is False
    assert audit["forbidden_endpoint_calls"] == {}
    report_text = paths.markdown_report.read_text(encoding="utf-8")
    assert "metadata 层面过千" in paths.markdown_report.read_text(encoding="utf-8")
    assert "不是评论正文抓取" in report_text
    assert "selection_manifest_sha256" in report_text
    assert "authoritative outputs" in report_text


def test_analyze_douyin_video_scope_cli_writes_summary_without_secrets(tmp_path: Path) -> None:
    processed = make_processed_run(tmp_path)
    out = tmp_path / "cli-out"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "llm_abm_sim.data_sources.cli",
            "analyze-douyin-video-scope",
            "--processed-dir",
            str(processed),
            "--output-dir",
            str(out),
            "--selection-manifest",
            str(MANIFEST),
            "--run-label",
            "unit-run",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Bearer" not in result.stdout
    assert "TIKHUB_API_KEY" not in result.stdout
    payload = json.loads(result.stdout)
    assert Path(payload["source_summary"]).exists()
    assert Path(payload["caption_matches"]).exists()
    assert Path(payload["comment_count_candidates"]).exists()
    assert Path(payload["metadata_audit"]).exists()


def test_analyze_requires_manifest_to_avoid_scope_drift(tmp_path: Path) -> None:
    processed = make_processed_run(tmp_path)
    try:
        analyze_processed_run(processed, output_dir=tmp_path / "out")
    except ValueError as exc:
        assert "--selection-manifest" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("analysis without manifest should fail")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "llm_abm_sim.data_sources.cli",
            "analyze-douyin-video-scope",
            "--processed-dir",
            str(processed),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "--selection-manifest" in result.stderr


def test_markdown_table_escapes_multiline_and_pipe_cells() -> None:
    table = markdown_table(["caption"], [{"caption": "line1\nline2 | <tag> & text"}])
    assert "line1<br>line2 \\| &lt;tag&gt; &amp; text" in table
    assert "\nline2 | pipe" not in table


def test_scope_manifest_rejects_generic_or_non_top10_tags(tmp_path: Path) -> None:
    bad_manifest = tmp_path / "bad.json"
    bad_manifest.write_text(
        json.dumps(
            {"challenge_selections": [{"tag": "酒店", "challenge_id": "1", "include": True}]}, ensure_ascii=False
        ),
        encoding="utf-8",
    )
    try:
        load_scope_tags(bad_manifest)
    except ValueError as exc:
        assert "exactly 10" in str(exc) or "excluded generic" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("generic manifest should fail")
