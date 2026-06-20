#!/usr/bin/env python3
"""Summarize existing Jinjiang Douyin topic/challenge/tag distribution.

This script is intentionally read-only for data inputs: it parses existing raw
TikHub page JSON and processed collection reports, then writes one aggregate
Markdown report. It does not import or call any TikHub client and does not read
.env files.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_RELATED = "jinjiang-related-unbounded-1y-20260612T133214Z"
RUN_ID_CAPPED = "jinjiang-hashtag-page-fixed-1y-20260612T103453Z"
RUN_ID_EXACT_ONLY = "jinjiang-hashtag-only-20260612T103453Z"
EXACT_CID = "1614016211862532"
EXACT_NAME = "锦江酒店"
WINDOW_START_TS = int(datetime(2025, 6, 12, tzinfo=timezone.utc).timestamp())
WINDOW_END_TS = int(datetime(2026, 6, 12, 23, 59, 59, tzinfo=timezone.utc).timestamp())

RAW_RUN_DIR = REPO_ROOT / "data/raw/tikhub/douyin/jinjiang_hotel" / RUN_ID_RELATED
PAGES_DIR = RAW_RUN_DIR / "pages"
RELATED_CHALLENGES = RAW_RUN_DIR / "related_challenges.json"
PROCESSED_DIR = REPO_ROOT / "data/processed/jinjiang_douyin"
RELATED_REPORT = PROCESSED_DIR / RUN_ID_RELATED / "collection_report.json"
CAPPED_REPORT = PROCESSED_DIR / RUN_ID_CAPPED / "collection_report.json"
EXACT_ONLY_REPORT = PROCESSED_DIR / RUN_ID_EXACT_ONLY / "collection_report.json"
OUTPUT_REPORT = REPO_ROOT / "docs/04-开发验证/jinjiang-douyin-existing-topic-distribution.md"

FILENAME_RE = re.compile(r"hashtag_video_list_(?P<cid>\d+)_cursor_(?P<cursor>\d+)\.json$")
HASHTAG_RE = re.compile(r"#([^#\s,，。；;：:！!？?、/\\|\[\]（）(){}<>《》\"'“”‘’]+)")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def text_of(value: Any) -> str:
    return value if isinstance(value, str) else ""


def video_id(item: dict[str, Any]) -> str | None:
    for key in ("aweme_id", "video_id", "id", "group_id"):
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return None


def create_time(item: dict[str, Any]) -> int | None:
    value = item.get("create_time")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def in_window(item: dict[str, Any]) -> bool:
    ts = create_time(item)
    return ts is not None and WINDOW_START_TS <= ts <= WINDOW_END_TS


def challenge_name_from_entry(entry: dict[str, Any]) -> str | None:
    for key in ("cha_name", "challenge_name", "hashtag_name", "name", "title"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lstrip("#")
    return None


def extract_tags(item: dict[str, Any]) -> set[str]:
    tags: set[str] = set()

    cha_list = item.get("cha_list")
    if isinstance(cha_list, list):
        for entry in cha_list:
            if isinstance(entry, dict):
                name = challenge_name_from_entry(entry)
                if name:
                    tags.add(name)

    text_extra = item.get("text_extra")
    if isinstance(text_extra, list):
        for entry in text_extra:
            if not isinstance(entry, dict):
                continue
            # Douyin hashtag markers usually use type=1 and hashtag_id/name.
            type_value = entry.get("type")
            has_hashtag_hint = any(k in entry for k in ("hashtag_name", "cha_name", "hashtag_id", "cid", "challenge_id"))
            if type_value in (1, "1", "hashtag", "challenge") or has_hashtag_hint:
                for key in ("hashtag_name", "cha_name", "challenge_name", "name"):
                    value = entry.get(key)
                    if isinstance(value, str) and value.strip():
                        tags.add(value.strip().lstrip("#"))

    caption = " ".join(text_of(item.get(key)) for key in ("caption", "desc", "title"))
    for match in HASHTAG_RE.finditer(caption):
        tag = match.group(1).strip().lstrip("#")
        if tag:
            tags.add(tag)

    return tags


@dataclass
class ChallengeStats:
    cid: str
    name: str = ""
    page_count: int = 0
    raw_rows: int = 0
    unique_videos: set[str] = field(default_factory=set)
    in_window_unique_videos: set[str] = field(default_factory=set)
    cursors: set[int] = field(default_factory=set)


@dataclass
class Aggregation:
    related_challenges_count: int
    related_challenge_map: dict[str, str]
    page_files: int
    challenge_stats: dict[str, ChallengeStats]
    global_raw_rows: int
    global_unique_videos: set[str]
    global_in_window_unique_videos: set[str]
    related_tag_rows: Counter[str]
    related_tag_videos: dict[str, set[str]]
    exact_tag_rows: Counter[str]
    exact_tag_videos: dict[str, set[str]]
    exact_page_files: list[Path]
    exact_cursors: list[int]
    exact_raw_rows: int
    exact_unique_videos: set[str]
    exact_in_window_unique_videos: set[str]
    exact_caption_has_hash: set[str]
    exact_caption_has_plain: set[str]
    exact_field_has_exact: set[str]
    exact_last_page: str | None
    exact_last_page_items: int | None


def inc_tag_counters(tags: Iterable[str], vid: str | None, row_counter: Counter[str], video_map: dict[str, set[str]]) -> None:
    for tag in tags:
        row_counter[tag] += 1
        if vid:
            video_map[tag].add(vid)


def aggregate() -> Aggregation:
    related = load_json(RELATED_CHALLENGES)
    if not isinstance(related, list):
        raise TypeError(f"{RELATED_CHALLENGES} must contain a list")
    challenge_map: dict[str, str] = {}
    for entry in related:
        if isinstance(entry, dict):
            cid = str(entry.get("cid") or entry.get("challenge_id") or "").strip()
            name = challenge_name_from_entry(entry)
            if cid:
                challenge_map[cid] = name or cid

    stats: dict[str, ChallengeStats] = {
        cid: ChallengeStats(cid=cid, name=name) for cid, name in challenge_map.items()
    }
    global_unique: set[str] = set()
    global_window: set[str] = set()
    related_tag_rows: Counter[str] = Counter()
    related_tag_videos: dict[str, set[str]] = defaultdict(set)
    exact_tag_rows: Counter[str] = Counter()
    exact_tag_videos: dict[str, set[str]] = defaultdict(set)
    exact_page_files: list[Path] = []
    exact_cursors: list[int] = []
    exact_unique: set[str] = set()
    exact_window: set[str] = set()
    exact_caption_hash: set[str] = set()
    exact_caption_plain: set[str] = set()
    exact_field_exact: set[str] = set()
    exact_raw_rows = 0
    global_raw_rows = 0
    exact_last_page = None
    exact_last_page_items = None

    page_paths = sorted(PAGES_DIR.glob("hashtag_video_list_*_cursor_*.json"))
    for path in page_paths:
        match = FILENAME_RE.search(path.name)
        if not match:
            continue
        cid = match.group("cid")
        cursor = int(match.group("cursor"))
        data = load_json(path)
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            items = []

        stat = stats.setdefault(cid, ChallengeStats(cid=cid, name=challenge_map.get(cid, cid)))
        stat.name = stat.name or challenge_map.get(cid, cid)
        stat.page_count += 1
        stat.raw_rows += len(items)
        stat.cursors.add(cursor)

        if cid == EXACT_CID:
            exact_page_files.append(path)
            exact_cursors.append(cursor)
            if exact_last_page is None or cursor > max([c for c in exact_cursors if c != cursor], default=-1):
                exact_last_page = path.name
                exact_last_page_items = len(items)

        for item in items:
            if not isinstance(item, dict):
                continue
            vid = video_id(item)
            global_raw_rows += 1
            if vid:
                global_unique.add(vid)
                stat.unique_videos.add(vid)
                if in_window(item):
                    global_window.add(vid)
                    stat.in_window_unique_videos.add(vid)
            tags = extract_tags(item)
            inc_tag_counters(tags, vid, related_tag_rows, related_tag_videos)

            if cid == EXACT_CID:
                exact_raw_rows += 1
                if vid:
                    exact_unique.add(vid)
                    if in_window(item):
                        exact_window.add(vid)
                    text = " ".join(text_of(item.get(key)) for key in ("caption", "desc", "title"))
                    if f"#{EXACT_NAME}" in text:
                        exact_caption_hash.add(vid)
                    if EXACT_NAME in text:
                        exact_caption_plain.add(vid)
                    if EXACT_NAME in tags:
                        exact_field_exact.add(vid)
                inc_tag_counters(tags, vid, exact_tag_rows, exact_tag_videos)

    # Correct last exact page by numeric cursor after all pages are known.
    if exact_page_files:
        last = max(exact_page_files, key=lambda p: int(FILENAME_RE.search(p.name).group("cursor")))  # type: ignore[union-attr]
        last_data = load_json(last)
        last_items = last_data.get("items") if isinstance(last_data, dict) else []
        exact_last_page = last.name
        exact_last_page_items = len(last_items) if isinstance(last_items, list) else 0

    return Aggregation(
        related_challenges_count=len(challenge_map),
        related_challenge_map=challenge_map,
        page_files=len(page_paths),
        challenge_stats=stats,
        global_raw_rows=global_raw_rows,
        global_unique_videos=global_unique,
        global_in_window_unique_videos=global_window,
        related_tag_rows=related_tag_rows,
        related_tag_videos=related_tag_videos,
        exact_tag_rows=exact_tag_rows,
        exact_tag_videos=exact_tag_videos,
        exact_page_files=exact_page_files,
        exact_cursors=sorted(exact_cursors),
        exact_raw_rows=exact_raw_rows,
        exact_unique_videos=exact_unique,
        exact_in_window_unique_videos=exact_window,
        exact_caption_has_hash=exact_caption_hash,
        exact_caption_has_plain=exact_caption_plain,
        exact_field_has_exact=exact_field_exact,
        exact_last_page=exact_last_page,
        exact_last_page_items=exact_last_page_items,
    )


def fmt_int(value: int | None) -> str:
    if value is None:
        return "-"
    return f"{value:,}"


def md_escape(value: Any) -> str:
    text = str(value) if value is not None else ""
    return text.replace("|", "\\|").replace("\n", " ")


def table(headers: list[str], rows: Iterable[Iterable[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(md_escape(cell) for cell in row) + " |")
    return "\n".join(lines)


def tag_rows(tag_row_counter: Counter[str], tag_video_map: dict[str, set[str]], limit: int = 50) -> list[list[Any]]:
    sorted_tags = sorted(tag_row_counter.keys(), key=lambda tag: (-len(tag_video_map.get(tag, set())), -tag_row_counter[tag], tag))[:limit]
    return [[rank, tag, fmt_int(len(tag_video_map.get(tag, set()))), fmt_int(tag_row_counter[tag])] for rank, tag in enumerate(sorted_tags, 1)]


def report_value(report: dict[str, Any], path: tuple[str, ...]) -> Any:
    node: Any = report
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def limits_text(report: dict[str, Any]) -> str:
    raw_limits = report.get("limits")
    limits: dict[str, Any] = raw_limits if isinstance(raw_limits, dict) else {}
    keys = ["max_videos", "max_comments_per_video", "max_replies_per_comment", "max_users", "max_search_pages"]
    parts: list[str] = []
    for key in keys:
        if key in limits:
            parts.append(f"{key}: {limits[key]}")
    if "max_search_pages" not in limits:
        parts.append("max_search_pages: 20（任务背景记录；当前 collection_report.json 未显式保存该字段）")
    return "; ".join(parts) if parts else "未在 report 中找到 limits"


def generate_markdown(agg: Aggregation) -> str:
    related_report = load_json(RELATED_REPORT)
    capped_report = load_json(CAPPED_REPORT)
    exact_only_report = load_json(EXACT_ONLY_REPORT)

    challenge_rows = []
    for stat in sorted(
        agg.challenge_stats.values(),
        key=lambda s: (-len(s.in_window_unique_videos), -len(s.unique_videos), s.name, s.cid),
    ):
        challenge_rows.append([
            len(challenge_rows) + 1,
            stat.cid,
            stat.name,
            fmt_int(stat.page_count),
            fmt_int(stat.raw_rows),
            fmt_int(len(stat.unique_videos)),
            fmt_int(len(stat.in_window_unique_videos)),
        ])

    simple_challenge_rows = [
        [row[2], row[6]] for row in challenge_rows[:50]
    ]

    exact_stat = agg.challenge_stats.get(EXACT_CID)
    exact_row = []
    if exact_stat:
        exact_rank = next((row[0] for row in challenge_rows if row[1] == EXACT_CID), "-")
        exact_row = [[
            exact_rank,
            EXACT_CID,
            EXACT_NAME,
            fmt_int(exact_stat.page_count),
            fmt_int(exact_stat.raw_rows),
            fmt_int(len(exact_stat.unique_videos)),
            fmt_int(len(exact_stat.in_window_unique_videos)),
        ]]

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    cursor_min = min(agg.exact_cursors) if agg.exact_cursors else None
    cursor_max = max(agg.exact_cursors) if agg.exact_cursors else None

    related_counts = related_report.get("counts", {}) if isinstance(related_report, dict) else {}
    related_dedupe = related_report.get("dedupe_counts", {}) if isinstance(related_report, dict) else {}
    report_deduped_videos = related_dedupe.get("deduped_videos") or related_dedupe.get("unique_video_refs")
    exact_only_counts = exact_only_report.get("counts", {}) if isinstance(exact_only_report, dict) else {}
    blocker = related_report.get("blocker", {}) if isinstance(related_report, dict) else {}
    failure_summary = related_report.get("failure_summary", {}) if isinstance(related_report, dict) else {}

    md = f"""# 现有抖音话题/标签分布说明：锦江酒店相关数据

生成时间：{now}

本报告只统计仓库中**已经存在**的 TikHub/Douyin raw/processed 数据；本次没有重新爬取、没有请求 TikHub、没有读取 `.env`、没有删除任何已有数据。报告只输出聚合统计，不列出用户昵称、bio 或其他个人资料明细。

> 口径提示：本脚本是针对当前 `2026-06-12` 锦江酒店数据快照的可复现渲染器，run_id、cid、时间窗口和校验数值均有意固定在脚本中；如未来换 run 复用，应先显式调整这些快照参数。

## 1. 数据来源与口径

### 1.1 related topics 无业务上限话题页 run

- run_id: `{RUN_ID_RELATED}`
- raw: `data/raw/tikhub/douyin/jinjiang_hotel/{RUN_ID_RELATED}/`
- processed: `data/processed/jinjiang_douyin/{RUN_ID_RELATED}/`
- 含义：不是只看 `#锦江酒店`，而是“锦江酒店相关话题”的 related challenge/topic 采集。
- challenge 发现接口：`fetch_challenge_search_v2`
- 视频页接口：`fetch_hashtag_video_list`
- 时间窗口：`2025-06-12` 到 `2026-06-12`（本报告近一年口径按 create_time 过滤）。

### 1.2 exact `#锦江酒店` capped baseline（不是全量）

- run_id: `{RUN_ID_CAPPED}`
- processed: `data/processed/jinjiang_douyin/{RUN_ID_CAPPED}/`
- 派生整理目录：`data/processed/jinjiang_douyin/{RUN_ID_EXACT_ONLY}/`
- 重要限制：这个 exact-only 目录来自 capped baseline 的复制/整理，**不是 all-in，也不是全量**，只能作为受控样本。
- baseline limits: {limits_text(capped_report)}
- exact-only 派生目录 report counts: videos={fmt_int(exact_only_counts.get('videos'))}, comments={fmt_int(exact_only_counts.get('comments'))}, replies={fmt_int(exact_only_counts.get('replies'))}; these are capped sample counts, not full coverage.

### 1.3 exact `#锦江酒店` 在 related unbounded run 里的话题页数据

- challenge name: `{EXACT_NAME}`
- challenge_id/cid: `{EXACT_CID}`
- 来源：`{RUN_ID_RELATED}` 的 `hashtag_video_list_{EXACT_CID}_cursor_*.json` 页面。
- 注意：这是 related run 中的 `#锦江酒店` 话题页数据，不等同于 capped baseline，也不等同于评论全量。

## 2. 全局汇总

| 指标 | 当前统计值 | 说明 |
| --- | ---: | --- |
| related challenge 总数 | {fmt_int(agg.related_challenges_count)} | 来自 `related_challenges.json` |
| hashtag_video_list page 文件数 | {fmt_int(agg.page_files)} | 本地 raw pages 目录下的页面 JSON 文件数 |
| raw video rows | {fmt_int(agg.global_raw_rows)} | 所有话题页 items 行数，未去重 |
| 全局去重 video_id 数 | {fmt_int(len(agg.global_unique_videos))} | 同一视频可能出现在多个 challenge 下 |
| 近一年全局去重 video_id 数 | {fmt_int(len(agg.global_in_window_unique_videos))} | create_time 在 2025-06-12 到 2026-06-12 内 |
| processed report: hashtag aweme rows | {fmt_int(related_counts.get('videos'))} | `collection_report.json` 的 processed 计数 |
| processed report: near-year deduped videos | {fmt_int(report_deduped_videos)} | `collection_report.json` 的窗口内去重视频计数；全局 raw 去重见上方 12,413 |
| processed report: comments | {fmt_int(related_counts.get('comments'))} | comments/replies 阶段已被 402 阻断，不能代表全量 |
| processed report: replies | {fmt_int(related_counts.get('replies'))} | comments/replies 阶段已被 402 阻断，不能代表全量 |

说明：per-challenge 视频数相加会大于全局去重数，因为同一视频可能挂多个话题或被多个话题页返回。`fetch_hashtag_video_list` 话题页也可能包含推荐/混排结果，因此“来自某话题页”不等于“标题文本必须包含该 hashtag”。

## 3. related unbounded run 中 exact `#锦江酒店` 话题页规模

{table(['rank', 'challenge_id', 'challenge_name', 'page_count', 'raw_video_rows', 'unique_video_ids', 'in_window_unique_video_ids'], exact_row)}

补充核对：

| 指标 | 当前统计值 |
| --- | ---: |
| exact `#锦江酒店` page 文件数 | {fmt_int(len(agg.exact_page_files))} |
| cursor 范围 | {cursor_min} 到 {cursor_max} |
| exact `#锦江酒店` raw rows | {fmt_int(agg.exact_raw_rows)} |
| exact `#锦江酒店` unique videos | {fmt_int(len(agg.exact_unique_videos))} |
| exact `#锦江酒店` 近一年 unique videos | {fmt_int(len(agg.exact_in_window_unique_videos))} |
| 最后一页 | `{agg.exact_last_page}` |
| 最后一页 items | {fmt_int(agg.exact_last_page_items)} |

## 4. challenge name | video number（近一年口径 Top 50）

以下 `video number` 指 `in_window_unique_video_ids`，即近一年窗口内按 video_id 去重后的视频数。

{table(['challenge name', 'video number'], simple_challenge_rows)}

## 5. Challenge 分布明细（全部 related challenges）

排序规则：先按 `in_window_unique_video_ids` 降序，再按 `unique_video_ids` 降序。

{table(['rank', 'challenge_id', 'challenge_name', 'page_count', 'raw_video_rows', 'unique_video_ids', 'in_window_unique_video_ids'], challenge_rows)}

## 6. 标签 / hashtag 分布

标签提取顺序：优先 `cha_list[].cha_name`，其次 `text_extra` 中的 `hashtag_name`/`cha_name` 等字段，再从 `caption`/`desc`/`title` 文本里用 `#xxx` 正则提取。`video_count` 是按 video_id 去重后的数量，`row_count` 是包含该标签的 aweme row 数。

### 6.1 全 related run 标签分布 Top 50

{table(['rank', 'tag', 'video_count', 'row_count'], tag_rows(agg.related_tag_rows, agg.related_tag_videos, 50))}

### 6.2 exact `#锦江酒店` 话题页内视频标签分布 Top 50

{table(['rank', 'tag', 'video_count', 'row_count'], tag_rows(agg.exact_tag_rows, agg.exact_tag_videos, 50))}

## 7. 标题包含情况：标题里是不是必须有 `#锦江酒店`？

针对 related unbounded run 里的 `{EXACT_CID}` / `{EXACT_NAME}` 话题页：

| 口径 | 去重视频数 | 说明 |
| --- | ---: | --- |
| 来自 `#锦江酒店` 话题页的视频 | {fmt_int(len(agg.exact_unique_videos))} | 以 source challenge/page cid 为准 |
| caption/desc/title 含 `#锦江酒店` | {fmt_int(len(agg.exact_caption_has_hash))} | 严格标题文本 hashtag 口径 |
| caption/desc/title 含 `锦江酒店` | {fmt_int(len(agg.exact_caption_has_plain))} | 标题文本包含品牌词口径，不要求 `#` |
| hashtags/cha_list/text_extra 含 exact `锦江酒店` | {fmt_int(len(agg.exact_field_has_exact))} | 结构化标签字段口径 |

解释：

- “来自 `#锦江酒店` 话题页”不等于“标题文本必须出现 `#锦江酒店`”。
- TikHub/Douyin 的话题页接口可能返回标题为空、标签字段缺失、或带有混排/推荐逻辑的视频。
- 如果用户要“标题必须含 `#锦江酒店`”，需要在话题页结果上再做严格标题过滤。
- 如果用户要“hashtags 字段含 exact `锦江酒店`”，这是另一个结构化标签字段口径。

## 8. capped / unbounded / 评论全量状态

| 数据目录/run | 当前定位 | 是否可称全量 |
| --- | --- | --- |
| `{RUN_ID_RELATED}` | 相关话题页视频索引 run；无业务上限地扫描 related challenges，但 comments/replies 后续被阻断 | 视频索引较完整；评论/回复不是全量 |
| `{RUN_ID_CAPPED}` | exact `#锦江酒店` capped baseline | 不是全量，只是受控样本 |
| `{RUN_ID_EXACT_ONLY}` | 从 capped baseline 复制/整理出来的 exact-only 目录 | 不是全量，只是更清晰命名的受控样本 |

评论/回复状态：

- related run 在 comments/replies 阶段遇到 TikHub `HTTP 402 Insufficient balance`。
- blocker 摘要：`{md_escape(blocker.get('type') or failure_summary.get('dominant_error') or 'HTTP 402 Insufficient balance')}`。
- 因此，当前数据不能说评论/回复是全量；本报告主要用于看“已有视频/话题/标签分布”。
- 评论互动网络、回复网络、用户扩散网络需要等 TikHub 余额恢复后继续补采。

## 9. 复现命令

```bash
python scripts/summarize_jinjiang_topic_distribution.py
python -m py_compile scripts/summarize_jinjiang_topic_distribution.py
```

生成报告：`docs/04-开发验证/jinjiang-douyin-existing-topic-distribution.md`
"""
    return md


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate(agg: Aggregation, markdown: str) -> None:
    require(agg.related_challenges_count == 181, f"unexpected related challenge count: {agg.related_challenges_count}")
    require(agg.page_files > 0, "no hashtag_video_list page files found")
    require(EXACT_CID in agg.challenge_stats, "exact cid missing from challenge stats")
    require(len(agg.exact_page_files) == 91, f"unexpected exact page count: {len(agg.exact_page_files)}")
    require(agg.exact_raw_rows == 790, f"unexpected exact raw row count: {agg.exact_raw_rows}")
    require(
        len(agg.exact_in_window_unique_videos) == 378,
        f"unexpected exact near-year count: {len(agg.exact_in_window_unique_videos)}",
    )
    require("12,413" in markdown, "global dedup video count missing from report")
    require("processed report: near-year deduped videos | 5,544" in markdown, "processed deduped video count missing")
    require("capped baseline" in markdown and "不是全量" in markdown, "capped baseline caveat missing")
    require("HTTP 402" in markdown and "不是全量" in markdown, "HTTP 402 non-full-comments caveat missing")
    require(EXACT_NAME in markdown and EXACT_CID in markdown, "exact challenge name/cid missing")


def main() -> None:
    for path in (PAGES_DIR, RELATED_CHALLENGES, RELATED_REPORT, CAPPED_REPORT, EXACT_ONLY_REPORT):
        if not path.exists():
            raise FileNotFoundError(path)
    agg = aggregate()
    markdown = generate_markdown(agg)
    validate(agg, markdown)
    OUTPUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_REPORT.write_text(markdown, encoding="utf-8")
    print(f"wrote {OUTPUT_REPORT.relative_to(REPO_ROOT)}")
    print(f"related_challenges={agg.related_challenges_count}")
    print(f"page_files={agg.page_files}")
    print(f"global_raw_rows={agg.global_raw_rows}")
    print(f"global_unique_videos={len(agg.global_unique_videos)}")
    print(f"global_in_window_unique_videos={len(agg.global_in_window_unique_videos)}")
    print(f"exact_pages={len(agg.exact_page_files)} exact_rows={agg.exact_raw_rows} exact_unique={len(agg.exact_unique_videos)} exact_in_window={len(agg.exact_in_window_unique_videos)}")


if __name__ == "__main__":
    main()
