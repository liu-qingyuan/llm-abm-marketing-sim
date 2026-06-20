from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from llm_abm_sim.data_sources.cli import (
    DEFAULT_SAFETY_EXCLUDED_VIDEO_IDS,
    JINJIANG_TOP10_CAPTION_HASHTAGS,
    build_caption_hashtag_comment_targets,
    load_csv_rows,
)

SECRET_MARKERS = ("Bearer", "Authorization", "TIKHUB_API_KEY")


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def fail(message: str) -> None:
    raise AssertionError(message)


def assert_no_excluded(rows: list[dict[str, str]], path: Path, excluded: set[str]) -> None:
    found = {str(row.get("video_id") or "") for row in rows} & excluded
    if found:
        fail(f"{path} contains excluded video_id(s): {sorted(found)}")


def scan_no_secrets(paths: list[Path]) -> None:
    for path in paths:
        if not path.exists() or path.is_dir():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        leaked = [marker for marker in SECRET_MARKERS if marker in text]
        if leaked:
            fail(f"{path} contains secret marker(s): {leaked}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit top10 caption hashtag comments collection outputs")
    parser.add_argument("--source-processed-dir", required=True)
    parser.add_argument("--processed-dir", required=True)
    parser.add_argument("--report-path")
    parser.add_argument("--stdout-log")
    parser.add_argument("--excluded-video-id", action="append", default=[])
    args = parser.parse_args(argv)

    source_processed = Path(args.source_processed_dir)
    processed = Path(args.processed_dir)
    excluded = set(DEFAULT_SAFETY_EXCLUDED_VIDEO_IDS) | {str(value) for value in args.excluded_video_id}

    source_rows = load_csv_rows(source_processed / "videos.csv")
    expected_candidates, _expected_manifest_rows, expected_excluded_found = build_caption_hashtag_comment_targets(
        source_rows,
        caption_hashtags=JINJIANG_TOP10_CAPTION_HASHTAGS,
        excluded_video_ids=sorted(excluded),
    )
    expected_count = len(expected_candidates)

    manifest = read_csv(processed / "target_video_manifest.csv")
    comments = read_csv(processed / "comments.csv")
    top_level_comments = read_csv(processed / "top_level_comments.csv")
    replies = read_csv(processed / "replies.csv")
    all_comments = read_csv(processed / "all_comments.csv")
    summary = read_csv(processed / "comment_video_summary.csv")
    report_path = processed / "collection_report.json"
    audit_path = processed / "comment_collection_audit.json"
    report: dict[str, Any] = json.loads(report_path.read_text(encoding="utf-8"))
    audit: dict[str, Any] = json.loads(audit_path.read_text(encoding="utf-8"))

    if len(manifest) != expected_count:
        fail(f"target manifest count {len(manifest)} != expected {expected_count}")
    if len(summary) != expected_count:
        fail(f"summary count {len(summary)} != expected {expected_count}")
    if int(report.get("target_video_count") or -1) != expected_count:
        fail(f"collection_report target_video_count {report.get('target_video_count')} != expected {expected_count}")
    if int(audit.get("target_video_count") or -1) != expected_count:
        fail(f"audit target_video_count {audit.get('target_video_count')} != expected {expected_count}")

    for path, rows in [
        (processed / "target_video_manifest.csv", manifest),
        (processed / "comments.csv", comments),
        (processed / "top_level_comments.csv", top_level_comments),
        (processed / "replies.csv", replies),
        (processed / "all_comments.csv", all_comments),
        (processed / "comment_video_summary.csv", summary),
    ]:
        assert_no_excluded(rows, path, excluded)

    if report.get("profiles_collected") is not False:
        fail("profiles_collected is not False")
    stage_status = report.get("stage_status", {})
    if stage_status.get("profiles") != "disabled":
        fail("stage_status.profiles is not disabled")
    if stage_status.get("comments") != "enabled":
        fail("stage_status.comments is not enabled")
    if stage_status.get("replies") != "enabled":
        fail("stage_status.replies is not enabled")
    if set(audit.get("excluded_video_ids_found_in_source_scope", [])) != set(expected_excluded_found):
        fail("audit excluded_video_ids_found_in_source_scope does not match source-derived exclusions")

    scan_targets = [report_path, audit_path, processed / "target_video_manifest.csv"]
    if args.report_path:
        scan_targets.append(Path(args.report_path))
    if args.stdout_log:
        scan_targets.append(Path(args.stdout_log))
    scan_no_secrets(scan_targets)

    result = {
        "ok": True,
        "expected_target_video_count": expected_count,
        "manifest_video_count": len(manifest),
        "comments": len(top_level_comments),
        "canonical_comments_csv": len(comments),
        "replies": len(replies),
        "all_comments": len(all_comments),
        "partial": bool(audit.get("partial")),
        "excluded_video_ids": sorted(excluded),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
