from pathlib import Path

from llm_abm_sim.runner import load_simulation_input
from llm_abm_sim.schemas import ExtraProfilePolicy, MissingProfilePolicy, ProfileFormat, SimulationInput


def test_dataset_config_resolves_relative_paths_against_config_directory(tmp_path):
    config_dir = tmp_path / "configs" / "fixtures"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "toy_dataset.yaml"
    config_path.write_text(
        """
run_id: dataset-path-test
simulation:
  horizon: 1
dataset:
  edge_list_path: ../../tests/fixtures/datasets/toy_edges.csv
  profile_path: ../../tests/fixtures/datasets/toy_profiles.json
  profile_format: json
  directed: true
  source_column: source
  target_column: target
  edge_weight_column: influence_weight
  edge_attribute_columns: [relationship]
  missing_profile_policy: error
  extra_profile_policy: include_as_node
""",
        encoding="utf-8",
    )

    loaded = load_simulation_input(config_path)

    assert loaded.dataset.edge_list_path == (config_dir / "../../tests/fixtures/datasets/toy_edges.csv").resolve()
    assert loaded.dataset.profile_path == (config_dir / "../../tests/fixtures/datasets/toy_profiles.json").resolve()
    assert loaded.dataset.profile_format is ProfileFormat.JSON
    assert loaded.dataset.directed is True
    assert loaded.dataset.source_column == "source"
    assert loaded.dataset.target_column == "target"
    assert loaded.dataset.edge_weight_column == "influence_weight"
    assert loaded.dataset.edge_attribute_columns == ["relationship"]
    assert loaded.dataset.missing_profile_policy is MissingProfilePolicy.ERROR
    assert loaded.dataset.extra_profile_policy is ExtraProfilePolicy.INCLUDE_AS_NODE
    assert loaded.dataset.uses_files is True


def test_dataset_config_normalizes_absolute_paths(tmp_path):
    profile_path = tmp_path / "profiles.json"
    config_path = tmp_path / "absolute.yaml"
    config_path.write_text(
        f"""
run_id: absolute-path-test
dataset:
  edge_list_path: {profile_path.parent / ".." / profile_path.parent.name / "edges.csv"}
  profile_path: {profile_path}
  profile_format: json
""",
        encoding="utf-8",
    )

    loaded = load_simulation_input(config_path)

    assert (
        loaded.dataset.edge_list_path == (profile_path.parent / ".." / profile_path.parent.name / "edges.csv").resolve()
    )
    assert loaded.dataset.profile_path == profile_path.resolve()


def test_direct_model_validation_keeps_unresolved_paths_side_effect_free():
    config = SimulationInput.model_validate(
        {
            "dataset": {
                "edge_list_path": "data/edges.csv",
                "profile_path": "data/profiles.csv",
                "profile_format": "csv",
            }
        }
    )

    assert config.dataset.edge_list_path == Path("data/edges.csv")
    assert config.dataset.profile_path == Path("data/profiles.csv")
    assert config.dataset.profile_format is ProfileFormat.CSV
