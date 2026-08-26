from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from llm_abm_sim.full_pool_probability_counterfactual import (
    COUNTERFACTUAL_SCHEMA_VERSION,
    ProbabilityCounterfactualRequest,
    run_probability_counterfactual,
    stable_probability_draw,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_source(root: Path) -> str:
    root.mkdir()
    membership_path = root / "latent-membership.csv"
    with membership_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("user_id", "latent_class"))
        writer.writeheader()
        writer.writerows(
            (
                {"user_id": "u1", "latent_class": "class_1"},
                {"user_id": "u2", "latent_class": "class_2"},
            )
        )

    probabilities = {
        ("u1", "message_1"): 0.0,
        ("u1", "message_2"): 1.0,
        ("u1", "message_3"): 0.75,
        ("u2", "message_1"): 0.25,
        ("u2", "message_2"): 0.5,
        ("u2", "message_3"): 0.9,
    }
    terminal_path = root / "terminal_rows.jsonl"
    with terminal_path.open("w", encoding="utf-8") as stream:
        for position, ((user_id, message_id), probability) in enumerate(probabilities.items()):
            source_engage = probability >= 0.5
            latent_class = "class_1" if user_id == "u1" else "class_2"
            environmental = 1.037 if latent_class == "class_1" else -0.833
            row = {
                "terminal_row_id": f"{user_id}:{message_id}:0:primary",
                "pair_id": f"{user_id}:{message_id}:0",
                "pair_schedule_position": position,
                "time_step": position % 2,
                "message_id": message_id,
                "user_id": user_id,
                "decision_variant": "primary",
                "prompt_version": "jinjiang-concurrent-message-primary-prompt-v1",
                "terminal_status": "succeeded",
                "provider_status": "succeeded",
                "engage": "true" if source_engage else "false",
                "probability": probability,
                "action": "like" if source_engage else "ignore",
                "context_profile_payload": json.dumps(
                    {
                        "user_id": user_id,
                        "concurrent_environmental_consciousness_coef": environmental,
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                "prompt_field_inclusion": json.dumps(
                    {"concurrent_environmental_consciousness_coef": "included"},
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            }
            stream.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")

    artifacts = []
    for path in (membership_path, terminal_path):
        artifacts.append(
            {
                "relative_path": path.name,
                "sha256": _sha256(path),
                "bytes": path.stat().st_size,
            }
        )
    manifest = {
        "schema_version": "full-pool-segmented-source-v4",
        "source_identity": "fixture-source-v4",
        "counts": {
            "distinct_users": 2,
            "terminal_rows": 6,
            "committed_batches": 2,
        },
        "row_hashes": {"terminal_rows.jsonl": _sha256(terminal_path)},
        "artifacts": artifacts,
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    return _sha256(manifest_path)


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_probability_counterfactual_realizes_persisted_probability_without_inventing_actions(tmp_path: Path) -> None:
    source = tmp_path / "source"
    manifest_sha256 = _write_source(source)
    source_terminal_sha256 = _sha256(source / "terminal_rows.jsonl")
    output = tmp_path / "counterfactual"

    result = run_probability_counterfactual(
        ProbabilityCounterfactualRequest(
            source_root=source,
            source_manifest_sha256=manifest_sha256,
            output_dir=output,
            seed=20260823,
        )
    )

    assert result.output_dir == output.resolve()
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == COUNTERFACTUAL_SCHEMA_VERSION
    assert manifest["classification"] == "exploratory_fixed_schedule_counterfactual"
    assert manifest["provider_calls"] == 0
    assert manifest["live_api_triggered"] is False
    assert manifest["production_deploy_eligible"] is False
    assert manifest["formal_replacement"] is False
    assert manifest["fixed_exposure_schedule"] is True
    assert manifest["feedback_recomputed"] is False
    assert manifest["environmental_consciousness_policy"] == "retained_from_source_prompt"

    rows = _jsonl(output / "counterfactual_pair_rows.jsonl")
    assert len(rows) == 6
    assert all("counterfactual_action" not in row for row in rows)
    assert all(row["environmental_consciousness_prompt_inclusion"] == "included" for row in rows)
    assert all("environmental_consciousness_coef" in row for row in rows)
    assert next(row for row in rows if row["persisted_probability"] == 0.0)["counterfactual_engaged"] is False
    assert next(row for row in rows if row["persisted_probability"] == 1.0)["counterfactual_engaged"] is True
    assert any(row["source_action"] == "ignore" and row["counterfactual_engaged"] for row in rows)
    assert _sha256(source / "terminal_rows.jsonl") == source_terminal_sha256

    summary = json.loads((output / "counterfactual_summary.json").read_text(encoding="utf-8"))
    assert summary["overall"]["exposures"] == 6
    assert summary["overall"]["mean_persisted_probability"] == pytest.approx(sum((0, 1, 0.75, 0.25, 0.5, 0.9)) / 6)
    assert (output / "segment_message_summary.csv").is_file()
    assert (output / "run_segment_summary.csv").is_file()
    assert (output / "report.md").is_file()


def test_probability_counterfactual_is_seeded_and_refuses_existing_output(tmp_path: Path) -> None:
    pair_id = "u1:message_1:0"
    assert stable_probability_draw(seed=7, pair_id=pair_id) == stable_probability_draw(seed=7, pair_id=pair_id)
    assert stable_probability_draw(seed=7, pair_id=pair_id) != stable_probability_draw(seed=8, pair_id=pair_id)

    source = tmp_path / "source"
    manifest_sha256 = _write_source(source)
    output = tmp_path / "already-exists"
    output.mkdir()
    with pytest.raises(FileExistsError, match="already exists"):
        run_probability_counterfactual(
            ProbabilityCounterfactualRequest(
                source_root=source,
                source_manifest_sha256=manifest_sha256,
                output_dir=output,
                seed=7,
            )
        )
