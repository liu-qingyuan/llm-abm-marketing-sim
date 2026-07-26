from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest

from llm_abm_sim import ConcurrentMessageExperimentConfig, ConcurrentMessageExperimentRunner
from llm_abm_sim.concurrent_message_experiment import authoritative_message_definitions
from llm_abm_sim.decision import (
    CachedDecisionAdapter,
    DecisionInput,
    EngageDecision,
    InMemoryDecisionCache,
    LLMDecisionAdapter,
    ProviderDecisionError,
)
from llm_abm_sim.final_research import TARGET_VIDEO_ID
from llm_abm_sim.prompt_field_summary import (
    CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
    CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
)
from llm_abm_sim.prompting import build_engagement_prompt
from llm_abm_sim.providers.openai_compatible import OpenAICompatibleDecisionAdapter, ProviderResponseEnvelope
from llm_abm_sim.schemas import PeerContext, PlatformContext, PostContent, ProviderLLMConfig, UserProfile

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
        prompt_version: str,
        positive_user_ids: set[str],
        fail_pairs: set[tuple[int, str, str]],
        model: str = "capture-model",
    ) -> None:
        self.name = name
        self.prompt_version = prompt_version
        self.positive_user_ids = positive_user_ids
        self.fail_pairs = fail_pairs
        self.request_invocations = 0
        self.safe_metadata = {
            "adapter": "scripted_concurrent",
            "provider": "mocked_concurrent",
            "model": model,
            "timeout_seconds": 0.1,
            "max_retries": 0,
            "prompt_version": prompt_version,
        }
        self.calls: list[dict[str, object]] = []

    def decide(
        self,
        post: PostContent,
        profile: UserProfile,
        peer_context: PeerContext,
        platform_context: PlatformContext | None = None,
        time_step: int = 0,
    ) -> EngageDecision:
        self.request_invocations += 1
        decision_input = DecisionInput(
            post=post,
            profile=profile,
            peer_context=peer_context,
            platform_context=platform_context or PlatformContext(),
            time_step=time_step,
            prompt_version=self.prompt_version,
        )
        prompt_messages = build_engagement_prompt(decision_input)
        self.calls.append(
            {
                "time_step": time_step,
                "message_id": post.post_id,
                "user_id": profile.user_id,
                "peer_context": peer_context,
                "platform_context": platform_context,
                "cache_key": decision_input.cache_key(),
                "prompt_messages": prompt_messages,
                "prompt_text": "\n".join(message["content"] for message in prompt_messages),
                "profile_payload": profile.model_dump(mode="json"),
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
                provider_metadata={
                    "adapter": "scripted_concurrent",
                    "model": self.safe_metadata["model"],
                    "prompt_version": self.prompt_version,
                },
            )
        return EngageDecision(
            engage=False,
            probability=0.08,
            reason=f"{self.name} ignore",
            confidence=0.88,
            action="ignore",
            decision_source=f"{self.name}_deterministic",
            provider_metadata={
                "adapter": "scripted_concurrent",
                "model": self.safe_metadata["model"],
                "prompt_version": self.prompt_version,
            },
        )


class _SequencedEnvelopeClient:
    def __init__(self, responses: list[ProviderResponseEnvelope | Exception]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[list[dict[str, str]], str]] = []

    def create_response(self, messages: list[dict[str, str]], model: str) -> ProviderResponseEnvelope:
        self.calls.append((messages, model))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


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


def _make_concurrent_fixture(tmp_path: Path, *, user_count: int = 30, seed_user_count: int = 10) -> Path:
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
        for number in range(1, min(user_count, seed_user_count) + 1)
    ]
    if user_count >= 11:
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


def _concurrent_prompt_profile(*, user_id: str, shadow: bool) -> UserProfile:
    payload: dict[str, object] = {
        "user_id": user_id,
        "activity_score": 0.5,
        "global_influence_score": 0.9,
        "local_influence_score": 0.4,
        "concurrent_environmental_consciousness_coef": 1.0,
        "concurrent_epistemic_value_weight": 0.1,
        "concurrent_environmental_value_weight": 0.8,
        "concurrent_functional_value_weight": 0.4,
        "concurrent_health_value_weight": 0.7,
        "concurrent_emotional_value_weight": 0.2,
        "concurrent_social_value_weight": 0.3,
        "concurrent_hotel_class": "midscale",
        "concurrent_travel_purpose": "leisure",
    }
    if shadow:
        payload.update(
            {
                "concurrent_gender": "female",
                "concurrent_age": "age_26_35",
                "concurrent_education": "bachelor",
                "concurrent_monthly_income": "income_8001_15000",
            }
        )
    return UserProfile.model_validate(payload)


def _provider_response(
    decision_text: str,
    *,
    observed_model: str = "shared-requested-model",
    usage_status: str = "complete",
    input_usage: int = 12,
    output_usage: int = 6,
) -> ProviderResponseEnvelope:
    return ProviderResponseEnvelope(
        decision_text=decision_text,
        observed_model=observed_model,
        observed_model_status="reported",
        usage_status=usage_status,
        input_tokens=input_usage if usage_status == "complete" else None,
        output_tokens=output_usage if usage_status == "complete" else None,
        total_tokens=(input_usage + output_usage) if usage_status == "complete" else None,
        cached_input_tokens=3 if usage_status == "complete" else None,
    )


def test_concurrent_message_runner_writes_validation_runtime_artifacts(tmp_path: Path) -> None:
    dataset_dir = _make_concurrent_fixture(tmp_path)
    primary_adapter = _ScriptedConcurrentAdapter(
        name="primary",
        prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
        positive_user_ids={"u1"},
        fail_pairs={(0, "message_3", "u4")},
    )
    shadow_adapter = _ScriptedConcurrentAdapter(
        name="shadow",
        prompt_version=CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
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
    assert validation["prompt_contract"]["primary"]["prompt_version"] == CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION
    assert validation["prompt_contract"]["shadow"]["prompt_version"] == CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION
    assert validation["variant_provider_accounting"]["primary"]["invocations"] == 60
    assert validation["variant_provider_accounting"]["shadow"]["invocations"] == 60
    assert validation["variant_provider_accounting"]["total"]["responses"] == 118
    assert "validation-only" in report_html
    assert "cannot be deployed" in report_html
    assert "Prompt Contract" in report_html
    assert "Provider Accounting" in report_html

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
    primary_prompt = primary_adapter.calls[0]["prompt_text"]
    shadow_prompt = shadow_adapter.calls[0]["prompt_text"]
    assert "Synthetic Experiment Labels（额外人口学对照）" not in primary_prompt
    assert "User 1" not in primary_prompt
    assert "Bio 1" not in primary_prompt
    assert "性别标签" not in primary_prompt
    assert "平台热门话题" not in primary_prompt
    assert "邻居曝光：0；邻居互动：0；互动比例：0.00" in primary_prompt
    assert "Synthetic Experiment Labels（额外人口学对照）" in shadow_prompt
    assert "性别标签：女性" in shadow_prompt
    assert "不得据此推断人格" in shadow_prompt

    first_pair_id = pair_rows[0]["pair_id"]
    primary_terminal = next(row for row in terminal_rows if row["pair_id"] == first_pair_id and row["decision_variant"] == "primary")
    shadow_terminal = next(row for row in terminal_rows if row["pair_id"] == first_pair_id and row["decision_variant"] == "shadow")
    assert primary_terminal["prompt_version"] == CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION
    assert shadow_terminal["prompt_version"] == CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION
    assert primary_terminal["cache_key"] != shadow_terminal["cache_key"]
    primary_profile_payload = json.loads(primary_terminal["context_profile_payload"])
    shadow_profile_payload = json.loads(shadow_terminal["context_profile_payload"])
    for forbidden in ("nickname", "bio", "signature", "follower_count", "concurrent_gender"):
        assert forbidden not in primary_profile_payload
    for included in ("concurrent_gender", "concurrent_age", "concurrent_education", "concurrent_monthly_income"):
        assert included in shadow_profile_payload
    primary_inclusion = json.loads(primary_terminal["prompt_field_inclusion"])
    shadow_inclusion = json.loads(shadow_terminal["prompt_field_inclusion"])
    assert "concurrent_gender" not in primary_inclusion
    assert shadow_inclusion["concurrent_gender"] == "included"
    assert json.loads(primary_terminal["peer_context_payload"]) == {
        "engaged_neighbors": 0,
        "exposed_neighbors": 0,
        "influential_engaged_neighbors": 0,
        "visible_likes": 0,
        "visible_comments": 0,
        "visible_shares": 0,
    }


def test_concurrent_cached_variants_do_not_cross_hit_between_prompt_tokens() -> None:
    post = authoritative_message_definitions()[0].as_post()
    primary_leaf = _ScriptedConcurrentAdapter(
        name="primary",
        prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
        positive_user_ids=set(),
        fail_pairs=set(),
    )
    shadow_leaf = _ScriptedConcurrentAdapter(
        name="shadow",
        prompt_version=CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
        positive_user_ids=set(),
        fail_pairs=set(),
    )
    primary = CachedDecisionAdapter(
        primary_leaf,
        InMemoryDecisionCache(),
        prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
    )
    shadow = CachedDecisionAdapter(
        shadow_leaf,
        InMemoryDecisionCache(),
        prompt_version=CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
    )

    for _ in range(2):
        primary.decide(post, _concurrent_prompt_profile(user_id="u1", shadow=False), PeerContext(), PlatformContext(), 0)
        shadow.decide(post, _concurrent_prompt_profile(user_id="u1", shadow=True), PeerContext(), PlatformContext(), 0)

    assert len(primary_leaf.calls) == 1
    assert len(shadow_leaf.calls) == 1
    assert set(primary.cache.decisions) != set(shadow.cache.decisions)


def test_concurrent_message_runner_rejects_mismatched_adapter_contracts(tmp_path: Path) -> None:
    dataset_dir = _make_concurrent_fixture(tmp_path)
    config = ConcurrentMessageExperimentConfig(
        dataset_dir=dataset_dir,
        sample_size=30,
        horizon=2,
        delivery_capacity=10,
        configuration_profile="validation",
    )

    with pytest.raises(ValueError, match="provider/model/timeout/retry/sampling"):
        ConcurrentMessageExperimentRunner(
            config,
            _ScriptedConcurrentAdapter(
                name="primary",
                prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
                positive_user_ids=set(),
                fail_pairs=set(),
                model="model-a",
            ),
            _ScriptedConcurrentAdapter(
                name="shadow",
                prompt_version=CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
                positive_user_ids=set(),
                fail_pairs=set(),
                model="model-b",
            ),
        )

    with pytest.raises(ValueError, match="primary adapter prompt_version"):
        ConcurrentMessageExperimentRunner(
            config,
            _ScriptedConcurrentAdapter(
                name="primary",
                prompt_version=CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
                positive_user_ids=set(),
                fail_pairs=set(),
            ),
            _ScriptedConcurrentAdapter(
                name="shadow",
                prompt_version=CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
                positive_user_ids=set(),
                fail_pairs=set(),
            ),
        )


def test_concurrent_message_runner_fails_closed_on_observed_model_mismatch(tmp_path: Path) -> None:
    dataset_dir = _make_concurrent_fixture(tmp_path, user_count=3, seed_user_count=1)
    config = ConcurrentMessageExperimentConfig(
        dataset_dir=dataset_dir,
        sample_size=3,
        horizon=1,
        delivery_capacity=1,
        configuration_profile="validation",
    )
    primary_client = _SequencedEnvelopeClient(
        [
            _provider_response('{"engage": false, "probability": 0.1, "reason": "mismatch", "confidence": 0.9, "action": "ignore"}', observed_model="other-observed-model"),
            _provider_response('{"engage": false, "probability": 0.1, "reason": "mismatch", "confidence": 0.9, "action": "ignore"}', observed_model="other-observed-model"),
            _provider_response('{"engage": false, "probability": 0.1, "reason": "mismatch", "confidence": 0.9, "action": "ignore"}', observed_model="other-observed-model"),
        ]
    )
    shadow_client = _SequencedEnvelopeClient(
        [
            _provider_response('{"engage": false, "probability": 0.1, "reason": "shadow", "confidence": 0.9, "action": "ignore"}', observed_model="shared-requested-model"),
            _provider_response('{"engage": false, "probability": 0.1, "reason": "shadow", "confidence": 0.9, "action": "ignore"}', observed_model="shared-requested-model"),
            _provider_response('{"engage": false, "probability": 0.1, "reason": "shadow", "confidence": 0.9, "action": "ignore"}', observed_model="shared-requested-model"),
        ]
    )
    primary_provider = OpenAICompatibleDecisionAdapter(
        ProviderLLMConfig(
            enabled=True,
            provider="mocked_openai_compatible",
            model="shared-requested-model",
            require_live_env=False,
            prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
        ),
        client=primary_client,
        sleep=lambda _delay: None,
    )
    shadow_provider = OpenAICompatibleDecisionAdapter(
        ProviderLLMConfig(
            enabled=True,
            provider="mocked_openai_compatible",
            model="shared-requested-model",
            require_live_env=False,
            prompt_version=CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
        ),
        client=shadow_client,
        sleep=lambda _delay: None,
    )

    run_dir = tmp_path / "observed-model-mismatch"
    with pytest.raises(ValueError, match="observed model mismatch"):
        ConcurrentMessageExperimentRunner(config, primary_provider, shadow_provider).run_and_write(run_dir)

    assert run_dir.exists()
    assert not any(run_dir.iterdir())


def test_concurrent_message_runner_accounts_provider_retries_without_estimating_missing_usage(tmp_path: Path) -> None:
    dataset_dir = _make_concurrent_fixture(tmp_path, user_count=3, seed_user_count=1)
    config = ConcurrentMessageExperimentConfig(
        dataset_dir=dataset_dir,
        sample_size=3,
        horizon=1,
        delivery_capacity=1,
        configuration_profile="validation",
    )
    primary_client = _SequencedEnvelopeClient(
        [
            _provider_response('{"unexpected": true}', usage_status="missing"),
            _provider_response('{"engage": false, "probability": 0.2, "reason": "retry success", "confidence": 0.9, "action": "ignore"}', input_usage=10, output_usage=5),
            _provider_response('{"engage": false, "probability": 0.1, "reason": "steady", "confidence": 0.9, "action": "ignore"}', input_usage=9, output_usage=4),
            _provider_response('{"engage": false, "probability": 0.1, "reason": "steady", "confidence": 0.9, "action": "ignore"}', input_usage=8, output_usage=4),
        ]
    )
    shadow_client = _SequencedEnvelopeClient(
        [
            _provider_response('{"engage": false, "probability": 0.1, "reason": "shadow", "confidence": 0.9, "action": "ignore"}', input_usage=7, output_usage=3),
            _provider_response('{"engage": false, "probability": 0.1, "reason": "shadow", "confidence": 0.9, "action": "ignore"}', input_usage=7, output_usage=3),
            _provider_response('{"engage": false, "probability": 0.1, "reason": "shadow", "confidence": 0.9, "action": "ignore"}', input_usage=7, output_usage=3),
        ]
    )
    primary_provider = OpenAICompatibleDecisionAdapter(
        ProviderLLMConfig(
            enabled=True,
            provider="mocked_openai_compatible",
            model="shared-requested-model",
            require_live_env=False,
            prompt_version=CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
            max_retries=1,
        ),
        client=primary_client,
        sleep=lambda _delay: None,
    )
    shadow_provider = OpenAICompatibleDecisionAdapter(
        ProviderLLMConfig(
            enabled=True,
            provider="mocked_openai_compatible",
            model="shared-requested-model",
            require_live_env=False,
            prompt_version=CONCURRENT_MESSAGE_SHADOW_PROMPT_VERSION,
            max_retries=1,
        ),
        client=shadow_client,
        sleep=lambda _delay: None,
    )

    output_dir = ConcurrentMessageExperimentRunner(config, primary_provider, shadow_provider).run_and_write(
        tmp_path / "concurrent-provider-run"
    )

    validation = json.loads((output_dir / "concurrent_validation.json").read_text(encoding="utf-8"))
    terminal_rows = _read_csv(output_dir / "concurrent_runtime_terminal_rows.csv")

    primary_accounting = validation["variant_provider_accounting"]["primary"]
    shadow_accounting = validation["variant_provider_accounting"]["shadow"]
    total_accounting = validation["variant_provider_accounting"]["total"]
    assert primary_accounting["invocations"] == 4
    assert primary_accounting["responses"] == 4
    assert primary_accounting["successful_decisions"] == 3
    assert primary_accounting["usage_complete_attempts"] == 2
    assert primary_accounting["usage_incomplete_attempts"] == 1
    assert primary_accounting["input_usage"] == 17
    assert primary_accounting["output_usage"] == 8
    assert primary_accounting["total_usage"] == 25
    assert shadow_accounting["invocations"] == 3
    assert shadow_accounting["responses"] == 3
    assert shadow_accounting["successful_decisions"] == 3
    assert shadow_accounting["usage_complete_attempts"] == 3
    assert total_accounting["invocations"] == 7
    assert total_accounting["responses"] == 7
    assert total_accounting["successful_decisions"] == 6

    first_primary_row = next(
        row
        for row in terminal_rows
        if row["decision_variant"] == "primary" and row["message_id"] == "message_1"
    )
    assert first_primary_row["request_invocations"] == "2"
    assert first_primary_row["provider_response_count"] == "2"
    assert first_primary_row["successful_decision_count"] == "1"
    assert first_primary_row["usage_complete"] == "false"
    assert first_primary_row["input_usage"] == ""
    assert first_primary_row["total_usage"] == ""

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
