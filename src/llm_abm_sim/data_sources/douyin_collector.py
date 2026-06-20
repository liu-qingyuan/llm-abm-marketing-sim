from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Protocol, TypeVar

from .douyin_normalizer import normalize_run
from .tikhub_client import TikHubClientError, TikHubSettings, redact_secrets

RAW_FILES = {
    "topic_query": "topic_query.jsonl",
    "challenge_posts": "challenge_posts.jsonl",
    "video_details": "video_details.jsonl",
    "comments": "comments.jsonl",
    "comment_replies": "comment_replies.jsonl",
    "user_profiles": "user_profiles.jsonl",
}

STAGE_CHALLENGE_INDEX = "challenge_index"
STAGE_VIDEO_METADATA = "video_metadata"
STAGE_COMMENTS = "comments"
STAGE_REPLIES = "replies"
STAGE_PROFILES = "profiles"
FULL_COLLECT_STAGES = (
    STAGE_CHALLENGE_INDEX,
    STAGE_VIDEO_METADATA,
    STAGE_COMMENTS,
    STAGE_REPLIES,
    STAGE_PROFILES,
)
METADATA_ONLY_STAGES = (STAGE_CHALLENGE_INDEX, STAGE_VIDEO_METADATA)
VALID_COLLECT_STAGES = frozenset(FULL_COLLECT_STAGES)


class DouyinClientProtocol(Protocol):
    settings: TikHubSettings
    endpoint_call_counts: dict[str, int]

    def fetch_topic_query(self, **payload: Any) -> Any: ...

    def fetch_challenge_posts(self, **payload: Any) -> Any: ...

    def fetch_video_search_v2(self, **payload: Any) -> Any: ...

    def fetch_general_search_v2(self, **payload: Any) -> Any: ...

    def fetch_challenge_search_v2(self, **payload: Any) -> Any: ...

    def fetch_video_search(self, **payload: Any) -> Any: ...

    def fetch_one_video(self, **params: Any) -> Any: ...

    def fetch_hashtag_video_list(self, **params: Any) -> Any: ...

    def fetch_video_comments(self, **params: Any) -> Any: ...

    def fetch_video_comment_replies(self, **params: Any) -> Any: ...

    def handler_user_profile(self, sec_user_id: str) -> Any: ...


@dataclass(frozen=True)
class DouyinChallengeSelection:
    rank: int
    name: str
    challenge_id: str
    source: str = ""
    include: bool = True
    include_reason: str = ""
    exclude_reason: str = ""
    is_generic: bool = False


@dataclass(frozen=True)
class DouyinCommentCandidate:
    video_id: str
    source_challenge_name: str = ""
    source_challenge_id: str = ""
    metadata_comment_count: int = 0
    comment_fetch_limit: int | None = None
    caption_hashtags: str = ""
    exclusion_reason: str = ""


@dataclass(frozen=True)
class DouyinCollectRequest:
    hashtag: str = "锦江酒店"
    start_date: str | None = None
    end_date: str | None = None
    run_id: str | None = None
    output_root: Path = Path(".")
    resume: bool = False
    mode: str = "mock"
    challenge_id: str | None = None
    challenge_selections: Sequence[DouyinChallengeSelection] | None = None
    selection_source: str = ""
    collection_scope: str = "single_hashtag"
    stages: Sequence[str] = FULL_COLLECT_STAGES
    comment_candidates: Sequence[DouyinCommentCandidate] | None = None
    source_video_rows: Sequence[dict[str, Any]] | None = None

    def enabled_stages(self) -> set[str]:
        stages = {str(stage).strip() for stage in self.stages if str(stage).strip()}
        unknown = stages - VALID_COLLECT_STAGES
        if unknown:
            raise ValueError(f"Unknown Douyin collection stage(s): {sorted(unknown)}")
        if STAGE_REPLIES in stages and STAGE_COMMENTS not in stages:
            raise ValueError("Douyin replies stage requires comments stage")
        if STAGE_VIDEO_METADATA in stages and STAGE_CHALLENGE_INDEX not in stages:
            raise ValueError("Douyin video_metadata stage requires challenge_index stage")
        if self.comment_candidates and stages - {STAGE_COMMENTS, STAGE_REPLIES}:
            raise ValueError("Douyin comment candidate runs support only comments/replies stages")
        return stages


class DouyinCollector:
    def __init__(self, client: DouyinClientProtocol, settings: TikHubSettings | None = None) -> None:
        self.client = client
        self.settings = settings or client.settings
        self.failed_pages: list[dict[str, Any]] = []
        self.skipped_users: list[str] = []
        self.quota_blocked = False

    def collect(self, request: DouyinCollectRequest) -> dict[str, Path]:
        run_id = request.run_id or make_run_id()
        raw_dir = request.output_root / "data" / "raw" / "tikhub" / "douyin" / "jinjiang_hotel" / run_id
        processed_dir = request.output_root / "data" / "processed" / "jinjiang_douyin" / run_id
        if not request.resume:
            self._ensure_fresh_run(raw_dir, processed_dir)
        raw_dir.mkdir(parents=True, exist_ok=True)
        checkpoint = self._load_checkpoint(raw_dir) if request.resume else {"completed": {}}
        if request.resume:
            self._restore_checkpoint_from_page_journals(raw_dir, checkpoint)
        self._write_manifest(raw_dir, run_id, request)
        if request.resume:
            self._rebuild_raw_jsonl_from_pages(raw_dir)

        stages = request.enabled_stages()
        stage_counts: dict[str, int] = {
            "indexed_video_refs": 0,
            "indexed_video_ids": 0,
            "selected_video_ids": 0,
            "video_detail_attempted": 0,
            "video_detail_succeeded": 0,
            "video_detail_failed": 0,
            "video_detail_skipped_out_of_window": 0,
            "video_metadata_promoted_from_challenge": 0,
        }

        video_refs: list[dict[str, Any]] = []
        if request.comment_candidates:
            video_refs = self._prepare_comment_candidate_video_refs(raw_dir, checkpoint, request)
            if STAGE_COMMENTS in stages:
                for candidate in request.comment_candidates:
                    if self.quota_blocked:
                        break
                    if candidate.metadata_comment_count == 0:
                        self._mark_complete(raw_dir, checkpoint, f"comments_zero_metadata:{candidate.video_id}")
                        continue
                    comments = self._collect_comments(raw_dir, checkpoint, candidate.video_id, limit=candidate.comment_fetch_limit)
                    if STAGE_REPLIES not in stages:
                        continue
                    for comment in comments:
                        if self.quota_blocked:
                            break
                        if comment_has_zero_replies(comment):
                            continue
                        comment_id = str(comment.get("comment_id") or comment.get("cid") or comment.get("id") or "")
                        if not comment_id:
                            continue
                        self._collect_replies(raw_dir, checkpoint, candidate.video_id, comment_id)
        if STAGE_CHALLENGE_INDEX in stages:
            video_refs = self._collect_challenge_video_refs(raw_dir, checkpoint, request)
            if not video_refs:
                video_refs = self._collect_search_v2_refs(raw_dir, checkpoint, request)
            if not video_refs:
                video_refs = self._collect_legacy_refs(raw_dir, checkpoint, request)
            self._rebuild_raw_jsonl_from_pages(raw_dir)
        if not video_refs:
            video_refs = read_jsonl(raw_dir / RAW_FILES["challenge_posts"])
        stage_counts["indexed_video_refs"] = len(video_refs)
        stage_counts["indexed_video_ids"] = len({video_ref_id(item) for item in video_refs if video_ref_id(item)})
        video_refs = dedupe_by_id(video_refs, self.settings.max_videos)
        stage_counts["selected_video_ids"] = len({video_ref_id(item) for item in video_refs if video_ref_id(item)})

        if STAGE_VIDEO_METADATA in stages:
            for item in video_refs:
                if self.quota_blocked:
                    break
                video_id = str(item.get("video_id") or item.get("aweme_id") or item.get("id") or "")
                if not video_id:
                    continue
                detail_ready = self._collect_video_metadata(raw_dir, checkpoint, request, item, video_id, stage_counts)
                if not detail_ready or STAGE_COMMENTS not in stages:
                    continue

                comments = self._collect_comments(raw_dir, checkpoint, video_id)
                if STAGE_REPLIES not in stages:
                    continue
                for comment in comments:
                    if comment_has_zero_replies(comment):
                        continue
                    comment_id = str(comment.get("comment_id") or comment.get("cid") or comment.get("id") or "")
                    if not comment_id:
                        continue
                    self._collect_replies(raw_dir, checkpoint, video_id, comment_id)

        self._rebuild_raw_jsonl_from_pages(raw_dir)
        if STAGE_PROFILES in stages:
            users = limit_items(extract_sec_user_ids(raw_dir), self.settings.max_users)
            self._collect_profiles(raw_dir, checkpoint, users)
            self._rebuild_raw_jsonl_from_pages(raw_dir)
        normalize_run(
            raw_dir,
            processed_dir,
            run_id=run_id,
            mode=request.mode,
            settings=self.settings,
            endpoint_call_counts=self.client.endpoint_call_counts,
            failed_pages=self.failed_pages,
            skipped_users=self.skipped_users,
            selection_metadata=self._selection_metadata(
                request,
                stages=stages,
                stage_counts=stage_counts,
                selected_video_ids=sorted({video_ref_id(item) for item in video_refs if video_ref_id(item)}),
            ),
            include_comments=STAGE_COMMENTS in stages,
            include_replies=STAGE_REPLIES in stages,
            include_profiles=STAGE_PROFILES in stages,
            video_source_mode=(
                "detail_only"
                if request.comment_candidates
                else "merged_detail_preferred"
                if STAGE_VIDEO_METADATA in stages
                else "challenge_only"
            ),
        )
        self._save_checkpoint(raw_dir, checkpoint)
        return {"raw_dir": raw_dir, "processed_dir": processed_dir, "report": processed_dir / "collection_report.json"}

    def _collect_video_metadata(
        self,
        raw_dir: Path,
        checkpoint: dict[str, Any],
        request: DouyinCollectRequest,
        item: dict[str, Any],
        video_id: str,
        stage_counts: dict[str, int],
    ) -> bool:
        detail_key = f"video_detail:{video_id}"
        detail_rows = read_page_items(raw_dir, detail_key)
        if not detail_rows and self._is_complete(checkpoint, detail_key):
            # Older runs may have complete detail checkpoints without detail
            # journals. Treat them as terminal skips for resume compatibility,
            # but new terminal skips write an auditable status journal.
            return False

        if detail_rows:
            return True

        if has_parseable_video_date(item) and not is_within_date_window(item, request.start_date, request.end_date):
            stage_counts["video_detail_skipped_out_of_window"] += 1
            self._commit_status(raw_dir, checkpoint, detail_key, video_id, "skipped_out_of_window", item)
            return False

        if has_usable_video_detail(item):
            detail = ensure_video_id(item, video_id)
            detail.setdefault("_metadata_source", "challenge_page")
            stage_counts["video_metadata_promoted_from_challenge"] += 1
        else:
            stage_counts["video_detail_attempted"] += 1
            before_failures = len(self.failed_pages)
            detail_result = self._safe_call(
                detail_key,
                lambda video_id=video_id: self.client.fetch_one_video(aweme_id=video_id),
            )
            if detail_result is None:
                stage_counts["video_detail_failed"] += max(1, len(self.failed_pages) - before_failures)
                self._commit_status(raw_dir, checkpoint, detail_key, video_id, "failed_detail", item)
                return False
            detail = ensure_video_id(detail_result, video_id)
            detail.setdefault("_metadata_source", "app_v3_detail")

        if not is_within_date_window(detail, request.start_date, request.end_date):
            stage_counts["video_detail_skipped_out_of_window"] += 1
            self._commit_status(raw_dir, checkpoint, detail_key, video_id, "skipped_out_of_window", detail)
            return False
        self._commit_page(raw_dir, checkpoint, detail_key, "video_details", [detail])
        stage_counts["video_detail_succeeded"] += 1
        return True


    def _collect_challenge_video_refs(
        self, raw_dir: Path, checkpoint: dict[str, Any], request: DouyinCollectRequest
    ) -> list[dict[str, Any]]:
        selections = self._resolve_challenge_selections(raw_dir, checkpoint, request)
        all_refs: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for selection in selections:
            if not selection.include:
                continue
            if self.quota_blocked:
                break
            for item in self._collect_single_challenge_video_refs(raw_dir, checkpoint, selection):
                ref_id = video_ref_id(item)
                if ref_id and ref_id not in seen_ids:
                    seen_ids.add(ref_id)
                    all_refs.append(item)
                    if self._limit_reached(all_refs, self.settings.max_videos):
                        return all_refs
        return all_refs

    def _collect_single_challenge_video_refs(
        self, raw_dir: Path, checkpoint: dict[str, Any], selection: DouyinChallengeSelection
    ) -> list[dict[str, Any]]:
        all_refs: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        cursor = 0
        for _page_number in self._page_numbers():
            if self.quota_blocked:
                break
            page_key = f"hashtag_video_list:{selection.challenge_id}:cursor:{cursor}"
            result: Any | None = None
            if self._is_complete(checkpoint, page_key):
                page_refs = read_page_items(raw_dir, page_key)
            else:
                result = self._safe_call(
                    page_key,
                    lambda challenge_id=selection.challenge_id, cursor=cursor: self.client.fetch_hashtag_video_list(
                        ch_id=challenge_id, cursor=cursor, sort_type=0
                    ),
                )
                if result is None:
                    break
                page_refs = extract_video_items(result)
                self._commit_page(raw_dir, checkpoint, page_key, "challenge_posts", page_refs)
            for item in page_refs:
                ref_id = video_ref_id(item)
                if ref_id and ref_id not in seen_ids:
                    seen_ids.add(ref_id)
                    enriched = dict(item)
                    enriched.setdefault("source_challenge_id", selection.challenge_id)
                    enriched.setdefault("source_challenge_name", selection.name)
                    enriched.setdefault("source_challenge_rank", selection.rank)
                    all_refs.append(enriched)
            if self._limit_reached(all_refs, self.settings.max_videos):
                return all_refs
            more = has_more(result) if result is not None else self._cached_page_may_have_next(page_refs)
            if not more:
                break
            next_cursor = extract_next_cursor(result, fallback=cursor + self.settings.search_page_size) if result is not None else cursor + self.settings.search_page_size
            if next_cursor == cursor:
                next_cursor += self.settings.search_page_size
            cursor = next_cursor
        return all_refs

    def _resolve_challenge_selections(
        self, raw_dir: Path, checkpoint: dict[str, Any], request: DouyinCollectRequest
    ) -> list[DouyinChallengeSelection]:
        if request.challenge_selections:
            return list(request.challenge_selections)
        if request.challenge_id:
            return [DouyinChallengeSelection(rank=1, name=request.hashtag, challenge_id=request.challenge_id, source="request.challenge_id")]
        challenge_id = self._find_challenge_id(raw_dir, checkpoint, request)
        if not challenge_id:
            return []
        return [DouyinChallengeSelection(rank=1, name=request.hashtag, challenge_id=challenge_id, source="challenge_search_v2")]

    def _find_challenge_id(self, raw_dir: Path, checkpoint: dict[str, Any], request: DouyinCollectRequest) -> str | None:
        page_key = "challenge_search_v2:cursor:0"
        if self._is_complete(checkpoint, page_key):
            rows = read_page_items(raw_dir, page_key)
            found = extract_challenge_id({"items": rows, "keyword": request.hashtag})
            if found:
                return found
        payload = build_challenge_search_payload(request, cursor=0)
        result = self._safe_call(page_key, lambda payload=payload: self.client.fetch_challenge_search_v2(**payload))
        if result is None:
            return None
        challenge_rows = extract_challenge_items(result)
        self._commit_page(raw_dir, checkpoint, page_key, "topic_query", challenge_rows or [result])
        return select_challenge_id(challenge_rows, request.hashtag) or extract_challenge_id(result)

    def _collect_search_v2_refs(
        self, raw_dir: Path, checkpoint: dict[str, Any], request: DouyinCollectRequest
    ) -> list[dict[str, Any]]:
        search_steps = [
            ("video_search_v2", self.client.fetch_video_search_v2),
            ("general_search_v2", self.client.fetch_general_search_v2),
            ("challenge_search_v2", self.client.fetch_challenge_search_v2),
        ]
        all_refs: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for search_name, method in search_steps:
            for page_number in self._page_numbers():
                if self.quota_blocked:
                    break
                cursor = page_number * self.settings.search_page_size
                page_key = f"{search_name}:cursor:{cursor}"
                if self._is_complete(checkpoint, page_key):
                    cached = read_page_items(raw_dir, page_key)
                    new_refs = [item for item in cached if video_ref_id(item) not in seen_ids]
                else:
                    payload = build_search_payload(request, cursor=cursor, count=self.settings.search_page_size)
                    result = self._safe_call(page_key, lambda method=method, payload=payload: method(**payload))
                    if result is None:
                        break
                    page_refs = extract_video_items(result)
                    self._commit_page(raw_dir, checkpoint, page_key, "challenge_posts", page_refs)
                    new_refs = [item for item in page_refs if video_ref_id(item) not in seen_ids]
                for item in new_refs:
                    ref_id = video_ref_id(item)
                    if ref_id:
                        seen_ids.add(ref_id)
                        all_refs.append(item)
                if self._limit_reached(all_refs, self.settings.max_videos):
                    return all_refs
                if not new_refs:
                    break
            if all_refs:
                return all_refs
        return []

    def _collect_legacy_refs(
        self, raw_dir: Path, checkpoint: dict[str, Any], request: DouyinCollectRequest
    ) -> list[dict[str, Any]]:
        topic = self._safe_call(
            "legacy_topic_query",
            lambda: self.client.fetch_topic_query(
                keyword=request.hashtag,
                start_date=request.start_date,
                end_date=request.end_date,
                app_name="aweme",
            ),
        )
        if topic is not None:
            self._commit_page(raw_dir, checkpoint, "legacy_topic_query", "topic_query", [topic])

        challenge_id = extract_challenge_id(topic)
        if challenge_id:
            page_key = f"legacy_challenge_posts:{challenge_id}"
            if not self._is_complete(checkpoint, page_key):
                result = self._safe_call(page_key, lambda: self.client.fetch_challenge_posts(challenge_id=challenge_id, cursor=0))
                if result is not None:
                    video_refs = extract_video_items(result)
                    self._commit_page(raw_dir, checkpoint, page_key, "challenge_posts", video_refs)
                    return video_refs
        page_key = "legacy_video_search_v1"
        if not self._is_complete(checkpoint, page_key):
            result = self._safe_call(
                page_key,
                lambda: getattr(self.client, "fetch_legacy_video_search_v1", self.client.fetch_video_search)(
                    keyword=request.hashtag,
                    start_date=request.start_date,
                    end_date=request.end_date,
                    cursor=0,
                ),
            )
            if result is not None:
                video_refs = extract_video_items(result)
                self._commit_page(raw_dir, checkpoint, page_key, "challenge_posts", video_refs)
                return video_refs
        return []


    def _collect_comments(
        self, raw_dir: Path, checkpoint: dict[str, Any], video_id: str, limit: int | None = -1
    ) -> list[dict[str, Any]]:
        effective_limit = self.settings.max_comments_per_video if limit == -1 else limit
        legacy_finite_key = f"comments:{video_id}" if effective_limit is not None else ""
        paged_comments: list[dict[str, Any]] = []
        failed = False
        cursor = 0
        for _page_number in self._page_numbers():
            if self.quota_blocked:
                break
            if effective_limit is not None and len(paged_comments) >= effective_limit:
                break
            comments_key = f"comments:{video_id}:cursor:{cursor}"
            result: Any | None = None
            if self._is_complete(checkpoint, comments_key):
                page_comments = read_page_items(raw_dir, comments_key)
            else:
                count = self.settings.search_page_size
                if effective_limit is not None:
                    remaining = max(0, effective_limit - len(paged_comments))
                    count = min(count, remaining)
                if count <= 0:
                    break
                result = self._safe_call(
                    comments_key,
                    lambda video_id=video_id, cursor=cursor, count=count: self.client.fetch_video_comments(
                        aweme_id=video_id, cursor=cursor, count=count
                    ),
                )
                if result is None:
                    failed = True
                    break
                page_comments = extract_comment_items(result, video_id)
                if effective_limit is not None:
                    page_comments = page_comments[: max(0, effective_limit - len(paged_comments))]
                self._commit_page(raw_dir, checkpoint, comments_key, "comments", page_comments)
            paged_comments.extend(page_comments)
            more = has_more(result) if result is not None else self._cached_page_may_have_next(page_comments)
            if not more:
                break
            next_cursor = extract_next_cursor(result, fallback=cursor + self.settings.search_page_size) if result is not None else cursor + self.settings.search_page_size
            if next_cursor == cursor:
                next_cursor += self.settings.search_page_size
            cursor = next_cursor
        if legacy_finite_key and not failed:
            self._mark_complete(raw_dir, checkpoint, legacy_finite_key)
        return paged_comments

    def _prepare_comment_candidate_video_refs(
        self, raw_dir: Path, checkpoint: dict[str, Any], request: DouyinCollectRequest
    ) -> list[dict[str, Any]]:
        by_id = {video_ref_id(row) or str(row.get("video_id") or ""): dict(row) for row in request.source_video_rows or []}
        refs: list[dict[str, Any]] = []
        for candidate in request.comment_candidates or []:
            row = by_id.get(candidate.video_id, {"video_id": candidate.video_id})
            row.setdefault("video_id", candidate.video_id)
            row.setdefault("source_challenge_id", candidate.source_challenge_id)
            row.setdefault("source_challenge_name", candidate.source_challenge_name)
            row.setdefault("comment_count", candidate.metadata_comment_count)
            row.setdefault("hashtags", candidate.caption_hashtags)
            row.setdefault("_metadata_source", "source_processed_videos")
            refs.append(row)
        for row in refs:
            video_id = str(row.get("video_id") or row.get("aweme_id") or "")
            if video_id:
                self._commit_page(raw_dir, checkpoint, f"candidate_video_metadata:{video_id}", "video_details", [row])
        return refs

    def _collect_replies(self, raw_dir: Path, checkpoint: dict[str, Any], video_id: str, comment_id: str) -> None:
        if self.settings.max_replies_per_comment is not None:
            replies_key = f"replies:{comment_id}"
            if self._is_complete(checkpoint, replies_key):
                return
            replies_result = self._safe_call(
                replies_key,
                lambda video_id=video_id, comment_id=comment_id: self.client.fetch_video_comment_replies(
                    aweme_id=video_id,
                    comment_id=comment_id,
                    cursor=0,
                    count=self._request_count(self.settings.max_replies_per_comment),
                ),
            )
            if replies_result is None:
                return
            replies = limit_items(
                extract_comment_items(replies_result, video_id, parent_comment_id=comment_id),
                self.settings.max_replies_per_comment,
            )
            self._commit_page(raw_dir, checkpoint, replies_key, "comment_replies", replies)
            return

        cursor = 0
        for _page_number in self._page_numbers():
            if self.quota_blocked:
                break
            replies_key = f"replies:{comment_id}:cursor:{cursor}"
            result: Any | None = None
            if self._is_complete(checkpoint, replies_key):
                page_replies = read_page_items(raw_dir, replies_key)
            else:
                result = self._safe_call(
                    replies_key,
                    lambda video_id=video_id, comment_id=comment_id, cursor=cursor: self.client.fetch_video_comment_replies(
                        aweme_id=video_id,
                        comment_id=comment_id,
                        cursor=cursor,
                        count=self.settings.search_page_size,
                    ),
                )
                if result is None:
                    break
                page_replies = extract_comment_items(result, video_id, parent_comment_id=comment_id)
                self._commit_page(raw_dir, checkpoint, replies_key, "comment_replies", page_replies)
            more = has_more(result) if result is not None else self._cached_page_may_have_next(page_replies)
            if not more:
                break
            next_cursor = extract_next_cursor(result, fallback=cursor + self.settings.search_page_size) if result is not None else cursor + self.settings.search_page_size
            if next_cursor == cursor:
                next_cursor += self.settings.search_page_size
            cursor = next_cursor

    def _collect_profiles(self, raw_dir: Path, checkpoint: dict[str, Any], sec_user_ids: list[str]) -> None:
        for sec_user_id in sec_user_ids:
            if self.quota_blocked:
                break
            key = f"profile:{sec_user_id}"
            if self._is_complete(checkpoint, key):
                continue
            try:
                result = self.client.handler_user_profile(sec_user_id)
                self._commit_page(raw_dir, checkpoint, key, "user_profiles", extract_user_items(result))
            except Exception as exc:  # noqa: BLE001 - single-profile failures should not abort a small batch.
                self.skipped_users.append(sec_user_id)
                message = redact_secrets(str(exc), [self.settings.api_key])
                self.failed_pages.append({"page": key, "error": message})
                if is_quota_blocker(message):
                    self.quota_blocked = True

    def _safe_call(self, page: str, fn) -> Any | None:
        try:
            return fn()
        except TikHubClientError as exc:
            message = redact_secrets(str(exc), [self.settings.api_key])
            self.failed_pages.append({"page": page, "error": message})
            if is_quota_blocker(message):
                self.quota_blocked = True
            return None


    def _selection_metadata(
        self,
        request: DouyinCollectRequest,
        *,
        stages: set[str] | None = None,
        stage_counts: dict[str, int] | None = None,
        selected_video_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        selections = [selection.__dict__ for selection in request.challenge_selections or []]
        if request.challenge_id and not selections:
            selections = [DouyinChallengeSelection(rank=1, name=request.hashtag, challenge_id=request.challenge_id, source="request.challenge_id").__dict__]
        enabled = sorted(stages if stages is not None else request.enabled_stages())
        return {
            "collection_scope": request.collection_scope,
            "selection_source": request.selection_source,
            "challenge_id": request.challenge_id,
            "challenge_selections": selections,
            "enabled_stages": enabled,
            "stage_status": {stage: ("enabled" if stage in enabled else "disabled") for stage in FULL_COLLECT_STAGES},
            "stage_counts": stage_counts or {},
            "selected_video_ids": selected_video_ids or [],
            "comment_candidates": [candidate.__dict__ for candidate in request.comment_candidates or []],
            "comment_target_count": len(request.comment_candidates or []),
            "comments_collected": STAGE_COMMENTS in enabled,
            "profiles_collected": STAGE_PROFILES in enabled,
            "video_source_mode": "merged_detail_preferred" if STAGE_VIDEO_METADATA in enabled else "challenge_only",
            "resume": request.resume,
            "limit_profile": "unbounded" if self.settings.business_limits_unbounded() else "capped",
            "quota_blocked": self.quota_blocked,
        }

    def _page_numbers(self):
        page_number = 0
        while self.settings.max_search_pages is None or page_number < self.settings.max_search_pages:
            yield page_number
            page_number += 1

    def _limit_reached(self, values: Sequence[Any], limit: int | None) -> bool:
        return limit is not None and len(values) >= limit

    def _request_count(self, limit: int | None) -> int:
        return limit if limit is not None else self.settings.search_page_size

    def _cached_page_may_have_next(self, page_items: Sequence[Any]) -> bool:
        # Page journals intentionally store normalized items, not the full API
        # envelope. On resume, a partial cached page cannot have a next page;
        # only a full page might need probing for the following cursor.
        return len(page_items) >= self.settings.search_page_size

    def _ensure_fresh_run(self, raw_dir: Path, processed_dir: Path) -> None:
        for directory in (raw_dir, processed_dir):
            if not directory.exists():
                continue
            if any(directory.iterdir()):
                raise FileExistsError(f"Refusing to reuse existing run directory without --resume: {directory}")

    def _write_manifest(self, raw_dir: Path, run_id: str, request: DouyinCollectRequest) -> None:
        manifest = {
            "run_id": run_id,
            "platform": "douyin",
            "hashtag": request.hashtag,
            "start_date": request.start_date,
            "end_date": request.end_date,
            "mode": request.mode,
            "collection_scope": request.collection_scope,
            "selection_source": request.selection_source,
            "challenge_id": request.challenge_id,
            "challenge_selections": [selection.__dict__ for selection in request.challenge_selections or []],
            "comment_target_count": len(request.comment_candidates or []),
            "config": self.settings.redacted(),
        }
        (raw_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    def _commit_status(
        self,
        raw_dir: Path,
        checkpoint: dict[str, Any],
        detail_key: str,
        video_id: str,
        status: str,
        source: dict[str, Any] | None = None,
    ) -> None:
        item: dict[str, Any] = {"video_id": video_id, "status": status}
        if source:
            item["source_keys"] = sorted(str(key) for key in source.keys())
        self._commit_page(raw_dir, checkpoint, f"video_metadata_status:{video_id}:{status}", "video_metadata_status", [item])
        self._mark_complete(raw_dir, checkpoint, detail_key)

    def _commit_page(
        self,
        raw_dir: Path,
        checkpoint: dict[str, Any],
        page_key: str,
        raw_kind: str,
        items: Iterable[dict[str, Any]],
    ) -> None:
        journal_dir = raw_dir / "pages"
        journal_dir.mkdir(parents=True, exist_ok=True)
        page = {
            "page_key": page_key,
            "raw_kind": raw_kind,
            "items": [redact_secrets(item, [self.settings.api_key]) for item in items],
        }
        target = journal_dir / f"{safe_page_key(page_key)}.json"
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(page, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(target)
        self._mark_complete(raw_dir, checkpoint, page_key)

    def _restore_checkpoint_from_page_journals(self, raw_dir: Path, checkpoint: dict[str, Any]) -> None:
        for page in self._load_page_journals(raw_dir):
            key = page.get("page_key")
            if key:
                checkpoint.setdefault("completed", {})[str(key)] = True
        self._save_checkpoint(raw_dir, checkpoint)

    def _rebuild_raw_jsonl_from_pages(self, raw_dir: Path) -> None:
        rows_by_kind: dict[str, list[dict[str, Any]]] = {kind: [] for kind in RAW_FILES}
        for page in self._load_page_journals(raw_dir):
            raw_kind = str(page.get("raw_kind", ""))
            items = page.get("items", [])
            if raw_kind in rows_by_kind and isinstance(items, list):
                rows_by_kind[raw_kind].extend(item for item in items if isinstance(item, dict))
        for raw_kind, filename in RAW_FILES.items():
            path = raw_dir / filename
            with path.open("w", encoding="utf-8") as handle:
                for item in rows_by_kind[raw_kind]:
                    handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
    def _load_page_journals(self, raw_dir: Path) -> list[dict[str, Any]]:
        journal_dir = raw_dir / "pages"
        if not journal_dir.exists():
            return []
        pages: list[dict[str, Any]] = []
        for path in sorted(journal_dir.glob("*.json")):
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                pages.append(loaded)
        return pages

    def _load_checkpoint(self, raw_dir: Path) -> dict[str, Any]:
        path = raw_dir / "checkpoints.json"
        if not path.exists():
            return {"completed": {}}
        return json.loads(path.read_text(encoding="utf-8"))

    def _save_checkpoint(self, raw_dir: Path, checkpoint: dict[str, Any]) -> None:
        safe = redact_secrets(checkpoint, [self.settings.api_key])
        (raw_dir / "checkpoints.json").write_text(json.dumps(safe, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    def _mark_complete(self, raw_dir: Path, checkpoint: dict[str, Any], key: str) -> None:
        checkpoint.setdefault("completed", {})[key] = True
        self._save_checkpoint(raw_dir, checkpoint)

    def _is_complete(self, checkpoint: dict[str, Any], key: str) -> bool:
        return bool(checkpoint.get("completed", {}).get(key))



def comment_has_zero_replies(comment: dict[str, Any]) -> bool:
    for key in ("reply_comment_total", "reply_count", "reply_total"):
        value = comment.get(key)
        if value in (None, ""):
            continue
        try:
            return int(value) <= 0
        except (TypeError, ValueError):
            continue
    return False

def is_quota_blocker(message: str) -> bool:
    lowered = message.lower()
    return "http 402" in lowered or "insufficient balance" in lowered or "余额" in message


def make_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def read_page_items(raw_dir: Path, page_key: str) -> list[dict[str, Any]]:
    path = raw_dir / "pages" / f"{safe_page_key(page_key)}.json"
    if not path.exists():
        return []
    page = json.loads(path.read_text(encoding="utf-8"))
    items = page.get("items", []) if isinstance(page, dict) else []
    return [item for item in items if isinstance(item, dict)]


def video_ref_id(item: dict[str, Any]) -> str:
    return str(item.get("video_id") or item.get("aweme_id") or item.get("id") or "")


def extract_challenge_id(topic: Any) -> str | None:
    if not isinstance(topic, dict):
        return None
    data_candidate = topic.get("data")
    candidates: list[dict[str, Any]] = [topic, data_candidate if isinstance(data_candidate, dict) else {}]
    for candidate in candidates:
        for key in ("challenge_id", "cid", "cha_id", "topic_id"):
            value = candidate.get(key)
            if value:
                return str(value)
    for key in ("items", "list", "data"):
        items = topic.get(key)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    found = extract_challenge_id(item)
                    if found:
                        return found
    return None



def extract_challenge_items(result: Any) -> list[dict[str, Any]]:
    if isinstance(result, list):
        list_rows: list[dict[str, Any]] = []
        for item in result:
            list_rows.extend(extract_challenge_items(item))
        return list_rows
    if not isinstance(result, dict):
        return []
    challenge_info = result.get("challenge_info")
    if isinstance(challenge_info, dict):
        return [challenge_info]
    business_data = result.get("business_data")
    if isinstance(business_data, list):
        business_rows: list[dict[str, Any]] = []
        for item in business_data:
            if isinstance(item, dict):
                business_rows.extend(extract_challenge_items(item.get("data")))
        return business_rows
    for key in ("challenges", "challenge_list", "items", "list"):
        value = result.get(key)
        if isinstance(value, list):
            nested_rows: list[dict[str, Any]] = []
            for item in value:
                nested_rows.extend(extract_challenge_items(item))
            return nested_rows or [item for item in value if isinstance(item, dict)]
    data = result.get("data")
    if isinstance(data, dict):
        return extract_challenge_items(data)
    return [result] if any(key in result for key in ("challenge_id", "cid", "cha_id", "topic_id", "cha_name")) else []


def select_challenge_id(challenge_rows: list[dict[str, Any]], hashtag: str) -> str | None:
    wanted = hashtag.lstrip("#").strip()
    for row in challenge_rows:
        name = str(row.get("cha_name") or row.get("hashtag_name") or row.get("name") or "").lstrip("#").strip()
        if name == wanted:
            found = extract_challenge_id(row)
            if found:
                return found
    return extract_challenge_id({"items": challenge_rows})


def extract_next_cursor(result: Any, fallback: int = 0) -> int:
    if not isinstance(result, dict):
        return fallback
    for candidate in (result, result.get("data") if isinstance(result.get("data"), dict) else {}):
        if not isinstance(candidate, dict):
            continue
        value = candidate.get("cursor") or candidate.get("max_cursor") or candidate.get("next_cursor")
        if value in (None, ""):
            continue
        try:
            return int(str(value))
        except (TypeError, ValueError):
            continue
    return fallback


def has_more(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    for candidate in (result, result.get("data") if isinstance(result.get("data"), dict) else {}):
        if isinstance(candidate, dict) and "has_more" in candidate:
            return bool(candidate.get("has_more"))
    return False

def extract_video_items(result: Any) -> list[dict[str, Any]]:
    if isinstance(result, list):
        list_rows: list[dict[str, Any]] = []
        for item in result:
            list_rows.extend(extract_video_items(item))
        return list_rows
    if not isinstance(result, dict):
        return []
    aweme_info = result.get("aweme_info")
    if isinstance(aweme_info, dict):
        return [aweme_info]
    business_data = result.get("business_data")
    if isinstance(business_data, list):
        business_rows: list[dict[str, Any]] = []
        for item in business_data:
            if not isinstance(item, dict):
                continue
            data = item.get("data")
            if isinstance(data, dict):
                business_rows.extend(extract_video_items(data))
        if business_rows:
            return business_rows
    for key in ("videos", "aweme_list", "aweme_infos", "mix_list", "items", "list"):
        value = result.get(key)
        if isinstance(value, list):
            extracted_rows = []
            for item in value:
                extracted_rows.extend(extract_video_items(item))
            if extracted_rows:
                return extracted_rows
            raw_rows = [item for item in value if isinstance(item, dict)]
            if raw_rows:
                return raw_rows
    data = result.get("data")
    if isinstance(data, dict):
        return extract_video_items(data)
    return [result] if any(key in result for key in ("video_id", "aweme_id", "id")) else []


def extract_comment_items(result: Any, video_id: str, parent_comment_id: str = "") -> list[dict[str, Any]]:
    if isinstance(result, list):
        rows: list[dict[str, Any]] = []
        for item in result:
            rows.extend(extract_comment_items(item, video_id, parent_comment_id))
        return rows
    if not isinstance(result, dict):
        return []
    for key in ("comments", "comment_list", "reply_comment", "replies", "items", "list"):
        value = result.get(key)
        if isinstance(value, list):
            rows = [dict(item) for item in value if isinstance(item, dict)]
            for row in rows:
                row.setdefault("video_id", video_id)
                if parent_comment_id:
                    row.setdefault("parent_comment_id", parent_comment_id)
            return rows
    data = result.get("data")
    if isinstance(data, dict):
        return extract_comment_items(data, video_id, parent_comment_id)
    return []


def extract_user_items(result: Any) -> list[dict[str, Any]]:
    if not isinstance(result, dict):
        return []
    for key in ("users", "user_list", "profiles", "items", "list"):
        value = result.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    data = result.get("data")
    if isinstance(data, dict):
        return extract_user_items(data)
    return [result] if any(key in result for key in ("user_id", "uid", "sec_user_id", "sec_uid")) else []


def extract_sec_user_ids(raw_dir: Path) -> list[str]:
    ids: set[str] = set()
    for path in [raw_dir / RAW_FILES["video_details"], raw_dir / RAW_FILES["comments"], raw_dir / RAW_FILES["comment_replies"]]:
        for row in read_jsonl(path):
            for value in walk_values(row):
                if isinstance(value, dict):
                    sec = value.get("sec_user_id") or value.get("sec_uid")
                    if sec:
                        ids.add(str(sec))
    return sorted(ids)


def walk_values(value: Any):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_values(child)


def unwrap_video_detail(row: dict[str, Any]) -> dict[str, Any]:
    current = row
    carried = {key: value for key, value in row.items() if key in {"video_id", "aweme_id"}}
    for _ in range(4):
        for key in ("aweme_detail", "aweme", "data"):
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


def ensure_video_id(detail: Any, video_id: str) -> dict[str, Any]:
    if isinstance(detail, dict):
        row = dict(detail)
        row.setdefault("video_id", video_id)
        return row
    return {"video_id": video_id}


def dedupe_by_id(items: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for item in items:
        key = str(item.get("video_id") or item.get("aweme_id") or item.get("id") or len(by_id))
        by_id[key] = item
    values = [by_id[key] for key in sorted(by_id)]
    return values if limit is None else values[:limit]


T = TypeVar("T")


def limit_items(items: list[T], limit: int | None) -> list[T]:
    return items if limit is None else items[:limit]


def chunks(values: list[str], size: int):
    for index in range(0, len(values), size):
        yield values[index : index + size]


def is_within_date_window(row: dict[str, Any], start_date: str | None, end_date: str | None) -> bool:
    row = unwrap_video_detail(row)
    published = parse_date_value(row.get("publish_time") or row.get("create_time") or row.get("createTime"))
    if published is None:
        return True
    if start_date and published < date.fromisoformat(start_date):
        return False
    if end_date and published > date.fromisoformat(end_date):
        return False
    return True


def has_parseable_video_date(row: dict[str, Any]) -> bool:
    detail = unwrap_video_detail(row)
    return parse_date_value(detail.get("publish_time") or detail.get("create_time") or detail.get("createTime")) is not None


def has_usable_video_detail(row: dict[str, Any]) -> bool:
    """Return true when a search/hashtag row is rich enough to normalize.

    TikHub hashtag pages in live runs can already include the same core fields
    needed by the normalizer, so using them avoids an expensive per-video
    detail call. Mock/search refs are often sparse ``{"aweme_id": ...}``
    pointers; those must still fetch App V3 detail so date filtering and text
    fields remain correct.
    """

    detail = unwrap_video_detail(row)
    return any(
        key in detail and detail.get(key) not in (None, "", [], {})
        for key in ("caption", "desc", "title", "author", "creator", "user", "statistics", "stats", "share_url", "video_url")
    ) or has_parseable_video_date(detail)


def parse_date_value(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).date()
    text = str(value)
    if text.isdigit():
        return datetime.fromtimestamp(int(text), tz=timezone.utc).date()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def safe_page_key(page_key: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", page_key).strip("_") or "page"


def build_search_payload(request: DouyinCollectRequest, *, cursor: int = 0, count: int = 20) -> dict[str, Any]:
    payload: dict[str, Any] = {"keyword": request.hashtag, "cursor": cursor, "count": count}
    payload["search_channel"] = "aweme_video_web"
    if request.start_date:
        payload["start_date"] = request.start_date
    if request.end_date:
        payload["end_date"] = request.end_date
    return payload


def build_challenge_search_payload(request: DouyinCollectRequest, *, cursor: int = 0) -> dict[str, Any]:
    return {
        "keyword": request.hashtag.lstrip("#"),
        "cursor": cursor,
        "sort_type": "0",
        "publish_time": "0",
        "filter_duration": "0",
        "content_type": "0",
        "search_id": "",
    }
