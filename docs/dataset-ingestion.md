# Dataset and Profile Ingestion

Dataset-backed runs let a simulation load its social graph from an edge-list file and user preferences from a profile CSV or JSON file. The default inline `profiles` and `graph_edges` config still works for small offline examples; use the `dataset` block when you want reproducible fixture or real-dataset ingestion.

## Minimal dataset config

```yaml
run_id: toy-dataset
random_seed: 123
simulation:
  horizon: 4
  seed_user_ids: [u1]
post:
  post_id: fixture-post
  text: "Eco skincare launch"
  topic_tags: [skincare, eco]
dataset:
  edge_list_path: ../../tests/fixtures/datasets/toy_edges.csv
  profile_path: ../../tests/fixtures/datasets/toy_profiles.csv
  profile_format: csv
  delimiter: ","
  directed: true
  source_column: source
  target_column: target
  edge_weight_column: influence_weight
  edge_attribute_columns: [relationship, touchpoint]
  missing_profile_policy: error
  extra_profile_policy: error
```

Working fixture files:

- Config: `configs/fixtures/toy_dataset.yaml`
- Edges: `tests/fixtures/datasets/toy_edges.csv`
- CSV profiles: `tests/fixtures/datasets/toy_profiles.csv`
- JSON profiles: `tests/fixtures/datasets/toy_profiles.json`

Run it offline with:

```bash
python -m llm_abm_sim.run --config configs/fixtures/toy_dataset.yaml --output runs/toy-dataset
```

Dataset-backed output folders include the normal run artifacts plus `dataset_validation.json`.

## Path resolution rules

`ExperimentRunner.from_config_file()` and `load_simulation_input()` resolve these fields relative to the directory containing the config file:

- `dataset.edge_list_path`
- `dataset.profile_path`

For example, in `configs/fixtures/toy_dataset.yaml`, `../../tests/fixtures/datasets/toy_edges.csv` resolves from `configs/fixtures/`, not from the shell's current working directory.

Absolute paths are normalized with `Path.resolve()` and stay absolute in the loaded config and in `dataset_validation.json`. Direct `SimulationInput.model_validate(...)` calls intentionally do not resolve paths, so schema validation remains side-effect free when no source config path is known.

## Edge-list schema

Two edge-list styles are supported.

### Header/column-based CSV or TSV

Use `source_column` and `target_column` together when the file has a header row:

```csv
source,target,influence_weight,relationship,touchpoint
u1,u2,0.90,follows,organic
u1,u3,0.60,follows,organic
```

Optional fields:

- `delimiter`: explicit CSV delimiter; if omitted, `.tsv` files use tab and other files use comma for column-based loading.
- `directed`: `true` builds a `networkx.DiGraph`; `false` builds an undirected `networkx.Graph`.
- `edge_weight_column`: copied to the NetworkX edge attribute named `weight` after scalar parsing.
- `edge_attribute_columns`: copied as named edge attributes after scalar parsing.

`source_column` and `target_column` must be provided as a pair. If either required cell is blank, loading fails with a validation error.

### Positional edge list

When `source_column` and `target_column` are omitted, each non-empty non-comment row must contain at least two values. With no delimiter, values are split on whitespace:

```text
u1 u2
u1 u3
# comments are ignored
```

With an explicit delimiter, rows are parsed as delimited records and the first two non-empty values become the edge endpoints.

## Profile schema

Profiles are validated as `UserProfile` records. Required field:

- `user_id`

Supported preference fields:

- `interest_tags`
- `brand_attitude` from `-1.0` to `1.0`
- `activity_level` from `0.0` to `1.0`
- `like_tendency` from `0.0` to `1.0`
- `comment_tendency` from `0.0` to `1.0`
- `share_tendency` from `0.0` to `1.0`

### CSV profiles

```csv
user_id,interest_tags,brand_attitude,activity_level,like_tendency,comment_tendency,share_tendency
u1,skincare|eco,0.8,0.9,0.8,0.3,0.6
u2,skincare|wellness,0.5,0.8,0.7,0.2,0.4
```

`interest_tags` may use JSON list syntax or a simple `|`, `;`, or `,` separated string. Blank cells are ignored so Pydantic defaults apply.

### JSON profiles

Both a top-level list and an object with a `profiles` list are accepted:

```json
{
  "profiles": [
    {
      "user_id": "u1",
      "interest_tags": ["skincare", "eco"],
      "brand_attitude": 0.8,
      "activity_level": 0.9,
      "like_tendency": 0.8,
      "comment_tendency": 0.3,
      "share_tendency": 0.6
    }
  ]
}
```

Duplicate `user_id` values fail validation.

## Graph/profile validation policies

Dataset loading compares graph node IDs with profile `user_id` values.

`missing_profile_policy` handles graph nodes without profile rows:

- `default`: create `UserProfile(user_id=<node id>)` with default preferences.
- `error`: fail the run.

`extra_profile_policy` handles profile rows whose `user_id` is absent from the graph:

- `ignore`: remove extra profile rows from the simulation.
- `include_as_node`: add each extra profile ID as an isolated graph node.
- `error`: fail the run.

The validation report records the raw mismatch sets and the applied action lists: `missing_profile_ids`, `default_profile_ids`, `extra_profile_ids`, `included_extra_profile_ids`, and `ignored_extra_profile_ids`.

## `dataset_validation.json`

For dataset-backed runs, `write_run_outputs()` writes `dataset_validation.json` next to `config.json`, `run_result.json`, `events.json`, `metrics_summary.json`, `step_records.csv`, and `report.html`.

The validation file is JSON-serializable and includes:

- resolved `edge_list_path` and `profile_path`;
- inferred or configured `profile_format`;
- `directed` graph mode;
- graph/profile counts;
- missing/extra profile diagnostics;
- validation policy names;
- edge weight and attribute column names;
- `errors`, which is empty for successful runs.

This artifact is intentionally metadata-only. It should not contain API keys, provider credentials, cookies, or raw secret-bearing records.
