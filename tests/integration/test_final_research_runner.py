from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from llm_abm_sim import (
    FinalResearchConfig,
    FinalResearchModel,
    FinalResearchRunner,
    ResearchUser,
    rebuild_final_research_report,
)
from llm_abm_sim.decision import (
    CachedDecisionAdapter,
    EngageDecision,
    InMemoryDecisionCache,
    LLMDecisionAdapter,
    RuleBasedDecisionAdapter,
)
from llm_abm_sim.field_lineage_trace import FieldLineageDefinition, UserFieldTrace, field_lineage_coverage_audit
from llm_abm_sim.final_research_report import (
    FinalResearchRankingReportPayload,
    FinalResearchRankingReportPayloadV3,
    FinalResearchRankingReportPayloadV5,
    FinalResearchReportWriter,
    RankingV5ExpandEvidence,
    _validate_persisted_ranking_report,
)
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
V5_DECISION_DOWNLOAD_FIELDS = (
    "runtime_decisions",
    "runtime_actions",
    "runtime_provider_failures",
    "ranking_runtime_outcomes",
    "ranking_runtime_summary",
)
V5_DECISION_SUMMARY_FIELDS = (
    "decision_execution_mode",
    "decision_source_counts",
    "action_counts",
    "terminal_counts",
    "degeneracy_flags",
    "live_api_triggered",
)
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


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")


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


def test_jinjiang_research_user_v5_rejects_interest_tags() -> None:
    with pytest.raises(ValidationError, match="interest_tags"):
        ResearchUser.model_validate(
            {
                "user_id": "u1",
                "interest_tags": ["legacy"],
                "latent_attributes": _latent_row(1),
            }
        )


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


_PROMPT_GLOBAL_INFLUENCE = re.compile(r"全平台影响力：[^（]+（([0-9]+(?:\.[0-9]+)?)）")


class _TargetDeliveryProviderClient:
    def __init__(
        self,
        *,
        failed_user_id: str | None = None,
        engage_all: bool = False,
        engage_seed_user: bool = True,
        cycle_actions: bool = False,
    ) -> None:
        self.failed_user_id = failed_user_id
        self.engage_all = engage_all
        self.engage_seed_user = engage_seed_user
        self.cycle_actions = cycle_actions
        self.calls: list[dict[str, object]] = []

    def create_response(self, messages: list[dict[str, str]], model: str) -> dict[str, object]:
        prompt = messages[-1]["content"]
        match = _PROMPT_GLOBAL_INFLUENCE.search(prompt)
        if match is None:
            raise AssertionError("fixture prompt must contain the observed global influence score")
        user_id = f"u{round(float(match.group(1)) * 10)}"
        self.calls.append({"user_id": user_id, "messages": messages, "model": model})
        if user_id == self.failed_user_id:
            raise TimeoutError("mocked exhausted provider failure with sk-secret")
        if self.cycle_actions:
            action = ("like", "comment", "share", "ignore")[(len(self.calls) - 1) % 4]
        elif self.engage_all or (self.engage_seed_user and user_id == "u80"):
            action = "like"
        else:
            action = "ignore"
        return {
            "engage": action != "ignore",
            "probability": 0.9 if action != "ignore" else 0.1,
            "reason": "controlled deterministic provider decision",
            "confidence": 1.0,
            "action": action,
        }


def _TargetDeliveryAdapter(
    *,
    failed_user_id: str | None = None,
    engage_all: bool = False,
    engage_seed_user: bool = True,
    cycle_actions: bool = False,
) -> OpenAICompatibleDecisionAdapter:
    client = _TargetDeliveryProviderClient(
        failed_user_id=failed_user_id,
        engage_all=engage_all,
        engage_seed_user=engage_seed_user,
        cycle_actions=cycle_actions,
    )
    return OpenAICompatibleDecisionAdapter(
        ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False),
        client=client,
        sleep=lambda _delay: None,
    )


def _target_delivery_client(adapter: OpenAICompatibleDecisionAdapter) -> _TargetDeliveryProviderClient:
    assert isinstance(adapter.client, _TargetDeliveryProviderClient)
    return adapter.client


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

    def run(output_dir: Path) -> tuple[Path, OpenAICompatibleDecisionAdapter]:
        adapter = _TargetDeliveryAdapter(failed_user_id="u79")
        return FinalResearchRunner(config, adapter).run_and_write(output_dir), adapter

    first_output, first_adapter = run(tmp_path / "ranking-runtime-a")
    second_output, second_adapter = run(tmp_path / "ranking-runtime-b")
    first_adapter_calls = _target_delivery_client(first_adapter).calls
    second_adapter_calls = _target_delivery_client(second_adapter).calls

    manifest = json.loads((first_output / "artifact_manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == "final-research-ranking-runtime-v3"
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
    assert len(first_adapter_calls) == len(exposed_outcomes) == manifest["decision_adapter_calls"]
    assert len({row["user_id"] for row in exposed_outcomes}) == len(exposed_outcomes)
    assert len(first_adapter_calls) <= 600
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
    neutral_peer_summary = "邻居曝光：0；邻居互动：0；互动比例：0.00"
    assert all(neutral_peer_summary in json.dumps(call["messages"], ensure_ascii=False) for call in first_adapter_calls)
    assert all(
        neutral_peer_summary in json.dumps(call["messages"], ensure_ascii=False) for call in second_adapter_calls
    )

    assert summary["runtime_version"] == "final-research-ranking-runtime-v3"
    assert summary["schedule_method"] == "global_stable_reranking_top20"
    assert summary["delivery_capacity"] == 20
    assert summary["ranking_formula"] == (
        "0.50 * base_network_relevance + 0.30 * engaged_neighbor_signal + 0.20 * historical_tag_affinity"
    )
    assert summary["engaged_neighbor_formula"] == "min(1, engaged_neighbor_count / 3)"
    assert summary["maximum_target_exposures"] == 600
    assert "background_impressions" not in summary["counts"]
    assert summary["counts"]["decision_adapter_calls"] == len(first_adapter_calls)
    assert ranking_diagnostics["schema_version"] == "ranking-diagnostics-v2"
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
    assert len(first_adapter_calls) == summary["counts"]["decision_adapter_calls"]

    assert report_payload["schema_version"] == "final-research-ranking-report-payload-v5"
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
    prompt_inputs = json.dumps([call["messages"] for call in first_adapter_calls], ensure_ascii=False)
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


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("like_count", None),
        ("comment_count", ""),
        ("share_count", "-1"),
        ("collect_count", "1.5"),
        ("like_count", "not-a-count"),
    ],
)
def test_target_aggregate_reference_rejects_invalid_raw_counts(
    tmp_path: Path,
    field_name: str,
    invalid_value: str | None,
) -> None:
    dataset_dir = _make_processed_fixture(tmp_path)
    video_rows = _read_csv(dataset_dir / "videos.csv")
    fieldnames = list(video_rows[0])
    if invalid_value is None:
        fieldnames.remove(field_name)
        for row in video_rows:
            row.pop(field_name)
    else:
        target_row = next(row for row in video_rows if row["video_id"] == TARGET_VIDEO_ID)
        target_row[field_name] = invalid_value
    _write_csv(dataset_dir / "videos.csv", fieldnames, video_rows)

    with pytest.raises(
        ValueError,
        match=rf"videos.csv target {field_name} must be a non-negative integer",
    ):
        FinalResearchRunner(
            FinalResearchConfig(dataset_dir=dataset_dir, sample_size=4),
            FailingIfCalledAdapter(),
        ).run_and_write(tmp_path / "invalid-aggregate-count")


def test_target_aggregate_counts_are_post_runtime_diagnostic_only(tmp_path: Path) -> None:
    first_counts = {
        "like_count": 101,
        "comment_count": 202,
        "share_count": 303,
        "collect_count": 404,
    }
    second_counts = {
        "like_count": 901,
        "comment_count": 802,
        "share_count": 703,
        "collect_count": 604,
    }

    def run_variant(name: str, counts: dict[str, int]) -> tuple[Path, OpenAICompatibleDecisionAdapter]:
        dataset_dir = _make_processed_fixture(tmp_path / name, user_count=6, dense_target_network=True)
        video_rows = _read_csv(dataset_dir / "videos.csv")
        target_row = next(row for row in video_rows if row["video_id"] == TARGET_VIDEO_ID)
        target_row.update({field_name: str(value) for field_name, value in counts.items()})
        _write_csv(dataset_dir / "videos.csv", list(video_rows[0]), video_rows)
        adapter = _TargetDeliveryAdapter()
        output = FinalResearchRunner(
            FinalResearchConfig(
                dataset_dir=dataset_dir,
                sample_size=6,
                provider=ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False),
            ),
            adapter,
        ).run_and_write(tmp_path / f"{name}-run")
        return output, adapter

    first_output, first_adapter = run_variant("aggregate-a", first_counts)
    second_output, second_adapter = run_variant("aggregate-b", second_counts)

    def expected_reference(counts: dict[str, int]) -> dict[str, object]:
        return {
            "source_artifact": "videos.csv",
            "record_key": {"video_id": TARGET_VIDEO_ID},
            **counts,
            "real_exposure_denominator_available": False,
            "user_level_attribution_available": False,
            "action_mutual_exclusivity_known": False,
            "diagnostic_only": True,
        }

    first_holdout = json.loads((first_output / "top20_holdout_diagnostic.json").read_text(encoding="utf-8"))
    second_holdout = json.loads((second_output / "top20_holdout_diagnostic.json").read_text(encoding="utf-8"))
    first_reference = first_holdout.pop("target_aggregate_engagement_reference")
    second_reference = second_holdout.pop("target_aggregate_engagement_reference")
    assert first_reference == expected_reference(first_counts)
    assert second_reference == expected_reference(second_counts)
    assert first_holdout == second_holdout

    first_diagnostics = json.loads((first_output / "ranking_diagnostics.json").read_text(encoding="utf-8"))
    second_diagnostics = json.loads((second_output / "ranking_diagnostics.json").read_text(encoding="utf-8"))
    assert (
        first_diagnostics["historical_top20_diagnostic"].pop("target_aggregate_engagement_reference") == first_reference
    )
    assert (
        second_diagnostics["historical_top20_diagnostic"].pop("target_aggregate_engagement_reference")
        == second_reference
    )
    assert first_diagnostics == second_diagnostics

    first_payload = json.loads((first_output / "final_research_report_payload.json").read_text(encoding="utf-8"))
    second_payload = json.loads((second_output / "final_research_report_payload.json").read_text(encoding="utf-8"))
    assert (
        first_payload["ranking_diagnostics"]["historical_top20_diagnostic"].pop("target_aggregate_engagement_reference")
        == first_reference
    )
    assert (
        second_payload["ranking_diagnostics"]["historical_top20_diagnostic"].pop(
            "target_aggregate_engagement_reference"
        )
        == second_reference
    )
    assert first_payload == second_payload

    first_report = (first_output / "report.html").read_text(encoding="utf-8")
    assert 'data-testid="target-aggregate-engagement-reference"' in first_report
    assert 'data-testid="target-aggregate-engagement-reference-table"' in first_report
    assert f"record_key.video_id={TARGET_VIDEO_ID}" in first_report
    for field_name, value in first_counts.items():
        assert f"<code>{field_name}</code>" in first_report
        assert f"<td>{value:,}</td>" in first_report
    assert "没有真实曝光分母" in first_report
    assert "不能关联到具体用户" in first_report
    assert "无法确认四类互动是否互斥" in first_report
    assert "仅用于诊断背景" in first_report
    assert 'data-testid="target-aggregate-reference-chart"' not in first_report
    assert 'data-testid="target-aggregate-benchmark-score"' not in first_report
    assert 'data-testid="target-aggregate-calibration-conclusion"' not in first_report

    for artifact_name in (
        "target_video_snapshot.json",
        "sample_manifest.csv",
        "sample_manifest.json",
        "seed_first_sample_audit.json",
        "offline_scores.csv",
        "ranking_runtime_candidates.csv",
        "ranking_runtime_outcomes.csv",
        "runtime_decisions.csv",
        "runtime_actions.csv",
    ):
        assert (first_output / artifact_name).read_bytes() == (second_output / artifact_name).read_bytes()
    assert _target_delivery_client(first_adapter).calls == _target_delivery_client(second_adapter).calls


def test_target_delivery_ranking_v5_excludes_interest_contract_and_is_validation_only(tmp_path: Path) -> None:
    dataset_dir = _make_processed_fixture(tmp_path, user_count=6, dense_target_network=True)
    user_rows = _read_csv(dataset_dir / "users.csv")
    for row in user_rows:
        row.pop("interest_tags")
    user_rows[0]["nickname"] = "绿色旅行用户"
    user_rows[0]["bio"] = "酒店环保内容"
    user_rows[0]["signature"] = "锦江ESG"
    _write_csv(dataset_dir / "users.csv", list(user_rows[0]), user_rows)
    adapter = _TargetDeliveryAdapter()

    output = FinalResearchRunner(
        FinalResearchConfig(
            dataset_dir=dataset_dir,
            sample_size=6,
            provider=ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False),
        ),
        adapter,
    ).run_and_write(tmp_path / "ranking-v5-contract")

    manifest = json.loads((output / "artifact_manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((output / "ranking_runtime_summary.json").read_text(encoding="utf-8"))
    diagnostics = json.loads((output / "ranking_diagnostics.json").read_text(encoding="utf-8"))
    diagnostics_summary = json.loads((output / "ranking_diagnostics_summary.json").read_text(encoding="utf-8"))
    payload = json.loads((output / "final_research_report_payload.json").read_text(encoding="utf-8"))
    users_document = json.loads((output / "final_research_users.json").read_text(encoding="utf-8"))
    config_snapshot = json.loads((output / "config_snapshot.json").read_text(encoding="utf-8"))
    expected_target_evidence = {
        "status": "persisted",
        "formal_research_evidence": False,
    }

    assert manifest["manifest_version"] == "final-research-ranking-runtime-v3"
    assert summary["runtime_version"] == "final-research-ranking-runtime-v3"
    assert diagnostics["schema_version"] == "ranking-diagnostics-v2"
    assert diagnostics_summary["schema_version"] == "ranking-diagnostics-summary-v2"
    assert payload["schema_version"] == "final-research-ranking-report-payload-v5"
    assert users_document["schema_version"] == "final-research-ranking-users-v5"
    assert config_snapshot["provider"]["prompt_version"] == "jinjiang-green-marketing-prompt-v3"
    assert summary["provider_metadata"]["prompt_version"] == "jinjiang-green-marketing-prompt-v3"
    assert manifest["sampling_status"] == summary["sampling_status"] == "validation_run"
    assert payload["run"]["sampling_status"] == "validation_run"
    assert manifest["evidence_state"] == summary["evidence_state"] == payload["evidence_state"]
    assert payload["evidence_state"]["schema_version"] == "ranking-v5-expand-evidence-v1"
    assert payload["evidence_state"]["contract_stage"] == "validation_expand"
    assert payload["evidence_state"]["target_aggregate_engagement_reference"] == expected_target_evidence
    assert payload["evidence_state"]["production_deploy_eligible"] is False
    decision_evidence = payload["evidence_state"]["decision_execution_evidence"]
    assert decision_evidence["schema_version"] == "final-research-decision-execution-evidence-v1"
    assert decision_evidence["status"] == "persisted"
    assert decision_evidence["formal_research_evidence"] is False
    assert decision_evidence["decision_execution_mode"] == "mock_provider"
    assert decision_evidence["adapter_chain"] == ["openai_compatible"]
    assert decision_evidence["decision_source_counts"] == {"provider": 6}
    assert decision_evidence["action_counts"] == {"like": 0, "comment": 0, "share": 0, "ignore": 6}
    assert decision_evidence["terminal_counts"] == {
        "sample_users": 6,
        "exposed_users": 6,
        "decided_users": 6,
        "provider_failed": 0,
        "below_delivery_capacity": 0,
    }
    assert decision_evidence["live_api_triggered"] is False
    assert decision_evidence["sampling_status"] == "validation_run"
    assert decision_evidence["degeneracy_flags"] == {
        "all_decisions_ignore": True,
        "single_action_only": True,
        "no_engagement_feedback": True,
    }
    assert decision_evidence["provider_metadata"]["adapter"] == "openai_compatible"
    crossed_evidence_state = {
        **payload["evidence_state"],
        "target_aggregate_engagement_reference": {
            "status": "pending",
            "formal_research_evidence": False,
        },
    }
    with pytest.raises(ValidationError, match="persisted Decision evidence requires persisted target aggregate"):
        RankingV5ExpandEvidence.model_validate(crossed_evidence_state)
    assert "interest_tags" not in payload["prompt_contract"]["allowed_profile_fields"]
    assert all(
        "interest_tags" not in json.dumps(call["messages"], ensure_ascii=False)
        for call in _target_delivery_client(adapter).calls
    )
    assert any(user["historical_tags"] for user in payload["users"])

    v5_user_artifacts = (
        "sample_manifest.csv",
        "sample_manifest.json",
        "final_research_users.csv",
        "final_research_users.json",
        "final_research_report_payload.json",
        "field_lineage_catalog.json",
        "user_field_trace.json",
        "field_source_records.json",
        "report.html",
    )
    for artifact_name in v5_user_artifacts:
        assert "interest_tags" not in (output / artifact_name).read_text(encoding="utf-8"), artifact_name

    persisted_report = (output / "report.html").read_bytes()
    persisted_payload = (output / "final_research_report_payload.json").read_bytes()
    validated = _validate_persisted_ranking_report(output)

    assert isinstance(validated.payload, FinalResearchRankingReportPayloadV5)
    assert validated.manifest["manifest_version"] == "final-research-ranking-runtime-v3"
    assert (output / "report.html").read_bytes() == persisted_report
    assert (output / "final_research_report_payload.json").read_bytes() == persisted_payload


def _promote_to_synthetic_formal_release(run_dir: Path) -> None:
    payload_path = run_dir / "final_research_report_payload.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    decision_evidence = payload["evidence_state"]["decision_execution_evidence"]
    decision_evidence.update(
        {
            "formal_research_evidence": True,
            "decision_execution_mode": "live_provider",
            "live_api_triggered": True,
            "sampling_status": "persisted_seed_first_formal_run",
        }
    )
    formal_state = {
        "schema_version": "ranking-v5-formal-evidence-v1",
        "contract_stage": "formal_release",
        "target_aggregate_engagement_reference": {
            "status": "persisted",
            "formal_research_evidence": False,
        },
        "decision_execution_evidence": decision_evidence,
        "production_deploy_eligible": True,
    }
    payload["run"]["sampling_status"] = "persisted_seed_first_formal_run"
    payload["evidence_state"] = formal_state
    _write_json(payload_path, payload)

    for file_name in ("artifact_manifest.json", "ranking_runtime_summary.json"):
        path = run_dir / file_name
        document = json.loads(path.read_text(encoding="utf-8"))
        document.update(
            {
                "sampling_status": "persisted_seed_first_formal_run",
                "decision_execution_mode": "live_provider",
                "live_api_triggered": True,
                "evidence_state": formal_state,
            }
        )
        _write_json(path, document)

    audit_path = run_dir / "seed_first_sample_audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit["sampling_status"] = "persisted_seed_first_formal_run"
    _write_json(audit_path, audit)
    rebuild_final_research_report(run_dir)


def _validate_release(
    repo_root: Path,
    run_dir: Path,
    contract_path: Path,
    *,
    snapshot_dir: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    validator = Path(__file__).resolve().parents[2] / "scripts" / "validate_abm_report_release.py"
    command = [
        sys.executable,
        str(validator),
        "--repo-root",
        str(repo_root),
        "--contract",
        str(contract_path),
        "--source-dir",
        str(run_dir),
    ]
    if snapshot_dir is not None:
        command.extend(["--snapshot-dir", str(snapshot_dir)])
    return subprocess.run(
        command,
        text=True,
        capture_output=True,
    )


def _write_v2_release_contract(repo_root: Path, run_dir: Path) -> Path:
    manifest = json.loads((run_dir / "artifact_manifest.json").read_text(encoding="utf-8"))
    payload = json.loads((run_dir / "final_research_report_payload.json").read_text(encoding="utf-8"))
    users = json.loads((run_dir / "final_research_users.json").read_text(encoding="utf-8"))
    diagnostics = json.loads((run_dir / "ranking_diagnostics.json").read_text(encoding="utf-8"))
    diagnostics_summary = json.loads((run_dir / "ranking_diagnostics_summary.json").read_text(encoding="utf-8"))
    runtime_summary = json.loads((run_dir / "ranking_runtime_summary.json").read_text(encoding="utf-8"))
    config = json.loads((run_dir / "config_snapshot.json").read_text(encoding="utf-8"))
    evidence_state = payload["evidence_state"]
    decision_evidence = evidence_state["decision_execution_evidence"]
    aggregate_reference = diagnostics["historical_top20_diagnostic"]["target_aggregate_engagement_reference"]
    artifact_paths = [*manifest["artifacts"].values(), "artifact_manifest.json"]
    contract = {
        "schema_version": "abm-report-release-contract-v2",
        "release_purpose": "formal_research",
        "source_directory": run_dir.relative_to(repo_root).as_posix(),
        "payload_schema_version": payload["schema_version"],
        "users_schema_version": users["schema_version"],
        "manifest_version": manifest["manifest_version"],
        "diagnostics_schema_version": diagnostics["schema_version"],
        "diagnostics_summary_schema_version": diagnostics_summary["schema_version"],
        "prompt_version": config["provider"]["prompt_version"],
        "evidence_schema_version": evidence_state["schema_version"],
        "decision_execution_evidence_schema_version": decision_evidence["schema_version"],
        "sampling_method": payload["run"]["sampling_method"],
        "sampling_status": payload["run"]["sampling_status"],
        "decision_execution_mode": decision_evidence["decision_execution_mode"],
        "live_api_triggered": decision_evidence["live_api_triggered"],
        "formal_research_evidence": decision_evidence["formal_research_evidence"],
        "production_deploy_eligible": evidence_state["production_deploy_eligible"],
        "sample_role_counts": payload["sample_role_counts"],
        "decision_source_counts": decision_evidence["decision_source_counts"],
        "action_counts": decision_evidence["action_counts"],
        "terminal_counts": decision_evidence["terminal_counts"],
        "degeneracy_flags": decision_evidence["degeneracy_flags"],
        "target_aggregate_engagement_reference": aggregate_reference,
        "artifact_sha256": {path: _sha256(run_dir / path) for path in artifact_paths},
    }
    contract_path = repo_root / "configs" / "deployments" / "synthetic-formal-fixture.json"
    _write_json(contract_path, contract)
    assert runtime_summary["evidence_state"] == evidence_state
    return contract_path


def _make_synthetic_formal_release(tmp_path: Path) -> tuple[Path, Path]:
    dataset_dir = _make_processed_fixture(tmp_path, user_count=6, dense_target_network=True)
    output = FinalResearchRunner(
        FinalResearchConfig(
            dataset_dir=dataset_dir,
            sample_size=6,
            provider=ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False),
        ),
        _TargetDeliveryAdapter(),
    ).run_and_write(tmp_path / "runs" / "synthetic-formal-fixture")
    _promote_to_synthetic_formal_release(output)
    return output, _write_v2_release_contract(tmp_path, output)


def test_release_v2_snapshot_binds_validation_to_uploaded_bytes(tmp_path: Path) -> None:
    output, contract = _make_synthetic_formal_release(tmp_path)
    snapshot = tmp_path / "deploy-snapshot"
    shutil.copytree(output, snapshot)
    (output / "report.html").write_text("source changed after snapshot", encoding="utf-8")

    validated = _validate_release(tmp_path, output, contract, snapshot_dir=snapshot)

    assert validated.returncode == 0, validated.stderr
    (snapshot / "report.html").write_text("snapshot tampered", encoding="utf-8")

    rejected = _validate_release(tmp_path, output, contract, snapshot_dir=snapshot)

    assert rejected.returncode == 1
    assert "SHA-256 for report.html mismatch" in rejected.stderr


def test_release_v2_accepts_synthetic_persisted_formal_fixture_without_rewriting(tmp_path: Path) -> None:
    output, contract = _make_synthetic_formal_release(tmp_path)
    report_before = (output / "report.html").read_bytes()
    payload_before = (output / "final_research_report_payload.json").read_bytes()

    validated = _validate_release(tmp_path, output, contract)

    assert validated.returncode == 0, validated.stderr
    assert "abm-report-release-contract-v2" in validated.stdout
    assert "formal_research" in validated.stdout
    assert "persisted_seed_first_formal_run" in validated.stdout
    assert "live_provider" in validated.stdout
    contract_document = json.loads(contract.read_text(encoding="utf-8"))
    assert contract_document["action_counts"] == {"like": 0, "comment": 0, "share": 0, "ignore": 6}
    assert contract_document["degeneracy_flags"] == {
        "all_decisions_ignore": True,
        "single_action_only": True,
        "no_engagement_feedback": True,
    }
    assert (output / "report.html").read_bytes() == report_before
    assert (output / "final_research_report_payload.json").read_bytes() == payload_before


@pytest.mark.parametrize("adapter_kind", ["mock_provider", "rule_based"])
def test_release_v2_rejects_runner_generated_validation_candidates(tmp_path: Path, adapter_kind: str) -> None:
    dataset_dir = _make_processed_fixture(tmp_path, user_count=6, dense_target_network=True)
    adapter: LLMDecisionAdapter = (
        _TargetDeliveryAdapter() if adapter_kind == "mock_provider" else RuleBasedDecisionAdapter()
    )
    output = FinalResearchRunner(
        FinalResearchConfig(
            dataset_dir=dataset_dir,
            sample_size=6,
            provider=ProviderLLMConfig(enabled=True, model="configured-model", require_live_env=False),
        ),
        adapter,
    ).run_and_write(tmp_path / "runs" / adapter_kind)
    contract = _write_v2_release_contract(tmp_path, output)

    rejected = _validate_release(tmp_path, output, contract)

    assert rejected.returncode == 1
    assert "invalid v2 release contract" in rejected.stderr
    assert json.loads((output / "artifact_manifest.json").read_text(encoding="utf-8"))["live_api_triggered"] is False


@pytest.mark.parametrize(
    ("corruption", "expected_error"),
    [
        ("purpose", "release_purpose"),
        ("source_directory", "source directory mismatch"),
        ("payload_schema", "payload_schema_version"),
        ("execution_mode", "decision_execution_mode"),
        ("live_fact", "live_api_triggered"),
        ("action_count", "decided_users must equal sum(action_counts)"),
        ("aggregate_reference", "target_aggregate_engagement_reference mismatch"),
        ("missing_hash", "must cover the exact manifest artifacts"),
        ("extra_field", "extra_forbidden"),
    ],
)
def test_release_v2_rejects_crossed_contract_evidence(
    tmp_path: Path,
    corruption: str,
    expected_error: str,
) -> None:
    output, contract_path = _make_synthetic_formal_release(tmp_path)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if corruption == "purpose":
        contract["release_purpose"] = "validation"
    elif corruption == "source_directory":
        contract["source_directory"] = "runs/a-different-formal-run"
    elif corruption == "payload_schema":
        contract["payload_schema_version"] = "final-research-ranking-report-payload-v4"
    elif corruption == "execution_mode":
        contract["decision_execution_mode"] = "rule_based"
    elif corruption == "live_fact":
        contract["live_api_triggered"] = False
    elif corruption == "action_count":
        contract["action_counts"]["like"] += 1
    elif corruption == "aggregate_reference":
        contract["target_aggregate_engagement_reference"]["like_count"] += 1
    elif corruption == "missing_hash":
        contract["artifact_sha256"].pop("runtime_actions.csv")
    elif corruption == "extra_field":
        contract["authorization_claim"] = "not part of the contract"
    else:  # pragma: no cover
        raise AssertionError(corruption)
    _write_json(contract_path, contract)

    rejected = _validate_release(tmp_path, output, contract_path)

    assert rejected.returncode == 1
    assert expected_error in rejected.stderr


@pytest.mark.parametrize(
    ("corruption", "expected_error"),
    [
        ("decision_row", "Decision and action row disagree"),
        ("holdout_source", "target aggregate engagement reference does not match source artifact"),
        ("missing_manifest_artifact", "artifact_set does not match exact contract"),
        ("parent_manifest_path", "artifact_set does not match exact contract"),
        ("absolute_manifest_path", "artifact_set does not match exact contract"),
    ],
)
def test_release_v2_rejects_cross_artifact_corruption_even_with_current_hashes(
    tmp_path: Path,
    corruption: str,
    expected_error: str,
) -> None:
    output, contract = _make_synthetic_formal_release(tmp_path)
    if corruption == "decision_row":
        path = output / "runtime_decisions.csv"
        rows = _read_csv(path)
        rows[0]["action"] = "like"
        _write_csv(path, list(rows[0]), rows)
    elif corruption == "holdout_source":
        path = output / "top20_holdout_diagnostic.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["target_aggregate_engagement_reference"]["like_count"] += 1
        _write_json(path, document)
    else:
        path = output / "artifact_manifest.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        if corruption == "missing_manifest_artifact":
            document["artifacts"].pop("runtime_actions")
        elif corruption == "parent_manifest_path":
            document["artifacts"]["runtime_actions"] = "../runtime_actions.csv"
        elif corruption == "absolute_manifest_path":
            document["artifacts"]["runtime_actions"] = str((output / "runtime_actions.csv").resolve())
        _write_json(path, document)
    if corruption in {"decision_row", "holdout_source"}:
        contract = _write_v2_release_contract(tmp_path, output)
    else:
        contract_document = json.loads(contract.read_text(encoding="utf-8"))
        contract_document["artifact_sha256"]["artifact_manifest.json"] = _sha256(output / "artifact_manifest.json")
        _write_json(contract, contract_document)

    rejected = _validate_release(tmp_path, output, contract)

    assert rejected.returncode == 1
    assert expected_error in rejected.stderr


def test_release_v2_rejects_contract_parent_symlink(tmp_path: Path) -> None:
    output, contract = _make_synthetic_formal_release(tmp_path)
    real_configs = tmp_path / "real-configs"
    (tmp_path / "configs").replace(real_configs)
    os.symlink(real_configs, tmp_path / "configs")
    symlinked_contract = tmp_path / "configs" / "deployments" / contract.name

    rejected = _validate_release(tmp_path, output, symlinked_contract)

    assert rejected.returncode == 1
    assert "release contract must not contain symlink components" in rejected.stderr


def test_release_v2_rejects_non_regular_snapshot_entries(tmp_path: Path) -> None:
    output, contract = _make_synthetic_formal_release(tmp_path)
    snapshot = tmp_path / "deploy-snapshot"
    shutil.copytree(output, snapshot)
    os.mkfifo(snapshot / "unapproved.pipe")

    rejected = _validate_release(tmp_path, output, contract, snapshot_dir=snapshot)

    assert rejected.returncode == 1
    assert "release directory contains non-regular entry: unapproved.pipe" in rejected.stderr


def test_release_v2_rejects_unmanifested_upload_files(tmp_path: Path) -> None:
    output, contract = _make_synthetic_formal_release(tmp_path)
    (output / "unapproved-debug-dump.json").write_text("{}", encoding="utf-8")

    rejected = _validate_release(tmp_path, output, contract)

    assert rejected.returncode == 1
    assert "source directory contains files outside the v2 artifact manifest" in rejected.stderr


def test_release_v2_rejects_tampered_or_symlinked_artifacts(tmp_path: Path) -> None:
    output, contract = _make_synthetic_formal_release(tmp_path)
    (output / "report.html").write_text("tampered", encoding="utf-8")

    tampered = _validate_release(tmp_path, output, contract)

    assert tampered.returncode == 1
    assert "SHA-256 for report.html mismatch" in tampered.stderr

    output, contract = _make_synthetic_formal_release(tmp_path / "symlink-case")
    catalog = output / "field_lineage_catalog.json"
    catalog.unlink()
    os.symlink(output / "user_field_trace.json", catalog)

    symlinked = _validate_release(tmp_path / "symlink-case", output, contract)

    assert symlinked.returncode == 1
    assert "source directory contains symlink" in symlinked.stderr


def test_target_delivery_rule_based_evidence_does_not_use_configured_provider_identity(tmp_path: Path) -> None:
    dataset_dir = _make_processed_fixture(tmp_path, user_count=6, dense_target_network=True)
    provider_config = ProviderLLMConfig(enabled=True, model="configured-but-unused", require_live_env=False)
    adapter = CachedDecisionAdapter(RuleBasedDecisionAdapter(), InMemoryDecisionCache())

    output = FinalResearchRunner(
        FinalResearchConfig(dataset_dir=dataset_dir, sample_size=6, provider=provider_config),
        adapter,
    ).run_and_write(tmp_path / "ranking-rule-based-evidence")

    manifest = json.loads((output / "artifact_manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((output / "ranking_runtime_summary.json").read_text(encoding="utf-8"))
    payload = json.loads((output / "final_research_report_payload.json").read_text(encoding="utf-8"))
    evidence = payload["evidence_state"]["decision_execution_evidence"]

    assert evidence["decision_execution_mode"] == "rule_based"
    assert evidence["adapter_chain"] == ["cached", "rule_based"]
    assert evidence["decision_source_counts"] == {"rule_based": 6}
    assert evidence["provider_metadata"] == {"adapter": "rule_based", "prompt_version": "engage-v1"}
    assert evidence["live_api_triggered"] is False
    assert evidence["sampling_status"] == "validation_run"
    assert summary["provider_metadata"] == evidence["provider_metadata"]
    assert manifest["decision_execution_mode"] == "rule_based"
    assert manifest["live_api_triggered"] is False
    assert "configured-but-unused" not in json.dumps(evidence)
    assert rebuild_final_research_report(output) == output / "report.html"


def test_target_delivery_deterministic_provider_covers_all_actions_in_one_run(tmp_path: Path) -> None:
    dataset_dir = _make_processed_fixture(tmp_path, user_count=30, dense_target_network=True)
    adapter = _TargetDeliveryAdapter(cycle_actions=True)

    output = FinalResearchRunner(
        FinalResearchConfig(
            dataset_dir=dataset_dir,
            sample_size=30,
            provider=ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False),
        ),
        adapter,
    ).run_and_write(tmp_path / "ranking-four-action-contract")

    decisions = _read_csv(output / "runtime_decisions.csv")
    actions = _read_csv(output / "runtime_actions.csv")
    summary = json.loads((output / "ranking_runtime_summary.json").read_text(encoding="utf-8"))
    payload = json.loads((output / "final_research_report_payload.json").read_text(encoding="utf-8"))
    evidence = payload["evidence_state"]["decision_execution_evidence"]
    report_html = (output / "report.html").read_text(encoding="utf-8")

    assert len(decisions) == len(actions) == 30
    assert evidence["decision_execution_mode"] == "mock_provider"
    assert evidence["decision_source_counts"] == {"provider": 30}
    assert set(evidence["action_counts"]) == {"like", "comment", "share", "ignore"}
    assert all(evidence["action_counts"][action] > 0 for action in ("like", "comment", "share", "ignore"))
    assert evidence["action_counts"] == dict(Counter(row["action"] for row in decisions))
    assert evidence["degeneracy_flags"] == {
        "all_decisions_ignore": False,
        "single_action_only": False,
        "no_engagement_feedback": False,
    }
    assert summary["action_counts"] == evidence["action_counts"]
    assert {user["result_status"] for user in payload["users"]} == {"like", "comment", "share", "ignore"}
    assert any(
        trace["field_name"] == "action" and trace["actual_usage_stages"] == ["Ranking", "Report Only"]
        for traces in payload["user_field_trace_index"].values()
        for trace in traces
    )
    assert 'data-testid="decision-execution-evidence"' in report_html
    assert 'data-testid="decision-source-counts"' in report_html
    assert 'data-testid="decision-action-counts"' in report_html
    assert 'data-testid="decision-terminal-counts"' in report_html
    assert 'data-testid="decision-degeneracy-flags"' in report_html
    assert "只决定谁获得曝光" in report_html
    assert payload["downloads"]["runtime_decisions"] == "runtime_decisions.csv"
    assert payload["downloads"]["runtime_actions"] == "runtime_actions.csv"
    assert payload["downloads"]["runtime_provider_failures"] == "runtime_provider_failures.csv"
    assert payload["downloads"]["ranking_runtime_outcomes"] == "ranking_runtime_outcomes.csv"
    assert payload["downloads"]["ranking_runtime_summary"] == "ranking_runtime_summary.json"


def test_target_delivery_ranking_runtime_caps_delivery_and_marks_final_below_capacity(tmp_path: Path) -> None:
    dataset_dir = _make_target_delivery_fixture(tmp_path)
    user_rows = _read_csv(dataset_dir / "users.csv")
    template = user_rows[-1]
    for number in range(81, 1011):
        user_rows.append(
            {
                **template,
                "user_id": f"u{number}",
                "nickname": f"User {number}",
                "bio": f"Bio {number}",
                "signature": f"Signature {number}",
                "follower_count": str(number * 10),
                "following_count": str(number),
                "video_count": str(number),
                "global_influence_score": str(number / 10),
                **{field_name: str(value) for field_name, value in _latent_row(number).items()},
            }
        )
    _write_csv(dataset_dir / "users.csv", list(user_rows[0]), user_rows)
    provider_config = ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False)
    adapter = _TargetDeliveryAdapter(engage_seed_user=False)
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
    decision_evidence = report_payload["evidence_state"]["decision_execution_evidence"]

    assert len(outcomes) == 1000
    assert len(exposed) == len(_target_delivery_client(adapter).calls) == summary["counts"]["target_exposures"] == 600
    assert len(below_capacity) == 400
    assert decision_evidence["action_counts"] == {"like": 0, "comment": 0, "share": 0, "ignore": 600}
    assert decision_evidence["terminal_counts"] == {
        "sample_users": 1000,
        "exposed_users": 600,
        "decided_users": 600,
        "provider_failed": 0,
        "below_delivery_capacity": 400,
    }
    assert decision_evidence["degeneracy_flags"] == {
        "all_decisions_ignore": True,
        "single_action_only": True,
        "no_engagement_feedback": True,
    }
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
    below_user_id = next(
        row["user_id"] for row in report_payload["users"] if row["result_status"] == "below_delivery_capacity"
    )
    below_traces = {trace["field_name"]: trace for trace in report_payload["user_field_trace_index"][below_user_id]}
    assert "interest_tags" not in below_traces
    assert below_traces["historical_tags"]["prompt_inclusion_status"] == "not_allowlisted"
    assert below_traces["result_status"]["source_record_locator"]["artifact_id"] == "ranking_runtime_outcomes"
    assert below_traces["action"]["evidence"][0]["evidence_kind"] == "not_exposed_no_action"
    assert below_traces["action"]["source_record_locator"]["artifact_id"] == "ranking_runtime_outcomes"
    assert below_traces["action"]["actual_usage_stages"] == ["Report Only"]
    assert below_traces["action"]["evidence"][0]["matched_values"] == [
        "action=unavailable",
        "affected_direct_neighbor_count=0",
    ]
    for field_name in ("engage", "probability", "reason", "confidence", "decision_source"):
        trace = below_traces[field_name]
        assert trace["source_record_locator"]["artifact_id"] == "ranking_runtime_outcomes"
        assert trace["evidence"][0]["evidence_kind"] == "runtime_value_unavailable"
        assert "result_status=below_delivery_capacity" in trace["evidence"][0]["matched_values"]
        assert "provider_status=not_called" in trace["evidence"][0]["matched_values"]


def test_target_delivery_ranking_v5_persists_historical_field_traces_without_interest_contract(tmp_path: Path) -> None:
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
    ).run_and_write(tmp_path / "ranking-v5-field-trace")

    manifest = json.loads((output / "artifact_manifest.json").read_text(encoding="utf-8"))
    payload = json.loads((output / "final_research_report_payload.json").read_text(encoding="utf-8"))
    catalog_document = json.loads((output / manifest["artifacts"]["field_lineage_catalog"]).read_text(encoding="utf-8"))
    trace_document = json.loads((output / manifest["artifacts"]["user_field_trace"]).read_text(encoding="utf-8"))
    source_document = json.loads((output / manifest["artifacts"]["field_source_records"]).read_text(encoding="utf-8"))

    assert payload["schema_version"] == "final-research-ranking-report-payload-v5"
    assert catalog_document["schema_version"] == "field-lineage-catalog-v1"
    assert trace_document["schema_version"] == "user-field-trace-v1"
    assert source_document["schema_version"] == "field-source-records-v1"
    assert payload["field_lineage_catalog"] == catalog_document["definitions"]
    assert payload["user_field_trace_index"] == trace_document["users"]
    expected_catalog_fields = {entry["field_name"] for entry in payload["field_lineage"]}
    catalog_by_field = {entry["field_name"]: entry for entry in payload["field_lineage_catalog"]}
    expected_trace_fields = {
        field_name
        for field_name, definition in catalog_by_field.items()
        if "user_id" in definition["record_key_fields"] or field_name.startswith("ranking_diagnostics.")
    }
    assert set(catalog_by_field) == expected_catalog_fields
    assert "interest_tags" not in expected_catalog_fields
    assert {entry["provenance"] for entry in payload["field_lineage_catalog"]} == {
        "Direct Observed Profile Field",
        "Historical Behavioral Evidence",
        "Derived Proxy Metric",
        "Synthetic Experiment Label",
        "Runtime Simulation Result",
    }
    assert all(
        {trace["field_name"] for trace in traces} == expected_trace_fields
        for traces in payload["user_field_trace_index"].values()
    )
    coverage_audit = catalog_document["coverage_audit"]
    assert coverage_audit["user_count"] == len(payload["users"])
    assert coverage_audit["catalog_field_count"] == len(expected_catalog_fields)
    assert coverage_audit["trace_count"] == len(payload["users"]) * len(expected_trace_fields)
    assert sum(coverage_audit["value_status_counts"].values()) == coverage_audit["trace_count"]
    assert {record["field_name"] for record in coverage_audit["field_coverage"]} == expected_catalog_fields
    assert sum(coverage_audit["provenance_field_counts"].values()) == len(expected_catalog_fields)

    u1_traces = {trace["field_name"]: trace for trace in payload["user_field_trace_index"]["u1"]}
    assert "interest_tags" not in u1_traces
    assert u1_traces["nickname"]["source_record_locator"]["artifact_id"] == "sample_manifest_json"
    assert u1_traces["activity_score"]["source_record_locator"]["artifact_id"] == "sample_manifest_json"
    assert u1_traces["base_network_relevance"]["source_record_locator"]["artifact_id"] == "field_source_records"
    assert u1_traces["activity_score"]["evidence"][0]["evidence_kind"] == "derived_proxy_inputs"
    assert u1_traces["latent_hotel_class"]["source_record_locator"]["artifact_id"] == "sample_manifest_json"
    assert u1_traces["latent_hotel_class"]["evidence"][0]["evidence_kind"] == "synthetic_experiment_contract"
    assert u1_traces["latest_ranking_position"]["source_record_locator"] == {
        "artifact_id": "ranking_runtime_candidates",
        "relative_path": "ranking_runtime_candidates.csv",
        "record_key": {"time_step": 0, "user_id": "u1"},
    }
    assert u1_traces["latest_ranking_position"]["prompt_inclusion_status"] == "not_allowlisted"
    assert u1_traces["action"]["source_record_locator"]["artifact_id"] == "runtime_decisions"
    assert u1_traces["action"]["source_record_locator"]["record_key"] == {
        "time_step": 0,
        "user_id": "u1",
        "video_id": payload["target_video"]["video_id"],
    }
    assert u1_traces["action"]["evidence"][0]["evidence_kind"] == "no_propagation_action"
    assert "action=ignore" in u1_traces["action"]["evidence"][0]["matched_values"]
    assert u1_traces["action"]["actual_usage_stages"] == ["Report Only"]
    assert u1_traces["provider_status"]["source_record_locator"]["artifact_id"] == "ranking_runtime_outcomes"
    assert (
        u1_traces["ranking_diagnostics.paired_ablation"]["source_record_locator"]["artifact_id"]
        == "ranking_ablation_diagnostics_csv"
    )
    assert u1_traces["ranking_diagnostics.paired_ablation"]["source_record_locator"]["record_key"] == {
        "time_step": 0,
        "user_id": "u1",
    }
    assert u1_traces["ranking_diagnostics.paired_ablation"]["evidence"][0]["matched_values"] == [
        "user_id=u1",
        "paired_ablation=True",
    ]
    assert u1_traces["ranking_diagnostics.summary"]["source_record_locator"]["artifact_id"] == (
        "ranking_diagnostics_summary"
    )
    assert u1_traces["ranking_diagnostics.weight_sensitivity"]["source_record_locator"]["record_key"] == {
        "time_step": 0,
        "variant_id": "main_50_30_20",
    }
    assert u1_traces["ranking_diagnostics.historical_top20_diagnostic"]["source_record_locator"]["record_key"] == {
        "schema_version": "ranking-diagnostics-v2",
        "section": "historical_top20_diagnostic",
    }
    assert u1_traces["ranking_diagnostics.summary"]["source_record_locator"]["record_key"] == {
        "schema_version": "ranking-diagnostics-summary-v2"
    }
    historical_diagnostic_catalog = catalog_by_field["ranking_diagnostics.historical_top20_diagnostic"]
    assert historical_diagnostic_catalog["source_fields"] == [
        "schema_version",
        "historical_top20_diagnostic",
        "target_aggregate_engagement_reference",
        "source_artifact",
        "record_key.video_id",
        "like_count",
        "comment_count",
        "share_count",
        "collect_count",
    ]
    assert historical_diagnostic_catalog["transformation_method"] == "post_runtime_holdout_diagnostic_forward_v2"
    assert "top20_holdout_diagnostic.json" in historical_diagnostic_catalog["transformation_description"]
    assert "videos.csv" in historical_diagnostic_catalog["transformation_description"]
    assert any("真实曝光分母" in value for value in historical_diagnostic_catalog["limitations"])
    assert any("用户级归属" in value for value in historical_diagnostic_catalog["limitations"])
    assert any("互斥" in value for value in historical_diagnostic_catalog["limitations"])

    u2_traces = {trace["field_name"]: trace for trace in payload["user_field_trace_index"]["u2"]}
    assert "interest_tags" not in u2_traces
    assert u2_traces["historical_tags"]["value_status"] == "present"
    assert u2_traces["historical_tags"]["prompt_inclusion_status"] == "not_allowlisted"
    assert u2_traces["action"]["evidence"][0]["evidence_kind"] == "no_propagation_action"
    source_records = {record["user_id"]: record for record in source_document["records"]}
    assert "interest_tags" not in source_records["u2"]
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
    assert "interest_tags" not in persisted_text
    assert "raw_prompt" not in persisted_text
    assert "raw_provider_response" not in persisted_text
    assert "sk-secret" not in persisted_text


def test_target_delivery_ranking_v5_keeps_injected_provider_client_in_validation(tmp_path: Path) -> None:
    dataset_dir = _make_target_delivery_fixture(tmp_path)
    provider_config = ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False)
    adapter = _TargetDeliveryAdapter()
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

    assert adapter.live_api_triggered is False
    assert all(document["sampling_status"] == "validation_run" for document in documents)
    assert report_payload["run"]["sampling_status"] == "validation_run"
    assert documents[3]["live_api_triggered"] is False
    assert report_payload["evidence_state"]["production_deploy_eligible"] is False
    assert "Persisted Seed-First Formal Run" not in (run_dir / "report.html").read_text(encoding="utf-8")
    assert rebuild_final_research_report(run_dir) == run_dir / "report.html"


def test_target_delivery_trace_records_feedback_and_provider_failure_from_the_same_run(tmp_path: Path) -> None:
    dataset_dir = _make_target_delivery_fixture(tmp_path)
    provider_config = ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False)
    run_dir = FinalResearchRunner(
        FinalResearchConfig(dataset_dir=dataset_dir, sample_size=70, provider=provider_config),
        _TargetDeliveryAdapter(failed_user_id="u79"),
    ).run_and_write(tmp_path / "ranking-runtime-trace")

    payload = json.loads((run_dir / "final_research_report_payload.json").read_text(encoding="utf-8"))
    traces_by_user = {
        user_id: {trace["field_name"]: trace for trace in traces}
        for user_id, traces in payload["user_field_trace_index"].items()
    }

    engaged_action = traces_by_user["u80"]["action"]
    assert engaged_action["value_status"] == "present"
    assert engaged_action["source_record_locator"]["artifact_id"] == "runtime_decisions"
    assert engaged_action["evidence"][0]["evidence_kind"] == "next_batch_direct_neighbor_signal"
    assert "action=like" in engaged_action["evidence"][0]["matched_values"]
    assert engaged_action["actual_usage_stages"] == ["Ranking", "Report Only"]
    assert any(
        value.startswith("affected_direct_neighbor_user_ids=")
        for value in engaged_action["evidence"][0]["matched_values"]
    )

    failed = traces_by_user["u79"]
    assert failed["provider_status"]["source_record_locator"]["artifact_id"] == "ranking_runtime_outcomes"
    assert failed["provider_failure_type"]["source_record_locator"]["artifact_id"] == ("runtime_provider_failures")
    assert failed["provider_failure_type"]["value_status"] == "present"
    assert failed["action"]["value_status"] == "empty"
    assert failed["action"]["source_record_locator"]["artifact_id"] == "ranking_runtime_outcomes"
    assert failed["action"]["evidence"][0]["evidence_kind"] == "provider_failure_no_action"
    assert failed["action"]["actual_usage_stages"] == ["Report Only"]
    failed_evidence = failed["action"]["evidence"][0]
    assert "action=unavailable" in failed_evidence["matched_values"]
    assert "affected_direct_neighbor_count=0" in failed_evidence["matched_values"]
    assert f"next_time_step={failed_evidence['record_key']['time_step'] + 1}" in failed_evidence["matched_values"]
    for field_name in ("engage", "probability", "reason", "confidence", "decision_source"):
        trace = failed[field_name]
        assert trace["source_record_locator"]["artifact_id"] == "ranking_runtime_outcomes"
        assert trace["evidence"][0]["evidence_kind"] == "runtime_value_unavailable"
        assert "result_status=provider_failed" in trace["evidence"][0]["matched_values"]
        assert "provider_status=provider_failed" in trace["evidence"][0]["matched_values"]


def test_target_delivery_trace_does_not_claim_ranking_usage_without_affected_neighbors(tmp_path: Path) -> None:
    dataset_dir = _make_processed_fixture(tmp_path, user_count=1010)
    provider_config = ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False)
    run_dir = FinalResearchRunner(
        FinalResearchConfig(dataset_dir=dataset_dir, sample_size=1000, provider=provider_config),
        _TargetDeliveryAdapter(engage_all=True),
    ).run_and_write(tmp_path / "ranking-runtime-final-batch-trace")

    payload = json.loads((run_dir / "final_research_report_payload.json").read_text(encoding="utf-8"))
    final_time_step = max(
        user["exposure_time_step"] for user in payload["users"] if user["exposure_time_step"] is not None
    )
    final_batch_user = next(user for user in payload["users"] if user["exposure_time_step"] == final_time_step)
    action_trace = next(
        trace
        for trace in payload["user_field_trace_index"][final_batch_user["user_id"]]
        if trace["field_name"] == "action"
    )

    assert final_batch_user["action"] == "like"
    assert action_trace["evidence"][0]["evidence_kind"] == "no_next_batch_signal"
    assert "affected_direct_neighbor_count=0" in action_trace["evidence"][0]["matched_values"]
    assert "affected_direct_neighbor_user_ids=[]" in action_trace["evidence"][0]["matched_values"]
    assert not any(value.startswith("next_time_step=") for value in action_trace["evidence"][0]["matched_values"])
    assert action_trace["actual_usage_stages"] == ["Report Only"]


def test_probability_runtime_keeps_injected_provider_client_in_validation(tmp_path: Path) -> None:
    dataset_dir = _make_processed_fixture(tmp_path)
    provider_config = ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False)
    adapter = _TargetDeliveryAdapter()
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

    assert adapter.live_api_triggered is False
    assert all(document["sampling_status"] == "validation_run" for document in documents)
    assert report_payload["run"]["sampling_method"] == "source_scope_stratified_sample_v1"
    assert report_payload["run"]["sampling_status"] == "validation_run"
    assert documents[2]["live_api_triggered"] is False
    assert "Persisted Probability Formal Run" not in report_html
    assert "Persisted Seed-First Formal Run" not in report_html


def test_target_delivery_ranking_report_rebuild_is_deterministic(tmp_path: Path) -> None:
    dataset_dir = _make_target_delivery_fixture(tmp_path)
    provider_config = ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False)
    adapter = _TargetDeliveryAdapter(failed_user_id="u79")
    run_dir = FinalResearchRunner(
        FinalResearchConfig(dataset_dir=dataset_dir, sample_size=70, provider=provider_config),
        adapter,
    ).run_and_write(tmp_path / "ranking-rebuildable")
    calls_before_rebuild = len(_target_delivery_client(adapter).calls)
    report_path = run_dir / "report.html"
    payload_path = run_dir / "final_research_report_payload.json"
    payload = FinalResearchRankingReportPayloadV5.model_validate_json(payload_path.read_text(encoding="utf-8"))
    users_document = json.loads((run_dir / "final_research_users.json").read_text(encoding="utf-8"))
    assert users_document["schema_version"] == "final-research-ranking-users-v5"
    direct_report = FinalResearchReportWriter.render_payload(payload).encode()
    assert report_path.read_bytes() == direct_report
    preserved_artifacts = {
        path.name: path.read_bytes() for path in run_dir.iterdir() if path.is_file() and path != report_path
    }

    assert rebuild_final_research_report(run_dir) == report_path
    first_payload = payload_path.read_bytes()
    first_report = report_path.read_bytes()
    assert first_report == direct_report
    assert len(_target_delivery_client(adapter).calls) == calls_before_rebuild

    assert rebuild_final_research_report(run_dir) == report_path
    assert payload_path.read_bytes() == first_payload
    assert report_path.read_bytes() == first_report
    assert {
        path.name: path.read_bytes() for path in run_dir.iterdir() if path.is_file() and path != report_path
    } == preserved_artifacts


def _restore_historical_top20_v1_catalog_definition(catalog: list[dict[str, Any]]) -> None:
    historical_diagnostic_definition = next(
        definition
        for definition in catalog
        if definition["field_name"] == "ranking_diagnostics.historical_top20_diagnostic"
    )
    historical_diagnostic_definition.update(
        {
            "source_fields": ["schema_version", "historical_top20_diagnostic"],
            "transformation_method": "same_run_ranking_diagnostic_v1",
            "transformation_description": "只引用本次 run 基于 persisted candidate evidence 生成的 diagnostics。",
            "value_range": "由对应 persisted artifact schema 约束。",
            "interpretation": "诊断只解释本次 persisted run，不构成真实平台因果或准确率结论。",
            "limitations": [
                "只引用本次 run 的 allowlisted persisted evidence。",
                "不得复用其他 run 的 rank delta、Top20 或 action 结果。",
            ],
        }
    )


def _convert_persisted_v5_run_to_pending_v5(run_dir: Path) -> None:
    pending_evidence_state = {
        "schema_version": "ranking-v5-expand-evidence-v1",
        "contract_stage": "validation_expand",
        "target_aggregate_engagement_reference": {
            "status": "pending",
            "formal_research_evidence": False,
        },
        "decision_execution_evidence": {
            "status": "pending",
            "formal_research_evidence": False,
        },
        "production_deploy_eligible": False,
    }
    for file_name in ("artifact_manifest.json", "ranking_runtime_summary.json"):
        path = run_dir / file_name
        document = json.loads(path.read_text(encoding="utf-8"))
        document["evidence_state"] = pending_evidence_state
        for field_name in V5_DECISION_SUMMARY_FIELDS:
            if file_name == "ranking_runtime_summary.json" or field_name != "live_api_triggered":
                document.pop(field_name, None)
        path.write_text(json.dumps(document, ensure_ascii=False) + "\n", encoding="utf-8")

    holdout_path = run_dir / "top20_holdout_diagnostic.json"
    holdout = json.loads(holdout_path.read_text(encoding="utf-8"))
    holdout.pop("target_aggregate_engagement_reference")
    holdout_path.write_text(json.dumps(holdout, ensure_ascii=False) + "\n", encoding="utf-8")

    diagnostics_path = run_dir / "ranking_diagnostics.json"
    diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    diagnostics["historical_top20_diagnostic"].pop("target_aggregate_engagement_reference")
    diagnostics_path.write_text(json.dumps(diagnostics, ensure_ascii=False) + "\n", encoding="utf-8")

    payload_path = run_dir / "final_research_report_payload.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    payload["evidence_state"] = pending_evidence_state
    payload["ranking_diagnostics"]["historical_top20_diagnostic"].pop("target_aggregate_engagement_reference")
    for field_name in V5_DECISION_DOWNLOAD_FIELDS:
        payload["downloads"].pop(field_name)
    _restore_historical_top20_v1_catalog_definition(payload["field_lineage_catalog"])
    payload_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")

    users_path = run_dir / "final_research_users.json"
    users_document = json.loads(users_path.read_text(encoding="utf-8"))
    users_document["links"] = payload["downloads"]
    users_path.write_text(json.dumps(users_document, ensure_ascii=False) + "\n", encoding="utf-8")

    catalog_path = run_dir / "field_lineage_catalog.json"
    catalog_document = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog_document["definitions"] = payload["field_lineage_catalog"]
    catalog_path.write_text(json.dumps(catalog_document, ensure_ascii=False) + "\n", encoding="utf-8")


def test_v5_rebuild_preserves_pending_expand_artifacts(tmp_path: Path) -> None:
    dataset_dir = _make_target_delivery_fixture(tmp_path)
    run_dir = FinalResearchRunner(
        FinalResearchConfig(
            dataset_dir=dataset_dir,
            sample_size=70,
            provider=ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False),
        ),
        _TargetDeliveryAdapter(),
    ).run_and_write(tmp_path / "ranking-v5-pending-expand")
    _convert_persisted_v5_run_to_pending_v5(run_dir)

    report_path = rebuild_final_research_report(run_dir)
    payload_path = run_dir / "final_research_report_payload.json"
    rebuilt = FinalResearchRankingReportPayloadV5.model_validate_json(payload_path.read_text(encoding="utf-8"))
    first_payload = payload_path.read_bytes()
    first_report = report_path.read_bytes()

    assert rebuilt.evidence_state.target_aggregate_engagement_reference.status == "pending"
    assert "target_aggregate_engagement_reference" not in cast(
        dict[str, object],
        rebuilt.ranking_diagnostics["historical_top20_diagnostic"],
    )
    assert 'data-testid="target-aggregate-engagement-reference"' not in first_report.decode()
    assert rebuild_final_research_report(run_dir) == report_path
    assert payload_path.read_bytes() == first_payload
    assert report_path.read_bytes() == first_report


def _convert_seed_first_v5_run_to_historical_v4(run_dir: Path) -> dict[str, Any]:
    payload_path = run_dir / "final_research_report_payload.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    payload["schema_version"] = "final-research-ranking-report-payload-v4"
    payload.pop("evidence_state")
    for field_name in V5_DECISION_DOWNLOAD_FIELDS:
        payload["downloads"].pop(field_name)
    payload["field_lineage"].append(
        {
            "field_name": "interest_tags",
            "provenance": "Historical Behavioral Evidence",
            "usage_stages": ["LLM Prompt", "Report Only"],
        }
    )
    payload["prompt_contract"]["allowed_profile_fields"].insert(0, "interest_tags")
    payload["ranking_diagnostics"]["schema_version"] = "ranking-diagnostics-v1"
    payload["ranking_diagnostics"]["summary"]["schema_version"] = "ranking-diagnostics-summary-v1"
    payload["ranking_diagnostics"]["historical_top20_diagnostic"].pop(
        "target_aggregate_engagement_reference",
        None,
    )
    for user in payload["users"]:
        user["interest_tags"] = []

    interest_definition = {
        "field_name": "interest_tags",
        "display_name_zh": "兴趣标签",
        "meaning": "processed variant 从历史 hashtags 与文本主题证据整理的用户兴趣主题。",
        "provenance": "Historical Behavioral Evidence",
        "source_artifact_kind": "allowlisted processed historical topic evidence snapshot",
        "record_key_fields": ["user_id"],
        "source_fields": ["historical_video_hashtags", "historical_text_topic_terms"],
        "transformation_method": "historical_topic_tags_stable_unique_v1",
        "transformation_description": "提取历史视频 hashtags 与相关文本主题词，清理空值、去重并稳定排序。",
        "declared_usage_stages": ["LLM Prompt", "Report Only"],
        "value_range": "去重后的字符串列表，可为空。",
        "interpretation": "表示可复算的历史主题代理，不是直接观测 profile 字段。",
        "limitations": [
            "仅表示可复算的历史行为主题，不代表真实心理画像。",
            "空列表不代表用户没有兴趣。",
            "不得从 historical_tags 静默回填。",
        ],
    }
    catalog = payload["field_lineage_catalog"]
    historical_index = next(
        index for index, definition in enumerate(catalog) if definition["field_name"] == "historical_tags"
    )
    catalog[historical_index]["limitations"] = ["没有真实曝光日志。", "不得回填到 interest_tags。"]
    _restore_historical_top20_v1_catalog_definition(catalog)
    catalog.insert(historical_index + 1, interest_definition)

    for user in payload["users"]:
        user_id = user["user_id"]
        traces = payload["user_field_trace_index"][user_id]
        for trace in traces:
            locator = trace["source_record_locator"]
            if trace["field_name"] == "ranking_diagnostics.historical_top20_diagnostic":
                locator["record_key"]["schema_version"] = "ranking-diagnostics-v1"
            if trace["field_name"] == "ranking_diagnostics.summary":
                locator["record_key"]["schema_version"] = "ranking-diagnostics-summary-v1"
        exposed = user["result_status"] != "below_delivery_capacity"
        traces.append(
            {
                "user_id": user_id,
                "field_name": "interest_tags",
                "value_status": "empty",
                "source_record_locator": {
                    "artifact_id": "field_source_records",
                    "relative_path": "field_source_records.json",
                    "record_key": {"user_id": user_id},
                },
                "evidence": [],
                "actual_usage_stages": ["Report Only"],
                "prompt_inclusion_status": "empty_omitted" if exposed else "not_exposed",
                "omission_reason": "empty_value_omitted_from_prompt" if exposed else "user_not_exposed_to_target_video",
            }
        )

    catalog_models = [FieldLineageDefinition.model_validate(definition) for definition in catalog]
    trace_models = {
        user_id: [UserFieldTrace.model_validate(trace) for trace in traces]
        for user_id, traces in payload["user_field_trace_index"].items()
    }
    catalog_document = {
        "schema_version": "field-lineage-catalog-v1",
        "definitions": catalog,
        "coverage_audit": field_lineage_coverage_audit(catalog_models, trace_models),
    }
    (run_dir / "field_lineage_catalog.json").write_text(
        json.dumps(catalog_document, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (run_dir / "user_field_trace.json").write_text(
        json.dumps(
            {"schema_version": "user-field-trace-v1", "users": payload["user_field_trace_index"]}, ensure_ascii=False
        )
        + "\n",
        encoding="utf-8",
    )
    source_path = run_dir / "field_source_records.json"
    source_document = json.loads(source_path.read_text(encoding="utf-8"))
    for record in source_document["records"]:
        record["interest_tags"] = []
        record["interest_tag_evidence"] = []
    source_path.write_text(json.dumps(source_document, ensure_ascii=False) + "\n", encoding="utf-8")

    sample_json_path = run_dir / "sample_manifest.json"
    sample_records = json.loads(sample_json_path.read_text(encoding="utf-8"))
    for record in sample_records:
        record["interest_tags"] = []
    sample_json_path.write_text(json.dumps(sample_records, ensure_ascii=False) + "\n", encoding="utf-8")
    for csv_name in ("sample_manifest.csv", "final_research_users.csv"):
        csv_path = run_dir / csv_name
        rows = _read_csv(csv_path)
        for row in rows:
            row["interest_tags"] = "[]"
        _write_csv(csv_path, list(rows[0]), rows)

    users_path = run_dir / "final_research_users.json"
    users_document = json.loads(users_path.read_text(encoding="utf-8"))
    users_document["schema_version"] = "final-research-ranking-users-v4"
    users_document["links"] = payload["downloads"]
    users_document["users"] = payload["users"]
    users_path.write_text(json.dumps(users_document, ensure_ascii=False) + "\n", encoding="utf-8")
    payload_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")

    manifest_path = run_dir / "artifact_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["manifest_version"] = "final-research-ranking-runtime-v2"
    manifest.pop("evidence_state")
    for field_name in V5_DECISION_SUMMARY_FIELDS:
        if field_name != "live_api_triggered":
            manifest.pop(field_name, None)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False) + "\n", encoding="utf-8")

    config_path = run_dir / "config_snapshot.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["provider"]["prompt_version"] = "jinjiang-green-marketing-prompt-v2"
    config_path.write_text(json.dumps(config, ensure_ascii=False) + "\n", encoding="utf-8")
    summary_path = run_dir / "ranking_runtime_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["runtime_version"] = "final-research-ranking-runtime-v2"
    summary["provider_metadata"]["prompt_version"] = "jinjiang-green-marketing-prompt-v2"
    summary.pop("evidence_state")
    for field_name in V5_DECISION_SUMMARY_FIELDS:
        summary.pop(field_name, None)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False) + "\n", encoding="utf-8")
    diagnostics_path = run_dir / "ranking_diagnostics.json"
    diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    diagnostics["schema_version"] = "ranking-diagnostics-v1"
    diagnostics["summary"]["schema_version"] = "ranking-diagnostics-summary-v1"
    diagnostics["historical_top20_diagnostic"].pop("target_aggregate_engagement_reference", None)
    diagnostics_path.write_text(json.dumps(diagnostics, ensure_ascii=False) + "\n", encoding="utf-8")
    holdout_path = run_dir / "top20_holdout_diagnostic.json"
    holdout = json.loads(holdout_path.read_text(encoding="utf-8"))
    holdout.pop("target_aggregate_engagement_reference", None)
    holdout_path.write_text(json.dumps(holdout, ensure_ascii=False) + "\n", encoding="utf-8")
    diagnostics_summary_path = run_dir / "ranking_diagnostics_summary.json"
    diagnostics_summary = json.loads(diagnostics_summary_path.read_text(encoding="utf-8"))
    diagnostics_summary["schema_version"] = "ranking-diagnostics-summary-v1"
    diagnostics_summary_path.write_text(json.dumps(diagnostics_summary, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def test_seed_first_v4_rebuild_preserves_historical_interest_contract(tmp_path: Path) -> None:
    dataset_dir = _make_target_delivery_fixture(tmp_path)
    run_dir = FinalResearchRunner(
        FinalResearchConfig(
            dataset_dir=dataset_dir,
            sample_size=70,
            provider=ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False),
        ),
        _TargetDeliveryAdapter(),
    ).run_and_write(tmp_path / "ranking-historical-v4")
    _convert_seed_first_v5_run_to_historical_v4(run_dir)
    payload_path = run_dir / "final_research_report_payload.json"

    assert rebuild_final_research_report(run_dir) == run_dir / "report.html"
    rebuilt = FinalResearchRankingReportPayload.model_validate_json(payload_path.read_text(encoding="utf-8"))
    assert rebuilt.schema_version == "final-research-ranking-report-payload-v4"
    assert all(user.interest_tags == [] for user in rebuilt.users)
    assert "interest_tags" in {definition.field_name for definition in rebuilt.field_lineage_catalog}
    historical_diagnostic = cast(
        dict[str, object],
        rebuilt.ranking_diagnostics["historical_top20_diagnostic"],
    )
    assert "target_aggregate_engagement_reference" not in historical_diagnostic
    assert "target_aggregate_engagement_reference" not in json.loads(
        (run_dir / "top20_holdout_diagnostic.json").read_text(encoding="utf-8")
    )
    report_html = (run_dir / "report.html").read_text(encoding="utf-8")
    assert "interest_tags" in report_html
    assert 'data-testid="target-aggregate-engagement-reference"' not in report_html


def test_seed_first_v4_rebuild_rejects_v2_target_aggregate_reference(tmp_path: Path) -> None:
    dataset_dir = _make_target_delivery_fixture(tmp_path)
    run_dir = FinalResearchRunner(
        FinalResearchConfig(
            dataset_dir=dataset_dir,
            sample_size=70,
            provider=ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False),
        ),
        _TargetDeliveryAdapter(),
    ).run_and_write(tmp_path / "ranking-v4-crossed-holdout-reference")
    reference = json.loads((run_dir / "top20_holdout_diagnostic.json").read_text(encoding="utf-8"))[
        "target_aggregate_engagement_reference"
    ]
    _convert_seed_first_v5_run_to_historical_v4(run_dir)
    holdout_path = run_dir / "top20_holdout_diagnostic.json"
    holdout = json.loads(holdout_path.read_text(encoding="utf-8"))
    holdout["target_aggregate_engagement_reference"] = reference
    holdout_path.write_text(json.dumps(holdout, ensure_ascii=False) + "\n", encoding="utf-8")
    diagnostics_path = run_dir / "ranking_diagnostics.json"
    diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    diagnostics["historical_top20_diagnostic"]["target_aggregate_engagement_reference"] = reference
    diagnostics_path.write_text(json.dumps(diagnostics, ensure_ascii=False) + "\n", encoding="utf-8")
    payload_path = run_dir / "final_research_report_payload.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    payload["ranking_diagnostics"]["historical_top20_diagnostic"]["target_aggregate_engagement_reference"] = reference
    payload_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="ranking-diagnostics-v1 cannot contain target aggregate engagement reference"):
        rebuild_final_research_report(run_dir)


def _convert_seed_first_v5_run_to_historical_v3(run_dir: Path) -> dict[str, Any]:
    payload_path = run_dir / "final_research_report_payload.json"
    payload_document = json.loads(payload_path.read_text(encoding="utf-8"))
    payload_document["schema_version"] = "final-research-ranking-report-payload-v3"
    payload_document.pop("evidence_state")
    payload_document["ranking_diagnostics"]["historical_top20_diagnostic"].pop(
        "target_aggregate_engagement_reference",
        None,
    )
    payload_document["field_lineage"].append(
        {
            "field_name": "interest_tags",
            "provenance": "Historical Behavioral Evidence",
            "usage_stages": ["LLM Prompt", "Report Only"],
        }
    )
    payload_document["ranking_diagnostics"]["schema_version"] = "ranking-diagnostics-v1"
    payload_document["ranking_diagnostics"]["summary"]["schema_version"] = "ranking-diagnostics-summary-v1"
    payload_document["prompt_contract"]["allowed_profile_fields"].append("interest_tags")
    payload_document["run"]["sampling_method"] = "network_augmented_research_sample"
    payload_document["run"]["sampling_status"] = "historical_network_augmented_run"
    payload_document.pop("sample_role_counts")
    payload_document.pop("field_lineage_catalog")
    payload_document.pop("user_field_trace_index")
    for field_name in (
        "field_lineage_catalog",
        "user_field_trace",
        "field_source_records",
        *V5_DECISION_DOWNLOAD_FIELDS,
    ):
        payload_document["downloads"].pop(field_name)

    users = payload_document["users"]
    cohort_user = next(user for user in users if not user["is_seed"])
    cohort_user_id = cohort_user["user_id"]
    replaced_base_user_id = "historical-base-user-replaced"
    scope_counts: dict[str, int] = {}
    seed_user_ids: list[str] = []
    for user in users:
        user["interest_tags"] = []
        user["in_base_sample"] = user["user_id"] != cohort_user_id
        user["is_network_cohort"] = user["user_id"] == cohort_user_id
        user["sample_role"] = (
            "seed" if user["is_seed"] else "network_cohort" if user["is_network_cohort"] else "ordinary"
        )
        scope = user["sample_source_scope"]
        scope_counts[scope] = scope_counts.get(scope, 0) + 1
        if user["is_seed"]:
            seed_user_ids.append(user["user_id"])
    user_ids = [user["user_id"] for user in users]
    base_user_ids = [user_id for user_id in user_ids if user_id != cohort_user_id] + [replaced_base_user_id]
    payload_document["sample_comparison"] = {
        "base_sample_count": len(base_user_ids),
        "final_sample_count": len(user_ids),
        "seed_count": len(seed_user_ids),
        "network_cohort_count": 1,
        "network_cohort_added_count": 1,
        "replacement_count": 1,
        "base_source_scope_counts": dict(sorted(scope_counts.items())),
        "final_source_scope_counts": dict(sorted(scope_counts.items())),
        "ordinary_count": 0,
    }
    payload_path.write_text(json.dumps(payload_document, ensure_ascii=False) + "\n", encoding="utf-8")

    manifest_path = run_dir / "artifact_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["manifest_version"] = "final-research-ranking-runtime-v2"
    manifest.pop("evidence_state")
    seed_audit_path = run_dir / manifest["artifacts"].pop("seed_first_sample_audit")
    seed_audit_path.unlink()
    manifest["artifacts"]["network_augmented_sample_audit"] = "network_augmented_sample_audit.json"
    for artifact_name in ("field_lineage_catalog", "user_field_trace", "field_source_records"):
        (run_dir / manifest["artifacts"].pop(artifact_name)).unlink()
    for field_name in (
        "sampling_method",
        "sampling_status",
        "sample_role_counts",
        *V5_DECISION_SUMMARY_FIELDS,
    ):
        if field_name != "live_api_triggered":
            manifest.pop(field_name, None)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False) + "\n", encoding="utf-8")

    historical_audit = {
        "schema_version": "network-augmented-sample-audit-v1",
        "base_sample": {
            "count": len(base_user_ids),
            "user_ids": base_user_ids,
            "source_scope_counts": dict(sorted(scope_counts.items())),
        },
        "seed_count": len(seed_user_ids),
        "seed_user_ids": seed_user_ids,
        "network_cohort": {
            "count": 1,
            "user_ids": [cohort_user_id],
            "added_user_ids": [cohort_user_id],
        },
        "ordinary_replacement": {"count": 1},
        "final_sample": {
            "count": len(user_ids),
            "user_ids": user_ids,
            "source_scope_counts": dict(sorted(scope_counts.items())),
        },
    }
    (run_dir / "network_augmented_sample_audit.json").write_text(
        json.dumps(historical_audit, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    for file_name in ("config_snapshot.json", "holdout_safe_audit.json", "ranking_runtime_summary.json"):
        document_path = run_dir / file_name
        document = json.loads(document_path.read_text(encoding="utf-8"))
        document.pop("sampling_method", None)
        document.pop("sampling_status", None)
        if file_name == "config_snapshot.json":
            document["provider"]["prompt_version"] = "jinjiang-green-marketing-prompt-v2"
        if file_name == "ranking_runtime_summary.json":
            document["runtime_version"] = "final-research-ranking-runtime-v2"
            document["provider_metadata"]["prompt_version"] = "jinjiang-green-marketing-prompt-v2"
            document.pop("evidence_state")
            for field_name in V5_DECISION_SUMMARY_FIELDS:
                document.pop(field_name, None)
        document_path.write_text(json.dumps(document, ensure_ascii=False) + "\n", encoding="utf-8")

    diagnostics_path = run_dir / "ranking_diagnostics.json"
    diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    diagnostics["schema_version"] = "ranking-diagnostics-v1"
    diagnostics["summary"]["schema_version"] = "ranking-diagnostics-summary-v1"
    diagnostics["historical_top20_diagnostic"].pop("target_aggregate_engagement_reference", None)
    diagnostics_path.write_text(json.dumps(diagnostics, ensure_ascii=False) + "\n", encoding="utf-8")
    holdout_path = run_dir / "top20_holdout_diagnostic.json"
    holdout = json.loads(holdout_path.read_text(encoding="utf-8"))
    holdout.pop("target_aggregate_engagement_reference", None)
    holdout_path.write_text(json.dumps(holdout, ensure_ascii=False) + "\n", encoding="utf-8")
    diagnostics_summary_path = run_dir / "ranking_diagnostics_summary.json"
    diagnostics_summary = json.loads(diagnostics_summary_path.read_text(encoding="utf-8"))
    diagnostics_summary["schema_version"] = "ranking-diagnostics-summary-v1"
    diagnostics_summary_path.write_text(json.dumps(diagnostics_summary, ensure_ascii=False) + "\n", encoding="utf-8")

    users_path = run_dir / "final_research_users.json"
    users_document = json.loads(users_path.read_text(encoding="utf-8"))
    users_document["schema_version"] = "final-research-ranking-users-v3"
    users_document["links"] = payload_document["downloads"]
    users_document["users"] = payload_document["users"]
    users_path.write_text(json.dumps(users_document, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def test_historical_network_augmented_v3_rebuild_preserves_legacy_artifact_contract(tmp_path: Path) -> None:
    dataset_dir = _make_target_delivery_fixture(tmp_path)
    provider_config = ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False)
    run_dir = FinalResearchRunner(
        FinalResearchConfig(dataset_dir=dataset_dir, sample_size=70, provider=provider_config),
        _TargetDeliveryAdapter(),
    ).run_and_write(tmp_path / "ranking-legacy-v3")
    manifest = _convert_seed_first_v5_run_to_historical_v3(run_dir)
    payload_path = run_dir / "final_research_report_payload.json"

    assert rebuild_final_research_report(run_dir) == run_dir / "report.html"
    first_payload = payload_path.read_bytes()
    first_report = (run_dir / "report.html").read_bytes()
    assert rebuild_final_research_report(run_dir) == run_dir / "report.html"
    assert payload_path.read_bytes() == first_payload
    assert (run_dir / "report.html").read_bytes() == first_report

    rebuilt_document = json.loads(first_payload)
    payload = FinalResearchRankingReportPayloadV3.model_validate(rebuilt_document)
    html = first_report.decode()

    assert payload.run.sampling_method == "network_augmented_research_sample"
    assert payload.run.sampling_status == "historical_network_augmented_run"
    assert payload.sample_comparison.network_cohort_count == 1
    assert payload.sample_comparison.network_cohort_added_count == 1
    assert payload.sample_comparison.replacement_count == 1
    cohort_user = next(user for user in payload.users if user.is_network_cohort)
    assert cohort_user.sample_role == "network_cohort"
    assert cohort_user.in_base_sample is False
    assert "Historical Network-Augmented Run" in html
    assert rebuilt_document["schema_version"] == "final-research-ranking-report-payload-v3"
    assert "field_lineage_catalog" not in rebuilt_document
    assert "user_field_trace_index" not in rebuilt_document
    assert "network_augmented_sample_audit" in manifest["artifacts"]
    historical_diagnostic = cast(
        dict[str, object],
        payload.ranking_diagnostics["historical_top20_diagnostic"],
    )
    assert "target_aggregate_engagement_reference" not in historical_diagnostic
    assert "target_aggregate_engagement_reference" not in json.loads(
        (run_dir / "top20_holdout_diagnostic.json").read_text(encoding="utf-8")
    )
    assert 'data-testid="target-aggregate-engagement-reference"' not in html
    assert all(
        name not in manifest["artifacts"]
        for name in ("seed_first_sample_audit", "field_lineage_catalog", "user_field_trace", "field_source_records")
    )


def test_historical_v3_rebuild_rejects_explicit_null_sampling_fields(tmp_path: Path) -> None:
    dataset_dir = _make_target_delivery_fixture(tmp_path)
    provider_config = ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False)
    source_run = FinalResearchRunner(
        FinalResearchConfig(dataset_dir=dataset_dir, sample_size=70, provider=provider_config),
        _TargetDeliveryAdapter(),
    ).run_and_write(tmp_path / "historical-v3-source")
    _convert_seed_first_v5_run_to_historical_v3(source_run)
    matrix = (
        ("artifact_manifest.json", "sampling_method", "manifest_sampling_method"),
        ("artifact_manifest.json", "sampling_status", "manifest_sampling_status"),
        ("ranking_runtime_summary.json", "sampling_method", "summary_sampling_method"),
        ("ranking_runtime_summary.json", "sampling_status", "summary_sampling_status"),
        ("network_augmented_sample_audit.json", "sampling_method", "audit_sampling_method"),
        ("network_augmented_sample_audit.json", "sampling_status", "audit_sampling_status"),
    )

    for file_name, field_name, expected_component in matrix:
        run_dir = tmp_path / f"historical-v3-null-{file_name}-{field_name}"
        shutil.copytree(source_run, run_dir)
        document_path = run_dir / file_name
        document = json.loads(document_path.read_text(encoding="utf-8"))
        document[field_name] = None
        document_path.write_text(json.dumps(document, ensure_ascii=False) + "\n", encoding="utf-8")
        payload_path = run_dir / "final_research_report_payload.json"
        report_path = run_dir / "report.html"
        persisted_payload = payload_path.read_bytes()
        persisted_report = report_path.read_bytes()

        with pytest.raises(
            ValueError,
            match=rf"Target Delivery Ranking rebuild contract mismatch: .*{expected_component}",
        ):
            rebuild_final_research_report(run_dir)

        assert payload_path.read_bytes() == persisted_payload, (file_name, field_name)
        assert report_path.read_bytes() == persisted_report, (file_name, field_name)


def _corrupt_ranking_rebuild_contract(run_dir: Path, corruption: str) -> None:
    def read_document(file_name: str) -> dict[str, Any]:
        return json.loads((run_dir / file_name).read_text(encoding="utf-8"))

    def write_document(file_name: str, document: dict[str, Any]) -> None:
        (run_dir / file_name).write_text(json.dumps(document, ensure_ascii=False) + "\n", encoding="utf-8")

    if corruption == "payload_schema":
        document = read_document("final_research_report_payload.json")
        document["schema_version"] = "final-research-ranking-report-payload-v3"
        write_document("final_research_report_payload.json", document)
    elif corruption == "users_schema":
        document = read_document("final_research_users.json")
        document["schema_version"] = "final-research-ranking-users-v3"
        write_document("final_research_users.json", document)
    elif corruption == "missing_users_schema":
        (run_dir / "final_research_users.json").unlink()
    elif corruption == "manifest_runtime_schema":
        document = read_document("artifact_manifest.json")
        document["manifest_version"] = "final-research-ranking-runtime-v999"
        write_document("artifact_manifest.json", document)
    elif corruption == "summary_runtime_schema":
        document = read_document("ranking_runtime_summary.json")
        document["runtime_version"] = "final-research-ranking-runtime-v999"
        write_document("ranking_runtime_summary.json", document)
    elif corruption == "crossed_runtime_v2":
        manifest = read_document("artifact_manifest.json")
        summary = read_document("ranking_runtime_summary.json")
        manifest["manifest_version"] = "final-research-ranking-runtime-v2"
        summary["runtime_version"] = "final-research-ranking-runtime-v2"
        write_document("artifact_manifest.json", manifest)
        write_document("ranking_runtime_summary.json", summary)
    elif corruption == "diagnostics_schema":
        document = read_document("ranking_diagnostics.json")
        document["schema_version"] = "ranking-diagnostics-v999"
        write_document("ranking_diagnostics.json", document)
    elif corruption == "diagnostics_summary_schema":
        document = read_document("ranking_diagnostics_summary.json")
        document["schema_version"] = "ranking-diagnostics-summary-v999"
        write_document("ranking_diagnostics_summary.json", document)
    elif corruption == "crossed_diagnostics_v1":
        diagnostics = read_document("ranking_diagnostics.json")
        summary = read_document("ranking_diagnostics_summary.json")
        diagnostics["schema_version"] = "ranking-diagnostics-v1"
        summary["schema_version"] = "ranking-diagnostics-summary-v1"
        write_document("ranking_diagnostics.json", diagnostics)
        write_document("ranking_diagnostics_summary.json", summary)
    elif corruption == "config_prompt_schema":
        document = read_document("config_snapshot.json")
        document["provider"]["prompt_version"] = "jinjiang-green-marketing-prompt-v999"
        write_document("config_snapshot.json", document)
    elif corruption == "runtime_prompt_schema":
        document = read_document("ranking_runtime_summary.json")
        document["provider_metadata"]["prompt_version"] = "jinjiang-green-marketing-prompt-v999"
        write_document("ranking_runtime_summary.json", document)
    elif corruption == "crossed_prompt_v2":
        config = read_document("config_snapshot.json")
        summary = read_document("ranking_runtime_summary.json")
        config["provider"]["prompt_version"] = "jinjiang-green-marketing-prompt-v2"
        summary["provider_metadata"]["prompt_version"] = "jinjiang-green-marketing-prompt-v2"
        write_document("config_snapshot.json", config)
        write_document("ranking_runtime_summary.json", summary)
    elif corruption == "sample_audit_schema":
        document = read_document("seed_first_sample_audit.json")
        document["schema_version"] = "network-augmented-sample-audit-v1"
        write_document("seed_first_sample_audit.json", document)
    elif corruption == "missing_sample_audit":
        (run_dir / "seed_first_sample_audit.json").unlink()
    elif corruption == "crossed_sample_audit_artifact":
        document = read_document("artifact_manifest.json")
        document["artifacts"].pop("seed_first_sample_audit")
        document["artifacts"]["network_augmented_sample_audit"] = "network_augmented_sample_audit.json"
        write_document("artifact_manifest.json", document)
    elif corruption in {"sampling_method", "sampling_status"}:
        crossed_value = (
            "network_augmented_research_sample"
            if corruption == "sampling_method"
            else "historical_network_augmented_run"
        )
        payload = read_document("final_research_report_payload.json")
        manifest = read_document("artifact_manifest.json")
        summary = read_document("ranking_runtime_summary.json")
        audit = read_document("seed_first_sample_audit.json")
        payload["run"][corruption] = crossed_value
        for document in (manifest, summary, audit):
            document[corruption] = crossed_value
        write_document("final_research_report_payload.json", payload)
        write_document("artifact_manifest.json", manifest)
        write_document("ranking_runtime_summary.json", summary)
        write_document("seed_first_sample_audit.json", audit)
    elif corruption == "extra_artifact":
        document = read_document("artifact_manifest.json")
        document["artifacts"]["unexpected"] = "report.html"
        write_document("artifact_manifest.json", document)
    elif corruption == "wrong_artifact_path":
        document = read_document("artifact_manifest.json")
        document["artifacts"]["final_research_users_csv"] = "users-v999.csv"
        write_document("artifact_manifest.json", document)
    else:  # pragma: no cover - test matrix owns the values
        raise AssertionError(f"unknown contract corruption: {corruption}")


def test_ranking_rebuild_contract_rejects_unknown_missing_and_crossed_evidence(tmp_path: Path) -> None:
    dataset_dir = _make_target_delivery_fixture(tmp_path)
    provider_config = ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False)
    source_run = FinalResearchRunner(
        FinalResearchConfig(dataset_dir=dataset_dir, sample_size=70, provider=provider_config),
        _TargetDeliveryAdapter(),
    ).run_and_write(tmp_path / "ranking-contract-source")
    matrix = {
        "payload_schema": "payload_schema",
        "users_schema": "users_schema",
        "missing_users_schema": "users_schema",
        "manifest_runtime_schema": "manifest_runtime_schema",
        "summary_runtime_schema": "summary_runtime_schema",
        "crossed_runtime_v2": "manifest_runtime_schema",
        "diagnostics_schema": "diagnostics_schema",
        "diagnostics_summary_schema": "diagnostics_summary_schema",
        "crossed_diagnostics_v1": "diagnostics_schema",
        "config_prompt_schema": "config_prompt_schema",
        "runtime_prompt_schema": "runtime_prompt_schema",
        "crossed_prompt_v2": "config_prompt_schema",
        "sample_audit_schema": "sample_audit_schema",
        "missing_sample_audit": "sample_audit_schema",
        "crossed_sample_audit_artifact": "sample_audit_artifact",
        "sampling_method": "payload_sampling_method",
        "sampling_status": "payload_sampling_status",
        "extra_artifact": "artifact_set",
        "wrong_artifact_path": "artifact_set",
    }

    for corruption, expected_component in matrix.items():
        run_dir = tmp_path / f"ranking-contract-{corruption}"
        shutil.copytree(source_run, run_dir)
        _corrupt_ranking_rebuild_contract(run_dir, corruption)
        payload_path = run_dir / "final_research_report_payload.json"
        report_path = run_dir / "report.html"
        persisted_payload = payload_path.read_bytes()
        persisted_report = report_path.read_bytes()

        with pytest.raises(
            ValueError,
            match=rf"Target Delivery Ranking rebuild contract mismatch: .*{expected_component}",
        ):
            rebuild_final_research_report(run_dir)

        assert payload_path.read_bytes() == persisted_payload, corruption
        assert report_path.read_bytes() == persisted_report, corruption


@pytest.mark.parametrize("file_name", ["artifact_manifest.json", "ranking_runtime_summary.json"])
def test_v5_rebuild_rejects_cross_document_decision_evidence_mismatch(tmp_path: Path, file_name: str) -> None:
    dataset_dir = _make_target_delivery_fixture(tmp_path)
    source_run = FinalResearchRunner(
        FinalResearchConfig(
            dataset_dir=dataset_dir,
            sample_size=70,
            provider=ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False),
        ),
        _TargetDeliveryAdapter(),
    ).run_and_write(tmp_path / "ranking-v5-evidence-source")
    run_dir = tmp_path / f"ranking-v5-evidence-{file_name}"
    shutil.copytree(source_run, run_dir)
    evidence_path = run_dir / file_name
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["evidence_state"]["decision_execution_evidence"]["decision_source_counts"]["provider"] += 1
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False) + "\n", encoding="utf-8")
    payload_path = run_dir / "final_research_report_payload.json"
    report_path = run_dir / "report.html"
    persisted_payload = payload_path.read_bytes()
    persisted_report = report_path.read_bytes()

    with pytest.raises(ValueError, match="does not match ranking report v5 validation evidence"):
        rebuild_final_research_report(run_dir)

    assert payload_path.read_bytes() == persisted_payload
    assert report_path.read_bytes() == persisted_report


@pytest.mark.parametrize(
    ("artifact_name", "mutate", "expected_error"),
    [
        (
            "runtime_decisions.csv",
            lambda rows: rows[0].__setitem__("decision_source", "tampered_source"),
            "decision_source_counts does not match runtime rows",
        ),
        (
            "runtime_actions.csv",
            lambda rows: rows[0].__setitem__("action", "comment"),
            "Decision and action row disagree",
        ),
        (
            "ranking_runtime_outcomes.csv",
            lambda rows: rows[0].__setitem__("result_status", "provider_failed"),
            "does not match its outcome",
        ),
    ],
)
def test_v5_rebuild_recomputes_decision_evidence_from_runtime_rows(
    tmp_path: Path,
    artifact_name: str,
    mutate,
    expected_error: str,
) -> None:
    dataset_dir = _make_target_delivery_fixture(tmp_path)
    run_dir = FinalResearchRunner(
        FinalResearchConfig(
            dataset_dir=dataset_dir,
            sample_size=70,
            provider=ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False),
        ),
        _TargetDeliveryAdapter(),
    ).run_and_write(tmp_path / f"ranking-v5-row-evidence-{artifact_name}")
    artifact_path = run_dir / artifact_name
    rows = _read_csv(artifact_path)
    mutate(rows)
    _write_csv(artifact_path, list(rows[0]), rows)
    payload_path = run_dir / "final_research_report_payload.json"
    report_path = run_dir / "report.html"
    persisted_payload = payload_path.read_bytes()
    persisted_report = report_path.read_bytes()

    with pytest.raises(ValueError, match=expected_error):
        rebuild_final_research_report(run_dir)

    assert payload_path.read_bytes() == persisted_payload
    assert report_path.read_bytes() == persisted_report


def test_v5_rebuild_rejects_missing_payload_evidence_without_publish(tmp_path: Path) -> None:
    dataset_dir = _make_target_delivery_fixture(tmp_path)
    run_dir = FinalResearchRunner(
        FinalResearchConfig(
            dataset_dir=dataset_dir,
            sample_size=70,
            provider=ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False),
        ),
        _TargetDeliveryAdapter(),
    ).run_and_write(tmp_path / "ranking-v5-missing-payload-evidence")
    payload_path = run_dir / "final_research_report_payload.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    payload.pop("evidence_state")
    payload_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    report_path = run_dir / "report.html"
    persisted_payload = payload_path.read_bytes()
    persisted_report = report_path.read_bytes()

    with pytest.raises(ValueError, match="evidence_state"):
        rebuild_final_research_report(run_dir)

    assert payload_path.read_bytes() == persisted_payload
    assert report_path.read_bytes() == persisted_report


def test_v5_rebuild_rejects_incomplete_nested_payload_evidence_without_publish(tmp_path: Path) -> None:
    dataset_dir = _make_target_delivery_fixture(tmp_path)
    source_run = FinalResearchRunner(
        FinalResearchConfig(
            dataset_dir=dataset_dir,
            sample_size=70,
            provider=ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False),
        ),
        _TargetDeliveryAdapter(),
    ).run_and_write(tmp_path / "ranking-v5-incomplete-payload-evidence-source")

    for corruption, expected_field in (
        ("empty_evidence_state", "schema_version"),
        ("missing_nested_field", "formal_research_evidence"),
    ):
        run_dir = tmp_path / f"ranking-v5-{corruption}"
        shutil.copytree(source_run, run_dir)
        payload_path = run_dir / "final_research_report_payload.json"
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        if corruption == "empty_evidence_state":
            payload["evidence_state"] = {}
        else:
            payload["evidence_state"]["decision_execution_evidence"].pop("formal_research_evidence")
        payload_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
        report_path = run_dir / "report.html"
        persisted_payload = payload_path.read_bytes()
        persisted_report = report_path.read_bytes()

        with pytest.raises(ValueError, match=expected_field):
            rebuild_final_research_report(run_dir)

        assert payload_path.read_bytes() == persisted_payload
        assert report_path.read_bytes() == persisted_report


def test_v5_rebuild_rejects_coerced_target_aggregate_reference_values(tmp_path: Path) -> None:
    dataset_dir = _make_target_delivery_fixture(tmp_path)
    source_run = FinalResearchRunner(
        FinalResearchConfig(
            dataset_dir=dataset_dir,
            sample_size=70,
            provider=ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False),
        ),
        _TargetDeliveryAdapter(),
    ).run_and_write(tmp_path / "ranking-v5-strict-reference-source")

    for case_number, (field_name, invalid_value, expected_error) in enumerate(
        (
            ("like_count", "1.0", "like_count"),
            ("comment_count", 2.0, "comment_count"),
            ("real_exposure_denominator_available", 0, "real_exposure_denominator_available"),
            ("diagnostic_only", 1, "diagnostic_only"),
            ("real_exposure_denominator_available", True, "diagnostic-only and non-comparable"),
            ("diagnostic_only", False, "diagnostic-only and non-comparable"),
        )
    ):
        run_dir = tmp_path / f"ranking-v5-strict-reference-{case_number}"
        shutil.copytree(source_run, run_dir)
        for file_name, path_parts in (
            ("top20_holdout_diagnostic.json", ("target_aggregate_engagement_reference",)),
            (
                "ranking_diagnostics.json",
                ("historical_top20_diagnostic", "target_aggregate_engagement_reference"),
            ),
            (
                "final_research_report_payload.json",
                ("ranking_diagnostics", "historical_top20_diagnostic", "target_aggregate_engagement_reference"),
            ),
        ):
            path = run_dir / file_name
            document = json.loads(path.read_text(encoding="utf-8"))
            reference = document
            for part in path_parts:
                reference = reference[part]
            reference[field_name] = invalid_value
            path.write_text(json.dumps(document, ensure_ascii=False) + "\n", encoding="utf-8")
        payload_path = run_dir / "final_research_report_payload.json"
        report_path = run_dir / "report.html"
        persisted_payload = payload_path.read_bytes()
        persisted_report = report_path.read_bytes()

        with pytest.raises(ValidationError, match=expected_error):
            rebuild_final_research_report(run_dir)

        assert payload_path.read_bytes() == persisted_payload
        assert report_path.read_bytes() == persisted_report


def test_v5_rebuild_rejects_target_aggregate_reference_that_differs_from_source_artifact(tmp_path: Path) -> None:
    dataset_dir = _make_target_delivery_fixture(tmp_path)
    source_run = FinalResearchRunner(
        FinalResearchConfig(
            dataset_dir=dataset_dir,
            sample_size=70,
            provider=ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False),
        ),
        _TargetDeliveryAdapter(),
    ).run_and_write(tmp_path / "ranking-v5-holdout-reference-source")
    run_dir = tmp_path / "ranking-v5-holdout-reference-tampered"
    shutil.copytree(source_run, run_dir)
    holdout_path = run_dir / "top20_holdout_diagnostic.json"
    holdout = json.loads(holdout_path.read_text(encoding="utf-8"))
    holdout["target_aggregate_engagement_reference"]["like_count"] += 1
    holdout_path.write_text(json.dumps(holdout, ensure_ascii=False) + "\n", encoding="utf-8")
    payload_path = run_dir / "final_research_report_payload.json"
    report_path = run_dir / "report.html"
    persisted_payload = payload_path.read_bytes()
    persisted_report = report_path.read_bytes()

    with pytest.raises(ValueError, match="target aggregate engagement reference.*source artifact"):
        rebuild_final_research_report(run_dir)

    assert payload_path.read_bytes() == persisted_payload
    assert report_path.read_bytes() == persisted_report


def test_target_delivery_ranking_report_escapes_download_paths_in_html(tmp_path: Path) -> None:
    dataset_dir = _make_target_delivery_fixture(tmp_path)
    provider_config = ProviderLLMConfig(enabled=True, model="mock-model", require_live_env=False)
    run_dir = FinalResearchRunner(
        FinalResearchConfig(dataset_dir=dataset_dir, sample_size=70, provider=provider_config),
        _TargetDeliveryAdapter(),
    ).run_and_write(tmp_path / "ranking-download-escaping")
    payload = FinalResearchRankingReportPayloadV5.model_validate_json(
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
        "duplicate_payload_user",
        "duplicate_runtime_user",
        "count_mismatch",
        "sampling_status_mismatch",
        "diagnostic_boolean_string",
        "csv_unsafe_link",
        "duplicate_source_record",
        "source_value_mismatch",
        "source_evidence_mismatch",
        "direct_source_mismatch",
        "derived_input_mismatch",
        "coverage_audit_mismatch",
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
    elif corruption == "direct_source_mismatch":
        sample_path = run_dir / "sample_manifest.json"
        sample = json.loads(sample_path.read_text(encoding="utf-8"))
        sample[0]["nickname"] = "tampered"
        sample_path.write_text(json.dumps(sample, ensure_ascii=False) + "\n", encoding="utf-8")
    elif corruption == "derived_input_mismatch":
        source_path = run_dir / "field_source_records.json"
        source = json.loads(source_path.read_text(encoding="utf-8"))
        source["records"][0]["derived_proxy_inputs"]["comment_count"] += 1
        source_path.write_text(json.dumps(source, ensure_ascii=False) + "\n", encoding="utf-8")
    elif corruption == "coverage_audit_mismatch":
        catalog_path = run_dir / "field_lineage_catalog.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        catalog["coverage_audit"]["trace_count"] += 1
        catalog_path.write_text(json.dumps(catalog, ensure_ascii=False) + "\n", encoding="utf-8")
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

    FinalResearchRunner(
        FinalResearchConfig(
            dataset_dir=dataset_dir,
            sample_size=4,
            provider=provider_config,
        ),
        provider,
    ).run_and_write(tmp_path / "ranking-prompt-runtime")

    assert client.requests
    prompt_text = json.dumps(client.requests, ensure_ascii=False)
    assert "邻居曝光：0；邻居互动：0；互动比例：0.00" in prompt_text
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


def test_final_research_report_uses_configured_formula_without_jinjiang_interest_projection(tmp_path: Path) -> None:
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
    assert json.loads(next(row for row in report_rows if row["user_id"] == "u1")["interest_tags"]) == []


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

    expected_error = ValueError if research_model is FinalResearchModel.TARGET_DELIVERY_RANKING_V2 else AssertionError
    expected_message = (
        "unsupported Final Research decision adapter"
        if research_model is FinalResearchModel.TARGET_DELIVERY_RANKING_V2
        else "adapter programming defect"
    )
    with pytest.raises(expected_error, match=expected_message):
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

    with pytest.raises(ValidationError, match="jinjiang-green-marketing-prompt-v3"):
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
