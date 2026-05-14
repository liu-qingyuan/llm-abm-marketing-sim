from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx

from .schemas import DatasetConfig, ExtraProfilePolicy, MissingProfilePolicy, ProfileFormat, UserProfile

PROFILE_LIST_FIELDS = {"interest_tags"}


@dataclass(frozen=True)
class DatasetValidationReport:
    """Serializable diagnostics for a dataset/profile load."""

    dataset_used: bool
    edge_list_path: str | None
    profile_path: str | None
    profile_format: str | None
    directed: bool
    graph_node_count: int
    graph_edge_count: int
    profile_record_count: int
    profile_count: int
    missing_profile_ids: list[str]
    default_profile_ids: list[str]
    extra_profile_ids: list[str]
    included_extra_profile_ids: list[str]
    ignored_extra_profile_ids: list[str]
    missing_profile_policy: str
    extra_profile_policy: str
    edge_weight_column: str | None
    edge_attribute_columns: list[str]
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return asdict(self)


@dataclass(frozen=True)
class NetworkDataset:
    """Loaded graph, user profiles, and validation diagnostics."""

    graph: nx.Graph
    profiles: dict[str, UserProfile]
    validation_report: DatasetValidationReport


# Backwards-compatible helper retained for existing callers.
def load_edge_list(path: str | Path, delimiter: str | None = None) -> nx.Graph:
    """Load an undirected social-network edge-list file."""

    return _load_graph_from_edge_list(
        Path(path),
        delimiter=delimiter,
        directed=False,
        source_column=None,
        target_column=None,
        edge_weight_column=None,
        edge_attribute_columns=[],
    )


def load_network_dataset(
    dataset_config: DatasetConfig,
    inline_edges: list[tuple[str, str]] | None = None,
    inline_profiles: list[UserProfile] | None = None,
) -> NetworkDataset:
    """Load graph and profile records, then apply graph/profile validation policies."""

    graph = _load_graph(dataset_config, inline_edges or [], inline_profiles or [])
    profile_records = _load_profile_records(dataset_config, inline_profiles or [])
    profile_ids = set(profile_records)
    graph_ids = {str(node) for node in graph.nodes}

    missing_profile_ids = sorted(graph_ids - profile_ids)
    extra_profile_ids = sorted(profile_ids - graph_ids)
    errors: list[str] = []

    if missing_profile_ids and dataset_config.missing_profile_policy is MissingProfilePolicy.ERROR:
        errors.append(f"missing profiles for graph nodes: {', '.join(missing_profile_ids)}")
    if extra_profile_ids and dataset_config.extra_profile_policy is ExtraProfilePolicy.ERROR:
        errors.append(f"profile rows absent from graph: {', '.join(extra_profile_ids)}")

    default_profile_ids: list[str] = []
    included_extra_profile_ids: list[str] = []
    ignored_extra_profile_ids: list[str] = []
    profiles = dict(profile_records)

    if not errors:
        if missing_profile_ids:
            default_profile_ids = missing_profile_ids
            for user_id in missing_profile_ids:
                profiles[user_id] = UserProfile(user_id=user_id)

        if extra_profile_ids:
            if dataset_config.extra_profile_policy is ExtraProfilePolicy.INCLUDE_AS_NODE:
                included_extra_profile_ids = extra_profile_ids
                graph.add_nodes_from(extra_profile_ids)
                graph_ids.update(extra_profile_ids)
            elif dataset_config.extra_profile_policy is ExtraProfilePolicy.IGNORE:
                ignored_extra_profile_ids = extra_profile_ids
                for user_id in extra_profile_ids:
                    profiles.pop(user_id, None)

    report = DatasetValidationReport(
        dataset_used=dataset_config.uses_files,
        edge_list_path=str(dataset_config.edge_list_path) if dataset_config.edge_list_path is not None else None,
        profile_path=str(dataset_config.profile_path) if dataset_config.profile_path is not None else None,
        profile_format=(dataset_config.profile_format.value if dataset_config.profile_format is not None else None),
        directed=dataset_config.directed,
        graph_node_count=graph.number_of_nodes(),
        graph_edge_count=graph.number_of_edges(),
        profile_record_count=len(profile_records),
        profile_count=len(profiles),
        missing_profile_ids=missing_profile_ids,
        default_profile_ids=default_profile_ids,
        extra_profile_ids=extra_profile_ids,
        included_extra_profile_ids=included_extra_profile_ids,
        ignored_extra_profile_ids=ignored_extra_profile_ids,
        missing_profile_policy=dataset_config.missing_profile_policy.value,
        extra_profile_policy=dataset_config.extra_profile_policy.value,
        edge_weight_column=dataset_config.edge_weight_column,
        edge_attribute_columns=list(dataset_config.edge_attribute_columns),
        errors=errors,
    )
    if errors:
        message = "; ".join(errors)
        raise ValueError(f"Dataset validation failed: {message}")
    return NetworkDataset(graph=graph, profiles=dict(sorted(profiles.items())), validation_report=report)


def _load_graph(
    dataset_config: DatasetConfig,
    inline_edges: list[tuple[str, str]],
    inline_profiles: list[UserProfile],
) -> nx.Graph:
    if dataset_config.edge_list_path is not None:
        return _load_graph_from_edge_list(
            dataset_config.edge_list_path,
            delimiter=dataset_config.delimiter,
            directed=dataset_config.directed,
            source_column=dataset_config.source_column,
            target_column=dataset_config.target_column,
            edge_weight_column=dataset_config.edge_weight_column,
            edge_attribute_columns=dataset_config.edge_attribute_columns,
        )

    graph: nx.Graph = nx.DiGraph() if dataset_config.directed else nx.Graph()
    graph.add_edges_from((str(left), str(right)) for left, right in inline_edges)
    for profile in inline_profiles:
        graph.add_node(profile.user_id)
    return graph


def _load_graph_from_edge_list(
    path: Path,
    *,
    delimiter: str | None,
    directed: bool,
    source_column: str | None,
    target_column: str | None,
    edge_weight_column: str | None,
    edge_attribute_columns: list[str],
) -> nx.Graph:
    graph: nx.Graph = nx.DiGraph() if directed else nx.Graph()
    if source_column or target_column:
        if not source_column or not target_column:
            raise ValueError("Both source_column and target_column are required for column-based edge loading")
        _load_column_edges(
            graph,
            Path(path),
            delimiter=_csv_delimiter(Path(path), delimiter),
            source_column=source_column,
            target_column=target_column,
            edge_weight_column=edge_weight_column,
            edge_attribute_columns=edge_attribute_columns,
        )
        return graph

    _load_positional_edges(graph, Path(path), delimiter=delimiter)
    return graph


def _load_column_edges(
    graph: nx.Graph,
    path: Path,
    *,
    delimiter: str,
    source_column: str,
    target_column: str,
    edge_weight_column: str | None,
    edge_attribute_columns: list[str],
) -> None:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        if reader.fieldnames is None:
            raise ValueError(f"Edge file has no header row: {path}")
        missing_columns = [column for column in [source_column, target_column] if column not in reader.fieldnames]
        if missing_columns:
            raise ValueError(f"Edge file is missing required columns: {', '.join(missing_columns)}")
        for row_number, row in enumerate(reader, start=2):
            source = _required_cell(row, source_column, path, row_number)
            target = _required_cell(row, target_column, path, row_number)
            attributes: dict[str, Any] = {}
            if edge_weight_column:
                weight_value = _optional_cell(row, edge_weight_column)
                if weight_value is not None:
                    attributes["weight"] = _parse_scalar(weight_value)
            for column in edge_attribute_columns:
                attribute_value = _optional_cell(row, column)
                if attribute_value is not None:
                    attributes[column] = _parse_scalar(attribute_value)
            graph.add_edge(source, target, **attributes)


def _load_positional_edges(graph: nx.Graph, path: Path, delimiter: str | None) -> None:
    with path.open(newline="", encoding="utf-8") as handle:
        if delimiter is None:
            for row_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                values = stripped.split()
                if len(values) < 2:
                    raise ValueError(f"Edge row {row_number} in {path} must contain at least two columns")
                graph.add_edge(values[0], values[1])
            return

        reader = csv.reader(handle, delimiter=delimiter)
        for row_number, row in enumerate(reader, start=1):
            values = [value.strip() for value in row if value.strip()]
            if not values or values[0].startswith("#"):
                continue
            if len(values) < 2:
                raise ValueError(f"Edge row {row_number} in {path} must contain at least two columns")
            graph.add_edge(values[0], values[1])


def _load_profile_records(
    dataset_config: DatasetConfig,
    inline_profiles: list[UserProfile],
) -> dict[str, UserProfile]:
    if dataset_config.profile_path is None:
        return _dedupe_profiles(inline_profiles)

    profile_format = dataset_config.profile_format or _infer_profile_format(dataset_config.profile_path)
    if profile_format is ProfileFormat.JSON:
        records = _read_json_profile_records(dataset_config.profile_path)
    elif profile_format is ProfileFormat.CSV:
        records = _read_csv_profile_records(
            dataset_config.profile_path, _csv_delimiter(dataset_config.profile_path, dataset_config.delimiter)
        )
    else:  # pragma: no cover - pydantic enum validation should prevent this branch.
        raise ValueError(f"Unsupported profile format: {profile_format}")
    return _dedupe_profiles([UserProfile.model_validate(_normalize_profile_record(record)) for record in records])


def _read_json_profile_records(path: Path) -> list[dict[str, Any]]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(loaded, dict) and "profiles" in loaded:
        loaded = loaded["profiles"]
    if not isinstance(loaded, list):
        raise ValueError("JSON profile files must be a list or an object with a 'profiles' list")
    return [_require_profile_record(record, path) for record in loaded]


def _read_csv_profile_records(path: Path, delimiter: str) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        return [dict(row) for row in reader]


def _normalize_profile_record(record: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in record.items():
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
            if value == "":
                continue
        if key in PROFILE_LIST_FIELDS:
            normalized[key] = _parse_list_value(value)
        else:
            normalized[key] = value
    return normalized


def _dedupe_profiles(profiles: list[UserProfile]) -> dict[str, UserProfile]:
    by_id: dict[str, UserProfile] = {}
    for profile in profiles:
        if profile.user_id in by_id:
            raise ValueError(f"Duplicate profile for user_id: {profile.user_id}")
        by_id[profile.user_id] = profile
    return by_id


def _require_profile_record(record: Any, path: Path) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ValueError(f"Profile record in {path} must be an object")
    return record


def _infer_profile_format(path: Path) -> ProfileFormat:
    if path.suffix.lower() == ".json":
        return ProfileFormat.JSON
    return ProfileFormat.CSV


def _csv_delimiter(path: Path, delimiter: str | None) -> str:
    if delimiter is not None:
        return delimiter
    if path.suffix.lower() == ".tsv":
        return "\t"
    return ","


def _required_cell(row: dict[str, str], column: str, path: Path, row_number: int) -> str:
    value = _optional_cell(row, column)
    if value is None:
        raise ValueError(f"Missing required value for {column!r} in {path} row {row_number}")
    return value


def _optional_cell(row: dict[str, str], column: str) -> str | None:
    value = row.get(column)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _parse_list_value(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if not isinstance(value, str):
        return [str(value)]
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    return [part.strip() for part in re.split(r"[|;,]", value) if part.strip()]


def _parse_scalar(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value
