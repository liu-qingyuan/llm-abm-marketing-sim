from __future__ import annotations

from pathlib import Path

from llm_abm_sim.graph_loader import load_network_dataset
from llm_abm_sim.schemas import DatasetConfig, ExtraProfilePolicy, MissingProfilePolicy, ProfileFormat


def test_tikhub_processed_files_roundtrip_through_existing_loader(tmp_path: Path) -> None:
    edges = tmp_path / "edges.csv"
    edges.write_text(
        "source,target,weight,comment_count,reply_count,mention_count,first_interaction_time,last_interaction_time\n"
        "u1,creator1,1,1,0,0,2025-06-01T00:00:00,2025-06-01T00:00:00\n"
        "u2,u1,1,0,1,0,2025-06-01T00:01:00,2025-06-01T00:01:00\n"
        "u1,u2,1,0,0,1,2025-06-01T00:02:00,2025-06-01T00:02:00\n",
        encoding="utf-8",
    )
    profiles = tmp_path / "profiles.csv"
    profiles.write_text(
        "user_id,user_type,follower_count,value_proposition,interest_tags,activity_score,activity_video_score,activity_comment_score,activity_reply_score,global_influence_score,local_influence_score,local_network_score,local_recognition_score,profile_index_method,profile_index_variant,brand_attitude,like_tendency,comment_tendency,share_tendency\n"
        "u1,commenter,10,green_quality,锦江酒店|绿色入住,0.7,0.2,0.8,0.6,0.2,0.5,0.4,0.6,log1p_p95_reference_weighted_v2,base,0.0,0.5,0.2,0.2\n"
        "u2,replier,20,comfort,绿色酒店,0.5,0.1,0.3,0.8,0.3,0.3,0.2,0.45,log1p_p95_reference_weighted_v2,base,0.0,0.5,0.2,0.2\n"
        "creator1,creator,1000,brand_official,酒店|锦江酒店,0.9,1.0,0.4,0.2,1.0,0.6,0.7,0.45,log1p_p95_reference_weighted_v2,base,0.0,0.5,0.2,0.2\n",
        encoding="utf-8",
    )
    dataset = load_network_dataset(
        DatasetConfig(
            edge_list_path=edges,
            profile_path=profiles,
            profile_format=ProfileFormat.CSV,
            directed=True,
            source_column="source",
            target_column="target",
            edge_weight_column="weight",
            edge_attribute_columns=[
                "comment_count",
                "reply_count",
                "mention_count",
                "first_interaction_time",
                "last_interaction_time",
            ],
            missing_profile_policy=MissingProfilePolicy.ERROR,
            extra_profile_policy=ExtraProfilePolicy.ERROR,
        )
    )
    assert dataset.graph.is_directed()
    assert dataset.graph["u1"]["creator1"]["weight"] == 1
    assert dataset.graph["u1"]["u2"]["mention_count"] == 1
    assert dataset.profiles["u1"].interest_tags == ["锦江酒店", "绿色入住"]
    extras = dataset.profiles["u1"].model_extra or {}
    assert extras["brand_attitude"] == "0.0"
    assert dataset.profiles["u1"].activity_score == 0.7
    assert extras["like_tendency"] == "0.5"
    assert extras["comment_tendency"] == "0.2"
    assert extras["share_tendency"] == "0.2"
    assert extras["value_proposition"] == "green_quality"
    assert extras["global_influence_score"] == "0.2"
    assert extras["local_influence_score"] == "0.5"
    assert extras["profile_index_method"] == "log1p_p95_reference_weighted_v2"
    assert extras["user_type"] == "commenter"
    assert "observed_activity_level" not in extras
    assert "observed_influence" not in extras
    assert "activity_level" not in extras
