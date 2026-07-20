from __future__ import annotations

import csv
import hashlib
import json
import math
import shutil
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from llm_abm_sim import FinalResearchConfig, FinalResearchModel, FinalResearchRunner, rebuild_final_research_report
from llm_abm_sim.decision import DecisionInput, EngageDecision, LLMDecisionAdapter, ProviderDecisionError
from llm_abm_sim.final_research_report import (
    FinalResearchRankingReportPayload,
    FinalResearchRankingReportPayloadV3,
    FinalResearchReportWriter,
)
from llm_abm_sim.prompting import build_engagement_prompt
from llm_abm_sim.providers.openai_compatible import OpenAICompatibleDecisionAdapter
from llm_abm_sim.safe_serialization import artifact_has_forbidden_terms
from llm_abm_sim.schemas import (
    FailClosedAction,
    PeerContext,
    PlatformContext,
    PostContent,
    ProviderLLMConfig,
    UserProfile,
)

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


def _make_processed_fixture(tmp_path: Path, *, user_count: int = 6, dense_target_network: bool = False) -> Path:
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
                "creator_user_id": "u1" if dense_target_network else "creator-history",
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
    historical_rows = [
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
    ]
    if dense_target_network:
        historical_rows.extend(
            {
                "comment_id": f"dense-{number}",
                "video_id": "history-jinjiang",
                "parent_comment_id": "0",
                "commenter_user_id": f"u{number}",
                "mentioned_user_ids": json.dumps(
                    [f"u{other}" for other in range(1, user_count + 1) if other != number]
                ),
                "like_count": 0,
                "comment_level": "comment",
            }
            for number in range(2, user_count + 1)
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
            *historical_rows,
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
        "interest_tags",
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
    for number in range(1, user_count + 1):
        user_id = f"u{number}"
        user_rows.append(
            {
                "user_id": user_id,
                "nickname": f"User {number}",
                "bio": "Bearer sk-secret" if number == 3 else f"Bio {number}",
                "signature": f"Signature {number}",
                "interest_tags": "[]",
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


def _make_network_augmented_fixture(tmp_path: Path) -> Path:
    dataset_dir = _make_processed_fixture(tmp_path, user_count=22)
    video_rows = _read_csv(dataset_dir / "videos.csv")
    for row in video_rows:
        if row["video_id"] == "history-jinjiang":
            row["creator_user_id"] = "u11"
    _write_csv(dataset_dir / "videos.csv", list(video_rows[0]), video_rows)

    historical_rows = [
        {
            "comment_id": f"scope-a-{number}",
            "video_id": "history-scope-a",
            "parent_comment_id": "0",
            "commenter_user_id": f"u{number}",
            "mentioned_user_ids": "[]",
            "like_count": number,
            "comment_level": "comment",
        }
        for number in range(1, 12)
    ]
    historical_rows.extend(
        {
            "comment_id": f"target-scope-{number}",
            "video_id": "history-jinjiang",
            "parent_comment_id": "0",
            "commenter_user_id": f"u{number}",
            "mentioned_user_ids": '["u21", "u22"]' if number == 20 else "[]",
            "like_count": number,
            "comment_level": "comment",
        }
        for number in range(12, 21)
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
            *historical_rows,
            {
                "comment_id": "target-holdout-1",
                "video_id": TARGET_VIDEO_ID,
                "parent_comment_id": "0",
                "commenter_user_id": "u1",
                "mentioned_user_ids": "[]",
                "like_count": 999,
                "comment_level": "comment",
            },
            {
                "comment_id": "target-holdout-2",
                "video_id": TARGET_VIDEO_ID,
                "parent_comment_id": "target-holdout-1",
                "commenter_user_id": "u5",
                "mentioned_user_ids": "[]",
                "like_count": 999,
                "comment_level": "reply",
            },
        ],
    )
    return dataset_dir


def _make_target_delivery_fixture(tmp_path: Path) -> Path:
    dataset_dir = _make_processed_fixture(tmp_path, user_count=80)
    video_rows = _read_csv(dataset_dir / "videos.csv")
    for row in video_rows:
        if row["video_id"] == "history-scope-b":
            row["hashtags"] = "[]"
    _write_csv(dataset_dir / "videos.csv", list(video_rows[0]), video_rows)

    historical_rows = [
        {
            "comment_id": f"scope-a-{number}",
            "video_id": "history-scope-a",
            "parent_comment_id": "0",
            "commenter_user_id": f"u{number}",
            "mentioned_user_ids": "[]",
            "like_count": 0,
            "comment_level": "comment",
        }
        for number in range(1, 51)
    ]
    historical_rows.append(
        {
            "comment_id": "target-scope-seed",
            "video_id": "history-jinjiang",
            "parent_comment_id": "0",
            "commenter_user_id": "u80",
            "mentioned_user_ids": '["u60"]',
            "like_count": 0,
            "comment_level": "comment",
        }
    )
    historical_rows.extend(
        {
            "comment_id": f"scope-b-{number}",
            "video_id": "history-scope-b",
            "parent_comment_id": "0",
            "commenter_user_id": f"u{number}",
            "mentioned_user_ids": "[]",
            "like_count": 0,
            "comment_level": "comment",
        }
        for number in range(51, 80)
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
            *historical_rows,
            {
                "comment_id": "target-holdout-1",
                "video_id": TARGET_VIDEO_ID,
                "parent_comment_id": "0",
                "commenter_user_id": "u1",
                "mentioned_user_ids": "[]",
                "like_count": 999,
                "comment_level": "comment",
            },
        ],
    )
    return dataset_dir


def _make_seed_first_scope_fallback_fixture(tmp_path: Path) -> Path:
    dataset_dir = _make_processed_fixture(tmp_path, user_count=30)
    historical_rows = [
        {
            "comment_id": f"scope-a-{number}",
            "video_id": "history-scope-a",
            "parent_comment_id": "0",
            "commenter_user_id": f"u{number}",
            "mentioned_user_ids": "[]",
            "like_count": 0,
            "comment_level": "comment",
        }
        for number in range(1, 5)
    ]
    historical_rows.append(
        {
            "comment_id": "scope-b-tie-u4",
            "video_id": "history-scope-b",
            "parent_comment_id": "0",
            "commenter_user_id": "u4",
            "mentioned_user_ids": "[]",
            "like_count": 0,
            "comment_level": "comment",
        }
    )
    historical_rows.extend(
        {
            "comment_id": f"scope-b-{number}",
            "video_id": "history-scope-b",
            "parent_comment_id": "0",
            "commenter_user_id": f"u{number}",
            "mentioned_user_ids": "[]",
            "like_count": number * 100,
            "comment_level": "comment",
        }
        for number in range(21, 31)
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
            *historical_rows,
            {
                "comment_id": "target-holdout",
                "video_id": TARGET_VIDEO_ID,
                "parent_comment_id": "0",
                "commenter_user_id": "u20",
                "mentioned_user_ids": '["u1", "u2"]',
                "like_count": 999999,
                "comment_level": "comment",
            },
        ],
    )
    return dataset_dir


def _make_seed_first_neighbor_capacity_fixture(tmp_path: Path) -> Path:
    dataset_dir = _make_processed_fixture(tmp_path, user_count=40)
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
                "comment_id": "seed-network",
                "video_id": "history-jinjiang",
                "parent_comment_id": "0",
                "commenter_user_id": "u40",
                "mentioned_user_ids": json.dumps([f"u{number}" for number in range(1, 26)]),
                "like_count": 1000,
                "comment_level": "comment",
            },
            {
                "comment_id": "global-local-overlap-38",
                "video_id": "history-scope-b",
                "parent_comment_id": "0",
                "commenter_user_id": "u38",
                "mentioned_user_ids": "[]",
                "like_count": 500,
                "comment_level": "comment",
            },
            {
                "comment_id": "global-local-overlap-39",
                "video_id": "history-scope-b",
                "parent_comment_id": "0",
                "commenter_user_id": "u39",
                "mentioned_user_ids": "[]",
                "like_count": 500,
                "comment_level": "comment",
            },
            {
                "comment_id": "target-holdout",
                "video_id": TARGET_VIDEO_ID,
                "parent_comment_id": "0",
                "commenter_user_id": "u30",
                "mentioned_user_ids": '["u26"]',
                "like_count": 999999,
                "comment_level": "comment",
            },
        ],
    )
    return dataset_dir


class _ScriptedProviderClient:
    def __init__(self) -> None:
        self.calls = 0
        self.requests: list[list[dict[str, str]]] = []

    def create_response(self, messages: list[dict[str, str]], model: str) -> dict[str, object]:
        del model
        self.requests.append(messages)
        self.calls += 1
        if self.calls == 2 or 4 <= self.calls <= 9:
            raise TimeoutError("mocked provider timeout with sk-secret")
        action = ("like", "share", "comment")[self.calls % 3]
        return {
            "engage": True,
            "probability": 0.8,
            "reason": "mocked deterministic engagement",
            "confidence": 0.9,
            "action": action,
        }


class _RecordingAdapter(LLMDecisionAdapter):
    def __init__(self, wrapped: LLMDecisionAdapter) -> None:
        self.wrapped = wrapped
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
                "post": post,
                "profile": profile,
                "peer_context": peer_context,
                "platform_context": platform_context,
                "time_step": time_step,
            }
        )
        return self.wrapped.decide(post, profile, peer_context, platform_context, time_step)


class _TargetDeliveryAdapter(LLMDecisionAdapter):
    def __init__(self, *, failed_user_id: str | None = None, mark_live_api_triggered: bool = False) -> None:
        self.failed_user_id = failed_user_id
        self.mark_live_api_triggered = mark_live_api_triggered
        self.live_api_triggered = False
        self.calls: list[dict[str, object]] = []

    def decide(
        self,
        post: PostContent,
        profile: UserProfile,
        peer_context: PeerContext,
        platform_context: PlatformContext | None = None,
        time_step: int = 0,
    ) -> EngageDecision:
        if self.mark_live_api_triggered:
            self.live_api_triggered = True
        build_engagement_prompt(
            DecisionInput(
                post=post,
                profile=profile,
                peer_context=peer_context,
                platform_context=platform_context or PlatformContext(),
                time_step=time_step,
            )
        )
        self.calls.append(
            {
                "post": post,
                "profile": profile,
                "peer_context": peer_context,
                "platform_context": platform_context,
                "time_step": time_step,
            }
        )
        if profile.user_id == self.failed_user_id:
            raise ProviderDecisionError(TimeoutError("mocked exhausted provider failure"))
        if profile.user_id == "u80":
            return EngageDecision(
                engage=True,
                probability=0.9,
                reason="controlled seed engagement",
                confidence=1.0,
                action="like",
                decision_source="mocked_provider",
            )
        return EngageDecision(
            engage=False,
            probability=0.1,
            reason="controlled ignore",
            confidence=1.0,
            action="ignore",
            decision_source="mocked_provider",
        )


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
    assert manifest["manifest_version"] == "final-research-offline-v2"
    assert manifest["artifacts"] == {
        "config_snapshot": "config_snapshot.json",
        "final_research_report": "report.html",
        "final_research_report_payload": "final_research_report_payload.json",
        "final_research_users_csv": "final_research_users.csv",
        "final_research_users_json": "final_research_users.json",
        "holdout_diagnostic": "top20_holdout_diagnostic.json",
        "holdout_safe_audit": "holdout_safe_audit.json",
        "seed_first_sample_audit": "seed_first_sample_audit.json",
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
    assert [row["user_id"] for row in sample_rows] == ["u1", "u2", "u5", "u6"]
    assert [row["is_seed"] for row in sample_rows] == ["true", "true", "true", "true"]
    assert audit["global_top10_local_top10_seed_union"] == ["u1", "u2", "u5", "u6"]
    assert all(
        field not in sample_rows[0]
        for field in ("brand_attitude", "like_tendency", "comment_tendency", "share_tendency")
    )
    offline_report_rows = _read_csv(first_output / "final_research_users.csv")
    assert len(offline_report_rows) == 4
    assert {row["result_status"] for row in offline_report_rows} == {"runtime_not_run"}
    assert {row["provider_status"] for row in offline_report_rows} == {"runtime_not_run"}
    assert {row["sample_role"] for row in offline_report_rows} == {"seed"}

    score_rows = {row["user_id"]: row for row in _read_csv(first_output / "offline_scores.csv")}
    assert len(score_rows) == 6
    assert float(score_rows["u1"]["historical_tag_affinity"]) == 0.5
    assert float(score_rows["u1"]["base_network_relevance"]) == 1.0
    assert float(score_rows["u1"]["base_network_score"]) == 1.0
    assert float(score_rows["u1"]["recommendation_score"]) == 0.6
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
    offline_payload = json.loads((first_output / "final_research_report_payload.json").read_text(encoding="utf-8"))
    offline_html = (first_output / "report.html").read_text(encoding="utf-8")
    assert offline_payload["run"]["sampling_method"] == "seed_first_research_sample_v1"
    assert offline_payload["run"]["sampling_status"] == "validation_run"
    assert offline_payload["sample_summary"]["sample_role_counts"] == {"seed": 4}
    assert {row["sample_role"] for row in offline_payload["users"]} == {"seed"}
    assert offline_payload["diagnostics"]["seed_method"].endswith("from the full eligible pool")
    assert offline_payload["recommendation_model"]["network_weight"] == 0.5
    assert offline_payload["recommendation_model"]["tag_affinity_weight"] == 0.2
    assert offline_payload["video_usage"]["runtime_target_video_count"] == 0
    assert offline_payload["batch_explanation"]["batch_count"] == 0
    assert "runtime 未启用" in offline_payload["video_usage"]["target_video_role"]
    assert "runtime 未启用" in offline_payload["batch_explanation"]["assignment_method"]
    assert "Batch 0 为 seeds" not in offline_html
    assert "30 个固定推荐批次" not in offline_html
    assert "Validation Run（验证运行） · Seed-First Research Sample（先选种子研究样本）" in offline_html
    assert "union within the sample" not in offline_html
    assert "<dt>推荐批次</dt><dd>未执行</dd>" in offline_html
    for relative_path in manifest["artifacts"].values():
        assert (first_output / relative_path).read_bytes() == (second_output / relative_path).read_bytes()


def test_offline_final_research_builds_seed_first_sample_from_full_pool(tmp_path: Path) -> None:
    dataset_dir = _make_network_augmented_fixture(tmp_path)
    adapter = FailingIfCalledAdapter()
    config = FinalResearchConfig(dataset_dir=dataset_dir, sample_size=20, random_seed=20260713)

    first_output = FinalResearchRunner(config, adapter).run_and_write(tmp_path / "seed-first-run-a")
    second_output = FinalResearchRunner(config, adapter).run_and_write(tmp_path / "seed-first-run-b")

    assert adapter.calls == 0
    manifest = json.loads((first_output / "artifact_manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == "final-research-offline-v2"
    assert manifest["sampling_method"] == "seed_first_research_sample_v1"
    assert manifest["sampling_status"] == "validation_run"
    assert manifest["artifacts"]["seed_first_sample_audit"] == "seed_first_sample_audit.json"
    assert "network_augmented_sample_audit" not in manifest["artifacts"]

    audit = json.loads((first_output / "seed_first_sample_audit.json").read_text(encoding="utf-8"))
    assert audit["schema_version"] == "seed-first-sample-audit-v1"
    assert audit["sampling_method"] == "seed_first_research_sample_v1"
    assert audit["eligible_pool"]["count"] == 22
    assert {"u21", "u22"} <= set(audit["seed_selection"]["seed_user_ids"])
    assert audit["seed_selection"]["selection_stage"] == "eligible_full_pool_before_sampling"
    assert audit["roles"]["counts"] == {"network_cohort": 0, "ordinary": 8, "seed": 12}

    final_user_ids = audit["final_sample"]["user_ids"]
    assert len(final_user_ids) == len(set(final_user_ids)) == 20
    role_user_ids = audit["roles"]["user_ids"]
    assert set(role_user_ids["seed"]) | set(role_user_ids["network_cohort"]) | set(role_user_ids["ordinary"]) == set(
        final_user_ids
    )
    assert not set(role_user_ids["seed"]) & set(role_user_ids["network_cohort"])
    assert not set(role_user_ids["seed"]) & set(role_user_ids["ordinary"])
    assert not set(role_user_ids["network_cohort"]) & set(role_user_ids["ordinary"])
    assert {row["user_id"] for row in _read_csv(first_output / "sample_manifest.csv")} == set(final_user_ids)

    holdout_audit = json.loads((first_output / "holdout_safe_audit.json").read_text(encoding="utf-8"))
    p95_degree = holdout_audit["base_network_relevance"]["p95_weighted_degree"]
    assert p95_degree == pytest.approx(2.9)
    score_rows = {row["user_id"]: row for row in _read_csv(first_output / "offline_scores.csv")}
    assert int(score_rows["u12"]["target_scope_weighted_degree"]) == 1
    assert float(score_rows["u12"]["base_network_relevance"]) == pytest.approx(
        min(1.0, math.log1p(1) / math.log1p(p95_degree)), abs=1e-6
    )
    assert float(score_rows["u1"]["base_network_relevance"]) == 0.0
    assert float(score_rows["u12"]["recommendation_score"]) == pytest.approx(
        0.50 * float(score_rows["u12"]["base_network_relevance"])
        + 0.20 * float(score_rows["u12"]["historical_tag_affinity"]),
        abs=1e-6,
    )

    for relative_path in manifest["artifacts"].values():
        assert (first_output / relative_path).read_bytes() == (second_output / relative_path).read_bytes()


def test_seed_first_sample_audits_overlap_scope_ties_and_fallback(tmp_path: Path) -> None:
    dataset_dir = _make_seed_first_scope_fallback_fixture(tmp_path)
    config = FinalResearchConfig(dataset_dir=dataset_dir, sample_size=20, random_seed=20260713)

    first_output = FinalResearchRunner(config, FailingIfCalledAdapter()).run_and_write(tmp_path / "scope-a")
    second_output = FinalResearchRunner(config, FailingIfCalledAdapter()).run_and_write(tmp_path / "scope-b")
    first_audit_path = first_output / "seed_first_sample_audit.json"
    second_audit_path = second_output / "seed_first_sample_audit.json"
    audit = json.loads(first_audit_path.read_text(encoding="utf-8"))

    seed_selection = audit["seed_selection"]
    assert set(seed_selection["global_top10_user_ids"]) == set(seed_selection["local_top10_user_ids"])
    assert seed_selection["seed_count"] == 10
    assert audit["scope_selection"]["tied_primary_scope_user_ids"] == ["u4"]
    assert audit["final_sample"]["primary_scope_by_user"]["u4"] == "锦江都城酒店"
    assert audit["scope_selection"]["fallback"]["needed_count"] == 6
    assert len(audit["scope_selection"]["fallback"]["selected_user_ids"]) == 6
    assert audit["roles"]["counts"] == {"network_cohort": 0, "ordinary": 10, "seed": 10}
    assert first_audit_path.read_bytes() == second_audit_path.read_bytes()


def test_seed_first_sample_caps_neighbors_by_edge_strength_and_user_id(tmp_path: Path) -> None:
    dataset_dir = _make_seed_first_neighbor_capacity_fixture(tmp_path)
    output = FinalResearchRunner(
        FinalResearchConfig(dataset_dir=dataset_dir, sample_size=20, random_seed=20260713),
        FailingIfCalledAdapter(),
    ).run_and_write(tmp_path / "neighbor-capacity")
    audit = json.loads((output / "seed_first_sample_audit.json").read_text(encoding="utf-8"))

    neighbor_selection = audit["neighbor_selection"]
    assert audit["seed_selection"]["seed_count"] == 17
    assert neighbor_selection["candidate_count"] == 18
    assert neighbor_selection["capacity"] == 3
    assert neighbor_selection["selected_user_ids"] == ["u16", "u17", "u18"]
    assert neighbor_selection["candidates"][0] == {
        "seed_edge_weight": 1,
        "selected": True,
        "user_id": "u16",
    }
    assert audit["roles"]["counts"] == {"network_cohort": 3, "ordinary": 0, "seed": 17}


def test_offline_final_research_handles_zero_target_scope_network_without_holdout_leakage(tmp_path: Path) -> None:
    dataset_dir = _make_processed_fixture(tmp_path)
    video_rows = _read_csv(dataset_dir / "videos.csv")
    for row in video_rows:
        if row["video_id"] == "history-jinjiang":
            row["source_challenge_name"] = "其他历史来源"
    _write_csv(dataset_dir / "videos.csv", list(video_rows[0]), video_rows)

    adapter = FailingIfCalledAdapter()
    output_dir = FinalResearchRunner(
        FinalResearchConfig(dataset_dir=dataset_dir, sample_size=4),
        adapter,
    ).run_and_write(tmp_path / "zero-network-run")

    assert adapter.calls == 0
    holdout_audit = json.loads((output_dir / "holdout_safe_audit.json").read_text(encoding="utf-8"))
    assert holdout_audit["holdout_interaction_rows"] == 2
    assert holdout_audit["base_network_relevance"]["p95_weighted_degree"] == 0.0
    score_rows = _read_csv(output_dir / "offline_scores.csv")
    assert {int(row["target_scope_weighted_degree"]) for row in score_rows} == {0}
    assert {float(row["base_network_relevance"]) for row in score_rows} == {0.0}


def test_target_delivery_ranking_runtime_reranks_global_top20_after_seed_engagement(tmp_path: Path) -> None:
    dataset_dir = _make_target_delivery_fixture(tmp_path)
    provider_config = ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False)
    config = FinalResearchConfig(
        dataset_dir=dataset_dir,
        sample_size=70,
        random_seed=20260713,
        provider=provider_config,
    )

    def run(output_dir: Path) -> tuple[Path, _TargetDeliveryAdapter]:
        adapter = _TargetDeliveryAdapter(failed_user_id="u79")
        return FinalResearchRunner(config, adapter).run_and_write(output_dir), adapter

    first_output, first_adapter = run(tmp_path / "ranking-runtime-a")
    second_output, second_adapter = run(tmp_path / "ranking-runtime-b")

    manifest = json.loads((first_output / "artifact_manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == "final-research-ranking-runtime-v2"
    assert manifest["artifacts"] == {
        "config_snapshot": "config_snapshot.json",
        "final_research_report": "report.html",
        "final_research_report_payload": "final_research_report_payload.json",
        "final_research_users_csv": "final_research_users.csv",
        "final_research_users_json": "final_research_users.json",
        "field_lineage_catalog": "field_lineage_catalog.json",
        "field_source_records": "field_source_records.json",
        "holdout_diagnostic": "top20_holdout_diagnostic.json",
        "holdout_safe_audit": "holdout_safe_audit.json",
        "seed_first_sample_audit": "seed_first_sample_audit.json",
        "offline_score_summary": "offline_score_summary.json",
        "offline_scores": "offline_scores.csv",
        "ranking_ablation_diagnostics_csv": "ranking_ablation_diagnostics.csv",
        "ranking_diagnostics": "ranking_diagnostics.json",
        "ranking_diagnostics_summary": "ranking_diagnostics_summary.json",
        "ranking_runtime_candidates": "ranking_runtime_candidates.csv",
        "ranking_runtime_outcomes": "ranking_runtime_outcomes.csv",
        "ranking_runtime_steps": "ranking_runtime_steps.csv",
        "ranking_runtime_summary": "ranking_runtime_summary.json",
        "ranking_weight_sensitivity_csv": "ranking_weight_sensitivity.csv",
        "runtime_actions": "runtime_actions.csv",
        "runtime_decisions": "runtime_decisions.csv",
        "runtime_provider_failures": "runtime_provider_failures.csv",
        "sample_manifest_csv": "sample_manifest.csv",
        "sample_manifest_json": "sample_manifest.json",
        "target_video_snapshot": "target_video_snapshot.json",
        "user_field_trace": "user_field_trace.json",
    }
    assert manifest["live_api_triggered"] is False

    candidates = _read_csv(first_output / "ranking_runtime_candidates.csv")
    outcomes = _read_csv(first_output / "ranking_runtime_outcomes.csv")
    steps = _read_csv(first_output / "ranking_runtime_steps.csv")
    decisions = _read_csv(first_output / "runtime_decisions.csv")
    failures = _read_csv(first_output / "runtime_provider_failures.csv")
    audit = json.loads((first_output / "seed_first_sample_audit.json").read_text(encoding="utf-8"))
    summary = json.loads((first_output / "ranking_runtime_summary.json").read_text(encoding="utf-8"))
    ranking_diagnostics = json.loads((first_output / "ranking_diagnostics.json").read_text(encoding="utf-8"))
    diagnostic_summary = json.loads((first_output / "ranking_diagnostics_summary.json").read_text(encoding="utf-8"))
    ablation_rows = _read_csv(first_output / "ranking_ablation_diagnostics.csv")
    sensitivity_rows = _read_csv(first_output / "ranking_weight_sensitivity.csv")
    report_rows = _read_csv(first_output / "final_research_users.csv")
    report_users = json.loads((first_output / "final_research_users.json").read_text(encoding="utf-8"))
    report_payload = json.loads((first_output / "final_research_report_payload.json").read_text(encoding="utf-8"))
    report_html = (first_output / "report.html").read_text(encoding="utf-8")

    assert manifest["sampling_method"] == "seed_first_research_sample_v1"
    assert manifest["sampling_status"] == "validation_run"
    assert "u80" in audit["roles"]["user_ids"]["seed"]
    assert "u60" in audit["roles"]["user_ids"]["network_cohort"]
    batch_zero = [row for row in candidates if row["time_step"] == "0"]
    assert {row["user_id"] for row in batch_zero} == set(audit["roles"]["user_ids"]["seed"])
    assert all(row["selected"] == "true" for row in batch_zero)

    batch_one = [row for row in candidates if row["time_step"] == "1"]
    assert len(batch_one) == int(steps[1]["eligible_users"])
    assert sum(row["selected"] == "true" for row in batch_one) == 20
    assert [int(row["ranking_position"]) for row in batch_one] == list(range(1, len(batch_one) + 1))
    u60 = next(row for row in batch_one if row["user_id"] == "u60")
    assert u60["selected"] == "true"
    assert int(u60["engaged_neighbor_count"]) == 1
    assert float(u60["engaged_neighbor_signal"]) == pytest.approx(1 / 3, abs=1e-6)
    assert float(u60["recommendation_score"]) == pytest.approx(0.1, abs=1e-6)
    static_order = sorted(
        batch_one,
        key=lambda row: (
            -(0.50 * float(row["base_network_relevance"]) + 0.20 * float(row["historical_tag_affinity"])),
            row["user_id"],
        ),
    )
    assert int(u60["ranking_position"]) < 1 + next(
        index for index, row in enumerate(static_order) if row["user_id"] == "u60"
    )

    exposed_outcomes = [row for row in outcomes if row["result_status"] != "below_delivery_capacity"]
    assert len(first_adapter.calls) == len(exposed_outcomes) == manifest["decision_adapter_calls"]
    assert len({row["user_id"] for row in exposed_outcomes}) == len(exposed_outcomes)
    assert len(first_adapter.calls) <= 600
    assert failures == [
        {
            "schedule_position": failures[0]["schedule_position"],
            "user_id": "u79",
            "video_id": TARGET_VIDEO_ID,
            "time_step": "0",
            "failure_type": "TimeoutError",
            "provider_metadata": failures[0]["provider_metadata"],
        }
    ]
    failed_position = int(failures[0]["schedule_position"])
    assert any(int(row["schedule_position"]) > failed_position for row in decisions)
    assert all(call["peer_context"] == PeerContext() for call in first_adapter.calls)
    assert all(call["peer_context"] == PeerContext() for call in second_adapter.calls)

    assert summary["runtime_version"] == "final-research-ranking-runtime-v2"
    assert summary["schedule_method"] == "global_stable_reranking_top20"
    assert summary["delivery_capacity"] == 20
    assert summary["ranking_formula"] == (
        "0.50 * base_network_relevance + 0.30 * engaged_neighbor_signal + 0.20 * historical_tag_affinity"
    )
    assert summary["engaged_neighbor_formula"] == "min(1, engaged_neighbor_count / 3)"
    assert summary["maximum_target_exposures"] == 600
    assert "background_impressions" not in summary["counts"]
    assert summary["counts"]["decision_adapter_calls"] == len(first_adapter.calls)
    assert ranking_diagnostics["schema_version"] == "ranking-diagnostics-v1"
    assert len(ranking_diagnostics["paired_ablation"]["batches"]) == len(steps) == 30
    assert ranking_diagnostics["paired_ablation"]["same_candidate_set_and_frozen_state"] is True
    assert ranking_diagnostics["paired_ablation"]["advances_user_state"] is False
    assert ranking_diagnostics["paired_ablation"]["calls_decision_adapter"] is False
    assert ranking_diagnostics["paired_ablation"]["complete_counterfactual_trajectory"] is False
    assert [variant["variant_id"] for variant in ranking_diagnostics["weight_sensitivity"]["variants"]] == [
        "main_50_30_20",
        "weaker_network_40_20_40",
        "no_network_0_0_100",
    ]
    batch_one_diagnostic = ranking_diagnostics["paired_ablation"]["batches"][1]
    assert batch_one_diagnostic["full_top_user_ids"] == [
        row["user_id"] for row in batch_one if row["selected"] == "true"
    ]
    assert "u60" in batch_one_diagnostic["network_added_user_ids"]
    diagnostic_batches = {int(batch["time_step"]): batch for batch in ranking_diagnostics["paired_ablation"]["batches"]}
    for step in steps:
        time_step = int(step["time_step"])
        persisted_batch = [row for row in candidates if int(row["time_step"]) == time_step]
        diagnostic_batch = diagnostic_batches[time_step]
        assert diagnostic_batch["eligible_count"] == int(step["eligible_users"])
        assert diagnostic_batch["candidate_user_ids"] == [row["user_id"] for row in persisted_batch]
    assert diagnostic_summary["diagnostic_decision_adapter_calls"] == 0
    assert diagnostic_summary["recommendation_signal_inclusion"]["network_signals_in_formula"] is True
    assert diagnostic_summary["observed_recommendation_signal_effect"]["top_selection_changed"] is True
    assert manifest["diagnostic_decision_adapter_calls"] == 0
    assert manifest["counts"]["ranking_diagnostic_batches"] == len(steps)
    assert manifest["counts"]["ranking_ablation_rows"] == len(ablation_rows) == len(candidates)
    assert manifest["counts"]["ranking_sensitivity_rows"] == len(sensitivity_rows) == 3 * len(steps)
    assert (
        manifest["counts"]["ranking_batches_with_network_top20_effect"]
        == diagnostic_summary["observed_recommendation_signal_effect"]["batches_with_top_selection_change"]
    )
    assert len(first_adapter.calls) == summary["counts"]["decision_adapter_calls"]

    assert report_payload["schema_version"] == "final-research-ranking-report-payload-v4"
    assert report_payload["run"]["sampling_method"] == "seed_first_research_sample_v1"
    assert report_payload["run"]["sampling_status"] == "validation_run"
    assert report_payload["sample_comparison"]["final_sample_count"] == audit["final_sample"]["count"]
    assert report_payload["sample_comparison"]["seed_count"] == audit["roles"]["counts"]["seed"]
    assert report_payload["sample_comparison"]["network_cohort_count"] == audit["roles"]["counts"]["network_cohort"]
    assert report_payload["sample_comparison"]["ordinary_count"] == audit["roles"]["counts"]["ordinary"]
    assert (
        report_payload["sample_comparison"]["final_source_scope_counts"] == audit["final_sample"]["source_scope_counts"]
    )
    assert len(report_rows) == len(report_users["users"]) == len(report_payload["users"]) == 70
    assert [row["user_id"] for row in report_payload["users"]] == [row["user_id"] for row in report_users["users"]]
    assert {row["result_status"] for row in report_payload["users"]} == {"like", "ignore", "provider_failed"}
    lineage = {entry["field_name"]: entry for entry in report_payload["field_lineage"]}
    assert set(report_payload["users"][0]) <= set(lineage)
    assert {
        "target_video.caption",
        "run.ranking_formula",
        "sample_comparison.network_cohort_count",
        "ranking_rounds.candidates.recommendation_score",
        "ranking_diagnostics.paired_ablation",
        "ranking_diagnostics.weight_sensitivity",
    } <= set(lineage)
    assert {entry["provenance"] for entry in lineage.values()} <= {
        "Direct Observed Profile Field",
        "Historical Behavioral Evidence",
        "Derived Proxy Metric",
        "Synthetic Experiment Label",
        "Runtime Simulation Result",
    }
    assert all(entry["usage_stages"] for entry in lineage.values())
    assert {stage for entry in lineage.values() for stage in entry["usage_stages"]} <= {
        "Sampling",
        "Seed Selection",
        "Ranking",
        "LLM Prompt",
        "Report Only",
    }
    for excluded_field in (
        "base_network_relevance",
        "engaged_neighbor_count",
        "engaged_neighbor_signal",
        "historical_tag_affinity",
        "recommendation_score",
        "latest_ranking_position",
    ):
        assert "LLM Prompt" not in lineage[excluded_field]["usage_stages"]
    assert 'data-testid="final-research-ranking-report"' in report_html
    assert 'data-report-mode="mechanism"' in report_html
    assert 'data-testid="mechanism-mode-button"' in report_html
    assert 'data-testid="run-evidence-mode-button"' in report_html
    for anchor in ("overview", "sample", "exposure-ranking", "llm-decision", "network-feedback"):
        assert f'href="#{anchor}"' in report_html
    assert 'data-testid="sample-construction-illustration"' in report_html
    assert 'data-testid="batch-zero-seeds-illustration"' in report_html
    assert 'data-testid="global-reranking-illustration"' in report_html
    assert 'data-testid="platform-llm-boundary-illustration"' in report_html
    assert 'data-testid="neighbor-feedback-illustration"' in report_html
    assert 'data-testid="capacity-network-impact-illustration"' in report_html
    assert report_html.count('src="data:image/webp;base64,') == 6
    assert "Accepted · persisted Validation Run" in report_html
    assert f"{audit['roles']['counts']['seed']} seeds" in report_html
    assert f"{audit['roles']['counts']['network_cohort']} Seed Neighbor Cohort" in report_html
    assert f"{audit['roles']['counts']['ordinary']} ordinary users" in report_html
    assert "live provider 正式运行" in report_html
    assert "Full-Pool Influence Seed Union" in report_html
    assert "not Global Reranking Top20 winners" in report_html
    for hotspot in (
        "batch-zero-hotspot-seeds",
        "reranking-hotspot-network",
        "reranking-hotspot-neighbor",
        "reranking-hotspot-affinity",
        "reranking-hotspot-top20",
    ):
        assert f'data-testid="{hotspot}"' in report_html
    assert 'data-testid="batch-zero-video-label"' in report_html
    assert "50% 历史评论网络位置" in report_html
    assert "30% 已互动直接邻居" in report_html
    assert "20% 历史标签亲和度" in report_html
    assert "Recommendation Signal Inclusion" in report_html
    assert "Observed Recommendation Signal Effect" in report_html
    assert 'class="ranking-hero"' not in report_html
    assert 'data-testid="ranking-funnel-section"' not in report_html
    assert 'data-testid="ranking-hero"' in report_html
    assert 'class="run-evidence-intro"' in report_html
    assert 'data-testid="run-evidence-method-status"' in report_html
    assert "Validation Run" in report_html
    assert "Seed-First 离线验证证据" in report_html
    for role in ("seed", "network_cohort", "ordinary"):
        role_count = sum(row["sample_role"] == role for row in report_payload["users"])
        assert f'data-testid="run-evidence-{role.replace("_", "-")}-count"' in report_html
        assert f">{role_count:,}</strong>" in report_html
    for retired_visual_token in (
        "#66509a",
        "#b8c4bd",
        "#bcc8c1",
        "#d9d1f1",
        "#ded9e9",
        "#e5ebe7",
        "#edf4f0",
        "#eef2ef",
        "#eef5f2",
        "#f8f7fb",
        "border-inline:1px solid var(--line)",
    ):
        assert retired_visual_token not in report_html
    assert 'data-testid="target-video-link"' in report_html
    assert 'data-testid="core-objects-section"' in report_html
    assert 'data-testid="sample-comparison-section"' in report_html
    assert 'data-testid="field-lineage-section"' in report_html
    assert 'data-testid="ranking-rounds-section"' in report_html
    assert 'data-testid="network-effect-section"' in report_html
    assert 'data-testid="paired-ablation-section"' in report_html
    assert 'data-testid="sensitivity-section"' in report_html
    assert 'data-testid="prompt-contract-section"' in report_html
    assert 'data-testid="ranking-users-section"' in report_html
    assert 'data-testid="user-detail"' in report_html
    assert 'data-testid="download-ranking-diagnostics"' in report_html
    assert "random_draw" not in report_html
    assert "background_content" not in report_html
    assert report_payload["ranking_diagnostics"] == ranking_diagnostics
    assert {
        "peer_context.engagement_ratio",
        "peer_context.influential_engaged_neighbors",
    } <= set(report_payload["prompt_contract"]["neutralized_fields"])
    assert sum(len(round_row["candidates"]) for round_row in report_payload["ranking_rounds"]) == len(candidates)
    batch_one_report = report_payload["ranking_rounds"][1]
    assert batch_one_report["candidates_with_positive_engaged_neighbor_signal"] > 0
    assert batch_one_report["selected_with_positive_engaged_neighbor_signal"] > 0
    assert batch_one_report["maximum_engaged_neighbor_signal"] == pytest.approx(1 / 3, abs=1e-6)
    assert all(row["report_path"] == "report.html" for row in report_rows)
    assert all(row["payload_path"] == "final_research_report_payload.json" for row in report_rows)
    assert all(row["json_path"] == "final_research_users.json" for row in report_rows)
    assert all(row["manifest_path"] == "artifact_manifest.json" for row in report_rows)

    runtime_text = "\n".join(
        (first_output / relative_path).read_text(encoding="utf-8")
        for name, relative_path in manifest["artifacts"].items()
        if name.startswith("ranking_runtime_") or name.startswith("runtime_")
    )
    assert "random_draw" not in runtime_text
    assert "background_content" not in runtime_text
    assert "sk-secret" not in runtime_text
    prompt_inputs = json.dumps(
        [
            {
                "peer_context": cast(PeerContext, call["peer_context"]).model_dump(mode="json"),
                "platform_context": cast(PlatformContext, call["platform_context"]).model_dump(mode="json"),
            }
            for call in first_adapter.calls
        ],
        ensure_ascii=False,
    )
    for forbidden in (
        "base_network_relevance",
        "engaged_neighbor_count",
        "engaged_neighbor_signal",
        "historical_tag_affinity",
        "recommendation_score",
        "ranking_position",
    ):
        assert forbidden not in prompt_inputs

    for relative_path in [*manifest["artifacts"].values(), "artifact_manifest.json"]:
        assert (first_output / relative_path).read_bytes() == (second_output / relative_path).read_bytes()


def test_target_delivery_ranking_runtime_caps_delivery_and_marks_final_below_capacity(tmp_path: Path) -> None:
    dataset_dir = _make_processed_fixture(tmp_path, user_count=1010)
    provider_config = ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False)
    adapter = _TargetDeliveryAdapter()
    output = FinalResearchRunner(
        FinalResearchConfig(
            dataset_dir=dataset_dir,
            sample_size=1000,
            provider=provider_config,
        ),
        adapter,
    ).run_and_write(tmp_path / "capacity-runtime")

    outcomes = _read_csv(output / "ranking_runtime_outcomes.csv")
    steps = _read_csv(output / "ranking_runtime_steps.csv")
    summary = json.loads((output / "ranking_runtime_summary.json").read_text(encoding="utf-8"))
    exposed = [row for row in outcomes if row["result_status"] != "below_delivery_capacity"]
    below_capacity = [row for row in outcomes if row["result_status"] == "below_delivery_capacity"]
    report_rows = _read_csv(output / "final_research_users.csv")
    report_users = json.loads((output / "final_research_users.json").read_text(encoding="utf-8"))["users"]
    report_payload = json.loads((output / "final_research_report_payload.json").read_text(encoding="utf-8"))

    assert len(outcomes) == 1000
    assert len(exposed) == len(adapter.calls) == summary["counts"]["target_exposures"] <= 600
    assert len(below_capacity) == 1000 - len(exposed)
    assert below_capacity
    assert all(int(row["selected_users"]) <= 20 for row in steps)
    assert all(row["provider_status"] == "not_called" for row in below_capacity)
    assert all(row["exposure_time_step"] == "" for row in below_capacity)
    assert len(report_rows) == len(report_users) == len(report_payload["users"]) == 1000
    assert {row["result_status"] for row in report_payload["users"]} == {
        "ignore",
        "below_delivery_capacity",
    }
    assert sum(row["result_status"] == "below_delivery_capacity" for row in report_payload["users"]) == len(
        below_capacity
    )
    assert next(stage for stage in report_payload["run_funnel"] if stage["key"] == "below_delivery_capacity")[
        "count"
    ] == len(below_capacity)
    assert {row["provider_status"] for row in report_payload["users"] if row["result_status"] == "ignore"} == {
        "succeeded"
    }
    assert {
        row["provider_status"] for row in report_payload["users"] if row["result_status"] == "below_delivery_capacity"
    } == {"not_called"}


def test_target_delivery_ranking_v4_persists_interest_and_historical_field_traces(tmp_path: Path) -> None:
    dataset_dir = _make_processed_fixture(tmp_path, user_count=6, dense_target_network=True)
    user_rows = _read_csv(dataset_dir / "users.csv")
    user_rows[0]["interest_tags"] = json.dumps(["锦江ESG"], ensure_ascii=False)
    user_rows[1]["interest_tags"] = "[]"
    _write_csv(dataset_dir / "users.csv", list(user_rows[0]), user_rows)
    provider_config = ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False)

    output = FinalResearchRunner(
        FinalResearchConfig(
            dataset_dir=dataset_dir,
            sample_size=6,
            provider=provider_config,
        ),
        _TargetDeliveryAdapter(),
    ).run_and_write(tmp_path / "ranking-v4-field-trace")

    manifest = json.loads((output / "artifact_manifest.json").read_text(encoding="utf-8"))
    payload = json.loads((output / "final_research_report_payload.json").read_text(encoding="utf-8"))
    catalog_document = json.loads((output / manifest["artifacts"]["field_lineage_catalog"]).read_text(encoding="utf-8"))
    trace_document = json.loads((output / manifest["artifacts"]["user_field_trace"]).read_text(encoding="utf-8"))
    source_document = json.loads((output / manifest["artifacts"]["field_source_records"]).read_text(encoding="utf-8"))

    assert payload["schema_version"] == "final-research-ranking-report-payload-v4"
    assert catalog_document["schema_version"] == "field-lineage-catalog-v1"
    assert trace_document["schema_version"] == "user-field-trace-v1"
    assert source_document["schema_version"] == "field-source-records-v1"
    assert payload["field_lineage_catalog"] == catalog_document["definitions"]
    assert payload["user_field_trace_index"] == trace_document["users"]
    assert {entry["field_name"] for entry in payload["field_lineage_catalog"]} == {
        "interest_tags",
        "historical_tags",
    }

    u1_traces = {trace["field_name"]: trace for trace in payload["user_field_trace_index"]["u1"]}
    assert u1_traces["interest_tags"]["value_status"] == "present"
    assert u1_traces["interest_tags"]["prompt_inclusion_status"] == "included"
    assert u1_traces["interest_tags"]["actual_usage_stages"] == ["LLM Prompt", "Report Only"]
    assert u1_traces["interest_tags"]["evidence"] == [
        {
            "evidence_kind": "historical_video_hashtags",
            "record_key": {"video_id": "history-jinjiang"},
            "source_fields": ["hashtags"],
            "matched_values": ["锦江ESG"],
        }
    ]
    locator = u1_traces["interest_tags"]["source_record_locator"]
    assert manifest["artifacts"][locator["artifact_id"]] == locator["relative_path"]
    assert locator["record_key"] == {"user_id": "u1"}

    u2_traces = {trace["field_name"]: trace for trace in payload["user_field_trace_index"]["u2"]}
    assert u2_traces["interest_tags"]["value_status"] == "empty"
    assert u2_traces["interest_tags"]["prompt_inclusion_status"] == "empty_omitted"
    assert u2_traces["historical_tags"]["value_status"] == "present"
    assert u2_traces["historical_tags"]["prompt_inclusion_status"] == "not_allowlisted"
    source_records = {record["user_id"]: record for record in source_document["records"]}
    assert source_records["u2"]["interest_tags"] == []
    assert source_records["u2"]["historical_tags"] == ["锦江ESG"]

    assert payload["downloads"]["field_lineage_catalog"] == manifest["artifacts"]["field_lineage_catalog"]
    assert payload["downloads"]["user_field_trace"] == manifest["artifacts"]["user_field_trace"]
    persisted_text = "\n".join(
        (output / relative_path).read_text(encoding="utf-8")
        for relative_path in (
            manifest["artifacts"]["field_lineage_catalog"],
            manifest["artifacts"]["user_field_trace"],
            manifest["artifacts"]["field_source_records"],
        )
    )
    assert "raw_prompt" not in persisted_text
    assert "raw_provider_response" not in persisted_text
    assert "sk-secret" not in persisted_text


def test_target_delivery_ranking_runtime_persists_live_status_after_adapter_call(tmp_path: Path) -> None:
    dataset_dir = _make_target_delivery_fixture(tmp_path)
    provider_config = ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False)
    adapter = _TargetDeliveryAdapter(mark_live_api_triggered=True)
    run_dir = FinalResearchRunner(
        FinalResearchConfig(dataset_dir=dataset_dir, sample_size=70, provider=provider_config),
        adapter,
    ).run_and_write(tmp_path / "ranking-live-status")

    documents = [
        json.loads((run_dir / file_name).read_text(encoding="utf-8"))
        for file_name in (
            "config_snapshot.json",
            "seed_first_sample_audit.json",
            "holdout_safe_audit.json",
            "artifact_manifest.json",
            "ranking_runtime_summary.json",
        )
    ]
    report_payload = json.loads((run_dir / "final_research_report_payload.json").read_text(encoding="utf-8"))

    assert adapter.live_api_triggered is True
    assert all(document["sampling_status"] == "persisted_seed_first_formal_run" for document in documents)
    assert report_payload["run"]["sampling_status"] == "persisted_seed_first_formal_run"
    assert documents[3]["live_api_triggered"] is True
    assert "Persisted Seed-First Formal Run" in (run_dir / "report.html").read_text(encoding="utf-8")
    assert rebuild_final_research_report(run_dir) == run_dir / "report.html"


def test_probability_runtime_persists_probability_formal_status_after_adapter_call(tmp_path: Path) -> None:
    dataset_dir = _make_processed_fixture(tmp_path)
    provider_config = ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False)
    adapter = _TargetDeliveryAdapter(mark_live_api_triggered=True)
    run_dir = FinalResearchRunner(
        FinalResearchConfig(
            dataset_dir=dataset_dir,
            research_model=FinalResearchModel.PROBABILITY_V1,
            sample_size=4,
            provider=provider_config,
        ),
        adapter,
    ).run_and_write(tmp_path / "probability-live-status")

    documents = [
        json.loads((run_dir / file_name).read_text(encoding="utf-8"))
        for file_name in (
            "config_snapshot.json",
            "holdout_safe_audit.json",
            "artifact_manifest.json",
        )
    ]
    report_payload = json.loads((run_dir / "final_research_report_payload.json").read_text(encoding="utf-8"))
    report_html = (run_dir / "report.html").read_text(encoding="utf-8")

    assert adapter.live_api_triggered is True
    assert all(document["sampling_status"] == "persisted_probability_formal_run" for document in documents)
    assert report_payload["run"]["sampling_method"] == "source_scope_stratified_sample_v1"
    assert report_payload["run"]["sampling_status"] == "persisted_probability_formal_run"
    assert documents[2]["live_api_triggered"] is True
    assert "Persisted Probability Formal Run" in report_html
    assert "Persisted Seed-First Formal Run" not in report_html


def test_target_delivery_ranking_report_rebuild_is_deterministic(tmp_path: Path) -> None:
    dataset_dir = _make_target_delivery_fixture(tmp_path)
    provider_config = ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False)
    adapter = _TargetDeliveryAdapter(failed_user_id="u79")
    run_dir = FinalResearchRunner(
        FinalResearchConfig(dataset_dir=dataset_dir, sample_size=70, provider=provider_config),
        adapter,
    ).run_and_write(tmp_path / "ranking-rebuildable")
    calls_before_rebuild = len(adapter.calls)
    report_path = run_dir / "report.html"
    payload_path = run_dir / "final_research_report_payload.json"
    payload = FinalResearchRankingReportPayload.model_validate_json(payload_path.read_text(encoding="utf-8"))
    direct_report = FinalResearchReportWriter.render_payload(payload).encode()
    assert report_path.read_bytes() == direct_report
    preserved_artifacts = {
        path.name: path.read_bytes() for path in run_dir.iterdir() if path.is_file() and path != report_path
    }

    assert rebuild_final_research_report(run_dir) == report_path
    first_payload = payload_path.read_bytes()
    first_report = report_path.read_bytes()
    assert first_report == direct_report
    assert len(adapter.calls) == calls_before_rebuild

    assert rebuild_final_research_report(run_dir) == report_path
    assert payload_path.read_bytes() == first_payload
    assert report_path.read_bytes() == first_report
    assert {
        path.name: path.read_bytes() for path in run_dir.iterdir() if path.is_file() and path != report_path
    } == preserved_artifacts


def test_target_delivery_ranking_v3_formal_run_rebuild_preserves_legacy_artifact_contract(tmp_path: Path) -> None:
    dataset_dir = _make_target_delivery_fixture(tmp_path)
    provider_config = ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False)
    run_dir = FinalResearchRunner(
        FinalResearchConfig(dataset_dir=dataset_dir, sample_size=70, provider=provider_config),
        _TargetDeliveryAdapter(mark_live_api_triggered=True),
    ).run_and_write(tmp_path / "ranking-legacy-v3")
    payload_document = json.loads((run_dir / "final_research_report_payload.json").read_text(encoding="utf-8"))
    payload_document["schema_version"] = "final-research-ranking-report-payload-v3"
    payload_document.pop("sample_role_counts")
    payload_document.pop("field_lineage_catalog")
    payload_document.pop("user_field_trace_index")
    for field_name in ("field_lineage_catalog", "user_field_trace", "field_source_records"):
        payload_document["downloads"].pop(field_name)
    payload_path = run_dir / "final_research_report_payload.json"
    payload_path.write_text(json.dumps(payload_document, ensure_ascii=False) + "\n", encoding="utf-8")
    manifest_path = run_dir / "artifact_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for artifact_name in ("field_lineage_catalog", "user_field_trace", "field_source_records"):
        (run_dir / manifest["artifacts"].pop(artifact_name)).unlink()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False) + "\n", encoding="utf-8")
    users_path = run_dir / "final_research_users.json"
    users_document = json.loads(users_path.read_text(encoding="utf-8"))
    users_document["schema_version"] = "final-research-ranking-users-v3"
    users_document["links"] = payload_document["downloads"]
    users_path.write_text(json.dumps(users_document, ensure_ascii=False) + "\n", encoding="utf-8")

    assert rebuild_final_research_report(run_dir) == run_dir / "report.html"
    first_payload = payload_path.read_bytes()
    first_report = (run_dir / "report.html").read_bytes()
    assert rebuild_final_research_report(run_dir) == run_dir / "report.html"
    assert payload_path.read_bytes() == first_payload
    assert (run_dir / "report.html").read_bytes() == first_report

    rebuilt_document = json.loads(first_payload)
    payload = FinalResearchRankingReportPayloadV3.model_validate(rebuilt_document)
    html = first_report.decode()

    assert payload.run.sampling_method == "seed_first_research_sample_v1"
    assert payload.run.sampling_status == "persisted_seed_first_formal_run"
    assert "Persisted Seed-First Formal Run" in html
    assert rebuilt_document["schema_version"] == "final-research-ranking-report-payload-v3"
    assert "field_lineage_catalog" not in rebuilt_document
    assert "user_field_trace_index" not in rebuilt_document
    assert all(
        name not in manifest["artifacts"]
        for name in ("field_lineage_catalog", "user_field_trace", "field_source_records")
    )


def test_target_delivery_ranking_report_escapes_download_paths_in_html(tmp_path: Path) -> None:
    dataset_dir = _make_target_delivery_fixture(tmp_path)
    provider_config = ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False)
    run_dir = FinalResearchRunner(
        FinalResearchConfig(dataset_dir=dataset_dir, sample_size=70, provider=provider_config),
        _TargetDeliveryAdapter(),
    ).run_and_write(tmp_path / "ranking-download-escaping")
    payload = FinalResearchRankingReportPayload.model_validate_json(
        (run_dir / "final_research_report_payload.json").read_text(encoding="utf-8")
    )
    payload.downloads.csv = 'users" onmouseover="alert(1).csv'

    html = FinalResearchReportWriter.render_payload(payload)

    assert 'href="users&quot; onmouseover=&quot;alert(1).csv"' in html
    assert 'href="users" onmouseover="alert(1).csv"' not in html


@pytest.mark.parametrize(
    "corruption",
    [
        "missing_required",
        "unsupported_schema",
        "duplicate_payload_user",
        "duplicate_runtime_user",
        "count_mismatch",
        "sampling_status_mismatch",
        "diagnostic_boolean_string",
        "csv_unsafe_link",
        "duplicate_source_record",
        "source_value_mismatch",
        "source_evidence_mismatch",
        "trace_unsafe_locator",
        "unsafe_path",
    ],
)
def test_target_delivery_ranking_report_rebuild_rejects_invalid_evidence_before_publish(
    tmp_path: Path,
    corruption: str,
) -> None:
    dataset_dir = _make_target_delivery_fixture(tmp_path)
    provider_config = ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False)
    source_run = FinalResearchRunner(
        FinalResearchConfig(dataset_dir=dataset_dir, sample_size=70, provider=provider_config),
        _TargetDeliveryAdapter(failed_user_id="u79"),
    ).run_and_write(tmp_path / "ranking-valid")
    run_dir = tmp_path / f"ranking-invalid-{corruption}"
    shutil.copytree(source_run, run_dir)
    payload_path = run_dir / "final_research_report_payload.json"
    report_path = run_dir / "report.html"

    if corruption == "missing_required":
        (run_dir / "ranking_runtime_summary.json").unlink()
    elif corruption == "unsupported_schema":
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        payload["schema_version"] = "final-research-ranking-report-payload-v999"
        payload_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    elif corruption == "duplicate_payload_user":
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        payload["users"][1]["user_id"] = payload["users"][0]["user_id"]
        payload_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    elif corruption == "duplicate_runtime_user":
        outcomes_path = run_dir / "ranking_runtime_outcomes.csv"
        outcomes = _read_csv(outcomes_path)
        outcomes[1]["user_id"] = outcomes[0]["user_id"]
        _write_csv(outcomes_path, list(outcomes[0]), outcomes)
    elif corruption == "count_mismatch":
        summary_path = run_dir / "ranking_runtime_summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["counts"]["sample_users"] += 1
        summary_path.write_text(json.dumps(summary, ensure_ascii=False) + "\n", encoding="utf-8")
    elif corruption == "sampling_status_mismatch":
        manifest_path = run_dir / "artifact_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["sampling_status"] = "persisted_seed_first_formal_run"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False) + "\n", encoding="utf-8")
    elif corruption == "diagnostic_boolean_string":
        diagnostics_path = run_dir / "ranking_diagnostics_summary.json"
        diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
        diagnostics["recommendation_signal_inclusion"]["network_signals_in_formula"] = "false"
        diagnostics_path.write_text(json.dumps(diagnostics, ensure_ascii=False) + "\n", encoding="utf-8")
    elif corruption == "csv_unsafe_link":
        users_path = run_dir / "final_research_users.csv"
        users = _read_csv(users_path)
        users[0]["report_path"] = "../outside.html"
        _write_csv(users_path, list(users[0]), users)
    elif corruption in {"duplicate_source_record", "source_value_mismatch", "source_evidence_mismatch"}:
        source_path = run_dir / "field_source_records.json"
        source = json.loads(source_path.read_text(encoding="utf-8"))
        if corruption == "duplicate_source_record":
            source["records"].append(source["records"][0])
        elif corruption == "source_value_mismatch":
            source["records"][0]["interest_tags"] = ["tampered"]
        else:
            record = next(item for item in source["records"] if item["historical_tag_evidence"])
            record["historical_tag_evidence"] = []
        source_path.write_text(json.dumps(source, ensure_ascii=False) + "\n", encoding="utf-8")
    elif corruption == "trace_unsafe_locator":
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        payload["user_field_trace_index"]["u1"][0]["source_record_locator"]["relative_path"] = "../outside.json"
        payload_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
        trace_path = run_dir / "user_field_trace.json"
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        trace["users"]["u1"][0]["source_record_locator"]["relative_path"] = "../outside.json"
        trace_path.write_text(json.dumps(trace, ensure_ascii=False) + "\n", encoding="utf-8")
    else:
        manifest_path = run_dir / "artifact_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["artifacts"]["final_research_users_csv"] = "../outside.csv"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False) + "\n", encoding="utf-8")

    persisted_payload = payload_path.read_bytes()
    persisted_report = report_path.read_bytes()
    with pytest.raises((FileNotFoundError, ValueError, ValidationError)):
        rebuild_final_research_report(run_dir)

    assert payload_path.read_bytes() == persisted_payload
    assert report_path.read_bytes() == persisted_report


def test_target_delivery_ranking_provider_prompt_excludes_ranking_evidence(tmp_path: Path) -> None:
    dataset_dir = _make_processed_fixture(tmp_path)
    provider_config = ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False)
    client = _ScriptedProviderClient()
    provider = OpenAICompatibleDecisionAdapter(provider_config, client=client, sleep=lambda _delay: None)
    adapter = _RecordingAdapter(provider)

    FinalResearchRunner(
        FinalResearchConfig(
            dataset_dir=dataset_dir,
            sample_size=4,
            provider=provider_config,
        ),
        adapter,
    ).run_and_write(tmp_path / "ranking-prompt-runtime")

    assert adapter.calls
    assert all(call["peer_context"] == PeerContext() for call in adapter.calls)
    prompt_text = json.dumps(client.requests, ensure_ascii=False)
    for forbidden in (
        "base_network_relevance",
        "dynamic_network",
        "engaged_neighbor_count",
        "engaged_neighbor_signal",
        "historical_tag_affinity",
        "recommendation_score",
        "ranking_position",
        "target-holdout",
    ):
        assert forbidden not in prompt_text


def test_mocked_provider_final_research_runs_fixed_batches_and_continues_after_failure(tmp_path: Path) -> None:
    dataset_dir = _make_processed_fixture(tmp_path, user_count=80, dense_target_network=True)
    provider_config = ProviderLLMConfig(
        enabled=True,
        model="mock-model",
        require_live_env=False,
        max_retries=5,
        retry_backoff_seconds=0.0,
    )
    config = FinalResearchConfig(
        dataset_dir=dataset_dir,
        research_model=FinalResearchModel.PROBABILITY_V1,
        sample_size=70,
        random_seed=20260713,
        provider=provider_config,
    )

    def run(output_dir: Path) -> tuple[Path, _RecordingAdapter, _ScriptedProviderClient]:
        client = _ScriptedProviderClient()
        provider = OpenAICompatibleDecisionAdapter(provider_config, client=client, sleep=lambda _delay: None)
        adapter = _RecordingAdapter(provider)
        return FinalResearchRunner(config, adapter).run_and_write(output_dir), adapter, client

    first_output, first_adapter, first_client = run(tmp_path / "runtime-a")
    second_output, _second_adapter, _second_client = run(tmp_path / "runtime-b")

    manifest = json.loads((first_output / "artifact_manifest.json").read_text(encoding="utf-8"))
    runtime_artifacts = {
        name: relative_path for name, relative_path in manifest["artifacts"].items() if name.startswith("runtime_")
    }
    assert runtime_artifacts == {
        "runtime_actions": "runtime_actions.csv",
        "runtime_background_events": "runtime_background_events.csv",
        "runtime_decisions": "runtime_decisions.csv",
        "runtime_exposures": "runtime_exposures.csv",
        "runtime_provider_failures": "runtime_provider_failures.csv",
        "runtime_steps": "runtime_steps.csv",
        "runtime_summary": "runtime_summary.json",
    }
    assert manifest["manifest_version"] == "final-research-runtime-v1"
    assert manifest["live_api_triggered"] is False
    assert {
        name: manifest["artifacts"][name]
        for name in (
            "final_research_report",
            "final_research_report_payload",
            "final_research_users_csv",
            "final_research_users_json",
        )
    } == {
        "final_research_report": "report.html",
        "final_research_report_payload": "final_research_report_payload.json",
        "final_research_users_csv": "final_research_users.csv",
        "final_research_users_json": "final_research_users.json",
    }

    exposures = _read_csv(first_output / runtime_artifacts["runtime_exposures"])
    offline_scores = _read_csv(first_output / "offline_scores.csv")
    legacy_audit = json.loads((first_output / "holdout_safe_audit.json").read_text(encoding="utf-8"))
    decisions = _read_csv(first_output / runtime_artifacts["runtime_decisions"])
    actions = _read_csv(first_output / runtime_artifacts["runtime_actions"])
    backgrounds = _read_csv(first_output / runtime_artifacts["runtime_background_events"])
    failures = _read_csv(first_output / runtime_artifacts["runtime_provider_failures"])
    steps = _read_csv(first_output / runtime_artifacts["runtime_steps"])
    report_rows = _read_csv(first_output / manifest["artifacts"]["final_research_users_csv"])
    report_json = json.loads(
        (first_output / manifest["artifacts"]["final_research_users_json"]).read_text(encoding="utf-8")
    )
    report_payload = json.loads(
        (first_output / manifest["artifacts"]["final_research_report_payload"]).read_text(encoding="utf-8")
    )
    report_html = (first_output / manifest["artifacts"]["final_research_report"]).read_text(encoding="utf-8")

    assert len(exposures) == 70
    assert len(offline_scores) == 80
    assert {row["base_network_relevance"] for row in offline_scores} == {""}
    assert "base_network_relevance" not in legacy_audit
    assert "network_augmented_sample_audit" not in manifest["artifacts"]
    assert len({row["user_id"] for row in exposures}) == 70
    seed_rows = [row for row in exposures if row["is_seed"] == "true"]
    non_seed_rows = [row for row in exposures if row["is_seed"] == "false"]
    assert seed_rows
    assert non_seed_rows
    assert {row["time_step"] for row in seed_rows} == {"0"}
    assert {int(row["time_step"]) for row in non_seed_rows} <= set(range(1, 30))
    assert all(row["exposure_outcome"] == "target_exposed" for row in seed_rows)
    assert all(row["random_draw"] == "" for row in seed_rows)
    assert all(row["random_draw"] != "" for row in non_seed_rows)

    target_exposures = [row for row in exposures if row["exposure_outcome"] == "target_exposed"]
    assert len(first_adapter.calls) == len(target_exposures)
    assert len({call["profile"].user_id for call in first_adapter.calls}) == len(first_adapter.calls)  # type: ignore[union-attr]
    assert len(decisions) == len(actions) == len(target_exposures) - len(failures)
    assert len(backgrounds) == len(exposures) - len(target_exposures)
    assert len(failures) == 1
    assert failures[0]["failure_type"] == "TimeoutError"
    assert "sk-secret" not in json.dumps(failures)
    assert first_client.calls == len(first_adapter.calls) + 6
    failed_position = int(failures[0]["schedule_position"])
    assert any(int(row["schedule_position"]) > failed_position for row in decisions)

    assert len(report_rows) == len(report_json["users"]) == 70
    assert [row["user_id"] for row in report_rows] == [row["user_id"] for row in report_json["users"]]
    assert set(report_rows[0]) == set(report_json["users"][0])
    assert {row["result_status"] for row in report_rows} == {
        *(row["action"] for row in decisions),
        *("background_content" for _row in backgrounds),
        *("provider_failed" for _row in failures),
    }
    assert next(row for row in report_rows if row["result_status"] == "provider_failed")["provider_status"] == (
        "provider_failed"
    )
    assert all(row["assigned_step"] != "" for row in report_rows)
    assert all(row["sample_source_scope"] for row in report_rows)
    assert all(row["report_path"] == "report.html" for row in report_rows)
    assert all(row["manifest_path"] == "artifact_manifest.json" for row in report_rows)
    assert "nickname" in report_rows[0]
    assert "bio" in report_rows[0]
    assert "signature" in report_rows[0]
    assert "interest_tags" in report_rows[0]
    assert "historical_tags" in report_rows[0]
    assert "latent_attributes" in report_rows[0]
    assert "brand_attitude" not in report_rows[0]
    assert "authorization" not in report_rows[0]
    assert report_payload["schema_version"] == "final-research-report-payload-v2"
    assert report_payload["core_objects"] == ["TargetVideo", "ResearchUser", "PlatformRecommendationModel"]
    assert [stage["key"] for stage in report_payload["run_funnel"]] == [
        "offline_scoring",
        "research_sample",
        "recommendation_opportunity",
        "target_exposure",
        "provider_decision",
        "engagement",
        "background_content",
    ]
    assert report_payload["recommendation_explanation"]["seed_example"]["random_draw"] is None
    assert report_payload["recommendation_explanation"]["non_seed_example"]["random_draw"] is not None
    assert len(report_payload["user_traces"]) == len(report_rows)
    assert report_payload["decision_contract"]["persisted_context_label"] == "重建的决策上下文"
    assert report_payload["downloads"]["csv"] == "final_research_users.csv"
    assert report_payload["downloads"]["users_json"] == "final_research_users.json"
    assert 'data-testid="final-research-report"' in report_html
    assert "final_research_users.csv" in report_html
    assert "final_research_users.json" in report_html
    assert "artifact_manifest.json" in report_html
    assert 'data-testid="funnel-section"' in report_html
    assert 'data-testid="recommendation-section"' in report_html
    assert 'data-testid="decision-section"' in report_html
    non_seed_target_exposures = sum(row["exposure_outcome"] == "target_exposed" for row in non_seed_rows)
    expected_exposure_breakdown = (
        f"{len(target_exposures)} 次 Provider Decision 调用来自 {len(seed_rows)} 个强制 seed 曝光和 "
        f"{non_seed_target_exposures} 个普通用户抽签曝光。"
    )
    assert 'data-testid="exposure-breakdown"' in report_html
    assert expected_exposure_breakdown in report_html

    assert len(steps) == 30
    assert steps[0]["time_step"] == "0"
    assert int(steps[0]["assigned_users"]) == len(seed_rows)
    assert sum(int(row["assigned_users"]) for row in steps[1:]) == len(non_seed_rows)
    repeated_batch = next(
        time_step for time_step in range(1, 30) if sum(int(row["time_step"]) == time_step for row in non_seed_rows) > 1
    )
    repeated_batch_rows = [row for row in non_seed_rows if int(row["time_step"]) == repeated_batch]
    assert len({row["engaged_neighbor_count"] for row in repeated_batch_rows}) == 1

    boosted_call = next(
        call
        for call in first_adapter.calls
        if call["peer_context"].engaged_neighbors > 0  # type: ignore[union-attr]
    )
    boosted_profile = boosted_call["profile"]
    boosted_peer = boosted_call["peer_context"]
    boosted_exposure = next(row for row in exposures if row["user_id"] == boosted_profile.user_id)  # type: ignore[union-attr]
    expected_dynamic = min(
        1.0,
        float(boosted_exposure["base_network_score"]) + 0.2 * boosted_peer.engaged_neighbors,  # type: ignore[union-attr]
    )
    assert float(boosted_exposure["dynamic_network_score"]) == pytest.approx(expected_dynamic)
    assert float(boosted_exposure["recommendation_score"]) == pytest.approx(
        0.7 * expected_dynamic + 0.3 * float(boosted_exposure["historical_tag_affinity"]),
        abs=1e-6,
    )

    first_call = first_adapter.calls[0]
    assert first_call["post"] == PostContent(
        post_id=TARGET_VIDEO_ID,
        text="当高端酒店开始限塑",
        topic_tags=["锦江ESG", "乡村振兴"],
    )
    assert first_call["platform_context"].feed_ranking_weight == 1.0  # type: ignore[union-attr]
    prompt_text = json.dumps(first_client.requests, ensure_ascii=False)
    for forbidden in (
        "recommendation_score",
        "historical_tag_affinity",
        "latent_class",
        "brand_attitude",
        "like_tendency",
        "comment_tendency",
        "share_tendency",
        "age_26_35",
        "female",
    ):
        assert forbidden not in prompt_text

    artifact_text = "\n".join(path.read_text(encoding="utf-8") for path in first_output.iterdir() if path.is_file())
    assert artifact_has_forbidden_terms(artifact_text) is False
    assert "sk-secret" not in artifact_text
    for relative_path in [*manifest["artifacts"].values(), "artifact_manifest.json"]:
        assert (first_output / relative_path).read_bytes() == (second_output / relative_path).read_bytes()


def test_final_research_report_rebuild_is_deterministic_and_upgrades_v1_payload(tmp_path: Path) -> None:
    dataset_dir = _make_processed_fixture(tmp_path)
    provider_config = ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False)
    client = _ScriptedProviderClient()
    provider = OpenAICompatibleDecisionAdapter(provider_config, client=client, sleep=lambda _delay: None)
    adapter = _RecordingAdapter(provider)
    run_dir = FinalResearchRunner(
        FinalResearchConfig(
            dataset_dir=dataset_dir,
            research_model=FinalResearchModel.PROBABILITY_V1,
            sample_size=4,
            provider=provider_config,
        ),
        adapter,
    ).run_and_write(tmp_path / "rebuildable-run")
    calls_before_rebuild = len(adapter.calls)
    payload_path = run_dir / "final_research_report_payload.json"
    preserved_artifacts = {
        name: (run_dir / name).read_bytes()
        for name in ("final_research_users.csv", "final_research_users.json", "artifact_manifest.json")
    }
    legacy_payload = json.loads(payload_path.read_text(encoding="utf-8"))
    legacy_payload["schema_version"] = "final-research-report-payload-v1"
    for field_name in (
        "run_funnel",
        "methodology_flow",
        "video_usage",
        "sampling_explanation",
        "comment_network_explanation",
        "recommendation_explanation",
        "batch_explanation",
        "decision_contract",
        "outcome_explanations",
        "dynamic_neighbor_summary",
        "user_traces",
    ):
        legacy_payload.pop(field_name)
    payload_path.write_text(json.dumps(legacy_payload, ensure_ascii=False) + "\n", encoding="utf-8")

    report_path = rebuild_final_research_report(run_dir)
    first_payload = payload_path.read_bytes()
    first_html = report_path.read_bytes()
    rebuilt_payload = json.loads(first_payload)

    assert report_path == run_dir / "report.html"
    assert rebuilt_payload["schema_version"] == "final-research-report-payload-v2"
    assert len(adapter.calls) == calls_before_rebuild

    assert rebuild_final_research_report(run_dir) == report_path
    assert payload_path.read_bytes() == first_payload
    assert report_path.read_bytes() == first_html
    assert {
        name: (run_dir / name).read_bytes()
        for name in ("final_research_users.csv", "final_research_users.json", "artifact_manifest.json")
    } == preserved_artifacts


def test_final_research_report_rebuild_rejects_inconsistent_summary_before_replacing_report(tmp_path: Path) -> None:
    dataset_dir = _make_processed_fixture(tmp_path)
    provider_config = ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False)
    provider = OpenAICompatibleDecisionAdapter(
        provider_config,
        client=_ScriptedProviderClient(),
        sleep=lambda _delay: None,
    )
    run_dir = FinalResearchRunner(
        FinalResearchConfig(
            dataset_dir=dataset_dir,
            research_model=FinalResearchModel.PROBABILITY_V1,
            sample_size=4,
            provider=provider_config,
        ),
        _RecordingAdapter(provider),
    ).run_and_write(tmp_path / "inconsistent-run")
    payload_path = run_dir / "final_research_report_payload.json"
    report_path = run_dir / "report.html"
    original_payload = payload_path.read_bytes()
    original_report = report_path.read_bytes()
    summary_path = run_dir / "runtime_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["counts"]["sample_users"] += 1
    summary_path.write_text(json.dumps(summary, ensure_ascii=False) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="sample_users"):
        rebuild_final_research_report(run_dir)

    assert payload_path.read_bytes() == original_payload
    assert report_path.read_bytes() == original_report


def test_final_research_report_rebuild_rejects_inconsistent_schedule_contract(tmp_path: Path) -> None:
    dataset_dir = _make_processed_fixture(tmp_path)
    provider_config = ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False)
    provider = OpenAICompatibleDecisionAdapter(
        provider_config,
        client=_ScriptedProviderClient(),
        sleep=lambda _delay: None,
    )
    run_dir = FinalResearchRunner(
        FinalResearchConfig(
            dataset_dir=dataset_dir,
            research_model=FinalResearchModel.PROBABILITY_V1,
            sample_size=4,
            provider=provider_config,
        ),
        _RecordingAdapter(provider),
    ).run_and_write(tmp_path / "invalid-schedule-run")
    summary_path = run_dir / "runtime_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["schedule_method"] = "tampered_schedule"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="schedule_method"):
        rebuild_final_research_report(run_dir)


@pytest.mark.parametrize(
    "corruption",
    [
        "missing_required",
        "unsupported_schema",
        "duplicate_user",
        "user_count",
        "missing_download",
        "source_scope_counts",
        "aggregates",
        "trends",
    ],
)
def test_final_research_report_rebuild_rejects_invalid_persisted_evidence(
    tmp_path: Path,
    corruption: str,
) -> None:
    dataset_dir = _make_processed_fixture(tmp_path)
    provider_config = ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False)
    provider = OpenAICompatibleDecisionAdapter(
        provider_config,
        client=_ScriptedProviderClient(),
        sleep=lambda _delay: None,
    )
    source_run = FinalResearchRunner(
        FinalResearchConfig(
            dataset_dir=dataset_dir,
            research_model=FinalResearchModel.PROBABILITY_V1,
            sample_size=4,
            provider=provider_config,
        ),
        _RecordingAdapter(provider),
    ).run_and_write(tmp_path / "valid-run")
    run_dir = tmp_path / f"invalid-{corruption}"
    shutil.copytree(source_run, run_dir)
    payload_path = run_dir / "final_research_report_payload.json"
    report_path = run_dir / "report.html"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))

    if corruption == "missing_required":
        (run_dir / "runtime_summary.json").unlink()
    elif corruption == "unsupported_schema":
        payload["schema_version"] = "final-research-report-payload-v999"
        payload_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    elif corruption == "duplicate_user":
        payload["users"][1]["user_id"] = payload["users"][0]["user_id"]
        payload_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    elif corruption == "user_count":
        payload["run"]["sample_size"] += 1
        payload_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    elif corruption == "missing_download":
        (run_dir / "final_research_users.csv").unlink()
    elif corruption == "source_scope_counts":
        payload["sample_summary"]["source_scope_counts"] = {"tampered-scope": len(payload["users"])}
        payload_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    elif corruption == "aggregates":
        payload["aggregates"]["action_distribution"][0]["value"] += 1
        payload_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    else:
        payload["trends"][0]["assigned_users"] += 1
        payload_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")

    persisted_payload = payload_path.read_bytes()
    persisted_report = report_path.read_bytes()
    with pytest.raises((FileNotFoundError, ValueError, ValidationError)):
        rebuild_final_research_report(run_dir)

    assert payload_path.read_bytes() == persisted_payload
    assert report_path.read_bytes() == persisted_report


def test_final_research_report_rebuild_rejects_artifact_symlink_outside_run(tmp_path: Path) -> None:
    dataset_dir = _make_processed_fixture(tmp_path)
    provider_config = ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False)
    provider = OpenAICompatibleDecisionAdapter(
        provider_config,
        client=_ScriptedProviderClient(),
        sleep=lambda _delay: None,
    )
    run_dir = FinalResearchRunner(
        FinalResearchConfig(
            dataset_dir=dataset_dir,
            research_model=FinalResearchModel.PROBABILITY_V1,
            sample_size=4,
            provider=provider_config,
        ),
        _RecordingAdapter(provider),
    ).run_and_write(tmp_path / "symlink-run")
    csv_path = run_dir / "final_research_users.csv"
    outside_path = tmp_path / "outside.csv"
    outside_path.write_text(csv_path.read_text(encoding="utf-8"), encoding="utf-8")
    csv_path.unlink()
    csv_path.symlink_to(outside_path)

    with pytest.raises(ValueError, match="outside the run directory"):
        rebuild_final_research_report(run_dir)


def test_final_research_report_dynamic_neighbor_activation_requires_actual_boost(tmp_path: Path) -> None:
    dataset_dir = _make_processed_fixture(tmp_path, user_count=80, dense_target_network=True)
    provider_config = ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False)
    provider = OpenAICompatibleDecisionAdapter(
        provider_config,
        client=_ScriptedProviderClient(),
        sleep=lambda _delay: None,
    )
    run_dir = FinalResearchRunner(
        FinalResearchConfig(
            dataset_dir=dataset_dir,
            research_model=FinalResearchModel.PROBABILITY_V1,
            sample_size=70,
            neighbor_boost=0.0,
            provider=provider_config,
        ),
        _RecordingAdapter(provider),
    ).run_and_write(tmp_path / "zero-neighbor-boost-run")
    payload = json.loads((run_dir / "final_research_report_payload.json").read_text(encoding="utf-8"))
    neighbor_summary = payload["dynamic_neighbor_summary"]

    assert neighbor_summary["users_with_positive_engaged_neighbor_count"] > 0
    assert neighbor_summary["maximum_actual_boost"] == 0.0
    assert neighbor_summary["activated"] is False
    assert "未实际生效" in neighbor_summary["explanation"]
    assert "均为 0" not in neighbor_summary["explanation"]


def test_final_research_report_uses_configured_formula_and_interest_tags(tmp_path: Path) -> None:
    dataset_dir = _make_processed_fixture(tmp_path)
    user_rows = _read_csv(dataset_dir / "users.csv")
    user_rows[0]["interest_tags"] = json.dumps(["hotel"])
    _write_csv(dataset_dir / "users.csv", list(user_rows[0]), user_rows)
    output = FinalResearchRunner(
        FinalResearchConfig(
            dataset_dir=dataset_dir,
            research_model=FinalResearchModel.PROBABILITY_V1,
            sample_size=4,
            network_weight=0.65,
            tag_affinity_weight=0.35,
            neighbor_boost=0.15,
        ),
        FailingIfCalledAdapter(),
    ).run_and_write(tmp_path / "configured-report")

    report_html = (output / "report.html").read_text(encoding="utf-8")
    report_rows = _read_csv(output / "final_research_users.csv")
    assert "0.65 network + 0.35 historical tag affinity" in report_html
    assert "min(1, base + 0.15 × engaged direct neighbors)" in report_html
    assert json.loads(next(row for row in report_rows if row["user_id"] == "u1")["interest_tags"]) == ["hotel"]


@pytest.mark.parametrize(
    "research_model",
    [FinalResearchModel.PROBABILITY_V1, FinalResearchModel.TARGET_DELIVERY_RANKING_V2],
)
def test_final_research_does_not_convert_unexpected_adapter_errors_to_provider_failures(
    tmp_path: Path,
    research_model: FinalResearchModel,
) -> None:
    class UnexpectedFailureAdapter(LLMDecisionAdapter):
        def decide(
            self,
            post: PostContent,
            profile: UserProfile,
            peer_context: PeerContext,
            platform_context: PlatformContext | None = None,
            time_step: int = 0,
        ) -> EngageDecision:
            del post, profile, peer_context, platform_context, time_step
            raise AssertionError("adapter programming defect")

    dataset_dir = _make_processed_fixture(tmp_path)
    config = FinalResearchConfig(
        dataset_dir=dataset_dir,
        research_model=research_model,
        sample_size=4,
        provider=ProviderLLMConfig(enabled=True, require_live_env=False),
    )

    with pytest.raises(AssertionError, match="adapter programming defect"):
        FinalResearchRunner(config, UnexpectedFailureAdapter()).run_and_write(
            tmp_path / f"failed-runtime-{research_model.value}"
        )

    assert not (tmp_path / f"failed-runtime-{research_model.value}" / "artifact_manifest.json").exists()


def test_final_research_config_rejects_missing_target_and_oversized_sample(tmp_path: Path) -> None:
    dataset_dir = _make_processed_fixture(tmp_path)
    rows = list(csv.DictReader((dataset_dir / "videos.csv").open(encoding="utf-8", newline="")))
    _write_csv(dataset_dir / "videos.csv", list(rows[0]), [row for row in rows if row["video_id"] != TARGET_VIDEO_ID])

    with pytest.raises(ValidationError, match="target video"):
        FinalResearchConfig(dataset_dir=dataset_dir, sample_size=4)

    dataset_dir = _make_processed_fixture(tmp_path / "fresh")
    with pytest.raises(ValidationError, match="sample_size"):
        FinalResearchConfig(dataset_dir=dataset_dir, sample_size=7)
    with pytest.raises(ValidationError, match="requires sample_size >= 2"):
        FinalResearchConfig(dataset_dir=dataset_dir, sample_size=1)
    assert (
        FinalResearchConfig(
            dataset_dir=dataset_dir,
            sample_size=1,
            research_model=FinalResearchModel.PROBABILITY_V1,
        ).sample_size
        == 1
    )

    with pytest.raises(ValidationError, match="must sum to 1.0"):
        FinalResearchConfig(dataset_dir=dataset_dir, sample_size=4, network_weight=0.8, tag_affinity_weight=0.3)

    with pytest.raises(ValidationError, match="fail_closed_action=raise"):
        FinalResearchConfig(
            dataset_dir=dataset_dir,
            sample_size=4,
            provider=ProviderLLMConfig(enabled=True, fail_closed_action=FailClosedAction.NO_ENGAGE),
        )

    with pytest.raises(ValidationError, match="horizon=30"):
        FinalResearchConfig(
            dataset_dir=dataset_dir,
            sample_size=4,
            horizon=29,
            provider=ProviderLLMConfig(enabled=True),
        )

    with pytest.raises(ValidationError, match="jinjiang-green-marketing-prompt-v2"):
        FinalResearchConfig(
            dataset_dir=dataset_dir,
            sample_size=4,
            provider=ProviderLLMConfig(enabled=True, prompt_version="other-prompt"),
        )

    ranking_config = FinalResearchConfig(
        dataset_dir=dataset_dir,
        sample_size=4,
        provider=ProviderLLMConfig(enabled=True, require_live_env=False),
    )
    assert ranking_config.research_model is FinalResearchModel.TARGET_DELIVERY_RANKING_V2
