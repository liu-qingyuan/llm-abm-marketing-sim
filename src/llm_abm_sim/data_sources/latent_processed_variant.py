from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .latent_attributes import (
    LATENT_ASSIGNMENT_COLUMNS,
    LatentUserAssignment,
    assign_latent_attributes,
    load_latent_attribute_spec,
    write_latent_assignment_outputs,
)

USER_TABLES = ("users.csv", "profiles.csv", "abm_user_profiles.csv")


class LatentProcessedVariantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    source_processed_dir: Path
    output_processed_dir: Path
    spec_path: Path
    seed: int
    run_id: str


class LatentProcessedVariantResult(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    output_processed_dir: Path
    user_count: int
    written_files: list[Path]
    audit_path: Path
    markdown_audit_path: Path
    spec_snapshot_path: Path


def generate_latent_processed_variant(
    request: LatentProcessedVariantRequest,
) -> LatentProcessedVariantResult:
    source_dir = request.source_processed_dir
    output_dir = request.output_processed_dir
    if not source_dir.exists() or not source_dir.is_dir():
        raise FileNotFoundError(f"source processed dir does not exist: {source_dir}")
    if source_dir.resolve() == output_dir.resolve():
        raise ValueError("output_processed_dir must be different from source_processed_dir")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"output processed dir already exists and is not empty: {output_dir}")
    _validate_required_user_tables(source_dir)

    output_dir.mkdir(parents=True, exist_ok=True)
    written_files: list[Path] = []
    for source_path in sorted(source_dir.iterdir()):
        target_path = output_dir / source_path.name
        if source_path.is_dir():
            shutil.copytree(source_path, target_path)
            written_files.extend(path for path in sorted(target_path.rglob("*")) if path.is_file())
        else:
            shutil.copy2(source_path, target_path)
            written_files.append(target_path)

    user_rows = _read_csv_rows(output_dir / "users.csv")
    user_ids = _user_ids(user_rows, output_dir / "users.csv")
    spec = load_latent_attribute_spec(request.spec_path)
    assignment_result = assign_latent_attributes(user_ids, spec, seed=request.seed)
    assignments_by_user = {assignment.user_id: assignment for assignment in assignment_result.assignments}
    for filename in USER_TABLES:
        table_path = output_dir / filename
        _merge_latent_columns(table_path, assignments_by_user)
        if table_path not in written_files:
            written_files.append(table_path)

    assignment_paths = write_latent_assignment_outputs(assignment_result, output_dir)
    audit_path = assignment_paths.audit_json
    markdown_audit_path = assignment_paths.audit_markdown
    spec_snapshot_path = assignment_paths.spec_snapshot_yaml
    _write_processed_variant_audit(
        audit_path=audit_path,
        markdown_audit_path=markdown_audit_path,
        source_processed_dir=source_dir,
        output_processed_dir=output_dir,
        run_id=request.run_id,
    )
    readme_path = output_dir / "README.md"
    readme_path.write_text(
        _render_readme(
            source_processed_dir=source_dir,
            output_processed_dir=output_dir,
            run_id=request.run_id,
            user_count=len(user_rows),
        ),
        encoding="utf-8",
    )
    for path in (
        assignment_paths.assignments_csv,
        audit_path,
        markdown_audit_path,
        spec_snapshot_path,
        readme_path,
    ):
        if path not in written_files:
            written_files.append(path)
    return LatentProcessedVariantResult(
        output_processed_dir=output_dir,
        user_count=len(user_rows),
        written_files=written_files,
        audit_path=audit_path,
        markdown_audit_path=markdown_audit_path,
        spec_snapshot_path=spec_snapshot_path,
    )


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _validate_required_user_tables(source_dir: Path) -> None:
    missing = [filename for filename in USER_TABLES if not (source_dir / filename).exists()]
    if missing:
        raise FileNotFoundError(f"source processed dir is missing required user table(s): {missing}")


def _user_ids(rows: list[dict[str, str]], path: Path) -> list[str]:
    user_ids = [str(row.get("user_id") or "").strip() for row in rows]
    if any(not user_id for user_id in user_ids):
        raise ValueError(f"{path} must contain non-empty user_id values")
    return user_ids


def _merge_latent_columns(path: Path, assignments_by_user: dict[str, LatentUserAssignment]) -> None:
    rows = _read_csv_rows(path)
    if not rows:
        return
    fieldnames = list(rows[0])
    latent_columns = [column for column in LATENT_ASSIGNMENT_COLUMNS if column != "user_id"]
    for column in latent_columns:
        if column not in fieldnames:
            fieldnames.append(column)

    merged_rows: list[dict[str, object]] = []
    for row in rows:
        user_id = str(row.get("user_id") or "").strip()
        if not user_id:
            raise ValueError(f"{path} must contain non-empty user_id values")
        assignment = assignments_by_user.get(user_id)
        if assignment is None:
            raise ValueError(f"{path} contains user_id not present in users.csv: {user_id}")
        flat_assignment = assignment.to_flat_row()
        merged_rows.append({**row, **{column: flat_assignment[column] for column in latent_columns}})

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(merged_rows)


def _write_processed_variant_audit(
    *,
    audit_path: Path,
    markdown_audit_path: Path,
    source_processed_dir: Path,
    output_processed_dir: Path,
    run_id: str,
) -> None:
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit = {
        "source_run": source_processed_dir.name,
        "output_run": run_id,
        "source_processed_dir": str(source_processed_dir),
        "output_processed_dir": str(output_processed_dir),
        "variant_type": "latent-v1 derived processed variant",
        "virtual_label_boundary": (
            "Latent labels are Virtual Experiment Labels for simulation grouping; "
            "they are not real user identity or observed Douyin profile facts."
        ),
        **audit,
    }
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_audit_path.write_text(_render_processed_audit_markdown(audit), encoding="utf-8")


def _render_processed_audit_markdown(audit: dict[str, object]) -> str:
    lines = [
        "# Latent Attribute Processed Variant Audit",
        "",
        "- variant: `latent-v1 derived processed variant`",
        f"- source_run: `{audit['source_run']}`",
        f"- output_run: `{audit['output_run']}`",
        f"- spec_id: `{audit['spec_id']}`",
        f"- method: `{audit['method']}`",
        f"- seed: `{audit['seed']}`",
        f"- user_count: `{audit['user_count']}`",
        f"- spec_hash: `{audit['spec_hash']}`",
        f"- max_count_deviation: `{audit['max_count_deviation']}`",
        f"- max_proportion_deviation: `{audit['max_proportion_deviation']}`",
        f"- privacy: {audit['privacy_statement']}",
        "",
        "## Virtual Experiment Labels",
        "",
        "Latent labels are Virtual Experiment Labels for simulation grouping; they are not real user identity or observed Douyin profile facts.",
        "",
        "## Class Counts",
        "",
        "| class | target | actual | count deviation | proportion deviation |",
        "|---|---:|---:|---:|---:|",
    ]
    class_counts = audit.get("class_counts")
    if isinstance(class_counts, dict):
        for class_name, counts in class_counts.items():
            if isinstance(counts, dict):
                lines.append(
                    f"| {class_name} | {counts['target_count']} | {counts['actual_count']} | "
                    f"{counts['count_deviation']} | {counts['proportion_deviation']} |"
                )
    lines.append("")
    lines.append("## Profile Counts")
    lines.append("")
    lines.append("| class | field | label | target | actual | count deviation | proportion deviation |")
    lines.append("|---|---|---|---:|---:|---:|---:|")
    profile_counts = audit.get("profile_counts")
    if isinstance(profile_counts, dict):
        for class_name, field_counts in profile_counts.items():
            if not isinstance(field_counts, dict):
                continue
            for field_name, label_counts in field_counts.items():
                if not isinstance(label_counts, dict):
                    continue
                for label, counts in label_counts.items():
                    if isinstance(counts, dict):
                        lines.append(
                            f"| {class_name} | {field_name} | {label} | {counts['target_count']} | "
                            f"{counts['actual_count']} | {counts['count_deviation']} | "
                            f"{counts['proportion_deviation']} |"
                        )
    lines.append("")
    return "\n".join(lines)


def _render_readme(
    *,
    source_processed_dir: Path,
    output_processed_dir: Path,
    run_id: str,
    user_count: int,
) -> str:
    return "\n".join(
        [
            "# Jinjiang latent-v1 derived processed variant",
            "",
            f"- output_run: `{run_id}`",
            f"- source_run: `{source_processed_dir.name}`",
            f"- source_processed_dir: `{source_processed_dir}`",
            f"- output_processed_dir: `{output_processed_dir}`",
            f"- user_count: `{user_count}`",
            "",
            "## Virtual Experiment Labels",
            "",
            "The `latent_` columns are Virtual Experiment Labels for controlled ABM simulation grouping. They are not real user identity, observed Douyin profile facts, third-party demographic labels, or psychological profiles.",
            "",
            "## Privacy Boundary",
            "",
            "Generation uses stable `user_id` values and the latent attribute spec. It does not read credentials, dotenv files, live providers, profile free text, or source payload detail.",
            "",
            "## Outputs",
            "",
            "- `users.csv`, `profiles.csv`, and `abm_user_profiles.csv` preserve source user rows and append `latent_` fields.",
            "- `latent_attribute_assignments.csv` contains one flat assignment row per user.",
            "- `latent_attribute_spec.yaml` snapshots the spec used for this run.",
            "- `latent_attribute_audit.json` and `latent_attribute_audit.md` contain aggregate assignment checks.",
            "",
        ]
    )
