from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any

from .douyin_collector import (
    METADATA_ONLY_STAGES,
    DouyinChallengeSelection,
    DouyinClientProtocol,
    DouyinCollector,
    DouyinCollectRequest,
    DouyinCommentCandidate,
)
from .douyin_models import COMMENT_COLUMNS
from .douyin_video_scope import analyze_processed_run, parse_hashtags_field
from .tikhub_client import TikHubClient, TikHubSettings, redact_secrets

JINJIANG_TOP10_CAPTION_HASHTAGS = [
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
DEFAULT_SAFETY_EXCLUDED_VIDEO_IDS = ["7486704870804770107", "7486891790218399034"]
DEFAULT_SAFETY_EXCLUSION_REASON = "女性安全/偷拍主题与当前锦江酒店评论研究目标不一致"


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class FixtureClient:
    def __init__(self, fixture: dict[str, Any]) -> None:
        self.fixture = fixture
        self.settings = TikHubSettings()
        self.endpoint_call_counts: dict[str, int] = {}

    def _get(self, key: str) -> Any:
        self.endpoint_call_counts[key] = self.endpoint_call_counts.get(key, 0) + 1
        return self.fixture.get(key, {})

    def fetch_topic_query(self, **payload: Any) -> Any:
        return self._get("topic_query")

    def fetch_challenge_posts(self, **payload: Any) -> Any:
        return self._get("challenge_posts")

    def _get_paged(self, key: str, payload: dict[str, Any]) -> Any:
        pages = self.fixture.get(f"{key}_pages")
        if isinstance(pages, dict):
            self.endpoint_call_counts[key] = self.endpoint_call_counts.get(key, 0) + 1
            return pages.get(str(payload.get("cursor", 0)), {})
        return self._get(key)

    def fetch_video_search_v2(self, **payload: Any) -> Any:
        return self._get_paged("video_search_v2", payload)

    def fetch_general_search_v2(self, **payload: Any) -> Any:
        return self._get_paged("general_search_v2", payload)

    def fetch_challenge_search_v2(self, **payload: Any) -> Any:
        return self._get_paged("challenge_search_v2", payload)

    def fetch_video_search(self, **payload: Any) -> Any:
        return self._get("video_search")

    def fetch_one_video(self, **params: Any) -> Any:
        video_id = str(params.get("aweme_id") or params.get("video_id") or "")
        details = self.fixture.get("video_details", {})
        if isinstance(details, dict):
            return details.get(video_id, {"video_id": video_id})
        return {"video_id": video_id}

    def fetch_hashtag_video_list(self, **params: Any) -> Any:
        return self._get_paged("hashtag_video_list", params)

    def fetch_video_comments(self, **params: Any) -> Any:
        video_id = str(params.get("aweme_id") or params.get("video_id") or "")
        return {"comments": self.fixture.get("comments", {}).get(video_id, [])}

    def fetch_video_comment_replies(self, **params: Any) -> Any:
        comment_id = str(params.get("comment_id") or "")
        return {"replies": self.fixture.get("replies", {}).get(comment_id, [])}

    def fetch_batch_user_profile(self, sec_user_ids: list[str]) -> Any:
        profiles = self.fixture.get("user_profiles", {})
        return {"users": [profiles[item] for item in sec_user_ids if item in profiles]}

    def handler_user_profile(self, sec_user_id: str) -> Any:
        return self.fixture.get("user_profiles", {}).get(sec_user_id, {"sec_user_id": sec_user_id})



def load_comment_candidate_manifest(path: Path) -> list[DouyinCommentCandidate]:
    data = load_comment_candidate_manifest_data(path)
    rows = data.get("comment_candidates", [])
    if not isinstance(rows, list):
        raise ValueError("comment candidate manifest must be a list or contain comment_candidates")
    candidates: list[DouyinCommentCandidate] = []
    seen_video_ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("comment candidate rows must be objects")
        video_id = str(row.get("video_id") or "").strip()
        if not video_id:
            raise ValueError("comment candidate rows require video_id")
        if video_id in seen_video_ids:
            raise ValueError(f"duplicate comment candidate video_id: {video_id}")
        seen_video_ids.add(video_id)
        raw_limit = row.get("comment_fetch_limit")
        if raw_limit in (None, "", "unbounded", "none", "null"):
            limit = None
        else:
            limit = int(raw_limit)
        candidates.append(
            DouyinCommentCandidate(
                video_id=video_id,
                source_challenge_name=str(row.get("source_challenge_name") or ""),
                source_challenge_id=str(row.get("source_challenge_id") or ""),
                metadata_comment_count=int(row.get("metadata_comment_count") or 0),
                comment_fetch_limit=limit,
                caption_hashtags=str(row.get("caption_hashtags") or ""),
                exclusion_reason=str(row.get("exclusion_reason") or ""),
            )
        )
    return candidates


def load_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def build_caption_hashtag_comment_targets(
    rows: list[dict[str, str]],
    *,
    caption_hashtags: list[str],
    excluded_video_ids: list[str],
) -> tuple[list[DouyinCommentCandidate], list[dict[str, Any]], list[str]]:
    tag_order = {tag.lstrip("#"): index for index, tag in enumerate(caption_hashtags)}
    excluded = set(str(video_id) for video_id in excluded_video_ids)
    targets_by_id: dict[str, dict[str, Any]] = {}
    excluded_found: list[str] = []
    for row in rows:
        video_id = str(row.get("video_id") or "").strip()
        if not video_id:
            continue
        row_tags = {tag for tag in parse_hashtags_field(row.get("hashtags", "")) if tag in tag_order}
        if not row_tags:
            continue
        matched = sorted(row_tags, key=lambda tag: tag_order[tag])
        if video_id in excluded:
            excluded_found.append(video_id)
            continue
        if video_id not in targets_by_id:
            targets_by_id[video_id] = {
                "video_id": video_id,
                "source_challenge_name": row.get("source_challenge_name", ""),
                "source_challenge_id": row.get("source_challenge_id", ""),
                "caption": row.get("caption", ""),
                "hashtags": row.get("hashtags", ""),
                "matched_caption_hashtags": ";".join(f"#{tag}" for tag in matched),
                "metadata_comment_count": parse_int(row.get("comment_count", "0")),
                "excluded": "false",
                "exclusion_reason": "",
            }
            continue
        existing = targets_by_id[video_id]
        merged = sorted(
            {tag.lstrip("#") for tag in str(existing["matched_caption_hashtags"]).split(";") if tag}
            | set(matched),
            key=lambda tag: tag_order[tag],
        )
        existing["matched_caption_hashtags"] = ";".join(f"#{tag}" for tag in merged)
        existing["metadata_comment_count"] = max(
            parse_int(str(existing.get("metadata_comment_count", 0))), parse_int(row.get("comment_count", "0"))
        )

    manifest_rows = sorted(targets_by_id.values(), key=lambda row: row["video_id"])
    candidates = [
        DouyinCommentCandidate(
            video_id=str(row["video_id"]),
            source_challenge_name=str(row.get("source_challenge_name", "")),
            source_challenge_id=str(row.get("source_challenge_id", "")),
            metadata_comment_count=parse_int(str(row.get("metadata_comment_count", 0))),
            comment_fetch_limit=None,
            caption_hashtags=str(row.get("matched_caption_hashtags", "")),
            exclusion_reason="",
        )
        for row in manifest_rows
    ]
    return candidates, manifest_rows, sorted(set(excluded_found))


def parse_int(value: Any) -> int:
    try:
        return int(float(str(value or 0)))
    except (TypeError, ValueError):
        return 0

def load_comment_candidate_manifest_data(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {"comment_candidates": data}


def load_comment_candidate_exclusions(path: Path) -> tuple[list[str], str]:
    data = load_comment_candidate_manifest_data(path)
    raw_excluded = data.get("excluded_video_ids", [])
    excluded: list[str] = []
    reasons: list[str] = []
    if isinstance(raw_excluded, list):
        for item in raw_excluded:
            if isinstance(item, dict):
                video_id = str(item.get("video_id") or "").strip()
                reason = str(item.get("exclusion_reason") or "").strip()
                if video_id:
                    excluded.append(video_id)
                if reason:
                    reasons.append(reason)
            else:
                video_id = str(item).strip()
                if video_id:
                    excluded.append(video_id)
    reason = str(data.get("exclusion_reason") or "").strip() or "; ".join(dict.fromkeys(reasons))
    return list(dict.fromkeys(excluded)), reason


def load_selection_manifest(path: Path) -> list[DouyinChallengeSelection]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("challenge_selections", data) if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise ValueError("selection manifest must be a list or contain challenge_selections")
    selections: list[DouyinChallengeSelection] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError("selection manifest rows must be objects")
        challenge_id = str(row.get("challenge_id") or row.get("cid") or row.get("cha_id") or "").strip()
        name = str(row.get("name") or row.get("tag") or row.get("challenge_name") or row.get("cha_name") or "").strip()
        if not challenge_id or not name:
            raise ValueError("selection manifest rows require challenge_id/cid and name/tag")
        selections.append(
            DouyinChallengeSelection(
                rank=int(row.get("rank") or index),
                name=name,
                challenge_id=challenge_id,
                source=str(row.get("source") or path),
                include=parse_bool(row.get("include", True)),
                include_reason=str(row.get("include_reason") or ""),
                exclude_reason=str(row.get("exclude_reason") or ""),
                is_generic=parse_bool(row.get("is_generic", False)),
            )
        )
    return selections


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def parse_stages(value: str | None) -> tuple[str, ...]:
    if not value:
        from .douyin_collector import FULL_COLLECT_STAGES

        return tuple(FULL_COLLECT_STAGES)
    stages = tuple(part.strip() for part in value.split(",") if part.strip())
    if not stages:
        raise ValueError("--stages must include at least one stage")
    return stages


def add_collect_arguments(parser: argparse.ArgumentParser, *, include_stage_switches: bool) -> None:
    parser.add_argument("--hashtag", default="锦江酒店")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--run-id")
    parser.add_argument("--output-root", default=".")
    parser.add_argument("--mock-fixture")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--env-file", help="Optional dotenv file to load explicitly; not loaded by default")
    parser.add_argument(
        "--challenge-id", help="Explicit Douyin challenge/cid to collect; skips live challenge discovery"
    )
    parser.add_argument("--selection-manifest", help="JSON file with challenge selections for a batch/top10 run")
    parser.add_argument("--collection-scope", default="single_hashtag")
    parser.add_argument("--selection-source", default="")
    if include_stage_switches:
        parser.add_argument(
            "--stages", help="Comma-separated stages: challenge_index,video_metadata,comments,replies,profiles"
        )
        parser.add_argument(
            "--skip-comments", action="store_true", help="Convenience alias to disable comments and replies stages"
        )
        parser.add_argument(
            "--skip-profiles", action="store_true", help="Convenience alias to disable profile collection"
        )
    parser.add_argument("--limit-profile", choices=["capped", "unbounded"], default="capped")
    parser.add_argument("--max-videos", type=int)
    parser.add_argument("--max-comments-per-video", type=int)
    parser.add_argument("--max-replies-per-comment", type=int)
    parser.add_argument("--max-users", type=int)
    parser.add_argument("--max-search-pages", type=int)
    parser.add_argument("--search-page-size", type=int)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TikHub Douyin data source utilities")
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect-douyin", help="Collect and normalize Douyin data")
    add_collect_arguments(collect, include_stage_switches=True)

    metadata = sub.add_parser(
        "collect-douyin-video-metadata", help="Collect Douyin challenge index and video metadata only"
    )
    add_collect_arguments(metadata, include_stage_switches=False)
    metadata.set_defaults(stages=",".join(METADATA_ONLY_STAGES), skip_comments=True, skip_profiles=True)

    candidate_comments = sub.add_parser(
        "collect-douyin-candidate-comments",
        help="Collect first-level comments for an explicit video candidate manifest",
    )
    add_collect_arguments(candidate_comments, include_stage_switches=False)
    candidate_comments.add_argument("--source-processed-dir", required=True)
    candidate_comments.add_argument("--comment-candidate-manifest", required=True)
    candidate_comments.add_argument("--report-path")
    candidate_comments.add_argument("--excluded-video-id", action="append", default=[])
    candidate_comments.add_argument("--exclusion-reason", default="")
    candidate_comments.set_defaults(stages="comments", skip_comments=False, skip_profiles=True)

    caption_comments = sub.add_parser(
        "collect-douyin-caption-hashtag-comments",
        help="Collect top-level comments and replies for videos matched by caption hashtags in a source videos.csv",
    )
    add_collect_arguments(caption_comments, include_stage_switches=False)
    caption_comments.add_argument("--source-processed-dir", required=True)
    caption_comments.add_argument("--caption-hashtag", action="append", default=[])
    caption_comments.add_argument("--report-path")
    caption_comments.add_argument("--excluded-video-id", action="append", default=[])
    caption_comments.add_argument("--exclusion-reason", default=DEFAULT_SAFETY_EXCLUSION_REASON)
    caption_comments.set_defaults(stages="comments,replies", skip_comments=False, skip_profiles=True)

    analyze = sub.add_parser(
        "analyze-douyin-video-scope",
        help="Analyze processed Douyin video metadata for top10 Jinjiang source/caption scope",
    )
    analyze.add_argument("--processed-dir", required=True)
    analyze.add_argument("--output-dir")
    analyze.add_argument("--report-path")
    analyze.add_argument("--selection-manifest", required=True)
    analyze.add_argument("--run-label")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command in {"collect-douyin", "collect-douyin-video-metadata", "collect-douyin-candidate-comments", "collect-douyin-caption-hashtag-comments"}:
        return collect_douyin(args)
    if args.command == "analyze-douyin-video-scope":
        return analyze_douyin_video_scope(args)
    parser.error("unknown command")
    return 2


def collect_douyin(args: argparse.Namespace) -> int:
    if requires_selection_manifest(args) and not args.selection_manifest:
        print(
            f"{args.command} with collection_scope={args.collection_scope!r} requires --selection-manifest",
            file=sys.stderr,
        )
        return 2
    if args.env_file:
        load_dotenv(Path(args.env_file))
    settings = TikHubSettings.from_env()
    if args.limit_profile == "unbounded":
        settings = settings.model_copy(
            update={
                "max_videos": None,
                "max_comments_per_video": None,
                "max_replies_per_comment": None,
                "max_users": None,
                "max_search_pages": None,
            }
        )
    overrides = {
        "max_videos": args.max_videos,
        "max_comments_per_video": args.max_comments_per_video,
        "max_replies_per_comment": args.max_replies_per_comment,
        "max_users": args.max_users,
        "max_search_pages": args.max_search_pages,
        "search_page_size": args.search_page_size,
    }
    settings = settings.model_copy(update={key: value for key, value in overrides.items() if value is not None})
    challenge_selections = load_selection_manifest(Path(args.selection_manifest)) if args.selection_manifest else None
    source_video_rows = (
        load_csv_rows(Path(args.source_processed_dir) / "videos.csv")
        if getattr(args, "source_processed_dir", None)
        else None
    )
    comment_candidates = (
        load_comment_candidate_manifest(Path(args.comment_candidate_manifest))
        if getattr(args, "comment_candidate_manifest", None)
        else None
    )
    target_manifest_rows: list[dict[str, Any]] = []
    caption_hashtags = [str(tag).strip().lstrip("#") for tag in getattr(args, "caption_hashtag", []) if str(tag).strip()]
    if args.command == "collect-douyin-caption-hashtag-comments":
        caption_hashtags = caption_hashtags or JINJIANG_TOP10_CAPTION_HASHTAGS
    excluded_video_ids = [str(value) for value in getattr(args, "excluded_video_id", [])]
    if args.command == "collect-douyin-caption-hashtag-comments":
        excluded_video_ids = list(dict.fromkeys([*DEFAULT_SAFETY_EXCLUDED_VIDEO_IDS, *excluded_video_ids]))
    manifest_exclusion_reason = ""
    excluded_found: list[str] = []
    if getattr(args, "comment_candidate_manifest", None):
        manifest_excluded, manifest_exclusion_reason = load_comment_candidate_exclusions(Path(args.comment_candidate_manifest))
        excluded_video_ids = list(dict.fromkeys([*manifest_excluded, *excluded_video_ids]))
    if args.command == "collect-douyin-caption-hashtag-comments":
        if source_video_rows is None:
            print("collect-douyin-caption-hashtag-comments requires --source-processed-dir/videos.csv", file=sys.stderr)
            return 2
        comment_candidates, target_manifest_rows, excluded_found = build_caption_hashtag_comment_targets(
            source_video_rows, caption_hashtags=caption_hashtags, excluded_video_ids=excluded_video_ids
        )
        if not comment_candidates:
            print("caption hashtag scope matched zero target videos", file=sys.stderr)
            return 2
    exclusion_reason = getattr(args, "exclusion_reason", "") or manifest_exclusion_reason
    if comment_candidates:
        candidate_ids = {candidate.video_id for candidate in comment_candidates}
        forbidden = candidate_ids & set(excluded_video_ids)
        if forbidden:
            print(f"comment candidate manifest includes excluded video_id(s): {sorted(forbidden)}", file=sys.stderr)
            return 2
        if args.command == "collect-douyin-caption-hashtag-comments":
            update = {
                "max_videos": None if args.max_videos is None else settings.max_videos,
                "max_comments_per_video": None if args.max_comments_per_video is None else settings.max_comments_per_video,
                "max_replies_per_comment": None if args.max_replies_per_comment is None else settings.max_replies_per_comment,
                "max_users": 0 if args.max_users is None else settings.max_users,
                "max_search_pages": None if args.max_search_pages is None else settings.max_search_pages,
            }
        else:
            update = {"max_comments_per_video": None, "max_replies_per_comment": 0, "max_users": 0, "max_search_pages": None}
        settings = settings.model_copy(update=update)
    stages = parse_stages(args.stages)
    if args.skip_comments:
        stages = tuple(stage for stage in stages if stage not in {"comments", "replies"})
    if args.skip_profiles:
        stages = tuple(stage for stage in stages if stage != "profiles")

    mode = "mock"
    if args.mock_fixture:
        fixture = json.loads(Path(args.mock_fixture).read_text(encoding="utf-8"))
        client: DouyinClientProtocol = FixtureClient(fixture)
        client.settings = settings
    else:
        ready, reason = settings.live_readiness()
        if not ready:
            print(f"TikHub live collection unavailable: {reason}", file=sys.stderr)
            return 2
        mode = "live"
        client = TikHubClient(settings)
    collector = DouyinCollector(client, settings)
    paths = collector.collect(
        DouyinCollectRequest(
            hashtag=args.hashtag,
            start_date=args.start_date,
            end_date=args.end_date,
            run_id=args.run_id,
            output_root=Path(args.output_root),
            resume=args.resume,
            mode=mode,
            challenge_id=args.challenge_id,
            challenge_selections=challenge_selections,
            selection_source=args.selection_source
            or (
                getattr(args, "comment_candidate_manifest", None)
                or args.selection_manifest
                or (str(Path(args.source_processed_dir) / "videos.csv") if getattr(args, "source_processed_dir", None) else "")
            ),
            collection_scope=args.collection_scope,
            stages=stages,
            comment_candidates=comment_candidates,
            source_video_rows=source_video_rows,
        )
    )
    if comment_candidates and args.command == "collect-douyin-candidate-comments":
        write_candidate_comment_outputs(
            processed_dir=paths["processed_dir"],
            raw_dir=paths["raw_dir"],
            run_id=args.run_id or paths["processed_dir"].name,
            candidates=comment_candidates,
            report_path=Path(args.report_path) if getattr(args, "report_path", None) else None,
            excluded_video_ids=excluded_video_ids,
            exclusion_reason=exclusion_reason,
        )
    if comment_candidates and args.command == "collect-douyin-caption-hashtag-comments":
        write_caption_hashtag_comment_outputs(
            processed_dir=paths["processed_dir"],
            raw_dir=paths["raw_dir"],
            run_id=args.run_id or paths["processed_dir"].name,
            candidates=comment_candidates,
            target_manifest_rows=target_manifest_rows,
            caption_hashtags=caption_hashtags,
            source_processed_dir=Path(args.source_processed_dir),
            report_path=Path(args.report_path) if getattr(args, "report_path", None) else None,
            excluded_video_ids=excluded_video_ids,
            excluded_found=excluded_found,
            exclusion_reason=exclusion_reason,
        )
    print(
        json.dumps(
            redact_secrets({key: str(value) for key, value in paths.items()}, [settings.api_key]), ensure_ascii=False
        )
    )
    return 0



def write_caption_hashtag_comment_outputs(
    *,
    processed_dir: Path,
    raw_dir: Path,
    run_id: str,
    candidates: list[DouyinCommentCandidate],
    target_manifest_rows: list[dict[str, Any]],
    caption_hashtags: list[str],
    source_processed_dir: Path,
    report_path: Path | None = None,
    excluded_video_ids: list[str] | None = None,
    excluded_found: list[str] | None = None,
    exclusion_reason: str = "",
) -> None:
    combined_comments_path = processed_dir / "comments.csv"
    all_comments = load_csv_rows(combined_comments_path) if combined_comments_path.exists() else []
    top_level_comments = [row for row in all_comments if row.get("comment_level") == "comment"]
    replies = [row for row in all_comments if row.get("comment_level") == "reply"]
    # Preserve the normalizer contract: comments.csv remains the canonical
    # combined comments+replies table. Convenience split files are additive.
    write_dict_csv(processed_dir / "all_comments.csv", all_comments, fieldnames=COMMENT_COLUMNS)
    write_dict_csv(processed_dir / "top_level_comments.csv", top_level_comments, fieldnames=COMMENT_COLUMNS)
    write_dict_csv(processed_dir / "replies.csv", replies, fieldnames=COMMENT_COLUMNS)

    target_manifest_path = processed_dir / "target_video_manifest.csv"
    write_dict_csv(
        target_manifest_path,
        target_manifest_rows,
        fieldnames=[
            "video_id",
            "source_challenge_name",
            "source_challenge_id",
            "caption",
            "hashtags",
            "matched_caption_hashtags",
            "metadata_comment_count",
            "excluded",
            "exclusion_reason",
        ],
    )

    report = json.loads((processed_dir / "collection_report.json").read_text(encoding="utf-8"))
    failed_pages = report.get("failed_pages", []) if isinstance(report.get("failed_pages"), list) else []
    comments_by_video: dict[str, list[dict[str, str]]] = {}
    replies_by_video: dict[str, list[dict[str, str]]] = {}
    comment_to_video: dict[str, str] = {}
    for row in top_level_comments:
        video_id = row.get("video_id", "")
        comments_by_video.setdefault(video_id, []).append(row)
        if row.get("comment_id"):
            comment_to_video[row["comment_id"]] = video_id
    for row in replies:
        replies_by_video.setdefault(row.get("video_id", ""), []).append(row)

    page_journals = load_page_journals(raw_dir)
    raw_comment_pages_by_video: dict[str, int] = {}
    raw_reply_pages_by_video: dict[str, int] = {}
    for page in page_journals:
        page_key = str(page.get("page_key", ""))
        raw_kind = str(page.get("raw_kind", ""))
        if raw_kind == "comments" and page_key.startswith("comments:"):
            parts = page_key.split(":")
            if len(parts) >= 2:
                raw_comment_pages_by_video[parts[1]] = raw_comment_pages_by_video.get(parts[1], 0) + 1
        if raw_kind == "comment_replies" and page_key.startswith("replies:"):
            parts = page_key.split(":")
            if len(parts) >= 2:
                video_id = comment_to_video.get(parts[1], "")
                if not video_id:
                    items = page.get("items", []) if isinstance(page.get("items"), list) else []
                    for item in items:
                        if isinstance(item, dict) and item.get("video_id"):
                            video_id = str(item["video_id"])
                            break
                if video_id:
                    raw_reply_pages_by_video[video_id] = raw_reply_pages_by_video.get(video_id, 0) + 1

    failed_comment_pages_by_video: dict[str, list[dict[str, Any]]] = {}
    failed_reply_pages_by_video: dict[str, list[dict[str, Any]]] = {}
    for item in failed_pages:
        page = str(item.get("page", "")) if isinstance(item, dict) else str(item)
        if page.startswith("comments:"):
            parts = page.split(":")
            if len(parts) >= 2:
                failed_comment_pages_by_video.setdefault(parts[1], []).append(item)
        if page.startswith("replies:"):
            parts = page.split(":")
            if len(parts) >= 2:
                video_id = comment_to_video.get(parts[1], "")
                if video_id:
                    failed_reply_pages_by_video.setdefault(video_id, []).append(item)

    manifest_by_id = {str(row["video_id"]): row for row in target_manifest_rows}
    summary_rows: list[dict[str, Any]] = []
    for candidate in candidates:
        video_id = candidate.video_id
        comment_failures = failed_comment_pages_by_video.get(video_id, [])
        reply_failures = failed_reply_pages_by_video.get(video_id, [])
        top_count = len(comments_by_video.get(video_id, []))
        reply_count = len(replies_by_video.get(video_id, []))
        raw_comment_pages = raw_comment_pages_by_video.get(video_id, 0)
        raw_reply_pages = raw_reply_pages_by_video.get(video_id, 0)
        if comment_failures:
            status = "partial" if top_count or reply_count else "failed"
        elif reply_failures:
            status = "reply_partial" if top_count or reply_count else "failed"
        elif raw_comment_pages == 0 and candidate.metadata_comment_count == 0:
            status = "complete"
        elif raw_comment_pages == 0:
            status = "not_collected"
        else:
            status = "complete"
        summary_rows.append(
            {
                "video_id": video_id,
                "source_challenge_name": candidate.source_challenge_name,
                "matched_caption_hashtags": manifest_by_id.get(video_id, {}).get("matched_caption_hashtags", candidate.caption_hashtags),
                "metadata_comment_count": candidate.metadata_comment_count,
                "top_level_comments_collected": top_count,
                "replies_collected": reply_count,
                "all_comments_collected": top_count + reply_count,
                "collection_status": status,
                "comment_failed_pages": json.dumps(comment_failures, ensure_ascii=False),
                "reply_failed_pages": json.dumps(reply_failures, ensure_ascii=False),
                "raw_comment_pages": raw_comment_pages,
                "raw_reply_pages": raw_reply_pages,
                "needs_more_comments": str(status in {"partial", "failed", "not_collected"} and (bool(comment_failures) or raw_comment_pages == 0)).lower(),
                "needs_more_replies": str(status in {"reply_partial", "failed"} and bool(reply_failures)).lower(),
                "exclusion_reason": "",
            }
        )
    summary_path = processed_dir / "comment_video_summary.csv"
    write_dict_csv(
        summary_path,
        summary_rows,
        fieldnames=[
            "video_id",
            "source_challenge_name",
            "matched_caption_hashtags",
            "metadata_comment_count",
            "top_level_comments_collected",
            "replies_collected",
            "all_comments_collected",
            "collection_status",
            "comment_failed_pages",
            "reply_failed_pages",
            "raw_comment_pages",
            "raw_reply_pages",
            "needs_more_comments",
            "needs_more_replies",
            "exclusion_reason",
        ],
    )

    partial_rows = [row for row in summary_rows if row["collection_status"] != "complete"]
    excluded = list(dict.fromkeys(excluded_video_ids or []))
    audit = {
        "run_id": run_id,
        "collection_type": "top10_caption_hashtag_all_comments",
        "source_run_id": source_processed_dir.name,
        "source_videos_csv": str(source_processed_dir / "videos.csv"),
        "caption_hashtags": [f"#{tag.lstrip('#')}" for tag in caption_hashtags],
        "target_video_count": len(candidates),
        "excluded_video_ids": excluded,
        "excluded_video_ids_found_in_source_scope": list(dict.fromkeys(excluded_found or [])),
        "exclusion_reason": exclusion_reason,
        "top_level_comments_collected": len(top_level_comments),
        "replies_collected": len(replies),
        "all_comments_collected": len(all_comments),
        "profiles_collected": False,
        "partial": bool(partial_rows),
        "complete_video_count": len(summary_rows) - len(partial_rows),
        "incomplete_video_count": len(partial_rows),
        "failed_comment_pages": [item for rows in failed_comment_pages_by_video.values() for item in rows],
        "failed_reply_pages": [item for rows in failed_reply_pages_by_video.values() for item in rows],
        "outputs": {
            "target_video_manifest": str(target_manifest_path),
            "comments": str(processed_dir / "comments.csv"),
            "top_level_comments": str(processed_dir / "top_level_comments.csv"),
            "replies": str(processed_dir / "replies.csv"),
            "all_comments": str(processed_dir / "all_comments.csv"),
            "comment_video_summary": str(summary_path),
            "collection_report": str(processed_dir / "collection_report.json"),
        },
    }
    (processed_dir / "comment_collection_audit.json").write_text(
        json.dumps(redact_secrets(audit), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    report["collection_type"] = "top10_caption_hashtag_all_comments"
    report["source_run_id"] = source_processed_dir.name
    report["source_videos_csv"] = str(source_processed_dir / "videos.csv")
    report["target_video_count"] = len(candidates)
    report["target_caption_hashtags"] = [f"#{tag.lstrip('#')}" for tag in caption_hashtags]
    report["excluded_video_ids_policy"] = "excluded from target_video_manifest and selected_video_ids"
    report["comments_collected"] = True
    report["replies_collected"] = True
    report["profiles_collected"] = False
    report.setdefault("stage_status", {})["comments"] = "enabled"
    report.setdefault("stage_status", {})["replies"] = "enabled"
    report.setdefault("stage_status", {})["profiles"] = "disabled"
    report.setdefault("stage_counts", {})["target_caption_hashtag_video_ids"] = len(candidates)
    report.setdefault("stage_counts", {})["excluded_caption_hashtag_video_ids"] = len(set(excluded_found or []))
    report["partial"] = bool(partial_rows)
    report["partial_reason"] = "failed_pages or not_collected videos present" if partial_rows else ""
    (processed_dir / "collection_report.json").write_text(
        json.dumps(redact_secrets(report), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# 锦江 Douyin top10 caption hashtag 全评论采集报告",
            "",
            f"- run: `{run_id}`",
            f"- source_run: `{source_processed_dir.name}`",
            "- collection: 基于 Caption hashtag 统计覆盖的视频，不是 4 个高评论候选视频。",
            "- metadata: 未重新跑 top10 metadata 全量采集；复用 source `videos.csv`。",
            "- comment scope: 一级评论 + 一级评论 replies。",
            "- profiles: 未抓 profiles。",
            "- excluded video IDs: " + ", ".join(f"`{video_id}`" for video_id in excluded),
            f"- target_video_count: `{len(candidates)}`",
            f"- top_level_comments_collected: `{len(top_level_comments)}`",
            f"- replies_collected: `{len(replies)}`",
            f"- all_comments_collected: `{len(all_comments)}`",
            f"- partial: `{str(bool(partial_rows)).lower()}`",
            "- secrets: 未打印凭据或请求认证头。",
            "",
            "## Caption hashtags",
            "",
        ]
        lines.extend(f"- `#{tag.lstrip('#')}`" for tag in caption_hashtags)
        lines.extend([
            "",
            "## Per-video status",
            "",
            "| video_id | source | matched_caption_hashtags | metadata_comment_count | comments | replies | all_comments | status | raw_comment_pages | raw_reply_pages | needs_more_comments | needs_more_replies |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | --- | --- |",
        ])
        for row in summary_rows:
            lines.append(
                "| {video_id} | {source_challenge_name} | {matched_caption_hashtags} | {metadata_comment_count} | {top_level_comments_collected} | {replies_collected} | {all_comments_collected} | {collection_status} | {raw_comment_pages} | {raw_reply_pages} | {needs_more_comments} | {needs_more_replies} |".format(**row)
            )
        lines.extend(["", "## Partial / blocker notes", ""])
        if partial_rows:
            lines.append(f"- incomplete_video_count: `{len(partial_rows)}`")
            for row in partial_rows[:200]:
                lines.append(
                    f"- `{row['video_id']}`: {row['collection_status']}; comment_failed_pages={row['comment_failed_pages']}; reply_failed_pages={row['reply_failed_pages']}"
                )
            if len(partial_rows) > 200:
                lines.append(f"- 其余 `{len(partial_rows) - 200}` 个 incomplete 视频见 `comment_video_summary.csv`。")
        else:
            lines.append("- No API/余额/限流/分页 blocker recorded in `failed_pages`.")
        lines.extend([
            "",
            "## Output files",
            "",
            f"- target_video_manifest: `{target_manifest_path}`",
            f"- comments (canonical combined): `{processed_dir / 'comments.csv'}`",
            f"- top_level_comments: `{processed_dir / 'top_level_comments.csv'}`",
            f"- replies: `{processed_dir / 'replies.csv'}`",
            f"- all_comments: `{processed_dir / 'all_comments.csv'}`",
            f"- summary: `{summary_path}`",
            f"- audit: `{processed_dir / 'comment_collection_audit.json'}`",
            f"- collection_report: `{processed_dir / 'collection_report.json'}`",
        ])
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_dict_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    if fieldnames is None:
        fieldnames = list(rows[0].keys()) if rows else []
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def load_page_journals(raw_dir: Path) -> list[dict[str, Any]]:
    journal_dir = raw_dir / "pages"
    if not journal_dir.exists():
        return []
    pages: list[dict[str, Any]] = []
    for path in sorted(journal_dir.glob("*.json")):
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(loaded, dict):
            pages.append(loaded)
    return pages


def write_candidate_comment_outputs(
    *,
    processed_dir: Path,
    raw_dir: Path,
    run_id: str,
    candidates: list[DouyinCommentCandidate],
    report_path: Path | None = None,
    excluded_video_ids: list[str] | None = None,
    exclusion_reason: str = "",
) -> None:
    comments = load_csv_rows(processed_dir / "comments.csv") if (processed_dir / "comments.csv").exists() else []
    report = json.loads((processed_dir / "collection_report.json").read_text(encoding="utf-8"))
    failed_pages = report.get("failed_pages", []) if isinstance(report.get("failed_pages"), list) else []
    comments_by_video: dict[str, int] = {}
    for row in comments:
        if row.get("comment_level") and row.get("comment_level") != "comment":
            continue
        video_id = row.get("video_id", "")
        comments_by_video[video_id] = comments_by_video.get(video_id, 0) + 1

    summary_rows: list[dict[str, Any]] = []
    for candidate in candidates:
        raw_pages = sorted((raw_dir / "pages").glob(f"comments_{candidate.video_id}_cursor_*.json"))
        failed_for_video = [item for item in failed_pages if f"comments:{candidate.video_id}" in str(item.get("page", ""))]
        count = comments_by_video.get(candidate.video_id, 0)
        capped = candidate.comment_fetch_limit is not None and count >= candidate.comment_fetch_limit
        failed = bool(failed_for_video)
        if failed:
            status = "partial" if count else "failed"
        elif candidate.comment_fetch_limit is not None and capped:
            status = "cap_reached"
        elif count >= candidate.metadata_comment_count and candidate.metadata_comment_count > 0:
            status = "complete"
        elif raw_pages:
            status = "complete_or_api_exhausted"
        else:
            status = "not_collected"
        needs_more = bool(failed)
        summary_rows.append(
            {
                "video_id": candidate.video_id,
                "source_challenge_name": candidate.source_challenge_name,
                "source_challenge_id": candidate.source_challenge_id,
                "metadata_comment_count": candidate.metadata_comment_count,
                "comment_fetch_limit": candidate.comment_fetch_limit if candidate.comment_fetch_limit is not None else "unbounded",
                "comments_collected": count,
                "collection_status": status,
                "failed_pages": json.dumps(failed_for_video, ensure_ascii=False),
                "raw_comment_pages": len(raw_pages),
                "needs_more_comments": str(needs_more).lower(),
                "exclusion_reason": candidate.exclusion_reason,
            }
        )

    summary_path = processed_dir / "comment_candidate_video_summary.csv"
    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "video_id",
            "source_challenge_name",
            "source_challenge_id",
            "metadata_comment_count",
            "comment_fetch_limit",
            "comments_collected",
            "collection_status",
            "failed_pages",
            "raw_comment_pages",
            "needs_more_comments",
            "exclusion_reason",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary_rows)

    excluded = excluded_video_ids or []
    audit = {
        "run_id": run_id,
        "collection_type": "filtered_candidate_comments",
        "first_level_comments_only": True,
        "replies_collected": False,
        "profiles_collected": False,
        "candidate_video_ids": [candidate.video_id for candidate in candidates],
        "excluded_video_ids": excluded,
        "exclusion_reason": exclusion_reason,
        "summary_rows": summary_rows,
        "failed_comment_pages": [item for item in failed_pages if "comments:" in str(item.get("page", ""))],
    }
    (processed_dir / "comment_collection_audit.json").write_text(
        json.dumps(redact_secrets(audit), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        total_comments = sum(int(row["comments_collected"] or 0) for row in summary_rows)
        lines = [
            "# 锦江 Douyin filtered candidate 一级评论采集报告",
            "",
            f"- run: `{run_id}`",
            "- collection: filtered candidate comments collection，不是全量 4552 视频评论采集。",
            "- comment scope: 只抓一级评论正文。",
            "- replies: 未抓 replies。",
            "- profiles: 未抓 profiles。",
            "- excluded: "
            + (", ".join(f"`{video_id}`" for video_id in excluded) if excluded else "none")
            + (f"；原因是{exclusion_reason}。" if excluded and exclusion_reason else "。"),
            "- capped videos: `7380282151763332403` 和 `7304930579651284264` 按 2000 cap。",
            "- unbounded videos: `7498610642853858569` 和 `7219508986515606839` 按全抓/自然分页结束。",
            f"- total first-level comments rows: `{total_comments}`",
            "",
            "## Per-video status",
            "",
            "| video_id | source | metadata_comment_count | comment_fetch_limit | comments_collected | status | raw_pages | needs_more |",
            "| --- | --- | ---: | --- | ---: | --- | ---: | --- |",
        ]
        for row in summary_rows:
            lines.append(
                "| {video_id} | {source_challenge_name} | {metadata_comment_count} | {comment_fetch_limit} | {comments_collected} | {collection_status} | {raw_comment_pages} | {needs_more_comments} |".format(**row)
            )
        partial = [row for row in summary_rows if row["collection_status"] in {"partial", "failed", "not_collected"}]
        lines.extend(["", "## Partial / blocker notes", ""])
        if partial:
            for row in partial:
                lines.append(f"- `{row['video_id']}`: {row['collection_status']}; failed_pages={row['failed_pages']}")
        else:
            lines.append("- No API/余额/限流/分页 blocker recorded in `failed_pages`.")
        lines.extend(["", "## Output files", "", f"- comments: `{processed_dir / 'comments.csv'}`", f"- summary: `{summary_path}`", f"- audit: `{processed_dir / 'comment_collection_audit.json'}`", f"- collection_report: `{processed_dir / 'collection_report.json'}`"])
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

def requires_selection_manifest(args: argparse.Namespace) -> bool:
    return (
        args.command == "collect-douyin-video-metadata"
        and str(args.collection_scope or "").startswith("jinjiang_top10_jinjiang_only")
    )


def analyze_douyin_video_scope(args: argparse.Namespace) -> int:
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
