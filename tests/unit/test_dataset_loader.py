import json
from pathlib import Path

import networkx as nx
import pytest

from llm_abm_sim.graph_loader import load_network_dataset
from llm_abm_sim.schemas import DatasetConfig, ExtraProfilePolicy, MissingProfilePolicy, ProfileFormat, UserProfile

LATENT_COLUMNS = [
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

VALID_LATENT_VALUES = [
    "jinjiang_user_latent_attributes_v1",
    "latent_class_exact_quota_v1",
    "20260630",
    "class_1",
    "1.037",
    "-1.678",
    "2.054",
    "-0.938",
    "1.502",
    "-1.517",
    "0.576",
    "economy",
    "business",
    "female",
    "age_26_35",
    "bachelor",
    "income_8001_15000",
]


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
                {"user_id": "u2", "interest_tags": ["skincare"], "activity_score": 0.7},
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
        "user_id,interest_tags,brand_attitude,activity_score\nu1,eco|skincare,0.5,0.9\nu2,gaming,-0.1,0.4\n",
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
    assert dataset.profiles["u1"].latent_attributes is None
    assert dataset.profiles["u3"] == UserProfile(user_id="u3")
    assert dataset.validation_report.missing_profile_ids == ["u3"]
    assert dataset.validation_report.default_profile_ids == ["u3"]


def test_load_network_dataset_parses_flat_latent_profile_columns(tmp_path):
    edges = tmp_path / "edges.csv"
    edges.write_text("u1 u2\n", encoding="utf-8")
    profiles = tmp_path / "profiles.csv"
    header = ["user_id", "interest_tags", "unknown_metric", *LATENT_COLUMNS]
    profiles.write_text(
        ",".join(header)
        + "\n"
        + ",".join(["u1", "eco|hotel", "kept", *VALID_LATENT_VALUES])
        + "\n"
        + ",".join(["u2", "hotel", "also-kept", *([""] * len(LATENT_COLUMNS))])
        + "\n",
        encoding="utf-8",
    )

    dataset = load_network_dataset(
        DatasetConfig(edge_list_path=edges, profile_path=profiles, profile_format=ProfileFormat.CSV)
    )

    attributes = dataset.profiles["u1"].latent_attributes
    assert attributes is not None
    assert attributes.spec_id == "jinjiang_user_latent_attributes_v1"
    assert attributes.method == "latent_class_exact_quota_v1"
    assert attributes.seed == 20260630
    assert attributes.latent_class == "class_1"
    assert attributes.environmental_consciousness_coef == 1.037
    assert attributes.value_weights.epistemic == -1.678
    assert attributes.value_weights.environmental == 2.054
    assert attributes.value_weights.functional == -0.938
    assert attributes.value_weights.health == 1.502
    assert attributes.value_weights.emotional == -1.517
    assert attributes.value_weights.social == 0.576
    assert attributes.profile_labels.hotel_class == "economy"
    assert attributes.profile_labels.travel_purpose == "business"
    assert attributes.profile_labels.gender == "female"
    assert attributes.profile_labels.age == "age_26_35"
    assert attributes.profile_labels.education == "bachelor"
    assert attributes.profile_labels.monthly_income == "income_8001_15000"
    assert dataset.profiles["u2"].latent_attributes is None

    extras = dataset.profiles["u1"].model_extra or {}
    assert extras["unknown_metric"] == "kept"
    assert "latent_class" not in extras
    assert "latent_epistemic_value_weight" not in extras
    assert dataset.validation_report.preserved_profile_attribute_columns == ["unknown_metric"]


def test_load_network_dataset_parses_flat_latent_json_profile_columns(tmp_path):
    edges = tmp_path / "edges.csv"
    edges.write_text("u1 u2\n", encoding="utf-8")
    profiles = tmp_path / "profiles.json"
    profiles.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "user_id": "u1",
                        **dict(zip(LATENT_COLUMNS, VALID_LATENT_VALUES, strict=True)),
                    },
                    {"user_id": "u2"},
                ]
            }
        ),
        encoding="utf-8",
    )

    dataset = load_network_dataset(
        DatasetConfig(edge_list_path=edges, profile_path=profiles, profile_format=ProfileFormat.JSON)
    )

    assert dataset.profiles["u1"].latent_attributes is not None
    assert dataset.profiles["u1"].latent_attributes.profile_labels.monthly_income == "income_8001_15000"
    assert dataset.profiles["u2"].latent_attributes is None


def test_load_network_dataset_rejects_incomplete_latent_profile_columns(tmp_path):
    edges = tmp_path / "edges.csv"
    edges.write_text("u1 u2\n", encoding="utf-8")
    profiles = tmp_path / "profiles.csv"
    profiles.write_text(
        "user_id,latent_attribute_spec_id,latent_class\nu1,jinjiang_user_latent_attributes_v1,class_1\nu2,,\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="incomplete latent attributes.*latent_attribute_method"):
        load_network_dataset(DatasetConfig(edge_list_path=edges, profile_path=profiles, profile_format=ProfileFormat.CSV))


def test_load_network_dataset_rejects_invalid_latent_class_and_numeric_values(tmp_path):
    edges = tmp_path / "edges.csv"
    edges.write_text("u1 u2\n", encoding="utf-8")
    header = ["user_id", *LATENT_COLUMNS]

    invalid_class = tmp_path / "invalid_class_profiles.csv"
    invalid_values = VALID_LATENT_VALUES.copy()
    invalid_values[LATENT_COLUMNS.index("latent_class")] = "class_4"
    invalid_class.write_text(
        ",".join(header) + "\n" + ",".join(["u1", *invalid_values]) + "\n" + ",".join(["u2", *VALID_LATENT_VALUES]),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="latent_attributes.latent_class"):
        load_network_dataset(
            DatasetConfig(edge_list_path=edges, profile_path=invalid_class, profile_format=ProfileFormat.CSV)
        )

    invalid_profile_label = tmp_path / "invalid_profile_label_profiles.csv"
    invalid_values = VALID_LATENT_VALUES.copy()
    invalid_values[LATENT_COLUMNS.index("latent_monthly_income")] = "income_unknown"
    invalid_profile_label.write_text(
        ",".join(header) + "\n" + ",".join(["u1", *invalid_values]) + "\n" + ",".join(["u2", *VALID_LATENT_VALUES]),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="latent_attributes.profile_labels.monthly_income"):
        load_network_dataset(
            DatasetConfig(edge_list_path=edges, profile_path=invalid_profile_label, profile_format=ProfileFormat.CSV)
        )

    invalid_seed = tmp_path / "invalid_seed_profiles.csv"
    invalid_values = VALID_LATENT_VALUES.copy()
    invalid_values[LATENT_COLUMNS.index("latent_attribute_seed")] = "not-a-number"
    invalid_seed.write_text(
        ",".join(header) + "\n" + ",".join(["u1", *invalid_values]) + "\n" + ",".join(["u2", *VALID_LATENT_VALUES]),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="latent_attributes.seed"):
        load_network_dataset(
            DatasetConfig(edge_list_path=edges, profile_path=invalid_seed, profile_format=ProfileFormat.CSV)
        )


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
                    {"user_id": "u1", "interest_tags": "eco, skincare", "activity_score": 0.9},
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


def test_realistic_marketing_fixture_preserves_real_data_attributes():
    dataset = load_network_dataset(
        DatasetConfig(
            edge_list_path=Path("tests/fixtures/datasets/realistic_marketing_edges.csv"),
            profile_path=Path("tests/fixtures/datasets/realistic_marketing_profiles.csv"),
            profile_format=ProfileFormat.CSV,
            delimiter=",",
            directed=True,
            source_column="source",
            target_column="target",
            edge_weight_column="influence_weight",
            edge_attribute_columns=[
                "relationship",
                "touchpoint",
                "frequency_per_week",
                "recency_days",
                "community_bridge",
            ],
            missing_profile_policy=MissingProfilePolicy.ERROR,
            extra_profile_policy=ExtraProfilePolicy.ERROR,
        ),
        seed_user_ids=["u01", "u11", "u19", "u29"],
    )

    assert isinstance(dataset.graph, nx.DiGraph)
    assert dataset.graph.number_of_nodes() == 36
    assert dataset.graph.number_of_edges() == 45
    edge = dataset.graph["u01"]["u02"]
    assert edge["weight"] == 0.92
    assert edge["relationship"] == "follows"
    assert edge["touchpoint"] == "organic_feed"
    assert edge["frequency_per_week"] == 5
    assert edge["recency_days"] == 1
    assert edge["community_bridge"] is False
    assert dataset.profiles["u01"].interest_tags == ["skincare", "eco", "sustainability"]
    extra = dataset.profiles["u01"].model_extra
    assert extra is not None
    assert extra["community"] == "eco_beauty"
    assert extra["segment"] == "koc_seed"
    assert extra["follower_count"] == "18500"

    report = dataset.validation_report.to_dict()
    assert report["dataset_used"] is True
    assert report["available_edge_columns"] == [
        "source",
        "target",
        "influence_weight",
        "relationship",
        "touchpoint",
        "frequency_per_week",
        "recency_days",
        "community_bridge",
    ]
    assert report["covered_seed_user_ids"] == ["u01", "u11", "u19", "u29"]
    assert report["missing_seed_user_ids"] == []
    assert set(report["preserved_profile_attribute_columns"]) >= {
        "community",
        "segment",
        "follower_count",
        "locale",
        "lifecycle_stage",
    }
