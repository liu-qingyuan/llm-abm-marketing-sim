from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .douyin_models import DouyinCommentRecord, DouyinEdgeRecord, DouyinVideoRecord


@dataclass
class EdgeAccumulator:
    comment_count: int = 0
    reply_count: int = 0
    mention_count: int = 0
    times: list[str] = field(default_factory=list)

    def add(self, kind: str, timestamp: str) -> None:
        if kind == "comment":
            self.comment_count += 1
        elif kind == "reply":
            self.reply_count += 1
        elif kind == "mention":
            self.mention_count += 1
        else:  # pragma: no cover - internal caller controls kind.
            raise ValueError(f"unknown edge interaction kind: {kind}")
        if timestamp:
            self.times.append(timestamp)


def build_interaction_edges(
    videos: list[DouyinVideoRecord], comments: list[DouyinCommentRecord]
) -> list[DouyinEdgeRecord]:
    creators = {video.video_id: video.creator_user_id for video in videos if video.creator_user_id}
    comments_by_id = {comment.comment_id: comment for comment in comments}
    edge_counts: dict[tuple[str, str], EdgeAccumulator] = defaultdict(EdgeAccumulator)

    def add(source: str, target: str, kind: str, timestamp: str) -> None:
        if not source or not target or source == target:
            return
        edge_counts[(source, target)].add(kind, timestamp)

    for comment in comments:
        if comment.comment_level == "comment":
            add(comment.commenter_user_id, creators.get(comment.video_id, ""), "comment", comment.publish_time)
        else:
            parent = comments_by_id.get(comment.parent_comment_id)
            add(comment.commenter_user_id, parent.commenter_user_id if parent else "", "reply", comment.publish_time)
        for mentioned in comment.mentioned_user_ids:
            add(comment.commenter_user_id, mentioned, "mention", comment.publish_time)

    records: list[DouyinEdgeRecord] = []
    for (source, target), counts in sorted(edge_counts.items()):
        times = sorted(counts.times)
        records.append(
            DouyinEdgeRecord(
                source=source,
                target=target,
                weight=counts.comment_count + counts.reply_count + counts.mention_count,
                comment_count=counts.comment_count,
                reply_count=counts.reply_count,
                mention_count=counts.mention_count,
                first_interaction_time=times[0] if times else "",
                last_interaction_time=times[-1] if times else "",
            )
        )
    return records
