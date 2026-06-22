#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from llm_abm_sim.data_sources.cli import load_dotenv  # noqa: E402
from llm_abm_sim.data_sources.douyin_models import PROFILE_COLUMNS, USER_COLUMNS  # noqa: E402
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
    "observed_activity_level",
    "observed_influence",
    "interest_tags",
    "brand_attitude",
    "activity_level",
    "like_tendency",
    "comment_tendency",
    "share_tendency",
    "profile_source",
    "profile_fetch_status",
    "attribute_provenance",
]
STATUS_COLUMNS = [
    "user_id",
    "sec_user_id",
    "status",
    "error",
    "attempted_at",
]


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


def is_quota_error(message: str) -> bool:
    text = message.lower()
    return any(token in text for token in ["quota", "rate limit", "too many", "402", "429", "insufficient balance"])


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
        level = row.get("comment_level", "comment")
        if level == "reply" or row.get("parent_comment_id"):
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


def discover_current_raw_sec_uids(source_run: Path, raw_base: Path, source_raw_run: Path | None = None) -> dict[str, tuple[str, str]]:
    """Recover explicit sec_uid values from the source run's raw artifacts.

    By default the collector uses the repository convention that a processed run
    and its raw run share the same run id. Callers can override that convention
    with ``--source-raw-run`` when deriving from a copied/renamed processed run.
    Only explicit raw ``sec_uid``/``sec_user_id`` evidence is accepted.
    """

    raw_root = source_raw_run or raw_base / source_run.name
    found: dict[str, tuple[str, str]] = {}
    for filename, source in [
        ("video_details.jsonl", "raw_video_details"),
        ("comments.jsonl", "raw_comments"),
        ("comment_replies.jsonl", "raw_replies"),
        ("user_profiles.jsonl", "raw_profiles"),
    ]:
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
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, HistoricalProfile]]:
    users = read_csv(source_run / "users.csv")
    if not users:
        raise ValueError(f"missing or empty users.csv: {source_run / 'users.csv'}")
    metrics_by_user, source_meta = source_role_and_metrics(source_run)
    user_ids = {row.get("user_id", "") for row in users if row.get("user_id")}
    effective_source_raw_run = source_raw_run or raw_root / source_run.name
    raw_secs = discover_current_raw_sec_uids(source_run, raw_root, effective_source_raw_run)
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
        if source in {"missing", "placeholder"} and uid in raw_secs:
            sec, source = raw_secs[uid]
        if source in {"missing", "placeholder"} and uid in historical_secs:
            sec, source = historical_secs[uid]
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
        "source_raw_run_contract": "Defaults to raw_root/source_run.name; override with --source-raw-run when the raw run id differs.",
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
        "scope_checks": validate_scope(source_run),
    }
    return rows, audit, historical_profiles


def write_target_audit(processed_dir: Path, target_rows: list[dict[str, Any]], audit: Mapping[str, Any]) -> None:
    public_rows = [{k: v for k, v in row.items() if not k.startswith("_")} for row in target_rows]
    write_csv(processed_dir / "profile_target_users.csv", PROFILE_FIELDNAMES, public_rows)
    (processed_dir / "profile_target_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
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


def load_statuses(raw_dir: Path) -> dict[str, dict[str, str]]:
    statuses: dict[str, dict[str, str]] = {}
    for row in read_csv(raw_dir / "profile_status.csv"):
        uid = row.get("user_id", "")
        if uid:
            statuses[uid] = row
    return statuses


def write_statuses(raw_dir: Path, statuses: Mapping[str, Mapping[str, Any]]) -> None:
    write_csv(raw_dir / "profile_status.csv", STATUS_COLUMNS, statuses.values())


def classify_fetchable(target_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in target_rows if str(row.get("profile_fetch_status")) == "pending" and str(row.get("sec_user_id_confidence")) in {"confirmed", "confirmed_equal_user_id"}]


def profile_item_matches_target(item: dict[str, Any], target_user_id: str, requested_sec_user_id: str) -> bool:
    user = normalize_profile_payload(item)
    normalized_uid = str(user.get("user_id") or "")
    normalized_sec = str(user.get("sec_user_id") or "")
    return bool((normalized_uid and normalized_uid == target_user_id) or (normalized_sec and normalized_sec == requested_sec_user_id))


def accepted_profile_items(result: Any, target_user_id: str, requested_sec_user_id: str) -> list[dict[str, Any]]:
    items = extract_user_items(result)
    accepted: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict) and profile_item_matches_target(item, target_user_id, requested_sec_user_id):
            accepted.append(item)
    return accepted


def collect_profiles(
    target_rows: list[dict[str, Any]],
    raw_dir: Path,
    client: TikHubClient,
    *,
    resume: bool,
    max_users: int | None,
    api_key: str,
) -> CollectionStats:
    statuses = load_statuses(raw_dir) if resume else {}
    fetchable = classify_fetchable(target_rows)
    if max_users is not None:
        fetchable = fetchable[:max_users]
    stats = CollectionStats(endpoint_call_counts=client.endpoint_call_counts)
    for row in fetchable:
        uid = str(row["user_id"])
        sec = str(row["sec_user_id"])
        existing = statuses.get(uid)
        if resume and existing and existing.get("status") in {"success", "failed", "quota_stopped"}:
            if existing.get("status") == "success":
                row["profile_fetch_status"] = "success"
            elif existing.get("status") == "failed":
                row["profile_fetch_status"] = "failed"
                row["skip_reason"] = existing.get("error", "failed")
            continue
        stats.attempted += 1
        try:
            result = client.handler_user_profile(sec)
            success_items = accepted_profile_items(result, uid, sec)
            if not success_items:
                message = "identity_mismatch_or_empty_profile_response"
                append_jsonl(
                    raw_dir / "rejected_user_profiles.jsonl",
                    {"user_id": uid, "sec_user_id": sec, "reason": message, "response": redact_secrets(result, [api_key]), "fetched_at": now_iso()},
                )
                statuses[uid] = {"user_id": uid, "sec_user_id": sec, "status": "failed", "error": message, "attempted_at": now_iso()}
                row["profile_fetch_status"] = "failed"
                row["skip_reason"] = message
                stats.failed += 1
                continue
            append_jsonl(raw_dir / "user_profiles.jsonl", {"user_id": uid, "sec_user_id": sec, "response": result, "items": success_items, "fetched_at": now_iso()})
            statuses[uid] = {"user_id": uid, "sec_user_id": sec, "status": "success", "error": "", "attempted_at": now_iso()}
            row["profile_fetch_status"] = "success"
            stats.succeeded += 1
        except Exception as exc:  # noqa: BLE001 - per-profile failure is recorded and collection continues.
            message = str(redact_secrets(str(exc), [api_key]))
            status = "quota_stopped" if is_quota_error(message) else "failed"
            statuses[uid] = {"user_id": uid, "sec_user_id": sec, "status": status, "error": message, "attempted_at": now_iso()}
            row["profile_fetch_status"] = "failed"
            row["skip_reason"] = message
            stats.failed += 1
            if status == "quota_stopped":
                stats.partial = True
                stats.partial_reason = "quota_or_rate_limit"
                stats.quota_or_rate_limited = True
                break
        finally:
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


def build_abm_row(target: Mapping[str, Any], user: Mapping[str, Any], profile_source: str, fetch_status: str) -> dict[str, Any]:
    comment_count = parse_int(target.get("comment_count"))
    reply_count = parse_int(target.get("reply_count"))
    edge_degree = parse_int(target.get("edge_degree"))
    comment_like_sum = parse_int(target.get("comment_like_sum"))
    follower_count = parse_int(user.get("follower_count"))
    video_count = parse_int(user.get("video_count"))
    observed_activity = max(parse_float(user.get("observed_activity_level"), 0.0), bounded_ratio(video_count, 100), bounded_ratio(comment_count + reply_count, 20))
    observed_influence = max(parse_float(user.get("observed_influence"), 0.0), bounded_log_ratio(follower_count), bounded_log_ratio(edge_degree + comment_like_sum, 4.0))
    verified = str(user.get("verified_type") or "")
    role = str(target.get("user_role") or "observed")
    if verified and verified not in {"0", "False", "false", ""}:
        user_type = "verified"
    elif target.get("priority_tier") == "creator":
        user_type = "creator"
    elif observed_influence >= 0.6:
        user_type = "kol_or_central_user"
    else:
        user_type = role
    interest_tags = sorted(set(target.get("_interest_tags") or []))
    provenance = {
        "observed_api_fields": ["follower_count", "following_count", "video_count", "verified_type"] if profile_source != "none" else [],
        "interaction_observed_fields": ["comment_count", "reply_count", "edge_degree", "comment_like_sum"],
        "derived_fields": ["observed_activity_level", "observed_influence", "interest_tags", "user_type"],
        "defaulted_future_model_fields": ["brand_attitude", "like_tendency", "comment_tendency", "share_tendency"],
    }
    return {
        "user_id": target.get("user_id", ""),
        "user_type": user_type,
        "follower_count": follower_count,
        "following_count": parse_int(user.get("following_count")),
        "video_count": video_count,
        "verified_type": verified,
        "observed_activity_level": round(observed_activity, 6),
        "observed_influence": round(observed_influence, 6),
        "interest_tags": interest_tags,
        "brand_attitude": 0.0,
        "activity_level": round(observed_activity, 6),
        "like_tendency": 0.5,
        "comment_tendency": 0.2,
        "share_tendency": 0.2,
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
) -> dict[str, int]:
    source_users_by_id = {row.get("user_id", ""): row for row in read_csv(source_run / "users.csv")}
    live_profiles = load_current_live_profiles(raw_dir)
    statuses = load_statuses(raw_dir)
    user_rows: list[dict[str, Any]] = []
    profile_rows: list[dict[str, Any]] = []
    abm_rows: list[dict[str, Any]] = []
    failed_rows: list[dict[str, Any]] = []
    missing_rows: list[dict[str, Any]] = []
    target_public_rows: list[dict[str, Any]] = []
    for target in target_rows:
        uid = str(target["user_id"])
        status = statuses.get(uid, {})
        if status.get("status") == "success":
            target["profile_fetch_status"] = "success"
            target["skip_reason"] = ""
        elif status.get("status") in {"failed", "quota_stopped"}:
            target["profile_fetch_status"] = "failed"
            target["skip_reason"] = status.get("error", "failed")
        elif target.get("profile_fetch_status") == "pending" and stats.partial:
            target["profile_fetch_status"] = "skipped"
            target["skip_reason"] = stats.partial_reason or "partial_stop"
        live = live_profiles.get(uid)
        hist = historical.get(uid)
        user, source = merge_profile_user(target, live, hist, source_users_by_id.get(uid, {}))
        fetch_status = str(target.get("profile_fetch_status") or "skipped")
        user_rows.append(user)
        if fetch_status == "failed":
            failed_rows.append({k: target.get(k, "") for k in PROFILE_FIELDNAMES})
        if target.get("sec_user_id_confidence") in {"missing", "placeholder"}:
            missing_rows.append({k: target.get(k, "") for k in PROFILE_FIELDNAMES})
        abm = build_abm_row(target, user, source, fetch_status)
        abm_rows.append(abm)
        if source != "none" and fetch_status in {"success", "skipped", "failed"}:
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
    return {
        "users": len(user_rows),
        "profiles": len(deduped_profiles),
        "abm_user_profiles": len(abm_rows),
        "failed_profile_users": len(failed_rows),
        "missing_sec_uid_users": len(missing_rows),
        "live_profiles": len(live_profiles),
        "historical_profiles_used": len([r for r in users_out if str(r.get("profile_source", "")).startswith("historical")]),
    }


def field_coverage(rows: list[dict[str, str]], fields: list[str]) -> dict[str, int]:
    return {field: sum(1 for row in rows if str(row.get(field, "")).strip()) for field in fields}


def effective_profile_limit(args: argparse.Namespace, settings: TikHubSettings) -> int | None:
    if args.max_users is not None:
        return args.max_users
    if args.limit_profile == "unbounded":
        return None
    return settings.max_users


def expansion_state(stats: CollectionStats, pending_after: int, partial_reason: str) -> str:
    if partial_reason == "audit_only":
        return "audit_only"
    if partial_reason == "no_confirmed_sec_uid" and stats.attempted == 0:
        return "derived_only_no_confirmed_sec_uid"
    if partial_reason.startswith("live_unavailable") and stats.attempted == 0:
        return "live_unavailable"
    if stats.attempted > 0 and pending_after == 0 and not stats.partial:
        return "live_profile_complete"
    if stats.attempted > 0:
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
    coverage = profile_field_coverage(users, target_rows)
    missing_count = len([row for row in target_rows if row.get("sec_user_id_confidence") in {"missing", "placeholder"}])
    pending_after = len([row for row in target_rows if row.get("profile_fetch_status") == "pending"])
    partial = stats.partial or pending_after > 0
    partial_reason = stats.partial_reason or ("pending_profiles_after_run" if pending_after else "")
    state = expansion_state(stats, pending_after, partial_reason)
    return {
        "run_id": run_id,
        "created_at": now_iso(),
        "source_dataset_path": str(source_run),
        "raw_dir": str(raw_dir),
        "processed_dir": str(processed_dir),
        "target_users": len(target_rows),
        "source_unique_users": target_audit.get("source_unique_users"),
        "attempted_profiles": stats.attempted,
        "successful_profiles": stats.succeeded,
        "failed_profiles": processed_counts.get("failed_profile_users", 0),
        "missing_sec_uid_users": missing_count,
        "skipped_profiles": len([row for row in target_rows if row.get("profile_fetch_status") == "skipped"]),
        "profiles_collected": stats.attempted > 0 and stats.succeeded > 0,
        "partial": partial,
        "partial_reason": partial_reason,
        "expansion_state": state,
        "quota_or_rate_limited": stats.quota_or_rate_limited,
        "limit_profile": "unbounded" if settings.max_users is None else "capped",
        "endpoint_call_counts": stats.endpoint_call_counts or {},
        "field_coverage": coverage,
        "processed_counts": dict(processed_counts),
        "target_audit_path": str(processed_dir / "profile_target_audit.json"),
        "scope_checks": target_audit.get("scope_checks", {}),
        "redacted_config": settings.redacted(),
        "secrets_read_printed_written": "no",
        "large_raw_processed_committed": "no",
        "private_csv_outputs": ["users.csv", "profiles.csv", "abm_user_profiles.csv", "profile_target_users.csv", "missing_sec_uid_users.csv", "failed_profile_users.csv"],
        "public_report_boundary": "Markdown reports contain aggregate statistics only; processed CSVs are local ignored research artifacts and must not be committed when they include profile-like fields.",
    }


def write_collection_docs(processed_dir: Path, report: Mapping[str, Any]) -> None:
    (processed_dir / "profile_collection_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (processed_dir / "profile_collection_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Profile collection audit",
        "",
        f"- source dataset: `{report.get('source_dataset_path')}`",
        f"- target users: {report.get('target_users')}",
        f"- attempted profiles: {report.get('attempted_profiles')}",
        f"- successful profiles: {report.get('successful_profiles')}",
        f"- failed profiles: {report.get('failed_profiles')}",
        f"- missing sec_uid users: {report.get('missing_sec_uid_users')}",
        f"- profiles_collected: {report.get('profiles_collected')}",
        f"- partial: {report.get('partial')}",
        f"- partial_reason: {report.get('partial_reason')}",
        f"- expansion_state: {report.get('expansion_state')}",
        f"- secrets read/printed/written: {report.get('secrets_read_printed_written')}",
        f"- raw/processed large data committed: {report.get('large_raw_processed_committed')}",
        "",
        "## Field coverage",
        "",
        "| field | non-empty rows |",
        "|---|---:|",
    ]
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
        f"- attempted profiles: {report.get('attempted_profiles')}",
        f"- successful profiles: {report.get('successful_profiles')}",
        f"- failed profiles: {report.get('failed_profiles')}",
        f"- missing sec_uid users: {report.get('missing_sec_uid_users')}",
        f"- profiles_collected: {report.get('profiles_collected')}",
        f"- partial: {report.get('partial')}",
        f"- partial_reason: {report.get('partial_reason')}",
        f"- expansion_state: {report.get('expansion_state')}",
        "- quota/rate limit: see partial_reason and endpoint_call_counts",
        "- secrets read/printed/written: no",
        "- raw/processed large data committed: no",
        "",
        "## 字段覆盖率",
        "",
        "| 字段 | 非空行数 |",
        "|---|---:|",
    ]
    for key, value in sorted((report.get("field_coverage") or {}).items()):
        lines.append(f"| {key} | {value} |")
    lines.extend([
        "",
        "说明：本文档只展示聚合统计，不展开昵称、bio、signature 等用户明细。`brand_attitude` 与分享倾向等字段当前为后续模型默认/派生字段，不视为真实观测行为。",
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
    parser.add_argument("--max-users", type=int)
    parser.add_argument("--limit-profile", choices=["capped", "unbounded"], default="capped")
    parser.add_argument("--processed-root", type=Path, default=PROCESSED_ROOT)
    parser.add_argument("--raw-root", type=Path, default=RAW_ROOT)
    parser.add_argument(
        "--source-raw-run",
        type=Path,
        help="Raw source run directory for sec_uid recovery. Defaults to raw-root/source-run-name.",
    )
    parser.add_argument("--docs-dir", type=Path, default=Path("docs/04-开发验证"))
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args(argv)

    source_run = args.source_run
    if not source_run.exists():
        print(f"source run not found: {source_run}", file=sys.stderr)
        return 2
    processed_dir = args.processed_root / args.output_run_id
    raw_dir = args.raw_root / args.output_run_id
    if processed_dir.exists() and not args.resume:
        print(f"processed output exists; use --resume: {processed_dir}", file=sys.stderr)
        return 2
    processed_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    if args.env_file:
        load_dotenv(Path(args.env_file))
    settings = TikHubSettings.from_env()
    if args.limit_profile == "unbounded":
        settings = settings.model_copy(update={"max_users": None})

    target_rows, target_audit, historical = build_profile_targets(source_run, args.processed_root, args.raw_root, source_raw_run=args.source_raw_run)
    write_target_audit(processed_dir, target_rows, target_audit)

    stats = CollectionStats()
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
            stats = collect_profiles(target_rows, raw_dir, client, resume=args.resume, max_users=effective_profile_limit(args, settings), api_key=settings.api_key)
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
        processed_dir / "profile_collection_audit.md",
        processed_dir / "README.md",
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
