"""Derive a corrected Jinjiang Douyin comments scope.

This script does not call live APIs and does not read .env. It only combines
already-materialized processed runs. If authorized top12 live metadata/comments
runs exist locally, pass them with --top12-* to include them in the final
derived scope; otherwise the script emits a metadata-gap audit.
"""
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path

OLD_RUN_ID = "jinjiang-top10-caption-hashtag-all-comments-excluding-safety-20260617T140519Z"
SOURCE_RUN_ID = "jinjiang-top10-jinjiang-only-video-metadata-unbounded-20260617T095743Z"
PROCESSED_ROOT = Path("data/processed/jinjiang_douyin")
OLD_RUN = PROCESSED_ROOT / OLD_RUN_ID
SOURCE_RUN = PROCESSED_ROOT / SOURCE_RUN_ID
SAFETY_EXCLUDED_IDS = {"7486704870804770107", "7486891790218399034"}
REMOVE_TAG = "#锦江宾馆"
SKIP_TAG = "#临空锦江宾馆"
ADD_TAG = "#锦江都城酒店吉安"
OLD_INCLUDED_TAGS = [
    "#锦江都城酒店",
    "#锦江之星酒店",
    "#锦江酒店",
    "#锦江之星",
    "#锦江宾馆",
    "#绵阳锦江国际酒店",
    "#锦江之星品尚",
    "#锦江酒店华西区",
    "#锦江之星海口",
    "#锦江酒店中国区",
]
CORRECTED_INCLUDED_TAGS = [t for t in OLD_INCLUDED_TAGS if t != REMOVE_TAG] + [ADD_TAG]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_csv(path: Path, rows: Iterable[Mapping[str, object]], fieldnames: list[str]) -> None:
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def tag_tokens(value: str) -> set[str]:
    tokens: set[str] = set()
    for part in re.split(r"[;；,，\s]+", (value or "").strip()):
        part = part.strip()
        if not part:
            continue
        tokens.add(part if part.startswith("#") else f"#{part}")
    return tokens


def parse_hashtags(value: str) -> set[str]:
    value = (value or "").strip()
    tokens: set[str] = set()
    if value:
        try:
            parsed = ast.literal_eval(value)
            if isinstance(parsed, (list, tuple, set)):
                for item in parsed:
                    text = str(item).strip()
                    if text:
                        tokens.add(text if text.startswith("#") else f"#{text}")
        except (ValueError, SyntaxError):
            pass
        for match in re.finditer(r"#([^#\s,，;；]+)", value):
            text = match.group(1).strip()
            if text:
                tokens.add(f"#{text}")
    return tokens


def source_caption_tags(row: dict[str, str]) -> set[str]:
    tags = parse_hashtags(row.get("hashtags", ""))
    caption = row.get("caption", "") or ""
    for match in re.finditer(r"#([^#\s,，;；]+)", caption):
        text = match.group(1).strip()
        if text:
            tags.add(f"#{text}")
    return tags


def first_by_video(rows: Iterable[dict[str, str]]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for row in rows:
        vid = str(row.get("video_id", "")).strip()
        if vid and vid not in out:
            out[vid] = row
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Derive corrected Jinjiang Douyin caption hashtag scope")
    parser.add_argument("--top12-metadata-run-id", default="", help="Optional processed run id containing #锦江都城酒店吉安 videos.csv")
    parser.add_argument("--top12-comments-run-id", default="", help="Optional processed run id containing #锦江都城酒店吉安 comments/replies")
    parser.add_argument("--live-api-authorized", action="store_true", help="Marks provenance that upstream top12 runs were collected after user live API authorization")
    return parser


def prefixed_sha_inputs(paths: dict[str, Path]) -> dict[str, str]:
    return {key: sha256_file(path) for key, path in paths.items() if path.exists()}


def main() -> None:
    args = build_parser().parse_args()
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    new_run_id = f"jinjiang-caption-hashtag-comments-excluding-binguan-adding-jian-derived-{now}"
    out_dir = PROCESSED_ROOT / new_run_id
    out_dir.mkdir(parents=True, exist_ok=False)

    manifest = read_csv(OLD_RUN / "target_video_manifest.csv")
    source_rows = read_csv(SOURCE_RUN / "videos.csv")
    top12_metadata_run = PROCESSED_ROOT / args.top12_metadata_run_id if args.top12_metadata_run_id else None
    top12_comments_run = PROCESSED_ROOT / args.top12_comments_run_id if args.top12_comments_run_id else None
    top12_source_rows = read_csv(top12_metadata_run / "videos.csv") if top12_metadata_run and (top12_metadata_run / "videos.csv").exists() else []
    if top12_source_rows:
        source_rows = [*source_rows, *top12_source_rows]
    summary_rows = read_csv(OLD_RUN / "comment_video_summary.csv")
    top12_summary_rows = read_csv(top12_comments_run / "comment_video_summary.csv") if top12_comments_run and (top12_comments_run / "comment_video_summary.csv").exists() else []
    old_summary_by_vid = first_by_video(summary_rows)
    top12_summary_by_vid = first_by_video(top12_summary_rows)
    old_comment_covered_vids = set(old_summary_by_vid)
    top12_comment_covered_vids = set(top12_summary_by_vid)

    manifest_tags_by_vid: dict[str, set[str]] = defaultdict(set)
    for row in manifest:
        vid = row.get("video_id", "").strip()
        if vid:
            manifest_tags_by_vid[vid].update(tag_tokens(row.get("matched_caption_hashtags", "")))

    old_target_vids = set(manifest_tags_by_vid)
    remove_vids = {vid for vid, tags in manifest_tags_by_vid.items() if REMOVE_TAG in tags}
    skip_vids = {vid for vid, tags in manifest_tags_by_vid.items() if SKIP_TAG in tags}
    base_keep_vids = old_target_vids - remove_vids - skip_vids - SAFETY_EXCLUDED_IDS

    source_by_vid = first_by_video(source_rows)
    add_vids_all: set[str] = set()
    add_remove_conflicts: set[str] = set()
    add_skip_conflicts: set[str] = set()
    add_rows_by_vid: dict[str, dict[str, str]] = {}
    for row in source_rows:
        vid = row.get("video_id", "").strip()
        if not vid:
            continue
        tags = source_caption_tags(row)
        if ADD_TAG in tags:
            add_vids_all.add(vid)
            add_rows_by_vid.setdefault(vid, row)
            if REMOVE_TAG in tags:
                add_remove_conflicts.add(vid)
            if SKIP_TAG in tags:
                add_skip_conflicts.add(vid)

    add_vids = add_vids_all - add_remove_conflicts - add_skip_conflicts - SAFETY_EXCLUDED_IDS
    add_covered_by_old_run = add_vids & old_comment_covered_vids
    add_covered_by_top12_run = add_vids & top12_comment_covered_vids
    add_already_covered = add_covered_by_old_run | add_covered_by_top12_run
    add_new_vids = add_vids - old_target_vids
    corrected_vids = base_keep_vids | add_vids
    covered_vids = (base_keep_vids & old_comment_covered_vids) | (add_vids & (old_comment_covered_vids | top12_comment_covered_vids))
    needs_fetch_vids = corrected_vids - covered_vids
    source_metadata_gap = len(add_vids_all) == 0
    partial = bool(needs_fetch_vids) or source_metadata_gap

    def keep_comment_rows(filename: str) -> list[dict[str, str]]:
        return [row for row in read_csv(OLD_RUN / filename) if row.get("video_id", "").strip() in covered_vids]

    top_rows = keep_comment_rows("top_level_comments.csv")
    reply_rows = keep_comment_rows("replies.csv")
    all_rows = keep_comment_rows("all_comments.csv")
    comments_rows = keep_comment_rows("comments.csv")

    def top12_comment_rows(filename: str) -> list[dict[str, str]]:
        if not top12_comments_run or not (top12_comments_run / filename).exists():
            return []
        return [row for row in read_csv(top12_comments_run / filename) if row.get("video_id", "").strip() in add_vids]

    top_rows.extend(top12_comment_rows("top_level_comments.csv"))
    reply_rows.extend(top12_comment_rows("replies.csv"))
    all_rows.extend(top12_comment_rows("all_comments.csv"))
    comments_rows.extend(top12_comment_rows("comments.csv"))

    manifest_fields = list(manifest[0].keys()) + ["needs_comment_fetch", "scope_change_action"]
    new_manifest_rows: list[dict[str, object]] = []
    for row in manifest:
        vid = row.get("video_id", "").strip()
        tags = tag_tokens(row.get("matched_caption_hashtags", ""))
        if vid in corrected_vids and vid in old_target_vids and REMOVE_TAG not in tags and SKIP_TAG not in tags:
            new_manifest_rows.append({**row, "needs_comment_fetch": "false", "scope_change_action": "kept_from_previous_run"})
    for vid in sorted(add_new_vids):
        src = add_rows_by_vid[vid]
        new_manifest_rows.append({
            "video_id": vid,
            "source_challenge_name": src.get("source_challenge_name", ""),
            "source_challenge_id": src.get("source_challenge_id", ""),
            "caption": src.get("caption", ""),
            "hashtags": src.get("hashtags", ""),
            "matched_caption_hashtags": ADD_TAG,
            "metadata_comment_count": src.get("comment_count", ""),
            "excluded": "false",
            "exclusion_reason": "",
            "needs_comment_fetch": "false" if vid in top12_comment_covered_vids or vid in old_comment_covered_vids else "true",
            "scope_change_action": "added_top12_with_authorized_live_comments" if vid in top12_comment_covered_vids else "added_top12_from_source_metadata",
        })
    write_csv(out_dir / "target_video_manifest.csv", new_manifest_rows, manifest_fields)

    summary_fields = list(summary_rows[0].keys()) + ["needs_comment_fetch", "scope_change_action"]
    new_summary_rows: list[dict[str, object]] = []
    for vid in sorted(corrected_vids):
        if vid in old_summary_by_vid:
            summary_row: dict[str, object] = dict(old_summary_by_vid[vid])
            summary_row["needs_comment_fetch"] = "false"
            summary_row["scope_change_action"] = "top12_already_covered" if vid in add_vids else "kept_from_previous_run"
        elif vid in top12_summary_by_vid:
            summary_row = dict(top12_summary_by_vid[vid])
            summary_row["needs_comment_fetch"] = "false"
            summary_row["scope_change_action"] = "added_top12_with_authorized_live_comments"
        else:
            src = source_by_vid.get(vid, add_rows_by_vid.get(vid, {}))
            summary_row = {k: "" for k in summary_rows[0].keys()}
            summary_row.update({
                "video_id": vid,
                "source_challenge_name": src.get("source_challenge_name", ""),
                "matched_caption_hashtags": ADD_TAG,
                "metadata_comment_count": src.get("comment_count", ""),
                "top_level_comments_collected": "0",
                "replies_collected": "0",
                "all_comments_collected": "0",
                "collection_status": "needs_comment_fetch",
                "needs_more_comments": "true",
                "needs_more_replies": "true",
                "needs_comment_fetch": "true",
                "scope_change_action": "added_top12_needs_comment_fetch",
            })
        new_summary_rows.append(summary_row)
    write_csv(out_dir / "comment_video_summary.csv", new_summary_rows, summary_fields)

    gap_fields = ["video_id", "source_challenge_name", "matched_caption_hashtags", "metadata_comment_count", "needs_comment_fetch", "reason"]
    gap_rows = []
    for vid in sorted(needs_fetch_vids):
        src = source_by_vid.get(vid, add_rows_by_vid.get(vid, {}))
        gap_rows.append({
            "video_id": vid,
            "source_challenge_name": src.get("source_challenge_name", ""),
            "matched_caption_hashtags": ADD_TAG if vid in add_vids else ";".join(sorted(manifest_tags_by_vid.get(vid, []))),
            "metadata_comment_count": src.get("comment_count", ""),
            "needs_comment_fetch": "true",
            "reason": "top12_added_from_local_metadata_without_existing_comment_coverage",
        })
    write_csv(out_dir / "needs_comment_fetch_manifest.csv", gap_rows, gap_fields)
    source_gap_fields = ["caption_hashtag", "status", "required_next_step", "live_api_required"]
    source_gap_rows = []
    if source_metadata_gap:
        source_gap_rows.append({
            "caption_hashtag": ADD_TAG,
            "status": "missing_from_local_source_videos_csv",
            "required_next_step": "supplement metadata/source scope before comment/reply collection",
            "live_api_required": "true_if_user_authorizes",
        })
    write_csv(out_dir / "source_metadata_gap_manifest.csv", source_gap_rows, source_gap_fields)

    for filename, rows in [
        ("top_level_comments.csv", top_rows),
        ("replies.csv", reply_rows),
        ("all_comments.csv", all_rows),
        ("comments.csv", comments_rows),
    ]:
        fields = list(read_csv(OLD_RUN / filename)[0].keys())
        write_csv(out_dir / filename, rows, fields)

    old_audit = json.loads((OLD_RUN / "comment_collection_audit.json").read_text(encoding="utf-8"))
    old_report = json.loads((OLD_RUN / "collection_report.json").read_text(encoding="utf-8"))
    audit = {
        "run_id": new_run_id,
        "derived_from_run_id": OLD_RUN_ID,
        "source_run_id": SOURCE_RUN_ID,
        "top12_metadata_run_id": args.top12_metadata_run_id,
        "top12_comments_run_id": args.top12_comments_run_id,
        "collection_type": "derived_scope_change_remove_jinjiang_binguan_add_jian",
        "scope_change_type": "research_object_boundary_correction",
        "old_caption_hashtags": OLD_INCLUDED_TAGS,
        "corrected_caption_hashtags": CORRECTED_INCLUDED_TAGS,
        "removed_caption_hashtag": REMOVE_TAG,
        "skipped_caption_hashtag": SKIP_TAG,
        "added_caption_hashtag": ADD_TAG,
        "current_unique_target_videos": len(old_target_vids),
        "old_comment_covered_unique_videos": len(old_comment_covered_vids),
        "physical_manifest_rows": len(manifest),
        "removed_jinjiang_binguan_unique_videos": len(remove_vids),
        "skipped_linkong_jinjiang_binguan_unique_videos": len(skip_vids),
        "remaining_after_removal_unique_videos": len(base_keep_vids),
        "top12_source_unique_videos": len(add_vids_all),
        "top12_source_unique_videos_after_exclusions": len(add_vids),
        "top12_covered_by_old_run": len(add_covered_by_old_run),
        "top12_covered_by_authorized_comments_run": len(add_covered_by_top12_run),
        "top12_already_covered_total": len(add_already_covered),
        "top12_new_unique_videos": len(add_new_vids),
        "top12_needs_comment_fetch": len(add_vids & needs_fetch_vids),
        "top12_comments_covered_unique_videos": len(add_vids & top12_comment_covered_vids),
        "live_api_authorized_for_top12_backfill": bool(args.live_api_authorized),
        "corrected_unique_target_videos": len(corrected_vids),
        "covered_unique_target_videos": len(covered_vids),
        "needs_comment_fetch_unique_videos": len(needs_fetch_vids),
        "source_metadata_gap_for_top12": source_metadata_gap,
        "top12_source_metadata_gap": source_metadata_gap,
        "top12_source_metadata_gap_manifest": str(out_dir / "source_metadata_gap_manifest.csv"),
        "completion_status": "source_metadata_gap_for_top12" if source_metadata_gap else ("comment_backfill_needed" if needs_fetch_vids else ("complete_with_authorized_top12_backfill" if args.top12_comments_run_id else "complete_from_existing_rows")),
        "top_level_comments_collected": len(top_rows),
        "replies_collected": len(reply_rows),
        "all_comments_collected": len(all_rows),
        "comments_collected": len(comments_rows),
        "partial": partial,
        "incomplete_video_count": len(needs_fetch_vids),
        "profiles_collected": False,
        "safety_excluded_ids": sorted(SAFETY_EXCLUDED_IDS),
        "safety_excluded_ids_found_in_corrected_scope": sorted(corrected_vids & SAFETY_EXCLUDED_IDS),
        "local_derivation_no_live_api_calls": True,
        "env_read_by_derivation_script": False,
        "old_audit_counts": {k: old_audit.get(k) for k in ["target_video_count", "top_level_comments_collected", "replies_collected", "all_comments_collected", "partial", "incomplete_video_count", "profiles_collected"]},
        "input_file_sha256": {
            "old_target_video_manifest_csv": sha256_file(OLD_RUN / "target_video_manifest.csv"),
            "old_top_level_comments_csv": sha256_file(OLD_RUN / "top_level_comments.csv"),
            "old_replies_csv": sha256_file(OLD_RUN / "replies.csv"),
            "old_all_comments_csv": sha256_file(OLD_RUN / "all_comments.csv"),
            "old_comments_csv": sha256_file(OLD_RUN / "comments.csv"),
            "old_comment_video_summary_csv": sha256_file(OLD_RUN / "comment_video_summary.csv"),
            "source_videos_csv": sha256_file(SOURCE_RUN / "videos.csv"),
            **prefixed_sha_inputs({
                "top12_metadata_videos_csv": top12_metadata_run / "videos.csv" if top12_metadata_run else Path("__missing__"),
                "top12_comments_top_level_comments_csv": top12_comments_run / "top_level_comments.csv" if top12_comments_run else Path("__missing__"),
                "top12_comments_replies_csv": top12_comments_run / "replies.csv" if top12_comments_run else Path("__missing__"),
                "top12_comments_all_comments_csv": top12_comments_run / "all_comments.csv" if top12_comments_run else Path("__missing__"),
                "top12_comments_summary_csv": top12_comments_run / "comment_video_summary.csv" if top12_comments_run else Path("__missing__"),
            }),
        },
        "needs_comment_fetch_manifest": str(out_dir / "needs_comment_fetch_manifest.csv"),
    }
    report = dict(old_report)
    report.update({
        "run_id": new_run_id,
        "mode": "derived_from_processed_runs",
        "live_fetch": bool(args.live_api_authorized),
        "video_source_mode": "derived_from_processed_runs",
        "endpoint_call_counts": {},
        "partial_reason": "source_metadata_gap_for_top12" if source_metadata_gap else ("comment_backfill_needed" if needs_fetch_vids else None),
        "derived_from_run_id": OLD_RUN_ID,
        "source_run_id": SOURCE_RUN_ID,
        "top12_metadata_run_id": args.top12_metadata_run_id,
        "top12_comments_run_id": args.top12_comments_run_id,
        "collection_type": audit["collection_type"],
        "target_caption_hashtags": CORRECTED_INCLUDED_TAGS,
        "counts": {
            **old_report.get("counts", {}),
            "videos": len(corrected_vids),
            "comments": len(top_rows),
            "replies": len(reply_rows),
            "profiles": 0,
            "text_items": len(all_rows),
        },
        "scope": {
            "type": "caption_hashtag_scope_change_derived",
            "removed_caption_hashtag": REMOVE_TAG,
            "skipped_caption_hashtag": SKIP_TAG,
            "added_caption_hashtag": ADD_TAG,
            "corrected_caption_hashtags": CORRECTED_INCLUDED_TAGS,
        },
        "target_video_count": len(corrected_vids),
        "top_level_comments_collected": len(top_rows),
        "replies_collected": len(reply_rows),
        "all_comments_collected": len(all_rows),
        "comments_collected": True,
        "profiles_collected": False,
        "partial": partial,
        "incomplete_video_count": len(needs_fetch_vids),
        "stage_counts": {
            **old_report.get("stage_counts", {}),
            "old_target_caption_hashtag_video_ids": len(old_target_vids),
            "old_comment_covered_video_ids": len(old_comment_covered_vids),
            "removed_jinjiang_binguan_video_ids": len(remove_vids),
            "top12_jian_source_video_ids": len(add_vids_all),
            "top12_jian_added_video_ids": len(add_new_vids),
            "selected_video_ids": len(corrected_vids),
            "needs_comment_fetch_video_ids": len(needs_fetch_vids),
            "top12_jian_source_metadata_gap": source_metadata_gap,
        },
        "completion_status": audit["completion_status"],
        "top12_source_metadata_gap": source_metadata_gap,
        "top12_source_metadata_gap_manifest": str(out_dir / "source_metadata_gap_manifest.csv"),
        "local_derivation_no_live_api_calls": True,
        "live_api_used_for_top12_backfill": bool(args.live_api_authorized),
        "scope_change_audit": "scope_change_audit.json",
        "needs_comment_fetch_manifest": "needs_comment_fetch_manifest.csv",
        "source_metadata_gap_manifest": "source_metadata_gap_manifest.csv",
        "stage_status": {
            **old_report.get("stage_status", {}),
            "comments": "derived_partial_needs_fetch" if partial else "derived_complete_with_top12_backfill",
            "replies": "derived_partial_needs_fetch" if partial else "derived_complete_with_top12_backfill",
            "profiles": "disabled",
        },
    })
    report["selection_metadata"] = {
        "collection_scope": "caption_hashtag_scope_change_remove_binguan_add_jian_derived",
        "selection_source": f"{SOURCE_RUN_ID}/videos.csv" + (f" + {args.top12_metadata_run_id}/videos.csv + {args.top12_comments_run_id}/comments" if args.top12_metadata_run_id or args.top12_comments_run_id else ""),
        "caption_hashtags": CORRECTED_INCLUDED_TAGS,
        "removed_caption_hashtag": REMOVE_TAG,
        "skipped_caption_hashtag": SKIP_TAG,
        "added_caption_hashtag": ADD_TAG,
        "source_metadata_gap_for_top12": source_metadata_gap,
        "top12_metadata_run_id": args.top12_metadata_run_id,
        "top12_comments_run_id": args.top12_comments_run_id,
        "live_api_used_for_top12_backfill": bool(args.live_api_authorized),
        "stage_counts": report.get("stage_counts", {}),
        "stage_status": report.get("stage_status", {}),
    }
    report["old_report_snapshot"] = {
        "note": "Selected old live-run fields preserved for lineage only; top-level report fields describe this derived offline run.",
        "run_id": old_report.get("run_id"),
        "collection_type": old_report.get("collection_type"),
        "target_caption_hashtags": old_report.get("target_caption_hashtags"),
        "counts": old_report.get("counts"),
        "endpoint_call_counts": old_report.get("endpoint_call_counts"),
        "created_at": old_report.get("created_at"),
    }

    (out_dir / "scope_change_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "collection_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    top12_status_note = (
        f"`{ADD_TAG}` is absent from the local source `videos.csv`; this derived run removes `{REMOVE_TAG}` "
        "but cannot claim complete top12 inclusion until metadata/source scope is supplemented."
        if source_metadata_gap
        else (
            f"`{ADD_TAG}` is present in the combined source metadata and all included top12 videos have comment/reply coverage."
            if not needs_fetch_vids
            else f"`{ADD_TAG}` is present in the combined source metadata; check `needs_comment_fetch_manifest.csv` before claiming comment/reply completeness."
        )
    )
    (out_dir / "README.md").write_text(
        f"""# Jinjiang Douyin derived scope run

- run_id: `{new_run_id}`
- derived_from: `{OLD_RUN_ID}`
- source_metadata: `{SOURCE_RUN_ID}`
- removed: `{REMOVE_TAG}` by `matched_caption_hashtags` caption-hashtag predicate
- skipped: `{SKIP_TAG}`
- added: `{ADD_TAG}` from authorized top12 metadata run if provided, otherwise local `videos.csv` only
- live API during derivation: not run
- live API used for upstream top12 backfill: `{str(bool(args.live_api_authorized)).lower()}`
- profiles_collected: false
- partial: `{str(partial).lower()}`
- completion_status: `{audit["completion_status"]}`

## Key counts

| metric | value |
|---|---:|
| old_unique_target_videos | {len(old_target_vids)} |
| removed_jinjiang_binguan_unique_videos | {len(remove_vids)} |
| top12_source_unique_videos | {len(add_vids_all)} |
| top12_new_unique_videos | {len(add_new_vids)} |
| corrected_unique_target_videos | {len(corrected_vids)} |
| top_level_comments | {len(top_rows)} |
| replies | {len(reply_rows)} |
| all_comments | {len(all_rows)} |
| needs_comment_fetch_unique_videos | {len(needs_fetch_vids)} |
| source_metadata_gap_for_top12 | {str(source_metadata_gap).lower()} |

## Provenance

| input | sha256 |
|---|---|
| old target manifest | `{sha256_file(OLD_RUN / "target_video_manifest.csv")}` |
| old top_level_comments | `{sha256_file(OLD_RUN / "top_level_comments.csv")}` |
| old replies | `{sha256_file(OLD_RUN / "replies.csv")}` |
| old all_comments | `{sha256_file(OLD_RUN / "all_comments.csv")}` |
| source videos | `{sha256_file(SOURCE_RUN / "videos.csv")}` |
{f"| top12 metadata videos | `{sha256_file(top12_metadata_run / 'videos.csv')}` |" if top12_metadata_run and (top12_metadata_run / 'videos.csv').exists() else ""}
{f"| top12 comments all_comments | `{sha256_file(top12_comments_run / 'all_comments.csv')}` |" if top12_comments_run and (top12_comments_run / 'all_comments.csv').exists() else ""}

See `scope_change_audit.json`, `needs_comment_fetch_manifest.csv`, and `source_metadata_gap_manifest.csv`.

## Top12 source metadata status

{top12_status_note}
""",
        encoding="utf-8",
    )
    doc_path = Path("docs/04-开发验证/jinjiang-douyin-caption-hashtag-scope-change-remove-jinjiang-binguan-add-jian-20260620.md")
    doc_path.write_text(
        f"""# 锦江 Douyin caption hashtag 口径二次修正审计

- generated_at: `{now}`
- derived_run_id: `{new_run_id}`
- old_run_id: `{OLD_RUN_ID}`
- source_run_id: `{SOURCE_RUN_ID}`
- completion_status: `{audit["completion_status"]}`
- partial: `{str(partial).lower()}`
- source_metadata_gap_for_top12: `{str(source_metadata_gap).lower()}`
- live_api_used_for_top12_backfill: `{str(bool(args.live_api_authorized)).lower()}`
- derivation_live_api_calls: `false`
- profiles_collected: `false`

## 口径变更

- 移除：`{REMOVE_TAG}`，以旧 manifest 的 `matched_caption_hashtags` caption-hashtag 语义为主。
- 跳过：`{SKIP_TAG}`。
- 补充：`{ADD_TAG}`；若提供授权 live top12 run，则合并该 run 的 metadata 与 comments/replies。
- 保持排除 safety video_id：`7486704870804770107`, `7486891790218399034`。

## 派生审计结果

| 指标 | 数值 |
|---|---:|
| 当前 unique target videos | {len(old_target_vids)} |
| manifest physical rows | {len(manifest)} |
| 含 #锦江宾馆 unique videos | {len(remove_vids)} |
| 剔除 #锦江宾馆 后剩余 unique videos | {len(base_keep_vids)} |
| source metadata 中 #锦江都城酒店吉安 unique videos | {len(add_vids_all)} |
| top12 已在旧 comments run 覆盖 | {len(add_covered_by_old_run)} |
| top12 授权补采 run 覆盖 | {len(add_covered_by_top12_run)} |
| top12 新增 unique videos | {len(add_new_vids)} |
| 修正后 unique target videos | {len(corrected_vids)} |
| top-level comments | {len(top_rows)} |
| replies | {len(reply_rows)} |
| all_comments | {len(all_rows)} |
| needs_comment_fetch videos | {len(needs_fetch_vids)} |
| partial | {str(partial).lower()} |
| completion_status | {audit["completion_status"]} |
| source_metadata_gap_for_top12 | {str(source_metadata_gap).lower()} |

## Provenance

| input | sha256 |
|---|---|
| old target manifest | `{sha256_file(OLD_RUN / "target_video_manifest.csv")}` |
| old top_level_comments | `{sha256_file(OLD_RUN / "top_level_comments.csv")}` |
| old replies | `{sha256_file(OLD_RUN / "replies.csv")}` |
| old all_comments | `{sha256_file(OLD_RUN / "all_comments.csv")}` |
| source videos | `{sha256_file(SOURCE_RUN / "videos.csv")}` |
{f"| top12 metadata videos | `{sha256_file(top12_metadata_run / 'videos.csv')}` |" if top12_metadata_run and (top12_metadata_run / 'videos.csv').exists() else ""}
{f"| top12 comments all_comments | `{sha256_file(top12_comments_run / 'all_comments.csv')}` |" if top12_comments_run and (top12_comments_run / 'all_comments.csv').exists() else ""}

## 结论

当前本地 source `videos.csv` 中 `{ADD_TAG}` 视频数为 `{len(add_vids_all)}`。因此本次生成的是离线 derived scope audit：已完成 `{REMOVE_TAG}` 剔除和旧评论/回复复用，{f"但还不能声称完成 top12 `{ADD_TAG}` 纳入。若后续补齐 metadata 后发现新增视频，需要用户另行授权 live API 后再补采评论/回复。" if source_metadata_gap else f"且本地 source metadata 已覆盖 top12 `{ADD_TAG}`；若 needs_comment_fetch videos 大于 0，需要另行授权 live API 后补采评论/回复。"}

Derived processed path:

`{out_dir}`
""",
        encoding="utf-8",
    )
    print(json.dumps({
        "new_run_id": new_run_id,
        "out_dir": str(out_dir),
        "doc_path": str(doc_path),
        "current_unique_target_videos": len(old_target_vids),
        "old_comment_covered_unique_videos": len(old_comment_covered_vids),
        "removed_jinjiang_binguan_unique_videos": len(remove_vids),
        "top12_source_unique_videos": len(add_vids_all),
        "top12_new_unique_videos": len(add_new_vids),
        "top12_comments_covered_unique_videos": len(add_vids & top12_comment_covered_vids),
        "corrected_unique_target_videos": len(corrected_vids),
        "top_level_comments_collected": len(top_rows),
        "replies_collected": len(reply_rows),
        "all_comments_collected": len(all_rows),
        "partial": partial,
        "incomplete_video_count": len(needs_fetch_vids),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
