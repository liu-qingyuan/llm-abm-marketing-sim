from __future__ import annotations

import ast
import csv
import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .decision import LLMDecisionAdapter
from .schemas import (
    LATENT_PROFILE_LABEL_FIELDS,
    LATENT_VALUE_DIMENSIONS,
    LEGACY_DEMO_PRESET_FIELDS,
    FailClosedAction,
    ProviderLLMConfig,
    ReportConfig,
)

TARGET_VIDEO_ID = "7328592728139353363"
TARGET_NETWORK_SCOPE = "锦江酒店"
PROFILE_INDEX_METHOD = "log1p_p95_reference_weighted_v2"
UNOBSERVED_PAIR_SEMANTICS = "No observed interaction is not evidence that a user saw the target video and chose ignore."
REQUIRED_DATASET_FILES = ("videos.csv", "users.csv")
SAMPLE_CSV_FIELDS = (
    "user_id",
    "nickname",
    "bio",
    "signature",
    "follower_count",
    "following_count",
    "video_count",
    "activity_score",
    "activity_video_score",
    "activity_comment_score",
    "activity_reply_score",
    "global_influence_score",
    "local_influence_score",
    "local_network_score",
    "local_recognition_score",
    "sample_source_scope",
    "is_seed",
    "latent_attribute_spec_id",
    "latent_attribute_method",
    "latent_attribute_seed",
    "latent_class",
    "latent_environmental_consciousness_coef",
    *(f"latent_{dimension}_value_weight" for dimension in LATENT_VALUE_DIMENSIONS),
    *(f"latent_{field_name}" for field_name in LATENT_PROFILE_LABEL_FIELDS),
)
SCORE_CSV_FIELDS = (
    "user_id",
    "base_network_score",
    "historical_tag_affinity",
    "recommendation_score",
    "has_non_target_history",
    "has_network_connection",
    "has_historical_tag_affinity",
)


class FinalResearchConfig(BaseModel):
    """Validated inputs for the single-target final research workflow."""

    model_config = ConfigDict(extra="forbid")

    dataset_dir: Path
    target_video_id: str = TARGET_VIDEO_ID
    sample_size: int = Field(default=1000, ge=1)
    horizon: int = Field(default=30, ge=1)
    random_seed: int = 20260713
    network_weight: float = Field(default=0.70, ge=0.0, le=1.0)
    tag_affinity_weight: float = Field(default=0.30, ge=0.0, le=1.0)
    neighbor_boost: float = Field(default=0.20, ge=0.0, le=1.0)
    provider: ProviderLLMConfig = Field(default_factory=ProviderLLMConfig)
    report: ReportConfig = Field(default_factory=ReportConfig)

    @field_validator("target_video_id")
    @classmethod
    def _target_video_is_fixed(cls, value: str) -> str:
        if value != TARGET_VIDEO_ID:
            raise ValueError(f"target_video_id must be the approved real target video {TARGET_VIDEO_ID}")
        return value

    @model_validator(mode="after")
    def _validate_dataset_and_weights(self) -> FinalResearchConfig:
        if not math.isclose(self.network_weight + self.tag_affinity_weight, 1.0, abs_tol=1e-9):
            raise ValueError("network_weight and tag_affinity_weight must sum to 1.0")
        if self.provider.enabled:
            if self.provider.fail_closed_action is not FailClosedAction.RAISE:
                raise ValueError("enabled final research provider must use fail_closed_action=raise")
            if self.provider.max_retries > 5:
                raise ValueError("enabled final research provider max_retries must not exceed 5")

        dataset_dir = self.dataset_dir.expanduser()
        if not dataset_dir.is_dir():
            raise ValueError(f"dataset_dir does not exist: {dataset_dir}")
        missing = [filename for filename in REQUIRED_DATASET_FILES if not (dataset_dir / filename).is_file()]
        if not (dataset_dir / "all_comments.csv").is_file() and not (dataset_dir / "comments.csv").is_file():
            missing.append("all_comments.csv or comments.csv")
        if missing:
            raise ValueError(f"dataset_dir is missing required file(s): {', '.join(missing)}")

        target_exists = False
        with (dataset_dir / "videos.csv").open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if _cell(row, "video_id") == self.target_video_id:
                    target_exists = True
                    break
        if not target_exists:
            raise ValueError(f"target video {self.target_video_id} is absent from videos.csv")

        user_ids: set[str] = set()
        with (dataset_dir / "users.csv").open(encoding="utf-8", newline="") as handle:
            for row_number, row in enumerate(csv.DictReader(handle), start=2):
                user_id = _cell(row, "user_id")
                if not user_id:
                    raise ValueError(f"users.csv row {row_number} has an empty user_id")
                if user_id in user_ids:
                    raise ValueError(f"users.csv contains duplicate user_id: {user_id}")
                user_ids.add(user_id)
        if self.sample_size > len(user_ids):
            raise ValueError(f"sample_size {self.sample_size} exceeds available user count {len(user_ids)}")
        self.dataset_dir = dataset_dir
        return self

    def snapshot(self) -> dict[str, object]:
        return {
            "dataset_dir": str(self.dataset_dir),
            "target_video_id": self.target_video_id,
            "sample_size": self.sample_size,
            "horizon": self.horizon,
            "horizon_semantics": "fixed recommendation batches, not natural days",
            "user_opportunity_limit": 1,
            "random_seed": self.random_seed,
            "network_weight": self.network_weight,
            "tag_affinity_weight": self.tag_affinity_weight,
            "neighbor_boost": self.neighbor_boost,
            "provider": self.provider.safe_metadata(),
            "report": self.report.model_dump(mode="json"),
        }


class TargetVideo(BaseModel):
    """Real target video fields allowed before holdout revelation."""

    model_config = ConfigDict(extra="forbid")

    video_id: str
    source_challenge_name: str
    source_challenge_rank: int
    caption: str
    hashtags: list[str]
    creator_user_id: str
    video_url: str


class ResearchUser(BaseModel):
    """Observed profile plus virtual labels and holdout-safe runtime proxies."""

    model_config = ConfigDict(extra="forbid")

    user_id: str
    nickname: str = ""
    bio: str = ""
    signature: str = ""
    follower_count: int = 0
    following_count: int = 0
    video_count: int = 0
    activity_score: float = 0.0
    activity_video_score: float = 0.0
    activity_comment_score: float = 0.0
    activity_reply_score: float = 0.0
    global_influence_score: float = 0.0
    local_influence_score: float = 0.0
    local_network_score: float = 0.0
    local_recognition_score: float = 0.0
    latent_attributes: dict[str, str | int | float]
    sample_source_scope: str = ""
    is_seed: bool = False

    def sample_row(self) -> dict[str, object]:
        row = self.model_dump(exclude={"latent_attributes"})
        row["is_seed"] = _csv_bool(self.is_seed)
        row.update(self.latent_attributes)
        return {field: row.get(field, "") for field in SAMPLE_CSV_FIELDS}


class OfflineRecommendationScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    base_network_score: float
    historical_tag_affinity: float
    recommendation_score: float
    has_non_target_history: bool
    has_network_connection: bool
    has_historical_tag_affinity: bool

    def csv_row(self) -> dict[str, object]:
        row = self.model_dump()
        for key in ("has_non_target_history", "has_network_connection", "has_historical_tag_affinity"):
            row[key] = _csv_bool(bool(row[key]))
        return row


@dataclass(frozen=True)
class _VideoRecord:
    video_id: str
    source_challenge_name: str
    source_challenge_rank: int
    caption: str
    hashtags: tuple[str, ...]
    creator_user_id: str
    video_url: str


@dataclass(frozen=True)
class _CommentRecord:
    comment_id: str
    video_id: str
    parent_comment_id: str
    commenter_user_id: str
    mentioned_user_ids: tuple[str, ...]
    like_count: int
    comment_level: str


@dataclass(frozen=True)
class _PreparedInputs:
    target_video: TargetVideo
    users_by_id: dict[str, ResearchUser]
    sample_user_ids: list[str]
    seed_user_ids: list[str]
    historical_video_count: int
    historical_interaction_rows: int
    holdout_interaction_rows: list[_CommentRecord]
    holdout_participant_ids: list[str]
    thresholds: dict[str, float]
    historical_interaction_user_ids: set[str]
    historical_tags_by_user: dict[str, set[str]]
    target_scope_weighted_degree: dict[str, int]
    source_scope_sample_counts: dict[str, int]


class _ResearchInputBuilder:
    def __init__(self, config: FinalResearchConfig) -> None:
        self.config = config

    def prepare(self) -> _PreparedInputs:
        videos = self._load_videos()
        comments = self._load_comments()
        profile_rows = _read_csv_rows(self.config.dataset_dir / "users.csv")
        target_record = videos[self.config.target_video_id]
        target_video = TargetVideo(
            video_id=target_record.video_id,
            source_challenge_name=target_record.source_challenge_name,
            source_challenge_rank=target_record.source_challenge_rank,
            caption=target_record.caption,
            hashtags=list(target_record.hashtags),
            creator_user_id=target_record.creator_user_id,
            video_url=target_record.video_url,
        )
        historical_videos = {video_id: video for video_id, video in videos.items() if video_id != target_video.video_id}
        historical_comments = [comment for comment in comments if comment.video_id != target_video.video_id]
        holdout_comments = [comment for comment in comments if comment.video_id == target_video.video_id]

        all_history_degree = _weighted_degrees(historical_videos, historical_comments)
        target_scope_video_ids = {
            video_id
            for video_id, video in historical_videos.items()
            if video.source_challenge_name == TARGET_NETWORK_SCOPE
        }
        target_scope_comments = [
            comment for comment in historical_comments if comment.video_id in target_scope_video_ids
        ]
        target_scope_degree = _weighted_degrees(historical_videos, target_scope_comments)
        history_counts, history_likes, historical_tags_by_user = _historical_user_signals(
            historical_videos,
            historical_comments,
        )
        thresholds = _holdout_safe_thresholds(profile_rows, history_counts, history_likes, all_history_degree)
        users_by_id = _build_research_users(
            profile_rows,
            history_counts=history_counts,
            history_likes=history_likes,
            all_history_degree=all_history_degree,
            thresholds=thresholds,
        )
        sample_user_ids, sample_scope_by_user = _sample_users(
            videos=historical_videos,
            comments=historical_comments,
            available_user_ids=set(users_by_id),
            sample_size=self.config.sample_size,
            random_seed=self.config.random_seed,
        )
        seed_user_ids = _select_seeds(sample_user_ids, users_by_id)
        seed_set = set(seed_user_ids)
        for user_id in sample_user_ids:
            user = users_by_id[user_id]
            users_by_id[user_id] = user.model_copy(
                update={
                    "sample_source_scope": sample_scope_by_user[user_id],
                    "is_seed": user_id in seed_set,
                }
            )
        return _PreparedInputs(
            target_video=target_video,
            users_by_id=users_by_id,
            sample_user_ids=sample_user_ids,
            seed_user_ids=seed_user_ids,
            historical_video_count=len(historical_videos),
            historical_interaction_rows=len(historical_comments),
            holdout_interaction_rows=holdout_comments,
            holdout_participant_ids=sorted({comment.commenter_user_id for comment in holdout_comments}),
            thresholds=thresholds,
            historical_interaction_user_ids=set(history_counts),
            historical_tags_by_user=historical_tags_by_user,
            target_scope_weighted_degree=target_scope_degree,
            source_scope_sample_counts=dict(sorted(Counter(sample_scope_by_user.values()).items())),
        )

    def _load_videos(self) -> dict[str, _VideoRecord]:
        videos: dict[str, _VideoRecord] = {}
        for row_number, row in enumerate(_read_csv_rows(self.config.dataset_dir / "videos.csv"), start=2):
            video_id = _cell(row, "video_id")
            if not video_id:
                raise ValueError(f"videos.csv row {row_number} has an empty video_id")
            if video_id in videos:
                raise ValueError(f"videos.csv contains duplicate video_id: {video_id}")
            videos[video_id] = _VideoRecord(
                video_id=video_id,
                source_challenge_name=_cell(row, "source_challenge_name"),
                source_challenge_rank=_int_cell(row, "source_challenge_rank"),
                caption=_cell(row, "caption"),
                hashtags=tuple(_parse_list(_cell(row, "hashtags"))),
                creator_user_id=_cell(row, "creator_user_id"),
                video_url=_cell(row, "video_url"),
            )
        return videos

    def _load_comments(self) -> list[_CommentRecord]:
        path = self.config.dataset_dir / "all_comments.csv"
        if not path.is_file():
            path = self.config.dataset_dir / "comments.csv"
        comments: list[_CommentRecord] = []
        seen_ids: set[str] = set()
        for row_number, row in enumerate(_read_csv_rows(path), start=2):
            comment_id = _cell(row, "comment_id")
            if not comment_id:
                raise ValueError(f"{path.name} row {row_number} has an empty comment_id")
            if comment_id in seen_ids:
                raise ValueError(f"{path.name} contains duplicate comment_id: {comment_id}")
            seen_ids.add(comment_id)
            level = _cell(row, "comment_level").lower()
            if level not in {"comment", "reply"}:
                level = "reply" if _has_parent(_cell(row, "parent_comment_id")) else "comment"
            comments.append(
                _CommentRecord(
                    comment_id=comment_id,
                    video_id=_cell(row, "video_id"),
                    parent_comment_id=_cell(row, "parent_comment_id"),
                    commenter_user_id=_cell(row, "commenter_user_id"),
                    mentioned_user_ids=tuple(_parse_list(_cell(row, "mentioned_user_ids"))),
                    like_count=_int_cell(row, "like_count"),
                    comment_level=level,
                )
            )
        return comments


class PlatformRecommendationModel:
    """Static recommendation scoring over historical network and tag signals."""

    def __init__(self, config: FinalResearchConfig, prepared: _PreparedInputs) -> None:
        self.config = config
        self.prepared = prepared
        max_degree = max(prepared.target_scope_weighted_degree.values(), default=0)
        self._base_network_scores = {
            user_id: (degree / max_degree if max_degree > 0 else 0.0)
            for user_id, degree in prepared.target_scope_weighted_degree.items()
        }
        self._target_tags = set(prepared.target_video.hashtags)

    def score_static(self, user_id: str) -> OfflineRecommendationScore:
        history_tags = self.prepared.historical_tags_by_user.get(user_id, set())
        affinity = len(self._target_tags & history_tags) / max(len(self._target_tags), 1)
        base_network_score = self._base_network_scores.get(user_id, 0.0)
        score = self.config.network_weight * base_network_score + self.config.tag_affinity_weight * affinity
        return OfflineRecommendationScore(
            user_id=user_id,
            base_network_score=round(base_network_score, 6),
            historical_tag_affinity=round(affinity, 6),
            recommendation_score=round(score, 6),
            has_non_target_history=user_id in self.prepared.historical_interaction_user_ids,
            has_network_connection=base_network_score > 0.0,
            has_historical_tag_affinity=affinity > 0.0,
        )

    def score_all(self) -> list[OfflineRecommendationScore]:
        return [self.score_static(user_id) for user_id in sorted(self.prepared.users_by_id)]


class FinalResearchRunner:
    """Prepare and write the deterministic offline final-research baseline."""

    def __init__(self, config: FinalResearchConfig, decision_adapter: LLMDecisionAdapter) -> None:
        self.config = config
        self.decision_adapter = decision_adapter

    def run_and_write(self, output_dir: str | Path) -> Path:
        output_path = Path(output_dir)
        dataset_path = self.config.dataset_dir.resolve()
        if output_path.resolve().is_relative_to(dataset_path):
            raise ValueError("output_dir must be outside dataset_dir")
        if output_path.exists() and any(output_path.iterdir()):
            raise FileExistsError(f"output_dir already exists and is not empty: {output_path}")
        output_path.mkdir(parents=True, exist_ok=True)

        prepared = _ResearchInputBuilder(self.config).prepare()
        scores = PlatformRecommendationModel(self.config, prepared).score_all()
        ranked_scores = sorted(scores, key=lambda item: (-item.recommendation_score, item.user_id))
        top_scores = ranked_scores[:20]
        diagnostic = _holdout_diagnostic(prepared, top_scores)

        artifacts = {
            "config_snapshot": "config_snapshot.json",
            "holdout_diagnostic": "top20_holdout_diagnostic.json",
            "holdout_safe_audit": "holdout_safe_audit.json",
            "offline_score_summary": "offline_score_summary.json",
            "offline_scores": "offline_scores.csv",
            "sample_manifest_csv": "sample_manifest.csv",
            "sample_manifest_json": "sample_manifest.json",
            "target_video_snapshot": "target_video_snapshot.json",
        }
        sample_users = [prepared.users_by_id[user_id] for user_id in prepared.sample_user_ids]
        _write_json(output_path / artifacts["config_snapshot"], self.config.snapshot())
        _write_json(output_path / artifacts["target_video_snapshot"], prepared.target_video.model_dump(mode="json"))
        _write_json(
            output_path / artifacts["sample_manifest_json"], [user.model_dump(mode="json") for user in sample_users]
        )
        _write_csv(
            output_path / artifacts["sample_manifest_csv"],
            list(SAMPLE_CSV_FIELDS),
            [user.sample_row() for user in sample_users],
        )
        _write_csv(
            output_path / artifacts["offline_scores"],
            list(SCORE_CSV_FIELDS),
            [score.csv_row() for score in scores],
        )
        _write_json(
            output_path / artifacts["offline_score_summary"],
            _score_summary(scores, ranked_scores, self.config),
        )
        _write_json(output_path / artifacts["holdout_diagnostic"], diagnostic)
        _write_json(
            output_path / artifacts["holdout_safe_audit"],
            {
                "profile_index_method": PROFILE_INDEX_METHOD,
                "historical_video_count": prepared.historical_video_count,
                "historical_interaction_rows": prepared.historical_interaction_rows,
                "holdout_interaction_rows": len(prepared.holdout_interaction_rows),
                "holdout_unique_participant_count": len(prepared.holdout_participant_ids),
                "holdout_safe_reference_thresholds": prepared.thresholds,
                "sample_size": len(prepared.sample_user_ids),
                "source_scope_sample_counts": prepared.source_scope_sample_counts,
                "global_top10_local_top10_seed_union": prepared.seed_user_ids,
                "seed_count": len(prepared.seed_user_ids),
                "source_dataset_modified": False,
                "holdout_boundary": (
                    "Target interactions and aggregate engagement counts were excluded from profile projection, "
                    "sampling, seed selection, and recommendation scoring."
                ),
            },
        )
        _write_json(
            output_path / "artifact_manifest.json",
            {
                "manifest_version": "final-research-offline-v1",
                "artifacts": artifacts,
                "counts": {
                    "historical_videos": prepared.historical_video_count,
                    "users_scored": len(scores),
                    "sample_users": len(prepared.sample_user_ids),
                    "seed_users": len(prepared.seed_user_ids),
                },
                "live_api_triggered": False,
                "decision_adapter_calls": 0,
            },
        )
        return output_path


def _build_research_users(
    profile_rows: Sequence[Mapping[str, str]],
    *,
    history_counts: Mapping[str, Counter[str]],
    history_likes: Mapping[str, int],
    all_history_degree: Mapping[str, int],
    thresholds: Mapping[str, float],
) -> dict[str, ResearchUser]:
    users: dict[str, ResearchUser] = {}
    for row in profile_rows:
        user_id = _cell(row, "user_id")
        counts = history_counts.get(user_id, Counter())
        signals = {
            "video_count": _int_cell(row, "video_count"),
            "comment_count": counts["comment"],
            "reply_count": counts["reply"],
            "edge_degree": all_history_degree.get(user_id, 0),
            "comment_like_sum": history_likes.get(user_id, 0),
        }
        video_score = _log_p95_score(signals["video_count"], thresholds["video_count"])
        comment_score = _log_p95_score(signals["comment_count"], thresholds["comment_count"])
        reply_score = _log_p95_score(signals["reply_count"], thresholds["reply_count"])
        network_score = _log_p95_score(signals["edge_degree"], thresholds["edge_degree"])
        recognition_score = _log_p95_score(signals["comment_like_sum"], thresholds["comment_like_sum"])
        users[user_id] = ResearchUser(
            user_id=user_id,
            nickname=_cell(row, "nickname"),
            bio=_cell(row, "bio"),
            signature=_cell(row, "signature"),
            follower_count=_int_cell(row, "follower_count"),
            following_count=_int_cell(row, "following_count"),
            video_count=signals["video_count"],
            activity_score=round(0.25 * video_score + 0.45 * comment_score + 0.30 * reply_score, 6),
            activity_video_score=round(video_score, 6),
            activity_comment_score=round(comment_score, 6),
            activity_reply_score=round(reply_score, 6),
            global_influence_score=_float_cell(row, "global_influence_score"),
            local_influence_score=round(0.60 * network_score + 0.40 * recognition_score, 6),
            local_network_score=round(network_score, 6),
            local_recognition_score=round(recognition_score, 6),
            latent_attributes=_latent_attributes(row),
        )
    return users


def _historical_user_signals(
    videos: Mapping[str, _VideoRecord],
    comments: Sequence[_CommentRecord],
) -> tuple[dict[str, Counter[str]], dict[str, int], dict[str, set[str]]]:
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    likes: dict[str, int] = defaultdict(int)
    tags: dict[str, set[str]] = defaultdict(set)
    for comment in comments:
        if not comment.commenter_user_id:
            continue
        counts[comment.commenter_user_id][comment.comment_level] += 1
        likes[comment.commenter_user_id] += max(0, comment.like_count)
        video = videos.get(comment.video_id)
        if video is not None:
            tags[comment.commenter_user_id].update(video.hashtags)
    return dict(counts), dict(likes), dict(tags)


def _weighted_degrees(
    videos: Mapping[str, _VideoRecord],
    comments: Sequence[_CommentRecord],
) -> dict[str, int]:
    comment_by_id = {comment.comment_id: comment for comment in comments}
    degree: dict[str, int] = defaultdict(int)

    def add(source: str, target: str) -> None:
        if not source or not target or source == target:
            return
        degree[source] += 1
        degree[target] += 1

    for comment in comments:
        if comment.comment_level == "comment":
            video = videos.get(comment.video_id)
            add(comment.commenter_user_id, video.creator_user_id if video is not None else "")
        else:
            parent = comment_by_id.get(comment.parent_comment_id)
            add(comment.commenter_user_id, parent.commenter_user_id if parent is not None else "")
        for mentioned_user_id in comment.mentioned_user_ids:
            add(comment.commenter_user_id, mentioned_user_id)
    return dict(degree)


def _holdout_safe_thresholds(
    profile_rows: Sequence[Mapping[str, str]],
    history_counts: Mapping[str, Counter[str]],
    history_likes: Mapping[str, int],
    all_history_degree: Mapping[str, int],
) -> dict[str, float]:
    fields = ("video_count", "comment_count", "reply_count", "edge_degree", "comment_like_sum")
    values: dict[str, list[int]] = {field: [] for field in fields}
    for row in profile_rows:
        user_id = _cell(row, "user_id")
        counts = history_counts.get(user_id, Counter())
        signals = {
            "video_count": _int_cell(row, "video_count"),
            "comment_count": counts["comment"],
            "reply_count": counts["reply"],
            "edge_degree": all_history_degree.get(user_id, 0),
            "comment_like_sum": history_likes.get(user_id, 0),
        }
        for field in fields:
            values[field].append(signals[field])
    return {field: round(_percentile(field_values, 0.95), 6) for field, field_values in values.items()}


def _sample_users(
    *,
    videos: Mapping[str, _VideoRecord],
    comments: Sequence[_CommentRecord],
    available_user_ids: set[str],
    sample_size: int,
    random_seed: int,
) -> tuple[list[str], dict[str, str]]:
    scope_order = sorted(
        {(video.source_challenge_rank, video.source_challenge_name) for video in videos.values()},
        key=lambda item: (item[0], item[1]),
    )
    pools: dict[str, set[str]] = defaultdict(set)
    for comment in comments:
        video = videos.get(comment.video_id)
        if video is not None and comment.commenter_user_id in available_user_ids:
            pools[video.source_challenge_name].add(comment.commenter_user_id)

    selected: list[str] = []
    selected_set: set[str] = set()
    scope_by_user: dict[str, str] = {}
    for _rank, scope_name in scope_order:
        remaining_slots = sample_size - len(selected)
        if remaining_slots <= 0:
            break
        candidates = sorted(pools.get(scope_name, set()) - selected_set)
        rng = random.Random(_stable_seed(random_seed, scope_name))
        rng.shuffle(candidates)
        for user_id in candidates[: min(100, remaining_slots)]:
            selected.append(user_id)
            selected_set.add(user_id)
            scope_by_user[user_id] = scope_name

    if len(selected) < sample_size:
        remaining = sorted(available_user_ids - selected_set)
        rng = random.Random(_stable_seed(random_seed, "remaining-users"))
        rng.shuffle(remaining)
        for user_id in remaining[: sample_size - len(selected)]:
            selected.append(user_id)
            scope_by_user[user_id] = "remaining_users"
    if len(selected) != sample_size:
        raise ValueError(f"could not select {sample_size} unique users; selected {len(selected)}")
    return selected, scope_by_user


def _select_seeds(sample_user_ids: Sequence[str], users_by_id: Mapping[str, ResearchUser]) -> list[str]:
    global_top = sorted(
        sample_user_ids,
        key=lambda user_id: (-users_by_id[user_id].global_influence_score, user_id),
    )[:10]
    local_top = sorted(
        sample_user_ids,
        key=lambda user_id: (-users_by_id[user_id].local_influence_score, user_id),
    )[:10]
    return sorted(set(global_top) | set(local_top))


def _holdout_diagnostic(
    prepared: _PreparedInputs,
    top_scores: Sequence[OfflineRecommendationScore],
) -> dict[str, object]:
    observed = prepared.holdout_participant_ids[:20]
    recommended = [score.user_id for score in top_scores]
    observed_set = set(observed)
    participant_signals = []
    target_tags = set(prepared.target_video.hashtags)
    max_degree = max(prepared.target_scope_weighted_degree.values(), default=0)
    for user_id in observed:
        history_tags = prepared.historical_tags_by_user.get(user_id, set())
        base_score = prepared.target_scope_weighted_degree.get(user_id, 0) / max_degree if max_degree else 0.0
        affinity = len(target_tags & history_tags) / max(len(target_tags), 1)
        participant_signals.append(
            {
                "user_id": user_id,
                "has_non_target_history": user_id in prepared.historical_interaction_user_ids,
                "has_network_connection": base_score > 0.0,
                "has_historical_tag_affinity": affinity > 0.0,
            }
        )
    return {
        "observed_holdout_participant_count": len(observed),
        "observed_holdout_participant_ids": observed,
        "model_recommended_user_count": len(recommended),
        "model_recommended_user_ids": recommended,
        "intersection_count": len(observed_set & set(recommended)),
        "intersection_user_ids": sorted(observed_set & set(recommended)),
        "observed_participant_signal_coverage": {
            "with_non_target_history": sum(bool(row["has_non_target_history"]) for row in participant_signals),
            "with_network_connection": sum(bool(row["has_network_connection"]) for row in participant_signals),
            "with_historical_tag_affinity": sum(
                bool(row["has_historical_tag_affinity"]) for row in participant_signals
            ),
            "rows": participant_signals,
        },
        "diagnostic_only": True,
        "unobserved_pair_semantics": UNOBSERVED_PAIR_SEMANTICS,
        "production_accuracy_claim": False,
    }


def _score_summary(
    scores: Sequence[OfflineRecommendationScore],
    ranked_scores: Sequence[OfflineRecommendationScore],
    config: FinalResearchConfig,
) -> dict[str, object]:
    values = [score.recommendation_score for score in scores]
    return {
        "user_count": len(scores),
        "formula": "network_weight * base_network_score + tag_affinity_weight * historical_tag_affinity",
        "network_weight": config.network_weight,
        "tag_affinity_weight": config.tag_affinity_weight,
        "minimum_score": min(values, default=0.0),
        "maximum_score": max(values, default=0.0),
        "mean_score": round(sum(values) / len(values), 6) if values else 0.0,
        "users_with_non_target_history": sum(score.has_non_target_history for score in scores),
        "users_with_network_connection": sum(score.has_network_connection for score in scores),
        "users_with_historical_tag_affinity": sum(score.has_historical_tag_affinity for score in scores),
        "top20_user_ids": [score.user_id for score in ranked_scores[:20]],
    }


def _latent_attributes(row: Mapping[str, str]) -> dict[str, str | int | float]:
    result: dict[str, str | int | float] = {
        "latent_attribute_spec_id": _cell(row, "latent_attribute_spec_id"),
        "latent_attribute_method": _cell(row, "latent_attribute_method"),
        "latent_attribute_seed": _int_cell(row, "latent_attribute_seed"),
        "latent_class": _cell(row, "latent_class"),
        "latent_environmental_consciousness_coef": _float_cell(row, "latent_environmental_consciousness_coef"),
    }
    for dimension in LATENT_VALUE_DIMENSIONS:
        result[f"latent_{dimension}_value_weight"] = _float_cell(row, f"latent_{dimension}_value_weight")
    for field_name in LATENT_PROFILE_LABEL_FIELDS:
        result[f"latent_{field_name}"] = _cell(row, f"latent_{field_name}")
    missing = [key for key, value in result.items() if value == ""]
    if missing:
        raise ValueError(f"user {_cell(row, 'user_id')!r} has incomplete latent attributes: {', '.join(missing)}")
    return result


def _percentile(values: Iterable[int], quantile: float) -> float:
    clean = sorted(max(0, int(value)) for value in values)
    if not clean:
        return 0.0
    position = (len(clean) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(clean[lower])
    fraction = position - lower
    return float(clean[lower] * (1 - fraction) + clean[upper] * fraction)


def _log_p95_score(value: int, threshold: float) -> float:
    if value <= 0 or threshold <= 0:
        return 0.0
    return max(0.0, min(1.0, math.log1p(value) / math.log1p(threshold)))


def _stable_seed(random_seed: int, label: str) -> int:
    digest = hashlib.sha256(f"{random_seed}:{label}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_csv(path: Path, fieldnames: list[str], rows: Sequence[Mapping[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parse_list(value: str) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            parsed = None
    if isinstance(parsed, (list, tuple, set)):
        return [str(item).strip() for item in parsed if str(item).strip()]
    return [part.strip() for part in value.replace("|", ",").replace(";", ",").split(",") if part.strip()]


def _cell(row: Mapping[str, Any], field_name: str) -> str:
    value = row.get(field_name, "")
    return str(value or "").strip()


def _int_cell(row: Mapping[str, Any], field_name: str) -> int:
    value = _cell(row, field_name)
    if not value:
        return 0
    try:
        return max(0, int(float(value)))
    except ValueError as error:
        raise ValueError(f"invalid integer value for {field_name}: {value!r}") from error


def _float_cell(row: Mapping[str, Any], field_name: str) -> float:
    value = _cell(row, field_name)
    if not value:
        return 0.0
    try:
        return float(value)
    except ValueError as error:
        raise ValueError(f"invalid float value for {field_name}: {value!r}") from error


def _has_parent(parent_comment_id: str) -> bool:
    return parent_comment_id not in {"", "0", "none", "null"}


def _csv_bool(value: bool) -> str:
    return "true" if value else "false"


assert not LEGACY_DEMO_PRESET_FIELDS.intersection(SAMPLE_CSV_FIELDS)
