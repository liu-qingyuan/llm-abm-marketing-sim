from __future__ import annotations

import csv
import hashlib
import json
import random
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

VALUE_DIMENSIONS = ("epistemic", "environmental", "functional", "health", "emotional", "social")
PROFILE_FIELDS = ("hotel_class", "travel_purpose", "gender", "age", "education", "monthly_income")
REQUIRED_CLASSES = ("class_1", "class_2", "class_3")
LATENT_ASSIGNMENT_COLUMNS = [
    "user_id",
    "latent_attribute_spec_id",
    "latent_attribute_method",
    "latent_attribute_seed",
    "latent_class",
    "latent_environmental_consciousness_coef",
    "latent_epistemic_value_weight",
    "latent_environmental_value_weight",
    "latent_functional_value_weight",
    "latent_health_value_weight",
    "latent_emotional_value_weight",
    "latent_social_value_weight",
    "latent_hotel_class",
    "latent_travel_purpose",
    "latent_gender",
    "latent_age",
    "latent_education",
    "latent_monthly_income",
]
PRIVACY_STATEMENT = (
    "Only stable user_id values were used for deterministic latent assignment; no profile text, "
    "raw source payloads, credentials, or live providers were read."
)


class LatentClassSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    probability: float = Field(ge=0.0, le=1.0)
    environmental_consciousness_coef: float
    value_weights: dict[str, float]
    profile_distributions: dict[str, dict[str, float]]

    @field_validator("value_weights")
    @classmethod
    def _validate_value_weights(cls, value: dict[str, float]) -> dict[str, float]:
        missing = sorted(set(VALUE_DIMENSIONS) - set(value))
        extra = sorted(set(value) - set(VALUE_DIMENSIONS))
        if missing or extra:
            raise ValueError(f"value_weights must contain exactly {VALUE_DIMENSIONS}; missing={missing}, extra={extra}")
        return value

    @field_validator("profile_distributions")
    @classmethod
    def _validate_profile_distributions(cls, value: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
        missing = sorted(set(PROFILE_FIELDS) - set(value))
        extra = sorted(set(value) - set(PROFILE_FIELDS))
        if missing or extra:
            raise ValueError(f"profile_distributions must contain exactly {PROFILE_FIELDS}; missing={missing}, extra={extra}")
        for field_name, distribution in value.items():
            _validate_probability_distribution(field_name, distribution)
        return value


class LatentAttributeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec_id: str
    method: str
    classes: dict[str, LatentClassSpec]

    @field_validator("spec_id", "method")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @model_validator(mode="after")
    def _validate_classes(self) -> LatentAttributeSpec:
        missing = sorted(set(REQUIRED_CLASSES) - set(self.classes))
        extra = sorted(set(self.classes) - set(REQUIRED_CLASSES))
        if missing or extra:
            raise ValueError(f"classes must contain exactly {REQUIRED_CLASSES}; missing={missing}, extra={extra}")
        total = sum(class_spec.probability for class_spec in self.classes.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"class probabilities must sum to 1.0; got {total:.12g}")
        return self


class LatentAttributes(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec_id: str
    method: str
    seed: int
    latent_class: str
    environmental_consciousness_coef: float
    value_weights: dict[str, float]
    class_profile: dict[str, str]


class LatentUserAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    latent_attributes: LatentAttributes

    def to_flat_row(self) -> dict[str, object]:
        attributes = self.latent_attributes
        row: dict[str, object] = {
            "user_id": self.user_id,
            "latent_attribute_spec_id": attributes.spec_id,
            "latent_attribute_method": attributes.method,
            "latent_attribute_seed": attributes.seed,
            "latent_class": attributes.latent_class,
            "latent_environmental_consciousness_coef": attributes.environmental_consciousness_coef,
        }
        for dimension in VALUE_DIMENSIONS:
            row[f"latent_{dimension}_value_weight"] = attributes.value_weights[dimension]
        for field_name in PROFILE_FIELDS:
            row[f"latent_{field_name}"] = attributes.class_profile[field_name]
        return row


class LatentAssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    user_ids: list[str]
    spec: LatentAttributeSpec
    seed: int


class LatentAssignmentAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec_id: str
    method: str
    spec_hash: str
    seed: int
    user_count: int
    class_counts: dict[str, dict[str, float | int]]
    profile_counts: dict[str, dict[str, dict[str, dict[str, float | int]]]]
    max_count_deviation: int
    max_proportion_deviation: float
    privacy_statement: str = PRIVACY_STATEMENT


class LatentAssignmentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignments: list[LatentUserAssignment]
    audit: LatentAssignmentAudit
    spec_snapshot: dict[str, Any]


@dataclass(frozen=True)
class LatentAssignmentPaths:
    assignments_csv: Path
    audit_json: Path
    audit_markdown: Path
    spec_snapshot_yaml: Path


def load_latent_attribute_spec(path: Path) -> LatentAttributeSpec:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        payload = json.loads(text)
    else:
        payload = yaml.safe_load(text)
    if not isinstance(payload, dict):
        raise ValueError("latent attribute spec must be a mapping")
    return LatentAttributeSpec.model_validate(payload)


def assign_latent_attributes(
    user_ids: Sequence[str],
    spec: LatentAttributeSpec,
    *,
    seed: int,
) -> LatentAssignmentResult:
    stable_user_ids = _stable_user_ids(user_ids)
    class_targets = _largest_remainder_counts(
        {class_name: class_spec.probability for class_name, class_spec in spec.classes.items()},
        len(stable_user_ids),
    )
    class_users = _assign_labels(
        stable_user_ids,
        class_targets,
        seed=_stable_seed(spec.spec_id, seed, "latent_class"),
    )
    assignments_by_user: dict[str, LatentUserAssignment] = {}
    profile_targets: dict[str, dict[str, dict[str, int]]] = {}

    for class_name in REQUIRED_CLASSES:
        class_spec = spec.classes[class_name]
        assigned_user_ids = class_users[class_name]
        class_profile_values: dict[str, dict[str, str]] = {user_id: {} for user_id in assigned_user_ids}
        profile_targets[class_name] = {}
        for field_name in PROFILE_FIELDS:
            targets = _largest_remainder_counts(class_spec.profile_distributions[field_name], len(assigned_user_ids))
            profile_targets[class_name][field_name] = targets
            field_assignments = _assign_labels(
                assigned_user_ids,
                targets,
                seed=_stable_seed(spec.spec_id, seed, class_name, field_name),
            )
            for label, label_user_ids in field_assignments.items():
                for user_id in label_user_ids:
                    class_profile_values[user_id][field_name] = label
        for user_id in assigned_user_ids:
            assignments_by_user[user_id] = LatentUserAssignment(
                user_id=user_id,
                latent_attributes=LatentAttributes(
                    spec_id=spec.spec_id,
                    method=spec.method,
                    seed=seed,
                    latent_class=class_name,
                    environmental_consciousness_coef=class_spec.environmental_consciousness_coef,
                    value_weights=dict(class_spec.value_weights),
                    class_profile=class_profile_values[user_id],
                ),
            )

    assignments = [assignments_by_user[user_id] for user_id in stable_user_ids]
    audit = _build_audit(
        spec,
        seed=seed,
        assignments=assignments,
        class_targets=class_targets,
        profile_targets=profile_targets,
    )
    return LatentAssignmentResult(
        assignments=assignments,
        audit=audit,
        spec_snapshot=_spec_snapshot(spec),
    )


def generate_latent_assignments(request: LatentAssignmentRequest) -> LatentAssignmentResult:
    return assign_latent_attributes(request.user_ids, request.spec, seed=request.seed)


def write_latent_assignment_outputs(result: LatentAssignmentResult, output_dir: Path) -> LatentAssignmentPaths:
    output_dir.mkdir(parents=True, exist_ok=True)
    assignments_csv = output_dir / "latent_attribute_assignments.csv"
    audit_json = output_dir / "latent_attribute_audit.json"
    audit_markdown = output_dir / "latent_attribute_audit.md"
    spec_snapshot_yaml = output_dir / "latent_attribute_spec.yaml"

    with assignments_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LATENT_ASSIGNMENT_COLUMNS)
        writer.writeheader()
        writer.writerows(assignment.to_flat_row() for assignment in result.assignments)
    audit_json.write_text(
        json.dumps(result.audit.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    audit_markdown.write_text(_render_audit_markdown(result.audit), encoding="utf-8")
    spec_snapshot_yaml.write_text(
        yaml.safe_dump(result.spec_snapshot, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return LatentAssignmentPaths(assignments_csv, audit_json, audit_markdown, spec_snapshot_yaml)


def _validate_probability_distribution(name: str, distribution: dict[str, float]) -> None:
    if not distribution:
        raise ValueError(f"{name} distribution must not be empty")
    invalid = {label: probability for label, probability in distribution.items() if probability < 0.0 or probability > 1.0}
    if invalid:
        raise ValueError(f"{name} distribution probabilities must be in [0, 1]: {invalid}")
    total = sum(distribution.values())
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"{name} distribution must sum to 1.0; got {total:.12g}")


def _largest_remainder_counts(distribution: dict[str, float], total_count: int) -> dict[str, int]:
    if total_count < 0:
        raise ValueError("total_count must be non-negative")
    exact_counts = {label: probability * total_count for label, probability in distribution.items()}
    counts = {label: int(exact) for label, exact in exact_counts.items()}
    remainder = total_count - sum(counts.values())
    ranked = sorted(
        distribution,
        key=lambda label: (-(exact_counts[label] - counts[label]), label),
    )
    for label in ranked[:remainder]:
        counts[label] += 1
    return counts


def _assign_labels(user_ids: list[str], target_counts: dict[str, int], *, seed: int) -> dict[str, list[str]]:
    shuffled = list(user_ids)
    random.Random(seed).shuffle(shuffled)
    assignments: dict[str, list[str]] = {}
    offset = 0
    for label in sorted(target_counts):
        count = target_counts[label]
        assignments[label] = sorted(shuffled[offset : offset + count])
        offset += count
    if offset != len(user_ids):
        raise ValueError("target counts must sum to user count")
    return assignments


def _stable_user_ids(user_ids: Sequence[str]) -> list[str]:
    normalized = [str(user_id).strip() for user_id in user_ids]
    if any(not user_id for user_id in normalized):
        raise ValueError("user_ids must not contain empty values")
    if len(set(normalized)) != len(normalized):
        raise ValueError("user_ids must be unique")
    return sorted(normalized)


def _stable_seed(*parts: object) -> int:
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def _spec_snapshot(spec: LatentAttributeSpec) -> dict[str, Any]:
    snapshot = spec.model_dump(mode="json")
    snapshot["spec_hash"] = _spec_hash(spec)
    return snapshot


def _spec_hash(spec: LatentAttributeSpec) -> str:
    canonical = json.dumps(spec.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _build_audit(
    spec: LatentAttributeSpec,
    *,
    seed: int,
    assignments: list[LatentUserAssignment],
    class_targets: dict[str, int],
    profile_targets: dict[str, dict[str, dict[str, int]]],
) -> LatentAssignmentAudit:
    user_count = len(assignments)
    actual_class_counts = Counter(assignment.latent_attributes.latent_class for assignment in assignments)
    max_count_deviation = 0
    max_proportion_deviation = 0.0
    class_counts: dict[str, dict[str, float | int]] = {}
    for class_name in REQUIRED_CLASSES:
        target_count = class_targets[class_name]
        actual_count = actual_class_counts[class_name]
        count_deviation = abs(actual_count - target_count)
        proportion_deviation = _proportion_deviation(target_count, actual_count, user_count)
        max_count_deviation = max(max_count_deviation, count_deviation)
        max_proportion_deviation = max(max_proportion_deviation, proportion_deviation)
        class_counts[class_name] = {
            "probability": spec.classes[class_name].probability,
            "target_count": target_count,
            "actual_count": actual_count,
            "target_proportion": _safe_ratio(target_count, user_count),
            "actual_proportion": _safe_ratio(actual_count, user_count),
            "count_deviation": count_deviation,
            "proportion_deviation": proportion_deviation,
        }

    profile_counts: dict[str, dict[str, dict[str, dict[str, float | int]]]] = {}
    assignments_by_class: dict[str, list[LatentUserAssignment]] = {
        class_name: [assignment for assignment in assignments if assignment.latent_attributes.latent_class == class_name]
        for class_name in REQUIRED_CLASSES
    }
    for class_name in REQUIRED_CLASSES:
        profile_counts[class_name] = {}
        class_assignments = assignments_by_class[class_name]
        class_count = len(class_assignments)
        for field_name in PROFILE_FIELDS:
            actual_counts = Counter(
                assignment.latent_attributes.class_profile[field_name] for assignment in class_assignments
            )
            profile_counts[class_name][field_name] = {}
            for label in sorted(profile_targets[class_name][field_name]):
                target_count = profile_targets[class_name][field_name][label]
                actual_count = actual_counts[label]
                count_deviation = abs(actual_count - target_count)
                proportion_deviation = _proportion_deviation(target_count, actual_count, class_count)
                max_count_deviation = max(max_count_deviation, count_deviation)
                max_proportion_deviation = max(max_proportion_deviation, proportion_deviation)
                profile_counts[class_name][field_name][label] = {
                    "probability": spec.classes[class_name].profile_distributions[field_name][label],
                    "target_count": target_count,
                    "actual_count": actual_count,
                    "target_proportion": _safe_ratio(target_count, class_count),
                    "actual_proportion": _safe_ratio(actual_count, class_count),
                    "count_deviation": count_deviation,
                    "proportion_deviation": proportion_deviation,
                }

    return LatentAssignmentAudit(
        spec_id=spec.spec_id,
        method=spec.method,
        spec_hash=_spec_hash(spec),
        seed=seed,
        user_count=user_count,
        class_counts=class_counts,
        profile_counts=profile_counts,
        max_count_deviation=max_count_deviation,
        max_proportion_deviation=max_proportion_deviation,
    )


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _proportion_deviation(target_count: int, actual_count: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return abs(actual_count - target_count) / denominator


def _render_audit_markdown(audit: LatentAssignmentAudit) -> str:
    lines = [
        "# Latent Attribute Assignment Audit",
        "",
        f"- spec_id: `{audit.spec_id}`",
        f"- method: `{audit.method}`",
        f"- seed: `{audit.seed}`",
        f"- user_count: `{audit.user_count}`",
        f"- spec_hash: `{audit.spec_hash}`",
        f"- max_count_deviation: `{audit.max_count_deviation}`",
        f"- max_proportion_deviation: `{audit.max_proportion_deviation:.12g}`",
        f"- privacy: {audit.privacy_statement}",
        "",
        "## Class Counts",
        "",
        "| class | target | actual | count deviation | proportion deviation |",
        "|---|---:|---:|---:|---:|",
    ]
    for class_name, counts in audit.class_counts.items():
        lines.append(
            f"| {class_name} | {counts['target_count']} | {counts['actual_count']} | "
            f"{counts['count_deviation']} | {counts['proportion_deviation']:.12g} |"
        )
    lines.append("")
    return "\n".join(lines)
