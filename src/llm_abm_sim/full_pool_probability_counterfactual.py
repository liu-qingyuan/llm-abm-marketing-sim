from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

COUNTERFACTUAL_SCHEMA_VERSION = "full-pool-fixed-schedule-probability-counterfactual-v1"
_DRAW_ALGORITHM = "sha256-seed-null-pair-id-first-53-bits-uniform-v1"
_SOURCE_SCHEMA_VERSION = "full-pool-segmented-source-v4"
_ENVIRONMENTAL_FIELD = "concurrent_environmental_consciousness_coef"
_MESSAGE_CODES = {"message_1": "M1", "message_2": "M2", "message_3": "M3"}
_SEGMENT_CODES = {"class_1": "S1", "class_2": "S2", "class_3": "S3"}
_POSITIVE_ACTIONS = {"like", "comment", "share"}


@dataclass(frozen=True)
class ProbabilityCounterfactualRequest:
    source_root: Path
    source_manifest_sha256: str
    output_dir: Path
    seed: int


@dataclass(frozen=True)
class ProbabilityCounterfactualResult:
    output_dir: Path
    row_count: int
    source_engagement_rate: float
    mean_persisted_probability: float
    counterfactual_engagement_rate: float


@dataclass
class _Aggregate:
    exposures: int = 0
    source_engaged: int = 0
    probability_sum: float = 0.0
    counterfactual_engaged: int = 0
    source_positive_to_counterfactual_ignore: int = 0
    source_ignore_to_counterfactual_positive: int = 0

    def add(self, *, source_engaged: bool, probability: float, counterfactual_engaged: bool) -> None:
        self.exposures += 1
        self.source_engaged += int(source_engaged)
        self.probability_sum += probability
        self.counterfactual_engaged += int(counterfactual_engaged)
        self.source_positive_to_counterfactual_ignore += int(source_engaged and not counterfactual_engaged)
        self.source_ignore_to_counterfactual_positive += int(not source_engaged and counterfactual_engaged)

    def payload(self) -> dict[str, int | float]:
        if self.exposures < 1:
            raise ValueError("counterfactual aggregate cannot be empty")
        source_rate = self.source_engaged / self.exposures
        mean_probability = self.probability_sum / self.exposures
        counterfactual_rate = self.counterfactual_engaged / self.exposures
        return {
            "exposures": self.exposures,
            "source_engaged": self.source_engaged,
            "source_engagement_rate": _metric(source_rate),
            "mean_persisted_probability": _metric(mean_probability),
            "counterfactual_engaged": self.counterfactual_engaged,
            "counterfactual_engagement_rate": _metric(counterfactual_rate),
            "change_percentage_points": _metric((counterfactual_rate - source_rate) * 100.0),
            "source_positive_to_counterfactual_ignore": self.source_positive_to_counterfactual_ignore,
            "source_ignore_to_counterfactual_positive": self.source_ignore_to_counterfactual_positive,
        }


def stable_probability_draw(*, seed: int, pair_id: str) -> float:
    """Return one order-independent reproducible U[0, 1) draw for a persisted pair."""

    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("counterfactual seed must be an integer")
    if not pair_id:
        raise ValueError("counterfactual pair_id must be non-empty")
    digest = hashlib.sha256(f"{seed}\0{pair_id}".encode()).digest()
    first_53_bits = int.from_bytes(digest[:8], "big") >> 11
    return first_53_bits / float(1 << 53)


def run_probability_counterfactual(request: ProbabilityCounterfactualRequest) -> ProbabilityCounterfactualResult:
    """Realize persisted probabilities on the frozen Full-Pool exposure schedule.

    This is an exploratory binary-engagement sensitivity. It never calls an Adapter or
    Provider, never creates a counterfactual action, and never rewrites the source.
    """

    source = _explicit_source_directory(request.source_root)
    output = _new_output_path(request.output_dir, source=source)
    manifest_path = source / "manifest.json"
    if _sha256_file(manifest_path) != request.source_manifest_sha256:
        raise ValueError("source manifest differs from the explicit SHA-256")
    source_manifest = _object(json.loads(manifest_path.read_text(encoding="utf-8")), "source manifest")
    if source_manifest.get("schema_version") != _SOURCE_SCHEMA_VERSION:
        raise ValueError("counterfactual source must be a closed source-v4 manifest")
    source_identity = _non_empty(source_manifest.get("source_identity"), "source identity")
    source_counts = _object(source_manifest.get("counts"), "source counts")
    expected_rows = _positive_int(source_counts.get("terminal_rows"), "terminal row count")
    expected_users = _positive_int(source_counts.get("distinct_users"), "distinct user count")
    committed_batches = _positive_int(source_counts.get("committed_batches"), "committed batch count")

    inventory = _needed_source_inventory(source_manifest)
    terminal_path = source / "terminal_rows.jsonl"
    membership_path = source / "latent-membership.csv"
    for relative, path in (("terminal_rows.jsonl", terminal_path), ("latent-membership.csv", membership_path)):
        expected = inventory[relative]
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"required source artifact is missing or unsafe: {relative}")
        if path.stat().st_size != expected["bytes"] or _sha256_file(path) != expected["sha256"]:
            raise ValueError(f"required source artifact differs from its manifest: {relative}")
    row_hashes = _object(source_manifest.get("row_hashes"), "source row hashes")
    if row_hashes.get("terminal_rows.jsonl") != inventory["terminal_rows.jsonl"]["sha256"]:
        raise ValueError("terminal row hash differs between source manifest inventories")

    membership = _read_membership(membership_path)
    if len(membership) != expected_users:
        raise ValueError("latent membership count differs from source manifest")

    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent))
    try:
        result = _write_counterfactual(
            source=source,
            source_manifest_sha256=request.source_manifest_sha256,
            source_identity=source_identity,
            terminal_path=terminal_path,
            membership=membership,
            expected_rows=expected_rows,
            committed_batches=committed_batches,
            seed=request.seed,
            staging=staging,
            source_artifacts=inventory,
        )
        os.replace(staging, output)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return ProbabilityCounterfactualResult(
        output_dir=output,
        row_count=int(result["row_count"]),
        source_engagement_rate=float(result["source_engagement_rate"]),
        mean_persisted_probability=float(result["mean_persisted_probability"]),
        counterfactual_engagement_rate=float(result["counterfactual_engagement_rate"]),
    )


def _write_counterfactual(
    *,
    source: Path,
    source_manifest_sha256: str,
    source_identity: str,
    terminal_path: Path,
    membership: dict[str, str],
    expected_rows: int,
    committed_batches: int,
    seed: int,
    staging: Path,
    source_artifacts: dict[str, dict[str, int | str]],
) -> dict[str, int | float]:
    overall = _Aggregate()
    by_segment: defaultdict[str, _Aggregate] = defaultdict(_Aggregate)
    by_message: defaultdict[str, _Aggregate] = defaultdict(_Aggregate)
    by_segment_message: defaultdict[tuple[str, str], _Aggregate] = defaultdict(_Aggregate)
    by_run_segment: defaultdict[tuple[int, str], _Aggregate] = defaultdict(_Aggregate)
    source_engagements_by_user: Counter[str] = Counter()
    counterfactual_engagements_by_user: Counter[str] = Counter()
    seen_pairs: set[str] = set()
    seen_user_messages: set[tuple[str, str]] = set()
    seen_users: set[str] = set()
    messages: set[str] = set()

    rows_path = staging / "counterfactual_pair_rows.jsonl"
    with terminal_path.open(encoding="utf-8") as source_stream, rows_path.open("w", encoding="utf-8") as output_stream:
        for line_number, line in enumerate(source_stream, start=1):
            if not line.strip():
                continue
            try:
                terminal = _object(json.loads(line), f"terminal row {line_number}")
            except json.JSONDecodeError as exc:
                raise ValueError(f"terminal row {line_number} is malformed") from exc
            pair_id = _non_empty(terminal.get("pair_id"), "pair id")
            user_id = _non_empty(terminal.get("user_id"), "user id")
            message_id = _non_empty(terminal.get("message_id"), "message id")
            if pair_id in seen_pairs or (user_id, message_id) in seen_user_messages:
                raise ValueError("source terminal rows contain duplicate pair identities")
            if user_id not in membership or message_id not in _MESSAGE_CODES:
                raise ValueError("source terminal row is crossed with membership or message contract")
            if terminal.get("decision_variant") != "primary" or terminal.get("terminal_status") != "succeeded":
                raise ValueError("counterfactual requires successful Primary terminal rows")
            time_step = _non_negative_int(terminal.get("time_step"), "time step")
            if time_step >= committed_batches:
                raise ValueError("source terminal row time step exceeds committed batches")
            schedule_position = _non_negative_int(terminal.get("pair_schedule_position"), "pair schedule position")
            probability = _probability(terminal.get("probability"))
            source_engaged = _canonical_bool(terminal.get("engage"), "source engage")
            source_action = _non_empty(terminal.get("action"), "source action")
            if (source_action in _POSITIVE_ACTIONS) != source_engaged:
                raise ValueError("source engage/action fields are inconsistent")
            prompt_version = _non_empty(terminal.get("prompt_version"), "prompt version")
            profile_payload = _json_object_string(terminal.get("context_profile_payload"), "context profile payload")
            inclusion = _json_object_string(terminal.get("prompt_field_inclusion"), "prompt field inclusion")
            environmental = profile_payload.get(_ENVIRONMENTAL_FIELD)
            if isinstance(environmental, bool) or not isinstance(environmental, (int, float)):
                raise ValueError("Environmental Consciousness is missing from persisted Prompt context")
            if inclusion.get(_ENVIRONMENTAL_FIELD) != "included":
                raise ValueError("Environmental Consciousness was not included in the persisted Prompt")

            draw = stable_probability_draw(seed=seed, pair_id=pair_id)
            counterfactual_engaged = draw < probability
            latent_class = membership[user_id]
            segment = _SEGMENT_CODES[latent_class]
            message = _MESSAGE_CODES[message_id]
            run = time_step + 1
            row = {
                "counterfactual_engaged": counterfactual_engaged,
                "environmental_consciousness_coef": environmental,
                "environmental_consciousness_prompt_inclusion": "included",
                "latent_class": latent_class,
                "message_id": message_id,
                "pair_id": pair_id,
                "pair_schedule_position": schedule_position,
                "persisted_probability": probability,
                "prompt_version": prompt_version,
                "run": run,
                "segment": segment,
                "source_action": source_action,
                "source_engage": source_engaged,
                "terminal_row_id": _non_empty(terminal.get("terminal_row_id"), "terminal row id"),
                "uniform_draw": draw,
                "user_id": user_id,
            }
            output_stream.write(_canonical_json(row) + "\n")

            for aggregate in (
                overall,
                by_segment[segment],
                by_message[message],
                by_segment_message[(segment, message)],
                by_run_segment[(run, "ALL")],
                by_run_segment[(run, segment)],
            ):
                aggregate.add(
                    source_engaged=source_engaged,
                    probability=probability,
                    counterfactual_engaged=counterfactual_engaged,
                )
            source_engagements_by_user[user_id] += int(source_engaged)
            counterfactual_engagements_by_user[user_id] += int(counterfactual_engaged)
            seen_pairs.add(pair_id)
            seen_user_messages.add((user_id, message_id))
            seen_users.add(user_id)
            messages.add(message_id)

    if len(seen_pairs) != expected_rows:
        raise ValueError("counterfactual row count differs from source manifest")
    if seen_users != set(membership):
        raise ValueError("counterfactual source does not cover the full membership")
    if messages != set(_MESSAGE_CODES):
        raise ValueError("counterfactual source does not contain the three authoritative messages")
    if len(seen_user_messages) != len(membership) * len(_MESSAGE_CODES):
        raise ValueError("counterfactual source does not contain complete user-message coverage")

    segment_message_rows = [
        _group_payload(aggregate, Segment=segment, Message=message)
        for (segment, message), aggregate in sorted(by_segment_message.items())
    ]
    run_segment_rows = [
        _group_payload(aggregate, Run=run, Segment=segment)
        for (run, segment), aggregate in sorted(by_run_segment.items(), key=lambda item: (item[0][0], item[0][1] != "ALL", item[0][1]))
    ]
    user_distribution = []
    for segment in sorted(_SEGMENT_CODES.values()):
        user_ids = sorted(user_id for user_id in membership if _SEGMENT_CODES[membership[user_id]] == segment)
        source_distribution = Counter(source_engagements_by_user[user_id] for user_id in user_ids)
        counterfactual_distribution = Counter(counterfactual_engagements_by_user[user_id] for user_id in user_ids)
        user_distribution.append(
            {
                "segment": segment,
                "users": len(user_ids),
                "source_engaged_messages_per_user": {str(key): source_distribution[key] for key in range(4)},
                "counterfactual_engaged_messages_per_user": {
                    str(key): counterfactual_distribution[key] for key in range(4)
                },
            }
        )

    summary = {
        "schema_version": COUNTERFACTUAL_SCHEMA_VERSION,
        "claim_boundary": (
            "Exploratory fixed-schedule binary-engagement sensitivity; not a Formal replacement, "
            "not calibrated to real platform behavior, and not an action or feedback trajectory."
        ),
        "overall": overall.payload(),
        "by_segment": [
            _group_payload(aggregate, segment=segment) for segment, aggregate in sorted(by_segment.items())
        ],
        "by_message": [
            _group_payload(aggregate, message=message) for message, aggregate in sorted(by_message.items())
        ],
        "by_segment_message": segment_message_rows,
        "user_engagement_distribution": user_distribution,
    }
    _write_json(staging / "counterfactual_summary.json", summary)
    _write_csv(staging / "segment_message_summary.csv", segment_message_rows)
    _write_csv(staging / "run_segment_summary.csv", run_segment_rows)
    (staging / "report.md").write_text(
        _report_markdown(
            source=source,
            seed=seed,
            overall=overall.payload(),
            by_segment={key: value.payload() for key, value in sorted(by_segment.items())},
            by_segment_message={key: value.payload() for key, value in sorted(by_segment_message.items())},
        ),
        encoding="utf-8",
    )

    artifact_names = (
        "counterfactual_pair_rows.jsonl",
        "counterfactual_summary.json",
        "segment_message_summary.csv",
        "run_segment_summary.csv",
        "report.md",
    )
    output_artifacts = [
        {
            "relative_path": name,
            "sha256": _sha256_file(staging / name),
            "bytes": (staging / name).stat().st_size,
        }
        for name in artifact_names
    ]
    manifest = {
        "schema_version": COUNTERFACTUAL_SCHEMA_VERSION,
        "classification": "exploratory_fixed_schedule_counterfactual",
        "source_root": str(source),
        "source_identity": source_identity,
        "source_manifest_sha256": source_manifest_sha256,
        "source_artifacts": source_artifacts,
        "seed": seed,
        "draw_algorithm": _DRAW_ALGORITHM,
        "decision_rule": "counterfactual_engaged = uniform_draw < persisted_probability",
        "probability_semantics_assumption": "probability_of_like_comment_or_share_after_one_exposure",
        "fixed_exposure_schedule": True,
        "feedback_recomputed": False,
        "counterfactual_action_generated": False,
        "environmental_consciousness_policy": "retained_from_source_prompt",
        "provider_calls": 0,
        "live_api_triggered": False,
        "production_deploy_eligible": False,
        "formal_replacement": False,
        "counts": {
            "rows": len(seen_pairs),
            "users": len(seen_users),
            "messages": len(messages),
            "runs": committed_batches,
        },
        "artifacts": output_artifacts,
    }
    _write_json(staging / "manifest.json", manifest)
    overall_payload = overall.payload()
    return {
        "row_count": len(seen_pairs),
        "source_engagement_rate": float(overall_payload["source_engagement_rate"]),
        "mean_persisted_probability": float(overall_payload["mean_persisted_probability"]),
        "counterfactual_engagement_rate": float(overall_payload["counterfactual_engagement_rate"]),
    }


def _report_markdown(
    *,
    source: Path,
    seed: int,
    overall: dict[str, int | float],
    by_segment: dict[str, dict[str, int | float]],
    by_segment_message: dict[tuple[str, str], dict[str, int | float]],
) -> str:
    lines = [
        "# Full-Pool Probability Realization Counterfactual",
        "",
        "> Exploratory fixed-schedule binary-engagement sensitivity. Provider calls: `0`. "
        "This is not a Formal replacement and is not calibrated to real platform behavior.",
        "",
        f"- Source: `{source}`",
        f"- Seed: `{seed}`",
        f"- Draw: `{_DRAW_ALGORITHM}`",
        "- Environmental Consciousness: retained exactly as included in the persisted Prompt context",
        "- Exposure schedule: frozen from the source; ranking and feedback were not recomputed",
        "- Counterfactual action: not generated",
        "",
        "## Headline",
        "",
        "| Scope | Source action rate | Mean persisted probability | Counterfactual engagement rate | Change |",
        "|---|---:|---:|---:|---:|",
        _markdown_metric_row("All", overall),
    ]
    for segment, payload in sorted(by_segment.items()):
        lines.append(_markdown_metric_row(segment, payload))
    lines.extend(
        [
            "",
            "## Segment × Message",
            "",
            "| Segment | Message | Source action rate | Mean probability | Counterfactual rate | Change |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for (segment, message), payload in sorted(by_segment_message.items()):
        lines.append(
            f"| {segment} | {message} | {_percent(payload['source_engagement_rate'])} | "
            f"{_percent(payload['mean_persisted_probability'])} | "
            f"{_percent(payload['counterfactual_engagement_rate'])} | "
            f"{float(payload['change_percentage_points']):+.2f} pp |"
        )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "The counterfactual asks only what happens when the persisted LLM probability is treated as an "
            "engagement probability and realized by a seeded ABM draw. It does not remove Prompt fields, call "
            "the Provider, infer a counterfactual action type, recompute campaign feedback, or replace the "
            "immutable source evidence.",
            "",
        ]
    )
    return "\n".join(lines)


def _markdown_metric_row(label: str, payload: dict[str, int | float]) -> str:
    return (
        f"| {label} | {_percent(payload['source_engagement_rate'])} | "
        f"{_percent(payload['mean_persisted_probability'])} | "
        f"{_percent(payload['counterfactual_engagement_rate'])} | "
        f"{float(payload['change_percentage_points']):+.2f} pp |"
    )


def _group_payload(aggregate: _Aggregate, **labels: str | int) -> dict[str, str | int | float]:
    return {**labels, **aggregate.payload()}


def _write_csv(path: Path, rows: list[dict[str, str | int | float]]) -> None:
    if not rows:
        raise ValueError("counterfactual CSV cannot be empty")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _needed_source_inventory(manifest: dict[str, object]) -> dict[str, dict[str, int | str]]:
    raw = manifest.get("artifacts")
    if not isinstance(raw, list):
        raise ValueError("source artifact inventory must be an array")
    needed: dict[str, dict[str, int | str]] = {}
    for item in raw:
        row = _object(item, "source artifact")
        if set(row) != {"relative_path", "sha256", "bytes"}:
            raise ValueError("source artifact fields are not exact")
        relative = _non_empty(row.get("relative_path"), "source artifact path")
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError("source artifact path is unsafe")
        if relative in {"terminal_rows.jsonl", "latent-membership.csv"}:
            digest = _sha256(row.get("sha256"), f"{relative} SHA-256")
            byte_count = _non_negative_int(row.get("bytes"), f"{relative} bytes")
            needed[relative] = {"sha256": digest, "bytes": byte_count}
    if set(needed) != {"terminal_rows.jsonl", "latent-membership.csv"}:
        raise ValueError("source manifest lacks counterfactual input artifacts")
    return needed


def _read_membership(path: Path) -> dict[str, str]:
    membership: dict[str, str] = {}
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["user_id", "latent_class"]:
            raise ValueError("latent membership fields are not exact")
        for row in reader:
            user_id = _non_empty(row.get("user_id"), "membership user id")
            latent_class = _non_empty(row.get("latent_class"), "membership latent class")
            if user_id in membership or latent_class not in _SEGMENT_CODES:
                raise ValueError("latent membership contains a duplicate user or unknown class")
            membership[user_id] = latent_class
    if not membership:
        raise ValueError("latent membership cannot be empty")
    return membership


def _explicit_source_directory(path: Path) -> Path:
    candidate = path.expanduser()
    if candidate.is_symlink():
        raise ValueError("source root must be one explicit real directory")
    resolved = candidate.resolve(strict=True)
    if resolved != candidate.absolute() or not resolved.is_dir():
        raise ValueError("source root must be one explicit real directory")
    return resolved


def _new_output_path(path: Path, *, source: Path) -> Path:
    candidate = path.expanduser()
    resolved = candidate.resolve(strict=False)
    if resolved != candidate.absolute():
        raise ValueError("output directory must be one canonical path")
    if os.path.lexists(resolved):
        raise FileExistsError(f"output directory already exists: {resolved}")
    if resolved == source or resolved.is_relative_to(source) or source.is_relative_to(resolved):
        raise ValueError("output directory must be independent from the immutable source")
    return resolved


def _canonical_bool(value: object, context: str) -> bool:
    if value in (True, "true"):
        return True
    if value in (False, "false"):
        return False
    raise ValueError(f"{context} is not a canonical boolean")


def _json_object_string(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, str):
        raise ValueError(f"{context} must be persisted JSON text")
    try:
        return _object(json.loads(value), context)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{context} is malformed") from exc


def _object(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    return {str(key): item for key, item in value.items()}


def _non_empty(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be a non-empty string")
    return value


def _non_negative_int(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{context} must be a non-negative integer")
    return value


def _positive_int(value: object, context: str) -> int:
    result = _non_negative_int(value, context)
    if result < 1:
        raise ValueError(f"{context} must be positive")
    return result


def _probability(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("persisted probability must be numeric")
    result = float(value)
    if not 0.0 <= result <= 1.0:
        raise ValueError("persisted probability must be between zero and one")
    return result


def _sha256(value: object, context: str) -> str:
    text = _non_empty(value, context)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{context} is malformed")
    return text


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _metric(value: float) -> float:
    return round(value, 12)


def _percent(value: int | float) -> str:
    return f"{float(value):.2%}"
