from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_abm_sim.decision import EngageDecision, LLMDecisionAdapter
from llm_abm_sim.providers.openai_compatible import OpenAICompatibleDecisionAdapter
from llm_abm_sim.runner import ExperimentRunner, load_simulation_input
from llm_abm_sim.schemas import (
    HotelClassLabel,
    LatentAttributes,
    LatentProfileLabels,
    LatentValueWeights,
    PeerContext,
    PlatformContext,
    PostContent,
    ProviderLLMConfig,
    SimulationConfig,
    SimulationInput,
    TravelPurposeLabel,
    UserProfile,
    ValueDimensions,
)


class AlwaysLikeAdapter(LLMDecisionAdapter):
    def decide(
        self,
        post: PostContent,
        profile: UserProfile,
        peer_context: PeerContext,
        platform_context: PlatformContext | None = None,
        time_step: int = 0,
    ) -> EngageDecision:
        return EngageDecision(
            engage=True,
            probability=0.99,
            reason="mocked_provider",
            confidence=1.0,
            action="like",
            decision_source="provider",
            provider_metadata={
                "provider": "mock",
                "model": "mock-model",
                "base_url": "https://user:pass@example.test/v1?api_key=secret",
                "headers": {"authorization": "Bearer sk-secret"},
                "raw_provider_response": {"token": "sk-secret"},
                "adapter": "mock",
                "adapter_version": "test-v1",
                "wire_api": "responses",
                "prompt_version": "mock-v1",
            },
        )


class PromptV2SequencedClient:
    def __init__(self) -> None:
        self.calls: list[tuple[list[dict[str, str]], str]] = []
        self.responses = [
            {"engage": True, "probability": 0.81, "reason": "comment fit", "confidence": 0.93, "action": "comment"},
            {"engage": False, "probability": 0.12, "reason": "low fit", "confidence": 0.88, "action": "ignore"},
            {"engage": True, "probability": 0.76, "reason": "like fit", "confidence": 0.9, "action": "like"},
            {"engage": True, "probability": 0.84, "reason": "share fit", "confidence": 0.91, "action": "share"},
        ]

    def create_response(self, messages: list[dict[str, str]], model: str) -> dict[str, object]:
        self.calls.append((messages, model))
        return self.responses[len(self.calls) - 1]


def test_mocked_provider_adapter_runs_through_experiment_runner():
    config = load_simulation_input(Path("configs/default.yaml"))
    runner = ExperimentRunner(config, decision_adapter=AlwaysLikeAdapter())

    result = runner.run()

    assert result.metrics_summary["final_engaged"] == 3
    assert all(event.decision.reason == "mocked_provider" for event in result.decision_events)


def test_provider_skip_run_config_fails_before_partial_simulation():
    config = load_simulation_input(Path("configs/default.yaml"))
    config = config.model_copy(
        update={
            "provider_llm": config.provider_llm.model_copy(update={"enabled": True, "fail_closed_action": "skip_run"})
        }
    )
    runner = ExperimentRunner(config)

    with pytest.raises(RuntimeError, match="skip_run"):
        runner.run()


def test_mocked_provider_run_writes_allowlisted_redacted_artifacts(tmp_path: Path):
    config = load_simulation_input(Path("configs/default.yaml"))
    config = config.model_copy(update={"provider_llm": config.provider_llm.model_copy(update={"enabled": True})})
    output_dir = tmp_path / "mock-provider"

    ExperimentRunner(config, decision_adapter=AlwaysLikeAdapter()).run_and_write(output_dir)

    metrics = json.loads((output_dir / "metrics_summary.json").read_text())
    assert metrics["decision_source_summary"]["provider"] > 0
    evidence = metrics["provider_evidence"]
    assert evidence["provider_decision_count"] > 0
    assert evidence["provider_metadata"]["base_url"] == "https://example.test/v1"
    artifact_text = "\n".join(path.read_text(errors="ignore") for path in output_dir.iterdir() if path.is_file())
    lowered = artifact_text.lower()
    assert "sk-secret" not in lowered
    assert "authorization" not in lowered
    assert "raw_provider_response" not in lowered
    assert "headers" not in lowered
    assert "provider-backed decision observed" in (output_dir / "report.html").read_text(encoding="utf-8")


def test_jinjiang_prompt_v2_mocked_provider_runs_end_to_end(tmp_path: Path):
    client = PromptV2SequencedClient()
    provider_config = ProviderLLMConfig(
        enabled=True,
        provider="mocked_openai_compatible",
        model="mock-jinjiang-prompt-v2",
        base_url="https://user:pass@example.test/v1?api_key=secret",
        require_live_env=True,
    )
    adapter = OpenAICompatibleDecisionAdapter(provider_config, client=client)
    output_dir = tmp_path / "runs" / "jinjiang-prompt-v2-mock-20260708T000000Z"

    runner = ExperimentRunner(_jinjiang_prompt_v2_config(provider_config), decision_adapter=adapter)
    output_path = runner.run_and_write(output_dir)

    assert output_path == output_dir
    assert len(client.calls) == 4
    assert {model for _, model in client.calls} == {"mock-jinjiang-prompt-v2"}

    prompt_text = "\n".join(message["content"] for messages, _ in client.calls for message in messages)
    assert "锦江酒店集团使用秸秆制品、推进环保举措的绿色营销内容" in prompt_text
    assert "【营销内容】" in prompt_text
    assert "【内容主要强调的价值】" in prompt_text
    assert "【用户可观测特征】" in prompt_text
    assert "【用户消费偏好】" in prompt_text
    assert "【其他用户行为】" in prompt_text
    assert "全平台影响力" in prompt_text
    assert "锦江酒店社群内的局部影响力" in prompt_text
    assert "环保意识倾向" in prompt_text
    assert "秸秆制品相关消费价值" in prompt_text
    assert "最近一次入住锦江旗下酒店类型" in prompt_text
    assert "最近一次入住锦江旗下酒店目的" in prompt_text
    for forbidden in (
        "brand_attitude",
        "like_tendency",
        "comment_tendency",
        "share_tendency",
        "latent_class",
        "age_26_35",
        "bachelor",
        "income_8001_15000",
        "raw_prompt",
        "api_key",
    ):
        assert forbidden not in prompt_text

    run_result = json.loads((output_dir / "run_result.json").read_text())
    decision_actions = {
        event["user_id"]: event["decision"]["action"]
        for step in run_result["step_records"]
        for event in step["decision_events"]
    }
    assert decision_actions == {
        "u_comment": "comment",
        "u_ignore": "ignore",
        "u_like": "like",
        "u_share": "share",
    }
    action_events = [
        event
        for step in run_result["step_records"]
        for event in step["action_events"]
    ]
    assert {event["action"] for event in action_events} == {"comment", "like", "share"}
    assert all(event["user_id"] != "u_ignore" for event in action_events)
    trace_profiles = [
        event["trace_summary"]["input"]["profile"]
        for step in run_result["step_records"]
        for event in step["decision_events"]
    ]
    for profile in trace_profiles:
        for removed_field in ("brand_attitude", "like_tendency", "comment_tendency", "share_tendency"):
            assert removed_field not in profile

    metrics = json.loads((output_dir / "metrics_summary.json").read_text())
    assert metrics["final_engaged"] == 3
    assert metrics["comment_count"] == 1
    assert metrics["like_count"] == 1
    assert metrics["share_count"] == 1
    assert metrics["decision_source_summary"] == {"provider": 4}
    evidence = metrics["provider_evidence"]
    assert evidence["provider_decision_count"] == 4
    assert evidence["first_provider_decision"]["action"] == "comment"
    assert evidence["provider_metadata"]["prompt_version"] == "jinjiang-green-marketing-prompt-v2"
    assert evidence["provider_metadata"]["base_url"] == "https://example.test/v1"
    assert output_dir.parent.name == "runs"
    assert output_dir.name.startswith("jinjiang-prompt-v2-mock-")

    report_payload = json.loads((output_dir / "report_payload.json").read_text())
    report_decision_actions = {
        event["decision"]["action"]
        for step in report_payload["trend"]
        for event in step["decision_events"]
    }
    report_action_events = [
        event
        for step in report_payload["trend"]
        for event in step["action_events"]
    ]
    assert report_decision_actions == {"comment", "ignore", "like", "share"}
    assert {event["action"] for event in report_action_events} == {"comment", "like", "share"}

    artifact_text = "\n".join(path.read_text(errors="ignore") for path in output_dir.iterdir() if path.is_file())
    lowered = artifact_text.lower()
    for forbidden in (
        "sk-secret",
        "authorization",
        "raw_prompt",
        "raw_provider_response",
        "headers",
        "user:pass",
        "api_key=secret",
        "brand_attitude",
        "like_tendency",
        "comment_tendency",
        "share_tendency",
    ):
        assert forbidden not in lowered
    assert "provider-backed decision observed" in (output_dir / "report.html").read_text(encoding="utf-8")


def _jinjiang_prompt_v2_config(provider_config: ProviderLLMConfig) -> SimulationInput:
    return SimulationInput(
        run_id="jinjiang-prompt-v2-mock-test",
        random_seed=20260708,
        simulation=SimulationConfig(
            horizon=1,
            seed_user_ids=["u_comment", "u_ignore", "u_like", "u_share"],
            base_exposure_probability=0.0,
            peer_exposure_boost=0.0,
            hot_topic_exposure_boost=0.0,
            share_exposure_boost=0.0,
            time_step_label="day",
            observation_window="mocked Prompt v2 smoke",
        ),
        platform_context=PlatformContext(
            time_label="绿色营销上线周",
            hot_topics=["锦江酒店", "环保"],
            platform_mood="用户正在讨论酒店环保用品",
            feed_ranking_weight=1.0,
            trace_visibility=1.0,
        ),
        post=PostContent(
            post_id="jinjiang-green-straw-campaign",
            text="锦江酒店集团推广秸秆制品客房用品，展示减少一次性塑料和推进绿色住宿体验的营销内容。",
            media_summary="短视频展示客房内秸秆制品洗漱用品和环保提示卡。",
            topic_tags=["锦江酒店", "环保", "秸秆制品"],
            value_dimensions=ValueDimensions(
                epistemic=0.35,
                environmental=0.95,
                functional=0.62,
                health=0.22,
                emotional=0.48,
                social=0.3,
            ),
        ),
        profiles=[
            _jinjiang_profile("u_comment", ["锦江酒店", "环保讨论"], 0.74, 0.52, 0.61, "midscale", "business"),
            _jinjiang_profile("u_ignore", ["游戏", "短剧"], 0.21, 0.16, 0.12, "economy", "leisure"),
            _jinjiang_profile("u_like", ["绿色旅行", "酒店体验"], 0.68, 0.44, 0.39, "economy", "leisure"),
            _jinjiang_profile("u_share", ["可持续消费", "商务差旅"], 0.83, 0.71, 0.66, "upper_midscale", "business"),
        ],
        graph_edges=[
            ("u_comment", "u_ignore"),
            ("u_like", "u_share"),
        ],
        provider_llm=provider_config,
    )


def _jinjiang_profile(
    user_id: str,
    interest_tags: list[str],
    activity_score: float,
    global_influence_score: float,
    local_influence_score: float,
    hotel_class: HotelClassLabel,
    travel_purpose: TravelPurposeLabel,
) -> UserProfile:
    return UserProfile.model_validate(
        {
            "user_id": user_id,
            "interest_tags": interest_tags,
            "activity_score": activity_score,
            "global_influence_score": global_influence_score,
            "local_influence_score": local_influence_score,
            "brand_attitude": 0.99,
            "like_tendency": 0.99,
            "comment_tendency": 0.99,
            "share_tendency": 0.99,
            "latent_attributes": LatentAttributes(
                spec_id="jinjiang_user_latent_attributes_v1",
                method="latent_class_exact_quota_v1",
                seed=20260630,
                latent_class="class_1",
                environmental_consciousness_coef=0.86,
                value_weights=LatentValueWeights(
                    epistemic=0.32,
                    environmental=0.91,
                    functional=0.64,
                    health=0.28,
                    emotional=0.5,
                    social=0.37,
                ),
                profile_labels=LatentProfileLabels(
                    hotel_class=hotel_class,
                    travel_purpose=travel_purpose,
                    gender="female",
                    age="age_26_35",
                    education="bachelor",
                    monthly_income="income_8001_15000",
                ),
            ),
        }
    )
