#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from llm_abm_sim.data_sources.cli import load_dotenv  # noqa: E402
from llm_abm_sim.data_sources.douyin_models import (  # noqa: E402
    PROFILE_COLUMNS,
    REMOVED_DEMO_PRESET_FIELDS,
    USER_COLUMNS,
)
from llm_abm_sim.data_sources.douyin_normalizer import normalize_user  # noqa: E402
from llm_abm_sim.data_sources.tikhub_client import TikHubClient, TikHubSettings, redact_secrets  # noqa: E402

DEFAULT_SOURCE_RUN = Path(
    "data/processed/jinjiang_douyin/"
    "jinjiang-caption-hashtag-comments-excluding-binguan-adding-jian-derived-20260621T025127Z"
)
PROCESSED_ROOT = Path("data/processed/jinjiang_douyin")
RAW_ROOT = Path("data/raw/tikhub/douyin/jinjiang_hotel")
SAFETY_EXCLUDED_VIDEO_IDS = {"7486704870804770107", "7486891790218399034"}
SENSITIVE_REPORT_PATTERNS = [
    "Authorization",
    "Cookie",
    "TIKHUB_API_KEY",
    "Bearer ",
]
PROFILE_BATCH_ENDPOINT = "fetch_batch_user_profile_v2"
PROFILE_HANDLER_ENDPOINT = "handler_user_profile"
PROFILE_FIELDNAMES = [
    "user_id",
    "sec_user_id",
    "sec_user_id_source",
    "sec_user_id_confidence",
    "user_role",
    "comment_count",
    "reply_count",
    "edge_degree",
    "in_degree",
    "out_degree",
    "comment_like_sum",
    "priority_tier",
    "profile_fetch_status",
    "skip_reason",
]
ABM_COLUMNS = [
    "user_id",
    "user_type",
    "follower_count",
    "following_count",
    "video_count",
    "verified_type",
    "interest_tags",
    "activity_score",
    "activity_video_score",
    "activity_publish_score",
    "activity_comment_score",
    "activity_reply_score",
    "global_influence_score",
    "local_influence_score",
    "local_network_score",
    "local_recognition_score",
    "influence_coverage_score",
    "influence_recognition_score",
    "influence_network_score",
    "profile_index_method",
    "profile_index_variant",
    "profile_source",
    "profile_fetch_status",
    "attribute_provenance",
]
STATUS_COLUMNS = [
    "user_id",
    "sec_user_id",
    "status",
    "endpoint",
    "http_status",
    "error_category",
    "error",
    "attempted_at",
]
RAW_SEC_UID_FILES = [
    ("comments.jsonl", "raw_comments"),
    ("comment_replies.jsonl", "raw_replies"),
    ("video_details.jsonl", "raw_video_details"),
    ("user_profiles.jsonl", "raw_profiles"),
]
RAW_SEC_UID_PAGE_SOURCES = {
    "candidate_video_metadata": "raw_video_details",
    "comments": "raw_comments",
    "replies": "raw_replies",
}
RAW_SEC_UID_SOURCE_PRIORITY = {
    "raw_comments": 0,
    "raw_replies": 1,
    "raw_video_details": 2,
    "raw_profiles": 3,
}


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            out: dict[str, Any] = {}
            for field in fieldnames:
                value = row.get(field, "")
                if isinstance(value, (list, dict)):
                    value = json.dumps(value, ensure_ascii=False, sort_keys=True)
                out[field] = value
            writer.writerow(out)


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def iter_jsonl_objects(path: Path) -> tuple[list[dict[str, Any]], int]:
    """Read a JSONL file and return parsed dict rows plus malformed-line count."""

    if not path.exists():
        return [], 0
    rows: list[dict[str, Any]] = []
    malformed = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    return rows, malformed


def iter_json_objects(path: Path) -> tuple[list[dict[str, Any]], int]:
    if not path.exists():
        return [], 0
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return [], 1
    if isinstance(obj, dict):
        return [obj], 0
    if isinstance(obj, list):
        return [item for item in obj if isinstance(item, dict)], 0
    return [], 0


def append_jsonl(path: Path, row: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def parse_int(value: Any) -> int:
    try:
        if value in (None, ""):
            return 0
        return int(float(str(value)))
    except (TypeError, ValueError):
        return 0


def has_parent_comment_id(value: Any) -> bool:
    return str(value or "").strip() not in {"", "0"}


def parse_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(str(value))
    except (TypeError, ValueError):
        return default


def bounded_ratio(value: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return max(0.0, min(1.0, value / denominator))


def bounded_log_ratio(value: int, denominator_power: float = 7.0) -> float:
    if value <= 0:
        return 0.0
    return max(0.0, min(1.0, math.log10(value + 1) / denominator_power))


PROFILE_INDEX_METHOD = "log1p_p95_reference_weighted_v2"
PROFILE_INDEX_VARIANT = "base"
PROFILE_INDEX_REFERENCE_BASIS = [
    "Qingbo DCI: publish/interaction/coverage dimensions and ln(X+1) count normalization",
    "Feigua and Newrank index logic: follower_count is treated only as platform coverage/popularity proxy when full playback/share/fan-growth fields are unavailable",
    "Tourism social-media engagement literature: comments require deeper participation than likes, supporting higher comment/reply activity weights",
    "Social network analysis: edge degree is a local network-position proxy; comment_like_sum is local recognition, not account-wide influence",
    "OECD/JRC composite-indicator practice: transparent weighting, log transformation, and sensitivity analysis for researcher-defined composite proxies",
]
PROFILE_INDEX_COMPONENT_FIELDS = [
    "activity_score",
    "activity_video_score",
    "activity_publish_score",
    "activity_comment_score",
    "activity_reply_score",
    "global_influence_score",
    "local_influence_score",
    "local_network_score",
    "local_recognition_score",
    "influence_coverage_score",
    "influence_recognition_score",
    "influence_network_score",
]
PROFILE_INDEX_SIGNAL_FIELDS = [
    "video_count",
    "comment_count",
    "reply_count",
    "follower_count",
    "edge_degree",
    "comment_like_sum",
]
ACTIVITY_WEIGHT_VARIANTS: dict[str, tuple[float, float, float]] = {
    "activity_equal": (1 / 3, 1 / 3, 1 / 3),
    "activity_base": (0.25, 0.45, 0.30),
    "activity_30_40_30": (0.30, 0.40, 0.30),
    "activity_20_50_30": (0.20, 0.50, 0.30),
    "activity_20_40_40": (0.20, 0.40, 0.40),
}
LOCAL_INFLUENCE_WEIGHT_VARIANTS: dict[str, tuple[float, float]] = {
    "local_equal": (0.50, 0.50),
    "local_base": (0.60, 0.40),
    "local_network_heavy": (0.70, 0.30),
}
NORMALIZATION_VARIANTS = ["log1p_p90", "log1p_p95", "log1p_p99", "rank_percentile"]


def percentile(values: Iterable[int], q: float) -> float:
    clean = sorted(max(0, int(value)) for value in values)
    if not clean:
        return 0.0
    if q <= 0:
        return float(clean[0])
    if q >= 1:
        return float(clean[-1])
    position = (len(clean) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(clean[int(position)])
    fraction = position - lower
    return float(clean[lower] * (1 - fraction) + clean[upper] * fraction)


def log_p95_score(value: int, p95: float) -> float:
    if value <= 0 or p95 <= 0:
        return 0.0
    return max(0.0, min(1.0, math.log1p(value) / math.log1p(p95)))


def log_percentile_score(value: int, threshold: float) -> float:
    if value <= 0 or threshold <= 0:
        return 0.0
    return max(0.0, min(1.0, math.log1p(value) / math.log1p(threshold)))


def rank_percentile_scores(values: Iterable[int]) -> list[float]:
    clean = [max(0, int(value)) for value in values]
    if not clean:
        return []
    if len(clean) == 1:
        return [1.0 if clean[0] > 0 else 0.0]
    sorted_values = sorted(clean)
    rank_sums: dict[int, float] = defaultdict(float)
    rank_counts: Counter[int] = Counter()
    for one_based_rank, value in enumerate(sorted_values, start=1):
        rank_sums[value] += one_based_rank
        rank_counts[value] += 1
    denominator = len(clean) - 1
    scores: list[float] = []
    for value in clean:
        if value <= 0:
            scores.append(0.0)
            continue
        average_rank = rank_sums[value] / rank_counts[value]
        scores.append(max(0.0, min(1.0, (average_rank - 1) / denominator)))
    return scores


def profile_index_signals(target: Mapping[str, Any], user: Mapping[str, Any]) -> dict[str, int]:
    comment_count = parse_int(target.get("comment_count"))
    reply_count = parse_int(target.get("reply_count"))
    return {
        "video_count": parse_int(user.get("video_count")),
        "comment_count": comment_count,
        "reply_count": reply_count,
        "follower_count": parse_int(user.get("follower_count")),
        "comment_like_sum": parse_int(target.get("comment_like_sum")),
        "edge_degree": parse_int(target.get("edge_degree")),
    }


def compute_profile_index_thresholds(signal_rows: Iterable[Mapping[str, int]]) -> dict[str, float]:
    buckets: dict[str, list[int]] = {key: [] for key in PROFILE_INDEX_SIGNAL_FIELDS}
    for row in signal_rows:
        for key in buckets:
            buckets[key].append(max(0, int(row.get(key, 0))))
    return {key: percentile(values, 0.95) for key, values in buckets.items()}


def compute_profile_index_scores(signals: Mapping[str, int], thresholds: Mapping[str, float]) -> dict[str, float]:
    video = log_p95_score(int(signals.get("video_count", 0)), float(thresholds.get("video_count", 0.0)))
    comment = log_p95_score(int(signals.get("comment_count", 0)), float(thresholds.get("comment_count", 0.0)))
    reply = log_p95_score(int(signals.get("reply_count", 0)), float(thresholds.get("reply_count", 0.0)))
    coverage = log_p95_score(int(signals.get("follower_count", 0)), float(thresholds.get("follower_count", 0.0)))
    recognition = log_p95_score(int(signals.get("comment_like_sum", 0)), float(thresholds.get("comment_like_sum", 0.0)))
    network = log_p95_score(int(signals.get("edge_degree", 0)), float(thresholds.get("edge_degree", 0.0)))
    activity = 0.25 * video + 0.45 * comment + 0.30 * reply
    local = 0.60 * network + 0.40 * recognition
    return {
        "activity_score": activity,
        "activity_video_score": video,
        "activity_publish_score": video,
        "activity_comment_score": comment,
        "activity_reply_score": reply,
        "global_influence_score": coverage,
        "local_influence_score": local,
        "local_network_score": network,
        "local_recognition_score": recognition,
        "influence_coverage_score": coverage,
        "influence_recognition_score": recognition,
        "influence_network_score": network,
    }


def normalization_scores(signal_rows: Sequence[Mapping[str, int]], method: str) -> dict[str, list[float]]:
    values_by_field = {
        field: [max(0, int(row.get(field, 0))) for row in signal_rows]
        for field in PROFILE_INDEX_SIGNAL_FIELDS
    }
    if method == "rank_percentile":
        return {field: rank_percentile_scores(values) for field, values in values_by_field.items()}
    quantile_by_method = {"log1p_p90": 0.90, "log1p_p95": 0.95, "log1p_p99": 0.99}
    if method not in quantile_by_method:
        raise ValueError(f"unknown normalization method: {method}")
    normalized: dict[str, list[float]] = {}
    for field, values in values_by_field.items():
        threshold = percentile(values, quantile_by_method[method])
        normalized[field] = [log_percentile_score(value, threshold) for value in values]
    return normalized


def composite_profile_scores(
    normalized: Mapping[str, list[float]],
    activity_weights: tuple[float, float, float] = ACTIVITY_WEIGHT_VARIANTS["activity_base"],
    local_weights: tuple[float, float] = LOCAL_INFLUENCE_WEIGHT_VARIANTS["local_base"],
) -> dict[str, list[float]]:
    video_scores = normalized["video_count"]
    comment_scores = normalized["comment_count"]
    reply_scores = normalized["reply_count"]
    follower_scores = normalized["follower_count"]
    network_scores = normalized["edge_degree"]
    recognition_scores = normalized["comment_like_sum"]
    activity = [
        activity_weights[0] * video + activity_weights[1] * comment + activity_weights[2] * reply
        for video, comment, reply in zip(video_scores, comment_scores, reply_scores, strict=True)
    ]
    local = [
        local_weights[0] * network + local_weights[1] * recognition
        for network, recognition in zip(network_scores, recognition_scores, strict=True)
    ]
    return {
        "activity_score": activity,
        "global_influence_score": list(follower_scores),
        "local_influence_score": local,
    }


def spearman_correlation(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("spearman inputs must have equal length")
    if not left:
        return 0.0
    left_ranks = rank_percentile_scores([int(round(value * 1_000_000)) for value in left])
    right_ranks = rank_percentile_scores([int(round(value * 1_000_000)) for value in right])
    mean_left = sum(left_ranks) / len(left_ranks)
    mean_right = sum(right_ranks) / len(right_ranks)
    numerator = sum((lval - mean_left) * (rval - mean_right) for lval, rval in zip(left_ranks, right_ranks, strict=True))
    left_var = sum((value - mean_left) ** 2 for value in left_ranks)
    right_var = sum((value - mean_right) ** 2 for value in right_ranks)
    if left_var <= 0 or right_var <= 0:
        return 1.0 if left == right else 0.0
    return numerator / math.sqrt(left_var * right_var)


def top_overlap(left: list[float], right: list[float], fraction: float) -> float:
    if len(left) != len(right):
        raise ValueError("top-overlap inputs must have equal length")
    if not left:
        return 0.0
    k = max(1, math.ceil(len(left) * fraction))
    left_top = {idx for idx, _value in sorted(enumerate(left), key=lambda item: (-item[1], item[0]))[:k]}
    right_top = {idx for idx, _value in sorted(enumerate(right), key=lambda item: (-item[1], item[0]))[:k]}
    return len(left_top & right_top) / k


def distribution_stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {key: 0.0 for key in ["mean", "variance", "min", "max", "p25", "p50", "p75", "p90", "p95", "p99"]}
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    scaled = sorted(int(round(value * 1_000_000)) for value in values)
    return {
        "mean": mean,
        "variance": variance,
        "min": min(values),
        "max": max(values),
        "p25": percentile(scaled, 0.25) / 1_000_000,
        "p50": percentile(scaled, 0.50) / 1_000_000,
        "p75": percentile(scaled, 0.75) / 1_000_000,
        "p90": percentile(scaled, 0.90) / 1_000_000,
        "p95": percentile(scaled, 0.95) / 1_000_000,
        "p99": percentile(scaled, 0.99) / 1_000_000,
    }


def profile_index_robustness_report(signal_rows: Sequence[Mapping[str, int]]) -> dict[str, Any]:
    base_normalized = normalization_scores(signal_rows, "log1p_p95")
    base_scores = composite_profile_scores(base_normalized)
    variants: dict[str, dict[str, Any]] = {}
    for method in NORMALIZATION_VARIANTS:
        normalized = normalization_scores(signal_rows, method)
        variants[f"normalization:{method}"] = {"method": method, "scores": composite_profile_scores(normalized)}
    for name, weights in ACTIVITY_WEIGHT_VARIANTS.items():
        variants[f"activity_weights:{name}"] = {
            "activity_weights": weights,
            "scores": composite_profile_scores(base_normalized, activity_weights=weights),
        }
    for name, weights in LOCAL_INFLUENCE_WEIGHT_VARIANTS.items():
        variants[f"local_weights:{name}"] = {
            "local_weights": weights,
            "scores": composite_profile_scores(base_normalized, local_weights=weights),
        }
    metrics: dict[str, Any] = {}
    for score_name, base_values in base_scores.items():
        comparisons: dict[str, Any] = {}
        for variant_name, variant in variants.items():
            variant_scores = cast(dict[str, list[float]], variant["scores"])
            variant_values = variant_scores[score_name]
            rho = spearman_correlation(base_values, variant_values)
            top10 = top_overlap(base_values, variant_values, 0.10)
            top20 = top_overlap(base_values, variant_values, 0.20)
            comparisons[variant_name] = {
                "spearman": round(rho, 6),
                "top10_overlap": round(top10, 6),
                "top20_overlap": round(top20, 6),
                "robust": rho >= 0.90 and top10 >= 0.80,
                "distribution": {key: round(value, 6) for key, value in distribution_stats(variant_values).items()},
            }
        metrics[score_name] = {
            "base_distribution": {key: round(value, 6) for key, value in distribution_stats(base_values).items()},
            "comparisons": comparisons,
            "robust": all(item["robust"] for item in comparisons.values()),
        }
    thresholds_by_quantile = {
        label: {
            field: round(percentile([max(0, int(row.get(field, 0))) for row in signal_rows], quantile), 6)
            for field in PROFILE_INDEX_SIGNAL_FIELDS
        }
        for label, quantile in {"p90": 0.90, "p95": 0.95, "p99": 0.99}.items()
    }
    return {
        "created_at": now_iso(),
        "profile_index_method": PROFILE_INDEX_METHOD,
        "profile_index_variant": PROFILE_INDEX_VARIANT,
        "proxy_semantics": "observable proxy only; not true psychological traits, true causal influence, or a direct DCI/Feigua/Newrank clone",
        "user_count": len(signal_rows),
        "thresholds": thresholds_by_quantile,
        "robust_rule": {"spearman_min": 0.90, "top10_overlap_min": 0.80},
        "metrics": metrics,
    }


def write_profile_index_robustness_report(processed_dir: Path, report: Mapping[str, Any]) -> None:
    json_path = processed_dir / "profile_index_robustness_report.json"
    md_path = processed_dir / "profile_index_robustness_report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Profile index robustness report",
        "",
        f"- method: `{report.get('profile_index_method')}`",
        f"- base variant: `{report.get('profile_index_variant')}`",
        f"- users: {report.get('user_count')}",
        f"- semantics: {report.get('proxy_semantics')}",
        "- robust rule: Spearman >= 0.90 and Top10% overlap >= 80%",
        "",
        "## Signal thresholds",
        "",
        "| quantile | video_count | comment_count | reply_count | follower_count | edge_degree | comment_like_sum |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    raw_thresholds: Any = report.get("thresholds")
    thresholds: Mapping[str, Any] = raw_thresholds if isinstance(raw_thresholds, dict) else {}
    for label in ["p90", "p95", "p99"]:
        raw_row: Any = thresholds.get(label, {})
        row: Mapping[str, Any] = raw_row if isinstance(raw_row, dict) else {}
        lines.append(
            "| {label} | {video_count} | {comment_count} | {reply_count} | {follower_count} | {edge_degree} | {comment_like_sum} |".format(
                label=label,
                video_count=row.get("video_count", 0),
                comment_count=row.get("comment_count", 0),
                reply_count=row.get("reply_count", 0),
                follower_count=row.get("follower_count", 0),
                edge_degree=row.get("edge_degree", 0),
                comment_like_sum=row.get("comment_like_sum", 0),
            )
        )
    lines.extend(["", "## Robustness summary", "", "| score | robust comparisons | total comparisons | base mean | base variance |", "|---|---:|---:|---:|---:|"])
    raw_metrics: Any = report.get("metrics")
    metrics: Mapping[str, Any] = raw_metrics if isinstance(raw_metrics, dict) else {}
    for score_name, metric in sorted(metrics.items()):
        if not isinstance(metric, dict):
            continue
        raw_comparisons: Any = metric.get("comparisons")
        comparisons: Mapping[str, Any] = raw_comparisons if isinstance(raw_comparisons, dict) else {}
        robust_count = sum(1 for value in comparisons.values() if isinstance(value, dict) and value.get("robust") is True)
        raw_base_distribution: Any = metric.get("base_distribution")
        base_distribution: Mapping[str, Any] = raw_base_distribution if isinstance(raw_base_distribution, dict) else {}
        lines.append(
            f"| {score_name} | {robust_count} | {len(comparisons)} | {base_distribution.get('mean', 0)} | {base_distribution.get('variance', 0)} |"
        )
    lines.extend(
        [
            "",
            "## Variant comparisons",
            "",
            "| score | variant | spearman | top10_overlap | top20_overlap | robust |",
            "|---|---|---:|---:|---:|---|",
        ]
    )
    for score_name, metric in sorted(metrics.items()):
        if not isinstance(metric, dict):
            continue
        raw_comparisons = metric.get("comparisons")
        comparisons = raw_comparisons if isinstance(raw_comparisons, dict) else {}
        for variant_name, comparison in sorted(comparisons.items()):
            if not isinstance(comparison, dict):
                continue
            lines.append(
                f"| {score_name} | {variant_name} | {comparison.get('spearman', 0)} | {comparison.get('top10_overlap', 0)} | {comparison.get('top20_overlap', 0)} | {comparison.get('robust', False)} |"
            )
    lines.append("\nAggregate-only report. It excludes user text/profile details, credential material, request headers, session values, and provider response details.\n")
    md_path.write_text("\n".join(lines), encoding="utf-8")


def recompute_profile_indices_in_place(processed_dir: Path) -> dict[str, Any]:
    users = read_csv(processed_dir / "users.csv")
    targets = read_csv(processed_dir / "profile_target_users.csv")
    existing_abm = {row.get("user_id", ""): row for row in read_csv(processed_dir / "abm_user_profiles.csv")}
    if not users:
        raise ValueError(f"missing or empty users.csv: {processed_dir / 'users.csv'}")
    if not targets:
        raise ValueError(f"missing or empty profile_target_users.csv: {processed_dir / 'profile_target_users.csv'}")
    targets_by_user = {row.get("user_id", ""): row for row in targets if row.get("user_id")}
    signal_rows: list[dict[str, int]] = []
    prepared: list[tuple[dict[str, str], dict[str, str], dict[str, int]]] = []
    for user in users:
        uid = user.get("user_id", "")
        target = targets_by_user.get(uid, {})
        signals = profile_index_signals(target, user)
        prepared.append((user, target, signals))
        signal_rows.append(signals)
    thresholds = compute_profile_index_thresholds(signal_rows)
    updated_users: list[dict[str, Any]] = []
    updated_profiles: list[dict[str, Any]] = []
    updated_abm: list[dict[str, Any]] = []
    for user, target, _signals in prepared:
        uid = user.get("user_id", "")
        previous = existing_abm.get(uid, {})
        fetch_status = user.get("profile_fetch_status") or target.get("profile_fetch_status") or "success"
        profile_source = user.get("profile_source") or previous.get("profile_source") or "live_current"
        row = build_abm_row(target, user, profile_source, fetch_status, profile_index_thresholds=thresholds)
        for field in ["user_type", "interest_tags"]:
            if previous.get(field, "") not in ("", None):
                row[field] = previous[field]
        row["profile_source"] = profile_source
        row["profile_fetch_status"] = fetch_status
        if previous.get("attribute_provenance"):
            provenance = row["attribute_provenance"]
            provenance["previous_profile_index_provenance_replaced"] = True
            row["attribute_provenance"] = provenance
        for field in [
            "activity_score",
            "activity_video_score",
            "activity_comment_score",
            "activity_reply_score",
            "global_influence_score",
            "local_influence_score",
            "local_network_score",
            "local_recognition_score",
            "profile_index_method",
            "profile_index_variant",
        ]:
            user[field] = row.get(field, "")
        updated_users.append(user)
        updated_profiles.append({field: row.get(field, "") for field in PROFILE_COLUMNS})
        updated_abm.append({field: row.get(field, "") for field in ABM_COLUMNS})
    write_csv(processed_dir / "users.csv", USER_COLUMNS + ["profile_source", "profile_fetch_status"], updated_users)
    write_csv(processed_dir / "profiles.csv", PROFILE_COLUMNS, updated_profiles)
    write_csv(processed_dir / "abm_user_profiles.csv", ABM_COLUMNS, updated_abm)
    robustness = profile_index_robustness_report(signal_rows)
    write_profile_index_robustness_report(processed_dir, robustness)
    report = load_json(processed_dir / "final_collection_report.json")
    if report:
        report["profile_index_method"] = PROFILE_INDEX_METHOD
        report["profile_index_variant"] = PROFILE_INDEX_VARIANT
        report["profile_index_thresholds"] = {key: round(float(value), 6) for key, value in thresholds.items()}
        report["profile_index_robustness_report"] = str(processed_dir / "profile_index_robustness_report.json")
        report["profile_index_proxy_semantics"] = "observable proxy only; not true psychological traits or true causal influence"
        report["updated_at"] = now_iso()
        (processed_dir / "final_collection_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "users": len(updated_users),
        "profiles": len(updated_profiles),
        "abm_user_profiles": len(updated_abm),
        "profile_index_method": PROFILE_INDEX_METHOD,
        "profile_index_thresholds": {key: round(float(value), 6) for key, value in thresholds.items()},
        "profile_index_robustness_report": str(processed_dir / "profile_index_robustness_report.json"),
    }


def recompute_profile_target_metrics_in_place(processed_dir: Path) -> dict[str, Any]:
    targets = read_csv(processed_dir / "profile_target_users.csv")
    if not targets:
        raise ValueError(f"missing or empty profile_target_users.csv: {processed_dir / 'profile_target_users.csv'}")
    metrics_by_user, source_meta = source_role_and_metrics(processed_dir)
    updated_targets: list[dict[str, Any]] = []
    changed_users = 0
    before_comment_sum = 0
    before_reply_sum = 0
    after_comment_sum = 0
    after_reply_sum = 0
    role_counts: Counter[str] = Counter()
    priority_counts: Counter[str] = Counter()
    for target in targets:
        uid = target.get("user_id", "")
        metrics = metrics_by_user.get(uid, {})
        updated: dict[str, Any] = dict(target)
        before_comment_sum += parse_int(target.get("comment_count"))
        before_reply_sum += parse_int(target.get("reply_count"))
        for field in ["comment_count", "reply_count", "edge_degree", "in_degree", "out_degree", "comment_like_sum"]:
            updated[field] = parse_int(metrics.get(field))
        updated["user_role"] = user_role(metrics)
        updated["priority_tier"] = priority_tier(metrics)
        after_comment_sum += parse_int(updated.get("comment_count"))
        after_reply_sum += parse_int(updated.get("reply_count"))
        role_counts[str(updated["user_role"])] += 1
        priority_counts[str(updated["priority_tier"])] += 1
        if any(str(updated.get(field, "")) != str(target.get(field, "")) for field in ["comment_count", "reply_count", "edge_degree", "in_degree", "out_degree", "comment_like_sum", "user_role", "priority_tier"]):
            changed_users += 1
        updated_targets.append(updated)
    write_csv(processed_dir / "profile_target_users.csv", PROFILE_FIELDNAMES, updated_targets)
    audit = {
        "updated_at": now_iso(),
        "method": "recompute_profile_target_metrics_from_processed_comments_v1",
        "bugfix": "treat parent_comment_id values '' and '0' as no parent unless comment_level is reply",
        "source_meta": source_meta,
        "target_users": len(updated_targets),
        "changed_users": changed_users,
        "before_comment_count_sum": before_comment_sum,
        "after_comment_count_sum": after_comment_sum,
        "before_reply_count_sum": before_reply_sum,
        "after_reply_count_sum": after_reply_sum,
        "user_role_counts": dict(sorted(role_counts.items())),
        "priority_tier_counts": dict(sorted(priority_counts.items())),
    }
    (processed_dir / "profile_target_metrics_recompute_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    return audit


def split_ids(value: str) -> list[str]:
    if not value:
        return []
    raw = value.strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        return [str(item) for item in parsed if str(item)]
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    return [part.strip().strip("'\"") for part in re.split(r"[;,]", raw) if part.strip().strip("'\"")]


def parse_tags(value: str) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = None
    tags: list[str] = []
    if isinstance(parsed, list):
        tags = [str(item).lstrip("#") for item in parsed if str(item).strip()]
    else:
        tags = [part.strip().lstrip("#") for part in re.split(r"[;,|]", value) if part.strip()]
    return [tag for tag in tags if tag]


def walk_values(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_values(child)


def find_user_id_near_sec(value: Any, sec: str) -> str:
    if isinstance(value, dict):
        if str(value.get("sec_user_id") or value.get("sec_uid") or "") == sec:
            uid = value.get("user_id") or value.get("uid") or value.get("id")
            if uid:
                return str(uid)
        for child in value.values():
            found = find_user_id_near_sec(child, sec)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_user_id_near_sec(child, sec)
            if found:
                return found
    return ""


def extract_explicit_sec_uids(rows: Iterable[dict[str, Any]], source: str) -> dict[str, tuple[str, str]]:
    found: dict[str, tuple[str, str]] = {}
    for row in rows:
        for value in walk_values(row):
            if not isinstance(value, dict):
                continue
            sec = value.get("sec_user_id") or value.get("sec_uid")
            if not sec:
                continue
            uid = value.get("user_id") or value.get("uid") or value.get("id") or find_user_id_near_sec(row, str(sec))
            if uid:
                found.setdefault(str(uid), (str(sec), source))
    return found


def iter_explicit_sec_uid_pairs(row: dict[str, Any]) -> Iterable[tuple[str, str]]:
    """Yield only explicitly labeled uid -> sec_uid/sec_user_id pairs from a raw row."""

    for value in walk_values(row):
        if not isinstance(value, dict):
            continue
        sec = value.get("sec_user_id") or value.get("sec_uid")
        if not sec:
            continue
        uid = value.get("user_id") or value.get("uid") or value.get("id") or find_user_id_near_sec(row, str(sec))
        if uid:
            yield str(uid), str(sec)


def iter_evidence_files(run_dir: Path) -> Iterable[tuple[Path, str]]:
    for filename, source in RAW_SEC_UID_FILES:
        path = run_dir / filename
        if path.exists():
            yield path, source
    page_roots = [run_dir / "pages", *sorted(run_dir.glob("pages_premerge_backup_*"))]
    for page_root in page_roots:
        if not page_root.is_dir():
            continue
        for path in sorted(page_root.glob("*.json")):
            source = next((value for prefix, value in RAW_SEC_UID_PAGE_SOURCES.items() if path.name.startswith(prefix)), "")
            if source:
                yield path, source


def normalize_profile_payload(row: dict[str, Any]) -> dict[str, Any]:
    missing: dict[str, list[str]] = defaultdict(list)
    user = normalize_user(row, missing).model_dump()
    return user


def extract_user_items(result: Any) -> list[dict[str, Any]]:
    if not isinstance(result, dict):
        return []
    for key in ("users", "user_list", "profiles", "items", "list"):
        value = result.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    data = result.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        nested = extract_user_items(data)
        if nested:
            return nested
    return [result] if any(key in result for key in ("user_id", "uid", "id", "sec_user_id", "sec_uid", "user")) else []


@dataclass
class HistoricalProfile:
    user: dict[str, Any]
    source: str
    raw_payload: dict[str, Any] | None = None


@dataclass
class CollectionStats:
    attempted: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    partial: bool = False
    partial_reason: str = ""
    quota_or_rate_limited: bool = False
    endpoint_call_counts: dict[str, int] | None = None
    http_status_counts: dict[str, int] | None = None
    rejected_by_endpoint_status: dict[str, int] | None = None
    cost_guard_triggered: bool = False
    cost_guard_reason: str = ""
    profile_api_requested: str = "cost-safe"
    profile_api_resolved: str = "handler"


@dataclass(frozen=True)
class ProfileErrorClassification:
    category: str
    http_status: str = ""
    quota_or_rate_limited: bool = False
    retryable: bool = False


@dataclass(frozen=True)
class SecUidEvidence:
    user_id: str
    sec_user_id: str
    source: str
    run_id: str
    path: str
    priority: int
    order: int

    @property
    def provenance(self) -> str:
        return f"{self.source}:{self.run_id}"


@dataclass
class SecUidEvidenceIndex:
    evidence: dict[str, SecUidEvidence]
    audit: dict[str, Any]


def classify_profile_error(message: str) -> ProfileErrorClassification:
    text = message.lower()
    http_status = re.search(r"\bhttp\s+(\d{3})\b", text)
    status = http_status.group(1) if http_status else ""
    if not status:
        response_code = re.search(r'"code"\s*:\s*(\d{3})', text)
        status = response_code.group(1) if response_code else ""
    if status in {"402"}:
        return ProfileErrorClassification("quota_or_balance", status, quota_or_rate_limited=True)
    if status in {"429"}:
        return ProfileErrorClassification("rate_limit", status, quota_or_rate_limited=True)
    if status == "400":
        return ProfileErrorClassification("provider_bad_request", status)
    if status:
        return ProfileErrorClassification(
            "provider_transient" if status.startswith("5") else "provider_error",
            status,
            retryable=status.startswith("5"),
        )
    if any(token in text for token in ["insufficient balance", "paid quota", "quota不足", "余额不足"]):
        return ProfileErrorClassification("quota_or_balance", quota_or_rate_limited=True)
    if any(token in text for token in ["rate limit", "too many requests"]):
        return ProfileErrorClassification("rate_limit", quota_or_rate_limited=True)
    if "identity_mismatch_or_empty_profile_response" in text:
        return ProfileErrorClassification("identity_mismatch_or_empty_response")
    return ProfileErrorClassification("provider_error")


def is_quota_error(message: str) -> bool:
    return classify_profile_error(message).quota_or_rate_limited


def increment_counter(counter: dict[str, int] | None, key: str) -> None:
    if counter is not None:
        counter[key] = counter.get(key, 0) + 1


def record_profile_error_stats(stats: CollectionStats, *, endpoint: str, classification: ProfileErrorClassification) -> None:
    if stats.http_status_counts is None:
        stats.http_status_counts = {}
    if stats.rejected_by_endpoint_status is None:
        stats.rejected_by_endpoint_status = {}
    status_key = classification.http_status or classification.category
    increment_counter(stats.http_status_counts, status_key)
    increment_counter(stats.rejected_by_endpoint_status, f"{endpoint}:{status_key}")


def endpoint_from_error_message(message: str) -> str:
    match = re.search(r"TikHub request failed for ([A-Za-z0-9_]+):", message)
    return match.group(1) if match else "unknown"


def classify_status_rows(statuses: Mapping[str, Mapping[str, str]]) -> tuple[dict[str, int], dict[str, int], int, str]:
    http_status_counts: Counter[str] = Counter()
    rejected_by_endpoint_status: Counter[str] = Counter()
    quota_stopped_profiles = 0
    quota_stop_reason = ""
    for row in statuses.values():
        if row.get("status") not in {"failed", "quota_stopped"}:
            continue
        classification = classify_profile_error(str(row.get("error") or ""))
        status_key = str(row.get("http_status") or classification.http_status or row.get("error_category") or classification.category)
        endpoint = str(row.get("endpoint") or endpoint_from_error_message(str(row.get("error") or "")))
        http_status_counts[status_key] += 1
        rejected_by_endpoint_status[f"{endpoint}:{status_key}"] += 1
        if row.get("status") == "quota_stopped":
            quota_stopped_profiles += 1
            quota_stop_reason = str(row.get("error") or quota_stop_reason)
    return dict(sorted(http_status_counts.items())), dict(sorted(rejected_by_endpoint_status.items())), quota_stopped_profiles, quota_stop_reason


def recommended_resume_command() -> str:
    return "\n".join(
        [
            ". .venv/bin/activate",
            "TIKHUB_QPS=2 TIKHUB_BACKOFF_SECONDS=2 TIKHUB_MAX_RETRIES=0 \\",
            "python scripts/collect_jinjiang_user_profiles.py \\",
            f"  --source-run {DEFAULT_SOURCE_RUN} \\",
            '  --sec-uid-evidence-glob "jinjiang-top10-caption-hashtag-all-comments-excluding-safety-20260617T140519Z*" \\',
            "  --sec-uid-evidence-run data/raw/tikhub/douyin/jinjiang_hotel/jinjiang-top12-jian-comments-replies-live-20260620T072706Z \\",
            "  --sec-uid-evidence-run data/raw/tikhub/douyin/jinjiang_hotel/jinjiang-top12-jian-video-metadata-live-20260620T072428Z \\",
            "  --sec-uid-evidence-run data/raw/tikhub/douyin/jinjiang_hotel/jinjiang-top10-jinjiang-only-video-metadata-unbounded-20260617T095743Z \\",
            "  --output-run-id jinjiang-profile-expansion-derived-20260622T151059Z-batch-full \\",
            "  --env-file .env \\",
            "  --profile-api handler \\",
            "  --limit-profile unbounded \\",
            "  --resume \\",
            "  --retry-failed-profiles",
        ]
    )


def mark_quota_stop(stats: CollectionStats) -> None:
    stats.partial = True
    stats.partial_reason = "quota_or_rate_limit"
    stats.quota_or_rate_limited = True


def mark_cost_guard(stats: CollectionStats, reason: str) -> None:
    stats.cost_guard_triggered = True
    stats.cost_guard_reason = reason

def classify_source_sec(user_id: str, sec: str) -> tuple[str, str]:
    if not sec:
        return "", "missing"
    if sec == user_id:
        return sec, "placeholder"
    return sec, "source_users"


def source_role_and_metrics(source_run: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    videos = read_csv(source_run / "videos.csv")
    comments = read_csv(source_run / "comments.csv")
    edges = read_csv(source_run / "edges.csv")
    text_items = read_csv(source_run / "text_items.csv")
    by_user: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "roles": set(),
            "comment_count": 0,
            "reply_count": 0,
            "comment_like_sum": 0,
            "in_degree": 0,
            "out_degree": 0,
            "edge_degree": 0,
            "interest_tags": set(),
        }
    )
    creators = {row.get("creator_user_id", "") for row in videos if row.get("creator_user_id")}
    for row in videos:
        uid = row.get("creator_user_id", "")
        if uid:
            by_user[uid]["roles"].add("creator")
            by_user[uid]["interest_tags"].update(parse_tags(row.get("hashtags", "")))
    for row in comments:
        uid = row.get("commenter_user_id", "")
        if not uid:
            continue
        level = str(row.get("comment_level") or "").strip().lower()
        parent_comment_id = row.get("parent_comment_id")
        if level == "reply" or (level not in {"comment", "reply"} and has_parent_comment_id(parent_comment_id)):
            by_user[uid]["roles"].add("replier")
            by_user[uid]["reply_count"] += 1
        else:
            by_user[uid]["roles"].add("commenter")
            by_user[uid]["comment_count"] += 1
        by_user[uid]["comment_like_sum"] += parse_int(row.get("like_count"))
        for mentioned in split_ids(row.get("mentioned_user_ids", "")):
            by_user[mentioned]["roles"].add("mentioned")
    for row in edges:
        source = row.get("source", "")
        target = row.get("target", "")
        weight = max(1, parse_int(row.get("weight")))
        if source:
            by_user[source]["out_degree"] += weight
        if target:
            by_user[target]["in_degree"] += weight
    for _uid, data in by_user.items():
        data["edge_degree"] = data["in_degree"] + data["out_degree"]
    for row in text_items:
        uid = row.get("user_id", "")
        text = row.get("text", "")
        if uid and text:
            for token in ["锦江", "酒店", "旅行", "住宿", "绿色", "都城", "锦江之星"]:
                if token in text:
                    by_user[uid]["interest_tags"].add(token)
    meta = {"creator_count": len(creators), "videos": len(videos), "comments": len(comments), "edges": len(edges)}
    return by_user, meta


def priority_tier(metrics: Mapping[str, Any]) -> str:
    roles = set(metrics.get("roles", set()))
    if "creator" in roles:
        return "creator"
    if parse_int(metrics.get("edge_degree")) >= 5 or parse_int(metrics.get("comment_like_sum")) >= 20:
        return "central_user"
    if parse_int(metrics.get("comment_count")) + parse_int(metrics.get("reply_count")) >= 2:
        return "active_commenter"
    return "regular"


def user_role(metrics: Mapping[str, Any]) -> str:
    roles = sorted(metrics.get("roles", set()))
    if not roles:
        return "observed"
    return roles[0] if len(roles) == 1 else "mixed"


def resolve_raw_evidence_run(value: Path, raw_root: Path) -> Path:
    """Resolve a raw evidence run argument as either a path or a RAW_ROOT run id."""

    candidate = value if value.is_absolute() or len(value.parts) > 1 else raw_root / value
    raw_root_resolved = raw_root.resolve()
    candidate_resolved = candidate.resolve() if candidate.exists() else candidate.absolute()
    try:
        candidate_resolved.relative_to(raw_root_resolved)
    except ValueError as exc:
        raise ValueError(f"raw evidence run must be under {raw_root}: {value}") from exc
    return candidate


def resolve_raw_evidence_runs(
    *,
    raw_root: Path,
    source_run: Path,
    source_raw_run: Path | None,
    evidence_runs: Iterable[Path] = (),
    evidence_globs: Iterable[str] = (),
) -> list[Path]:
    """Return ordered, root-limited raw evidence runs.

    Order is deterministic: source raw run first for backward compatibility,
    then repeated ``--sec-uid-evidence-run`` values in CLI order, then sorted
    matches for each ``--sec-uid-evidence-glob`` rooted at ``raw_root``.
    """

    ordered: list[Path] = [resolve_raw_evidence_run(source_raw_run, raw_root) if source_raw_run else raw_root / source_run.name]
    ordered.extend(resolve_raw_evidence_run(path, raw_root) for path in evidence_runs)
    raw_root_resolved = raw_root.resolve()
    for pattern in evidence_globs:
        for path in sorted(raw_root.glob(pattern)):
            try:
                path.resolve().relative_to(raw_root_resolved)
            except ValueError:
                continue
            ordered.append(path)
    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in ordered:
        normalized = path.resolve() if path.exists() else path
        if normalized not in seen:
            seen.add(normalized)
            deduped.append(path)
    return deduped


def build_sec_uid_evidence_index(evidence_runs: Iterable[Path], current_user_ids: set[str]) -> SecUidEvidenceIndex:
    """Index explicit raw sec_uid evidence from multiple run directories.

    Conflict policy: lower file priority wins (comments, replies, video details,
    raw profiles), then earlier run order wins. Conflicting alternatives are
    counted in the audit and never printed with raw payload excerpts.
    """

    indexed: dict[str, SecUidEvidence] = {}
    candidate_counts: Counter[str] = Counter()
    accepted_counts: Counter[str] = Counter()
    conflicts: Counter[str] = Counter()
    scanned_files: list[str] = []
    scanned_runs: list[str] = []
    malformed_jsonl_lines = 0
    missing_run_paths: list[str] = []
    rejected_not_current_user = 0
    rejected_empty_or_placeholder = 0
    run_list = list(evidence_runs)
    for run_order, run_dir in enumerate(run_list):
        if not run_dir.exists():
            missing_run_paths.append(str(run_dir))
            continue
        if not run_dir.is_dir():
            missing_run_paths.append(str(run_dir))
            continue
        scanned_runs.append(str(run_dir))
        run_id = run_dir.name
        for path, source in iter_evidence_files(run_dir):
            scanned_files.append(str(path))
            rows, malformed = iter_jsonl_objects(path) if path.suffix == ".jsonl" else iter_json_objects(path)
            malformed_jsonl_lines += malformed
            for row in rows:
                for uid, sec in iter_explicit_sec_uid_pairs(row):
                    if uid not in current_user_ids:
                        rejected_not_current_user += 1
                        continue
                    if not sec or sec == uid:
                        rejected_empty_or_placeholder += 1
                        continue
                    provenance = f"{source}:{run_id}"
                    candidate_counts[provenance] += 1
                    candidate = SecUidEvidence(
                        user_id=uid,
                        sec_user_id=sec,
                        source=source,
                        run_id=run_id,
                        path=str(path),
                        priority=RAW_SEC_UID_SOURCE_PRIORITY.get(source, 99),
                        order=run_order,
                    )
                    existing = indexed.get(uid)
                    if existing is None:
                        indexed[uid] = candidate
                        accepted_counts[provenance] += 1
                        continue
                    if existing.sec_user_id == sec:
                        continue
                    conflicts[f"{existing.provenance}|{candidate.provenance}"] += 1
                    if (candidate.priority, candidate.order) < (existing.priority, existing.order):
                        accepted_counts[existing.provenance] -= 1
                        indexed[uid] = candidate
                        accepted_counts[provenance] += 1
    audit = {
        "created_at": now_iso(),
        "contract": {
            "accepted_fields": ["sec_uid", "sec_user_id"],
            "scope": "raw_root-limited evidence runs filtered to current source users",
            "flag_semantics": "--sec-uid-evidence-run accepts a path or run id under raw_root; --sec-uid-evidence-glob is rooted at raw_root and sorted; --source-raw-run is scanned first for compatibility.",
            "precedence": "first accepted evidence wins by file priority comments < replies < video_details < user_profiles, then CLI/glob run order; conflicts are aggregate-audited.",
            "privacy": "aggregate-only audit; no nickname, bio, signature, or raw payload excerpts.",
            "processed_historical_policy": "historical processed profiles may fill local output fields but do not promote a missing/placeholder sec_uid to live-callable confirmed evidence.",
        },
        "scanned_run_count": len(scanned_runs),
        "scanned_runs": scanned_runs,
        "missing_run_paths": missing_run_paths,
        "scanned_file_count": len(scanned_files),
        "scanned_files": scanned_files,
        "malformed_jsonl_lines": malformed_jsonl_lines,
        "raw_candidate_pairs": sum(candidate_counts.values()),
        "accepted_users": len(indexed),
        "accepted_by_source": {k: v for k, v in sorted(accepted_counts.items()) if v},
        "candidate_by_source": dict(sorted(candidate_counts.items())),
        "conflict_count": sum(conflicts.values()),
        "conflicts_by_source_pair": dict(sorted(conflicts.items())),
        "rejected_not_current_user": rejected_not_current_user,
        "rejected_empty_or_placeholder": rejected_empty_or_placeholder,
    }
    return SecUidEvidenceIndex(evidence=indexed, audit=audit)


def discover_current_raw_sec_uids(source_run: Path, raw_base: Path, source_raw_run: Path | None = None) -> dict[str, tuple[str, str]]:
    """Recover explicit sec_uid values from the source run's raw artifacts.

    By default the collector uses the repository convention that a processed run
    and its raw run share the same run id. Callers can override that convention
    with ``--source-raw-run`` when deriving from a copied/renamed processed run.
    Only explicit raw ``sec_uid``/``sec_user_id`` evidence is accepted.
    """

    raw_root = source_raw_run or raw_base / source_run.name
    found: dict[str, tuple[str, str]] = {}
    for filename, source in RAW_SEC_UID_FILES:
        found.update({k: v for k, v in extract_explicit_sec_uids(read_jsonl(raw_root / filename), source).items() if k not in found})
    return found




def has_observed_profile_signal(row: Mapping[str, Any]) -> bool:
    uid = str(row.get("user_id") or "")
    sec = str(row.get("sec_user_id") or row.get("sec_uid") or "")
    if sec and sec != uid:
        return True
    if str(row.get("nickname") or row.get("bio") or row.get("signature") or "").strip():
        return True
    if str(row.get("verified_type") or "").strip() not in {"", "0", "False", "false"}:
        return True
    return any(parse_int(row.get(key)) > 0 for key in ["follower_count", "following_count", "video_count", "aweme_count"])

def run_declares_no_profiles(run_dir: Path) -> bool:
    for name in ("profile_collection_report.json", "collection_report.json"):
        report = load_json(run_dir / name)
        if not report:
            continue
        if report.get("profiles_collected") is False:
            return True
        if name == "profile_collection_report.json" and parse_int(report.get("successful_profiles")) == 0:
            return True
    return False

def discover_historical_profiles(
    current_user_ids: set[str], processed_root: Path, raw_root: Path, *, exclude_processed_run: Path | None = None
) -> tuple[dict[str, HistoricalProfile], dict[str, tuple[str, str]]]:
    profiles: dict[str, HistoricalProfile] = {}
    secuids: dict[str, tuple[str, str]] = {}
    exclude_resolved = exclude_processed_run.resolve() if exclude_processed_run else None
    for path in sorted(processed_root.glob("*/profiles.csv")):
        if exclude_resolved and path.parent.resolve() == exclude_resolved:
            continue
        if run_declares_no_profiles(path.parent):
            continue
        for row in read_csv(path):
            uid = row.get("user_id", "")
            if uid in current_user_ids and uid not in profiles and has_observed_profile_signal(row):
                profiles[uid] = HistoricalProfile(user=dict(row), source=f"historical_processed_profiles:{path.parent.name}")
    for path in sorted(processed_root.glob("*/users.csv")):
        if exclude_resolved and path.parent.resolve() == exclude_resolved:
            continue
        if run_declares_no_profiles(path.parent):
            continue
        for row in read_csv(path):
            uid = row.get("user_id", "")
            sec = row.get("sec_user_id", "")
            if uid in current_user_ids and sec and sec != uid and uid not in secuids:
                secuids[uid] = (sec, f"historical_processed_users:{path.parent.name}")
            if uid in current_user_ids and uid not in profiles and has_observed_profile_signal(row):
                profiles[uid] = HistoricalProfile(user=dict(row), source=f"historical_processed_users:{path.parent.name}")
    for path in sorted(raw_root.glob("*/user_profiles.jsonl")):
        rows = read_jsonl(path)
        for uid, pair in extract_explicit_sec_uids(rows, f"historical_raw_profiles:{path.parent.name}").items():
            if uid in current_user_ids and uid not in secuids:
                secuids[uid] = pair
        for row in rows:
            for item in extract_user_items(row):
                user = normalize_profile_payload(item)
                uid = str(user.get("user_id") or "")
                if uid in current_user_ids and uid not in profiles and has_observed_profile_signal(user):
                    profiles[uid] = HistoricalProfile(user=user, source=f"historical_raw_profiles:{path.parent.name}", raw_payload=item)
    return profiles, secuids


def validate_scope(source_run: Path) -> dict[str, Any]:
    videos = read_csv(source_run / "videos.csv")
    manifest = read_csv(source_run / "target_video_manifest.csv")
    video_ids = {row.get("video_id", "") for row in videos}
    manifest_text = (source_run / "target_video_manifest.csv").read_text(encoding="utf-8", errors="ignore") if (source_run / "target_video_manifest.csv").exists() else ""
    videos_text = (source_run / "videos.csv").read_text(encoding="utf-8", errors="ignore") if (source_run / "videos.csv").exists() else ""
    report = load_json(source_run / "collection_report.json")
    return {
        "videos_count": len(videos),
        "manifest_count": len(manifest),
        "safety_excluded_video_ids_absent": sorted(SAFETY_EXCLUDED_VIDEO_IDS & video_ids) == [],
        "safety_excluded_present": sorted(SAFETY_EXCLUDED_VIDEO_IDS & video_ids),
        "binguan_absent_in_manifest_and_videos": "锦江宾馆" not in manifest_text and "锦江宾馆" not in videos_text,
        "linkong_binguan_absent_in_manifest_and_videos": "临空锦江宾馆" not in manifest_text and "临空锦江宾馆" not in videos_text,
        "jian_included": "锦江都城酒店吉安" in manifest_text or "锦江都城酒店吉安" in videos_text,
        "source_profiles_collected": report.get("profiles_collected", False),
    }


def build_profile_targets(
    source_run: Path,
    processed_root: Path,
    raw_root: Path,
    *,
    source_raw_run: Path | None = None,
    sec_uid_evidence_runs: Iterable[Path] = (),
    sec_uid_evidence_globs: Iterable[str] = (),
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, HistoricalProfile]]:
    users = read_csv(source_run / "users.csv")
    if not users:
        raise ValueError(f"missing or empty users.csv: {source_run / 'users.csv'}")
    metrics_by_user, source_meta = source_role_and_metrics(source_run)
    user_ids = {row.get("user_id", "") for row in users if row.get("user_id")}
    evidence_run_paths = resolve_raw_evidence_runs(
        raw_root=raw_root,
        source_run=source_run,
        source_raw_run=source_raw_run,
        evidence_runs=sec_uid_evidence_runs,
        evidence_globs=sec_uid_evidence_globs,
    )
    evidence_index = build_sec_uid_evidence_index(evidence_run_paths, user_ids)
    effective_source_raw_run = evidence_run_paths[0] if evidence_run_paths else raw_root / source_run.name
    historical_profiles, historical_secs = discover_historical_profiles(user_ids, processed_root, raw_root, exclude_processed_run=source_run)
    rows: list[dict[str, Any]] = []
    sec_source_counts: Counter[str] = Counter()
    role_counts: Counter[str] = Counter()
    placeholder_count = 0
    missing_count = 0
    confirmed_count = 0
    for row in users:
        uid = row.get("user_id", "")
        if not uid:
            continue
        sec, source = classify_source_sec(uid, row.get("sec_user_id", ""))
        if source in {"missing", "placeholder"} and uid in evidence_index.evidence:
            evidence = evidence_index.evidence[uid]
            sec, source = evidence.sec_user_id, evidence.provenance
        if source == "placeholder":
            placeholder_count += 1
            fetch_status = "skipped"
            skip_reason = "placeholder_sec_user_id"
            confidence = "placeholder"
        elif source == "missing":
            missing_count += 1
            fetch_status = "skipped"
            skip_reason = "missing_sec_user_id"
            confidence = "missing"
        else:
            confirmed_count += 1
            fetch_status = "pending"
            skip_reason = ""
            confidence = "confirmed_equal_user_id" if sec == uid else "confirmed"
        metrics = metrics_by_user.get(uid, {})
        role = user_role(metrics)
        role_counts[role] += 1
        sec_source_counts[source] += 1
        rows.append(
            {
                "user_id": uid,
                "sec_user_id": sec,
                "sec_user_id_source": source,
                "sec_user_id_confidence": confidence,
                "user_role": role,
                "comment_count": parse_int(metrics.get("comment_count")),
                "reply_count": parse_int(metrics.get("reply_count")),
                "edge_degree": parse_int(metrics.get("edge_degree")),
                "in_degree": parse_int(metrics.get("in_degree")),
                "out_degree": parse_int(metrics.get("out_degree")),
                "comment_like_sum": parse_int(metrics.get("comment_like_sum")),
                "priority_tier": priority_tier(metrics),
                "profile_fetch_status": fetch_status,
                "skip_reason": skip_reason,
                "_interest_tags": sorted(metrics.get("interest_tags", set())),
            }
        )
    tier_order = {"creator": 0, "central_user": 1, "active_commenter": 2, "regular": 3}
    rows.sort(key=lambda item: (tier_order.get(str(item["priority_tier"]), 9), -parse_int(item["edge_degree"]), -parse_int(item["comment_count"]) - parse_int(item["reply_count"]), str(item["user_id"])))
    audit = {
        "created_at": now_iso(),
        "source_dataset_path": str(source_run),
        "source_raw_run_path": str(effective_source_raw_run),
        "source_raw_run_contract": "Defaults to raw_root/source_run.name; override with --source-raw-run when the raw run id differs. Additional --sec-uid-evidence-run/glob values extend raw evidence recovery.",
        "sec_uid_evidence_audit": evidence_index.audit,
        "source_meta": source_meta,
        "target_users": len(rows),
        "source_unique_users": len(user_ids),
        "confirmed_sec_uid_users": confirmed_count,
        "placeholder_sec_uid_users": placeholder_count,
        "missing_sec_uid_users": missing_count,
        "sec_user_id_source_counts": dict(sorted(sec_source_counts.items())),
        "user_role_counts": dict(sorted(role_counts.items())),
        "historical_reusable_profiles": len(historical_profiles),
        "historical_sec_uid_users": len(historical_secs),
        "historical_sec_uid_policy": "historical processed sec_uid values are audited but do not promote missing/placeholder IDs to live-callable confirmed sec_uid without raw/source evidence.",
        "scope_checks": validate_scope(source_run),
    }
    return rows, audit, historical_profiles


def write_target_audit(processed_dir: Path, target_rows: list[dict[str, Any]], audit: Mapping[str, Any]) -> None:
    public_rows = [{k: v for k, v in row.items() if not k.startswith("_")} for row in target_rows]
    write_csv(processed_dir / "profile_target_users.csv", PROFILE_FIELDNAMES, public_rows)
    (processed_dir / "profile_target_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    raw_sec_uid_audit = audit.get("sec_uid_evidence_audit")
    sec_uid_audit: Mapping[str, Any] = cast(Mapping[str, Any], raw_sec_uid_audit) if isinstance(raw_sec_uid_audit, dict) else {}
    (processed_dir / "sec_uid_evidence_audit.json").write_text(json.dumps(sec_uid_audit, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Profile target audit",
        "",
        f"- source dataset: `{audit.get('source_dataset_path')}`",
        f"- target users: {audit.get('target_users')}",
        f"- confirmed sec_uid users: {audit.get('confirmed_sec_uid_users')}",
        f"- placeholder sec_uid users: {audit.get('placeholder_sec_uid_users')}",
        f"- missing sec_uid users: {audit.get('missing_sec_uid_users')}",
        f"- historical reusable profiles: {audit.get('historical_reusable_profiles')}",
        "",
        "## Role distribution",
        "",
        "| role | users |",
        "|---|---:|",
    ]
    for key, value in sorted((audit.get("user_role_counts") or {}).items()):
        lines.append(f"| {key} | {value} |")
    lines.extend(["", "## Sec uid source distribution", "", "| source | users |", "|---|---:|"])
    for key, value in sorted((audit.get("sec_user_id_source_counts") or {}).items()):
        lines.append(f"| {key} | {value} |")
    lines.append("\nNo nickname, bio, signature, token, cookie, or raw profile payload details are shown in this report.\n")
    (processed_dir / "profile_target_audit.md").write_text("\n".join(lines), encoding="utf-8")
    evidence_lines = [
        "# Sec uid evidence audit",
        "",
        "This audit is aggregate-only. It does not include nickname, bio, signature, raw payload excerpts, headers, tokens, cookies, or authorization values.",
        "",
        f"- scanned runs: {sec_uid_audit.get('scanned_run_count', 0)}",
        f"- scanned files: {sec_uid_audit.get('scanned_file_count', 0)}",
        f"- raw candidate pairs: {sec_uid_audit.get('raw_candidate_pairs', 0)}",
        f"- accepted users: {sec_uid_audit.get('accepted_users', 0)}",
        f"- conflict count: {sec_uid_audit.get('conflict_count', 0)}",
        f"- malformed JSONL lines: {sec_uid_audit.get('malformed_jsonl_lines', 0)}",
        f"- rejected non-current users: {sec_uid_audit.get('rejected_not_current_user', 0)}",
        "",
        "## Accepted evidence by provenance",
        "",
        "| provenance | users |",
        "|---|---:|",
    ]
    for key, value in sorted((sec_uid_audit.get("accepted_by_source") or {}).items()):
        evidence_lines.append(f"| {key} | {value} |")
    evidence_lines.extend(["", "## Conflict source pairs", "", "| source pair | conflicts |", "|---|---:|"])
    for key, value in sorted((sec_uid_audit.get("conflicts_by_source_pair") or {}).items()):
        evidence_lines.append(f"| {key} | {value} |")
    if not (sec_uid_audit.get("conflicts_by_source_pair") or {}):
        evidence_lines.append("| none | 0 |")
    evidence_lines.append("")
    (processed_dir / "sec_uid_evidence_audit.md").write_text("\n".join(evidence_lines), encoding="utf-8")


def load_statuses(raw_dir: Path) -> dict[str, dict[str, str]]:
    statuses: dict[str, dict[str, str]] = {}
    for row in read_csv(raw_dir / "profile_status.csv"):
        uid = row.get("user_id", "")
        if uid:
            statuses[uid] = row
    return statuses


def write_statuses(raw_dir: Path, statuses: Mapping[str, Mapping[str, Any]]) -> None:
    write_csv(raw_dir / "profile_status.csv", STATUS_COLUMNS, statuses.values())


def status_error_category(row: Mapping[str, str]) -> str:
    category = str(row.get("error_category") or "").strip()
    if category:
        return category
    error = str(row.get("error") or "")
    return classify_profile_error(error).category if error else ""


def classify_fetchable(target_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in target_rows if str(row.get("profile_fetch_status")) == "pending" and str(row.get("sec_user_id_confidence")) in {"confirmed", "confirmed_equal_user_id"}]


def profile_item_matches_target(item: dict[str, Any], target_user_id: str, requested_sec_user_id: str) -> bool:
    user = normalize_profile_payload(item)
    normalized_uid = str(user.get("user_id") or "")
    normalized_sec = str(user.get("sec_user_id") or "")
    if normalized_uid:
        return normalized_uid == target_user_id
    return bool(normalized_sec and normalized_sec == requested_sec_user_id)


def accepted_profile_items(result: Any, target_user_id: str, requested_sec_user_id: str) -> list[dict[str, Any]]:
    items = extract_user_items(result)
    accepted: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict) and profile_item_matches_target(item, target_user_id, requested_sec_user_id):
            accepted.append(item)
    return accepted


def chunks(rows: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    for index in range(0, len(rows), size):
        yield rows[index : index + size]


def record_profile_success(raw_dir: Path, statuses: dict[str, dict[str, str]], row: dict[str, Any], item: dict[str, Any], response: Any | None = None) -> None:
    uid = str(row["user_id"])
    sec = str(row["sec_user_id"])
    payload = {"user_id": uid, "sec_user_id": sec, "items": [item], "fetched_at": now_iso()}
    if response is not None:
        payload["response"] = response
    append_jsonl(raw_dir / "user_profiles.jsonl", payload)
    statuses[uid] = {
        "user_id": uid,
        "sec_user_id": sec,
        "status": "success",
        "endpoint": "",
        "http_status": "",
        "error_category": "",
        "error": "",
        "attempted_at": now_iso(),
    }
    row["profile_fetch_status"] = "success"
    row["skip_reason"] = ""


def record_profile_failure(
    raw_dir: Path,
    statuses: dict[str, dict[str, str]],
    row: dict[str, Any],
    message: str,
    *,
    response: Any | None = None,
    api_key: str = "",
    status: str = "failed",
    endpoint: str = "",
    classification: ProfileErrorClassification | None = None,
) -> None:
    uid = str(row["user_id"])
    sec = str(row["sec_user_id"])
    classification = classification or classify_profile_error(message)
    rejected: dict[str, Any] = {"user_id": uid, "sec_user_id": sec, "reason": message, "fetched_at": now_iso()}
    if endpoint:
        rejected["endpoint"] = endpoint
    if classification.http_status:
        rejected["http_status"] = classification.http_status
    rejected["error_category"] = classification.category
    if response is not None:
        rejected["response"] = redact_secrets(response, [api_key])
    append_jsonl(raw_dir / "rejected_user_profiles.jsonl", rejected)
    statuses[uid] = {
        "user_id": uid,
        "sec_user_id": sec,
        "status": status,
        "endpoint": endpoint,
        "http_status": classification.http_status,
        "error_category": classification.category,
        "error": message,
        "attempted_at": now_iso(),
    }
    row["profile_fetch_status"] = "failed"
    row["skip_reason"] = message


def collect_one_profile_with_handler(
    raw_dir: Path,
    statuses: dict[str, dict[str, str]],
    row: dict[str, Any],
    client: TikHubClient,
    stats: CollectionStats,
    *,
    api_key: str,
) -> bool:
    """Collect one profile via the single-user handler.

    Returns True when collection should stop because the single-user endpoint
    hit a quota/rate-limit style blocker. The caller owns attempted counting so
    batch fallback can avoid double-counting the same target user.
    """

    uid = str(row["user_id"])
    sec = str(row["sec_user_id"])
    try:
        result = client.handler_user_profile(sec)
        success_items = accepted_profile_items(result, uid, sec)
        if not success_items:
            message = "identity_mismatch_or_empty_profile_response"
            classification = classify_profile_error(message)
            record_profile_error_stats(stats, endpoint=PROFILE_HANDLER_ENDPOINT, classification=classification)
            record_profile_failure(
                raw_dir,
                statuses,
                row,
                message,
                response=result,
                api_key=api_key,
                endpoint=PROFILE_HANDLER_ENDPOINT,
                classification=classification,
            )
            stats.failed += 1
            return False
        record_profile_success(raw_dir, statuses, row, success_items[0], response=result)
        stats.succeeded += 1
        return False
    except Exception as exc:  # noqa: BLE001 - per-profile failure is recorded and collection continues.
        message = str(redact_secrets(str(exc), [api_key]))
        classification = classify_profile_error(message)
        status = "quota_stopped" if classification.quota_or_rate_limited else "failed"
        record_profile_error_stats(stats, endpoint=PROFILE_HANDLER_ENDPOINT, classification=classification)
        record_profile_failure(
            raw_dir,
            statuses,
            row,
            message,
            api_key=api_key,
            status=status,
            endpoint=PROFILE_HANDLER_ENDPOINT,
            classification=classification,
        )
        stats.failed += 1
        if status == "quota_stopped":
            mark_quota_stop(stats)
            return True
        return False


def collect_batch_profiles_with_split_fallback(
    batch: list[dict[str, Any]],
    raw_dir: Path,
    statuses: dict[str, dict[str, str]],
    client: TikHubClient,
    stats: CollectionStats,
    *,
    api_key: str,
    max_batch_http400_splits: int = 0,
    _batch_http400_splits: list[int] | None = None,
) -> bool:
    """Collect a batch, recursively splitting failed batches before handler fallback.

    TikHub's batch endpoint can fail the whole request when one sec_user_id in a
    50-user batch is unacceptable to the endpoint. Splitting keeps the fast path
    for valid sub-batches and only falls back to the slower single-user handler
    for isolated records. Returns True when quota/rate-limit style blocking is
    observed and the caller should stop this run.
    """

    if not batch:
        return False
    if _batch_http400_splits is None:
        _batch_http400_splits = [0]
    try:
        result = client.fetch_batch_user_profile([str(row["sec_user_id"]) for row in batch])
    except Exception as exc:  # noqa: BLE001 - batch failure is split or checkpointed per target.
        message = str(redact_secrets(str(exc), [api_key]))
        classification = classify_profile_error(message)
        status = "quota_stopped" if classification.quota_or_rate_limited else "failed"
        record_profile_error_stats(stats, endpoint=PROFILE_BATCH_ENDPOINT, classification=classification)
        if status == "quota_stopped":
            for row in batch:
                record_profile_failure(
                    raw_dir,
                    statuses,
                    row,
                    message,
                    api_key=api_key,
                    status=status,
                    endpoint=PROFILE_BATCH_ENDPOINT,
                    classification=classification,
                )
                stats.failed += 1
            write_statuses(raw_dir, statuses)
            mark_quota_stop(stats)
            mark_cost_guard(stats, f"batch_{classification.http_status or classification.category}_stop")
            return True
        if len(batch) > 1 and classification.http_status == "400" and _batch_http400_splits[0] >= max_batch_http400_splits:
            mark_cost_guard(stats, "batch_http400_downgrade_handler")
            for row in batch:
                if collect_one_profile_with_handler(raw_dir, statuses, row, client, stats, api_key=api_key):
                    write_statuses(raw_dir, statuses)
                    return True
            write_statuses(raw_dir, statuses)
            return False
        if len(batch) > 1:
            if classification.http_status == "400":
                _batch_http400_splits[0] += 1
            midpoint = len(batch) // 2
            if collect_batch_profiles_with_split_fallback(
                batch[:midpoint],
                raw_dir,
                statuses,
                client,
                stats,
                api_key=api_key,
                max_batch_http400_splits=max_batch_http400_splits,
                _batch_http400_splits=_batch_http400_splits,
            ):
                return True
            return collect_batch_profiles_with_split_fallback(
                batch[midpoint:],
                raw_dir,
                statuses,
                client,
                stats,
                api_key=api_key,
                max_batch_http400_splits=max_batch_http400_splits,
                _batch_http400_splits=_batch_http400_splits,
            )
        if len(batch) == 1:
            stop = collect_one_profile_with_handler(raw_dir, statuses, batch[0], client, stats, api_key=api_key)
            write_statuses(raw_dir, statuses)
            return stop
        for row in batch:
            record_profile_failure(
                raw_dir,
                statuses,
                row,
                message,
                api_key=api_key,
                status=status,
                endpoint=PROFILE_BATCH_ENDPOINT,
                classification=classification,
            )
            stats.failed += 1
        write_statuses(raw_dir, statuses)
        return False

    for row in batch:
        uid = str(row["user_id"])
        sec = str(row["sec_user_id"])
        success_items = accepted_profile_items(result, uid, sec)
        if success_items:
            record_profile_success(raw_dir, statuses, row, success_items[0])
            stats.succeeded += 1
        else:
            classification = classify_profile_error("identity_mismatch_or_empty_profile_response")
            record_profile_error_stats(stats, endpoint=PROFILE_BATCH_ENDPOINT, classification=classification)
            stop = collect_one_profile_with_handler(raw_dir, statuses, row, client, stats, api_key=api_key)
            if stop:
                write_statuses(raw_dir, statuses)
                return True
    write_statuses(raw_dir, statuses)
    return False


def collect_profiles(
    target_rows: list[dict[str, Any]],
    raw_dir: Path,
    client: TikHubClient,
    *,
    resume: bool,
    max_users: int | None,
    api_key: str,
    profile_api: str = "handler",
    retry_failed_profiles: bool = False,
    batch_handler_fallback: bool = True,
    max_batch_http400_splits: int = 0,
) -> CollectionStats:
    statuses = load_statuses(raw_dir) if resume else {}
    all_fetchable = classify_fetchable(target_rows)
    fetchable: list[dict[str, Any]] = []
    for row in all_fetchable:
        existing = statuses.get(str(row["user_id"]))
        if resume and existing:
            existing_status = existing.get("status")
            if existing_status == "success":
                row["profile_fetch_status"] = "success"
                continue
            if existing_status in {"failed", "quota_stopped"} and not retry_failed_profiles:
                row["profile_fetch_status"] = "failed"
                row["skip_reason"] = existing.get("error", "failed")
                continue
        fetchable.append(row)
    if max_users is not None:
        fetchable = fetchable[:max_users]
    stats = CollectionStats(
        endpoint_call_counts=client.endpoint_call_counts,
        http_status_counts={},
        rejected_by_endpoint_status={},
        profile_api_requested=profile_api,
        profile_api_resolved=resolve_profile_api(profile_api, limit_profile="capped"),
    )
    profile_api = stats.profile_api_resolved
    for row in fetchable:
        uid = str(row["user_id"])
        sec = str(row["sec_user_id"])
        existing = statuses.get(uid)
        if resume and existing:
            existing_status = existing.get("status")
            if existing_status == "success":
                row["profile_fetch_status"] = "success"
                continue
            if existing_status in {"failed", "quota_stopped"} and not retry_failed_profiles:
                row["profile_fetch_status"] = "failed"
                row["skip_reason"] = existing.get("error", "failed")
                continue
        if profile_api == "batch":
            continue
        stats.attempted += 1
        stop = collect_one_profile_with_handler(raw_dir, statuses, row, client, stats, api_key=api_key)
        write_statuses(raw_dir, statuses)
        if stop:
            break
    if profile_api == "batch" and not stats.partial:
        pending = [
            row
            for row in fetchable
            if not (
                resume
                and (statuses.get(str(row["user_id"])) or {}).get("status") == "success"
            )
            and not (
                resume
                and not retry_failed_profiles
                and (statuses.get(str(row["user_id"])) or {}).get("status") in {"failed", "quota_stopped"}
            )
        ]
        for batch in chunks(pending, 50):
            stats.attempted += len(batch)
            if batch_handler_fallback:
                if collect_batch_profiles_with_split_fallback(
                    batch,
                    raw_dir,
                    statuses,
                    client,
                    stats,
                    api_key=api_key,
                    max_batch_http400_splits=max_batch_http400_splits,
                ):
                    break
                continue
            try:
                result = client.fetch_batch_user_profile([str(row["sec_user_id"]) for row in batch])
            except Exception as exc:  # noqa: BLE001 - batch failure is checkpointed per target.
                message = str(redact_secrets(str(exc), [api_key]))
                classification = classify_profile_error(message)
                status = "quota_stopped" if classification.quota_or_rate_limited else "failed"
                record_profile_error_stats(stats, endpoint=PROFILE_BATCH_ENDPOINT, classification=classification)
                for row in batch:
                    record_profile_failure(
                        raw_dir,
                        statuses,
                        row,
                        message,
                        api_key=api_key,
                        status=status,
                        endpoint=PROFILE_BATCH_ENDPOINT,
                        classification=classification,
                    )
                    stats.failed += 1
                write_statuses(raw_dir, statuses)
                if status == "quota_stopped":
                    mark_quota_stop(stats)
                    mark_cost_guard(stats, f"batch_{classification.http_status or classification.category}_stop")
                    break
                if classification.http_status == "400":
                    mark_cost_guard(stats, "batch_http400_failed_without_fallback")
                continue
            for row in batch:
                uid = str(row["user_id"])
                sec = str(row["sec_user_id"])
                success_items = accepted_profile_items(result, uid, sec)
                if success_items:
                    record_profile_success(raw_dir, statuses, row, success_items[0])
                    stats.succeeded += 1
                else:
                    classification = classify_profile_error("identity_mismatch_or_empty_profile_response")
                    record_profile_error_stats(stats, endpoint=PROFILE_BATCH_ENDPOINT, classification=classification)
                    record_profile_failure(
                        raw_dir,
                        statuses,
                        row,
                        "identity_mismatch_or_empty_profile_response",
                        api_key=api_key,
                        endpoint=PROFILE_BATCH_ENDPOINT,
                        classification=classification,
                    )
                    stats.failed += 1
            write_statuses(raw_dir, statuses)
    stats.endpoint_call_counts = client.endpoint_call_counts
    return stats


def load_current_live_profiles(raw_dir: Path) -> dict[str, dict[str, Any]]:
    by_user: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(raw_dir / "user_profiles.jsonl"):
        target_uid = str(row.get("user_id") or "")
        items = row.get("items") if isinstance(row.get("items"), list) else extract_user_items(row.get("response"))
        for item in items or []:
            if not isinstance(item, dict):
                continue
            target_sec = str(row.get("sec_user_id") or "")
            if not profile_item_matches_target(item, target_uid, target_sec):
                continue
            user = normalize_profile_payload(item)
            uid = target_uid
            user["user_id"] = uid
            by_user[uid] = user
            break
    return by_user


def merge_profile_user(target: Mapping[str, Any], live: dict[str, Any] | None, historical: HistoricalProfile | None, source_user: Mapping[str, str]) -> tuple[dict[str, Any], str]:
    uid = str(target["user_id"])
    base = {field: "" for field in USER_COLUMNS}
    base.update({field: source_user.get(field, "") for field in USER_COLUMNS if field in source_user})
    base["user_id"] = uid
    base["sec_user_id"] = target.get("sec_user_id", "") or base.get("sec_user_id", "")
    source = "none"
    if historical:
        source = historical.source
        for key, value in historical.user.items():
            if key in base and value not in (None, "") and not base.get(key):
                base[key] = value
    if live:
        source = "live_current"
        for key, value in live.items():
            if key in base and value not in (None, ""):
                base[key] = value
        base["user_id"] = uid
        base["sec_user_id"] = live.get("sec_user_id") or target.get("sec_user_id", "") or base.get("sec_user_id", "")
    return base, source


def build_abm_row(
    target: Mapping[str, Any],
    user: Mapping[str, Any],
    profile_source: str,
    fetch_status: str,
    *,
    profile_index_thresholds: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    follower_count = parse_int(user.get("follower_count"))
    video_count = parse_int(user.get("video_count"))
    signals = profile_index_signals(target, user)
    thresholds = profile_index_thresholds or compute_profile_index_thresholds([signals])
    index_scores = compute_profile_index_scores(signals, thresholds)
    influence_score = max(index_scores["global_influence_score"], index_scores["local_influence_score"])
    verified = str(user.get("verified_type") or "")
    role = str(target.get("user_role") or "observed")
    if verified and verified not in {"0", "False", "false", ""}:
        user_type = "verified"
    elif target.get("priority_tier") == "creator":
        user_type = "creator"
    elif influence_score >= 0.6:
        user_type = "kol_or_central_user"
    else:
        user_type = role
    interest_tags = sorted(set(target.get("_interest_tags") or []))
    provenance = {
        "profile_index_method": PROFILE_INDEX_METHOD,
        "profile_index_variant": PROFILE_INDEX_VARIANT,
        "profile_index_reference_basis": PROFILE_INDEX_REFERENCE_BASIS,
        "profile_index_thresholds": {key: round(float(value), 6) for key, value in thresholds.items()},
        "observed_api_fields": ["follower_count", "following_count", "video_count", "verified_type"] if profile_source != "none" else [],
        "interaction_observed_fields": ["comment_count", "reply_count", "edge_degree", "comment_like_sum"],
        "derived_fields": [*PROFILE_INDEX_COMPONENT_FIELDS, "interest_tags", "user_type"],
        "removed_demo_preset_fields": REMOVED_DEMO_PRESET_FIELDS,
        "field_contract_note": "Demo preset fields are not emitted in processed profile outputs.",
    }
    return {
        "user_id": target.get("user_id", ""),
        "user_type": user_type,
        "follower_count": follower_count,
        "following_count": parse_int(user.get("following_count")),
        "video_count": video_count,
        "verified_type": verified,
        "interest_tags": interest_tags,
        "activity_score": round(index_scores["activity_score"], 6),
        "activity_video_score": round(index_scores["activity_video_score"], 6),
        "activity_publish_score": round(index_scores["activity_publish_score"], 6),
        "activity_comment_score": round(index_scores["activity_comment_score"], 6),
        "activity_reply_score": round(index_scores["activity_reply_score"], 6),
        "global_influence_score": round(index_scores["global_influence_score"], 6),
        "local_influence_score": round(index_scores["local_influence_score"], 6),
        "local_network_score": round(index_scores["local_network_score"], 6),
        "local_recognition_score": round(index_scores["local_recognition_score"], 6),
        "influence_coverage_score": round(index_scores["influence_coverage_score"], 6),
        "influence_recognition_score": round(index_scores["influence_recognition_score"], 6),
        "influence_network_score": round(index_scores["influence_network_score"], 6),
        "profile_index_method": PROFILE_INDEX_METHOD,
        "profile_index_variant": PROFILE_INDEX_VARIANT,
        "profile_source": profile_source,
        "profile_fetch_status": fetch_status,
        "attribute_provenance": provenance,
    }


def build_processed_outputs(
    source_run: Path,
    processed_dir: Path,
    raw_dir: Path,
    target_rows: list[dict[str, Any]],
    historical: Mapping[str, HistoricalProfile],
    stats: CollectionStats,
) -> dict[str, Any]:
    source_users_by_id = {row.get("user_id", ""): row for row in read_csv(source_run / "users.csv")}
    live_profiles = load_current_live_profiles(raw_dir)
    statuses = load_statuses(raw_dir)
    user_rows: list[dict[str, Any]] = []
    profile_rows: list[dict[str, Any]] = []
    abm_rows: list[dict[str, Any]] = []
    failed_rows: list[dict[str, Any]] = []
    missing_rows: list[dict[str, Any]] = []
    target_public_rows: list[dict[str, Any]] = []
    prepared_rows: list[tuple[dict[str, Any], dict[str, Any], str, str]] = []
    signal_rows: list[dict[str, int]] = []
    for target in target_rows:
        uid = str(target["user_id"])
        status = statuses.get(uid, {})
        if status.get("status") == "success":
            target["profile_fetch_status"] = "success"
            target["skip_reason"] = ""
        elif status.get("status") in {"failed", "quota_stopped"}:
            target["profile_fetch_status"] = status.get("status")
            target["skip_reason"] = status.get("error", "failed")
        elif target.get("profile_fetch_status") == "pending" and stats.partial:
            target["profile_fetch_status"] = "skipped"
            target["skip_reason"] = stats.partial_reason or "partial_stop"
        live = live_profiles.get(uid)
        hist = historical.get(uid)
        user, source = merge_profile_user(target, live, hist, source_users_by_id.get(uid, {}))
        fetch_status = str(target.get("profile_fetch_status") or "skipped")
        prepared_rows.append((target, user, source, fetch_status))
        signal_rows.append(profile_index_signals(target, user))
    profile_index_thresholds = compute_profile_index_thresholds(signal_rows)
    for target, user, source, fetch_status in prepared_rows:
        if fetch_status in {"failed", "quota_stopped"}:
            failed_rows.append({k: target.get(k, "") for k in PROFILE_FIELDNAMES})
        if target.get("sec_user_id_confidence") in {"missing", "placeholder"}:
            missing_rows.append({k: target.get(k, "") for k in PROFILE_FIELDNAMES})
        abm = build_abm_row(target, user, source, fetch_status, profile_index_thresholds=profile_index_thresholds)
        for field in [
            "activity_score",
            "activity_video_score",
            "activity_comment_score",
            "activity_reply_score",
            "global_influence_score",
            "local_influence_score",
            "local_network_score",
            "local_recognition_score",
            "profile_index_method",
            "profile_index_variant",
        ]:
            user[field] = abm.get(field, "")
        user_rows.append(user)
        abm_rows.append(abm)
        if source != "none" and fetch_status in {"success", "skipped", "failed", "quota_stopped"}:
            profile_rows.append({field: abm.get(field, "") for field in PROFILE_COLUMNS})
        target_public_rows.append({k: target.get(k, "") for k in PROFILE_FIELDNAMES})
    # no duplicates, stable first row by sorted target order
    seen_profiles: set[str] = set()
    deduped_profiles = []
    for row in profile_rows:
        uid = str(row.get("user_id", ""))
        if uid and uid not in seen_profiles:
            seen_profiles.add(uid)
            deduped_profiles.append(row)
    write_csv(processed_dir / "profile_target_users.csv", PROFILE_FIELDNAMES, target_public_rows)
    users_out: list[dict[str, Any]] = []
    for idx, row in enumerate(user_rows):
        uid = str(row.get("user_id", ""))
        src = "live_current" if uid in live_profiles else historical[uid].source if uid in historical else "none"
        users_out.append(dict(row, profile_source=src, profile_fetch_status=target_rows[idx].get("profile_fetch_status", "")))
    write_csv(processed_dir / "users.csv", USER_COLUMNS + ["profile_source", "profile_fetch_status"], users_out)
    write_csv(processed_dir / "profiles.csv", PROFILE_COLUMNS, deduped_profiles)
    write_csv(processed_dir / "abm_user_profiles.csv", ABM_COLUMNS, abm_rows)
    write_csv(processed_dir / "failed_profile_users.csv", PROFILE_FIELDNAMES, failed_rows)
    write_csv(processed_dir / "missing_sec_uid_users.csv", PROFILE_FIELDNAMES, missing_rows)
    robustness = profile_index_robustness_report(signal_rows)
    write_profile_index_robustness_report(processed_dir, robustness)
    return {
        "users": len(user_rows),
        "profiles": len(deduped_profiles),
        "abm_user_profiles": len(abm_rows),
        "failed_profile_users": len(failed_rows),
        "missing_sec_uid_users": len(missing_rows),
        "live_profiles": len(live_profiles),
        "historical_profiles_used": len([r for r in users_out if str(r.get("profile_source", "")).startswith("historical")]),
        "profile_index_method": PROFILE_INDEX_METHOD,
        "profile_index_thresholds": {key: round(float(value), 6) for key, value in profile_index_thresholds.items()},
        "profile_index_robustness_report": str(processed_dir / "profile_index_robustness_report.json"),
    }


def field_coverage(rows: list[dict[str, str]], fields: list[str]) -> dict[str, int]:
    return {field: sum(1 for row in rows if str(row.get(field, "")).strip()) for field in fields}


def effective_profile_limit(args: argparse.Namespace, settings: TikHubSettings) -> int | None:
    if args.max_users is not None:
        return args.max_users
    if args.limit_profile == "unbounded":
        return None
    return settings.max_users


def resolve_profile_api(profile_api: str, *, limit_profile: str) -> str:
    if profile_api in {"cost-safe", "auto"}:
        return "handler"
    return profile_api


def expansion_state(attempted: int, succeeded: int, pending_after: int, partial_reason: str) -> str:
    if partial_reason == "audit_only":
        return "audit_only"
    if partial_reason == "no_confirmed_sec_uid" and attempted == 0:
        return "derived_only_no_confirmed_sec_uid"
    if partial_reason.startswith("live_unavailable") and attempted == 0:
        return "live_unavailable"
    if attempted > 0 and pending_after == 0 and not partial_reason:
        return "live_profile_complete"
    if attempted > 0 or succeeded > 0:
        return "live_profile_partial"
    return "derived_only"


def profile_field_coverage(users: list[dict[str, str]], target_rows: list[dict[str, Any]]) -> dict[str, int]:
    profile_backed = [row for row in users if row.get("profile_source") and row.get("profile_source") != "none"]
    return {
        "user_id": len(target_rows),
        "sec_user_id": len([row for row in target_rows if row.get("sec_user_id_confidence") in {"confirmed", "confirmed_equal_user_id"}]),
        "nickname": sum(1 for row in profile_backed if row.get("nickname")),
        "follower_count": sum(1 for row in profile_backed if row.get("follower_count") not in ("", "0")),
        "following_count": sum(1 for row in profile_backed if row.get("following_count") not in ("", "0")),
        "video_count": sum(1 for row in profile_backed if row.get("video_count") not in ("", "0")),
        "verified_type": sum(1 for row in profile_backed if row.get("verified_type") not in ("", "0")),
        "bio": sum(1 for row in profile_backed if row.get("bio")),
    }


def build_collection_report(
    *,
    run_id: str,
    source_run: Path,
    processed_dir: Path,
    raw_dir: Path,
    target_rows: list[dict[str, Any]],
    target_audit: Mapping[str, Any],
    processed_counts: Mapping[str, int],
    stats: CollectionStats,
    settings: TikHubSettings,
) -> dict[str, Any]:
    users = read_csv(processed_dir / "users.csv")
    statuses = load_statuses(raw_dir)
    status_http_counts, status_endpoint_counts, quota_stopped_profiles, quota_stop_reason = classify_status_rows(statuses)
    cumulative_attempted = len(statuses)
    cumulative_success = len([row for row in statuses.values() if row.get("status") == "success"])
    cumulative_failed = len([row for row in statuses.values() if row.get("status") in {"failed", "quota_stopped"}])
    cumulative_quota_stopped = len([row for row in statuses.values() if row.get("status") == "quota_stopped"])
    coverage = profile_field_coverage(users, target_rows)
    missing_count = len([row for row in target_rows if row.get("sec_user_id_confidence") in {"missing", "placeholder"}])
    pending_after = len([row for row in target_rows if row.get("profile_fetch_status") == "pending"])
    partial = stats.partial or pending_after > 0 or cumulative_quota_stopped > 0
    partial_reason = stats.partial_reason or ("quota_or_rate_limit" if cumulative_quota_stopped else "pending_profiles_after_run" if pending_after else "")
    state = expansion_state(cumulative_attempted, cumulative_success, pending_after, partial_reason)
    return {
        "run_id": run_id,
        "created_at": now_iso(),
        "source_dataset_path": str(source_run),
        "raw_dir": str(raw_dir),
        "processed_dir": str(processed_dir),
        "target_users": len(target_rows),
        "source_unique_users": target_audit.get("source_unique_users"),
        "attempted_profiles": cumulative_attempted,
        "successful_profiles": cumulative_success,
        "failed_profiles": cumulative_failed,
        "current_run_attempted_profiles": stats.attempted,
        "current_run_successful_profiles": stats.succeeded,
        "current_run_failed_profiles": stats.failed,
        "current_run_success_delta": stats.succeeded,
        "missing_sec_uid_users": missing_count,
        "skipped_profiles": len([row for row in target_rows if row.get("profile_fetch_status") == "skipped"]) or pending_after,
        "pending_profiles": pending_after,
        "profiles_collected": cumulative_success > 0,
        "partial": partial,
        "partial_reason": partial_reason,
        "expansion_state": state,
        "quota_or_rate_limited": stats.quota_or_rate_limited or cumulative_quota_stopped > 0,
        "quota_stopped_profiles": quota_stopped_profiles,
        "quota_stop_reason": quota_stop_reason,
        "limit_profile": "unbounded" if settings.max_users is None else "capped",
        "profile_api_requested": stats.profile_api_requested,
        "profile_api_resolved": stats.profile_api_resolved,
        "profile_error_contract": {
            "http_400": "provider_bad_request; do not classify as quota; batch may downgrade to handler without recursively expanding cost.",
            "http_402": "quota_or_balance; stop immediately.",
            "http_429": "rate_limit; stop immediately.",
            "identity_mismatch_or_empty_response": "write rejected_user_profiles.jsonl and do not count success.",
        },
        "endpoint_call_counts": stats.endpoint_call_counts or {},
        "http_status_counts": status_http_counts,
        "current_run_http_status_counts": stats.http_status_counts or {},
        "rejected_by_endpoint_status": status_endpoint_counts,
        "current_run_rejected_by_endpoint_status": stats.rejected_by_endpoint_status or {},
        "cost_guard_triggered": stats.cost_guard_triggered,
        "cost_guard_reason": stats.cost_guard_reason,
        "recommended_resume_mode": "handler",
        "next_resume_command": recommended_resume_command(),
        "field_coverage": coverage,
        "processed_counts": dict(processed_counts),
        "target_audit_path": str(processed_dir / "profile_target_audit.json"),
        "sec_uid_evidence_audit_path": str(processed_dir / "sec_uid_evidence_audit.json"),
        "scope_checks": target_audit.get("scope_checks", {}),
        "redacted_config": settings.redacted(),
        "secrets_read_printed_written": "no",
        "large_raw_processed_committed": "no",
        "private_csv_outputs": ["users.csv", "profiles.csv", "abm_user_profiles.csv", "profile_target_users.csv", "missing_sec_uid_users.csv", "failed_profile_users.csv"],
        "public_report_boundary": "Markdown reports contain aggregate statistics only; processed CSVs are local ignored research artifacts and must not be committed when they include profile-like fields.",
        "processed_profile_contract": {
            "removed_demo_preset_fields": REMOVED_DEMO_PRESET_FIELDS,
            "raw_private_data_overwritten": "no",
        },
    }


def write_collection_docs(processed_dir: Path, report: Mapping[str, Any]) -> None:
    (processed_dir / "profile_collection_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (processed_dir / "profile_collection_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Profile collection audit",
        "",
        f"- source dataset: `{report.get('source_dataset_path')}`",
        f"- target users: {report.get('target_users')}",
        f"- sec_uid evidence recovery coverage: {(report.get('field_coverage') or {}).get('sec_user_id', 0)} / {report.get('target_users')}",
        f"- attempted profiles: {report.get('attempted_profiles')}",
        f"- successful profiles: {report.get('successful_profiles')}",
        f"- failed profiles: {report.get('failed_profiles')}",
        f"- missing sec_uid users: {report.get('missing_sec_uid_users')}",
        f"- profiles_collected: {report.get('profiles_collected')}",
        f"- partial: {report.get('partial')}",
        f"- partial_reason: {report.get('partial_reason')}",
        f"- expansion_state: {report.get('expansion_state')}",
        f"- profile_api: requested `{report.get('profile_api_requested')}`, resolved `{report.get('profile_api_resolved')}`",
        f"- quota_stopped_profiles: {report.get('quota_stopped_profiles')}",
        f"- current_run_success_delta: {report.get('current_run_success_delta')}",
        f"- cost_guard_triggered: {report.get('cost_guard_triggered')}",
        f"- cost_guard_reason: {report.get('cost_guard_reason')}",
        f"- recommended_resume_mode: {report.get('recommended_resume_mode')}",
        f"- secrets read/printed/written: {report.get('secrets_read_printed_written')}",
        f"- raw/processed large data committed: {report.get('large_raw_processed_committed')}",
        "",
        "## Cost audit",
        "",
        "### Endpoint call counts",
        "",
        "| endpoint | calls |",
        "|---|---:|",
    ]
    for key, value in sorted((report.get("endpoint_call_counts") or {}).items()):
        lines.append(f"| {key} | {value} |")
    lines.extend(["", "### HTTP status counts", "", "| status/category | rows |", "|---|---:|"])
    for key, value in sorted((report.get("http_status_counts") or {}).items()):
        lines.append(f"| {key} | {value} |")
    lines.extend(["", "### Rejected by endpoint/status", "", "| endpoint:status | rows |", "|---|---:|"])
    for key, value in sorted((report.get("rejected_by_endpoint_status") or {}).items()):
        lines.append(f"| {key} | {value} |")
    lines.extend([
        "",
        "## Field coverage",
        "",
        "| field | non-empty rows |",
        "|---|---:|",
    ])
    for key, value in sorted((report.get("field_coverage") or {}).items()):
        lines.append(f"| {key} | {value} |")
    lines.extend(["", "## Scope checks", "", "| check | value |", "|---|---|"])
    for key, value in (report.get("scope_checks") or {}).items():
        if isinstance(value, (dict, list)):
            continue
        lines.append(f"| {key} | {value} |")
    lines.append("\nNo nickname, bio, signature, or raw profile payload details are shown in this report.\n")
    (processed_dir / "profile_collection_audit.md").write_text("\n".join(lines), encoding="utf-8")
    readme = [
        "# Jinjiang profile expansion derived run",
        "",
        "This local run extends the corrected Jinjiang Douyin research dataset with public profile signals where confirmed lookup IDs are available.",
        "",
        "## Outputs",
        "",
        "- `profile_target_users.csv`: target manifest and profile fetch status.",
        "- `users.csv`: local profile/user fields; may contain sensitive nickname/bio fields and should not be committed.",
        "- `profiles.csv`: profile-derived ABM rows for rows with live or historical profile fields.",
        "- `abm_user_profiles.csv`: ABM initialization fields with provenance.",
        "- `missing_sec_uid_users.csv` / `failed_profile_users.csv`: explicit partial manifests.",
        "",
        "Reports in this directory intentionally contain aggregate statistics only.",
        "Processed CSVs are local ignored research artifacts and may contain profile-like fields when live or historical profiles exist; do not commit them.",
    ]
    (processed_dir / "README.md").write_text("\n".join(readme) + "\n", encoding="utf-8")


def write_validation_doc(docs_dir: Path, report: Mapping[str, Any]) -> Path:
    docs_dir.mkdir(parents=True, exist_ok=True)
    path = docs_dir / f"jinjiang-douyin-profile-expansion-{datetime.now(timezone.utc).strftime('%Y%m%d')}.md"
    lines = [
        "# 锦江酒店 Douyin 用户 Profile 扩展验证小结",
        "",
        f"- source dataset: `{report.get('source_dataset_path')}`",
        f"- target users: {report.get('target_users')}",
        f"- sec_uid evidence recovery coverage: {(report.get('field_coverage') or {}).get('sec_user_id', 0)} / {report.get('target_users')}",
        f"- attempted profiles: {report.get('attempted_profiles')}",
        f"- successful profiles: {report.get('successful_profiles')}",
        f"- failed profiles: {report.get('failed_profiles')}",
        f"- missing sec_uid users: {report.get('missing_sec_uid_users')}",
        f"- profiles_collected: {report.get('profiles_collected')}",
        f"- partial: {report.get('partial')}",
        f"- partial_reason: {report.get('partial_reason')}",
        f"- expansion_state: {report.get('expansion_state')}",
        f"- profile_api: requested `{report.get('profile_api_requested')}`, resolved `{report.get('profile_api_resolved')}`",
        f"- quota_stopped_profiles: {report.get('quota_stopped_profiles')}",
        f"- current_run_success_delta: {report.get('current_run_success_delta')}",
        f"- cost_guard_triggered: {report.get('cost_guard_triggered')}",
        f"- recommended_resume_mode: {report.get('recommended_resume_mode')}",
        "- quota/rate limit: see partial_reason and endpoint_call_counts",
        "- secrets read/printed/written: no",
        "- raw/processed large data committed: no",
        "",
        "## 成本审计（聚合）",
        "",
        "| 指标 | 值 |",
        "|---|---:|",
        f"| quota_stopped_profiles | {report.get('quota_stopped_profiles')} |",
        f"| current_run_success_delta | {report.get('current_run_success_delta')} |",
        "",
        "### endpoint_call_counts",
        "",
        "| endpoint | calls |",
        "|---|---:|",
    ]
    for key, value in sorted((report.get("endpoint_call_counts") or {}).items()):
        lines.append(f"| {key} | {value} |")
    lines.extend(["", "### http_status_counts", "", "| status/category | rows |", "|---|---:|"])
    for key, value in sorted((report.get("http_status_counts") or {}).items()):
        lines.append(f"| {key} | {value} |")
    lines.extend([
        "",
        "## 字段覆盖率",
        "",
        "| 字段 | 非空行数 |",
        "|---|---:|",
    ])
    for key, value in sorted((report.get("field_coverage") or {}).items()):
        lines.append(f"| {key} | {value} |")
    lines.extend([
        "",
        "说明：本文档只展示聚合统计，不展开昵称、bio、signature 等用户明细。`brand_attitude`、`like_tendency`、`comment_tendency`、`share_tendency` 是已移除的历史 demo preset 字段，不再写入新的 processed profile 输出。",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def scan_report_safety(paths: Iterable[Path]) -> list[str]:
    findings: list[str] = []
    for path in paths:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in SENSITIVE_REPORT_PATTERNS:
            if pattern in text:
                findings.append(f"{path}:{pattern}")
        if re.search(r"(?i)(api[_-]?key|token|secret)\s*[:=]\s*[A-Za-z0-9_\-]{8,}", text):
            findings.append(f"{path}:token_like_secret")
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect/profile-audit Jinjiang Douyin observed users")
    parser.add_argument("--source-run", type=Path, default=DEFAULT_SOURCE_RUN)
    parser.add_argument("--output-run-id", default=f"jinjiang-profile-expansion-derived-{timestamp()}")
    parser.add_argument("--env-file")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--retry-failed-profiles",
        action="store_true",
        help="With --resume, retry users previously marked failed or quota_stopped; successes are still skipped.",
    )
    parser.add_argument("--max-users", type=int)
    parser.add_argument("--limit-profile", choices=["capped", "unbounded"], default="capped")
    parser.add_argument(
        "--profile-api",
        choices=["cost-safe", "auto", "handler", "batch"],
        default="cost-safe",
        help="Profile API strategy. 'cost-safe'/'auto' resolve to App V3 handler; 'batch' is explicit opt-in for Web batch profile.",
    )
    parser.add_argument(
        "--max-batch-http400-splits",
        type=int,
        default=0,
        help="Maximum recursive batch HTTP 400 splits before downgrading the batch to handler. Default 0 avoids repeated costly batch 400 calls.",
    )
    parser.add_argument("--processed-root", type=Path, default=PROCESSED_ROOT)
    parser.add_argument("--raw-root", type=Path, default=RAW_ROOT)
    parser.add_argument(
        "--source-raw-run",
        type=Path,
        help="Raw source run directory for sec_uid recovery. Defaults to raw-root/source-run-name.",
    )
    parser.add_argument(
        "--sec-uid-evidence-run",
        type=Path,
        action="append",
        default=[],
        help="Additional raw evidence run path or run id under --raw-root. Can be repeated.",
    )
    parser.add_argument(
        "--sec-uid-evidence-glob",
        action="append",
        default=[],
        help="Additional raw evidence run glob rooted at --raw-root. Can be repeated; matches are sorted.",
    )
    parser.add_argument("--docs-dir", type=Path, default=Path("docs/04-开发验证"))
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument(
        "--recompute-profile-indices-only",
        action="store_true",
        help="Offline-only in-place recompute of profile index columns and robustness reports for an existing processed run.",
    )
    parser.add_argument(
        "--recompute-profile-target-metrics-only",
        action="store_true",
        help="Offline-only in-place recompute of profile_target_users.csv comment/reply metrics, then refresh profile index columns.",
    )
    args = parser.parse_args(argv)

    source_run = args.source_run
    if not source_run.exists():
        print(f"source run not found: {source_run}", file=sys.stderr)
        return 2
    if args.recompute_profile_target_metrics_only:
        target_audit = recompute_profile_target_metrics_in_place(source_run)
        counts = recompute_profile_indices_in_place(source_run)
        safety_findings = scan_report_safety(
            [
                source_run / "profile_target_metrics_recompute_audit.json",
                source_run / "profile_index_robustness_report.md",
                source_run / "profile_index_robustness_report.json",
                source_run / "final_collection_report.json",
            ]
        )
        if safety_findings:
            print(f"unsafe report content: {safety_findings}", file=sys.stderr)
            return 3
        print(json.dumps({"processed_dir": str(source_run), "target_audit": target_audit, "report": counts, "live_fetch": False}, ensure_ascii=False))
        return 0
    if args.recompute_profile_indices_only:
        counts = recompute_profile_indices_in_place(source_run)
        safety_findings = scan_report_safety(
            [
                source_run / "profile_index_robustness_report.md",
                source_run / "profile_index_robustness_report.json",
                source_run / "final_collection_report.json",
            ]
        )
        if safety_findings:
            print(f"unsafe report content: {safety_findings}", file=sys.stderr)
            return 3
        print(json.dumps({"processed_dir": str(source_run), "report": counts, "live_fetch": False}, ensure_ascii=False))
        return 0
    processed_dir = args.processed_root / args.output_run_id
    raw_dir = args.raw_root / args.output_run_id
    if processed_dir.exists() and not args.resume:
        print(f"processed output exists; use --resume: {processed_dir}", file=sys.stderr)
        return 2
    processed_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "rejected_user_profiles.jsonl").touch(exist_ok=True)

    if args.env_file:
        load_dotenv(Path(args.env_file))
    settings = TikHubSettings.from_env()
    if args.limit_profile == "unbounded":
        settings = settings.model_copy(update={"max_users": None})
    profile_api_resolved = resolve_profile_api(args.profile_api, limit_profile=args.limit_profile)

    target_rows, target_audit, historical = build_profile_targets(
        source_run,
        args.processed_root,
        args.raw_root,
        source_raw_run=args.source_raw_run,
        sec_uid_evidence_runs=args.sec_uid_evidence_run,
        sec_uid_evidence_globs=args.sec_uid_evidence_glob,
    )
    write_target_audit(processed_dir, target_rows, target_audit)

    stats = CollectionStats()
    stats.profile_api_requested = args.profile_api
    stats.profile_api_resolved = profile_api_resolved
    if not args.audit_only:
        fetchable = classify_fetchable(target_rows)
        if fetchable:
            ready, reason = settings.live_readiness()
            if not ready:
                stats.partial = True
                stats.partial_reason = f"live_unavailable:{reason}"
        else:
            stats.partial = True
            stats.partial_reason = "no_confirmed_sec_uid"
        if classify_fetchable(target_rows) and not stats.partial:
            client = TikHubClient(settings)
            stats = collect_profiles(
                target_rows,
                raw_dir,
                client,
                resume=args.resume,
                max_users=effective_profile_limit(args, settings),
                api_key=settings.api_key,
                profile_api=profile_api_resolved,
                retry_failed_profiles=args.retry_failed_profiles,
                max_batch_http400_splits=max(0, args.max_batch_http400_splits),
            )
            stats.profile_api_requested = args.profile_api
            stats.profile_api_resolved = profile_api_resolved
    else:
        stats.partial = True
        stats.partial_reason = "audit_only"

    processed_counts = build_processed_outputs(source_run, processed_dir, raw_dir, target_rows, historical, stats)
    report = build_collection_report(
        run_id=args.output_run_id,
        source_run=source_run,
        processed_dir=processed_dir,
        raw_dir=raw_dir,
        target_rows=target_rows,
        target_audit=target_audit,
        processed_counts=processed_counts,
        stats=stats,
        settings=settings,
    )
    write_collection_docs(processed_dir, report)
    doc_path = write_validation_doc(args.docs_dir, report)
    safety_findings = scan_report_safety([
        processed_dir / "profile_target_audit.md",
        processed_dir / "sec_uid_evidence_audit.md",
        processed_dir / "profile_collection_audit.md",
        processed_dir / "README.md",
        processed_dir / "sec_uid_evidence_audit.json",
        processed_dir / "profile_collection_report.json",
        processed_dir / "profile_collection_audit.json",
        doc_path,
    ])
    if safety_findings:
        print(f"unsafe report content: {safety_findings}", file=sys.stderr)
        return 3
    print(json.dumps({"processed_dir": str(processed_dir), "raw_dir": str(raw_dir), "doc_path": str(doc_path), "report": report}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
