import json

import networkx as nx
import pytest

from llm_abm_sim.graph_loader import load_network_dataset
from llm_abm_sim.schemas import DatasetConfig, ExtraProfilePolicy, MissingProfilePolicy, ProfileFormat, UserProfile


def test_load_network_dataset_returns_directed_graph_profiles_and_serializable_report(tmp_path):
    edges = tmp_path / "edges.csv"
    edges.write_text(
        "source,target,influence_weight,relationship\nu1,u2,0.7,friend\nu2,u3,0.2,colleague\n",
        encoding="utf-8",
    )
    profiles = tmp_path / "profiles.json"
    profiles.write_text(
        json.dumps(
            [
                {"user_id": "u1", "interest_tags": ["eco", "skincare"], "brand_attitude": 0.8},
                {"user_id": "u2", "interest_tags": ["skincare"], "activity_level": 0.7},
                {"user_id": "u3", "interest_tags": ["gaming"], "brand_attitude": -0.2},
            ]
        ),
        encoding="utf-8",
    )

    dataset = load_network_dataset(
        DatasetConfig(
            edge_list_path=edges,
            profile_path=profiles,
            profile_format=ProfileFormat.JSON,
            directed=True,
            source_column="source",
            target_column="target",
            edge_weight_column="influence_weight",
            edge_attribute_columns=["relationship"],
            missing_profile_policy=MissingProfilePolicy.ERROR,
        )
    )

    assert isinstance(dataset.graph, nx.DiGraph)
    assert sorted(dataset.graph.nodes) == ["u1", "u2", "u3"]
    assert dataset.graph["u1"]["u2"]["weight"] == 0.7
    assert dataset.graph["u1"]["u2"]["relationship"] == "friend"
    assert dataset.profiles["u1"].interest_tags == ["eco", "skincare"]
    assert dataset.profiles["u3"].brand_attitude == -0.2

    report = dataset.validation_report.to_dict()
    assert report["dataset_used"] is True
    assert report["directed"] is True
    assert report["graph_node_count"] == 3
    assert report["graph_edge_count"] == 2
    assert report["profile_record_count"] == 3
    assert report["profile_count"] == 3
    assert report["missing_profile_ids"] == []
    assert report["extra_profile_ids"] == []
    assert report["edge_weight_column"] == "influence_weight"
    assert report["edge_attribute_columns"] == ["relationship"]
    json.dumps(report)


def test_load_network_dataset_parses_csv_profiles_and_defaults_missing_profiles(tmp_path):
    edges = tmp_path / "edges.csv"
    edges.write_text("u1 u2\nu2 u3\n", encoding="utf-8")
    profiles = tmp_path / "profiles.csv"
    profiles.write_text(
        "user_id,interest_tags,brand_attitude,activity_level\nu1,eco|skincare,0.5,0.9\nu2,gaming,-0.1,0.4\n",
        encoding="utf-8",
    )

    dataset = load_network_dataset(
        DatasetConfig(
            edge_list_path=edges,
            profile_path=profiles,
            profile_format=ProfileFormat.CSV,
            missing_profile_policy=MissingProfilePolicy.DEFAULT,
        )
    )

    assert isinstance(dataset.graph, nx.Graph)
    assert sorted(dataset.profiles) == ["u1", "u2", "u3"]
    assert dataset.profiles["u1"].interest_tags == ["eco", "skincare"]
    assert dataset.profiles["u3"] == UserProfile(user_id="u3")
    assert dataset.validation_report.missing_profile_ids == ["u3"]
    assert dataset.validation_report.default_profile_ids == ["u3"]


def test_load_network_dataset_supports_extra_profile_policies(tmp_path):
    edges = tmp_path / "edges.csv"
    edges.write_text("u1,u2\n", encoding="utf-8")
    profiles = tmp_path / "profiles.json"
    profiles.write_text(
        json.dumps(
            [
                {"user_id": "u1"},
                {"user_id": "u2"},
                {"user_id": "u-extra", "interest_tags": ["bonus"]},
            ]
        ),
        encoding="utf-8",
    )

    ignored = load_network_dataset(
        DatasetConfig(edge_list_path=edges, profile_path=profiles, profile_format=ProfileFormat.JSON, delimiter=",")
    )
    assert sorted(ignored.graph.nodes) == ["u1", "u2"]
    assert "u-extra" not in ignored.profiles
    assert ignored.validation_report.ignored_extra_profile_ids == ["u-extra"]

    included = load_network_dataset(
        DatasetConfig(
            edge_list_path=edges,
            profile_path=profiles,
            profile_format=ProfileFormat.JSON,
            delimiter=",",
            extra_profile_policy=ExtraProfilePolicy.INCLUDE_AS_NODE,
        )
    )
    assert sorted(included.graph.nodes) == ["u-extra", "u1", "u2"]
    assert "u-extra" in included.profiles
    assert included.validation_report.included_extra_profile_ids == ["u-extra"]


def test_load_network_dataset_errors_for_validation_policy_violations(tmp_path):
    edges = tmp_path / "edges.csv"
    edges.write_text("u1 u2\n", encoding="utf-8")
    profiles = tmp_path / "profiles.json"
    profiles.write_text(json.dumps([{"user_id": "u1"}, {"user_id": "u-extra"}]), encoding="utf-8")

    with pytest.raises(ValueError, match="missing profiles.*u2"):
        load_network_dataset(
            DatasetConfig(
                edge_list_path=edges,
                profile_path=profiles,
                profile_format=ProfileFormat.JSON,
                missing_profile_policy=MissingProfilePolicy.ERROR,
            )
        )

    with pytest.raises(ValueError, match="absent from graph.*u-extra"):
        load_network_dataset(
            DatasetConfig(
                edge_list_path=edges,
                profile_path=profiles,
                profile_format=ProfileFormat.JSON,
                extra_profile_policy=ExtraProfilePolicy.ERROR,
            )
        )


def test_load_network_dataset_reads_profile_object_json_and_comma_lists(tmp_path):
    edges = tmp_path / "edges.csv"
    edges.write_text("left,right\nu1,u2\n", encoding="utf-8")
    profiles = tmp_path / "profiles.json"
    profiles.write_text(
        json.dumps(
            {
                "profiles": [
                    {"user_id": "u1", "interest_tags": "eco, skincare", "activity_level": 0.9},
                    {"user_id": "u2", "interest_tags": "gaming; wellness", "brand_attitude": -0.4},
                ]
            }
        ),
        encoding="utf-8",
    )

    dataset = load_network_dataset(
        DatasetConfig(
            edge_list_path=edges,
            profile_path=profiles,
            profile_format=ProfileFormat.JSON,
            delimiter=",",
            source_column="left",
            target_column="right",
        )
    )

    assert sorted(dataset.graph.edges) == [("u1", "u2")]
    assert dataset.profiles["u1"].interest_tags == ["eco", "skincare"]
    assert dataset.profiles["u2"].interest_tags == ["gaming", "wellness"]
    assert dataset.validation_report.profile_format == "json"


def test_load_network_dataset_rejects_duplicate_profile_ids(tmp_path):
    edges = tmp_path / "edges.csv"
    edges.write_text("u1 u2\n", encoding="utf-8")
    profiles = tmp_path / "profiles.csv"
    profiles.write_text("user_id,interest_tags\nu1,eco\nu1,skincare\nu2,eco\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Duplicate profile.*u1"):
        load_network_dataset(
            DatasetConfig(edge_list_path=edges, profile_path=profiles, profile_format=ProfileFormat.CSV)
        )
