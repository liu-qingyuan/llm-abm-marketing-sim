from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest

from llm_abm_sim import ConcurrentMessageExperimentConfig, ConcurrentMessageExperimentRunner
from llm_abm_sim.concurrent_message_experiment import authoritative_message_definitions
from llm_abm_sim.decision import EngageDecision, LLMDecisionAdapter, ProviderDecisionError
from llm_abm_sim.final_research import TARGET_VIDEO_ID
from llm_abm_sim.schemas import PeerContext, PlatformContext, PostContent, UserProfile

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


class _ScriptedConcurrentAdapter(LLMDecisionAdapter):
    def __init__(
        self,
        *,
        name: str,
        positive_user_ids: set[str],
        fail_pairs: set[tuple[int, str, str]],
    ) -> None:
        self.name = name
        self.positive_user_ids = positive_user_ids
        self.fail_pairs = fail_pairs
        self.safe_metadata = {"adapter": name}
        self.calls: list[dict[str, object]] = []

    def decide(
        self,
        post: PostContent,
        profile: UserProfile,
        peer_context: PeerContext,
        platform_context: PlatformContext | None = None,
        time_step: int = 0,
    ) -> EngageDecision:
        self.calls.append(
            {
                "time_step": time_step,
                "message_id": post.post_id,
                "user_id": profile.user_id,
                "peer_context": peer_context,
                "platform_context": platform_context,
            }
        )
        if (time_step, post.post_id, profile.user_id) in self.fail_pairs:
            raise ProviderDecisionError(TimeoutError(self.name))
        if time_step == 0 and profile.user_id in self.positive_user_ids:
            return EngageDecision(
                engage=True,
                probability=0.92,
                reason=f"{self.name} positive",
                confidence=0.88,
                action="like",
                decision_source=f"{self.name}_deterministic",
                provider_metadata={"adapter": self.name, "user_id": profile.user_id},
            )
        return EngageDecision(
            engage=False,
            probability=0.08,
            reason=f"{self.name} ignore",
            confidence=0.88,
            action="ignore",
            decision_source=f"{self.name}_deterministic",
            provider_metadata={"adapter": self.name, "user_id": profile.user_id},
        )


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _latent_row(latent_class: str) -> dict[str, object]:
    weights_by_class = {
        "class_1": {
            "epistemic": 0.0,
            "environmental": 2.0,
            "functional": 0.0,
            "health": 2.0,
            "emotional": 0.0,
            "social": 2.0,
        },
        "class_2": {
            "epistemic": 0.0,
            "environmental": 1.0,
            "functional": 2.0,
            "health": 2.0,
            "emotional": 0.0,
            "social": 0.0,
        },
        "class_3": {
            "epistemic": 2.0,
            "environmental": 1.0,
            "functional": 0.0,
            "health": 1.0,
            "emotional": 0.0,
            "social": 0.0,
        },
    }
    weights = weights_by_class[latent_class]
    return {
        "latent_attribute_spec_id": "fixture-latent-v1",
        "latent_attribute_method": "fixture-exact-quota",
        "latent_attribute_seed": 7,
        "latent_class": latent_class,
        "latent_environmental_consciousness_coef": 1.0,
        "latent_epistemic_value_weight": weights["epistemic"],
        "latent_environmental_value_weight": weights["environmental"],
        "latent_functional_value_weight": weights["functional"],
        "latent_health_value_weight": weights["health"],
        "latent_emotional_value_weight": weights["emotional"],
        "latent_social_value_weight": weights["social"],
        "latent_hotel_class": "midscale",
        "latent_travel_purpose": "leisure",
        "latent_gender": "female",
        "latent_age": "age_26_35",
        "latent_education": "bachelor",
        "latent_monthly_income": "income_8001_15000",
    }


def _latent_class_for_user(user_number: int) -> str:
    if user_number <= 16:
        return "class_1"
    if user_number <= 22:
        return "class_2"
    return "class_3"


def _make_concurrent_fixture(tmp_path: Path, *, user_count: int = 30) -> Path:
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
                "video_url": "https://example.test/holdout",
                "caption": "holdout target",
                "hashtags": "[]",
                "creator_user_id": "creator-target",
                "like_count": 0,
                "comment_count": 0,
                "share_count": 0,
                "collect_count": 0,
            },
            {
                "video_id": "history-jinjiang",
                "source_challenge_name": "锦江酒店",
                "source_challenge_rank": 3,
                "video_url": "https://example.test/history",
                "caption": "history jinjiang",
                "hashtags": "[]",
                "creator_user_id": "creator-history",
                "like_count": 0,
                "comment_count": 0,
                "share_count": 0,
                "collect_count": 0,
            },
        ],
    )
    history_rows = [
        {
            "comment_id": f"seed-{number}",
            "video_id": "history-jinjiang",
            "parent_comment_id": "0",
            "commenter_user_id": f"u{number}",
            "mentioned_user_ids": "[]",
            "like_count": 100,
            "comment_level": "comment",
        }
        for number in range(1, 11)
    ]
    history_rows.append(
        {
            "comment_id": "candidate-u11",
            "video_id": "history-jinjiang",
            "parent_comment_id": "0",
            "commenter_user_id": "u11",
            "mentioned_user_ids": json.dumps(["u1", "u2"]),
            "like_count": 0,
            "comment_level": "comment",
        }
    )
    history_rows.append(
        {
            "comment_id": "holdout-comment",
            "video_id": TARGET_VIDEO_ID,
            "parent_comment_id": "0",
            "commenter_user_id": "u1",
            "mentioned_user_ids": "[]",
            "like_count": 0,
            "comment_level": "comment",
        }
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
        history_rows,
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
        *LATENT_COLUMNS,
    ]
    user_rows: list[dict[str, object]] = []
    for number in range(1, user_count + 1):
        user_rows.append(
            {
                "user_id": f"u{number}",
                "nickname": f"User {number}",
                "bio": f"Bio {number}",
                "signature": f"Signature {number}",
                "follower_count": 1000 - number,
                "following_count": 100 + number,
                "video_count": 20 if number <= 10 else 1,
                "global_influence_score": 1000 - number if number <= 10 else float(100 - number),
                **_latent_row(_latent_class_for_user(number)),
            }
        )
    _write_csv(dataset_dir / "users.csv", user_fields, user_rows)
    return dataset_dir


def test_concurrent_message_runner_writes_validation_runtime_artifacts(tmp_path: Path) -> None:
    dataset_dir = _make_concurrent_fixture(tmp_path)
    primary_adapter = _ScriptedConcurrentAdapter(
        name="primary",
        positive_user_ids={"u1"},
        fail_pairs={(0, "message_3", "u4")},
    )
    shadow_adapter = _ScriptedConcurrentAdapter(
        name="shadow",
        positive_user_ids={"u2"},
        fail_pairs={(0, "message_2", "u3")},
    )
    config = ConcurrentMessageExperimentConfig(
        dataset_dir=dataset_dir,
        sample_size=30,
        horizon=2,
        delivery_capacity=10,
        configuration_profile="validation",
    )

    output_dir = ConcurrentMessageExperimentRunner(config, primary_adapter, shadow_adapter).run_and_write(
        tmp_path / "concurrent-run"
    )

    validation = json.loads((output_dir / "concurrent_validation.json").read_text(encoding="utf-8"))
    pair_rows = _read_csv(output_dir / "concurrent_runtime_pairs.csv")
    terminal_rows = _read_csv(output_dir / "concurrent_runtime_terminal_rows.csv")
    candidate_rows = _read_csv(output_dir / "concurrent_runtime_candidates.csv")
    step_rows = json.loads((output_dir / "concurrent_runtime_steps.json").read_text(encoding="utf-8"))
    report_html = (output_dir / "report.html").read_text(encoding="utf-8")

    assert validation["production_deploy_eligible"] is False
    assert validation["counts"]["actual_exposures"] == 60
    assert validation["counts"]["terminal_rows"] == 120
    assert validation["counts"]["primary_failures"] == 1
    assert validation["counts"]["shadow_failures"] == 1
    assert validation["per_message"]["message_1"]["exposures"] == 20
    assert validation["per_message"]["message_2"]["exposures"] == 20
    assert validation["per_message"]["message_3"]["exposures"] == 20
    assert "validation-only" in report_html
    assert "cannot be deployed" in report_html

    assert len(pair_rows) == 60
    assert len({row["pair_id"] for row in pair_rows}) == 60
    assert len(terminal_rows) == 120
    assert len({row["terminal_row_id"] for row in terminal_rows}) == 120
    assert len({(row["message_id"], row["user_id"]) for row in pair_rows}) == len(pair_rows)
    assert sum(row["primary_status"] == "provider_failed" for row in pair_rows) == 1
    assert sum(row["shadow_status"] == "provider_failed" for row in pair_rows) == 1

    first_batch_candidates = [row for row in candidate_rows if row["time_step"] == "0"]
    assert first_batch_candidates
    assert all(int(row["campaign_engaged_neighbor_count"]) == 0 for row in first_batch_candidates)

    assert step_rows[0]["deduplicated_committed_primary_positive_user_ids"] == ["u1"]
    assert [message["message_id"] for message in step_rows[0]["messages"]] == ["message_1", "message_2", "message_3"]

    second_batch_message_summaries = {message["message_id"]: message for message in step_rows[1]["messages"]}
    assert second_batch_message_summaries["message_1"]["selected_user_ids"] != second_batch_message_summaries["message_3"]["selected_user_ids"]
    assert "u23" in second_batch_message_summaries["message_3"]["selected_user_ids"]
    assert "u12" in second_batch_message_summaries["message_1"]["selected_user_ids"]

    u11_second_batch_rows = [
        row
        for row in candidate_rows
        if row["time_step"] == "1" and row["user_id"] == "u11"
    ]
    assert u11_second_batch_rows
    assert all(int(row["campaign_engaged_neighbor_count"]) == 1 for row in u11_second_batch_rows)

    u1_rows = [row for row in pair_rows if row["time_step"] == "0" and row["user_id"] == "u1"]
    assert len(u1_rows) == 3
    assert all(row["campaign_feedback_committed"] == "true" for row in u1_rows)

    u2_rows = [row for row in pair_rows if row["time_step"] == "0" and row["user_id"] == "u2"]
    assert len(u2_rows) == 3
    assert all(row["shadow_action"] == "like" for row in u2_rows)
    assert all(row["campaign_feedback_committed"] == "false" for row in u2_rows)

    primary_failure_pair = next(row for row in pair_rows if row["message_id"] == "message_3" and row["user_id"] == "u4")
    assert primary_failure_pair["primary_status"] == "provider_failed"
    assert primary_failure_pair["shadow_status"] == "succeeded"

    shadow_failure_pair = next(row for row in pair_rows if row["message_id"] == "message_2" and row["user_id"] == "u3")
    assert shadow_failure_pair["primary_status"] == "succeeded"
    assert shadow_failure_pair["shadow_status"] == "provider_failed"

    assert len(primary_adapter.calls) == 60
    assert len(shadow_adapter.calls) == 60


def test_concurrent_message_config_rejects_non_production_shape_on_default_profile(tmp_path: Path) -> None:
    dataset_dir = _make_concurrent_fixture(tmp_path)

    with pytest.raises(ValueError, match="production sample_size must be 1000"):
        ConcurrentMessageExperimentConfig(dataset_dir=dataset_dir, sample_size=30)

    with pytest.raises(ValueError, match="authoritative three-message contract"):
        ConcurrentMessageExperimentConfig(
            dataset_dir=dataset_dir,
            sample_size=30,
            horizon=2,
            delivery_capacity=10,
            configuration_profile="validation",
            messages=(
                authoritative_message_definitions()[0].model_copy(update={"title": "Altered title"}),
                authoritative_message_definitions()[1],
                authoritative_message_definitions()[2],
            ),
        )

    validation_config = ConcurrentMessageExperimentConfig(
        dataset_dir=dataset_dir,
        sample_size=30,
        horizon=2,
        delivery_capacity=10,
        configuration_profile="validation",
    )

    assert validation_config.configuration_profile == "validation"
