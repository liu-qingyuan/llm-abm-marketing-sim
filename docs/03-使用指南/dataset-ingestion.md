# 数据集与用户画像导入

数据集驱动运行可以从边列表文件加载社交图，从 CSV/JSON 用户画像文件加载用户偏好。小型离线样例仍可使用配置里的内联 `profiles` 和 `graph_edges`；当你需要可复现 fixture 或真实数据导入时，使用 `dataset` 配置块。

## 最小数据集配置

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

可用 fixture：

- 配置：`configs/fixtures/toy_dataset.yaml`
- 边文件：`tests/fixtures/datasets/toy_edges.csv`
- CSV 画像：`tests/fixtures/datasets/toy_profiles.csv`
- JSON 画像：`tests/fixtures/datasets/toy_profiles.json`

离线运行：

```bash
python -m llm_abm_sim.run --config configs/fixtures/toy_dataset.yaml --output runs/toy-dataset
```

数据集驱动输出目录除了常规产物，还会包含 `dataset_validation.json`。

## 路径解析规则

`ExperimentRunner.from_config_file()` 和 `load_simulation_input()` 会把以下字段按“配置文件所在目录”解析：

- `dataset.edge_list_path`
- `dataset.profile_path`

例如 `configs/fixtures/toy_dataset.yaml` 中的 `../../tests/fixtures/datasets/toy_edges.csv` 是从 `configs/fixtures/` 解析，不是从当前 shell 工作目录解析。

绝对路径会通过 `Path.resolve()` 规范化，并在 loaded config 与 `dataset_validation.json` 中保持绝对路径。直接调用 `SimulationInput.model_validate(...)` 时不会解析路径，以保证 schema 校验本身没有文件系统副作用。

## 真实社交网络 ABM 数据合约

“真实 ABM 数据”指可以替代小 fixture 的本地社交网络数据集，不需要修改仿真器代码。原始/私密导出应放在被 git 忽略的 `data/raw/` 或 `data/processed/`，然后用本地 config 的 `dataset` block 引用清洗后的文件。仓库只提交小型合成或匿名样例。

生产形态输入包含：

| 输入 | 必需形态 | 说明 |
|---|---|---|
| 边列表 | `source`、`target` 列 | 关注/好友/影响关系；不对称 feed 建议 `directed: true`。 |
| 边权重 | 可选数值列，如 `influence_weight` | 复制到 NetworkX edge attribute `weight`，作为后续阶段可用图元数据。 |
| 关系属性 | `edge_attribute_columns` 中列出的可选列 | 例：`relationship`、`touchpoint`、`frequency_per_week`、`recency_days`、`community_bridge`。 |
| 用户画像 | 每个 `user_id` 一行 | 必需决策字段会被校验；额外公开列保留在 `UserProfile.model_extra`。 |
| 用户属性 | 可选非秘密列 | 例：`community`、`segment`、`follower_count`、`locale`、`lifecycle_stage`。不要在可提交 fixture 中包含姓名、邮箱、handle、token、私密备注。 |
| 种子用户 | `simulation.seed_user_ids` | 必须存在于图中；`dataset_validation.json` 会报告覆盖和缺失 seed ID。 |
| 平台上下文 | `platform_context` block | 热话题、feed 排名权重、痕迹可见性、平台氛围。 |
| 营销帖子 | `post` block | 文本、素材摘要、话题标签，供规则或 Provider-backed adapter 使用。 |
| 时间设置 | `simulation.horizon`、`time_step_label`、`observation_window` | 保留多轮扩散记录。 |

加载器会在 `dataset_validation.json` 中报告：源文件名、图方向性、图/画像数量、画像覆盖缺口、额外画像 ID、边权重列、保留边属性列、可用边列、保留额外画像列、seed 覆盖、errors。该报告只含元数据，不应包含秘密或原始私密记录。

## 真实感营销 fixture

仓库包含一个可提交的真实感样例，用于集成和 E2E 覆盖：

- 配置：`configs/fixtures/realistic_marketing_dataset.yaml`
- 边：`tests/fixtures/datasets/realistic_marketing_edges.csv`
- 画像：`tests/fixtures/datasets/realistic_marketing_profiles.csv`

它包含 36 个用户、45 条有向加权关系、四个社群、种子 KOC 用户、兴趣、品牌态度/活跃度/互动倾向，以及关系/触点属性。运行：

```bash
python -m llm_abm_sim.run --config configs/fixtures/realistic_marketing_dataset.yaml --output runs/realistic-marketing-dataset
```

预期产物包括 `config.json`、`dataset_validation.json`、`run_result.json`、`events.json`、`metrics_summary.json`、`step_records.csv` 和 `report.html`。

## 边列表 schema

支持两种边列表风格。

### 带表头的 CSV 或 TSV

文件有表头时，同时配置 `source_column` 和 `target_column`：

```csv
source,target,influence_weight,relationship,touchpoint
u1,u2,0.90,follows,organic
u1,u3,0.60,follows,organic
```

可选字段：

- `delimiter`：显式 CSV 分隔符；省略时 `.tsv` 使用 tab，其他列式文件使用逗号。
- `directed`：`true` 构建 `networkx.DiGraph`；`false` 构建无向 `networkx.Graph`。
- `edge_weight_column`：解析为标量后复制到 NetworkX edge attribute `weight`。
- `edge_attribute_columns`：解析为标量后按原列名复制为边属性。

`source_column` 和 `target_column` 必须成对提供。任一必需单元格为空时，加载会因校验错误失败。

### 位置式边列表

省略 `source_column` 和 `target_column` 时，每个非空、非注释行至少包含两个值。没有显式分隔符时按空白分割：

```text
u1 u2
u1 u3
# comments are ignored
```

设置显式分隔符时，按分隔记录解析，前两个非空值作为边端点。

## 用户画像 schema

用户画像会被校验为 `UserProfile`。必需字段：

- `user_id`

核心画像字段：

- `interest_tags`
- `activity_score`，范围 `0.0` 到 `1.0`

历史 demo 中的 `brand_attitude`、`like_tendency`、`comment_tendency`、`share_tendency` 不再是正式决策合同字段。旧数据中如仍存在这些列，会作为额外非秘密属性保留用于兼容加载，但默认决策和 provider prompt 不读取这些字段。

### CSV 用户画像

```csv
user_id,interest_tags,activity_score
u1,skincare|eco,0.9
u2,skincare|wellness,0.8
```

`interest_tags` 可以使用 JSON list，也可以使用 `|`、`;` 或 `,` 分隔的简单字符串。空单元格会被忽略，由 Pydantic 默认值生效。

### JSON 用户画像

接受顶层 list，也接受带 `profiles` list 的对象：

```json
{
  "profiles": [
    {
      "user_id": "u1",
      "interest_tags": ["skincare", "eco"],
      "activity_score": 0.9
    }
  ]
}
```

重复 `user_id` 会导致校验失败。额外非秘密列会被保留，用于真实数据诊断和未来特征；当前确定性决策只使用已校验的画像字段。

## 图/画像校验策略

数据集加载会比较图节点 ID 和 profile `user_id`。

`missing_profile_policy` 处理图中有节点但没有画像的情况：

- `default`：创建 `UserProfile(user_id=<node id>)`，使用默认偏好。
- `error`：运行失败。

`extra_profile_policy` 处理画像中有 `user_id` 但图中没有节点的情况：

- `ignore`：从仿真中移除额外画像。
- `include_as_node`：把额外画像 ID 添加为孤立节点。
- `error`：运行失败。

校验报告会记录 mismatch 集合和策略结果：`missing_profile_ids`、`default_profile_ids`、`extra_profile_ids`、`included_extra_profile_ids`、`ignored_extra_profile_ids`。

## `dataset_validation.json`

数据集驱动运行时，`write_run_outputs()` 会把 `dataset_validation.json` 写在 `config.json`、`run_result.json`、`events.json`、`metrics_summary.json`、`step_records.csv`、`report.html` 旁边。

该文件可 JSON 序列化，包含：

- 解析后的 `edge_list_path` 和 `profile_path`；
- 推断或配置的 `profile_format`；
- `directed` 图模式；
- 图/画像计数；
- missing/extra profile 诊断；
- 校验策略名；
- 边权重列和属性列名；
- 可用边文件列；
- 保留的额外 profile 属性列；
- seed user IDs、covered seed IDs、missing seed IDs；
- `errors`，成功运行时为空。

该产物应只包含元数据，不得包含 API key、Provider credentials、cookies 或 raw secret-bearing records。
