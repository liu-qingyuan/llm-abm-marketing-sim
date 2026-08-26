#!/usr/bin/env python3
"""Run one explicit, zero-Provider Full-Pool two-stage validation replay."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import platform
import resource
import shutil
import tempfile
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path

from llm_abm_sim.concurrent_message_experiment import (
    CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_DELIVERY_CAPACITY,
    CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_HORIZON,
    CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_SAMPLE_SIZE,
)
from llm_abm_sim.full_pool_two_stage_replay import (
    FullPoolTwoStageReplay,
    FullPoolTwoStageReplayRequest,
)

_CONFIRMATION = "FULL_POOL_TWO_STAGE_VALIDATION_ZERO_PROVIDER"
_RECORD_SCHEMA = "full-pool-two-stage-validation-run-record-v1"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--source-manifest-sha256", required=True)
    parser.add_argument("--source-identity", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run-record", type=Path, required=True)
    parser.add_argument(
        "--protected-root",
        type=Path,
        action="append",
        default=[],
        help=(
            "Explicit immutable artifact root to hash before and after replay; repeatable. "
            "The Source-v4 root is protected automatically."
        ),
    )
    parser.add_argument(
        "--protected-file",
        type=Path,
        action="append",
        default=[],
        help="Explicit immutable artifact file to hash before and after replay; repeatable.",
    )
    parser.add_argument(
        "--confirm-zero-provider-validation",
        required=True,
        metavar="TOKEN",
        help=f"Exact opt-in token: {_CONFIRMATION}",
    )
    return parser


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _protected_snapshot(root: Path) -> dict[str, object]:
    candidate = root.expanduser()
    if candidate.is_symlink():
        raise ValueError(f"protected root must not be a symlink: {candidate}")
    resolved = candidate.resolve(strict=True)
    if resolved != candidate.absolute() or not resolved.is_dir():
        raise ValueError(f"protected root must be one explicit real directory: {candidate}")
    entries = tuple(sorted(resolved.rglob("*"), key=lambda path: path.as_posix()))
    if any(path.is_symlink() or not (path.is_file() or path.is_dir()) for path in entries):
        raise ValueError(f"protected root contains an unsafe entry: {resolved}")
    files = [
        {
            "relative_path": path.relative_to(resolved).as_posix(),
            "sha256": _sha256_file(path),
            "bytes": path.stat().st_size,
        }
        for path in entries
        if path.is_file()
    ]
    identity = hashlib.sha256(
        json.dumps(
            files,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "kind": "directory",
        "root": str(resolved),
        "file_count": len(files),
        "total_bytes": sum(int(row["bytes"]) for row in files),
        "inventory_sha256": identity,
    }


def _protected_file_snapshot(path: Path) -> dict[str, object]:
    candidate = path.expanduser()
    if candidate.is_symlink():
        raise ValueError(f"protected file must not be a symlink: {candidate}")
    resolved = candidate.resolve(strict=True)
    if resolved != candidate.absolute() or not resolved.is_file():
        raise ValueError(f"protected file must be one explicit real file: {candidate}")
    return {
        "kind": "file",
        "path": str(resolved),
        "sha256": _sha256_file(resolved),
        "bytes": resolved.stat().st_size,
    }


def _peak_rss_bytes() -> int:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if platform.system() == "Darwin" else peak * 1024)


def _json_object(path: Path, context: str) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{context} is missing or unsafe")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    return {str(key): item for key, item in value.items()}


def _mapping(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    return {str(key): item for key, item in value.items()}


def _integer(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{context} must be a non-negative integer")
    return value


def _validation_facts(output: Path) -> dict[str, object]:
    manifest = _json_object(output / "manifest.json", "realized manifest")
    evidence = _json_object(output / "realization-evidence.json", "realization evidence")
    projection = _json_object(output / "realized-projection.json", "realized projection")
    counts = _mapping(manifest.get("counts"), "realized counts")
    expected_candidates = 3 * sum(
        CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_SAMPLE_SIZE
        - CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_DELIVERY_CAPACITY * time_step
        for time_step in range(CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_HORIZON)
    )
    expected_counts = {
        "users": CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_SAMPLE_SIZE,
        "messages": 3,
        "pairs": CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_SAMPLE_SIZE * 3,
        "exposures": CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_SAMPLE_SIZE * 3,
        "realized_terminals": CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_SAMPLE_SIZE * 3,
        "batch_commits": CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_HORIZON,
        "candidate_rows": expected_candidates,
        "membership_rows": CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_SAMPLE_SIZE,
        "projection_rows": 3 * 3 * CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_HORIZON,
    }
    if any(counts.get(key) != value for key, value in expected_counts.items()):
        raise ValueError("validation output does not close the production Full-Pool denominator")

    accounting = _mapping(evidence.get("accounting"), "realization accounting")
    upstream = _mapping(accounting.get("upstream"), "upstream accounting")
    realization = _mapping(accounting.get("realization"), "realization-stage accounting")
    if (
        upstream.get("logical_judgments") != expected_counts["pairs"]
        or upstream.get("live_api_triggered") is not True
        or upstream.get("formal_research_evidence") is not True
        or upstream.get("production_deploy_eligible") is not True
        or realization != {"live_api_triggered": False, "provider_calls": 0}
        or manifest.get("production_deploy_eligible") is not False
    ):
        raise ValueError("validation output does not preserve composite Provider accounting")

    rows = projection.get("rows")
    if not isinstance(rows, list):
        raise ValueError("realized projection rows must be an array")
    grouped: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    runs: dict[tuple[str, str], set[int]] = defaultdict(set)
    for raw in rows:
        row = _mapping(raw, "realized projection row")
        segment = row.get("Segment")
        message = row.get("Message")
        if segment not in {"S1", "S2", "S3"} or message not in {"M1", "M2", "M3"}:
            raise ValueError("realized projection contains an unknown Segment or Message")
        key = (str(segment), str(message))
        run = _integer(row.get("Run"), "projection Run")
        likes = _integer(row.get("Total Likes"), "projection Likes")
        comments = _integer(row.get("Total Comments"), "projection Comments")
        shares = _integer(row.get("Total Shares"), "projection Shares")
        exposure = _integer(row.get("Exposure"), "projection Exposure")
        if likes + comments + shares > exposure or run in runs[key]:
            raise ValueError("realized projection action or Run denominator is crossed")
        runs[key].add(run)
        grouped[key].update(
            {
                "like": likes,
                "comment": comments,
                "share": shares,
                "exposure": exposure,
            }
        )
    expected_runs = set(range(1, CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_HORIZON + 1))
    expected_groups = {(segment, message) for segment in ("S1", "S2", "S3") for message in ("M1", "M2", "M3")}
    if set(grouped) != expected_groups or any(value != expected_runs for value in runs.values()):
        raise ValueError("realized projection does not close all Segment × Message delivery rounds")

    group_facts: dict[str, dict[str, object]] = {}
    action_counts: Counter[str] = Counter()
    total_exposure = 0
    total_engagement = 0
    for segment, message in sorted(grouped):
        values = grouped[(segment, message)]
        engagement = values["like"] + values["comment"] + values["share"]
        exposure = values["exposure"]
        if exposure < 1:
            raise ValueError("one Segment × Message cell has an empty exposure denominator")
        action_counts.update(
            {
                "like": values["like"],
                "comment": values["comment"],
                "share": values["share"],
                "ignore": exposure - engagement,
            }
        )
        total_exposure += exposure
        total_engagement += engagement
        group_facts[f"{segment}-{message}"] = {
            "exposure": exposure,
            "engagement": engagement,
            "engagement_rate": round(float(Fraction(engagement, exposure)), 8),
        }
    segment_exposures = {
        segment: {grouped[(segment, message)]["exposure"] for message in ("M1", "M2", "M3")}
        for segment in ("S1", "S2", "S3")
    }
    if (
        any(len(exposures) != 1 for exposures in segment_exposures.values())
        or sum(next(iter(exposures)) for exposures in segment_exposures.values())
        != CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_SAMPLE_SIZE
    ):
        raise ValueError("Segment × Message cells do not close the Full-Pool membership")
    if dict(action_counts) != manifest.get("action_counts"):
        raise ValueError("independently recomputed realized action counts are crossed")

    message_order_by_segment = {
        segment: sorted(
            ("M1", "M2", "M3"),
            key=lambda message: Fraction(
                grouped[(segment, message)]["like"]
                + grouped[(segment, message)]["comment"]
                + grouped[(segment, message)]["share"],
                grouped[(segment, message)]["exposure"],
            ),
            reverse=True,
        )
        for segment in ("S1", "S2", "S3")
    }
    if message_order_by_segment["S2"] != ["M2", "M3", "M1"] or message_order_by_segment[
        "S3"
    ] != ["M3", "M2", "M1"]:
        raise ValueError("realized S2 or S3 message ordering differs from the frozen diagnosis")

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("realized artifact inventory must be an array")
    return {
        "counts": counts,
        "action_counts": dict(action_counts),
        "realization_status_counts": manifest.get("realization_status_counts"),
        "overall_single_exposure": {
            "exposure": total_exposure,
            "engagement": total_engagement,
            "engagement_rate": round(float(Fraction(total_engagement, total_exposure)), 8),
        },
        "segment_message_single_exposure": group_facts,
        "message_order_by_segment": message_order_by_segment,
        "delivery_denominator": {
            "regular_per_message_batch_capacity": (
                CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_DELIVERY_CAPACITY
            ),
            "final_per_message_batch_capacity": (
                CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_SAMPLE_SIZE
                - CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_DELIVERY_CAPACITY
                * (CONCURRENT_MESSAGE_FULL_POOL_PRODUCTION_HORIZON - 1)
            ),
        },
        "upstream_accounting": upstream,
        "realization_accounting": realization,
        "artifact_count": len(artifacts),
        "artifact_bytes": sum(
            _integer(_mapping(ref, "artifact reference").get("bytes"), "artifact bytes")
            for ref in artifacts
        ),
    }


def _guard_new_paths(
    *,
    output: Path,
    run_record: Path,
    protected_roots: list[Path],
    protected_files: list[Path],
) -> tuple[Path, Path]:
    output_target = output.expanduser().resolve(strict=False)
    record_target = run_record.expanduser().resolve(strict=False)
    if os.path.lexists(output_target):
        raise FileExistsError(f"output already exists: {output_target}")
    if os.path.lexists(record_target):
        raise FileExistsError(f"run record already exists: {record_target}")
    if record_target == output_target or record_target.is_relative_to(output_target):
        raise ValueError("run record must be independent from the immutable realized source")
    for root in protected_roots:
        if (
            output_target == root
            or output_target.is_relative_to(root)
            or root.is_relative_to(output_target)
            or record_target.is_relative_to(root)
        ):
            raise ValueError("output and run record must not overlap protected artifacts")
    for path in protected_files:
        if path.is_relative_to(output_target) or record_target == path:
            raise ValueError("output and run record must not overlap protected artifacts")
    return output_target, record_target


def _remove_output(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        raise ValueError("validation output became unsafe during cleanup")
    shutil.rmtree(path)


def _write_record(path: Path, payload: dict[str, object]) -> None:
    target = path.expanduser().resolve(strict=False)
    if target != path.expanduser().absolute():
        raise ValueError("run record must use one canonical path")
    if os.path.lexists(target):
        raise FileExistsError(f"run record already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.tmp-",
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def main() -> int:
    arguments = _parser().parse_args()
    if arguments.confirm_zero_provider_validation != _CONFIRMATION:
        raise ValueError("zero-Provider two-stage validation confirmation token is invalid")
    source_root = arguments.source_root.expanduser().resolve(strict=True)
    protected_roots = [source_root, *arguments.protected_root]
    protected_identities = [path.expanduser().resolve(strict=True) for path in protected_roots]
    protected_files = [path.expanduser().resolve(strict=True) for path in arguments.protected_file]
    if len(protected_identities) != len(set(protected_identities)):
        raise ValueError("protected roots must be unique explicit paths")
    if len(protected_files) != len(set(protected_files)) or any(
        path.is_relative_to(root) for path in protected_files for root in protected_identities
    ):
        raise ValueError("protected files must be unique and independent from protected roots")
    output_target, record_target = _guard_new_paths(
        output=arguments.output_dir,
        run_record=arguments.run_record,
        protected_roots=protected_identities,
        protected_files=protected_files,
    )
    protected_before = [
        *(_protected_snapshot(root) for root in protected_identities),
        *(_protected_file_snapshot(path) for path in protected_files),
    ]
    started_at = datetime.now(UTC)
    started = time.perf_counter()
    result = None
    try:
        result = FullPoolTwoStageReplay().run_and_close(
            FullPoolTwoStageReplayRequest(
                source_root=source_root,
                source_manifest_sha256=arguments.source_manifest_sha256,
                source_identity=arguments.source_identity,
                output_dir=output_target,
            )
        )
        validation_facts = _validation_facts(result.output_dir)
        protected_after = [
            *(_protected_snapshot(root) for root in protected_identities),
            *(_protected_file_snapshot(path) for path in protected_files),
        ]
        if protected_after != protected_before:
            raise ValueError("an explicitly protected immutable artifact changed during replay")
        finished_at = datetime.now(UTC)
        implementation_files = [
            Path(__file__).resolve(),
            Path(inspect.getfile(FullPoolTwoStageReplay)).resolve(),
        ]
        record = {
            "schema_version": _RECORD_SCHEMA,
            "classification": "non_authoritative_non_deployable_validation",
            "source": {
                "root": str(source_root),
                "manifest_sha256": arguments.source_manifest_sha256,
                "source_identity": arguments.source_identity,
            },
            "output": {
                "root": str(result.output_dir),
                "manifest_sha256": result.manifest_sha256,
                "source_identity": result.source_identity,
                "users": result.user_count,
                "pairs": result.pair_count,
                "committed_batches": result.committed_batch_count,
                "production_deploy_eligible": result.production_deploy_eligible,
            },
            "accounting": {
                "realization_provider_calls": result.realization_provider_calls,
                "realization_live_api_triggered": False,
            },
            "implementation": [
                {
                    "path": str(path),
                    "sha256": _sha256_file(path),
                    "bytes": path.stat().st_size,
                }
                for path in implementation_files
            ],
            "validation_facts": validation_facts,
            "resource_evidence": {
                "started_at": started_at.isoformat(),
                "finished_at": finished_at.isoformat(),
                "duration_seconds": round(time.perf_counter() - started, 6),
                "peak_rss_bytes": _peak_rss_bytes(),
            },
            "protected_artifacts_before": protected_before,
            "protected_artifacts_after": protected_after,
        }
        _write_record(record_target, record)
    except BaseException:
        if result is not None and result.output_dir.exists():
            _remove_output(result.output_dir)
        raise
    print(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
