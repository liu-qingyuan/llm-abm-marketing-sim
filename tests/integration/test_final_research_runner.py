from __future__ import annotations

import csv
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from llm_abm_sim import FinalResearchConfig, FinalResearchRunner, rebuild_final_research_report
from llm_abm_sim.decision import EngageDecision, LLMDecisionAdapter
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
                "interest_tags": json.dumps(["hotel", f"scope-{number % 2}"], ensure_ascii=False),
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
        "final_research_report": "report.html",
        "final_research_report_payload": "final_research_report_payload.json",
        "final_research_users_csv": "final_research_users.csv",
        "final_research_users_json": "final_research_users.json",
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
    offline_report_rows = _read_csv(first_output / "final_research_users.csv")
    assert len(offline_report_rows) == 4
    assert {row["result_status"] for row in offline_report_rows} == {"runtime_not_run"}
    assert {row["provider_status"] for row in offline_report_rows} == {"runtime_not_run"}

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
    offline_payload = json.loads((first_output / "final_research_report_payload.json").read_text(encoding="utf-8"))
    offline_html = (first_output / "report.html").read_text(encoding="utf-8")
    assert offline_payload["video_usage"]["runtime_target_video_count"] == 0
    assert offline_payload["batch_explanation"]["batch_count"] == 0
    assert "runtime 未启用" in offline_payload["video_usage"]["target_video_role"]
    assert "runtime 未启用" in offline_payload["batch_explanation"]["assignment_method"]
    assert "Batch 0 为 seeds" not in offline_html
    assert "30 个固定推荐批次" not in offline_html
    assert "<dt>推荐批次</dt><dd>未执行</dd>" in offline_html
    for relative_path in manifest["artifacts"].values():
        assert (first_output / relative_path).read_bytes() == (second_output / relative_path).read_bytes()


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
    assert "data-testid=\"final-research-report\"" in report_html
    assert "final_research_users.csv" in report_html
    assert "final_research_users.json" in report_html
    assert "artifact_manifest.json" in report_html
    assert 'data-testid="funnel-section"' in report_html
    assert 'data-testid="recommendation-section"' in report_html
    assert 'data-testid="decision-section"' in report_html

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
        FinalResearchConfig(dataset_dir=dataset_dir, sample_size=4, provider=provider_config),
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
        FinalResearchConfig(dataset_dir=dataset_dir, sample_size=4, provider=provider_config),
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
        FinalResearchConfig(dataset_dir=dataset_dir, sample_size=4, provider=provider_config),
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
        FinalResearchConfig(dataset_dir=dataset_dir, sample_size=4, provider=provider_config),
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
        FinalResearchConfig(dataset_dir=dataset_dir, sample_size=4, provider=provider_config),
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
    output = FinalResearchRunner(
        FinalResearchConfig(
            dataset_dir=dataset_dir,
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
    assert json.loads(report_rows[0]["interest_tags"])[0] == "hotel"


def test_final_research_does_not_convert_unexpected_adapter_errors_to_provider_failures(tmp_path: Path) -> None:
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
        sample_size=4,
        provider=ProviderLLMConfig(enabled=True, require_live_env=False),
    )

    with pytest.raises(AssertionError, match="adapter programming defect"):
        FinalResearchRunner(config, UnexpectedFailureAdapter()).run_and_write(tmp_path / "failed-runtime")

    assert not (tmp_path / "failed-runtime" / "artifact_manifest.json").exists()


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
