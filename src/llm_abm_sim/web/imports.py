from __future__ import annotations

import csv
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from llm_abm_sim.graph_loader import DatasetValidationReport, load_network_dataset
from llm_abm_sim.safe_serialization import safe_data
from llm_abm_sim.schemas import DatasetConfig, ProfileFormat

FORBIDDEN_PROFILE_FRAGMENTS = (
    "authorization",
    "cookie",
    "access_token",
    "token",
    "secret",
    "password",
    "credential",
    "headers",
    "raw_prompt",
    "raw_provider",
)


@dataclass(frozen=True)
class DatasetUpload:
    validation_id: str
    work_dir: Path
    users_path: Path
    edges_path: Path
    dataset_config: DatasetConfig
    validation_report: DatasetValidationReport

    def safe_report(self) -> dict[str, Any]:
        return safe_dataset_validation_report(self.validation_report)


def validate_upload_files(
    *,
    root_dir: Path,
    users_filename: str,
    users_source: Path,
    edges_filename: str,
    edges_source: Path,
    seed_user_ids: list[str] | None = None,
) -> DatasetUpload:
    """Normalize uploaded dataset files and validate through load_network_dataset."""

    validation_id = f"dataset-{uuid4().hex[:12]}"
    work_dir = root_dir / "uploads" / validation_id
    work_dir.mkdir(parents=True, exist_ok=True)

    users_path = _normalize_users_file(users_source, users_filename, work_dir)
    edges_path, edge_columns = _normalize_edges_file(edges_source, edges_filename, work_dir)
    dataset_config = DatasetConfig(
        edge_list_path=edges_path,
        profile_path=users_path,
        profile_format=ProfileFormat.JSON if users_path.suffix.lower() == ".json" else ProfileFormat.CSV,
        delimiter=",",
        source_column="source",
        target_column="target",
        edge_weight_column="weight" if "weight" in edge_columns else None,
        edge_attribute_columns=[column for column in edge_columns if column not in {"source", "target", "weight"}],
    )
    validation_report = load_network_dataset(dataset_config, seed_user_ids=seed_user_ids or []).validation_report
    return DatasetUpload(
        validation_id=validation_id,
        work_dir=work_dir,
        users_path=users_path,
        edges_path=edges_path,
        dataset_config=dataset_config,
        validation_report=validation_report,
    )


def safe_dataset_validation_report(report: DatasetValidationReport) -> dict[str, Any]:
    """Return a Web-safe validation payload without forbidden uploaded attribute names."""

    payload = report.to_dict()
    for key in ("preserved_profile_attribute_columns", "available_edge_columns", "edge_attribute_columns"):
        values = payload.get(key)
        if isinstance(values, list):
            payload[key] = [value for value in values if not _is_forbidden_name(str(value))]
    errors = payload.get("errors")
    if isinstance(errors, list):
        payload["errors"] = [_redact_forbidden_fragments(str(error)) for error in errors]
    return safe_data(payload)


def _normalize_users_file(source: Path, filename: str, work_dir: Path) -> Path:
    suffix = Path(filename).suffix.lower()
    if suffix == ".json":
        loaded = json.loads(source.read_text(encoding="utf-8"))
        if isinstance(loaded, dict) and "profiles" in loaded:
            records = loaded["profiles"]
        else:
            records = loaded
        if not isinstance(records, list):
            raise ValueError("users JSON must be a list or an object with a 'profiles' list")
        safe_records = [_drop_forbidden_keys(_require_object(record, "profile")) for record in records]
        path = work_dir / "users.json"
        path.write_text(json.dumps(safe_records, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
    path = work_dir / "users.csv"
    _copy_csv_dropping_forbidden_columns(source, path)
    return path


def _normalize_edges_file(source: Path, filename: str, work_dir: Path) -> tuple[Path, list[str]]:
    suffix = Path(filename).suffix.lower()
    path = work_dir / "edges.csv"
    if suffix == ".json":
        loaded = json.loads(source.read_text(encoding="utf-8"))
        if isinstance(loaded, dict) and "edges" in loaded:
            loaded = loaded["edges"]
        if not isinstance(loaded, list):
            raise ValueError("edges JSON must be a list or an object with an 'edges' list")
        records = [_drop_forbidden_keys(_require_object(record, "edge")) for record in loaded]
        if not records:
            raise ValueError("edges JSON must contain at least one edge")
        for index, record in enumerate(records, start=1):
            if not str(record.get("source", "")).strip() or not str(record.get("target", "")).strip():
                raise ValueError(f"edge {index} is missing required source/target")
        columns = _ordered_columns(records, required=("source", "target"), preferred=("weight", "relationship"))
        _write_csv_records(path, records, columns)
        return path, columns

    shutil.copyfile(source, path)
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        columns = list(reader.fieldnames or [])
    if "source" not in columns or "target" not in columns:
        raise ValueError("edges CSV must include source and target columns")
    return path, [column for column in columns if not _is_forbidden_name(column)]


def _copy_csv_dropping_forbidden_columns(source: Path, destination: Path) -> None:
    with source.open(newline="", encoding="utf-8") as input_handle:
        reader = csv.DictReader(input_handle)
        if reader.fieldnames is None:
            raise ValueError("users CSV must include a header row")
        fieldnames = [field for field in reader.fieldnames if not _is_forbidden_name(field)]
        if "user_id" not in fieldnames:
            raise ValueError("users CSV must include user_id column")
        rows = [{field: row.get(field, "") for field in fieldnames} for row in reader]
    with destination.open("w", newline="", encoding="utf-8") as output_handle:
        writer = csv.DictWriter(output_handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_csv_records(path: Path, records: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for record in records:
            writer.writerow({column: record.get(column, "") for column in columns})


def _ordered_columns(
    records: list[dict[str, Any]], *, required: tuple[str, ...], preferred: tuple[str, ...]
) -> list[str]:
    discovered: list[str] = []
    for record in records:
        for key in record:
            if key not in discovered and not _is_forbidden_name(key):
                discovered.append(key)
    ordered = [key for key in required if key in discovered]
    ordered.extend(key for key in preferred if key in discovered and key not in ordered)
    ordered.extend(key for key in discovered if key not in ordered)
    return ordered


def _require_object(record: Any, label: str) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ValueError(f"{label} records must be objects")
    return record


def _drop_forbidden_keys(record: dict[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in record.items() if not _is_forbidden_name(str(key))}


def _is_forbidden_name(name: str) -> bool:
    lowered = name.lower()
    return any(fragment in lowered for fragment in FORBIDDEN_PROFILE_FRAGMENTS)


def _redact_forbidden_fragments(text: str) -> str:
    redacted = text
    for fragment in FORBIDDEN_PROFILE_FRAGMENTS:
        redacted = redacted.replace(fragment, "<redacted>")
        redacted = redacted.replace(fragment.upper(), "<redacted>")
    return redacted
