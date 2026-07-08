from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from llm_abm_sim.data_sources.latent_attributes import LATENT_ASSIGNMENT_COLUMNS
from llm_abm_sim.data_sources.latent_processed_variant import (
    LatentProcessedVariantRequest,
    generate_latent_processed_variant,
)

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "generate_jinjiang_latent_attributes.py"


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


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def make_source_processed_run(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "processed" / "source-run"
    rows = [
        {"user_id": "u1", "nickname": "Alice", "brand_attitude": "0.0", "like_tendency": "0.5", "comment_tendency": "0.2", "share_tendency": "0.2"},
        {"user_id": "u2", "nickname": "Bob", "brand_attitude": "0.0", "like_tendency": "0.5", "comment_tendency": "0.2", "share_tendency": "0.2"},
        {"user_id": "u3", "nickname": "Carol", "brand_attitude": "0.0", "like_tendency": "0.5", "comment_tendency": "0.2", "share_tendency": "0.2"},
        {"user_id": "u4", "nickname": "Dan", "brand_attitude": "0.0", "like_tendency": "0.5", "comment_tendency": "0.2", "share_tendency": "0.2"},
    ]
    for filename in ("users.csv", "profiles.csv", "abm_user_profiles.csv"):
        write_csv(source / filename, ["user_id", "nickname", "brand_attitude", "like_tendency", "comment_tendency", "share_tendency"], rows)
    write_csv(source / "edges.csv", ["source", "target", "weight"], [{"source": "u1", "target": "u2", "weight": 1}])
    (source / "collection_report.json").write_text(json.dumps({"run_id": "source-run"}), encoding="utf-8")
    spec_path = tmp_path / "latent_spec.yaml"
    spec_path.write_text(yaml.safe_dump(make_spec_payload(), allow_unicode=True, sort_keys=False), encoding="utf-8")
    return source, spec_path


def test_generate_latent_processed_variant_creates_derived_run_without_mutating_source(tmp_path: Path) -> None:
    source, spec_path = make_source_processed_run(tmp_path)
    before = {path.relative_to(source): path.read_bytes() for path in source.iterdir() if path.is_file()}
    output = tmp_path / "processed" / "latent-run"

    result = generate_latent_processed_variant(
        LatentProcessedVariantRequest(
            source_processed_dir=source,
            output_processed_dir=output,
            spec_path=spec_path,
            seed=20260630,
            run_id="latent-run",
        )
    )

    assert result.output_processed_dir == output
    assert output.exists()
    assert (output / "edges.csv").read_text(encoding="utf-8") == (source / "edges.csv").read_text(encoding="utf-8")
    assert {path.relative_to(source): path.read_bytes() for path in source.iterdir() if path.is_file()} == before
    assert read_csv(output / "users.csv")


def test_generate_latent_processed_variant_adds_latent_columns_to_user_tables(tmp_path: Path) -> None:
    source, spec_path = make_source_processed_run(tmp_path)
    output = tmp_path / "processed" / "latent-run"

    result = generate_latent_processed_variant(
        LatentProcessedVariantRequest(
            source_processed_dir=source,
            output_processed_dir=output,
            spec_path=spec_path,
            seed=20260630,
            run_id="latent-run",
        )
    )

    assert result.user_count == 4
    latent_columns = set(LATENT_ASSIGNMENT_COLUMNS) - {"user_id"}
    removed_fields = {"brand_attitude", "like_tendency", "comment_tendency", "share_tendency"}
    for filename in ("users.csv", "profiles.csv", "abm_user_profiles.csv"):
        source_rows = read_csv(source / filename)
        output_rows = read_csv(output / filename)
        assert [row["user_id"] for row in output_rows] == [row["user_id"] for row in source_rows]
        assert (set(source_rows[0]) - removed_fields).issubset(output_rows[0])
        assert removed_fields.isdisjoint(output_rows[0])
        assert latent_columns.issubset(output_rows[0])
        assert all(row["latent_class"] for row in output_rows)


def test_generate_latent_processed_variant_requires_all_user_tables(tmp_path: Path) -> None:
    source, spec_path = make_source_processed_run(tmp_path)
    (source / "abm_user_profiles.csv").unlink()

    with pytest.raises(FileNotFoundError, match="abm_user_profiles.csv"):
        generate_latent_processed_variant(
            LatentProcessedVariantRequest(
                source_processed_dir=source,
                output_processed_dir=tmp_path / "processed" / "latent-run",
                spec_path=spec_path,
                seed=20260630,
                run_id="latent-run",
            )
        )


def test_generate_latent_processed_variant_writes_artifacts_with_virtual_label_boundary(tmp_path: Path) -> None:
    source, spec_path = make_source_processed_run(tmp_path)
    output = tmp_path / "processed" / "latent-run"

    result = generate_latent_processed_variant(
        LatentProcessedVariantRequest(
            source_processed_dir=source,
            output_processed_dir=output,
            spec_path=spec_path,
            seed=20260630,
            run_id="latent-run",
        )
    )

    assert result.audit_path == output / "latent_attribute_audit.json"
    assert result.markdown_audit_path == output / "latent_attribute_audit.md"
    assert result.spec_snapshot_path == output / "latent_attribute_spec.yaml"
    for path in [result.audit_path, result.markdown_audit_path, result.spec_snapshot_path, output / "README.md"]:
        assert path.exists()
        assert path in result.written_files

    audit = json.loads(result.audit_path.read_text(encoding="utf-8"))
    assert audit["source_run"] == "source-run"
    assert audit["output_run"] == "latent-run"
    assert audit["user_count"] == 4
    assert audit["privacy_statement"].startswith("Only stable user_id values")
    assert audit["class_counts"]["class_1"]["actual_count"] == 2
    assert "gender" in audit["profile_counts"]["class_1"]

    spec_snapshot = yaml.safe_load(result.spec_snapshot_path.read_text(encoding="utf-8"))
    assert spec_snapshot["spec_id"] == "jinjiang_user_latent_attributes_v1"
    assert len(spec_snapshot["spec_hash"]) == 64

    report_text = "\n".join(
        [
            result.markdown_audit_path.read_text(encoding="utf-8"),
            (output / "README.md").read_text(encoding="utf-8"),
        ]
    )
    assert "latent-v1 derived processed variant" in report_text
    assert "Virtual Experiment Labels" in report_text
    assert "not real user identity" in report_text
    assert "| class_1 | gender |" in report_text
    for forbidden in ("bio", "signature", "raw payload", ".env", "TIKHUB_API_KEY"):
        assert forbidden not in report_text


def test_generate_jinjiang_latent_attributes_cli_smoke_does_not_read_env_or_live_api(tmp_path: Path) -> None:
    source, spec_path = make_source_processed_run(tmp_path)
    (tmp_path / ".env").write_text("TIKHUB_API_KEY=must_not_be_printed\n", encoding="utf-8")
    output = tmp_path / "processed" / "latent-run"
    env = {**os.environ, "PYTHONPATH": str(Path.cwd() / "src")}

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--source-processed-dir",
            str(source),
            "--spec",
            str(spec_path),
            "--output-processed-dir",
            str(output),
            "--seed",
            "20260630",
        ],
        cwd=tmp_path,
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )

    payload = json.loads(result.stdout)
    assert payload["output_processed_dir"] == str(output)
    assert payload["user_count"] == 4
    assert (output / "latent_attribute_audit.json").exists()
    combined_output = result.stdout + result.stderr
    for forbidden in ("must_not_be_printed", "TIKHUB_API_KEY", "Bearer", "live API"):
        assert forbidden not in combined_output
