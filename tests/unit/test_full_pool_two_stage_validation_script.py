from __future__ import annotations

import json
import runpy
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

_SCRIPT = runpy.run_path(
    str(Path(__file__).parents[2] / "scripts" / "run_full_pool_two_stage_validation.py")
)
_guard_new_paths = cast(Callable[..., tuple[Path, Path]], _SCRIPT["_guard_new_paths"])
_validation_facts = cast(Callable[[Path], dict[str, Any]], _SCRIPT["_validation_facts"])


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _full_pool_validation_fixture(root: Path) -> None:
    root.mkdir()
    segment_sizes = {"S1": 12_000, "S2": 12_000, "S3": 12_400}
    engagement_tenths = {
        ("S1", "M1"): 5,
        ("S1", "M2"): 6,
        ("S1", "M3"): 7,
        ("S2", "M1"): 2,
        ("S2", "M2"): 6,
        ("S2", "M3"): 4,
        ("S3", "M1"): 2,
        ("S3", "M2"): 4,
        ("S3", "M3"): 6,
    }
    rows: list[dict[str, int | str]] = []
    action_counts: Counter[str] = Counter()
    for segment, size in segment_sizes.items():
        quotient, remainder = divmod(size, 30)
        for message in ("M1", "M2", "M3"):
            for run in range(1, 31):
                exposure = quotient + (run <= remainder)
                likes = exposure * engagement_tenths[(segment, message)] // 10
                rows.append(
                    {
                        "Run": run,
                        "Message": message,
                        "Segment": segment,
                        "Total Likes": likes,
                        "Total Comments": 0,
                        "Total Shares": 0,
                        "Exposure": exposure,
                    }
                )
                action_counts.update({"like": likes, "ignore": exposure - likes})
    for action in ("comment", "share"):
        action_counts[action] = 0

    counts = {
        "users": 36_400,
        "messages": 3,
        "pairs": 109_200,
        "exposures": 109_200,
        "realized_terminals": 109_200,
        "batch_commits": 30,
        "candidate_rows": 1_691_730,
        "membership_rows": 36_400,
        "projection_rows": 270,
        "runtime_resident_row_high_water": 120_000,
    }
    _write_json(
        root / "manifest.json",
        {
            "counts": counts,
            "action_counts": {
                action: action_counts[action]
                for action in ("ignore", "like", "comment", "share")
            },
            "realization_status_counts": {
                "provider_ignore": 1,
                "draw_pass": action_counts["like"],
                "draw_fail": action_counts["ignore"] - 1,
            },
            "production_deploy_eligible": False,
            "artifacts": [{"relative_path": "fixture", "sha256": "0" * 64, "bytes": 1}],
        },
    )
    _write_json(
        root / "realization-evidence.json",
        {
            "accounting": {
                "upstream": {
                    "logical_judgments": 109_200,
                    "live_api_triggered": True,
                    "formal_research_evidence": True,
                    "production_deploy_eligible": True,
                },
                "realization": {"live_api_triggered": False, "provider_calls": 0},
            }
        },
    )
    _write_json(root / "realized-projection.json", {"rows": rows})


def test_validation_facts_recompute_full_pool_metrics_and_preference_order(tmp_path: Path) -> None:
    output = tmp_path / "realized-source"
    _full_pool_validation_fixture(output)

    facts = _validation_facts(output)

    assert facts["message_order_by_segment"] == {
        "S1": ["M3", "M2", "M1"],
        "S2": ["M2", "M3", "M1"],
        "S3": ["M3", "M2", "M1"],
    }
    assert facts["overall_single_exposure"]["exposure"] == 109_200  # type: ignore[index]
    assert facts["realization_accounting"] == {
        "live_api_triggered": False,
        "provider_calls": 0,
    }


def test_validation_paths_cannot_overlap_protected_artifacts(tmp_path: Path) -> None:
    protected = tmp_path / "immutable"
    protected.mkdir()

    with pytest.raises(ValueError, match="overlap"):
        _guard_new_paths(
            output=protected / "must-not-write",
            run_record=tmp_path / "record.json",
            protected_roots=[protected.resolve()],
            protected_files=[],
        )
