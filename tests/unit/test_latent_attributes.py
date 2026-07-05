from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from llm_abm_sim.data_sources.latent_attributes import (
    PROFILE_FIELDS,
    LatentAttributeSpec,
    assign_latent_attributes,
    load_latent_attribute_spec,
    write_latent_assignment_outputs,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
JINJIANG_LATENT_SPEC = REPO_ROOT / "configs" / "latent_attributes" / "jinjiang_user_latent_attributes_v1.yaml"


def make_spec_payload() -> dict[str, object]:
    profile_distributions = {
        "hotel_class": {"economy": 0.5, "midscale": 0.3, "upper_midscale": 0.2},
        "travel_purpose": {"business": 0.4, "leisure": 0.6},
        "gender": {"female": 0.6, "male": 0.4},
        "age": {
            "age_18_25": 0.1,
            "age_26_35": 0.4,
            "age_36_45": 0.3,
            "age_46_55": 0.1,
            "age_56_plus": 0.1,
        },
        "education": {
            "high_school_or_below": 0.1,
            "community_college": 0.2,
            "bachelor": 0.5,
            "master_or_above": 0.2,
        },
        "monthly_income": {
            "income_8000_or_less": 0.3,
            "income_8001_15000": 0.3,
            "income_15001_25000": 0.2,
            "income_25001_40000": 0.1,
            "income_40001_or_more": 0.1,
        },
    }
    value_weights = {
        "epistemic": -1.0,
        "environmental": 2.0,
        "functional": 0.5,
        "health": 1.5,
        "emotional": -0.2,
        "social": 0.7,
    }
    return {
        "spec_id": "jinjiang_user_latent_attributes_v1",
        "method": "latent_class_exact_quota_v1",
        "classes": {
            "class_1": {
                "probability": 0.5,
                "environmental_consciousness_coef": 1.037,
                "value_weights": value_weights,
                "profile_distributions": profile_distributions,
            },
            "class_2": {
                "probability": 0.3,
                "environmental_consciousness_coef": -0.833,
                "value_weights": {**value_weights, "functional": 1.0},
                "profile_distributions": profile_distributions,
            },
            "class_3": {
                "probability": 0.2,
                "environmental_consciousness_coef": -0.205,
                "value_weights": {**value_weights, "epistemic": 0.8},
                "profile_distributions": profile_distributions,
            },
        },
    }


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_load_latent_attribute_spec_from_yaml_and_validate_required_fields(tmp_path: Path) -> None:
    path = tmp_path / "latent.yaml"
    path.write_text(yaml.safe_dump(make_spec_payload(), allow_unicode=True), encoding="utf-8")

    spec = load_latent_attribute_spec(path)

    assert spec.spec_id == "jinjiang_user_latent_attributes_v1"
    assert set(spec.classes) == {"class_1", "class_2", "class_3"}
    assert set(spec.classes["class_1"].value_weights) == {
        "epistemic",
        "environmental",
        "functional",
        "health",
        "emotional",
        "social",
    }
    assert set(spec.classes["class_1"].profile_distributions) == set(PROFILE_FIELDS)


def test_jinjiang_latent_spec_matches_final_dataset_validation_class_targets() -> None:
    spec = load_latent_attribute_spec(JINJIANG_LATENT_SPEC)
    user_ids = [f"user_{index:05d}" for index in range(36_400)]

    result = assign_latent_attributes(user_ids, spec, seed=20260630)

    assert result.audit.class_counts["class_1"]["target_count"] == 15_616
    assert result.audit.class_counts["class_2"]["target_count"] == 15_070
    assert result.audit.class_counts["class_3"]["target_count"] == 5_714
    assert result.audit.max_count_deviation == 0
    assert result.audit.max_proportion_deviation == 0.0


def test_spec_validation_rejects_missing_class_value_dimension_profile_field_and_bad_distribution() -> None:
    missing_class = make_spec_payload()
    del missing_class["classes"]["class_3"]  # type: ignore[index]
    with pytest.raises(ValidationError, match="classes must contain exactly"):
        LatentAttributeSpec.model_validate(missing_class)

    missing_value_dimension = make_spec_payload()
    del missing_value_dimension["classes"]["class_1"]["value_weights"]["social"]  # type: ignore[index]
    with pytest.raises(ValidationError, match="value_weights must contain exactly"):
        LatentAttributeSpec.model_validate(missing_value_dimension)

    missing_profile_field = make_spec_payload()
    del missing_profile_field["classes"]["class_1"]["profile_distributions"]["monthly_income"]  # type: ignore[index]
    with pytest.raises(ValidationError, match="profile_distributions must contain exactly"):
        LatentAttributeSpec.model_validate(missing_profile_field)

    bad_distribution = make_spec_payload()
    bad_distribution["classes"]["class_1"]["profile_distributions"]["gender"] = {"female": 0.9, "male": 0.2}  # type: ignore[index]
    with pytest.raises(ValidationError, match="distribution must sum to 1.0"):
        LatentAttributeSpec.model_validate(bad_distribution)


def test_assign_latent_attributes_is_stable_and_uses_exact_largest_remainder_quotas() -> None:
    spec = LatentAttributeSpec.model_validate(make_spec_payload())
    user_ids = [f"user_{index:02d}" for index in range(10)]

    first = assign_latent_attributes(user_ids, spec, seed=20260630)
    second = assign_latent_attributes(list(reversed(user_ids)), spec, seed=20260630)

    first_rows = [assignment.to_flat_row() for assignment in first.assignments]
    second_rows = [assignment.to_flat_row() for assignment in second.assignments]
    assert first_rows == second_rows

    class_counts: Counter[str] = Counter(str(row["latent_class"]) for row in first_rows)
    assert class_counts == {"class_1": 5, "class_2": 3, "class_3": 2}
    assert first.audit.class_counts["class_1"]["target_count"] == 5
    assert first.audit.class_counts["class_1"]["actual_count"] == 5
    assert first.audit.max_count_deviation == 0
    assert first.audit.max_proportion_deviation == 0.0

    for class_name, class_total in class_counts.items():
        class_rows = [row for row in first_rows if row["latent_class"] == class_name]
        gender_counts: Counter[str] = Counter(str(row["latent_gender"]) for row in class_rows)
        assert sum(gender_counts.values()) == class_total
        for label, counts in first.audit.profile_counts[class_name]["gender"].items():
            assert gender_counts[label] == counts["target_count"]
            assert counts["actual_count"] == counts["target_count"]


def test_assignment_rejects_duplicate_or_empty_user_ids() -> None:
    spec = LatentAttributeSpec.model_validate(make_spec_payload())
    with pytest.raises(ValueError, match="unique"):
        assign_latent_attributes(["u1", "u1"], spec, seed=1)
    with pytest.raises(ValueError, match="empty"):
        assign_latent_attributes(["u1", " "], spec, seed=1)


def test_write_outputs_are_aggregate_and_do_not_include_private_source_fields(tmp_path: Path) -> None:
    spec = LatentAttributeSpec.model_validate(make_spec_payload())
    result = assign_latent_attributes([f"user_{index}" for index in range(12)], spec, seed=7)

    paths = write_latent_assignment_outputs(result, tmp_path)

    rows = read_csv(paths.assignments_csv)
    assert len(rows) == 12
    assert set(rows[0]) == {
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
    }

    audit = json.loads(paths.audit_json.read_text(encoding="utf-8"))
    assert audit["privacy_statement"].startswith("Only stable user_id values")
    assert audit["user_count"] == 12
    assert len(audit["spec_hash"]) == 64

    output_text = "\n".join(path.read_text(encoding="utf-8") for path in paths.__dict__.values())
    for forbidden in ("nickname", "bio", "signature", "raw payload", ".env", "API key", "TIKHUB_API_KEY"):
        assert forbidden not in output_text
