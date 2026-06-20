from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import html
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCOPE_ANALYSIS_SCHEMA_VERSION = "top10_jinjiang_video_scope.v1"
EXCLUDED_TAG_REASONS = {
    "酒店": "泛化酒店主题，且名称不带锦江",
    "住宿": "泛化/弱相关住宿主题，且名称不带锦江",
    "高性价比酒店推荐": "消费决策相关但名称不带锦江，不属于本轮名称带锦江 top10",
}
SOURCE_SUMMARY_COLUMNS = [
    "source_challenge_rank",
    "source_challenge_name",
    "source_challenge_id",
    "indexed_video_ids",
    "selected_video_ids",
    "videos_with_caption",
    "videos_with_hashtags",
]
CAPTION_MATCH_COLUMNS = [
    "caption_hashtag",
    "matched_video_count",
    "unique_video_count",
    "over_1000_video_count",
    "over_10000_video_count",
    "max_metadata_comment_count",
    "sum_metadata_comment_count",
    "median_metadata_comment_count",
]
MULTILABEL_COLUMNS = [
    "video_id",
    "source_challenge_name",
    "source_challenge_id",
    "caption_hashtag",
    "caption",
    "metadata_comment_count",
    "over_1000_by_metadata",
    "over_10000_by_metadata",
    "comment_count_confidence",
    "needs_comment_fetch",
]
UNIVERSE_COLUMNS = [
    "video_id",
    "source_challenge_name",
    "source_challenge_id",
    "caption_hashtags",
    "caption_hashtag_count",
    "caption",
    "metadata_comment_count",
    "over_1000_by_metadata",
    "over_10000_by_metadata",
    "comment_count_confidence",
    "needs_comment_fetch",
    "source_tag_missing_from_caption",
]
CANDIDATE_COLUMNS = [
    "video_id",
    "source_challenge_name",
    "source_challenge_id",
    "caption_hashtags",
    "caption",
    "metadata_comment_count",
    "over_1000_by_metadata",
    "over_10000_by_metadata",
    "comment_count_confidence",
    "needs_comment_fetch",
]
AUTHORITATIVE_OUTPUTS = {
    "source_summary": "top10_jinjiang_video_source_summary.csv",
    "caption_hashtag_matches": "top10_jinjiang_caption_hashtag_matches.csv",
    "caption_hashtag_multilabel_detail": "top10_jinjiang_caption_hashtag_multilabel_detail.csv",
    "video_universe": "top10_jinjiang_video_universe.csv",
    "comment_count_candidates": "top10_jinjiang_comment_count_candidates.csv",
    "metadata_audit": "top10_jinjiang_video_metadata_audit.json",
}


@dataclass(frozen=True)
class ScopeAnalysisPaths:
    source_summary: Path
    caption_matches: Path
    multilabel_detail: Path
    video_universe: Path
    comment_count_candidates: Path
    metadata_audit: Path
    markdown_report: Path


def analyze_processed_run(
    processed_dir: Path,
    *,
    output_dir: Path | None = None,
    report_path: Path | None = None,
    manifest_path: Path | None = None,
    run_label: str | None = None,
) -> ScopeAnalysisPaths:
    output_dir = output_dir or processed_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    videos = read_csv(processed_dir / "videos.csv")
    report = read_json(processed_dir / "collection_report.json")
    scope_rows = load_scope_rows(manifest_path)
    tags = [row["name"] for row in scope_rows]
    source_summary = build_source_summary(videos, report, scope_rows)
    multilabel_rows, universe_rows, caption_summary = build_caption_outputs(videos, tags)
    candidate_rows = build_comment_count_candidates(universe_rows)
    audit = build_metadata_audit(
        videos,
        report,
        tags,
        source_summary,
        multilabel_rows,
        universe_rows,
        manifest_path=manifest_path,
    )

    source_path = output_dir / "top10_jinjiang_video_source_summary.csv"
    caption_path = output_dir / "top10_jinjiang_caption_hashtag_matches.csv"
    multilabel_path = output_dir / "top10_jinjiang_caption_hashtag_multilabel_detail.csv"
    universe_path = output_dir / "top10_jinjiang_video_universe.csv"
    candidate_path = output_dir / "top10_jinjiang_comment_count_candidates.csv"
    audit_path = output_dir / "top10_jinjiang_video_metadata_audit.json"
    markdown_path = report_path or output_dir / "jinjiang-douyin-top10-jinjiang-video-scope-report.md"

    write_csv(source_path, SOURCE_SUMMARY_COLUMNS, source_summary)
    write_csv(caption_path, CAPTION_MATCH_COLUMNS, caption_summary)
    write_csv(multilabel_path, MULTILABEL_COLUMNS, multilabel_rows)
    write_csv(universe_path, UNIVERSE_COLUMNS, universe_rows)
    write_csv(candidate_path, CANDIDATE_COLUMNS, candidate_rows)
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(
        render_markdown(
            run_label or processed_dir.name,
            tags,
            source_summary,
            caption_summary,
            universe_rows,
            candidate_rows,
            audit,
        ),
        encoding="utf-8",
    )
    return ScopeAnalysisPaths(
        source_path, caption_path, multilabel_path, universe_path, candidate_path, audit_path, markdown_path
    )


def load_scope_tags(manifest_path: Path | None = None) -> list[str]:
    return [row["name"] for row in load_scope_rows(manifest_path)]


def load_scope_rows(manifest_path: Path | None = None) -> list[dict[str, str]]:
    if manifest_path is None:
        raise ValueError("top10 Jinjiang analysis requires --selection-manifest to lock the exact 10-tag scope")
    data = read_json(manifest_path)
    manifest_rows = data.get("challenge_selections", data) if isinstance(data, dict) else data
    rows = []
    for index, row in enumerate(manifest_rows, start=1):
        if not isinstance(row, dict) or row.get("include") is False:
            continue
        tag = str(row.get("tag") or row.get("name") or row.get("challenge_name") or "").strip()
        if tag:
            rows.append(
                {
                    "rank": str(row.get("rank") or index),
                    "name": tag,
                    "challenge_id": str(row.get("challenge_id") or row.get("cid") or row.get("cha_id") or ""),
                }
            )
    tags = [row["name"] for row in rows]
    validate_scope_tags(tags)
    return rows


def validate_scope_tags(tags: list[str]) -> None:
    if len(tags) != len(set(tags)):
        raise ValueError("scope tags must be unique")
    if len(tags) != 10:
        raise ValueError("top10 Jinjiang scope requires exactly 10 included tags")
    excluded = set(tags) & set(EXCLUDED_TAG_REASONS)
    if excluded:
        raise ValueError(f"scope tags include excluded generic tags: {sorted(excluded)}")
    non_jinjiang = [tag for tag in tags if "锦江" not in tag]
    if non_jinjiang:
        raise ValueError(f"scope tags must all contain 锦江: {non_jinjiang}")


def build_source_summary(
    videos: list[dict[str, str]], report: dict[str, Any], scope_rows: list[dict[str, str]] | None = None
) -> list[dict[str, Any]]:
    by_source: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in videos:
        by_source[(row.get("source_challenge_name", ""), row.get("source_challenge_id", ""))].append(row)
    output: list[dict[str, Any]] = []
    if scope_rows:
        source_keys = [(row["name"], row.get("challenge_id", ""), row.get("rank", "")) for row in scope_rows]
    else:
        source_keys = [
            (name, cid, str(min(parse_int(row.get("source_challenge_rank")) for row in rows) if rows else ""))
            for (name, cid), rows in by_source.items()
        ]
    for name, cid, rank in sorted(source_keys, key=lambda item: (parse_int(item[2]), item[0], item[1])):
        rows = by_source.get((name, cid), [])
        output.append(
            {
                "source_challenge_rank": rank,
                "source_challenge_name": name,
                "source_challenge_id": cid,
                "indexed_video_ids": len({row.get("video_id", "") for row in rows if row.get("video_id")}),
                "selected_video_ids": len({row.get("video_id", "") for row in rows if row.get("video_id")}),
                "videos_with_caption": sum(1 for row in rows if row.get("caption", "").strip()),
                "videos_with_hashtags": sum(1 for row in rows if parse_hashtags_field(row.get("hashtags", ""))),
            }
        )
    return output


def build_caption_outputs(
    videos: list[dict[str, str]], tags: list[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    tag_set = set(tags)
    tag_order = {tag: index for index, tag in enumerate(tags)}
    multilabel_rows: list[dict[str, Any]] = []
    universe_rows_by_video_id: dict[str, dict[str, Any]] = {}
    matched_by_tag: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for row in videos:
        video_id = row.get("video_id", "")
        hashtags = [tag for tag in parse_hashtags_field(row.get("hashtags", "")) if tag in tag_set]
        hashtags = sorted(set(hashtags), key=lambda tag: tag_order[tag])
        comment_count = parse_int(row.get("comment_count"))
        confidence = comment_count_confidence(row)
        needs_fetch = needs_comment_fetch(row, confidence)
        for tag in hashtags:
            matched_by_tag[tag].append((video_id, comment_count))
            multilabel_rows.append(
                {
                    "video_id": video_id,
                    "source_challenge_name": row.get("source_challenge_name", ""),
                    "source_challenge_id": row.get("source_challenge_id", ""),
                    "caption_hashtag": f"#{tag}",
                    "caption": row.get("caption", ""),
                    "metadata_comment_count": comment_count,
                    "over_1000_by_metadata": str(comment_count >= 1000).lower(),
                    "over_10000_by_metadata": str(comment_count >= 10000).lower(),
                    "comment_count_confidence": confidence,
                    "needs_comment_fetch": str(needs_fetch).lower(),
                }
            )
        source_name = row.get("source_challenge_name", "")
        universe_rows_by_video_id.setdefault(
            video_id,
            {
                "video_id": video_id,
                "source_challenge_name": source_name,
                "source_challenge_id": row.get("source_challenge_id", ""),
                "caption_hashtags": ";".join(f"#{tag}" for tag in hashtags),
                "caption_hashtag_count": len(hashtags),
                "caption": row.get("caption", ""),
                "metadata_comment_count": comment_count,
                "over_1000_by_metadata": str(comment_count >= 1000).lower(),
                "over_10000_by_metadata": str(comment_count >= 10000).lower(),
                "comment_count_confidence": confidence,
                "needs_comment_fetch": str(needs_fetch).lower(),
                "source_tag_missing_from_caption": str(
                    bool(source_name in tag_set and source_name not in hashtags)
                ).lower(),
            },
        )
    universe_rows = list(universe_rows_by_video_id.values())
    caption_summary = []
    for tag in tags:
        matches = matched_by_tag.get(tag, [])
        unique_counts = max_comment_count_by_video(matches)
        counts = list(unique_counts.values())
        caption_summary.append(
            {
                "caption_hashtag": f"#{tag}",
                "matched_video_count": len(matches),
                "unique_video_count": len(unique_counts),
                "over_1000_video_count": sum(1 for value in counts if value >= 1000),
                "over_10000_video_count": sum(1 for value in counts if value >= 10000),
                "max_metadata_comment_count": max(counts, default=0),
                "sum_metadata_comment_count": sum(counts),
                "median_metadata_comment_count": median_int(counts),
            }
        )
    return multilabel_rows, universe_rows, caption_summary


def max_comment_count_by_video(matches: list[tuple[str, int]]) -> dict[str, int]:
    output: dict[str, int] = {}
    for video_id, comment_count in matches:
        output[video_id] = max(output.get(video_id, 0), comment_count)
    return output


def median_int(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return round((ordered[mid - 1] + ordered[mid]) / 2)


def build_comment_count_candidates(universe_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = [row for row in universe_rows if parse_int(str(row.get("metadata_comment_count"))) >= 1000]
    return sorted(candidates, key=lambda row: parse_int(str(row.get("metadata_comment_count"))), reverse=True)


def build_metadata_audit(
    videos: list[dict[str, str]],
    report: dict[str, Any],
    tags: list[str],
    source_summary: list[dict[str, Any]],
    multilabel_rows: list[dict[str, Any]],
    universe_rows: list[dict[str, Any]],
    manifest_path: Path | None,
) -> dict[str, Any]:
    endpoint_calls = (
        report.get("endpoint_call_counts", {}) if isinstance(report.get("endpoint_call_counts"), dict) else {}
    )
    forbidden = {
        "fetch_video_comments",
        "fetch_video_comment_replies",
        "handler_user_profile",
        "comments",
        "comment_replies",
        "user_profile",
    }
    forbidden_calls = {key: value for key, value in endpoint_calls.items() if key in forbidden and value}
    source_mismatch = [row for row in universe_rows if row["source_tag_missing_from_caption"] == "true"]
    caption_source_mismatch = [
        row
        for row in multilabel_rows
        if row.get("caption_hashtag", "").lstrip("#") != row.get("source_challenge_name", "")
    ]
    multi_tag = [row for row in universe_rows if int(row["caption_hashtag_count"]) > 1]
    return {
        "analysis_schema_version": SCOPE_ANALYSIS_SCHEMA_VERSION,
        "scope_tags": tags,
        "scope_manifest": manifest_provenance(manifest_path),
        "authoritative_outputs": AUTHORITATIVE_OUTPUTS,
        "excluded_tags": EXCLUDED_TAG_REASONS,
        "counts": {
            "videos_csv_rows": len(videos),
            "source_challenge_rows": len(source_summary),
            "deduped_video_total": len({row.get("video_id") for row in videos}),
            "multilabel_match_total": len(multilabel_rows),
            "videos_with_multiple_top10_caption_hashtags": len(multi_tag),
            "source_without_matching_caption_hashtag": len(source_mismatch),
            "caption_hashtag_source_mismatch": len(caption_source_mismatch),
            "over_1000_candidate_videos": sum(
                1 for row in universe_rows if parse_int(str(row.get("metadata_comment_count"))) >= 1000
            ),
            "over_10000_candidate_videos": sum(
                1 for row in universe_rows if parse_int(str(row.get("metadata_comment_count"))) >= 10000
            ),
        },
        "stage_status": report.get("stage_status", {}),
        "comments_collected": report.get("comments_collected"),
        "profiles_collected": report.get("profiles_collected"),
        "endpoint_call_counts": endpoint_calls,
        "forbidden_endpoint_calls": forbidden_calls,
        "comment_count_policy": {
            "over_1000_rule": "metadata_comment_count >= 1000",
            "precision_note": "Exact comment counts require later comment pagination or a trusted TikHub count field; this phase does not fetch comments.",
        },
    }


def parse_hashtags_field(value: str) -> list[str]:
    stripped = (value or "").strip()
    if not stripped:
        return []
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        try:
            parsed = ast.literal_eval(stripped)
        except (ValueError, SyntaxError):
            parsed = None
    if isinstance(parsed, list):
        return [str(item).strip().lstrip("#") for item in parsed if str(item).strip()]
    return [
        part.strip().lstrip("#") for part in stripped.replace("|", ";").replace(",", ";").split(";") if part.strip()
    ]


def comment_count_confidence(row: dict[str, str]) -> str:
    if row.get("metadata_source") == "app_v3_detail" or row.get("raw_detail_status") == "detail":
        return "detail_metadata"
    if row.get("comment_count", "") == "":
        return "missing"
    return "metadata_level_needs_confirmation"


def needs_comment_fetch(row: dict[str, str], confidence: str) -> bool:
    return confidence != "detail_metadata" or row.get("comment_count", "") == ""


def parse_int(value: str | None) -> int:
    try:
        return int(float(value or 0))
    except ValueError:
        return 0


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def manifest_provenance(manifest_path: Path | None) -> dict[str, str]:
    if manifest_path is None:
        return {}
    return {
        "path": str(manifest_path),
        "sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    }


def render_markdown(
    run_label: str,
    tags: list[str],
    source_summary: list[dict[str, Any]],
    caption_summary: list[dict[str, Any]],
    universe_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
    audit: dict[str, Any],
) -> str:
    lines = [
        "# 锦江 Douyin top10 名称带锦江视频集合统计报告",
        "",
        f"- run: `{run_label}`",
        "- scope: 只统计 10 个名称带 `锦江` 的 source challenge 与 caption hashtag。",
        f"- selection_manifest: `{audit.get('scope_manifest', {}).get('path', '')}`",
        f"- selection_manifest_sha256: `{audit.get('scope_manifest', {}).get('sha256', '')}`",
        f"- analysis_schema_version: `{audit.get('analysis_schema_version', '')}`",
        "- authoritative outputs: 本报告只以 `top10_jinjiang_*` CSV/JSON 作为本阶段统计依据；同目录下 `comments.csv` / `profiles.csv` / `edges.csv` 等为通用 normalizer 占位或派生产物，不代表本阶段抓取了评论正文、replies 或 profiles。",
        "- caption hashtag 口径: 只认显式 `#锦江...`；普通文本不进入主计数。",
        "- collection mode: **metadata-only**，不是评论正文抓取。",
        "- comments/replies/profiles: 本阶段不抓取评论正文、不抓 replies、不抓 profiles。",
        "- comment_count 来源: 视频 metadata/detail/list 字段；`metadata_level_needs_confirmation` 适合预筛，精确评论总数仍需后续 detail/comment 阶段确认。",
        "- 本阶段只判断是否值得后续爬评论，不实际爬评论。",
        "",
        "## A. Scope",
        "",
    ]
    lines.extend(f"{index}. {tag}" for index, tag in enumerate(tags, start=1))
    lines.extend(["", "### Excluded", ""])
    lines.extend(f"- `{tag}`: {reason}" for tag, reason in EXCLUDED_TAG_REASONS.items())
    lines.extend(["", "## B. Source challenge 统计", "", markdown_table(SOURCE_SUMMARY_COLUMNS, source_summary)])
    lines.extend(["", "## C. Caption hashtag 统计", "", markdown_table(CAPTION_MATCH_COLUMNS, caption_summary)])
    lines.extend(
        [
            "",
            "## D. Source vs caption 差异",
            "",
            f"- deduped_video_total: `{audit['counts']['deduped_video_total']}`",
            f"- multilabel_match_total: `{audit['counts']['multilabel_match_total']}`",
            f"- source_without_matching_caption_hashtag: `{audit['counts']['source_without_matching_caption_hashtag']}`",
            f"- caption_hashtag_source_mismatch: `{audit['counts']['caption_hashtag_source_mismatch']}`",
            f"- videos_with_multiple_top10_caption_hashtags: `{audit['counts']['videos_with_multiple_top10_caption_hashtags']}`",
            f"- over_1000_candidate_videos: `{audit['counts']['over_1000_candidate_videos']}`",
            f"- over_10000_candidate_videos: `{audit['counts']['over_10000_candidate_videos']}`",
            "",
            "## E. 评论数过千判断（metadata-only）",
            "",
            "本阶段不抓评论。`metadata_comment_count >= 1000` 先标记为 metadata 层面过千候选；`>= 10000` 标记为 metadata 层面过万候选；缺失或 challenge-page provenance 需要后续 detail/comment 阶段确认。",
            "",
            markdown_table(
                [
                    "video_id",
                    "source_challenge_name",
                    "caption_hashtags",
                    "metadata_comment_count",
                    "over_1000_by_metadata",
                    "over_10000_by_metadata",
                    "comment_count_confidence",
                    "needs_comment_fetch",
                ],
                universe_rows,
            ),
            "",
            "## F. 过千/过万候选视频（仅 metadata 预筛）",
            "",
            markdown_table(CANDIDATE_COLUMNS, candidate_rows),
            "",
            "## Safety audit",
            "",
            f"- comments_collected: `{audit.get('comments_collected')}`",
            f"- profiles_collected: `{audit.get('profiles_collected')}`",
            f"- forbidden_endpoint_calls: `{audit.get('forbidden_endpoint_calls')}`",
        ]
    )
    return "\n".join(lines) + "\n"


def markdown_table(columns: list[str], rows: list[dict[str, Any]]) -> str:
    if not rows:
        rows = []
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = ["| " + " | ".join(markdown_cell(row.get(column, "")) for column in columns) + " |" for row in rows]
    return "\n".join([header, sep, *body])


def markdown_cell(value: Any) -> str:
    escaped = html.escape(str(value), quote=False)
    return (
        escaped
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r\n", "<br>")
        .replace("\n", "<br>")
        .replace("\r", "<br>")
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze top10 Jinjiang Douyin source/caption video scope from processed metadata"
    )
    parser.add_argument("--processed-dir", required=True)
    parser.add_argument("--output-dir")
    parser.add_argument("--report-path")
    parser.add_argument("--selection-manifest", required=True)
    parser.add_argument("--run-label")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    paths = analyze_processed_run(
        Path(args.processed_dir),
        output_dir=Path(args.output_dir) if args.output_dir else None,
        report_path=Path(args.report_path) if args.report_path else None,
        manifest_path=Path(args.selection_manifest) if args.selection_manifest else None,
        run_label=args.run_label,
    )
    print(json.dumps({key: str(value) for key, value in paths.__dict__.items()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
