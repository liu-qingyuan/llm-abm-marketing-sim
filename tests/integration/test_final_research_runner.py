from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from llm_abm_sim import FinalResearchConfig, FinalResearchRunner
from llm_abm_sim.decision import EngageDecision, LLMDecisionAdapter
from llm_abm_sim.safe_serialization import artifact_has_forbidden_terms
from llm_abm_sim.schemas import PeerContext, PlatformContext, PostContent, UserProfile

TARGET_VIDEO_ID = "7328592728139353363"
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


class FailingIfCalledAdapter(LLMDecisionAdapter):
    def __init__(self) -> None:
        self.calls = 0

    def decide(
        self,
        post: PostContent,
        profile: UserProfile,
        peer_context: PeerContext,
        platform_context: PlatformContext | None = None,
        time_step: int = 0,
    ) -> EngageDecision:
        self.calls += 1
        raise AssertionError("offline baseline must not call decision_adapter")


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _latent_row(user_number: int) -> dict[str, object]:
    return {
        "latent_attribute_spec_id": "fixture-latent-v1",
        "latent_attribute_method": "fixture-exact-quota",
        "latent_attribute_seed": 7,
        "latent_class": f"class_{(user_number % 3) + 1}",
        "latent_environmental_consciousness_coef": 1.0,
        "latent_epistemic_value_weight": 0.1,
        "latent_environmental_value_weight": 0.2,
        "latent_functional_value_weight": 0.3,
        "latent_health_value_weight": 0.4,
        "latent_emotional_value_weight": 0.5,
        "latent_social_value_weight": 0.6,
        "latent_hotel_class": "midscale",
        "latent_travel_purpose": "leisure",
        "latent_gender": "female",
        "latent_age": "age_26_35",
        "latent_education": "bachelor",
        "latent_monthly_income": "income_8001_15000",
    }


def _make_processed_fixture(tmp_path: Path) -> Path:
    dataset_dir = tmp_path / "processed" / "latent-v1"
    _write_csv(
        dataset_dir / "videos.csv",
        [
            "video_id",
            "source_challenge_name",
            "source_challenge_rank",
            "video_url",
            "caption",
            "hashtags",
            "creator_user_id",
            "like_count",
            "comment_count",
            "share_count",
            "collect_count",
        ],
        [
            {
                "video_id": TARGET_VIDEO_ID,
                "source_challenge_name": "锦江酒店",
                "source_challenge_rank": 3,
                "video_url": "https://example.test/target?token=secret-token&cookie=secret-cookie",
                "caption": "当高端酒店开始限塑",
                "hashtags": '["锦江ESG", "乡村振兴"]',
                "creator_user_id": "creator-target",
                "like_count": 999,
                "comment_count": 2,
                "share_count": 999,
                "collect_count": 999,
            },
            {
                "video_id": "history-jinjiang",
                "source_challenge_name": "锦江酒店",
                "source_challenge_rank": 3,
                "caption": "绿色酒店历史内容",
                "hashtags": '["锦江ESG"]',
                "creator_user_id": "creator-history",
            },
            {
                "video_id": "history-scope-a",
                "source_challenge_name": "锦江都城酒店",
                "source_challenge_rank": 1,
                "caption": "都城历史内容",
                "hashtags": "[]",
                "creator_user_id": "creator-scope-a",
            },
            {
                "video_id": "history-scope-b",
                "source_challenge_name": "锦江之星",
                "source_challenge_rank": 4,
                "caption": "锦江之星历史内容",
                "hashtags": '["乡村振兴"]',
                "creator_user_id": "creator-scope-b",
            },
        ],
    )
    _write_csv(
        dataset_dir / "all_comments.csv",
        [
            "comment_id",
            "video_id",
            "parent_comment_id",
            "commenter_user_id",
            "mentioned_user_ids",
            "like_count",
            "comment_level",
        ],
        [
            {
                "comment_id": "h1",
                "video_id": "history-jinjiang",
                "parent_comment_id": "0",
                "commenter_user_id": "u1",
                "mentioned_user_ids": "[]",
                "like_count": 4,
                "comment_level": "comment",
            },
            {
                "comment_id": "h2",
                "video_id": "history-jinjiang",
                "parent_comment_id": "h1",
                "commenter_user_id": "u2",
                "mentioned_user_ids": '["u3"]',
                "like_count": 2,
                "comment_level": "reply",
            },
            {
                "comment_id": "h3",
                "video_id": "history-scope-a",
                "parent_comment_id": "0",
                "commenter_user_id": "u3",
                "mentioned_user_ids": "[]",
                "like_count": 1,
                "comment_level": "comment",
            },
            {
                "comment_id": "h4",
                "video_id": "history-scope-b",
                "parent_comment_id": "0",
                "commenter_user_id": "u4",
                "mentioned_user_ids": "[]",
                "like_count": 0,
                "comment_level": "comment",
            },
            {
                "comment_id": "t1",
                "video_id": TARGET_VIDEO_ID,
                "parent_comment_id": "0",
                "commenter_user_id": "u1",
                "mentioned_user_ids": "[]",
                "like_count": 500,
                "comment_level": "comment",
            },
            {
                "comment_id": "t2",
                "video_id": TARGET_VIDEO_ID,
                "parent_comment_id": "t1",
                "commenter_user_id": "u5",
                "mentioned_user_ids": "[]",
                "like_count": 500,
                "comment_level": "reply",
            },
        ],
    )
    user_fields = [
        "user_id",
        "nickname",
        "bio",
        "signature",
        "follower_count",
        "following_count",
        "video_count",
        "global_influence_score",
        "brand_attitude",
        "like_tendency",
        "comment_tendency",
        "share_tendency",
        "authorization",
        "cookie",
        "raw_prompt",
        "raw_provider_response",
        "credential_path",
        *LATENT_COLUMNS,
    ]
    user_rows = []
    for number, user_id in enumerate(["u1", "u2", "u3", "u4", "u5", "u6"], start=1):
        user_rows.append(
            {
                "user_id": user_id,
                "nickname": f"User {number}",
                "bio": "Bearer sk-secret" if number == 3 else f"Bio {number}",
                "signature": f"Signature {number}",
                "follower_count": number * 10,
                "following_count": number,
                "video_count": number,
                "global_influence_score": number / 10,
                "brand_attitude": 1,
                "like_tendency": 1,
                "comment_tendency": 1,
                "share_tendency": 1,
                "authorization": "Bearer sk-secret",
                "cookie": "secret-cookie",
                "raw_prompt": "secret prompt",
                "raw_provider_response": '{"token":"sk-secret"}',
                "credential_path": "/Users/example/.codex/auth.json",
                **_latent_row(number),
            }
        )
    _write_csv(dataset_dir / "users.csv", user_fields, user_rows)
    return dataset_dir


def test_offline_final_research_baseline_is_holdout_safe_and_deterministic(tmp_path: Path) -> None:
    dataset_dir = _make_processed_fixture(tmp_path)
    source_hashes = {path.name: _sha256(path) for path in dataset_dir.iterdir() if path.is_file()}
    adapter = FailingIfCalledAdapter()
    config = FinalResearchConfig(
        dataset_dir=dataset_dir,
        sample_size=4,
        random_seed=20260713,
    )

    first_output = FinalResearchRunner(config, adapter).run_and_write(tmp_path / "run-a")
    second_output = FinalResearchRunner(config, adapter).run_and_write(tmp_path / "run-b")

    assert first_output == tmp_path / "run-a"
    assert adapter.calls == 0
    manifest = json.loads((first_output / "artifact_manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifacts"] == {
        "config_snapshot": "config_snapshot.json",
        "holdout_diagnostic": "top20_holdout_diagnostic.json",
        "holdout_safe_audit": "holdout_safe_audit.json",
        "offline_score_summary": "offline_score_summary.json",
        "offline_scores": "offline_scores.csv",
        "sample_manifest_csv": "sample_manifest.csv",
        "sample_manifest_json": "sample_manifest.json",
        "target_video_snapshot": "target_video_snapshot.json",
    }

    target = json.loads((first_output / "target_video_snapshot.json").read_text(encoding="utf-8"))
    assert target["video_id"] == TARGET_VIDEO_ID
    assert target["video_url"] == "https://example.test/target"
    assert "comment_count" not in target
    assert "like_count" not in target

    audit = json.loads((first_output / "holdout_safe_audit.json").read_text(encoding="utf-8"))
    assert audit["historical_video_count"] == 3
    assert audit["holdout_interaction_rows"] == 2
    assert audit["holdout_unique_participant_count"] == 2
    assert audit["source_dataset_modified"] is False

    sample_rows = _read_csv(first_output / "sample_manifest.csv")
    assert len(sample_rows) == 4
    assert [row["user_id"] for row in sample_rows] == ["u3", "u1", "u2", "u4"]
    assert [row["is_seed"] for row in sample_rows] == ["true", "true", "true", "true"]
    assert audit["global_top10_local_top10_seed_union"] == ["u1", "u2", "u3", "u4"]
    assert all(
        field not in sample_rows[0]
        for field in ("brand_attitude", "like_tendency", "comment_tendency", "share_tendency")
    )

    score_rows = {row["user_id"]: row for row in _read_csv(first_output / "offline_scores.csv")}
    assert len(score_rows) == 6
    assert float(score_rows["u1"]["historical_tag_affinity"]) == 0.5
    assert float(score_rows["u1"]["base_network_score"]) == 1.0
    assert float(score_rows["u1"]["recommendation_score"]) == 0.85
    assert score_rows["u5"]["has_non_target_history"] == "false"
    assert float(score_rows["u5"]["recommendation_score"]) == 0.0
    assert score_rows["u3"]["has_non_target_history"] == "true"
    assert score_rows["u3"]["has_historical_tag_affinity"] == "false"

    diagnostic = json.loads((first_output / "top20_holdout_diagnostic.json").read_text(encoding="utf-8"))
    assert diagnostic["observed_holdout_participant_ids"] == ["u1", "u5"]
    assert diagnostic["intersection_count"] == 2
    assert diagnostic["intersection_user_ids"] == ["u1", "u5"]
    assert diagnostic["unobserved_pair_semantics"] == (
        "No observed interaction is not evidence that a user saw the target video and chose ignore."
    )

    assert source_hashes == {path.name: _sha256(path) for path in dataset_dir.iterdir() if path.is_file()}
    artifact_text = "\n".join(path.read_text(encoding="utf-8") for path in first_output.iterdir() if path.is_file())
    assert artifact_has_forbidden_terms(artifact_text) is False
    assert "secret-token" not in artifact_text
    assert "secret-cookie" not in artifact_text
    assert "credential_path" not in artifact_text
    assert "User 1" in artifact_text
    assert "Bio 1" in artifact_text
    assert "Signature 1" in artifact_text
    assert "<redacted>" in artifact_text
    for relative_path in manifest["artifacts"].values():
        assert (first_output / relative_path).read_bytes() == (second_output / relative_path).read_bytes()


def test_final_research_config_rejects_missing_target_and_oversized_sample(tmp_path: Path) -> None:
    dataset_dir = _make_processed_fixture(tmp_path)
    rows = list(csv.DictReader((dataset_dir / "videos.csv").open(encoding="utf-8", newline="")))
    _write_csv(dataset_dir / "videos.csv", list(rows[0]), [row for row in rows if row["video_id"] != TARGET_VIDEO_ID])

    with pytest.raises(ValidationError, match="target video"):
        FinalResearchConfig(dataset_dir=dataset_dir, sample_size=4)

    dataset_dir = _make_processed_fixture(tmp_path / "fresh")
    with pytest.raises(ValidationError, match="sample_size"):
        FinalResearchConfig(dataset_dir=dataset_dir, sample_size=7)

    with pytest.raises(ValidationError, match="must sum to 1.0"):
        FinalResearchConfig(dataset_dir=dataset_dir, sample_size=4, network_weight=0.8, tag_affinity_weight=0.3)
