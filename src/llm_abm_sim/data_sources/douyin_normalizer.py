from __future__ import annotations

import csv
import json
import math
import re
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .douyin_models import (
    COMMENT_COLUMNS,
    EDGE_COLUMNS,
    PROFILE_COLUMNS,
    REMOVED_DEMO_PRESET_FIELDS,
    TEXT_ITEM_COLUMNS,
    USER_COLUMNS,
    VIDEO_COLUMNS,
    DouyinCollectionReport,
    DouyinCommentRecord,
    DouyinProfileRecord,
    DouyinUserRecord,
    DouyinVideoRecord,
    FieldProvenance,
)
from .douyin_network import build_interaction_edges
from .tikhub_client import TikHubSettings, redact_secrets

TOPIC_TOKENS = ["锦江酒店", "锦江", "酒店", "旅行", "住宿"]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                rows.append(json.loads(stripped))
    return rows


def normalize_run(
    raw_dir: Path,
    processed_dir: Path,
    *,
    run_id: str,
    mode: str,
    settings: TikHubSettings,
    endpoint_call_counts: dict[str, int] | None = None,
    failed_pages: list[dict[str, Any]] | None = None,
    skipped_users: list[str] | None = None,
    selection_metadata: dict[str, Any] | None = None,
    include_comments: bool = True,
    include_replies: bool = True,
    include_profiles: bool = True,
    video_source_mode: str = "detail_only",
) -> DouyinCollectionReport:
    processed_dir.mkdir(parents=True, exist_ok=True)
    raw_details = load_jsonl(raw_dir / "video_details.jsonl")
    raw_challenge_posts = load_jsonl(raw_dir / "challenge_posts.jsonl")
    allowed_video_ids = selected_video_ids(selection_metadata)
    excluded_video_ids = terminal_unsuccessful_video_ids(raw_dir)
    raw_videos, video_source_counts = select_video_rows(
        raw_details,
        raw_challenge_posts,
        video_source_mode,
        allowed_video_ids=allowed_video_ids,
        excluded_video_ids=excluded_video_ids,
    )
    terminal_counts = terminal_status_counts(raw_dir)
    raw_comments = load_jsonl(raw_dir / "comments.jsonl") if include_comments else []
    raw_replies = load_jsonl(raw_dir / "comment_replies.jsonl") if include_comments and include_replies else []
    raw_profiles = load_jsonl(raw_dir / "user_profiles.jsonl") if include_profiles else []

    missing_fields: dict[str, list[str]] = defaultdict(list)
    videos = dedupe_videos([normalize_video(row, missing_fields) for row in raw_videos])
    comments = dedupe_comments(
        [normalize_comment(row, "comment", missing_fields) for row in raw_comments]
        + [normalize_comment(row, "reply", missing_fields) for row in raw_replies]
    )
    users = merge_users(videos, comments, [normalize_user(row, missing_fields) for row in raw_profiles])
    profiles = build_profiles(users, videos, comments) if include_profiles else []
    edges = build_interaction_edges(videos, comments)
    text_items = build_text_items(videos, comments)

    write_csv(processed_dir / "videos.csv", VIDEO_COLUMNS, [record.model_dump() for record in videos])
    write_csv(processed_dir / "comments.csv", COMMENT_COLUMNS, [_comment_row(record) for record in comments])
    write_csv(processed_dir / "text_items.csv", TEXT_ITEM_COLUMNS, text_items)
    write_csv(processed_dir / "users.csv", USER_COLUMNS, [record.model_dump() for record in users])
    write_csv(processed_dir / "edges.csv", EDGE_COLUMNS, [record.model_dump() for record in edges])
    write_csv(processed_dir / "profiles.csv", PROFILE_COLUMNS, [_profile_row(record) for record in profiles])

    report = DouyinCollectionReport(
        run_id=run_id,
        mode="live" if mode == "live" else "mock",
        counts={
            "videos": len(videos),
            "comments": len([c for c in comments if c.comment_level == "comment"]),
            "replies": len([c for c in comments if c.comment_level == "reply"]),
            "users": len(users),
            "edges": len(edges),
            "profiles": len(profiles),
            "text_items": len(text_items),
        },
        limits={
            "max_videos": settings.max_videos,
            "max_comments_per_video": settings.max_comments_per_video,
            "max_replies_per_comment": settings.max_replies_per_comment,
            "max_users": settings.max_users,
            "max_search_pages": settings.max_search_pages,
        },
        limit_profile="unbounded" if settings.business_limits_unbounded() else "capped",
        selection_metadata=redact_secrets(selection_metadata or {}, [settings.api_key]),
        endpoint_call_counts=endpoint_call_counts or {},
        missing_fields=dict(missing_fields),
        failed_pages=redact_secrets(failed_pages or [], [settings.api_key]),
        skipped_users=sorted(set(skipped_users or [])),
        dedupe_counts={
            "raw_videos": len(raw_videos),
            "deduped_videos": len(videos),
            "raw_video_details": len(raw_details),
            "raw_challenge_posts": len(raw_challenge_posts),
            "raw_comments_and_replies": len(raw_comments) + len(raw_replies),
            "deduped_comments_and_replies": len(comments),
        },
        live_fetch=settings.live_fetch,
        redacted_config=settings.redacted(),
        stage_counts=build_stage_counts(
            selection_metadata,
            videos=videos,
            comments=comments,
            video_source_counts=video_source_counts,
            terminal_counts=terminal_counts,
            raw_details=raw_details,
        ),
        stage_status=(selection_metadata or {}).get("stage_status", {}) if isinstance(selection_metadata, dict) else {},
        comments_collected=include_comments,
        profiles_collected=include_profiles,
        video_source_mode=video_source_mode,
        field_provenance={
            "videos": FieldProvenance(
                observed=[
                    "video_id",
                    "source_challenge_id",
                    "source_challenge_name",
                    "caption",
                    "creator_user_id",
                    "counts",
                ],
                derived=["hashtags", "video_url", "raw_detail_status", "metadata_source"],
                defaulted=[],
            ),
            "profiles": FieldProvenance(
                observed=["follower_count", "video_count"],
                derived=["activity_score", "global_influence_score", "local_influence_score", "interest_tags"],
                defaulted=[],
            ),
        },
        processed_profile_contract={
            "removed_demo_preset_fields": REMOVED_DEMO_PRESET_FIELDS,
            "raw_private_data_overwritten": False,
        },
    )
    (processed_dir / "collection_report.json").write_text(
        json.dumps(redact_secrets(report.model_dump(mode="json"), [settings.api_key]), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def build_stage_counts(
    selection_metadata: dict[str, Any] | None,
    *,
    videos: list[DouyinVideoRecord],
    comments: list[DouyinCommentRecord],
    video_source_counts: dict[str, int],
    terminal_counts: dict[str, int],
    raw_details: list[dict[str, Any]],
) -> dict[str, int]:
    base: dict[str, int] = {}
    if isinstance(selection_metadata, dict) and isinstance(selection_metadata.get("stage_counts"), dict):
        base.update({str(key): int(value) for key, value in selection_metadata["stage_counts"].items() if isinstance(value, int)})
    detail_rows = video_source_counts.get("detail", 0)
    base["video_detail_succeeded"] = max(base.get("video_detail_succeeded", 0), detail_rows)
    base["video_detail_skipped_out_of_window"] = max(
        base.get("video_detail_skipped_out_of_window", 0), terminal_counts.get("skipped_out_of_window", 0)
    )
    base["video_detail_failed"] = max(base.get("video_detail_failed", 0), terminal_counts.get("failed_detail", 0))
    promoted = len([row for row in raw_details if unwrap(row).get("_metadata_source") == "challenge_page"])
    base["video_metadata_promoted_from_challenge"] = max(base.get("video_metadata_promoted_from_challenge", 0), promoted)
    base.update(
        {
            "videos_with_caption": len([video for video in videos if video.caption.strip()]),
            "videos_with_hashtags": len([video for video in videos if video.hashtags]),
            "comments_video_ids_without_video_metadata": len({comment.video_id for comment in comments} - {video.video_id for video in videos}),
            "video_rows_from_detail": detail_rows,
            "video_rows_from_challenge": video_source_counts.get("challenge", 0),
        }
    )
    return base


def select_video_rows(
    raw_details: list[dict[str, Any]],
    raw_challenge_posts: list[dict[str, Any]],
    video_source_mode: str,
    *,
    allowed_video_ids: set[str] | None = None,
    excluded_video_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    excluded_video_ids = excluded_video_ids or set()
    if video_source_mode == "challenge_only":
        rows = [
            row
            for row in raw_challenge_posts
            if has_normalizable_video_metadata(row) and is_allowed_video_row(row, allowed_video_ids, excluded_video_ids)
        ]
        return rows, {"detail": 0, "challenge": len(rows)}
    if video_source_mode == "merged_detail_preferred":
        by_id: dict[str, tuple[str, dict[str, Any]]] = {}
        for row in raw_challenge_posts:
            if not has_normalizable_video_metadata(row) or not is_allowed_video_row(row, allowed_video_ids, excluded_video_ids):
                continue
            key = video_row_id(row)
            if key:
                by_id[key] = ("challenge", row)
        for row in raw_details:
            if not is_allowed_video_row(row, allowed_video_ids, set()):
                continue
            key = video_row_id(row)
            if key:
                by_id[key] = ("detail", row)
        counts = {"detail": 0, "challenge": 0}
        rows = []
        for _key, (source, row) in sorted(by_id.items()):
            counts[source] += 1
            rows.append(row)
        return rows, counts
    rows = [row for row in raw_details if is_allowed_video_row(row, allowed_video_ids, set())]
    return rows, {"detail": len(rows), "challenge": 0}


def selected_video_ids(selection_metadata: dict[str, Any] | None) -> set[str] | None:
    if not isinstance(selection_metadata, dict):
        return None
    values = selection_metadata.get("selected_video_ids")
    if not isinstance(values, list):
        return None
    ids = {str(value) for value in values if str(value)}
    return ids or None


def terminal_unsuccessful_video_ids(raw_dir: Path) -> set[str]:
    ids, _counts = terminal_status_summary(raw_dir)
    return ids


def terminal_status_counts(raw_dir: Path) -> dict[str, int]:
    _ids, counts = terminal_status_summary(raw_dir)
    return counts


def terminal_status_summary(raw_dir: Path) -> tuple[set[str], dict[str, int]]:
    journal_dir = raw_dir / "pages"
    if not journal_dir.exists():
        return set(), {}
    ids: set[str] = set()
    counts: dict[str, int] = {}
    for path in journal_dir.glob("video_metadata_status_*.json"):
        try:
            page = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(page, dict):
            continue
        for item in page.get("items", []):
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "")
            video_id = str(item.get("video_id") or "")
            if video_id and status in {"failed_detail", "skipped_out_of_window"}:
                ids.add(video_id)
                counts[status] = counts.get(status, 0) + 1
    return ids, counts


def is_allowed_video_row(row: dict[str, Any], allowed_video_ids: set[str] | None, excluded_video_ids: set[str]) -> bool:
    video_id = video_row_id(row)
    if not video_id or video_id in excluded_video_ids:
        return False
    return allowed_video_ids is None or video_id in allowed_video_ids


def video_row_id(row: dict[str, Any]) -> str:
    data = unwrap(row)
    return first_str(data, "video_id", "aweme_id", "id")


def has_normalizable_video_metadata(row: dict[str, Any]) -> bool:
    data = unwrap(row)
    return any(
        key in data and data.get(key) not in (None, "", [], {})
        for key in ("caption", "desc", "title", "author", "creator", "user", "statistics", "stats", "share_url", "video_url", "cha_list", "hashtags", "text_extra")
    )


def normalize_video(row: dict[str, Any], missing_fields: dict[str, list[str]]) -> DouyinVideoRecord:
    data = unwrap(row)
    video_id = first_str(data, "video_id", "aweme_id", "id")
    if not video_id:
        missing_fields["video"].append("video_id")
        video_id = f"missing-video-{abs(hash(json.dumps(data, sort_keys=True, default=str)))}"
    author = first_dict(data, "author", "creator", "user")
    stats = first_dict(data, "statistics", "stats")
    metadata_source = first_str(data, "_metadata_source", "metadata_source")
    return DouyinVideoRecord(
        video_id=video_id,
        source_challenge_id=first_str(data, "source_challenge_id", "_source_challenge_id"),
        source_challenge_name=first_str(data, "source_challenge_name", "_source_challenge_name"),
        source_challenge_rank=first_int(data, "source_challenge_rank", "_source_challenge_rank"),
        raw_detail_status="detail" if metadata_source == "app_v3_detail" else "promoted_from_challenge" if metadata_source == "challenge_page" else "unknown",
        metadata_source=metadata_source,
        video_url=first_str(data, "video_url", "share_url", "url"),
        publish_time=str(first_any(data, "publish_time", "create_time", "createTime", default="")),
        caption=first_str(data, "caption", "desc", "title"),
        hashtags=extract_hashtags(data),
        creator_user_id=first_str(data, "creator_user_id", "author_user_id") or first_str(author, "user_id", "uid", "id"),
        like_count=first_int(data, "like_count", "digg_count") or first_int(stats, "like_count", "digg_count"),
        comment_count=first_int(data, "comment_count") or first_int(stats, "comment_count"),
        share_count=first_int(data, "share_count") or first_int(stats, "share_count"),
        collect_count=first_int(data, "collect_count", "收藏") or first_int(stats, "collect_count"),
    )


def normalize_comment(row: dict[str, Any], level: str, missing_fields: dict[str, list[str]]) -> DouyinCommentRecord:
    data = unwrap(row)
    user = first_dict(data, "user", "commenter", "author")
    comment_id = first_str(data, "comment_id", "cid", "id")
    if not comment_id:
        missing_fields["comment"].append("comment_id")
        comment_id = f"missing-comment-{abs(hash(json.dumps(data, sort_keys=True, default=str)))}"
    comment_level = "reply" if level == "reply" or first_str(data, "parent_comment_id", "reply_comment_id") else "comment"
    parent = first_str(data, "parent_comment_id", "reply_comment_id", "reply_id")
    return DouyinCommentRecord(
        comment_id=comment_id,
        video_id=first_str(data, "video_id", "aweme_id"),
        parent_comment_id=parent,
        commenter_user_id=first_str(data, "commenter_user_id", "user_id") or first_str(user, "user_id", "uid", "id"),
        content=first_str(data, "content", "text", "comment_text"),
        publish_time=str(first_any(data, "publish_time", "create_time", "createTime", default="")),
        mentioned_user_ids=extract_mentions(data),
        like_count=first_int(data, "like_count", "digg_count"),
        comment_level=comment_level,  # type: ignore[arg-type]
    )


def normalize_user(row: dict[str, Any], missing_fields: dict[str, list[str]]) -> DouyinUserRecord:
    data = unwrap(row)
    user = first_dict(data, "user", "profile") or data
    user_id = first_str(user, "user_id", "uid", "id")
    if not user_id:
        missing_fields["user"].append("user_id")
        user_id = first_str(user, "sec_user_id", "sec_uid") or "unknown-user"
    follower_count = first_int(user, "follower_count", "followers")
    video_count = first_int(user, "video_count", "aweme_count")
    return DouyinUserRecord(
        user_id=user_id,
        sec_user_id=first_str(user, "sec_user_id", "sec_uid"),
        nickname=first_str(user, "nickname", "name"),
        follower_count=follower_count,
        following_count=first_int(user, "following_count", "follow_count"),
        video_count=video_count,
        verified_type=str(first_any(user, "verified_type", "verification_type", default="")),
        bio=first_str(user, "bio", "signature", "desc"),
        activity_score=bounded_ratio(video_count, 100),
        activity_video_score=bounded_ratio(video_count, 100),
        global_influence_score=bounded_log_ratio(follower_count),
    )


def merge_users(
    videos: list[DouyinVideoRecord], comments: list[DouyinCommentRecord], profile_users: list[DouyinUserRecord]
) -> list[DouyinUserRecord]:
    by_id: dict[str, DouyinUserRecord] = {user.user_id: user for user in profile_users if user.user_id}
    for video in videos:
        if video.creator_user_id and video.creator_user_id not in by_id:
            by_id[video.creator_user_id] = DouyinUserRecord(user_id=video.creator_user_id)
    for comment in comments:
        if comment.commenter_user_id and comment.commenter_user_id not in by_id:
            by_id[comment.commenter_user_id] = DouyinUserRecord(user_id=comment.commenter_user_id)
        for mentioned in comment.mentioned_user_ids:
            if mentioned and mentioned not in by_id:
                by_id[mentioned] = DouyinUserRecord(user_id=mentioned)
    return [by_id[key] for key in sorted(by_id)]


def build_profiles(
    users: list[DouyinUserRecord], videos: list[DouyinVideoRecord], comments: list[DouyinCommentRecord]
) -> list[DouyinProfileRecord]:
    tags_by_user: dict[str, set[str]] = defaultdict(set)
    comment_counts: dict[str, int] = defaultdict(int)
    creators = {video.creator_user_id for video in videos if video.creator_user_id}
    for video in videos:
        tags_by_user[video.creator_user_id].update(video.hashtags)
        for token in TOPIC_TOKENS:
            if token and token in video.caption:
                tags_by_user[video.creator_user_id].add(token)
    for comment in comments:
        comment_counts[comment.commenter_user_id] += 1
        for token in TOPIC_TOKENS:
            if token and token in comment.content:
                tags_by_user[comment.commenter_user_id].add(token)
    profiles: list[DouyinProfileRecord] = []
    for user in users:
        activity_comment_score = bounded_ratio(comment_counts[user.user_id], 20)
        activity = max(user.activity_score, activity_comment_score)
        profiles.append(
            DouyinProfileRecord(
                user_id=user.user_id,
                user_type="creator" if user.user_id in creators else "observed",
                follower_count=user.follower_count,
                value_proposition="",
                interest_tags=sorted(tag for tag in tags_by_user[user.user_id] if tag),
                activity_score=activity,
                activity_video_score=user.activity_video_score,
                activity_publish_score=user.activity_video_score,
                activity_comment_score=activity_comment_score,
                global_influence_score=user.global_influence_score,
            )
        )
    return profiles


def build_text_items(videos: list[DouyinVideoRecord], comments: list[DouyinCommentRecord]) -> list[dict[str, Any]]:
    """Build a text-only research view without storing video media.

    Rows intentionally retain only minimal provenance identifiers plus text
    fields needed for downstream social-network and ABM preparation. Mention
    rows are separate interaction pointers derived from the same comment text.
    """
    creators = {video.video_id: video.creator_user_id for video in videos if video.creator_user_id}
    comments_by_id = {comment.comment_id: comment for comment in comments}
    rows: list[dict[str, Any]] = []

    for video in videos:
        if video.caption:
            rows.append(
                {
                    "item_id": f"video:{video.video_id}",
                    "item_type": "video_caption",
                    "video_id": video.video_id,
                    "parent_comment_id": "",
                    "user_id": video.creator_user_id,
                    "target_user_id": "",
                    "text": video.caption,
                    "publish_time": video.publish_time,
                    "like_count": video.like_count,
                    "source": "videos.csv",
                }
            )

    for comment in comments:
        if comment.comment_level == "reply":
            parent = comments_by_id.get(comment.parent_comment_id)
            target_user_id = parent.commenter_user_id if parent else ""
            item_type = "reply"
        else:
            target_user_id = creators.get(comment.video_id, "")
            item_type = "comment"
        rows.append(
            {
                "item_id": comment.comment_id,
                "item_type": item_type,
                "video_id": comment.video_id,
                "parent_comment_id": comment.parent_comment_id,
                "user_id": comment.commenter_user_id,
                "target_user_id": target_user_id,
                "text": comment.content,
                "publish_time": comment.publish_time,
                "like_count": comment.like_count,
                "source": "comments.csv",
            }
        )
        for mentioned_user_id in comment.mentioned_user_ids:
            rows.append(
                {
                    "item_id": f"{comment.comment_id}:mention:{mentioned_user_id}",
                    "item_type": "mention",
                    "video_id": comment.video_id,
                    "parent_comment_id": comment.parent_comment_id,
                    "user_id": comment.commenter_user_id,
                    "target_user_id": mentioned_user_id,
                    "text": comment.content,
                    "publish_time": comment.publish_time,
                    "like_count": comment.like_count,
                    "source": "comments.csv",
                }
            )
    return rows


def dedupe_videos(records: Iterable[DouyinVideoRecord]) -> list[DouyinVideoRecord]:
    by_id = {record.video_id: record for record in records}
    return [by_id[key] for key in sorted(by_id)]


def dedupe_comments(records: Iterable[DouyinCommentRecord]) -> list[DouyinCommentRecord]:
    by_id = {record.comment_id: record for record in records}
    return [by_id[key] for key in sorted(by_id)]


def write_csv(path: Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: serialize_cell(row.get(column, "")) for column in columns})


def _comment_row(record: DouyinCommentRecord) -> dict[str, Any]:
    row = record.model_dump()
    row["mentioned_user_ids"] = record.mentioned_user_ids
    return row


def _profile_row(record: DouyinProfileRecord) -> dict[str, Any]:
    row = record.model_dump()
    row["interest_tags"] = record.interest_tags
    return row


def serialize_cell(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def unwrap(row: dict[str, Any]) -> dict[str, Any]:
    current = row
    carried = {key: value for key, value in row.items() if key in {"video_id", "aweme_id", "parent_comment_id"}}
    for _ in range(4):
        for key in ("aweme_detail", "aweme", "comment", "reply", "data"):
            value = current.get(key)
            if isinstance(value, dict):
                merged = dict(value)
                for parent_key, parent_value in carried.items():
                    merged.setdefault(parent_key, parent_value)
                current = merged
                break
        else:
            return current
    return current


def first_any(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return default


def first_str(data: dict[str, Any], *keys: str) -> str:
    value = ""
    for key in keys:
        if key in data and data[key] not in (None, ""):
            value = data[key]
            break
    return "" if value is None else str(value)


def first_int(data: dict[str, Any], *keys: str) -> int:
    value = first_any(data, *keys, default=0)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def first_dict(data: dict[str, Any], *keys: str) -> dict[str, Any]:
    value = first_any(data, *keys, default={})
    return value if isinstance(value, dict) else {}


def extract_hashtags(data: dict[str, Any]) -> list[str]:
    raw = first_any(data, "hashtags", "cha_list", "text_extra", default=[])
    tags: list[str] = []
    if isinstance(raw, str):
        tags.extend(part.strip(" #") for part in re.split(r"[,，|;；]", raw) if part.strip(" #"))
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                tags.append(item.strip(" #"))
            elif isinstance(item, dict):
                tag = first_str(item, "hashtag_name", "cha_name", "name", "tag")
                if tag:
                    tags.append(tag.strip(" #"))
    caption = first_str(data, "caption", "desc", "title")
    tags.extend(match.strip() for match in re.findall(r"#([^#\s]+)", caption))
    return sorted(set(tag for tag in tags if tag))


def extract_mentions(data: dict[str, Any]) -> list[str]:
    raw = first_any(data, "mentioned_user_ids", "mentions", "text_extra", default=[])
    mentions: list[str] = []
    if isinstance(raw, str):
        mentions.extend(part.strip() for part in re.split(r"[,，|;；]", raw) if part.strip())
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                mentions.append(item.strip())
            elif isinstance(item, dict):
                user_id = first_str(item, "user_id", "uid", "id", "sec_uid")
                if user_id:
                    mentions.append(user_id)
    return sorted(set(item for item in mentions if item))


def bounded_ratio(value: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return max(0.0, min(1.0, value / denominator))


def bounded_log_ratio(value: int) -> float:
    if value <= 0:
        return 0.0
    return max(0.0, min(1.0, math.log10(value + 1) / 7.0))
